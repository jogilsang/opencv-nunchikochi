#!/usr/bin/env python3
"""Build the Agentic Vision agent-workflow diagrams (SVG) from AGENT_WORKFLOW_SPEC.md.

OWNER: web tab (W9). Hand-authored, deterministic SVG — no external service, no network.
Emits:
  docs/diagrams/agent_workflow.svg          full one-pager (1920px-wide readable)
  docs/diagrams/agent_workflow_compact.svg  6-8 node simplified version for the video

Every node/edge/branch here comes from docs/diagrams/AGENT_WORKFLOW_SPEC.md (which is
code-derived). Nothing not in the spec is drawn. PNGs are rendered separately with
Playwright (see docs/diagrams/README.md) — this script only writes SVG.

Colour meaning (fixed):
  vision        = blue     (#2f6fe0)
  agent decide  = purple   (#7c5cff)
  human-in-loop = orange   (#e08a2f)
  failure/fallback = red dashed (#d2443a)
  safety guardrail = green  (#2fa36b)
Usage:  python docs/diagrams/build_agent_diagram.py [--out docs/diagrams]
"""
from __future__ import annotations
import argparse
import html
from pathlib import Path

# ---- palette (colour meaning is fixed by the brief) -------------------------
C = {
    "vision": "#2f6fe0",
    "agent": "#7c5cff",
    "human": "#e08a2f",
    "fail": "#d2443a",
    "safety": "#2fa36b",
    "neutral": "#5b6676",
    "ink": "#0e141c",
    "bg": "#0e141c",
    "panel": "#161f2b",
    "panel2": "#1d2836",
    "line": "#2a3850",
    "fg": "#e8eef6",
    "muted": "#a9b8cc",
}
# fill tints per kind (dark theme, readable at 1920)
FILL = {
    "vision": "#122543",
    "agent": "#241a4d",
    "human": "#3a2912",
    "fail": "#361713",
    "safety": "#113224",
    "io": "#1d2836",
    "neutral": "#1a2230",
}
STROKE = {
    "vision": C["vision"], "agent": C["agent"], "human": C["human"],
    "fail": C["fail"], "safety": C["safety"], "io": C["line"], "neutral": C["neutral"],
}
FONT = ('font-family="ui-sans-serif,-apple-system,Segoe UI,Roboto,Helvetica,Arial,'
        '\'Apple SD Gothic Neo\',\'Malgun Gothic\',sans-serif"')


# ---- tiny SVG builder -------------------------------------------------------
class Svg:
    def __init__(self, w, h):
        self.w, self.h, self.parts = w, h, []

    def rect(self, x, y, w, h, fill, stroke, rx=14, sw=2, dash=None, opacity=1.0):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.parts.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" ry="{rx}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{d} opacity="{opacity}"/>')

    def diamond(self, cx, cy, w, h, fill, stroke, sw=2):
        pts = f"{cx},{cy-h/2} {cx+w/2},{cy} {cx},{cy+h/2} {cx-w/2},{cy}"
        self.parts.append(
            f'<polygon points="{pts}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>')

    def text(self, x, y, s, size=15, fill=None, weight="600", anchor="middle"):
        fill = fill or C["fg"]
        self.parts.append(
            f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill}" {FONT} '
            f'font-weight="{weight}" text-anchor="{anchor}" '
            f'dominant-baseline="middle">{html.escape(s)}</text>')

    def multiline(self, x, y, lines, size=15, fill=None, weight="600", anchor="middle", lh=18):
        fill = fill or C["fg"]
        n = len(lines)
        y0 = y - (n - 1) * lh / 2
        for i, ln in enumerate(lines):
            self.text(x, y0 + i * lh, ln, size=size, fill=fill, weight=weight, anchor=anchor)

    def line(self, x1, y1, x2, y2, stroke=None, sw=2, dash=None, arrow=True):
        stroke = stroke or C["muted"]
        d = f' stroke-dasharray="{dash}"' if dash else ""
        mk = ' marker-end="url(#arrow)"' if arrow else ""
        self.parts.append(
            f'<path d="M {x1} {y1} L {x2} {y2}" fill="none" stroke="{stroke}" '
            f'stroke-width="{sw}"{d}{mk}/>')

    def path(self, d, stroke=None, sw=2, dash=None, arrow=True):
        stroke = stroke or C["muted"]
        da = f' stroke-dasharray="{dash}"' if dash else ""
        mk = ' marker-end="url(#arrow)"' if arrow else ""
        self.parts.append(
            f'<path d="{d}" fill="none" stroke="{stroke}" stroke-width="{sw}"{da}{mk}/>')

    def edge_label(self, x, y, s, size=13, fill=None):
        fill = fill or C["muted"]
        w = max(26, len(s) * 7 + 10)
        self.parts.append(
            f'<rect x="{x-w/2}" y="{y-11}" width="{w}" height="22" rx="6" '
            f'fill="{C["bg"]}" stroke="{C["line"]}" stroke-width="1"/>')
        self.text(x, y, s, size=size, fill=fill, weight="600")

    def marker_badge(self, x, y, n, color):
        self.parts.append(
            f'<circle cx="{x}" cy="{y}" r="15" fill="{color}" stroke="{C["fg"]}" stroke-width="2"/>')
        self.text(x, y + 1, n, size=16, fill="#ffffff", weight="800")

    def svg(self):
        defs = (
            '<defs>'
            '<marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
            'markerHeight="7" orient="auto-start-reverse">'
            f'<path d="M 0 0 L 10 5 L 0 10 z" fill="{C["muted"]}"/></marker>'
            '</defs>')
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" '
            f'viewBox="0 0 {self.w} {self.h}" font-family="sans-serif">'
            f'<rect width="{self.w}" height="{self.h}" fill="{C["bg"]}"/>'
            f'{defs}' + "".join(self.parts) + '</svg>')


