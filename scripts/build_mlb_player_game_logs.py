"""MLB player GAME LOGS across seasons + season hand splits, from the MLB StatsAPI.

WHY (lane `intelligence-evidence-coverage`; user 2026-10-08: "we need robust history - so ensure we have
years of data, not just days - esp for player historic performance"). On the fleet, MLB player history was
the 2026 Statcast pitches (one season, no runs / RBIs) and the feed_live logs (since 2026-06-14). A prop's
"last 10", its "vs this team" and its "vs LHP/RHP" need several seasons.

For every player in this season's Statcast splits (batters and pitchers), per season:
  * `stats=gameLog` -> one row per game (date, opponent, home/away, game type, the prop stats);
  * `stats=statSplits&sitCodes=vl,vr` -> that season's line vs left- and right-handed pitching (hitters)
    or batters (pitchers).
Writes, under `<mlb data root>/derived/`:
    mlb_player_game_log_<season>_hitting.csv / _pitching.csv
    mlb_hand_splits_<season>.csv
INCREMENTAL: a past season's player already FETCHED is not re-fetched -- recorded in
`mlb_player_game_log_<season>_<group>.fetched.json`, because a player with no games that season leaves no row
to prove it; a failed fetch is not recorded, so the next run retries it. The CURRENT season is always
re-fetched (it changes daily). Regular season ("R") and postseason (F/D/L/W) kept and labelled.

    python scripts/build_mlb_player_game_logs.py                   # 2023 .. this season
    python scripts/build_mlb_player_game_logs.py --seasons 2024,2025
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import glob
import json
import os
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable, Iterable

REPO = Path(__file__).resolve().parents[1]
BASE = "https://statsapi.mlb.com/api/v1"
HITTING = ("pa", "ab", "h", "tb", "hr", "rbi", "r", "so", "bb", "hbp")
PITCHING = ("is_starter", "outs", "k", "bb", "er", "h", "hr", "pitches", "batters_faced")
LOG_KEYS = ("date", "season", "game_type", "game_pk", "player_id", "player_name", "team", "opponent", "is_home")
SPLIT_FIELDS = ("season", "group", "player_id", "code", "pa", "ab", "h", "tb", "hr", "so", "bb")
FetchJson = Callable[[str], Any]


def mlb_data_root() -> Path:
    override = str(os.environ.get("SYNDICATE_MLB_DATA_ROOT") or "").strip()
    if override:
        return Path(override)
    return Path(os.environ.get("SYNDICATE_DATA_ROOT", str(REPO / "data"))) / "mlb_source" / "source_artifacts" / "data"


def _fetch(url: str, attempts: int = 3) -> Any:
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                return json.loads(response.read())
        except Exception:  # noqa: BLE001
            if attempt == attempts - 1:
                raise
            time.sleep(4.0 * (attempt + 1))


def _outs(innings: Any) -> int:
    """'6.2' innings -> 20 outs."""
    text = str(innings or "0")
    whole, _, part = text.partition(".")
    try:
        return int(whole or 0) * 3 + int(part or 0)
    except ValueError:
        return 0


def log_rows(group: str, season: int, payload: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for block in payload.get("stats") or []:
        for s in block.get("splits") or []:
            st = s.get("stat") or {}
            row = {
                "date": s.get("date"), "season": season, "game_type": s.get("gameType"),
                "game_pk": (s.get("game") or {}).get("gamePk"), "player_id": (s.get("player") or {}).get("id"),
                "player_name": (s.get("player") or {}).get("fullName"), "team": (s.get("team") or {}).get("name"),
                "opponent": (s.get("opponent") or {}).get("name"), "is_home": int(bool(s.get("isHome"))),
            }
            if group == "hitting":
                row.update(pa=st.get("plateAppearances", 0), ab=st.get("atBats", 0), h=st.get("hits", 0),
                           tb=st.get("totalBases", 0), hr=st.get("homeRuns", 0), rbi=st.get("rbi", 0),
                           r=st.get("runs", 0), so=st.get("strikeOuts", 0), bb=st.get("baseOnBalls", 0),
                           hbp=st.get("hitByPitch", 0))
            else:
                row.update(is_starter=int(bool(st.get("gamesStarted"))), outs=_outs(st.get("inningsPitched")),
                           k=st.get("strikeOuts", 0), bb=st.get("baseOnBalls", 0), er=st.get("earnedRuns", 0),
                           h=st.get("hits", 0), hr=st.get("homeRuns", 0), pitches=st.get("numberOfPitches", 0),
                           batters_faced=st.get("battersFaced", 0))
            if row["date"] and row["player_id"]:
                out.append(row)
    return out


def split_rows(group: str, season: int, player_id: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for block in payload.get("stats") or []:
        for s in block.get("splits") or []:
            code = (s.get("split") or {}).get("code")
            st = s.get("stat") or {}
            if code in ("vl", "vr"):
                out.append({"season": season, "group": group, "player_id": player_id, "code": code,
                            "pa": st.get("plateAppearances", st.get("battersFaced", 0)), "ab": st.get("atBats", 0),
                            "h": st.get("hits", 0), "tb": st.get("totalBases", 0), "hr": st.get("homeRuns", 0),
                            "so": st.get("strikeOuts", 0), "bb": st.get("baseOnBalls", 0)})
    return out


def current_players(root: Path) -> dict[str, set[str]]:
    """{'hitting': batter ids, 'pitching': pitcher ids} from the newest Statcast splits file."""
    files = sorted(glob.glob(str(root / "derived" / "mlb_matchup_splits_*_asof_*.json")))
    if not files:
        raise SystemExit("no mlb_matchup_splits file -- run scripts/build_mlb_matchup_splits.py first")
    payload = json.loads(Path(files[-1]).read_text(encoding="utf-8"))
    return {"hitting": set(payload.get("batters") or {}), "pitching": set(payload.get("pitchers") or {})}


def _read(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write(path: Path, fields: Iterable[str], rows: Iterable[dict[str, Any]]) -> None:
    fields = list(fields)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".csv.tmp")
    with tmp.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fields})
    os.replace(tmp, path)


def run(season: int, *, current: int, fetch: FetchJson = _fetch, pause: float = 0.05) -> dict[str, Any]:
    root = mlb_data_root()
    players = current_players(root)
    summary: dict[str, Any] = {"season": season, "fetched": 0, "kept": 0, "failed": 0}
    split_path = root / "derived" / f"mlb_hand_splits_{season}.csv"
    split_existing = _read(split_path)
    have_split = {(r["group"], r["player_id"]) for r in split_existing}
    splits = [r for r in split_existing if season != current]
    for group, stats in (("hitting", HITTING), ("pitching", PITCHING)):
        path = root / "derived" / f"mlb_player_game_log_{season}_{group}.csv"
        existing = _read(path)
        # WHO WAS FETCHED, not who has rows: a past-season player with no games that season leaves no row,
        # so "has rows" re-fetched him every run (2024: 573 of 1,530, 2025: 385 -- 2026-10-08 hand run).
        fetched_path = path.with_suffix(".fetched.json")
        fetched: set[str] = set()
        if season != current and fetched_path.is_file():
            try:
                fetched = {str(x) for x in json.loads(fetched_path.read_text(encoding="utf-8"))}
            except (OSError, ValueError):
                fetched = set()
        with_rows = {r["player_id"] for r in existing}
        have = (with_rows | fetched) if season != current else set()
        rows: list[dict[str, Any]] = [r for r in existing if r["player_id"] in with_rows and r["player_id"] in have]
        for pid in sorted(players[group]):
            if pid in have:
                summary["kept"] += 1
                continue
            try:
                rows.extend(log_rows(group, season, fetch(f"{BASE}/people/{pid}/stats?stats=gameLog&season={season}&group={group}&gameType=R,F,D,L,W")))
                if season == current or (group, pid) not in have_split:
                    splits.extend(split_rows(group, season, pid, fetch(
                        f"{BASE}/people/{pid}/stats?stats=statSplits&sitCodes=vl,vr&season={season}&group={group}")))
                summary["fetched"] += 1
                fetched.add(pid)
            except Exception as exc:  # noqa: BLE001
                summary["failed"] += 1
                print(f"[mlb_logs] FETCH_FAILED season={season} group={group} player={pid} {type(exc).__name__}", flush=True)
            time.sleep(pause)
        rows.sort(key=lambda r: (str(r["date"]), str(r["player_id"])))
        _write(path, LOG_KEYS + stats, rows)
        if season != current:  # a failed fetch is NOT recorded, so the next run retries it
            tmp = fetched_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(sorted(fetched | with_rows)), encoding="utf-8")
            os.replace(tmp, fetched_path)
        summary[f"{group}_rows"] = len(rows)
    _write(split_path, SPLIT_FIELDS, splits)
    summary["split_rows"] = len(splits)
    print("[mlb_logs] RUN " + " ".join(f"{k}={v}" for k, v in summary.items()), flush=True)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--seasons", default=None, help="comma list; default: three seasons back through this one")
    args = parser.parse_args(argv)
    current = dt.date.today().year
    seasons = [int(s) for s in args.seasons.split(",")] if args.seasons else list(range(current - 3, current + 1))
    for season in seasons:
        try:
            run(season, current=current)
        except Exception as exc:  # noqa: BLE001
            print(f"[mlb_logs] SEASON_FAILED season={season} {type(exc).__name__}: {exc}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
