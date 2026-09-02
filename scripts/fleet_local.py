"""Run the three Syndicate services locally, with production run-modes and no
way to spend money or touch production. `todo.md #625` build item (4).

    py -3 scripts/fleet_local.py doctor          # prove the guards engage; starts nothing
    py -3 scripts/fleet_local.py up --duration-seconds 120
    py -3 scripts/fleet_local.py up --roles web --fetch live
    py -3 scripts/fleet_local.py down

WHAT "PRODUCTION RUN-MODES" MEANS AND WHY IT IS THE HARD PART
-------------------------------------------------------------
The three roles are not three copies of one program. They are the SAME code
with different env, and the env is what decides which loops run — `#625`'s own
practicals and this repo's standing rule both say so ("loop ownership is an env
flag that moves with no diff"). Measured 2026-09-02, the live services differ on
**137 of 194 keys**, and the differences are the product: `SYNDICATE_REFRESH_LANE`,
`SYNDICATE_WEB_DYNO`, `SYNDICATE_MLB_REFRESH_TICK_OWNER`,
`SYNDICATE_ENABLE_LIVE_ODDS_REFRESH_LOOP`, and two dozen `*_ENABLE_*_AUTORUN`
flags.

So this runner does NOT invent a local configuration. It starts from a snapshot
of the real env and CHANGES AS LITTLE AS POSSIBLE — because a local fleet whose
config is hand-written reproduces a machine nobody runs, which is the failure
`#625` exists to end.

WHAT IT CHANGES, AND WHY EACH ONE
---------------------------------
Everything else is passed through verbatim.

FORCED (the run would be unsafe or wrong without it):
  SYNDICATE_EXECUTION_MODE=paper       real orders (see the money block below)
  SYNDICATE_EXECUTION_LIVE_ARMED=0     the second, independent arm switch
  SYNDICATE_EXECUTION_ENABLED=0        the loop that would place them
  SYNDICATE_DATA_ROOT / _REPORTS_ROOT  the local mirror, never a Render path
  SYNDICATE_REFRESH_STATE_BACKEND      file by default; redis only if asked
  SYNDICATE_BOOTSTRAP_ON_START=0       seeding the checkout over the mirror
                                       would overwrite the fixture under test

DROPPED (a credential this process must not hold):
  KALSHI_*, POLYMARKET_*               nothing left to sign an order with
  ODDS_API_KEY / CFBD_API_KEY          a shared, metered budget -- the OddsAPI
                                       cap is 5M calls and CFBD's month is
                                       already exhausted (`#633`)
  ADMIN_TOKEN, SYNDICATE_WEB_PUBLISH_URL   production WRITE paths
  REDIS_URL / keyvalue URL             production's shared state store; a local
                                       worker writing run manifests into it
                                       would corrupt production's own

THE MONEY BLOCK, WHICH IS THE ACTUAL POINT OF THIS TOOL
--------------------------------------------------------
Read off the live services on 2026-09-02, live-odds-worker runs
`SYNDICATE_EXECUTION_MODE=live`, `SYNDICATE_EXECUTION_LIVE_ARMED=1`,
`SYNDICATE_EXECUTION_ENABLED=1`, `SYNDICATE_EXECUTION_VENUE=kalshi,polymarket`,
with a real `KALSHI_PRIVATE_KEY` and `POLYMARKET_US_PRIVATE_KEY` (both also on
refresh-worker) and day caps of $40 / $150. **Running that env on a laptop
places real orders.** Three independent things must therefore hold, and the
child asserts all three itself in `scripts/_fleet_guard.py` rather than trusting
this file's scrub — because a scrub is a thing that can be mis-edited, and the
guard is what makes the failure loud instead of expensive.

FETCH MODE IS EXPLICIT, AND REPLAY IS THE DEFAULT (`#625` law 3)
-----------------------------------------------------------------
In replay mode every outbound connection is denied and recorded; loopback is
allowed so the roles can talk to each other and to a local redis. `--fetch live`
opts in, and the receipt records that it did, so a run that spent real quota is
identifiable afterwards rather than reconstructed.

MEMORY CAPS ARE A WATCHDOG, NOT A CONTAINER — SAID PLAINLY
-----------------------------------------------------------
`#625` asks for "optional memory-capped containers at 2/2/4GB". This runs
processes, not containers, so the caps are enforced by SAMPLING RSS and acting,
not by the kernel. That is a weaker guarantee and it is labelled as one
everywhere it is reported: a process can exceed the cap between samples, and a
sudden allocation can outrun the sampler entirely. It is useful for the slow
ratchet this repo actually sees (`refresh-worker memory is boot-confounded`,
`worker periodic work is never free`), and it is NOT evidence about what Render
would do at its own ceiling.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts._fleet_guard import (  # noqa: E402
    MODE_ENV,
    RECEIPT_ENV,
    ROLE_ENV,
    SHARED_BUDGET_ENV,
    VENUE_CREDENTIAL_ENV,
)

STATE_DIRNAME = ".fleet_local"

# Straight from `render.yaml`. The start commands are the production ones; the
# memory caps are the Render plans (standard 2GB, pro 4GB).
@dataclass(frozen=True)
class Role:
    name: str
    command: tuple[str, ...]
    memory_cap_mb: int
    render_plan: str
    note: str
    bounded_command: tuple[str, ...] = ()
    """A variant used by `--bounded`: the same entrypoint asked to do one pass
    rather than loop forever. Only the workers have one."""


ROLES: dict[str, Role] = {
    "web": Role(
        name="web",
        # gunicorn in production. Locally we run the same WSGI app through the
        # same server when it is importable, and fall back to Flask's own
        # server on Windows, where gunicorn does not run at all. The fallback is
        # REPORTED, never silent: it is a different server and a reader must be
        # able to tell which one produced a reading.
        command=("gunicorn", "wsgi:application", "--bind", "127.0.0.1:{port}", "--workers", "1", "--threads", "4"),
        memory_cap_mb=2048,
        render_plan="standard",
        note="serves artifacts; does no heavy computation (CLAUDE.md's load-bearing rule)",
    ),
    "refresh-worker": Role(
        name="refresh-worker",
        command=(sys.executable, "scripts/run_refresh_worker.py"),
        bounded_command=(sys.executable, "scripts/run_refresh_worker.py", "--run-once"),
        memory_cap_mb=4096,
        render_plan="pro",
        note="sims, artifacts, evaluation; owns the intelligence-state loop",
    ),
    "live-odds-worker": Role(
        name="live-odds-worker",
        command=(sys.executable, "scripts/run_live_odds_refresh_worker.py"),
        bounded_command=(sys.executable, "scripts/run_live_odds_refresh_worker.py", "--run-once"),
        memory_cap_mb=2048,
        render_plan="standard",
        note="odds capture and the live tier; in production this is the role that TRADES",
    ),
}

FORCED_ENV_BASE: dict[str, str] = {
    "SYNDICATE_EXECUTION_MODE": "paper",
    "SYNDICATE_EXECUTION_LIVE_ARMED": "0",
    "SYNDICATE_EXECUTION_ENABLED": "0",
    # Seeding the git checkout over the mirror would overwrite the very fixture
    # a local run is supposed to be reading.
    "SYNDICATE_BOOTSTRAP_ON_START": "0",
    # `data_root()` raises instead of falling back when this is set, which is
    # right on Render and wrong here.
    "RENDER": "",
    "PYTHONIOENCODING": "utf-8",
    "PYTHONUNBUFFERED": "1",
}

DROPPED_ENV: tuple[str, ...] = VENUE_CREDENTIAL_ENV + SHARED_BUDGET_ENV + (
    "RENDER_API_KEY",
    "REDIS_URL",
    "SYNDICATE_KEYVALUE_URL",
    "ANTHROPIC_API_KEY",
    # Per-sport source roots and live-lens dirs point at Render paths and would
    # silently win over SYNDICATE_DATA_ROOT (`source_roots.py:117-120`, and the
    # live-lens dirs are read at IMPORT time).
    *[f"SYNDICATE_{sport}_SOURCE_ROOT" for sport in ("MLB", "NBA", "WNBA", "NHL", "NFL", "NCAAF", "NCAAB", "SOCCER")],
    *[f"{sport}_LIVE_LENS_DIR" for sport in ("MLB", "NBA", "NHL", "WNBA")],
    *[f"{sport}_BETTING_DATA_ROOT" for sport in ("MLB", "NBA", "WNBA")],
)


def state_dir(mirror: Path) -> Path:
    return mirror / STATE_DIRNAME


def load_env_snapshot(path: Path | None) -> tuple[dict[str, dict[str, str]], dict[str, int]]:
    """Load a `#625`(3) env snapshot. Returns (values, withheld-count per service).

    Deliberately a FILE, not a live Render call: a fleet that reads production
    config at start time is a fleet whose behaviour changes when somebody edits
    an env var, and `#625`(3) already produces dated snapshots for exactly this.

    **THE SNAPSHOT'S SECRET-WITHHOLDING IS THIS RUNNER'S STRONGEST CREDENTIAL
    SCRUB, and it is structural rather than a list I maintain.**
    `snapshot_render_env.py` records `{len, sha256_12}` for every value and a
    plaintext `value` ONLY where it has established the key cannot be a
    credential. So a secret is not something this runner has to remember to
    drop — it was never in the file to begin with, and no future key added to
    production can leak through by being absent from `DROPPED_ENV`. The
    deny-list stays as the second mechanism, and the child's guard as the third.
    """
    if path is None:
        raise SystemExit(
            "no env snapshot. Pass --env-snapshot <file.json>.\n"
            "Produce one with:  py -3 scripts/snapshot_render_env.py --out <dir>"
        )
    if not path.is_file():
        raise SystemExit(f"env snapshot not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    services = payload.get("services") if isinstance(payload, dict) else None
    if not isinstance(services, dict):
        raise SystemExit(
            f"{path} is not a snapshot_render_env.py file (no `services` block)."
        )
    values: dict[str, dict[str, str]] = {}
    withheld: dict[str, int] = {}
    for service, block in services.items():
        keys = (block or {}).get("keys") if isinstance(block, dict) else None
        if not isinstance(keys, dict):
            continue
        kept: dict[str, str] = {}
        hidden = 0
        for key, entry in keys.items():
            if isinstance(entry, dict) and "value" in entry:
                kept[str(key)] = str(entry["value"])
            else:
                hidden += 1
        values[str(service)] = kept
        withheld[str(service)] = hidden
    return values, withheld


def derive_env(
    role: Role,
    snapshot: dict[str, str],
    *,
    mirror: Path,
    fetch: str,
    state_backend: str,
    receipt_path: Path,
    guard_dir: Path,
    port: int,
) -> tuple[dict[str, str], dict[str, Any]]:
    """Production env in, safe env out. Returns (env, an auditable diff)."""
    env = dict(os.environ)
    # Start from the production snapshot so the RUN-MODES are production's.
    env.update(snapshot)

    dropped = sorted({name for name in DROPPED_ENV if name in env and str(env.get(name) or "").strip()})
    for name in DROPPED_ENV:
        env.pop(name, None)

    forced: dict[str, str] = dict(FORCED_ENV_BASE)
    forced["SYNDICATE_DATA_ROOT"] = str(mirror)
    forced["SYNDICATE_REPORTS_ROOT"] = str(state_dir(mirror) / "reports" / role.name)
    forced["SYNDICATE_REFRESH_STATE_BACKEND"] = state_backend
    if state_backend == "file":
        # MEASURED: both workers REFUSE to start on a file backend --
        # `assert_refresh_state_backend_ready` raises "Local state backend not
        # allowed in multi-service deployment" (`refresh_state_store.py:316`)
        # whenever `SYNDICATE_REQUIRE_HOSTED_STORAGE` is truthy, and production
        # sets it to `true` on all three services. Clearing `RENDER` alone is
        # not enough; the predicate is an OR of the two.
        #
        # This is a legitimate forced override rather than a workaround: the
        # assertion exists because on Render the three services do NOT share a
        # disk, so a file backend would silently give each its own state. On one
        # laptop they DO share it, which is the condition the assertion is
        # protecting, so declaring that is telling the truth. With
        # `--state redis` the flag is left exactly as production has it.
        forced["SYNDICATE_REQUIRE_HOSTED_STORAGE"] = ""
    forced[ROLE_ENV] = role.name
    forced[MODE_ENV] = fetch
    forced[RECEIPT_ENV] = str(receipt_path)
    if role.name == "web":
        forced["PORT"] = str(port)
    changed = {k: v for k, v in forced.items() if env.get(k) != v}
    for key, value in forced.items():
        if value == "":
            env.pop(key, None)
        else:
            env[key] = value

    # The guard directory FIRST, so `sitecustomize` resolves to ours.
    existing = env.get("PYTHONPATH") or ""
    env["PYTHONPATH"] = os.pathsep.join([str(guard_dir), str(REPO_ROOT)] + ([existing] if existing else []))
    return env, {
        "dropped": dropped,
        "forced": {k: ("<local path>" if "ROOT" in k else v) for k, v in changed.items()},
        "passed_through": len(snapshot) - len(dropped),
    }


def write_guard_dir(target: Path) -> Path:
    """Generate the `sitecustomize.py` CPython imports at interpreter startup.

    This is the ONLY hook that reaches every role: gunicorn and
    `python scripts/run_*.py` share no entrypoint, so a guard installed in one
    would miss the others.
    """
    target.mkdir(parents=True, exist_ok=True)
    (target / "sitecustomize.py").write_text(
        '"""GENERATED by scripts/fleet_local.py -- do not edit; it is rewritten on every `up`.\n'
        "\n"
        "CPython imports this during interpreter startup, before __main__, which is\n"
        "why it reaches gunicorn as well as a plain script. It engages the local\n"
        "fleet guard and RAISES if money could be spent -- see scripts/_fleet_guard.py.\n"
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


