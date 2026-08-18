#!/usr/bin/env python3
"""Gating input checklist for the football sim engine (`smartsim2`, NFL + NCAAF).

Mandated by `docs/ai_context/model_engine_standard.md` §1. The reference
implementation is `scripts/sim_input_checklist.py` (MLB); `soccer_sim_input_checklist.py`
is soccer's. This is football's, and it exists because the standard's own failure
shape is present here in its most complete form:

    offensive_epa = _first_float(offensive_metrics, ["offensive_epa", "epa_play", ...])
    ...
    score += (offensive_epa or 0.0) * 0.55

If nothing populates `offensive_metrics`, that term contributes exactly 0.0
forever, `build_drive_priors` returns its neutral profile, the Monte Carlo runs,
the tests pass, and the output is identical to a build where the whole advanced
feature stack does not exist.

WHY THIS IS NOT A COPY OF MLB'S OR SOCCER'S. Three structural differences, and
each one defeats the other two engines' checklist shape:

  1. MLB's profiles are FLAT dataclasses, so `dataclasses.fields()` enumerates
     the whole input surface. `SmartSim2SimulationInput` has SIX meaningful
     typed fields and one untyped `feature_generation_payload: dict[str, Any]`
     that carries everything else. `fields()` alone sees a container.

  2. Soccer reads its dict keys through a single `_first_float(container, [keys])`
     shape, so one AST pass over those call sites finds them. Football reads
     through THREE shapes, and a checklist that models only the first will
     report a clean run while two thirds of the surface is unmeasured:
         `_extract_block(sources, [block_names])`   -- which dict, by alias
         `_first_float(block, [keys])`              -- which key, by alias
         `_mean_float(block.get("k") or block.get("k2") ...)` -- player usage

  3. AND THE ONE THAT ACTUALLY MATTERS HERE, which neither other sport has:
     football's engine is reached by FIVE separate entrypoint scripts that each
     construct `SmartSim2SimulationInput` themselves. A payload key can be
     perfectly populated by the feature layer and still never reach the engine,
     because the entrypoint never passes it. So this checklist has a level the
     others do not -- LEVEL 0, an AST census of every construction site, asking
     whether it passes `feature_generation_payload` AT ALL.

     CONSUMED + POPULATED + NEVER-PASSED is football's alarm, and it is invisible
     to a population measurement alone. That is why level 0 gates first.

None of the three levels is a name grep. Every one reads structure -- dataclass
fields, or the literal argument lists of the engine's own call sites -- so a
renamed key or a new entrypoint changes this report instead of silently passing.

Exit code: 0 only if every level is clean. Non-zero on any alarm, so this can
gate `/preflight` or `scripts/migration_gate.py`.

Usage:
    py -3 scripts/football_sim_input_checklist.py
    py -3 scripts/football_sim_input_checklist.py --sport nfl --season 2025 --week 1
    py -3 scripts/football_sim_input_checklist.py --json reports/football_input_checklist.json
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import fields
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from syndicate.features.football.sim_engine.smartsim2.contracts import (  # noqa: E402
    SmartSim2SimulationInput,
)

ENGINE = REPO / "syndicate/features/football/sim_engine/smartsim2/drive_priors.py"

# Every site that constructs a `SmartSim2SimulationInput`. Enumerated here rather
# than discovered by a repo-wide walk because the SET of entrypoints is itself a
# reviewable fact -- a new one appearing is a change this file should force
# someone to make deliberately. `--strict-entrypoints` re-derives the set by
# scanning `scripts/` and fails if it finds one not listed here.
#
# `kind` decides whether an unpassed payload is an ALARM or a NOTE:
#   production -- writes an artifact a user-facing surface reads. Alarm.
#   analysis   -- offline measurement/backtest. Note only; a deliberately
#                 payload-free arm is a legitimate control in a backtest.
ENTRYPOINTS: tuple[tuple[str, str, str], ...] = (
    ("scripts/generate_smartsim2_nfl_projections.py", "production", "NFL regular season -> smartsim2_projections_<season>_wk<week>.csv"),
    ("scripts/generate_smartsim2_nfl_preseason_projections.py", "production", "NFL preseason -> smartsim2_preseason_projections_<season>_wk<week>.csv"),
    ("scripts/generate_smartsim2_ncaaf_projections.py", "production", "NCAAF -> smartsim2_ncaaf_projections_<season>_wk<week>.csv"),
    ("scripts/backtest_nfl_preseason_projection.py", "analysis", "preseason backtest"),
    ("scripts/analyze_nfl_injury_adjustment_sides.py", "analysis", "injury-adjustment side analysis"),
    ("syndicate/features/football/sim_engine/smartsim2/calibration/baseline_audit.py", "analysis", "calibration baseline audit"),
)

# Typed `SmartSim2SimulationInput` fields that carry no model signal -- they are
# bookkeeping or structural, and an entrypoint that omits them is not a defect.
# Anything NOT listed here is a model input and must be passed by production.
STRUCTURAL_FIELDS = {
    "home_team",
    "away_team",
    "seed",
    "quarters",
    "quarter_seconds",
    "initial_field_position",
    "initial_down",
    "initial_distance",
    "initial_possession_owner",
}

# Payload blocks the engine reads that are LEGITIMATELY sport-specific, with the
# reason. NCAAF-only inputs are not a defect on an NFL run. Anything consumed and
# not listed here must clear the population floor on both sports.
EXPECTED_SPARSE: dict[str, str] = {
    "returning_production": "NCAAF-only: returning production is a college roster-churn concept; the NFL has no equivalent and `build_ncaaf_returning_production_snapshot.py` is the only producer",
    "coach_continuity": "NCAAF-only: `build_ncaaf_coach_continuity_snapshot.py` is the only producer",
    "transfer_impact": "NCAAF-only: the transfer portal has no NFL analogue; `build_ncaaf_transfer_portal_snapshot.py` is the only producer",
}

# A consumed block must be populated on at least this share of real games before
# it counts as fed. Deliberately low -- this gate is for ZERO, not for quality.
POPULATION_FLOOR = 0.50

# Below this many games a population percentage is NOT A MEASUREMENT and must be
# reported UNMEASURED, never as 0%. Earned on 2026-08-18: the first run of this
# script passed `season=None`, the loader fell back to a degenerate single-game
# context, and every block read "0.0% populated on 1 game" -- which reads exactly
# like a total data outage and is in fact a broken instrument. The real load at
# `season=2025, week=1` returns 272 games with `team_metrics` carrying 28 keys.
# A 0% is evidence only once the instrument is known to be able to read non-zero.
MIN_GAMES_FOR_A_RATE = 8


# --------------------------------------------------------------------------
# LEVEL 0 -- do the entrypoints pass a payload at all?
# --------------------------------------------------------------------------
def _constructor_kwargs(path: Path) -> list[tuple[set[str], list[str] | None]]:
    """`(kwargs_passed, payload_top_level_keys)` per `SmartSim2SimulationInput(...)` site.

    Read from the AST's keyword list, not from source text, so a reformatted or
    line-wrapped call reads identically and a `**kwargs` splat is visible as
    `None` rather than being silently counted as "passes nothing".

    PRESENCE IS NOT REACHABILITY, so the payload's own literal keys come back
    too. Earned on 2026-08-18: `calibration/baseline_audit.py` DOES pass a
    `feature_generation_payload`, and the first version of this gate therefore
    reported it "YES / wired". Its payload is
    `{game_id, season, week, market_total, market_spread_home}` -- and NOT ONE of
    those is a key the engine reads. `drive_priors._extract_block` wants a nested
    block named `market_features`/`market`/`betting`; a flat `market_total` is
    invisible to it. So the payload is passed, and it is inert.

    A gate that asks only "is a payload passed" would green-light exactly the
    half-fix it exists to catch. `payload_top_level_keys` is None when the
    argument is not a literal dict (a variable, a call, a splat) -- unknown, and
    unknown is reported, never assumed wired.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return []
    out: list[tuple[set[str], list[str] | None]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = getattr(func, "id", None) or getattr(func, "attr", None)
        if name != "SmartSim2SimulationInput":
            continue
        passed = {kw.arg for kw in node.keywords if kw.arg is not None}
        if any(kw.arg is None for kw in node.keywords):
            passed.add("**")  # a splat: cannot be resolved statically
        payload_keys: list[str] | None = None
        for kw in node.keywords:
            if kw.arg != "feature_generation_payload":
                continue
            if isinstance(kw.value, ast.Dict):
                payload_keys = [
                    k.value for k in kw.value.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)
                ]
        out.append((passed, payload_keys))
    return out


