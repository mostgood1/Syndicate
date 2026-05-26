from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class TailRule:
    stat: str
    slope: float
    intercept: float
    slack: float

    def limit(self, minutes: float) -> float:
        try:
            m = float(minutes)
            if not np.isfinite(m) or m < 0:
                m = 0.0
        except Exception:
            m = 0.0
        return float(np.floor(self.slope * m + self.intercept + self.slack))


DEFAULT_RULES: list[TailRule] = [
    # These mirror the caps in connected_game.py but include small slack.
    TailRule("ast_sim", slope=0.44, intercept=1.0, slack=2.0),
    TailRule("reb_sim", slope=0.45, intercept=2.0, slack=3.0),
    TailRule("threes_sim", slope=0.30, intercept=1.0, slack=1.0),
    TailRule("tov_sim", slope=0.30, intercept=1.0, slack=2.0),
    TailRule("stl_sim", slope=0.12, intercept=1.0, slack=1.0),
    TailRule("blk_sim", slope=0.10, intercept=1.0, slack=1.0),
    # Points are higher-variance; keep the check loose.
    TailRule("pts_sim", slope=1.10, intercept=6.0, slack=8.0),

    # Attempts + fouls: keep ceilings minutes-driven.
    TailRule("fga_sim", slope=0.75, intercept=4.0, slack=4.0),
    TailRule("fg3a_sim", slope=0.50, intercept=2.0, slack=3.0),
    TailRule("fta_sim", slope=0.35, intercept=2.0, slack=3.0),
    TailRule("pf_sim", slope=0.18, intercept=1.0, slack=1.0),
]


def _newest_csv(glob_pat: str) -> Path | None:
    paths = [Path(p) for p in sorted(Path().glob(glob_pat))]
    if not paths:
        return None
    try:
        paths.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    except Exception:
        pass
    return paths[0]


