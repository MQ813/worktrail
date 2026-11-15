"""Build isolated, reproducible sample projects through the production command queue."""

import argparse
import json
import time
import uuid
from email.message import EmailMessage
from pathlib import Path

from fastapi.testclient import TestClient

from mail_jira_assistant.ai import FakeRunner, OpenCodeRunner
from mail_jira_assistant.project_ai import CommandResult
from mail_jira_assistant.service import sync, worker
from mail_jira_assistant.settings import load
from mail_jira_assistant.storage import connect
from mail_jira_assistant.web import create_app

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--config", type=Path)
parser.add_argument("--live", action="store_true")
args = parser.parse_args()
root = args.output.resolve()
if root.exists():
    raise ValueError("Use a new isolated output directory")
root.mkdir(parents=True)
runtime = root / "runtime"
inbox = root / "inbox"
inbox.mkdir()
kb = root / "knowledge"
kb.mkdir()
(root / "settings.toml").write_text(
    'profile="demo"\nai_backend="fake"\nhistory_only=true\nsample_mode=true\ninbox="inbox"\nknowledge="knowledge"\nautomatic_drafts=false\n',
    encoding="utf-8",
)
mail = EmailMessage()
mail["From"] = "customer@example.test"
mail["To"] = "engineer@example.test"
mail["Message-ID"] = "<atlas-library-sample@example.test>"
mail["Subject"] = "[합성 샘플] 28nm Atlas GPIO library 개발 요청"
mail.set_content(
    "28nm 공정 Atlas GPIO library 개발을 요청합니다. 산출물은 검증된 GPIO library와 검증 보고서입니다. 목표 일정은 2027-03-31입니다. Spec: 전원 1.8V, 온도 -40~125도. 담당자는 미정입니다. 검증 시뮬레이션 일정과 전달 필요 일정은 아직 정하지 않았습니다. 회신 초안 작성과 별도로 프로젝트로 관리해 주세요."
)
(inbox / "atlas.eml").write_bytes(mail.as_bytes())
sync(runtime, inbox, history_only=False)
db = connect(runtime)
iid = db.execute("SELECT id FROM inquiries").fetchone()[0]
with db:
    db.execute("DELETE FROM jobs")
    db.execute(
        "INSERT OR REPLACE INTO project_unassigned VALUES(?,?,?)",
        (iid, db.execute("SELECT max(id) FROM revisions").fetchone()[0], "[]"),
    )
    db.execute(
        "INSERT OR REPLACE INTO meta VALUES('ai_connection_status','합성 샘플 데이터 · 일부 프로젝트는 실제 OpenCode로 생성')"
    )
db.close()
client = TestClient(create_app(runtime, kb, sample_mode=True))
results = []


