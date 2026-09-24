"""Read-only watcher: exit when at least one closed-today lane block is safe to archive from outside.

Safe = block still on origin/main lanes.md, header CLOSED, every session id named in the block's
header or closure lines has a transcript idle >= IDLE_MIN, the newest commit touching any line of the
block on origin/main is >= IDLE_MIN old (last-modifier check), no worktree under SESS has an
uncommitted `.syndicate/lanes.md` diff mentioning the slug, the slug holds no claims and has no OPEN
header (claim-state checks; claims unknown = unsafe), and any worktree named for the lane is clean. Also exits when every block is gone (owners archived them), or at MAX_WAIT_MIN.
Polls every POLL_SEC. Writes nothing to the repo.
"""
import re, subprocess, sys, time, types
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")
import os
W = os.environ.get("ARCHIVE_WORKTREE") or sys.exit("set ARCHIVE_WORKTREE")
SESS = Path(r"C:\tmp\syndicate-sessions")
PROJ = Path(r"C:\Users\tempadmin\.claude\projects")
SLUGS = ("disk-inventory-test-clock fotmob-season-scoped-league-ids ncaaf-prop-kickoff-slate-date "
         "preview-date-pin-inert quote-shard-date-fallback-prod soccer-season-market-audit "
         "test-wall-clock-timebombs wnba-schedule-guard-fix").split()
IDLE_MIN, POLL_SEC, MAX_WAIT_MIN = 60, 300, 120
# An uncommitted worktree lanes.md diff older than this is abandoned WIP: reported, not blocking.
# 3 days, DELIBERATELY not IDLE_MIN -- see owner_liveness.py for the measurement (2026-09-23).
DIFF_STALE_MIN = 4320
# Claude session ids only: a full uuid NOT preceded by `local_` (the desktop id has no transcript),
# or a bare `session <8hex>`. Both reduce to the 8-char prefix the transcript glob matches.
UUID = re.compile(r"(?<!local_)\b([0-9a-f]{8})-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\b")
SHORT = re.compile(r"\bsession ([0-9a-f]{8})\b")
start = time.time()

BOUNDARY = re.compile(r"^#{2,3}\s")


def block_last_mod(L):
    """Last-modifier check (added 2026-09-18, session 4991d2ec; same rule as owner_liveness.py):
    header index -> (sha, minutes since the newest commit touching any line of that CLOSED block on
    origin/main). Catches a close/edit by a session the header does not name. One blame call."""
    idx = [i for i, l in enumerate(L) if re.match(r"^### \S+ — CLOSED", l)]
    if not idx:
        return {}
    end = lambda i: next((j for j in range(i + 1, len(L)) if BOUNDARY.match(L[j])), len(L))
    cmd = ["git", "-C", W, "blame", "--porcelain"]
    for i in idx:
        cmd += ["-L", f"{i + 1},{max(i + 1, end(i))}"]
    out = subprocess.run(cmd + ["origin/main", "--", ".syndicate/lanes.md"], capture_output=True).stdout.decode("utf-8", "replace").split("\n")
    ctime, line_commit, cur = {}, {}, None
    for o in out:
        hm = re.match(r"^([0-9a-f]{40}) \d+ (\d+)", o)
        if hm:
            cur = hm.group(1)
            line_commit[int(hm.group(2)) - 1] = cur
        elif o.startswith("committer-time ") and cur:
            ctime[cur] = int(o.split()[1])
    res = {}
    for i in idx:
        shas = {line_commit[k] for k in range(i, end(i)) if k in line_commit}
        if shas:
            s = max(shas, key=lambda x: ctime.get(x, 0))
            res[i] = (s, (time.time() - ctime.get(s, 0)) / 60)
    return res


def changed_lines_only(diff):
    """The ADDED/REMOVED lines of a unified diff, nothing else. Same fix as owner_liveness.py,
    2026-09-23: a slug can appear in a lanes.md diff as unchanged CONTEXT (lane blocks are large, so
    every hunk carries its neighbours' headers), and matching the whole diff text attributes ANOTHER
    lane's edit to them. Measured that day: worktree `tripwire-applog-page-cap` did not touch
    `render-yaml-env-drift` at all, yet blocked 15,508 B of CLOSED-STALE lane from archiving.
    NARROWS the check only: a real edit to a slug's block always produces a `+`/`-` line with that
    slug in it."""
    return "\n".join(l for l in diff.split("\n")
                     if l[:1] in ("+", "-") and not l.startswith(("+++", "---")))


