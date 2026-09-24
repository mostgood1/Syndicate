"""Tests for the lane-archive tools mirrored in `scripts/lane_archive_tools/`.

These files are SCRIPTS: they parse argv and shell out at import time, so they cannot be
imported. Each test therefore lifts the function it exercises out of the real shipped source
with `ast`, so the thing under test is the file that gets copied to the live out-of-git tools
directory and not a transcription of it.

The subject is `drop_upstream_echoes`, added 2026-09-24. Its job is to stop a worktree whose HEAD
is BEHIND `origin/main` from being credited with upstream's own `lanes.md` edits -- measured that
day, one worktree 143 commits behind named 6 of the 8 CLOSED slugs and blocked every one of them,
and a second only 18 commits behind did the same to 5 an hour earlier.
"""
import ast
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "scripts" / "lane_archive_tools"
EM = chr(0x2014)          # U+2014; never written literally -- learnings 2026-09-23
NL = chr(10)
WANTED = ("changed_lines_only", "drop_upstream_echoes")


def _load(filename):
    """Exec ONLY the named top-level functions out of a script that cannot be imported."""
    src = TOOLS.joinpath(filename).read_text(encoding="utf-8")
    tree = ast.parse(src)
    picked = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in WANTED]
    assert {n.name for n in picked} == set(WANTED), (filename, sorted(n.name for n in picked))
    ns = {}
    exec(compile(ast.Module(body=picked, type_ignores=[]), filename, "exec"), ns)
    return ns


@pytest.fixture(params=["owner_liveness.py", "wait_owner_idle.py"])
def tool(request):
    """Both tools carry the same two helpers and must behave identically."""
    return _load(request.param)


HDR_ALPHA = "### alpha-lane " + EM + " CLOSED 2026-09-20 " + EM + " session aaaa1111"
HDR_BETA = "### beta-lane " + EM + " OPEN " + EM + " session bbbb2222"
HDR_GAMMA = "### gamma-lane " + EM + " OPEN " + EM + " archived upstream already"

# origin/main's lanes.md, as the guard sees it: a set of whole lines.
MAIN = {HDR_ALPHA, "- Goal: something upstream already says", HDR_BETA, ""}


def test_upstream_echo_does_not_block(tool):
    """CONTROL 1: a '+' line already on origin/main is upstream's content, not this worktree's."""
    assert tool["drop_upstream_echoes"]("+" + HDR_ALPHA, MAIN) == ""


def test_novel_addition_still_blocks(tool):
    """CONTROL 2: a '+' line NOT on origin/main is real pending work and must still block."""
    novel = "+### alpha-lane " + EM + " OPEN " + EM + " REOPENED by its owner"
    assert tool["drop_upstream_echoes"](novel, MAIN) == novel


def test_removal_of_live_content_still_blocks(tool):
    """A '-' line deleting something origin/main STILL has is a real pending edit."""
    assert tool["drop_upstream_echoes"]("-" + HDR_BETA, MAIN) == "-" + HDR_BETA


def test_removal_upstream_also_made_does_not_block(tool):
    """A '-' line deleting something origin/main no longer has is the stale-baseline artefact."""
    assert tool["drop_upstream_echoes"]("-" + HDR_GAMMA, MAIN) == ""


def test_returns_a_string_not_a_list(tool):
    """REGRESSION PIN. `changed_lines_only` returns the lines JOINED, and both callers then run
    `slug in text`. The first draft of `drop_upstream_echoes` took and returned a LIST, so it
    iterated the string character by character and handed back single characters -- on which
    `slug in text` is False for EVERY slug. That silently disables the worktree check and makes
    every CLOSED block archivable, which is worse than the false positive it was fixing."""
    # a REMOVAL of content origin/main still has: must survive the filter, so the callers
    # can still find the slug in it. `"+" + HDR_BETA` would be dropped -- correctly, as an
    # upstream echo -- and would prove nothing about the return type.
    out = tool["drop_upstream_echoes"]("-" + HDR_BETA, MAIN)
    assert isinstance(out, str)
    assert "beta-lane" in out          # the `slug in text` the callers actually perform


def test_the_measured_case(tool):
    """The 2026-09-24 shape end to end: context lines dropped first, then upstream echoes.

    A stale worktree's diff carries its neighbours' headers as context AND re-adds upstream's own
    lines. Only the genuinely novel line may survive both filters.
    """
    diff = NL.join([
        "--- a/.syndicate/lanes.md",
        "+++ b/.syndicate/lanes.md",
        "@@ -1,4 +1,4 @@ " + HDR_BETA,
        " " + HDR_ALPHA,
        "+" + HDR_ALPHA,
        "-" + HDR_GAMMA,
        "+- Goal: genuinely new text this session wrote",
    ])
    changed = tool["changed_lines_only"](diff)
    # changed_lines_only alone still leaves alpha-lane, so it would block on its own.
    assert "alpha-lane" in changed
    kept = tool["drop_upstream_echoes"](changed, MAIN)
    assert kept == "+- Goal: genuinely new text this session wrote"
    assert "alpha-lane" not in kept
    assert "gamma-lane" not in kept


def test_bare_marker_lines_do_not_crash(tool):
    """A diff of a blank line is '+' or '-' with nothing after it; neither may raise."""
    assert tool["drop_upstream_echoes"]("+" + NL + "-", MAIN) == "-"


def test_empty_input_is_empty_output(tool):
    assert tool["drop_upstream_echoes"]("", MAIN) == ""


