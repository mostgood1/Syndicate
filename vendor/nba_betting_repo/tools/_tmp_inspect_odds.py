from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def _try_read_csv(path: Path) -> pd.DataFrame | None:
    try:
        return pd.read_csv(path)
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="YYYY-MM-DD")
    args = ap.parse_args()

    d = str(args.date).strip()
    proc = Path("data") / "processed"

    names = [
        f"game_odds_{d}.csv",
        f"odds_snapshot_{d}.csv",
        f"odds_{d}.csv",
        f"closing_lines_{d}.csv",
        f"lines_{d}.csv",
        f"period_lines_{d}.csv",
    ]

    for name in names:
        p = proc / name
        print(name, "exists" if p.exists() else "MISSING")
        if not p.exists():
            continue

        df = _try_read_csv(p)
        if df is None:
            print("  read error")
            continue

        print("  shape", df.shape)
        print("  cols", list(df.columns))
        try:
            print("  head", df.head(2).to_dict(orient="records"))
        except Exception:
            pass

    cands = sorted(
        [
            p.name
            for p in proc.glob(f"*{d}*.csv")
            if ("odds" in p.name.lower() or "line" in p.name.lower())
        ]
    )
    print("Candidates:", cands)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
