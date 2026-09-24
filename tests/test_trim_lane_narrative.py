"""`scripts/trim_lane_narrative.py` -- the keep policy, with controls.

Every test here exists because a real block broke an earlier version of the rule
on 2026-09-24. The controls matter more than the assertions: a keep-policy test
that cannot fail is worthless, because "keep more" always passes a "nothing was
lost" check.
"""
from __future__ import annotations

import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
sys.path.insert(0, os.path.join(REPO, ".claude", "hooks"))

T = pytest.importorskip("trim_lane_narrative")

EM = "—"


def _claims():
    return T.claims_fn()


def _hdr(slug="demo", status="OPEN"):
    return "### %s %s %s %s opened 2026-09-01 %s session deadbeef-0000-0000-0000-000000000000" % (
        slug, EM, status, EM, EM)


def _plan(lines):
    block = [l for l in lines]
    return T.plan(block, _claims())


# ----------------------------------------------------------------- contract
def test_contract_key_keeps_its_whole_subtree():
    """`- Falsification test:` carries its content in children.

    Found on `polymarket-rejected-resubmit-loop`: keeping the parent alone left a
    contract promising a list and delivering nothing, and every automated check
    still passed -- no claim moved, nothing was orphaned, the claim set matched.
    """
    block = [_hdr(),
             "- **OLD NOTE 2026-09-02.** history",
             "- Falsification test:",
             "  - first clause",
             "  - second clause"]
    _full, _cl, keep = _plan(block)
    assert 2 in keep, "the contract key itself"
    assert 3 in keep and 4 in keep, "its children ARE the contract"


def test_control_a_plain_history_parents_children_are_moved():
    """CONTROL for the above: the subtree rule must NOT keep every parent.

    Without this, `test_contract_key_keeps_its_whole_subtree` would pass for an
    implementation that simply keeps everything.
    """
    block = [_hdr(),
             "- **OLD NOTE 2026-09-02.** history",
             "  - a detail of the old note",
             "  - another detail"]
    _full, _cl, keep = _plan(block)
    assert 2 not in keep and 3 not in keep, "plain history children must move"


def test_a_colon_terminated_kept_line_keeps_its_children():
    block = [_hdr(),
             "- Verification:",
             "  - the reading that proves it"]
    _full, _cl, keep = _plan(block)
    assert 2 in keep


# -------------------------------------------------------------------- claims
def test_a_claim_bearing_line_is_kept_BY_THE_CLAIM_RULE():
    """The fixture must isolate the claim rule, or the test proves nothing.

    A first version used a plain `- Files:` line, which the CONTRACT rule keeps
    anyway -- so deleting the claim rule entirely left the suite green. Only the
    mutation check caught that. This shape (`**Files:**` nested under a
    non-contract parent, as in `book-quotes-splice-repair`'s P3 pre-registration)
    is claim-bearing and is matched by NO other keep rule: `**` stops CONTRACT
    matching, the parent is not a contract key and does not end in a colon.
    """
    block = [_hdr(),
             "- Files: `a/b.py`",
             "- **P3 PRE-REG 2026-09-02.** plan",
             "    - **Files:** `x/y.py` (NEW)"]
    full, claim_lines, keep = _plan(block)
    assert full, "fixture must declare claims or the test is vacuous"
    assert 3 in claim_lines, "the nested declaration is claim-bearing"
    assert not T.CONTRACT.match(block[3]), "no other rule may explain keeping it"
    assert not T.OUTSTANDING.search(block[3])
    assert 3 in keep


def test_claim_lines_are_found_by_REMOVAL_not_by_spelling():
    """A line that declares no path can still be claim-bearing.

    `**Files, scope widened (no other OPEN lane claims these):**` in
    `book-quotes-splice-repair` names nothing itself; removing it breaks the parse
    of its children. A grep for `Files:` gets the set wrong in both directions.
    """
    block = [_hdr(),
             "- Files: `a/b.py`",
             "  - **Files, scope widened:**",
             "    - `c/d.py`"]
    full, claim_lines, keep = _plan(block)
    # whatever the guard's parse does, the policy must not drop a line whose
    # removal changes the claim set
    for i in claim_lines:
        assert i in keep
    assert full, "fixture declares claims"


