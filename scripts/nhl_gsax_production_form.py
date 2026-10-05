"""H22: goalie GSAx for game-line totals, measured in PRODUCTION FORM before shipping (lane `nhl-game-lines-model`).

Both arms are exactly what production computes, except the GSAx factor:
  * team strength: in-season BLEND (W=10) of score-adjusted team xG (`inseason_team_xg` machinery), prior 2024-25;
  * projection.project_game -> adapters.build_game_prediction with the shipped calibration, at the book's total;
  * starter: an as-of rotation pick standing in for the collector's projection (most starts in the team's last 10
    games; on the 2nd night of a back-to-back, the other goalie if the top one started the night before), with the
    Daily Faceoff archive's CONFIRMED starter overlaid when posted before the scheduled start and the name maps to a
    goalie who has appeared for the team this season (`confirmed_goalies.name_key`);
  * GSAx (arm B only): `goalie_gsax.gsax_factor` (k=160, w=0.25), this season's shots strictly before the date, prior
    2024-25, league ratio as-of. The home goalie scales the away lambdas and vice versa.
Honesty: xG model and score weights fit on 2023-24 + 2024-25 only; (k, w) were tuned on 2025-26 pre-January in V8,
so the OOS window (>= 2026-01-01) is the headline. Paired, date-clustered bootstrap.

Usage: py -3 scripts/nhl_gsax_production_form.py --pbp-2023 C:/tmp/nhllines/pbp_2023 --pbp-2024 C:/tmp/nhllines/pbp_2024
"""
from __future__ import annotations

import argparse
import bisect
import importlib.util
import json
import pickle
import statistics
import sys
from collections import Counter, defaultdict
from datetime import date as _date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


E = _load("nhl_season_inputs_experiment")
BGL = E.BGL


def attach_goalie_shots(season: List[dict], pbp_dir: Path, pattern: str, model) -> None:
    """Per game: [(defending abbr, goalie id, xG, goal)] for non-empty-net unblocked shots on a goalie."""
    from syndicate.features.nhl import goalie_gsax as GG
    from syndicate.features.nhl.sim_engine.hockeysim.historical_truth import shot_xg_model as X
    files = {}
    for f in pbp_dir.glob(pattern):
        files[f.stem.replace("playbyplay_", "")] = f
    for g in season:
        g["gshots"] = []
        f = files.get(g["gid"])
        pbp = BGL._rj(f) if f else None
        if not pbp:
            continue
        gids = GG.goalies_in_order(pbp)
        shots = g["shots"]
        if len(gids) != len(shots) or not shots:
            continue
        xs = model.predict_proba(X.featurize(shots))[:, 1]
        for s, gk, x in zip(shots, gids, xs):
            if gk is None or s.is_empty_net:
                continue
            defending = g["away"] if s.team_id == g["home_id"] else g["home"]
            g["gshots"].append((defending, int(gk), float(x), int(s.is_goal)))


class Gsax:
    def __init__(self, season: List[dict], prior_season: List[dict]):
        self.rows = sorted((g["date"], gk, x, gl) for g in season for (_d, gk, x, gl) in g["gshots"])
        self.dates = [r[0] for r in self.rows]
        self.prior: Dict[int, Tuple[float, float]] = defaultdict(lambda: (0.0, 0.0))
        acc = defaultdict(lambda: [0.0, 0.0])
        for g in prior_season:
            for (_d, gk, x, gl) in g["gshots"]:
                acc[gk][0] += x; acc[gk][1] += gl
        self.prior = {k: (v[0], v[1]) for k, v in acc.items()}
        self._cache = {}

    def asof(self, date: str):
        if date not in self._cache:
            i = bisect.bisect_left(self.dates, date)
            t = defaultdict(lambda: [0.0, 0.0])
            for (_d, gk, x, gl) in self.rows[:i]:
                t[gk][0] += x; t[gk][1] += gl
            xg = sum(v[0] for v in t.values()); ga = sum(v[1] for v in t.values())
            self._cache[date] = ({k: (v[0], v[1]) for k, v in t.items()}, (ga / xg) if xg else 0.0)
        return self._cache[date]


def starter_history(acts: Dict[str, dict]) -> Tuple[Dict, Dict, Dict]:
    """team -> [(date, starter pid)] (2025-26 regular season), pid -> boxscore name, (gid, team) -> actual pid."""
    hist, names, actual = defaultdict(list), {}, {}
    for gid, a in acts.items():
        if a.get("season") != 20252026 or a.get("gtype") != 2:
            continue
        for p in a["players"]:
            if p["pos"] == "G":
                names[p["pid"]] = p["name"]
                if p.get("starter"):
                    hist[p["team"]].append((a["date"], p["pid"]))
                    actual[(gid, p["team"])] = p["pid"]
    for t in hist:
        hist[t].sort()
    return hist, names, actual