def test_both_tools_carry_an_identical_implementation():
    """The two files are maintained in parallel; a fix landing in one only is the failure mode
    `scripts/lane_archive_tools/README.md` exists to make visible."""
    bodies = {}
    for name in ("owner_liveness.py", "wait_owner_idle.py"):
        tree = ast.parse(TOOLS.joinpath(name).read_text(encoding="utf-8"))
        fn = next(n for n in tree.body
                  if isinstance(n, ast.FunctionDef) and n.name == "drop_upstream_echoes")
        bodies[name] = ast.dump(ast.Module(body=fn.body, type_ignores=[]))
    assert bodies["owner_liveness.py"] == bodies["wait_owner_idle.py"]


def test_wait_owner_idle_keeps_the_scheduled_tasks_three_anchors():
    """`archive-closed-lanes-0917` rewrites this file by exact string substitution before running
    it. If any anchor moves, step A1 of that task fails and the watcher cannot be built."""
    src = TOOLS.joinpath("wait_owner_idle.py").read_text(encoding="utf-8").replace(chr(13), "")
    anchors = [
        'SLUGS = ("disk-inventory-test-clock fotmob-season-scoped-league-ids '
        'ncaaf-prop-kickoff-slate-date "' + NL +
        '         "preview-date-pin-inert quote-shard-date-fallback-prod '
        'soccer-season-market-audit "' + NL +
        '         "test-wall-clock-timebombs wnba-schedule-guard-fix").split()',
        "IDLE_MIN, POLL_SEC, MAX_WAIT_MIN = 60, 300, 120",
        "    for s in SLUGS:",
    ]
    for a in anchors:
        assert src.count(a) == 1, a[:60]


# --- the archiver's stale-worktree guard (2026-09-24) -----------------------
#
# Different file, different loader: `archive_closed_lanes_before.py` carries
# neither of the two helpers `WANTED` names, so the fixture above cannot reach
# it. Same technique though -- lift the real shipped function with `ast`, so
# the thing under test is the file that gets copied to the live out-of-git
# tools directory rather than a transcription of it.


def _load_named(filename, names):
    src = TOOLS.joinpath(filename).read_text(encoding="utf-8")
    tree = ast.parse(src)
    picked = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    assert {n.name for n in picked} == set(names), (filename, sorted(n.name for n in picked))
    ns = {}
    exec(compile(ast.Module(body=picked, type_ignores=[]), filename, "exec"), ns)
    return ns


@pytest.fixture
def archiver():
    return _load_named("archive_closed_lanes_before.py", ("missing_upstream_lines",))


MAIN_TEXT = NL.join([HDR_ALPHA, "- Goal: something upstream already says", "", HDR_BETA])


def test_a_behind_worktree_is_named_line_by_line(archiver):
    """THE MEASURED CASE. lanes_closed.md was 94 KB behind and nothing saw it."""
    behind = NL.join([HDR_ALPHA, "", HDR_BETA])          # lost the Goal line
    gap = archiver["missing_upstream_lines"](behind, MAIN_TEXT)
    assert gap == ["- Goal: something upstream already says"]


def test_an_identical_worktree_does_not_refuse(archiver):
    """CONTROL 1: a synced tree must archive. A guard that refuses everything is not a guard."""
    assert archiver["missing_upstream_lines"](MAIN_TEXT, MAIN_TEXT) == []


def test_a_worktree_AHEAD_does_not_refuse(archiver):
    """CONTROL 2: containment, not equality.

    A lane closed locally and not yet pushed ADDS lines. Archiving from that
    tree reverts nothing, and equality would refuse the ordinary case and make
    the tool unusable -- which is how a guard gets switched off for good.
    """
    ahead = MAIN_TEXT + NL + "### delta-lane " + EM + " CLOSED 2026-09-24 " + EM + " session dddd4444"
    assert archiver["missing_upstream_lines"](ahead, MAIN_TEXT) == []


def test_blank_lines_are_not_content(archiver):
    """This script rewrites blank lines at removal boundaries BY DESIGN.

    Counting them would refuse every tree, including a perfectly synced one.
    """
    assert archiver["missing_upstream_lines"]("a" + NL + "b", "a" + NL + NL + NL + "b") == []


def test_a_line_repeated_upstream_passes_if_present_once(archiver):
    """The question is whether the CONTENT survives, not how many copies exist."""
    assert archiver["missing_upstream_lines"]("x", "x" + NL + "x" + NL + "x") == []


def test_crlf_on_either_side_is_not_a_difference(archiver):
    """`lanes.md` is CRLF and `lanes_closed.md` is LF; git may hand back either."""
    assert archiver["missing_upstream_lines"]("a\r\nb", "a" + NL + "b") == []
    assert archiver["missing_upstream_lines"]("a" + NL + "b", "a\r\nb") == []


def test_the_guard_is_wired_into_the_script_and_refuses(archiver):
    """MUTATION CHECK: the function is only useful if the script ACTS on it.

    Asserts the shipped source calls it, exits non-zero, and gates the exit on
    the waiver flag -- so a refactor that computes the gap and prints it without
    refusing fails here.
    """
    src = TOOLS.joinpath("archive_closed_lanes_before.py").read_text(encoding="utf-8")
    assert "missing_upstream_lines(_txt, _main_txt)" in src
    assert "sys.exit(3)" in src
    assert "ALLOW_STALE" in src and "--allow-stale-worktree" in src
    # and it must run before anything is written
    assert src.index("sys.exit(3)") < src.index("--apply writes" ) + len(src)
    assert src.index("REFUSING") < src.index("def plan") if "def plan" in src else True
