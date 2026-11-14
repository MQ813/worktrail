"""WorkTrail pages extend the existing local workspace."""

from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

from . import worklog
from .storage import connect


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str = Field(min_length=1, max_length=100000)
    performed_on: str | None = None
    project: str = Field(default="", max_length=300)
    inquiry_id: str | None = None
    action_id: int | None = None
    status: Literal["needs_review", "confirmed", "excluded"] = "needs_review"
    version: int = 1
    duplicate_of: int | None = None
    minutes: int | None = Field(default=None, ge=0, le=1440)
    complete_action: bool = False


class Import(BaseModel):
    path: str
    performed_on: str
    project: str = ""


class ProjectLink(BaseModel):
    inquiry_id: str
    project: str = Field(max_length=300)


def attach(app, runtime, page, esc, inquiries):
    def query(sql, args=()):
        db = connect(runtime)
        try:
            return [dict(r) for r in db.execute(sql, args)]
        finally:
            db.close()

    def guarded(fn):
        try:
            return fn()
        except (ValueError, OSError, LookupError) as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/activities")
    def activities():
        return worklog.records(runtime)

    @app.post("/api/activities")
    def add(data: Record):
        return {"id": guarded(lambda: worklog.save(runtime, data.model_dump()))}

    @app.put("/api/activities/{aid}")
    def edit(aid: int, data: Record):
        return {"id": guarded(lambda: worklog.save(runtime, data.model_dump(), aid))}

    @app.get("/api/activities/{aid}/history")
    def history(aid: int):
        return {
            "edits": query("SELECT * FROM activity_edits WHERE activity_id=?", (aid,)),
            "evidence": query(
                "SELECT * FROM activity_evidence WHERE activity_id=? OR activity_id IN (SELECT id FROM activities WHERE duplicate_of=?)",
                (aid, aid),
            ),
        }

    @app.get("/api/worklog/{on}/export")
    def download(on: str):
        path = guarded(lambda: worklog.export(runtime, on))
        return FileResponse(
            path, filename=on + ".md", media_type="text/markdown; charset=utf-8"
        )

    @app.post("/api/worklog/import")
    def import_file(data: Import):
        guarded(
            lambda: worklog.import_markdown(
                runtime, data.path, data.performed_on, data.project
            )
        )
        return {"ok": True}

    @app.post("/api/projects/link")
    def link(data: ProjectLink):
        from .project_updates import link

        return {
            "ok": True,
            "id": guarded(lambda: link(runtime, data.inquiry_id, data.project)),
        }

    def render_record(r, show_project=True):
        status = {
            "needs_review": "확인 필요",
            "confirmed": "수행 확정",
            "excluded": "집계 제외",
        }.get(r["status"], r["status"])
        evidence = (
            f'<a href="/inquiries/{esc(r["inquiry_id"])}">문의·원문</a>'
            if r["inquiry_id"]
            else '<span class="muted">수동 기록</span>'
        )
        project_cell = f"<td>{esc(r['project'])}</td>" if show_project else ""
        return (
            f"<tr><td>{esc(r['performed_on'] or '수행일 확인 필요')}</td>{project_cell}"
            f'<td><a href="{record_url(r)}">{esc(r["description"][:200])}</a></td>'
            f"<td>{esc(status)}{(' · 중복 #' + str(r['duplicate_of'])) if r['duplicate_of'] else ''}</td>"
            f"<td>{evidence}</td></tr>"
        )

    def record_url(r):
        if r.get("resolved_project_id"):
            return f"/projects/{r['resolved_project_id']}?edit={r['id']}#record-editor"
        return f"/projects?activity={r['id']}#unassigned-records"

    @app.get("/today")
    def today():
        on = datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()
        body = '<h1 class="sr-only">오늘</h1><div class="daily-grid">'
        panels = []
        for state, title in [
            ("open", "내 할 일"),
            ("proposed", "확인할 할 일·수행 제안"),
            ("waiting", "상대 회신 대기"),
        ]:
            tasks = query(
                "SELECT a.*,s.subject FROM actions a LEFT JOIN sources s ON s.id=a.inquiry_id WHERE a.state=? ORDER BY a.id DESC",
                (state,),
            )
            panel = f'<section class="card"><div class="section-heading"><h2>{title}</h2><span>{len(tasks)}건</span></div>'
            if tasks:
                panel += (
                    '<ul class="task-list">'
                    + "".join(
                        f'<li><a href="/inquiries/{esc(a["inquiry_id"])}">{esc(a["subject"] or a["description"])}</a><details class="task-detail"><summary>할 일 내용</summary><p>{esc(a["description"])}</p></details></li>'
                        for a in tasks
                    )
                    + "</ul>"
                )
            else:
                panel += (
                    '<p class="empty empty-compact">'
                    + {
                        "open": "등록된 할 일이 없습니다.",
                        "proposed": "확인할 제안이 없습니다.",
                        "waiting": "회신을 기다리는 할 일이 없습니다.",
                    }[state]
                    + "</p>"
                )
            panels.append(panel + "</section>")
        replies = [
            r
            for r in inquiries()
            if (r.get("effective_classification") or {}).get("response_expected")
            == "yes"
        ]
        reply_panel = f'<section class="card"><div class="section-heading"><h2>답변 필요</h2><span>{len(replies)}건</span></div>'
        reply_panel += (
            (
                '<ul class="task-list">'
                + "".join(
                    f'<li><a href="/inquiries/{esc(r["id"])}">{esc(r["subject"])}</a></li>'
                    for r in replies
                )
                + "</ul>"
            )
            if replies
            else '<p class="empty empty-compact">답변이 필요한 문의가 없습니다.</p>'
        )
        body += (
            '<div class="stack">'
            + panels[0]
            + panels[2]
            + reply_panel
            + '</section></div><div class="stack">'
            + panels[1]
            + '</div></div><section class="card spaced"><div class="section-heading"><h2>오늘 수행 기록</h2><a class="button" href="/projects">프로젝트에서 기록</a></div>'
        )
        records = [r for r in activities() if r["performed_on"] == on]
        body += (
            '<div class="scroll"><table><thead><tr><th>수행일</th><th>프로젝트</th><th>내용</th><th>상태</th><th>근거</th></tr></thead><tbody>'
            + "".join(render_record(r) for r in records)
            + "</tbody></table></div>"
            if records
            else '<p class="empty empty-compact">오늘 확정한 수행 기록이 없습니다.</p>'
        )
        body += "</section>"
        pending = query(
            "SELECT c.id,c.project_id,c.payload,p.code,p.name FROM project_changes c JOIN projects p ON p.id=c.project_id WHERE c.review='pending' ORDER BY c.id DESC LIMIT 30"
        )
        body += '<section class="card spaced"><h2>프로젝트 AI 제안 · 미확정</h2>'
        import json

        for c in pending:
            body += f'<p><a href="/projects/{c["project_id"]}">{esc(c["code"])} · {esc(c["name"])}</a> · {esc(json.loads(c["payload"])["text"][:200])}</p>'
        if not pending:
            body += '<p class="empty empty-compact">확인을 기다리는 프로젝트 변경이 없습니다.</p>'
        body += "</section>"
        return page(body, "today")

    @app.get("/worklog")
    def log(on: str = "", edit: int = 0, inquiry: str = ""):
        from urllib.parse import urlencode

        record = next((r for r in activities() if r["id"] == edit), None)
        pid = record.get("resolved_project_id") if record else None
        if not pid and inquiry:
            links = query(
                "SELECT project_id FROM inquiry_projects WHERE inquiry_id=? UNION SELECT project_id FROM project_source_links WHERE inquiry_id=?",
                (inquiry, inquiry),
            )
            pid = links[0]["project_id"] if links else None
        args = {
            k: v for k, v in {"on": on, "edit": edit, "inquiry": inquiry}.items() if v
        }
        if pid:
            target = f"/projects/{pid}"
        else:
            target = "/projects"
            if edit:
                args = {"activity": edit}
        return RedirectResponse(
            target
            + ("?" + urlencode(args) if args else "")
            + ("#record-editor" if pid else ""),
            status_code=303,
        )

    def render_project_records(pid, on="", edit=0, inquiry=""):
        on = on or datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()
        project = query("SELECT * FROM projects WHERE id=?", (pid,))[0]
        all_rows = [r for r in activities() if r["resolved_project_id"] == pid]
        r = next((r for r in all_rows if r["id"] == edit), {})
        if edit and not r:
            raise HTTPException(404, "이 프로젝트의 수행 기록이 아닙니다.")
        if not r and inquiry:
            r = {"inquiry_id": inquiry}
        body = '<section class="card spaced" id="project-records"><div class="section-heading"><h2>수행 기록</h2><a href="#record-editor">수행 기록 추가</a></div>'
        body += f'<form class="toolbar" method="get" action="/projects/{pid}#project-records"><label>수행일<input type="date" name="on" value="{esc(on)}"></label><button>날짜 보기</button></form>'
        body += '<div class="scroll"><table><thead><tr><th>수행일</th><th>내용</th><th>상태</th><th>근거</th></tr></thead><tbody>'
        body += (
            "".join(
                render_record(x, False)
                for x in all_rows
                if x["performed_on"] == on or x["status"] == "needs_review"
            )
            + "</tbody></table></div>"
            + (
                ""
                if any(
                    x["performed_on"] == on or x["status"] == "needs_review"
                    for x in all_rows
                )
                else '<p class="empty">선택한 날짜의 기록과 확인할 수행 제안이 없습니다.</p>'
            )
            + "</section>"
        )
        body += f'<details class="card spaced" id="record-editor"{" open" if edit or inquiry else ""}><summary>{"수행 기록 편집 #" + str(edit) if edit else "수행 기록 추가"}</summary><form id="activity-form" data-project-id="{pid}" data-id="{r.get("id", "")}" data-version="{r.get("version", 1)}"><input type="hidden" name="project" value="{esc(project["name"])}"><div class="record-fields">'
        body += f'<label class="full">수행 내용<textarea name="description" required>{esc(r.get("description", ""))}</textarea></label>'
        for name, label, value, kind in [
            (
                "performed_on",
                "실제 수행일",
                r.get("performed_on") or ("" if r.get("id") else on),
                "date",
            ),
            ("inquiry_id", "관련 메일·Jira", r.get("inquiry_id") or "", "text"),
            ("action_id", "연결할 할 일", r.get("action_id") or "", "number"),
            (
                "duplicate_of",
                "중복 대표 기록",
                r.get("duplicate_of") or "",
                "number",
            ),
            (
                "minutes",
                "소요 분 (직접 입력, 선택)",
                r.get("minutes") if r.get("minutes") is not None else "",
                "number",
            ),
        ]:
            options = None
            if name == "inquiry_id":
                options = [
                    (x["id"], x["subject"])
                    for x in query(
                        "SELECT DISTINCT s.id,s.subject FROM sources s WHERE s.id IN (SELECT inquiry_id FROM project_source_links WHERE project_id=? UNION SELECT inquiry_id FROM inquiry_projects WHERE project_id=?) ORDER BY s.rowid DESC",
                        (pid, pid),
                    )
                ]
            elif name == "action_id":
                options = [
                    (x["id"], x["description"])
                    for x in query(
                        "SELECT id,description FROM actions WHERE inquiry_id IN (SELECT inquiry_id FROM project_source_links WHERE project_id=? UNION SELECT inquiry_id FROM inquiry_projects WHERE project_id=?)",
                        (pid, pid),
                    )
                ]
            elif name == "duplicate_of":
                options = [
                    (x["id"], x["description"])
                    for x in all_rows
                    if x["id"] != edit and not x["duplicate_of"]
                ]
            if options is not None:
                body += (
                    f'<label>{label}<select name="{name}"><option value="">연결 없음</option>'
                    + "".join(
                        f'<option value="{esc(k)}" {"selected" if str(k) == str(value) else ""}>{esc(v[:120])}</option>'
                        for k, v in options
                    )
                    + "</select></label>"
                )
            else:
                body += f'<label>{label}<input name="{name}" type="{kind}" value="{esc(value)}"></label>'
        body += (
            '<label>상태<select name="status">'
            + "".join(
                f'<option value="{v}" {"selected" if r.get("status") == v else ""}>{label}</option>'
                for v, label in [
                    ("needs_review", "확인 필요"),
                    ("confirmed", "수행 확정"),
                    ("excluded", "집계 제외"),
                ]
            )
            + '</select></label></div><label><input type="checkbox" name="complete_action"> 연결한 할 일의 완료를 직접 확인</label><button class="primary">기록 저장</button></form>'
        )
        if r.get("id"):
            body += f'<p>원문 작성일: {esc(r.get("source_date"))} · 수집 시각: {esc(r.get("collected_at"))}</p><a href="/api/activities/{edit}/history">근거·편집 이력</a>'
            for a in query(
                "SELECT a.id,a.description,a.state FROM actions a WHERE inquiry_id=?",
                (r.get("inquiry_id"),),
            ):
                body += f"<p>할 일 #{a['id']}: {esc(a['description'])} ({esc(a['state'])})</p>"
        body += "</details>"
        return body

    return render_project_records
