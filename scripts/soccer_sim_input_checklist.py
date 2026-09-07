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

import argparse
import ast
import json
import os
import sys
from dataclasses import fields
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from syndicate.features.soccer.contracts import SoccerMatchFeatures  # noqa: E402
from syndicate.features.soccer.features.market_odds import (  # noqa: E402
    market_lines_by_event,
)
from syndicate.features.soccer.features.loaders import (  # noqa: E402
    build_soccer_match_features,
    compute_team_ratings,
    team_rows_from_match_history,
)

ENGINE = REPO / "syndicate/features/soccer/sim_engine/soccersim/possession_priors.py"


def _data_root() -> Path:
    """The root this script both READS its history from and PUBLISHES under.

    Copied verbatim from `scripts/sim_input_checklist.py::_data_root` (MLB), and
    the reason is MLB's own scar, quoted in that function's docstring: the read
    path was hardcoded to `REPO/data` while `--publish` resolved
    `SYNDICATE_DATA_ROOT`, so **the file read from one root and wrote to
    another** -- on the worker it audited the ephemeral checkout and stamped the
    result as production.

    The `hist_dir` below was hardcoded the same way. It is routed through here so
    that ONE root answers both questions, which is what makes the `host` field in
    the published report mean anything: `host: worker` now says the numbers came
    off the mounted disk, not off whatever the checkout happens to carry.

    Locally `SYNDICATE_DATA_ROOT` is unset and this returns `REPO/data`, i.e. the
    exact path that was hardcoded here before -- no local behaviour change.
    """
    root = str(os.environ.get("SYNDICATE_DATA_ROOT") or "").strip()
    return Path(root).expanduser().resolve() if root else (REPO / "data")

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
    # WAS "team_metrics" -- a placeholder guess from before `availability_
    # metrics` existed as its own field. Corrected now that it does; a wrong
    # mapping here would have this gate reporting the field FED whenever
    # team_metrics happened to be non-empty, regardless of whether
    # availability was ever actually populated.
    "availability_metrics": "availability_metrics",
}

# `spread` and `total` are NOT SoccerMatchFeatures fields -- they are sub-dicts
# INSIDE `market_features`, read as locals:
#
#     total  = market_features.get("total")
#     spread = market_features.get("spread")
#     total_line = _first_float(total, ["line", "total", "value"])
#
# The AST walk sees the LOCAL name, so both landed in the "NO MAPPING" branch
# and were counted as alarms. That is the instrument reporting its own blind
# spot as a defect in the engine: two of the nine alarms on 2026-09-07 were
# these, and neither carried any evidence about whether the field is fed.
NESTED_CONTAINER_TO_FIELD = {
    "spread": ("market_features", "spread"),
    "total": ("market_features", "total"),
}

