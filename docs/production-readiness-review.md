# WorkTrail 운영 준비 검토

검토일: 2026-11-14 (KST) · 기준 커밋: af262de · 대상: Windows 개인용 로컬 앱과 CLI/WSL 실행 경로.

## 판단

개인 PC에서 합성 데이터로 시범 운용할 기반은 갖췄다. 실제 사내 메일·JIRA·기술문서를 상시 처리하려면 아래 P1 항목부터 보완해야 한다. 현 구조의 지원 범위는 단일 사용자·단일 호스트다. 공유 서버로 확장할 경우 사용자 인증, 데이터별 권한, 감사 주체, 저장소 분리부터 별도 설계해야 한다.

이번 검토는 코드·설정·테스트·배포 스크립트를 읽고 로컬 합성 데이터로 확인했다. 실제 계정/모델/Office/DRM을 호출하거나 운영 데이터를 읽지 않았다. 제품 코드는 변경하지 않았다.

## 확인 결과

- Windows 개발 환경에서 `python -m pytest -q`: **60 passed**, 15.29초. Starlette TestClient의 httpx 사용 중단 예정 경고 1건.
- `python -m pip check`: **No broken requirements found**.
- 세 lock 파일의 고유 패키지/버전 조합 **44개**를 OSV querybatch로 조회: 응답에 취약점 매칭 **0건**. 조회 시점의 알려진 취약점 확인일 뿐, 패키지 버전 존재 여부·공급망·미등록 취약점·배포 EXE의 실제 구성까지 보증하지 않는다.
- 합성 파일 재현: Origin/인증 헤더 없이 `/api/worklog/import`로 runtime 밖 파일을 가져오기 **200**, `/api/activities` 조회 **200**, 합성 파일 본문 노출 확인.
- mock 기반 재현: `word_active`로 `.doc`/`.rtf`를 전달하면 둘 다 **unsupported**, COM helper 호출 **없음**.

이미 있는 방어도 유지해야 한다. loopback 바인딩, TrustedHost, 외부 Origin의 변경 요청 거부, JSON 요청 강제, CSP/이스케이프, 첨부 다운로드 경로 제한, SVG 인라인 거부, JIRA HTTPS·동일 origin·리다이렉트 거부, SQL 파라미터 바인딩, AI 근거 검증, 사용자 편집본 보존, worker lease/heartbeat, SQLite snapshot 백업이 구현되어 있다.

## P1 — 실제 사내 데이터 투입 전

### 1. 로컬 HTTP API에 세션 접근 통제가 없다

근거: `src/mail_jira_assistant/web.py:158`, `:172`, `worklog_web.py:84`, `worklog.py:234`.

Host/Origin 검사는 호출자 인증이 아니다. 로컬의 다른 프로세스·다른 사용자 세션에서 loopback 포트에 접근할 수 있으면 문의·원본·첨부를 읽고 기록을 수정하거나 AI 작업을 요청할 수 있다. Origin이 없는 JSON 요청도 허용된다. 임의 경로 import는 이 접근 권한으로 앱 실행 계정이 읽을 수 있는 텍스트 파일을 DB에 복사하고 API로 읽는 통로가 된다. 확장자 제한도 없고 파일 전체를 읽은 뒤 2MiB를 검사한다.

이는 원격 웹사이트가 즉시 모든 데이터를 읽을 수 있다는 재현은 아니다. 기존 Origin/JSON/Host 방어가 일반적인 브라우저 공격 경로를 줄이고 있다. 확인한 문제는 **로컬 호출자를 신뢰하는 경계**다.

조치:

- 앱 시작마다 예측 불가능한 토큰을 만들고 데이터 조회·다운로드·변경 API에 검증한다. 데스크톱/일반 브라우저 실행 모두 bootstrap·세션 전달 방식을 설계한다. URL query와 access log에 토큰을 남기지 않는다.
- import는 네이티브 파일 선택으로 승인한 경로나 명시적 허용 폴더로 제한하고, regular file·경로·읽기 최대량을 검사한다. UNC/장치 경로는 운영 요구를 정해 허용한다.
- 운영 환경의 `testserver` 허용 제거, 필요 없는 `/docs`·`/openapi.json` 비활성화는 추가 축소 조치다. 이것만으로 인증 문제가 해결되지는 않는다.

완료 기준: 토큰 없는 읽기/변경/원본 다운로드가 거부되고 정상 UI는 작동하며, 승인하지 않은 경로 import가 실패한다. pywebview도 로컬 REST API에 세션 토큰을 사용하도록 안내한다: https://pywebview.flowrl.com/guide/security

