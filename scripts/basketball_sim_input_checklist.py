#!/usr/bin/env python3
"""Gating input checklist for the basketball smart-sim engine (NBA + WNBA).

Mandated by `docs/ai_context/model_engine_standard.md` Sec 1. Reference
implementations: `scripts/sim_input_checklist.py` (MLB, flat dataclass),
`scripts/soccer_sim_input_checklist.py` (dict-in-dataclass), and
`scripts/football_sim_input_checklist.py` (typed dataclass + payload dict).
This is basketball's, and it is a FOURTH shape none of the other three cover.

WHY THIS IS NOT A COPY OF ANY OF THEM.

  1. There is no flat per-entity dataclass to enumerate. `vendor/{wnba,nba}_
     betting_repo/src/*/sim/smart_sim.py`'s only dataclass is `SmartSimConfig`
     (n_sims, seed, roster_mode, use_pbp) -- run-level knobs, not model signal.
     The real per-player signal lives in a `PlayerPriors.rates` dict keyed by
     `(TEAM, PLAYER_KEY) -> {"pts_pm": ..., "reb_pm": ..., ...}`, and the real
     per-team signal lives in a plain DataFrame loaded from a CSV. Both are
     enumerated here by reading the CONSUMER's own literal key list via AST
     (soccer's approach), not a dataclass, and not a name grep.

  2. THE FACT THAT MAKES THIS ENGINE GENUINELY DIFFERENT: nearly the entire
     input-computation surface of the "real" vendor module is MONKEYPATCHED
     at call time. `basketball_props_smart_sim._call_source_simulate_smart_
     game_local` swaps ~20 of the vendor module's own helper functions --
     `_apply_player_priors`, `_team_adj_from_advanced_stats`,
     `_compute_player_priors_cached`, `_load_smartsim_total_calibration`,
     `_load_intervals_band_calibration`, `_load_intervals_time_profile`,
     `_load_player_stat_calibration`, `_rotation_sim_minutes_from_history`,
     `_player_split_rate_context`, `_player_career_opponent_rate_context`,
     `_opponent_position_rate_context`, `simulate_pbp_game_boxscore`,
     `simulate_event_level_boxscore`, and more (`basketball_props_smart_sim.py`
     :3842-3995) -- for Syndicate-local ports that live in
     `basketball_props_smart_sim.py` and `basketball_props_onnx.py`. So
     "the vendor import succeeded" (Level 0 below) does NOT mean vendor logic
     computed the inputs. [History: since P6 there is no vendor module and no
     patching -- the orchestrator calls these ports directly.] Only `simulate_smart_game`'s own possession/quarter
     orchestration is genuinely vendor code; the DATA is Syndicate's. This
     checklist therefore audits the LOCAL PORTS
     (`_apply_player_priors_local`, `compute_player_priors_local`,
     `_team_adj_from_advanced_stats_local`/`_team_adv_row_local`), because
     those are what actually execute in production -- auditing the vendor
     originals would answer a question about code that does not run.

  3. Level 0 (bridge reachability) is football's structural concern in a
     different shape: football's alarm is a payload never PASSED; basketball's
     is the game call never reaching the engine. Until plan P6 (2026-10-10)
     that meant the vendored module never IMPORTED and the bridge silently
     falling back to a flat stub (`todo.md` #440). P6 deleted both: the bridge's
     `_call_source_simulate_smart_game_local` now imports
     `basketball_engine.orchestrator.simulate_smart_game` and nothing vendored.
     Level 0 checks THAT, with a positive control (see its docstring). The old
     check called the deleted `_import_real_smart_sim_module_local` and raised
     AttributeError, so the published report stopped on 2026-10-10.

CONSUMED + UNPOPULATED is still the alarm. Exit 1 on any Level 0-2 or Level 4
alarm. Level 3 (optional calibration artifacts) is reported but does not fail
the gate on its own -- see the Level 3 docstring for why. Level 4 (todo #821)
covers the pregame QUARTER model, which runs before the player sim and which
nothing audited: its TeamContextLocal fields (consumed vs passed by the
builder) and whether the game model's predicted points reach off_rating.

RENDER IS THE SUBSTRATE OF RECORD (`model_engine_standard.md` Sec 3b). Levels
1-3 here read the LOCAL mirror (`data/{wnba,nba}_source/data/processed/`)
because that is what is reachable from this checkout; every population number
below is a statement about the checkout, not about production, and says so.
Level 0 is code-path reachability, not data, so it is not substrate-sensitive
the same way -- but it proves only what THIS interpreter imports; it does not
prove a live worker runs the same commit.

Usage:
    py -3 scripts/basketball_sim_input_checklist.py
    py -3 scripts/basketball_sim_input_checklist.py --json reports/basketball_input_checklist.json
"""
from __future__ import annotations

import argparse
import ast
import collections
import dataclasses
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

BRIDGE_PATH = REPO / "syndicate/features/shared/basketball_props_smart_sim.py"
ONNX_PATH = REPO / "syndicate/features/shared/basketball_props_onnx.py"


def _data_root() -> Path:
    """The root the `processed_root`s below are read from AND `--publish` writes to.

    Copied from `scripts/sim_input_checklist.py::_data_root` (MLB). MLB's own
    docstring records why it must be ONE function: that script had its read path
    hardcoded to `REPO/data` while `--publish` resolved `SYNDICATE_DATA_ROOT`, so
    **the file read from one root and wrote to another** -- on the worker it
    audited the ephemeral checkout and stamped the result as production.

    `LEAGUES[*]["processed_root"]` was hardcoded the same way. Routing both
    through here is what makes the published `host` field mean something:
    `host: worker` now says the numbers came off the mounted disk.

    Locally `SYNDICATE_DATA_ROOT` is unset and this returns `REPO/data`, i.e. the
    exact prefix that was hardcoded here before -- no local behaviour change.
    """
    root = str(os.environ.get("SYNDICATE_DATA_ROOT") or "").strip()
    return Path(root).expanduser().resolve() if root else (REPO / "data")

