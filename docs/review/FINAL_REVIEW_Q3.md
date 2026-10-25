# FINAL REVIEW Q3 — 제출 직전 최종 독립 재심사

READ-ONLY 검증 탭. 코드·데이터는 수정하지 않았다. 이 문서 + 새 테스트
(`tests/review/test_keys_q3_adversarial.py`, 5건)만 추가했다. 이전 보고를 믿지 않고
전부 직접 재현했다. 스캔한 개인·회사·프로필 식별자 단어는 이 문서에 적지 않는다(공개 저장소에 들어감).

판정 한 줄: **GO** — 치명(blocker) 발견 **0건**. 경미 2건(비차단).

---

## 1. 재현 (직접 실행)

| 항목 | 기대 | 실측 | 결과 |
|---|---|---|---|
| `uv run pytest -q` | 361 | **361 passed** (+ Q3 신규 5 → 366) | ✅ 일치 |
| web `npm run e2e` | 97/97 | **97/97 passed, 0 failed** | ✅ 일치 |
| web `npm run test:unit` | 7/7 | **7 pass, 0 fail** | ✅ 일치 |
| 심사자 문서 수치(DEVPOST/README/TECHNICAL_REPORT/CLAIMS_CHECK) | 361·97/97·7/7 | 전부 361·97/97·7/7로 기재 | ✅ 일치 |

문서 수치 불일치(심사자 비노출 내부 문서):
- `docs/submission/CHECKLIST.md` §2 "전체 테스트 266 통과", §5 "266 테스트, 148ms" — 현재 실측 **361 테스트·~178ms**. 내부 체크리스트의 잔존 수치이며 **심사자 대면 문서(DEVPOST_TEXT·README·TECHNICAL_REPORT·CLAIMS_CHECK)는 361로 최신**. (경미, 소유: 문서/A15)

---

## 2. 체험 키·IP 프라이버시 (가장 중요) — 코드+테스트로 직접 확인

근거 코드: `src/nunchi/service/keys.py`, `src/nunchi/service/app.py`(`_source_ip`, `_check_key`).
배포 API의 `POST /v1/keys`는 **호출하지 않음**(일일 한도 보존). 로컬 서비스·MemoryKeyStore·moto로만.
신규 반례 테스트 `tests/review/test_keys_q3_adversarial.py` (5건, 전부 통과):

| 공격 각도 | 확인 | 결과 |
|---|---|---|
| 원본 키 저장 안 됨 | 저장은 `KEY#sha256(key)`뿐(`hash_key`), put_item에 평문 키 없음 | ✅ |
| 원본 IP 저장 안 됨 | `IP#<HMAC-SHA256(ip)>#date`만, 솔트는 SSM SecureString `/nunchi/ip-salt` | ✅ |
| 원본 키·IP가 state/trace/EMF/응답에 전무 | 신규 테스트 `test_raw_key_and_ip_absent_everywhere`: 키 발급→세션→프레임을 라이브 스택에 흘리고 보유한 state store·trace·EMF stdout·프레임 응답에서 키/IP/키해시 전부 부재 | ✅ |
| `expires_at` **코드 비교**(TTL 의존 금지) | `validate()`가 `expires_at <= now`로 판정, 행 삭제 안 함. 신규 `test_expired_key_rejected_via_live_check_without_deletion`(라이브 401 `key_expired`) + `test_store_present_expired_row_and_ip_isolation`(행 잔존 확인) | ✅ |
| 만료 직후 키 거부 | 라이브 `/v1/sessions`에 만료 키 → 401 `{"error":"key_expired"}`(행 존재=`key_invalid` 아님) | ✅ |
| TTL 삭제 전 항목도 거부 | 행 `kh in store._keys` 남아있는데 `key_expired` 반환 | ✅ |
| `X-Forwarded-For` 위조로 우회 불가 | `_source_ip`는 API GW `requestContext.http.sourceIp`만 신뢰, XFF/X-Real-IP 무시. 신규 `test_forged_xff_cannot_bypass_per_ip_limit`: 매 호출 다른 위조 XFF라도 4번째 429 | ✅ |
| 같은 IP 4번째 429 | 신규 테스트 + 기존 `test_ip_daily_limit_http_429`(flat `ip_daily_limit`+retry_after_s+limit=3) | ✅ |
| 서로 다른 IP 격리 | 신규 `test_store_present_expired_row_and_ip_isolation` + 기존 `test_different_ips_isolated` | ✅ |
| 전역 6개 소진 시 503 | 신규 `test_global_cap_503_at_default_six`: **환경변수 미override(실제 기본 6)**로 6개 성공 후 7번째 503 `{"error":"capacity"}` | ✅ |
| 48h TTL | `IP_COUNT_TTL_S=48*3600`, `DAY_COUNT_TTL_S=48*3600` | ✅ |
| 원자적 카운터(버스트 우회 불가) | DynamoKeyStore `ADD n` + `ConditionExpression attribute_not_exists(n) OR n < :cap`; 기존 moto 테스트 `test_dynamo_keystore_caps_are_atomic` | ✅ |

