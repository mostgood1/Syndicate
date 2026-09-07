"""Tests for the growth-episode detector. `#632`, lane `web-oom-growth-episode`.

`UPDATE 26` closed the composition question and opened a narrower one: growth on
web is INTERMITTENT, and a 31-minute mature window did not reproduce an episode
at all. This catches one in the process.

The sizing is the part most likely to be wrong, so it is pinned by name below:
`UPDATE 23`'s episode was +42.4 MB over 31 min -- ~1.4 MB/min -- and a short
baseline with a large trigger would miss exactly that.
"""

from __future__ import annotations

import time

import pytest

from syndicate.features.shared import memory_observability


def _cap(t, anon, glibc=None, pymalloc=None):
    return {"t": t, "anon": anon, "glibc": glibc, "pymalloc": pymalloc}


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    memory_observability._GROWTH_EPISODE_STATE.update({
        "baseline": None, "last_check": 0.0, "episodes": [], "routes": {},
        "max_delta_mb": 0.0, "checks": 0, "pymalloc_budget": {"count": 0},
    })
    # Default the process PAST the warm-up, so a test opts IN to the boot-ramp
    # path rather than being silently blocked by it. Left the other way round,
    # every trigger test would pass for the wrong reason -- nothing fires during
    # warm-up, so "did not fire" would look like a working threshold.
    import os as _os
    memory_observability._GROWTH_EPISODE_AGE_STATE.update(
        {"pid": _os.getpid(), "t0": time.time() - 100_000.0})
    monkeypatch.delenv("SYNDICATE_GROWTH_EPISODE", raising=False)
    yield
    memory_observability._GROWTH_EPISODE_STATE.update({
        "baseline": None, "last_check": 0.0, "episodes": [], "routes": {},
        "max_delta_mb": 0.0, "checks": 0, "pymalloc_budget": {"count": 0},
    })


# --- the attribution ---------------------------------------------------------

def test_growth_is_split_across_the_terms_that_can_move():
    ep = memory_observability.build_growth_episode(
        _cap(1000.0, 500.0, glibc=390.0, pymalloc=100.0),
        _cap(1600.0, 540.0, glibc=428.0, pymalloc=102.0),
        {"/mlb/api/cards": 30, "/api/ops/memory": 4}, "/api/ops/memory")
    assert ep["anon_delta_mb"] == 40.0
    assert ep["glibc_delta_mb"] == 38.0
    assert ep["pymalloc_delta_mb"] == 2.0
    assert ep["unattributed_mb"] == 0.0
    assert ep["glibc_pct_of_growth"] == 95.0
    assert ep["dominant_term"] == "glibc"
    assert ep["reads_as"] == "attributed"
    assert ep["elapsed_s"] == 600.0
    assert ep["rate_mb_per_min"] == 4.0


def test_the_route_mix_is_reported_and_the_single_rule_is_labelled_as_not_a_cause():
    ep = memory_observability.build_growth_episode(
        _cap(0.0, 500.0, glibc=390.0, pymalloc=100.0),
        _cap(600.0, 540.0, glibc=428.0, pymalloc=102.0),
        {"/a": 30, "/b": 4}, "/b")
    assert ep["routes_since_baseline"] == {"/a": 30, "/b": 4}
    assert ep["route_requests_total"] == 34
    assert ep["observed_at_route"] == "/b"
    # The rule in flight at the crossing is whichever request happened to finish
    # there, not the allocator. The output has to say so.
    assert "NOT the allocator" in ep["observed_at_route_note"]


def test_an_unattributed_majority_says_the_cheap_capture_is_insufficient():
    # `.so` private-dirty and the main stack are NOT read here -- that needs
    # smaps, which is O(regions). If either drifts from the constant it measured
    # as, it lands in unattributed, and that is a finding rather than a bucket.
    ep = memory_observability.build_growth_episode(
        _cap(0.0, 500.0, glibc=390.0, pymalloc=100.0),
        _cap(600.0, 560.0, glibc=395.0, pymalloc=101.0),
        {}, None)
    assert ep["unattributed_mb"] == 54.0
    assert ep["dominant_term"] == "unattributed"
    assert ep["reads_as"] == "unattributed_dominant"
    assert "smaps partition has to come back" in ep["why"]


def test_a_missing_allocator_reading_is_incomplete_not_zero():
    ep = memory_observability.build_growth_episode(
        _cap(0.0, 500.0, glibc=390.0, pymalloc=None),
        _cap(600.0, 540.0, glibc=428.0, pymalloc=None),
        {}, None)
    assert ep["pymalloc_delta_mb"] is None
    assert ep["reads_as"] == "incomplete"


