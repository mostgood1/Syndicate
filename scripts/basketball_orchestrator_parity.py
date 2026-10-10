"""PARITY GATE for plan P6: the native smart-sim orchestrator against the vendored one, game for game.

Lane basketball-native-orchestrator. P1's tools (record_basketball_engine_corpus.py,
basketball_engine_parity.py) gate the possession ENGINE one draw at a time. This
gates the ORCHESTRATOR one GAME at a time: the whole ``simulate_smart_game`` call
plus the bridge's post-processing, i.e. the dict written to
``smart_sim_<date>_<H>_<A>.json``.

THE TWO ARMS. Both run the CURRENT bridge's ports. Only the orchestrator differs.
  native    ``basketball_props_smart_sim._call_source_simulate_smart_game_local``
            as it is now (syndicate/features/basketball_engine/orchestrator).
  vendored  the pre-P6 bridge functions, read by AST from git at
            ``VENDORED_ARM_COMMIT`` (``_vendor_smart_sim_code_root_local``,
            ``_import_real_smart_sim_module_local``, ``_build_local_smart_sim_module``,
            ``_call_source_simulate_smart_game_local``) and executed against the
            current module's namespace. That is the code production ran, so it is
            not a hand copy. It imports ``vendor/<pkg>_repo/src/<pkg>/sim/smart_sim.py``
            and patches its 29 names exactly as production did. It refuses if the
            vendored import fails, because the old flat fallback is not an arm.

SUBCOMMANDS
  record   Run the production entrypoint (``_smart_sim_run_date_local``, the call
           ``export_props_predictions_with_smart_sim_local`` makes) on a SCRATCH
           copy of ``<league>_source``, with ``--arm``, a fixed ``--seed`` and one
           worker. Every game call is saved: the kwargs as production built them,
           the global numpy/random RNG states before the call, the output, and its
           digest.
  replay   A FRESH process replays a corpus through one arm, games in recording
           order, restoring the RNG states. If the replay arm is the recording arm,
           the output digest must reproduce, which proves the corpus captured every
           input. Otherwise every leaf is compared with the recorded output.
  compare  End-to-end: the smart_sim_*.json two runs wrote, leaf for leaf (P1's
           ``compare_sim_artifacts``).
  compare-outputs  Two ``replay --save-outputs`` runs (one per arm, same checkout) against EACH OTHER.
           Use it after a shared port changed since recording, when the recorded output no longer applies.

SAFETY. ``--source-root`` must not be inside ``--prod-data-root``. ``--env-from-pid``
loads a fleet role's env as a Python dict from /proc/<pid>/environ (P1's
``load_role_env``): production-root values are redirected to the scratch root and
keyvalue/redis keys dropped. No value is printed. Run it at ``nice -n 19``.
"""

from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import json
import math
import os
import pickle
import random
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# The last commit on origin/main whose bridge still ran the VENDORED orchestrator.
VENDORED_ARM_COMMIT = "a1ee82cb"
_VENDORED_ARM_FUNCS = (
    "_vendor_smart_sim_code_root_local",
    "_import_real_smart_sim_module_local",
    "_build_local_smart_sim_module",
    "_call_source_simulate_smart_game_local",
    "_import_advanced_stats_builders_local",
)
BRIDGE_REL = "syndicate/features/shared/basketball_props_smart_sim.py"


def output_digest(out: Any) -> str:
    return hashlib.sha256(pickle.dumps(out, protocol=4)).hexdigest()


