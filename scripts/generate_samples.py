"""Reproducible synthetic mailbox. Expected outcomes are kept outside AI inputs."""

import json
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path

ROOT = Path(__file__).parents[1] / "src/mail_jira_assistant/samples"
ME = "조민규 <mingyu.cho@worktrail.example>"
OTHER = "김영수 <youngsu.kim@worktrail.example>"
CUSTOMER = "이서연 <seoyeon.lee@customer.example>"
BASE = datetime(2026, 11, 14, 8, 0, tzinfo=timezone(timedelta(hours=9)))
CASES = [
    (
        "ad",
        "(광고) EDA 시뮬레이터 연말 프로모션",
        "안녕하세요. EDA 시뮬레이터 연말 할인 행사 안내입니다. 11월 한정 20% 할인과 제품 소개 웨비나를 제공합니다. 본 메일은 마케팅 수신 동의에 따라 발송되었습니다.",
        ME,
        "",
    ),
    (
        "ad",
        "(광고) 반도체 기술 세미나 무료 등록",
        "반도체 공정과 ESD 설계 동향 세미나에 초대합니다. 무료 등록 이벤트이며 업무 문의나 회신 요청이 아닙니다.",
        ME,
        "",
    ),
    (
        "ad",
        "(광고) 계측 장비 신제품 및 카탈로그",
        "새로운 반도체 파라미터 분석기 카탈로그와 구매 프로모션을 안내합니다. 제품 뉴스레터이며 답변은 필요하지 않습니다.",
        ME,
        "",
    ),
    (
        "cc",
        "[샘플] WT65 라이브러리 면적 자료 확인 요청",
        "수신 : 김영수 님\n\n안녕하세요. WT65 1.8 V GPIO 라이브러리의 셀 면적 표가 지난 배포본과 다른지 확인하고 고객에게 회신해 주시기 바랍니다. 이 요청은 위 수신 담당자에게 드리는 문의입니다.\n필요 자료는 첨부 없이 기존 릴리스 노트를 참조해 주세요.",
        OTHER,
        ME,
    ),
    (
        "cc",
        "[샘플] ESD 검증 보고서 형식 문의",
        "수신 : 박지훈 님\n\n고객 제출용 ESD 보고서에 포함할 시험 조건과 보고서 양식을 확인해 주십시오. 보고서 작성과 답변 담당자는 위 수신인입니다. 나머지 참조자는 진행 공유 대상으로 포함했습니다.",
        "박지훈 <jihoon.park@worktrail.example>",
        ME,
    ),
    (
        "system",
        "[샘플] 설계 포털 계정 권한 만료 예정 알림",
        "이 메일은 권한관리 시스템이 자동 발송한 알림입니다. 설계 포털 계정 권한이 2026-12-31에 만료될 예정입니다. 현재 갱신 신청이나 별도 조치는 필요하지 않습니다. 문의 메일에 대한 회신 대상이 아니며, 본 발신 주소는 수신하지 않습니다.",
        ME,
        "",
    ),
    (
        "system",
        "[샘플] 11월 부서 행사 일정 자동 안내",
        "부서 일정 시스템에서 자동 발송한 안내입니다. 2026-11-26 16:00 부서 기술 공유회가 예정되어 있습니다. 참석 여부 회신이나 준비 과제는 없습니다. 일정 공지 용도로만 전달합니다.",
        ME,
        "",
    ),
    (
        "simple",
        "[샘플] 고객 문의: WT65 GPIO fail-safe 조건",
        "수신 : 조민규 님\n\nWT65 GPIO v1.4의 fail-safe 사용 조건을 확인 부탁드립니다. 고객 조건은 VDDIO=0 V, PAD 입력=1.8 V, 온도=25 C입니다. 신규 simulation은 요청하지 않으며, 기존 승인 가이드에 나온 허용 여부와 적용 조건을 메일로 설명해 주세요.",
        ME,
        "",
    ),
    (
        "image",
        "[샘플] 고객 문의: GPIO 누설 전류 캡처 해석",
        "수신 : 조민규 님\n\nWT65 GPIO의 고온 누설 전류 sweep 결과를 본문 캡처로 보냅니다. 공정 WT65, VDDIO=1.8 V, 온도=125 C 조건입니다. 캡처에서 급격히 변화하는 구간이 어디인지 확인하고 측정 설정을 어떻게 다시 확인해야 하는지 답변 부탁드립니다. 수치와 곡선은 이미지에만 있으므로 캡처를 직접 확인해야 합니다. 새로운 simulation 의뢰는 아닙니다.",
        ME,
        "",
    ),
    (
        "simulation",
        "[샘플] 고객 복수 문의: ESD clamp 설명 및 추가 simulation",
        "수신 : 조민규 님\n\nWT65 ESD clamp v2.1에 대해 세 가지 문의드립니다.\n1. 승인 가이드의 HBM 2 kV 조건과 CDM 500 V 조건 차이를 간단히 설명해 주세요.\n2. TT/SS/FF, -40/25/125 C에서 trigger voltage와 holding current를 추가 simulation해 주세요. VDD=1.8 V이며 입력 pulse rise time은 10 ns입니다.\n3. 2026-11-18 17:00 KST까지 simulation 결과와 검토 의견을 회신할 수 있는지 알려 주세요. 기존 자료 설명 답변과 신규 simulation 수행은 구분해서 관리 부탁드립니다.",
        ME,
        "",
    ),
    (
        "release",
        "[샘플] 고객 복수 문의: GPIO 호환성 답변 및 DB release 요청",
        "수신 : 조민규 님\n\nWT65 GPIO v1.4와 v1.3의 핀 호환 여부를 기존 릴리스 노트 기준으로 회신 부탁드립니다. 또한 누락된 LEF abstract를 포함한 v1.4.1 DB release를 요청합니다. 요청 일정은 2026-11-20 15:00 KST입니다. 릴리스 전 LVS clean 로그와 DB checksum 검증을 수행하고 전달 목록을 작성해 주세요. 이번 메일은 release 요청이며 이미 완료되었다는 뜻은 아닙니다.",
        ME,
        "",
    ),
    (
        "jira",
        "[JIRA] ESD-1234 고객 ESD clamp 시험 조건 문의",
        'ESD-1234 이슈에 새 댓글이 등록되었습니다.\n요약: HBM과 CDM 검증 조건 확인 요청\n일부 내용: "이전 시험 조건과 최신 답변의 차이를 확인..."\n이 알림에는 전체 본문과 이전 댓글이 없습니다. 실제 이슈와 모든 댓글을 확인하세요.\nhttps://jira.worktrail.example/browse/ESD-1234',
        ME,
        "",
    ),
    (
        "jira",
        "[JIRA] ESD-1235 추가 simulation 일정 확인",
        'ESD-1235 이슈가 업데이트되었습니다.\n요약: clamp trigger sweep 요청\n일부 내용: "코너와 온도 조건을 추가했습니다..."\n정확한 수행자, 변경된 조건 및 기한은 실제 이슈의 전체 본문과 댓글에 있습니다.\nhttps://jira.worktrail.example/browse/ESD-1235',
        ME,
        "",
    ),
    (
        "jira",
        "[JIRA] ESD-1236 DB release 진행 공유",
        'ESD-1236 이슈에 상태 변경이 등록되었습니다.\n일부 내용: "릴리스 검증 로그를 업로드..."\n다른 수행자의 변경일 수 있으므로 알림만 보고 내 수행 실적으로 기록하지 마세요. 전체 맥락을 확인하세요.\nhttps://jira.worktrail.example/browse/ESD-1236',
        ME,
        "",
    ),
]


