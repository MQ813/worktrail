import json
from pathlib import Path

from fastapi.testclient import TestClient

from mail_jira_assistant.ai import FakeRunner
from mail_jira_assistant.rules import non_action
from mail_jira_assistant.sample_data import install, prepare
from mail_jira_assistant.service import enqueue, sync, worker
from mail_jira_assistant.settings import Settings
from mail_jira_assistant.storage import connect
from mail_jira_assistant.web import create_app


def test_requested_sample_pack_rules_intake_and_idempotency(tmp_path):
    settings = Settings(**prepare(tmp_path))
    settings.runtime = str(tmp_path / "runtime")
    install(settings.runtime, settings)
    db = connect(settings.runtime)
    assert db.execute("SELECT count(*) FROM sources").fetchone()[0] == 17
    assert (
        db.execute("SELECT count(*) FROM inquiries WHERE state='dismissed'").fetchone()[
            0
        ]
        == 10
    )
    assert db.execute("SELECT count(*) FROM classifications").fetchone()[0] == 10
    assert db.execute("SELECT count(*) FROM jobs").fetchone()[0] == 7
    assert (
        db.execute("SELECT count(*) FROM sources WHERE kind='jira'").fetchone()[0] == 3
    )
    assert (
        db.execute(
            "SELECT count(*) FROM sources WHERE kind='jira_notification'"
        ).fetchone()[0]
        == 3
    )
    img = db.execute(
        "SELECT * FROM sources WHERE subject LIKE '%캡처 해석%'"
    ).fetchone()
    assert img["coverage"] == "partial"
    attachment = json.loads(img["attachments"])[0]
    assert attachment["status"] == "needs_vision" and attachment["cid"]
    assert (Path(settings.runtime) / attachment["path"]).is_file()
    alert = db.execute(
        "SELECT * FROM sources WHERE subject LIKE '[JIRA] ESD-1234%'"
    ).fetchone()
    issue = db.execute("SELECT * FROM sources WHERE message_id='ESD-1234'").fetchone()
    assert (
        "중요한 조건을 추가" in issue["body"]
        and "중요한 조건을 추가" not in alert["body"]
    )
    api = TestClient(
        create_app(
            settings.runtime,
            settings.knowledge,
            settings.jira_servers,
            sample_mode=True,
        )
    )
    assert "/inquiries/" + issue["id"] in api.get("/inquiries/" + alert["id"]).text
    assert "합성 샘플 환경" in api.get("/").text
    # Re-install preserves bytes, source IDs and job deduplication, even a user's edited file.
    file = Path(settings.inbox) / "worktrail-samples-v1/01-ad.eml"
    original = file.read_bytes()
    prepare(tmp_path)
    install(settings.runtime, settings)
    assert file.read_bytes() == original
    assert db.execute("SELECT count(*) FROM sources").fetchone()[0] == 17
    assert db.execute("SELECT count(*) FROM jobs").fetchone()[0] == 7
    worker(settings.runtime, FakeRunner(), settings.knowledge)
    assert (
        db.execute("SELECT count(*) FROM jobs WHERE state='failed'").fetchone()[0] == 0
    )
    assert (
        db.execute(
            "SELECT count(*) FROM activities WHERE status='confirmed'"
        ).fetchone()[0]
        == 0
    )
    db.close()


def test_cc_is_not_excluded_when_a_request_names_self_or_has_no_explicit_addressee():
    args = dict(
        subject="기술 문의",
        kind="mail",
        recipients="김영수 <other@example.test>",
        cc="조민규 <me@example.test>",
        identity=["me@example.test", "조민규"],
    )
    assert (
        non_action(body="수신 : 김영수 님\n전압 조건을 확인해 주세요.", **args)[0]
        == "cc_explicit_other_addressee"
    )
    assert (
        non_action(
            body="수신 : 김영수 님\n조민규 님도 simulation을 부탁드립니다.", **args
        )
        is None
    )
    assert non_action(body="참조자를 포함해 모두 조건을 확인해 주세요.", **args) is None


def test_advertisement_subject_alone_is_a_rule_and_manual_rerun_remains_possible(
    tmp_path,
):
    from email.message import EmailMessage

    mail = EmailMessage()
    mail["From"] = "vendor@example.test"
    mail["To"] = "me@example.test"
    mail["Subject"] = "(광고) 행사"
    mail.set_content("신제품 행사 안내")
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "ad.eml").write_bytes(mail.as_bytes())
    runtime = tmp_path / "state"
    sync(runtime, inbox)
    enqueue(runtime)
    db = connect(runtime)
    sid = db.execute("SELECT id FROM inquiries").fetchone()[0]
    assert db.execute("SELECT count(*) FROM jobs").fetchone()[0] == 0
    enqueue(runtime, sid)
    assert db.execute("SELECT count(*) FROM jobs").fetchone()[0] == 1
    db.close()


def test_automatic_mail_with_a_required_action_is_not_dismissed_by_no_action_rule():
    assert (
        non_action(
            subject="권한 만료",
            body="권한 만료 전 11월 18일까지 포털에서 갱신 신청을 해 주세요.",
            kind="auto_notification",
        )
        is None
    )


def test_native_auth_wait_does_not_start_a_model_request(monkeypatch):
    from types import SimpleNamespace

    from mail_jira_assistant.ai_connection import native_openai_ready

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout="No authenticated integrations")

    monkeypatch.setattr("mail_jira_assistant.ai_connection.subprocess.run", run)
    settings = Settings(
        ai_backend="opencode",
        ai_executable="opencode.exe",
        ai_global_args=["--standalone"],
        classify_model="openai/gpt-6.1-sol-fast",
    )
    ready, status = native_openai_ready(settings)
    assert not ready and "대기" in status
    assert calls == [["opencode.exe", "--standalone", "auth", "list"]]
    monkeypatch.setattr(
        "mail_jira_assistant.ai_connection.subprocess.run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="OpenAI - connected"),
    )
    assert native_openai_ready(settings)[0]
