import json

import pytest
from fastapi.testclient import TestClient
from test_project_workspace import setup_workspace

from mail_jira_assistant import project_ai as ai
from mail_jira_assistant.ai import FakeRunner
from mail_jira_assistant.service import worker
from mail_jira_assistant.storage import connect
from mail_jira_assistant.web import create_app


def ready(runtime, client, pid, result, key="proposal", **kwargs):
    data = dict(
        text="검증 일정 2027-04-15 변경",
        mode="auto",
        project_id=pid,
        include_subissues=True,
        preview=True,
        request_key=key,
    )
    data.update(kwargs)
    response = client.post("/api/project-ai", json=data)
    assert response.status_code == 200, response.text
    db = connect(runtime)
    request = ai.CommandRequest.model_validate_json(
        db.execute(
            "SELECT context FROM project_ai_requests WHERE id=?", (key,)
        ).fetchone()[0]
    )
    try:
        with db:
            ai.apply(db, request, result, key)
    finally:
        db.close()
    return client.get("/api/project-ai/" + key).json()


def test_directory_tabs_separate_workspaces_and_remove_folder_api(tmp_path):
    client, pid, _, _, _ = setup_workspace(tmp_path)
    for tab in ("list", "connections", "new", "ai", "history"):
        html = client.get("/projects?tab=" + tab).text
        assert html.count('aria-current="location"') == 1
        assert 'aria-label="프로젝트 탐색"' in html
        assert "JOB 폴더 가져오기" not in html
        assert ('id="project-create-form"' in html) == (tab == "new")
        assert ('id="ai-workspace-form"' in html) == (tab == "ai")
        assert ('id="project-connections"' in html) == (tab == "connections")
    assert client.post(
        "/api/projects/import-folder", json={"path": "unread"}
    ).status_code in (404, 405)
    assert client.get("/projects?tab=unknown").status_code == 404


def test_manual_creation_saves_all_fields_and_duplicate_never_updates(tmp_path):
    client = TestClient(create_app(tmp_path, tmp_path))
    data = dict(
        name="수동 생성",
        purpose="검증 보고서",
        owner="개발팀",
        process="28nm",
        development_target="GPIO",
        target_on="2027-06-30",
        started_on="2026-11-15",
        spec="1.8V",
    )
    pid = client.post("/api/projects", json=data).json()["id"]
    db = connect(tmp_path)
    row = dict(db.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone())
    assert all(row[k] == v for k, v in data.items())
    assert (
        client.post("/api/projects", json={**data, "purpose": "overwrite"}).status_code
        == 409
    )
    assert (
        client.post(
            "/api/projects",
            json={**data, "name": "bad date", "target_on": "2027-02-30"},
        ).status_code
        == 409
    )
    assert db.execute("SELECT count(*) FROM projects").fetchone()[0] == 1
    db.close()


def test_proposal_worker_has_no_writes_until_apply_and_survives_reload(tmp_path):
    client, pid, _, wids, eid = setup_workspace(tmp_path)
    result = ai.CommandResult(
        outcome="update",
        project_id=pid,
        metadata={"target_on": "2027-04-15"},
        changes=[
            dict(
                project_id=pid,
                work_item_id=wids[0],
                section="progress",
                kind="progress",
                text="검증 일정 2027-04-15 변경",
                evidence=[dict(source_ref="user", text="2027-04-15")],
            )
        ],
    )

    class Runner(FakeRunner):
        def project_command(self, request):
            return result

    assert (
        client.post(
            "/api/project-ai",
            json=dict(
                text="검증 일정 2027-04-15 변경",
                preview=True,
                include_subissues=True,
                project_id=pid,
                request_key="durable",
            ),
        ).status_code
        == 200
    )
    worker(tmp_path, Runner(), tmp_path)
    db = connect(tmp_path)
    assert db.execute(
        "SELECT target_on,version FROM projects WHERE id=?", (pid,)
    ).fetchone()[:] == ("TBD", 1)
    assert db.execute("SELECT count(*) FROM project_ai_history").fetchone()[0] == 0
    client = TestClient(create_app(tmp_path, tmp_path))
    status = client.get("/api/project-ai/durable").json()
    assert status["state"] == "ready" and len(status["projects"][0]["entries"]) == 3
    response = client.post(
        "/api/project-ai/durable/apply",
        json={
            "metadata": {"target_on": "2027-04-20"},
            "texts": ["사용자가 편집한 검증 일정"],
        },
    )
    assert response.status_code == 200, response.text
    assert (
        db.execute("SELECT target_on FROM projects WHERE id=?", (pid,)).fetchone()[0]
        == "2027-04-20"
    )
    assert db.execute("SELECT count(*) FROM project_ai_history").fetchone()[0] == 1
    assert (
        db.execute(
            "SELECT work_item_id FROM project_entries WHERE text=?",
            ("사용자가 편집한 검증 일정",),
        ).fetchone()[0]
        == wids[0]
    )
    h = db.execute("SELECT * FROM project_ai_history").fetchone()
    assert json.loads(h["input"])["review_edits"]["texts"] == [
        "사용자가 편집한 검증 일정"
    ]
    assert client.post("/api/project-ai/durable/apply", json={}).status_code == 200
    assert db.execute("SELECT count(*) FROM project_ai_history").fetchone()[0] == 1
    assert (
        client.post(f"/api/project-ai/history/{h['id']}/undo", json={}).status_code
        == 200
    )
    assert (
        db.execute("SELECT target_on FROM projects WHERE id=?", (pid,)).fetchone()[0]
        == "TBD"
    )
    db.close()


