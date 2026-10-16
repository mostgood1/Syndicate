"""Parity gate: the NATIVE MLB daily sim (syndicate/features/mlb/native/tools/daily_update.py) == the vendored one.

Lane mlb-daily-sim-native-p3 (2026-10-16). Fleet-side (Linux). The daily sim spans processes (daily_update ->
daily_update_multi_profile -> multiprocessing workers -> eval/tune/statcast scripts), and its request caches expire on
the wall clock, so a record/replay tape would have to follow every process and freeze every clock. This uses a
SAME-INSTANT design instead:

  three arms run CONCURRENTLY, each from its OWN copy of the fleet checkout and its OWN copy of the MLB data:
    vendored  vendor/mlb_bettingv2/tools/daily_update.py   (production today)
    native    syndicate/features/mlb/native/tools/daily_update.py
    vself     the vendored script again -- the NOISE FLOOR (what two identical runs differ by)
  native vs vendored must sit at that floor: every leaf that differs between them must also differ vendored vs vself
  (wall clock, network jitter), and nothing else may.

Each arm runs the exact argv scripts/run_mlb_daily_sim_job.py builds (its publish step is NOT run: no shared state is
touched), with the refresh-worker's own environment read as a dict from /proc (never printed) and every path under
the production data root / fleet checkout remapped onto the arm's copies. A `sitecustomize` on PYTHONPATH records, in
every python process of every arm, which modules it loaded from vendor/ and its argv -- so "the native run imports and
launches nothing vendored" is measured across the whole process tree, not assumed.

  prepare  copy the checkout + MLB data once to a snapshot, fan out to the 3 arms, overlay the worktree's MLB code
  run      start the 3 arms at once (nice 19), wait, write <work>/run.json
  compare  file-by-file, leaf-by-leaf, against the noise floor; `--plant` must be reported

Usage (fleet):
  python scripts/mlb_daily_sim_parity.py prepare --work W --overlay /mnt/c/.../worktree
  PYTHONHASHSEED=0 python scripts/mlb_daily_sim_parity.py run --work W --date D --season 2026 --sims 200 --only-game-pks PK
  python scripts/mlb_daily_sim_parity.py compare --work W [--plant]
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ARMS = ("vendored", "native", "vself")
FLEET_CHECKOUT = Path("/home/amyn/Syndicate")
PROD_DATA = Path("/home/amyn/syndicate-prod/data")
#: The daily sim reads the MLB trees only; copying the whole prod data root (all sports) would be ~10x the bytes.
DATA_SUBTREES = ("mlb_source",)
SCRIPT = {"vendored": "vendor/mlb_bettingv2/tools/daily_update.py", "vself": "vendor/mlb_bettingv2/tools/daily_update.py",
          "native": "syndicate/features/mlb/native/tools/daily_update.py"}
#: Leaf NAMES that are wall-clock or process identity by construction -- needed only where two runs happen to agree on
#: one by luck in the floor pair (the vself floor already excuses everything that differs between identical runs).
#: Every ignored diff is still counted and listed.
_IGNORE_SNAKE = re.compile(r"(?i)^(?:.*_)?(?:generated|recorded|updated|created|started|finished|completed|modified|fetched)_at$"
                           r"|^(?:.*_)?(?:timestamp|run_stamp|runstamp|hostname|pid|elapsed_s|elapsed_ms|duration_s|duration_ms)$")
_IGNORE_CAMEL = re.compile(r"^[a-z][A-Za-z0-9]*(?:At|Ms)$")


class _Ignore:
    @staticmethod
    def search(name: str) -> bool:
        return bool(_IGNORE_SNAKE.search(name) or _IGNORE_CAMEL.search(name))


IGNORE_LEAF = _Ignore()

SITECUSTOMIZE = r'''
import atexit, json, os, sys
_out = os.environ.get("MLB_PARITY_TRACE_DIR")
if _out:
    def _dump():
        try:
            vend = sorted(n for n, m in list(sys.modules.items())
                          if "/vendor/" in (getattr(m, "__file__", "") or "").replace("\\", "/"))
            with open(os.path.join(_out, f"proc_{os.getpid()}.json"), "w", encoding="utf-8") as fh:
                json.dump({"pid": os.getpid(), "argv": sys.argv, "vendored_modules": vend}, fh)
        except Exception:
            pass
    atexit.register(_dump)
'''


def _sh(cmd: list[str]) -> None:
    subprocess.run(["nice", "-n", "19", *cmd], check=True)


def cmd_prepare(args) -> int:
    work = Path(args.work)
    if work.exists():
        shutil.rmtree(work)
    snap = work / "snap"
    (snap / "data").mkdir(parents=True)
    # ONE copy of the live trees, then every arm from it (arms copied at different moments differ by exactly that).
    _sh(["rsync", "-a", "--exclude=.git", "--exclude=__pycache__", f"{FLEET_CHECKOUT}/", f"{snap}/Syndicate/"])
    for sub in DATA_SUBTREES:
        _sh(["cp", "-a", str(PROD_DATA / sub), str(snap / "data" / sub)])
    overlay = Path(args.overlay) / "syndicate" / "features" / "mlb"
    _sh(["rsync", "-a", "--exclude=__pycache__", f"{overlay}/", f"{snap}/Syndicate/syndicate/features/mlb/"])
    for arm in ARMS:
        _sh(["cp", "-a", str(snap), str(work / arm)])
        (work / arm / "trace").mkdir()
        (work / arm / "site").mkdir()
        (work / arm / "site" / "sitecustomize.py").write_text(SITECUSTOMIZE, encoding="utf-8")
    shutil.rmtree(snap)
    print(json.dumps({"work": str(work), "arms": list(ARMS)}))
    return 0


def _worker_env() -> dict[str, str]:
    pid = subprocess.run(["pgrep", "-f", "scripts/[r]un_refresh_worker.py"], capture_output=True, text=True).stdout.split()[0]
    raw = Path(f"/proc/{pid}/environ").read_bytes().decode("utf-8", "replace").split("\0")
    return dict(kv.split("=", 1) for kv in raw if "=" in kv)


def _arm_env(base: dict[str, str], arm_dir: Path) -> dict[str, str]:
    env = {}
    for k, v in base.items():
        v = v.replace(str(PROD_DATA), str(arm_dir / "data")).replace(str(FLEET_CHECKOUT), str(arm_dir / "Syndicate"))
        env[k] = v
    env["PYTHONPATH"] = os.pathsep.join([str(arm_dir / "site"), env["PYTHONPATH"]] if env.get("PYTHONPATH") else [str(arm_dir / "site")])
    env["MLB_PARITY_TRACE_DIR"] = str(arm_dir / "trace")
    env["PYTHONHASHSEED"] = "0"
    env["ODDS_API_KEY"] = ""  # the job runs with --refresh-current-oddsapi off; nothing here may spend OddsAPI calls
    env.pop("SYNDICATE_MLB_ROSTER_REBUILD_DATE", None)  # read by the job wrapper only; the argv below is explicit
    return env


def _job_argv(args) -> list[str]:
    """scripts/run_mlb_daily_sim_job.py's command, minus the interpreter and script."""
    argv = ["--workflow", "ui-daily", "--date", args.date, "--season", args.season, "--sims", str(args.sims),
            "--workers", str(args.workers), "--git-push", "off", "--validate-render-frontend", "off",
            "--build-next-day", "off", "--allow-empty-current-oddsapi", "on", "--refresh-current-oddsapi", "off"]
    if args.only_game_pks:
        argv += ["--only-game-pks", args.only_game_pks]
    return argv


