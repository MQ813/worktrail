import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mail_jira_assistant.ai import FakeRunner, OpenCodeRunner
from mail_jira_assistant.contracts import Request
from mail_jira_assistant.service import enqueue, sync, worker
from mail_jira_assistant.storage import connect
from mail_jira_assistant.web import create_app

INBOX = Path(__file__).parent / "fixtures/inbox"
KB = Path(__file__).parent / "fixtures/kb"


def test_end_to_end_dedup_edit_restart(tmp_path):
    inbox = tmp_path / "mail"
    shutil.copytree(INBOX, inbox)
    runtime = tmp_path / "state"
    assert sync(runtime, inbox) == 1
    shutil.copy(inbox / "gpio.eml", inbox / "moved.eml")
    assert sync(runtime, inbox) == 0
    enqueue(runtime)
    enqueue(runtime)
    assert worker(runtime, FakeRunner(), KB) == 2
    client = TestClient(create_app(runtime))
    sid = client.get("/api/inquiries").json()[0]["id"]
    assert client.get("/inquiries/" + sid).status_code == 200
    result = client.put(
        "/api/drafts/" + sid,
        json={"version": 1, "body": "사용자 수정본", "review": "reviewed"},
    )
    assert result.json()["version"] == 2
    assert (
        client.put(
            "/api/drafts/" + sid, json={"version": 1, "body": "늦은 수정"}
        ).status_code
        == 409
    )
    assert (
        client.put(
            "/api/drafts/" + sid,
            headers={"origin": "https://other.test"},
            json={"version": 2, "body": "x"},
        ).status_code
        == 403
    )
    enqueue(runtime)
    assert worker(runtime, FakeRunner(), KB) == 0
    restarted = TestClient(create_app(runtime))
    assert "사용자 수정본" in restarted.get("/inquiries/" + sid).text
    assert restarted.get("/api/inquiries").json()[0]["state"] == "needs_review"
    db = connect(runtime)
    assert db.execute("SELECT count(*) FROM sources").fetchone()[0] == 1
    assert db.execute("SELECT count(*) FROM jobs").fetchone()[0] == 2
    assert db.execute("SELECT count(*) FROM edits").fetchone()[0] == 1
    db.close()


def test_history_only_and_failure_preserve_original(tmp_path):
    assert sync(tmp_path, INBOX) == 1
    db = connect(tmp_path)
    assert db.execute("SELECT count(*) FROM jobs").fetchone()[0] == 0
    db.close()

    class Broken(FakeRunner):
        def classify(self, r):
            raise TimeoutError("synthetic timeout")

    enqueue(tmp_path)
    assert worker(tmp_path, Broken(), KB) == 0
    db = connect(tmp_path)
    assert db.execute("SELECT state FROM jobs").fetchone()[0] == "retry_wait"
    assert db.execute("SELECT error FROM attempts").fetchone()[0]
    raw = db.execute("SELECT raw_path FROM sources").fetchone()[0]
    assert (tmp_path / raw).exists()
    db.close()


def test_bad_file_does_not_stop_ingest(tmp_path):
    inbox = tmp_path / "inbox"
    shutil.copytree(INBOX, inbox)
    (inbox / "bad.eml").write_text("broken")
    assert sync(tmp_path / "runtime", inbox) == 1
    db = connect(tmp_path / "runtime")
    assert db.execute("SELECT count(*) FROM sync_errors").fetchone()[0] == 1
    db.close()


def test_invalid_evidence_and_budget_fail_without_draft(tmp_path):
    class Wrong(FakeRunner):
        def classify(self, r):
            result = super().classify(r)
            result.evidence[0].text = "invented"
            return result

    sync(tmp_path, INBOX)
    enqueue(tmp_path)
    assert worker(tmp_path, Wrong(), KB) == 0
    db = connect(tmp_path)
    assert db.execute("SELECT count(*) FROM drafts").fetchone()[0] == 0
    with db:
        db.execute("UPDATE jobs SET state='pending'")
    assert worker(tmp_path, FakeRunner(), KB, max_chars=1) == 0
    assert (
        db.execute("SELECT error FROM jobs")
        .fetchone()[0]
        .endswith("input_budget_exceeded")
    )
    db.close()


def test_expired_job_recovery(tmp_path):
    sync(tmp_path, INBOX)
    enqueue(tmp_path)
    db = connect(tmp_path)
    with db:
        db.execute("UPDATE jobs SET state='running',lease=0,token='old',attempts=1")
    db.close()
    assert worker(tmp_path, FakeRunner(), KB) == 2


def test_attachment_html_and_reply(tmp_path):
    from email.message import EmailMessage

    folder = tmp_path / "inbox"
    folder.mkdir()
    msg = EmailMessage()
    msg["From"] = "c@example.test"
    msg["To"] = "me@example.test"
    msg["Message-ID"] = "<a@test>"
    msg["Subject"] = "<script>alert(1)</script>"
    msg.set_content("문의 부탁드립니다.")
    msg.add_attachment(
        b"attachment",
        maintype="application",
        subtype="octet-stream",
        filename="../../outside",
    )
    (folder / "a.eml").write_bytes(msg.as_bytes())
    msg2 = EmailMessage()
    msg2["In-Reply-To"] = "<a@test>"
    msg2["Message-ID"] = "<b@test>"
    msg2["Subject"] = "reply"
    msg2.set_content('<img src="https://track.test">', subtype="html")
    (folder / "b.eml").write_bytes(msg2.as_bytes())
    runtime = tmp_path / "runtime"
    assert sync(runtime, folder) == 2
    db = connect(runtime)
    sources = db.execute("SELECT * FROM sources ORDER BY message_id").fetchall()
    assert sources[0]["conversation"] == sources[1]["conversation"]
    assert len(list((runtime / "blobs").iterdir())) == 3
    client = TestClient(create_app(runtime))
    assert (
        "<script>alert(1)</script>"
        not in client.get("/inquiries/" + sources[0]["id"]).text
    )
    assert "<img src=" not in client.get("/inquiries/" + sources[1]["id"]).text
    db.close()


def test_opencode_event_contract(monkeypatch):
    monkeypatch.setattr("mail_jira_assistant.ai.own_process", lambda proc: None)
    import json
    import subprocess

    result = FakeRunner().classify(
        Request(source_ref="x", subject="s", body="question")
    )

    class Process:
        returncode = 0

        def wait(self, timeout=None):
            return 0

    def run(args, **kwargs):
        assert "--continue" not in args and "--auto" not in args
        assert kwargs["shell"] is False
        kwargs["stdout"].write(
            json.dumps(
                {"type": "text", "part": {"text": result.model_dump_json()}}
            ).encode()
        )
        kwargs["stdout"].flush()
        return Process()

    monkeypatch.setattr(subprocess, "Popen", run)
    assert (
        OpenCodeRunner().classify(Request(source_ref="x", subject="s", body="question"))
        == result
    )
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: Process())
    with pytest.raises(ValueError, match="empty_output"):
        OpenCodeRunner().classify(Request(source_ref="x", subject="s", body="q"))