# Real per-sport local mirrors. Per CLAUDE.md / model_engine_standard.md Sec 3b
# these are a lossy, periodically-refreshed cold-start copy, NOT production --
# every population number below names this substrate explicitly.
LEAGUES: dict[str, dict[str, Any]] = {
    "wnba": {
        # NOT data/wnba_source/data/processed/ -- its team_advanced_stats_2026*.csv
        # are 0-byte leftovers in THIS checkout (measured: both the season file
        # and the 2026-05-30 as-of file are empty). source_artifacts/ has real,
        # non-empty as-of snapshots through 2026-07-15 (3259 bytes each) for the
        # SAME boxscores_history.csv (byte-identical, diffed). This is exactly
        # the per-family-desync trap CLAUDE.md describes: which of two
        # git-tracked mirror copies is "the" local one is not fixed per sport.
        "processed_root": _data_root() / "wnba_source/source_artifacts/data/processed",
        # The `<sport>_source` directory this league's report publishes under.
        # Stated rather than derived from the league key so a future rename has
        # to be made deliberately -- and because it is what the
        # HOT_ARTIFACT_PATTERNS glob (`*_source/source_artifacts/data/
        # sim_input_report/sim_input_report_*.json`) actually matches on.
        "source_dir": "wnba_source",
        "season": 2026,
        # Real coverage measured from boxscores_history.csv: 2026-04-25 .. 2026-07-07.
        "priors_as_of": "2026-07-08",
        "advanced_as_of": "2026-07-08",
        # Level 4 only: where the pregame smart-sim run reads predictions_<D>.csv and writes smart_sim_*.json. NOT
        # processed_root above. Measured on the fleet 2026-11-17: wnba_source/data/processed holds 17 predictions files
        # and 22 sims (newest 10-31); source_artifacts/data/processed holds 1 and 88 (newest 07-15).
        "sim_root": _data_root() / "wnba_source/data/processed",
    },
    "nba": {
        # NOTE the different sub-path from wnba above (no `source_artifacts/`) --
        # that asymmetry is the checkout's, not a typo. The PUBLISH path is
        # `source_dir/source_artifacts/data/sim_input_report/` for both, because
        # that is the only shape the allowlist glob matches.
        "processed_root": _data_root() / "nba_source/data/processed",
        "source_dir": "nba_source",
        "season": 2026,
        # Real coverage measured from boxscores_history.csv: up to 2026-05-24
        # (NBA season/finals window before the summer gap).
        "priors_as_of": "2026-05-25",
        "advanced_as_of": "2026-05-25",
        # Level 4: the same directory (fleet 2026-11-17: 42 predictions files, 266 sims, newest 11-17).
        "sim_root": _data_root() / "nba_source/data/processed",
    },
}

# Optional calibration artifacts the engine's LOCAL PORTS read (see docstring
# point 2). Each degrades gracefully to None/{} when absent -- the engine does
# not crash -- but "degrades gracefully" and "populated" are different claims,
# and the standard's own precedent (MLB's BVP) is explicit that zero is a
# failure even for a documented-sparse field. Reported as its own level rather
# than folded into Level 1/2 because these are FILE-level (once per game, not
# once per player/team) and each has a known builder tool -- see
# docs/ai_context/basketball_sim_engine_reference.md Sec on calibration.
CALIBRATION_ARTIFACTS = (
    "smart_sim_total_calibration.json",
    "intervals_band_calibration.json",
    "intervals_time_profile.json",
    "player_stat_calibration.json",
)

MIN_ROWS_FOR_A_RATE = 5  # below this a population % is UNMEASURED, not 0%.
POPULATION_FLOOR = 0.50


# --------------------------------------------------------------------------
# Structural extraction -- AST over the ACTUAL local-port source, never a grep.
# --------------------------------------------------------------------------
def _find_function(tree: ast.AST, name: str) -> ast.AST | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _literal_str(node: ast.AST) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def consumed_player_prior_keys() -> list[str]:
    """The `_pm` rate keys `_apply_player_priors_local` reads out of
    `PlayerPriors.rates`, from its own literal `stat_pm_keys = [(...), ...]`
    list (`basketball_props_smart_sim.py`). Second element of each tuple."""
    tree = ast.parse(BRIDGE_PATH.read_text(encoding="utf-8"))
    fn = _find_function(tree, "_apply_player_priors_local")
    if fn is None:
        return []
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.List):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if targets != ["stat_pm_keys"]:
                continue
            out = []
            for elt in node.value.elts:
                if isinstance(elt, ast.Tuple) and len(elt.elts) == 2:
                    key = _literal_str(elt.elts[1])
                    if key:
                        out.append(key)
            return out
    return []


def produced_player_prior_keys() -> list[str]:
    """The `_pm`-suffixed keys `compute_player_priors_local` actually WRITES
    into `PlayerPriors.rates`, from its own literal `stat_cols = {...}` dict
    (`basketball_props_onnx.py`). Excludes "min" (feeds `min_mu`, not `_pm`)."""
    tree = ast.parse(ONNX_PATH.read_text(encoding="utf-8"))
    fn = _find_function(tree, "compute_player_priors_local")
    if fn is None:
        return []
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if targets != ["stat_cols"]:
                continue
            out = []
            for k in node.value.keys:
                name = _literal_str(k)
                if name and name != "min":
                    out.append(f"{name}_pm")
            return out
    return []


def consumed_team_advanced_keys() -> list[str]:
    """The team-advanced-stats keys `_team_adv_row_local` reads, from its own
    literal `for key in [...]:` loop (`basketball_props_smart_sim.py`)."""
    tree = ast.parse(BRIDGE_PATH.read_text(encoding="utf-8"))
    fn = _find_function(tree, "_team_adv_row_local")
    if fn is None:
        return []
    for node in ast.walk(fn):
        if isinstance(node, ast.For) and isinstance(node.iter, ast.List):
            out = [s for s in (_literal_str(e) for e in node.iter.elts) if s]
            if out:
                return out
    return []


