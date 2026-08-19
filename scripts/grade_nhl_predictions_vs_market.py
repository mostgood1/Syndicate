#!/usr/bin/env python3
"""Score hockeysim's real published moneyline/total/puck-line predictions against the REAL market
and REAL settled outcomes — the market-comparison backtest MLB already has
(`scripts/grade_mlb_hitter_props_vs_market.py`), NHL never did until now.

WHY THIS IS A DIFFERENT INSTRUMENT FROM EVERYTHING ELSE THIS SESSION MEASURED. Every calibration
this session ran (special-teams goal/shot multipliers, block rate, the xG model's holdout AUC)
checks whether the engine's INTERNAL statistics match REAL AGGREGATE reality, or whether one
sub-component predicts its own narrow target well. None of that tells you whether the resulting
GAME-LEVEL prediction beats the price a real market already set — the only question that actually
answers "does this show an edge." This script is that check, mirroring the exact methodology MLB's
`convergence-phase7-crps` lane already validated the hard way (see the report doc for the
methodology this was built from and the mistakes it avoids repeating).

METRIC: Brier score (`syndicate.features.shared.model_scoring.brier_score`) — lower is better,
0.25 is a coin flip. Not CRPS (that scores continuous distributions against a REALIZED VALUE;
this scores a REAL BOOK PRICE against a binary outcome, comparing two probability FORECASTS, not
forecast-vs-outcome directly for the model side).

WHY THESE COLUMNS ARE NOT CIRCULAR. `predictions_{date}.csv`'s `p_home_ml`/`p_over`/`p_home_pl_-1.5`
come from `adapters.build_game_prediction`, which only calls `game_market_sim.simulate_from_period_lambdas`
on `HockeyGameFeatures.period_goal_lambdas` — the market-anchoring mechanism
(`market_anchoring.anchor_game_features`) is a SEPARATE, opt-in code path that only touches the
PROPS pipeline (`build_prop_projections`), never this one. Confirmed by reading `adapters.py`
directly, not assumed from column naming. Where a `_model`-suffixed column exists (one legacy file
from the pre-migration vendor pipeline, `hockeysim_engine_reference.md` §1), it is preferred anyway
— cheap insurance, since that file's plain columns were written by different, non-Syndicate code
this script did not audit.

JOIN, COUNTED NOT SILENTLY DROPPED (the MLB harness's own hard-won discipline, see its docstring
and `docs/ai_context/todo.md`'s`#463`-adjacent notes): every row that fails to score is counted
under a named reason, never just omitted. `devig()` is passed BOTH sides of every market (a 2-way
de-vig of a market with more than 2 sides manufactures fake edges — not a risk here, NHL moneyline/
total/puck-line are genuinely 2-way, but the discipline is kept anyway for anyone extending this).
A push (total exactly equal to the line) is excluded from scoring, not counted as a loss for either
side. A market whose base rate falls at or outside `[0.001, 0.999]` is refused, not reported, since
Brier is degenerate there (matches `grade_mlb_hitter_props_vs_market.py`'s own guard).

REAL DATA SOURCES, NO SYNTHETIC SUBSTITUTION:
- Predictions + market odds: `data/nhl_source/data/processed/predictions_<date>.csv` (NOT
  `predictions_sim_*.csv`, a different per-draw shape) — `home_ml_odds`/`away_ml_odds`/`over_odds`/
  `under_odds`/`home_pl_-1.5_odds`/`away_pl_+1.5_odds` are the REAL American prices captured at
  build time, on the SAME row as the model's own probability for that market.
- Settled outcomes: `data/nhl_source/data/ingestion_cache/boxscore_*.json` (the real cache §2e/§2g/
  §2i/§2j/§2k of this session's work already bulk-fetched), filtered to `gameState in
  {"OFF","FINAL"}` — genuinely finished games only, joined on `(date, home_abbr, away_abbr)` via
  `syndicate.local_nhl_odds._team_abbr` (the same team-name resolver `loaders.py` already uses).

Usage:
  py -3 scripts/grade_nhl_predictions_vs_market.py
  py -3 scripts/grade_nhl_predictions_vs_market.py --json reports/nhl_market_backtest/predictions_vs_market.json
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from syndicate.features.shared.model_scoring import brier_score  # noqa: E402
from syndicate.features.shared.opportunity_signals import devig  # noqa: E402
from syndicate.local_nhl_odds import _team_abbr  # noqa: E402


def _nhl_source_root() -> Path:
    import os
    env = str(os.environ.get("SYNDICATE_ARTIFACT_ROOT_NHL") or "").strip()
    if env:
        p = Path(env)
        if p.exists():
            return p
    return REPO / "data" / "nhl_source"


def _to_float(v: object) -> Optional[float]:
    try:
        if v is None or str(v).strip() == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def load_predictions(root: Path) -> List[Dict]:
    """One row per game across every real `predictions_<date>.csv` under the processed dir.
    Excludes `predictions_sim_*.csv` (a per-sim-draw shape, not a per-game prediction row)."""
    proc = root / "data" / "processed"
    rows: List[Dict] = []
    for path in sorted(proc.glob("predictions_*.csv")):
        if path.name.startswith("predictions_sim_"):
            continue
        with path.open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                row["_source_file"] = path.name
                rows.append(row)
    return rows


def load_settled_outcomes(root: Path) -> Dict[Tuple[str, str, str], Tuple[int, int]]:
    """`{(date, home_abbr, away_abbr): (home_score, away_score)}` from the real boxscore cache --
    ONLY genuinely finished games. Never guesses a score from an in-progress or future game."""
    cache_dir = root / "data" / "ingestion_cache"
    out: Dict[Tuple[str, str, str], Tuple[int, int]] = {}
    for p in cache_dir.glob("boxscore_*.json"):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if str(d.get("gameState") or "") not in ("OFF", "FINAL"):
            continue
        date = str(d.get("gameDate") or "")[:10]
        home = d.get("homeTeam") or {}
        away = d.get("awayTeam") or {}
        h_abbr = str(home.get("abbrev") or "").upper()
        a_abbr = str(away.get("abbrev") or "").upper()
        h_score = home.get("score")
        a_score = away.get("score")
        if not date or not h_abbr or not a_abbr or h_score is None or a_score is None:
            continue
        out[(date, h_abbr, a_abbr)] = (int(h_score), int(a_score))
    return out


# One entry per market: how to pull the model's own probability, the market's two American prices
# (for a fair-probability de-vig), and how to compute the realized 0/1 outcome from a settled score.
# `push_check`, when present, returns True for a row that should be excluded (not scored either way).
MARKET_SPECS = [
    {
        "key": "home_ml",
        "model_cols": ("p_home_ml_model", "p_home_ml"),
        "odds_cols": ("home_ml_odds", "away_ml_odds"),
        "outcome": lambda h, a, row: 1.0 if h > a else 0.0,
        "push_check": lambda h, a, row: h == a,  # NHL games can't end tied, but guard anyway
    },
    {
        "key": "total_over",
        "model_cols": ("p_over_model", "p_over"),
        "odds_cols": ("over_odds", "under_odds"),
        "outcome": lambda h, a, row: 1.0 if (h + a) > _to_float(row.get("totals_line_used") or 0) else 0.0,
        "push_check": lambda h, a, row: (h + a) == _to_float(row.get("totals_line_used")),
    },
    {
        "key": "home_puck_line_-1.5",
        "model_cols": ("p_home_pl_-1.5",),
        "odds_cols": ("home_pl_-1.5_odds", "away_pl_+1.5_odds"),
        "outcome": lambda h, a, row: 1.0 if (h - a) > 1.5 else 0.0,
        "push_check": lambda h, a, row: False,  # a half-point line can never push
    },
]


def score(rows: List[Dict], outcomes: Dict[Tuple[str, str, str], Tuple[int, int]]):
    counters: Counter = Counter()
    pairs: Dict[str, Dict[str, List[Tuple[float, float]]]] = {
        m["key"]: {"model": [], "market": []} for m in MARKET_SPECS
    }
    dates_seen = set()
    dates_matched = set()
    seen_games = set()

    for row in rows:
        date = str(row.get("date") or "")[:10]  # normalize -- some files carry a full timestamp
        if not date:
            counters["bad_row:no_date"] += 1
            continue
        dates_seen.add(date)
        home_abbr = _team_abbr(row.get("home"))
        away_abbr = _team_abbr(row.get("away"))
        if not home_abbr or not away_abbr:
            counters["bad_row:unresolved_team_name"] += 1
            continue
        game_key = (date, home_abbr, away_abbr)
        # STALE-FILE DEDUP, found by running this script for real: several `predictions_<date>.csv`
        # files are byte-identical copies of an earlier date's slate (the pipeline re-serving the
        # last real games under new date-stamped filenames once the underlying series ended,
        # verified with a plain `diff` -- not assumed). Scoring the SAME settled game more than
        # once would silently inflate n with non-independent, literally duplicate observations and
        # bias the average toward whichever game happened to repeat. Counted, not silently dropped.
        if game_key in seen_games:
            counters["duplicate_stale_file_row"] += 1
            continue
        seen_games.add(game_key)
        settled = outcomes.get(game_key)
        if settled is None:
            counters["no_settled_outcome"] += 1
            continue
        dates_matched.add(date)
        h_score, a_score = settled

        for spec in MARKET_SPECS:
            key = spec["key"]
            p_model = None
            for col in spec["model_cols"]:
                p_model = _to_float(row.get(col))
                if p_model is not None:
                    break
            odds = [_to_float(row.get(c)) for c in spec["odds_cols"]]
            if p_model is None:
                counters[f"{key}:no_model"] += 1
                continue
            if any(o is None for o in odds):
                counters[f"{key}:no_market"] += 1
                continue
            if spec["push_check"](h_score, a_score, row):
                counters[f"{key}:push"] += 1
                continue
            fair = devig(odds)
            if fair is None:
                counters[f"{key}:devig_failed"] += 1
                continue
            outcome = spec["outcome"](h_score, a_score, row)
            pairs[key]["model"].append((p_model, outcome))
            pairs[key]["market"].append((fair[0], outcome))
            counters[f"{key}:scored"] += 1

    return pairs, counters, dates_seen, dates_matched


def _summarize(pairs: List[Tuple[float, float]]) -> Optional[Dict]:
    if not pairs:
        return None
    scores = [brier_score(p, o) for p, o in pairs]
    scores = [s for s in scores if s is not None]
    if not scores:
        return None
    n = len(scores)
    base_rate = sum(o for _, o in pairs) / len(pairs)
    return {"n": n, "brier": sum(scores) / n, "base_rate": round(base_rate, 4)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=None)
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args()

    root = args.root or _nhl_source_root()
    rows = load_predictions(root)
    outcomes = load_settled_outcomes(root)

    pred_dates = sorted({str(r.get("date") or "") for r in rows if r.get("date")})
    outcome_dates = sorted({k[0] for k in outcomes})
    print(f"predictions: {len(rows)} rows across {len(pred_dates)} dates "
          f"({pred_dates[0] if pred_dates else '?'}..{pred_dates[-1] if pred_dates else '?'})")
    print(f"settled outcomes cached: {len(outcomes)} games across {len(outcome_dates)} dates")

    pairs, counters, dates_seen, dates_matched = score(rows, outcomes)
    intersection = sorted(dates_seen & dates_matched)
    print(f"prediction dates with a matched settled outcome (the INTERSECTION this result "
          f"actually rests on): {len(intersection)} of {len(dates_seen)} -- {intersection}")

    print("\njoin/scoring breakdown (every row accounted for, nothing silently dropped):")
    for reason, n in sorted(counters.items()):
        print(f"  {reason:40s} {n}")

    print("\n" + "=" * 88)
    print("RESULTS -- Brier, lower is better, 0.25 = coin flip")
    print("=" * 88)
    results = {}
    for spec in MARKET_SPECS:
        key = spec["key"]
        model_summary = _summarize(pairs[key]["model"])
        market_summary = _summarize(pairs[key]["market"])
        if model_summary is None or market_summary is None:
            print(f"  {key:22s} UNMEASURED -- 0 scoreable rows")
            results[key] = {"verdict": "unmeasured"}
            continue
        base = model_summary["base_rate"]
        if base <= 0.001 or base >= 0.999:
            print(f"  {key:22s} REFUSED -- base rate {base} is degenerate (n={model_summary['n']})")
            results[key] = {"verdict": "refused_degenerate_base_rate", "n": model_summary["n"], "base_rate": base}
            continue
        n = model_summary["n"]
        b_model = model_summary["brier"]
        b_market = market_summary["brier"]
        verdict = "MODEL BEATS MARKET" if b_model < b_market else "market wins"
        print(f"  {key:22s} n={n:3d}  base_rate={base:.3f}  model={b_model:.4f}  "
              f"market={b_market:.4f}  {verdict}")
        results[key] = {
            "n": n, "base_rate": base, "brier_model": round(b_model, 4),
            "brier_market": round(b_market, 4), "verdict": verdict,
        }

    print("\n" + "=" * 88)
    total_scored = sum(v.get("n", 0) for v in results.values() if "n" in v)
    print(f"CAVEAT, stated plainly: this checkout's LOCAL predictions_<date>.csv coverage is "
          f"{len(pred_dates)} dates ({sum(1 for r in rows if r.get('date'))} game-rows), all "
          f"playoff-window, single-game nights. Total scored observations across all markets: "
          f"{total_scored}. This is FAR below any sample size that could support a real "
          f"'beats/loses to market' conclusion (the MLB harness this mirrors uses hundreds of "
          f"props per market and STILL found its single-seed noise floor exceeded the effects "
          f"under study). This run proves the harness is correct end-to-end on real data -- it is "
          f"NOT a statistically powered verdict. Re-run against a fuller regular-season mirror "
          f"before citing a result from this script as evidence of edge either way.")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "prediction_dates": pred_dates,
            "outcome_date_count": len(outcome_dates),
            "intersection_dates": intersection,
            "counters": dict(counters),
            "results": results,
            "total_scored": total_scored,
        }
        args.json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nwrote {args.json}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
