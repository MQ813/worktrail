import json
from email.message import EmailMessage
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mail_jira_assistant import project_updates as pu
from mail_jira_assistant.ai import FakeRunner
from mail_jira_assistant.contracts import ProjectUpdate
from mail_jira_assistant.service import enqueue, sync, worker
from mail_jira_assistant.storage import connect
from mail_jira_assistant.web import create_app

KB = Path(__file__).parent / "fixtures/kb"


def setup(tmp_path, body="TODO: 회로 검증 요청\n결정: 수정안 A로 진행"):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    mail = EmailMessage()
    mail["From"] = "customer@example.test"
    mail["To"] = "me@example.test"
    mail["Message-ID"] = "<project@test>"
    mail["Subject"] = "SmartIO 검증"
    mail.set_content(body)
    (inbox / "one.eml").write_bytes(mail.as_bytes())
    runtime = tmp_path / "state"
    sync(runtime, inbox, history_only=False)
    db = connect(runtime)
    iid = db.execute("SELECT id FROM inquiries").fetchone()[0]
    with db:
        pid = pu.ensure_project(db, "SmartIO", "JOB-006")
        db.execute("INSERT INTO project_source_links VALUES(?,?,'user')", (iid, pid))
    db.close()
    enqueue(runtime)
    return runtime, iid, pid


def rows(runtime, sql, args=()):
    db = connect(runtime)
    try:
        return [dict(r) for r in db.execute(sql, args)]
    finally:
        db.close()


def test_automatic_independent_update_review_and_export(tmp_path):
    runtime, iid, pid = setup(tmp_path)

    class NoReply(FakeRunner):
        def classify(self, request):
            c = super().classify(request)
            c.response_expected = "no"
            c.project_update_needed = "yes"
            return c

    assert worker(runtime, NoReply(), KB) == 2
    assert not rows(runtime, "SELECT * FROM drafts")
    changes = rows(runtime, "SELECT * FROM project_changes")
    assert len(changes) == 2
    assert not rows(runtime, "SELECT * FROM project_entries")
    client = TestClient(create_app(runtime, KB))
    assert "미확정" in client.get(f"/projects/{pid}").text
    data = {"selections": [{"id": c["id"], "decision": "confirmed"} for c in changes]}
    assert client.post("/api/projects/review", json=data).status_code == 200
    assert len(rows(runtime, "SELECT * FROM project_entries")) == 2
    assert client.post("/api/projects/review", json=data).status_code == 409
    output = pu.export(runtime, pid)
    assert output.parent.name == "JOB-006"
    assert "수정안 A" in output.read_text(encoding="utf-8")
    assert not rows(runtime, "SELECT * FROM activities WHERE status='confirmed'")
    assert worker(runtime, NoReply(), KB) == 0


def test_partial_confirm_stales_remaining_and_preserves_edits(tmp_path):
    runtime, _, pid = setup(tmp_path)
    worker(runtime, FakeRunner(), KB)
    changes = rows(runtime, "SELECT * FROM project_changes")
    pu.review(
        runtime,
        [
            {
                "id": changes[0]["id"],
                "decision": "confirmed",
                "text": "사람이 수정한 내용",
            }
        ],
    )
    assert (
        rows(runtime, "SELECT text FROM project_entries")[0]["text"]
        == "사람이 수정한 내용"
    )
    assert (
        rows(
            runtime,
            "SELECT freshness FROM project_changes WHERE id=?",
            (changes[1]["id"],),
        )[0]["freshness"]
        == "stale"
    )
    with pytest.raises(ValueError, match="재검토"):
        pu.review(runtime, [{"id": changes[1]["id"], "decision": "confirmed"}])
    pu.review(runtime, [{"id": changes[1]["id"], "decision": "rejected"}])
    assert (
        rows(runtime, "SELECT version FROM projects WHERE id=?", (pid,))[0]["version"]
        == 2
    )


