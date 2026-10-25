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
→ `{"ok":true,"cv_version":"5.0.0","backend":"opencv","arch":"aarch64","stubs":false}`

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
