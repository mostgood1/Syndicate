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


def test_disclaimer_markers_match_the_hook_source():
    """The copied `_DISCLAIMER_MARKERS` tuple must not drift from lane-guard.py's
    either -- same failure mode as the regexes above, just a list instead of a
    pattern. This is the sync check the FILES_RE drift (2026-08-19) showed was
    missing: a test that pins REGEXES alone still let the marker list rot."""
    src = HOOK.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"^_DISCLAIMER_MARKERS\s*=\s*\((.*?)\n\)", src, re.MULTILINE | re.DOTALL)
    assert m, "_DISCLAIMER_MARKERS not found in lane-guard.py -- the hook changed shape"
    hook_markers = eval("(" + m.group(1) + ")")  # noqa: S307 - our own repo file, literal only
    assert mod._DISCLAIMER_MARKERS == hook_markers, (
        "_DISCLAIMER_MARKERS has DRIFTED from lane-guard.py; this check is now "
        "measuring something the guard does not"
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


# --------------------------------------------------------------------------
# 3. A CONFLICTED FILE IS NOT A LEDGER WITH VIOLATIONS -- it is two files.
#
# MEASURED 2026-08-30: lanes.md sat `UU` in the shared tree with markers at
# 3724/3778/3966 and this script printed INVARIANTS HOLD, having parsed BOTH
# sides as real lanes. Three OPEN lanes existed only on one side, with zero
# copies in HEAD and zero in origin/main.
# --------------------------------------------------------------------------

CONFLICTED = """## OPEN

<<<<<<< Updated upstream
### alpha — OPEN — opened 2026-08-17
- Files: `a/one.py`.
=======
### alpha — OPEN — opened 2026-08-17
- Files: `a/one.py`.

### only-on-the-stashed-side — OPEN — opened 2026-08-30
- Files: `b/two.py`.
>>>>>>> Stashed changes
"""


def test_a_conflicted_ledger_is_refused_with_its_own_exit_code():
    """3, not 1. "This cannot be checked" is a different answer from "this
    failed", and both are different from the green it used to print."""
    assert mod.main([_write(CONFLICTED)]) == 3


def test_the_marker_lines_are_named(capsys):
    """A refusal nobody can act on is a refusal people learn to bypass."""
    mod.main([_write(CONFLICTED)])
    out = capsys.readouterr().out
    assert "UNRESOLVED MERGE MARKERS" in out
    # Derived, not hardcoded: the point is that EVERY marker the parser found
    # is named in the output, not that they sit at particular offsets.
    for number, _line in mod.conflict_markers(CONFLICTED):
        assert f"line {number}:" in out
    assert "INVARIANTS HOLD" not in out


def test_the_regression_itself_the_duplicate_no_longer_reads_as_two_lanes():
    """`alpha` appears on BOTH sides. The old code counted that as two
    legitimate OPEN lanes contesting `a/one.py` -- or, with identical Files
    blocks, as a clean ledger. Either way it answered a question about a file
    that does not exist."""
    assert len(mod.conflict_markers(CONFLICTED)) == 2
    assert mod.main([_write(CONFLICTED)]) == 3


def test_a_lane_present_on_only_one_side_is_why_this_matters():
    """The refusal has to fire BEFORE parsing, because after parsing the
    one-sided lane looks exactly like a normal lane and nothing flags that
    choosing the other side deletes it."""
    assert "only-on-the-stashed-side" in CONFLICTED
    assert mod.main([_write(CONFLICTED)]) == 3


def test_a_setext_underline_is_NOT_a_conflict_marker():
    """`=======` on its own line is a markdown H1 underline. Keying on it would
    refuse legitimate ledgers, so only the labelled open/close markers count."""
    setext = "Heading\n=======\n\n## OPEN\n\n### alpha — OPEN — opened 2026-08-17\n- Files: `a/one.py`.\n"
    assert mod.conflict_markers(setext) == []
    assert mod.main([_write(setext)]) == 0


def test_a_clean_ledger_still_passes():
    """The guard must not have made everything red."""
    assert mod.conflict_markers(ONE_HOLDER) == []
    assert mod.main([_write(ONE_HOLDER)]) == 0
