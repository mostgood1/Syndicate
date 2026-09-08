#!/usr/bin/env python3
"""HOW BIG IS THE OPEN-LANE POPULATION, and how much of it is nobody's?

WHY THIS EXISTS. The session-start digest caps its OPEN LANES section at 600
bytes (`session-start.sh`, `LANE_CAP`). Measured 2026-09-08 that section was
**31,404 bytes**, so a starting session was shown **1.9% of the state** -- three
arbitrary lanes in file order -- with no indication that 44 others existed. You
cannot defer a lead to a lane you cannot see, and you cannot avoid a collision
with a lane you were never shown. A truncated SAMPLE reads as the whole; a COUNT
cannot.

WHAT IT REPLACES IT WITH. One line that is strictly more informative than the
600 bytes it displaces:

    47 OPEN / 22 UNOWNED / 21 stale>7d / oldest 22d (convergence-phase7-crps)

`--digest` prints exactly that and nothing else. The full listing is one command
away and is not paid for at every session start.

IT MIRRORS `lane_claims._claims()` HEADER-FOR-HEADER, deliberately. This repo's
own rule (`pending_deploys.py`, quoted in `lane_claim_audit.py`): "a second tool
answering the same question differently is worse than no second tool." A census
that counts lanes `lane-guard` does not consider open -- or misses ones it does
-- would be a third opinion about `lanes.md`, and the file already has enough.
So the OPEN test here is the same one the guard applies: `LANE_RE`, falling back
to `ASCII_LANE_RE` for a malformed separator, then `OPEN_RE` against the status
segment. `lane_claims` is imported directly rather than through
`lane_claim_audit.py`'s AST loader: that loader exists because `lane-guard.py`
has a hyphen and reads stdin at import; `lane_claims.py` has neither problem.

UNOWNED IS READ FROM THE WHOLE HEADER LINE, not from the status segment.
`LANE_RE` group(2) stops at the second em-dash, and lanes write the marker on
either side of it -- `— OPEN, **UNOWNED** [sweep] — opened ...` puts it inside,
`— **OPEN** — ... — UNOWNED` puts it outside. Reading the whole line is the only
spelling that catches both. This is a LOOSER test than the OPEN one on purpose,
and it is why this tool's UNOWNED count (22) differs from a body-wide grep (25):
a lane whose BODY says the session is gone but whose HEADER does not is counted
owned here. Stated rather than reconciled, because the header is what a starting
session actually reads.

READ THE REF, NOT THE CHECKOUT. The primary tree was **429 commits behind**
`origin/main` on 2026-09-08 and carried 70 lane headers against origin's 52 --
a diverged snapshot that never received origin's archive passes. A census taken
from it is a census of a tree nobody else has. So this reports BOTH by default
and says when they disagree. `git show` reads a local ref: no network, no fetch,
~40 ms.

    py -3 scripts/lane_census.py                 # full listing + divergence
    py -3 scripts/lane_census.py --digest        # the one line
    py -3 scripts/lane_census.py --json
    py -3 scripts/lane_census.py --ref WORKTREE  # skip the origin comparison

Exit 0 = census taken. 2 = could not read a ledger at all.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, ".claude", "hooks"))
try:
    from lane_claims import ASCII_LANE_RE, HEADER_RE, LANE_RE, OPEN_RE
except Exception as exc:  # pragma: no cover
    sys.stderr.write(
        "lane_census: cannot import .claude/hooks/lane_claims.py (%s). Refusing "
        "to hand-roll a second lane parser.\n" % exc)
    raise SystemExit(2)

DATE_RE = re.compile(r"(20\d\d)-(\d\d)-(\d\d)")
OPENED_RE = re.compile(r"opened\s+(20\d\d-\d\d-\d\d)")
STALE_DAYS = 7


def _today():
    return _dt.date.today()


def _d(s):
    try:
        y, m, d = s.split("-")
        return _dt.date(int(y), int(m), int(d))
    except Exception:
        return None


def lanes(text):
    """[{slug, opened, unowned, newest}] for every OPEN lane in `text`.

    The OPEN test is `_claims`'s, header for header. `newest` is the latest date
    mentioned ANYWHERE in the block -- header or body -- which is the closest
    thing `lanes.md` has to "when was this last worked". It is not a checkpoint
    timestamp and does not pretend to be: a lane that quotes a date from an old
    incident reads as fresher than it is, so `stale` is a floor on the true
    staleness, never a ceiling.
    """
    out = []
    cur = None
    for line in text.splitlines():
        if HEADER_RE.match(line):
            m = LANE_RE.match(line) or ASCII_LANE_RE.match(line)
            if m and OPEN_RE.search(m.group(2)):
                opened = OPENED_RE.search(line)
                cur = {
                    "slug": m.group(1),
                    "opened": opened.group(1) if opened else None,
                    # Whole line, not the status segment -- see module docstring.
                    "unowned": "UNOWNED" in line,
                    "newest": None,
                }
                out.append(cur)
            else:
                cur = None
            # The header's own dates count toward `newest`.
            if cur is None:
                continue
        if cur is None:
            continue
        for mm in DATE_RE.finditer(line):
            d = _d(mm.group(0))
            if d and (cur["newest"] is None or d > cur["newest"]):
                cur["newest"] = d
    return out


def summarise(rows, today=None):
    today = today or _today()
    total = len(rows)
    unowned = sum(1 for r in rows if r["unowned"])
    stale = 0
    oldest_days, oldest_slug = 0, None
    for r in rows:
        n = r["newest"]
        if n is not None and (today - n).days > STALE_DAYS:
            stale += 1
        o = _d(r["opened"]) if r["opened"] else None
        if o:
            age = (today - o).days
            if age > oldest_days:
                oldest_days, oldest_slug = age, r["slug"]
    return {
        "open": total, "unowned": unowned, "stale": stale,
        "oldest_days": oldest_days, "oldest_slug": oldest_slug,
    }


def read_ref(ref):
    """`lanes.md` at a git ref, or None. Never raises."""
    if ref == "WORKTREE":
        try:
            with open(os.path.join(REPO, ".syndicate", "lanes.md"),
                      encoding="utf-8") as fh:
                return fh.read()
        except Exception:
            return None
    try:
        env = dict(os.environ)
        # Git Bash rewrites the bare `rev:path` colon form into a Windows path
        # and the read fails with a false "does not exist". Belt and braces:
        # this repo has already lost time to it twice.
        env["MSYS_NO_PATHCONV"] = "1"
        p = subprocess.run(
            ["git", "-C", REPO, "show", "%s:.syndicate/lanes.md" % ref],
            capture_output=True, text=True, encoding="utf-8", env=env)
        return p.stdout if p.returncode == 0 and p.stdout else None
    except Exception:
        return None


def behind(ref):
    try:
        p = subprocess.run(["git", "-C", REPO, "rev-list", "--count",
                            "HEAD..%s" % ref],
                           capture_output=True, text=True, encoding="utf-8")
        return int(p.stdout.strip()) if p.returncode == 0 else None
    except Exception:
        return None


def digest_line(tree, origin, n_behind):
    s = tree
    line = "%d OPEN / %d UNOWNED / %d stale>%dd" % (
        s["open"], s["unowned"], s["stale"], STALE_DAYS)
    if s["oldest_slug"]:
        line += " / oldest %dd (%s)" % (s["oldest_days"], s["oldest_slug"])
    if origin and (origin["open"] != s["open"]
                   or origin["unowned"] != s["unowned"]):
        line += " | origin/main: %d/%d" % (origin["open"], origin["unowned"])
    if n_behind:
        line += " | TREE %d BEHIND origin/main" % n_behind
    return line


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--digest", action="store_true",
                    help="one line, for the session-start digest")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--ref", default="origin/main",
                    help="ref to compare the worktree against, or WORKTREE to "
                         "skip the comparison (default: origin/main)")
    args = ap.parse_args(argv)

    tree_text = read_ref("WORKTREE")
    if tree_text is None:
        sys.stderr.write("lane_census: no .syndicate/lanes.md in %s\n" % REPO)
        return 2
    tree = summarise(lanes(tree_text))

    origin = None
    n_behind = None
    if args.ref != "WORKTREE":
        ref_text = read_ref(args.ref)
        if ref_text is not None:
            origin = summarise(lanes(ref_text))
            n_behind = behind(args.ref)

    if args.digest:
        print(digest_line(tree, origin, n_behind))
        return 0

    if args.json:
        print(json.dumps({"worktree": tree, "ref": args.ref,
                          "ref_summary": origin, "behind": n_behind}, indent=2))
        return 0

    print(digest_line(tree, origin, n_behind))
    print()
    rows = sorted(lanes(tree_text),
                  key=lambda r: (r["opened"] or "9999", r["slug"]))
    today = _today()
    for r in rows:
        o = _d(r["opened"]) if r["opened"] else None
        age = "%3dd" % (today - o).days if o else "  ?d"
        n = r["newest"]
        quiet = (today - n).days if n else None
        print("  %-4s %-9s %-46s %s" % (
            age,
            "UNOWNED" if r["unowned"] else "owned",
            r["slug"],
            ("quiet %dd" % quiet) if quiet is not None and quiet > STALE_DAYS
            else ""))
    print()
    print("  %d OPEN. Claims: py -3 scripts/check_lane_claims.py" % tree["open"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
