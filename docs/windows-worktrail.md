# Windows 전환 및 WorkTrail 통합

작성일: 2026-11-14. 참조: `\\wsl.localhost\Ubuntu\home\minq\codes_wsl\inquiry-system`.

## 기존 구현 확인

계획만으로 판단하지 않고 코드·schema v4·진행/계약/평가/이식 문서와 45개 테스트를 확인했습니다. 해당 저장소와 상위 작업 폴더에 적용할 AGENTS.md는 발견되지 않았습니다. 기존 수집/대화 연결/분류·수행 제안/JIRA GET/초안 버전·수정본/lease·attempt·잠금/백업을 재사용합니다. 실제 사내 연결과 모델 정확도는 기존에도 미검증입니다. 별도 worklog 저장소나 Markdown 위치는 제공되지 않았으며 관련 없는 디렉터리는 탐색하지 않았습니다.

WSL 종속: `.venv/bin`, systemd unit, Unix shebang, SIGKILL/process group, UTF-8 locale, Linux CPython wheelhouse. Windows에서는 별도 `.venv\Scripts`, 로그인 사용자 데스크톱, native multiprocessing spawn, UTF-8 명시, 자식 tree 종료를 사용합니다. systemd 예제는 Linux 전용으로 유지합니다.

## 실행

```powershell
C:\miniconda3\python.exe -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[test,desktop,documents,build]'
.\.venv\Scripts\python.exe -m mail_jira_assistant.desktop
# 합성 fixture를 넣는 별도 데모
.\.venv\Scripts\python.exe -m mail_jira_assistant.desktop --data-dir "$env:LOCALAPPDATA\WorkTrail-Demo" --demo
.\scripts\build_windows.ps1
.\dist\WorkTrail\WorkTrail.exe
```

기본 영속 경로는 `%LOCALAPPDATA%\WorkTrail`: `settings.toml`, `runtime/app.sqlite3`, 원본 `runtime/blobs`, `runtime/exports`, 회전 `desktop.log`, WebView2 프로필. 설치 폴더에 업무 데이터를 쓰지 않습니다. `--data-dir`로 다른 로컬 경로를 지정할 수 있습니다. 설정 TOML 경로는 설정 파일 기준입니다. CLI는 기존 `--runtime` 동작을 유지하므로 데스크톱 DB를 조작할 때 명시하세요.

Windows 10/11 x64, Microsoft Edge WebView2 Evergreen Runtime, .NET Framework 4.8 및 해당 runtime 정책을 확인하세요. 배포 폴더 전체를 복사합니다. Python은 빌드 호스트에 필요하고, 배포 실행 파일은 Python을 포함합니다. OpenCode와 Office/Outlook/DRM 허용 프로그램은 포함하지 않습니다. 사내 반입 시 대상 OS에서 smoke와 checksum을 확인하세요. 인터넷/CDN 정적 자산을 사용하지 않습니다.

## Windows 빌드

Windows PowerShell에서 저장소 루트 `D:\codes\worktrail`을 기준으로 실행합니다.
처음 준비할 때는 위 실행 절의 명령으로 `.venv`를 생성합니다.

```powershell
.\.venv\Scripts\python.exe -m pip install -e '.[test,desktop,documents,build]'
.\.venv\Scripts\python.exe -m pytest -q
.\scripts\build_windows.ps1
.\dist\WorkTrail\WorkTrail.exe
```

빌드 스크립트는 PyInstaller의 onedir 방식으로 `dist\WorkTrail`을 만들고,
README와 `docs`를 복사합니다. 실행 파일은 `dist\WorkTrail\WorkTrail.exe`입니다.
배포할 때는 `_internal`을 포함한 `dist\WorkTrail` 폴더 전체를 복사합니다.
`-Output`은 WorkTrail 폴더를 생성할 상위 경로이며 기본값은 `dist`입니다.
빌드는 현재 `.venv`의 패키지 목록을 `requirements-windows.lock`에도 기록합니다.

실행 중인 배포 앱은 편집 내용을 저장하고 종료한 뒤 다시 빌드합니다.
빌드 폴더와 별도로 기본 업무 데이터는 `%LOCALAPPDATA%\WorkTrail`에 보존됩니다.

배포 파일의 실제 WebView2 실행·AI 변경안 반영·worker 복구·재실행 보존을
별도의 샘플 데이터 경로에서 확인하려면 다음을 실행합니다.
`--output`은 실행할 때마다 존재하지 않는 새 경로를 지정합니다.

```powershell
.\.venv\Scripts\python.exe scripts\desktop_smoke.py --exe dist\WorkTrail\WorkTrail.exe --output runtime\windows-build-smoke --projects
```

