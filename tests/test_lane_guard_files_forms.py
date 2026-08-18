"""`lane-guard.py` must read every shape a Files declaration is actually written in.

Measured on the real `.syndicate/lanes.md`, 2026-08-18: 32 of 37 Files
declarations used `- Files:` and 5 used `- **Files (...):**`. The bold five
matched nothing, so they declared files no hook could see -- the worst available
state, because the ledger says a file is held and the guard lets anyone edit it.

The second, subtler gap: a declaration WRAPPED across lines puts its paths on
continuation lines that begin with a word rather than a `-`, and the claim loop
only read `-` bullets. `syndicate/features/shared/clv_join.py` looked guarded
only because the same basename appears in prose further down under a `-` that
the unbounded block ran into. An accidental claim from prose is not protection:
it moves the moment someone edits the prose.

Both directions are asserted here. Over-claiming is not the safe side of this
trade -- it blocks sessions from files nobody holds -- so the terminator and the
disclaimer skip are pinned too.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
GUARD = REPO_ROOT / ".claude" / "hooks" / "lane-guard.py"


@pytest.fixture(scope="module")
def guard():
    """Import the hook. It ends in `sys.exit(main())`, so importing RUNS it."""
    spec = importlib.util.spec_from_file_location("lane_guard_under_test", GUARD)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except SystemExit:
        pass
    assert hasattr(module, "_claims"), "guard loaded without _claims -- exit moved earlier"
    return module


def claims(guard, text):
    return set(guard._claims(text))


BOLD = """\
### demo-lane — OPEN — opened 2026-08-18 — session: demo
- **Goal (single testable outcome):** something measurable.
- **Files (exclusive to this lane):** `syndicate/features/shared/thing.py`,
  `tests/test_thing.py` (new). Collision check RUN: CLEAR.
- **DELIBERATELY OUT OF SCOPE — a collision I am not going to work around.**
  `syndicate/features/shared/not_mine.py` is held by another lane.
"""

PLAIN_WRAPPED = """\
### demo-lane — OPEN — opened 2026-08-18 — session: demo
- Files (claimed 2026-08-15 22:0xZ, collision check CLEAR via `lane-guard.py`'s
  own `_claims()`): `syndicate/features/shared/clv_join.py`,
  `tests/test_clv_close_timing.py` (new).
- **DEFECT FIXED AND VERIFIED — web `4316c907` live.**
  Recomputed the mean from the rows: `-0.3077` both ways, n=131.
"""


def test_bold_files_declaration_is_read(guard):
    """The five blocks in the real ledger that declared files nothing could see."""
    got = {p for _, p in claims(guard, BOLD)}
    assert "syndicate/features/shared/thing.py" in got
    assert "tests/test_thing.py" in got


def test_bold_field_terminates_the_block(guard):
    """The dangerous half: teaching FILES_RE the bold form without FIELD_RE
    would run the block into every later bullet and claim files nobody holds."""
    got = {p for _, p in claims(guard, BOLD)}
    assert "syndicate/features/shared/not_mine.py" not in got


def test_wrapped_continuation_lines_are_read(guard):
    """Paths on lines that begin with a word, not a `-`."""
    got = {p for _, p in claims(guard, PLAIN_WRAPPED)}
    assert "syndicate/features/shared/clv_join.py" in got
    assert "tests/test_clv_close_timing.py" in got


def test_prose_after_the_block_is_not_claimed(guard):
    """`-0.3077` was a real claim under the old parser. Numbers are not files."""
    got = {p for _, p in claims(guard, PLAIN_WRAPPED)}
    assert not any(p.startswith("-0.") for p in got), got


def test_closed_lane_claims_nothing(guard):
    closed = BOLD.replace("— OPEN —", "— CLOSED —")
    assert claims(guard, closed) == set()


def test_disclaimer_bullet_is_still_skipped(guard):
    """2026-08-15: "NOT claimed, deliberately" was parsed AS a claim, blocking
    the lane that actually owned the file. Scanning more lines must not undo it."""
    text = """\
### demo-lane — OPEN — opened 2026-08-18 — session: demo
- Files: `syndicate/features/shared/mine.py`
  - **NOT claimed, deliberately:** `syndicate/features/shared/theirs.py` -- held
    by OPEN lane `other-lane`.
"""
    got = {p for _, p in claims(guard, text)}
    assert "syndicate/features/shared/mine.py" in got
    assert "syndicate/features/shared/theirs.py" not in got


def test_the_real_ledger_parses_and_claims_something(guard):
    """A parser change that silently returned nothing would pass every unit test
    above while unguarding the entire repo."""
    lanes = (REPO_ROOT / ".syndicate" / "lanes.md").read_text(encoding="utf-8-sig")
    got = claims(guard, lanes)
    assert len(got) > 50, f"only {len(got)} claims parsed from the real ledger"
    assert any(p.endswith(".py") for _, p in got)