def test_failed_update_does_not_rollback_draft(tmp_path):
    runtime, _, _ = setup(tmp_path)

    class Broken(FakeRunner):
        def project_update(self, request):
            raise ValueError("project-invalid")

    worker(runtime, Broken(), KB)
    assert len(rows(runtime, "SELECT * FROM drafts")) == 1
    assert (
        rows(runtime, "SELECT state FROM jobs WHERE kind='project_update'")[0]["state"]
        == "failed"
    )
    assert not rows(runtime, "SELECT * FROM project_entries")


def test_no_change_and_no_update_trigger(tmp_path):
    runtime, _, _ = setup(tmp_path, "감사합니다")
    worker(runtime, FakeRunner(), KB)
    assert not rows(runtime, "SELECT * FROM project_changes")
    assert json.loads(
        rows(runtime, "SELECT result FROM project_update_runs")[0]["result"]
    )["no_change"]


def test_input_evidence_and_target_validation(tmp_path):
    runtime, _, _ = setup(tmp_path)

    class BadEvidence(FakeRunner):
        def project_update(self, request):
            result = super().project_update(request)
            result.changes[0].evidence[0].text = "없는 근거"
            return result

    worker(runtime, BadEvidence(), KB)
    assert (
        "project_invalid_evidence"
        in rows(runtime, "SELECT error FROM jobs WHERE kind='project_update'")[0][
            "error"
        ]
    )
    assert not rows(runtime, "SELECT * FROM project_changes")


def test_unassigned_and_link_schedules_update(tmp_path):
    runtime, iid, pid = setup(tmp_path)
    db = connect(runtime)
    with db:
        db.execute("DELETE FROM project_source_links")
    db.close()
    worker(runtime, FakeRunner(), KB)
    assert rows(runtime, "SELECT * FROM project_unassigned")
    client = TestClient(create_app(runtime, KB))
    assert (
        client.post(
            "/api/projects/link", json={"inquiry_id": iid, "project": "SmartIO"}
        ).status_code
        == 200
    )
    worker(runtime, FakeRunner(), KB)
    assert not rows(runtime, "SELECT * FROM project_unassigned")
    assert rows(runtime, "SELECT * FROM project_changes WHERE project_id=?", (pid,))


def test_atomic_batch_invalid_selection(tmp_path):
    runtime, _, _ = setup(tmp_path)
    worker(runtime, FakeRunner(), KB)
    c = rows(runtime, "SELECT * FROM project_changes")[0]
    with pytest.raises(ValueError):
        pu.review(
            runtime,
            [
                {"id": c["id"], "decision": "confirmed"},
                {"id": 99999, "decision": "confirmed"},
            ],
        )
    assert not rows(runtime, "SELECT * FROM project_entries")
    assert (
        rows(runtime, "SELECT review FROM project_changes WHERE id=?", (c["id"],))[0][
            "review"
        ]
        == "pending"
    )


def test_export_preserves_notes_blocks_external_edits(tmp_path):
    runtime, _, pid = setup(tmp_path)
    worker(runtime, FakeRunner(), KB)
    path = pu.export(runtime, pid)
    initial = path.read_text(encoding="utf-8")
    path.write_text("내 메모\n" + initial, encoding="utf-8")
    pu.export(runtime, pid)
    assert path.read_text(encoding="utf-8").startswith("내 메모")
    path.write_text(
        path.read_text(encoding="utf-8").replace("주요 결정", "내가 바꾼 결정"),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="생성 영역"):
        pu.export(runtime, pid)


def test_rejected_replay_not_recreated(tmp_path):
    runtime, iid, pid = setup(tmp_path)
    worker(runtime, FakeRunner(), KB)
    changes = rows(runtime, "SELECT * FROM project_changes")
    pu.review(runtime, [{"id": c["id"], "decision": "rejected"} for c in changes])
    client = TestClient(create_app(runtime, KB))
    client.post(f"/api/projects/{pid}/regenerate", json={})
    worker(runtime, FakeRunner(), KB)
    assert len(rows(runtime, "SELECT * FROM project_changes")) == 2
    assert not rows(runtime, "SELECT * FROM project_changes WHERE review='pending'")


def test_updates_disabled(tmp_path):
    runtime, _, _ = setup(tmp_path)
    assert worker(runtime, FakeRunner(), KB, automatic_project_updates=False) == 2
    assert not rows(runtime, "SELECT * FROM project_update_runs")


