"""NHL team metrics for THIS season to date -- a display table for pick explanations, never a sim input.

WHY (lane `intelligence-evidence-coverage`; user 2026-10-08: "update the NHL grids
for this season and find a way to utilize advanced data that includes this
season"). The NHL explanation tables read `team_*_latest.csv`, frozen 2026-08-18/19
on 2025-26. The sim already reads an in-season xG blend (`team_xg_2026-2027.csv`,
lane `nhl-season-inputs-in-season`), and its other season inputs switch to
in-season blends on Nov 1 BY DECISION -- so this script must NOT write any
`<stem>_<season>.csv` the loaders prefer. It writes its own name:

    nhl_source/data/processed/nhl_team_season_to_date_<season>.csv

Per team, 2026-27 REGULAR season only (game_type 2): GP, goals for/against per
game, xGF/xGA per game and xG share (the production shot model, `game_xg`), PP%,
PK%, shots for/against per game, faceoff win% -- each with its league rank.
Inputs are the same cached gamecenter payloads the in-season builders use
(`data/ingestion_cache/`, fetched once per game; a new game costs 3 requests).

    python scripts/build_nhl_season_to_date.py
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

FIELDS = ("abbr", "games", "gf_pg", "ga_pg", "xgf_pg", "xga_pg", "xg_share", "pp_pct", "pk_pct",
          "shots_pg", "shots_against_pg", "faceoff_win_pct")
# (field, higher is better) -- the rank columns written beside each metric
RANKED = (("gf_pg", True), ("ga_pg", False), ("xgf_pg", True), ("xga_pg", False), ("xg_share", True),
          ("pp_pct", True), ("pk_pct", True), ("shots_pg", True), ("shots_against_pg", False), ("faceoff_win_pct", True))


def nhl_root() -> Path:
    override = str(os.environ.get("SYNDICATE_NHL_SOURCE_ROOT") or "").strip()
    if override:
        return Path(override)
    return Path(os.environ.get("SYNDICATE_DATA_ROOT", str(REPO / "data"))) / "nhl_source"


def team_table(payloads: list[Mapping[str, Any]]) -> dict[str, dict[str, float]]:
    """abbr -> metrics, from [{box, landing, pbp}] of finished regular-season games."""
    from syndicate.features.nhl.inseason_season_inputs import current_counts
    from syndicate.features.nhl.inseason_team_xg import game_xg

    counts = current_counts(list(payloads))
    sums: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for rec in counts["records"]:
        for me, opp, gf, ga, sf, sa in (
            (rec.home_abbr, rec.away_abbr, rec.home_goals, rec.away_goals, rec.home_sog, rec.away_sog),
            (rec.away_abbr, rec.home_abbr, rec.away_goals, rec.home_goals, rec.away_sog, rec.home_sog),
        ):
            s = sums[me]
            s["games"] += 1
            s["gf"] += gf
            s["ga"] += ga
            s["sf"] += sf
            s["sa"] += sa
    regular = {str(rec.game_id) for rec in counts["records"]}
    for p in payloads:
        pbp = p.get("pbp")
        if not pbp or str(pbp.get("id") or "") not in regular:
            continue
        got = game_xg(pbp)
        if got is None:
            continue
        home, away, hx, ax = got
        sums[home]["xgf"] += hx
        sums[home]["xga"] += ax
        sums[home]["xg_games"] += 1
        sums[away]["xgf"] += ax
        sums[away]["xga"] += hx
        sums[away]["xg_games"] += 1
    out: dict[str, dict[str, float]] = {}
    for abbr, s in sums.items():
        n = s["games"]
        team = counts["team"].get(abbr, {})
        row: dict[str, float] = {"games": int(n), "gf_pg": s["gf"] / n, "ga_pg": s["ga"] / n,
                                 "shots_pg": s["sf"] / n, "shots_against_pg": s["sa"] / n}
        if s["xg_games"]:
            row["xgf_pg"] = s["xgf"] / s["xg_games"]
            row["xga_pg"] = s["xga"] / s["xg_games"]
            if s["xgf"] + s["xga"] > 0:
                row["xg_share"] = s["xgf"] / (s["xgf"] + s["xga"])
        pp = team.get("pp_pct")
        if pp and pp[1] > 0:
            row["pp_pct"] = pp[0] / pp[1]
        pk = team.get("pk_ga_rate")
        if pk and pk[1] > 0:
            row["pk_pct"] = 1.0 - pk[0] / pk[1]
        fo = team.get("faceoff_pct")
        if fo and fo[1] > 0:
            row["faceoff_win_pct"] = fo[0] / fo[1]
        out[abbr] = row
    for field, higher in RANKED:
        values = [(row[field], abbr) for abbr, row in out.items() if field in row]
        for value, abbr in values:
            better = sum(1 for other, _ in values if (other > value if higher else other < value))
            out[abbr][f"{field}_rank"] = better + 1
    return out


def run(today: dt.date | None = None, *, fetch=None) -> dict[str, Any]:
    from syndicate.features.nhl.inseason_season_inputs import _load_or_fetch
    from syndicate.features.nhl.inseason_team_xg import finished_regular_games, season_code

    today = today or dt.date.today()
    if fetch is None:
        from syndicate.features.nhl.boxscore_log import fetch_json as fetch
    base = "https://api-web.nhle.com/v1"
    root = nhl_root()
    season = season_code(today)
    cache = root / "data" / "ingestion_cache"
    games, unreadable = finished_regular_games(fetch, start=dt.date(int(season[:4]), 9, 15), end=today, base=base, cache_dir=cache)
    counts = {"cached": 0, "fetched": 0, "failed": 0}
    payloads = []
    for g in games:
        gid = g["game_id"]
        payloads.append({
            "box": _load_or_fetch(cache, f"boxscore_{gid}.json", f"{base}/gamecenter/{gid}/boxscore", fetch, counts,
                                  lambda p: bool(p.get("playerByGameStats"))),
            "landing": _load_or_fetch(cache, f"landing_{gid}.json", f"{base}/gamecenter/{gid}/landing", fetch, counts,
                                      lambda p: bool(p.get("summary"))),
            "pbp": _load_or_fetch(cache, f"playbyplay_{gid}.json", f"{base}/gamecenter/{gid}/play-by-play", fetch, counts,
                                  lambda p: bool(p.get("plays"))),
        })
    table = team_table(payloads)
    summary: dict[str, Any] = {"season": season, "finished_games": len(games), "unreadable_days": len(unreadable),
                               "payloads": counts, "teams": len(table)}
    if table:
        out = root / "data" / "processed" / f"nhl_team_season_to_date_{season}.csv"
        out.parent.mkdir(parents=True, exist_ok=True)
        header = list(FIELDS) + [f"{f}_rank" for f, _ in RANKED]
        tmp = out.with_suffix(".csv.tmp")
        with tmp.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=header)
            writer.writeheader()
            for abbr in sorted(table):
                row = table[abbr]
                writer.writerow({"abbr": abbr, **{k: (round(v, 4) if isinstance(v, float) else v) for k, v in row.items()}})
        os.replace(tmp, out)
        summary["written"] = str(out)
    print("[nhl_std] RUN " + " ".join(f"{k}={v}" for k, v in summary.items()), flush=True)
    return summary


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__.split("\n")[0]).parse_args(argv)
    run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
