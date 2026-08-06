"""Emit the result files prediction_reconciliation is already looking for (#214).

WHY THIS EXISTS
---------------
Settlement is not broken. It is STARVED.

`RECONCILIATION_ENABLE_REFRESH_WORKER_AUTORUN=true` on refresh-worker, and
`prediction_reconciliation.reconcile_prediction_results_for_date` settles by
globbing for `RECONCILIATION_PATTERNS` -- `closing_lines_{date}.csv`,
`game_results_{date}.json`, `recon_games_{date}.csv` and friends. When no file
matches, every prediction logs "no match found" and is skipped. No error, no
alarm, and `/api/portfolio/summary` reads `settled_count: 0` forever (measured on
production 2026-08-06: 5 tracked, 5 pending, avg_clv null).

Note which file it wants: a CLOSING LINES file. That is exactly what #208
established was never captured. The autorun has been waiting for an artifact the
capture defect guaranteed could not exist.

Both halves are now available:
  - closing prices come from the #209 per-book quote log via `closing_quotes()`,
    which is a lookup rather than the pregame->live stamp that structurally could
    not fire for rows without a commence_time;
  - final scores come from each sport's free results API -- deliberately NOT from
    our own graded artifacts, which carry the single-book contamination #211
    measured at 2.79 ROI points.

WHAT IT WRITES
--------------
ONE merged file, `closing_lines_{date}.csv`, and the merge is not tidiness --
it is required. `_match_result_row` picks the FIRST row matching a prediction and
reads the outcome AND the closing price off that single row. Emitting outcomes
and closing prices as two files means whichever matches first wins and the other
is never consulted, so a bet settles with a null closing price (caught by
test_reconciliation_settles_and_computes_price_clv before this was merged).

Each row therefore carries market identity + best closing price + the book that
offered it + the graded outcome where one is derivable.

Raw finals are also written to `finals_{date}.json` for inspection. That name is
deliberately NOT one of RECONCILIATION_PATTERNS: `game_results_{date}.json` would
be matched ahead of the merged file and reintroduce the exact bug above.

Files land in `reports/settlement_inputs/`, inside the roots reconciliation
already scans. No read-side change is needed: this makes an existing, enabled,
currently-idle autorun start finding files.

OUTCOME SOURCES, IN ORDER
-------------------------
1. `graded_outcomes.graded_rows_for_date(sport, date)` -- a grader registry that
   already exists for ALL EIGHT sports and yields `player`/`line`/`actual`/
   `result`, so it covers PROPS, not just game markets. An earlier version of
   this file claimed no actuals source was wired anywhere; that was wrong, and
   the correction matters because props are most of the volume.
2. MLB StatsAPI finals, for game markets. Kept as well as the graders rather than
   replaced by them: the graders read per-sport market-accuracy artifacts that
   are only populated on the worker disks, so on a cold checkout they return
   zero rows while StatsAPI still resolves. Two independent sources beat one.

Whatever a row cannot be graded by still ships with its closing price, so CLV is
ready the moment an outcome does exist. But note the ordering constraint: CLV is
written at SETTLEMENT, so a row that never grades never records CLV either.
`graded_rows` in the summary is the number to watch -- `closing_rows` alone says
how much price data exists, not how much of it can settle.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from syndicate.features.shared.odds_book_quotes import closing_quotes  # noqa: E402
from syndicate.features.shared.odds_book_quotes import read_book_quotes  # noqa: E402
from syndicate.features.shared.refresh_state_store import data_root  # noqa: E402

# Free, no OddsAPI credits. Only MLB is wired today; the others need their own
# results endpoint and are listed so the gap is explicit rather than silent.
STATSAPI_MLB = "https://statsapi.mlb.com/api/v1/schedule"
SPORTS_WITHOUT_RESULTS_SOURCE = ("nba", "wnba", "nhl", "nfl", "ncaaf", "ncaab", "soccer")


def _http_json(url: str, timeout: int = 120) -> Any:
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=timeout) as response:
            return json.loads(response.read())
    except Exception:
        return None


def _mlb_finals(date_str: str) -> list[dict[str, Any]]:
    payload = _http_json(f"{STATSAPI_MLB}?sportId=1&date={date_str}&hydrate=linescore")
    out: list[dict[str, Any]] = []
    for day in ((payload or {}).get("dates") or []):
        for game in (day.get("games") or []):
            if str(((game.get("status") or {}).get("abstractGameState")) or "") != "Final":
                continue
            teams = game.get("teams") or {}
            away, home = teams.get("away") or {}, teams.get("home") or {}
            away_name = str(((away.get("team") or {}).get("name")) or "").strip()
            home_name = str(((home.get("team") or {}).get("name")) or "").strip()
            if away.get("score") is None or home.get("score") is None:
                continue
            out.append(
                {
                    "sport": "mlb",
                    "date": date_str,
                    "event_id": str(game.get("gamePk") or ""),
                    "home_team": home_name,
                    "away_team": away_name,
                    "home_score": int(home["score"]),
                    "away_score": int(away["score"]),
                }
            )
    return out


def _graded_outcome_rows(sport: str, date_str: str) -> list[dict[str, Any]]:
    """Per-sport graded outcomes, including player props.

    Registered for all eight sports in graded_outcomes.GRADED_OUTCOME_GRADERS
    and yielding sport/market/selection/player/line/actual/result. Returns []
    rather than raising when a sport's underlying accuracy artifacts are absent,
    which is the normal state on any machine that is not the worker holding them.
    """
    try:
        from syndicate.features.shared.graded_outcomes import graded_rows_for_date

        return [row for row in (graded_rows_for_date(sport, date_str) or []) if isinstance(row, dict)]
    except Exception as exc:  # noqa: BLE001
        print(f"[settlement_inputs] grader failed sport={sport}: {type(exc).__name__}: {exc}", flush=True)
        return []


def _graded_index(rows: list[dict[str, Any]]) -> dict[tuple, dict[str, Any]]:
    """(player|'', market, selection) -> grading facts, for prop-level matching.

    Keyed on the player rather than the teams, because a prop's identity is the
    player and the market -- two players in the same game have entirely
    different outcomes for the same market name.
    """
    index: dict[tuple, dict[str, Any]] = {}
    for row in rows:
        player = str(row.get("player") or "").strip().lower()
        market = str(row.get("market") or "").strip().lower()
        selection = str(row.get("selection") or "").strip().lower()
        if not market:
            continue
        facts = {key: row[key] for key in ("actual", "result", "pnl") if row.get(key) is not None}
        if not facts:
            continue
        index[(player, market, selection)] = facts
        # Also keyed without the selection, so an Over row can grade an Under
        # bet off the same `actual` -- _row_outcome compares actual against the
        # row's own line and derives the side from the bet, not from here.
        if "actual" in facts:
            index.setdefault((player, market, ""), {"actual": facts["actual"]})
    return index


def _outcome_index(finals: list[dict[str, Any]]) -> dict[tuple, dict[str, Any]]:
    """(home, away, market, selection) -> the grading facts for that market.

    `actual` is whatever the market is ABOUT -- the run total for a total, the
    home margin for a spread -- because `_row_outcome` compares `actual` against
    the row's own line. One score therefore grades several different markets.
    Moneyline is graded outright here since it has no line to compare against.
    """
    index: dict[tuple, dict[str, Any]] = {}
    for final in finals:
        home, away = final["home_score"], final["away_score"]
        home_team, away_team = final["home_team"], final["away_team"]
        facts = {"home_score": home, "away_score": away, "final_event_id": final.get("event_id")}
        index[(home_team, away_team, "h2h", "home")] = {
            **facts, "result": "win" if home > away else ("push" if home == away else "loss")}
        index[(home_team, away_team, "h2h", "away")] = {
            **facts, "result": "win" if away > home else ("push" if home == away else "loss")}
        for selection in ("over", "under"):
            index[(home_team, away_team, "totals", selection)] = {**facts, "actual": home + away}
        index[(home_team, away_team, "spreads", "home")] = {**facts, "actual": home - away}
        index[(home_team, away_team, "spreads", "away")] = {**facts, "actual": away - home}
    return index


def _closing_rows(sport: str, date_str: str) -> list[dict[str, Any]]:
    """Best closing price per market, with the book that offered it.

    Best rather than an arbitrary book, because #211 measured that grading
    against one arbitrarily-chosen bookmaker cost 2.79 ROI points on an
    identical bet set. Settling against a single book's close would rebuild the
    same bias on the settlement side.
    """
    rows = read_book_quotes(sport, date_str)
    if not rows:
        return []
    closing = closing_quotes(rows)

    best_by_market: dict[tuple, dict[str, Any]] = {}
    for quote in closing.values():
        key = (
            quote.get("event_id"), quote.get("market"), quote.get("segment"),
            quote.get("selection"), quote.get("player_name"), quote.get("line"),
        )
        price = quote.get("price")
        if price is None:
            continue
        current = best_by_market.get(key)
        if current is None or int(price) > int(current.get("price") or -10**9):
            best_by_market[key] = quote

    out: list[dict[str, Any]] = []
    for quote in best_by_market.values():
        out.append(
            {
                "sport": quote.get("sport"),
                "date": date_str,
                "event_id": quote.get("event_id"),
                "home_team": quote.get("home_team"),
                "away_team": quote.get("away_team"),
                "market": quote.get("market"),
                "segment": quote.get("segment"),
                "selection": quote.get("selection"),
                "player_name": quote.get("player_name"),
                # `line` is the column reconciliation's _row_closing_line reads
                # first; closing_line is the explicit alias.
                "line": quote.get("line"),
                "closing_line": quote.get("line"),
                "closing_price": quote.get("price"),
                "closing_bookmaker": quote.get("bookmaker"),
                "book_updated_at": quote.get("book_updated_at"),
                "captured_at": quote.get("captured_at"),
            }
        )
    return out


DEFAULT_SPORTS = ("mlb", "nba", "wnba", "nhl", "nfl", "ncaaf", "ncaab", "soccer")


def emit_for_date(
    date_str: str,
    *,
    sports: list[str] | tuple[str, ...] = DEFAULT_SPORTS,
    out_dir: Path | None = None,
) -> dict[str, Any]:
    """Emit one date's merged settlement input file. The unit run_refresh_worker
    calls per target date, and what `main` loops over for the CLI."""
    target = Path(out_dir) if out_dir is not None else (data_root() / "settlement_inputs")
    target.mkdir(parents=True, exist_ok=True)

    closing: list[dict[str, Any]] = []
    for sport in sports:
        closing.extend(_closing_rows(str(sport).strip().lower(), date_str))

    finals: list[dict[str, Any]] = _mlb_finals(date_str) if "mlb" in sports else []
    outcomes = _outcome_index(finals)

    graded_by_sport: dict[str, dict[tuple, dict[str, Any]]] = {}
    for sport in sports:
        slug = str(sport).strip().lower()
        graded_by_sport[slug] = _graded_index(_graded_outcome_rows(slug, date_str))

    # THE MERGE. Reconciliation reads outcome and closing price off ONE matched
    # row, so they have to travel together -- see the module docstring. A row
    # with no derivable outcome still ships: it carries a real closing price and
    # grades the moment an outcome does exist.
    graded = 0
    for row in closing:
        facts = None
        # Graders first: they cover props, which are most of the volume and
        # which the team-keyed finals index cannot reach at all.
        by_player = graded_by_sport.get(str(row.get("sport") or "").strip().lower()) or {}
        if by_player:
            player = str(row.get("player_name") or "").strip().lower()
            market = str(row.get("market") or "").strip().lower()
            selection = str(row.get("selection") or "").strip().lower()
            facts = by_player.get((player, market, selection)) or by_player.get((player, market, ""))
        if not facts:
            facts = outcomes.get(
                (row.get("home_team"), row.get("away_team"), row.get("market"), row.get("selection"))
            )
        if not facts:
            continue
        row.update(facts)
        graded += 1

    closing_path = target / f"closing_lines_{date_str}.csv"
    finals_path = target / f"finals_{date_str}.json"

    if closing:
        fieldnames = sorted({key for row in closing for key in row})
        with closing_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(closing)
    if finals:
        finals_path.write_text(json.dumps({"date": date_str, "rows": finals}, indent=1), encoding="utf-8")

    for path in (closing_path, finals_path):
        if path.exists():
            try:
                from syndicate.features.shared.artifact_publisher import publish_hot_artifact

                publish_hot_artifact(path)
            except Exception as exc:  # noqa: BLE001
                print(f"[settlement_inputs] publish failed {path.name}: {type(exc).__name__}: {exc}", flush=True)

    # graded_rows is the number that actually matters: closing_rows alone says
    # how much price data exists, not how much of it can settle.
    print(
        f"[settlement_inputs] date={date_str} closing_rows={len(closing)} "
        f"graded_rows={graded} finals={len(finals)}",
        flush=True,
    )
    return {"date": date_str, "closing_rows": len(closing), "graded_rows": graded, "finals": len(finals)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", help="ISO date; defaults to yesterday UTC")
    parser.add_argument("--days", type=int, default=1, help="Number of dates ending at --date")
    parser.add_argument("--sports", default="mlb,nba,wnba,nhl,nfl,ncaaf,ncaab,soccer")
    parser.add_argument("--out-dir", default=None)
    args = parser.parse_args(argv)

    end_date = (
        datetime.fromisoformat(args.date).date()
        if args.date
        else (datetime.now(timezone.utc) - timedelta(days=1)).date()
    )
    sports = [item.strip().lower() for item in str(args.sports).split(",") if item.strip()]
    # data_root(), NOT reports_root(). run_refresh_worker's reconciliation
    # autorun passes `result_roots = [data_root()]` explicitly, precisely
    # because that is the persistent Render disk rather than the ephemeral code
    # checkout. Writing anywhere else means the autorun never globs these files
    # and settlement stays exactly as starved as before.
    out_dir = Path(args.out_dir) if args.out_dir else (data_root() / "settlement_inputs")
    out_dir.mkdir(parents=True, exist_ok=True)

    summary: list[dict[str, Any]] = []
    for offset in range(max(1, args.days)):
        date_str = (end_date - timedelta(days=offset)).isoformat()
        summary.append(emit_for_date(date_str, sports=sports, out_dir=out_dir))

    missing = [sport for sport in sports if sport in SPORTS_WITHOUT_RESULTS_SOURCE]
    if missing:
        # Say it rather than let a zero look like "no games that day". A silent
        # cap reads as coverage when it is absence.
        print(
            f"[settlement_inputs] NOTE no results source wired for: {','.join(missing)} -- "
            "closing lines are emitted for them, outcomes are not, so their bets stay pending.",
            flush=True,
        )
    print(json.dumps({"out_dir": str(out_dir), "dates": summary}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
