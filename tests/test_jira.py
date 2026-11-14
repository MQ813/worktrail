"""Read-only connector, partial failure and notification coverage (S07–10,23)."""

import copy
import json
from pathlib import Path

import pytest
from test_tracking import mail

from mail_jira_assistant.ai import FakeRunner
from mail_jira_assistant.jira import HTTPJira, NoRedirect, discover, register, sync_jira
from mail_jira_assistant.service import enqueue, sync, worker
from mail_jira_assistant.storage import connect

FIXTURE = Path(__file__).parent / "fixtures/jira/gpio.json"
KB = Path(__file__).parent / "fixtures/kb"


def servers():
    return [
        dict(
            server_id="one",
            base_url="https://one.example.test",
            fixture=str(FIXTURE),
            poll_seconds=0,
        ),
        dict(
            server_id="two",
            base_url="https://two.example.test",
            fixture=str(FIXTURE),
            poll_seconds=0,
        ),
    ]


def test_notification_discovery_multiple_servers_and_unknown_host(tmp_path):
    inbox = tmp_path / "in"
    runtime = tmp_path / "state"
    configs = servers()
    mail(
        inbox,
        "jira notification",
        "https://one.example.test/browse/SAME-1\nhttps://two.example.test/browse/SAME-1\nhttps://unknown.example.test/browse/EXT-2",
        "<jira@test>",
        sender="jira@example.test",
    )
    sync(runtime, inbox, jira_servers=configs, history_only=False)
    assert sync_jira(runtime, configs, history_only=False) == 2
    enqueue(runtime, include_history=False)
    assert worker(runtime, FakeRunner(), KB) == 4
    db = connect(runtime)
    assert db.execute("SELECT count(*) FROM jira_issues").fetchone()[0] == 3
    assert db.execute("SELECT count(*) FROM drafts").fetchone()[0] == 2
    assert (
        db.execute(
            "SELECT error FROM jira_issues WHERE server_id LIKE 'unknown:%'"
        ).fetchone()[0]
        == "connection_required"
    )
    # Already tracked issues change without another notification.
    assert sync_jira(runtime, configs, history_only=False) == 2
    enqueue(runtime, include_history=False)
    worker(runtime, FakeRunner(), KB)
    assert (
        db.execute("SELECT count(*) FROM events WHERE kind='comment_added'").fetchone()[
            0
        ]
        == 2
    )
    assert db.execute("SELECT count(*) FROM draft_versions").fetchone()[0] == 4
    db.close()


def test_incomplete_page_does_not_delete_previous_comments(tmp_path):
    configs = servers()[:1]
    register(tmp_path, "https://one.example.test/browse/A-1", configs)
    sync_jira(tmp_path, configs)
    db = connect(tmp_path)
    before = db.execute("SELECT snapshot FROM jira_issues").fetchone()[0]
    partial = copy.deepcopy(json.loads(FIXTURE.read_text(encoding="utf-8"))[0])
    partial["fields"]["comment"]["total"] = 10
    f = tmp_path / "partial.json"
    f.write_text(json.dumps(partial))
    configs[0]["fixture"] = str(f)
    assert sync_jira(tmp_path, configs, force=True) == 0
    assert db.execute("SELECT snapshot FROM jira_issues").fetchone()[0] == before
    assert db.execute("SELECT count(*) FROM revisions").fetchone()[0] == 1
    assert db.execute("SELECT error FROM jira_issues").fetchone()[0]
    db.close()


def test_attachment_failure_is_visible_and_other_issue_progresses(tmp_path):
    configs = servers()
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))[0]
    payload["fields"]["attachment"] = [
        dict(
            id="55",
            filename="file.pdf",
            mimeType="application/pdf",
            content="https://evil.test/download",
        )
    ]
    f = tmp_path / "attachment.json"
    f.write_text(json.dumps(payload))
    configs[0]["fixture"] = str(f)
    for s in configs:
        register(tmp_path, s["base_url"] + "/browse/A-1", configs)
    assert sync_jira(tmp_path, configs) == 2
    db = connect(tmp_path)
    a = db.execute(
        "SELECT attachments,coverage FROM sources WHERE sender='one'"
    ).fetchone()
    assert json.loads(a[0])[0]["status"] == "download_failed" and a[1] == "partial"
    db.close()


def test_http_all_comment_pages_and_origin_restriction():
    connector = HTTPJira(dict(base_url="https://jira.test", api_version="2"))
    calls = []

    def request(path, raw=False):
        calls.append(path)
        if "/comment?" not in path:
            return {"id": "1", "fields": {}}
        if "startAt=0" in path:
            return {
                "startAt": 0,
                "total": 2,
                "comments": [{"id": "1", "body": "first"}],
            }
        return {"startAt": 1, "total": 2, "comments": [{"id": "2", "body": "second"}]}

    connector.request = request
    assert len(connector.fetch("A-1")["fields"]["comment"]["comments"]) == 2
    assert len(calls) == 3
    connector = HTTPJira(dict(base_url="https://jira.test", token_env="SECRET"))
    with pytest.raises(ValueError, match="origin"):
        connector.download("https://evil.test/download")
    with pytest.raises(ValueError, match="redirect"):
        NoRedirect().redirect_request(None, None, None, None, None, None)


def test_metadata_does_not_automatically_generate_draft(tmp_path):
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))[0]
    changed = copy.deepcopy(payload)
    changed["fields"]["status"]["name"] = "Closed"
    f = tmp_path / "status.json"
    f.write_text(json.dumps([payload, changed]))
    configs = servers()[:1]
    configs[0]["fixture"] = str(f)
    register(tmp_path, "https://one.example.test/browse/A-1", configs)
    sync_jira(tmp_path, configs, history_only=False)
    enqueue(tmp_path, include_history=False)
    worker(tmp_path, FakeRunner(), KB)
    sync_jira(tmp_path, configs, history_only=False)
    enqueue(tmp_path, include_history=False)
    db = connect(tmp_path)
    assert db.execute("SELECT count(*) FROM jobs").fetchone()[0] == 2
    assert (
        db.execute(
            "SELECT count(*) FROM events WHERE kind='status_changed'"
        ).fetchone()[0]
        == 1
    )
    db.close()


def test_discovery_without_any_server_config(tmp_path):
    assert len(discover(tmp_path, "https://customer.test/browse/C-1", [])) == 1
    with pytest.raises(ValueError):
        register(tmp_path, "https://user:password@customer.test/browse/C-1", [])


def test_jira_operations_and_detail_render_with_real_data(tmp_path):
    from fastapi.testclient import TestClient

    from mail_jira_assistant.web import create_app

    configs = servers()[:1]
    iid = register(tmp_path, "https://one.example.test/browse/A-1", configs)
    sync_jira(tmp_path, configs, history_only=False)
    enqueue(tmp_path, include_history=False)
    worker(tmp_path, FakeRunner(), KB)
    client = TestClient(create_app(tmp_path, KB, configs))
    assert client.get("/operations").status_code == 200
    assert client.get("/inquiries/" + iid).status_code == 200
    assert "JIRA 추적" in client.get("/operations").text
