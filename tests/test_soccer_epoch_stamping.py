"""`#353` — a launch is not a refresh.

`unitEpochs` was stamped at LAUNCH, before the subprocess had done anything, so
a unit that failed marked itself satisfied for the full 4-hour interval exactly
as if it had succeeded.

Measured on production 2026-08-11: la_liga launched at 15:36, 16:13 and 16:46,
wrote nothing at any of its three dates, and at 18:36 the autorun reported
`no_unit_due units=8 next_due_in_s=3612` while five other leagues had refreshed
within fifteen minutes. Its files stayed on `generated_at: 2026-07-20` -- 22
days -- and would have stayed there indefinitely, because each retry re-stamps
on launch and sleeps again.

Same shape as `#347`, where the reuse recorder fired after a REUSE and the guard
agreed with itself forever.
"""

from __future__ import annotations

import importlib.util
import pathlib
import time

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "_rrw_epoch", pathlib.Path(__file__).resolve().parents[1] / "scripts" / "run_refresh_worker.py"
)


@pytest.fixture()
def worker():
    mod = importlib.util.module_from_spec(_SPEC)
    _SPEC.loader.exec_module(mod)
    return mod


def _rec(tmp_path, league, date_str, mtime):
    d = tmp_path / "soccer_source" / league / "api" / "recommendations"
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"recommendations_{date_str}.json"
    f.write_text("{}", encoding="utf-8")
    import os
    os.utime(f, (mtime, mtime))
    return f


def test_a_file_written_after_launch_counts_as_a_write(worker, tmp_path, monkeypatch):
    import syndicate.features.shared.refresh_state_store as store
    monkeypatch.setattr(store, "data_root", lambda: tmp_path)
    launched = time.time() - 60
    _rec(tmp_path, "championship", "2026-08-14", mtime=launched + 41)   # observed: 41s
    wrote, path, mtime = worker._soccer_unit_wrote_since("championship|2026-08-14", launched)
    assert wrote is True
    assert mtime > launched


def test_a_file_older_than_the_launch_is_not_a_write(worker, tmp_path, monkeypatch):
    # THE OBSERVED FAILURE: la_liga launched three times, file untouched since July.
    import syndicate.features.shared.refresh_state_store as store
    monkeypatch.setattr(store, "data_root", lambda: tmp_path)
    launched = time.time() - 60
    _rec(tmp_path, "la_liga", "2026-08-15", mtime=launched - 22 * 86400)
    wrote, _p, _m = worker._soccer_unit_wrote_since("la_liga|2026-08-15", launched)
    assert wrote is False


def test_an_absent_file_is_not_a_write(worker, tmp_path, monkeypatch):
    import syndicate.features.shared.refresh_state_store as store
    monkeypatch.setattr(store, "data_root", lambda: tmp_path)
    wrote, _p, _m = worker._soccer_unit_wrote_since("eredivisie|2026-08-14", time.time() - 60)
    assert wrote is False


def test_unknowable_is_none_and_never_false(worker):
    # Marking a unit failed because we could not LOOK would retry it forever.
    # None must stay distinct from False.
    assert worker._soccer_unit_wrote_since("no-separator", time.time())[0] is None
    assert worker._soccer_unit_wrote_since("", 1.0)[0] is None
    assert worker._soccer_unit_wrote_since("la_liga|2026-08-15", 0.0)[0] is None


def test_the_launch_no_longer_stamps_the_success_epoch(worker):
    src = (pathlib.Path(__file__).resolve().parents[1] / "scripts" / "run_refresh_worker.py").read_text(encoding="utf-8")
    # the launch writes an ATTEMPT, not a refresh
    assert '"lastAttemptEpochs": {**last_attempts, _soccer_unit_key(unit): launched_epoch}' in src
    assert '"unitEpochs": {**unit_epochs, _soccer_unit_key(unit): launched_epoch}' not in src, (
        "the launch is stamping the success epoch again -- this is the #353 defect"
    )


def test_success_and_attempt_are_separate_clocks(worker):
    src = (pathlib.Path(__file__).resolve().parents[1] / "scripts" / "run_refresh_worker.py").read_text(encoding="utf-8")
    assert "retry_backoff_seconds" in src
    assert "SOCCER_UNIT_CONFIRMED" in src, "a verified write must be attributable in the log"
