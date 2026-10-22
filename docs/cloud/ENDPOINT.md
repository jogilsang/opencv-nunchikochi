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