def test_pymalloc_dominant_would_falsify_the_lane_hypothesis():
    # The lane predicts glibc. This is the shape that refutes it.
    ep = memory_observability.build_growth_episode(
        _cap(0.0, 500.0, glibc=390.0, pymalloc=100.0),
        _cap(600.0, 540.0, glibc=392.0, pymalloc=138.0),
        {}, None)
    assert ep["dominant_term"] == "pymalloc"
    assert ep["pymalloc_pct_of_growth"] == 95.0


# --- the trigger, and the sizing that decides what it can see -----------------

def test_a_slow_climb_of_the_update_23_shape_still_fires(monkeypatch):
    """UPDATE 23's episode was +42.4 MB over 31 min = ~1.4 MB/min. A 5-minute
    baseline with a 20 MB trigger sees ~7 MB of that and MISSES the thing being
    hunted. With the shipped defaults -- 15 min baseline, 15 MB trigger -- a
    1.4 MB/min climb crosses at ~11 minutes."""
    monkeypatch.setenv("SYNDICATE_GROWTH_EPISODE", "1")
    monkeypatch.setenv("SYNDICATE_GROWTH_EPISODE_CHECK_SECONDS", "0")
    anon = {"v": 500.0}
    monkeypatch.setattr(memory_observability, "_process_anon_mb", lambda: anon["v"])
    monkeypatch.setattr(memory_observability, "glibc_mallinfo2",
                        lambda: {"available": True, "glibc_total_mb": anon["v"] - 110.0})
    monkeypatch.setattr(memory_observability, "log_pymalloc_arena_stats",
                        lambda *a, **k: {"arena_mb": 100.0})

    memory_observability.maybe_capture_growth_episode("/mlb/api/cards")  # baseline
    fired = None
    for minute in range(1, 16):
        anon["v"] = 500.0 + 1.4 * minute
        fired = memory_observability.maybe_capture_growth_episode("/mlb/api/cards")
        if fired:
            break
    assert fired is not None, "a 1.4 MB/min climb must fire on the shipped defaults"
    assert fired["anon_delta_mb"] >= 15.0
    assert fired["dominant_term"] == "glibc"


def test_below_the_trigger_nothing_fires_but_the_rise_is_still_recorded(monkeypatch):
    monkeypatch.setenv("SYNDICATE_GROWTH_EPISODE", "1")
    monkeypatch.setenv("SYNDICATE_GROWTH_EPISODE_CHECK_SECONDS", "0")
    anon = {"v": 500.0}
    monkeypatch.setattr(memory_observability, "_process_anon_mb", lambda: anon["v"])
    monkeypatch.setattr(memory_observability, "glibc_mallinfo2",
                        lambda: {"available": True, "glibc_total_mb": 390.0})
    monkeypatch.setattr(memory_observability, "log_pymalloc_arena_stats",
                        lambda *a, **k: {"arena_mb": 100.0})
    memory_observability.maybe_capture_growth_episode("/x")
    anon["v"] = 508.0
    assert memory_observability.maybe_capture_growth_episode("/x") is None
    # THE FIELD THAT MAKES A NULL READABLE: zero episodes at 1.2 MB means flat,
    # zero at 14.8 MB means the trigger is mis-sized. Without it they look alike.
    report = memory_observability.growth_episode_report()
    assert report["episodes_captured"] == 0
    assert report["max_anon_rise_seen_mb"] == pytest.approx(8.0, abs=0.1)


def test_a_restart_rebaselines_instead_of_recording_a_negative_episode(monkeypatch):
    monkeypatch.setenv("SYNDICATE_GROWTH_EPISODE", "1")
    monkeypatch.setenv("SYNDICATE_GROWTH_EPISODE_CHECK_SECONDS", "0")
    anon = {"v": 600.0}
    monkeypatch.setattr(memory_observability, "_process_anon_mb", lambda: anon["v"])
    monkeypatch.setattr(memory_observability, "glibc_mallinfo2",
                        lambda: {"available": True, "glibc_total_mb": 390.0})
    monkeypatch.setattr(memory_observability, "log_pymalloc_arena_stats",
                        lambda *a, **k: {"arena_mb": 100.0})
    memory_observability.maybe_capture_growth_episode("/x")
    anon["v"] = 120.0                      # a fresh process
    memory_observability.maybe_capture_growth_episode("/x")
    state = memory_observability._GROWTH_EPISODE_STATE
    assert state["baseline"]["anon"] == 120.0
    assert state["episodes"] == []


