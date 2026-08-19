#!/usr/bin/env python3
"""Gating input checklist for the hockeysim engine (NHL).

Mandated by `docs/ai_context/model_engine_standard.md` §1. Reference implementation:
`scripts/sim_input_checklist.py` (MLB). This is NHL's, and it exists because the standard's own
failure shape was found here TWICE in one pass:

    elo_p = _elo_win_prob(home.elo_rating, away.elo_rating, profile)   # nothing populated elo_rating
    p_goal_home *= (1.0 + 1.5 * st_home.get("pp_pct", 0.2))            # st_home always {} -> 0.2

If nothing populates a field a `.get(key, NEUTRAL)` default reads, the call returns the neutral
value forever, the sim runs, the tests pass, and the output is identical to a build where the
feature does not exist. `elo_rating` and `HockeyTeamFeatures.special_teams` (`pp_pct`/`pk_pct`/
`committed_per_game`) are now fixed (`historical_truth/elo_builder.py` +
`scripts/build_nhl_elo_artifact.py`; `historical_truth/special_teams_builder.py` +
`scripts/build_nhl_special_teams_artifact.py`).

CORRECTION, 2026-08-18: an earlier pass of this script AST-walked `engine.py`'s
`(special_teams_cal or {}).get(...)` call sites and reported those 7 keys (`pp_shot_multiplier`,
`pk_shot_multiplier`, `pp_goal_multiplier`, `pk_goal_multiplier`, `blocks_ev_rate`, `blocks_pk_rate`,
`blocks_pp_def_rate`) as what `HockeyTeamFeatures.special_teams` needs to carry. **That was wrong.**
`special_teams_cal` is a SEPARATE parameter from `st_home`/`st_away` — plumbed end-to-end
(`runtime.py` -> `engine.py`, twice) but with **no caller anywhere that ever passes it a value**
(checked: every call site either omits it or is itself a passthrough default of `None`). The dict
`build_team_features` actually populates (`HockeyTeamFeatures.special_teams`) is threaded to
`st_home`/`st_away` (`player_props.py:90-91`), whose real consumed keys are `pp_pct`, `pk_pct`,
`committed_per_game` (`engine.py:677-678,973-980`) — three keys, not seven, and none of them
overlap with `special_teams_cal`'s. This script now reports BOTH correctly and separately: Part A
is the real, now-fixed `special_teams` alarm; Part B is `special_teams_cal`'s keys, reported as
UNREACHABLE (a stricter alarm than unpopulated per the standard's §4.3 — populating
`HockeyTeamFeatures` could never fix this even in principle, because nothing reads it into that
parameter).

`HockeyTeamFeatures`/`HockeyPlayerFeatures` are FLAT dataclasses (like MLB's `BatterProfile` /
`PitcherProfile`) with exactly ONE dict-shaped exception (`special_teams`, like soccer's nested
metrics). So this works at two levels, matching whichever engine's script fits each part -- not a
name grep in either:

  1. `dataclasses.fields()` over `HockeyTeamFeatures` / `HockeyPlayerFeatures` -- the flat surface,
     measured over REAL built slates (`build_slate_features`), never a fixture.
  2. AST over `engine.py`'s `st_home.get("key", default)` / `st_away.get(...)` call sites -- the
     keys `special_teams` actually feeds, mirroring soccer's `_first_float` AST walk.

CONSUMED + UNPOPULATED is the alarm, and it exits non-zero.

Usage:
  py -3 scripts/nhl_sim_input_checklist.py
  py -3 scripts/nhl_sim_input_checklist.py --json reports/nhl_input_checklist.json
"""
from __future__ import annotations

import argparse
import ast
import glob
import json
import re
import sys
from dataclasses import fields
from pathlib import Path
from typing import Dict, List, Tuple

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from syndicate.features.nhl.sim_engine.hockeysim.contracts import (  # noqa: E402
    HockeyPlayerFeatures,
    HockeyTeamFeatures,
)
from syndicate.features.nhl.sim_engine.hockeysim.features.loaders import (  # noqa: E402
    build_slate_features,
    nhl_source_root,
)

ENGINE_DIR = REPO / "syndicate/features/nhl/sim_engine/hockeysim"
ENGINE_FILE = ENGINE_DIR / "engine.py"