# --------------------------------------------------------------------------
# Level 0 -- bridge reachability (the #440 hypothesis, made runnable)
# --------------------------------------------------------------------------
ORCHESTRATOR_MODULE = "syndicate.features.basketball_engine.orchestrator"
BRIDGE_CALL_FN = "_call_source_simulate_smart_game_local"
# Top-level names of the vendored packages (`vendor/{nba,wnba}_betting_repo/src/`).
VENDORED_PACKAGES = ("nba_betting", "wnba_betting")


def bridge_engine_problems(bridge_source: str) -> list[str]:
    """Why the bridge's game call does NOT reach `orchestrator.simulate_smart_game`; [] when it does.

    AST, not a substring: the call function must import `simulate_smart_game` FROM the
    orchestrator package and call that name. A docstring that mentions the path does not count.
    """
    tree = ast.parse(bridge_source)
    fn = _find_function(tree, BRIDGE_CALL_FN)
    if fn is None:
        return [f"bridge: {BRIDGE_CALL_FN} is gone -- the checklist no longer knows where the game call is"]
    imported = any(
        isinstance(n, ast.ImportFrom) and n.module == ORCHESTRATOR_MODULE
        and any(a.name == "simulate_smart_game" and a.asname is None for a in n.names)
        for n in ast.walk(fn)
    )
    called = any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "simulate_smart_game"
        for n in ast.walk(fn)
    )
    problems = []
    if not imported:
        problems.append(f"bridge: {BRIDGE_CALL_FN} does not import simulate_smart_game from {ORCHESTRATOR_MODULE}")
    if not called:
        problems.append(f"bridge: {BRIDGE_CALL_FN} never calls simulate_smart_game")
    return problems


def vendored_modules_loaded(module_names: Any) -> list[str]:
    """The loaded module names that belong to a vendored basketball package."""
    return sorted(
        m for m in module_names
        if any(m == p or m.startswith(p + ".") for p in VENDORED_PACKAGES)
    )


def level0_bridge_reachability() -> tuple[list[dict[str, Any]], list[str]]:
    """Does the production game call reach the native orchestrator, with no vendored module loaded?

    Until plan P6 (2026-10-10) this asked whether the bridge's vendored-module import succeeded
    (`_import_real_smart_sim_module_local`). P6 deleted that function and its flat-stub fallback;
    the bridge now imports `basketball_engine.orchestrator.simulate_smart_game` and nothing vendored.
    Three checks, each able to fail:
      * the bridge's game call imports and calls the orchestrator's `simulate_smart_game` (AST);
      * importing the bridge and the orchestrator loads no `nba_betting`/`wnba_betting` module;
      * the orchestrator resolves each league to ITS OWN constants (`orchestrator_league` maps any
        unknown code to NBA, so a WNBA game silently run on NBA minutes would otherwise pass).
    Plus a positive control: the same checks run over a bridge with the orchestrator import
    removed and a module set with a vendored module added must alarm, or Level 0 is blind.
    """
    rows: list[dict[str, Any]] = []
    alarms: list[str] = []

    bridge_source = BRIDGE_PATH.read_text(encoding="utf-8")
    wiring = bridge_engine_problems(bridge_source)
    alarms.extend(f"LEVEL 0 WIRING: {p}" for p in wiring)

    import_error = ""
    try:
        from syndicate.features.shared import basketball_props_smart_sim  # noqa: F401
        from syndicate.features.basketball_engine import orchestrator
    except Exception as exc:
        orchestrator = None
        import_error = f"{type(exc).__name__}: {exc}"
        alarms.append(f"LEVEL 0 IMPORT: the bridge or {ORCHESTRATOR_MODULE} failed to import: {import_error}")
    engine_callable = bool(orchestrator) and callable(getattr(orchestrator, "simulate_smart_game", None))
    if orchestrator is not None and not engine_callable:
        alarms.append(f"LEVEL 0 IMPORT: {ORCHESTRATOR_MODULE}.simulate_smart_game is missing or not callable")

    vendored = vendored_modules_loaded(list(sys.modules))
    if vendored:
        alarms.append(f"LEVEL 0 VENDORED: importing the bridge + orchestrator loaded {vendored}")

    for league in LEAGUES:
        resolved = ""
        if orchestrator is not None:
            try:
                resolved = orchestrator.orchestrator_league(league).code
            except Exception as exc:
                resolved = f"{type(exc).__name__}: {exc}"
        league_ok = resolved == league
        if orchestrator is not None and not league_ok:
            alarms.append(f"LEVEL 0 LEAGUE: orchestrator_league({league!r}) resolved to {resolved!r}")
        ok = not wiring and engine_callable and not vendored and league_ok
        rows.append({
            "league": league,
            "engine": f"{ORCHESTRATOR_MODULE}.simulate_smart_game",
            "bridge_calls_orchestrator": not wiring,
            "engine_callable": engine_callable,
            "orchestrator_league": resolved,
            "vendored_modules_loaded": vendored,
            "import_error": import_error,
            "verdict": "NATIVE ORCHESTRATOR" if ok else "BROKEN",
        })

    # Positive control (model_engine_standard.md: a check that cannot fail is not a check).
    broken_bridge = bridge_source.replace(
        f"from {ORCHESTRATOR_MODULE} import OrchestratorEnv, simulate_smart_game",
        f"from {ORCHESTRATOR_MODULE} import OrchestratorEnv",
    )
    if broken_bridge == bridge_source or not bridge_engine_problems(broken_bridge):
        alarms.append("LEVEL 0 BLIND: removing the orchestrator import from the bridge did not trip the wiring "
                      "check (the import line changed shape) -- Level 0 cannot fail as written")
    if not vendored_modules_loaded([*sys.modules, "nba_betting.sim.smart_sim"]):
        alarms.append("LEVEL 0 BLIND: a loaded nba_betting.sim.smart_sim did not trip the vendored-module check")
    return rows, alarms