def cmd_doctor(args: argparse.Namespace) -> int:
    """Prove the guards would engage. Starts no role."""
    from scripts.mirror_manifest import mirror_root

    mirror = mirror_root(args.mirror)
    snapshot, withheld = load_env_snapshot(Path(args.env_snapshot) if args.env_snapshot else None)
    guard_dir = write_guard_dir(state_dir(mirror) / "guard")
    print(f"FLEET DOCTOR   mirror={mirror}")
    print(f"  env snapshot   {args.env_snapshot}")
    for service in sorted(snapshot):
        print(f"     {service:18} {len(snapshot[service])} plaintext keys, "
              f"{withheld.get(service, 0)} withheld as possible credentials (never on disk)")

    ok_all = True
    for name in args.roles:
        role = ROLES[name]
        service_env = snapshot.get(name) or {}
        if not service_env:
            print(f"\n  [{name}] NO SNAPSHOT for this service -- refusing to guess a config.")
            ok_all = False
            continue
        receipt = state_dir(mirror) / "receipts" / f"{name}.doctor.json"
        env, diff = derive_env(
            role,
            service_env,
            mirror=mirror,
            fetch=args.fetch,
            state_backend=args.state,
            receipt_path=receipt,
            guard_dir=guard_dir,
            port=args.port,
        )
        print(f"\n  [{name}]  plan={role.render_plan}  cap={role.memory_cap_mb} MB")
        print(f"      snapshot keys {len(service_env)}, dropped {len(diff['dropped'])}, forced {len(diff['forced'])}")
        if diff["dropped"]:
            print(f"      DROPPED  {', '.join(diff['dropped'])}")

        resolved_ok, detail = resolve_sitecustomize(guard_dir, env)
        print(f"      sitecustomize {'OK' if resolved_ok else 'WRONG'}  {detail}")
        ok_all = ok_all and resolved_ok

        # Does the guard actually ENGAGE, and does it REFUSE a money-armed env?
        probe = subprocess.run(
            [sys.executable, "-c", "pass"], env=env, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=120
        )
        engaged = receipt.is_file() and probe.returncode == 0
        print(f"      guard engaged {'YES' if engaged else 'NO'}  (rc={probe.returncode})")
        if engaged:
            payload = json.loads(receipt.read_text(encoding="utf-8"))
            for reason in payload.get("money_off_because") or []:
                print(f"        money off: {reason}")
            print(f"        network:   {payload.get('network')}")
            if payload.get("shared_budget_credentials_present"):
                print(f"        WARNING shared-budget creds still present: {payload['shared_budget_credentials_present']}")
                ok_all = False
        else:
            print(f"        stderr: {(probe.stderr or '').strip()[-400:]}")
            ok_all = False

        # NEGATIVE CONTROL: re-arm money and require the guard to REFUSE.
        # A guard that has only ever been seen to pass is not known to be a guard.
        armed = dict(env)
        armed["SYNDICATE_EXECUTION_MODE"] = "live"
        armed["SYNDICATE_EXECUTION_LIVE_ARMED"] = "1"
        refusal = subprocess.run(
            [sys.executable, "-c", "pass"], env=armed, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=120
        )
        refused = refusal.returncode != 0 and "could spend money" in (refusal.stderr or "").lower()
        print(f"      REFUSES a money-armed env: {'YES' if refused else 'NO'}  (rc={refusal.returncode})")
        ok_all = ok_all and refused

    print()
    print("DOCTOR: " + ("READY" if ok_all else "NOT READY -- do not start the fleet"))
    return 0 if ok_all else 1


