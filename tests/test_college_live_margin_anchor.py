"""Live college margins are market-anchored (user 2026-11-03 "Anchor them", NCAAB and WNCAAB).

The live full-game margin is shifted by the game's pregame gap (closing consensus home margin minus the pregame sim's
home margin), so at the tip the served margin IS the market's and live edges come only from the game state. Measured
before: ECU -26.5 read -27 pp off the sim's compressed margin on the first live women's game."""

from __future__ import annotations

import pytest

from syndicate.features.ncaab import live_resim as lr


@pytest.fixture(autouse=True)
def _lane_age_gate_off(monkeypatch):
    """The `#762` lane-age gate (default on) judges a lane against the wall clock, and these lanes carry fixed past
    times. This file pins the margin anchor, not lane age (loaned to lane `live-gameline-lane-age-gate`, 2026-11-07)."""
    monkeypatch.setenv("SYNDICATE_LIVE_GAMELINE_LANE_AGE_GATE", "off")


AWAY, HOME = "Army Black Knights", "Duke Blue Devils"
COMMENCE = "2026-11-04T00:00:00Z"


def _quote(book, line, seen, *, selection="home", market="spreads", segment="full", event="ev1", home=HOME, away=AWAY):
    return {"event_id": event, "bookmaker": book, "market": market, "segment": segment, "selection": selection,
            "line": line, "commence_time": COMMENCE, "snapshot_ts": seen, "home_team": home, "away_team": away}


def _result(margins):
    hist = {}
    for m in margins:
        hist[str(m)] = hist.get(str(m), 0) + 1
    n = len(margins)
    return {"sims_run": n, "home_win_prob": sum(1 for m in margins if m > 0) / n, "total_mean": 140.0,
            "home_margin_mean": sum(margins) / n, "total_dist": {"140": n}, "margin_dist": hist, "segments": {}}


def test_switch_is_on_unless_turned_off():
    assert lr.margin_anchor_enabled({}) is True
    assert lr.margin_anchor_enabled({"SYNDICATE_COLLEGE_LIVE_MARGIN_ANCHOR": "0"}) is False
    assert lr.margin_anchor_enabled({"SYNDICATE_COLLEGE_LIVE_MARGIN_ANCHOR": "on"}) is True


KEY = (lr._join_key("ncaab", HOME), lr._join_key("ncaab", AWAY))


def _closing(rows, tip=None):
    quotes = lr.home_spread_quotes("ncaab", "2026-11-03", rows=rows)
    return {k: lr.closing_home_margin(v, tip=lr._utc(tip)) for k, v in quotes.items()}


def test_closing_margin_is_each_books_last_pregame_home_line_then_the_median():
    rows = [
        _quote("a", -5.5, "2026-11-03T22:00:00Z"),
        _quote("a", -6.5, "2026-11-03T23:30:00Z"),            # a's close
        _quote("a", -12.5, "2026-11-04T00:30:00Z"),           # in play: never the close
        _quote("b", -7.5, "2026-11-03T23:50:00Z"),            # b's close
        _quote("b", 7.5, "2026-11-03T23:50:00Z", selection="away"),
        _quote("c", 141.5, "2026-11-03T23:50:00Z", market="totals", selection="over"),
        _quote("d", -3.5, "2026-11-03T23:50:00Z", segment="h1"),
    ]
    assert _closing(rows) == {KEY: (7.0, 2)}


def test_close_compares_times_not_text_and_cuts_at_the_actual_tip():
    """The women's shard writes commence as `2026-11-03 16:00:00+00:00` and snapshot_ts with a `T`: as TEXT every
    same-day quote sorts after its own commence. And a line first posted at the listed time is still pregame when
    the game tips minutes later (ECU 11-03)."""
    spaced = [{**_quote("a", -24.5, "2026-11-03T15:58:00+00:00"), "commence_time": "2026-11-03 16:00:00+00:00"}]
    assert _closing(spaced) == {KEY: (24.5, 1)}
    late = [{**_quote("a", -24.5, "2026-11-03T16:00:02+00:00"), "commence_time": "2026-11-03 16:00:00+00:00"}]
    assert _closing(late) == {KEY: None}, "after the listed time and no tip known: not a close"
    assert _closing(late, tip="2026-11-03T16:04:43Z") == {KEY: (24.5, 1)}
    assert _closing(late, tip="2026-11-03T16:00:01Z") == {KEY: None}