def test_rebase_after_partial_confirm(tmp_path):
    runtime, _, pid = setup(tmp_path)
    worker(runtime, FakeRunner(), KB)
    changes = rows(runtime, "SELECT * FROM project_changes")
    pu.review(runtime, [{"id": changes[0]["id"], "decision": "confirmed"}])
    client = TestClient(create_app(runtime, KB))
    client.post(f"/api/projects/{pid}/regenerate", json={})
    worker(runtime, FakeRunner(), KB)
    pending = rows(runtime, "SELECT * FROM project_changes WHERE review='pending'")
    assert len(pending) == 1 and pending[0]["freshness"] == "current"
    pu.review(runtime, [{"id": pending[0]["id"], "decision": "confirmed"}])
    assert len(rows(runtime, "SELECT * FROM project_entries")) == 2
    assert rows(runtime, "SELECT * FROM project_changes WHERE review='superseded'")


def test_explicit_job_link_and_ai_hint_is_only_candidate(tmp_path):
    runtime, iid, pid = setup(tmp_path, "JOB-006 TODO: 시험 요청")
    db = connect(runtime)
    with db:
        db.execute("DELETE FROM project_source_links")
    db.close()
    worker(runtime, FakeRunner(), KB)
    assert (
        rows(runtime, "SELECT origin FROM project_source_links")[0]["origin"] == "code"
    )
    assert rows(runtime, "SELECT * FROM project_changes")


def test_no_updates_does_not_queue_project_ai(tmp_path):
    runtime, _, _ = setup(tmp_path)

    class OnlyDraft(FakeRunner):
        def classify(self, request):
            c = super().classify(request)
            c.project_update_needed = "no"
            return c

    assert worker(runtime, OnlyDraft(), KB) == 2
    assert not rows(runtime, "SELECT * FROM jobs WHERE kind='project_update'")


def test_wrong_project_and_metadata_confirmation(tmp_path):
    runtime, _, pid = setup(tmp_path, "결정: 담당자는 홍길동")

    class Metadata(FakeRunner):
        def project_update(self, request):
            return ProjectUpdate(
                changes=[
                    dict(
                        project_id=pid,
                        section="overview",
                        kind="project_metadata",
                        metadata_field="owner",
                        text="홍길동",
                        evidence=[
                            dict(source_ref=request.source_ref, text="담당자는 홍길동")
                        ],
                    )
                ]
            )

    worker(runtime, Metadata(), KB)
    assert rows(runtime, "SELECT owner FROM projects")[0]["owner"] == ""
    c = rows(runtime, "SELECT * FROM project_changes")[0]
    pu.review(runtime, [{"id": c["id"], "decision": "confirmed"}])
    assert rows(runtime, "SELECT owner FROM projects")[0]["owner"] == "홍길동"


def test_import_sections_assets_and_backup_restore(tmp_path):
    from mail_jira_assistant.operations import backup, restore

    folder = tmp_path / "old" / "JOB-009"
    (folder / "issues").mkdir(parents=True)
    (folder / "assets").mkdir()
    (folder / "index.md").write_text(
        "# JOB-009 SmartIO\n\n## 주요 결정\n- A로 결정\n## 다음 액션\n- 회로 검증\n",
        encoding="utf-8",
    )
    (folder / "issues" / "issue.md").write_text(
        "# 상세\n## 주요 이슈\n- 통신 불안정\n", encoding="utf-8"
    )
    (folder / "assets" / "wave.bin").write_bytes(b"test-binary")
    runtime = tmp_path / "state"
    pid = pu.import_folder(runtime, folder)
    changes = rows(runtime, "SELECT * FROM project_changes")
    assert len(changes) == 3
    assert {json.loads(c["payload"])["section"] for c in changes} == {
        "decisions",
        "next_actions",
        "issues",
    }
    pu.review(runtime, [{"id": c["id"], "decision": "confirmed"} for c in changes])
    output = pu.export(runtime, pid)
    assert (output.parent / "assets/wave.bin").read_bytes() == b"test-binary"
    output.write_text(
        "내 메모\n" + output.read_text(encoding="utf-8"), encoding="utf-8"
    )
    backup(runtime, tmp_path / "backup")
    restored = tmp_path / "restored"
    restore(tmp_path / "backup", restored)
    assert (
        (restored / "projects/JOB-009/index.md")
        .read_text(encoding="utf-8")
        .startswith("내 메모")
    )
    assert pu.export(restored, pid).read_text(encoding="utf-8").startswith("내 메모")


