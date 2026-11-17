"""MLB live player-exit gate (lane live-player-exit-gate, user 2026-11-16).

A STARTER who leaves for injury or is ejected is not modelled by the live MC (pregame lineup; an injured
starting pitcher is back on the mound in the sims whenever his team bats), so the game's live lines are
refused. A routine pinch-hitter or pitching change is not an exit. Fixture: the real statsapi feed of 822722
(SEA @ WSH 2026-06-14, Josh Naylor "Injury Delay" top 6, replaced bottom 6), trimmed to the keys the detector
and the tick read.
"""

from __future__ import annotations

import copy
import gzip
import json
from pathlib import Path

import pytest

from syndicate.features.mlb import live_lens as LL
from syndicate.features.mlb import live_player_exits as X
from syndicate.features.mlb.live_lens_port import app_slice as A
from syndicate.features.shared import live_player_exit_hold as H
from syndicate.features.shared import live_player_status as lps

_FIX = Path(__file__).parent / "fixtures" / "live_player_status" / "mlb_822722_final_injury_exit.json.gz"
_FEED = json.loads(gzip.decompress(_FIX.read_bytes()).decode("utf-8"))
HOME, AWAY = "Washington Nationals", "Seattle Mariners"
NAYLOR = 647304


def _feed(*, state: str = "Live", detailed: str = "In Progress", injury: bool = True) -> dict:
    f = copy.deepcopy(_FEED)
    f["gameData"]["status"].update(abstractGameState=state, detailedState=detailed)
    if not injury:
        for play in f["liveData"]["plays"]["allPlays"]:
            play["playEvents"] = [e for e in play["playEvents"]
                                  if not ((e["details"]["eventType"] == "game_advisory") and "Injury" in (e["details"]["description"] or ""))]
    return f


def _add_event(f: dict, inning: int, half: str, event: dict) -> None:
    f["liveData"]["plays"]["allPlays"].append({"about": {"inning": inning, "halfInning": half}, "playEvents": [event]})


# ----------------------------------------------------------------- detector

def test_a_starter_injured_and_replaced_is_a_key_exit():
    status = lps.exits_from_mlb_feed(_feed())
    assert status.in_progress and (status.home_team, status.away_team) == (HOME, AWAY)
    assert [(p.team, p.player, p.reason, p.key) for p in status.players_out] == [("SEA", "Josh Naylor", "injury", True)]


def test_a_routine_substitution_is_not_an_exit():
    # The same replacement (Wisdom for Naylor) without the injury advisory is a manager's choice.
    assert lps.exits_from_mlb_feed(_feed(injury=False)).players_out == ()


def test_not_in_play_never_reports_and_warmup_is_not_in_play():
    assert lps.exits_from_mlb_feed(_feed(state="Final", detailed="Final")).players_out == ()
    assert lps.exits_from_mlb_feed(_feed(detailed="Warmup")).in_progress is False


def test_an_ejected_starter_is_out_and_an_ejected_manager_is_not():
    f = _feed(injury=False)
    _add_event(f, 7, "top", {"type": "action", "player": {"id": 999001},
                             "details": {"eventType": "ejection", "description": "Manager ejected."}})
    assert lps.exits_from_mlb_feed(f).players_out == ()
    _add_event(f, 7, "top", {"type": "action", "player": {"id": NAYLOR},
                             "details": {"eventType": "ejection", "description": "Josh Naylor ejected."}})
    assert [(p.player, p.reason, p.key) for p in lps.exits_from_mlb_feed(f).players_out] == [("Josh Naylor", "ejection", True)]


def test_an_injured_starting_pitcher_is_out_once_his_team_changes_pitchers():
    f = _feed(injury=False)
    starter = f["liveData"]["boxscore"]["teams"]["home"]["pitchers"][0]
    _add_event(f, 9, "top", {"type": "action", "player": {"id": starter},
                             "details": {"eventType": "game_advisory", "description": "Injury Delay."}})
    assert lps.exits_from_mlb_feed(f).players_out == ()  # hurt, still pitching
    _add_event(f, 9, "top", {"type": "action", "player": {"id": 1}, "replacedPlayer": None,
                             "details": {"eventType": "pitching_substitution", "description": "Pitching Change."}})
    (out,) = lps.exits_from_mlb_feed(f).players_out
    assert (out.team, out.player_id, out.reason, out.key) == ("WSH", str(starter), "injury", True)


