import json

import pytest
from fastapi.testclient import TestClient

from mail_jira_assistant import project_ai as ai
from mail_jira_assistant.project_updates import ensure_project
from mail_jira_assistant.storage import connect
from mail_jira_assistant.web import create_app


def setup_workspace(tmp_path, count=2):
    db = connect(tmp_path)
    with db:
        pid = ensure_project(db, "Library development")
        other = ensure_project(db, "Other project")
        ids = []
        for number in range(count):
            wid = db.execute(
                "INSERT INTO project_work_items(project_id,title,detail) VALUES(?,?,1)",
                (pid, f"CELL_{number:02}"),
            ).lastrowid
            ids.append(wid)
            db.execute(
                "INSERT INTO project_entries(project_id,work_item_id,section,kind,text) VALUES(?,?,'progress','progress',?)",
                (pid, wid, f"PRIVATE_CELL_{number:02} " + "개발 진행 내용 " * 40),
            )
        eid = db.execute(
            "INSERT INTO project_entries(project_id,section,kind,text) VALUES(?,'overview','progress','COMMON_OVERVIEW')",
            (pid,),
        ).lastrowid
    db.close()
    return TestClient(create_app(tmp_path, tmp_path)), pid, other, ids, eid


def test_common_ai_uses_project_content_and_preserves_issue_boundary(tmp_path):
    client, pid, _, ids, _ = setup_workspace(tmp_path, 35)
    data = dict(
        text="공통 검증 기준", mode="update", project_id=pid, request_key="common"
    )
    assert client.post("/api/project-ai", json=data).status_code == 200
    db = connect(tmp_path)
    request = ai.CommandRequest.model_validate_json(
        db.execute(
            "SELECT context FROM project_ai_requests WHERE id='common'"
        ).fetchone()[0]
    )
    assert len(request.projects[0]["entries"]) == 1
    assert len(request.projects[0]["work_items"]) == 35
    result = ai.CommandResult(
        outcome="update",
        project_id=pid,
        changes=[
            dict(
                project_id=pid,
                section="decisions",
                kind="decision",
                text=data["text"],
                evidence=[dict(source_ref="user", text=data["text"])],
            )
        ],
    )
    with db:
        ai.apply(db, request, result, "common")
    assert (
        db.execute(
            "SELECT work_item_id FROM project_entries WHERE text=?", (data["text"],)
        ).fetchone()[0]
        is None
    )
    with db:
        ai.enqueue(db, ai.CommandInput(**{**data, "request_key": "outside"}))
    request = ai.CommandRequest.model_validate_json(
        db.execute(
            "SELECT context FROM project_ai_requests WHERE id='outside'"
        ).fetchone()[0]
    )
    result.changes[0].work_item_id = ids[0]
    with pytest.raises(ValueError, match="해당 이슈"), db:
        ai.apply(db, request, result, "outside")
    assert db.execute("SELECT count(*) FROM project_work_items").fetchone()[0] == 35
    db.close()


def test_overview_and_issue_contents_are_separate(tmp_path):
    client, pid, other, ids, _ = setup_workspace(tmp_path)
    overview = client.get(f"/projects/{pid}").text
    assert "COMMON_OVERVIEW" in overview
    # Only short issue previews appear; full bodies and editors live in the issue.
    assert overview.count('class="workspace-entry"') == 1
    detail = client.get(f"/projects/{pid}?work_item={ids[0]}").text
    assert "PRIVATE_CELL_00" in detail
    assert "PRIVATE_CELL_01" not in detail and "COMMON_OVERVIEW" not in detail
    assert f'name="work_item_id" value="{ids[0]}"' in detail
    assert client.get(f"/projects/{other}?work_item={ids[0]}").status_code == 404
    assert client.get(f"/projects/{pid}?view=unknown").status_code == 404


def test_manual_entry_scope_version_and_issue_redirect(tmp_path):
    client, pid, other, ids, _ = setup_workspace(tmp_path)
    bad = client.post(
        f"/api/projects/{other}/entries",
        json=dict(version=1, work_item_id=ids[0], section="progress", text="wrong"),
    )
    assert bad.status_code == 409
    response = client.post(
        f"/api/projects/{pid}/entries",
        json=dict(
            version=1, work_item_id=ids[0], section="progress", text="NEW_SCOPED_NOTE"
        ),
    )
    assert response.status_code == 200
    assert "NEW_SCOPED_NOTE" in client.get(f"/projects/{pid}?work_item={ids[0]}").text
    assert (
        "NEW_SCOPED_NOTE" not in client.get(f"/projects/{pid}?work_item={ids[1]}").text
    )
    assert (
        client.post(
            f"/api/projects/{pid}/entries",
            json=dict(version=1, section="progress", text="stale"),
        ).status_code
        == 409
    )
    response = client.post(
        f"/api/projects/{pid}/work-items",
        json=dict(version=2, title="New cell", detail=True),
    )
    assert response.status_code == 200
    assert "work_item=" in response.json()["redirect"]
    assert "New cell" in client.get(response.json()["redirect"]).text


