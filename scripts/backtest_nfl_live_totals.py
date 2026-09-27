"""Cutoff-replay accuracy harness for NFL's LIVE rest-of-game distributions.

WHY THIS EXISTS, AND WHY IT COMES BEFORE THE FEATURE.

`nfl/live_resim.py::resim_live_game` now RETURNS `margin_dist` / `total_dist`
(it built them per sim and discarded them at the return, the same defect NCAAF
carried until 2026-09-26 and MLB until `0315f548`). `build_game_lens`
deliberately does NOT publish them, so `live_gameline_join` still refuses a live
NFL total or spread BY NAME. This harness is the ruler that a decision to open
that gate would have to be made on -- and nothing here opens it.

IT IS MODELLED ON `scripts/backtest_ncaaf_live_totals.py` AND ON THAT HARNESS'S
FAILURE. NCAAF's totals correction shipped and was withdrawn hours later: the
`shift +2.165` it was fitted on came from a grade run against an SP+ file
stamped `fetched_at 2026-09-05, verified=False`, 22 days stale. Re-run on the
ratings production actually reads, the measured bias was +0.171 with a
bootstrap-over-games CI of [-1.176, +1.538] -- the "defect" was the input, and
the harness had printed that provenance every run while nobody read it. So here
provenance is not a footnote: `--json` carries a per-week verdict, the text
output leads with it, and a run whose ratings cannot be placed in time SAYS SO.

WHAT IT DOES. Takes COMPLETED games, rebuilds the live state at the end of
Q1/Q2/Q3 -- where the score is exact and the clock is 0:00, so no play-by-play
is needed -- runs the SHIPPED `resim_live_game`, and scores its distribution
against the REAL final.

FOUR THINGS THAT ARE NFL-SPECIFIC AND CHANGE HOW THE NUMBER READS
-----------------------------------------------------------------
1. **THE FLAG.** `resim_live_game` refuses `nfl_live_resim_disabled` unless
   `SYNDICATE_NFL_LIVE_RESIM` is set, and it is absent from `render.yaml`, so
   the feature is OFF in production. The harness passes the flag through the
   function's own `env=` parameter and reports that it did. Grading a
   default-off producer is legitimate -- the grade is the precondition for
   turning it on -- but no reading here is a reading about live production.

2. **`UNINFORMATIVE_BAND` REFUSES MOST GAMES, AND THAT IS THE POINT.**
   `resim_live_game` returns a refusal, carrying NO distribution, whenever the
   produced P(home) lands in 0.35-0.65 -- measured 93.8% of NFL games. So the
   population that COULD be priced is only the confident tail, and grading that
   tail is grading what production would publish. `--band bypass` monkeypatches
   the module constant to measure what the band costs; those rows are labelled
   `band_bypassed` and are DIAGNOSTIC, never the headline.

3. **RATINGS COME FROM THE ARTIFACT THE TICK READS**, per week:
   `nfl_source/smartsim2_ratings_<season>_wk<week>.json`, written by
   `generate_smartsim2_nfl_projections.py` from the same play-by-play as the
   pregame projection so the two cannot drift. A team absent from it is
   REFUSED and COUNTED -- `build_live_lens_snapshot` substitutes `(0.0, 0.0)`
   there, which is the engine's average team and trips `degenerate_ratings`,
   and a silent exclusion would flatter the sample either way.

4. **NFL RATINGS BARELY SEPARATE TEAMS.** Lane `nfl-rating-units` measured
   across-game `margin_mean` stdev 2.16 against NCAAF's 15.37. That is the
   reason the band exists and the reason a thin sample here is likely to be
   thinner still after refusals.

THE HEADLINE IS THE WORST POWERED PREDICTED-PROBABILITY BUCKET, not the
aggregate. A model can be calibrated on average and badly wrong exactly where
it is confident, and the confident cells are the ones that get bet. A bucket
below `MIN_BUCKET_N` is REPORTED and excluded from the headline.

THE BASELINE IS DELIBERATELY HOSTILE. `frozen` = nobody scores again, i.e. the
total (or margin) already on the board at the cutoff. Anyone watching has it
for free.

EVERY CONFIDENCE INTERVAL IS BOOTSTRAPPED OVER GAMES, NOT ROWS. Three cutoffs
from one game share that game's outcome; resampling rows treats correlated
observations as independent and returns an interval far too tight.

Usage:
    py -3 scripts/backtest_nfl_live_totals.py --weeks 1,2,3 --ratings-dir <dir>
    py -3 scripts/backtest_nfl_live_totals.py --weeks 1,2 --market margin --json
"""

