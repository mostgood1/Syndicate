"""PARITY GATE: the native basketball engine against the vendored one, seed for seed.

Lane basketball-native-engine (plan P1, docs/ai_context/basketball_live_native_plan.md).

Every case is ONE engine call, exactly as production made it: the kwargs that
the vendored ``smart_sim.simulate_smart_game`` passed to Syndicate's per-draw
helper, plus the RNG state just before the call. The case is replayed twice
from that state:

  vendored  -- ``vendor/<league>_betting_repo/src/<pkg>/sim/events.py``, called
               the way production called it (kwargs filtered to the
               signature, ``_sample_lineup`` swapped for Syndicate's
               ``_sample_lineup_local`` for the call). This is a frozen copy of
               the removed ``_call_real_events_entrypoint_local``.
  native    -- ``syndicate.features.basketball_engine`` with
               ``league=league_params(code)`` and
               ``sample_lineup=_sample_lineup_local``.

A case passes only if every output LEAF is equal (ints exactly, floats bit for
bit, NaN == NaN) AND the RNG state after the call is identical. The second
condition proves that both engines drew the same number of variates, not just
that they printed the same box.

    py -3 scripts/basketball_engine_parity.py --corpus <dir>      # replay a recorded corpus (exit 1 on any mismatch)
    py -3 scripts/basketball_engine_parity.py --synthetic 200     # synthetic smoke over both leagues

The corpus comes from ``scripts/record_basketball_engine_corpus.py``. Report the
corpus size with the result: a PASS over 3 cases is not a PASS over 3,000.
"""

from __future__ import annotations

import argparse
import copy
import importlib
import inspect
import json
import math
import pickle
import sys
import time
from pathlib import Path
from typing import Any, Iterable

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PACKAGES = {"nba": "nba_betting", "wnba": "wnba_betting"}
ENTRYPOINTS = ("simulate_pbp_game_boxscore", "simulate_event_level_boxscore")


# ---------------------------------------------------------------------------------------------------------------
# The two engines
# ---------------------------------------------------------------------------------------------------------------

_VENDORED: dict[str, Any] = {}


def vendored_events_module(league: str):
    """The vendored events module, imported from the repo's vendor tree (as production's loader did)."""
    league = str(league).lower()
    if league not in _VENDORED:
        package = PACKAGES[league]
        src = ROOT / "vendor" / f"{package}_repo" / "src"
        if str(src) not in sys.path:
            sys.path.insert(0, str(src))
        _VENDORED[league] = importlib.import_module(f"{package}.sim.events")
    return _VENDORED[league]


def production_sampler():
    from syndicate.features.shared.basketball_props_smart_sim import _sample_lineup_local

    return _sample_lineup_local


def call_vendored(*, league: str, entrypoint: str, kwargs: dict[str, Any], sampler) -> Any:
    """FROZEN copy of production's `_call_real_events_entrypoint_local` (removed from basketball_props_smart_sim)."""
    module = vendored_events_module(league)
    fn = getattr(module, entrypoint)
    params = inspect.signature(fn).parameters
    if not any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
        kwargs = {k: v for k, v in kwargs.items() if k in params}
    sentinel = object()
    original = getattr(module, "_sample_lineup", sentinel)
    if sampler is not None:
        module._sample_lineup = sampler
    try:
        return fn(**kwargs)
    finally:
        if original is sentinel:
            try:
                delattr(module, "_sample_lineup")
            except AttributeError:
                pass
        else:
            module._sample_lineup = original


def call_native(*, league: str, entrypoint: str, kwargs: dict[str, Any], sampler) -> Any:
    from syndicate.features import basketball_engine as eng

    fn = getattr(eng, entrypoint)
    params = inspect.signature(fn).parameters
    kwargs = {k: v for k, v in kwargs.items() if k in params}
    return fn(**kwargs, league=eng.league_params(league), sample_lineup=sampler)


# ---------------------------------------------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------------------------------------------


def leaf_diffs(a: Any, b: Any, path: str = "$", out: list[str] | None = None, limit: int = 20) -> list[str]:
    """Every leaf where a != b (exact). Floats compare bit for bit; NaN equals NaN."""
    out = [] if out is None else out
    if len(out) >= limit:
        return out
    if isinstance(a, dict) and isinstance(b, dict):
        if set(a) != set(b):
            out.append(f"{path}: keys {sorted(set(a) ^ set(b))}")
        for k in a:
            if k in b:
                leaf_diffs(a[k], b[k], f"{path}.{k}", out, limit)
        return out
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        if len(a) != len(b):
            out.append(f"{path}: len {len(a)} != {len(b)}")
            return out
        for i, (x, y) in enumerate(zip(a, b)):
            leaf_diffs(x, y, f"{path}[{i}]", out, limit)
        return out
    if isinstance(a, np.ndarray) or isinstance(b, np.ndarray):
        if not np.array_equal(np.asarray(a), np.asarray(b), equal_nan=True):
            out.append(f"{path}: arrays differ")
        return out
    if isinstance(a, float) and isinstance(b, float):
        if not ((math.isnan(a) and math.isnan(b)) or a == b):
            out.append(f"{path}: {a!r} != {b!r}")
        return out
    if type(a) is not type(b) and not (isinstance(a, (int, np.integer)) and isinstance(b, (int, np.integer))):
        out.append(f"{path}: type {type(a).__name__} != {type(b).__name__}")
        return out
    if a != b:
        out.append(f"{path}: {a!r} != {b!r}")
    return out


