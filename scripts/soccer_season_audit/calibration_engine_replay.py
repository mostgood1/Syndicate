# -*- coding: utf-8 -*-
"""Fix #2 step B, ENGINE REPLAY. PRE-REGISTERED 2026-09-15 ~20:15Z, before this ran.

Runs the SHIPPED path from the lane worktree:
`build_soccer_player_features` -> `build_usage_profiles` -> `project_player_props`.
It scores the published `shots_over_probabilities` / `shots_on_target_over_probabilities`
on appeared outfield players, dates >= 2026-08-26, with the same squads, recs and
outcomes as runs 5-6. U_RAW is the same engine's unconditional ladder:
Poisson(`expected_shots`), and Poisson(`expected_shots_on_target`) for SOT.

H14: the engine reproduces run 6's MIX_PROD2 within 0.002 on all four pooled numbers
     (shots 0.6108 / 0.4691, SOT 0.4931 / 0.1988), and beats U_RAW on all four.
     FALSIFIED IF any number is off by more than 0.002, or any does not beat U_RAW.
     A miss means the code is not the measured model: plumbing drift, a dropped
     field, or rounding.
"""
import collections
import contextlib
import importlib.util
import io
import os
import math
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

LANE = Path(os.environ.get("SYNDICATE_CHECKOUT") or Path(__file__).resolve().parents[2])  # the checkout this file lives in
sys.path.insert(0, str(LANE))
import syndicate  # noqa: E402  -- bind the package to the LANE worktree before anything else imports it
assert Path(syndicate.__file__).resolve().parent.parent == LANE, syndicate.__file__

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("crm", HERE / "calibration_role_mixture.py")
crm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(crm)

from syndicate.features.soccer.features.loaders import build_soccer_player_features  # noqa: E402
from syndicate.features.soccer.sim_engine.soccersim import player_props as PP  # noqa: E402

assert Path(PP.__file__).resolve().is_relative_to(LANE), PP.__file__
assert hasattr(PP, "_mixture_over_probabilities"), "lane code not loaded"

CUT = "2026-08-26"
EPS = 1e-6


def clamp(x):
    return min(1 - EPS, max(EPS, x))


def main():
    print("player_props from", PP.__file__)
    recs, outc = crm.load_recs(), crm.load_outcomes()
    tmp = Path(crm.S) / "calib_engine_root"
    shutil.rmtree(tmp, ignore_errors=True)
    root = crm.rs.build_root(tmp)
    crm.bsa.roster_rows = crm.rs.seed_roster_rows
    rows_by_league = {}
    for league in crm.LEAGUES:
        with contextlib.redirect_stdout(io.StringIO()):
            rows_by_league[league] = crm.bsa._load_player_rows(league, root)

    pts = []
    with_roles = collections.Counter()
    for (lg, mid), m in recs.items():
        o = outc.get((lg, mid))
        if not o or m["shots_h"] is None or str(m["date"]) < CUT:
            continue
        dist = SimpleNamespace(mean_home_goals=m["home_mean"] or 0.0, mean_away_goals=m["away_mean"] or 0.0,
                               mean_home_shots=m["shots_h"], mean_away_shots=m["shots_a"],
                               mean_home_shots_on_target=m["sot_h"] or 0.0, mean_away_shots_on_target=m["sot_a"] or 0.0)
        with contextlib.redirect_stdout(io.StringIO()):
            feats = build_soccer_player_features(rows_by_league[lg], league=lg, date=m["date"], fixture_teams=[m["home"], m["away"]])
        for side, club in (("home", m["home"]), ("away", m["away"])):
            rows = [{"player_id": f.player_id, "player_name": f.player_name, "position": f.position, "team": f.team,
                     **dict(f.usage_metrics or {})} for f in feats if f.team == club]
            if not rows or not (m["shots_h"] if side == "home" else m["shots_a"]):
                continue
            profiles = PP.build_usage_profiles(rows, side=side, team=club)
            projections = [PP.project_player_props(dist, p) for p in profiles]
            roster = [q for q in o["players"] if q["side"] == side]
            preds = [{"player_name": p.player_name, "side": side} for p in projections]
            for i, j in crm.strict_match(preds, roster).items():
                q, proj, prof = roster[j], projections[i], profiles[i]
                if not crm.appeared(q) or prof.is_goalkeeper or proj.position.upper().startswith("G"):
                    continue
                with_roles["roles" if prof.start_probability is not None else "no_roles"] += 1
                rec = {"lg": lg, "shots": float(q.get("shots") or 0.0), "sot": float(q.get("sot") or 0.0)}
                rec["E_s1"] = clamp(proj.shots_over_probabilities["0.5"])
                rec["E_s2"] = clamp(proj.shots_over_probabilities["1.5"])
                rec["E_t1"] = clamp(proj.shots_on_target_over_probabilities["0.5"])
                rec["E_t2"] = clamp(proj.shots_on_target_over_probabilities["1.5"])
                rec["U_s1"] = clamp(PP.poisson_at_least(proj.expected_shots, 1))
                rec["U_s2"] = clamp(PP.poisson_at_least(proj.expected_shots, 2))
                rec["U_t1"] = clamp(PP.poisson_at_least(proj.expected_shots_on_target, 1))
                rec["U_t2"] = clamp(PP.poisson_at_least(proj.expected_shots_on_target, 2))
                rec["E_mean"] = proj.expected_shots_if_playing
                pts.append(rec)

    def ll(sel, arm, kind, k):
        target = "shots" if kind == "s" else "sot"
        return crm.mean(-(math.log(x[f"{arm}_{kind}{k}"]) if x[target] >= k else math.log(1 - x[f"{arm}_{kind}{k}"])) for x in sel)

    print(f"TEST (>= {CUT}) points {len(pts)} profiles {dict(with_roles)}")
    ref = {("s", 1): 0.6108, ("s", 2): 0.4691, ("t", 1): 0.4931, ("t", 2): 0.1988}
    ok = True
    for (kind, k), target in ref.items():
        e, u = ll(pts, "E", kind, k), ll(pts, "U", kind, k)
        good = abs(e - target) <= 0.002 and e < u
        ok &= good
        print(f"  {'SHOTS' if kind == 's' else 'SOT  '} P(>={k}) engine {e:.4f} (run 6 {target:.4f}, diff {e - target:+.4f}) | U_RAW {u:.4f} -> {'ok' if good else 'MISS'}")
    print(f"  mean ratio engine if_playing {crm.mean(x['E_mean'] for x in pts) / max(crm.mean(x['shots'] for x in pts), 1e-9):.2f}")
    wins = 0
    for lg in crm.LEAGUES:
        sel = [x for x in pts if x["lg"] == lg]
        if sel:
            e, u = ll(sel, "E", "s", 1), ll(sel, "U", "s", 1)
            wins += e < u
            print(f"  {lg:20s} n={len(sel):5d} shots0.5 engine {e:.4f} U_RAW {u:.4f}")
    print(f"league wins {wins}/10 | H14 {'NOT FALSIFIED' if ok else 'FALSIFIED'}")


if __name__ == "__main__":
    main()
