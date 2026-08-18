#!/usr/bin/env python3
"""Gating input checklist for the hockeysim engine (NHL).

Mandated by `docs/ai_context/model_engine_standard.md` §1. Reference implementation:
`scripts/sim_input_checklist.py` (MLB). This is NHL's, and it exists because the standard's own
failure shape was found here TWICE in one pass:

    elo_p = _elo_win_prob(home.elo_rating, away.elo_rating, profile)   # nothing populated elo_rating
    cal_pp_sh_mult = _f((special_teams_cal or {}).get("pp_shot_multiplier", 1.0), 1.0)  # always {}

If nothing populates a field a `.get(key, NEUTRAL)` default reads, the call returns the neutral
value forever, the sim runs, the tests pass, and the output is identical to a build where the
feature does not exist. `elo_rating` is now fixed (`historical_truth/elo_builder.py` +
`scripts/build_nhl_elo_artifact.py`); `special_teams` is not — this script is what proves that,
on real data, rather than by inspection.

`HockeyTeamFeatures`/`HockeyPlayerFeatures` are FLAT dataclasses (like MLB's `BatterProfile` /
`PitcherProfile`) with exactly ONE dict-shaped exception (`special_teams`, like soccer's nested
metrics). So this works at two levels, matching whichever engine's script fits each part -- not a
name grep in either:

  1. `dataclasses.fields()` over `HockeyTeamFeatures` / `HockeyPlayerFeatures` -- the flat surface,
     measured over REAL built slates (`build_slate_features`), never a fixture.
  2. AST over `engine.py`'s `(special_teams_cal or {}).get("key", default)` call sites -- the keys
     actually read out of the one dict field, mirroring soccer's `_first_float` AST walk.

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


def special_teams_consumed_keys() -> List[Tuple[str, object]]:
    """Every `(special_teams_cal or {}).get("key", default)` call site in `engine.py`.

    Structural (reads the call's own arguments), so a renamed/added key changes this report
    instead of silently passing -- the same discipline as soccer's `_first_float` AST walk.
    """
    tree = ast.parse(ENGINE_FILE.read_text(encoding="utf-8"))
    out: List[Tuple[str, object]] = []
    seen = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get"):
            continue
        if "special_teams_cal" not in ast.dump(node.func.value):
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

    team_defaults = {f.name: f.default for f in fields(HockeyTeamFeatures)}
    player_defaults = {f.name: f.default for f in fields(HockeyPlayerFeatures)}

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

    print("\n--- HockeyTeamFeatures.special_teams (dict; AST-walked keys) " + "-" * 25)
    st_pct = st_nonempty / max(1, n_teams)
    st_keys = special_teams_consumed_keys()
    print(f"  dict populated (non-empty) on {st_pct:.1%} of team-sides")
    print(f"  keys the engine actually reads via `.get(key, default)`: {len(st_keys)}")
    for key, default in st_keys:
        # An empty container makes every key inside it 0% by definition -- the only case this
        # script needs to resolve without re-reading each team's raw dict on every date.
        if st_nonempty == 0:
            failures.append(("team", f"special_teams.{key}", 0.0))
            rows.append({"kind": "team", "field": f"special_teams.{key}", "pct": 0.0,
                          "consumed": True, "status": "FAIL"})
            print(f"  {0.0:6.1%}   special_teams.{key:28s} FAIL  consumed (default {default!r}) but NEVER populated")
        else:
            print(f"  {'?':>6}   special_teams.{key:28s} dict is sometimes populated -- audit per-key rate manually")

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