def node(s, x, y, w, h, kind, lines, size=15):
    s.rect(x, y, w, h, FILL[kind], STROKE[kind])
    s.multiline(x + w / 2, y + h / 2, lines, size=size)


def dnode(s, cx, cy, w, h, kind, lines, size=14):
    s.diamond(cx, cy, w, h, FILL[kind], STROKE[kind])
    s.multiline(cx, cy, lines, size=size, lh=16)


def legend(s, x, y):
    items = [
        ("vision", "Vision (OpenCV 5)"),
        ("agent", "Agent decision"),
        ("human", "Human-in-the-loop"),
        ("safety", "Safety guardrail"),
        ("fail", "Failure / fallback (dashed)"),
    ]
    s.rect(x, y, 360, 182, C["panel"], C["line"], rx=12, sw=1)
    s.text(x + 18, y + 26, "Legend", size=16, fill=C["fg"], anchor="start")
    yy = y + 52
    for kind, label in items:
        dash = "6 5" if kind == "fail" else None
        s.rect(x + 18, yy - 11, 30, 22, FILL[kind], STROKE[kind], rx=6, sw=2, dash=dash)
        s.text(x + 60, yy, label, size=14, fill=C["muted"], anchor="start", weight="600")
        yy += 26


# =============================================================================
# FULL diagram
# =============================================================================
def build_full() -> str:
    W, H = 2000, 1660
    s = Svg(W, H)
    s.text(W / 2, 40, "Nunchikochi — Agent workflow (one frame: perceive \u2192 decide \u2192 act)",
           size=24, weight="800")
    s.text(W / 2, 68, "Every node and branch is derived from src/nunchi/agent/ via docs/diagrams/AGENT_WORKFLOW_SPEC.md",
           size=14, fill=C["muted"], weight="500")

    legend(s, 40, 96)
    # invariant caption (privacy)
    s.rect(430, 96, 560, 40, C["panel2"], C["line"], rx=10, sw=1)
    s.text(710, 116, "Invariant: frames / images / coordinates are never stored, returned, or traced.",
           size=14, fill=C["muted"])
    # principle caption
    s.rect(1010, 96, 560, 40, C["panel2"], C["line"], rx=10, sw=1)
    s.text(1290, 116, "LLM only proposes; rules + guardrails are the floor (latency 0, cost 0 on normal frames).",
           size=13, fill=C["muted"])

    cx = 760            # central column for intake
    ladder_x = 430      # diamonds column
    act_x = 1140        # action column (right)
    sl_x = 790          # second_look column (between diamonds and actions)

    # --- top intake ---
    node(s, cx - 150, 160, 300, 56, "io",
         ["frame_in + AgentContext", "(frame_bgr = request-scope memory)"], size=14)
    s.line(cx, 216, cx, 244)
    node(s, cx - 120, 244, 240, 46, "neutral", ["coerce \u2192 FrameResult"], size=14)
    s.line(cx, 290, cx, 318)
    node(s, cx - 150, 318, 300, 52, "vision", ["vision_result: quality, events,", "face_present, persons (no image)"], size=13)

    # rule ladder rows (priority 0..5), generous spacing
    gap = 150
    y0 = 440
    ys = [y0 + i * gap for i in range(6)]

    def diamond_row(cy, lines, kind="agent"):
        dnode(s, ladder_x, cy, 230, 86, kind, lines)

    def action(cy, kind, lines, w=250):
        node(s, act_x - w / 2, cy - 26, w, 52, kind, lines, size=13)

    # entry from vision_result to first diamond
    s.path(f"M {cx} 370 L {cx} 400 L {ladder_x} 400 L {ladder_x} {ys[0]-43}")

    # row 0 away
    diamond_row(ys[0], ["0  away?", "no face \u00b7 persons 0 \u00b7 ok"])
    action(ys[0], "safety", ["suppress_focus", "(away)"])
    s.path(f"M {ladder_x+115} {ys[0]} L {act_x-125} {ys[0]}")
    s.edge_label((ladder_x + 115 + act_x - 125) / 2, ys[0] - 15, "yes")
    s.path(f"M {ladder_x} {ys[0]+43} L {ladder_x} {ys[1]-43}")
    s.edge_label(ladder_x, (ys[0] + ys[1]) / 2, "no")

    # row 1 quality bad? (3-way)
    diamond_row(ys[1], ["1  quality bad?"])
    # 1a repeated(3x) -> ask_confirmation (human), placed above-right
    action(ys[1] - 52, "human", ["ask_confirmation", "(quality \u00d73)"], w=230)
    s.path(f"M {ladder_x+100} {ys[1]-22} L {act_x-115} {ys[1]-52}")
    s.edge_label((ladder_x + 100 + act_x - 115) / 2 - 20, ys[1] - 52, "yes \u00d73")
    # 1b second_look(enhance)
    node(s, sl_x - 110, ys[1] + 20, 220, 48, "vision", ["second_look(enhance)"], size=13)
    s.path(f"M {ladder_x+90} {ys[1]+30} L {ladder_x+90} {ys[1]+44} L {sl_x-110} {ys[1]+44}")
    s.edge_label(ladder_x + 160, ys[1] + 44, "bad quality")
    s.marker_badge(sl_x + 118, ys[1] + 44, "1", C["vision"])
    # resolved -> none (up-right)
    action(ys[1] + 6, "agent", ["none", "(quality cleared)"], w=210)
    s.path(f"M {sl_x+110} {ys[1]+40} L {act_x-105} {ys[1]+8}")
    s.edge_label((sl_x + 110 + act_x - 105) / 2, ys[1] + 12, "resolved")
    # not resolved -> request_recalibration (down-right, clear of next row)
    action(ys[1] + 64, "fail", ["request_recalibration"], w=230)
    s.path(f"M {sl_x} {ys[1]+68} L {sl_x} {ys[1]+90} L {act_x-115} {ys[1]+64}", dash="6 5", stroke=C["fail"])
    s.edge_label(sl_x + 130, ys[1] + 90, "not resolved / no variant")
    # no -> down
    s.path(f"M {ladder_x} {ys[1]+43} L {ladder_x} {ys[2]-43}")
    s.edge_label(ladder_x, (ys[1] + ys[2]) / 2, "no")

    # row 2 dnd
    diamond_row(ys[2], ["2  do_not_disturb?"])
    action(ys[2], "safety", ["suppress_focus", "(dnd)"])
    s.path(f"M {ladder_x+115} {ys[2]} L {act_x-125} {ys[2]}")
    s.edge_label((ladder_x + 115 + act_x - 125) / 2, ys[2] - 15, "yes")
    s.path(f"M {ladder_x} {ys[2]+43} L {ladder_x} {ys[3]-43}")
    s.edge_label(ladder_x, (ys[2] + ys[3]) / 2, "no")

    # row 3 low-confidence band
    diamond_row(ys[3], ["3  conf \u2208 band?", "[thr_lo, 0.60], no pending"])
    node(s, sl_x - 120, ys[3] - 24, 240, 48, "vision", ["second_look(zoom/strict)"], size=13)
    s.path(f"M {ladder_x+115} {ys[3]} L {sl_x-120} {ys[3]}")
    s.edge_label((ladder_x + 115 + sl_x - 120) / 2, ys[3] - 15, "in band")
    s.marker_badge(sl_x + 128, ys[3] - 24, "2", C["vision"])
    # confirm/reject -> none (up)
    action(ys[3] - 52, "agent", ["none", "(auto confirm/reject)"], w=220)
    s.path(f"M {sl_x+120} {ys[3]-24} L {act_x-110} {ys[3]-52}")
    s.edge_label((sl_x + 120 + act_x - 110) / 2, ys[3] - 54, "confirm/reject")
    # unchanged -> ask_confirmation (human, down)  marker ③
    action(ys[3] + 44, "human", ["ask_confirmation", "(low confidence)"], w=230)
    s.path(f"M {sl_x} {ys[3]} L {sl_x} {ys[3]+44} L {act_x-115} {ys[3]+44}")
    s.edge_label(sl_x + 150, ys[3] + 24, "unchanged")
    s.marker_badge(act_x - 115 - 15, ys[3] + 44, "3", C["human"])
    # no -> down
    s.path(f"M {ladder_x} {ys[3]+43} L {ladder_x} {ys[4]-43}")
    s.edge_label(ladder_x, (ys[3] + ys[4]) / 2, "no")

    # row 4 focus
    diamond_row(ys[4], ["4  focus?", "stable \u00b7 low blink \u00b7 \u2265120s"])
    action(ys[4], "safety", ["suppress_focus", "(focus)"])
    s.path(f"M {ladder_x+115} {ys[4]} L {act_x-125} {ys[4]}")
    s.edge_label((ladder_x + 115 + act_x - 125) / 2, ys[4] - 15, "yes")
    s.path(f"M {ladder_x} {ys[4]+43} L {ladder_x} {ys[5]-43}")
    s.edge_label(ladder_x, (ys[4] + ys[5]) / 2, "no")

    # row 5 sustained -> nudge / cooldown / normal
    diamond_row(ys[5], ["5  sustained \u2265 180s?"])
    action(ys[5] - 34, "agent", ["nudge"], w=170)
    s.path(f"M {ladder_x+100} {ys[5]-10} L {act_x-85} {ys[5]-34}")
    s.edge_label((ladder_x + 100 + act_x - 85) / 2, ys[5] - 44, "yes \u00b7 under cap \u00b7 cooldown ok")
    action(ys[5] + 34, "safety", ["suppress_focus", "(cooldown/daily_cap)"], w=250)
    s.path(f"M {ladder_x+90} {ys[5]+30} L {ladder_x+90} {ys[5]+34} L {act_x-125} {ys[5]+34}")
    s.edge_label(ladder_x + 160, ys[5] + 34, "cooldown / cap")
    node(s, ladder_x - 105, ys[5] + 78, 210, 44, "agent", ["none (normal)"], size=13)
    s.path(f"M {ladder_x} {ys[5]+43} L {ladder_x} {ys[5]+78}")
    s.edge_label(ladder_x, ys[5] + 62, "no")

    # ================= bottom band: LLM refine -> guardrails -> emit =================
    band_y = 1290
    # LLM planner (optional), fed by ambiguous actions
    llm_x = act_x + 120
    node(s, llm_x - 130, band_y - 28, 260, 56, "agent", ["planner (LLM) \u2014 optional,", "ambiguous frames only"], size=13)
    # keep-rules fallback (red) to the right of LLM
    keep_x = llm_x + 360
    node(s, keep_x - 125, band_y - 28, 250, 56, "fail", ["keep rule decision", "(planner = rules)"], size=13)
    s.path(f"M {llm_x+130} {band_y} L {keep_x-125} {band_y}", dash="6 5", stroke=C["fail"])
    s.edge_label((llm_x + 130 + keep_x - 125) / 2, band_y - 16, "cap/timeout/except/blocked")
    # dotted feeds from ambiguous actions (quality x3, ask low-conf, nudge) into LLM
    s.path(f"M {act_x+115} {ys[1]-52} C {llm_x+320} 500, {llm_x+300} 1080, {llm_x} {band_y-28}", dash="4 6", stroke=C["agent"])
    s.path(f"M {act_x+85} {ys[5]-34} C {llm_x+260} 1180, {llm_x+120} 1220, {llm_x} {band_y-20}", dash="4 6", stroke=C["agent"])
    # label sits on the upper dotted feed (so it clearly tags the "llm mode" edges, not floating)
    s.edge_label(llm_x + 300, 600, "llm mode")
    # guardrails (green) below LLM
    node(s, llm_x - 130, band_y + 70, 260, 54, "safety", ["guardrails: whitelist,", "no-diagnosis, length"], size=13)
    s.path(f"M {llm_x} {band_y+28} L {llm_x} {band_y+70}", stroke=C["safety"])
    # emit (centre), fed by guardrails + all rule actions
    emit_x = cx
    node(s, emit_x - 165, band_y - 28, 330, 56, "io", ["emit Decision + trace", "(no image / coords)"], size=14)
    # rule actions collect into emit — drop straight down from the cooldown action's
    # bottom edge, then into emit's right edge through the open gap (no node/label crossings)
    s.path(f"M {act_x} {ys[5]+60} L {act_x} {band_y+6} L {emit_x+165} {band_y+6}")
    s.edge_label(act_x - 70, band_y + 6, "all actions")
    # guardrails -> emit
    s.path(f"M {llm_x-130} {band_y+97} C {emit_x+260} {band_y+97}, {emit_x+180} {band_y+40}, {emit_x+120} {band_y+28}", stroke=C["safety"])
    s.edge_label(emit_x + 300, band_y + 92, "guardrailed")
    # trace note
    s.text(emit_x, band_y + 56, "trace = JSONL (ts, tool, args, result_summary, decision, evidence) \u2014 no images",
           size=13, fill=C["muted"])

    # ================= human reply -> raise threshold feedback (left) =================
    h_x = 180
    h_y = 1140
    node(s, h_x - 125, h_y - 28, 250, 56, "human", ["human reply", "(yes / no)"], size=14)
    # ask_confirmation (③) dotted to human
    s.path(f"M {act_x-115-15} {ys[3]+44} C 260 {ys[3]+160}, 120 980, {h_x} {h_y-28}", dash="4 6", stroke=C["human"])
    node(s, h_x - 125, h_y + 72, 250, 54, "agent", ["raise_threshold", "(persists next frames)"], size=13)
    s.path(f"M {h_x} {h_y+28} L {h_x} {h_y+72}", stroke=C["human"])
    s.edge_label(h_x, h_y + 50, "no")
    s.marker_badge(h_x + 136, h_y + 72 + 27, "4", C["agent"])
    # feedback arrow back up to row 3 band test
    s.path(f"M {h_x-125} {h_y+99} C 30 820, 30 {ys[3]+30}, {ladder_x-115} {ys[3]+8}", dash="6 4", stroke=C["agent"])
    s.edge_label(120, 760, "raises thr_lo")
    # "yes" branch note — placed in open space below raise_threshold (clear of the sustained arrow)
    s.text(h_x - 125, h_y + 150, "yes \u2192 event confirmed, pending cleared",
           size=13, fill=C["muted"], anchor="start")

    # ================= marker captions (bottom strip, C1..C4) =================
    cap_y = H - 120
    s.rect(40, cap_y - 16, W - 80, 118, C["panel"], C["line"], rx=10, sw=1)
    caps = [
        ("1", C["vision"], "C1 action: second_look(enhance) clears quality \u2192 none, instead of recalibrate or asking."),
        ("2", C["vision"], "C2 tool call: confidence in band \u2192 second_look(zoom/strict) re-looks before anything."),
        ("3", C["human"], "C3 approval: only low-confidence asks the human; if second_look resolves, it does not."),
        ("4", C["agent"], "C4 learned control: a human 'no' raises that behaviour's threshold, and it persists."),
    ]
    for i, (n, col, txt) in enumerate(caps):
        yy = cap_y + 10 + i * 24
        s.marker_badge(70, yy, n, col)
        s.text(94, yy, txt, size=14, fill=C["muted"], anchor="start", weight="600")
    return s.svg()


