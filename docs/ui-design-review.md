## 승인한 5개 탭·AI 작업 공간의 실제 앱 반영 (2026-11-15)

프로토타입 승인을 받아 프로젝트 목록 / 연결 검토 / 프로젝트 추가 / AI / 작업 이력을 실제 FastAPI HTML/CSS/JavaScript 앱에 연결했다. 직접 입력의 모든 필드를 저장하고, JOB 폴더 가져오기 메뉴/API를 제거했다. 연결 검토는 기존 근거/단서/직접 연결을 유지하며 AI 작업 공간으로 요청을 이어간다. 독립 프로토타입 파일은 설계 참고용으로 보존하며 앱에서 로드하지 않는다.

새 AI 탭은 실제 worker/OpenCode를 사용한다. 생성·수정은 서버에서 같은 반영 로직을 savepoint로 검증한 뒤 변경안만 저장하고, 사용자가 이름·메타데이터·내용을 편집해 반영할 때 프로젝트/원문 버전·범위·근거를 다시 검사한다. 반영 전 프로젝트/연결/변경 이력에는 쓰지 않는다. 사용자 편집은 이력 입력에 보존하며 재반영은 중복 저장하지 않는다. 검색 결과는 제공된 프로젝트 ID만 허용하고 검색 요청의 내용 변경을 거절한다. 공통 내용과 기존 이슈를 함께 수정할 수 있으며, 상세의 기존 공통/선택 이슈 AI 경계는 유지한다. DB 스키마를 바꾸지 않고 기존 JSON 요청에 기본값을 제공한다.

MASTER·검토 기록과 이미 읽은 두 SKILL 원문을 기준으로, 원본 HEAD f6b76575f949707b4e3c37cd86cb44b0b98643e8 / 6ae86f61f520d6ca229d2f40e070410638c908c5를 재확인하고 Taste system/copy, UI UX quick-reference의 입력·탐색 기준을 다시 활용했다. Taste의 실제 업무 내용·같은 정렬선·기존 로컬 토큰/서체·구체적 행동 문구를 채택했다. UI UX Pro Max 검색 `asynchronous request error recovery --domain ux -n 3`에서 Error Recovery / Error Messages / Error Placement를 확인하고, 입력 곁 오류·처리 중/완료 피드백·다시 작성/작업 이력 복귀를 적용했다. deep-linking/state-preservation 기준으로 요청·변경안 URL, 탭 필터 및 작성 중 요청/생성 입력/변경안 편집 보존을 적용했다. 짧은 메타데이터는 한 줄 입력, ISO 날짜는 날짜 선택기, 목적/Spec/기록은 여러 줄 입력으로 구별했다.

전체 디자인 방향을 바꾸지 않아 domain 검색만 실행했다. 다른 프레임워크·외부 폰트·CDN·런타임 UI 라이브러리는 추가하지 않았다. 업무 앱과 승인 시안에 필요하지 않은 사진·히어로·무작위 팔레트·WebGL·장면 효과·마케팅 gate는 적용하지 않았다. 승인된 새 공통 탐색/변경안 규칙은 MASTER에 반영했다.

Computer Use로 실제 샘플 앱의 AI 요청→worker 처리→변경안 직접 편집→DB 반영→프로젝트의 변경 전후/이력 보존을 확인했고, 실제 앱 AI 화면을 열어 두었다. 사용자 업무 DB는 테스트에 쓰지 않았다. 별도의 Edge 자동 검증에서 320/390/768/1024/1440px × 5개 탭과 AI 결과 4종 = 45개 조합, 키보드 건너뛰기/포커스·보이는 라벨·긴 한국어·수평 넘침·생성 저장/재로딩·필수 오류·수정안 편집/반영·검색/빈 결과·조건부 생성/수정·대상 선택·추가 정보·worker 실패/복귀·동시 변경 거절·작업 이력·필터 보존을 통과했다. 페이지 JavaScript 오류와 외부 요청은 0건이었다. 한 줄/날짜 입력 보완 뒤 390/1440px의 생성/수정 4개 조합과 변경안 편집 후 새로고침 보존/날짜 저장도 추가 검증했다. 기존 대비 토큰을 재사용했고 점검한 텍스트 대비는 4.5:1 이상이며 전체 접근성 인증은 아니다.

