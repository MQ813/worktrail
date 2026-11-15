import uuid

import pytest
from fastapi.testclient import TestClient
from test_project_updates import KB, rows, setup

from mail_jira_assistant import project_ai as ai
from mail_jira_assistant.ai import FakeRunner
from mail_jira_assistant.service import worker
from mail_jira_assistant.storage import connect
from mail_jira_assistant.web import create_app


def submit(runtime, **kwargs):
    client = TestClient(create_app(runtime, KB))
    data = dict(
        text="신규 검증 프로젝트. 일정 TBD", mode="create", request_key=uuid.uuid4().hex
    )
    data.update(kwargs)
    response = client.post("/api/project-ai", json=data)
    assert response.status_code == 200, response.text
    return client, data, response.json()["request_id"]


def test_create_inquiry_idempotent_confirm_cancel(tmp_path):
    runtime, iid, _ = setup(tmp_path)
    client, data, key = submit(runtime, inquiry_ids=[iid])
    assert client.post("/api/project-ai", json=data).status_code == 200
    assert len(rows(runtime, "SELECT * FROM jobs WHERE kind='project_command'")) == 1
    worker(runtime, FakeRunner(), KB)
    status = client.get("/api/project-ai/" + key).json()
    assert status["state"] == "applied", status
    pid = status["project_id"]
    p = rows(runtime, "SELECT * FROM projects WHERE id=?", (pid,))[0]
    assert p["spec"] == p["target_on"] == "TBD"
    assert rows(
        runtime,
        "SELECT * FROM project_source_links WHERE inquiry_id=? AND project_id=?",
        (iid, pid),
    )
    assert "AI 반영 · 미확인" in client.get(f"/projects/{pid}").text
    h = rows(runtime, "SELECT * FROM project_ai_history WHERE project_id=?", (pid,))[0]
    assert (
        client.post(f"/api/project-ai/history/{h['id']}/confirm", json={}).status_code
        == 200
    )
    assert (
        rows(runtime, "SELECT * FROM project_ai_history WHERE id=?", (h["id"],))[0][
            "confirmed"
        ]
        == 1
    )
    assert (
        client.post(f"/api/project-ai/history/{h['id']}/undo", json={}).status_code
        == 200
    )
    assert (
        rows(runtime, "SELECT state FROM projects WHERE id=?", (pid,))[0]["state"]
        == "cancelled"
    )
    assert (
        client.post(f"/api/project-ai/history/{h['id']}/undo", json={}).status_code
        == 409
    )


def test_schedule_replace_undo_and_no_action_completion(tmp_path):
    runtime, iid, pid = setup(tmp_path)
    db = connect(runtime)
    with db:
        db.execute("DELETE FROM jobs")
        eid = db.execute(
            "INSERT INTO project_entries(project_id,section,kind,text) VALUES(?,'next_actions','schedule','기한 2027-03-10')",
            (pid,),
        ).lastrowid
    db.close()
    client, _, key = submit(
        runtime, text="기한 2027-03-10 -> 2027-03-24", mode="update", project_id=pid
    )

    class Runner(FakeRunner):
        def project_command(self, request):
            return ai.CommandResult(
                outcome="update",
                project_id=pid,
                metadata={"target_on": "2027-03-24"},
                before_text={str(eid): "기한 2027-03-10"},
                changes=[
                    dict(
                        project_id=pid,
                        section="next_actions",
                        kind="schedule",
                        operation="update",
                        entry_id=eid,
                        text="기한 2027-03-24",
                        evidence=[dict(source_ref="user", text=request.instruction)],
                    )
                ],
            )

    worker(runtime, Runner(), KB)
    assert client.get("/api/project-ai/" + key).json()["state"] == "applied"
    assert (
        len(rows(runtime, "SELECT * FROM project_entries WHERE project_id=?", (pid,)))
        == 1
    )
    assert (
        rows(runtime, "SELECT text FROM project_entries WHERE id=?", (eid,))[0]["text"]
        == "기한 2027-03-24"
    )
    assert not rows(runtime, "SELECT * FROM activities")
    hid = rows(runtime, "SELECT id FROM project_ai_history")[0]["id"]
    assert (
        client.post(f"/api/project-ai/history/{hid}/undo", json={}).status_code == 200
    )
    assert (
        rows(runtime, "SELECT text FROM project_entries WHERE id=?", (eid,))[0]["text"]
        == "기한 2027-03-10"
    )


