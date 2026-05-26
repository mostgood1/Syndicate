from __future__ import annotations

import ast
import json
from pathlib import Path

import pandas as pd


def _parse_list(val):
    if isinstance(val, list):
        return val
    s = str(val or "").strip()
    if s in {"", "None", "nan"}:
        return []
    try:
        v = json.loads(s)
        return v if isinstance(v, list) else []
    except Exception:
        try:
            v = ast.literal_eval(s)
            return v if isinstance(v, list) else []
        except Exception:
            return []


def main() -> None:
    date_str = "2026-01-20"
    cards_p = Path(f"data/processed/props_recommendations_{date_str}.csv")
    if not cards_p.exists():
        raise SystemExit(f"Missing: {cards_p}")

    cards = pd.read_csv(cards_p)
    plays_rows: list[dict] = []
    for _, row in cards.iterrows():
        for pl in _parse_list(row.get("plays")):
            if not isinstance(pl, dict):
                continue
            rec = dict(pl)
            rec["player"] = row.get("player")
            rec["team"] = row.get("team")
            plays_rows.append(rec)

    plays = pd.DataFrame(plays_rows)
    print("CARDS:", cards_p.as_posix())
    print("cards:", len(cards))
    print("plays:", len(plays))

    if plays.empty:
        return

    plays["market"] = plays.get("market", "").astype(str).str.lower()
    plays["side"] = plays.get("side", "").astype(str).str.upper()
    plays["price"] = pd.to_numeric(plays.get("price"), errors="coerce")
    plays["edge"] = pd.to_numeric(plays.get("edge"), errors="coerce")
    plays["ev"] = pd.to_numeric(plays.get("ev"), errors="coerce")

    bad_price = plays[(plays["price"].notna()) & ((plays["price"] < -150) | (plays["price"] > 150))]
    print("plays outside [-150,+150]:", len(bad_price))

    print("\nmarket mix (top 12):")
    print(plays["market"].value_counts().head(12).to_string())

    for m in ["pts", "pra"]:
        part = plays[plays["market"] == m]
        print(f"\n{m}: n={len(part)}")
        if not part.empty:
            print(" price min/max:", float(part["price"].min()), float(part["price"].max()))
            print(" edge mean:", float(part["edge"].mean()))
            print(" ev mean:", float(part["ev"].mean()))
            cols = [c for c in ["player", "team", "market", "side", "line", "price", "edge", "ev", "book"] if c in part.columns]
            print(" top 10 EV:\n", part.sort_values("ev", ascending=False)[cols].head(10).to_string(index=False))


if __name__ == "__main__":
    main()
