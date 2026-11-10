"""Browser smoke test of the one-port build (`make smoke`): the paths the demo depends on, in real Chromium.

Unit and API tests never ran the exported UI, which is how a login redirect loop under `make serve` survived two
phases. This starts the API + static UI on a free port over a throwaway copy of the database, then checks:

1. /login/ stays put (no redirect loop) and an identity card signs in to the workbench;
2. the Brightwater question shows both conflicting values (60 vs 90 days) side by side;
3. a citation opens the document with exactly the cited sentence highlighted;
4. the walled associate (theo.brandt) gets an abstention on a Harrow question, with no Harrow ref on the page;
5. the Evaluation lab, seen by theo.brandt, shows none of the walled matter's answers.

Needs the static export (`make web-export`) and Playwright + Chromium (`make smoke` installs both on demand).
"""

from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import Page, expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
WALLED_SECRETS = ("1,150,000", "620,000", "LF-HARROW")
# Questions about the walled matter that only people on it may see (gold rows asked by marcus.oyelaran).
WALLED_QUESTIONS = ("When is the Harrow mediation scheduled?", "revisit the Harrow litigation hold",
                    "What is our opening offer to Fenwick in Harrow?")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_server(tmp: Path) -> tuple[subprocess.Popen, str]:
    db = ROOT / "data" / "inkfall.db"
    if not db.exists():
        subprocess.run([sys.executable, "-m", "inkfall.seed"], cwd=ROOT, check=True)
    shutil.copy(db, tmp / "inkfall.db")
    port = free_port()
    env = {**os.environ, "INKFALL_DB": str(tmp / "inkfall.db"), "INKFALL_DATA_DIR": str(tmp)}
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "inkfall.api:create_app", "--factory",
                             "--host", "127.0.0.1", "--port", str(port)], cwd=ROOT, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    for _ in range(240):
        try:
            with urllib.request.urlopen(f"{base}/health", timeout=2) as r:  # noqa: S310 - localhost only
                if r.status == 200:
                    return proc, base
        except OSError:
            time.sleep(0.5)
    proc.terminate()
    raise SystemExit("server did not start")


def sign_in(page: Page, base: str, name: str) -> None:
    page.goto(f"{base}/login/")
    page.get_by_text(name, exact=True).click()
    expect(page.get_by_role("heading", name="Ask the vault")).to_be_visible(timeout=60_000)


def run(base: str) -> list[str]:
    checks: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1400, "height": 900})

        page.goto(f"{base}/login/")
        expect(page.get_by_text("Ava Lindqvist", exact=True)).to_be_visible(timeout=30_000)
        page.wait_for_timeout(2500)
        assert page.url.rstrip("/").endswith("/login"), f"login page redirected to {page.url}"
        checks.append("login page is stable (no redirect loop)")

        sign_in(page, base, "Ava Lindqvist")
        checks.append("ava.lindqvist reaches the workbench")

        page.get_by_role("button", name=re.compile("Brightwater supply agreement for convenience")).click()
        page.get_by_role("button", name="Ask", exact=True).click()
        expect(page.get_by_text("Contradictory evidence")).to_be_visible(timeout=60_000)
        body = page.inner_text("body")
        assert "60 days" in body and "90 days" in body, "conflict values not shown"
        checks.append("conflicting clauses shown side by side (60 vs 90 days)")

        answer = " ".join(" ".join(page.locator(".sentence-text").all_inner_texts()).split())
        page.locator("button", has_text=re.compile(r"^P\d")).first.click()
        mark = page.locator("mark.cite-mark").first
        expect(mark).to_be_visible(timeout=30_000)
        quote = " ".join(mark.inner_text().split())
        assert quote and quote in answer, f"highlight {quote!r} is not one of the cited answer sentences"
        checks.append("citation opens with exactly the cited sentence highlighted")
        page.keyboard.press("Escape")

        sign_in(page, base, "Theo Brandt")
        page.locator("textarea").fill("What settlement authority has the client given in the Harrow matter?")
        page.get_by_role("button", name="Ask", exact=True).click()
        expect(page.get_by_text(re.compile("Insufficient evidence"))).to_be_visible(timeout=60_000)
        body = page.inner_text("body")
        leaked = [s for s in WALLED_SECRETS if s in body]
        assert not leaked, f"walled content on the workbench: {leaked}"
        checks.append("walled associate abstains on the Harrow matter; nothing from it on the page")

        with page.expect_response(lambda r: "/api/eval/report" in r.url, timeout=60_000) as resp:
            page.goto(f"{base}/lab/")
        payload = resp.value.text()
        expect(page.get_by_text("Failures explorer")).to_be_visible(timeout=60_000)
        page.locator("select").filter(has=page.locator("option", has_text="Show all rows")).select_option("")
        body = page.inner_text("body")
        leaked = [s for s in (*WALLED_SECRETS, *WALLED_QUESTIONS) if s in body or s in payload]
        assert not leaked, f"walled content in the evaluation lab (page or its API response): {leaked}"
        checks.append("evaluation lab shows the walled associate none of the walled matter's answers")
        browser.close()
    return checks


def main() -> None:
    if not (ROOT / "web" / "out" / "index.html").exists():
        raise SystemExit("no static export: run make web-export first")
    tmp = Path(tempfile.mkdtemp(prefix="inkfall-smoke-"))
    proc, base = start_server(tmp)
    try:
        for c in run(base):
            print(f"ok  {c}")
        print("SMOKE: ALL PASSED")
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
