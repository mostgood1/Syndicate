"""The lane-invariant check must agree with the hook it copies from.

The script parses `lanes.md` with regexes COPIED out of `.claude/hooks/lane-guard.py`
because that module cannot be imported (it is a hook: it runs `main()` at import
and `sys.exit()`s on EOF stdin, killing the caller with exit code 0 and no
output). Copying is the only option, and drift is the risk it creates -- so the
first test reads the hook's SOURCE and pins the four regexes against it.
"""
from __future__ import annotations

import importlib.util
import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
HOOK = REPO / ".claude" / "hooks" / "lane-guard.py"

spec = importlib.util.spec_from_file_location(
    "check_lane_invariants", REPO / "scripts" / "check_lane_invariants.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


# --------------------------------------------------------------------------
# 1. The copied regexes must not drift from the hook's.
# --------------------------------------------------------------------------

@pytest.mark.skipif(not HOOK.exists(), reason="lane-guard.py not present")
@pytest.mark.parametrize("name", ["HEADER_RE", "LANE_RE", "OPEN_RE", "FILES_RE"])
def test_regex_matches_the_hook_source(name):
    """Read the hook as TEXT. Importing it would exit the test process."""
    src = HOOK.read_text(encoding="utf-8", errors="replace")
    m = re.search(rf"^{name}\s*=\s*re\.compile\((.+)\)$", src, re.MULTILINE)
    assert m, f"{name} not found in lane-guard.py -- the hook changed shape"
    hook_pattern = eval(m.group(1))  # noqa: S307 - our own repo file, literal only
    assert getattr(mod, name).pattern == hook_pattern, (
        f"{name} has DRIFTED from lane-guard.py; this check is now measuring "
        f"something the guard does not"
    )


# --------------------------------------------------------------------------
# 2. The invariants themselves.
# --------------------------------------------------------------------------

ONE_HOLDER = """## OPEN

### alpha — OPEN — opened 2026-08-17
- Files: `a/one.py`, `a/two.py`.

### beta — OPEN — opened 2026-08-17
- Files: `b/three.py`.
"""

CONTESTED = """## OPEN

### alpha — OPEN — opened 2026-08-17
- Files: `shared/thing.py`.

### beta — OPEN — opened 2026-08-17
- Files: `shared/thing.py`.
"""


def test_clean_ledger_passes():
    assert mod.contested_files(mod.claims(ONE_HOLDER)) == {}
    assert mod.open_lanes_under_archived(ONE_HOLDER) == []
    assert mod.main([_write(ONE_HOLDER)]) == 0


def test_two_open_lanes_on_one_file_fails():
    contested = mod.contested_files(mod.claims(CONTESTED))
    assert contested == {"shared/thing.py": ["alpha", "beta"]}
    assert mod.main([_write(CONTESTED)]) == 1


def test_a_closed_lane_does_not_contest():
    """Only OPEN lanes hold claims -- a closed one sharing a path is fine."""
    text = CONTESTED.replace("### beta — OPEN", "### beta — CLOSED-VERIFIED")
    assert mod.contested_files(mod.claims(text)) == {}


def test_open_under_archived_is_caught():
    text = ONE_HOLDER + "\n## Archived lanes\n\n### gamma — OPEN — opened 2026-08-17\n- Files: `c/four.py`.\n"
    assert mod.open_lanes_under_archived(text) == ["gamma"]
    assert mod.main([_write(text)]) == 1


def test_archived_closed_lane_is_fine():
    text = ONE_HOLDER + "\n## Archived lanes\n\n### gamma — CLOSED 2026-08-17\n- Files: `c/four.py`.\n"
    assert mod.open_lanes_under_archived(text) == []


def test_open_anywhere_in_the_first_segment_counts():
    """The hook's rule, and the one an earlier archive pass got NARROWER than:
    `\\bOPEN\\b` anywhere before the second em-dash, not `— OPEN` immediately."""
    text = "## OPEN\n\n### alpha — RE-TAKEN, still OPEN — opened 2026-08-17\n- Files: `a/one.py`.\n"
    assert ("alpha", "a/one.py") in mod.claims(text)


def test_a_disclaimer_under_files_becomes_a_phantom_claim():
    """Documents the hazard rather than fixing it -- the parser is the guard's."""
    text = (
        "## OPEN\n\n### alpha — OPEN — opened 2026-08-17\n"
        "- Files: `a/one.py`.\n"
        "  `beta` names `other/thing.py` as a candidate — a DIFFERENT file.\n"
    )
    assert ("alpha", "other/thing.py") in mod.claims(text), "phantom no longer reproduces"
    assert mod.prose_paths_in_files_blocks(text), "the hint must flag it"


def test_a_new_top_level_bullet_ends_the_files_block():
    """The documented FIX for the phantom: move the disclaimer out."""
    text = (
        "## OPEN\n\n### alpha — OPEN — opened 2026-08-17\n"
        "- Files: `a/one.py`.\n"
        "- Collision check: `beta` names `other/thing.py` as a candidate.\n"
    )
    assert ("alpha", "other/thing.py") not in mod.claims(text)


def test_missing_file_exits_2_not_0():
    """A check that cannot read its input must not report success."""
    assert mod.main(["does/not/exist.md"]) == 2


@pytest.fixture(autouse=True)
def _tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "_TEST_TMP", tmp_path, raising=False)
    globals()["_TMP"] = tmp_path


def _write(text: str) -> str:
    p = _TMP / "lanes.md"
    p.write_text(text, encoding="utf-8")
    return str(p)