공통 `scripts/ui_review.py`도 별도 샘플 서버에서 36개 화면/너비와 초안·수행 기록 저장/재로딩을 통과했다. pytest 120개, Ruff, JS 구문 검사, diff whitespace 검사를 통과했다. 실제 OpenCode로 읽기 전용 검색과 기존 대상을 찾아 프로젝트 일정/기존 cell 이슈를 함께 수정하는 변경안 생성·반영을 검증했다. 일반 UI/실패 테스트는 합성 runner이며 실제 모델의 모든 자연어 정확도를 평가한 것은 아니다.

브라우저 결과: `runtime/project-directory-review-1794745474546081600/verification.json`, `general/report.json`, `final-controls.json`, `final-update-1440.png`, `final-create-390.png`. 실제 모델 결과: `runtime/project-directory-live-1794745155963245900/verification.json`. 새 배포물 `dist/WorkTrail-project-ai-tabs/WorkTrail/WorkTrail.exe`의 실제 WebView2 4개 메뉴, 5개 프로젝트 탭/AI 변경안 생성·반영, 기존 프로젝트/이슈, 중복 실행 방지, worker 복구, 종료 시 서버 종료와 재실행 데이터 보존은 `runtime/project-directory-native-20261115/verification.json`에서 통과했다.

---

## 5개 탭·AI 작업 공간 프로토타입 개정 (2026-11-15)

사용자의 후속 요청으로 `prototypes/project-create/`를 프로젝트 목록 / 연결 검토 / 프로젝트 추가 / AI / 작업 이력의 5개 탭으로 바꿨다. JOB 폴더 가져오기 UI·이벤트·전용 스타일을 제거했고, 프로젝트 추가에는 직접 입력만 남겼다. AI를 독립 작업 공간으로 옮겨 자유 요청, 대상 직접 선택/요청에서 찾기, 선택 참고 문의와 생성·업데이트·검색·기존 대상 유무에 따른 처리 결과 예시를 제공한다. 변경 전후/생성안을 직접 편집하고 ‘예시 반영’하면 이 미리보기의 목록과 이력에만 반영된다. 실제 AI·앱 API·DB·실행 파일은 연결하거나 변경하지 않았다.

MASTER와 이전 검토 기록, 두 SKILL 원문과 기준 HEAD `f6b76575f949707b4e3c37cd86cb44b0b98643e8` / `6ae86f61f520d6ca229d2f40e070410638c908c5`, Taste system/copy, UI UX quick-reference의 폼·탐색과 pro-rules의 적용 범위를 다시 확인했다. Taste의 업무 내용 중심, 동일 정렬선·기존 토큰/서체, 구체적인 행동 문구를 채택했다. 요청과 결과는 나란히 두되, 공통 일정과 cell 이슈 변경은 별도 구역으로 표시한다. 원래 아래에 길게 쌓이던 요청 예시는 입력 근처의 짧은 버튼으로 줄였다.

UI UX Pro Max 검색 `navigation feedback user control --domain ux -n 3`의 결과는 Keyboard Navigation / Breadcrumbs / Feedback Loop였다. 키보드 탐색과 보이는 포커스를 채택하고, 결과 직접 편집과 ‘요청 수정’으로 반복할 수 있게 했다. 현재 구조는 한 단계의 탭 탐색이므로 3단계 이상의 breadcrumb는 추가하지 않았다. thumbs up/down 평가 위젯은 화면 흐름 검토 목적에 필요하지 않아 추가하지 않았다. quick-reference의 deep-linking/nav-state-active/state-preservation, input-labels/error-placement/focus-management/submit-feedback을 적용했다. 기존 WorkTrail 디자인의 개별 탐색·입력 개선이므로 전체 디자인 시스템 생성과 다른 프레임워크 가이드는 사용하지 않았다. 업무 앱이므로 히어로·사진·랜덤 팔레트·WebGL·장면 효과·마케팅 gate는 적용하지 않았다. 외부 폰트·CDN·런타임 의존성도 추가하지 않았다.

Computer Use의 실제 브라우저에서 5개 탭, AI 요청 예시, 기존 프로젝트 일정/하위 이슈 변경 전후, 예시 반영→변경된 목록→작업 이력, 작은 화면의 한 열 배치를 확인했다. 입력 영역과 예시 버튼을 줄여 작은 창에서 예시를 더 빨리 찾도록 다듬었다. 기본 창 크기로 복원하고 AI 변경안 화면을 열어 두었다. 별도 자동 검증 중 참고 문의의 원문뿐 아니라 제목도 연결 단서에 포함해야 하는 문제를 수정했다.

