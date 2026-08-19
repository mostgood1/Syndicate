from __future__ import annotations

import datetime as dt
import importlib
from pathlib import Path
from typing import Any


def _to_int(value: Any) -> int:
    try:
        import pandas as pd

        numeric = pd.to_numeric(value, errors="coerce")
        if pd.isna(numeric):
            return 0
        return int(float(numeric))
    except Exception:
        return 0


def _to_minutes(value: Any) -> float:
    try:
        import pandas as pd

        text = str(value or "").strip()
        if not text:
            return 0.0
        if ":" in text:
            minutes_text, seconds_text = text.split(":", 1)
            minutes = pd.to_numeric(minutes_text, errors="coerce")
            seconds = pd.to_numeric(seconds_text, errors="coerce")
            if pd.isna(minutes) or pd.isna(seconds):
                return 0.0
            return float(minutes) + (float(seconds) / 60.0)
        numeric = pd.to_numeric(text, errors="coerce")
        if pd.isna(numeric):
            return 0.0
        return float(numeric)
    except Exception:
        return 0.0


def _parse_made_attempted(value: Any) -> tuple[int, int]:
    text = str(value or "").strip()
    if not text:
        return 0, 0
    if "-" not in text:
        numeric = _to_int(text)
        return numeric, numeric
    left, right = text.split("-", 1)
    return _to_int(left), _to_int(right)


def _history_key_columns(columns: list[str]) -> list[str]:
    for candidate in (["game_id", "PLAYER_ID"], ["game_id", "TEAM_ABBREVIATION", "PLAYER_NAME"]):
        if all(column in columns for column in candidate):
            return candidate
    return []


def _read_existing_history(processed_root: Path):
    import pandas as pd

    parquet_path = processed_root / "boxscores_history.parquet"
    csv_path = processed_root / "boxscores_history.csv"
    if parquet_path.exists():
        try:
            return pd.read_parquet(parquet_path)
        except Exception:
            pass
    if csv_path.exists():
        try:
            return pd.read_csv(csv_path)
        except Exception:
            pass
    return pd.DataFrame()


def _write_history(processed_root: Path, history_df) -> str | None:
    parquet_path = processed_root / "boxscores_history.parquet"
    csv_path = processed_root / "boxscores_history.csv"
    try:
        history_df.to_parquet(parquet_path, index=False)
        return str(parquet_path)
    except Exception:
        try:
            history_df.to_csv(csv_path, index=False)
            return str(csv_path)
        except Exception:
            return None


def _event_rows_from_summary(*, summary: dict[str, Any], event_id: str, date_str: str, league_code: str):
    rows: list[dict[str, Any]] = []
    smart_sim_module = importlib.import_module("syndicate.features.shared.basketball_props_smart_sim")
    espn_to_tri = getattr(smart_sim_module, "_espn_to_tri_local")

    boxscore = (summary or {}).get("boxscore") or {}
    teams = boxscore.get("players") or []
    if not isinstance(teams, list):
        return rows

    for team_payload in teams:
        team = (team_payload or {}).get("team") or {}
        team_abbr = str(team.get("abbreviation") or "").strip().upper()
        team_tri = espn_to_tri(team_abbr, league_code=league_code) if team_abbr else ""
        stat_groups = (team_payload or {}).get("statistics") or []
        if not isinstance(stat_groups, list) or not stat_groups:
            continue
        group = stat_groups[0] or {}
        labels = group.get("labels") or []
        athletes = group.get("athletes") or []
        if not isinstance(labels, list) or not isinstance(athletes, list):
            continue

        for athlete_payload in athletes:
            athlete = (athlete_payload or {}).get("athlete") or {}
            player_name = str(athlete.get("displayName") or "").strip()
            if not player_name:
                continue
            stats = athlete_payload.get("stats") or []
            if not isinstance(stats, list):
                stats = []
            stat_map = {str(label): (stats[idx] if idx < len(stats) else None) for idx, label in enumerate(labels)}
            field_goals_made, field_goals_attempted = _parse_made_attempted(stat_map.get("FG"))
            threes_made, threes_attempted = _parse_made_attempted(stat_map.get("3PT"))
            free_throws_made, free_throws_attempted = _parse_made_attempted(stat_map.get("FT"))
            player_id = str(athlete.get("id") or "").strip()
            rows.append(
                {
                    "game_id": str(event_id),
                    "gameId": str(event_id),
                    "TEAM_ABBREVIATION": str(team_tri),
                    "PLAYER_ID": int(player_id) if player_id.isdigit() else None,
                    "PLAYER_NAME": player_name,
                    "MIN": _to_minutes(stat_map.get("MIN")),
                    "PTS": _to_int(stat_map.get("PTS")),
                    "REB": _to_int(stat_map.get("REB")),
                    "AST": _to_int(stat_map.get("AST")),
                    "STL": _to_int(stat_map.get("STL")),
                    "BLK": _to_int(stat_map.get("BLK")),
                    "TOV": _to_int(stat_map.get("TO")),
                    "OREB": _to_int(stat_map.get("OREB")),
                    "DREB": _to_int(stat_map.get("DREB")),
                    "PF": _to_int(stat_map.get("PF")),
                    "FGM": field_goals_made,
                    "FGA": field_goals_attempted,
                    "FG3M": threes_made,
                    "FG3A": threes_attempted,
                    "FTM": free_throws_made,
                    "FTA": free_throws_attempted,
                    "PLUS_MINUS": _to_int(stat_map.get("+/-")),
                    "STARTER": bool(athlete_payload.get("starter")),
                    "START_POSITION": str(((athlete.get("position") or {}).get("abbreviation")) or ""),
                    "source": "espn",
                    "date": str(date_str),
                }
            )
    return rows


