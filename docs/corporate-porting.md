# Windows 0.3 사내 이식 추가

Windows 실행/설정/COM/배포/백업은 [WorkTrail 안내](windows-worktrail.md)를 먼저 확인하세요. 아래 systemd/.venv/bin/Linux wheelhouse 절차는 기존 WSL 호스트용 이력입니다. Windows onedir 배포 폴더 전체를 반입하고 새 PC에서 WebView2/.NET과 외부 OpenCode/Office를 확인해야 합니다. 실제 DRM/인증/프로그램 버전/계정 권한/원본 경로/대화상자/Word·Outlook 프로세스 보존을 소수 파일에서 확인한 뒤 활성화하세요. 실제 검증 전에는 현장 체크박스를 완료 처리하지 않습니다.

# 사내 적용 직전 인수·이식 절차

상태: **사전 준비 완료, 현장 검증 미수행**. 사내 실데이터·인증정보가 없는 개발 환경에서 확인한 결과와 실제 연결 성공을 구분합니다.

## 1. 반입 전 준비

대상 OS/아키텍처·Python 버전, 패키지 반입 정책, 로컬 영속 디스크, 사내 OpenCode/모델, 받은/보낸 EML 폴더와 본인 별칭, JIRA API/인증을 확인합니다. Windows/다른 Python 버전에는 해당 환경용 wheel을 준비합니다. 현재 생성한 wheelhouse는 **Linux x86_64 CPython 3.14**용이며 대상 호환성은 미확정입니다.

개발 환경과 같은 OS/Python이면 다음 명령으로 설치자료·설정·테스트·체크섬을 묶습니다.

```sh
.venv/bin/python scripts/prepare_release.py --output dist/corporate-kit-0.2.0
```

다른 OS/Python이면 그 환경에서 같은 스크립트를 실행하거나 대상용 wheel을 별도로 내려받아야 합니다. native dependency wheel에는 플랫폼/ABI가 포함되므로 파일명만 바꾸지 않습니다. 실제 메일·DB·토큰·집의 OpenCode 인증 디렉터리는 kit에 포함하지 않습니다.

## 2. 오프라인 설치와 합성 점검

kit 루트에서 실행합니다. 현재 반입 묶음은 `dist/mail-jira-assistant-0.2.0-linux-cp314.tar.gz`입니다. 같은 환경의 별도 venv에서 네트워크 없이 설치·45개 테스트·demo 실행을 검증했습니다.

```sh
python3 scripts/verify_release.py .
```

```sh
python3 -m venv .venv
.venv/bin/python -m pip install --no-index --find-links wheelhouse -r requirements-test.lock mail-jira-assistant==0.2.0
.venv/bin/python -m pip check
.venv/bin/python -m pytest -q
.venv/bin/mail-jira --runtime demo-runtime demo
.venv/bin/mail-jira --runtime demo-runtime serve
```

Windows는 `.venv\Scripts\python.exe`, `mail-jira.exe` 경로로 바꿉니다. 선택 extractor의 Unix 메모리/CPU 제한은 Linux에서 검증했으며 Windows에서는 subprocess timeout이 적용됩니다. 테스트와 demo는 실제 AI/네트워크를 호출하지 않습니다. 브라우저는 기본 localhost:8000만 허용합니다.

`checksums.json`의 SHA256을 확인하고, 문서의 테스트 수와 현장 실행 결과를 별도 기록합니다. 개발환경 테스트 성공을 현장 테스트 성공으로 복사하지 않습니다.

## 3. corporate 설정과 인증

`config/corporate.toml`을 별도 운영 파일로 복사하고 다음을 교체합니다.

| 항목 | 확인할 내용 |
|---|---|
| runtime | 로컬 영속 디스크의 전용 디렉터리. SQLite WAL을 NFS/SMB에 두지 않기 |
| inbox / sent | 실제 export 폴더, 작성 완료 방식, 표준 MIME/DRM 여부 |
| identity | 본인 이메일·공유 계정·별칭. JIRA 서버별 identity에 계정 ID |
| knowledge | 실제 Markdown/GEK 접근 권한·문서 구조. 필요하면 knowledge adapter 교체 |
| jira_servers | 서버별 HTTPS base URL·API v2/v3·조회 주기·인증 환경변수 |
| classify_model / draft_model | 사내 OpenCode에서 확인한 모델 ID·입력 한도·timeout |
| history_only | 처음에는 true |
| automatic_drafts | 처음에는 false |

환경변수 `MAIL_JIRA_INTERNAL_TOKEN`에 사내에서 발급받은 토큰을 전달합니다. 기본 connector는 Bearer이며 Basic/SSO/쿠키/별도 인증 proxy가 필요한 서버는 `HTTPJira` adapter를 조정하고 같은 origin/redirect/페이지 완전성 테스트를 유지합니다. 집의 모델 계정이나 인증 파일을 사내로 옮기지 않습니다.

무인 실행은 OS의 서비스 secret 저장/제한된 환경파일을 사용합니다. 예제 systemd는 `%h/.config/mail-jira/secrets.env`를 읽으며 실제 파일 권한을 600으로 제한합니다. 토큰을 Git·TOML·CLI 인자·평가 보고서에 넣지 않습니다. SSL 인증서 오류를 우회하기 위해 TLS 검증을 끄지 않습니다. 사내 CA는 OS/Python 신뢰 저장소에 반영합니다.

```sh
.venv/bin/mail-jira --config config/corporate.toml doctor
.venv/bin/mail-jira --config config/corporate.toml poll --once --dry-run
```

