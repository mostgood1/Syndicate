# -*- coding: utf-8 -*-
"""Market-anchored vs unanchored soccer props, graded against REALIZED SHOTS.

This is the harness that answered `todo.md #622`(3) on 2026-09-03:

    6,486 gradeable (player, match) rows | 136 matches | 56 league-date units
    base MAE      0.52126 shots
    anchored MAE  0.52163 shots   ->  +0.00038 per player-match, +0.072% WORSE
    per match: worse in 95/136 (70%), sign test p=0.0000
               mean -0.00101, sd 0.01106, t=-1.06, MEDIAN delta +0.0000

WHY IT GRADES OUTCOMES AND NEVER A BOOK PRICE
---------------------------------------------
`market_anchoring` pulls the simulation TOWARD the h2h market. Scoring it against
a market price therefore rewards it for converging, which it does by
construction, and a "-40% MAE vs the market" result says nothing about skill. The
only question that construction cannot answer is whether the anchored projection
predicts WHAT HAPPENED better than the unanchored one. So the target is realized
shots from ESPN commentary.

FOUR THINGS THAT MAKE THE COMPARISON FAIR, three of them learned the hard way
--------------------------------------------------------------------------
1. **BOTH ARMS ARE RE-SIMULATED HERE.** The archived production predictions are
   unanchored and may have been built with different lineups, player rows or
   rating vintage. Using them as the base arm lets any of that leak into the
   difference. Base and anchored differ ONLY in the ratings handed to
   `build_soccer_simulation_input`.
2. **RATINGS ARE `as_of` THE FIXTURE DATE.** `compute_team_ratings` demands it
   precisely so a forward-looking and a backward-looking caller cannot be
   confused; passing today would score an August fixture with September form.
3. **THE GRADING POPULATION IS EVERY PREDICTED PLAYER, with `realized = 0` when
   they took no shots.** The first version skipped zero-outcome rows, reasoning
   that a 0 for an unused substitute is an availability fact. That is SELECTION
   ON THE DEPENDENT VARIABLE: it kept **42 of 197 rows (a 79% cut)** and left
   every survivor with `realized >= 1`, on a test of whether anchoring RAISES
   projections. Corrected, the MAE moved 0.98 -> 0.52. `fit_soccer_shot_shrinkage`
   uses this same denominator, and it grades the UNCONDITIONAL `expected_shots`
   -- which already prices in the chance of not appearing, and is what makes a
   zero a legitimate outcome rather than an artefact.
4. **STATISTICS ARE MATCH-CLUSTERED.** Every player in a match receives the SAME
   anchor shift, so player rows are not independent. The player-level sign test
   read **p=0.0027 against its own t of -1.28** -- when those two disagree the
   disagreement IS the diagnosis. One mean delta per match, then test across
   matches.

A LEAKAGE THAT CANNOT BE REMOVED, STATED RATHER THAN HIDDEN
----------------------------------------------------------
`players_*.csv` are SEASON aggregates, so a past fixture's player usage is
informed by matches played after it. This inflates BOTH arms identically and
cancels in the paired difference -- but the ABSOLUTE MAEs are therefore
optimistic and must not be quoted as the model's skill. **The paired delta is the
result; the levels are not.**

INPUTS (fetch them first with `fetch_prod_artifacts_paced.py`, not in a loop)
    --odds-cache   soccer_source/artifacts/soccer/odds_history/<date>.json
    --recs-cache   soccer_source/<league>/api/recommendations/recommendations_<date>.json
Ratings and rosters come from `--source-root` (default `data/soccer_source`).
ESPN summaries are fetched once per match and cached under `--espn-cache`.

    python scripts/backtest_soccer_anchor_vs_outcomes.py \
        --odds-cache reports/prod_cache/odds_history \
        --recs-cache reports/prod_cache/recommendations \
        --weight 0.4 --before 2026-09-02
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import re
import statistics as stats
import sys
import time
import unicodedata
import urllib.request
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

GOALS_BASED = {"eredivisie", "primeira_liga", "championship", "belgian_pro_league"}
# mls needs a network fetch for ratings; belgian_pro_league's outcome capture was
# measured at 0.13 (`fit_soccer_shot_shrinkage`'s BAD set) -- outcomes absent,
# not zero, which would read as a model error.
DEFAULT_LEAGUES = ("epl", "la_liga", "serie_a", "bundesliga", "ligue_1",
                   "eredivisie", "primeira_liga", "championship")
_OPTS: dict = {}


def fold(name) -> str:
    """NFKD-strip + lowercase. `Alvaro Morata` and `Álvaro Morata` are one
    player; raw equality matched 18 of 37 shooters and looked like thin data."""
    return "".join(c for c in unicodedata.normalize("NFKD", str(name))
                   if not unicodedata.combining(c)).lower().strip()


def american_to_prob(value):
    """A price strictly inside (-100, 100) is not an American price; refuse it
    rather than manufacture a probability."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    if -100.0 < value < 100.0:
        return None
    return (-value) / ((-value) + 100.0) if value < 0 else 100.0 / (value + 100.0)


