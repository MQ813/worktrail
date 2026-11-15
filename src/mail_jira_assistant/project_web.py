"""Project-centered worklog pages and review endpoints."""

import json
from typing import Literal

from fastapi import HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from . import project_updates as projects
from .storage import connect


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Create(Strict):
    name: str = Field(min_length=1, max_length=300)
    code: str | None = None
    purpose: str = Field(default="", max_length=5000)
    owner: str = Field(default="", max_length=300)
    process: str = Field(default="TBD", max_length=300)
    development_target: str = Field(default="TBD", max_length=300)
    target_on: str = "TBD"
    started_on: str = ""
    spec: str = Field(default="TBD", max_length=5000)


class Selection(Strict):
    id: int
    decision: Literal["confirmed", "rejected"]
    text: str | None = Field(default=None, min_length=1, max_length=5000)


class Review(Strict):
    selections: list[Selection] = Field(min_length=1, max_length=100)


class Metadata(Strict):
    version: int
    purpose: str = Field(max_length=5000)
    owner: str = Field(max_length=300)
    state: str = Field(max_length=100)
    started_on: str = ""
    target_on: str = "TBD"
    spec: str = "TBD"
    process: str = "TBD"
    development_target: str = "TBD"


class PathInput(Strict):
    path: str


class Entry(Strict):
    version: int
    work_item_id: int | None = None
    section: Literal[
        "overview", "progress", "issues", "decisions", "updates", "next_actions"
    ]
    text: str = Field(min_length=1, max_length=5000)


class WorkItem(Strict):
    title: str = Field(min_length=1, max_length=300)
    detail: bool = False
    version: int


class Unlink(Strict):
    inquiry_id: str


class ExistingLink(Strict):
    project_id: int = Field(gt=0)
    revision: int = Field(gt=0)


class HistoryReplay(Strict):
    start: str
    end: str


class AssignActivity(Strict):
    project_id: int
    version: int


