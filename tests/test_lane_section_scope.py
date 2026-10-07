"""lane_claims: two lanes may own DIFFERENT declared sections of one file.

MEASURED DEADLOCK, 2026-10-07 -- the same shape as the loan deadlock a day earlier.
`fleet-watchdog-auto-recovery` held `docs/ai_context/local_production_runbook.md
(watchdog section only)` and `web-restart-healthz` held the same file `(web reload
section only)`. Disjoint by their owners' own declaration, and each blocked the other,
because the parser cannot represent a section.

WHAT THIS HONOURS AND WHAT IT DOES NOT. A PreToolUse hook cannot know which lines a
write will touch, so this honours a declaration rather than verifying it -- exactly as
the loan support honours a grant -- and `lane-postwrite-check` stays the net. Every
other case fails closed, which is what the last four tests pin.
"""
from __future__ import annotations

import importlib.util
import pathlib

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "lane_claims_sections", _ROOT / ".claude/hooks/lane_claims.py")
lc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lc)

DOC = "docs/ai_context/local_production_runbook.md"


def _lane(slug, files, status="OPEN"):
    return (f"### {slug} — {status} — opened 2026-10-07 — session s-{slug}\n"
            f"- Goal: whatever\n"
            f"- Files: {files}\n"
            f"- Blocked by: none")


def _lanes(*blocks):
    return "## OPEN\n\n" + "\n\n".join(blocks) + "\n"


WATCHDOG = _lane("watchdog-lane", f"scripts/w.py, {DOC} (watchdog section only)")
WEBRELOAD = _lane("webreload-lane", f"scripts/r.py, {DOC} (web reload section only)")


def _blocked_by(text, current, rel):
    conflict = None
    for slug, f in lc._claims(text):
        if slug != current and lc.matches(rel, f):
            conflict = slug
    return conflict


def test_two_different_declared_sections_both_pass():
    text = _lanes(WATCHDOG, WEBRELOAD)
    assert _blocked_by(text, "watchdog-lane", DOC) == "webreload-lane", \
        "the raw claim set still collides -- the section check is what resolves it"
    assert lc.sections_are_disjoint(text, "watchdog-lane", DOC) == "watchdog section only"
    assert lc.sections_are_disjoint(text, "webreload-lane", DOC) == "web reload section only"


def test_a_lane_with_NO_section_declaration_is_still_blocked():
    """The case that would make the file unguarded if this were done wrong."""
    text = _lanes(WATCHDOG, WEBRELOAD, _lane("outsider-lane", "scripts/other.py"))
    assert lc.sections_are_disjoint(text, "outsider-lane", DOC) is None
    assert _blocked_by(text, "outsider-lane", DOC) is not None


def test_two_lanes_naming_the_SAME_section_still_block_each_other():
    """They really do collide -- a declaration of the same section is not disjointness."""
    twin = _lane("twin-lane", f"{DOC} (watchdog section only)")
    text = _lanes(WATCHDOG, twin)
    assert lc.sections_are_disjoint(text, "watchdog-lane", DOC) is None
    assert lc.sections_are_disjoint(text, "twin-lane", DOC) is None


def test_one_section_holder_plus_one_WHOLE_FILE_holder_blocks_both():
    """A whole-file claim is not a section, so the section holder gets no pass either --
    the un-declared holder may be editing anywhere in the file."""
    whole = _lane("whole-file-lane", f"{DOC}")
    text = _lanes(WATCHDOG, whole)
    assert lc.sections_are_disjoint(text, "watchdog-lane", DOC) is None
    assert lc.sections_are_disjoint(text, "whole-file-lane", DOC) is None


def test_a_CLOSED_section_holder_does_not_contest_at_all():
    text = _lanes(WATCHDOG, _lane("webreload-lane", f"{DOC} (web reload section only)",
                                  status="CLOSED 2026-10-07"))
    assert _blocked_by(text, "watchdog-lane", DOC) is None, "a closed lane holds nothing"


def test_the_qualifier_must_say_SECTION_and_ONLY_not_merely_only():
    """Narrow on purpose. The ledger is full of other `ONLY` qualifiers scoping a claim
    to part of a CODE file; widening this to any `only` would start permitting
    concurrent writes to code on the strength of a comment."""
    assert lc._section_of("(watchdog section only)") == "watchdog section only"
    assert lc._section_of("(_soccer_rosters_step + its one wiring loop ONLY)") is None
    assert lc._section_of("(reload-web subcommand only)") is None
    assert lc._section_of("(no parenthetical qualifier)") is None


def test_the_section_qualifier_does_not_leak_to_other_paths_on_the_line():
    """`scripts/w.py` on the same Files line carries no declaration and must stay a
    plain whole-file claim."""
    text = _lanes(WATCHDOG, _lane("other", "scripts/w.py"))
    assert lc.sections_are_disjoint(text, "watchdog-lane", "scripts/w.py") is None
    assert ("watchdog-lane", "scripts/w.py") not in lc.section_scopes(text)


def test_section_scopes_reports_the_declaration():
    text = _lanes(WATCHDOG, WEBRELOAD)
    scopes = lc.section_scopes(text)
    assert scopes[("watchdog-lane", DOC)] == "watchdog section only"
    assert scopes[("webreload-lane", DOC)] == "web reload section only"
