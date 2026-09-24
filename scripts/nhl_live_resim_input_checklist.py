"""Gating input checklist for the NHL LIVE re-sim (`nhl/live_resim.py`).

    py -3 scripts/nhl_live_resim_input_checklist.py
    py -3 scripts/nhl_live_resim_input_checklist.py --json report.json --publish

WHY A SECOND NHL CHECKLIST. `nhl_sim_input_checklist.py` audits the PREGAME
engine's inputs. The live re-sim consumes a strict subset of those PLUS a second
substrate the pregame path never touches: the live game state (period, clock,
score) read from `/v1/score/<date>`. Those two have completely different failure
modes and only one of them is auditable from an artifact, so auditing them
together would let a confident number about the first stand in for silence about
the second.

WHAT `model_engine_standard` §1 REQUIRES, and how each is met here:

  CONSUMED x POPULATED, both measured   -- `consumed()` greps `live_resim.py`
                                          ONLY (not the whole engine: a field
                                          the pregame sim reads and the resume
                                          does not is irrelevant here), and
                                          `populated()` measures over real
                                          `build_slate_features` output.
  `dataclasses.fields()`, never a grep  -- the field list comes from
                                          `fields(HockeyTeamFeatures)` and
                                          `fields(HockeyPlayerFeatures)`.
  compare against the DEFAULT           -- `populated()` takes the dataclass
                                          default, not None. A field sitting at
                                          its default is UNFED even though it
                                          holds a number.
  EXPECTED_SPARSE, with a reason each   -- below.
  exit non-zero                         -- so this can gate `/preflight`.
  a bounded report artifact             -- `--publish`.

THE LIVE-STATE HALF IS UNMEASURABLE TODAY AND SAYS SO. NHL is out of season
until early October 2026; `/v1/score/<date>` returns no live game, so the
fraction of live rows carrying a usable `clock` cannot be measured at all. This
script reports that as **UNMEASURED**, never as 0% and never as a pass. It is
the known gap: `/v1/schedule` returns `clock: null` on live games -- 7 of 7
measured 2026-09-22 -- which is exactly why `live_resim` reads the score
endpoint and REFUSES (`no_clock`) rather than assuming a full period.

SUBSTRATE (`model_engine_standard` §3b). A local `data/**` read is a statement
about this checkout, not about production, so the population half prints
UNMEASURED with the reason when no mirrored slate is present. `checkout` is
never a claim.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import fields
from pathlib import Path
from typing import Dict

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from syndicate.features.nhl.sim_engine.hockeysim.contracts import (  # noqa: E402
    HockeyPlayerFeatures,
    HockeyTeamFeatures,
)

LIVE_RESIM = ROOT / "syndicate" / "features" / "nhl" / "live_resim.py"

# Fields legitimately sparse, each with the reason it is allowed to be.
EXPECTED_SPARSE = {
    "line_slot": "bench and scratch players legitimately carry no line slot; the "
                 "resume REFUSES a game whose lineups carry none at all "
                 "(`no_line_slots`), which is the case that matters",
    "pp_unit": "only players actually on a power-play unit carry one",
    "pk_unit": "only players actually on a penalty-kill unit carry one",
    "is_starting_goalie": "true for exactly one goalie per team per game",
}
SPARSE_FLOOR = 0.05
POPULATED_FLOOR = 0.50

# The live-state inputs, which have NO artifact substrate. Each is read by
# `live_state_from_score_row` and each has a named refusal when absent -- that
# pairing is what keeps a missing input from becoming a silent default.
LIVE_STATE_INPUTS = {
    "gameState": "game_state_unrecognised / game_not_started / game_final",
    "periodDescriptor.number": "no_period",
    "clock.timeRemaining": "no_clock",
    "clock.inIntermission": "in_intermission",
    "homeTeam.score": "no_score",
    "awayTeam.score": "no_score",
    "homeTeam.name": "no_team_names",
    "awayTeam.name": "no_team_names",
}


def _live_resim_source() -> str:
    return LIVE_RESIM.read_text(encoding="utf-8", errors="replace")


# Accessor methods the resume calls INSTEAD of naming fields. Every field their
# bodies touch is consumed by the resume just as surely as one it names itself,
# and a name search over `live_resim.py` cannot see any of them.
#
# MEASURED WHILE WRITING THIS SCRIPT: the first version reported exactly ONE
# consumed player field (`line_slot`) and would have silently skipped
# `player_id`, `full_name`, `position`, `proj_toi`, `shot_weight`,
# `goal_weight` and `block_weight` -- seven inputs the engine genuinely runs on,
# reported as "not consumed" and therefore never checked for population. That is
# the standard's own section 4.1 failure -- ABSENT and UNFED have opposite
# remedies -- reproduced inside the tool written to prevent it.
_ACCESSORS = ("roster_row", "lineup_row")


def _fields_read_by_accessors(cls) -> set:
    """Field names the accessor methods read, via AST -- never a name grep."""
    import ast
    import inspect
    import textwrap

    out = set()
    for meth in _ACCESSORS:
        fn = getattr(cls, meth, None)
        if fn is None:
            continue
        try:
            tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
        except (OSError, SyntaxError, TypeError):
            continue
        for node in ast.walk(tree):
            if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                    and node.value.id == "self"):
                out.add(node.attr)
    return out


def consumed(name: str, src: str, via_accessor=frozenset()) -> bool:
    """Does the RESUME read this field, directly OR through an accessor it calls?

    Scoped to `live_resim.py` on purpose. A field the pregame engine consumes
    and the resume does not is not this checklist's business, and folding them
    together is how a healthy pregame number comes to vouch for the live path.

    Deliberately BROAD, per the standard's own rule: a false `consumed` costs
    one harmless row, a false `unconsumed` hides the exact defect this exists
    to find.
    """
    if name in via_accessor:
        return True
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


def _mirrored_dates() -> list[str]:
    """Dates with a mirrored NHL slate, newest first. Empty is UNMEASURED."""
    processed = ROOT / "data" / "nhl_source" / "data" / "processed"
    if not processed.is_dir():
        return []
    out = []
    for f in processed.glob("predictions_*.csv"):
        stem = f.stem.replace("predictions_", "")
        if len(stem) == 10 and stem[4] == "-":
            out.append(stem)
    return sorted(set(out), reverse=True)[:5]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", type=Path, default=None)
    ap.add_argument("--warn-only", action="store_true")
    ap.add_argument("--publish", action="store_true",
                    help="write the bounded report into the artifact tree so production can "
                         "be audited without streaming per-game rosters")
    args = ap.parse_args()

    src = _live_resim_source()
    team_defaults = {f.name: f.default for f in fields(HockeyTeamFeatures)}
    player_defaults = {f.name: f.default for f in fields(HockeyPlayerFeatures)}

    # The resume calls `roster_row()` / `lineup_row()` rather than naming most
    # of these, so their bodies decide what is genuinely consumed.
    player_via = _fields_read_by_accessors(HockeyPlayerFeatures)
    team_via = _fields_read_by_accessors(HockeyTeamFeatures)
    team_consumed = sorted(n for n in team_defaults if consumed(n, src, team_via))
    player_consumed = sorted(n for n in player_defaults if consumed(n, src, player_via))

    report: Dict[str, object] = {
        "engine": "nhl_live_resim",
        "source": str(LIVE_RESIM.relative_to(ROOT)).replace("\\", "/"),
        "team_fields_consumed": team_consumed,
        "player_fields_consumed": player_consumed,
        "live_state_inputs": LIVE_STATE_INPUTS,
    }

    print("NHL LIVE RE-SIM INPUT CHECKLIST")
    print(f"  consumed from HockeyTeamFeatures  : {', '.join(team_consumed) or '(none)'}")
    print(f"  consumed from HockeyPlayerFeatures: {', '.join(player_consumed) or '(none)'}")
    print()

    # ---- half 1: the live-state inputs. No artifact substrate, ever. --------
    print("LIVE-STATE INPUTS (read from /v1/score/<date>; NO artifact substrate)")
    missing_refusal = [k for k, reason in LIVE_STATE_INPUTS.items() if not reason.strip()]
    for key, refusal in LIVE_STATE_INPUTS.items():
        print(f"  {key:26} absent -> refuses as: {refusal}")
    print("  POPULATION: **UNMEASURED**. NHL is out of season until early October 2026, so no")
    print("  live row exists to measure. This is NOT 0% and NOT a pass. Every input above has a")
    print("  NAMED refusal, which is what keeps an absent one from becoming a silent default.")
    print()
    report["live_state_population"] = "UNMEASURED_out_of_season"

    # ---- half 2: the feature inputs, measured over a mirror if present ------
    dates = _mirrored_dates()
    if not dates:
        print("FEATURE INPUTS: **UNMEASURED** -- no `predictions_<date>.csv` under the NHL mirror")
        print("  in THIS CHECKOUT. Per model_engine_standard section 3b that is UNMEASURED, not 0%:")
        print("  `data/**` is a lossy, per-family-refreshed mirror, never a snapshot of what")
        print("  production computed. Read the served board before concluding anything is unfed.")
        report["feature_population"] = "UNMEASURED_no_mirror"
        verdict = 2
    else:
        from syndicate.features.nhl.sim_engine.hockeysim.features.loaders import (
            build_slate_features,
        )

        team_hits: Dict[str, int] = {}
        player_hits: Dict[str, int] = {}
        n_teams = n_players = 0
        for date in dates:
            for game in build_slate_features(date):
                for side in (game.home, game.away):
                    n_teams += 1
                    for name in team_consumed:
                        if populated(getattr(side, name, None), team_defaults[name]):
                            team_hits[name] = team_hits.get(name, 0) + 1
                for group in (game.home_players, game.away_players):
                    for p in group:
                        n_players += 1
                        for name in player_consumed:
                            if populated(getattr(p, name, None), player_defaults[name]):
                                player_hits[name] = player_hits.get(name, 0) + 1

        failures = []
        print(f"FEATURE INPUTS, measured over {len(dates)} mirrored date(s): "
              f"{n_teams} team-sides, {n_players} players")
        for label, names, hits, total in (
            ("team", team_consumed, team_hits, n_teams),
            ("player", player_consumed, player_hits, n_players),
        ):
            for name in names:
                rate = (hits.get(name, 0) / total) if total else 0.0
                floor = SPARSE_FLOOR if name in EXPECTED_SPARSE else POPULATED_FLOOR
                ok = rate >= floor
                flag = "ok  " if ok else "FAIL"
                note = f"  (sparse by design: {EXPECTED_SPARSE[name]})" if name in EXPECTED_SPARSE else ""
                print(f"  [{flag}] {label}.{name:24} {rate:6.1%}{note}")
                if not ok:
                    failures.append(f"{label}.{name}")
        report["feature_population"] = {
            "dates": dates, "team_sides": n_teams, "players": n_players,
            "team_hits": team_hits, "player_hits": player_hits,
        }
        report["failures"] = failures
        verdict = 1 if failures else 0
        if failures:
            print()
            print(f"  CONSUMED BUT NOT POPULATED: {', '.join(failures)}")
            print("  That combination is the alarm -- broken AND invisible. A neutral default")
            print("  makes an unfed field indistinguishable from a working one.")

    if missing_refusal:
        print(f"  [FAIL] live-state inputs with no named refusal: {missing_refusal}")
        verdict = max(verdict, 1)

    if args.json:
        args.json.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        print(f"\nwrote {args.json}")
    if args.publish:
        from syndicate.features.shared.refresh_state_store import data_root

        out = data_root() / "reports" / "nhl_live_resim_input_report.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        print(f"published {out}")

    print()
    print({0: "PASS", 1: "FAIL", 2: "UNMEASURED (not a pass)"}[verdict])
    if args.warn_only and verdict:
        print("(--warn-only: exiting 0)")
        return 0
    return verdict


if __name__ == "__main__":
    raise SystemExit(main())
