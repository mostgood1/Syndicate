"""Soccer's missing settlement source: real match results, graded against
the markets the board actually prices.

Context: docs/reports/syndicate_learning_loop_plan_2026_08_03.md Stage 1.
Before this module, soccer had zero settlement coverage repo-wide -- no
actuals builder, no reconciliation dir -- despite a calibrated 10-league
engine (soccersim) and real per-league recommendations. Every other
sport's grader in graded_outcomes.py reads a result some upstream module
already computed; soccer has no such module, so this one computes results
directly from ground truth instead of delegating.

Ground truth: schedule_{season}.json (syndicate.features.soccer.sources.schedule_payload)
carries the real ESPN-sourced home_score/away_score/status_state per
event_id -- separately from recommendations_{date}.json, which mixes
predictions with a live/final score field that has a documented staleness
bug (recommendations_payload's own docstring: matches observed stuck at
status_state="pre" days after the real game finished). Reading the
schedule artifact instead of the recommendations artifact for "did this
game finish, and what was the score" avoids inheriting that bug.

Markets graded, and why these three specifically:
- Moneyline (3-way: home/draw/away) -- needs no market line at all, so it
  needs no odds-feed join to grade correctly.
- Totals @ 2.5 -- the fixed checkpoint this codebase already treats as
  soccer's standard total everywhere else (cards.py/market_board.py/
  live_lens.py all key off `over_2_5_probability`), so grading at 2.5
  matches what the rest of the app already calls "the" total instead of
  inventing a new convention.
- Both Teams To Score (BTTS) -- unambiguous from the final score alone,
  no line needed, and a genuinely large soccer market.
Spread/Asian-handicap is deliberately NOT graded here: unlike a fixed
totals checkpoint, a soccer spread's line varies per match with no
single "standard" number, and this local mirror has no captured
game_odds_current.csv to derive one from -- grading against a guessed
line would silently mis-score real bets. Add it once a real per-match
line source is confirmed available in production.
"""

from __future__ import annotations

from typing import Any

from syndicate.features.soccer.sources import LEAGUE_DISPLAY_NAMES
from syndicate.features.soccer.sources import game_odds_rows
from syndicate.features.soccer.sources import schedule_payload


