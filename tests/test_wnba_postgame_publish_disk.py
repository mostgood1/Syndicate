"""`#675`: WNBA's post-game artifacts reach web, and the box scores lost to keyvalue come back.

Measured 2026-09-19 on refresh-worker: the hourly producer built every slate
(`WROTE date=2026-09-18 games=3 rows=59`) and published NONE of it. Its own result
read `keyvalue_backed_not_a_file` for all four files: the three recon CSVs (real files,
refused by the publish block's ordering) and the box score (written into keyvalue, never
to disk). Web's newest dated box score stayed `boxscores_2026-08-24.csv`.

Every test here fails on the pre-change code.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from scripts import run_refresh_worker as worker
from syndicate.features.shared import refresh_state_store as store_mod


# --- the storage rule ----------------------------------------------------------------


def test_dated_box_scores_leave_keyvalue_and_nothing_else_moves(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_REFRESH_STATE_BACKEND", "keyvalue")
    processed = tmp_path / "wnba_source" / "data" / "processed"
    assert store_mod._keyvalue_backed(processed / "boxscores_2026-09-18.csv") is False
    # Deliberately untouched: the history file (its own writer) and every other path.
    assert store_mod._keyvalue_backed(processed / "boxscores_history.csv") is True
    assert store_mod._keyvalue_backed(processed / "recon_games_2026-09-18.csv") is True
    assert store_mod._keyvalue_backed(tmp_path / "nba_source" / "data" / "processed" / "boxscores_2026-09-18.csv") is True


def test_the_writer_and_the_settlers_reader_both_use_disk(tmp_path, monkeypatch):
    """One predicate moves both, so the settler cannot look where the writer did not write."""
    monkeypatch.setenv("SYNDICATE_REFRESH_STATE_BACKEND", "keyvalue")
    monkeypatch.setattr(store_mod, "_get_keyvalue_client", lambda: (_ for _ in ()).throw(AssertionError("keyvalue touched")))
    path = tmp_path / "wnba_source" / "data" / "processed" / "boxscores_2026-09-18.csv"
    store_mod.write_text_file(path, "game_id,PTS\n401,12\n")
    assert path.is_file()
    # `read_text_file` strips trailing whitespace (existing store behaviour); the rows are what matter.
    assert store_mod.read_text_file(path).splitlines() == ["game_id,PTS", "401,12"]


# --- the producer --------------------------------------------------------------------


@pytest.fixture()
def state(tmp_path, monkeypatch):
    held: dict[str, dict] = {}
    monkeypatch.setattr(worker, "_refresh_state_store", lambda: {
        "read_json_file": lambda path: held.get(str(path)),
        "write_json_file": lambda path, payload: held.__setitem__(str(path), payload),
        "reports_root": lambda: tmp_path / "reports",
    })
    monkeypatch.delenv("SYNDICATE_WNBA_POSTGAME_PRODUCER", raising=False)
    monkeypatch.setenv("SYNDICATE_WNBA_POSTGAME_INTERVAL_SECONDS", "300")
    monkeypatch.setattr(worker, "_wnba_postgame_target_dates", lambda lookback_days=30: ["2026-09-18", "2026-09-17", "2026-09-16"])
    return held


def _status(held: dict) -> dict:
    return held[str(worker._wnba_postgame_status_path())]


def _reopen_gate(held: dict) -> None:
    path = str(worker._wnba_postgame_status_path())
    held[path] = {**held[path], "lastRunEpoch": 0.0}


def test_a_recon_file_on_disk_is_published_under_the_keyvalue_backend(state, tmp_path):
    processed = tmp_path / "wnba_source" / "data" / "processed"
    processed.mkdir(parents=True)
    paths = {}
    for kind in ("games", "quarters", "props"):
        p = processed / f"recon_{kind}_2026-09-18.csv"
        p.write_text("date\n", encoding="utf-8")
        paths[kind] = str(p)
    sent: list[str] = []
    with patch("scripts.build_wnba_recon.build_date", return_value={"status": "ok", "games": 3, "quarters": 3, "props": 59, "paths": paths}), \
         patch("scripts.build_wnba_boxscores.build_date", return_value={"status": "empty", "rows": 0}), \
         patch("syndicate.features.shared.refresh_state_store._keyvalue_backed", return_value=True), \
         patch("syndicate.features.shared.artifact_publisher.publish_hot_artifact", side_effect=lambda p, timeout_seconds=0: sent.append(str(p)) or True):
        result = worker._run_wnba_postgame_producer_tick()
    # Pre-change: all three read `keyvalue_backed_not_a_file`, exactly production's 2026-09-18 result.
    assert result["published"] == {f"recon_{k}_2026-09-18.csv": True for k in ("games", "quarters", "props")}
    assert len(sent) == 3


def _build_box_into(box_dir: Path):
    def build_box(date_str, **kw):
        box_dir.mkdir(parents=True, exist_ok=True)
        (box_dir / f"boxscores_{date_str}.csv").write_text("game_id\n", encoding="utf-8")
        return {"status": "ok", "rows": 1}
    return build_box


def test_a_done_date_whose_box_score_was_never_published_is_rebuilt_newest_first(state, tmp_path):
    state[str(worker._wnba_postgame_status_path())] = {"lastRunEpoch": 0.0, "done": {
        "2026-09-18": "ok", "2026-09-17": "no_final", "2026-09-16": "ok"}}
    box_dir = tmp_path / "wnba_source" / "data" / "processed"

    with patch("scripts.build_wnba_recon.build_date", return_value={"status": "ok", "games": 1, "quarters": 1, "props": 1}), \
         patch("scripts.build_wnba_boxscores.build_date", side_effect=_build_box_into(box_dir)), \
         patch("syndicate.features.shared.refresh_state_store.data_root", return_value=tmp_path), \
         patch("syndicate.features.shared.artifact_publisher.publish_hot_artifact", return_value=True):
        first = worker._run_wnba_postgame_producer_tick()
        _reopen_gate(state)
        second = worker._run_wnba_postgame_producer_tick()
        _reopen_gate(state)
        third = worker._run_wnba_postgame_producer_tick()
    # 09-17 had no finished games ("no_final"), so it has no box score to rebuild.
    assert (first["date"], first["box_rebuild"]) == ("2026-09-18", True)
    assert first["published"]["boxscores_2026-09-18.csv"] is True
    assert (second["date"], second["box_rebuild"]) == ("2026-09-16", True)
    assert third is None, "every ok date's box score has been published: the backlog is drained"
    assert _status(state)["box_rebuilds"] == {"2026-09-18": 1, "2026-09-16": 1}
    assert _status(state)["box_published"] == {"2026-09-18": True, "2026-09-16": True}


def test_a_box_score_the_settlement_pass_already_wrote_is_still_published(state, tmp_path):
    """`intelligence_state._refresh_wnba_boxscores` writes yesterday's file and never publishes it.

    Once the marker puts that write on disk, "on disk" no longer means "on web".
    Keyed on the file being present, the backfill skipped 2026-09-18 for good.
    """
    state[str(worker._wnba_postgame_status_path())] = {"lastRunEpoch": 0.0, "done": {
        "2026-09-18": "ok", "2026-09-17": "no_final", "2026-09-16": "no_final"}}
    box_dir = tmp_path / "wnba_source" / "data" / "processed"
    box_dir.mkdir(parents=True)
    (box_dir / "boxscores_2026-09-18.csv").write_text("game_id\n401\n", encoding="utf-8")
    sent: list[str] = []
    with patch("scripts.build_wnba_recon.build_date", return_value={"status": "ok", "games": 1, "quarters": 1, "props": 1}), \
         patch("scripts.build_wnba_boxscores.build_date", side_effect=_build_box_into(box_dir)), \
         patch("syndicate.features.shared.refresh_state_store.data_root", return_value=tmp_path), \
         patch("syndicate.features.shared.artifact_publisher.publish_hot_artifact", side_effect=lambda p, timeout_seconds=0: sent.append(Path(p).name) or True):
        result = worker._run_wnba_postgame_producer_tick()
    assert result is not None and (result["date"], result["box_rebuild"]) == ("2026-09-18", True)
    assert "boxscores_2026-09-18.csv" in sent


def test_a_normal_tick_records_its_publish_so_the_date_is_never_rebuilt(state, tmp_path):
    """Steady state: yesterday is built and published once, then the producer is idle."""
    state[str(worker._wnba_postgame_status_path())] = {
        "lastRunEpoch": 0.0,
        "done": {"2026-09-17": "ok", "2026-09-16": "ok"},
        "box_published": {"2026-09-17": True, "2026-09-16": True},
    }
    box_dir = tmp_path / "wnba_source" / "data" / "processed"
    with patch("scripts.build_wnba_recon.build_date", return_value={"status": "ok", "games": 1, "quarters": 1, "props": 1}), \
         patch("scripts.build_wnba_boxscores.build_date", side_effect=_build_box_into(box_dir)), \
         patch("syndicate.features.shared.refresh_state_store.data_root", return_value=tmp_path), \
         patch("syndicate.features.shared.artifact_publisher.publish_hot_artifact", return_value=True):
        first = worker._run_wnba_postgame_producer_tick()
        _reopen_gate(state)
        second = worker._run_wnba_postgame_producer_tick()
    assert (first["date"], first["box_rebuild"]) == ("2026-09-18", False)
    assert second is None
    assert _status(state)["box_published"]["2026-09-18"] is True
    assert _status(state).get("box_rebuilds", {}) == {}


def test_a_date_espn_will_not_serve_is_given_up_after_three_attempts(state, tmp_path):
    state[str(worker._wnba_postgame_status_path())] = {
        "lastRunEpoch": 0.0,
        "done": {"2026-09-18": "ok", "2026-09-17": "ok", "2026-09-16": "ok"},
        "box_published": {"2026-09-17": True, "2026-09-16": True},
    }
    targets = []
    with patch("scripts.build_wnba_recon.build_date", return_value={"status": "ok", "games": 1, "quarters": 1, "props": 1}), \
         patch("scripts.build_wnba_boxscores.build_date", return_value={"status": "error", "rows": 0}), \
         patch("syndicate.features.shared.refresh_state_store.data_root", return_value=tmp_path), \
         patch("syndicate.features.shared.artifact_publisher.publish_hot_artifact", return_value=True):
        for _ in range(5):
            result = worker._run_wnba_postgame_producer_tick()
            targets.append(result and result["date"])
            _reopen_gate(state)
    assert targets == ["2026-09-18"] * 3 + [None, None]
    assert _status(state)["box_rebuilds"] == {"2026-09-18": 3}


def test_the_lookback_reaches_the_first_lost_date():
    """2026-08-25 was the first slate lost; the fix reached production on 2026-09-19/20."""
    from datetime import date, timedelta

    with patch("syndicate.features.shared.timezone.central_today", return_value=date(2026, 9, 20)):
        dates = worker._wnba_postgame_target_dates()
    assert "2026-08-25" in dates and dates[0] == (date(2026, 9, 20) - timedelta(days=1)).isoformat()