Edge 검증: 320/390/768/1024/1440px × 5개 탭 및 AI 결과 4종 = 45개 조합의 수평 넘침·현재 위치·제목·보이는 라벨을 통과했다. 작은 화면의 주요 조작 높이도 확인했다. 직접 입력 필수 오류/첫 입력 포커스/요약/입력 유지, AI 필수 오류·준비 중/완료, 수정안 편집→예시 반영→목록/이력, 신규안 오류/편집/반영, 새 예시 검색과 대상 선택, 자동 일치→수정/불일치→생성, 검색 빈 상태→생성 요청, 대상 충돌/추가 정보와 복귀 포커스, 참고 문의, 뒤로 가기/검색 유지, 건너뛰기/현재 경로 보존, 긴 한국어와 사용자 문자열 이스케이프를 확인했다. JavaScript 오류 0건, 요청은 로컬 정적 자산 GET만 있었고 외부 요청/앱 API 호출은 0건이었다. 점검한 본문/보조문/강조색 대비는 4.5:1 이상이며 전체 접근성 인증은 아니다. 실제 AI 응답의 정확성이나 서버 장애는 검증 대상이 아니다.

결과: `runtime/project-ai-preview-review-1794744016338721800/verification.json`, `final-ai.png`, `ai-create-1440.png`, `ai-update-1440.png`, `ai-search-1440.png`, `ai-auto-1440.png`, `long-korean-390.png`. `node --check`와 `git diff --check`도 통과했다. 본앱 공통 레이아웃 변경이 없어 `scripts/ui_review.py`·앱 기능 테스트·Windows 빌드는 다시 실행하지 않았다. 프로토타입 단계이므로 MASTER의 공통 규칙은 유지한다. 아래 생성 전용 화면 기록은 이전 시안이며 현재 구성은 이번 개정과 `project-navigation-proposal.md`를 따른다.

---

## 생성 전용 화면 프로토타입 (2026-11-15)

사용자 요청에 따라 기존 작업 전체를 먼저 `b4e3ad5`로 커밋했다. 이후 `prototypes/project-create/`에 별도 HTML/CSS/JavaScript 미리보기를 만들었다. 기존 앱의 CSS 토큰과 shell만 참조하며 본앱의 라우트·JS·DB·실행 파일은 바꾸지 않는다. 프로젝트 목록/연결 검토/작업 이력, 추가 전용 화면의 직접 입력/AI로 정리/JOB 폴더 가져오기, 작성 내용 요약과 생성 후 화면 예시를 제공한다. 데이터는 합성 예시이고 입력은 메모리에서만 유지한다. 사용자 범위에 맞춰 실제 저장·AI 호출·파일 선택/읽기는 연결하지 않았다.

두 SKILL 원문과 기준 HEAD `f6b76575f949707b4e3c37cd86cb44b0b98643e8` / `6ae86f61f520d6ca229d2f40e070410638c908c5`를 확인하고 Taste system/copy, UI UX quick-reference의 폼·탐색 기준을 읽었다. Taste의 동일 정렬선·토큰/서체 재사용·업무 내용 중심·행동을 정확히 이름 짓기를 채택했다. 반복 생성 카드 대신 같은 위치의 방식 탐색을 사용하고 선택 입력은 접어서 시작한다. 사용자 요청이 업무 화면 미리보기이므로 사진·히어로·랜덤 팔레트·효과·마케팅 gate는 적용하지 않았다.

UI UX Pro Max 검색 `form field grouping progressive disclosure --domain ux -n 3`에서 Error Placement / Submit Feedback / Form Labels가 반환되었다. 입력별 보이는 라벨, aria-describedby로 연결한 오류와 첫 오류로의 포커스, 실제 저장 성공과 구별한 미리보기 결과를 채택했다. 필드 그룹/선택 정보 접기/뒤로 가기·입력 보존은 quick-reference의 field-grouping/progressive-disclosure/back-behavior/state-preservation 기준을 사용했다. 기존 디자인 방향을 유지하는 개별 폼 개선이므로 전체 디자인 시스템/다른 프레임워크 가이드는 생성하지 않았다.

