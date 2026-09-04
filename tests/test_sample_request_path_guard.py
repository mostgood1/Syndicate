"""Tests for `scripts/sample_request_path_guard.py`.

These cover the two ways this measurement goes wrong in practice, both of which
already produced a bad number in this repo: differencing counters ACROSS
gunicorn workers, and quoting a per-minute rate off a couple of burst events.

No network. What is under test is the arithmetic, not the endpoint.
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import sample_request_path_guard as sampler  # noqa: E402

OP = "mlb_cards_fetch_current_feed_live"
T0 = dt.datetime(2026, 9, 4, 18, 42, 53, tzinfo=dt.timezone.utc)


def _sample(minutes: float, pid: int, count: int) -> dict:
    return {
        "at": (T0 + dt.timedelta(minutes=minutes)).isoformat(),
        "pid": pid,
        "warned": count,
        "refused": 0,
        "by_operation": {OP: count},
    }


def test_deltas_are_computed_within_a_pid_never_across_workers():
    """The real shape, 2026-09-04: pid 97 idle at 192 while pid 98 climbed
    176 -> 240. Differencing consecutive READS instead of per-pid series would
    have produced +16/-48/+64 nonsense, including negatives."""
    samples = [
        _sample(0.0, 97, 192), _sample(0.5, 98, 176), _sample(1.0, 97, 192),
        _sample(1.5, 98, 208), _sample(2.0, 97, 192), _sample(2.5, 98, 240),
    ]
    summary = sampler.summarise(samples, OP, min_events=1)

    assert summary["pids_observed"] == [97, 98]
    by_pid = {row["pid"]: row for row in summary["per_pid"]}
    assert by_pid[97]["delta"] == 0
    assert by_pid[98]["delta"] == 64
    assert summary["total_delta"] == 64
    assert summary["restarts"] == []


def test_a_rate_is_refused_below_the_event_floor():
    """The exact error this tool exists to stop me repeating. Two bursts read as
    8.7/min over 7.4 min and 5.4/min over 11.9 min -- same run, same events."""
    samples = [_sample(0.0, 98, 176), _sample(4.0, 98, 208), _sample(11.9, 98, 240)]
    summary = sampler.summarise(samples, OP, min_events=5)

    assert summary["increase_events"] == 2
    assert summary["rate_is_quotable"] is False
    # The arithmetic is still reported -- withholding it entirely would just
    # push the reader to compute it themselves, without the caveat.
    assert summary["rate_per_minute"] is not None
    assert summary["total_delta"] == 64


def test_a_rate_is_quotable_once_enough_events_accrue():
    samples = [_sample(i * 2.0, 98, 100 + i * 32) for i in range(7)]
    summary = sampler.summarise(samples, OP, min_events=5)

    assert summary["increase_events"] == 6
    assert summary["rate_is_quotable"] is True
    assert summary["total_delta"] == 192


def test_a_worker_restart_withholds_the_delta_instead_of_zeroing_it():
    """A counter that DECREASES means the process restarted. Treating that as
    'no work happened' would report a quiet window during a crash loop -- the
    exact false negative this repo keeps paying for."""
    samples = [_sample(0.0, 98, 500), _sample(1.0, 98, 532), _sample(2.0, 98, 16)]
    summary = sampler.summarise(samples, OP, min_events=1)

    row = summary["per_pid"][0]
    assert row["restarted"] is True
    assert row["delta"] is None, "a restart must withhold the delta, not report 16-500"
    assert summary["restarts"] and summary["restarts"][0]["pid"] == 98
    assert summary["total_delta"] == 0


def test_failed_reads_do_not_masquerade_as_zero_activity():
    """A read that errored is thinner coverage, not a quiet service."""
    samples = [
        _sample(0.0, 98, 176),
        {"at": (T0 + dt.timedelta(minutes=0.5)).isoformat(), "error": "URLError: timed out"},
        _sample(1.0, 98, 208),
    ]
    summary = sampler.summarise(samples, OP, min_events=1)

    assert summary["per_pid"][0]["samples"] == 2
    assert summary["total_delta"] == 32


def test_omitting_the_operation_measures_the_warned_total():
    samples = [_sample(0.0, 98, 10), _sample(1.0, 98, 40)]
    samples[0]["warned"], samples[1]["warned"] = 100, 150
    summary = sampler.summarise(samples, None, min_events=1)

    assert summary["operation"] == "(all warnings)"
    assert summary["total_delta"] == 50
