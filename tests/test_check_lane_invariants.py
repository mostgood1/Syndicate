"""The lane-invariant check must parse with the module the guard enforces with.

It no longer COPIES that parser, so these tests no longer compare two copies.
They assert there is only one.

WHAT THIS FILE USED TO DO, AND WHY IT STOPPED WORKING. `check_lane_invariants.py`
held its own four regexes and its own `_DISCLAIMER_MARKERS`, copied out of
`.claude/hooks/lane-guard.py` because that module is a hook and could not be
imported. Five tests read the hook as TEXT and pinned the copies against a
`re.search` for `^HEADER_RE = re.compile(...)$`.

**Then the hook's parser was extracted into `.claude/hooks/lane_claims.py`, and
all five tests went red on `assert m` -- "not found in lane-guard.py".** They
stayed red on `origin/main` while `check_lane_invariants.py` exited 0 and printed
INVARIANTS HOLD, so nothing surfaced it at session start. Measured 2026-09-04:
the four regexes and the marker tuple had NOT drifted; four OTHER things had,
because the test could only ever pin what it had been told to look for. The
worst of them made a whole lane's claim set read as EMPTY -- see
`test_the_four_divergences_the_old_pinning_could_not_see`.

**A test that compares two copies is a worse instrument than one definition.**
It can only fail when it can still FIND both copies, it can only cover what
someone remembered to list, and its passing says nothing about the parts nobody
listed. `check_lane_invariants.py` now imports from `lane_claims.py` -- the same
import `lane-guard.py` does -- and section 1 below asserts the imported names
are the SAME OBJECTS, which is a claim about identity that cannot be satisfied
by a copy that happens to agree today.
"""
from __future__ import annotations

import ast
import importlib.util
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
HOOKS = REPO / ".claude" / "hooks"
sys.path.insert(0, str(HOOKS))
import lane_claims  # noqa: E402 - needs the path insert above

