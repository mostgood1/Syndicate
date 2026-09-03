# -*- coding: utf-8 -*-
"""Pull production artifacts into a local cache ONE AT A TIME, resumably.

WHY THIS EXISTS RATHER THAN A LOOP OVER `/api/ops/artifacts/export`.

Measured 2026-09-02/03 while assembling a 22-date soccer backtest (~200 MB
across ~99 artifacts). A naive loop took the web service down and then could not
finish:

  * `web` is a **2 GB** container. Every export makes it read the artifact and
    JSON-encode it in memory, so a 9 MB file is a real allocation, not a stream.
    It sat at 1,726/2,048 MB with 322 MB headroom, then `oomKilled` at the 2Gi
    limit (`01:46:58Z`), then failed a health check (`02:15:54Z`).
  * After recovery it stayed UNSTABLE rather than uniformly slow. The SAME
    one-file request measured **7.2 / 7.1 / 7.2 s and then 43.2 s**, while a
    150-file request took 7.2 s in the same minute. A narrow request slower than
    a broad one rules out both tree-walk cost and payload cost.

THREE DESIGN CHOICES, each paid for by a failure:

1. **ONE REQUEST AT A TIME, with a pause sized to the payload.** The failure mode
   is concurrency and rapid succession, not request count.
2. **NO PRE-FLIGHT HEALTH CHECK.** The first version probed with a tiny request
   before each pull. That probe is *itself* an artifact export — one was measured
   at 43.2 s — so it cost as much as the thing it guarded, DOUBLED the load, and
   gated progress on a signal no more reliable than just attempting the fetch.
   Erratic latency wants a long timeout and a real backoff, not permission.
3. **WRITE EACH FILE THE MOMENT IT ARRIVES, and skip what is already cached.** A
   crash or a 502 then costs only the file in flight. The first run of this
   measurement lost everything to a single 502 because nothing was persisted --
   and the retry it did have never fired, because the ONE unwrapped call was the
   inventory request that runs first.

An empty result is cached as `{}` so a genuine absence is remembered and not
re-requested on every resume.

    python scripts/fetch_prod_artifacts_paced.py \
        --pattern "soccer_source/artifacts/soccer/odds_history/*.json" \
        --out-dir reports/prod_cache/odds_history --pause 45
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE = os.environ.get("SYNDICATE_OPS_BASE_URL", "https://syndicate-an21.onrender.com")
RETRYABLE = (408, 429, 500, 502, 503, 504)


def admin_token() -> str:
    """Same convention as `fetch_mlb_edge_scan_rows.py` -- the gitignored `.env`
    beside the repo, never argv, so the secret cannot reach a log or a prompt."""
    token = str(os.environ.get("ADMIN_TOKEN") or "").strip()
    if token:
        return token
    env = REPO_ROOT / ".env"
    if env.is_file():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("ADMIN_TOKEN="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("no ADMIN_TOKEN in the environment or .env")


def export(base: str, token: str, params: dict, timeout: int) -> dict:
    url = f"{base}/api/ops/artifacts/export?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"X-Admin-Token": token})
    with urllib.request.urlopen(request, timeout=timeout) as handle:
        return json.loads(handle.read().decode("utf-8"))


def safe_name(artifact_name: str) -> str:
    """A cache filename that cannot escape the output directory."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", artifact_name)


def fetch_one(base, token, pattern, dest: Path, pause: float, timeout: int, attempts: int) -> str:
    if dest.exists() and dest.stat().st_size > 0:
        return "cached"
    for attempt in range(attempts):
        started = time.time()
        try:
            artifacts = export(base, token, {"pattern": pattern}, timeout).get("artifacts") or {}
        except urllib.error.HTTPError as exc:
            if exc.code not in RETRYABLE or attempt == attempts - 1:
                print(f"    HTTP {exc.code} -- giving up on {pattern}", flush=True)
                return f"http_{exc.code}"
            wait = 30 * (2 ** attempt)
            print(f"    HTTP {exc.code} -- backing off {wait}s", flush=True)
            time.sleep(wait)
            continue
        except Exception as exc:  # timeouts, resets: the service is unstable, not gone
            if attempt == attempts - 1:
                print(f"    {type(exc).__name__} -- giving up on {pattern}", flush=True)
                return type(exc).__name__
            wait = 30 * (2 ** attempt)
            print(f"    {type(exc).__name__} -- backing off {wait}s", flush=True)
            time.sleep(wait)
            continue
        if not artifacts:
            dest.write_text("{}", encoding="utf-8")   # remember the ABSENCE
            return "absent"
        raw = list(artifacts.values())[0]
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(raw if isinstance(raw, str) else json.dumps(raw), encoding="utf-8")
        print(f"    cached {dest.stat().st_size/1e6:.1f} MB in {time.time()-started:.0f}s "
              f"-> pausing {pause:.0f}s", flush=True)
        time.sleep(pause)
        return "fetched"
    return "exhausted"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pattern", required=True,
                        help="artifact glob; expanded via names_only, then each match pulled singly")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--pause", type=float, default=45.0, help="seconds between fetches")
    parser.add_argument("--timeout", type=int, default=600,
                        help="per-request timeout; generous because latency is erratic, not because the service is dead")
    parser.add_argument("--attempts", type=int, default=6)
    parser.add_argument("--base-url", default=DEFAULT_BASE)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    token = admin_token()
    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = REPO_ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    # The inventory is a fetch too, and it is the one that runs FIRST -- so it
    # gets the same retry as everything else. Leaving it bare is exactly how the
    # first attempt at this died before any backoff could fire.
    inventory = out_dir / "_inventory.json"
    if inventory.exists():
        names = list(json.loads(inventory.read_text(encoding="utf-8")))
        print(f"inventory: {len(names)} artifact(s) (cached)", flush=True)
    else:
        names = []
        for attempt in range(args.attempts):
            try:
                payload = export(args.base_url, token, {"pattern": args.pattern, "names_only": "1"}, args.timeout)
                names = sorted((payload.get("artifacts") or {}))
                inventory.write_text(json.dumps(names), encoding="utf-8")
                break
            except Exception as exc:
                wait = 30 * (2 ** attempt)
                print(f"  inventory {type(exc).__name__} -- retry in {wait}s", flush=True)
                time.sleep(wait)
        if not names:
            print("could not read the inventory; nothing fetched")
            return 1
        print(f"inventory: {len(names)} artifact(s)", flush=True)

    if args.limit:
        names = names[:args.limit]
    print(f"estimated gentle-fetch time: ~{len(names)*args.pause/60:.0f} min "
          f"(one request at a time)\n", flush=True)

    tally: dict[str, int] = {}
    for i, name in enumerate(names, 1):
        dest = out_dir / safe_name(name)
        print(f"  [{i}/{len(names)}] {name}", flush=True)
        outcome = fetch_one(args.base_url, token, name, dest, args.pause, args.timeout, args.attempts)
        tally[outcome] = tally.get(outcome, 0) + 1

    print(f"\nDONE  {tally}")
    print(f"cache: {out_dir}")
    return 0 if tally.get("fetched", 0) or tally.get("cached", 0) else 2


if __name__ == "__main__":
    sys.exit(main())
