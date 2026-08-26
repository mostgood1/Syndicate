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
             3 = CLAIMED (another holder owns this service's deploy claim)
             4 = OFF_MAIN (the target SHA is not contained in origin/main)
             5 = TOO_SOON (deployed again inside this service's minimum spacing)

THE THREE PROPERTIES, because they are independent and each was learned
separately -- a deploy needs all three and no two of them imply the third:

    CLAIMED    serialisation   two deploys must not overlap
    OFF_MAIN   composition     the second must contain the first
    TOO_SOON   spacing         the service must have time to produce something

`#562`: fifteen refresh-worker deploys in 6h15m were perfectly serialised and
perfectly composed, and left the board frozen all evening anyway, because the
median instance was SIGTERMed 1202 s into a 21-minute boot-to-first-publish
cycle. Serialisation is not spacing.
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
# 4 = the target commit is not contained in `origin/main`. Separate from HOLD
# because the remedy is different again: HOLD means "wait", CLAIMED means "not
# yours", OFF_MAIN means "this SHA cannot compose with anyone else's".
#
# WHY, and it is a specific incident. Services have historically run deploy
# branches cut from the LIVE SHA rather than from main -- 170 `origin/deploy/*`
# branches exist and the sampled tips are all off main. Two such deploys do not
# contain each other, so the second silently reverts the first. Measured
# 2026-08-15: a verified refresh-worker fix went live at 21:36:59Z and was gone
# by 21:45:20Z because a peer cut from an earlier live SHA. Both deploys
# "succeeded"; the deploy claim correctly serialised them; nothing warned.
#
# SERIALISATION IS NOT COMPOSITION. The claim orders deploys and cannot make
# them cumulative. Requiring the target to be an ancestor of `origin/main` makes
# every later main commit contain every earlier one, by construction, which is
# the property the claim cannot provide.
EXIT_OFF_MAIN = 4
# 5 = this service was deployed too recently. Separate from HOLD again, and the
# distinction is the whole reason this exists: HOLD means "something is running
# right now, wait for a lull", TOO_SOON means "nothing is running BECAUSE you
# just restarted it, and it has not had time to produce anything yet".
#
# WHY, measured 2026-08-25/26 (`#562`, and `deploys.md` carries the working).
# A user reported the Layer 2 board and the compact scoreboard frozen for ~20
# minutes. Every reader was healthy; the PRODUCER was being restarted faster
# than it could produce:
#
#     15 deploys 19:26:55Z -> 01:13:38Z, all trigger=api
#     15 WORKER_SHUTDOWN, all SIGTERM
#     median instance uptime  1202 s = 20.0 min   (5 of 15 under 8 minutes)
#     boot-to-first-publish   20 min 41 s         (instance -fzb6v)
#
# The median instance died within a minute of its first publish and five
# published nothing at all. Every chips-publish gap contained at least one
# deploy; the 54-minute gap contained five.
#
# THE CLAIM CANNOT PREVENT THIS AND WAS NEVER MEANT TO. `deploy_claim.py`
# SERIALISES deploys -- it stops two landing at once, and its own docstring is
# careful that serialisation is not composition (which is what `OFF_MAIN`
# added). This is the third property, and it is not implied by either:
# serialisation is not SPACING. Fifteen deploys can be perfectly ordered,
# perfectly composed, each correctly claimed and released, and still leave the
# board frozen all evening -- which is exactly what happened.
EXIT_TOO_SOON = 5

# THE MINIMUM SPACING, PER SERVICE, IN SECONDS. 0 disables the check.
#
# ONLY refresh-worker's NUMBER IS MEASURED, and the other two are 0 for that
# reason rather than because they are known to be safe. Stating an unmeasured
# number here would be inventing the exact kind of threshold this repo keeps
# paying for; the verdict line prints "not rate-limited" for a 0 so the absence
# is VISIBLE rather than implied.
#
#   refresh-worker  1500 s (25 min). Boot-to-first-publish measured at 20 min
#                   41 s, so anything under ~21 minutes guarantees a board that
#                   never publishes. 25 gives the cycle its measured length plus
#                   margin for a slower slate.
#   live-odds-worker  UNMEASURED. It has no `WORKER_SHUTDOWN` handler, so the
#                   uptime figure that made refresh-worker's case does not exist
#                   for it. Measure its boot-to-first-publish before setting one.
#   web             DELIBERATELY 0, and this is a judgement not a gap. A web
#                   deploy loses no cycle -- web only reads artifacts. Its cost
#                   is ~2 minutes of 502s, which is a different problem, and one
#                   the deploy claim already serialises.
#
# Override per service with SYNDICATE_DEPLOY_MIN_INTERVAL_SECONDS_<SERVICE>
# (dashes as underscores, upper case), or all of them with
# SYNDICATE_DEPLOY_MIN_INTERVAL_SECONDS.
DEFAULT_MIN_DEPLOY_INTERVAL_SECONDS = {
    "refresh-worker": 1500,
    "live-odds-worker": 0,
    "web": 0,
    "syndicate": 0,
}

# Deploy statuses that DID NOT restart the service, so they do not start the
# clock. Everything else does, INCLUDING anything unrecognised -- rule 1 of this
# file is that unknown must not land on the permissive branch, and a status we
# cannot classify is exactly that.
#
# `canceled` IS COUNTED, and that is not conservatism for its own sake: this
# file's own header records that cancelling a deploy which has passed
# `build_ended` does not avoid a restart, it CAUSES one (a second
# MALLOC_ARENA_INIT 29 s after the cancel, with the child pid namespace reset).
# A cancel during the BUILD phase is harmless and will be over-counted here.
# Over-counting costs a wait; under-counting costs the board.
NON_RESTARTING_DEPLOY_STATUSES = frozenset({
    "build_failed",
    "pre_deploy_failed",
    "build_in_progress",
    "pre_deploy_in_progress",
    "created",
    "queued",
})


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


# Services whose process list is read from their OWN /api/ops/memory endpoint
# instead of from an ALL_PROCESS_MEMORY log line. See `web_processes` below.
API_SAMPLED_SERVICES = {"web", "syndicate"}
WEB_BASE_URL = os.environ.get("SYNDICATE_DIAG_BASE_URL", "https://syndicate-an21.onrender.com")


def _admin_token() -> str | None:
    value = str(os.environ.get("ADMIN_TOKEN") or "").strip()
    if value:
        return value
    env_path = REPO_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("ADMIN_TOKEN"):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def web_processes() -> tuple[list[dict], str] | None:
    """Web's live process list, read from the service itself. `#465`.

    WHY WEB CANNOT USE THE LOG PATH. `deploy_preflight` was built around
    `ALL_PROCESS_MEMORY`, a stderr line the WORKERS emit every few seconds.
    **Web has not emitted one since 2026-08-14**, so its sample is permanently
    stale and the verdict is permanently UNKNOWN -- which the guard treats as
    HOLD, so every web deploy needed a break-glass grant. A guard that must be
    broken on every use has stopped being a guard.

    THE CAUSE OF THE SILENCE IS STILL UNKNOWN, and this does not pretend to fix
    it. FOUR causes have been claimed for it and all four were wrong (broken
    sampler / missing psutil / deleted emitter / no caller on web -- see
    `state.md [web-preflight-dead-sample]`). **This fix deliberately does not
    depend on the answer**: whatever stopped the log line, the endpoint reads
    the same processes from the same container, live, on request.

    IT IS ALSO WHAT EVERY BREAK-GLASS ALREADY DID BY HAND. The 2026-08-18 and
    2026-08-19 web grants both substituted exactly this reading -- process list
    from `/api/ops/memory`, each entry identified by cmdline -- and recorded it
    in `deploys.md` as the evidence the deploy was safe. This promotes that
    manual step to the normal path.

    The records carry `pid`, `ppid` and `cmdline`, which is precisely what
    `classify()` consumes, so no translation is involved and no field is
    invented. Returns (processes, iso8601_now) or None if unreachable.
    """
    token = _admin_token()
    if not token:
        return None
    request = urllib.request.Request(
        f"{WEB_BASE_URL}/api/ops/memory",
        headers={"X-Admin-Token": token, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return None
    processes = ((payload or {}).get("memory") or {}).get("processes")
    if not isinstance(processes, list) or not processes:
        # An empty list is NOT evidence of an idle service -- it is a failed
        # read. Returning it would turn "I cannot see" into "nothing running",
        # which is the exact inversion this whole script exists to prevent.
        return None
    return processes, datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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


def _age_seconds(stamp: str, now: datetime) -> float | None:
    """Seconds between an RFC3339 stamp and `now`, or None if unreadable.

    DELIBERATELY NOT CLAMPED AT ZERO. A negative age means the clocks disagree,
    and the sample-age call site already treats that as "a receipt nobody should
    trust the rest of" -- clamping would hide it. For the deploy-spacing caller a
    negative reads as "very recent", which refuses, which is the safe direction.
    """
    text = str(stamp or "").strip()
    if not text:
        return None
    try:
        return (now - datetime.fromisoformat(text.replace("Z", "+00:00"))).total_seconds()
    except (TypeError, ValueError):
        return None


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


def min_deploy_interval_seconds(service: str) -> int:
    """The spacing this service requires, honouring both env overrides.

    Per-service override wins over the global one, which wins over the table.
    A value that will not parse falls back rather than raising: a preflight that
    dies on a malformed env var teaches people to skip the preflight.
    """
    keys = (
        "SYNDICATE_DEPLOY_MIN_INTERVAL_SECONDS_" + str(service or "").replace("-", "_").upper(),
        "SYNDICATE_DEPLOY_MIN_INTERVAL_SECONDS",
    )
    for name in keys:
        raw = str(os.environ.get(name) or "").strip()
        if raw:
            try:
                return max(0, int(float(raw)))
            except (TypeError, ValueError):
                continue
    return int(DEFAULT_MIN_DEPLOY_INTERVAL_SECONDS.get(service, 0))


def _deploy_restart_moment(deploy: dict) -> str:
    """When this deploy actually restarted the service, best available.

    `finishedAt` is the moment the new instance took over, which is what the
    spacing is measured from. A deploy still in flight has none, so its start is
    used -- it has already restarted the service or is about to, and either way
    firing another now is the "one build cancelled another" failure.
    """
    for field in ("finishedAt", "updatedAt", "createdAt"):
        value = str(deploy.get(field) or "").strip()
        if value:
            return value
    return ""


def last_restarting_deploy(service_id: str, key: str) -> dict:
    """The most recent deploy that restarted (or is restarting) this service.

    READ FROM RENDER, NOT FROM A LOCAL LEDGER, and that is the load-bearing
    choice. The 15 deploys that caused `#562` came from parallel sessions and
    all carried `trigger=api`; a file in this checkout can only ever see the
    ones this session wrote. `deploy_claim.py`'s own docstring makes the same
    argument about cross-session coordination: the only thing that sees every
    session's deploys is the thing every session deploys THROUGH.

    Returns {} when the list cannot be read or holds nothing restarting. The
    caller treats {} as "cannot tell" and does NOT refuse on it -- see the call
    site for why that one unknown is deliberately permissive.
    """
    deploys = _get(f"https://api.render.com/v1/services/{service_id}/deploys?limit=20", key) or []
    best: dict = {}
    best_moment = ""
    for row in deploys:
        deploy = row.get("deploy", row)
        status = str(deploy.get("status") or "").strip().lower()
        if status in NON_RESTARTING_DEPLOY_STATUSES:
            continue
        moment = _deploy_restart_moment(deploy)
        if not moment:
            continue
        # Lexical comparison on RFC3339 UTC, and sorted here rather than trusted
        # from the API: this file's own header records that the deploys/logs
        # endpoints do not return what their ordering suggests, and reading
        # `rows[0]` as newest produced a four-hour error in the direction that
        # says "safe to deploy".
        if moment > best_moment:
            best, best_moment = deploy, moment
    return best


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
            # HOW the evidence was obtained, and how old it was. A CLEAR from a
            # live endpoint read and a CLEAR from a log line are different
            # claims, and without these the receipt cannot be audited after the
            # fact -- which is the only time anyone reads it. `#465`.
            "sample_source": report.get("sample_source"),
            "sample_age_seconds": report.get("sample_age_seconds"),
            # `#562`. On the receipt and not only in the report, so "were we
            # hammering this service" is answerable from the deploy trail
            # afterwards rather than by reconstructing it from the Render API by
            # hand, which is what it took the first time.
            "min_deploy_interval_seconds": report.get("min_deploy_interval_seconds"),
            "seconds_since_last_deploy": (report.get("last_deploy") or {}).get("age_seconds"),
            "allow_rapid": report.get("allow_rapid"),
        }
        (RECEIPT_DIR / f"{args.service}.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    except Exception:
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--service", required=True, choices=sorted(SERVICE_IDS))
    parser.add_argument("--target-commit", default="", help="commit you intend to deploy; warns if already live")
    parser.add_argument("--allow-off-main", action="store_true",
                        help="permit a target commit that is NOT on origin/main. Such a "
                             "deploy cannot compose with another session's -- whichever "
                             "lands second silently reverts the first. Record why in deploys.md.")
    parser.add_argument("--allow-rapid", action="store_true",
                        help="permit a deploy inside this service's minimum spacing. The "
                             "escape hatch is here because a rate limit with no override "
                             "turns an outage into a longer one -- a revert must always be "
                             "able to go out. Record why in deploys.md.")
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

    # Composition check. `origin/main` is re-read from the local repo, so a stale
    # fetch reads as off-main rather than as on-main: an unknown must not land on
    # the permissive branch, and the remedy (`git fetch origin`) is in the reason.
    off_main = False
    if args.target_commit and not args.allow_off_main:
        on_main = is_ancestor(args.target_commit, "origin/main")
        report["target_on_main"] = on_main
        off_main = on_main is not True

    # SERVICE-AWARE SAMPLING (`#465`). Web is read from its own
    # /api/ops/memory; the workers keep the log path, which demonstrably works
    # for them (refresh-worker emits every ~17s). The fallback direction matters:
    # if the endpoint read fails we drop to the log path and, if that is also
    # empty, the existing staleness gate returns UNKNOWN. There is no branch
    # here that turns "cannot see" into "nothing running".
    sample = parsed = None
    sample_source = "log:ALL_PROCESS_MEMORY"
    if args.service in API_SAMPLED_SERVICES:
        api = web_processes()
        if api:
            processes, _sampled_at = api
            # Stamp with the run's OWN `now`, not a clock read taken inside the
            # fetch. Using the latter produced `age -2s` on the first live run:
            # harmless to the staleness gate, but a receipt that reports a
            # NEGATIVE age is a receipt nobody should trust the rest of.
            sample, parsed = (now.isoformat().replace("+00:00", "Z"), ""), {"processes": processes}
            sample_source = "api:/api/ops/memory"
    if parsed is None:
        sample = newest_log(service_id, key, "ALL_PROCESS_MEMORY")
        parsed = parse_processes(sample[1]) if sample else None
        sample_source = "log:ALL_PROCESS_MEMORY"
    age = _age_seconds(sample[0], now) if (sample and parsed) else None
    report["sample_at"] = sample[0] if sample else None
    report["sample_age_seconds"] = round(age, 1) if age is not None else None
    # Which path produced the verdict. Without this the receipt cannot be
    # audited: a CLEAR from a live endpoint read and a CLEAR from a log line are
    # different claims about how the evidence was obtained.
    report["sample_source"] = sample_source

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

    # `#562`. HOW LONG SINCE THIS SERVICE LAST RESTARTED.
    #
    # Computed unconditionally so the numbers reach the report even when the
    # limit is 0 or overridden -- a deploy log that records "spacing not
    # enforced" alongside the actual gap is auditable; one that records nothing
    # cannot answer "were we hammering it" after the fact, which is the question
    # that took a whole evening to answer by hand.
    min_interval = min_deploy_interval_seconds(args.service)
    report["min_deploy_interval_seconds"] = min_interval
    last_deploy: dict = {}
    since_last_deploy: float | None = None
    try:
        last_deploy = last_restarting_deploy(service_id, key)
        since_last_deploy = _age_seconds(_deploy_restart_moment(last_deploy), now) if last_deploy else None
    except Exception as exc:  # noqa: BLE001
        report["last_deploy_error"] = f"{type(exc).__name__}: {exc}"
    report["last_deploy"] = (
        {
            "id": last_deploy.get("id"),
            "status": last_deploy.get("status"),
            "commit": str((last_deploy.get("commit") or {}).get("id") or "")[:8] or None,
            "trigger": last_deploy.get("trigger"),
            "restarted_at": _deploy_restart_moment(last_deploy) or None,
            "age_seconds": since_last_deploy,
        }
        if last_deploy else None
    )

    # TOO_SOON ONLY WHEN WE ACTUALLY KNOW, and this is the one place in this file
    # where an unknown is deliberately NOT refused. Rule 1 says unknown must not
    # land on the permissive branch -- it applies to the question this script
    # exists for ("is something running that a deploy would kill"), which is
    # answered from the process sample and still refuses on absence.
    #
    # This is a different question. If the deploys endpoint cannot be read, the
    # process checks below are unaffected and still decide; refusing here as
    # well would mean a Render API blip blocks every deploy including a revert,
    # which is a worse failure than the one being prevented. The unknown is
    # RECORDED (`last_deploy: null`, or `last_deploy_error`) rather than
    # swallowed, so a preflight that could not see the history says so.
    too_soon = (
        min_interval > 0
        and not args.allow_rapid
        and since_last_deploy is not None
        and since_last_deploy < min_interval
    )
    report["too_soon"] = too_soon
    report["allow_rapid"] = bool(args.allow_rapid)

    stale = age is None or age > args.max_sample_age_seconds
    if off_main:
        verdict, code = "OFF_MAIN", EXIT_OFF_MAIN
        on_main = report.get("target_on_main")
        reason = (
            f"{args.target_commit[:8]} is not contained in origin/main"
            + (" (git could not say -- run `git fetch origin`)" if on_main is None else "")
            + ". A SHA off main cannot compose with another session's deploy: whichever "
              "lands second silently reverts the first. Rebase onto origin/main and "
              "deploy a commit that is on it, or pass --allow-off-main and say why in "
              "deploys.md."
        )
    elif foreign_claim:
        verdict, code = "CLAIMED", EXIT_CLAIMED
        reason = (
            f"deploy claim on {args.service} is held by {foreign_claim.get('holder')}"
            + (f" for {str(foreign_claim.get('target_commit'))[:8]}" if foreign_claim.get("target_commit") else "")
            + ". Coordinate with them, or --force the claim if that session is gone."
        )
    elif too_soon:
        # ORDERED BEFORE THE STALE-SAMPLE CHECK, and that ordering is the point
        # rather than an accident. Immediately after a deploy the worker has
        # usually not printed an ALL_PROCESS_MEMORY line yet, so the sample IS
        # stale -- and UNKNOWN would mask TOO_SOON behind a reason that tells the
        # operator to wait for a log line when what they actually need is to wait
        # 22 more minutes. Both refuse, so the gate is unchanged either way; the
        # REASON is what decides what the reader does next, and only one of them
        # is true.
        verdict, code = "TOO_SOON", EXIT_TOO_SOON
        wait_s = max(0, int(min_interval - (since_last_deploy or 0)))
        last = report.get("last_deploy") or {}
        in_flight = str(last.get("status") or "").strip().lower() in {"update_in_progress", "in_progress"}
        reason = (
            (f"a deploy of {args.service} is STILL IN FLIGHT ({last.get('id')}, "
             f"started {since_last_deploy:.0f}s ago). Deploying now cancels it mid-update, "
             f"which restarts the service twice rather than once."
             if in_flight else
             f"{args.service} was deployed {since_last_deploy / 60:.0f} min ago "
             f"({last.get('id')}, {last.get('trigger') or 'unknown trigger'}), "
             f"inside its {min_interval / 60:.0f} min minimum spacing.")
            + f" Wait {wait_s // 60} min {wait_s % 60}s."
            + (" refresh-worker takes ~21 min from boot to its first board publish, so a"
               " deploy inside that window leaves the board frozen and throws away the"
               " build in flight (`#562`)." if args.service == "refresh-worker" else "")
            + " If this is a revert or the board is already broken, --allow-rapid and say"
              " why in deploys.md."
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
    # PRINTED ON EVERY RUN, INCLUDING WHEN THE LIMIT IS OFF. A spacing rule that
    # only appears when it fires is one nobody knows the shape of until it blocks
    # them, and "not rate-limited" needs to be a thing a reader can SEE -- two of
    # the three services are at 0 because their cycle is unmeasured, not because
    # they are known to be safe.
    _last = report.get("last_deploy") or {}
    _gap = "unknown" if since_last_deploy is None else f"{since_last_deploy / 60:.0f} min ago"
    if min_interval > 0:
        _limit = f"min spacing {min_interval // 60} min"
        if args.allow_rapid:
            _limit += "  [OVERRIDDEN by --allow-rapid]"
    else:
        _limit = "not rate-limited (no measured cycle for this service)"
    print(f"last deploy    {_gap}"
          + (f"   {_last.get('id')} {_last.get('status') or ''} trigger={_last.get('trigger') or '?'}" if _last else "")
          + f"   {_limit}")
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
