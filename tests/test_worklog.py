from email.message import EmailMessage
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mail_jira_assistant import worklog
from mail_jira_assistant.ai import FakeRunner
from mail_jira_assistant.document_access import read
from mail_jira_assistant.service import enqueue, sync, worker
from mail_jira_assistant.storage import connect
from mail_jira_assistant.web import create_app

KB = Path(__file__).parent / "fixtures/kb"


def put_mail(folder, name, body, reply=None):
    folder.mkdir(exist_ok=True, parents=True)
    m = EmailMessage()
    m["From"] = "me@example.test"
    m["To"] = "you@example.test"
    m["Subject"] = "검증"
    m["Message-ID"] = f"<{name.encode().hex()}@test>"
    m["Date"] = "Mon, 02 Nov 2026 10:00:00 +0900"
    if reply:
        m["In-Reply-To"] = "<" + reply.split("@")[0][1:].encode().hex() + "@test>"
    m.set_content(body)
    (folder / (name + ".eml")).write_bytes(m.as_bytes())


def record(**extra):
    return dict(
        description="실제 검증 수행",
        performed_on="2026-11-02",
        project="GPIO",
        status="confirmed",
        **extra,
    )


def test_full_link_reclassification_edit_export_backup(tmp_path):
    root = tmp_path / "한글 공백"
    inbox = root / "in"
    sent = root / "sent"
    runtime = root / "state"
    put_mail(inbox, "request", "검증 후 회신 부탁드립니다.")
    sync(runtime, inbox, history_only=False)
    enqueue(runtime)
    worker(runtime, FakeRunner(), KB)
    db = connect(runtime)
    iid = db.execute("SELECT id FROM inquiries").fetchone()[0]
    task = db.execute("SELECT id FROM actions").fetchone()[0]
    put_mail(sent, "promise", "검증하겠습니다.", "<request@test>")
    sync(runtime, inbox, sent=sent, history_only=False)
    enqueue(runtime)
    worker(runtime, FakeRunner(), KB)
    assert not worklog.records(runtime)
    put_mail(sent, "performed", "검증 완료 후 결과를 전달했습니다.", "<request@test>")
    sync(runtime, inbox, sent=sent, history_only=False)
    enqueue(runtime)
    worker(runtime, FakeRunner(), KB)
    proposals = worklog.records(runtime)
    assert len(proposals) == 1 and proposals[0]["performed_on"] is None
    assert proposals[0]["source_date"] and proposals[0]["collected_at"]
    aid = proposals[0]["id"]
    client = TestClient(create_app(runtime, KB))
    data = record(inquiry_id=iid, action_id=task, complete_action=True, version=1)
    assert client.put(f"/api/activities/{aid}", json=data).status_code == 200
    assert (
        db.execute("SELECT state FROM actions WHERE id=?", (task,)).fetchone()[0]
        == "done"
    )
    from mail_jira_assistant.contracts import Classification
    from mail_jira_assistant.worklog import capture

    row = db.execute("SELECT * FROM classification_history ORDER BY id DESC").fetchone()
    with db:
        capture(
            db,
            iid,
            row["revision_id"],
            Classification.model_validate_json(row["result"]),
        )
    assert len(worklog.records(runtime)) == 1
    assert worklog.records(runtime)[0]["description"] == "실제 검증 수행"
    assert client.put(f"/api/activities/{aid}", json=data).status_code == 409
    assert client.get(f"/api/activities/{aid}/history").json()["edits"]
    dest = tmp_path / "Obsidian 한글" / "2026-11-02.md"
    dest.parent.mkdir()
    dest.write_text("# 내 메모\n유지할 내용\n", encoding="utf-8")
    worklog.export(runtime, "2026-11-02", dest)
    before = dest.read_text(encoding="utf-8")
    worklog.export(runtime, "2026-11-02", dest)
    assert (
        dest.read_text(encoding="utf-8") == before
        and before.count("실제 검증 수행") == 1
    )
    assert "유지할 내용" in before
    from mail_jira_assistant.operations import backup, restore

    backup(runtime, tmp_path / "backup")
    restore(tmp_path / "backup", tmp_path / "restored")
    assert worklog.records(tmp_path / "restored")[0]["description"] == "실제 검증 수행"
    for url in [
        "/today",
        "/worklog",
        "/projects",
        f"/worklog?edit={aid}",
        f"/inquiries/{iid}",
    ]:
        assert client.get(url).status_code == 200
    db.close()


