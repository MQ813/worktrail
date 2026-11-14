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


class PathInput(Strict):
    path: str


class Entry(Strict):
    version: int
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

    @app.post("/api/projects")
    def create(data: Create):
        def run():
            db = connect(runtime)
            try:
                with db:
                    return projects.ensure_project(db, data.name, data.code)
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

    @app.post("/api/projects/import-folder")
    def import_folder(data: PathInput):
        return {"id": guarded(lambda: projects.import_folder(runtime, data.path))}

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
                    if not db.execute(
                        "UPDATE projects SET version=version+1 WHERE id=? AND version=?",
                        (pid, data.version),
                    ).rowcount:
                        raise ValueError("다른 변경이 있습니다. 새로고침하세요.")
                    db.execute(
                        "INSERT INTO project_entries(project_id,section,kind,text) VALUES(?,?,'progress',?)",
                        (pid, data.section, data.text),
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
        return {"ok": True}

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
    def index(activity: int = 0, inquiry: str = ""):
        rows = query(
            "SELECT p.*,(SELECT count(*) FROM project_changes c WHERE c.project_id=p.id AND c.review='pending') AS pending FROM projects p ORDER BY p.code"
        )
        body = '<h1 class="sr-only">프로젝트</h1>'
        body += '<section class="card"><h2>프로젝트 목록</h2>'
        if rows:
            body += (
                '<ul class="task-list">'
                + "".join(
                    f'<li><a href="/projects/{p["id"]}">{esc(p["code"])} · {esc(p["name"])}</a><span>미확정 {p["pending"]}건 · {esc(p["state"])}</span></li>'
                    for p in rows
                )
                + "</ul>"
            )
        else:
            body += '<p class="empty">프로젝트가 없습니다. 새 프로젝트를 만들거나 JOB 폴더를 가져오세요.</p>'
        body += '</section><details class="card spaced"><summary>새 프로젝트</summary><form data-project-api="/api/projects"><label>프로젝트 이름<input name="name" required maxlength="300"></label><button class="primary">프로젝트 만들기</button><p role="alert" class="form-feedback"></p></form></details>'
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
        unresolved = query(
            "SELECT u.*,s.subject FROM project_unassigned u JOIN sources s ON s.id=u.inquiry_id ORDER BY u.revision_id DESC"
        )
        body += f'<details class="card spaced"{" open" if unresolved else ""}><summary>프로젝트 연결이 필요한 변경 · {len(unresolved)}건</summary>'
        if not unresolved:
            body += (
                '<p class="empty empty-compact">연결을 기다리는 변경이 없습니다.</p>'
            )
        for u in unresolved:
            body += f'<article class="project-change"><a href="/inquiries/{esc(u["inquiry_id"])}">{esc(u["subject"])}</a><p>연결 단서: {esc(u["hints"])}</p></article>'
        opts = "".join(
            f'<option value="{esc(p["name"])}">{esc(p["code"])} · {esc(p["name"])}</option>'
            for p in rows
        )
        body += f'</details><details class="card spaced"{" open" if inquiry else ""}><summary>메일·Jira를 프로젝트에 연결</summary><form id="project-form"><label>관련 문의<select name="inquiry_id" required>'
        body += "".join(
            f'<option value="{esc(i["id"])}" {"selected" if i["id"] == inquiry else ""}>{esc(i["subject"])}</option>'
            for i in query(
                "SELECT s.id,s.subject FROM inquiries i JOIN sources s ON s.id=i.id"
            )
        )
        body += f'</select></label><label>프로젝트<select name="project" required>{opts}</select></label><button>연결하고 업데이트 생성</button></form></details>'
        body += '<details class="card spaced"><summary>기존 JOB 폴더 가져오기</summary><form data-project-api="/api/projects/import-folder"><label>프로젝트 폴더 전체 경로<input name="path" required placeholder="D:\\worklog\\JOB-006"></label><button>원본 보존 후 가져오기</button><p role="alert" class="form-feedback"></p></form></details>'
        return page(body, "projects")

    @app.get("/projects/{pid}")
    def detail(
        pid: int, work_item: int = 0, on: str = "", edit: int = 0, inquiry: str = ""
    ):
        ps = query("SELECT * FROM projects WHERE id=?", (pid,))
        if not ps:
            raise HTTPException(404, "프로젝트 없음")
        p = ps[0]
        changes = query(
            "SELECT * FROM project_changes WHERE project_id=? AND review='pending' ORDER BY id DESC",
            (pid,),
        )
        body = f'<header class="project-heading"><h1>{esc(p["code"])} · {esc(p["name"])}</h1><span class="muted">미확정 {len(changes)}건</span><a href="#record-editor">수행 기록 추가</a></header>'
        jobs = query(
            "SELECT state,error FROM jobs WHERE kind='project_update' AND source_id IN (SELECT inquiry_id FROM project_source_links WHERE project_id=? UNION SELECT inquiry_id FROM inquiry_projects WHERE project_id=?) ORDER BY id DESC LIMIT 1",
            (pid, pid),
        )
        if jobs:
            labels = {
                "pending": "대기",
                "running": "생성 중",
                "retry_wait": "재시도 대기",
                "failed": "실패",
                "succeeded": "완료",
                "cancelled": "취소",
            }
            body += f'<p role="status">최근 업데이트 작업: {esc(labels.get(jobs[0]["state"], jobs[0]["state"]))} {esc(jobs[0]["error"] or "")} · <a href="/projects/{pid}">결과 새로고침</a></p>'
        body += f'<div class="toolbar"><a class="button" href="/api/projects/{pid}/export">Markdown 내보내기</a><a class="button" href="/api/projects/{pid}/archive">JOB 폴더 ZIP</a><a class="button" href="/api/projects/{pid}/export?pending=false">확정본 내보내기</a><button data-command="/api/projects/{pid}/regenerate">최신 내용으로 다시 생성</button><a href="/operations">처리 상태·실패 확인</a></div>'
        body += f'<section class="card"><div class="project-summary"><span>{esc(p["owner"] or "담당자 미지정")}</span><span>{esc(p["state"])}</span><span>{esc(p["purpose"])}</span></div><details><summary>프로젝트 개요 수정</summary>'
        body += f'<form data-project-api="/api/projects/{pid}" data-method="PUT" data-version="{p["version"]}"><div class="form-grid">'
        for name, label in (
            ("purpose", "목적"),
            ("owner", "담당자"),
            ("state", "상태"),
            ("started_on", "시작일"),
        ):
            input_type = "date" if name == "started_on" else "text"
            body += f'<label>{label}<input type="{input_type}" name="{name}" value="{esc(p[name])}"></label>'
        body += '</div><button>개요 저장</button><p role="alert" class="form-feedback"></p></form></details></section>'
        entries = query(
            "SELECT * FROM project_entries WHERE project_id=? AND deleted=0 ORDER BY id",
            (pid,),
        )
        for section, title in projects.SECTIONS.items():
            relevant = [
                c
                for c in changes
                if json.loads(c["payload"])["section"] == section
                and (
                    not work_item
                    or json.loads(c["payload"]).get("work_item_id") == work_item
                )
            ]
            confirmed = [
                e
                for e in entries
                if e["section"] == section
                and (not work_item or e["work_item_id"] == work_item)
            ]
            if not relevant and not confirmed:
                continue
            body += f'<section class="card spaced"><h2>{title}{" · 변경 " + str(len(relevant)) + "건" if relevant else ""}</h2>'
            for e in confirmed:
                body += f'<article class="project-entry"><span class="badge">확정</span><p class="project-text">{esc(e["text"])}</p></article>'
                body += f'<details><summary>확정 내용 수정</summary><form data-project-api="/api/projects/{pid}/entries/{e["id"]}" data-method="PUT" data-version="{p["version"]}"><input type="hidden" name="section" value="{esc(e["section"])}"><label>내용<textarea name="text" required maxlength="5000">{esc(e["text"])}</textarea></label><button>수정 저장</button><p role="alert" class="form-feedback"></p></form></details>'
            for c in relevant:
                payload = json.loads(c["payload"])
                fresh = (
                    "검토 가능"
                    if c["freshness"] == "current"
                    else "재검토 필요 · " + c["freshness"]
                )
                body += f'<article class="project-change" data-change-id="{c["id"]}"><div class="section-heading"><h3>AI {esc({"add": "추가", "update": "수정", "delete": "삭제"}.get(payload["operation"], payload["operation"]))} · 미확정 #{c["id"]}</h3><span>{esc(fresh)}</span></div>'
                if payload.get("_history_basis"):
                    body += f'<p class="badge">과거 수집 이력 재구성 · revision {c["revision_id"]}</p>'
                if c["before_text"]:
                    body += f'<p>기존 확정 내용</p><blockquote class="project-text">{esc(c["before_text"])}</blockquote>'
                body += f'<label>변경 제안 · 수정 후 확정 가능<textarea class="project-proposal" maxlength="5000">{esc(payload["text"])}</textarea></label><p>{esc(payload.get("reason", ""))}</p>'
                body += "<details><summary>근거 확인</summary>"
                if c["inquiry_id"]:
                    body += f'<a href="/inquiries/{esc(c["inquiry_id"])}">메일·Jira 원문 · revision {c["revision_id"]}</a>'
                for evidence in payload["evidence"]:
                    body += f'<blockquote class="project-text">{esc(evidence["text"])}</blockquote>'
                body += '</details><div class="toolbar">'
                disabled = " disabled" if c["freshness"] != "current" else ""
                body += f'<label><input type="checkbox" class="project-select" value="{c["id"]}"{disabled}> 묶음 검토에 선택</label><button class="primary" data-project-review="confirmed"{disabled}>확정 / 수정 후 확정</button><button data-project-review="rejected">반려</button></div><p role="alert" class="form-feedback"></p></article>'
            if not relevant and not confirmed:
                body += (
                    '<p class="empty empty-compact">아직 기록한 내용이 없습니다.</p>'
                )
            body += "</section>"
        if changes:
            body += '<div class="toolbar spaced"><button data-project-batch="confirmed">선택한 변경 확정</button><button data-project-batch="rejected">선택한 변경 반려</button><p role="alert" id="project-review-feedback"></p></div>'
        body += f'<details class="card spaced"><summary>업무 직접 기록</summary><form data-project-api="/api/projects/{pid}/entries" data-version="{p["version"]}"><label>기록 구역<select name="section">'
        body += "".join(
            f'<option value="{k}">{v}</option>' for k, v in projects.SECTIONS.items()
        )
        body += '</select></label><label>내용<textarea name="text" required maxlength="5000"></textarea></label><button>사람 작성으로 저장</button><p role="alert" class="form-feedback"></p></form></details>'
        work_items = query(
            "SELECT * FROM project_work_items WHERE project_id=?", (pid,)
        )
        body += '<section class="card spaced"><h2>업무 항목</h2>'
        for w in work_items:
            body += f'<p><a href="/projects/{pid}?work_item={w["id"]}">#{w["id"]} · {esc(w["title"])}</a> · {"상세 문서 생성" if w["detail"] else "index에서 관리"}</p>'
        body += f'<form data-project-api="/api/projects/{pid}/work-items" data-version="{p["version"]}"><label>업무 제목<input name="title" required maxlength="300"></label><label><input type="checkbox" name="detail"> 별도 이슈 문서 생성</label><button>업무 추가 / 문서 설정 변경</button><p class="muted">기존 업무 제목을 입력하면 상세 문서 설정을 변경합니다.</p><p role="alert" class="form-feedback"></p></form></section>'
        body += render_records(pid, on, edit, inquiry)
        body += '<section class="card spaced"><h2>관련 메일·Jira</h2>'
        for i in query(
            "SELECT DISTINCT s.id,s.subject FROM sources s WHERE s.id IN (SELECT inquiry_id FROM project_source_links WHERE project_id=? UNION SELECT inquiry_id FROM inquiry_projects WHERE project_id=?)",
            (pid, pid),
        ):
            body += (
                f'<p><a href="/inquiries/{esc(i["id"])}">{esc(i["subject"])}</a></p>'
            )
            body += f'<button data-command="/api/projects/{pid}/unlink" data-payload="{esc(json.dumps({"inquiry_id": i["id"]}))}" data-reload="true">이 프로젝트에서 연결 해제</button>'
        body += '</section><details class="card spaced"><summary>검토 이력</summary>'
        for r in query(
            "SELECT r.* FROM project_reviews r JOIN project_changes c ON c.id=r.change_id WHERE c.project_id=? ORDER BY r.id DESC LIMIT 100",
            (pid,),
        ):
            body += f"<p>변경 #{r['change_id']} · {esc(r['decision'])} · {esc(json.loads(r['payload'])['text'])}</p>"
        body += "</details>"
        body += f'<details class="card spaced"><summary>기간을 지정해 기존 이력 재구성</summary><form data-project-api="/api/projects/{pid}/replay-history"><label>수집 시작일<input type="date" name="start" required></label><label>수집 종료일<input type="date" name="end" required></label><p>한국 시간 기준 수집 이력을 최대 500건 처리합니다. 과거 상태가 현재와 다를 수 있어 결과는 미확정으로 표시합니다.</p><button>이력 재구성 요청</button><p role="alert" class="form-feedback"></p></form></details>'
        body += f'<details class="card spaced"><summary>외부 문서 수정 가져오기</summary><form data-project-api="/api/projects/{pid}/import-document"><label>Markdown 전체 경로<input name="path" required></label><p>원본을 보존하고 변경 내용을 추가 후보로 가져옵니다. 기존 내용의 대체·삭제는 직접 확인하세요.</p><button>변경 후보 가져오기</button><p role="alert" class="form-feedback"></p></form></details>'
        return page(body, "projects")
