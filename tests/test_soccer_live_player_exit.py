"""Soccer live player-exit gate (lane live-player-exit-gate, user 2026-11-16).

A red card the sim applied is MODELLED and the match stays priced (the user's 11-16 rule for a modelled exit);
the starting keeper subbed off is NOT modelled and refuses the match. An out player's props are refused only
where the prop sim did not already take him off (``squad`` basis). Fixture: the real ESPN summary of
401879244 (BRE @ BHA, Igor Thiago red card 23').
"""

from __future__ import annotations

import copy
import gzip
import json
import sys
from pathlib import Path

from syndicate.features.shared import live_player_exit_hold as H
from syndicate.features.shared import live_player_status as lps
from syndicate.features.shared import soccer_live_gameline_source as src
from syndicate.features.soccer import live_player_exits as X

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

_FIX = Path(__file__).parent / "fixtures" / "live_player_status" / "soccer_401879244_final_redcard.json.gz"
_SUMMARY = json.loads(gzip.decompress(_FIX.read_bytes()).decode("utf-8"))
HOME, AWAY = "Brighton & Hove Albion", "Brentford"


def _summary(*, red: bool = True, keeper_off: bool = False, live: bool = True) -> dict:
    s = copy.deepcopy(_SUMMARY)
    if live:
        s["header"]["competitions"][0]["status"]["type"]["state"] = "in"
    if not red:
        s["keyEvents"] = [e for e in s["keyEvents"] if e["type"]["text"] != "Red Card"]
    if keeper_off:
        keeper = next(e for e in s["rosters"][0]["roster"]
                      if (e.get("position") or {}).get("abbreviation") == "G" and e.get("starter"))
        keeper["subbedOut"] = True
    return s


def _game(*, away_red_applied: bool = True, basis: str = "on_pitch") -> dict:
    return {"event_id": "401879244", "league": "epl", "home_team": HOME, "away_team": AWAY,
            "projection": {"home_win_probability": 0.62, "draw_probability": 0.22, "away_win_probability": 0.16,
                           "simulations": 400, "home_red_card_applied": False,
                           "away_red_card_applied": away_red_applied},
            "live_player_props": [
                {"player_name": "Igor Thiago", "lineup_basis": basis, "projected_final_shots": 1.0,
                 "shots_over_probabilities": {"0.5": 0.4}, "shots_so_far": 1},
                {"player_name": "Kaoru Mitoma", "lineup_basis": basis, "projected_final_shots": 2.1,
                 "shots_over_probabilities": {"1.5": 0.55}, "shots_so_far": 1}]}


def test_a_red_card_the_sim_applied_is_modelled_and_the_match_stays_priced():
    game = _game()
    tally = X.apply_player_exits(game, _summary())
    assert [(p["player"], p["reason"], p["key"], p["modelled"]) for p in game["playersOut"]] == [
        ("Igor Thiago", "red_card", True, True)]
    assert "liveRefusal" not in game and tally["modelled"] == 1 and tally["refused_games"] == 0
    hold = H.ExitHold(read_fn=lambda s: {"games": [game]}, env={}).check("soccer", HOME, AWAY)
    assert hold["verdict"] == "pass"


def test_a_red_card_the_projection_did_not_apply_refuses():
    game = _game(away_red_applied=False)
    X.apply_player_exits(game, _summary())
    assert game["liveRefusal"] == "key_player_out" and "Igor Thiago:red_card" in game["liveRefusalDetail"]


def test_the_starting_keeper_subbed_off_refuses_the_match():
    game = _game()
    X.apply_player_exits(game, _summary(red=False, keeper_off=True))
    assert game["liveRefusal"] == "key_player_out" and "keeper_change" in game["liveRefusalDetail"]
    assert [p["modelled"] for p in game["playersOut"]] == [False]


def test_off_ne_on(monkeypatch):
    on = _game()
    X.apply_player_exits(on, _summary(red=False, keeper_off=True))
    monkeypatch.setenv(lps.ENV_SWITCH, "off")
    off = _game()
    tally = X.apply_player_exits(off, _summary(red=False, keeper_off=True), X.new_tally())
    assert on["liveRefusal"] == "key_player_out"
    assert "liveRefusal" not in off and "playersOut" not in off and tally["enabled"] is False


def test_a_clean_match_publishes_an_empty_exit_list_and_unreadable_publishes_none():
    clean = _game()
    X.apply_player_exits(clean, _summary(red=False))
    assert clean["playersOut"] == [] and "liveRefusal" not in clean
    unread = _game()
    tally = X.apply_player_exits(unread, None)
    assert "playersOut" not in unread and tally["unreadable"] == 1
    final = _game()
    X.apply_player_exits(final, _summary(live=False))
    assert "playersOut" not in final


