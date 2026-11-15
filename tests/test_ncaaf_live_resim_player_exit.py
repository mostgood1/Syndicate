"""NCAAF live re-sim refuses a game whose quarterback has left it (lane live-player-exit-gate).

Built on the real Nebraska @ Rutgers final of 2026-11-14 (ESPN 401858525): Rutgers QB Sean Ashenfelder,
"#6 S.Ashenfelder injured on the play" at 18:26:47Z (Q2 8:03), never appears again; AJ Surace finishes.
The payload is final, so the in-game tests flip its header state to "in".
"""

from __future__ import annotations

import copy
import gzip
import json
import threading
import time
from pathlib import Path

import pytest

from syndicate.features.ncaaf import live_resim as lr
from syndicate.features.shared import live_player_exit_hold as H
from syndicate.features.shared import live_player_exit_tick as T
from syndicate.features.shared import live_player_status as lps

FIX = Path(__file__).parent / "fixtures" / "live_player_status" / "ncaaf_401858525_final_qb_injured_2026-11-14.json.gz"
GAMES = [{"away_team": "Nebraska", "home_team": "Rutgers", "live_key": "158@164"}]
ROW = {"in_progress": True, "final": False, "period": 3, "clock": "10:00", "home_score": 10, "away_score": 17,
       "event_id": "401858525"}
RATINGS = {"rutgers": (0.4, 0.2), "nebraska": (0.6, 0.3)}


@pytest.fixture
def summary():
    with gzip.open(FIX, "rt", encoding="utf-8") as fh:
        s = json.load(fh)
    s["header"]["competitions"][0]["status"]["type"]["state"] = "in"
    return s


def _clean(summary, monkeypatch):
    """No injury text AND no replacement rule: Surace's snaps would otherwise give Ashenfelder away."""
    monkeypatch.setattr(lps, "REPLACED_AFTER_SNAPS", 10**6)
    s = copy.deepcopy(summary)
    for drive in s["drives"]["previous"]:
        for play in drive["plays"]:
            play["text"] = play["text"].replace("#6 S.Ashenfelder injured on the play", "")
    return s


def _snapshot(monkeypatch, payload, env=None, row=ROW):
    calls: list = []
    monkeypatch.setattr(T, "fetch_espn_summary", lambda sport, event_id: calls.append((sport, event_id)) or payload)
    snap = lr.build_live_lens_snapshot("2026-11-14", games=GAMES, live_index={"158@164": row}, ratings=RATINGS,
                                       sims=20, env=env if env is not None else {})
    return snap, calls


def _lane(snap):
    return snap["games"][0]["gameLens"][0]


def test_detector_reads_the_college_form(summary):
    st = lps.exits_from_espn_summary("ncaaf", summary, game_id="401858525")
    out = {p.player: p for p in st.players_out}
    qb = out["Sean Ashenfelder"]
    assert (qb.team, qb.key, qb.reason, qb.since) == ("RUTG", True, "injured_in_play", "2026-11-14T18:26:47Z")
    assert lps.gameline_refusal(st)["players"] == ["RUTG:Sean Ashenfelder:injured_in_play"]
    # Three Rutgers defenders hurt that day came back (they make later tackles) and are NOT out.
    assert not {"Jaden Ofurie", "Lawrence Noel", "Sam Kromah"} & set(out)
    # An offensive lineman is in no box category: published with no team, never key.
    assert any(p.team == "" and not p.key for p in st.players_out)


def test_off_ne_on_the_switch_reaches_the_refusal(monkeypatch, summary):
    on, on_calls = _snapshot(monkeypatch, summary)
    off, off_calls = _snapshot(monkeypatch, summary, env={lps.ENV_SWITCH: "off"})
    assert _lane(on)["liveResimRefusal"] == "key_player_out" and _lane(on)["source"] == "pregame"
    assert "RUTG:Sean Ashenfelder:injured_in_play" in _lane(on)["liveResimRefusalDetail"]
    assert "liveResimRefusal" not in _lane(off) and _lane(off)["source"] == "live_resim"
    assert on_calls == [("ncaaf", "401858525")] and off_calls == []  # off costs no GET
    assert "playersOut" in on["games"][0] and "playersOut" not in off["games"][0]
    assert on["coverage"]["refusals_by_reason"] == {"key_player_out": 1}
    tally = on["coverage"]["player_exits"]
    assert tally["live_games"] == 1 and tally["read"] == 1 and tally["key_players_out"] == 1