def _quotes(margin, books=3, seen="2026-11-03T23:00:00Z"):
    return [(lr._utc(seen), f"b{i}", -float(margin), lr._utc(COMMENCE)) for i in range(books)]


def test_anchor_orients_the_neutral_site_and_refuses_by_name():
    facts = lr.ResumeFacts("401", "10", "20", 30, 28, 2, 600.0, "home", 100, "t")
    names = {"home": HOME, "away": AWAY}
    key, rev = KEY, (KEY[1], KEY[0])
    a = lr.margin_anchor_for(facts, names, league="ncaab", market={key: _quotes(7.0)}, sims={"401": (4.0, "10")})
    assert (a.market_home_margin, a.sim_home_margin, a.offset, a.books) == (7.0, 4.0, 3.0, 3)
    # Odds feed and slate both oriented the other way: both flip onto the live home side.
    b = lr.margin_anchor_for(facts, names, league="ncaab", market={rev: _quotes(-7.0)}, sims={"401": (-4.0, "20")})
    assert (b.market_home_margin, b.sim_home_margin) == (7.0, 4.0)
    for market, sims, detail in (({key: _quotes(7.0)}, {}, "no pregame sim"), ({}, {"401": (4.0, "10")}, "no closing"),
                                 ({key: _quotes(7.0)}, {"401": (4.0, "99")}, "neither side")):
        r = lr.margin_anchor_for(facts, names, league="ncaab", market=market, sims=sims)
        assert isinstance(r, lr.NcaabResimRefusal) and r.reason == "no_margin_anchor" and detail in r.detail


def test_anchor_shifts_the_margin_and_rederives_the_win_prob():
    margins = [m for m in range(5, 30) for _ in range(8)]   # 200 draws, mean 17.0
    raw = _result(margins)
    out = lr.anchor_result(raw, lr.MarginAnchor(market_home_margin=26.5, sim_home_margin=17.2, books=4))  # +9.3
    assert all(isinstance(int(k), int) and isinstance(v, int) for k, v in out["margin_dist"].items())
    assert sum(out["margin_dist"].values()) == 200
    assert out["home_margin_mean"] == pytest.approx(17.0 + 9.3, abs=1 / 200)
    assert out["home_win_prob"] == 1.0 and out["raw_home_win_prob"] == raw["home_win_prob"]
    assert out["raw_home_margin_mean"] == pytest.approx(17.0) and out["margin_anchor"]["offset"] == 9.3
    # A shift onto 0 counts half each way (a game cannot end tied).
    flat = lr.anchor_result(_result([1] * 100 + [-1] * 100), lr.MarginAnchor(-1.0, 0.0, 1))
    assert flat["margin_dist"] == {"-2": 100, "0": 100} and flat["home_win_prob"] == pytest.approx(0.25)


def test_the_shift_scales_with_the_regulation_still_to_play():
    def facts(period, clock):
        return lr.ResumeFacts("1", "10", "20", 0, 0, period, clock, None, 0, "t")

    frac = lr.remaining_regulation_fraction
    assert frac(facts(1, 1200.0), "ncaab") == 1.0 and frac(facts(2, 1200.0), "ncaab") == 0.5
    assert frac(facts(1, 0.0), "ncaab") == 0.5, "a half-time break: the second half is still to play"
    assert frac(facts(3, 300.0), "ncaab") == 0.0, "overtime: no pregame gap left to apply"
    assert frac(facts(3, 600.0), "wncaab") == 0.5 and frac(facts(4, 60.0), "wncaab") == pytest.approx(60 / 2400)
    flat = _result([5] * 200)
    half = lr.anchor_result(flat, lr.MarginAnchor(26.5, 16.5, 3), remaining_fraction=0.5)
    assert half["home_margin_mean"] == pytest.approx(10.0) and half["margin_anchor"]["appliedOffset"] == 5.0