def test_migration_v5_preserves_project_name_and_source(tmp_path):
    runtime, iid, pid = setup(tmp_path)
    db = connect(runtime)
    with db:
        db.execute("DELETE FROM migrations WHERE version=6")
    db.close()
    db = connect(runtime)
    assert (
        db.execute("SELECT name,code FROM projects WHERE id=?", (pid,)).fetchone()[
            "name"
        ]
        == "SmartIO"
    )
    assert db.execute("SELECT 1 FROM sources WHERE id=?", (iid,)).fetchone()
    db.close()
    assert (runtime / "pre-migration-v5.sqlite3").exists()


def test_unlink_prevents_confirm(tmp_path):
    runtime, iid, pid = setup(tmp_path)
    worker(runtime, FakeRunner(), KB)
    change = rows(runtime, "SELECT * FROM project_changes")[0]
    pu.unlink(runtime, iid, pid)
    with pytest.raises(ValueError):
        pu.review(runtime, [{"id": change["id"], "decision": "confirmed"}])


def test_source_change_while_ai_runs_is_stale(tmp_path):
    from mail_jira_assistant.service import add_revision

    runtime, iid, _ = setup(tmp_path)

    class NewSource(FakeRunner):
        def project_update(self, request):
            db = connect(runtime)
            with db:
                add_revision(db, iid, iid, dict(body="후속: 결정 변경", subject="변경"))
            db.close()
            return super().project_update(request)

    worker(runtime, NewSource(), KB)
    assert rows(runtime, "SELECT * FROM project_changes WHERE freshness='stale'")
    assert not rows(runtime, "SELECT * FROM project_entries")


def test_conflicting_proposals_require_rejection_then_regeneration(tmp_path):
    runtime, _, pid = setup(tmp_path, "일정 A 또는 일정 B 검토")
    db = connect(runtime)
    with db:
        eid = db.execute(
            "INSERT INTO project_entries(project_id,section,kind,text) VALUES(?,'progress','schedule','기존 일정')",
            (pid,),
        ).lastrowid
    db.close()

    class Changed(FakeRunner):
        value = "일정 A"

        def project_update(self, request):
            return ProjectUpdate(
                changes=[
                    dict(
                        project_id=pid,
                        section="progress",
                        kind="schedule",
                        operation="update",
                        entry_id=eid,
                        text=self.value,
                        evidence=[dict(source_ref=request.source_ref, text=self.value)],
                    )
                ]
            )

    runner = Changed()
    worker(runtime, runner, KB)
    client = TestClient(create_app(runtime, KB))
    client.post(f"/api/projects/{pid}/regenerate", json={})
    runner.value = "일정 B"
    worker(runtime, runner, KB)
    changes = rows(
        runtime, "SELECT * FROM project_changes WHERE review='pending' ORDER BY id"
    )
    assert len(changes) == 2 and all(c["freshness"] == "conflict" for c in changes)
    with pytest.raises(ValueError):
        pu.review(runtime, [{"id": changes[1]["id"], "decision": "confirmed"}])
    pu.review(runtime, [{"id": changes[0]["id"], "decision": "rejected"}])
    client.post(f"/api/projects/{pid}/regenerate", json={})
    worker(runtime, runner, KB)
    current = rows(runtime, "SELECT * FROM project_changes WHERE review='pending'")
    assert len(current) == 1 and current[0]["freshness"] == "current"
    pu.review(runtime, [{"id": current[0]["id"], "decision": "confirmed"}])
    assert (
        rows(runtime, "SELECT text FROM project_entries WHERE id=?", (eid,))[0]["text"]
        == "일정 B"
    )


