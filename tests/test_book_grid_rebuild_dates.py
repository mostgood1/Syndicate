"""`SYNDICATE_BOOK_GRID_REBUILD_DATES` rebuilds a named past (sport, date), once.

Lane `mlb-past-date-chip-score`. The tick builds today and yesterday only, so a
fix to how a board is BUILT never reached the 09-15 MLB slate (last built 03:10Z
09-17, 0 of 15 games scored). The knob is scoped by SPORT because
`_sport_covers_date` admits every past date for every sport -- a bare date would
pull and pivot eight shards to repair one.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SPEC = importlib.util.spec_from_file_location(
    "run_refresh_worker_rebuild_dates", os.path.join(_ROOT, "scripts", "run_refresh_worker.py")
)
worker = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(worker)

TODAY = "2026-09-18"


def _parse(value: str) -> dict:
    with patch.dict(os.environ, {"SYNDICATE_BOOK_GRID_REBUILD_DATES": value}):
        return worker._book_grid_rebuild_dates(TODAY)


def setup_function(_fn):
    worker._BOOK_GRID_REBUILT_ONCE.clear()
    worker._BOOK_GRID_LAST_RUN.clear()


def test_unset_is_empty():
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("SYNDICATE_BOOK_GRID_REBUILD_DATES", None)
        assert worker._book_grid_rebuild_dates(TODAY) == {}


def test_parses_sport_scoped_dates():
    assert _parse("mlb:2026-09-15, NBA:2026-09-15,mlb:2026-09-14") == {
        "2026-09-15": {"mlb", "nba"},
        "2026-09-14": {"mlb"},
    }


def test_refuses_today_yesterday_future_malformed_and_bare_dates():
    assert _parse("mlb:2026-09-18,mlb:2026-09-17,mlb:2026-09-19,mlb:09-15,2026-09-15") == {}


def _run_tick(tmp_path: Path, env: dict) -> list[tuple[str, str]]:
    built: list[tuple[str, str]] = []
    shard = tmp_path / "shard.jsonl"
    shard.write_text("{}\n", encoding="utf-8")

    def _build(sport, day):
        built.append((sport, day))
        return {"rows": [], "rows_total": 0}

    with patch.dict(os.environ, env), \
         patch.object(worker, "central_today_iso", return_value=TODAY), \
         patch.object(worker, "_book_grid_forward_days", return_value=0), \
         patch.object(worker, "_book_grid_refresh_interval_seconds", return_value=0), \
         patch("syndicate.features.shared.book_grid_artifact.build_book_grid_artifact", side_effect=_build), \
         patch("syndicate.features.shared.book_grid_artifact.write_book_grid_artifact", return_value=shard), \
         patch("syndicate.features.shared.artifact_publisher.publish_hot_artifact", return_value=None), \
         patch("syndicate.features.shared.artifact_publisher.pull_streamed_artifact", return_value=None), \
         patch("syndicate.features.shared.odds_book_quotes.book_quotes_path", return_value=shard), \
         patch("syndicate.features.shared.refresh_state_store.data_root", return_value=tmp_path):
        worker._run_book_grid_artifact_tick()
    return built


def test_tick_builds_only_the_named_sport_for_the_extra_date_and_only_once(tmp_path):
    env = {"SYNDICATE_BOOK_GRID_REBUILD_DATES": "mlb:2026-09-15", "SYNDICATE_ENABLE_BOOK_GRID_ARTIFACT": "true"}
    first = _run_tick(tmp_path, env)
    assert [pair for pair in first if pair[1] == "2026-09-15"] == [("mlb", "2026-09-15")]
    # Today and yesterday are still built exactly as before.
    assert ("mlb", TODAY) in first and ("mlb", "2026-09-17") in first

    second = _run_tick(tmp_path, env)
    assert not [pair for pair in second if pair[1] == "2026-09-15"]


def test_tick_without_the_knob_never_touches_an_older_date(tmp_path):
    os.environ.pop("SYNDICATE_BOOK_GRID_REBUILD_DATES", None)
    built = _run_tick(tmp_path, {"SYNDICATE_ENABLE_BOOK_GRID_ARTIFACT": "true"})
    assert not [pair for pair in built if pair[1] < "2026-09-17"]