def _to_num_series(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series([0.0] * len(df))
    return pd.to_numeric(df[col], errors="coerce").fillna(0.0)


def audit_players_csv(df: pd.DataFrame, rules: Iterable[TailRule]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "rows": int(len(df)),
        "violations": [],
        "percentiles": {},
        "max": {},
    }

    if df.empty:
        return out

    min_sim = _to_num_series(df, "min_sim")

    # percentile + max summary for common stats
    for c in [
        "min_sim",
        "pts_sim",
        "reb_sim",
        "ast_sim",
        "threes_sim",
        "tov_sim",
        "stl_sim",
        "blk_sim",
        "fga_sim",
        "fgm_sim",
        "fg3a_sim",
        "fta_sim",
        "ftm_sim",
        "pf_sim",
    ]:
        if c in df.columns:
            s = _to_num_series(df, c)
            out["max"][c] = float(s.max())
            out["percentiles"][c] = {
                "p95": float(np.quantile(s, 0.95)),
                "p99": float(np.quantile(s, 0.99)),
            }

    # basic minutes sanity
    out["counts"] = {
        "min_ge_40": int((min_sim >= 40).sum()),
        "min_ge_44": int((min_sim >= 44).sum()),
        "min_ge_48": int((min_sim >= 48).sum()),
    }

    # rule-based checks: stat <= floor(slope*min + intercept + slack)
    for rule in rules:
        if rule.stat not in df.columns:
            continue
        stat = _to_num_series(df, rule.stat)
        lim = min_sim.map(rule.limit)
        bad = stat > lim
        n_bad = int(bad.sum())
        if n_bad <= 0:
            continue

        worst = df.loc[bad].copy()
        worst["_limit"] = lim[bad].values
        worst["_stat"] = stat[bad].values
        cols = [c for c in ["date", "game_id", "team", "player_name", "player_key"] if c in worst.columns]
        cols += ["min_sim", rule.stat, "_limit"]
        worst = worst.sort_values(rule.stat, ascending=False).head(12)

        out["violations"].append(
            {
                "rule": {
                    "stat": rule.stat,
                    "slope": rule.slope,
                    "intercept": rule.intercept,
                    "slack": rule.slack,
                },
                "count": n_bad,
                "examples": worst[cols].to_dict(orient="records"),
            }
        )

    # Logical constraints (make <= attempt, and 3PM <= 3PA/FGM)
    def _add_constraint(name: str, bad_mask: pd.Series, extra_cols: list[str]) -> None:
        try:
            n_bad = int(bad_mask.sum())
            if n_bad <= 0:
                return
            worst = df.loc[bad_mask].copy()
            cols = [c for c in ["date", "game_id", "team", "player_name", "player_key"] if c in worst.columns]
            cols += [c for c in ["min_sim"] + extra_cols if c in worst.columns]
            worst = worst.sort_values(extra_cols[0], ascending=False).head(12) if extra_cols else worst.head(12)
            out["violations"].append(
                {
                    "rule": {"stat": name, "type": "constraint"},
                    "count": n_bad,
                    "examples": worst[cols].to_dict(orient="records"),
                }
            )
        except Exception:
            return

    if ("fgm_sim" in df.columns) and ("fga_sim" in df.columns):
        fgm = _to_num_series(df, "fgm_sim")
        fga = _to_num_series(df, "fga_sim")
        _add_constraint("fgm_le_fga", fgm > fga, ["fgm_sim", "fga_sim"])

    if ("ftm_sim" in df.columns) and ("fta_sim" in df.columns):
        ftm = _to_num_series(df, "ftm_sim")
        fta = _to_num_series(df, "fta_sim")
        _add_constraint("ftm_le_fta", ftm > fta, ["ftm_sim", "fta_sim"])

    # threes_sim is FG3M in the evaluator output.
    if ("threes_sim" in df.columns) and ("fg3a_sim" in df.columns):
        fg3m = _to_num_series(df, "threes_sim")
        fg3a = _to_num_series(df, "fg3a_sim")
        _add_constraint("fg3m_le_fg3a", fg3m > fg3a, ["threes_sim", "fg3a_sim"])

    if ("threes_sim" in df.columns) and ("fgm_sim" in df.columns):
        fg3m = _to_num_series(df, "threes_sim")
        fgm = _to_num_series(df, "fgm_sim")
        _add_constraint("fg3m_le_fgm", fg3m > fgm, ["threes_sim", "fgm_sim"])

    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Audit connected sim player stat tails for realism/predictability")
    ap.add_argument(
        "--players-csv",
        default="",
        help="Path to connected_realism_players_*.csv. If omitted, uses newest under data/processed.",
    )
    ap.add_argument(
        "--glob",
        default="data/processed/connected_realism_players_*.csv",
        help="Glob used to find newest csv when --players-csv not provided.",
    )
    ap.add_argument("--out-json", default="", help="Optional path to write audit report JSON.")
    ap.add_argument(
        "--fail",
        choices=["never", "any"],
        default="any",
        help="Exit non-zero if violations found.",
    )
    args = ap.parse_args()

    csv_path = Path(args.players_csv) if args.players_csv else (_newest_csv(args.glob) or Path(""))
    if not csv_path or not str(csv_path) or not csv_path.exists():
        print(f"No players CSV found (players-csv='{args.players_csv}' glob='{args.glob}')")
        return 2

    df = pd.read_csv(csv_path)
    report = audit_players_csv(df, DEFAULT_RULES)
    report["players_csv"] = str(csv_path).replace("\\", "/")

    # Pretty print summary
    print(f"Audit CSV: {report['players_csv']}")
    print(f"Rows: {report['rows']}")
    if "counts" in report:
        print("Minutes counts:", report["counts"])
    if report.get("max"):
        mx = report["max"]
        print("Max:", {k: mx[k] for k in sorted(mx.keys())})

    v = report.get("violations") or []
    if v:
        print(f"Violations: {len(v)} rule(s)")
        for item in v:
            r = item.get("rule") or {}
            print(f" - {r.get('stat')}: {item.get('count')} rows exceed minutes-based limit")
        if args.fail == "any":
            rc = 1
        else:
            rc = 0
    else:
        print("Violations: none")
        rc = 0

    if args.out_json:
        out_path = Path(args.out_json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        disp = str(out_path).replace("\\", "/")
        print(f"Wrote: {disp}")

    return rc


if __name__ == "__main__":
    raise SystemExit(main())
