"""Football UNDERS test (HU-NFL, HU-NCAAF): do prop unders beat the closing market? (lane `signal-engine-football`)

Pre-registered in the lane block ("FOOTBALL v2 PRE-REGISTERED", `817efce7`) before any outcome was loaded -- the
football twin of the NBA H6 test (`nba_unders_test.py`):

  lines       the v1 backfill closes (kickoff - 10 min), ONE main line per (event, market, player), every two-sided
              market in `FOOTBALL_MARKET_STATS`; fair = median per-book Shin (`signal_lift_football.main_lines`)
  windows     NFL discover 2023-24 / confirm 2025; NCAAF 2025 weeks 1-8 / 9-16 (`signal_lift_football.WINDOWS`)
  outcomes    NFL: production's per-play extractors, a player with no qualifying play is VOID; NCAAF: the CFBD box row,
              none -> void; pushes void
  bar         CONFIRM game-clustered 95% CI of the UNDER residual > 0 AND the DISCOVER point estimate > 0
  reported    flat ROI of the under at the best and the median book price; per-market CONFIRM residuals with BH
              q = 0.10; NFL SENSITIVITY: a no-play player on NO injury-report line that week graded as 0, not void

    SYNDICATE_DATA_ROOT=~/syndicate-prod/data python3 scripts/football_unders_test.py --sport nfl \\
        --quotes-dir ~/syndicate-prod/data/backfill/nfl_prop_closes_2023_25 \\
        --injuries-dir ~/syndicate-prod/data/backfill/nfl_injuries_2009_25 --out hu_nfl.json
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
for _p in (REPO_ROOT, REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from nba_unders_test import roi_stats  # noqa: E402
from signal_lift_football import (  # noqa: E402
    WINDOWS,
    _read_jsonl,
    main_lines,
    ncaaf_box_index,
    nfl_outcomes,
    quote_files,
    window_of,
)
from syndicate.features.shared.matchup_signals import bh_adjust, norm_player, residual_stats  # noqa: E402


def injury_listed(path: Path | None, season: int) -> dict[tuple[int, str], set[str]]:
    """(week, team) -> gsis ids with ANY report_status that REG week (Out, Doubtful, Questionable)."""
    out: dict[tuple[int, str], set[str]] = defaultdict(set)
    if path is None or not path.is_file():
        return out
    with path.open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            if str(r.get("season")) == str(season) and (r.get("game_type") or "REG") == "REG" \
                    and (r.get("report_status") or "").strip() and r.get("gsis_id"):
                try:
                    out[(int(r["week"]), r.get("team") or "")].add(r["gsis_id"])
                except (TypeError, ValueError, KeyError):
                    continue
    return out


def grade_lines(sport: str, root: Path, quotes_dir: Path, injuries_dir: Path | None) -> tuple[list[dict], list[dict], dict]:
    """(primary rows, NFL sensitivity rows, counts). Row: {window, stat, game, y, p, under_dec_best, under_dec_median}."""
    from syndicate.features.nfl import player_stats as ps
    from syndicate.features.shared.team_aliases import canonical_team

    seasons = {s for spans in WINDOWS[sport].values() for s, _, _ in spans}
    counts: dict[str, int] = defaultdict(int)
    primary, sensitivity = [], []
    outcomes: dict[int, Any] = {}
    listed: dict[int, Any] = {}
    box_rows = ncaaf_box_index(root, seasons)[1] if sport == "ncaaf" else {}
    for season, week, path in quote_files(quotes_dir):
        window = window_of(sport, season, week)
        if window is None:
            continue
        for line in main_lines(_read_jsonl(path)):
            counts["main_lines"] += 1
            value, sens_value = None, None
            if sport == "nfl":
                teams = {canonical_team("nfl", str(line.get("away_team") or "")),
                         canonical_team("nfl", str(line.get("home_team") or ""))} - {None}
                pid, _src = ps.resolve_player_id_for_game(season, week, line["player"], teams,
                                                          lambda t: canonical_team("nfl", t))
                if pid is None:
                    counts["unresolved_player"] += 1
                    continue
                if season not in outcomes:
                    outcomes[season] = nfl_outcomes(season)
                    inj = injuries_dir / f"injuries_{season}.csv" if injuries_dir else None
                    listed[season] = injury_listed(inj, season)
                res = outcomes[season].get((pid, week))
                if res:
                    value = sens_value = float(res.get(line["stat"]) or 0.0)
                else:
                    team, _ = ps.player_team_with_prior(season, week, pid)
                    if team and pid not in listed[season].get((week, team), set()):
                        sens_value = 0.0
                        counts["sensitivity_zero_graded"] += 1
            else:
                res = box_rows.get((str(line.get("cfbd_game_id") or ""), norm_player(line["player"])))
                if res:
                    value = sens_value = float(res.get(line["stat"]) or 0.0)
            for v, bucket, tag in ((value, primary, "void_no_outcome"), (sens_value, sensitivity, None)):
                if v is None:
                    if tag:
                        counts[tag] += 1
                    continue
                if v == line["point"]:
                    if tag:
                        counts["void_push"] += 1
                    continue
                bucket.append({"window": window, "stat": line["stat"], "game": line["event"],
                               "y": 1.0 if v < line["point"] else 0.0, "p": 1.0 - line["p_over"],
                               "under_dec_best": line["under_dec_best"], "under_dec_median": line["under_dec_median"]})
            if value is not None and value != line["point"]:
                counts["graded"] += 1
    return primary, sensitivity, dict(counts)


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for window in ("discover", "confirm"):
        rs = [r for r in rows if r["window"] == window]
        out[window] = {"residual": residual_stats(rs, B=2000), "roi_best_price": roi_stats(rs, "under_dec_best", B=600),
                       "roi_median_price": roi_stats(rs, "under_dec_median", B=600)}
    d, c = out["discover"]["residual"], out["confirm"]["residual"]
    out["verdict"] = "SUPPORTED" if c.get("ci95") and c["ci95"][0] > 0 and (d.get("residual") or 0) > 0 else "NOT SUPPORTED"
    return out


def per_market_confirm(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by: dict[str, list] = defaultdict(list)
    for r in rows:
        if r["window"] == "confirm":
            by[r["stat"]].append(r)
    report = {m: {"residual": residual_stats(rs, B=600), "roi_best_price": roi_stats(rs, "under_dec_best", B=300)}
              for m, rs in sorted(by.items())}
    for m, keep in bh_adjust({m: e["residual"].get("p_one_sided") for m, e in report.items()}, q=0.10).items():
        report[m]["bh_q10"] = keep
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--sport", choices=("nfl", "ncaaf"), required=True)
    ap.add_argument("--data-root", default=os.environ.get("SYNDICATE_DATA_ROOT") or "")
    ap.add_argument("--quotes-dir", required=True)
    ap.add_argument("--injuries-dir", default=None)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    if not args.data_root:
        print("REFUSING: no --data-root", flush=True)
        return 2
    root = Path(os.path.expanduser(args.data_root))
    inj = Path(os.path.expanduser(args.injuries_dir)) if args.injuries_dir else None
    primary, sens, counts = grade_lines(args.sport, root, Path(os.path.expanduser(args.quotes_dir)), inj)
    name = "HU-NFL" if args.sport == "nfl" else "HU-NCAAF"
    report: dict[str, Any] = {"hypothesis": name, "counts": counts, "primary": summarize(primary),
                              "per_market_confirm": per_market_confirm(primary)}
    if args.sport == "nfl":
        report["sensitivity_no_report_as_zero"] = summarize(sens)
    Path(args.out).write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"{name} counts {counts}", flush=True)
    blocks = [("primary", report["primary"])] + ([("sensitivity", report["sensitivity_no_report_as_zero"])]
                                                 if args.sport == "nfl" else [])
    for label, block in blocks:
        for w in ("discover", "confirm"):
            s, rb, rm = block[w]["residual"], block[w]["roi_best_price"], block[w]["roi_median_price"]
            print(f"  {label:11s} {w:8s} n={s.get('n')} g={s.get('games')} hit={s.get('hit_rate')} p={s.get('mean_p')} "
                  f"resid={s.get('residual')} ci={s.get('ci95')} | ROI best={rb.get('roi_pct')} {rb.get('ci95')} "
                  f"median={rm.get('roi_pct')}", flush=True)
        print(f"  {label:11s} VERDICT {block['verdict']}", flush=True)
    for m, e in report["per_market_confirm"].items():
        s = e["residual"]
        print(f"    confirm {m:18s} n={s.get('n')} resid={s.get('residual')} ci={s.get('ci95')} "
              f"ROI best={e['roi_best_price'].get('roi_pct')} BH={e['bh_q10']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
