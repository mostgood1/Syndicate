"""The NCAAF live re-sim prices from the pregame generator's in-season blend (`todo #678`).

WHY THIS EXISTS. From week 3 the pregame generator prices on `inseason_blend_ppa`
(prior-season SP+ blended with season-to-date per-game PPA; first applied on
production 2026-09-18 23:16:15Z) while `_run_ncaaf_live_resim_tick` kept reading
SP+, so one game's pregame and live numbers rested on different team ratings.

WHAT MUST HOLD:
  1. REACHABILITY (`model_engine_standard.md`): off != on through the REAL tick --
     the live lane's win probability moves when the blend is switched on.
  2. Off, week < 3, or no usable entry -> the SP+ path exactly as before, and the
     reason is said on the status.
  3. A missing week falls back to the newest EARLIER entry, by name; never a
     later week, never a neutral default.
"""

from __future__ import annotations

import json

import pytest

import scripts.run_refresh_worker as rw
from scripts.generate_smartsim2_ncaaf_projections import inseason_blend_artifact_path
from syndicate.features.ncaaf import live_resim as lr

BLEND_ENV = "SYNDICATE_NCAAF_INSEASON_BLEND"

# SP+ says Auburn is the better side; the blend says Baylor is, by a lot, so the
# difference cannot be sim noise.
SP_INDEX = {"auburn": (30.0, 18.0), "baylor": (24.0, 24.0)}
BLEND_TEAMS = {"auburn": [20.0, 30.0, 2], "baylor": [36.0, 14.0, 2]}


def _write_blend(season: int, weeks: dict) -> None:
    path = inseason_blend_artifact_path(season)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {"season": season, "weeks": {str(w): {"k": 2.0, "teams": teams} for w, teams in weeks.items()}}
    path.write_text(json.dumps(doc), encoding="utf-8")


@pytest.fixture
def roots(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("SYNDICATE_NCAAF_SOURCE_ROOT", str(tmp_path / "ncaaf_source"))
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path / "reports"))
    monkeypatch.setenv("SYNDICATE_REFRESH_STATE_BACKEND", "file")
    monkeypatch.delenv(BLEND_ENV, raising=False)
    return tmp_path


# ---------------------------------------------------------------------------
# the helper
# ---------------------------------------------------------------------------

def test_the_blend_entry_for_the_week_is_the_index(roots):
    _write_blend(2026, {3: BLEND_TEAMS})
    index, source = rw._ncaaf_inseason_blend_index(2026, 3)
    assert source == "inseason_blend_wk3"
    assert index == {"auburn": (20.0, 30.0), "baylor": (36.0, 14.0)}


def test_off_is_off_and_says_so(roots, monkeypatch):
    _write_blend(2026, {3: BLEND_TEAMS})
    for value in ("off", "false", "0", "no"):
        monkeypatch.setenv(BLEND_ENV, value)
        assert rw._ncaaf_inseason_blend_index(2026, 3) == (None, "blend_disabled")


def test_weeks_1_and_2_stay_on_sp(roots):
    _write_blend(2026, {3: BLEND_TEAMS})
    assert rw._ncaaf_inseason_blend_index(2026, 2) == (None, "week_below_3")


def test_no_artifact_is_named(roots):
    assert rw._ncaaf_inseason_blend_index(2026, 3) == (None, "no_blend_artifact")


def test_a_missing_week_falls_back_to_the_newest_EARLIER_entry_by_name(roots):
    _write_blend(2026, {3: BLEND_TEAMS, 5: {"auburn": [1.0, 1.0, 3]}})
    index, source = rw._ncaaf_inseason_blend_index(2026, 4)
    assert source == "inseason_blend_wk3_stale_week_for_wk4"
    assert index["baylor"] == (36.0, 14.0)


def test_only_a_LATER_week_is_never_used(roots):
    _write_blend(2026, {5: BLEND_TEAMS})
    assert rw._ncaaf_inseason_blend_index(2026, 3) == (None, "no_blend_entry_at_or_before_wk3")


