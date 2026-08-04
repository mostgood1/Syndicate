"""One grading contract for every sport's evaluation-ledger settlement.

Context: Syndicate learning loop (docs/reports/syndicate_learning_loop_plan_2026_08_03.md), Stage 1.
See also: docs/ai_context/architecture.md

Role:
- `graded_rows_for_date(sport, date_str)` is the single entrypoint
  evaluation_settlement.settle_ledger_for_date should call. Before this
  module, settlement hardcoded a two-sport allowlist (_SUPPORTED_SPORTS =
  ("mlb", "wnba")) because grading was implemented ad hoc, once per sport,
  inline in evaluation_settlement.py -- the reason 6 of 8 sports could
  never be settled wasn't missing data, it was a missing adapter.
- Every grader below returns the SAME row shape
  match_graded_row/_pnl_for_settlement already consume (sport, market,
  selection, player, team, home, away, title, line, actual, odds, result,
  pnl, closing_price) -- this module does not change the matching
  contract, only centralizes who is allowed to answer "what happened".

Constraints:
- Read-only against each sport's own already-graded/scored artifacts;
  mirrors evaluation_settlement.py's own constraint of never recomputing a
  join a sport's own module already does.
- A sport with no real grader yet returns [] rather than raising, so an
  unmatched ledger record for that sport is correctly attributed to
  "no graded rows available" (evaluation_settlement's own diagnostic
  breakdown) instead of crashing settlement for every other sport.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Callable, Mapping


GradedRowGrader = Callable[[str], list[dict[str, Any]]]

# Documented, not enforced: the canonical GradedOutcome shape every grader
# below produces (a superset across sports -- most rows only populate the
# fields relevant to their own market). Kept as a plain dict, not a
# dataclass/TypedDict, because match_graded_row/_pnl_for_settlement already
# consume these as Mapping[str, Any] and every existing per-sport source
# (market_accuracy payloads, performance logs) is naturally dict-shaped --
# wrapping and unwrapping a dataclass at every call site would add
# conversion cost without changing what's actually validated.
GRADED_OUTCOME_FIELDS = (
    "sport", "market", "selection", "player", "team", "home", "away",
    "title", "line", "actual", "odds", "result", "pnl", "closing_price",
)


def _unavailable_graded_rows_for_date(_date_str: str) -> list[dict[str, Any]]:
    return []


# ---------------------------------------------------------------------------
# MLB / WNBA / NBA / NHL -- all four already flow through the same
# "days -> games.rows / props.rows" shape (live_lens_local.build_local_market_accuracy_payload
# for wnba/nba/nhl; MLB has its own equivalent by-kind structure). One
# generic extractor handles all of them; only the payload-builder and the
# per-row field names differ slightly.
# ---------------------------------------------------------------------------


def _mlb_graded_rows_for_date(date_str: str) -> list[dict[str, Any]]:
    from syndicate.features.mlb.market_accuracy import build_market_accuracy_payload

    try:
        payload = build_market_accuracy_payload(f"date={date_str}")
    except Exception:
        return []
    if not isinstance(payload, dict):
        return []

    rows: list[dict[str, Any]] = []
    for day in payload.get("days") or []:
        if not isinstance(day, dict) or str(day.get("date") or "") != date_str:
            continue
        by_kind = day.get("rows") if isinstance(day.get("rows"), dict) else {}
        kind_rows = by_kind.get("official") or by_kind.get("playable") or by_kind.get("all") or []
        for row in kind_rows:
            if not isinstance(row, dict):
                continue
            result = str(row.get("result") or "").strip().lower()
            if result not in {"win", "loss", "push", "void"}:
                continue
            rows.append(
                {
                    "sport": "mlb",
                    "market": row.get("market"),
                    "selection": row.get("selection"),
                    "player": row.get("player_name"),
                    "team": row.get("team"),
                    "title": row.get("title"),
                    "line": row.get("line"),
                    "actual": row.get("actual"),
                    "odds": row.get("odds"),
                    "result": result,
                    "pnl": row.get("profit_u"),
                }
            )
    return rows


def _local_market_accuracy_graded_rows_for_date(
    sport: str, date_str: str, *, build_payload: Callable[[str], dict[str, Any] | None]
) -> list[dict[str, Any]]:
    try:
        payload = build_payload(f"date={date_str}")
    except Exception:
        return []
    if not isinstance(payload, dict):
        return []

    rows: list[dict[str, Any]] = []
    for day in payload.get("days") or []:
        if not isinstance(day, dict) or str(day.get("date") or "") != date_str:
            continue
        games = day.get("games") if isinstance(day.get("games"), dict) else {}
        for row in games.get("rows") or []:
            if not isinstance(row, dict):
                continue
            result = str(row.get("result") or "").strip().lower()
            if result not in {"win", "loss", "push", "void"}:
                continue
            rows.append(
                {
                    "sport": sport,
                    "market": row.get("market"),
                    "selection": row.get("side"),
                    "home": row.get("home"),
                    "away": row.get("away"),
                    "line": row.get("line"),
                    "actual": row.get("actual"),
                    "odds": row.get("price"),
                    "result": result,
                }
            )
        props = day.get("props") if isinstance(day.get("props"), dict) else {}
        for row in props.get("rows") or []:
            if not isinstance(row, dict):
                continue
            result = str(row.get("result") or "").strip().lower()
            if result not in {"win", "loss", "push", "void"}:
                continue
            rows.append(
                {
                    "sport": sport,
                    "market": row.get("market"),
                    "selection": row.get("side"),
                    "player": row.get("player"),
                    "team": row.get("team"),
                    "line": row.get("line"),
                    "actual": row.get("actual"),
                    "odds": row.get("price"),
                    "result": result,
                }
            )
    return rows


def _wnba_graded_rows_for_date(date_str: str) -> list[dict[str, Any]]:
    from syndicate.features.shared.live_lens_local import build_local_market_accuracy_payload
    from syndicate.features.wnba.sources import processed_root

    root = processed_root()
    return _local_market_accuracy_graded_rows_for_date(
        "wnba", date_str, build_payload=lambda qs: build_local_market_accuracy_payload(qs, root)
    )


def _nba_graded_rows_for_date(date_str: str) -> list[dict[str, Any]]:
    from syndicate.features.nba.market_accuracy import build_market_accuracy_payload

    return _local_market_accuracy_graded_rows_for_date("nba", date_str, build_payload=build_market_accuracy_payload)


def _nhl_graded_rows_for_date(date_str: str) -> list[dict[str, Any]]:
    from syndicate.features.nhl.market_accuracy import build_market_accuracy_payload

    return _local_market_accuracy_graded_rows_for_date("nhl", date_str, build_payload=build_market_accuracy_payload)


# ---------------------------------------------------------------------------
# NFL -- schedule_{season}.csv carries the real closing spread/total/
# moneyline numbers AND the game date AND (once played) the final score,
# all keyed by the same game_id. smartsim2_performance_tracking's own
# log (smartsim2_performance_log.jsonl) does NOT carry a date, only
# season/week, and it grades the MODEL's pick, not an arbitrary
# selection+line -- neither is directly usable as a generic "what would an
# arbitrary bet on this game have graded as" ladder the way MLB/WNBA's
# market_accuracy rows already are. Build that ladder straight from the
# schedule file instead: one graded row per side per market
# (moneyline/spread/total), which needs nothing but the closing numbers
# already on that row and the final score -- no model attribution needed,
# mirroring how MLB/WNBA's own graded rows don't care which model
# recommended a selection either.
# ---------------------------------------------------------------------------


def _read_schedule_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    except Exception:
        return []


def _to_float(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except Exception:
        return None


def _nfl_schedule_paths() -> list[Path]:
    from syndicate.features.nfl.sources import default_nfl_source_root

    root = default_nfl_source_root() / "data"
    if not root.exists():
        return []
    # Every schedule_{season}.csv the mirror has on disk -- scanning all of
    # them (rather than guessing a season from date_str's year, which is
    # wrong for the January stub of a season that started the prior
    # calendar year) so a January date still resolves against the right file.
    return sorted(root.glob("schedule_*.csv"))


def _nfl_graded_rows_for_date(date_str: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for schedule_path in _nfl_schedule_paths():
        for game in _read_schedule_csv(schedule_path):
            if str(game.get("gameday") or "").strip() != date_str:
                continue
            home_score = _to_float(game.get("home_score"))
            away_score = _to_float(game.get("away_score"))
            if home_score is None or away_score is None:
                continue
            home_team = str(game.get("home_team") or "").strip()
            away_team = str(game.get("away_team") or "").strip()
            title = f"{away_team} @ {home_team}"
            actual_margin = home_score - away_score
            actual_total = home_score + away_score
            spread_line = _to_float(game.get("spread_line"))
            total_line = _to_float(game.get("total_line"))
            home_moneyline = _to_float(game.get("home_moneyline"))
            away_moneyline = _to_float(game.get("away_moneyline"))

            def _ml_result(margin_for_side: float) -> str:
                if margin_for_side == 0:
                    return "push"
                return "win" if margin_for_side > 0 else "loss"

            rows.append({"sport": "nfl", "market": "moneyline", "selection": home_team, "home": home_team, "away": away_team, "title": title, "actual": home_score, "odds": home_moneyline, "result": _ml_result(actual_margin)})
            rows.append({"sport": "nfl", "market": "moneyline", "selection": away_team, "home": home_team, "away": away_team, "title": title, "actual": away_score, "odds": away_moneyline, "result": _ml_result(-actual_margin)})

            if spread_line is not None:
                # schedule_line convention (nfl/cards.py): spread_line is the
                # home team's own number (negative favors home), matching
                # the sign _nfl_market_board_rows_for_game already assumes.
                def _spread_result(covers_margin: float) -> str:
                    if covers_margin == 0:
                        return "push"
                    return "win" if covers_margin > 0 else "loss"

                rows.append({"sport": "nfl", "market": "spread", "selection": home_team, "home": home_team, "away": away_team, "title": title, "line": spread_line, "actual": actual_margin, "odds": -110, "result": _spread_result(actual_margin + spread_line)})
                rows.append({"sport": "nfl", "market": "spread", "selection": away_team, "home": home_team, "away": away_team, "title": title, "line": -spread_line, "actual": -actual_margin, "odds": -110, "result": _spread_result(-actual_margin - spread_line)})

            if total_line is not None:
                over_result = "push" if actual_total == total_line else ("win" if actual_total > total_line else "loss")
                under_result = "push" if actual_total == total_line else ("win" if actual_total < total_line else "loss")
                rows.append({"sport": "nfl", "market": "total", "selection": "over", "home": home_team, "away": away_team, "title": title, "line": total_line, "actual": actual_total, "odds": -110, "result": over_result})
                rows.append({"sport": "nfl", "market": "total", "selection": "under", "home": home_team, "away": away_team, "title": title, "line": total_line, "actual": actual_total, "odds": -110, "result": under_result})
    return rows


# ---------------------------------------------------------------------------
# Not yet available. Registered (rather than omitted) so evaluation_settlement
# treats these sports as "supported, currently zero graded rows" -- the
# correct diagnostic bucket -- instead of "unsupported sport", and so
# building the real grader later (Stage 1 follow-up) needs no change
# anywhere else once it lands.
# ---------------------------------------------------------------------------


def _soccer_graded_rows_for_date(_date_str: str) -> list[dict[str, Any]]:
    # No actuals builder exists yet (plan doc P-finding: "soccer has no
    # actuals builder at all" -- a calibrated 10-league engine whose
    # predictions can never be scored). Tracked separately as its own
    # build_soccer_actuals.py effort.
    return []


def _ncaab_graded_rows_for_date(_date_str: str) -> list[dict[str, Any]]:
    # No evaluation modules exist for NCAAB at all yet (no props module, no
    # picks module, no market_accuracy equivalent).
    return []


def _ncaaf_graded_rows_for_date(_date_str: str) -> list[dict[str, Any]]:
    # NCAAF's own performance log (smartsim2_performance_log.jsonl, 752 real
    # graded games) has the same date gap the NFL adapter above works around
    # via schedule_{season}.csv -- but NCAAF's on-disk schedule data is a
    # scattered set of timestamped snapshot CSVs
    # (college_football_schedule_2025_predicted_totals_enhanced*.csv) with
    # no game_id column matching the performance log's CFBD numeric ids, and
    # no closing spread/total/moneyline columns at all. Resolving that needs
    # its own investigation (likely the cfbd_lines_wk*.json files carry the
    # real market numbers + a joinable id) rather than a guess here.
    return []


GRADED_OUTCOME_GRADERS: dict[str, GradedRowGrader] = {
    "mlb": _mlb_graded_rows_for_date,
    "wnba": _wnba_graded_rows_for_date,
    "nba": _nba_graded_rows_for_date,
    "nhl": _nhl_graded_rows_for_date,
    "nfl": _nfl_graded_rows_for_date,
    "ncaaf": _ncaaf_graded_rows_for_date,
    "soccer": _soccer_graded_rows_for_date,
    "ncaab": _ncaab_graded_rows_for_date,
}


def graded_rows_for_date(sport: str, date_str: str) -> list[dict[str, Any]]:
    sport_slug = str(sport or "").strip().lower()
    grader = GRADED_OUTCOME_GRADERS.get(sport_slug)
    if grader is None:
        return []
    return grader(date_str)


__all__ = [
    "GRADED_OUTCOME_FIELDS",
    "GRADED_OUTCOME_GRADERS",
    "graded_rows_for_date",
]