def level0_entrypoints(strict: bool, consumed_block_aliases: set[str]) -> tuple[list[dict[str, Any]], list[str]]:
    model_fields = [f.name for f in fields(SmartSim2SimulationInput) if f.name not in STRUCTURAL_FIELDS]
    rows: list[dict[str, Any]] = []
    alarms: list[str] = []

    for rel, kind, purpose in ENTRYPOINTS:
        path = REPO / rel
        if not path.exists():
            alarms.append(f"ENTRYPOINT MISSING: {rel} is listed in ENTRYPOINTS and does not exist")
            continue
        sites = _constructor_kwargs(path)
        if not sites:
            alarms.append(f"ENTRYPOINT NO LONGER CONSTRUCTS: {rel} builds no SmartSim2SimulationInput")
            continue
        for passed, payload_keys in sites:
            missing = [f for f in model_fields if f not in passed and "**" not in passed]
            has_payload = "feature_generation_payload" in passed or "**" in passed
            # Which of the payload's own literal keys the engine would actually
            # read. None = not statically knowable, reported as unknown.
            reachable = None if payload_keys is None else sorted(set(payload_keys) & consumed_block_aliases)
            if not has_payload:
                verdict = "NO PAYLOAD"
            elif payload_keys is None:
                verdict = "payload (keys not static)"
            elif reachable:
                verdict = f"WIRED ({len(reachable)} block(s))"
            else:
                verdict = "INERT PAYLOAD"
            rows.append({
                "entrypoint": rel,
                "kind": kind,
                "purpose": purpose,
                "passes_payload": has_payload,
                "payload_keys": payload_keys,
                "reachable_blocks": reachable,
                "verdict": verdict,
                "missing_model_fields": missing,
            })
            if kind == "production" and not has_payload:
                alarms.append(
                    f"UNWIRED PAYLOAD: {rel} constructs SmartSim2SimulationInput without "
                    f"`feature_generation_payload`, so every key `drive_priors.py` reads "
                    f"falls to its neutral default on every game this script projects"
                )
            elif kind == "production" and payload_keys is not None and not reachable:
                alarms.append(
                    f"INERT PAYLOAD: {rel} passes a `feature_generation_payload` whose keys "
                    f"({', '.join(payload_keys) or 'none'}) match NO block `drive_priors.py` reads. "
                    f"It is wired and has no effect -- presence is not reachability"
                )

    if strict:
        listed = {rel for rel, _, _ in ENTRYPOINTS}
        for candidate in sorted((REPO / "scripts").glob("*.py")):
            rel = candidate.relative_to(REPO).as_posix()
            if rel in listed:
                continue
            if _constructor_kwargs(candidate):
                alarms.append(f"UNLISTED ENTRYPOINT: {rel} constructs SmartSim2SimulationInput and is not in ENTRYPOINTS")
    return rows, alarms


