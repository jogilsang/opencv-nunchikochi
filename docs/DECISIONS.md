# Project decisions (public summary)

| # | Decision | Status |
|---|---|---|
| D1 | Labelled clips for vision accuracy are recorded locally with `eval/record_clips.py`; face video is never committed (`eval/clips/` is git-ignored). Until recorded, per-behaviour accuracy is reported as "unmeasured". | open |
| D2 | Best Use of COOL: not pursued. COOL is distributed as an AWS Marketplace AMI, while this service ships as a Lambda zip. | closed (not pursued) |
| D3 | Repository is public. Models are Apache-2.0 / permissive (see `models/MANIFEST.json`, `docs/review/Q1_REPORT.md` licence table). | done |
| D4 | A review endpoint (API Gateway + Lambda arm64) is kept until 2026-11-10 and then destroyed with `cloud/destroy.sh`. Budget guard: CloudWatch request-spike alarm, reserved concurrency 5. | approved |
