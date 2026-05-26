from __future__ import annotations

from pathlib import Path

import pandas as pd


def _find_pnl_column(df: pd.DataFrame) -> str:
    for c in ["profit", "pnl", "net", "net_profit", "profit_units", "profit_unit"]:
        if c in df.columns:
            return c
    raise KeyError("No PnL/profit column found")


def roi_mean_profit(df: pd.DataFrame, pnl_col: str) -> float:
    pnl = pd.to_numeric(df[pnl_col], errors="coerce").fillna(0.0)
    return float(pnl.mean()) if len(pnl) else 0.0


def pick_top_play_per_player_day(
    df: pd.DataFrame,
    *,
    core_stats: set[str] | None = None,
    pts_pra_min_edge: float | None = None,
) -> pd.DataFrame:
    out = df.copy()

    out["stat"] = out["stat"].astype(str).str.lower()
    out["side"] = out.get("side", "").astype(str).str.upper()
    out["price"] = pd.to_numeric(out.get("price"), errors="coerce")
    out["ev"] = pd.to_numeric(out.get("ev"), errors="coerce")
    out["edge"] = pd.to_numeric(out.get("edge"), errors="coerce")

    out = out[pd.notna(out["price"])].copy()
    out = out[(out["price"] >= -150) & (out["price"] <= 150)].copy()

    # basic regular market filter
    out = out[out["side"].isin({"OVER", "UNDER"})].copy()
    out = out[~out["stat"].isin({"dd", "td"})].copy()

    if pts_pra_min_edge is not None:
        mask = out["stat"].isin({"pts", "pra"})
        out = out[~mask | (out["edge"].abs() >= float(pts_pra_min_edge))].copy()

    if core_stats:
        core_stats_l = {s.lower() for s in core_stats}
        out["_is_core"] = out["stat"].isin(core_stats_l)
    else:
        out["_is_core"] = False

    # For each (date, player, team), pick best by: core first (if any), then EV desc, then |edge| desc
    group_cols = [c for c in ["date", "player_id", "player_name", "team"] if c in out.columns]
    if not group_cols:
        group_cols = ["date", "player_name"] if "date" in out.columns and "player_name" in out.columns else ["player_name"]

    def _pick_group(g: pd.DataFrame) -> pd.DataFrame:
        gg = g
        if core_stats:
            core = gg[gg["_is_core"]]
            if not core.empty:
                gg = core
        gg = gg.copy()
        gg["_ev"] = gg["ev"].fillna(-1e9)
        gg["_edge_abs"] = gg["edge"].abs().fillna(0.0)
        gg = gg.sort_values(["_ev", "_edge_abs"], ascending=[False, False])
        return gg.head(1)

    picked = out.groupby(group_cols, dropna=False, group_keys=False).apply(_pick_group)
    return picked.drop(columns=[c for c in ["_is_core", "_ev", "_edge_abs"] if c in picked.columns])


def main() -> None:
    p = Path("data/processed/props_eval_bets_2026-01-06_2026-01-19_edge0p10_dedupe.csv")
    df = pd.read_csv(p)

    pnl_col = _find_pnl_column(df)
    df["ev"] = pd.to_numeric(df.get("ev"), errors="coerce")
    df["edge"] = pd.to_numeric(df.get("edge"), errors="coerce")

    base = df.copy()
    print("BASE rows", len(base), "roi(mean_profit)", roi_mean_profit(base, pnl_col))

    top_any = pick_top_play_per_player_day(base, core_stats=None, pts_pra_min_edge=None)
    print("TOP1/player/day (no core) rows", len(top_any), "roi(mean_profit)", roi_mean_profit(top_any, pnl_col))

    top_core = pick_top_play_per_player_day(base, core_stats={"reb", "ra", "ast"}, pts_pra_min_edge=0.15)
    print("TOP1/player/day (core pref + pts/pra edge>=0.15) rows", len(top_core), "roi(mean_profit)", roi_mean_profit(top_core, pnl_col))

    # show stat mix
    if "stat" in top_core.columns:
        mix = top_core["stat"].astype(str).str.lower().value_counts().head(10)
        print("Core-top stat mix:\n", mix.to_string())


if __name__ == "__main__":
    main()
