"""The WNBA post-game producer tick: bounded cost, drains, and never retries forever.

This wires two producers into refresh-worker, which is the exact place `#241` put
this worker into a production restart loop at ~1.4GB headroom. The cost rules are
therefore the point of this file, not an afterthought:

  * ONE DATE PER TICK -- a backlog drains over ticks and never multiplies a
    single tick's cost.
  * interval-gated, and it self-skips once the backlog is drained.
  * a date with no completed games is DONE, not a permanent retry.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from scripts import run_refresh_worker as worker


@pytest.fixture()
def store(tmp_path, monkeypatch):
    """An in-memory refresh state store, so the tick's own gating is observable."""
    state: dict[str, dict] = {}

    def read_json_file(path):
        return state.get(str(path))

    def write_json_file(path, payload):
        state[str(path)] = payload

    monkeypatch.setattr(worker, "_refresh_state_store", lambda: {
        "read_json_file": read_json_file, "write_json_file": write_json_file,
        "reports_root": lambda: tmp_path,
    })
    monkeypatch.delenv("SYNDICATE_WNBA_POSTGAME_PRODUCER", raising=False)
    monkeypatch.delenv("SYNDICATE_WNBA_POSTGAME_INTERVAL_SECONDS", raising=False)
    return state


def _patched(recon_status="ok", box_status="ok"):
    return (
        patch("scripts.build_wnba_recon.build_date",
              return_value={"status": recon_status, "games": 4, "quarters": 4, "props": 86}),
        patch("scripts.build_wnba_boxscores.build_date",
              return_value={"status": box_status, "rows": 86}),
    )


def test_off_switch_is_respected(store, monkeypatch):
    monkeypatch.setenv("SYNDICATE_WNBA_POSTGAME_PRODUCER", "off")
    recon, box = _patched()
    with recon as r, box:
        assert worker._run_wnba_postgame_producer_tick() is None
        assert r.call_count == 0


def test_absent_env_means_on():
    """CLAUDE.md's standing rule: absent is not off; the code's default decides."""
    assert worker._wnba_postgame_producer_enabled() is True


def test_one_date_per_tick(store):
    """The `#241` rule. Two ticks must not become one long tick."""
    recon, box = _patched()
    with recon as r, box:
        first = worker._run_wnba_postgame_producer_tick()
        assert r.call_count == 1, "a single tick must build exactly one date"
        assert first["marked_done"] is True
        assert first["date"]


def test_interval_gate_blocks_the_next_tick(store):
    recon, box = _patched()
    with recon as r, box:
        assert worker._run_wnba_postgame_producer_tick() is not None
        calls_after_first = r.call_count
        assert worker._run_wnba_postgame_producer_tick() is None
        assert r.call_count == calls_after_first, "interval gate must suppress the build"


def test_backlog_drains_one_date_at_a_time(store, monkeypatch):
    monkeypatch.setenv("SYNDICATE_WNBA_POSTGAME_INTERVAL_SECONDS", "300")
    recon, box = _patched()
    seen: list[str] = []
    with recon as r, box:
        for _ in range(3):
            # Defeat only the interval gate, so the per-tick date count is what
            # is under test.
            path = str(worker._wnba_postgame_status_path())
            if path in store:
                store[path] = {**store[path], "lastRunEpoch": 0.0}
            result = worker._run_wnba_postgame_producer_tick()
            assert result is not None
            seen.append(result["date"])
    assert len(seen) == 3
    assert len(set(seen)) == 3, "each tick must take a DIFFERENT outstanding date"
    assert r.call_count == 3


def test_a_date_with_no_games_is_done_not_retried_forever(store):
    """The World Cup break is 17 days of empty slates; they must not churn."""
    recon, box = _patched(recon_status="no_final")
    with recon, box:
        result = worker._run_wnba_postgame_producer_tick()
    assert result["marked_done"] is True
    done = store[str(worker._wnba_postgame_status_path())]["done"]
    assert done[result["date"]] == "no_final"


def test_an_error_is_left_outstanding_so_it_retries(store):
    with patch("scripts.build_wnba_recon.build_date", side_effect=RuntimeError("espn down")), \
         patch("scripts.build_wnba_boxscores.build_date", return_value={"status": "ok", "rows": 0}):
        result = worker._run_wnba_postgame_producer_tick()
    assert result["marked_done"] is False
    assert result["recon"]["status"] == "error"
    assert store[str(worker._wnba_postgame_status_path())]["done"] == {}


def test_a_failing_boxscore_does_not_lose_the_recon(store):
    """The two producers are independent; one failing must not undo the other."""
    with patch("scripts.build_wnba_recon.build_date",
               return_value={"status": "ok", "games": 4, "quarters": 4, "props": 86}), \
         patch("scripts.build_wnba_boxscores.build_date", side_effect=RuntimeError("403")):
        result = worker._run_wnba_postgame_producer_tick()
    assert result["recon"]["status"] == "ok"
    assert result["boxscores"]["status"] == "error"
    assert result["marked_done"] is True


def test_drained_backlog_costs_one_write_and_no_builds(store, monkeypatch):
    """Steady state after the backlog clears must not call the producers at all."""
    monkeypatch.setenv("SYNDICATE_WNBA_POSTGAME_INTERVAL_SECONDS", "300")
    path = str(worker._wnba_postgame_status_path())
    store[path] = {
        "lastRunEpoch": 0.0,
        "done": {date_str: "ok" for date_str in worker._wnba_postgame_target_dates()},
    }
    recon, box = _patched()
    with recon as r, box as b:
        assert worker._run_wnba_postgame_producer_tick() is None
        assert r.call_count == 0 and b.call_count == 0


