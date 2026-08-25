"""Capture NCAAF game lines (moneyline / spread / total) from The Odds API.

`#557`. The NCAAF board had a projection on all 51 week-1 games and a price on
none, because `syndicate/features/ncaaf/cards.py` read lines from
`cfbd_lines_{season}_wk{week}.json` -- a path whose only two writers
(`fetch_ncaaf_market_lines.py`, `fetch_cfbd_lines.py`) have ZERO callers on any
service, and which exists in git at no SHA. This is the producer that was
missing.

WHERE THE DATA GOES, AND WHY THERE IS NO NEW FILE
-------------------------------------------------
Straight into the SHARED quote log, `append_book_quotes(sport="ncaaf", ...)`,
which is the same sink `fetch_nfl_team_odds_local.py` writes to. Three things
follow from that and none of them would from a bespoke file:

  1. `*_source/tracking/book_quotes/*.jsonl` is ALREADY in
     `HOT_ARTIFACT_PATTERNS` -- the globs are sport-agnostic -- so the capture
     crosses live-odds-worker -> web with no allowlist change. (Measured
     2026-08-25: the publisher is already pulling
     `ncaaf_source/tracking/book_quotes/<date>.jsonl` and finding it absent.)
  2. `run_refresh_worker.py`'s book-grid pass already loops over `ncaaf`, so
     these rows become `book_grid_<date>.json` on their own, which is what
     Layer 1 reads. Its `no_precomputed_grid_artifact` clears without a line of
     code.
  3. The cards board and Layer 1 end up on ONE line source instead of two that
     can disagree.

EVERY BOOK IS KEPT. `quote_rows_from_oddsapi_events` flattens the whole
`event -> bookmakers -> markets -> outcomes` nesting, so the log gets all
five-to-seven books in the response we already paid for -- which is what CLV and
best-price grading need later. The board's own aggregation across those books
lives in `syndicate/features/ncaaf/oddsapi_lines.py`, not here.

TEAM NAMES ARE THE RISK, NOT THE FETCH. OddsAPI sends "<School> <Mascot>"
("TCU Horned Frogs") while the board joins on CFBD's canonical name ("TCU"), and
`state.md` records that roughly 680 schools share mascots -- so a fuzzy match is
how another game's price lands on this card. Resolution is exact, refuses
ambiguity, and `--report` prints every name that did not resolve. RUN THAT FIRST
on any new season: an unresolved name is a game that will silently show no line.

USAGE
-----
    python scripts/fetch_ncaaf_oddsapi_game_lines.py --report
    python scripts/fetch_ncaaf_oddsapi_game_lines.py

Requires `ODDS_API_KEY` (or a `.env` beside the repo root). Region defaults to
`us` via `ODDS_API_REGION`; the sport key to `americanfootball_ncaaf` via
`ODDS_API_SPORT_NCAAF`.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.oddsapi_quota import record_oddsapi_quota

DEFAULT_SPORT_KEY = "americanfootball_ncaaf"


def _load_env() -> None:
    """Mirror `CfbdClient.from_env`'s ordering: process environment wins, `.env`
    fills the gap. Five NCAAF builders once died on a missing key with a
    populated `.env` beside them (`ncaaf_data_pipeline.md` section 3) -- same
    trap, same fix."""
    if os.environ.get("ODDS_API_KEY"):
        return
    try:
        from dotenv import load_dotenv
    except Exception:
        return
    for candidate in (REPO_ROOT / ".env", Path.cwd() / ".env"):
        if candidate.is_file():
            load_dotenv(candidate)
            if os.environ.get("ODDS_API_KEY"):
                return


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def _base_url() -> str:
    return _env("ODDS_API_BASE", "https://api.the-odds-api.com/v4") or "https://api.the-odds-api.com/v4"


def _market_map() -> dict[str, tuple[str, str]]:
    """Full-game keys only, from the shared vocabulary, used both to REQUEST and
    to TAG so the two cannot drift (`#343`).

    Interval markets are deliberately NOT requested. A first-quarter total shown
    as the game total is `learnings.md` 2026-08-21's exact failure -- a number
    that is right and labelled wrong -- and nothing on this board consumes
    segments yet, so asking for them would only spend credits.
    """
    from syndicate.features.shared.market_segments import full_game_market_keys

    return full_game_market_keys(("h2h", "spreads", "totals"))


def fetch_events(
    api_key: str,
    *,
    sport_key: str = DEFAULT_SPORT_KEY,
    region: str = "us",
    odds_format: str = "american",
    timeout: int = 25,
) -> list[dict[str, Any]]:
    markets = ",".join(sorted(_market_map().keys()))
    response = requests.get(
        f"{_base_url()}/sports/{sport_key}/odds",
        params={
            "apiKey": api_key,
            "regions": region,
            "markets": markets,
            "oddsFormat": odds_format,
        },
        timeout=timeout,
    )
    # response.url, not a rebuilt path: the recorder buckets by the markets that
    # actually went out, and redacts apiKey before persisting.
    record_oddsapi_quota(response.headers, sport="ncaaf", endpoint=response.url)
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, list) else []


def _event_team_names(events: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for event in events:
        for field in ("home_team", "away_team"):
            value = event.get(field)
            if value:
                names.append(str(value))
    return names


def append_quotes(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Flatten every book's game markets into the shared quote log.

    Sharded by each event's OWN commence date rather than by the run date. NFL's
    fetcher shards by run date because it has no week argument and refreshes
    daily; NCAAF cannot copy that, because week 1 spans ten calendar days
    (2026: 08-29 to 09-07) and the board reads the shard for the date a game
    actually kicks off. Sharding by run date would file every line under today
    and the board would find none of them.
    """
    from syndicate.features.shared.odds_book_quotes import (
        append_book_quotes,
        quote_rows_from_oddsapi_events,
    )

    now = datetime.now(tz=timezone.utc)
    captured_at = now.isoformat()
    market_map = _market_map()

    by_date: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        commence = str(event.get("commence_time") or "")[:10]
        if not commence:
            # No kickoff date means no shard the board would ever read it from.
            # Dropping it is honest; filing it under today is not.
            continue
        by_date.setdefault(commence, []).append(event)

    results: dict[str, Any] = {"dates": {}, "rows_appended": 0, "events": len(events)}
    for date_str, date_events in sorted(by_date.items()):
        rows = quote_rows_from_oddsapi_events(date_events, market_map=market_map)
        outcome = append_book_quotes(
            sport="ncaaf",
            date_str=date_str,
            rows=rows,
            captured_at=captured_at,
        )
        appended = int((outcome or {}).get("appended") or 0) if isinstance(outcome, dict) else 0
        results["dates"][date_str] = {"events": len(date_events), "rows": len(rows), "appended": appended}
        results["rows_appended"] += appended
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report",
        action="store_true",
        help="Fetch and print the team-name resolution report WITHOUT writing quotes. "
             "Run this first on a new season -- an unresolved name is a game that "
             "will silently show no line.",
    )
    parser.add_argument("--sport-key", default=None, help=f"OddsAPI sport key (default {DEFAULT_SPORT_KEY})")
    parser.add_argument("--region", default=None, help="OddsAPI region (default us)")
    parser.add_argument(
        "--events-json",
        default=None,
        help="Read events from a local JSON file instead of the API. For replaying a "
             "captured response offline; no credits are spent.",
    )
    args = parser.parse_args(argv)

    _load_env()

    if args.events_json:
        events = json.loads(Path(args.events_json).read_text(encoding="utf-8"))
        if not isinstance(events, list):
            print("[ncaaf_odds] events-json must contain a JSON array of events", flush=True)
            return 2
    else:
        api_key = _env("ODDS_API_KEY")
        if not api_key:
            print(
                "[ncaaf_odds] MISSING ODDS_API_KEY -- set it in the environment or a .env "
                "beside the repo root. Nothing was fetched.",
                flush=True,
            )
            return 2
        events = fetch_events(
            api_key,
            sport_key=args.sport_key or _env("ODDS_API_SPORT_NCAAF", DEFAULT_SPORT_KEY) or DEFAULT_SPORT_KEY,
            region=args.region or _env("ODDS_API_REGION", "us") or "us",
        )

    from syndicate.features.ncaaf.oddsapi_lines import resolution_report

    report = resolution_report(_event_team_names(events))
    print(
        f"[ncaaf_odds] EVENTS events={len(events)} teams={report['total']} "
        f"resolved={report['resolved']} unresolved={len(report['unresolved'])}",
        flush=True,
    )
    if report["unresolved"]:
        # Loud on purpose. Every name here is a game whose card shows no line,
        # and the symptom on the board (an empty market block) is identical to
        # "no book quoted it" -- so the only place the difference is visible is
        # this line.
        print(
            "[ncaaf_odds] UNRESOLVED_TEAMS "
            + ", ".join(repr(name) for name in report["unresolved"][:40]),
            flush=True,
        )
        print(
            "[ncaaf_odds] add these to _ODDSAPI_NAME_SUPPLEMENT in "
            "syndicate/features/ncaaf/oddsapi_lines.py",
            flush=True,
        )

    if args.report:
        return 0

    outcome = append_quotes(events)
    for date_str, detail in sorted(outcome["dates"].items()):
        print(
            f"[ncaaf_odds] QUOTES date={date_str} events={detail['events']} "
            f"rows={detail['rows']} appended={detail['appended']}",
            flush=True,
        )
    print(
        f"[ncaaf_odds] DONE events={outcome['events']} dates={len(outcome['dates'])} "
        f"rows_appended={outcome['rows_appended']}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
