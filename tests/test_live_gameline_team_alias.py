"""NCAAF live game-line join: the team-name ALIAS fallback (todo #791, lane ncaaf-live-join-team-alias).

Measured 2026-11-12 on the fleet: the board's NCAAF rows are named by the ODDS feed, the NCAAF live lens by ESPN's
`displayName`, and `live_gameline_join` keyed both on the exact name. Over every non-inplay NCAAF book grid
2026-10-01..11-21 (34 dates), 43 of 433 odds game pairs (9.9%) matched their ESPN game ONLY through
`team_aliases.chip_join_key`; 0 matched neither way and 0 were ambiguous. UMass @ Toledo on 11-11 showed no Live proj.
on any of its 17 live rows while its lane sat in the lens as "Massachusetts Minutemen".

These pin:
  * the fallback resolves the season's real spellings to one pair, and `MAS` (UMass Dartmouth's abbr) to nothing;
  * EXACT FIRST: a row that joins by exact name joins identically with the fallback on or off, and an exact hit beats
    an alias one;
  * through the board's own attach (`board_enrichment.attach_live_gamelines_for_sport`) a renamed game's rows come
    out EXACTLY as the same game spelled identically does -- full-game and segment alike -- and are counted;
  * off != on: `SYNDICATE_LIVE_GAMELINE_TEAM_ALIASES=off` returns the renamed rows to `no_live_gameline_projection`;
  * two lens games under one canonical pair are refused AMBIGUOUS, never picked; an unresolvable name stays a miss;
    no other sport aliases.
"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from syndicate.features.ncaaf import live_resim
from syndicate.features.ncaaf.live_resim import LIVE_SEGMENTS_ENV, build_live_lens_snapshot
from syndicate.features.shared import board_enrichment
from syndicate.features.shared import live_gameline_join as lgj

ESPN_AWAY, ESPN_HOME = "Massachusetts Minutemen", "Toledo Rockets"  # what the lens publishes (ESPN displayName)
ODDS_AWAY, ODDS_HOME = "UMass Minutemen", "Toledo Rockets"  # what the board's rows carry (the odds feed)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in (lgj.TEAM_ALIAS_JOIN_ENV, LIVE_SEGMENTS_ENV, "NCAAF_LIVE_TOTAL_BIAS_POINTS",
                "NCAAF_LIVE_TOTAL_SPREAD_SCALE", "NCAAF_LIVE_MARGIN_BIAS_POINTS", "NCAAF_LIVE_MARGIN_SPREAD_SCALE",
                "NCAAF_LIVE_RESIM_SIMS", lgj.LANE_AGE_GATE_ENV, lgj.MAX_LANE_AGE_ENV, lgj.COLLEGE_SEGMENT_PRICING_ENV):
        monkeypatch.delenv(key, raising=False)


# ------------------------------------------------------------------------------------------------ the key itself

# Every distinct spelling pair the 2026-11-12 season sizing found (odds feed, ESPN displayName).
SEASON_SPELLINGS = [
    ("UMass Minutemen", "Massachusetts Minutemen"),
    ("Appalachian State Mountaineers", "App State Mountaineers"),
    ("Hawaii Rainbow Warriors", "Hawai'i Rainbow Warriors"),
    ("Louisiana Ragin Cajuns", "Louisiana Ragin' Cajuns"),
    ("Southern Mississippi Golden Eagles", "Southern Miss Golden Eagles"),
    ("San Jose State Spartans", "San José State Spartans"),
    ("Sam Houston State Bearkats", "Sam Houston Bearkats"),
    ("McNeese State Cowboys", "McNeese Cowboys"),
    ("Citadel Bulldogs", "The Citadel Bulldogs"),
]


@pytest.mark.parametrize("odds_name,espn_name", SEASON_SPELLINGS)
def test_the_seasons_two_spellings_resolve_to_one_pair(odds_name, espn_name):
    odds_key = lgj.team_alias_pair_key("ncaaf", odds_name, "Toledo Rockets")
    assert odds_key is not None
    assert odds_key == lgj.team_alias_pair_key("ncaaf", espn_name, "Toledo Rockets")


def test_mas_resolves_to_nothing_so_it_can_never_alias():
    """UMass Dartmouth's real abbr, which the 2026-08-29 map turned into a confident wrong join."""
    assert lgj.team_alias_pair_key("ncaaf", "MAS", "Toledo Rockets") is None
    assert lgj.team_alias_pair_key("ncaaf", "Nowhere Tech Owls", "Toledo Rockets") is None


def test_no_other_sport_aliases_and_the_switch_reads_off():
    assert lgj.team_alias_join_enabled("ncaaf") is True  # absent = on
    for sport in ("ncaab", "wncaab", "nba", "nfl", "nhl", "mlb", None):
        assert lgj.team_alias_join_enabled(sport) is False
        assert lgj.team_alias_pair_key(sport, ODDS_AWAY, ODDS_HOME) is None
    for value in ("off", "OFF", "0", "false", "no"):
        assert lgj.team_alias_join_enabled("ncaaf", {lgj.TEAM_ALIAS_JOIN_ENV: value}) is False
    for value in ("", "on", "1", "yes"):
        assert lgj.team_alias_join_enabled("ncaaf", {lgj.TEAM_ALIAS_JOIN_ENV: value}) is True