def test_a_game_with_no_key_exit_is_priced_and_still_publishes_its_exits(monkeypatch, summary):
    snap, _ = _snapshot(monkeypatch, _clean(summary, monkeypatch))
    assert _lane(snap)["source"] == "live_resim"
    assert snap["coverage"]["live_resimmed"] == 1
    assert snap["games"][0]["playersOut"] and not any(p["key"] for p in snap["games"][0]["playersOut"])


def test_unreadable_is_counted_and_never_refuses(monkeypatch):
    snap, calls = _snapshot(monkeypatch, None)
    assert calls == [("ncaaf", "401858525")]
    assert snap["coverage"]["player_exits"]["unreadable"] == 1
    assert "playersOut" not in snap["games"][0] and _lane(snap)["source"] == "live_resim"


def test_a_game_not_in_progress_costs_no_get(monkeypatch, summary):
    snap, calls = _snapshot(monkeypatch, summary, row={**ROW, "in_progress": False})
    assert calls == [] and snap["coverage"]["player_exits"]["live_games"] == 0


def test_the_entry_hold_matches_book_names_to_the_snapshot_schools(monkeypatch, summary):
    snap, _ = _snapshot(monkeypatch, summary)
    hold = H.ExitHold(read_fn=lambda sport: snap, env={})
    out = hold.check("ncaaf", "Rutgers Scarlet Knights", "Nebraska Cornhuskers")
    assert out["verdict"] == "fail" and out["players"] == ["RUTG:Sean Ashenfelder:injured_in_play"]
    assert hold.check("ncaaf", "Nebraska Cornhuskers", "Rutgers Scarlet Knights")["verdict"] == "fail"
    assert hold.check("ncaaf", "Rutgers Scarlet Knights", "Michigan Wolverines")["verdict"] == "unknown"


def test_the_longest_school_wins_so_ohio_state_is_not_ohio():
    snap = {"games": [
        {"home_name": "Miami (OH)", "away_name": "Ohio", "playersOut": [{"team": "OHIO", "player": "QB", "reason": "injury", "key": True}]},
        {"home_name": "Michigan", "away_name": "Ohio State", "playersOut": []},
    ]}
    hold = H.ExitHold(read_fn=lambda sport: snap, env={})
    assert hold.check("ncaaf", "Michigan Wolverines", "Ohio State Buckeyes")["verdict"] == "pass"
    assert hold.check("ncaaf", "Miami (OH) RedHawks", "Ohio Bobcats")["verdict"] == "fail"


def test_the_tick_runs_gets_in_parallel_and_counts_what_the_budget_missed():
    rows = [{"in_progress": True, "event_id": str(i)} for i in range(6)]
    live = {"n": 0, "max": 0}
    lock = threading.Lock()

    def fetch(event_id):
        with lock:
            live["n"] += 1
            live["max"] = max(live["max"], live["n"])
        time.sleep(1.5 if event_id == "5" else 0.2)
        with lock:
            live["n"] -= 1
        return {"header": {"competitions": [{"status": {"type": {"state": "in"}}}]}}

    statuses, tally = T.collect_exit_statuses("ncaaf", rows, env={}, fetch=fetch, budget_seconds=0.8, max_workers=6)
    assert live["max"] >= 2  # concurrent, not one at a time
    assert tally["read"] == 5 and tally["budget_exhausted"] == 1 and "5" not in statuses


def test_the_LIVE_GAMELINE_index_drops_the_game_through_the_real_join(monkeypatch, summary):
    """Off != on at the join itself: the clean game indexes a live projection, the Ashenfelder game none."""
    from syndicate.features.shared.live_gameline_join import (
        analytic_std_err_for_sport,
        build_live_gameline_index,
        lens_sources_for_sport,
    )

    def index(snap):
        return build_live_gameline_index(snap, sources=lens_sources_for_sport("ncaaf"),
                                         analytic_std_err=analytic_std_err_for_sport("ncaaf"),
                                         sport="ncaaf", slate_date="2026-11-14")

    priced, _ = _snapshot(monkeypatch, _clean(summary, monkeypatch))
    refused, _ = _snapshot(monkeypatch, summary)
    assert len(index(priced)) >= 1
    assert index(refused) == {}