def test_mid_game_the_anchor_moves_only_the_remaining_game():
    """The 2026-11-03 16:45Z ECU board: Q2 2:11 left (55.5% of regulation to play), raw margin 17.5, pregame gap
    +10.37 (market 24.5, sim 14.13), live line 21.5. Unscaled, the anchor itself was a +20 pp spread edge."""
    ecu = lr.ResumeFacts("401913822", "10", "20", 23, 32, 2, 131.0, "home", 300, "t")
    fraction = lr.remaining_regulation_fraction(ecu, "wncaab")
    assert fraction == pytest.approx(1331 / 2400)
    margins = [m for m in range(5, 31) for _ in range(8)][:200]   # mean ~17.4
    raw = _result(margins)
    anchor = lr.MarginAnchor(24.5, 14.13, 1)
    scaled = lr.anchor_result(raw, anchor, remaining_fraction=fraction)
    full = lr.anchor_result(raw, anchor)
    assert scaled["home_margin_mean"] == pytest.approx(raw["home_margin_mean"] + 10.37 * fraction, abs=0.01)
    assert abs(scaled["home_margin_mean"] - 21.5) < abs(full["home_margin_mean"] - 21.5)


def _snapshot(monkeypatch, *, anchor_on, market, sims, previous=None, budget_seconds=240.0):
    events = [{"event_id": "401", "status_state": "in"}, {"event_id": "402", "status_state": "in"}]
    monkeypatch.setenv("SYNDICATE_COLLEGE_LIVE_MARGIN_ANCHOR", "1" if anchor_on else "0")
    monkeypatch.setattr("syndicate.features.shared.request_path_guard.refuse_if_compute_in_request_path", lambda *_: None)
    monkeypatch.setattr("syndicate.features.shared.basketball_pbp.scoreboard_events", lambda sb: events)
    monkeypatch.setattr(lr, "load_player_priors", lambda *a, **k: lr.NcaabResimRefusal("no_player_priors"))
    monkeypatch.setattr(lr, "odds_team_names", lambda *a, **k: {})
    monkeypatch.setattr(lr, "_espn_names", lambda s: {"home": HOME, "away": AWAY, "home_id": "10", "away_id": "20"})
    monkeypatch.setattr(lr, "resume_from_summary",
                        lambda s, **k: (None, None, lr.ResumeFacts(s["id"], "10", "20", 3, 0, 1, 531.0, "home", 5, "t")))
    monkeypatch.setattr(lr, "build_engine_inputs", lambda *a, **k: {"home_players": None, "away_players": None})
    monkeypatch.setattr("syndicate.features.nba.live_resim.map_state_names", lambda gs, h, a: (gs, {}))
    monkeypatch.setattr(lr, "_anchor_sources", lambda league, d, clock=None: (market, sims))
    simmed = []
    margins = [m for m in range(5, 30) for _ in range(8)]
    monkeypatch.setattr(lr, "resim_live_game", lambda inputs, gs, **kw: simmed.append(1) or _result(margins))
    lr._ROTATION_CURSOR.clear()
    lr._ANCHOR_CACHE.clear()
    snap = lr.build_live_lens_snapshot("2026-11-03", previous=previous or {}, dirs=[], budget_seconds=budget_seconds,
                                       fetch_scoreboard=lambda *a: {}, fetch_summary=lambda league, eid: {"id": eid})
    return snap, simmed