### 2. AI 외부 전송 정책을 설정 단계에서 강제하지 않는다

근거: `service.py:449`, `ai.py:91`, `:174`, `settings.py:36`, `desktop.py:117`, `config/corporate.toml`.

요청에는 메일 본문·첨부 추출문·과거 대화·수신자·내부 메모·KB가 포함된다. corporate 설정에서도 모델은 선택 사항이라 OpenCode의 외부 기본 설정에 의존할 수 있다. 데스크톱은 `ai_backend=opencode` 설정으로 실제 호출하고 CLI의 `worker --live` 확인 단계는 거치지 않는다. 이는 자동 처리 설계와 일치하지만 README의 “명시적 opt-in 명령에서만” 설명은 데스크톱과 맞지 않는다.

조치: corporate에서는 분류/초안 모델과 승인 provider를 명시하고 미설정 시 실행을 거부한다. 외부 전송 허용 여부와 데이터 종류를 설정·초기 연결 화면에서 명확히 보여준다. 분류만 하더라도 외부 전송이 발생한다는 점을 표시한다. 제외 폴더·기밀 문서 제외·필드 최소화·필요한 마스킹을 적용하고 승인되지 않은 모델로의 fallback을 막는다. 기본 corporate 운용은 history-only, 자동 초안 해제에서 시작한다.

완료 기준: 미승인 provider/모델 설정으로는 호출이 시작되지 않으며, 합성 canary로 각 단계에 실제 전송하는 필드를 검증한다.

### 3. OpenCode 실행 격리는 OS 보안 경계가 아니다

근거: `ai.py:152`, `:174`, `settings.py:31`.

임시 cwd·도구 deny·timeout은 유용하지만 subprocess는 같은 Windows 사용자 권한과 전체 환경변수를 상속한다. JIRA 토큰 등 불필요한 비밀도 자식에 전달될 수 있다. 사용자 전역 OpenCode 설정/플러그인/저장 정책까지 이 코드가 차단한다고 볼 수 없다. 기본 argument 모드는 메일·KB를 프로세스 명령행에 담는다. 실제 도구 권한 우회를 이번에 재현한 것은 아니다.

조치: 검증된 OpenCode 버전과 전용 실행 프로필을 사용하고, 필요한 환경변수만 전달한다. native stdin 모드를 검증한 뒤 기본값으로 바꾼다. 실제 외부 runner가 프롬프트 공격에도 파일/셸/MCP/네트워크 도구를 실행하지 않는지 악성 합성 입력으로 시험한다. 더 강한 격리가 필요하면 agent CLI 대신 고정 모델 API 경계나 별도 권한의 프로세스를 검토한다.

완료 기준: 메일이 명령행에 나타나지 않고, runner에 JIRA canary 토큰이 전달되지 않으며, 허용하지 않은 도구 실행이 실패한다.

### 4. 원문·프롬프트·로그·백업의 보존 정책이 없다

근거: `storage.py:36`, `service.py:661`, `:802`, `ai.py:239`, `operations.py:13`.

SQLite와 blob은 앱 수준 암호화 없이 저장된다. attempts에 입력 전문과 결과, runner stdout/stderr가 누적된다. 환경변수 기반 secret 정제는 일부 runner 로그에만 적용되며, 메일·KB의 개인정보나 `attempts.input`까지 제거하는 기능은 아니다. 회전 로그와 달리 DB 이력·blob의 보존 기간/용량 정책이 없다. 백업도 같은 민감도를 가진다. `mkdir(mode=0o700)`만으로 기존 폴더 및 Windows ACL을 검증했다고 볼 수 없다.

조치: 사용자 전용 ACL 확인, 관리 PC의 디스크 암호화, 백업 접근권한/암호화, 입력 전문 로깅 기본 해제 또는 짧은 보존, 조회 가능한 삭제/보존 정책을 도입한다. 삭제는 revisions/attempts/edits/blob/백업까지 고려하고 미참조 blob만 정리한다. WAL·마이그레이션 snapshot도 보호 대상에 포함한다.

완료 기준: 별도 Windows 계정에서 데이터 접근이 거부되고, 합성 비밀이 일반 로그/진단 패키지에 없으며, 보존 기간 이후 정리와 복원 절차가 검증된다.

### 5. 문서 처리 timeout은 있지만 메모리 제한은 실제 경로에 없다

근거: `documents.py:149`, `:184`, `process_worker.py:10`, `:34`, `knowledge.py:31`, `worklog.py:239`.