def cmd_run(args) -> int:
    work = Path(args.work)
    base = _worker_env()
    started = time.time()
    procs = {}
    for arm in ARMS:
        arm_dir = work / arm
        cwd = arm_dir / "Syndicate" / "vendor" / "mlb_bettingv2"
        script = arm_dir / "Syndicate" / SCRIPT[arm]
        log = open(arm_dir / "run.log", "w", encoding="utf-8")
        procs[arm] = (subprocess.Popen(["nice", "-n", "19", sys.executable, str(script), *_job_argv(args)], cwd=cwd,
                                       env=_arm_env(base, arm_dir), stdout=log, stderr=subprocess.STDOUT), log)
    rcs = {}
    for arm, (p, log) in procs.items():
        rcs[arm] = p.wait()
        log.close()
    out = {"started": started, "finished": time.time(), "rc": rcs, "argv": _job_argv(args)}
    (work / "run.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out))
    return 0 if all(v == 0 for v in rcs.values()) else 2


# ------------------------------------------------------------------------------------------------------------ compare


def _changed_files(arm_dir: Path, since: float) -> dict[str, Path]:
    out = {}
    for root in (arm_dir / "data", arm_dir / "Syndicate"):
        for p in root.rglob("*"):
            if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc":
                try:
                    if p.stat().st_mtime >= since:
                        out[str(p.relative_to(arm_dir))] = p
                except OSError:
                    pass
    return out


def _load(p: Path) -> Any:
    raw = p.read_bytes()
    if p.suffix == ".json":
        try:
            return json.loads(raw)
        except ValueError:
            pass
    if p.suffix == ".jsonl":
        try:
            return [json.loads(x) for x in raw.decode("utf-8").splitlines() if x.strip()]
        except ValueError:
            pass
    if p.suffix == ".csv":
        try:
            return list(csv.reader(io.StringIO(raw.decode("utf-8"))))
        except (UnicodeDecodeError, csv.Error):
            pass
    return {"__bytes__": raw.hex() if len(raw) < 4096 else f"{len(raw)}:{hash(raw)}"}


def _leaves(a: Any, b: Any, path: str, out: list[str], header: list[str] | None = None) -> int:
    n = 0
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b), key=str):
            if k not in a or k not in b:
                out.append(f"{path}.{k}: only in {'A' if k in a else 'B'}")
                continue
            n += _leaves(a[k], b[k], f"{path}.{k}", out)
        return n
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append(f"{path}: len {len(a)} != {len(b)}")
        is_csv = a and all(isinstance(r, list) for r in a[:3])
        hdr = a[0] if is_csv else None
        for i, (x, y) in enumerate(zip(a, b)):
            if is_csv and i > 0 and isinstance(x, list) and isinstance(y, list):
                for j, (u, v) in enumerate(zip(x, y)):
                    n += 1
                    col = hdr[j] if hdr and j < len(hdr) else str(j)
                    if u != v:
                        out.append(f"{path}[{i}].{col}: {u[:60]!r} != {v[:60]!r}")
            else:
                n += _leaves(x, y, f"{path}[{i}]", out)
        return n
    if a != b:
        out.append(f"{path}: {str(a)[:60]!r} != {str(b)[:60]!r}")
    return 1


