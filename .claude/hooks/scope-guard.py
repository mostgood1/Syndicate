#!/usr/bin/env python3
"""PostToolUse(Edit|Write|MultiEdit|NotebookEdit) - names a write outside YOUR OWN lane's declared scope.

THE GAP IT FILLS, and it is the last one in this directory. Every other guard
here protects FILES AND THE LEDGER FROM THE SESSION: `lane-guard` blocks another
lane's claims, `lane-postwrite-check` is its shell-write sibling, `commit-guard`
the shared index, `discard-guard` content that exists nowhere else,
`deploy-guard` the deploy locks, `checkpoint-guard` uncheckpointed work. NOTHING
protected THE OBJECTIVE FROM THE SESSION.

The hole is exact. `lane-guard.py:187` fires only on `is claimed by OPEN lane
'<conflict>'`, so a write to a file NO lane claims is free -- stated as a
deliberate non-goal in `lane-postwrite-check`'s own docstring ("a write to a file
NO open lane claims -- out of scope by design, that is not a lane violation").
That is correct for OWNERSHIP and it is exactly wrong for SCOPE. `current_lane()`
had two non-test consumers when this was written (`lane-guard.py:124`,
`lane-postwrite-check.py:149,264`) and BOTH used it only to exclude yourself from
other-lane conflict detection. The five audit scripts (`check_lane_claims`,
`check_lane_invariants`, `lane_identity_check`, `lane_claim_audit`,
`audit_lane_unguarding`) all answer ledger-COHERENCE questions. Nobody asked "is
this write serving the goal I declared". Located before building, per
`learnings.md` 2026-09-07 FORBIDDEN: building a guard before locating the one
that already exists.

WHAT IT IS FOR, measured 2026-09-08 ON `origin/main`, not on the checkout:
**47 OPEN lane blocks, 22 UNOWNED** (counted on the header line; counting the
body's UNOWNED markers too gives 25). 21 of the 47 have no date anywhere in the
block newer than 2026-09-01 -- open, and untouched for a week. Sessions take an
objective, hit a lead, follow the lead, and the objective is never closed.

READ THE LEDGER FROM `origin/main`, WHICH IS HOW THESE NUMBERS NEARLY WENT IN
WRONG. The primary checkout was **429 commits behind** when this was built, and
its `lanes.md` carries 70 header blocks against origin's 52 -- a diverged
snapshot that never received origin's archive passes. The first draft of this
docstring cited a 2026-09-06 cluster of same-day lane closures as the worked
example; those blocks do not exist on `origin/main` in `lanes.md` OR in
`lanes_closed.md`, so the claim could not be stood up and was removed rather
than softened. `MSYS_NO_PATHCONV=1 git show origin/main:.syndicate/lanes.md` is
the read -- Git Bash mangles the bare `rev:path` colon syntax on this machine.

THE MECHANISM, stated better than this docstring can, by the lane `profitable-
buckets` (opened 2026-09-08, header: "Opened because the work kept deviating
into sim internals -- user"):

    This session already spent hours going from a ledger bucket gap into
    segment pricing, first5 skill, full-game discrimination, late-inning
    ceilings, a home-field term and two deploys. EACH HOP WAS LOCALLY
    JUSTIFIED AND THE SUM WAS DEVIATION.

That last sentence is the entire design rationale. No single hop is catchable by
judgement, because every hop IS justified at the moment it is taken; only the
sum is wrong, and nothing was watching the sum. That lane also carries a
hand-written ANTI-DRIFT RULE, which is a session solving this by willpower in
prose -- exactly the thing this repo's culture says should be a mechanism.
(Both that lane and its rule were UNPUSHED when this was written: local only,
origin has neither. An unpushed rule is not a shared rule.)

HOW OFTEN THE ALTERNATIVE IS TAKEN, measured on `origin/main`: 9 instances of
deliberate deferral in `lanes.md` ("NOT MINE TO WIRE", "it wants its own lane",
"spawned as its own task") against 41 `findings_*.md` files -- the usual product
of following a lead inline. **Roughly 1 deferral per 4.5 leads followed.** 18 of
54 findings/handoff files are referenced by no lane at all.

NO STANDING RULE COVERED THIS. `learnings.md` on `origin/main` (4,081 lines) has
no FORBIDDEN or standing rule on scope drift, staying on-goal, deferring leads,
or delegation -- checked before building, since a rule already stated is cheaper
than a guard. And the `syndicate-engineer` subagent that CLAUDE.md prescribes
for exactly this has ZERO recorded invocations in the entire ledger.

MEASURED 2026-09-08, AND IT IS NOT MOSTLY A DRIFT DETECTOR. The falsification
test this guard was shipped owing has now run, over 345 session transcripts
mapped to lanes through the `session <uuid>` in their headers, scored with THIS
FILE'S OWN `_area`/`_is_test` (loaded by AST, not reimplemented).

  RATE, on 22 scoreable sessions: **11 firings total, mean 0.50 per session,
  median 0, max 4. SILENT in 16 of 22 (73%). Zero sessions above 4.** The
  once-per-area cap holds: this costs about one message every two sessions.

  PRECISION, hand-classified against each lane's stated Goal: **6 of 11 were
  IN-GOAL edits into an area the lane had simply not declared. 4 were genuine
  excursions; 1 borderline.** The strongest true positive was a session whose
  four lanes were about an unknown-submit banner and a Polymarket price gate
  editing `football/sim_engine/smartsim2/`. One fired on eight scratch scripts
  written to the REPO ROOT (`_write_log.py`, `_ledger3.py`, ...).

SO THE HONEST DESCRIPTION IS NARROWER THAN THE ONE THIS FILE SHIPPED WITH: at
the measured rate it is mostly an UNDER-DECLARATION detector, with real drift a
large minority. That is still worth having -- a stale `Files:` block is exactly
what makes `lane-guard`'s collision detection lie, and this guard's own message
already prescribes the right fix ("add the path to this lane's `Files:`") -- but
do not claim it catches drift 11 times out of 11. It caught it 4 times.

EVERY BIAS IN THAT MEASUREMENT FLATTERS THE GUARD, so the firing rate is a LOWER
BOUND: sessions were scored against the UNION of all their lanes' areas (one
session held 14) while the real hook checks the ONE lane in the marker; the
CURRENT `Files:` lists were scored against historical edits, so a lane that added
paths later reads as having declared them all along; 14 of 55 sessions carried a
bogus `[compacted]` lane attribution that inflates the declared set; and 33
sessions were excluded outright because their lane has zero parsed claims (a
released-claims lane cannot yield a false-positive rate).

WHY IT WARNS AND CANNOT BLOCK. Drift is a judgement call -- some out-of-area
writes genuinely serve the goal -- and this repo has already lost two guards to
firing on correct work (`checkpoint-guard`'s docstring: "A warning that fires
every time carries no information", and `lane-guard` blocked three consecutive
correct edits in one session on marker contention). PostToolUse runs after the
write, so the change exists either way; the point is that you are asked the
question in the same turn, while the edit is still trivially revertable. Exit 2
is what carries the text to the model -- the same convention its PostToolUse
siblings use (`lane-postwrite-check.py:294`, `ledger-postwrite-check.py:178`).

ONCE PER AREA PER SESSION, and this is the part that makes it survivable. An
obvious implementation speaks on every out-of-area edit, which for a session
legitimately working across two directories means a message per keystroke and a
guard people learn to scroll past. The AREA (the file's directory) is recorded
the first time it is reported and never reported again for that session, so the
cost of a real excursion is exactly one message.

THE AREA RULE IS DELIBERATELY COARSE: two paths are in the same area iff they
have the same directory. `syndicate/features/nfl/cards.py` and
`.../nfl/picks.py` are one area; `.../nfl/cards.py` and `.../mlb/cards.py` are
two, and cross-sport is the classic drift shape in this repo. A rule finer than
this fires on normal work; a rule coarser (first two segments) puts all of
`syndicate/features` in one area and sees nothing.

TESTS ARE NEVER DRIFT. Writing the test for the change you just made is the
work, so `tests/**` and any `test_*` basename are exempt regardless of area.
Without that carve-out a lane declaring one source file is warned the moment it
does the right thing, which is the false positive most likely to get this
switched off.

WHAT IT DOES NOT CATCH, stated so nobody reads a clean run as proof:
  * shell writes -- heredocs, `sed -i`, `python - <<'PY'`. `lane-postwrite-check`
    measured those at about 1 in 10 of all writes to tracked source. Closing it
    means predicting a write from a command string, which that file explains at
    length is not reliably possible. This is the Edit-family layer only.
  * anything under `.syndicate/` or `.claude/`, exempt via `lane_claims.is_exempt`
    exactly as in `lane-guard`. Checkpointing is not drift, and `lanes.md` is
    rewritten by every session that checkpoints.
  * drift WITHIN a declared area. A lane that claims a directory and wanders
    inside it is invisible here. The `/checkpoint` MET/NOT MET/DRIFTED line is
    the instrument for that; this one only sees the file system.
  * a session whose lane declares no parseable claims -- reported once, as
    itself, because `check_lane_claims.py` exists for that class of defect.

`_goal_for()` LIVES HERE AND ITS HOME IS `lane_claims.py`. It is the only
lanes.md field parser outside that module. It is here because it has exactly one
caller; the moment a second appears, move it, per `learnings.md` 2026-08-20 -- a
defect in what all the guards share must be fixed in a shared module or the next
guard re-makes it.

FAILS OPEN on anything unexpected, and never silently: a missing shared module
says so on stderr, because "an inert guard and a satisfied guard are
indistinguishable from outside" is this repo's own phrase for how
`ledger-append-guard` read as passing for its entire existence.
Override: `SYNDICATE_SCOPE_GUARD=off`.
"""
import hashlib
import json
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from hook_trees import roots
    from lane_claims import _claims, _norm, is_exempt
    from lane_marker import current_lane, safe_session_id