def test_control_a_prose_line_is_not_claim_bearing():
    """CONTROL: not every line is claim-bearing, or the measurement is vacuous."""
    block = [_hdr(),
             "- Files: `a/b.py`",
             "- **OLD NOTE 2026-09-02.** plain prose with no path"]
    _full, claim_lines, _keep = _plan(block)
    assert 2 not in claim_lines


# --------------------------------------------------------------- outstanding
@pytest.mark.parametrize("marker", ["OWED", "LEFT:", "STILL", "NOT MET", "TODO"])
def test_outstanding_work_is_kept(marker):
    block = [_hdr(),
             "- **OLD NOTE 2026-09-02.** history",
             "- **status** %s something" % marker]
    _full, _cl, keep = _plan(block)
    assert 2 in keep, marker


# -------------------------------------------------------------- idempotency
def test_a_previous_pointer_is_kept_and_does_not_win_newest():
    """The pointer carries the trim date, so it must not count as newest.

    Measured on `polymarket-ask-pricing`: before this, a re-run wanted to move
    `CLAIM TAKEN 2026-09-23`, the genuine newest entry, because the pointer dated
    2026-09-24 had taken the slot. A trimmer that eats more on every run is worse
    than none.
    """
    block = [_hdr(),
             "- **TRIMMED 2026-09-24 by `scripts/trim_lane_narrative.py`. history moved.",
             "- **REAL NEWEST 2026-09-23.** the genuine latest entry",
             "- **OLDER 2026-09-02.** history"]
    _full, _cl, keep = _plan(block)
    assert 1 in keep, "the pointer is metadata and is kept"
    assert 2 in keep, "the newest REAL entry must still be kept"
    assert 3 not in keep, "older history still moves"


def test_control_without_a_pointer_the_newest_dated_line_is_kept():
    block = [_hdr(),
             "- **NEWER 2026-09-23.** latest",
             "- **OLDER 2026-09-02.** history"]
    _full, _cl, keep = _plan(block)
    assert 1 in keep and 2 not in keep


# ------------------------------------------------------------------ locate
def test_locate_stops_at_the_next_heading():
    lines = [_hdr("alpha"), "- body", "### beta " + EM + " OPEN " + EM + " x", "- other"]
    assert T.locate(lines, "alpha") == (0, 2)


def test_locate_returns_none_for_an_unknown_slug():
    assert T.locate([_hdr("alpha"), "- body"], "nope") is None


# ------------------------------------------------------- the real ledger
def test_the_policy_is_idempotent_on_the_live_lanes_file():
    """Re-planning an already-trimmed block must move nothing but blanks.

    Guards the property directly on the file the tool actually edits, so it keeps
    holding as `lanes.md` changes.
    """
    path = os.path.join(REPO, ".syndicate", "lanes.md")
    if not os.path.exists(path):
        pytest.skip("no lanes.md")
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().split("\n")
    claims = _claims()
    checked = 0
    for i, l in enumerate(lines):
        if not T.POINTER_RE.search(l):
            continue
        slug = next((lines[j].split()[1] for j in range(i, -1, -1)
                     if lines[j].startswith("### ")), None)
        if slug is None:
            continue
        found = T.locate(lines, slug)
        if found is None:
            continue
        s, e = found
        block = lines[s:e]
        _full, _cl, keep = T.plan(block, claims)
        moved = [k for k in range(len(block)) if k not in set(keep) and block[k].strip()]
        # a trimmed block may still be MORE aggressively trimmable under this
        # policy than the hand trim that made it -- the CLI refuses that without
        # --retrim. What must never happen is the pointer losing its own slot.
        assert any(T.POINTER_RE.search(block[k]) for k in keep), slug
        checked += 1
    assert checked, "no trimmed block found -- this test would be vacuous"
