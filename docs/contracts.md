# WorkTrail 0.3 추가 계약

schema v5는 기존 Inquiry/Action/Draft에 project, activity, evidence, edit/import 이력을 추가합니다. 수행 제안은 classify 성공과 같은 transaction에서 저장되며 분류를 다시 호출하지 않습니다. 확정 수행에는 실제 수행일이 필수이며 AI/초안 검토는 완료를 확정하지 않습니다. 중복 대표만 집계하고 분류의 source/revision과 사용자 편집본을 각각 보존합니다.

`GET/POST /api/activities`, `PUT /api/activities/{id}`, `GET /api/activities/{id}/history`, `GET /api/worklog/{date}/export`, `POST /api/worklog/import`, `POST /api/projects/link`. Record는 description/performed_on/project/inquiry_id/action_id/status/version/duplicate_of/minutes/complete_action을 사용합니다. status는 needs_review/confirmed/excluded이고 완료 연결은 confirmed + action_id + 명시 확인이 필요합니다. 충돌/잘못된 연결은 409입니다.

문서 adapter는 status/text/locations/warnings를 반환하고 source adapter는 headers도 반환합니다. 빈 본문은 extract_failed, 이미지나 첨부 미해석은 partial입니다. COM은 helper의 STA에서만 실행하며 timeout으로 해당 helper만 종료합니다. Word active-session adapter는 새로 연 readonly 문서만 닫고 사용자 문서/프로그램은 종료하지 않습니다.

OpenCode runner는 ai_prefix/ai_global_args/ai_input으로 교체합니다. Windows native는 .exe를 사용하고 shell shim은 거부합니다. 긴 입력은 설치된 버전에서 검증한 stdin을 사용합니다. 독립 WSL 실행에는 standalone 및 Linux timeout을 함께 설정합니다. Windows에서는 AI 자식 tree만 Job Object로 관리합니다. 실제 모델의 의미적 정확도는 별도 평가 대상입니다.

아래는 유지되는 0.2 계약입니다.

# 실행·저장 계약 (0.2)

## 교체 경계

- `HTTPJira` / `FixtureJira`: `fetch(issue_key)`는 완전한 이슈 스냅샷, `download(url)`은 바이트를 반환합니다. 공통 workflow는 API별 인증/페이지 모양에 의존하지 않습니다. 실제 JIRA는 GET·HTTPS·지정 origin·redirect 거부·timeout·응답 상한을 적용합니다. API v2/v3 Bearer 기본이며 특수 인증은 adapter를 교체합니다.
- `MarkdownKnowledge`: `overview / search / find / read / related`. 참조는 상대경로+SHA256이며 경로 밖 읽기를 거부합니다. 검색은 키워드 순위이고 의미 유사도나 적용 공정 일치를 보장하지 않습니다.
- `AiRunner`: `classify(Request) -> Classification`, `draft(Request) -> Draft`. Fake/OpenCode가 같은 Pydantic 계약을 사용하며 `extra=forbid`입니다.

## AI 입력·출력

Request는 source_ref·제목·최신 본문·제한된 과거 대화/첨부·방향·To/CC·본인 별칭·수동 판단/메모·현재 할 일·revision·KB와 누락 정보를 포함합니다. 예산 초과 시 과거 대화/문서는 사유를 기록하고 제외합니다. 최신 질문 자체가 너무 크면 개별 작업을 실패 처리해 다음 문의로 진행합니다. 문자 상한을 보수적 입력 예산으로 사용하며 모델별 정확한 토큰 계산은 하지 않습니다.

분류는 네 축의 yes/no/unknown, 검토 필요, 본문 근거, 여러 Action, 누락 정보를 반환합니다. 근거 source_ref/segment와 발췌가 실제 입력에 있어야 합니다. Action은 todo/performed/waiting, 담당·기한·근거·기존 action ID 연결 후보를 가집니다. 다른 문의의 action ID를 참조할 수 없습니다. **AI 수행 증거는 완료 확정이 아닌 제안**입니다.

초안은 answer_mode, 제목/본문, KB 참조·정확한 발췌·적용 조건, 누락/한계를 반환합니다. technical_answer는 실제 지식 근거, applicable=true와 조건, 완전한 coverage와 누락 없는 입력을 요구합니다. 이는 스키마·출처 검증이며 문장 의미나 모든 수치의 정답을 증명하지 않습니다. 실제 모델/사람 평가가 필요합니다.

