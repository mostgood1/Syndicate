"""Render the cheat sheets as ONE self-contained branded page (lane `cheat-sheets`) -- the same template `/cheatsheets`
serves, for publishing outside the app (an X post, a shared link).

The app page loads headshots and logos from their CDNs. A shared page should not depend on outside image hosts, so
`--embed-images` fetches each one ONCE (cached under `<data root>/cheatsheets/.img_cache/`), shrinks it to 96 px
WebP and inlines it. Free CDN GETs only; no OddsAPI.

    py -3 scripts/render_cheat_sheets.py --data-root //wsl.localhost/Ubuntu-24.04/home/amyn/syndicate-prod/data \
        --date 2026-10-14 --out cheat_sheets_2026-10-14.html --embed-images
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared import cheat_sheet_images as img  # noqa: E402
from syndicate.features.shared import cheat_sheets as cs  # noqa: E402

TEMPLATE = REPO_ROOT / "syndicate" / "templates" / "cheat_sheets.html"
LOGO = REPO_ROOT / "syndicate" / "static" / "brand" / "syndicate_roi_badge.webp"
IMAGE_FIELDS = (
    ("rows", (("headshot_url", "headshot_src"), ("team_logo", "team_logo_src"), ("opponent_logo", "opponent_logo_src"))),
    ("games", (("home_logo", "home_logo_src"), ("away_logo", "away_logo_src"))),
)


def embed_images(sheets: dict[str, dict[str, Any]], cache: Path) -> dict[str, int]:
    """Point every image at an inlined copy (fetched once into the generator's cache) -- a shared page must not depend
    on outside image hosts, and inlined images keep the page's own PNG export working."""
    seen: dict[str, str | None] = {}
    counts = {"urls": 0, "embedded": 0}
    for sheet in sheets.values():
        for section, fields in IMAGE_FIELDS:
            for item in sheet.get(section) or []:
                for url_field, src_field in fields:
                    url = item.get(url_field)
                    if not url:
                        continue
                    if url not in seen:
                        seen[url] = img.data_uri(img.cache_image(url, cache, img.ROW_SIZE), cache)
                        counts["urls"] += 1
                        counts["embedded"] += seen[url] is not None
                    item[src_field] = seen[url]
    return counts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-root", default=os.environ.get("SYNDICATE_DATA_ROOT") or "")
    ap.add_argument("--date", required=True)
    ap.add_argument("--sports", default=",".join(cs.SPORT_ORDER))
    ap.add_argument("--out", required=True)
    ap.add_argument("--embed-images", action="store_true")
    args = ap.parse_args(argv)
    if not args.data_root:
        print("REFUSING: no --data-root", flush=True)
        return 2
    root = Path(os.path.expanduser(args.data_root))
    sheets = []
    for sport in [s.strip() for s in args.sports.split(",") if s.strip()]:
        f = root / "cheatsheets" / sport / f"{args.date}.json"
        if f.is_file():
            sheets.append(json.loads(f.read_text(encoding="utf-8")))
    payload = cs.page_payload(sheets)
    counts = embed_images(payload, img.cache_dir(root)) if args.embed_images else {}
    logo = "data:image/webp;base64," + base64.b64encode(LOGO.read_bytes()).decode()
    meta = {"mode": "static", "date": args.date}
    html = TEMPLATE.read_text(encoding="utf-8")
    html = html.replace("/*__DATA__*/null", json.dumps(payload, default=str).replace("</", "<\\/"), 1)
    html = html.replace("/*__META__*/null", json.dumps(meta), 1).replace("__LOGO_SRC__", logo)
    html = html.replace("<!--__SITE_HEAD__-->", "", 1).replace("<!--__SITE_HEADER__-->", "", 1)
    out = Path(args.out)
    out.write_text(html, encoding="utf-8")
    print(f"CHEAT_SHEET_PAGE {out} sports={list(payload)} rows={ {k: len(v['rows']) for k, v in payload.items()} } "
          f"images={counts} kb={round(out.stat().st_size / 1024)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
