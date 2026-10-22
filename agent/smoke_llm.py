"""Small LIVE Bedrock smoke (<=10 calls) proving the real LLM path + cost/latency.

Run: uv run python agent/smoke_llm.py   (needs captain creds; botocore[crt] for SSO)
Writes:
  - agent/samples/trace_llm.jsonl   : real agent decisions with planner="llm"
  - agent/llm_calls.jsonl           : appended per-call tokens/latency/est-cost (by planner)
Prints a latency/token/cost table. No images; prompts are summaries only.

Budget guard: hard cap of 10 calls here; dev total must stay under $2 (see README).
"""
from __future__ import annotations

import json
import pathlib

from nunchi.agent import AgentContext, NunchiAgent, PolicyConfig
from nunchi.agent.planner import BedrockPlanner, estimate_cost_usd
from nunchi.contracts import Event, FrameResult, Metrics, Quality, SessionSummary

OUT = pathlib.Path(__file__).parent / "samples"
OUT.mkdir(exist_ok=True)
LLM_LOG = pathlib.Path(__file__).parent / "llm_calls.jsonl"
MAX_CALLS = 10


def _frame(t, *, face=True, ok=True, issues=None, events=None, brightness=118.0):
    return FrameResult(session_id="smoke", t=t, face_present=face, persons=1 if face else 0,
                       metrics=Metrics(), calibrated=True,
                       quality=Quality(ok=ok, brightness=brightness, sharpness=210.0,
                                       face_px=96, issues=issues or []),
                       events=events or [], backend="opencv", cv_version="5.0.0")


def main() -> None:
    planner = BedrockPlanner(profile="captain", region="us-east-1",
                             max_tokens=160, timeout_s=10.0)
    cfg = PolicyConfig(sustained_min_s=180.0, llm_timeout_s=10.0,
                       llm_report_timeout_s=15.0, llm_max_calls=MAX_CALLS)
    agent = NunchiAgent(vision=None, mode="llm", config=cfg, planner=planner)
    ctx = AgentContext(session_id="smoke")

    # a few ambiguous moments (each may trigger one real LLM call)
    scenarios = [
        ("low_conf drink", _frame(30.0, events=[Event("drink", 29.0, 30.0, 0.5)])),
        ("low_conf yawn",  _frame(60.0, events=[Event("yawn", 59.0, 60.0, 0.55)])),
    ]
    # a sustained forward_head over two frames -> nudge wording (1 call)
    agent.decide(ctx, _frame(10.0, events=[Event("forward_head", 0.0, None, 0.9)]))
    for name, fr in scenarios:
        ctx.pending_confirmation = None
        dec = agent.decide(ctx, fr)
        print(f"[{name}] -> {dec.action} ({dec.reason}) planner={agent.trace.lines[-1].planner}")
    dec = agent.decide(ctx, _frame(300.0, events=[Event("forward_head", 0.0, None, 0.9)]))
    print(f"[nudge forward_head] -> {dec.action} ({dec.reason}) "
          f"planner={agent.trace.lines[-1].planner}")

    # one report via the LLM path
    summ = SessionSummary(session_id="smoke", date="2026-10-22",
                          seconds={"forward_head": 600.0}, nudges_sent=1)
    prev = SessionSummary(session_id="smoke-prev", date="2026-10-21",
                          seconds={"forward_head": 400.0})
    rep = agent.report(summ, prev)
    print(f"[report] source={rep['source']} :: {rep['text_en'][:80]}")

    # write the agent trace (llm lines included; image-free)
    (OUT / "trace_llm.jsonl").write_text(agent.trace.to_jsonl() + "\n", encoding="utf-8")

    # cost/latency table from the per-call log
    _print_cost_table()


def _print_cost_table() -> None:
    if not LLM_LOG.exists():
        print("(no llm_calls.jsonl yet)")
        return
    rows = [json.loads(ln) for ln in LLM_LOG.read_text().splitlines() if ln.strip()]
    ok = [r for r in rows if r.get("status") == "ok"]
    print("\n=== Bedrock call log (all) ===")
    print(f"{'purpose':16} {'status':12} {'in':>5} {'out':>5} {'ms':>8} {'usd':>10}")
    for r in rows:
        print(f"{r.get('purpose',''):16} {r.get('status',''):12} "
              f"{r.get('tokens_in',0):>5} {r.get('tokens_out',0):>5} "
              f"{r.get('latency_ms',0):>8} {r.get('est_cost_usd',0):>10.6f}")
    if ok:
        n = len(ok)
        avg_ms = sum(r["latency_ms"] for r in ok) / n
        avg_in = sum(r["tokens_in"] for r in ok) / n
        avg_out = sum(r["tokens_out"] for r in ok) / n
        total = sum(r["est_cost_usd"] for r in rows)
        per_call = estimate_cost_usd(round(avg_in), round(avg_out))
        print(f"\nOK calls: {n} | avg latency {avg_ms:.0f} ms | "
              f"avg tokens in {avg_in:.0f}/out {avg_out:.0f}")
        print(f"est per-call ${per_call:.6f} | est TOTAL (all calls, this file) ${total:.6f}")


if __name__ == "__main__":
    main()
