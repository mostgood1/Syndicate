"""Run Syndicate PRODUCTION on one machine -- web, refresh-worker,
live-odds-worker and the shared state store -- from render.yaml's own config.
Lane `local-production-host` `[2026-09-30]`: all three Render services are
billing-suspended.

    py -3 scripts/local_production.py init        # home dir + secrets template
    py -3 scripts/local_production.py doctor      # everything that would stop `up`
    py -3 scripts/local_production.py up          # bootstrap once, then supervise forever
    py -3 scripts/local_production.py status      # pids, /healthz, log tails
    py -3 scripts/local_production.py down        # stop a running `up`
    py -3 scripts/local_production.py env --role refresh-worker   # the derived env, secrets masked
    py -3 scripts/local_production.py backup      # snapshot data root + redis (also a nightly job)
    py -3 scripts/local_production.py ci-run      # the ci-suite cron, in its own checkout (also a job)

Runbook: docs/ai_context/local_production_runbook.md.

HOW THIS DIFFERS FROM scripts/fleet_local.py
--------------------------------------------
`fleet_local.py` is a REHEARSAL harness: replay-only network, no API keys, no
admin token, paper money, a bounded run. That is right for testing code and
wrong for serving production. This tool is the production counterpart:

* The env comes from `render.yaml` ITSELF, parsed at start, per service. Nothing
  here restates a run-mode. Loop ownership (`SYNDICATE_MLB_REFRESH_TICK_OWNER`,
  `SYNDICATE_ENABLE_LIVE_ODDS_REFRESH_LOOP`, the intelligence loop on
  refresh-worker only, ...) is whatever the blueprint says for that service, so
  a change to render.yaml changes the local fleet the same way it would have
  changed Render.
* Keys the blueprint marks `sync: false`, `generateValue: true`, or that live
  only in the Render dashboard (venue keys, ANTHROPIC_API_KEY, the
  `*_AUTORUN` switches) come from ONE local file, `local_production.env`, in
  the home directory -- never from the repo. `init` writes a template listing
  every such key the blueprint names.
* Real network, real keys, a long-running supervisor that restarts a role that
  exits (Render restarts a crashed worker; so does this).

WHAT IS CHANGED FROM THE BLUEPRINT, AND WHY EACH ONE
----------------------------------------------------
Everything not listed is passed through verbatim.

  /opt/render/project/data/...  -> <home>/data/...   one shared disk (see below)
  /opt/render/project/src/...   -> <repo>/...
  SYNDICATE_REFRESH_STATE_URL   -> local redis       the keyvalue `fromService`
  ADMIN_TOKEN (fromService/generateValue) -> local_production.env, one value
  SYNDICATE_WEB_PUBLISH_URL     -> REMOVED           see "one shared disk"
  SYNDICATE_BOOTSTRAP_ON_START  -> 0 in the roles    `up` seeds ONCE, first
  PORT                          -> --port
  RENDER=true, RENDER_SERVICE_NAME, RENDER_INSTANCE_ID, RENDER_GIT_COMMIT
                                -> set, because the code branches on them:
                                   the request-path compute guard, portfolio
                                   auth (`required` on Render), disk
                                   compaction, per-service lanes. Without them
                                   the web process quietly behaves like a
                                   developer laptop instead of production.
  SYNDICATE_EXECUTION_MODE / _LIVE_ARMED -> paper, 0
                                   UNLESS `up --allow-live-execution`. Real
                                   money is never armed by a config file alone.
  SYNDICATE_EXECUTION_ENABLED   -> 1 (paper fills, venue settlement, ORDER_PATH)
                                   unless local_production.env says 0.

ONE SHARED DISK
---------------
On Render each service had its OWN 50 GB disk, so workers pushed artifacts to
web over the private network (`SYNDICATE_WEB_PUBLISH_URL` ->
`/api/ops/artifacts/publish`) and pulled web's copies back. On one machine all
three roles read and write the same `SYNDICATE_DATA_ROOT`, so publishing to
ourselves would only re-write files in place over HTTP. With the URL unset the
publisher skips cleanly (`PULL_SKIP_NOT_CONFIGURED` / `SEASON_PULL_SKIP_...`),
which is the correct no-op here. `--publish-loopback` restores it against the
local web if a web-side side effect of publish ever turns out to matter.

STATE STORE
-----------
Production is `SYNDICATE_REFRESH_STATE_BACKEND=keyvalue` with
`SYNDICATE_REQUIRE_HOSTED_STORAGE=true`; with `RENDER=true` the workers REFUSE a
file backend (`assert_refresh_state_backend_ready`). So the default here is a
local Redis, and `up` starts `redis-server` itself (persistent, loopback only)
when one is installed and nothing is listening. `--state file` is the fallback
for a machine with no Redis at all: it clears RENDER and
REQUIRE_HOSTED_STORAGE, which is honest on one shared disk but means the
Render-only branches above are OFF -- `doctor` says so.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import platform
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
LOGSTAMP_DIR = REPO_ROOT / "scripts" / "local_logstamp"
# `python scripts/local_production.py` puts scripts/ on sys.path, not the repo
# root, and `down` imports syndicate.features.shared.process_liveness.
# It also broke `import-render-env` (`from scripts.snapshot_render_env`) on the
# first native-Windows run, 2026-09-30.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
RENDER_YAML = REPO_ROOT / "render.yaml"
IS_WINDOWS = os.name == "nt"

RENDER_DATA_PREFIX = "/opt/render/project/data"
RENDER_SRC_PREFIX = "/opt/render/project/src"
ENV_FILE_NAME = "local_production.env"
PIDFILE_NAME = "supervisor.json"

ROLE_ORDER = ("web", "refresh-worker", "live-odds-worker")
# render.yaml service name -> local role name
SERVICE_TO_ROLE = {"syndicate": "web", "refresh-worker": "refresh-worker", "live-odds-worker": "live-odds-worker"}
# Render plan memory, reported by `status` next to each role's RSS so a local
# reading can be held against the ceiling it used to run under.
PLAN_MEMORY_MB = {"web": 2048, "refresh-worker": 4096, "live-odds-worker": 2048}

EXECUTION_KEYS = ("SYNDICATE_EXECUTION_MODE", "SYNDICATE_EXECUTION_LIVE_ARMED", "SYNDICATE_EXECUTION_ENABLED")
# PAPER, BUT RUNNING. Mode=paper and armed=0 are what keep money off: a live
# order needs BOTH mode=live and armed=1, and in paper `place_order` never calls
# a venue submitter. ENABLED was forced to 0 here too (copied from
# fleet_local.py, a replay harness that also strips the venue keys), and that
# silenced far more than orders: on 2026-10-02 the fleet's whole life showed
# 431 PORTFOLIO_COMMIT, 0 PORTFOLIO_EXECUTED / PAPER2_EXECUTED, 0
# VENUE_SETTLEMENT, 0 ORDER_PATH -- no paper evidence, no settlement of the
# real venue accounts. So ENABLED defaults to 1; `SYNDICATE_EXECUTION_ENABLED=0`
# in local_production.env still turns the whole tick off.
PAPER_EXECUTION = {"SYNDICATE_EXECUTION_MODE": "paper", "SYNDICATE_EXECUTION_LIVE_ARMED": "0"}
PAPER_EXECUTION_ENABLED_DEFAULT = "1"

# Known dashboard-only keys: read by the code, set on the live services, and
# declared NOWHERE in render.yaml (names from scripts/_fleet_guard.py and the
# env snapshots). `init` lists them in the template so none is forgotten.
DASHBOARD_ONLY_KEYS: dict[str, str] = {
    "ANTHROPIC_API_KEY": "Ask the Syndicate LLM briefings (absent = snapshot-only answers)",
    "CFBD_API_KEY": "NCAAF stats (CollegeFootballData)",
    "KALSHI_API_KEY_ID": "Kalshi venue -- quotes and (only when live-armed) orders",
    "KALSHI_PRIVATE_KEY": "Kalshi RSA key, PEM with literal \\n newlines",
    "POLYMARKET_US_API_KEY_ID": "Polymarket US venue",
    "POLYMARKET_US_PRIVATE_KEY": "Polymarket US signing key",
    "SYNDICATE_EXECUTION_VENUE": "e.g. kalshi,polymarket",
    "SYNDICATE_EXECUTION_MODE": "paper (default) | live -- live ALSO needs `up --allow-live-execution`",
    "SYNDICATE_EXECUTION_LIVE_ARMED": "0 | 1",
    "SYNDICATE_EXECUTION_ENABLED": "0 | 1",
    "SYNDICATE_PORTFOLIO_USERNAME": "portfolio page login (required once RENDER=true)",
    "SYNDICATE_PORTFOLIO_PASSWORD_HASH": "werkzeug hash: python -c \"from werkzeug.security import generate_password_hash as g; print(g('pw'))\"",
}

# Deliberately NOT carried over even when present in the env file: they point at
# Render itself, and a local fleet must not act on production's account.
NEVER_CARRY = ("RENDER_API_KEY",)


# --------------------------------------------------------------------------
# render.yaml -> per-role env
# --------------------------------------------------------------------------


@dataclass
class BlueprintKey:
    key: str
    value: str | None  # None = needs a local value
    source: str  # value | generate | from_web | keyvalue | sync_false


def load_blueprint(path: Path = RENDER_YAML) -> dict[str, list[BlueprintKey]]:
    import yaml

    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    out: dict[str, list[BlueprintKey]] = {}
    for service in doc.get("services") or []:
        role = SERVICE_TO_ROLE.get(str(service.get("name") or ""))
        if role is None:
            continue
        keys: list[BlueprintKey] = []
        for entry in service.get("envVars") or []:
            name = str(entry.get("key") or "").strip()
            if not name:
                continue
            if "value" in entry:
                keys.append(BlueprintKey(name, str(entry["value"]), "value"))
            elif entry.get("generateValue"):
                keys.append(BlueprintKey(name, None, "generate"))
            elif isinstance(entry.get("fromService"), dict):
                ref = entry["fromService"]
                if str(ref.get("type")) == "keyvalue":
                    keys.append(BlueprintKey(name, None, "keyvalue"))
                else:
                    keys.append(BlueprintKey(name, None, "from_web"))
            elif entry.get("sync") is False:
                keys.append(BlueprintKey(name, None, "sync_false"))
        out[role] = keys
    missing = [r for r in ROLE_ORDER if r not in out]
    if missing:
        raise SystemExit(f"render.yaml has no service for role(s) {missing}; expected {SERVICE_TO_ROLE}")
    return out


def parse_env_file(path: Path) -> dict[str, str]:
    """KEY=VALUE lines; `#` comments; optional surrounding quotes. `\\n` inside a
    double-quoted value becomes a newline (PEM keys)."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            quote = value[0]
            value = value[1:-1]
            if quote == '"':
                value = value.replace("\\n", "\n")
        if key:
            values[key] = value
    return values


def rewrite_path(value: str, *, data_root: Path) -> str:
    if value == RENDER_DATA_PREFIX or value.startswith(RENDER_DATA_PREFIX + "/"):
        tail = value[len(RENDER_DATA_PREFIX):].lstrip("/")
        return str(data_root.joinpath(*tail.split("/")) if tail else data_root)
    if value == RENDER_SRC_PREFIX or value.startswith(RENDER_SRC_PREFIX + "/"):
        tail = value[len(RENDER_SRC_PREFIX):].lstrip("/")
        return str(REPO_ROOT.joinpath(*tail.split("/")) if tail else REPO_ROOT)
    return value