OpenCode는 `run --format json --agent plan` 기본값을 사용합니다. 이벤트의 text `part.text`만 합친 후 애플리케이션 JSON을 다시 검증합니다. prompt version 2, 분류/초안 모델 설정을 분리합니다. stdout 1MiB 제한, 저장 로그 각 최대 64KiB, timeout 시 Unix 프로세스 그룹 종료, 독립 입력·세션 비재사용, 알려진 환경 secret 값 정제를 적용합니다. attempt에 입력·결과·정제 로그·시각을 저장합니다. 실제 설치 버전의 이벤트/권한 호환성은 live 미검증입니다.

## 영속성·상태

SQLite migration 1~4. 기존 P1의 초안/편집/작업을 보존하고 원본 기준 revision을 bootstrap합니다. migration은 원자 트랜잭션이며 source/message/thread/revision/작업 조회 index를 둡니다.

메일 source ID는 원본 바이트 SHA256, JIRA ID는 server_id+issue_key 해시입니다. 메일 References/In-Reply-To로 대화를 묶고 source→inquiry 연결을 별도로 관리합니다. 같은 Message-ID의 다른 바이트는 충돌 확인 대상으로 보존합니다. revision은 입력 snapshot을 보존하며 event는 댓글 추가/수정/삭제·상태·담당·본문 변경과 수동 연결을 기록합니다. JIRA 페이지/필드가 불완전하면 이전 snapshot을 유지합니다. 메타데이터만 바뀐 이슈는 자동 초안을 만들지 않습니다.

작업 중복 키는 `(inquiry, kind, input_revision, request_id)`이며 자동 작업 request_id는 빈 문자열, 수동 재분류/재생성은 고유 UUID입니다. 단일 worker 잠금과 heartbeat, lease·attempt token·현재 lock owner를 확인한 결과만 채택합니다. 일시 오류/잘못된 JSON·스키마는 최대 3회, 근거/예산 검증 실패는 즉시 failed입니다. 수동 재시도는 감사 기록을 남깁니다.

초안 review와 freshness는 독립입니다. 편집 version 충돌은 409이고, 재생성 결과는 후보 이력에 추가합니다. editing/reviewed/archived 본문은 AI가 덮어쓰지 않습니다. 새 원문/KB 변경, 실행 중 입력 변경은 stale입니다. 수동 분류는 해당 revision에 적용하며 새 원문이면 재확인을 표시합니다. 새 요청은 이전 수동 완료 이력을 보존하면서 needs_review로 재개합니다.

첫 history-only 수집 source는 baseline입니다. poll의 재조회 가능한 미처리 revision에서 작업을 만들므로 수집 직후 종료되어도 다음 poll이 등록합니다. AI 실패는 수집 cursor를 되돌리지 않습니다. 파일 이동·재수집은 바이트 해시로 중복되지 않습니다.

## 웹 API

- `GET /api/inquiries`, `GET /api/operations`, `GET /inquiries/{id}`.
- `POST /api/inquiries/{id}/classify`, `/regenerate`: 작업 등록.
- `PUT /api/drafts/{id}`: `{version, body, review}`; review는 editing/reviewed/archived.
- `POST /api/draft-versions/{version_id}/adopt`: `{version}`; 후보 명시 채택, 변경된 KB 후보는 409.
- `POST /api/inquiries/{id}/override`: `{revision, state, note}`.
- `POST /api/inquiries/{id}/classification`: `{revision, response_expected, action_required, work_performed, waiting_for_others, note}`.
- `POST /api/actions/{id}`: `{version, state}`.
- `POST /api/sources/{id}/link`: `{target: inquiry_id | null}`; null은 별도 문의로 분리. 원본/기존 초안/판단 이력은 삭제하지 않습니다. 문의별 상태·편집본을 자동 병합하지 않습니다.
- `POST /api/jira`: `{url}`, `POST /api/jira/{id}/{pause|resume|refresh}`.
- `POST /api/jobs/{id}/retry`.

모든 변경은 JSON·동일 origin을 요구하고 localhost Host만 허용합니다. CSP로 외부 자산·inline script·frame을 제한합니다. 원문 HTML은 실행하지 않고 첨부는 다운로드가 기본이며 안전한 raster MIME의 CID만 inline 표시합니다. 인증 없는 localhost 전용이며 사내 공개 서비스 인증을 대신하지 않습니다.