@pytest.mark.parametrize("change", ["project", "source"])
def test_proposal_apply_revalidates_project_and_source_without_partial_writes(
    tmp_path, change
):
    from test_project_updates import setup

    runtime, iid, pid = setup(tmp_path)
    client = TestClient(create_app(runtime, tmp_path))
    status = ready(
        runtime,
        client,
        pid,
        ai.CommandResult(
            outcome="update", project_id=pid, metadata={"target_on": "2027-04-15"}
        ),
        inquiry_ids=[iid],
    )
    assert status["state"] == "ready"
    db = connect(runtime)
    with db:
        if change == "project":
            db.execute("UPDATE projects SET version=version+1 WHERE id=?", (pid,))
        else:
            db.execute("DELETE FROM project_source_links WHERE inquiry_id=?", (iid,))
            db.execute(
                "INSERT INTO audit(kind,target,detail,created) VALUES('project_unlink',?,?,strftime('%s','now')+1)",
                (iid, str(pid)),
            )
    assert client.post("/api/project-ai/proposal/apply", json={}).status_code == 409
    assert (
        db.execute("SELECT target_on FROM projects WHERE id=?", (pid,)).fetchone()[0]
        == "TBD"
    )
    assert db.execute("SELECT count(*) FROM project_ai_history").fetchone()[0] == 0
    db.close()


def test_search_is_readonly_with_scope_validation_and_history(tmp_path):
    client, pid, other, _, _ = setup_workspace(tmp_path)
    result = ai.CommandResult(
        outcome="search", matches=[dict(project_id=pid, reason="GPIO 검증 조건 일치")]
    )
    status = ready(tmp_path, client, pid, result, mode="search")
    assert status["state"] == "searched" and status["projects"][0]["id"] == pid
    assert client.post("/api/project-ai/proposal/apply", json={}).status_code == 409
    db = connect(tmp_path)
    assert db.execute("SELECT count(*) FROM project_ai_history").fetchone()[0] == 0
    assert "검색 완료" in client.get("/projects?tab=history").text
    db.close()
    with pytest.raises(ValueError, match="범위"):
        ready(
            tmp_path,
            client,
            pid,
            ai.CommandResult(
                outcome="search",
                matches=[dict(project_id=other, reason="outside scope")],
            ),
            key="outside",
            mode="search",
        )
    with pytest.raises(ValueError, match="방식"):
        ready(
            tmp_path,
            client,
            pid,
            ai.CommandResult(
                outcome="update", project_id=pid, metadata={"owner": "write"}
            ),
            key="unsafe-search",
            mode="search",
        )


def test_new_proposal_validates_before_commit_and_edits_are_bounded(tmp_path):
    client, pid, _, _, _ = setup_workspace(tmp_path)
    initial = ai.CommandResult(
        outcome="create", name="New GPIO", metadata={"purpose": "검증 보고서"}
    )
    status = ready(tmp_path, client, None, initial, mode="create")
    assert status["state"] == "ready" and status["project_id"] is None
    db = connect(tmp_path)
    assert db.execute("SELECT count(*) FROM projects").fetchone()[0] == 2
    assert (
        client.post(
            "/api/project-ai/proposal/apply", json={"metadata": {"unknown": "bad"}}
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/api/project-ai/proposal/apply", json={"texts": ["extra"]}
        ).status_code
        == 409
    )
    response = client.post(
        "/api/project-ai/proposal/apply",
        json={"name": "Edited new GPIO", "metadata": {"purpose": "편집된 목적"}},
    )
    assert response.status_code == 200, response.text
    row = db.execute(
        "SELECT name,purpose FROM projects WHERE id=?", (response.json()["project_id"],)
    ).fetchone()
    assert row[:] == ("Edited new GPIO", "편집된 목적")
    db.close()


def test_invalid_preview_rolls_back_and_cannot_mislabel_issue(tmp_path):
    client, pid, _, wids, eid = setup_workspace(tmp_path)
    result = ai.CommandResult(
        outcome="update",
        project_id=pid,
        metadata={"owner": "must rollback"},
        before_text={str(eid): "COMMON_OVERVIEW"},
        changes=[
            dict(
                project_id=pid,
                work_item_id=wids[0],
                entry_id=eid,
                operation="update",
                section="overview",
                kind="progress",
                text="검증 일정 2027-04-15 변경",
                evidence=[dict(source_ref="user", text="2027-04-15")],
            )
        ],
    )
    with pytest.raises(ValueError, match="상충"):
        ready(tmp_path, client, pid, result)
    db = connect(tmp_path)
    assert (
        db.execute("SELECT owner FROM projects WHERE id=?", (pid,)).fetchone()[0] == ""
    )
    assert db.execute("SELECT count(*) FROM project_ai_history").fetchone()[0] == 0
    db.close()
