"""Fit and BACKTEST an NCAAF player-prop model on real 2025 game logs.

--------------------------------------------------------------------------
WHAT THIS CAN AND CANNOT ANSWER
--------------------------------------------------------------------------

IT CANNOT ANSWER "DOES IT BEAT THE MARKET", and no amount of care here would
change that: **there are zero historical NCAAF player-prop odds.** NFL has
`oddsapi_player_props_2023_wk*.csv` back to 2023 (109,750 rows); NCAAF's first
capture in this platform's history happened 2026-08-26, hours before this file
was written. With no closing line there is no ROI, no CLV and no edge.

Saying that plainly matters, because the natural next move -- grade against the
LIVE 2026 wk1 prices -- would produce an ROI number from **8 games of
ungraded pregame quotes**, and that number would be reported and remembered.
`state.md` records the cost of exactly that shape: prop denominators counted in
per-book ROWS rather than BETS overstated significance **3.4x**.

WHAT IT DOES ANSWER: out-of-sample predictive accuracy against real outcomes,
with a naive baseline to beat. That is the honest analogue of "beats the
market" when no market exists, and it is a PRECONDITION for the market test
rather than a substitute -- a model that cannot beat a base rate will not beat
a price.

--------------------------------------------------------------------------
THE BACKTEST IS TEMPORAL AND THE SPLIT IS THE WHOLE POINT
--------------------------------------------------------------------------

For each graded week `w`, rates are fitted on weeks `< w` ONLY and used to
predict week `w`. Nothing from week `w` or later touches the fit.

`state.md` records what the alternative costs on this exact sport: NCAAF
ratings were once read from `/ppa/teams?year=S`, a season-aggregate that
CONTAINS the game being predicted, and it inflated apparent skill by 30%
(r 0.663 vs 0.509 as-of, 558 games). A season-long player rate would be the
same defect wearing different clothes.

--------------------------------------------------------------------------
BASELINES, BECAUSE A SCORE WITHOUT ONE IS NOT A RESULT
--------------------------------------------------------------------------

Two, and the model has to beat both:

  base_rate   every player gets the league-wide rate for that market. Beating
              this only proves players differ from each other.
  player_mean the player's own prior-weeks mean, ungoverned. This is the real
              bar: it is what "just use his average" gets you, and a model that
              cannot beat it is adding machinery, not information.

Usage:
    python scripts/backtest_ncaaf_player_props.py --season 2025
    python scripts/backtest_ncaaf_player_props.py --season 2025 --min-week 6 --json
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


#: Markets this models, mapped to the game-log column that realises them.
#: Deliberately the SAME market set the live capture quotes -- modelling a
#: market nobody prices is a number with no counterparty.
YARDAGE_MARKETS = {
    "Receiving Yards": "receiving_yards",
    "Rushing Yards": "rushing_yards",
    "Passing Yards": "passing_yards",
    "Receptions": "receptions",
    "Passing TDs": "passing_tds",
}
BINARY_MARKET = ("Anytime TD", "anytime_td")

#: A player with fewer prior games than this is not projected. Two games of
#: history is a rate with no denominator worth the name, and the live capture
#: shows 6 of 68 quoted players have no 2025 history at all -- so refusing is
#: a real branch, not a theoretical one.
MIN_PRIOR_GAMES = 3


def _f(value: Any) -> float:
    try:
        text = str(value or "").strip()
        return float(text) if text else 0.0
    except (TypeError, ValueError):
        return 0.0


def load_rows(path: Path, season: int) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [r for r in csv.DictReader(handle) if str(r.get("season")) == str(season)]


def _brier(prob: float, outcome: int) -> float:
    return (prob - outcome) ** 2


def backtest(rows: list[dict[str, str]], *, min_week: int) -> dict[str, Any]:
    weeks = sorted({int(r["week"]) for r in rows if str(r.get("week") or "").isdigit()})
    by_week: dict[int, list[dict[str, str]]] = defaultdict(list)
    for r in rows:
        if str(r.get("week") or "").isdigit():
            by_week[int(r["week"])].append(r)

    # --- ANYTIME TD, scored with Brier against two baselines
    td = {"model": [], "player_mean": [], "base_rate": [], "n": 0, "refused": 0}
    # --- YARDAGE / COUNT markets, scored with MAE
    yard: dict[str, dict[str, list[float]]] = {
        m: {"model": [], "player_mean": [], "base_rate": []} for m in YARDAGE_MARKETS
    }
    yard_n: dict[str, int] = defaultdict(int)

    for w in weeks:
        if w < min_week:
            continue
        prior = [r for r in rows if int(r["week"]) < w]
        if not prior:
            continue

        # Fit on prior weeks ONLY.
        games_by_player: dict[str, int] = defaultdict(int)
        td_by_player: dict[str, float] = defaultdict(float)
        sums: dict[tuple[str, str], float] = defaultdict(float)
        for r in prior:
            pid = str(r.get("player_id") or "")
            if not pid:
                continue
            games_by_player[pid] += 1
            td_by_player[pid] += _f(r.get(BINARY_MARKET[1]))
            for market, col in YARDAGE_MARKETS.items():
                sums[(pid, market)] += _f(r.get(col))

        league_td = (sum(td_by_player.values()) / max(1, sum(games_by_player.values())))
        # THE PRIOR IS CONDITIONED ON PARTICIPATION, and the first version of
        # this was not. A global per-game mean is dominated by the players who
        # never touch that market -- most of a roster has zero passing yards --
        # so shrinking a quarterback toward it drags him toward non-passers.
        #
        # MEASURED, global prior, 2025 weeks 5-16, n=18,989:
        #
        #     market            model MAE   player-mean MAE
        #     Passing Yards        18.785     9.798     <- 1.9x WORSE
        #     Rushing Yards        14.833    12.400
        #     Receiving Yards      16.853    15.380
        #
        # The model beat the league base rate on all five and LOST to "just use
        # his own average" on all five. That is the signature of a prior
        # pulling in the wrong direction, not of a weak signal.
        #
        # Conditioning on players with ANY prior volume in the market makes the
        # prior mean something: "what does a passer average", not "what does a
        # roster average".
        participants: dict[str, list[float]] = {m: [] for m in YARDAGE_MARKETS}
        for (pid_k, market_k), total in sums.items():
            if total > 0 and games_by_player.get(pid_k):
                participants[market_k].append(total / games_by_player[pid_k])
        league_yard = {
            m: (statistics.mean(participants[m]) if participants[m] else 0.0)
            for m in YARDAGE_MARKETS
        }
        # A player with no prior volume in a market is not projected for it at
        # all -- a receiver has no passing-yards line, and inventing one is how
        # a model generates confident nonsense on markets nobody quotes.
        has_volume = {
            (pid_k, market_k) for (pid_k, market_k), total in sums.items() if total > 0
        }

        for r in by_week[w]:
            pid = str(r.get("player_id") or "")
            g = games_by_player.get(pid, 0)
            if not pid:
                continue
            if g < MIN_PRIOR_GAMES:
                td["refused"] += 1
                continue

            # ---- Anytime TD: shrunk rate -> P(at least one)
            raw = td_by_player[pid] / g
            # Empirical-Bayes shrink toward the league rate. Weight is the
            # player's own sample: a 3-game rate of 1.00 is not a 100% scorer,
            # and an unshrunk rate would say it is.
            k = 4.0
            shrunk = (td_by_player[pid] + k * league_td) / (g + k)
            p_model = 1.0 - math.exp(-max(0.0, shrunk))  # Poisson P(>=1)
            p_mean = min(0.99, max(0.01, raw))
            outcome = 1 if _f(r.get(BINARY_MARKET[1])) > 0 else 0
            td["model"].append(_brier(p_model, outcome))
            td["player_mean"].append(_brier(p_mean, outcome))
            td["base_rate"].append(_brier(1.0 - math.exp(-league_td), outcome))
            td["n"] += 1

            # ---- Yardage / counts: shrunk mean, scored by MAE
            for market, col in YARDAGE_MARKETS.items():
                if (pid, market) not in has_volume:
                    continue
                actual = _f(r.get(col))
                pm = sums[(pid, market)] / g
                sm = (sums[(pid, market)] + k * league_yard[market]) / (g + k)
                yard[market]["model"].append(abs(sm - actual))
                yard[market]["player_mean"].append(abs(pm - actual))
                yard[market]["base_rate"].append(abs(league_yard[market] - actual))
                yard_n[market] += 1

    def mean(xs: list[float]) -> float:
        return statistics.mean(xs) if xs else float("nan")

    return {
        "weeks_graded": [w for w in weeks if w >= min_week],
        "anytime_td": {
            "n": td["n"],
            "refused_min_games": td["refused"],
            "brier_model": mean(td["model"]),
            "brier_player_mean": mean(td["player_mean"]),
            "brier_base_rate": mean(td["base_rate"]),
        },
        "yardage": {
            m: {
                "n": yard_n[m],
                "mae_model": mean(yard[m]["model"]),
                "mae_player_mean": mean(yard[m]["player_mean"]),
                "mae_base_rate": mean(yard[m]["base_rate"]),
            }
            for m in YARDAGE_MARKETS
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Backtest an NCAAF player-prop model on real game logs.")
    parser.add_argument("--season", type=int, default=2025)
    parser.add_argument("--min-week", type=int, default=5, help="First week to GRADE; earlier weeks are fit-only.")
    parser.add_argument("--path", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    path = args.path or (
        REPO_ROOT / "data" / "ncaaf_source" / "source_artifacts" / "data" / "processed"
        / "player_game_stats" / "ncaaf_player_game_stats_snapshot.csv"
    )
    if not path.exists():
        print(f"ERROR: no player game stats at {path}")
        return 2

    rows = load_rows(path, args.season)
    if not rows:
        print(f"ERROR: no rows for season {args.season} in {path}")
        return 3

    result = backtest(rows, min_week=args.min_week)
    result["season"] = args.season
    result["rows"] = len(rows)
    result["players"] = len({r.get("player_id") for r in rows})

    if args.json:
        print(json.dumps(result, indent=2))
        return 0

    td = result["anytime_td"]
    print(f"NCAAF player-prop backtest -- season {args.season}, {result['rows']:,} game logs, "
          f"{result['players']:,} players")
    print(f"graded weeks {result['weeks_graded'][0]}..{result['weeks_graded'][-1]}, "
          f"fit on prior weeks only\n")
    print("ANYTIME TD  (Brier, lower is better)")
    print(f"  n                 {td['n']:,}   (refused, <{MIN_PRIOR_GAMES} prior games: {td['refused_min_games']:,})")
    print(f"  model             {td['brier_model']:.5f}")
    print(f"  player mean       {td['brier_player_mean']:.5f}")
    print(f"  league base rate  {td['brier_base_rate']:.5f}")
    beat_mean = td["brier_model"] < td["brier_player_mean"]
    beat_base = td["brier_model"] < td["brier_base_rate"]
    print(f"  -> beats player mean: {beat_mean}   beats base rate: {beat_base}")

    print("\nYARDAGE / COUNTS  (MAE, lower is better)")
    print(f"  {'market':18s} {'n':>7s} {'model':>9s} {'plyr mean':>10s} {'base':>9s}  verdict")
    for m, s in result["yardage"].items():
        better = "beats both" if s["mae_model"] < min(s["mae_player_mean"], s["mae_base_rate"]) else (
            "beats base only" if s["mae_model"] < s["mae_base_rate"] else "beats neither")
        print(f"  {m:18s} {s['n']:>7,} {s['mae_model']:>9.3f} {s['mae_player_mean']:>10.3f} "
              f"{s['mae_base_rate']:>9.3f}  {better}")

    ready = [m for m, s in result["yardage"].items()
             if s["mae_model"] < min(s["mae_player_mean"], s["mae_base_rate"])]
    if beat_mean and beat_base:
        ready.append("Anytime TD")
    all_markets = list(result["yardage"]) + ["Anytime TD"]
    print("\nVERDICT -- markets where the model beats BOTH baselines:")
    print(f"  ready      : {', '.join(ready) if ready else '(none)'}")
    not_ready = [m for m in all_markets if m not in ready]
    if not_ready:
        print(f"  NOT ready  : {', '.join(not_ready)}")
        print("  On those the player's own prior-weeks mean predicts better than the")
        print("  model. Shipping there would add machinery, not information.")

    print("\nNO MARKET COMPARISON IS POSSIBLE. There are zero historical NCAAF prop")
    print("odds -- the first capture in this platform's history was 2026-08-26.")
    print("These numbers say the model predicts outcomes better or worse than a")
    print("naive rule. They do NOT say it beats a price, and must not be quoted")
    print("as if they did.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
