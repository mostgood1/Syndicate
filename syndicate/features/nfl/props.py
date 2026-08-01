"""NFL player props -- Layer 1 inventory rows (folded into
syndicate.features.nfl.cards.build_nfl_market_board) and a Layer 2 ranked
"props ladder" page, both built on real season-to-date player rates
(syndicate.features.nfl.player_stats) rather than a trained model -- see
that module's docstring and this session's plan notes for why (no
NBA/WNBA-style trained per-player model exists or is being built here).

Real player-prop ODDS (data/nfl_source/oddsapi_player_props_{season}_wk{week}.csv)
are populated for very few weeks (the-odds-api's live-odds-only fetch
script has no historical-backfill capability) -- both entry points here
degrade gracefully to empty output for any week without real rows, rather
than erroring or fabricating.
"""

from __future__ import annotations

import csv
import statistics
from functools import lru_cache
from pathlib import Path
from typing import Any

from syndicate.features.nfl.player_stats import STAT_KEYS
from syndicate.features.nfl.player_stats import player_rate
from syndicate.features.nfl.player_stats import resolve_player_id
from syndicate.features.nfl.sources import default_nfl_source_root
from syndicate.features.shared.market_inventory import join_odds_to_sim
from syndicate.features.shared.rank_board import build_rank_page_context

_NFL_PROP_MARKET_TO_STAT: dict[str, str] = {
    "Passing Yards": "passing_yards",
    "Passing Attempts": "passing_attempts",
    "Passing TDs": "passing_tds",
    "Rushing Yards": "rushing_yards",
    "Rushing Attempts": "rushing_attempts",
    "Receptions": "receptions",
    "Anytime TD": "anytime_td",
}


def nfl_props_available_weeks(season: int) -> list[int]:
    """Weeks that actually have real (non-empty) player-prop rows -- most
    weeks are header-only stubs (see module docstring), so this is NOT
    the same as "every oddsapi_player_props_*.csv file that exists on
    disk"."""
    import glob
    import re

    pattern = str(default_nfl_source_root() / f"oddsapi_player_props_{season}_wk*.csv")
    weeks: list[int] = []
    for path in glob.glob(pattern):
        match = re.search(r"_wk(\d+)\.csv$", path)
        if not match:
            continue
        week = int(match.group(1))
        if _nfl_raw_player_props(season, week):
            weeks.append(week)
    return sorted(set(weeks))


def nfl_props_key(away_full_name: str, home_full_name: str) -> str:
    return f"{away_full_name.strip()}|{home_full_name.strip()}"


def _props_path(season: int, week: int) -> Path:
    return default_nfl_source_root() / f"oddsapi_player_props_{season}_wk{week}.csv"


@lru_cache(maxsize=16)
def _nfl_raw_player_props(season: int, week: int) -> tuple[dict[str, Any], ...]:
    """Real quoted player-prop rows for this week -- () for any week the
    real odds feed was never populated for (the common case today, not an
    error)."""
    path = _props_path(season, week)
    if not path.exists():
        return ()
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = tuple(row for row in csv.DictReader(handle) if row.get("player") and row.get("market"))
    return rows


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _nfl_prop_model_probability(*, stat: str, mean: float | None, stdev: float | None, n: int, line: float | None) -> float | None:
    """Real season-to-date rate, converted to a probability -- a
    Normal-CDF cover probability for count/yardage stats with a real
    quoted line (same pattern as _nfl_cover_probability in cards.py,
    duplicated here rather than cross-imported, matching this session's
    established per-module convention), or the player's own per-game hit
    rate directly for anytime_td (a one-sided market with no line -- the
    rate itself IS the probability of scoring, no distribution needed)."""
    if n < 2 or mean is None:
        return None
    if stat == "anytime_td":
        return max(0.0, min(1.0, mean))
    if line is None or stdev is None or stdev <= 0:
        return None
    return 1.0 - statistics.NormalDist(mean, stdev).cdf(line)