실제 브라우저에서 먼저 프로젝트 이름 입력이 짧게 보이던 폭을 수정했다. AI/폴더 방식으로 바꿀 때 이전 수동 입력이 새 결과처럼 보이지 않게 요약 상태를 분리했다. hash 탐색 중 건너뛰기 링크가 생성 화면을 벗어나지 않도록 수정했다. Computer Use에서도 생성 전용 화면 접근, 직접 입력 예시와 요약, AI 요청 화면을 직접 확인하고 미리보기 탭을 남겼다.

Edge QA: 320/390/768/1024/1440px × 목록/연결/이력/직접 입력/AI/폴더 = 30개 조합의 수평 넘침·보이는 라벨·접근성 제목을 확인했다. 검색/빈 상태, 필수 오류와 포커스, 실시간 요약과 사용자 문자열 이스케이프, AI 예시→수정→생성 후 화면, 폴더 예시→결과, 브라우저 뒤로 가기와 입력 유지, 건너뛰기와 현재 화면 보존, 긴 한국어를 검증했다. 점검한 본문/보조문/사이드바의 대비는 4.5:1 이상이며 전체 접근성 인증은 아니다. JavaScript 오류 0건, 외부 요청 0건, 요청은 정적 자산 GET만 있었고 앱 API 호출은 0건이었다.

최종 결과: `runtime/project-create-preview-review-1794742576021394400/verification.json`, `final-create.png`, `list-1440.png`, `ai-1440.png`, `import-1440.png`, `long-korean-390.png`. 본앱 공통 레이아웃 변경이 없어 `scripts/ui_review.py`와 기존 기능 테스트/Windows 빌드를 다시 실행하지 않았다. 프로토타입은 새 공통 디자인 규칙의 확정이 아니므로 MASTER는 유지했다.

---

## 문의함 필터·출처 / 프로젝트 연결 검토 (2026-11-15)

두 원본 체크아웃 HEAD f6b76575f949707b4e3c37cd86cb44b0b98643e8 / 6ae86f61f520d6ca229d2f40e070410638c908c5를 다시 확인하고 두 SKILL 원문과 Taste system/copy, UI UX quick-reference의 탐색 지침을 읽었다. Taste의 실제 콘텐츠·동일 체계·행동을 정확히 이름 짓는 기준에 따라 빈 `[]`와 검색하지 않은 결과의 단정을 제거하고 실제 선택/연결 행동을 제공했다. 업무 화면이므로 사진·히어로·랜덤 팔레트·애니메이션·마케팅 gate는 적용하지 않았다.

UI UX Pro Max에서 `navigation tabs drawer forms --domain ux -n 4`를 실행했다. Sticky Navigation / Keyboard Navigation / Breadcrumbs / Back Button 중 키보드 조작과 복귀 경로를 채택하고 추가 고정 탐색은 도입하지 않았다. drawer와 전용 화면 판단은 quick-reference의 nav-hierarchy/modal-vs-navigation/state-preservation을 근거로 했다. `color not only status --domain ux -n 3`의 Color Only와 Submit Feedback을 채택해 출처 텍스트를 유지한 색상 배경, 연결 중 피드백·오류·저장 후 완료 안내를 제공했다. 다른 프레임워크 가이드·외부 폰트·CDN은 추가하지 않았다.

실제 실행 중인 사용자 DB를 읽기 전용으로 확인했다. 기존 연결 대기 10건은 모두 광고/공지/참조/중복 Jira 알림의 예전 분류이며 프로젝트 필드가 없고 업무 축은 모두 no였다. 기존 로직은 unknown을 프로젝트 관련으로 간주하고 빈 기본 단서를 보존했다. 새 후보 필터로는 이 10건이 0건이며 문의/원문을 삭제하지 않는다. worker가 다시 평가하는 파생 대기 행만 정리한다. 답변이 필요 없더라도 명시적인 프로젝트 업데이트/결정/일정/수행 근거가 있으면 후보로 유지한다.

이번 반영: 요약 클릭→상태/재검토 초안 필터 적용, 검색 시 최신성 유지, 출처 배경색, Jira/받은 메일 필터 구분, 후보 선정 이유/원문 근거/식별 단서, 실제 기존 프로젝트 선택과 연결. 새 연결 API는 존재하는 프로젝트 ID와 원문 revision을 검사하고 트랜잭션으로 저장/작업 요청/감사 기록을 처리한다. 성공 후 프로젝트 변경 검토로 이동하며 완료 안내를 표시한다. 목록/연결 검토/작업 이력 탭 및 생성 전용 화면 분리는 구현이 아닌 별도 검토안 `docs/project-navigation-proposal.md`다.