def test_the_clock_gate_is_claimed_before_the_expensive_work(monkeypatch):
    monkeypatch.setenv("SYNDICATE_GROWTH_EPISODE", "1")
    monkeypatch.setenv("SYNDICATE_GROWTH_EPISODE_CHECK_SECONDS", "600")
    calls = []
    monkeypatch.setattr(memory_observability, "_process_anon_mb",
                        lambda: (calls.append(1), 500.0)[1])
    monkeypatch.setattr(memory_observability, "glibc_mallinfo2",
                        lambda: {"available": True, "glibc_total_mb": 390.0})
    monkeypatch.setattr(memory_observability, "log_pymalloc_arena_stats",
                        lambda *a, **k: {"arena_mb": 100.0})
    for _ in range(25):
        memory_observability.maybe_capture_growth_episode("/x")
    assert len(calls) == 1, "the per-request path must be one clock comparison"


def test_routes_are_counted_on_every_request_not_only_on_a_check(monkeypatch):
    monkeypatch.setenv("SYNDICATE_GROWTH_EPISODE", "1")
    monkeypatch.setenv("SYNDICATE_GROWTH_EPISODE_CHECK_SECONDS", "600")
    monkeypatch.setattr(memory_observability, "_process_anon_mb", lambda: 500.0)
    monkeypatch.setattr(memory_observability, "glibc_mallinfo2",
                        lambda: {"available": True, "glibc_total_mb": 390.0})
    monkeypatch.setattr(memory_observability, "log_pymalloc_arena_stats",
                        lambda *a, **k: {"arena_mb": 100.0})
    for _ in range(7):
        memory_observability.maybe_capture_growth_episode("/mlb/api/cards")
    for _ in range(3):
        memory_observability.maybe_capture_growth_episode("/nba/api/cards")
    # SIX, not seven. The first call establishes the baseline, and rebasing
    # clears the table -- correctly, because the counts are "since baseline" and
    # that request happened before one existed. Worth pinning: an off-by-one here
    # would be invisible in production and would quietly misweight the route mix
    # that an episode reports.
    assert memory_observability._GROWTH_EPISODE_STATE["routes"] == {
        "/mlb/api/cards": 6, "/nba/api/cards": 3}


def test_the_route_table_is_capped(monkeypatch):
    monkeypatch.setenv("SYNDICATE_GROWTH_EPISODE", "1")
    monkeypatch.setenv("SYNDICATE_GROWTH_EPISODE_CHECK_SECONDS", "600")
    monkeypatch.setattr(memory_observability, "_process_anon_mb", lambda: 500.0)
    for i in range(200):
        memory_observability.maybe_capture_growth_episode("/route/%d" % i)
    assert (len(memory_observability._GROWTH_EPISODE_STATE["routes"])
            <= memory_observability._GROWTH_EPISODE_ROUTE_CAP)


def test_the_episode_ring_is_bounded(monkeypatch):
    state = memory_observability._GROWTH_EPISODE_STATE
    state["episodes"] = [{"n": i} for i in range(50)]
    del state["episodes"][:-memory_observability._GROWTH_EPISODE_MAX_KEPT]
    assert len(state["episodes"]) == memory_observability._GROWTH_EPISODE_MAX_KEPT
    assert state["episodes"][-1] == {"n": 49}


# --- the gate and the failure modes ------------------------------------------

def test_off_by_default_and_does_no_work(monkeypatch):
    calls = []
    monkeypatch.setattr(memory_observability, "_process_anon_mb",
                        lambda: (calls.append(1), 500.0)[1])
    assert memory_observability.growth_episode_enabled() is False
    assert memory_observability.maybe_capture_growth_episode("/x") is None
    assert calls == []


def test_it_never_raises(monkeypatch):
    monkeypatch.setenv("SYNDICATE_GROWTH_EPISODE", "1")
    monkeypatch.setenv("SYNDICATE_GROWTH_EPISODE_CHECK_SECONDS", "0")

    def _boom():
        raise RuntimeError("procfs gone")

    monkeypatch.setattr(memory_observability, "_process_anon_mb", _boom)
    assert memory_observability.maybe_capture_growth_episode("/x") is None


def test_report_is_readable_before_anything_has_happened():
    report = memory_observability.growth_episode_report()
    assert report["episodes_captured"] == 0
    assert report["baseline_age_s"] is None
    assert report["max_anon_rise_seen_mb"] == 0.0
    assert report["trigger_mb"] == 15.0


# --- the warm-up: skip the boot ramp -----------------------------------------