def test_an_out_players_props_refuse_only_without_the_on_pitch_basis():
    on_pitch = _game(basis="on_pitch")
    assert X.apply_player_exits(on_pitch, _summary())["props_refused"] == 0
    squad = _game(basis="squad")
    assert X.apply_player_exits(squad, _summary())["props_refused"] == 1
    thiago, mitoma = squad["live_player_props"]
    assert thiago["notPricedReason"] == "player_out" and "notPricedReason" not in mitoma


def test_the_gameline_and_prop_indexes_skip_what_the_gate_refused(monkeypatch):
    refused = _game(basis="squad")
    X.apply_player_exits(refused, _summary(keeper_off=True))
    monkeypatch.setattr(src, "soccer_live_games", lambda *a, **k: [refused])
    diag: dict = {}
    assert len(src.soccer_live_gameline_index("2026-11-16", diagnostics=diag)) == 0
    assert diag["skipped_key_player_out"] == 1
    report = src.soccer_live_prop_index("2026-11-16")
    assert report["skipped_player_out"] == 1
    players = {k[0] for k in report["index"]}
    assert "igor thiago" not in players and "kaoru mitoma" in players  # only the out player is dropped
    priced = _game()
    X.apply_player_exits(priced, _summary())
    monkeypatch.setattr(src, "soccer_live_games", lambda *a, **k: [priced])
    assert len(src.soccer_live_gameline_index("2026-11-16")) == 1


def test_the_entry_hold_fails_a_refused_match_on_either_team_order():
    game = _game()
    X.apply_player_exits(game, _summary(red=False, keeper_off=True))
    hold = H.ExitHold(read_fn=lambda s: {"games": [game]}, env={})
    for a, b in ((HOME, AWAY), (AWAY, HOME)):
        out = hold.check("soccer", a, b)
        assert out["verdict"] == "fail" and out["reason"] == "key_player_out"
    assert H.PUBLISHING_SPORTS["soccer"] == "soccer_live_lens.json"


def test_the_poller_publishes_the_exit_and_refuses_on_its_own_tick(monkeypatch, tmp_path):
    """Reachability: the production call site in `poll_league`, with the real detector and a real summary."""
    import poll_soccer_live_state as poller

    state = {"event_id": "401879244", "home_team": HOME, "away_team": AWAY, "half": 2, "clock_remaining": 1500.0,
             "score_home": 1, "score_away": 0, "home_red_cards": 0, "away_red_cards": 1, "home_corners_so_far": 4,
             "away_corners_so_far": 3, "home_shots_so_far": 8, "away_shots_so_far": 4,
             "home_shots_on_target_so_far": 3, "away_shots_on_target_so_far": 1, "player_stats": {}}
    summary = {"s": _summary()}
    monkeypatch.setattr(poller, "fetch_events", lambda *a, **k: [
        {"event_id": "401879244", "home_team": HOME, "away_team": AWAY,
         "status_display_clock": "65'", "status_period": 2, "status_detail": "2nd Half"}])
    monkeypatch.setattr(poller, "build_live_state", lambda *a, **k: dict(state))
    monkeypatch.setattr(poller, "fetch_match_summary", lambda *a, **k: summary["s"])
    monkeypatch.setattr(poller, "_load_team_ratings", lambda *a, **k: {})
    monkeypatch.setattr(poller, "_fill_promoted", lambda *a, **k: None)
    monkeypatch.setattr(poller, "_load_player_rows", lambda *a, **k: [])
    monkeypatch.setattr(poller, "_rating_for", lambda *a, **k: {"attack_rating": 0.0, "defense_rating": 0.0})
    monkeypatch.setattr(poller, "fotmob_momentum_block", lambda *a, **k: {"supported": False})
    monkeypatch.setattr(poller, "_build_match_boxes", lambda *a, **k: {})

    def poll():
        return poller.poll_league("epl", "2026-11-16", source_root=tmp_path / "src", out_root=tmp_path / "out",
                                  simulations=4)

    red = poll()
    (game,) = red["games"].values()
    assert game["projection"]["away_red_card_applied"] is True
    assert [(p["player"], p["modelled"]) for p in game["playersOut"]] == [("Igor Thiago", True)]
    assert "liveRefusal" not in game and red["playerExits"]["read"] == 1
    summary["s"] = _summary(red=False, keeper_off=True)
    state["away_red_cards"] = 0
    keeper = poll()
    (game,) = keeper["games"].values()
    assert game["liveRefusal"] == "key_player_out" and keeper["playerExits"]["refused_games"] == 1
