"""Rehearse the fleet's three roles locally: the fleet's own role env, paper
money, and no way to reach production. `todo.md #625` build item (4).

    py -3 scripts/fleet_local.py --mirror M snapshot --fleet-home H   # once: credential-free env copy
    py -3 scripts/fleet_local.py --mirror M doctor                    # prove the guards engage; starts nothing
    py -3 scripts/fleet_local.py --mirror M up --bounded --duration-seconds 120
    py -3 scripts/fleet_local.py --mirror M up --roles web --fetch live
    py -3 scripts/fleet_local.py --mirror M down

`M` is a mirror laid out like the fleet's data root (`--mirror` or
SYNDICATE_MIRROR_ROOT; never inside the git tree, OneDrive, or a fleet home).
`H` is the fleet home, `~/syndicate-prod`; inside WSL run `snapshot` with
`python3` and `--mirror /mnt/c/...`, since `fleet_env/` is mode 0700 there.

`scripts/local_production.py` is the PRODUCTION counterpart (real keys, real
network, supervised forever). This is the rehearsal: same env construction,
none of the reach.

WHAT "PRODUCTION RUN-MODES" MEANS AND WHY IT IS THE HARD PART
-------------------------------------------------------------
The three roles are not three copies of one program. They are the SAME code
with different env, and the env is what decides which loops run -- `#625`'s own
practicals and this repo's standing rule both say so ("loop ownership is an env
flag that moves with no diff"). Measured 2026-09-02, the services differed on
**137 of 194 keys**, and the differences are the product: `SYNDICATE_REFRESH_LANE`,
`SYNDICATE_WEB_DYNO`, `SYNDICATE_MLB_REFRESH_TICK_OWNER`,
`SYNDICATE_ENABLE_LIVE_ODDS_REFRESH_LOOP`, and two dozen `*_ENABLE_*_AUTORUN`
flags.

So this runner does NOT invent a configuration. Each role's env is built by
the fleet's own `local_production.derive_role_env`, from the fleet's own
layers, a later one winning:
  1. `scripts/fleet_role_spec.json` -- the keys each role declares;
  2. a CREDENTIAL-FREE copy of `<fleet home>/fleet_env/<role>.json` (below);
  3. NOT `local_production.env`: it holds the live keys and the live arm;
  4. the fleet's forced keys -- service markers, worker->web URLs pointed at
     THIS run's web, the plan memory cap, a shared-disk publish no-op;
then this tool's rehearsal overrides. A role is not started without layer 2
unless `--spec-only` says so: absent is not off, and the snapshot is where most
`*_AUTORUN` switches live (88/182/148 keys against 52/84/76 declared).

THE SNAPSHOT NEVER HOLDS A SECRET, AND THAT IS STRUCTURAL
---------------------------------------------------------
`fleet_env/<role>.json` holds every value in plaintext, venue keys included.
`snapshot` reads it ONCE and writes `<mirror>/.fleet_local/env/fleet_env/
<role>.json` with only values that cannot be credentials
(`rehearsal_value_allowed`): booleans; the fleet's own `{data_root}` /
`{repo_root}` paths; and numbers or plain strings whose KEY NAME is not
secret-shaped and whose VALUE has no key-shaped run. Shape AND name, so a leak
needs both to fail at once -- the 2026-09 producer learned that from
`ADMIN_TOKEN`, a ten-digit number, which a shape-only rule wrote to disk. A
withheld key is recorded by NAME only; not even a hash (a ten-digit token's
`sha256` reverses in seconds). `doctor`/`up` refuse a file that does not carry
the rehearsal mark, so the live `fleet_env/` cannot be pointed at them, and
re-apply the rule on load anyway.

WHAT IT CHANGES ON TOP, AND WHY EACH ONE
----------------------------------------
FORCED:
  SYNDICATE_EXECUTION_MODE=paper       real orders (see the money block below)
  SYNDICATE_EXECUTION_LIVE_ARMED=0     the second, independent arm switch
  SYNDICATE_EXECUTION_ENABLED=0        the loop that would place them
  SYNDICATE_DATA_ROOT / _REPORTS_ROOT  the mirror, never the fleet's data root
  SYNDICATE_REFRESH_STATE_BACKEND      filesystem by default; keyvalue only on
                                       an explicit --redis-url that is not the
                                       fleet's
  SYNDICATE_BOOTSTRAP_ON_START=0       seeding the checkout over the mirror
                                       would overwrite the fixture under test
  SYNDICATE_HOSTED (removed)           `data_root()` and the hosted-only
                                       branches; see `--state` below

DROPPED (a credential this process must not hold, from ANY layer, including
the operator's own shell):
  KALSHI_*, POLYMARKET_*               nothing left to sign an order with
  ODDS_API_KEY / CFBD_API_KEY          a shared, metered budget -- the OddsAPI
                                       cap is 5M calls, CFBD's month was
                                       exhausted (`#633`)
  ADMIN_TOKEN, SYNDICATE_WEB_PUBLISH_URL   production WRITE paths
  REDIS_URL / keyvalue URL             production's shared state store
  inherited SYNDICATE_* from the shell the fleet's supervisor has none; a
                                       developer's shell value would change a
                                       run-mode no fleet layer set

THE MONEY BLOCK, WHICH IS THE ACTUAL POINT OF THIS TOOL
--------------------------------------------------------
The fleet has traded live money since 2026-10-19: live-odds-worker runs
`SYNDICATE_EXECUTION_MODE=live`, `SYNDICATE_EXECUTION_LIVE_ARMED=1`,
`SYNDICATE_EXECUTION_ENABLED=1`, `SYNDICATE_EXECUTION_VENUE=kalshi,polymarket`,
with real `KALSHI_PRIVATE_KEY` and `POLYMARKET_US_PRIVATE_KEY`. **Running that env
anywhere places real orders.** Several independent things must therefore hold,
and the child asserts them itself in `scripts/_fleet_guard.py` rather than
trusting this file's scrub -- because a scrub is a thing that can be mis-edited,
and the guard is what makes the failure loud instead of expensive.

AND PRODUCTION IS ON THIS MACHINE `[2026-11-17, lane fleet-local-env-source]`
---------------------------------------------------------------------------
Measured: a guarded replay child connected to 127.0.0.1:10000 (the fleet's web)
and :6379 (its Redis) from Windows, and resolved its web base URL to the fleet.
Now the guard denies the fleet's ports in every fetch mode, the workers' web URLs
point at this run's web, `--port` / `--redis-url` refuse the fleet's ports, and a
mirror inside a fleet home is refused -- by this file and again by the child.

FETCH MODE IS EXPLICIT, AND REPLAY IS THE DEFAULT (`#625` law 3)
-----------------------------------------------------------------
In replay mode every non-loopback connection is denied and recorded; loopback
is allowed (except the fleet's ports) so the roles can talk to each other.
`--fetch live` opts in, and the receipt records that it did, so a run that spent
real quota is identifiable afterwards rather than reconstructed.

`--state`: `file` (default) is `local_production --state file`, which clears
SYNDICATE_HOSTED and SYNDICATE_REQUIRE_HOSTED_STORAGE (both workers refuse a
file backend otherwise) -- honest on one shared disk, but the hosted-only
branches (request-path guard, portfolio auth, disk compaction) are OFF, as on
the fleet's own `--state file`. `redis` needs `--redis-url` to a server that is
not the fleet's.

MEMORY CAPS ARE A WATCHDOG, NOT A CONTAINER -- SAID PLAINLY
-----------------------------------------------------------
The caps are the fleet's own per-role defaults (`local_production.PLAN_MEMORY_MB`,
2/4/2 GB), enforced by SAMPLING RSS and acting, not by the kernel. A process can
exceed the cap between samples, and a sudden allocation can outrun the sampler.
Useful for the slow ratchet (`refresh-worker memory is boot-confounded`, `worker
periodic work is never free`); NOT evidence about the fleet's own ceiling.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import local_production as lp  # noqa: E402
from scripts._fleet_guard import (  # noqa: E402
    FLEET_PORTS,
    MODE_ENV,
    RECEIPT_ENV,
    ROLE_ENV,
    SHARED_BUDGET_ENV,
    VENUE_CREDENTIAL_ENV,
    is_production_path,
    url_port,
)

STATE_DIRNAME = ".fleet_local"
# Stamped into every file `snapshot` writes. `doctor`/`up` refuse a `fleet_env/`
# without it: the fleet's own copy holds the live credentials.
REHEARSAL_MARK = "fleet_local.py snapshot (credential-free; rehearsal_value_allowed)"


@dataclass(frozen=True)
class Role:
    name: str
    note: str

    @property
    def memory_cap_mb(self) -> int:
        """The fleet's own default cap for the role (`local_production.PLAN_MEMORY_MB`)."""
        return int(lp.PLAN_MEMORY_MB[self.name])


