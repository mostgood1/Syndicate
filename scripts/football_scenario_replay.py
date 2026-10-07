"""Mid-drive LIVE replay: production vs the re-fit candidate, resumed from real snaps.

Lane `football-scenario-calibration`. Pre-registered ("LIVE mid-drive replay gate") in
`.syndicate/findings_2026-10-06_football_scenario_calibration.md` before this file.

The existing live backtests resume only at quarter ends with the clock at 0:00. This
resumes from REAL mid-drive states -- down, distance, field position, possession,
clock and the score at the start of the snap -- through PRODUCTION'S OWN live
functions (`nfl/live_resim.resim_live_game`, `ncaaf/live_resim.resim_live_game`),
which both take a `profile`. Ratings are what the live tick feeds: NFL raw
`team_rating` as-of the week; NCAAF the raw as-of blend, shrunk by the function's own
live level shrink.

Two departures from the live tick, identical in both arms: NFL's publish guard
(`UNINFORMATIVE_BAND`) is disabled -- it refuses close states, which would drop them
from a grade of the ENGINE -- and `rating_sd = 0`.

    py -3 scripts/football_scenario_replay.py run --sport nfl --season 2024 --every 8      # FIT dev run
    FOOTBALL_SCENARIO_READ_VALIDATION=1 py -3 scripts/football_scenario_replay.py run --sport nfl --season 2025
"""
from __future__ import annotations

import argparse
import csv
import dataclasses
import gzip
import json
import os
import random
import sys
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts import football_scenario_rates as F  # noqa: E402

SIMS = 300
VALIDATION_SEASON = 2025
_NCAAF_SNAP = {"Rush", "Pass Reception", "Pass Incompletion", "Sack", "Passing Touchdown", "Rushing Touchdown",
               "Interception", "Pass Interception Return", "Interception Return Touchdown",
               "Fumble Recovery (Own)", "Fumble Recovery (Opponent)", "Fumble Return Touchdown"}


# ---------------------------------------------------------------------------
# states: one real scrimmage snap per regulation quarter, seeded by (game, quarter)
# ---------------------------------------------------------------------------

def _pick(rows: List[dict], gid: str, q: int) -> Optional[dict]:
    if not rows:
        return None
    return rows[random.Random(f"{gid}|{q}").randrange(len(rows))]


def nfl_states(season: int, game_ids: set) -> Dict[str, Dict[str, Any]]:
    path = F.nfl_root() / "tracking" / "nflverse" / "pbp" / f"pbp_{season}.csv"
    by_game: Dict[str, Dict[int, List[dict]]] = defaultdict(lambda: defaultdict(list))
    final: Dict[str, dict] = {}
    with path.open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            gid = r["game_id"]
            if gid not in game_ids:
                continue
            final[gid] = r
            q = F._i(r.get("qtr"))
            if (r.get("play_type") in ("pass", "run") and r.get("down") in ("1", "2", "3", "4") and 1 <= q <= 4
                    and F._i(r.get("quarter_seconds_remaining")) > 0 and r.get("posteam")):
                by_game[gid][q].append(r)
    out = {}
    for gid, quarters in by_game.items():
        last = final[gid]
        home = last["home_team"]
        states = []
        for q in (1, 2, 3, 4):
            r = _pick(quarters.get(q, []), gid, q)
            if r is None:
                continue
            home_has = r["posteam"] == home
            ps, ds = F._i(r.get("posteam_score")), F._i(r.get("defteam_score"))
            states.append({"q": q, "clock": F._i(r["quarter_seconds_remaining"]),
                           "home_score": ps if home_has else ds, "away_score": ds if home_has else ps,
                           "down": F._i(r["down"]), "distance": max(1, F._i(r.get("ydstogo"), 10)),
                           "field_position": max(1, min(99, 100 - F._i(r.get("yardline_100"), 75))),
                           "owner": "home" if home_has else "away"})
        hs, as_ = F._i(last.get("home_score")), F._i(last.get("away_score"))
        out[gid] = {"states": states, "final_margin": hs - as_, "final_total": hs + as_}
    return out


