"""A prop market the books pull mid-game keeps a DISPLAY-ONLY live number (`#762` (6), user "Yes, build it" 2026-11-08).

Measured 2026-11-07 on the fleet: 1,598 of 14,478 live NBA prop row-builds had their player in the lens and no line
for their market, 79% of one late build's rows. The re-sim priced only each game's LATEST odds pull, books take props
down as a game goes on, and the board keeps the row. These tests drive the real producer over two ticks, run its rows
through the real join and the board's column builder, and pin that a pulled line is shown and never priced -- also
when its flag is lost on the way (off != on, and fail-safe). Hermetic: no network, no data/."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from syndicate.features.nba import live_resim as lr
from syndicate.features.shared import live_projection_join as J
from syndicate.features.shared.board_enrichment import attach_modelled_fair_edges
from syndicate.features.shared.layer2_board import _live_projection_columns, _model_value_ev
from syndicate.features.shared.live_edge_policy import live_edge_unavailable_reason
from tests.basketball_engine_fixtures import synthetic_game_kwargs
from tests.basketball_pbp_fixtures import Game

PLAYER = "De'Aaron Fox"
NK = lr.normalize_name(PLAYER)
BANKED = {"pts": 12, "reb": 3, "ast": 4, "threes": 1, "stl": 0, "blk": 0, "tov": 1}
# Rest-of-game draws: points +3 (30) or +8 (70) -> mean final 18.5, P(over 15.5) = P(over 19.5) = 0.7; rebounds +0 or
# +3 -> P(over 3.5) = 0.5. Nothing below is a certainty.
REMAINDERS = {"pts": {"3": 30, "8": 70}, "reb": {"0": 50, "3": 50}}
DATE = "2026-01-15"
T0 = datetime(2026, 1, 16, 1, 0, tzinfo=timezone.utc)


def _result():
    return {"sims_run": 100, "home_win_prob": 0.6, "total_mean": 220.0, "home_margin_mean": 3.0,
            "total_dist": {"220": 100}, "margin_dist": {"3": 100}, "segments": {},
            "player_remainders": {"home": {PLAYER: {k: dict(v) for k, v in REMAINDERS.items()}}, "away": {}}}


def _rows_at(rows, prop, line):
    return [r for r in rows if r["prop"] == prop and r["line"] == line]


# ------------------------------------------------------------------------------------------------ the producer

def test_a_pulled_line_is_published_flagged_with_no_model_probability():
    rows, counts = lr.build_live_props(_result(), {NK: BANKED}, {(NK, "pts"): (15.5,)},
                                       pulled={(NK, "pts"): (19.5,)})
    (live,) = _rows_at(rows, "player_points", 15.5)
    (gone,) = _rows_at(rows, "player_points", 19.5)
    assert live["liveModelProbOver"] == 0.7 and "quotePulled" not in live and "liveDisplayProbOver" not in live
    assert gone["quotePulled"] is True and gone["liveModelProbOver"] is None
    assert gone["liveDisplayProbOver"] == 0.7 and gone["unpricedReason"] == "quote_pulled"
    assert (gone["liveProjection"], gone["actualSoFar"]) == (18.5, 12.0)
    assert (counts["priced"], counts["pulled_rows"], counts["rows"]) == (1, 1, 2)


def test_a_line_still_posted_is_never_marked_pulled():
    rows, counts = lr.build_live_props(_result(), {NK: BANKED}, {(NK, "pts"): (15.5,)},
                                       pulled={(NK, "pts"): (15.5,)})
    assert len(rows) == 1 and "quotePulled" not in rows[0] and counts["pulled_rows"] == 0


def test_a_pulled_double_double_is_flagged_too():
    rows, counts = lr.build_live_props(_result(), {NK: BANKED}, {}, pulled={(NK, "dd"): (1.5,)})
    (dd,) = _rows_at(rows, "player_double_double", 1.5)
    assert dd["quotePulled"] is True and dd["liveModelProbOver"] is None and counts["pulled_rows"] == 1


def test_pulled_lines_are_what_was_remembered_minus_what_this_pull_covers():
    remembered = lr._merge_posted_lines({(NK, "pts"): (20.5,), (NK, "reb"): (3.5,), (NK, "dd"): (1.5,)},
                                        {(NK, "pts"): (15.5,)})
    assert remembered == {(NK, "pts"): (15.5, 20.5), (NK, "reb"): (3.5,), (NK, "dd"): (1.5,)}
    gone = lr.pulled_lines(remembered, lr.with_neighbour_lines({(NK, "pts"): (15.5,)}))
    # 20.5 +-1 minus the 12.5..18.5 the live 15.5 covers; a market gone entirely keeps all of its +-1;
    # a yes/no line has no neighbours.
    assert gone == {(NK, "pts"): (19.5, 20.5, 21.5), (NK, "reb"): (2.5, 3.5, 4.5), (NK, "dd"): (1.5,)}


def test_the_memory_is_bounded_around_this_pull():
    many = {(NK, "pts"): tuple(0.5 + i for i in range(41))}
    kept = lr._merge_posted_lines(many, {(NK, "pts"): (20.5,)})[(NK, "pts")]
    assert len(kept) == lr.MAX_REMEMBERED_LINES_PER_KEY and 20.5 in kept
    assert min(kept) >= 8.5 and max(kept) <= 32.5


def test_the_payload_round_trips_and_skips_what_it_cannot_read():
    lines = {(NK, "pts"): (20.5, 15.5), (NK, "dd"): (1.5,)}
    payload = lr._posted_lines_payload(lines)
    assert lr._posted_lines_from_payload(payload) == {(NK, "pts"): (15.5, 20.5), (NK, "dd"): (1.5,)}
    assert lr._posted_lines_from_payload([["x", "pts"], ["y", "pts", ["nan", "bad"]], "junk"]) == {}
    assert lr._posted_lines_from_payload(None) == {}


@pytest.mark.parametrize("raw, on", [(None, True), ("", True), ("1", True), ("on", True),
                                     ("0", False), ("off", False), ("false", False), ("NO", False)])
def test_the_switch_is_on_unless_turned_off(raw, on):
    env = {} if raw is None else {lr.PULLED_LINES_ENV: raw}
    assert lr.pulled_lines_enabled(env) is on


# ------------------------------------------------------------------------------------------------ two real ticks

@pytest.fixture
def ticks(tmp_path, monkeypatch):
    """One live game, a stub engine returning `_result()`, and props pulls the test sets per tick."""
    kw = synthetic_game_kwargs(np.random.default_rng(7), league="nba", entrypoint="simulate_pbp_game_boxscore")
    kw.pop("rng", None)
    lr.persist_engine_inputs(DATE, "GSW", "NYK", {**{k: None for k in lr._INPUT_KEYS}, **kw}, root=tmp_path)
    state = {"minute": 0, "lines": {}, "refuse": False}
    real_resume = lr.resume_from_summary

    def resume(summary, *, date="", as_of="", league=lr.LEAGUE):
        state["minute"] += 1
        return real_resume(summary, date=date, league=league,
                           as_of=(T0 + timedelta(minutes=state["minute"])).isoformat())

    def resim(*_a, **_k):
        return lr.NbaResimRefusal("engine_failed", "stub") if state["refuse"] else _result()

    g = Game("nba", state="in")
    g.shot(1, "11:00", "home", "h1").shot(1, "10:30", "away", "a1", pts=3)
    summary = g.summary()
    monkeypatch.setattr(lr, "resume_from_summary", resume)
    monkeypatch.setattr(lr, "resim_live_game", resim)
    monkeypatch.setattr(lr, "lines_from_props_csv", lambda *_a, **_k: dict(state["lines"]))
    monkeypatch.setattr(lr, "actuals_from_summary", lambda _s: {NK: dict(BANKED)})
    scoreboard = {"events": [{"id": "A", "competitions": [{"status": {"type": {"state": "in"}}, "competitors": []}]}]}

    def tick(lines, previous=None, **kwargs):
        state["lines"] = lines
        return lr.build_live_lens_snapshot(DATE, budget_seconds=250, fetch_scoreboard=lambda *_a: scoreboard,
                                           fetch_summary=lambda *_a: summary, inputs_root=tmp_path,
                                           clock=lambda: 0.0, previous=previous,
                                           now=T0 + timedelta(minutes=state["minute"] + 1), **kwargs)

    state["tick"] = tick
    return state


def _game(snap):
    (game,) = snap["games"]
    return game


TICK1 = {(NK, "pts"): (15.5,), (NK, "reb"): (3.5,)}
TICK2 = {(NK, "pts"): (16.5,)}            # the rebounds market came down; points moved one step


def test_a_market_pulled_between_ticks_keeps_flagged_rows(ticks):
    snap1 = ticks["tick"](TICK1)
    assert lr._posted_lines_from_payload(_game(snap1)["postedLines"]) == {(NK, "pts"): (15.5,), (NK, "reb"): (3.5,)}
    assert not [r for r in _game(snap1)["liveProps"] if r.get("quotePulled")]

    game = _game(ticks["tick"](TICK2, previous=snap1))
    rebounds = [r for r in game["liveProps"] if r["prop"] == "player_rebounds"]
    assert sorted(r["line"] for r in rebounds) == [2.5, 3.5, 4.5]
    assert all(r["quotePulled"] is True and r["liveModelProbOver"] is None for r in rebounds)
    # The old points line is inside the +-3 window of the live 16.5: a live quote neighbour, NOT pulled.
    (old_points,) = _rows_at(game["liveProps"], "player_points", 15.5)
    assert "quotePulled" not in old_points and old_points["liveModelProbOver"] is not None
    cov = game["livePropsCoverage"]
    assert (cov["pulled_rows"], cov["keys_pulled"], cov["remember_lines"]) == (3, 1, True)
    assert lr._posted_lines_from_payload(game["postedLines"]) == {(NK, "pts"): (15.5, 16.5), (NK, "reb"): (3.5,)}


def test_off_is_not_on(ticks, monkeypatch):
    snap1 = ticks["tick"](TICK1, remember_lines=False)
    game = _game(ticks["tick"](TICK2, previous=snap1, remember_lines=False))
    assert not [r for r in game["liveProps"] if r["prop"] == "player_rebounds"]
    assert "postedLines" not in game and game["livePropsCoverage"]["pulled_rows"] == 0
    # The env switch reaches the same branch, and the default (absent) is on.
    monkeypatch.setenv(lr.PULLED_LINES_ENV, "off")
    game = _game(ticks["tick"](TICK2, previous=ticks["tick"](TICK1)))
    assert not [r for r in game["liveProps"] if r["prop"] == "player_rebounds"]
    monkeypatch.delenv(lr.PULLED_LINES_ENV)
    game = _game(ticks["tick"](TICK2, previous=ticks["tick"](TICK1)))
    assert [r for r in game["liveProps"] if r["prop"] == "player_rebounds"]


def test_a_refused_tick_does_not_forget_the_lines(ticks):
    snap1 = ticks["tick"](TICK1)
    ticks["refuse"] = True
    snap2 = ticks["tick"]({}, previous=snap1)
    assert _game(snap2)["gameLens"][0]["liveResimRefusal"] == "engine_failed"
    assert lr._posted_lines_from_payload(_game(snap2)["postedLines"]) == {(NK, "pts"): (15.5,), (NK, "reb"): (3.5,)}
    ticks["refuse"] = False
    game = _game(ticks["tick"]({}, previous=snap2))
    assert {r["prop"] for r in game["liveProps"] if r.get("quotePulled")} == {"player_points", "player_rebounds"}


def test_another_dates_snapshot_feeds_nothing(ticks):
    snap1 = ticks["tick"](TICK1)
    snap1["date"] = "2026-01-14"
    game = _game(ticks["tick"](TICK2, previous=snap1))
    assert not [r for r in game["liveProps"] if r.get("quotePulled")]


# ------------------------------------------------------------------------------------------------ join and board

def _snapshot():
    rows, _ = lr.build_live_props(_result(), {NK: BANKED}, {(NK, "pts"): (15.5,)}, pulled={(NK, "pts"): (19.5,)})
    return {"games": [{"status": {"detailedState": "In Progress"}, "liveProps": rows}]}


def _board_row(line, side="over"):
    # A real pulled row still carries its PREGAME projection; the test proves the join adds nothing priceable to it.
    return {"sport": "nba", "kind": "prop", "player_name": "De'Aaron Fox", "market": "player_points", "line": line,
            "side": side, "game": {"state": "live"},
            "projection": {"model_prob_over": 0.62, "market_fair_prob_over": 0.5, "basis": "pregame_sim"}}


def test_the_join_shows_a_pulled_row_and_prices_nothing():
    live, gone = _board_row(15.5), _board_row(19.5)
    cov = J.attach_live_projections([live, gone], J.build_live_prop_index(_snapshot()))
    assert (cov["rows_live_projected"], cov["rows_live_display_only"], cov["rows_live_display_only_pulled"]) == (1, 1, 1)
    assert live["projection"]["live_aware"] is True
    p = gone["projection"]
    assert (p["live_projected"], p["actual_so_far"], p["live_display_prob_over"]) == (18.5, 12.0, 0.7)
    assert p["live_display_only"] is True and p["live_quote_pulled"] is True
    for forbidden in ("live_aware", "live_prob_over", "live_model_prob_over", "edge_vs_market_pct"):
        assert forbidden not in p, forbidden
    # The pregame fields are left exactly as the build had them.
    assert (p["model_prob_over"], p["basis"]) == (0.62, "pregame_sim")


def test_nothing_downstream_can_price_a_pulled_row_live():
    gone = _board_row(19.5)
    before = _board_row(19.5)
    J.attach_live_projections([gone], J.build_live_prop_index(_snapshot()))
    # The live-edge policy refuses it exactly as it refused the row with no live number at all.
    assert live_edge_unavailable_reason(gone) is not None
    assert live_edge_unavailable_reason(gone) == live_edge_unavailable_reason(before)
    assert _model_value_ev(gone, "over", -110, "book_margin_model") == _model_value_ev(before, "over", -110,
                                                                                       "book_margin_model")
    priced_after = attach_modelled_fair_edges([gone]).get("modelled_edge_rows_priced")
    assert priced_after == attach_modelled_fair_edges([before]).get("modelled_edge_rows_priced")


def test_a_dropped_flag_still_prices_nothing():
    snapshot = _snapshot()
    for row in snapshot["games"][0]["liveProps"]:
        row.pop("quotePulled", None)
    gone = _board_row(19.5)
    cov = J.attach_live_projections([gone], J.build_live_prop_index(snapshot))
    assert gone["projection"].get("edge_vs_market_pct") is None
    assert gone["projection"].get("live_prob_over") is None
    assert cov["edge_withheld_by_reason"].get("no_live_probability") == 1


def test_board_columns_show_the_count_actual_and_the_rows_own_side():
    over, under = _board_row(19.5), _board_row(19.5, side="under")
    J.attach_live_projections([over, under], J.build_live_prop_index(_snapshot()))
    cols_over, cols_under = _live_projection_columns(over), _live_projection_columns(under)
    assert (cols_over["live_projection"], cols_over["actual"]) == (18.5, 12.0)
    assert cols_over["live_model_probability"] == 0.7 and abs(cols_under["live_model_probability"] - 0.3) < 1e-9
    assert "live_aware" not in cols_over


def test_web_read_time_refresh_finds_the_pulled_row():
    hit = J.live_prop_hit(J.build_live_prop_index(_snapshot()), "De'Aaron Fox", "player_points", 19.5)
    assert hit is not None and hit["quote_pulled"] is True and hit["live_projection"] == 18.5
    assert hit["live_prob_over"] is None