def nfl_props_rows_for_week(season: int, week: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Real odds + real-rate-based sim rows for every quoted player prop
    this week. Entity = player's real full name (as quoted by the odds
    feed); market = the stat key. A real quoted line is always included
    even when the player's rate can't be resolved yet (too few games,
    or a name the pbp data has no record of) -- never silently dropped."""
    odds_rows: list[dict[str, Any]] = []
    sim_rows: list[dict[str, Any]] = []
    for row in _nfl_raw_player_props(season, week):
        stat = _NFL_PROP_MARKET_TO_STAT.get(str(row.get("market") or "").strip())
        if stat is None:
            continue
        player_name = str(row.get("player") or "").strip()
        # Keyed by real team full names (not a game_pk) -- this feed carries
        # no game id of its own, and callers that need to attach these rows
        # to a specific game-board entry (build_nfl_market_board) match on
        # this same away/home pair, then remap to that game's real game_id
        # before joining -- see nfl_props_key().
        game_id = nfl_props_key(str(row.get("away_team") or ""), str(row.get("home_team") or ""))
        line = _safe_float(row.get("line"))
        over_odds = _safe_float(row.get("over_price"))
        under_odds = _safe_float(row.get("under_price"))

        if stat == "anytime_td":
            if over_odds is not None:
                odds_rows.append({"game_id": game_id, "market": stat, "period": "full_game", "entity": player_name, "side": "over", "odds": over_odds, "market_type": "prop"})
        else:
            if over_odds is not None:
                odds_rows.append({"game_id": game_id, "market": stat, "period": "full_game", "entity": player_name, "side": "over", "line": line, "odds": over_odds, "market_type": "prop"})
            if under_odds is not None:
                odds_rows.append({"game_id": game_id, "market": stat, "period": "full_game", "entity": player_name, "side": "under", "line": line, "odds": under_odds, "market_type": "prop"})

        player_id = resolve_player_id(season, player_name)
        if player_id is None:
            continue
        mean, stdev, n = player_rate(season, week, player_id, stat)
        model_prob = _nfl_prop_model_probability(stat=stat, mean=mean, stdev=stdev, n=n, line=line)
        if model_prob is None:
            continue
        sim_rows.append({
            "game_id": game_id, "market": stat, "period": "full_game", "entity": player_name,
            "sim_projection": model_prob, "projected_value": mean, "sim_source": "nfl_season_rate",
        })
    return odds_rows, sim_rows


def _format_stat_label(stat: str) -> str:
    return {value: key for key, value in _NFL_PROP_MARKET_TO_STAT.items()}.get(stat, stat.replace("_", " ").title())


def build_nfl_props_page_context(season: int, week: int) -> dict[str, Any]:
    """Ranked props ladder -- one card per real quoted prop with a
    resolved real-rate model probability, sorted by edge (model
    probability minus the odds' own single-sided implied probability --
    labeled as market-implied, not no-vig, same honesty
    syndicate.features.mlb.hr_targets.py already uses for the same
    reason)."""
    odds_rows, sim_rows = nfl_props_rows_for_week(season, week)
    inventory = join_odds_to_sim(odds_rows, sim_rows)

    cards: list[dict[str, Any]] = []
    for row in inventory:
        sim_projection = row.get("sim_projection")
        odds = row.get("odds")
        if sim_projection is None or odds is None:
            continue
        implied_prob = (100.0 / (odds + 100.0)) if odds > 0 else ((-odds) / ((-odds) + 100.0))
        edge = sim_projection - implied_prob
        stat_label = _format_stat_label(row.get("market"))
        side = str(row.get("side") or "").title()
        line = row.get("line")
        line_text = f"{line:g}" if isinstance(line, (int, float)) else "-"
        cards.append({
            "title": f"{row.get('entity')} — {stat_label}",
            "eyebrow": "NFL Props",
            "badge": f"{edge:+.1%} edge",
            "meta": f"{side} {line_text}" if line is not None else side,
            "metrics": [
                {"label": "Real rate model", "value": f"{sim_projection:.1%}"},
                {"label": "Market implied", "value": f"{implied_prob:.1%}"},
                {"label": "Real odds", "value": f"{odds:+.0f}" if odds is not None else "-"},
                {"label": "Season-to-date value", "value": f"{row.get('projected_value'):.1f}" if row.get("projected_value") is not None else "-"},
            ],
            "summary": f"{row.get('entity')}'s real season-to-date rate implies {sim_projection:.1%} on this {stat_label.lower()} line, vs. a market-implied {implied_prob:.1%}.",
            "list_items": [],
            "_edge": edge,
        })
    cards.sort(key=lambda card: card.pop("_edge"), reverse=True)

    return build_rank_page_context(
        selected_date=f"{season}-01-{week:02d}",
        route_path="/nfl/props",
        intro_title="NFL Props",
        intro_body="Real quoted player-prop lines ranked by edge against a real season-to-date rate baseline (not a trained model) -- see the module docstring for why, and note most weeks have no real prop odds populated yet.",
        aria_label="NFL props ladder",
        source_path=str(_props_path(season, week)),
        source_title="Real OddsAPI player-prop snapshot",
        source_date_display=f"{season} Week {week}",
        rank_cards=cards,
        using_sample_data=False,
        header_stats=[
            {"label": "Cards", "value": str(len(cards))},
            {"label": "Season", "value": str(season)},
            {"label": "Week", "value": str(week)},
        ],
        module_links=[{"label": "Market Board", "href": f"/nfl/market-board?season={season}&week={week}", "active": False}],
        control_label="Week",
        control_type="number",
        control_name="week",
        control_value=str(week),
        hidden_fields=[{"name": "season", "value": str(season)}],
        empty_state=None if cards else {
            "eyebrow": "NFL props",
            "title": "No real player-prop lines available for this week",
            "body": "The real OddsAPI player-props snapshot has no rows for this season/week -- this feed only ever captures whatever is live/upcoming when it's refreshed, so most historical weeks have none.",
            "list_items": [f"Season: {season}", f"Week: {week}"],
        },
    )