# --------------------------------------------------------------------------
# Level 1 -- PlayerPriors per-minute rate keys (CONSUMED vs PRODUCED vs REAL)
# --------------------------------------------------------------------------
def level1_player_priors() -> tuple[dict[str, Any], list[str], list[str]]:
    from syndicate.features.shared import basketball_props_onnx as onnx

    consumed = consumed_player_prior_keys()
    produced = produced_player_prior_keys()
    alarms: list[str] = []
    notes: list[str] = []

    if not consumed:
        alarms.append("LEVEL 1 READ NOTHING: `stat_pm_keys` literal not found in "
                       "_apply_player_priors_local -- the function was restructured "
                       "and this checklist is blind to it.")
    if not produced:
        alarms.append("LEVEL 1 READ NOTHING: `stat_cols` literal not found in "
                       "compute_player_priors_local -- restructured, checklist blind.")

    drift = sorted(set(consumed) - set(produced)) if consumed and produced else []
    if drift:
        alarms.append(
            f"KEY DRIFT: _apply_player_priors_local reads {drift} but "
            f"compute_player_priors_local's stat_cols never produces them -- "
            f"these are consumed and structurally UNPOPULATABLE regardless of data."
        )

    per_league: dict[str, Any] = {}
    for league, cfg in LEAGUES.items():
        processed_root = cfg["processed_root"]
        as_of = cfg["priors_as_of"]
        result: dict[str, Any] = {"processed_root": str(processed_root), "as_of": as_of}
        if not processed_root.is_dir():
            result["error"] = f"UNMEASURED: {processed_root} does not exist in this checkout"
            alarms.append(f"UNMEASURED: {league} player priors -- {result['error']}")
            per_league[league] = result
            continue
        try:
            priors = onnx.compute_player_priors_local(
                processed_root=processed_root, date_str=as_of,
                cfg=onnx.PlayerPriorsConfig(days_back=21),
            )
        except Exception as exc:
            result["error"] = f"{type(exc).__name__}: {exc}"
            alarms.append(f"LOADER EXCEPTION: {league} compute_player_priors_local raised {result['error']}")
            per_league[league] = result
            continue

        rates = priors.rates
        n = len(rates)
        result["rated_player_rows"] = n
        if n < MIN_ROWS_FOR_A_RATE:
            result["note"] = (
                f"UNMEASURED (FROM THIS CHECKOUT): only {n} rated (team, player) rows "
                f"as of {as_of}; data/**  is a lossy mirror (CLAUDE.md) -- this is a "
                f"statement about the checkout, not about production."
            )
            notes.append(f"{league}: {result['note']}")
            per_league[league] = result
            continue

        # Membership, NOT `value > 0.0`. `compute_player_priors_local` only
        # ever sets a `_pm` key when a player clears (min_games, min_minutes_
        # avg); below that it stores `{"min_mu": ...}` alone. A rostered
        # player who is present and genuinely recorded zero blocks/threes in
        # the window has `blk_pm: 0.0` -- a REAL, present value -- and a
        # `value > 0.0` test cannot tell that apart from the key never being
        # set at all. That is exactly the `.get(key, 1.0)`-shaped trap
        # `model_engine_standard.md` Sec4.2 warns about, just at 0.0 instead
        # of 1.0. Confirmed by measurement: the naive `> 0.0` test read
        # blk_pm/stl_pm/threes_pm as thinly populated purely because blocks,
        # steals and threes are legitimately zero for most non-starters --
        # not because the field is unfed.
        keys = consumed or produced
        pct_by_key: dict[str, float] = {}
        for key in keys:
            hits = sum(1 for rr in rates.values() if key in rr)
            pct_by_key[key] = round(100.0 * hits / n, 1)
        result["populated_pct_by_key"] = pct_by_key
        per_league[league] = result

        for key, pct in pct_by_key.items():
            if pct < POPULATION_FLOOR * 100:
                alarms.append(
                    f"UNFED: {league} PlayerPriors.rates[*].{key} populated on {pct}% "
                    f"of {n} rated rows as of {as_of} (floor {POPULATION_FLOOR:.0%}), "
                    f"FROM THIS CHECKOUT"
                )

    return {"consumed": consumed, "produced": produced, "by_league": per_league}, alarms, notes


# --------------------------------------------------------------------------
# Level 2 -- team advanced-stats keys
# --------------------------------------------------------------------------
def level2_team_advanced() -> tuple[dict[str, Any], list[str], list[str]]:
    from syndicate.features.shared import basketball_props_smart_sim as bridge

    consumed = consumed_team_advanced_keys()
    alarms: list[str] = []
    notes: list[str] = []
    if not consumed:
        alarms.append("LEVEL 2 READ NOTHING: literal key list not found in "
                       "_team_adv_row_local -- restructured, checklist blind.")

    per_league: dict[str, Any] = {}
    for league, cfg in LEAGUES.items():
        processed_root = cfg["processed_root"]
        as_of = cfg["advanced_as_of"]
        season = cfg["season"]
        result: dict[str, Any] = {"processed_root": str(processed_root), "season": season, "as_of": as_of}
        try:
            df = bridge._load_team_advanced_stats_asof_local(
                processed_root=processed_root, season=season, as_of_date_str=as_of.replace("-", ""),
            )
        except Exception as exc:
            result["error"] = f"{type(exc).__name__}: {exc}"
            alarms.append(f"LOADER EXCEPTION: {league} _load_team_advanced_stats_asof_local raised {result['error']}")
            per_league[league] = result
            continue

        n = 0 if df is None else len(df)
        result["teams"] = n
        if n < MIN_ROWS_FOR_A_RATE:
            result["note"] = f"UNMEASURED (FROM THIS CHECKOUT): only {n} team rows loaded"
            notes.append(f"{league}: {result['note']}")
            per_league[league] = result
            continue

        pct_by_key: dict[str, float] = {}
        for key in consumed:
            if key not in df.columns:
                pct_by_key[key] = 0.0
                continue
            non_null = df[key].notna().sum()
            pct_by_key[key] = round(100.0 * float(non_null) / n, 1)
        result["populated_pct_by_key"] = pct_by_key
        per_league[league] = result

        for key, pct in pct_by_key.items():
            if pct < POPULATION_FLOOR * 100:
                alarms.append(
                    f"UNFED: {league} team_advanced_stats.{key} populated on {pct}% "
                    f"of {n} teams (season={season}, as_of={as_of}, floor {POPULATION_FLOOR:.0%}), "
                    f"FROM THIS CHECKOUT"
                )

    return {"consumed": consumed, "by_league": per_league}, alarms, notes