def ncaaf_states(season: int, game_ids: set) -> Dict[str, Dict[str, Any]]:
    root = F.PRIMARY / "data" / "ncaaf_source" / "historical_truth"
    meta = {str(g["id"]): g for g in F._ncaaf_games(season)}
    by_game: Dict[str, Dict[int, List[dict]]] = defaultdict(lambda: defaultdict(list))
    for wk in range(1, 17):
        p = root / f"plays_{season}_wk{wk:02d}.json.gz"
        if not p.exists():
            continue
        for r in json.load(gzip.open(p, "rt", encoding="utf-8")):
            gid = str(r.get("gameId"))
            if gid not in game_ids:
                continue
            q = F._i(r.get("period"))
            clock = F._i((r.get("clock") or {}).get("minutes")) * 60 + F._i((r.get("clock") or {}).get("seconds"))
            if r.get("playType") in _NCAAF_SNAP and 1 <= F._i(r.get("down")) <= 4 and 1 <= q <= 4 and clock > 0:
                r["_clock"] = clock
                by_game[gid][q].append(r)
    out = {}
    for gid, quarters in by_game.items():
        g = meta[gid]
        states = []
        for q in (1, 2, 3, 4):
            rows = sorted(quarters.get(q, []), key=lambda r: (F._i(r.get("driveNumber")), F._i(r.get("playNumber"))))
            r = _pick(rows, gid, q)
            if r is None:
                continue
            home_has = r.get("offense") == r.get("home")
            os_, ds = F._i(r.get("offenseScore")), F._i(r.get("defenseScore"))
            states.append({"q": q, "clock": r["_clock"],
                           "home_score": os_ if home_has else ds, "away_score": ds if home_has else os_,
                           "down": F._i(r["down"]), "distance": max(1, F._i(r.get("distance"), 10)),
                           "field_position": max(1, min(99, 100 - F._i(r.get("yardsToGoal"), 75))),
                           "owner": "home" if home_has else "away"})
        hs, as_ = F._i(g["homePoints"]), F._i(g["awayPoints"])
        out[gid] = {"states": states, "final_margin": hs - as_, "final_total": hs + as_}
    return out


# ---------------------------------------------------------------------------
# workers
# ---------------------------------------------------------------------------

_W: Dict[str, Any] = {}


def _init(sport: str, arg: str, candidate: Dict[str, Any]) -> None:
    if sport == "nfl":
        F._nfl_init(arg, {})
        from syndicate.features.nfl import live_resim as L
        from syndicate.features.football.sim_engine.smartsim2.calibration_profile import NFL_CALIBRATION_PROFILE as P
        L.UNINFORMATIVE_BAND = (2.0, 2.0)      # engine grade, not the publish guard (both arms)
    else:
        F._ncaaf_init(arg, {})
        from syndicate.features.ncaaf import live_resim as L
        from syndicate.features.football.sim_engine.smartsim2.ncaaf_calibration_profile import NCAAF_CALIBRATION_PROFILE as P
    _W.update(sport=sport, L=L, arms={"production": P, "candidate": dataclasses.replace(P, **candidate)})


def _ratings(task: Dict[str, Any]):
    if _W["sport"] == "nfl":
        gen, s = F._W["gen"], task["season"]
        plays, prior = F._nfl_plays(s), F._nfl_plays(s - 1)
        ho, hd, _ = gen.team_rating(task["home"], week=task["week"], current_plays=plays, prior_plays=prior)
        ao, ad, _ = gen.team_rating(task["away"], week=task["week"], current_plays=plays, prior_plays=prior)
        return ho, hd, ao, ad
    gen = F._W["gen"]
    (ho, hd), (ao, ad) = task["index"][gen.norm(task["home"])], task["index"][gen.norm(task["away"])]
    return ho, hd, ao, ad


