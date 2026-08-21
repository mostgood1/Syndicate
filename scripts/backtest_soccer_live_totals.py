"""Cutoff-replay accuracy harness for soccer's LIVE totals projection.

WHY THIS EXISTS. `project_live_match` resumes a Monte Carlo from the current
half/clock/score and now publishes a full scoreline distribution
(`scoreline_probabilities`), so the live board can price any total. Nothing
measured whether those numbers are any good. A live tier with no accuracy
harness is exactly the shape this repo has paid for before: a projection that
renders, is believed, and has never been scored.

WHAT IT DOES. Takes a COMPLETED match, replays it at a series of cutoffs using
`build_live_state(..., as_of_seconds=T)` -- which exists precisely for this and
says so -- projects from each, and scores the projection against the REAL final
total. One fetch, N cutoffs.

WHY IT IS THE PREREQUISITE FOR THE FOTMOB WORK. The xG question is "does
in-match shot quality beat shot volume", and that is a COMPARISON on identical
cutoffs. Without this harness there is no way to answer it that is not just an
opinion about a plausible feature. Build the ruler before the thing it measures.

THE BASELINE IS DELIBERATELY HOSTILE. `frozen` = assume no further goals, i.e.
the scoreline at the cutoff. It is trivially available to anyone watching, so a
projection that cannot beat it late in a match is not adding anything. Reported
side by side rather than as a footnote, because a MAE with nothing to compare
against reads as good or bad depending on the reader's priors.

RATINGS ARE THE PRODUCTION ONES WHERE SUPPLIED. `--ratings-file` takes a
`recommendations_<date>.json`, whose `adapter_metadata.{home,away}_rating_detail`
carries the exact `attack_rating`/`defense_rating` the live sim used. Falling
back to neutral (0.0) is allowed but is RECORDED IN THE OUTPUT, because a score
produced under different ratings than production ran is not a reading about
production.

Usage:
    py -3 scripts/backtest_soccer_live_totals.py --league la_liga \
        --event-id 401882908 --cutoffs 15,30,45,60,75 --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.soccer.features.live_lens import project_live_match
from syndicate.features.soccer.ingestion.espn_live_state import build_live_state
from syndicate.features.soccer.ingestion.espn_lineups import fetch_match_summary

# Lines to score P(over) at. 2.5 is the market's default; 1.5 and 3.5 matter
# because a live total moves off 2.5 the moment anyone scores, which is the
# whole reason the distribution was published.
DEFAULT_LINES = (1.5, 2.5, 3.5)
_NEUTRAL = {"attack_rating": 0.0, "defense_rating": 0.0}


def _p_over(scorelines: dict[str, float], line: float) -> float | None:
    """P(total > line) from the sim's own scoreline distribution."""
    if not scorelines:
        return None
    total = 0.0
    mass = 0.0
    for key, prob in scorelines.items():
        parts = str(key).split("-")
        if len(parts) != 2:
            continue
        try:
            goals = int(parts[0]) + int(parts[1])
        except (TypeError, ValueError):
            continue
        mass += float(prob)
        if goals > line:
            total += float(prob)
    if not 0.99 <= mass <= 1.01:
        return None
    return total