def boxscore_history_max_date(processed_root: Path) -> Any:
    """Latest recorded game date in boxscores_history.{parquet,csv}, or None.

    Reads only the "date" column (fast even on the ~20MB NBA history) rather
    than loading the full frame -- used as a cheap freshness check before
    deciding whether to re-run the (network-fetching) bootstrap below.
    """
    import pandas as pd

    parquet_path = processed_root / "boxscores_history.parquet"
    csv_path = processed_root / "boxscores_history.csv"
    try:
        if parquet_path.exists():
            frame = pd.read_parquet(parquet_path, columns=["date"])
        elif csv_path.exists():
            frame = pd.read_csv(csv_path, usecols=["date"])
        else:
            return None
        if frame.empty or "date" not in frame.columns:
            return None
        parsed = pd.to_datetime(frame["date"], errors="coerce")
        if parsed.isna().all():
            return None
        return parsed.max()
    except Exception:
        return None


def boxscore_history_is_stale(processed_root: Path, *, max_age_days: int) -> bool:
    """True when the history file is missing, empty, or its newest game is
    older than max_age_days. bootstrap_boxscores_history_local only ever
    writes data through "yesterday" relative to the date it's run for, so a
    file that's merely a day or two behind is normal, not stale.
    """
    import pandas as pd

    max_date = boxscore_history_max_date(processed_root)
    if max_date is None:
        return True
    age_days = (pd.Timestamp.now().normalize() - max_date.normalize()).days
    return age_days > max(0, int(max_age_days))


