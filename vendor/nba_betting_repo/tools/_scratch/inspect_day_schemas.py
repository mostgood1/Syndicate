import argparse
from pathlib import Path

import pandas as pd


def main() -> int:
    ap = argparse.ArgumentParser(description="Inspect processed CSV schemas for one day")
    ap.add_argument("--date", required=True, help="YYYY-MM-DD")
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[1]
    processed = root / "data" / "processed"

    ds = args.date
    for fn in [f"predictions_{ds}.csv", f"finals_{ds}.csv", f"game_odds_{ds}.csv"]:
        p = processed / fn
        print("\n---", fn, "exists=", p.exists(), "size=", (p.stat().st_size if p.exists() else None))
        if not p.exists():
            continue
        df = pd.read_csv(p)
        print("rows=", len(df))
        print("cols=", df.columns.tolist())
        print(df.head(3).to_string(index=False))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
