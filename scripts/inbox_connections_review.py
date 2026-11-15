"""Edge QA for inbox shortcuts, source colors and project connection review."""

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
from mail_jira_assistant.sample_data import install, prepare
from mail_jira_assistant.service import worker
from mail_jira_assistant.settings import Settings
from mail_jira_assistant.storage import connect


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep-server", action="store_true")
    parser.add_argument("--port", type=int, default=8793)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = root / "runtime" / ("inbox-connections-review-" + str(time.time_ns()))
    output.mkdir(parents=True)
    settings = Settings(**prepare(output))
    settings.runtime = str(output / "state")
    install(settings.runtime, settings)
    worker(settings.runtime, FakeRunner(), settings.knowledge)
    db = connect(settings.runtime)
    with db:
        pid = ensure_project(db, "WT65 ESD Library 검증", "JOB-065")
        candidates = db.execute(
            "SELECT u.* FROM project_unassigned u JOIN sources s ON s.id=u.inquiry_id WHERE s.kind!='jira' ORDER BY u.revision_id LIMIT 2"
        ).fetchall()
        assert len(candidates) == 2
        candidate_ids = {r["inquiry_id"] for r in candidates}
        for r in db.execute("SELECT id,state FROM inquiries").fetchall():
            if r["id"] not in candidate_ids and r["state"] != "dismissed":
                db.execute(
                    "INSERT INTO project_source_links VALUES(?,?,'user')",
                    (r["id"], pid),
                )
        # Legacy rows must be excluded even before the background worker can prune them.
        legacy = db.execute(
            "SELECT c.source_id,c.result FROM classifications c JOIN inquiries i ON i.id=c.source_id WHERE i.state='dismissed'"
        ).fetchall()
        for r in legacy:
            value = json.loads(r["result"])
            for key in ("project_update_needed", "project_hints", "update_kinds"):
                value.pop(key, None)
            db.execute(
                "UPDATE classifications SET result=? WHERE source_id=?",
                (json.dumps(value), r["source_id"]),
            )
            revision = db.execute(
                "SELECT max(id) FROM revisions WHERE inquiry_id=?", (r["source_id"],)
            ).fetchone()[0]
            db.execute(
                "INSERT OR REPLACE INTO project_unassigned VALUES(?,?,'[]')",
                (r["source_id"], revision),
            )
        db.execute(
            "UPDATE inquiries SET state='in_progress' WHERE id=?",
            (candidates[0]["inquiry_id"],),
        )
        db.execute(
            "UPDATE inquiries SET state='waiting_external' WHERE id=?",
            (candidates[1]["inquiry_id"],),
        )
        db.execute(
            "UPDATE drafts SET freshness='stale' WHERE source_id=?",
            (candidates[0]["inquiry_id"],),
        )
    db.close()
    server = output / "server.py"
    server.write_text(
        "import threading,time,uvicorn\nfrom mail_jira_assistant.web import create_app\nfrom mail_jira_assistant.ai import FakeRunner\nfrom mail_jira_assistant.service import worker\n"
        f"runtime={settings.runtime!r}\nkb={settings.knowledge!r}\n"
        "def run():\n    while True:\n        worker(runtime,FakeRunner(),kb)\n        time.sleep(.3)\n"
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
                urllib.request.urlopen(base, timeout=1).close()
                break
            except OSError:
                time.sleep(0.1)
        errors, external, checks = [], [], []
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="msedge", headless=True)
            page = browser.new_page(locale="ko-KR", reduced_motion="reduce")
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on(
                "request",
                lambda r: (
                    external.append(r.url) if not r.url.startswith(base) else None
                ),
            )
            routes = [
                ("inbox", "/"),
                ("review-filter", "/?state=needs_review"),
                ("stale-filter", "/?view=drafts&freshness=stale"),
                ("connections", "/projects"),
            ]
            for width in (320, 390, 768, 1024, 1440):
                page.set_viewport_size({"width": width, "height": 1000})
                for name, route in routes:
                    assert page.goto(base + route).status == 200
                    if name == "connections":
                        page.locator(".candidate-link > summary").first.click()
                    assert page.evaluate(
                        "document.documentElement.scrollWidth<=innerWidth"
                    ), (name, width)
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
            for label, expected in (
                ("확인할 문의", "needs_review"),
                ("진행 중", "in_progress"),
                ("회신 대기", "waiting_external"),
            ):
                page.goto(base)
                link = page.locator(".stats a").filter(has_text=label)
                count = int(link.locator("strong").inner_text())
                link.click()
                assert page.locator("select[name=state]").input_value() == expected
                assert page.locator(".inquiry-table tbody tr").count() == count
                assert page.locator(".stats a[aria-current=true]").count() == 1
            page.locator(".stats a").filter(has_text="재검토할 초안").click()
            assert page.locator("[name=freshness]").input_value() == "stale"
            assert page.locator(".inquiry-table tbody tr").count() >= 1
            page.get_by_label("문의 검색").fill("WT65")
            page.get_by_role("button", name="검색", exact=True).click()
            assert page.locator("[name=freshness]").input_value() == "stale"
            page.goto(base)
            contrasts = page.locator(
                ".source-badge--jira,.source-badge--inbound"
            ).evaluate_all(
                """es=>es.map(e=>{const s=getComputedStyle(e),lum=c=>{const v=c.match(/[\\d.]+/g).slice(0,3).map(x=>{x=+x/255;return x<=.04045?x/12.92:((x+.055)/1.055)**2.4});return .2126*v[0]+.7152*v[1]+.0722*v[2]};const a=lum(s.color),b=lum(s.backgroundColor);return {label:e.textContent,background:s.backgroundColor,ratio:(Math.max(a,b)+.05)/(Math.min(a,b)+.05)}})"""
            )
            assert all(c["ratio"] >= 4.5 for c in contrasts)
            assert len({c["background"] for c in contrasts}) == 2
            page.keyboard.press("Tab")
            assert page.locator(":focus").inner_text() == "본문으로 건너뛰기"
            page.goto(base + "/projects")
            articles = page.locator(".project-candidate")
            assert articles.count() == 2
            assert all("[]" not in text for text in articles.all_text_contents())
            assert not page.get_by_text("기존 프로젝트 찾기", exact=True).count()
            articles.first.locator(".candidate-evidence > summary").click()
            assert articles.first.locator("blockquote").is_visible()
            articles.first.locator(".candidate-link > summary").click()
            form = articles.first.locator("form[data-project-api]")
            form.get_by_label("연결할 프로젝트").select_option(str(pid))
            form.get_by_role("button", name="선택한 프로젝트에 연결").click()
            page.wait_for_url(f"**/projects/{pid}?view=review")
            page.locator("#toast").filter(
                has_text="선택한 프로젝트에 연결했습니다."
            ).wait_for()
            page.goto(base + "/projects")
            assert page.locator(".project-candidate").count() == 1
            page.locator(".project-candidate .candidate-link > summary").click()
            form = page.locator(".project-candidate form[data-project-api]")
            form.get_by_label("연결할 프로젝트").select_option(str(pid))
            form.locator("[name=revision]").evaluate("e=>e.value='1'")
            form.get_by_role("button", name="선택한 프로젝트에 연결").click()
            form.get_by_text(
                "새 원문이 도착했습니다. 새로고침 후 연결하세요.", exact=True
            ).wait_for()
            assert form.get_by_role("button").is_enabled()
            page.screenshot(path=str(output / "connection-error.png"), full_page=True)
            page.get_by_role(
                "button", name="프로젝트 관리 대상 아님", exact=True
            ).click()
            page.wait_for_load_state("networkidle")
            page.get_by_text("프로젝트 연결 검토 · 0건", exact=True).wait_for()
            assert not errors and not external, (errors, external)
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
            external_requests=external,
            source_contrasts=contrasts,
            legacy_nonwork_rows=len(legacy),
            eligible_rows=2,
            flows=[
                "summary filters",
                "stale search persistence",
                "source badges",
                "keyboard",
                "candidate reasons/evidence",
                "explicit project connection",
                "stale revision error",
                "dismiss/empty state",
            ],
            url=base,
            server_pid=process.pid,
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
