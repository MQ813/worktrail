# WorkTrail 0.4.1 · 프로젝트 통합·조밀한 업무 화면 (2026-11-14)

업무일지·답변 초안 독립 메뉴를 제거하고 오늘/문의함/프로젝트/운영 상태 4개 메뉴로 통합했다. 수행 기록은 프로젝트 안에서 작성·수행일별 조회·편집·확정하고 프로젝트 선택은 문맥으로 고정한다. 다른 프로젝트 기록을 섞지 않으며 이전 /worklog 링크는 해당 프로젝트로 redirect한다. 미지정 기존 기록을 프로젝트에 연결하고 수정 이력을 보존하는 경로도 추가했다.

공통 상단 경로·반복 제목·설명을 제거하고 AI 연결·합성 환경은 sidebar footer로 옮겼다. 실제 발신자는 문의 제목과 같은 줄, 목록 행은 약 37px, 본문/편집기 행간 1.5로 조정했다. 개요·가져오기 폼과 빈 구역의 공간을 줄였다.

자동 테스트 86개 및 Ruff 통과. 실제 Edge에서 새 화면 12개 + 공통 36개 화면/너비 조합과 프로젝트 안의 수행 기록 저장/재로딩, 초안 저장, 부분 확정·반려를 검증했다. 1440px 화면의 목록 표 시작 180px, 행 높이 36.75px, 본문 행간 1.5를 측정했다. UI 결과는 `runtime/project-review-1794664527313607900/`, 최종 native 검증은 `runtime/compact-native-smoke/verification.json`에 보존한다. 최종 실행 파일은 `dist/WorkTrail-0.4.1/WorkTrail/WorkTrail.exe`다.

---

# WorkTrail 0.4 · 프로젝트 중심 업무일지와 자동 업데이트 (2026-11-14)

공통 classify schema 2에 프로젝트 변경 판단·종류·연결 단서를 추가하고, 답변 draft와 독립적으로 project_update 작업을 등록하도록 확장했다. Windows/CLI runner 및 별도 모델 설정을 연결했다. 기존 규칙분류의 답변 불필요와 업무 변경 없음도 구분한다. 최초 history-only는 유지하고, 프로젝트·수집 기간을 명시한 과거 revision 재구성 경로를 추가했다.

DB v6은 JOB 코드·개요·업무 항목·확정 항목·미확정 변경·근거·검토 이력·가져온 원본을 보존한다. 기존 DB는 migration 전 snapshot을 만든다. 프로젝트 화면에 변경 전후와 AI 미확정 표시, 원문·부분 확정·수정·반려·묶음 검토·재생성을 추가했다. 사람 수정과 오래된 원문/프로젝트 버전을 검증하며 상충 제안은 자동 선택하지 않는다. 수행 실적과 초안 검토는 별도 확정 절차다.

index.md 단독과 issues/assets 폴더, ZIP, 확정본 출력, 기존 JOB 폴더 가져오기, 외부 수정의 원본 보존·추가 후보 가져오기를 제공한다. 사용자 메모와 생성 영역 충돌을 보존하고 백업/복원에도 문서를 포함했다. 실시간 양방향 동기화·자동 3-way 병합·이미지 해석·메일/Jira 쓰기는 추가하지 않았다.

검증: 자동 테스트 83개, Ruff, 새 프로젝트 관련 실제 Edge 12개 화면/너비 조합과 기존 42개 조합, 실제 모델 합성 평가 3/3. 실제 Windows EXE에서 프로젝트 연결·화면·자동 업데이트, 중복 실행·worker 복구·재기동 데이터 보존을 검증했다. 증거 및 재현은 [프로젝트 업무일지 안내](project-worklog.md)를 따른다. 사내 실제 메일/Jira/DRM 정확도와 장기 운영은 현장 미검증이다.

배포: `dist/project-worklog-final/WorkTrail/WorkTrail.exe`. 현재 사용 중인 앱과 기본 사용자 DB는 교체하거나 재시작하지 않았다. 새 버전 실행 전에 편집을 저장하고 기존 앱을 종료한다.

---

# WorkTrail 0.3.3 · 초안 생성 안내 (2026-11-14)

