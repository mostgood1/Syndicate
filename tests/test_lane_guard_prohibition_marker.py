"""A lane that PROHIBITS a file must not be read as CLAIMING it.

Measured 2026-09-03. `check_lane_invariants.py` reported `render.yaml` CONTESTED
by `accuracy-autorun-rearm` and `ncaaf-live-cadence`. Neither claimed it: both
wrote **"never `render.yaml`"**, because a `render.yaml` push fires
`blueprint_sync` and rewrites every env key on all three services. Every other
way of saying that was already a disclaimer marker -- `not touch`, `not taken`,
`released` -- and `never` was missing, so the two lanes most carefully avoiding
the repo's highest-blast-radius file were reported as fighting over it.

**WHY THIS MATTERS MORE THAN TIDINESS.** The guard's failure modes are
asymmetric. A false claim is noisy and safe. A MISSED claim lets two lanes edit
one file with no warning, which is the incident the lane system exists to stop.
So the fix had to be one that cannot lose claims -- an added prefix-cut marker --
and two tempting alternatives were rejected after being measured:

  * cross-line carry-over (so a disclaimer governs its wrapped continuation):
    buys tidiness in the dangerous direction.
  * word-boundary marker matching: measured to change **129 claims** across the
    real `lanes.md`, because these markers are deliberately substrings so
    `not touch` also covers `not touched`. Reverted.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CHECKER = _load(ROOT / "scripts" / "check_lane_invariants.py", "cli_check")

LANES = """## OPEN

### lane-a — OPEN — opened 2026-09-03 — session aaa
- Files: `syndicate/features/a.py`.
  Render ENV via the single-key API — **never `render.yaml`**, which fires
  `blueprint_sync` and rewrites every key on all three services.
- Blocked by: none.

### lane-b — OPEN — opened 2026-09-03 — session bbb
- Files: `syndicate/features/b.py`.
  Render ENV on the worker via the single-key API — **never `render.yaml`**
  (pushing it fires `blueprint_sync`).
- Blocked by: none.

## Archived lanes
"""


def test_a_prohibition_is_not_a_claim() -> None:
    """THE BUG. Two lanes swearing off a file were reported as contesting it."""
    claims = CHECKER.claims(LANES)
    holders = sorted(slug for slug, path in claims if path == "render.yaml")
    assert holders == [], f"a prohibition was read as a claim by {holders}"
    assert CHECKER.contested_files(claims) == {}


def test_the_real_files_are_still_claimed() -> None:
    """The fix must not buy quiet by losing claims -- that is the dangerous
    direction. Both lanes still claim their actual files."""
    claims = CHECKER.claims(LANES)
    assert ("lane-a", "syndicate/features/a.py") in claims
    assert ("lane-b", "syndicate/features/b.py") in claims


def test_a_path_BEFORE_the_word_never_is_still_claimed() -> None:
    """`never` is a PREFIX cut, so it governs what follows it and nothing else.
    A file mentioned before the word is a real claim and must survive."""
    text = """## OPEN

### lane-c — OPEN — opened 2026-09-03 — session ccc
- Files: `syndicate/features/c.py` (never deployed), and that is all.
- Blocked by: none.

## Archived lanes
"""
    assert ("lane-c", "syndicate/features/c.py") in CHECKER.claims(text)


def test_the_marker_tuple_has_exactly_one_definition() -> None:
    """There is nothing left to keep in sync: `_DISCLAIMER_MARKERS` is defined
    once, in `.claude/hooks/lane_claims.py`, and both readers import it.

    THIS TEST USED TO SCRAPE TWO FILES FOR THE TUPLE AND COMPARE THEM, and it
    had been failing on `origin/main` since the parser was extracted out of
    `lane-guard.py` -- `re.search` returned None for the hook and the test died
    on `AttributeError: 'NoneType' object has no attribute 'group'`, never
    reaching its assertion. Measured 2026-09-04: red at HEAD, same line, before
    any of this session's changes.

    That is the third instance of one failure mode. A test that compares two
    copies of a definition depends on being able to FIND both copies, so
    consolidating them -- the actual fix -- breaks the test in a way that reads
    like an error rather than a pass. The durable form is to assert the
    single-sourcing itself.
    """
    sys.path.insert(0, str(ROOT / ".claude" / "hooks"))
    import lane_claims

    assert CHECKER._DISCLAIMER_MARKERS is lane_claims._DISCLAIMER_MARKERS, (
        "the checker has its own marker tuple again")
    assert "never" in lane_claims._DISCLAIMER_MARKERS, (
        "the prohibition marker this file exists for is gone")

    # And no second definition anywhere on the enforcement path.
    definition = re.compile(r"^_DISCLAIMER_MARKERS\s*=\s*\(", re.M)
    definers = [p for p in (
        ROOT / ".claude" / "hooks" / "lane_claims.py",
        ROOT / ".claude" / "hooks" / "lane-guard.py",
        ROOT / "scripts" / "check_lane_invariants.py",
    ) if definition.search(p.read_text(encoding="utf-8", errors="replace"))]
    assert definers == [ROOT / ".claude" / "hooks" / "lane_claims.py"], (
        f"expected exactly one definition, in lane_claims.py; found {definers}")


def test_a_claimed_path_must_not_contain_a_marker_word() -> None:
    """THE TRAP THIS LANE FELL INTO. The first version of this test file was
    named `test_lane_guard_never_marker.py`; the marker cut INSIDE its own path
    and silently dropped a real claim. Substring matching is what makes the
    other markers work (`not touch` covering `not touched`), so the rule is on
    the NAMING side: never put a marker word in a path you intend to claim."""
    markers = CHECKER._DISCLAIMER_MARKERS
    own = Path(__file__).name.lower()
    hits = [m for m in markers if m in own]
    assert not hits, f"this test's own filename contains marker(s) {hits} and would not be claimable"
