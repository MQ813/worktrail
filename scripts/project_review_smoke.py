"""Browser QA for project review on disposable synthetic data only."""

import json
import os
import subprocess
import sys
import time
import urllib.request
from email.message import EmailMessage
from pathlib import Path

from playwright.sync_api import sync_playwright

from mail_jira_assistant.ai import FakeRunner
from mail_jira_assistant.project_updates import ensure_project
from mail_jira_assistant.service import enqueue, sync, worker
from mail_jira_assistant.storage import connect

root = Path(__file__).resolve().parents[1]
output = root / "runtime" / ("project-review-" + str(time.time_ns()))
output.mkdir(parents=True)
inbox = output / "inbox"
inbox.mkdir()
message = EmailMessage()
message["From"] = "customer@example.test"
message["To"] = "engineer@example.test"
message["Message-ID"] = "<review@test>"
message["Subject"] = "JOB-006 SmartIO 검증"
message.set_content(
    "TODO: 파형과 회로 검증 요청\n결정: 수정안 A로 진행\n일정: 시험 기한은 2026-11-20"
)
(inbox / "one.eml").write_bytes(message.as_bytes())
runtime = output / "state"
db = connect(runtime)
with db:
    pid = ensure_project(db, "SmartIO Maintenance", "JOB-006")
    db.execute(
        "INSERT OR REPLACE INTO meta VALUES('ai_connection_status','합성 FakeRunner · UI 검증')"
    )
db.close()
sync(runtime, inbox, history_only=False)
enqueue(runtime)
worker(runtime, FakeRunner(), root / "tests/fixtures/kb")
(output / "server.py").write_text(
    "import uvicorn\nfrom mail_jira_assistant.web import create_app\n"
    f"uvicorn.run(create_app({str(runtime)!r}, {str(root / 'tests/fixtures/kb')!r}, sample_mode=True), host='127.0.0.1', port=8779)\n",
    encoding="utf-8",
)
log = (output / "server.log").open("w", encoding="utf-8")
process = subprocess.Popen(
    [sys.executable, str(output / "server.py")],
    stdout=log,
    stderr=log,
    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
)
base = "http://127.0.0.1:8779"
try:
    for _ in range(100):
        try:
            urllib.request.urlopen(base + "/projects", timeout=1).close()
            break
        except OSError:
            time.sleep(0.1)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, channel="msedge")
        context = browser.new_context(locale="ko-KR", reduced_motion="reduce")
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda err: errors.append(str(err)))
        checks = []
        for width in (320, 390, 768, 1440):
            page.set_viewport_size({"width": width, "height": 1000})
            for route in ("/projects", f"/projects/{pid}", "/today"):
                assert page.goto(base + route).status == 200
                assert page.locator("h1").count() == 1
                assert page.evaluate(
                    "document.documentElement.scrollWidth <= innerWidth"
                ), (route, width)
                assert page.locator('nav a[aria-current="page"]').count() == 1
                assert page.locator("nav a").all_text_contents() == [
                    "오늘",
                    "문의함",
                    "프로젝트",
                    "운영 상태",
                ]
                assert page.locator(".workspace-bar").count() == 0
                assert (
                    page.locator(
                        "#main .connection-status, #main .sample-notice"
                    ).count()
                    == 0
                )
                assert page.locator(".sidebar-status .connection-status").count() == 1
                assert page.locator(".sidebar-status .sample-notice").count() == 1
                unnamed = page.locator(
                    "input:not([type=hidden]),select,textarea"
                ).evaluate_all(
                    "els=>els.filter(e=>!e.labels.length&&!e.getAttribute('aria-label')).map(e=>e.name)"
                )
                assert not unnamed, unnamed
                checks.append({"route": route, "width": width})
                if route == f"/projects/{pid}" and width in (390, 1440):
                    page.screenshot(
                        path=str(output / f"project-{width}.png"), full_page=True
                    )
        page.set_viewport_size({"width": 1440, "height": 1000})
        page.goto(base + f"/projects/{pid}")
        page.keyboard.press("Tab")
        assert page.locator(":focus").inner_text() == "본문으로 건너뛰기"
        first = page.locator("[data-change-id]").first
        first.locator("summary").click()
        assert first.locator("blockquote").count() >= 1
        first.locator("textarea").fill("사람이 검토한 결정 내용")
        with page.expect_navigation(wait_until="networkidle"):
            first.locator('[data-project-review="confirmed"]').click()
        assert "사람이 검토한 결정 내용" in page.locator(".project-entry").inner_text()
        assert page.locator('[data-project-review="confirmed"]:disabled').count() >= 1
        with page.expect_navigation(wait_until="networkidle"):
            page.locator('[data-project-review="rejected"]').first.click()
        assert not errors, errors
        page.goto(base + "/")
        metrics = page.evaluate("""() => ({
          tableTop: document.querySelector('.inquiry-table').getBoundingClientRect().top,
          rowHeight: document.querySelector('.inquiry-table tbody tr').getBoundingClientRect().height,
          mainTop: document.querySelector('#main').getBoundingClientRect().top,
          footerBottom: document.querySelector('.sidebar-status').getBoundingClientRect().bottom
        })""")
        assert metrics["tableTop"] < 250, metrics
        assert metrics["rowHeight"] <= 48, metrics
        assert metrics["mainTop"] == 0, metrics
        page.screenshot(path=str(output / "inbox-1440.png"), full_page=True)
        detail = page.locator("a.title").first.get_attribute("href")
        page.goto(base + detail)
        ratio = page.locator(".source pre").first.evaluate(
            "e=>parseFloat(getComputedStyle(e).lineHeight)/parseFloat(getComputedStyle(e).fontSize)"
        )
        assert ratio <= 1.5
        page.screenshot(path=str(output / "message-1440.png"), full_page=True)
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
            str(output / "general-review"),
        ],
        check=True,
    )
    (output / "verification.json").write_text(
        json.dumps(
            {
                "checks": checks,
                "errors": errors,
                "review_flow": "passed",
                "density": metrics,
                "message_line_height": ratio,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(output)
finally:
    process.terminate()
    process.wait(timeout=10)
    log.close()
