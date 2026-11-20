"""The orientation-free college live game-line join (lane college-neutral-site-live-join, 2026-11-19).

Measured on the fleet 2026-11-19: WVU / Florida (ESPN 401920517) and Auburn / Notre Dame (401920519), both at a neutral
site, carried rows "West Virginia @ Florida" / "Auburn @ Notre Dame" (the odds feed's orientation) while the NCAAB
live re-sim published them away Florida / home WVU and away Notre Dame / home Auburn (ESPN's `homeAway`). The join
keys the ordered pair, so every full-game row was withheld `no_live_gameline_projection` while the lane sat indexed
the other way round: WVU / Florida dark from 1:47 PM CST to the final, Auburn / Notre Dame from its tip.

These pin:
  * the switch: absent = SHADOW (files nothing, counts), `on` files the views, `off` does neither; NCAAB / WNCAAB only;
  * the SIDE MAPPING on a hand-built game: the row's home win probability, its spread side and sign, its state
    scores and its segment margin are the lane's AWAY numbers, and a segment's three-way win probability keeps its
    tie mass out of both sides;
  * the real thing end to end: lanes written by the NCAAB / WNCAAB producer's own functions, reversed against their
    rows, come out of the board's own attach (`board_enrichment.attach_live_gamelines_for_sport`) EXACTLY as an
    independently hand-flipped twin lane in the row's frame does -- full-game and segment rows alike;
  * off != on, shadow == off for every served row, and the count is where a reader looks;
  * EXACT FIRST: a pair a lane already answers is never shadowed, and an exact join is identical in every mode;
  * every field a hit carries is classified, and an unclassified one refuses the view by name.
"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone

import pytest

from syndicate.features.ncaab import live_resim as lr
from syndicate.features.shared import board_enrichment
from syndicate.features.shared import live_gameline_join as lgj
from syndicate.features.shared import live_gameline_orientation as orientation

AS_OF = (datetime.now(timezone.utc) - timedelta(seconds=40)).isoformat()
NOW = datetime.now(timezone.utc).isoformat()
DATE = "2026-11-19"

# ESPN listed the WVU / Florida game away Florida, home WVU; the odds feed (and so every board row) the other way.
ESPN_AWAY, ESPN_HOME = "Florida Gators", "West Virginia Mountaineers"
ROW_AWAY, ROW_HOME = ESPN_HOME, ESPN_AWAY


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in (orientation.ORIENTATION_JOIN_ENV, lgj.LANE_AGE_GATE_ENV, lgj.MAX_LANE_AGE_ENV,
                lgj.COLLEGE_SEGMENT_PRICING_ENV, lgj.QUOTE_ORDER_BASIS_ENV, lgj.MODEL_BEHIND_SCORE_ENV,
                "SYNDICATE_LIVE_ENDGAME_FRESHNESS", "SYNDICATE_CELL_CALIBRATION_LIVE_PROB"):
        monkeypatch.delenv(key, raising=False)


# ----------------------------------------------------------------------------------------------------- the switch

def test_absent_is_shadow_and_only_college_basketball_ever_joins_reversed():
    for sport in ("ncaab", "wncaab", "NCAAB"):
        assert orientation.orientation_join_mode(sport, {}) == orientation.MODE_SHADOW
        assert orientation.orientation_join_mode(sport, {orientation.ORIENTATION_JOIN_ENV: "nonsense"}) == "shadow"
        for value in ("on", "ON", "1", "true", "yes"):
            assert orientation.orientation_join_mode(sport, {orientation.ORIENTATION_JOIN_ENV: value}) == "on"
        for value in ("off", "0", "false", "no"):
            assert orientation.orientation_join_mode(sport, {orientation.ORIENTATION_JOIN_ENV: value}) == "off"
    for sport in ("nba", "ncaaf", "nfl", "nhl", "mlb", "wnba", "soccer", None):
        assert orientation.orientation_join_mode(sport, {orientation.ORIENTATION_JOIN_ENV: "on"}) == "off"


# ------------------------------------------------------------------------------------------ a hand-built game

def _literal_lane_game():
    """One live lane in the producer's shape (`ncaab/live_resim._lane_row` / `build_game_lens`), ESPN's frame:
    home WVU. WVU trails 23-32 with 10:00 left; the anchored full-game margin is WVU -6 in 70 sims and WVU +4 in 30,
    so P(WVU wins) = 0.30. The second half: WVU -3 in 50, level in 20, WVU +2 in 30 (three-way 0.30 / 0.20 / 0.50)."""
    return {
        "event_id": "401920517", "home": ESPN_HOME, "away": ESPN_AWAY, "home_name": ESPN_HOME, "away_name": ESPN_AWAY,
        "home_id": "277", "away_id": "57", "nameSource": "odds", "status": {"detailedState": "In Progress"},
        "gameLens": [{
            "key": "live", "label": "Live", "source": "live_resim", "closed": False,
            "modelHomeWinProb": 0.30, "rawModelHomeWinProb": 0.34, "simsRun": 100,
            "liveStateAsOf": AS_OF, "liveScoreChangedAt": AS_OF,
            "projection": {
                "homeMargin": -3.0, "rawHomeMargin": -2.0, "total": 140.0,
                "homeScore": 23, "awayScore": 32, "period": 2, "clockSeconds": 600.0, "scoreSource": "official",
                "totalRunsDist": {"136": 50, "144": 50},
                "marginDist": {"-6": 70, "4": 30},
                "marginAnchor": {"marketHomeMargin": -4.5, "simHomeMargin": -1.0, "offset": -3.5, "books": 8},
                "segments": {
                    "h1": {"total_mean": 55.0, "total_dist": {"55": 100}, "margin_dist": {"-9": 100}, "sims": 100,
                           "includesOvertime": False, "remainingFraction": 0.0, "settled": True,
                           "marginAnchored": True, "marginAnchorOffset": 0.0},
                    "h2": {"total_mean": 85.0, "total_dist": {"84": 50, "86": 50},
                           "margin_dist": {"-3": 50, "0": 20, "2": 30}, "sims": 100, "includesOvertime": True,
                           "remainingFraction": 0.25, "settled": False, "marginAnchored": True,
                           "marginAnchorOffset": -0.9},
                },
            },
        }],
    }


def _row(segment, market, line, *, away=ROW_AWAY, home=ROW_HOME, sport="ncaab", home_score=32, away_score=23,
         market_prob=0.5):
    sides = ["over", "under"] if market == "totals" else ["home", "away"]
    return {"kind": "game", "sport": sport, "market": market, "segment": segment, "line": line, "sides": sides,
            "away_team": away, "home_team": home, "age_seconds": 20.0, "updated_at": NOW,
            "game": {"state": "live", "home_score": home_score, "away_score": away_score},
            "projection": {"market_fair_prob_over": market_prob}}


def _grid(**kw):
    return [_row("full", "h2h", None, **kw), _row("full", "spreads", 3.5, **kw), _row("full", "totals", 140.5, **kw),
            _row("h2", "spreads", 0.5, **kw), _row("h2", "totals", 85.5, **kw)]


def _attach(monkeypatch, snapshot, grid, *, sport="ncaab", mode=None):
    from syndicate.features.shared import refresh_state_store

    if mode is None:
        monkeypatch.delenv(orientation.ORIENTATION_JOIN_ENV, raising=False)
    else:
        monkeypatch.setenv(orientation.ORIENTATION_JOIN_ENV, mode)
    monkeypatch.setattr(refresh_state_store, "read_json_file", lambda _path: copy.deepcopy(snapshot))
    return board_enrichment.attach_live_gamelines_for_sport(grid, sport=sport, selected_date=DATE)


def test_the_rows_side_of_every_number_is_the_lanes_away_side(monkeypatch):
    """The side mapping, by hand. Rows: West Virginia @ Florida, so the row's HOME is the lane's AWAY (Florida)."""
    grid = _grid()
    coverage = _attach(monkeypatch, {"games": [_literal_lane_game()]}, grid, mode="on")
    h2h, spread, total, h2_spread, h2_total = grid
    assert lgj.REASON_NO_LIVE_PROJECTION not in (coverage.get("withheld_by_reason") or {})

    # h2h: P(row home = Florida wins) = P(lane away wins) = 1 - 0.30.
    assert h2h["live_gameline"]["home_win_prob"] == pytest.approx(0.70)
    # The re-sim's state, in the row's frame: Florida 32 at home, WVU 23 away.
    assert h2h["live_gameline"]["state_home_score"] == 32 and h2h["live_gameline"]["state_away_score"] == 23
    # The point forecast: Florida by 3, not WVU by 3.
    assert h2h["live_gameline"]["home_margin"] == pytest.approx(3.0)
    # Spreads, the away-frame line +3.5 (WVU +3.5): the row's home (Florida) covers when Florida's margin > 3.5,
    # i.e. in the 70 sims Florida wins by 6. In the lane's own frame that same 3.5 would read 0.30 -- the sign error.
    # (`model_prob_raw` is the histogram's own share; the priced number is that, Agresti-Coull smoothed and scaled.)
    assert spread["live_gameline"]["model_prob_raw"] == pytest.approx(0.70)
    assert spread["live_gameline"]["model_prob"] > 0.5 and spread["live_gameline"]["edge_pp"] > 0
    assert h2h["live_gameline"]["model_prob_raw"] == pytest.approx(0.70)
    assert spread["live_gameline"]["home_margin"] == pytest.approx(3.0)
    # Totals do not depend on the side.
    assert total["live_gameline"]["total_mean"] == pytest.approx(140.0)
    assert total["live_gameline"]["model_prob_raw"] is not None
    # The second half, Live column (segment pricing is off): Florida's mean margin is +0.9 (= -(-3*.5 + 0 + 2*.3)).
    assert h2_spread[lgj.LIVE_DISPLAY_KEY]["home_margin"] == pytest.approx(0.9)
    assert h2_total[lgj.LIVE_DISPLAY_KEY]["total_mean"] == pytest.approx(85.0)
    # Counted where a reader looks.
    assert coverage["orientation_reversed"] == {"mode": "on", "games": 1, "rows": 5, "joined": 5}
    assert coverage["index_diagnostics"]["orientation_reversed"]["joined"] == 5


def test_a_segment_keeps_its_tie_mass_out_of_both_sides():
    """The second half can end level, so the restated three-way P(home) is P(lane margin < 0), not 1 - P(> 0)."""
    hit = lgj._segment_hit(_literal_lane_game()["gameLens"][0],
                           _literal_lane_game()["gameLens"][0]["projection"], "h2")
    assert hit["home_win_prob"] == pytest.approx(0.30)          # lane: WVU ahead in 30 of 100
    view, why = orientation.reversed_view(hit)
    assert why is None
    assert view["home_win_prob"] == pytest.approx(0.50)         # row: Florida ahead in 50 of 100 -- not 0.70
    assert view["margin_dist"] == {"3": 50, "0": 20, "-2": 30}
    assert view["margin_dist_raw"] == view["margin_dist"]
    assert view["home_margin"] == pytest.approx(0.9)
    assert view[orientation.VIEW_MARKER] is True
    assert hit["margin_dist"] == {"-3": 50, "0": 20, "2": 30}   # the lane's own hit is untouched


# ------------------------------------------------------------------- the producer's own lanes, end to end

def _producer_game(league, *, away, home, event_id="401920519", seed=11):
    """A lane written by the producer's own functions (`resim_live_game` -> `stamp_segment_progress` -> `anchor_result`
    -> `_lane_row`), with a random engine: H2 / Q3 in progress, anchored to the market."""
    import numpy as np

    regulation = 2 if league == "ncaab" else 4
    draws = np.random.default_rng(seed)

    def simulate(_rng, _gs):
        hq = [int(x) for x in draws.integers(12, 46, size=regulation)]
        aq = [int(x) for x in draws.integers(12, 46, size=regulation)]
        if sum(hq) == sum(aq):
            return {"ot_pts": [7]}, {"ot_pts": [4]}, hq, aq
        return {}, {}, hq, aq

    result = lr.resim_live_game({}, None, sims=lr.MIN_SIMS, base_seed=3, simulate=simulate, league=league)
    period = 2 if league == "ncaab" else 3
    facts = lr.ResumeFacts(event_id=event_id, home_id="2", away_id="87", home_score=41, away_score=37, period=period,
                           clock_seconds=431.0, possession=None, last_seq=120, as_of=AS_OF, tip_wallclock="",
                           score_changed_at=AS_OF)
    result = lr.stamp_segment_progress(result, facts, league)
    result = lr.anchor_result(result, lr.MarginAnchor(market_home_margin=-2.5, sim_home_margin=1.5, books=9),
                              remaining_fraction=lr.remaining_regulation_fraction(facts, league))
    names = {"home": home, "away": away, "home_id": "2", "away_id": "87", "source": "odds"}
    return lr._lane_row(event_id, names, facts, result)


def _negate_keys(dist):
    return {str(-int(k)): v for k, v in dist.items()}


def _hand_flipped_twin(game):
    """The same lane as the producer WOULD have written it in the row's frame. Written here, at the LENS level, on
    purpose: the module restates the join's HIT, so the two flips share no code and agreeing is evidence."""
    twin = copy.deepcopy(game)
    for a, b in (("home", "away"), ("home_name", "away_name"), ("home_id", "away_id")):
        twin[a], twin[b] = game[b], game[a]
    lane = twin["gameLens"][0]
    lane["modelHomeWinProb"] = 1.0 - game["gameLens"][0]["modelHomeWinProb"]
    if lane.get("rawModelHomeWinProb") is not None:
        lane["rawModelHomeWinProb"] = 1.0 - lane["rawModelHomeWinProb"]
    proj = lane["projection"]
    proj["homeMargin"] = -proj["homeMargin"]
    proj["homeScore"], proj["awayScore"] = proj["awayScore"], proj["homeScore"]
    proj["marginDist"] = _negate_keys(proj["marginDist"])
    for block in proj["segments"].values():
        block["margin_dist"] = _negate_keys(block["margin_dist"])
    return twin


