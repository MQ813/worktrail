"""Review the project workspace in Edge using disposable library/cell fixtures."""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

from mail_jira_assistant.ai import FakeRunner
from mail_jira_assistant.project_updates import ensure_project
from mail_jira_assistant.service import enqueue, sync, worker
from mail_jira_assistant.storage import connect


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep-server", action="store_true")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = root / "runtime" / ("project-workspace-review-" + str(time.time_ns()))
    output.mkdir(parents=True)
    runtime, kb = output / "state", root / "tests/fixtures/kb"
    sync(runtime, root / "src/mail_jira_assistant/demo/inbox", history_only=False)
    enqueue(runtime)
    worker(runtime, FakeRunner(), kb)
    db = connect(runtime)
    with db:
        pid = ensure_project(db, "Atlas GPIO Library 개발", "JOB-028")
        db.execute(
            "UPDATE projects SET purpose=?,owner='Library 개발팀',state='active',started_on='2026-11-10',target_on='2027-03-31',process='28nm',development_target='GPIO Library · 1.8V / 3.3V',spec='I/O 1.8V / 3.3V\n온도 −40~125°C\nPVT 9 corners' WHERE id=?",
            (
                "28nm 공정용 GPIO library 개발. cell별 회로 설계와 PVT 검증을 마친 뒤, 검증된 library와 sign-off 보고서를 전달한다.",
                pid,
            ),
        )
        for section, text in [
            (
                "progress",
                "기본 cell 회로 설계 완료. 1.8V 계열부터 PVT 시뮬레이션을 진행하고 있습니다.",
            ),
            (
                "decisions",
                "1.8V와 3.3V 계열을 분리 검증하고, 공통 testbench를 사용하기로 결정했습니다.",
            ),
            (
                "next_actions",
                "GPIO_BIDIR_1V8의 slow corner 파형을 확인한 뒤, 3.3V 계열 검증을 시작합니다.",
            ),
        ]:
            db.execute(
                "INSERT INTO project_entries(project_id,section,kind,text) VALUES(?,?,'progress',?)",
                (pid, section, text),
            )
        items = []
        for n in range(28):
            title = (
                [
                    "GPIO_BIDIR_1V8",
                    "GPIO_BIDIR_3V3",
                    "GPIO_INPUT_SCHMITT",
                    "GPIO_OUTPUT_OPEN_DRAIN",
                ][n]
                if n < 4
                else f"GPIO_CELL_{n + 1:02}"
            )
            wid = db.execute(
                "INSERT INTO project_work_items(project_id,title,detail) VALUES(?,?,1)",
                (pid, title),
            ).lastrowid
            items.append(wid)
            for section, text in [
                (
                    "progress",
                    f"{title} · 회로 설계와 nominal 시뮬레이션 완료. slow corner의 지연 시간을 검증 중입니다.",
                ),
                (
                    "issues",
                    "저전압 조건에서 출력 지연이 목표를 넘는지 파형 확인이 필요합니다.",
                ),
                (
                    "next_actions",
                    "SS / −40°C / VDD 최소 조건의 파형을 확인하고 결과를 testbench 기준표에 기록합니다.",
                ),
            ]:
                db.execute(
                    "INSERT INTO project_entries(project_id,work_item_id,section,kind,text) VALUES(?,?,?,'progress',?)",
                    (pid, wid, section, text),
                )
        empty_pid = ensure_project(db, "신규 검증 프로젝트")
    db.close()
    server = output / "server.py"
    server.write_text(
        "import threading,time,uvicorn\nfrom mail_jira_assistant.web import create_app\nfrom mail_jira_assistant.ai import FakeRunner\nfrom mail_jira_assistant.service import worker\n"
        f"runtime={str(runtime)!r}\nkb={str(kb)!r}\n"
        "def run():\n    while True:\n        worker(runtime,FakeRunner(),kb)\n        time.sleep(.2)\n"
        "threading.Thread(target=run,daemon=True).start()\n"
        f"uvicorn.run(create_app(runtime,kb,sample_mode=True),host='127.0.0.1',port={args.port})\n",
        encoding="utf-8",
    )
    log = (output / "server.log").open("w", encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, str(server)],
        stdout=log,
        stderr=log,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    base = f"http://127.0.0.1:{args.port}"
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(base + "/projects", timeout=1).close()
                break
            except OSError:
                time.sleep(0.1)
        errors, checks = [], []
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="msedge", headless=True)
            context = browser.new_context(locale="ko-KR", reduced_motion="reduce")
            page = context.new_page()
            page.on("pageerror", lambda e: errors.append(str(e)))
            routes = [
                ("list", "/projects"),
                ("overview", f"/projects/{pid}"),
                ("issues", f"/projects/{pid}?view=issues"),
                ("issue", f"/projects/{pid}?work_item={items[0]}"),
                ("records", f"/projects/{pid}?view=records"),
                ("review", f"/projects/{pid}?view=review"),
                ("settings", f"/projects/{pid}?view=settings"),
                ("empty", f"/projects/{empty_pid}"),
                ("empty-issues", f"/projects/{empty_pid}?view=issues"),
            ]
            for width in (320, 390, 768, 1024, 1440):
                page.set_viewport_size({"width": width, "height": 1000})
                for name, route in routes:
                    assert page.goto(base + route).status == 200
                    assert page.evaluate(
                        "document.documentElement.scrollWidth<=innerWidth"
                    ), (name, width)
                    assert page.locator("h1").count() == 1
                    assert page.locator('nav [aria-current="page"]').count() == 1
                    assert not page.locator(
                        "input:not([type=hidden]),select,textarea"
                    ).evaluate_all(
                        "es=>es.filter(e=>!e.labels.length&&!e.getAttribute('aria-label')).map(e=>e.name)"
                    )
                    checks.append(dict(name=name, width=width))
                    if width in (390, 1440):
                        page.screenshot(
                            path=str(output / f"{name}-{width}.png"), full_page=True
                        )
            page.set_viewport_size({"width": 1440, "height": 1000})
            page.goto(base + f"/projects/{pid}?view=issues")
            assert page.locator(".issue-name").count() == 12
            page.get_by_role("link", name="다음", exact=True).click()
            assert "issue_page=2" in page.url
            page.get_by_label("이슈 검색").fill("GPIO_BIDIR_1V8")
            page.get_by_role("button", name="검색", exact=True).click()
            assert page.locator(".issue-name").count() == 1
            page.locator(".issue-name").click()
            assert (
                page.locator(".issue-detail-heading h2").inner_text()
                == "GPIO_BIDIR_1V8"
            )
            first = page.locator(".workspace-entry").first
            first.locator("summary").click()
            long_note = "GPIO_BIDIR_1V8 · 브라우저에서 편집한 한국어 검증 내용. " * 25
            first.locator("textarea").fill(long_note)
            first.get_by_role("button", name="수정 저장", exact=True).click()
            page.wait_for_load_state("networkidle")
            page.reload()
            assert long_note in page.locator(".issue-detail").text_content()
            page.get_by_role("button", name="이슈 AI로 편집", exact=True).click()
            assert page.locator("dialog textarea").evaluate(
                "e=>e===document.activeElement"
            )
            page.keyboard.press("Escape")
            assert page.get_by_role(
                "button", name="이슈 AI로 편집", exact=True
            ).evaluate("e=>e===document.activeElement")
            page.get_by_role("button", name="이슈 AI로 편집", exact=True).click()
            form = page.locator("dialog .project-ai-form")
            form.get_by_role("button", name="AI로 업데이트", exact=True).click()
            form.get_by_text("요청 내용 또는 문의를 선택하세요.", exact=True).wait_for()
            form.get_by_label("AI 요청", exact=True).fill(
                "SS corner의 지연 검증을 다음 검토 항목으로 기록해줘."
            )
            form.get_by_role("button", name="AI로 업데이트", exact=True).click()
            assert not form.get_by_role(
                "button", name="AI로 업데이트", exact=True
            ).is_enabled()
            form.locator(".form-feedback").filter(has_text="AI").wait_for()
            page.wait_for_url(
                f"**/projects/{pid}?view=issues&work_item={items[0]}",
                wait_until="networkidle",
            )
            page.get_by_text(
                "SS corner의 지연 검증을 다음 검토 항목으로 기록해줘.", exact=True
            ).first.wait_for()
            page.get_by_role("link", name="변경 내용 확인 →").click()
            page.get_by_role("button", name="내용 확인", exact=True).click()
            page.wait_for_load_state("networkidle")
            page.get_by_role("heading", name="사용자 확인", exact=False).wait_for()
            page.get_by_role("button", name="변경 되돌리기", exact=True).click()
            page.wait_for_load_state("networkidle")
            page.get_by_role("heading", name="되돌림", exact=False).wait_for()
            page.goto(base + f"/projects/{pid}?view=issues")
            page.get_by_role("link", name="이슈 추가", exact=True).click()
            page.get_by_label("이슈 제목", exact=True).fill(
                "GPIO_NEW_CELL · 긴 한국어 검증 이슈"
            )
            page.get_by_role("button", name="이슈 만들기", exact=True).click()
            page.wait_for_url("**/projects/*?view=issues&work_item=*")
            assert "GPIO_NEW_CELL" in page.locator(".issue-detail-heading").inner_text()
            page.get_by_text("이슈 내용 추가", exact=True).click()
            page.locator("#entry-composer textarea").fill(
                "새 cell의 입력 임계값 검증 조건을 확인합니다."
            )
            page.locator("#entry-composer button").click()
            page.get_by_text(
                "새 cell의 입력 임계값 검증 조건을 확인합니다.", exact=True
            ).first.wait_for()
            page.goto(base + f"/projects/{pid}?view=settings")
            page.get_by_label("담당자", exact=True).fill("검증 담당팀")
            page.get_by_role("button", name="개요 저장", exact=True).click()
            page.wait_for_load_state("networkidle")
            page.get_by_role("link", name="개요", exact=True).click()
            page.get_by_text("검증 담당팀", exact=True).wait_for()
            page.reload()
            page.keyboard.press("Tab")
            assert page.locator(":focus").inner_text() == "본문으로 건너뛰기"
            # Contrast of the semantic tokens against their actual intended surfaces.
            contrasts = page.evaluate("""() => {
              const s=getComputedStyle(document.documentElement), luminance=c=>{const v=c.match(/[\\d.]+/g).slice(0,3).map(x=>{x=+x/255;return x<=.04045?x/12.92:((x+.055)/1.055)**2.4});return .2126*v[0]+.7152*v[1]+.0722*v[2]};
              return [['--ink','--canvas'],['--muted','--canvas'],['--accent','--canvas'],['--warning-ink','--warning-bg']].map(([a,b])=>{const probe=document.createElement('span');document.body.append(probe);probe.style.color=s.getPropertyValue(a);const x=luminance(getComputedStyle(probe).color);probe.style.color=s.getPropertyValue(b);const y=luminance(getComputedStyle(probe).color);probe.remove();return {pair:[a,b],ratio:(Math.max(x,y)+.05)/(Math.min(x,y)+.05)}});
            }""")
            assert all(c["ratio"] >= 4.5 for c in contrasts), contrasts
            assert not errors, errors
            page.screenshot(path=str(output / "final-overview.png"), full_page=True)
            page.goto(base + f"/projects/{pid}?work_item={items[1]}")
            page.screenshot(path=str(output / "final-issue.png"), full_page=True)
            browser.close()
        subprocess.run(
            [
                sys.executable,
                str(root / "scripts/ui_review.py"),
                "--url",
                base,
                "--channel",
                "msedge",
                "--output",
                str(output / "general"),
            ],
            check=True,
        )
        report = dict(
            checks=checks,
            javascript_errors=errors,
            contrasts=contrasts,
            flows=[
                "pagination",
                "issue search",
                "edit/reload long Korean",
                "dialog focus/escape",
                "AI validation/loading/scoped update",
                "confirm/undo",
                "create issue",
                "add scoped entry",
                "metadata save",
                "skip link",
            ],
            server_pid=process.pid,
            project_id=pid,
            work_item_ids=items,
            url=base,
        )
        (output / "verification.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(output)
    finally:
        if not args.keep_server:
            process.terminate()
            process.wait(timeout=15)
        log.close()


if __name__ == "__main__":
    main()
