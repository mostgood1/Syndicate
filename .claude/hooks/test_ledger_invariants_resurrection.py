#!/usr/bin/env python3
"""Tests for the STALE-TREE predicate in `ledger_invariants.py`.

Run: py -3 .claude/hooks/test_ledger_invariants_resurrection.py

WHAT THIS PINS. On 2026-09-02 a kalshi CODE commit carried a `lanes.md` from a
tree ~90 commits behind origin/main. It reverted a trim pass -- 180,974 B back
to 209,141 B -- and left 14 blocks duplicated across `lanes.md` and
`lanes_history.md`. Every existing predicate passed: no slug had two blocks
IN lanes.md, and no OPEN lane sat under the archive marker.

The commit ADDED blocks, so nothing was "lost" for a dropped-content check to
find. What it reverted was a DELETION, and a deletion is invisible to any
predicate that only looks at what is present. The only signature that fires is
a block appearing VERBATIM in upstream's history while upstream's lanes.md no
longer has it.

The near-miss these cases exist to prevent: SAME-SLUG is not the test. 36 slugs
legitimately live in both files -- history holds superseded blocks of lanes that
are still alive, and 18 of those were OPEN at the time. Header-identity is not
the test either: 24 headers matched where only 14 bodies did. Body byte-identity
is the discriminator, and a looser one would have blocked honest work.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

HOOKS = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("ledger_invariants",
                                              HOOKS / "ledger_invariants.py")
li = importlib.util.module_from_spec(spec)
spec.loader.exec_module(li)

RESULTS = []


def check(label, got, want):
    RESULTS.append((label, got, want))


def lanes(*blocks):
    return "## OPEN\n\n" + "\n\n".join(blocks) + "\n"


def history(*blocks):
    return "## SUPERSEDED\n\n" + "\n\n".join(blocks) + "\n"


ALPHA = "### alpha \u2014 CLOSED 2026-09-02 \u2014 session x\n- Goal: a thing.\n- Blocked by: none"
BETA = "### beta \u2014 OPEN \u2014 session y\n- Files: `b/two.py`\n- Blocked by: none"
ALPHA_NEWER = "### alpha \u2014 CLOSED 2026-09-02 \u2014 session x\n- Goal: a thing, REVISED.\n- Blocked by: none"


def main():
    # THE FAILURE, reproduced: upstream archived alpha; a stale tree brings it back.
    check("an archived block coming back is FLAGGED",
          li.resurrected_blocks(lanes(ALPHA, BETA), lanes(BETA), history(ALPHA)),
          ["alpha"])

    # The same content while upstream still has it live is just normal.
    check("a block upstream still has LIVE is not flagged",
          li.resurrected_blocks(lanes(ALPHA, BETA), lanes(ALPHA, BETA), history(ALPHA)),
          [])

    # The 36-slug case. Same slug, different body -> legitimate supersession.
    check("same slug, DIFFERENT body is not flagged",
          li.resurrected_blocks(lanes(ALPHA_NEWER), lanes(ALPHA_NEWER), history(ALPHA)),
          [])

    check("an empty history flags nothing",
          li.resurrected_blocks(lanes(ALPHA), lanes(ALPHA), history()),
          [])

    # A block ends at a `## ` heading too; without that boundary the last block
    # of a section swallows the archive marker and never matches anything.
    tail = lanes(ALPHA) + "\n## Archived lanes\n\nsome trailing prose\n"
    check("a `## ` heading ends a block",
          li.resurrected_blocks(tail, lanes(BETA), history(ALPHA)),
          ["alpha"])

    # FAILS OPEN: no root -> the predicate is skipped, never guessed.
    check("violations() with no root gives no opinion",
          li.violations(".syndicate/lanes.md", lanes(ALPHA, BETA)),
          [])

    # ... and the OTHER predicates still work through the new signature.
    two = lanes(ALPHA, ALPHA)
    check("a duplicate slug still blocks (via the new signature)",
          bool(li.violations(".syndicate/lanes.md", two)), True)

    # --- narrative resurrection: content moved WITHIN blocks -----------------
    #
    # `resurrected_blocks` keys on a whole block and is blind to a COMPACTION,
    # which keeps every header in place and moves only the prose. Measured
    # 2026-09-04 on `a8000faf`: lanes.md 203,047 -> 84,956 B, no block archived,
    # and `violations()` returned 0 on a stale 208 KB working copy whose commit
    # would have put 1,308 archived lines back.
    prose = [('line %02d ' % k) + 'x' * 44 for k in range(40)]
    kept = '### a — OPEN — x' + chr(10) + '- Files: `a/b.py`' + chr(10)
    up_lanes = kept
    up_hist = chr(10).join(prose)
    stale = kept + chr(10) + chr(10).join(prose)

    n, _s = li.resurrected_lines(stale, up_lanes, up_hist)
    check('a compaction revert is COUNTED (block check cannot see it)', n, 40)
    check('the block check itself stays silent on it',
          li.resurrected_blocks(stale, up_lanes, up_hist), [])
    check('upstream own copy counts ZERO',
          li.resurrected_lines(up_lanes, up_lanes, up_hist)[0], 0)
    check('short lines are not evidence (< 40 chars)',
          li.resurrected_lines(kept + chr(10) + '- Blocked by: none.',
                               up_lanes, '- Blocked by: none.')[0], 0)
    few = kept + chr(10) + chr(10).join(prose[:5])
    check('a handful of quoted lines is UNDER the floor',
          li.resurrected_lines(few, up_lanes, up_hist)[0] >= li._RESURRECT_FLOOR,
          False)

    # THE CONTRACT. `_resurrected` returns SLUGS and `_lanes` joins them as
    # strings; returning a tuple made `_lanes` raise TypeError, which
    # `violations()` swallows -- the guard reading CLEAN while inert. That is why
    # the narrative check lives in its own function.
    check('_resurrected still yields strings, never tuples',
          all(isinstance(x, str) for x in li._resurrected(stale, None)), True)

    failed = 0
    for label, got, want in RESULTS:
        ok = got == want
        failed += not ok
        print(f"  {'PASS' if ok else 'FAIL'}  {label}")
        if not ok:
            print(f"        got={got!r} want={want!r}")
    print(f"\n{len(RESULTS) - failed}/{len(RESULTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