def test_duplicate_cross_source_and_manual_preservation(tmp_path):
    a = worklog.save(tmp_path, record())
    b = worklog.save(tmp_path, record(duplicate_of=a))
    assert worklog.markdown(tmp_path, "2026-11-02").count("실제 검증 수행") == 1
    assert len(worklog.records(tmp_path)) == 2
    with pytest.raises(ValueError):
        worklog.save(tmp_path, record(duplicate_of=b, version=1), a)
    with pytest.raises(ValueError):
        worklog.save(tmp_path, dict(description="未確認", status="confirmed"))


def test_markdown_import_is_explicit_idempotent_and_generated_rejected(tmp_path):
    runtime = tmp_path / "state"
    path = tmp_path / "旧 업무.md"
    path.write_text("# 업무\n- 수행 기록", encoding="utf-8")
    worklog.import_markdown(runtime, path, "2026-11-01", "고객")
    with pytest.raises(ValueError):
        worklog.import_markdown(runtime, path, "2026-11-01")
    copy = tmp_path / "copy.md"
    copy.write_bytes(path.read_bytes())
    worklog.import_markdown(runtime, copy, "2026-11-01")
    assert (
        len(worklog.records(runtime)) == 1
        and worklog.records(runtime)[0]["status"] == "needs_review"
    )
    output = worklog.export(runtime, "2026-11-01")
    with pytest.raises(ValueError):
        worklog.import_markdown(runtime, output, "2026-11-01")
    output.write_text(worklog.START + "broken", encoding="utf-8")
    with pytest.raises(ValueError):
        worklog.export(runtime, "2026-11-01")
    assert output.read_text(encoding="utf-8").endswith("broken")


def test_com_fake_timeout_recovery_and_ui_independence(tmp_path):
    f = tmp_path / "문서 공백.eml"
    put_mail(tmp_path, "문서 공백", "일반 본문")
    assert read(f)["status"] == "ready"
    empty = tmp_path / "empty.txt"
    empty.write_text("", encoding="utf-8")
    assert read(empty, "fake")["status"] == "extract_failed"
    client = TestClient(create_app(tmp_path / "state", KB))
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor() as pool:
        pending = pool.submit(read, empty, "fake_timeout", 0.3)
        assert client.get("/today").status_code == 200
        assert pending.result()["status"] == "extract_failed"
    empty.write_text("복구 후 텍스트", encoding="utf-8")
    assert read(empty, "fake")["text"].strip() == "복구 후 텍스트"


def test_v4_migration_snapshot_keeps_existing_data(tmp_path):
    db = connect(tmp_path)
    with db:
        db.execute("DELETE FROM migrations WHERE version>=5")
    db.close()
    connect(tmp_path).close()
    assert (tmp_path / "pre-migration-v4.sqlite3").exists()