## 실행 수명

한 데이터 경로에 한 앱만 OS 파일 잠금으로 실행합니다. 백엔드는 loopback의 임의 포트를 실제 bind한 뒤 전달합니다. 웹/API와 수집·AI worker를 별도 프로세스로 분리합니다. 문서 추출/COM은 spawn한 별도 helper에서 실행하며 COM 호출은 직렬입니다. 트레이 상주는 이번 버전에 넣지 않았습니다. 창 닫기를 확인하면 백엔드/worker에 종료를 요청하고 최대 5초 후 해당 앱 프로세스만 종료합니다. 실행 중 lease가 남은 작업은 다음 기동 시 만료 후 기존 attempt token 규칙으로 복구합니다. Office/Outlook 프로세스를 종료하거나 Quit하지 않습니다. 창을 닫기 전에 편집본을 저장하세요.

## AI

기존 `opencode run --format json --agent plan` 계약을 유지합니다. 설치된 WSL 2.3.0의 `run --help`에서 model `provider/model#variant`, session/continue, file, JSON 옵션을 확인했습니다. session/continue/auto를 사용하지 않습니다. Windows PATH에는 native OpenCode가 없고 WSL executable은 ELF라 native 실행이 불가능했습니다. 정상 설치·로그인·모델 연결은 변경하지 않았습니다. `config/windows-wsl.toml`은 기존 executable을 `ai_prefix` argv로 호출하는 교체 가능한 예제입니다. WSL 호출에 Windows 환경변수가 자동 전달되지 않으므로 permission deny를 prefix의 env에 명시합니다. 실제 사내 사용은 native executable을 설정하고 prefix를 비우는 방식을 우선합니다. 설치된 버전·이벤트 출력·권한 정책은 사내 live smoke로 재확인하세요.

`worker --live` 또는 `live-smoke`는 기존과 같이 명시적으로 사용합니다. 데스크톱은 사용자가 설정한 `ai_backend="opencode"`일 때만 실제 runner를 실행합니다. 기본은 fake와 history-only입니다. 모델/인증 값은 배포물에 넣지 않습니다. 일반 테스트는 실제 모델을 호출하지 않습니다.

## 업무 데이터와 호환

Inquiry = WorkItem, 기존 Action = ActionItem, sources/revisions = Evidence, drafts/edits = Draft를 유지합니다. schema v5는 projects/inquiry_projects, activities/activity_evidence/activity_edits/worklog_imports를 추가합니다. 기존 v4 DB는 SQLite snapshot을 `pre-migration-v4.sqlite3`으로 보관한 후 additive migration합니다. 기존 backup/restore는 원본 blob과 새 테이블을 함께 보존합니다. restore는 새 경로에만 허용합니다. settings.toml과 desktop.log는 DB 백업과 별도로 복사하세요.

공통 분류 트랜잭션에서 performed 제안을 기록합니다. AI 재분류는 사용자 편집 기록을 덮어쓰지 않습니다. todo/waiting은 기존 Action 흐름을 재사용합니다. 수행 확정에는 실제 수행일을 요구하며 원문 작성일·수집 시각과 분리합니다. 자동 제안의 수행일은 빈 값으로 두므로 늦은 수집도 오늘 실적으로 오인하지 않습니다. 수행자·근거·관련 action ID는 원래 분류 evidence에 보존합니다. 불확실한 연결은 사람이 확인하며 자동 확정하지 않습니다.

여러 출처의 같은 수행은 대표 활동 ID를 `duplicate_of`에 지정해 연결하고 대표 기록만 집계합니다. 교차 출처 의미 중복은 자동 확정하지 않습니다. 사용자가 확인하지 않은 제안은 집계하지 않습니다. 수동 시간만 기록하며 메일 수나 시각으로 시간을 계산하지 않습니다. 할 일 완료는 확정 수행과 연결한 후 별도 체크로만 변경합니다. 초안 생성·검토는 수행 활동을 만들지 않습니다.

오늘/문의함/답변 초안/업무일지/프로젝트를 동일 업무와 연결합니다. 프로젝트 화면에서 문의 ID로 프로젝트를 연결하며 관련 할 일/수행을 모읍니다. 수행 기록 편집에는 version 충돌 확인과 변경 전 snapshot이 있습니다. 근거/편집 이력 링크로 원래 분류와 수정본을 확인할 수 있습니다.