def devigged_h2h(odds_cache: Path, date: str) -> dict:
    """event_id -> {home_team, away_team, p_home} from one odds_history shard.

    Mean per side IN PROBABILITY SPACE across books, then proportional de-vig.
    Averaging American prices is meaningless and produced 43% impossible prices
    once already (`[wnba-consensus-price]`)."""
    hits = list(odds_cache.glob(f"*{date}*"))
    if not hits:
        return {}
    try:
        doc = json.loads(hits[0].read_text(encoding="utf-8"))
    except Exception:
        return {}
    per, meta = collections.defaultdict(lambda: collections.defaultdict(list)), {}
    for key, block in (doc.get("markets") or {}).items():
        if "market=h2h" not in key:
            continue
        field = dict(p.split("=", 1) for p in key.split("|") if "=" in p)
        eid, home, away, side = (field.get("event_id"), field.get("home_team"),
                                 field.get("away_team"), field.get("side"))
        history = block.get("history") or []
        if not (eid and home and away and side and history):
            continue
        prob = american_to_prob(history[-1].get("odds"))
        if prob is None:
            continue
        per[eid]["home" if side == home else "away" if side == away else "draw"].append(prob)
        meta[eid] = (home, away)
    out = {}
    for eid, sides in per.items():
        if set(sides) != {"home", "draw", "away"}:
            continue          # a partial three-way cannot be de-vigged
        means = {k: sum(v) / len(v) for k, v in sides.items()}
        total = sum(means.values())
        if total > 0:
            out[eid] = {"home_team": meta[eid][0], "away_team": meta[eid][1],
                        "p_home": means["home"] / total}
    return out


def ratings_as_of(league: str, as_of: str, source_root: Path):
    import pandas as pd
    from syndicate.features.soccer.features.loaders import compute_team_ratings
    from syndicate.features.soccer.features.loaders import team_rows_from_match_history
    if league in GOALS_BASED:
        frames = [pd.read_csv(p) for p in sorted((source_root / league / "history").glob("matches_*.csv"))]
        if not frames:
            raise SystemExit(f"no match history for {league}")
        rows = team_rows_from_match_history(pd.concat(frames, ignore_index=True).to_dict("records"))
        return compute_team_ratings(rows, as_of=as_of, window=90)  # two rows/match
    frames = [pd.read_csv(p) for p in sorted((source_root / league / "team_history").glob("teams_*.csv"))]
    if not frames:
        raise SystemExit(f"no team history for {league}")
    rows = pd.concat(frames, ignore_index=True).to_dict("records")
    return compute_team_ratings(rows, as_of=as_of, window=45)


def player_rows(league: str, source_root: Path):
    import pandas as pd
    frames = [pd.read_csv(p) for p in sorted((source_root / league / "players").glob("players_*.csv"))]
    return pd.concat(frames, ignore_index=True).to_dict("records") if frames else []


