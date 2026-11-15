"""Project directory tabs and the dedicated manual/AI workspaces."""

import json
from urllib.parse import urlencode

from .project_views import excerpt


def header(tab, count):
    body = '<header class="project-top"><h1>프로젝트</h1></header><nav class="project-tabs directory-tabs" aria-label="프로젝트 탐색">'
    for key, title in (
        ("list", "프로젝트 목록"),
        ("connections", "연결 검토"),
        ("new", "프로젝트 추가"),
        ("ai", "AI"),
        ("history", "작업 이력"),
    ):
        href = "/projects" if key == "list" else "/projects?" + urlencode({"tab": key})
        current = ' aria-current="location"' if tab == key else ""
        badge = f" <span>{count}</span>" if key == "connections" and count else ""
        body += f'<a href="{href}"{current}>{title}{badge}</a>'
    return body + "</nav>"


def create_form():
    return MANUAL_FORM


def ai_workspace(query, esc, inquiry="", project_id=0):
    targets = '<option value="auto">요청 내용에서 찾기</option><option value="new">새 프로젝트</option>'
    for p in query("SELECT id,code,name FROM projects ORDER BY code"):
        selected = " selected" if p["id"] == project_id else ""
        targets += f'<option value="{p["id"]}"{selected}>{esc(p["code"])} · {esc(p["name"])}</option>'
    sources = ""
    for s in query(
        "SELECT s.id,s.subject FROM sources s JOIN inquiries i ON i.id=s.id ORDER BY (s.id=?) DESC,s.rowid DESC LIMIT 100",
        (inquiry,),
    ):
        selected = " selected" if s["id"] == inquiry else ""
        sources += (
            f'<option value="{esc(s["id"])}"{selected}>{esc(s["subject"])}</option>'
        )
    return (
        AI_WORKSPACE.replace("$TARGET_OPTIONS", targets)
        .replace("$SOURCE_OPTIONS", sources)
        .replace("$SOURCES_OPEN", "open" if inquiry else "")
    )


def request_history(query, esc):
    rows = query(
        "SELECT r.*,j.state AS job_state,j.error,p.code,p.name FROM project_ai_requests r LEFT JOIN jobs j ON j.request_id=r.id AND j.kind='project_command' LEFT JOIN projects p ON p.id=r.project_id ORDER BY r.created DESC LIMIT 100"
    )
    body = '<div class="section-heading"><h2>작업 이력</h2><a class="text-link" href="/projects?tab=history">새로고침</a></div>'
    if not rows:
        return (
            body
            + '<p class="empty">아직 AI 요청이 없습니다. <a href="/projects?tab=ai">AI에게 요청하기</a></p>'
        )
    body += '<div class="scroll"><table class="directory-history"><thead><tr><th>요청 내용</th><th>대상 프로젝트</th><th>처리 상태</th><th>요청 시각</th></tr></thead><tbody>'
    from datetime import datetime

    for r in rows:
        state = {
            "ready": "변경안 확인",
            "applied": "반영 완료",
            "searched": "검색 완료",
            "needs_input": "추가 정보 필요",
        }.get(
            r["state"],
            {
                "pending": "대기",
                "running": "처리 중",
                "retry_wait": "재시도 대기",
                "failed": "실패",
                "succeeded": "완료",
            }.get(r["job_state"], "대기"),
        )
        request = json.loads(r["input"])
        target = (
            f'<a href="/projects/{r["project_id"]}">{esc(r["code"])} · {esc(r["name"])}</a>'
            if r["project_id"]
            else ("신규 프로젝트" if request["mode"] == "create" else "요청에서 판단")
        )
        body += f'<tr><td><a class="text-link" href="/projects?tab=ai&amp;request={esc(r["id"])}">{esc(excerpt(request["text"] or "참고 문의에서 정리", 160))}</a>'
        if r["question"] or r["error"]:
            body += f'<p class="row-excerpt">{esc(excerpt(r["question"] or r["error"], 200))}</p>'
        when = datetime.fromtimestamp(r["created"]).astimezone().strftime("%m.%d %H:%M")
        body += f'</td><td>{target}</td><td><span class="status-label">{state}</span></td><td>{when}</td></tr>'
    return body + "</tbody></table></div>"


