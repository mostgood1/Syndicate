"""Capture WNBA live pbp snapshots -- and REFUSE to store a skeleton.

`#454`. Lane `game-shape-capture` (scope addition).

WHY THE REFUSAL IS THE WHOLE DESIGN, and not a nicety.

`build_live_pbp_stats_payload` (`syndicate/features/wnba/cards.py:6390`) does not
compute pbp. It reads a stored snapshot and, when there is none with games,
returns a HARDCODED ALL-NULL SKELETON -- one entry per requested event id, with
`ok: True`, `pbp_quarters` all null, and empty possession/attempt maps. The real
computation (`_live_pbp_possession_stats`, `poss_est = FGA + TOV + 0.44*FTA -
OREB`) lives in `vendor/wnba_betting_repo/app.py`, not in Syndicate.

Two consequences, both measured 2026-08-16:

1. **A skeleton is indistinguishable from "nothing happened" to every
   consumer.** `ok: True` plus a complete structure reads as an answer. On a
   slate the user could see was two games final and one live, the endpoint
   returned three all-null records.
2. **A persisted skeleton is STICKY.** Line 6401 returns the stored payload
   whenever its `games` list is non-empty -- and a skeleton's is. So a skeleton
   written pregame is served in preference to real data for the rest of the day.
   Of 120 game records in the tracked mirror, **103 carry no possession data**;
   that population is consistent with stored skeletons rather than with games
   that had no plays.

So a capturer that stored whatever the endpoint returned would industrialise the
defect: it would fill a corpus with confident nulls, and every downstream count
would be a real number over a fake denominator. **This tool stores a record only
when it carries actual pbp signal, and reports skeletons as a separate counter
so the defect stays visible as a number.**

WHAT THIS DOES NOT DO. It does not fix `build_live_pbp_stats_payload`, and it
does not compute possessions itself -- inventing a second implementation of the
`poss_est` formula is how two numbers that should agree start disagreeing. It
captures what the endpoint genuinely produces, and says plainly when that is
nothing.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_BASE_URL = "https://syndicate-an21.onrender.com"
_NON_TEAM_KEYS = frozenset({"home", "away", "total", "unknown", "UNKNOWN"})


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def has_pbp_signal(game: Any) -> bool:
    """Does this record carry ANY real pbp content?

    The skeleton is `ok`-shaped and complete, so presence of the keys proves
    nothing -- only a non-null VALUE does. Any one of these is sufficient:
    a real possession estimate, a real attempt count, or a non-null quarter.
    """
    if not isinstance(game, Mapping):
        return False
    poss = game.get("pbp_possessions")
    if isinstance(poss, Mapping):
        for key, block in poss.items():
            if key in _NON_TEAM_KEYS or not isinstance(block, Mapping):
                continue
            try:
                if float(block.get("poss_est") or 0) > 0:
                    return True
            except (TypeError, ValueError):
                pass
    attempts = game.get("pbp_attempts")
    if isinstance(attempts, Mapping):
        for key, block in attempts.items():
            if key in _NON_TEAM_KEYS or not isinstance(block, Mapping):
                continue
            if any(v for v in block.values()):
                return True
    quarters = game.get("pbp_quarters")
    if isinstance(quarters, Mapping):
        totals = quarters.get("q_totals")
        if isinstance(totals, Mapping) and any(v is not None for v in totals.values()):
            return True
        current = quarters.get("current")
        if isinstance(current, Mapping) and current.get("period") is not None:
            return True
    return False


def classify(payload: Any) -> dict[str, Any]:
    """Split a payload's games into real vs skeleton. Never raises."""
    out = {"games": 0, "with_signal": 0, "skeleton": 0, "real_games": [], "error": None}
    if not isinstance(payload, Mapping):
        out["error"] = "payload_not_a_mapping"
        return out
    games = payload.get("games")
    if not isinstance(games, list):
        out["error"] = "games_not_a_list"
        return out
    for game in games:
        out["games"] += 1
        if has_pbp_signal(game):
            out["with_signal"] += 1
            out["real_games"].append(game)
        else:
            out["skeleton"] += 1
    return out


def fetch(base_url: str, date: str, *, ttl: int = 1, timeout: int = 45) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/wnba/api/live_pbp_stats?" + urllib.parse.urlencode(
        {"date": date, "ttl": ttl}
    )
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def capture_path(out_dir: Path, date: str) -> Path:
    return out_dir / f"wnba_pbp_capture_{date}.jsonl"


def append_capture(path: Path, payload: Mapping[str, Any], real_games: list[Any]) -> int:
    """Append ONE record carrying only the games with real signal.

    Skeletons are never written. The record keeps the payload's own
    `generated_at` so a later reader can order ticks without trusting file
    mtimes, and stamps its own capture time separately -- those are different
    clocks and conflating them has cost this repo before.
    """
    if not real_games:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "captured_at": _now_iso(),
        "source_generated_at": payload.get("generated_at"),
        "date": payload.get("date"),
        "requested_date": payload.get("requested_date"),
        "games": real_games,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, separators=(",", ":"), default=str) + "\n")
    return len(real_games)


def run_once(base_url: str, date: str, out_dir: Path, *, store: bool) -> dict[str, Any]:
    try:
        payload = fetch(base_url, date)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:160]}",
                "games": 0, "with_signal": 0, "skeleton": 0, "written": 0}
    result = classify(payload)
    written = 0
    if store and result["with_signal"]:
        written = append_capture(capture_path(out_dir, date), payload, result["real_games"])
    return {
        "ok": True,
        "generated_at": payload.get("generated_at"),
        "games": result["games"],
        "with_signal": result["with_signal"],
        "skeleton": result["skeleton"],
        "written": written,
        "error": result["error"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, help="Slate date, YYYY-MM-DD (Central).")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--out-dir", default="data/wnba_source/data/processed/pbp_capture")
    parser.add_argument("--interval", type=int, default=60, help="Seconds between polls.")
    parser.add_argument("--max-ticks", type=int, default=1,
                        help="How many polls to run. 1 = a single probe.")
    parser.add_argument("--probe", action="store_true",
                        help="Report only; never write. Use this to test whether the "
                             "endpoint is serving real data or a skeleton.")
    args = parser.parse_args(argv)

    out_dir = Path(args.out_dir)
    store = not args.probe
    totals = {"ticks": 0, "games": 0, "with_signal": 0, "skeleton": 0, "written": 0, "errors": 0}

    for tick in range(max(1, args.max_ticks)):
        result = run_once(args.base_url, args.date, out_dir, store=store)
        totals["ticks"] += 1
        if not result.get("ok"):
            totals["errors"] += 1
            print(f"[{tick + 1}] ERROR {result.get('error')}")
        else:
            for key in ("games", "with_signal", "skeleton", "written"):
                totals[key] += result.get(key) or 0
            print(f"[{tick + 1}] generated_at={result.get('generated_at')} "
                  f"games={result['games']} with_signal={result['with_signal']} "
                  f"skeleton={result['skeleton']} written={result['written']}")
        if tick + 1 < args.max_ticks:
            time.sleep(max(1, args.interval))

    print()
    print("TOTALS:", json.dumps(totals))
    if totals["games"] and not totals["with_signal"]:
        # This is the diagnostic that matters, and it must not read as success.
        print()
        print("  ALL RECORDS WERE SKELETONS. Nothing was stored, deliberately.")
        print("  The endpoint returned `ok: True` with a complete structure and no")
        print("  data. See this module's docstring: `build_live_pbp_stats_payload`")
        print("  emits an all-null skeleton when it has no stored snapshot, and a")
        print("  persisted skeleton is served in preference to real data thereafter.")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