앱에서 새 초안 요청 후 표시되던 개발용 worker 실행 안내를 제거했습니다. 일반 변경과 초안/분류 요청의 완료 안내를 구분하고, 초안 화면에 최근 생성 상태·결과 새로고침·처리 상태 확인 링크를 표시합니다. 기존 편집본 보존과 재생성 비교 후보 동작은 유지합니다. 문의/대화/편집 회귀 14개 통과. 요청 당시 최근 초안 작업 #15가 이미 succeeded임을 확인했습니다. 실행 중인 기존 앱과 편집을 건드리지 않도록 별도 배포 폴더에 빌드합니다.

# WorkTrail 0.3.2 · Windows native 실제 모델 검증 (2026-11-14)

OpenAI 기기 인증 완료를 CLI의 Connected to OpenAI/auth list stored로 확인했습니다. Windows native OpenCode 2.3.0 + openai/gpt-6.1-sol-fast에서 모델 분류 대상 7개와 초안 6개가 모두 성공했습니다. 규칙분류 10개 포함 전체 원문은 17개입니다. 확정 수행 기록은 0개이며 다른 담당자 JIRA 실적을 내 수행으로 집계하지 않았습니다.

초기 초안 4개는 technical_answer와 누락 정보가 동시에 반환돼 insufficient_coverage로 거부됐습니다. prompt version 3에서 기존 검증 계약을 명시하고, 분류 단계의 미적재 KB를 고객 정보 누락으로 판단하지 않도록 보완했습니다. fail-safe 문의 재분류와 실패 초안 재시도를 수행했으며 이전 history/attempt와 사용자 편집을 삭제하지 않았습니다. 검증 기준은 완화하지 않았습니다. 현재 실패 작업 0개, 초안 6개를 확인했습니다. fail-safe는 승인 자료 기반 technical_answer, 이미지 문의는 internal_review이며 이미지 수치를 추측하지 않습니다. simulation/release의 미수행·미확정 조건은 internal_review/clarification_request로 남깁니다.

증거: runtime/native-live-verification.json. 직전 전체 60 tests pass에 더해 prompt 변경 후 runner/flow/sample 회귀 19 tests pass 및 ruff 통과. 실제 모델 결과는 합성 데이터 기준이며 사내 DRM/JIRA/모델 정확도 보증이 아닙니다.

Avast 경고는 IDP.HELU.PSE96 command-line detection, Behavior Shield, C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe, 2026-11-14T00:29:42.445Z로 확인했습니다. 해당 시각 ±약 2분의 Windows PowerShell engine event 400 조회는 기록 없음이었습니다. 실제 차단 명령/부모 프로세스를 확보하지 못했으므로 오탐이나 파일 감염으로 단정하지 않았습니다. 백신 설정/예외/격리 상태는 변경하지 않았고, 이후 진단·빌드는 가능한 직접 CLI argv로 실행했습니다.

# WorkTrail 0.3.1 · native OpenCode / 요청 샘플 (2026-11-14)

