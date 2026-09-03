"""Ledger invariants, in one place, imported by the hooks that enforce them.

WHY A SHARED MODULE HERE, when `check_lane_invariants.py` deliberately COPIES
`lane-guard.py`'s regexes instead of importing them. That copy exists because
`lane-guard.py` is a HOOK: it ends in a bare `sys.exit(main())`, so importing it
kills the importer with exit 0 and no output. This file is not a hook -- it has
no `main()` and no side effects on import -- so the reason for duplicating does
not apply, and three copies of the same predicate would drift.

WHAT IS AND IS NOT AN INVARIANT HERE. Each predicate below is a failure that
actually happened and that a reader cannot see by looking:

  lanes.md      a lane with MORE THAN ONE block   -- the append-instead-of-edit
                failure; took the file to 2.12x cap, one lane at 16 blocks.
                a block BELOW `## Archived lanes` -- `lane-guard` reads lanes.md
                and nothing else, so an archive pass drops those claims SILENTLY.
  state.md      an UNKEYED `##` section           -- without a subject key,
                stacking on it is invisible; this file has been collapsed twice.
                a STACKED subject                 -- two sections, one subject,
                which is how contradictions accumulate.
  learnings.md  a TRUNCATED rule stub             -- a compacted entry whose rule
                line stops mid-clause. 77 of 176 stubs were in this state on
                2026-08-19; the evidence file had the text, the file everyone
                READS did not.

Every predicate is CLEAN at the time of writing (0/0/0/0/0), so none of them
blocks the legitimate present state of any file.
"""
from __future__ import annotations

import collections
import re

LANES = ".syndicate/lanes.md"
STATE = ".syndicate/state.md"
LEARNINGS = ".syndicate/learnings.md"
TRACKED = (LANES, STATE, LEARNINGS)

_LANE_HDR = re.compile(r"(?m)^###\s+(\S+)\s")
_ARCHIVE = re.compile(r"(?m)^## Archived lanes")
_STATE_HDR = re.compile(r"(?m)^##\s+(.*)$")
_STATE_KEY = re.compile(r"^\[([^\]]+)\]")
_EVIDENCE = "- *(evidence in `learnings_evidence.md`)*"
# A line that ends a sentence, a bolded clause, code, a quote -- or a colon,
# which legitimately introduces an indented block and is NOT truncation.
_COMPLETE = re.compile(r'[.!?)*`":]\s*$')



def _blocks(text):
    """[(slug, body)] for every `### ` block. A block ends at the next `### `
    OR at any `## ` section heading -- without the second boundary the LAST
    block of a section swallows every heading after it."""
    out, slug, buf = [], None, []
    for line in text.splitlines():
        m = _LANE_HDR.match(line)
        if m:
            if slug:
                out.append((slug, "\n".join(buf).rstrip()))
            slug, buf = m.group(1), [line]
        elif re.match(r"^#{1,2} ", line):
            if slug:
                out.append((slug, "\n".join(buf).rstrip()))
            slug, buf = None, []
        elif slug is not None:
            buf.append(line)
    if slug:
        out.append((slug, "\n".join(buf).rstrip()))
    return out


def resurrected_blocks(text, upstream_lanes, upstream_history):
    """Slugs whose block is VERBATIM in upstream's history and gone from
    upstream's lanes.md -- i.e. this content was archived and is coming back.

    THIS IS THE STALE-TREE SIGNATURE, and it is the only one that fires on the
    real failure. Measured 2026-09-02: a kalshi CODE commit carried a lanes.md
    from a tree ~90 commits behind and reverted a trim pass, taking the file
    from 180,974 B back to 209,141 B and leaving 14 blocks duplicated across
    lanes.md and lanes_history.md. Nothing was lost, so no "dropped block" check
    would have seen it -- the commit ADDED blocks. What it actually reverted was
    a DELETION, and a deletion is invisible to every predicate that looks only
    at what is present.

    Same-slug is NOT the test: 36 slugs legitimately appear in both files,
    because history holds SUPERSEDED blocks of lanes that are still alive, and
    18 of those lanes are OPEN. Byte-identity of the BODY is what separates
    "this lane has an older block on record" from "this exact block is being
    un-archived". Header identity alone is not enough either -- 24 headers match
    where only 14 bodies do.
    """
    archived = {body for _slug, body in _blocks(upstream_history)}
    live = {body for _slug, body in _blocks(upstream_lanes)}
    return sorted({slug for slug, body in _blocks(text)
                   if body in archived and body not in live})


def _git_show(root, rev_path):
    import subprocess
    try:
        r = subprocess.run(["git", "-C", root, "show", rev_path],
                           capture_output=True, timeout=20)
        return r.stdout.decode("utf-8", "replace") if r.returncode == 0 else None
    except Exception:
        return None