# --------------------------------------------------------------------------
# Level 3 -- optional per-game calibration artifacts
# --------------------------------------------------------------------------
def level3_calibration_artifacts() -> tuple[dict[str, Any], list[str]]:
    """These are genuinely optional (`if not p.exists(): return None`) --
    the engine does not misbehave without them, unlike a `.get(key, 1.0)`
    silent-neutral-default field. But `model_engine_standard.md`'s own
    precedent (MLB Sec 4.2, the BVP entry in EXPECTED_SPARSE) treats total
    absence as worth reporting regardless of graceful degradation: "zero is a
    failure even for an expected-sparse field." So this level REPORTS but does
    NOT by itself fail the gate -- these are calibration LAYERS with their own
    builder tools (`vendor/{wnba,nba}_betting_repo/tools/build_intervals_band_
    calibration.py`, `build_intervals_time_profile.py`,
    `build_player_stat_calibration.py`), not per-entity model inputs, and none
    of the three has ever been observed to run in the daily pipeline (not
    audited here -- see the reference doc). Folding an unowned, never-
    scheduled builder into the hard gate would make every run fail for a
    reason no on-call engineer for this lane can fix without first deciding
    whether these calibration layers should be scheduled at all.
    """
    notes: list[str] = []
    by_league: dict[str, Any] = {}
    for league, cfg in LEAGUES.items():
        processed_root = cfg["processed_root"]
        present = {name: (processed_root / name).is_file() for name in CALIBRATION_ARTIFACTS}
        by_league[league] = present
        missing = [name for name, ok in present.items() if not ok]
        if missing:
            notes.append(
                f"{league}: ABSENT on this checkout's mirror ({processed_root}): "
                f"{', '.join(missing)}. Each degrades gracefully (engine returns None/{{}} "
                f"and skips the adjustment) -- not a crash risk, but these mechanisms are "
                f"reading as fully inert on this substrate. UNVERIFIED on Render (see reference doc)."
            )
    return by_league, notes


# --------------------------------------------------------------------------
# Level 4 -- the pregame QUARTER model's team inputs (todo #821)
# --------------------------------------------------------------------------
# Levels 1-2 audit the player sim's inputs. The quarter model (`_simulate_quarters_local`) runs BEFORE the player sim
# and its means set the player sim's target points, but nothing audited what it reads: a `TeamContextLocal` per team,
# built by the pregame worker from a job dict. That gap hid todo #821: the job build reads the game model's predicted
# total/margin under WNBA's column names, NBA's predictions carry pred_total/pred_margin, and every NBA sim ran both
# teams at baseline_off_rating (261 of 261 fleet NBA sims, 10-03..11-16). Every field held a valid-looking 110.6.
QUARTER_MODEL_CONSUMERS = ("_simulate_quarters_local", "_adjustments_local")
QUARTER_MODEL_BUILDER = "_smart_sim_worker_run_local"
GAME_MODEL_RECENT_FILES = 14
_PREDICTIONS_FILE_RE = re.compile(r"^predictions_(\d{4}-\d{2}-\d{2})\.csv$")


def _team_context_field_names() -> list[str]:
    from syndicate.features.shared.basketball_props_smart_sim import TeamContextLocal

    return [f.name for f in dataclasses.fields(TeamContextLocal)]


def _team_context_slots() -> set[str]:
    """`GameInputsLocal` fields that hold a `TeamContextLocal` (home, away), from dataclasses.fields()."""
    from syndicate.features.shared.basketball_props_smart_sim import GameInputsLocal

    return {f.name for f in dataclasses.fields(GameInputsLocal) if "TeamContextLocal" in str(f.type)}


def consumed_team_context_fields(bridge_source: str) -> dict[str, list[str]]:
    """{field: [consumer functions]} for the `TeamContextLocal` fields the quarter model READS.

    The field list comes from dataclasses.fields(); consumption from the AST of each consumer: an attribute load
    `<ctx>.<field>` or a literal `getattr(<ctx>, "<field>", ...)`, where `<ctx>` is a parameter annotated
    `TeamContextLocal` or a name bound from `<inputs>.home` / `<inputs>.away`. Never a name grep.
    """
    fields = set(_team_context_field_names())
    slots = _team_context_slots()
    tree = ast.parse(bridge_source)
    out: dict[str, list[str]] = collections.defaultdict(list)
    for fn_name in QUARTER_MODEL_CONSUMERS:
        fn = _find_function(tree, fn_name)
        if fn is None:
            continue
        ctx_names = {a.arg for a in [*fn.args.args, *fn.args.kwonlyargs]
                     if a.annotation is not None and "TeamContextLocal" in ast.unparse(a.annotation)}
        for node in ast.walk(fn):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Attribute) and node.value.attr in slots:
                ctx_names.update(t.id for t in node.targets if isinstance(t, ast.Name))

        def _is_ctx(expr: ast.AST) -> bool:
            if isinstance(expr, ast.Name):
                return expr.id in ctx_names
            return isinstance(expr, ast.Attribute) and expr.attr in slots   # inp.home.<field>

        seen: set[str] = set()
        for node in ast.walk(fn):
            if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load) and node.attr in fields and _is_ctx(node.value):
                seen.add(node.attr)
            elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr"
                  and len(node.args) >= 2 and _is_ctx(node.args[0])):
                name = _literal_str(node.args[1])
                if name in fields:
                    seen.add(name)
        for name in sorted(seen):
            out[name].append(fn_name)
    return dict(out)


