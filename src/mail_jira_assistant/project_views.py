"""Server-rendered project workspace: overview, scoped issues and review tools."""

import json
from urllib.parse import urlencode

from . import project_ai_web
from .project_updates import SECTIONS

STATES = {
    "active": "진행 중",
    "completed": "완료",
    "paused": "보류",
    "cancelled": "취소",
}


def url(pid, view="overview", **params):
    return f"/projects/{pid}?" + urlencode({"view": view, **params})


def excerpt(text, limit=120):
    text = " ".join((text or "").split())
    return text[:limit] + ("…" if len(text) > limit else "")


def prose(text, esc, limit=360):
    if len(text or "") <= limit:
        return f'<p class="project-text">{esc(text)}</p>'
    return f'<details class="long-content"><summary>{esc(excerpt(text, 180))} <span class="text-link">전체 내용</span></summary><p class="project-text">{esc(text)}</p></details>'


def index_table(rows, esc, q="", attention=""):
    filtered = [
        p
        for p in rows
        if q.casefold() in (p["code"] + p["name"] + p["purpose"]).casefold()
        and (not attention or p["unconfirmed"] or p["pending"])
    ]
    body = '<header class="project-top"><div><h1>프로젝트</h1><p>목표와 진행 내용, 하위 이슈를 한곳에서 관리합니다.</p></div><div class="toolbar"><a class="button" href="#ai-project-request">AI로 생성</a><a class="button primary" href="#new-project">프로젝트 추가</a></div></header>'
    body += f'<form class="workspace-filter" method="get"><label>프로젝트 검색<input type="search" name="q" value="{esc(q)}" placeholder="이름, 프로젝트 번호, 목적"></label><label>확인 상태<select name="attention"><option value="">전체 프로젝트</option><option value="review"{" selected" if attention else ""}>확인이 필요한 프로젝트</option></select></label><button>검색</button></form>'
    body += f'<section class="project-directory"><div class="section-heading"><h2>프로젝트 목록 <span class="muted">{len(filtered)}개</span></h2></div>'
    if not filtered:
        body += (
            '<p class="empty">검색 결과가 없습니다. 검색 조건을 바꾸거나 프로젝트를 추가하세요.</p>'
            if rows
            else '<p class="empty">프로젝트가 없습니다. 프로젝트를 추가하거나 AI로 첫 프로젝트를 만들어 보세요.</p>'
        )
    else:
        body += '<div class="scroll"><table class="project-table"><thead><tr><th>프로젝트 / 목적</th><th>상태</th><th>목표 일정</th><th>하위 이슈</th><th>확인</th></tr></thead><tbody>'
        for p in filtered:
            count = p["unconfirmed"] + p["pending"]
            body += f'<tr><td><a class="project-name" href="/projects/{p["id"]}"><span class="project-code">{esc(p["code"])}</span><strong>{esc(p["name"])}</strong></a><p class="row-excerpt">{esc(excerpt(p["purpose"]) or "목적 미입력")}</p></td><td><span class="status-label">{esc(STATES.get(p["state"], p["state"]))}</span></td><td>{esc(p["target_on"] or "TBD")}</td><td><a class="text-link" href="{url(p["id"], "issues")}">{p["issue_count"]}개</a></td><td>'
            body += (
                f'<a class="review-label" href="{url(p["id"], "review")}">확인 필요 {count}</a>'
                if count
                else '<span class="muted">—</span>'
            )
            body += "</td></tr>"
        body += "</tbody></table></div>"
    return body + "</section>"


