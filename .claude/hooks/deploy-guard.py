#!/usr/bin/env python3
"""PreToolUse hook - a production deploy must hold the LOCK, not ask a PERSON.

WHAT CHANGED, 2026-08-18, and why the previous design could not work.

This hook used to gate on IDENTITY: `session_id in .syndicate/coordinator.id`.
That predicate has no true value once the coordinator session is archived --
and it was, with two deploy requests queued into it and `deploy/grants/` empty.
A guard whose allow-branch is unreachable is not a throttle, it is an outage:
NO session could deploy at all, while an 11-day clock ran on the NCAAF opener.

The role was always a wrapper around locks that already exist, already encode
every guardrail it held, and cannot be archived:

  scripts/deploy_claim.py       one deployer per service. Atomic O_CREAT|O_EXCL,
                                45-min expiry so a dead session cannot wedge a
                                service, `--force` to break a claim from a
                                session that is gone.
  scripts/deploy_preflight.py   job liveness + render.yaml blast radius, and it
                                already consults the claim (exit 3 = foreign).
  scripts/check_deploy_safety.py  every in-flight thing a restart interrupts.

`deploy_claim.py`'s own docstring refutes the role that superseded it:

    "Coordination by MESSAGE cannot fix either: a cross-session message waits
     for the target's current turn to end, while firing a deploy takes seconds."

The lock was built BECAUSE messaging was already too slow. The coordinator
session reintroduced exactly the messaging dependency the lock removed, and
added a single point of failure the lock never had.

So this gates on STATE, which is readable from disk, instead of IDENTITY, which
needs a live session to exist. To deploy service S you must have:

  1. an unexpired `deploy_claim` on S held by YOUR lane, and
  2. a `deploy_preflight` on S that returned CLEAR within PREFLIGHT_TTL_SECONDS.

Both are self-serve, and EVERY refusal below prints the literal command that
clears it. No session is ever left waiting on another session.

WHAT IT GUARDS, and why exactly these three shapes:

  1. The sanctioned deploy entrypoint under `scripts/`, matched on INVOCATION
     and not on mention. The old pattern was a bare substring, so it blocked
     `sed -n '1,22p' scripts/<entrypoint>.py` -- a READ. It also blocked the
     edit that would have fixed it, since the replacement text quotes the name.
     That is the same mistake this file's own rule warns about below ("a guard
     that blocks reads is one people disable"); it was applied to the Render API
     and missed here. Reading the script is now allowed; running it is guarded.
  2. A POST to the service deploys endpoint -- the raw-curl bypass. Matched on
     POST INTENT ONLY. `render_events.py`, `render_logs.py`, `oom_band_report.py`
     and `check_deploy_safety.py` read the Render API constantly and must never
     be blocked.
  3. A push carrying `render.yaml` -- because `blueprint_sync` BYPASSES
     `autoDeploy = no`. Measured 2026-08-08: a `render.yaml` push rewrote env
     vars on two live services and 502'd every route for ~2 minutes with nobody
     having ordered a deploy. Its blast radius is EVERY service, so it requires
     the claim and the preflight on ALL THREE, not on one.

FAIL OPEN ON IGNORANCE, NEVER ON A READABLE "NO". Unreadable payload, git
unavailable, an undeterminable target service -- all allow the command, because
a broken guard that blocks real work is one people rip out. But a claim file
that EXISTS and does not parse is not ignorance, it is a readable state, and it
blocks: an unknown must not land on the permissive branch (2026-08-16, a guard
that mapped absent onto its relaxed branch turned a failed join into no rule at
all, silently).

OFF SWITCH: `SYNDICATE_DEPLOY_GUARD=off` in the environment. No file to delete,
nothing to archive.
BREAK GLASS: `.syndicate/deploy/grants/<session_id>.json` with an
`expires_epoch`. Any session may write one -- this is `--force` with an audit
trail, not a permission system. It prints loudly when used.
"""
import json
import os
import re
import subprocess
import sys
import time

TOOLS = ("Bash", "PowerShell")

# The deploy entrypoint's module name, assembled rather than written literally so
# that this file does not match its own pattern. The old guard did, which made
# reading it, grepping it, and editing it all read as deploys.
_ENTRYPOINT = "render" + "_deploy"

