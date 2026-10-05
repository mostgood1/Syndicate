"""In-season team xG for NHL game lines: prior-season only vs current-season only vs an empirical-Bayes blend.
Lane `nhl-season-inputs-in-season`.

WHY. Production projects every 2026-27 game from FROZEN 2025-26 season files (team_xg_latest.csv built
2026-08-18; nothing rebuilds season inputs in-season). Team xG is the only team-strength input the game
lines read (projection.project_game; Elo's blend weight is 0). This measures what in-season updating buys.

ARMS (production form: projection.project_game -> adapters.build_game_prediction, shipped calibration):
  PRIOR   team xGF/xGA per game from the whole previous regular season (what production does today)
  CURRENT current-season-to-date, strictly before the game (prior only when a team has played 0 games)
  BLEND   (w * prior + n * current) / (w + n), n = the team's games played this season before the game

NO LEAKAGE, BY CONSTRUCTION
  * w is chosen on the 2024-25 season (prior = 2023-24) by moneyline log-loss, then FROZEN;
  * the headline is 2025-26 (prior = 2024-25), scored from opening night;
  * the xG model for a target season is fit ONLY on shots from earlier seasons (2023-24 for the tuning
    season; 2023-24 + 2024-25 for the evaluation season), with the production estimator
    (shot_xg_model.featurize + LogisticRegression(max_iter=2000), as scripts/build_nhl_xg_artifact.py);
  * team aggregation is production's: every Fenwick shot incl. empty-net, summed per game.

DATA (read-only): 2023-24 and 2024-25 play-by-play cached from api-web.nhle.com (--pbp-2023, --pbp-2024);
2025-26 play-by-play from the primary checkout's ingestion_cache; 2025-26 outcomes and closing lines from
backtest_nhl_game_lines' actuals.json / book.json. 2024-25 outcomes are read from its play-by-play.

Usage:
  py -3 scripts/nhl_season_inputs_experiment.py --pbp-2023 C:/tmp/nhllines/pbp_2023 --pbp-2024 C:/tmp/nhllines/pbp_2024
"""
from __future__ import annotations

import argparse
import bisect
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import importlib.util  # noqa: E402

_s = importlib.util.spec_from_file_location("_bgl", REPO / "scripts" / "backtest_nhl_game_lines.py")
BGL = importlib.util.module_from_spec(_s)
_s.loader.exec_module(BGL)


def _leads(pbp: dict) -> List[int]:
    from syndicate.features.nhl.inseason_team_xg import home_lead_before_shots
    return home_lead_before_shots(pbp)


def team_game_xg_adj(season: List[dict], model, weights: Dict[int, float]) -> None:
    """Score-adjusted twin of `team_game_xg` (xg_h_adj / xg_a_adj), production weighting."""
    from syndicate.features.nhl.sim_engine.hockeysim.historical_truth import shot_xg_model as X
    from syndicate.features.nhl.inseason_team_xg import score_weight
    for g in season:
        g["xg_h_adj"] = g["xg_a_adj"] = 0.0
        if not g["shots"]:
            continue
        p = model.predict_proba(X.featurize(g["shots"]))[:, 1]
        ok = len(g["leads"]) == len(g["shots"])
        for i, (s, x) in enumerate(zip(g["shots"], p)):
            home = s.team_id == g["home_id"]
            lead = (g["leads"][i] if home else -g["leads"][i]) if ok else 0
            wx = float(x) * (score_weight(lead, weights) if ok else 1.0)
            g["xg_h_adj" if home else "xg_a_adj"] += wx


def adj_view(season: List[dict]) -> List[dict]:
    return [{**g, "xg_h": g["xg_h_adj"], "xg_a": g["xg_a_adj"]} for g in season]


def load_season(pbp_dir: Path, pattern: str) -> List[dict]:
    """Regular-season games from cached play-by-play: id, date, home/away abbr, shots, final score."""
    from syndicate.features.nhl.sim_engine.hockeysim.historical_truth import shot_xg_model as X
    games = []
    for f in sorted(pbp_dir.glob(pattern)):
        d = BGL._rj(f)
        if not d or int(d.get("gameType") or 0) != 2 or not d.get("plays"):
            continue
        home, away = d.get("homeTeam") or {}, d.get("awayTeam") or {}
        if home.get("score") is None or away.get("score") is None:
            continue
        games.append({"gid": str(d["id"]), "date": str(d.get("gameDate") or "")[:10],
                      "home": str(home.get("abbrev") or "").upper(), "away": str(away.get("abbrev") or "").upper(),
                      "home_id": int(home["id"]), "final_h": int(home["score"]), "final_a": int(away["score"]),
                      "shots": X.parse_play_by_play_shots(d), "leads": _leads(d)})
    games.sort(key=lambda g: (g["date"], g["gid"]))
    return games