except Exception as exc:  # pragma: no cover - only when a shared module is gone
    sys.stderr.write(
        "scope-guard: CANNOT IMPORT its shared modules (%s). Writes are NOT "
        "being checked against the current lane's declared scope.\n" % exc)
    sys.exit(0)

OFF_ENV = "SYNDICATE_SCOPE_GUARD"
TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")

# The lane block field this reads back to the session. Tolerates the bold and
# the plain spelling, the same way `lane_claims.FILES_RE` does for `Files:`.
GOAL_RE = re.compile(r"^\s*-\s*\*{0,2}Goal\b[^:]*:?(.*)$", re.IGNORECASE)
# Any following line that starts a NEW field ends the goal.
FIELD_RE = re.compile(r"^\s*-\s*\*{0,2}\w")
HEADER_RE = re.compile(r"^###\s")
GOAL_MAX_LINES = 4


def _area(rel):
    """The directory a path lives in. '.' for a repo-root file."""
    return os.path.dirname(_norm(rel)) or "."


def _is_test(rel):
    """Writing the test for your change is the work, never drift."""
    norm = _norm(rel)
    return (
        norm == "tests"
        or norm.startswith("tests/")
        or "/tests/" in "/" + norm
        or os.path.basename(norm).startswith("test_")
    )


