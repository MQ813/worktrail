"""Conversation, user ownership and baseline invariants (S03–06,16–17,20–21,24)."""

import json
from email.message import EmailMessage
from pathlib import Path

from fastapi.testclient import TestClient

from mail_jira_assistant.ai import FakeRunner
from mail_jira_assistant.service import enqueue, poll, sync, worker
from mail_jira_assistant.storage import connect
from mail_jira_assistant.web import create_app

KB = Path(__file__).parent / "fixtures/kb"


def mail(
    folder,
    name,
    body,
    mid,
    reply=None,
    sender="customer@example.test",
    to="me@example.test",
    cc=None,
):
    folder.mkdir(parents=True, exist_ok=True)
    m = EmailMessage()
    m["From"] = sender
    m["To"] = to
    m["Subject"] = name
    m["Message-ID"] = mid
    if reply:
        m["In-Reply-To"] = reply
    if cc:
        m["Cc"] = cc
    m.set_content(body)
    p = folder / (name + ".eml")
    p.write_bytes(m.as_bytes())
    return p


def test_conversation_multiple_actions_direction_and_manual_history(tmp_path):
    inbox = tmp_path / "in"
    sent = tmp_path / "sent"
    runtime = tmp_path / "state"
    mail(
        inbox,
        "question",
        "GPIO 온도와 전압을 확인 부탁드립니다.",
        "<1@test>",
        to="other@example.test",
        cc="alias@example.test",
    )
    mail(
        sent,
        "promise",
        "온도와 전압을 검토하겠습니다.",
        "<2@test>",
        "<1@test>",
        sender="alias@example.test",
    )
    sync(
        runtime,
        inbox,
        sent=sent,
        identity=["me@example.test", "alias@example.test"],
        history_only=False,
    )
    db = connect(runtime)
    sources = db.execute("SELECT * FROM sources ORDER BY rowid").fetchall()
    iid = sources[0]["id"]
    assert sources[0]["inquiry_id"] == sources[1]["inquiry_id"]
    assert sources[1]["direction"] == "outbound"
    assert db.execute("SELECT count(*) FROM inquiries").fetchone()[0] == 1

    class Multiple(FakeRunner):
        def classify(self, r):
            assert r.direction == "outbound"
            assert r.identity == ["me@example.test", "alias@example.test"]
            c = super().classify(r)
            c.actions = []
            from mail_jira_assistant.contracts import Action

            for description in ["온도 확인", "전압 확인"]:
                c.actions.append(
                    Action(
                        description=description, evidence_refs=[r.source_ref + "#body"]
                    )
                )
            return c

    enqueue(runtime)
    worker(runtime, Multiple(), KB)
    assert db.execute("SELECT count(*) FROM actions").fetchone()[0] == 2
    assert db.execute("SELECT count(*) FROM drafts").fetchone()[0] == 0
    client = TestClient(create_app(runtime, KB))
    rev = db.execute("SELECT max(id) FROM revisions").fetchone()[0]
    assert (
        client.post(
            f"/api/inquiries/{iid}/override",
            json={"state": "completed", "note": "실제 회신 확인", "revision": rev},
        ).status_code
        == 200
    )
    # New customer request reopens for review, while manual completion remains in history.
    mail(
        inbox, "followup", "추가 GPIO 전류를 확인 부탁드립니다.", "<3@test>", "<1@test>"
    )
    sync(runtime, inbox, history_only=False)
    assert db.execute("SELECT state FROM inquiries").fetchone()[0] == "needs_review"
    assert db.execute("SELECT state FROM overrides").fetchone()[0] == "completed"
    assert (
        client.post(
            f"/api/inquiries/{iid}/override",
            json={"state": "completed", "revision": rev},
        ).status_code
        == 409
    )
    db.close()


