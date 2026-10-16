"""P5 (lane wnba-native-live-cutover): the WNBA native live re-sim feeding the WNBA game lens.

Reachability first (switch off -> the linear lens, byte for byte; on -> the native numbers), then the properties a
wrong answer would hide: a stale, undated or refused snapshot never reaches the lens, pushes are excluded from the
cover / over probabilities, and the pregame persist hook writes WNBA inputs without touching the sim."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np

from syndicate.features.nba import live_resim as lr
from syndicate.features.wnba import cards
from syndicate.features.wnba import live_resim as W

ON = {W.LIVE_RESIM_ENV: "1"}


def _iso(seconds_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat()


def _lane(p=0.8, total=168.0):
    return {"source": lr.LIVE_RESIM_LENS_SOURCE, "modelHomeWinProb": p, "simsRun": 200,
            "projection": {"total": total, "homeMargin": 7.0,
                           "marginDist": {"-3": 1, "2": 1, "5": 2, "9": 4},      # vs spread -2.5: -5.5,-0.5,2.5,6.5
                           "totalRunsDist": {"160": 2, "165": 1, "170": 5}}}     # vs total 165.5: under, under, over


def _snapshot(lanes, generated_at=None):
    return {"generatedAt": generated_at if generated_at is not None else _iso(30),
            "games": [{"event_id": "401", "home_code": "LVA", "away_code": "NYL", "gameLens": lanes}]}


GAME = {"event_id": "401", "home_tri": "LVA", "away_tri": "NYL"}


# ---- the lookup -------------------------------------------------------------------------------------------------

def test_lookup_is_off_unless_switched_on():
    assert W.native_lane(GAME, snapshot=_snapshot([_lane()]), env={}) is None
    assert W.native_lane(GAME, snapshot=_snapshot([_lane()]), env=ON)["modelHomeWinProb"] == 0.8


def test_stale_undated_refused_or_other_game_never_reaches_the_lens():
    assert W.native_lane(GAME, snapshot=_snapshot([_lane()], generated_at=_iso(W.MAX_SNAPSHOT_AGE_SECONDS + 60)), env=ON) is None
    assert W.native_lane(GAME, snapshot=_snapshot([_lane()], generated_at=""), env=ON) is None      # unknown != fresh
    refused = {"source": lr.PREGAME_LENS_SOURCE, "liveResimRefusal": "no_pregame_inputs"}
    assert W.native_lane(GAME, snapshot=_snapshot([refused]), env=ON) is None
    assert W.native_lane({**GAME, "event_id": "999"}, snapshot=_snapshot([_lane()]), env=ON) is None


def test_codes_match_only_when_the_card_has_no_event_id():
    no_id = {"home_tri": "LVA", "away_tri": "NYL"}
    assert W.native_lane(no_id, snapshot=_snapshot([_lane()]), env=ON) is not None
    assert W.native_lane({**no_id, "home_tri": "SEA"}, snapshot=_snapshot([_lane()]), env=ON) is None


def test_cover_and_over_exclude_pushes():
    lane = _lane()
    assert W.p_win_given_no_push(lane["projection"]["marginDist"], -2.5) == 6 / 8
    assert W.p_win_given_no_push({"-2": 1, "2": 1, "3": 2}, -2.0) == 2 / 3                 # margin 2 vs -2 is a push
    assert W.p_win_given_no_push(lane["projection"]["totalRunsDist"], 165.5, offset_sign=-1) == 5 / 8
    assert W.p_win_given_no_push({}, 1.0) is None and W.p_win_given_no_push({"1": 1}, None) is None


# ---- the lens (reachability) ------------------------------------------------------------------------------------

def _card():
    return {"event_id": "401", "home_tri": "LVA", "away_tri": "NYL",
            "betting": {"p_home_win": 0.6, "home_ml": -150, "away_ml": 130, "home_spread": -2.5, "total": 165.5,
                        "p_home_cover": 0.55, "p_total_over": 0.5, "pred_total": 166.0},
            "live_state": {"home_pts": 40, "away_pts": 30, "in_progress": True},
            "status": {"period": 2, "clock": "5:00", "in_progress": True}}


def test_switch_off_is_exactly_the_linear_lens(monkeypatch):
    monkeypatch.delenv(W.LIVE_RESIM_ENV, raising=False)
    lane = cards._build_wnba_game_lens(_card())[0]
    assert lane["source"] == "live_projection" and lane["projectionModel"] == "linear" and lane["simsRun"] is None
    assert lane["modelHomeWinProb"] == cards._wnba_live_margin_win_prob(0.6, 10.0, 15.0)


def test_switch_on_serves_the_native_numbers(monkeypatch):
    monkeypatch.setattr(W, "native_lane", lambda game, **_: _lane() if game.get("event_id") == "401" else None)
    off = cards._build_wnba_game_lens(_card())[0]          # native_lane stub ignores the env: proves the wiring
    assert off["projectionModel"] == "native_resim" and off["source"] == "live_projection"
    assert off["modelHomeWinProb"] == 0.8 and off["projection"]["total"] == 168.0 and off["simsRun"] == 200
    m = off["markets"]
    assert m["moneyline"]["p_win"] == 0.8 and m["moneyline"]["selection"] == "home"
    assert m["spread"]["p_win"] == 6 / 8 and m["total"]["p_win"] == 5 / 8


def test_a_lookup_failure_falls_back_to_linear(monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("snapshot unreadable")
    monkeypatch.setattr(W, "native_lane", boom)
    assert cards._build_wnba_game_lens(_card())[0]["projectionModel"] == "linear"


def test_pregame_games_never_consult_the_resim(monkeypatch):
    called = []
    monkeypatch.setattr(W, "native_lane", lambda *a, **k: called.append(1) or _lane())
    card = _card()
    card["live_state"] = {"home_pts": None, "away_pts": None}
    card["status"] = {}
    lane = cards._build_wnba_game_lens(card)[0]
    assert lane["source"] == "pregame" and lane["projectionModel"] is None and called == []


# ---- tick, loop, persist hook ----------------------------------------------------------------------------------

def test_tick_builds_wnba_and_writes_its_own_path(monkeypatch, tmp_path):
    seen = {}

    def build(date_str, **kw):
        seen.update(kw, date=date_str)
        return {"generatedAt": _iso(0), "games": [{"gameLens": [_lane()]}], "refusalsByReason": {}}

    writes = {}
    monkeypatch.setattr(lr, "build_live_lens_snapshot", build)
    import syndicate.features.shared.refresh_state_store as rss
    monkeypatch.setattr(rss, "write_json_file", lambda path, obj: writes.setdefault(str(path), obj))
    status = W.run_tick("2027-05-20")
    assert seen["league"] == "wnba" and seen["date"] == "2027-05-20" and seen["sims"] == 200
    assert status["written"] is True and status["resimmed"] == 1
    assert list(writes) == [str(W.snapshot_path())] and str(W.snapshot_path()).endswith("wnba_live_resim.json")


def test_loop_does_not_start_when_off(monkeypatch):
    monkeypatch.delenv(W.LIVE_RESIM_ENV, raising=False)
    assert W.start_loop() is False


def test_team_names_are_registered_for_the_board_join():
    assert lr.team_name("wnba", "LVA") == "Las Vegas Aces" and lr.team_name("wnba", "TOR") == "Toronto Tempo"


def test_pregame_persist_hook_writes_wnba_inputs_and_changes_nothing(monkeypatch):
    from syndicate.features.shared import basketball_props_smart_sim as bps
    from tests.test_nba_live_resim import _kwargs

    kw = _kwargs(seed=3)
    for side, team in (("home_players", "LVA"), ("away_players", "NYL")):
        kw[side] = kw[side].assign(team=team, asof_date="2026-08-12")
    calls = []

    class _P:
        def stat(self):
            class _S:
                st_size = 1
            return _S()

    monkeypatch.setattr(lr, "persist_engine_inputs", lambda d, h, a, k, **opt: calls.append((d, h, a, opt)) or _P())
    bps._PERSISTED_ENGINE_INPUT_KEYS.clear()

    def run(seed):
        return bps._simulate_pbp_game_boxscore_local(league_code="wnba", rng=np.random.default_rng(seed), **kw)

    a = run(5)
    b = run(5)
    assert calls == [("2026-08-12", "LVA", "NYL", {"league": "wnba"})]          # once per game, WNBA stamp
    assert a[2] == b[2] and a[3] == b[3]
