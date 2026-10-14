"""The lane-claim checker's severity split, which is the whole design.

THE DEFECT THESE TESTS PIN, measured on the live ledger 2026-10-12. The
near-miss escalation ("an absent path with a close-named neighbour is a typo")
fired unconditionally, so it reported two deliberate `(NEW)` reservations as
typos, and for one of them the remedy it printed named a file that ANOTHER OPEN
lane claims -- advice that would have put two lanes on one path and had the
guard block one of them.

The ncaaf-live-cadence worked example (claimed `tests/test_ncaaf_live_autorun.py`
while creating `tests/test_ncaaf_lines_autorun.py`) is why the escalation exists
at all, so the first thing asserted here is that it still fails. Honouring the
`(NEW)` marker costs that catch nothing: that lane's typo'd path carries no
marker.
"""
import importlib.util
import os
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_lane_claims.py"
EM = chr(8212)


def _load():
    spec = importlib.util.spec_from_file_location("clc_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _repo(tmp_path, files, lanes):
    """A throwaway git repo holding `files`, with `lanes` as .syndicate/lanes.md."""
    for rel in files:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# fixture\n", encoding="utf-8")
    syn = tmp_path / ".syndicate"
    syn.mkdir(parents=True, exist_ok=True)
    (syn / "lanes.md").write_text(lanes, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    return tmp_path


def _run(tmp_path):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(tmp_path), PYTHONIOENCODING="utf-8")
    out = subprocess.run([sys.executable, str(SCRIPT)], env=env, cwd=str(tmp_path),
                         capture_output=True, text=True, encoding="utf-8", errors="replace")
    return out.returncode, (out.stdout or "") + (out.stderr or "")


def _block(slug, files):
    return (
        "## OPEN\n\n"
        "### %s %s OPEN %s opened 2026-10-12 %s session 00000000-0000-0000-0000-000000000000\n"
        "- Goal: fixture\n"
        "- Files: %s\n"
        "- Blocked by: none\n" % (slug, EM, EM, EM, files)
    )


def test_the_worked_example_still_fails_an_unmarked_typo(tmp_path):
    """ncaaf-live-cadence's shape: absent path, close neighbour, no (NEW) marker."""
    repo = _repo(tmp_path, ["tests/test_ncaaf_lines_autorun.py"],
                 _block("ncaaf-live-cadence", "tests/test_ncaaf_live_autorun.py"))
    code, out = _run(repo)
    assert code == 1, out
    assert "tests/test_ncaaf_live_autorun.py" in out
    assert "almost certainly a TYPO" in out
    assert "tests/test_ncaaf_lines_autorun.py" in out


def test_a_NEW_marked_reservation_is_not_called_a_typo(tmp_path):
    """The soccer case: the lane said (NEW), so the close name is not a verdict."""
    repo = _repo(tmp_path, ["tests/test_soccer_anytime_scorer.py"],
                 _block("soccer-live-anytime-scorer",
                        "tests/test_soccer_live_anytime_scorer.py (NEW)"))
    code, out = _run(repo)
    assert code == 0, out
    assert "almost certainly a TYPO" not in out
    assert "does not exist YET" in out
    assert "[marked NEW]" in out
    # the neighbour is still disclosed, as information
    assert "tests/test_soccer_anytime_scorer.py" in out


def test_a_neighbour_another_OPEN_lane_claims_is_never_offered(tmp_path):
    """The NBA case: the remedy must not name a file another lane holds."""
    lanes = (
        _block("nba-lineup-pools", "tests/test_nba_lineup_pools.py")
        + "\n### nba-pregame-lineup-pools %s OPEN %s opened 2026-10-12 %s session "
          "00000000-0000-0000-0000-000000000001\n"
          "- Goal: fixture\n"
          "- Files: tests/test_nba_pregame_lineup_pools.py\n"
          "- Blocked by: none\n" % (EM, EM, EM)
    )
    repo = _repo(tmp_path, ["tests/test_nba_pregame_lineup_pools.py"], lanes)
    code, out = _run(repo)
    assert "almost certainly a TYPO" not in out, out
    assert "nba-pregame-lineup-pools" in out
    assert "claim it" in out
    assert "tests/test_nba_lineup_pools.py" in out


def test_the_held_neighbour_rule_applies_even_without_a_NEW_marker(tmp_path):
    """Ownership alone is enough: an unmarked claim must not be sent to take it."""
    lanes = (
        _block("taker", "tests/test_thing_alpha.py")
        + "\n### holder %s OPEN %s opened 2026-10-12 %s session "
          "00000000-0000-0000-0000-000000000002\n"
          "- Goal: fixture\n"
          "- Files: tests/test_thing_alpba.py\n"
          "- Blocked by: none\n" % (EM, EM, EM)
    )
    repo = _repo(tmp_path, ["tests/test_thing_alpba.py"], lanes)
    code, out = _run(repo)
    assert "almost certainly a TYPO" not in out, out
    assert "DO NOT ADOPT" in out or "claim it" in out


def test_a_glob_stays_broken_however_it_is_marked(tmp_path):
    """(NEW) excuses a path that will exist; it cannot excuse an impossible token."""
    repo = _repo(tmp_path, ["tests/test_real.py"],
                 _block("globber", "tests/test_football_scenario_*.py (NEW)"))
    code, out = _run(repo)
    assert code == 1, out
    assert "a glob" in out


def test_marked_new_at_reads_the_marker_not_a_section_qualifier():
    """The detector is string work, not a regex -- a backslash escape once died
    in transit through a shell heredoc and left the marker permanently unseen."""
    m = _load()
    line = "- Files: a/b.py (NEW), c/d.py (the live section only), e/f.py (new, as-of)"
    for path, expected in (("a/b.py", True), ("c/d.py", False), ("e/f.py", True)):
        at = line.find(path) + len(path)
        assert m._marked_new_at(line, at) is expected, path
    # and no control byte survived into the module
    assert chr(8) not in SCRIPT.read_text(encoding="utf-8")
# ---------------------------------------------------------------------------
# The near-miss-OPEN header check, and the false positive it had.
#
# Measured 2026-10-14: lane `nba-pregame-lineup-pools` carried the status
# `CLOSED 2026-10-14 (GOAL MET via the pre-opener as-of replay; ...)`. The
# predicate was `("OPEN" in status.upper()) and not OPEN_RE.search(status)`, so
# the substring `open` inside the PROSE word "pre-opener" matched while
# `OPEN_RE` (case-sensitive) did not -- and that single false positive made this
# script exit 1 on origin/main, which is why EVERY session's start digest read
# `LEDGER INCOHERENT`. Only the first em-dash segment is the status field, which
# is why one lane tripped it and every other CLOSED block did not.
# ---------------------------------------------------------------------------


def _hdr(slug, status, sess="00000000-0000-0000-0000-000000000000"):
    return "### %s %s %s %s opened 2026-10-12 %s session %s" % (slug, EM, status, EM, EM, sess)


def _lanes(header, claimed="tests/test_thing.py"):
    """The near-miss block PLUS a genuinely OPEN companion that holds a claim.

    Load-bearing, not padding: with only the near-miss lane the claim set is
    legitimately EMPTY and the script's `[FATAL] the parser found ZERO claims
    while lanes.md holds N header(s) reading OPEN` alarm fires first, returning
    before the near-miss section is reported. That alarm is correct, so the
    fixture gives it a real claim to find.
    """
    return _doc_lines([
        "## OPEN", "",
        _hdr("companion-open-lane", "OPEN"),
        "- Goal: a real OPEN lane so the claim set is not empty",
        "- Files: tests/test_companion.py",
        "- Blocked by: none", "",
        header, "- Goal: fixture", "- Files: %s" % claimed, "- Blocked by: none",
    ])


def _doc_lines(lines):
    return chr(10).join(lines)


def _near_miss_reported(out):
    return "DECLARE files under a header" in out


def test_a_closed_lane_whose_status_prose_says_pre_opener_is_NOT_a_near_miss(tmp_path):
    """The real false positive: lowercase `open` inside a prose word."""
    repo = _repo(
        tmp_path,
        ["tests/test_thing.py", "tests/test_companion.py"],
        _lanes(_hdr("closed-prose-lane",
                    "CLOSED 2026-10-14 (GOAL MET via the pre-opener as-of replay; handed to todo #696)")),
    )
    code, out = _run(repo)
    assert not _near_miss_reported(out), out
    assert "closed-prose-lane" not in out, out


def test_a_real_REOPENED_header_declaring_files_is_STILL_reported(tmp_path):
    """The worked example this check exists for must keep firing."""
    repo = _repo(
        tmp_path,
        ["tests/test_thing.py", "tests/test_companion.py"],
        _lanes(_hdr("reopened-lane", "**REOPENED 2026-09-03 for the READ side**")),
    )
    code, out = _run(repo)
    assert _near_miss_reported(out), out
    assert "reopened-lane" in out
    assert code == 1


def test_an_OPENED_header_declaring_files_is_STILL_reported(tmp_path):
    repo = _repo(
        tmp_path,
        ["tests/test_thing.py", "tests/test_companion.py"],
        _lanes(_hdr("opened-lane", "OPENED 2026-10-01")),
    )
    code, out = _run(repo)
    assert _near_miss_reported(out), out
    assert "opened-lane" in out


def test_a_plain_CLOSED_header_declaring_files_is_a_historical_record(tmp_path):
    """The docstring's own promise, which the predicate never actually checked."""
    repo = _repo(
        tmp_path,
        ["tests/test_thing.py", "tests/test_companion.py"],
        _lanes(_hdr("plain-closed-lane", "CLOSED")),
    )
    code, out = _run(repo)
    assert not _near_miss_reported(out), out


def test_a_standalone_OPEN_header_is_not_a_near_miss_either(tmp_path):
    """Control: a genuinely OPEN lane is enforced, so it is not in this class."""
    repo = _repo(
        tmp_path,
        ["tests/test_thing.py", "tests/test_companion.py"],
        _lanes(_hdr("open-lane", "OPEN")),
    )
    code, out = _run(repo)
    assert not _near_miss_reported(out), out
def test_a_CLOSED_lane_mentioning_REOPENED_in_prose_is_still_a_historical_record(tmp_path):
    """Makes the CLOSED_RE clause load-bearing.

    Without it, an UPPERCASE non-standalone `OPEN` inside a CLOSED lane's status
    -- here the word REOPENED in prose -- satisfies `"OPEN" in status` and gets
    reported. The docstring's promise is that a CLOSED lane with a Files block is
    a historical record, so this is the test that holds the predicate to it. The
    pre-opener fixture alone does NOT exercise this clause, because that prose is
    lowercase and fails the containment anyway.
    """
    repo = _repo(
        tmp_path,
        ["tests/test_thing.py", "tests/test_companion.py"],
        _lanes(_hdr("closed-mentions-reopened",
                    "CLOSED 2026-10-14 (superseded; the REOPENED plan was dropped)")),
    )
    code, out = _run(repo)
    assert not _near_miss_reported(out), out
    assert "closed-mentions-reopened" not in out, out


def test_a_non_closed_status_with_lowercase_open_prose_is_not_a_near_miss(tmp_path):
    """Pins the .upper() removal, which the pre-opener fixture does NOT.

    Measured 2026-10-14 by mutation: with only the pre-opener fixture, restoring
    `status.upper()` still passed, because that status carries a CLOSED token and
    the CLOSED_RE clause saves it independently. EITHER change alone fixes the
    real-world case, so neither was pinned. This fixture drops the CLOSED token
    -- a BLOCKED lane whose prose happens to contain "pre-opener" -- so only the
    case-sensitive containment can keep it out of the report.
    """
    repo = _repo(
        tmp_path,
        ["tests/test_thing.py", "tests/test_companion.py"],
        _lanes(_hdr("blocked-prose-lane",
                    "BLOCKED 2026-10-14 (waiting on the pre-opener replay)")),
    )
    code, out = _run(repo)
    assert not _near_miss_reported(out), out
    assert "blocked-prose-lane" not in out, out