# --------------------------------------------------------------------------
# LEVEL 1 -- which payload blocks and keys does the engine consume?
# --------------------------------------------------------------------------
def _literal_str_list(node: ast.AST) -> list[str]:
    if not isinstance(node, ast.List):
        return []
    return [e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]


def consumed_surface() -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """`(blocks, keys_by_local)` read structurally from the engine's call sites.

    blocks:        local variable name -> the payload dict names it will accept
                   (from `_extract_block(sources, [names])`)
    keys_by_local: local variable name -> every key read out of it (from
                   `_first_float(local, [keys])` and `local.get("key")`)

    Both come from the literal ARGUMENTS of the engine's own calls. A renamed key
    changes this output; it cannot pass silently.
    """
    tree = ast.parse(ENGINE.read_text(encoding="utf-8"))
    blocks: dict[str, list[str]] = {}
    keys: dict[str, list[str]] = {}

    for node in ast.walk(tree):
        # `local = _extract_block(sources, ["alias", ...])`
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            call = node.value
            if getattr(call.func, "id", None) == "_extract_block" and len(call.args) == 2:
                names = _literal_str_list(call.args[1])
                for target in node.targets:
                    if isinstance(target, ast.Name) and names:
                        blocks[target.id] = names

        if not isinstance(node, ast.Call):
            continue
        fname = getattr(node.func, "id", None)

        # `_first_float(local, ["key", ...])`
        if fname == "_first_float" and len(node.args) == 2:
            local = getattr(node.args[0], "id", None)
            literal = _literal_str_list(node.args[1])
            if local and literal:
                keys.setdefault(local, []).extend(literal)

        # `local.get("key")` -- the `_mean_float(player_usage.get(...) or ...)` shape
        if getattr(node.func, "attr", None) == "get" and len(node.args) == 1:
            owner = getattr(node.func.value, "id", None)
            arg = node.args[0]
            if owner and isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                keys.setdefault(owner, []).append(arg.value)

    for local in keys:
        keys[local] = sorted(dict.fromkeys(keys[local]))
    return blocks, keys


# --------------------------------------------------------------------------
# LEVEL 2 -- are those blocks populated on REAL games?
# --------------------------------------------------------------------------
def _payload_candidates(game: Any) -> dict[str, dict[str, Any]]:
    """What the feature layer holds for this game, keyed by `FootballGameFeatures` field."""
    out: dict[str, dict[str, Any]] = {}
    for f in fields(game):
        value = getattr(game, f.name, None)
        if isinstance(value, dict):
            out[f.name] = value
    return out