def run_unit(job):
    """One (league, date): solve the shift per priced fixture, then simulate the
    slate TWICE -- once on history ratings, once on anchored ones."""
    league, date, fixtures, targets, opts = job
    from syndicate.features.soccer.adapters import build_soccer_simulation_adapter
    from syndicate.features.soccer.features.loaders import build_soccer_simulation_input
    from syndicate.features.soccer.features.market_anchoring import solve_market_rating_shift
    from syndicate.features.soccer.features.market_anchoring import _clamp
    from syndicate.features.soccer.features.team_names import match_team_name

    source_root = Path(opts["source_root"])
    try:
        base = ratings_as_of(league, date, source_root)
    except SystemExit as exc:
        return {"league": league, "date": date, "error": str(exc), "rows": []}
    rosters = player_rows(league, source_root)
    if not rosters:
        return {"league": league, "date": date, "error": "no player rows", "rows": []}

    names = list(base)
    anchored = {team: dict(rating) for team, rating in base.items()}
    applied = {}
    for index, fixture in enumerate(fixtures):
        target = targets.get(fixture["match_id"])
        if target is None:
            continue
        home_key = match_team_name(fixture["home_team"], names)
        away_key = match_team_name(fixture["away_team"], names)
        if home_key is None or away_key is None or home_key == away_key:
            continue
        shift = solve_market_rating_shift(
            home_rating=anchored[home_key], away_rating=anchored[away_key],
            market_home_win_probability=target,
            simulations=opts["solver_sims"], seed=1000 + index,
            max_iterations=opts["solver_iters"])
        delta = shift * opts["weight"]
        anchored[home_key] = {**anchored[home_key],
                              "attack_rating": round(_clamp(anchored[home_key]["attack_rating"] + delta, -0.35, 0.35), 4)}
        anchored[away_key] = {**anchored[away_key],
                              "attack_rating": round(_clamp(anchored[away_key]["attack_rating"] - delta, -0.35, 0.35), 4)}
        applied[fixture["match_id"]] = round(delta, 5)

    if not applied:
        return {"league": league, "date": date, "error": "no fixture got an anchor target", "rows": []}

    adapter = build_soccer_simulation_adapter(league)
    per_key: dict = {}
    for arm, ratings in (("base", base), ("anchored", anchored)):
        sim_input = build_soccer_simulation_input(
            league=league, date=date, fixtures=fixtures, ratings=ratings,
            player_rows=rosters, simulations=opts["sims"])
        output = adapter.simulate_props(sim_input)
        for row in output.player_outputs:
            key = f"{row.get('match_id')}|{fold(row.get('player_name'))}"
            # UNCONDITIONAL expected_shots -- see the module docstring, point 3.
            per_key.setdefault(key, {})[arm] = row.get("expected_shots")
    rows = [{"match_id": k.split("|", 1)[0], "player": k.split("|", 1)[1],
             "base": v["base"], "anchored": v["anchored"]}
            for k, v in per_key.items()
            if v.get("base") is not None and v.get("anchored") is not None]
    return {"league": league, "date": date, "error": None, "rows": rows,
            "applied": applied, "fixtures": len(fixtures)}


def espn_actuals(args):
    from syndicate.features.soccer.ingestion.espn_lineups import LEAGUE_ESPN_SLUGS
    from syndicate.features.soccer.ingestion.espn_shot_events import extract_shot_events
    league, match_id, cache_dir = args
    cache = Path(cache_dir) / f"{league}_{match_id}.json"
    try:
        if cache.exists():
            summary = json.loads(cache.read_text(encoding="utf-8"))
        else:
            url = (f"https://site.web.api.espn.com/apis/site/v2/sports/soccer/"
                   f"{LEAGUE_ESPN_SLUGS[league]}/summary?event={match_id}")
            request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(request, timeout=45) as handle:
                summary = json.loads(handle.read().decode("utf-8"))
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(summary), encoding="utf-8")
        events = extract_shot_events(summary, event_id=str(match_id))
    except Exception:
        return match_id, None
    shots: collections.Counter = collections.Counter()
    for event in events:
        who = fold(event.get("shooter_name") or event.get("player_name") or "")
        if who:
            shots[who] += 1
    return match_id, {"shots": dict(shots), "events": len(events)}


def grade(rows, actuals):
    """EVERY predicted player in a match with a healthy feed, `realized = 0`
    when absent. See the module docstring, point 3 -- filtering the zeros is
    selection on the dependent variable."""
    graded, dropped = [], 0
    for row in rows:
        got = actuals.get(row["match_id"])
        if not got or got["events"] == 0:
            dropped += 1              # no feed: unknowable, not zero
            continue
        realized = got["shots"].get(row["player"], 0)
        graded.append({**row, "realized": realized})
    return graded, dropped