def populated_team_context_fields(bridge_source: str) -> tuple[list[str], int]:
    """(fields EVERY `TeamContextLocal(...)` call in the pregame builder passes by keyword, number of such calls).
    A field a call does not pass holds its dataclass default on every pregame sim."""
    tree = ast.parse(bridge_source)
    fn = _find_function(tree, QUARTER_MODEL_BUILDER)
    if fn is None:
        return [], 0
    calls = [n for n in ast.walk(fn)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "TeamContextLocal"]
    if not calls:
        return [], 0
    passed = [{kw.arg for kw in c.keywords if kw.arg} for c in calls]
    return sorted(set.intersection(*passed)), len(calls)


def team_context_structural_alarms(bridge_source: str) -> tuple[dict[str, Any], list[str]]:
    consumed = consumed_team_context_fields(bridge_source)
    populated, n_calls = populated_team_context_fields(bridge_source)
    alarms: list[str] = []
    if not consumed:
        alarms.append(f"LEVEL 4 READ NOTHING: no TeamContextLocal field read found in {QUARTER_MODEL_CONSUMERS} -- "
                      "the quarter model was restructured and this checklist is blind to it.")
    if n_calls == 0:
        alarms.append(f"LEVEL 4 READ NOTHING: no TeamContextLocal(...) call in {QUARTER_MODEL_BUILDER} -- "
                      "the pregame builder was restructured and this checklist is blind to it.")
    unfed = sorted(set(consumed) - set(populated)) if consumed and n_calls else []
    for name in unfed:
        alarms.append(
            f"STRUCTURALLY UNFED: TeamContextLocal.{name} is read by {', '.join(consumed[name])} but no "
            f"TeamContextLocal(...) call in {QUARTER_MODEL_BUILDER} passes it -- it holds its dataclass default on "
            f"every pregame sim, regardless of data.")
    data = {
        "fields": _team_context_field_names(),
        "consumed": consumed,
        "populated_by_builder": populated,
        "builder_calls": n_calls,
        "consumed_not_populated": unfed,
        "populated_not_consumed": sorted(set(populated) - set(consumed)),
    }
    return data, alarms


def _num_like_the_job_build(value: Any) -> float | None:
    """Copy of `_smart_sim_run_date_local`'s inner `_num` (a closure there, so it cannot be imported)."""
    import numpy as np
    import pandas as pd

    try:
        numeric = float(pd.to_numeric(value, errors="coerce"))
        return numeric if np.isfinite(numeric) else None
    except Exception:
        return None


def game_model_feed_census(sim_root: Path, *, recent: int = GAME_MODEL_RECENT_FILES) -> dict[str, Any]:
    """Does the game model reach the quarter model's off_rating, measured two ways over the newest `recent`
    predictions_<D>.csv files in `sim_root`:

      * INPUT: replay the job build's own read (`_game_model_points_local`, imported, so the column names cannot
        drift from production) over every row: how many rows it would feed.
      * OUTPUT: the smart_sim_<D>_*.json artifacts of the same dates: how many carry market_anchor.game_model_fed and
        how many of those are True. Sims written before todo #821 F0 loaded carry no field and are counted apart.
    """
    import pandas as pd
    from syndicate.features.shared import basketball_props_smart_sim as bridge

    files = sorted((m.group(1), p) for p in sim_root.glob("predictions_*.csv")
                   if (m := _PREDICTIONS_FILE_RE.match(p.name)))[-int(recent):]
    rows = fed = 0
    found: collections.Counter = collections.Counter()
    unreadable: list[str] = []
    for _, path in files:
        try:
            df = pd.read_csv(path)
        except Exception as exc:
            unreadable.append(f"{path.name}: {type(exc).__name__}")
            continue
        for _, row in df.iterrows():
            _, _, audit = bridge._game_model_points_local(row, _num_like_the_job_build)
            rows += 1
            fed += int(bool(audit["game_model_fed"]))
            found.update(audit["game_model_columns"])
    sims = with_field = sims_fed = 0
    for date, _ in files:
        for sim_path in sim_root.glob(f"smart_sim_{date}_*.json"):
            sims += 1
            try:
                anchor = json.loads(sim_path.read_text(encoding="utf-8")).get("market_anchor") or {}
            except Exception:
                continue
            if isinstance(anchor, dict) and "game_model_fed" in anchor:
                with_field += 1
                sims_fed += int(bool(anchor.get("game_model_fed")))
    return {
        "sim_root": str(sim_root),
        "dates": [d for d, _ in files],
        "read_columns": list(bridge.GAME_MODEL_READ_COLUMNS_LOCAL),
        "prediction_rows": rows,
        "prediction_rows_fed": fed,
        "columns_present": {c: int(found.get(c, 0)) for c in bridge.GAME_MODEL_KNOWN_COLUMNS_LOCAL},
        "unreadable": unreadable,
        "sims": sims,
        "sims_with_field": with_field,
        "sims_fed": sims_fed,
    }


def _pct(part: int, whole: int) -> float:
    return round(100.0 * part / whole, 1) if whole else 0.0


