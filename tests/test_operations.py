"""Recovery, isolation, backup and security invariants (S14–15,19,21–22)."""

import sqlite3
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_tracking import mail

from mail_jira_assistant.ai import FakeRunner
from mail_jira_assistant.operations import backup, restore
from mail_jira_assistant.service import enqueue, sync, worker
from mail_jira_assistant.storage import connect
from mail_jira_assistant.web import create_app

KB = Path(__file__).parent / "fixtures/kb"


def setup(tmp_path):
    inbox = tmp_path / "in"
    runtime = tmp_path / "state"
    mail(inbox, "a", "GPIO 온도를 확인 부탁드립니다.", "<a@test>")
    sync(runtime, inbox)
    enqueue(runtime)
    return inbox, runtime


def test_transient_retry_bounded_and_other_jobs_proceed(tmp_path):
    inbox, runtime = setup(tmp_path)
    mail(inbox, "b", "두 번째 문의", "<b@test>")
    sync(runtime, inbox)
    enqueue(runtime)

    class Flaky(FakeRunner):
        def classify(self, r):
            if "GPIO" in r.body:
                raise TimeoutError("synthetic")
            return super().classify(r)

    assert worker(runtime, Flaky(), KB, retry_delay=0) == 2
    db = connect(runtime)
    assert (
        db.execute("SELECT attempts FROM jobs WHERE state='failed'").fetchone()[0] == 3
    )
    assert (
        db.execute("SELECT count(*) FROM jobs WHERE state='running'").fetchone()[0] == 0
    )
    assert db.execute("SELECT count(*) FROM drafts").fetchone()[0] == 1
    db.close()


def test_budget_large_source_isolated_from_other_inquiries(tmp_path):
    inbox, runtime = setup(tmp_path)
    mail(inbox, "huge", "X" * 40000, "<huge@test>")
    sync(runtime, inbox)
    enqueue(runtime)
    assert worker(runtime, FakeRunner(), KB) == 2
    db = connect(runtime)
    assert (
        db.execute("SELECT error FROM jobs WHERE state='failed'")
        .fetchone()[0]
        .endswith("input_budget_exceeded")
    )
    assert db.execute("SELECT count(*) FROM drafts").fetchone()[0] == 1
    db.close()


def test_heartbeat_and_exclusive_worker(tmp_path):
    _, runtime = setup(tmp_path)
    entered = threading.Event()
    release = threading.Event()

    class Slow(FakeRunner):
        def classify(self, r):
            entered.set()
            assert release.wait(5)
            return super().classify(r)

    t = threading.Thread(
        target=worker, args=(runtime, Slow(), KB), kwargs={"lease_seconds": 0.6}
    )
    t.start()
    assert entered.wait(3)
    time.sleep(0.8)
    assert worker(runtime, FakeRunner(), KB, lease_seconds=0.6) == 0
    db = connect(runtime)
    assert (
        db.execute("SELECT lease FROM jobs WHERE state='running'").fetchone()[0]
        > time.time()
    )
    db.close()
    release.set()
    t.join(5)
    assert not t.is_alive()


def test_late_result_cannot_overwrite_after_token_loss(tmp_path):
    _, runtime = setup(tmp_path)

    class Lost(FakeRunner):
        def classify(self, r):
            db = connect(runtime)
            with db:
                db.execute("UPDATE jobs SET token='replacement' WHERE state='running'")
            db.close()
            return super().classify(r)

    worker(runtime, Lost(), KB)
    db = connect(runtime)
    assert db.execute("SELECT count(*) FROM classifications").fetchone()[0] == 0
    assert (
        db.execute("SELECT error FROM attempts").fetchone()[0]
        == "late_result_discarded"
    )
    with db:
        db.execute("UPDATE jobs SET lease=0")
    db.close()
    assert worker(runtime, FakeRunner(), KB) == 2


def test_portable_backup_restores_edit_history_and_blobs(tmp_path):
    _, runtime = setup(tmp_path)
    worker(runtime, FakeRunner(), KB)
    client = TestClient(create_app(runtime, KB))
    iid = client.get("/api/inquiries").json()[0]["id"]
    client.put(
        "/api/drafts/" + iid,
        json={"version": 1, "body": "복원할 편집본", "review": "reviewed"},
    )
    backup(runtime, tmp_path / "backup")
    restore(tmp_path / "backup", tmp_path / "restored")
    restored = TestClient(create_app(tmp_path / "restored", KB))
    assert "복원할 편집본" in restored.get("/inquiries/" + iid).text
    db = connect(tmp_path / "restored")
    assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert db.execute("SELECT count(*) FROM edits").fetchone()[0] == 1
    assert restored.get("/sources/" + iid + "/raw").status_code == 200
    db.close()
    with pytest.raises(ValueError):
        restore(tmp_path / "backup", runtime)
    (tmp_path / "backup/app.sqlite3").write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="checksum"):
        restore(tmp_path / "backup", tmp_path / "bad")
    assert not (tmp_path / "bad").exists()


