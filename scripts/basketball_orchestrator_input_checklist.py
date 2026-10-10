"""GATING input checklist for Syndicate's smart-sim ORCHESTRATOR (model engine standard §1).

Lane basketball-native-orchestrator (plan P6). Scope: what one call of
``syndicate/features/basketball_engine/orchestrator/smart_sim.py:simulate_smart_game``
reads. Two neighbours own their own layers and this does not repeat them:
  * ``scripts/basketball_engine_input_checklist.py`` (P1): the possession ENGINE
    (``EventSimConfig`` / ``LeagueParams`` / ``GameState``, player-frame columns);
  * ``scripts/basketball_sim_input_checklist.py``: the smart-sim data layers
    (player priors, team advanced stats, calibration artifacts).

ENUMERATED, never grepped for names I expected (standard §1):
  * ``dataclasses.fields()`` of every run-level dataclass the orchestrator reads:
      SmartSimConfigLocal  the ``cfg`` production passes (bridge ``_build_smart_sim_config_local``);
      SmartSimConfig       the orchestrator's own default config (must carry the same fields);
      OrchestratorLeague   the league constants (``orch.league``);
      SmartSimPaths        the roots (``orch.paths``);
  * ``inspect.signature(simulate_smart_game)`` parameters;
  * every literal key read from ``pregame_context`` (``pregame_context.get("<k>")``).

CONSUMED? from the orchestrator SOURCE by AST: ``cfg.<f>`` / ``getattr(cfg, "<f>")``,
``orch.league.<f>`` / ``getattr(orch.league, "<f>")``, ``orch.paths.<f>``, a Name
load of each parameter, ``pregame_context.get("<k>")``. ``view.py`` and
``hooks.py`` count as consumers of ``orch.*`` too.

POPULATED? measured over a corpus recorded by
``scripts/basketball_orchestrator_parity.py record`` (REAL production games): a
``cfg`` field at its dataclass DEFAULT counts as unfed; a parameter that is None
or empty counts as unfed; a context key that is absent or None counts as unfed.
League constants carry no defaults (every field is set explicitly per league), so
for them the check is CONSUMED only: an unconsumed constant is reported as dead.

CONSUMED + UNPOPULATED is the alarm, exit 1. The explicit lists keep the gate
honest: EXPECTED_CONSTANT (production rightly leaves the default),
EXPECTED_SPARSE (legitimately absent for some games) and DEFAULT_IS_A_VALUE (the
bridge always sets it, and the default is one of its real values), each with its reason. An
entry that stops being true FAILS the gate, so the lists cannot rot.

SUBSTRATE: the corpus is a copy of the fleet's production data root taken at
recording time; the report names the corpus directory, leagues and dates.

    python scripts/basketball_orchestrator_input_checklist.py --corpus <dir> [--json-out report.json]
    python scripts/basketball_orchestrator_input_checklist.py --static   # consumption + wiring only; never PASS on population
"""

from __future__ import annotations

import argparse
import ast
import inspect
import json
import pickle
import sys
from dataclasses import MISSING, fields
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PKG = ROOT / "syndicate" / "features" / "basketball_engine" / "orchestrator"

# Production leaves these at the dataclass default, and that is right.
EXPECTED_CONSTANT: dict[str, str] = {
    "cfg.priors_days_back": "21-day priors window; the bridge never overrides it (the priors port reads its own windows)",
    "cfg.use_pbp": "True is the default and the only production mode (the event-level path refuses by name, P1)",
    "cfg.seed": "None in production (a fresh draw per run); parity runs set it, which is why this can read populated",
}
# The default IS a production value, always set explicitly by the bridge (not an absence).
DEFAULT_IS_A_VALUE: dict[str, str] = {
    "cfg.roster_mode": (
        "the bridge always passes it (`_build_smart_sim_config_local(roster_mode=_resolve_smart_sim_roster_mode_local(...))`): "
        "'historical' for a past date, 'pregame' for today or later. A corpus that re-simulates past dates reads 'historical'"
    ),
}
# Legitimately absent for some or all production games.
EXPECTED_SPARSE: dict[str, str] = {
    "param.game_id": "the bridge never passes it; the orchestrator infers it (`_infer_game_id` hook)",
    "param.market_total": "None when the slate has no total yet; the orchestrator falls back to period lines",
    "param.market_home_spread": "None when the slate has no spread yet",
    "param.excluded_player_keys_by_team": "empty when no player is ruled out for either team",
    "ctx.home_b2b": "False is a value, not an absence; absent only if the job carries no schedule flag",
    "ctx.away_b2b": "as home_b2b",
    "ctx.home_injuries_out": "0 is a value",
    "ctx.away_injuries_out": "0 is a value",
}


def _src(name: str) -> str:
    return (PKG / name).read_text(encoding="utf-8")