def sign_test(wins: int, n: int) -> float:
    if n == 0:
        return 1.0
    tail = max(wins, n - wins)
    return min(1.0, sum(math.comb(n, k) for k in range(tail, n + 1)) / 2 ** n * 2)


def report(graded) -> dict:
    base_err = [abs(g["base"] - g["realized"]) for g in graded]
    anch_err = [abs(g["anchored"] - g["realized"]) for g in graded]
    diffs = [b - a for b, a in zip(base_err, anch_err)]
    n = len(diffs)
    wins = sum(1 for d in diffs if d > 0)

    per_match: dict = collections.defaultdict(list)
    for g, d in zip(graded, diffs):
        per_match[g["match_id"]].append(d)
    match_deltas = [stats.mean(v) for v in per_match.values()]
    m = len(match_deltas)
    m_wins = sum(1 for x in match_deltas if x > 0)
    m_sd = stats.pstdev(match_deltas) or 1e-9

    print("=" * 92)
    print("ANCHORED vs BASE on REALIZED SHOTS (paired, same player-match)")
    print(f"   rows {n}   base MAE {stats.mean(base_err):.5f}   anchored MAE {stats.mean(anch_err):.5f}")
    print(f"   difference {stats.mean(anch_err)-stats.mean(base_err):+.5f} shots per player-match "
          f"({(stats.mean(anch_err)-stats.mean(base_err))/max(stats.mean(base_err),1e-9)*100:+.3f}%)")
    print(f"   player-level sign test p={sign_test(wins, n):.4f}  "
          f"-- INFLATED, rows in a match share one anchor shift")
    print()
    print("MATCH-CLUSTERED (the unit of independence)")
    print(f"   matches {m}   anchored better in {m_wins}/{m}")
    print(f"   mean per-match delta {stats.mean(match_deltas):+.5f}   sd {m_sd:.5f}   "
          f"t {stats.mean(match_deltas)/(m_sd/math.sqrt(max(m,1))):+.2f}")
    print(f"   median per-match delta {stats.median(match_deltas):+.5f}")
    print(f"   sign test p={sign_test(m_wins, m):.4f}")
    print()
    print("   REPORT EFFECT SIZE FIRST. At this n a vanishing effect still reads")
    print("   p=0.0000; direction and magnitude are different findings.")
    return {"rows": n, "matches": m,
            "base_mae": stats.mean(base_err), "anchored_mae": stats.mean(anch_err),
            "paired_mean_improvement": stats.mean(diffs), "row_wins": wins,
            "row_sign_test_p_INFLATED": sign_test(wins, n),
            "match_mean_delta": stats.mean(match_deltas),
            "match_median_delta": stats.median(match_deltas),
            "match_sd": m_sd, "match_wins": m_wins,
            "match_sign_test_p": sign_test(m_wins, m),
            "match_deltas": match_deltas}


