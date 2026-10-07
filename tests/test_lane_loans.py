"""lane_claims: a granted LOAN is enforceable, and a forged one is not.

MEASURED DEADLOCK, 2026-10-06. Three OPEN lanes named
`syndicate/features/shared/basketball_props_smart_sim.py`: one owner and two borrowers
that had each correctly recorded `(LOAN from <owner>` on their own Files line. Running
lane-guard's own predicate, ALL THREE were blocked -- the two borrowers by each other and
the OWNER by a borrower -- because a borrower's own claim cannot help it (`slug == current`
is skipped) and counts against everyone else. Nobody could write the file.

So a loaned path is NOT a claim: it leaves the claim set, leaving the lender as the single
holder, and `loan_is_honoured` is what permits the borrower -- only ever when the named
lender genuinely holds the path. The forged-loan test below is the one that keeps the guard
from becoming decorative.
"""
from __future__ import annotations

import importlib.util
import pathlib

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "lane_claims_under_test", _ROOT / ".claude/hooks/lane_claims.py")
lc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lc)

PATH = "syndicate/features/shared/thing.py"


def _lanes(*blocks):
    return "## OPEN\n\n" + "\n\n".join(blocks) + "\n"


def _lane(slug, files, status="OPEN"):
    return (f"### {slug} — {status} — opened 2026-10-06 — session s-{slug}\n"
            f"- Goal: whatever\n"
            f"- Files: {files}\n"
            f"- Blocked by: none")


OWNER = _lane("owner-lane", PATH + " (the thing)")
BORROWER = _lane("borrower-lane", PATH + " (LOAN from owner-lane, granted in chat)")


def _blocked_by(text, current, rel):
    """lane-guard's own decision, reproduced: skip your slug, block on any other match."""
    conflict = None
    for slug, f in lc._claims(text):
        if slug != current and lc.matches(rel, f):
            conflict = slug
    return conflict


def test_a_loaned_path_is_not_a_claim_so_the_lender_is_the_single_holder():
    text = _lanes(OWNER, BORROWER)
    holders = lc.claims_by_path(text).get(PATH) or set()
    assert holders == {"owner-lane"}, holders
    # which is what stops check_lane_invariants reporting a contest
    assert PATH not in {f for s, f in lc._claims(text) if s == "borrower-lane"}


def test_the_owner_is_not_blocked_by_a_borrower():
    """The half that made this urgent: a borrower's claim used to lock the OWNER out."""
    assert _blocked_by(_lanes(OWNER, BORROWER), "owner-lane", PATH) is None


def test_two_borrowers_do_not_block_each_other():
    second = _lane("borrower-two", PATH + " (LOAN from owner-lane)")
    text = _lanes(OWNER, BORROWER, second)
    assert _blocked_by(text, "borrower-lane", PATH) == "owner-lane", \
        "still blocked by the OWNER's claim -- which the loan then honours"
    assert lc.loan_is_honoured(text, "borrower-lane", PATH) == "owner-lane"
    assert lc.loan_is_honoured(text, "borrower-two", PATH) == "owner-lane"


def test_a_FORGED_loan_naming_a_lane_that_does_not_hold_the_path_is_NOT_honoured():
    """The control that keeps the guard meaningful. Without it any lane could write
    `(LOAN from anyone)` and walk straight through."""
    forged = _lane("forger-lane", PATH + " (LOAN from some-other-lane)")
    other = _lane("some-other-lane", "unrelated/file.py")
    text = _lanes(OWNER, forged, other)
    assert lc.loan_is_honoured(text, "forger-lane", PATH) is None
    assert _blocked_by(text, "forger-lane", PATH) == "owner-lane"


def test_a_loan_from_a_CLOSED_lane_is_not_honoured():
    """A closed lane holds nothing, so it can lend nothing."""
    closed_owner = _lane("owner-lane", PATH + " (the thing)", status="CLOSED 2026-10-06")
    text = _lanes(closed_owner, BORROWER)
    assert lc.loan_is_honoured(text, "borrower-lane", PATH) is None


def test_a_loan_marker_does_not_release_the_OTHER_paths_on_the_same_line():
    """The marker is scoped to its own comma-fragment. A sibling path on the same Files
    line is an ordinary claim and must stay claimed -- the `Files:` prefix-cut incident
    is the reason this is tested rather than assumed."""
    mixed = _lane("mixed-lane",
                  PATH + " (LOAN from owner-lane), syndicate/features/shared/mine.py")
    text = _lanes(OWNER, mixed)
    mine = lc.claims_by_path(text).get("syndicate/features/shared/mine.py") or set()
    assert mine == {"mixed-lane"}, mine
    assert (lc.claims_by_path(text).get(PATH) or set()) == {"owner-lane"}


def test_a_lane_with_no_loan_is_unaffected():
    """Non-loan parsing is untouched: loaned paths are subtracted from the existing
    extraction rather than the extraction being rewritten."""
    plain = _lane("plain-lane", "a/b.py, c/d.py")
    by_path = lc.claims_by_path(_lanes(plain))
    assert (by_path.get("a/b.py") or set()) == {"plain-lane"}
    assert (by_path.get("c/d.py") or set()) == {"plain-lane"}


def test_loans_lists_the_triple():
    text = _lanes(OWNER, BORROWER)
    assert ("borrower-lane", PATH, "owner-lane") in set(lc.loans(text))
