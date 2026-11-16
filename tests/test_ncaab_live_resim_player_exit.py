"""NCAAB / WNCAAB live re-sim refuses a game a starter has left (lane live-player-exit-gate, user 2026-11-16).

Two reads, because the tick ROTATES: a game re-simmed this tick is read from the summary the loop already fetched;
a game it carries (or never reaches) is read once on the exit pool, and a carried lane a starter has left since is
replaced by the refusal. A foul-out the engine state carries is MODELLED and priced (NBA's rule). Harness: the
rotation test's fakes (`test_ncaab_live_resim.test_rotation_and_carry_forward`) with a synthetic ESPN summary
(`tests/basketball_pbp_fixtures.Game`) feeding the real detector.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from syndicate.features.ncaab import live_resim as lr
from syndicate.features.shared import live_player_exit_hold as H
from syndicate.features.shared import live_player_status as lps
from tests.basketball_pbp_fixtures import Game

AWAY, HOME = "Army Black Knights", "Duke Blue Devils"


@pytest.fixture(autouse=True)
def _lane_age_gate_off(monkeypatch):
    monkeypatch.setenv("SYNDICATE_LIVE_GAMELINE_LANE_AGE_GATE", "off")
    monkeypatch.setenv("SYNDICATE_COLLEGE_LIVE_MARGIN_ANCHOR", "0")


def _summary(ejected: str | None = None, fouled_out: str | None = None):
    g = Game("ncaab", state="in")
    g.shot(1, "15:00", "home", "h1").shot(1, "14:30", "away", "a1", pts=3)
    if fouled_out:
        for i in range(5):
            g.foul(1, f"{13 - i}:00", "home", fouled_out)
    g.end_period(1)
    g.shot(2, "19:40", "home", "h2")
    s = g.summary(pf={fouled_out: 5} if fouled_out else None)
    for team in s["boxscore"]["players"]:
        for cat in team["statistics"]:
            cat["labels"] = cat["names"]  # a real ESPN box carries both; the detector reads PF by label
            for entry in cat["athletes"]:
                if ejected and entry["athlete"]["displayName"] == ejected:
                    entry["ejected"] = True
                    entry["starter"] = True
    return s


RESULT = {"sims_run": 100, "home_win_prob": 0.6, "total_mean": 140.0, "home_margin_mean": 3.0,
          "total_dist": {}, "margin_dist": {}, "segments": {}}


@pytest.fixture
def tick(monkeypatch):
    """-> run(summaries_by_event, *, previous=None, gs=None, n=1, budget=1000) -> (snapshot, resimmed ids, fetched ids)"""
    monkeypatch.setattr("syndicate.features.shared.request_path_guard.refuse_if_compute_in_request_path", lambda *_: None)
    monkeypatch.setattr(lr, "load_player_priors", lambda *a, **k: lr.NcaabResimRefusal("no_player_priors"))
    monkeypatch.setattr(lr, "odds_team_names", lambda *a, **k: {})
    monkeypatch.setattr(lr, "build_engine_inputs", lambda *a, **k: {"home_players": None, "away_players": None})

    def run(summaries, *, previous=None, gs=None, n=1, budget=1000.0):
        events = [{"event_id": str(i), "status_state": "in"} for i in range(n)]
        monkeypatch.setattr("syndicate.features.shared.basketball_pbp.scoreboard_events", lambda sb: events)
        state = gs if gs is not None else SimpleNamespace(home_player_fouls={}, away_player_fouls={})
        monkeypatch.setattr(lr, "resume_from_summary", lambda s, **k: (
            None, state, lr.ResumeFacts(str(s.get("_eid")), "10", "20", 40, 38, 2, 600.0, "home", 300, "t")))
        monkeypatch.setattr("syndicate.features.nba.live_resim.map_state_names", lambda g, h, a: (g, {}))
        now = {"t": 0.0}
        resimmed: list[str] = []
        fetched: list[str] = []

        def resim(inputs, g, **kw):
            now["t"] += 10.0
            resimmed.append("x")
            return dict(RESULT)

        def fetch(league, eid):
            fetched.append(eid)
            return {**summaries[eid], "_eid": eid}

        monkeypatch.setattr(lr, "resim_live_game", resim)
        lr._ROTATION_CURSOR.clear() if previous is None else None
        snap = lr.build_live_lens_snapshot("2026-01-10", previous=previous or {}, fetch_scoreboard=lambda *a: {},
                                           fetch_summary=fetch, budget_seconds=budget, clock=lambda: now["t"],
                                           workers=0, d1_ids=frozenset())
        return snap, resimmed, fetched
    return run


def _lane(game):
    return game["gameLens"][0]


def test_a_starter_ejected_refuses_the_game_before_any_sim(tick):
    snap, resimmed, _ = tick({"0": _summary(ejected="H1")})
    game = snap["games"][0]
    assert _lane(game)["liveResimRefusal"] == "key_player_out" and "H1:ejection" in _lane(game)["liveResimRefusalDetail"]
    assert resimmed == []  # no draws spent on a game it will not price
    assert [(p["player"], p["reason"], p["key"]) for p in game["playersOut"]] == [("H1", "ejection", True)]
    assert snap["refusalsByReason"] == {"key_player_out": 1} and snap["counts"]["refused"] == 1
    assert snap["playerExits"]["read"] == 1 and snap["playerExits"]["refused_games"] == 1


def test_off_ne_on(tick, monkeypatch):
    on, _, _ = tick({"0": _summary(ejected="H1")})
    monkeypatch.setenv(lps.ENV_SWITCH, "off")
    off, resimmed, _ = tick({"0": _summary(ejected="H1")})
    assert _lane(on["games"][0])["liveResimRefusal"] == "key_player_out"
    assert _lane(off["games"][0])["source"] == lr.LIVE_RESIM_LENS_SOURCE and resimmed == ["x"]
    assert "playersOut" not in off["games"][0] and off["playerExits"]["enabled"] is False


def test_a_clean_game_is_priced_and_publishes_an_empty_exit_list(tick):
    snap, resimmed, fetched = tick({"0": _summary()})
    game = snap["games"][0]
    assert _lane(game)["source"] == lr.LIVE_RESIM_LENS_SOURCE and resimmed == ["x"]
    assert game["playersOut"] == [] and snap["refusalsByReason"] == {}
    assert fetched == ["0"]  # read from the summary the loop fetched: no second GET


def test_a_foul_out_the_engine_state_carries_is_priced(tick):
    gs = SimpleNamespace(home_player_fouls={"H1": 5}, away_player_fouls={})
    snap, resimmed, _ = tick({"0": _summary(fouled_out="h1")}, gs=gs)
    game = snap["games"][0]
    assert _lane(game)["source"] == lr.LIVE_RESIM_LENS_SOURCE and resimmed == ["x"]
    assert [(p["player"], p["reason"], p["key"], p["modelled"]) for p in game["playersOut"]] == [
        ("H1", "foul_out", True, True)]
    assert H.ExitHold(read_fn=lambda s: {"games": [{**game, "home_name": HOME, "away_name": AWAY}]}, env={}).check(
        "ncaab", HOME, AWAY)["verdict"] == "pass"


def test_a_foul_out_the_engine_state_does_not_carry_is_refused(tick):
    snap, resimmed, _ = tick({"0": _summary(fouled_out="h1")})
    game = snap["games"][0]
    assert _lane(game)["liveResimRefusal"] == "key_player_out" and resimmed == []
    assert [(p["player"], p["modelled"]) for p in game["playersOut"]] == [("H1", False)]


def test_a_CARRIED_lane_a_starter_has_since_left_is_refused_within_one_tick(tick):
    """Tick 1 prices 0..2 and never reaches 3; tick 2 starts at 3, re-sims 3, 0, 1 and would carry 2 priced --
    but game 2's starter was ejected in between, and the exit pool reads it."""
    clean = {str(i): _summary() for i in range(4)}
    first, _, fetched1 = tick(clean, n=4, budget=25)
    assert first["counts"]["resimmed"] == 3 and first["counts"]["not_reached"] == 1
    assert fetched1 == ["0", "1", "2", "3"]  # 3 was never reached, so the exit pool read it
    prev = {g["event_id"]: g for g in first["games"]}
    second, _, fetched2 = tick({**clean, "2": _summary(ejected="H1")}, previous=prev, n=4, budget=25)
    by = {g["event_id"]: g for g in second["games"]}
    assert "2" in fetched2
    assert _lane(by["2"])["liveResimRefusal"] == "key_player_out" and not by["2"].get("carriedForward")
    assert second["counts"]["carried_forward"] == 0 and second["playerExits"]["refused_carried"] == 1
    assert all(_lane(by[i])["source"] == lr.LIVE_RESIM_LENS_SOURCE for i in ("0", "1", "3"))