# Identity / derived fields, not model INPUTS -- excluded the same way MLB's checklist excludes
# `player` and soccer's excludes containers with no engine mapping.
EXCLUDED_TEAM_FIELDS = {"name", "abbrev", "period_goal_lambdas", "special_teams"}
EXCLUDED_PLAYER_FIELDS = {"player_id", "full_name", "position"}

# Legitimately sparse, documented with a reason -- anything NOT listed, and consumed, must clear
# the floor. `is_starting_goalie` is boolean and True for exactly one player per team per game by
# definition (one starter out of ~20+ roster rows), so a low population-of-True rate is correct
# behaviour, not a defect -- the population metric below treats "differs from default" as the
# signal, and `False` IS the default, so this field's honest rate is intentionally low.
EXPECTED_SPARSE = {
    "is_starting_goalie": "true for exactly one goalie per team per game by construction",
    "pp_unit": "only players actually assigned a power-play unit carry one",
    "pk_unit": "only players actually assigned a penalty-kill unit carry one",
    "line_slot": "bench/extra players legitimately carry no line slot",
}
SPARSE_FLOOR = 0.05
POPULATED_FLOOR = 0.50


def _engine_source() -> str:
    parts = []
    for path in ENGINE_DIR.rglob("*.py"):
        try:
            parts.append(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    return "\n".join(parts)


def consumed(name: str, src: str) -> bool:
    """Does the engine READ this field anywhere? Deliberately broad, per the standard's own rule:
    a false 'consumed' costs one harmless row, a false 'unconsumed' hides the exact defect this
    script exists to find."""
    esc = re.escape(name)
    return bool(re.search(r"\." + esc + r"\b", src) or re.search(r"['\"]" + esc + r"['\"]", src))


def populated(value: object, default: object) -> bool:
    if value is None:
        return False
    if isinstance(value, (dict, list, tuple, set)):
        return len(value) > 0
    if isinstance(value, str):
        return value.strip() != ""
    if isinstance(value, bool):
        return value != default
    if isinstance(value, (int, float)):
        return value != default
    return True


def _get_calls_on(varname: str, source_path: Path) -> List[Tuple[str, object]]:
    """Every `(<varname> or {}).get("key", default)` / `<varname>.get("key", default)` call site.

    Structural (reads the call's own arguments), so a renamed/added key changes this report
    instead of silently passing -- the same discipline as soccer's `_first_float` AST walk.
    """
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    out: List[Tuple[str, object]] = []
    seen = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get"):
            continue
        if varname not in ast.dump(node.func.value):
            continue
        if not node.args or not isinstance(node.args[0], ast.Constant):
            continue
        key = node.args[0].value
        if key in seen:
            continue
        seen.add(key)
        default = node.args[1].value if len(node.args) > 1 and isinstance(node.args[1], ast.Constant) else None
        out.append((key, default))
    return out


def special_teams_consumed_keys() -> List[Tuple[str, object]]:
    """The keys `HockeyTeamFeatures.special_teams` ACTUALLY reaches: `st_home.get(...)` /
    `st_away.get(...)` in `engine.py` -- NOT `special_teams_cal`, a separate parameter (see
    `special_teams_cal_reachability` below)."""
    home = _get_calls_on("st_home", ENGINE_FILE)
    away = _get_calls_on("st_away", ENGINE_FILE)
    seen = {k for k, _ in home}
    return home + [kv for kv in away if kv[0] not in seen]


def special_teams_cal_reachability() -> Tuple[List[Tuple[str, object]], bool]:
    """The 7 keys `special_teams_cal` is CONSUMED for, and whether anything outside
    `runtime.py`/`engine.py` (i.e. any real caller) ever supplies it a value.

    `runtime.run_hockeysim_game` and `engine.HockeySim` both default this parameter to `None` and
    only pass it straight through internally -- so "reachable" means some EXTERNAL call site (a
    real producer, not this plumbing) passes `special_teams_cal=` with a value. None does, checked
    structurally: every `.py` under `syndicate/features/nhl/` for a `run_hockeysim_game(` /
    `HockeySim(` call site that supplies the keyword at all.
    """
    keys = _get_calls_on("special_teams_cal", ENGINE_FILE)
    reachable = False
    for path in (ENGINE_DIR.parent.parent).rglob("*.py"):
        if path in (ENGINE_FILE, ENGINE_DIR / "runtime.py"):
            continue  # the plumbing itself, not a caller
        try:
            src = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "special_teams_cal" in src and ("run_hockeysim_game(" in src or "HockeySim(" in src):
            reachable = True
            break
    return keys, reachable


def _mirrored_dates() -> List[str]:
    proc = nhl_source_root() / "data" / "processed"
    dates = sorted({
        m.group(1) for p in glob.glob(str(proc / "predictions_*.csv"))
        if (m := re.search(r"predictions_(\d{4}-\d{2}-\d{2})\.csv$", p))
    })
    return dates


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", type=Path, default=None)
    ap.add_argument("--warn-only", action="store_true")
    ap.add_argument("--publish", action="store_true",
                     help="write the report into the artifact tree (bounded, allowlisted) so "
                          "production can be audited without a per-game artifact stream, matching "
                          "MLB's sim_input_report pattern -- roster-level objects are not "
                          "allowlisted, this small report is.")
    args = ap.parse_args()

    dates = _mirrored_dates()
    if not dates:
        print("REFUSED: no predictions_<date>.csv found under the NHL mirror -- nothing to audit "
              "from THIS CHECKOUT. Per model_engine_standard.md §3b this means UNMEASURED, not 0%: "
              "`data/**` is a lossy, per-family-refreshed mirror, not a snapshot of what production "
              "computed. Check the served board (`/nhl/api/cards?date=...`) before concluding "
              "anything is unpopulated.")
        return 2

    src = _engine_source()
    team_hits: Dict[str, int] = {}
    player_hits: Dict[str, int] = {}
    n_teams = 0
    n_players = 0
    st_nonempty = 0
    st_key_hits: Dict[str, int] = {}

    team_defaults = {f.name: f.default for f in fields(HockeyTeamFeatures)}
    player_defaults = {f.name: f.default for f in fields(HockeyPlayerFeatures)}
    # AST-derived, NOT a hardcoded tuple (model_engine_standard.md: "never a name grep") -- a
    # hardcoded ("pp_pct", "pk_pct", "committed_per_game") tuple here previously silently missed
    # `pp_shot_index`/`pk_shot_index_allowed` (§2f) and `block_rate_index` (§2g) when they were
    # added to `special_teams_consumed_keys()`'s AST walk but not to this loop -- it reported all
    # three as 0.0% FAIL ("consumed but NEVER populated") even though `load_team_special_teams_map`
    # populates all six correctly on every team-side, checked directly. Fixed by driving this loop
    # off the same function the report table already uses, so the two can never drift again.
    st_consumed_keys = [k for k, _ in special_teams_consumed_keys()]

    for date in dates:
        games = build_slate_features(date)
        for game in games:
            for team in (game.home, game.away):
                n_teams += 1
                for f in fields(HockeyTeamFeatures):
                    if f.name in EXCLUDED_TEAM_FIELDS:
                        continue
                    if populated(getattr(team, f.name, None), team_defaults.get(f.name)):
                        team_hits[f.name] = team_hits.get(f.name, 0) + 1
                if team.special_teams:
                    st_nonempty += 1
                for key in st_consumed_keys:
                    if team.special_teams.get(key) is not None:
                        st_key_hits[key] = st_key_hits.get(key, 0) + 1
            for players in (game.home_players, game.away_players):
                for p in players:
                    n_players += 1
                    for f in fields(HockeyPlayerFeatures):
                        if f.name in EXCLUDED_PLAYER_FIELDS:
                            continue
                        if populated(getattr(p, f.name, None), player_defaults.get(f.name)):
                            player_hits[f.name] = player_hits.get(f.name, 0) + 1

    print("=" * 88)
    print("NHL SIM INPUT CHECKLIST (hockeysim)")
    print("=" * 88)
    print(f"\n  substrate: THIS CHECKOUT's data/nhl_source mirror ({nhl_source_root()})")
    print(f"  dates {len(dates)} ({dates[0]}..{dates[-1]})   games audited: sum over dates")
    print(f"  team-sides {n_teams}   players {n_players}")
    print("  a field FAILS when the engine READS it and nothing FEEDS it\n")

    failures: List[Tuple[str, str, float]] = []
    warnings: List[Tuple[str, str, float]] = []
    rows = []

    print("--- HockeyTeamFeatures " + "-" * 63)
    entries = []
    for f in fields(HockeyTeamFeatures):
        if f.name in EXCLUDED_TEAM_FIELDS:
            continue
        pct = team_hits.get(f.name, 0) / max(1, n_teams)
        entries.append((pct, f.name, consumed(f.name, src)))
    for pct, name, is_consumed in sorted(entries):
        sparse = name in EXPECTED_SPARSE
        bucket = None
        if is_consumed and pct == 0.0:
            status, bucket = "FAIL  consumed but NEVER populated", failures
        elif is_consumed and pct < SPARSE_FLOOR and not sparse:
            status, bucket = "FAIL  consumed, almost never populated", failures
        elif is_consumed and pct < POPULATED_FLOOR and not sparse:
            status, bucket = "warn  consumed, thinly populated", warnings
        elif not is_consumed and pct == 0.0:
            status = "note  unread and unfed (dead field)"
        else:
            status = "ok"
        if bucket is not None:
            bucket.append(("team", name, pct))
        rows.append({"kind": "team", "field": name, "pct": round(pct, 4), "consumed": is_consumed,
                      "status": status.split()[0]})
        if status != "ok":
            mark = "*" if sparse else " "
            print(f"  {pct:6.1%} {mark} {name:32s} {status}")

    print("\n--- HockeyPlayerFeatures " + "-" * 61)
    entries = []
    for f in fields(HockeyPlayerFeatures):
        if f.name in EXCLUDED_PLAYER_FIELDS:
            continue
        pct = player_hits.get(f.name, 0) / max(1, n_players)
        entries.append((pct, f.name, consumed(f.name, src)))
    for pct, name, is_consumed in sorted(entries):
        sparse = name in EXPECTED_SPARSE
        bucket = None
        if is_consumed and pct == 0.0:
            status, bucket = "FAIL  consumed but NEVER populated", failures
        elif is_consumed and pct < SPARSE_FLOOR and not sparse:
            status, bucket = "FAIL  consumed, almost never populated", failures
        elif is_consumed and pct < POPULATED_FLOOR and not sparse:
            status, bucket = "warn  consumed, thinly populated", warnings
        elif not is_consumed and pct == 0.0:
            status = "note  unread and unfed (dead field)"
        else:
            status = "ok"
        if bucket is not None:
            bucket.append(("player", name, pct))
        rows.append({"kind": "player", "field": name, "pct": round(pct, 4), "consumed": is_consumed,
                      "status": status.split()[0]})
        if status != "ok":
            mark = "*" if sparse else " "
            print(f"  {pct:6.1%} {mark} {name:32s} {status}")

    print("\n--- PART A: HockeyTeamFeatures.special_teams (dict; feeds st_home/st_away) " + "-" * 10)
    st_pct = st_nonempty / max(1, n_teams)
    st_keys = special_teams_consumed_keys()
    print(f"  dict populated (non-empty) on {st_pct:.1%} of team-sides")
    print(f"  keys the engine actually reads via `st_home`/`st_away`.get(key, default): {len(st_keys)}")
    for key, default in st_keys:
        pct = st_key_hits.get(key, 0) / max(1, n_teams)
        if pct == 0.0:
            failures.append(("team", f"special_teams.{key}", 0.0))
            rows.append({"kind": "team", "field": f"special_teams.{key}", "pct": 0.0,
                          "consumed": True, "status": "FAIL"})
            print(f"  {pct:6.1%}   special_teams.{key:28s} FAIL  consumed (default {default!r}) but NEVER populated")
        elif pct < POPULATED_FLOOR:
            warnings.append(("team", f"special_teams.{key}", pct))
            rows.append({"kind": "team", "field": f"special_teams.{key}", "pct": round(pct, 4),
                          "consumed": True, "status": "warn"})
            print(f"  {pct:6.1%}   special_teams.{key:28s} warn  consumed, thinly populated")
        else:
            rows.append({"kind": "team", "field": f"special_teams.{key}", "pct": round(pct, 4),
                          "consumed": True, "status": "ok"})
            print(f"  {pct:6.1%}   special_teams.{key:28s} ok")

    print("\n--- PART B: special_teams_cal (SEPARATE parameter, not fed by HockeyTeamFeatures) " + "-" * 3)
    cal_keys, cal_reachable = special_teams_cal_reachability()
    print(f"  keys the engine reads via `(special_teams_cal or {{}}).get(...)`: {len(cal_keys)}")
    print(f"  reachable from any real caller (not just runtime.py/engine.py's own passthrough): {cal_reachable}")
    resolved_cal: Dict[str, float] = {}
    if cal_reachable:
        try:
            from syndicate.features.nhl.sim_engine.hockeysim.calibration_profile import build_nhl_sim_config
            from syndicate.features.nhl.sim_engine.hockeysim.player_props import _special_teams_cal
            resolved_cal = _special_teams_cal(build_nhl_sim_config())
        except Exception as exc:  # reachable per the structural check but couldn't resolve -- say so
            print(f"  (reachable structurally, but resolving a live value failed: {exc!r})")
    for key, default in cal_keys:
        label = f"special_teams_cal.{key}"
        if not cal_reachable:
            failures.append(("team", label, 0.0))
            rows.append({"kind": "team", "field": label, "pct": 0.0, "consumed": True,
                          "status": "FAIL", "note": "unreachable, not just unpopulated"})
            print(f"  {0.0:6.1%}   {label:34s} FAIL  consumed (default {default!r}), parameter UNREACHABLE -- "
                  f"no caller anywhere supplies it, so no producer could fix this by feeding "
                  f"HockeyTeamFeatures (wrong conduit; see the module docstring)")
        elif key in resolved_cal:
            live = resolved_cal[key]
            calibrated = (default is None) or (abs(float(live) - float(default)) > 1e-9)
            rows.append({"kind": "team", "field": label, "pct": 1.0, "consumed": True,
                         "status": "ok", "note": f"live={live!r} default={default!r} calibrated={calibrated}"})
            tag = "calibrated (differs from the old neutral default)" if calibrated else "reachable, still at its neutral default -- not yet calibrated"
            print(f"  {'ok':>6}   {label:34s} live={live!r}  {tag}")
        else:
            print(f"  {'?':>6}   {label:34s} reachable now -- re-audit population, not just presence")

    print("\n" + "=" * 88)
    if failures:
        print(f"FAILURES: {len(failures)} field(s) the engine READS and nothing FEEDS\n")
        for kind, name, pct in failures:
            print(f"    {kind:8s} {name:32s} {pct:.1%}")
        print("\n  Each is a silent no-op: the sim runs, produces numbers, and those numbers are")
        print("  identical to a build where the feature does not exist.")
    else:
        print("PASS: every field the engine reads is populated above its floor.")
    if warnings:
        print(f"\n  {len(warnings)} thin field(s) — not failing, worth a look:")
        for kind, name, pct in warnings:
            print(f"    {kind:8s} {name:32s} {pct:.1%}")
    print("  (* = documented as expected-sparse in EXPECTED_SPARSE)")

    payload = {
        "schema_version": 1, "substrate": "local_checkout", "dates": dates,
        "team_sides": n_teams, "players": n_players,
        "failures": len(failures), "warnings": len(warnings), "rows": rows,
    }
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nwrote {args.json}")

    if args.publish:
        import os
        from datetime import datetime, timezone
        root = str(os.environ.get("SYNDICATE_ARTIFACT_ROOT_NHL") or "").strip()
        base = Path(root).expanduser().resolve() if root else (REPO / "data" / "nhl_source")
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        out = base / "data" / "sim_input_report" / f"sim_input_report_{stamp}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        payload["substrate"] = "worker" if root else "local_checkout"
        payload["generated_at"] = datetime.now(timezone.utc).isoformat()
        out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\npublished {out}")

    return 1 if (failures and not args.warn_only) else 0


if __name__ == "__main__":
    raise SystemExit(main())
