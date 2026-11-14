"""Fixed synthetic model comparison. Real inference requires --live explicitly."""

import argparse
import json
import time
from pathlib import Path

from mail_jira_assistant.ai import FakeRunner, OpenCodeRunner
from mail_jira_assistant.contracts import Request, validate_draft, validate_evidence
from mail_jira_assistant.knowledge import knowledge

root = Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser()
p.add_argument("--live", action="store_true")
p.add_argument("--model")
p.add_argument("--output", default="runtime/evaluation.json")
a = p.parse_args()
runner = OpenCodeRunner(model=a.model) if a.live else FakeRunner()
results = []
for scenario in json.loads(
    (root / "tests/fixtures/model-evaluation.json").read_text(encoding="utf-8")
):
    started = time.monotonic()
    result = {"id": scenario["id"], "checks": {}, "error": None}
    try:
        req = Request(
            source_ref=scenario["id"],
            subject=scenario["subject"],
            body=scenario["body"],
            direction=scenario["direction"],
            identity=["engineer@example.test"],
        )
        classification = runner.classify(req)
        validate_evidence(classification, req)
        result["classification"] = classification.model_dump()
        result["checks"] = {
            axis: getattr(classification, axis) == value
            for axis, value in scenario["expected"].items()
        }
        if classification.response_expected == "yes":
            req.knowledge = knowledge(root / "tests/fixtures/kb", req.body)
            if not req.knowledge:
                req.limitations = ["적용 가능한 근거 없음"]
            req.missing_information = classification.missing_information
            draft = runner.draft(req)
            validate_draft(draft, req)
            result["draft"] = draft.model_dump()
            if scenario.get("draft_modes"):
                result["checks"]["safe_answer_mode"] = (
                    draft.answer_mode in scenario["draft_modes"]
                )
            result["checks"]["no_unsupported_number"] = (
                not any(number in draft.body for number in ("10uA", "20uA", "100uA"))
                if scenario["id"] == "S18"
                else True
            )
    except Exception as exc:
        result["error"] = type(exc).__name__ + ": " + str(exc)
    result["duration"] = time.monotonic() - started
    results.append(result)
report = {
    "backend": "opencode" if a.live else "fake",
    "model": a.model,
    "accuracy_claim": False,
    "note": "합성 계약/필수 판단 검사. fake 통과는 실제 모델 정확도가 아닙니다. 근거 적합성/누락/수정 정도는 사람이 검토합니다.",
    "results": results,
}
output = Path(a.output)
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(
    output,
    ":",
    sum(not r["error"] and all(r["checks"].values()) for r in results),
    "/",
    len(results),
)
if any(r["error"] or not all(r["checks"].values()) for r in results):
    raise SystemExit(1)