# ---------------------------------------------------------------------------------------- the resolver, directly

def _game(away, home, gid):
    lane = {"source": "live_resim", "modelHomeWinProb": 0.6, "projection": {"homeMargin": 3.0, "total": 50.0}}
    return {"gamePk": gid, "matchup": {"away": {"name": away}, "home": {"name": home}}, "gameLens": [lane]}


def _index(*games):
    return lgj.build_live_gameline_index({"games": list(games)}, sport="ncaaf", sources=("live_resim",))


def _resolve(index, away, home):
    return lgj.resolve_live_gameline(index, (lgj._norm_team(away), lgj._norm_team(home)), sport="ncaaf",
                                     row_teams=(away, home))


def test_an_exact_hit_beats_an_alias_one():
    exact = _game(ODDS_AWAY, ODDS_HOME, "exact")
    renamed = _game(ESPN_AWAY, ESPN_HOME, "renamed")
    index = _index(renamed, exact)
    hit, why = _resolve(index, ODDS_AWAY, ODDS_HOME)
    if hit is None:  # the projection object the index keeps is not the game dict; identify by game_pk
        pytest.fail(why)
    assert hit["game_pk"] == "exact" and why == lgj.SINGLE


def test_two_lens_games_under_one_canonical_pair_are_refused_ambiguous_not_picked():
    index = _index(_game(ESPN_AWAY, ESPN_HOME, "a"), _game("UMass", "Toledo", "b"))
    assert lgj.team_alias_pair_key("ncaaf", "UMass", "Toledo") == lgj.team_alias_pair_key("ncaaf", ESPN_AWAY, ESPN_HOME)
    hit, why = _resolve(index, ODDS_AWAY, ODDS_HOME)
    assert hit is None and why == lgj.REASON_GAME_AMBIGUOUS


def test_the_index_counts_its_alias_keys_only_where_the_fallback_is_on(monkeypatch):
    diag: dict = {}
    lgj.build_live_gameline_index({"games": [_game(ESPN_AWAY, ESPN_HOME, "a")]}, sport="ncaaf",
                                  sources=("live_resim",), diagnostics=diag)
    assert diag["alias_keys"] == 1 and diag["indexed"] == 1
    diag_nba: dict = {}
    lgj.build_live_gameline_index({"games": [_game(ESPN_AWAY, ESPN_HOME, "a")]}, sport="nba",
                                  sources=("live_resim",), diagnostics=diag_nba)
    assert "alias_keys" not in diag_nba
    monkeypatch.setenv(lgj.TEAM_ALIAS_JOIN_ENV, "off")
    diag_off: dict = {}
    index = lgj.build_live_gameline_index({"games": [_game(ESPN_AWAY, ESPN_HOME, "a")]}, sport="ncaaf",
                                          sources=("live_resim",), diagnostics=diag_off)
    assert "alias_keys" not in diag_off and index.alias_candidates == {}


# ------------------------------------------------------------------------------- through the board's own attach

AS_OF = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
NOW = datetime.now(timezone.utc).isoformat()


def _snapshot(monkeypatch, espn_away, espn_home):
    """The REAL producer (`build_live_lens_snapshot`, fake engine; Q2 6:40, 10-7), then the ESPN `displayName`
    stamp `run_refresh_worker` puts on `matchup` -- the name the join reads first. One fixed live-state time for
    every snapshot in this module, so two builds differ only in what a test changes."""
    def simulate(sim_input, profile=None):  # noqa: ARG001
        odd = sim_input.seed % 2 == 1
        q2 = (7, 3) if odd else (0, 3)
        log = ({"quarter": 2, "home_points": q2[0], "away_points": q2[1]},
               {"quarter": 3, "home_points": 7, "away_points": 0}, {"quarter": 4, "home_points": 3, "away_points": 7})
        return SimpleNamespace(quarter_log=log, final_score={"home": 10 + q2[0] + 10, "away": 7 + q2[1] + 7})

    monkeypatch.setattr(live_resim, "simulate_game", simulate)
    state = {"in_progress": True, "final": False, "period": 2, "clock": "6:40", "home_score": 10, "away_score": 7,
             "possession_owner": "home", "situation": {}, "home_linescores": [7, 3], "away_linescores": [0, 7],
             "as_of": AS_OF}
    snapshot = build_live_lens_snapshot(
        "2026-11-11", games=[{"away_team": "Massachusetts", "home_team": "Toledo", "live_key": "k"}],
        live_index={"k": state}, ratings={"toledo": (1.0, 1.0), "massachusetts": (0.0, 0.0)}, sims=8)
    for game in snapshot["games"]:
        game["matchup"] = {"away": {"name": espn_away}, "home": {"name": espn_home}}
    return snapshot


