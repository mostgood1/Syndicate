#!/usr/bin/env python3
"""Pre+PostToolUse(Bash|PowerShell) - reports a shell write to ANOTHER lane's file.

THE GAP IT FILLS. `lane-guard.py` is registered on `Edit|Write|MultiEdit|
NotebookEdit` only, so every file change made through the shell -- a heredoc, a
`sed -i`, a `python - <<'PY'` byte-rewrite, a `cp` restore, `git apply` -- is
invisible to it. That is not an exotic path in this repo. Measured 2026-09-03
over all 292 session transcripts, counting writes whose target resolves to a
`git ls-files` path: writes to tracked SOURCE files ran 9,023 through the Edit
family against 1,045 through Bash/PowerShell, so ABOUT ONE IN TEN carried no
lane check at all. Under `.syndicate/` the shell is the majority path outright
(2,618 vs 1,069) -- which is exactly why the LEDGER already has a postwrite
backstop (`ledger-postwrite-check.py`) and lane OWNERSHIP had none.

`lane-guard` was the only guard in this directory standing on one layer.
`ledger-append-guard.py` shares its Edit-only matcher but is caught twice more,
at write time and at commit time. `commit-guard.py` does no ownership work at
all. This is the missing layer, and it is deliberately the CHEAP one.

WHY NOT JUST ADD `Bash` TO `lane-guard`'s MATCHER. That means predicting a
file write from a shell command STRING, which is not reliably possible. The
census above needed seven regex families and still misses cases. A guard that
BLOCKS on a guess will eventually refuse a correct heredoc, and this repo's
own `learnings.md` is emphatic that a guard people route around costs more than
no guard -- `lane-guard` has already been through that once, when a contended
marker slot blocked three consecutive correct edits in one session. So this
watches OUTCOMES, not commands: it never parses a shell string and it can
never refuse one.

WHY NOT DIFF THE WORKING TREE. `git status --porcelain` measured at 200 ms per
call here. `ledger-postwrite-check.py` already rejected a 41 ms git subprocess
on this same hook path as too expensive, for the identical reason -- a slow
guard gets switched off. Statting only the paths some OTHER open lane claims
measured 1.3 ms for the 43 claims live at the time. That is the whole trick:
the interesting set is tiny, and it is exactly the set the ledger already names.

THE WINDOW IS ONE TOOL CALL, and this is the part that makes the signal usable.
An obvious implementation compares against "the last time I looked", which in a
repo running five sessions means every legitimate write by ANOTHER lane's owner
gets reported to everyone else -- a warning that fires constantly and is
therefore ignored, which is the failure mode this file exists downstream of. So
`--pre` snapshots the (mtime, size) of the candidate paths BEFORE the command
and the post pass compares against THAT. Anything reported changed inside the
seconds your own command was running. It is still not PROOF you wrote it, and
the message says so -- `ledger-postwrite-check` learned that lesson the hard way
when it accused a session whose command was a `grep`.

The snapshot is keyed by (tree, session), so concurrent sessions cannot consume
or corrupt each other's, and it lives in the OS temp dir -- never in the repo,
because a hook that littered the tree it guards would be caught by its siblings.

IT WARNS, IT CANNOT BLOCK. PostToolUse runs after the write; the change exists
either way. The point is that you find out in the same turn instead of at
commit time or never, while the file is still trivially revertable and before
the other lane's owner builds on top of it.

WHAT IT DOES NOT CATCH, stated plainly so nobody reads a clean run as proof:
  * a write made and reverted inside ONE command (the signature comes back);
  * a write to a file NO open lane claims -- out of scope by design, that is
    not a lane violation;
  * a write to a claim the parser cannot see. 8 of the 44 claims live when this
    was written named a path absent from `git ls-files` -- brace expansions
    (`scripts/{build_wnba_recon`), globs, prose read as a claim. Those guard
    nothing HERE and nothing in `lane-guard` either. `scripts/check_lane_claims.py`
    is the check for that, and it runs at session start.
  * anything under `.syndicate/` or `.claude/`, which are exempt exactly as they
    are in `lane-guard`. Not an oversight: `.syndicate/lanes.md` is claimed by
    an OPEN lane right now and is rewritten by every session that checkpoints.

FAILS OPEN on anything unexpected, and `--pre` NEVER returns non-zero under any
circumstance -- it must not be able to block a command.
Override: `SYNDICATE_LANE_POSTCHECK=off`.
"""
import hashlib
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from hook_trees import roots
    from lane_claims import claims_by_path, is_exempt
    from lane_marker import current_lane, safe_session_id
except Exception as exc:  # pragma: no cover - only when a shared module is gone
    sys.stderr.write(
        "lane-postwrite-check: CANNOT IMPORT its shared modules (%s). Shell "
        "writes are NOT being reconciled against lane claims." % exc + chr(10))
    sys.exit(0)

OFF_ENV = "SYNDICATE_LANE_POSTCHECK"


def _snap_path(root, session_id):
    """Per (tree, session). Two sessions must not share one snapshot slot.

    `.syndicate/.current-lane` is the standing example of what a single shared
    slot does here: whichever session wrote last answered for all of them, and
    it took a real cross-session deploy misattribution to find. Not repeating
    the shape.
    """
    key = hashlib.sha1(
        (os.path.normcase(os.path.abspath(root)) + "|" + session_id).encode("utf-8")
    ).hexdigest()[:16]
    return os.path.join(tempfile.gettempdir(), "syndicate-lane-snap-%s.json" % key)


