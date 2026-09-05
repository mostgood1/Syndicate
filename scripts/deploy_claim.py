"""One deployer per service, enforced by a file instead of by asking nicely.

WHY THIS EXISTS -- measured on 2026-08-15, both failure modes in one evening:

  CANCEL.  web took five deploys in twenty-one minutes from four sessions. The
  19:20 deploy cancelled the 19:15 one MID-BUILD; Render cancels an in-flight
  deploy when a new one starts, and the owner of the cancelled build was never
  told. Its fix stayed unshipped for 90 minutes while everyone believed it was
  live.

  SILENT REVERT.  The prop `0.5` fix went live on refresh-worker at 21:36:59Z,
  content-verified. By 21:45:20Z the service was a commit that did NOT contain
  it, and the fix was gone from production. A peer had cut its deploy branch
  from an earlier live SHA. Two "successful" deploys; one silently undone;
  nothing anywhere warned.

Coordination by MESSAGE cannot fix either: a cross-session message waits for the
target's current turn to end, while firing a deploy takes seconds. Every hold
sent that evening arrived after the deploy it was meant to stop. And three
sessions ARCHIVED mid-coordination, so "everyone agreed" has a shelf life of
minutes.

So the claim is a FILE in the shared worktree -- visible to every session
instantly, surviving the session that wrote it, and checked by the one gate the
protocol already says every deploy must pass: `/preflight`.

DESIGN NOTES, each paid for:

  * TTL, not a lock.  Sessions archive constantly and a dead holder must not
    wedge a service forever. A claim expires (default 45 min) and preflight
    reports it as EXPIRED rather than honouring it.

  * Atomic acquire via O_CREAT|O_EXCL.  Two sessions racing get one winner and
    one clean refusal, not two holders.

  * A token, so release is not a free-for-all.  `--force` exists for the dead
    holder, and it names who broke the claim in the file it replaces.

  * NOT committed.  `.syndicate/deploy_claims/` is gitignored: it is runtime
    state about right now, not history. A claim in git would be a claim that
    outlives its truth.

Usage:
    py -3 scripts/deploy_claim.py acquire --service web --holder my-lane
    py -3 scripts/deploy_claim.py status  [--service web]
    py -3 scripts/deploy_claim.py release --service web --token <tok>
    py -3 scripts/deploy_claim.py release --service web --force --holder me

Exit codes: 0 = success / claim is yours or free, 1 = held by someone else.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _main_worktree_root() -> Path:
    """The tree the DEPLOY GUARD reads -- not necessarily the one this file is in.

    THE FAILURE THIS REMOVES, measured 2026-09-03. Sessions each work in their
    own git worktree (`session_worktree.py`), so a copy of this script inside a
    worktree resolved `REPO_ROOT` to that worktree and wrote the claim there.
    `deploy-guard.py` reads `CLAUDE_PROJECT_DIR or cwd`, which is the PRIMARY
    tree, so it never saw those claims: it reported `claim NOT HELD by anyone`
    seconds after a successful `acquire`, three times in one session.

    A guard that cannot see a claim is the smaller half. The larger half is that
    two sessions in two worktrees could each `acquire` the same service and both
    succeed, because they were writing to different files -- the lock would be
    silently non-mutual at exactly the moment it is load-bearing. That is
    `#635`'s bug along a new axis: there it was two NAMES for one box, here it is
    two TREES for one repo, and in both cases every claim involved was "valid".

    `--git-common-dir` is the same for every worktree of a repo and points at the
    primary tree's `.git`, so its parent is the tree the guard reads. Falls back
    to `REPO_ROOT` when git cannot answer -- a claim in the wrong place still
    beats a crash in the tool that serialises deploys.
    """
    import subprocess

    for args in (
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],  # git >= 2.31
        ["git", "rev-parse", "--git-common-dir"],
    ):
        try:
            done = subprocess.run(
                args, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=15
            )
        except Exception:
            continue
        if done.returncode != 0:
            continue
        raw = (done.stdout or "").strip()
        if not raw:
            continue
        common = Path(raw)
        if not common.is_absolute():
            common = (REPO_ROOT / common).resolve()
        # `.git` -> its parent is the main worktree. A bare repo or anything
        # unexpected falls through to REPO_ROOT rather than guessing.
        if common.name == ".git" and common.parent.is_dir():
            return common.parent
    return REPO_ROOT


#: Tests monkeypatch this attribute, so it stays a module-level constant.
CLAIM_DIR = _main_worktree_root() / ".syndicate" / "deploy_claims"
SERVICES = ("web", "syndicate", "refresh-worker", "live-odds-worker")
DEFAULT_TTL_SECONDS = 45 * 60

# `#635`. ONE LOCK PER SERVICE, NOT PER NAME.
#
# `web` and `syndicate` are two names for `srv-d88ahvrbc2fs73eodu30`, and this
# file used to key the claim on whichever string you typed -- so `web.json` and
# `syndicate.json` were independent locks on one box. MEASURED 2026-09-02: one
# lane held `web` with a build in flight, another was GRANTED `syndicate`,
# deployed, and Render cancelled the first build 0.6s later. Both claims were
# valid. No --force, no guard override; the claim step was run by both.
#
# The alias was already known elsewhere and only here was it missed:
# `deploy_preflight.py` maps both names to the same service id, and
# `deploy-guard.py` maps that id to `web`. Three components, three answers.
#
# The canonical name is the one the guard uses, so a claim written here is the
# claim the guard reads. LEGACY_ALIASES is read on lookup so a `syndicate.json`
# written by an older copy of this script still blocks -- absent that, upgrading
# would silently free a held lock, which is the failure this fix exists to stop.
CANONICAL = {
    "web": "web",
    "syndicate": "web",
    "refresh-worker": "refresh-worker",
    "live-odds-worker": "live-odds-worker",
}
LEGACY_ALIASES = {"web": ("web", "syndicate")}
#: `status` iterates this, so one box prints one line. The old listing showed
#: `web HELD` and `syndicate free` on consecutive lines for the same service,
#: which is how the 2026-09-02 collision was read as "a different service".
CANONICAL_SERVICES = ("web", "refresh-worker", "live-odds-worker")


def canonical(service: str) -> str:
    """The service a name refers to. Unknown names map to themselves rather than
    raising: a new service must not silently share another's lock."""
    return CANONICAL.get(str(service or "").strip(), str(service or "").strip())


