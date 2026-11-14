# Windows 0.3 검증 추가

2026-11-14 · Windows 10 build 19045 x64, CPython 3.12.3. 전체 **55 passed**, 합성 평가 **5/5**, ruff/pip check 통과. Windows EXE의 WebView2 DOM·메뉴 이동·중복 실행·worker kill/restart·정상 종료·재기동 데이터 유지를 확인했습니다. 실제 WSL OpenCode 2.3.0의 독립 stdin 합성 smoke도 근거 검증을 통과했습니다. 사내 DRM/JIRA나 모델 정확도 성공을 뜻하지 않습니다. 상세와 재현 명령은 [진행 기록](progress.md)을 확인하세요.

아래는 참조 0.2의 Linux 검증 이력입니다.

# 검증 결과와 평가 범위

2026-11-14 · Linux/WSL CPython 3.14.4. 일반 검증은 합성 데이터·가짜 runner이며 실제 사내/모델 연결을 사용하지 않습니다.

## 자동 검증

`python -m pytest -q`: **45 passed**, Starlette/httpx TestClient deprecation 경고 1건. `ruff check src tests scripts` 통과. 브라우저는 선택 Playwright/Chromium 158로 실제 저장·검토·재로딩·수동 상태 변경·모바일·로컬 자산만 요청하는지 확인했습니다.

| 계획 시나리오 | 자동 검증의 근거 | 실제 모델/현장 평가 경계 |
|---|---|---|
| S01~S02 | EML→분류→KB→조건 확인 draft, KB 발췌/적용 조건/누락 검증 | 기술 답변 정확도와 필요한 질문은 실제 모델 평가 필요 |
| S03 | 본인 별칭·To/CC·발신 방향이 AI snapshot에 전달됨 | 직접 지목/CC 의미 판단의 정확도는 미평가 |
| S04 | 예정/수행 fake 사례, 기존 action 참조와 완료 미확정 | 실제 문장별 완료 증거 판단은 미평가 |
| S05~S06 | 파일 이동/중복, reply와 바뀐 제목, 다중 action, 충돌 Message-ID 보존 | 애매한 업무 연결은 사용자 확인 |
| S07~S10 | 링크 발견 후 알림 제외, 두 서버 같은 키, 새 알림 없는 댓글 갱신, 미등록 서버·첨부 실패 | 실제 인증/서버 응답 미확인 |
| S11~S13 | HTML 표/링크, 인용문·서명 복원, CID와 안전한 preview, CSV/텍스트 PDF/스캔 PDF/DOCX/XLSX/PPTX·깨진 첨부 | OCR/회로 이미지/DRM은 미지원 |
| S14 | 실제 subprocess의 timeout·빈/잘못된 출력·비정상 종료, bounded retry와 secret 정제 | 실제 OpenCode/모델 이벤트 미확인 |
| S15 | heartbeat·단일 worker, 실제 프로세스 SIGKILL/lease 만료 복구, 늦은 token 결과 거부 | 장기 현장 scheduler 운영 미확인 |
| S16~S17 | 새 reply stale·검토/수정 보존, 최초 baseline 후 신규만 작업 등록 | 현장 폴더의 파일 안정화 시간 조정 필요 |
| S18~S19 | 관련 KB 없음/적용조건 근거 없는 technical answer 거부, 큰 문의 실패 격리 | 실제 공정 불일치 의미 판단은 미평가 |
| S20~S21 | 수동 분류/완료 이력 보존·재확인, 재생성별 후보, 실행 중 원문/KB 변경 stale·낡은 편집 409 | 다중 사용자 서비스는 범위 밖 |
| S22 | SQLite snapshot+blob/checksum, 새 경로 복원·편집/원본 유지·손상 거부 | 사내 실제 저장장치 복원 훈련 필요 |
| S23 | 긴 댓글의 여러 HTTP page, 부분 total/필드 실패 시 snapshot 유지 | 실제 서버 pagination/첨부 권한 대조 필요 |
| S24 | 초안 검토 후 inquiry 자동 완료 없음 | 실제 발송/답변 여부는 사람/보낸메일 근거로 관리 |

## 합성 모델 비교

`tests/fixtures/model-evaluation.json`은 S01/S02/S04 예정/S04 수행/S18의 5개 고정 입력과 필수 축/안전한 answer_mode를 정의합니다.

```sh
.venv/bin/python scripts/evaluate.py
.venv/bin/python scripts/evaluate.py --live --model provider/model --output runtime/live-evaluation.json
```

FakeRunner 결과: **5/5**. 이는 계약·평가 실행기의 작동 확인이며 모델 정확도 수치가 아닙니다. 보고서에는 `accuracy_claim=false`가 기록됩니다. 실제 모델 평가·사내 모델 비교·실제 문의의 근거 적합성/수정량 평가는 수행하지 않았습니다.

## 브라우저 검증

```sh
.venv/bin/mail-jira --runtime runtime/browser-demo demo
.venv/bin/mail-jira --runtime runtime/browser-demo serve --port 8765
# 별도 터미널. 선택 설치: pip install playwright; python -m playwright install chromium
.venv/bin/python scripts/browser_smoke.py
```

검증 스크립트는 합성 초안을 수정하므로 폐기 가능한 runtime에서 실행합니다. 개발 WSL의 그래픽 라이브러리가 부족해 `/tmp`에 별도 해제한 GBM 라이브러리와 로컬 폰트를 사용했고, headless 단일 프로세스 실행으로 캡처했습니다. 앱 runtime 의존성에는 브라우저/Playwright가 포함되지 않습니다. 외부 요청과 JS/CSP 오류가 없으며 390px 모바일 가로 넘침이 없었습니다. 최종 캡처는 `runtime/browser-review/`입니다.

## 미확인 항목

실제 OpenCode 모델 호출·agent/permission 제한, 실제 사내 메일/JIRA/GEK, 다른 OS/Python wheel, 사내 scheduler·장기 부하·운영 백업 복원은 미검증입니다. 이 항목을 합성 테스트 통과로 완료 처리하지 않습니다.

## 배포물 격리 검증

`dist/corporate-kit-0.2.0`에서 새 venv에 `pip install --no-index --find-links wheelhouse -r requirements-test.lock mail-jira-assistant==0.2.0` 실행, `pip check` 통과. import 경로가 새 venv의 site-packages임을 확인한 뒤 **45 tests passed**, repo 밖 작업 디렉터리에서 package demo 수집 1/작업 4, 합성 평가 **5/5**를 확인했습니다. 이 결과는 Linux CPython 3.14용이며 사내 호스트 설치 결과가 아닙니다.