def generate(
    text,
    name,
    sections=None,
    confirm=False,
    live=False,
    project_id=None,
    needs_input=False,
):
    key = uuid.uuid4().hex
    data = dict(
        text=text,
        mode="update" if project_id else "create",
        project_id=project_id,
        inquiry_ids=[iid] if live and not project_id else [],
        request_key=key,
    )
    response = client.post("/api/project-ai", json=data)
    assert response.status_code == 200, response.text

    class FixtureRunner(FakeRunner):
        def project_command(self, request):
            if needs_input:
                return CommandResult(
                    question="동일 공정의 개발 대상과 목표 산출물을 지정해 주세요."
                )
            changes = []
            for title, section, content in sections or [("", "overview", text)]:
                changes.append(
                    dict(
                        project_id=project_id or 0,
                        section=section,
                        kind="issue",
                        work_title=title,
                        detail=bool(title),
                        text=content,
                        evidence=[dict(source_ref="user", text=text)],
                    )
                )
            before_text = {}
            if project_id and changes:
                original = request.projects[0]["entries"][0]
                changes[0].update(
                    operation="update",
                    entry_id=original["id"],
                    section=original["section"],
                )
                before_text[str(original["id"])] = original["text"]
            return CommandResult(
                outcome="update" if project_id else "create",
                project_id=project_id,
                name=name,
                metadata={"target_on": "2027-02-24"}
                if project_id
                else {"purpose": text, "target_on": "TBD", "spec": "TBD"},
                changes=changes,
                before_text=before_text,
            )

    if live and args.live:
        settings = load(args.config)
        runner = OpenCodeRunner(
            settings.ai_executable,
            settings.project_update_model or settings.draft_model,
            settings.ai_timeout,
            settings.ai_agent,
            prefix=settings.ai_prefix,
            global_args=settings.ai_global_args,
            input_mode=settings.ai_input,
        )
    else:
        runner = FixtureRunner()
    worker(runtime, runner, kb, max_chars=24000)
    status = client.get("/api/project-ai/" + key).json()
    if needs_input:
        assert status["state"] == "needs_input", status
    else:
        assert status["state"] == "applied", status
    if confirm:
        db = connect(runtime)
        hid = db.execute(
            "SELECT max(id) FROM project_ai_history WHERE project_id=?",
            (status["project_id"],),
        ).fetchone()[0]
        db.close()
        assert (
            client.post(f"/api/project-ai/history/{hid}/confirm", json={}).status_code
            == 200
        )
    results.append(dict(name=name, key=key, live=bool(live and args.live), **status))
    return status["project_id"]


generate(
    "문의 연결 없이 14nm 공정의 SRAM 타이밍 검증 보고서를 작성하는 독립 프로젝트. 전달 일정과 상세 spec은 TBD.",
    "[샘플] 독립 SRAM 타이밍 검증",
)
atlas_pid = generate(
    "선택한 문의로 신규 프로젝트를 만들어줘. 공정·개발 대상·목표 일정·spec과 미정 정보를 구분해 기록해줘.",
    "[샘플] 문의 연결 Atlas GPIO",
    live=True,
)
if args.live:
    generate(
        "Atlas GPIO library 프로젝트의 목표 일정을 2027-03-31에서 2027-04-15로 변경해줘. 나머지 spec과 산출물은 유지해.",
        "Atlas GPIO 실제 OpenCode 일정 변경",
        live=True,
        project_id=atlas_pid,
    )
generate(
    "65nm Orion ADC 검증. 하위 이슈: PVT 시뮬레이션, 노이즈 분석, 결과 보고서. 각 이슈별 진행을 추적한다. 일정과 상세 spec은 TBD.",
    "[샘플] 하위 이슈 Orion ADC",
    sections=[
        ("PVT 시뮬레이션", "next_actions", "PVT 시뮬레이션 준비 · 일정 TBD"),
        ("노이즈 분석", "issues", "노이즈 분석 조건 확인 필요"),
        ("결과 보고서", "progress", "검증 보고서 작성 준비"),
    ],
)
generate(
    "40nm 공정 Delta SPI library의 인터페이스 명세를 정리한다. 목표일과 미정 spec은 TBD.",
    "[샘플] 내용 확인 완료 Delta SPI",
    confirm=True,
)
pid = generate(
    "90nm Vega PLL 평가. 목표 산출물은 평가 보고서. 평가 일정은 2027-02-10.",
    "[샘플] 일정 변경 Vega PLL",
    confirm=True,
)
generate(
    "Vega PLL 평가 일정이 2027-02-10에서 2027-02-24로 변경됨. 기존 평가 일정은 변경 이력으로 보존.",
    "[샘플] 일정 변경 Vega PLL",
    project_id=pid,
    sections=[("평가 일정", "updates", "일정 변경: 2027-02-10 → 2027-02-24")],
)
generate(
    "같은 공정 프로젝트 중 관련된 것에 업데이트해줘. 대상은 확인 필요.",
    "[샘플] 대상 선택 필요",
    needs_input=True,
)
(root / "sample-manifest.json").write_text(
    json.dumps(
        {"created": time.time(), "synthetic": True, "projects": results},
        ensure_ascii=False,
        indent=2,
    ),
    encoding="utf-8",
)
print(root)
