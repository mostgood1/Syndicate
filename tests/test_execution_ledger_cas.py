"""`#656` -- the execution ledger's merge-read and its SET are ONE compare-and-swap.

`#600`'s three-way merge re-read the store and then SET, with nothing atomic
between the two, so a SET landing in that window was overwritten by the late
writer's stale copy. On 2026-09-04 that reverted live order `6bc5617c` to
`submitted` and froze placement on both venues for six days.

Every test here runs the REAL `_persist` over a fake Redis that enforces WATCH
by the server's rule, and fires the rival write from INSIDE the merge's GET --
after it has read, before our EXEC. Each one FAILS on the pre-`#656` module: a
concurrency test that passes on the defect proves nothing.
"""

from __future__ import annotations

import pytest
import redis

from syndicate.features.shared import execution_ledger as ledger
from syndicate.features.shared import refresh_state_store as store
from syndicate.features.shared.execution_ledger import (
    LIVE,
    PAPER,
    STATUS_FILLED,
    STATUS_REJECTED,
    OrderRequest,
    complete_order,
    record_order,
    unreconciled_orders,
)
from tests.test_refresh_state_store_cas import _FakeRedis


@pytest.fixture(autouse=True)
def kv(tmp_path, monkeypatch):
    fake = _FakeRedis()

    def _client():
        return fake

    _client.cache_clear = lambda: None
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path))
    monkeypatch.setenv("SYNDICATE_REFRESH_STATE_BACKEND", "keyvalue")
    monkeypatch.delenv("SYNDICATE_EXECUTION_MODE", raising=False)
    monkeypatch.delenv("SYNDICATE_EXECUTION_LIVE_ARMED", raising=False)
    monkeypatch.setattr(store, "_get_keyvalue_client", _client)
    return fake


def _key() -> str:
    return store._state_key_for_path(ledger._ledger_path())


def _request(**overrides) -> OrderRequest:
    base = {
        "position_key": "abc123",
        "selected_date": "2026-08-22",
        "venue": "paper",
        "sport": "mlb",
        "event_id": "evt-1",
        "market": "h2h",
        "side": "home",
        "requested_price": -110.0,
        "requested_stake_dollars": 12.50,
    }
    base.update(overrides)
    return OrderRequest(**base)


def _rival_inside_the_merge_read(kv, write):
    """Run `write` once, right after the next GET of the ledger has read --
    after a `_persist`'s merge-read, before its SET."""
    fired = []

    def hook(key):
        if key == _key() and not fired:
            fired.append(1)
            kv.on_get = None
            write()

    kv.on_get = hook
    return fired


def _ledger_blip(kv, monkeypatch):
    """Every GET of the ledger fails, as a store blip does. Returns the undo."""
    real_get = kv.get

    def broken(key):
        if key == _key():
            raise redis.exceptions.ConnectionError("store blip")
        return real_get(key)

    monkeypatch.setattr(kv, "get", broken)
    return lambda: monkeypatch.setattr(kv, "get", real_get)


def test_THE_2026_09_04_INTERLEAVING_the_rival_write_now_survives(kv, capsys):
    """The same interleaving `test_execution_ledger.py` replays on disk, on the
    backend production actually uses."""
    k, _ = record_order(_request(venue="polymarket", position_key="K"), mode=LIVE)
    q, _ = record_order(_request(position_key="Q"), mode=PAPER)

    # refresh-worker completes its paper fill: load, change Q ...
    state = ledger._load()
    for order in state["orders"]:
        if order["idempotency_key"] == q["idempotency_key"]:
            order["status"] = STATUS_FILLED
    # ... and live-odds-worker's WHOLE write lands after its merge-read.
    fired = _rival_inside_the_merge_read(
        kv,
        lambda: complete_order(
            k["idempotency_key"],
            status=STATUS_REJECTED,
            error="OrderBuildError: market_unresolved_for_position",
        ),
    )
    capsys.readouterr()
    ledger._persist(state)

    assert fired == [1], "the rival never landed inside the window"
    stored = ledger.find_order(k["idempotency_key"])
    assert stored["status"] == STATUS_REJECTED
    assert stored["error"] == "OrderBuildError: market_unresolved_for_position"
    assert stored["venue_resolved_at"] is not None
    assert ledger.find_order(q["idempotency_key"])["status"] == STATUS_FILLED
    assert unreconciled_orders() == []
    assert "LEDGER_CAS conflicts=1" in capsys.readouterr().out


def test_a_persist_nobody_races_costs_ONE_read_and_one_transaction(kv):
    """The merge always re-read. The CAS moves that read inside a WATCH and adds
    nothing -- no second GET of a 2.7 MB document on every write."""
    record_order(_request(position_key="A"), mode=PAPER)
    state = ledger._load()
    state["orders"][0]["status"] = STATUS_FILLED
    kv.log.clear()

    ledger._persist(state)

    assert [op[0] for op in kv.log] == ["watch", "get", "exec", "set"]


