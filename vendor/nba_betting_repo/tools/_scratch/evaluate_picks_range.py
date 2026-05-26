import argparse
import datetime as dt
import os
import sys
from dataclasses import dataclass
from typing import Optional

import pandas as pd


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from nba_betting.teams import to_tricode  # noqa: E402


def _date_range(start: dt.date, end: dt.date):
    d = start
    while d <= end:
        yield d
        d = d + dt.timedelta(days=1)


def _american_profit_per_1unit(odds: Optional[float]) -> Optional[float]:
    if odds is None:
        return None
    try:
        o = float(odds)
    except Exception:
        return None
    if pd.isna(o) or o == 0:
        return None
    if o > 0:
        return o / 100.0
    return 100.0 / abs(o)


@dataclass
class GradeResult:
    outcome: str  # win|loss|push|ungraded
    profit: Optional[float]


def _grade_row(row: pd.Series, odds_row: Optional[pd.Series], finals_row: Optional[pd.Series]) -> GradeResult:
    market = str(row.get("market") or "").strip().lower()
    pick = str(row.get("pick") or "").strip().upper()

    if finals_row is None:
        return GradeResult("ungraded", None)

    home_pts = float(finals_row.get("home_pts"))
    away_pts = float(finals_row.get("visitor_pts"))

    odds_val = row.get("odds")
    if pd.isna(odds_val):
        odds_val = None
    profit_if_win = _american_profit_per_1unit(odds_val)

    # Moneyline
    if market == "moneyline":
        if pick not in {"HOME", "AWAY"}:
            return GradeResult("ungraded", None)
        home_win = home_pts > away_pts
        away_win = away_pts > home_pts
        if home_pts == away_pts:
            return GradeResult("push", 0.0)
        won = home_win if pick == "HOME" else away_win
        if profit_if_win is None:
            return GradeResult("ungraded", None)
        return GradeResult("win" if won else "loss", profit_if_win if won else -1.0)

    if odds_row is None:
        return GradeResult("ungraded", None)

    # Spread (ATS)
    if market == "spread":
        if pick not in {"HOME", "AWAY"}:
            return GradeResult("ungraded", None)

        try:
            home_spread = float(odds_row.get("home_spread"))
            away_spread = float(odds_row.get("away_spread"))
        except Exception:
            return GradeResult("ungraded", None)

        if pick == "HOME":
            adj_home = home_pts + home_spread
            cmp = adj_home - away_pts
        else:
            adj_away = away_pts + away_spread
            cmp = adj_away - home_pts

        if cmp == 0:
            return GradeResult("push", 0.0)

        won = cmp > 0
        if profit_if_win is None:
            return GradeResult("ungraded", None)
        return GradeResult("win" if won else "loss", profit_if_win if won else -1.0)

    # Totals
    if market == "total":
        if pick not in {"OVER", "UNDER"}:
            return GradeResult("ungraded", None)
        try:
            total_line = float(odds_row.get("total"))
        except Exception:
            return GradeResult("ungraded", None)

        total_pts = home_pts + away_pts
        if total_pts == total_line:
            return GradeResult("push", 0.0)

        won = (total_pts > total_line) if pick == "OVER" else (total_pts < total_line)
        if profit_if_win is None:
            return GradeResult("ungraded", None)
        return GradeResult("win" if won else "loss", profit_if_win if won else -1.0)

    return GradeResult("ungraded", None)