def _to_float(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except Exception:
        return None


def _seasons_to_try(date_str: str) -> list[int]:
    try:
        year = int(str(date_str)[:4])
    except Exception:
        return []
    # Different leagues number seasons differently (MLS: calendar year;
    # EPL/Bundesliga/etc: split-year seasons that sometimes get filed under
    # either the start or end year in this mirror) -- trying all three
    # nearby years is cheap (one cached schedule_payload() lookup each,
    # @lru_cache'd) and sidesteps needing a per-league convention table.
    return [year - 1, year, year + 1]


def _odds_price_index(league: str) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """event_id -> raw odds rows for that event, keyed by the odds feed's
    OWN event_id (unrelated to the schedule's ESPN event_id -- see
    market_board._soccer_odds_event_for_match's docstring for why these
    two ids can never be compared directly)."""
    index: dict[str, list[dict[str, Any]]] = {}
    for row in game_odds_rows(league):
        event_id = str(row.get("event_id") or "").strip()
        if event_id:
            index.setdefault(event_id, []).append(row)
    return index


def _resolve_odds_rows_for_match(*, home_team: str, away_team: str, odds_index: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    from syndicate.features.soccer.features.team_names import match_team_name

    for rows in odds_index.values():
        if not rows:
            continue
        row_home = str(rows[0].get("home_team") or "").strip()
        row_away = str(rows[0].get("away_team") or "").strip()
        if not row_home or not row_away:
            continue
        if match_team_name(home_team, [row_home]) and match_team_name(away_team, [row_away]):
            return rows
    return []


def _price_for(odds_rows: list[dict[str, Any]], *, market: str, side: str, line: float | None = None) -> float | None:
    for row in odds_rows:
        if str(row.get("market") or "").strip().lower() != market:
            continue
        if str(row.get("side") or "").strip().lower() != side:
            continue
        if line is not None:
            row_line = _to_float(row.get("line"))
            if row_line is None or abs(row_line - line) > 1e-6:
                continue
        price = _to_float(row.get("price"))
        if price is not None:
            return price
    return None


def graded_rows_for_league_date(league: str, date_str: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    odds_index: dict[str, list[dict[str, Any]]] | None = None
    seen_event_ids: set[str] = set()
    for season in _seasons_to_try(date_str):
        payload = schedule_payload(league, season)
        matches = payload.get("matches") if isinstance(payload, dict) and isinstance(payload.get("matches"), list) else []
        for match in matches:
            if not isinstance(match, dict):
                continue
            if str(match.get("date") or "")[:10] != date_str:
                continue
            if str(match.get("status_state") or "").strip().lower() != "post":
                continue
            event_id = str(match.get("event_id") or "").strip()
            if event_id and event_id in seen_event_ids:
                continue
            home_score = _to_float(match.get("home_score"))
            away_score = _to_float(match.get("away_score"))
            if home_score is None or away_score is None:
                continue
            if event_id:
                seen_event_ids.add(event_id)

            home_team = str(match.get("home_team") or "").strip()
            away_team = str(match.get("away_team") or "").strip()
            title = f"{away_team} @ {home_team}"
            total_goals = home_score + away_score

            if odds_index is None:
                odds_index = _odds_price_index(league)
            match_odds_rows = _resolve_odds_rows_for_match(home_team=home_team, away_team=away_team, odds_index=odds_index) if odds_index else []

            def _ml_result(side: str) -> str:
                if side == "home":
                    return "win" if home_score > away_score else "loss"
                if side == "away":
                    return "win" if away_score > home_score else "loss"
                return "win" if home_score == away_score else "loss"

            for side, selection in (("home", home_team), ("draw", "Draw"), ("away", away_team)):
                rows.append(
                    {
                        "sport": "soccer",
                        "league": league,
                        "market": "moneyline",
                        "selection": selection,
                        "home": home_team,
                        "away": away_team,
                        "title": title,
                        "actual": home_score if side == "home" else (away_score if side == "away" else None),
                        "odds": _price_for(match_odds_rows, market="h2h", side=side),
                        "result": _ml_result(side),
                    }
                )

            over_result = "win" if total_goals > 2.5 else "loss"
            under_result = "win" if total_goals < 2.5 else "loss"
            rows.append({"sport": "soccer", "league": league, "market": "total", "selection": "over", "home": home_team, "away": away_team, "title": title, "line": 2.5, "actual": total_goals, "odds": _price_for(match_odds_rows, market="totals", side="over", line=2.5), "result": over_result})
            rows.append({"sport": "soccer", "league": league, "market": "total", "selection": "under", "home": home_team, "away": away_team, "title": title, "line": 2.5, "actual": total_goals, "odds": _price_for(match_odds_rows, market="totals", side="under", line=2.5), "result": under_result})

            both_scored = home_score > 0 and away_score > 0
            rows.append({"sport": "soccer", "league": league, "market": "btts", "selection": "yes", "home": home_team, "away": away_team, "title": title, "actual": both_scored, "odds": _price_for(match_odds_rows, market="btts", side="yes"), "result": "win" if both_scored else "loss"})
            rows.append({"sport": "soccer", "league": league, "market": "btts", "selection": "no", "home": home_team, "away": away_team, "title": title, "actual": both_scored, "odds": _price_for(match_odds_rows, market="btts", side="no"), "result": "loss" if both_scored else "win"})
    return rows


def graded_rows_for_date(date_str: str) -> list[dict[str, Any]]:
    """All leagues, one date -- what graded_outcomes.py registers for
    sport="soccer". Scans every league (cheap: schedule_payload is
    @lru_cache'd and this is a handful of dict lookups per league) rather
    than requiring a caller to already know which leagues played that day."""
    rows: list[dict[str, Any]] = []
    for league in LEAGUE_DISPLAY_NAMES:
        try:
            rows.extend(graded_rows_for_league_date(league, date_str))
        except Exception:
            continue
    return rows


__all__ = ["graded_rows_for_date", "graded_rows_for_league_date"]
