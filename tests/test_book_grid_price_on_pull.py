"""Price on pull (lane live-price-on-pull, todo #786): between book-grid ticks, a LIVE sport whose quote
shard just changed is rebuilt -- grid and in-play overlay, i.e. its live lines are priced -- instead of
waiting for the tick's own 120 s clock.

Why: the live join prices a quote only up to 120 s old (ncaab/wncaab/nba/ncaaf), and the grid tick ran on
a clock unrelated to live-odds-worker's pulls. Measured 2026-11-11: NCAAB overlay rows were last seen a
median 136 s before their build (the book moved only 19 s before that look), and the join refused 320 of
570 non-segment NCAAB evaluations for quote age.

These drive the REAL `_run_book_grid_artifact_tick` (the harness of `test_book_grid_skip_nonlive.py`),
with real shard files whose mtimes are set, and check off != on through SYNDICATE_BOOK_GRID_PRICE_ON_PULL.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SPEC = importlib.util.spec_from_file_location(
    "run_refresh_worker_price_on_pull", os.path.join(_ROOT, "scripts", "run_refresh_worker.py")
)
worker = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(worker)

TODAY = "2026-11-11"
T0 = datetime(2026, 11, 11, 23, 30, tzinfo=timezone.utc).timestamp()
LIVE = {"rows": [{"game": {"state": "live"}, "commence_time": "2026-11-11T23:00:00Z"}], "rows_total": 1}
FINAL = {"rows": [{"game": {"state": "final"}, "commence_time": "2026-11-11T20:00:00Z"}], "rows_total": 1}


def setup_function(_fn):
    worker._BOOK_GRID_LAST_RUN.clear()
    worker._BOOK_GRID_SPORT_STATE.clear()
    for key in ("SYNDICATE_BOOK_GRID_PRICE_ON_PULL", "SYNDICATE_BOOK_GRID_SKIP_NONLIVE_SPORTS",
                "SYNDICATE_BOOK_GRID_REFRESH_INTERVAL_SECONDS"):
        os.environ.pop(key, None)


def _shard(tmp_path: Path, changed_at: float | None, sidecar_at: float | None = None) -> Path:
    shard = tmp_path / "2026-11-11.jsonl"
    shard.write_text("{}\n", encoding="utf-8")
    os.utime(shard, (changed_at or T0 - 3600, changed_at or T0 - 3600))
    if sidecar_at is not None:
        sidecar = tmp_path / "2026-11-11.state.json"
        sidecar.write_text("{}", encoding="utf-8")
        os.utime(sidecar, (sidecar_at, sidecar_at))
    return shard


def _state(sport: str, *, built_at: float, live: bool, read_at: float | None = None, day: str = TODAY) -> None:
    worker._BOOK_GRID_SPORT_STATE[sport] = {"date": day, "built_at": built_at, "quotes_read_at": read_at or built_at,
                                            "live": live, "next_start": None}


def _tick(tmp_path: Path, shard: Path, now: float, payloads: dict, *, interval: int = 120, env: dict | None = None,
          forward_days: int = 0):
    built: list[tuple[str, str]] = []

    def _build(sport, day):
        built.append((sport, day))
        return payloads.get(sport) if day == TODAY else None

    with patch.dict(os.environ, env or {}), \
         patch.object(worker.time, "time", return_value=now), \
         patch.object(worker, "central_today_iso", return_value=TODAY), \
         patch.object(worker, "_book_grid_forward_days", return_value=forward_days), \
         patch.object(worker, "_book_grid_refresh_interval_seconds", return_value=interval), \
         patch("syndicate.features.shared.book_grid_artifact.build_book_grid_artifact", side_effect=_build), \
         patch("syndicate.features.shared.book_grid_artifact.write_book_grid_artifact", return_value=shard), \
         patch("syndicate.features.shared.artifact_publisher.publish_hot_artifact", return_value=None), \
         patch("syndicate.features.shared.artifact_publisher.pull_streamed_artifact", return_value=None), \
         patch("syndicate.features.shared.odds_book_quotes.book_quotes_path", return_value=shard), \
         patch("syndicate.features.shared.refresh_state_store.data_root", return_value=tmp_path):
        meta = worker._run_book_grid_artifact_tick()
    return built, meta


# --- the decision ---------------------------------------------------------------------------------------


def test_a_live_sport_whose_quotes_landed_after_its_last_read_is_due(tmp_path):
    shard = _shard(tmp_path, changed_at=T0 + 40)
    _state("ncaab", built_at=T0, live=True)
    with patch("syndicate.features.shared.odds_book_quotes.book_quotes_path", return_value=shard):
        assert worker._book_grid_sports_with_new_live_quotes(TODAY, T0 + 60) == ["ncaab"]
        # Quiet period: a shard touched 2 s ago may still be mid-flush.
        os.utime(shard, (T0 + 58, T0 + 58))
        assert worker._book_grid_sports_with_new_live_quotes(TODAY, T0 + 60) == []
        # Nothing new since the last read.
        os.utime(shard, (T0 - 5, T0 - 5))
        assert worker._book_grid_sports_with_new_live_quotes(TODAY, T0 + 60) == []
        # Min gap: built 10 s ago, whatever the shard says.
        os.utime(shard, (T0 + 40, T0 + 40))
        _state("ncaab", built_at=T0 + 50, live=True, read_at=T0 + 20)
        assert worker._book_grid_sports_with_new_live_quotes(TODAY, T0 + 60) == []
        # A sport that was not live at its last build never takes this path.
        _state("ncaab", built_at=T0, live=False)
        assert worker._book_grid_sports_with_new_live_quotes(TODAY, T0 + 60) == []
        # Yesterday's state is not today's.
        _state("ncaab", built_at=T0, live=True, day="2026-11-10")
        assert worker._book_grid_sports_with_new_live_quotes(TODAY, T0 + 60) == []


def test_the_sidecar_counts_as_new_quotes(tmp_path):
    """`.state.json` is rewritten on every flush; a pull that only refreshes last-seen is still new."""
    shard = _shard(tmp_path, changed_at=T0 - 600, sidecar_at=T0 + 30)
    _state("ncaab", built_at=T0, live=True)
    with patch("syndicate.features.shared.odds_book_quotes.book_quotes_path", return_value=shard):
        assert worker._book_grid_shard_mtime("ncaab", TODAY) == T0 + 30
        assert worker._book_grid_sports_with_new_live_quotes(TODAY, T0 + 60) == ["ncaab"]


def test_no_shard_is_never_new_quotes(tmp_path):
    _state("ncaab", built_at=T0, live=True)
    with patch("syndicate.features.shared.odds_book_quotes.book_quotes_path", return_value=tmp_path / "absent.jsonl"):
        assert worker._book_grid_shard_mtime("ncaab", TODAY) is None
        assert worker._book_grid_sports_with_new_live_quotes(TODAY, T0 + 60) == []


# --- the tick (reachability: off != on) -----------------------------------------------------------------


def test_on_pull_rebuilds_only_the_live_sport_between_ticks(tmp_path):
    shard = _shard(tmp_path, changed_at=T0 + 40)
    worker._BOOK_GRID_LAST_RUN.update({"all": T0, "any_live": True, "previous_date": "2026-11-10"})
    _state("ncaab", built_at=T0, live=True)
    _state("nfl", built_at=T0, live=False)
    built, meta = _tick(tmp_path, shard, T0 + 60, {"ncaab": LIVE, "nfl": FINAL})
    assert built == [("ncaab", TODAY)], built
    assert meta["on_pull"] == ["ncaab"] and meta["written"] == ["ncaab:1"]
    assert worker._BOOK_GRID_LAST_RUN["all"] == T0, "an on-pull pass must not move the regular clock"
    assert worker._BOOK_GRID_SPORT_STATE["ncaab"]["built_at"] == T0 + 60
    assert worker._BOOK_GRID_SPORT_STATE["ncaab"]["quotes_read_at"] == T0 + 60


def test_off_switch_restores_the_fixed_clock(tmp_path):
    shard = _shard(tmp_path, changed_at=T0 + 40)
    worker._BOOK_GRID_LAST_RUN.update({"all": T0, "any_live": True})
    _state("ncaab", built_at=T0, live=True)
    built, meta = _tick(tmp_path, shard, T0 + 60, {"ncaab": LIVE}, env={"SYNDICATE_BOOK_GRID_PRICE_ON_PULL": "off"})
    assert built == [] and meta is None
    # ...and ON, the same state and shard build (off != on).
    built_on, meta_on = _tick(tmp_path, shard, T0 + 60, {"ncaab": LIVE})
    assert built_on == [("ncaab", TODAY)] and meta_on["on_pull"] == ["ncaab"]


def test_nothing_new_means_no_pass(tmp_path):
    shard = _shard(tmp_path, changed_at=T0 - 30)
    worker._BOOK_GRID_LAST_RUN.update({"all": T0, "any_live": True})
    _state("ncaab", built_at=T0, live=True)
    assert _tick(tmp_path, shard, T0 + 60, {"ncaab": LIVE}) == ([], None)


def test_an_on_pull_pass_never_builds_other_dates(tmp_path):
    """No previous-date rebuild (still owed: `previous_date` is not set) and no forward dates on this path."""
    shard = _shard(tmp_path, changed_at=T0 + 40)
    worker._BOOK_GRID_LAST_RUN.update({"all": T0, "any_live": True})   # previous_date NOT marked done
    _state("ncaab", built_at=T0, live=True)
    built, meta = _tick(tmp_path, shard, T0 + 60, {"ncaab": LIVE}, forward_days=3)
    assert built == [("ncaab", TODAY)], built
    assert meta["rebuilt_previous"] is None
    assert "previous_date" not in worker._BOOK_GRID_LAST_RUN, "the regular tick still owes yesterday's rebuild"
    assert "forward" not in worker._BOOK_GRID_LAST_RUN


def test_an_on_pull_pass_does_not_clobber_liveness(tmp_path):
    """The pull-path sport went final, but NBA (not rebuilt this pass) is still live: stay on the live cadence."""
    shard = _shard(tmp_path, changed_at=T0 + 40)
    worker._BOOK_GRID_LAST_RUN.update({"all": T0, "any_live": True})
    _state("ncaab", built_at=T0, live=True)
    _state("nba", built_at=T0 + 50, live=True)       # inside its min gap, so not rebuilt here
    built, meta = _tick(tmp_path, shard, T0 + 60, {"ncaab": FINAL, "nba": LIVE})
    assert built == [("ncaab", TODAY)]
    assert worker._BOOK_GRID_SPORT_STATE["ncaab"]["live"] is False
    assert worker._BOOK_GRID_LAST_RUN["any_live"] is True


def test_the_regular_tick_is_unchanged(tmp_path):
    """When the clock comes round, the full tick runs as before and reports no on-pull sports."""
    shard = _shard(tmp_path, changed_at=T0 + 40)
    worker._BOOK_GRID_LAST_RUN.update({"all": T0, "any_live": True, "previous_date": "2026-11-10"})
    _state("ncaab", built_at=T0, live=True)
    built, meta = _tick(tmp_path, shard, T0 + 130, {"ncaab": LIVE})
    assert ("ncaab", TODAY) in built and meta["on_pull"] == []
    assert worker._BOOK_GRID_LAST_RUN["all"] == T0 + 130
