"""`#600` -- FORCE the collision, because 68 minutes of real traffic would not.

MEASURED 2026-08-29 04:53Z, both writers, 20 polls over 68 minutes:
**59 settlement lines, 49 execute lines, ZERO `LEDGER_MERGE`.** The machinery
that could collide was demonstrably running and no collision happened.

WHY THAT NULL IS NOT A PASS, and why this file exists. `_merge_onto_current`
runs on EVERY persist -- only the LOG at `execution_ledger.py:645` is
conditional. So in production the merge is reachable, running, and finding
nothing to merge, while **its CONFLICT branch has never once executed**. The
three-way rules the whole fix exists for are, in production, untested code.

`test_execution_ledger_concurrent_writers.py` covers those rules, but it hands
`_merge_onto_current` a baseline it constructed itself. That proves the
FUNCTION is right; it does not prove the GAP is where we think it is, or that a
second writer landing in that gap actually reaches the branch. This file races
real threads through the real `_load()` -> `_persist()` path instead.

THE COLLISION IS FORCED, NOT HOPED FOR. Every test synchronises on
`threading.Event` so the intruder's persist lands strictly inside the slow
writer's window -- no sleeps, no timing luck. And the two that can, assert
`concurrent >= 1`, because **a concurrency test that passes because the threads
never overlapped is worse than no test**: it reports green for the one
condition it was written to create.
"""

from __future__ import annotations

import threading

import pytest

from syndicate.features.shared import execution_ledger as ledger


@pytest.fixture(autouse=True)
def _isolated_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path))
    monkeypatch.delenv("SYNDICATE_REFRESH_STATE_BACKEND", raising=False)
    yield


def _order(key, **kw):
    o = {"idempotency_key": key, "status": "filled", "selected_date": "2026-08-26"}
    o.update(kw)
    return o


def _seed(*keys):
    state = ledger._load()
    state["orders"] = [_order(k) for k in keys]
    ledger._persist(state)


def _stored():
    return {o["idempotency_key"]: o for o in ledger._load()["orders"]}


def _merge_lines(capsys):
    return [l for l in capsys.readouterr().out.splitlines() if "LEDGER_MERGE" in l]


def _concurrent_from(lines):
    """The `concurrent=N` the merge actually reported."""
    for line in lines:
        for tok in line.split():
            if tok.startswith("concurrent="):
                return int(tok.split("=", 1)[1])
    return 0


def _race(slow_edit, intruder, *, timeout=15):
    """Run `slow_edit` across a gap that `intruder` writes into.

    The slow writer loads, WAITS, then edits and persists. The intruder gets a
    complete independent read-modify-write inside that window. Deterministic:
    the intruder cannot finish before the load, and the persist cannot start
    before the intruder is done.
    """
    loaded = threading.Event()
    intruder_done = threading.Event()
    failure = []

    def _slow():
        try:
            state = ledger._load()          # baseline captured HERE
            loaded.set()
            if not intruder_done.wait(timeout):
                failure.append("intruder never signalled")
                return
            slow_edit(state)
            ledger._persist(state)          # merge happens HERE
        except Exception as exc:            # surfaced, never swallowed
            failure.append(f"{type(exc).__name__}: {exc}")

    t = threading.Thread(target=_slow)
    t.start()
    assert loaded.wait(timeout), "slow writer never loaded"
    intruder()
    intruder_done.set()
    t.join(timeout + 5)
    assert not t.is_alive(), "slow writer hung"
    assert not failure, failure


# ---------------------------------------------------------------------------
# THE GAP, FORCED OPEN
# ---------------------------------------------------------------------------


def test_a_FORCED_collision_actually_EXECUTES_the_merge_branch(capsys):
    """THE TEST THIS FILE EXISTS FOR.

    `LEDGER_MERGE` has never been emitted in production. Here it must be, or
    the conflict branch is still unexecuted and `#600` is still unverified at
    the mechanism level.
    """
    _seed("a", "b")

    def slow_edit(state):
        for o in state["orders"]:
            if o["idempotency_key"] == "a":
                o["outcome"] = "won"

    def intruder():
        # MODIFIES AN EXISTING ROW, and that detail is the whole finding below.
        other = ledger._load()
        for o in other["orders"]:
            if o["idempotency_key"] == "b":
                o["outcome"] = "lost"
        ledger._persist(other)

    _race(slow_edit, intruder)

    lines = _merge_lines(capsys)
    assert lines, "LEDGER_MERGE was NOT emitted -- the conflict branch did not run"
    assert _concurrent_from(lines) >= 1, (
        "merge ran but reported concurrent=0, so the threads did not actually "
        f"overlap and this test proves nothing: {lines}"
    )


def test_an_ADDITION_ONLY_race_is_MERGED_but_never_LOGGED():
    """A BLIND SPOT IN THE INSTRUMENT, found by this file and not by 68 minutes
    of production traffic.

    `counts["concurrent"]` increments only when a row **already in our
    baseline** has a different fingerprint now (`execution_ledger.py:443`). An
    intruder that only APPENDS rows never trips it -- `was is None` -- so the
    merge silently rescues the addition and `LEDGER_MERGE` is never printed.

    **THIS INVALIDATES THE OBVIOUS READING OF THE PRODUCTION NULL.** "Zero
    `LEDGER_MERGE` in 68 minutes" was reported as "no collisions happened". It
    actually means "no other writer MODIFIED a row we had loaded". A placement
    cycle appending orders while settlement holds a snapshot is exactly an
    addition-only race, it IS being merged, and it logs nothing.

    Asserted rather than fixed: making the log fire on every rescue was
    considered and rejected in `_persist`'s own comment ("a line on every write
    would be constant noise"). The defect is the INFERENCE drawn from silence,
    not the silence.
    """
    _seed("a", "b")
    captured: list[str] = []

    def slow_edit(state):
        for o in state["orders"]:
            if o["idempotency_key"] == "a":
                o["outcome"] = "won"

    def intruder():
        other = ledger._load()
        other["orders"].append(_order("added_by_other"))
        ledger._persist(other)

    import io
    import contextlib

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        _race(slow_edit, intruder)
    captured.extend(buf.getvalue().splitlines())

    stored = _stored()
    # The merge DID its job...
    assert "added_by_other" in stored, "the addition was clobbered"
    assert stored["a"].get("outcome") == "won", "our grade was lost"
    # ...and said nothing about it.
    assert not [l for l in captured if "LEDGER_MERGE" in l], (
        "addition-only races now log -- good, but update the production "
        "interpretation in `#600` and delete this test's premise"
    )


