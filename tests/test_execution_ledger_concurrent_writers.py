"""`#600` — two services read-modify-write this ledger, and it was losing writes.

Every scenario here is the shape MEASURED in production on 2026-08-28, when
live-odds-worker's stale snapshot overwrote a settlement pass 12 seconds after
it landed and the ledger shrank by 8,031 bytes. The nine grades in that write
were gone before anyone read them, and the `SETTLED ... graded=9` log line that
described them was perfectly true.

The load-bearing test is `test_a_stale_writer_no_longer_clobbers...`: it fails
against the pre-fix module and is the whole reason the merge exists.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared import execution_ledger as ledger


@pytest.fixture(autouse=True)
def _isolated_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path))
    monkeypatch.delenv("SYNDICATE_REFRESH_STATE_BACKEND", raising=False)
    yield


def _seed(*keys):
    """Put orders in the store the way a real slate would leave them."""
    state = ledger._load()
    state["orders"] = [
        {"idempotency_key": k, "status": "filled", "selected_date": "2026-08-26"}
        for k in keys
    ]
    ledger._persist(state)


def _stored():
    return {o["idempotency_key"]: o for o in ledger._load()["orders"]}


# ---------------------------------------------------------------------------
# THE MEASURED FAILURE
# ---------------------------------------------------------------------------


def test_a_stale_writer_no_longer_clobbers_a_grade_it_never_touched():
    """THE `#600` REGRESSION, in the exact order it happened in production.

    refresh-worker graded two orders. live-odds-worker was already holding a
    snapshot from before those grades existed; it reconciled a THIRD, unrelated
    order and wrote its whole copy back, discarding both grades.

    The distinction that matters is not which orders a writer HOLDS -- the
    stale writer holds all of them -- but which it CHANGED.
    """
    _seed("graded-a", "graded-b", "reconciled-c")

    # live-odds-worker loads FIRST, before the grades exist.
    stale = ledger._load()

    # refresh-worker grades two orders and persists.
    fresh = ledger._load()
    for row in fresh["orders"]:
        if row["idempotency_key"] in {"graded-a", "graded-b"}:
            row["outcome"] = "won"
            row["pnl_dollars"] = 1.23
    ledger._persist(fresh)
    assert {k: v.get("outcome") for k, v in _stored().items()} == {
        "graded-a": "won", "graded-b": "won", "reconciled-c": None,
    }

    # live-odds-worker now reconciles its own row and writes its STALE copy.
    for row in stale["orders"]:
        if row["idempotency_key"] == "reconciled-c":
            row["reconciled_at"] = "2026-08-28T17:41:02Z"
    ledger._persist(stale)

    after = _stored()
    # THE GRADES SURVIVE. Pre-fix, both were None here.
    assert after["graded-a"].get("outcome") == "won"
    assert after["graded-b"].get("outcome") == "won"
    assert after["graded-a"].get("pnl_dollars") == 1.23
    # And the stale writer's own edit landed.
    assert after["reconciled-c"].get("reconciled_at") == "2026-08-28T17:41:02Z"


def test_the_ledger_never_goes_backwards_when_a_stale_writer_lands():
    """The production symptom was a SIZE that shrank. Rows added by the fresh
    writer must not vanish because a stale writer never knew about them."""
    _seed("existing")

    stale = ledger._load()

    fresh = ledger._load()
    fresh["orders"].append(
        {"idempotency_key": "placed-later", "status": "submitted"}
    )
    ledger._persist(fresh)

    stale["orders"][0]["reconciled_at"] = "now"
    ledger._persist(stale)

    assert set(_stored()) == {"existing", "placed-later"}


# ---------------------------------------------------------------------------
# DELETION -- the case a naive union would break
# ---------------------------------------------------------------------------


def test_a_deliberate_deletion_survives_the_merge():
    """`record_order` POPS a `rejected` row to free the retry -- "freeing the
    budget without freeing the retry is half a fix". A merge that unioned rows
    back in would make a transient refusal permanent."""
    _seed("keep", "drop-me")

    state = ledger._load()
    state["orders"] = [o for o in state["orders"] if o["idempotency_key"] != "drop-me"]
    ledger._persist(state)

    assert set(_stored()) == {"keep"}


def test_a_deletion_racing_an_update_keeps_the_UPDATE():
    """The one case where our deletion must lose. Dropping a row somebody else
    just wrote destroys information that cannot be recovered; keeping it costs
    a stale row that the next pass can remove again."""
    _seed("contested")

    deleter = ledger._load()

    updater = ledger._load()
    updater["orders"][0]["outcome"] = "won"
    ledger._persist(updater)

    deleter["orders"] = []
    ledger._persist(deleter)

    assert _stored()["contested"].get("outcome") == "won"


# ---------------------------------------------------------------------------
# The edges the merge must not get wrong
# ---------------------------------------------------------------------------


def test_our_own_edit_still_wins_on_a_row_we_actually_changed():
    """The merge must not become "never write anything"."""
    _seed("mine")
    state = ledger._load()
    state["orders"][0]["status"] = "filled"
    state["orders"][0]["outcome"] = "lost"
    ledger._persist(state)
    assert _stored()["mine"].get("outcome") == "lost"


def test_a_state_built_without_load_still_writes_and_says_so(capsys):
    """No baseline means no merge is possible. Behaving exactly as the old code
    did is the honest fallback -- guessing a snapshot would be worse -- and the
    counter records it rather than letting it look like a merge."""
    merged, counts = ledger._merge_onto_current(
        [{"idempotency_key": "hand-built"}], None
    )
    assert [o["idempotency_key"] for o in merged] == ["hand-built"]
    assert counts.get("no_baseline") == 1


def test_a_failed_re_read_falls_back_LOUDLY_rather_than_silently(monkeypatch, capsys):
    """Falling back to a blind write is the OLD behaviour, so it is not a new
    risk -- but it is the exact moment a write can be lost, so it must not be
    silent."""
    _seed("row")
    state = ledger._load()
    state["orders"][0]["outcome"] = "won"

    def _boom():
        raise ledger.LedgerError("store unreachable")

    monkeypatch.setattr(ledger, "_load", _boom)
    ledger._persist(state)
    assert "MERGE_READ_FAILED" in capsys.readouterr().out


def test_the_baseline_never_reaches_the_stored_document():
    """A private key that leaked into the ledger would be written to the money
    record and served by `/api/portfolio/live`."""
    _seed("row")
    state = ledger._load()
    assert ledger._BASELINE_KEY in state
    ledger._persist(state)
    assert ledger._BASELINE_KEY not in state

    from syndicate.features.shared.refresh_state_store import read_json_file

    raw = read_json_file(ledger._ledger_path())
    assert ledger._BASELINE_KEY not in raw
    for row in raw.get("orders") or []:
        assert ledger._BASELINE_KEY not in row


def test_the_merge_line_reports_what_it_rescued(capsys):
    """The instrument. Without it the fix is invisible in production and a
    silent merge is indistinguishable from a silent clobber."""
    _seed("theirs", "ours")

    stale = ledger._load()
    fresh = ledger._load()
    fresh["orders"][0]["outcome"] = "won"
    ledger._persist(fresh)
    capsys.readouterr()

    stale["orders"][1]["reconciled_at"] = "now"
    ledger._persist(stale)

    out = capsys.readouterr().out
    assert "LEDGER_MERGE" in out
    assert "concurrent=1" in out
    assert "kept_theirs=1" in out
    assert "wrote_ours=1" in out


def test_orders_without_an_idempotency_key_are_carried_not_dropped():
    """A legacy row with neither key cannot be merged safely. Carrying it is the
    conservative direction; dropping it would delete a money record."""
    state = ledger._load()
    state["orders"] = [{"position_key": "legacy-1", "status": "filled"}]
    ledger._persist(state)
    assert len(ledger._load()["orders"]) == 1


# ---------------------------------------------------------------------------
# Both raised by lane `venue-join-refusal-visibility` reviewing the fix.
# ---------------------------------------------------------------------------


def test_the_trim_runs_AFTER_the_merge_so_it_cannot_resurrect_a_dropped_row(monkeypatch):
    """The cap belongs to the document actually being WRITTEN.

    Trimming our own copy first and merging after would re-add, from the store,
    exactly the oldest rows the trim had just dropped -- the cap would never
    bind and `TRIMMED dropped=N` would be a lie. Trim was untested entirely
    until this was pointed out.
    """
    monkeypatch.setattr(ledger, "_MAX_RECORDS", 4)
    _seed("a", "b", "c", "d", "e", "f")

    state = ledger._load()
    state["orders"][-1]["outcome"] = "won"
    ledger._persist(state)

    kept = [o["idempotency_key"] for o in ledger._load()["orders"]]
    # Capped, and capped to the NEWEST -- oldest out, as the trim intends.
    assert len(kept) == 4
    assert kept == ["c", "d", "e", "f"]
    # And our edit survived the trim rather than being dropped and re-added.
    assert ledger._load()["orders"][-1].get("outcome") == "won"


def test_a_TRANSIENT_read_failure_still_merges_instead_of_clobbering(monkeypatch, capsys):
    """The failure mode this fix INTRODUCED. `_persist` never re-read before,
    so a blip on that read is a new way to lose exactly the writes the merge
    exists to protect. One retry covers it.
    """
    _seed("theirs", "ours")

    stale = ledger._load()
    fresh = ledger._load()
    fresh["orders"][0]["outcome"] = "won"
    ledger._persist(fresh)

    real_load = ledger._load
    calls = {"n": 0}

    def _flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise ledger.LedgerError("transient")
        return real_load()

    stale["orders"][1]["reconciled_at"] = "now"
    monkeypatch.setattr(ledger, "_load", _flaky)
    ledger._persist(stale)
    monkeypatch.setattr(ledger, "_load", real_load)

    after = _stored()
    # NOT clobbered: the retry got a clean read and the merge ran.
    assert after["theirs"].get("outcome") == "won"
    assert after["ours"].get("reconciled_at") == "now"
    assert "MERGE_READ_FAILED" not in capsys.readouterr().out