# The commands are the fleet's (`local_production.role_command`); `--bounded`
# appends `--run-once` to a worker so it does one pass instead of looping.
ROLES: dict[str, Role] = {
    "web": Role("web", "serves artifacts; does no heavy computation (CLAUDE.md's load-bearing rule)"),
    "refresh-worker": Role("refresh-worker", "sims, artifacts, evaluation; owns the intelligence-state loop"),
    "live-odds-worker": Role("live-odds-worker", "odds capture and the live tier; on the fleet this is the role that TRADES"),
}
assert tuple(ROLES) == lp.ROLE_ORDER, "fleet_local's roles must be the fleet's roles"

FORCED_ENV_BASE: dict[str, str] = {
    "SYNDICATE_EXECUTION_MODE": "paper",
    "SYNDICATE_EXECUTION_LIVE_ARMED": "0",
    "SYNDICATE_EXECUTION_ENABLED": "0",
    # Seeding the git checkout over the mirror would overwrite the very fixture
    # a local run is supposed to be reading.
    "SYNDICATE_BOOTSTRAP_ON_START": "0",
    # `data_root()` raises instead of falling back when this is set, and it
    # switches on the hosted-only branches; a rehearsal is `--state file`-shaped.
    # (The hosted marker: `SYNDICATE_HOSTED`, `RENDER` until 2026-11-17, `service_identity`.)
    "SYNDICATE_HOSTED": "",
    "PYTHONIOENCODING": "utf-8",
    "PYTHONUNBUFFERED": "1",
}

DROPPED_ENV: tuple[str, ...] = VENUE_CREDENTIAL_ENV + SHARED_BUDGET_ENV + tuple(lp.NEVER_CARRY) + (
    "REDIS_URL",
    "SYNDICATE_KEYVALUE_URL",
    "ANTHROPIC_API_KEY",
)

# Per-sport roots that silently win over SYNDICATE_DATA_ROOT (`source_roots.py`;
# the live-lens dirs are read at IMPORT time). The fleet's own values are
# `{data_root}/...`, which expand into the mirror and are kept -- that is the
# fleet's layout. Any value that resolves OUTSIDE the mirror is dropped.
MIRROR_BOUND_ENV: tuple[str, ...] = (
    *[f"SYNDICATE_{sport}_SOURCE_ROOT" for sport in ("MLB", "NBA", "WNBA", "NHL", "NFL", "NCAAF", "NCAAB", "SOCCER")],
    *[f"{sport}_LIVE_LENS_DIR" for sport in ("MLB", "NBA", "NHL", "WNBA")],
    *[f"{sport}_BETTING_DATA_ROOT" for sport in ("MLB", "NBA", "WNBA")],
    "NHL_DATA_DIR",
)

# --------------------------------------------------------------------------
# The credential-free snapshot
# --------------------------------------------------------------------------

