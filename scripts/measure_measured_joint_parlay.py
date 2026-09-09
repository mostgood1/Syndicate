"""Heuristic parlay price vs. the MEASURED-JOINT price, on real published sims.

`#621` Phase 5. The two arms differ in ONE thing: how the pairwise dependence
between legs reaches `P(all legs win)`.

    heuristic (today)   mean of the pairwise `correlation_score` flag-sums,
                        interpolated toward the Frechet bound
    measured joint      every pair's own Spearman coefficient out of
                        `sim.joint`, converted to an INDICATOR correlation by
                        `threshold_correlation`, assembled by the second-order
                        covariance expansion in
                        `intelligence_parlay_runtime.measured_joint_weight`

MARGINALS ARE HELD IDENTICAL ACROSS ARMS -- both read `p` from the sim's own
published `*_dist` for that player/market at the traded line, so the only moving
part is the dependence term. Anything the comparison shows is attributable to
it and to nothing else.

THIS IS A DIFFERENCE, NOT AN IMPROVEMENT, and the script says so in its own
output. Scoring needs SETTLED rows for both legs of a pair. The joint producer
deployed 2026-09-04T23:26Z so joints exist from 2026-09-05, and
`mlb_source/reconciliation/props_actuals_*.csv` over 2026-09-05..08 carries 28
BATTER rows in total against 488 pitcher rows -- and the joint's batter
dimensions are the only ones a pair can be built from. That is not a population.
`--actuals-dir` will score whatever it is given and prints the pair count so the
power is visible; today that count is single digits.

WHAT WOULD SCORE IT, concretely: `scripts/backfill_mlb_sim_joint.py` re-runs the
sim over git-tracked rosters for 2026-06-29..07-11, where `daily_top_props`
grades ~8,096 batter legs, and `scripts/score_joint_pair_pricing.py` already
scores four arms on that population. This estimator is added there as a fifth
arm (`sec2`), so scoring it is one backfill run away and needs no new instrument.

INPUT. A directory of published `sim_*.json` artifacts, laid out
`<dir>/<date>/sim_*.json`. Pull them without re-running anything:

    curl -sG -H "X-Admin-Token: $ADMIN_TOKEN" \
      --data-urlencode "pattern=mlb_source/source_artifacts/data/daily/sims/<date>/*.json" \
      https://<web>/api/ops/artifacts/export

MLB ONLY. No other sport publishes a joint; there is nothing to compare
elsewhere and this script refuses to pretend otherwise.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
import os
import pathlib
import statistics
import sys
import unicodedata
from collections import Counter, defaultdict

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from syndicate.features import correlation_engine  # noqa: E402
from syndicate.features import intelligence_parlay_runtime as pr  # noqa: E402
from syndicate.features.mlb.sim_joint_correlation import JointCorrelationIndex  # noqa: E402

#: The joint's batter dimensions and the line each is traded at most often.
#: `total_bases` at 1.5 rather than 0.5 on purpose: 0.5 is the same event as
#: `hits > 0.5` and would put a degenerate pair in the population.
MARKET_LINES = {
    "hits": 0.5,
    "home_runs": 0.5,
    "total_bases": 1.5,
    "rbi": 0.5,
}
MARKET_LABELS = {
    "hits": "batter_hits",
    "home_runs": "batter_home_runs",
    "total_bases": "batter_total_bases",
    "rbi": "batter_rbis",
}
EPS = 1e-6


def _norm(value) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(text.lower().replace(".", " ").replace("-", " ").split())


def _p_over(dist, line: float):
    """P(count > line) from the sim's published histogram. None when degenerate."""
    if not dist:
        return None
    if isinstance(dist, dict):
        items = dist.items()
    else:
        items = dist
    total = over = 0.0
    for key, count in items:
        try:
            value, weight = float(key), float(count)
        except (TypeError, ValueError):
            continue
        total += weight
        if value > line:
            over += weight
    if total <= 0.0:
        return None
    p = over / total
    return None if (p <= EPS or p >= 1.0 - EPS) else p


def _game_pk(path: pathlib.Path):
    for token in path.stem.split("_"):
        if token.startswith("pk") and token[2:].isdigit():
            return int(token[2:])
    return None