## 4. 실제 EML과 JIRA 읽기 검증

1. 자동화를 끈 상태에서 소수 실제 EML만 별도 폴더에 복사합니다. 받은/보낸 방향·별칭·To/CC·References·원래 날짜와 KST 표시를 확인합니다.
2. MIME 본문·HTML 표·CID 회로/서명 이미지·첨부 원본과 추출 위치를 비교합니다. 암호화/DRM은 표준 parser 성공으로 간주하지 않고 원문 접근 adapter 필요로 기록합니다.
3. JIRA URL을 수동 등록하고 **읽기만** 수집합니다. 이슈 ID/키·담당·멘션 표현·댓글 전체 개수·새 댓글/수정·첨부 권한·닫힌 이슈를 실제 응답과 대조합니다.
4. 인증/권한 실패에서 서버가 paused 또는 오류 상태로 보이고 기존 댓글/첨부가 사라지지 않는지 확인합니다. 다른 등록 서버나 외부 첨부 호스트에 토큰이 전달되지 않아야 합니다.
5. 원본과 DB를 확인하고 history-only baseline을 마칩니다. 다음 poll에서 과거 댓글을 신규 처리하지 않는지 확인합니다.

실제 서버마다 응답 모양이 다르면 connector의 정규화만 변경하고 합성 회귀 테스트를 추가합니다. UI에 조회 성공이 보인다는 이유로 pagination/첨부까지 모두 확보했다고 판단하지 않습니다.

## 5. 사내 모델 확인과 점진 활성화

OpenCode 재설치/재로그인을 기본 작업으로 하지 않습니다. 사내 설치 버전의 `--version`, `run --help`, 지정 agent·도구 거부·출력 이벤트를 먼저 확인합니다.

```sh
.venv/bin/mail-jira --config config/corporate.toml live-smoke --model corporate-provider/model
.venv/bin/python scripts/evaluate.py --live --model corporate-provider/model --output runtime/corporate-evaluation.json
```

같은 합성 평가 항목을 집/사내 모델로 비교하고 분류 축, 수행 예정/완료, To/CC/지목, 적용 조건, 근거 위치, 누락/추가 질문, 금지 수치, 지연과 사람이 수정한 정도를 기록합니다. 합성 5개 항목은 작은 시작 평가이며 실제 문의의 정확도를 보장하지 않습니다.

그다음 이력 수집 → 새 변경 자동 분류 → 선택 문의의 수동 초안 → 자동 초안 순서로 활성화합니다.

```sh
# history_only=true로 baseline 수집
.venv/bin/mail-jira --config config/corporate.toml poll --once
# 이후 새 변경만 분류 대상으로. automatic_drafts=false 유지
.venv/bin/mail-jira --config config/corporate.toml poll --once --activate
.venv/bin/mail-jira --config config/corporate.toml worker --live
```

화면에서 실제 문의 몇 건의 분류를 직접 보정하고 **새 초안 요청**을 사용합니다. 수정/검토 이력이 새 원문이나 재생성에 보존되는지 확인한 뒤 `history_only=false`, 마지막으로 `automatic_drafts=true`를 검토합니다. 초안 검토와 실제 발송/완료를 분리해 운영합니다.

## 6. 예약 실행·백업·되돌리기

`config/systemd/`의 사용자 service/timer는 `%h/mail-jira` 설치 예제입니다. 실제 위치를 수정한 뒤 사용자 systemd에 설치합니다. WSL에서 systemd/로그인 후 유지가 가능한지 확인합니다. Windows 작업 스케줄러 등 다른 실행 방법을 선택하면 poll timer와 중복 활성화하지 않습니다. 지속 worker는 `worker --watch --live`를 사용합니다. 웹 서버에서 scheduler를 시작하지 않습니다.

실제 적용 전에 새 백업 경로와 새 복원 경로로 검증합니다.

```sh
.venv/bin/mail-jira --config config/corporate.toml backup /local-backups/mail-jira-before-activation
.venv/bin/mail-jira --runtime /local-restore-check/mail-jira restore /local-backups/mail-jira-before-activation
.venv/bin/mail-jira --runtime /local-restore-check/mail-jira serve --port 8001
```

문의/할 일/편집/검토/원본 다운로드를 비교합니다. 장애 시 poll/worker 예약 실행을 중지하고 운영 상태·백업을 확보합니다. 정상 snapshot을 **새 경로**에 복원하고 corporate runtime 경로를 그 경로로 바꾼 뒤 history-only로 점검합니다. 기존 DB에 덮어쓰는 복원은 제공하지 않습니다.

## 현장 완료 기록 (아직 미확인)

- [ ] 대상 OS/Python·wheel 설치·로컬 디스크·권한 확인
- [ ] 실제 수신/발신 EML·DRM·날짜·CID·첨부 대조
- [ ] 서버별 JIRA 인증·전체 댓글·멘션·첨부 권한/URL·갱신 대조
- [ ] 실제 GEK/Markdown 접근과 적용 조건 대조
- [ ] 사내 모델 live smoke·합성/실제 문의 평가·timeout/입력 조정
- [ ] localhost/포트 접근·무인 인증·예약 실행 유지 확인
- [ ] 실제 호스트 백업/새 경로 복원과 사용자 편집 보존 확인
- [ ] 소수 실제 문의의 수동 검토 후 단계적 활성화

모두 현장에서 검증한 항목만 체크합니다. 다른 PC에 공개하려면 사용자 인증·접근 제어·TLS·Host 정책을 별도로 설계해야 하며 현재 localhost 앱을 바로 외부 bind하지 않습니다.