def _league_grid(league, away, home):
    rows = [_row("full", "h2h", None, away=away, home=home, sport=league, home_score=37, away_score=41),
            _row("full", "spreads", 2.5, away=away, home=home, sport=league, home_score=37, away_score=41),
            _row("full", "spreads", -4.5, away=away, home=home, sport=league, home_score=37, away_score=41),
            _row("full", "totals", 150.5, away=away, home=home, sport=league, home_score=37, away_score=41)]
    for seg in lr.segment_layout(league):
        rows.append(_row(seg, "spreads", 1.5, away=away, home=home, sport=league, home_score=37, away_score=41))
        rows.append(_row(seg, "totals", 40.5, away=away, home=home, sport=league, home_score=37, away_score=41))
    return rows


def _served(coverage):
    return {k: v for k, v in coverage.items() if k not in ("index_diagnostics", "orientation_reversed",
                                                             "lane_age_max_s")}  # the last is wall-clock


@pytest.mark.parametrize("league", ["ncaab", "wncaab"])
def test_a_reversed_games_rows_come_out_exactly_as_its_hand_flipped_twins_do(monkeypatch, league):
    """The 11-19 Auburn / Notre Dame shape: rows Auburn @ Notre Dame, the lane (ESPN) Notre Dame @ Auburn. With the
    switch on they must equal, row for row, the rows the same lane gives when written in their frame."""
    espn_away, espn_home = "Notre Dame Fighting Irish", "Auburn Tigers"
    lane_game = _producer_game(league, away=espn_away, home=espn_home)
    twin = _hand_flipped_twin(lane_game)
    assert (twin["away"], twin["home"]) == (espn_home, espn_away)

    reference = _league_grid(league, espn_home, espn_away)
    cov_ref = _attach(monkeypatch, {"games": [twin]}, reference, sport=league, mode="on")
    assert cov_ref["rows_live_gameline_projected"] > 0  # the reference joined, so the comparison means something

    reversed_rows = _league_grid(league, espn_home, espn_away)
    cov_rev = _attach(monkeypatch, {"games": [lane_game]}, reversed_rows, sport=league, mode="on")
    assert reversed_rows == reference
    assert _served(cov_rev) == _served(cov_ref)
    lit = sum(1 for r in reference if "live_gameline" in r or lgj.LIVE_DISPLAY_KEY in r)
    assert cov_rev["orientation_reversed"] == {"mode": "on", "games": 1, "rows": len(reversed_rows), "joined": lit}
    assert cov_ref["orientation_reversed"]["rows"] == 0  # the twin joins exactly; nothing is restated