def cmd_up(args: argparse.Namespace) -> int:
    from scripts.mirror_manifest import mirror_root

    mirror = mirror_root(args.mirror)
    snapshot, withheld = load_env_snapshot(Path(args.env_snapshot) if args.env_snapshot else None)
    root = state_dir(mirror)
    guard_dir = write_guard_dir(root / "guard")
    (root / "logs").mkdir(parents=True, exist_ok=True)
    (root / "receipts").mkdir(parents=True, exist_ok=True)

    print(f"FLEET UP   mirror={mirror}   fetch={args.fetch}   state={args.state}")
    for service in sorted(snapshot):
        print(f"  {service:18} {len(snapshot[service])} plaintext keys, {withheld.get(service, 0)} withheld")
    running: list[RunningRole] = []
    try:
        for index, name in enumerate(args.roles):
            role = ROLES[name]
            service_env = snapshot.get(name) or {}
            if not service_env:
                print(f"  [{name}] NO SNAPSHOT -- skipped rather than guessed.")
                continue
            receipt = root / "receipts" / f"{name}.json"
            receipt.unlink(missing_ok=True)
            log_path = root / "logs" / f"{name}.log"
            env, diff = derive_env(
                role,
                service_env,
                mirror=mirror,
                fetch=args.fetch,
                state_backend=args.state,
                receipt_path=receipt,
                guard_dir=guard_dir,
                port=args.port + index,
            )

            resolved_ok, detail = resolve_sitecustomize(guard_dir, env)
            if not resolved_ok:
                print(f"  [{name}] REFUSING TO START: the guard would not load -- {detail}")
                continue

            command = list(role.bounded_command or role.command) if args.bounded else list(role.command)
            command = [part.format(port=env.get("PORT", str(args.port))) if isinstance(part, str) else part for part in command]
            if role.name == "web" and not _gunicorn_usable():
                # REPORTED, not silent: a different server can produce different
                # readings, and a reader has to know which one ran.
                command = [sys.executable, "-m", "flask", "--app", "wsgi:application", "run",
                           "--port", env.get("PORT", str(args.port)), "--no-reload"]
                print(f"  [{name}] gunicorn is not USABLE here (on Windows it imports fcntl, which "
                      "does not exist) -- falling back to the Flask dev server. This is NOT the "
                      "production server; do not read performance or concurrency from it.")

            handle = log_path.open("w", encoding="utf-8", errors="replace")
            process = subprocess.Popen(
                command, cwd=str(REPO_ROOT), env=env, stdout=handle, stderr=subprocess.STDOUT
            )
            running.append(RunningRole(role=role, process=process, receipt_path=receipt, log_path=log_path, started_at=time.time()))
            print(f"  [{name}] pid={process.pid}  cap={role.memory_cap_mb} MB  log={log_path}")
            print(f"           dropped {len(diff['dropped'])} credential/root vars, forced {len(diff['forced'])}, "
                  f"passed through {diff['passed_through']} production keys")

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