spec = importlib.util.spec_from_file_location(
    "check_lane_invariants", REPO / "scripts" / "check_lane_invariants.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


# --------------------------------------------------------------------------
# 1. There must be ONE definition, not two that agree.
# --------------------------------------------------------------------------

SHARED_NAMES = [
    "HEADER_RE", "LANE_RE", "ASCII_LANE_RE", "OPEN_RE", "FILES_RE", "FIELD_RE",
    "_DISCLAIMER_MARKERS", "_claimable_prefix", "_claims", "_paths_in",
]


@pytest.mark.parametrize("name", SHARED_NAMES)
def test_the_checker_shares_lane_claims_object_it_does_not_copy_it(name):
    """`is`, not `==`. An equal copy is exactly what this file used to permit.

    Equality passes for a copy that agrees TODAY, which is the state the repo
    was in on 2026-09-04 while four real divergences were live.

    THIS TEST IS NECESSARY AND NOT SUFFICIENT, and the reason is worth knowing
    before trusting it: **`re.compile` memoises.** Re-pasting
    `HEADER_RE = re.compile(r"^###\\s")` into `check_lane_invariants.py` hands
    back the very object `lane_claims` already compiled, so `is` passes on a
    genuine copy. Measured 2026-09-04 by mutation -- the copy was inserted, all
    30 tests stayed green, and it took reading `re`'s cache to see why. The
    identity check still binds the tuple and the four functions, where nothing
    is interned; `test_the_checker_defines_none_of_them_itself` is what closes
    the regex half, by asking the source instead of the object.
    """
    assert hasattr(mod, name), (
        f"{name} is not exposed by check_lane_invariants -- if it was renamed, "
        f"rename it here; if it was re-COPIED, that is the regression")
    assert getattr(mod, name) is getattr(lane_claims, name), (
        f"{name} is NOT lane_claims' object. A private copy has been "
        f"reintroduced and this check will drift from the guard again")


def test_the_checker_defines_none_of_them_itself():
    """Every shared name must arrive by import and be assigned nowhere.

    Asked of the AST, not of a regex over the text, so a definition cannot hide
    behind formatting -- and asked about ABSENCE in the file under test, which
    is what makes it survive the next refactor of the hook. The old drift tests
    scraped a DIFFERENT file for the PRESENCE of a definition, so moving that
    definition broke the test rather than failing it.
    """
    tree = ast.parse((REPO / "scripts" / "check_lane_invariants.py").read_text(
        encoding="utf-8", errors="replace"))

    # MODULE SCOPE, not `tree.body`: the import sits inside a `try:` (it has a
    # refusal branch), and a re-pasted definition could just as easily land in
    # an `if`. Recurse through those, and stop at `def`/`class` -- a local named
    # `FILES_RE` inside some helper is not a second definition of the parser.
    def module_scope(body):
        for node in body:
            yield node
            if isinstance(node, ast.Try):
                yield from module_scope(node.body + node.orelse + node.finalbody)
                for handler in node.handlers:
                    yield from module_scope(handler.body)
            elif isinstance(node, (ast.If, ast.With)):
                yield from module_scope(node.body + getattr(node, "orelse", []))

    nodes = list(module_scope(tree.body))

    imported = {alias.asname or alias.name
                for node in nodes
                if isinstance(node, ast.ImportFrom) and node.module == "lane_claims"
                for alias in node.names}
    missing = [n for n in SHARED_NAMES if n not in imported]
    assert not missing, f"not imported from lane_claims: {missing}"

    # An assignment OR a `def`. Re-copying `_claimable_prefix` would be the
    # second, and it is the one that cost this repo a whole Files line.
    defined = {t.id for node in nodes if isinstance(node, ast.Assign)
               for t in node.targets if isinstance(t, ast.Name)}
    defined |= {node.name for node in nodes
                if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
    redefined = sorted(defined & set(SHARED_NAMES))
    assert not redefined, (
        f"{redefined} is BOTH imported from lane_claims and defined here. That "
        f"is the two-copies state this module was rewritten to end -- and note "
        f"`is` will NOT catch it for a regex, because re.compile memoises")


def test_lane_guard_imports_the_same_module_so_the_chain_is_closed():
    """Identity with `lane_claims` only matters because the GUARD uses it too.

    Read as text: importing `lane-guard.py` runs `main()` and `sys.exit()`s.
    That is a real constraint on the HOOK and the reason this indirection
    exists -- but it is not a constraint on `lane_claims.py`, which is a pure
    library. This assertion is what makes the identity above load-bearing
    rather than two modules agreeing with each other about nothing.
    """
    src = (HOOKS / "lane-guard.py").read_text(encoding="utf-8", errors="replace")
    assert "from lane_claims import" in src, (
        "lane-guard.py no longer imports lane_claims -- the enforcement path "
        "has moved and check_lane_invariants.py must follow it, not this test")
    assert "_claims," in src, "lane-guard.py no longer imports the claim parser"


def test_the_four_divergences_the_old_pinning_could_not_see():
    """The regression corpus. Every case reproduced on `origin/main`, 2026-09-04.

    All four passed the old five drift tests -- because those pinned four
    regexes and a tuple, and none of these is any of those. Case B is the one
    that mattered: the checker returned ZERO claims for the lane, and a lane
    with no claims cannot contest a file, so `every claimed file has exactly one
    OPEN holder` was satisfied vacuously and INVARIANTS HOLD printed green.
    """
    cases = {
        "A. ASCII-hyphen lane header":
            "## OPEN\n\n### alpha - OPEN - opened 2026-09-04\n- Files: `a/one.py`.\n",
        "B. disclaimer marker INSIDE a backticked filename":
            "## OPEN\n\n### alpha \u2014 OPEN \u2014 opened 2026-09-04\n"
            "- Files: `scripts/archive_released_lanes.py`, `tests/t.py`.\n",
        "C. blank line then indented prose":
            "## OPEN\n\n### alpha \u2014 OPEN \u2014 opened 2026-09-04\n"
            "- Files: `a/one.py`.\n\n  `b/two.py` mentioned in prose.\n",
        "D. backslash path":
            "## OPEN\n\n### alpha \u2014 OPEN \u2014 opened 2026-09-04\n"
            "- Files: `scripts\\win.py`.\n",
    }
    for label, text in cases.items():
        assert mod.claims(text) == set(lane_claims._claims(text)), label

    # And the specific readings, so a future change that makes both sides wrong
    # in the same way still fails here.
    assert mod.claims(cases["A. ASCII-hyphen lane header"]) == {("alpha", "a/one.py")}
    assert mod.claims(cases["B. disclaimer marker INSIDE a backticked filename"]) == {
        ("alpha", "scripts/archive_released_lanes.py"), ("alpha", "tests/t.py")}, (
        "the whole Files line was dropped -- `_claimable_prefix` is cutting "
        "inside the filename again")
    assert mod.claims(cases["C. blank line then indented prose"]) == {("alpha", "a/one.py")}
    assert mod.claims(cases["D. backslash path"]) == {("alpha", "scripts/win.py")}


def test_the_checker_and_the_guard_agree_on_the_LIVE_ledger():
    """Synthetic corpora are built by whoever is looking. This one is not.

    Skipped rather than failed when `lanes.md` is absent: a worktree checked out
    without it is not a drift.
    """
    ledger = REPO / ".syndicate" / "lanes.md"
    if not ledger.exists():
        pytest.skip("no .syndicate/lanes.md in this tree")
    text = ledger.read_text(encoding="utf-8", errors="replace")
    assert mod.claims(text) == set(lane_claims._claims(text))


def test_an_unimportable_parser_must_not_read_as_green():
    """The refusal path. `lane-guard.py` fails OPEN on a missing `lane_claims`
    -- a guard that blocks every edit is worse than no guard. This file is a
    CHECK, and the inverse applies: its whole output is a verdict, so the one
    thing it must never do is print a green one it did not compute.

    Asserted on the source because triggering it for real means breaking the
    import for the whole session.
    """
    src = (REPO / "scripts" / "check_lane_invariants.py").read_text(
        encoding="utf-8", errors="replace")
    head = src[:src.index("def conflict_markers")]
    assert "from lane_claims import" in head
    assert "sys.exit(2)" in head, (
        "the import guard no longer refuses -- if it now falls back to a local "
        "copy, that is the drift this whole file exists to prevent")


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
    hits = mod.prose_paths_in_files_blocks(text)
    assert hits, "the hint must flag it"
    assert all(c for _line, c in hits), (
        "no disclaimer marker here, so the phantom really is a claim")


def test_a_RELEASED_line_is_flagged_but_reported_as_NOT_claiming():
    """The hint's MESSAGE was wrong, not the ledger.

    `_claimable_prefix` cuts at the first disclaimer marker, so a `released:`
    line claims nothing. The hint still surfaces it -- a human should confirm
    the marker is deliberate -- but it must not say the path becomes a claim.
    Measured 2026-09-02 on `artifact_publisher.py`: the old wording ("each
    becomes a CLAIM") was read at face value and reported as a live false claim
    on a ledger that was correct.
    """
    text = """## OPEN

### alpha — OPEN — opened 2026-09-02
- Files: `a/one.py`,
  released: `syndicate/features/shared/artifact_publisher.py` (claimed by nobody).
"""
    held = mod.claims(text)
    assert ("alpha", "a/one.py") in held, "the real claim survives"
    assert not [p for _s, p in held if "artifact_publisher" in p], (
        "a released: path must not be claimed")
    hits = mod.prose_paths_in_files_blocks(text)
    assert hits, "the line is still surfaced for a human to eyeball"
    assert not any(c for _line, c in hits), (
        "and it must be reported as NOT claiming")


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


# --------------------------------------------------------------------------
# Orphaned lane markers: the check that would have caught 2026-09-04.
#
# A session rebuilt `lanes.md` from `git show origin/main:.syndicate/lanes.md`
# and another session's block -- uncommitted, primary-tree-only -- was dropped.
# No git guard fired: a rebuild is a plain file write, and `discard-guard.py`
# watches git operations. The check that WAS run, "0 deletions vs origin/main",
# cannot see this by construction, because upstream never had the block.
#
# `.current-lane.<session>` survives, because it is a different file.
# --------------------------------------------------------------------------

def _lane_dir(tmp_path, *, lanes="", closed=None, markers=None):
    d = tmp_path / ".syndicate"
    d.mkdir()
    (d / "lanes.md").write_text(lanes, encoding="utf-8")
    if closed is not None:
        (d / "lanes_closed.md").write_text(closed, encoding="utf-8")
    for session, slug in (markers or {}).items():
        (d / f".current-lane.{session}").write_text(slug, encoding="utf-8")
    return d / "lanes.md"


def test_a_marker_whose_block_exists_nowhere_fails(tmp_path):
    """THE 2026-09-04 CASE, reproduced: the block is gone, the marker remains."""
    path = _lane_dir(
        tmp_path,
        lanes="## OPEN\n\n### some-other-lane — OPEN\n- Files: a.py\n",
        markers={"c4287631": "render-events-nondict-reason"},
    )
    missing, stale = mod.orphaned_lane_markers(path.read_text(encoding="utf-8"), str(path))
    assert [slug for slug, _ in missing] == ["render-events-nondict-reason"]
    assert stale == []


def test_a_marker_for_an_archived_lane_is_only_a_hint(tmp_path):
    """A FAIL here would be noise -- the lane was closed and the marker was
    never emptied -- and a noisy check is one people learn to skip."""
    path = _lane_dir(
        tmp_path,
        lanes="## OPEN\n",
        closed="### done-lane — CLOSED\n",
        markers={"abc": "done-lane"},
    )
    missing, stale = mod.orphaned_lane_markers(path.read_text(encoding="utf-8"), str(path))
    assert missing == []
    assert [slug for slug, _ in stale] == ["done-lane"]


def test_an_emptied_marker_is_not_a_lane(tmp_path):
    """`/lane close` empties the marker; that is success, not an orphan."""
    path = _lane_dir(tmp_path, lanes="## OPEN\n", markers={"abc": "   \n"})
    missing, stale = mod.orphaned_lane_markers(path.read_text(encoding="utf-8"), str(path))
    assert missing == [] and stale == []


def test_a_live_block_satisfies_its_marker(tmp_path):
    path = _lane_dir(
        tmp_path,
        lanes="## OPEN\n\n### held-lane — OPEN\n- Files: a.py\n",
        markers={"abc": "held-lane"},
    )
    missing, stale = mod.orphaned_lane_markers(path.read_text(encoding="utf-8"), str(path))
    assert missing == [] and stale == []


def test_a_bom_does_not_hide_a_block(tmp_path):
    """A UTF-8 BOM survives errors="replace" and glues itself to the first
    heading, which would report a lane that is present as destroyed."""
    path = _lane_dir(tmp_path, lanes="\ufeff### held-lane — OPEN\n", markers={"abc": "held-lane"})
    missing, stale = mod.orphaned_lane_markers(
        path.read_text(encoding="utf-8").lstrip("\ufeff"), str(path))
    assert missing == [] and stale == []


def test_main_exits_nonzero_on_an_orphan(tmp_path, capsys):
    """The check must FAIL the run, not merely mention it."""
    path = _lane_dir(
        tmp_path,
        lanes="## OPEN\n\n### kept — OPEN\n- Files: a.py\n",
        markers={"c4287631": "destroyed-lane"},
    )
    assert mod.main([str(path), "--quiet"]) == 1
    out = capsys.readouterr().out
    assert "destroyed-lane" in out and "in NO ledger file" in out


# ---------------------------------------------------------------------------
# 2026-09-05: "in NO ledger file" was ALSO reported for a block that exists on
# origin/main and merely has not been pulled. The marker set is CURRENT (it is
# written into the primary tree the moment a lane opens) while `lanes.md` in
# that tree is a working copy that runs behind -- measured that day at 58
# commits and 45 headers against 101 upstream. The remedies are opposite:
# PULL, versus restore a block that genuinely exists nowhere. The old message
# named the wrong one and asserted "upstream cannot have it" about a case where
# upstream demonstrably did.
# ---------------------------------------------------------------------------


def _fake_git(monkeypatch, mapping, *, fail=False):
    """Stand in for `git show <ref>:.syndicate/<file>`.

    `mapping` is {filename: text}; anything absent returns rc=1, which is what
    git does for a path that is not in the ref.
    """
    import subprocess as _sp

    class _R:
        def __init__(self, rc, out):
            self.returncode, self.stdout = rc, out

    def run(cmd, **kw):
        if fail:
            raise OSError("git not available")
        name = cmd[-1].rsplit("/", 1)[-1]
        if name not in mapping:
            return _R(1, b"")
        return _R(0, mapping[name].encode("utf-8"))

    monkeypatch.setattr(mod.subprocess, "run", run)
    return _sp


def test_upstream_lane_slugs_reads_every_ledger_file(monkeypatch):
    _fake_git(monkeypatch, {
        "lanes.md": "### live-one — OPEN\n",
        "lanes_history.md": "### trimmed-one — CLOSED\n",
    })
    got = mod.upstream_lane_slugs(pathlib.Path(".syndicate"))
    assert got == {"live-one", "trimmed-one"}


def test_upstream_unknown_is_none_not_empty(monkeypatch):
    """An unknown that defaults to the PERMISSIVE branch turns a failed lookup
    into a relaxed rule. None keeps the strict verdict; a set() would silently
    assert that upstream has nothing."""
    _fake_git(monkeypatch, {}, fail=True)
    assert mod.upstream_lane_slugs(pathlib.Path(".syndicate")) is None
    # No ledger file present in the ref at all is also UNKNOWN, not "empty".
    _fake_git(monkeypatch, {})
    assert mod.upstream_lane_slugs(pathlib.Path(".syndicate")) is None


def test_a_block_that_is_only_upstream_is_a_pull_hint_not_a_failure(tmp_path, monkeypatch, capsys):
    """THE 2026-09-05 CASE: `web-oom-burst-source`'s marker was in the primary
    tree and its block was on origin/main. This must not fail, and must not
    tell anyone to rewrite the block."""
    path = _lane_dir(
        tmp_path,
        lanes="## OPEN\n\n### kept — OPEN\n- Files: a.py\n",
        markers={"b2b5b45b": "web-oom-burst-source"},
    )
    _fake_git(monkeypatch, {"lanes.md": "### web-oom-burst-source — OPEN\n"})
    assert mod.main([str(path), "--quiet"]) == 0
    out = capsys.readouterr().out
    assert "IS on origin/main" in out and "PULL, do not restore" in out
    assert "upstream cannot have it" not in out


def test_a_block_upstream_does_not_have_still_fails(tmp_path, monkeypatch, capsys):
    """The reachability half: with git answering and the slug absent upstream,
    the verdict must still be FAIL. Without this, the new branch could swallow
    every orphan and the test above would pass for the wrong reason."""
    path = _lane_dir(
        tmp_path,
        lanes="## OPEN\n\n### kept — OPEN\n- Files: a.py\n",
        markers={"c4287631": "destroyed-lane"},
    )
    _fake_git(monkeypatch, {"lanes.md": "### something-else — OPEN\n"})
    assert mod.main([str(path), "--quiet"]) == 1
    out = capsys.readouterr().out
    assert "destroyed-lane" in out
    assert "origin/main does not carry it either" in out


def test_when_git_cannot_answer_the_message_does_not_claim_it_checked(tmp_path, monkeypatch, capsys):
    """A healthy-looking reading is evidence only once you know what makes it
    read unhealthy. With no git answer the check must stay a FAIL AND must say
    upstream was not consulted, rather than asserting anything about it."""
    path = _lane_dir(
        tmp_path,
        lanes="## OPEN\n\n### kept — OPEN\n- Files: a.py\n",
        markers={"c4287631": "destroyed-lane"},
    )
    _fake_git(monkeypatch, {}, fail=True)
    assert mod.main([str(path), "--quiet"]) == 1
    out = capsys.readouterr().out
    assert "upstream NOT CHECKED" in out
    assert "upstream cannot have it" not in out