def test_baseline_no_historical_ai_even_after_restart(tmp_path):
    inbox = tmp_path / "in"
    runtime = tmp_path / "state"
    mail(inbox, "old", "과거 GPIO 문의", "<old@test>")
    assert poll(runtime, inbox) == 1
    assert poll(runtime, inbox, activate=True) == 0
    db = connect(runtime)
    assert db.execute("SELECT count(*) FROM jobs").fetchone()[0] == 0
    mail(inbox, "new", "새 GPIO 문의", "<new@test>")
    poll(runtime, inbox, activate=True)
    poll(runtime, inbox, activate=True)
    assert db.execute("SELECT count(*) FROM jobs").fetchone()[0] == 1
    worker(runtime, FakeRunner(), KB)
    assert db.execute("SELECT count(*) FROM drafts").fetchone()[0] == 1
    db.close()


def test_new_reply_and_regeneration_preserve_reviewed_copy(tmp_path):
    inbox = tmp_path / "in"
    runtime = tmp_path / "state"
    mail(inbox, "first", "GPIO 온도 확인 부탁드립니다.", "<1@test>")
    sync(runtime, inbox, history_only=False)
    enqueue(runtime)
    worker(runtime, FakeRunner(), KB)
    db = connect(runtime)
    iid = db.execute("SELECT id FROM inquiries").fetchone()[0]
    client = TestClient(create_app(runtime, KB))
    client.put(
        "/api/drafts/" + iid,
        json={"version": 1, "body": "내가 검토한 내용", "review": "reviewed"},
    )
    mail(inbox, "next", "GPIO 전압도 확인 부탁드립니다.", "<2@test>", "<1@test>")
    poll(runtime, inbox, activate=True)
    worker(runtime, FakeRunner(), KB)
    draft = db.execute("SELECT * FROM drafts").fetchone()
    assert (
        draft["body"] == "내가 검토한 내용"
        and draft["review"] == "reviewed"
        and draft["freshness"] == "stale"
    )
    assert db.execute("SELECT count(*) FROM draft_versions").fetchone()[0] == 2
    assert db.execute("SELECT state FROM inquiries").fetchone()[0] != "completed"
    assert (
        client.post("/api/inquiries/" + iid + "/regenerate", json={}).status_code == 200
    )
    assert (
        client.post("/api/inquiries/" + iid + "/regenerate", json={}).status_code == 200
    )
    worker(runtime, FakeRunner(), KB)
    assert db.execute("SELECT count(*) FROM draft_versions").fetchone()[0] == 4
    assert db.execute("SELECT body FROM drafts").fetchone()[0] == "내가 검토한 내용"
    candidate = db.execute("SELECT max(id) FROM draft_versions").fetchone()[0]
    assert (
        client.post(
            f"/api/draft-versions/{candidate}/adopt", json={"version": 2}
        ).status_code
        == 200
    )
    assert db.execute("SELECT freshness FROM drafts").fetchone()[0] == "current"
    assert db.execute("SELECT count(*) FROM edits").fetchone()[0] == 2
    db.close()


def test_source_changes_during_draft_are_stale_and_followed_up(tmp_path):
    inbox = tmp_path / "in"
    runtime = tmp_path / "state"
    mail(inbox, "first", "GPIO 확인 부탁드립니다.", "<1@test>")
    sync(runtime, inbox, history_only=False)
    enqueue(runtime)

    class Changed(FakeRunner):
        once = False

        def draft(self, r):
            if not self.once:
                self.once = True
                mail(inbox, "reply", "추가 조건입니다.", "<2@test>", "<1@test>")
                sync(runtime, inbox, history_only=False)
            return super().draft(r)

    worker(runtime, Changed(), KB)
    db = connect(runtime)
    versions = db.execute(
        "SELECT revision_id FROM draft_versions ORDER BY id"
    ).fetchall()
    assert len(versions) == 2 and versions[0][0] < versions[1][0]
    assert (
        db.execute("SELECT count(*) FROM jobs WHERE state='running'").fetchone()[0] == 0
    )
    db.close()


