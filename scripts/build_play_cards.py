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
LOGO = REPO_ROOT / "syndicate" / "static" / "brand" / "syndicate_roi_badge.webp"
CENTRAL = timezone(timedelta(hours=-5))


def central_today() -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=5)).date().isoformat()


def chart_svg(values: list[float], labels: list[str], line: float | None, side: str | None) -> str:
    """Last-N bars (oldest left), the line dashed; green = cleared the bet's side, red = missed."""
    if not values or line is None:
        return '<svg viewBox="0 0 400 230"><text x="200" y="120" fill="#9db0bf" font-size="22" text-anchor="middle" font-family="Barlow">No recent games on file</text></svg>'
    w, h, pad, base = 400, 230, 10, 190
    top = max(max(values), float(line)) * 1.15 or 1.0
    n = len(values)
    bw = (w - 2 * pad) / n
    y = lambda v: base - (v / top) * (base - 20)
    parts = [f'<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg">']
    for i, v in enumerate(values):
        hit = v != line and ((v > line) if side in ("over", "yes") else (v < line))
        x = pad + i * bw + bw * 0.14
        color = "#8cff2e" if hit else "#ff5a4a"
        parts.append(f'<rect x="{x:.1f}" y="{y(v):.1f}" width="{bw * 0.72:.1f}" height="{base - y(v):.1f}" rx="3" fill="{color}"/>')
        parts.append(f'<text x="{x + bw * 0.36:.1f}" y="{y(v) - 6:.1f}" fill="#f4f7fa" font-size="17" font-weight="700" text-anchor="middle" font-family="Barlow">{v:g}</text>')
        lab = html.escape(str(labels[i] if i < len(labels) else "").split("-")[-1].split(" ")[-1])[:6]
        parts.append(f'<text x="{x + bw * 0.36:.1f}" y="{base + 22}" fill="#9db0bf" font-size="13" text-anchor="middle" font-family="Barlow">{lab}</text>')
    parts.append(f'<line x1="{pad}" x2="{w - pad}" y1="{y(float(line)):.1f}" y2="{y(float(line)):.1f}" stroke="#1fa8ff" stroke-width="3" stroke-dasharray="8 6"/>')
    parts.append(f'<text x="{w - pad}" y="{y(float(line)) - 8:.1f}" fill="#1fa8ff" font-size="17" font-weight="700" text-anchor="end" font-family="Barlow">line {float(line):g}</text>')
    parts.append("</svg>")
    return "".join(parts)


def kickoff_label(commence: str | None) -> str:
    if not commence:
        return ""
    try:
        t = datetime.fromisoformat(str(commence).replace("Z", "+00:00")).astimezone(CENTRAL)
    except ValueError:
        return ""
    return t.strftime("%a %-I:%M %p CT") if os.name != "nt" else t.strftime("%a %#I:%M %p CT")


def face_html(fields: dict[str, Any]) -> str:
    """Headshot with the team crest as a badge; the crest alone when there is no headshot; initials last."""
    e = lambda s: html.escape(str(s if s is not None else ""), quote=True)
    badge = f'<span class="badge"><img src="{e(fields["team_logo"])}" alt=""></span>' if fields.get("team_logo") else ""
    if fields.get("headshot"):
        return f'<div class="face"><img class="head" src="{e(fields["headshot"])}" alt="">{badge}</div>'
    if fields.get("team_logo"):
        return f'<div class="face"><img class="solo" src="{e(fields["team_logo"])}" alt=""></div>'
    initials = "".join(w[0] for w in str(fields.get("player") or "").split()[:2]).upper()
    return f'<div class="face"><span class="ini">{e(initials)}</span></div>'


def embed_card_images(fields: dict[str, Any], cache: Path) -> dict[str, Any]:
    """Inline the card's images (a PNG render and a shared HTML card must not depend on outside hosts)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("render_cheat_sheets", REPO_ROOT / "scripts" / "render_cheat_sheets.py")
    rcs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rcs)
    out = dict(fields)
    for key, size in (("headshot", 260), ("team_logo", 96), ("home_logo", 96), ("away_logo", 96)):
        if out.get(key):
            out[key] = rcs.data_uri(out[key], cache, size)
    return out


def render_card(fields: dict[str, Any], logo_uri: str) -> str:
    matchup = fields.get("matchup") or ""
    away, _, home = matchup.partition(" @ ")
    e = lambda s: html.escape(str(s if s is not None else ""))
    crest = lambda src: f'<img class="crest" src="{html.escape(src, quote=True)}" alt="">' if src else ""
    meta = " · ".join(str(x) for x in (fields.get("team"), fields.get("pos")) if x)
    hits = sum(1 for v in fields["form_values"] if v != fields["line"] and (
        (v > fields["line"]) if fields["side"] in ("over", "yes") else (v < fields["line"]))) if fields["form_values"] and fields["line"] is not None else 0
    caption = (f"{hits} of last {len(fields['form_values'])} cleared {fields['side']} {fields['line']:g}"
               if fields["form_values"] and fields["line"] is not None else "")
    return string.Template(TEMPLATE.read_text(encoding="utf-8")).safe_substitute(
        logo=logo_uri, label=e(fields["label"]), number=fields["number"], away=e(away), home=e(home),
        sport=e(fields["sport"]), kickoff=e(fields.get("kickoff_ct") or kickoff_label(fields.get("commence_time"))),
        player=e(fields["player"]), player_meta=e(meta), face=face_html(fields),
        away_crest=crest(fields.get("away_logo")), home_crest=crest(fields.get("home_logo")),
        bet=e(fields["bet"]), price=e(fields["price"]), book=e(fields["book"]), books=e(fields["books"]),
        fair=e(fields["fair"]), edge=e(fields["edge"]), win_prob=e(fields["win_prob"]),
        model_note=e(f" · model {fields['model_prob']}" if fields.get("model_prob") else ""),
        chart=chart_svg(fields["form_values"], fields["form_labels"], fields["line"], fields["side"]),
        chart_caption=e(caption), why="".join(f"<li>{e(w)}</li>" for w in fields["why"]),
        risk="".join(f"<li>{e(r)}</li>" for r in fields["risk"]))


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


def append_ledger(path: Path, records: list[dict[str, Any]]) -> int:
    seen = set()
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                seen.add(json.loads(line)["card_id"])
            except (ValueError, KeyError):
                continue
    new = [r for r in records if r["card_id"] not in seen]
    if new:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            for r in new:
                fh.write(json.dumps(r, default=str) + "\n")
    return len(new)


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
    logo_uri = "data:image/webp;base64," + base64.b64encode(LOGO.read_bytes()).decode()
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    pairs, records = [], []
    cache = root / "cheatsheets" / ".img_cache"
    for fields, row, sport in picked:
        html_path = out_dir / f"{fields['number']:02d}_{sport}_{fields['id']}.html"
        shown = fields if args.no_embed else embed_card_images(fields, cache)
        html_path.write_text(render_card(shown, logo_uri), encoding="utf-8")
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
