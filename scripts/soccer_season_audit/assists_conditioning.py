# -*- coding: utf-8 -*-
"""`#673` H33, measurement BEFORE code. PRE-REGISTERED 2026-09-18 in `.syndicate/lanes.md`
(lane `soccer-prop-conditioning`, commit e332c7c4), before this ran.

The board prices `player_assists` off `assists_over_probabilities`, a Poisson ladder
over the UNCONDITIONAL mean, while shots and shots on target price a start/sub mixture
conditional on the player appearing. A book voids a player prop on a DNP, so the
settled population is APPEARED players, and that is the population scored here.

Population: appeared outfield (player, match) rows, dates 2026-07-22..2026-09-14, the
SHIPPED engine from this checkout replayed on fix #1's squads (the
`calibration_role_mixture` harness). TRAIN dates < 2026-08-26 (the one fitted
constant, MIX_c's c), TEST dates >= 2026-08-26 (every verdict). Outcome: the ESPN
box score's `goalAssists` (`outcomes.py`, which now extracts it).

Arms, scored as P(assists >= 1) and P(assists >= 2):
  U      `assists_over_probabilities`, today's board: Poisson(`expected_assists`)
  DIV    Poisson(`expected_assists_if_playing`) = Poisson(expected_assists / max(m, 0.25))
  MIX    the goals mixture applied to assists, nothing new fitted:
         a_full = team_goals * 0.72 * rate_a / sum(rate_a * m_onpitch) over the side,
         rate_a = xa_per90 (else assists_per90), m_onpitch = the engine's season-scoped
         on-pitch minutes share; components (pS, a_full * 83.1/90) and
         (1 - pS, 1.8 * a_full * 15.6/90), pS = the profile's `start_probability`.
         No set-piece bonus: the goals mixture carries no penalty bonus either.
  MIX_c  MIX with both component means scaled by c, c in 0.50..1.60 step 0.05, fitted
         on TRAIN log loss at line 0.5. Reported, not a hypothesis.

H33: MIX beats U on TEST log loss at line 0.5, pooled AND in >= 8 of 10 leagues, AND
     MIX beats DIV pooled at line 0.5. FALSIFIED otherwise.
Reported: line 1.5 log loss, Brier at 0.5, level ratio (mean predicted / realised).

Run from the lane worktree:
    SOCCER_AUDIT_CACHE=<cache> SYNDICATE_REPO_ROOT=<a tree with data/> \
        py -3 scripts/soccer_season_audit/assists_conditioning.py [--shipped]

RESULT, 2026-09-18 on `origin/main` e332c7c4 (before the engine change): H33 NOT
FALSIFIED. TEST line 0.5 log loss U 0.2366 / DIV 0.2331 / MIX 0.2309, MIX beats U
in 9 of 10 leagues (EPL the loss), level U 0.74 / DIV 1.13 / MIX 0.93, c fit 1.00.

`--shipped` is the reproduction check for the engine change H33 licensed: it
requires the engine's OWN `assists_over_probabilities` to equal the MIX arm to 4 dp
on every row, stamped `appearing`, and prints the pooled log loss it produces. A
miss means the code is not the measured model.
"""
import contextlib
import importlib.util
import io
import math
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

CHECKOUT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(CHECKOUT))
import syndicate  # noqa: E402  -- bind the package to THIS checkout before `common` inserts another

assert Path(syndicate.__file__).resolve().parent.parent == CHECKOUT, syndicate.__file__

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("crm_h33", HERE / "calibration_role_mixture.py")
crm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(crm)

from syndicate.features.soccer.features.loaders import build_soccer_player_features  # noqa: E402
from syndicate.features.soccer.sim_engine.soccersim import player_props as PP  # noqa: E402

assert Path(PP.__file__).resolve().is_relative_to(CHECKOUT), PP.__file__

FIRST, CUT, LAST = "2026-07-22", "2026-08-26", "2026-09-14"
ASSISTED_GOAL_SHARE = 0.72
MIN_START, MIN_SUB, SUB_INTENSITY = 83.1, 15.6, 1.8
C_GRID = [round(0.50 + 0.05 * i, 2) for i in range(23)]
EPS = 1e-6
SHIPPED = "--shipped" in sys.argv


def num(value):
    try:
        f = float(value)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def rate(row, keys):
    for key in keys:
        value = row.get(key)
        if value is None or str(value).strip() == "":
            continue
        f = num(value)
        if f is not None:
            return max(0.0, f)
    return 0.0


