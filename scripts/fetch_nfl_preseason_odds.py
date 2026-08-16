"""Fetch real NFL preseason market odds from OddsAPI.

Confirmed live 2026-08-05: `americanfootball_nfl_preseason` is a real,
active OddsAPI sport key (`GET /v4/sports` lists it, `active: true`) --
NOT the same key as the regular season (`americanfootball_nfl`). A real
call returned 1 real event (the Hall of Fame Game, CAR @ ARI) with 9 real
bookmakers already posting moneyline/spread/total lines.

Writes data/nfl_source/preseason_odds_{season}.csv -- one row per real
game with a real posted line, joined to the real preseason schedule
(schedule_preseason_{season}.csv, see fetch_nfl_preseason_schedule.py) by
team-pair for a real week number and game_id. Reuses
fetch_nfl_team_odds_local.py's team-name normalization, bookmaker
selection, and quota-recording helpers directly rather than duplicating
them.

preseason_odds_{season}.csv is opened in "w" mode on every run (confirmed
2026-08-05) -- it only ever reflects whatever games OddsAPI currently
lists as active for americanfootball_nfl_preseason. Once a game is
played, it drops out of OddsAPI's active-events response and its real
closing line disappears from this file with no history, which makes
after-the-fact ATS/totals grading permanently impossible for that game.
To prevent that, every run of this script also writes/appends to a dated
snapshot file, preseason_odds_snapshot_{season}_MM_DD.csv (MM_DD = the
date this script ran, i.e. the snapshot-taken day) -- see
write_preseason_odds_snapshot() for the exact durability contract and why
this convention (CSV-per-day, not the regular season's
real_betting_lines_{season}_MM_DD.json) was chosen.

Usage:
  python scripts/fetch_nfl_preseason_odds.py --season 2026
"""
from __future__ import annotations

import argparse
import csv
import os
import datetime as dt
import sys
from datetime import date
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import requests  # noqa: E402

from scripts.fetch_nfl_team_odds_local import get_base_url  # noqa: E402
from syndicate.features.shared.oddsapi_quota import record_oddsapi_quota  # noqa: E402
from scripts.fetch_nfl_preseason_schedule import preseason_schedule_path
from scripts.fetch_nfl_team_odds_local import _env
from scripts.fetch_nfl_team_odds_local import choose_bookmaker
from scripts.fetch_nfl_team_odds_local import fetch_odds
from scripts.fetch_nfl_team_odds_local import normalize_team_name
from syndicate.features.nfl.sources import default_nfl_source_root

DATA_ROOT = default_nfl_source_root()
PRESEASON_SPORT_KEY = "americanfootball_nfl_preseason"

ODDS_COLUMNS: tuple[str, ...] = (
    "game_id",
    "season",
    "week",
    "home_team",
    "away_team",
    "home_moneyline",
    "away_moneyline",
    "spread_home",
    "total_line",
    "book",
    "fetched_at",
)


def preseason_odds_path(season: int, *, data_root: Path | None = None) -> Path:
    root = data_root if data_root is not None else DATA_ROOT
    return root / f"preseason_odds_{season}.csv"


def load_schedule_lookup(season: int) -> dict[tuple[str, str], dict[str, str]]:
    """{(normalized_away_name, normalized_home_name): {game_id, week,
    home_team (real abbr), away_team (real abbr)}} from the real
    preseason schedule -- the join key is the normalized full team name
    (shared vocabulary between ESPN's schedule and OddsAPI's odds), the
    stored value keeps the real abbreviation so this script's own output
    stays consistent with every other preseason CSV's team-code
    convention."""
    path = preseason_schedule_path(season, source_root=DATA_ROOT)
    lookup: dict[tuple[str, str], dict[str, str]] = {}
    if not path.exists():
        return lookup
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            away_abbr = (row.get("away_team") or "").strip()
            home_abbr = (row.get("home_team") or "").strip()
            if not away_abbr or not home_abbr:
                continue
            away = normalize_team_name(away_abbr)
            home = normalize_team_name(home_abbr)
            lookup[(away, home)] = {
                "game_id": row.get("game_id", ""),
                "week": row.get("week", ""),
                "away_team": away_abbr,
                "home_team": home_abbr,
            }
    return lookup


