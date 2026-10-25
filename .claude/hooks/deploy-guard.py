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
     Python/JS POST intent counts too (`method="POST"`, `.post(`, a request
     body), but only when it is ATTACHED to the deploys URL: same line before
     it, or after it and before the next URL. `POST_INTENT` alone is
     curl/PowerShell-only, and a Python urllib deploy used to pass UNCHECKED
     (lane `deploy-guard-python-post`, 2026-09-15).
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

# POST INTENT AS PYTHON/JS WRITES IT. Lane `deploy-guard-python-post`, 2026-09-15.
#
# `POST_INTENT` above only knows curl/PowerShell, so a Python urllib POST to the
# deploys endpoint matched the endpoint, failed the intent, and was ALLOWED
# UNCHECKED -- no claim, no preflight, no `NO_EXPECTATION`. Measured 2026-09-15:
# both web deploys of that day (`b6a0e346`, `da268e07`) were exactly that shape
# and the guard never evaluated them; they held the locks only by choice.
#
# WHY THIS IS NOT ALSO A WHOLE-COMMAND AND. A read-only Python probe routinely
# GETs `/deploys?limit=` AND POSTs to an app endpoint in one command. "Endpoint
# anywhere AND POST anywhere" would block it, and a guard that blocks reads is
# one people disable. So the intent must be ATTACHED to the deploys URL: written
# before it on the same line (`requests.post("https://.../deploys"`), or after
# it within `_PY_INTENT_WINDOW` characters and before the next URL
# (`Request("https://.../deploys", data=..., method="POST")`).
_PY_POST_INTENT = re.compile(
    r"(method\s*[=:]\s*['\"]POST['\"]"   # urllib.request.Request(method="POST"), fetch({method: 'POST'})
    r"|\.post\s*\("                        # requests.post(, httpx.post(, session.post(
    r"|\.request\s*\(\s*['\"]POST['\"]"  # http.client / requests.request("POST", ...)
    # `data=` counts only as a CALL ARGUMENT (after "(" or ","), which is how a
    # request body is passed. As a bare `\bdata\s*=` it also matched the
    # ASSIGNMENT `data = json.loads(urlopen(req))` after a deploys GET and read a
    # read as a deploy -- measured on `scripts/build_consolidated_graft.py:93-96`
    # (lane `deploy-guard-file-scripts`, 2026-09-15).
    r"|[(,]\s*data\s*=\s*(?!None\b)[^,)\s=])",
    re.I)
_URL_START = re.compile(r"https?://", re.I)
_PY_INTENT_WINDOW = 400

# A DEPLOY MADE BY A SCRIPT FILE. Lane `deploy-guard-file-scripts`, 2026-09-15.
#
# Every check above reads COMMAND TEXT, so `py -3 deploy.py` carried nothing to
# match and passed unchecked however the file deployed -- the blind spot the
# `deploy-guard-python-post` lane recorded as its known limit. The guard now
# reads the file a command runs and applies the same checks to its CONTENTS:
# attached Python/JS POST intent for `.py`, same-line curl/PowerShell intent for
# `.sh`/`.ps1` (backslash and backtick continuations joined first).
#
# MEASURED BEFORE ENABLING: 22 repo files mention a deploys endpoint; with the
# `data=` fix above exactly one classifies as a deploy -- `render_deploy.py`,
# which the sanctioned-entrypoint rule already guards. `deploy_preflight.py`,
# `bandwidth_tripwire.py`, `ratchet_sample.py` and the graft builder read.
#
# ONE FILE, ONE LEVEL. Imports, `python -m <module>`, and paths built at runtime
# are not followed. A file that cannot be found, is over `_SCRIPT_MAX_BYTES`, or
# does not read is ALLOWED -- the fail-open rule at the bottom of this file --
# because a guard that blocks on a lookup it could not make is one people remove.
SCRIPT_RUN = re.compile(
    r"(?:^|[|;&`(\s])(?:py|python|python3|uv\s+run(?:\s+python)?|bash|sh)"
    r"(?:\s+-\d(?:\.\d+)?)?(?:\s+-[A-Za-z]\S*)*"
    r"\s+['\"]?([^\s'\";|&<>]+\.(?:py|sh))['\"]?", re.I)
