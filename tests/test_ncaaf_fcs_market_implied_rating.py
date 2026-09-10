"""FBS-vs-FCS live re-sim on a MARKET-IMPLIED rating (lane `ncaaf-fcs-market-implied-rating`).

WHY THIS EXISTS. FAMU @ MIA (2026-09-10) was absent from the NCAAF live lens: the
projections artifact is FBS-vs-FBS only, and `live_resim._ratings_for` refuses a
side with no SP+ row rather than rate it league-average. User decision
2026-09-10: rate the FCS side off the market's PREGAME spread and total.

WHAT MUST NOT BREAK:
  1. REACHABILITY FIRST (`model_engine_standard.md` §4.3): flag off -> the game is
     not in the snapshot at all; flag on -> it gains one `live_resim` lane.
  2. PROVENANCE: every such lane says `ratingSource: market_implied`; an FBS lane
     carries no such key, so its payload is unchanged.
  3. THE LINE IS PREGAME ONLY: a live odds object is never read as the prior, and
     a live game with no captured line refuses by name (`no_pregame_line`).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

import scripts.run_refresh_worker as rw
from syndicate.features.ncaaf import live_resim as lr

ENV = "SYNDICATE_NCAAF_FCS_MARKET_IMPLIED"

# Production SP+ 2026, read from /api/ops/artifacts/export (render substrate),
# `fetched_at` 2026-09-10T01:36:36Z: Miami (35.0, 13.3); Florida A&M absent.
MIAMI_SP = (35.0, 13.3)
MEANS = (25.656, 26.195)
FAMU_KEY = "florida a&m@miami"


def _odds(*, spread=-59.5, total=65.5, home_fav=True, away_fav=False):
    return [{
        "provider": {"name": "DraftKings"}, "details": "MIA -59.5",
        "spread": spread, "overUnder": total,
        "homeTeamOdds": {"favorite": home_fav}, "awayTeamOdds": {"favorite": away_fav},
    }]


def _event(*, away_loc="Florida A&M", home_loc="Miami", state="pre", odds=True,
           period=1, clock="15:00", away_score="0", home_score="0", eid="401858213",
           away_id="50", home_id="2390"):
    event = {
        "id": eid,
        "status": {"period": period, "displayClock": clock,
                   "type": {"state": state, "completed": state == "post", "shortDetail": "x"}},
        "competitions": [{
            "competitors": [
                {"homeAway": "home", "score": home_score,
                 "team": {"id": home_id, "location": home_loc,
                          "displayName": f"{home_loc} Hurricanes", "abbreviation": "HOM"}},
                {"homeAway": "away", "score": away_score,
                 "team": {"id": away_id, "location": away_loc,
                          "displayName": f"{away_loc} Rattlers", "abbreviation": "AWY"}},
            ],
        }],
    }
    if odds:
        event["competitions"][0]["odds"] = _odds()
    if state == "in":
        event["competitions"][0]["situation"] = {
            "possession": home_id, "down": 1, "distance": 10, "yardLine": 75,
        }
    return event


# ---------------------------------------------------------------------------
# THE PARSER AND THE FORMULA
# ---------------------------------------------------------------------------

class TestPregameLine:
    def test_home_favourite_reads_as_a_positive_home_margin(self):
        line = lr.pregame_line_from_espn_event(_event())
        assert line == {"home_margin": 59.5, "total": 65.5, "provider": "DraftKings",
                        "details": "MIA -59.5"}

    def test_away_favourite_reads_as_a_negative_home_margin(self):
        event = _event()
        event["competitions"][0]["odds"] = _odds(spread=7.0, total=48.5, home_fav=False, away_fav=True)
        assert lr.pregame_line_from_espn_event(event)["home_margin"] == -7.0

    def test_a_LIVE_event_never_yields_a_pregame_line(self):
        """The whole contract: a live quote is not the prior."""
        assert lr.pregame_line_from_espn_event(_event(state="in")) is None
        assert lr.pregame_line_from_espn_event(_event(state="post")) is None

    def test_no_odds_and_an_ambiguous_favourite_are_refused(self):
        assert lr.pregame_line_from_espn_event(_event(odds=False)) is None
        event = _event()
        event["competitions"][0]["odds"] = _odds(home_fav=True, away_fav=True)
        assert lr.pregame_line_from_espn_event(event) is None


class TestImpliedComponents:
    def _points(self, off, dfn, opp_off, opp_dfn):
        baseline = (MEANS[0] + MEANS[1]) / 2.0
        return off + opp_dfn - baseline, opp_off + dfn - baseline

    def test_the_market_line_is_reproduced_under_sp_plus_own_formula(self):
        """Two unknowns, two equations: plugging the implied components back into
        SP+'s additive form must return the market's 62.5 - 3.0."""
        u_off, u_def = lr.market_implied_sp_components(
            rated_offense=MIAMI_SP[0], rated_defense=MIAMI_SP[1], rated_is_home=True,
            home_margin=59.5, total=65.5, league_means=MEANS,
        )
        miami_pts, famu_pts = self._points(MIAMI_SP[0], MIAMI_SP[1], u_off, u_def)
        assert miami_pts == pytest.approx(62.5)
        assert famu_pts == pytest.approx(3.0)

    def test_the_rated_AWAY_case(self):
        u_off, u_def = lr.market_implied_sp_components(
            rated_offense=30.0, rated_defense=20.0, rated_is_home=False,
            home_margin=-24.0, total=52.0, league_means=MEANS,
        )
        away_pts, home_pts = self._points(30.0, 20.0, u_off, u_def)
        assert away_pts == pytest.approx(38.0)
        assert home_pts == pytest.approx(14.0)

    def test_a_line_implying_a_negative_score_is_refused(self):
        assert lr.market_implied_sp_components(
            rated_offense=35.0, rated_defense=13.3, rated_is_home=True,
            home_margin=70.0, total=60.0, league_means=MEANS,
        ) is None


# ---------------------------------------------------------------------------
# THE TICK, END TO END, THROUGH THE JOIN THE BOARD CALLS
# ---------------------------------------------------------------------------

class _FakeProjection:
    def __init__(self, away_team, home_team):
        self.away_team = away_team
        self.home_team = home_team


@pytest.fixture
def tick(tmp_path, monkeypatch):
    """Wire the REAL tick; stub only its inputs. Returns a setter for ESPN events."""
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("SYNDICATE_NCAAF_SOURCE_ROOT", str(tmp_path / "ncaaf_source"))
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path / "reports"))
    monkeypatch.setenv("SYNDICATE_REFRESH_STATE_BACKEND", "file")
    monkeypatch.setenv("NCAAF_LIVE_RESIM_SIMS", "12")
    monkeypatch.delenv(ENV, raising=False)
    monkeypatch.setattr(rw, "_season_projection_target_week", lambda sport, season: 2)
    monkeypatch.setattr(rw, "_ncaaf_live_resim_interval_seconds", lambda _status: 0.0)
    monkeypatch.setattr(
        rw, "_ncaaf_sp_ratings_index",
        lambda _season: ({"miami": MIAMI_SP, "auburn": (28.0, 18.0), "baylor": (25.0, 20.0)}, "test"),
    )
    monkeypatch.setattr(
        "syndicate.features.ncaaf.smartsim2_projection.read_projection_artifact",
        lambda **_kwargs: (_FakeProjection("Baylor", "Auburn"),),
    )
    state = {"events": []}
    monkeypatch.setattr(
        "scripts.poll_ncaaf_live_state._fetch_scoreboard", lambda _date: {"events": list(state["events"])}
    )

    def set_events(*events):
        state["events"] = list(events)

    return set_events


def _fbs_live():
    return _event(away_loc="Baylor", home_loc="Auburn", state="in", odds=False, period=2,
                  clock="7:00", away_score="7", home_score="14", eid="401", away_id="239", home_id="2")


def _snapshot():
    from syndicate.features.shared.refresh_state_store import data_root, read_json_file

    return read_json_file(lr.live_lens_snapshot_path(data_root()))


def _status():
    store = rw._refresh_state_store()
    return store["read_json_file"](rw._ncaaf_live_resim_status_path()) or {}


def _lanes_by_game(snapshot):
    return {f"{g['away_name']}@{g['home_name']}".lower(): g["gameLens"][0] for g in snapshot["games"]}


def _famu_live():
    return _event(state="in", odds=False, period=2, clock="9:12", away_score="0", home_score="21")


def test_ON_captures_the_line_pregame_then_resims_the_live_game_on_it(tick):
    tick(_event(state="pre"), _fbs_live())
    first = rw._run_ncaaf_live_resim_tick()
    assert first["fcs"]["candidates"] == 1
    assert first["fcs"]["lines_captured"] >= 1
    captured = _status()["fcsPregameLines"][FAMU_KEY]
    assert captured["home_margin"] == 59.5 and captured["total"] == 65.5
    assert captured["event_id"] == "401858213"

    # Kickoff. The live event carries NO odds: the prior must come from the capture.
    tick(_famu_live(), _fbs_live())
    second = rw._run_ncaaf_live_resim_tick()
    assert second["fcs"]["priced_on_implied_rating"] == 1
    assert second["coverage"]["live_resimmed"] == 2

    lanes = _lanes_by_game(_snapshot())
    famu = lanes[FAMU_KEY]
    assert famu["source"] == "live_resim"
    assert famu["ratingSource"] == "market_implied"
    assert famu["marketImplied"]["unrated_team"] == "florida a&m"
    assert famu["marketImplied"]["line"]["home_margin"] == 59.5
    assert 0.5 < famu["modelHomeWinProb"] <= 1.0

    # PROVENANCE IS ADDITIVE: the FBS lane is exactly what it was.
    fbs = lanes["baylor@auburn"]
    assert fbs["source"] == "live_resim"
    assert "ratingSource" not in fbs and "marketImplied" not in fbs

    # And it reaches the JOIN the board calls, on the grid's spelling.
    from syndicate.features.shared.live_gameline_join import build_live_gameline_index, lens_sources_for_sport

    index = build_live_gameline_index(_snapshot(), sources=lens_sources_for_sport("ncaaf"), sport="ncaaf")
    assert ("florida a&m rattlers", "miami hurricanes") in index


def test_OFF_the_game_is_not_in_the_snapshot_at_all(tick, monkeypatch):
    """off != on: the flag decides whether the FCS game exists in the lens."""
    tick(_event(state="pre"), _fbs_live())
    rw._run_ncaaf_live_resim_tick()                     # captures the line, flag on
    tick(_famu_live(), _fbs_live())
    monkeypatch.setenv(ENV, "off")
    off = rw._run_ncaaf_live_resim_tick()
    assert off["fcs"] == {"enabled": False}
    assert set(_lanes_by_game(_snapshot())) == {"baylor@auburn"}

    monkeypatch.delenv(ENV)
    on = rw._run_ncaaf_live_resim_tick()
    assert on["fcs"]["priced_on_implied_rating"] == 1
    assert set(_lanes_by_game(_snapshot())) == {"baylor@auburn", FAMU_KEY}


def test_a_live_game_with_no_captured_line_refuses_by_name(tick):
    """Deployed after kickoff, say: no capture, and the live odds are NOT used."""
    live_with_odds = _famu_live()
    live_with_odds["competitions"][0]["odds"] = _odds()
    tick(live_with_odds, _fbs_live())
    meta = rw._run_ncaaf_live_resim_tick()
    assert meta["fcs"]["no_pregame_line"] == 1
    assert meta["fcs"]["lines_captured"] == 0

    famu = _lanes_by_game(_snapshot())[FAMU_KEY]
    assert famu["source"] == "pregame"
    assert famu["liveResimRefusal"] == "no_pregame_line"
    assert "modelHomeWinProb" not in famu

    from syndicate.features.shared.live_gameline_join import build_live_gameline_index, lens_sources_for_sport

    index = build_live_gameline_index(_snapshot(), sources=lens_sources_for_sport("ncaaf"), sport="ncaaf")
    assert ("florida a&m rattlers", "miami hurricanes") not in index


def test_captured_lines_survive_an_early_return_and_are_pruned_after_two_days(tick):
    tick(_event(state="pre"), _fbs_live())
    rw._run_ncaaf_live_resim_tick()
    store = rw._refresh_state_store()
    status = _status()
    status["fcsPregameLines"]["stale@game"] = {
        "home_margin": 3.0, "total": 50.0, "captured_at": "2026-01-01T00:00:00+00:00",
    }
    store["write_json_file"](rw._ncaaf_live_resim_status_path(), status)
    rw._run_ncaaf_live_resim_tick()
    kept = _status()["fcsPregameLines"]
    assert FAMU_KEY in kept
    assert "stale@game" not in kept


def test_the_flag_defaults_on_and_only_named_values_turn_it_off(monkeypatch):
    monkeypatch.delenv(ENV, raising=False)
    assert lr.fcs_market_implied_enabled() is True
    for value in ("off", "0", "false", "NO"):
        monkeypatch.setenv(ENV, value)
        assert lr.fcs_market_implied_enabled() is False
    monkeypatch.setenv(ENV, "on")
    assert lr.fcs_market_implied_enabled() is True
