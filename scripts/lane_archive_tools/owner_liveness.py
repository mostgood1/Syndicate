"""Read-only: for every CLOSED lane block on origin/main's lanes.md, decide whether it is SAFE to
archive from outside its owning session.

SAFE requires ALL of:
  * the header status is CLOSED[-X] and the slug holds no claims (lane_claims._claims);
  * the block's first 3 lines name at least one Claude session id (a full uuid NOT preceded by
    `local_`, or `session <8hex>`), and EVERY such session's transcript
    (~/.claude/projects/*/<sid>*.jsonl) is idle >= --idle-min minutes; an unknown transcript is NOT safe;
  * the newest commit touching ANY line of the block on origin/main (git blame, committer time) is
    >= --idle-min old -- catches a close/edit by a session the header does not name;
  * no worktree under C:\\tmp\\syndicate-sessions has a RECENT uncommitted `.syndicate/lanes.md` diff
    that mentions the slug (the owner may be reopening it), and the lane-named worktree, if any, is
    clean. "Recent" means the worktree file's mtime is within --diff-stale-min (default 3 days,
    deliberately NOT --idle-min); an older diff is abandoned
    WIP, is reported as `stale-diff-ignored<name>[<days>d]`, and does NOT block. An unreadable mtime
    still blocks. Added 2026-09-23 after a 13.8-day-old diff blocked 54 KB of archiving with no live
    party involved.

Usage:
  py -3 owner_liveness.py --worktree <path to a worktree synced to origin/main> [--idle-min 240]
Last line: SAFE_SLUGS=<comma list, possibly empty>
Origin: session 3a65723e, 2026-09-15. On 09-15 a live owner was reopening a lane that read CLOSED
on origin/main, in an uncommitted worktree edit; see learnings.md "a lane whose header reads CLOSED
on origin/main is safe to archive".
"""
import argparse
import re
import subprocess
import sys
import time
import types
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ap = argparse.ArgumentParser()
ap.add_argument("--worktree", required=True)
ap.add_argument("--idle-min", type=float, default=60)
ap.add_argument("--diff-stale-min", type=float, default=4320,
                help="an uncommitted worktree lanes.md diff older than this (minutes) is abandoned WIP, "
                     "reported but not blocking. Default 4320 = 3 days. NOT tied to --idle-min.")
args = ap.parse_args()
W = Path(args.worktree)
SESS = Path(r"C:\tmp\syndicate-sessions")
PROJ = Path.home() / ".claude" / "projects"
UUID = re.compile(r"(?<!local_)\b([0-9a-f]{8})-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\b")
SHORT = re.compile(r"\bsession ([0-9a-f]{8})\b")
CLOSED_HDR = re.compile(r"^### (\S+) — CLOSED")
BOUNDARY = re.compile(r"^#{2,3}\s")

subprocess.run(["git", "-C", str(W), "fetch", "-q", "origin"], check=True)
text = subprocess.run(["git", "-C", str(W), "show", "origin/main:.syndicate/lanes.md"],
                      capture_output=True, check=True).stdout.decode("utf-8")
L = text.split("\n")
mod = types.ModuleType("lane_claims_ro")
guard = W / ".claude" / "hooks" / "lane_claims.py"
exec(compile(guard.read_text(encoding="utf-8"), str(guard), "exec"), mod.__dict__)
claimed = {s for s, _ in mod._claims(text)}
open_slugs = {m.group(1) for l in L for m in [re.match(r"^### (\S+) — OPEN\b", l)] if m}

transcripts = {}
for f in PROJ.glob("*/*.jsonl"):
    transcripts.setdefault(f.stem[:8], []).append(f.stat().st_mtime)

def changed_lines_only(diff):
    """The ADDED/REMOVED lines of a unified diff, nothing else.

    A slug can appear in a lanes.md diff as unchanged CONTEXT. Lane blocks are large, so every hunk
    carries its neighbours' `### slug - STATUS` headers in the context lines around each change, and
    matching the whole diff text attributes ANOTHER lane's edit to them. Measured 2026-09-23:
    worktree `tripwire-applog-page-cap` held a diff that did not touch `render-yaml-env-drift` at
    all -- the slug was present only as a context line in the first hunk -- and that blocked
    15,508 B of CLOSED-STALE lane from being archived. `+++`/`---` are file headers, not content;
    `@@` hunk headers carry a trailing context excerpt and are excluded for the same reason.

    This NARROWS the check, it does not weaken it. A worktree that really edits a slug's block still
    produces a `+` or `-` line carrying that slug, because a lane edit rewrites the header or a line
    inside the block. Only pure-context mentions stop matching."""
    return "\n".join(l for l in diff.split("\n")
                     if l[:1] in ("+", "-") and not l.startswith(("+++", "---")))