def _path(service: str) -> Path:
    return CLAIM_DIR / f"{canonical(service)}.json"


def _existing_paths(service: str) -> list[Path]:
    """Every file that could hold a live claim on this service, canonical first."""
    name = canonical(service)
    return [CLAIM_DIR / f"{alias}.json" for alias in LEGACY_ALIASES.get(name, (name,))]


def _read(service: str) -> dict | None:
    # `#635`: canonical file first, then any legacy alias. A claim written by an
    # older copy of this script under `syndicate.json` must still be seen, or
    # this fix would itself free a lock somebody is holding.
    for p in _existing_paths(service):
        if p.exists():
            break
    else:
        p = _path(service)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (ValueError, OSError):
        # A corrupt claim must not block deploys forever, but it also must not
        # silently read as "free" -- surface it as its own state.
        return {"holder": "<unreadable>", "corrupt": True, "acquired_at": 0, "ttl_seconds": 0}


def age_and_expiry(claim: dict) -> tuple[float, bool]:
    age = time.time() - float(claim.get("acquired_at") or 0)
    ttl = float(claim.get("ttl_seconds") or DEFAULT_TTL_SECONDS)
    return age, age > ttl


def active_claim(service: str) -> dict | None:
    """The claim that should block a deploy, or None. Expired claims do not block."""
    claim = _read(service)
    if not claim:
        return None
    _, expired = age_and_expiry(claim)
    return None if expired else claim