`resource.setrlimit`는 documents 모듈을 직접 실행하는 `__main__`에 있다. 실제 extraction은 multiprocessing helper가 `_extract`를 호출하므로 이 제한이 실행되지 않는다. Windows helper에도 메모리 제한이 없다. 압축된 PDF가 파싱 중 크게 팽창하면 20MiB 입력/15초 제한만으로는 호스트 메모리를 보호하지 못한다. KB는 파일별 크기 제한 없이 모두 읽으며 Markdown import도 전체 읽기 후 제한한다.

조치: Windows Job Object의 helper 메모리 제한, Unix worker 진입점의 실제 resource 제한을 적용한다. 부모로 보내는 text/locations/warnings도 상한을 둔다. KB 파일 크기·검색 총량·import bounded read를 제한한다. 메일 단위 전체 처리 시간/첨부 총량도 관리한다. pypdf 공식 문서도 작은 페이지 수와 별개로 content stream 처리에서 큰 메모리 사용이 발생할 수 있음을 설명한다: https://github.com/py-pdf/pypdf/blob/main/docs/user/extract-text.md

완료 기준: 압축률 높은 합성 문서·큰 KB·느린 문서를 처리해도 제한된 helper만 종료되고 다음 문의 처리가 계속된다.

### 6. Windows 배포 재현성·신뢰성·업데이트 절차가 부족하다

근거: `scripts/build_windows.ps1:3`, `:9`, `scripts/package_windows.py:29`, `:37`, `.github/workflows/check.yml:5`.

빌드는 현재 `.venv`로 EXE를 만든 뒤 `pip freeze`로 lock을 덮어쓴다. 검토된 lock에서 깨끗한 환경을 재구성했다는 보장이 없다. CI는 Ubuntu 기능 테스트만 수행한다. 배포 체크섬은 전송 오류를 검출하지만 manifest까지 바꾼 배포자의 진위를 인증하지 않는다. 서명/업데이트 검증/실패 시 이전 버전 복귀 절차가 스크립트에 없다. 배포 폴더를 재사용하면 남은 파일도 통째로 포함하며, runtime 검증 JSON을 존재 여부만 보고 복사한다.

조치: hash를 포함한 Windows lock을 검토하고 clean venv에서 설치·검증·빌드한다. runtime/build/test 의존성 분리, SBOM과 알려진 취약점 검사, Windows CI·frozen EXE smoke를 추가한다. 검토된 SHA로 Actions를 고정하고 최소 권한을 지정한다. 배포 폴더를 새로 만들고 허용 목록만 패키징한다. 검증 JSON은 합성 여부·민감정보 정제 확인 후 명시적으로 포함한다. EXE/배포물 서명과 서명 검증을 적용하고, 오프라인 운영이라면 자동 업데이트 대신 서명된 수동 반입·교체·복구 절차를 만든다.

완료 기준: 새 Windows 환경에서 lock으로 빌드한 EXE의 실행·종료·복원·버전 업그레이드를 통과하고, 변조된 배포물은 거부된다.

## P2 — 시범 운영 중 해결

### 7. `.doc`/`.rtf` Word adapter 분기가 실행되지 않는다

`documents.py:151`의 조기 반환 대상에서 `.doc`/`.rtf`를 제외하지 않아 `:162`의 word_active 분기에 도달하지 않는다. 합성 입력과 helper mock으로 재현했다. adapter 분기를 먼저 선택하거나 지원 형식 판단을 하나로 통합하고, 표준 모드는 기존처럼 unsupported로 둔다.

Word 연동은 사용자의 활성 Word에서 `Documents.Open(ReadOnly=True)`를 호출하지만 매크로 차단 설정은 확인하지 않는다(`document_access.py:105`). ReadOnly만으로 실행 콘텐츠 차단을 보장하지 않는다. **COM adapter를 활성화할 때는 P1 조건**으로 다뤄야 한다. 별도 관리된 Word 인스턴스/사내 정책과의 호환성을 검토하고 자동화 보안을 명시적으로 적용한다. 사용자의 활성 세션 설정을 바꾸면 반드시 원복하고 동시 접근도 통제한다. Office 자체가 helper와 별도 프로세스이므로 helper timeout이 문서까지 닫았다는 가정도 금지한다. 공식 설명: https://learn.microsoft.com/office/vba/api/word.application.automationsecurity

### 8. 수집과 AI 작업이 서로 지연시킬 수 있다