def build_odds_rows(events: list[dict[str, Any]], schedule_lookup: dict[tuple[str, str], dict[str, str]], season: int) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    fetched_at = datetime.now(timezone.utc).isoformat()
    for event in events:
        away = normalize_team_name(event.get("away_team") or "")
        home = normalize_team_name(event.get("home_team") or "")
        matched = schedule_lookup.get((away, home))
        if not matched:
            continue
        bookmaker = choose_bookmaker(event.get("bookmakers") or [])
        if not bookmaker:
            continue

        moneyline_home = moneyline_away = spread_home = total_line = None
        for market in bookmaker.get("markets") or []:
            key = market.get("key")
            outcomes = market.get("outcomes", []) or []
            if key == "h2h":
                for outcome in outcomes:
                    name = normalize_team_name(outcome.get("name", ""))
                    if name == home:
                        moneyline_home = outcome.get("price")
                    elif name == away:
                        moneyline_away = outcome.get("price")
            elif key == "spreads":
                for outcome in outcomes:
                    name = normalize_team_name(outcome.get("name", ""))
                    if name == home:
                        spread_home = outcome.get("point")
            elif key == "totals":
                for outcome in outcomes:
                    if str(outcome.get("name") or "").strip().lower().startswith("over"):
                        total_line = outcome.get("point")

        rows.append(
            {
                "game_id": matched["game_id"],
                "season": str(season),
                "week": matched["week"],
                "home_team": matched["home_team"],
                "away_team": matched["away_team"],
                "home_moneyline": "" if moneyline_home is None else str(moneyline_home),
                "away_moneyline": "" if moneyline_away is None else str(moneyline_away),
                "spread_home": "" if spread_home is None else str(spread_home),
                "total_line": "" if total_line is None else str(total_line),
                "book": str(bookmaker.get("key") or ""),
                "fetched_at": fetched_at,
            }
        )
    return rows


def preseason_odds_snapshot_path(season: int, *, data_root: Path | None = None, snapshot_date: date | None = None) -> Path:
    root = data_root if data_root is not None else DATA_ROOT
    stamp = (snapshot_date or datetime.now(timezone.utc).date()).strftime("%m_%d")
    return root / f"preseason_odds_snapshot_{season}_{stamp}.csv"


def write_preseason_odds_snapshot(
    rows: list[dict[str, str]],
    *,
    season: int,
    data_root: Path | None = None,
    snapshot_date: date | None = None,
) -> Path:
    """Durable, dated copy of this run's odds rows -- the piece that
    actually prevents the data loss described in the module docstring.

    Design choice: a CSV keyed by the snapshot-taken date
    (preseason_odds_snapshot_{season}_MM_DD.csv), not the regular season's
    real_betting_lines_{season}_MM_DD.json
    (scripts/fetch_nfl_team_odds_local.py::write_daily_lines). Both mirror
    the same real precedent -- "one frozen file per calendar day, never
    touched again once that day has passed" -- but the regular season's
    JSON shape exists to reshape OddsAPI's response into a
    {"lines": {"AWAY @ HOME": {...}}} dict keyed by team pair for its own
    downstream readers; this script's rows are already flat, already
    game_id-keyed CSV records (identical shape to preseason_odds_{season}.csv
    itself), so writing another CSV is the zero-reshaping, least-risk
    choice -- it is literally the same row shape, just preserved instead of
    overwritten.

    Never overwrites a game_id already present in today's file: OddsAPI
    dropping a played game from its live response (this script's `rows`
    argument no longer containing that game_id on a later run) must not
    erase the row a prior run already captured for it today. New game_ids
    seen for the first time today are appended; a game_id already present
    keeps whatever row was recorded first (the earliest, closest-to-open
    line for that game, on that day).
    """
    path = preseason_odds_snapshot_path(season, data_root=data_root, snapshot_date=snapshot_date)
    existing_rows: list[dict[str, str]] = []
    existing_game_ids: set[str] = set()
    if path.exists():
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                existing_rows.append(row)
                existing_game_ids.add(str(row.get("game_id") or ""))

    new_rows = [row for row in rows if str(row.get("game_id") or "") not in existing_game_ids]

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(ODDS_COLUMNS))
        writer.writeheader()
        for row in existing_rows:
            writer.writerow(row)
        for row in new_rows:
            writer.writerow(row)
    return path