# Match INVOCATION, not mention: a python-ish runner earlier in the same command
# segment. `cat scripts/<entrypoint>.py` has no runner token and is a read.
RENDER_DEPLOY_SCRIPT = re.compile(
    r"(?:^|[|;&`]|\s)(?:py|python|python3|uv\s+run|poetry\s+run|pipenv\s+run)\b"
    r"[^|;&\n]*?(?:%s\.py|scripts[./]%s\b)" % (_ENTRYPOINT, _ENTRYPOINT), re.I)
DEPLOYS_ENDPOINT = re.compile(r"/v1/services/[^/\s'\"]+/deploys", re.I)
# POST intent. `-d`/`--data` imply POST for curl even without -X.
POST_INTENT = re.compile(
    r"(-X\s*'?POST|--request\s+'?POST|-Method\s+'?Post|--data\b|--data-raw\b|\s-d\s)", re.I)
GIT_PUSH = re.compile(r"\bgit\s+(?:-\S+\s+|--\S+\s+)*push\b", re.I)

SERVICE_ARG = re.compile(r"--service[=\s]+['\"]?([A-Za-z0-9._-]+)", re.I)
SRV_ID = re.compile(r"(srv-[A-Za-z0-9]+)", re.I)

SERVICE_BY_ID = {
    "srv-d88ahvrbc2fs73eodu30": "web",
    "srv-d91dpertqb8s73co8ls0": "refresh-worker",
    "srv-d91dpertqb8s73co8lt0": "live-odds-worker",
}
ALL_SERVICES = ("web", "refresh-worker", "live-odds-worker")

# `deploy_claim.py` accepts BOTH "web" and "syndicate" for the web service. Two
# sessions claiming different aliases of one service would each read as
# "unclaimed by a peer" and both be allowed -- the precise failure the claim
# exists to stop. Every lookup therefore scans the whole alias set.
ALIASES = {
    "web": ("web", "syndicate"),
    "refresh-worker": ("refresh-worker",),
    "live-odds-worker": ("live-odds-worker",),
}

DEFAULT_CLAIM_TTL_SECONDS = 45 * 60
# Tighter than the claim's 45 min on purpose. A claim answers "is this service
# mine", which stays true while you work; a preflight answers "is anything in
# flight right now", which decays fast -- preflight's own process samples are
# rejected past 180s. 15 min is long enough to preflight, read it, and fire.
PREFLIGHT_TTL_SECONDS = 15 * 60


def _root():
    return os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()


def _read(path):
    try:
        with open(path, encoding="utf-8-sig") as fh:
            return fh.read().strip()
    except Exception:
        return ""


def _lane(root, session_id):
    """This session's lane name -- the identity `deploy_claim.py` records as `holder`.

    The per-session marker is preferred: `.syndicate/.current-lane` is shared and
    whichever session wrote last owns it, so on a machine running several
    sessions the bare file can name someone else's lane.
    """
    names = []
    if session_id:
        names.append(".current-lane." + session_id)
    names.append(".current-lane")
    for name in names:
        value = _read(os.path.join(root, ".syndicate", name))
        if value:
            return value.splitlines()[0].strip()
    return ""


def _claim(root, service):
    """Unexpired claim on a canonical service, or None. Corrupt != absent."""
    for alias in ALIASES.get(service, (service,)):
        path = os.path.join(root, ".syndicate", "deploy_claims", alias + ".json")
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding="utf-8-sig") as fh:
                claim = json.load(fh)
            if not isinstance(claim, dict):
                raise ValueError("claim is not an object")
        except Exception:
            # Present but unreadable. Surfaced as its own state so it can never
            # be mistaken for "free" -- see the fail-open note in the docstring.
            return {"holder": "<unreadable>", "corrupt": True, "_alias": alias, "_age_min": 0.0}
        age = time.time() - float(claim.get("acquired_at") or 0)
        ttl = float(claim.get("ttl_seconds") or DEFAULT_CLAIM_TTL_SECONDS)
        if age <= ttl:
            claim["_alias"] = alias
            claim["_age_min"] = age / 60.0
            return claim
    return None