def test_NEITHER_writer_loses_its_write_in_a_forced_collision():
    """The production symptom: nine grades gone 12 seconds after landing."""
    _seed("a", "b")

    def slow_edit(state):
        for o in state["orders"]:
            if o["idempotency_key"] == "a":
                o["outcome"] = "won"

    def intruder():
        other = ledger._load()
        other["orders"].append(_order("c"))
        ledger._persist(other)

    _race(slow_edit, intruder)

    stored = _stored()
    assert stored["a"].get("outcome") == "won", "the slow writer's grade was lost"
    assert "c" in stored, "the intruder's new order was clobbered"
    assert "b" in stored, "an untouched row disappeared"


def test_THE_PRODUCTION_SHAPE_settlement_grading_races_a_placement_cycle():
    """The exact pairing the watcher waited for and never saw: a settlement
    pass grading existing rows while a placement cycle appends a new one. 59
    settlement lines and 49 execute lines in 68 minutes produced no collision;
    this produces it deliberately."""
    _seed("bet1", "bet2", "bet3")

    def slow_edit(state):
        for o in state["orders"]:
            o["outcome"] = "won"
            o["settled_value"] = 153.0

    def intruder():
        cycle = ledger._load()
        cycle["orders"].append(_order("bet4"))
        ledger._persist(cycle)

    _race(slow_edit, intruder)

    stored = _stored()
    assert len(stored) == 4, f"expected 4 orders, got {sorted(stored)}"
    for key in ("bet1", "bet2", "bet3"):
        assert stored[key].get("outcome") == "won", f"{key} lost its grade"
    assert "bet4" in stored, "the placement was clobbered by the settlement write"


def test_SIX_writers_racing_the_same_gap_all_survive(capsys):
    """One collision could be luck in the merge's favour. Six intruders inside
    one writer's window is closer to the shape a busy slate has."""
    _seed("base")

    def slow_edit(state):
        for o in state["orders"]:
            if o["idempotency_key"] == "base":
                o["outcome"] = "won"

    def intruder():
        for i in range(6):
            s = ledger._load()
            s["orders"].append(_order(f"n{i}"))
            # Each intruder ALSO touches an existing row, so the run is a real
            # same-row race and not the addition-only kind that logs nothing.
            for o in s["orders"]:
                if o["idempotency_key"] == "base":
                    o["venue_status"] = f"seen_by_{i}"
            ledger._persist(s)

    _race(slow_edit, intruder, timeout=25)

    stored = _stored()
    assert stored["base"].get("outcome") == "won"
    missing = [f"n{i}" for i in range(6) if f"n{i}" not in stored]
    assert not missing, f"intruder writes lost: {missing}"
    assert _concurrent_from(_merge_lines(capsys)) >= 1


def test_a_DELETION_racing_the_gap_keeps_the_other_writers_UPDATE():
    """`_merge_onto_current`'s hardest rule, reached through the real path
    rather than called directly: our stale copy DROPPED a row the other writer
    was busy updating. The update must win -- a deletion derived from a stale
    read is not an instruction."""
    _seed("keep", "contested")

    def slow_edit(state):
        state["orders"] = [o for o in state["orders"]
                           if o["idempotency_key"] != "contested"]

    def intruder():
        other = ledger._load()
        for o in other["orders"]:
            if o["idempotency_key"] == "contested":
                o["outcome"] = "won"
        ledger._persist(other)

    _race(slow_edit, intruder)

    stored = _stored()
    assert "contested" in stored, "a stale-read deletion erased a live update"
    assert stored["contested"].get("outcome") == "won"


def test_a_DELIBERATE_deletion_still_survives_a_collision():
    """The mirror of the test above, and the reason that one is not simply
    'never delete'. A row the slow writer deleted that NOBODY else touched must
    stay deleted -- otherwise the merge resurrects rows and the cap never
    holds."""
    _seed("keep", "doomed")

    def slow_edit(state):
        state["orders"] = [o for o in state["orders"]
                           if o["idempotency_key"] != "doomed"]

    def intruder():
        other = ledger._load()
        other["orders"].append(_order("unrelated"))
        ledger._persist(other)

    _race(slow_edit, intruder)

    stored = _stored()
    assert "doomed" not in stored, "the merge resurrected a deliberate deletion"
    assert "keep" in stored and "unrelated" in stored


def test_the_ledger_never_SHRINKS_across_a_forced_collision():
    """The measurable that started `#600`: the document went BACKWARDS by 8,031
    bytes. Row count is the durable version of that assertion."""
    _seed(*[f"o{i}" for i in range(12)])
    before = len(_stored())

    def intruder():
        s = ledger._load()
        s["orders"].append(_order("late"))
        ledger._persist(s)

    _race(lambda state: None, intruder)

    assert len(_stored()) == before + 1, "the ledger shrank across a collision"
