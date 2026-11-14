# WorkTrail UI 개선 · 2026-11-14

Taste Skill과 UI UX Pro Max를 검토해 업무 앱에 맞는 시각 체계·탐색·폼·접근성 기준을 적용했습니다. [검토와 적용 범위](docs/ui-design-review.md), [디자인 기준](design-system/worktrail/MASTER.md)을 확인하세요.

새 Windows 실행 파일: `dist/ui-refresh/WorkTrail/WorkTrail.exe`. 기존 앱에서 편집 내용을 저장하고 종료한 뒤 실행하세요. 브라우저 42개 화면/너비 조합, 기능 테스트 60개, 실제 Windows WebView2 실행·재기동 검증을 통과했습니다.

# WorkTrail 0.3.3

새 초안 요청은 앱 내부에서 자동 처리됩니다. 개발용 worker 실행 안내를 제거하고 최근 생성 상태와 결과 새로고침 링크를 표시합니다. 기존 창의 편집 내용을 저장하고 새 버전을 실행하세요.

# WorkTrail 0.3.2

Windows native OpenCode/OpenAI 연결과 합성 메일·JIRA의 실제 모델 분류 7건 및 초안 6건이 검증됐습니다. 근거 검증을 유지한 prompt v3 보완을 포함합니다. 최신 검증은 [진행 기록](docs/progress.md)을 확인하세요.

# WorkTrail 0.3.1 · Windows OpenCode와 요청 샘플

Windows용 OpenCode 2.3.0과 연결해 실행할 수 있으며, 요청한 광고·참조·자동 알림·단순 답변·추가 업무·JIRA 알림의 합성 메일 14개와 JIRA 전체 이슈 3개를 제공합니다. [샘플별 확인 방법과 native 설정](docs/native-and-samples.md)을 확인하세요. 실제 계정 인증/모델 호출 결과는 최신 진행 기록을 기준으로 확인합니다. 샘플은 이미 수행한 업무가 아니므로 확정 업무일지 0건이 정상입니다.

# WorkTrail 0.3 · Windows 앱과 업무일지 통합

2026-11-14 기준 참조 구현의 45개 테스트를 WSL에서 확인한 뒤 Windows로 확장했습니다. 기존 수집·분류·답변 초안·원본·편집본·DB 구조를 유지합니다. Windows 앱 실행은 아래 명령을 사용하세요.

```powershell
.\dist\WorkTrail\WorkTrail.exe
# 합성 demo는 별도 데이터 폴더에서 실행
.\dist\WorkTrail\WorkTrail.exe --data-dir "$env:LOCALAPPDATA\WorkTrail-Demo" --demo
```

기본 데이터: `%LOCALAPPDATA%\WorkTrail`. Windows 10/11 x64, WebView2 Runtime, .NET Framework 4.8이 필요합니다. 배포 폴더 전체를 복사하세요. 실행 파일은 Python을 포함하며 OpenCode·Office·DRM 프로그램은 외부 의존성입니다.

오늘 / 문의함 / 답변 초안 / 업무일지 / 프로젝트 화면을 제공합니다. 공통 분류의 수행 제안을 확인한 뒤 실제 수행일을 입력해 확정합니다. 수동 기록, 할 일 완료 연결, 중복 대표 기록 지정, 편집 이력, 날짜별 Markdown 내보내기, 명시한 기존 Markdown 파일 가져오기를 지원합니다. 재분류·초안 재생성은 사용자 편집본을 보존합니다.

소스 실행·Windows 빌드·설정·WSL OpenCode runner·COM adapter·백업/복구는 [Windows 운영 안내](docs/windows-worktrail.md), 최신 결과와 현장 미검증 항목은 [진행 기록](docs/progress.md)을 확인하세요. 실제 사내 DRM·JIRA·권한 프로그램은 집에서 검증하지 않았습니다. 메일 발송과 JIRA 쓰기는 제공하지 않습니다.

---

아래는 재사용한 0.2 WSL 구현의 실행·검증 기록입니다. `.venv/bin`, Linux wheelhouse, systemd 절차는 Windows 실행에 적용하지 않습니다.

# 메일·JIRA 문의 워크스페이스

받은·보낸 EML과 JIRA를 수집하고, 대화·할 일·답변 초안을 브라우저에서 검토하는 **개인용 로컬 시스템**입니다. P2~P5 구현과 P6 사내 이식 준비를 제공합니다. 메일 발송·JIRA 댓글 게시·상태 변경 기능은 없습니다.

## 시작하기