worktree_diffs = {}
stale_diffs = {}   # name -> (age_minutes, diff text); mentioned in output, but NOT a WAIT reason
for d in SESS.iterdir() if SESS.exists() else []:
    if not (d / ".git").exists():
        continue
    r = subprocess.run(["git", "-C", str(d), "diff", "HEAD", "--", ".syndicate/lanes.md"], capture_output=True)
    if r.returncode == 0 and r.stdout.strip():
        # Staleness bound (added 2026-09-23): an uncommitted lanes.md diff is a LIVE-OWNER signal only
        # while it is actually recent. Measured 2026-09-23: worktree `bandwidth-controlled-transfer`
        # held a 94/79 lanes.md diff whose mtime was 13.8 DAYS old, on a HEAD of the same age, with
        # every session named on it 7-10 days idle -- abandoned WIP, not a live edit. Unbounded, it
        # blocked 54 KB of archiving indefinitely with NO live party involved, and nothing said why.
        # This bound is DELIBERATELY NOT --idle-min. Owner idleness and diff abandonment are different
        # questions with different scales: tying them together was tried on 2026-09-23 and at the
        # default 240m it also discarded `tripwire-applog-page-cap`'s 0.2d diff, whose session was
        # RUNNING at that moment. A live session can legitimately sit on a pending lanes.md edit for
        # hours. --diff-stale-min therefore defaults to 3 DAYS, which separates the measured
        # abandonment case (13.8d, HEAD equally old, every named session 7-10d idle) from a live
        # session's in-progress work, and is tunable on its own.
        # An UNREADABLE mtime stays blocking: unknown must not default to the permissive branch.
        try:
            age_min = (time.time() - (d / ".syndicate" / "lanes.md").stat().st_mtime) / 60
        except OSError:
            age_min = None
        text = changed_lines_only(r.stdout.decode("utf-8", "replace"))
        if age_min is not None and age_min > args.diff_stale_min:
            stale_diffs[d.name] = (age_min, text)
        else:
            worktree_diffs[d.name] = text

now = time.time()

# Last-modifier check (added 2026-09-18, session 4991d2ec): the header names the OWNER, but a
# block can be closed or edited by a session it never names (fotmob-team-name-aliases was CLOSED
# by scheduled task session 96d06e18 at 19:08Z; owner da346015 idle 3910m read SAFE). Blame every
# CLOSED block's lines on origin/main in ONE call; a block whose newest touching commit is younger
# than --idle-min is WAIT. Committer time, so a rebased land counts as a fresh modification.
def block_end(i):
    return next((j for j in range(i + 1, len(L)) if BOUNDARY.match(L[j])), len(L))

closed_idx = [i for i, l in enumerate(L) if CLOSED_HDR.match(l)]
last_mod = {}   # header index -> (sha, committer_time)
if closed_idx:
    cmd = ["git", "-C", str(W), "blame", "--porcelain"]
    for i in closed_idx:
        cmd += ["-L", f"{i + 1},{max(i + 1, block_end(i))}"]
    out = subprocess.run(cmd + ["origin/main", "--", ".syndicate/lanes.md"],
                         capture_output=True, check=True).stdout.decode("utf-8", "replace").split("\n")
    ctime, line_commit = {}, {}
    cur = None
    for o in out:
        hm = re.match(r"^([0-9a-f]{40}) \d+ (\d+)", o)
        if hm:
            cur = hm.group(1)
            line_commit[int(hm.group(2)) - 1] = cur
        elif o.startswith("committer-time ") and cur:
            ctime[cur] = int(o.split()[1])
    for i in closed_idx:
        shas = {line_commit[k] for k in range(i, block_end(i)) if k in line_commit}
        if shas:
            newest = max(shas, key=lambda s: ctime.get(s, 0))
            last_mod[i] = (newest, ctime.get(newest, 0))

safe = []
for i, line in enumerate(L):
    m = CLOSED_HDR.match(line)
    if not m:
        continue
    slug = m.group(1)
    head = "\n".join(L[i:i + 3])
    sids = sorted(set(UUID.findall(head)) | set(SHORT.findall(head)))
    idles = {s: ((now - max(transcripts[s])) / 60 if s in transcripts else None) for s in sids}
    reasons = []
    if slug in claimed:
        reasons.append("holds claims")
    if slug in open_slugs:
        reasons.append("also has an OPEN header")
    if not sids:
        reasons.append("no session id in header")
    for s, v in idles.items():
        if v is None:
            reasons.append(f"{s} transcript not found")
        elif v < args.idle_min:
            reasons.append(f"{s} idle {v:.0f}m < {args.idle_min:.0f}m")
    lm = last_mod.get(i)
    lm_age = (now - lm[1]) / 60 if lm else None
    if lm is None:
        reasons.append("block last-modifier unknown (blame empty)")
    elif lm_age < args.idle_min:
        reasons.append(f"block last modified {lm_age:.0f}m ago by {lm[0][:8]} (< {args.idle_min:.0f}m)")
    colliding = [n for n, diff in worktree_diffs.items() if slug in diff]
    if colliding:
        reasons.append("uncommitted lanes.md edit mentions it in worktree(s) " + ",".join(colliding))
    # Stale diffs are NOT a WAIT reason, but they are never silently dropped: an ignored signal that
    # prints nothing is indistinguishable from a signal that was never there.
    stale_hits = [f"{n}[{age / 1440:.1f}d]" for n, (age, dtext) in stale_diffs.items() if slug in dtext]
    lane_wt = SESS / slug
    if lane_wt.exists() and (lane_wt / ".git").exists():
        if subprocess.run(["git", "-C", str(lane_wt), "status", "--porcelain"], capture_output=True).stdout.strip():
            reasons.append("lane-named worktree dirty")
    idle_txt = ", ".join(f"{s}={'?' if v is None else f'{v:.0f}m'}" for s, v in idles.items())
    verdict = "SAFE" if not reasons else "WAIT: " + "; ".join(reasons)
    lm_txt = f" lastmod[{lm[0][:8]}={lm_age:.0f}m]" if lm else " lastmod[?]"
    stale_txt = (" stale-diff-ignored" + ",".join(stale_hits)) if stale_hits else ""
    print(f"{slug:40s} sessions[{idle_txt}]{lm_txt}{stale_txt} -> {verdict}")
    if not reasons:
        safe.append(slug)
print(f"SAFE_SLUGS={','.join(safe)}")