def _legs_for_game(record, game_pk: int, game_key: str):
    legs = []
    for pid, profile in (((record or {}).get("sim") or {}).get("hitter_props") or {}).items():
        if not profile.get("is_lineup_batter"):
            continue
        if float(profile.get("pa_mean") or 0.0) < 1.0:
            continue
        for market, line in MARKET_LINES.items():
            p = _p_over(profile.get(f"{market}_dist"), line)
            if p is None:
                continue
            name = profile.get("name")
            legs.append(
                {
                    "sport": "mlb",
                    "sport_slug": "mlb",
                    "game_pk": game_pk,
                    "event_id": game_key,
                    "game_key": game_key,
                    "player_id": int(pid),
                    "player_name": name,
                    "subject_key": name,
                    "name": f"{name} Over {line} {market}",
                    "team": profile.get("team"),
                    "team_key": profile.get("team"),
                    "market": MARKET_LABELS[market],
                    "market_key": MARKET_LABELS[market],
                    "selection": "over",
                    "side": "over",
                    "model_probability": p,
                    "line": line,
                    "_market": market,
                }
            )
    return legs


FLAG = "SYNDICATE_PARLAY_MEASURED_JOINT"


def _price(legs_tuple, *, measured: bool, index=None):
    """Price one ticket under exactly one arm.

    The heuristic arm runs with the FLAG ABSENT, not merely with the resolver
    cleared -- so it is the byte-for-byte today path, and the run doubles as the
    `off != on` proof on real data rather than on a fixture.
    """
    if measured:
        os.environ[FLAG] = "1"
        correlation_engine.register_measured_correlation_resolver(index.as_lookup())
    else:
        os.environ.pop(FLAG, None)
        correlation_engine.register_measured_correlation_resolver(None)
    profile = pr._parlay_correlation_profile(legs_tuple)
    return pr._combined_probability(legs_tuple, profile), profile


def _percentile(values, q: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(q * (len(ordered) - 1)))))
    return ordered[index]


