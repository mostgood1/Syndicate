import os
import pandas as pd
import numpy as np
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
_DATA_ROOT_ENV = (os.environ.get("NBA_BETTING_DATA_ROOT") or "").strip()
DATA_ROOT = Path(_DATA_ROOT_ENV).expanduser().resolve() if _DATA_ROOT_ENV else (BASE_DIR / "data")
PROC_DIR = DATA_ROOT / "processed"


def norm_key(s: str) -> str:
    if not isinstance(s, str):
        return ""
    s = s.upper()
    for ch in ["'", ".", ",", "-", "\u2019"]:
        s = s.replace(ch, "")
    s = " ".join(s.split())
    return s


def find_expected_minutes_file(date_str: str) -> str | None:
    candidates = [
        PROC_DIR / f"pregame_expected_minutes_{date_str}.csv",
        PROC_DIR / "_bak_expected_minutes_eval" / f"pregame_expected_minutes_{date_str}.csv",
        PROC_DIR / "_bak_expected_minutes" / f"pregame_expected_minutes_{date_str}.csv",
    ]
    for cand in candidates:
        if cand.exists():
            return str(cand)
    return None


def main():
    g_path = str(PROC_DIR / "connected_realism_games_2026-02-10_2026-02-12.csv")
    p_path = str(PROC_DIR / "connected_realism_players_2026-02-10_2026-02-12.csv")

    g = pd.read_csv(g_path)
    p = pd.read_csv(p_path)

    gid = 22500782
    row = g.loc[g.game_id == gid].iloc[0]

    print("GAME", gid, row["date"], row["away_tri"], "@", row["home_tri"])
    print("away_min_mae_topk", row["away_min_mae_topk"], "home_min_mae_topk", row["home_min_mae_topk"])
    print("away_source", row.get("away_minutes_source"), "away_signal_n", row.get("away_minutes_signal_n"))
    print("home_source", row.get("home_minutes_source"), "home_signal_n", row.get("home_minutes_signal_n"))

    pp = p.loc[p.game_id == gid].copy()
    print("\nTeams in player rows:", sorted(pp["team"].unique()))

    for team in sorted(pp["team"].unique()):
        t = pp.loc[pp.team == team].copy()
        t["abs_err"] = (t["min_sim"] - t["min_act"]).abs()
        print("\n==", team, "== n", len(t), "sum_act", float(t["min_act"].sum()), "sum_sim", float(t["min_sim"].sum()))
        print("Top abs minute errors:")
        cols = ["player_name", "min_act", "min_sim", "abs_err", "minutes_source"]
        cols = [c for c in cols if c in t.columns]
        print(t.sort_values("abs_err", ascending=False)[cols].head(12).to_string(index=False))

    exp_path = find_expected_minutes_file(row["date"])
    print("\nexpected-minutes file:", exp_path)
    if not exp_path:
        return

    exp = pd.read_csv(exp_path)
    exp["team"] = exp["team_tri"].astype(str).str.upper()
    exp["_pkey"] = exp["player_name"].map(norm_key)

    if "exp_asof_ts" in exp.columns:
        exp = exp.sort_values("exp_asof_ts").drop_duplicates(["team", "_pkey"], keep="last")

    for team in sorted(pp["team"].unique()):
        actual = pp.loc[pp.team == team].copy()
        actual["_pkey"] = actual["player_name"].map(norm_key)
        exp_t = exp.loc[exp.team == team].copy()

        m = set(actual["_pkey"]) & set(exp_t["_pkey"])
        miss = sorted(set(actual["_pkey"]) - set(exp_t["_pkey"]))
        print(f"\nCoverage {team}: actual_players={len(actual)} match={len(m)} miss={len(miss)}")
        if miss:
            print("Missing examples:", miss[:12])


if __name__ == "__main__":
    main()
