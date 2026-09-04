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
# state.md was SPLIT 2026-09-03 (`scripts/split_state.py`): the index and the
# cross-cutting subjects stay in state.md, the bodies live in these parts.
# Every one has to be TRACKED and routed to `_state`, or a commit touching
# `state_mlb.md` is checked by nothing at all -- the guard would go quiet
# exactly where the content moved.
#
# WHAT THIS CANNOT SEE, stated so nobody assumes otherwise: `_state` runs
# per-file, so it catches a subject stacked WITHIN one part -- the common case,
# someone appending a second section to the file they are already editing. A
# slug duplicated ACROSS two parts is invisible here and is caught instead by
# `scripts/state_key_check.py`, which pools slugs over every part and runs in
# session-start's coherence loop.
# DISCOVERED, NOT LISTED. A hard-coded tuple made every future split a
# two-file edit in the hooks, and a split that forgot it would leave the new
# part checked by NOTHING -- silent, and in the direction of less enforcement.
# Globbing means a part is covered the moment it exists. Archives are excluded:
# they legitimately hold a superseded body under a slug that is still live.
def _discover_state_parts():
    """Rooted at the REPO, not the process CWD.

    A CWD-rooted glob returns nothing when a hook runs from anywhere else --
    which is the normal case for a session worktree -- and the failure is
    silent and permissive. `violations()` also pattern-matches, so a part this
    misses is still routed; this list only has to be good enough for TRACKED.
    """
    import pathlib
    for base in (pathlib.Path(__file__).resolve().parents[2],  # repo root
                 pathlib.Path(".")):
        try:
            found = sorted(p.name for p in (base / ".syndicate").glob("state_*.md")
                           if not p.name.startswith("state_archive"))
            if found:
                return tuple(f".syndicate/{n}" for n in found)
        except Exception:
            continue
    return ()


# Resolved at import for the common case; `violations()` also falls back to a
# suffix match so a part that appeared after import is still routed.
STATE_PARTS = _discover_state_parts()
LEARNINGS = ".syndicate/learnings.md"
# THE FILE THE PROTOCOL'S NON-NEGOTIABLE RESTS ON, and until 2026-09-04 the only
# ledger file with no guard at ANY stage: absent from TRACKED, and its two
# mentions in `ledger-append-guard.py` are prose (a docstring and a remedy
# string), not predicates. `ledger-postwrite-check.py` never named it at all.
#
# It was not a discovery miss -- `_discover_state_parts()` only globs
# `state_*.md`, so `deploys.md` was never a candidate -- it was simply never
# added. Found because a grep COUNT of the guard source returned 2 for
# `deploys.md` and 2 for `learnings.md`, which have opposite coverage; a count
# of a filename cannot tell a predicate from a sentence mentioning the file.
DEPLOYS = ".syndicate/deploys.md"
TRACKED = (LANES, STATE, *STATE_PARTS, LEARNINGS, DEPLOYS)

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


# A resurrected LINE, for content that moved WITHIN blocks rather than as a block.
#
# `resurrected_blocks` above was built for the stale-tree revert and catches it
# when a whole block comes back. It is blind to the other shape, measured
# 2026-09-04: `a8000faf` COMPACTED all 39 OPEN blocks -- header, `- Files:` and
# `- Blocked by:` kept in place, narrative moved verbatim to `lanes_history.md`.
# lanes.md went 203,047 -> 84,956 B. No block was archived, no header changed, no
# claim moved, so nothing reads as a resurrected BLOCK and `violations()` returned
# **0 on a 208 KB stale working copy** whose commit would have put 1,412 lines /
# 111,496 B of archived narrative straight back.
#
# That is the same hazard `_deploys` already refuses on its own file, and the
# same reason: the damage is invisible in the diff's shape (a big ADDITION, which
# reads as ordinary work) and only visible against upstream.
#
# TWO FILTERS, both to keep this from crying wolf:
#   * length >= 40 -- short lines ("- Blocked by: none.") legitimately appear in
#     both files and in every new block; only substantial prose is evidence.
#   * a floor of 25 -- quoting an archived line or two while writing a new block
#     is normal. Re-adding dozens is not something legitimate work does, and the
#     real event re-adds hundreds.
_RESURRECT_MIN_LEN = 40
_RESURRECT_FLOOR = 25