# No credential is spelled "false".
_BOOLEAN_LITERAL = re.compile(r"^(?:true|false|yes|no|on|off)$", re.IGNORECASE)
# The 2026-09 producer's name list, plus the account-shaped names a plain string
# could carry (a portfolio username is half a login).
_SECRET_NAME = re.compile(
    r"TOKEN|KEY|SECRET|PASSWORD|PASSWD|CREDENTIAL|PRIVATE|AUTH|SIGNATURE|SALT|HASH|"
    r"DSN|URL|URI|CONN|COOKIE|SESSION|USER|LOGIN|EMAIL|ACCOUNT|PHONE",
    re.IGNORECASE,
)
# A key-shaped run: 16+ letters and digits with at least one of each (hex and
# base64 keys, PEM bodies). Identifiers split on `_` / `-` / `,` never reach it.
_KEYLIKE_RUN = re.compile(r"(?=[A-Za-z0-9]*[0-9])(?=[A-Za-z0-9]*[A-Za-z])[A-Za-z0-9]{16,}")
_MAX_PLAIN_LEN = 512


def rehearsal_value_allowed(key: str, value: Any) -> bool:
    """May this fleet_env value be written to a rehearsal snapshot?

    Allowed only where it cannot be a credential:
      * a boolean literal, under any name;
      * a value in the fleet's own path layout (`{data_root}` / `{repo_root}`);
      * otherwise the KEY NAME must not be secret-shaped AND the value must be
        short and hold no key-shaped run.
    A key this runner drops is never recorded, whatever its value.
    """
    name = str(key or "")
    if name in DROPPED_ENV:
        return False
    text = "" if value is None else str(value)
    if _BOOLEAN_LITERAL.match(text):
        return True
    if _KEYLIKE_RUN.search(text) or len(text) > _MAX_PLAIN_LEN:
        return False
    if text.startswith((lp.DATA_ROOT_TOKEN, lp.REPO_ROOT_TOKEN)):
        return True
    return not _SECRET_NAME.search(name)