기존 프라이버시 반례 계속 통과: `test_no_persist`(2), `test_privacy_q2_adversarial`(6), `test_privacy_no_frame_leak`(3) — 전부 green.

---

## 3. 표정 수치 (`overlay.expr`, V14)

| 확인 | 결과 |
|---|---|
| 감정 라벨 미생성(코드) | `src/nunchi/vision/expression.py`·`web/buddy.js`의 "emotion/행복/슬픔" 언급은 전부 **부정문**(라벨 안 만든다). 실제 분류 코드 0건 | ✅ |
| 감정 라벨 미생성(UI) | `web/i18n.js` "facial movement, not an emotion guess" / "감정을 추정하지 않아요" | ✅ |
| 감정 라벨 미생성(문서) | `FACE_EXPRESSION.md` "감정 추정이 아니다", `CLAIMS_CHECK.md` "not emotion inference" | ✅ |
| 응답에만, 저장 안 됨 | 기존 `test_overlay_expr.py`(state/trace/EMF/summary 부재, needle 반례) + V14 `tests/vision/test_expression_privacy.py` | ✅ |
| null 안전 | 5필드 각 `0..1|null`, 저신뢰(pose conf<0.3)→전필드 null, 보정 전 smile/brow=null, 정지영상 EAR 무변동→eye null | ✅ |
| 문서 한계 ↔ UI·Devpost 일치 | `FACE_EXPRESSION.md`(미소=기하 추정·실제 정확도 미측정·감정 아님) ↔ UI·DEVPOST("measured facial movement, not emotion") 일치 | ✅ |

---

## 4. 정직성

| 확인 | 결과 |
|---|---|
| 인형=얼굴+목 일관(UI) | `i18n.js`: "face + neck", "the neck is estimated ... We don't draw a body" / "몸은 그리지 않아요" | ✅ |
| 옛 "상체·팔·책상" 잔존 | 라이브 UI·`buddy.js`·`buddy-kinematics.js`에는 없음(W20이 torsoLean/armRaise 제거). `WEB_E2E.md`의 상체 서술은 **날짜 구분된 과거 섹션 §3c(W14)**이고 **§3h(W20)에서 명시적으로 폐기**("Removed: chest/belly, arms, hands, desk"). `BODY_POSE_FEASIBILITY.md`는 "미구현·후속" 문서. 현재 주장 아님 | ✅(경미) |
| 측정/추정/미측정 구분 | `CLAIMS_CHECK.md` 전 항목 태깅, `CONTRACTS.md` "어깨·몸통은 추정하지 않음", 목=labelled estimate | ✅ |
| 알림 9→5 합성 표기 | `ALERT_CALMING.md` "Synthetic scenario, NOT a real-use measurement" + DEVPOST/TECHNICAL "synthetic". 스크립트 `eval/agent/alert_calming.py` 직접 실행 → **Total alerts 9→5, Nudges 6→3, 첫 알림 180s 동일, 첫 반복 600s 지연** 재현 | ✅ |
| 데모 비교 "예시 데이터" 라벨 | `i18n.js` `historyExample: "Example data"/"예시 데이터"`, e2e가 데모에서 라벨 노출·localStorage 미기록 검증 | ✅ |
| Devpost "키 따로 전달" 낡은 문구 | **없음**. 자가발급 1버튼 "Get a trial key (30 min)", "no shared key", "3/day per IP, 6/day total"로 최신 | ✅ |

