"""Forms and API for project commands; no model work in HTTP requests."""

import json

from . import project_ai as ai
from .storage import connect


def attach(app, runtime, guarded):
    def transaction(fn):
        db = connect(runtime)
        try:
            with db:
                return fn(db)
        finally:
            db.close()

    @app.post("/api/project-ai")
    def command(data: ai.CommandInput):
        key = guarded(lambda: transaction(lambda db: ai.enqueue(db, data)))
        return {"request_id": key}

    @app.get("/api/project-ai/{key}")
    def status(key: str):
        def read(db):
            row = db.execute(
                "SELECT r.*,j.state AS job_state,j.error FROM project_ai_requests r LEFT JOIN jobs j ON j.request_id=r.id AND j.kind='project_command' WHERE r.id=?",
                (key,),
            ).fetchone()
            if not row:
                raise ValueError("요청이 없습니다.")
            return {
                k: row[k]
                for k in ("state", "project_id", "question", "job_state", "error")
            }

        return guarded(lambda: transaction(read))

    @app.post("/api/project-ai/history/{hid}/confirm")
    def confirm(hid: int):
        guarded(lambda: transaction(lambda db: ai.review(db, hid)))
        return {"ok": True}

    @app.post("/api/project-ai/history/{hid}/undo")
    def undo(hid: int):
        guarded(lambda: transaction(lambda db: ai.review(db, hid, undo=True)))
        return {"ok": True}

    @app.post("/api/project-ai/dismiss/{iid}")
    def dismiss(iid: str):
        from .service import latest

        def run(db):
            if not db.execute("SELECT 1 FROM inquiries WHERE id=?", (iid,)).fetchone():
                raise ValueError("문의가 없습니다.")
            db.execute(
                "INSERT OR REPLACE INTO project_ai_dismissed VALUES(?,?)",
                (iid, latest(db, iid)),
            )
            db.execute("DELETE FROM project_unassigned WHERE inquiry_id=?", (iid,))

        guarded(lambda: transaction(run))
        return {"ok": True}


def form(query, esc, pid=None, iid=None, work_item_id=None):
    body = '<form class="project-ai-form"><label>AI 요청<textarea name="text" maxlength="16000" placeholder="변경할 내용과 새로 확인된 정보를 입력하세요."></textarea></label>'
    if pid:
        body += f'<input type="hidden" name="mode" value="update"><input type="hidden" name="project_id" value="{pid}">'
        if work_item_id:
            body += f'<input type="hidden" name="work_item_id" value="{work_item_id}"><p class="muted">선택한 이슈의 내용만 수정합니다. 프로젝트 개요와 다른 이슈는 요청 범위에 포함되지 않습니다.</p>'
        else:
            body += '<p class="muted">프로젝트 개요와 공통 내용을 업데이트합니다. 기존 하위 이슈의 상세 수정은 해당 이슈에서 요청하세요.</p>'
    else:
        body += '<div class="form-grid"><label>처리 방식<select name="mode"><option value="auto">요청에서 판단</option><option value="create">신규 프로젝트 생성</option><option value="update">기존 프로젝트 업데이트</option></select></label>'
        body += '<label>대상 프로젝트<select name="project_id"><option value="">AI가 관련 프로젝트 찾기</option>'
        for p in query("SELECT id,code,name FROM projects ORDER BY code"):
            body += f'<option value="{p["id"]}">{esc(p["code"])} · {esc(p["name"])}</option>'
        body += "</select></label></div>"
    body += f'<details class="ai-sources"{" open" if iid else ""}><summary>메일·Jira를 참고 자료로 추가</summary><label>참고할 기존 문의<select name="inquiry_ids" multiple size="4">'
    for s in query(
        "SELECT s.id,s.subject FROM sources s JOIN inquiries i ON i.id=s.id ORDER BY s.rowid DESC"
    ):
        body += f'<option value="{esc(s["id"])}"{" selected" if s["id"] == iid else ""}>{esc(s["subject"])}</option>'
    body += (
        '</select></label><p class="muted">문의는 여러 개 선택할 수 있습니다.</p></details><p class="muted">입력한 정보를 반영합니다. 부족한 정보는 TBD로 남기며, 변경 검토에서 확인하거나 되돌릴 수 있습니다.</p><button class="primary">'
        + ("AI로 업데이트" if pid else "AI로 생성·업데이트")
        + '</button><p role="status" aria-live="polite" class="form-feedback"></p></form>'
    )
    return body


def unconfirmed_entries(query, pid):
    states = set()
    for row in query(
        "SELECT before_state,after_state FROM project_ai_history WHERE project_id=? AND confirmed=0 AND reverted=0",
        (pid,),
    ):
        before = json.loads(row["before_state"])
        after = json.loads(row["after_state"])
        previous = {e["id"]: e for e in before["entries"]} if before else {}
        for entry in after["entries"]:
            if entry != previous.get(entry["id"]):
                states.add((entry["id"], entry["version"], entry["text"]))
    return states


def history(query, esc, pid):
    rows = query(
        "SELECT * FROM project_ai_history WHERE project_id=? ORDER BY id DESC", (pid,)
    )
    if not rows:
        return ""
    body = '<section class="card spaced"><h2>AI 반영 이력</h2>'
    for r in rows:
        state = (
            "되돌림"
            if r["reverted"]
            else "사용자 확인"
            if r["confirmed"]
            else "AI 반영 · 미확인"
        )
        before, after = json.loads(r["before_state"]), json.loads(r["after_state"])
        body += f'<article class="project-change"><h3>{state} · #{r["id"]}</h3><details><summary>변경 전후·입력 근거</summary>'
        for field in ai.FIELDS:
            old, new = before.get(field, "") if before else "", after.get(field, "")
            if old != new:
                body += f'<p class="project-text">{esc({"target_on": "목표 일정", "spec": "Spec", "process": "공정", "development_target": "개발 대상"}.get(field, field))}: {esc(old or "없음")} → {esc(new)}</p>'
        old_entries = {e["id"]: e for e in before["entries"]} if before else {}
        for e in after["entries"]:
            old = old_entries.get(e["id"], {}).get("text", "")
            if old != e["text"]:
                body += f'<p class="project-text">{esc(old or "새 항목")} → {esc(e["text"])}</p>'
        request = json.loads(r["input"])
        body += f'<p class="project-text">요청: {esc(request["instruction"])}</p>'
        for source in request["sources"]:
            if source["source_ref"] != "user":
                body += f'<a href="/inquiries/{esc(source["source_ref"])}">원문 · revision {source["revision"]}</a>'
            body += (
                f'<blockquote class="project-text">{esc(source["body"])}</blockquote>'
            )
        body += "</details>"
        if not r["reverted"]:
            body += '<div class="toolbar">'
            if not r["confirmed"]:
                body += f'<button data-command="/api/project-ai/history/{r["id"]}/confirm" data-reload="true">내용 확인</button>'
            body += f'<button data-command="/api/project-ai/history/{r["id"]}/undo" data-reload="true">{"생성 취소" if before is None else "변경 되돌리기"}</button></div>'
        body += "</article>"
    return body + "</section>"