def main() -> int:
    ap = argparse.ArgumentParser(description="Grade picks_YYYY-MM-DD.csv over a date range.")
    ap.add_argument("--start", required=True, help="YYYY-MM-DD")
    ap.add_argument("--end", required=True, help="YYYY-MM-DD")
    ap.add_argument(
        "--processed-dir",
        default=os.path.join(ROOT, "data", "processed"),
        help="Folder containing picks_*, finals_*, game_odds_* CSVs.",
    )
    ap.add_argument(
        "--out",
        default=None,
        help="Optional output CSV path for detailed graded rows (default: data/processed/picks_eval_<start>_<end>.csv).",
    )

    args = ap.parse_args()
    start = dt.date.fromisoformat(args.start)
    end = dt.date.fromisoformat(args.end)

    processed_dir = args.processed_dir
    if args.out:
        out_path = args.out
    else:
        out_path = os.path.join(processed_dir, f"picks_eval_{start.isoformat()}_{end.isoformat()}.csv")

    all_rows: list[dict] = []
    missing_picks = 0

    for d in _date_range(start, end):
        ds = d.isoformat()
        fp_picks = os.path.join(processed_dir, f"picks_{ds}.csv")
        if not os.path.exists(fp_picks):
            missing_picks += 1
            continue

        fp_odds = os.path.join(processed_dir, f"game_odds_{ds}.csv")
        fp_finals = os.path.join(processed_dir, f"finals_{ds}.csv")

        picks = pd.read_csv(fp_picks)
        odds = pd.read_csv(fp_odds) if os.path.exists(fp_odds) else pd.DataFrame()
        finals = pd.read_csv(fp_finals) if os.path.exists(fp_finals) else pd.DataFrame()

        # Build odds lookup by (date, home_tri, away_tri)
        if len(odds):
            odds = odds.copy()
            odds["home_tri"] = odds["home_team"].map(to_tricode)
            odds["away_tri"] = odds["visitor_team"].map(to_tricode)
        odds_idx = (
            odds.set_index(["date", "home_tri", "away_tri"], drop=False) if len(odds) else None
        )

        # Finals already keyed by (date, home_tri, away_tri)
        finals_idx = (
            finals.set_index(["date", "home_tri", "away_tri"], drop=False) if len(finals) else None
        )

        # Normalize picks key
        picks = picks.copy()
        picks["home_tri"] = picks["home_team"].map(to_tricode)
        picks["away_tri"] = picks["visitor_team"].map(to_tricode)

        for _, r in picks.iterrows():
            key = (r.get("date"), r.get("home_tri"), r.get("away_tri"))
            odds_row = None
            finals_row = None

            if odds_idx is not None and key in odds_idx.index:
                odds_row = odds_idx.loc[key]
                if isinstance(odds_row, pd.DataFrame):
                    odds_row = odds_row.iloc[0]
            if finals_idx is not None and key in finals_idx.index:
                finals_row = finals_idx.loc[key]
                if isinstance(finals_row, pd.DataFrame):
                    finals_row = finals_row.iloc[0]

            grade = _grade_row(r, odds_row, finals_row)
            out = dict(r)
            out["outcome"] = grade.outcome
            out["profit_1u"] = grade.profit
            all_rows.append(out)

    df = pd.DataFrame(all_rows)
    df.to_csv(out_path, index=False)

    def _summarize(label: str, sub: pd.DataFrame):
        graded = sub[sub["outcome"] != "ungraded"].copy()
        n = len(graded)
        if n == 0:
            return {"label": label, "n": 0, "win_rate": None, "roi": None}

        n_win = int((graded["outcome"] == "win").sum())
        n_loss = int((graded["outcome"] == "loss").sum())
        n_push = int((graded["outcome"] == "push").sum())

        # Win rate excludes pushes
        denom = n_win + n_loss
        win_rate = (n_win / denom) if denom > 0 else None

        profit = float(pd.to_numeric(graded["profit_1u"], errors="coerce").fillna(0).sum())
        roi = profit / n

        return {
            "label": label,
            "n": n,
            "n_win": n_win,
            "n_loss": n_loss,
            "n_push": n_push,
            "win_rate": win_rate,
            "roi": roi,
            "profit": profit,
        }

    print(f"Wrote {out_path}")
    print(f"Missing picks files: {missing_picks}")

    if len(df) == 0:
        print("No rows graded.")
        return 0

    summaries = []
    summaries.append(_summarize("ALL", df))
    for m in ["spread", "total", "moneyline"]:
        summaries.append(_summarize(m.upper(), df[df["market"].str.lower() == m]))

    s = pd.DataFrame(summaries)
    print("\nSummary (stake=1 unit per pick):")
    print(s.to_string(index=False))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