# =============================================================================
# COMPACT diagram (6-8 nodes) for the video
# =============================================================================
def build_compact() -> str:
    W, H = 1760, 560
    s = Svg(W, H)
    s.text(W / 2, 40, "Nunchikochi \u2014 agentic vision loop (simplified)", size=24, weight="800")
    legend(s, 40, 70)

    y = 300
    xs = [120, 400, 690, 1010, 1380]
    node(s, xs[0], y - 34, 220, 68, "vision", ["frame \u2192 OpenCV 5", "quality + confidence"], size=15)
    dnode(s, xs[1] + 110, y, 220, 96, "agent", ["uncertain?", "(low quality or", "low confidence)"])
    node(s, xs[2], y - 40, 240, 80, "vision", ["second_look", "(enhance / zoom / strict)", "re-analyse"], size=14)
    dnode(s, xs[3] + 110, y, 220, 96, "agent", ["resolved?"])
    node(s, xs[4], y - 90, 240, 64, "agent", ["act quietly", "(none / nudge / suppress)"], size=14)
    node(s, xs[4], y + 24, 240, 64, "human", ["ask the human", "yes / no"], size=14)

    # edges
    s.line(xs[0] + 220, y, xs[1] + 110 - 110, y)
    s.path(f"M {xs[1]+220} {y} L {xs[2]} {y}")
    s.edge_label((xs[1] + 220 + xs[2]) / 2, y - 14, "yes")
    # marker ① on vision re-look
    s.marker_badge(xs[2] + 120, y - 40, "1", C["vision"])
    s.path(f"M {xs[2]+240} {y} L {xs[3]+110-110} {y}")
    s.path(f"M {xs[3]+220} {y} L {xs[4]} {y-58}")
    s.edge_label((xs[3] + 220 + xs[4]) / 2, y - 58, "resolved \u2192 quiet")
    s.path(f"M {xs[3]+220} {y} L {xs[4]} {y+56}")
    s.edge_label((xs[3] + 220 + xs[4]) / 2 - 40, y + 30, "unchanged \u2192 ask")
    s.marker_badge(xs[4] - 22, y + 56, "3", C["human"])
    # uncertain? no -> quiet (straight path along top)
    s.path(f"M {xs[1]+110} {y-48} C {xs[1]+110} 150, {xs[4]+120} 150, {xs[4]+120} {y-90}")
    s.edge_label((xs[1] + 110 + xs[4] + 120) / 2, 150, "no (normal) \u2192 none")
    # human no -> threshold feedback (marker ④)
    s.path(f"M {xs[4]+120} {y+88} C {xs[4]+120} 500, {xs[1]+110} 500, {xs[1]+110} {y+48}", dash="6 4", stroke=C["agent"])
    s.edge_label((xs[4] + 120 + xs[1] + 110) / 2, 500, "human 'no' \u2192 raise threshold (persists)")
    s.marker_badge(xs[4] + 120 + 16, y + 88, "4", C["agent"])

    s.text(W / 2, H - 26,
           "Vision result changes the decision: re-look before asking (\u2460), human in control (\u2462), learned threshold (\u2463).",
           size=14, fill=C["muted"])
    return s.svg()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent))
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "agent_workflow.svg").write_text(build_full(), encoding="utf-8")
    (out / "agent_workflow_compact.svg").write_text(build_compact(), encoding="utf-8")
    print(f"[diagram] wrote {out/'agent_workflow.svg'}")
    print(f"[diagram] wrote {out/'agent_workflow_compact.svg'}")


if __name__ == "__main__":
    main()
