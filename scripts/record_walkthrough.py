"""Record the UI walkthrough video + screenshots with Playwright (docs/media/).

Not part of the app or CI; needs `pip install playwright==1.64.0` in any Python and a Chromium build.
Run the app first on a free port with the local model selected, e.g.:

    INKFALL_API_PORT=5112 INKFALL_LLM_MODEL=gpt-oss:20b ./run.sh
    python scripts/record_walkthrough.py --base http://127.0.0.1:5112 --out docs/media
"""

from __future__ import annotations

import argparse
import shutil
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

Q = "What availability does the Orion SLA commit to?"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:5112")
    ap.add_argument("--out", default="docs/media")
    ap.add_argument("--mode", default="ollama", help="answer mode option value to select")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    tmp = out / "_video_tmp"
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1280, "height": 760}, record_video_dir=str(tmp),
                                  record_video_size={"width": 1280, "height": 760})
        page = ctx.new_page()
        t0 = time.time()
        page.goto(f"{args.base}/login")
        page.wait_for_timeout(1500)
        page.get_by_role("button", name="dana.whitcombe").click()
        page.locator("textarea").wait_for(timeout=20000)
        page.wait_for_timeout(1200)
        page.locator("select").filter(has_text="Extractive").select_option(args.mode)
        page.wait_for_timeout(600)
        page.locator("textarea").fill(Q)
        page.wait_for_timeout(800)
        page.get_by_role("button", name="Ask", exact=True).click()
        page.locator(".mode-banner").wait_for(timeout=120000)
        page.wait_for_timeout(1500)
        page.locator(".mode-banner").scroll_into_view_if_needed()
        page.wait_for_timeout(2500)
        page.screenshot(path=str(out / "generated-answer.png"))
        chip = page.locator(".sentences .chip-row button").first
        if chip.count():
            chip.click()
            page.wait_for_timeout(3000)
            page.screenshot(path=str(out / "citation-verified.png"))
            page.keyboard.press("Escape")
            page.wait_for_timeout(800)
        page.goto(f"{args.base}/lab")
        page.wait_for_timeout(2500)
        sec = page.get_by_text("Answer faithfulness: LLM judge vs reference labels").first
        sec.scroll_into_view_if_needed()
        page.wait_for_timeout(1000)
        page.mouse.wheel(0, -60)
        page.wait_for_timeout(2500)
        page.screenshot(path=str(out / "faithfulness-console.png"))
        for _ in range(6):
            page.mouse.wheel(0, 380)
            page.wait_for_timeout(900)
        page.wait_for_timeout(1500)
        print(f"recorded {time.time() - t0:.1f} s")
        ctx.close()
        browser.close()
    vids = sorted(tmp.glob("*.webm"))
    if vids:
        shutil.move(str(vids[-1]), out / "walkthrough.webm")
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
