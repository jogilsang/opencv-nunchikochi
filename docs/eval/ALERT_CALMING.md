# Alert calming — before/after measurement (A12)

Owner: agent tab. **Synthetic scenario, NOT a real-use measurement.** It shows that the
A11 calming defaults cut how often the agent interrupts, and states the cost of that quiet.

## What was run

One deterministic 1-hour desk session (121 frames, one every 30 s, no RNG, no network, no
images) is fed through the real `NunchiAgent` twice:

- **Before** = the pre-A11 defaults at commit `1897ea7` (10/10/5-min cooldowns; no hourly
  nudge/confirm caps; no same-kind confirm guard; no quality debounce).
- **After** = the current calm defaults (20-min cooldown; ≤3 nudges/hour; ≤2 confirm
  toasts/hour and never the same kind twice in a row; a 30-s face-present quality debounce).

Both runs execute the *same* current `policy.py`; "before" is reproduced by setting the
new knobs to no-op values, so the new code paths are inert and only the old thresholds act.

Scenario mix (`eval/agent/alert_calming.py::_frames`): a near-constant forward-head lean
for the whole hour; a head tilt in alternating 600-s blocks; a low-confidence yawn/drink
event every 300 s (borderline → confirm candidate); and a face-present marginal-quality
(blurry) stretch from 1200 s to 1265 s.

Reproduce:

```bash
uv run python eval/agent/alert_calming.py
# writes docs/eval/alert_calming_result.json + docs/eval/timeline_sample.json, prints the table
```

Seed: none (fixed deterministic schedule). Full result JSON: `docs/eval/alert_calming_result.json`.

## Result

| Metric | Before (pre-A11) | After (calm) |
|---|---|---|
| Nudges sent | 6 | 3 |
| Confirm toasts asked | 1 | 1 |
| Quality warnings | 2 | 1 |
| **Total alerts** | **9** | **5** |
| Silent frames | 6 | 7 |

In this hour the agent interrupts **9 → 5 times (≈44% fewer)**. Nudges for the same
unchanging posture problem drop from 6 to 3 (the 20-min cooldown plus the ≤3/hour cap),
and the transient first quality blip no longer fires a warning (2 → 1). The single
low-confidence event is far enough apart that neither the hourly confirm cap nor the
same-kind guard binds here, so confirms are unchanged (1 → 1) — reported as-is, not inflated.

## The cost of being quiet (honest)

| Cost | Value |
|---|---|
| First nudge timing | identical, 180 s in both (calming never delays the *first* alert) |
| First **repeat** nudge delayed by | **600 s** (10 min later under the calmer cooldown) |
| Held nudges vs before | 3 |
| Held confirms vs before | 0 |
| Held quality warnings vs before | 1 |

Held alerts are **not lost**: each is counted in the end-of-session suppressed digest and
surfaces in the report. The "after" digest for this run was
`{"cooldown:forward_head": 75, "hourly_cap:forward_head": 34, "quality_transient": 1}` —
i.e. the same posture problem was re-announced less often, not ignored. The real trade-off
is latency: if a *new* problem began during a cooldown window, its nudge would wait out the
remaining cooldown (worst case ~20 min for a posture behaviour), which is why the digest
and the per-window timeline exist — so nothing a long session surfaces is silently dropped.

## Per-window timeline + multi-session trend (sample)

`docs/eval/timeline_sample.json` is a synthetic end-of-session payload the web/report can
quote verbatim (numbers only, no images): today's bad-posture timeline bucketed into
5/10/30/60-minute windows with a `per_hour_rate`, plus five synthetic prior sessions whose
rate trends down. Today reads **2.0/h vs a 7.2/h baseline → `improving`**, with EN/KO lines.

## Devpost용 문장 (EN + KO, 새 수치만)

**EN:**
We measured the calming effect on a deterministic, synthetic one-hour desk session (not a
real-use measurement). Under the earlier defaults the agent interrupted 9 times; under the
current calm defaults it interrupts 5 — about 44% fewer — while the *first* nudge still
fires at the same moment (180 s). Repeat nudges for the same unchanging posture drop from 6
to 3, and a transient quality blip no longer raises a warning. Nothing is silently dropped:
every suppressed signal is counted and shown in the end-of-session report, and the cost is
latency — a repeat nudge can wait out up to a 20-minute cooldown. Reproduce with
`uv run python eval/agent/alert_calming.py`.

**KO:**
결정적 합성 1시간 데스크 세션(실사용 측정 아님)으로 알림 진정 효과를 측정했다. 이전 기본값에서는
에이전트가 9번 끼어들었고, 현재의 조용한 기본값에서는 5번으로 약 44% 줄었다. 단 *첫* 넛지는 두
경우 모두 같은 시점(180초)에 울린다. 바뀌지 않는 같은 자세에 대한 반복 넛지는 6→3으로 줄고, 잠깐의
품질 저하는 더 이상 경고를 띄우지 않는다. 억제된 신호는 조용히 버려지지 않는다 — 모두 세어서 세션
종료 리포트에 보여 주며, 대가는 지연이다(반복 넛지는 최대 20분 쿨다운을 기다릴 수 있다). 재현:
`uv run python eval/agent/alert_calming.py`.