검증: pytest 전체 112개, Ruff, diff whitespace 검사 통과. `scripts/inbox_connections_review.py`는 320/390/768/1024/1440px × 4화면 = 20개 조합과 요약 링크 4종, 재검토 검색 유지, 색상 구분, 키보드, 후보 근거, 직접 연결·완료 안내, 오래된 원문 오류, 제외/빈 상태를 확인했다. 공통 `scripts/ui_review.py`의 36개 조합·초안/수행 기록 저장·재로딩도 통과했다. 출처 색상 쌍의 최저 대비는 6.73:1이며 페이지 JavaScript 오류/외부 요청은 0건이다. 전체 WCAG 인증은 아니다. AI 작업 응답은 FakeRunner 합성 데이터로 검증했다.

Computer Use의 내장 브라우저에서도 실제 요약 클릭 후 선택값/목록 변화, 넓은 화면의 Jira/받은 메일 배경색, 재검토 조건 표시, 기존 프로젝트 선택→연결→해당 프로젝트 이동을 확인했다. 작은 화면에서 요약 링크는 두 열로 유지하고 기본 창 크기로 복원했다.

결과: `runtime/inbox-connections-review-1794741178770495000/verification.json`, `general/report.json`, `inbox-1440.png`, `connections-1440.png`, `connection-error.png`. 새 Windows 배포물 `dist/WorkTrail-inbox-projects/WorkTrail/WorkTrail.exe`의 실제 WebView2 4개 메뉴/프로젝트·이슈 페이지, 중복 실행 방지, worker 재시작, 앱 종료 시 서버 종료, 재실행 기록 보존도 별도 샘플 데이터에서 통과했다: `runtime/inbox-connections-native-20261115/verification.json`. 실행 중 기존 앱과 업무 DB는 수정하지 않았다.

---

## 프로젝트 작업 공간 재구성 (2026-11-15)

Taste Skill과 UI UX Pro Max의 원본 체크아웃 HEAD를 각각 `f6b76575f949707b4e3c37cd86cb44b0b98643e8`, `6ae86f61f520d6ca229d2f40e070410638c908c5`로 확인하고 두 SKILL 원문, Taste system/copy, UI UX quick-reference와 pro-rules의 적용 범위를 읽었다. FastAPI HTML/CSS/JavaScript와 WebView2를 유지했다.

Taste의 실제 콘텐츠 우선, 같은 정렬선·간격·서체·색상 체계, 반복 카드와 상투적인 문구 축소를 채택했다. 본문 위에 쌓이던 AI 이력·내보내기·관리 도구를 별도 탭으로 옮겼다. 프로젝트 공통 내용과 cell 이슈 본문을 분리하고, 개요는 목적/진행/결정/다음 액션과 기본 정보로 읽도록 구성했다. 사진·히어로·랜덤 팔레트·WebGL·장면 효과·마케팅 gate는 업무 앱의 읽기/편집 목적과 맞지 않아 적용하지 않았다.

UI UX Pro Max 검색을 실제 실행했다.

- `progressive disclosure hierarchy navigation --domain ux -n 4`: Breadcrumbs, Heading Hierarchy, Sticky Navigation, Font Size Scale. 프로젝트 목록→프로젝트→이슈의 위치와 복귀 경로, 제목 단계와 서체 위계를 채택했다. 추가 고정 탐색은 도입하지 않았다.
- `progressive disclosure --domain ux -n 3`: Heading Line Balance만 반환되어 점진적 노출의 근거로 채택하지 않았다. 점진적 노출은 quick-reference의 progressive-disclosure/field-grouping/content-priority 지침을 사용했다.
- `keyboard focus modal --domain ux -n 3`: Focus States, Focus Not Obscured (Enhanced/Minimum). native dialog의 입력 포커스, Escape 종료, 원래 버튼으로 복귀와 보이는 포커스를 검증했다. AAA 인증을 주장하지 않는다.

검색·12개 단위 페이지 이동·독립 이슈 상세·내용 옆 직접/AI 편집을 제공한다. 800px 이하의 이슈 전환은 보이는 라벨의 select로 줄였다. 프로젝트 AI 요청에는 공통 본문과 이슈 목록을, 이슈 요청에는 선택한 본문만 전달하며 서버에서 범위 밖 변경과 동시 편집 충돌을 막는다. AI 폼은 요청 중 버튼 비활성화와 입력 곁 상태/오류를 표시한다.

