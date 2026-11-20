"""NHL live re-sim refuses a game whose STARTING GOALIE has left (lane live-player-exit-gate, user 2026-11-16).

The tick already reads each live game's api-web box for `livePlayerStats`; the gate reads that same response
(`_box_capturing_fetch`), so it costs no GET. The detector is `live_player_status.exits_from_nhl_boxscore`
(a non-starter goalie with ice time = the starter is out, KEY). Fixture: the real api-web box of 2025021309
(UTA starter Vejmelka 40:00, Vanecek 18:31), from `tests/fixtures/live_player_status/`.
"""

from __future__ import annotations

import copy
import gzip
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from syndicate.features.nhl import live_resim as LR
from syndicate.features.shared import live_player_exit_hold as H
from syndicate.features.shared import live_player_status as lps

PK = "2025021309"
_BOX = json.loads(gzip.decompress(
    (Path(__file__).parent / "fixtures" / "live_player_status" / "nhlapi_2025021309_final_goaliechange.json.gz")
    .read_bytes()).decode("utf-8"))

RESULT = {"home_win_prob": 0.58, "sims_run": 2, "home_margin_mean": 0.4, "total_mean": 5.6, "margin_dist": {}}


def _box(*, relief_toi: str | None = None, state: str = "LIVE") -> dict:
    box = copy.deepcopy(_BOX)
    box["gameState"] = state
    if relief_toi is not None:
        for side in ("homeTeam", "awayTeam"):
            for g in box["playerByGameStats"][side]["goalies"]:
                if not g.get("starter"):
                    g["toi"] = relief_toi
    return box


def _row(state: str = "LIVE") -> dict:
    return {"id": PK, "gameState": state, "awayTeam": {"name": {"default": "Blues"}, "score": 1},
            "homeTeam": {"name": {"default": "Mammoth"}, "score": 2}, "periodDescriptor": {"number": 2},
            "clock": {"timeRemaining": "10:00", "inIntermission": False}}


@pytest.fixture
def tick(monkeypatch):
    monkeypatch.setattr("syndicate.features.shared.request_path_guard.refuse_if_compute_in_request_path",
                        lambda *_: None)
    monkeypatch.setattr(LR, "resim_live_game", lambda features, state, sims=0: dict(RESULT))

    def run(box, *, state: str = "LIVE"):
        calls: list[str] = []

        def fetch(url):
            calls.append(url)
            return box if url.endswith("/boxscore") else None
        snap = LR.build_live_lens_snapshot("2026-11-16", sims=2, score_rows=[_row(state)],
                                           slate_features=[SimpleNamespace(game_pk=PK)],
                                           player_stats_fetch_json=fetch)
        return snap, calls
    return run


def test_a_pulled_starter_refuses_the_lane_and_publishes_who_is_out(tick):
    snap, calls = tick(_box())
    game = snap["games"][0]
    (lane,) = game["gameLens"]
    assert lane["source"] == LR.PREGAME_LENS_SOURCE and lane["refusedSource"] == LR.LIVE_RESIM_LENS_SOURCE
    assert lane["liveResimRefusal"] == "key_player_out" and "UTA:K. Vejmelka:goalie_change" in lane["liveResimRefusalDetail"]
    assert "modelHomeWinProb" not in lane
    assert [(p["team"], p["player"], p["reason"], p["key"]) for p in game["playersOut"]] == [
        ("UTA", "K. Vejmelka", "goalie_change", True)]
    assert sum(u.endswith("/boxscore") for u in calls) == 1  # the livePlayerStats GET, not a second one
    assert snap["coverage"]["refusalsByReason"] == {"key_player_out": 1} and snap["coverage"]["liveResimmed"] == 0
    assert snap["playerExits"]["refused_games"] == 1 and snap["playerExits"]["read"] == 1


def test_off_ne_on(tick, monkeypatch):
    on, _ = tick(_box())
    monkeypatch.setenv(lps.ENV_SWITCH, "off")
    off, _ = tick(_box())
    assert on["games"][0]["gameLens"][0]["liveResimRefusal"] == "key_player_out"
    assert off["games"][0]["gameLens"][0]["source"] == LR.LIVE_RESIM_LENS_SOURCE
    assert "playersOut" not in off["games"][0] and off["playerExits"]["enabled"] is False


def test_a_relief_goalie_with_no_ice_time_keeps_the_game_priced(tick):
    snap, _ = tick(_box(relief_toi="00:00"))
    game = snap["games"][0]
    assert game["gameLens"][0]["source"] == LR.LIVE_RESIM_LENS_SOURCE and game["gameLens"][0]["modelHomeWinProb"] == 0.58
    assert game["playersOut"] == [] and snap["playerExits"]["refused_games"] == 0


def test_an_unreadable_box_publishes_no_exit_list_and_keeps_the_lane(tick):
    snap, _ = tick(None)
    game = snap["games"][0]
    assert "playersOut" not in game and game["gameLens"][0]["source"] == LR.LIVE_RESIM_LENS_SOURCE
    assert snap["playerExits"]["read"] == 0


def test_a_box_that_is_no_longer_live_never_refuses(tick):
    snap, _ = tick(_box(state="OFF"))
    assert snap["games"][0]["gameLens"][0]["source"] == LR.LIVE_RESIM_LENS_SOURCE
    assert "playersOut" not in snap["games"][0]


def test_the_board_index_drops_the_refused_game_and_the_entry_hold_fails(tick):
    from syndicate.features.shared.live_gameline_join import build_live_gameline_index, lens_sources_for_sport

    refused, _ = tick(_box())
    priced, _ = tick(_box(relief_toi="00:00"))

    def index(snap):
        return build_live_gameline_index(snap, sources=lens_sources_for_sport("nhl"), sport="nhl")

    assert len(index(priced)) >= 1 and len(index(refused)) == 0
    g = refused["games"][0]
    hold = H.ExitHold(read_fn=lambda s: refused, env={}).check("nhl", g["home_name"], g["away_name"])
    assert hold["verdict"] == "fail" and hold["players"] == ["UTA:K. Vejmelka:goalie_change"]
    assert H.ExitHold(read_fn=lambda s: priced, env={}).check("nhl", g["away_name"], g["home_name"])["verdict"] == "pass"


def test_nhl_publishes_to_the_hold():
    assert H.PUBLISHING_SPORTS["nhl"] == LR.live_lens_snapshot_path().name


def test_a_live_box_without_starter_flags_still_refuses_the_lane(tick):
    """2026-11-20 BUF @ WSH: a live goalie change read players_out=0; a box with no `starter` flags must refuse."""
    box = _box()
    for side in ("homeTeam", "awayTeam"):
        for g in box["playerByGameStats"][side]["goalies"]:
            g.pop("starter", None)
    snap, _ = tick(box)
    lane = snap["games"][0]["gameLens"][0]
    assert lane["liveResimRefusal"] == "key_player_out" and snap["playerExits"]["refused_games"] == 1
    assert {p["player"] for p in snap["games"][0]["playersOut"]} == {"K. Vejmelka", "V. Vanecek"}
