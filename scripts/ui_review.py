"""Opt-in visual/interaction review against a disposable sample server.

Requires Playwright; Windows can use the installed Edge via --channel msedge.
This writes one confirmed worklog record and edits/reviews one sample draft.
"""

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8767")
    parser.add_argument(
        "--output", type=Path, default=Path("runtime/ui-redesign/review")
    )
    parser.add_argument("--channel", default=None)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    errors, external, checks = [], [], []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, channel=args.channel)
        context = browser.new_context(locale="ko-KR", reduced_motion="reduce")
        page = context.new_page()
        page.set_default_timeout(10000)
        page.on("pageerror", lambda err: errors.append(str(err)))

        def route(req):
            if not req.request.url.startswith(args.url + "/"):
                external.append(req.request.url)
                req.abort()
            else:
                req.continue_()

        page.route("**/*", route)
        page.goto(args.url)
        detail = page.locator("a.title").first.get_attribute("href")
        routes = [
            ("/", "inbox", "/"),
            ("/?view=drafts", "draft-filter", "/"),
            ("/today", "today", "/today"),
            ("/projects", "projects", "/projects"),
            ("/operations", "operations", "/operations"),
            (detail, "detail", "/"),
        ]
        for width in (320, 375, 390, 768, 1024, 1440):
            page.set_viewport_size({"width": width, "height": 900})
            for path, name, selected in routes:
                response = page.goto(args.url + path)
                assert response.status == 200, (path, response.status)
                assert page.locator("h1").count() == 1, path
                current = page.locator('nav a[aria-current="page"]')
                assert (
                    current.count() == 1 and current.get_attribute("href") == selected
                )
                assert page.evaluate(
                    "document.documentElement.scrollWidth <= innerWidth"
                ), (path, width, "viewport overflow")
                unnamed = page.locator(
                    "input:not([type=hidden]), select, textarea"
                ).evaluate_all(
                    "els => els.filter(e => !e.labels.length && !e.getAttribute('aria-label'))"
                    ".map(e => e.name || e.id)"
                )
                assert not unnamed, (path, unnamed)
                if width in (390, 1440):
                    page.screenshot(
                        path=str(args.output / f"{name}-{width}.png"), full_page=True
                    )
                checks.append({"page": name, "width": width})

        page.set_viewport_size({"width": 1440, "height": 1000})
        page.goto(args.url)
        page.keyboard.press("Tab")
        assert page.locator(".skip-link").evaluate("e => e === document.activeElement")
        page.keyboard.press("Enter")
        assert page.locator("#main").evaluate("e => e === document.activeElement")
        assert (
            page.locator(".primary").first.evaluate(
                "e => getComputedStyle(e).transitionDuration"
            )
            == "0s"
        )

        page.get_by_label("문의 검색", exact=True).fill("NO-MATCH-WORKTRAIL-UI")
        page.get_by_role("button", name="검색", exact=True).click()
        page.wait_for_url("**q=NO-MATCH-WORKTRAIL-UI**")
        assert page.locator(".empty").is_visible()
        page.get_by_role("link", name="초기화", exact=True).click()
        page.wait_for_selector("a.title")
        page.get_by_text("상세 필터", exact=True).click()
        page.locator('select[name="work"]').select_option("actions")
        page.get_by_role("button", name="검색", exact=True).click()
        page.wait_for_url("**work=actions**")
        assert page.locator(".advanced-filters").get_attribute("open") is not None

        page.goto(args.url + detail)
        editor = page.locator("#draft-body")
        original = editor.input_value()
        editor.fill(original + "\nUI 브라우저 검증 메모")
        assert "저장하지 않은" in page.locator("#save-status").inner_text()
        page.locator("#save-edit").click()
        page.wait_for_function(
            "() => document.querySelector('#save-status').textContent === '저장했습니다.'"
        )
        page.reload()
        assert "UI 브라우저 검증 메모" in editor.input_value()
        editor.fill(original)
        page.locator("#save-review").click()
        page.wait_for_function(
            "() => document.querySelector('#save-status').textContent.includes('검토 완료')"
        )

        response = context.request.post(
            args.url + "/api/projects", data={"name": "UI 검증 프로젝트"}
        )
        pid = response.json()["id"]
        page.goto(args.url + f"/projects/{pid}?view=records")
        page.locator("#record-editor > summary").click()
        form = page.locator("#activity-form")
        form.get_by_label("수행 내용", exact=True).fill("UI 브라우저 검증용 수행 기록")
        form.locator('select[name="status"]').select_option("confirmed")
        form.get_by_role("button", name="기록 저장", exact=True).click()
        page.wait_for_url("**/projects/*?on=**")
        assert "UI 브라우저 검증용 수행 기록" in page.locator("table").inner_text()
        assert not errors, errors
        assert not external, external
        browser.close()
    report = {
        "layout_checks": checks,
        "interactions": [
            "active navigation",
            "field labels",
            "skip link",
            "reduced motion",
            "empty search",
            "advanced filters",
            "draft save/reload/review",
            "worklog save",
        ],
        "page_errors": errors,
        "external_requests": external,
    }
    (args.output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"UI review passed: {len(checks)} page/width combinations; interactions; offline assets. {args.output}"
    )


if __name__ == "__main__":
    main()