#: The change under test, as a value: the native arm runs (and its ops report records) the native copy of the script the
#: vendored arm runs. Mapped back before comparing -- COUNTED and reported, so it is a listed class, never a silent pass.
NATIVE_SCRIPTS = "<ARM>/Syndicate/syndicate/features/mlb/native/tools/"
VENDORED_SCRIPTS = "<ARM>/Syndicate/vendor/mlb_bettingv2/tools/"


def _map_native_scripts(obj: Any, counter: list[int]) -> Any:
    if isinstance(obj, str):
        if NATIVE_SCRIPTS in obj:
            counter[0] += obj.count(NATIVE_SCRIPTS)
            return obj.replace(NATIVE_SCRIPTS, VENDORED_SCRIPTS)
        return obj
    if isinstance(obj, list):
        return [_map_native_scripts(x, counter) for x in obj]
    if isinstance(obj, dict):
        return {k: _map_native_scripts(v, counter) for k, v in obj.items()}
    return obj


def _normalize(obj: Any, arm_dir: Path) -> Any:
    """Each arm's own directory -> "<ARM>" in every string, so a path differs only by what follows it. Without this every
    absolute path differs between EVERY pair of arms, the floor excuses it, and a native script path recorded where the
    vendored one was would hide inside the noise."""
    prefix = str(arm_dir)
    if isinstance(obj, str):
        return obj.replace(prefix, "<ARM>")
    if isinstance(obj, list):
        return [_normalize(x, arm_dir) for x in obj]
    if isinstance(obj, dict):
        return {str(k).replace(prefix, "<ARM>"): _normalize(v, arm_dir) for k, v in obj.items()}
    return obj