# --------------------------------------------------------------------------- leaf comparison
def leaf_compare(a: Any, b: Any, path: str = "$", diffs: list[str] | None = None, limit: int = 25) -> tuple[int, list[str]]:
    """(leaves compared, differences). Exact: floats bit for bit, NaN == NaN, types must match (int kinds aside)."""
    import numpy as np
    import pandas as pd

    diffs = [] if diffs is None else diffs
    n = 0

    def note(msg: str) -> None:
        if len(diffs) < limit:
            diffs.append(msg)

    if isinstance(a, dict) and isinstance(b, dict):
        if set(a) != set(b):
            note(f"{path}: keys differ {sorted(map(str, set(a) ^ set(b)))[:10]}")
        for k in a:
            if k in b:
                m, _ = leaf_compare(a[k], b[k], f"{path}.{k}", diffs, limit)
                n += m
        return n, diffs
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        if type(a) is not type(b):
            note(f"{path}: {type(a).__name__} != {type(b).__name__}")
        if len(a) != len(b):
            note(f"{path}: len {len(a)} != {len(b)}")
            return n, diffs
        for i, (x, y) in enumerate(zip(a, b)):
            m, _ = leaf_compare(x, y, f"{path}[{i}]", diffs, limit)
            n += m
        return n, diffs
    if isinstance(a, pd.DataFrame) or isinstance(b, pd.DataFrame):
        ok = isinstance(a, pd.DataFrame) and isinstance(b, pd.DataFrame) and a.shape == b.shape and list(a.columns) == list(b.columns) and a.equals(b)
        if not ok:
            note(f"{path}: DataFrames differ")
        return n + (int(a.size) if isinstance(a, pd.DataFrame) else 1), diffs
    if isinstance(a, np.ndarray) or isinstance(b, np.ndarray):
        aa, bb = np.asarray(a), np.asarray(b)
        if aa.shape != bb.shape or aa.dtype != bb.dtype or not np.array_equal(aa, bb, equal_nan=aa.dtype.kind in "fc"):
            note(f"{path}: arrays differ")
        return n + int(aa.size), diffs
    n += 1
    if isinstance(a, float) and isinstance(b, float):
        if type(a) is not type(b):
            note(f"{path}: type {type(a).__name__} != {type(b).__name__}")
        elif not ((math.isnan(a) and math.isnan(b)) or a == b):
            note(f"{path}: {a!r} != {b!r}")
        return n, diffs
    if type(a) is not type(b):
        note(f"{path}: type {type(a).__name__} != {type(b).__name__}")
        return n, diffs
    try:
        equal = a == b
        equal = bool(equal)
    except Exception:
        equal = repr(a) == repr(b)
    if not equal:
        note(f"{path}: {a!r} != {b!r}"[:300])
    return n, diffs


# --------------------------------------------------------------------------- arms
def _bridge():
    from syndicate.features.shared import basketball_props_smart_sim as bps

    return bps


_VENDORED_NS: dict[str, Any] | None = None


VENDORED_BRIDGE_FILE: Path | None = None  # --vendored-bridge: the bridge at VENDORED_ARM_COMMIT, exported (no git on the copy)


def vendored_arm_source(commit: str = VENDORED_ARM_COMMIT) -> str:
    if VENDORED_BRIDGE_FILE is not None:
        raw = Path(VENDORED_BRIDGE_FILE).expanduser().read_bytes()
        print(f"VENDORED_ARM file={VENDORED_BRIDGE_FILE} sha256={hashlib.sha256(raw).hexdigest()[:16]}", flush=True)
        text = raw.decode("utf-8")
    else:
        text = subprocess.check_output(["git", "-C", str(ROOT), "show", f"{commit}:{BRIDGE_REL}"]).decode("utf-8")
    tree = ast.parse(text)
    lines = text.split("\n")
    defs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    missing = [f for f in _VENDORED_ARM_FUNCS if f not in defs]
    if missing:
        raise SystemExit(f"vendored arm: {missing} not found at {commit}")
    return "\n\n\n".join("\n".join(lines[defs[f].lineno - 1 : defs[f].end_lineno]) for f in _VENDORED_ARM_FUNCS) + "\n"


def _vendored_ns() -> dict[str, Any]:
    global _VENDORED_NS
    if _VENDORED_NS is None:
        bps = _bridge()
        ns = dict(vars(bps))
        ns["_REAL_SMART_SIM_MODULE_CACHE_LOCAL"] = {}
        ns["_ADVANCED_STATS_BUILDER_MODULE_CACHE_LOCAL"] = {}
        ns["_simulate_smart_game_local"] = None  # the deleted flat fallback: never an arm
        exec(compile(vendored_arm_source(), f"<vendored arm {VENDORED_ARM_COMMIT}>", "exec"), ns)
        _VENDORED_NS = ns
    return _VENDORED_NS