Computer Use: Windows sky 창 캡처가 `FrameArrived timed out`, `window capture timed out`으로 실패하여 CUA 내장 브라우저로 전환했다. 기존 화면을 직접 본 뒤 이슈 검색 위치/내용 밀도/모바일 탭 간격을 조정했다. 합성 cell 이슈의 직접 편집·저장, AI 요청·처리 중·반영 후 같은 이슈 복귀, 390px 선택 상자로 다른 cell 이동, 1440px 개요/상세를 실제 화면으로 확인했다. 기본 크기로 복원하고 최종 개요 탭을 남겼다.

검증: 전체 pytest 106개와 Ruff 통과. `scripts/project_workspace_review.py`에서 320/390/768/1024/1440px × 9화면 = 45개 조합의 넘침·메뉴·보이는 라벨, 검색/페이지 이동, 긴 한국어 저장·재로딩, 이슈 추가/내용 추가, 개요 수정, dialog 포커스/Escape, 빈 입력/AI 로딩/범위 반영, 확인/되돌림, 빈 상태를 통과했다. 공통 `scripts/ui_review.py`의 36개 조합과 초안·수행 기록 흐름, JavaScript 오류 0건·외부 요청 0건도 통과했다. 본문/보조문/강조/경고 토큰의 해당 배경 대비는 최저 5.68:1이다. 전체 WCAG 감사는 아니다. AI 동작은 FakeRunner 합성 응답으로 검증했으며 실제 모델 판단을 새로 평가하지 않았다.

최종 브라우저 결과: `runtime/project-workspace-review-1794710344434326100/verification.json`, `general/report.json`, `final-overview.png`, `final-issue.png`. 기존 프로젝트 변경 검토 smoke와 AI 프로젝트 smoke도 새 탐색에 맞춰 통과했다. 새 배포물 `dist/WorkTrail-project-workspace/WorkTrail/WorkTrail.exe`의 실제 WebView2 4개 메뉴, 프로젝트/이슈 상세, 중복 실행 방지, worker 복구, 종료 뒤 서버 종료, 재실행 데이터 보존을 별도 샘플 데이터로 통과했다: `runtime/project-workspace-native-20261115-final/verification.json`. 업무 DB와 실행 중 기존 앱은 변경하지 않았다.

---

## 0.5 AI 프로젝트 생성·업데이트 (2026-11-15)

`runtime/ui-skills/taste`와 `runtime/ui-skills/ux`의 HEAD가 각각 기존 기준 커밋 f6b7657 / 6ae86f6임을 확인하고 두 SKILL 원문 및 Taste system/copy, UI UX quick-reference를 읽었다.

UI UX Pro Max에서 `form asynchronous feedback undo confirmation --domain ux -n 3` 검색을 실행했다. Confirmation Messages, Submit Feedback, Confirmation Dialogs 결과 중 요청 직후 버튼 비활성화, 입력 곁 로딩/성공/오류, 분명한 완료 상태를 채택했다. 별도 사전 승인 대화상자는 사용자 합의한 자동 반영/사후 확인과 충돌하므로 도입하지 않았다. 되돌리기는 이력과 버전 검사로 복구를 제한하며 파괴적 삭제를 제공하지 않는다.

Taste에서는 실제 요청·문의 제목 중심, 기존 정렬선과 간격/서체/색상 토큰, 구체적인 행동 문구, 펼쳐 보는 변경 전후를 채택했다. 히어로·사진·랜덤 팔레트·장면 효과·마케팅 gate는 업무 앱 맥락과 프로젝트 기준에 따라 적용하지 않았다. FastAPI HTML/CSS/JS를 유지하고 다른 프레임워크 지침·외부 폰트·CDN을 추가하지 않았다.

실제 Edge: 생성→내용 확인→업데이트→되돌리기, 빈 입력 오류, 긴 한국어 내용, 키보드 건너뛰기, 미확인/확인/되돌림, 보이는 라벨, 320/390/768/1440px의 새 화면 8개 조합에서 넘침을 점검했다. 기존 색상 토큰을 재사용했고 새 대비 인증은 수행하지 않았다. `scripts/ui_review.py` 공통 36개 화면/너비·저장/편집/탐색·외부 자산 0건도 통과했다. JavaScript 오류 0건. 최신 결과: `runtime/ai-project-review-1794707505972398700/verification.json`, `general/report.json`, `detail.png`. UI는 실제 업무 DB가 아닌 폐기 가능한 합성 서버에서 확인했다.

