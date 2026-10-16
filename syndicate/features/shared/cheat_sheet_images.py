"""Headshots and logos for the cheat sheets and play cards, cached ONCE on the data root (lane `cheat-sheets`).

The GENERATOR fetches each image (free CDN GETs) and stores it under `<data root>/cheatsheets/.img_cache/<key>.bin`;
the web only serves those files by key (`/cheatsheets/img/<key>.webp`), so a page view never reaches an outside host
(the web/worker split) and the browser's PNG export can draw them (same origin -- a cross-origin image taints the
canvas and the export fails). An empty file remembers a miss, so a dead URL is not retried on every build.
"""
from __future__ import annotations

import base64
import hashlib
import io
import re
import urllib.request
from pathlib import Path

KEY_RE = re.compile(r"^[0-9a-f]{40}$")
ROW_SIZE = 96
CARD_SIZE = 260
HERO_SIZE = 900      # a play card's athlete (brand spec 2026-10-16: 40-60% of the card), `hero_image_px` in the brand JSON


def cache_dir(data_root: Path | str) -> Path:
    return Path(data_root) / "cheatsheets" / ".img_cache"


def cache_key(url: str, size: int) -> str:
    return hashlib.sha1(f"{size}|{url}".encode("utf-8")).hexdigest()


def shrink(raw: bytes, size: int) -> bytes:
    """`size` px on the long side, WebP. Without Pillow the original bytes are kept."""
    try:
        from PIL import Image
    except ImportError:
        return raw
    with Image.open(io.BytesIO(raw)) as im:
        im = im.convert("RGBA")
        im.thumbnail((size, size))
        out = io.BytesIO()
        im.save(out, "WEBP", quality=82)
    return out.getvalue()


def cache_image(url: str | None, cache: Path, size: int = ROW_SIZE, *, fetch: bool = True) -> str | None:
    """The cache key for `url` at `size`, fetching it once; None when it cannot be had."""
    if not url or not str(url).startswith("https://"):
        return None
    key = cache_key(str(url), size)
    hit = cache / f"{key}.bin"
    if hit.is_file():
        return key if hit.stat().st_size else None
    if not fetch:
        return None
    try:
        req = urllib.request.Request(str(url), headers={"User-Agent": "Mozilla/5.0 (Syndicate cheat sheets)"})
        with urllib.request.urlopen(req, timeout=12) as resp:
            body = shrink(resp.read(), size)
    except Exception:  # noqa: BLE001 -- a missing face is a fallback, not a failure
        body = b""
    cache.mkdir(parents=True, exist_ok=True)
    tmp = hit.with_name(hit.name + ".tmp")
    tmp.write_bytes(body)
    tmp.replace(hit)
    return key if body else None


def local_src(key: str | None) -> str | None:
    return f"/cheatsheets/img/{key}.webp" if key else None


def data_uri(key: str | None, cache: Path) -> str | None:
    if not key or not KEY_RE.match(key):
        return None
    path = cache / f"{key}.bin"
    try:
        body = path.read_bytes()
    except OSError:
        return None
    if not body:
        return None
    mime = "image/webp" if body[:4] == b"RIFF" else "image/png" if body[:4] == b"\x89PNG" else "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(body).decode()
