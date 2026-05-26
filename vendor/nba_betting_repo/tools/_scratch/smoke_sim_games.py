from __future__ import annotations

import argparse

from nba_betting.sim_games import simulate_games_for_date


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    args = ap.parse_args()

    df = simulate_games_for_date(args.date)
    print("rows", len(df))
    if not df.empty:
        cols = [c for c in ("home_team", "visitor_team", "p_home_cover", "p_home_win", "spread_line", "total_line") if c in df.columns]
        print(df[cols].head(10).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