def test_confirmed_waiting_reuses_action_and_is_not_automatic(tmp_path):
    runtime, _, pid = setup(tmp_path, "회신 부탁드립니다")

    class Waiting(FakeRunner):
        def classify(self, request):
            c = super().classify(request)
            c.actions[0].kind = "waiting"
            return c

        def project_update(self, request):
            return ProjectUpdate(
                changes=[
                    dict(
                        project_id=pid,
                        section="next_actions",
                        kind="waiting",
                        action_id=request.open_actions[0]["id"],
                        text="고객 회신 대기",
                        evidence=[
                            dict(
                                source_ref=request.source_ref, text="회신 부탁드립니다"
                            )
                        ],
                    )
                ]
            )

    worker(runtime, Waiting(), KB)
    assert rows(runtime, "SELECT state FROM actions")[0]["state"] == "proposed"
    c = rows(runtime, "SELECT * FROM project_changes")[0]
    pu.review(runtime, [{"id": c["id"], "decision": "confirmed"}])
    assert rows(runtime, "SELECT state FROM actions")[0]["state"] == "waiting"
    assert len(rows(runtime, "SELECT * FROM actions")) == 1


def test_external_edit_intake_preserves_original_and_pending_only(tmp_path):
    runtime, _, pid = setup(tmp_path)
    worker(runtime, FakeRunner(), KB)
    path = pu.export(runtime, pid)
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "## 주요 결정\n", "## 주요 결정\n- 사람이 추가한 결정\n"
        ),
        encoding="utf-8",
    )
    pu.import_document(runtime, pid, path)
    imported = rows(runtime, "SELECT * FROM project_changes WHERE inquiry_id IS NULL")
    assert len(imported) == 1
    assert not rows(runtime, "SELECT * FROM project_entries")
    assert json.loads(imported[0]["payload"])["text"] == "사람이 추가한 결정"
    pu.review(runtime, [{"id": imported[0]["id"], "decision": "confirmed"}])
    assert "사람이 추가한 결정" in pu.export(runtime, pid).read_text(encoding="utf-8")


def test_period_history_replay_uses_explicit_basis_and_only_target_project(tmp_path):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from mail_jira_assistant.service import add_revision

    runtime, iid, pid = setup(tmp_path)
    db = connect(runtime)
    with db:
        other = pu.ensure_project(db, "Other")
        db.execute("INSERT INTO project_source_links VALUES(?,?,'user')", (iid, other))
        db.execute("UPDATE sources SET baseline=1")
        db.execute("DELETE FROM jobs")
        add_revision(
            db, iid, iid, dict(subject="후속", body="최신 메시지, 추가 변경 없음")
        )
    db.close()
    today = datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()
    assert pu.replay_history(runtime, pid, today, today) == 2
    worker(runtime, FakeRunner(), KB)
    proposals = rows(runtime, "SELECT * FROM project_changes")
    assert proposals and {c["project_id"] for c in proposals} == {pid}
    assert all(
        json.loads(c["payload"])["_history_basis"] > c["revision_id"] for c in proposals
    )
    pu.review(runtime, [{"id": c["id"], "decision": "confirmed"} for c in proposals])
    assert rows(runtime, "SELECT * FROM project_entries")


def test_import_partial_confirm_can_regenerate_remaining(tmp_path):
    folder = tmp_path / "JOB-020"
    folder.mkdir()
    (folder / "index.md").write_text(
        "# JOB-020 기존 프로젝트\n## 주요 결정\n- A\n## 다음 액션\n- B\n",
        encoding="utf-8",
    )
    runtime = tmp_path / "state"
    pid = pu.import_folder(runtime, folder)
    proposals = rows(runtime, "SELECT * FROM project_changes")
    pu.review(runtime, [{"id": proposals[0]["id"], "decision": "confirmed"}])
    client = TestClient(create_app(runtime, KB))
    assert client.post(f"/api/projects/{pid}/regenerate", json={}).json()["queued"] == 1
    pending = rows(runtime, "SELECT * FROM project_changes WHERE review='pending'")
    assert len(pending) == 1 and pending[0]["freshness"] == "current"
    pu.review(runtime, [{"id": pending[0]["id"], "decision": "confirmed"}])
    assert len(rows(runtime, "SELECT * FROM project_entries")) == 2
