"""MLS ratings across a season boundary (lane mls-ratings-season-rollover, 2026-11-27).

The MLS branch of `build_soccer_artifacts._load_team_ratings` fetched ASA's aggregates for `date.today().year`. From
2027-01-01 that season has no games until the late-February opener, so every MLS team fell to the same
PROMOTED_TEAM_RATING. The fix takes the season from the build date and fills each team's first 34 games at last
season's per-match rates (measured: `scripts/rail_monitor/mls_rollover/mls_rollover_study.py`).

These pin it:
  - IDENTICAL while every team has 34+ games (all of 2026 now): the fetch's rows untouched, last season not fetched,
    and the ratings equal to the old code's;
  - the season is the build date's, never the wall clock's;
  - a pre-opener 2027 build rates every team from 2026, so the teams differ (they were all equal before);
  - the blend weights: n games at this season's rate plus 34 - n at last season's;
  - an expansion team (no last season) keeps this season's numbers; a team with no game yet takes last season's;
  - a failed fetch of last season falls back to this season alone, as before;
  - the production loader reaches it (reachability through `_load_team_ratings`).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def bsa():
    spec = importlib.util.spec_from_file_location("bsa_mls_rollover", REPO / "scripts" / "build_soccer_artifacts.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _row(team, season, games, xf, xa):
    return {"league": "mls", "season": str(season), "team": team, "xg_for": xf, "xg_against": xa, "ppda": None,
            "games": float(games)}


# Real shapes: 2026 every team 34-36 games (ASA, read 2026-11-27); 2025 a full season.
S2026 = [_row("Inter Miami", 2026, 36, 1.9, 1.2), _row("Columbus Crew", 2026, 35, 1.6, 1.1),
         _row("San Diego FC", 2026, 34, 1.5, 1.3), _row("Chicago Fire", 2026, 34, 1.2, 1.6)]
S2025 = [_row("Inter Miami", 2025, 34, 2.1, 1.4), _row("Columbus Crew", 2025, 34, 1.4, 1.0),
         _row("San Diego FC", 2025, 34, 1.7, 1.2), _row("Chicago Fire", 2025, 34, 1.0, 1.8)]


def _fake(tables, calls, fail=()):
    def fetch(season):
        calls.append(int(season))
        if int(season) in fail:
            raise ConnectionError("ASA unreachable")
        return [dict(r) for r in tables.get(int(season), [])]
    return fetch


def test_identical_while_every_team_has_a_full_season(bsa, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(bsa, "fetch_asa_mls_team_history", _fake({2026: S2026, 2025: S2025}, calls))
    rows = bsa._mls_team_rows("2026-11-28")
    assert rows == S2026
    assert calls == [2026]  # last season is not even fetched
    assert "MLS_SEASON_CARRY" not in capsys.readouterr().out


def test_ratings_equal_the_old_codes_for_a_2026_build(bsa, monkeypatch):
    """The old branch: `compute_team_ratings(fetch(today.year), as_of, allow_undated=True)` with today in 2026."""
    calls = []
    monkeypatch.setattr(bsa, "fetch_asa_mls_team_history", _fake({2026: S2026, 2025: S2025}, calls))
    new = bsa._load_team_ratings("mls", Path("/nonexistent"), "2026-11-28")
    old = bsa.compute_team_ratings([dict(r) for r in S2026], as_of="2026-11-28", allow_undated=True)
    assert new == old


def test_the_season_is_the_build_dates_not_the_wall_clocks(bsa, monkeypatch):
    calls = []
    monkeypatch.setattr(bsa, "fetch_asa_mls_team_history", _fake({2026: S2026, 2025: S2025}, calls))

    class _Jan2027:
        @staticmethod
        def today():
            import datetime
            return datetime.date(2027, 1, 4)

    monkeypatch.setattr(bsa, "date_cls", _Jan2027)  # the wall clock in January: the build date still rules
    assert bsa._mls_team_rows("2026-12-05") == S2026
    assert calls == [2026]


def test_a_pre_opener_2027_build_rates_every_team_from_2026(bsa, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(bsa, "fetch_asa_mls_team_history", _fake({2027: [], 2026: S2026}, calls))
    rows = bsa._mls_team_rows("2027-02-27")
    assert calls == [2027, 2026]
    by = {r["team"]: r for r in rows}
    assert set(by) == {r["team"] for r in S2026}
    for r in S2026:
        got = by[r["team"]]
        assert (got["xg_for"], got["xg_against"]) == (r["xg_for"], r["xg_against"])
        assert got["games"] == 0.0 and got["season"] == "2027" and got["carried_games"] == 34.0
        assert got["carried_from_season"] == "2026"
    assert "MLS_SEASON_CARRY as_of=2027-02-27 season=2027 previous=2026 teams=4 carried=4" in capsys.readouterr().out
    ratings = bsa._load_team_ratings("mls", Path("/nonexistent"), "2027-02-27")
    attacks = {round(v["attack_rating"], 6) for v in ratings.values()}
    assert len(ratings) == 4 and len(attacks) == 4  # the old code: 0 rows -> every team the same promoted prior


def test_the_old_code_would_have_rated_nobody_in_february(bsa):
    """What the fix replaces: an empty 2027 fetch gives an empty table, and `_fill_promoted` makes every team equal."""
    ratings = bsa.compute_team_ratings([], as_of="2027-02-27", allow_undated=True)
    assert ratings == {}
    teams = ["Inter Miami", "Chicago Fire"]
    filled = bsa._fill_promoted(ratings, teams, "mls")
    assert filled == teams and ratings["Inter Miami"] == ratings["Chicago Fire"]


def test_the_blend_weights_this_season_by_its_games(bsa, monkeypatch):
    s2027 = [_row("Inter Miami", 2027, 10, 1.5, 1.0), _row("Chicago Fire", 2027, 34, 1.4, 1.4)]
    monkeypatch.setattr(bsa, "fetch_asa_mls_team_history", _fake({2027: s2027, 2026: S2026}, []))
    by = {r["team"]: r for r in bsa._mls_team_rows("2027-05-01")}
    mia = by["Inter Miami"]
    assert mia["xg_for"] == round((10 * 1.5 + 24 * 1.9) / 34, 4)
    assert mia["xg_against"] == round((10 * 1.0 + 24 * 1.2) / 34, 4)
    assert mia["games"] == 10.0 and mia["carried_games"] == 24.0
    assert by["Chicago Fire"] == s2027[1]  # a full season already: untouched
    assert by["Columbus Crew"]["games"] == 0.0  # no 2027 game yet: last season alone


def test_an_expansion_team_keeps_its_own_numbers(bsa, monkeypatch):
    s2027 = [_row("New Club SC", 2027, 3, 1.1, 1.7), _row("Inter Miami", 2027, 3, 2.0, 1.0)]
    monkeypatch.setattr(bsa, "fetch_asa_mls_team_history", _fake({2027: s2027, 2026: S2026}, []))
    by = {r["team"]: r for r in bsa._mls_team_rows("2027-03-15")}
    assert by["New Club SC"] == s2027[0]
    assert by["Inter Miami"]["carried_games"] == 31.0


def test_a_failed_last_season_fetch_falls_back_to_this_season(bsa, monkeypatch, capsys):
    s2027 = [_row("Inter Miami", 2027, 3, 2.0, 1.0)]
    monkeypatch.setattr(bsa, "fetch_asa_mls_team_history", _fake({2027: s2027}, [], fail={2026}))
    assert bsa._mls_team_rows("2027-03-15") == s2027
    assert "MLS_SEASON_CARRY_UNAVAILABLE" in capsys.readouterr().out


def test_a_failed_this_season_fetch_still_raises(bsa, monkeypatch):
    """Unchanged: the current season's fetch failing is not swallowed (it raised before too)."""
    monkeypatch.setattr(bsa, "fetch_asa_mls_team_history", _fake({}, [], fail={2027}))
    with pytest.raises(ConnectionError):
        bsa._mls_team_rows("2027-03-15")


def test_other_leagues_do_not_touch_asa(bsa, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(bsa, "fetch_asa_mls_team_history", _fake({2026: S2026}, calls))
    with pytest.raises(SystemExit):
        bsa._load_team_ratings("eredivisie", tmp_path, "2026-11-28")  # no history on disk: the old SystemExit
    assert calls == []