- Windows native OpenCode 2.3.0 설치 완료. 공식 GitHub asset SHA-256 `2e14eee53f4abad803d55fdc472c1b12dc3802d687ae204f81e7908bd2ab1895` 대조. 사용자 PATH 및 WorkTrail absolute exe 설정. 기존 WSL 설치/로그인은 변경하지 않았습니다.
- 현재 사용자의 `%LOCALAPPDATA%\WorkTrail` 설정/DB/blob을 백업한 뒤 native `.exe`, 빈 ai_prefix, standalone, stdin으로 전환했습니다. 자격 증명은 WorkTrail 설정/배포물에 넣지 않습니다.
- 계정 연결은 **사용자 기기 인증 완료 대기**입니다. 설치된 CLI auth list의 마지막 결과는 `No authenticated integrations`. Windows native 실제 모델 호출 성공으로 기록하지 않습니다. 브라우저 자동 열기는 자동 승인 검토에서 blocked by policy로 거부돼 직접 기기 인증으로 전환했습니다. 인증 전 작업은 attempts=0으로 대기하고 인증 후 재개합니다.
- 요청한 메일 **14건**(광고3/참조전용2/시스템2/단순답변2/답변+추가업무2/JIRA알림3), 연결된 전체 JIRA **3건**. 이미지 CID PNG, 실제 기한, 코너 simulation 및 DB release 조건, 다른 수행자의 JIRA 댓글을 포함합니다. 실제 회사/외부 JIRA가 아닌 로컬 fixture입니다.
- 사용자 기본 앱 DB에서 원문17, 규칙분류10, 모델분류 대기7/시도0 확인. 기존 앱을 정상 종료하고 새 EXE에서 합성 환경 표시와 원문 적재를 확인했습니다. 실제 모델 결과는 인증 후 검증해야 합니다.
- 광고 제목 규칙, 명시된 다른 수신인+본인 CC 전용 규칙(본인에게 별도 요청이 있으면 자동 제외하지 않음), 추가 조치 없음이 명시된 자동 알림 규칙, JIRA 알림 중복답변 제외를 저장 이력/근거와 연결했습니다. 조치 필요 자동 알림을 무조건 no-action으로 확정하지 않습니다.
- 이슈별 fixture lookup과 알림→전체 이슈 화면 링크, sample_mode 안내, `--samples` 원문 적재를 추가했습니다. 샘플 기준표는 AI/KB에 주입하지 않습니다.
- **60 tests passed**, ruff/format 검사 통과. 실제 Windows EXE smoke의 메뉴·중복 실행·worker 강제 종료/재시작·backend 종료·재기동 데이터 유지 통과(`runtime/native-sample-release-smoke/verification.json`). 패키지 안 샘플 EML/fixture/CID로 `--samples` 실행/정상 종료 확인(`runtime/sample-pack-exe-smoke/smoke.json`). 시각 캡처는 helper timeout으로 성공 처리하지 않았고 접근성 tree/DOM/API/DB 확인만 기록합니다.
- 이미지 픽셀 해석 기능은 여전히 미지원입니다. 캡처 의존 질문은 partial/needs_vision이며 직접 확인 전 수치/확정 기술 답변을 만들지 않습니다. 이 샘플은 수행 전 요청들이므로 확정 업무일지 0건이 정상입니다.

자세한 입력 목록/실행/계정 연결: [native와 샘플 안내](native-and-samples.md).

---

# WorkTrail 0.3 Windows 통합 진행 — 2026-11-14

참조 저장소를 읽고 WSL의 기존 테스트 45 passed를 기준으로 기록했습니다. Windows 초기 기준은 36 passed/9 failed였으며 CP949·Unix shebang·문서 subprocess 인코딩 문제를 수정해 기존 45개가 모두 통과했습니다. 참조 runtime/DB/소스는 수정하지 않았습니다.

현재 완료:

- Windows Python 3.12.3 별도 venv, pywebview 6.2.1 / WebView2, PyInstaller 6.22.3 onedir x64 실행 파일.
- localhost 백엔드/수집·AI worker/문서·COM helper 분리, 사용자 데이터 경로, 앱 잠금, worker supervisor, 종료·부모 소멸 감지. worker 강제 종료가 Python 공유 Event를 잠그는 실제 결함을 Windows 커널 Event로 수정했습니다.
- schema v5 additive migration 및 v4 사전 snapshot, 기존 원본/초안/사용자 편집 호환. 백업/새 경로 복원에 업무일지 데이터 포함.
- 공통 classify 결과의 수행 제안만 업무 기록으로 연결. 원문 작성일·수집시각·실제 수행일 분리, 불확실한 수행일은 빈 값, 직접 확정/할 일 완료 연결, 사용자 편집 이력/version 보존.
- 메일/JIRA 같은 수행의 대표 활동 연결과 중복 집계 제외, 대표 기록에서 양쪽 근거 확인. 다른 source/revision에서 반복한 실제 수행은 별도 제안으로 보존합니다. 의미상 동일 여부는 사용자 확인 대상입니다.
- 오늘/문의함/답변 초안/업무일지/프로젝트 화면, 수동 기록, 원문·활동 연결, 프로젝트 연결, Markdown 생성 영역 보존 export와 명시 파일 import.
- EML/fake/Outlook MSG 정규화 adapter. 이미 열려 있는 허용 Word 세션에서 읽기 전용 문서를 여는 선택 adapter, COM STA 초기화·해제, 전용 직렬 helper·timeout·재시도. 사용자가 열어 둔 문서와 Office/Outlook 프로세스는 종료하지 않습니다.

