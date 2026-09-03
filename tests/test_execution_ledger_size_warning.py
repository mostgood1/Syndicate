"""`#643`: the execution ledger's size warning must report the bound that BINDS.

The line used to end `-- the store refuses at 8MB`. That is true, and it reads
as an approaching outage on the service that trades. It is not one: `_MAX_RECORDS`
trims before the payload is serialized, so the size is bounded by
(bytes-per-order x cap), not by uptime.

MEASURED 2026-09-03, live-odds-worker's own log stream, three readings over
1.92h: bytes=2,508,823 / 2,509,822 / 2,512,819 against orders=2,294 / 2,294 /
2,297 -- **1093.6, 1094.1, 1094.0 bytes per order, flat**. Growth +2,081 B/h,
+1.6 orders/h. `TRIMMED` had never fired in 72h. At the 5,000-record cap that
projects to ~5.47MB, **65% of the 8MB ceiling**, which the cap prevents it from
crossing.

So the only thing that can make the ceiling reachable is per-order SIZE growth,
past ~1,677 B/order (+53%). That number is invisible in a total, which is why
the warning now reports the join rather than the sum.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from syndicate.features.shared import execution_ledger  # noqa: E402


def test_the_record_cap_bounds_the_payload_below_the_store_ceiling() -> None:
    """THE STRUCTURAL CLAIM `#643` rests on. If this fails, the ledger really can
    reach a refusal and the item's original alarm was right after all."""
    measured_bytes_per_order = 1094  # live-odds-worker, 2026-09-03, 3 readings
    projected = measured_bytes_per_order * execution_ledger._MAX_RECORDS
    ceiling = execution_ledger._store_max_bytes()

    assert projected < ceiling, (
        f"the {execution_ledger._MAX_RECORDS}-record cap projects to {projected} bytes, "
        f"at or above the {ceiling}-byte refusal -- the cap no longer protects the write"
    )
    # And with real margin, not by a hair.
    assert projected < ceiling * 0.8


def test_the_break_even_per_order_size_is_the_number_that_matters() -> None:
    """Documents the actual risk surface: not time, not count -- per-order size."""
    ceiling = execution_ledger._store_max_bytes()
    break_even = ceiling / execution_ledger._MAX_RECORDS
    assert break_even == pytest.approx(1677.7, abs=1.0)
    # 1094 measured -> a 53% per-order growth is required before the cap stops working.
    assert break_even / 1094 == pytest.approx(1.53, abs=0.02)


def test_the_ceiling_is_read_from_the_store_not_copied() -> None:
    """A hardcoded 8MB would go stale against SYNDICATE_KEYVALUE_MAX_BYTES and
    misreport the very threshold it warns about."""
    from syndicate.features.shared import refresh_state_store

    assert execution_ledger._store_max_bytes() == refresh_state_store._keyvalue_max_bytes()


def test_store_max_bytes_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """A warning that raises is worse than one that is conservative -- this runs
    on the persist path of the role that trades."""
    import builtins

    real_import = builtins.__import__

    def boom(name, *args, **kwargs):
        if "refresh_state_store" in name:
            raise ImportError("moved")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", boom)
    assert execution_ledger._store_max_bytes() == 8 * 1024 * 1024


def _warn_line(capsys: pytest.CaptureFixture) -> str:
    out = capsys.readouterr().out
    return next((l for l in out.splitlines() if "SIZE_WARNING" in l), "")


def test_the_warning_says_BOUNDED_at_the_measured_production_size(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, tmp_path: Path
) -> None:
    """Production's real shape must not read as an alarm."""
    monkeypatch.setattr(execution_ledger, "write_json_file", lambda path, state: None)
    monkeypatch.setattr(execution_ledger, "_ledger_path", lambda: tmp_path / "l.json")
    # ~1094 bytes/order across 2,297 orders, the measured production shape.
    orders = [{"idempotency_key": f"k{i}", "pad": "x" * 1040} for i in range(2297)]

    execution_ledger._persist({"orders": orders})

    line = _warn_line(capsys)
    assert "BOUNDED" in line and "UNBOUNDED" not in line
    assert "not an approaching outage" in line
    assert "bytes_per_order=" in line and "projected_at_cap=" in line


def test_the_warning_says_UNBOUNDED_when_the_cap_stops_protecting(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, tmp_path: Path
) -> None:
    """THE CASE THE OLD LINE COULD NOT DISTINGUISH. Same total, different shape:
    few orders, each huge, so the cap projects ABOVE the ceiling. This is a real
    approaching failure and must not read like the healthy case."""
    monkeypatch.setattr(execution_ledger, "write_json_file", lambda path, state: None)
    monkeypatch.setattr(execution_ledger, "_ledger_path", lambda: tmp_path / "l.json")
    # ~2,100 bytes/order -> 5000 x 2100 = 10.5MB, above the 8MB ceiling.
    orders = [{"idempotency_key": f"k{i}", "pad": "x" * 2050} for i in range(1100)]

    execution_ledger._persist({"orders": orders})

    line = _warn_line(capsys)
    assert "UNBOUNDED" in line
    assert "orders will fail to persist" in line


def test_the_two_verdicts_are_distinguishable_at_the_SAME_total_size(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, tmp_path: Path
) -> None:
    """The point of the change, stated as a test: a total cannot tell these apart
    and the per-order join can. Both payloads are ~2.4MB."""
    monkeypatch.setattr(execution_ledger, "write_json_file", lambda path, state: None)
    monkeypatch.setattr(execution_ledger, "_ledger_path", lambda: tmp_path / "l.json")

    execution_ledger._persist({"orders": [{"k": i, "pad": "x" * 1040} for i in range(2300)]})
    safe = _warn_line(capsys)
    execution_ledger._persist({"orders": [{"k": i, "pad": "x" * 2050} for i in range(1170)]})
    risky = _warn_line(capsys)

    safe_bytes = int(safe.split("bytes=")[1].split()[0])
    risky_bytes = int(risky.split("bytes=")[1].split()[0])
    assert abs(safe_bytes - risky_bytes) / safe_bytes < 0.10, "totals are within 10%"
    assert "BOUNDED" in safe and "UNBOUNDED" not in safe
    assert "UNBOUNDED" in risky


def test_trimming_still_happens_before_the_size_is_measured(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, tmp_path: Path
) -> None:
    """The whole bound rests on the trim preceding serialization. If that order
    ever inverts, the reported size is of a payload that was never written."""
    monkeypatch.setattr(execution_ledger, "write_json_file", lambda path, state: None)
    monkeypatch.setattr(execution_ledger, "_ledger_path", lambda: tmp_path / "l.json")
    over = execution_ledger._MAX_RECORDS + 250

    state = execution_ledger._persist({"orders": [{"k": i, "pad": "x" * 400} for i in range(over)]})

    assert state["trimmed"] == 250
    assert len(state["orders"]) == execution_ledger._MAX_RECORDS
    line = _warn_line(capsys)
    if line:
        assert f"orders={execution_ledger._MAX_RECORDS}" in line, "size reported for the TRIMMED payload"