def cmd_acquire(args: argparse.Namespace) -> int:
    CLAIM_DIR.mkdir(parents=True, exist_ok=True)
    existing = _read(args.service)
    if existing:
        age, expired = age_and_expiry(existing)
        if not expired and not args.force:
            print(
                f"HELD by {existing.get('holder')} for {age/60:.1f} min "
                f"(target {str(existing.get('target_commit'))[:8] or '?'}). "
                f"Not acquiring. "
                f"holder session: {existing.get('holder_session') or 'unrecorded'} "
                # NOT checkable. This used to say "check it with list_sessions
                # (isRunning)" and that is FALSE: the id recorded here is a bare
                # `CLAUDE_CODE_SESSION_ID`, while `list_sessions` returns
                # `local_<uuid>` from a different space, so the lookup reads
                # "absent" for a LIVE holder as readily as a dead one. This is
                # the THIRD site that said it and by far the worst, because it
                # is printed at the exact moment a reader is deciding whether to
                # `--force`. See the long note at `holder_session`.
                f"-- a BREADCRUMB ONLY: it is NOT checkable against "
                f"list_sessions (different id space), so do not read its "
                f"absence as 'gone'. To tell whether the holder is alive, run "
                f"deploy_preflight.py and look for a RUNNING CHILD under this "
                f"service -- that is evidence; a roster lookup is not. "
                f"THIS CLAIM RECORDS NO PID: the one it used to record was the "
                f"acquire CLI's own and always read dead. An unrecorded session "
                f"is UNKNOWN, not gone. TTL is the real bound -- this expires on "
                f"its own in "
                f"{max(0, int((existing.get('ttl_seconds') or 0) - age))//60} min. "
                f"If that session is genuinely gone, re-run with --force "
                f"-- it will record that you broke their claim."
            )
            return 1
        why = "expired" if expired else "forced"
        print(f"replacing {why} claim held by {existing.get('holder')} ({age/60:.1f} min old)")

    token = secrets.token_hex(8)
    payload = {
        "service": args.service,
        "holder": args.holder,
        "token": token,
        "target_commit": args.target_commit,
        "reason": args.reason,
        "acquired_at": time.time(),
        "acquired_at_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "ttl_seconds": args.ttl,
        # THE HOLDER IS A SESSION, NOT A PROCESS -- this field used to say
        # otherwise. It recorded `os.getpid()`: the pid of THIS `deploy_claim.py
        # acquire` CLI invocation, which exits ~1s after writing the claim. So
        # EVERY claim read as "held by a dead process" within seconds of being
        # taken. Measured 2026-09-01: a live claim with 15 min of TTL left was
        # force-broken by a session whose liveness check was CORRECT --
        # `Get-Process 22884` really did report dead. The FIELD lied, not the
        # checker, and it turned `--force` from an escape hatch into the default.
        #
        # `holder_session` outlives the CLI process. **IT CANNOT BE CHECKED
        # AGAINST `list_sessions`, AND THIS COMMENT USED TO SAY IT COULD.**
        # That sentence was acted on and was wrong: this field records
        # `CLAUDE_CODE_SESSION_ID`, a BARE uuid, while `list_sessions` returns
        # ids of the form `local_<uuid>` from a DIFFERENT id space. They are
        # not the same identifier and not a prefix of one another.
        #
        # Demonstrated 2026-09-04, not argued: the `web` claim recorded
        # `b2b5b45b-...` while the roster knew that same, demonstrably ALIVE
        # session (it replied to a message) as `local_05200b16-...`. One
        # session, two ids. So NO claim's `holder_session` can ever appear in
        # that roster, and "absent from the roster" reads exactly the same for
        # a live holder as for a dead one -- it is INERT, not merely weak.
        #
        # THE SELF-TEST, so nobody has to take this on faith: run the check
        # against YOUR OWN live claim. Your `$CLAUDE_CODE_SESSION_ID` has no
        # `local_` prefix and your own session is not findable in the roster by
        # it either. One call, no history needed, and it fails for a session
        # that is provably alive -- because it is the one running the test.
        #
        # WHAT IS ACTUALLY EVIDENCE: `deploy_preflight.py`'s process output. A
        # running child under the claim PROVES the holder is alive. A roster
        # lookup proves nothing in either direction.
        #
        # AND THE TRAP THAT OUTLIVES THIS ONE: **a free claim is not an idle
        # box.** The TTL expiring frees the LOCK, not the WORK -- a job the
        # holder started keeps running, and a deploy restarts the service and
        # kills it. Measured 2026-09-04: at TTL expiry an eredivisie
        # `build_soccer_artifacts` and an MLB `run_mlb_daily_sim_job` were both
        # still in flight. Gate on the PROCESS LIST, not just the claim.
        #
        # Never cite a roster read as grounds to `--force`. None when the env
        # var is absent, and None must NOT be read as "gone": absent identity
        # is UNKNOWN, and unknown is not permission to force.
        #
        # NO `pid` IS WRITTEN ANY MORE. `deploy_preflight.py` never read it, so
        # its only consumer was a human deciding whether to break a lock, and it
        # could not be used correctly. THE TTL IS THE LIVENESS INVARIANT and
        # always was -- it is what actually held here.
        "holder_session": os.environ.get("CLAUDE_CODE_SESSION_ID") or None,
    }
    if existing:
        payload["replaced"] = {
            "holder": existing.get("holder"),
            "acquired_at_iso": existing.get("acquired_at_iso"),
        }

    # Write straight into the O_EXCL handle. There is NO temp-file rename here,
    # deliberately: the first version wrote a temp then `Path.replace`d it, and
    # on 2026-08-15 that raised
    #   PermissionError: [WinError 5] Access is denied: refresh-worker.tmp -> .json
    # because this repo lives under OneDrive, which locks files mid-sync. It left
    # a ZERO-BYTE claim plus an orphaned .tmp holding the real payload -- i.e. the
    # claim tool failed at the exact moment it was being relied on. O_CREAT|O_EXCL
    # already gives the property the rename was there for (one winner among racing
    # acquires), so the rename was never buying anything.
    blob = json.dumps(payload, indent=2)
    path = _path(args.service)
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        if not (existing and (args.force or age_and_expiry(existing)[1])):
            print("HELD -- lost the race to another session. Not acquiring.")
            return 1
        # Ours to take (forced or expired): truncate in place, still no rename.
        fd = os.open(str(path), os.O_WRONLY | os.O_TRUNC)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(blob)
    except OSError as exc:
        # Never leave a zero-byte file behind pretending to be a claim: an
        # unreadable claim reads as EXPIRED, which does not block, which is the
        # safe direction -- but say so loudly rather than reporting success.
        path.unlink(missing_ok=True)
        print(f"ACQUIRE FAILED writing the claim ({exc}). Nothing is held.")
        return 1
    # Sweep any .tmp left by the pre-2026-08-15 implementation.
    path.with_suffix(".tmp").unlink(missing_ok=True)
    print(f"ACQUIRED {args.service} by {args.holder}")
    print(f"token {token}   ttl {args.ttl}s")
    return 0