from __future__ import annotations

import argparse
import collections
import datetime as _dt
import json
import random
import statistics
import sys
import urllib.request
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# The SAME url shape `nfl/live_game_state._fetch_scoreboard` uses, and with the
# same header policy: that module's docstring says urllib's own default
# User-Agent is what ESPN accepts from Render, so a custom one here would be
# testing a different client than production's.
ESPN = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"

# End of each quarter. Q4 is excluded: there is no rest of game to simulate.
CUTOFF_PERIODS = (1, 2, 3)

BUCKETS = ((0.0, 0.1), (0.1, 0.2), (0.2, 0.3), (0.3, 0.4), (0.4, 0.5),
           (0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.0))

# Same floor NCAAF's harness uses. Below it a bucket is REPORTED but cannot be
# the headline: an n=3 cell producing the worst gap would read as the model's
# weakest point when it is noise.
MIN_BUCKET_N = 30

# NFL totals cluster tighter and lower than college ones (the 2026 board sits
# around 44), so the ladder is NFL's, not NCAAF's 45.5/52.5/59.5. Half-point
# lines, so a total can never push against them.
DEFAULT_TOTAL_LINES = "37.5,44.5,51.5"

# MARGINS ARE NOT GRADED ON A FIXED LADDER, AND NOT ON THE MODEL'S OWN CENTRE.
# NCAAF measured both wrong answers on 2026-09-27. A fixed +-10.5 ladder put
# 3,988 of 3,990 cells in one bucket (each game has its own centre, so every
# line sits below the whole distribution) and reported a meaningless worst gap
# of 0.0004. Anchoring on the model's median is worse, because it is
# STRUCTURALLY BLIND to the bias it was added to measure: a location shift moves
# the distribution and the anchor together, so every predicted probability is
# unchanged -- measured 0.1036 -> 0.1036 at a shift that demonstrably moved the
# signed bias.
#
# The anchor is the FROZEN MARGIN: the score differential already on the board
# at the cutoff. Observed, not modelled, so a location correction genuinely
# changes P(cover) -- which is also how a real live spread behaves, since it is
# quoted against the game in front of it and does not move when our estimator
# does.
MARGIN_LINE_OFFSETS = (-14.0, -7.0, -3.0, 0.0, 3.0, 7.0, 14.0)

# Passed to `resim_live_game(env=...)`. NOT written to `os.environ`: the harness
# must not leave a process-wide flag set for anything else that imports the
# module, and the function takes an explicit env for exactly this reason.
RESIM_ENV = {"SYNDICATE_NFL_LIVE_RESIM": "1"}


# ---------------------------------------------------------------------------
# inputs, and their provenance
# ---------------------------------------------------------------------------

