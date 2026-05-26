from __future__ import annotations

from pathlib import Path

import pandas as pd


def _find_pnl_column(df: pd.DataFrame) -> str:
    for c in ["profit", "pnl", "net", "net_profit", "profit_units", "profit_unit"]:
        if c in df.columns:
            return c
    raise KeyError("No PnL/profit column found")


def roi_units(df: pd.DataFrame, pnl_col: str, stake_col: str | None) -> float:
    pnl = pd.to_numeric(df[pnl_col], errors="coerce").fillna(0.0)
    if stake_col and stake_col in df.columns:
        stake = pd.to_numeric(df[stake_col], errors="coerce").fillna(1.0)
        denom = float(stake.sum())
        return float(pnl.sum()) / denom if denom else 0.0
    # fallback: mean pnl per bet
    return float(pnl.mean())


def main() -> None:
    p = Path("data/processed/props_eval_bets_2026-01-06_2026-01-19_edge0p10_dedupe.csv")
    if not p.exists():
        raise SystemExit(f"Missing file: {p}")

    df = pd.read_csv(p)
    pnl_col = _find_pnl_column(df)
    stake_col = "stake" if "stake" in df.columns else None

    # Coerce required fields
    df["price"] = pd.to_numeric(df.get("price"), errors="coerce")
    df = df[pd.notna(df["price"])].copy()

    base_roi = roi_units(df, pnl_col, stake_col)
    cap = df[(df["price"] >= -150) & (df["price"] <= 150)].copy()
    cap_roi = roi_units(cap, pnl_col, stake_col)

    print("FILE:", p.as_posix())
    print("ROWS:", len(df), "PNL_COL:", pnl_col, "STAKE_COL:", stake_col)
    print("BASE ROI:", base_roi)
    print("CAP[-150,+150] ROI:", cap_roi, "N:", len(cap))

    if "stat" in cap.columns:
        cap["stat"] = cap["stat"].astype(str).str.lower()
        non_pts_pra = cap[~cap["stat"].isin({"pts", "pra"})].copy()
        print(
            "CAP[-150,+150] excl {pts,pra} ROI:",
            roi_units(non_pts_pra, pnl_col, stake_col),
            "N:",
            len(non_pts_pra),
        )

        core = cap[cap["stat"].isin({"reb", "ra", "ast"})].copy()
        print(
            "CAP[-150,+150] only {reb,ra,ast} ROI:",
            roi_units(core, pnl_col, stake_col),
            "N:",
            len(core),
        )

    # points + pra focus
    if "stat" in cap.columns:

        for stat in ["pts", "pra"]:
            part = cap[cap["stat"] == stat]
            if part.empty:
                print(f"{stat}: n=0")
                continue
            print(f"{stat}: n={len(part)} roi={roi_units(part, pnl_col, stake_col)}")
            if "side" in part.columns:
                part["side"] = part["side"].astype(str).str.upper()
                by_side = (
                    part.groupby("side")
                    .apply(lambda g: roi_units(g, pnl_col, stake_col))
                    .sort_values(ascending=False)
                )
                print(f"{stat} ROI by side:\n{by_side.to_string()}")

        # best/worst stats overall under cap
        by_stat = (
            cap.groupby("stat")
            .apply(lambda g: roi_units(g, pnl_col, stake_col))
            .sort_values(ascending=False)
        )
        print("TOP stats (cap):")
        print(by_stat.head(8).to_string())
        print("BOTTOM stats (cap):")
        print(by_stat.tail(8).to_string())


if __name__ == "__main__":
    main()