def _diff(arm_a: Path, arm_b: Path, since: float, plant: bool = False, map_scripts: bool = False) -> dict:
    fa, fb = _changed_files(arm_a, since), _changed_files(arm_b, since)
    mapped = [0]
    diffs: list[str] = []
    leaves = 0
    for rel in sorted(set(fa) - set(fb)):
        diffs.append(f"{rel}: written only by A")
    for rel in sorted(set(fb) - set(fa)):
        diffs.append(f"{rel}: written only by B")
    planted = None
    for rel in sorted(set(fa) & set(fb)):
        if rel.endswith(("run.log",)) or "/trace/" in f"/{rel}" or rel.startswith(("trace/", "site/")):
            continue
        a, b = _normalize(_load(fa[rel]), arm_a), _normalize(_load(fb[rel]), arm_b)
        if map_scripts:
            b = _map_native_scripts(b, mapped)
        if plant and planted is None and isinstance(b, (dict, list)) and b:
            if isinstance(b, dict):
                k = next((k for k, v in b.items() if isinstance(v, (int, float)) and not isinstance(v, bool)), None)
                if k is not None:
                    b[k] = b[k] + 1
                    planted = f"{rel}.{k}"
        leaves += _leaves(a, b, rel, diffs)
    return {"files_a": len(fa), "files_b": len(fb), "leaves": leaves, "diffs": diffs, "planted": planted,
            "native_script_paths_mapped": mapped[0]}


def _key(d: str) -> str:
    """A diff's leaf path with indices folded, so the same leaf in different rows counts as one kind."""
    return re.sub(r"\[\d+\]", "[*]", d.split(": ", 1)[0])


def cmd_compare(args) -> int:
    work = Path(args.work)
    run = json.loads((work / "run.json").read_text(encoding="utf-8"))
    since = float(run["started"]) - 1
    floor = _diff(work / "vendored", work / "vself", since)
    test = _diff(work / "vendored", work / "native", since, plant=args.plant, map_scripts=True)
    floor_keys = {_key(d) for d in floor["diffs"]}
    def split(diffs):
        # A leaf under a `timings` object is a stopwatch reading by construction (`timings.explanation_diagnostics_s`
        # read 0.0 vs 0.001 s, 2026-10-16) -- the floor pair can agree on one by luck.
        ign = [d for d in diffs if IGNORE_LEAF.search(_key(d).rsplit(".", 1)[-1]) or ".timings." in _key(d)]
        rest = [d for d in diffs if d not in ign]
        return ign, rest
    t_ign, t_rest = split(test["diffs"])
    beyond_floor = [d for d in t_rest if _key(d) not in floor_keys]
    traces = {}
    for arm in ARMS:
        procs = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((work / arm / "trace").glob("proc_*.json"))]
        traces[arm] = {"processes": len(procs),
                       "processes_loading_vendor": sum(1 for p in procs if p["vendored_modules"]),
                       "vendored_scripts_run": sorted({a for p in procs for a in p["argv"][:1]
                                                       if "/vendor/" in a.replace("\\", "/")})}
    report = {
        "rc": run["rc"],
        "floor (vendored vs vself)": {"files": [floor["files_a"], floor["files_b"]], "leaves": floor["leaves"],
                                      "diffs": len(floor["diffs"]), "kinds": sorted(floor_keys)[:40]},
        "test (vendored vs native)": {"files": [test["files_a"], test["files_b"]], "leaves": test["leaves"],
                                      "diffs": len(test["diffs"]), "ignored_wallclock": len(t_ign),
                                      "beyond_floor": len(beyond_floor), "first_beyond_floor": beyond_floor[:25],
                                      "planted": test["planted"],
                                      "native_script_paths_mapped": test["native_script_paths_mapped"]},
        "trace": traces,
    }
    print(json.dumps(report, indent=1))
    native_clean = traces["native"]["processes"] > 0 and traces["native"]["processes_loading_vendor"] == 0 \
        and not traces["native"]["vendored_scripts_run"]
    if args.plant:
        return 0 if beyond_floor else 3
    return 0 if (not beyond_floor and native_clean and all(v == 0 for v in run["rc"].values())) else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--work", required=True)
    p.add_argument("--overlay", required=True, help="the worktree whose syndicate/features/mlb/ is under test")
    r = sub.add_parser("run")
    r.add_argument("--work", required=True)
    r.add_argument("--date", required=True)
    r.add_argument("--season", required=True)
    r.add_argument("--sims", type=int, default=200)
    r.add_argument("--workers", type=int, default=1)
    r.add_argument("--only-game-pks", default="")
    c = sub.add_parser("compare")
    c.add_argument("--work", required=True)
    c.add_argument("--plant", action="store_true")
    args = ap.parse_args(argv)
    return {"prepare": cmd_prepare, "run": cmd_run, "compare": cmd_compare}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