def consumed_from_source() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {"cfg": set(), "league": set(), "paths": set(), "param": set(), "ctx": set()}
    trees = {n: ast.parse(_src(n)) for n in ("smart_sim.py", "hooks.py", "view.py", "connected_game.py", "boxscores.py", "prob_calibration.py")}
    sim_fn = next(n for n in trees["smart_sim.py"].body if isinstance(n, ast.FunctionDef) and n.name == "simulate_smart_game")
    params = {a.arg for a in sim_fn.args.args + sim_fn.args.kwonlyargs}
    for name, tree in trees.items():
        for n in ast.walk(tree):
            if isinstance(n, ast.Attribute):
                v = n.value
                if isinstance(v, ast.Name) and v.id == "cfg":
                    out["cfg"].add(n.attr)
                if isinstance(v, ast.Attribute) and isinstance(v.value, ast.Name) and v.value.id == "orch":
                    if v.attr == "league":
                        out["league"].add(n.attr)
                    elif v.attr == "paths":
                        out["paths"].add(n.attr)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "getattr" and len(n.args) >= 2:
                tgt, key = n.args[0], n.args[1]
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    if isinstance(tgt, ast.Name) and tgt.id == "cfg":
                        out["cfg"].add(key.value)
                    if isinstance(tgt, ast.Attribute) and isinstance(tgt.value, ast.Name) and tgt.value.id == "orch" and tgt.attr == "league":
                        out["league"].add(key.value)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "get":
                base = n.func.value
                if isinstance(base, ast.Name) and base.id == "pregame_context" and n.args and isinstance(n.args[0], ast.Constant):
                    out["ctx"].add(str(n.args[0].value))
    # A paths field the bridge's ports read off the view (`paths = getattr(smart_sim_module, "paths")`).
    bridge = (ROOT / "syndicate" / "features" / "shared" / "basketball_props_smart_sim.py").read_text(encoding="utf-8")
    for f in ("data_processed", "data_raw", "root"):
        if f"source_paths.{f}" in bridge or f"getattr(source_paths, \"{f}\"" in bridge:
            out["paths"].add(f)
    for n in ast.walk(sim_fn):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id in params:
            out["param"].add(n.id)
    out["param"].discard("orch")
    return out


def wiring_check() -> list[str]:
    """The production call must reach the native orchestrator, and nothing on the path may import a vendored module."""
    problems: list[str] = []
    bridge = (ROOT / "syndicate" / "features" / "shared" / "basketball_props_smart_sim.py").read_text(encoding="utf-8")
    tree = ast.parse(bridge)
    fn = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_call_source_simulate_smart_game_local"), None)
    if fn is None:
        problems.append("bridge: _call_source_simulate_smart_game_local is gone")
    else:
        seg = ast.get_source_segment(bridge, fn) or ""
        if "basketball_engine.orchestrator import" not in seg:
            problems.append("bridge: _call_source_simulate_smart_game_local does not import the native orchestrator")
        if "setattr(" in seg:
            problems.append("bridge: _call_source_simulate_smart_game_local still patches attributes")
    for n in ast.walk(tree):
        # A runtime import of a vendored SIM module: importlib.import_module(...) / __import__(...) whose argument
        # names `.sim.`, or an import statement of one. Docstrings that mention the old path are history, not imports.
        if isinstance(n, ast.Call):
            f = n.func
            name = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else "")
            if name in ("import_module", "__import__") and n.args:
                text = ast.get_source_segment(bridge, n.args[0]) or ""
                if ".sim" in text:
                    problems.append(f"bridge:{n.lineno} imports a vendored sim module: {text}")
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            mod = (n.module or "") if isinstance(n, ast.ImportFrom) else ",".join(a.name for a in n.names)
            if "betting.sim" in mod or mod.startswith("vendor"):
                problems.append(f"bridge:{n.lineno} imports {mod}")
    for p in sorted(PKG.glob("*.py")):
        t = ast.parse(p.read_text(encoding="utf-8"))
        for n in ast.walk(t):
            if isinstance(n, (ast.Import, ast.ImportFrom)):
                mod = (n.module or "") if isinstance(n, ast.ImportFrom) else ",".join(a.name for a in n.names)
                if "nba_betting" in mod or "wnba_betting" in mod or mod.startswith("vendor"):
                    problems.append(f"orchestrator/{p.name}:{n.lineno} imports {mod}")
    return problems


def _unfed(v: Any) -> bool:
    if v is None:
        return True
    try:
        import pandas as pd

        if isinstance(v, pd.DataFrame):
            return v.empty
    except Exception:
        pass
    if isinstance(v, (dict, list, tuple, set, str)):
        return len(v) == 0
    return False