@dataclass
class Settings:
    home: Path
    port: int = 10000
    host: str = "127.0.0.1"
    state: str = "redis"
    redis_url: str = "redis://127.0.0.1:6379/0"
    allow_live_execution: bool = False
    publish_loopback: bool = False

    @property
    def data_root(self) -> Path:
        return self.home / "data"

    @property
    def logs_dir(self) -> Path:
        return self.home / "logs"

    @property
    def run_dir(self) -> Path:
        return self.home / "run"

    @property
    def env_file(self) -> Path:
        return self.home / ENV_FILE_NAME


RENDER_SERVICE_IDS = {
    # scripts/snapshot_render_env.py SERVICES, restated so this file has no
    # import-time dependency on it.
    "web": "srv-d88ahvrbc2fs73eodu30",
    "refresh-worker": "srv-d91dpertqb8s73co8ls0",
    "live-odds-worker": "srv-d91dpertqb8s73co8lt0",
}


def live_env_path(settings: "Settings", role: str) -> Path:
    return settings.home / "render_env" / f"{role}.json"


def load_live_env(settings: "Settings", role: str) -> dict[str, str]:
    path = live_env_path(settings, role)
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    values = payload.get("values") if isinstance(payload, dict) else None
    return {str(k): ("" if v is None else str(v)) for k, v in (values or {}).items()}


def git_commit() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=20)
        return out.stdout.strip()
    except Exception:
        return ""


def role_scope_prefix(role: str) -> str:
    """`live-odds-worker` -> `LIVE_ODDS_WORKER__`: the prefix a role-scoped key carries in the local file."""
    return role.upper().replace("-", "_") + "__"


def role_local_view(local: dict[str, str], role: str) -> tuple[dict[str, str], list[str]]:
    """The local file as ONE role sees it: global keys, then that role's `ROLE__KEY` overrides.

    The local file applies every key to every role, so a value that legitimately
    differs per role (live-odds-worker's `SYNDICATE_ACTIVE_SPORTS` carries nba/nhl,
    web's does not) could only live in the imported Render snapshot, which a
    re-import overwrites. `LIVE_ODDS_WORKER__SYNDICATE_ACTIVE_SPORTS=...` pins it
    for that role alone `[2026-10-05, lane local-env-role-scoped-pin]`.

    Another role's scoped key is dropped, never exported under its literal name.
    A prefix that names no role is an ordinary key (so a real env key containing
    `__` keeps working).
    """
    prefixes = {r: role_scope_prefix(r) for r in ROLE_ORDER}
    view: dict[str, str] = {}
    scoped: dict[str, str] = {}
    for key, value in local.items():
        owner = next((r for r, p in prefixes.items() if key.startswith(p) and len(key) > len(p)), None)
        if owner is None:
            view[key] = value
        elif owner == role:
            scoped[key[len(prefixes[owner]):]] = value
    view.update(scoped)
    return view, sorted(scoped)


def derive_role_env(
    role: str,
    blueprint: dict[str, list[BlueprintKey]],
    local: dict[str, str],
    settings: Settings,
    *,
    live: dict[str, str] | None = None,
    base_env: dict[str, str] | None = None,
    instance_id: str = "",
) -> tuple[dict[str, str], dict[str, Any]]:
    """Blueprint -> live Render env (if imported) -> local file -> forced.

    The live layer matters: the blueprint was 166 keys behind the live services
    (learnings.md, FORBIDDEN note on render.yaml), and those undeclared keys are
    where most `*_AUTORUN` switches and all venue credentials live."""
    env = dict(os.environ if base_env is None else base_env)
    # A stray RENDER_* in the operator's shell must not leak in.
    for name in list(env):
        if name.startswith("RENDER_") or name == "RENDER":
            env.pop(name, None)
    audit: dict[str, Any] = {"rewritten": [], "local": [], "unset": [], "forced": {}, "live": 0}
    live = live or {}
    # Role-scoped `ROLE__KEY` lines resolve to plain keys for this role only, and
    # beat the same key's global line; every layer below sees the resolved view.
    local, audit["role_scoped"] = role_local_view(local, role)

    for item in blueprint[role]:
        if item.source == "value":
            value = rewrite_path(item.value or "", data_root=settings.data_root)
            if value != item.value:
                audit["rewritten"].append(item.key)
            env[item.key] = value
        elif item.source == "keyvalue":
            env[item.key] = settings.redis_url
        else:  # generate / from_web / sync_false -> live env or the local file decides
            if item.key in live:
                env[item.key] = rewrite_path(str(live[item.key]), data_root=settings.data_root)
            elif item.key in local:
                env[item.key] = local[item.key]
                audit["local"].append(item.key)
            else:
                env.pop(item.key, None)
                audit["unset"].append(item.key)

    # The live service's own env overrides its blueprint declaration: live is
    # what production actually ran.
    for key, value in live.items():
        if key in NEVER_CARRY or value is None:
            continue
        new = rewrite_path(str(value), data_root=settings.data_root)
        if env.get(key) != new:
            audit["live"] += 1
        env[key] = new
        if key in audit["unset"]:
            audit["unset"].remove(key)

    # Local file: explicit operator overrides, applied to every role. With no
    # live import this is also where dashboard-only keys come from.
    for key, value in local.items():
        if key in NEVER_CARRY:
            continue
        env[key] = rewrite_path(value, data_root=settings.data_root)
        if key in audit["unset"]:
            audit["unset"].remove(key)
        if key not in audit["local"]:
            audit["local"].append(key)

    # No cgroup here, so every memory-headroom gate read None and failed CLOSED
    # (chip publish, MLB overview isolation, MLB daily sim -- first native-
    # Windows run, 2026-09-30). Give each role its old Render plan as a ceiling;
    # memory_observability then measures the role's process-tree RSS against
    # it. A default, so local_production.env can still override it.
    if role in PLAN_MEMORY_MB and not str(env.get("SYNDICATE_LOCAL_MEMORY_LIMIT_MB") or "").strip():
        env["SYNDICATE_LOCAL_MEMORY_LIMIT_MB"] = str(PLAN_MEMORY_MB[role])

    forced: dict[str, str] = {
        "SYNDICATE_BOOTSTRAP_ON_START": "0",
        "PYTHONUNBUFFERED": "1",
        "PYTHONIOENCODING": "utf-8",
        "SYNDICATE_LOCAL_PRODUCTION": "1",
        "SYNDICATE_WEB_WORKER_RECYCLE_STAMP": str(settings.run_dir / "web_worker_recycle.stamp"),
    }
    local_web = f"http://127.0.0.1:{settings.port}"
    # Every worker->web URL points at the local web. With these unset the code
    # falls back to the PUBLIC onrender host (live_lens_loop.py
    # _wnba_live_box_base_url, publish_model_scorecard.base_url), which is
    # suspended -- and would be billed egress if it were not.
    forced["SYNDICATE_INTERNAL_WEB_BASE_URL"] = local_web
    forced["SYNDICATE_WNBA_LIVE_BOX_BASE_URL"] = local_web
    forced["SYNDICATE_BASE_URL"] = local_web
    if not settings.publish_loopback:
        env.pop("SYNDICATE_WEB_PUBLISH_URL", None)
    else:
        forced["SYNDICATE_WEB_PUBLISH_URL"] = local_web
    # The service markers are set in BOTH state modes. Without them web is not
    # `_is_render_web_dyno()`, and then syndicate/app.py starts the intelligence
    # and live-refresh loops on first request WITHOUT reading their flags --
    # duplicating refresh-worker's board build on the same disk.
    forced.update(
        {
            "RENDER_SERVICE_NAME": f"local-{role}",
            "RENDER_SERVICE_ID": f"local-{role}",
            "RENDER_INSTANCE_ID": instance_id or f"local-{role}-{int(time.time())}",
        }
    )
    commit = git_commit()
    if commit:
        forced["RENDER_GIT_COMMIT"] = commit
    public = local.get("SYNDICATE_PUBLIC_URL", "").strip()
    if public:
        forced["RENDER_EXTERNAL_URL"] = public
    if settings.state == "redis":
        forced.update(
            {
                "RENDER": "true",
                "SYNDICATE_REFRESH_STATE_BACKEND": "keyvalue",
                "SYNDICATE_REFRESH_STATE_URL": settings.redis_url,
            }
        )
    else:
        forced["SYNDICATE_REFRESH_STATE_BACKEND"] = "filesystem"
        env.pop("SYNDICATE_REQUIRE_HOSTED_STORAGE", None)
        env.pop("SYNDICATE_REFRESH_STATE_URL", None)
    if role == "web":
        forced["PORT"] = str(settings.port)

    if not settings.allow_live_execution:
        forced.update(PAPER_EXECUTION)
        # Only the operator's own file may turn paper execution off; the
        # Render import's value is about LIVE money and does not apply here.
        forced["SYNDICATE_EXECUTION_ENABLED"] = (
            str(local.get("SYNDICATE_EXECUTION_ENABLED") or "").strip() or PAPER_EXECUTION_ENABLED_DEFAULT
        )

    for key, value in forced.items():
        if env.get(key) != value:
            audit["forced"][key] = value
        env[key] = value

    existing = env.get("PYTHONPATH") or ""
    front = [str(REPO_ROOT)]
    # Every line a role prints gets its UTC emission time (scripts/local_logstamp):
    # Render stamped lines, a log file does not, and render_logs --local reads these.
    if str(env.get("SYNDICATE_LOCAL_LOG_TIMESTAMPS", "1")).strip() != "0":
        front.insert(0, str(LOGSTAMP_DIR))
    env["PYTHONPATH"] = os.pathsep.join(front + ([existing] if existing else []))
    return env, audit


def money_is_live(env: dict[str, str]) -> bool:
    return (
        str(env.get("SYNDICATE_EXECUTION_MODE") or "").strip().lower() == "live"
        and str(env.get("SYNDICATE_EXECUTION_LIVE_ARMED") or "").strip().lower() in {"1", "true", "yes", "on"}
    )


SECRET_HINTS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "PRIVATE", "HASH", "URL")


def mask(key: str, value: str) -> str:
    if any(h in key.upper() for h in SECRET_HINTS) and value and not value.startswith(("/", "http://127.", "redis://127.")):
        return f"<set, {len(value)} chars>"
    return value


# --------------------------------------------------------------------------
# role commands
# --------------------------------------------------------------------------


def gunicorn_usable() -> bool:
    # No `shutil.which("gunicorn")`: web is launched as `sys.executable -m
    # gunicorn`, which never needs PATH, and a venv python run without
    # activation (the WSL boot task) has no venv bin/ on PATH -- that check
    # silently fell back to waitress on Linux (first WSL2 run, 2026-10-01).
    if IS_WINDOWS:
        return False
    probe = subprocess.run([sys.executable, "-c", "import gunicorn.util, fcntl"], capture_output=True, timeout=60)
    return probe.returncode == 0