def test_message_id_collision_and_manual_unlink_preserve_data(tmp_path):
    inbox = tmp_path / "in"
    runtime = tmp_path / "state"
    mail(inbox, "a", "첫 요청", "<same@test>")
    mail(inbox, "b", "다른 요청", "<same@test>")
    sync(runtime, inbox)
    db = connect(runtime)
    assert db.execute("SELECT count(*) FROM inquiries").fetchone()[0] == 2
    assert (
        db.execute("SELECT count(*) FROM sources WHERE coverage='partial'").fetchone()[
            0
        ]
        == 1
    )
    ids = [r[0] for r in db.execute("SELECT id FROM inquiries")]
    client = TestClient(create_app(runtime, KB))
    assert (
        client.post(
            "/api/sources/" + ids[1] + "/link", json={"target": ids[0]}
        ).status_code
        == 200
    )
    assert client.post("/api/sources/" + ids[1] + "/link", json={}).status_code == 200
    assert db.execute("SELECT count(*) FROM sources").fetchone()[0] == 2
    assert db.execute("SELECT count(*) FROM audit").fetchone()[0] == 2
    db.close()


def test_manual_classification_survives_reclassify_and_requires_reconfirmation(
    tmp_path,
):
    inbox = tmp_path / "in"
    runtime = tmp_path / "state"
    mail(inbox, "first", "GPIO 질문", "<1@test>")
    sync(runtime, inbox, history_only=False)
    enqueue(runtime)
    worker(runtime, FakeRunner(), KB)
    client = TestClient(create_app(runtime, KB))
    iid = client.get("/api/inquiries").json()[0]["id"]
    db = connect(runtime)
    revision = db.execute("SELECT max(id) FROM revisions").fetchone()[0]
    correction = dict(
        revision=revision,
        response_expected="no",
        action_required="no",
        work_performed="unknown",
        waiting_for_others="yes",
        note="담당자에게 전달 완료",
    )
    assert (
        client.post(
            "/api/inquiries/" + iid + "/classification", json=correction
        ).status_code
        == 200
    )
    client.post("/api/inquiries/" + iid + "/classify", json={})
    worker(runtime, FakeRunner(), KB)
    item = client.get("/api/inquiries").json()[0]
    assert (
        item["manual_classification"]["response_expected"] == "no"
        and not item["classification_needs_review"]
    )
    mail(inbox, "next", "새 요청입니다.", "<2@test>", "<1@test>")
    sync(runtime, inbox, history_only=False)
    assert client.get("/api/inquiries").json()[0]["classification_needs_review"]
    assert (
        client.post(
            "/api/inquiries/" + iid + "/classification", json=correction
        ).status_code
        == 409
    )
    db.close()


def test_performed_action_can_reference_existing_task_without_auto_completing(tmp_path):
    from mail_jira_assistant.contracts import Action

    inbox = tmp_path / "in"
    runtime = tmp_path / "state"
    mail(
        inbox,
        "first",
        "GPIO 온도 검토하겠습니다.",
        "<1@test>",
        sender="me@example.test",
    )
    sync(runtime, inbox, identity=["me@example.test"])
    enqueue(runtime)
    worker(runtime, FakeRunner(), KB)
    db = connect(runtime)
    iid = db.execute("SELECT id FROM inquiries").fetchone()[0]
    aid = db.execute("SELECT id FROM actions").fetchone()[0]
    mail(
        inbox,
        "done",
        "검증을 완료했습니다.",
        "<2@test>",
        "<1@test>",
        sender="me@example.test",
    )
    sync(runtime, inbox, identity=["me@example.test"])

    class Completed(FakeRunner):
        def classify(self, r):
            result = super().classify(r)
            assert aid in {x["id"] for x in r.open_actions}
            result.actions = [
                Action(
                    kind="performed",
                    description="온도 검증 수행",
                    related_action_ids=[aid],
                    evidence_refs=[r.source_ref + "#body"],
                )
            ]
            return result

    enqueue(runtime, iid)
    worker(runtime, Completed(), KB)
    assert (
        db.execute("SELECT state FROM actions WHERE id=?", (aid,)).fetchone()[0]
        == "proposed"
    )
    evidence = db.execute(
        "SELECT evidence FROM actions WHERE description='온도 검증 수행'"
    ).fetchone()[0]
    assert json.loads(evidence)["related_action_ids"] == [aid]
    db.close()
