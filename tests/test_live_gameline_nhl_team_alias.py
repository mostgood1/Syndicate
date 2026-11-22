"""NHL live game-line join through the team-name ALIAS fallback (lane nhl-live-join-stl-alias, 2026-11-21).

Measured on the fleet 11-21 6:43 PM CST (`.syndicate/findings_2026-11-21_layer2_rail_monitor.md`, flag 4): the NHL
live lens names the club "St. Louis Blues", the odds rows say "St Louis Blues", and `_norm_team` keeps the period, so
New Jersey @ St. Louis was the ONE live NHL game whose moneyline and puck-line rows carried no live model -- every
other game's did. `team_aliases.chip_join_key("nhl", ...)` already folds both spellings to one key.

The switch is `SYNDICATE_LIVE_GAMELINE_NHL_TEAM_ALIASES`, ABSENT = OFF (a betting change: it loads in a window).
These pin:
  * off != on: absent/off leaves the Blues rows a named miss (`no_live_gameline_projection`), on joins them;
  * on, a Blues row comes out EXACTLY as the same game spelled alike does, and is counted;
  * EXACT FIRST: a row whose pair already matches is identical on or off;
  * NCAAF's fallback (absent = ON) is unchanged by the NHL switch, and the global off turns NHL off too;
  * no other sport reads the NHL switch, and no two NHL clubs share a key.
"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone

import pytest

from syndicate.features.shared import live_gameline_join as lgj
from syndicate.features.shared.live_gameline_join import LIVE_DISPLAY_KEY, attach_live_gamelines, build_live_gameline_index

LENS_AWAY, LENS_HOME = "New Jersey Devils", "St. Louis Blues"  # what the NHL lens publishes (fleet, 11-21)
ODDS_AWAY, ODDS_HOME = "New Jersey Devils", "St Louis Blues"  # what the odds rows carry (fleet, 11-21)
LANE_AT = datetime(2026, 11, 22, 0, 40, 0, tzinfo=timezone.utc)
NOW = LANE_AT + timedelta(seconds=60)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in (lgj.TEAM_ALIAS_JOIN_ENV, lgj.NHL_TEAM_ALIAS_JOIN_ENV, lgj.LANE_AGE_GATE_ENV, lgj.MAX_LANE_AGE_ENV,
                "SYNDICATE_LIVE_GAMELINE_MAX_QUOTE_AGE_SECONDS", lgj.COLLEGE_SEGMENT_PRICING_ENV,
                lgj.QUOTE_ORDER_BASIS_ENV):
        monkeypatch.delenv(key, raising=False)


def _lane():
    """The live NHL lane's shape on the fleet 11-21 (`nhl_live_lens.json`): a win probability, the means and a
    margin histogram."""
    return {"key": "live", "source": "live_resim", "modelHomeWinProb": 0.695, "simsRun": 200,
            "liveStateAsOf": LANE_AT.isoformat(),
            "projection": {"homeMargin": 0.875, "total": 5.17,
                           "displayMarginDist": {"1": 54, "-1": 26, "2": 47, "-2": 29, "3": 24, "4": 11}}}


def _snapshot(away, home):
    # The NHL lens carries `away_name` / `home_name` at the top level (no `matchup`), as on the fleet.
    return {"games": [{"away_name": away, "home_name": home, "gamePk": "2026020368", "gameLens": [_lane()]}]}


def _grid(away, home):
    def row(market, line, sides, prob):
        return {"kind": "game", "sport": "nhl", "market": market, "segment": "full", "line": line, "sides": sides,
                "away_team": away, "home_team": home, "age_seconds": 20.0,
                "updated_at": (LANE_AT + timedelta(seconds=30)).isoformat(), "game": {"state": "live"},
                "projection": {"market_fair_prob_over": prob}}

    return [row("h2h", None, ["home", "away"], 0.6), row("spreads", -1.5, ["home", "away"], 0.4),
            row("totals", 5.5, ["over", "under"], 0.5)]


def _attach(grid, snapshot):
    index = build_live_gameline_index(snapshot, sources=("live_resim",), sport="nhl")
    return attach_live_gamelines(grid, index, sport="nhl", segment_pricing_enabled=False,
                                 segment_display_only="nhl" in lgj.LIVE_DISPLAY_SPORTS, now=NOW)


def _strip_names(rows):
    return [{k: v for k, v in row.items() if k not in ("away_team", "home_team")} for row in rows]


def _drop_volatile(coverage):
    return {k: v for k, v in coverage.items() if k not in ("index_diagnostics", "rows_joined_by_team_alias",
                                                             "lane_age_max_s")}


def _joined(row):
    return LIVE_DISPLAY_KEY in row or "live_gameline" in row


# ------------------------------------------------------------------------------------------------ the switch

def test_absent_is_off_and_only_the_on_words_turn_it_on():
    assert lgj.team_alias_join_enabled("nhl") is False
    for value in ("", "off", "0", "false", "no", "maybe"):
        assert lgj.team_alias_join_enabled("nhl", {lgj.NHL_TEAM_ALIAS_JOIN_ENV: value}) is False
    for value in ("on", "ON", "1", "true", "yes"):
        assert lgj.team_alias_join_enabled("nhl", {lgj.NHL_TEAM_ALIAS_JOIN_ENV: value}) is True


def test_the_global_off_turns_nhl_off_too():
    env = {lgj.NHL_TEAM_ALIAS_JOIN_ENV: "on", lgj.TEAM_ALIAS_JOIN_ENV: "off"}
    assert lgj.team_alias_join_enabled("nhl", env) is False


@pytest.mark.parametrize("nhl_value", [None, "on", "off"])
def test_ncaaf_is_unchanged_by_the_nhl_switch(nhl_value):
    env = {} if nhl_value is None else {lgj.NHL_TEAM_ALIAS_JOIN_ENV: nhl_value}
    assert lgj.team_alias_join_enabled("ncaaf", env) is True
    assert lgj.team_alias_join_enabled("ncaaf", {**env, lgj.TEAM_ALIAS_JOIN_ENV: "off"}) is False


def test_no_other_sport_reads_the_nhl_switch():
    env = {lgj.NHL_TEAM_ALIAS_JOIN_ENV: "on"}
    for sport in ("ncaab", "wncaab", "nba", "wnba", "nfl", "mlb", "soccer", None):
        assert lgj.team_alias_join_enabled(sport, env) is False


# ----------------------------------------------------------------------------------------------- the key itself

def test_both_st_louis_spellings_resolve_to_one_pair(monkeypatch):
    monkeypatch.setenv(lgj.NHL_TEAM_ALIAS_JOIN_ENV, "on")
    key = lgj.team_alias_pair_key("nhl", ODDS_AWAY, ODDS_HOME)
    assert key is not None and key == lgj.team_alias_pair_key("nhl", LENS_AWAY, LENS_HOME)
    # the premise: the exact key really does differ, which is the defect
    assert lgj._norm_team(ODDS_HOME) != lgj._norm_team(LENS_HOME)


def test_no_two_nhl_clubs_share_a_key():
    from syndicate.features.shared.team_aliases import chip_join_key
    from syndicate.local_nhl_odds import TEAM_NAME_TO_ABBR

    by_key: dict[str, set[str]] = {}
    for name, abbr in TEAM_NAME_TO_ABBR.items():
        key = chip_join_key("nhl", name)
        if key:
            by_key.setdefault(key, set()).add(str(abbr))
    collisions = {k: v for k, v in by_key.items() if len(v) > 1}
    assert not collisions, collisions


# ------------------------------------------------------------------------------------------------ the join, off != on

def test_off_leaves_the_blues_rows_a_named_miss():
    grid = _grid(ODDS_AWAY, ODDS_HOME)
    coverage = _attach(grid, _snapshot(LENS_AWAY, LENS_HOME))
    assert coverage["withheld_by_reason"].get(lgj.REASON_NO_LIVE_PROJECTION) == len(grid)
    assert not any(_joined(row) for row in grid)
    assert "rows_joined_by_team_alias" not in coverage


def test_on_joins_the_blues_rows_exactly_as_the_same_game_spelled_alike(monkeypatch):
    monkeypatch.setenv(lgj.NHL_TEAM_ALIAS_JOIN_ENV, "on")
    same = _grid(LENS_AWAY, LENS_HOME)
    cov_same = _attach(same, _snapshot(LENS_AWAY, LENS_HOME))
    renamed = _grid(ODDS_AWAY, ODDS_HOME)
    cov_renamed = _attach(renamed, _snapshot(LENS_AWAY, LENS_HOME))

    assert any(_joined(row) for row in same)  # the reference joined, so the comparison means something
    assert lgj.REASON_NO_LIVE_PROJECTION not in cov_renamed["withheld_by_reason"]
    assert _strip_names(renamed) == _strip_names(same)
    assert _drop_volatile(cov_renamed) == _drop_volatile(cov_same)
    assert cov_renamed["rows_joined_by_team_alias"] == len(renamed)
    assert "rows_joined_by_team_alias" not in cov_same
    # the moneyline shows the lane's own home probability
    assert renamed[0][LIVE_DISPLAY_KEY]["prob_over"] == pytest.approx(0.695, abs=0.01)


def test_an_exact_join_is_identical_with_the_nhl_switch_on_or_off(monkeypatch):
    off = _grid(LENS_AWAY, LENS_HOME)
    cov_off = _attach(off, _snapshot(LENS_AWAY, LENS_HOME))
    monkeypatch.setenv(lgj.NHL_TEAM_ALIAS_JOIN_ENV, "on")
    on = _grid(LENS_AWAY, LENS_HOME)
    cov_on = _attach(on, _snapshot(LENS_AWAY, LENS_HOME))
    assert on == off
    assert _drop_volatile(cov_on) == _drop_volatile(cov_off)


def test_on_an_unresolvable_name_stays_a_named_miss(monkeypatch):
    monkeypatch.setenv(lgj.NHL_TEAM_ALIAS_JOIN_ENV, "on")
    grid = _grid("Nowhere Icemen", ODDS_HOME)
    coverage = _attach(grid, _snapshot(LENS_AWAY, LENS_HOME))
    assert coverage["withheld_by_reason"].get(lgj.REASON_NO_LIVE_PROJECTION) == len(grid)
    assert not any(_joined(row) for row in grid)


def test_on_the_index_files_the_lens_game_under_its_canonical_pair(monkeypatch):
    diag_off: dict = {}
    index_off = build_live_gameline_index(_snapshot(LENS_AWAY, LENS_HOME), sources=("live_resim",), sport="nhl",
                                          diagnostics=diag_off)
    assert "alias_keys" not in diag_off and index_off.alias_candidates == {}
    monkeypatch.setenv(lgj.NHL_TEAM_ALIAS_JOIN_ENV, "on")
    diag_on: dict = {}
    index_on = build_live_gameline_index(copy.deepcopy(_snapshot(LENS_AWAY, LENS_HOME)), sources=("live_resim",),
                                         sport="nhl", diagnostics=diag_on)
    assert diag_on["alias_keys"] == 1 and diag_on["indexed"] == 1
    assert list(index_on.alias_candidates) == [lgj.team_alias_pair_key("nhl", ODDS_AWAY, ODDS_HOME)]