def role_command(role: str, env: dict[str, str], settings: Settings) -> tuple[list[str], str]:
    if role == "web":
        workers = env.get("WEB_CONCURRENCY", "2")
        threads = env.get("GUNICORN_THREADS", "4")
        if gunicorn_usable():
            # render.yaml's startCommand, minus the `sh -c` wrapper. It runs from
            # the repo root, so ./gunicorn.conf.py (memory guard, access-log
            # durations) loads exactly as on Render.
            return (
                [
                    sys.executable, "-m", "gunicorn", "wsgi:application",
                    "--bind", f"{settings.host}:{settings.port}",
                    "--workers", workers,
                    "--threads", threads,
                    "--timeout", env.get("GUNICORN_TIMEOUT", "60"),
                    "--graceful-timeout", env.get("GUNICORN_GRACEFUL_TIMEOUT", "30"),
                    "--keep-alive", env.get("GUNICORN_KEEPALIVE", "5"),
                    "--access-logfile", "-",
                ],
                "gunicorn",
            )
        # Windows: gunicorn imports fcntl and cannot run. waitress is a
        # production WSGI server (threaded, one process); give it the same
        # number of request slots web had (workers x threads).
        slots = max(4, int(workers or 1) * int(threads or 1))
        return (
            [
                sys.executable, "-m", "waitress",
                f"--host={settings.host}", f"--port={settings.port}",
                f"--threads={slots}", "--channel-timeout=120",
                "wsgi:application",
            ],
            "waitress",
        )
    if role == "refresh-worker":
        return [sys.executable, "scripts/run_refresh_worker.py"], "python"
    if role == "live-odds-worker":
        return [sys.executable, "scripts/run_live_odds_refresh_worker.py"], "python"
    raise ValueError(role)


# --------------------------------------------------------------------------
# redis
# --------------------------------------------------------------------------


def _redis_host_port(url: str) -> tuple[str, int]:
    from urllib.parse import urlparse

    parsed = urlparse(url)
    return parsed.hostname or "127.0.0.1", int(parsed.port or 6379)


def port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def redis_ping(url: str) -> tuple[bool, str]:
    try:
        import redis

        client = redis.Redis.from_url(url, socket_timeout=3, socket_connect_timeout=3)
        client.ping()
        info = client.info("server")
        return True, f"redis {info.get('redis_version', '?')}"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def find_redis_server() -> str | None:
    for name in ("redis-server", "memurai", "valkey-server"):
        found = shutil.which(name)
        if found:
            return found
    return None


def start_local_redis(settings: Settings) -> subprocess.Popen | None:
    """Start a persistent, loopback-only redis if nothing answers. Returns the
    process when WE started it (so `up` stops it on exit), else None."""
    ok, _ = redis_ping(settings.redis_url)
    if ok:
        return None
    host, port = _redis_host_port(settings.redis_url)
    if host not in {"127.0.0.1", "localhost"}:
        raise SystemExit(f"redis at {settings.redis_url} does not answer, and it is not local so it cannot be started here.")
    binary = find_redis_server()
    if not binary:
        raise SystemExit(
            "no redis answering at %s and no redis-server/memurai on PATH.\n"
            "  Windows: install Memurai Developer (redis-compatible) or run redis in WSL/Docker,\n"
            "           or rerun with --state file (see the runbook for what that turns off).\n"
            "  Linux:   apt install redis-server" % settings.redis_url
        )
    redis_dir = settings.home / "redis"
    redis_dir.mkdir(parents=True, exist_ok=True)
    log = (settings.logs_dir / "redis.log").open("a", encoding="utf-8")
    proc = subprocess.Popen(
        [
            binary, "--bind", "127.0.0.1", "--port", str(port), "--dir", str(redis_dir),
            "--appendonly", "yes", "--save", "300 10", "--protected-mode", "yes",
        ],
        stdout=log, stderr=subprocess.STDOUT,
    )
    for _ in range(40):
        if redis_ping(settings.redis_url)[0]:
            print(f"  [redis] started pid={proc.pid} dir={redis_dir}", flush=True)
            return proc
        if proc.poll() is not None:
            break
        time.sleep(0.25)
    raise SystemExit(f"redis-server did not come up; see {settings.logs_dir / 'redis.log'}")


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------