def _fetch_week(season: int, week: int, *, seasontype: int = 2,
                timeout: float = 45.0) -> list[dict[str, Any]]:
    url = f"{ESPN}?seasontype={int(seasontype)}&week={int(week)}&year={int(season)}"
    with urllib.request.urlopen(urllib.request.Request(url), timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8")).get("events") or []


def completed_games(season: int, week: int, **kwargs: Any) -> list[dict[str, Any]]:
    """Finished games carrying a per-quarter linescore for BOTH sides.

    A game without four quarters of linescore cannot be cut off at a quarter
    boundary at all, so it is skipped here rather than half-scored later.

    Teams are the ESPN ABBREVIATIONS, because that is how the ratings artifact
    is keyed (`ARI`, `ATL`, ...) and how the tick looks them up. Joining on
    display names would miss every team and every game would come back
    "unrated", which is indistinguishable from a real refusal.
    """
    out: list[dict[str, Any]] = []
    for event in _fetch_week(season, week, **kwargs):
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

        def _line(c: Mapping[str, Any]) -> list[int]:
            return [int(float(x.get("value"))) for x in (c.get("linescores") or [])
                    if x.get("value") is not None]

        hl, al = _line(home), _line(away)
        if len(hl) < 4 or len(al) < 4:
            continue
        out.append({
            "event_id": str(event.get("id") or ""),
            "week": int(week),
            "kickoff": str(event.get("date") or ""),
            "date": str(event.get("date") or "")[:10],
            "home_team": str((home.get("team") or {}).get("abbreviation") or ""),
            "away_team": str((away.get("team") or {}).get("abbreviation") or ""),
            "home_line": hl,
            "away_line": al,
            "home_final": int(float(home.get("score") or 0)),
            "away_final": int(float(away.get("score") or 0)),
        })
    return out


def load_ratings_artifact(path: Path) -> tuple[dict[str, tuple[float, float]], dict[str, Any]]:
    """`({team: (offense, defense)}, provenance)` from a ratings artifact.

    READ THE WAY PRODUCTION READS IT -- `read_ratings_artifact` takes
    `teams[team]["offense"|"defense"]` and skips a malformed entry -- but unlike
    production this RAISES on an empty table instead of returning `{}`. The tick
    can afford to refuse every game by name; a grade that silently scored zero
    cells would report a pass.

    The provenance block is the part that matters. NCAAF's withdrawn correction
    was fitted on a file whose own stamp said it was 22 days old.
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    teams = payload.get("teams") if isinstance(payload, Mapping) else None
    if not isinstance(teams, Mapping) or not teams:
        raise ValueError(f"no teams table in {path}")
    out: dict[str, tuple[float, float]] = {}
    sources: dict[str, int] = {}
    for team, entry in teams.items():
        try:
            out[str(team)] = (float(entry["offense"]), float(entry["defense"]))
        except (KeyError, TypeError, ValueError):
            continue
        source = str((entry or {}).get("rating_source") or "unknown")
        sources[source] = sources.get(source, 0) + 1
    if not out:
        raise ValueError(f"ratings table in {path} had no usable (offense, defense) pairs")
    return out, {
        "path": path.name,
        "season": payload.get("season"),
        "week": payload.get("week"),
        # ABSENT PROVENANCE IS STALE, NOT FRESH. `_freshness` enforces that.
        "generated_at": payload.get("generated_at"),
        "teams": len(out),
        "rating_sources": sources,
    }


def _parse_iso(value: Any) -> _dt.datetime | None:
    try:
        parsed = _dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=_dt.timezone.utc)


def rating_freshness(provenance: Mapping[str, Any], *, kickoffs: list[str],
                     now: _dt.datetime | None = None) -> dict[str, Any]:
    """Age, and whether these ratings could have SEEN the games they grade.

    Two different questions, and NCAAF's incident was only the first of them:

    * `age_days` -- how stale the file is against now. Absent `generated_at`
      gives a verdict of `STALE_NO_PROVENANCE`, never a pass. This is the rule
      the withdrawn NCAAF correction broke.
    * `point_in_time` -- whether the file was written BEFORE the earliest game
      it is being used to grade. A file written afterwards has had those games'
      results folded into it, so a grade using it is measuring a model that saw
      the answer. The exception is recorded rather than assumed: a file whose
      every `rating_source` is `prior_season_fallback` cannot contain this
      season's results whatever its stamp says, so it is `CONTENT_CLEAN`.
    """
    stamp = _parse_iso(provenance.get("generated_at"))
    now = now or _dt.datetime.now(_dt.timezone.utc)
    earliest = min((k for k in (_parse_iso(x) for x in kickoffs) if k), default=None)
    sources = dict(provenance.get("rating_sources") or {})
    prior_only = bool(sources) and set(sources) == {"prior_season_fallback"}
    if stamp is None:
        verdict = "STALE_NO_PROVENANCE"
    elif earliest is None:
        verdict = "UNPLACEABLE_NO_KICKOFFS"
    elif stamp <= earliest:
        verdict = "POINT_IN_TIME"
    elif prior_only:
        verdict = "CONTENT_CLEAN_PRIOR_SEASON_ONLY"
    else:
        verdict = "LEAKAGE_RISK_RATINGS_POSTDATE_GAMES"
    return {
        "generated_at": provenance.get("generated_at"),
        "age_days": round((now - stamp).total_seconds() / 86400.0, 2) if stamp else None,
        "earliest_graded_kickoff": earliest.isoformat() if earliest else None,
        "rating_sources": sources,
        "verdict": verdict,
    }


# ESPN's ABBREVIATIONS ARE NOT THE RATINGS ARTIFACT'S. Measured on the first
# real run: `unrated_team:LAR` x2 and `unrated_team:WSH` x2, because the artifact
# is keyed the nflverse way (`LA`, `WAS`) and ESPN says `LAR`, `WSH`. Those were
# the only two of 32 that disagreed, which is exactly why this is a named map and
# not a fuzzy match -- a fuzzy match would also "resolve" a team that genuinely
# has no rating, and that must stay a counted refusal.
#
# THIS IS A HARNESS JOIN, NOT A PRODUCTION BUG. The tick joins the projection
# artifact's own team names to ratings written by the SAME generator run, so the
# two cannot disagree there. It is a hazard for anything that joins ESPN to this
# artifact, and it surfaced here only because the refusal was counted by name
# instead of being silently dropped.
ESPN_TO_RATINGS_ABBR = {"LAR": "LA", "WSH": "WAS"}


def ratings_pair(ratings: Mapping[str, Any], team: str) -> tuple[float, float] | None:
    """The pair, or None. NEVER a neutral substitute.

    `build_live_lens_snapshot` does `ratings.get(team, (0.0, 0.0))`, and 0.0/0.0
    is the engine's AVERAGE team: it yields a probability indistinguishable from
    a real one (it would in fact trip `degenerate_ratings`, but only because the
    OTHER side is also missing). Refusing and counting is the only honest read.
    """
    pair = ratings.get(str(team))
    if pair is None:
        pair = ratings.get(ESPN_TO_RATINGS_ABBR.get(str(team), ""))
    if isinstance(pair, (list, tuple)) and len(pair) >= 2:
        try:
            return float(pair[0]), float(pair[1])
        except (TypeError, ValueError):
            return None
    return None


# ---------------------------------------------------------------------------
# the replay
# ---------------------------------------------------------------------------

def _p_over(dist: Mapping[str, Any], line: float) -> float | None:
    """P(value > line | not a push), from the empirical histogram.

    The rule the segment join uses: STRICTLY greater, equality is a push and
    belongs to neither side. None when every draw lands on the line, and None
    when ANY key is unparseable -- silently skipping one reweights the
    distribution, which is a worse error than refusing the cell.
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


def margin_lines_for(row: Mapping[str, Any]) -> list[float]:
    """Half-point lines straddling the MODEL-INDEPENDENT frozen margin."""
    try:
        away_at, home_at = row["score_at_cutoff"]
        frozen = float(home_at) - float(away_at)
    except (KeyError, TypeError, ValueError):
        return []
    return [frozen + offset + 0.5 for offset in MARGIN_LINE_OFFSETS]


def replay_game(game: Mapping[str, Any], *, ratings: Mapping[str, Any],
                sims: int, band: str = "respect") -> tuple[list[dict[str, Any]], dict[str, int]]:
    """One completed game -> (rows, refusals_by_reason).

    CALLS THE SHIPPED FUNCTION. Re-implementing its loop would measure
    something production does not run -- the same class of error as grading
    against ratings production never used.
    """
    from syndicate.features.nfl import live_resim as lr

    home_pair = ratings_pair(ratings, game["home_team"])
    away_pair = ratings_pair(ratings, game["away_team"])
    if home_pair is None or away_pair is None:
        missing = [t for t, p in ((game["home_team"], home_pair), (game["away_team"], away_pair))
                   if p is None]
        return [], {f"unrated_team:{','.join(missing)}": 1}

    actual_total = game["home_final"] + game["away_final"]
    actual_margin = game["home_final"] - game["away_final"]
    rows: list[dict[str, Any]] = []
    refusals: dict[str, int] = {}

    # `--band bypass` widens the constant so `lo <= p <= hi` can never be true.
    # It is a monkeypatch of the module attribute the function reads, NOT an
    # edit to the module: `live_resim.py` is claimed by lane
    # nfl-live-resim-activation and this harness does not touch it. Every row
    # produced this way is stamped `band_bypassed`.
    original_band = lr.UNINFORMATIVE_BAND
    if band == "bypass":
        lr.UNINFORMATIVE_BAND = (2.0, 2.0)
    try:
        for period in CUTOFF_PERIODS:
            home_at = sum(game["home_line"][:period])
            away_at = sum(game["away_line"][:period])
            state = lr.NflLiveGameState(
                away_team=game["away_team"],
                home_team=game["home_team"],
                period=period,
                # The cutoff IS the quarter boundary: clock 0:00 of that period,
                # which the engine resumes from as the start of the next one.
                clock_seconds=0,
                home_score=home_at,
                away_score=away_at,
                possession_owner=None,
            )
            result = lr.resim_live_game(
                state,
                home_offense=home_pair[0], home_defense=home_pair[1],
                away_offense=away_pair[0], away_defense=away_pair[1],
                sims=sims, env=RESIM_ENV,
            )
            if not isinstance(result, dict):
                reason = getattr(result, "reason", "unknown_refusal")
                refusals[reason] = refusals.get(reason, 0) + 1
                continue
            rows.append({
                "event_id": game["event_id"],
                "week": game["week"],
                "date": game["date"],
                "matchup": f'{game["away_team"]} @ {game["home_team"]}',
                "cutoff_period": period,
                "score_at_cutoff": [away_at, home_at],
                "total_at_cutoff": home_at + away_at,
                "actual_total": actual_total,
                "actual_margin": actual_margin,
                "projected_total": result.get("total_mean"),
                "projected_margin": result.get("margin_mean"),
                "total_dist": result.get("total_dist") or {},
                "margin_dist": result.get("margin_dist") or {},
                "model_home_win_prob": result.get("model_home_win_prob"),
                "sims_run": result.get("sims_run"),
                "possession_unknown": bool(result.get("possession_marginalised")),
                "band_bypassed": band == "bypass",
            })
    finally:
        lr.UNINFORMATIVE_BAND = original_band
    return rows, refusals


# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------

def _signed_errors_by_game(rows: list[Mapping[str, Any]], *, market: str,
                           shift: float = 0.0) -> dict[str, list[float]]:
    key = "projected_margin" if market == "margin" else "projected_total"
    actual_key = "actual_margin" if market == "margin" else "actual_total"
    grouped: dict[str, list[float]] = collections.defaultdict(list)
    for row in rows:
        if row.get(key) is None:
            continue
        grouped[str(row.get("event_id"))].append(
            float(row[key]) + shift - float(row[actual_key]))
    return dict(grouped)


def bootstrap_bias_ci(rows: list[Mapping[str, Any]], *, market: str = "total",
                      shift: float = 0.0, iterations: int = 2000,
                      seed: int = 20260927, alpha: float = 0.05,
                      cluster: bool = True) -> list[float] | None:
    """Percentile CI for the signed bias, RESAMPLING GAMES.

    Three cutoffs from one game share that game's final score, so they are one
    observation wearing three hats. A row-level bootstrap treats them as three
    independent draws and returns an interval roughly sqrt(3) too tight, which
    is exactly how a bias that cannot be shown non-zero gets fitted into a
    shipped constant.

    `cluster=False` exists ONLY so a test can demonstrate that difference on a
    fixture. Nothing in the reported output uses it.
    """
    grouped = _signed_errors_by_game(rows, market=market, shift=shift)
    if len(grouped) < 2:
        return None
    keys = list(grouped)
    rng = random.Random(seed)
    if not cluster:
        flat_all = [e for errors in grouped.values() for e in errors]
        draws = []
        for _ in range(iterations):
            sample = [flat_all[rng.randrange(len(flat_all))] for _ in flat_all]
            draws.append(statistics.fmean(sample))
    else:
        draws = []
        for _ in range(iterations):
            picked = [grouped[keys[rng.randrange(len(keys))]] for _ in keys]
            flat = [e for errors in picked for e in errors]
            if not flat:
                continue
            draws.append(statistics.fmean(flat))
    if not draws:
        return None
    draws.sort()
    lo = draws[int((alpha / 2) * (len(draws) - 1))]
    hi = draws[int((1 - alpha / 2) * (len(draws) - 1))]
    return [round(lo, 4), round(hi, 4)]


def score(rows: list[dict[str, Any]], *, lines: list[float],
          market: str = "total", shift: float = 0.0) -> dict[str, Any]:
    """Calibration by predicted-probability bucket, plus the hostile baseline."""
    buckets: dict[tuple[float, float], list[tuple[float, int]]] = collections.defaultdict(list)
    abs_err_model: list[float] = []
    abs_err_frozen: list[float] = []
    # SIGNED, because MAE hides direction and direction is the whole question: a
    # distribution that is too LOW and one that is too NARROW produce the same
    # "realised exceeds predicted" pattern and need opposite fixes.
    # `signed = projected - actual`, so NEGATIVE means the model projects fewer
    # points (or a smaller home margin) than the game produced.
    signed_err_model: list[float] = []
    sim_spread: list[float] = []

    for row in rows:
        actual = row["actual_margin"] if market == "margin" else row["actual_total"]
        proj_key = "projected_margin" if market == "margin" else "projected_total"
        if row.get(proj_key) is not None:
            projected = float(row[proj_key]) + shift
            abs_err_model.append(abs(projected - actual))
            signed_err_model.append(projected - actual)
        dist = row.get("margin_dist" if market == "margin" else "total_dist") or {}
        if dist:
            try:
                pairs = [(float(k), int(v)) for k, v in dist.items()]
                n = sum(c for _, c in pairs)
                mu = sum(v * c for v, c in pairs) / n
                var = sum(c * (v - mu) ** 2 for v, c in pairs) / n
                sim_spread.append(var ** 0.5)
            except (TypeError, ValueError, ZeroDivisionError):
                pass
        # FROZEN: nobody scores again. Free to anyone watching the game.
        frozen = ((row["score_at_cutoff"][1] - row["score_at_cutoff"][0])
                  if market == "margin" else row["total_at_cutoff"])
        abs_err_frozen.append(abs(frozen - actual))

        dist_for_scoring = dict(dist)
        if shift:
            shifted: dict[str, int] = {}
            for raw, count in dist_for_scoring.items():
                try:
                    shifted[f"{float(raw) + shift:.4f}"] = int(count)
                except (TypeError, ValueError):
                    shifted = {}
                    break
            dist_for_scoring = shifted
        row_lines = margin_lines_for(row) if market == "margin" else lines
        for line in row_lines:
            prob = _p_over(dist_for_scoring, line)
            if prob is None:
                continue
            if actual == line:
                continue  # a push settles as a refund: evidence about neither side
            hit = 1 if actual > line else 0
            for lo, hi in BUCKETS:
                if lo <= prob < hi or (hi == 1.0 and prob == 1.0):
                    buckets[(lo, hi)].append((prob, hit))
                    break

    report = []
    worst_gap = None
    worst_bucket = None
    powered_cells = 0
    realised_above_predicted = 0
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
        if realised > predicted:
            realised_above_predicted += 1
        if powered:
            powered_cells += 1
            if worst_gap is None or gap > worst_gap:
                worst_gap, worst_bucket = gap, f"{lo:.1f}-{hi:.1f}"

    return {
        "market": market,
        "cutoff_rows": len(rows),
        "games": len({r["event_id"] for r in rows}),
        "scored_cells": sum(len(v) for v in buckets.values()),
        "band_bypassed_rows": sum(1 for r in rows if r.get("band_bypassed")),
        "possession_unknown_share": (
            round(sum(1 for r in rows if r.get("possession_unknown")) / len(rows), 4)
            if rows else None
        ),
        "mae_projection": round(statistics.fmean(abs_err_model), 3) if abs_err_model else None,
        "bias_projection": round(statistics.fmean(signed_err_model), 3) if signed_err_model else None,
        "bias_ci_over_games": bootstrap_bias_ci(rows, market=market, shift=shift),
        "sim_sd_mean": round(statistics.fmean(sim_spread), 3) if sim_spread else None,
        "residual_sd": round(statistics.pstdev(signed_err_model), 3) if len(signed_err_model) > 1 else None,
        "mae_frozen": round(statistics.fmean(abs_err_frozen), 3) if abs_err_frozen else None,
        "beats_frozen": (
            (statistics.fmean(abs_err_model) < statistics.fmean(abs_err_frozen))
            if abs_err_model and abs_err_frozen else None
        ),
        "worst_powered_bucket": worst_bucket,
        "worst_powered_bucket_gap": round(worst_gap, 4) if worst_gap is not None else None,
        "powered_buckets": powered_cells,
        # DIRECTION ACROSS BUCKETS. Realised above predicted in 8+ of 10 is a
        # systematic bias even when the worst gap looks acceptable.
        "buckets_reported": len(report),
        "buckets_realised_above_predicted": realised_above_predicted,
        "min_bucket_n": MIN_BUCKET_N,
        "calibration": report,
    }


# ---------------------------------------------------------------------------
# cli
# ---------------------------------------------------------------------------

def _ratings_by_week(directory: Path, season: int, weeks: list[int]):
    """`{week: (ratings, provenance)}` from the artifacts the tick reads."""
    loaded: dict[int, tuple[dict[str, tuple[float, float]], dict[str, Any]]] = {}
    errors: dict[str, str] = {}
    for week in weeks:
        path = directory / f"smartsim2_ratings_{season}_wk{week}.json"
        try:
            loaded[week] = load_ratings_artifact(path)
        except Exception as exc:  # noqa: BLE001
            errors[str(week)] = f"{type(exc).__name__}: {exc}"
    return loaded, errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--weeks", default="1,2,3", help="comma-separated NFL weeks")
    parser.add_argument("--seasontype", type=int, default=2)
    # PRODUCTION'S OWN DEFAULT, deliberately. `DEFAULT_SIMS = 120`; a higher
    # count would cut Monte Carlo noise and flatter a producer that does not run
    # at that count.
    parser.add_argument("--sims", type=int, default=None,
                        help="default: the module's DEFAULT_SIMS, i.e. production's")
    parser.add_argument("--ratings-dir", default=None,
                        help="directory of smartsim2_ratings_<season>_wk<week>.json "
                             "as fetched from production; provenance is reported")
    parser.add_argument("--lines", default=DEFAULT_TOTAL_LINES)
    parser.add_argument("--market", default="total", choices=("total", "margin"))
    parser.add_argument("--band", default="respect", choices=("respect", "bypass"),
                        help="respect = grade what production would publish; "
                             "bypass = diagnostic, measures what the band costs")
    parser.add_argument("--shift", type=float, default=0.0,
                        help="candidate location correction, applied to the projection "
                             "AND the histogram")
    parser.add_argument("--limit", type=int, default=None, help="max games, for a smoke run")
    parser.add_argument("--dump-rows", default=None,
                        help="save replay rows so variants are scored on the SAME draws")
    parser.add_argument("--score-only", default=None, help="score saved rows, no simulation")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    lines = [float(x) for x in str(args.lines).split(",") if x.strip()]

    # SIMULATE ONCE, SCORE MANY. Re-simulating per variant would make a
    # comparison of corrections partly a comparison of random seeds.
    if args.score_only:
        saved = json.loads(Path(args.score_only).read_text(encoding="utf-8"))
        result = score(saved["rows"], lines=lines, market=args.market, shift=args.shift)
        for key in ("weeks", "completed_games_found", "games_unrated_refused",
                    "refusals_by_reason", "ratings_provenance", "sims_per_cutoff",
                    "band", "flag_source"):
            result[key] = saved.get(key)
        result["calibration_shift"] = args.shift
        result["scored_from"] = args.score_only
        print(json.dumps(result, indent=1, sort_keys=True))
        return 0

    from syndicate.features.nfl.live_resim import DEFAULT_SIMS

    sims = int(args.sims) if args.sims else int(DEFAULT_SIMS)
    weeks = [int(w) for w in str(args.weeks).split(",") if w.strip()]

    if not args.ratings_dir:
        print("REFUSING: --ratings-dir is required.", flush=True)
        print("The tick rates a game from nfl_source/smartsim2_ratings_<season>_wk<week>.json; "
              "a grade run on anything else is not a reading about production, and a grade "
              "run on invented ratings is not a reading at all.", flush=True)
        return 3

    loaded, ratings_errors = _ratings_by_week(Path(args.ratings_dir), args.season, weeks)
    if not loaded:
        print(f"NO RATINGS ARTIFACTS READ: {ratings_errors}", flush=True)
        return 3

    seen: set[str] = set()
    games: list[dict[str, Any]] = []
    duplicates = 0
    for week in weeks:
        try:
            for game in completed_games(args.season, week, seasontype=args.seasontype):
                if game["event_id"] in seen:
                    duplicates += 1
                    continue
                seen.add(game["event_id"])
                games.append(game)
        except Exception as exc:  # noqa: BLE001
            print(f"  week {week}: fetch failed {type(exc).__name__}: {exc}", flush=True)
    if args.limit:
        games = games[: args.limit]

    rows: list[dict[str, Any]] = []
    refusals: dict[str, int] = {}
    unrated_games = 0
    weeks_without_ratings = 0
    for game in games:
        entry = loaded.get(int(game["week"]))
        if entry is None:
            weeks_without_ratings += 1
            refusals["no_ratings_artifact_for_week"] = refusals.get("no_ratings_artifact_for_week", 0) + 1
            continue
        game_rows, game_refusals = replay_game(
            game, ratings=entry[0], sims=sims, band=args.band)
        for reason, count in game_refusals.items():
            refusals[reason] = refusals.get(reason, 0) + count
        if not game_rows:
            unrated_games += 1
        rows.extend(game_rows)

    provenance = {}
    for week, (_, prov) in sorted(loaded.items()):
        kickoffs = [g["kickoff"] for g in games if int(g["week"]) == week]
        provenance[str(week)] = {**prov, **rating_freshness(prov, kickoffs=kickoffs)}

    # HOW MANY OF THE SCORED ROWS REST ON EACH PROVENANCE VERDICT. The whole
    # NCAAF lesson is that the provenance was printed and not read, and a
    # per-week table is still one join away from the number. This puts the split
    # in the same output as the headline: measured 2026-09-27, the totals bias
    # was -0.435 on the 36 LEAKAGE_RISK rows and -9.623 on the 9 clean ones, so
    # an aggregate bias here is a blend of two different measurements.
    rows_by_verdict: dict[str, int] = {}
    for row in rows:
        verdict = str((provenance.get(str(row.get("week"))) or {}).get("verdict")
                      or "NO_PROVENANCE_FOR_WEEK")
        rows_by_verdict[verdict] = rows_by_verdict.get(verdict, 0) + 1

    result = score(rows, lines=lines, market=args.market, shift=args.shift)
    result.update({
        "season": args.season,
        "weeks": weeks,
        "dates_covered": sorted({g["date"] for g in games}),
        "completed_games_found": len(games),
        "duplicate_events_skipped": duplicates,
        "games_with_no_scored_row": unrated_games,
        "games_in_weeks_without_ratings": weeks_without_ratings,
        "refusals_by_reason": refusals,
        "refused_cutoffs": sum(refusals.values()),
        "ratings_provenance": provenance,
        "scored_rows_by_ratings_verdict": rows_by_verdict,
        "ratings_errors": ratings_errors,
        "sims_per_cutoff": sims,
        "band": args.band,
        "lines_scored": lines if args.market == "total" else f"frozen margin {MARGIN_LINE_OFFSETS}",
        "flag_source": "passed via resim_live_game(env=...); SYNDICATE_NFL_LIVE_RESIM "
                       "is absent from render.yaml, so the feature is OFF in production",
        "calibration_shift": args.shift,
    })

    if args.dump_rows:
        Path(args.dump_rows).write_text(json.dumps({**result, "rows": rows}), encoding="utf-8")
        print(f"dumped {len(rows)} rows -> {args.dump_rows}", flush=True)

    if args.json:
        print(json.dumps(result, indent=1, sort_keys=True))
        return 0

    print(f"NFL LIVE {args.market.upper()} CUTOFF-REPLAY  season={args.season} "
          f"weeks={weeks} band={args.band} sims={sims}")
    print("  RATINGS PROVENANCE (read this before the number):")
    for week, prov in sorted(provenance.items()):
        print(f"    wk{week}: {prov['path']} generated_at={prov['generated_at']} "
              f"age={prov['age_days']}d teams={prov['teams']} "
              f"sources={prov['rating_sources']}")
        print(f"           verdict={prov['verdict']} "
              f"earliest_graded_kickoff={prov['earliest_graded_kickoff']}")
    print(f"  SCORED ROWS BY RATINGS VERDICT: {result['scored_rows_by_ratings_verdict']}")
    print(f"  games={result['completed_games_found']} scored_games={result['games']} "
          f"cutoff_rows={result['cutoff_rows']} scored_cells={result['scored_cells']} "
          f"dates={len(result['dates_covered'])}")
    print(f"  refused cutoffs={result['refused_cutoffs']} {result['refusals_by_reason']}")
    print(f"  MAE projection {result['mae_projection']} vs FROZEN {result['mae_frozen']}  "
          f"beats_frozen={result['beats_frozen']}")
    print(f"  signed bias {result['bias_projection']} "
          f"CI(bootstrap over games) {result['bias_ci_over_games']}  "
          f"sim_sd {result['sim_sd_mean']}  residual_sd {result['residual_sd']}")
    print(f"  WORST POWERED BUCKET {result['worst_powered_bucket']} "
          f"gap={result['worst_powered_bucket_gap']} "
          f"(powered buckets {result['powered_buckets']}/{result['buckets_reported']}, "
          f"n>={MIN_BUCKET_N})")
    print(f"  realised above predicted in {result['buckets_realised_above_predicted']} "
          f"of {result['buckets_reported']} reported buckets")
    print(f"  {'bucket':10s} {'n':>6s} {'pred':>8s} {'real':>8s} {'gap':>8s}  powered")
    for cell in result["calibration"]:
        print(f"  {cell['bucket']:10s} {cell['n']:>6d} {cell['predicted']:>8.4f} "
              f"{cell['realised']:>8.4f} {cell['gap']:>8.4f}  {cell['powered']}")
    print()
    print("A grade is not a decision, and an UNDERPOWERED grade is not a pass.")
    print(f"`#499`'s precedent was a MEASURED worst-bucket 0.150 over 249 games / "
          f"23,712 samples. This run rests on {result['games']} games and "
          f"{result['scored_cells']} cells.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