def test_the_first_persist_in_a_process_says_the_CAS_is_active(kv, capsys, monkeypatch):
    """A persist nobody raced prints nothing, so without this line a deployed
    CAS reads exactly like an undeployed one until the first collision."""
    # `raising=False` so the pre-`#656` module fails this on the ASSERTION, not
    # on a missing attribute -- red for the right reason, or it proves nothing.
    monkeypatch.setattr(ledger, "_cas_announced", False, raising=False)
    record_order(_request(position_key="A"), mode=PAPER)
    record_order(_request(position_key="B"), mode=PAPER)

    assert capsys.readouterr().out.count("LEDGER_CAS_ACTIVE backend=keyvalue") == 1


def test_losing_EVERY_attempt_falls_back_loudly_and_STAMPS_the_document(kv, capsys, monkeypatch):
    """Refusing would drop OUR write -- in `complete_order`, a recorded fill,
    which strands the order the way the race does. So the last resort is the
    old non-atomic write, and the fact that it happened survives as state."""
    monkeypatch.setattr(ledger, "_CAS_MAX_ATTEMPTS", 2, raising=False)
    a, _ = record_order(_request(position_key="A"), mode=PAPER)
    state = ledger._load()
    state["orders"][0]["status"] = STATUS_FILLED
    rivals = []

    def another_writer_in_every_window(key):
        if key == _key():
            kv.on_get = None
            rivals.append(1)
            record_order(_request(position_key=f"R{len(rivals)}"), mode=PAPER)
            kv.on_get = another_writer_in_every_window

    kv.on_get = another_writer_in_every_window
    ledger._persist(state)
    kv.on_get = None

    assert "LEDGER_CAS_EXHAUSTED attempts=2" in capsys.readouterr().out
    stamp = ledger._load()["last_blind_write"]
    assert stamp["reason"] == "cas_retries_exhausted"
    assert stamp["attempts"] == 2
    assert ledger.find_order(a["idempotency_key"])["status"] == STATUS_FILLED


def test_a_FAILED_merge_read_is_a_failure_not_an_empty_ledger(kv, capsys, monkeypatch):
    """`read_json_file` answers a failed read with the same None as an absent
    key. Through `_load`, the merge read that as an EMPTY ledger and wrote our
    copy as the whole document -- silently, unstamped. Now the retry and the
    stamp fire."""
    a, _ = record_order(_request(position_key="A"), mode=PAPER)
    record_order(_request(position_key="B"), mode=PAPER)
    state = ledger._load()
    for order in state["orders"]:
        if order["idempotency_key"] == a["idempotency_key"]:
            order["status"] = STATUS_FILLED
    capsys.readouterr()

    restore = _ledger_blip(kv, monkeypatch)
    ledger._persist(state)
    restore()

    assert "MERGE_READ_FAILED" in capsys.readouterr().out
    assert ledger._load()["last_blind_write"]["reason"] == "merge_read_failed_after_retries"


def test_a_write_from_an_EMPTY_load_during_a_blip_is_REFUSED_rather_than_replacing_the_ledger(
    kv, capsys, monkeypatch
):
    """Raised by lane write-ahead-build-refusal. During a blip `record_order`'s
    own `_load` reads EMPTY (`#658`), so its copy is the one new row; with the
    merge-read failing too, a blind write of it REPLACES THE WHOLE LEDGER. A
    compare-and-swap cannot stop that -- the key really was unchanged."""
    a, _ = record_order(_request(position_key="A"), mode=PAPER)
    b, _ = record_order(_request(position_key="B"), mode=PAPER)
    capsys.readouterr()

    restore = _ledger_blip(kv, monkeypatch)
    with pytest.raises(ledger.LedgerError):
        record_order(_request(position_key="C"), mode=PAPER)
    restore()

    kept = {o["idempotency_key"] for o in ledger._load()["orders"]}
    assert {a["idempotency_key"], b["idempotency_key"]} <= kept
    assert "REFUSED" in capsys.readouterr().out


def test_a_stale_writer_does_not_erase_a_blind_write_stamp_it_never_saw(kv):
    """`last_blind_write` is a DOCUMENT-level field, so the row merge never
    carried it: a writer holding a copy from before the stamp wrote its own
    None over it, erasing the one durable record that a write was lost."""
    record_order(_request(position_key="A"), mode=PAPER)
    stale = ledger._load()
    stamped = ledger._load()
    stamped["last_blind_write"] = {"at": "2026-09-10T00:00:00Z", "reason": "cas_retries_exhausted"}
    ledger._persist(stamped)

    stale["orders"][0]["status"] = STATUS_FILLED
    ledger._persist(stale)

    stamp = ledger._load()["last_blind_write"]
    assert stamp is not None, "a stale writer erased the stamp"
    assert stamp["reason"] == "cas_retries_exhausted"