def _load_actuals(actuals_dir: pathlib.Path):
    """date -> (norm(player), market) -> (actual, line). Batter markets only."""
    market_by_label = {
        "hits": "hits",
        "home runs": "home_runs",
        "total bases": "total_bases",
        "rbis": "rbi",
        "runs batted in": "rbi",
    }
    out = defaultdict(dict)
    if not actuals_dir or not actuals_dir.is_dir():
        return out
    for path in sorted(actuals_dir.glob("props_actuals_*.csv")):
        date = path.stem.replace("props_actuals_", "")
        text = path.read_text(encoding="utf-8")
        for row in csv.DictReader(io.StringIO(text)):
            market = market_by_label.get(str(row.get("market") or "").strip().lower())
            if not market:
                continue
            try:
                out[date][(_norm(row.get("player")), market)] = (
                    float(row["actual"]),
                    float(row["line"]),
                )
            except (TypeError, ValueError, KeyError):
                continue
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sims-dir", required=True, help="<dir>/<date>/sim_*.json")
    parser.add_argument("--actuals-dir", default="", help="dir of props_actuals_<date>.csv")
    parser.add_argument("--out", default="", help="write the JSON summary here")
    parser.add_argument("--max-triples-per-game", type=int, default=400)
    args = parser.parse_args()

    sims_dir = pathlib.Path(args.sims_dir)
    dates = sorted(p for p in sims_dir.iterdir() if p.is_dir())
    if not dates:
        print("no date directories under %s" % sims_dir)
        return 3
    actuals = _load_actuals(pathlib.Path(args.actuals_dir)) if args.actuals_dir else {}

    pr.reset_measured_joint_coverage()

    pair_rows = []
    triple_rows = []
    weights = []
    games = 0
    joints = 0
    reasons_total = Counter()
    settled = []

    for date_dir in dates:
        date = date_dir.name
        for path in sorted(date_dir.glob("sim_*.json")):
            games += 1
            record = json.loads(path.read_text(encoding="utf-8"))
            joint = ((record or {}).get("sim") or {}).get("joint")
            game_pk = _game_pk(path)
            if not joint or game_pk is None:
                continue
            joints += 1
            index = JointCorrelationIndex()
            index.add_game(game_pk, joint)
            legs = _legs_for_game(record, game_pk, path.stem)
            if len(legs) < 2:
                continue

            for i in range(len(legs)):
                for j in range(i + 1, len(legs)):
                    pair = (legs[i], legs[j])

                    heuristic_p, heuristic_profile = _price(pair, measured=False)
                    measured_p, measured_profile = _price(pair, measured=True, index=index)

                    block = measured_profile.get("measured_joint") or {}
                    row = {
                        "date": date,
                        "game": path.stem,
                        "a": legs[i]["name"],
                        "b": legs[j]["name"],
                        "p_a": legs[i]["model_probability"],
                        "p_b": legs[j]["model_probability"],
                        "same_player": legs[i]["player_id"] == legs[j]["player_id"],
                        "heuristic_score": heuristic_profile["pair_scores"][0],
                        "heuristic_p": heuristic_p,
                        "measured_p": measured_p,
                        "applied": bool(block.get("applied")),
                        "pairs_measured": int(block.get("pairs_measured") or 0),
                        "pairs_fallback": int(block.get("pairs_fallback") or 0),
                        "phi": (measured_profile["pair_details"][0].get("threshold_correlation")),
                        "rho": (measured_profile["pair_scores"][0]),
                    }
                    if row["applied"] and heuristic_p is not None and measured_p is not None:
                        row["delta"] = measured_p - heuristic_p
                        w = pr.measured_joint_weight(
                            [row["p_a"], row["p_b"]], block.get("pair_phi") or {}
                        )
                        if w is not None:
                            row["weight"] = w
                            row["min_p"] = min(row["p_a"], row["p_b"])
                            weights.append(abs(w))
                    pair_rows.append(row)

                    if actuals and row["applied"]:
                        got_a = actuals.get(date, {}).get((_norm(legs[i]["player_name"]), legs[i]["_market"]))
                        got_b = actuals.get(date, {}).get((_norm(legs[j]["player_name"]), legs[j]["_market"]))
                        if got_a and got_b and got_a[1] == legs[i]["line"] and got_b[1] == legs[j]["line"]:
                            settled.append(
                                {
                                    "y": 1 if (got_a[0] > got_a[1] and got_b[0] > got_b[1]) else 0,
                                    "heuristic": heuristic_p,
                                    "measured": measured_p,
                                    "game": path.stem,
                                    "same_player": legs[i]["player_id"] == legs[j]["player_id"],
                                }
                            )

            # n-leg: 3-leg same-game tickets, which is what the average was
            # actually destroying. Capped per game so the run stays bounded.
            taken = 0
            for i in range(len(legs)):
                for j in range(i + 1, len(legs)):
                    for k in range(j + 1, len(legs)):
                        if taken >= args.max_triples_per_game:
                            break
                        trio = (legs[i], legs[j], legs[k])
                        heuristic_p, _ = _price(trio, measured=False)
                        measured_p, measured_profile = _price(trio, measured=True, index=index)
                        block = measured_profile.get("measured_joint") or {}
                        if block.get("applied") and heuristic_p is not None and measured_p is not None:
                            triple_rows.append(
                                {
                                    "date": date,
                                    "game": path.stem,
                                    "legs": [legs[i]["name"], legs[j]["name"], legs[k]["name"]],
                                    "heuristic_p": heuristic_p,
                                    "measured_p": measured_p,
                                    "delta": measured_p - heuristic_p,
                                    "pairs_measured": int(block.get("pairs_measured") or 0),
                                    "pairs_fallback": int(block.get("pairs_fallback") or 0),
                                }
                            )
                        taken += 1
                    if taken >= args.max_triples_per_game:
                        break
                if taken >= args.max_triples_per_game:
                    break
            reasons_total.update(index.reasons)

    correlation_engine.register_measured_correlation_resolver(None)
    os.environ.pop(FLAG, None)

    applied = [r for r in pair_rows if r.get("applied") and "delta" in r]
    deltas = [r["delta"] for r in applied]
    coverage = pr.measured_joint_coverage()

    print("=" * 78)
    print("MEASURED JOINT vs HEURISTIC -- MLB ONLY, published sim artifacts")
    print("=" * 78)
    print("dates                %d  (%s .. %s)" % (len(dates), dates[0].name, dates[-1].name))
    print("sim artifacts        %d   carrying sim.joint: %d" % (games, joints))
    print()
    print("COVERAGE (denominators, not decoration)")
    print("  2-leg tickets      %d" % len(pair_rows))
    print("  NOTE: counters below are CUMULATIVE over the 2-leg AND 3-leg arms,")
    print("        so pair counts exceed the ticket count by design.")
    print("  pairs measured     %d  (%.1f%%)" % (
        coverage["pairs_measured"],
        100.0 * coverage["pairs_measured"] / max(1, coverage["pairs_total"]),
    ))
    print("  pairs fallback     %d  (%.1f%%)  <- unmeasured, NOT independent" % (
        coverage["pairs_fallback"],
        100.0 * coverage["pairs_fallback"] / max(1, coverage["pairs_total"]),
    ))
    print("  legs measured      %d of %d" % (coverage["legs_measured"], coverage["legs_total"]))
    print("  parlays measured   %d   not-mlb %d   no-measured-pair %d" % (
        coverage["parlays_measured"],
        coverage["parlays_not_mlb"],
        coverage["parlays_no_measured_pair"],
    ))
    print("  resolver reasons   %s" % dict(reasons_total))
    print()

    if deltas:
        print("PAIR DIFFERENCE  measured_p - heuristic_p     n=%d" % len(deltas))
        print("  mean %+0.5f   median %+0.5f   sd %0.5f" % (
            statistics.fmean(deltas), statistics.median(deltas),
            statistics.pstdev(deltas) if len(deltas) > 1 else 0.0,
        ))
        for q in (0.01, 0.05, 0.25, 0.50, 0.75, 0.95, 0.99):
            print("  p%-4s %+0.5f" % (int(q * 100), _percentile(deltas, q)))
        print("  min  %+0.5f   max %+0.5f" % (min(deltas), max(deltas)))
        same = [r["delta"] for r in applied if r["same_player"]]
        cross = [r["delta"] for r in applied if not r["same_player"]]
        for label, sub in (("same-player", same), ("cross-player", cross)):
            if sub:
                print("  %-13s n=%-7d mean %+0.5f  median %+0.5f" % (
                    label, len(sub), statistics.fmean(sub), statistics.median(sub)))
    if weights:
        print()
        print("UNCAPPED FRECHET WEIGHT |w|  (what the cap acts on)   n=%d" % len(weights))
        groups = [
            ("all", weights),
            ("same-player", [abs(r["weight"]) for r in applied if r["same_player"] and "weight" in r]),
            ("cross-player", [abs(r["weight"]) for r in applied if not r["same_player"] and "weight" in r]),
        ]
        for label, sub in groups:
            if not sub:
                continue
            print("  %-13s n=%-7d p50 %0.4f  p90 %0.4f  p99 %0.4f  max %0.4f" % (
                label, len(sub), _percentile(sub, 0.5), _percentile(sub, 0.9),
                _percentile(sub, 0.99), max(sub)))
        print("  share within a candidate cap:")
        print("      %-9s %9s %9s %9s" % ("bound", "all", "same-pl", "cross-pl"))
        for bound in (0.25, 0.40, 0.60, 0.75, 0.85, 0.95):
            cells = []
            for _, sub in groups:
                cells.append("%.2f%%" % (100.0 * sum(1 for w in sub if w <= bound) / float(len(sub))) if sub else "-")
            print("      %-9.2f %9s %9s %9s" % (bound, cells[0], cells[1], cells[2]))
        print()
        print("WHERE THE CAP BINDS  (|w| > %0.2f)" % pr._MEASURED_JOINT_MAX_SHIFT)
        over = [r for r in applied if abs(r.get("weight") or 0.0) > pr._MEASURED_JOINT_MAX_SHIFT]
        if over:
            thin = [r for r in over if r["min_p"] < 0.15]
            print("  pairs %d of %d (%.2f%%)   with a leg at p<0.15: %d (%.1f%%)" % (
                len(over), len(applied), 100.0 * len(over) / len(applied),
                len(thin), 100.0 * len(thin) / len(over)))
            print("  median min-marginal capped %0.3f vs uncapped %0.3f" % (
                statistics.median([r["min_p"] for r in over]),
                statistics.median([r["min_p"] for r in applied if abs(r.get("weight") or 0.0) <= pr._MEASURED_JOINT_MAX_SHIFT]) if len(over) < len(applied) else float("nan")))
            print("  same-player share capped %.1f%% vs population %.1f%%" % (
                100.0 * sum(1 for r in over if r["same_player"]) / len(over),
                100.0 * sum(1 for r in applied if r["same_player"]) / len(applied)))

    if triple_rows:
        td = [r["delta"] for r in triple_rows]
        print()
        print("3-LEG DIFFERENCE  measured_p - heuristic_p     n=%d" % len(td))
        print("  mean %+0.5f   median %+0.5f   min %+0.5f   max %+0.5f" % (
            statistics.fmean(td), statistics.median(td), min(td), max(td)))
        fully = [r for r in triple_rows if r["pairs_fallback"] == 0]
        print("  all three pairs measured: %d of %d" % (len(fully), len(triple_rows)))

    if applied:
        print()
        print("BIGGEST DISAGREEMENTS (hand-check these)")
        ranked = sorted(applied, key=lambda r: -abs(r["delta"]))[:10]
        for r in ranked:
            print("  %+0.4f  %s | %s" % (r["delta"], r["a"], r["b"]))
            print("           p_a=%0.4f p_b=%0.4f  rho_S=%+0.3f phi=%s  heur_score=%+0.3f  w=%+0.3f" % (
                r["p_a"], r["p_b"], r["rho"], r.get("phi"), r["heuristic_score"], r.get("weight", float("nan"))))
            print("           heuristic_p=%0.4f  measured_p=%0.4f  independent=%0.4f" % (
                r["heuristic_p"], r["measured_p"], r["p_a"] * r["p_b"]))

    print()
    if settled:
        def ll(p, y):
            p = min(max(p, 1e-9), 1 - 1e-9)
            return -(math.log(p) if y else math.log(1 - p))
        n = len(settled)
        print("SETTLEMENT SCORING   n=%d pairs  -- REPORTED, NOT RELIED ON" % n)
        for arm in ("heuristic", "measured"):
            print("  %-10s log-loss %0.5f  brier %0.5f" % (
                arm,
                sum(ll(r[arm], r["y"]) for r in settled) / n,
                sum((r[arm] - r["y"]) ** 2 for r in settled) / n,
            ))
        print("  positives %d of %d   distinct games %d   same-player %d" % (
            sum(r["y"] for r in settled), n,
            len({r["game"] for r in settled}),
            sum(1 for r in settled if r["same_player"])))
        print("  n IS THE WHOLE STORY. With a near-all-zero outcome column the arm")
        print("  that prices LOWER wins mechanically, which is not evidence about")
        print("  dependence. No bootstrap is run because there are not enough")
        print("  independent game clusters to resample. DIFFERENCE, not improvement.")
    else:
        print("SETTLEMENT SCORING   NONE. This is a DIFFERENCE, not an IMPROVEMENT.")
        print("  What would score it: scripts/backfill_mlb_sim_joint.py then")
        print("  scripts/score_joint_pair_pricing.py (the `sec2` arm).")

    if args.out:
        out = pathlib.Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(
                {
                    "dates": [d.name for d in dates],
                    "sim_artifacts": games,
                    "with_joint": joints,
                    "coverage": coverage,
                    "resolver_reasons": dict(reasons_total),
                    "pair_delta_n": len(deltas),
                    "pair_delta_mean": statistics.fmean(deltas) if deltas else None,
                    "pair_delta_median": statistics.median(deltas) if deltas else None,
                    "pair_delta_percentiles": {
                        str(q): _percentile(deltas, q) for q in (0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99)
                    } if deltas else {},
                    "weight_abs_percentiles": {
                        str(q): _percentile(weights, q) for q in (0.5, 0.9, 0.95, 0.99, 0.999)
                    } if weights else {},
                    "weight_share_within": {
                        str(b): sum(1 for w in weights if w <= b) / float(len(weights))
                        for b in (0.25, 0.4, 0.5, 0.6, 0.75)
                    } if weights else {},
                    "triple_delta_n": len(triple_rows),
                    "settled_pairs": len(settled),
                    "biggest_disagreements": sorted(applied, key=lambda r: -abs(r["delta"]))[:10],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print("\nwrote %s" % out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
