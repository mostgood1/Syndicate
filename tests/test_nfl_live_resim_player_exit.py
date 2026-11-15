"""NFL live re-sim refuses a game whose quarterback has left it (lane live-player-exit-gate).

Built on the real NE @ DET halftime payload of 2026-11-15 (ESPN 401873053), where Drake Maye was
hurt at 14:41:43Z and the re-sim -- 0 player inputs -- kept simulating him.
"""

from __future__ import annotations

import copy
import gzip
import json
from pathlib import Path

import pytest

from syndicate.features.nfl import live_player_box
from syndicate.features.nfl import live_resim as R
from syndicate.features.shared import live_player_status as lps

FIX = Path(__file__).parent / "fixtures" / "live_player_status" / "nfl_401873053_halftime_2026-11-15.json.gz"

LIVE_ROW = {
    "state": "in", "event_id": "401873053", "period": 3, "clock_seconds": 600,
    "home_score": 21, "away_score": 3, "possession_owner": "home",
    "down": 2, "distance": 7, "field_position": 41,
}
GAMES = [{"away_team": "NE", "home_team": "DET", "live_key": "g1"}]
RATINGS = {"DET": (27.0, 19.0), "NE": (20.0, 24.0)}


@pytest.fixture
def summary():
    with gzip.open(FIX, "rt", encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture
def no_box(monkeypatch):
    """The box-score attach is a separate GET this file is not about."""
    monkeypatch.setattr(R, "_attach_live_player_stats", lambda targets, **kw: {"stubbed": True})


def _snapshot(monkeypatch, payload, env):
    calls = []

    def fake_fetch(event_id):
        calls.append(event_id)
        return payload

    monkeypatch.setattr(live_player_box, "_fetch_summary", fake_fetch)
    snap = R.build_live_lens_snapshot("2026-11-15", games=GAMES, live_index={"g1": LIVE_ROW},
                                      ratings=RATINGS, sims=20, env=env)
    return snap, calls


def _reason(snap):
    return snap["games"][0]["gameLens"][0]["refusal"]["reason"]


def test_off_ne_on_the_switch_reaches_the_refusal(monkeypatch, summary, no_box):
    on, on_calls = _snapshot(monkeypatch, summary, env={})
    off, off_calls = _snapshot(monkeypatch, summary, env={lps.ENV_SWITCH: "off"})
    assert _reason(on) == "key_player_out"
    assert _reason(off) != "key_player_out"
    assert on_calls == ["401873053"] and off_calls == []  # off costs no GET
    assert "playersOut" in on["games"][0] and "playersOut" not in off["games"][0]


def test_the_refusal_names_the_player_and_the_tick_counts_it(monkeypatch, summary, no_box):
    snap, _ = _snapshot(monkeypatch, summary, env={})
    lane = snap["games"][0]["gameLens"][0]
    assert lane["ok"] is False
    assert "NE:Drake Maye:injured_in_play" in lane["refusal"]["detail"]
    assert snap["coverage"]["refusals_by_reason"] == {"key_player_out": 1}
    tally = snap["coverage"]["player_exits"]
    assert tally["read"] == 1 and tally["key_players_out"] == 1
    out = {p["player"]: p for p in snap["games"][0]["playersOut"]}
    assert out["Drake Maye"]["key"] is True
    assert out["Robert Spillane"]["key"] is False  # props-only exit published too


def test_a_game_with_no_exit_is_unchanged(monkeypatch, summary, no_box):
    """0 change to games with no exit: the refusal is the flag's, exactly as before this lane."""
    clean = copy.deepcopy(summary)
    clean["injuries"] = []
    for drive in clean["drives"]["previous"]:
        for play in drive["plays"]:
            play["text"] = play["text"].split(" was injured during the play")[0]
    snap, _ = _snapshot(monkeypatch, clean, env={})
    monkeypatch.setattr(live_player_box, "_fetch_summary", lambda e: None)
    base = R.build_live_lens_snapshot("2026-11-15", games=GAMES, live_index={"g1": LIVE_ROW},
                                      ratings=RATINGS, sims=20, env={})
    assert _reason(snap) == _reason(base) == "nfl_live_resim_disabled"
    assert snap["games"][0]["playersOut"] == []


def test_an_unreadable_summary_is_counted_never_read_as_nobody_out(monkeypatch, no_box):
    snap, calls = _snapshot(monkeypatch, None, env={})
    assert calls == ["401873053"]
    assert snap["coverage"]["player_exits"]["unreadable"] == 1
    assert "playersOut" not in snap["games"][0]


def test_a_final_game_keeps_its_own_refusal(monkeypatch, summary, no_box):
    monkeypatch.setattr(live_player_box, "_fetch_summary", lambda e: summary)
    snap = R.build_live_lens_snapshot("2026-11-15", games=GAMES,
                                      live_index={"g1": {**LIVE_ROW, "state": "final"}},
                                      ratings=RATINGS, sims=20, env={})
    assert _reason(snap) == "game_final"
    assert snap["coverage"]["player_exits"]["live_games"] == 0
