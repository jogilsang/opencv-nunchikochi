# COOL — listing & competition research notes (C tab, read-only)

Research only: no Marketplace subscription, no deploy. Subscription is the user's call (U2).
Confirmed: 2026-10-22. Where a page was JS-rendered or unclear, it is marked **미확인**.

## What COOL is

Cloud Optimized OpenCV Library (COOL) — the first officially supported, cloud-optimized
build of OpenCV for **AWS Graviton (Arm64)**, from the OpenCV.org core team with AWS.
Optimizes core CV ops (resize, adaptive gaussian, contour detection, etc.).

| fact | value | source |
|---|---|---|
| Target hardware | AWS Graviton 2/3/4/5, Arm64 only | opencv.org/cool, aws-news |
| Delivery method | **Pre-built AMIs on AWS Marketplace** | aws-news (COOL framework) |
| Speedup (AWS benchmark) | **20–70% faster** than pip OpenCV on Graviton; avg ~**1.5x**; 78+ functions, most ≥1.2x, some 1.8x | aws-news, opencv.org press |
| Workflow example | image-analysis pipeline 1.2fps → 1.6fps (**~30%**) | aws-news |
| Pricing / trial | **7-day free trial**, then standard AWS billing (per listing) — exact $ **미확인**(Marketplace page is JS-rendered, no server HTML) | aws-news; Marketplace pp pages |
| Listings | separate per generation: "...For Graviton3", "...For AWS Graviton5", etc. | Marketplace prodview-5b2boxpyztidw / prodview-igdweaoo6prb6 |
| Version | **미확인** (listing version not readable without JS; likely tracks OpenCV 5.x) | — |
| pip / container / wheel delivery | **not offered** — AMI only (as of research date) | aws-news ("Pre-built AMIs … eliminate … compilation") |

Sources (accessed 2026-10-22):
- https://opencv.org/cool/ · https://opencv.org/cloud/
- https://aws-news.com/article/2026-04-10-accelerating-opencv-on-graviton-the-cool-framework
- https://aws.amazon.com/marketplace/pp/prodview-5b2boxpyztidw (Graviton3) ·
  https://aws.amazon.com/marketplace/pp/prodview-igdweaoo6prb6 (Graviton5) — JS-rendered, specifics 미확인
- https://aws.amazon.com/marketplace/seller-profile?id=seller-q3au5rsqt2mq6 (seller)

## Competition angle ("Best Use of COOL")

- OpenCV AI Competition 2026 (Aug 12–Oct 26). Special prizes **$1,000 each**: *Best Use of
  Cloud-Optimized OpenCV Library* and *Agentic Vision Award*. Top-50 proposals get a
  $150 AWS compute grant. (opencv.org press / opencv.org/cool "$200 grant" — 두 페이지가 $150/$200로 다름 → **미확인, 둘 다 기록**)
- Judging: innovation, technical execution, real-world impact, UX, documentation.
- Implied bar for the COOL prize: the **core CV workload runs on Graviton/Arm** with a
  **reproducible baseline measurement** showing the COOL vs standard-build difference.

## Fit vs our stack (the honest gap)

- Our service is **Lambda arm64 zip** with pip `opencv-python-headless==5.0.0.93` (C2).
  Lambda already runs on **Graviton** — so the "core workload on Arm" requirement is met.
- **But COOL ships as an AMI, not a pip wheel or container layer.** There is no supported
  way to drop COOL into a Lambda zip. Using COOL would mean an **EC2/AMI** (or, if a
  container image is ever offered, a Lambda-container) deployment path — a change from C2.
- Therefore a true "COOL build vs pip build" A/B is **not possible on the current stack**
  without standing up a Graviton EC2 from the COOL AMI (a subscription + deploy = U2, out
  of scope here).

## Decision input (see BENCH_PLAN / RESULTS for the measured half)

Challenge **"Best Use of COOL" = conditional / likely defer.** Reasoning in one line:
the prize wants a reproducible COOL-vs-baseline gain on Graviton, but COOL is AMI-only
and our stack is Lambda-zip; without the user subscribing (U2) and adding an EC2/AMI path
we can only publish an **honest x86-vs-arm64 baseline** (below), not a COOL delta — so we
treat COOL as a stretch goal gated on U2 and focus the submission on the general +
Agentic Vision tracks, keeping the baseline ready to extend if the user subscribes.