def test_an_old_injury_advisory_does_not_turn_a_late_tactical_sub_into_an_exit():
    f = _feed(injury=False)
    _add_event(f, 2, "top", {"type": "action", "player": {"id": NAYLOR},
                             "details": {"eventType": "game_advisory", "description": "Injury Delay."}})
    # Naylor's only replacement in the fixture is in the bottom of the 6th: far more than one half-inning later.
    assert lps.exits_from_mlb_feed(f).players_out == ()


# ----------------------------------------------------------------- producer

def test_a_refused_game_lens_never_runs_the_mc_and_says_why(monkeypatch):
    def no_mc(*a, **k):
        raise AssertionError("a refused game must not run the live MC")
    monkeypatch.setattr(A, "_live_mc_projection", no_mc)
    card = {"gamePk": 822722, "status": {"abstract": "Live", "detailed": "In Progress"}, "predictions": {}}
    snapshot = {"status": {"abstractGameState": "Live", "detailedState": "In Progress"},
                "current": {"inning": 7, "halfInning": "top", "count": {"outs": 1}},
                "teams": {"away": {"totals": {"R": 1}}, "home": {"totals": {"R": 6}}}}
    lanes = A._build_game_lens(card, snapshot, None, None, live_mc_refusal="SEA:Josh Naylor:injury")
    assert lanes and all(lane["source"] not in ("live_mc", "live_mc_first5") for lane in lanes)
    assert all(lane["liveResimRefusal"] == "key_player_out" for lane in lanes)


def _stub_tick(monkeypatch, feed: dict, *, mc: dict) -> None:
    card = {"gamePk": 822722, "status": {"abstract": "Live", "detailed": "In Progress"},
            "away": {"abbr": "SEA", "name": AWAY}, "home": {"abbr": "WSH", "name": HOME}, "predictions": {}}
    snapshot = {"status": {"abstractGameState": "Live", "detailedState": "In Progress"},
                "current": {"inning": 7, "halfInning": "top", "count": {"outs": 1}},
                "teams": {"away": {"totals": {"R": 1}}, "home": {"totals": {"R": 6}}}}
    for name, value in {
        "_load_cards_artifacts": lambda d: {}, "_should_load_cards_archive_context": lambda d, a: False,
        "_schedule_games_for_date": lambda d: [], "_load_live_lens_cards": lambda d, **k: [card],
        "_load_game_line_market_index": lambda d: {}, "_load_live_lens_feed": lambda pk, d: feed,
        "_load_live_lens_snapshot": lambda pk, d, feed=None: snapshot,
        "_supplement_card_status_from_live_feed": lambda *a, **k: None,
        "_load_sim_context_for_game": lambda *a, **k: {"found": False},
        "_prop_lens_rows": lambda *a, **k: [], "_live_mc_projection": lambda *a, **k: dict(mc),
        "_current_live_prop_rows": lambda *a, **k: [{"playerName": "Josh Naylor"}, {"playerName": "Julio Rodriguez"}],
        "_normalize_live_lens_live_prop_row": lambda row, *a: row,
        "_game_line_market_for_card": lambda *a: None, "_live_matchup_text": lambda s: "",
    }.items():
        monkeypatch.setattr(A, name, value)


MC = {"away": 2.0, "home": 6.5, "total": 8.5, "homeMargin": 4.5, "homeWinProb": 0.93, "awayWinProb": 0.07,
      "closed": False, "source": "live_mc", "simsRun": 120, "totalRunsDist": {}, "marginDist": {}}


def test_the_tick_publishes_the_exit_and_refuses_the_game(monkeypatch, capsys):
    """Reachability: the production call site in `_live_lens_payload`, with the real detector and feed."""
    _stub_tick(monkeypatch, _feed(), mc=MC)
    payload = A._live_lens_payload("2026-06-14")
    (game,) = payload["games"]
    assert game["liveRefusal"] == "key_player_out" and game["liveRefusalDetail"] == "SEA:Josh Naylor:injury"
    assert [(p["player"], p["key"], p["modelled"]) for p in game["playersOut"]] == [("Josh Naylor", True, False)]
    assert all(lane["source"] != "live_mc" for lane in game["gameLens"])
    assert [r["playerName"] for r in game["liveProps"]] == ["Julio Rodriguez"]
    assert payload["playerExits"]["refused_games"] == 1 and payload["playerExits"]["props_dropped"] == 1
    assert "[mlb_live_lens] PLAYER_EXIT_TICK" in capsys.readouterr().out


