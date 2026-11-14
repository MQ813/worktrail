# 0.3.2 최신 확인

OpenAI 연결과 실제 Windows 모델 분류 7건·초안 6건 검증을 완료했습니다. 초기 근거 검증 오류는 prompt v3로 수정하고 이전 이력을 보존했습니다. 새 실행 파일을 사용하세요. 아래 인증 대기는 0.3.1 시점 이력입니다.

# 요청 시나리오 샘플과 Windows native OpenCode (0.3.1)

모든 데이터는 합성입니다. 사내 메일/JIRA에 접속하지 않습니다. 샘플에서 내 역할은 조민규(`mingyu.cho@worktrail.example`), JIRA 계정은 `mingyu.cho`입니다.

| 입력 | 수 | 확인할 동작 |
|---|---:|---|
| `(광고)` 제목 | 3 | 마케팅 헤더가 없어도 광고 규칙으로 답변·할 일 제외 |
| 참조 전용, 본문 `수신 : 다른 이름 님` | 2 | 실제 To 수신인 이름 일치·내가 CC에만 있음 확인 후 제외 |
| 자동 시스템 알림 | 2 | 권한 만료/부서 행사 안내, 회신·준비 요청이 없는 자동 알림 제외 |
| 단순 답변 | 2 | 기존 승인 자료 답변 1, CID PNG 캡처 검토 필요 1 |
| 답변+추가 업무 | 2 | 코너 simulation(11/18 17:00 KST), 검증 및 DB release(11/20 15:00 KST) |
| `[JIRA] ESD-1234~1236` 알림 | 3 | 알림 본문만으로 판단하지 않고 연결 이슈 전체/댓글로 이동 |

EML은 14개입니다. JIRA 이슈 3개를 추가 수집하므로 문의함의 원문 항목은 총 17개입니다. 알림 3개는 중복 답변 대상에서 제외합니다. ESD-1234는 단순 기술 답변, ESD-1235는 신규 simulation, ESD-1236은 다른 담당자/봇의 수행 공유로 구성했습니다. 합성 JIRA 서버 URL `.example`은 로컬 `FixtureJira`로만 조회하며 실제 네트워크 서버가 아닙니다. 이슈별 fixture lookup을 지원해 알림 3개가 각각 다른 전체 컨텍스트에 연결됩니다.

샘플 원본: `src/mail_jira_assistant/samples/inbox`, `jira/issues.json`, `assets/gpio-capture.png`, `knowledge/`. `manifest.json`은 수량/기대 동작 비교용이며 모델 입력/KB에는 넣지 않습니다. 파일명이나 비교용 정답표를 AI의 답변으로 복사하지 않습니다.

## 실행과 재설치

현재 사용자 기본 WorkTrail 데이터 폴더에 샘플을 설치합니다. 설치는 기존 파일을 덮어쓰지 않고 원본 바이트 기반 수집·작업 키로 중복을 방지합니다. 데이터/설정을 변경하기 전에 기존 SQLite snapshot+blob과 settings TOML을 `backup-before-native-*`, `settings-before-native-*.toml`로 보관합니다.

```powershell
# 설치된 native OpenCode를 설정하고 요청 샘플을 적재 (실제 모델 호출 없음)
.\.venv\Scripts\python.exe scripts/configure_native.py
# 실행 중 실제 모델은 명시적으로 선택된 native backend가 담당
.\dist\WorkTrail\WorkTrail.exe
# 다른 데이터 경로에서 새 샘플 흐름 보기
.\dist\WorkTrail\WorkTrail.exe --data-dir "$env:LOCALAPPDATA\WorkTrail-Samples" --samples
```

`--samples`는 샘플 원문과 처리 작업을 등록하며 현재 설정의 runner를 사용합니다. 새 폴더 기본 설정은 FakeRunner이므로 실제 모델 검증이라고 기록하지 않습니다. 실제 native 모드가 필요하면 먼저 그 데이터 폴더에 `configure_native.py --data-dir ...`를 실행하세요.

## Windows OpenCode

공식 `anomalyco/opencode` v2.3.0의 `opencode-windows-x64.zip`을 설치하고 GitHub asset SHA-256을 대조했습니다. 설치 경로는 `%LOCALAPPDATA%\Programs\OpenCode\bin\opencode.exe`이며 사용자 PATH에 추가했습니다. 기존 WSL 설치·인증은 수정하지 않았습니다. WorkTrail 설정은 `ai_prefix=[]`, `ai_global_args=["--standalone"]`, `ai_input="stdin"`과 native `.exe`를 사용합니다. 모델은 `openai/gpt-6.1-sol-fast`를 우선 사용하며 실제 계정 접근과 호출 결과를 별도로 검증합니다.

계정 인증은 사용자가 OpenCode의 공식 브라우저/기기 인증 절차를 직접 완료합니다. 토큰을 settings나 배포물에 넣지 않습니다. 브라우저 자동 열기는 이 개발 세션의 자동 승인 검토에서 `blocked by policy`로 거부돼 수동 기기 인증으로 전환했습니다. `auth export`를 로그에 출력하거나 WSL의 토큰 파일을 복사하지 않습니다.

## 이미지와 수행 기록 경계

CID PNG가 본문과 원본에 보존되고 상세에서 표시됩니다. 현재 텍스트 runner는 이미지 픽셀을 해석하지 않습니다. 캡처 확인이 필요한 질문은 `needs_vision`/partial로 표시하고 구체적 수치를 추측한 확정 답변을 금지합니다. 실제 시각 해석 기능이 완료됐다고 주장하지 않습니다.

새 요청 샘플은 아직 수행한 업무가 아니므로 확정 업무일지는 0건이 정상입니다. 답변 초안/검토도 수행 확정이 아닙니다. simulation/release 작업을 실제로 수행한 뒤 수동 수행 기록과 연결해 확정할 수 있습니다. 다른 담당자의 JIRA 수행을 내 실적으로 집계하면 안 됩니다.

공식 참고: [OpenCode release](https://github.com/anomalyco/opencode/releases/tag/v2.3.0), [OpenCode 계정 연결](https://opencode.ai/docs/providers), [독립 실행](https://opencode.ai/docs/cli).


## 이번 세션 검증 상태

테스트 60개와 실제 EXE 수명/복구 smoke는 통과했습니다. 현재 Windows 계정 연결은 사용자 기기 인증 대기 상태이므로 native 모델 분류/초안 품질 검증은 아직 완료하지 않았습니다. 앱은 계정이 연결될 때까지 작업의 시도 횟수를 소모하지 않고 수집/조회만 유지합니다. 인증 뒤 자동 재개합니다. `Connect-OpenCode.cmd`로 만료된 기기 인증을 새로 시작할 수도 있습니다. 앱의 문의함에서 17개 원문과 규칙분류를 먼저 확인할 수 있습니다.