def test_the_boot_ramp_does_not_fire(monkeypatch):
    """Measured in production 2026-09-07: the detector fired 18.4 s after boot on
    +230.3 MB at 750 MB/min, with `/` and `/healthz` the only routes -- five
    platform health checks. That is the boot ramp, a phase UPDATE 25/26 already
    measured, and catching it cost the episode slot AND polluted
    max_anon_rise_seen_mb. The phenomenon being hunted runs at ~1.4 MB/min."""
    monkeypatch.setenv("SYNDICATE_GROWTH_EPISODE", "1")
    monkeypatch.setenv("SYNDICATE_GROWTH_EPISODE_CHECK_SECONDS", "0")
    anon = {"v": 99.3}
    monkeypatch.setattr(memory_observability, "_process_anon_mb", lambda: anon["v"])
    monkeypatch.setattr(memory_observability, "glibc_mallinfo2",
                        lambda: {"available": True, "glibc_total_mb": anon["v"] * 0.6})
    monkeypatch.setattr(memory_observability, "log_pymalloc_arena_stats",
                        lambda *a, **k: {"arena_mb": anon["v"] * 0.35})
    # A process seconds old, exactly as in the production capture.
    memory_observability._GROWTH_EPISODE_AGE_STATE.update(
        {"pid": __import__("os").getpid(), "t0": time.time() - 18.0})

    memory_observability.maybe_capture_growth_episode("/healthz")
    anon["v"] = 329.7
    assert memory_observability.maybe_capture_growth_episode("/healthz") is None
    report = memory_observability.growth_episode_report()
    assert report["episodes_captured"] == 0
    # The field that distinguishes flat from mis-sized stays clean.
    assert report["max_anon_rise_seen_mb"] == 0.0
    assert report["warmup_remaining_s"] > 0


def test_after_the_warmup_the_same_rise_does_fire(monkeypatch):
    monkeypatch.setenv("SYNDICATE_GROWTH_EPISODE", "1")
    monkeypatch.setenv("SYNDICATE_GROWTH_EPISODE_CHECK_SECONDS", "0")
    anon = {"v": 500.0}
    monkeypatch.setattr(memory_observability, "_process_anon_mb", lambda: anon["v"])
    monkeypatch.setattr(memory_observability, "glibc_mallinfo2",
                        lambda: {"available": True, "glibc_total_mb": anon["v"] - 110.0})
    monkeypatch.setattr(memory_observability, "log_pymalloc_arena_stats",
                        lambda *a, **k: {"arena_mb": 100.0})
    memory_observability._GROWTH_EPISODE_AGE_STATE.update(
        {"pid": __import__("os").getpid(), "t0": time.time() - 2000.0})

    memory_observability.maybe_capture_growth_episode("/mlb/api/cards")
    anon["v"] = 530.0
    fired = memory_observability.maybe_capture_growth_episode("/mlb/api/cards")
    assert fired is not None
    assert fired["anon_delta_mb"] == 30.0
    # Age is stamped on the episode so a ramp-TAIL capture stays identifiable:
    # the arena is still filling until ~30 min.
    assert fired["process_age_s"] > 1900


def test_process_age_is_per_pid_not_inherited_from_import(monkeypatch):
    """gunicorn forks AFTER import, so anything captured at module scope belongs
    to the parent. That trap shipped `proc_token` inert earlier in #632, with
    pids 99 and 98 sharing one token."""
    import os as _os
    memory_observability._GROWTH_EPISODE_AGE_STATE.update({"pid": -1, "t0": 0.0})
    age = memory_observability._growth_process_age_s()
    assert age < 5.0, "a new pid must re-derive its own t0, not inherit one"
    assert memory_observability._GROWTH_EPISODE_AGE_STATE["pid"] == _os.getpid()


def test_the_latest_triple_is_published_whether_or_not_it_fires(monkeypatch):
    """A rate comparison needs the pymalloc arena size CONTINUOUSLY, not only
    inside an episode. The triple is already taken every interval, so publishing
    it adds no measurement -- and without it, toggling another flag and re-reading
    the arena rate would need a second instrument."""
    monkeypatch.setenv("SYNDICATE_GROWTH_EPISODE", "1")
    monkeypatch.setenv("SYNDICATE_GROWTH_EPISODE_CHECK_SECONDS", "0")
    monkeypatch.setattr(memory_observability, "_process_anon_mb", lambda: 500.0)
    monkeypatch.setattr(memory_observability, "glibc_mallinfo2",
                        lambda: {"available": True, "glibc_total_mb": 390.0})
    monkeypatch.setattr(memory_observability, "log_pymalloc_arena_stats",
                        lambda *a, **k: {"arena_mb": 162.0})
    memory_observability.maybe_capture_growth_episode("/x")
    report = memory_observability.growth_episode_report()
    assert report["episodes_captured"] == 0, "nothing should have fired"
    cap = report["last_capture"]
    assert cap["anon"] == 500.0
    assert cap["glibc"] == 390.0
    assert cap["pymalloc"] == 162.0