def call_vendored(*, processed_root: Path, league_code: str, kwargs: dict[str, Any]):
    ns = _vendored_ns()
    module = ns["_build_local_smart_sim_module"](processed_root=processed_root, league_code=league_code)
    if not hasattr(module, "build_exact_ladder_payload") or getattr(module, "simulate_smart_game", None) is None:
        raise SystemExit("vendored arm: the vendored smart_sim did not import (refusing the flat fallback)")
    return ns["_call_source_simulate_smart_game_local"](smart_sim_module=module, processed_root=processed_root, league_code=league_code, kwargs=kwargs)


def call_native(*, processed_root: Path, league_code: str, kwargs: dict[str, Any]):
    return _NATIVE_CALL(processed_root=processed_root, league_code=league_code, kwargs=kwargs)


_NATIVE_CALL = None


def arm_fn(arm: str):
    global _NATIVE_CALL
    if _NATIVE_CALL is None:
        _NATIVE_CALL = _bridge()._call_source_simulate_smart_game_local
    return call_vendored if arm == "vendored" else call_native


def _rng_states():
    import numpy as np

    return {"numpy": copy.deepcopy(np.random.get_state()), "random": random.getstate()}


def _restore_rng(states) -> None:
    import numpy as np

    np.random.set_state(states["numpy"])
    random.setstate(states["random"])


# --------------------------------------------------------------------------- record
def load_role_env(pid: int, *, prod_root: str, scratch_root: str) -> dict[str, str]:
    from scripts.record_basketball_engine_corpus import load_role_env as _p1

    return _p1(pid, prod_root=prod_root, scratch_root=scratch_root)


