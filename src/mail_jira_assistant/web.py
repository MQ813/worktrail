import html
import json
from datetime import UTC
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .knowledge import MarkdownKnowledge, refresh_freshness
from .service import add_revision, audit, dumps, enqueue, latest
from .storage import connect

LABELS = {
    "needs_review": "확인 필요",
    "in_progress": "진행 중",
    "waiting_external": "회신 대기",
    "completed": "업무 완료",
    "dismissed": "제외",
    "archived": "보류",
    "generated": "생성됨",
    "editing": "편집 중",
    "reviewed": "검토 완료",
    "current": "최신",
    "stale": "재검토 필요",
    "inbound": "받은 메일",
    "outbound": "보낸 메일",
    "unknown": "방향 확인",
    "pending": "대기",
    "running": "실행 중",
    "retry_wait": "재시도 대기",
    "succeeded": "성공",
    "failed": "실패",
    "cancelled": "취소",
    "ready": "텍스트 추출됨",
    "unsupported": "미지원 형식",
    "needs_vision": "이미지 해석 필요",
    "partial": "일부만 확보",
    "download_failed": "다운로드 실패",
    "extract_failed": "추출 실패",
    "proposed": "확인할 제안",
    "open": "할 일",
    "waiting": "회신 대기",
    "done": "완료",
}


def esc(value):
    return html.escape(str(value if value is not None else ""))


def local_date(value):
    from datetime import datetime
    from email.utils import parsedate_to_datetime
    from zoneinfo import ZoneInfo

    try:
        try:
            stamp = parsedate_to_datetime(value)
        except (ValueError, TypeError):
            stamp = datetime.fromisoformat(value)
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=UTC)
        return stamp.astimezone(ZoneInfo("Asia/Seoul")).strftime("%Y.%m.%d %H:%M KST")
    except (ValueError, TypeError):
        return value or "날짜 미상"


def badge(value):
    color = (
        "warn"
        if value
        in (
            "stale",
            "needs_review",
            "partial",
            "needs_vision",
            "retry_wait",
            "proposed",
        )
        else (
            "error"
            if value in ("failed", "download_failed", "extract_failed")
            else (
                "ok"
                if value
                in ("reviewed", "current", "succeeded", "done", "completed", "ready")
                else ""
            )
        )
    )
    return (
        '<span class="badge ' + color + '">' + esc(LABELS.get(value, value)) + "</span>"
    )


def button(text, url, payload=None, reload=False):
    return (
        '<button data-command="'
        + esc(url)
        + '" data-payload="'
        + esc(dumps(payload or {}))
        + '" data-reload="'
        + str(reload).lower()
        + '">'
        + esc(text)
        + "</button>"
    )


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Edit(Strict):
    version: int
    body: str = Field(max_length=100000)
    review: Literal["editing", "reviewed", "archived"] = "editing"


class Override(Strict):
    state: Literal[
        "needs_review", "in_progress", "waiting_external", "completed", "dismissed"
    ]
    note: str = Field(default="", max_length=4000)
    revision: int


class ActionEdit(Strict):
    state: Literal["proposed", "open", "waiting", "done", "cancelled"]
    version: int


class ClassificationEdit(Strict):
    revision: int
    response_expected: Literal["yes", "no", "unknown"]
    action_required: Literal["yes", "no", "unknown"]
    work_performed: Literal["yes", "no", "unknown"]
    waiting_for_others: Literal["yes", "no", "unknown"]
    note: str = Field(default="", max_length=4000)


class JiraURL(Strict):
    url: str = Field(max_length=2000)


class Link(Strict):
    target: str | None = None


class Adopt(Strict):
    version: int