def game_model_feed_alarms(league: str, census: dict[str, Any]) -> tuple[list[str], list[str]]:
    alarms: list[str] = []
    notes: list[str] = []
    dates = census["dates"]
    window = f"{dates[0]}..{dates[-1]}" if dates else "no dates"
    rows, fed = census["prediction_rows"], census["prediction_rows_fed"]
    present = ", ".join(f"{c} {n}" for c, n in census["columns_present"].items())
    if rows < MIN_ROWS_FOR_A_RATE:
        notes.append(f"{league}: game-model feed UNMEASURED -- {rows} predictions rows in {census['sim_root']} ({window})")
    elif fed < POPULATION_FLOOR * rows:
        alarms.append(
            f"UNFED: {league} quarter-model off_rating -- the job build's game-model read "
            f"({'/'.join(census['read_columns'])}) found values on {_pct(fed, rows)}% of {rows} predictions rows over "
            f"{len(dates)} dates ({window}); columns present: {present}. Both teams then run at baseline_off_rating "
            f"(todo #821).")
    sims, with_field, sims_fed = census["sims"], census["sims_with_field"], census["sims_fed"]
    if with_field >= MIN_ROWS_FOR_A_RATE and sims_fed < POPULATION_FLOOR * with_field:
        alarms.append(
            f"UNFED: {league} smart_sim artifacts -- market_anchor.game_model_fed is true on {_pct(sims_fed, with_field)}% "
            f"of {with_field} sims ({window}).")
    elif sims and with_field == 0:
        notes.append(f"{league}: market_anchor.game_model_fed absent on all {sims} sims ({window}) -- written before "
                     "todo #821 F0 loaded; the INPUT replay above is the reading until it does.")
    return alarms, notes


def level4_quarter_model_inputs() -> tuple[dict[str, Any], list[str], list[str]]:
    bridge_source = BRIDGE_PATH.read_text(encoding="utf-8")
    structural, alarms = team_context_structural_alarms(bridge_source)
    notes: list[str] = []
    # Positive control: the same check over a builder that stops passing off_rating must alarm, or Level 4 is blind.
    blinded = re.sub(r"off_rating=home_off_rtg,\s*", "", bridge_source, count=1)
    if blinded == bridge_source or "off_rating" not in team_context_structural_alarms(blinded)[0]["consumed_not_populated"]:
        alarms.append("LEVEL 4 BLIND: dropping off_rating from the builder's TeamContextLocal(...) call did not trip "
                      "the structural check (the call changed shape) -- Level 4 cannot fail as written")
    by_league: dict[str, Any] = {}
    for league, cfg in LEAGUES.items():
        sim_root = Path(cfg.get("sim_root") or cfg["processed_root"])
        if not sim_root.is_dir():
            by_league[league] = {"sim_root": str(sim_root), "error": "UNMEASURED: directory does not exist here"}
            notes.append(f"{league}: game-model feed UNMEASURED -- {sim_root} does not exist on this substrate")
            continue
        try:
            census = game_model_feed_census(sim_root)
        except Exception as exc:
            by_league[league] = {"sim_root": str(sim_root), "error": f"{type(exc).__name__}: {exc}"}
            alarms.append(f"LOADER EXCEPTION: {league} game-model feed census raised {type(exc).__name__}: {exc}")
            continue
        by_league[league] = census
        a, n = game_model_feed_alarms(league, census)
        alarms.extend(a)
        notes.extend(n)
    return {"structural": structural, "game_model_feed": by_league}, alarms, notes