def rotation_pick(hist, team: str, date: str) -> Optional[int]:
    prev = [x for x in hist.get(team, []) if x[0] < date]
    if not prev:
        return None
    last10 = prev[-10:]
    c = Counter(p for _d, p in last10)
    order = sorted(c, key=lambda p: (-c[p], -max(i for i, (_d, q) in enumerate(last10) if q == p)))
    top = order[0]
    yday = (_date.fromisoformat(date) - timedelta(days=1)).isoformat()
    if prev[-1][0] == yday and prev[-1][1] == top and len(order) > 1:
        return order[1]
    return top


def dfo_confirmed(dfo_dir: Path, date: str) -> Dict[str, str]:
    from syndicate.features.nhl import confirmed_goalies as C
    f = dfo_dir / f"{date}.json"
    if not f.exists():
        return {}
    games = json.loads(f.read_text(encoding="utf-8")).get("games") or []
    conf, _why = C.confirmed_by_team(games, datetime(2100, 1, 1, tzinfo=timezone.utc))
    return conf


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pbp-2023", required=True)
    ap.add_argument("--pbp-2024", required=True)
    ap.add_argument("--out", default="C:/tmp/nhllines")
    ap.add_argument("--records", default="C:/tmp/nhlprops/bt_lqp_0.5/records.pkl")
    ap.add_argument("--scoreadj-weights", default="C:/tmp/nhllines/scoreadj_w_eval.json")
    ap.add_argument("--n-sims", type=int, default=8000)
    a = ap.parse_args()
    out = Path(a.out)
    from syndicate.features.nhl import confirmed_goalies as C
    from syndicate.features.nhl import goalie_gsax as GG
    from syndicate.features.nhl.sim_engine.hockeysim import adapters as A
    from syndicate.features.nhl.sim_engine.hockeysim.contracts import HockeyGameFeatures, HockeyMarketLines
    from syndicate.features.nhl.sim_engine.hockeysim.contracts import HockeyTeamFeatures as HTF
    from syndicate.features.nhl.sim_engine.hockeysim.projection import project_game

    src = BGL._main_worktree() / "data" / "nhl_source" / "data" / "ingestion_cache"
    s23 = E.load_season(Path(a.pbp_2023), "*.json")
    s24 = E.load_season(Path(a.pbp_2024), "*.json")
    s25 = E.load_season(src, "playbyplay_2025*.json")
    weights = {int(k): float(v) for k, v in json.loads(Path(a.scoreadj_weights).read_text(encoding="utf-8"))["weights"].items()}
    m = E.fit_xg([s23, s24])
    E.team_game_xg(s24, m); E.team_game_xg(s25, m)
    E.team_game_xg_adj(s24, m, weights); E.team_game_xg_adj(s25, m, weights)
    prior_adj, asof_adj = E.season_rates(E.adj_view(s24)), E.AsOf(E.adj_view(s25))
    attach_goalie_shots(s24, Path(a.pbp_2024), "*.json", m)
    attach_goalie_shots(s25, src, "playbyplay_2025*.json", m)
    gs = Gsax(s25, s24)
    acts = pickle.load(open(a.records, "rb"))["actuals"]
    hist, names, actual = starter_history(acts)
    act = json.loads((out / "actuals.json").read_text(encoding="utf-8"))
    book = json.loads((out / "book.json").read_text(encoding="utf-8"))
    print(f"seasons {len(s23)}/{len(s24)}/{len(s25)}; goalie shots 2025-26 {len(gs.rows)}, prior goalies {len(gs.prior)}", flush=True)

    rows, miss = [], Counter()
    st_acc = Counter()
    for g in s25:
        r = act.get(g["gid"])
        if not r or r["arm"] != "regular":
            continue
        b = book.get(g["gid"], {})
        tl = b.get("total_line")
        conf = dfo_confirmed(out / "dfo", g["date"])
        pick = {}
        for ab in (g["home"], g["away"]):
            p = rotation_pick(hist, ab, g["date"])
            if ab in conf:
                pool = {q for d, q in hist.get(ab, []) if d < g["date"]}
                hits = [q for q in pool if C.name_key(names.get(q)) == C.name_key(conf[ab])]
                if len(hits) == 1:
                    p = hits[0]; st_acc["dfo_used"] += 1
            pick[ab] = p
            if actual.get((g["gid"], ab)) is not None:
                st_acc["n"] += 1; st_acc["right"] += int(p == actual[(g["gid"], ab)])
        table, lr = gs.asof(g["date"])
        fh = GG.gsax_factor(pick[g["home"]], table, lr, prior=gs.prior) or 1.0   # home goalie
        fa = GG.gsax_factor(pick[g["away"]], table, lr, prior=gs.prior) or 1.0
        hf, ha = E.rates_for("BLEND", 10.0, g["home"], g["date"], prior_adj, asof_adj)
        af, aa = E.rates_for("BLEND", 10.0, g["away"], g["date"], prior_adj, asof_adj)
        pr = project_game(HTF(name=g["home"], xgf_per_60=hf, xga_per_60=ha), HTF(name=g["away"], xgf_per_60=af, xga_per_60=aa))
        res = {}
        for arm, (mh, ma) in (("BASE", (1.0, 1.0)), ("GSAX", (fa, fh))):
            f = HockeyGameFeatures(game_pk=g["gid"], date=g["date"],
                                   home=HTF(name=g["home"], period_goal_lambdas=tuple(x * mh for x in pr.period_home_lambdas)),
                                   away=HTF(name=g["away"], period_goal_lambdas=tuple(x * ma for x in pr.period_away_lambdas)),
                                   market=HockeyMarketLines(total_line=tl))
            p = A.build_game_prediction(f, calibration=A.NHL_GAME_MARKET_CALIBRATION, n_sims=a.n_sims)
            res[arm] = {"ml": p.p_home_ml, "tot": p.model_total, "ov": p.p_over, "push": getattr(p, "p_push", None)}
        rows.append({"date": g["date"], "r": r, "tl": tl, "fh": fh, "fa": fa, **res})
    print(f"games {len(rows)}; starter accuracy {st_acc['right']}/{st_acc['n']} = {st_acc['right'] / max(1, st_acc['n']):.3f} "
          f"(dfo used {st_acc['dfo_used']}); factor != 1 on {sum(1 for x in rows if x['fh'] != 1.0 or x['fa'] != 1.0)} games; "
          f"factor range {min(min(x['fh'], x['fa']) for x in rows):.3f}..{max(max(x['fh'], x['fa']) for x in rows):.3f}", flush=True)
    yml = lambda x: 1 if x["r"]["final_h"] > x["r"]["final_a"] else 0
    tot = lambda x: x["r"]["final_h"] + x["r"]["final_a"]
    report = {}
    for wname, R in (("ALL 2025-26 regular", rows), ("OOS >= 2026-01-01", [x for x in rows if x["date"] >= "2026-01-01"])):
        OV = [x for x in R if x["tl"] is not None and not (float(x["tl"]).is_integer() and tot(x) == x["tl"])
              and x["BASE"]["ov"] is not None and x["GSAX"]["ov"] is not None]
        yov = lambda x: 1 if tot(x) > x["tl"] else 0
        d_ov = BGL._boot_diff([(x["date"], BGL._brier(x["GSAX"]["ov"], yov(x)) - BGL._brier(x["BASE"]["ov"], yov(x))) for x in OV])
        d_ml = BGL._boot_diff([(x["date"], BGL._brier(x["GSAX"]["ml"], yml(x)) - BGL._brier(x["BASE"]["ml"], yml(x))) for x in R])
        d_mae = BGL._boot_diff([(x["date"], abs(x["GSAX"]["tot"] - tot(x)) - abs(x["BASE"]["tot"] - tot(x))) for x in R])
        bk = [x for x in OV if (book.get(x["r"].get("gid", ""), {}) or {}).get("p_over") is not None]
        print(f"== {wname}: n={len(R)} (OVER@close n={len(OV)})")
        print(f"   GSAX - BASE: OVER@close dBrier {d_ov[0]:+.5f} [{d_ov[1]:+.5f},{d_ov[2]:+.5f}] | ML dBrier {d_ml[0]:+.5f} "
              f"[{d_ml[1]:+.5f},{d_ml[2]:+.5f}] | total dMAE {d_mae[0]:+.4f} [{d_mae[1]:+.4f},{d_mae[2]:+.4f}]", flush=True)
        report[wname] = {"n": len(R), "n_over": len(OV), "d_over": d_ov, "d_ml": d_ml, "d_mae": d_mae}
    (out / "gsax_production_form.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print("DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
