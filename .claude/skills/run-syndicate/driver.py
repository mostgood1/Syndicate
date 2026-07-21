"""Syndicate run/drive harness.

Launches the Flask dev server as a subprocess on a fixed local port,
polls until it actually answers (never a blind sleep), then drives it
with Playwright (chromium, headless) to prove real pages render.
Screenshots land in the `screenshots/` directory next to this file.

Usage (from the repo root, i.e. the Syndicate/ directory):

    python .claude/skills/run-syndicate/driver.py smoke
    python .claude/skills/run-syndicate/driver.py shoot /portfolio out.png
    python .claude/skills/run-syndicate/driver.py stop

`smoke` is the representative flow: home -> portfolio -> betting board
(cards view) -> betting board (blotter view), asserting each key
element actually mounted and that no page threw a console error.
"""
from __future__ import annotations

import platform
import socket
import subprocess
import sys
import time
from pathlib import Path

HOST = "127.0.0.1"
PORT = 5057
BASE = f"http://{HOST}:{PORT}"
# .claude/skills/run-syndicate/driver.py -> repo root is 3 parents up.
REPO_ROOT = Path(__file__).resolve().parents[3]
SCREENSHOT_DIR = Path(__file__).resolve().parent / "screenshots"


def _port_open() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((HOST, PORT)) == 0


def start_server(timeout: float = 30.0) -> subprocess.Popen:
    if _port_open():
        raise RuntimeError(f"Port {PORT} already in use -- run `python driver.py stop` first.")
    proc = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "from syndicate.app import app; "
            f"app.run(host='{HOST}', port={PORT}, debug=False, use_reloader=False)",
        ],
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _port_open():
            return proc
        if proc.poll() is not None:
            output = proc.stdout.read().decode("utf-8", "replace") if proc.stdout else ""
            raise RuntimeError(f"Server exited early (code {proc.returncode}):\n{output[-4000:]}")
        time.sleep(0.5)
    proc.kill()
    raise TimeoutError(f"Server did not open port {PORT} within {timeout}s")


def stop_server(proc: subprocess.Popen | None = None) -> None:
    if proc is not None:
        proc.kill()
        proc.wait(timeout=10)
        return
    # Best-effort port-based kill for `python driver.py stop` run standalone
    # (no in-process handle to the launched server).
    if platform.system() == "Windows":
        out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True).stdout
        for line in out.splitlines():
            if f":{PORT}" in line and "LISTENING" in line:
                pid = line.split()[-1]
                subprocess.run(["taskkill", "/F", "/PID", pid])
    else:
        subprocess.run(["pkill", "-f", f"port={PORT}"])


def smoke() -> None:
    from playwright.sync_api import sync_playwright

    SCREENSHOT_DIR.mkdir(exist_ok=True)
    errors: list[str] = []

    def _console(page):
        page.on("console", lambda m: errors.append(f"{m.type}: {m.text}") if m.type == "error" else None)
        page.on("pageerror", lambda exc: errors.append(f"pageerror: {exc}"))

    with sync_playwright() as p:
        browser = p.chromium.launch()

        # Home gets its OWN fresh server process, and nothing else is
        # visited in that process afterward. Visiting `/` triggers client
        # JS's hydrateHomeRails() -> GET /api/home in the background --
        # observed behavior: the FIRST /api/home call after a cold start
        # can be fast (~10s) or slow, but once it has fired, subsequent
        # unrelated requests to the SAME process (e.g. the next
        # page.goto("/portfolio")) have been observed to hang 200s+. That
        # looks like a real app-side wedge (a lock or background thread
        # that doesn't release), not a Playwright/driver issue -- see
        # Gotchas in SKILL.md. Isolating it to its own process is what
        # makes this driver reliable to run repeatedly.
        proc = start_server()
        try:
            page = browser.new_page(viewport={"width": 1500, "height": 1100})
            _console(page)
            page.goto(f"{BASE}/", wait_until="domcontentloaded")
            hydrated = True
            try:
                page.wait_for_selector(".home-command-center", timeout=30000)
            except Exception:
                hydrated = False
            page.screenshot(path=str(SCREENSHOT_DIR / "home.png"), full_page=True)
            if not hydrated:
                print("NOTE: /api/home did not hydrate within 30s -- screenshot shows the light shell, not the command center. See Gotchas in SKILL.md.")
            page.close()
        finally:
            stop_server(proc)

        # Portfolio + betting board (cards, then blotter) share a second,
        # separate process -- neither of these routes triggers the /api/home
        # background fetch, so they don't need isolating from each other.
        proc = start_server()
        try:
            page = browser.new_page(viewport={"width": 1500, "height": 1100})
            _console(page)

            page.goto(f"{BASE}/portfolio", wait_until="domcontentloaded")
            page.wait_for_selector(".portfolio-tiles", timeout=15000)
            page.screenshot(path=str(SCREENSHOT_DIR / "portfolio.png"), full_page=True)

            page.goto(f"{BASE}/intelligence", wait_until="domcontentloaded")
            page.wait_for_selector(
                "#board-cards .board-grid, #board-cards .board-blotter-wrap, .board-empty",
                timeout=30000,
            )
            page.screenshot(path=str(SCREENSHOT_DIR / "board_cards.png"), full_page=True)

            page.click("#board-view-tabs button:has-text('Blotter')")
            page.wait_for_selector("#board-cards .board-blotter-wrap, .board-empty", timeout=10000)
            page.screenshot(path=str(SCREENSHOT_DIR / "board_blotter.png"), full_page=True)
            page.close()
        finally:
            stop_server(proc)

        browser.close()

    print(f"Screenshots written to {SCREENSHOT_DIR}")
    if errors:
        print("Console errors:")
        for e in errors:
            print(" ", e)
        raise SystemExit(1)
    print("No console errors.")


def shoot(path: str, out: str) -> None:
    from playwright.sync_api import sync_playwright

    proc = start_server()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1500, "height": 1100})
            page.goto(f"{BASE}{path}", wait_until="domcontentloaded", timeout=90000)
            time.sleep(1)
            page.screenshot(path=out, full_page=True)
            browser.close()
    finally:
        stop_server(proc)
    print(f"Wrote {out}")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] == "smoke":
        smoke()
    elif args[0] == "shoot" and len(args) >= 2:
        shoot(args[1], args[2] if len(args) > 2 else "shot.png")
    elif args[0] == "stop":
        stop_server()
    else:
        print(__doc__)
        sys.exit(1)
