"""Real Edge QA on a disposable synthetic project-command server."""

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

from mail_jira_assistant.ai import FakeRunner
from mail_jira_assistant.service import enqueue, sync, worker
from mail_jira_assistant.storage import connect

root = Path(__file__).resolve().parents[1]
output = root / "runtime" / ("ai-project-review-" + str(time.time_ns()))
output.mkdir(parents=True)
runtime = output / "state"
sync(runtime, root / "src/mail_jira_assistant/demo/inbox", history_only=False)
enqueue(runtime)
worker(runtime, FakeRunner(), root / "tests/fixtures/kb")
db = connect(runtime)
iid = db.execute("SELECT id FROM inquiries LIMIT 1").fetchone()[0]
with db:
    db.execute(
        "INSERT OR REPLACE INTO project_unassigned VALUES(?,?,?)",
        (
            iid,
            db.execute(
                "SELECT max(id) FROM revisions WHERE inquiry_id=?", (iid,)
            ).fetchone()[0],
            "[]",
        ),
    )
db.close()
(output / "server.py").write_text(
    """import threading,time
import uvicorn
from mail_jira_assistant.web import create_app
from mail_jira_assistant.service import worker
from mail_jira_assistant.ai import FakeRunner
runtime=RUNTIME
kb=KB
def run():
    while True:
        worker(runtime,FakeRunner(),kb)
        time.sleep(.2)
threading.Thread(target=run,daemon=True).start()
uvicorn.run(create_app(runtime,kb,sample_mode=True),host='127.0.0.1',port=8783)
""".replace("RUNTIME", repr(str(runtime))).replace(
        "KB", repr(str(root / "tests/fixtures/kb"))
    ),
    encoding="utf-8",
)
log = (output / "server.log").open("w", encoding="utf-8")
process = subprocess.Popen(
    [sys.executable, str(output / "server.py")],
    stdout=log,
    stderr=log,
    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
)
base = "http://127.0.0.1:8783"
try:
    for _ in range(100):
        try:
            urllib.request.urlopen(base + "/projects", timeout=1).close()
            break
        except OSError:
            time.sleep(0.1)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(locale="ko-KR", reduced_motion="reduce")
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(base + "/projects?tab=connections")
        page.get_by_role(
            "link", name="AI로 프로젝트 찾기·정리", exact=True
        ).first.click()
        page.locator("#ai-submit").click()
        page.locator("#ai-proposal-form").wait_for(timeout=30000)
        page.get_by_role("button", name="변경안 반영", exact=True).click()
        page.get_by_role("link", name="변경 검토에서 보기", exact=True).click()
        page.wait_for_url("**/projects/*?view=review", timeout=30000)
        pid = urlsplit(page.url).path.rsplit("/", 1)[1]
        assert page.get_by_role("heading", name="AI 반영 · 미확인 · #1").count() == 1
        page.get_by_role("button", name="내용 확인", exact=True).click()
        page.wait_for_load_state("networkidle")
        assert page.get_by_role("heading", name="사용자 확인 · #1").count() == 1
        page.get_by_role("button", name="AI로 업데이트", exact=True).click()
        form = page.locator(".project-ai-form")
        form.locator("[name=text]").fill("긴 한국어 개발 검증 요청 " * 35)
        form.get_by_role("button", name="AI로 업데이트", exact=True).click()
        page.get_by_role("heading", name="AI 반영 · 미확인 · #2").wait_for(
            timeout=30000
        )
        page.get_by_role("button", name="변경 되돌리기", exact=True).first.click()
        page.wait_for_load_state("networkidle")
        assert page.get_by_role("heading", name="되돌림 · #2").count() == 1
        checks = []
        for width in (320, 390, 768, 1440):
            page.set_viewport_size({"width": width, "height": 1000})
            for route in ("/projects", f"/projects/{pid}"):
                page.goto(base + route)
                page.locator("details").evaluate_all(
                    "(items)=>items.forEach(item=>item.open=true)"
                )
                assert page.evaluate(
                    "document.documentElement.scrollWidth<=innerWidth"
                ), (width, route)
                assert page.locator("nav [aria-current=page]").count() == 1
                assert page.locator("h1").count() == 1
                checks.append({"width": width, "route": route, "overflow": False})
        page.goto(base + f"/projects/{pid}")
        page.keyboard.press("Tab")
        assert (
            page.evaluate("document.activeElement.textContent").strip()
            == "본문으로 건너뛰기"
        )
        page.screenshot(path=str(output / "detail.png"), full_page=True)
        # Empty input feedback remains near the form.
        page.get_by_role("button", name="AI로 업데이트", exact=True).click()
        page.locator(".project-ai-form button").click()
        page.get_by_text("요청 내용 또는 문의를 선택하세요.", exact=True).wait_for()
        assert not errors, errors
        (output / "verification.json").write_text(
            json.dumps(
                {
                    "checks": checks,
                    "flows": [
                        "create",
                        "confirm",
                        "update",
                        "undo",
                        "validation",
                        "keyboard",
                    ],
                    "javascript_errors": errors,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        browser.close()
    subprocess.run(
        [
            sys.executable,
            str(root / "scripts/ui_review.py"),
            "--channel",
            "msedge",
            "--url",
            base,
            "--output",
            str(output / "general"),
        ],
        check=True,
    )
    print(output)
finally:
    process.terminate()
    process.wait(timeout=15)
    log.close()
