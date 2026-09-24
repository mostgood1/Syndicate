"""`lane_census.block_bytes` / `budget_line` / `budget_digest`.

WHY THESE EXIST. The attribution was added on 2026-09-24 because the
session-start digest emitted `LEDGER OVER BUDGET: lanes.md 485KB>234KB` next to
`LANE ARCHIVE OWED: 15 closed/orphaned lanes`, neither carrying a size. Read
together they are problem and remedy, and a session read them that way -- opened
a lane and archived nine blocks before measuring that closed blocks were 45KB of
a 245KB overage while OPEN blocks held 361KB. The fix is that the alarm now
states the SIZE of what archiving can recover, beside the overage.

THE LOAD-BEARING TEST IS CONSERVATION, not a golden number. The first version of
this verification asserted byte totals against a separate census I had run by
hand; they disagreed by ~1.4KB and the hand census was the one that was wrong --
it lost 825B of the file. A total that must equal the file size cannot be wrong
in that direction silently, and it does not rot when lanes.md changes.

Every test carries a CONTROL: an assertion that the thing being checked can
actually fail. `learnings.md`: a guard whose healthy reading you have never seen
fail is not an instrument.
"""
from __future__ import annotations

import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
sys.path.insert(0, os.path.join(REPO, ".claude", "hooks"))

lane_census = pytest.importorskip("lane_census")

EM = "—"


def _lanes(*blocks):
    return "# Lanes\n\n## OPEN\n\n" + "\n".join(blocks) + "\n"


def _block(slug, status, body_lines=2, session="deadbeef"):
    head = "### %s %s %s %s opened 2026-09-01 %s session %s0000-0000-0000-0000" % (
        slug, EM, status, EM, EM, session)
    body = "\n".join("- line %d for %s" % (i, slug) for i in range(body_lines))
    return head + "\n" + body + "\n"


# --------------------------------------------------------------- conservation
def test_block_bytes_attributes_every_byte_exactly_once():
    text = _lanes(_block("alpha", "OPEN"), _block("beta", "CLOSED"))
    ob, cb, xb, ranked = lane_census.block_bytes(text)
    assert ob + cb + xb == len(text.encode("utf-8"))
    assert [r[0] for r in ranked] == ["alpha"]


def test_conservation_holds_on_the_real_file():
    """The invariant that matters, on the bytes the alarm actually reads."""
    path = os.path.join(REPO, ".syndicate", "lanes.md")
    if not os.path.exists(path):
        pytest.skip("no lanes.md in this tree")
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    ob, cb, xb, _ = lane_census.block_bytes(text)
    assert ob + cb + xb == len(text.encode("utf-8"))


def test_conservation_control_a_dropped_bucket_is_detectable():
    """CONTROL: conservation must FAIL when a bucket is ignored.

    Without this, the sum test passes trivially for any implementation that
    happens to return the file size, and would keep passing if the split broke.
    """
    text = _lanes(_block("alpha", "OPEN"), _block("beta", "CLOSED"))
    ob, cb, xb, _ = lane_census.block_bytes(text)
    assert cb > 0, "fixture must contain a non-OPEN block or the control is vacuous"
    assert ob + xb != len(text.encode("utf-8"))


