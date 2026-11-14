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
