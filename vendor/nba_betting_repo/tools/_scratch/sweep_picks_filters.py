import argparse
import datetime as dt
import os
import subprocess
import sys
from dataclasses import dataclass

import pandas as pd


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PROCESSED = os.path.join(ROOT, "data", "processed")


def _date_range(start: dt.date, end: dt.date):
    d = start
    while d <= end:
        yield d
        d = d + dt.timedelta(days=1)


def _run(args: list[str]) -> int:
    cp = subprocess.run(args, capture_output=True, text=True)
    if cp.returncode != 0:
        print(cp.stdout)
        print(cp.stderr, file=sys.stderr)
    return cp.returncode


@dataclass
class Combo:
    min_ats_edge: float
    min_ats_ev: float
    ats_blend: float
    min_total_edge: float
    min_total_ev: float
    totals_blend: float

    def label(self) -> str:
        return (
            f"atsEdge{self.min_ats_edge:.2f}_atsEV{self.min_ats_ev:.2f}_atsB{self.ats_blend:.2f}__"
            f"totEdge{self.min_total_edge:.2f}_totEV{self.min_total_ev:.2f}_totB{self.totals_blend:.2f}"
        )


def _summarize(eval_csv: str) -> dict:
    df = pd.read_csv(eval_csv)

    def _summ(sub: pd.DataFrame) -> dict:
        sub = sub[sub["outcome"] != "ungraded"].copy()
        n = int(len(sub))
        if n == 0:
            return {"n": 0, "roi": None, "profit": 0.0}
        profit = float(pd.to_numeric(sub["profit_1u"], errors="coerce").fillna(0).sum())
        roi = profit / n
        return {"n": n, "roi": roi, "profit": profit}

    out = {"ALL": _summ(df)}
    out["SPREAD"] = _summ(df[df["market"].str.lower() == "spread"])
    out["TOTAL"] = _summ(df[df["market"].str.lower() == "total"])
    out["MONEYLINE"] = _summ(df[df["market"].str.lower() == "moneyline"])
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Sweep totals filters by generating picks into per-combo folders and grading them.")
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--topN", type=int, default=10)
    ap.add_argument("--minScore", type=float, default=0.15)

    ap.add_argument("--minAtsEdge", type=float, default=0.05)
    ap.add_argument("--minAtsEV", type=float, default=0.00)
    ap.add_argument("--atsBlend", type=float, default=0.25)

    ap.add_argument("--gridMinTotalEdge", default="0.02,0.03,0.04,0.05")
    ap.add_argument("--gridTotalsBlend", default="0.10,0.25,0.40")
    ap.add_argument("--minTotalEV", type=float, default=0.00)

    ap.add_argument(
        "--sweepRoot",
        default=os.path.join(PROCESSED, "sweeps"),
        help="Base folder where per-combo processed dirs are created.",
    )

    args = ap.parse_args()

    start = dt.date.fromisoformat(args.start)
    end = dt.date.fromisoformat(args.end)

    grid_edges = [float(x) for x in str(args.gridMinTotalEdge).split(",") if str(x).strip()]
    grid_blends = [float(x) for x in str(args.gridTotalsBlend).split(",") if str(x).strip()]

    combos: list[Combo] = []
    for e in grid_edges:
        for b in grid_blends:
            combos.append(
                Combo(
                    min_ats_edge=float(args.minAtsEdge),
                    min_ats_ev=float(args.minAtsEV),
                    ats_blend=float(args.atsBlend),
                    min_total_edge=float(e),
                    min_total_ev=float(args.minTotalEV),
                    totals_blend=float(b),
                )
            )

    py = sys.executable
    recommend = os.path.join(ROOT, "tools", "recommend_picks.py")
    evaluate = os.path.join(ROOT, "tools", "evaluate_picks_range.py")

    rows = []

    for combo in combos:
        out_dir = os.path.join(args.sweepRoot, f"picks_{combo.label()}_{start.isoformat()}_{end.isoformat()}")
        os.makedirs(out_dir, exist_ok=True)

        # Generate picks into this directory
        for d in _date_range(start, end):
            ds = d.isoformat()
            out_path = os.path.join(out_dir, f"picks_{ds}.csv")
            rc = _run(
                [
                    py,
                    recommend,
                    "--date",
                    ds,
                    "--topN",
                    str(int(args.topN)),
                    "--minScore",
                    str(float(args.minScore)),
                    "--minAtsEdge",
                    str(combo.min_ats_edge),
                    "--minAtsEV",
                    str(combo.min_ats_ev),
                    "--atsBlend",
                    str(combo.ats_blend),
                    "--minTotalEdge",
                    str(combo.min_total_edge),
                    "--minTotalEV",
                    str(combo.min_total_ev),
                    "--totalsBlend",
                    str(combo.totals_blend),
                    "--out",
                    out_path,
                ]
            )
            # If missing inputs, recommend exits 0 and doesn't create file; that's OK.
            if rc != 0:
                return rc

        # Copy finals/odds files are read from PROCESSED; evaluator reads from one folder.
        # So: run evaluator against main processed dir but tell it to read picks from out_dir by passing processed-dir=ROOT/data/processed? Not possible.
        # Instead: symlink/copy required finals/odds into out_dir.
        # We'll copy the minimal set (finals_*, game_odds_*) for the window.
        for d in _date_range(start, end):
            ds = d.isoformat()
            for prefix in ("finals_", "game_odds_"):
                src = os.path.join(PROCESSED, f"{prefix}{ds}.csv")
                if os.path.exists(src):
                    dst = os.path.join(out_dir, os.path.basename(src))
                    if not os.path.exists(dst):
                        try:
                            import shutil

                            shutil.copyfile(src, dst)
                        except Exception:
                            pass

        # Grade
        rc = _run([py, evaluate, "--start", start.isoformat(), "--end", end.isoformat(), "--processed-dir", out_dir])
        if rc != 0:
            return rc

        eval_csv = os.path.join(out_dir, f"picks_eval_{start.isoformat()}_{end.isoformat()}.csv")
        summ = _summarize(eval_csv)

        rows.append(
            {
                "minTotalEdge": combo.min_total_edge,
                "totalsBlend": combo.totals_blend,
                "atsEdge": combo.min_ats_edge,
                "atsBlend": combo.ats_blend,
                "n_all": summ["ALL"]["n"],
                "roi_all": summ["ALL"]["roi"],
                "profit_all": summ["ALL"]["profit"],
                "n_total": summ["TOTAL"]["n"],
                "roi_total": summ["TOTAL"]["roi"],
                "profit_total": summ["TOTAL"]["profit"],
                "n_spread": summ["SPREAD"]["n"],
                "roi_spread": summ["SPREAD"]["roi"],
                "profit_spread": summ["SPREAD"]["profit"],
                "n_ml": summ["MONEYLINE"]["n"],
                "roi_ml": summ["MONEYLINE"]["roi"],
                "profit_ml": summ["MONEYLINE"]["profit"],
                "out_dir": out_dir,
            }
        )

    out = pd.DataFrame(rows)
    out = out.sort_values(["roi_all", "n_all"], ascending=[False, False])
    out_path = os.path.join(args.sweepRoot, f"sweep_summary_{start.isoformat()}_{end.isoformat()}.csv")
    out.to_csv(out_path, index=False)

    print(f"Wrote {out_path}")
    # Print top few
    cols = [
        "minTotalEdge",
        "totalsBlend",
        "n_all",
        "roi_all",
        "n_total",
        "roi_total",
        "n_spread",
        "roi_spread",
        "n_ml",
        "roi_ml",
    ]
    print(out[cols].head(12).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