PS_FILE = re.compile(r"-File\s+['\"]?([^\s'\";|&<>]+\.ps1)['\"]?", re.I)
DIRECT_SCRIPT = re.compile(r"(?:^|[|;&`(\s])(\.{1,2}[/\\][^\s'\";|&<>]+\.(?:sh|ps1))", re.I)
_SCRIPT_MAX_BYTES = 512 * 1024
GIT_PUSH = re.compile(r"\bgit\s+(?:-\S+\s+|--\S+\s+)*push\b", re.I)

SERVICE_ARG = re.compile(r"--service[=\s]+['\"]?([A-Za-z0-9._-]+)", re.I)
# `crn-` MATTERS AS MUCH AS `srv-`. `DEPLOYS_ENDPOINT` below already matched
# `/v1/services/crn-.../deploys`, but this pattern did not, so `_target_services`
# resolved NOTHING for a cron deploy and the guard took its "ignorance, not a
# readable no" branch: ALLOWED UNCHECKED, while printing advice to take a lock
# that `deploy_claim.py` then refused by `choices`. Measured 2026-09-08 (`#647`).
SRV_ID = re.compile(r"((?:srv|crn)-[A-Za-z0-9]+)", re.I)
COMMIT_ARG = re.compile(r"--commit[=\s]+['\"]?([0-9a-f]{7,40})", re.I)
# The SHA a Python/JS deploy carries in its JSON body. Read like `--commit` so a
# CLEAR receipt is bound to the commit actually being deployed, whichever form
# the command takes.
COMMIT_ID_FIELD = re.compile(r"['\"]commitId['\"]\s*:\s*['\"]([0-9a-f]{7,40})['\"]", re.I)

SERVICE_BY_ID = {
    "srv-d88ahvrbc2fs73eodu30": "web",
    "srv-d91dpertqb8s73co8ls0": "refresh-worker",
    "srv-d91dpertqb8s73co8lt0": "live-odds-worker",
    "crn-dafj4ie7bikc738q9ol0": "sim-input-reports",
    "crn-dafg4h0u01pc73aavs6g": "ci-suite",
    "crn-dafffnn40ujc73b349pg": "mlb-season-artifacts",
    "crn-dam0ao942hec73cge0rg": "model-scorecard",
}
CRON_SERVICES = ("sim-input-reports", "ci-suite", "mlb-season-artifacts", "model-scorecard")
# `ALL_SERVICES` is what a `render.yaml` push expands to, and crons are NOT in
# `render.yaml` -- `blueprint_sync` cannot reach them. They are guarded when
# named directly, and must not be dragged into a blueprint push's blast radius,
# which would demand three claims nobody needs and teach people to --force.
ALL_SERVICES = ("web", "refresh-worker", "live-odds-worker")

