"""A claim under a dot-directory must guard the file it names.

WHY THIS EXISTS. `lane-guard._paths_in` stripped punctuation SYMMETRICALLY --
``tok.strip("`<>*_()[].,;")`` -- which removes a LEADING dot as well as a
trailing period. So `.syndicate/x.md` became `syndicate/x.md`, and because the
matcher is `rel.endswith("/" + f)`:

    ".syndicate/x.md".endswith("/syndicate/x.md")   ->   False

Every claim under `.syndicate/` or `.claude/` named a file it could never match
and guarded NOTHING, silently. Measured 2026-08-31 on the live ledger: one such
claim (`exchange-join-refusals` on a findings doc), and `check_lane_invariants`
reported it healthy the whole time -- it verifies that each claim has exactly
one holder, which is true of a claim that guards nothing.

THE FIRST TEST IS THE ONE THAT WOULD HAVE FAILED BEFORE THE FIX. The others
pin the behaviour the fix must NOT break: a trailing sentence period still
goes, and so does a trailing backtick. The first cut of the fix used
`.rstrip(".")` after stripping the rest, which left `` `x.py`. `` ending in a
backtick and broke a DIFFERENT claim while repairing this one -- so the
asymmetry belongs on the LEFT side only.

HOW THIS FILE LOADS THE PARSER, AND WHY IT CHANGED `[2026-09-04]`. It used to
read `lane-guard.py`, slice the text at `def main`, and `exec` the prefix -- the
standard workaround for a hook that `sys.exit()`s at import. `_paths_in` has
since moved into `.claude/hooks/lane_claims.py`, which `lane-guard.py` imports,
so the exec'd namespace no longer had the function and all 8 tests here died on
`AttributeError` before reaching a single assertion. Measured red at HEAD
2026-09-04, unrelated to any change in the same session.

**The function under test never moved out of the enforcement path -- only out of
the file this test had hardcoded.** That is the difference between a test that
fails and a test that stops existing, and it is why this now imports the library
rather than reconstructing a module from a slice of hook source.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

HOOKS = pathlib.Path(__file__).resolve().parents[1] / ".claude" / "hooks"
sys.path.insert(0, str(HOOKS))
import lane_claims  # noqa: E402 - needs the path insert above


def _guard():
    """The parser `lane-guard.py` enforces with, imported not reconstructed."""
    return lane_claims


@pytest.mark.parametrize(
    "path",
    [".syndicate/findings_x.md", ".claude/hooks/lane-guard.py", ".github/workflows/ci.yml"],
)
def test_a_dot_directory_path_survives_extraction(path):
    """The regression itself. Pre-fix these came back with the dot removed."""
    got = list(_guard()._paths_in("`%s`" % path))
    assert got == [path], "leading dot stripped: %r" % got


def test_the_extracted_claim_can_actually_MATCH_the_file_it_names():
    """Extraction alone is not the point -- `rel.endswith("/" + f)` is where the
    mangled claim failed, so assert against THAT, not against the string."""
    rel = ".syndicate/findings_x.md"
    (claimed,) = list(_guard()._paths_in("`%s`" % rel))
    assert rel == claimed or rel.endswith("/" + claimed), (
        "claim %r cannot match an edit to %r" % (claimed, rel)
    )


def test_a_trailing_sentence_period_is_still_stripped():
    """off != on in the direction that protects existing behaviour."""
    assert list(_guard()._paths_in("`syndicate/features/shared/x.py`.")) == [
        "syndicate/features/shared/x.py"
    ]


def test_a_trailing_backtick_is_still_stripped():
    """The bug the first cut of the fix introduced: strip the dot on the right
    and the backtick behind it survives."""
    assert list(_guard()._paths_in("`a/b.py`. `c/d.py`,")) == ["a/b.py", "c/d.py"]


def test_ordinary_wrapping_punctuation_is_unaffected():
    assert list(_guard()._paths_in("(`x/y.py`), [z/w.py];")) == ["x/y.py", "z/w.py"]


def test_a_bare_dot_does_not_become_a_claim():
    assert list(_guard()._paths_in(" . .. ")) == []
