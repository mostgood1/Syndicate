"""A QB with fewer than 2 full starts in his as-of log gets no passing-yards/attempts probability.

Lane `nfl-passing-yards-prop-coin` (user decision 2026-10-08). Measured: such rows are 5% of FIT
2023-24 passing-yards quotes and carry 68% of production's log-loss in excess of a coin, priced at
P(over) ~0.07 against a realised over-rate of ~0.51. The quoted ODDS row survives; only the model's
opinion is withheld.
"""
from __future__ import annotations

import pytest

from syndicate.features.nfl import player_stats as ps
from syndicate.features.nfl import props as P


def _plays(game_id, week, team, attempts):
    """`attempts`: {passer_id: n pass attempts} for one team in one game."""
    return [{"game_id": game_id, "week": week, "posteam": team, "passer_player_id": pid, "pass_attempt": "1",
             "passing_yards": "7"} for pid, n in attempts.items() for _ in range(n)]


# BACKUP: relief in wk1-2 (10%, 25% of attempts), first start wk3 (100%). STARTER: full starts wk1-3.
_PLAYS = tuple(
    _plays("G1", 1, "ATL", {"STARTER": 36, "BACKUP": 4})
    + _plays("G2", 2, "ATL", {"STARTER": 30, "BACKUP": 10})
    + _plays("G3", 3, "ATL", {"BACKUP": 35})
    + _plays("H1", 1, "NO", {"NOQB": 33})
    + _plays("H2", 2, "NO", {"NOQB": 31})
    + _plays("H3", 3, "NO", {"NOQB": 29})
)


@pytest.fixture(autouse=True)
def _fixture(monkeypatch):
    monkeypatch.delenv("SYNDICATE_NFL_QB_STARTS_REFUSAL", raising=False)
    monkeypatch.delenv("SYNDICATE_NFL_QB_STARTS_ONLY_RATE", raising=False)
    monkeypatch.setattr(ps, "load_player_plays", lambda season: _PLAYS if season == 2026 else ())
    ps._pass_attempt_shares.cache_clear()
    yield
    ps._pass_attempt_shares.cache_clear()


def test_full_starts_count_only_games_at_or_above_the_share():
    assert ps.qb_full_starts(2026, 4, "STARTER", "current_season_rolling") == 2
    assert ps.qb_full_starts(2026, 4, "BACKUP", "current_season_rolling") == 1
    assert ps.qb_full_starts(2026, 3, "BACKUP", "current_season_rolling") == 0


def test_the_log_is_strictly_before_the_week():
    """Week 3's start must not count when pricing week 3 -- the same no-lookahead as `player_rate`."""
    assert ps.qb_full_starts(2026, 3, "STARTER", "current_season_rolling") == 2
    assert ps.qb_full_starts(2026, 2, "STARTER", "current_season_rolling") == 1


def test_the_prior_season_fallback_reads_the_prior_season_log():
    assert ps.qb_full_starts(2027, 1, "STARTER", "prior_season_fallback") == 2
    assert ps.qb_full_starts(2027, 1, "BACKUP", "prior_season_fallback") == 1
    assert ps.qb_full_starts(2027, 1, "STARTER", "current_season_rolling") == 0


def test_refusal_applies_to_passing_yards_and_attempts_only():
    assert ps.qb_starts_refused(2026, 4, "BACKUP", "passing_yards", "current_season_rolling")
    assert ps.qb_starts_refused(2026, 4, "BACKUP", "passing_attempts", "current_season_rolling")
    assert not ps.qb_starts_refused(2026, 4, "BACKUP", "passing_tds", "current_season_rolling")
    assert not ps.qb_starts_refused(2026, 4, "STARTER", "passing_yards", "current_season_rolling")


def _rows(monkeypatch, quotes):
    monkeypatch.setattr(P, "_best_price_player_props", lambda season, week: quotes)
    monkeypatch.setattr(P, "resolve_player_id_for_game",
                        lambda season, week, name, teams, canon: ({"Backup Qb": "BACKUP", "Starter Qb": "STARTER"}[name], "test"))
    monkeypatch.setattr(P, "player_team_with_prior", lambda season, week, pid: ("Atlanta Falcons", "current_season"))
    monkeypatch.setattr(P, "nfl_game_context_multiplier", lambda *a: 1.0)
    return P.nfl_props_rows_for_week(2026, 4, use_artifact=False)


def _quote(player, market, line):
    return {"market": market, "player": player, "line": line, "away_team": "New Orleans Saints",
            "home_team": "Atlanta Falcons", "over_price": -110, "under_price": -110}


def test_the_row_builder_withholds_the_probability_but_keeps_the_odds(monkeypatch):
    quotes = [_quote("Backup Qb", "Passing Yards", 220.5), _quote("Starter Qb", "Passing Yards", 220.5),
              _quote("Backup Qb", "Passing TDs", 1.5)]
    odds, sims = _rows(monkeypatch, quotes)
    priced = {(r["entity"], r["market"].split("::")[0]) for r in sims}
    assert ("Backup Qb", "passing_yards") not in priced
    assert ("Starter Qb", "passing_yards") in priced
    assert ("Backup Qb", "passing_tds") in priced
    assert sum(1 for r in odds if r["entity"] == "Backup Qb" and r["market"].startswith("passing_yards")) == 2


def test_off_is_not_on(monkeypatch):
    """Reachability: with the switch off the same backup IS priced, so the refusal above is this code's doing."""
    monkeypatch.setenv("SYNDICATE_NFL_QB_STARTS_REFUSAL", "off")
    # Isolated from the starts-only RATE (2026-10-08): it cannot price a QB with < 2 starts either,
    # so for passing_yards BOTH switches must be off to restore the old row.
    monkeypatch.setenv("SYNDICATE_NFL_QB_STARTS_ONLY_RATE", "off")
    _odds, sims = _rows(monkeypatch, [_quote("Backup Qb", "Passing Yards", 220.5)])
    assert [r["entity"] for r in sims] == ["Backup Qb"]