@pytest.mark.parametrize("league", ["ncaab", "wncaab"])
def test_off_and_shadow_leave_the_reversed_rows_dark_and_on_lights_them(monkeypatch, league):
    """off != on, through the board's own attach. Shadow serves exactly what off serves and counts the rows."""
    lane = _producer_game(league, away="Notre Dame Fighting Irish", home="Auburn Tigers")
    served = {}
    for mode in ("off", None, "on"):
        grid = _league_grid(league, "Auburn Tigers", "Notre Dame Fighting Irish")
        coverage = _attach(monkeypatch, {"games": [lane]}, grid, sport=league, mode=mode)
        served[mode] = (grid, coverage)
    off_grid, off_cov = served["off"]
    assert off_cov["rows_live_gameline_projected"] == 0
    assert off_cov["withheld_by_reason"][lgj.REASON_NO_LIVE_PROJECTION] == 4  # every full-game row, by name
    assert all("live_gameline" not in r and lgj.LIVE_DISPLAY_KEY not in r for r in off_grid)
    assert "orientation_reversed" not in off_cov

    shadow_grid, shadow_cov = served[None]
    assert shadow_grid == off_grid
    assert _served(shadow_cov) == _served(off_cov)
    n_rows = len(shadow_grid)
    assert shadow_cov["orientation_reversed"] == {"mode": "shadow", "games": 1, "rows": n_rows, "joined": 0}

    on_grid, on_cov = served["on"]
    assert on_grid != off_grid
    assert on_cov["rows_live_gameline_projected"] == 4
    assert lgj.REASON_NO_LIVE_PROJECTION not in on_cov["withheld_by_reason"]
    assert all(isinstance(r.get("live_gameline"), dict) for r in on_grid if r["segment"] == "full")
    # Every segment still to play shows its Live number; a settled one shows nothing, exactly as on any game.
    open_segments = [r for r in on_grid if r["segment"] != "full" and r["segment"] in ("h2", "q3", "q4")]
    assert open_segments and all(isinstance(r.get(lgj.LIVE_DISPLAY_KEY), dict) for r in open_segments)
    assert on_cov["orientation_reversed"]["joined"] == sum(
        1 for r in on_grid if "live_gameline" in r or lgj.LIVE_DISPLAY_KEY in r)


