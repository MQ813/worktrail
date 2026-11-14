"""WorkTrail pages extend the existing local workspace."""

from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from fastapi.responses import FileResponse
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
        db = connect(runtime)
        try:
            with db:
                if not db.execute(
                    "SELECT 1 FROM inquiries WHERE id=?", (data.inquiry_id,)
                ).fetchone():
                    raise HTTPException(404, "문의 없음")
                pid = worklog.project(db, data.project)
                db.execute(
                    "INSERT OR REPLACE INTO inquiry_projects VALUES(?,?)",
                    (data.inquiry_id, pid),
                )
        finally:
            db.close()
        return {"ok": True}

    def render_record(r):
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
        return (
            f"<tr><td>{esc(r['performed_on'] or '수행일 확인 필요')}</td><td>{esc(r['project'])}</td>"
            f'<td><a href="/worklog?edit={r["id"]}">{esc(r["description"][:200])}</a></td>'
            f"<td>{esc(status)}{(' · 중복 #' + str(r['duplicate_of'])) if r['duplicate_of'] else ''}</td>"
            f"<td>{evidence}</td></tr>"
        )

    @app.get("/today")
    def today():
        on = datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()
        body = f'<header class="top"><div><h1>오늘</h1><p>{on} · 할 일을 확인하고 수행한 업무를 기록하세요.</p></div><a class="button primary" href="/worklog">업무 기록 추가</a></header><div class="daily-grid">'
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
            + '</div></div><section class="card spaced"><div class="section-heading"><h2>오늘 수행 기록</h2><a class="button" href="/worklog">업무일지 보기</a></div>'
        )
        records = [r for r in activities() if r["performed_on"] == on]
        body += (
            '<div class="scroll"><table><thead><tr><th>수행일</th><th>프로젝트</th><th>내용</th><th>상태</th><th>근거</th></tr></thead><tbody>'
            + "".join(render_record(r) for r in records)
            + "</tbody></table></div>"
            if records
            else '<p class="empty empty-compact">아직 기록한 업무가 없습니다. 수행한 일을 업무일지에 남겨 보세요.</p>'
        )
        body += '</section><p class="muted">초안 검토는 발송이나 업무 완료로 집계하지 않습니다.</p>'
        return page(body, "today")

    @app.get("/worklog")
    def log(on: str = "", edit: int = 0, inquiry: str = ""):
        on = on or datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()
        all_rows = activities()
        r = next((r for r in all_rows if r["id"] == edit), {})
        if not r and inquiry:
            r = {"inquiry_id": inquiry}
        body = '<header class="top"><div><h1>업무일지</h1><p>실제 수행일을 입력하고 확정한 업무를 모아 보세요.</p></div><a class="button primary" href="#record-editor">업무 기록 추가</a></header>'
        body += f'<div class="split"><form class="toolbar" method="get"><label>수행일<input type="date" name="on" value="{esc(on)}"></label><button>날짜 보기</button></form><a class="button" href="/api/worklog/{esc(on)}/export">Markdown 내보내기</a></div>'
        body += '<section class="card"><h2>수행 기록</h2><div class="scroll"><table><thead><tr><th>수행일</th><th>프로젝트</th><th>내용</th><th>상태</th><th>근거</th></tr></thead><tbody>'
        body += (
            "".join(
                render_record(x)
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
        body += f'<section class="card spaced" id="record-editor"><h2>{"기록 편집 #" + str(edit) if r else "수동 기록"}</h2><p class="muted">분류의 수행 제안을 확인하고 실제 수행일을 입력하세요. 확인 전에는 집계되지 않습니다.</p><form id="activity-form" data-id="{r.get("id", "")}" data-version="{r.get("version", 1)}"><div class="record-fields">'
        body += f'<label class="full">수행 내용<textarea name="description" required>{esc(r.get("description", ""))}</textarea></label>'
        for name, label, value, kind in [
            (
                "performed_on",
                "실제 수행일",
                r.get("performed_on") or ("" if r.get("id") else on),
                "date",
            ),
            ("project", "프로젝트", r.get("project", ""), "text"),
            ("inquiry_id", "관련 문의 ID", r.get("inquiry_id") or "", "text"),
            ("action_id", "연결할 할 일 ID", r.get("action_id") or "", "number"),
            (
                "duplicate_of",
                "같은 수행의 대표 기록 ID",
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
                        "SELECT s.id,s.subject FROM inquiries i JOIN sources s ON s.id=i.id ORDER BY s.rowid DESC"
                    )
                ]
            elif name == "action_id":
                options = [
                    (x["id"], x["description"])
                    for x in query(
                        "SELECT id,description FROM actions WHERE inquiry_id=? OR ? IS NULL",
                        (r.get("inquiry_id"), r.get("inquiry_id")),
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
        if r:
            body += f'<p>원문 작성일: {esc(r.get("source_date"))} · 수집 시각: {esc(r.get("collected_at"))}</p><a href="/api/activities/{edit}/history">근거·편집 이력</a>'
            for a in query(
                "SELECT a.id,a.description,a.state FROM actions a WHERE inquiry_id=?",
                (r.get("inquiry_id"),),
            ):
                body += f"<p>할 일 #{a['id']}: {esc(a['description'])} ({esc(a['state'])})</p>"
        body += (
            '</section><details class="card spaced"><summary>기존 Markdown 가져오기</summary><p class="muted">사용자가 지정한 파일 하나만 읽으며 원본을 보존합니다. 생성 일지는 재입력하지 않습니다.</p><form id="import-form"><label>Markdown 파일의 전체 경로<input name="path" placeholder="C:\\work\\notes.md" required></label><label>수행일<input type="date" name="performed_on" value="'
            + esc(on)
            + '" required></label><label>프로젝트<input name="project" placeholder="프로젝트 이름"></label><button>확인 대상으로 가져오기</button></form></details>'
        )
        return page(body, "worklog")

    @app.get("/projects")
    def projects():
        body = '<header><h1>프로젝트</h1><p>같은 프로젝트의 문의와 수행 기록을 함께 확인하세요.</p></header><section class="card"><h2>프로젝트에 문의 연결</h2><form id="project-form"><label>관련 문의<select name="inquiry_id" id="project-inquiry" required></select></label><label>프로젝트 이름<input name="project" placeholder="예: GPIO 라이브러리" required></label><button class="primary">문의 연결</button></form></section>'
        opts = "".join(
            f'<option value="{esc(x["id"])}">{esc(x["subject"])}</option>'
            for x in query(
                "SELECT s.id,s.subject FROM inquiries i JOIN sources s ON s.id=i.id"
            )
        )
        body = body.replace(
            '<select name="inquiry_id" id="project-inquiry" required></select>',
            '<select name="inquiry_id" required>' + opts + "</select>",
        )
        projects = query("SELECT * FROM projects ORDER BY name")
        if not projects:
            body += '<section class="card spaced"><h2>연결된 프로젝트가 없습니다</h2><p class="muted">위에서 문의를 연결하면 프로젝트별로 모아 볼 수 있습니다.</p></section>'
        for p in projects:
            body += '<section class="card spaced"><h2>' + esc(p["name"]) + "</h2>"
            for i in query(
                "SELECT s.id,s.subject FROM inquiry_projects m JOIN sources s ON s.id=m.inquiry_id WHERE m.project_id=?",
                (p["id"],),
            ):
                body += f'<p><a href="/inquiries/{esc(i["id"])}">{esc(i["subject"])}</a></p>'
                for a in query("SELECT * FROM actions WHERE inquiry_id=?", (i["id"],)):
                    body += f"<p>할 일 #{a['id']} · {esc(a['description'])} · {esc(a['state'])}</p>"
            body += (
                '<div class="scroll"><table><thead><tr><th>수행일</th><th>프로젝트</th><th>내용</th><th>상태</th><th>근거</th></tr></thead><tbody>'
                + "".join(
                    render_record(r) for r in activities() if r["project"] == p["name"]
                )
                + "</tbody></table></div></section>"
            )
        return page(body, "projects")
