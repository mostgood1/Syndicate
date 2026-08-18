#!/usr/bin/env python3
"""Gating input checklist for the soccer sim engine (`soccersim`).

Mandated by `docs/ai_context/model_engine_standard.md` §1. The reference
implementation is `scripts/sim_input_checklist.py` (MLB); this is soccer's, and
it exists because the standard's own failure shape is present here:

    share = _first_float(possession_metrics, ["possession_share", ...])

If nothing populates `possession_metrics`, that returns None forever, the caller
falls back to a neutral default, the sim runs, the tests pass, and the output is
identical to a build where the feature does not exist.

WHY THIS IS NOT A COPY OF MLB'S. MLB's profiles are FLAT dataclasses, so
`dataclasses.fields()` enumerates the whole input surface. Soccer's advanced
metrics live INSIDE dicts (`possession_metrics`, `set_piece_metrics`, ...), so
`fields()` alone sees five containers and none of the ~30 keys that matter. This
therefore works at two levels, and neither is a name grep:

  1. `dataclasses.fields()` over `SoccerMatchFeatures` -- the containers.
  2. AST over the engine's `_first_float(<container>, [<keys>])` call sites --
     the keys it actually reads. Structural, read from the call arguments, so a
     renamed key changes this report instead of silently passing.

CONSUMED + UNPOPULATED is the alarm, and it exits non-zero.
"""
from __future__ import annotations

import ast
import sys
from dataclasses import fields
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from syndicate.features.soccer.contracts import SoccerMatchFeatures  # noqa: E402
from syndicate.features.soccer.features.loaders import build_soccer_match_features  # noqa: E402

ENGINE = REPO / "syndicate/features/soccer/sim_engine/soccersim/possession_priors.py"

# The engine's own parameter names -> the SoccerMatchFeatures field that feeds
# them. Taken from `adapters.py::_engine_input` (:51-55), which is the single
# place the mapping is decided. `attacking_metrics` is fed from `team_metrics`
# and that indirection is exactly where xG goes missing, so it is stated here
# rather than assumed.
CONTAINER_TO_FIELD = {
    "attacking_metrics": "team_metrics",
    "defensive_metrics": "defensive_metrics",
    "possession_metrics": "possession_metrics",
    "set_piece_metrics": "set_piece_metrics",
    "tempo_metrics": "tempo_features",
    "market_features": "market_features",
    "form_metrics": "team_metrics",
    "availability_metrics": "team_metrics",
}


def consumed_keys() -> dict[str, list[list[str]]]:
    """Every `_first_float(container, [keys])` the engine performs, by container."""
    tree = ast.parse(ENGINE.read_text(encoding="utf-8"))
    out: dict[str, list[list[str]]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if getattr(node.func, "id", None) != "_first_float" or len(node.args) != 2:
            continue
        container, keys = node.args
        name = getattr(container, "id", None)
        if name is None or not isinstance(keys, ast.List):
            continue
        literal = [k.value for k in keys.elts if isinstance(k, ast.Constant) and isinstance(k.value, str)]
        if literal:
            out.setdefault(name, []).append(literal)
    return out


def main() -> int:
    # A REAL feature payload from the production constructor -- not a fixture.
    # Ratings shaped like `compute_team_ratings` output so the call is honest.
    ratings = {
        "ajax": {"attack_rating": 0.31, "defense_rating": -0.12},
        "psv": {"attack_rating": 0.28, "defense_rating": -0.09},
    }
    match = build_soccer_match_features(
        league="eredivisie", date="2026-08-19",
        home_team="Ajax", away_team="PSV", ratings=ratings,
    )

    print("SOCCER SIM INPUT CHECKLIST")
    print(f"engine: {ENGINE.relative_to(REPO)}")
    print()

    field_names = {f.name for f in fields(SoccerMatchFeatures)}
    consumed = consumed_keys()
    alarms: list[str] = []
    dead: list[str] = []

    for container in sorted(consumed):
        target = CONTAINER_TO_FIELD.get(container)
        if target is None:
            print(f"  ?     {container:22s} -> NO MAPPING in CONTAINER_TO_FIELD (engine param unknown to this script)")
            alarms.append(f"{container} (unmapped)")
            continue
        if target not in field_names:
            print(f"  FAIL  {container:22s} -> '{target}' is not a SoccerMatchFeatures field")
            alarms.append(f"{container} -> {target}")
            continue
        payload = getattr(match, target) or {}
        for keys in consumed[container]:
            present = [k for k in keys if k in payload]
            label = f"{container}.{keys[0]}"
            if present:
                print(f"  ok    {label:46s} fed by {present[0]!r}")
            else:
                print(f"  ALARM {label:46s} CONSUMED, container '{target}' has none of {keys}")
                alarms.append(label)

    print()
    print(f"containers on SoccerMatchFeatures : {len(field_names)}")
    print(f"engine read sites                 : {sum(len(v) for v in consumed.values())}")
    print(f"CONSUMED + UNPOPULATED            : {len(alarms)}")
    if dead:
        print(f"populated but unread (dead)       : {len(dead)}")
    print()
    if alarms:
        print("THE ALARM. Each of these is a feature the simulation reads and nothing")
        print("feeds; every one returns a neutral default and is indistinguishable")
        print("from a build where the feature does not exist.")
        for a in alarms:
            print(f"  - {a}")
        return 1
    print("All consumed inputs are populated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
