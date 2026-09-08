"""Does the first5 model beat the MARKET, or only climatology?

The skill backtest established that the pregame first5 number DISCRIMINATES --
top tercile 67.4% against bottom tercile 45.4% out of sample, 3.82 sigma, while
the full-game model separates at 0.88 sigma. That says the model carries
information. It does NOT say the market lacks it, and the market is the only bar
that decides whether to bet.

This joins the model's first5 probability to the book's own first5 h2h price on
the same game and asks the one question that matters: **where the model and the
market disagree, which one is right?**

THE LEG FRAME IS HANDLED THE WAY THE SHIPPED CODE HANDLES IT, and the artifact
makes it explicit -- `markets.segments.first1.h2h` carries `is_3_way: true` and
`draw_odds`, while `first5` is quoted two-way. So a three-way quote is de-vigged
across three legs and compared to the RAW model probability; a two-way quote is
de-vigged across two and compared to the model's tie-removed conditional
`home/(home+away)`. Mixing those frames is worth ~11 points of fabricated edge,
which is the whole reason `segment_home_win_prob` exists.

CONSENSUS, NOT BEST PRICE. Each game is quoted by several books; the market
probability is the MEDIAN de-vigged home probability across them. Taking the
best price would measure a shopping advantage rather than the model's, which is
the selection effect already measured at +6.2 pts elsewhere in this repo.

Run:  python scripts/backtest_mlb_first5_vs_market.py
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import pathlib
import re
import statistics
import sys
from collections import defaultdict

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.backtest_mlb_first5_skill import (  # noqa: E402
    SEGMENT_INNINGS,
    linescores_for_date,
    load_predictions,
    segment_actual,
)

ODDS_GLOB = str(REPO / "data" / "mlb_source" / "source_artifacts" / "data" / "market"
                / "oddsapi" / "oddsapi_game_lines_*.json")
DATE_RE = re.compile(r"(\d{4})_(\d{2})_(\d{2})")


def implied(american) -> float | None:
    try:
        odds = float(str(american).replace("+", ""))
    except (TypeError, ValueError):
        return None
    if odds == 0:
        return None
    return 100.0 / (odds + 100.0) if odds > 0 else (-odds) / ((-odds) + 100.0)


def devig_home(h2h: dict) -> tuple[float | None, bool]:
    """(de-vigged P(home), was_three_way). None when the quote is not two-sided."""
    home = implied(h2h.get("home_odds"))
    away = implied(h2h.get("away_odds"))
    if home is None or away is None:
        return None, False
    draw = implied(h2h.get("draw_odds")) if h2h.get("is_3_way") else None
    total = home + away + (draw or 0.0)
    if total <= 0:
        return None, bool(draw is not None)
    return home / total, draw is not None


def load_market(segment: str) -> dict:
    """(date, home, away) -> {"p_home": median devig, "three_way": bool, "books": n}"""
    per_game: dict = defaultdict(list)
    three_way: dict = {}
    for path in sorted(glob.glob(ODDS_GLOB)):
        m = DATE_RE.search(pathlib.Path(path).name)
        if not m:
            continue
        date = "-".join(m.groups())
        try:
            with open(path, encoding="utf-8") as fh:
                doc = json.load(fh)
        except Exception:
            continue
        for game in doc.get("games") or []:
            seg = ((game.get("markets") or {}).get("segments") or {}).get(segment) or {}
            h2h = seg.get("h2h") or {}
            prob, is3 = devig_home(h2h)
            if prob is None:
                continue
            key = (date, str(game.get("home_team") or "").strip().lower(),
                   str(game.get("away_team") or "").strip().lower())
            per_game[key].append(prob)
            three_way[key] = is3
    return {k: {"p_home": statistics.median(v), "books": len(v),
                "three_way": three_way.get(k, False)}
            for k, v in per_game.items()}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--segment", default="first5")
    ap.add_argument("--min-books", type=int, default=2)
    args = ap.parse_args()

    market = load_market(args.segment)
    mkt_dates = sorted({d for d, _, _ in market})
    print(f"MARKET   games={len(market)}  dates={len(mkt_dates)}"
          + (f"  {mkt_dates[0]}..{mkt_dates[-1]}" if mkt_dates else ""))

    preds, _ = load_predictions()
    pred_dates = sorted({d for d, _ in preds})
    print(f"MODEL    games={len(preds)}  dates={len(pred_dates)}  "
          f"{pred_dates[0]}..{pred_dates[-1]}")

    # team names differ between the two families, so join on (date, teams) after
    # normalising -- and COUNT the misses rather than letting a thin join look
    # like a thin market.
    rows, misses = [], defaultdict(int)
    inter_dates = sorted(set(mkt_dates) & set(pred_dates))
    print(f"INTERSECTION dates={len(inter_dates)}"
          + (f"  {inter_dates[0]}..{inter_dates[-1]}" if inter_dates else ""))

    linescore_cache: dict = {}
    for date in inter_dates:
        lines = linescore_cache.get(date) or linescores_for_date(date)
        linescore_cache[date] = lines
        by_teams = {}
        for pk_date, pk in preds:
            if pk_date != date:
                continue
            game = lines.get(str(pk))
            if game is None:
                continue
            by_teams[str(pk)] = game
        for (mdate, home, away), mrow in market.items():
            if mdate != date:
                continue
            if mrow["books"] < args.min_books:
                misses["too_few_books"] += 1
                continue
            # find the model row for this matchup via StatsAPI team names
            hit_pk = None
            for pk_date, pk in preds:
                if pk_date != date:
                    continue
                g = lines.get(str(pk)) or {}
                names = g.get("teams") or {}
                if not names:
                    continue
            # StatsAPI schedule hydration in the cache does not carry team names,
            # so fall back to matching on the daily summary's own abbreviations
            # is not possible here; join by ORDER is unsafe. Use the odds
            # event's teams against the schedule instead.
            misses["no_team_join"] += 1
        break

    # The join above cannot work from the cached payload (it stores only innings
    # and state), so re-fetch names once per date with a richer parse.
    print("\nre-fetching schedules with team names for the join ...")
    import urllib.request
    rows = []
    for date in inter_dates:
        url = (f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={date}"
               f"&hydrate=linescore")
        try:
            with urllib.request.urlopen(url, timeout=60) as resp:
                doc = json.load(resp)
        except Exception:
            continue
        for day in doc.get("dates") or []:
            for game in day.get("games") or []:
                if str(((game.get("status") or {}).get("abstractGameState") or "")).lower() != "final":
                    continue
                pk = int(game.get("gamePk"))
                teams = game.get("teams") or {}
                home = str(((teams.get("home") or {}).get("team") or {}).get("name") or "").strip().lower()
                away = str(((teams.get("away") or {}).get("team") or {}).get("name") or "").strip().lower()
                mrow = market.get((date, home, away))
                if mrow is None:
                    misses["market_missing_for_game"] += 1
                    continue
                if mrow["books"] < args.min_books:
                    misses["too_few_books"] += 1
                    continue
                block = (preds.get((date, pk)) or {}).get(args.segment)
                if not block:
                    misses["model_missing_for_game"] += 1
                    continue
                innings = [{"away": ((i.get("away") or {}).get("runs")),
                            "home": ((i.get("home") or {}).get("runs"))}
                           for i in (game.get("linescore") or {}).get("innings") or []]
                actual = segment_actual(innings, SEGMENT_INNINGS[args.segment])
                if actual is None:
                    misses["segment_never_resolved"] += 1
                    continue
                a_runs, h_runs = actual
                ph = float(block.get("home_win_prob") or 0.0)
                pa = float(block.get("away_win_prob") or 0.0)
                if mrow["three_way"]:
                    model_p = ph
                    outcome = 1 if h_runs > a_runs else 0
                else:
                    if h_runs == a_runs:
                        misses["push_on_two_way"] += 1
                        continue
                    if ph + pa <= 0:
                        misses["model_degenerate"] += 1
                        continue
                    model_p = ph / (ph + pa)
                    outcome = 1 if h_runs > a_runs else 0
                rows.append({"date": date, "game_pk": pk,
                             "model": model_p, "market": mrow["p_home"],
                             "edge": model_p - mrow["p_home"], "home_won": outcome,
                             "three_way": mrow["three_way"], "books": mrow["books"]})

    print(f"\nJOINED n={len(rows)}   skipped: {dict(misses)}")
    if len(rows) < 30:
        print("UNMEASURED: fewer than 30 joined games. Report no rate off this.")
        return 1

    dates = sorted({r["date"] for r in rows})
    print(f"dates actually resting on: {len(dates)}  {dates[0]}..{dates[-1]}")

    def brier(key):
        return sum((r[key] - r["home_won"]) ** 2 for r in rows) / len(rows)

    print(f"\nBRIER over the SAME {len(rows)} games")
    print(f"  model   {brier('model'):.5f}")
    print(f"  market  {brier('market'):.5f}")
    print(f"  delta   {brier('model') - brier('market'):+.5f}"
          f"   (negative = the model is better)")

    print(f"\nWHERE THEY DISAGREE -- by model edge over the market")
    buckets = [(-1.0, -0.05), (-0.05, -0.02), (-0.02, 0.02), (0.02, 0.05), (0.05, 1.0)]
    for lo, hi in buckets:
        sel = [r for r in rows if lo <= r["edge"] < hi]
        if not sel:
            continue
        n = len(sel)
        actual = sum(r["home_won"] for r in sel) / n
        mkt = sum(r["market"] for r in sel) / n
        mdl = sum(r["model"] for r in sel) / n
        se = math.sqrt(max(actual * (1 - actual), 1e-9) / n)
        flag = ""
        if n >= 30:
            flag = "  <- model closer" if abs(actual - mdl) < abs(actual - mkt) else "  <- market closer"
        print(f"  edge [{lo:+.2f},{hi:+.2f})  n={n:4d}  model {mdl:.3f}  "
              f"market {mkt:.3f}  ACTUAL {actual:.3f} +/-{se:.3f}{flag}"
              + ("" if n >= 30 else "   UNMEASURED (n<30)"))

    # The single decisive number: betting the side the model prefers, at the
    # market's own price, over every game where the disagreement clears a bar.
    for bar in (0.02, 0.05):
        sel = [r for r in rows if abs(r["edge"]) >= bar]
        if len(sel) < 30:
            print(f"\nedge>={bar:.0%}: n={len(sel)} UNMEASURED")
            continue
        wins = sum(1 for r in sel
                   if (r["home_won"] == 1) == (r["edge"] > 0))
        exp = sum((r["market"] if r["edge"] > 0 else 1 - r["market"]) for r in sel) / len(sel)
        rate = wins / len(sel)
        se = math.sqrt(rate * (1 - rate) / len(sel))
        print(f"\nBETTING THE MODEL'S SIDE at edge>={bar:.0%}:  n={len(sel)}  "
              f"win rate {rate:.4f}  market expected {exp:.4f}  "
              f"delta {rate - exp:+.4f} ({(rate - exp) / se:+.2f} sigma)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