def test_mail_and_jira_same_work_are_confirmed_once_with_all_evidence(tmp_path):
    from mail_jira_assistant.contracts import Action
    from mail_jira_assistant.jira import register, sync_jira

    runtime = tmp_path / "state"
    inbox = tmp_path / "sent"
    put_mail(inbox, "result", "검증 완료 후 전달했습니다.")
    sync(runtime, tmp_path / "empty", sent=inbox, history_only=False)
    servers = [
        dict(
            server_id="one",
            base_url="https://one.example.test",
            fixture=str(Path(__file__).parent / "fixtures/jira/gpio.json"),
            poll_seconds=0,
        )
    ]
    register(runtime, "https://one.example.test/browse/A-1", servers)
    sync_jira(runtime, servers, history_only=False)

    class Performed(FakeRunner):
        def classify(self, request):
            c = super().classify(request)
            c.work_performed = "yes"
            c.response_expected = "no"
            c.action_required = "no"
            c.actions = [
                Action(
                    kind="performed",
                    description="공통 검증 결과",
                    assignee="self",
                    evidence_refs=[request.source_ref + "#body"],
                )
            ]
            return c

    enqueue(runtime)
    worker(runtime, Performed(), KB)
    rows = worklog.records(runtime)
    assert len(rows) == 2
    first, second = rows
    for r in rows:
        worklog.save(
            runtime,
            dict(
                description=r["description"],
                project="공통 검증",
                performed_on="2026-11-02",
                status="confirmed",
                inquiry_id=r["inquiry_id"],
                version=1,
                duplicate_of=first["id"] if r["id"] == second["id"] else None,
            ),
            r["id"],
        )
    assert worklog.markdown(runtime, "2026-11-02").count("공통 검증 결과") == 1
    client = TestClient(create_app(runtime, KB))
    assert (
        len(client.get(f"/api/activities/{first['id']}/history").json()["evidence"])
        == 2
    )
    db = connect(runtime)
    assert {r[0] for r in db.execute("SELECT DISTINCT kind FROM sources")} == {
        "mail",
        "jira",
    }
    db.close()


def test_repeated_real_performance_in_new_message_is_not_collapsed(tmp_path):
    runtime = tmp_path / "state"
    sent = tmp_path / "sent"
    put_mail(sent, "first", "검증 완료 후 전달했습니다.")
    sync(runtime, tmp_path / "empty", sent=sent, history_only=False)
    enqueue(runtime)
    worker(runtime, FakeRunner(), KB)
    put_mail(sent, "second", "검증 완료 후 전달했습니다.", "<first@test>")
    sync(runtime, tmp_path / "empty", sent=sent, history_only=False)
    enqueue(runtime)
    worker(runtime, FakeRunner(), KB)
    assert len(worklog.records(runtime)) == 2
    assert all(r["performed_on"] is None for r in worklog.records(runtime))


def test_word_adapter_only_closes_its_document_and_always_releases_com(
    tmp_path, monkeypatch
):
    import os

    if os.name != "nt":
        pytest.skip("Windows COM contract")
    from types import SimpleNamespace

    import pythoncom
    import win32com.client

    from mail_jira_assistant.document_access import read_word

    events = []
    monkeypatch.setattr(
        pythoncom, "CoInitializeEx", lambda flags: events.append("init")
    )
    monkeypatch.setattr(pythoncom, "CoUninitialize", lambda: events.append("release"))
    path = tmp_path / "권한 문서.docx"

    class Document:
        Content = SimpleNamespace(Text="허용 프로그램의 텍스트")
        InlineShapes = SimpleNamespace(Count=1)
        Shapes = SimpleNamespace(Count=0)

        def Close(self, **kwargs):
            assert kwargs == {"SaveChanges": 0}
            events.append("close")

    class Documents:
        existing = []

        def __iter__(self):
            return iter(self.existing)

        def Open(self, path, **kwargs):
            assert kwargs["ReadOnly"] and not kwargs["AddToRecentFiles"]
            return Document()

    docs = Documents()
    monkeypatch.setattr(
        win32com.client, "GetActiveObject", lambda name: SimpleNamespace(Documents=docs)
    )
    assert read_word(path)["status"] == "partial"
    assert events == ["init", "close", "release"]
    events.clear()
    docs.existing = [SimpleNamespace(FullName=str(path))]
    with pytest.raises(ValueError, match="사용자가 열어"):
        read_word(path)
    assert events == ["init", "release"]