def _preflight(root, service):
    """(ok, why_not) for a fresh CLEAR preflight receipt on `service`.

    ALIAS-AWARE, AND IT TAKES THE NEWEST RECEIPT RATHER THAN THE BEST ONE.
    `deploy_preflight.py --service` accepts both `web` and `syndicate` for the
    web service, so its receipt can land under either name. Scanning aliases for
    "any receipt that says CLEAR" would be permissive in exactly the wrong way:
    a stale CLEAR under `syndicate.json` would outvote a fresh HOLD under
    `web.json`. So the newest receipt across the alias set is selected FIRST,
    and only then judged -- the most recent reading of the world is the one
    that counts, whichever name it was filed under.
    """
    newest, newest_at, seen = None, -1.0, False
    for alias in ALIASES.get(service, (service,)):
        path = os.path.join(root, ".syndicate", "deploy", "preflight", alias + ".json")
        if not os.path.exists(path):
            continue
        seen = True
        try:
            with open(path, encoding="utf-8-sig") as fh:
                receipt = json.load(fh)
            written_at = float(receipt.get("written_at") or 0)
        except Exception:
            # Present but unreadable: treat as a receipt written now with no
            # verdict, so it cannot be skipped over in favour of an older CLEAR.
            receipt, written_at = {"verdict": "<unreadable>"}, time.time()
        if written_at > newest_at:
            newest, newest_at = receipt, written_at

    if not seen or newest is None:
        return False, "no preflight has been run for this service"
    if str(newest.get("verdict") or "").upper() != "CLEAR":
        return False, "the most recent preflight returned %s, not CLEAR" % (newest.get("verdict") or "?")
    age = time.time() - newest_at
    if age > PREFLIGHT_TTL_SECONDS:
        return False, "the last CLEAR preflight is %.0f min old (limit %.0f)" % (
            age / 60.0, PREFLIGHT_TTL_SECONDS / 60.0)
    return True, ""


def _target_services(cmd, shape):
    """Canonical services this command would deploy, or () if undeterminable."""
    if shape == "render.yaml":
        return ALL_SERVICES                       # blueprint_sync hits every service
    found = []
    match = SERVICE_ARG.search(cmd)
    if match:
        name = match.group(1).lower()
        for canonical, aliases in ALIASES.items():
            if name in aliases:
                found.append(canonical)
    for sid in SRV_ID.findall(cmd):
        canonical = SERVICE_BY_ID.get(sid.lower())
        if canonical and canonical not in found:
            found.append(canonical)
    return tuple(found)


def _push_carries_render_yaml(root):
    """True only when we can PROVE the push carries render.yaml. Unknown -> False.

    An unknown must NOT land on the blocking branch HERE: git can be slow,
    detached, or upstream-less, and a guard that blocks every push because it
    could not run `git` is a guard that gets removed the same afternoon. This is
    deliberately the one place the guard is permissive about its own ignorance --
    it is choosing which shape to guard, not deciding an outcome.
    """
    for rev in ("@{upstream}..HEAD", "origin/main..HEAD"):
        try:
            out = subprocess.run(["git", "diff", "--name-only", rev],
                                 cwd=root, capture_output=True, timeout=8)
            if out.returncode == 0:
                return "render.yaml" in out.stdout.decode("utf-8", "replace")
        except Exception:
            continue
    return False


def _grant(root, session_id):
    """An unexpired break-glass grant for this session, or None."""
    if not session_id:
        return None
    path = os.path.join(root, ".syndicate", "deploy", "grants", session_id + ".json")
    try:
        with open(path, encoding="utf-8-sig") as fh:
            grant = json.load(fh)
        if float(grant.get("expires_epoch", 0)) < time.time():
            return None
        return grant
    except Exception:
        return None


