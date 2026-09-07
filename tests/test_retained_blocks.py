"""Per-route RETAINED pymalloc blocks. `#632`, lane `web-oom-pymalloc-trigger`.

`UPDATE 27` caught pymalloc arenas jumping +6/+13/+17/+18 MB in 1 MB units, so a
jump is a burst of SMALL-OBJECT allocations that outlives the free pools -- not
fragmentation. Finding which route does it needs per-request resolution, and
reading arena bytes costs 2.86 ms a side. `sys.getallocatedblocks()` is 0.679
microseconds and measures the CAUSE (live blocks) rather than the effect
(arenas), so it rides the existing solo-request path unconditionally.

These tests run the real allocator -- no mock can tell you whether the counter
actually tracks retention.
"""

from __future__ import annotations

import sys

import pytest

from syndicate.features.shared import memory_observability


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setenv("SYNDICATE_REQUEST_MEMORY_PROFILE", "on")
    # The solo path is gated on a readable per-process anon, which needs
    # /proc/self/smaps_rollup -- absent on every dev machine in this repo. The
    # coupling is deliberate (one code path, one solo window, and the
    # `unreadable` counter makes a failure visible), and it is pinned by
    # `test_blocks_stop_when_anon_becomes_unreadable` below.
    anon = {"v": 500.0}
    monkeypatch.setattr(memory_observability, "_process_anon_mb",
                        lambda: anon["v"])
    memory_observability.reset_request_memory_attribution()
    yield
    memory_observability.reset_request_memory_attribution()
    memory_observability._REQUEST_MEMORY_STATE["inflight"] = 0


def _request(route, body=None):
    """One solo request through the real entry/teardown pair."""
    token = memory_observability.note_request_start(route)
    held = body() if body is not None else None
    memory_observability.note_request_end(token, route, emit_every=10 ** 9)
    return held


# --- the counter itself ------------------------------------------------------

def test_the_counter_tracks_retention_not_churn():
    """The distinction the whole attribution rests on. Measured locally: a
    50,000-dict burst moved getallocatedblocks by +149,723, and after `del` it
    settled at +140. What a route RETAINS forces a new arena; what it allocates
    and frees inside its own window costs nothing."""
    before = memory_observability._allocated_blocks()
    churn = [{"k": i} for i in range(20000)]
    during = memory_observability._allocated_blocks()
    del churn
    after = memory_observability._allocated_blocks()
    assert during - before > 15000, "the burst must be visible"
    assert after - before < 1000, "freed blocks must not count as retained"


def test_it_reports_none_rather_than_zero_when_unavailable(monkeypatch):
    monkeypatch.delattr(sys, "getallocatedblocks", raising=True)
    assert memory_observability._allocated_blocks() is None


# --- per-route attribution ---------------------------------------------------

def test_a_route_that_retains_is_separated_from_one_that_does_not():
    keep: list = []
    _request("/keeps", lambda: keep.extend({"k": i} for i in range(20000)))
    _request("/churns", lambda: [{"k": i} for i in range(20000)] and None)

    routes = memory_observability._REQUEST_MEMORY_STATE["routes"]
    kept = routes["/keeps"]["blocks_total"]
    churned = routes["/churns"]["blocks_total"]
    assert kept > 15000, "a retaining route must show its blocks"
    assert churned < kept / 10, "a churning route must not look like a retaining one"
    assert keep  # keep the reference alive to the assertion


def test_repeated_requests_accumulate_and_track_n():
    held: list = []
    for _ in range(3):
        _request("/keeps", lambda: held.extend({"k": i} for i in range(5000)))
    row = memory_observability._REQUEST_MEMORY_STATE["routes"]["/keeps"]
    assert row["blocks_n"] == 3
    assert row["blocks_total"] > 12000
    assert row["blocks_max"] > 4000
    assert len(held) == 15000


def test_a_row_created_before_this_shipped_does_not_KeyError():
    # Rows persist across a deploy in a long-lived worker; the new keys are read
    # with .get defaults precisely so an old row cannot raise.
    state = memory_observability._REQUEST_MEMORY_STATE
    state["routes"]["/legacy"] = {"solo_n": 5, "total_mb": 1.0, "max_mb": 0.5}
    _request("/legacy")
    row = state["routes"]["/legacy"]
    assert row["solo_n"] == 6
    assert row["blocks_n"] == 1


