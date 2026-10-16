"""Render the day's Syndicate ROI play cards (lane `play-cards`): 1080 x 1350 PNGs + a review gallery + the ledger.

Reads `<data root>/cheatsheets/<sport>/<date>.json` (scripts/build_cheat_sheets.py), keeps only rows whose PRICE CHECK
passes (`syndicate.features.shared.play_cards.select`), fills `syndicate/templates/play_cards/card.html`, and
screenshots each card with Playwright/Chromium when it is installed (the Windows dev host has it; the fleet venv does
not -- without it the cards are written as HTML only). Every card is appended once to
`<data root>/playcards/ledger.jsonl` for `scripts/grade_play_cards.py` to settle at the close and on the result.

    py -3 scripts/build_play_cards.py --data-root //wsl.localhost/Ubuntu-24.04/home/amyn/syndicate-prod/data --sports nfl,ncaaf,nhl,soccer
"""
from __future__ import annotations

import argparse
import base64
import html
import json
import os
import string
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared import play_cards as pc  # noqa: E402

TEMPLATE = REPO_ROOT / "syndicate" / "templates" / "play_cards" / "card.html"


def central_today() -> str:
    return pc.central(datetime.now(timezone.utc)).date().isoformat()


chart_svg = pc.chart_svg
kickoff_label = pc.kickoff_label
hero_html = pc.hero_html
append_ledger = pc.append_ledger


def embed_card_images(fields: dict[str, Any], cache: Path) -> dict[str, Any]:
    """Inline the card's images (a PNG render and a shared HTML card must not depend on outside hosts)."""
    from syndicate.features.shared import cheat_sheet_images as img

    out = dict(fields)
    for key, size in (("headshot", img.CARD_SIZE), ("team_logo", img.LOGO_CARD_SIZE), ("home_logo", img.LOGO_CARD_SIZE),
                      ("away_logo", img.LOGO_CARD_SIZE), ("hero", img.HERO_SIZE), ("hero_away", img.HERO_SIZE),
                      ("hero_home", img.HERO_SIZE)):
        value = str(out.get(key) or "")
        if value.startswith("/cheatsheets/img/"):          # the sheet's cached copy (the hero is cached at 900px)
            out[key] = img.data_uri(value.rsplit("/", 1)[-1].split(".", 1)[0], cache)
        elif value:
            out[key] = img.data_uri(img.cache_image(value, cache, size), cache)
    return out


def render_card(fields: dict[str, Any], logo_uri: str) -> str:
    return pc.render_card(fields, logo_uri, TEMPLATE.read_text(encoding="utf-8"))


def to_png(cards: list[tuple[Path, Path]]) -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("PLAY_CARDS playwright not installed -- HTML cards only", flush=True)
        return 0
    done = 0
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1080, "height": 1350}, device_scale_factor=1)
        for html_path, png_path in cards:
            page.set_content(html_path.read_text(encoding="utf-8"), wait_until="networkidle")
            page.evaluate("document.fonts.ready")
            page.screenshot(path=str(png_path), clip={"x": 0, "y": 0, "width": 1080, "height": 1350})
            done += 1
        browser.close()
    return done


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-root", default=os.environ.get("SYNDICATE_DATA_ROOT") or "")
    ap.add_argument("--date", default=None)
    ap.add_argument("--sports", default="nfl,ncaaf,nhl,soccer,nba,wnba,ncaab,mlb")
    ap.add_argument("--per-sport", type=int, default=3)
    ap.add_argument("--label", default="FREE PLAY")
    ap.add_argument("--no-png", action="store_true")
    ap.add_argument("--no-embed", action="store_true", help="link images from their CDNs instead of inlining them")
    ap.add_argument("--no-ledger", action="store_true", help="render only (a preview run does not enter the record)")
    args = ap.parse_args(argv)
    if not args.data_root:
        print("REFUSING: no --data-root", flush=True)
        return 2
    root = Path(os.path.expanduser(args.data_root))
    date = args.date or central_today()
    sheets = []
    for sport in [s.strip() for s in args.sports.split(",") if s.strip()]:
        f = root / "cheatsheets" / sport / f"{date}.json"
        if f.is_file():
            sheets.append(json.loads(f.read_text(encoding="utf-8")))
    picked = pc.pick_cards(sheets, per_sport=args.per_sport, label=args.label)
    out_dir = root / "playcards" / date
    out_dir.mkdir(parents=True, exist_ok=True)
    logos = {}     # the sport's badge (its ball), embedded once per sport
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    pairs, records = [], []
    cache = root / "cheatsheets" / ".img_cache"
    for fields, row, sport in picked:
        html_path = out_dir / f"{fields['number']:02d}_{sport}_{fields['id']}.html"
        shown = fields if args.no_embed else embed_card_images(fields, cache)
        if sport not in logos:
            logos[sport] = "data:image/webp;base64," + base64.b64encode((pc.BRAND_DIR / pc.badge_name(sport)).read_bytes()).decode()
        html_path.write_text(render_card(shown, logos[sport]), encoding="utf-8")
        pairs.append((html_path, html_path.with_suffix(".png")))
        records.append(pc.ledger_record(fields, row, sport=sport, generated_at=generated_at))
    pngs = 0 if args.no_png else to_png(pairs)
    gallery = "".join(f'<figure><img src="{p.name}" alt=""><figcaption>{html.escape(h.name)}</figcaption></figure>'
                      if p.exists() else f'<iframe src="{h.name}" width="540" height="675"></iframe>' for h, p in pairs)
    (out_dir / "index.html").write_text(f"<!doctype html><meta charset=utf-8><title>Play cards {date}</title>"
                                        f"<style>body{{background:#04070c;color:#ccc;font-family:sans-serif;display:flex;flex-wrap:wrap;gap:16px;padding:16px}}"
                                        f"img{{width:540px}}</style>{gallery}", encoding="utf-8")
    added = 0 if args.no_ledger else append_ledger(root / "playcards" / "ledger.jsonl", records)
    print(f"PLAY_CARDS date={date} sheets={len(sheets)} cards={len(picked)} png={pngs} ledger_added={added} out={out_dir}", flush=True)
    for fields, _, sport in picked:
        print(f"  #{fields['number']} {sport} {fields['player']} {fields['bet']} {fields['price']} {fields['book']} edge {fields['edge']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
