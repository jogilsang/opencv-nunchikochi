# 공통 규칙 (모든 탭)

## 소유 범위 (다른 탭 소유 경로는 직접 수정 금지 — 보고서에 "○○ 탭에게 요청: …")
| 탭 | 영역 | 경로 |
|---|---|---|
| **V (vision)** | OpenCV 5 파이프라인, 모델, 평가 | `src/nunchi/vision/`, `vision/`, `models/`, `eval/`(clips 제외 스크립트), `tests/vision/` |
| **C (cloud)** | 서비스, IaC, 배포, 벤치(COOL), 관측성 | `src/nunchi/service/`, `cloud/`, `tests/service/`, `docs/ARCHITECTURE.md`의 클라우드 절 |
| **A (agent)** | 결정 루프, 도구, trace, 리포트, 에이전트 평가 | `src/nunchi/agent/`, `agent/`, `tests/agent/` |
| **W (web)** | 웹 클라이언트, UX, 리포트·공유 카드, 데모 에셋 | `web/`, `docs/assets/` |
| **지휘자 (Claude)** | 계약·문서·보고서·통합·검증·제출물 | `src/nunchi/contracts.py`, `docs/`(위 예외 제외), `README.md`, `pyproject.toml`, `uv.lock`, `tests/fixtures/`, `tests/test_contracts.py`, `tests/e2e/` |

## 금지 (어기면 작업 반려)
- `git push`, `git reset --hard`, `git add -A`/`git add .`, `git commit -a`. 커밋은 `git -C <repo> commit -m "…" -- <소유 경로>`만. 커밋 메시지는 Conventional Commits(영문 소문자 명령형).
- 다른 탭 소유 경로 수정, `contracts.py` 수정(필요하면 CONTRACT-CHANGE 요청).
- **영상·이미지를 디스크·S3·로그·trace·테스트 산출물에 저장**(합성/공개 샘플 이미지는 `eval/`·`tests/` 예외, 사용자 얼굴 영상은 `eval/clips/` 로컬 전용·gitignore).
- AWS 리소스 생성은 **C 탭만**, 프로필 `captain`, 리전 `us-east-1`, 이름 접두사 `nunchi-`, 태그 `project=nunchikochi`. IAM 광범위 권한·퍼블릭 S3 쓰기·비용 큰 리소스 금지. 삭제 계획 명시. 다른 탭은 AWS에 쓰지 않는다(읽기도 필요 시 C 탭에 요청).
- 새 의존성은 **소유한 dependency-group**에만 정확한 버전으로 추가하고 보고서에 적는다. `uv.lock`은 커밋하지 않는다(지휘자가 체크포인트마다 고정).
- 무거운 명령(전체 pytest 반복, 모델 대용량 추론 배치, docker build)은 `nice -n 15` 로 한 번에 하나. 이 노트북은 4개 탭이 같이 쓴다.
- 비밀·키·계정 ID를 코드·문서·로그에 쓰지 않는다.

## 작업 방식
- 시작: `docs/CONTRACTS.md`, `docs/ARCHITECTURE.md`, 자기 브리프(`_briefs/<ID>.md`)를 읽는다. 새 지시는 브리프 파일 경로로 온다.
- 작은 단위로 커밋(소유 경로만), **단계마다 300자 이내 보고**(무엇을 했고 어떤 수치·증거가 있는지, 막힌 것, 다른 탭에게 필요한 것).
- 테스트는 정상 2·예외 2·오류 1 이상, 동작 기준, 외부 의존성은 mock. pytest, 린트 `ruff`.
- 숫자는 **직접 돌린 값만** 보고한다. 추측·기억으로 정확도/지연을 쓰지 않는다. 측정 명령과 결과 파일 경로를 함께 적는다.
- 막히면 30분 안에 보고하고 다음 작업으로 넘어간다. 완료하면 BACKLOG의 자기 항목을 `[x]`로 하지 말고(지휘자가 확인 후 체크) 보고서 맨 위에 `DONE <ID>` 를 쓴다.
- 대기하지 말 것: 완료 보고 뒤 다음 지시가 올 때까지 자기 영역의 `docs/BACKLOG.md` "자율 라운드" 항목을 진행한다.

## 품질 기준 (세계 수준의 최소선)
- 공개 데모에서 **실패가 보이지 않을 것**: 예외는 사용자 친화 상태로 변환, 지연·품질 불량·카메라 거부·네트워크 끊김 처리.
- 재현성: 새 머신에서 `uv sync && uv run pytest` 와 문서의 배포 명령으로 동작.
- 정직성: 정확도·성능은 측정값과 한계(실패 사례 포함)를 함께 쓴다. 대회 규칙은 **오해를 일으키는 주장**을 실격 사유로 둔다.