def _ratings_from_artifact(path: Path, home_team: str) -> tuple[dict, dict, str]:
    """The ratings PRODUCTION used, from a recommendations artifact."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return dict(_NEUTRAL), dict(_NEUTRAL), f"neutral (artifact unreadable: {type(exc).__name__})"
    for match in payload.get("matches") or []:
        matchup = match.get("matchup") or {}
        if str(matchup.get("home_team") or "") != home_team:
            continue
        meta = match.get("adapter_metadata") or {}
        home = meta.get("home_rating_detail") or {}
        away = meta.get("away_rating_detail") or {}
        if home and away:
            return dict(home), dict(away), f"production artifact {path.name}"
    return dict(_NEUTRAL), dict(_NEUTRAL), f"neutral (no matching fixture in {path.name})"


def replay(
    league: str,
    event_id: str,
    *,
    cutoffs: list[int],
    simulations: int,
    ratings_file: Path | None,
    lines: tuple[float, ...] = DEFAULT_LINES,
) -> dict[str, Any]:
    summary = fetch_match_summary(league, event_id)

    # FULL match first: this is the ground truth the cutoffs are scored against.
    final_state = build_live_state(summary, event_id=event_id)
    actual_home = int(final_state["score_home"])
    actual_away = int(final_state["score_away"])
    actual_total = actual_home + actual_away

    home_team = final_state["home_team"]
    away_team = final_state["away_team"]
    if ratings_file is not None:
        home_rating, away_rating, ratings_source = _ratings_from_artifact(ratings_file, home_team)
    else:
        home_rating, away_rating, ratings_source = dict(_NEUTRAL), dict(_NEUTRAL), "neutral (none supplied)"

    rows: list[dict[str, Any]] = []
    for minute in cutoffs:
        state = build_live_state(summary, event_id=event_id, as_of_seconds=minute * 60.0)
        goals_so_far = int(state["score_home"]) + int(state["score_away"])
        projection = project_live_match(
            state, home_rating=home_rating, away_rating=away_rating, simulations=simulations
        )
        scorelines = projection.scoreline_probabilities
        row: dict[str, Any] = {
            "minute": minute,
            "score_at_cutoff": f"{state['score_home']}-{state['score_away']}",
            "goals_so_far": goals_so_far,
            "projected_total": projection.projected_final_total,
            # THE HOSTILE BASELINE: assume nothing else happens.
            "frozen_total": goals_so_far,
            "abs_error_projection": round(abs(projection.projected_final_total - actual_total), 4),
            "abs_error_frozen": abs(goals_so_far - actual_total),
            "scoreline_support": len(scorelines),
            "brier": {},
        }
        for line in lines:
            p = _p_over(scorelines, line)
            if p is None:
                row["brier"][str(line)] = None
                continue
            outcome = 1.0 if actual_total > line else 0.0
            row["brier"][str(line)] = {
                "p_over": round(p, 4),
                "outcome": outcome,
                "brier": round((p - outcome) ** 2, 4),
            }
        rows.append(row)

    def _mean(vals):
        vals = [v for v in vals if v is not None]
        return round(sum(vals) / len(vals), 4) if vals else None

    summary_block: dict[str, Any] = {
        "mae_projection": _mean([r["abs_error_projection"] for r in rows]),
        "mae_frozen": _mean([r["abs_error_frozen"] for r in rows]),
        "brier_by_line": {},
    }
    for line in lines:
        scored = [r["brier"].get(str(line)) for r in rows]
        summary_block["brier_by_line"][str(line)] = _mean(
            [s["brier"] for s in scored if isinstance(s, dict)]
        )
    # The verdict a reader actually wants, stated rather than left to arithmetic.
    if summary_block["mae_projection"] is not None and summary_block["mae_frozen"] is not None:
        delta = summary_block["mae_frozen"] - summary_block["mae_projection"]
        summary_block["beats_frozen_baseline"] = delta > 0
        summary_block["mae_improvement_vs_frozen"] = round(delta, 4)

    return {
        "league": league,
        "event_id": event_id,
        "matchup": f"{away_team} @ {home_team}",
        "actual_final": f"{actual_home}-{actual_away}",
        "actual_total": actual_total,
        "simulations": simulations,
        "ratings_source": ratings_source,
        "cutoffs": rows,
        "summary": summary_block,
    }


def batch(
    leagues: list[str],
    window: str,
    *,
    cutoffs: list[int],
    simulations: int,
    ratings_file: Path | None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Every COMPLETED match in `window`, across `leagues`, replayed and pooled.

    n=1 cannot support an accuracy claim, which is what the single-match mode
    was explicitly labelled as. Pooling is what turns this into a reading.

    POOLED BY CUTOFF, not just overall. A live projection that is good at 75'
    and bad at 15' is a different system from one that is uniformly mediocre,
    and a single MAE hides which one we have -- the shape is the finding.

    A match that fails to fetch or replay is COUNTED AND NAMED, never dropped
    silently: a pool that quietly shrinks to the matches that happened to work
    reports the accuracy of the easy cases.
    """
    from syndicate.features.soccer.ingestion.espn_lineups import fetch_events

    results: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []

    # DISCOVER ALL LEAGUES FIRST, THEN INTERLEAVE. A flat "stop at `limit`"
    # over leagues in order starves every league after the first few -- the
    # pool would be one country's football wearing a multi-league label, which
    # is exactly the generality this harness is supposed to test. Round-robin
    # so a cap trims each league evenly instead of truncating the tail.
    discovered: dict[str, list[str]] = {}
    for league in leagues:
        try:
            events = fetch_events(league, date_windows=[window], statuses={"post"})
        except Exception as exc:
            failures.append({"league": league, "event_id": "-", "error": f"{type(exc).__name__}: {exc}"})
            continue
        discovered[league] = [str(e.get("event_id") or "") for e in events if e.get("event_id")]

    ordered: list[tuple[str, str]] = []
    for i in range(max((len(v) for v in discovered.values()), default=0)):
        for league, ids in discovered.items():
            if i < len(ids):
                ordered.append((league, ids[i]))

    for league, event_id in ordered:
        if True:
            if limit is not None and len(results) >= limit:
                break
            if not event_id:
                continue
            try:
                results.append(
                    replay(league, event_id, cutoffs=cutoffs, simulations=simulations,
                           ratings_file=ratings_file)
                )
            except Exception as exc:
                failures.append({"league": league, "event_id": event_id,
                                 "error": f"{type(exc).__name__}: {exc}"})

    def _mean(vals):
        vals = [v for v in vals if v is not None]
        return round(sum(vals) / len(vals), 4) if vals else None

    by_cutoff: dict[str, Any] = {}
    for minute in cutoffs:
        rows = [r for res in results for r in res["cutoffs"] if r["minute"] == minute]
        briers = [r["brier"].get("2.5") for r in rows]
        by_cutoff[str(minute)] = {
            "n": len(rows),
            "mae_projection": _mean([r["abs_error_projection"] for r in rows]),
            "mae_frozen": _mean([r["abs_error_frozen"] for r in rows]),
            "brier_2_5": _mean([b["brier"] for b in briers if isinstance(b, dict)]),
        }

    all_rows = [r for res in results for r in res["cutoffs"]]
    pooled = {
        "matches": len(results),
        "cutoff_rows": len(all_rows),
        "mae_projection": _mean([r["abs_error_projection"] for r in all_rows]),
        "mae_frozen": _mean([r["abs_error_frozen"] for r in all_rows]),
    }
    for line in DEFAULT_LINES:
        b = [r["brier"].get(str(line)) for r in all_rows]
        pooled[f"brier_{str(line).replace('.', '_')}"] = _mean(
            [x["brier"] for x in b if isinstance(x, dict)]
        )
    if pooled["mae_projection"] is not None and pooled["mae_frozen"] is not None:
        pooled["mae_improvement_vs_frozen"] = round(
            pooled["mae_frozen"] - pooled["mae_projection"], 4)
        pooled["beats_frozen_baseline"] = pooled["mae_improvement_vs_frozen"] > 0

    return {
        "window": window,
        "leagues": leagues,
        "simulations": simulations,
        "ratings_source": results[0]["ratings_source"] if results else "n/a",
        "pooled": pooled,
        "by_cutoff": by_cutoff,
        "failures": failures,
        "matches": [
            {"league": r["league"], "event_id": r["event_id"], "matchup": r["matchup"],
             "actual_total": r["actual_total"], "mae": r["summary"]["mae_projection"]}
            for r in results
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--league", default=None)
    parser.add_argument("--event-id", default=None)
    parser.add_argument("--batch-leagues", default=None,
                        help="comma-separated leagues to pool across")
    parser.add_argument("--window", default=None, help="YYYYMMDD-YYYYMMDD")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--cutoffs", default="15,30,45,60,75")
    parser.add_argument("--simulations", type=int, default=300)
    parser.add_argument("--ratings-file", default=None,
                        help="recommendations_<date>.json whose adapter_metadata carries "
                             "the ratings production actually used")
    parser.add_argument("--out", default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    cutoffs = [int(x) for x in str(args.cutoffs).split(",") if str(x).strip()]

    if args.batch_leagues:
        if not args.window:
            parser.error("--batch-leagues requires --window")
        pooled = batch(
            [x.strip() for x in args.batch_leagues.split(",") if x.strip()],
            args.window,
            cutoffs=cutoffs,
            simulations=args.simulations,
            ratings_file=Path(args.ratings_file) if args.ratings_file else None,
            limit=args.limit,
        )
        if args.out:
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_text(json.dumps(pooled, indent=2), encoding="utf-8")
        if args.json:
            print(json.dumps(pooled, indent=2))
        else:
            pl = pooled["pooled"]
            print(f"window {pooled['window']}  leagues {','.join(pooled['leagues'])}  "
                  f"sims={pooled['simulations']}  ratings: {pooled['ratings_source']}")
            print(f"matches {pl['matches']}  cutoff-rows {pl['cutoff_rows']}  "
                  f"failures {len(pooled['failures'])}")
            print()
            print(f"{'cutoff':>7} {'n':>4} {'MAE proj':>9} {'MAE froz':>9} {'brier@2.5':>10}")
            for minute, row in pooled["by_cutoff"].items():
                print(f"{minute:>7} {row['n']:>4} {str(row['mae_projection']):>9} "
                      f"{str(row['mae_frozen']):>9} {str(row['brier_2_5']):>10}")
            print()
            print(f"POOLED MAE projection {pl['mae_projection']}  frozen {pl['mae_frozen']}")
            if "beats_frozen_baseline" in pl:
                v = "BEATS" if pl["beats_frozen_baseline"] else "DOES NOT BEAT"
                print(f"VERDICT: projection {v} frozen by {pl['mae_improvement_vs_frozen']}")
            print(f"Brier 1.5/2.5/3.5: {pl.get('brier_1_5')} / {pl.get('brier_2_5')} / {pl.get('brier_3_5')}")
            for f in pooled["failures"][:8]:
                print(f"  FAILED {f['league']} {f['event_id']}: {f['error'][:80]}")
        return 0

    if not args.league or not args.event_id:
        parser.error("single-match mode needs --league and --event-id")
    result = replay(
        args.league,
        args.event_id,
        cutoffs=cutoffs,
        simulations=args.simulations,
        ratings_file=Path(args.ratings_file) if args.ratings_file else None,
    )

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        s = result["summary"]
        print(f"{result['matchup']}  final {result['actual_final']} (total {result['actual_total']})")
        print(f"ratings: {result['ratings_source']}  sims={result['simulations']}")
        print()
        print(f"{'min':>4} {'score':>7} {'proj':>7} {'frozen':>7} {'|e|proj':>8} {'|e|froz':>8}  brier@2.5")
        for r in result["cutoffs"]:
            b = r["brier"].get("2.5")
            bs = f"{b['brier']:.4f} (p={b['p_over']:.2f})" if isinstance(b, dict) else "-"
            print(f"{r['minute']:>4} {r['score_at_cutoff']:>7} {r['projected_total']:>7.2f} "
                  f"{r['frozen_total']:>7} {r['abs_error_projection']:>8.3f} {r['abs_error_frozen']:>8}  {bs}")
        print()
        print(f"MAE projection {s['mae_projection']}   MAE frozen-baseline {s['mae_frozen']}")
        if "beats_frozen_baseline" in s:
            verdict = "BEATS" if s["beats_frozen_baseline"] else "DOES NOT BEAT"
            print(f"VERDICT: projection {verdict} the frozen baseline "
                  f"(MAE improvement {s['mae_improvement_vs_frozen']})")
        print(f"Brier by line: {s['brier_by_line']}")

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
