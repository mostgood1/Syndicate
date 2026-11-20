"""Is any live NCAAF game's board row the REVERSE of its live lens's orientation, and is it dark?

Lane college-neutral-site-live-join (todo #854), 2026-11-20. READ-ONLY. Run on the fleet, at nice 19, with the fleet's code:

    cd ~/Syndicate && PYTHONPATH=$HOME/Syndicate SYNDICATE_DATA_ROOT=$HOME/syndicate-prod/data \\
        nice -n 19 ~/.venvs/syndicate/bin/python <this file> --start 2026-10-01 --end 2026-11-19

WHY. NCAAB went dark on neutral-site games whose odds-feed rows were in the reverse order of the ESPN-oriented live lane
(findings_2026-11-19_college_neutral_site_live_join.md). NCAAF has the same shape with a different source:
- the live lens takes home/away from the CFBD projection artifact (`smartsim2_projections_<season>_wk<w>.csv`;
  `scripts/run_refresh_worker.py` `_run_ncaaf_live_resim_tick` builds its `games` from it);
- the rows carry the odds feed's order.

Two orientation failures are possible, and this names both:
1. rows reversed against the lens: the join misses (`no_live_gameline_projection`), and the game is dark while reversed;
2. ESPN reversed against CFBD: the lens looks ESPN's live state up by `away@home` location in CFBD's order, misses, and
   refuses the game `no_live_state` ("no ESPN row matched this game"). The rows join, but to a lane with no number.
   The live evidence log (`live_evidence/ncaaf/<date>.jsonl`, from 11-09) names each dark game's lane refusal.

Measured 2026-11-20 over 10-01..11-19: 0 of 420 live games had rows reversed; 35 direct games had no modelled full-game
row, for other causes.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
from collections import Counter, defaultdict
from pathlib import Path


def _key(name: str) -> str:
    from syndicate.features.shared.team_aliases import chip_join_key

    text = str(name or "").strip()
    return chip_join_key("ncaaf", text) or text.lower()


def _artifact_pairs(root: Path, season: int) -> dict[frozenset, tuple[str, str, str, str, str, str]]:
    out: dict[frozenset, tuple[str, str, str, str, str, str]] = {}
    for path in sorted(root.glob(f"smartsim2_projections_{season}_wk*.csv")):
        with path.open(encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                a, h = _key(row["away_team"]), _key(row["home_team"])
                out[frozenset((a, h))] = (a, h, row["away_team"], row["home_team"], row["week"], row["game_id"])
    return out


def _lane_refusals(data_root: Path, date: str) -> dict[frozenset, Counter]:
    """Unordered pair -> Counter of (lane source, refusal) over the day's evidence-log rows."""
    out: dict[frozenset, Counter] = defaultdict(Counter)
    path = data_root / "live_evidence" / "ncaaf" / f"{date}.jsonl"
    if not path.exists():
        return out
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            a, h = _key(row.get("away_name") or row.get("away")), _key(row.get("home_name") or row.get("home"))
            if a and h:
                out[frozenset((a, h))][f"{row.get('source')}:{row.get('refusal') or '-'}"] += 1
    return out


def run(start: str, end: str, data_root: Path, season: int) -> dict:
    root = data_root / "ncaaf_source" / "data"
    artifact = _artifact_pairs(root, season)
    totals: Counter = Counter()
    games_out: list[dict] = []
    not_in_artifact: set = set()
    day, last = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    while day <= last:
        date = day.isoformat()
        day += dt.timedelta(days=1)
        path = root / "live_gameline_ledger" / f"live_gameline_ledger_{date}.jsonl"
        if not path.exists():
            continue
        totals["ledger_dates"] += 1
        games: dict[frozenset, dict[tuple[str, str], list]] = defaultdict(lambda: defaultdict(lambda: [0, 0, 0, None, None]))
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                a, h = _key(r.get("away_team")), _key(r.get("home_team"))
                if not a or not h or a == h:
                    continue
                cell = games[frozenset((a, h))][(a, h)]
                cell[0] += 1
                if str(r.get("segment") or "") in ("full", "full_game", "game"):
                    cell[1] += 1
                    cell[2] += r.get("model_home_win_prob") is not None
                t = r.get("recorded_at")
                cell[3] = t if cell[3] is None or (t and t < cell[3]) else cell[3]
                cell[4] = t if cell[4] is None or (t and t > cell[4]) else cell[4]
        refusals = _lane_refusals(data_root, date)
        for pair, orients in games.items():
            art = artifact.get(pair)
            if art is None:
                not_in_artifact.add(tuple(sorted(pair)))
                totals["live_games_not_in_artifact"] += 1
                continue
            totals["live_games"] += 1
            direct, rev = orients.get((art[0], art[1])), orients.get((art[1], art[0]))
            lanes = dict(refusals.get(pair) or {})
            if rev:
                totals["reversed"] += 1
                totals["dark_while_reversed"] += rev[2] == 0
            if direct and not rev:
                totals["direct"] += 1
                if direct[2] == 0:
                    totals["direct_dark"] += 1
                    totals["direct_dark_no_live_state"] += any("no_live_state" in k for k in lanes)
            if rev or (direct and direct[2] == 0):
                games_out.append({
                    "date": date, "lens": f"{art[2]} @ {art[3]}", "week": art[4], "event": art[5],
                    "reversed_rows": (rev or [0])[0], "reversed_full_modelled": (rev or [0, 0, 0])[2],
                    "reversed_first_last_utc": [(rev or [0, 0, 0, None, None])[3], (rev or [0, 0, 0, None, None])[4]],
                    "direct_rows": (direct or [0])[0], "direct_full_modelled": (direct or [0, 0, 0])[2],
                    "lane_source_refusal_counts": lanes or "no evidence-log rows (before 11-09, or none)",
                })
    return {"start": start, "end": end, "season": season, "totals": dict(totals),
            "reversed_or_dark_games": games_out, "not_in_artifact": sorted(not_in_artifact)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--root", default=os.environ.get("SYNDICATE_DATA_ROOT") or str(Path.home() / "syndicate-prod" / "data"))
    ap.add_argument("--json", help="write the full result here")
    args = ap.parse_args()
    out = run(args.start, args.end, Path(args.root), args.season)
    if args.json:
        Path(args.json).write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"ncaaf {out['start']}..{out['end']} totals={json.dumps(out['totals'], sort_keys=True)}")
    for g in out["reversed_or_dark_games"]:
        tag = "REVERSED" if g["reversed_rows"] else "DIRECT_DARK"
        print(tag, json.dumps(g, sort_keys=True))
    print("not in any artifact:", out["not_in_artifact"][:20])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
