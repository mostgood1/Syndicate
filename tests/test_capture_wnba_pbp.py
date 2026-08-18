"""Tests for `scripts/capture_wnba_pbp.py` (`#454`, lane `game-shape-capture`).

The skeleton fixture below is the EXACT structure
`build_live_pbp_stats_payload` (`wnba/cards.py:6403-6421`) emits when it has no
stored snapshot, and the one production served for three real games on
2026-08-16.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

_SPEC = importlib.util.spec_from_file_location(
    "capture_wnba_pbp",
    Path(__file__).resolve().parents[1] / "scripts" / "capture_wnba_pbp.py",
)
mod = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(mod)


def _skeleton(event_id: str = "401857148") -> dict[str, Any]:
    """Byte-for-byte the shape `cards.py:6410-6421` builds."""
    return {
        "event_id": event_id,
        "game_id": event_id,
        "home": None,
        "away": None,
        "pbp_attempts": {"home": {}, "away": {}, "unknown": {}, "total": {}},
        "pbp_attempts_periods": {},
        "pbp_possessions": {"home": {}, "away": {}, "unknown": {}, "total": {}},
        "pbp_possessions_periods": {},
        "pbp_quarters": {"q_totals": {"q1": None, "q2": None, "q3": None, "q4": None},
                         "current": {"period": None, "q_total": None}},
        "pbp_recent": {"window_sec": 180, "points_total": None, "attempts": None,
                       "possessions": None,
                       "current_scoring_run": {"team": None, "points": None},
                       "seconds_since_score": None},
    }


def _real(event_id: str = "PHX@TOR") -> dict[str, Any]:
    game = _skeleton(event_id)
    game["pbp_possessions"] = {
        "home": {"poss_est": 0.0}, "away": {"poss_est": 0.0},
        "PHX": {"poss_est": 73.0, "tov": 11, "oreb": 7, "dreb": 20},
        "TOR": {"poss_est": 73.04, "tov": 12, "oreb": 9, "dreb": 21},
        "total": {"poss_est": 146.04},
    }
    game["pbp_quarters"] = {"q_totals": {"q1": 38, "q2": 44, "q3": 45, "q4": 36},
                            "current": {"period": 4, "q_total": 36}}
    return game


# --------------------------------------------------------------------------
# The refusal -- the whole point
# --------------------------------------------------------------------------


def test_the_production_skeleton_has_no_signal():
    """The exact payload served for 3 real games (2 final, 1 live) on 08-16.

    `ok: True` plus a complete structure reads as an answer to every consumer.
    If this returns True the capturer would industrialise the defect.
    """
    assert mod.has_pbp_signal(_skeleton()) is False


def test_a_real_record_has_signal():
    assert mod.has_pbp_signal(_real()) is True


def test_signal_is_detected_from_any_one_of_the_three_sources():
    """Guards against checking possessions only.

    A game can have attempts or a live quarter before any possession estimate
    settles; treating those as skeletons would drop the earliest real ticks.
    """
    only_quarter = _skeleton()
    only_quarter["pbp_quarters"]["current"]["period"] = 1
    assert mod.has_pbp_signal(only_quarter) is True

    only_attempts = _skeleton()
    only_attempts["pbp_attempts"] = {"PHX": {"fg2_att": 12, "fg3_att": 5, "ft_att": 3},
                                     "home": {}, "away": {}, "total": {}}
    assert mod.has_pbp_signal(only_attempts) is True

    only_q_totals = _skeleton()
    only_q_totals["pbp_quarters"]["q_totals"]["q1"] = 26
    assert mod.has_pbp_signal(only_q_totals) is True


def test_zero_valued_home_away_possessions_are_not_signal():
    """The tricode trap again: home/away are 0.0 on every populated record.

    Counting them would make every skeleton look real.
    """
    game = _skeleton()
    game["pbp_possessions"] = {"home": {"poss_est": 0.0}, "away": {"poss_est": 0.0},
                               "total": {"poss_est": 0.0}}
    assert mod.has_pbp_signal(game) is False


def test_has_pbp_signal_never_raises():
    for bad in (None, {}, "", 0, [], object(), {"pbp_possessions": "banana"}):
        assert mod.has_pbp_signal(bad) is False


# --------------------------------------------------------------------------
# Classification and storage
# --------------------------------------------------------------------------


def test_classify_splits_real_from_skeleton():
    payload = {"games": [_skeleton("a"), _real("PHX@TOR"), _skeleton("c")]}
    out = mod.classify(payload)
    assert out["games"] == 3
    assert out["with_signal"] == 1
    assert out["skeleton"] == 2
    assert len(out["real_games"]) == 1


def test_classify_never_raises_on_junk():
    assert mod.classify(None)["error"] == "payload_not_a_mapping"
    assert mod.classify({"games": "nope"})["error"] == "games_not_a_list"


def test_append_capture_writes_nothing_when_there_is_no_real_game(tmp_path):
    """A capture file that contains skeletons is worse than no capture file."""
    path = tmp_path / "cap.jsonl"
    assert mod.append_capture(path, {"generated_at": "x"}, []) == 0
    assert not path.exists()


def test_append_capture_keeps_both_clocks_separate(tmp_path):
    """Source `generated_at` and our `captured_at` are different clocks.

    Conflating them has cost this repo before -- a stale payload captured now
    would otherwise look fresh.
    """
    path = tmp_path / "cap.jsonl"
    written = mod.append_capture(
        path, {"generated_at": "2026-08-16T16:14:21-05:00", "date": "2026-08-16"}, [_real()]
    )
    assert written == 1
    record = json.loads(path.read_text(encoding="utf-8").strip())
    assert record["source_generated_at"] == "2026-08-16T16:14:21-05:00"
    assert record["captured_at"] != record["source_generated_at"]
    assert len(record["games"]) == 1


def test_run_once_in_probe_mode_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "fetch", lambda *a, **k: {"games": [_real()], "generated_at": "x"})
    out = mod.run_once("http://x", "2026-08-16", tmp_path, store=False)
    assert out["with_signal"] == 1
    assert out["written"] == 0
    assert not list(tmp_path.glob("*.jsonl"))


def test_run_once_stores_only_the_real_games(tmp_path, monkeypatch):
    monkeypatch.setattr(
        mod, "fetch",
        lambda *a, **k: {"games": [_skeleton("a"), _real("PHX@TOR")], "generated_at": "x",
                         "date": "2026-08-16"},
    )
    out = mod.run_once("http://x", "2026-08-16", tmp_path, store=True)
    assert out["skeleton"] == 1 and out["with_signal"] == 1 and out["written"] == 1
    record = json.loads(mod.capture_path(tmp_path, "2026-08-16").read_text(encoding="utf-8").strip())
    assert [g["game_id"] for g in record["games"]] == ["PHX@TOR"]


def test_run_once_reports_a_fetch_failure_rather_than_writing(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise urllib_error()

    def urllib_error():
        return RuntimeError("connection reset")

    monkeypatch.setattr(mod, "fetch", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    out = mod.run_once("http://x", "2026-08-16", tmp_path, store=True)
    assert out["ok"] is False
    assert "RuntimeError" in out["error"]
    assert out["written"] == 0