def resurrected_lines(text, upstream_lanes, upstream_history):
    """(count, sample) of substantial lines upstream ARCHIVED that are coming back.

    A line counts only if it is absent from upstream's `lanes.md` AND present in
    upstream's `lanes_history.md` -- i.e. upstream deliberately moved it out and
    this text is putting it back.
    """
    def sig(s):
        return set(l.strip() for l in (s or "").splitlines()
                   if len(l.strip()) >= _RESURRECT_MIN_LEN)
    back = (sig(text) - sig(upstream_lanes)) & sig(upstream_history)
    return len(back), sorted(back)[:3]


def _resurrected(text, root):
    """Fails OPEN: no root, no git, no ref -> no opinion."""
    if not root:
        return []
    up_lanes = _git_show(root, "origin/main:.syndicate/lanes.md")
    up_hist = _git_show(root, "origin/main:.syndicate/lanes_history.md")
    if up_lanes is None or up_hist is None:
        return []
    return resurrected_blocks(text, up_lanes, up_hist)


def _resurrected_narrative(text, root):
    """[(what, how)] when upstream-ARCHIVED narrative is coming back.

    Separate from `_resurrected` ON PURPOSE. That function's contract is a
    list of SLUGS and `_lanes` joins it as strings; returning a tuple from it
    made `_lanes` raise TypeError, which `violations()` catches and turns into
    an empty result -- the guard reporting CLEAN while inert. Caught here by a
    positive case that stayed at 0 after the change. Fails open like its
    sibling: no root, no git, no ref -> no opinion.
    """
    if not root:
        return []
    up_lanes = _git_show(root, "origin/main:.syndicate/lanes.md")
    up_hist = _git_show(root, "origin/main:.syndicate/lanes_history.md")
    if up_lanes is None or up_hist is None:
        return []
    n, sample = resurrected_lines(text, up_lanes, up_hist)
    if n < _RESURRECT_FLOOR:
        return []
    nl = chr(10)
    shown = nl.join('    ' + s[:100] for s in sample)
    what = ('%d archived line(s) are coming BACK into lanes.md -- content '
            'upstream moved to lanes_history.md:%s%s' % (n, nl, shown))
    how = nl.join([
        'Your lanes.md is BEHIND origin/main and this commit would REVERT a',
        'compaction or trim. Nothing is DELETED, so the diff reads as an',
        'ordinary addition -- which is why this check exists and why the block',
        'check stays silent: the narrative moved WITHIN blocks, so no block',
        'reads as resurrected.',
        '  git fetch origin main',
        '  git checkout origin/main -- .syndicate/lanes.md',
        'then re-apply YOUR edit on top. READ `git diff -- .syndicate/lanes.md`',
        'FIRST: an uncommitted ADDITION in that file is destroyed by the',
        'checkout, and a deletions count cannot see it.',
    ])
    return [(what, how)]