### CLAIMS_CHECK 무작위 12개 근거 대조 (10개 이상)

| # | 주장 | 대조 | 결과 |
|---|---|---|---|
| 1 | 361 테스트 | 직접 실행 361 | ✅ |
| 2 | e2e 97/97 · buddy 7/7 | 직접 실행 일치 | ✅ |
| 3 | 프레임 비저장 5 테스트 | no_persist 2 + no_frame_leak 3 = 5 | ✅ |
| 4 | 키 IP=3/GLOBAL=6/ISSUING | `cloud/template.yaml` L246·248·249 실측 | ✅ |
| 5 | 9→5 알림(합성) | 스크립트 실행 재현(§4) | ✅ |
| 6 | 머리 pose solvePnP | `headpose.py` solvePnP 5회 등장 | ✅ |
| 7 | no-diagnosis 가드(EN+KO) | `test_guardrails_deep.py` 17 테스트 통과 | ✅ |
| 8 | 22 결정 + 9 적대 시나리오 | `AGENT_EVAL.md` 시나리오 22·사람확인 9 | ✅ |
| 9 | 조용 기본·쿨다운 | policy/context + `test_calm_alerts.py` | ✅ |
| 10 | 표정=측정 아닌 감정 | §3 전수 확인 | ✅ |
| 11 | 지연 ~178–282ms/cold ~2.5s | `LATENCY.md` 워밍/콜드 섹션 존재(실측 기재) | ✅(문서상) |
| 12 | 자가발급 30분 키 | `template.yaml`+e2e W21+§2 신규 테스트 | ✅ |

---

## 5. 배포본 대조 (`docs/cloud/ENDPOINT.md` URL, 키 미사용·미출력)

| 확인 | 실측 | 결과 |
|---|---|---|
| `/healthz` key_issuing:true | `{"ok":true,"cv_version":"5.0.0","backend":"opencv","arch":"aarch64","stubs":false,"key_issuing":true}` | ✅ |
| 키 없음 401 | `POST /v1/sessions` → 401 | ✅ |
| `key_invalid` 401 | 잘못된 키 → `{"error":"key_invalid"}` 401 | ✅ |
| CORS preflight(x-anon-id, /v1/keys) | `OPTIONS /v1/keys` → 200, allow-origin=CloudFront 도메인, methods GET,OPTIONS,POST, headers content-type,x-anon-id,x-api-key | ✅ |
| 데모 200 | `GET /?demo=1` → 200 | ✅ |
| 웹 파일 sha(소스 대비) | app.js·buddy.js·buddy-kinematics.js·i18n.js·api.js·index.html **6/6 sha256 MATCH** | ✅ |

배포 키는 사용/출력하지 않았다.

---

## 6. 공개 저장소 (`git clone` HEAD **30ea238** 확인)

