import json
from email.message import EmailMessage

from fastapi.testclient import TestClient

from mail_jira_assistant import project_updates as projects
from mail_jira_assistant.ai import FakeRunner
from mail_jira_assistant.contracts import Classification
from mail_jira_assistant.service import enqueue, latest, sync, worker
from mail_jira_assistant.storage import connect
from mail_jira_assistant.web import create_app


def fixture(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    for number, (subject, body) in enumerate(
        (
            ("MAIL_REVIEW", "TODO: 파형 검증 요청"),
            ("MAIL_PROGRESS", "진행 조건 확인"),
            ("JIRA_WAITING", "TODO: 결과 회신 대기"),
            ("(광고) AD_LEGACY", "행사 안내"),
        )
    ):
        mail = EmailMessage()
        mail["From"] = "customer@example.test"
        mail["To"] = "engineer@example.test"
        mail["Subject"] = subject
        mail["Message-ID"] = f"<inbox-case-{number}@example.test>"
        mail.set_content(body)
        (inbox / f"{number}.eml").write_bytes(mail.as_bytes())
    runtime = tmp_path / "state"
    sync(runtime, inbox, history_only=False)
    enqueue(runtime)
    worker(runtime, FakeRunner(), tmp_path)
    db = connect(runtime)
    ids = {r["subject"]: r["id"] for r in db.execute("SELECT id,subject FROM sources")}
    with db:
        db.execute(
            "UPDATE inquiries SET state='in_progress' WHERE id=?",
            (ids["MAIL_PROGRESS"],),
        )
        db.execute(
            "UPDATE inquiries SET state='waiting_external' WHERE id=?",
            (ids["JIRA_WAITING"],),
        )
        db.execute("UPDATE sources SET kind='jira' WHERE id=?", (ids["JIRA_WAITING"],))
        db.execute(
            "UPDATE drafts SET freshness='stale' WHERE source_id=?",
            (ids["MAIL_PROGRESS"],),
        )
        pid = projects.ensure_project(db, "Cell Library", "JOB-042")
    db.close()
    return runtime, ids, pid, TestClient(create_app(runtime, tmp_path))


def table(text):
    return text.split("<tbody>")[1].split("</tbody>")[0]


def test_summary_links_apply_exact_filters_and_stale_survives_search(tmp_path):
    _, _, _, client = fixture(tmp_path)
    text = client.get("/").text
    for state, title in (
        ("needs_review", "MAIL_REVIEW"),
        ("in_progress", "MAIL_PROGRESS"),
        ("waiting_external", "JIRA_WAITING"),
    ):
        assert f'href="/?state={state}"' in text
        filtered = client.get("/", params={"state": state}).text
        body = table(filtered)
        assert title in body
        assert (
            sum(
                other in body
                for other in ("MAIL_REVIEW", "MAIL_PROGRESS", "JIRA_WAITING")
            )
            == 1
        )
        assert f'<option value="{state}" selected>' in filtered
    stale = client.get("/?view=drafts&freshness=stale").text
    assert "MAIL_PROGRESS" in table(stale) and "MAIL_REVIEW" not in table(stale)
    assert '<option value="stale" selected>' in stale
    assert 'class="advanced-filters" open' in stale
    assert 'aria-current="true"' in stale
    searched = client.get("/?q=MAIL&view=drafts&freshness=stale").text
    assert "MAIL_PROGRESS" in table(searched) and "MAIL_REVIEW" not in table(searched)


def test_jira_and_received_mail_are_distinct_sources(tmp_path):
    _, _, _, client = fixture(tmp_path)
    text = client.get("/").text
    assert 'source-badge--jira">JIRA</span>' in text
    assert 'source-badge--inbound">받은 메일</span>' in text
    assert "JIRA_WAITING" not in table(client.get("/?source=inbound").text)
    assert "JIRA_WAITING" in table(client.get("/?source=jira").text)
    assert "MAIL_REVIEW" not in table(client.get("/?source=jira").text)


def test_legacy_nonwork_queue_is_hidden_and_pruned_without_losing_inquiries(tmp_path):
    runtime, ids, _, client = fixture(tmp_path)
    db = connect(runtime)
    iid = ids["(광고) AD_LEGACY"]
    # Reproduce old classification JSON without project-related fields.
    data = {
        k: "no"
        for k in (
            "response_expected",
            "action_required",
            "work_performed",
            "waiting_for_others",
        )
    }
    data.update(review_required=False, evidence=[], actions=[])
    with db:
        db.execute(
            "UPDATE classifications SET result=? WHERE source_id=?",
            (json.dumps(data), iid),
        )
        db.execute(
            "INSERT OR REPLACE INTO project_unassigned VALUES(?,?,'[]')",
            (iid, latest(db, iid)),
        )
    html = client.get("/projects").text
    assert (
        "AD_LEGACY"
        not in html.split('id="project-connections"')[1].split(
            '</details><details class="card spaced"'
        )[0]
    )
    with db:
        assert not projects.schedule(db, iid, latest(db, iid), Classification(**data))
    assert not db.execute(
        "SELECT 1 FROM project_unassigned WHERE inquiry_id=?", (iid,)
    ).fetchone()
    assert db.execute("SELECT 1 FROM inquiries WHERE id=?", (iid,)).fetchone()
    assert db.execute("SELECT 1 FROM sources WHERE id=?", (iid,)).fetchone()
    db.close()


def test_unknown_nonaction_is_not_a_candidate_but_no_reply_project_changes_are(
    tmp_path,
):
    runtime, ids, _, _ = fixture(tmp_path)
    db = connect(runtime)
    iid = ids["MAIL_REVIEW"]
    data = Classification(
        response_expected="no",
        action_required="no",
        work_performed="no",
        waiting_for_others="no",
        review_required=False,
        evidence=[],
    )
    with db:
        assert not projects.schedule(db, iid, latest(db, iid), data)
        data.project_update_needed = "yes"
        assert not projects.schedule(
            db, iid, latest(db, iid), data
        )  # Missing link creates a candidate, not a job.
    assert db.execute(
        "SELECT 1 FROM project_unassigned WHERE inquiry_id=?", (iid,)
    ).fetchone()
    db.close()


def test_real_connection_has_evidence_validates_revision_and_never_creates_project(
    tmp_path,
):
    runtime, ids, pid, client = fixture(tmp_path)
    iid = ids["MAIL_REVIEW"]
    db = connect(runtime)
    version = latest(db, iid)
    page = client.get("/projects").text
    assert "기존 프로젝트 찾기" not in page
    assert "기존 프로젝트에 연결" in page and "선택한 프로젝트에 연결" in page
    assert "검토 이유" in page and "업무 변경 근거" in page
    assert "특정 프로젝트를 식별할 단서가 없습니다" in page
    assert "연결 단서: []" not in page
    bad = client.post(
        f"/api/projects/connect/{iid}", json=dict(project_id=99999, revision=version)
    )
    assert bad.status_code == 409
    assert db.execute("SELECT count(*) FROM projects").fetchone()[0] == 1
    assert (
        client.post(
            f"/api/projects/connect/{iid}",
            json=dict(project_id=pid, revision=version + 1),
        ).status_code
        == 409
    )
    result = client.post(
        f"/api/projects/connect/{iid}", json=dict(project_id=pid, revision=version)
    )
    assert result.status_code == 200
    assert result.json()["redirect"] == f"/projects/{pid}?view=review"
    assert (
        db.execute(
            "SELECT project_id FROM project_source_links WHERE inquiry_id=?", (iid,)
        ).fetchone()[0]
        == pid
    )
    assert not db.execute(
        "SELECT 1 FROM project_unassigned WHERE inquiry_id=?", (iid,)
    ).fetchone()
    assert db.execute(
        "SELECT 1 FROM jobs WHERE source_id=? AND kind='project_update' AND state='pending'",
        (iid,),
    ).fetchone()
    assert db.execute(
        "SELECT 1 FROM audit WHERE kind='project_link_existing' AND target=?", (iid,)
    ).fetchone()
    db.close()


def test_literal_project_codes_and_names_supply_hints(tmp_path):
    runtime, ids, _, _ = fixture(tmp_path)
    db = connect(runtime)
    iid = ids["MAIL_REVIEW"]
    with db:
        db.execute(
            "UPDATE sources SET body='JOB-042 Cell Library 일정 변경' WHERE id=?",
            (iid,),
        )
    signal = projects.connection_signal(db, iid)
    assert signal["eligible"]
    assert "JOB-042" in signal["hints"]
    assert "JOB-042 · Cell Library" in signal["hints"]
    db.close()