# ------------------------------------------------------- OPEN/closed split
def test_open_and_closed_are_split_by_the_guards_own_test():
    """The closed bucket must hold the CLOSED block's own bytes.

    An earlier version asserted only `ob > cb` and `ranked == ['alpha']`. A
    mutation that counted closed bytes as OPEN still passed it: `cb` merely went
    to 0, which keeps `ob > cb` true and leaves `ranked` untouched, because
    `per_open` is only written when the block is OPEN. The test was vacuous for
    exactly the confusion it existed to catch, and only the mutation check found
    that. So pin both buckets to the blocks that produced them.
    """
    alpha = _block("alpha", "OPEN", body_lines=8)
    closed = _lanes(alpha, _block("beta", "CLOSED", body_lines=1))
    opened = _lanes(alpha, _block("beta", "OPEN", body_lines=1))
    ob1, cb1, xb1, ranked1 = lane_census.block_bytes(closed)
    ob2, cb2, xb2, ranked2 = lane_census.block_bytes(opened)

    # Differential, not absolute: `_lanes` puts a blank line between blocks and
    # it is attributed to the block above, so an absolute `ob == len(alpha)`
    # assertion is brittle for reasons that have nothing to do with the split.
    # Flipping beta's status must move EXACTLY its bytes from one bucket to the
    # other -- which is false for any mutation that conflates the two.
    # Flipping the status also changes the file's length, because "CLOSED" is two
    # bytes longer than "OPEN". The first version of this assertion ignored that
    # and failed by exactly 2 on correct code -- a brittle test reads as a bug in
    # the thing it tests, which is worse than no test.
    delta = len(opened.encode("utf-8")) - len(closed.encode("utf-8"))
    assert cb1 > 0, "a zero closed bucket is the mutation this test must catch"
    assert cb2 == 0, "with both blocks OPEN, nothing may remain in closed"
    assert ob2 == ob1 + cb1 + delta, "beta's bytes must move whole between buckets"
    assert xb2 == xb1, "the unattributed bucket must not absorb the difference"
    assert [r[0] for r in ranked1] == ["alpha"]
    assert sorted(r[0] for r in ranked2) == ["alpha", "beta"]


def test_count_agrees_with_this_modules_own_census():
    """No second opinion about lanes.md -- the module's rule, tested."""
    text = _lanes(_block("a", "OPEN"), _block("b", "OPEN"), _block("c", "CLOSED"))
    _ob, _cb, _xb, ranked = lane_census.block_bytes(text)
    assert len(ranked) == lane_census.summarise(lane_census.lanes(text))["open"]


def test_session_prefix_is_carried_so_the_debt_has_an_owner():
    text = _lanes(_block("alpha", "OPEN", session="abc12345"))
    _ob, _cb, _xb, ranked = lane_census.block_bytes(text)
    assert ranked[0][2] == "abc12345"


# --------------------------------------------------------------- the alarm
def test_silent_when_under_budget():
    text = _lanes(_block("alpha", "OPEN"))
    assert lane_census.budget_line(text, 10_000_000) is None
    assert lane_census.budget_digest(text, 10_000_000) is None


def test_speaks_when_over_budget_and_names_the_archivable_size():
    text = _lanes(_block("alpha", "OPEN", body_lines=40),
                  _block("beta", "CLOSED", body_lines=5))
    line = lane_census.budget_line(text, 100)
    assert line is not None
    assert "OPEN blocks" in line
    assert "archiv" in line.lower(), "must name what archiving can recover"
    assert "OWNING session" in line, "must say the rest is not unilaterally payable"


def test_digest_form_stays_short_enough_for_the_digest():
    """The digest body had 136B of headroom; the full sentence (~280B) overflowed."""
    text = _lanes(_block("alpha", "OPEN", body_lines=40))
    d = lane_census.budget_digest(text, 100)
    assert d is not None
    assert len(d.encode("utf-8")) <= 60, d


@pytest.mark.parametrize("bad", [0, None, -1])
def test_absent_cap_raises_rather_than_defaulting_permissive(bad):
    """An absent cap must not fall through to the permissive branch.

    Found by this function's own verification: `if cap and size <= cap` skipped
    the guard for a falsy cap, so cap=0 produced a line advertising a "0KB cap"
    -- an alarm that is always true. `feedback_unknown_must_not_default_permissive`.
    """
    text = _lanes(_block("alpha", "OPEN"))
    with pytest.raises(ValueError):
        lane_census.budget_line(text, bad)
    with pytest.raises(ValueError):
        lane_census.budget_digest(text, bad)