검증 결과:

- Windows `python -m pytest -q`: **55 passed**, 기존 Starlette/httpx deprecation 경고 1건. Fake/fixture 및 COM lifecycle stub 기준이며 사내 성공을 뜻하지 않습니다.
- `ruff check`, `ruff format --check`, `pip check` 통과. 합성 평가 **5/5**, 실제 정확도 주장 없음.
- `tests/test_worklog.py`: 수신→약속→수행/전달·기존 할 일 완료 확인, 수행일 미지정·늦은 수집, 재분류 후 편집 보존, version 충돌, 메일/JIRA 양쪽 근거·대표 기록 1건 집계, 반복 수행 구분, 백업/복원, 사용자 Markdown 보존·반복 동일성·생성본 재입력 거부, COM timeout 중 UI API 유지·다음 helper 복구, Word COM readonly/사용자 문서 보호·해제 stub.
- `tests/test_runner.py`: 한글 36,000자 stdin fixture 및 Windows Job Object의 소유 자식/손자 종료 포함. 기존 worker 실제 프로세스 kill→lease 복구 회귀도 통과.
- 실제 Windows EXE smoke: WebView2에서 오늘 및 문의함/업무일지/프로젝트/답변 초안/운영 상태 로딩. 동일 데이터 중복 실행 차단, worker 강제 종료→supervisor 재시작 중 API 유지, 정상 창 닫기→백엔드 종료, 앱 재기동→수동 수행 기록 유지. 재현 명령: `python scripts/desktop_smoke.py --output 'runtime/새 검증 폴더'`. 결과는 해당 폴더의 verification.json과 smoke*.json.
- native Windows OpenCode는 PATH에 없었고 기존 WSL executable은 ELF입니다. 설치·로그인은 바꾸지 않았습니다. WSL OpenCode **2.3.0**의 version/run help/models를 확인하고 Windows Python→WSL runner→`openai/gpt-6.1-sol-fast` 합성 live smoke에서 JSON·근거 계약 검증을 통과했습니다. 초기 invalid_action_evidence를 prompt 계약 명시로 수정했으며, 별도 standalone·stdin 경로도 실제 검증했습니다. 분류 정확도/사내 모델 평가 결과는 아닙니다.
- Windows UI 캡처 도구는 FrameArrived/window capture timeout이 두 차례 발생했습니다. 시각 레이아웃 검토 완료로 기록하지 않으며, 네이티브 WebView2의 DOM/화면 이동 및 HTTP 검증 결과만 기록합니다.

남은 제한·사내 확인:

실제 DRM 문서/허용 Outlook·Word 버전·COM 등록·bitness·계정/대화상자 복구, 실제 EML과 원본 경로 정책, 사내 JIRA 인증·담당자/댓글 의미, native OpenCode, 오프라인 반입·새 PC WebView2/.NET 환경, 장시간 운영은 미검증입니다. Excel/PowerPoint DRM COM adapter는 제공하지 않으며 기존 표준 파일 추출만 사용합니다. 별도 worklog 저장소 위치/구조가 없으므로 임의 일괄 변환은 하지 않았습니다. 명시한 Markdown 한 파일을 원문 그대로 확인 대상으로 가져옵니다. 트레이 상주는 이번 버전에 없으며 닫으면 종료합니다. 메일 발송·JIRA 쓰기는 없습니다.

자세한 실행·운영·백업·외부 의존성: [Windows 안내](windows-worktrail.md).

---

아래는 참조 0.2의 WSL 개발 이력입니다.

# 개발 진행 — 2026-11-14

현재 범위: **P2~P5 로컬 구현·검증, P6 사내 적용 직전 준비**. 실제 사내 적용은 수행하지 않았습니다.

