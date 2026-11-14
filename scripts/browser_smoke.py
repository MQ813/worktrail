"""Optional real-browser smoke; run only against a disposable demo runtime."""

import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright

p = argparse.ArgumentParser()
p.add_argument("--url", default="http://127.0.0.1:8765")
p.add_argument("--output", default="runtime/browser-review")
a = p.parse_args()
output = Path(a.output)
output.mkdir(parents=True, exist_ok=True)
with sync_playwright() as pw:
    browser = pw.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--no-zygote",
            "--single-process",
            "--disable-software-rasterizer",
        ],
    )
    context = browser.new_context(
        viewport={"width": 1440, "height": 1000}, locale="ko-KR"
    )
    page = context.new_page()
    errors = []
    external = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.on(
        "console", lambda msg: errors.append(msg.text) if msg.type == "error" else None
    )

    def route(req):
        if not req.request.url.startswith(a.url):
            external.append(req.request.url)
            req.abort()
        else:
            req.continue_()

    page.route("**/*", route)
    page.goto(a.url)
    page.wait_for_selector("a.title")
    page.screenshot(path=str(output / "inbox-desktop.png"), full_page=True)
    page.locator("a.title").first.click()
    page.wait_for_selector("#draft-body")
    page.locator("#draft-body").fill(
        "브라우저에서 수정한 합성 초안입니다. 측정 조건을 확인 부탁드립니다."
    )
    page.locator("#save-edit").click()
    page.wait_for_function(
        "() => document.querySelector('#save-status').textContent==='저장했습니다.'"
    )
    page.locator("#save-review").click()
    page.wait_for_function(
        "() => document.querySelector('#save-status').textContent.includes('검토 완료')"
    )
    page.reload()
    assert "브라우저에서 수정한" in page.locator("#draft-body").input_value()
    assert "검토 완료" in page.locator(".badge").all_text_contents()
    form = page.locator("#override-form")
    form.locator("select").select_option("in_progress")
    form.locator("input").fill("브라우저 검증 중")
    form.locator("button").click()
    page.wait_for_load_state("networkidle")
    assert page.locator("#state").input_value() == "in_progress"
    page.evaluate("window.scrollTo(0,0)")
    page.get_by_text("분류 직접 보정", exact=True).click()
    manual = page.locator("#classification-form")
    manual.locator('select[name="response_expected"]').select_option("no")
    manual.locator('input[name="note"]').fill("브라우저 분류 보정 검증")
    with page.expect_navigation():
        manual.locator("button").click()
    page.wait_for_selector("#draft-body")
    page.evaluate("window.scrollTo(0,0)")
    page.screenshot(path=str(output / "detail-desktop.png"), full_page=True)
    page.set_viewport_size({"width": 390, "height": 844})
    page.screenshot(path=str(output / "detail-mobile.png"), full_page=True)
    assert page.evaluate("document.documentElement.scrollWidth<=window.innerWidth")
    page.goto(a.url + "/operations")
    page.wait_for_selector("#jira-form")
    page.screenshot(path=str(output / "operations-mobile.png"), full_page=True)
    assert not errors, errors
    assert not external, external
    browser.close()
print(
    "Browser smoke passed: edit/reload/review/state/mobile/offline assets; screenshots:",
    output,
)