def build_jobs(args, opts):
    from syndicate.features.soccer.features.team_names import match_team_name
    recs_cache, odds_cache = Path(args.recs_cache), Path(args.odds_cache)
    pattern = re.compile(r"recommendations_(\d{4}-\d{2}-\d{2})\.json$")
    by_date: dict = collections.defaultdict(list)
    for path in sorted(recs_cache.glob("*")):
        found = pattern.search(path.name)
        if not found:
            continue
        date = found.group(1)
        if date >= args.before:
            continue                     # no outcomes yet
        league = next((lg for lg in args.leagues if f"_{lg}_" in path.name or f"{lg}_" in path.name), None)
        if league is None:
            continue
        by_date[date].append((league, path))

    jobs = []
    for date, entries in sorted(by_date.items()):
        h2h = devigged_h2h(odds_cache, date)
        if not h2h:
            continue                     # a date with no usable h2h anchors nothing
        for league, path in entries:
            try:
                rec = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            fixtures, targets = [], {}
            for match in (rec.get("matches") or []):
                matchup = match.get("matchup") or {}
                home, away = str(matchup.get("home_team") or ""), str(matchup.get("away_team") or "")
                mid = str(match.get("match_id") or match.get("event_id") or "")
                if not (home and away and mid):
                    continue
                hit = next((v for v in h2h.values()
                            if v["home_team"] == home and v["away_team"] == away), None)
                if hit is None:          # the two feeds do not share a naming convention
                    hit = next((v for v in h2h.values()
                                if match_team_name(home, [v["home_team"]])
                                and match_team_name(away, [v["away_team"]])), None)
                fixtures.append({"match_id": mid, "home_team": home, "away_team": away})
                if hit:
                    targets[mid] = float(hit["p_home"])
            if fixtures and targets:
                jobs.append((league, date, fixtures, targets, opts))
    return jobs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--odds-cache", required=True, help="dir of odds_history shards")
    parser.add_argument("--recs-cache", required=True, help="dir of recommendations_<date>.json")
    parser.add_argument("--source-root", default=str(REPO_ROOT / "data" / "soccer_source"))
    parser.add_argument("--espn-cache", default=str(REPO_ROOT / "reports" / "soccer_anchor_backtest" / "espn_cache"))
    parser.add_argument("--out", default=str(REPO_ROOT / "reports" / "soccer_anchor_backtest" / "anchor_vs_outcomes.json"))
    parser.add_argument("--weight", type=float, default=0.4)
    parser.add_argument("--simulations", type=int, default=400, help="matches build_soccer_artifacts' production value")
    parser.add_argument("--solver-simulations", type=int, default=100)
    parser.add_argument("--solver-iterations", type=int, default=5)
    parser.add_argument("--before", default="2026-09-02", help="grade only dates strictly before this")
    parser.add_argument("--leagues", default=",".join(DEFAULT_LEAGUES))
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--limit-units", type=int, default=None)
    args = parser.parse_args()
    args.leagues = [x.strip() for x in args.leagues.split(",") if x.strip()]

    opts = {"weight": args.weight, "sims": args.simulations,
            "solver_sims": args.solver_simulations, "solver_iters": args.solver_iterations,
            "source_root": args.source_root}

    started = time.perf_counter()
    jobs = build_jobs(args, opts)
    if args.limit_units:
        jobs = jobs[:args.limit_units]
    anchored_fixtures = sum(len(j[3]) for j in jobs)
    print(f"league-date units {len(jobs)}   fixtures with an anchor target {anchored_fixtures}   "
          f"({time.perf_counter()-started:.0f}s to assemble)", flush=True)
    if not jobs:
        print("no jobs -- check --odds-cache/--recs-cache are populated "
              "(fetch_prod_artifacts_paced.py) and that --before leaves past dates")
        return 1

    # Units run SERIALLY inside a worker, so the LONGEST unit sets the floor --
    # total work / worker count badly underestimates wall time (measured: a 45
    # min estimate against ~2 h actual).
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(run_unit, jobs, chunksize=1))
    errors = collections.Counter(r["error"] for r in results if r["error"])
    if errors:
        print(f"unit errors: {dict(errors)}", flush=True)
    rows = [r for res in results for r in res["rows"]]
    print(f"paired projection rows {len(rows)}   ({time.perf_counter()-started:.0f}s)", flush=True)

    wanted = sorted({(res["league"], r["match_id"]) for res in results for r in res["rows"]})
    print(f"fetching ESPN actuals for {len(wanted)} matches ...", flush=True)
    actuals = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        for mid, got in pool.map(espn_actuals, [(lg, mid, args.espn_cache) for lg, mid in wanted]):
            if got:
                actuals[mid] = got
    print(f"actuals for {len(actuals)}/{len(wanted)} matches", flush=True)

    graded, dropped = grade(rows, actuals)
    print(f"gradeable (player, match) rows {len(graded)}   dropped for no/empty feed {dropped}\n", flush=True)
    if not graded:
        print("NOTHING GRADEABLE -- the join failed. Do NOT read this as a null result.")
        return 2

    summary = report(graded)
    summary.update({"units": len(jobs), "anchored_fixtures": anchored_fixtures,
                    "weight": args.weight, "simulations": args.simulations,
                    "dropped_no_feed": dropped})
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2, default=float), encoding="utf-8")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
