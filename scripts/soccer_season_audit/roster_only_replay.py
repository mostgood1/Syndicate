# -*- coding: utf-8 -*-
"""H-ROSTER replay: does adding ESPN-roster players with no stats row improve the props?

PRE-REGISTERED in `.syndicate/findings_2026-10-06_soccer_roster_only_players_prereg.md`
(5c36cf37) and, for every choice that file leaves open, in lane
`soccer-roster-only-players` (`lanes.md`, landed 9c170ca4 BEFORE this ran).

Two arms over the SAME pre-kickoff team distributions and the SAME squads:
  A  the shipped engine: `_load_player_rows` -> `build_soccer_player_features`
     -> `build_usage_profiles` -> `project_player_props` (the
     `calibration_engine_replay.py` method)
  B  A's squad + `roster_only_players.roster_only_rows` appended per club.

Primary metric (per market): log loss on APPEARED outfield players listed in BOTH
arms, summed per match as B - A, bootstrapped over matches (2000 reps, seed 11).
  SOT 0.5      shots_on_target_over_probabilities["0.5"]  (conditional on appearing)
  anytime      anytime_scorer_probability_if_playing     (conditional on appearing)
PASS = both 95% CIs wholly < 0, AND listed-player calibration (realised / expected)
moves toward 1.0: starters' first scorer (the `scorer_race` the board prices) and
listed appeared players' anytime.

Run (cache = the 10-02 props cache; rosters = the fleet's rosters_2026.csv copies):
    SOCCER_AUDIT_CACHE=C:/tmp/soccer-lpb/cache ROSTER_ONLY_ROSTERS=<dir> \
        py -3 roster_only_replay.py --out <report.json>
"""
import argparse
import collections
import contextlib
import csv
import glob
import importlib.util
import io
import json
import math
import os
import random
import re
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

CHECKOUT = Path(os.environ.get("SYNDICATE_CHECKOUT") or Path(__file__).resolve().parents[2])
sys.path.insert(0, str(CHECKOUT))
import syndicate  # noqa: E402

assert Path(syndicate.__file__).resolve().parent.parent == CHECKOUT.resolve(), syndicate.__file__
HERE = Path(__file__).resolve().parent
sys.path.append(str(HERE))

spec = importlib.util.spec_from_file_location("bsa_roster_only", CHECKOUT / "scripts" / "build_soccer_artifacts.py")
bsa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bsa)

from syndicate.features.soccer.features.loaders import build_soccer_player_features  # noqa: E402
import roster_only_players as ROP  # noqa: E402  -- the measured mechanism; NOT shipped (H-ROSTER failed)
from syndicate.features.soccer.sim_engine.soccersim import player_props as PP  # noqa: E402
from syndicate.features.shared.prop_projections import _norm_name  # noqa: E402
from syndicate.features.shared.soccer_scorer_markets import scorer_race  # noqa: E402

from common import LEAGUES, S, load_outcomes, load_recs  # noqa: E402
from namejoin_diag import strict_match  # noqa: E402
import replay_squads as rs  # noqa: E402

START, END = "2026-09-17", "2026-09-30"
EPS = 1e-6
ESPN_CACHE = os.path.join(tempfile.gettempdir(), "espn_shots_cache")
ROSTERS = Path(os.environ.get("ROSTER_ONLY_ROSTERS") or "")


def clip(p):
    return min(1 - EPS, max(EPS, float(p)))


def ll(p, y):
    p = clip(p)
    return -(math.log(p) if y else math.log(1 - p))


def appeared(q):
    return bool(q.get("starter") or q.get("subbed_in"))


def fleet_roster_rows(league, season):
    path = ROSTERS / league / f"rosters_{season}.csv"
    if not path.exists():
        return ()
    with path.open(encoding="utf-8") as handle:
        return tuple(csv.DictReader(handle))


def stats_names(root, league):
    names = []
    for f in sorted(glob.glob(str(root / league / "players" / "players_*.csv"))):
        with open(f, encoding="utf-8") as handle:
            names.extend(r.get("player_name") for r in csv.DictReader(handle))
    return names


