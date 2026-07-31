from __future__ import annotations

"""Per-pitcher/batter MLB game-log index, built from the raw `feed_live`
game feeds already mirrored under `{data_root}/raw/statsapi/feed_live/`.

No such index exists anywhere else in the repo -- NBA/WNBA/NHL have one
(`boxscores_history.csv`, `player_game_stats.csv`), MLB doesn't. This module
is worker/offline-only (see `scripts/build_mlb_player_game_log.py`): scanning
hundreds of feed files is too heavy to do inside a Flask request, so it's
built here once and read as a small CSV by
`syndicate.blueprints.ask_the_syndicate_data`.
"""

import csv
import glob
import gzip
import json
import os
from typing import Any

from syndicate.features.mlb.cards import _iter_team_players

PITCHER_LOG_FILENAME = "mlb_pitcher_game_log.csv"
BATTER_LOG_FILENAME = "mlb_batter_game_log.csv"

PITCHER_FIELDS = [
    "date", "game_pk", "player_id", "player_name", "team", "opponent",
    "is_starter", "ip", "outs", "pitches", "k", "bb", "er", "h", "r", "hr",
]
BATTER_FIELDS = [
    "date", "game_pk", "player_id", "player_name", "team", "opponent",
    "ab", "h", "r", "rbi", "hr", "bb", "so", "tb",
]


def _to_int(value: Any) -> int:
    try:
        if value is None or isinstance(value, bool):
            return 0
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return 0


def iter_feed_live_files(data_root: str):
    """Yield (date_str, game_pk, path) for every mirrored feed_live file."""
    pattern = os.path.join(data_root, "raw", "statsapi", "feed_live", "*", "*", "*.json*")
    for path in sorted(glob.glob(pattern)):
        if not (path.endswith(".json") or path.endswith(".json.gz")):
            continue
        game_pk_text = os.path.splitext(os.path.basename(path))[0]
        if game_pk_text.endswith(".json"):
            game_pk_text = game_pk_text[: -len(".json")]
        try:
            game_pk = int(game_pk_text)
        except ValueError:
            continue
        date_str = os.path.basename(os.path.dirname(path))
        yield date_str, game_pk, path