def _candidates(root, session_id):
    """{path_on_disk: (claimed_token, [slugs])} for files held by OTHER lanes.

    Empty when this tree has no ledger, when the marker names no lane, or when
    every claim belongs to you. Never raises.
    """
    lanes_file = os.path.join(root, ".syndicate", "lanes.md")
    try:
        with open(lanes_file, encoding="utf-8") as fh:
            text = fh.read()
    except Exception:
        return {}

    mine, _used = current_lane(root, session_id)

    out = {}
    try:
        for claimed, slugs in claims_by_path(text).items():
            # A file YOU hold is not a finding, and neither is one where you are
            # among the holders -- a shared claim is the ledger's business, not
            # this hook's.
            others = sorted(s for s in slugs if s != mine)
            if not others or (mine and mine in slugs):
                continue
            if is_exempt(claimed):
                continue
            path = os.path.join(root, *claimed.split("/"))
            # A claim naming a path that does not exist guards nothing. Silent
            # here BY DESIGN -- reporting it every Bash call would be noise, and
            # `scripts/check_lane_claims.py` reports it once, at session start,
            # where it is actionable.
            if os.path.exists(path):
                out[path] = (claimed, others)
    except Exception:
        return {}
    return out


def _sig(path):
    try:
        st = os.stat(path)
        return [int(st.st_mtime_ns), st.st_size]
    except OSError:
        return None


def _pre(payload, session_id):
    """Record the BEFORE picture. Always exits 0, whatever happens."""
    snap = {}
    for root in roots(payload):
        try:
            for path, (claimed, slugs) in _candidates(root, session_id).items():
                snap[path] = {"sig": _sig(path), "claimed": claimed,
                              "slugs": slugs, "root": root}
        except Exception:
            continue
    try:
        with open(_snap_path(payload.get("cwd") or ".", session_id), "w",
                  encoding="utf-8") as fh:
            json.dump(snap, fh)
    except Exception:
        pass
    return 0


def _post(payload, session_id):
    spath = _snap_path(payload.get("cwd") or ".", session_id)
    try:
        with open(spath, encoding="utf-8") as fh:
            snap = json.load(fh)
    except Exception:
        # No snapshot -- the pre pass did not run, or this is the first call.
        # SILENT: with nothing to compare against, every file reads as changed,
        # and a burst of false warnings at session start would train everyone to
        # ignore this hook on day one.
        return 0
    if not isinstance(snap, dict):
        return 0

    # Consume it. A stale snapshot must never be compared against twice: the
    # second comparison would re-report the same change, which is the
    # "fires on state, not on transition" failure.
    try:
        os.remove(spath)
    except Exception:
        pass

    changed = []
    for path, rec in snap.items():
        if not isinstance(rec, dict):
            continue
        before = rec.get("sig")
        after = _sig(path)
        if before == after:
            continue
        changed.append((path, rec, before, after))

    if not changed:
        return 0

    lane, _used = current_lane(payload.get("cwd") or ".", session_id)
    sys.stderr.write(
        "OUT-OF-LANE WRITE: a file claimed by another OPEN lane CHANGED while "
        "your shell" + chr(10) +
        "command was running. lane-guard does not see shell writes, so nothing "
        "blocked this." + chr(10) +
        "Your lane: '" + (lane or "none") + "'." + chr(10) + chr(10))
    for path, rec, before, after in changed:
        claimed = rec.get("claimed", path)
        slugs = ", ".join(rec.get("slugs") or [])
        if after is None:
            what = "DELETED"
        elif before is None:
            what = "created"
        else:
            what = "modified (%d -> %d bytes)" % (before[1], after[1])
        sys.stderr.write("  %s  %s" % (claimed, what) + chr(10))
        sys.stderr.write("      claimed by OPEN lane: %s" % slugs + chr(10))
        sys.stderr.write("      in tree: %s" % rec.get("root", "?") + chr(10))
    sys.stderr.write(
        chr(10) +
        "This is a WARNING, not a block -- the write already happened, and the "
        "check" + chr(10) +
        "sees a (mtime, size) change, never an author, so a concurrent session "
        "could" + chr(10) +
        "have made it. If it was you: revert it, or take the claim in "
        ".syndicate/lanes.md" + chr(10) +
        "and say so in the other lane's block. Do not edit across lanes "
        "silently." + chr(10) +
        "Silence: " + OFF_ENV + "=off" + chr(10))
    return 2


def main():
    if os.environ.get(OFF_ENV, "").lower() == "off":
        return 0
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if payload.get("tool_name", "") not in ("Bash", "PowerShell"):
        return 0

    session_id = safe_session_id(payload.get("session_id"))
    if not session_id:
        # Without a session id the snapshot slot would be shared, and a shared
        # slot is the bug this file refuses to re-make. Also: no session id
        # means no per-session lane marker, so "your lane" is unknowable and
        # every claim would look like someone else's.
        return 0

    if "--pre" in sys.argv[1:]:
        try:
            return _pre(payload, session_id)
        except Exception:
            return 0  # a pre pass must NEVER block a command
    try:
        return _post(payload, session_id)
    except Exception:
        return 0


sys.exit(main())