Python 3.11 이상. 현재 검증 환경은 Linux/WSL의 CPython 3.14.4입니다.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-test.lock
.venv/bin/python -m pip install -e . --no-deps
.venv/bin/mail-jira doctor
.venv/bin/mail-jira demo
.venv/bin/mail-jira serve
```

브라우저에서 http://127.0.0.1:8000 을 엽니다. demo는 패키지에 포함한 합성 EML·JIRA·Markdown과 FakeRunner만 사용합니다. 설치된 wheel에서도 실행되며, 인터넷·모델 로그인·CDN이 필요 없습니다. FakeRunner는 저장·검토 흐름을 확인하는 합성 응답이며 실제 분류 정확도를 뜻하지 않습니다.

문의함에서 제목·상대방·본문을 검색하고 상태·출처·서버/프로젝트·할 일/실패·수집 날짜로 필터링합니다. 상세에서 대화, CID 이미지, 첨부 텍스트, 수행 제안, 분류 보정, 업무 상태를 확인합니다. 초안을 수정·복사·검토·보류하거나 재생성 후보를 비교할 수 있습니다. 생성본·편집 이력을 보존하며 새 원문·근거 변경 시 재검토가 표시됩니다. **검토 완료는 실제 답변이나 업무 완료가 아닙니다.**

## 수집과 작업 실행

```sh
# 경로는 TOML 파일 위치를 기준으로 해석합니다. CLI 경로는 현재 디렉터리 기준입니다.
.venv/bin/mail-jira --config config/demo.toml sync
.venv/bin/mail-jira --config config/demo.toml poll --once
.venv/bin/mail-jira --config config/demo.toml poll --once --activate
.venv/bin/mail-jira --config config/demo.toml worker
.venv/bin/mail-jira --config config/demo.toml serve
```

- `sync`는 수집만 수행합니다. `poll` 기본값은 history-only이며 최초 이력을 baseline으로 저장합니다.
- `poll --once --activate`는 baseline 이후 새 변경만 작업으로 등록합니다. 과거 문의는 상세 화면의 **분류 요청**으로 개별 실행합니다.
- `poll`은 `--once`가 없으면 설정 주기로 수집합니다. `worker --watch`는 대기 작업을 지속 실행합니다. 웹 요청은 긴 AI 작업을 직접 실행하지 않습니다.
- 화면에서 요청한 작업은 worker 실행 때 처리됩니다. 운영 상태에서 실패·입력 분량·소요 시간을 보고 재시도할 수 있습니다.
- `automatic_drafts=false`이면 분류만 자동 수행하고 **새 초안 요청**으로 선택한 문의만 작성합니다.
- `poll --once --dry-run --activate`는 파일별 신규/기수집·baseline·예정 작업을 표시하며 DB·커서·로그를 변경하지 않습니다. 원격 JIRA 변경은 네트워크를 조회하지 않아 예측하지 않습니다.

```sh
.venv/bin/mail-jira --config config/corporate.toml jira-add https://jira.company.example/browse/PROJ-123
.venv/bin/mail-jira status
.venv/bin/mail-jira backup runtime-backup-20261114
.venv/bin/mail-jira --runtime restored-runtime restore runtime-backup-20261114
```

백업은 SQLite snapshot API와 원본 blob·체크섬을 함께 저장합니다. 복원은 **존재하지 않는 새 경로**만 허용합니다. 실행 중 DB 파일만 따로 복사하지 마세요. DB는 실행 호스트의 로컬 영속 디스크에 둡니다.

## 실제 모델과 사내 연결

`config/corporate.toml`은 교체할 경로·본인 별칭·JIRA 계정·모델 설정의 예제입니다. 실제 토큰은 `token_env`가 가리키는 환경변수로 전달합니다. JIRA connector는 HTTPS GET만 사용하고 인증정보를 다른 origin이나 redirect로 보내지 않습니다. 기본 구현은 API v2/v3와 Bearer 인증이며 사내 특수 인증/응답은 connector 경계에서 조정합니다.

실제 AI 호출은 다음 명시적 opt-in 명령에서만 일어납니다. 기존 OpenCode 설치·로그인은 변경하지 않습니다.

```sh
.venv/bin/mail-jira live-smoke --model provider/model
.venv/bin/mail-jira --config config/corporate.toml worker --live --watch
.venv/bin/python scripts/evaluate.py --live --model provider/model --output runtime/corporate-evaluation.json
```

OpenCode의 분류/초안 모델·agent·timeout·입력 제한을 설정할 수 있습니다. 독립 임시 디렉터리·도구 거부·세션 비재사용·출력 제한·프로세스 그룹 timeout과 로그의 secret 정제를 적용합니다. 실제 OpenCode 이벤트·agent/permission 호환성은 opt-in live smoke로 현장에서 확인해야 합니다.

## 검증과 이식 자료

```sh
.venv/bin/python -m pytest -q
.venv/bin/python scripts/evaluate.py
.venv/bin/python scripts/prepare_release.py --output dist/corporate-kit-0.2.0
```

별도 venv의 오프라인 wheel 설치·`pip check`·전체 테스트·패키지 demo도 통과했습니다. 반입 묶음은 `dist/mail-jira-assistant-0.2.0-linux-cp314.tar.gz`이며 `scripts/verify_release.py`로 체크섬을 검증합니다.

현재 자동 테스트 **45개 통과**, 합성 평가 **5/5**, 실제 Chromium에서 저장·검토·재로딩·업무 상태·모바일·외부 요청 없는 자산 로딩을 검증했습니다. 선택적인 `scripts/browser_smoke.py`는 Playwright/Chromium과 폐기 가능한 demo runtime에서 사용합니다.

지원: 텍스트/CSV·PDF 텍스트·DOCX/XLSX/PPTX, 원본/CID 보존, 위치·수식 캐시 구분, 시간/크기 제한과 실패 격리. OCR·이미지/회로 해석·DRM 해독·XLSX 재계산은 지원하지 않고 한계로 표시합니다. 기본 제한은 EML 100MiB, 첨부 20MiB/추출 15초/100개, 문서 텍스트 10만 자입니다.

현재는 localhost·한 호스트·개인 사용자·단일 AI worker용입니다. 사내 실제 EML/DRM·JIRA 인증/API·모델·대상 OS와 Python·예약 실행·GEK는 아직 검증하지 않았습니다. Linux CPython 3.14용 wheelhouse를 다른 OS/Python에 그대로 적용하지 마세요. [사내 이식 절차](docs/corporate-porting.md), [진행 기록](docs/progress.md), [검증 범위](docs/evaluation.md), [계약](docs/contracts.md)을 확인하세요.