def _append_nfl_preseason_book_quotes(events: list[dict[str, Any]]) -> None:
    """Every book's preseason game-market price into the shared quote log.

    THIS WAS MISSING, and it is why NFL preseason never reached the board.
    Measured on production 2026-08-07: /api/board/book-grid?sport=nfl carried
    1,246 rows across 272 events whose commence_time ran 2026-09-10..2027-01-10
    -- entirely regular season -- while the one real preseason game in the
    window (CAR @ ARI, 2026-08-06) had no row at all. Matched by TEAM NAME, not
    event id: the board keys on OddsAPI's hex ids and the schedule on ESPN's
    numerics, so an id comparison reports "absent" for the wrong reason.

    The gap was plumbing, not fetching. `fetch_nfl_team_odds_local.py` is the
    only other NFL script that appends here and it pulls `americanfootball_nfl`
    -- regular season only. This script already pays for the real
    `americanfootball_nfl_preseason` key, then wrote its response to a CSV for
    the preseason cards page and dropped it. /api/board/book-grid reads
    book_quotes and nothing else, so those paid-for prices could never appear.

    Sharded under `sport="nfl"`, not a separate "nfl_preseason" slug: the board
    is keyed by sport slug, so a new slug would need a new board rather than
    populating the existing one. Preseason and regular-season events never
    collide -- distinct OddsAPI event ids.

    Mirrors `_append_nfl_team_book_quotes` deliberately, including never
    raising: a quote-log failure must not fail the odds refresh.
    """
    try:
        if not isinstance(events, list) or not events:
            return
        from syndicate.features.shared.odds_book_quotes import append_book_quotes, quote_rows_from_oddsapi_events

        now = datetime.now(tz=timezone.utc)
        rows = quote_rows_from_oddsapi_events(events, market_map=_nfl_segment_market_map())
        result = append_book_quotes(
            sport="nfl",
            date_str=now.date().isoformat(),
            rows=rows,
            captured_at=now.isoformat(),
        )
        print(f"[odds_book_quotes] nfl preseason quote_rows={len(rows)} appended={result.get('appended')}")
    except Exception as exc:
        print(f"[odds_book_quotes] nfl preseason append FAILED {type(exc).__name__}: {exc}")


def _preseason_segment_window_seconds() -> int:
    """How far before kickoff to start paying for interval markets.

    Default 4 hours, matching the value set for MLB on 2026-08-10 after the same
    tradeoff was made there. Env-tunable so the cost can be moved without a
    deploy.
    """
    raw = str(os.environ.get("SYNDICATE_NFL_PRESEASON_SEGMENT_WINDOW_SECONDS") or "").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 4 * 3600


