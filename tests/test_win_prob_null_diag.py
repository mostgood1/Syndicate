"""Tests for the readable `win_prob` null-counter channel.

The counter these tests cover replaced one that was unobservable in production:
its `print()` went to a stdout that `refresh_odds_sources._run_command`
discards for a successful step. So the assertions that matter here are not
"does the arithmetic work" -- it is three lines of arithmetic -- but:

  1. a run's reading is READABLE AFTERWARD through the same path the ops route
     uses (writer and reader must agree on the key), and
  2. the PRODUCERS actually call the recorder. A library that works while
     nothing calls it is exactly the failure mode this whole lane exists to fix,
     so the wiring is asserted directly rather than inferred.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared import win_prob_null_diag as diag  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_reports_root(tmp_path, monkeypatch):
    # Filesystem backend against a temp root: the keyvalue path is the same code
    # in `write_json_file`, and pinning the root is what keeps one test's
    # readings out of another's.
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path))
    monkeypatch.setenv("SYNDICATE_REFRESH_STATE_BACKEND", "filesystem")
    monkeypatch.setenv("SYNDICATE_REFRESH_LANE", "live-odds-worker")
    yield


def test_reading_is_readable_after_a_run():
    written = diag.record(sport="wnba", tag="refresh_wnba_oddsapi_props", rows=15, nulls=0, date="2026-08-15")
    assert written is not None

    result = diag.read_all()
    assert result["readings"], "a recorded run must be visible to the reader"
    latest = result["readings"][0]["latest"]
    assert latest["rows"] == 15
    assert latest["null_no_price"] == 0
    assert latest["service"] == "live-odds-worker"
    assert latest["date"] == "2026-08-15"
    assert result["any_exercised"] is True


def test_writer_and_reader_agree_on_the_key():
    # The single most likely way this channel silently fails: the producer
    # writes one key and the route reads another, which renders as "the
    # producer never ran" rather than as a bug.
    diag.record(sport="wnba", tag="refresh_wnba_oddsapi_props", rows=3, nulls=1)
    expected = str(diag.diag_path("wnba", "live-odds-worker")).replace("\\", "/")
    probed = {entry["key_path"]: entry for entry in diag.read_all()["probed"]}
    assert expected in probed
    assert probed[expected]["present"] is True


def test_rows_zero_is_a_reading_not_a_confirmation():
    # NBA out of season: the producer reported, and computed nothing. That must
    # NOT read as "the fix is holding".
    diag.record(sport="nba", tag="refresh_nba_oddsapi_props", rows=0, nulls=0, date="2026-08-15")
    result = diag.read_all()
    assert result["readings"][0]["latest"]["exercised"] is False
    assert result["any_exercised"] is False
    assert "says nothing about the fix" in result["summary"]["interpretation"]


def test_no_reading_is_distinguishable_from_a_zero_reading():
    # An absent key is a fact about the emitter, never about the code.
    result = diag.read_all()
    assert result["readings"] == []
    assert result["summary"]["interpretation"] == "no producer has reported yet"
    # ...and the reader still says where it looked, so "nothing found" cannot be
    # confused with "looked in the wrong place".
    assert len(result["probed"]) >= len(diag.KNOWN_SPORTS)
    assert all(entry["present"] is False for entry in result["probed"])


def test_null_rows_report_a_rate_and_read_as_the_fix_working():
    diag.record(sport="wnba", tag="refresh_wnba_oddsapi_props", rows=8, nulls=2)
    result = diag.read_all()
    assert result["summary"]["pct"] == 25.0
    assert "published None instead of 0.5" in result["summary"]["interpretation"]


def test_per_service_keys_do_not_overwrite_each_other(monkeypatch):
    # `disk_maintenance._status_path` records what one shared key cost: both
    # workers share one Redis, so the second writer silently erased the first.
    diag.record(sport="wnba", tag="refresh_wnba_oddsapi_props", rows=15, nulls=0)
    monkeypatch.setenv("SYNDICATE_REFRESH_LANE", "refresh-worker")
    diag.record(sport="wnba", tag="refresh_wnba_oddsapi_props", rows=0, nulls=0)

    services = {entry["latest"]["service"]: entry["latest"] for entry in diag.read_all()["readings"]}
    assert services["live-odds-worker"]["rows"] == 15
    assert services["refresh-worker"]["rows"] == 0


def test_prior_runs_are_retained():
    diag.record(sport="wnba", tag="refresh_wnba_oddsapi_props", rows=1, nulls=0)
    diag.record(sport="wnba", tag="refresh_wnba_oddsapi_props", rows=2, nulls=0)
    entry = diag.read_all()["readings"][0]
    assert entry["latest"]["rows"] == 2
    assert entry["recent"][0]["rows"] == 1
    assert entry["runs_recorded"] == 2


def test_record_never_raises_and_never_breaks_the_run(monkeypatch):
    # It is called from the producers' `finally`, guarding the process exit code.
    def _boom(*args, **kwargs):
        raise RuntimeError("keyvalue is down")

    monkeypatch.setattr(diag, "write_json_file", _boom)
    assert diag.record(sport="wnba", tag="refresh_wnba_oddsapi_props", rows=5, nulls=1) is None


def test_a_failed_read_is_not_reported_as_an_absent_key(monkeypatch):
    def _unreadable(path):
        return None, False

    monkeypatch.setattr(diag, "read_json_file_result", _unreadable)
    result = diag.read_all()
    assert result["readings"] == []
    assert all(entry["read_failed"] is True for entry in result["probed"])


def _load_producer(script_name: str):
    spec = importlib.util.spec_from_file_location(f"_producer_{script_name}", REPO_ROOT / "scripts" / f"{script_name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("script_name", "sport"),
    [("refresh_wnba_oddsapi_props", "wnba"), ("refresh_nba_oddsapi_props", "nba")],
)
def test_producer_emit_actually_records(script_name, sport):
    # Asserts the BRANCH, not the outcome: the library being correct proves
    # nothing if the producer never reaches it, and that gap is precisely what
    # made the previous counter unreadable.
    module = _load_producer(script_name)
    module._WIN_PROB_STATS["rows"] = 4
    module._WIN_PROB_STATS["null_no_price"] = 1
    module._WIN_PROB_RUN_DATE["date"] = "2026-08-15"

    module._emit_win_prob_stats()

    readings = diag.read_all(sports=[sport])["readings"]
    assert readings, f"{script_name} must publish a readable reading"
    latest = readings[0]["latest"]
    assert latest["rows"] == 4
    assert latest["null_no_price"] == 1
    assert latest["date"] == "2026-08-15"
    assert latest["sport"] == sport
