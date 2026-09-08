"""`#632`: the chip publisher's GATES are the thing worth testing.

This adds periodic work to a 4 GB worker with an OOM history, and `#241` is the
precedent where exactly that caused a restart loop. So the tests that matter are
not "does it publish" but "does it REFUSE, for each reason, and say which".

Measured cause, for whoever reads this later: consecutive `GAME_CHIPS_PUBLISHED`
for the one date web reads ran a 24.1 minute median (range 12.6-32.2) against the
endpoint's 120 s threshold, because chips were published once per
`build_layer2_shortlist` and depend on none of it.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared import game_chip_publisher as pub


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    pub._reset_for_tests()
    monkeypatch.delenv("SYNDICATE_GAME_CHIP_PUBLISH_SECONDS", raising=False)
    monkeypatch.delenv("SYNDICATE_GAME_CHIP_PUBLISH_ENABLED", raising=False)
    yield
    pub._reset_for_tests()


def _ok_headroom(_min_bytes):
    return {"sufficient": True, "headroom_mb": 3400.0}


def _call(**kw):
    kw.setdefault("headroom", _ok_headroom)
    kw.setdefault("today", lambda: "2026-09-08")
    kw.setdefault("sports", ["mlb"])
    return pub.maybe_publish_game_chips(**kw)


def test_it_publishes_and_records_the_date_and_count():
    written = {}
    out = _call(now=1000.0,
                build=lambda d, s: [{"sport": "mlb"}, {"sport": "mlb"}],
                write=lambda d, c: written.update({"date": d, "n": len(c)}))
    assert out == {"date": "2026-09-08", "chips": 2, "gap_seconds": None}
    assert written == {"date": "2026-09-08", "n": 2}
    assert pub.publisher_state()["publishes"] == 1


def test_the_interval_gate_blocks_a_second_publish_and_then_releases():
    calls = {"n": 0}

    def build(d, s):
        calls["n"] += 1
        return [{"sport": "mlb"}]

    assert _call(now=1000.0, build=build, write=lambda d, c: None) is not None
    # 119 s later: inside the 120 s default, refused.
    assert _call(now=1119.0, build=build, write=lambda d, c: None) is None
    assert calls["n"] == 1, "a refused tick must not pay for the build"
    # 121 s later: released, and the gap is reported.
    out = _call(now=1121.0, build=build, write=lambda d, c: None)
    assert out is not None and out["gap_seconds"] == pytest.approx(121.0)
    assert calls["n"] == 2
    assert pub.publisher_state()["skips"].get("interval") == 1


def test_INSUFFICIENT_headroom_refuses_and_never_builds():
    calls = {"n": 0}

    def build(d, s):
        calls["n"] += 1
        return [{"sport": "mlb"}]

    assert _call(now=1000.0, headroom=lambda _b: {"sufficient": False, "headroom_mb": 120.0},
                 build=build, write=lambda d, c: None) is None
    assert calls["n"] == 0, "the guard must refuse BEFORE paying for the fan-out"
    assert pub.publisher_state()["skips"].get("headroom") == 1


def test_UNMEASURABLE_headroom_counts_as_INSUFFICIENT():
    """`memory_headroom_snapshot` returns None when it cannot read the cgroup.
    Mapping unknown onto the permissive branch is how a failed read silently
    becomes a relaxed rule -- and this runs on the service with the OOM history."""
    calls = {"n": 0}

    def build(d, s):
        calls["n"] += 1
        return [{"sport": "mlb"}]

    assert _call(now=1000.0, headroom=lambda _b: None,
                 build=build, write=lambda d, c: None) is None
    assert calls["n"] == 0
    assert pub.publisher_state()["skips"].get("headroom") == 1


def test_an_EMPTY_build_is_not_published():
    """Overwriting a good artifact with zero chips blanks every sport's strip,
    and a chip-less strip is indistinguishable from a sport with no games."""
    wrote = {"n": 0}
    assert _call(now=1000.0, build=lambda d, s: [],
                 write=lambda d, c: wrote.update({"n": wrote["n"] + 1})) is None
    assert wrote["n"] == 0
    assert pub.publisher_state()["skips"].get("empty_build") == 1


def test_a_raising_build_never_propagates_into_the_worker_loop():
    def boom(d, s):
        raise RuntimeError("provider registry down")

    assert _call(now=1000.0, build=boom, write=lambda d, c: None) is None
    assert pub.publisher_state()["skips"].get("RuntimeError") == 1
    # And it must not have poisoned the clock: the next tick may still publish.
    out = _call(now=1001.0, build=lambda d, s: [{"sport": "mlb"}], write=lambda d, c: None)
    assert out is not None


def test_a_raising_WRITE_does_not_advance_the_clock_into_a_lie():
    def bad_write(d, c):
        raise IOError("disk full")

    assert _call(now=1000.0, build=lambda d, s: [{"sport": "mlb"}], write=bad_write) is None
    # `last_publish_at` must NOT have moved -- a failed write is not a publish,
    # and stamping it would suppress the next attempt for a full interval
    # precisely when the artifact is stale.
    assert pub.publisher_state()["last_publish_at"] == 0.0
    assert pub.publisher_state()["publishes"] == 0


def test_only_ONE_date_is_published_and_it_is_the_one_web_reads():
    seen = []
    _call(now=1000.0, today=lambda: "2026-09-08",
          build=lambda d, s: [{"sport": "mlb"}], write=lambda d, c: seen.append(d))
    assert seen == ["2026-09-08"], "publishing a second date doubles the cost for a date nobody serves"


def test_an_empty_date_refuses_rather_than_writing_to_an_empty_key():
    wrote = []
    assert _call(now=1000.0, today=lambda: "  ",
                 build=lambda d, s: [{"sport": "mlb"}], write=lambda d, c: wrote.append(d)) is None
    assert wrote == []
    assert pub.publisher_state()["skips"].get("no_date") == 1


def test_the_interval_has_a_FLOOR_so_config_cannot_become_a_duty_cycle_change(monkeypatch):
    monkeypatch.setenv("SYNDICATE_GAME_CHIP_PUBLISH_SECONDS", "5")
    assert pub.publish_interval_seconds() == 60.0
    monkeypatch.setenv("SYNDICATE_GAME_CHIP_PUBLISH_SECONDS", "nonsense")
    assert pub.publish_interval_seconds() == 120.0
    monkeypatch.setenv("SYNDICATE_GAME_CHIP_PUBLISH_SECONDS", "300")
    assert pub.publish_interval_seconds() == 300.0


def test_it_can_be_turned_off_without_a_deploy(monkeypatch):
    monkeypatch.setenv("SYNDICATE_GAME_CHIP_PUBLISH_ENABLED", "false")
    assert _call(now=1000.0, build=lambda d, s: [{"sport": "mlb"}], write=lambda d, c: None) is None
    assert pub.publisher_state()["skips"].get("disabled") == 1


def test_absent_flag_means_ON_and_the_default_is_stated(monkeypatch):
    # Absent must not silently mean off -- that is how a shipped fix stays inert.
    monkeypatch.delenv("SYNDICATE_GAME_CHIP_PUBLISH_ENABLED", raising=False)
    assert pub.enabled() is True
    assert pub.publish_interval_seconds() == 120.0


# --- the thread: the cadence fix only works if it has its OWN clock -----------

def test_the_thread_starts_once_and_is_idempotent():
    """It is bootstrapped from the worker's loop tick, which fires on every
    iteration, so starting a second thread per tick would be a duty-cycle bug."""
    import threading as _t
    try:
        assert pub.ensure_publisher_thread() is True
        first = pub._thread
        for _ in range(5):
            assert pub.ensure_publisher_thread() is True
        assert pub._thread is first, "a second thread per tick would multiply the work"
        assert first.daemon, "a non-daemon thread would block worker shutdown"
        assert first.name == "game-chip-publisher"
        assert sum(1 for th in _t.enumerate() if th.name == "game-chip-publisher") == 1
    finally:
        pub.stop_publisher_thread()


def test_the_thread_does_not_start_when_disabled(monkeypatch):
    monkeypatch.setenv("SYNDICATE_GAME_CHIP_PUBLISH_ENABLED", "false")
    try:
        assert pub.ensure_publisher_thread() is False
        assert pub._thread is None
    finally:
        pub.stop_publisher_thread()


def test_stop_is_safe_to_call_twice_and_when_never_started():
    pub.stop_publisher_thread()
    pub.stop_publisher_thread()
    assert pub._thread is None


def test_a_dead_thread_is_replaced_rather_than_leaving_the_publisher_silent():
    try:
        assert pub.ensure_publisher_thread() is True
        pub.stop_publisher_thread()          # clears the handle
        assert pub._thread is None
        # The next loop tick must bring it back, or one crash silences chip
        # publishing for the life of the worker.
        assert pub.ensure_publisher_thread() is True
        assert pub._thread is not None and pub._thread.is_alive()
    finally:
        pub.stop_publisher_thread()


def test_the_thread_ACTUALLY_CALLS_the_publisher_on_its_own_clock(monkeypatch):
    """THE REACHABILITY TEST. Starting a thread proves a thread exists, not that
    it does the work -- and the whole point of the thread is that the worker's
    own tick (1-18 min, median ~15) is too slow to carry this."""
    import time as _time
    calls = {"n": 0}

    def fake_publish(**_kw):
        calls["n"] += 1
        return None

    monkeypatch.setattr(pub, "maybe_publish_game_chips", fake_publish)
    monkeypatch.setattr(pub, "publish_interval_seconds", lambda: 10.0)  # -> 5 s poll
    try:
        assert pub.ensure_publisher_thread() is True
        deadline = _time.time() + 8.0
        while calls["n"] < 2 and _time.time() < deadline:
            _time.sleep(0.1)
        assert calls["n"] >= 2, (
            "the thread must call the publisher REPEATEDLY on its own clock; "
            f"got {calls['n']} calls in 8 s"
        )
    finally:
        pub.stop_publisher_thread()


def test_stopping_the_thread_actually_stops_the_calls(monkeypatch):
    import time as _time
    calls = {"n": 0}
    monkeypatch.setattr(pub, "maybe_publish_game_chips",
                        lambda **_k: calls.__setitem__("n", calls["n"] + 1))
    monkeypatch.setattr(pub, "publish_interval_seconds", lambda: 10.0)
    pub.ensure_publisher_thread()
    _time.sleep(0.5)
    pub.stop_publisher_thread()
    settled = calls["n"]
    _time.sleep(1.0)
    assert calls["n"] == settled, "a stopped thread must not keep doing worker work"
