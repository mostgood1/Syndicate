"""Cutoff-replay accuracy harness for NCAAF's LIVE rest-of-game distributions.

WHY THIS EXISTS, AND WHY IT COMES BEFORE THE FEATURE.

`ncaaf/live_resim.py` says in terms that it will not publish `marginDist` /
`totalRunsDist`, "though this re-sim has them in hand", because
`live_gameline_join` would price totals and spreads off them the moment they
appeared and **no NCAAF live totals estimator has ever been graded**. `#499` is
the precedent in the other direction: WNBA totals became priceable only after a
249-game / 23,712-sample backtest produced a measured worst-bucket 0.150.

Measured on the served board 2026-09-26T21:28Z, mid-slate, that gate costs:

    19 live games, 1,743 rows, 1,174 projected, **8 with an edge (0%)**
    172 rows withheld `live_resim_published_no_distribution_for_this_market`
        (91 full/spreads, 81 full/totals)

So NCAAF produces essentially no live edges. The fix is NOT to publish the
distribution -- that is a one-line change that opens pricing on the strength of
a sim count alone. The fix is to GRADE the estimator, and this is the ruler.

WHAT IT DOES. Takes COMPLETED games, rebuilds the live state at end of Q1/Q2/Q3
-- where the score is known exactly and the clock is 0:00, so no play-by-play is
needed -- runs the SHIPPED `resim_live_game`, and scores its distribution
against the REAL final.

IT GRADES THE SHIPPED FUNCTION, NOT A COPY. `resim_live_game` collapsed its
draws to means; it now returns `total_dist` / `margin_dist` as well, and
`build_game_lens` still constructs its lane field by field so those keys reach
no lens and no pricer. Re-implementing the sim loop here would measure something
production does not run -- the same error as scoring against ratings production
never used.

RATINGS ARE THE PRODUCTION ONES, AND A FALLBACK IS RECORDED. The worker rates a
game through `load_sp_ratings` -> `sp_league_means` -> `sp_offense_defense_rating`,
and `_ratings_for` refuses an unrated side rather than substituting 0.0, which
is the engine's AVERAGE team. This harness refuses the same way and COUNTS the
refusals, because an FBS-vs-FCS fixture excluded silently would flatter the
sample.

THE BASELINE IS DELIBERATELY HOSTILE. `frozen` = assume nobody scores again,
i.e. the total already on the board at the cutoff. Anyone watching has it for
free, so a distribution that cannot beat it is not adding anything. Reported
side by side, never as a footnote.

THE HEADLINE NUMBER IS THE WORST PREDICTED-PROBABILITY BUCKET GAP, not the
aggregate and not a per-quarter average. A model can be well calibrated on
average while being badly wrong exactly where it is confident, and it is the
confident cells that get bet.

A KNOWN HAZARD, REPORTED RATHER THAN HIDDEN: when possession is unknown the
re-sim runs two plans (home/away at field position 25) and POOLS the draws. A
pooled mixture is wider than either component, so calibration measured over a
sample dominated by unknown-possession states is not the same reading as one
taken with possession known. The share is in the output.

Usage:
    py -3 scripts/backtest_ncaaf_live_totals.py --window 20260901-20260925 --json
    py -3 scripts/backtest_ncaaf_live_totals.py --dates 2026-09-20,2026-09-13
"""

from __future__ import annotations

import argparse
import collections
import json
import statistics
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

ESPN = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard"

# End of each quarter. The score is exact and the clock is 0:00, so no
# play-by-play is needed -- which is what makes a powered sample reachable from
# the scoreboard alone. Q4 is excluded: there is no rest of game to simulate.
CUTOFF_PERIODS = (1, 2, 3)

# Calibration buckets over the PREDICTED probability.
BUCKETS = ((0.0, 0.1), (0.1, 0.2), (0.2, 0.3), (0.3, 0.4), (0.4, 0.5),
           (0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.0))

# A cell needs enough samples for a frequency to mean anything. Below this the
# bucket is REPORTED but excluded from the worst-gap headline, and the exclusion
# is stated -- an unpowered bucket producing the worst gap would otherwise read
# as the model's weakest point when it is just noise.
MIN_BUCKET_N = 30


def _fetch_scoreboard(date_str: str, *, timeout: float) -> list[dict[str, Any]]:
    url = f"{ESPN}?{urllib.parse.urlencode({'dates': date_str.replace('-', ''), 'limit': 400})}"
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode()).get("events") or []


