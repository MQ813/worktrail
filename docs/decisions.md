# 구현 선택

- P0/P1의 Python·FastAPI·Pydantic·SQLite 구조를 이어받았습니다. 미사용 추상 계층을 늘리지 않고 service/storage/web, connector/document/knowledge/AI 교체 모듈로 분리했습니다. 화면은 서버 렌더링과 로컬 CSS/JS이며 Node 빌드나 CDN이 필요 없습니다.
- P1 DB를 migration 1~4로 올리면서 원본·초안·편집·작업 이력을 보존합니다. 메일은 content-addressed source, 대화는 별도 inquiry 연결, JIRA는 서버+키로 식별합니다. 확실하지 않은 Message-ID 병합은 하지 않습니다.
- 미처리 revision 재조회로 poll 중간 종료 후 작업 등록을 복구합니다. 최초 baseline 이전 이력은 자동 활성화하지 않습니다. 자동 초안 여부와 실제 모델 호출을 별도 opt-in으로 나눴습니다.
- AI는 구조화 제안만 반환하고 저장/완료/채택은 프로그램과 사용자가 담당합니다. 재생성 요청은 UUID별 작업으로 기록하고 사용자 편집본을 덮어쓰지 않습니다. review 완료와 실제 업무 완료를 분리합니다.
- 모델 프롬프트/계약은 코드 version 2로 유지합니다. 정확한 토큰 계산 대신 문자 예산과 보수적 제외/실패 경로를 사용합니다. 무근거 technical_answer는 검증에서 거부하지만 의미상 정확성은 실제 모델 평가 대상입니다.
- PDF는 선택 의존성 pypdf, Office는 제한된 ZIP/XML 읽기를 사용합니다. 별도 추출 프로세스에 시간·메모리·압축 해제 상한을 적용합니다. OCR/DRM/이미지는 원본과 해석 필요 상태를 보존합니다.
- 기본 JIRA HTTP는 urllib 기반 read-only v2/v3 Bearer입니다. redirect/다른 origin에 인증을 보내지 않습니다. 불완전 필드/댓글 응답을 삭제로 해석하지 않습니다. 다른 사내 인증은 adapter 변경 대상으로 명시했습니다.
- 키워드 KB는 재현 가능한 경로/해시/정확한 발췌를 반환합니다. 적용 공정의 의미 일치는 검색 점수만으로 확정하지 않습니다. technical_answer의 적용 조건·근거를 별도 요구합니다.
- scheduler는 웹 프로세스와 분리합니다. poll/worker CLI와 systemd 사용자 unit을 준비했고 현장 OS에 맞는 실행 방식 한 가지만 선택합니다.
- 실제 모델 호출은 별도 opt-in 원칙을 유지했습니다. 설치/로그인 변경·실제 사내 연결·메일 발송·JIRA 쓰기는 수행하지 않았습니다.