def default_home() -> Path:
    override = os.environ.get("SYNDICATE_LOCAL_HOME", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    if IS_WINDOWS:
        # NOT under OneDrive: the data root is tens of GB of churning files.
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        return Path(base) / "SyndicateProd"
    return Path.home() / "syndicate-prod"


def settings_from_args(args: argparse.Namespace) -> Settings:
    home = Path(args.home).expanduser().resolve() if args.home else default_home()
    return Settings(
        home=home,
        port=int(args.port),
        host=str(args.host),
        state=str(args.state),
        redis_url=str(args.redis_url),
        allow_live_execution=bool(getattr(args, "allow_live_execution", False)),
        publish_loopback=bool(getattr(args, "publish_loopback", False)),
    )


def template_text(blueprint: dict[str, list[BlueprintKey]]) -> str:
    needed: dict[str, set[str]] = {}
    for role, items in blueprint.items():
        for item in items:
            if item.source in {"generate", "from_web", "sync_false"}:
                needed.setdefault(item.key, set()).add(role)
    lines = [
        "# Syndicate local production -- secrets and dashboard-only settings.",
        "# NEVER commit this file. Read by scripts/local_production.py for every role.",
        "# Blank or commented-out = the key is ABSENT, and absent is not always 'off':",
        "# check the code default before relying on it (CLAUDE.md #284).",
        "",
        "# --- declared in render.yaml without a value (sync: false / generated) ---",
    ]
    for key in sorted(needed):
        roles = ",".join(sorted(needed[key]))
        default = ""
        if key == "ADMIN_TOKEN":
            import secrets

            default = secrets.token_hex(24)
        lines.append(f"# roles: {roles}")
        lines.append(f"{key}={default}" if default else f"# {key}=")
    lines += ["", "# --- read by the code, set only in the Render dashboard ---"]
    for key, why in DASHBOARD_ONLY_KEYS.items():
        lines.append(f"# {why}")
        lines.append(f"# {key}=")
    lines += [
        "",
        "# --- local-only ---",
        "# Public URL if you expose the site (cloudflared etc.); becomes RENDER_EXTERNAL_URL.",
        "# SYNDICATE_PUBLIC_URL=https://syndicate.example.com",
        "# cloudflared named-tunnel token: `up` then also runs the tunnel as a role.",
        "# CLOUDFLARED_TUNNEL_TOKEN=",
        "",
    ]
    return "\n".join(lines)


def cmd_init(args: argparse.Namespace) -> int:
    settings = settings_from_args(args)
    for path in (settings.home, settings.data_root, settings.logs_dir, settings.run_dir):
        path.mkdir(parents=True, exist_ok=True)
    if settings.env_file.exists() and not args.force:
        print(f"kept existing {settings.env_file} (use --force to rewrite the template)")
    else:
        settings.env_file.write_text(template_text(load_blueprint()), encoding="utf-8")
        try:
            os.chmod(settings.env_file, 0o600)
        except OSError:
            pass
        print(f"wrote {settings.env_file} -- fill in the keys you have, then run `doctor`.")
    print(f"home      {settings.home}")
    print(f"data root {settings.data_root}")
    return 0


def checkout_depth_ok(repo_root: Path) -> bool:
    """True when `repo_root_from` (parents[3]) exists for pipeline/*.py (#313)."""
    return len((Path(repo_root) / "pipeline" / "x.py").parents) > 3


def _check(ok: bool, label: str, detail: str = "", *, warn: bool = False) -> bool:
    tag = "OK  " if ok else ("WARN" if warn else "FAIL")
    print(f"  [{tag}] {label}" + (f" -- {detail}" if detail else ""))
    return ok or warn


def cmd_doctor(args: argparse.Namespace) -> int:
    settings = settings_from_args(args)
    print(f"LOCAL PRODUCTION DOCTOR   home={settings.home}   state={settings.state}")
    ok = True
    ok &= _check(sys.version_info[:2] == (3, 11), "python 3.11 (render.yaml PYTHON_VERSION=3.11.9)",
                 platform.python_version(), warn=sys.version_info[:2] >= (3, 11))
    # `#313`: pipeline/intelligence_state.py does `repo_root_from(__file__)`,
    # which is `parents[3]` -- two levels ABOVE the repo. A checkout at
    # C:\Syndicate raises IndexError on import and web never starts (first
    # native-Windows run, 2026-09-30). On Render it resolves to /opt/render.
    depth_ok = checkout_depth_ok(REPO_ROOT)
    ok &= _check(depth_ok, "checkout depth",
                 str(REPO_ROOT) if depth_ok else
                 f"{REPO_ROOT} is too shallow: web crashes on import (#313). "
                 "Clone at least two directories below the drive root, e.g. C:\\SyndicateProd\\repo\\Syndicate")
    missing = []
    for module in ("flask", "redis", "pandas", "numpy", "onnxruntime", "yaml", "psutil"):
        try:
            __import__(module)
        except Exception:
            missing.append(module)
    web_server = "gunicorn" if gunicorn_usable() else "waitress"
    try:
        __import__(web_server)
    except Exception:
        missing.append(web_server)
    ok &= _check(not missing, "python packages", "missing: " + ", ".join(missing) + "  -> pip install -r requirements.txt psutil waitress pyyaml" if missing else f"web server: {web_server}")

    try:
        blueprint = load_blueprint()
        _check(True, "render.yaml parsed", ", ".join(f"{r}={len(blueprint[r])} keys" for r in ROLE_ORDER))
    except Exception as exc:  # noqa: BLE001
        _check(False, "render.yaml parsed", str(exc))
        return 1

    local = parse_env_file(settings.env_file)
    imported = {r: load_live_env(settings, r) for r in ROLE_ORDER}
    _check(all(imported.values()), "live Render env imported",
           ", ".join(f"{r}={len(imported[r])} keys" for r in ROLE_ORDER) if all(imported.values())
           else "no -- run `import-render-env` (needs RENDER_API_KEY) for full parity; blueprint-only until then",
           warn=True)
    ok &= _check(settings.env_file.is_file(), "secrets file", str(settings.env_file) if settings.env_file.is_file() else "missing -- run `init`")
    for key, why in (
        ("ADMIN_TOKEN", "ops API, artifact export/publish"),
        ("ODDS_API_KEY", "every odds refresh"),
    ):
        present = bool(local.get(key) or imported["web"].get(key) or any(i.key == key and i.value for i in blueprint["web"]))
        ok &= _check(present, f"{key}", why if present else f"ABSENT -- {why} will not work")
    for key in ("ANTHROPIC_API_KEY", "KALSHI_API_KEY_ID", "POLYMARKET_US_API_KEY_ID", "CFBD_API_KEY", "SYNDICATE_PORTFOLIO_USERNAME"):
        have = bool(local.get(key) or any(imported[r].get(key) for r in ROLE_ORDER))
        _check(have, key, "set" if have else "absent (feature degrades, not fatal)", warn=True)

    unset: dict[str, list[str]] = {}
    for role in ROLE_ORDER:
        _, audit = derive_role_env(role, blueprint, local, settings, live=load_live_env(settings, role))
        for key in audit["unset"]:
            unset.setdefault(key, []).append(role)
    if unset:
        print("  [INFO] blueprint keys with no local value (absent on these roles):")
        for key in sorted(unset):
            print(f"           {key}  ({', '.join(unset[key])})")

    if settings.state == "redis":
        good, detail = redis_ping(settings.redis_url)
        if not good:
            good = find_redis_server() is not None
            detail = "not running, but a server binary is on PATH -- `up` will start it" if good else detail + " and no redis-server/memurai on PATH"
        ok &= _check(good, f"state store {settings.redis_url}", detail)
    else:
        _check(True, "state store: filesystem",
               "RENDER/REQUIRE_HOSTED_STORAGE cleared -> request-path compute guard is warn-only, portfolio auth only if creds set",
               warn=True)

    web_host = settings.host
    ok &= _check(not port_open(web_host if web_host != "0.0.0.0" else "127.0.0.1", settings.port), f"port {settings.port} free",
                 "" if not port_open("127.0.0.1", settings.port) else "something is already listening")

    settings.home.mkdir(parents=True, exist_ok=True)
    free_gb = shutil.disk_usage(settings.home).free / 1e9
    ok &= _check(free_gb >= 60, "disk free at home", f"{free_gb:.0f} GB (Render gave each service 50 GB)", warn=free_gb >= 20)
    try:
        import psutil

        total_gb = psutil.virtual_memory().total / 1e9
        _check(total_gb >= 12, "RAM", f"{total_gb:.1f} GB (Render plans summed to 8 GB; 12+ leaves room for the OS)", warn=True)
    except Exception:
        pass
    if "onedrive" in str(settings.home).lower():
        _check(False, "home is under OneDrive", "move it (SYNDICATE_LOCAL_HOME) -- OneDrive syncing a live data root is unsafe", warn=True)
    if IS_WINDOWS:
        _check(False, "native Windows",
               "WSL2 (Ubuntu) is the supported host: on native Windows os.replace onto an open "
               "file fails intermittently, gunicorn does not run (waitress serves web), and "
               "memory guards read nothing. See the runbook.", warn=True)
        _check(True, "Windows sleep", "disable sleep/Modern Standby on AC power or the workers stall (see runbook)", warn=True)

    data_seeded = (settings.data_root / "mlb_source").exists()
    _check(data_seeded, "data root seeded", str(settings.data_root) if data_seeded else "not yet -- `up` seeds it from the checkout first", warn=True)
    if not settings.allow_live_execution:
        print("  [INFO] money: PAPER (live execution needs `up --allow-live-execution` AND the env file set to live)")
    print()
    print("DOCTOR: " + ("READY" if ok else "NOT READY"))
    return 0 if ok else 1


def cmd_env(args: argparse.Namespace) -> int:
    settings = settings_from_args(args)
    blueprint = load_blueprint()
    local = parse_env_file(settings.env_file)
    env, audit = derive_role_env(args.role, blueprint, local, settings, live=load_live_env(settings, args.role), base_env={})
    for key in sorted(env):
        print(f"{key}={mask(key, env[key]) if not args.unmask else env[key]}")
    print(f"# rewritten paths: {len(audit['rewritten'])}  local: {len(audit['local'])}  unset: {audit['unset']}", file=sys.stderr)
    print(f"# forced: {sorted(audit['forced'])}", file=sys.stderr)
    return 0


def cmd_import_render_env(args: argparse.Namespace) -> int:
    """Pull each suspended service's LIVE env through the Render API into
    <home>/render_env/<role>.json. Plaintext, because a production run needs
    the real values; it lives outside the repo, owner-readable only, and is
    never printed. Reads only -- this never writes to Render."""
    settings = settings_from_args(args)
    from scripts.snapshot_render_env import _api_key, fetch_env

    api_key = _api_key(args.env_file or "")
    out_dir = settings.home / "render_env"
    out_dir.mkdir(parents=True, exist_ok=True)
    for role, service_id in RENDER_SERVICE_IDS.items():
        try:
            values, pages = fetch_env(service_id, api_key)
        except Exception as exc:  # noqa: BLE001
            print(f"  [{role}] FAILED {type(exc).__name__}: {exc}")
            continue
        path = live_env_path(settings, role)
        path.write_text(
            json.dumps(
                {
                    "service_id": service_id,
                    "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                    "pages": pages,
                    "values": values,
                },
                indent=1,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        print(f"  [{role}] {len(values)} keys ({pages} page(s)) -> {path}")
    return 0


def run_bootstrap(settings: Settings, blueprint: dict[str, list[BlueprintKey]], local: dict[str, str]) -> int:
    """Seed the shared data root from the checkout ONCE, before any role starts.
    Same script and env Render ran at boot (seed-only: existing files are never
    overwritten), but one pass instead of three racing ones on one disk."""
    env, _ = derive_role_env("refresh-worker", blueprint, local, settings, live=load_live_env(settings, "refresh-worker"))
    env["SYNDICATE_BOOTSTRAP_ON_START"] = "1"
    settings.data_root.mkdir(parents=True, exist_ok=True)
    (settings.data_root / "reports").mkdir(parents=True, exist_ok=True)
    started = time.time()
    print(f"  [bootstrap] seeding {settings.data_root} from {REPO_ROOT / 'data'} ...", flush=True)
    with (settings.logs_dir / "bootstrap.log").open("a", encoding="utf-8") as log:
        log.write(f"\n==== bootstrap {dt.datetime.now(dt.timezone.utc).isoformat()} ====\n")
        log.flush()
        rc = subprocess.run(
            [sys.executable, "scripts/bootstrap_data_root.py"], cwd=str(REPO_ROOT), env=env, stdout=log, stderr=subprocess.STDOUT
        ).returncode
    print(f"  [bootstrap] rc={rc} in {time.time() - started:.0f}s (log {settings.logs_dir / 'bootstrap.log'})", flush=True)
    return rc


@dataclass
class Supervised:
    name: str
    command: list[str]
    env: dict[str, str]
    log_path: Path
    process: subprocess.Popen | None = None
    started_at: float = 0.0
    restarts: int = 0
    backoff: float = 5.0


@dataclass(frozen=True)
class ScheduledJob:
    name: str
    hour: int  # UTC
    minute: int  # UTC
    argv: tuple[str, ...]  # after sys.executable; "{home}" is replaced with the local home
    weekday: int | None = None  # None = daily; 0 = Monday (Render cron `* * 1`)


# Render cron jobs that were created in the dashboard, not in render.yaml, plus
# the local-only backup. Render crons do not catch up; a laptop can be asleep at
# the scheduled minute, so each job runs ONCE on its UTC day at the first
# supervisor tick at or after its time. Every job gets refresh-worker's env (one
# shared disk, so the local data root IS the one each cron used to publish to).
SCHEDULED_JOBS: tuple[ScheduledJob, ...] = (
    # `sim-input-reports` crn-dafj4ie7bikc738q9ol0, `0 7 * * *` (state_worker.md).
    # Production ran `--publish --verify` from a cron with an EMPTY disk, so it
    # pulled basketball's inputs from web first. Here the inputs are already on
    # the shared disk (`--no-pull`), and publishing onto that disk is a no-op.
    ScheduledJob("sim-input-reports", 7, 0, ("scripts/publish_sim_input_reports.py", "--no-pull")),
    # `ci-suite` crn-dafg4h0u01pc73aavs6g, `0 8 * * *`. Runs in its own checkout
    # with a scrubbed env (`ci-run`) -- never against the fleet's Redis or data.
    ScheduledJob("ci-suite", 8, 0, ("scripts/local_production.py", "--home", "{home}", "ci-run")),
    # `data-backup`: local-only. Render kept the three disks; here the data root
    # is the ONLY copy of everything written since 2026-09-30.
    ScheduledJob("data-backup", 9, 15, ("scripts/local_production.py", "--home", "{home}", "backup")),
    # `mlb-season-artifacts` crn-dafffnn40ujc73b349pg, `0 9 * * 1`. Without
    # `--publish` it builds straight into the data root, which is the disk
    # refresh-worker's `pull_season_artifacts` would have copied them to.
    ScheduledJob("mlb-season-artifacts", 9, 0, ("scripts/publish_mlb_season_artifacts.py",), weekday=0),
    # `model-scorecard` crn-dam0ao942hec73cge0rg, `30 11 * * *` (state_model.md).
    # Production ran `--publish --verify`; `--publish` is an HTTP self-publish
    # onto the disk `write()` already wrote to, so it is dropped here.
    ScheduledJob("model-scorecard", 11, 30, ("scripts/publish_model_scorecard.py", "--verify")),
    # `movement-by-sport` (lane `layer2-freshness-1h`, 2026-10-02, user "go ahead
    # with 1"): per sport, does the MARKET's move since a price was first seen
    # predict the close beyond fair value? Read-only on the quote log; writes
    # reports/intelligence/movement_by_sport/<date>.json. A sport gets its own
    # movement weight only when this reads `momentum`/`reversion` on >= 20 games.
    # 10:30Z: after the night's games are final and after the 09:15 backup.
    ScheduledJob("movement-by-sport", 10, 30, ("scripts/consensus_movement_by_sport.py",)),
    # `ncaab-team-ratings` (lane `intelligence-evidence-coverage`, 2026-10-07,
    # user "build the NCAAB ratings producer"): adjusted O/D/tempo from ESPN box
    # scores into ncaab_source/data/processed/team_ratings_<season>_asof_*.csv,
    # incremental (only new finals are fetched). 10:45Z: after the night's
    # games are final; in the offseason it re-reads a complete season and
    # fetches nothing.
    ScheduledJob("ncaab-team-ratings", 10, 45, ("scripts/build_ncaab_team_ratings.py",)),
    # `mlb-matchup-splits` + `nfl-defense-vs-position` (lane
    # `intelligence-evidence-coverage`, phase 2, 2026-10-08, user "focus on
    # recency and matchups"): batter vs LHP/RHP / vs team + the full-season
    # batter-game log from the raw Statcast pitches (~21 s, 68 MB), and what
    # each NFL defense allows per position from nflverse pbp + roster. Both
    # write dated files the board's recency/matchup sentence reads.
    ScheduledJob("mlb-matchup-splits", 10, 50, ("scripts/build_mlb_matchup_splits.py",)),
    ScheduledJob("nfl-defense-vs-position", 10, 55, ("scripts/build_nfl_defense_vs_position.py",)),
    # NBA / WNBA: what each team allows to G/F/C per game, one table per
    # (season, phase) -- regular season and playoffs never mixed (~9 s).
    ScheduledJob("basketball-defense-vs-position", 11, 0, ("scripts/build_basketball_defense_vs_position.py",)),
    # NHL this-season team table for explanations ONLY (user 2026-10-08: "advanced
    # data that includes this season"): writes nhl_team_season_to_date_<season>.csv,
    # never a `<stem>_<season>.csv` the sim loaders prefer. Cached payloads: ~3 requests a new game.
    ScheduledJob("nhl-season-to-date", 11, 5, ("scripts/build_nhl_season_to_date.py",)),
    # NHL: what each team allows to opposing forwards / defensemen per game (this
    # season's cached box scores, no fetching); after nhl-season-to-date fills the cache.
    ScheduledJob("nhl-defense-vs-position", 11, 10, ("scripts/build_nhl_defense_vs_position.py",)),
    # Soccer per-match player log (ESPN summaries; incremental -- one request per new
    # final): what soccer prop recency / vs-opponent history reads before live boxes.
    ScheduledJob("soccer-player-match-log", 11, 15, ("scripts/build_soccer_player_match_log.py",)),
)


def job_is_due(job: ScheduledJob, now: dt.datetime, last_run_date: str | None) -> bool:
    if last_run_date == now.date().isoformat():
        return False
    if job.weekday is not None and now.weekday() != job.weekday:
        return False
    return (now.hour, now.minute) >= (job.hour, job.minute)


def run_due_jobs(
    settings: "Settings",
    env: dict[str, str],
    running: dict[str, subprocess.Popen],
    *,
    now: dt.datetime | None = None,
    jobs: Sequence[ScheduledJob] = SCHEDULED_JOBS,
) -> None:
    state_path = settings.run_dir / "scheduled_jobs.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.is_file() else {}
    except ValueError:
        state = {}
    now = now or dt.datetime.now(dt.timezone.utc)
    today = now.date().isoformat()
    for job in jobs:
        name = job.name
        proc = running.get(name)
        if proc is not None:
            if proc.poll() is None:
                continue
            print(f"  [job:{name}] finished rc={proc.returncode}", flush=True)
            state.setdefault(name, {})["last_rc"] = proc.returncode
            state[name]["finished_at"] = now.isoformat()
            running.pop(name, None)
        if not job_is_due(job, now, state.get(name, {}).get("last_run_date")):
            continue
        argv = [part.replace("{home}", str(settings.home)) for part in job.argv]
        log_path = settings.logs_dir / f"job-{name}.log"
        rotate_log(log_path)
        handle = log_path.open("a", encoding="utf-8", errors="replace")
        handle.write(f"\n==== {name} {now.isoformat()} ====\n")
        handle.flush()
        running[name] = subprocess.Popen([sys.executable, *argv], cwd=str(REPO_ROOT), env=env, stdout=handle, stderr=subprocess.STDOUT)
        state[name] = {"last_run_date": today, "started_at": now.isoformat(), "pid": running[name].pid}
        print(f"  [job:{name}] started pid={running[name].pid} log={log_path}", flush=True)
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _spawn(item: Supervised) -> None:
    item.log_path.parent.mkdir(parents=True, exist_ok=True)
    rotate_log(item.log_path)
    handle = item.log_path.open("a", encoding="utf-8", errors="replace")
    handle.write(f"\n==== start {dt.datetime.now(dt.timezone.utc).isoformat()} restarts={item.restarts} cmd={' '.join(item.command)} ====\n")
    handle.flush()
    kwargs: dict[str, Any] = {}
    if IS_WINDOWS:
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    else:
        kwargs["start_new_session"] = True
    item.process = subprocess.Popen(item.command, cwd=str(REPO_ROOT), env=item.env, stdout=handle, stderr=subprocess.STDOUT, **kwargs)
    item.started_at = time.time()
    print(f"  [{item.name}] pid={item.process.pid} log={item.log_path}", flush=True)


def rotate_log(path: Path, max_bytes: int = 200 * 1024 * 1024, keep: int = 5) -> None:
    try:
        if not path.is_file() or path.stat().st_size < max_bytes:
            return
        for index in range(keep - 1, 0, -1):
            older = path.with_name(f"{path.name}.{index}")
            if older.exists():
                older.replace(path.with_name(f"{path.name}.{index + 1}"))
        path.replace(path.with_name(f"{path.name}.1"))
    except OSError:
        pass


def rotate_running_log(path: Path, max_bytes: int = 200 * 1024 * 1024, keep: int = 5) -> bool:
    """Rotate a log a LIVE role is still appending to (copy, then truncate).

    `rotate_log` renames, which only works at spawn: a running role keeps its
    handle on the renamed file. refresh-worker does not exit on its own, so its
    log grew 108 MB in 3.5 h with nothing ever rotating it (2026-10-01). The
    roles' handles are opened in append mode, so after the truncate their next
    write lands at the new end of file. Lines written between the copy and the
    truncate are lost -- a few lines once per 200 MB."""
    try:
        if not path.is_file() or path.stat().st_size < max_bytes:
            return False
        for index in range(keep - 1, 0, -1):
            older = path.with_name(f"{path.name}.{index}")
            if older.exists():
                older.replace(path.with_name(f"{path.name}.{index + 1}"))
        shutil.copyfile(path, path.with_name(f"{path.name}.1"))
        with path.open("r+b") as handle:
            handle.truncate(0)
        return True
    except OSError:
        return False


def ensure_redis_durable(url: str) -> str:
    """Turn on AOF on an ALREADY-RUNNING redis that `up` did not start.

    `start_local_redis` starts its own redis with `--appendonly yes`, but on the
    WSL host apt's systemd redis-server answers first, so `up` reuses it with the
    distro defaults: appendonly=no, RDB `save 3600 1 300 100 60 10000`
    (measured 2026-10-01) -- a crash could drop up to an hour of state. Render
    keyvalue is persistent. CONFIG REWRITE makes it survive a redis restart; if
    the config file is not writable the change still holds until then."""
    try:
        import redis

        client = redis.Redis.from_url(url, socket_timeout=5, socket_connect_timeout=5)
        current = str(client.config_get("appendonly").get("appendonly", "")).lower()
        if current == "yes":
            return "aof=already-on"
        client.config_set("appendonly", "yes")
        try:
            client.config_rewrite()
            return "aof=enabled+persisted"
        except Exception as exc:  # noqa: BLE001
            return f"aof=enabled (runtime only; CONFIG REWRITE failed: {type(exc).__name__})"
    except Exception as exc:  # noqa: BLE001
        return f"aof=unknown ({type(exc).__name__}: {exc})"


def _terminate(process: subprocess.Popen | None, timeout: float = 30.0) -> None:
    if process is None or process.poll() is not None:
        return
    try:
        if IS_WINDOWS:
            process.send_signal(signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
        else:
            os.killpg(process.pid, signal.SIGTERM)
    except Exception:
        try:
            process.terminate()
        except Exception:
            pass
    try:
        process.wait(timeout=timeout)
    except Exception:
        try:
            if IS_WINDOWS:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)], capture_output=True)
            else:
                os.killpg(process.pid, signal.SIGKILL)
        except Exception:
            process.kill()


def wait_healthy(settings: Settings, timeout: float) -> bool:
    deadline = time.time() + timeout
    url = f"http://127.0.0.1:{settings.port}/healthz"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                if response.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(2)
    return False


def cmd_up(args: argparse.Namespace) -> int:
    settings = settings_from_args(args)
    for path in (settings.home, settings.data_root, settings.logs_dir, settings.run_dir):
        path.mkdir(parents=True, exist_ok=True)
    pidfile = settings.run_dir / PIDFILE_NAME
    if pidfile.is_file():
        try:
            prior = json.loads(pidfile.read_text(encoding="utf-8"))
            import psutil

            if psutil.pid_exists(int(prior.get("supervisor_pid") or 0)):
                raise SystemExit(f"already running (supervisor pid {prior['supervisor_pid']}). `down` first.")
        except (ValueError, ImportError):
            pass

    blueprint = load_blueprint()
    local = parse_env_file(settings.env_file)
    if not settings.env_file.is_file():
        raise SystemExit(f"no {settings.env_file}. Run `init` first.")
    roles = [r for r in ROLE_ORDER if r in args.roles]

    live_money = settings.allow_live_execution and any(
        money_is_live({**load_live_env(settings, r), **local}) for r in roles
    )
    print(f"LOCAL PRODUCTION UP   home={settings.home}   state={settings.state}   port={settings.port}   commit={git_commit()[:12]}")
    print(f"  money: {'LIVE -- real orders can be placed' if live_money else 'paper'}", flush=True)

    redis_proc = start_local_redis(settings) if settings.state == "redis" else None
    if settings.state == "redis":
        print(f"  [redis] {ensure_redis_durable(settings.redis_url)}", flush=True)

    if not args.skip_bootstrap:
        rc = run_bootstrap(settings, blueprint, local)
        if rc != 0:
            print("  [bootstrap] non-zero exit -- continuing; roles read whatever is present (see log)", flush=True)

    boot = int(time.time())
    items: list[Supervised] = []
    for role in roles:
        env, audit = derive_role_env(role, blueprint, local, settings, live=load_live_env(settings, role), instance_id=f"local-{role}-{boot}")
        command, server = role_command(role, env, settings)
        if role == "web" and server == "waitress":
            print("  [web] waitress (gunicorn cannot run on Windows). Same app, one process, threaded.", flush=True)
        if audit["unset"]:
            print(f"  [{role}] {len(audit['unset'])} blueprint key(s) absent locally: {', '.join(audit['unset'])}", flush=True)
        items.append(Supervised(role, command, env, settings.logs_dir / f"{role}.log"))
    token = local.get("CLOUDFLARED_TUNNEL_TOKEN", "").strip()
    if token and not args.no_tunnel and shutil.which("cloudflared"):
        tunnel_env = dict(os.environ)
        tunnel_env["TUNNEL_TOKEN"] = token
        items.append(Supervised("tunnel", ["cloudflared", "tunnel", "--no-autoupdate", "run"], tunnel_env, settings.logs_dir / "tunnel.log"))

    stopping = {"flag": False}

    def _stop(*_: Any) -> None:
        stopping["flag"] = True

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    if IS_WINDOWS and hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, _stop)  # type: ignore[attr-defined]

    def _write_pidfile() -> None:
        pidfile.write_text(
            json.dumps(
                {
                    "supervisor_pid": os.getpid(),
                    "started_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                    "port": settings.port,
                    "state": settings.state,
                    "roles": {i.name: (i.process.pid if i.process else None) for i in items},
                    "restarts": {i.name: i.restarts for i in items},
                    "redis_pid": redis_proc.pid if redis_proc else None,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    jobs: dict[str, subprocess.Popen] = {}
    try:
        # web first, workers after it answers: the workers' first tick reads
        # state web may still be seeding, and a worker publish/pull against a
        # dead web only produces noise.
        for item in items:
            _spawn(item)
            if item.name == "web":
                healthy = wait_healthy(settings, timeout=float(args.web_start_timeout))
                print(f"  [web] /healthz {'200' if healthy else 'NOT answering yet -- starting workers anyway'}", flush=True)
        _write_pidfile()
        job_env = next((i.env for i in items if i.name == "refresh-worker"), None)
        stop_file = settings.run_dir / "stop"
        stop_file.unlink(missing_ok=True)
        last_rotation_check = 0.0
        while not stopping["flag"]:
            if stop_file.exists():
                stop_file.unlink(missing_ok=True)
                break
            if time.time() - last_rotation_check >= 60:
                last_rotation_check = time.time()
                for item in items:
                    if rotate_running_log(item.log_path):
                        print(f"  [{item.name}] log rotated (copy+truncate) at 200 MB", flush=True)
            if job_env is not None and not args.no_jobs:
                try:
                    run_due_jobs(settings, job_env, jobs)
                except Exception as exc:  # noqa: BLE001
                    print(f"  [jobs] {type(exc).__name__}: {exc}", flush=True)
            for item in items:
                if item.process is not None and item.process.poll() is None:
                    continue
                code = item.process.poll() if item.process else None
                ran = time.time() - item.started_at
                # A role that stayed up 10+ minutes gets a fresh backoff; one
                # that crash-loops backs off to 5 minutes rather than burning
                # CPU (and API quota) on restarts.
                item.backoff = 5.0 if ran > 600 else min(item.backoff * 2, 300.0)
                print(f"  [{item.name}] exited code={code} after {ran:.0f}s -- restarting in {item.backoff:.0f}s", flush=True)
                verdict = note_role_exit(settings, local, item.name, code, ran)
                if verdict:
                    print(f"  [{item.name}] {verdict}", flush=True)
                deadline = time.time() + item.backoff
                while time.time() < deadline and not stopping["flag"]:
                    time.sleep(1)
                if stopping["flag"]:
                    break
                item.restarts += 1
                if item.name in ROLE_ORDER:
                    item.env["RENDER_INSTANCE_ID"] = f"local-{item.name}-{int(time.time())}"
                _spawn(item)
                _write_pidfile()
            time.sleep(2)
    finally:
        print("  stopping roles ...", flush=True)
        for proc in jobs.values():
            _terminate(proc)
        for item in reversed(items):
            _terminate(item.process)
        if redis_proc is not None:
            _terminate(redis_proc, timeout=15)
        pidfile.unlink(missing_ok=True)
        print("  stopped.", flush=True)
    return 0


#: Roles whose signal deaths are checked against a deploy claim. The refresh-
#: worker is the one a stray restart hurts: it kills the in-flight board build
#: and the restart pays a ~20 min cold ranking_records rebuild (measured
#: 2026-10-07, five unannounced restarts in one afternoon kept the board stale).
CLAIM_GUARDED_ROLES = ("refresh-worker",)
ROLE_RESTARTS_LOG = "role_restarts.jsonl"
_CLAIM_DEFAULT_TTL_SECONDS = 45 * 60


def deploy_claim_dir(local: dict[str, str]) -> Path:
    """Where `scripts/deploy_claim.py` writes claims, as seen from THIS host.

    The claims live in the primary Windows tree; the fleet runs from a WSL
    checkout whose own `.syndicate/deploy_claims` never receives one, so the
    fleet sets `SYNDICATE_DEPLOY_CLAIM_DIR` to the `/mnt/c/...` path."""
    override = _setting(local, "SYNDICATE_DEPLOY_CLAIM_DIR")
    if override:
        return Path(override).expanduser()
    return REPO_ROOT / ".syndicate" / "deploy_claims"


def active_role_claim(claim_dir: Path, role: str, *, now: float | None = None) -> dict | None:
    """The unexpired claim on `role`, else None. Same file and TTL rule as
    deploy_claim.py. Missing, expired AND unreadable all read as unclaimed --
    an unknown claim must not default to the permissive answer."""
    try:
        claim = json.loads((claim_dir / f"{role}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(claim, dict):
        return None
    try:
        age = (time.time() if now is None else now) - float(claim.get("acquired_at") or 0)
        ttl = float(claim.get("ttl_seconds") or _CLAIM_DEFAULT_TTL_SECONDS)
    except (TypeError, ValueError):
        return None
    return None if age > ttl else claim


def _signal_name(code: int | None) -> str | None:
    """The signal a role died of, from a Popen returncode (-N) or a shell's 128+N."""
    if code is None:
        return None
    number = -code if code < 0 else code - 128 if code in (128 + 9, 128 + 15) else 0
    if number <= 0:
        return None
    try:
        return signal.Signals(number).name
    except ValueError:
        return f"SIG{number}"


def record_role_event(settings: Settings, local: dict[str, str], role: str, event: str, **fields: Any) -> dict:
    """Check `role`'s claim, append one JSON line to logs/role_restarts.jsonl, return it."""
    claim = active_role_claim(deploy_claim_dir(local), role)
    entry = {
        "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "role": role,
        "event": event,
        "claimed": claim is not None,
        "holder": (claim or {}).get("holder"),
        **fields,
    }
    try:
        settings.logs_dir.mkdir(parents=True, exist_ok=True)
        with (settings.logs_dir / ROLE_RESTARTS_LOG).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")
    except OSError:
        pass
    return entry


def note_role_exit(settings: Settings, local: dict[str, str], role: str, code: int | None, ran_s: float) -> str | None:
    """A guarded role exited without the supervisor stopping it: say whether a claim
    covered it. The exit already happened -- this cannot refuse it, only make it
    impossible to do silently. SIGKILL can also be the kernel OOM killer.

    ANY exit counts, not only a signal death: the refresh-worker traps SIGTERM and
    exits 0, so a manual `kill -TERM` reads `code=0` (measured 2026-10-07 19:14 CT,
    `exited code=0 after 17334s`). A signal-only check missed exactly the restarts
    it was written for."""
    if role not in CLAIM_GUARDED_ROLES or code is None:
        return None
    sig = _signal_name(code)
    entry = record_role_event(settings, local, role, "exit", code=code, signal=sig, ran_s=round(ran_s))
    how = f"signal={sig}" if sig else f"code={code}"
    if entry["claimed"]:
        return f"CLAIMED_RESTART {how} holder={entry['holder']}"
    hint = " (or the OOM killer)" if sig == "SIGKILL" else (" (graceful TERM, or a crash)" if not sig else "")
    return (
        f"UNCLAIMED_RESTART {how}{hint} -- no unexpired deploy claim on {role}. "
        f"Restart only under `deploy_claim.py acquire --service {role}` + check_deploy_safety, "
        f"right after a save (learnings.md). Logged to {ROLE_RESTARTS_LOG}."
    )


def _kill_pid_tree(pid: int) -> bool:
    """Kill `pid` and its descendants. True if anything was alive to kill."""
    try:
        import psutil

        proc = psutil.Process(pid)
        for child in proc.children(recursive=True):
            try:
                child.kill()
            except Exception:
                pass
        proc.kill()
        return True
    except Exception:
        return False


def cmd_down(args: argparse.Namespace) -> int:
    from syndicate.features.shared.process_liveness import pid_is_alive

    settings = settings_from_args(args)
    pidfile = settings.run_dir / PIDFILE_NAME
    stop_file = settings.run_dir / "stop"
    if not pidfile.is_file():
        print("not running (no pidfile).")
        return 0
    info = json.loads(pidfile.read_text(encoding="utf-8"))
    pid = int(info.get("supervisor_pid") or 0)

    # A supervisor that is already gone cannot read the stop file, so waiting
    # for it only burns the timeout (measured 2026-09-30: 90 s against a
    # supervisor the cloud session had already killed). Reap whatever it
    # recorded instead -- its roles and redis can outlive it as orphans.
    if not pid_is_alive(pid, zombie_is_dead=True):
        print(f"supervisor {pid} is not running (stale pidfile).")
        recorded = dict(info.get("roles") or {})
        if info.get("redis_pid"):
            recorded["redis"] = info["redis_pid"]
        for name, child_pid in recorded.items():
            if child_pid and pid_is_alive(int(child_pid), zombie_is_dead=True):
                killed = _kill_pid_tree(int(child_pid))
                print(f"  [{name}] orphan pid={child_pid} {'killed' if killed else 'could not be killed'}")
        pidfile.unlink(missing_ok=True)
        stop_file.unlink(missing_ok=True)
        print("down.")
        return 0

    # `down` takes the refresh-worker with it, so it needs the same claim a
    # restart does. systemd's ExecStop (INVOCATION_ID is set) is a host
    # shutdown and is never refused -- only recorded.
    local = parse_env_file(settings.env_file)
    via_systemd = bool(os.environ.get("INVOCATION_ID"))
    unclaimed_ok = str(getattr(args, "unclaimed_ok", "") or "").strip()
    claim = active_role_claim(deploy_claim_dir(local), "refresh-worker")
    if claim is None and not via_systemd and not unclaimed_ok:
        record_role_event(settings, local, "refresh-worker", "down_refused")
        print(
            "REFUSED: `down` stops the refresh-worker, and no unexpired deploy claim covers it.\n"
            "  python scripts/deploy_claim.py acquire --service refresh-worker --holder <lane>\n"
            "  then check_deploy_safety (idle = right after a save), then `down` again.\n"
            "  Override: --unclaimed-ok \"<reason>\" (recorded)."
        )
        return 3
    record_role_event(
        settings, local, "refresh-worker", "down",
        via="systemd" if via_systemd else "cli", reason=unclaimed_ok or None,
    )
    stop_file.write_text("stop", encoding="utf-8")
    deadline = time.time() + float(args.timeout)
    while time.time() < deadline and pidfile.is_file():
        if not pid_is_alive(pid, zombie_is_dead=True):
            break
        time.sleep(1)
    if pidfile.is_file():
        if pid_is_alive(pid, zombie_is_dead=True):
            print(f"supervisor {pid} did not stop in {args.timeout}s -- killing its process tree")
            _kill_pid_tree(pid)
        pidfile.unlink(missing_ok=True)
    stop_file.unlink(missing_ok=True)
    print("down.")
    return 0


BACKUP_EXCLUDES = ("*.lock", "*.pid")
BACKUP_SNAPSHOT_FORMAT = "%Y%m%dT%H%M%SZ"


def _setting(local: dict[str, str], key: str) -> str:
    return (os.environ.get(key) or local.get(key) or "").strip()


def default_backup_dir(settings: Settings, local: dict[str, str]) -> Path:
    """Where the hard-linked snapshots live: `SYNDICATE_LOCAL_BACKUP_DIR`, else
    `<home>-backup` beside the home -- the SAME filesystem as the data root, on
    purpose. rsync must preserve mtimes for `--link-dest` to match anything,
    and WSL's `/mnt/c` (9p, `uid=0`, no metadata) refuses every utime from the
    WSL user: measured 2026-10-01, 2,946 `failed to set times` in 4 minutes
    with 2,768 of ~41k files copied. The off-disk copy is a single archive
    instead (`default_offdisk_dir`)."""
    override = _setting(local, "SYNDICATE_LOCAL_BACKUP_DIR")
    if override:
        return Path(override).expanduser()
    return settings.home.parent / f"{settings.home.name}-backup"


def default_offdisk_dir(local: dict[str, str]) -> Path | None:
    """Where the newest snapshot is archived OFF the data root's disk image:
    `SYNDICATE_LOCAL_BACKUP_OFFDISK_DIR`, else `/mnt/c/SyndicateBackup` on WSL
    (the WSL disk is one VHDX file, so this survives a lost or unregistered
    distro), else none. Still the same physical disk -- copying it to a second
    drive or off the machine is the only protection against disk failure."""
    override = _setting(local, "SYNDICATE_LOCAL_BACKUP_OFFDISK_DIR")
    if override:
        return Path(override).expanduser()
    if not IS_WINDOWS and Path("/mnt/c").is_dir():
        return Path("/mnt/c/SyndicateBackup")
    return None


def archive_offdisk(snapshot: Path, offdisk: Path, keep: int) -> dict[str, Any]:
    """`tar | gzip -1` the snapshot into ONE file on `offdisk` (a single
    sequential write: no per-file metadata for 9p to refuse), `.partial` until
    complete, keep the newest `keep`."""
    offdisk.mkdir(parents=True, exist_ok=True)
    for stale in offdisk.glob("*.tar.gz.partial"):
        stale.unlink(missing_ok=True)
    target = offdisk / f"{snapshot.name}.tar.gz"
    partial = offdisk / f"{snapshot.name}.tar.gz.partial"
    command = ["tar", "-C", str(snapshot.parent), "--use-compress-program=gzip -1", "-cf", str(partial), snapshot.name]
    if shutil.which("nice") and not IS_WINDOWS:
        command = ["nice", "-n", "15"] + command
    proc = subprocess.run(command, capture_output=True, text=True)
    # tar exits 1 for "file changed as we read it"; the snapshot is not being
    # written, so anything non-zero here is a real failure.
    if proc.returncode != 0 or not partial.is_file():
        partial.unlink(missing_ok=True)
        return {"ok": False, "rc": proc.returncode, "error": (proc.stderr or "")[-300:]}
    partial.rename(target)
    archives = sorted(p for p in offdisk.glob("*.tar.gz") if p.is_file())
    for old in archives[: max(0, len(archives) - keep)]:
        old.unlink(missing_ok=True)
    return {"ok": True, "path": str(target), "bytes": target.stat().st_size}


def _complete_snapshots(dest: Path) -> list[Path]:
    snaps = []
    for path in dest.iterdir() if dest.is_dir() else []:
        if not path.is_dir() or path.name.endswith(".partial"):
            continue
        try:
            dt.datetime.strptime(path.name, BACKUP_SNAPSHOT_FORMAT)
        except ValueError:
            continue
        if (path / "manifest.json").is_file():
            snaps.append(path)
    return sorted(snaps, key=lambda p: p.name)


def _count_tree(root: Path) -> tuple[int, int]:
    files = size = 0
    for dirpath, _dirs, names in os.walk(root):
        for name in names:
            if any(Path(name).match(pattern) for pattern in BACKUP_EXCLUDES):
                continue
            try:
                size += os.stat(os.path.join(dirpath, name)).st_size
                files += 1
            except OSError:
                pass
    return files, size


def cmd_backup(args: argparse.Namespace) -> int:
    """Snapshot the data root (rsync, hard-linked against the previous snapshot)
    and the Redis state, keep the newest `--keep`. A snapshot is only renamed
    from `<ts>.partial` to `<ts>` once its manifest is written, so a run that
    dies half way never looks like a backup."""
    settings = settings_from_args(args)
    local = parse_env_file(settings.env_file)
    dest = Path(args.dest).expanduser() if args.dest else default_backup_dir(settings, local)
    if not settings.data_root.is_dir():
        print(f"REFUSING: no data root at {settings.data_root}")
        return 2
    rsync = shutil.which("rsync")
    if not rsync:
        print("REFUSING: rsync not found (the backup is implemented for the Linux/WSL host).")
        return 3
    dest.mkdir(parents=True, exist_ok=True)
    for stale in dest.glob("*.partial"):
        shutil.rmtree(stale, ignore_errors=True)
    started = dt.datetime.now(dt.timezone.utc)
    name = started.strftime(BACKUP_SNAPSHOT_FORMAT)
    partial = dest / f"{name}.partial"
    (partial / "data").mkdir(parents=True)
    previous = _complete_snapshots(dest)
    src_files, src_bytes = _count_tree(settings.data_root)
    # -rt, not -a: a --dest on drvfs/9p cannot chown, so -a would exit 23 there.
    command = [rsync, "-rt", "--delete"] + [f"--exclude={p}" for p in BACKUP_EXCLUDES]
    if previous:
        command.append(f"--link-dest={previous[-1] / 'data'}")
    command += [f"{settings.data_root}/", f"{partial / 'data'}/"]
    if shutil.which("nice") and not IS_WINDOWS:
        command = ["nice", "-n", "15"] + command
    print(f"backup {settings.data_root} -> {partial}  (link-dest {previous[-1].name if previous else 'none'})", flush=True)
    rc = subprocess.run(command).returncode
    # 24 = "some files vanished before they could be transferred": the roles keep
    # writing during the copy. Anything else is a failed snapshot.
    if rc not in (0, 24):
        print(f"FAILED: rsync rc={rc}; {partial} left for inspection and removed by the next run")
        return 4
    redis_note = "skipped (state=file)"
    if settings.state == "redis":
        redis_cli = shutil.which("redis-cli")
        if redis_cli:
            host, port = _redis_host_port(settings.redis_url)
            proc = subprocess.run([redis_cli, "-h", host, "-p", str(port), "--rdb", str(partial / "redis.rdb")],
                                  capture_output=True, text=True)
            redis_note = "ok" if proc.returncode == 0 and (partial / "redis.rdb").is_file() else f"FAILED rc={proc.returncode}"
        else:
            redis_note = "skipped (no redis-cli)"
    dst_files, dst_bytes = _count_tree(partial / "data")
    manifest = {
        "snapshot": name,
        "started_at": started.isoformat(),
        "finished_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source": str(settings.data_root),
        "source_files_at_start": src_files,
        "source_bytes_at_start": src_bytes,
        "snapshot_files": dst_files,
        "snapshot_bytes": dst_bytes,
        "rsync_rc": rc,
        "link_dest": previous[-1].name if previous else None,
        "redis": redis_note,
        "commit": git_commit(),
    }
    (partial / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    partial.rename(dest / name)
    kept = _complete_snapshots(dest)
    for old in kept[: max(0, len(kept) - int(args.keep))]:
        shutil.rmtree(old, ignore_errors=True)
    print(f"snapshot {dest / name}: {dst_files} files / {dst_bytes / 1e9:.2f} GB "
          f"(source at start {src_files} / {src_bytes / 1e9:.2f} GB), redis {redis_note}, rsync rc={rc}", flush=True)
    rc_out = 5 if redis_note.startswith("FAILED") else 0
    offdisk = None if args.no_offdisk else (Path(args.offdisk).expanduser() if args.offdisk else default_offdisk_dir(local))
    if offdisk is None:
        print("off-disk archive: none configured (SYNDICATE_LOCAL_BACKUP_OFFDISK_DIR)")
        return rc_out
    started_archive = time.time()
    result = archive_offdisk(dest / name, offdisk, int(args.offdisk_keep))
    if not result["ok"]:
        print(f"FAILED: off-disk archive into {offdisk}: rc={result['rc']} {result['error']}")
        return 6
    print(f"off-disk archive {result['path']}: {result['bytes'] / 1e9:.2f} GB in {time.time() - started_archive:.0f}s")
    return rc_out


# Keys that make a process act on the fleet's state or on a venue. The CI run
# gets none of them: a test suite run with the fleet's env would read and write
# the live Redis and data root.
CI_ENV_PASSTHROUGH = ("PATH", "HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "TMPDIR", "TERM", "SHELL")


def ci_env(base: dict[str, str] | None = None) -> dict[str, str]:
    base = dict(os.environ if base is None else base)
    env = {key: base[key] for key in CI_ENV_PASSTHROUGH if key in base}
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def cmd_ci_run(args: argparse.Namespace) -> int:
    """The `ci-suite` cron: run_ci_suite.py at this checkout's HEAD, in a
    SEPARATE clone (<home>/ci-checkout) so test output never dirties the
    checkout the fleet runs from, with a scrubbed env so no test can reach the
    fleet's Redis, data root or venue keys. Render ran it on its own instance
    with `--pytest-chunks 8 --pytest-workers 0`."""
    settings = settings_from_args(args)
    checkout = settings.home / "ci-checkout"
    head = git_commit()
    if not head:
        print("REFUSING: cannot read this checkout's HEAD")
        return 2
    git = ["git", "-c", f"safe.directory={REPO_ROOT}"]
    if not (checkout / ".git").is_dir():
        shutil.rmtree(checkout, ignore_errors=True)
        rc = subprocess.run(git + ["clone", "--quiet", "--no-checkout", str(REPO_ROOT), str(checkout)]).returncode
        if rc != 0:
            print(f"FAILED: clone rc={rc}")
            return 3
    for step in (["fetch", "--quiet", str(REPO_ROOT), head], ["checkout", "--quiet", "--force", "--detach", head],
                 ["clean", "-fdq"]):
        rc = subprocess.run(git + ["-C", str(checkout)] + step).returncode
        if rc != 0:
            print(f"FAILED: git {step[0]} rc={rc}")
            return 3
    summary = settings.run_dir / "ci-suite-latest.json"
    command = [sys.executable, "scripts/run_ci_suite.py", "--pytest-chunks", "8", "--pytest-workers", "0", "--json", str(summary)]
    if shutil.which("nice") and not IS_WINDOWS:
        command = ["nice", "-n", "15"] + command
    print(f"ci-suite at {head[:12]} in {checkout} (env scrubbed to {sorted(ci_env())})", flush=True)
    return subprocess.run(command, cwd=str(checkout), env=ci_env()).returncode


def role_loaded_commit(pid: int | None) -> str | None:
    """RENDER_GIT_COMMIT from the role's own environment: the commit of the
    supervisor's last `up`. NOT what a role runs after a role-only restart
    (the supervisor reuses the env) or a gunicorn HUP -- see `role_code`."""
    if not pid:
        return None
    try:
        import psutil

        return psutil.Process(int(pid)).environ().get("RENDER_GIT_COMMIT")
    except Exception:
        return None


def head_at(epoch: float, repo: Path = REPO_ROOT) -> str | None:
    """The checkout's HEAD at `epoch`, from its reflog (newest first). None when
    the reflog cannot answer: no git, no reflog, or `epoch` older than it."""
    try:
        out = subprocess.run(
            ["git", "reflog", "show", "--date=unix", "--format=%H %gd", "HEAD"],
            cwd=str(repo), capture_output=True, text=True, timeout=30,
        )
    except Exception:
        return None
    if out.returncode != 0:
        return None
    for line in out.stdout.splitlines():
        match = re.match(r"^([0-9a-f]{40}) \S*@\{(\d+)\}$", line.strip())
        if match and int(match.group(2)) <= epoch:
            return match.group(1)
    return None


def role_start_epoch(pid: int | None, role: str = "") -> float | None:
    """When the role's CODE was loaded. For web, gunicorn's OLDEST worker: a HUP
    replaces the workers (which import the app) and keeps the master. For the
    workers, the process itself; its children are sims, started later."""
    if not pid:
        return None
    try:
        import psutil

        proc = psutil.Process(int(pid))
        if role == "web":
            kids = [c.create_time() for c in proc.children()]
            if kids:
                return min(kids)
        return proc.create_time()
    except Exception:
        return None


def role_code(pid: int | None, role: str = "", repo: Path = REPO_ROOT) -> tuple[str, str]:
    """(commit, source) for what a role RUNS: HEAD at its start (`reflog`), else
    the env stamp (`env`, exact only for a role started by `up`).

    Measured 2026-10-02: live-odds-worker read `code=927d1787` from its env
    while it ran c1067485, which it loaded at a role-only restart (its split log
    line exists only in c1067485)."""
    started = role_start_epoch(pid, role)
    if started is not None:
        commit = head_at(started, repo)
        if commit:
            return commit, "reflog"
    return role_loaded_commit(pid) or "", "env"


# Paths no role imports or reads at runtime: a gap made only of these leaves a
# role's loaded code identical to HEAD's. `scripts/local_production.py` and
# `deploy/local/` are the SUPERVISOR and host install tooling -- no role imports
# them (only a comment in memory_observability.py names the file) -- so a change
# there needs `down`/`up` of the supervisor, not a role restart.
NON_RUNTIME_PATHSPECS = (":!.syndicate", ":!docs", ":!tests", ":!reports", ":!data", ":!*.md",
                         ":!scripts/local_production.py", ":!deploy/local")


def runtime_files_between(old: str, new: str, repo: Path = REPO_ROOT) -> list[str] | None:
    """Files that differ between two commits and could change what a role runs.

    None when git cannot answer (unknown commit, shallow clone, no git): the
    caller must treat that as STALE, never as current."""
    try:
        out = subprocess.run(
            ["git", "diff", "--name-only", old, new, "--", ".", *NON_RUNTIME_PATHSPECS],
            cwd=str(repo), capture_output=True, text=True, timeout=30,
        )
    except Exception:
        return None
    if out.returncode != 0:
        return None
    return [line for line in out.stdout.splitlines() if line.strip()]


def code_stamp_note(loaded: str, head: str, *, diff=runtime_files_between) -> str:
    """The `status` suffix for a role spawned on `loaded` while the checkout is at `head`.

    A commit-stamp comparison alone called every role STALE after a ledger-only
    fast-forward (2026-10-02: roles on `9856dd92`, HEAD `82bd182e`, one ledger
    commit between). Only a RUNTIME difference needs a restart."""
    if not loaded or not head or loaded == head:
        return ""
    files = diff(loaded, head)
    if files is None:
        return f" (HEAD {head[:8]}: STALE? cannot diff {loaded[:8]}..{head[:8]} -- treat as stale)"
    if not files:
        return f" (HEAD {head[:8]}: no role code changed -- nothing to load)"
    return f" (HEAD {head[:8]}: STALE -- {len(files)} runtime file(s) changed; restart the role to load HEAD)"


def _tail(path: Path, lines: int) -> list[str]:
    if lines <= 0 or not path.is_file():
        return []
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        handle.seek(max(0, size - 64 * 1024))
        return handle.read().decode("utf-8", errors="replace").splitlines()[-lines:]


def reload_progress(old_workers: set[int], current_workers: set[int], expected: int) -> str:
    """Where a HUP reload is: `booting` (fewer than `expected` new workers),
    `draining` (new set up, an old worker still alive), or `done`."""
    new = current_workers - old_workers
    if len(new) < expected:
        return "booting"
    if current_workers & old_workers:
        return "draining"
    return "done"


def _healthz_probe(port: int, timeout: float = 5.0) -> tuple[bool, float, str]:
    started = time.monotonic()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=timeout) as response:
            ok = response.status == 200
            via = response.headers.get("X-Syndicate-Health") or "flask"
            response.read()
        return ok, time.monotonic() - started, via
    except Exception as exc:  # noqa: BLE001 - every failure is a reading here
        return False, time.monotonic() - started, type(exc).__name__


def cmd_reload_web(args: argparse.Namespace) -> int:
    """Load new web code with a gunicorn HUP -- lane `web-restart-healthz` `[2026-10-06]`.

    WHY NOT TERM. On 2026-10-06 a session loaded web code by sending TERM to the
    gunicorn master (deploys.md 18:48:23Z). The master took ~2 min to drain and exit
    under a saturated host, the supervisor then restarted it, and between the old
    master closing its listener and the new one binding, `/healthz` was REFUSED
    (watchdog: down, Connection refused, 18:52:27Z), followed by ~8 min of cold
    workers. A HUP keeps the master and its listening socket: new workers boot (and
    import the new code) while the old ones drain, so a client waits at worst for a
    worker -- it is never refused. The supervisor sees no exit and keeps its pid.
    Polls `/healthz` every `--interval` s throughout and prints max latency and
    failures. Exit 0 only when every old worker is gone, the full new set is up, and
    `/healthz` answers 200; 1 otherwise (the reload is not confirmed -- go look)."""
    settings = settings_from_args(args)
    pidfile = settings.run_dir / PIDFILE_NAME
    if not pidfile.is_file():
        print("not running (no pidfile).")
        return 1
    info = json.loads(pidfile.read_text(encoding="utf-8"))
    master = (info.get("roles") or {}).get("web")
    port = int(info.get("port") or settings.port)
    try:
        import psutil

        proc = psutil.Process(int(master))
        cmdline = " ".join(proc.cmdline())
    except Exception as exc:  # noqa: BLE001
        print(f"web master {master} not readable ({type(exc).__name__}); nothing sent.")
        return 1
    if "gunicorn" not in cmdline or os.name == "nt":
        print("web is not a gunicorn master here (waitress/Windows); HUP does not apply -- use down/up.")
        return 1
    old = {c.pid for c in proc.children()}
    expected = int(args.workers or len(old) or 2)
    print(f"web master {master}: HUP; old workers {sorted(old)}; waiting for {expected} new", flush=True)
    os.kill(int(master), signal.SIGHUP)
    started = time.monotonic()
    deadline = started + float(args.timeout)
    probes = failures = 0
    worst = 0.0
    state = "booting"
    last_ok = False
    while time.monotonic() < deadline:
        ok, latency, via = _healthz_probe(port)
        probes += 1
        failures += 0 if ok else 1
        worst = max(worst, latency)
        last_ok = ok
        try:
            current = {c.pid for c in proc.children()}
        except Exception:  # noqa: BLE001 - the master itself died
            print("web master vanished during the reload -- the supervisor restarts it; NOT confirmed.")
            return 1
        state = reload_progress(old, current, expected)
        print(f"  +{time.monotonic() - started:5.1f}s healthz={'200' if ok else 'FAIL'} {latency:.2f}s via={via} "
              f"workers={sorted(current)} {state}", flush=True)
        if state == "done" and ok:
            break
        time.sleep(max(0.0, float(args.interval) - latency))
    print(f"RELOAD_WEB {json.dumps({'state': state, 'healthz_ok_last': last_ok, 'probes': probes, 'failures': failures, 'max_latency_s': round(worst, 2), 'elapsed_s': round(time.monotonic() - started, 1)}, sort_keys=True)}",
          flush=True)
    return 0 if state == "done" and last_ok else 1


def cmd_status(args: argparse.Namespace) -> int:
    settings = settings_from_args(args)
    pidfile = settings.run_dir / PIDFILE_NAME
    if not pidfile.is_file():
        print("not running (no pidfile).")
        return 1
    info = json.loads(pidfile.read_text(encoding="utf-8"))
    print(f"supervisor pid={info.get('supervisor_pid')} since {info.get('started_at')} state={info.get('state')}")
    try:
        import psutil
    except Exception:
        psutil = None  # type: ignore[assignment]
    head = git_commit()
    for name, pid in (info.get("roles") or {}).items():
        rss = "?"
        alive = False
        if psutil is not None and pid:
            try:
                proc = psutil.Process(int(pid))
                alive = proc.is_running()
                total = proc.memory_info().rss + sum(c.memory_info().rss for c in proc.children(recursive=True))
                rss = f"{total / 1024 / 1024:.0f} MB"
            except Exception:
                pass
        cap = PLAN_MEMORY_MB.get(name)
        loaded, source = role_code(pid, name)
        code = ""
        if loaded:
            code = f"  code={loaded[:8]}" + ("" if source == "reflog" else "(env stamp)") + code_stamp_note(loaded, head)
        print(f"  {name:17} pid={pid} {'up' if alive else 'DOWN'}  rss={rss}" + (f" (Render plan {cap} MB)" if cap else "")
              + f"  restarts={(info.get('restarts') or {}).get(name, 0)}" + code)
    port = int(info.get("port") or settings.port)
    for path in ("/healthz", "/api/ops/version"):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=10) as response:
                body = response.read(300).decode("utf-8", errors="replace").replace("\n", " ")
                print(f"  GET {path} -> {response.status}  {body[:160]}")
        except Exception as exc:  # noqa: BLE001
            print(f"  GET {path} -> {type(exc).__name__}: {exc}")
    try:
        job_state = json.loads((settings.run_dir / "scheduled_jobs.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        job_state = {}
    for job in SCHEDULED_JOBS:
        row = job_state.get(job.name) or {}
        when = f"{'Mon ' if job.weekday == 0 else ''}{job.hour:02d}:{job.minute:02d}Z"
        print(f"  job {job.name:21} {when:10} last_run={row.get('last_run_date', 'never')}  rc={row.get('last_rc', '-')}")
    for name in (info.get("roles") or {}):
        print(f"\n--- {name} (last {args.lines} lines) ---")
        for line in _tail(settings.logs_dir / f"{name}.log", args.lines):
            print(f"  {line}")
    return 0


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--home", help="state/data/logs dir (default: SYNDICATE_LOCAL_HOME, else %%LOCALAPPDATA%%\\SyndicateProd or ~/syndicate-prod)")
    parser.add_argument("--port", type=int, default=int(os.environ.get("SYNDICATE_LOCAL_PORT") or 10000))
    parser.add_argument("--host", default=os.environ.get("SYNDICATE_LOCAL_BIND") or "127.0.0.1",
                        help="web bind address; 127.0.0.1 unless you mean to expose it on the LAN")
    parser.add_argument("--state", choices=("redis", "file"), default="redis")
    parser.add_argument("--redis-url", default=os.environ.get("SYNDICATE_LOCAL_REDIS_URL") or "redis://127.0.0.1:6379/0")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="create the home dir and the secrets template")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("import-render-env", help="pull the three services' live env via the Render API (read-only)")
    p.add_argument("--env-file", help=".env holding RENDER_API_KEY (default: environment, then repo .env)")
    p.set_defaults(func=cmd_import_render_env)

    p = sub.add_parser("doctor", help="check everything `up` needs; starts nothing")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("env", help="print one role's derived env (secrets masked)")
    p.add_argument("--role", choices=ROLE_ORDER, required=True)
    p.add_argument("--unmask", action="store_true")
    p.set_defaults(func=cmd_env)

    p = sub.add_parser("up", help="seed once, start redis if needed, supervise the roles until stopped")
    p.add_argument("--roles", default=",".join(ROLE_ORDER))
    p.add_argument("--skip-bootstrap", action="store_true")
    p.add_argument("--allow-live-execution", action="store_true",
                   help="let the env file's SYNDICATE_EXECUTION_* through. Without this, money is always paper.")
    p.add_argument("--publish-loopback", action="store_true", help="point SYNDICATE_WEB_PUBLISH_URL at the local web")
    p.add_argument("--no-tunnel", action="store_true")
    p.add_argument("--no-jobs", action="store_true", help="do not run the scheduled jobs (SCHEDULED_JOBS: the Render crons + data-backup)")
    p.add_argument("--web-start-timeout", type=float, default=180.0)
    p.set_defaults(func=cmd_up)

    p = sub.add_parser("down", help="stop a running `up`")
    p.add_argument("--timeout", type=float, default=90.0)
    p.add_argument("--unclaimed-ok", metavar="REASON", default="", help="stop without a refresh-worker deploy claim (recorded in logs/role_restarts.jsonl)")
    p.set_defaults(func=cmd_down)

    p = sub.add_parser("backup", help="snapshot the data root + redis (hard-linked, keeps --keep); a scheduled job")
    p.add_argument("--dest", help="snapshot directory (default SYNDICATE_LOCAL_BACKUP_DIR, else <home>-backup)")
    p.add_argument("--keep", type=int, default=7)
    p.add_argument("--offdisk", help="archive directory (default SYNDICATE_LOCAL_BACKUP_OFFDISK_DIR, else /mnt/c/SyndicateBackup on WSL)")
    p.add_argument("--offdisk-keep", type=int, default=2)
    p.add_argument("--no-offdisk", action="store_true")
    p.set_defaults(func=cmd_backup)

    p = sub.add_parser("ci-run", help="the ci-suite cron: run_ci_suite.py in <home>/ci-checkout with a scrubbed env")
    p.set_defaults(func=cmd_ci_run)

    p = sub.add_parser("reload-web", help="load new web code by gunicorn HUP (rolling; never refuses), then confirm")
    p.add_argument("--timeout", type=float, default=300.0)
    p.add_argument("--interval", type=float, default=2.0)
    p.add_argument("--workers", type=int, default=0, help="new workers to wait for (default: as many as before)")
    p.set_defaults(func=cmd_reload_web)

    p = sub.add_parser("status", help="pids, memory, health, log tails")
    p.add_argument("--lines", type=int, default=8)
    p.set_defaults(func=cmd_status)

    args = parser.parse_args(list(argv))
    if hasattr(args, "roles") and isinstance(args.roles, str):
        args.roles = [r.strip() for r in args.roles.split(",") if r.strip()]
        unknown = [r for r in args.roles if r not in ROLE_ORDER]
        if unknown:
            parser.error(f"unknown role(s) {unknown}; known: {ROLE_ORDER}")
    return args


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(list(argv if argv is not None else sys.argv[1:]))
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
