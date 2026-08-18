"""#324 -- is it safe to deploy this service right now?

WHY THIS EXISTS, and it is a specific failure rather than a general worry.

2026-08-10 15:54:50Z I deployed refresh-worker after a hand-rolled check that
probed three tokens in the logs -- `build_soccer_artifacts`,
`SOCCER_UNIT_LAUNCHED`, `run_refresh_odds_job` -- and printed one line:

    PREFLIGHT: CLEAR TO DEPLOY

It was not clear. `generate_smartsim2_nfl_preseason_projections.py --season 2026
--week 2` (pid 427) had started at 15:53:49Z, **61 seconds earlier**, and a
sibling lane had explicitly named NFL smartsim and MLB `daily_update.py` as
kill-risk. I caught it after triggering and canceled mid-`update_in_progress`.

**The cancel did NOT save the child, and believing it did was a second error.**
Measured afterwards: cancelling a deploy that has already passed `build_ended`
and entered the update phase does not avoid a restart -- it CAUSES one.

    15:43:16  MALLOC_ARENA_INIT pid=39      <- the 87cdd3e1 boot
    15:55:10  deploy_started
    15:57:50  build_ended (succeeded)
    15:58:43  deploy_ended (canceled)       <- my cancel
    15:59:12  MALLOC_ARENA_INIT pid=38      <- a SECOND process start, 29s later

Child pids reset from ~297 to ~75 across that boundary, so the pid namespace
changed: a container restart. The NFL child died anyway; the one I saw a minute
later and called a survivor was a fresh launch. **There is no safe abort once
the update phase starts -- the only cheap moment is BEFORE triggering, which is
what this script is for.**

**The bug was not the missing token. It was the shape of the check.** A probe
list can only find hazards you already remembered, and printing a single global
verdict over a partial list makes absence-of-evidence read as coverage. So this
script does the opposite: it ENUMERATES every process the service is running and
makes you look at the list. `ALL_PROCESS_MEMORY` already carries every child with
its cmdline, pid and rss -- the data was in a payload I was already fetching.

Three rules it enforces, each from a thing that went wrong that night:

1. **Unknown is not clear.** No fresh process sample -> exit 2, never exit 0.
   A guard that maps "I could not tell" onto its permissive branch is worse than
   no guard (see todo.md, `#324` and the `unknown must not default permissive`
   note).
2. **Re-read the live commit.** My deploy was ALSO redundant: `87cdd3e1` had
   landed at 15:42:48Z already carrying my fix, and I acted on a commit I read
   43 minutes earlier. With `--target-commit` this says so before you spend a
   reboot.
3. **Sort log timestamps yourself.** The Render logs API returns the newest N
   presented OLDEST-FIRST, with or without `direction=backward` (measured; see
   `#324`). `rows[0]` is not the newest and reading it as such produced a
   four-hour error in exactly the direction that says "safe to deploy".

Read-only. Performs GETs against the Render API and never writes.

    py -3 scripts/deploy_preflight.py --service refresh-worker
    py -3 scripts/deploy_preflight.py --service refresh-worker --target-commit f1bba90c
    py -3 scripts/deploy_preflight.py --service refresh-worker --json

Exit codes:  0 = CLEAR (only infrastructure running)
             1 = HOLD (a job would be killed, or the deploy is redundant)
             2 = UNKNOWN (no fresh evidence -- treat as HOLD)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

SERVICE_IDS = {
    "syndicate": "srv-d88ahvrbc2fs73eodu30",
    "web": "srv-d88ahvrbc2fs73eodu30",
    "refresh-worker": "srv-d91dpertqb8s73co8ls0",
    "live-odds-worker": "srv-d91dpertqb8s73co8lt0",
}

OWNER_ID = "tea-d2bb5n95pdvs73cje4fg"

# A process sample older than this tells you about a world that may no longer
# exist. The worker emits ALL_PROCESS_MEMORY every few seconds, so anything
# beyond a couple of minutes means the emitter is wedged or the service is down
# -- either way, not evidence of an idle service.
DEFAULT_MAX_SAMPLE_AGE_SECONDS = 180

EXIT_CLEAR, EXIT_HOLD, EXIT_UNKNOWN = 0, 1, 2
# 3 = another session holds the deploy claim for this service. Separate from
# HOLD because the remedy is different: HOLD means "wait for a lull", CLAIMED
# means "this is not yours to deploy". Added 2026-08-15 after web took five
# deploys in 21 minutes from four sessions -- one cancelled a peer's build
# mid-flight, and a verified refresh-worker fix was silently reverted 8 minutes
# after going live by a peer cutting from a stale live SHA. Anything already
# treating non-zero as "do not deploy" keeps working unchanged.
EXIT_CLAIMED = 3


def _api_key() -> str:
    value = str(os.environ.get("RENDER_API_KEY") or "").strip()
    if value:
        return value
    env_path = REPO_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("RENDER_API_KEY"):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("RENDER_API_KEY not set in the environment or .env")


def _get(url: str, key: str):
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}", "Accept": "application/json"})
    for attempt in range(6):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            # Same reasoning as audit_blueprint_drift: a throttled read must not
            # render as "nothing running".
            if exc.code != 429 or attempt == 5:
                raise
            time.sleep(3.0 * (attempt + 1))
    raise RuntimeError("unreachable")


def newest_log(service_id: str, key: str, text: str, limit: int = 20) -> tuple[str, str] | None:
    """Newest matching log line, sorted BY US.

    The API presents the newest N oldest-first, so `rows[0]` is the oldest of
    the page. Measured 2026-08-10 with and without `direction=backward`.
    """
    query = urllib.parse.urlencode(
        {"ownerId": OWNER_ID, "resource": service_id, "limit": str(limit), "text": text}
    )
    payload = _get(f"https://api.render.com/v1/logs?{query}", key)
    rows = (payload or {}).get("logs") or []
    matching = sorted(
        (str(row.get("timestamp") or ""), str(row.get("message") or ""))
        for row in rows
        # The filter is a case-insensitive SUBSTRING match, so it over-matches
        # longer tokens (MALLOC_TRIM also hits MALLOC_TRIM_INIT). Re-check.
        if text.lower() in str(row.get("message") or "").lower()
    )
    return matching[-1] if matching else None


def parse_processes(message: str) -> dict | None:
    start = message.find("{")
    if start < 0:
        return None
    try:
        return json.loads(message[start:])
    except Exception:
        return None


# Long-lived processes that ARE the service. Note the asymmetry with the probe
# list this script exists to replace: an unrecognised process falls through to
# "job", which BLOCKS. Being wrong about a name here costs a spurious HOLD; the
# old design's equivalent mistake cost a killed job. Only the fail-safe
# direction may be a name list.
INFRASTRUCTURE_CMDLINE_MARKERS = (
    "graceful-shell-command.sh",
    "run_refresh_worker.py",
    "run_live_odds_refresh_worker.py",
    "gunicorn",          # web: master AND its forked workers are the service
    "wsgi:app",
)


def is_defunct(proc: dict) -> bool:
    """A reaped-pending (zombie) child, which a deploy cannot harm -- it is already dead.

    `#324`. Measured on refresh-worker 2026-08-10: pid 1457 sat in 108 of 342
    samples across 15 minutes and made this script return UNKNOWN forever,
    which would have made the whole check useless on the one service it was
    built for. Diagnosed from fields the payload already carries:

        name='python'   -> /proc/<pid>/status IS readable (Name:, PPid: parsed)
        rss_mb=None     -> no VmRSS: line, i.e. no memory maps
        cmdline=''      -> /proc/<pid>/cmdline is empty
        PROCESS_ENUM_DEBUG errors: only `psutil_unavailable`, no procfs failure

    Readable status + no maps + no cmdline is state Z and nothing else. The
    distinction that matters: a process we cannot read AT ALL (no name either)
    is genuinely unknown and must still block, because it might be live work.
    """
    return (
        not (proc.get("cmdline") or [])
        and proc.get("rss_mb") is None
        and bool(str(proc.get("name") or "").strip())
    )


def classify(processes: list[dict]) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    """Split into (infrastructure, job children, defunct, unidentifiable).

    Infrastructure is the container shell (ppid 0), whatever it started directly
    -- on the workers that is `graceful-shell-command.sh` and the long-lived
    `run_refresh_worker.py` -- and anything whose cmdline names a known
    long-lived server. On web the gunicorn WORKERS are forked from the master
    rather than from the shell, so a purely topological rule marks them as jobs
    and the service can never be deployed. Anything else is work in flight.
    """
    by_pid = {p.get("pid"): p for p in processes if p.get("pid") is not None}
    shell_pids = {p["pid"] for p in by_pid.values() if p.get("ppid") in (0, None)}
    # Fall back to init-parented when no explicit shell is present, so a service
    # without the wrapper still classifies rather than calling everything a job.
    infra_parents = shell_pids or {1}
    infra, jobs, defunct, unknown = [], [], [], []
    for proc in by_pid.values():
        cmdline = " ".join(proc.get("cmdline") or []).strip()
        is_server = any(marker in cmdline for marker in INFRASTRUCTURE_CMDLINE_MARKERS)
        if proc.get("pid") in infra_parents or proc.get("ppid") in infra_parents or is_server:
            infra.append(proc)
        elif cmdline:
            jobs.append(proc)
        elif is_defunct(proc):
            # Already dead, awaiting reap. Reported so it stays visible, but it
            # cannot be "killed by a deploy" and must not block one.
            defunct.append(proc)
        else:
            # Nothing readable at all -- not even a name. Could be live work, so
            # it must not be silently dropped into the clear branch.
            unknown.append(proc)
    return infra, jobs, defunct, unknown


def live_deploy(service_id: str, key: str) -> dict:
    deploys = _get(f"https://api.render.com/v1/services/{service_id}/deploys?limit=10", key) or []
    for row in deploys:
        deploy = row.get("deploy", row)
        if deploy.get("status") == "live":
            return deploy
    return {}


# The three real services. `SERVICE_IDS` also carries `syndicate` as an alias
# for `web`, which would double-count the fleet view.
FLEET = ("web", "refresh-worker", "live-odds-worker")


def fleet_live_commits(key: str) -> dict[str, dict]:
    """Every service's live commit, not just the one being deployed. (D5)

    Deploy drift has now affected FOUR audits. The services are all
    `branch=main, autoDeploy=no` and yet run off-branch commits on divergent
    lines, so "what is live" is a per-service question with three different
    answers -- and a branch cut from the wrong one has already been a ROLLBACK
    for refresh-worker rather than a deploy. A preflight that reports only the
    target service cannot show that, which is exactly how the drift kept
    reaching audits: nobody was looking at the other two.

    A per-service failure degrades to `null` for that row rather than taking
    down the gate -- this block is context, and it must never be the reason a
    safe deploy is refused or an unsafe one waved through.
    """
    out: dict[str, dict] = {}
    for name in FLEET:
        service_id = SERVICE_IDS[name]
        try:
            deploy = live_deploy(service_id, key)
            commit = str((deploy.get("commit") or {}).get("id") or "")
            out[name] = {
                "service_id": service_id,
                "live_commit": commit[:8] or None,
                "finished_at": deploy.get("finishedAt"),
            }
        except Exception as exc:  # noqa: BLE001 - context, never a gate
            out[name] = {"service_id": service_id, "live_commit": None,
                         "finished_at": None, "error": f"{type(exc).__name__}: {exc}"}
    return out


def is_ancestor(candidate: str, descendant: str) -> bool | None:
    """True when `candidate` is already contained in `descendant`. None if git cannot say."""
    try:
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", candidate, descendant],
            cwd=REPO_ROOT, capture_output=True, timeout=30,
        )
        return result.returncode == 0
    except Exception:
        return None


RECEIPT_DIR = REPO_ROOT / ".syndicate" / "deploy" / "preflight"


def _write_receipt(args, report, verdict, reason, live_commit) -> None:
    """Persist this verdict so `deploy-guard.py` can gate on it.

    WHY A FILE. The guard runs in a different process, seconds-to-minutes later,
    and cannot see this run's exit code. Before 2026-08-18 it gated on whether
    your session id was the coordinator's; it now gates on whether a preflight
    actually returned CLEAR recently, which is a property of the WORLD rather
    than of who is asking.

    WHY EVERY VERDICT AND NOT ONLY `CLEAR`. Writing only on CLEAR would leave a
    stale CLEAR in place when a later run returns HOLD -- preflight, get CLEAR,
    a sim starts, preflight again and get HOLD, and the guard would still be
    reading the first receipt and let the deploy through. Overwriting on every
    verdict makes the newest reading the one that counts, so a HOLD actively
    REVOKES the CLEAR before it. An unknown must never leave the permissive
    branch standing.

    Never raises: a preflight that cannot write its receipt must still print its
    verdict and return its exit code. The guard treats an absent receipt as
    "not preflighted", which is the safe reading.
    """
    try:
        RECEIPT_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "service": args.service,
            "verdict": verdict,
            "reason": reason,
            "holder": args.holder or None,
            "target_commit": args.target_commit or None,
            "live_commit": live_commit or None,
            "written_at": time.time(),
            "written_at_iso": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "jobs_in_flight": len(report.get("jobs_in_flight") or []),
        }
        (RECEIPT_DIR / f"{args.service}.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    except Exception:
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--service", required=True, choices=sorted(SERVICE_IDS))
    parser.add_argument("--target-commit", default="", help="commit you intend to deploy; warns if already live")
    parser.add_argument("--max-sample-age-seconds", type=int, default=DEFAULT_MAX_SAMPLE_AGE_SECONDS)
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--holder",
        default=os.environ.get("SYNDICATE_DEPLOY_HOLDER", ""),
        help="your lane/session name. If another holder owns this service's deploy claim, "
             "preflight returns CLAIMED (exit 3) instead of CLEAR.",
    )
    args = parser.parse_args()

    key = _api_key()
    service_id = SERVICE_IDS[args.service]
    now = datetime.now(timezone.utc)
    report: dict = {"service": args.service, "service_id": service_id, "checked_at": now.isoformat()}

    deploy = live_deploy(service_id, key)
    live_commit = str((deploy.get("commit") or {}).get("id") or "")
    report["live_commit"] = live_commit[:8]
    report["live_finished_at"] = deploy.get("finishedAt")

    report["fleet"] = fleet_live_commits(key)

    redundant = False
    if args.target_commit and live_commit:
        contained = is_ancestor(args.target_commit, live_commit)
        report["target_commit"] = args.target_commit[:8]
        report["target_already_live"] = contained
        redundant = contained is True

    sample = newest_log(service_id, key, "ALL_PROCESS_MEMORY")
    parsed = parse_processes(sample[1]) if sample else None
    if sample and parsed:
        age = (now - datetime.fromisoformat(sample[0].replace("Z", "+00:00"))).total_seconds()
    else:
        age = None
    report["sample_at"] = sample[0] if sample else None
    report["sample_age_seconds"] = round(age, 1) if age is not None else None

    infra: list[dict] = []
    jobs: list[dict] = []
    defunct: list[dict] = []
    unidentifiable: list[dict] = []
    if parsed:
        infra, jobs, defunct, unidentifiable = classify(parsed.get("processes") or [])
    report["process_count"] = (parsed or {}).get("process_count")
    fmt = lambda p: {
        "pid": p.get("pid"), "ppid": p.get("ppid"), "rss_mb": p.get("rss_mb"),
        "cmdline": " ".join(p.get("cmdline") or []),
    }
    report["infrastructure"] = [fmt(p) for p in infra]
    report["jobs_in_flight"] = [fmt(p) for p in jobs]
    report["defunct"] = [fmt(p) for p in defunct]
    report["unidentifiable"] = [fmt(p) for p in unidentifiable]

    # The deploy claim is consulted BEFORE the process checks, because it answers
    # a different question: not "is it safe to deploy now" but "is this yours to
    # deploy at all". A CLEAR lull is worth nothing if a peer is mid-train on the
    # same service -- that is precisely how one build cancelled another.
    claim = None
    try:
        from deploy_claim import active_claim  # noqa: PLC0415 -- optional, must never break preflight

        claim = active_claim(args.service)
    except Exception:  # a missing or broken claim tool must not block a deploy
        claim = None
    foreign_claim = claim if (claim and claim.get("holder") != (args.holder or None)) else None
    report["deploy_claim"] = (
        {"holder": claim.get("holder"), "target_commit": claim.get("target_commit"),
         "acquired_at_iso": claim.get("acquired_at_iso"), "yours": foreign_claim is None}
        if claim else None
    )

    stale = age is None or age > args.max_sample_age_seconds
    if foreign_claim:
        verdict, code = "CLAIMED", EXIT_CLAIMED
        reason = (
            f"deploy claim on {args.service} is held by {foreign_claim.get('holder')}"
            + (f" for {str(foreign_claim.get('target_commit'))[:8]}" if foreign_claim.get("target_commit") else "")
            + ". Coordinate with them, or --force the claim if that session is gone."
        )
    elif stale:
        verdict, code = "UNKNOWN", EXIT_UNKNOWN
        reason = "no ALL_PROCESS_MEMORY sample" if age is None else f"sample is {age:.0f}s old (limit {args.max_sample_age_seconds}s)"
    elif jobs:
        verdict, code = "HOLD", EXIT_HOLD
        reason = f"{len(jobs)} job(s) in flight; a deploy kills them"
    elif unidentifiable:
        verdict, code = "UNKNOWN", EXIT_UNKNOWN
        reason = f"{len(unidentifiable)} child process(es) with no readable cmdline"
    elif redundant:
        verdict, code = "HOLD", EXIT_HOLD
        reason = f"{args.target_commit[:8]} is already contained in live {live_commit[:8]} -- the deploy is redundant"
    else:
        verdict, code = "CLEAR", EXIT_CLEAR
        reason = "only infrastructure processes running" + (
            f" ({len(defunct)} defunct child(ren) awaiting reap -- already dead, cannot be killed by a deploy)" if defunct else ""
        )
    report["verdict"] = verdict
    report["reason"] = reason
    _write_receipt(args, report, verdict, reason, live_commit)

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return code

    print(f"service        {args.service}  ({service_id})")
    print(f"live commit    {live_commit[:8] or '?'}   finished {deploy.get('finishedAt') or '?'}")
    if claim:
        who = "YOU" if foreign_claim is None else claim.get("holder")
        print(f"deploy claim   held by {who}"
              + (f"   target {str(claim.get('target_commit'))[:8]}" if claim.get("target_commit") else "")
              + (f"   since {claim.get('acquired_at_iso')}" if claim.get("acquired_at_iso") else ""))
    else:
        print("deploy claim   none -- acquire one before deploying "
              "(scripts/deploy_claim.py acquire --service "
              f"{args.service} --holder <you>)")
    if args.target_commit:
        state = {True: "ALREADY LIVE -- redundant", False: "not yet live", None: "git could not say"}[report.get("target_already_live")]
        print(f"target commit  {args.target_commit[:8]}   {state}")
    print(f"sample         {report['sample_at'] or 'NONE'}"
          + (f"   age {age:.0f}s" if age is not None else ""))

    # D5. Printed on EVERY run, including CLEAR, for the same reason the process
    # enumeration is: the number you need is the one for the service you are NOT
    # deploying. `<-- deploying` marks the target so the other two read as
    # context rather than as instructions.
    print("\ndeployed commit per service:")
    for name in FLEET:
        row = report["fleet"].get(name) or {}
        marker = "  <-- deploying" if SERVICE_IDS.get(args.service) == row.get("service_id") else ""
        if row.get("error"):
            print(f"  {name:18s} UNREADABLE ({row['error']}){marker}")
        else:
            print(f"  {name:18s} {row.get('live_commit') or '?':8s}  "
                  f"finished {row.get('finished_at') or '?'}{marker}")
    # The enumeration is the point. Print it ALWAYS, including on CLEAR --
    # a verdict with no list is what made the original check misleading.
    print(f"\nprocesses ({report['process_count']} reported):")
    for label, group in (("infra", infra), ("JOB", jobs), ("defunct", defunct), ("UNKNOWN", unidentifiable)):
        for proc in group:
            cmd = " ".join(proc.get("cmdline") or []) or "<no cmdline>"
            print(f"  [{label:7s}] pid {str(proc.get('pid')):>6s}  ppid {str(proc.get('ppid')):>6s}  "
                  f"rss {str(proc.get('rss_mb')):>8s}  {cmd[:96]}")
    if not (infra or jobs or defunct or unidentifiable):
        print("  <none enumerated>")
    print(f"\n{verdict}: {reason}")
    return code


if __name__ == "__main__":
    sys.exit(main())