def completed_games(date_str: str, *, timeout: float = 45.0) -> list[dict[str, Any]]:
    """Finished games carrying a per-quarter linescore for BOTH sides.

    A game without linescores cannot be cut off at a quarter boundary at all, so
    it is skipped here rather than half-scored later.
    """
    out: list[dict[str, Any]] = []
    for event in _fetch_scoreboard(date_str, timeout=timeout):
        competitions = event.get("competitions") or []
        if not competitions:
            continue
        comp = competitions[0]
        status = ((comp.get("status") or {}).get("type") or {})
        if not status.get("completed"):
            continue
        home = away = None
        for competitor in comp.get("competitors") or []:
            side = str(competitor.get("homeAway") or "")
            if side == "home":
                home = competitor
            elif side == "away":
                away = competitor
        if not home or not away:
            continue
        def _line(c):
            return [int(float(x.get("value"))) for x in (c.get("linescores") or [])
                    if x.get("value") is not None]
        hl, al = _line(home), _line(away)
        if len(hl) < 4 or len(al) < 4:
            continue  # no quarter detail, or a shortened game
        out.append({
            "event_id": str(event.get("id") or ""),
            "date": date_str,
            "home_team": str((home.get("team") or {}).get("location") or ""),
            "away_team": str((away.get("team") or {}).get("location") or ""),
            "home_line": hl,
            "away_line": al,
            "home_final": int(float(home.get("score") or 0)),
            "away_final": int(float(away.get("score") or 0)),
        })
    return out


def _p_over(dist: dict[str, int], line: float) -> float | None:
    """P(total > line | not a push), from the empirical histogram.

    Same rule the segment join uses: STRICTLY greater, equality is a push and
    belongs in neither side. None when every draw lands on the line.
    """
    over = under = 0
    for raw, count in dist.items():
        try:
            value, n = float(raw), int(count)
        except (TypeError, ValueError):
            return None
        if value > line:
            over += n
        elif value < line:
            under += n
    decided = over + under
    return (over / decided) if decided else None


def _ratings_from_file(path: Path):
    """`{team: [offense, defense]}` from a saved ratings file.

    THE SAME ESCAPE HATCH SOCCER'S HARNESS HAS, and for the same reason: the
    live path needs a CFBD key, which a grading run may not have, and a grade
    that cannot be run is not a grade. What it must NEVER do is invent ratings
    -- 0.0 is the engine's AVERAGE team, so a substituted rating produces a
    probability indistinguishable from a real one. The file's provenance is
    reported in the output so a reading taken this way is never mistaken for one
    taken from production's own load.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    table = raw.get("ratings") if isinstance(raw, dict) and "ratings" in raw else raw
    if not isinstance(table, dict) or not table:
        raise ValueError("no ratings table in the file")
    # KEYED THE WAY PRODUCTION KEYS IT. `sp_offense_defense_rating` looks up
    # `sp_index.get(norm(team))`, so a file keyed on raw names matches nothing
    # and every game comes back "unrated" -- which reads exactly like an
    # FBS-vs-FCS refusal and would have quietly emptied the sample.
    from scripts.generate_smartsim2_ncaaf_projections import norm

    out: dict[str, tuple[float, float]] = {}
    for team, pair in table.items():
        if isinstance(pair, (list, tuple)) and len(pair) >= 2:
            out[norm(str(team))] = (float(pair[0]), float(pair[1]))
        elif isinstance(pair, dict) and "offense" in pair and "defense" in pair:
            out[norm(str(team))] = (float(pair["offense"]), float(pair["defense"]))
    if not out:
        raise ValueError("ratings table had no usable (offense, defense) pairs")
    return out


def _ratings_index(season: int):
    """Production's own ratings path, or None with the reason recorded."""
    try:
        from scripts.generate_smartsim2_ncaaf_projections import (
            load_sp_ratings,
            sp_league_means,
        )

        sp_index = load_sp_ratings(season)
        return sp_index, sp_league_means(sp_index), None
    except Exception as exc:  # noqa: BLE001
        return None, None, f"{type(exc).__name__}: {exc}"