---

# Taste Skill / UI UX Pro Max 검토와 적용

## 0.4.1 실무 화면 통합

두 원문과 MASTER를 다시 읽고 UI UX Pro Max의 `dense table line height --domain ux -n 3` 검색에서 본문 행간·표 넘침 지침을 확인했다. 본문 1.5배, 표 영역 내 스크롤과 반응형 레이블을 채택했다. Taste의 실제 콘텐츠 중심·중복 문구 제거·같은 정렬선 원칙에 따라 상단 경로/설명을 제거하고 시스템 상태를 sidebar 하단으로 옮겼다. 마케팅용 히어로·사진·애니메이션은 적용하지 않았다.

독립 업무일지/초안 메뉴를 제거하고 업무 기록을 프로젝트 문맥에 포함했다. 실제 브라우저에서 메뉴 4개, main 안의 상태 배너 부재, sidebar 상태 존재, 행 높이 36.75px와 본문 행간 1.5, 수평 넘침·키보드 이동·입력 라벨·저장/재로딩을 점검했다. 기록·초안·AI 제안 기능을 보존하면서 새 화면 12개 + 공통 36개 화면/너비 조합을 검증했다. 최종 결과와 inbox/message/project PNG는 `runtime/project-review-1794664527313607900/`에 보존했다.

---

## 0.4 프로젝트 변경 검토 화면

같은 기준 커밋의 두 원문을 `runtime/ui-skills/`에 받아 다시 읽었다. UI UX Pro Max에서 `review changes error feedback --domain ux -n 3` 검색을 실행했고 Error Recovery, Error Feedback, Error Messages 결과가 프로젝트 변경 검토에 적합함을 확인했다. 실패 뒤 재생성/운영 상태 경로, 입력 주변 오류, role=alert/status를 채택했다. Taste에서는 실제 업무 내용·변경 비교 중심, 기존 정렬·간격·서체 유지와 실제 브라우저 확인을 적용했다. 사진·히어로·애니메이션·마케팅 gate는 기존 WorkTrail 기준에 따라 적용하지 않았다.

AI 변경은 기존 warning 토큰과 텍스트로 표시하고, 항목별 수정 입력·근거 펼치기·확정/반려·선택 묶음 검토를 제공한다. 브라우저 smoke에서 320/390/768/1440px의 새 화면 12개 조합, 키보드 건너뛰기, 보이는 라벨, 넘침, 수정 후 확정·반려를 확인했다. 공통 UI 회귀 42개 조합과 초안/업무 기록 저장·재로딩도 통과했다. 결과는 `runtime/project-review-1794660896654951300/`에 보존했다. 기존 대비 토큰을 재사용했으며 새 화면 전체의 WCAG 인증을 수행한 것은 아니다.

---

검토일: 2026-11-14. 기존 상태: Git 저장소가 없어 `main`을 초기화하고
기존 제외 설정을 유지한 채 소스 90개 파일을 `8c9b2d9`에 보존했다.
실행 데이터, venv, 빌드 산출물은 기존 `.gitignore`에 따라 제외했다.

## 원본과 판단