def test_an_exact_join_is_identical_in_every_mode(monkeypatch):
    lane = _producer_game("ncaab", away="Notre Dame Fighting Irish", home="Auburn Tigers")
    grids = {}
    for mode in ("off", None, "on"):
        grid = _league_grid("ncaab", "Notre Dame Fighting Irish", "Auburn Tigers")
        coverage = _attach(monkeypatch, {"games": [lane]}, grid, mode=mode)
        grids[mode] = (grid, _served(coverage))
        if mode is not None and mode != "off":
            assert coverage["orientation_reversed"]["rows"] == 0
    assert grids["off"] == grids[None] == grids["on"]
    assert grids["on"][1]["rows_live_gameline_projected"] == 4


def test_a_pair_some_lane_answers_exactly_is_never_shadowed_by_a_view():
    """Two lanes, one per orientation (never seen, but it must not be resolved by a guess): no view is filed, and
    each row meets the lane named in its own order."""
    a = _producer_game("ncaab", away="Auburn Tigers", home="Notre Dame Fighting Irish", event_id="1", seed=1)
    b = _producer_game("ncaab", away="Notre Dame Fighting Irish", home="Auburn Tigers", event_id="2", seed=2)
    index = lgj.build_live_gameline_index({"games": [a, b]}, sport="ncaab", sources=("live_resim",))
    before = {k: list(v) for k, v in index.candidates.items()}
    state = orientation.prepare(index, None, sport="ncaab", environ={orientation.ORIENTATION_JOIN_ENV: "on"})
    assert state.views == 0 and state.keys == set()
    assert {k: list(v) for k, v in index.candidates.items()} == before
    key = (lgj._norm_team("Auburn Tigers"), lgj._norm_team("Notre Dame Fighting Irish"))
    hit, _why = lgj.resolve_live_gameline(index, key, sport="ncaab")
    assert hit["home_win_prob"] == a["gameLens"][0]["modelHomeWinProb"]
    assert orientation.VIEW_MARKER not in hit