# --- the discards, inherited from the anon path ------------------------------

def test_a_concurrent_request_is_not_attributed():
    outer = memory_observability.note_request_start("/outer")
    inner = memory_observability.note_request_start("/inner")
    assert inner is None, "a second in-flight request must not be attributed"
    memory_observability.note_request_end(inner, "/inner", emit_every=10 ** 9)
    memory_observability.note_request_end(outer, "/outer", emit_every=10 ** 9)
    routes = memory_observability._REQUEST_MEMORY_STATE["routes"]
    # The outer request was not alone throughout either, so neither is recorded.
    assert "/inner" not in routes
    assert routes.get("/outer", {}).get("blocks_n") is None


def test_a_background_iteration_disqualifies_the_window():
    memory_observability.note_background_work_start()
    token = memory_observability.note_request_start("/during-loop")
    assert token is None
    memory_observability.note_background_work_end()


def test_the_gc2_split_is_reported_separately(monkeypatch):
    """Split, do not exclude -- the rule the anon deltas already follow. A gen-2
    collection inside the window frees blocks the request never allocated, so
    those windows under-report retention and have to be countable apart."""
    gen2 = {"n": 0}
    monkeypatch.setattr(memory_observability, "_gc_gen2_collections",
                        lambda: gen2["n"])
    held: list = []
    _request("/clean", lambda: held.extend({"k": i} for i in range(5000)))

    def _collect_midway():
        # The counter has to rise INSIDE the window: `collected` is
        # `gc2_after > gc2_before`, so bumping it before the request would leave
        # both readings equal and the window would score as clean.
        held.extend({"k": i} for i in range(5000))
        gen2["n"] += 1

    _request("/collected", _collect_midway)

    split = memory_observability._BLOCKS_SPLIT_STATE
    assert split["no_gc2_n"] == 1
    assert split["with_gc2_n"] == 1
    assert split["no_gc2_blocks"] > 4000
    rows = memory_observability._REQUEST_MEMORY_STATE["routes"]
    assert rows["/clean"]["blocks_no_gc2_n"] == 1
    assert rows["/collected"]["blocks_gc2_n"] == 1
    # A gc2 window must NOT pollute the clean total, which is the number the
    # attribution is read off.
    assert "blocks_no_gc2_total" not in rows["/collected"]


# --- the report --------------------------------------------------------------

def test_the_payload_carries_the_blocks_split():
    held: list = []
    _request("/keeps", lambda: held.extend({"k": i} for i in range(5000)))
    payload = memory_observability.request_memory_attribution_payload()
    assert "blocks_split" in payload
    assert payload["blocks_split"]["no_gc2_n"] >= 1
    assert payload["solo_attributed"] >= 1


def test_reset_clears_the_blocks_state():
    held: list = []
    _request("/keeps", lambda: held.extend({"k": i} for i in range(5000)))
    assert memory_observability._BLOCKS_SPLIT_STATE["no_gc2_n"] == 1
    memory_observability.reset_request_memory_attribution()
    assert memory_observability._BLOCKS_SPLIT_STATE == {
        "with_gc2_n": 0, "with_gc2_blocks": 0, "no_gc2_n": 0, "no_gc2_blocks": 0}


def test_nothing_is_recorded_when_the_profile_is_off(monkeypatch):
    monkeypatch.delenv("SYNDICATE_REQUEST_MEMORY_PROFILE", raising=False)
    held: list = []
    _request("/keeps", lambda: held.extend({"k": i} for i in range(5000)))
    assert memory_observability._REQUEST_MEMORY_STATE["routes"] == {}


def test_blocks_stop_when_anon_becomes_unreadable(monkeypatch):
    """The coupling, stated so it cannot surprise anyone. Blocks ride the solo
    window, and that window is only opened when per-process anon reads. If
    smaps_rollup ever fails in production, block attribution stops with it --
    which the `unreadable` counter is there to make visible rather than silent."""
    monkeypatch.setattr(memory_observability, "_process_anon_mb", lambda: None)
    held: list = []
    _request("/keeps", lambda: held.extend({"k": i} for i in range(5000)))
    assert memory_observability._REQUEST_MEMORY_STATE["routes"] == {}
    assert memory_observability._REQUEST_MEMORY_STATE["unreadable"] >= 1