def first_scorer(league, match_id):
    """(first-goal scorer's normalised name or None, n goals) from the ESPN summary; None if unusable."""
    path = os.path.join(ESPN_CACHE, f"{league}_{match_id}.json")
    if not os.path.exists(path):
        return None
    j = json.load(io.open(path, encoding="utf-8"))
    comp = ((j.get("header") or {}).get("competitions") or [{}])[0]
    if ((comp.get("status") or {}).get("type") or {}).get("name") != "STATUS_FULL_TIME":
        return None
    goals = []
    for e in j.get("keyEvents") or []:
        if not e.get("scoringPlay") or e.get("shootout"):
            continue
        if str((e.get("type") or {}).get("type") or "") == "own-goal":
            continue
        parts = e.get("participants") or []
        name = ((parts[0] if parts else {}).get("athlete") or {}).get("displayName")
        if not name:
            return None
        key = ((e.get("period") or {}).get("number") or 0, float((e.get("clock") or {}).get("value") or 0.0))
        goals.append((key, _norm_name(name)))
    goals.sort()
    if len(goals) >= 2 and goals[0][0] == goals[1][0]:
        return None
    return {"first": goals[0][1] if goals else None}


def project(rows, side, club, dist):
    profiles = PP.build_usage_profiles(rows, side=side, team=club)
    return [PP.project_player_props(dist, prof).to_dict() for prof in profiles]


