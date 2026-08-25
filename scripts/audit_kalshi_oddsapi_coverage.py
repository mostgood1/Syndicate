"""Print the exact evidence queries behind `kalshi_oddsapi_coverage_audit.md`.

WHY THIS IS A QUERY PRINTER AND NOT A FETCHER
--------------------------------------------------------------------------

Direct HTTP to Kalshi's hosts and to the live Syndicate service is BLOCKED
from these sandboxes (the agent proxy denies the host). A script that "checks
coverage" by calling Kalshi from here would return an empty page, and an empty
page is indistinguishable from a venue that lists nothing -- the exact false
negative `kalshi_catalogue.py`'s header exists to refuse. So this script makes
NO network call.

What it does instead is emit the `mcp__Render__list_logs` invocations that
produced every table in the audit, so the next reader RE-DERIVES the document
rather than trusting a snapshot of it. That is the only reproducibility
available given the network constraint, and it is worth more than a stale
table: the log lines below are still being written every few minutes.

`--gates` additionally prints the registry/vocabulary state from THIS
checkout, which is a local read and therefore always available. Compare it
against a live `AUTO_SERIES` line to see how far the deployed SHA has drifted
from `main` -- a distinction that mattered enormously on 2026-08-25, when the
fix landed live at 20:20:57Z in the middle of the audit and made every earlier
`unmapped_series` reading describe a system that no longer existed.

    python scripts/audit_kalshi_oddsapi_coverage.py            # the queries
    python scripts/audit_kalshi_oddsapi_coverage.py --gates    # local state too
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Same idiom as `scripts/refresh_odds_sources.py`: this script is run as
# `python scripts/...` from the repo root, so the package is not importable
# without it.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

WORKSPACE = "tea-d2bb5n95pdvs73cje4fg"
REFRESH_WORKER = "srv-d91dpertqb8s73co8ls0"
LIVE_ODDS_WORKER = "srv-d91dpertqb8s73co8lt0"

# (audit section, what the line answers, the `text` filter, which services)
#
# ORDERED BY THE GATE EACH ONE REPORTS, because that ordering is the whole
# point of the audit: the same symptom ("Kalshi has no market") has had five
# different causes, and only the log line that names the GATE distinguishes
# them.
QUERIES: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    (
        "§2 catalogue census",
        "THE ONLY CENSUS of what Kalshi lists. Counts SERIES, not markets. "
        "NBA's n INCLUDES WNBA's (substring match), and soccer has no line at "
        "all because it has no ticker token -- that is a property of the "
        "probe, not of Kalshi.",
        "[refresh_worker] KALSHI_SERIES_CATALOGUE",
        (REFRESH_WORKER,),
    ),
    (
        "§2 catalogue census",
        "Per-sport series samples from the same read. One line per sport, "
        "INCLUDING empty ones -- but only when the catalogue answered.",
        "[refresh_worker] KALSHI_SPORT ",
        (REFRESH_WORKER,),
    ),
    (
        "§2 truncation caveat",
        "The market listing. `truncated=True` on every run observed and "
        "~99.5% combinatorial, so every per-series count derived from it is a "
        "FLOOR. Do not read it as the catalogue.",
        "[kalshi_discovery] LISTED",
        (REFRESH_WORKER,),
    ),
    (
        "§3 registration (gate 1)",
        "What registered, prop vs game. `game_series` 173 -> 204 at "
        "2026-08-25T20:32:19Z is how the soccer title-prefix fix was measured.",
        "[kalshi_discovery] AUTO_SERIES ",
        (REFRESH_WORKER,),
    ),
    (
        "§7 gap table (gates 1 and 4)",
        "THE WORK QUEUE. `unmapped_series` means add a registry line; "
        "`stat_not_in_market_vocabulary` means add a `market_keys` entry, and "
        "carries the stat text VERBATIM in `detail=`. Different jobs. "
        "CAPPED AT 12 ROWS PER RUN -- against 68 gap series it under-reports "
        "~5x, so page across many runs.",
        "[kalshi_discovery] GAP series=",
        (REFRESH_WORKER,),
    ),
    (
        "§3 registration (gate 1)",
        "Series whose ticker names a sport we model and which NOTHING "
        "registered. Fires only when non-empty and once per process.",
        "SERIES_UNREGISTERED",
        (REFRESH_WORKER, LIVE_ODDS_WORKER),
    ),
    (
        "§4 ladders (gates 2b, 2c)",
        "THE LADDER EVIDENCE. `this_tick` carries each series' TRUE market "
        "count; `trimmed=` is what never reached the join's working set. "
        "MAX_MARKETS_PER_SERIES=400 truncated KXNCAAFSPREAD 1994->400.",
        "[kalshi_odds] TICK",
        (REFRESH_WORKER, LIVE_ODDS_WORKER),
    ),
    (
        "§4 capture layer",
        "The capture-first record, written from `full_markets` BEFORE both "
        "bounds -- whole ladders. `unparsed` currently keys on the refusal "
        "REASON rather than the series (recommendation #4).",
        "[kalshi_odds] DAILY_BOOK",
        (REFRESH_WORKER, LIVE_ODDS_WORKER),
    ),
    (
        "§5 the join (gate 5)",
        "Where capture stops being coverage. 2026-08-25T20:16:06Z: "
        "kalshi_markets=6000 matched=54, unreadable_title=3703 (62%). This is "
        "why the 'stop paying OddsAPI' table cannot yet be acted on.",
        "BOARD_JOIN",
        (REFRESH_WORKER,),
    ),
    (
        "§5 board demand",
        "THE HIGHEST-VALUE LINE FOR THIS QUESTION: it names a demand that went "
        "unmet. `board_wanted` is what the board asked for and found nothing "
        "for; `sources_offered` is who answered -- and Kalshi appears in none "
        "of its buckets on any reading taken 2026-08-25.",
        "VENUE_REPRICE_KEYS",
        (REFRESH_WORKER, LIVE_ODDS_WORKER),
    ),
)


def print_queries(start: str, end: str) -> None:
    print("# Evidence queries for docs/ai_context/kalshi_oddsapi_coverage_audit.md")
    print("#")
    print("# Run each with the Render MCP tool `mcp__Render__list_logs`.")
    print(f"# workspaceId = {WORKSPACE}")
    print(f"# refresh-worker   = {REFRESH_WORKER}")
    print(f"# live-odds-worker = {LIVE_ODDS_WORKER}")
    print("#")
    print("# `logger.info` NEVER reaches Render's collector -- only")
    print("# `print(..., flush=True)` does. Every line below is a print.")
    print("#")
    print("# Check the LIVE SHA FIRST (`list_deploys` on the refresh-worker).")
    print("# A reading from before a registry deploy describes a system that")
    print("# no longer exists, and mixing the two generations is the single")
    print("# easiest way to draw a wrong conclusion from this evidence.")
    print()
    for section, why, text, services in QUERIES:
        print(f"## {section}: {text!r}")
        for line in why.split(". "):
            line = line.strip().rstrip(".")
            if line:
                print(f"#   {line}.")
        print(
            json.dumps(
                {
                    "workspaceId": WORKSPACE,
                    "resource": list(services),
                    "text": [text],
                    "startTime": start,
                    "endTime": end,
                    "limit": 100,
                },
                indent=2,
            )
        )
        print()


def print_gates() -> None:
    """Registry and vocabulary state from THIS checkout. A local read."""
    from syndicate.features.shared.kalshi_catalogue import (
        SERIES_OUT_OF_SCOPE,
        SERIES_SPORT,
    )
    from syndicate.features.shared import market_keys

    print("# Local registry state (this checkout, NOT production)")
    print()
    by_sport: dict[str, list[str]] = {}
    for ticker, sport in sorted(SERIES_SPORT.items()):
        by_sport.setdefault(sport, []).append(ticker)
    print(f"SERIES_SPORT (hand-registered): {len(SERIES_SPORT)}")
    for sport, tickers in sorted(by_sport.items()):
        print(f"  {sport:>7}  {len(tickers):>2}  {' '.join(tickers)}")
    print()
    print(f"SERIES_OUT_OF_SCOPE: {len(SERIES_OUT_OF_SCOPE)}  "
          f"{' '.join(sorted(SERIES_OUT_OF_SCOPE))}")
    print()

    # THE GAP THAT IS INVISIBLE ANY OTHER WAY. `auto_series_from_catalogue`
    # refuses to register a prop series unless `canonical_market_key` resolves
    # its stat -- so a sport ABSENT from `_BY_SPORT` can never discover a
    # player prop, however many the venue lists. That is what kept 317 NFL
    # series at `classified_n=0` before football was added, and it is true of
    # nhl and ncaab in this checkout.
    print("_BY_SPORT prop vocabulary -- a sport ABSENT here can NEVER")
    print("auto-register a player-prop series (see market_keys' own header):")
    every = ("mlb", "nba", "wnba", "nhl", "nfl", "ncaaf", "ncaab", "soccer")
    for sport in every:
        table = market_keys._BY_SPORT.get(sport)
        mark = f"{len(table):>3} entries" if table else "  ** ABSENT **"
        print(f"  {sport:>7}  {mark}")
    print()
    print("_TOTAL_UNIT game-total vocabulary (game totals resolve without a")
    print("prop map, which is why a sport can price totals and no props):")
    for sport in every:
        units = market_keys._TOTAL_UNIT.get(sport)
        print(f"  {sport:>7}  {sorted(units) if units else '** ABSENT **'}")
    print()

    try:
        from syndicate.features.soccer.sources import LEAGUE_DISPLAY_NAMES
    except Exception as exc:  # pragma: no cover - import guard mirrors the module's
        print(f"soccer LEAGUE_DISPLAY_NAMES unavailable: {exc}")
        return
    print("Soccer competitions that can register, matched as a TITLE PREFIX.")
    print("A competition NOT on this list stays `unmapped_series` BY DESIGN --")
    print("UCL/UEL/UECL/EFL Cup are all absent, which is a product decision")
    print("rather than a defect:")
    for slug, display in sorted(LEAGUE_DISPLAY_NAMES.items()):
        print(f"  {slug:>19}  {display!r}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2026-08-25T12:00:00Z")
    parser.add_argument("--end", default="2026-08-25T21:00:00Z")
    parser.add_argument(
        "--gates",
        action="store_true",
        help="also print registry/vocabulary state from this checkout",
    )
    args = parser.parse_args()
    print_queries(args.start, args.end)
    if args.gates:
        print()
        print_gates()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