def _seen_path(root, session_id):
    """Per (tree, session). Two sessions must not share one slot.

    Same reasoning and same shape as `lane-postwrite-check._snap_path`:
    `.syndicate/.current-lane` is the standing example of what one shared slot
    does here, and it took a cross-session deploy misattribution to find.
    Lives in the OS temp dir, never in the repo -- a hook that littered the
    tree it guards would be caught by its siblings.
    """
    key = hashlib.sha1(
        (os.path.normcase(os.path.abspath(root)) + "|" + session_id).encode("utf-8")
    ).hexdigest()[:16]
    return os.path.join(tempfile.gettempdir(), "syndicate-scope-seen-%s.json" % key)


def _load_seen(path):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return set(data) if isinstance(data, list) else set()
    except Exception:
        return set()


def _save_seen(path, seen):
    """Best effort. Losing this file costs one duplicate message, never a block."""
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(sorted(seen), fh)
    except Exception:
        pass


def _goal_for(text, slug):
    """The `- Goal:` body of lane `slug`, verbatim, capped at GOAL_MAX_LINES.

    Verbatim is the whole point. The session has forgotten the goal -- that is
    the condition being treated -- so a paraphrase would be the guard writing
    the thing it is supposed to be reminding you of.
    """
    in_lane = False
    out = []
    for line in text.splitlines():
        if HEADER_RE.match(line):
            if in_lane:
                break
            in_lane = line.split()[1:2] == [slug]
            continue
        if not in_lane:
            continue
        if out:
            # Collecting a wrapped goal; a new field or a blank line ends it.
            if not line.strip() or FIELD_RE.match(line):
                break
            out.append(line.strip())
            if len(out) >= GOAL_MAX_LINES:
                break
            continue
        m = GOAL_RE.match(line)
        if m:
            first = m.group(1).strip()
            out.append(first if first else "(empty)")
    return " ".join(out).strip()


def _my_areas(text, slug):
    """(areas, claim_count) for the lane this session holds."""
    areas, n = set(), 0
    for s, path in _claims(text):
        if s != slug:
            continue
        n += 1
        areas.add(_area(path))
    return areas, n


def _lanes_text(payload):
    """(root, text) for the first tree that actually has a lane ledger."""
    for root in roots(payload):
        lanes = os.path.join(root, ".syndicate", "lanes.md")
        if os.path.exists(lanes):
            try:
                with open(lanes, encoding="utf-8") as fh:
                    return root, fh.read()
            except Exception:
                return root, ""
    return "", ""


