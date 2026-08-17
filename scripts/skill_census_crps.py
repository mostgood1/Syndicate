"""CRPS skill census against CLIMATOLOGY, across sports. `#440` Phase 7.

THE QUESTION. 69 sport x market pairs ship a prediction and, as of the
2026-08-14 model audit, TWO had a backtest. This asks the cheapest useful
question of as many of them as the local mirror can answer:

    does this forecast beat CLIMATOLOGY -- the marginal distribution of the
    same quantity -- as a DISTRIBUTION?

    skill = 1 - CRPS_model / CRPS_climatology      > 0 means real skill

WHY CLIMATOLOGY AND NOT A CONSTANT. Scored 2026-08-17 on MLB pitcher outs, a
constant point prediction was used as the baseline and the verdict went into
`state.md`. That is a point test on a distributional model: a constant cannot
price `P(outs > 17.5)`, and MAE is blind to calibration and sharpness -- the
exact axis the finding lived on. `learnings.md` 2026-08-17 carries the rule.
This script only ever compares like with like.

SEGMENTATION IS NOT OPTIONAL. Climatology is computed WITHIN a segment
(e.g. NFL preseason separately from regular season). Pooling them would hand
the model credit for knowing that preseason scoring differs from regular
season -- which is not skill, it is a schedule lookup.

REFUSALS, deliberate and matching `projection_skill`'s existing convention:
  * a cell below `--min-n` reports `unmeasured`, never a number
  * a sport whose distribution or outcome is absent locally is reported as
    UNMEASURED WITH THE REASON, never silently dropped
  * coverage (dates, and the intersection) is printed BEFORE any score, per
    CLAUDE.md -- a census that rests on one date must say so

Usage:
  py -3 scripts/skill_census_crps.py
  py -3 scripts/skill_census_crps.py --sports nfl --min-n 30
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.model_scoring import crps_empirical, crps_normal  # noqa: E402

DATA = REPO_ROOT / "data"
PROJ_RE = re.compile(r"smartsim2_(preseason_)?projections_(\d{4})_wk(\d+)\.csv$", re.I)


# --------------------------------------------------------------------------
# observation record
# --------------------------------------------------------------------------
class Obs:
    __slots__ = ("sport", "market", "segment", "actual", "mean", "sigma", "samples",
                 "key", "leak")

    def __init__(self, sport, market, segment, actual, *, mean=None, sigma=None,
                 samples=None, key=None, leak=None):
        self.sport, self.market, self.segment = sport, market, segment
        self.actual, self.mean, self.sigma, self.samples, self.key = (
            actual, mean, sigma, samples, key)
        # None = point-in-time clean. A string = why this observation's forecast
        # saw its own outcome, carried on the RECORD so it cannot be lost when
        # cells are aggregated.
        self.leak = leak

    def model_crps(self) -> float | None:
        if self.samples:
            return crps_empirical(self.actual, self.samples)
        if self.mean is not None and self.sigma is not None:
            return crps_normal(self.actual, self.mean, self.sigma)
        return None


# --------------------------------------------------------------------------
# NFL / NCAAF -- smartsim2 projections (mean + stdev) x nflverse pbp finals
# --------------------------------------------------------------------------
def _nflverse_finals(seasons: set[int], sport: str) -> dict[str, tuple[float, float]]:
    """game_id -> (home_final, away_final), from the pbp truth files."""
    out: dict[str, tuple[float, float]] = {}
    base = DATA / f"{sport}_source" / "historical_truth"
    for season in sorted(seasons):
        path = base / f"play_by_play_{season}.csv.gz"
        if not path.is_file():
            continue
        try:
            with gzip.open(path, "rt", encoding="utf-8", errors="replace") as handle:
                for row in csv.DictReader(handle):
                    gid = (row.get("game_id") or "").strip()
                    if not gid:
                        continue
                    try:
                        home = float(row.get("total_home_score") or 0)
                        away = float(row.get("total_away_score") or 0)
                    except (TypeError, ValueError):
                        continue
                    prev = out.get(gid)
                    # the final score is the max reached in the game
                    if prev is None or (home + away) > (prev[0] + prev[1]):
                        out[gid] = (home, away)
        except Exception as exc:  # noqa: BLE001
            print(f"    [warn] {path.name}: {type(exc).__name__}: {exc}")
    return out


def _cfbd_finals(seasons: set[int], sport: str) -> dict[str, tuple[float, float]]:
    """game id -> (home_points, away_points), from CFBD `games_<season>.json.gz`.

    NCAAF truth is NOT nflverse. `_nflverse_finals` looks for
    `play_by_play_<season>.csv.gz` and found zero NCAAF matches, which the census
    correctly reported as UNMEASURED rather than as a skill of zero. CFBD ships a
    game-level file, so no play aggregation is needed: `homePoints`/`awayPoints`
    are the finals, and `id` is the same ESPN-style key the projections carry.

    Only `completed` games with both scores present are returned -- a scheduled
    or in-progress game must not enter a backtest as a 0-0 outcome.
    """
    out: dict[str, tuple[float, float]] = {}
    base = DATA / f"{sport}_source" / "historical_truth"
    for season in sorted(seasons):
        path = base / f"games_{season}.json.gz"
        if not path.is_file():
            continue
        try:
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                games = json.load(handle)
        except Exception as exc:  # noqa: BLE001
            print(f"    [warn] {path.name}: {type(exc).__name__}: {exc}")
            continue
        for game in games if isinstance(games, list) else []:
            if not game.get("completed"):
                continue
            home, away = game.get("homePoints"), game.get("awayPoints")
            if home is None or away is None:
                continue
            gid = str(game.get("id") or "").strip()
            if gid:
                try:
                    out[gid] = (float(home), float(away))
                except (TypeError, ValueError):
                    continue
    return out


_RATING_SEASON_RE = re.compile(r"season_(\d{4})")


def _leak_reason(rating_source: str, game_season: int) -> str | None:
    """Did this forecast's inputs include the season it is predicting?

    Measured 2026-08-17: NCAAF's 2025 projection files carry
    `rating_source=cfbd_ppa_season_2025` and `generated_at=2026-07-16` -- FULL
    2025 season PPA, computed after the season ended, used to predict 2025
    games. A week-11 game is therefore predicted using ratings that include that
    very game and every game after it.

    This is the same shape the 2026-08-14 model audit found in the soccer
    backtests ("a season-to-date aggregate recomputed from a current table") and
    the same one `plan_2026-08-14_models.md` D1 marked NOT CITABLE.

    The 2026 files show the CORRECT pattern for contrast:
    `cfbd_ppa_season_2025_fallback_for_2026` -- prior-season ratings, which is
    point-in-time safe.
    """
    match = _RATING_SEASON_RE.search(str(rating_source or ""))
    if not match:
        return None
    rating_season = int(match.group(1))
    if rating_season >= game_season:
        return (f"rating_source={rating_source} supplies season-{rating_season} ratings "
                f"to a season-{game_season} game (in-sample)")
    return None


def collect_football(sport: str) -> tuple[list[Obs], dict]:
    src = DATA / f"{sport}_source"
    proj_files = sorted(p for p in src.rglob("smartsim2_*projections_*.csv") if PROJ_RE.search(p.name))
    meta = {"projection_files": len(proj_files), "reason": None}
    if not proj_files:
        meta["reason"] = "no smartsim2 projection files in the local mirror"
        return [], meta

    rows = []
    seasons: set[int] = set()
    for path in proj_files:
        m = PROJ_RE.search(path.name)
        preseason, season = bool(m.group(1)), int(m.group(2))
        seasons.add(season)
        try:
            with path.open(encoding="utf-8", newline="") as handle:
                for row in csv.DictReader(handle):
                    row["_segment"] = "preseason" if preseason else "regular"
                    row["_season"] = season
                    rows.append(row)
        except Exception:  # noqa: BLE001
            continue

    # Truth format is per-sport: nflverse pbp CSV for NFL, CFBD game JSON for NCAAF.
    finals = _cfbd_finals(seasons, sport) if sport == "ncaaf" else _nflverse_finals(seasons, sport)
    meta["truth_source"] = "cfbd_games" if sport == "ncaaf" else "nflverse_pbp"
    meta["seasons"] = sorted(seasons)
    meta["projection_rows"] = len(rows)
    meta["truth_games"] = len(finals)

    out: list[Obs] = []
    joined = 0
    leaks: Counter = Counter()
    for row in rows:
        gid = (row.get("game_id") or "").strip()
        final = finals.get(gid)
        if final is None:
            continue
        joined += 1
        home, away = final
        seg = f"{row['_segment']}"
        leak = _leak_reason(row.get("rating_source", ""), int(row["_season"]))
        if leak:
            leaks[leak] += 1
        for market, actual, mean_key, sd_key in (
            ("margin", home - away, "margin_mean", "margin_stdev"),
            ("total", home + away, "total_mean", "total_stdev"),
        ):
            try:
                mean = float(row.get(mean_key))
                sigma = float(row.get(sd_key))
            except (TypeError, ValueError):
                continue
            if sigma <= 0:
                continue
            out.append(Obs(sport, market, seg, float(actual), mean=mean, sigma=sigma,
                           key=gid, leak=leak))
    meta["joined_games"] = joined
    if leaks:
        meta["leaked_rows"] = dict(leaks)
    if not out:
        meta["reason"] = (f"{len(rows)} projection rows and {len(finals)} truth games, "
                          "but ZERO game_id matches -- the two families do not overlap locally")
    return out, meta


# --------------------------------------------------------------------------
# NHL -- raw sim samples x boxscore actuals
# --------------------------------------------------------------------------
def collect_nhl() -> tuple[list[Obs], dict]:
    src = DATA / "nhl_source" / "data" / "processed"
    sample_files = sorted(src.glob("props_boxscores_sim_samples_*.csv"))
    meta = {"sample_files": len(sample_files), "reason": None}
    if not sample_files:
        meta["reason"] = "no props_boxscores_sim_samples_*.csv in the local mirror"
        return [], meta

    # WHAT THIS FILE ACTUALLY CONTAINS, measured rather than inferred from its
    # name: `props_boxscores_sim_samples_*.csv` is NOT player props. On
    # 2026-06-02 all 8,000 rows carry `player_id=0` (the TEAM aggregate) and the
    # only market is GOALS. So the scoreable quantity here is TEAM GOALS, with
    # 2,000 draws per team-game -- which is the ideal shape for `crps_empirical`,
    # just not the one the filename advertises.
    cache = DATA / "nhl_source" / "data" / "ingestion_cache"
    actuals: dict[tuple[str, str], float] = {}
    box_files = sorted(cache.glob("boxscore_*.json"))
    meta["boxscore_files"] = len(box_files)
    if not box_files:
        meta["reason"] = "sim samples exist but no boxscore_*.json actuals"
        return [], meta

    # The cache is keyed by NHL gamePk, not by date, so build (date, player, market).
    for path in box_files:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        date = str(payload.get("gameDate") or "")[:10]
        if not date:
            continue
        for team_key in ("homeTeam", "awayTeam"):
            team = payload.get(team_key) or {}
            score = team.get("score")
            if score is None:
                continue
            # The sim keys teams by FULL name ("Carolina Hurricanes"); the
            # boxscore splits it into placeName + commonName, each a
            # localisation dict. Rebuild it rather than matching on abbrev,
            # which the sim file does not carry.
            place = (team.get("placeName") or {}).get("default") or ""
            common = (team.get("commonName") or {}).get("default") or ""
            full = f"{place} {common}".strip()
            if not full:
                continue
            try:
                actuals[(date, full)] = float(score)
            except (TypeError, ValueError):
                continue
    meta["actual_team_games"] = len(actuals)
    if not actuals:
        meta["reason"] = (f"{len(box_files)} boxscore files parsed but no team scores extracted "
                          "-- the cached shape is not the one this reader expects")
        return [], meta

    # sim draws -> per (date, team) empirical distribution, FULL GAME only
    draws: dict[tuple[str, str], Counter] = defaultdict(Counter)
    for path in sample_files:
        try:
            with path.open(encoding="utf-8", newline="") as handle:
                for row in csv.DictReader(handle):
                    # period 0 = full game; 1-3 are per-period segments and
                    # would be scored against a full-game actual if kept.
                    if str(row.get("period") or "").strip() != "0":
                        continue
                    if str(row.get("market") or "").strip().upper() != "GOALS":
                        continue
                    key = (str(row.get("date") or "")[:10], str(row.get("team") or "").strip())
                    try:
                        draws[key][str(float(row.get("value")))] += 1
                    except (TypeError, ValueError):
                        continue
        except Exception:  # noqa: BLE001
            continue
    meta["sim_team_games"] = len(draws)
    meta["sim_dates"] = len({k[0] for k in draws})
    meta["actual_dates"] = len({k[0] for k in actuals})
    meta["date_intersection"] = len({k[0] for k in draws} & {k[0] for k in actuals})

    out: list[Obs] = []
    for key, pmf in draws.items():
        actual = actuals.get(key)
        if actual is None:
            continue
        out.append(Obs("nhl", "team_goals", "full_game", actual,
                       samples=dict(pmf), key=f"{key[0]}:{key[1]}"))
    meta["joined"] = len(out)
    if not out:
        meta["reason"] = (f"{len(draws)} simulated team-games and {len(actuals)} actual "
                          "team-games, but ZERO joined -- dates or team names do not overlap")
    return out, meta


# --------------------------------------------------------------------------
def score(observations: list[Obs], min_n: int) -> list[dict]:
    """Per (sport, market, segment): model CRPS vs climatology CRPS."""
    cells: dict[tuple[str, str, str], list[Obs]] = defaultdict(list)
    for obs in observations:
        cells[(obs.sport, obs.market, obs.segment)].append(obs)

    rows = []
    for (sport, market, segment), group in sorted(cells.items()):
        actuals = [o.actual for o in group]
        # CLIMATOLOGY IS WITHIN-SEGMENT, deliberately -- see module docstring.
        clim_pmf = {str(v): c for v, c in Counter(actuals).items()}
        clim = [s for s in (crps_empirical(a, clim_pmf) for a in actuals) if s is not None]
        model = [s for s in (o.model_crps() for o in group) if s is not None]
        n = min(len(clim), len(model))
        row = {"sport": sport, "market": market, "segment": segment, "n": n}
        # A cell whose forecasts saw their own outcomes is NOT a skill
        # measurement, however large n is. The number is still computed and
        # shown -- so it is visible what a naive backtest would have claimed --
        # but it is never labelled skill and never counted in the totals.
        leaked = {o.leak for o in group if o.leak}
        if leaked:
            row["leak"] = sorted(leaked)[0]
        if n < min_n:
            row["verdict"] = "unmeasured"
            row["reason"] = f"n={n} < min_n={min_n}"
        else:
            cm, cc = sum(model) / len(model), sum(clim) / len(clim)
            skill = (1.0 - cm / cc) if cc > 0 else 0.0
            # PAIRED interval, not two independent means. Every observation is
            # scored by BOTH forecasts, so the per-observation difference
            # removes the game-to-game variance that dominates CRPS and would
            # otherwise swamp a real few-percent effect. Normal approximation on
            # the paired differences; n here is in the hundreds.
            diffs = [c - m for c, m in zip(clim, model)]
            mean_d = sum(diffs) / len(diffs)
            var = sum((d - mean_d) ** 2 for d in diffs) / max(1, len(diffs) - 1)
            se = (var / len(diffs)) ** 0.5
            lo, hi = mean_d - 1.96 * se, mean_d + 1.96 * se
            row.update({"crps_model": cm, "crps_climatology": cc, "skill": skill,
                        "paired_mean_gain": mean_d, "paired_se": se,
                        "skill_lo": (lo / cc) if cc > 0 else 0.0,
                        "skill_hi": (hi / cc) if cc > 0 else 0.0,
                        "significant": lo > 0 or hi < 0})
            if leaked:
                row["verdict"] = "LEAKY — NOT CITABLE as skill"
            elif not row["significant"]:
                row["verdict"] = "INDISTINGUISHABLE from climatology"
            elif skill > 0:
                row["verdict"] = "BEATS climatology"
            else:
                row["verdict"] = "loses to climatology"
        rows.append(row)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sports", default="nfl,ncaaf,nhl")
    parser.add_argument("--min-n", type=int, default=30)
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args()
    wanted = {s.strip().lower() for s in args.sports.split(",") if s.strip()}

    print("=" * 100)
    print("CRPS SKILL CENSUS vs CLIMATOLOGY")
    print("=" * 100)
    print("\nCOVERAGE FIRST (a census that rests on one date must say so)\n")

    observations: list[Obs] = []
    unmeasured: list[tuple[str, str]] = []
    for sport in sorted(wanted):
        if sport in ("nfl", "ncaaf"):
            obs, meta = collect_football(sport)
        elif sport == "nhl":
            obs, meta = collect_nhl()
        else:
            obs, meta = [], {"reason": "no collector implemented for this sport"}
        print(f"  {sport:8s} {json.dumps({k: v for k, v in meta.items() if k != 'reason'})}")
        if meta.get("reason"):
            print(f"           UNMEASURED: {meta['reason']}")
            unmeasured.append((sport, meta["reason"]))
        observations.extend(obs)

    rows = score(observations, args.min_n)
    print(f"\nRESULTS   skill = 1 - CRPS_model / CRPS_climatology   (min_n={args.min_n})\n")
    header = f"  {'sport':7s} {'market':10s} {'segment':11s} {'n':>6s} {'CRPS mdl':>9s} {'CRPS clim':>10s} {'skill':>9s}  verdict"
    print(header)
    print("  " + "-" * (len(header) + 2))
    for r in rows:
        if r["verdict"] == "unmeasured":
            print(f"  {r['sport']:7s} {r['market']:10s} {r['segment']:11s} {r['n']:6d} "
                  f"{'—':>9s} {'—':>10s} {'—':>9s}  unmeasured ({r['reason']})")
        else:
            ci = f"[{r['skill_lo']:+.2%}, {r['skill_hi']:+.2%}]"
            print(f"  {r['sport']:7s} {r['market']:10s} {r['segment']:11s} {r['n']:6d} "
                  f"{r['crps_model']:9.4f} {r['crps_climatology']:10.4f} {r['skill']:+8.2%}  "
                  f"{r['verdict']}")
            print(f"  {'':7s} {'':10s} {'':11s} {'':6s} {'':9s} {'':10s} {'95% CI':>9s}  {ci}")

    scored = [r for r in rows if r["verdict"] != "unmeasured" and not r.get("leak")]
    leaky = [r for r in rows if r.get("leak")]
    beat = [r for r in scored if r.get("significant") and r["skill"] > 0]
    lose = [r for r in scored if r.get("significant") and r["skill"] <= 0]
    tied = [r for r in scored if not r.get("significant")]
    print(f"\n  cells scored {len(scored)}   BEAT {len(beat)}   lose {len(lose)}   "
          f"indistinguishable {len(tied)}   LEAKY {len(leaky)}   "
          f"unmeasured {len([r for r in rows if r['verdict'] == 'unmeasured'])}")
    for r in leaky:
        print(f"    LEAK  {r['sport']}/{r['market']}: {r['leak']}")
    print("  'indistinguishable' is a THIRD outcome, not a rounding of 'loses': a CI")
    print("  spanning zero means the sample cannot tell, which is not the same finding.")
    print("  Climatology is computed WITHIN segment and IN-SAMPLE, so it is a hard")
    print("  baseline: beating it is conservative, losing to it is not automatically damning.")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps({"rows": rows, "unmeasured": unmeasured}, indent=2),
                             encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