`desktop.tasks`는 poll 후 `worker()`를 같은 루프에서 호출하고 worker는 대기열을 빌 때까지 처리한다. AI 작업이 오래 쌓이면 새 메일 수집이 poll_seconds 이상 밀릴 수 있다. JIRA도 이슈당 최대 1000페이지, 첨부 수 제한 없이 순차 처리하여 전체 poll 시간 상한이 없다(`jira.py:118`, `:238`).

poll과 worker를 독립 실행하거나 worker의 작업 수/시간 slice를 제한한다. JIRA 전체 조회 시간·댓글 수/용량·첨부 총량·429 Retry-After·백오프를 추가하고 미완료 수집을 명확히 표시한다. desktop supervisor는 worker만 재시작하므로 backend 사망도 탐지·표시한다. 최종 poll 성공 시각, worker heartbeat, 대기열 최고 대기시간, 디스크 여유를 운영 상태에 표시한다.

### 9. 데이터가 늘면 목록 화면이 느려진다

`web.py:270`은 전체 문의와 body를 읽고 문의별 여러 SQL을 실행한다. 검색·필터도 Python에서 전체 목록을 처리하며 `/today`, `/worklog`, `/projects`도 많은 데이터를 매번 불러온다. KB 검색은 매번 전체 Markdown을 읽는다.

SQL 필터·페이지네이션·목록에서 본문 제외·집계 쿼리·필요한 인덱스·KB 캐시/색인을 적용한다. 합성 메일 수만 건과 대용량 KB로 응답 시간, 메모리, worker 동시 접근을 측정한다. 단일 사용자 전제를 유지해도 장기간 누적량 기준은 필요하다.

### 10. 백업은 runtime 복원이 가능하지만 운영 환경 전체 백업은 아니다

현재 snapshot+blob+체크섬·새 경로 복원은 좋은 기반이다. 그러나 runtime 밖 settings, identity, KB, OpenCode 실행 버전/설정은 포함되지 않는다. 복원 뒤 모델·근거·경로를 재구성해야 한다. 백업 전체 파일에 `read_bytes()`로 체크섬을 계산하므로 DB가 커지면 메모리도 커진다.

비밀 없는 설정과 승인된 KB 버전 참조를 포함한 운영 복구 목록을 만들고, hash는 스트리밍으로 계산한다. 자동/수동 백업 주기, 보존 개수, 저장 용량, 허용 손실 시간과 복구 목표 시간을 정한다. 새 PC에서 편집본·원본·첨부·작업 대기열뿐 아니라 올바른 설정으로 재개되는지 복구 훈련한다.

### 11. 문서와 품질 기준을 현재 동작에 맞춘다

README에는 45/55/60개 테스트 및 Windows/WSL 안내, CLI live opt-in과 desktop 자동 처리 설명이 혼재한다. 운영자용 시작 문서 하나에서 지원 OS·설정·데이터 위치·실제 전송 여부·백업·업데이트·장애 복구를 안내하고 과거 릴리스 기록은 분리한다. 버전 문자열도 pyproject/README/package 스크립트의 단일 원천으로 통합한다.

합성 모델 평가와 구조 검증은 실제 현장 정확도 보증이 아니다. 승인된 비식별 평가 자료로 회신 필요/본인 수행/참조 메일/JIRA 작성자/이미지 미해석을 별도 평가하고, 오탐·누락 및 사람이 수정한 비율을 측정한다. 기존의 “초안 검토 ≠ 발송/업무 완료” 원칙은 유지한다.

## 권장 작업 순서

1. API 세션/경로 통제 + corporate AI 모델/전송 정책 + stdin/최소 환경변수.
2. 저장·로그·백업 보호 + 실제 문서 helper 자원 제한. COM 사용 시 별도 보안 게이트.
3. clean Windows 빌드·서명/검증·취약점 검사·업그레이드/복구 시험.
4. `.doc`/`.rtf` 결함, poll/worker 지연과 backend 장애 감지 해결.
5. 소규모 사내 시범 운영으로 정확도·지연·용량을 측정한 뒤 목록/KB 성능과 보존 정책을 조정.

라이브러리를 무조건 최신으로 바꾸기보다, OS별 lock 차이(FastAPI/PDF 등)를 검토하고 보안 패치·호환성·빌드 결과를 함께 관리하는 것이 우선이다. 정기 OSV/pip-audit 검사와 Windows/모델 runner 회귀 검증을 CI에 연결한다. OSV 조회 방식: https://google.github.io/osv.dev/post-v1-querybatch/