def level2_population(sport: str, season: int | None, week: int, blocks: dict[str, list[str]], keys: dict[str, list[str]]) -> dict[str, Any]:
    """Measure population over games the PRODUCTION feature loader returns.

    Not a fixture. `FootballSimulationAdapter.load_features` is the same call the
    analysis track makes, so what it returns is what the feature layer can
    actually supply today -- which is the honest ceiling for any wiring fix.
    """
    from syndicate.features.football.adapters import FootballSimulationAdapter

    adapter = FootballSimulationAdapter(sport=sport)
    try:
        sim_input = adapter.load_features(date="", selection=week, season=season)
    except Exception as exc:  # a loader failure is a real result, not a crash
        return {"sport": sport, "season": season, "week": week, "games": 0,
                "load_error": f"{type(exc).__name__}: {exc}", "blocks": {}}

    games = list(sim_input.games)
    if len(games) < MIN_GAMES_FOR_A_RATE:
        # NOT "0% populated". See MIN_GAMES_FOR_A_RATE -- too few games to divide by.
        #
        # AND THIS IS A STATEMENT ABOUT THIS CHECKOUT, NOT ABOUT PRODUCTION.
        # `data/**` in git is a lossy mirror (see CLAUDE.md). Measured 2026-08-18:
        # this loader returned 0 NCAAF games locally while production served 16
        # on `GET /ncaaf/api/cards?week=1`. I filed that local zero as a
        # production defect and had to retract it. The message says so explicitly
        # because the retraction is the expensive part.
        return {"sport": sport, "season": season, "week": week, "games": len(games),
                "load_error": (
                    f"loader returned {len(games)} games (< {MIN_GAMES_FOR_A_RATE}) FROM THIS CHECKOUT; "
                    f"population UNMEASURED, not zero. `data/**` is a lossy mirror -- this says "
                    f"nothing about production. Check the served board before concluding anything: "
                    f"GET /{sport}/api/cards?week={week}"
                ),
                "blocks": {}}

    # block local-name -> how many games supply at least one key the engine reads
    fed: dict[str, int] = {local: 0 for local in blocks}
    key_fed: dict[str, dict[str, int]] = {local: {} for local in blocks}

    for game in games:
        available = _payload_candidates(game)
        for local, aliases in blocks.items():
            source: dict[str, Any] = {}
            for alias in aliases:
                candidate = available.get(alias)
                if isinstance(candidate, dict) and candidate:
                    source = candidate
                    break
            wanted = keys.get(local, [])
            hits = [k for k in wanted if source.get(k) not in (None, "")]
            if hits:
                fed[local] += 1
            for k in hits:
                key_fed[local][k] = key_fed[local].get(k, 0) + 1

    n = len(games)
    return {
        "sport": sport,
        "season": season,
        "week": week,
        "games": n,
        "load_error": None,
        "blocks": {
            local: {
                "aliases_accepted": blocks[local],
                "keys_consumed": keys.get(local, []),
                "games_with_any_key": fed[local],
                "populated_pct": round(100.0 * fed[local] / n, 1),
                "per_key_pct": {k: round(100.0 * c / n, 1) for k, c in sorted(key_fed[local].items())},
            }
            for local in sorted(blocks)
        },
    }