def replay_game(game: dict[str, Any], *, sp_index, means, sims: int) -> list[dict[str, Any]]:
    """One completed game -> a row per cutoff, or [] when it cannot be rated."""
    from scripts.generate_smartsim2_ncaaf_projections import sp_offense_defense_rating
    from syndicate.features.ncaaf.live_resim import NcaafLiveGameState, resim_live_game

    home_pair = sp_offense_defense_rating(game["home_team"], sp_index, means)
    away_pair = sp_offense_defense_rating(game["away_team"], sp_index, means)
    if home_pair is None or away_pair is None:
        # The same refusal production makes. Counted by the caller.
        return []
    (home_off, home_def) = home_pair
    (away_off, away_def) = away_pair

    actual_total = game["home_final"] + game["away_final"]
    actual_margin = game["home_final"] - game["away_final"]
    rows: list[dict[str, Any]] = []
    for period in CUTOFF_PERIODS:
        home_at = sum(game["home_line"][:period])
        away_at = sum(game["away_line"][:period])
        state = NcaafLiveGameState(
            home_team=game["home_team"],
            away_team=game["away_team"],
            period=period,
            clock_seconds=0,
            home_score=home_at,
            away_score=away_at,
            possession_owner=None,
            as_of=game["date"],
        )
        result = resim_live_game(
            state,
            home_offense=home_off,
            home_defense=home_def,
            away_offense=away_off,
            away_defense=away_def,
            sims=sims,
        )
        if not isinstance(result, dict):
            continue
        rows.append({
            "event_id": game["event_id"],
            "date": game["date"],
            "matchup": f'{game["away_team"]} @ {game["home_team"]}',
            "cutoff_period": period,
            "score_at_cutoff": [away_at, home_at],
            "total_at_cutoff": home_at + away_at,
            "actual_total": actual_total,
            "actual_margin": actual_margin,
            "projected_total": result.get("total_mean"),
            "projected_margin": result.get("home_margin_mean"),
            "total_dist": result.get("total_dist") or {},
            "sims_run": result.get("sims_run"),
            "possession_unknown": bool(result.get("possession_unknown")),
        })
    return rows


def score(rows: list[dict[str, Any]], *, lines: list[float]) -> dict[str, Any]:
    """Calibration by predicted-probability bucket, plus the hostile baseline."""
    buckets: dict[tuple[float, float], list[tuple[float, int]]] = collections.defaultdict(list)
    abs_err_model: list[float] = []
    abs_err_frozen: list[float] = []

    for row in rows:
        actual = row["actual_total"]
        if row.get("projected_total") is not None:
            abs_err_model.append(abs(float(row["projected_total"]) - actual))
        # FROZEN: nobody scores again. Free to anyone watching.
        abs_err_frozen.append(abs(row["total_at_cutoff"] - actual))
        for line in lines:
            prob = _p_over(row["total_dist"], line)
            if prob is None:
                continue
            if actual == line:
                continue  # a push is not an outcome to be scored
            hit = 1 if actual > line else 0
            for lo, hi in BUCKETS:
                if lo <= prob < hi or (hi == 1.0 and prob == 1.0):
                    buckets[(lo, hi)].append((prob, hit))
                    break

    report = []
    worst_gap = None
    worst_bucket = None
    for lo, hi in BUCKETS:
        cell = buckets.get((lo, hi)) or []
        if not cell:
            continue
        predicted = statistics.fmean(p for p, _ in cell)
        realised = statistics.fmean(h for _, h in cell)
        gap = abs(predicted - realised)
        powered = len(cell) >= MIN_BUCKET_N
        report.append({
            "bucket": f"{lo:.1f}-{hi:.1f}", "n": len(cell),
            "predicted": round(predicted, 4), "realised": round(realised, 4),
            "gap": round(gap, 4), "powered": powered,
        })
        if powered and (worst_gap is None or gap > worst_gap):
            worst_gap, worst_bucket = gap, f"{lo:.1f}-{hi:.1f}"

    return {
        "cutoff_rows": len(rows),
        "games": len({r["event_id"] for r in rows}),
        "possession_unknown_share": (
            round(sum(1 for r in rows if r["possession_unknown"]) / len(rows), 4) if rows else None
        ),
        "mae_projection": round(statistics.fmean(abs_err_model), 3) if abs_err_model else None,
        "mae_frozen": round(statistics.fmean(abs_err_frozen), 3) if abs_err_frozen else None,
        "beats_frozen": (
            (statistics.fmean(abs_err_model) < statistics.fmean(abs_err_frozen))
            if abs_err_model and abs_err_frozen else None
        ),
        "worst_powered_bucket": worst_bucket,
        "worst_powered_bucket_gap": round(worst_gap, 4) if worst_gap is not None else None,
        "min_bucket_n": MIN_BUCKET_N,
        "calibration": report,
    }