def test_targets_are_completed_dates_only():
    """A live slate must never be half-written."""
    from syndicate.features.shared.timezone import central_today

    targets = worker._wnba_postgame_target_dates()
    assert targets, "must produce a backlog window"
    assert central_today().isoformat() not in targets, "today is not complete"
    assert len(targets) == len(set(targets))


def test_interval_has_a_floor():
    """A misconfigured tiny interval is the shape `#241` warns about."""
    import os

    os.environ["SYNDICATE_WNBA_POSTGAME_INTERVAL_SECONDS"] = "1"
    try:
        assert worker._wnba_postgame_interval_seconds() >= 300.0
    finally:
        os.environ.pop("SYNDICATE_WNBA_POSTGAME_INTERVAL_SECONDS", None)


# ------------------------------------------------- cross-disk reachability
def _publish_patch(recorder, ok=True):
    def _publish(path, timeout_seconds=None):
        recorder.append(str(path))
        return ok
    return patch("syndicate.features.shared.artifact_publisher.publish_hot_artifact", _publish)


def test_produced_artifacts_are_published_to_web(store, tmp_path):
    """Writing to the worker's disk is NOT the same as web being able to read it.

    Measured 2026-09-01: the tick logged recon ok / games 4 / props 86 while web
    still reported `recon_games: false` for the same date, because there is no
    blanket sweep on this service. Allowlisting makes a path ELIGIBLE to cross;
    it does not carry it.
    """
    recon_dir = tmp_path / "wnba_source" / "data" / "processed"
    recon_dir.mkdir(parents=True)
    written = {}
    for kind in ("games", "quarters", "props"):
        p = recon_dir / f"recon_{kind}_2026-08-30.csv"
        p.write_text("date\n", encoding="utf-8")
        written[kind] = str(p)
    box = recon_dir / "boxscores_2026-08-30.csv"
    box.write_text("game_id\n", encoding="utf-8")

    sent: list[str] = []
    with patch("scripts.build_wnba_recon.build_date",
               return_value={"status": "ok", "games": 4, "quarters": 4, "props": 86, "paths": written}), \
         patch("scripts.build_wnba_boxscores.build_date", return_value={"status": "ok", "rows": 86}), \
         patch("scripts.build_wnba_boxscores.artifact_relative_path",
               return_value="wnba_source/data/processed/boxscores_2026-08-30.csv"), \
         patch("syndicate.features.shared.refresh_state_store.data_root", return_value=tmp_path), \
         _publish_patch(sent):
        result = worker._run_wnba_postgame_producer_tick()

    names = {p.rsplit("\\", 1)[-1].rsplit("/", 1)[-1] for p in sent}
    assert "recon_games_2026-08-30.csv" in names
    assert "recon_quarters_2026-08-30.csv" in names, "quarters is the one that had no allowlist entry"
    assert "recon_props_2026-08-30.csv" in names
    assert "boxscores_2026-08-30.csv" in names, "the boxscore is web-facing too"
    assert all(value is True for value in result["published"].values())


def test_a_missing_file_is_named_not_silently_false(store, tmp_path):
    """A `published: false` with no reason is the blindness this block removes."""
    sent: list[str] = []
    with patch("scripts.build_wnba_recon.build_date",
               return_value={"status": "ok", "games": 1, "quarters": 1, "props": 1,
                             "paths": {"games": str(tmp_path / "nope.csv")}}), \
         patch("scripts.build_wnba_boxscores.build_date", return_value={"status": "empty", "rows": 0}), \
         _publish_patch(sent):
        result = worker._run_wnba_postgame_producer_tick()
    assert result["published"]["nope.csv"] == "missing"
    assert sent == [], "a missing file must not be handed to the publisher"


def test_publish_failure_does_not_undo_the_build(store, tmp_path):
    recon_dir = tmp_path / "p"
    recon_dir.mkdir()
    p = recon_dir / "recon_games_2026-08-30.csv"
    p.write_text("date\n", encoding="utf-8")
    with patch("scripts.build_wnba_recon.build_date",
               return_value={"status": "ok", "games": 1, "quarters": 1, "props": 1, "paths": {"games": str(p)}}), \
         patch("scripts.build_wnba_boxscores.build_date", return_value={"status": "empty", "rows": 0}), \
         patch("syndicate.features.shared.artifact_publisher.publish_hot_artifact",
               side_effect=RuntimeError("web unreachable")):
        result = worker._run_wnba_postgame_producer_tick()
    assert "error" in result["published"]
    assert result["marked_done"] is True, "the recon is on disk; a publish failure must not force a rebuild"


def test_keyvalue_backed_artifacts_are_named_not_called_missing(store, tmp_path):
    """A keyvalue artifact is not a lost file and must not be reported as one.

    `write_text_file` returns after `client.set` without touching disk, so a
    keyvalue-backed path never becomes a file. Reporting `missing` sends the
    next reader looking for something that was written correctly.
    """
    sent: list[str] = []
    with patch("scripts.build_wnba_recon.build_date",
               return_value={"status": "ok", "games": 1, "quarters": 1, "props": 1,
                             "paths": {"games": str(tmp_path / "recon_games_2026-08-30.csv")}}),          patch("scripts.build_wnba_boxscores.build_date", return_value={"status": "empty", "rows": 0}),          patch("syndicate.features.shared.refresh_state_store._keyvalue_backed", return_value=True),          _publish_patch(sent):
        result = worker._run_wnba_postgame_producer_tick()
    assert result["published"]["recon_games_2026-08-30.csv"] == "keyvalue_backed_not_a_file"
    assert sent == [], "a keyvalue artifact must not be handed to the file publisher"
