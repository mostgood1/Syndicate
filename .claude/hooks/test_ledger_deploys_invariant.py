#!/usr/bin/env python3
"""`.syndicate/deploys.md` under the ledger guard: `dropped_sections`.

WHY THIS FILE WAS UNGUARDED UNTIL 2026-09-04, since the gap is instructive:
`deploys.md` was absent from `TRACKED`, its two mentions in
`ledger-append-guard.py` were PROSE (a docstring and a remedy string) rather
than predicates, and `ledger-postwrite-check.py` never named it. It was the only
ledger file with no cover at any stage -- and it is the one `CLAUDE.md`'s
non-negotiable rests on (*"Never claim a fix works without a measurement written
to `.syndicate/deploys.md`"*) and the one the session-start digest reads open
obligations from.

It was found because a grep COUNT of the guard source returned 2 for
`deploys.md` and 2 for `learnings.md`, which have OPPOSITE coverage. A count of
a filename cannot tell a predicate from a sentence mentioning the file, so the
probe measured nothing in either direction and produced a REASSURANCE.

WHAT THE PREDICATE IS, and what it deliberately is not:

  FIRES   a `## ` section on origin/main that this text lacks and
          `deploys_history.md` does not hold -- i.e. a MEASUREMENT being dropped
          by a commit made from a stale tree.
  QUIET   a section that moved to `deploys_history.md` (archiving is not loss)
  QUIET   no root, no git, no upstream ref (fails OPEN, like every other
          upstream-reading predicate in the module)

It is the MIRROR of `resurrected_blocks`, not a copy: that one fires on archived
content coming BACK, because on `lanes.md` a stale tree duplicates and loses
nothing. `deploys.md` is append-only prose, so the same stale tree SUBTRACTS
instead. Neither predicate sees the other's case.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from ledger_invariants import CHECKS, TRACKED, dropped_sections  # noqa: E402

FAILURES = []


def check(name, got, want):
    if got != want:
        FAILURES.append(f"{name}: got {got!r}, want {want!r}")
        print(f"  FAIL {name}: got {got!r}, want {want!r}")
    else:
        print(f"  ok   {name}")


UP = """## 2026-09-04 first — a measurement
body one
## 2026-09-04 second — another
body two
## 2026-09-04 third — a third
body three
"""


def test_registration():
    """Presence in TRACKED is not coverage -- the dispatch entry is."""
    check("deploys.md in TRACKED", ".syndicate/deploys.md" in TRACKED, True)
    check("deploys.md routed in CHECKS", ".syndicate/deploys.md" in CHECKS, True)
    # The failure this guards: a TRACKED file with no CHECKS entry makes
    # `violations()` return [] forever -- decoration that reads as coverage.
    check("every TRACKED file is routed",
          sorted(f for f in TRACKED if f not in CHECKS), [])


def test_clean_when_nothing_dropped():
    check("identical text is clean", dropped_sections(UP, UP, ""), [])
    check("text AHEAD of upstream is clean",
          dropped_sections(UP + "## 2026-09-04 fourth — new\nbody\n", UP, ""), [])


def test_fires_on_a_dropped_measurement():
    stale = "## 2026-09-04 first — a measurement\nbody one\n"
    missing = dropped_sections(stale, UP, "")
    check("two dropped sections are reported", len(missing), 2)
    check("and it names them",
          missing[0].startswith("## 2026-09-04 second"), True)


def test_archiving_is_not_dropping():
    """`deploys_history.md` exists and is used. A section that moved there is
    accounted for; only one in NEITHER place is a loss."""
    without_first = "".join(UP.splitlines(keepends=True)[2:])
    archived = "## 2026-09-04 first — a measurement\nbody one\n"
    check("moved to history -> clean", dropped_sections(without_first, UP, archived), [])
    check("moved nowhere -> fires", len(dropped_sections(without_first, UP, "")), 1)


def test_fails_open():
    """No upstream is NO OPINION, never a block. A guard that refuses when it
    cannot read is one people switch off."""
    from ledger_invariants import violations
    check("no root -> no opinion", violations(".syndicate/deploys.md", UP, None), [])
    check("empty text -> no opinion", violations(".syndicate/deploys.md", "", "/nonexistent"), [])


def test_only_hash_hash_headers_count():
    """`###` subsections are not measurements and must not create noise."""
    up = UP + "### a subsection\nbody\n"
    check("### is ignored", dropped_sections(UP, up, ""), [])


def main():
    for fn in (test_registration, test_clean_when_nothing_dropped,
               test_fires_on_a_dropped_measurement, test_archiving_is_not_dropping,
               test_fails_open, test_only_hash_hash_headers_count):
        print(fn.__name__)
        fn()
    if FAILURES:
        print(f"\n{len(FAILURES)} FAILURE(S)")
        return 1
    print("\nall deploys.md invariant tests pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
