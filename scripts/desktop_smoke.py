"""Opt-in actual Windows EXE smoke in an isolated directory, never production data."""

import argparse
import json
import os
import signal
import sqlite3
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


def wait_report(root):
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if (root / "smoke.json").exists():
            return json.loads((root / "smoke.json").read_text(encoding="utf-8"))
        time.sleep(0.1)
    raise TimeoutError("WebView2 smoke report not created")


def request(base, path, data=None):
    req = urllib.request.Request(
        base + path,
        data=json.dumps(data).encode("utf-8") if data is not None else None,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=5) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--exe", type=Path, default=Path("dist/WorkTrail/WorkTrail.exe")
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--projects", action="store_true")
    args = parser.parse_args()
    root = args.output.resolve()
    if root.exists():
        raise ValueError("Use a new isolated output directory")
    executable = args.exe.resolve()

    def launch(seconds):
        return subprocess.Popen(
            [
                str(executable),
                "--data-dir",
                str(root),
                "--demo",
                "--smoke-seconds",
                str(seconds),
            ]
        )

    process = launch(25 if args.projects else 12)
    try:
        report = wait_report(root)
        assert report["title"] == "WorkTrail"
        assert len(report["pages"]) == 4
        for route, body in report["pages"].items():
            assert "WorkTrail" in body, (route, body)
            assert "Internal Server Error" not in body
        base = f"http://127.0.0.1:{report['port']}"
        duplicate = launch(1)
        duplicate.wait(timeout=15)
        assert (root / "duplicate.json").exists()
        iid = request(base, "/api/inquiries")[0]["id"]
        if args.projects:
            assert (
                "/api/projects/{pid}/replay-history"
                in request(base, "/openapi.json")["paths"]
            )
            linked = request(
                base,
                "/api/projects/link",
                {"inquiry_id": iid, "project": "프로젝트 배포 검증"},
            )
            with urllib.request.urlopen(
                base + f"/projects/{linked['id']}", timeout=5
            ) as response:
                project_html = response.read().decode("utf-8")
                assert "프로젝트 배포 검증" in project_html
                assert 'class="project-tabs"' in project_html
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                with sqlite3.connect(root / "runtime" / "app.sqlite3") as db:
                    done = db.execute(
                        "SELECT count(*) FROM project_update_runs WHERE inquiry_id=?",
                        (iid,),
                    ).fetchone()[0]
                if done:
                    break
                time.sleep(0.2)
            else:
                raise AssertionError("Frozen project update job did not complete")
            with sqlite3.connect(root / "runtime" / "app.sqlite3") as db:
                version = db.execute(
                    "SELECT version FROM projects WHERE id=?", (linked["id"],)
                ).fetchone()[0]
            issue = request(
                base,
                f"/api/projects/{linked['id']}/work-items",
                dict(version=version, title="CELL_NATIVE 검증", detail=True),
            )
            with urllib.request.urlopen(
                base + issue["redirect"], timeout=5
            ) as response:
                issue_html = response.read().decode("utf-8")
                assert "CELL_NATIVE 검증" in issue_html
                assert "이슈 내용 추가" in issue_html
                assert 'name="work_item_id"' in issue_html
        on = datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()
        saved = request(
            base,
            "/api/activities",
            dict(
                description="배포물 재기동 보존 확인",
                performed_on=on,
                project="배포 검증",
                status="confirmed",
                inquiry_id=iid,
            ),
        )
        os.kill(report["worker_pid"], signal.SIGTERM)
        assert request(base, "/api/activities")[0]["id"] == saved["id"]
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            if "restarting" in (root / "desktop.log").read_text(encoding="utf-8"):
                break
            time.sleep(0.1)
        else:
            raise AssertionError("worker was not supervised")
        process.wait(timeout=30)
        assert process.returncode == 0
        try:
            request(base, "/api/inquiries")
            raise AssertionError("backend remained after desktop exit")
        except urllib.error.URLError:
            pass
        (root / "smoke.json").rename(root / "smoke-first.json")
        process = launch(2)
        second = wait_report(root)
        new_base = f"http://127.0.0.1:{second['port']}"
        restored = request(new_base, "/api/activities")
        assert (
            len(restored) == 1
            and restored[0]["description"] == "배포물 재기동 보존 확인"
        )
        process.wait(timeout=30)
        assert process.returncode == 0
        result = dict(
            passed=True,
            checks=[
                "WebView2 four menus",
                "single instance",
                "worker restart while API responds",
                "backend exit",
                "persistent activity on relaunch",
                *(["project link/page/automatic update"] if args.projects else []),
            ],
            report=str(root / "smoke.json"),
        )
        (root / "verification.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(result, ensure_ascii=True))
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)


if __name__ == "__main__":
    main()