class Workspace:
    def __init__(self, query, esc, p, entries, changes, items):
        self.query, self.esc, self.p = query, esc, p
        self.pid = p["id"]
        self.entries, self.changes, self.items = entries, changes, items
        self.unconfirmed = project_ai_web.unconfirmed_entries(query, self.pid)
        self.histories = query(
            "SELECT * FROM project_ai_history WHERE project_id=? AND confirmed=0 AND reverted=0",
            (self.pid,),
        )

    def header(self, view, item=None):
        p, esc, pid = self.p, self.esc, self.pid
        body = f'<div class="project-back"><a href="/projects">← 프로젝트 목록</a><span>{esc(p["code"])}</span></div>'
        body += f'<header class="project-top"><div><div class="project-title"><h1>{esc(p["name"])}</h1><span class="status-label">{esc(STATES.get(p["state"], p["state"]))}</span></div></div><div class="toolbar"><a class="button" href="{url(pid, "records")}#record-editor">수행 기록 추가</a><button class="primary" data-open-dialog="project-ai-dialog">{"이슈 AI로 편집" if item else "AI로 업데이트"}</button></div></header>'
        body += '<nav class="project-tabs" aria-label="프로젝트 내 탐색">'
        for key, title, count in (
            ("overview", "개요", None),
            ("issues", "하위 이슈", len(self.items)),
            ("records", "수행 기록", None),
            ("review", "변경 검토", len(self.changes) + len(self.histories)),
            ("settings", "자료·설정", None),
        ):
            current = ' aria-current="location"' if view == key else ""
            body += f'<a href="{url(pid, key)}"{current}>{title}{f" <span>{count}</span>" if count is not None else ""}</a>'
        body += "</nav>"
        if (self.histories or self.changes) and view != "review":
            pending = " · ".join(
                part
                for part in (
                    f"AI 반영 · 미확인 {len(self.histories)}건"
                    if self.histories
                    else "",
                    f"미확정 {len(self.changes)}건" if self.changes else "",
                )
                if part
            )
            body += f'<div class="review-notice"><span>{pending}</span><a href="{url(pid, "review")}">변경 내용 확인 →</a></div>'
        body += '<dialog id="project-ai-dialog" class="workspace-dialog" aria-labelledby="ai-dialog-title"><div class="section-heading"><h2 id="ai-dialog-title">AI로 내용 업데이트</h2><button type="button" data-close-dialog>닫기</button></div>'
        body += f'<p class="ai-scope">대상 · {esc(item["title"] if item else p["name"])}</p>'
        body += project_ai_web.form(
            self.query, esc, pid=pid, work_item_id=item["id"] if item else None
        )
        return body + "</dialog>"

    def editor(self, wid=None):
        body = f'<details class="entry-composer" id="entry-composer"><summary>{"이슈 내용 추가" if wid else "프로젝트 내용 추가"}</summary><form data-project-api="/api/projects/{self.pid}/entries" data-version="{self.p["version"]}">'
        if wid:
            body += f'<input type="hidden" name="work_item_id" value="{wid}">'
        body += (
            '<label>기록 구역<select name="section">'
            + "".join(
                f'<option value="{key}">{label}</option>'
                for key, label in SECTIONS.items()
            )
            + '</select></label><label>내용<textarea name="text" required maxlength="5000"></textarea></label><button>내용 저장</button><p role="status" class="form-feedback"></p></form></details>'
        )
        return body

    def entry(self, e):
        esc = self.esc
        pending = (e["id"], e["version"], e["text"]) in self.unconfirmed
        body = f'<article class="workspace-entry" id="entry-{e["id"]}">'
        if pending:
            body += '<span class="entry-origin">AI 반영 · 미확인</span>'
        body += prose(e["text"], esc)
        body += f'<div class="entry-actions"><details class="entry-edit"><summary>내용 편집<span class="sr-only"> #{e["id"]}</span></summary><form data-project-api="/api/projects/{self.pid}/entries/{e["id"]}" data-method="PUT" data-version="{self.p["version"]}"><input type="hidden" name="section" value="{e["section"]}"><label>내용<textarea name="text" required maxlength="5000">{esc(e["text"])}</textarea></label><button>수정 저장</button><p role="status" class="form-feedback"></p></form></details><button class="entry-ai-action" data-open-dialog="project-ai-dialog" data-ai-prompt="기록 #{e["id"]}의 내용을 수정해줘. 변경할 정보: ">AI로 편집<span class="sr-only"> #{e["id"]}</span></button></div></article>'
        return body

    def content(self, wid=None, include_editor=True):
        entries = [e for e in self.entries if e["work_item_id"] == wid]
        if not entries:
            return (
                '<div class="workspace-empty"><h3>아직 기록한 내용이 없습니다</h3><p>내용을 직접 추가하거나 상단 AI로 업데이트를 요청하세요.</p><a class="text-link" href="#entry-composer">내용 추가 →</a></div>'
                + (self.editor(wid) if include_editor else "")
            )
        body = ""
        for key, title in SECTIONS.items():
            relevant = [e for e in entries if e["section"] == key]
            if not relevant:
                continue
            body += f'<section class="content-section"><h2>{title}<span class="muted">{len(relevant)}</span></h2>'
            # Recent entries first. Older content remains available without a long initial page.
            relevant.reverse()
            body += "".join(self.entry(e) for e in relevant[:3])
            if len(relevant) > 3:
                body += (
                    f'<details class="older-entries"><summary>이전 내용 {len(relevant) - 3}건 보기</summary>'
                    + "".join(self.entry(e) for e in relevant[3:])
                    + "</details>"
                )
            body += "</section>"
        return body + (self.editor(wid) if include_editor else "")

    def overview(self):
        p, esc, pid = self.p, self.esc, self.pid
        body = (
            '<div class="overview-layout"><div class="overview-content"><section class="project-purpose"><div class="section-heading"><h2>프로젝트 목적</h2><a class="text-link" href="'
            + url(pid, "settings")
            + '">개요 편집</a></div>'
        )
        body += (
            prose(
                p["purpose"]
                or "목적을 입력하면 프로젝트의 개발 범위를 한눈에 확인할 수 있습니다.",
                esc,
            )
            + "</section>"
        )
        if any(e["work_item_id"] is None for e in self.entries) or not self.items:
            body += self.content(include_editor=False)
        if self.items:
            body += f'<section class="content-section"><div class="section-heading"><h2>하위 이슈 <span class="muted">{len(self.items)}개</span></h2><a class="text-link" href="{url(pid, "issues")}">전체 보기 →</a></div>'
            body += self.issue_table(self.items[:4]) + "</section>"
        body += self.editor()
        body += '</div><aside class="project-facts" aria-label="프로젝트 기본 정보"><div class="section-heading"><h2>기본 정보</h2></div><dl>'
        for field, label in (
            ("owner", "담당자"),
            ("target_on", "목표 일정"),
            ("started_on", "시작일"),
            ("process", "공정"),
            ("development_target", "개발 대상"),
            ("spec", "Spec"),
        ):
            body += f"<div><dt>{label}</dt><dd>{prose(p[field] or '미지정', esc, 180)}</dd></div>"
        body += f'</dl><a class="text-link" href="{url(pid, "settings")}">기본 정보 편집 →</a></aside></div>'
        return body

    def issue_table(self, items):
        esc = self.esc
        body = '<div class="scroll"><table class="issue-table"><thead><tr><th>이슈</th><th>최근 내용</th><th>기록</th></tr></thead><tbody>'
        for w in items:
            entries = [e for e in self.entries if e["work_item_id"] == w["id"]]
            last = entries[-1] if entries else None
            pending = sum(
                (e["id"], e["version"], e["text"]) in self.unconfirmed for e in entries
            )
            body += f'<tr><td><a class="issue-name" href="{url(self.pid, "issues", work_item=w["id"])}"><span class="project-code">#{w["id"]}</span><strong>{esc(w["title"])}</strong></a>{f"<span class=entry-origin>미확인 {pending}건</span>" if pending else ""}</td><td><span class="row-excerpt">{esc(excerpt(last["text"], 90)) if last else "내용을 추가해 주세요"}</span></td><td>{len(entries)}</td></tr>'
        return body + "</tbody></table></div>"

    def issues(self, item=None, q="", issue_page=1):
        esc, pid = self.esc, self.pid
        filtered = [w for w in self.items if q.casefold() in w["title"].casefold()]
        search = f'<form class="workspace-filter issue-filter" method="get"><input type="hidden" name="view" value="issues"><label>이슈 검색<input type="search" name="q" value="{esc(q)}" placeholder="cell 이름 또는 이슈 제목"></label><button>검색</button><span class="muted">{len(filtered)}개 / 전체 {len(self.items)}개</span></form>'
        body = ""
        if not item:
            body = (
                '<div class="section-heading"><h2>하위 이슈</h2><a class="button" href="#new-issue">이슈 추가</a></div>'
                + search
            )
        if item:
            body += (
                '<div class="issue-workspace"><aside class="issue-navigation" aria-label="하위 이슈 목록"><a class="issue-back text-link" href="'
                + url(pid, "issues")
                + '">← 전체 이슈</a>'
                + search
                + '<form class="issue-mobile-switch" method="get"><input type="hidden" name="view" value="issues"><label>이슈 전환<select name="work_item">'
                + "".join(
                    f'<option value="{w["id"]}"{" selected" if w["id"] == item["id"] else ""}>{esc(w["title"])}</option>'
                    for w in self.items
                )
                + "</select></label><button>이동</button></form><ul>"
            )
            for w in filtered:
                current = ' aria-current="true"' if w["id"] == item["id"] else ""
                body += f'<li><a href="{url(pid, "issues", work_item=w["id"], **({"q": q} if q else {}))}"{current}><span class="project-code">#{w["id"]}</span>{esc(w["title"])}</a></li>'
            body += f'</ul></aside><div class="issue-detail"><div class="issue-detail-heading"><span class="project-code">하위 이슈 #{item["id"]}</span><h2>{esc(item["title"])}</h2><p class="muted">이 이슈의 진행·결정·다음 액션을 따로 기록합니다.</p></div>'
            body += self.content(item["id"])
            body += f'<details class="entry-composer"><summary>이슈 문서 설정</summary><form data-project-api="/api/projects/{pid}/work-items" data-version="{self.p["version"]}"><input type="hidden" name="title" value="{esc(item["title"])}"><label><input type="checkbox" name="detail"{" checked" if item["detail"] else ""}> 내보낼 때 별도 이슈 문서 생성</label><button>설정 저장</button><p role="status" class="form-feedback"></p></form></details></div></div>'
        elif filtered:
            pages = max(1, (len(filtered) + 11) // 12)
            issue_page = min(max(1, issue_page), pages)
            offset = (issue_page - 1) * 12
            body += self.issue_table(filtered[offset : offset + 12])
            if pages > 1:
                body += f'<div class="list-pagination"><span class="muted">{offset + 1}–{min(offset + 12, len(filtered))} / {len(filtered)}개</span>'
                if issue_page > 1:
                    body += f'<a class="button" href="{url(pid, "issues", q=q, issue_page=issue_page - 1)}">이전</a>'
                if issue_page < pages:
                    body += f'<a class="button" href="{url(pid, "issues", q=q, issue_page=issue_page + 1)}">다음</a>'
                body += "</div>"
        else:
            body += (
                '<div class="workspace-empty"><h3>검색 결과가 없습니다</h3><p>다른 이슈 제목으로 검색해 보세요.</p></div>'
                if self.items
                else '<div class="workspace-empty"><h3>하위 이슈가 없습니다</h3><p>cell별 개발이나 검증 항목을 이슈로 추가하면 각각의 내용을 따로 관리할 수 있습니다.</p></div>'
            )
        body += f'<details class="entry-composer" id="new-issue"><summary>하위 이슈 추가</summary><form data-project-api="/api/projects/{pid}/work-items" data-version="{self.p["version"]}"><label>이슈 제목<input name="title" required maxlength="300" placeholder="예: GPIO_CELL_A 타이밍 검증"></label><input type="hidden" name="detail" value="true"><button>이슈 만들기</button><p role="status" class="form-feedback"></p></form></details>'
        return body

    def review(self):
        esc = self.esc
        body = '<div class="section-heading"><h2>변경 검토</h2><span>AI 반영 확인과 변경 제안 검토</span></div>'
        body += project_ai_web.history(self.query, esc, self.pid)
        if not self.changes and not self.histories:
            body += (
                '<p class="empty empty-compact">확인을 기다리는 변경이 없습니다.</p>'
            )
        names = {w["id"]: w["title"] for w in self.items}
        for c in self.changes:
            payload = json.loads(c["payload"])
            fresh = (
                "검토 가능"
                if c["freshness"] == "current"
                else "재검토 필요 · " + c["freshness"]
            )
            body += f'<article class="project-change" data-change-id="{c["id"]}"><div class="section-heading"><h3>미확정 변경 #{c["id"]} · {esc(SECTIONS[payload["section"]])}</h3><span>{esc(fresh)}</span></div>'
            wid = payload.get("work_item_id")
            body += f'<p class="muted">대상 · {esc(names.get(wid, payload.get("work_title") or "프로젝트 공통"))}</p>'
            if c["before_text"]:
                body += f'<details><summary>기존 내용</summary><blockquote class="project-text">{esc(c["before_text"])}</blockquote></details>'
            body += f'<label>변경 제안 · 수정 후 확정 가능<textarea class="project-proposal" maxlength="5000">{esc(payload["text"])}</textarea></label><p>{esc(payload.get("reason", ""))}</p><details><summary>근거 확인</summary>'
            if c["inquiry_id"]:
                body += f'<a class="text-link" href="/inquiries/{esc(c["inquiry_id"])}">메일·Jira 원문 · revision {c["revision_id"]}</a>'
            for evidence in payload["evidence"]:
                body += f'<blockquote class="project-text">{esc(evidence["text"])}</blockquote>'
            disabled = " disabled" if c["freshness"] != "current" else ""
            body += f'</details><div class="toolbar"><label><input type="checkbox" class="project-select" value="{c["id"]}"{disabled}> 묶음 검토에 선택</label><button class="primary" data-project-review="confirmed"{disabled}>확정 / 수정 후 확정</button><button data-project-review="rejected">반려</button></div><p role="alert" class="form-feedback"></p></article>'
        if self.changes:
            body += '<div class="toolbar spaced"><button data-project-batch="confirmed">선택한 변경 확정</button><button data-project-batch="rejected">선택한 변경 반려</button><p role="alert" id="project-review-feedback"></p></div>'
        body += '<details class="entry-composer"><summary>이전 검토 이력</summary>'
        for r in self.query(
            "SELECT r.* FROM project_reviews r JOIN project_changes c ON c.id=r.change_id WHERE c.project_id=? ORDER BY r.id DESC LIMIT 100",
            (self.pid,),
        ):
            body += f'<p class="project-text">변경 #{r["change_id"]} · {esc({"confirmed": "확정", "rejected": "반려"}.get(r["decision"], r["decision"]))} · {esc(json.loads(r["payload"])["text"])}</p>'
        return body + "</details>"

    def settings(self):
        esc, p, pid = self.esc, self.p, self.pid
        body = '<div class="settings-layout"><section><h2>프로젝트 개요 수정</h2>'
        body += f'<form data-project-api="/api/projects/{pid}" data-method="PUT" data-version="{p["version"]}"><label>목적<textarea name="purpose" maxlength="5000">{esc(p["purpose"])}</textarea></label><div class="form-grid">'
        for name, label in (
            ("owner", "담당자"),
            ("state", "상태"),
            ("started_on", "시작일"),
            ("target_on", "목표 일정 (YYYY-MM-DD 또는 TBD)"),
            ("process", "공정"),
            ("development_target", "개발 대상"),
        ):
            if name == "state":
                options = dict(STATES)
                options.setdefault(p[name], p[name])
                body += (
                    '<label>상태<select name="state">'
                    + "".join(
                        f'<option value="{esc(value)}"{" selected" if value == p[name] else ""}>{esc(title)}</option>'
                        for value, title in options.items()
                    )
                    + "</select></label>"
                )
            else:
                body += f'<label>{label}<input type="{"date" if name == "started_on" else "text"}" name="{name}" value="{esc(p[name])}"></label>'
        body += f'</div><label>Spec<textarea name="spec">{esc(p["spec"])}</textarea></label><button>개요 저장</button><p role="status" class="form-feedback"></p></form></section><aside><h2>문서 내보내기</h2><div class="export-links"><a class="button" href="/api/projects/{pid}/export">Markdown 내보내기</a><a class="button" href="/api/projects/{pid}/archive">JOB 폴더 ZIP</a><a class="button" href="/api/projects/{pid}/export?pending=false">확정본 내보내기</a></div><h2>관련 메일·Jira</h2>'
        sources = self.query(
            "SELECT DISTINCT s.id,s.subject FROM sources s WHERE s.id IN (SELECT inquiry_id FROM project_source_links WHERE project_id=? UNION SELECT inquiry_id FROM inquiry_projects WHERE project_id=?)",
            (pid, pid),
        )
        if not sources:
            body += '<p class="muted">연결된 메일·Jira가 없습니다.</p>'
        for i in sources:
            body += f'<div class="linked-source"><a class="text-link" href="/inquiries/{esc(i["id"])}">{esc(i["subject"])}</a><button data-command="/api/projects/{pid}/unlink" data-payload="{esc(json.dumps({"inquiry_id": i["id"]}))}" data-reload="true">연결 해제</button></div>'
        body += f'<a class="text-link" href="/projects?project_id={pid}#project-form">메일·Jira 연결 →</a><details class="entry-composer"><summary>업데이트 다시 생성</summary><button data-command="/api/projects/{pid}/regenerate">최신 내용으로 다시 생성</button><p><a class="text-link" href="/operations">처리 상태·실패 확인 →</a></p></details>'
        body += f'<details class="entry-composer"><summary>기간을 지정해 기존 이력 재구성</summary><form data-project-api="/api/projects/{pid}/replay-history"><label>수집 시작일<input type="date" name="start" required></label><label>수집 종료일<input type="date" name="end" required></label><p>한국 시간 기준 최대 500건을 처리합니다. 결과는 미확정으로 표시합니다.</p><button>이력 재구성 요청</button><p role="status" class="form-feedback"></p></form></details>'
        body += f'<details class="entry-composer"><summary>외부 문서 수정 가져오기</summary><form data-project-api="/api/projects/{pid}/import-document"><label>Markdown 전체 경로<input name="path" required></label><p>원본을 보존하고 변경 후보를 가져옵니다.</p><button>변경 후보 가져오기</button><p role="status" class="form-feedback"></p></form></details></aside></div>'
        return body