def _resurrected(text, root):
    """Fails OPEN: no root, no git, no ref -> no opinion."""
    if not root:
        return []
    up_lanes = _git_show(root, "origin/main:.syndicate/lanes.md")
    up_hist = _git_show(root, "origin/main:.syndicate/lanes_history.md")
    if up_lanes is None or up_hist is None:
        return []
    return resurrected_blocks(text, up_lanes, up_hist)


def _lanes(text, root=None):
    out = []
    counts = collections.Counter(m.group(1) for m in _LANE_HDR.finditer(text))
    dupes = sorted(s for s, n in counts.items() if n > 1)
    if dupes:
        out.append(("a lane with MORE THAN ONE block: " + ", ".join(dupes[:6]),
                    "One lane, one block. Edit the existing block in place; the narrative\n"
                    "belongs in .syndicate/log/<today>.md. Cleanup:\n"
                    "  py -3 scripts/trim_lane_blocks.py --apply"))
    arch = _ARCHIVE.search(text)
    if arch:
        below = sorted(set(_LANE_HDR.findall(text[arch.start():])))
        if below:
            out.append(("lane block(s) BELOW `## Archived lanes`: " + ", ".join(below[:6]),
                        "lane-guard reads lanes.md and NOTHING else, so the next archive pass\n"
                        "moves these out and their file claims stop being enforced SILENTLY.\n"
                        "  py -3 scripts/hoist_open_lanes.py --apply"))
    back = _resurrected(text, root)
    if back:
        out.append(("block(s) already ARCHIVED upstream, coming BACK: " + ", ".join(back[:6]),
                    "Your lanes.md is BEHIND origin/main. These blocks were moved to\n"
                    "lanes_history.md upstream and this commit would un-archive them,\n"
                    "duplicating them across both files and reverting whoever moved them.\n"
                    "This is how a trim pass gets clobbered by an unrelated code commit.\n"
                    "  git fetch origin main\n"
                    "  git checkout origin/main -- .syndicate/lanes.md   # take upstream's\n"
                    "then re-apply YOUR block to that copy. Do not commit a ledger file\n"
                    "from a stale tree alongside unrelated changes."))
    return out


def _state(text, root=None):
    out = []
    heads = _STATE_HDR.findall(text)
    unkeyed = [h.strip() for h in heads if not h.strip().startswith("[")]
    if unkeyed:
        out.append((f"{len(unkeyed)} UNKEYED section(s), e.g. " + unkeyed[0][:56],
                    "Add a subject key: `## [subject-slug] TITLE`. Without one the section\n"
                    "cannot be compared against anything and stacking on it is invisible.\n"
                    "  py -3 scripts/state_key_check.py"))
    slugs = [_STATE_KEY.match(h.strip()).group(1) for h in heads if h.strip().startswith("[")]
    stacked = sorted(s for s, n in collections.Counter(slugs).items() if n > 1)
    if stacked:
        out.append(("STACKED subject(s): " + ", ".join(stacked[:6]),
                    "One subject, one section -- EDIT THE LINE, do not append a contradicting\n"
                    "section. Collapse into one, newest truth winning, and keep the superseded\n"
                    "claim visible if it is actionable and wrong."))
    return out


def _learnings(text, root=None):
    lines = text.split("\n")
    bad = 0
    for i, l in enumerate(lines):
        if l.strip() != _EVIDENCE:
            continue
        j = i - 1
        while j > 0 and not lines[j].strip():
            j -= 1
        rule = lines[j].strip()
        if rule and not _COMPLETE.search(rule):
            bad += 1
    if bad:
        return [(f"{bad} compacted stub(s) whose rule line stops MID-CLAUSE",
                 "The rule -- the thing the stub exists to keep -- is cut off in the file\n"
                 "everyone reads, while the full text sits in learnings_evidence.md.\n"
                 "Recover the wrapped continuation from the evidence file; a replacement\n"
                 "must START WITH the stub it replaces, never merely come from the same body.")]
    return []


CHECKS = {LANES: _lanes, STATE: _state, LEARNINGS: _learnings}


def violations(rel_path, text, root=None):
    """[(what, how_to_fix)] for a ledger file, or [] if clean/unknown.

    `root` is the repo the commit runs in. Predicates that need UPSTREAM state
    (see `_resurrected`) are skipped without it, so callers that cannot resolve
    a tree lose nothing they had before.
    """
    fn = CHECKS.get(rel_path)
    if fn is None or not text:
        return []
    try:
        return fn(text, root)
    except Exception:
        return []
