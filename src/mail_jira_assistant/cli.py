import argparse
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from .ai import FakeRunner, OpenCodeRunner
from .contracts import Request, validate_evidence
from .service import enqueue, poll, sync, worker
from .settings import load


def main():
    p = argparse.ArgumentParser(description="로컬 메일·JIRA 문의 도우미")
    p.add_argument("--config")
    p.add_argument("--runtime")
    p.add_argument("--inbox")
    p.add_argument("--sent")
    p.add_argument("--kb")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor")
    sub.add_parser("sync")
    poll_cli = sub.add_parser("poll")
    poll_cli.add_argument("--once", action="store_true")
    poll_cli.add_argument("--activate", action="store_true")
    poll_cli.add_argument("--dry-run", action="store_true")
    w = sub.add_parser("worker")
    w.add_argument("--live", action="store_true")
    w.add_argument("--model")
    w.add_argument("--watch", action="store_true")
    serve = sub.add_parser("serve")
    serve.add_argument("--port", type=int, default=8000)
    sub.add_parser("demo")
    smoke = sub.add_parser("live-smoke")
    smoke.add_argument("--model")
    b = sub.add_parser("backup")
    b.add_argument("destination")
    r = sub.add_parser("restore")
    r.add_argument("source")
    j = sub.add_parser("jira-add")
    j.add_argument("url")
    sub.add_parser("status")
    a = p.parse_args()
    s = load(a.config)
    for arg, key in [
        ("runtime", "runtime"),
        ("inbox", "inbox"),
        ("sent", "sent"),
        ("kb", "knowledge"),
    ]:
        if getattr(a, arg):
            setattr(s, key, getattr(a, arg))
    if a.command == "doctor":
        exe = shutil.which(s.ai_executable)
        parent = Path(s.runtime).resolve()
        while not parent.exists():
            parent = parent.parent
        version = (
            subprocess.run(
                [exe, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            ).stdout.strip()
            if exe
            else None
        )
        print(
            json.dumps(
                dict(
                    profile=s.profile,
                    python=os.sys.version,
                    inbox=Path(s.inbox).is_dir(),
                    sent=not s.sent or Path(s.sent).is_dir(),
                    knowledge=Path(s.knowledge).is_dir(),
                    runtime_parent_writable=os.access(parent, os.W_OK),
                    opencode=exe,
                    version=version,
                    credentials=[
                        {
                            "server_id": x["server_id"],
                            "present": bool(os.environ.get(x.get("token_env", ""))),
                        }
                        for x in s.jira_servers
                        if not x.get("fixture")
                    ],
                    corporate_verification="현장 확인 필요",
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    if a.command == "live-smoke":
        req = Request(
            source_ref="synthetic-smoke",
            subject="합성 문의",
            body="측정 온도 확인 후 회신 부탁드립니다.",
        )
        result = OpenCodeRunner(
            s.ai_executable,
            a.model or s.classify_model,
            s.ai_timeout,
            s.ai_agent,
            prefix=s.ai_prefix,
            global_args=s.ai_global_args,
            input_mode=s.ai_input,
        ).classify(req)
        validate_evidence(result, req)
        print(result.model_dump_json())
        return
    if a.command in ("backup", "restore"):
        from .operations import backup, restore

        print(
            backup(s.runtime, a.destination)
            if a.command == "backup"
            else restore(a.source, s.runtime)
        )
        return
    if a.command == "jira-add":
        from .jira import register

        print(register(s.runtime, a.url, s.jira_servers))
        return
    if a.command == "status":
        from .storage import connect

        db = connect(s.runtime)
        print(
            json.dumps(
                dict(
                    jobs=[
                        dict(r)
                        for r in db.execute(
                            "SELECT state,count(*) AS count FROM jobs GROUP BY state"
                        )
                    ],
                    sources=db.execute("SELECT count(*) FROM sources").fetchone()[0],
                    errors=db.execute("SELECT count(*) FROM sync_errors").fetchone()[0],
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
        db.close()
        return
    kwargs = dict(
        sent=s.sent,
        identity=s.identity,
        jira_servers=s.jira_servers,
        stable_seconds=s.stable_seconds,
        document_adapter=s.document_adapter,
        document_timeout=s.document_timeout,
        attachment_adapter=s.attachment_adapter,
    )
    if a.command == "poll":
        if a.dry_run:
            from .service import preview

            print(
                json.dumps(
                    preview(
                        s.runtime,
                        s.inbox,
                        sent=s.sent,
                        activate=a.activate or not s.history_only,
                    ),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return
        try:
            while True:
                print(
                    "수집:",
                    poll(
                        s.runtime,
                        s.inbox,
                        activate=a.activate or not s.history_only,
                        **kwargs,
                    ),
                    flush=True,
                )
                if a.once:
                    break
                time.sleep(s.poll_seconds)
        except KeyboardInterrupt:
            pass
        return
    if a.command in ("sync", "demo"):
        print("수집:", sync(s.runtime, s.inbox, **kwargs))
        if a.command == "sync" and s.jira_servers:
            from .jira import sync_jira

            print("JIRA:", sync_jira(s.runtime, s.jira_servers))
        if a.command == "demo":
            from .jira import register, sync_jira

            demo_fixture = Path(__file__).resolve().parent / "demo/jira/gpio.json"
            if demo_fixture.exists():
                servers = [
                    dict(
                        server_id="demo",
                        base_url="https://jira.example.test",
                        fixture=str(demo_fixture),
                        poll_seconds=0,
                    )
                ]
                register(
                    s.runtime, "https://jira.example.test/browse/DEMO-101", servers
                )
                sync_jira(s.runtime, servers)
            enqueue(s.runtime)
    if a.command in ("worker", "demo"):
        live = getattr(a, "live", False)
        if s.ai_backend == "opencode" and not live:
            p.error("실제 모델 실행은 worker --live로 명시해야 합니다.")

        class StageRunner:
            last_log = {}

            def classify(self, request):
                runner = OpenCodeRunner(
                    s.ai_executable,
                    a.model or s.classify_model,
                    s.ai_timeout,
                    s.ai_agent,
                    prefix=s.ai_prefix,
                    global_args=s.ai_global_args,
                    input_mode=s.ai_input,
                )
                try:
                    return runner.classify(request)
                finally:
                    self.last_log = runner.last_log

            def draft(self, request):
                runner = OpenCodeRunner(
                    s.ai_executable,
                    a.model or s.draft_model,
                    s.ai_timeout,
                    s.ai_agent,
                    prefix=s.ai_prefix,
                    global_args=s.ai_global_args,
                    input_mode=s.ai_input,
                )
                try:
                    return runner.draft(request)
                finally:
                    self.last_log = runner.last_log

            def project_command(self, request):
                runner = OpenCodeRunner(
                    s.ai_executable,
                    a.model or s.project_update_model or s.draft_model,
                    s.ai_timeout,
                    s.ai_agent,
                    prefix=s.ai_prefix,
                    global_args=s.ai_global_args,
                    input_mode=s.ai_input,
                )
                try:
                    return runner.project_command(request)
                finally:
                    self.last_log = runner.last_log

            def project_update(self, request):
                runner = OpenCodeRunner(
                    s.ai_executable,
                    a.model or s.project_update_model or s.draft_model,
                    s.ai_timeout,
                    s.ai_agent,
                    prefix=s.ai_prefix,
                    global_args=s.ai_global_args,
                    input_mode=s.ai_input,
                )
                try:
                    return runner.project_update(request)
                finally:
                    self.last_log = runner.last_log

        runner = StageRunner() if live else FakeRunner()
        try:
            while True:
                print(
                    "작업 완료:",
                    worker(
                        s.runtime,
                        runner,
                        s.knowledge,
                        s.max_chars,
                        lease_seconds=s.lease_seconds,
                        retry_delay=s.retry_delay,
                        automatic_drafts=s.automatic_drafts,
                        automatic_project_updates=s.automatic_project_updates,
                    ),
                    flush=True,
                )
                if not getattr(a, "watch", False):
                    break
                time.sleep(2)
        except KeyboardInterrupt:
            pass
    if a.command == "serve":
        import uvicorn

        from .web import create_app

        uvicorn.run(
            create_app(s.runtime, s.knowledge, s.jira_servers),
            host="127.0.0.1",
            port=a.port,
        )


if __name__ == "__main__":
    main()