# `deploy_claim.py` accepts BOTH "web" and "syndicate" for the web service. Two
# sessions claiming different aliases of one service would each read as
# "unclaimed by a peer" and both be allowed -- the precise failure the claim
# exists to stop. Every lookup therefore scans the whole alias set.
ALIASES = {
    "web": ("web", "syndicate"),
    "refresh-worker": ("refresh-worker",),
    "live-odds-worker": ("live-odds-worker",),
    **{name: (name,) for name in CRON_SERVICES},
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


def _claim(root, service, lane=""):
    """Unexpired claim on a canonical service, or None. Corrupt != absent.

    `#635`. WHEN TWO ALIAS FILES BOTH HOLD A CLAIM, THE BLOCKING ONE WINS.
    This used to return the FIRST alias found, which makes the verdict depend on
    dict order: with `web.json` held by a peer and `syndicate.json` held by you,
    the wrong iteration order reads as "your own claim, proceed" and lets you
    cancel their build. `deploy_claim.py` no longer writes two files, but old
    ones exist and a guard must not be correct only because of tidy inputs.
    """
    found = []
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
            found.append(claim)
    if not found:
        return None
    # Prefer a claim held by SOMEONE ELSE: that is the one that must block.
    for claim in found:
        if not lane or str(claim.get("holder") or "") != lane:
            return claim
    return found[0]


def _python_post_to_deploys(cmd):
    """True when Python/JS POST intent is ATTACHED to a deploys-endpoint URL.

    See `_PY_POST_INTENT` for why attachment and not co-occurrence. Checked per
    endpoint occurrence: the text before it on its own line (after any earlier
    URL there), and the text after it up to the next URL or the window. A
    comment naming the endpoint carries no intent, so it does not match on its
    own.
    """
    for match in DEPLOYS_ENDPOINT.finditer(cmd):
        line_start = cmd.rfind("\n", 0, match.start()) + 1
        before = cmd[line_start:match.start()]
        urls = list(_URL_START.finditer(before))
        if urls:
            # Drop this endpoint's own scheme+host, then anything before an
            # earlier URL on the line: intent there belongs to that URL.
            before = before[:urls[-1].start()]
            earlier = list(_URL_START.finditer(before))
            if earlier:
                before = before[earlier[-1].end():]
        after = cmd[match.end():match.end() + _PY_INTENT_WINDOW]
        nxt = _URL_START.search(after)
        if nxt:
            after = after[:nxt.start()]
        if _PY_POST_INTENT.search(before) or _PY_POST_INTENT.search(after):
            return True
    return False


def _script_paths(cmd):
    """Script-file paths a command runs, in order, de-duplicated."""
    found = []
    for pattern in (SCRIPT_RUN, PS_FILE, DIRECT_SCRIPT):
        for match in pattern.finditer(cmd):
            path = match.group(1)
            if path not in found:
                found.append(path)
    return found


def _resolve_script(path, bases):
    """An existing file for `path`, trying it absolute and then under each base."""
    candidate = str(path).strip("'\"")
    drive = re.match(r"^/([a-zA-Z])/(.*)$", candidate)   # Git Bash /c/Users/... on Windows
    if drive and os.name == "nt":
        candidate = drive.group(1).upper() + ":/" + drive.group(2)
    options = [candidate] if os.path.isabs(candidate) else [os.path.join(b, candidate) for b in bases if b]
    for option in options:
        if os.path.isfile(option):
            return option
    return None


def _script_file_deploy(cmd, bases):
    """(path, contents) of the first script file the command runs that deploys, else (None, "").

    See `SCRIPT_RUN`. Every lookup failure is ignorance and returns no match.
    """
    for raw in _script_paths(cmd):
        path = _resolve_script(raw, bases)
        if not path:
            continue
        try:
            if os.path.getsize(path) > _SCRIPT_MAX_BYTES:
                continue
            with open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except Exception:
            continue
        if path.lower().endswith(".py"):
            if _python_post_to_deploys(text):
                return path, text
            continue
        joined = re.sub(r"(?:\\|`)\r?\n", " ", text)
        if any(DEPLOYS_ENDPOINT.search(line) and POST_INTENT.search(line) for line in joined.splitlines()):
            return path, text
    return None, ""


def _script_texts(cmd, bases):
    """[(path, contents)] of every readable SHELL script file the command runs.

    Shell only: a `.py` that holds fleet commands as STRING LITERALS (a test
    fixture, a proof harness) is not running them, and reading Python as shell
    blocked exactly that on 2026-10-25, the first time the installed hook ran.
    """
    out = []
    for raw in _script_paths(cmd):
        path = _resolve_script(raw, bases)
        if not path or not path.lower().endswith((".sh", ".ps1")):
            continue
        try:
            if os.path.getsize(path) > _SCRIPT_MAX_BYTES:
                continue
            with open(path, encoding="utf-8", errors="replace") as fh:
                out.append((path, fh.read()))
        except Exception:
            continue
    return out


# FLEET DEPLOYS `[2026-10-25, lane deploy-guard-fleet; user: "make deploy-guard
# require a claim + CLEAR fleet preflight for fleet ff / reload-web / role
# restarts"]`.
#
# Render has been billing-suspended since 2026-09-30, so every check above
# guards a production nobody deploys to, and the deploys that DO happen --
# `git merge --ff-only <sha>` in the fleet checkout, `local_production.py
# reload-web`, a `kill -TERM` the supervisor respawns -- matched nothing and ran
# unchecked. They held the locks only by habit. `deploy_preflight.py` reads the
# fleet since `0b93cbe8`, so the same two locks now apply:
#
#   ff of the fleet checkout  claim on ANY fleet service held by your lane + a
#                             fresh CLEAR receipt for THAT exact SHA on one of
#                             them. An ff loads nothing by itself, but it is the
#                             step that chooses what every later reload and
#                             respawn will run -- and a ref (`github/main`) is
#                             refused: the tip can carry another lane's commits
#                             (memory `feedback_ff_only_own_sha`).
#   reload-web, HUP/TERM of gunicorn          -> web
#   TERM/KILL of a worker role                -> that role
#   `local_production.py down`, kill of the supervisor -> all three
#
# A kill of a NUMERIC pid is resolved against the fleet's process table: killing
# your own job is not a deploy and stays allowed; a pid that cannot be resolved
# is ignorance and is allowed (the fail-open rule). Path restores
# (`git checkout -- <file>`) and a plain `git reset` (unstage) are not moves.
FLEET_ROLES = ("web", "refresh-worker", "live-odds-worker")
FLEET_CHECKOUT = re.compile(r"(?:~|\$HOME|\$\{HOME\}|/home/[^/\s'\"]+)/Syndicate(?![\w.-])")
_GIT_GLOBAL_OPTS = r"(?:-C\s+\S+\s+|-c\s+\S+\s+|--[\w-]+(?:=\S+)?\s+)*"
FLEET_GIT_MOVE = re.compile(
    r"\bgit\s+" + _GIT_GLOBAL_OPTS + r"(merge|pull|reset|rebase|switch|checkout|cherry-pick|revert)(?![\w-])"
    r"([^;&|\n'\"`)]*)", re.I)
FLEET_RELOAD_WEB = re.compile(r"local_production\.py\b[^;&|\n]*\sreload-web\b")
FLEET_DOWN = re.compile(r"local_production\.py\b[^;&|\n]*\sdown\b")
FLEET_KILL = re.compile(r"(?:^|[|;&`(\s'\"])(kill|pkill|killall)\b([^;&|\n'\"`]*)")
_SHA = re.compile(r"^[0-9a-f]{7,40}$", re.I)
_ROLE_BY_NAME = (
    ("run_live_odds_refresh_worker", ("live-odds-worker",)),
    ("run_refresh_worker", ("refresh-worker",)),
    ("gunicorn", ("web",)),
    ("wsgi:application", ("web",)),
    ("local_production", FLEET_ROLES),
)


def _roles_named(text):
    found = []
    for token, roles in _ROLE_BY_NAME:
        if token in text:
            found.extend(r for r in roles if r not in found)
    return found


def _fleet_ps(pids):
    """{pid: args} on the fleet host, or None when it cannot be read (ignorance).

    `SYNDICATE_FLEET_PS_FIXTURE` (a file of `pid args` lines) replaces `ps`, for tests.
    """
    fixture = os.environ.get("SYNDICATE_FLEET_PS_FIXTURE")
    try:
        if fixture:
            with open(fixture, encoding="utf-8") as fh:
                text = fh.read()
        else:
            command = ["ps", "-o", "pid=,args=", "-p", ",".join(pids)]
            if os.name == "nt":
                command = ["wsl", "--"] + command
            proc = subprocess.run(command, capture_output=True, timeout=10)
            text = proc.stdout.decode("utf-8", "replace")
    except Exception:
        return None
    rows = {}
    for line in text.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2 and parts[0].isdigit():
            rows[parts[0]] = parts[1]
    return rows


# QUOTED TEXT IS NOT A DEPLOY. The ledger quotes fleet commands verbatim
# (deploys.md: "`git merge --ff-only 9260ea0b` at 18:56:50Z", "`local_production.py
# reload-web` 2.6 s"), and so do commit messages and greps of it. A guard that
# blocks the write recording a deploy is one people disable. So: heredoc and
# PowerShell here-string BODIES are dropped unless an interpreter consumes them
# (`bash -s <<EOF` executes; `cat >> deploys.md <<EOF` does not), and a match is
# skipped when the words before it in its segment start with a text tool.
_HEREDOC = re.compile(r"(?m)^([^\n]*?)<<-?\s*(['\"]?)(\w+)\2[^\n]*\n(.*?)\n[ \t]*\3[ \t]*$", re.S)
_HERE_STRING = re.compile(r"@(['\"])\r?\n.*?\r?\n\1@", re.S)
# Shells only: a heredoc fed to `py -` is PYTHON, and its string literals are not commands.
_EXEC_FIRST = {"bash", "sh", "zsh", "wsl", "wsl.exe", "ssh"}
_TEXT_FIRST = {"grep", "rg", "egrep", "sed", "awk", "cat", "echo", "printf", "head", "tail", "less",
               "findstr", "select-string", "write-output", "write-host", "git", "gh", "tee"}


def _first_word(text):
    words = re.findall(r"[A-Za-z0-9_.:-]+", text)
    return words[0].lower() if words else ""


def _executed_text(cmd):
    """`cmd` minus the quoted bodies that are data rather than commands."""
    def heredoc(match):
        if _first_word(match.group(1).rsplit("|", 1)[-1]) in _EXEC_FIRST:
            return match.group(0)
        return match.group(1) + "<<HEREDOC-DATA"
    return _HERE_STRING.sub("@'HERE-STRING-DATA'@", _HEREDOC.sub(heredoc, cmd))


def _is_text(cmd, pos):
    """True when the match at `pos` is an argument of a text tool, not a command.

    The segment starts after the last `;&|` or newline OUTSIDE quotes: `grep
    'restart.*\\|kill.*refresh'` is one grep, not a grep and a kill (found by the
    transcript sweep run before enabling this), while `wsl -- bash -lc 'cd
    ~/Syndicate && git merge ...'` is one `wsl` segment whose quoted body runs.
    """
    start, quote, i = 0, "", 0
    while i < pos:
        ch = cmd[i]
        if quote:
            if ch == quote:
                quote = ""
            elif ch == "\\" and quote == '"':
                i += 1
        elif ch in "'\"":
            quote = ch
        elif ch in ";&|\n":
            start = i + 1
        i += 1
    return _first_word(cmd[start:pos]) in _TEXT_FIRST


_CD = re.compile(r"(?:^|[\s;&|('\"])(?:cd|--cd)\s+['\"]?([^\s'\";&|)]+)")
_GIT_C = re.compile(r"\s-C\s+['\"]?([^\s'\";&|)]+)")


def _git_dir(cmd, match):
    """The directory a git command runs in: its own `-C`, else the nearest `cd` before it."""
    own = _GIT_C.search(match.group(0))
    if own:
        return own.group(1)
    cds = list(_CD.finditer(cmd, 0, match.start()))
    return cds[-1].group(1) if cds else ""


def _fleet_deploy(cmd):
    """{"roles": [...], "ff": ref-or-None, "what": [...]} when `cmd` deploys to the fleet, else None."""
    cmd = _executed_text(cmd)
    roles, what, ff_ref = [], [], None

    def add(names, label):
        for name in names:
            if name not in roles:
                roles.append(name)
        if label not in what:
            what.append(label)

    if FLEET_CHECKOUT.search(cmd):
        for match in FLEET_GIT_MOVE.finditer(cmd):
            # BOUND TO ITS DIRECTORY, not to the command: the sweep found ledger
            # worktree ffs (`cd /c/tmp/ledger-1002 && git merge --ff-only
            # origin/main`) sharing a command with a later `~/Syndicate` read.
            if _is_text(cmd, match.start()) or not FLEET_CHECKOUT.search(_git_dir(cmd, match)):
                continue
            verb, rest = match.group(1).lower(), match.group(2)
            tokens = rest.split()
            if verb in ("checkout", "switch") and "--" in tokens:
                continue                                   # a path restore, not a move
            if verb == "reset" and not any(t in ("--hard", "--keep", "--merge") for t in tokens):
                continue                                   # unstage, not a move
            refs = [t for t in tokens if not t.startswith("-") and not re.search(r"[<>]", t)]
            ff_ref = refs[-1] if refs else "<no ref>"
            what.append("a move of the fleet checkout (`git %s %s`)" % (verb, ff_ref))
            break
    if any(not _is_text(cmd, m.start()) for m in FLEET_RELOAD_WEB.finditer(cmd)):
        add(("web",), "`local_production.py reload-web`")
    if any(not _is_text(cmd, m.start()) for m in FLEET_DOWN.finditer(cmd)):
        add(FLEET_ROLES, "`local_production.py down`")
    for match in FLEET_KILL.finditer(cmd):
        if _is_text(cmd, match.start(1)):
            continue
        args = match.group(2)
        if re.search(r"(?:^|\s)-(?:0|s\s*0)(?:\s|$)", args):
            continue                                       # signal 0 only probes
        # Names are read to the end of the SEGMENT, not of `args`: the target is
        # often a substitution, `kill -HUP $(pgrep -f "gunicorn ..." | head -1)`,
        # whose quote and pipe would otherwise hide the role.
        segment = re.split(r"[;&\n]", cmd[match.start(2):], maxsplit=1)[0]
        named = _roles_named(segment)
        if named:
            add(named, "a %s of a fleet role (%s)" % (match.group(1), ", ".join(named)))
            continue
        pids = [t for t in args.split() if t.isdigit()]
        if not pids or (os.name == "nt" and "wsl" not in cmd):
            continue                                       # a Windows pid is not the fleet
        table = _fleet_ps(pids)
        if not table:
            continue                                       # cannot resolve: ignorance, allow
        for pid in pids:
            named = _roles_named(table.get(pid, ""))
            if named:
                add(named, "a %s of fleet pid %s (%s)" % (match.group(1), pid, ", ".join(named)))
    if not roles and ff_ref is None:
        return None
    return {"roles": roles, "ff": ff_ref, "what": what}


def _claim_problem(root, service, lane):
    claim = _claim(root, service, lane)
    if claim is None:
        return "NOT HELD by anyone -- take it"
    if claim.get("corrupt"):
        return "file exists but does not parse (%s.json) -- re-acquire with --force" % claim.get("_alias")
    if lane and str(claim.get("holder") or "") == lane:
        return ""
    return "held by %s for %.0f min -- not yours" % (
        claim.get("holder") or "<unnamed>", claim.get("_age_min") or 0.0)


def _check_fleet(root, lane, fleet):
    """0 to allow, or the refusal's exit code. Same two locks as a Render deploy."""
    kind = "a FLEET deploy: " + "; ".join(fleet["what"])
    ff = fleet["ff"]
    if ff is not None and not _SHA.match(ff):
        sys.stderr.write(
            "BLOCKED: this command is %s.\n"
            "Move the fleet checkout to an EXACT SHA you have read, not `%s`: a ref's tip\n"
            "can carry another lane's commits you never reviewed. Then take the locks:\n"
            "  git merge --ff-only <sha>        # in ~/Syndicate, after git fetch\n"
            % (kind, ff))
        return 2
    state, blocked = [], False
    for service in fleet["roles"]:
        claim_problem = _claim_problem(root, service, lane)
        ok, why = _preflight(root, service, ff)
        if claim_problem or not ok:
            blocked = True
        state.append((service, claim_problem, "" if ok else why))
    if ff is not None and not fleet["roles"]:
        # An ff alone: ONE fleet service of yours must vouch for this SHA.
        rows = []
        for service in FLEET_ROLES:
            claim_problem = _claim_problem(root, service, lane)
            ok, why = _preflight(root, service, ff)
            if not claim_problem and ok:
                rows = []
                break
            rows.append((service, claim_problem, "" if ok else why))
        if rows:
            blocked = True
            kind += (" -- needs YOUR claim + a CLEAR preflight for %s on ANY ONE fleet service"
                     " (web is the usual one for an ff + reload-web)" % ff[:8])
            state = rows
    if blocked:
        return _refuse(kind, lane, state)
    sys.stderr.write(
        "DEPLOY GUARD: clear -- %s under `%s`.\n"
        "Record the MEASUREMENT in .syndicate/deploys.md, then release the claim(s).\n"
        % ("; ".join(fleet["what"]), lane))
    return 0


def _commits_agree(receipt_sha, deploy_sha):
    """True when the receipt vouches for the SHA actually being deployed.

    Either may be abbreviated, so this is a prefix comparison in whichever
    direction is longer. Without this, a CLEAR taken for one commit authorises a
    deploy of any OTHER commit for the next 15 minutes -- including one that is
    off main, which is the exact thing preflight's OFF_MAIN verdict exists to
    stop. The receipt has to be bound to its subject or it is just a timer.
    """
    a, b = str(receipt_sha or "").lower(), str(deploy_sha or "").lower()
    if not a or not b:
        return False
    return a.startswith(b) or b.startswith(a)


def _preflight(root, service, deploy_sha=None):
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
    verdict = str(newest.get("verdict") or "").upper()
    if verdict != "CLEAR":
        # CARRY THE PREFLIGHT'S OWN REASON, not just the verdict name. `#563`.
        #
        # This guard's contract is that every refusal prints the literal thing
        # that clears it, so no session is left waiting on another. TOO_SOON is
        # the first verdict where that thing is NOT a command -- it is elapsed
        # time -- and "returned TOO_SOON, not CLEAR" plus this file's standing
        # "run the preflight" remedy sends the reader into a retry loop against a
        # clock. The preflight already computed the wait in minutes and the
        # --allow-rapid escape; passing it through is what keeps the promise.
        detail = str(newest.get("reason") or "").strip()
        return False, ("the most recent preflight returned %s, not CLEAR" % (verdict or "?")
                       + (" -- %s" % detail if detail else ""))
    age = time.time() - newest_at
    if age > PREFLIGHT_TTL_SECONDS:
        return False, "the last CLEAR preflight is %.0f min old (limit %.0f)" % (
            age / 60.0, PREFLIGHT_TTL_SECONDS / 60.0)
    if deploy_sha:
        receipt_sha = newest.get("target_commit")
        if not receipt_sha:
            return False, ("the CLEAR preflight was run without --target-commit, so it "
                           "vouches for no particular SHA (re-run it with "
                           "--target-commit %s)" % deploy_sha[:8])
        if not _commits_agree(receipt_sha, deploy_sha):
            return False, ("the CLEAR preflight is for %s but this deploys %s"
                           % (str(receipt_sha)[:8], deploy_sha[:8]))
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


def _blueprint_drift(root):
    """(exit_code, printable) from scripts/check_blueprint_drift.py.

    Returns (0, "") when the checker cannot be run at all -- ALLOWING the push.
    That looks like the wrong default for a safety check and is the right one
    HERE: this hook's whole contract is to fail open (`except Exception:
    sys.exit(0)` at the bottom of the file), and a missing checker must not
    become a way to wedge every render.yaml push forever. The checker itself
    fails CLOSED on an unreadable API, which is where that judgement belongs.
    """
    if str(os.environ.get("SYNDICATE_ALLOW_BLUEPRINT_DRIFT") or "").strip().lower() in ("1", "true", "yes", "on"):
        return 0, ""
    script = os.path.join(root, "scripts", "check_blueprint_drift.py")
    if not os.path.isfile(script):
        return 0, ""
    try:
        proc = subprocess.run([sys.executable, script],
                              capture_output=True, timeout=120, cwd=root)
    except Exception:  # noqa: BLE001 -- a broken checker must not wedge pushes
        return 0, ""
    out = (proc.stdout or b"").decode("utf-8", "replace")
    tail = [ln for ln in out.splitlines() if ln.startswith(("DRIFT:", "UNKNOWN:", "CLEAR:"))]
    return proc.returncode, chr(10).join(tail[-4:]) or out[-400:]


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
                         " --target-commit <sha> --expect FIELD=VALUE --baseline FIELD=VALUE"
                         " --baseline-read-at <UTC>"
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

    script_path, script_text = None, ""
    fleet = _fleet_deploy(cmd)
    if fleet is None:
        for _path, _text in _script_texts(cmd, [str(payload.get("cwd") or ""), root, os.getcwd()]):
            fleet = _fleet_deploy(_text)
            if fleet is not None:
                fleet["what"].append("run from the script %s" % _path)
                break
    if fleet is not None:
        session_id = re.sub(r"[^A-Za-z0-9._-]", "", str(payload.get("session_id") or ""))[:128]
        grant = _grant(root, session_id)
        if grant:
            sys.stderr.write(
                "BREAK-GLASS GRANT IN EFFECT for this session (service=%s; note: %s).\n"
                "The claim/preflight locks were NOT checked for this FLEET deploy. Record\n"
                "in .syndicate/deploys.md why it was needed.\n"
                % (grant.get("service", "any"), grant.get("note", "no note recorded")))
            return 0
        return _check_fleet(root, _lane(root, session_id), fleet)

    if RENDER_DEPLOY_SCRIPT.search(cmd):
        kind, shape = "a Render deploy (the sanctioned entrypoint)", "deploy"
    elif DEPLOYS_ENDPOINT.search(cmd) and POST_INTENT.search(cmd):
        kind, shape = "a Render deploy (POST to the deploys endpoint)", "deploy"
    elif _python_post_to_deploys(cmd):
        kind, shape = "a Render deploy (a Python/JS POST to the deploys endpoint)", "deploy"
    elif GIT_PUSH.search(cmd) and _push_carries_render_yaml(root):
        kind, shape = ("a push carrying `render.yaml`, which fires `blueprint_sync` and "
                       "APPLIES TO PRODUCTION even though autoDeploy is off"), "render.yaml"
    else:
        script_path, script_text = _script_file_deploy(
            cmd, [str(payload.get("cwd") or ""), root, os.getcwd()])
        if not script_path:
            return 0
        kind, shape = ("a Render deploy (a script file that POSTs to the deploys endpoint: %s)"
                       % script_path), "deploy"

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

    # BLUEPRINT DRIFT: a `render.yaml` push is refused while the file is behind
    # LIVE env, and NO CLAIM CAN AUTHORISE IT. This runs BEFORE the lock logic
    # on purpose -- the locks answer "is it your turn", and no amount of turn
    # makes deleting 167 production env vars correct.
    #
    # MEASURED 2026-09-08: `render.yaml` was 167 keys behind production across
    # three services. A sync would have deleted `SYNDICATE_EXECUTION_MODE=live`,
    # `SYNDICATE_EXECUTION_LIVE_ARMED=1`, the spend caps of a live-money
    # execution system, AND the venue credentials themselves
    # (`KALSHI_PRIVATE_KEY`, `POLYMARKET_US_PRIVATE_KEY`), while overwriting
    # `ODDS_API_KEY` on all three. Three locks and a CLEAR preflight would have
    # let every bit of that through, because none of them looks at env.
    #
    # THIS FILE'S OWN HEADER PROMISED THIS CHECK AND NOBODY HAD WRITTEN IT: it
    # advertises "`scripts/deploy_preflight.py`   job liveness + render.yaml
    # blast radius", and preflight contains no env-var logic at all. This makes
    # the sentence true.
    #
    # SCOPED TO `render.yaml` PUSHES ONLY, so an ordinary service deploy pays
    # nothing -- no API calls, no latency, no new way to fail. And the module
    # tail is `except Exception: sys.exit(0)`, so a bug in the checker itself
    # still fails OPEN, which is this file's standing contract.
    if shape == "render.yaml":
        drift_code, drift_out = _blueprint_drift(root)
        if drift_code != 0:
            sys.stderr.write(
                "BLOCKED: this push carries `render.yaml`, and the file is BEHIND\n"
                "live production env. `blueprint_sync` would apply it wholesale.\n\n"
                "%s\n\n"
                "No claim authorises this -- the locks order deploys, they do not\n"
                "make a destructive one safe. Reconcile the live values INTO\n"
                "render.yaml first, and do NOT copy secrets into a git-tracked\n"
                "file (ODDS_API_KEY, ADMIN_TOKEN, KALSHI_PRIVATE_KEY and\n"
                "POLYMARKET_US_PRIVATE_KEY belong to the dashboard; they want\n"
                "`sync: false`).\n\n"
                "  py -3 scripts/check_blueprint_drift.py       # the full enumeration\n\n"
                "Override, and say why in .syndicate/deploys.md:\n"
                "  SYNDICATE_ALLOW_BLUEPRINT_DRIFT=1\n"
                % drift_out)
            return 2

    services = _target_services(cmd + "\n" + script_text, shape)
    if not services:
        # Ignorance, not a readable "no": allow, but say so loudly.
        sys.stderr.write(
            "DEPLOY GUARD: could not determine the target service from this command,\n"
            "so it is ALLOWED unchecked. If this really is a deploy, take the locks:\n"
            "  python scripts/deploy_claim.py acquire --service <svc> --holder <lane>\n"
            "  python scripts/deploy_preflight.py --service <svc> --holder <lane> --target-commit <sha>\n"
            "      --expect FIELD=VALUE --baseline FIELD=VALUE --baseline-read-at <UTC>\n")
        return 0

    lane = _lane(root, session_id)
    # A render.yaml push carries no --commit; the receipt-to-SHA binding applies
    # to service deploys only.
    m = COMMIT_ARG.search(cmd) or COMMIT_ID_FIELD.search(cmd) or COMMIT_ID_FIELD.search(script_text)
    deploy_sha = m.group(1) if (m and shape == "deploy") else None

    state, blocked = [], False
    for service in services:
        claim = _claim(root, service, lane)
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

        preflight_ok, why = _preflight(root, service, deploy_sha)
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