def test_snapshot_anchors_priced_games_and_refuses_the_rest_before_simming(monkeypatch):
    snap, simmed = _snapshot(monkeypatch, anchor_on=True, market={KEY: _quotes(26.5, books=5)}, sims={"401": (17.2, "10")})
    assert snap["marginAnchor"] == "on" and len(simmed) == 1, "the unanchored game is refused BEFORE it is simmed"
    lanes = {g["event_id"]: g["gameLens"][0] for g in snap["games"]}
    assert lanes["402"]["liveResimRefusal"] == "no_margin_anchor" and "modelHomeWinProb" not in lanes["402"]
    priced = lanes["401"]
    anchor = priced["projection"]["marginAnchor"]
    # 1st half, 531 s left: (1200 + 531) / 2400 of regulation remains, so 72.1% of the +9.3 gap is applied.
    assert anchor["offset"] == 9.3 and anchor["remainingFraction"] == pytest.approx(1731 / 2400, abs=1e-4)
    assert priced["projection"]["homeMargin"] == pytest.approx(17.0 + 9.3 * 1731 / 2400, abs=0.01)
    assert priced["projection"]["rawHomeMargin"] == pytest.approx(17.0) and priced["rawModelHomeWinProb"] == 1.0


def test_off_serves_the_raw_sim(monkeypatch):
    snap, simmed = _snapshot(monkeypatch, anchor_on=False, market={}, sims={})
    assert snap["marginAnchor"] == "off" and len(simmed) == 2
    lane = snap["games"][0]["gameLens"][0]
    assert lane["projection"]["homeMargin"] == pytest.approx(17.0) and "marginAnchor" not in lane["projection"]


def test_a_raw_lane_from_before_the_anchor_is_not_carried_forward(monkeypatch):
    """A zero budget carries every previous lane forward -- except, with the anchor on, a priced lane without one."""
    def lane(anchored):
        projection = {"marginAnchor": {"offset": 1.0}} if anchored else {}
        return {"gameLens": [{"source": "live_resim", "modelHomeWinProb": 0.9, "projection": projection}]}

    previous = {"401": {"event_id": "401", **lane(True)}, "402": {"event_id": "402", **lane(False)}}
    snap, simmed = _snapshot(monkeypatch, anchor_on=True, market={}, sims={}, previous=previous, budget_seconds=0.0)
    assert not simmed and snap["counts"]["carried_forward"] == 1 and snap["counts"]["not_reached"] == 1
    assert [g["event_id"] for g in snap["games"] if g.get("carriedForward")] == ["401"]
    off, _ = _snapshot(monkeypatch, anchor_on=False, market={}, sims={}, previous=previous, budget_seconds=0.0)
    assert off["counts"]["carried_forward"] == 2


def test_the_board_prices_the_anchored_spread_near_the_market_and_the_raw_one_far_from_it():
    """off != on end to end: the ECU case. Sim margin ~17, market -26.5. Raw: a large negative live edge on the home
    spread. Anchored by the pregame gap: the live number sits on the market at the same state."""
    from syndicate.features.shared.live_gameline_join import (attach_live_gamelines, build_live_gameline_index,
                                                               lens_sources_for_sport)

    margins = [m for m in range(5, 30) for _ in range(8)]  # mean 17.0
    facts = lr.ResumeFacts("401", "10", "20", 3, 0, 1, 531.0, "home", 5, "2026-11-03T16:05:38+00:00")

    def edge(result):
        snap = {"games": [lr._lane_row("401", {"home": HOME, "away": AWAY, "source": "odds"}, facts, result)]}
        index = build_live_gameline_index(snap, sources=lens_sources_for_sport("wncaab"), sport="wncaab")
        # The grid's spread line is the AWAY-frame line (home covers when margin > L): ECU -26.5 is L = 26.5.
        row = {"kind": "game", "market": "spreads", "segment": "full", "away_team": AWAY, "home_team": HOME,
               "line": 26.5, "age_seconds": 30.0, "updated_at": "2026-11-03 16:05:40+00:00",
               "game": {"state": "live"}, "sides": ["home", "away"],
               "projection": {"model_prob_over": 0.5, "market_fair_prob_over": 0.5, "basis": "college_pregame_sim"}}
        attach_live_gamelines([row], index)
        return (row.get("live_gameline") or {}).get("edge_pp")

    raw_edge = edge(_result(margins))
    anchored_edge = edge(lr.anchor_result(_result(margins), lr.MarginAnchor(26.5, 17.0, 5)))
    assert raw_edge is not None and raw_edge < -25, raw_edge
    assert anchored_edge is not None and abs(anchored_edge) < 6, anchored_edge