def replay_case(case: dict[str, Any], sampler) -> dict[str, Any]:
    """Run one recorded call through both engines from the recorded RNG state."""
    league, entrypoint = case["league"], case["entrypoint"]
    results = {}
    for name, fn in (("vendored", call_vendored), ("native", call_native)):
        rng = np.random.Generator(np.random.PCG64())
        rng.bit_generator.state = copy.deepcopy(case["rng_state"])
        kwargs = dict(case["kwargs"])
        kwargs["rng"] = rng
        err = None
        try:
            out = fn(league=league, entrypoint=entrypoint, kwargs=kwargs, sampler=sampler)
        except Exception as exc:  # an exception is an output too: both must raise the same thing
            out, err = None, f"{type(exc).__name__}: {exc}"
        results[name] = (out, err, rng.bit_generator.state)
    (vo, ve, vs), (no, ne, ns) = results["vendored"], results["native"]
    diffs: list[str] = []
    if entrypoint == "simulate_event_level_boxscore":
        # The vendored event-level simulator cannot run (NameError on its first possession); the native one refuses
        # by name. Parity here means: both fail. If the vendored one ever SUCCEEDS, that is a mismatch to look at.
        if ve is None:
            diffs.append("vendored event-level simulator returned a result; the native refusal assumed it never can")
        if ne is None or "NotImplementedError" not in ne:
            diffs.append(f"native event-level simulator did not refuse: {ne!r}")
        return {"ok": not diffs, "diffs": diffs, "raised": ve}
    if ve != ne:
        diffs.append(f"exception: vendored={ve!r} native={ne!r}")
    else:
        leaf_diffs(vo, no, "$", diffs)
    if vs != ns:
        diffs.append("rng state after the call differs (different number of draws)")
    # Replay fidelity: the vendored replay must reproduce what PRODUCTION computed for this call, or the corpus did not
    # capture the call faithfully and a native match would prove nothing about production.
    fidelity = None
    if case.get("production_digest"):
        from scripts.record_basketball_engine_corpus import output_digest

        fidelity = output_digest(vo) == case["production_digest"]
        if not fidelity:
            diffs.append("vendored replay does not reproduce production's recorded output (corpus fidelity)")
    return {"ok": not diffs, "diffs": diffs, "raised": ve, "fidelity": fidelity}


# ---------------------------------------------------------------------------------------------------------------
# Corpus I/O
# ---------------------------------------------------------------------------------------------------------------


def iter_corpus(corpus_dir: Path) -> Iterable[tuple[str, dict[str, Any]]]:
    """Yield (source, case) for every recorded call. One pickle per game; each holds kwargs once + per-draw states."""
    for path in sorted(Path(corpus_dir).glob("*.pkl")):
        with path.open("rb") as fh:
            game = pickle.load(fh)
        digests = game.get("output_digests") or []
        for j, state in enumerate(game["rng_states"]):
            yield f"{path.name}#{j}", {
                "league": game["league"],
                "entrypoint": game["entrypoint"],
                "kwargs": game["kwargs"],
                "rng_state": state,
                "production_digest": digests[j] if j < len(digests) else None,
            }


def synthetic_cases(n: int, seed: int = 20261009) -> Iterable[tuple[str, dict[str, Any]]]:
    from tests.basketball_engine_fixtures import synthetic_game_kwargs

    master = np.random.default_rng(seed)
    for i in range(int(n)):
        league = ("nba", "wnba")[i % 2]
        entrypoint = ENTRYPOINTS[0] if i % 7 else ENTRYPOINTS[1]
        kwargs = synthetic_game_kwargs(master, league=league, entrypoint=entrypoint)
        state = np.random.Generator(np.random.PCG64(int(master.integers(0, 2**63 - 1)))).bit_generator.state
        yield f"synthetic#{i}", {"league": league, "entrypoint": entrypoint, "kwargs": kwargs, "rng_state": state}


def _strip_volatile(obj: Any, volatile: set[str]) -> Any:
    if isinstance(obj, dict):
        return {k: _strip_volatile(v, volatile) for k, v in obj.items() if k not in volatile}
    if isinstance(obj, list):
        return [_strip_volatile(v, volatile) for v in obj]
    return obj


