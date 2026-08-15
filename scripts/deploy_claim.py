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
CLAIM_DIR = REPO_ROOT / ".syndicate" / "deploy_claims"
SERVICES = ("web", "syndicate", "refresh-worker", "live-odds-worker")
DEFAULT_TTL_SECONDS = 45 * 60


def _path(service: str) -> Path:
    return CLAIM_DIR / f"{service}.json"


def _read(service: str) -> dict | None:
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
                f"Not acquiring.\nIf that session is gone, re-run with --force "
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
        "pid": os.getpid(),
    }
    if existing:
        payload["replaced"] = {
            "holder": existing.get("holder"),
            "acquired_at_iso": existing.get("acquired_at_iso"),
        }

    tmp = _path(args.service).with_suffix(".tmp")
    try:
        # O_EXCL on the real path is what makes two racing acquires produce one
        # winner. Write to a temp first so a crash cannot leave a half-file.
        fd = os.open(str(_path(args.service)), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
    except FileExistsError:
        if not (existing and (args.force or age_and_expiry(existing)[1])):
            print("HELD -- lost the race to another session. Not acquiring.")
            return 1
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(_path(args.service))
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
    services = [args.service] if args.service else list(SERVICES)
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
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