| 확인 | 결과 |
|---|---|
| 최신 커밋 = 30ea238 | ✅ (brief 지정과 일치) |
| 커밋 작성자 noreply | ✅ 최근 5커밋 전부 `*@users.noreply.github.com` |
| AWS 계정 ID(12자리) | **0건**(배포 스크립트는 런타임 `sts get-caller-identity`로 받아 `***last4`로 마스킹) | ✅ |
| 액세스 키/시크릿/토큰/PEM | **0건**(AKIA/secret/BEGIN/ghp_/AIza 등 전무) | ✅ |
| 홈 경로 `/Users/..`·`/home/..` | **0건** | ✅ |
| `web/config.json`·모델·영상 바이너리 | **커밋 안 됨**(.gitignore가 config.json·models/*.onnx·*.bin·node_modules·.venv·*.real.json 커버) | ✅ |
| 개인·회사 식별 정보 | 실명·회사명·이메일 **0건**. 노출된 식별자는 (a) 공개 저장소에 내재한 **GitHub 소유자 핸들**(repo URL·LICENSE 저작권·noreply 이메일, 7건 전부 이 범주) — 공개 저장소상 불가피·비밀 아님 | ✅ |

### 발견 (경미, 비차단)

- **F1 (경미, 소유: cloud 탭)**: 공개 저장소에 AWS **프로필 이름**이 플레이스홀더가 아닌 **리터럴**로 41회 존재(`cloud/deploy.sh`·`destroy.sh`·`cloud/README.md`·`agent/smoke_llm.py`). `CLAIMS_CHECK.md`는 "docs는 `<aws-profile>`로 지칭"이라고 적었으나 실제 코드/스크립트엔 실제 프로필명이 남음. **비밀 아님**(로컬 CLI 별칭·계정/자격 미노출)이나 주장과 코드가 어긋남. 수정 원하면 cloud 탭이 리터럴→`<aws-profile>` 치환. 제출 차단 아님.

---

## 7. 제출 체크 (사용자 몫 정리)

`docs/submission/CHECKLIST.md` + Devpost 요건 대조. **자동 검증 가능 항목은 전부 통과.** 남은 것은 전부 사람(U) 작업:

- [U] Devpost 참가 등록·로그인, 소속/팀 소개 문구(1인+에이전트 보조 정직 표기)
- [U] ≤5분 영상 촬영·업로드(공개/미등록): `docs/video/*` 대본·샷리스트·자막·가이드 준비됨. 로그아웃 상태 열람·길이 ≤5:00 확인
- [U] 실제 라벨 클립 녹화(`eval/record_clips.py`) 후 VISION_EVAL 채움 — 현재 비전 정확도는 "미측정"으로 정직 표기됨(차단 아님)
- [U] 심사 키 전달: Devpost 노트에 평문 키 금지 → 라이브 페이지 자가발급 버튼 안내 또는 비공개 필드
- [U] 기술 보고서 다이어그램 자리표시자 2곳 그림 삽입, PENDING 3건(실클립/COOL/제출절차) 한계로 명시
- [U] Best Use of COOL: AMI 전용이라 Lambda zip 구조로 불가 — 구독 안 하면 폼에서 미선택
- [U] 제출 후 11/10 `cloud/destroy.sh`로 스택 정리, 비용 확인

### 제출 전 권고(선택, 비차단)
- 내부 `CHECKLIST.md`의 "266 테스트/148ms"를 361/~178ms로 갱신(심사자 비노출이라 차단 아님).
- 원하면 F1(프로필 리터럴)을 플레이스홀더로 치환.

---

## 판정

| | |
|---|---|
| **결정** | **GO** |
| 치명(blocker) | **0건** |
| 경미(비차단) | 2건 — F1(공개 repo 프로필 리터럴), 내부 CHECKLIST 수치 잔존(266/148ms) |
| 미검증 | 비전 행동인식 실클립 정확도(설계상 "미측정" 정직 표기), COOL(구조상 불가), 실사용 종단 추세(미측정 표기), 배포 `POST /v1/keys`(한도 보존 위해 의도적 미호출 — 로컬/moto로 대체 검증) |

재현·프라이버시(키/IP)·표정·정직성·배포 대조·공개 저장소 모두 직접 확인했고 치명 결함을 찾지 못했다.
남은 항목은 전부 사람 작업(영상·등록·클립)이거나 정직하게 "미측정"으로 표기된 한계다. **제출 진행 가능.**
