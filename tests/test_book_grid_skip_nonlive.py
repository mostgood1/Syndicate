"""Lever 2b of lane `live-inplay-board-cadence`: on the live cadence, a sport with nothing live
and nothing starting soon is rebuilt on the non-live cadence instead of every tick.

Measured on 2026-09-20's live windows (44 ticks): the grid tick takes ~80 s median, one sport
after another, and every sport's today-grid was rebuilt at the live cadence while ANY game was
live -- NCAAF spent 17 s on a grid with nothing live in one tick. The guard that matters most:
a sport about to kick off must NOT be skipped, or its first-quarter lines wait out 600 s.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SPEC = importlib.util.spec_from_file_location(
    "run_refresh_worker_skip_nonlive", os.path.join(_ROOT, "scripts", "run_refresh_worker.py")
)
worker = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(worker)

TODAY = "2026-09-20"
T0 = datetime(2026, 9, 20, 18, 0, tzinfo=timezone.utc).timestamp()


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _payload(state: str, kickoff: float) -> dict:
    return {"rows": [{"game": {"state": state}, "commence_time": _iso(kickoff)}], "rows_total": 1}


def setup_function(_fn):
    worker._BOOK_GRID_LAST_RUN.clear()
    worker._BOOK_GRID_SPORT_STATE.clear()
    for key in ("SYNDICATE_BOOK_GRID_SKIP_NONLIVE_SPORTS", "SYNDICATE_BOOK_GRID_NONLIVE_LEAD_SECONDS",
                "SYNDICATE_BOOK_GRID_REFRESH_INTERVAL_SECONDS"):
        os.environ.pop(key, None)


# --- the pieces ---------------------------------------------------------------------------------


def test_state_from_payload_reads_live_and_the_next_kickoff():
    rows = {"rows": [
        {"game": {"state": "final"}, "commence_time": _iso(T0 - 7200)},
        {"game": {"state": "pregame"}, "commence_time": _iso(T0 + 3600)},
        {"game": {"state": "pregame"}, "commence_time": _iso(T0 - 1200)},   # should have started: counts
        {"game": {"state": "pregame"}, "commence_time": _iso(T0 - 7200)},   # 2 h stale: ignored
    ]}
    state = worker._book_grid_sport_state_from_payload(rows, T0)
    assert state == {"live": False, "next_start": T0 - 1200}
    assert worker._book_grid_sport_state_from_payload(_payload("live", T0 - 600), T0)["live"] is True


def test_due_decision_matrix():
    info = {"date": TODAY, "built_at": T0, "live": False, "next_start": T0 + 7200}
    due = lambda now, **kw: worker._book_grid_sport_due_today("ncaaf", TODAY, now, live_cadence=kw.get("live", True))  # noqa: E731
    assert due(T0 + 60, live=False) == (True, "all_due")
    assert due(T0 + 60) == (True, "not_built_today")
    worker._BOOK_GRID_SPORT_STATE["ncaaf"] = info
    assert due(T0 + 130) == (False, "not_live")
    assert due(T0 + 600) == (True, "nonlive_interval_elapsed")
    assert due(T0 + 7200 - 900) == (True, "starting_soon"), "kickoff inside the 900 s lead"
    worker._BOOK_GRID_SPORT_STATE["ncaaf"] = dict(info, live=True)
    assert due(T0 + 130) == (True, "live")
    worker._BOOK_GRID_SPORT_STATE["ncaaf"] = dict(info, date="2026-09-19")
    assert due(T0 + 130) == (True, "not_built_today")
    worker._BOOK_GRID_SPORT_STATE["ncaaf"] = info
    with patch.dict(os.environ, {"SYNDICATE_BOOK_GRID_SKIP_NONLIVE_SPORTS": "off"}):
        assert due(T0 + 130) == (True, "skip_off")


def test_an_explicit_interval_pin_never_skips():
    worker._BOOK_GRID_LAST_RUN["any_live"] = True
    assert worker._book_grid_live_cadence_active() is True
    with patch.dict(os.environ, {"SYNDICATE_BOOK_GRID_REFRESH_INTERVAL_SECONDS": "300"}):
        assert worker._book_grid_live_cadence_active() is False


# --- the tick itself (reachability: off != on) --------------------------------------------------


def _tick(tmp_path: Path, now: float, payloads: dict, env: dict | None = None):
    built: list[str] = []
    shard = tmp_path / "shard.jsonl"
    shard.write_text("{}\n", encoding="utf-8")

    def _build(sport, day):
        if day != TODAY or sport not in payloads:
            return None
        built.append(sport)
        return payloads[sport]

    with patch.dict(os.environ, env or {}), \
         patch.object(worker.time, "time", return_value=now), \
         patch.object(worker, "central_today_iso", return_value=TODAY), \
         patch.object(worker, "_book_grid_forward_days", return_value=0), \
         patch.object(worker, "_book_grid_refresh_interval_seconds", return_value=0), \
         patch("syndicate.features.shared.book_grid_artifact.build_book_grid_artifact", side_effect=_build), \
         patch("syndicate.features.shared.book_grid_artifact.write_book_grid_artifact", return_value=shard), \
         patch("syndicate.features.shared.artifact_publisher.publish_hot_artifact", return_value=None), \
         patch("syndicate.features.shared.artifact_publisher.pull_streamed_artifact", return_value=None), \
         patch("syndicate.features.shared.odds_book_quotes.book_quotes_path", return_value=shard), \
         patch("syndicate.features.shared.refresh_state_store.data_root", return_value=tmp_path):
        meta = worker._run_book_grid_artifact_tick()
    return built, meta


def test_a_non_live_sport_is_skipped_on_the_live_cadence_and_the_live_one_is_not(tmp_path):
    payloads = {"mlb": _payload("live", T0 - 3600), "ncaaf": _payload("pregame", T0 + 5 * 3600)}
    first, meta1 = _tick(tmp_path, T0, payloads)
    assert first == ["mlb", "ncaaf"] and meta1["live_cadence"] is False and meta1["any_live"] is True

    second, meta2 = _tick(tmp_path, T0 + 130, payloads)
    assert second == ["mlb"], "NCAAF has nothing live and was built 130 s ago"
    assert meta2["live_cadence"] is True and meta2["skipped_not_live"] == ["ncaaf"] and meta2["live_sports"] == ["mlb"]

    # off != on: the kill switch restores every sport every tick.
    third, _ = _tick(tmp_path, T0 + 260, payloads, env={"SYNDICATE_BOOK_GRID_SKIP_NONLIVE_SPORTS": "off"})
    assert third == ["mlb", "ncaaf"]


def test_a_sport_about_to_kick_off_is_never_skipped(tmp_path):
    payloads = {"mlb": _payload("live", T0 - 3600), "ncaaf": _payload("pregame", T0 + 600)}
    _tick(tmp_path, T0, payloads)
    second, meta = _tick(tmp_path, T0 + 130, payloads)
    assert second == ["mlb", "ncaaf"], "kickoff in ~8 min is inside the 900 s lead"
    assert meta["skipped_not_live"] == []


def test_a_kickoff_alone_puts_the_next_tick_on_the_live_cadence(tmp_path):
    """Nothing live anywhere, NCAAF kicks off in 10 min: the next tick must not wait 600 s."""
    _, meta = _tick(tmp_path, T0, {"ncaaf": _payload("pregame", T0 + 600)})
    assert meta["any_live"] is False and meta["starting_soon"] == ["ncaaf"]
    assert worker._BOOK_GRID_LAST_RUN["any_live"] is True
    # ... and a kickoff hours away does not.
    setup_function(None)
    _tick(tmp_path, T0, {"ncaaf": _payload("pregame", T0 + 5 * 3600)})
    assert worker._BOOK_GRID_LAST_RUN["any_live"] is False