def test_an_empty_entry_keeps_sp(roots):
    _write_blend(2026, {3: {}})
    assert rw._ncaaf_inseason_blend_index(2026, 3) == (None, "blend_entry_wk3_empty")


def test_the_substitution_precedes_every_reader_of_the_index():
    """The ratings, the league means and the FCS back-out all read `sp_index`;
    the blend must replace it before the first of them, or some lanes would be
    priced on SP+ and others on the blend inside one tick."""
    import inspect

    body = inspect.getsource(rw._run_ncaaf_live_resim_tick)
    swap = body.index("_ncaaf_inseason_blend_index(season, week)")
    assert swap < body.index("sp_league_means(sp_index)")
    assert swap < body.index("_ncaaf_fcs_market_implied_games(")


# ---------------------------------------------------------------------------
# THE TICK, END TO END -- off != on
# ---------------------------------------------------------------------------

class _FakeProjection:
    def __init__(self, away_team, home_team):
        self.away_team = away_team
        self.home_team = home_team


def _live_event():
    return {
        "id": "401",
        "status": {"period": 2, "displayClock": "7:00",
                   "type": {"state": "in", "completed": False, "shortDetail": "x"}},
        "competitions": [{
            "competitors": [
                {"homeAway": "home", "score": "14",
                 "team": {"id": "2", "location": "Auburn", "displayName": "Auburn Tigers", "abbreviation": "AUB"}},
                {"homeAway": "away", "score": "14",
                 "team": {"id": "239", "location": "Baylor", "displayName": "Baylor Bears", "abbreviation": "BAY"}},
            ],
            "situation": {"possession": "2", "down": 1, "distance": 10, "yardLine": 75},
        }],
    }


@pytest.fixture
def tick(roots, monkeypatch):
    monkeypatch.setenv("NCAAF_LIVE_RESIM_SIMS", "200")
    monkeypatch.setenv("SYNDICATE_NCAAF_FCS_MARKET_IMPLIED", "off")
    monkeypatch.setattr(rw, "_season_projection_target_week", lambda sport, season: 3)
    monkeypatch.setattr(rw, "_ncaaf_live_resim_interval_seconds", lambda _status: 0.0)
    monkeypatch.setattr(rw, "_ncaaf_sp_ratings_index", lambda _season: (dict(SP_INDEX), "sp_test"))
    monkeypatch.setattr(
        "syndicate.features.ncaaf.smartsim2_projection.read_projection_artifact",
        lambda **_kwargs: (_FakeProjection("Baylor", "Auburn"),),
    )
    monkeypatch.setattr("scripts.poll_ncaaf_live_state._fetch_scoreboard", lambda _date: {"events": [_live_event()]})
    _write_blend(2026, {3: BLEND_TEAMS})


def _home_win_prob():
    from syndicate.features.shared.refresh_state_store import data_root, read_json_file

    snapshot = read_json_file(lr.live_lens_snapshot_path(data_root()))
    (game,) = snapshot["games"]
    lane = game["gameLens"][0]
    assert lane["source"] == "live_resim"
    return float(lane["modelHomeWinProb"]), snapshot


def test_ON_the_tick_prices_on_the_blend_and_says_so(tick, monkeypatch):
    on = rw._run_ncaaf_live_resim_tick()
    assert on["sp_ratings_source"] == "inseason_blend_wk3"
    assert on["inseason_blend"] == "inseason_blend_wk3"
    assert on["sp_ratings_teams"] == 2
    p_on, snapshot = _home_win_prob()
    assert snapshot["spRatingsSource"] == "inseason_blend_wk3"

    monkeypatch.setenv(BLEND_ENV, "off")
    off = rw._run_ncaaf_live_resim_tick()
    assert off["sp_ratings_source"] == "sp_test"
    assert off["inseason_blend"] == "blend_disabled"
    p_off, _ = _home_win_prob()

    # OFF != ON, in the direction the ratings say: the blend makes Baylor (away)
    # the stronger side, so the home win probability must FALL.
    print(f"LIVE_RESIM_BLEND_REACHABILITY p_home_on={p_on:.4f} p_home_off={p_off:.4f}")
    assert p_on < p_off - 0.10, (p_on, p_off)