def on_pitch_minutes(rows):
    """The engine's season-scoped on-pitch minutes share (`build_usage_profiles`)."""
    season_max = {}
    for r in rows:
        games = num(r.get("games"))
        if games:
            key = str(r.get("season"))
            season_max[key] = max(season_max.get(key, 0.0), games)
    out = []
    for r in rows:
        games, played = num(r.get("games")), num(r.get("minutes"))
        matches = season_max.get(str(r.get("season")), 0.0)
        if games and played is not None and matches > 0:
            value = played / (matches * 90.0)
        else:
            value = rate(r, ("expected_minutes_share", "minutes_share", "minutes_pct"))
        out.append(min(1.0, max(0.0, value if value > 0 else 1.0)))
    return out


def p_ge(mu, k):
    return PP.poisson_at_least(max(mu, 0.0), k)


def mix(x, k, c):
    p_start, lam_start, lam_sub = x["mix"]
    return p_start * p_ge(c * lam_start, k) + (1.0 - p_start) * p_ge(c * lam_sub, k)


def log_loss(ps, ys):
    total = 0.0
    for p, y in zip(ps, ys):
        p = min(1 - EPS, max(EPS, p))
        total -= math.log(p) if y else math.log(1 - p)
    return total / max(len(ys), 1)


def brier(ps, ys):
    return sum((p - y) ** 2 for p, y in zip(ps, ys)) / max(len(ys), 1)


