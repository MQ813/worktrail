"""Synthetic-only project AI evaluation. Real inference requires --live."""

import argparse
import json
import time
from pathlib import Path

from mail_jira_assistant.ai import FakeRunner, OpenCodeRunner
from mail_jira_assistant.contracts import (
    Request,
    validate_evidence,
    validate_project_update,
)
from mail_jira_assistant.settings import load

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--config")
parser.add_argument("--live", action="store_true")
parser.add_argument("--output", default="runtime/project-model-evaluation.json")
args = parser.parse_args()
settings = load(args.config)
runner = (
    OpenCodeRunner(
        settings.ai_executable,
        settings.project_update_model or settings.classify_model,
        settings.ai_timeout,
        settings.ai_agent,
        prefix=settings.ai_prefix,
        global_args=settings.ai_global_args,
        input_mode=settings.ai_input,
    )
    if args.live
    else FakeRunner()
)
project = dict(
    id=1,
    code="JOB-006",
    name="SmartIO Maintenance",
    purpose="SmartIO 유지보수",
    version=1,
    owner="",
    state="active",
    started_on="",
    entries=[],
    work_items=[],
    pending=[],
)
cases = [
    (
        "decision_only",
        "결정: SmartIO 수정안 A로 진행하기로 합의했습니다. 참고용 공유이며 회신은 필요하지 않습니다.",
        "decision",
    ),
    (
        "todo_and_reply",
        "SmartIO 파형을 검증하고 2026-11-20까지 결과를 회신해주세요.",
        "todo",
    ),
    ("no_change", "감사합니다. 추가 업무나 결정 변경은 없습니다.", None),
]
results = []
for name, body, expected_kind in cases:
    start = time.monotonic()
    result = {"case": name}
    try:
        request = Request(
            source_ref=name,
            subject="JOB-006 SmartIO",
            body=body,
            direction="inbound",
            identity=["engineer@example.test"],
            projects=[project],
        )
        c = runner.classify(request)
        validate_evidence(c, request)
        u = runner.project_update(request)
        validate_project_update(u, request)
        checks = {
            "expected_change": any(change.kind == expected_kind for change in u.changes)
            if expected_kind
            else u.no_change
        }
        if args.live:
            checks["classify_update"] = c.project_update_needed == (
                "yes" if expected_kind else "no"
            )
            if name == "decision_only":
                checks["no_reply"] = c.response_expected == "no"
        result.update(
            classification=c.model_dump(),
            update=u.model_dump(),
            checks=checks,
            passed=all(checks.values()),
        )
    except Exception as exc:
        result.update(error=str(exc), passed=False)
    result["seconds"] = round(time.monotonic() - start, 2)
    results.append(result)
    print(name, result["passed"], flush=True)
output = Path(args.output)
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(
    json.dumps({"live": args.live, "results": results}, ensure_ascii=False, indent=2),
    encoding="utf-8",
)
raise SystemExit(0 if all(r["passed"] for r in results) else 1)