Markdown 집계는 코드로만 수행합니다. 명시한 날짜의 확정 대표 수행만 날짜/프로젝트로 출력합니다. `<!-- worktrail:begin -->`~`<!-- worktrail:end -->` 영역만 갱신하고 사용자 메모를 보존합니다. 표시가 손상되면 기존 파일을 그대로 두고 실패합니다. Obsidian 경로를 지정한 직접 export는 Python API `worklog.export(runtime, date, destination)`를 사용합니다. 화면 다운로드는 runtime/exports에 저장합니다. 가져오기는 사용자가 지정한 파일 하나만 읽고 원본 blob과 내용을 보존해 확인 대상으로 만듭니다. 동일 경로/바이트 재입력은 중복 활동을 만들지 않으며 WorkTrail 생성 표시가 있는 파일은 거부합니다. 기존 자료의 구조별 일괄 변환은 실제 자료를 받은 뒤 추가합니다.

## 권한 프로그램 adapter

`document_adapter="eml"`이 기본입니다. `fake`는 가정 검증용, `outlook_msg`는 사내 허용 Outlook의 OpenSharedItem 예제입니다. EML/COM 결과는 status/text/locations/warnings/headers로 정규화합니다. 원본 바이트는 그대로 보존합니다. `outlook_msg`는 .msg 입력을 추가로 읽습니다. 표준 EML을 Outlook adapter에 강제로 통과시키지 말고 폴더/프로필을 분리하세요. 실제 사내 EML 접근 방식은 허용 프로그램에 맞춘 추가 adapter가 필요할 수 있습니다.

STA COM 초기화/해제는 helper 내부에서 수행합니다. timeout은 helper만 종료하고 다음 호출에서 새 helper를 생성합니다. 권한 프로그램의 대화상자가 남으면 사용자가 직접 확인한 후 재시도해야 합니다. 빈 본문/오류는 성공으로 저장하지 않고 sync_errors에 남깁니다. 이미지·COM 첨부 미추출은 partial로 표시합니다. win32com은 DRM 해제가 아닙니다. 로그인한 사용자 세션만 지원하며 Windows 서비스는 전제하지 않습니다.

## 검증과 사내 확인

최신 실행 결과는 docs/progress.md에 기록합니다. 실제 DRM, Outlook/Office 버전·프로필/bitness, 프로그램 허용 정책, JIRA 인증·pagination·담당자/계정 매핑, native OpenCode, 오프라인 반입, 장시간 운용은 사내 미검증입니다. 집의 fake/fixture 결과를 사내 성공으로 바꾸지 않습니다.

공식 참고: [pywebview 배포](https://pywebview.flowrl.com/guide/freezing.html), [Windows Job Objects와 자식 프로세스](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects), [PyInstaller multiprocessing](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html).


## 0.3 최종 보완

종료 신호는 Windows 커널 Event를 사용합니다. 강제 종료된 worker의 Python 잠금 때문에 종료가 멈추지 않도록 실제 배포 kill/restart 시험으로 검증했습니다. desktop/backend/worker 로그는 각각 사용자 데이터 폴더에 회전 저장합니다. 부모 앱이 사라지면 자식도 종료 신호를 설정합니다.

`attachment_adapter="word_active"`는 이미 열려 있는 Word의 허용 세션을 사용해 .doc/.docx/.rtf 첨부를 읽는 선택 기능입니다. 보존 blob 경로를 readonly로 열며 새로 연 문서만 닫습니다. 원본 파일명/DRM 정책에 따라 사내에서 별도 경로 adapter가 필요할 수 있습니다. 기존 사용자 문서가 같은 경로로 열려 있으면 접근을 거부합니다. 실제 Word/DRM 검증은 미완료이고 lifecycle stub만 검증했습니다. Excel/PowerPoint COM은 포함하지 않았습니다.

`ai_input="stdin"`은 Windows 명령행 한도를 피합니다. 기존 WSL 2.3.0에서 실제 검증했습니다. 기본 argument 모드는 호환성을 위해 유지하며 한도 초과는 명시적으로 실패시킵니다. native 실행은 실제 .exe를 지정하고 .cmd/.bat/.ps1 shell shim은 사용하지 않습니다. WSL 예제는 `--standalone`과 Linux timeout을 적용해 Windows 연결 종료 후에도 실행 수명을 제한합니다. 현장 timeout을 변경하면 두 값도 함께 조정하세요.

최종 검증: 55 tests, ruff/format/pip check, FakeRunner 평가 5/5, 실제 배포 EXE의 5개 메뉴와 오늘 화면·중복 실행·worker 재시작·종료·데이터 유지. 실제 UI 캡처 도구 timeout으로 픽셀 단위 시각 검토는 미완료입니다. 자세한 증거는 docs/progress.md를 확인하세요.
