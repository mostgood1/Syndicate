"""`#352` — did the soccer unit actually write anything?

The launch is fire-and-forget: the worker records a pid and returns without
checking what the subprocess did. A unit that dies in two seconds and one that
simulates a full slate look identical from outside -- both log
SOCCER_UNIT_LAUNCHED, both decrement `due`.

Measured 2026-08-11: units ran at 15:36 and 16:13, `due` fell 8 -> 7, and both
target files still carried `generated_at: 2026-07-20` -- 22 days old.
"""

from __future__ import annotations

import importlib.util
import pathlib
import time

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "_rrw_soccer", pathlib.Path(__file__).resolve().parents[1] / "scripts" / "run_refresh_worker.py"
)


@pytest.fixture()
def worker():
    mod = importlib.util.module_from_spec(_SPEC)
    _SPEC.loader.exec_module(mod)
    return mod


def _make(tmp_path, league, date_str, mtime=None):
    d = tmp_path / "soccer_source" / league / "api" / "recommendations"
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"recommendations_{date_str}.json"
    f.write_text("{}", encoding="utf-8")
    if mtime is not None:
        import os
        os.utime(f, (mtime, mtime))
    return f


def test_a_unit_that_left_a_stale_file_reads_as_not_written(worker, tmp_path, monkeypatch, capsys):
    # THE OBSERVED FAILURE: file exists, is 22 days old, unit "ran".
    import syndicate.features.shared.refresh_state_store as store
    monkeypatch.setattr(store, "data_root", lambda: tmp_path)
    _make(tmp_path, "la_liga", "2026-08-15", mtime=time.time() - 22 * 86400)
    worker._report_soccer_unit_outcome({"lastUnit": "la_liga|2026-08-15", "lastLaunchEpoch": time.time() - 60})
    out = capsys.readouterr().out
    assert "SOCCER_UNIT_OUTCOME" in out
    assert "exists=True" in out
    assert "wrote_since_launch=False" in out


def test_a_unit_that_wrote_reads_as_written(worker, tmp_path, monkeypatch, capsys):
    import syndicate.features.shared.refresh_state_store as store
    monkeypatch.setattr(store, "data_root", lambda: tmp_path)
    _make(tmp_path, "mls", "2026-08-15", mtime=time.time())
    worker._report_soccer_unit_outcome({"lastUnit": "mls|2026-08-15", "lastLaunchEpoch": time.time() - 60})
    out = capsys.readouterr().out
    assert "wrote_since_launch=True" in out


def test_an_absent_file_is_distinct_from_a_stale_one(worker, tmp_path, monkeypatch, capsys):
    # "never created" and "left untouched" are different bugs and must not
    # render the same way -- absent means the unit produced nothing at all.
    import syndicate.features.shared.refresh_state_store as store
    monkeypatch.setattr(store, "data_root", lambda: tmp_path)
    worker._report_soccer_unit_outcome({"lastUnit": "eredivisie|2026-08-14", "lastLaunchEpoch": time.time() - 60})
    out = capsys.readouterr().out
    assert "exists=False" in out
    assert "file_age_s=-1" in out


def test_no_status_yet_prints_nothing(worker, capsys):
    worker._report_soccer_unit_outcome({})
    assert capsys.readouterr().out == ""


def test_it_runs_before_the_gates_so_it_cannot_go_silent(worker):
    # An outcome that only prints when a NEW launch happens would go quiet
    # exactly when the units stop working.
    src = (pathlib.Path(__file__).resolve().parents[1] / "scripts" / "run_refresh_worker.py").read_text(encoding="utf-8")
    call = src.index("_report_soccer_unit_outcome(last_status)")
    units = src.index("units, scope_kind = _soccer_refresh_units(selected_date)")
    assert call < units, "the outcome report must run before the unit gates"


def test_the_key_separator_matches_soccer_unit_key(worker):
    """The bug this shipped with: I parsed `lastUnit` on ":" without reading
    `_soccer_unit_key`, which joins on "|". The split yielded no date, the guard
    returned early, and the diagnostic printed nothing on EVERY tick -- an
    instrument declining silently, which is the exact defect it exists to
    expose.
    """
    key = worker._soccer_unit_key({"league": "la_liga", "date": "2026-08-15"})
    assert key == "la_liga|2026-08-15"
    league, sep, date = key.partition("|")
    assert sep and league == "la_liga" and date == "2026-08-15"


def test_an_unparseable_key_says_so_rather_than_returning_silently(worker, capsys):
    worker._report_soccer_unit_outcome({"lastUnit": "nonsense", "lastLaunchEpoch": 1.0})
    assert "SOCCER_UNIT_OUTCOME_UNPARSED" in capsys.readouterr().out