def _fetch_preseason_event_segments(api_key: str, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per-event interval markets (Q1-Q4/H1-H2) for kickoffs inside the window.

    WHY PER-EVENT AT ALL (`#349`). The slate endpoint this script already calls
    serves the core three only; MLB's fetcher documents the same split and pays
    for segments on `/events/{id}/odds`. So requesting `totals_q1` on the slate
    call cannot work, and the interval vocabulary `_nfl_segment_market_map()`
    already builds had nothing feeding it -- measured 2026-08-11, all 121 NFL
    preseason rows were `segment: full`.

    WHY WINDOWED. This is `#16`/`#17`'s tradeoff restated: one slate call covers
    every game, while segments cost one call PER EVENT. At 16 preseason
    fixtures that is 16 credits per sweep against 1, so it is spent only on
    games about to kick off. A fixture two days out gets the core three and
    nothing else, which is what it had before this.

    Failure is per-event and non-fatal: a segment fetch that 404s or times out
    must not cost the slate its prices.
    """
    window = _preseason_segment_window_seconds()
    if window <= 0 or not events:
        return []
    now = dt.datetime.now(dt.timezone.utc)
    seg_keys = [key for key, spec in _nfl_segment_market_map().items() if spec[0] != "full"]
    if not seg_keys:
        return []
    enriched: list[dict[str, Any]] = []
    for event in events:
        event_id = str(event.get("id") or "").strip()
        raw_commence = str(event.get("commence_time") or "").strip()
        if not event_id or not raw_commence:
            continue
        try:
            kickoff = dt.datetime.fromisoformat(raw_commence.replace("Z", "+00:00"))
        except ValueError:
            continue
        until = (kickoff - now).total_seconds()
        # Inside the window, and not long finished. A negative `until` is a live
        # or recent game, which is exactly when interval lines matter most.
        if until > window or until < -6 * 3600:
            continue
        try:
            response = requests.get(
                f"{get_base_url()}/sports/{PRESEASON_SPORT_KEY}/events/{event_id}/odds",
                params={
                    "apiKey": api_key,
                    "regions": "us",
                    "markets": ",".join(seg_keys),
                    "oddsFormat": "american",
                },
                timeout=20,
            )
            record_oddsapi_quota(response.headers, sport="nfl", endpoint=response.url)
            if response.status_code != 200:
                continue
            payload = response.json()
        except Exception as exc:  # noqa: BLE001
            print(f"[nfl_preseason] segment fetch failed event={event_id} {type(exc).__name__}: {exc}", flush=True)
            continue
        if isinstance(payload, dict) and payload.get("bookmakers"):
            enriched.append(payload)
    print(
        f"[nfl_preseason] SEGMENT_FETCH window_s={window} events_in_window={len(enriched)} of {len(events)}",
        flush=True,
    )
    return enriched


def _nfl_segment_market_map() -> dict[str, tuple[str, str]]:
    """`#343`: full-game + Q1-Q4/H1-H2, from the shared vocabulary."""
    from syndicate.features.shared.market_segments import full_game_market_keys, segment_market_keys

    return {**full_game_market_keys(), **segment_market_keys("nfl")}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, required=True)
    args = parser.parse_args()

    api_key = _env("ODDS_API_KEY")
    if not api_key:
        raise RuntimeError("Missing ODDS_API_KEY environment variable")

    events = fetch_odds(api_key=api_key, sport_key=PRESEASON_SPORT_KEY, region="us", odds_format="american")
    # Before build_odds_rows, deliberately: that function drops any event it
    # cannot match against schedule_preseason_{season}.csv, and the quote log
    # should keep every price this response was paid for even when the schedule
    # mirror is stale -- which, measured 2026-08-07, it is.
    # Interval markets come from the per-event endpoint (`#349`); the slate call
    # above cannot serve them. Appended alongside the slate events so both land
    # in the same quote-log write, tagged by the shared vocabulary.
    segment_events = _fetch_preseason_event_segments(api_key, events)
    _append_nfl_preseason_book_quotes(events + segment_events)
    schedule_lookup = load_schedule_lookup(args.season)
    rows = build_odds_rows(events, schedule_lookup, args.season)

    path = preseason_odds_path(args.season)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(ODDS_COLUMNS))
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    # Always fetch + snapshot in the same run -- simplest, most robust
    # wiring: every real invocation of this script (including the existing
    # nfl_preseason_oddsapi_refresh RefreshStep in
    # scripts/refresh_odds_sources.py) durably preserves that run's lines
    # with no separate step to remember to wire in or that can drift out of
    # sync with the live fetch.
    snapshot_path = write_preseason_odds_snapshot(rows, season=args.season)

    # `flush=True`, and it is not cosmetic. THIS RUN'S RESULT WAS INVISIBLE.
    #
    # Measured 2026-08-16: the process was observed on live-odds-worker at
    # 00:24:36Z (caught in an ALL_PROCESS_MEMORY cmdline snapshot), and NOT ONE
    # of these four lines reached Render's log collector -- a `text=` search for
    # `events_fetched` across both workers over two days returned 0 matches.
    # Unflushed stdout in a short-lived subprocess is buffered and lost, which
    # is the failure mode `CLAUDE.md` already records as "logger.info never
    # reaches Render's log collector (use print(..., flush=True))". The one
    # print in this file that DOES carry it (the segment-fetch failure at :340)
    # is the one that shows up.
    #
    # THE COST OF THAT SILENCE, concretely: the NFL board carried zero rows for
    # 08-16..08-29 while 33 preseason games sat on the real schedule, and the
    # question "did this fetch return no events, or return them and fail to
    # append?" could not be answered from production at all. Both branches were
    # still open after an hour of log and artifact archaeology. These four
    # numbers would have closed it immediately.
    #
    # `events_fetched` is the one that matters most: it separates "the vendor
    # has no lines for this week yet" (a real, correct empty board) from "we
    # fetched them and lost them downstream" (a bug).
    print(f"[nfl_preseason] events_fetched={len(events)}", flush=True)
    print(f"[nfl_preseason] rows_matched={len(rows)}", flush=True)
    print(f"[nfl_preseason] odds_path={path}", flush=True)
    print(f"[nfl_preseason] snapshot_path={snapshot_path}", flush=True)
    # The commence-time span of what came back, so an empty or short board is
    # attributable to the FEED's horizon rather than guessed at. A run that
    # returns only this week's game and a run that returns three weeks of them
    # are different facts and previously serialised identically -- as nothing.
    _spans = sorted(
        str(event.get("commence_time") or "")[:10]
        for event in events
        if isinstance(event, dict) and event.get("commence_time")
    )
    print(
        f"[nfl_preseason] commence_dates={_spans[0] if _spans else 'none'}"
        f"..{_spans[-1] if _spans else 'none'} distinct={len(set(_spans))}",
        flush=True,
    )


if __name__ == "__main__":
    main()