def main():
    for folder in ("inbox", "jira", "knowledge"):
        (ROOT / folder).mkdir(parents=True, exist_ok=True)
    manifest = []
    for i, (kind, subject, body, to, cc) in enumerate(CASES, 1):
        msg = EmailMessage()
        msg["From"] = (
            "JIRA Bot <jira@worktrail.example>"
            if kind == "jira"
            else "Notification <noreply@worktrail.example>"
            if kind == "system"
            else "Marketing <news@vendor.example>"
            if kind == "ad"
            else CUSTOMER
        )
        msg["To"] = to
        if cc:
            msg["Cc"] = cc
        msg["Subject"] = subject
        msg["Date"] = (BASE + timedelta(minutes=i * 7)).strftime(
            "%a, %d %b %Y %H:%M:%S %z"
        )
        msg["Message-ID"] = f"<worktrail-samples-v1-{i:02d}@worktrail.example>"
        if kind in ("system", "jira"):
            msg["Auto-Submitted"] = "auto-generated"
        msg.set_content("[합성 샘플 · 실제 사내 데이터 아님]\n" + body)
        if kind == "image":
            import html

            msg.add_alternative(
                "<html><body><p>"
                + html.escape(body).replace("\n", "<br>")
                + '</p><img src="cid:gpio-capture@worktrail" alt="합성 GPIO sweep 캡처"></body></html>',
                subtype="html",
            )
            msg.get_payload()[-1].add_related(
                (ROOT / "assets/gpio-capture.png").read_bytes(),
                maintype="image",
                subtype="png",
                cid="<gpio-capture@worktrail>",
                filename="gpio-capture.png",
                disposition="inline",
            )
        filename = f"{i:02d}-{kind}.eml"
        (ROOT / "inbox" / filename).write_bytes(msg.as_bytes())
        manifest.append(
            dict(
                file=filename,
                message_id=str(msg["Message-ID"]),
                category=kind,
                subject=subject,
                response_expected="yes"
                if kind in ("simple", "image", "simulation", "release")
                else "no",
                expected_tasks={
                    "simulation": [
                        "코너·온도 simulation",
                        "2026-11-18 17:00 KST 결과 회신",
                    ],
                    "release": ["LVS/checksum 검증", "2026-11-20 15:00 KST DB release"],
                }.get(kind, []),
                needs_image_review=kind == "image",
            )
        )
    issues = {}
    descriptions = [
        (
            "ESD-1234",
            "[샘플] WT65 ESD clamp HBM/CDM 시험 조건 질의",
            "고객은 WT65 clamp v2.1의 HBM 2 kV와 CDM 500 V 검증 조건을 문의했습니다. 담당자는 조민규(mingyu.cho)입니다. 기존 가이드로 설명하면 되며 신규 simulation이나 DB release 요청은 아닙니다.",
            [
                (
                    "customer",
                    "우리는 1.8 V I/O에 clamp v2.1을 사용하고 있습니다. HBM과 CDM 판정 기준 및 fixture 차이를 기존 가이드 기준으로 설명 부탁드립니다.",
                ),
                (
                    "mingyu.cho",
                    "이전 시험 리포트를 확인하겠습니다. 아직 고객에게 답변을 보내지 않았습니다.",
                ),
                (
                    "customer",
                    "중요한 조건을 추가합니다. 고객 시험은 JS-001과 JS-002 순서를 구분하며, 가이드에 없는 판정 수치는 추측하지 말아 주세요.",
                ),
            ],
            "mingyu.cho",
            "Open",
        ),
        (
            "ESD-1235",
            "[샘플] ESD trigger corner/temperature simulation 요청",
            "담당자는 조민규(mingyu.cho)입니다. clamp v2.1, VDD 1.8 V, pulse rise time 10 ns에서 TT/SS/FF 및 -40/25/125 C sweep을 신규 수행해 주세요. 기한은 2026-11-18 17:00 KST입니다. 실행 전 요청 조건을 회신할 필요가 있습니다.",
            [
                (
                    "customer",
                    "기본 trigger voltage뿐 아니라 holding current도 결과표에 넣어 주세요.",
                ),
                (
                    "mingyu.cho",
                    "추가 조건을 확인 중입니다. simulation 실행과 결과 검토는 아직 수행하지 않았습니다.",
                ),
                (
                    "customer",
                    "알림 본문에서 생략된 추가 조건: 동일 코너마다 clamp leakage도 같이 저장하고 netlist 버전을 결과표에 적어 주세요.",
                ),
            ],
            "mingyu.cho",
            "In Progress",
        ),
        (
            "ESD-1236",
            "[샘플] 다른 담당자의 GPIO v1.4.1 DB release 진행 공유",
            "담당자는 박지훈(jihoon.park)이며 조민규(mingyu.cho)는 watcher로만 포함됐습니다. 이 업무에서 조민규에게 별도 답변이나 신규 수행 요청은 없습니다.",
            [
                (
                    "jihoon.park",
                    "2026-11-13에 LVS clean과 checksum 검증을 완료하고 고객 전달 목록을 작성했습니다. 수행자는 박지훈입니다.",
                ),
                (
                    "release.bot",
                    "2026-11-14에 DB package staging이 완료됐습니다. 자동화 시스템의 작업 결과입니다.",
                ),
                (
                    "customer",
                    "11월 20일 release 일정 확인했습니다. 최종 전달은 담당자 박지훈 님에게 요청하겠습니다.",
                ),
            ],
            "jihoon.park",
            "In Review",
        ),
    ]
    for index, (key, summary, description, comments, owner, status) in enumerate(
        descriptions, 1234
    ):
        issues[key] = dict(
            id=str(index),
            key=key,
            fields=dict(
                summary=summary,
                description="[합성 JIRA fixture · 원격 서버 접속 없음]\n" + description,
                status={"name": status},
                assignee={
                    "name": owner,
                    "displayName": "조민규" if owner == "mingyu.cho" else "박지훈",
                },
                updated="2026-11-14T09:00:00+09:00",
                comment={
                    "total": len(comments),
                    "comments": [
                        dict(
                            id=f"{key}-{i}",
                            author={"name": actor},
                            body=body,
                            created=f"2026-11-{12 + i:02d}T09:00:00+09:00",
                        )
                        for i, (actor, body) in enumerate(comments)
                    ],
                },
                attachment=[],
            ),
        )
    (ROOT / "jira/issues.json").write_text(
        json.dumps({"issues": issues}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (ROOT / "knowledge/wt65-approved-synthetic.md").write_text(
        """# 합성 승인 자료: WT65 GPIO 및 ESD clamp
이 문서는 기능 검증용 합성 자료이며 실제 공정/제품의 보증 자료가 아닙니다.

## GPIO v1.4 fail-safe
대상 공정 WT65, GPIO v1.4, 온도 25 C, VDDIO=0 V에서 PAD 입력 0~1.8 V를 적용하는 fail-safe 조건을 지원합니다. 전원 차단 상태에서 PAD 입력이 1.8 V를 초과하는 조건은 이 자료가 승인하지 않습니다. 고객 조건이 이 범위와 일치할 때만 이 조건을 인용하세요.

## GPIO 릴리스 호환성
WT65 GPIO v1.4와 v1.3의 외부 핀 이름과 핀 순서는 동일합니다. LEF abstract와 LVS/checksum은 개별 release package 검증이 필요하며, 이 문서만으로 새 DB가 이미 검증되었다고 단정할 수 없습니다.

## ESD clamp v2.1 HBM/CDM
HBM과 CDM은 서로 다른 ESD 방전 모델과 시험 fixture를 사용합니다. WT65 clamp v2.1의 합성 승인 항목은 HBM 2 kV와 CDM 500 V로 구분합니다. 시험 순서와 판정 세부 수치는 해당 리포트/JS-001/JS-002 원문을 확인해야 하며 여기에는 제공되지 않습니다. 신규 코너 simulation 결과나 trigger/holding 수치는 아직 없습니다.

## 이미지 캡처
메일의 GPIO 누설 전류 캡처 수치와 곡선 변화 구간은 이 문서에 없습니다. 이미지 확인 전 구체적 수치를 만들지 마세요.
""",
        encoding="utf-8",
    )
    (ROOT / "manifest.json").write_text(
        json.dumps(
            {
                "version": 1,
                "identity": ["mingyu.cho@worktrail.example", "조민규"],
                "mail_count": 14,
                "jira_count": 3,
                "cases": manifest,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (ROOT / "README.md").write_text(
        "# WorkTrail 합성 샘플\n\n14개 메일 + 연결 JIRA 3개입니다. manifest.json은 비교용 정답표이며 AI 입력이나 KB에 넣지 않습니다. 이미지 질문은 실제 캡처 해석 지원 전까지 확인 필요 상태가 정상입니다. JIRA URL은 .example이고 로컬 fixture로만 조회합니다.\n",
        encoding="utf-8",
    )
    print("Created 14 EML + 3 JIRA issues; all data synthetic.")


if __name__ == "__main__":
    main()