# --------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sport", choices=["nfl", "ncaaf", "both"], default="both")
    parser.add_argument("--season", type=int, default=None)
    parser.add_argument("--week", type=int, default=1)
    parser.add_argument("--json", type=Path, default=None, help="write the bounded report artifact here")
    parser.add_argument("--strict-entrypoints", action="store_true", help="fail on a scripts/ entrypoint not listed in ENTRYPOINTS")
    parser.add_argument("--skip-population", action="store_true", help="levels 0 and 1 only (no artifact reads)")
    args = parser.parse_args()

    alarms: list[str] = []
    notes: list[str] = []

    print("=" * 78)
    print("FOOTBALL SIM INPUT CHECKLIST -- smartsim2 (NFL + NCAAF)")
    print("model_engine_standard.md §1 -- CONSUMED + UNPOPULATED is the alarm")
    print("=" * 78)

    # ---- LEVEL 1 -------------------------------------------------------
    # Runs FIRST: level 0 needs the consumed block names to tell a wired payload
    # from an inert one.
    print("\nLEVEL 1 -- CONSUMED SURFACE (structural, from the engine's own call sites)")
    print("-" * 78)
    blocks, keys = consumed_surface()
    consumed_blocks = {b: v for b, v in blocks.items()}
    all_aliases = {alias for aliases in blocks.values() for alias in aliases}
    total_keys = 0
    for local in sorted(consumed_blocks):
        wanted = keys.get(local, [])
        total_keys += len(wanted)
        sparse = " [EXPECTED_SPARSE]" if local in EXPECTED_SPARSE else ""
        print(f"  {local}{sparse}")
        print(f"      accepts blocks named: {', '.join(consumed_blocks[local])}")
        print(f"      reads keys ({len(wanted)}): {', '.join(wanted) if wanted else '(none read directly)'}")
    print(f"\nconsumed blocks: {len(consumed_blocks)}   consumed keys: {total_keys}")
    if not consumed_blocks:
        alarms.append("LEVEL 1 READ NOTHING: the AST found no `_extract_block` call sites -- the engine was restructured and this checklist is now blind")

    # ---- LEVEL 0 -------------------------------------------------------
    print("\nLEVEL 0 -- ENTRYPOINT WIRING (does the caller pass a payload the engine can READ?)")
    print("-" * 78)
    rows, l0_alarms = level0_entrypoints(args.strict_entrypoints, all_aliases)
    alarms.extend(l0_alarms)
    print(f"{'entrypoint':<62} {'kind':<11} verdict")
    for row in rows:
        print(f"{row['entrypoint']:<62} {row['kind']:<11} {row['verdict']}")
    prod = [r for r in rows if r["kind"] == "production"]
    effective = [r for r in prod if r["reachable_blocks"]]
    print(f"\nproduction entrypoints passing a payload the engine can READ: "
          f"{len(effective)} of {len(prod)}")

    # ---- LEVEL 2 -------------------------------------------------------
    population: list[dict[str, Any]] = []
    if args.skip_population:
        notes.append("population skipped by --skip-population; levels 0 and 1 only")
        print("\nLEVEL 2 -- SKIPPED (--skip-population)")
    else:
        print("\nLEVEL 2 -- POPULATION ON REAL GAMES (production feature loader, not a fixture)")
        print("-" * 78)
        sports = ["nfl", "ncaaf"] if args.sport == "both" else [args.sport]
        for sport in sports:
            # An EXPLICIT season. Passing None lets the loader fall back to a
            # degenerate context, and a degenerate context reads as a data
            # outage -- see MIN_GAMES_FOR_A_RATE.
            season = args.season
            if season is None:
                from syndicate.features.nfl.sources import latest_season

                season = latest_season()
            result = level2_population(sport, season, args.week, blocks, keys)
            population.append(result)
            print(f"\n  {sport.upper()}  season={season} week={result['week']}  games={result['games']}")
            if result["load_error"]:
                print(f"      UNMEASURED: {result['load_error']}")
                # An input surface that cannot be measured does NOT pass. A gate
                # that maps "unknown" onto its permissive branch is not a gate.
                alarms.append(f"UNMEASURED: {sport} season={season} week={args.week} -- {result['load_error']}")
                continue
            print(f"      {'block':<24} {'populated%':>11}   keys actually present")
            for local, info in result["blocks"].items():
                present = ", ".join(f"{k}={v}%" for k, v in info["per_key_pct"].items()) or "(none)"
                print(f"      {local:<24} {info['populated_pct']:>10.1f}%   {present}")
                if local in EXPECTED_SPARSE:
                    continue
                if info["populated_pct"] < POPULATION_FLOOR * 100:
                    alarms.append(
                        f"UNFED: {sport} `{local}` populated on {info['populated_pct']}% of {result['games']} games "
                        f"(floor {POPULATION_FLOOR:.0%}); the engine consumes {len(info['keys_consumed'])} keys from it"
                    )

    # ---- VERDICT -------------------------------------------------------
    print("\n" + "=" * 78)
    for local, reason in EXPECTED_SPARSE.items():
        print(f"EXPECTED_SPARSE  {local}: {reason}")
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
        print("PASS -- every consumed input is wired and populated")
    print("=" * 78)

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps({
            "entrypoints": rows,
            "consumed_blocks": {b: {"aliases": blocks[b], "keys": keys.get(b, [])} for b in sorted(blocks)},
            "population": population,
            "expected_sparse": EXPECTED_SPARSE,
            "population_floor": POPULATION_FLOOR,
            "alarms": alarms,
            "notes": notes,
            "status": "fail" if alarms else "pass",
        }, indent=2), encoding="utf-8")
        print(f"report written: {args.json}")

    return 1 if alarms else 0


if __name__ == "__main__":
    raise SystemExit(main())
