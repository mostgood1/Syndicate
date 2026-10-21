"""PARITY GATE for plan P6: the native smart-sim orchestrator, game for game (record / replay / compare).

Lane basketball-native-orchestrator. P1's tools (record_basketball_engine_corpus.py,
basketball_engine_parity.py) gate the possession ENGINE one draw at a time. This
gates the ORCHESTRATOR one GAME at a time: the whole ``simulate_smart_game`` call
plus the bridge's post-processing, i.e. the dict written to
``smart_sim_<date>_<H>_<A>.json``.

THE ARM: ``basketball_props_smart_sim._call_source_simulate_smart_game_local`` as it is now
(syndicate/features/basketball_engine/orchestrator). The VENDORED arm (the pre-P6 bridge read from git at
``VENDORED_ARM_COMMIT`` and run against vendor/) and the vendored-vs-native ``builders`` comparison were removed
2026-10-20 (lane vendor-dead-paths-cleanup): vendor/ is empty. Parity was proven on the fleet 2026-10-10 (deploys.md). ``VENDORED_ARM_COMMIT``
and ``BRIDGE_REL`` stay: they name the pre-P6 bridge in git history, which the orchestrator input checklist's
positive control reads.

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
import copy
import hashlib
import json
import math
import os
import pickle
import random
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# The last commit on origin/main whose bridge still ran the VENDORED orchestrator (git history; read by the
# orchestrator input checklist's positive control).
VENDORED_ARM_COMMIT = "a1ee82cb"
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


def call_native(*, processed_root: Path, league_code: str, kwargs: dict[str, Any]):
    return _NATIVE_CALL(processed_root=processed_root, league_code=league_code, kwargs=kwargs)


_NATIVE_CALL = None


def arm_fn(arm: str):
    global _NATIVE_CALL
    if _NATIVE_CALL is None:
        _NATIVE_CALL = _bridge()._call_source_simulate_smart_game_local
    if arm != "native":
        raise SystemExit(f"arm {arm!r}: only 'native' exists (the vendored arm went with vendor/, {NOTE})")
    return call_native


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
    r.add_argument("--arm", choices=("native",), default="native")
    r.add_argument("--n-sims", type=int, default=100)
    r.add_argument("--seed", type=int, required=True)
    r.add_argument("--max-games", type=int, default=None)
    r.add_argument("--env-from-pid", type=int, default=None)
    r.add_argument("--prod-data-root", default="~/syndicate-prod/data")
    r.add_argument("--scratch-data-root", default=None)
    r.add_argument("--out-prefix", default="smart_sim")
    p = sub.add_parser("replay")
    p.add_argument("--corpus", required=True, type=Path)
    p.add_argument("--arm", choices=("native",), default="native")
    p.add_argument("--league", choices=("nba", "wnba"), default=None)
    p.add_argument("--json-out", default=None)
    p.add_argument("--env-from-pid", type=int, default=None)
    p.add_argument("--prod-data-root", default="~/syndicate-prod/data")
    p.add_argument("--scratch-data-root", default=None)
    p.add_argument("--save-outputs", default=None, help="pickle each replayed output here (for compare-outputs)")
    co = sub.add_parser("compare-outputs")
    co.add_argument("--dir-a", required=True)
    co.add_argument("--dir-b", required=True)
    c = sub.add_parser("compare")
    c.add_argument("--dir-a", required=True)
    c.add_argument("--prefix-a", default="smart_sim")
    c.add_argument("--dir-b", required=True)
    c.add_argument("--prefix-b", default="smart_sim")
    c.add_argument("--volatile", default="")
    c.add_argument("--root-a", default=None)
    c.add_argument("--root-b", default=None)
    args = ap.parse_args(argv)
    return {"record": cmd_record, "replay": cmd_replay, "compare": cmd_compare, "compare-outputs": cmd_compare_outputs}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
