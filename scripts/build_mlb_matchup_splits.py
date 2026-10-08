"""MLB matchup splits + a full-season per-game batter log, from the raw Statcast pitches.

WHY (lane `intelligence-evidence-coverage`, phase 2; user 2026-10-08: "focus on
recency and matchups (hitter vs pitcher, hitter vs team, etc)"). Measured gaps
on the fleet 2026-10-08:
  * the batter/pitcher game logs cover 17 dates (feed_live-bound), so "last 10
    games" cannot reach most of the season;
  * no handedness split as COUNTS exists (only sim multipliers), and nothing
    records a batter's line against a particular opposing team.
The raw pitches (`statcast/raw_pitches/<season>/*.csv.gz`, regular season to
09-30, ~756k pitches) carry everything: a plate appearance is a pitch row with a
non-empty `events`; the batter's team comes from the half inning (Top = away).

WRITES, under `<mlb data root>/derived/` (DATED by the newest game included):
  * `mlb_matchup_splits_<season>_asof_<YYYYMMDD>.json` -- per batter: vs LHP /
    vs RHP / vs each opposing team; per pitcher: vs LHB / vs RHB and throwing hand.
    Each cell: pa, ab, h, tb, hr, so, bb, hbp.
  * `mlb_batter_game_log_statcast_<season>.csv` -- one row per batter-game.

Regular season only (`game_type == "R"`).

    python scripts/build_mlb_matchup_splits.py               # season from the newest raw dir
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

REPO = Path(__file__).resolve().parents[1]
SCHEMA = "mlb_matchup_splits_v1"
HITS = {"single": 1, "double": 2, "triple": 3, "home_run": 4}
STRIKEOUTS = {"strikeout", "strikeout_double_play"}
WALKS = {"walk", "intent_walk"}
NOT_AB = WALKS | {"hit_by_pitch", "sac_fly", "sac_bunt", "sac_fly_double_play", "sac_bunt_double_play", "catcher_interf", "truncated_pa"}
CELL = ("pa", "ab", "h", "tb", "hr", "so", "bb", "hbp")
LOG_FIELDS = ("date", "game_pk", "player_id", "team", "opponent", "pa", "ab", "h", "tb", "hr", "so", "bb", "hbp")


def mlb_data_root() -> Path:
    override = str(os.environ.get("SYNDICATE_MLB_DATA_ROOT") or "").strip()
    if override:
        return Path(override)
    return Path(os.environ.get("SYNDICATE_DATA_ROOT", str(REPO / "data"))) / "mlb_source" / "source_artifacts" / "data"


def outcome(event: str) -> dict[str, int]:
    """The plate-appearance counts one `events` value contributes."""
    tb = HITS.get(event, 0)
    return {
        "pa": 1,
        "ab": 0 if event in NOT_AB else 1,
        "h": 1 if tb else 0,
        "tb": tb,
        "hr": 1 if event == "home_run" else 0,
        "so": 1 if event in STRIKEOUTS else 0,
        "bb": 1 if event in WALKS else 0,
        "hbp": 1 if event == "hit_by_pitch" else 0,
    }


def _add(cell: dict[str, int], counts: Mapping[str, int]) -> None:
    for key, value in counts.items():
        cell[key] = cell.get(key, 0) + value


def aggregate(pitches: Iterable[Mapping[str, str]]):
    """(batters, pitchers, game_log, newest_date) from raw pitch rows."""
    batters: dict[str, dict[str, Any]] = defaultdict(lambda: {"vs_L": {}, "vs_R": {}, "vs_team": defaultdict(dict)})
    pitchers: dict[str, dict[str, Any]] = defaultdict(lambda: {"throws": None, "vs_L": {}, "vs_R": {}})
    log: dict[tuple[str, str], dict[str, Any]] = {}
    newest = ""
    for row in pitches:
        event = str(row.get("events") or "").strip()
        if not event or str(row.get("game_type") or "").strip() != "R":
            continue
        batter = str(row.get("batter") or "").strip()
        pitcher = str(row.get("pitcher") or "").strip()
        throws = str(row.get("p_throws") or "").strip().upper()
        stands = str(row.get("stand") or "").strip().upper()
        top = str(row.get("inning_topbot") or "").strip().lower().startswith("top")
        home, away = str(row.get("home_team") or "").strip(), str(row.get("away_team") or "").strip()
        bat_team, opp_team = (away, home) if top else (home, away)
        date = str(row.get("game_date") or "").strip()
        game_pk = str(row.get("game_pk") or "").strip()
        if not batter or not pitcher or throws not in {"L", "R"}:
            continue
        counts = outcome(event)
        b = batters[batter]
        _add(b[f"vs_{throws}"], counts)
        if opp_team:
            _add(b["vs_team"][opp_team], counts)
        p = pitchers[pitcher]
        p["throws"] = throws
        if stands in {"L", "R"}:
            _add(p[f"vs_{stands}"], counts)
        entry = log.setdefault((game_pk, batter), {"date": date, "game_pk": game_pk, "player_id": batter, "team": bat_team, "opponent": opp_team})
        _add(entry, counts)
        newest = max(newest, date)
    return batters, pitchers, log, newest


def run(season: int | None = None) -> dict[str, Any]:
    root = mlb_data_root()
    raw_root = root / "statcast" / "raw_pitches"
    if season is None:
        years = sorted(int(p.name) for p in raw_root.iterdir() if p.is_dir() and p.name.isdigit()) if raw_root.is_dir() else []
        if not years:
            raise SystemExit(f"no raw pitch seasons under {raw_root}")
        season = years[-1]
    files = sorted((raw_root / str(season)).glob("*.csv.gz"))

    def pitches():
        for path in files:
            with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
                yield from csv.DictReader(handle)

    batters, pitchers, log, newest = aggregate(pitches())
    out_dir = root / "derived"
    out_dir.mkdir(parents=True, exist_ok=True)
    asof = newest.replace("-", "") or dt.date.today().strftime("%Y%m%d")
    payload = {
        "schema": SCHEMA, "season": season, "through": newest, "files": len(files),
        "generated_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "cell_fields": list(CELL),
        "batters": {k: {"vs_L": v["vs_L"], "vs_R": v["vs_R"], "vs_team": dict(v["vs_team"])} for k, v in batters.items()},
        "pitchers": dict(pitchers),
    }
    splits_path = out_dir / f"mlb_matchup_splits_{season}_asof_{asof}.json"
    tmp = splits_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(tmp, splits_path)
    log_path = out_dir / f"mlb_batter_game_log_statcast_{season}.csv"
    tmp = log_path.with_suffix(".csv.tmp")
    with tmp.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=LOG_FIELDS)
        writer.writeheader()
        for entry in sorted(log.values(), key=lambda e: (e["date"], e["game_pk"], e["player_id"])):
            writer.writerow({k: entry.get(k, 0) for k in LOG_FIELDS})
    os.replace(tmp, log_path)
    summary = {"season": season, "files": len(files), "through": newest, "batters": len(batters), "pitchers": len(pitchers),
               "batter_games": len(log), "splits": str(splits_path), "log": str(log_path)}
    print("[mlb_splits] RUN " + " ".join(f"{k}={v}" for k, v in summary.items()), flush=True)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--season", type=int, default=None)
    run(parser.parse_args(argv).season)
    return 0


if __name__ == "__main__":
    sys.exit(main())
