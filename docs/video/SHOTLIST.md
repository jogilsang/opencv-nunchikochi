# Shot list — Nunchikochi demo video

Owner: web tab (W7). Pairs each beat of `SCRIPT.md` with the exact on-screen asset and the
caption line. Assets live in `docs/screenshots/` (see `ASSETS.md`); motion can be recorded
with `web/tools/record_demo.mjs`. Architecture diagram is a conductor placeholder.

`URL state`: `demo` = `?demo=1` (recorded session, no camera; realtime-paced ~60–90s with a
progress bar + "Skip to report" — add `&fast=1` for quick auto-advancing playback, as the
recorder does); `live` = local-live with a Playwright **fake** camera (`live-*` shots /
`record_demo.mjs --live`); `n/a` = static asset. The "Demo playback — not a real camera" strip
shows in demo mode only (never in live). **[USER]** rows are optional on-camera/voice, user's
choice (U5).

| # | time | screen / asset | URL state | narration line (abridged) | caption (burned-in) |
|---|------|----------------|-----------|---------------------------|---------------------|
| 1 | 0:00–0:30 | [USER] talking head *or* `demo-01-start.png` under VO | n/a / demo | "We creep toward the screen and never notice until it hurts… a calm desk coach that reads posture and fatigue cues — never who you are." | Reads posture & fatigue cues — never who you are. |
| 2 | 0:30–0:45 | `demo-01-start.png` (consent) | demo | "One promise up front: frames are analysed in memory on AWS and discarded immediately." | Frames analysed in memory on AWS, then discarded. |
| 2 | 0:45–1:00 | `demo-08-privacy.png` (privacy modal) | demo | "Only aggregate numbers are kept. A wellbeing nudge, not a diagnosis." | Only aggregate numbers kept · not a diagnosis. |
| 3 | 1:00–1:12 | `live-02-connected-ready.png` (mode select, Live, status line) | live | "Pick Live mode, allow the camera." | Live mode · running on arm64 · OpenCV 5. |
| 3 | 1:12–1:25 | `demo-02-calibrate.png` (5s countdown) | demo | "Five seconds learning your neutral posture." | Calibrating neutral posture (5s). |
| 3 | 1:25–1:42 | `demo-03-run-overlay.png` (overlay on) | demo / `record_demo.mjs` | "Turn on 'what OpenCV sees' — face box and landmark points, coordinates only." | What OpenCV sees — coordinates only, no image. |
| 3 | 1:42–1:55 | `demo-05-run-toast.png` (nudge) | demo | "Lean in and hold it — a gentle nudge. Two at most." | Gentle nudge · max 2 · never covers metrics. |
| 4 | 1:55–2:12 | `demo-03-run-overlay.png` (metric cards) | demo | "OpenCV 5 detects the face, finds landmarks, derives eye-openness, head tilt, distance." | OpenCV 5: detect · landmarks · metrics. |
| 4 | 2:12–2:30 | `demo-04-run-skeleton.png` (quality skeleton) | demo | "It scores quality and can take a second look before bothering you." | Low quality → second look first. |
| 5 | 2:30–2:52 | `demo-06-agent-panel.png` (agent timeline, second_look rows) | demo | "When uncertain it asks OpenCV to look again — and the result changes the plan." | The view changes the decision (second_look). |
| 5 | 2:52–3:15 | `demo-05-run-toast.png` (confirm toast) | demo | "Still unsure → it asks you yes/no. Off-list suggestions are rejected by a guardrail." | You stay in control · guardrail on the model. |
| 6 | 3:15–3:30 | `w14-buddy-front-neutral.png` → `w14-buddy-front-forward.png` (seated figure, leans forward) | demo / `record_demo.mjs` | "Meet the posture buddy — a seated upper-body figure. The head and drink are measured; the neck and torso are a model estimate, and the legs aren't drawn." | Head + hand measured · neck + torso estimated · no legs. |
| 6 | 3:30–3:42 | `w14-buddy-drinking.png` (arm raised) → `w14-buddy-side.png` → `w14-buddy-ghost.png` (sky-blue ghost) | demo / `record_demo.mjs` | "Lean in and the body gives an estimated bow; take a sip and the measured drink event raises its arm. The faint sky-blue outline is good posture." | Drink event raises the arm · faint outline = good posture. |
| 6 | 3:42–3:55 | `w14-buddy-side.png` + rewind timeline (held still when unsure) | demo | "Scrub the timeline to see when your head crept forward. Movement is ~1.5× exaggerated, and when tracking is unsure it holds still." | Rewind · ~1.5× · neck/torso are an estimate. |
| 7 | 3:55–4:15 | [DIAGRAM] architecture (placeholder) + `demo-08-privacy.png` | n/a | "One Lambda, arm64 Graviton, concurrency cap 5; state in DynamoDB 24h; frames never stored; a frame analyses in ~0.2–0.3s, enough for 2 fps." | AWS · arm64 Graviton · ~0.2–0.3s/frame · frames never stored. |
| 8 | 4:15–4:30 | `demo-04-run-skeleton.png` → confirm toast (failure path) | demo | "Dark room → quality warning → second look doesn't clear it → it asks you." | Failure path: unsure → ask, don't guess. |
| 8 | 4:30–4:45 | text card over `demo-07-report.png` | n/a | "22 deterministic + 9 adversarial scenarios; one left failing on purpose." | Eval: 22/22 + 9 adversarial · 1 honest FAIL. |
| 9 | 4:45–4:55 | `demo-07-report.png` / `demo-09-report-ko.png` [USER] close | demo | "OpenCV 5 that sees, an agent that decides with you, frames never kept." | OpenCV 5 · agent-with-you · privacy-first. |

## Notes for the editor
- Prefer motion (recorded webm from `record_demo.mjs`) for scenes 3–6; the buddy panel (scene 6)
  shows the seated figure moving (head tilt → forward → drink → ghost → rewind).
  Fall back to the static PNGs (`w14-buddy-*.png`) if recording isn't available.
- The architecture diagram (scene 7) is the conductor's asset; until it lands, use a
  placeholder card and keep the VO.
- Captions are burned-in short lines; the full SRT (`captions.en.srt`) carries the complete
  narration timing.
- The posture buddy measures only the head angles + the drink event: never imply it measures
  the body. The burned-in caption "head + hand measured · neck + torso estimated · no legs"
  must stay on the buddy shots.
- Do **not** place any accuracy percentage on screen (vision P/R/F1 unmeasured) and do not
  show account IDs, keys, or real faces (except optional [USER] shots the user records).