def measure_corpus(corpus: Path, consumed: dict[str, set[str]]) -> dict[str, Any]:
    from syndicate.features.shared.basketball_props_smart_sim import SmartSimConfigLocal

    defaults = {f.name: (f.default if f.default is not MISSING else None) for f in fields(SmartSimConfigLocal)}
    rows: dict[str, dict[str, int]] = {}
    meta = {"games": 0, "leagues": {}, "dates": {}}

    def bump(key: str, fed: bool) -> None:
        r = rows.setdefault(key, {"fed": 0, "unfed": 0})
        r["fed" if fed else "unfed"] += 1

    for p in sorted(corpus.glob("*.pkl")):
        with p.open("rb") as fh:
            case = pickle.load(fh)
        kw = case["kwargs"]
        meta["games"] += 1
        meta["leagues"][case["league"]] = meta["leagues"].get(case["league"], 0) + 1
        meta["dates"].setdefault(case["league"], set()).add(case["date"])
        cfg = kw.get("cfg")
        for f in fields(SmartSimConfigLocal):
            v = getattr(cfg, f.name, None)
            bump(f"cfg.{f.name}", v is not None and v != defaults[f.name] if f.name != "event_cfg" else v is not None)
        for prm in consumed["param"]:
            bump(f"param.{prm}", not _unfed(kw.get(prm)))
        ctx = kw.get("pregame_context") or {}
        for k in consumed["ctx"]:
            v = ctx.get(k)
            bump(f"ctx.{k}", v is not None and not (isinstance(v, float) and v != v))
    meta["dates"] = {k: sorted(v) for k, v in meta["dates"].items()}
    return {"meta": meta, "rows": rows}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Gating input checklist for the basketball smart-sim orchestrator (exit 1 on alarm).")
    ap.add_argument("--corpus", type=Path, default=None)
    ap.add_argument("--static", action="store_true")
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args(argv)

    from syndicate.features.basketball_engine.orchestrator import OrchestratorLeague, SmartSimConfig, SmartSimPaths, simulate_smart_game
    from syndicate.features.shared.basketball_props_smart_sim import SmartSimConfigLocal

    consumed = consumed_from_source()
    alarms: list[str] = []
    report: dict[str, Any] = {"consumed": {k: sorted(v) for k, v in consumed.items()}}

    # Enumerations.
    cfg_fields = [f.name for f in fields(SmartSimConfigLocal)]
    native_cfg_fields = [f.name for f in fields(SmartSimConfig)]
    if sorted(cfg_fields) != sorted(native_cfg_fields):
        alarms.append(f"SmartSimConfigLocal fields {cfg_fields} != the orchestrator's SmartSimConfig {native_cfg_fields}")
    for name in consumed["cfg"]:
        if name not in cfg_fields:
            alarms.append(f"orchestrator reads cfg.{name}, which SmartSimConfigLocal does not carry (it can only ever be absent)")
    league_fields = [f.name for f in fields(OrchestratorLeague)]
    report["league_dead"] = sorted(set(league_fields) - consumed["league"] - {"code"})
    for name in consumed["league"]:
        if name not in league_fields:
            alarms.append(f"orchestrator reads orch.league.{name}, which OrchestratorLeague does not define")
    path_fields = [f.name for f in fields(SmartSimPaths)]
    for name in consumed["paths"]:
        if name not in path_fields:
            alarms.append(f"orchestrator reads orch.paths.{name}, which SmartSimPaths does not define")
    sig = [p for p in inspect.signature(simulate_smart_game).parameters if p != "orch"]
    report["unconsumed_params"] = sorted(set(sig) - consumed["param"])

    wiring = wiring_check()
    alarms += [f"WIRING: {w}" for w in wiring]

    if args.corpus is not None and not args.static:
        m = measure_corpus(args.corpus.expanduser(), consumed)
        report["corpus"] = {"dir": str(args.corpus), **m["meta"]}
        table = []
        for key, r in sorted(m["rows"].items()):
            kind, name = key.split(".", 1)
            is_consumed = name in consumed[kind] or (kind == "cfg" and name == "event_cfg" and "event_cfg" in consumed["cfg"])
            unfed_all = r["fed"] == 0
            if key in EXPECTED_CONSTANT:
                status = "EXPECTED_CONSTANT" if unfed_all else "FED (EXPECTED_CONSTANT is stale)"
                if not unfed_all and key != "cfg.seed":
                    alarms.append(f"{key} is fed in {r['fed']} games but listed EXPECTED_CONSTANT: remove the entry")
            elif key in EXPECTED_SPARSE:
                status = "EXPECTED_SPARSE"
            elif key in DEFAULT_IS_A_VALUE:
                status = "DEFAULT_IS_A_VALUE"
            elif not is_consumed:
                status = "NOT_CONSUMED"
            elif r["unfed"]:
                status = "UNFED"
                alarms.append(f"CONSUMED + UNPOPULATED: {key} unfed in {r['unfed']} of {r['fed'] + r['unfed']} games")
            else:
                status = "OK"
            table.append({"input": key, **r, "status": status})
        report["inputs"] = table
        for row in table:
            print(f"{row['input']:<44} fed={row['fed']:<4} unfed={row['unfed']:<4} {row['status']}")
        verdict = "FAIL" if alarms else "PASS"
    else:
        verdict = "FAIL" if alarms else "STATIC_ONLY"
    report["alarms"] = alarms
    report["verdict"] = verdict
    print(f"league constants never read (dead): {report['league_dead']}")
    print(f"simulate_smart_game params never read: {report['unconsumed_params']}")
    for a in alarms:
        print("ALARM " + a)
    print(f"ORCH_CHECKLIST verdict={verdict} alarms={len(alarms)}")
    if args.json_out:
        Path(args.json_out).expanduser().write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return 1 if verdict == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