def redact_snapshot(values: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    kept = {k: v for k, v in values.items() if rehearsal_value_allowed(k, v)}
    return kept, sorted(k for k in values if k not in kept)


def state_dir(mirror: Path) -> Path:
    return mirror / STATE_DIRNAME


def default_env_dir(mirror: Path) -> Path:
    """Where `snapshot` writes and `doctor`/`up` read: laid out like a fleet home
    (`<dir>/fleet_env/<role>.json`), so local_production's own loaders read it."""
    return state_dir(mirror) / "env"


def _env_settings(env_dir: Path) -> lp.Settings:
    return lp.Settings(home=env_dir)


def write_rehearsal_snapshot(fleet_home: Path, out_dir: Path, *, now: dt.datetime | None = None) -> dict[str, dict[str, Any]]:
    """Read the fleet's `fleet_env/` ONCE and write a credential-free copy.

    Returns per-role {kept, withheld (names), source}. NEVER returns or prints a value."""
    now = now or dt.datetime.now(dt.timezone.utc)
    source = _env_settings(fleet_home)
    missing = lp.missing_env_snapshots(source, lp.ROLE_ORDER)
    if missing:
        raise SystemExit(
            f"no fleet env for {', '.join(missing)} under {fleet_home / lp.ENV_SNAPSHOT_DIR_NAME}.\n"
            "--fleet-home is the fleet's home (~/syndicate-prod), the directory that holds fleet_env/."
        )
    target = _env_settings(out_dir)
    summary: dict[str, dict[str, Any]] = {}
    for role in lp.ROLE_ORDER:
        src_path = lp.env_snapshot_path(source, role)
        meta = json.loads(src_path.read_text(encoding="utf-8"))
        if isinstance(meta, dict) and meta.get("redacted_by"):
            raise SystemExit(f"{src_path} is already a rehearsal snapshot; --fleet-home is the fleet's own home.")
        values = lp.load_env_snapshot(source, role)
        kept, withheld = redact_snapshot(values)
        dest = lp.env_snapshot_path(target, role)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(
            json.dumps(
                {
                    "role": role,
                    "redacted_by": REHEARSAL_MARK,
                    "rehearsal_snapshot_at": now.isoformat(),
                    "source": str(src_path),
                    "snapshot_taken_at": (meta or {}).get("snapshot_taken_at") if isinstance(meta, dict) else None,
                    "values": dict(sorted(kept.items())),
                    "withheld": withheld,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        summary[role] = {"source_keys": len(values), "kept": len(kept), "withheld": withheld, "path": str(dest)}
    return summary


@dataclass
class RoleSnapshot:
    values: dict[str, str]
    withheld: list[str]
    taken_at: str | None
    rehearsal_at: str | None
    rewithheld: list[str] = field(default_factory=list)


def load_rehearsal_env(env_dir: Path) -> dict[str, RoleSnapshot]:
    """{role: RoleSnapshot} for every role whose rehearsal file exists.

    Refuses a single JSON file (the Render-era format) and any `fleet_env/` file
    without the rehearsal mark (the fleet's own copy holds live credentials).
    The rule is re-applied on load; `rewithheld` lists anything it caught."""
    if env_dir.is_file():
        raise SystemExit(
            f"{env_dir} is a file. --env-snapshot is now a DIRECTORY written by `fleet_local.py snapshot`\n"
            "(<dir>/fleet_env/<role>.json). A single JSON file is the Render-era format from\n"
            "snapshot_render_env.py, retired 2026-11-15 (lane render-retirement)."
        )
    settings = _env_settings(env_dir)
    out: dict[str, RoleSnapshot] = {}
    for role in lp.ROLE_ORDER:
        path = lp.env_snapshot_path(settings, role)
        if not path.is_file():
            continue
        meta = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(meta, dict) or meta.get("redacted_by") != REHEARSAL_MARK:
            raise SystemExit(
                f"refusing {path}: it is not a rehearsal snapshot (no `redacted_by` mark).\n"
                "It may be the fleet's own fleet_env/, which holds the live credentials. Make a\n"
                "credential-free copy with `fleet_local.py snapshot --fleet-home <fleet home>`."
            )
        values = lp.load_env_snapshot(settings, role)
        kept, rewithheld = redact_snapshot(values)
        out[role] = RoleSnapshot(
            values=kept,
            withheld=sorted(set(meta.get("withheld") or []) | set(rewithheld)),
            taken_at=meta.get("snapshot_taken_at"),
            rehearsal_at=meta.get("rehearsal_snapshot_at"),
            rewithheld=rewithheld,
        )
    return out


# --------------------------------------------------------------------------
# Refusals: nothing here may resolve to production
# --------------------------------------------------------------------------


def rehearsal_mirror(explicit: str | None) -> Path:
    from scripts.mirror_manifest import mirror_root

    mirror = mirror_root(explicit)
    fleet_data = (lp.default_home() / "data").expanduser()
    try:
        same = mirror.resolve() == fleet_data.resolve()
    except OSError:
        same = False
    if same or is_production_path(str(mirror)):
        raise SystemExit(
            f"refusing: mirror {mirror} is a fleet data root (or inside a fleet home).\n"
            "Production runs on this machine; a rehearsal writes only to its own mirror."
        )
    return mirror


def check_ports(port: int, redis_url: str | None) -> None:
    if port in FLEET_PORTS:
        raise SystemExit(f"refusing --port {port}: it is one of the fleet's own ports {FLEET_PORTS}.")
    if redis_url and url_port(redis_url) in FLEET_PORTS:
        raise SystemExit(
            f"refusing --redis-url on port {url_port(redis_url)}: the fleet's Redis is its whole shared state store.\n"
            "Start a rehearsal redis on another port (e.g. redis-server --port 6390)."
        )


# --------------------------------------------------------------------------
# Env derivation
# --------------------------------------------------------------------------


@dataclass
class _RehearsalSettings(lp.Settings):
    """The fleet's Settings with the data root moved to the mirror and every
    run-time path under the mirror's state dir."""

    mirror: Path = Path(".")

    @property
    def data_root(self) -> Path:  # type: ignore[override]
        return self.mirror


def derive_env(
    role: Role | str,
    snapshot: dict[str, str],
    *,
    mirror: Path,
    fetch: str,
    state_backend: str,
    receipt_path: Path,
    guard_dir: Path,
    port: int,
    redis_url: str | None = None,
    base_env: dict[str, str] | None = None,
) -> tuple[dict[str, str], dict[str, Any]]:
    """The fleet's env construction in, a rehearsal env out. Returns (env, an auditable diff).

    `port` is the WEB role's port: every role gets it, so the workers' web URLs
    point at this run's web and never at the fleet."""
    name = role.name if isinstance(role, Role) else str(role)
    if state_backend == "redis" and not redis_url:
        raise SystemExit("--state redis needs --redis-url to a rehearsal redis (never the fleet's).")
    check_ports(port, redis_url)
    inherited = dict(os.environ if base_env is None else base_env)
    stripped = sorted(k for k in inherited if k.startswith("SYNDICATE_"))
    for key in stripped:
        inherited.pop(key, None)
    settings = _RehearsalSettings(
        home=state_dir(mirror) / "home",
        port=port,
        state="redis" if state_backend == "redis" else "file",
        # Never None: a spec `keyvalue` key gets this URL, and one nothing answers
        # is the safe one when the backend is the filesystem.
        redis_url=redis_url or lp.CI_DEAD_REDIS_URL,
        allow_live_execution=False,
        publish_loopback=False,
        mirror=mirror,
    )
    spec = lp.load_role_spec()
    env, audit = lp.derive_role_env(
        name,
        spec,
        {},  # never local_production.env: it holds the live keys and the live arm
        settings,
        snapshot=snapshot,
        base_env=inherited,
        instance_id=f"rehearsal-{name}-{int(time.time())}",
    )

    dropped = sorted({key for key in DROPPED_ENV if str(env.get(key) or "").strip()})
    for key in DROPPED_ENV:
        env.pop(key, None)
    outside: list[str] = []
    mirror_text = str(mirror.resolve()).lower().replace("\\", "/").rstrip("/")
    for key in MIRROR_BOUND_ENV:
        value = str(env.get(key) or "").strip()
        if not value:
            continue
        # A relative value resolves against the child's cwd, the checkout.
        path = Path(value) if Path(value).is_absolute() else REPO_ROOT / value
        try:
            resolved = str(path.resolve()).lower().replace("\\", "/")
        except OSError:
            resolved = str(path).lower()
        if not (resolved == mirror_text or resolved.startswith(mirror_text + "/")):
            outside.append(key)
            env.pop(key, None)

    forced: dict[str, str] = dict(FORCED_ENV_BASE)
    forced["SYNDICATE_DATA_ROOT"] = str(mirror)
    forced["SYNDICATE_REPORTS_ROOT"] = str(state_dir(mirror) / "reports" / name)
    if state_backend != "redis":
        # Both workers REFUSE a file backend while this is truthy
        # (`assert_refresh_state_backend_ready`), and the fleet sets it on every
        # role. One disk shared by all three roles is the condition that
        # assertion protects, so clearing it states the truth -- exactly what
        # `local_production --state file` does.
        forced["SYNDICATE_REQUIRE_HOSTED_STORAGE"] = ""
    forced[ROLE_ENV] = name
    forced[MODE_ENV] = fetch
    forced[RECEIPT_ENV] = str(receipt_path)
    changed = {k: v for k, v in forced.items() if env.get(k) != v}
    for key, value in forced.items():
        if value == "":
            env.pop(key, None)
        else:
            env[key] = value

    # The guard directory FIRST, so `sitecustomize` resolves to ours (the
    # fleet's log-stamp sitecustomize is shadowed; `resolve_sitecustomize`
    # proves which one wins).
    existing = env.get("PYTHONPATH") or ""
    env["PYTHONPATH"] = os.pathsep.join([str(guard_dir), str(REPO_ROOT)] + ([existing] if existing else []))
    return env, {
        "dropped": dropped,
        "dropped_outside_mirror": outside,
        "stripped_inherited": stripped,
        "forced": {k: ("<local path>" if "ROOT" in k else v) for k, v in changed.items()},
        "declared": len(spec[name]),
        "snapshot_keys": len(snapshot),
        "unset_declared": list(audit.get("unset") or []),
        "markers": {k: env.get(k) for k in lp.SERVICE_MARKERS if env.get(k)},
    }


def role_command(role: Role, env: dict[str, str], *, port: int, bounded: bool) -> tuple[list[str], str]:
    """The fleet's own command (`local_production.role_command`): gunicorn on
    Linux, waitress on Windows. `--bounded` asks a worker for one pass."""
    settings = lp.Settings(home=Path("."), port=port)
    command, server = lp.role_command(role.name, env, settings)
    if bounded and role.name != "web":
        command = list(command) + ["--run-once"]
    return list(command), server


# --------------------------------------------------------------------------
# The guard
# --------------------------------------------------------------------------


def write_guard_dir(target: Path) -> Path:
    """Generate the `sitecustomize.py` CPython imports at interpreter startup.

    This is the ONLY hook that reaches every role: gunicorn/waitress and
    `python scripts/run_*.py` share no entrypoint, so a guard installed in one
    would miss the others.
    """
    target.mkdir(parents=True, exist_ok=True)
    (target / "sitecustomize.py").write_text(
        '"""GENERATED by scripts/fleet_local.py -- do not edit; it is rewritten on every `up`.\n'
        "\n"
        "CPython imports this during interpreter startup, before __main__, which is\n"
        "why it reaches the web server as well as a plain script. It engages the local\n"
        "fleet guard and EXITS if money could be spent or production reached --\n"
        "see scripts/_fleet_guard.py.\n"
        '"""\n'
        "import sys\n"
        f"sys.path.insert(0, {str(REPO_ROOT)!r})\n"
        "from scripts._fleet_guard import engage\n"
        "engage()\n",
        encoding="utf-8",
    )
    return target


def resolve_sitecustomize(guard_dir: Path, env: dict[str, str]) -> tuple[bool, str]:
    """Prove the child WOULD load our guard, before starting anything.

    `presence is not reachability`: a `sitecustomize.py` on disk is not a
    `sitecustomize` that gets imported -- another one earlier on the path, or a
    `-S` interpreter, silently wins. So ask a real interpreter, with the real
    env, which file it resolves.
    """
    probe = subprocess.run(
        [sys.executable, "-c", "import sitecustomize,sys; sys.stdout.write(sitecustomize.__file__)"],
        env=env,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    resolved = (probe.stdout or "").strip()
    expected = str((guard_dir / "sitecustomize.py").resolve())
    ok = bool(resolved) and Path(resolved).resolve() == Path(expected)
    if not ok:
        return False, f"resolved {resolved or '<none>'} (stderr: {(probe.stderr or '').strip()[:300]}), expected {expected}"
    return True, resolved


# A child that tries each fleet port; the guard must refuse before any connect.
_FLEET_PORT_PROBE = (
    "import socket, sys\n"
    "for port in [int(p) for p in sys.argv[1:]]:\n"
    "    try:\n"
    "        socket.create_connection(('127.0.0.1', port), timeout=2).close()\n"
    "        print(port, 'CONNECTED')\n"
    "    except OSError as exc:\n"
    "        print(port, 'GUARD' if 'FLEET PORT' in str(exc) else 'OS')\n"
)


def probe_fleet_ports(env: dict[str, str]) -> dict[int, str]:
    probe = subprocess.run(
        [sys.executable, "-c", _FLEET_PORT_PROBE, *map(str, FLEET_PORTS)],
        env=env, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=120,
    )
    out: dict[int, str] = {}
    for line in (probe.stdout or "").splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0].isdigit():
            out[int(parts[0])] = parts[1]
    return out


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------


@dataclass
class RunningRole:
    role: Role
    process: subprocess.Popen
    receipt_path: Path
    log_path: Path
    started_at: float
    peak_rss_mb: float = 0.0
    samples: int = 0
    cap_breaches: int = 0
    receipt: dict[str, Any] = field(default_factory=dict)


def sample_rss_mb(pid: int) -> float | None:
    """RSS of the process tree. None when psutil is unavailable -- and that is
    reported, not silently treated as 0, which would read as a healthy run."""
    try:
        import psutil
    except Exception:
        return None
    try:
        proc = psutil.Process(pid)
        total = proc.memory_info().rss
        for child in proc.children(recursive=True):
            try:
                total += child.memory_info().rss
            except Exception:
                continue
        return total / (1024 * 1024)
    except Exception:
        return None


def cmd_snapshot(args: argparse.Namespace) -> int:
    """Write the credential-free copy of the fleet's env. Prints key NAMES and counts only."""
    out_dir = Path(args.out).expanduser() if args.out else default_env_dir(rehearsal_mirror(args.mirror))
    if is_production_path(str(out_dir)):
        raise SystemExit(f"refusing --out {out_dir}: inside a fleet home.")
    fleet_home = Path(args.fleet_home).expanduser()
    summary = write_rehearsal_snapshot(fleet_home, out_dir)
    print(f"REHEARSAL SNAPSHOT   from {fleet_home / lp.ENV_SNAPSHOT_DIR_NAME}   to {out_dir / lp.ENV_SNAPSHOT_DIR_NAME}")
    for role, row in summary.items():
        print(f"  {role:18} {row['kept']} of {row['source_keys']} kept, {len(row['withheld'])} withheld "
              f"(names only, no value or hash): {', '.join(row['withheld'])}")
    return 0


def _snapshot_for(args: argparse.Namespace, mirror: Path) -> tuple[Path, dict[str, RoleSnapshot]]:
    env_dir = Path(args.env_snapshot).expanduser() if args.env_snapshot else default_env_dir(mirror)
    loaded = load_rehearsal_env(env_dir) if (env_dir.exists() or args.env_snapshot) else {}
    return env_dir, loaded


def _no_snapshot_message(env_dir: Path) -> str:
    return (
        f"NO REHEARSAL SNAPSHOT at {env_dir / lp.ENV_SNAPSHOT_DIR_NAME} -- refusing to guess the undeclared keys "
        "(absent is not off).\n      Make one: fleet_local.py --mirror <M> snapshot --fleet-home <fleet home>, "
        "or pass --spec-only to rehearse the declared keys alone."
    )


def cmd_doctor(args: argparse.Namespace) -> int:
    """Prove the guards would engage. Starts no role."""
    mirror = rehearsal_mirror(args.mirror)
    check_ports(args.port, args.redis_url)
    env_dir, snapshots = _snapshot_for(args, mirror)
    guard_dir = write_guard_dir(state_dir(mirror) / "guard")
    print(f"FLEET DOCTOR   mirror={mirror}   fetch={args.fetch}   state={args.state}   web port={args.port}")
    print(f"  env layers     scripts/fleet_role_spec.json -> {env_dir / lp.ENV_SNAPSHOT_DIR_NAME} "
          f"-> (never local_production.env) -> forced{' [--spec-only]' if args.spec_only else ''}")

    ok_all = True
    for name in args.roles:
        role = ROLES[name]
        snap = snapshots.get(name)
        if snap is None and not args.spec_only:
            print(f"\n  [{name}] {_no_snapshot_message(env_dir)}")
            ok_all = False
            continue
        receipt = state_dir(mirror) / "receipts" / f"{name}.doctor.json"
        receipt.unlink(missing_ok=True)
        env, diff = derive_env(
            role,
            snap.values if snap else {},
            mirror=mirror,
            fetch=args.fetch,
            state_backend=args.state,
            receipt_path=receipt,
            guard_dir=guard_dir,
            port=args.port,
            redis_url=args.redis_url,
        )
        _, server = role_command(role, env, port=args.port, bounded=False)
        print(f"\n  [{name}]  cap={role.memory_cap_mb} MB (the fleet's default)  server={server}")
        if snap:
            print(f"      spec {diff['declared']} declared + snapshot {len(snap.values)} kept / {len(snap.withheld)} withheld "
                  f"(fleet_env taken {snap.taken_at}, copied {snap.rehearsal_at})")
            if snap.rewithheld:
                print(f"      RE-WITHHELD ON LOAD (the file held them): {', '.join(snap.rewithheld)}")
                ok_all = False
        else:
            print(f"      spec {diff['declared']} declared, NO snapshot (--spec-only): undeclared run-mode keys are absent")
        print(f"      dropped {len(diff['dropped'])}, forced {len(diff['forced'])}, "
              f"stripped {len(diff['stripped_inherited'])} inherited SYNDICATE_* from this shell")
        if diff["dropped"]:
            print(f"      DROPPED  {', '.join(diff['dropped'])}")
        if diff["dropped_outside_mirror"]:
            print(f"      DROPPED (outside the mirror)  {', '.join(diff['dropped_outside_mirror'])}")
        if diff["unset_declared"]:
            print(f"      declared, no rehearsal value (unset)  {', '.join(diff['unset_declared'])}")
        print(f"      markers  {', '.join(f'{k}={v}' for k, v in diff['markers'].items())}")
        base_url = env.get("SYNDICATE_INTERNAL_WEB_BASE_URL")
        url_ok = url_port(base_url or "") == args.port
        print(f"      worker->web URL {base_url}  {'OK (this run)' if url_ok else 'WRONG'}")
        ok_all = ok_all and url_ok

        resolved_ok, detail = resolve_sitecustomize(guard_dir, env)
        print(f"      sitecustomize {'OK' if resolved_ok else 'WRONG'}  {detail}")
        ok_all = ok_all and resolved_ok

        # Does the guard actually ENGAGE?
        probe = subprocess.run(
            [sys.executable, "-c", "pass"], env=env, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=120
        )
        engaged = receipt.is_file() and probe.returncode == 0
        print(f"      guard engaged {'YES' if engaged else 'NO'}  (rc={probe.returncode})")
        if engaged:
            payload = json.loads(receipt.read_text(encoding="utf-8"))
            for reason in (payload.get("money_off_because") or []) + (payload.get("production_off_because") or []):
                print(f"        off: {reason}")
            print(f"        network:   {payload.get('network')}")
            if payload.get("shared_budget_credentials_present"):
                print(f"        WARNING shared-budget creds still present: {payload['shared_budget_credentials_present']}")
                ok_all = False
        else:
            print(f"        stderr: {(probe.stderr or '').strip()[-400:]}")
            ok_all = False

        # NEGATIVE CONTROLS. A guard that has only ever been seen to pass is not
        # known to be a guard.
        armed = dict(env)
        armed["SYNDICATE_EXECUTION_MODE"] = "live"
        armed["SYNDICATE_EXECUTION_LIVE_ARMED"] = "1"
        refusal = subprocess.run(
            [sys.executable, "-c", "pass"], env=armed, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=120
        )
        refused = refusal.returncode != 0 and "could spend money" in (refusal.stderr or "").lower()
        print(f"      REFUSES a money-armed env: {'YES' if refused else 'NO'}  (rc={refusal.returncode})")
        ok_all = ok_all and refused

        ports = probe_fleet_ports(env)
        ports_ok = all(ports.get(port) == "GUARD" for port in FLEET_PORTS)
        print("      REFUSES the fleet's ports: "
              + ", ".join(f"{port} {'YES' if ports.get(port) == 'GUARD' else 'NO (' + str(ports.get(port)) + ')'}" for port in FLEET_PORTS))
        ok_all = ok_all and ports_ok

        prod_env = dict(env)
        prod_env["SYNDICATE_DATA_ROOT"] = str(Path.home() / "syndicate-prod" / "data")
        prod = subprocess.run(
            [sys.executable, "-c", "pass"], env=prod_env, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=120
        )
        prod_refused = prod.returncode != 0 and "could write to production" in (prod.stderr or "").lower()
        print(f"      REFUSES the fleet's data root: {'YES' if prod_refused else 'NO'}  (rc={prod.returncode})")
        ok_all = ok_all and prod_refused

    print()
    print("DOCTOR: " + ("READY" if ok_all else "NOT READY -- do not start the fleet"))
    return 0 if ok_all else 1


def cmd_up(args: argparse.Namespace) -> int:
    mirror = rehearsal_mirror(args.mirror)
    check_ports(args.port, args.redis_url)
    env_dir, snapshots = _snapshot_for(args, mirror)
    root = state_dir(mirror)
    guard_dir = write_guard_dir(root / "guard")
    (root / "logs").mkdir(parents=True, exist_ok=True)
    (root / "receipts").mkdir(parents=True, exist_ok=True)

    print(f"FLEET UP   mirror={mirror}   fetch={args.fetch}   state={args.state}   web port={args.port}")
    for name in args.roles:
        snap = snapshots.get(name)
        if snap:
            print(f"  {name:18} snapshot {len(snap.values)} kept, {len(snap.withheld)} withheld (fleet_env taken {snap.taken_at})")
    running: list[RunningRole] = []
    try:
        for name in args.roles:
            role = ROLES[name]
            snap = snapshots.get(name)
            if snap is None and not args.spec_only:
                print(f"  [{name}] {_no_snapshot_message(env_dir)}")
                continue
            receipt = root / "receipts" / f"{name}.json"
            receipt.unlink(missing_ok=True)
            receipt.with_suffix(".network.jsonl").unlink(missing_ok=True)
            log_path = root / "logs" / f"{name}.log"
            env, diff = derive_env(
                role,
                snap.values if snap else {},
                mirror=mirror,
                fetch=args.fetch,
                state_backend=args.state,
                receipt_path=receipt,
                guard_dir=guard_dir,
                port=args.port,
                redis_url=args.redis_url,
            )

            resolved_ok, detail = resolve_sitecustomize(guard_dir, env)
            if not resolved_ok:
                print(f"  [{name}] REFUSING TO START: the guard would not load -- {detail}")
                continue

            command, server = role_command(role, env, port=args.port, bounded=args.bounded)
            if role.name == "web" and server != "gunicorn":
                # REPORTED, not silent: a different server can produce different
                # readings, and a reader has to know which one ran.
                print(f"  [{name}] web runs {server}, the fleet's own fallback where gunicorn cannot run "
                      "(Windows: no fcntl). The fleet's web is gunicorn; do not read concurrency from this.")

            handle = log_path.open("w", encoding="utf-8", errors="replace")
            process = subprocess.Popen(
                command, cwd=str(REPO_ROOT), env=env, stdout=handle, stderr=subprocess.STDOUT
            )
            running.append(RunningRole(role=role, process=process, receipt_path=receipt, log_path=log_path, started_at=time.time()))
            print(f"  [{name}] pid={process.pid}  cap={role.memory_cap_mb} MB  log={log_path}")
            print(f"           spec {diff['declared']} declared + snapshot {diff['snapshot_keys']}; dropped "
                  f"{len(diff['dropped'])} credential vars, forced {len(diff['forced'])}")

        if not running:
            print("nothing started.")
            return 1

        # A ROLE IS NOT 'STARTED' UNTIL ITS RECEIPT EXISTS. The parent cannot see
        # inside the child; the receipt is the child saying the guard engaged.
        deadline = time.time() + 60
        for item in running:
            while time.time() < deadline and not item.receipt_path.is_file():
                if item.process.poll() is not None:
                    break
                time.sleep(0.5)
            if item.receipt_path.is_file():
                item.receipt = json.loads(item.receipt_path.read_text(encoding="utf-8"))
                print(f"  [{item.role.name}] guard receipt OK -- {item.receipt.get('network')}")
            else:
                print(f"  [{item.role.name}] NO GUARD RECEIPT -- killing it. "
                      f"exit={item.process.poll()}  see {item.log_path}")
                _terminate(item.process)

        report = _watch(running, duration=args.duration_seconds, sample_every=args.sample_seconds, kill_on_cap=args.kill_on_cap)
        _print_report(report)
        if args.write:
            Path(args.write).parent.mkdir(parents=True, exist_ok=True)
            Path(args.write).write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        return 0 if report["ok"] else 1
    finally:
        for item in running:
            _terminate(item.process)


def _terminate(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=15)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass


def _watch(running: list[RunningRole], *, duration: float, sample_every: float, kill_on_cap: bool) -> dict[str, Any]:
    psutil_available = sample_rss_mb(os.getpid()) is not None
    end = time.time() + duration
    while time.time() < end:
        for item in running:
            if item.process.poll() is not None:
                continue
            rss = sample_rss_mb(item.process.pid)
            if rss is None:
                continue
            item.samples += 1
            item.peak_rss_mb = max(item.peak_rss_mb, rss)
            if rss > item.role.memory_cap_mb:
                item.cap_breaches += 1
                if kill_on_cap:
                    print(f"  [{item.role.name}] RSS {rss:.0f} MB over the {item.role.memory_cap_mb} MB cap -- killing")
                    _terminate(item.process)
        time.sleep(sample_every)
    roles = []
    for item in running:
        denied = _denied(item.receipt_path)
        roles.append(
            {
                "role": item.role.name,
                "cap_mb": item.role.memory_cap_mb,
                "peak_rss_mb": round(item.peak_rss_mb, 1) if item.samples else None,
                "samples": item.samples,
                "cap_breaches": item.cap_breaches,
                "exit_code": item.process.poll(),
                "ran_seconds": round(time.time() - item.started_at, 1),
                "guard": item.receipt,
                "log": str(item.log_path),
                "network_attempts_denied": len(denied),
                "fleet_port_attempts_denied": sum(1 for row in denied if row.get("fleet_port")),
            }
        )
    return {
        # A GUARD RECEIPT IS NOT A HEALTHY ROLE. The first version of this
        # reported ok=True while all three roles had exited 1 — the receipt only
        # says the guard engaged, which happens before the role does any work.
        # A role that exited non-zero inside the window is a failure, and a role
        # that never got sampled is not evidence of anything either.
        "ok": all(r["guard"] and r["exit_code"] in (None, 0) for r in roles),
        "memory_enforcement": "WATCHDOG (RSS sampling), NOT a container limit"
        + ("" if psutil_available else " -- psutil MISSING, no samples taken"),
        "psutil_available": psutil_available,
        "roles": roles,
    }


def _denied(receipt_path: Path) -> list[dict[str, Any]]:
    path = receipt_path.with_suffix(".network.jsonl")
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except ValueError:
                rows.append({})
    return rows


def _print_report(report: dict[str, Any]) -> None:
    print()
    print(f"FLEET REPORT  ok={report['ok']}")
    print(f"  memory: {report['memory_enforcement']}")
    for row in report["roles"]:
        peak = f"{row['peak_rss_mb']} MB" if row["peak_rss_mb"] is not None else "not sampled"
        print(
            f"  [{row['role']:17}] peak {peak:>12} of {row['cap_mb']} MB cap "
            f"({row['samples']} samples, {row['cap_breaches']} breaches)  "
            f"exit={row['exit_code']}{' FAILED' if row['exit_code'] not in (None, 0) else ''}  ran {row['ran_seconds']}s  "
            f"denied outbound={row['network_attempts_denied']} (fleet ports {row['fleet_port_attempts_denied']})"
        )
        if not row["guard"]:
            print("        NO GUARD RECEIPT -- this role is not attested and was not trusted")


def cmd_down(args: argparse.Namespace) -> int:
    """There is no daemon: `up` owns its children and reaps them on exit. This
    exists so `down` is not a missing verb, and to clear a stale guard dir.
    The rehearsal snapshot (`.fleet_local/env/`) and logs are kept."""
    mirror = rehearsal_mirror(args.mirror)
    root = state_dir(mirror)
    if not root.exists():
        print(f"nothing to clear at {root}")
        return 0
    for name in ("guard", "receipts"):
        shutil.rmtree(root / name, ignore_errors=True)
    print(f"cleared {root / 'guard'} and {root / 'receipts'} (logs kept at {root / 'logs'}, "
          f"snapshot kept at {default_env_dir(mirror)})")
    print("NOTE: `up` runs in the foreground and terminates its own children, so")
    print("there is no background fleet for this to stop.")
    return 0


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mirror", help="mirror root (else SYNDICATE_MIRROR_ROOT)")
    parser.add_argument("--env-snapshot",
                        help="the rehearsal snapshot DIRECTORY written by `snapshot` (default <mirror>/.fleet_local/env)")
    parser.add_argument("--spec-only", action="store_true",
                        help="rehearse on fleet_role_spec.json alone (undeclared run-mode keys absent; labelled)")
    parser.add_argument(
        "--roles",
        default="web,refresh-worker,live-odds-worker",
        help="comma-separated subset of the three roles",
    )
    parser.add_argument("--fetch", choices=("replay", "live"), default="replay",
                        help="replay (default) denies every non-loopback connection and records it")
    parser.add_argument("--state", choices=("file", "redis"), default="file")
    parser.add_argument("--redis-url", help="a rehearsal redis for --state redis (never the fleet's port 6379)")
    parser.add_argument("--port", type=int, default=5000, help="this run's web port (every role's web URL)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_snapshot = sub.add_parser("snapshot", help="write a credential-free copy of the fleet's fleet_env/")
    p_snapshot.add_argument("--fleet-home", required=True, help="the fleet's home (~/syndicate-prod), which holds fleet_env/")
    p_snapshot.add_argument("--out", help="directory to write (default <mirror>/.fleet_local/env)")
    p_snapshot.set_defaults(func=cmd_snapshot)

    p_doctor = sub.add_parser("doctor", help="prove the guards engage; start nothing")
    p_doctor.set_defaults(func=cmd_doctor)

    p_up = sub.add_parser("up", help="start the roles")
    p_up.add_argument("--duration-seconds", type=float, default=60.0)
    p_up.add_argument("--sample-seconds", type=float, default=2.0)
    p_up.add_argument("--bounded", action="store_true", help="ask the workers for a single pass (--run-once)")
    p_up.add_argument("--kill-on-cap", action="store_true", help="terminate a role that exceeds its cap")
    p_up.add_argument("--write", help="write the JSON report here")
    p_up.set_defaults(func=cmd_up)

    p_down = sub.add_parser("down", help="clear guard/receipt state")
    p_down.set_defaults(func=cmd_down)

    args = parser.parse_args(argv)
    args.roles = [r.strip() for r in str(args.roles).split(",") if r.strip()]
    unknown = [r for r in args.roles if r not in ROLES]
    if unknown:
        parser.error(f"unknown role(s): {', '.join(unknown)}. known: {', '.join(ROLES)}")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(list(argv if argv is not None else sys.argv[1:]))
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
