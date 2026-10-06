"""Measure hockeysim's simulated power-play TIME per team-game straight from the engine (lane nhl-pp-time).

Runs the props engine path (`player_props.build_prop_projections`'s own inputs: `build_slate_features`
over an as-of root -> `runtime.run_hockeysim_game`) and reads, per simulated game, each team's PP
seconds (its starting goalie's `shift` events with strength "PP"; the goalie is on ice every
segment), PP goals, all goals and shots. Real side: the official NHL stats
`team/powerplaytime?isGame=true` rows (`timeOnIcePp`, `powerPlayGoalsFor`) saved by
`--official`, joined on (date, team full name).

The calibration profile is whatever `SYNDICATE_CALIBRATION_PROFILE_PATH_NHL` resolves to, so the
same script measures the production engine and a candidate (`pp_time_model` etc.).

    py -3 scripts/nhl_pp_time_engine_measure.py --roots C:/tmp/nhlprops/bt_scratch/roots \
        --official <dir with pptime_20252026_2.json> --dates 45 --sims 40 --seed-dates 11 --out x.json
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from syndicate.features.nhl.sim_engine.hockeysim.adapters import game_seed  # noqa: E402
from syndicate.features.nhl.sim_engine.hockeysim.calibration_profile import (  # noqa: E402
    NHL_CALIBRATION_PROFILE_METADATA,
    build_nhl_sim_config,
)
from syndicate.features.nhl.sim_engine.hockeysim.features.loaders import build_slate_features  # noqa: E402
from syndicate.features.nhl.sim_engine.hockeysim.player_props import (  # noqa: E402
    _special_teams_cal,
    _starter_goalie_id,
    _team_rates,
)
from syndicate.features.nhl.sim_engine.hockeysim.models import RateModels  # noqa: E402
from syndicate.features.nhl.sim_engine.hockeysim.runtime import run_hockeysim_game  # noqa: E402


def measure_game(game, n_sims: int) -> dict:
    rates = RateModels(home=_team_rates(game.home), away=_team_rates(game.away), player_rates={})
    roster_home = [p.roster_row() for p in game.home_players]
    roster_away = [p.roster_row() for p in game.away_players]
    lineup_home = [p.lineup_row() for p in game.home_players]
    lineup_away = [p.lineup_row() for p in game.away_players]
    st_home = dict(game.home.special_teams) or None
    st_away = dict(game.away.special_teams) or None
    cal = _special_teams_cal(build_nhl_sim_config(profile=None))
    # every dressed goalie: the engine emits shifts for ITS starter (max toi_proj, engine.py `_starter_goalie`),
    # which can differ from the props layer's flagged starter; only one goalie per team is ever on ice.
    goalies = {game.home.name: {int(p.player_id) for p in game.home_players if str(p.position).upper() == "G"},
               game.away.name: {int(p.player_id) for p in game.away_players if str(p.position).upper() == "G"}}
    acc = {t: collections.Counter() for t in (game.home.name, game.away.name)}
    per_player = collections.defaultdict(collections.Counter)
    seed0 = game_seed(game.date, game.game_pk)
    for i in range(n_sims):
        _gs, events = run_hockeysim_game(
            game.home.name, game.away.name, roster_home, roster_away, rates,
            lineup_home=lineup_home, lineup_away=lineup_away,
            st_home=st_home, st_away=st_away, special_teams_cal=cal, profile=None, seed=seed0 + i,
        )
        for e in events:
            team = e.team
            if team not in acc:
                continue
            st = str((e.meta or {}).get("strength", "EV")).upper()
            if e.kind == "shift" and e.player_id is not None and int(e.player_id) not in goalies[team]:
                if st in ("PP", "PK"):
                    per_player[(team, int(e.player_id))][st] += float((e.meta or {}).get("dur", 0.0))
            if e.kind == "shift" and e.player_id is not None and int(e.player_id) in goalies[team]:
                dur = float((e.meta or {}).get("dur", 0.0))
                acc[team]["sec"] += dur
                if st == "PP":
                    acc[team]["pp_sec"] += dur
                    if int(e.period) >= 4:
                        acc[team]["pp_sec_ot"] += dur
                elif st == "PK":
                    acc[team]["pk_sec"] += dur
            elif e.kind == "goal":
                acc[team]["goals"] += 1
                if st == "PP":
                    acc[team]["pp_goals"] += 1
                elif st == "PK":
                    acc[team]["sh_goals"] += 1
            elif e.kind == "shot":
                acc[team]["shots"] += 1
                if st == "PP":
                    acc[team]["pp_shots"] += 1
                elif st == "PK":
                    acc[team]["sh_shots"] += 1
    out = {}
    for t, c in acc.items():
        out[t] = {k: v / n_sims for k, v in c.items()}
    units = {(side.name, int(p.player_id)): (p.pp_unit, getattr(p, "pk_unit", None), p.position)
             for side, players in ((game.home, game.home_players), (game.away, game.away_players)) for p in players}
    out["_players"] = [dict(team=t, pid=pid, pp_unit=units.get((t, pid), (None,) * 3)[0], pk_unit=units.get((t, pid), (None,) * 3)[1],
                            pos=units.get((t, pid), (None,) * 3)[2], pp_sec=c["PP"] / n_sims, pk_sec=c["PK"] / n_sims)
                       for (t, pid), c in per_player.items()]
    return out


def real_team_counts(pbp_dir: str, game_id: str) -> dict:
    """{'home'|'away': {goals, sog, sh_goals}} from a cached play-by-play, regulation + OT (no shootout)."""
    f = os.path.join(pbp_dir, f"pbp_{game_id}.json")
    if not os.path.exists(f):
        return {}
    p = json.load(open(f, encoding="utf-8"))
    side_of = {int(p["homeTeam"]["id"]): "home", int(p["awayTeam"]["id"]): "away"}
    out = {s: collections.Counter() for s in ("home", "away")}
    for pl in p.get("plays") or []:
        pd = pl.get("periodDescriptor") or {}
        if str(pd.get("periodType") or "REG") == "SO":
            continue
        k = pl.get("typeDescKey")
        if k not in ("goal", "shot-on-goal"):
            continue
        side = side_of.get(int((pl.get("details") or {}).get("eventOwnerTeamId") or 0))
        if side is None:
            continue
        out[side]["sog"] += 1
        sc = str(pl.get("situationCode") or "1551")
        a_sk, h_sk = (int(sc[1]), int(sc[2])) if len(sc) == 4 and sc.isdigit() else (5, 5)
        own, opp = (h_sk, a_sk) if side == "home" else (a_sk, h_sk)
        pp = own > opp and opp < 5
        sh = own < opp and own < 5
        if pp:
            out[side]["pp_sog"] += 1
        if sh:
            out[side]["sh_sog"] += 1
        if k == "goal":
            out[side]["goals"] += 1
            if sh:
                out[side]["sh_goals"] += 1
    return out


def _boot(rows, num, den=None, B=1000, seed=7):
    """Game-clustered bootstrap of sum(num)/sum(den) (den None -> mean per row)."""
    groups = collections.defaultdict(list)
    for r in rows:
        groups[r["gid"]].append(r)
    keys = list(groups)
    rng = random.Random(seed)
    def stat(rs):
        a = sum(num(r) for r in rs)
        b = sum(den(r) for r in rs) if den else len(rs)
        return a / max(1e-9, b)
    point = stat(rows)
    bs = sorted(stat([r for _ in keys for r in groups[keys[rng.randrange(len(keys))]]]) for _ in range(B))
    return round(point, 4), round(bs[int(0.025 * B)], 4), round(bs[int(0.975 * B) - 1], 4)


def rescore(path: str, official_dir: str, pbp_dir: str, season: str = "20252026") -> dict:
    """Re-summarise a saved run against official PP data + play-by-play team totals, with game-clustered CIs."""
    d = json.load(open(path, encoding="utf-8"))
    off = json.load(open(os.path.join(official_dir, f"pptime_{season}_2.json"), encoding="utf-8"))["data"]
    idx = {(r["gameDate"], r["teamFullName"]): r for r in off}
    rows = []
    cache = {}
    for r in d["rows"]:
        o = idx.get((r["date"], r["team"]))
        if not o:
            continue
        gid = str(o["gameId"])
        if gid not in cache:
            cache[gid] = real_team_counts(pbp_dir, gid)
        side = "home" if o.get("homeRoad") == "H" else "away"
        rc = cache[gid].get(side)
        if not rc:
            continue
        rows.append(dict(r, gid=gid, real_pp_sec=float(o["timeOnIcePp"]), real_pp_goals=int(o["powerPlayGoalsFor"]),
                         real_goals=rc["goals"], real_sog=rc["sog"], real_sh_goals=rc["sh_goals"],
                         real_pp_sog=rc["pp_sog"], real_sh_sog=rc["sh_sog"]))
    g = lambda k: (lambda r: float(r.get(k) or 0.0))
    out = dict(team_games=len(rows), games=len({r["gid"] for r in rows}), unmatched=len(d["rows"]) - len(rows),
               profile=d["summary"].get("profile"))
    for lab, sk, rk, scale in (("pp_min", "sim_pp_sec", "real_pp_sec", 60.0), ("pp_goals", "sim_pp_goals", "real_pp_goals", 1.0),
                               ("goals", "sim_goals", "real_goals", 1.0), ("sog", "sim_shots", "real_sog", 1.0),
                               ("sh_goals", "sim_sh_goals", "real_sh_goals", 1.0), ("pp_sog", "sim_pp_shots", "real_pp_sog", 1.0),
                               ("sh_sog", "sim_sh_shots", "real_sh_sog", 1.0)):
        out[lab] = dict(sim=_boot(rows, lambda r, k=sk, s=scale: g(k)(r) / s), real=_boot(rows, lambda r, k=rk, s=scale: g(k)(r) / s),
                        ratio=_boot(rows, g(sk), g(rk)) if scale == 1.0 else _boot(rows, g(sk), g(rk)))
    out["sim_pp_ot_min"] = round(sum(g("sim_pp_sec_ot")(r) for r in rows) / max(1, len(rows)) / 60, 4)
    out["sim_pp_shots"] = round(sum(g("sim_pp_shots")(r) for r in rows) / max(1, len(rows)), 4)
    out["sim_sh_shots"] = round(sum(g("sim_sh_shots")(r) for r in rows) / max(1, len(rows)), 4)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rescore", nargs="*", default=None, help="saved run JSONs to re-summarise (needs --pbp)")
    ap.add_argument("--pbp", default="")
    ap.add_argument("--roots", default="")
    ap.add_argument("--official", required=True)
    ap.add_argument("--season", default="20252026")
    ap.add_argument("--dates", type=int, default=45)
    ap.add_argument("--seed-dates", type=int, default=11)
    ap.add_argument("--sims", type=int, default=40)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    if args.rescore:
        res = {Path(p).stem: rescore(p, args.official, args.pbp, args.season) for p in args.rescore}
        print(json.dumps(res, indent=1))
        Path(args.out).write_text(json.dumps(res, indent=1), encoding="utf-8")
        return 0

    off = json.load(open(os.path.join(args.official, f"pptime_{args.season}_2.json"), encoding="utf-8"))["data"]
    real = {(r["gameDate"], r["teamFullName"]): r for r in off}
    roots = sorted(glob.glob(os.path.join(args.roots, "2025-1[12]-*")) + glob.glob(os.path.join(args.roots, "2026-0[1-4]-*")))
    random.Random(args.seed_dates).shuffle(roots)
    roots = sorted(roots[: args.dates])
    rows = []
    players = []
    for r in roots:
        d = Path(r).name
        for g in build_slate_features(d, root=Path(r)):
            m = measure_game(g, args.sims)
            for pr in m.pop("_players"):
                players.append(dict(pr, date=d))
            for side, opp in ((g.home, g.away), (g.away, g.home)):
                rr = real.get((d, side.name))
                rows.append(dict(date=d, team=side.name, opp=opp.name, matched=rr is not None,
                                 real_pp_sec=(float(rr["timeOnIcePp"]) if rr else None),
                                 real_pp_goals=(int(rr["powerPlayGoalsFor"]) if rr else None),
                                 real_pp_opp=(int(rr["ppOpportunities"]) if rr else None),
                                 opp_committed=float((opp.special_teams or {}).get("committed_per_game", 3.0)),
                                 **{f"sim_{k}": v for k, v in m[side.name].items()}))
        print(d, len(rows), flush=True)
    x = [r for r in rows if r["matched"]]
    n = len(x)
    def mean(k):
        return sum(float(r.get(k) or 0.0) for r in x) / max(1, n)
    summary = dict(profile=str(NHL_CALIBRATION_PROFILE_METADATA), team_games=n, unmatched=len(rows) - n, dates=len(roots), sims=args.sims,
                   sim_pp_min=mean("sim_pp_sec") / 60, real_pp_min=mean("real_pp_sec") / 60,
                   sim_pp_goals=mean("sim_pp_goals"), real_pp_goals=mean("real_pp_goals"),
                   sim_pk_min=mean("sim_pk_sec") / 60, sim_pp_ot_min=mean("sim_pp_sec_ot") / 60,
                   sim_goals=mean("sim_goals"), sim_shots=mean("sim_shots"), sim_pp_shots=mean("sim_pp_shots"),
                   sim_sh_goals=mean("sim_sh_goals"), sim_sh_shots=mean("sim_sh_shots"),
                   opp_committed_x2=2 * mean("opp_committed"))
    summary["pp_time_ratio"] = summary["sim_pp_min"] / max(1e-9, summary["real_pp_min"])
    summary["pp_goal_ratio"] = summary["sim_pp_goals"] / max(1e-9, summary["real_pp_goals"])
    print(json.dumps(summary, indent=1))
    Path(args.out).write_text(json.dumps(dict(summary=summary, rows=rows, players=players), indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
