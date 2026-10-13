"""Lift test for matchup signals: does the side win more often, and more than the market says? (lane `signal-engine-nba`)

For each prop line in the snapshot files: the Shin fair per book (production `opportunity_signals.devig`), median
across books; the outcome from the stats.nba game logs (integer-line pushes and DNPs dropped); the as-of signal row for
that player and date (`build_nba_signals.py`). For each registered signal, on the lines where it FIRES (its markets,
its side):

  residual = y - p_shin          lift vs the MARKET (mean, 95% CI bootstrapped over games)
  hit rate vs the baseline       the same side on ELIGIBLE lines where the signal did not fire

per window (DISCOVER / CONFIRM, pre-registered in the lane block), with Benjamini-Hochberg on the CONFIRM p-values.

    python3 scripts/signal_lift.py --data-root ~/syndicate-prod/data --season 2025-26 \\
        --props-dir ~/syndicate-prod/data/backfill/nba_props_2025_26/asof/props_odds_hist \\
        --logs-statsnba ~/syndicate-prod/data/backfill/nba_props_2025_26/cache/statsnba/playergamelogs_2025-26_Regular_Season.json \\
        --out lift.json
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.matchup_signals import (  # noqa: E402
    REGISTRY,
    bh_adjust,
    norm_player,
    read_signal_table,
    residual_stats,
)
from syndicate.features.shared.opportunity_signals import devig  # noqa: E402

WINDOWS = {"discover": ("2025-10-21", "2026-01-31"), "confirm": ("2026-02-01", "2026-04-12")}
MARKET_STATS = {
    "player_points": ("PTS",), "player_rebounds": ("REB",), "player_assists": ("AST",), "player_threes": ("FG3M",),
    "player_points_rebounds_assists": ("PTS", "REB", "AST"), "player_points_rebounds": ("PTS", "REB"),
    "player_points_assists": ("PTS", "AST"), "player_rebounds_assists": ("REB", "AST"),
}


def _eligible(name: str, feats: Mapping[str, Any]) -> bool:
    """Lines where the signal COULD have fired (its inputs are known) -- the baseline population."""
    min10 = feats.get("min_prior10")
    if name in ("nba.minutes_trend_up", "nba.minutes_trend_down"):
        return feats.get("min_trend") is not None
    if name == "nba.start_promotion":
        return feats.get("started_last") is not None
    if name == "nba.b2b":
        return feats.get("rest_days") is not None and min10 is not None and min10 >= 28
    if name == "nba.blowout_risk":
        return feats.get("spread_abs") is not None and min10 is not None and min10 >= 30
    return False


def load_outcomes(path: Path) -> dict[tuple[str, str], dict[str, float]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rs = payload["resultSets"][0]
    idx = {h: i for i, h in enumerate(rs["headers"])}
    out = {}
    for row in rs["rowSet"]:
        stats = {}
        for col in ("PTS", "REB", "AST", "FG3M", "MIN"):
            v = row[idx[col]]
            stats[col] = float(v) if v is not None else None
        out[(norm_player(row[idx["PLAYER_NAME"]]), str(row[idx["GAME_DATE"]])[:10])] = stats
    return out


def load_lines(path: Path) -> list[dict[str, Any]]:
    """One record per (event, market, player, point) with the median Shin fair over two-sided books."""
    books: dict[tuple, dict[str, dict[str, float]]] = defaultdict(lambda: defaultdict(dict))
    with path.open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            market = r.get("market")
            if market not in MARKET_STATS:
                continue
            try:
                point, price = float(r["point"]), float(r["price"])
            except (TypeError, ValueError, KeyError):
                continue
            side = str(r.get("outcome_name") or "").strip().lower()
            if side not in ("over", "under"):
                continue
            key = (r["event_id"], market, norm_player(r.get("player_name")), point)
            books[key][r.get("bookmaker") or ""][side] = price
    lines = []
    for (event, market, player, point), by_book in books.items():
        fairs = []
        for sides in by_book.values():
            if "over" in sides and "under" in sides:
                fair = devig([sides["over"], sides["under"]], method="shin")
                if fair:
                    fairs.append(fair[0])
        if fairs:
            lines.append({"event": event, "market": market, "player_key": player, "point": point,
                          "p_over": statistics.median(fairs), "books": len(fairs)})
    return lines


def evaluate(day_lines: Mapping[str, list[dict[str, Any]]], outcomes: Mapping[tuple[str, str], Mapping[str, float]],
             signals: Mapping[str, Mapping[str, Mapping[str, Any]]]) -> dict[str, Any]:
    fired_rows: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    base_rows: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    joined = dropped_no_outcome = dropped_push = dropped_no_signal = 0
    for day, lines in day_lines.items():
        window = next((w for w, (lo, hi) in WINDOWS.items() if lo <= day <= hi), None)
        if window is None:
            continue
        for line in lines:
            res = outcomes.get((line["player_key"], day))
            if not res or any(res.get(c) is None for c in MARKET_STATS[line["market"]]):
                dropped_no_outcome += 1
                continue
            value = sum(res[c] for c in MARKET_STATS[line["market"]])
            if value == line["point"]:
                dropped_push += 1
                continue
            feats = signals.get(day, {}).get(line["player_key"])
            if feats is None:
                dropped_no_signal += 1
                continue
            joined += 1
            fires = set(feats.get("fires") or ())
            for name, spec in REGISTRY.items():
                if line["market"] not in spec.markets or not _eligible(name, feats):
                    continue
                over = value > line["point"]
                y = 1.0 if (over if spec.side == "over" else not over) else 0.0
                p = line["p_over"] if spec.side == "over" else 1.0 - line["p_over"]
                rec = {"y": y, "p": p, "game": line["event"]}
                (fired_rows if name in fires else base_rows)[(name, window)].append(rec)
    report: dict[str, Any] = {"lines_joined": joined, "dropped_no_outcome": dropped_no_outcome,
                              "dropped_push": dropped_push, "dropped_no_signal_row": dropped_no_signal, "signals": {}}
    confirm_p = {}
    for name, spec in REGISTRY.items():
        entry: dict[str, Any] = {"side": spec.side, "rule": spec.rule}
        for window in WINDOWS:
            fired = residual_stats(fired_rows[(name, window)])
            base = residual_stats(base_rows[(name, window)], B=200)
            entry[window] = {"fired": fired, "baseline": base,
                             "hit_lift_vs_baseline": None if not fired.get("n") or not base.get("n")
                             else round(fired["hit_rate"] - base["hit_rate"], 4)}
        confirm_p[name] = entry["confirm"]["fired"].get("p_one_sided")
        d, c = entry["discover"]["fired"], entry["confirm"]["fired"]
        entry["verdict"] = ("SUPPORTED" if c.get("ci95") and c["ci95"][0] > 0 and (d.get("residual") or 0) > 0
                            else "NOT SUPPORTED")
        report["signals"][name] = entry
    survivors = bh_adjust(confirm_p, q=0.10)
    for name in report["signals"]:
        report["signals"][name]["bh_q10_confirm"] = survivors.get(name, False)
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-root", default=os.environ.get("SYNDICATE_DATA_ROOT") or "")
    ap.add_argument("--season", required=True)
    ap.add_argument("--props-dir", required=True)
    ap.add_argument("--logs-statsnba", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    root = os.path.expanduser(args.data_root)
    outcomes = load_outcomes(Path(os.path.expanduser(args.logs_statsnba)))
    day_lines, signals = {}, {}
    last = max(hi for _, hi in WINDOWS.values())
    for path in sorted(Path(os.path.expanduser(args.props_dir)).glob("*.csv")):
        day = path.stem
        if day > last:
            continue
        day_lines[day] = load_lines(path)
        signals[day] = {r["player_key"]: r for r in read_signal_table(root, "nba", args.season, day)}
    report = evaluate(day_lines, outcomes, signals)
    report["lines_total"] = sum(len(v) for v in day_lines.values())
    Path(args.out).write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"LIFT lines_total={report['lines_total']} joined={report['lines_joined']} "
          f"no_outcome={report['dropped_no_outcome']} push={report['dropped_push']} no_signal={report['dropped_no_signal_row']}")
    for name, e in report["signals"].items():
        for w in WINDOWS:
            f, b = e[w]["fired"], e[w]["baseline"]
            print(f"  {name:24s} {w:8s} fired n={f.get('n')} g={f.get('games')} hit={f.get('hit_rate')} p={f.get('mean_p')} "
                  f"resid={f.get('residual')} ci={f.get('ci95')} | base n={b.get('n')} hit={b.get('hit_rate')} resid={b.get('residual')} "
                  f"| hit_lift={e[w]['hit_lift_vs_baseline']}")
        print(f"  {name:24s} VERDICT {e['verdict']}  BH(q=.10, confirm)={e['bh_q10_confirm']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
