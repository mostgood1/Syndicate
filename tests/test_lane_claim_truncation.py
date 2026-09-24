"""A lane can claim files the guard does not enforce, and nothing said so.

`lane_claims._claimable_prefix` cuts a `- Files:` line at the first disclaimer
marker, and the cut is a PREFIX -- so every path listed AFTER it is dropped.
That is right for a prohibition and silently wrong for a line that mentions
another lane and then keeps listing its own files.

MEASURED 2026-09-24 on the live `lanes.md`: 18 Files lines lose a path, 17 of
them OPEN, including one lane that keeps 0 of 3 and loses `render.yaml`. The
marker list's own comment records its blast radius as "4 lines out of 2,186 and
every one is a genuine disclaimer", which no longer holds.

These tests pin the REPORTING. The cut itself is deliberately unchanged --
loosening it would newly contest files across seventeen lanes at once.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".claude" / "hooks"))

from lane_claims import (  # noqa: E402
    claims_by_path,
    claims_lost_to_disclaimer,
)

OPEN_HEADER = "### a-lane — OPEN — opened 2026-09-24 — session abc"
CLOSED_HEADER = "### b-lane — CLOSED — opened 2026-09-24 — session abc"


def _lane(files_line: str, header: str = OPEN_HEADER) -> str:
    return "\n".join([header, files_line, "- Blocked by: none", ""])


def test_a_mid_sentence_negation_silently_drops_every_later_path():
    """The exact shape that cost this session 5 of 7 claims."""
    text = _lane(
        "- Files: `a/one.py` (the loop ONLY, no rate change), `a/two.py`, `a/three.py`"
    )
    kept = {p for p, slugs in claims_by_path(text).items() if "a-lane" in slugs}
    assert kept == {"a/one.py"}, kept

    reports = list(claims_lost_to_disclaimer(text))
    assert len(reports) == 1
    slug, open_lane, marker, lost = reports[0]
    assert slug == "a-lane" and open_lane is True
    assert marker == ", no "
    assert lost == ["a/three.py", "a/two.py"]


def test_a_reference_to_another_lane_also_drops_what_follows():
    text = _lane("- Files: `a/one.py`, `a/two.py` (held by other-lane), `a/three.py`")
    _slug, _open, marker, lost = next(iter(claims_lost_to_disclaimer(text)))
    assert marker == "held by"
    assert "a/three.py" in lost


def test_a_clean_files_line_reports_nothing():
    """The check must be silent when there is nothing to say, or it gets ignored."""
    text = _lane("- Files: `a/one.py`, `a/two.py`, `a/three.py`")
    assert list(claims_lost_to_disclaimer(text)) == []


def test_a_leading_disclaimer_is_NOT_a_loss():
    """"NOT claimed, deliberately: `x.py`" claims nothing and loses nothing --
    the claimable prefix is empty and `x.py` was never a claim. Reporting it
    would be crying wolf on the machinery working."""
    text = _lane("- Files: **NOT claimed, deliberately:** `a/one.py`")
    assert claims_by_path(text) == {}
    # The REPORTER still sees a path named and not kept, which is literally
    # true, so it says so. The CHECKER is what must not fail on it: "not
    # claimed" is a negation about what follows, not a reference to another
    # lane, so it lands under PROBABLY CORRECT. Asserting the reporter stayed
    # silent here would have hidden the same shape when it IS a defect.
    reports = list(claims_lost_to_disclaimer(text))
    assert len(reports) == 1 and reports[0][2] == "not claimed"


def test_closed_lanes_are_excluded_by_default_and_included_on_request():
    text = _lane(
        "- Files: `a/one.py` (held by other), `a/two.py`", header=CLOSED_HEADER
    )
    assert list(claims_lost_to_disclaimer(text)) == []
    assert len(list(claims_lost_to_disclaimer(text, open_only=False))) == 1


def test_reporting_does_not_change_what_is_ENFORCED():
    """The whole safety property of this lane: `claims_by_path` is untouched.

    Asserted on a line that BOTH functions see, so a future edit that tries to
    'fix' the cut inside `claims_by_path` fails here rather than silently
    re-contesting seventeen lanes.
    """
    text = _lane("- Files: `a/one.py` (the loop ONLY, no rate change), `a/two.py`")
    before = {p: set(s) for p, s in claims_by_path(text).items()}
    list(claims_lost_to_disclaimer(text))  # drain the generator
    after = {p: set(s) for p, s in claims_by_path(text).items()}
    assert before == after == {"a/one.py": {"a-lane"}}


# ---------------------------------------------------------------------------
# The checker script
# ---------------------------------------------------------------------------


def _run_checker(lanes_file: Path):
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_lane_claim_truncation.py"),
         "--lanes", str(lanes_file)],
        capture_output=True, text=True, cwd=str(ROOT), timeout=300,
    )


def test_the_checker_exits_zero_on_a_clean_ledger(tmp_path):
    f = tmp_path / "lanes.md"
    f.write_text(_lane("- Files: `scripts/check_lane_claim_truncation.py`"), encoding="utf-8")
    out = _run_checker(f)
    assert out.returncode == 0, out.stdout + out.stderr


def test_the_checker_exits_nonzero_and_NAMES_the_lane_and_the_lost_path(tmp_path):
    f = tmp_path / "lanes.md"
    # Two REAL tracked paths, the second behind a reference-style marker.
    f.write_text(
        _lane("- Files: `scripts/check_lane_claim_truncation.py` (held by other-lane), "
              "`tests/test_lane_claim_truncation.py`"),
        encoding="utf-8",
    )
    out = _run_checker(f)
    assert out.returncode == 1, out.stdout + out.stderr
    assert "a-lane" in out.stdout
    assert "tests/test_lane_claim_truncation.py" in out.stdout


def test_prose_that_merely_looks_path_shaped_does_NOT_fail_the_check(tmp_path):
    """`Yes/No` and `2b/3` are real tokens the extractor picks up. A checker
    that fails on those gets ignored, and the real losses go with it."""
    f = tmp_path / "lanes.md"
    f.write_text(_lane("- Files: `scripts/check_lane_claim_truncation.py` (held by other), Yes/No, 2b/3"),
                 encoding="utf-8")
    out = _run_checker(f)
    assert out.returncode == 0, out.stdout + out.stderr


def test_a_negation_marker_is_reported_apart_and_does_not_fail(tmp_path):
    """"no `render.yaml`" is the cut working correctly -- the file was FORBIDDEN,
    not claimed. Scoring it the same as a genuine under-claim would make the
    highest-blast-radius file in the repo look like a defect every run."""
    f = tmp_path / "lanes.md"
    f.write_text(
        _lane("- Files: `tests/test_lane_claim_truncation.py`. No deploy, no `render.yaml`"),
        encoding="utf-8",
    )
    out = _run_checker(f)
    assert out.returncode == 0, out.stdout + out.stderr


def test_a_path_with_trailing_ledger_punctuation_still_resolves(tmp_path):
    """The ledger punctuates around its backticked paths and the extractor can
    carry the tail along. Binning that as prose is an UNDER-report, which is the
    direction this check exists to stop."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import importlib

    mod = importlib.import_module("check_lane_claim_truncation")
    tracked = {"tests/test_poll_soccer_live_state.py"}
    assert mod._resolves("tests/test_poll_soccer_live_state.py`:", tracked)
    assert mod._resolves("`tests/test_poll_soccer_live_state.py`,", tracked)
    assert not mod._resolves("Yes/No", tracked)
