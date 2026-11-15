# 프로젝트 탐색·AI 작업 공간 미리보기

실제 앱에 연결하지 않은 HTML/CSS/JavaScript 프로토타입이다.

- 프로젝트 목록 / 연결 검토 / 프로젝트 추가 / AI / 작업 이력의 5개 탭
- 직접 입력과 작성 내용 요약
- AI 자유 요청, 기존 대상 선택과 참고 문의
- 생성·기존 내용 수정·검색·찾아서 생성/수정의 결과 예시
- 생성안과 변경 전후 편집, 예시 반영 후 목록·이력 확인

JOB 폴더 가져오기는 제거했다. AI는 프로젝트 추가와 분리했다.
`index.html`을 브라우저로 열거나, 저장소 루트에서 정적 서버를 실행한다.

```powershell
.venv/Scripts/python.exe -m http.server 8796 --bind 127.0.0.1 --directory D:/codes/worktrail
```

미리보기: `http://127.0.0.1:8796/prototypes/project-create/index.html#/projects/ai`

기존 앱의 로컬 `app.css`와 이 폴더의 CSS만 사용한다.
외부 자산·API 호출·실제 AI·파일 읽기·DB 저장은 없다.
AI 결과는 키워드에 따른 합성 예시이며 일반적인 자연어 판단 기능은 아니다.
입력과 반영 내용은 메모리에만 있고 새로고침하면 초기화된다.
기존 실행 파일과 앱 코드는 변경하지 않는다.