def replay_game(task: Dict[str, Any]) -> Dict[str, Any]:
    L, sport = _W["L"], _W["sport"]
    ho, hd, ao, ad = _ratings(task)
    rows = []
    for st in task["states"]:
        cls = L.NflLiveGameState if sport == "nfl" else L.NcaafLiveGameState
        state = cls(away_team=task["away"], home_team=task["home"], period=st["q"], clock_seconds=st["clock"],
                    home_score=st["home_score"], away_score=st["away_score"], down=st["down"],
                    distance=st["distance"], field_position=st["field_position"], possession_owner=st["owner"])
        rec = {"q": st["q"]}
        for arm, prof in _W["arms"].items():
            if sport == "nfl":
                res = L.resim_live_game(state, home_offense=ho, home_defense=hd, away_offense=ao, away_defense=ad,
                                        sims=SIMS, profile=prof, env={"SYNDICATE_NFL_LIVE_RESIM": "1"}, rating_sd=0.0)
                ok = isinstance(res, dict)
                rec[arm] = ({"p": res["model_home_win_prob_raw"], "margin": res["margin_mean"], "total": res["total_mean"]}
                            if ok else {"refused": res.reason})
            else:
                res = L.resim_live_game(state, home_offense=ho, home_defense=hd, away_offense=ao, away_defense=ad,
                                        sims=SIMS, profile=prof, level_shrink=None)
                ok = isinstance(res, dict)
                rec[arm] = ({"p": res["home_win_prob"], "margin": res["home_margin_mean"], "total": res["total_mean"]}
                            if ok else {"refused": res.reason})
        rows.append(rec)
    return {"game_id": str(task["game_id"]), "week": task["week"], "final_margin": task["final_margin"],
            "final_total": task["final_total"], "rows": rows}


# ---------------------------------------------------------------------------
# run + grade
# ---------------------------------------------------------------------------

def cmd_run(args) -> None:
    sport, season = args.sport, args.season
    out = F.OUT_ROOT / sport / "refit"
    out.mkdir(parents=True, exist_ok=True)
    if season == VALIDATION_SEASON:
        if not os.environ.get("FOOTBALL_SCENARIO_READ_VALIDATION"):
            raise SystemExit("2025 is VALIDATION; set FOOTBALL_SCENARIO_READ_VALIDATION=1 to read it (once)")
        marker = out / "LIVE_VALIDATION_READ"
        if marker.exists() and not args.resume:
            raise SystemExit(f"live 2025 already read for {sport}: {marker.read_text().strip()}")
        marker.write_text(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), encoding="utf-8")
    candidate = json.loads((out / "descent_result.json").read_text(encoding="utf-8"))["overrides"]
    tasks = (F.nfl_tasks if sport == "nfl" else F.ncaaf_tasks)([season], SIMS)
    if args.every > 1:
        tasks = tasks[:: args.every]
    ids = {str(t["game_id"]) for t in tasks}
    states = (nfl_states if sport == "nfl" else ncaaf_states)(season, ids)
    cache = out / f"live_replay_{season}{'_every' + str(args.every) if args.every > 1 else ''}.jsonl"
    done = set()
    if cache.exists():
        done = {json.loads(l)["game_id"] for l in cache.read_text(encoding="utf-8").splitlines() if l.strip()}
    todo = [dict(t, **states[str(t["game_id"])]) for t in tasks if str(t["game_id"]) in states and str(t["game_id"]) not in done]
    print(f"[live {sport} {season}] {len(tasks)} games, {len(states)} with states, {len(done)} cached, "
          f"{len(todo)} to run, {SIMS} sims/state/arm -> {cache}", flush=True)
    arg = str(F.nfl_root()) if sport == "nfl" else str(F.ncaaf_work())
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=args.workers, initializer=_init, initargs=(sport, arg, candidate)) as ex, \
            cache.open("a", encoding="utf-8") as fh:
        futs = [ex.submit(replay_game, t) for t in todo]
        for i, fut in enumerate(as_completed(futs), 1):
            fh.write(json.dumps(fut.result()) + "\n")
            fh.flush()
            if i % 20 == 0 or i == len(todo):
                el = time.time() - t0
                print(f"[live {sport}] {i}/{len(todo)}  {el / 60:.1f} min  eta {el / i * (len(todo) - i) / 60:.1f} min", flush=True)
    grade(sport, cache, season)


