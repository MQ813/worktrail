"""Browser/interaction review of project tabs and staged AI on a disposable server."""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from mail_jira_assistant.ai import FakeRunner
from mail_jira_assistant.project_ai import CommandResult
from mail_jira_assistant.project_updates import ensure_project
from mail_jira_assistant.service import enqueue, sync, worker
from mail_jira_assistant.storage import connect


class ReviewRunner(FakeRunner):
    def project_command(self, request):
        time.sleep(0.5)
        if not request.preview:
            return super().project_command(request)
        if "강제 실패" in request.instruction:
            raise ValueError("검증용 실패입니다. 입력을 바꿔 다시 요청하세요.")
        if "추가 정보" in request.instruction:
            return CommandResult(question="변경할 일정과 대상 프로젝트를 알려 주세요.")
        if request.mode == "search":
            return CommandResult(
                outcome="search",
                matches=[]
                if "없는" in request.instruction
                else [
                    dict(
                        project_id=p["id"],
                        reason="GPIO Library와 3.3V 개발 범위가 일치합니다.",
                    )
                    for p in request.projects
                    if "GPIO" in p["name"]
                ],
            )
        p = next((p for p in request.projects if p["id"] == request.project_id), None)
        if not p and request.mode == "auto" and "없는대상" not in request.instruction:
            p = next((p for p in request.projects if "GPIO" in p["name"]), None)
        if p:
            issue = p["work_items"][0] if p["work_items"] else None
            return CommandResult(
                outcome="update",
                project_id=p["id"],
                metadata={"target_on": "2027-04-15"},
                changes=[
                    dict(
                        project_id=p["id"],
                        work_item_id=issue["id"] if issue else None,
                        section="next_actions",
                        kind="schedule",
                        text="2027년 12월 7일 PVT 검증을 시작합니다.",
                        evidence=[dict(source_ref="user", text=request.instruction)],
                    )
                ],
            )
        return CommandResult(
            outcome="create",
            name="없던 프로젝트 개발"
            if "없는대상" in request.instruction
            else "Nova DAC 개발",
            metadata={
                "purpose": "40nm DAC 개발과 PVT 검증 보고서 전달",
                "process": "40nm",
                "owner": "Analog 개발팀",
                "target_on": "2027-06-30",
            },
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8798)
    parser.add_argument("--keep-server", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = root / "runtime" / ("project-directory-review-" + str(time.time_ns()))
    output.mkdir(parents=True)
    runtime = output / "state"
    kb = root / "tests/fixtures/kb"
    sync(runtime, root / "src/mail_jira_assistant/demo/inbox", history_only=False)
    enqueue(runtime)
    worker(runtime, FakeRunner(), kb)
    db = connect(runtime)
    with db:
        pid = ensure_project(db, "Atlas GPIO Library 개발", "JOB-028")
        db.execute(
            "UPDATE projects SET purpose='28nm GPIO library · 1.8V / 3.3V cell 개발과 PVT 검증',owner='Library 개발팀',target_on='2027-03-31',process='28nm',development_target='GPIO Library',spec='1.8V / 3.3V' WHERE id=?",
            (pid,),
        )
        for name in ("GPIO_BIDIR_3V3", "GPIO_BIDIR_1V8"):
            wid = db.execute(
                "INSERT INTO project_work_items(project_id,title,detail) VALUES(?,?,1)",
                (pid, name),
            ).lastrowid
            db.execute(
                "INSERT INTO project_entries(project_id,work_item_id,section,kind,text) VALUES(?,?,'progress','progress','nominal 시뮬레이션 완료')",
                (pid, wid),
            )
        ensure_project(db, "Orion ADC 검증", "JOB-041")
    db.close()
    (output / "settings.toml").write_text(
        'profile="demo"\nai_backend="fake"\nhistory_only=true\nsample_mode=true\nruntime="state"\ninbox="inbox"\nknowledge="knowledge"\nautomatic_drafts=false\n',
        encoding="utf-8",
    )
    server = output / "server.py"
    server.write_text(
        "import sys,threading,time,uvicorn\n"
        + f"sys.path.insert(0,{str(root)!r})\n"
        + "from scripts.project_directory_review import ReviewRunner\nfrom mail_jira_assistant.web import create_app\nfrom mail_jira_assistant.service import worker\n"
        + f"runtime={str(runtime)!r}\nkb={str(kb)!r}\n"
        + "def run():\n    while True:\n        worker(runtime,ReviewRunner(),kb)\n        time.sleep(.1)\n"
        + "threading.Thread(target=run,daemon=True).start()\n"
        + f'uvicorn.run(create_app(runtime,kb,sample_mode=True),host="127.0.0.1",port={args.port})\n',
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
    errors = []
    external = []
    checks = []
    flows = []
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(base + "/projects", timeout=1).close()
                break
            except OSError:
                time.sleep(0.1)
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="msedge", headless=True)
            context = browser.new_context(locale="ko-KR", reduced_motion="reduce")
            page = context.new_page()
            page.set_default_timeout(15000)
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on(
                "request",
                lambda r: (
                    external.append(r.url) if not r.url.startswith(base) else None
                ),
            )

            def navigate(tab="ai"):
                page.goto(base + "/projects?tab=" + tab)

            def run(text=None, target="auto", example=None):
                if example:
                    page.locator("[data-ai-example=" + example + "]").click()
                    if example == "update":
                        page.locator("#ai-target").select_option(str(pid))
                        page.locator("#ai-request").fill(
                            "Atlas GPIO Library의 목표 일정을 2027-04-15로 바꾸고 GPIO_BIDIR_3V3 이슈에 2027-12-07 검증 시작을 추가해줘."
                        )
                else:
                    page.locator("#ai-request").fill(text)
                    page.locator("#ai-target").select_option(str(target))
                page.locator("#ai-submit").click()
                expect(page.locator(".ai-output")).to_have_attribute(
                    "aria-busy", "true"
                )
                expect(page.locator(".ai-output")).to_have_attribute(
                    "aria-busy", "false", timeout=30000
                )

            for width in (320, 390, 768, 1024, 1440):
                page.set_viewport_size({"width": width, "height": 1000})
                for tab in ("list", "connections", "new", "ai", "history"):
                    navigate(tab)
                    assert page.locator(".directory-tabs a").count() == 5
                    assert page.locator(".directory-tabs [aria-current]").count() == 1
                    assert page.locator("h1").count() == 1
                    assert page.evaluate(
                        "document.documentElement.scrollWidth<=innerWidth"
                    ), (width, tab)
                    assert page.locator(
                        "input:not([type=hidden]),select,textarea"
                    ).evaluate_all("es=>es.every(e=>e.labels.length>0)"), (width, tab)
                    assert "JOB 폴더 가져오기" not in page.locator("main").inner_text()
                    checks.append({"width": width, "tab": tab})
                    if width in (390, 1440):
                        page.screenshot(
                            path=str(output / f"{tab}-{width}.png"), full_page=True
                        )
                for mode in ("create", "update", "search", "auto"):
                    navigate()
                    run(example=mode)
                    assert page.evaluate(
                        "document.documentElement.scrollWidth<=innerWidth"
                    ), (width, mode)
                    checks.append({"width": width, "result": mode})
                    if width in (390, 1440):
                        page.screenshot(
                            path=str(output / f"ai-{mode}-{width}.png"), full_page=True
                        )
            page.set_viewport_size({"width": 1440, "height": 1000})
            navigate("new")
            page.get_by_role("button", name="프로젝트 만들기", exact=True).click()
            expect(page.locator("#name-error")).to_be_visible()
            assert page.locator("#project-name").evaluate(
                "e=>e===document.activeElement"
            )
            page.locator("#project-name").fill("수동 생성 검증")
            page.locator("#project-purpose").fill(
                "긴 한국어 목적·산출물 <script>원문 표시</script>"
            )
            page.locator("#project-process").fill("28nm")
            page.locator("#project-target").fill("GPIO")
            page.locator("#project-date").fill("2027-06-30")
            page.get_by_role("link", name="AI", exact=True).click()
            page.get_by_role("link", name="프로젝트 추가", exact=True).click()
            expect(page.locator("#project-name")).to_have_value("수동 생성 검증")
            expect(page.locator("#summary-purpose")).to_contain_text("<script>")
            page.get_by_role("button", name="프로젝트 만들기", exact=True).click()
            page.wait_for_url("**/projects/*")
            page.reload()
            assert "긴 한국어 목적" in page.locator("main").inner_text()
            flows.append("manual fields, errors/focus, draft preservation, save/reload")
            navigate()
            page.locator("#ai-reset").click()
            page.locator("#ai-submit").click()
            expect(page.locator("#ai-error")).to_be_visible()
            run(example="update")
            request = page.url
            expect(page.locator("#ai-result-kind")).to_have_text(
                "기존 프로젝트 업데이트"
            )
            page.locator("[data-metadata=target_on]").fill("2027-04-20")
            page.locator("[data-change-text]").fill("사용자가 편집한 한국어 검증 일정")
            page.reload()
            expect(page.locator("[data-metadata=target_on]")).to_have_value(
                "2027-04-20"
            )
            expect(page.locator("[data-change-text]")).to_have_value(
                "사용자가 편집한 한국어 검증 일정"
            )
            page.get_by_role("button", name="변경안 반영", exact=True).click()
            expect(page.locator("#ai-result-kind")).to_have_text("반영 완료")
            page.get_by_role("link", name="프로젝트 열기", exact=True).click()
            assert "2027-04-20" in page.locator("main").inner_text()
            page.locator('.project-tabs a[href*="view=issues"]').click()
            page.locator(".issue-name").first.click()
            assert (
                "사용자가 편집한 한국어 검증 일정" in page.locator("main").inner_text()
            )
            page.goto(request)
            expect(page.locator("#ai-result-kind")).to_have_text("반영 완료")
            flows.append(
                "update common and issue, edit/apply, project persistence, request reload"
            )
            navigate()
            run(example="create")
            page.locator("#proposal-name").fill("Nova DAC 사용자 수정")
            page.get_by_role("button", name="변경안 반영", exact=True).click()
            expect(page.locator("#ai-result-kind")).to_have_text("반영 완료")
            flows.append("create proposal/edit/apply")
            navigate()
            run(example="search")
            expect(page.locator(".ai-match")).to_contain_text("Atlas GPIO")
            page.get_by_role(
                "button", name="이 프로젝트에 요청하기", exact=True
            ).click()
            expect(page.locator("#ai-target")).to_have_value(str(pid))
            run("없는 프로젝트 찾아줘")
            expect(page.locator("#ai-create-from-search")).to_be_visible()
            page.locator("#ai-create-from-search").click()
            expect(page.locator("#ai-target")).to_have_value("new")
            flows.append(
                "readonly search, choose target, empty search to create request"
            )
            navigate()
            run(
                "기존 프로젝트면 수정하고 없으면 만들어줘. Atlas GPIO Library 검증 일정 2027-04-15"
            )
            expect(page.locator("#ai-result-kind")).to_have_text(
                "기존 프로젝트 업데이트"
            )
            run("기존 프로젝트면 수정하고 없으면 만들어줘. 없는대상 · 검증 보고서 전달")
            expect(page.locator("#ai-result-kind")).to_have_text("신규 프로젝트 생성")
            flows.append("conditional matched update / unmatched create")
            navigate()
            run("추가 정보 필요")
            expect(page.locator("#ai-result-kind")).to_have_text("추가 정보 필요")
            page.locator("#ai-revise").click()
            assert page.locator("#ai-request").evaluate("e=>e===document.activeElement")
            run("강제 실패")
            expect(page.locator("#ai-result-kind")).to_have_text("처리 실패")
            flows.append("additional information and worker failure recovery")
            navigate()
            run(example="update")
            page.reload()
            expect(page.locator("#ai-result-kind")).to_have_text(
                "기존 프로젝트 업데이트"
            )
            db = connect(runtime)
            with db:
                db.execute("UPDATE projects SET version=version+1 WHERE id=?", (pid,))
            db.close()
            page.get_by_role("button", name="변경안 반영", exact=True).click()
            expect(page.locator("#proposal-error")).to_contain_text("변경되었습니다")
            page.get_by_role("link", name="작업 이력", exact=True).click()
            assert "변경안 확인" in page.locator("main").inner_text()
            flows.append("durable proposal, optimistic conflict/no write, history")
            page.goto(base + "/projects?q=Atlas&state=active")
            page.get_by_role("link", name="프로젝트 추가", exact=True).click()
            page.get_by_role("link", name="프로젝트 목록", exact=True).click()
            expect(page.locator("input[name=q]")).to_have_value("Atlas")
            expect(page.locator("select[name=state]")).to_have_value("active")
            flows.append("tab filter preservation")
            page.goto(base + "/projects?tab=ai&keyboard=1")
            page.keyboard.press("Tab")
            assert page.locator(".skip-link").evaluate("e=>e===document.activeElement")
            page.keyboard.press("Enter")
            assert page.locator("#main").evaluate("e=>e===document.activeElement")
            flows.append("keyboard skip and focus")
            navigate()
            run(example="update")
            page.screenshot(path=str(output / "final-ai.png"), full_page=True)
            page.set_viewport_size({"width": 390, "height": 844})
            page.locator("#ai-request").fill(
                "긴 한국어 GPIO 라이브러리 개발 검증 내용 " * 100
            )
            page.locator("[data-change-text]").fill(
                "하위 이슈의 긴 한국어 검증 기록 " * 100
            )
            assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
            page.screenshot(path=str(output / "long-korean-390.png"), full_page=True)
            assert not errors, errors
            assert not external, external
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
        (output / "verification.json").write_text(
            json.dumps(
                {
                    "checks": checks,
                    "flows": flows,
                    "javascript_errors": errors,
                    "external_requests": external,
                    "server_pid": process.pid,
                    "runtime": str(runtime),
                    "project_id": pid,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(output)
    finally:
        if not args.keep_server:
            process.terminate()
            process.wait(timeout=15)
        log.close()


if __name__ == "__main__":
    main()