def test_all_mutations_reject_foreign_origin_and_dns_rebinding(tmp_path):
    _, runtime = setup(tmp_path)
    worker(runtime, FakeRunner(), KB)
    client = TestClient(create_app(runtime, KB))
    iid = client.get("/api/inquiries").json()[0]["id"]
    for suffix in ("classify", "regenerate", "override"):
        assert (
            client.post(
                "/api/inquiries/" + iid + "/" + suffix,
                headers={"Origin": "https://evil.test"},
                json={},
            ).status_code
            == 403
        )
    assert client.get("/", headers={"host": "evil.test"}).status_code == 400
    assert (
        client.get("/").headers["content-security-policy"].find("script-src 'self'")
        >= 0
    )
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/app.css").status_code == 200


def test_p1_migration_retains_working_copy(tmp_path):
    # Create original schema exactly as P1 used it, then upgrade.
    db = sqlite3.connect(tmp_path / "app.sqlite3")
    db.executescript(
        "CREATE TABLE jobs(id INTEGER PRIMARY KEY,source_id TEXT,kind TEXT,state TEXT,attempts INTEGER DEFAULT 0,token TEXT,lease REAL,error TEXT,UNIQUE(source_id,kind));INSERT INTO jobs(source_id,kind,state) VALUES('old','classify','failed');CREATE TABLE drafts(source_id TEXT PRIMARY KEY,generated TEXT,body TEXT,version INTEGER DEFAULT 1,review TEXT DEFAULT 'generated');INSERT INTO drafts VALUES('old','{}','사용자 초안',7,'reviewed');"
    )
    db.executescript(
        "CREATE TABLE sources(id TEXT PRIMARY KEY,message_id TEXT,conversation TEXT,subject TEXT,sender TEXT,recipients TEXT,date TEXT,body TEXT,raw_path TEXT,attachments TEXT); INSERT INTO sources VALUES('old','m','c','s','a','b','','body','blobs/old','[]'); CREATE TABLE inquiries(id TEXT PRIMARY KEY,state TEXT); INSERT INTO inquiries VALUES('old','needs_review');"
    )
    db.close()
    db = connect(tmp_path)
    assert db.execute("SELECT body,version FROM drafts").fetchone()[:] == (
        "사용자 초안",
        7,
    )
    assert "request_id" in {r[1] for r in db.execute("PRAGMA table_info(jobs)")}
    db.close()


def test_worker_process_kill_recovers_after_real_lease_expiry(tmp_path):
    import subprocess
    import sys

    _, runtime = setup(tmp_path)
    marker = tmp_path / "entered"
    script = """import sys,time
from pathlib import Path
from mail_jira_assistant.ai import FakeRunner
from mail_jira_assistant.service import worker
class Blocking(FakeRunner):
 def classify(self,r):
  Path(sys.argv[2]).write_text('running')
  time.sleep(60)
worker(sys.argv[1],Blocking(),sys.argv[3],lease_seconds=.4)
"""
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(runtime), str(marker), str(KB)]
    )
    try:
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert marker.exists()
        process.kill()
        process.wait(timeout=5)
        time.sleep(0.6)
        assert worker(runtime, FakeRunner(), KB) == 2
        db = connect(runtime)
        assert (
            db.execute("SELECT count(*) FROM jobs WHERE state='running'").fetchone()[0]
            == 0
        )
        assert (
            db.execute("SELECT error FROM attempts ORDER BY id LIMIT 1").fetchone()[0]
            == "lease_expired"
        )
        db.close()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


def test_dry_run_is_read_only_and_shows_planned_changes(tmp_path):
    from mail_jira_assistant.service import preview

    inbox, runtime = setup(tmp_path)
    before = (runtime / "app.sqlite3").read_bytes()
    mail(inbox, "new", "새 문의", "<new@test>")
    result = preview(runtime, inbox, activate=True)
    assert len([x for x in result["files"] if x["planned_job"] == "classify"]) == 1
    assert (runtime / "app.sqlite3").read_bytes() == before
    assert preview(tmp_path / "not-created", inbox)["files"]
    assert not (tmp_path / "not-created").exists()


def test_manual_draft_policy_keeps_classification_without_auto_generation(tmp_path):
    _, runtime = setup(tmp_path)
    assert worker(runtime, FakeRunner(), KB, automatic_drafts=False) == 1
    db = connect(runtime)
    iid = db.execute("SELECT id FROM inquiries").fetchone()[0]
    assert db.execute("SELECT count(*) FROM drafts").fetchone()[0] == 0
    db.close()
    enqueue(runtime, iid, regenerate=True)
    assert worker(runtime, FakeRunner(), KB, automatic_drafts=False) == 1