def main():
    print("engine from", PP.__file__)
    recs, outc = crm.load_recs(), crm.load_outcomes()
    tmp = Path(crm.S) / "calib_assists_root"
    shutil.rmtree(tmp, ignore_errors=True)
    root = crm.rs.build_root(tmp)
    crm.bsa.roster_rows = crm.rs.seed_roster_rows
    rows_by_league = {}
    for league in crm.LEAGUES:
        with contextlib.redirect_stdout(io.StringIO()):
            rows_by_league[league] = crm.bsa._load_player_rows(league, root)

    pts, ladder_checked, ladder_mismatch = [], 0, 0
    for (lg, mid), m in recs.items():
        o = outc.get((lg, mid))
        date = str(m["date"])
        if not o or m["shots_h"] is None or not (FIRST <= date <= LAST):
            continue
        dist = SimpleNamespace(
            mean_home_goals=m["home_mean"] or 0.0, mean_away_goals=m["away_mean"] or 0.0,
            mean_home_shots=m["shots_h"], mean_away_shots=m["shots_a"],
            mean_home_shots_on_target=m["sot_h"] or 0.0, mean_away_shots_on_target=m["sot_a"] or 0.0,
        )
        with contextlib.redirect_stdout(io.StringIO()):
            feats = build_soccer_player_features(rows_by_league[lg], league=lg, date=date, fixture_teams=[m["home"], m["away"]])
        for side, club, team_goals in (("home", m["home"], m["home_mean"]), ("away", m["away"], m["away_mean"])):
            if not team_goals:
                continue
            rows = [{"player_id": f.player_id, "player_name": f.player_name, "position": f.position, "team": f.team,
                     **dict(f.usage_metrics or {})} for f in feats if f.team == club]
            if not rows:
                continue
            profiles = PP.build_usage_profiles(rows, side=side, team=club)
            projections = [PP.project_player_props(dist, p) for p in profiles]
            minutes = on_pitch_minutes(rows)
            rates = [rate(r, ("xa_per90", "assists_per90", "xa", "assists")) for r in rows]
            denom = sum(r * mm for r, mm in zip(rates, minutes))
            roster = [q for q in o["players"] if q["side"] == side]
            preds = [{"player_name": p.player_name, "side": side} for p in projections]
            for i, j in crm.strict_match(preds, roster).items():
                q = roster[j]
                prof, proj = profiles[i], projections[i]
                if not crm.appeared(q) or prof.is_goalkeeper or proj.position.upper().startswith("G"):
                    continue
                assists = q.get("assists")
                if assists is None:
                    continue
                # REACHABILITY: U must BE the engine's published ladder, or this
                # scores a reconstruction instead of the board's number.
                ladder_checked += 1
                if not SHIPPED and abs(proj.assists_over_probabilities["0.5"] - round(p_ge(proj.expected_assists, 1), 4)) > 2e-4:
                    ladder_mismatch += 1
                a_full = team_goals * ASSISTED_GOAL_SHARE * rates[i] / denom if denom > 0 else 0.0
                p_start = prof.start_probability if prof.start_probability is not None else 0.5
                pts.append({
                    "lg": lg, "date": date, "y1": int(assists >= 1), "y2": int(assists >= 2),
                    "U1": proj.assists_over_probabilities["0.5"], "U2": proj.assists_over_probabilities["1.5"],
                    "D1": p_ge(proj.expected_assists_if_playing, 1), "D2": p_ge(proj.expected_assists_if_playing, 2),
                    "mix": (p_start, a_full * MIN_START / 90.0, SUB_INTENSITY * a_full * MIN_SUB / 90.0),
                    "E1": proj.assists_over_probabilities["0.5"], "E2": proj.assists_over_probabilities["1.5"],
                    "Ec": (getattr(proj, "ladder_conditioning", None) or {}).get("assists_over_probabilities"),
                })

    if SHIPPED:
        off = [x for x in pts if abs(x["E1"] - round(mix(x, 1, 1.0), 4)) > 1e-4
               or abs(x["E2"] - round(mix(x, 2, 1.0), 4)) > 1e-4]
        stamped = sum(1 for x in pts if x["Ec"] == "appearing")
        held_out = [x for x in pts if x["date"] >= CUT]
        engine_ll = log_loss([x["E1"] for x in held_out], [x["y1"] for x in held_out])
        print(f"SHIPPED engine: {len(pts) - len(off)}/{len(pts)} rows equal MIX to 4 dp at both lines; "
              f"{stamped}/{len(pts)} stamped 'appearing'; TEST line 0.5 log loss {engine_ll:.4f} (MIX measured 0.2309)")
        print("REPRODUCED" if pts and not off and stamped == len(pts) else "NOT REPRODUCED")
        return

    train = [x for x in pts if x["date"] < CUT]
    test = [x for x in pts if x["date"] >= CUT]
    print(f"points {len(pts)} | train {len(train)} test {len(test)} | U ladder == Poisson(expected_assists): "
          f"{ladder_checked - ladder_mismatch}/{ladder_checked}")
    assert ladder_checked and ladder_mismatch == 0, "U is not the engine's published ladder"

    c_fit = min(C_GRID, key=lambda c: log_loss([mix(x, 1, c) for x in train], [x["y1"] for x in train]))
    print(f"FITTED on TRAIN: MIX_c intensity c = {c_fit:.2f}")

    def arms(sel, k):
        return {
            "U": [x[f"U{k}"] for x in sel],
            "DIV": [x[f"D{k}"] for x in sel],
            "MIX": [mix(x, k, 1.0) for x in sel],
            "MIX_c": [mix(x, k, c_fit) for x in sel],
        }

    def report(title, sel):
        out = {}
        for k in (1, 2):
            ys = [x[f"y{k}"] for x in sel]
            real = sum(ys) / max(len(ys), 1)
            cells = []
            for name, ps in arms(sel, k).items():
                ll = log_loss(ps, ys)
                out[(name, k)] = ll
                level = (sum(ps) / max(len(ps), 1)) / max(real, 1e-9)
                extra = f" B {brier(ps, ys):.4f}" if k == 1 else ""
                cells.append(f"{name} {ll:.4f}/{level:.2f}{extra}")
            print(f"  {title:20s} line {k - 0.5:.1f} n={len(sel):5d} real {real:.3f} | LL/level: " + " | ".join(cells))
        return out

    print("\n=== TEST (held out), log loss / level ratio")
    pooled = report("pooled", test)
    wins, leagues = 0, 0
    for lg in crm.LEAGUES:
        sel = [x for x in test if x["lg"] == lg]
        if not sel:
            print(f"  {lg:20s} NO TEST ROWS")
            continue
        leagues += 1
        r = report(lg, sel)
        wins += r[("MIX", 1)] < r[("U", 1)]
    print("\n=== TRAIN, for the level only")
    report("pooled", train)

    h33 = pooled[("MIX", 1)] < pooled[("U", 1)] and wins >= 8 and pooled[("MIX", 1)] < pooled[("DIV", 1)]
    print(f"\nH33 {'NOT FALSIFIED' if h33 else 'FALSIFIED'}: pooled line 0.5 MIX {pooled[('MIX', 1)]:.4f} vs U "
          f"{pooled[('U', 1)]:.4f} vs DIV {pooled[('DIV', 1)]:.4f}; MIX beats U in {wins} of {leagues} leagues with TEST rows (bar 8 of 10)")


if __name__ == "__main__":
    main()
