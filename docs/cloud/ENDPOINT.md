# nunchi — deployed endpoints (captain / us-east-1)

Stack `nunchi`, deployed 2026-10-22 (C3), public entry point changed to API Gateway in C3b.
Kept until **2026-11-10**, then `cloud/destroy.sh --apply`. No account id, no API key here.
The API key lives only in SSM SecureString `/nunchi/api-key`.

| what | value |
|---|---|
| Web (CloudFront) | https://dhys8dgxlvbgx.cloudfront.net |
| Service API base (**API Gateway HTTP API**) | https://54hlt77s4k.execute-api.us-east-1.amazonaws.com |
| CloudWatch dashboard | `nunchi-service` (us-east-1) |
| DynamoDB table | `nunchi-sessions` |
| Lambda function | `nunchi-service` (arm64/Graviton, python3.12) |
| API key | SSM SecureString `/nunchi/api-key` (header `X-Api-Key`) — never in this repo |

Health (public, no key): `curl https://54hlt77s4k.execute-api.us-east-1.amazonaws.com/healthz`
→ `{"ok":true,"cv_version":"5.0.0","backend":"opencv","arch":"aarch64","stubs":false,"key_issuing":true}`

## Public entry point: API Gateway (Function URL was org-SCP-blocked)

C3 found the public **Lambda Function URL** (AuthType NONE) is denied (403) by an
organization SCP on this member account. C3b (conductor-approved, same stack/region/prefix/
tags) swapped the public entry point to an **API Gateway HTTP API** (`nunchi-api`,
payload 2.0, `$default` route → Lambda AWS_PROXY). The Function URL resource was removed;
Lambda invoke is now permitted only from this API's ARN (principal apigateway.amazonaws.com,
SourceArn scoped). **Public `/healthz` now returns 200** — the SCP allows public API Gateway.
App-level `X-Api-Key` (SSM) is unchanged; API Gateway default throttle rate 20 / burst 40;
CORS limited to the CloudFront domain + localhost dev origin. Access logs carry minimal
fields only (requestId/time/ip/method/path/status/len/latency) — no body, no headers, no key.

## C14 — anonymous multi-session history + trend (2026-10-23)

Same stack/region/prefix/tags; **service code only** (Lambda updated, template unchanged,
no new resource — DynamoDB key format extended only). Mem 1536 / timeout 15 / reserved
concurrency 5 / cost alarm all unchanged.

- New request header **`X-Anon-Id`** (browser-held random hex token, 16–64 chars) on the
  mutating + summary routes. Added to CORS `Access-Control-Allow-Headers`
  (`X-Api-Key, X-Anon-Id, Content-Type`). Missing/malformed token ⇒ "no-record mode"
  (that session is simply not stored — never an error).
- "Same user" is linked only by that token's **SHA-256 hash, first 32 hex** →
  `USER#<hash>`. The raw token is never written to the table or logs.