def _say(body, once_key):
    # A NON-ASCII GOAL MUST NOT CRASH THIS GUARD INTO SILENCE, and that is not
    # hypothetical: every lane header in `lanes.md` is em-dash delimited by the
    # ledger's own rule, so goals routinely carry U+2014. Writing one to a
    # cp1252 console raises UnicodeEncodeError, which `__main__` would catch and
    # turn into exit 0 -- the guard would go quiet on exactly the lanes that
    # follow the house style. Caught live 2026-09-08 on this file's own lane.
    # `errors="replace"` because a mangled dash is a cosmetic loss and a silent
    # guard is not.
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.stderr.write(body)
    sys.stderr.write(
        "\nFIRST TIME THIS SESSION for %s. You will not be told again for it.\n"
        "The write already happened -- this is a WARNING and cannot block you.\n"
        "Silence: %s=off\n" % (once_key, OFF_ENV))
    return 2


def main():
    if os.environ.get(OFF_ENV, "").lower() == "off":
        return 0
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if payload.get("tool_name", "") not in TOOLS:
        return 0

    path = (payload.get("tool_input") or {}).get("file_path")
    if not path:
        return 0

    # `is_exempt` checks the PATH ITSELF for a `.syndicate`/`.claude` segment
    # rather than its position under a root, so it holds in the primary tree
    # and in any linked worktree alike -- the exact bug fixed in `lane-guard`
    # on 2026-08-18.
    if is_exempt(path):
        return 0

    session_id = safe_session_id(payload.get("session_id"))
    if not session_id:
        # No session id means no per-session marker, so "your lane" is
        # unknowable, and the once-per-area slot would be shared between
        # sessions. A shared slot is the bug this directory refuses to re-make.
        return 0

    root, text = _lanes_text(payload)
    if not text:
        return 0

    try:
        rel = _norm(os.path.relpath(path, root))
    except Exception:
        return 0

    # OUTSIDE THE TREE THAT HOLDS THE LEDGER -> NOT SCOPE-JUDGEABLE. `relpath`
    # answers with a `../../..` escape rather than failing, and firing on that
    # is worse than staying quiet twice over: the message names a path nobody
    # can act on, and the bogus "area" is then written into the once-per-area
    # slot, so the REAL area of that name is silenced for the rest of the
    # session. Caught live 2026-09-08 -- a Git Bash `/c/Users/...` cwd against
    # a Windows-Python `abspath` produced exactly this, five levels of `..`.
    if rel == ".." or rel.startswith("../"):
        return 0

    if _is_test(rel):
        return 0

    seen_path = _seen_path(root, session_id)
    seen = _load_seen(seen_path)

    slug, _used = current_lane(root, payload.get("session_id"))

    if not slug:
        if "\x00no-lane" in seen:
            return 0
        seen.add("\x00no-lane")
        _save_seen(seen_path, seen)
        return _say(
            "scope-guard: this session holds NO LANE, and just wrote %s.\n\n"
            "  `.syndicate/lanes.md` is how the next session learns what you were\n"
            "  doing. Without a lane there is no declared goal to drift from, and\n"
            "  nothing to close.\n\n"
            "    /lane open <slug> \"<goal>\"\n" % rel,
            "this session")

    areas, n_claims = _my_areas(text, slug)

    if not n_claims:
        if "\x00no-claims" in seen:
            return 0
        seen.add("\x00no-claims")
        _save_seen(seen_path, seen)
        return _say(
            "scope-guard: lane '%s' declares NO PARSEABLE `Files:` claim, so this\n"
            "write (%s) cannot be checked against its scope -- and neither\n"
            "`lane-guard` nor `lane-postwrite-check` is protecting those paths for\n"
            "you. `scripts/check_lane_claims.py` is the check for this.\n"
            % (slug, rel), "lane '%s'" % slug)

    area = _area(rel)
    if area in areas or area in seen:
        return 0

    seen.add(area)
    _save_seen(seen_path, seen)

    goal = _goal_for(text, slug) or "(no `- Goal:` line found in the lane block)"
    return _say(
        "scope-guard: %s is OUTSIDE lane '%s'.\n\n"
        "  declared areas: %s\n"
        "  this write:     %s\n\n"
        "  the lane's Goal, verbatim:\n"
        "    %s\n\n"
        "IS THIS THE GOAL, OR A LEAD?\n"
        "  goal -> add the path to this lane's `Files:` in .syndicate/lanes.md.\n"
        "  lead -> DO NOT follow it. One line, then back to the objective:\n"
        "            /lead \"<what you saw>\"\n"
        "          It is cheaper than the excursion you were about to take, which\n"
        "          is the entire point -- this repo defers about 1 lead in 4.5,\n"
        "          and 18 of 54 findings files are referenced by no lane.\n"
        "          If it IS now the objective, say so out loud and open a lane;\n"
        "          switching objectives silently is what this guard is for.\n"
        "          \"Each hop was locally justified and the sum was deviation.\"\n"
        "            -- lane `profitable-buckets`, 2026-09-08\n"
        % (rel, slug, ", ".join(sorted(areas)) or "(none)", area, goal),
        "area '%s'" % area)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)  # fail open, always