def _load_feed(path: str) -> dict[str, Any] | None:
    try:
        raw = open(path, "rb").read()
        if path.endswith(".gz"):
            raw = gzip.decompress(raw)
        payload = json.loads(raw.decode("utf-8"))
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def extract_game_log_rows(
    feed: dict[str, Any], date_str: str, game_pk: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """One completed feed_live payload -> (pitcher_rows, batter_rows)."""
    game_data = feed.get("gameData") if isinstance(feed.get("gameData"), dict) else {}
    status = game_data.get("status") if isinstance(game_data.get("status"), dict) else {}
    if str(status.get("abstractGameState") or "") != "Final":
        return [], []

    teams = game_data.get("teams") if isinstance(game_data.get("teams"), dict) else {}
    team_abbr = {
        side: str((teams.get(side) or {}).get("abbreviation") or "")
        for side in ("away", "home")
    }
    opponent_abbr = {"away": team_abbr.get("home", ""), "home": team_abbr.get("away", "")}

    pitcher_rows: list[dict[str, Any]] = []
    batter_rows: list[dict[str, Any]] = []
    for side in ("away", "home"):
        for player_obj in _iter_team_players(feed, side):
            person = player_obj.get("person") if isinstance(player_obj.get("person"), dict) else {}
            name = str(person.get("fullName") or "").strip()
            try:
                player_id = int(person.get("id") or 0)
            except (TypeError, ValueError):
                player_id = 0
            if not name or player_id <= 0:
                continue
            stats = player_obj.get("stats") if isinstance(player_obj.get("stats"), dict) else {}
            pitching = stats.get("pitching") if isinstance(stats.get("pitching"), dict) else None
            batting = stats.get("batting") if isinstance(stats.get("batting"), dict) else None

            if isinstance(pitching, dict) and pitching:
                pitcher_rows.append({
                    "date": date_str,
                    "game_pk": game_pk,
                    "player_id": player_id,
                    "player_name": name,
                    "team": team_abbr.get(side, ""),
                    "opponent": opponent_abbr.get(side, ""),
                    "is_starter": 1 if _to_int(pitching.get("gamesStarted")) >= 1 else 0,
                    "ip": str(pitching.get("inningsPitched") or "0.0"),
                    "outs": _to_int(pitching.get("outs")),
                    "pitches": _to_int(pitching.get("numberOfPitches")),
                    "k": _to_int(pitching.get("strikeOuts")),
                    "bb": _to_int(pitching.get("baseOnBalls")),
                    "er": _to_int(pitching.get("earnedRuns")),
                    "h": _to_int(pitching.get("hits")),
                    "r": _to_int(pitching.get("runs")),
                    "hr": _to_int(pitching.get("homeRuns")),
                })

            if isinstance(batting, dict) and batting:
                ab = _to_int(batting.get("atBats"))
                pa = _to_int(batting.get("plateAppearances"))
                if ab <= 0 and pa <= 0:
                    continue
                batter_rows.append({
                    "date": date_str,
                    "game_pk": game_pk,
                    "player_id": player_id,
                    "player_name": name,
                    "team": team_abbr.get(side, ""),
                    "opponent": opponent_abbr.get(side, ""),
                    "ab": ab,
                    "h": _to_int(batting.get("hits")),
                    "r": _to_int(batting.get("runs")),
                    "rbi": _to_int(batting.get("rbi")),
                    "hr": _to_int(batting.get("homeRuns")),
                    "bb": _to_int(batting.get("baseOnBalls")),
                    "so": _to_int(batting.get("strikeOuts")),
                    "tb": _to_int(batting.get("totalBases")),
                })

    return pitcher_rows, batter_rows


def _read_existing(path: str) -> tuple[list[dict[str, Any]], set[tuple[int, int]]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[int, int]] = set()
    if not os.path.exists(path):
        return rows, seen
    try:
        with open(path, newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                rows.append(row)
                try:
                    seen.add((int(row["game_pk"]), int(row["player_id"])))
                except (KeyError, TypeError, ValueError):
                    continue
    except Exception:
        return [], set()
    return rows, seen


def _write_csv(path: str, fields: list[str], rows: list[dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})
    os.replace(tmp_path, path)


def bootstrap_mlb_player_game_log(data_root: str) -> dict[str, Any]:
    """Best-effort incremental build/update of the pitcher/batter game-log
    CSVs under `{data_root}/processed/`. Never raises -- skips unreadable
    feed files the same way `_bvp_counts_for_pitcher` skips bad cache files.
    """
    processed_dir = os.path.join(data_root, "processed")
    pitcher_path = os.path.join(processed_dir, PITCHER_LOG_FILENAME)
    batter_path = os.path.join(processed_dir, BATTER_LOG_FILENAME)

    pitcher_rows, pitcher_seen = _read_existing(pitcher_path)
    batter_rows, batter_seen = _read_existing(batter_path)
    known_game_pks = {gp for gp, _ in pitcher_seen} | {gp for gp, _ in batter_seen}

    games_scanned = 0
    games_new = 0
    pitcher_rows_added = 0
    batter_rows_added = 0

    for date_str, game_pk, path in iter_feed_live_files(data_root):
        games_scanned += 1
        if game_pk in known_game_pks:
            continue
        feed = _load_feed(path)
        if feed is None:
            continue
        new_pitcher_rows, new_batter_rows = extract_game_log_rows(feed, date_str, game_pk)
        if not new_pitcher_rows and not new_batter_rows:
            continue
        games_new += 1
        known_game_pks.add(game_pk)
        for row in new_pitcher_rows:
            key = (row["game_pk"], row["player_id"])
            if key in pitcher_seen:
                continue
            pitcher_seen.add(key)
            pitcher_rows.append(row)
            pitcher_rows_added += 1
        for row in new_batter_rows:
            key = (row["game_pk"], row["player_id"])
            if key in batter_seen:
                continue
            batter_seen.add(key)
            batter_rows.append(row)
            batter_rows_added += 1

    if pitcher_rows_added:
        pitcher_rows.sort(key=lambda r: (str(r.get("date") or ""), _to_int(r.get("game_pk"))))
        _write_csv(pitcher_path, PITCHER_FIELDS, pitcher_rows)
    if batter_rows_added:
        batter_rows.sort(key=lambda r: (str(r.get("date") or ""), _to_int(r.get("game_pk"))))
        _write_csv(batter_path, BATTER_FIELDS, batter_rows)

    return {
        "games_scanned": games_scanned,
        "games_new": games_new,
        "pitcher_rows_added": pitcher_rows_added,
        "batter_rows_added": batter_rows_added,
        "pitcher_rows_total": len(pitcher_rows),
        "batter_rows_total": len(batter_rows),
    }