def cmd_record(args) -> int:
    source_root = args.source_root.expanduser().resolve()
    prod = str(Path(args.prod_data_root).expanduser().resolve())
    if str(source_root).startswith(prod):
        raise SystemExit(f"REFUSED: --source-root {source_root} is inside the production data root; use a scratch copy")
    if args.env_from_pid is not None:
        if not args.scratch_data_root:
            raise SystemExit("--env-from-pid needs --scratch-data-root")
        env = load_role_env(args.env_from_pid, prod_root=prod, scratch_root=args.scratch_data_root)
        os.environ.clear()
        os.environ.update(env)
    import numpy as np

    bps = _bridge()
    call = arm_fn(args.arm)
    out_dir = args.out_dir.expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = []
    for date in [d.strip() for d in args.dates.split(",") if d.strip()]:
        counter = {"n": 0}

        def recording(*, processed_root, league_code, kwargs, _date=date):
            body = copy.deepcopy(kwargs)
            states = _rng_states()
            out = call(processed_root=processed_root, league_code=league_code, kwargs=kwargs)
            case = {
                "league": args.league, "date": _date, "arm": args.arm, "seq": counter["n"],
                "processed_root": str(processed_root), "league_code": league_code,
                "kwargs": body, "rng_states": states, "output": out, "output_digest": output_digest(out),
            }
            tag = f"{args.league}_{_date}_{counter['n']:03d}_{kwargs.get('home_tri')}_{kwargs.get('away_tri')}"
            tmp = out_dir / f"{tag}.tmp"
            with tmp.open("wb") as fh:
                pickle.dump(case, fh, protocol=4)
            tmp.replace(out_dir / f"{tag}.pkl")
            counter["n"] += 1
            return out

        original = bps._call_source_simulate_smart_game_local
        bps._call_source_simulate_smart_game_local = recording
        if args.seed is not None:
            np.random.seed(int(args.seed))
            random.seed(int(args.seed))
        started = time.time()
        try:
            result = bps._smart_sim_run_date_local(
                processed_root=source_root / "data" / "processed",
                raw_root=source_root / "data" / "raw",
                date_str=date,
                n_sims=int(args.n_sims),
                seed=args.seed,
                max_games=args.max_games,
                overwrite=True,
                pbp=True,
                workers=1,
                roster_mode=bps._resolve_smart_sim_roster_mode_local(date_str=date, roster_mode="historical"),
                out_prefix=str(args.out_prefix),
                league_code=args.league,
            )
        finally:
            bps._call_source_simulate_smart_game_local = original
        row = {"league": args.league, "date": date, "arm": args.arm, "games_recorded": counter["n"], "elapsed_s": round(time.time() - started, 1)}
        try:
            row["run_summary"] = {k: v for k, v in dict(result or {}).items() if isinstance(v, (int, float, str, bool))}
        except Exception:
            pass
        print("ORCH_CORPUS_DATE " + json.dumps(row), flush=True)
        summary.append(row)
    (out_dir / f"record_summary_{args.league}_{args.arm}.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    ok = all(r["games_recorded"] > 0 and (r.get("run_summary") or {}).get("failures", 0) == 0 for r in summary)
    return 0 if ok else 1


# --------------------------------------------------------------------------- replay
def iter_corpus(corpus: Path):
    for p in sorted(corpus.glob("*.pkl"), key=lambda q: (q.name.split("_")[0], q.name.split("_")[1], q.name)):
        with p.open("rb") as fh:
            yield p.name, pickle.load(fh)


def cmd_replay(args) -> int:
    if args.env_from_pid is not None:
        env = load_role_env(args.env_from_pid, prod_root=str(Path(args.prod_data_root).expanduser().resolve()), scratch_root=args.scratch_data_root)
        os.environ.clear()
        os.environ.update(env)
    call = arm_fn(args.arm)
    rows, total_leaves, bad = [], 0, 0
    for name, case in iter_corpus(args.corpus.expanduser()):
        if args.league and case["league"] != args.league:
            continue
        kwargs = copy.deepcopy(case["kwargs"])
        _restore_rng(case["rng_states"])
        t0 = time.time()
        try:
            out = call(processed_root=Path(case["processed_root"]), league_code=case["league_code"], kwargs=kwargs)
            err = None
        except Exception as exc:  # a crash is a mismatch, reported by name
            out, err = None, f"{type(exc).__name__}: {exc}"
        row: dict[str, Any] = {"case": name, "league": case["league"], "date": case["date"], "recorded_arm": case["arm"], "replay_arm": args.arm, "s": round(time.time() - t0, 1)}
        if err:
            row.update(verdict="CRASH", error=err[:500])
            bad += 1
        else:
            if args.save_outputs:
                save_dir = Path(args.save_outputs).expanduser()
                save_dir.mkdir(parents=True, exist_ok=True)
                with (save_dir / name).open("wb") as fh:
                    pickle.dump(out, fh, protocol=4)
            digest = output_digest(out)
            row["digest_reproduced"] = digest == case["output_digest"]
            n, diffs = leaf_compare(case["output"], out)
            row["leaves"] = n
            row["diffs"] = diffs
            total_leaves += n
            if case["arm"] == args.arm:
                ok = row["digest_reproduced"] and not diffs
                row["verdict"] = "REPRODUCED" if ok else "NOT_REPRODUCED"
            else:
                ok = not diffs
                row["verdict"] = "IDENTICAL" if ok else "DIFFERS"
            bad += 0 if ok else 1
        print("ORCH_REPLAY " + json.dumps(row)[:2000], flush=True)
        rows.append(row)
    leagues = sorted({r["league"] for r in rows})
    report = {
        "replay_arm": args.arm,
        "games": len(rows),
        "games_by_league": {lg: sum(1 for r in rows if r["league"] == lg) for lg in leagues},
        "dates_by_league": {lg: sorted({r["date"] for r in rows if r["league"] == lg}) for lg in leagues},
        "leaves_compared": total_leaves,
        "games_failed": bad,
        "verdict": "PASS" if rows and bad == 0 else "FAIL",
        "rows": rows,
    }
    if args.json_out:
        Path(args.json_out).expanduser().write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print("ORCH_PARITY " + json.dumps({k: v for k, v in report.items() if k != "rows"}), flush=True)
    return 0 if report["verdict"] == "PASS" else 1


def cmd_builders(args) -> int:
    """PASS 2: the team-advanced-stats builders, vendored vs native, on one data root.

    For each date it calls exactly what `_ensure_team_advanced_stats_asof_local` calls (season from
    `_season_from_date_str_local`, as_of = compact date, min_games 10 for NBA else 1), through each arm's
    `_import_advanced_stats_builders_local`, and compares the DataFrames: shape, columns, every cell."""
    import pandas as pd

    bps = _bridge()
    processed_root = args.source_root.expanduser().resolve() / "data" / "processed"
    league = bps._league_for_code_local(args.league)
    package = "wnba_betting" if args.league != "nba" else "nba_betting"
    v_box, v_logs = _vendored_ns()["_import_advanced_stats_builders_local"](package_name=package, processed_root=processed_root)
    if v_box is None or v_logs is None:
        raise SystemExit("vendored arm: advanced-stats builders did not import")
    n_box, n_logs = bps._import_advanced_stats_builders_local(package_name=package, processed_root=processed_root)
    min_games = 1 if args.league != "nba" else 10
    rows, cells, bad = [], 0, 0
    for date in [d.strip() for d in args.dates.split(",") if d.strip()]:
        season = bps._season_from_date_str_local(date_str=date, league=league)
        as_of = date.replace("-", "")
        for kind, vf, nf in (
            ("boxscores", v_box.compute_team_advanced_stats_from_boxscores, n_box.compute_team_advanced_stats_from_boxscores),
            ("player_logs", v_logs.compute_team_advanced_stats_from_player_logs, n_logs.compute_team_advanced_stats_from_player_logs),
        ):
            out = {}
            for arm, fn in (("vendored", vf), ("native", nf)):
                try:
                    out[arm] = fn(int(season), min_games=min_games, as_of=as_of)
                except Exception as exc:
                    out[arm] = f"{type(exc).__name__}: {exc}"
            a, b = out["vendored"], out["native"]
            if isinstance(a, pd.DataFrame) and isinstance(b, pd.DataFrame):
                same = a.shape == b.shape and list(a.columns) == list(b.columns) and a.equals(b)
                n = int(a.size)
            else:
                same = (not isinstance(a, pd.DataFrame)) and (not isinstance(b, pd.DataFrame)) and str(a) == str(b)
                n = 0
            cells += n
            bad += 0 if same else 1
            row = {"date": date, "season": season, "kind": kind, "rows": int(a.shape[0]) if isinstance(a, pd.DataFrame) else None,
                   "cells": n, "verdict": "IDENTICAL" if same else "DIFFERS",
                   "vendored": None if isinstance(a, pd.DataFrame) else str(a)[:200], "native": None if isinstance(b, pd.DataFrame) else str(b)[:200]}
            print("ORCH_BUILDERS " + json.dumps(row), flush=True)
            rows.append(row)
    rep = {"league": args.league, "comparisons": len(rows), "non_empty": sum(1 for r in rows if r["rows"]), "cells_compared": cells, "failed": bad,
           "verdict": "PASS" if rows and bad == 0 else "FAIL", "rows": rows}
    if args.json_out:
        Path(args.json_out).expanduser().write_text(json.dumps(rep, indent=2), encoding="utf-8")
    print("ORCH_BUILDERS_PARITY " + json.dumps({k: v for k, v in rep.items() if k != "rows"}), flush=True)
    return 0 if rep["verdict"] == "PASS" else 1


def cmd_compare_outputs(args) -> int:
    """Two `replay --save-outputs` directories, game by game, every leaf.

    This is the check that survives a change to a SHARED port: run both arms on the same checkout and compare them
    to EACH OTHER. The comparison against the recorded output is only valid when the ports are unchanged since
    recording."""
    a_dir, b_dir = Path(args.dir_a).expanduser(), Path(args.dir_b).expanduser()
    names = sorted({p.name for p in a_dir.glob("*.pkl")} | {p.name for p in b_dir.glob("*.pkl")})
    rows, leaves, bad = [], 0, 0
    for name in names:
        pa, pb = a_dir / name, b_dir / name
        if not (pa.exists() and pb.exists()):
            rows.append({"case": name, "verdict": "MISSING_IN_" + ("A" if not pa.exists() else "B")})
            bad += 1
            continue
        with pa.open("rb") as fa, pb.open("rb") as fb:
            a, b = pickle.load(fa), pickle.load(fb)
        n, diffs = leaf_compare(a, b)
        leaves += n
        bad += 1 if diffs else 0
        rows.append({"case": name, "leaves": n, "diffs": diffs, "verdict": "DIFFERS" if diffs else "IDENTICAL"})
        print("ORCH_OUT " + json.dumps(rows[-1])[:1500], flush=True)
    rep = {"games": len(names), "leaves_compared": leaves, "games_failed": bad, "verdict": "PASS" if names and not bad else "FAIL"}
    print("ORCH_OUT_PARITY " + json.dumps(rep), flush=True)
    return 0 if rep["verdict"] == "PASS" else 1


def cmd_compare(args) -> int:
    from scripts.basketball_engine_parity import compare_sim_artifacts

    volatile = set(args.volatile.split(",")) if args.volatile else set()
    roots = (args.root_a, args.root_b) if args.root_a and args.root_b else None
    rep = compare_sim_artifacts(Path(args.dir_a), args.prefix_a, Path(args.dir_b), args.prefix_b, volatile, roots)
    print("ORCH_E2E " + json.dumps(rep), flush=True)
    return 0 if rep["verdict"] == "PASS" else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record")
    r.add_argument("--league", required=True, choices=("nba", "wnba"))
    r.add_argument("--dates", required=True)
    r.add_argument("--source-root", required=True, type=Path, help="SCRATCH copy of <league>_source")
    r.add_argument("--out-dir", required=True, type=Path)
    r.add_argument("--arm", choices=("vendored", "native"), default="vendored")
    r.add_argument("--n-sims", type=int, default=100)
    r.add_argument("--seed", type=int, required=True)
    r.add_argument("--max-games", type=int, default=None)
    r.add_argument("--env-from-pid", type=int, default=None)
    r.add_argument("--prod-data-root", default="~/syndicate-prod/data")
    r.add_argument("--scratch-data-root", default=None)
    r.add_argument("--out-prefix", default="smart_sim")
    r.add_argument("--vendored-bridge", type=Path, default=None, help=f"{BRIDGE_REL} as of {VENDORED_ARM_COMMIT} (else git show)")
    p = sub.add_parser("replay")
    p.add_argument("--corpus", required=True, type=Path)
    p.add_argument("--arm", choices=("vendored", "native"), required=True)
    p.add_argument("--league", choices=("nba", "wnba"), default=None)
    p.add_argument("--json-out", default=None)
    p.add_argument("--env-from-pid", type=int, default=None)
    p.add_argument("--prod-data-root", default="~/syndicate-prod/data")
    p.add_argument("--scratch-data-root", default=None)
    p.add_argument("--vendored-bridge", type=Path, default=None)
    p.add_argument("--save-outputs", default=None, help="pickle each replayed output here (for compare-outputs)")
    co = sub.add_parser("compare-outputs")
    co.add_argument("--dir-a", required=True)
    co.add_argument("--dir-b", required=True)
    bl = sub.add_parser("builders")
    bl.add_argument("--league", required=True, choices=("nba", "wnba"))
    bl.add_argument("--dates", required=True)
    bl.add_argument("--source-root", required=True, type=Path, help="SCRATCH copy of <league>_source")
    bl.add_argument("--json-out", default=None)
    bl.add_argument("--vendored-bridge", type=Path, default=None)
    c = sub.add_parser("compare")
    c.add_argument("--dir-a", required=True)
    c.add_argument("--prefix-a", default="smart_sim")
    c.add_argument("--dir-b", required=True)
    c.add_argument("--prefix-b", default="smart_sim")
    c.add_argument("--volatile", default="")
    c.add_argument("--root-a", default=None)
    c.add_argument("--root-b", default=None)
    args = ap.parse_args(argv)
    global VENDORED_BRIDGE_FILE
    VENDORED_BRIDGE_FILE = getattr(args, "vendored_bridge", None)
    return {"record": cmd_record, "replay": cmd_replay, "compare": cmd_compare, "builders": cmd_builders, "compare-outputs": cmd_compare_outputs}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