def test_off_ne_on(monkeypatch):
    _stub_tick(monkeypatch, _feed(), mc=MC)
    monkeypatch.setenv(lps.ENV_SWITCH, "off")
    (game,) = A._live_lens_payload("2026-06-14")["games"]
    assert "liveRefusal" not in game and "playersOut" not in game
    assert any(lane["source"] == "live_mc" for lane in game["gameLens"])


def test_a_clean_game_is_priced_and_publishes_an_empty_exit_list(monkeypatch):
    _stub_tick(monkeypatch, _feed(injury=False), mc=MC)
    (game,) = A._live_lens_payload("2026-06-14")["games"]
    assert game["playersOut"] == [] and "liveRefusal" not in game
    assert any(lane["source"] == "live_mc" for lane in game["gameLens"])


# ----------------------------------------------------------------- report -> snapshot -> board / hold

def _refused_row() -> dict:
    return {"gamePk": 822722, "status": {"abstract": "Live", "detailed": "In Progress"},
            "matchup": {"away": {"abbr": "SEA", "name": AWAY}, "home": {"abbr": "WSH", "name": HOME}},
            "gameLens": [{"key": "live", "source": "live_projection", "liveResimRefusal": "key_player_out"}],
            "playersOut": [{"team": "SEA", "player": "Josh Naylor", "reason": "injury", "key": True, "modelled": False}],
            "liveRefusal": "key_player_out", "liveRefusalDetail": "SEA:Josh Naylor:injury"}


def test_the_exit_survives_the_card_merge_and_reaches_the_snapshot_row():
    card_row = {"gamePk": 822722, "status": {"abstract": "Live", "detailed": "In Progress"}, "gameLens": []}
    merged = LL._enhance_card_row_with_live_projection(card_row, _refused_row())
    assert merged["liveRefusal"] == "key_player_out" and merged["playersOut"][0]["player"] == "Josh Naylor"
    snap_row = LL._game_from_report_row(merged | {"matchup": _refused_row()["matchup"]}, report_date="2026-06-14",
                                        generated_at="2026-06-14T20:00:00Z")
    assert snap_row["liveRefusal"] == "key_player_out" and snap_row["playersOut"][0]["reason"] == "injury"


def test_carry_forward_never_restores_the_pre_exit_price(monkeypatch):
    previous = {"generatedAt": "2026-06-14T20:00:00Z",
                "games": [{"gamePk": 822722, "gameLens": [{"key": "live", "source": "live_mc", "simsRun": 120,
                                                           "modelHomeWinProb": 0.9}]}]}
    monkeypatch.setattr(LL, "_snapshot_generated_at_age_seconds", lambda s: 30.0)
    monkeypatch.setattr(LL, "_status_bucket_from_row", lambda row: "live")
    refused = LL._carry_forward_live_state_lens({"games": [_refused_row()]}, previous)
    assert refused["games"][0]["gameLens"][0]["source"] == "live_projection"
    clean = {k: v for k, v in _refused_row().items() if k not in ("liveRefusal", "liveRefusalDetail")}
    carried = LL._carry_forward_live_state_lens({"games": [clean]}, previous)
    assert carried["games"][0]["gameLens"][0]["source"] == "live_mc"  # the existing carry is untouched


def test_the_entry_hold_fails_a_refused_game_on_either_team_order():
    row = LL._game_from_report_row(_refused_row(), report_date="2026-06-14", generated_at="2026-06-14T20:00:00Z")
    hold = H.ExitHold(read_fn=lambda s: {"games": [row]}, env={})
    for a, b in ((HOME, AWAY), (AWAY, HOME)):
        out = hold.check("mlb", a, b)
        assert out["verdict"] == "fail" and out["players"] == ["SEA:Josh Naylor:injury"]
    clean = dict(row, playersOut=[])
    assert H.ExitHold(read_fn=lambda s: {"games": [clean]}, env={}).check("mlb", HOME, AWAY)["verdict"] == "pass"
    assert H.PUBLISHING_SPORTS["mlb"] == LL.live_lens_snapshot_path().name


def test_the_board_join_withholds_a_refused_mlb_game():
    from syndicate.features.shared.live_gameline_join import lens_sources_for_sport

    assert "live_projection" not in lens_sources_for_sport("mlb")