MANUAL_FORM = r"""
      <div class="project-create-screen">
        <div class="creation-layout">
          <div class="creation-editor">
            <form id="project-create-form" novalidate>
              <div class="section-heading"><h2>기본 정보</h2></div>
              <label for="project-name">프로젝트 이름 <span class="required-label">필수</span></label><input id="project-name" name="name" placeholder="예: Atlas GPIO Library 개발" maxlength="300" required aria-describedby="name-error"><p class="field-error" id="name-error" hidden></p>
              <label for="project-purpose">목적·산출물 <span class="required-label">필수</span></label><textarea id="project-purpose" name="purpose" placeholder="어떤 일을 완료하고, 무엇을 전달할지 적어 주세요." maxlength="5000" required aria-describedby="purpose-error"></textarea><p class="field-error" id="purpose-error" hidden></p>
              <div class="creation-fields"><label>공정<input id="project-process" name="process" placeholder="예: 28nm" maxlength="300"></label><label>개발 대상<input id="project-target" name="development_target" placeholder="예: GPIO Library · 1.8V / 3.3V" maxlength="300"></label><label>담당자<input id="project-owner" name="owner" placeholder="담당자 또는 팀 이름" maxlength="300"></label><label>목표 일정<input type="date" id="project-date" name="target_on"></label></div>
              <details class="optional-fields" id="spec-fields"><summary>Spec·추가 정보 <span>선택</span></summary><label>Spec<textarea id="project-spec" name="spec" placeholder="전압, 온도, 검증 조건 등" maxlength="5000"></textarea></label><label>시작일<input type="date" id="project-start" name="started_on"></label></details>
              <div class="creation-actions"><button class="primary">프로젝트 만들기</button><a class="button" href="/projects">취소</a></div><p role="alert" class="field-error" id="form-feedback" hidden></p>
            </form>
          </div>
          <aside class="creation-summary" aria-labelledby="summary-title"><div class="section-heading"><h2 id="summary-title">작성 내용</h2><span id="summary-origin">직접 입력</span></div><div class="summary-document"><span class="project-code">프로젝트 번호 · 자동 부여</span><h3 id="summary-name">새 프로젝트</h3><p id="summary-purpose" class="muted">프로젝트 이름과 목적을 입력하면 이곳에서 한눈에 확인할 수 있습니다.</p><dl id="summary-facts"><div><dt>공정</dt><dd data-summary="process">미지정</dd></div><div><dt>개발 대상</dt><dd data-summary="target">미지정</dd></div><div><dt>담당자</dt><dd data-summary="owner">미지정</dd></div><div><dt>목표 일정</dt><dd data-summary="date">미정</dd></div></dl><div id="summary-spec-block" hidden><h4>Spec</h4><p id="summary-spec"></p></div></div><p class="summary-note">생성 후 프로젝트 개요와<br>하위 이슈를 구분해서 관리합니다.</p></aside>
        </div>
      </div>


"""

AI_WORKSPACE = r"""
      <section id="ai-screen" aria-labelledby="ai-heading">
        <h2 id="ai-heading" class="sr-only">AI 프로젝트 작업</h2>
        <div class="ai-workspace">
          <div class="ai-composer creation-editor">
            <form id="ai-workspace-form" novalidate>
              <div class="section-heading"><h2>AI에게 요청</h2><button type="button" class="text-button" id="ai-reset">새 요청</button></div>
              <label for="ai-request">요청할 내용 <span class="required-label">필수</span></label>
              <textarea id="ai-request" aria-describedby="ai-help ai-error" placeholder="프로젝트를 찾거나, 새로 만들거나, 기존 내용을 수정해 주세요. 메일 내용을 그대로 붙여 넣어도 됩니다." maxlength="8000" required></textarea>
              <p class="muted" id="ai-help">여러 작업을 한 번에 요청할 수 있습니다.</p><p class="field-error" id="ai-error" hidden></p>
              <div class="ai-examples" role="group" aria-label="요청 예시"><span>예시</span><button type="button" data-ai-example="create">신규 생성</button><button type="button" data-ai-example="update">내용 수정</button><button type="button" data-ai-example="search">검색</button><button type="button" data-ai-example="auto">찾아서 정리</button></div>
              <label for="ai-target">대상 프로젝트</label>
              <select id="ai-target" aria-describedby="ai-target-help">$TARGET_OPTIONS</select>
              <p class="muted" id="ai-target-help">수정할 프로젝트를 알고 있다면 직접 선택하세요.</p>
              <details class="optional-fields" $SOURCES_OPEN><summary>참고 문의 <span>선택</span></summary><label for="ai-inquiries">참고할 문의</label><select id="ai-inquiries" multiple size="4">$SOURCE_OPTIONS</select><p class="muted">Ctrl 키로 여러 문의를 선택할 수 있습니다.</p></details>
              <div class="creation-actions"><button class="primary" id="ai-submit">요청 실행</button><span class="action-note">생성·수정은 변경안을 확인한 뒤 반영합니다.</span></div>
              <p id="ai-progress" class="prototype-feedback" role="status"></p>
            </form>

          </div>
          <section class="ai-output" aria-labelledby="ai-output-title" aria-busy="false">
            <div class="section-heading"><h2 id="ai-output-title" tabindex="-1">처리 결과</h2><span id="ai-result-kind">요청 대기</span></div>
            <div id="ai-output-body"><div class="ai-empty"><h3>요청한 작업을 이곳에서 확인합니다</h3><p>찾은 프로젝트, 수정할 내용, 새로 만들 내용을 구분해서 보여줍니다.</p><ol><li>내용과 일치하는 프로젝트 확인</li><li>생성·수정할 내용 확인 및 편집</li><li>반영 결과를 목록과 작업 이력에서 확인</li></ol><p class="muted">요청 예시로 요청을 시작할 수 있습니다.</p></div></div>
          </section>
        </div>
      </section>


"""