def test_a_carried_lane_keeps_a_foul_out_it_already_modelled(tick):
    gs = SimpleNamespace(home_player_fouls={"H1": 5}, away_player_fouls={})
    fouled = {str(i): _summary(fouled_out="h1") for i in range(4)}
    first, _, _ = tick(fouled, n=4, budget=25, gs=gs)
    prev = {g["event_id"]: g for g in first["games"]}
    second, _, _ = tick(fouled, previous=prev, n=4, budget=25, gs=gs)
    carried = [g for g in second["games"] if g.get("carriedForward")]
    assert len(carried) == 1 and _lane(carried[0])["source"] == lr.LIVE_RESIM_LENS_SOURCE
    assert [p["modelled"] for p in carried[0]["playersOut"]] == [True]


def test_the_board_index_drops_the_refused_game_and_the_entry_hold_fails():
    from syndicate.features.shared.live_gameline_join import build_live_gameline_index, lens_sources_for_sport

    def simulate(rng, gs, i=[0]):
        i[0] += 1
        return {}, {}, [40, 40], [40, 30 if i[0] % 20 else 45]

    facts = lr.ResumeFacts("401", "10", "20", 70, 58, 2, 120.0, "home", 400, "2026-11-05T01:00:00+00:00")
    priced = lr._lane_row("401", {"home": HOME, "away": AWAY, "source": "odds"}, facts,
                          lr.resim_live_game({}, None, sims=200, simulate=simulate))
    priced["playersOut"] = []
    out = [{"team": "DUKE", "player": "Cooper Flagg", "reason": "ejection", "key": True}]
    refused = lr._exit_refusal_row("401", {"home": HOME, "away": AWAY, "source": "odds"}, facts,
                                   ["DUKE:Cooper Flagg:ejection"], out)

    def index(game):
        return build_live_gameline_index({"games": [game]}, sources=lens_sources_for_sport("ncaab"), sport="ncaab")

    assert len(index(priced)) == 1 and len(index(refused)) == 0
    for sport in ("ncaab", "wncaab"):
        hold = H.ExitHold(read_fn=lambda s: {"games": [refused]}, env={}).check(sport, HOME, AWAY)
        assert hold["verdict"] == "fail" and hold["players"] == ["DUKE:Cooper Flagg:ejection"]
        assert H.ExitHold(read_fn=lambda s: {"games": [priced]}, env={}).check(sport, AWAY, HOME)["verdict"] == "pass"


def test_college_publishes_to_the_hold():
    assert H.PUBLISHING_SPORTS["ncaab"] == lr.live_lens_snapshot_path("ncaab").name
    assert H.PUBLISHING_SPORTS["wncaab"] == lr.live_lens_snapshot_path("wncaab").name