def create_app(runtime, kb=None, jira_servers=(), *, sample_mode=False):
    kb = kb or str(Path(__file__).parent / "demo/kb")
    app = FastAPI(title="메일·JIRA 문의함")
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"],
    )
    app.mount(
        "/static",
        StaticFiles(directory=Path(__file__).parent / "static"),
        name="static",
    )

    @app.middleware("http")
    async def security(request, call_next):
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if origin and origin != str(request.base_url).rstrip("/"):
                return HTMLResponse(
                    "다른 출처에서 요청할 수 없습니다.", status_code=403
                )
            if not request.headers.get("content-type", "").startswith(
                "application/json"
            ):
                return HTMLResponse("JSON 요청이 필요합니다.", status_code=415)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    def rows(sql, args=()):
        db = connect(runtime)
        try:
            return [dict(r) for r in db.execute(sql, args)]
        finally:
            db.close()

    def need(iid):
        result = rows("SELECT * FROM inquiries WHERE id=?", (iid,))
        if not result:
            raise HTTPException(404, "문의를 찾을 수 없습니다.")
        return result[0]

    def page(body, tab="inbox"):
        from datetime import datetime
        from zoneinfo import ZoneInfo

        navigation = [
            (
                "today",
                "/today",
                "오늘",
                "M8 2v4m8-4v4M3 10h18M5 4h14a2 2 0 0 1 2 2v14H3V6a2 2 0 0 1 2-2",
            ),
            ("inbox", "/", "문의함", "M3 4h18v16H3zM3 13h5l2 3h4l2-3h5"),
            (
                "drafts",
                "/?view=drafts",
                "답변 초안",
                "M14 3H4v18h16V11M9 15l1-5 8-8 4 4-8 8-5 1z",
            ),
            ("worklog", "/worklog", "업무일지", "M5 3h14v18H5zM9 8h6m-6 4h6m-6 4h4"),
            ("projects", "/projects", "프로젝트", "M3 6h7l2 2h9v12H3zM3 6V4h7l2 2"),
            ("ops", "/operations", "운영 상태", "M3 12h4l3-8 4 16 3-8h4"),
        ]
        title = next((label for key, _, label, _ in navigation if key == tab), "문의함")
        nav = ""
        for key, href, label, path in navigation:
            if key in ("today", "worklog", "ops"):
                nav += (
                    '<div class="nav-label">'
                    + {"today": "업무", "worklog": "기록", "ops": "관리"}[key]
                    + "</div>"
                )
            current = ' class="active" aria-current="page"' if key == tab else ""
            nav += (
                f'<a href="{href}"{current}><svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="{path}"/></svg>'
                + label
                + "</a>"
            )
        context = ""
        connection = rows("SELECT value FROM meta WHERE key='ai_connection_status'")
        if connection:
            context += (
                '<p class="connection-status">AI 실행: '
                + esc(connection[0]["value"])
                + "</p>"
            )
        if sample_mode:
            context += (
                '<details class="sample-notice"><summary>합성 샘플 환경 <span>실제 사내 데이터 아님</span></summary>'
                "<p>메일 14건 + 연결 JIRA 3건 · 내 역할: 조민규. JIRA는 로컬 fixture를 조회합니다. 이미지 캡처는 직접 확인이 필요합니다.</p></details>"
            )
        date = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y.%m.%d")
        return HTMLResponse(
            '<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>WorkTrail</title><link rel="stylesheet" href="/static/app.css"><script src="/static/app.js" defer></script></head><body><a class="skip-link" href="#main">본문으로 건너뛰기</a><div class="shell"><aside class="sidebar"><a class="brand" href="/"><span class="brand-mark" aria-hidden="true">w.</span>WorkTrail</a><div class="workspace-name">개인 워크스페이스</div><nav class="nav" aria-label="주 메뉴">'
            + nav
            + '</nav><footer><span class="local-indicator" aria-hidden="true"></span> 로컬에 보관되는 업무<br><span class="muted">검토 후 직접 답변하세요.</span></footer></aside><div class="workspace"><div class="workspace-bar"><span>내 워크스페이스 <span class="breadcrumb-divider" aria-hidden="true">/</span> <strong>'
            + title
            + "</strong></span><time>"
            + date
            + '</time></div><main class="main" id="main" tabindex="-1">'
            + context
            + body
            + '</main></div></div><div id="toast" role="status" aria-live="polite" aria-atomic="true"></div></body></html>'
        )

    @app.get("/api/inquiries")
    def inquiries():
        db = connect(runtime)
        try:
            with db:
                refresh_freshness(db, kb)
        finally:
            db.close()
        result = rows(
            "SELECT s.*,i.state,d.review,d.freshness,d.version,(SELECT max(created) FROM revisions WHERE inquiry_id=i.id) AS last_change,(SELECT count(*) FROM jobs WHERE source_id=i.id AND state='failed') AS failed_jobs FROM inquiries i JOIN sources s ON s.id=i.id LEFT JOIN drafts d ON d.source_id=i.id ORDER BY (SELECT max(id) FROM revisions WHERE inquiry_id=i.id) DESC"
        )
        for item in result:
            manual = rows(
                "SELECT result,revision_id FROM manual_classifications WHERE inquiry_id=? ORDER BY id DESC LIMIT 1",
                (item["id"],),
            )
            item["manual_classification"] = (
                json.loads(manual[0]["result"]) if manual else None
            )
            item["classification_needs_review"] = bool(
                manual
                and rows(
                    "SELECT max(id) AS revision FROM revisions WHERE inquiry_id=?",
                    (item["id"],),
                )[0]["revision"]
                != manual[0]["revision_id"]
            )
            automatic = rows(
                "SELECT result FROM classifications WHERE source_id=?", (item["id"],)
            )
            item["effective_classification"] = (
                item["manual_classification"]
                if manual and not item["classification_needs_review"]
                else (json.loads(automatic[0]["result"]) if automatic else None)
            )
        return result

    @app.get("/", response_class=HTMLResponse)
    def index(
        q: str = "",
        state: str = "",
        view: str = "",
        source: str = "",
        server: str = "",
        work: str = "",
        after: str = "",
    ):
        all_items = inquiries()
        items = [
            r
            for r in all_items
            if (
                not q
                or q.lower()
                in (r["subject"] + " " + r["body"] + " " + r["sender"]).lower()
            )
            and (not state or r["state"] == state)
            and (view != "drafts" or r["review"])
        ]
        if source:
            items = [
                r
                for r in items
                if (
                    r["kind"] == "jira"
                    if source == "jira"
                    else r["direction"] == source
                )
            ]
        if server:
            items = [
                r
                for r in items
                if server.lower() in (r["sender"] + " " + r["message_id"]).lower()
            ]
        if work == "actions":
            items = [
                r
                for r in items
                if rows(
                    "SELECT 1 FROM actions WHERE inquiry_id=? AND state IN ('proposed','open','waiting')",
                    (r["id"],),
                )
            ]
        if work == "failed":
            items = [
                r
                for r in items
                if rows(
                    "SELECT 1 FROM jobs WHERE source_id=? AND state='failed'",
                    (r["id"],),
                )
            ]
        if after:
            from datetime import datetime

            try:
                threshold = (
                    datetime.fromisoformat(after).replace(tzinfo=UTC).timestamp()
                )
            except ValueError:
                threshold = 0
            items = [
                r
                for r in items
                if rows(
                    "SELECT 1 FROM revisions WHERE inquiry_id=? AND created>=?",
                    (r["id"], threshold),
                )
            ]
        stats = [
            ("확인할 문의", sum(r["state"] == "needs_review" for r in all_items)),
            ("진행 중", sum(r["state"] == "in_progress" for r in all_items)),
            ("회신 대기", sum(r["state"] == "waiting_external" for r in all_items)),
            ("재검토할 초안", sum(r["freshness"] == "stale" for r in all_items)),
        ]
        body = (
            '<header class="top"><div><h1>'
            + ("답변 초안" if view == "drafts" else "문의함")
            + '</h1><p class="muted">'
            + (
                "근거를 확인하고 답변을 다듬으세요. 검토 완료 후 직접 발송합니다."
                if view == "drafts"
                else "받은 문의를 확인하고 답변과 할 일을 이어가세요."
            )
            + '</p></div><a class="button primary" href="/worklog">업무 기록 추가</a></header><div class="stats" aria-label="전체 문의 요약">'
            + "".join(
                '<div class="stat"><span class="muted">'
                + label
                + "</span><strong>"
                + str(n)
                + "</strong></div>"
                for label, n in stats
            )
            + "</div>"
        )
        body += (
            '<section class="card inbox-panel"><div class="list-heading"><h2>'
            + ("초안 목록" if view == "drafts" else "문의 목록")
            + ' <span class="result-count">'
            + str(len(items))
            + '건</span></h2><span class="muted">최근 변경순</span></div>'
            + '<form class="inbox-filters" method="get"><div class="filter-main"><label class="search-field">문의 검색<input name="q" value="'
            + esc(q)
            + '" placeholder="제목, 보낸 사람, 본문"><input type="hidden" name="view" value="'
            + esc(view)
            + '"></label><label>업무 상태<select name="state"><option value="">모든 상태</option>'
            + "".join(
                '<option value="'
                + s
                + '" '
                + ("selected" if state == s else "")
                + ">"
                + LABELS[s]
                + "</option>"
                for s in (
                    "needs_review",
                    "in_progress",
                    "waiting_external",
                    "completed",
                    "dismissed",
                )
            )
            + '</select></label><label>출처<select name="source"><option value="">모든 출처</option>'
            + "".join(
                '<option value="'
                + v
                + '" '
                + ("selected" if source == v else "")
                + ">"
                + label
                + "</option>"
                for v, label in [
                    ("inbound", "받은 메일"),
                    ("outbound", "보낸 메일"),
                    ("jira", "JIRA"),
                ]
            )
            + '</select></label><button class="primary">검색</button><a class="button" href="'
            + ("/?view=drafts" if view == "drafts" else "/")
            + '">초기화</a></div><details class="advanced-filters"'
            + (" open" if server or work or after else "")
            + '><summary>상세 필터</summary><div class="filter-extra"><label>서버 · 프로젝트 · 상대방<input name="server" value="'
            + esc(server)
            + '" placeholder="이름으로 검색"></label><label>작업<select name="work"><option value="">모든 작업</option><option value="actions" '
            + ("selected" if work == "actions" else "")
            + '>남은 할 일</option><option value="failed" '
            + ("selected" if work == "failed" else "")
            + '>실패 작업</option></select></label><label>수집 날짜 이후<input type="date" name="after" value="'
            + esc(after)
            + '"></label></div></details></form><div class="scroll"><table class="inquiry-table"><thead><tr><th>문의 · 대화</th><th>업무 상태</th><th>답변 초안</th><th class="hide-mobile">출처</th></tr></thead><tbody>'
        )
        for r in items:
            body += (
                '<tr><td><a class="title" href="/inquiries/'
                + r["id"]
                + '">'
                + esc(r["subject"])
                + '</a><span class="muted">'
                + esc(r["sender"])
                + (" · 분류 재확인 필요" if r["classification_needs_review"] else "")
                + "</span></td><td>"
                + badge(r["state"])
                + "</td><td>"
                + (
                    badge(r["review"]) + " " + badge(r["freshness"])
                    if r["review"]
                    else '<span class="muted">초안 없음</span>'
                )
                + '</td><td class="hide-mobile">'
                + esc(
                    "JIRA"
                    if r["kind"] == "jira"
                    else LABELS.get(r["direction"], r["direction"])
                )
                + "</td></tr>"
            )
        body += (
            "</tbody></table></div>"
            + (
                ""
                if items
                else '<div class="empty">표시할 문의가 없습니다.<br>메일을 수집하거나 검색 조건을 바꿔 주세요.</div>'
            )
            + '</section><div class="notice">초안 검토는 발송과 별개입니다. 실제 답변 후 업무 상태를 직접 확인하세요.</div>'
        )
        return page(body, "drafts" if view == "drafts" else "inbox")

    @app.post("/api/inquiries/{iid}/classify")
    def classify(iid: str):
        need(iid)
        enqueue(runtime, iid)
        return {"queued": True}

    @app.post("/api/inquiries/{iid}/regenerate")
    def regenerate(iid: str):
        need(iid)
        enqueue(runtime, iid, regenerate=True)
        return {"queued": True}

    @app.put("/api/drafts/{iid}")
    def edit(iid: str, data: Edit):
        db = connect(runtime)
        try:
            with db:
                changed = db.execute(
                    "UPDATE drafts SET body=?,review=?,version=version+1 WHERE source_id=? AND version=?",
                    (data.body, data.review, iid, data.version),
                ).rowcount
                if not changed:
                    raise HTTPException(
                        409,
                        "다른 편집이 저장되었습니다. 현재 내용을 복사해 두고 새로고침하세요.",
                    )
                db.execute(
                    "INSERT INTO edits(source_id,version,body,review) VALUES(?,?,?,?)",
                    (iid, data.version + 1, data.body, data.review),
                )
                audit(
                    db,
                    "draft_edit",
                    iid,
                    {"version": data.version + 1, "review": data.review},
                )
            return {"version": data.version + 1}
        finally:
            db.close()

    @app.post("/api/inquiries/{iid}/override")
    def override(iid: str, data: Override):
        need(iid)
        db = connect(runtime)
        try:
            with db:
                if latest(db, iid) != data.revision:
                    raise HTTPException(
                        409, "새 원문이 도착했습니다. 확인 후 다시 변경하세요."
                    )
                db.execute(
                    "INSERT INTO overrides(inquiry_id,revision_id,state,note,created) VALUES(?,?,?,?,strftime('%s','now'))",
                    (iid, data.revision, data.state, data.note),
                )
                db.execute("UPDATE inquiries SET state=? WHERE id=?", (data.state, iid))
                audit(db, "override", iid, data.model_dump())
            return {"saved": True}
        finally:
            db.close()

    @app.post("/api/inquiries/{iid}/classification")
    def manual_classification(iid: str, data: ClassificationEdit):
        need(iid)
        db = connect(runtime)
        try:
            with db:
                if latest(db, iid) != data.revision:
                    raise HTTPException(
                        409, "새 원문이 도착했습니다. 확인 후 다시 분류하세요."
                    )
                result = data.model_dump(exclude={"revision", "note"})
                db.execute(
                    "INSERT INTO manual_classifications(inquiry_id,revision_id,result,note,created) VALUES(?,?,?,?,strftime('%s','now'))",
                    (iid, data.revision, dumps(result), data.note),
                )
                if data.response_expected != "yes":
                    db.execute(
                        "UPDATE jobs SET state='cancelled' WHERE source_id=? AND input_version=? AND kind='draft' AND request_id='' AND state IN ('pending','retry_wait')",
                        (iid, data.revision),
                    )
                audit(db, "manual_classification", iid, data.model_dump())
            return {"saved": True}
        finally:
            db.close()

    @app.post("/api/actions/{aid}")
    def action(aid: int, data: ActionEdit):
        db = connect(runtime)
        try:
            with db:
                if not db.execute(
                    "UPDATE actions SET state=?,version=version+1 WHERE id=? AND version=?",
                    (data.state, aid, data.version),
                ).rowcount:
                    raise HTTPException(409, "할 일이 변경되었습니다. 새로고침하세요.")
                audit(db, "action_state", str(aid), data.model_dump())
            return {"saved": True}
        finally:
            db.close()

    @app.post("/api/draft-versions/{vid}/adopt")
    def adopt(vid: int, data: Adopt):
        db = connect(runtime)
        try:
            with db:
                candidate = db.execute(
                    "SELECT * FROM draft_versions WHERE id=?", (vid,)
                ).fetchone()
                if not candidate:
                    raise HTTPException(404)
                draft = json.loads(candidate["generated"])
                for ref in draft.get("knowledge_refs", []):
                    try:
                        current_ref = MarkdownKnowledge(kb).read(ref.rsplit(":", 1)[0])[
                            "ref"
                        ]
                    except (OSError, ValueError):
                        current_ref = None
                    if ref != current_ref:
                        raise HTTPException(
                            409, "근거 문서가 변경된 후보입니다. 새 초안을 요청하세요."
                        )
                iid = candidate["inquiry_id"]
                if not db.execute(
                    "UPDATE drafts SET generated=?,body=?,version=version+1,review='editing',revision_id=?,freshness=? WHERE source_id=? AND version=?",
                    (
                        candidate["generated"],
                        draft["body"],
                        candidate["revision_id"],
                        "current"
                        if latest(db, iid) == candidate["revision_id"]
                        else "stale",
                        iid,
                        data.version,
                    ),
                ).rowcount:
                    raise HTTPException(409, "초안이 변경되었습니다.")
                db.execute(
                    "INSERT INTO edits(source_id,version,body,review) VALUES(?,?,?,?)",
                    (iid, data.version + 1, draft["body"], "editing"),
                )
                audit(db, "draft_adopt", iid, {"candidate": vid})
            return {"saved": True}
        finally:
            db.close()

    @app.post("/api/sources/{sid}/link")
    def link(sid: str, data: Link):
        db = connect(runtime)
        try:
            with db:
                s = db.execute("SELECT * FROM sources WHERE id=?", (sid,)).fetchone()
                if not s:
                    raise HTTPException(404)
                target = data.target or sid
                if target == sid:
                    db.execute("INSERT OR IGNORE INTO inquiries(id) VALUES(?)", (sid,))
                if not db.execute(
                    "SELECT 1 FROM inquiries WHERE id=?", (target,)
                ).fetchone():
                    raise HTTPException(404, "연결할 문의 ID를 확인하세요.")
                old = s["inquiry_id"]
                db.execute("UPDATE sources SET inquiry_id=? WHERE id=?", (target, sid))
                add_revision(
                    db,
                    target,
                    sid,
                    {
                        "body": s["body"],
                        "attachments": json.loads(s["attachments"]),
                        "link": target,
                    },
                    "manual_link",
                )
                db.execute(
                    "UPDATE drafts SET freshness='stale' WHERE source_id IN (?,?)",
                    (old, target),
                )
                audit(db, "source_link", sid, {"previous": old, "target": target})
            return {"saved": True}
        finally:
            db.close()

    @app.get("/attachments/{sid}/{aid}")
    def attachment(sid: str, aid: str, inline: bool = False):
        result = rows("SELECT attachments FROM sources WHERE id=?", (sid,))
        if not result:
            raise HTTPException(404)
        a = next(
            (
                a
                for a in json.loads(result[0]["attachments"])
                if a["id"] == aid and a.get("path")
            ),
            None,
        )
        if not a:
            raise HTTPException(404)
        path = (Path(runtime) / a["path"]).resolve()
        if (
            not path.is_relative_to((Path(runtime) / "blobs").resolve())
            or not path.is_file()
        ):
            raise HTTPException(404)
        safe_inline = inline and a["mime"] in (
            "image/png",
            "image/jpeg",
            "image/gif",
            "image/webp",
        )
        return FileResponse(
            path,
            media_type=a["mime"] if safe_inline else "application/octet-stream",
            filename=a.get("name") or aid,
            content_disposition_type="inline" if safe_inline else "attachment",
        )

    @app.get("/sources/{sid}/raw")
    def raw(sid: str):
        result = rows("SELECT raw_path FROM sources WHERE id=?", (sid,))
        if not result:
            raise HTTPException(404)
        path = (Path(runtime) / result[0]["raw_path"]).resolve()
        if not path.is_relative_to((Path(runtime) / "blobs").resolve()):
            raise HTTPException(404)
        return FileResponse(
            path, filename=sid + ".bin", media_type="application/octet-stream"
        )

    @app.get("/inquiries/{iid}", response_class=HTMLResponse)
    def detail(iid: str):
        inquiry = need(iid)
        sources = rows(
            "SELECT * FROM sources WHERE inquiry_id=? ORDER BY rowid DESC", (iid,)
        )
        s = rows("SELECT * FROM sources WHERE id=?", (iid,))[0]
        db = connect(runtime)
        revision = latest(db, iid)
        db.close()
        drafts = rows("SELECT * FROM drafts WHERE source_id=?", (iid,))
        d = drafts[0] if drafts else None
        # Knowledge changes invalidate working copy, while preserving review and body.
        if d:
            for ref in json.loads(d["generated"]).get("knowledge_refs", []):
                try:
                    current = MarkdownKnowledge(kb).read(ref.rsplit(":", 1)[0])["ref"]
                except (OSError, ValueError):
                    current = None
                if current != ref:
                    db = connect(runtime)
                    with db:
                        db.execute(
                            "UPDATE drafts SET freshness='stale' WHERE source_id=?",
                            (iid,),
                        )
                    db.close()
                    d["freshness"] = "stale"
                    break
        body = (
            '<a class="muted" href="/">← 문의함으로</a><div class="top"><div><h1>'
            + esc(s["subject"])
            + '</h1><div class="pillrow">'
            + badge(inquiry["state"])
            + ' <span class="muted">대화 '
            + str(len(sources))
            + "건 · revision "
            + str(revision)
            + "</span></div></div>"
            + button("분류 요청", "/api/inquiries/" + iid + "/classify")
            + '</div><div class="grid"><div class="stack"><section class="card"><h2>대화와 첨부</h2>'
        )
        for idx, source in enumerate(sources):
            body += (
                '<div class="source">'
                + badge(source["direction"])
                + ' <span class="muted">'
                + esc(source["sender"])
                + " · "
                + esc(local_date(source["date"]))
                + '</span><p class="muted">'
                + esc(source["recipients"])
                + "</p><pre>"
                + esc(source["body"])
                + '</pre><div class="attachments">'
            )
            for a in json.loads(source["attachments"]):
                url = "/attachments/" + source["id"] + "/" + a["id"]
                body += (
                    '<div class="file">'
                    + badge(a["status"])
                    + " "
                    + (
                        '<a href="'
                        + url
                        + '">'
                        + esc(a.get("name") or "인라인 이미지")
                        + "</a>"
                        if a.get("path")
                        else esc(a.get("name"))
                    )
                    + '<div class="muted">'
                    + esc(" · ".join(a.get("warnings", [])))
                    + "</div>"
                )
                if a.get("cid") and a["mime"] in (
                    "image/png",
                    "image/jpeg",
                    "image/gif",
                    "image/webp",
                ):
                    body += (
                        '<img class="cid" alt="'
                        + esc(a.get("name") or a["cid"])
                        + '" src="'
                        + url
                        + '?inline=true">'
                    )
                if a.get("text"):
                    body += (
                        "<details><summary>추출 텍스트·위치</summary><pre>"
                        + esc(a["text"])
                        + "</pre></details>"
                    )
                body += "</div>"
            snapshot = rows(
                "SELECT snapshot FROM revisions WHERE source_id=? ORDER BY id DESC LIMIT 1",
                (source["id"],),
            )
            excluded = (
                json.loads(snapshot[0]["snapshot"]).get("excluded", {})
                if snapshot
                else {}
            )
            if excluded.get("access_warnings"):
                body += (
                    '<p class="warn">'
                    + esc("; ".join(excluded["access_warnings"]))
                    + "</p>"
                )
            if excluded.get("quoted_text") or excluded.get("signature"):
                body += (
                    "<details><summary>정리한 인용문·서명 보기</summary><pre>"
                    + esc(
                        excluded.get("quoted_text", "")
                        + "\n"
                        + excluded.get("signature", "")
                    )
                    + "</pre></details>"
                )
            body += (
                '</div><details><summary>원본·연결 정보</summary><a class="button" href="/sources/'
                + source["id"]
                + '/raw">원본 다운로드</a><p class="muted">출처 ID <code>'
                + source["id"]
                + "</code></p>"
                + button(
                    "별도 문의로 분리",
                    "/api/sources/" + source["id"] + "/link",
                    {},
                    True,
                )
                + "</details></div>"
            )
        body += '</section><section class="card"><h2>할 일과 수행 제안</h2>'
        actions = rows("SELECT * FROM actions WHERE inquiry_id=? ORDER BY id", (iid,))
        for a in actions:
            kind = json.loads(a["evidence"]).get("kind", "todo")
            kind_label = {
                "todo": "할 일 제안",
                "performed": "수행 증거 후보",
                "waiting": "회신 대기",
            }.get(kind, kind)
            body += (
                '<div class="action"><span>'
                + badge(a["state"])
                + " "
                + esc(kind_label + " · " + a["description"])
                + '<br><span class="muted">담당 '
                + esc(a["assignee"])
                + " · 기한 "
                + esc(a["due_at"] or "미정")
                + "</span></span><div>"
                + (
                    button(
                        "할 일 확정",
                        "/api/actions/" + str(a["id"]),
                        {"version": a["version"], "state": "open"},
                        True,
                    )
                    if a["state"] == "proposed" and kind != "performed"
                    else ""
                )
                + button(
                    "대기",
                    "/api/actions/" + str(a["id"]),
                    {"version": a["version"], "state": "waiting"},
                    True,
                )
                + button(
                    "완료 확인" if a["state"] != "done" else "다시 열기",
                    "/api/actions/" + str(a["id"]),
                    {
                        "version": a["version"],
                        "state": "done" if a["state"] != "done" else "open",
                    },
                    True,
                )
                + "</div></div>"
            )
        if not actions:
            body += '<p class="muted">분류 후 확인할 할 일이 여기에 표시됩니다.</p>'
        body += (
            '</section></div><div class="stack"><section class="card"><div class="split"><h2>답변 초안</h2>'
            + button("새 초안 요청", "/api/inquiries/" + iid + "/regenerate")
            + "</div>"
            + '<p class="muted">앱이 켜져 있으면 생성 요청을 자동으로 처리합니다. 기존 편집본은 보존하며, 재생성 결과는 비교 후보로 표시될 수 있습니다.</p>'
            + '<p><a href="/inquiries/'
            + esc(iid)
            + '">결과 새로고침</a> · <a href="/operations">처리 상태 확인</a></p>'
        )
        recent_generation = rows(
            "SELECT state FROM jobs WHERE source_id=? AND kind='draft' ORDER BY id DESC LIMIT 1",
            (iid,),
        )
        if recent_generation:
            generation_label = {
                "pending": "생성 대기",
                "running": "초안 생성 중",
                "retry_wait": "재시도 대기",
                "succeeded": "생성 완료",
                "failed": "생성 실패 · 처리 상태 확인 필요",
                "cancelled": "요청 취소",
            }.get(recent_generation[0]["state"], "처리 상태 확인 필요")
            body += (
                '<p role="status">최근 초안 요청: <strong>'
                + esc(generation_label)
                + "</strong></p>"
            )
        if d:
            generated = json.loads(d["generated"])
            body += (
                '<div class="pillrow">'
                + badge(d["review"])
                + " "
                + badge(d["freshness"])
                + "</div>"
            )
            if d["freshness"] == "stale":
                body += '<div class="notice warn">원문 또는 근거가 변경되었습니다. 편집본을 보존했습니다. 새 초안 후보와 비교해 다시 검토하세요.</div>'
            if generated["limitations"]:
                body += (
                    '<div class="notice warn">'
                    + esc(" · ".join(generated["limitations"]))
                    + "</div>"
                )
            body += (
                '<label for="draft-body">답변 내용</label><textarea id="draft-body" data-id="'
                + iid
                + '" data-version="'
                + str(d["version"])
                + '">'
                + esc(d["body"])
                + '</textarea><div class="toolbar"><button class="primary" id="save-edit">수정 저장</button><button id="save-review">검토 완료</button><button id="copy-draft">내용 복사</button><button id="hold-draft">보류</button></div><p class="status" id="save-status" role="status"></p><div class="muted">검토 완료는 실제 발송이나 업무 완료로 처리되지 않습니다.</div><details><summary>생성 원본·근거·누락 정보</summary><pre>'
                + esc(d["generated"])
                + "</pre></details>"
            )
            versions = rows(
                "SELECT * FROM draft_versions WHERE inquiry_id=? ORDER BY id DESC LIMIT 20",
                (iid,),
            )
            for v in versions:
                body += (
                    "<details><summary>초안 후보 #"
                    + str(v["id"])
                    + " · revision "
                    + str(v["revision_id"])
                    + "</summary><pre>"
                    + esc(json.loads(v["generated"])["body"])
                    + "</pre>"
                    + button(
                        "이 후보를 편집본으로 채택",
                        "/api/draft-versions/" + str(v["id"]) + "/adopt",
                        {"version": d["version"]},
                        True,
                    )
                    + "</details>"
                )
        else:
            body += '<div class="empty">아직 초안이 없습니다.<br>새 초안을 요청하면 생성 작업이 등록됩니다. 완료 후 새로고침해 확인하세요.</div>'
        if d:
            for edit in rows(
                "SELECT * FROM edits WHERE source_id=? ORDER BY id DESC LIMIT 20",
                (iid,),
            ):
                body += (
                    "<details><summary>저장한 편집본 v"
                    + str(edit["version"])
                    + " · "
                    + esc(LABELS.get(edit["review"], edit["review"]))
                    + "</summary><pre>"
                    + esc(edit["body"])
                    + "</pre></details>"
                )
        body += (
            '</section><section class="card"><h2>업무 상태 · 수동 판단</h2><form id="override-form" action="/api/inquiries/'
            + iid
            + '/override" data-revision="'
            + str(revision)
            + '"><label for="state">현재 상태</label><select id="state" name="state">'
            + "".join(
                '<option value="'
                + state
                + '" '
                + ("selected" if state == inquiry["state"] else "")
                + ">"
                + LABELS[state]
                + "</option>"
                for state in (
                    "needs_review",
                    "in_progress",
                    "waiting_external",
                    "completed",
                    "dismissed",
                )
            )
            + '</select><label for="note">판단 근거·메모</label><input id="note" name="note" placeholder="실제 답변 여부, 후속 확인 사항"><p><button class="primary">상태 저장</button></p></form><details><summary>분류 근거·변경 이력</summary>'
        )
        for c in rows(
            "SELECT * FROM classification_history WHERE inquiry_id=? ORDER BY id DESC LIMIT 10",
            (iid,),
        ):
            body += (
                "<h3>분류 · revision "
                + str(c["revision_id"])
                + "</h3><pre>"
                + esc(c["result"])
                + "</pre>"
            )
        for o in rows(
            "SELECT * FROM overrides WHERE inquiry_id=? ORDER BY id DESC LIMIT 10",
            (iid,),
        ):
            body += (
                "<p>"
                + badge(o["state"])
                + " "
                + esc(o["note"])
                + " · revision "
                + str(o["revision_id"])
                + "</p>"
            )
        for event in rows(
            "SELECT kind,revision_id FROM events WHERE inquiry_id=? ORDER BY id DESC LIMIT 20",
            (iid,),
        ):
            body += (
                '<p class="muted">'
                + esc(event["kind"])
                + " · revision "
                + str(event["revision_id"])
                + "</p>"
            )
        manual = rows(
            "SELECT * FROM manual_classifications WHERE inquiry_id=? ORDER BY id DESC LIMIT 1",
            (iid,),
        )
        effective = json.loads(manual[0]["result"]) if manual else {}
        body += "</details><details><summary>분류 직접 보정</summary>"
        if manual and manual[0]["revision_id"] != revision:
            body += '<div class="notice warn">이전 원문에 대한 수동 분류입니다. 새 변경을 확인하고 다시 저장하세요.</div>'
        body += (
            '<form id="classification-form" action="/api/inquiries/'
            + iid
            + '/classification" data-revision="'
            + str(revision)
            + '">'
        )
        for axis, label in [
            ("response_expected", "답변 필요"),
            ("action_required", "내 행동 필요"),
            ("work_performed", "수행 증거"),
            ("waiting_for_others", "상대 회신 대기"),
        ]:
            body += (
                "<label>"
                + label
                + '<select name="'
                + axis
                + '">'
                + "".join(
                    '<option value="'
                    + v
                    + '" '
                    + ("selected" if effective.get(axis, "unknown") == v else "")
                    + ">"
                    + text
                    + "</option>"
                    for v, text in [
                        ("yes", "예"),
                        ("no", "아니요"),
                        ("unknown", "확인 필요"),
                    ]
                )
                + "</select></label>"
            )
        body += (
            '<label>판단 메모<input name="note" value="'
            + esc(manual[0]["note"] if manual else "")
            + '"></label><p><button>분류 저장</button></p></form>'
        )
        body += (
            '</details><details><summary>다른 문의에 출처 연결</summary><form id="link-form" action="/api/sources/'
            + (sources[0]["id"] if sources else iid)
            + '/link"><label>대상 문의 ID<input name="target" required placeholder="대상 문의의 64자리 ID"></label><button>연결</button></form><p class="muted">현재 문의 ID <code>'
            + iid
            + "</code></p></details></section></div></div>"
        )
        body += (
            '<section class="card spaced"><h2>수행 기록 · 업무일지</h2><p><a href="/worklog?inquiry='
            + esc(iid)
            + '">이 문의에 수동 수행 기록 추가</a></p>'
        )
        for issue in rows("SELECT id,issue_key,url FROM jira_issues"):
            if any(issue["url"] in source["body"] for source in sources):
                body += (
                    '<p>연결된 JIRA 전체 본문·댓글: <a href="/inquiries/'
                    + esc(issue["id"])
                    + '">'
                    + esc(issue["issue_key"])
                    + "</a></p>"
                )
        for activity in rows(
            "SELECT id,description,status FROM activities WHERE inquiry_id=?", (iid,)
        ):
            body += (
                '<p><a href="/worklog?edit='
                + str(activity["id"])
                + '">'
                + esc(activity["description"])
                + "</a> · "
                + esc(activity["status"])
                + "</p>"
            )
        body += "</section>"
        return page(body)

    @app.post("/api/jira")
    def jira(data: JiraURL):
        from .jira import register

        try:
            return {"id": register(runtime, data.url, jira_servers)}
        except ValueError as exc:
            raise HTTPException(422, str(exc))

    @app.post("/api/jira/{issue_id}/{operation}")
    def jira_control(issue_id: str, operation: Literal["pause", "resume", "refresh"]):
        db = connect(runtime)
        try:
            with db:
                if not db.execute(
                    "UPDATE jira_issues SET state=?,next_poll=0 WHERE id=?",
                    ("paused" if operation == "pause" else "active", issue_id),
                ).rowcount:
                    raise HTTPException(404)
                audit(db, "jira_" + operation, issue_id, {})
            return {"saved": True}
        finally:
            db.close()

    @app.post("/api/jobs/{jid}/retry")
    def retry(jid: int):
        db = connect(runtime)
        try:
            with db:
                if not db.execute(
                    "UPDATE jobs SET state='pending',attempts=0,available=0,error=NULL WHERE id=? AND state IN ('failed','retry_wait','cancelled')",
                    (jid,),
                ).rowcount:
                    raise HTTPException(409, "재시도 가능한 작업이 아닙니다.")
                audit(db, "job_retry", str(jid), {})
            return {"queued": True}
        finally:
            db.close()

    @app.get("/api/operations")
    def operations_data():
        return dict(
            jobs=rows("SELECT * FROM jobs ORDER BY id DESC LIMIT 100"),
            errors=rows("SELECT * FROM sync_errors"),
            jira=rows(
                "SELECT id,server_id,issue_key,url,state,error,next_poll FROM jira_issues"
            ),
            locks=rows("SELECT name,expires FROM locks"),
            meta=rows("SELECT * FROM meta WHERE key LIKE 'last_%'"),
            attempts=rows(
                "SELECT id,job_id,length(input) AS input_chars,finished-started AS duration,error FROM attempts ORDER BY id DESC LIMIT 20"
            ),
        )

    @app.get("/operations", response_class=HTMLResponse)
    def operations():
        data = operations_data()
        body = '<header><h1>운영 상태</h1><p class="muted">수집과 AI 처리 상태를 확인하고 실패한 작업을 다시 실행하세요.</p></header><section class="card"><h2>JIRA 추적</h2><form class="toolbar" id="jira-form"><label class="grow">JIRA 이슈 URL<input name="url" type="url" required placeholder="https://jira.example/browse/PROJ-123"></label><button class="primary">이슈 등록</button></form>'
        for j in data["jira"]:
            body += (
                '<div class="action"><span>'
                + esc(j["server_id"] + " / " + j["issue_key"])
                + " "
                + badge(j["state"])
                + '<br><span class="muted">'
                + esc(j["error"] or "연결 정상")
                + "</span></span><div>"
                + button(
                    "재개" if j["state"] == "paused" else "일시중지",
                    "/api/jira/"
                    + j["id"]
                    + ("/resume" if j["state"] == "paused" else "/pause"),
                    {},
                    True,
                )
                + button("갱신 예약", "/api/jira/" + j["id"] + "/refresh", {}, True)
                + "</div></div>"
            )
        body += '</section><section class="card spaced"><h2>작업 큐</h2><div class="scroll"><table><thead><tr><th>작업</th><th>상태</th><th>시도</th><th>오류·복구</th></tr></thead><tbody>'
        for j in data["jobs"]:
            body += (
                '<tr><td><a href="/inquiries/'
                + j["source_id"]
                + '">#'
                + str(j["id"])
                + " "
                + esc(j["kind"])
                + '</a><div class="muted">revision '
                + str(j["input_version"])
                + "</div></td><td>"
                + badge(j["state"])
                + "</td><td>"
                + str(j["attempts"])
                + "</td><td>"
                + esc(j["error"] or "—")
                + (
                    " "
                    + button(
                        "다시 시도", "/api/jobs/" + str(j["id"]) + "/retry", {}, True
                    )
                    if j["state"] in ("failed", "retry_wait", "cancelled")
                    else ""
                )
                + "</td></tr>"
            )
        body += '</tbody></table></div></section><section class="card spaced"><h2>최근 실행</h2><div class="scroll"><table><thead><tr><th>작업</th><th>소요 시간</th><th>입력 분량</th><th>결과</th></tr></thead><tbody>'
        for attempt in data["attempts"]:
            body += (
                "<tr><td>#"
                + str(attempt["job_id"])
                + "</td><td>"
                + (
                    "%.1f초" % attempt["duration"]
                    if attempt["duration"] is not None
                    else "실행 중"
                )
                + "</td><td>"
                + str(attempt["input_chars"] or 0)
                + "자</td><td>"
                + esc(attempt["error"] or "성공")
                + "</td></tr>"
            )
        body += "</tbody></table></div><h3>마지막 메일 수집</h3>"
        from datetime import datetime

        for entry in data["meta"]:
            body += (
                '<p class="muted">'
                + esc(
                    local_date(
                        datetime.fromtimestamp(float(entry["value"]), UTC).isoformat()
                    )
                )
                + "</p>"
            )
        body += (
            '</section><section class="card spaced"><h2>수집 오류</h2>'
            + (
                "".join(
                    "<p><code>"
                    + esc(e["path"])
                    + "</code><br>"
                    + esc(e["error"])
                    + "</p>"
                    for e in data["errors"]
                )
                or '<p class="muted">수집 오류가 없습니다.</p>'
            )
            + "</section>"
        )
        return page(body, "ops")

    from .worklog_web import attach

    attach(app, runtime, page, esc, inquiries)
    return app
