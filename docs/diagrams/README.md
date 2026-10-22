# Agent workflow diagrams

Owner: web tab (W9). Submission figure for the **Best Agentic Vision** prize. Everything
here is drawn from [`AGENT_WORKFLOW_SPEC.md`](AGENT_WORKFLOW_SPEC.md), which is itself
derived from `src/nunchi/agent/`. **No branch that isn't in the spec is drawn.**

## Files

| file | what | size |
|---|---|---|
| `agent_workflow.svg` / `.png` | full one-pager: intake → 6-rule ladder → second_look branches → LLM/guardrails → emit, plus the human-confirm + threshold feedback loop | 2000×1660 (PNG 2× = 4000×3320) |
| `agent_workflow_compact.svg` / `.png` | 6-node simplified loop for the video | 1760×560 (PNG 2× = 3520×1120) |
| `build_agent_diagram.py` | regenerates both SVGs (hand-authored, deterministic, no network) | — |

Colour meaning is fixed: **vision = blue**, **agent decision = purple**,
**human-in-the-loop = orange**, **safety guardrail = green**, **failure/fallback = red
dashed**. A legend is on each diagram. Numbered markers ①–④ sit on the points where a
**vision result changes the subsequent decision** (maps to AGENTIC_VISION.md C1–C4).

## Reproduce

```bash
# 1) SVG (pure Python stdlib, no deps, no network)
python docs/diagrams/build_agent_diagram.py            # writes both .svg

# 2) PNG @2x (Playwright screenshot of the SVG; installed tool, no upload)
#    render helper (example): set content=<svg>, deviceScaleFactor=2, screenshot the <svg>
#    see the W9 render step; any SVG->PNG rasteriser at 2x works (rsvg-convert, resvg, etc.)
```

The PNGs in this folder were rendered with Playwright/Chromium at `deviceScaleFactor: 2`
and visually checked (no overlap, no clipping, labels ≥ 14px / crisp at 2×).

## Node ↔ spec correspondence (full diagram)

Every node/edge traces back to a spec row. `§` numbers refer to `AGENT_WORKFLOW_SPEC.md`.

| diagram node | spec | code |
|---|---|---|
| frame_in + AgentContext | §1 `frame_in` | `agent.decide()` entry (`frame_bgr` = request-scope memory) |
| coerce → FrameResult | §1 `coerce` | `decide()._coerce` |
| vision_result (quality/events/face/persons) | §1 `vision_result` | vision tab input; no image |
| 0 away? → suppress_focus(away) | §2 edge 0 | `policy.decide()` priority 0 |
| 1 quality bad? | §2 edges 1a/1b/1c | `policy` priority 1 |
| • yes ×3 → ask_confirmation(quality ×3) | §2 edge 1a | `quality_repeat_for_confirm(3)` |
| • bad quality → **second_look(enhance)** ① | §2 edge 1b | `tools.second_look(enhance)` |
| • resolved → none(quality cleared) | §2 edge 1b | — |
| • not resolved / no variant → request_recalibration *(red)* | §2 edge 1c, §5 | fallback |
| 2 do_not_disturb? → suppress_focus(dnd) | §2 edge 2 | `policy` priority 2 |
| 3 conf ∈ band? [thr_lo,0.60], no pending | §2 edges 3a/3b | `policy` priority 3 |
| • in band → **second_look(zoom/strict)** ② | §2 edge 3a, §3 | `tools.second_look` |
| • confirm/reject → none(auto) | §2 edge 3a | — |
| • unchanged → ask_confirmation(low confidence) ③ | §2 edge 3b, §4 | human-in-the-loop |
| 4 focus? → suppress_focus(focus) | §2 edge 4 | `policy` priority 4 |
| 5 sustained ≥180s? → nudge | §2 edge 5a | `send_nudge` |
| • cooldown / cap → suppress_focus(cooldown/daily_cap) | §2 edge 5b | — |
| • no → none(normal) | §2 edge 6 | — |
| planner (LLM) — optional *(purple)* | §5 LLM refine | `planner.run_with_budget()` |
| keep rule decision *(red dashed)* | §5 cap/timeout/except/blocked | guardrails/budget fallback |
| guardrails: whitelist, no-diagnosis, length *(green)* | §3/§5 | `guardrails.apply_guardrails` |
| emit Decision + trace (no image/coords) | §1 `emit_decision` | `decide()` end; trace is image-free |
| human reply (yes/no) *(orange)* | §4 | `resolve_confirmation()` |
| raise_threshold (persists) ④ | §4 | `apply_confirmation(confirmed=False)` |

## Marker ↔ C1–C4 (vision result changes the decision)

| marker | caption | AGENTIC_VISION.md |
|---|---|---|
| ① | action: `second_look(enhance)` clears quality → `none` instead of recalibrate/ask | C1 |
| ② | tool call: confidence in band → `second_look(zoom/strict)` re-looks before anything | C2 |
| ③ | approval: only low-confidence asks the human; if `second_look` resolves, it does not | C3 |
| ④ | learned control: a human "no" raises that behaviour's threshold and persists | C4 |

## Compact diagram nodes

`frame → OpenCV 5` → `uncertain?` → **`second_look` ①** → `resolved?` → `act quietly`
(resolved) / **`ask the human` ③** (unchanged); `no (normal) → none` shortcut; and the
`human 'no' → raise threshold ④` feedback edge back to `uncertain?`. Same colour legend.

## Scope / notes

- These are the **agent** workflow diagrams only. The AWS **architecture** diagram is the
  conductor's (`aws_architecture.*`), not produced here.
- If the agent code or `AGENT_WORKFLOW_SPEC.md` changes, re-run `build_agent_diagram.py`
  and re-render. The spec is the single source; fix the spec first (code-first rule).
- **Spec check (W9):** every node/edge/failure path in §1–§5 is represented in the full
  diagram; no diagram element lacks a spec row. No spec errors found while drawing.