def test_issue_search_and_pagination(tmp_path):
    client, pid, _, _, _ = setup_workspace(tmp_path, 29)
    page1 = client.get(f"/projects/{pid}?view=issues").text
    page2 = client.get(f"/projects/{pid}?view=issues&issue_page=2").text
    assert page1.count('class="issue-name"') == page2.count('class="issue-name"') == 12
    assert "CELL_00" in page1 and "CELL_12" not in page1
    assert "CELL_12" in page2 and "CELL_00" not in page2
    found = client.get(f"/projects/{pid}?view=issues&q=CELL_28").text
    assert found.count('class="issue-name"') == 1 and "CELL_28" in found
    assert (
        "검색 결과가 없습니다"
        in client.get(f"/projects/{pid}?view=issues&q=missing").text
    )


@pytest.mark.parametrize("violation", ["scope", "metadata", "entry"])
def test_ai_cannot_edit_outside_selected_issue(tmp_path, violation):
    _, pid, _, ids, eid = setup_workspace(tmp_path)
    db = connect(tmp_path)
    with db:
        ai.enqueue(
            db,
            ai.CommandInput(
                text="검증 완료 조건 확인",
                mode="update",
                project_id=pid,
                work_item_id=ids[0],
                request_key="scoped",
            ),
        )
    request = ai.CommandRequest.model_validate_json(
        db.execute("SELECT context FROM project_ai_requests").fetchone()[0]
    )
    result = ai.CommandResult(
        outcome="update",
        project_id=pid,
        changes=[
            dict(
                project_id=pid,
                work_item_id=ids[1] if violation == "scope" else ids[0],
                section="overview",
                kind="issue",
                operation="update" if violation == "entry" else "add",
                entry_id=eid if violation == "entry" else None,
                text="검증 완료 조건 확인",
                evidence=[dict(source_ref="user", text="검증 완료 조건 확인")],
            )
        ],
        metadata={"owner": "WRONG"} if violation == "metadata" else {},
    )
    with pytest.raises(ValueError), db:
        ai.apply(db, request, result, "scoped")
    assert not db.execute("SELECT 1 FROM project_ai_history").fetchone()
    assert (
        db.execute("SELECT version FROM projects WHERE id=?", (pid,)).fetchone()[0] == 1
    )
    db.close()


def test_large_project_scoped_ai_context_and_undo(tmp_path):
    client, pid, _, ids, _ = setup_workspace(tmp_path, 35)
    data = dict(
        text="동일한 검증 조건",
        mode="update",
        project_id=pid,
        work_item_id=ids[0],
        request_key="large",
    )
    assert client.post("/api/project-ai", json=data).status_code == 200
    assert (
        client.post(
            "/api/project-ai",
            json={**data, "work_item_id": None, "request_key": "large-common"},
        ).status_code
        == 200
    )
    db = connect(tmp_path)
    request = ai.CommandRequest.model_validate_json(
        db.execute(
            "SELECT context FROM project_ai_requests WHERE id='large'"
        ).fetchone()[0]
    )
    assert (
        len(request.projects[0]["entries"])
        == len(request.projects[0]["work_items"])
        == 1
    )
    before = ai.snapshot(db, pid)
    result = ai.CommandResult(
        outcome="update",
        project_id=pid,
        changes=[
            dict(
                project_id=pid,
                work_item_id=ids[0],
                section="decisions",
                kind="decision",
                text=data["text"],
                evidence=[dict(source_ref="user", text=data["text"])],
            )
        ],
    )
    with db:
        ai.apply(db, request, result, "large")
    history = db.execute("SELECT * FROM project_ai_history").fetchone()
    assert len(json.loads(history["after_state"])["work_items"]) == 35
    assert (
        db.execute(
            "SELECT work_item_id FROM project_entries WHERE text=?", (data["text"],)
        ).fetchone()[0]
        == ids[0]
    )
    with db:
        ai.review(db, history["id"], undo=True)
    # Undo advances the project version while restoring the actual content.
    after = ai.snapshot(db, pid)
    assert [(e["id"], e["text"], e["deleted"]) for e in before["entries"]] == [
        (e["id"], e["text"], e["deleted"]) for e in after["entries"] if not e["deleted"]
    ]
    assert before["work_items"] == after["work_items"]
    db.close()