def attach(app, runtime, page, esc, render_records):
    def query(sql, args=()):
        db = connect(runtime)
        try:
            return [dict(r) for r in db.execute(sql, args)]
        finally:
            db.close()

    def guarded(fn):
        import sqlite3

        try:
            return fn()
        except (ValueError, OSError, LookupError, sqlite3.IntegrityError) as exc:
            raise HTTPException(409, str(exc)) from exc

    from . import project_ai_web

    project_ai_web.attach(app, runtime, guarded)

    @app.post("/api/projects/connect/{iid}")
    def connect_existing(iid: str, data: ExistingLink):
        guarded(
            lambda: projects.link_existing(runtime, iid, data.project_id, data.revision)
        )
        return {
            "redirect": f"/projects/{data.project_id}?view=review",
            "message": "선택한 프로젝트에 연결했습니다. 업데이트 생성 요청을 등록했습니다.",
        }

    @app.post("/api/projects")
    def create(data: Create):
        def run():
            db = connect(runtime)
            try:
                with db:
                    if not data.name.strip():
                        raise ValueError("프로젝트 이름을 입력하세요.")
                    if db.execute(
                        "SELECT 1 FROM projects WHERE name=?", (data.name.strip(),)
                    ).fetchone():
                        raise ValueError(
                            "같은 이름의 프로젝트가 있습니다. 목록에서 기존 프로젝트를 확인하세요."
                        )
                    from datetime import date

                    for value in (data.target_on, data.started_on):
                        if value not in ("", "TBD"):
                            date.fromisoformat(value)
                    pid = projects.ensure_project(db, data.name.strip(), data.code)
                    for field in (
                        "purpose",
                        "owner",
                        "process",
                        "development_target",
                        "target_on",
                        "started_on",
                        "spec",
                    ):
                        db.execute(
                            f"UPDATE projects SET {field}=? WHERE id=?",
                            (getattr(data, field), pid),
                        )
                    db.execute(
                        "INSERT INTO audit(kind,target,detail,created) VALUES('project_manual_create',?,?,strftime('%s','now'))",
                        (str(pid), data.model_dump_json()),
                    )
                    return pid
            finally:
                db.close()

        return {"id": guarded(run)}

    @app.post("/api/projects/review")
    def review(data: Review):
        guarded(
            lambda: projects.review(runtime, [s.model_dump() for s in data.selections])
        )
        return {"ok": True}

    @app.post("/api/activities/{aid}/assign-project")
    def assign_activity(aid: int, data: AssignActivity):
        from . import worklog

        record = next((r for r in worklog.records(runtime) if r["id"] == aid), None)
        ps = query("SELECT name FROM projects WHERE id=?", (data.project_id,))
        if not record or not ps:
            raise HTTPException(404, "기록 또는 프로젝트 없음")
        guarded(
            lambda: worklog.save(
                runtime,
                {**record, "project": ps[0]["name"], "version": data.version},
                aid,
            )
        )
        return {
            "id": data.project_id,
            "redirect": f"/projects/{data.project_id}?edit={aid}#record-editor",
        }

    @app.put("/api/projects/{pid}")
    def edit(pid: int, data: Metadata):
        guarded(lambda: projects.edit_project(runtime, pid, data.model_dump()))
        return {"ok": True}

    @app.post("/api/projects/{pid}/import-document")
    def import_document(pid: int, data: PathInput):
        guarded(lambda: projects.import_document(runtime, pid, data.path))
        return {"ok": True}

    @app.post("/api/projects/{pid}/replay-history")
    def replay(pid: int, data: HistoryReplay):
        return {
            "queued": guarded(
                lambda: projects.replay_history(runtime, pid, data.start, data.end)
            )
        }

    @app.post("/api/projects/{pid}/entries")
    def entry(pid: int, data: Entry):
        def run():
            db = connect(runtime)
            try:
                with db:
                    if (
                        data.work_item_id
                        and not db.execute(
                            "SELECT 1 FROM project_work_items WHERE id=? AND project_id=?",
                            (data.work_item_id, pid),
                        ).fetchone()
                    ):
                        raise ValueError("이 프로젝트의 하위 이슈가 아닙니다.")
                    if not db.execute(
                        "UPDATE projects SET version=version+1 WHERE id=? AND version=?",
                        (pid, data.version),
                    ).rowcount:
                        raise ValueError("다른 변경이 있습니다. 새로고침하세요.")
                    db.execute(
                        "INSERT INTO project_entries(project_id,work_item_id,section,kind,text) VALUES(?,?,?,'progress',?)",
                        (pid, data.work_item_id, data.section, data.text),
                    )
                    db.execute(
                        "UPDATE project_changes SET freshness='stale' WHERE project_id=? AND review='pending'",
                        (pid,),
                    )
                    db.execute(
                        "INSERT INTO audit(kind,target,detail,created) VALUES('project_manual_entry',?,?,strftime('%s','now'))",
                        (str(pid), data.model_dump_json()),
                    )
            finally:
                db.close()

        guarded(run)
        return {"ok": True}

    @app.post("/api/projects/{pid}/work-items")
    def work_item(pid: int, data: WorkItem):
        def run():
            db = connect(runtime)
            try:
                with db:
                    if not db.execute(
                        "UPDATE projects SET version=version+1 WHERE id=? AND version=?",
                        (pid, data.version),
                    ).rowcount:
                        raise ValueError("다른 변경이 있습니다. 새로고침하세요.")
                    db.execute(
                        "INSERT INTO project_work_items(project_id,title,detail) VALUES(?,?,?) ON CONFLICT(project_id,title) DO UPDATE SET detail=excluded.detail",
                        (pid, data.title, data.detail),
                    )
                    db.execute(
                        "UPDATE project_changes SET freshness='stale' WHERE project_id=? AND review='pending'",
                        (pid,),
                    )
            finally:
                db.close()

        guarded(run)
        wid = query(
            "SELECT id FROM project_work_items WHERE project_id=? AND title=?",
            (pid, data.title),
        )[0]["id"]
        return {"redirect": f"/projects/{pid}?view=issues&work_item={wid}"}

    @app.put("/api/projects/{pid}/entries/{eid}")
    def edit_entry(pid: int, eid: int, data: Entry):
        def run():
            db = connect(runtime)
            try:
                with db:
                    old = db.execute(
                        "SELECT * FROM project_entries WHERE id=? AND project_id=? AND deleted=0",
                        (eid, pid),
                    ).fetchone()
                    if (
                        not old
                        or not db.execute(
                            "UPDATE projects SET version=version+1 WHERE id=? AND version=?",
                            (pid, data.version),
                        ).rowcount
                    ):
                        raise ValueError("다른 변경이 있습니다. 새로고침하세요.")
                    db.execute(
                        "UPDATE project_entries SET text=?,section=?,version=version+1 WHERE id=?",
                        (data.text, data.section, eid),
                    )
                    db.execute(
                        "UPDATE project_changes SET freshness='stale' WHERE project_id=? AND review='pending'",
                        (pid,),
                    )
                    db.execute(
                        "INSERT INTO audit(kind,target,detail,created) VALUES('project_entry_edit',?,?,strftime('%s','now'))",
                        (
                            str(eid),
                            json.dumps(
                                {"before": dict(old), "after": data.model_dump()},
                                ensure_ascii=False,
                            ),
                        ),
                    )
            finally:
                db.close()

        guarded(run)
        return {"ok": True}

    @app.post("/api/projects/{pid}/regenerate")
    def regenerate(pid: int):
        from .service import latest

        def run():
            db = connect(runtime)
            try:
                with db:
                    ids = [
                        r[0]
                        for r in db.execute(
                            "SELECT inquiry_id FROM project_source_links WHERE project_id=? UNION SELECT inquiry_id FROM inquiry_projects WHERE project_id=?",
                            (pid, pid),
                        )
                    ]
                    for iid in ids:
                        projects.schedule(db, iid, latest(db, iid), force=True)
                    return len(ids) + projects.refresh_imports(db, pid)
            finally:
                db.close()

        return {"queued": guarded(run)}

    @app.get("/api/projects/{pid}/export")
    def export(pid: int, pending: bool = True):
        path = guarded(lambda: projects.export(runtime, pid, pending=pending))
        return FileResponse(
            path,
            filename=path.parent.name + "-index.md",
            media_type="text/markdown; charset=utf-8",
        )

    @app.post("/api/projects/{pid}/unlink")
    def unlink(pid: int, data: Unlink):
        guarded(lambda: projects.unlink(runtime, data.inquiry_id, pid))
        return {"ok": True}

    @app.get("/api/projects/{pid}/changes")
    def changes(pid: int):
        return query(
            "SELECT * FROM project_changes WHERE project_id=? ORDER BY id DESC", (pid,)
        )

    @app.get("/api/projects/{pid}/archive")
    def archive(pid: int, pending: bool = True):
        import zipfile
        from pathlib import Path

        index = guarded(lambda: projects.export(runtime, pid, pending=pending))
        target = Path(runtime) / "exports" / (index.parent.name + ".zip")
        target.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in index.parent.rglob("*"):
                if path.is_file() and path.resolve().is_relative_to(
                    index.parent.resolve()
                ):
                    archive.write(path, path.relative_to(index.parent.parent))
        return FileResponse(target, filename=target.name, media_type="application/zip")

    @app.get("/api/projects/{pid}/history")
    def history(pid: int):
        return query(
            "SELECT r.* FROM project_reviews r JOIN project_changes c ON c.id=r.change_id WHERE c.project_id=? ORDER BY r.id DESC",
            (pid,),
        )

    @app.get("/projects")
    def index(
        activity: int = 0,
        inquiry: str = "",
        q: str = "",
        attention: str = "",
        project_id: int = 0,
        tab: str = "",
        state: str = "",
    ):
        from . import project_directory as directory
        from .project_views import index_table

        tab = tab or ("connections" if activity or inquiry or project_id else "list")
        if tab not in ("list", "connections", "new", "ai", "history"):
            raise HTTPException(404, "프로젝트 화면이 없습니다.")
        rows = query(
            "SELECT p.*,(SELECT count(*) FROM project_work_items w WHERE w.project_id=p.id) AS issue_count,(SELECT count(*) FROM project_changes c WHERE c.project_id=p.id AND c.review='pending') AS pending,(SELECT count(*) FROM project_ai_history h WHERE h.project_id=p.id AND h.confirmed=0 AND h.reverted=0) AS unconfirmed FROM projects p ORDER BY p.code"
        )
        db = connect(runtime)
        try:
            unresolved = projects.unassigned_candidates(db)
        finally:
            db.close()
        body = '<div class="project-directory-screen">' + directory.header(
            tab, len(unresolved)
        )
        if tab == "list":
            body += index_table(rows, esc, q, attention, state)
        elif tab == "new":
            body += directory.create_form()
        elif tab == "ai":
            body += directory.ai_workspace(query, esc, inquiry, project_id)
        elif tab == "history":
            body += directory.request_history(query, esc)
        else:
            from . import worklog

            unassigned = [
                r for r in worklog.records(runtime) if r["resolved_project_id"] is None
            ]
            if unassigned:
                body += '<section class="card spaced" id="unassigned-records"><h2>프로젝트 연결이 필요한 수행 기록</h2>'
                for r in unassigned:
                    options = "".join(
                        f'<option value="{p["id"]}">{esc(p["code"])} · {esc(p["name"])}</option>'
                        for p in rows
                    )
                    body += f'<form data-project-api="/api/activities/{r["id"]}/assign-project" data-version="{r["version"]}"><p>{esc(r["description"])}</p><label>연결할 프로젝트<select name="project_id" required><option value="">프로젝트 선택</option>{options}</select></label><button>프로젝트에 연결</button><p role="alert" class="form-feedback"></p></form>'
                body += "</section>"
            db = connect(runtime)
            try:
                unresolved = projects.unassigned_candidates(db)
            finally:
                db.close()
            body += f'<details class="card spaced" id="project-connections"{" open" if unresolved else ""}><summary>프로젝트 연결 검토 · {len(unresolved)}건</summary>'
            if not unresolved:
                body += '<p class="empty empty-compact">프로젝트 연결을 검토할 문의가 없습니다.</p>'
            for u in unresolved:
                body += f'<article class="project-candidate"><h3><a class="text-link" href="/inquiries/{esc(u["inquiry_id"])}">{esc(u["subject"])}</a></h3><p class="candidate-reason">검토 이유 · {esc(u["reason"])}</p>'
                if u["evidence"]:
                    body += f'<details class="candidate-evidence"><summary>업무 변경 근거</summary><blockquote class="project-text">{esc(u["evidence"])}</blockquote></details>'
                body += (
                    f'<p class="muted">연결 단서 · {esc(" · ".join(u["hints"]))}</p>'
                    if u["hints"]
                    else '<p class="muted">특정 프로젝트를 식별할 단서가 없습니다. 원문을 확인해 연결할 프로젝트를 선택하세요.</p>'
                )
                body += f'<div class="toolbar"><a class="button" href="/projects?tab=ai&amp;inquiry={esc(u["inquiry_id"])}">AI로 프로젝트 찾기·정리</a><button data-command="/api/project-ai/dismiss/{esc(u["inquiry_id"])}" data-reload="true">프로젝트 관리 대상 아님</button></div><p role="status" class="form-feedback"></p>'
                body += '<details class="candidate-link"><summary>기존 프로젝트에 연결</summary>'
                if rows:
                    options = "".join(
                        f'<option value="{p["id"]}">{esc(p["code"])} · {esc(p["name"])}</option>'
                        for p in rows
                    )
                    body += f'<form data-project-api="/api/projects/connect/{esc(u["inquiry_id"])}"><input type="hidden" name="revision" value="{u["revision_id"]}"><label>연결할 프로젝트<select name="project_id" required><option value="">프로젝트를 선택하세요</option>{options}</select></label><p class="muted">선택한 프로젝트에 연결한 뒤 업데이트 생성을 요청합니다. 결과는 프로젝트의 변경 검토에서 확인합니다.</p><button>선택한 프로젝트에 연결</button><p role="status" class="form-feedback"></p></form>'
                else:
                    body += '<p class="muted">아직 연결할 프로젝트가 없습니다. 먼저 프로젝트를 추가하세요.</p><a class="text-link" href="/projects?tab=new">프로젝트 추가 →</a>'
                body += "</details></article>"
            opts = "".join(
                f'<option value="{esc(p["name"])}"{" selected" if p["id"] == project_id else ""}>{esc(p["code"])} · {esc(p["name"])}</option>'
                for p in rows
            )
            body += f'</details><details class="card spaced"{" open" if inquiry or project_id else ""}><summary>메일·Jira를 프로젝트에 연결</summary><form id="project-form"><label>관련 문의<select name="inquiry_id" required>'
            body += "".join(
                f'<option value="{esc(i["id"])}" {"selected" if i["id"] == inquiry else ""}>{esc(i["subject"])}</option>'
                for i in query(
                    "SELECT s.id,s.subject FROM inquiries i JOIN sources s ON s.id=i.id"
                )
            )
            body += f'</select></label><label>프로젝트<select name="project" required>{opts}</select></label><button>연결하고 업데이트 생성</button></form></details>'
        return page(body + "</div>", "projects")

    @app.get("/projects/{pid}")
    def detail(
        pid: int,
        work_item: int = 0,
        on: str = "",
        edit: int = 0,
        inquiry: str = "",
        view: str = "",
        q: str = "",
        issue_page: int = 1,
    ):
        from .project_views import Workspace

        ps = query("SELECT * FROM projects WHERE id=?", (pid,))
        if not ps:
            raise HTTPException(404, "프로젝트 없음")
        entries = query(
            "SELECT * FROM project_entries WHERE project_id=? AND deleted=0 ORDER BY id",
            (pid,),
        )
        changes = query(
            "SELECT * FROM project_changes WHERE project_id=? AND review='pending' ORDER BY id DESC",
            (pid,),
        )
        items = query(
            "SELECT * FROM project_work_items WHERE project_id=? ORDER BY id", (pid,)
        )
        item = next((w for w in items if w["id"] == work_item), None)
        if work_item and not item:
            raise HTTPException(404, "이 프로젝트의 하위 이슈가 아닙니다.")
        view = view or (
            "issues"
            if work_item
            else "records"
            if on or edit or inquiry
            else "overview"
        )
        if view not in ("overview", "issues", "records", "review", "settings"):
            raise HTTPException(404, "프로젝트 화면 없음")
        workspace = Workspace(query, esc, ps[0], entries, changes, items)
        body = '<div class="project-workspace">' + workspace.header(
            view, item if view == "issues" else None
        )
        if view == "overview":
            body += workspace.overview()
        elif view == "issues":
            body += workspace.issues(item, q, issue_page)
        elif view == "records":
            body += render_records(pid, on, edit, inquiry)
        elif view == "review":
            body += workspace.review()
        else:
            body += workspace.settings()
        return page(body + "</div>", "projects")