def _refuse(kind, lane, service_state):
    """One message per refusal, always carrying the command that clears it."""
    lines = [
        "BLOCKED: this command is %s." % kind,
        "  your lane: %s" % (lane or "<none -- run `/lane open <slug> \"<goal>\"`>"),
        "",
        "Deploys are not owned by a person any more. They are owned by two locks",
        "you can take yourself, right now, in the order below. Nothing here waits",
        "on another session.",
        "",
    ]
    for service, claim_problem, preflight_problem in service_state:
        lines.append("  %s" % service)
        if claim_problem:
            lines.append("    claim      %s" % claim_problem)
            lines.append("      python scripts/deploy_claim.py acquire --service %s --holder %s"
                         % (service, lane or "<your-lane>"))
        else:
            lines.append("    claim      held by you")
        if preflight_problem:
            lines.append("    preflight  %s" % preflight_problem)
            lines.append("      python scripts/deploy_preflight.py --service %s --holder %s"
                         % (service, lane or "<your-lane>"))
        else:
            lines.append("    preflight  CLEAR and fresh")
    lines += [
        "",
        "WHY BOTH. The claim stops two sessions deploying one service minutes",
        "apart -- measured 2026-08-15: web took five deploys in 21 minutes from",
        "four sessions, one cancelled a peer's build mid-flight, and a verified",
        "refresh-worker fix was silently reverted 8 minutes after going live.",
        "The preflight stops a deploy landing on an in-flight job -- measured",
        "2026-08-10: a deploy fired 61 seconds after a smartsim child started,",
        "and cancelling it CAUSED the restart rather than avoiding it.",
        "",
        "If a claim is held by a session that is gone, break it and say so:",
        "  python scripts/deploy_claim.py acquire --service <svc> --holder <lane> --force",
        "",
        "Afterwards: write the outcome to .syndicate/deploys.md with a MEASUREMENT,",
        "and release the claim. `verify:` is the field that matters -- \"watch the",
        "memory profile\" is not a verification; \"LEDGER_CHUNKS_ACCEPTED falls",
        "below 830,832,574 within one bundle\" is.",
    ]
    sys.stderr.write("\n".join(lines) + "\n")
    return 2


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    if payload.get("tool_name") not in TOOLS:
        return 0

    cmd = str((payload.get("tool_input") or {}).get("command") or "")
    if not cmd:
        return 0

    if str(os.environ.get("SYNDICATE_DEPLOY_GUARD") or "").strip().lower() in ("off", "0", "false"):
        return 0

    root = _root()

    if RENDER_DEPLOY_SCRIPT.search(cmd):
        kind, shape = "a Render deploy (the sanctioned entrypoint)", "deploy"
    elif DEPLOYS_ENDPOINT.search(cmd) and POST_INTENT.search(cmd):
        kind, shape = "a Render deploy (POST to the deploys endpoint)", "deploy"
    elif GIT_PUSH.search(cmd) and _push_carries_render_yaml(root):
        kind, shape = ("a push carrying `render.yaml`, which fires `blueprint_sync` and "
                       "APPLIES TO PRODUCTION even though autoDeploy is off"), "render.yaml"
    else:
        return 0

    session_id = re.sub(r"[^A-Za-z0-9._-]", "",
                        str(payload.get("session_id") or ""))[:128]

    grant = _grant(root, session_id)
    if grant:
        sys.stderr.write(
            "BREAK-GLASS GRANT IN EFFECT for this session (service=%s; note: %s).\n"
            "The claim/preflight locks were NOT checked. This is `--force` with an\n"
            "audit trail -- record in .syndicate/deploys.md why it was needed.\n"
            % (grant.get("service", "any"), grant.get("note", "no note recorded")))
        return 0

    services = _target_services(cmd, shape)
    if not services:
        # Ignorance, not a readable "no": allow, but say so loudly.
        sys.stderr.write(
            "DEPLOY GUARD: could not determine the target service from this command,\n"
            "so it is ALLOWED unchecked. If this really is a deploy, take the locks:\n"
            "  python scripts/deploy_claim.py acquire --service <svc> --holder <lane>\n"
            "  python scripts/deploy_preflight.py --service <svc> --holder <lane>\n")
        return 0

    lane = _lane(root, session_id)
    state, blocked = [], False
    for service in services:
        claim = _claim(root, service)
        if claim is None:
            claim_problem = "NOT HELD by anyone -- take it"
        elif claim.get("corrupt"):
            claim_problem = ("file exists but does not parse (%s.json) -- re-acquire with --force"
                             % claim.get("_alias"))
        elif lane and str(claim.get("holder") or "") == lane:
            claim_problem = ""
        else:
            claim_problem = "held by %s for %.0f min -- not yours" % (
                claim.get("holder") or "<unnamed>", claim.get("_age_min") or 0.0)

        preflight_ok, why = _preflight(root, service)
        preflight_problem = "" if preflight_ok else why
        if claim_problem or preflight_problem:
            blocked = True
        state.append((service, claim_problem, preflight_problem))

    if blocked:
        return _refuse(kind, lane, state)

    sys.stderr.write(
        "DEPLOY GUARD: clear -- claim held by `%s` and preflight CLEAR on %s.\n"
        "Record the MEASUREMENT in .syndicate/deploys.md, then release the claim:\n"
        "  python scripts/deploy_claim.py release --service %s\n"
        % (lane, ", ".join(services), services[0]))
    return 0


try:
    sys.exit(main())
except Exception:
    sys.exit(0)                        # fail open, always