def grade(sport: str, cache: Path, season: int) -> None:
    games = [json.loads(l) for l in cache.read_text(encoding="utf-8").splitlines() if l.strip()]
    per_game: Dict[str, Dict[str, List[float]]] = {}
    by_q: Dict[int, Dict[str, List[float]]] = defaultdict(lambda: defaultdict(list))
    refused = defaultdict(int)
    n_states = 0
    for g in games:
        y = 1.0 if g["final_margin"] > 0 else (0.5 if g["final_margin"] == 0 else 0.0)
        d = defaultdict(list)
        for r in g["rows"]:
            a, b = r["production"], r["candidate"]
            if "refused" in a or "refused" in b:
                refused[a.get("refused") or b.get("refused")] += 1
                continue
            n_states += 1
            for k, fn in (("brier", lambda x: (x["p"] - y) ** 2),
                          ("margin", lambda x: abs(g["final_margin"] - x["margin"])),
                          ("total", lambda x: abs(g["final_total"] - x["total"]))):
                delta = fn(b) - fn(a)
                d[k].append(delta)
                by_q[r["q"]][k].append(delta)
                d[k + "_prod"].append(fn(a))
        if d:
            per_game[g["game_id"]] = d
    print(f"\n[live {sport} {season}] {len(per_game)} games, {n_states} states graded, refused {dict(refused)}")
    gates = {}
    for k, tol, name in (("brier", 0.003, "L1_brier"), ("margin", 0.15, "L2_margin_abs_err"), ("total", 0.15, "L3_total_abs_err")):
        # game-clustered: one mean delta per game, then the paired bootstrap over games
        deltas = [sum(v[k]) / len(v[k]) for v in per_game.values() if v.get(k)]
        prod = sum(sum(v[k + "_prod"]) / len(v[k + "_prod"]) for v in per_game.values() if v.get(k)) / len(deltas)
        m, lo, hi = F._paired_ci(deltas)
        gates[name] = {"pass": hi < tol, "production": round(prod, 4), "delta": round(m, 4),
                       "ci": [round(lo, 4), round(hi, 4)], "tol": tol}
        print(f"  {'PASS' if hi < tol else 'FAIL'}  {name:20} production {prod:.4f}  cand-prod {m:+.4f} [{lo:+.4f}, {hi:+.4f}]  (tol < +{tol})")
    for q in sorted(by_q):
        row = by_q[q]
        print(f"     Q{q}: " + "  ".join(f"{k} {sum(v) / len(v):+.4f} (n={len(v)})" for k, v in row.items()))
    passed = all(v["pass"] for v in gates.values())
    print(f"  => {'LIVE GATES PASS' if passed else 'LIVE GATES FAIL'}")
    (cache.with_suffix(".report.json")).write_text(json.dumps({"sport": sport, "season": season, "games": len(per_game),
                                                               "states": n_states, "refused": refused, "gates": gates,
                                                               "PASS": passed}, indent=1), encoding="utf-8")


def main(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("run",))
    ap.add_argument("--sport", choices=("nfl", "ncaaf"), required=True)
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--every", type=int, default=1)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args(argv)
    if args.season == VALIDATION_SEASON and args.every != 1:
        raise SystemExit("VALIDATION replays every 2025 game (amendment 3 rule)")
    cmd_run(args)


if __name__ == "__main__":
    main()