| 단계 | 구현·검증 | 사내에서 남은 확인 |
|---|---|---|
| P2 | 수신/발신·별칭/To/CC, 대화별 inquiry, 여러 할 일·수행 연결 제안, revision/event, 수동 분류/상태·메모 이력, baseline, stale·편집 충돌·재생성 후보 | 실제 메일의 담당/완료 판단과 모델 정확도 |
| P3 | JIRA 알림 발견 후 제외, 수동 등록, 다중 서버·미등록 호스트, 순차 fixture, 댓글 전체 페이지·필드 완전성, 실패 시 이전 snapshot 보존, 첨부 실패·주기 조회/일시중지/닫힌 이슈 저빈도, read-only HTTP 경계 | 사내 API·인증·멘션·첨부 URL 정책·응답 매핑 |
| P4 | HTML 표/링크·CID 보존, 인용문/서명 복원 표시, text/CSV/PDF/Office 추출·위치·제한, Markdown 검색, 입력 예산·근거 적용 조건 검증, 생성/편집 이력·KB freshness | OCR/회로 해석·DRM은 미지원, 실제 KB 적용성/모델 답변 품질 |
| P5 | cursor·미처리 revision 재조회, single worker/poll 잠금·heartbeat·lease/token, 제한 재시도·늦은 결과 거부, 큰 문의 격리, dry-run·운영 상태·재시도, checksum backup/새 경로 restore, 로컬 자산 | 실제 호스트 스케줄러·DB 경로·장기 운영 |
| P6 준비 | 검증 설정·비밀정보 없는 corporate 예제, lock·wheelhouse 생성기, 패키지 내 offline demo, systemd 사용자 unit 예제, 이식 runbook·합성 모델 평가기·CI 정의 | 대상 OS/Python·의존성 반입, 실제 EML/JIRA/GEK/모델 smoke, 현장 백업 복원·점진 활성화 |

## 확인한 결과

- `.venv/bin/python -m pytest -q`: **45 passed**. Starlette의 httpx TestClient deprecation 1건, 실패 없음.
- `ruff check src tests scripts`와 format 검사.
- `scripts/evaluate.py`: FakeRunner 합성 계약/판단 항목 **5/5**. 실제 모델 정확도 수치가 아닙니다.
- 실제 worker 프로세스 SIGKILL → lease 만료 → 다음 worker 재수행·완료 확인.
- SQLite backup → 다른 경로 restore → 사용자 편집·검토·원본 다운로드 유지, 손상된 checksum 거부.
- Chromium 158 실제 브라우저: 초안 수정·저장·검토, 새로고침 보존, 수동 업무 상태 변경, 390px 모바일 가로 넘침 없음, 외부 요청/JS 오류 없음. 캡처는 `runtime/browser-review/`에 보관합니다.
- `dist/corporate-kit-0.2.0/` wheelhouse를 별도 venv에 `--no-index`로 설치하고 `pip check` 통과. 저장소 src가 아닌 설치된 wheel에서 **45 tests passed**, 패키지 내 demo 수집 1/완료 4, 합성 평가 **5/5** 확인.
- 최종 반입 archive: `dist/mail-jira-assistant-0.2.0-linux-cp314.tar.gz`. `checksums.json`과 표준 라이브러리 검증 스크립트를 포함합니다. 검증한 OS/Python 이외의 호환성을 뜻하지 않습니다.

## 알려진 경계

단일 사용자/호스트/worker, localhost 브라우저 전용입니다. 정확한 AI 판단이나 기술 수치의 정답을 fake로 검증했다고 주장하지 않습니다. 기본 JIRA는 v2/v3 Bearer GET이며 사내 특수 인증/DRM/GEK는 현장 adapter 검증이 필요합니다. 벡터 검색·OCR·이미지/회로 해석·스프레드시트 재계산·메일 발송/JIRA 쓰기는 제공하지 않습니다. CI의 Python 버전 matrix는 정의했으며 외부 CI 실행 결과는 아직 없습니다.

원본 계획서의 마지막 ‘사내 이식 후 실제 환경 검증’ 항목은 완료 처리하지 않았습니다. 현장 확인 항목과 실행 순서는 `corporate-porting.md`에 남겼습니다.
