"""Screenshot Portfolio Watch's "Purchaser vs Layer 2 board and rail" panel (lane portfolio-monitor). READ-ONLY.

Opens the built page (file://, no server) in headless Chromium, waits for the panel's tiles, and saves a PNG of the
panel section. Prints the PNG path and the panel's tile text.
usage: py -3 panel_shot.py <out.png> [page.html]   (default page: C:\\SyndicateProd\\portfolio_watch\\page\\dashboard.html)
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

out = Path(sys.argv[1])
page_path = Path(sys.argv[2] if len(sys.argv) > 2 else r"C:\SyndicateProd\portfolio_watch\page\dashboard.html")
out.parent.mkdir(parents=True, exist_ok=True)
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1180, "height": 900}, color_scheme="dark")
    page.goto(page_path.resolve().as_uri())
    page.wait_for_selector("#align-tiles .tile", timeout=20000)
    section = page.locator("#alignment")
    section.scroll_into_view_if_needed()
    section.screenshot(path=str(out))
    text = page.locator("#align-tiles").inner_text()
    browser.close()
print("saved", out)
print(text)
