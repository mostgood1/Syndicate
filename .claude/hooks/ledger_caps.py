#!/usr/bin/env python3
"""THE LEDGER SIZE CAPS, read from the one place that ENFORCES them.

`session-start.sh` is the only component whose cap does anything -- it is what
prints `LEDGER OVER BUDGET` at every session start. Every other tool that
mentions a cap is REPORTING, and a reporting tool with its own copy of the
number drifts silently in the direction that matters most: it keeps claiming a
file is over budget after the budget was raised.

WHY THIS MODULE EXISTS, measured 2026-09-03. `5c3ad9c4` raised `lanes.md` from
120,000 to 240,000. `trim_lane_blocks.py` kept `--cap 120000` as its default and
`archive_released_lanes.py` kept `cap 120000` in a print. So the tool a human
actually runs said:

    cap 120000      1.66x -> 1.58x  *** STILL OVER ***

while `session-start.sh`, holding the real number, said nothing about lanes.md
at all -- 203,061 B against 240,000 is 0.85x, comfortably UNDER.

It cost something. Session c38d3e5c read that line and reported to their user
that `lanes.md` "sits at 1.61x its cap with zero movable blocks, so closing
lanes is the only remedy and no tool can help" -- an unresolved constraint that
does not exist. A permanently-red "STILL OVER" is the wolf-crying failure this
repo keeps paying for, and this instance was manufactured entirely by constant
drift between two files nobody diffed.

IT PARSES THE SHELL, DELIBERATELY. The alternative was a fourth copy of the
numbers in a Python constant, which is the problem restated. The line is stable
and simple (`for f in lanes.md:240000 learnings.md:400000; do`), the parse is
anchored on it, and every failure mode falls back to the documented default AND
SAYS SO through `cap_source()` -- a silent fallback would rebuild the same drift
with extra steps.

`state.md` is deliberately NOT here: since the 2026-09-03 split its budget is
three separate alarms (index / per-part / total) computed inline in the shell,
and flattening those into one number would misreport all three.
"""
import os
import re

# Used only when the shell cannot be read. Kept equal to the values in
# `session-start.sh` at the time of writing, so a fallback is stale rather than
# wrong -- and `cap_source()` reports which one you got.
_FALLBACK = {"lanes.md": 240000, "learnings.md": 400000}

_LINE = re.compile(r"^\s*for\s+f\s+in\s+(.+?);\s*do\s*$", re.M)
_PAIR = re.compile(r"([A-Za-z0-9_.-]+\.md):(\d+)")


def _hook_path(root=None):
    root = root or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    return os.path.join(root, ".claude", "hooks", "session-start.sh")


def caps(root=None):
    """({name: cap}, source) -- source is "session-start.sh" or "fallback"."""
    try:
        with open(_hook_path(root), encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except Exception:
        return dict(_FALLBACK), "fallback"
    for m in _LINE.finditer(text):
        pairs = dict((n, int(v)) for n, v in _PAIR.findall(m.group(1)))
        # The state.md alarms live in a different loop; take the one that
        # actually carries the ledger files this module is asked about.
        if "lanes.md" in pairs or "learnings.md" in pairs:
            merged = dict(_FALLBACK)
            merged.update(pairs)
            return merged, "session-start.sh"
    return dict(_FALLBACK), "fallback"


def cap(name, root=None):
    """The enforced byte budget for a ledger file, by bare name."""
    return caps(root)[0].get(name, _FALLBACK.get(name, 0))


def cap_source(root=None):
    """Where the numbers came from. Print it -- a silent fallback is the bug."""
    return caps(root)[1]