def test_no_other_sport_is_restated_even_with_the_switch_on(monkeypatch):
    lane = _literal_lane_game()
    index = lgj.build_live_gameline_index({"games": [lane]}, sport="nba", sources=("live_resim",))
    state = orientation.prepare(index, None, sport="nba", environ={orientation.ORIENTATION_JOIN_ENV: "on"})
    assert state.mode == "off" and state.views == 0
    assert (lgj._norm_team(ROW_AWAY), lgj._norm_team(ROW_HOME)) not in index.candidates
    assert orientation.finish(state, _grid(sport="nba"), {}, {}) is None


# ------------------------------------------------------------------------------- every field is classified

@pytest.mark.parametrize("league", ["ncaab", "wncaab"])
def test_every_field_of_a_real_hit_is_classified_and_restates(league):
    """Over `dataclasses.fields()`'s spirit: the hit's ACTUAL keys (full game and every segment), from a lane the
    producer wrote, each in exactly one table. A field added to the join's hit fails here until it is classified."""
    assert not (orientation.SIDE_FREE_FIELDS & orientation.RESTATED_FIELDS)
    lane = _producer_game(league, away="Notre Dame Fighting Irish", home="Auburn Tigers")
    indexes = [lgj.build_live_gameline_index({"games": [lane]}, sport=league, sources=("live_resim",))]
    indexes += [lgj.build_live_gameline_index({"games": [lane]}, sport=league, sources=("live_resim",), segment=seg)
                for seg in lr.segment_layout(league)]
    seen = 0
    for index in indexes:
        for projections in index.candidates.values():
            for projection in projections:
                unknown = set(projection) - orientation.SIDE_FREE_FIELDS - orientation.RESTATED_FIELDS
                assert not unknown, f"classify {sorted(unknown)} in live_gameline_orientation"
                view, why = orientation.reversed_view(projection)
                assert why is None and view is not None
                assert set(view) == set(projection) | {orientation.VIEW_MARKER}
                seen += 1
    assert seen == 1 + len(lr.segment_layout(league))