@pytest.mark.parametrize(
    "kind", ["stale", "wrong_target", "bad_evidence", "duplicate_name", "wrong_mode"]
)
def test_invalid_result_atomic(tmp_path, kind):
    runtime, iid, pid = setup(tmp_path)
    db = connect(runtime)
    with db:
        db.execute("DELETE FROM jobs")
    db.close()
    mode = "update" if kind in ("stale", "wrong_target", "wrong_mode") else "create"
    client, _, key = submit(
        runtime, mode=mode, project_id=pid if mode == "update" else None
    )
    if kind == "stale":
        db = connect(runtime)
        with db:
            db.execute("UPDATE projects SET version=version+1 WHERE id=?", (pid,))
        db.close()

    class Runner(FakeRunner):
        def project_command(self, request):
            result = super().project_command(request)
            if kind == "wrong_target":
                result.project_id = 999
            if kind == "bad_evidence":
                result.changes[0].evidence[0].text = "invented"
            if kind == "duplicate_name":
                result.name = "SmartIO"
            if kind == "wrong_mode":
                result.outcome = "create"
            return result

    worker(runtime, Runner(), KB)
    status = client.get("/api/project-ai/" + key).json()
    assert status["job_state"] == "failed", status
    assert len(rows(runtime, "SELECT * FROM projects")) == 1
    assert not rows(runtime, "SELECT * FROM project_ai_history")
    assert not rows(runtime, "SELECT * FROM project_entries")


def test_needs_input_and_request_key_conflict(tmp_path):
    runtime, _, _ = setup(tmp_path)
    client, data, key = submit(runtime, mode="update")
    assert (
        client.post("/api/project-ai", json={**data, "text": "변경된 입력"}).status_code
        == 409
    )
    worker(runtime, FakeRunner(), KB)
    status = client.get("/api/project-ai/" + key).json()
    assert status["state"] == "needs_input"
    assert status["question"]


def test_followup_edit_blocks_undo(tmp_path):
    runtime, _, pid = setup(tmp_path)
    client, _, key = submit(runtime, mode="update", project_id=pid)
    worker(runtime, FakeRunner(), KB)
    assert client.get("/api/project-ai/" + key).json()["state"] == "applied"
    h = rows(runtime, "SELECT id FROM project_ai_history")[0]["id"]
    db = connect(runtime)
    with db:
        db.execute("UPDATE projects SET version=version+1 WHERE id=?", (pid,))
    db.close()
    assert client.post(f"/api/project-ai/history/{h}/undo", json={}).status_code == 409


def test_inquiry_auto_update_and_dismiss(tmp_path):
    runtime, iid, pid = setup(tmp_path)
    db = connect(runtime)
    with db:
        db.execute("UPDATE projects SET ai_managed=1 WHERE id=?", (pid,))
    db.close()
    worker(runtime, FakeRunner(), KB)
    assert rows(runtime, "SELECT * FROM project_ai_history WHERE project_id=?", (pid,))
    assert rows(runtime, "SELECT * FROM project_entries WHERE project_id=?", (pid,))
    assert not rows(runtime, "SELECT * FROM project_changes WHERE review='pending'")
    client = TestClient(create_app(runtime, KB))
    assert client.post("/api/project-ai/dismiss/" + iid, json={}).status_code == 200
    assert rows(runtime, "SELECT * FROM project_ai_dismissed")


def test_source_unlink_after_request_blocks_relink(tmp_path):
    runtime, iid, pid = setup(tmp_path)
    db = connect(runtime)
    with db:
        db.execute("DELETE FROM jobs")
    db.close()
    client, _, key = submit(runtime, mode="update", project_id=pid, inquiry_ids=[iid])
    from mail_jira_assistant.project_updates import unlink

    unlink(runtime, iid, pid)
    worker(runtime, FakeRunner(), KB)
    assert client.get("/api/project-ai/" + key).json()["job_state"] == "failed"
    assert not rows(
        runtime,
        "SELECT * FROM project_source_links WHERE inquiry_id=? AND project_id=?",
        (iid, pid),
    )
    assert not rows(runtime, "SELECT * FROM project_ai_history")


def test_unconfirmed_export_and_metadata_only_label(tmp_path):
    from mail_jira_assistant.project_updates import markdown

    runtime, _, pid = setup(tmp_path)
    db = connect(runtime)
    with db:
        db.execute("DELETE FROM jobs")
        db.execute(
            "INSERT INTO project_entries(project_id,section,kind,text) VALUES(?,'overview','issue','기존 확인된 내용')",
            (pid,),
        )
    db.close()
    client, _, key = submit(
        runtime, mode="update", project_id=pid, text="목표일 2027-04-15"
    )

    class Runner(FakeRunner):
        def project_command(self, request):
            return ai.CommandResult(
                outcome="update", project_id=pid, metadata={"target_on": "2027-04-15"}
            )

    worker(runtime, Runner(), KB)
    assert client.get("/api/project-ai/" + key).json()["state"] == "applied"
    db = connect(runtime)
    with pytest.raises(ValueError, match="미확인"):
        markdown(db, pid, pending=False)
    assert "미확인" in markdown(db, pid)
    db.close()
    from mail_jira_assistant.project_ai_web import unconfirmed_entries

    assert not unconfirmed_entries(lambda sql, args: rows(runtime, sql, args), pid)
    assert client.get("/operations").status_code == 200
