from fastapi.testclient import TestClient

from mail_jira_assistant import project_updates, worklog
from mail_jira_assistant.storage import connect
from mail_jira_assistant.web import create_app


def test_only_four_menus_and_status_in_sidebar(tmp_path):
    db = connect(tmp_path)
    with db:
        db.execute("INSERT INTO meta VALUES('ai_connection_status','TEST_CONNECTION')")
    db.close()
    client = TestClient(create_app(tmp_path, tmp_path, sample_mode=True))
    for url in ("/", "/today", "/projects", "/operations", "/?view=drafts"):
        text = client.get(url).text
        nav = text.split("<nav")[1].split("</nav>")[0]
        assert nav.count("<a ") == 4
        assert "/worklog" not in nav and "view=drafts" not in nav
        assert "답변 초안" not in nav and "업무일지" not in nav
        main = text.split("<main")[1].split("</main>")[0]
        assert "TEST_CONNECTION" not in main and "합성 샘플 환경" not in main
        assert "TEST_CONNECTION" in text.split("<footer")[1].split("</footer>")[0]
        assert "workspace-bar" not in text


def test_records_are_project_scoped_and_legacy_links_redirect(tmp_path):
    a = worklog.save(
        tmp_path, dict(description="ONLY_PROJECT_A", project="A", status="needs_review")
    )
    b = worklog.save(
        tmp_path, dict(description="ONLY_PROJECT_B", project="B", status="needs_review")
    )
    db = connect(tmp_path)
    pids = {r["name"]: r["id"] for r in db.execute("SELECT id,name FROM projects")}
    db.close()
    client = TestClient(create_app(tmp_path, tmp_path))
    response = client.get(f"/projects/{pids['A']}?view=records")
    assert "ONLY_PROJECT_A" in response.text and "ONLY_PROJECT_B" not in response.text
    assert 'name="project" value="A"' in response.text
    assert client.get(f"/projects/{pids['A']}?edit={b}").status_code == 404
    legacy = client.get(f"/worklog?edit={a}", follow_redirects=False)
    assert legacy.status_code == 303
    assert legacy.headers["location"].startswith(f"/projects/{pids['A']}?edit={a}")
    assert (
        client.get("/worklog", follow_redirects=False).headers["location"]
        == "/projects"
    )


def test_unassigned_legacy_records_can_be_assigned_without_loss(tmp_path):
    aid = worklog.save(
        tmp_path, dict(description="LEGACY_PRESERVED", status="needs_review")
    )
    db = connect(tmp_path)
    with db:
        pid = project_updates.ensure_project(db, "Assigned")
    db.close()
    client = TestClient(create_app(tmp_path, tmp_path))
    assert "LEGACY_PRESERVED" in client.get("/projects").text
    response = client.post(
        f"/api/activities/{aid}/assign-project", json={"project_id": pid, "version": 1}
    )
    assert response.status_code == 200
    assert f"/projects/{pid}?edit={aid}" in response.json()["redirect"]
    assert "LEGACY_PRESERVED" in client.get(f"/projects/{pid}?view=records").text
    assert "LEGACY_PRESERVED" not in client.get("/projects").text
    assert client.get(f"/api/activities/{aid}/history").json()["edits"]
    assert (
        client.post(
            f"/api/activities/{aid}/assign-project",
            json={"project_id": pid, "version": 1},
        ).status_code
        == 409
    )