# --------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", type=Path, default=None)
    parser.add_argument("--warn-only", action="store_true")
    parser.add_argument(
        "--publish", action="store_true",
        help="write the report into the artifact tree so PRODUCTION can be audited. The "
             "processed/ inputs this gate measures are not allowlisted; the worker runs "
             "this and publishes the bounded result instead -- MLB's sim_input_report "
             "pattern (`scripts/sim_input_checklist.py`).",
    )
    args = parser.parse_args()

    print("=" * 84)
    print("BASKETBALL SIM INPUT CHECKLIST -- NBA + WNBA smart-sim bridge")
    print("model_engine_standard.md Sec1 -- CONSUMED + UNPOPULATED is the alarm")
    print("=" * 84)

    alarms: list[str] = []
    notes: list[str] = []

    print("\nLEVEL 0 -- BRIDGE REACHABILITY (game call -> native orchestrator, nothing vendored)")
    print("-" * 84)
    l0_rows, l0_alarms = level0_bridge_reachability()
    alarms.extend(l0_alarms)
    for row in l0_rows:
        print(f"  {row['league']:5s} league={row['orchestrator_league'] or '-':5s} {row['verdict']}  ({row['engine']})")

    print("\nLEVEL 1 -- PLAYER PRIORS PER-MINUTE RATE KEYS (dict-shaped, AST not grep)")
    print("-" * 84)
    l1_data, l1_alarms, l1_notes = level1_player_priors()
    alarms.extend(l1_alarms)
    notes.extend(l1_notes)
    print(f"  consumed by _apply_player_priors_local : {l1_data['consumed']}")
    print(f"  produced by compute_player_priors_local : {l1_data['produced']}")
    for league, info in l1_data["by_league"].items():
        print(f"\n  {league.upper()}  as_of={info.get('as_of')}")
        if "error" in info:
            print(f"      ERROR: {info['error']}")
        elif "note" in info:
            print(f"      {info['note']}")
        else:
            print(f"      rated rows: {info['rated_player_rows']}")
            for key, pct in info["populated_pct_by_key"].items():
                print(f"      {key:16s} {pct:6.1f}%")

    print("\nLEVEL 2 -- TEAM ADVANCED-STATS KEYS")
    print("-" * 84)
    l2_data, l2_alarms, l2_notes = level2_team_advanced()
    alarms.extend(l2_alarms)
    notes.extend(l2_notes)
    print(f"  consumed by _team_adv_row_local : {l2_data['consumed']}")
    for league, info in l2_data["by_league"].items():
        print(f"\n  {league.upper()}  season={info.get('season')} as_of={info.get('as_of')}")
        if "error" in info:
            print(f"      ERROR: {info['error']}")
        elif "note" in info:
            print(f"      {info['note']}")
        else:
            print(f"      teams: {info['teams']}")
            for key, pct in info["populated_pct_by_key"].items():
                print(f"      {key:16s} {pct:6.1f}%")

    print("\nLEVEL 3 -- OPTIONAL PER-GAME CALIBRATION ARTIFACTS (reported, not gating)")
    print("-" * 84)
    l3_data, l3_notes = level3_calibration_artifacts()
    notes.extend(l3_notes)
    for league, present in l3_data.items():
        print(f"  {league.upper()}")
        for name, ok in present.items():
            print(f"      {'present' if ok else 'ABSENT ':8s} {name}")

    print("\nLEVEL 4 -- PREGAME QUARTER-MODEL TEAM INPUTS (TeamContextLocal + the game-model feed, todo #821)")
    print("-" * 84)
    l4_data, l4_alarms, l4_notes = level4_quarter_model_inputs()
    alarms.extend(l4_alarms)
    notes.extend(l4_notes)
    s4 = l4_data["structural"]
    print(f"  consumed by {'/'.join(QUARTER_MODEL_CONSUMERS)} : {sorted(s4['consumed'])}")
    print(f"  passed by every TeamContextLocal(...) in {QUARTER_MODEL_BUILDER} ({s4['builder_calls']} calls) : "
          f"{s4['populated_by_builder']}")
    print(f"  consumed, not passed : {s4['consumed_not_populated']}")
    for league, info in l4_data["game_model_feed"].items():
        print(f"\n  {league.upper()}  sim_root={info.get('sim_root')}")
        if "error" in info:
            print(f"      ERROR: {info['error']}")
            continue
        d = info["dates"]
        print(f"      dates: {len(d)} ({d[0] + '..' + d[-1] if d else '-'})")
        print(f"      predictions rows fed: {info['prediction_rows_fed']} of {info['prediction_rows']} "
              f"(read {'/'.join(info['read_columns'])}; present {info['columns_present']})")
        print(f"      sims: {info['sims']}  carrying game_model_fed: {info['sims_with_field']}  fed: {info['sims_fed']}")

    print("\n" + "=" * 84)
    print("SUBSTRATE: Levels 1-3 read the LOCAL MIRROR under data/{wnba,nba}_source/. "
          "Per CLAUDE.md / model_engine_standard.md Sec3b this is a lossy, periodically "
          "refreshed cold-start copy -- NOT production. Every number above is a claim "
          "about THIS CHECKOUT. This run does not read production (the local fleet, "
          "http://127.0.0.1:10000, and its data root ~/syndicate-prod/data); see the "
          "reference doc for the last independently-verified production reading "
          "(2026-08-15, lane sim-engine-phase0-census).")

    if notes:
        print()
        for note in notes:
            print(f"NOTE   {note}")
    print()
    if alarms:
        for alarm in alarms:
            print(f"ALARM  {alarm}")
        print(f"\nFAIL -- {len(alarms)} alarm(s)")
    else:
        print("PASS -- every consumed input is reachable and populated on this substrate")
    print("=" * 84)

    # Built once so `--json` and `--publish` can never describe different runs.
    report: dict[str, Any] = {
        "level0_bridge_reachability": l0_rows,
        "level1_player_priors": l1_data,
        "level2_team_advanced": l2_data,
        "level3_calibration_artifacts": l3_data,
        "level4_quarter_model_inputs": l4_data,
        "alarms": alarms,
        "notes": notes,
        "status": "fail" if alarms else "pass",
    }

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        print(f"report written: {args.json}")

    if args.publish:
        # `os` and `datetime` are imported at MODULE scope on purpose. MLB's
        # `--publish` block once did `import os` locally, which made `os` a local
        # name for the WHOLE function and turned an earlier diagnostic print into
        # an UnboundLocalError on exactly the failing path.
        base = _data_root()   # the same root LEAGUES[*]["processed_root"] read from
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        published: dict[str, Any] = {
            "schema_version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            # "worker" iff the mounted-disk root is configured; `_data_root()`
            # falls back to REPO/data on a dev box and that is "local".
            "host": "worker" if str(os.environ.get("SYNDICATE_DATA_ROOT") or "").strip() else "local",
            # CANONICAL provenance key, same spelling in all five reports.
            # See the note in the MLB checklist: `host` only means
            # SYNDICATE_DATA_ROOT was set, so it cannot distinguish a
            # worker from a laptop that has it set. The resolved path can.
            "resolved_root": str(base),
            # kept: pre-existing readers, and it is the same value here.
            "data_root": str(base),
            # This gate covers BOTH leagues in one pass -- Level 0's key drift
            # and Level 1's consumed/produced sets are shared, and the alarm
            # list is flat. Splitting it per league would mean guessing which
            # alarm belongs to whom from its text, so the WHOLE report is
            # written under each league's own `<league>_source` tree instead.
            # `published_for_league` says which copy you are holding.
            "leagues": sorted(LEAGUES),
            **report,
        }
        for league, cfg in LEAGUES.items():
            out = (base / cfg["source_dir"] / "source_artifacts/data/sim_input_report"
                   / f"sim_input_report_{stamp}.json")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(
                json.dumps({**published, "published_for_league": league}, indent=2, default=str),
                encoding="utf-8",
            )
            print(f"\npublished {out}")
        print("  This is the ONLY way the production population is readable: the")
        print("  artifacts endpoint gates on HOT_ARTIFACT_PATTERNS and the processed/")
        print("  inputs this gate measures are deliberately not on it.")

    return 1 if (alarms and not args.warn_only) else 0


if __name__ == "__main__":
    raise SystemExit(main())