def compare_sim_artifacts(dir_a: Path, prefix_a: str, dir_b: Path, prefix_b: str, volatile: set[str], roots: tuple[str, str] | None = None) -> dict[str, Any]:
    """End-to-end A/B: the smart_sim_<date>_<H>_<A>.json each arm wrote, leaf for leaf (volatile keys named, not hidden)."""
    a_files = {p.name[len(prefix_a):]: p for p in Path(dir_a).glob(f"{prefix_a}_*.json")}
    b_files = {p.name[len(prefix_b):]: p for p in Path(dir_b).glob(f"{prefix_b}_*.json")}
    games = sorted(set(a_files) | set(b_files))
    out: dict[str, Any] = {"games": len(games), "only_in_a": sorted(set(a_files) - set(b_files)), "only_in_b": sorted(set(b_files) - set(a_files)), "identical": 0, "differ": {}, "volatile_keys_ignored": sorted(volatile)}
    for g in sorted(set(a_files) & set(b_files)):
        ta, tb = a_files[g].read_text(encoding="utf-8"), b_files[g].read_text(encoding="utf-8")
        if roots:  # each arm runs on its own copy of the data: an input PATH echoed into the artifact names the copy
            ta, tb = ta.replace(roots[0], "<DATA_ROOT>"), tb.replace(roots[1], "<DATA_ROOT>")
        ja = _strip_volatile(json.loads(ta), volatile)
        jb = _strip_volatile(json.loads(tb), volatile)
        d = leaf_diffs(ja, jb, "$", [], limit=10)
        if d:
            out["differ"][g] = d
        else:
            out["identical"] += 1
    out["verdict"] = "PASS" if (out["identical"] == len(games) and games) else "FAIL"
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Native vs vendored basketball engine parity (exit 1 on any mismatch).")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--corpus", type=Path, help="directory of recorded *.pkl games")
    src.add_argument("--synthetic", type=int, help="number of synthetic cases")
    src.add_argument("--compare-sims", nargs=4, metavar=("DIR_A", "PREFIX_A", "DIR_B", "PREFIX_B"), help="end-to-end: compare two arms' smart_sim JSON artifacts")
    ap.add_argument("--volatile-key", action="append", default=[], help="a key to ignore in --compare-sims (repeatable; listed in the report)")
    ap.add_argument("--data-roots", nargs=2, metavar=("ROOT_A", "ROOT_B"), help="--compare-sims: each arm's data root, normalised to one token before comparing")
    ap.add_argument("--sampler", choices=("production", "vendored_default"), default="production")
    ap.add_argument("--json-out", type=Path)
    ap.add_argument("--max-cases", type=int, default=None)
    args = ap.parse_args(argv)

    if args.compare_sims:
        da, pa, db, pb = args.compare_sims
        report = compare_sim_artifacts(Path(da).expanduser(), pa, Path(db).expanduser(), pb, set(args.volatile_key), tuple(args.data_roots) if args.data_roots else None)
        text = json.dumps(report, indent=2)
        print(text)
        if args.json_out:
            args.json_out.parent.mkdir(parents=True, exist_ok=True)
            args.json_out.write_text(text, encoding="utf-8")
        return 0 if report["verdict"] == "PASS" else 1

    sampler = production_sampler() if args.sampler == "production" else None
    cases = iter_corpus(args.corpus) if args.corpus else synthetic_cases(args.synthetic)
    started = time.time()
    n = n_fail = n_raised = n_fidelity = 0
    by_league: dict[str, dict[str, int]] = {}
    games: set[str] = set()
    failures: list[dict[str, Any]] = []
    for source, case in cases:
        if args.max_cases is not None and n >= args.max_cases:
            break
        res = replay_case(case, sampler)
        n += 1
        games.add(source.split("#")[0])
        tally = by_league.setdefault(f"{case['league']}:{case['entrypoint']}", {"cases": 0, "mismatch": 0})
        tally["cases"] += 1
        if res["raised"]:
            n_raised += 1
        if res.get("fidelity") is True:
            n_fidelity += 1
        if not res["ok"]:
            n_fail += 1
            tally["mismatch"] += 1
            if len(failures) < 25:
                failures.append({"case": source, "diffs": res["diffs"][:10]})
    report = {
        "substrate": f"corpus:{args.corpus}" if args.corpus else f"synthetic:{args.synthetic}",
        "sampler": args.sampler,
        "cases": n,
        "games": len(games),
        "mismatched_cases": n_fail,
        "cases_where_both_raised": n_raised,
        "cases_reproducing_production_output": n_fidelity,
        "by_league_entrypoint": by_league,
        "failures": failures,
        "elapsed_s": round(time.time() - started, 1),
        "verdict": "PASS" if (n > 0 and n_fail == 0) else ("EMPTY" if n == 0 else "FAIL"),
    }
    text = json.dumps(report, indent=2)
    print(text)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(text, encoding="utf-8")
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