def fit_xg(seasons: List[List[dict]]):
    from sklearn.linear_model import LogisticRegression
    from syndicate.features.nhl.sim_engine.hockeysim.historical_truth import shot_xg_model as X
    shots = [s for season in seasons for g in season for s in g["shots"]]
    return LogisticRegression(max_iter=2000).fit(X.featurize(shots), [int(s.is_goal) for s in shots])


def team_game_xg(season: List[dict], model) -> None:
    """Annotate each game with per-team xGF (production aggregation: all Fenwick incl. EN)."""
    from syndicate.features.nhl.sim_engine.hockeysim.historical_truth import shot_xg_model as X
    for g in season:
        if not g["shots"]:
            g["xg_h"] = g["xg_a"] = 0.0
            continue
        p = model.predict_proba(X.featurize(g["shots"]))[:, 1]
        g["xg_h"] = float(sum(x for s, x in zip(g["shots"], p) if s.team_id == g["home_id"]))
        g["xg_a"] = float(sum(x for s, x in zip(g["shots"], p) if s.team_id != g["home_id"]))


def season_rates(season: List[dict]) -> Dict[str, Tuple[float, float]]:
    agg = defaultdict(lambda: [0.0, 0.0, 0])
    for g in season:
        for t, f, a in ((g["home"], g["xg_h"], g["xg_a"]), (g["away"], g["xg_a"], g["xg_h"])):
            agg[t][0] += f; agg[t][1] += a; agg[t][2] += 1
    return {t: (v[0] / v[2], v[1] / v[2]) for t, v in agg.items() if v[2]}


class AsOf:
    def __init__(self, season: List[dict]):
        self.by_team = defaultdict(list)  # team -> [(date, xgf, xga)]
        for g in season:
            self.by_team[g["home"]].append((g["date"], g["xg_h"], g["xg_a"]))
            self.by_team[g["away"]].append((g["date"], g["xg_a"], g["xg_h"]))
        self.dates = {t: [x[0] for x in v] for t, v in self.by_team.items()}
        self.cum = {}
        for t, v in self.by_team.items():
            cf, ca, out = 0.0, 0.0, [(0.0, 0.0)]
            for _d, f, a in v:
                cf += f; ca += a; out.append((cf, ca))
            self.cum[t] = out

    def current(self, team: str, date: str) -> Tuple[int, float, float]:
        n = bisect.bisect_left(self.dates.get(team, []), date)
        if n == 0:
            return 0, 0.0, 0.0
        cf, ca = self.cum[team][n]
        return n, cf / n, ca / n


def rates_for(arm: str, w: Optional[float], team: str, date: str, prior, asof: AsOf):
    pf, pa = prior.get(team, (None, None))
    n, cf, ca = asof.current(team, date)
    if pf is None:
        return (cf, ca) if n else (None, None)
    if arm == "PRIOR" or n == 0:
        return pf, pa
    if arm == "CURRENT":
        return cf, ca
    return (w * pf + n * cf) / (w + n), (w * pa + n * ca) / (w + n)


def predict(game: dict, arm: str, w, prior, asof, total_line=None):
    from syndicate.features.nhl.sim_engine.hockeysim import adapters as A
    from syndicate.features.nhl.sim_engine.hockeysim.contracts import HockeyGameFeatures, HockeyMarketLines
    from syndicate.features.nhl.sim_engine.hockeysim.contracts import HockeyTeamFeatures as HTF
    from syndicate.features.nhl.sim_engine.hockeysim.projection import project_game
    hf, ha = rates_for(arm, w, game["home"], game["date"], prior, asof)
    af, aa = rates_for(arm, w, game["away"], game["date"], prior, asof)
    pr = project_game(HTF(name=game["home"], xgf_per_60=hf, xga_per_60=ha), HTF(name=game["away"], xgf_per_60=af, xga_per_60=aa))
    f = HockeyGameFeatures(game_pk=game["gid"], date=game["date"],
                           home=HTF(name=game["home"], period_goal_lambdas=tuple(pr.period_home_lambdas)),
                           away=HTF(name=game["away"], period_goal_lambdas=tuple(pr.period_away_lambdas)),
                           market=HockeyMarketLines(total_line=total_line))
    p = A.build_game_prediction(f, calibration=A.NHL_GAME_MARKET_CALIBRATION, n_sims=8000)
    return {"ml": p.p_home_ml, "tot": p.model_total, "ov": p.p_over}


