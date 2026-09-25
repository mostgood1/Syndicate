#!/usr/bin/env python3
"""What every sport's sim data ACTUALLY delivers to the Layer 1 / Layer 2 boards.

WHY THIS EXISTS. "Which sports are done?" was answered by hand four times on
2026-09-24/25 and was wrong every time -- a matrix I wrote was stale or wrong in
FOUR of its eight rows within two hours, and each correction came from a
production reading I had not taken. `live_tier_coverage_check.py` (`#688`)
closed half the gap: it proves the WIRING exists. It reports `fail=0` for a
sport delivering nothing, because wiring is not delivery.

This is the other half. It reads PRODUCTION and reports, per sport:

  PREGAME  does the pregame sim reach the board  (Layer 1 `rows_with_projection`)
  LIVE     does the live re-sim reach the board  (book-grid `live_game_state`
           lens games/states, and `live_gameline_ledger` candidates/written)

Both come from HTTP APIs, deliberately. Every log-based attempt at this question
during that investigation was defeated by the same thing: the orchestrator runs
producers under `subprocess.run(capture_output=True)` and DISCARDS a successful
step's stdout, so an absent log line means nothing. An API payload cannot be
swallowed that way.

READ THE COLUMNS AS A LADDER, not as pass/fail. A sport with no games today is
not broken, and the probe says `no_games` rather than 0 so the two stay apart --
that distinction is the single most expensive thing to get wrong here.

Usage:
    py -3 scripts/board_delivery_probe.py                    # today, all sports
    py -3 scripts/board_delivery_probe.py --date 2026-09-27  # a Sunday NFL slate
    py -3 scripts/board_delivery_probe.py --sports nhl,nfl --json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

ALL_SPORTS = ("mlb", "nfl", "ncaaf", "nhl", "nba", "wnba", "soccer", "ncaab")
DEFAULT_BASE = "https://syndicate-an21.onrender.com"


def _admin_token() -> str:
    token = str(os.environ.get("ADMIN_TOKEN") or "").strip()
    if token:
        return token
    env_path = REPO_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.strip().startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() == "ADMIN_TOKEN":
                return value.strip().strip('"').strip("'")
    return ""


def _get(base: str, path: str, params: dict[str, str], token: str, timeout: float) -> Any:
    url = f"{base}{path}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"X-Admin-Token": token})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode())


# The UPSTREAM schedule, per sport. Without this the probe can report "no rows"
# and cannot say whether that is correct. That gap produced a FALSE REPORT on
# 2026-09-25: an empty future WNBA date was called a total board gap, when the
# pipeline was healthy and simply had no games. It also let NHL's real defect --
# four games upstream, zero on the board -- read the same as a quiet day.
#
# ESPN's scoreboard is one shape for seven sports. Soccer is league-scoped and
# deliberately returns UNKNOWN rather than a wrong zero: a sport whose schedule
# cannot be established must not be scored as "no games".
_ESPN_PATHS = {
    "mlb": "baseball/mlb",
    "nfl": "football/nfl",
    "ncaaf": "football/college-football",
    "nba": "basketball/nba",
    "wnba": "basketball/wnba",
    "ncaab": "basketball/mens-college-basketball",
    "nhl": "hockey/nhl",
}


def upstream_games(sport: str, date: str, *, timeout: float) -> int | None:
    """How many games the WORLD says exist, or None when unknowable."""
    path = _ESPN_PATHS.get(sport)
    if not path:
        return None
    url = (f"https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard"
           f"?dates={date.replace('-', '')}")
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode())
        return len(payload.get("events") or [])
    except Exception:
        return None


def probe_sport(sport: str, date: str, *, base: str, token: str, timeout: float) -> dict[str, Any]:
    out: dict[str, Any] = {"sport": sport, "date": date}

    # --- PREGAME: Layer 1 is the board the pregame projection has to reach.
    try:
        layer1 = _get(base, "/api/board/layer1", {"sport": sport, "date": date}, token, timeout)
        counts = layer1.get("counts") or {}
        out["games"] = counts.get("games")
        out["rows"] = counts.get("rows")
        out["rows_in_grid"] = counts.get("rows_in_grid")
        out["rows_other_dates"] = counts.get("rows_other_dates")
        out["rows_with_projection"] = counts.get("rows_with_projection")
        out["enrichment"] = layer1.get("enrichment")
        detail = layer1.get("enrichment_detail") or {}
        out["rows_modelled_fair"] = detail.get("rows_modelled_fair")
    except Exception as exc:  # noqa: BLE001
        out["layer1_error"] = f"{type(exc).__name__} {getattr(exc, 'code', '')}".strip()

    # --- LIVE: the book grid carries the live-lens fingerprint and the
    #     game-line ledger, which is where a live re-sim shows up or does not.
    try:
        grid = _get(base, "/api/board/book-grid", {"sport": sport, "date": date}, token, timeout)
        live_state = grid.get("live_game_state") if isinstance(grid.get("live_game_state"), dict) else {}
        fingerprint = live_state.get("lens_fingerprint") if isinstance(live_state.get("lens_fingerprint"), dict) else {}
        out["lens_games"] = live_state.get("lens_games")
        out["lens_states"] = fingerprint.get("states")
        out["lens_age_seconds"] = live_state.get("snapshot_age_seconds")
        ledger = grid.get("live_gameline_ledger") if isinstance(grid.get("live_gameline_ledger"), dict) else {}
        out["gameline_candidates"] = ledger.get("candidates")
        out["gameline_written"] = ledger.get("written")
        out["gameline_enabled"] = ledger.get("enabled")
    except Exception as exc:  # noqa: BLE001
        out["grid_error"] = f"{type(exc).__name__} {getattr(exc, 'code', '')}".strip()

    out["upstream_games"] = upstream_games(sport, date, timeout=min(timeout, 30.0))
    out["verdict"] = _verdict(out)
    return out


def _verdict(row: dict[str, Any]) -> str:
    """One word, and `no_games` is NOT a failure.

    Conflating "this sport has nothing scheduled" with "this sport delivers
    nothing" is the specific error this probe exists to stop making.
    """
    if row.get("layer1_error"):
        return "unreadable"
    games = row.get("games") or 0
    rows = row.get("rows") or 0
    in_grid = row.get("rows_in_grid") or 0
    upstream = row.get("upstream_games")

    # THE COMPARISON THIS PROBE EXISTS FOR. Games the world has and the board
    # does not is the defect; everything else about an empty board is weather.
    if upstream and not games:
        return "MISSING_FROM_BOARD"

    if not games and not rows:
        if upstream is None:
            # Unknowable upstream. Say so rather than scoring it as fine --
            # `no_games` here would be the same false clean this probe was
            # built to stop giving.
            return "no_board_rows_schedule_unknown"
        if in_grid:
            # Rows exist in the grid and the board scoped them out. THIS IS NOT
            # BY ITSELF A BUG and the verdict must not pretend otherwise: the
            # +/-8h capture window routinely puts an adjacent slate's rows in
            # today's shard, so a sport with nothing scheduled today reads this
            # way harmlessly (nfl and soccer on 2026-09-25, whose own game-day
            # boards are healthy -- nfl 09-27 is 14 games / 1474 rows).
            #
            # It is a BUG only when the sport HAS games today, which is the nhl
            # 2026-09-25 case: four games live, 18 rows in the grid, all scoped
            # out as 2026-09-24. This probe does not read the upstream schedule,
            # so it reports the SHAPE and refuses to classify it.
            return "grid_rows_other_dates"
        return "no_games"
    projected = row.get("rows_with_projection") or 0
    if not projected:
        return "pregame_missing"
    live_states = row.get("lens_states") or {}
    live_now = int(live_states.get("live") or 0) if isinstance(live_states, dict) else 0
    if live_now and not (row.get("gameline_written") or 0):
        return "live_not_delivered"
    if live_now:
        return "live_delivering"
    return "pregame_delivering"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--date", default=None, help="slate date; default = today, Central")
    parser.add_argument("--sports", default=",".join(ALL_SPORTS))
    parser.add_argument("--base-url", default=DEFAULT_BASE)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    date = args.date
    if not date:
        from syndicate.features.shared.timezone import central_today_iso

        date = central_today_iso()

    token = _admin_token()
    if not token:
        print("ADMIN_TOKEN not found in the environment or .env", flush=True)
        return 2

    sports = [s.strip().lower() for s in str(args.sports).split(",") if s.strip()]
    rows = [probe_sport(s, date, base=args.base_url, token=token, timeout=args.timeout) for s in sports]

    if args.json:
        print(json.dumps({"date": date, "rows": rows}, indent=1, sort_keys=True))
        return 0

    print(f"BOARD DELIVERY  date={date}  base={args.base_url}")
    header = (f"{'sport':7s} {'games':>5} {'rows':>6} {'proj':>6} {'proj%':>6} "
              f"{'fair':>5} {'up':>4} {'lens':>5} {'live':>4} {'cand':>5} {'writ':>5}  verdict")
    print(header)
    print("-" * len(header))
    for row in rows:
        games = row.get("games") or 0
        total = row.get("rows") or 0
        projected = row.get("rows_with_projection") or 0
        pct = f"{100 * projected / total:.0f}%" if total else "-"
        states = row.get("lens_states") if isinstance(row.get("lens_states"), dict) else {}
        print(f"{row['sport']:7s} {games:>5} {total:>6} {projected:>6} {pct:>6} "
              f"{row.get('rows_modelled_fair') or 0:>5} "
              f"{('?' if row.get('upstream_games') is None else row.get('upstream_games')):>4} "
              f"{row.get('lens_games') or 0:>5} "
              f"{int(states.get('live') or 0):>4} {row.get('gameline_candidates') or 0:>5} "
              f"{row.get('gameline_written') or 0:>5}  {row['verdict']}")
    print()
    print("verdicts: MISSING_FROM_BOARD (games exist upstream, board has none -- THE defect) |")
    print("          no_games (nothing scheduled -- NOT a failure) | "
          "grid_rows_other_dates (grid has rows the board scoped out;")
    print("          BENIGN when nothing is scheduled today, a DATE BUG when the sport has games -- check the schedule) |")
    print("          pregame_missing | pregame_delivering | "
          "live_not_delivered (games live, no game-line written) | live_delivering")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