- `POST /v1/sessions/{id}/end`: response `summary` now carries `timeline`
  (`{bad_posture:{5m,10m,30m,60m}, per_hour_rate}`, numbers only) and `report` carries
  `trend` (A11 `compare`, using the user's last ≤5 sessions). Persists a numbers-only
  daily summary at `USER#<hash>` / `DAY#<date>#<session-id>` (TTL 30 days); same-day
  repeats use a distinct sort key (full session id), so they do not overwrite.
- `GET /v1/summary?date=`: now returns `{summary, previous, history:[≤5 oldest-first]}`
  (back-compat: existing keys unchanged).
- Privacy: a strict key whitelist (`sanitize_summary`) drops any non-aggregate or
  image/landmark-looking key before the item is built, so pixel/coordinate data can never
  reach the USER#/DAY# table.

## C15 — web (W16/W17) redeploy + CORS allows X-Anon-Id (2026-10-23)

Same stack/region/prefix/tags. Web static re-synced for W16 (calm alerts, posture-record
timeline) + W17 (real server fields: `report.trend`, `history`; anonymous `X-Anon-Id`
continuity). CloudFront `/*` invalidated.

- **API Gateway CORS fix**: the HTTP API's gateway-level CORS `AllowHeaders` was
  `content-type, x-api-key` — missing `x-anon-id`, so a browser preflight for a W17 request
  carrying `X-Anon-Id` would have failed. Template `CorsConfiguration.AllowHeaders` now adds
  `x-anon-id` (config change on the existing API; no new resource). Preflight
  `OPTIONS /v1/frames` (Origin = CloudFront) now returns
  `access-control-allow-headers: content-type,x-anon-id,x-api-key` and
  `access-control-allow-origin: https://dhys8dgxlvbgx.cloudfront.net`.
- `web/config.json` is apiBase only (no key); its apiBase matches the API whose CORS origin
  is the CloudFront domain.
- Lambda code / Mem 1536 / timeout 15 / reserved concurrency 5 / env (5 baseline vars) /
  SSM key / cost alarms all unchanged.

## C16 — web (W18/W19) redeploy (2026-10-23)

Same stack/region/prefix/tags. Web static re-synced for W18 (empty posture-record chart
collapses on short sessions) + W19 (short sessions still show the bad-posture count + bars,
with a "not comparable yet" note). CloudFront `/*` invalidated. All 16 deployable files
hash-match the source (mismatch 0). **No server/template/resource change** — `/healthz` 200,
no-key 401, CORS preflight still allows `x-anon-id`; `web/config.json` apiBase only.

## C17 — 30-minute trial-key issuing (2026-10-25)

Same stack/region/prefix/tags; **service code + template config only, no new resource
kind** (the DynamoDB item format is extended inside the existing `nunchi-sessions` table).
Judges no longer need a shared key: the live page's "Get a trial key" button calls a new
**public** endpoint that mints a 30-minute key. Abuse guards: per-IP **3/UTC-day**, global
**6/UTC-day** (user decision 2026-10-25, env `NUNCHI_KEY_GLOBAL_DAILY`, default 6). Mem
1536 / timeout 15 / reserved concurrency 5 / cost alarm / SSM master key all unchanged.

### API

- `POST /v1/keys` (**no key required**, empty body):
  - 200 `{"key":"<64 hex>","expires_at":"<ISO8601 Z>","ttl_s":1800,"remaining_today":<n>}`
  - 429 `{"error":"ip_daily_limit","retry_after_s":<to next UTC 00:00>,"limit":3}`
  - 503 `{"error":"capacity"}` when the global daily cap (6) is exhausted
- All other `/v1/*` routes still take `X-Api-Key`. A trial key that is **expired** → 401
  `{"error":"key_expired"}`; an unknown key → 401 `{"error":"key_invalid"}`. The SSM master
  key (`/nunchi/api-key`) stays valid for ops/local.
- `GET /healthz` (public) now also returns `"key_issuing": true` (the web uses this to show
  the button; a local service leaves it false and hides it).

### Privacy (what is stored)

- **IP**: only `requestContext.http.sourceIp` from API Gateway is trusted (never
  `X-Forwarded-For`). The raw IP is **never** stored, logged, or traced — only a keyed
  **HMAC-SHA256** of it (salt from SSM SecureString `/nunchi/ip-salt`, random if absent).
  The per-IP daily counter is `IP#<hash>#<YYYY-MM-DD>` (TTL 48h).
- **Key**: the plaintext key is never stored — only `KEY#<sha256(key)>` with `expires_at`.
  Validation compares `expires_at` **in code**; DynamoDB TTL deletion lags hours and is
  never trusted for correctness (the item carries a ~1h cushion past expiry).
- **Access logs**: the API Gateway access-log format **no longer carries the client IP**
  (the `ip` field was removed); it keeps only requestId/time/method/path/status/len/latency.
- Counters use an **atomic conditional increment** (`ADD n` with `n < cap`), so a concurrent
  burst can never push a count past the cap (no read-then-write race).

### Deploy + live verification (captain / us-east-1)

- Template diff (change set): Add `HttpApiKeysRoute` (`POST /v1/keys`), Modify `HttpApiStage`
  (per-route throttle rate 2 / burst 5 on `POST /v1/keys` + access-log format minus `ip`),
  Modify `ServiceFunction` (new env: `NUNCHI_KEY_ISSUING=1`, `NUNCHI_IP_SALT_PARAM`,
  `NUNCHI_KEY_IP_DAILY=3`, `NUNCHI_KEY_GLOBAL_DAILY=6`), Modify `ServiceRole`
  (+`dynamodb:UpdateItem` for the conditional counters, +`ssm:GetParameter` on the ip-salt
  param). **No replacements** — no data loss; DynamoDB table/CloudFront/alarms/concurrency
  untouched. New SSM SecureString `/nunchi/ip-salt` provisioned out-of-band (value never
  printed).
- Live curl: `/healthz` `key_issuing:true`; `POST /v1/keys` ×3 → 200 with
  `remaining_today` 2→1→0 and `ttl_s=1800`, 4th → **429 ip_daily_limit**; an issued key →
  `POST /v1/sessions` **200**; an invalid key → **401 key_invalid**; master SSM key →
  **200**, no key → **401**. The 30-minute **expiry** is proven by unit tests (clock
  injected), not by waiting live.
- DynamoDB scan after issuance: items are `KEY#<sha256>` (attrs `expires_at,ttl` only),
  `IP#<hmac>#<date>` (`n`), `DAY#<date>` (`n`) — **no raw IPv4, no raw key** anywhere.

### Honest limitations

- A **shared/NAT IP** (office, campus, conference Wi-Fi) shares the 3/day budget across
  everyone behind it, so colleagues may see `ip_daily_limit` sooner than expected.
- A **mobile** client whose IP changes (cell ↔ Wi-Fi) is treated as a new IP and may need a
  fresh key, but also gets a fresh 3/day allowance.
- A **bot flood from many IPs** can exhaust the global **6/day** cap; after that,
  `POST /v1/keys` returns 503 `capacity` until the next UTC day — but the **master-key path
  and the demo (no-camera) mode are unaffected**, so a judge can still be handed access.
- Deployed via `lambda update-function-code` after the change set, because the Lambda S3
  key is unchanged (the documented C3 gotcha): CloudFormation does not re-pull a same-key
  zip, so the code push is explicit.

## C19 — web (W20/W21/W22) redeploy (2026-10-25)

Same stack/region/prefix/tags. **Web static only, no server/template/resource change.**
Re-synced the W20 face+neck buddy, the expression redraw, and the one-button 30-min
trial-key UI (web commit d3cd8d3). CloudFront `/*` invalidated; all 33 deployable files
hash-match the CloudFront-served bytes (**mismatch 0**); `/` and `/?demo=1` 200. CORS
preflight for `POST /v1/keys` and `POST /v1/sessions` (Origin = CloudFront) both 200 with
the CloudFront origin + `content-type,x-anon-id,x-api-key`; `/healthz` 200 `key_issuing:true`,
no-key 401. Screenshots `docs/screenshots/c19-{demo-buddy,live-trialkey-button,mobile}.png`
(pageerror 0; `POST /v1/keys` not called — button presence confirmed by UI + `/healthz`).
One stale S3 object noted for a future cleanup: `e2e/capture-w14.mjs` (source removed;
`--delete` not used).