def _gunicorn_usable() -> bool:
    """Can gunicorn actually RUN, not merely be on PATH?

    `shutil.which("gunicorn")` returns a path on Windows — pip installs a `.exe`
    shim — and gunicorn then dies on `import fcntl`, which does not exist on
    Windows. Measured: the shim was found, the role started, and the log said
    `ModuleNotFoundError: No module named 'fcntl'`. Presence is not
    reachability, in the harness that exists to check exactly that.
    """
    if shutil.which("gunicorn") is None:
        return False
    probe = subprocess.run(
        [sys.executable, "-c", "import gunicorn.util"], capture_output=True, text=True, timeout=60
    )
    return probe.returncode == 0


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
                "network_attempts_denied": _count_denied(item.receipt_path),
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


def _count_denied(receipt_path: Path) -> int:
    path = receipt_path.with_suffix(".network.jsonl")
    if not path.is_file():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


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
            f"denied outbound={row['network_attempts_denied']}"
        )
        if not row["guard"]:
            print("        NO GUARD RECEIPT -- this role is not attested and was not trusted")


def cmd_down(args: argparse.Namespace) -> int:
    """There is no daemon: `up` owns its children and reaps them on exit. This
    exists so `down` is not a missing verb, and to clear a stale guard dir."""
    from scripts.mirror_manifest import mirror_root

    mirror = mirror_root(args.mirror)
    root = state_dir(mirror)
    if not root.exists():
        print(f"nothing to clear at {root}")
        return 0
    for name in ("guard", "receipts"):
        shutil.rmtree(root / name, ignore_errors=True)
    print(f"cleared {root / 'guard'} and {root / 'receipts'} (logs kept at {root / 'logs'})")
    print("NOTE: `up` runs in the foreground and terminates its own children, so")
    print("there is no background fleet for this to stop.")
    return 0


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mirror", help="mirror root (else SYNDICATE_MIRROR_ROOT)")
    parser.add_argument("--env-snapshot", help="per-service env snapshot JSON (`#625`(3))")
    parser.add_argument(
        "--roles",
        default="web,refresh-worker,live-odds-worker",
        help="comma-separated subset of the three roles",
    )
    parser.add_argument("--fetch", choices=("replay", "live"), default="replay",
                        help="replay (default) denies every non-loopback connection and records it")
    parser.add_argument("--state", choices=("file", "redis"), default="file")
    parser.add_argument("--port", type=int, default=5000)
    sub = parser.add_subparsers(dest="command", required=True)

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
