"""Wire ESPN's confirmed-lineup data into the live props pipeline.

The Phase 7 backtest (``scripts/backtest_soccer_starter_awareness.py``)
proved real confirmed lineups measurably improve prop allocation accuracy
over season-only usage rates. This module is the live-pipeline hookup:
before a fixture kicks off, ESPN's confirmed lineup exists for some window
(typically the last ~hour before kickoff); before that, or if a fixture
can't be matched, it falls back to season-only allocation automatically --
no lineup source is required for the pipeline to run, it's a strict
improvement when one is available.

Usage: call ``attach_confirmed_starters`` on a fixtures list before
``build_soccer_simulation_input`` (the same opt-in-preprocessing pattern
``market_anchoring.anchor_ratings_to_market`` uses). Fixtures where no
confirmed lineup was found come back unchanged.
"""

from __future__ import annotations

import unicodedata
from typing import Any

from syndicate.features.soccer.features.team_names import match_team_name
from syndicate.features.soccer.ingestion.espn_lineups import extract_match_player_rows
from syndicate.features.soccer.ingestion.espn_lineups import fetch_events
from syndicate.features.soccer.ingestion.espn_lineups import fetch_match_summary
from syndicate.features.soccer.sim_engine.soccersim.player_props import player_row_key

_DEFAULT_MIN_STARTERS = 7


def _norm_player_name(name: str) -> str:
    text = unicodedata.normalize("NFKD", str(name or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.lower().replace(".", " ").replace("-", " ").split())


def resolve_starter_ids(player_rows: list[dict[str, Any]], starter_names: set[str]) -> set[str]:
    """Map normalized ESPN starter names onto the identity keys
    ``build_usage_profiles`` actually uses (player_id when present, else a
    name-based key) -- so a ``starters`` set built from this function lines
    up with the rows passed into it, regardless of which ingestion source
    (Understat, ASA, ...) those rows came from."""
    resolved: set[str] = set()
    for index, row in enumerate(player_rows):
        if _norm_player_name(row.get("player_name")) in starter_names:
            resolved.add(player_row_key(row, index, "_"))
    return resolved


def find_event_for_fixture(
    events: list[dict[str, Any]],
    *,
    home_team: str,
    away_team: str,
) -> dict[str, Any] | None:
    """Match a fixture's team names against a pre-fetched ESPN event list."""
    team_pairs = [(event.get("home_team"), event.get("away_team")) for event in events]
    home_names = [pair[0] for pair in team_pairs if pair[0]]
    matched_home = match_team_name(home_team, home_names)
    if matched_home is None:
        return None
    for event in events:
        if event.get("home_team") != matched_home:
            continue
        if match_team_name(away_team, [event.get("away_team")] if event.get("away_team") else []) is not None:
            return event
    return None


def fetch_confirmed_starter_ids(
    league: str,
    *,
    home_team: str,
    away_team: str,
    home_player_rows: list[dict[str, Any]],
    away_player_rows: list[dict[str, Any]],
    events: list[dict[str, Any]] | None = None,
    date_windows: list[str] | None = None,
    min_starters: int = _DEFAULT_MIN_STARTERS,
) -> tuple[set[str], set[str]] | None:
    """Confirmed starter id sets for one fixture, or ``None`` if no matching
    event was found or its lineup isn't posted yet (fewer than
    ``min_starters`` flagged on either side -- ESPN's pre-kickoff roster
    exists ahead of the real lineup announcement with nobody flagged as a
    starter, so this threshold is what actually distinguishes "posted" from
    "not yet")."""
    if events is None:
        windows = date_windows or []
        if not windows:
            return None
        events = fetch_events(league, date_windows=windows, statuses={"pre", "in"})
    event = find_event_for_fixture(events, home_team=home_team, away_team=away_team)
    if event is None:
        return None

    summary = fetch_match_summary(league, event["event_id"])
    rows = extract_match_player_rows(summary, event_id=event["event_id"])
    if not rows:
        return None

    home_names = {_norm_player_name(row["player_name"]) for row in rows if row["side"] == "home" and row["starter"]}
    away_names = {_norm_player_name(row["player_name"]) for row in rows if row["side"] == "away" and row["starter"]}
    if len(home_names) < min_starters or len(away_names) < min_starters:
        return None

    home_ids = resolve_starter_ids(home_player_rows, home_names)
    away_ids = resolve_starter_ids(away_player_rows, away_names)
    if len(home_ids) < min_starters or len(away_ids) < min_starters:
        # Lineup was posted but too few names matched our season-data
        # roster to trust the result (name-matching gap, mid-season
        # signing not yet in the per-90 source, etc.).
        return None
    return home_ids, away_ids


def attach_confirmed_starters(
    fixtures: list[dict[str, Any]],
    *,
    league: str,
    player_rows_by_team: dict[str, list[dict[str, Any]]],
    date_windows: list[str],
    min_starters: int = _DEFAULT_MIN_STARTERS,
) -> list[dict[str, Any]]:
    """Return a copy of ``fixtures`` with ``home_starter_ids`` /
    ``away_starter_ids`` populated wherever ESPN has a confirmed lineup.
    Fixtures without a match, or without a posted lineup yet, come back
    unchanged -- the caller's existing season-only allocation still applies.
    Fetches the league's event list once and reuses it across all fixtures.
    """
    events = fetch_events(league, date_windows=date_windows, statuses={"pre", "in"})
    team_names = list(player_rows_by_team)
    updated: list[dict[str, Any]] = []
    for fixture in fixtures:
        new_fixture = dict(fixture)
        home_team = str(fixture.get("home_team") or "")
        away_team = str(fixture.get("away_team") or "")
        home_key = match_team_name(home_team, team_names)
        away_key = match_team_name(away_team, team_names)
        if home_key is None or away_key is None:
            updated.append(new_fixture)
            continue
        result = fetch_confirmed_starter_ids(
            league,
            home_team=home_team,
            away_team=away_team,
            home_player_rows=player_rows_by_team[home_key],
            away_player_rows=player_rows_by_team[away_key],
            events=events,
            min_starters=min_starters,
        )
        if result is not None:
            home_ids, away_ids = result
            new_fixture["home_starter_ids"] = tuple(home_ids)
            new_fixture["away_starter_ids"] = tuple(away_ids)
        updated.append(new_fixture)
    return updated


__all__ = [
    "attach_confirmed_starters",
    "fetch_confirmed_starter_ids",
    "find_event_for_fixture",
    "resolve_starter_ids",
]
