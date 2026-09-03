#!/usr/bin/env python3
"""WHICH LANE IS THIS SESSION HOLDING? Shared by every hook that asks.

Extracted 2026-09-03 from `deploy-guard.py`, which had the better of the two
implementations that existed. `lane-guard.py` carried its own copy inline, and
`lane-postwrite-check.py` was about to be the third -- which is the exact
situation `learnings.md` 2026-08-20 forbids: a defect in what all the guards
share must be fixed in a shared module, or the next guard re-makes it.

THE TWO COPIES HAD ALREADY DIVERGED, AND THE DIFFERENCE WAS LIVE. `deploy-guard`
read the marker with `encoding="utf-8-sig"` and took `splitlines()[0]`;
`lane-guard` read plain UTF-8 and `.strip()`. A marker file written with a BOM
therefore resolved to the lane slug for deploys and to the literal string
U+FEFF for edits -- and U+FEFF matches no lane, so that session would have been
blocked from editing its OWN claimed files with a message telling it to write
the marker it had already written. One such marker existed in `.syndicate/` when
this module was created. Reading it the tolerant way is now the only way.

WHY THE PER-SESSION MARKER IS PREFERRED, preserved from `deploy-guard`:
`.syndicate/.current-lane` is a single shared slot and whichever session wrote
it last owns it, so on a machine running several sessions the bare file names
someone else's lane. That is not hypothetical -- measured 2026-08-19, a
refresh-worker deploy claim was acquired under a lane name belonging to a
different session, twice, traced to exactly this fallback. `/lane` was changed
the same day to stop writing the bare file at all, so a session with no marker
of its own now correctly reads as "no lane" rather than inheriting an identity.

THE SESSION ID IS SANITISED because it arrives from outside and goes straight
into a filename. `lane-guard` did this and `deploy-guard` did not; the shared
version does, which is the strictly safer of the two behaviours.

NO EXCEPTION ESCAPES. Every caller here is a hook whose contract is to fail
open, and an unreadable marker must read as "no lane", never as a crash.
"""
import os
import re


def safe_session_id(session_id):
    """The session id reduced to what is safe in a filename."""
    return re.sub(r"[^A-Za-z0-9._-]", "", str(session_id or "").strip())[:128]


def _read(path):
    # utf-8-sig, not utf-8: see the BOM divergence in this module's docstring.
    try:
        with open(path, encoding="utf-8-sig") as fh:
            return fh.read().strip()
    except Exception:
        return ""


def current_lane(root, session_id=""):
    """(lane_slug, used_per_session_marker) for the session running in `root`.

    Returns ("", False) when no marker holds a value -- which is the SAFE
    reading, since a caller comparing "" against a lane slug never matches and
    so never grants ownership by accident.
    """
    sid = safe_session_id(session_id)
    names = []
    if sid:
        names.append(".current-lane." + sid)
    names.append(".current-lane")
    for i, name in enumerate(names):
        value = _read(os.path.join(root, ".syndicate", name))
        if value:
            return value.splitlines()[0].strip(), (i == 0 and bool(sid))
    return "", False