| 원본 | 검토한 커밋 | 판단과 채택 범위 |
|---|---|---|
| [Taste Skill](https://github.com/Leonxlnx/taste-skill) | `f6b76575f949707b4e3c37cd86cb44b0b98643e8` (tasteskill 2.5.1) | 시각적 일관성, 실제 콘텐츠 중심, 명확한 문구와 브라우저 확인 기준을 채택 |
| [UI UX Pro Max](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill) | `6ae86f61f520d6ca229d2f40e070410638c908c5` | 제품에 맞는 스타일 선택, 접근성·탐색·폼·반응형 지침과 검색 도구를 채택 |

둘 다 UI 프레임워크가 아닌 에이전트용 지침이다. 원본은 검토용 임시 폴더에
받아 읽었으며, 글로벌 스킬·자동 실행 hook·런타임 의존성은 설치하지 않았다.
사용자가 요청한 장점별 선별 적용을 우선했다. 원본 코드나 자산은 앱에 복사하지 않았다.

Taste의 최신 주된 대상은 회사·제품 홍보 웹사이트다. 전체 화면 히어로,
사진 할당, 랜덤 팔레트, WebGL, 장면 효과와 마케팅 전용 검증 gate를 업무 앱에
그대로 적용하면 목적과 충돌한다. 따라서 전체 워크플로를 실행했다고 주장하지 않으며,
공통 시각 원칙과 실제 브라우저 확인을 이 프로젝트의 기존 구조에 맞췄다.

UI UX Pro Max의 다음 검색을 실제 실행했다.

```text
search.py "productivity workspace desktop minimal" --design-system -p WorkTrail --density 8 --variance 2 -f markdown
search.py "badge chip label wraps" --domain ux -n 2
```

첫 결과의 **Minimalism & Swiss Style**은 업무 앱에 적합했다. 같은 결과에 포함된
Product Demo + Features 랜딩페이지 패턴은 제외했다. 추천된 밝은 teal/orange 색상과
온라인 Plus Jakarta Sans 폰트 대신, 로컬 한국어 가독성과 차분한 업무 맥락을 위해
채도를 낮춘 녹색과 시스템 폰트를 선택했다. 두 번째 검색에서는 짧은 상태 라벨을
한 줄로 유지하고 레이블이 잘리지 않도록 하는 기준을 채택했다.

## 반영 결과

- 공통: 밝은 탐색 영역, 일관된 SVG 선 아이콘, 한국어 메뉴 그룹,
  정확한 현재 위치 표시, 상단 경로, 건너뛰기 링크, 공통 색상 토큰과 포커스.
- 문의함·초안: 장식 문구 제거, 통계 카드 대신 요약 줄, 목록 건수,
  보이는 검색 라벨, 상세 필터와 초기화, 모바일에서 줄어드는 열.
- 오늘: 실제 개수와 빈 상태, 과도하게 늘어나지 않는 영역, 펼쳐 읽는 제안 내용.
- 업무일지: 날짜·내보내기·추가 행동 구분, 두 열 입력 폼,
  빈 기록 안내, 접을 수 있는 Markdown 가져오기, 상태 한국어 표기,
  연결 문의가 없는 수동 기록에서 잘못된 링크 제거.
- 프로젝트·운영: 입력 라벨, 빈 프로젝트 안내, 표 영역의 수평 스크롤.
- 동작: 기존 저장·복사·검토·재생성·분류·업무 상태 API 계약을 유지했다.

유지할 디자인 기준은 [MASTER.md](../design-system/worktrail/MASTER.md)에 기록했다.

## 검증과 실행

기존 기능 테스트 60개 통과. 마지막 기록 표시 변경 후 관련 테스트 8개도 통과했다.
Ruff 검사 통과. 실제 Edge로 7개 화면을
320/375/390/768/1024/1440px에서 점검해 42개 조합 모두 통과했다. `scripts/ui_review.py`는
현재 메뉴·입력 라벨·수평 넘침·건너뛰기·모션 감소·검색과 상세 필터·초안
저장/재로딩/검토 완료·업무일지 저장까지 통과했으며 화면과 JSON 결과를 저장했다.
페이지 JavaScript 오류와 외부 자산 요청은 0건이었다.
문의함의 보조 텍스트·상태 라벨·주요 버튼·메뉴·폼 라벨 80곳을 실제 계산된 색상으로
검사했으며, 최저 텍스트 대비는 5.18:1이었다. 이 값은 앱 전체의 자동 접근성 감사 결과가 아니다.

```powershell
.venv/Scripts/python.exe scripts/ui_review.py --channel msedge --url http://127.0.0.1:8767
```

이 명령은 실행 중인 **폐기 가능한 샘플 서버**를 대상으로 사용한다.
기본 UI 검토 결과는 `runtime/ui-redesign/review/`에 저장된다.
이 점검은 완전한 WCAG 인증이나 모든 보조기기 검증을 의미하지 않는다.

Windows 빌드는 `dist/ui-refresh/WorkTrail/WorkTrail.exe`에 별도로 생성했다.
`scripts/desktop_smoke.py`로 실제 WebView2의 다섯 기본 화면 로딩, 중복 실행 방지,
워커 강제 종료 후 복구, 앱 종료 후 서버 종료, 재실행 후 기록 보존을 검증했다.
결과: `runtime/ui-redesign/native-smoke/verification.json`.
기존 실행 중인 앱은 편집 내용을 저장하고 종료한 뒤 새 실행 파일로 실행한다.
