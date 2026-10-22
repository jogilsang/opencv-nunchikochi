#!/usr/bin/env python3
"""Capture Nunchikochi demo-mode screenshots for the 5-minute video. OWNER: web tab.

Drives the static web app in DEMO playback (?demo=1) with Playwright and saves PNGs.
No camera, no AWS, no real faces — only the synthetic demo session is shown.

Usage:
    # serve the web/ folder first (static files, no bundler)
    python3 -m http.server 8099 --directory web &
    # then capture (installs Playwright's chromium on first run)
    uv run --with playwright python web/tools/capture.py --base http://localhost:8099 --out docs/screenshots

If Playwright isn't available this script prints install guidance and exits non-zero
without touching anything.
"""
import argparse
import sys
import time
from pathlib import Path

SHOTS = []  # populated as we go, for the summary line


def log(msg):
    print(f"[capture] {msg}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8099", help="base URL serving web/")
    ap.add_argument("--out", default="docs/screenshots", help="output dir for PNGs")
    ap.add_argument("--lang", default="en", choices=["en", "ko"])
    args = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        log("Playwright for Python is not installed.")
        log("Install (ephemeral) and run:")
        log("  uv run --with playwright python web/tools/capture.py")
        log("  (first run also needs: uv run --with playwright python -m playwright install chromium)")
        return 2

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    base = args.base.rstrip("/")
    demo_url = f"{base}/?demo=1&lang={args.lang}"

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 980, "height": 900}, device_scale_factor=2)
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        def shot(name, full_page=False):
            path = out / name
            page.screenshot(path=str(path), full_page=full_page)
            SHOTS.append(name)
            log(f"shot {name}")

        log(f"opening {demo_url}")
        page.goto(demo_url, wait_until="networkidle")
        page.wait_for_function("window.__nunchi && window.__nunchi.screen === 'screen-start'")
        page.wait_for_timeout(250)
        shot("demo-01-start.png")

        # consent + start -> calibrate
        page.check("#consent")
        page.click("#btn-start")
        page.wait_for_function("window.__nunchi.screen === 'screen-calibrate'")
        page.wait_for_timeout(1500)
        shot("demo-02-calibrate.png")

        # run: overlay visible
        page.wait_for_function("window.__nunchi.screen === 'screen-run'")
        page.wait_for_timeout(1200)
        shot("demo-03-run-overlay.png")

        # quality skeleton (dark beat) — banner shows
        try:
            page.wait_for_function(
                "document.getElementById('quality-banner')?.classList.contains('show')", timeout=6000
            )
            page.wait_for_timeout(150)
            shot("demo-04-run-skeleton.png")
        except Exception:
            log("quality beat not caught (continuing)")

        # nudge / confirmation toast
        try:
            page.wait_for_selector(".toast", timeout=8000)
            page.wait_for_timeout(150)
            shot("demo-05-run-toast.png")
        except Exception:
            log("toast not caught (continuing)")

        # agent activity panel with second_look rows
        try:
            page.wait_for_selector(".toast.confirm", timeout=8000)
        except Exception:
            pass
        page.click("#btn-agent")
        page.wait_for_function("!document.getElementById('agent-panel').hidden")
        page.check("#agent-showall")
        page.wait_for_timeout(200)
        shot("demo-06-agent-panel.png", full_page=True)
        page.click("#btn-agent-close")

        # report (demo auto-ends; also force end to be safe)
        try:
            page.wait_for_function("window.__nunchi.screen === 'screen-report'", timeout=8000)
        except Exception:
            page.click("#btn-end")
            page.wait_for_function("window.__nunchi.screen === 'screen-report'")
        page.wait_for_timeout(400)
        shot("demo-07-report.png", full_page=True)

        # privacy modal
        page.click("#btn-privacy")
        page.wait_for_function("!document.getElementById('privacy-modal').hidden")
        shot("demo-08-privacy.png")
        page.keyboard.press("Escape")

        # Korean report for the video's KO beat
        page.click("#lang-ko")
        page.wait_for_timeout(300)
        shot("demo-09-report-ko.png", full_page=True)

        browser.close()
        if errors:
            log(f"PAGE ERRORS: {errors}")
            return 1

    log(f"done — {len(SHOTS)} screenshots in {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