def test_a_field_it_cannot_restate_refuses_the_view_by_name():
    base = lgj.live_gameline_from_lens(_literal_lane_game()["gameLens"], sources=("live_resim",))
    assert orientation.reversed_view({**base, "home_pace": 70.0}) == (None, "unclassified_field:home_pace")
    assert orientation.reversed_view({**base, "analytic_markets": {"spread": {"line": -3.5, "p_home_cover": 0.6}}}) \
        == (None, "analytic_market_not_restatable")
    assert orientation.reversed_view({**base, "margin_dist": {"-6.5": 1}}) == (None, "margin_dist_key_not_integer")
    assert orientation.reversed_view({**base, "progress": {"half": "top"}}) \
        == (None, "progress_field_not_side_free:half")
    assert orientation.reversed_view({**base, "home_win_prob": 1.4}) == (None, "home_win_prob_out_of_range")

    index = lgj.build_live_gameline_index({"games": [_literal_lane_game()]}, sport="ncaab", sources=("live_resim",))
    for projections in index.candidates.values():
        projections[0]["home_pace"] = 70.0
    state = orientation.prepare(index, None, sport="ncaab", environ={orientation.ORIENTATION_JOIN_ENV: "on"})
    assert state.views == 0 and state.refused == {"unclassified_field:home_pace": 1}
    assert (lgj._norm_team(ROW_AWAY), lgj._norm_team(ROW_HOME)) not in index.candidates


def test_the_line_is_printed_only_when_there_is_a_view_and_parses(monkeypatch, capsys):
    _attach(monkeypatch, {"games": [_producer_game("ncaab", away="Notre Dame Fighting Irish",
                                                   home="Auburn Tigers")]},
            _league_grid("ncaab", "Notre Dame Fighting Irish", "Auburn Tigers"), mode="on")
    assert orientation.LOG_TAG not in capsys.readouterr().out  # an exact join says nothing

    _attach(monkeypatch, {"games": [_literal_lane_game()]}, _grid())
    lines = [line for line in capsys.readouterr().out.splitlines() if orientation.LOG_TAG in line]
    assert len(lines) == 1
    fields = dict(token.split("=", 1) for token in lines[0].split(orientation.LOG_TAG)[1].split())
    assert fields["sport"] == "ncaab" and fields["mode"] == "shadow"
    assert (fields["games"], fields["rows"], fields["joined"]) == ("1", "5", "0")
    assert fields["refused"] == "{}" and fields["error"] == "none"
    assert fields["pairs"] == "west_virginia_mountaineers@florida_gators"