def dropped_sections(text, upstream_deploys, upstream_history):
    """`## ` headers upstream has that this text and the archive BOTH lack.

    THE FAILURE THIS CATCHES IS A LOST MEASUREMENT, which is the one failure
    `deploys.md` cannot tolerate: `CLAUDE.md`'s non-negotiable is *"Never claim
    a fix works without a measurement written to `.syndicate/deploys.md`"*, and
    the session-start digest reads open deploy obligations out of this file. An
    entry that silently stops existing turns an unverified deploy into one that
    looks verified, and turns an owed reading into one nobody is tracking.

    IT IS THE OPPOSITE DIRECTION FROM `resurrected_blocks`, deliberately. That
    predicate fires on a stale tree bringing ARCHIVED content BACK, because on
    `lanes.md` nothing is lost and the damage is duplication. Here the file is
    APPEND-ONLY prose, so the stale-tree damage is subtraction instead --
    different symptom, same cause, and neither predicate sees the other's case.

    ARCHIVING IS NOT DROPPING. `.syndicate/deploys_history.md` exists and is
    used, so a header that moved there is accounted for and clean; only a header
    that is in NEITHER place is a loss.

    PROVENANCE, stated honestly rather than dressed up: unlike the other
    predicates in this module, this one is PREVENTIVE. The stale-tree commit it
    guards against was measured on `lanes.md` (2026-09-02, a code commit
    reverting a trim pass; and 2026-09-04, a `land` correctly BLOCKED for the
    same reason). No `deploys.md` loss is on record -- git's own rebase of a
    pure append usually prevents it. What is on record is two hand-resolved
    ledger conflicts in one session, where a careless resolution drops exactly
    this way and nothing would have said so.

    Fails OPEN, like every other upstream-reading predicate here.
    """
    def headers(blob):
        return [ln.strip() for ln in (blob or "").splitlines() if ln.startswith("## ")]

    have = set(headers(text)) | set(headers(upstream_history))
    return [h for h in headers(upstream_deploys) if h not in have]


def _deploys(text, root):
    """Fails OPEN: no root, no git, no ref -> no opinion."""
    if not root:
        return []
    up = _git_show(root, "origin/main:.syndicate/deploys.md")
    if up is None:
        return []
    # Absent history is not a reason to refuse -- treat it as empty and let the
    # main file answer. `_git_show` returns None for a path that does not exist.
    hist = _git_show(root, "origin/main:.syndicate/deploys_history.md") or ""
    missing = dropped_sections(text, up, hist)
    if not missing:
        return []
    shown = "\n".join(f"    {h[:110]}" for h in missing[:5])
    more = f"\n    ... and {len(missing) - 5} more" if len(missing) > 5 else ""
    return [(
        f"{len(missing)} measurement section(s) on origin/main are MISSING from this "
        f"commit's deploys.md, and are not in deploys_history.md either:\n"
        f"{shown}{more}",
        "Your deploys.md is BEHIND origin/main and this commit would DROP those\n"
        "measurements. deploys.md is append-only and is where the protocol's\n"
        "non-negotiable measurement lands; a lost entry makes an unverified\n"
        "deploy look verified.\n"
        "  git fetch origin main\n"
        "  git checkout origin/main -- .syndicate/deploys.md   # take upstream's\n"
        "then re-append YOUR entry to that copy.",
    )]


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
    out.extend(_resurrected_narrative(text, root))
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


CHECKS = {LANES: _lanes, STATE: _state, LEARNINGS: _learnings,
          DEPLOYS: _deploys,
          **{p: _state for p in STATE_PARTS}}


def violations(rel_path, text, root=None):
    """[(what, how_to_fix)] for a ledger file, or [] if clean/unknown.

    `root` is the repo the commit runs in. Predicates that need UPSTREAM state
    (see `_resurrected`) are skipped without it, so callers that cannot resolve
    a tree lose nothing they had before.
    """
    fn = CHECKS.get(rel_path)
    if fn is None and re.match(r"(?:.*/)?\.syndicate/state_(?!archive)[a-z0-9_-]+\.md$",
                               (rel_path or "").replace("\\", "/")):
        # A part that did not exist when this module was imported, or a caller
        # that resolved the path differently. Route it rather than fall through
        # to "unknown file, no opinion" -- that silence is the failure mode the
        # glob above exists to prevent, and it fails PERMISSIVE.
        fn = _state
    if fn is None or not text:
        return []
    try:
        return fn(text, root)
    except Exception:
        return []
