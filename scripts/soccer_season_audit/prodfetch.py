# -*- coding: utf-8 -*-
"""Batched, paced pull of production soccer artifacts for the season audit.

One request at a time (web is a 2 GB container that OOM'd on rapid exports,
see scripts/fetch_prod_artifacts_paced.py). Unlike that script, a pattern may
return several small files in ONE response, so the audit takes tens of requests
rather than thousands. Every file is written the moment its batch lands, and a
batch already on disk is skipped on resume.

    py -3 prodfetch.py inventory "<glob>" <out_dir>
    py -3 prodfetch.py batch "<glob>" <out_dir> [pause_s]
"""
import json
import re
import sys
import time
import urllib.error
from pathlib import Path

import os  # noqa: E402

PRIMARY = Path(os.environ.get("SYNDICATE_REPO_ROOT") or Path(__file__).resolve().parents[2])
sys.path.insert(0, str(PRIMARY / "scripts"))
from fetch_prod_artifacts_paced import DEFAULT_BASE, admin_token, export  # noqa: E402

RETRYABLE = (408, 429, 500, 502, 503, 504)


def safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)


def call(params: dict, timeout: int = 600, attempts: int = 6) -> dict:
    token = admin_token()
    for attempt in range(attempts):
        try:
            return export(DEFAULT_BASE, token, params, timeout)
        except urllib.error.HTTPError as exc:
            if exc.code not in RETRYABLE or attempt == attempts - 1:
                raise
        except Exception:
            if attempt == attempts - 1:
                raise
        wait = 30 * (2 ** attempt)
        print(f"    retry in {wait}s", flush=True)
        time.sleep(wait)
    return {}


def inventory(pattern: str, out_dir: Path) -> list[str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()
    names = sorted((call({"pattern": pattern, "names_only": "1"}).get("artifacts") or {}))
    (out_dir / "_inventory.json").write_text(json.dumps(names), encoding="utf-8")
    print(f"inventory {len(names)} names in {time.time()-started:.1f}s  ({pattern})", flush=True)
    return names


def batch(pattern: str, out_dir: Path, pause: float) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    marker = out_dir / f"_done_{safe(pattern)}"
    if marker.exists():
        print(f"  cached batch {pattern}", flush=True)
        return 0
    started = time.time()
    arts = call({"pattern": pattern}).get("artifacts") or {}
    total = 0
    for name, raw in arts.items():
        text = raw if isinstance(raw, str) else json.dumps(raw)
        (out_dir / safe(name)).write_text(text, encoding="utf-8")
        total += len(text)
    marker.write_text(str(len(arts)), encoding="utf-8")
    print(f"  {pattern}: {len(arts)} files {total/1e6:.2f} MB in {time.time()-started:.1f}s", flush=True)
    time.sleep(pause)
    return len(arts)


if __name__ == "__main__":
    mode, pattern, out = sys.argv[1], sys.argv[2], Path(sys.argv[3])
    if mode == "inventory":
        inventory(pattern, out)
    else:
        batch(pattern, out, float(sys.argv[4]) if len(sys.argv) > 4 else 8.0)
