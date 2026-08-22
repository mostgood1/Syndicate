"""`#504` — settlement was left in the position `#341` rescued reconciliation from.

`#341` moved `_launch_autorun_reconciliation` to the front of the exclusive
if/elif chain because a late branch only runs on a tick where every earlier one
declines, and during a slate `mlb_refresh` keeps winning. It left
`_launch_autorun_evaluation_settlement` behind, and seven NFL branches were
later inserted ABOVE it — so the job that actually puts outcomes on the
portfolio ended up 13th of 14, further back than the job `#341` fixed.

MEASURED 2026-08-22, not inferred. Settlement was enabled at 17:13Z and reached
its branch exactly ONCE in 45 minutes, at 17:28:34.610Z — 0.65ms after
`SOCCER_AUTORUN_SKIPPED reason=spacing_gate`. It got that tick by coincidence.
At 18:00:16.855Z the chain stopped at branch 12 instead:

    SOCCER_UNIT_LAUNCHED league=la_liga unit=1/44 due=12 spacing_seconds=300

44 queued soccer units at one per 300s, plus `mlb_refresh` above it. Forcing a
20-minute interval produced ZERO runs in ten minutes, because the interval gate
was never the blocker — chain position was.

THESE TESTS ASSERT THE ORDER, NOT THE BEHAVIOUR, and that is deliberate: the
defect is positional, so a behavioural test passes just as happily on the broken
arrangement. This mirrors `tests/test_reconciliation_autorun_ordering.py`, which
exists for the same reason one branch up.
"""

from __future__ import annotations

import pathlib
import re

SRC = (pathlib.Path(__file__).resolve().parents[1] / "scripts" / "run_refresh_worker.py").read_text(encoding="utf-8")

SETTLEMENT = "_launch_autorun_evaluation_settlement"
RECONCILIATION = "_launch_autorun_reconciliation"


def _autorun_order() -> list[str]:
    return re.findall(r"elif (_launch_autorun_\w+)\(", SRC)


def test_settlement_is_in_the_chain_at_all() -> None:
    assert SETTLEMENT in _autorun_order()


def test_settlement_runs_before_the_branches_that_measurably_starved_it() -> None:
    order = _autorun_order()
    settlement = order.index(SETTLEMENT)
    for later in (
        # Wins nearly every tick during a slate — this file says so itself.
        "_launch_autorun_mlb_refresh",
        "_launch_autorun_weekly_sports_refresh",
        # 44 queued units at one per 300s on 2026-08-22; the branch that was
        # observed taking the tick settlement needed.
        "_launch_autorun_soccer_weekly_refresh",
    ):
        assert settlement < order.index(later), (
            f"{later} precedes settlement; an elif chain means settlement only "
            "runs on a tick where it declines, which is how #504 reached its "
            "branch once in 45 minutes"
        )


def test_settlement_runs_before_the_nfl_branches_inserted_above_it() -> None:
    """The seven NFL autoruns were added between `#341` and `#504`.

    Individually cheap and usually rate-limited, but each one is an `elif` that
    can take the single daily tick settlement needs.
    """
    order = _autorun_order()
    settlement = order.index(SETTLEMENT)
    nfl = [name for name in order if name.startswith("_launch_autorun_nfl_")]
    assert nfl, "expected the NFL autoruns to still be in this chain"
    for name in nfl:
        assert settlement < order.index(name), f"{name} precedes settlement"


def test_settlement_sits_directly_behind_reconciliation() -> None:
    """The two daily-gated INLINE evaluation jobs are adjacent, in this order.

    Order matters beyond starvation: reconciliation emits the settlement inputs
    (`closing_lines_{date}.csv`) that settlement and the ledger bridge then
    consume, so on any day both run, reconciliation running first is the
    arrangement that lets settlement see fresh inputs rather than last cycle's.
    """
    order = _autorun_order()
    assert order.index(SETTLEMENT) == order.index(RECONCILIATION) + 1, (
        f"expected {SETTLEMENT} directly after {RECONCILIATION}, got {order[:4]}"
    )


def test_promoting_it_did_not_duplicate_or_drop_a_branch() -> None:
    """The move was a lift-and-reinsert, so guard both failure modes."""
    order = _autorun_order()
    assert len(order) == len(set(order)), f"duplicate branch in the chain: {order}"
    assert order.count(SETTLEMENT) == 1


def test_the_two_properties_that_make_this_safe_still_hold() -> None:
    """`#341`'s justification is only valid while both remain true.

    DAILY GATED so it wins at most one tick per 24h, and INLINE so it never
    holds a job slot. If either changes, this position needs re-arguing rather
    than inheriting.
    """
    # Daily gate, not an interval: the Central-date comparison is the mechanism.
    assert "_evaluation_settlement_should_run_now" in SRC
    assert re.search(r"now_central\.date\(\) == last_central_date", SRC)
    # Inline: settlement calls the ledger directly rather than launching a job.
    assert "settle_ledger_for_dates" in SRC


def test_the_run_is_claimed_before_the_work() -> None:
    """`#256`. Without this, a death mid-pass re-runs on next boot forever.

    That is what turned an expensive pass into 110 OOM kills over eleven hours
    on 2026-08-07, and it is the property that makes promoting an EXPENSIVE job
    this high survivable rather than reckless.
    """
    claim = SRC.index("CLAIM THE RUN BEFORE DOING THE WORK")
    work = SRC.index("result = settle_ledger_for_dates(")
    assert claim < work, "the run must be claimed before settle_ledger_for_dates"