def _dates(args) -> list[str]:
    if args.dates:
        return [d.strip() for d in args.dates.split(",") if d.strip()]
    if args.window:
        import datetime

        start, _, end = args.window.partition("-")
        d0 = datetime.date.fromisoformat(f"{start[:4]}-{start[4:6]}-{start[6:8]}")
        d1 = datetime.date.fromisoformat(f"{end[:4]}-{end[4:6]}-{end[6:8]}")
        out = []
        while d0 <= d1:
            out.append(d0.isoformat())
            d0 += datetime.timedelta(days=1)
        return out
    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--window", default=None, help="YYYYMMDD-YYYYMMDD")
    parser.add_argument("--dates", default=None, help="comma-separated ISO dates")
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--sims", type=int, default=300)
    parser.add_argument("--lines", default="45.5,52.5,59.5")
    parser.add_argument("--limit", type=int, default=None, help="max games, for a smoke run")
    parser.add_argument("--ratings-file", default=None,
                        help="JSON {team: [offense, defense]}; provenance is reported")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    dates = _dates(args)
    if not dates:
        print("give --window or --dates", flush=True)
        return 2

    ratings_provenance = "production sp_offense_defense_rating"
    if args.ratings_file:
        try:
            from scripts.generate_smartsim2_ncaaf_projections import sp_league_means

            sp_index = _ratings_from_file(Path(args.ratings_file))
            means, ratings_error = sp_league_means(sp_index), None
            ratings_provenance = f"file:{args.ratings_file}"
        except Exception as exc:  # noqa: BLE001
            sp_index = means = None
            ratings_error = f"{type(exc).__name__}: {exc}"
    else:
        sp_index, means, ratings_error = _ratings_index(args.season)
    if sp_index is None:
        print(f"NO PRODUCTION RATINGS: {ratings_error}", flush=True)
        print("Refusing to score: a grade produced under different ratings than "
              "production ran is not a reading about production.", flush=True)
        return 3

    games: list[dict[str, Any]] = []
    for date_str in dates:
        try:
            games.extend(completed_games(date_str))
        except Exception as exc:  # noqa: BLE001
            print(f"  {date_str}: fetch failed {type(exc).__name__}", flush=True)
    if args.limit:
        games = games[: args.limit]

    rows: list[dict[str, Any]] = []
    unrated = 0
    for game in games:
        replayed = replay_game(game, sp_index=sp_index, means=means, sims=args.sims)
        if not replayed:
            unrated += 1
        rows.extend(replayed)

    lines = [float(x) for x in str(args.lines).split(",") if x.strip()]
    result = score(rows, lines=lines)
    result["dates"] = len(dates)
    result["completed_games_found"] = len(games)
    result["games_unrated_refused"] = unrated
    result["sims_per_cutoff"] = args.sims
    result["lines_scored"] = lines
    result["ratings_source"] = ratings_provenance

    if args.json:
        print(json.dumps(result, indent=1, sort_keys=True))
        return 0

    print(f"NCAAF LIVE TOTALS CUTOFF-REPLAY  dates={len(dates)} "
          f"games={result['games']} cutoff_rows={result['cutoff_rows']} "
          f"unrated_refused={unrated}")
    print(f"  possession unknown on {result['possession_unknown_share']} of rows "
          f"(pooled two-plan draws -- widens the mixture)")
    print(f"  MAE projection {result['mae_projection']}  vs FROZEN {result['mae_frozen']}  "
          f"beats_frozen={result['beats_frozen']}")
    print(f"  WORST POWERED BUCKET {result['worst_powered_bucket']} "
          f"gap={result['worst_powered_bucket_gap']}  (n>={MIN_BUCKET_N})")
    print(f"  {'bucket':10s} {'n':>6s} {'pred':>8s} {'real':>8s} {'gap':>8s}  powered")
    for cell in result["calibration"]:
        print(f"  {cell['bucket']:10s} {cell['n']:>6d} {cell['predicted']:>8.4f} "
              f"{cell['realised']:>8.4f} {cell['gap']:>8.4f}  {cell['powered']}")
    print()
    print("A grade is not a decision. `#499`'s bar was a MEASURED worst-bucket")
    print("0.150 over 249 games; publishing NCAAF's distribution is a separate,")
    print("deliberate edit to `build_game_lens` made on the strength of this.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
