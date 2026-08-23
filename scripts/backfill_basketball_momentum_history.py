"""Backfill a SEASON of basketball event dumps from ESPN, one date at a time.

**THIS EXISTS BECAUSE WAITING IS THE EXPENSIVE OPTION AND NOBODY NEEDS TO.**
Live capture yields ~16 interval outcomes a night on a four-game slate, so a
quarter-level fit reaches 100 outcomes in about a week. ESPN's summary endpoint
is retrospectively complete for any past game, so the same season costs ~1.2
minutes of fetching for WNBA (286 games -> ~1,144 quarter outcomes) -- roughly
seventy nights of live capture.

The mirror cannot substitute: `live_pbp_stats_*.jsonl` persists only aggregates
(measured: 0 clock values across 37 files), and `game_cards_*.csv` carries 81
distinct games with odds but no plays. **There is no play-level history in this
repo at all.** That absence is the whole reason `#514` was filed.

## WHAT IT WRITES

The SAME `momentum_events_<date>.json` shape the live poller writes, so a
backfilled date and a captured one are indistinguishable downstream and
`basketball_projection_rows` reads both without knowing which is which.

It does NOT write the per-tick `live_momentum_*.jsonl`. That artifact is the
CAUSAL record -- what a card actually showed at instant t -- and a backfill has
no such history. Fabricating one would turn a reconstruction into a false claim
about what was displayed.

## MULTIPLE SEASONS, AND WHY THE SPLIT MUST BE BY SEASON

Three WNBA seasons is ~5.5 minutes and ~21 MB for **3,432 quarter outcomes**.
That is what turns a fit into a BACKTEST: fit on the earlier seasons, hold out
the most recent, and never look at the holdout until the design is frozen.

**THE SPLIT MUST BE TEMPORAL, NEVER RANDOM.** A random split puts quarters from
the same game -- and the same team, roster and season -- on both sides, so the
model is scored partly on states it effectively memorised. Every soccer and MLB
evaluation in this repo that has meant anything used a held-out period; the ones
that used pooled snapshots are the ones whose numbers had to be retracted.

**AND SEASONS ARE NOT EXCHANGEABLE.** Pace drifts, rules change, and the WNBA
literally added a team -- `GSV` (Golden State Valkyries) is in
`_canonical_wnba_tri`'s map and did not exist in earlier seasons. So a
multi-season fit needs pace checked per season before pooling, not assumed. If
pace has moved materially, pooling seasons without a season term will fit the
average of two different games.

Off-season dates cost one empty scoreboard call each, so pass a real season
window rather than a whole calendar year.

## RUNS ON THE WORKER

ESPN is 403 from a Claude Code sandbox. This is a one-shot job for
`refresh-worker`, reporting through the log collector.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterator

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.poll_basketball_momentum import _SPORT_PATH, fetch_summary, scoreboard_url
from syndicate.features.shared.basketball_momentum_artifacts import build_momentum_block
from syndicate.features.shared.basketball_momentum_artifacts import momentum_events_path
from syndicate.features.shared.basketball_momentum_artifacts import write_momentum_events

# Polite spacing between ESPN calls. The whole WNBA season is ~286 requests, so
# a quarter second each costs ~1.2 minutes and there is no reason to go faster.
_SLEEP_SECONDS = 0.25


def all_event_ids(league: str, date_str: str) -> list[str]:
    """Every event on a past date, regardless of state.

    `poll_basketball_momentum.live_event_ids` filters to `state == "in"`, which
    is right for live capture and wrong here: a backfill wants FINISHED games,
    and those read `post`.

    NO CUSTOM USER-AGENT. `site.api.espn.com` returns 403 to a browser-spoof UA
    from Render's egress -- measured 2026-08-22, and it cost most of a live
    slate before it was found. The sibling host `site.web.api.espn.com` used by
    `fetch_summary` has the OPPOSITE policy. Do not unify them.
    """
    url = scoreboard_url(league, date_str)
    try:
        with urllib.request.urlopen(url, timeout=25) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, TimeoutError) as exc:
        print(f"[backfill] SCOREBOARD_FAILED date={date_str} {type(exc).__name__}: {exc}",
              flush=True)
        return []

    out: list[str] = []
    for event in (payload.get("events") or []):
        if not isinstance(event, dict):
            continue
        event_id = str(event.get("id") or "").strip()
        if event_id:
            out.append(event_id)
    return out


def _dates(start: str, end: str) -> Iterator[str]:
    a = date.fromisoformat(start)
    b = date.fromisoformat(end)
    while a <= b:
        yield a.isoformat()
        a += timedelta(days=1)


def backfill_date(
    league: str, date_str: str, *, out_root: Path, overwrite: bool = False
) -> tuple[int, int]:
    """(games written, pressure rows). Returns (0, 0) for an empty date."""
    path = momentum_events_path(out_root, league_code=league, date_str=date_str)
    if path.exists() and not overwrite:
        # RESUMABLE BY DEFAULT. A season backfill that has to restart from the
        # top after any interruption is one that never finishes.
        print(f"[backfill] SKIP_EXISTING date={date_str} path={path}", flush=True)
        return (0, 0)

    event_ids = all_event_ids(league, date_str)
    if not event_ids:
        return (0, 0)

    games: dict[str, Any] = {}
    for event_id in event_ids:
        time.sleep(_SLEEP_SECONDS)
        summary = fetch_summary(league, event_id)
        if not summary:
            print(f"[backfill] SUMMARY_MISSING date={date_str} event={event_id}", flush=True)
            continue
        block = build_momentum_block(summary, league_code=league, include_rows=True)
        if block.get("pressure_rows"):
            games[event_id] = block
        else:
            # Named, not silently skipped: a date that quietly yields nothing is
            # indistinguishable from a date with no games, and only one is a bug.
            print(f"[backfill] NO_ROWS date={date_str} event={event_id} "
                  f"supported={block.get('supported')} reason={block.get('reason')!r}",
                  flush=True)
        del summary

    if not games:
        return (0, 0)

    payload = {"league": league, "date": date_str, "games": games}
    rows = write_momentum_events(payload, path=path)
    print(f"[backfill] WROTE date={date_str} games={len(games)} rows={rows} path={path}",
          flush=True)
    return (len(games), rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--league", default="wnba", choices=sorted(_SPORT_PATH))
    parser.add_argument("--start", required=True, help="ISO date, inclusive")
    parser.add_argument("--end", required=True, help="ISO date, inclusive")
    parser.add_argument("--data-root", default=None)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)

    if args.data_root:
        root = Path(args.data_root)
    else:
        from syndicate.features.shared.refresh_state_store import data_root
        root = data_root()

    total_games = total_rows = empty_dates = 0
    for date_str in _dates(args.start, args.end):
        games, rows = backfill_date(args.league, date_str, out_root=root,
                                    overwrite=args.overwrite)
        total_games += games
        total_rows += rows
        if not games:
            empty_dates += 1

    print(f"[backfill] DONE league={args.league} {args.start}..{args.end} "
          f"games={total_games} rows={total_rows} empty_dates={empty_dates}",
          flush=True)
    # Exit 3, not 0, on a backfill that wrote nothing -- a silent empty run is
    # how a broken fetch gets mistaken for an off-season.
    return 0 if total_games else 3


if __name__ == "__main__":
    raise SystemExit(main())