def cmd_release(args: argparse.Namespace) -> int:
    claim = _read(args.service)
    if not claim:
        print(f"{args.service}: no claim to release")
        return 0
    if not args.force and args.token != claim.get("token"):
        print(
            f"REFUSED: {args.service} is held by {claim.get('holder')} and the token does "
            f"not match. Use --force if that session is gone."
        )
        return 1
    _path(args.service).unlink(missing_ok=True)
    print(f"released {args.service} (was {claim.get('holder')})")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    # `#635`: one line per BOX. Listing `web` and `syndicate` as separate rows
    # is what made a collision read as "a different service is busy" on
    # 2026-09-02 -- the status output was the proximate cause, not just the
    # split file. An explicit --service is canonicalised for the same reason.
    services = [canonical(args.service)] if args.service else list(CANONICAL_SERVICES)
    held = 0
    for svc in services:
        claim = _read(svc)
        if not claim:
            print(f"  {svc:<17} free")
            continue
        age, expired = age_and_expiry(claim)
        state = "EXPIRED (does not block)" if expired else "HELD"
        if not expired:
            held += 1
        print(
            f"  {svc:<17} {state} by {claim.get('holder')} "
            f"{age/60:.1f} min  target={str(claim.get('target_commit') or '')[:8]}"
        )
        if claim.get("holder_session"):
            # NOT a liveness hint. This id is in a different space from the
            # one `list_sessions` returns (bare uuid vs `local_<uuid>`), so it
            # can never be found there -- see the long note at `holder_session`.
            # The line used to read "(liveness: list_sessions, NOT pid)" and
            # that sent a reader to a test that cannot return "present".
            print(f"  {'':<17} session: {claim['holder_session']}"
                  f"  (breadcrumb only -- NOT checkable against list_sessions;"
                  f" the TTL is the liveness bound)")
        if claim.get("reason"):
            print(f"  {'':<17} reason: {claim['reason']}")
    return 1 if held else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("acquire")
    a.add_argument("--service", required=True, choices=SERVICES)
    a.add_argument("--holder", required=True, help="lane or session name -- who to blame/ask")
    a.add_argument("--target-commit", default=None)
    a.add_argument("--reason", default=None)
    a.add_argument("--ttl", type=int, default=DEFAULT_TTL_SECONDS)
    a.add_argument("--force", action="store_true", help="break a live claim; records that you did")
    a.set_defaults(func=cmd_acquire)

    r = sub.add_parser("release")
    r.add_argument("--service", required=True, choices=SERVICES)
    r.add_argument("--token", default=None)
    r.add_argument("--force", action="store_true")
    r.set_defaults(func=cmd_release)

    s = sub.add_parser("status")
    s.add_argument("--service", default=None, choices=SERVICES)
    s.set_defaults(func=cmd_status)

    args = ap.parse_args(argv)

    # Say it out loud when the claim is not where this script lives. Silent
    # redirection would fix the lock and leave the next reader hunting for a
    # file that is not in the tree they are standing in.
    try:
        CLAIM_DIR.relative_to(REPO_ROOT)
    except ValueError:
        print(
            f"[deploy_claim] worktree detected -- claims live in the MAIN tree, "
            f"which is what deploy-guard.py reads: {CLAIM_DIR}",
            file=sys.stderr,
            flush=True,
        )

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