def drop_upstream_echoes(changed, main_lines):
    """Discard changed lines whose content is ALREADY what `origin/main` says. Added 2026-09-24.

    `changed_lines_only()` answers "did this worktree CHANGE a line naming the slug". It compares
    against the worktree's OWN HEAD, so on a checkout that is behind, UPSTREAM's edits render as
    that worktree's +/- lines and are attributed to its session. This is a THIRD false-positive
    mechanism, distinct from the two fixed on 2026-09-23 (unchanged CONTEXT lines; ABANDONED
    diffs), and neither of those guards can see it -- the diff is genuinely fresh and the owner
    genuinely live, so both correctly decline to act.

    Measured 2026-09-24: worktree `tripwire-applog-page-cap`, HEAD 143 commits behind, named 6 of
    the 8 CLOSED slugs. Of its 310 changed lines only 13 were novel, and every one of the 3 slugs
    blocked SOLELY by it was named by exactly ONE + line byte-identical to `origin/main`. A second
    worktree, only 18 commits behind, produced the same effect on 5 slugs an hour earlier and had
    stopped doing so an hour after that -- so this is the ordinary, intermittent state of a large
    worktree pool, not one stale outlier a run can expect to be absent.

    The rule: a + line whose text is already on `origin/main`, and a - line whose text is already
    absent from it, say nothing about this worktree's pending work. Everything else is kept -- a
    novel + line, and a - line removing content `origin/main` still has.

    This NARROWS the check and cannot hide real work: a session that edits a block to exactly what
    upstream already says has made a no-op edit, and any other edit leaves a line failing both
    tests. The comparison is whole-line set membership, so a genuine edit that reproduced a line
    existing verbatim elsewhere in `origin/main`'s lanes.md would be discounted; lane lines are
    long and distinctive enough that this has not been observed, but it is a real bound on the
    method and not a proof.

    Takes and returns the SAME shape as `changed_lines_only()`: the diff text joined by
    newlines, NOT a list. The first draft of this function took a list, so it iterated the
    string CHARACTER BY CHARACTER and returned a list of single characters -- on which the
    callers' `slug in diff` test is False for every slug, silently disabling the worktree
    check altogether and making every CLOSED block archivable. Caught by
    test_the_measured_case before it ran anywhere. Keep the two signatures in step.
    """
    return "\n".join(
        l for l in changed.split("\n")
        if not ((l[:1] == "+" and l[1:] in main_lines)
                or (l[:1] == "-" and l[1:] not in main_lines)))


def worktree_lanes_diffs(main_lines):
    """Uncommitted-edit check (added 2026-09-18, session 4991d2ec; same rule as owner_liveness.py):
    worktree name -> its uncommitted `.syndicate/lanes.md` diff. A slug named in one may be being
    reopened by a live session even though origin/main reads CLOSED.

    Staleness bound added 2026-09-23 (same change as owner_liveness.py): returns (fresh, stale).
    A diff whose worktree file has not been written for DIFF_STALE_MIN is abandoned WIP, not a live
    owner -- measured that day, `bandwidth-controlled-transfer` held a 94/79 diff 13.8 DAYS old, on
    an equally old HEAD, every session named on it 7-10 days idle, and it blocked 54 KB of archiving
    with no live party involved. The bound is NOT IDLE_MIN: at 240m it also discarded a 0.2d diff
    whose session was running. An unreadable mtime stays BLOCKING (unknown is not permissive)."""
    res, stale = {}, {}
    for d in SESS.iterdir() if SESS.exists() else []:
        if not (d / ".git").exists():
            continue
        r = subprocess.run(["git", "-C", str(d), "diff", "HEAD", "--", ".syndicate/lanes.md"], capture_output=True)
        if r.returncode == 0 and r.stdout.strip():
            try:
                age_min = (time.time() - (d / ".syndicate" / "lanes.md").stat().st_mtime) / 60
            except OSError:
                age_min = None
            text = drop_upstream_echoes(changed_lines_only(r.stdout.decode("utf-8", "replace")),
                                        main_lines)
            if age_min is not None and age_min > DIFF_STALE_MIN:
                stale[d.name] = (age_min, text)
            else:
                res[d.name] = text
    return res, stale


