# 합성 승인 자료: WT65 GPIO 및 ESD clamp
이 문서는 기능 검증용 합성 자료이며 실제 공정/제품의 보증 자료가 아닙니다.

## GPIO v1.4 fail-safe
대상 공정 WT65, GPIO v1.4, 온도 25 C, VDDIO=0 V에서 PAD 입력 0~1.8 V를 적용하는 fail-safe 조건을 지원합니다. 전원 차단 상태에서 PAD 입력이 1.8 V를 초과하는 조건은 이 자료가 승인하지 않습니다. 고객 조건이 이 범위와 일치할 때만 이 조건을 인용하세요.

## GPIO 릴리스 호환성
WT65 GPIO v1.4와 v1.3의 외부 핀 이름과 핀 순서는 동일합니다. LEF abstract와 LVS/checksum은 개별 release package 검증이 필요하며, 이 문서만으로 새 DB가 이미 검증되었다고 단정할 수 없습니다.

## ESD clamp v2.1 HBM/CDM
HBM과 CDM은 서로 다른 ESD 방전 모델과 시험 fixture를 사용합니다. WT65 clamp v2.1의 합성 승인 항목은 HBM 2 kV와 CDM 500 V로 구분합니다. 시험 순서와 판정 세부 수치는 해당 리포트/JS-001/JS-002 원문을 확인해야 하며 여기에는 제공되지 않습니다. 신규 코너 simulation 결과나 trigger/holding 수치는 아직 없습니다.

## 이미지 캡처
메일의 GPIO 누설 전류 캡처 수치와 곡선 변화 구간은 이 문서에 없습니다. 이미지 확인 전 구체적 수치를 만들지 마세요.