def bootstrap_boxscores_history_local(*, processed_root: Path, date_str: str, league_code: str, lookback_days: int = 35) -> dict[str, Any]:
    import pandas as pd

    processed_root.mkdir(parents=True, exist_ok=True)
    smart_sim_module = importlib.import_module("syndicate.features.shared.basketball_props_smart_sim")
    espn_scoreboard = getattr(smart_sim_module, "_espn_scoreboard_local")
    espn_summary = getattr(smart_sim_module, "_espn_summary_local")
    espn_to_tri = getattr(smart_sim_module, "_espn_to_tri_local")

    requested_date = pd.to_datetime(str(date_str or ""), errors="coerce", utc=True)
    if pd.isna(requested_date):
        return {"date": str(date_str), "rows": 0, "history_rows": 0, "wrote": None, "error": "invalid_date"}
    requested_date = requested_date.tz_localize(None)

    current_utc = pd.Timestamp.now(tz="UTC").tz_localize(None)
    end_date = min(requested_date.normalize() - pd.Timedelta(days=1), current_utc.normalize() - pd.Timedelta(days=1))
    if pd.isna(end_date):
        return {"date": str(date_str), "rows": 0, "history_rows": 0, "wrote": None, "error": "invalid_end_date"}
    start_date = end_date - pd.Timedelta(days=max(0, int(lookback_days) - 1))

    # Diagnostics for the caller (`_bootstrap_local_boxscores_history_for_props`):
    # `_espn_scoreboard_local` swallows every fetch exception/non-OK status and
    # returns `{}` (falsy). A genuinely gameless day returns a TRUTHY dict with
    # an empty `events` list, so `scoreboard` being falsy specifically means the
    # HTTP call itself failed -- not "no games" -- and is distinguishable from
    # here without touching the fetch helper. This was previously invisible:
    # the loop below silently accumulated zero rows on total fetch failure,
    # `combined` fell back to `existing_history` unchanged, and the write below
    # still succeeded (fresh mtime, stale content) -- the exact shape that let
    # boxscores_history.csv sit frozen at 2026-06-30 while its own mtime kept
    # advancing every bootstrap tick, reporting as "handled" indefinitely.
    days_checked = 0
    days_fetch_failed = 0
    frames = []
    current = start_date
    while current <= end_date:
        current_date = current.strftime("%Y-%m-%d")
        days_checked += 1
        scoreboard = espn_scoreboard(processed_root=processed_root, date_str=current_date, league_code=league_code, force=False)
        if not scoreboard:
            days_fetch_failed += 1
        events = scoreboard.get("events") if isinstance(scoreboard, dict) else None
        day_rows: list[dict[str, Any]] = []
        if isinstance(events, list):
            for event in events:
                try:
                    event_id = str((event or {}).get("id") or "").strip()
                    if not event_id:
                        continue
                    competitions = (event or {}).get("competitions") or []
                    if not competitions:
                        continue
                    competitors = (competitions[0] or {}).get("competitors") or []
                    home_team = next((item for item in competitors if str((item or {}).get("homeAway") or "") == "home"), None)
                    away_team = next((item for item in competitors if str((item or {}).get("homeAway") or "") == "away"), None)
                    if not home_team or not away_team:
                        continue
                    home_abbr = str((((home_team or {}).get("team") or {}).get("abbreviation")) or "").strip().upper()
                    away_abbr = str((((away_team or {}).get("team") or {}).get("abbreviation")) or "").strip().upper()
                    if not espn_to_tri(home_abbr, league_code=league_code) or not espn_to_tri(away_abbr, league_code=league_code):
                        continue
                    summary = espn_summary(processed_root=processed_root, event_id=event_id, league_code=league_code, force=False)
                    day_rows.extend(
                        _event_rows_from_summary(
                            summary=summary,
                            event_id=event_id,
                            date_str=current_date,
                            league_code=league_code,
                        )
                    )
                except Exception:
                    continue
        if day_rows:
            day_df = pd.DataFrame(day_rows)
            day_df.to_csv(processed_root / f"boxscores_{current_date}.csv", index=False)
            frames.append(day_df)
        current += pd.Timedelta(days=1)

    existing_history = _read_existing_history(processed_root)
    if __import__("os").environ.get("WNBA_ISOLATE_AFTER_HISTORY_LOAD", "").strip().lower() in {"1", "true", "yes"}: return {"date": str(date_str), "rows": int(len(existing_history)) if existing_history is not None else 0, "history_rows": int(len(existing_history)) if existing_history is not None else 0, "wrote": str(processed_root / "boxscores_history.parquet") if (processed_root / "boxscores_history.parquet").exists() else (str(processed_root / "boxscores_history.csv") if (processed_root / "boxscores_history.csv").exists() else None), "error": None}
    current_history = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if existing_history is not None and not existing_history.empty and current_history is not None and not current_history.empty:
        combined = pd.concat([existing_history, current_history], ignore_index=True)
    elif existing_history is not None and not existing_history.empty:
        combined = existing_history.copy()
    else:
        combined = current_history.copy()

    if combined is None or combined.empty:
        return {"date": str(date_str), "rows": 0, "history_rows": 0, "wrote": None, "error": "no_rows"}

    if "date" in combined.columns:
        combined["date"] = pd.to_datetime(combined["date"], errors="coerce")
    key_columns = _history_key_columns(list(combined.columns))
    if key_columns:
        combined = combined.sort_values(["date"], kind="stable")
        combined = combined.drop_duplicates(subset=key_columns, keep="last")
    combined = combined.sort_values([column for column in ["date", "game_id", "PLAYER_ID"] if column in combined.columns], kind="stable")
    wrote = _write_history(processed_root, combined)
    return {
        "date": str(date_str),
        "rows": int(len(current_history)) if current_history is not None else 0,
        "history_rows": int(len(combined)),
        "wrote": wrote,
        "error": None if wrote else "write_failed",
        "days_checked": int(days_checked),
        "days_fetch_failed": int(days_fetch_failed),
    }