def claim_state(L):
    """Claim-state checks (added 2026-09-18, session 4991d2ec; same rules as owner_liveness.py):
    (slugs holding claims, slugs that also have an OPEN header) on origin/main. `_claims` is loaded
    from origin/main's `.claude/hooks/lane_claims.py`, not the (possibly stale) ARCHIVE_WORKTREE copy.
    Returns (None, open) if the guard cannot be loaded -- callers must then treat every slug as unsafe."""
    open_slugs = {m.group(1) for l in L for m in [re.match(r"^### (\S+) — OPEN\b", l)] if m}
    src = subprocess.run(["git", "-C", W, "show", "origin/main:.claude/hooks/lane_claims.py"], capture_output=True)
    if src.returncode != 0:
        return None, open_slugs
    mod = types.ModuleType("lane_claims_ro")
    try:
        exec(compile(src.stdout.decode("utf-8"), "lane_claims.py@origin/main", "exec"), mod.__dict__)
        return {s for s, _ in mod._claims("\n".join(L))}, open_slugs
    except Exception as e:
        print(f"claim_state: lane_claims load failed: {e!r}", flush=True)
        return None, open_slugs


def transcript_idle_min(sid):
    files = [f for f in PROJ.glob("*/*.jsonl") if f.stem.startswith(sid)]
    if not files:
        return None
    return (time.time() - max(f.stat().st_mtime for f in files)) / 60

while True:
    subprocess.run(["git", "-C", W, "fetch", "-q", "origin"])
    L = subprocess.run(["git", "-C", W, "show", "origin/main:.syndicate/lanes.md"], capture_output=True).stdout.decode("utf-8").split("\n")
    stamp = time.strftime("%H:%MZ", time.gmtime())
    lastmod = block_last_mod(L)
    wt_diffs, wt_stale = worktree_lanes_diffs(set(L))
    claimed, open_slugs = claim_state(L)
    present, safe, report = 0, [], []
    for s in SLUGS:
        i = next((i for i, l in enumerate(L) if l.startswith(f"### {s} ")), None)
        if i is None:
            report.append(f"{s}: GONE")
            continue
        present += 1
        if not re.match(r"—\s*CLOSED", L[i][len(f"### {s} "):]):
            report.append(f"{s}: header no longer CLOSED")
            continue
        head = "\n".join(L[i:i + 3])
        sids = sorted(set(UUID.findall(head)) | set(SHORT.findall(head)))
        idles = {sid: transcript_idle_min(sid) for sid in sids}
        wt = SESS / s
        dirty = bool(wt.exists() and subprocess.run(["git", "-C", str(wt), "status", "--porcelain"], capture_output=True).stdout.strip())
        lm = lastmod.get(i)
        colliding = [n for n, diff in wt_diffs.items() if s in diff]
        stale_hits = [f"{n}[{age / 1440:.1f}d]" for n, (age, dt) in wt_stale.items() if s in dt]
        claim_flags = (["CLAIMS-UNKNOWN"] if claimed is None else ["HOLDS-CLAIMS"] if s in claimed else []) + (["ALSO-OPEN"] if s in open_slugs else [])
        ok = bool(sids) and all(v is not None and v >= IDLE_MIN for v in idles.values()) and not dirty and lm is not None and lm[1] >= IDLE_MIN and not colliding and not claim_flags
        report.append(f"{s}: sessions " + ", ".join(f"{k}={'?' if v is None else f'{v:.0f}m'}" for k, v in idles.items()) + (f" lastmod {lm[0][:8]}={lm[1]:.0f}m" if lm else " lastmod ?") + (" DIRTY-WORKTREE" if dirty else "") + (f" UNCOMMITTED-EDIT-IN[{','.join(colliding)}]" if colliding else "") + (f" stale-diff-ignored[{','.join(stale_hits)}]" if stale_hits else "") + "".join(" " + f for f in claim_flags) + (" -> SAFE" if ok else ""))
        if ok:
            safe.append(s)
    waited = (time.time() - start) / 60
    if safe or present == 0 or waited >= MAX_WAIT_MIN:
        print(f"[{stamp}] waited {waited:.0f}m | present {present} | SAFE {safe}")
        print("\n".join("  " + r for r in report))
        sys.exit(0)
    time.sleep(POLL_SEC)