# UNPOPULATED BY DELIBERATE DECISION, NOT BY DEFECT -- each with the reason and
# where the reasoning lives. Modelled on MLB's `7dc4893d`, which moved five
# `vs_pitcher_*` fields out of the failure count for exactly this reason: a gate
# whose alarm list permanently contains four known-good entries cannot tell
# anyone that a FIFTH one is new. These are still printed, and still counted --
# under `disabled`, never under `failures`.
#
# Removing an entry here is a claim that the decision behind it was reversed.
# Do not silence a NEW alarm by adding to this dict.
DISABLED: dict[str, str] = {
    "attacking_metrics.goals_per_match":
        "goals are the xG STAND-IN on the football-data path (`xg_for = home_goals`), so "
        "feeding a goals field beside it puts the same number through `_attack_strength` "
        "twice -- 0.22 as xG plus 0.14 as goals = 0.36. Measured by A/B artifact build: "
        "`total_mean` 3.16 -> 3.39, `home_mean` 1.71 -> 1.89 on one eredivisie fixture. "
        "See loaders.py `NO goals_for / goals_against ON THIS PATH, DELIBERATELY`.",
    "defensive_metrics.goals_against_per_match":
        "same double-count on the defensive side (0.22 + 0.14 on `xg_against`). Same "
        "loaders.py comment.",
    "defensive_metrics.ppda":
        "the football-data history carries no ppda column, so `compute_team_ratings` emits "
        "0.0 -- and 0.0 is not 'no pressing', it is MISSING read as the most aggressive "
        "press possible (`_pressing_index` maps low ppda -> high press). loaders.py drops "
        "it rather than feed a fabricated extreme.",
    "possession_metrics.ppda":
        "same source gap and same deliberate drop as `defensive_metrics.ppda`.",
    "market_features.model_probability":
        "the engine's key list here is ['model_probability','confidence','edge'] -- all three "
        "name the MODEL's own view. Feeding the market's de-vigged win probability under that "
        "name would misstate its provenance and is circular at prior-build time (the prior is "
        "an input to the model whose probability it would be). The market's opinion IS fed, as "
        "the two things a market actually quotes: `total.line` and `spread.home_line`. "
        "Re-open this only if a genuine pre-sim model probability exists to put here.",
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
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--publish", action="store_true",
        help="write the report into the artifact tree so PRODUCTION can be audited. The "
             "per-match feature payloads this gate measures are not allowlisted; the worker "
             "runs this and publishes the bounded result instead -- MLB's sim_input_report "
             "pattern (`scripts/sim_input_checklist.py`).",
    )
    ap.add_argument(
        "--warn-only", action="store_true",
        help="report alarms but exit 0. For the PRODUCTION caller: this gate runs inside a "
             "refresh step, and a non-zero exit there marks the step failed and can mask or "
             "disrupt the build it is auditing. MLB's caller passes the same flag "
             "(`run_mlb_daily_sim_job.py`). A human run should NOT pass it -- the non-zero "
             "exit is the gate.",
    )
    args = ap.parse_args()

    # A REAL feature payload from the production constructor -- not a fixture.
    # Ratings shaped like `compute_team_ratings` output so the call is honest.
    # RATINGS COME FROM REAL HISTORY, NOT A HAND FIXTURE.
    #
    # A hand-written ratings dict drifts from what `compute_team_ratings`
    # actually emits, and then this gate reports correctly-wired fields as
    # unfed -- which it did twice on 2026-08-18, once after the xG wiring and
    # once after the converter wiring. A checklist that can be wrong in the
    # ALARMING direction is survivable; one that can be wrong in the reassuring
    # direction is not, and a stale fixture can do both.
    import csv

    hist_dir = _data_root() / "soccer_source" / "eredivisie" / "history"
    hist = sorted(hist_dir.glob("matches_*.csv"))
    if not hist:
        print("  cannot run: no eredivisie match history on disk")
        return 2
    rows: list[dict] = []
    for path in hist:
        with path.open(encoding="utf-8", newline="") as fh:
            rows.extend(dict(r) for r in csv.DictReader(fh))
    # Same optional ESPN backfill the two production loaders now read
    # (`build_soccer_artifacts.py`, `backtest_soccer_h2h_calibration.py`) --
    # kept in sync here on purpose, or this gate silently stops representing
    # what production actually feeds.
    espn_path = hist_dir / "espn_match_stats.json"
    espn_stats = json.loads(espn_path.read_text(encoding="utf-8")) if espn_path.exists() else []
    ratings = compute_team_ratings(
        team_rows_from_match_history(rows, espn_stats=espn_stats), as_of="2026-08-19", allow_undated=False
    )
    if len(ratings) < 2:
        print(f"  cannot run: only {len(ratings)} rated teams from {len(rows)} history rows")
        return 2
    home, away = sorted(ratings)[:2]
    print(f"  ratings source: {len(hist)} history file(s), {len(rows)} rows, {len(ratings)} rated teams")
    print(f"  fixture: {home} vs {away}")
    print()

    # A REAL availability value, not a synthetic one -- same discipline as the
    # ratings above. `starters_available_share` is PER-FIXTURE, not part of
    # `ratings`, so it cannot be looked up for this synthetic (home, away)
    # pairing the way ratings can; any real observed value from the same
    # artifact proves the constructor param -> engine path is genuinely wired,
    # which is what this gate checks.
    real_availability = next(
        (r["home_starters_available_share"] for r in espn_stats if r.get("home_starters_available_share") is not None),
        None,
    )
    # The MARKET LINES production now attaches, read the same way production
    # reads them -- `build_soccer_artifacts.py` calls `market_lines_by_event` on
    # this exact CSV and puts the result on the fixture as `market_features`.
    # Kept in sync here for the same reason the ESPN backfill above is: a gate
    # that constructs its payload differently from production stops representing
    # production, and its alarms stop meaning anything.
    #
    # ANY real priced event, not this synthetic pairing -- same discipline as
    # `real_availability` above. The (home, away) pair here is the two
    # alphabetically-first rated teams and need not be playing this week; what
    # the gate checks is that the constructor -> engine path carries a real
    # value, not that this particular fixture is priced.
    odds_path = hist_dir.parent / "api" / "odds" / "game_odds_current.csv"
    real_market: dict = {}
    if odds_path.is_file():
        with odds_path.open(encoding="utf-8-sig", newline="") as fh:
            priced_lines = market_lines_by_event(list(csv.DictReader(fh)))
        # SOURCED INDEPENDENTLY, not both from the first priced event. The two
        # markets have different coverage -- eredivisie 2026-09-07: 12 of 12
        # events carry a total, only 7 of 12 a spread -- so taking both from one
        # event reports `spread.home_line` UNFED whenever that event happens to
        # be one of the five without one. That is the gate reporting sampling
        # luck as a wiring defect, which is the failure this whole file exists
        # to avoid.
        first_total = next((e["total_line"] for e in priced_lines.values()
                            if e.get("total_line") is not None), None)
        first_spread = next((e["spread_home_line"] for e in priced_lines.values()
                             if e.get("spread_home_line") is not None), None)
        if first_total is not None:
            real_market["total"] = {"line": float(first_total)}
        if first_spread is not None:
            real_market["spread"] = {"home_line": float(first_spread)}
    print(f"  market lines: {odds_path.name} "
          f"{'present' if odds_path.is_file() else 'ABSENT'} -> market_features={sorted(real_market) or 'none'}")

    match = build_soccer_match_features(
        league="eredivisie", date="2026-08-19",
        home_team=home, away_team=away, ratings=ratings,
        home_starters_available_share=real_availability,
        market_features=real_market or None,
    )

    print("SOCCER SIM INPUT CHECKLIST")
    print(f"engine: {ENGINE.relative_to(REPO)}")
    print()

    field_names = {f.name for f in fields(SoccerMatchFeatures)}
    consumed = consumed_keys()
    alarms: list[str] = []
    dead: list[str] = []
    # Same rows the block below PRINTS, captured so `--publish` can carry them.
    # Pure appends -- no branch here decides anything, so the exit code cannot
    # move because of them.
    report_rows: list[dict[str, object]] = []

    disabled_rows: list[dict[str, object]] = []

    for container in sorted(consumed):
        target = CONTAINER_TO_FIELD.get(container)
        nested = NESTED_CONTAINER_TO_FIELD.get(container)
        if target is None and nested is None:
            print(f"  ?     {container:22s} -> NO MAPPING in CONTAINER_TO_FIELD (engine param unknown to this script)")
            alarms.append(f"{container} (unmapped)")
            report_rows.append({"container": container, "target": None, "field": None,
                                "status": "unmapped", "fed_by": None})
            continue
        if nested is not None:
            # A sub-dict of a real field (`market_features["spread"]`), so the
            # payload is one level down. Resolved here rather than mapped to the
            # PARENT field, which would report `spread` fed whenever
            # `market_features` held anything at all.
            outer, inner = nested
            payload = (getattr(match, outer) or {}).get(inner) or {}
            for keys in consumed[container]:
                label = f"{container}.{keys[0]}"
                present = [k for k in keys if k in payload]
                if present:
                    print(f"  ok    {label:46s} fed by {present[0]!r} (via {outer}[{inner!r}])")
                    report_rows.append({"container": container, "target": f"{outer}.{inner}",
                                        "field": keys[0], "keys_accepted": keys,
                                        "status": "ok", "fed_by": present[0]})
                else:
                    print(f"  ALARM {label:46s} CONSUMED, {outer}[{inner!r}] has none of {keys}")
                    alarms.append(label)
                    report_rows.append({"container": container, "target": f"{outer}.{inner}",
                                        "field": keys[0], "keys_accepted": keys,
                                        "status": "ALARM", "fed_by": None})
            continue
        if target not in field_names:
            print(f"  FAIL  {container:22s} -> '{target}' is not a SoccerMatchFeatures field")
            alarms.append(f"{container} -> {target}")
            report_rows.append({"container": container, "target": target, "field": None,
                                "status": "FAIL", "fed_by": None})
            continue
        payload = getattr(match, target) or {}
        for keys in consumed[container]:
            # MIRRORS THE ENGINE'S OWN LOOKUP. `_first_float(..., side=)` prefers
            # `{side}_{key}` because the payload is one dict per match while the
            # priors are built per possession owner. A checklist that only
            # checked bare keys would report correctly-wired per-team metrics as
            # unfed -- which it did, on the first run after the wiring landed.
            present = [k for k in keys if k in payload]
            if not present:
                present = [f"{sd}_{k}" for k in keys for sd in ("home", "away")
                           if f"{sd}_{k}" in payload]
            label = f"{container}.{keys[0]}"
            if present:
                print(f"  ok    {label:46s} fed by {present[0]!r}")
                report_rows.append({"container": container, "target": target, "field": keys[0],
                                    "keys_accepted": keys, "status": "ok", "fed_by": present[0]})
            elif label in DISABLED:
                # Consumed, unpopulated, and MEANT to be. Printed so it stays
                # visible, but kept out of `alarms` so the alarm list only ever
                # holds things nobody has decided about.
                print(f"  off   {label:46s} DELIBERATE -- {DISABLED[label][:72]}...")
                disabled_rows.append({"container": container, "target": target, "field": keys[0],
                                      "keys_accepted": keys, "status": "disabled",
                                      "reason": DISABLED[label]})
                report_rows.append({"container": container, "target": target, "field": keys[0],
                                    "keys_accepted": keys, "status": "disabled",
                                    "fed_by": None, "reason": DISABLED[label]})
            else:
                print(f"  ALARM {label:46s} CONSUMED, container '{target}' has none of {keys}")
                alarms.append(label)
                report_rows.append({"container": container, "target": target, "field": keys[0],
                                    "keys_accepted": keys, "status": "ALARM", "fed_by": None})

    print()
    print(f"containers on SoccerMatchFeatures : {len(field_names)}")
    print(f"engine read sites                 : {sum(len(v) for v in consumed.values())}")
    print(f"CONSUMED + UNPOPULATED            : {len(alarms)}")
    print(f"unpopulated BY DECISION (disabled): {len(disabled_rows)}")
    if dead:
        print(f"populated but unread (dead)       : {len(dead)}")
    print()
    if alarms:
        print("THE ALARM. Each of these is a feature the simulation reads and nothing")
        print("feeds; every one returns a neutral default and is indistinguishable")
        print("from a build where the feature does not exist.")
        for a in alarms:
            print(f"  - {a}")
    else:
        print("All consumed inputs are populated.")

    if args.publish:
        # `os` and `datetime` are imported at MODULE scope on purpose. MLB's
        # `--publish` block once did `import os` locally, which made `os` a local
        # name for the WHOLE function and turned an earlier diagnostic print into
        # an UnboundLocalError on exactly the failing path.
        base = _data_root()   # the same root `hist_dir` above was read from
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        out = (base / "soccer_source/source_artifacts/data/sim_input_report"
               / f"sim_input_report_{stamp}.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({
            "schema_version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            # "worker" iff the mounted-disk root is configured; `_data_root()`
            # falls back to REPO/data on a dev box and that is "local".
            "host": "worker" if str(os.environ.get("SYNDICATE_DATA_ROOT") or "").strip() else "local",
            "data_root": str(base),
            "league": "eredivisie",
            # This script's OWN counts, named for what they count -- soccer has
            # no rosters to count and must not borrow MLB's key for one.
            "history_files": len(hist),
            "history_rows": len(rows),
            "rated_teams": len(ratings),
            "containers": len(field_names),
            "read_sites": sum(len(v) for v in consumed.values()),
            "alarms": alarms,
            # Separate key, like MLB's report. A consumer counting `alarms` must
            # not have to know which entries were decisions.
            "disabled": disabled_rows,
            "rows": report_rows,
        }, indent=2), encoding="utf-8")
        print("")
        print(f"published {out}")
        print("  This is the ONLY way the production population is readable: the")
        print("  artifacts endpoint gates on HOT_ARTIFACT_PATTERNS and the per-match")
        print("  feature payloads this gate measures are deliberately not on it.")

    if alarms and args.warn_only:
        # The PRODUCTION path. Reported loudly, exit 0 -- see --warn-only's help.
        # Printed rather than silent so the refresh log distinguishes "ran and
        # found alarms" from "ran clean"; with a bare exit 0 those two are the
        # same line of output, which is the ambiguity this gate exists to remove.
        print(f"WARN_ONLY: {len(alarms)} alarm(s) reported, exiting 0 so the refresh step "
              f"is not marked failed. The published report is the instrument.")
        return 0
    return 1 if alarms else 0


if __name__ == "__main__":
    raise SystemExit(main())