def boot(units, fn, reps=2000, seed=11):
    rng = random.Random(seed)
    vals = []
    for _ in range(reps):
        sample = [units[rng.randrange(len(units))] for _ in units]
        vals.append(fn(sample))
    vals.sort()
    return [vals[int(0.025 * reps)], vals[int(0.975 * reps) - 1]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--start", default=START)
    ap.add_argument("--end", default=END)
    args = ap.parse_args()
    assert ROSTERS.is_dir(), f"ROSTER_ONLY_ROSTERS not a directory: {ROSTERS}"

    recs, outc = load_recs(prekickoff_only=True), load_outcomes()
    tmp = Path(S) / "roster_only_root"
    shutil.rmtree(tmp, ignore_errors=True)
    root = rs.build_root(tmp)
    bsa.roster_rows = fleet_roster_rows  # production reads the runtime disk's roster for the rescue
    rows_by_league, names_by_league, substrate = {}, {}, {}
    for league in LEAGUES:
        with contextlib.redirect_stdout(io.StringIO()):
            rows_by_league[league] = bsa._load_player_rows(league, root)
        substrate[league] = dict(bsa._PLAYER_LOAD_AUDIT)
        names_by_league[league] = stats_names(root, league)
    evidence = {str(r.get("player_id")): r.get("season_evidence") for lg in LEAGUES for r in rows_by_league[lg]}
    extra_by_league, extra_audit = {}, {}
    for league in LEAGUES:
        extra_by_league[league], extra_audit[league] = ROP.roster_only_rows(
            fleet_roster_rows(league, bsa.default_season(league)), names_by_league[league], rows_by_league[league],
            league=league)

    cov = collections.Counter()
    print("prekickoff build dates:", collections.Counter(m["date"][:7] for m in recs.values()), flush=True)
    dates_used = set()
    per_match = []          # one unit per match
    added_rows = []         # added players' own scoring
    audits = collections.defaultdict(collections.Counter)
    for (lg, mid), m in sorted(recs.items()):
        cov["prekickoff_builds"] += 1
        if not (args.start <= m["date"] <= args.end):
            continue
        cov["in_window"] += 1
        o = outc.get((lg, mid))
        if not o:
            cov["no_outcome"] += 1
            continue
        if m["shots_h"] is None:
            cov["no_distribution"] += 1
            continue
        dist = SimpleNamespace(mean_home_goals=m["home_mean"] or 0.0, mean_away_goals=m["away_mean"] or 0.0,
                               mean_home_shots=m["shots_h"], mean_away_shots=m["shots_a"],
                               mean_home_shots_on_target=m["sot_h"] or 0.0, mean_away_shots_on_target=m["sot_a"] or 0.0)
        with contextlib.redirect_stdout(io.StringIO()):
            extra = extra_by_league[lg]
            feats_a = build_soccer_player_features(rows_by_league[lg], league=lg, date=m["date"], fixture_teams=[m["home"], m["away"]])
            feats_b = build_soccer_player_features(rows_by_league[lg] + extra, league=lg, date=m["date"], fixture_teams=[m["home"], m["away"]])
        unit = {"match": f"{lg}|{mid}", "league": lg, "date": m["date"], "sot": [], "any": [], "players_a": [], "players_b": []}
        for side, club in (("home", m["home"]), ("away", m["away"])):
            def rows_of(feats):
                return [{"player_id": f.player_id, "player_name": f.player_name, "position": f.position, "team": f.team,
                         "_source": (f.adapter_metadata or {}).get("source"), **dict(f.usage_metrics or {})}
                        for f in feats if f.team == club]
            ra, rb = rows_of(feats_a), rows_of(feats_b)
            n_added = sum(1 for r in rb if r["_source"] == ROP.SOURCE_TAG)
            audits[lg]["sides"] += 1
            audits[lg]["added"] += n_added
            audits[lg]["listed"] += len(ra)
            if not ra or not (m["shots_h"] if side == "home" else m["shots_a"]):
                cov["empty_side"] += 1
                continue
            pa, pb = project(ra, side, club, dist), project(rb, side, club, dist)
            for p, r in zip(pb, rb):
                p["_added"] = r["_source"] == ROP.SOURCE_TAG
            unit["players_a"].extend(pa)
            unit["players_b"].extend(pb)
            box = [q for q in o["players"] if q["side"] == side]
            map_a = strict_match([{"player_name": p["player_name"], "side": side} for p in pa], box)
            map_b = strict_match([{"player_name": p["player_name"], "side": side} for p in pb], box)
            b_by_id = {p["player_id"]: i for i, p in enumerate(pb)}
            box_of_b = {i: j for i, j in map_b.items()}
            for i, j in map_a.items():
                q = box[j]
                pa_i = pa[i]
                if not appeared(q) or str(pa_i.get("position") or "").upper() in ("GK", "G", "GOALKEEPER") or pa_i.get("expected_saves"):
                    continue
                ib = b_by_id.get(pa_i["player_id"])
                if ib is None or box_of_b.get(ib) != j:
                    cov["listed_rebound_differently"] += 1
                    continue
                pb_i = pb[ib]
                y_sot = int((q.get("sot") or 0) >= 1)
                y_goal = int((q.get("goals") or 0) >= 1)
                a_sot = (pa_i.get("shots_on_target_over_probabilities") or {}).get("0.5")
                b_sot = (pb_i.get("shots_on_target_over_probabilities") or {}).get("0.5")
                if a_sot is not None and b_sot is not None:
                    unit["sot"].append((a_sot, b_sot, y_sot, evidence.get(str(pa_i["player_id"]))))
                a_any, b_any = pa_i.get("anytime_scorer_probability_if_playing"), pb_i.get("anytime_scorer_probability_if_playing")
                if a_any is not None and b_any is not None:
                    unit["any"].append((a_any, b_any, y_goal, evidence.get(str(pa_i["player_id"]))))
            for i, j in map_b.items():
                if pb[i].get("_added") and appeared(box[j]) and not pb[i].get("expected_saves"):
                    q = box[j]
                    added_rows.append({"league": lg, "p_sot": (pb[i].get("shots_on_target_over_probabilities") or {}).get("0.5"),
                                       "p_any": pb[i].get("anytime_scorer_probability_if_playing"),
                                       "y_sot": int((q.get("sot") or 0) >= 1), "y_goal": int((q.get("goals") or 0) >= 1),
                                       "starter": bool(q.get("starter"))})
            unit.setdefault("box", []).extend([dict(q, _bound_a=(j in set(map_a.values()))) for j, q in enumerate(box)])
        fs = first_scorer(lg, mid)
        unit["first"] = fs
        if unit["sot"] or unit["any"]:
            per_match.append(unit)
            dates_used.add(m["date"])

    def delta(units, key):
        return sum(ll(b, y) - ll(a, y) for u in units for a, b, y, _ in u[key])

    def n_of(units, key):
        return sum(len(u[key]) for u in units)

    report = {"coverage": {**cov, "matches_scored": len(per_match), "dates": len(dates_used),
                           "window": [min(dates_used), max(dates_used)] if dates_used else None,
                           "player_files_vintage": "2026-10-02 production pull (leak <= 15 days)",
                           "roster_source": str(ROSTERS)},
              "substrate": substrate, "roster_only_audit": {lg: {k: v for k, v in a.items() if k != "priors"} for lg, a in extra_audit.items()},
              "priors": {lg: a.get("priors") for lg, a in extra_audit.items()}, "squads": {lg: dict(c) for lg, c in audits.items()}, "markets": {}}
    for key, label in (("sot", "SOT 0.5"), ("any", "anytime")):
        n = n_of(per_match, key)
        units = [u for u in per_match if u[key]]
        if not n:
            report["markets"][label] = {"n_players": 0}
            continue
        d = delta(units, key)
        report["markets"][label] = {
            "n_players": n, "n_matches": len(units),
            "logloss_A": round(sum(ll(a, y) for u in units for a, _, y, _ in u[key]) / n, 5),
            "logloss_B": round(sum(ll(b, y) for u in units for _, b, y, _ in u[key]) / n, 5),
            "delta_per_player": round(d / n, 5),
            "delta_ci95_per_player": [round(v, 5) for v in boot(units, lambda us: delta(us, key) / max(n_of(us, key), 1))],
            "mean_p_A": round(sum(a for u in units for a, _, _, _ in u[key]) / n, 4),
            "mean_p_B": round(sum(b for u in units for _, b, _, _ in u[key]) / n, 4),
            "realised": round(sum(y for u in units for _, _, y, _ in u[key]) / n, 4),
        }
        for lg in sorted({u["league"] for u in units}):
            sub = [u for u in units if u["league"] == lg]
            nn = n_of(sub, key)
            report["markets"][label].setdefault("by_league", {})[lg] = {"n": nn, "matches": len(sub), "delta_per_player": round(delta(sub, key) / nn, 5)}
        # Season phase (descriptive, lane choice 9): the listed player's row is current-season or prior-season evidence.
        for ev in ("current", "prior_only", "single_season"):
            sub = [{**u, key: [t for t in u[key] if t[3] == ev]} for u in units]
            sub = [u for u in sub if u[key]]
            nn = n_of(sub, key)
            if nn:
                report["markets"][label].setdefault("by_season_evidence", {})[ev] = {
                    "n": nn, "matches": len(sub), "delta_per_player": round(delta(sub, key) / nn, 5),
                    "ci95": [round(v, 5) for v in boot(sub, lambda us: delta(us, key) / max(n_of(us, key), 1), reps=1000)]}

    # Calibration (realised / expected) of LISTED players: anytime on appeared listed players, and
    # first scorer for starters via the board's scorer_race over each arm's full list.
    any_rows = [(a, b, y) for u in per_match for a, b, y, _ in u["any"]] or [(1.0, 1.0, 0)]
    calib = {"anytime_listed": {"A": round(sum(y for *_, y in any_rows) / sum(a for a, _, _ in any_rows), 4),
                                "B": round(sum(y for *_, y in any_rows) / sum(b for _, b, _ in any_rows), 4),
                                "n": len(any_rows)}}
    fs_units = []
    for u in per_match:
        if not u.get("first"):
            continue
        rec = recs.get(tuple(u["match"].split("|", 1)))
        race_a = scorer_race(u["players_a"], match_expected_goals=rec["total_mean"])["by_player"]
        race_b = scorer_race(u["players_b"], match_expected_goals=rec["total_mean"])["by_player"]
        starters_a = []
        for q in u["box"]:
            if not q.get("starter") or not q.get("_bound_a"):
                continue
            key = _norm_name(q["name"])
            pa_ = next((v for k, v in race_a.items() if _norm_name(k) == key), None)
            pb_ = next((v for k, v in race_b.items() if _norm_name(k) == key), None)
            if pa_ is None or pb_ is None:
                continue
            starters_a.append((pa_, pb_, int(u["first"]["first"] == key)))
        if starters_a:
            fs_units.append(starters_a)
    if fs_units:
        flat = [x for u in fs_units for x in u]
        calib["first_scorer_starters"] = {
            "n": len(flat), "matches": len(fs_units), "realised": sum(y for *_, y in flat),
            "A": round(sum(y for *_, y in flat) / sum(a for a, _, _ in flat), 4),
            "B": round(sum(y for *_, y in flat) / sum(b for _, b, _ in flat), 4),
            "A_ci95": [round(v, 3) for v in boot(fs_units, lambda us: sum(y for u in us for *_, y in u) / sum(a for u in us for a, _, _ in u))],
            "B_ci95": [round(v, 3) for v in boot(fs_units, lambda us: sum(y for u in us for *_, y in u) / sum(b for u in us for _, b, _ in u))],
        }
    report["calibration"] = calib
    if added_rows:
        report["added_players_appeared"] = {
            "n": len(added_rows), "starters": sum(r["starter"] for r in added_rows),
            "sot_rate_realised": round(sum(r["y_sot"] for r in added_rows) / len(added_rows), 4),
            "sot_mean_p": round(sum(r["p_sot"] or 0 for r in added_rows) / len(added_rows), 4),
            "goal_rate_realised": round(sum(r["y_goal"] for r in added_rows) / len(added_rows), 4),
            "goal_mean_p": round(sum(r["p_any"] or 0 for r in added_rows) / len(added_rows), 4),
        }
    m = report["markets"]
    passed = all(m[k].get("n_players") and m[k]["delta_ci95_per_player"][1] < 0 for k in m) and all(
        abs(c["B"] - 1) < abs(c["A"] - 1) for c in (calib.get("first_scorer_starters"), calib["anytime_listed"]) if c)
    report["verdict"] = "PASS" if passed else "FAIL"
    Path(args.out).write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("coverage", "markets", "calibration", "verdict")}, indent=1))
    print("added_players_appeared", report.get("added_players_appeared"))


if __name__ == "__main__":
    main()