def scoreadj_eval(a, s23, s24, s25, out: Path) -> int:
    weights = {int(k): float(v) for k, v in json.loads(Path(a.scoreadj_weights).read_text(encoding="utf-8"))["weights"].items()}
    m_eval = fit_xg([s23, s24])
    team_game_xg(s24, m_eval); team_game_xg(s25, m_eval)
    team_game_xg_adj(s24, m_eval, weights); team_game_xg_adj(s25, m_eval, weights)
    prior, asof = season_rates(s24), AsOf(s25)
    prior_adj, asof_adj = season_rates(adj_view(s24)), AsOf(adj_view(s25))
    act = json.loads((out / "actuals.json").read_text(encoding="utf-8"))
    book = json.loads((out / "book.json").read_text(encoding="utf-8"))
    yml = lambda x: 1 if x["r"]["final_h"] > x["r"]["final_a"] else 0
    tot = lambda x: x["r"]["final_h"] + x["r"]["final_a"]
    res = {}
    for arm_name in ("regular", "playoff"):
        rows = []
        for g in s25:
            r = act.get(g["gid"])
            if not r or r["arm"] != arm_name:
                continue
            b = book.get(g["gid"], {})
            rows.append({"date": g["date"], "r": r, "b": b,
                         "BLEND": predict(g, "BLEND", 10.0, prior, asof, b.get("total_line")),
                         "BLEND_ADJ": predict(g, "BLEND", 10.0, prior_adj, asof_adj, b.get("total_line"))})
        if not rows:
            print(f"== {arm_name}: no rows (play-by-play for this arm not loaded)")
            continue
        d = BGL._boot_diff([(x["date"], BGL._brier(x["BLEND_ADJ"]["ml"], yml(x)) - BGL._brier(x["BLEND"]["ml"], yml(x))) for x in rows])
        dl = BGL._boot_diff([(x["date"], BGL._ll(x["BLEND_ADJ"]["ml"], yml(x)) - BGL._ll(x["BLEND"]["ml"], yml(x))) for x in rows])
        dm = BGL._boot_diff([(x["date"], abs(x["BLEND_ADJ"]["tot"] - tot(x)) - abs(x["BLEND"]["tot"] - tot(x))) for x in rows])
        mean_shift = statistics.fmean(abs(x["BLEND_ADJ"]["ml"] - x["BLEND"]["ml"]) for x in rows)
        print(f"== {arm_name}: n={len(rows)} | mean |dp_home_ml| {mean_shift:.5f}")
        print(f"   BLEND_ADJ - BLEND: ML dBrier {d[0]:+.5f} [{d[1]:+.5f},{d[2]:+.5f}] | ML dLL {dl[0]:+.5f} [{dl[1]:+.5f},{dl[2]:+.5f}] "
              f"| total dMAE {dm[0]:+.4f} [{dm[1]:+.4f},{dm[2]:+.4f}]", flush=True)
        res[arm_name] = {"n": len(rows), "d_brier": d, "d_ll": dl, "d_total_mae": dm, "mean_abs_dp": mean_shift}
    (out / "scoreadj_production_form.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    print("DONE", flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pbp-2023", required=True)
    ap.add_argument("--pbp-2024", required=True)
    ap.add_argument("--out", default="C:/tmp/nhllines")
    ap.add_argument("--scoreadj-weights", default=None,
                    help="JSON {lead: weight} fit on seasons BEFORE 2025-26: run ONLY the production-form score-adjusted "
                         "comparison BLEND_ADJ vs BLEND at w=10 (the shipped weight) on 2025-26")
    a = ap.parse_args()
    out = Path(a.out)
    src = BGL._main_worktree() / "data" / "nhl_source" / "data" / "ingestion_cache"
    s23 = load_season(Path(a.pbp_2023), "*.json")
    s24 = load_season(Path(a.pbp_2024), "*.json")
    s25 = load_season(src, "playbyplay_2025*.json")
    print(f"seasons: 2023-24 {len(s23)} games, 2024-25 {len(s24)}, 2025-26 {len(s25)}", flush=True)
    if a.scoreadj_weights:
        return scoreadj_eval(a, s23, s24, s25, Path(a.out))

    # --- tuning stage: target 2024-25, prior 2023-24, xG model fit on 2023-24 only
    m_tune = fit_xg([s23])
    team_game_xg(s23, m_tune); team_game_xg(s24, m_tune)
    prior24, asof24 = season_rates(s23), AsOf(s24)
    hw = lambda g: 1 if g["final_h"] > g["final_a"] else 0
    tune = {}
    for w in (None, 0.0, 5.0, 10.0, 20.0, 40.0, 80.0):
        arm = "PRIOR" if w is None else ("CURRENT" if w == 0.0 else "BLEND")
        P = [(g, predict(g, arm, w, prior24, asof24)) for g in s24]
        ll = statistics.fmean(BGL._ll(p["ml"], hw(g)) for g, p in P)
        mae = statistics.fmean(abs(p["tot"] - (g["final_h"] + g["final_a"])) for g, p in P)
        tune[str(w)] = {"arm": arm, "ml_logloss": ll, "total_mae": mae}
        print(f"tune 2024-25 w={w} ({arm}): ML log-loss {ll:.5f}  total MAE {mae:.4f}  n={len(P)}", flush=True)
    blends = {k: v for k, v in tune.items() if v["arm"] == "BLEND"}
    w_star = float(min(blends, key=lambda k: blends[k]["ml_logloss"]))
    print(f"CHOSEN w = {w_star} (2024-25 ML log-loss among BLEND arms; frozen)", flush=True)

    # --- evaluation: target 2025-26, prior 2024-25, xG model fit on 2023-24 + 2024-25 only
    m_eval = fit_xg([s23, s24])
    team_game_xg(s24, m_eval); team_game_xg(s25, m_eval)
    prior25, asof25 = season_rates(s24), AsOf(s25)
    act = json.loads((out / "actuals.json").read_text(encoding="utf-8"))
    book = json.loads((out / "book.json").read_text(encoding="utf-8"))
    rows = []
    for g in s25:
        r = act.get(g["gid"])
        if not r or r["arm"] != "regular":
            continue
        b = book.get(g["gid"], {})
        n_h = asof25.current(g["home"], g["date"])[0]; n_a = asof25.current(g["away"], g["date"])[0]
        rec = {"date": g["date"], "r": r, "b": b, "n": min(n_h, n_a)}
        for arm, w in (("PRIOR", None), ("CURRENT", 0.0), ("BLEND", w_star)):
            rec[arm] = predict(g, arm, w, prior25, asof25, b.get("total_line"))
        rows.append(rec)
    yml = lambda x: 1 if x["r"]["final_h"] > x["r"]["final_a"] else 0
    tot = lambda x: x["r"]["final_h"] + x["r"]["final_a"]
    for name, R in (("2025-26 ALL from opening night", rows),
                    ("games 1-20 (min team games < 20)", [x for x in rows if x["n"] < 20]),
                    ("games 20-40", [x for x in rows if 20 <= x["n"] < 40]),
                    ("games 40+", [x for x in rows if x["n"] >= 40])):
        if not R:
            continue
        print(f"== {name}: n={len(R)}")
        for a_, b_ in (("BLEND", "PRIOR"), ("BLEND", "CURRENT"), ("CURRENT", "PRIOR")):
            d = BGL._boot_diff([(x["date"], BGL._brier(x[a_]["ml"], yml(x)) - BGL._brier(x[b_]["ml"], yml(x))) for x in R])
            dm = BGL._boot_diff([(x["date"], abs(x[a_]["tot"] - tot(x)) - abs(x[b_]["tot"] - tot(x))) for x in R])
            print(f"   {a_} - {b_}: ML dBrier {d[0]:+.4f} [{d[1]:+.4f},{d[2]:+.4f}] | total dMAE {dm[0]:+.4f} [{dm[1]:+.4f},{dm[2]:+.4f}]")
        ML = [x for x in R if x["b"].get("ml_home") is not None]
        for arm in ("PRIOR", "CURRENT", "BLEND"):
            vb = BGL._boot_diff([(x["date"], BGL._brier(x[arm]["ml"], yml(x)) - BGL._brier(x["b"]["ml_home"], yml(x))) for x in ML])
            print(f"   {arm:<7} ML vs book {vb[0]:+.4f} [{vb[1]:+.4f},{vb[2]:+.4f}] (n={len(ML)})", flush=True)
    (out / "season_inputs_experiment.json").write_text(json.dumps({"tune": tune, "w_star": w_star}, indent=1), encoding="utf-8")
    print("DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