def _grid(away, home):
    def row(segment, market, line):
        sides = ["over", "under"] if market == "totals" else ["home", "away"]
        return {"kind": "game", "sport": "ncaaf", "market": market, "segment": segment, "line": line,
                "sides": sides, "away_team": away, "home_team": home, "age_seconds": 20.0, "updated_at": NOW,
                "game": {"state": "live"}, "projection": {"market_fair_prob_over": 0.5}}

    return [row("full", "totals", 47.5), row("full", "spreads", -3.5), row("full", "h2h", None),
            row("h1", "totals", 26.5), row("q3", "totals", 13.5), row("h1", "spreads", 3.5)]


def _attach(monkeypatch, snapshot, grid):
    from syndicate.features.shared import refresh_state_store

    monkeypatch.setattr(refresh_state_store, "read_json_file", lambda _path: copy.deepcopy(snapshot))
    return board_enrichment.attach_live_gamelines_for_sport(grid, sport="ncaaf", selected_date="2026-11-11")


def _strip_names(rows):
    return [{k: v for k, v in row.items() if k not in ("away_team", "home_team")} for row in rows]


def _drop_volatile(coverage):
    return {k: v for k, v in coverage.items() if k not in ("index_diagnostics", "rows_joined_by_team_alias",
                                                             "lane_age_max_s")}


def test_a_renamed_games_rows_come_out_exactly_as_the_same_game_spelled_alike(monkeypatch):
    """The whole claim of #791 on one game: UMass rows against a "Massachusetts" lane == UMass rows against a
    "UMass" lane, row for row (full-game priced or refused, segment display), and every one of them is counted."""
    same = _grid(ODDS_AWAY, ODDS_HOME)
    cov_same = _attach(monkeypatch, _snapshot(monkeypatch, ODDS_AWAY, ODDS_HOME), same)
    renamed = _grid(ODDS_AWAY, ODDS_HOME)
    cov_renamed = _attach(monkeypatch, _snapshot(monkeypatch, ESPN_AWAY, ESPN_HOME), renamed)

    assert cov_same["rows_live_gameline_projected"] > 0  # the reference actually joined, so the comparison means something
    assert lgj.REASON_NO_LIVE_PROJECTION not in cov_renamed["withheld_by_reason"]
    assert _strip_names(renamed) == _strip_names(same)
    assert _drop_volatile(cov_renamed) == _drop_volatile(cov_same)
    # Counted where a reader looks: every live row of the renamed game came through the fallback (3 full-game lookups
    # + 3 segment display lookups), none of the spelled-alike one did, and the full-game index filed it once.
    assert cov_renamed["rows_joined_by_team_alias"] == 6
    assert "rows_joined_by_team_alias" not in cov_same
    assert cov_renamed["index_diagnostics"]["alias_keys"] == 1
    # And the segment rows carry the display number, exactly as #785 shows them on a matched game.
    assert renamed[3][lgj.LIVE_DISPLAY_KEY]["total_mean"] == 23.5


def test_off_through_the_env_returns_the_renamed_rows_to_a_named_miss(monkeypatch):
    monkeypatch.setenv(lgj.TEAM_ALIAS_JOIN_ENV, "off")
    grid = _grid(ODDS_AWAY, ODDS_HOME)
    coverage = _attach(monkeypatch, _snapshot(monkeypatch, ESPN_AWAY, ESPN_HOME), grid)
    assert coverage["withheld_by_reason"].get(lgj.REASON_NO_LIVE_PROJECTION) == 3
    assert coverage["rows_live_gameline_projected"] == 0
    assert all(lgj.LIVE_DISPLAY_KEY not in row and "live_gameline" not in row for row in grid)
    assert "rows_joined_by_team_alias" not in coverage
    assert "alias_keys" not in coverage["index_diagnostics"]


def test_an_exact_join_is_identical_with_the_fallback_on_or_off(monkeypatch):
    on = _grid(ODDS_AWAY, ODDS_HOME)
    cov_on = _attach(monkeypatch, _snapshot(monkeypatch, ODDS_AWAY, ODDS_HOME), on)
    monkeypatch.setenv(lgj.TEAM_ALIAS_JOIN_ENV, "off")
    off = _grid(ODDS_AWAY, ODDS_HOME)
    cov_off = _attach(monkeypatch, _snapshot(monkeypatch, ODDS_AWAY, ODDS_HOME), off)
    assert on == off
    assert _drop_volatile(cov_on) == _drop_volatile(cov_off)


def test_an_unresolvable_name_stays_a_named_miss(monkeypatch):
    grid = _grid("Nowhere Tech Owls", ODDS_HOME)
    coverage = _attach(monkeypatch, _snapshot(monkeypatch, ESPN_AWAY, ESPN_HOME), grid)
    assert coverage["withheld_by_reason"].get(lgj.REASON_NO_LIVE_PROJECTION) == 3
    assert all(lgj.LIVE_DISPLAY_KEY not in row for row in grid)
