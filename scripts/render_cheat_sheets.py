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
import hashlib
import io
import json
import os
import sys
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared import cheat_sheets as cs  # noqa: E402

TEMPLATE = REPO_ROOT / "syndicate" / "templates" / "cheat_sheets.html"
LOGO = REPO_ROOT / "syndicate" / "static" / "brand" / "syndicate_roi_badge.webp"
IMAGE_FIELDS = (("rows", ("headshot_url", "team_logo", "opponent_logo")), ("games", ("home_logo", "away_logo")))


def shrink(raw: bytes, size: int = 96) -> tuple[bytes, str]:
    try:
        from PIL import Image
    except ImportError:
        return raw, "image/png"
    with Image.open(io.BytesIO(raw)) as im:
        im = im.convert("RGBA")
        im.thumbnail((size, size))
        out = io.BytesIO()
        im.save(out, "WEBP", quality=82)
    return out.getvalue(), "image/webp"


def data_uri(url: str, cache: Path, size: int = 96) -> str | None:
    """The image as a data URI, fetched once per URL; None when it cannot be fetched (the page then falls back)."""
    if not url.startswith("https://"):
        return None
    key = hashlib.sha1(f"{size}|{url}".encode("utf-8")).hexdigest()
    hit = cache / f"{key}.bin"
    if hit.is_file():
        body = hit.read_bytes()
        return None if not body else "data:image/webp;base64," + base64.b64encode(body).decode()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Syndicate cheat sheets)"})
        with urllib.request.urlopen(req, timeout=12) as resp:
            body, _mime = shrink(resp.read(), size)
    except Exception:  # noqa: BLE001 -- a missing face is a fallback, not a failure
        body = b""
    cache.mkdir(parents=True, exist_ok=True)
    hit.write_bytes(body)                       # an empty file remembers a miss
    return None if not body else "data:image/webp;base64," + base64.b64encode(body).decode()


def embed_images(sheets: dict[str, dict[str, Any]], cache: Path) -> dict[str, int]:
    seen: dict[str, str | None] = {}
    counts = {"urls": 0, "embedded": 0}
    for sheet in sheets.values():
        for section, fields in IMAGE_FIELDS:
            for item in sheet.get(section) or []:
                for field in fields:
                    url = item.get(field)
                    if not url:
                        continue
                    if url not in seen:
                        seen[url] = data_uri(url, cache)
                        counts["urls"] += 1
                        counts["embedded"] += seen[url] is not None
                    item[field] = seen[url]
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
    counts = embed_images(payload, root / "cheatsheets" / ".img_cache") if args.embed_images else {}
    logo = "data:image/webp;base64," + base64.b64encode(LOGO.read_bytes()).decode()
    html = TEMPLATE.read_text(encoding="utf-8")
    data = json.dumps(payload, default=str).replace("</", "<\\/")
    html = html.replace("/*__DATA__*/null", data, 1).replace("__LOGO_SRC__", logo, 1)
    html = html.replace("<!--__SITE_HEAD__-->", "", 1).replace("<!--__SITE_HEADER__-->", "", 1)
    out = Path(args.out)
    out.write_text(html, encoding="utf-8")
    print(f"CHEAT_SHEET_PAGE {out} sports={list(payload)} rows={ {k: len(v['rows']) for k, v in payload.items()} } "
          f"images={counts} kb={round(out.stat().st_size / 1024)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
