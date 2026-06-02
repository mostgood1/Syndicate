from __future__ import annotations

"""Lineup tracker: expected lines (EV), PP, PK with confidence scores (baseline).

Leverages existing TOI-based inference as a starting point; allows manual overrides
and confidence scoring per unit.
"""

from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from .rosters import build_roster_snapshot, infer_lines, project_toi
from .lineups_sources import fetch_dailyfaceoff_team_lineups
from .collect import collect_player_game_stats
from ..utils.io import RAW_DIR
from .shifts_api import avg_toi_from_processed_shift_files


def _apply_shift_history_toi(df: pd.DataFrame, date: str, processed_dir: Optional[Path]) -> pd.DataFrame:
    if df is None or df.empty or processed_dir is None or "player_id" not in df.columns or "team" not in df.columns:
        return df
    try:
        hist = avg_toi_from_processed_shift_files(Path(processed_dir), end_date=date, days=45)
    except Exception:
        return df
    if hist is None or hist.empty:
        return df
    try:
        hist = hist.copy()
        hist["team"] = hist["team"].astype(str).str.upper()
        hist = hist[["team", "player_id", "avg_toi_minutes"]].rename(columns={"avg_toi_minutes": "hist_toi"})
        out = df.merge(hist, on=["team", "player_id"], how="left")
        out["proj_toi"] = pd.to_numeric(out["hist_toi"], errors="coerce").fillna(pd.to_numeric(out.get("proj_toi"), errors="coerce"))
        if out["proj_toi"].isna().any() and {"position"}.issubset(set(out.columns)):
            pos_medians = out.groupby(["team", "position"])["proj_toi"].transform("median")
            out["proj_toi"] = out["proj_toi"].fillna(pos_medians)
        return out.drop(columns=["hist_toi"], errors="ignore")
    except Exception:
        return df


def _ensure_player_game_stats(date: str, days: int = 45) -> Path:
    stats_path = RAW_DIR / "player_game_stats.csv"
    try:
        if stats_path.exists() and getattr(stats_path.stat(), "st_size", 0) > 0:
            return stats_path
    except Exception:
        pass
    try:
        end_dt = datetime.strptime(str(date), "%Y-%m-%d")
        start_dt = end_dt - timedelta(days=int(days))
        collect_player_game_stats(start_dt.strftime("%Y-%m-%d"), date, source="web")
    except Exception:
        pass
    return stats_path


def _recent_toi_history(date: str, days: int = 45) -> pd.DataFrame:
    stats_path = _ensure_player_game_stats(date, days=days)
    if not stats_path.exists() or getattr(stats_path.stat(), "st_size", 0) == 0:
        return pd.DataFrame(columns=["player_id", "toi_avg", "games_played"])
    try:
        stats = pd.read_csv(stats_path)
    except Exception:
        return pd.DataFrame(columns=["player_id", "toi_avg", "games_played"])
    if stats is None or stats.empty or "date" not in stats.columns:
        return pd.DataFrame(columns=["player_id", "toi_avg", "games_played"])
    try:
        end_dt = datetime.strptime(str(date), "%Y-%m-%d")
        start_dt = end_dt - timedelta(days=int(days))
        stats = stats.copy()
        stats["date_key"] = pd.to_datetime(stats["date"], errors="coerce").dt.strftime("%Y-%m-%d")
        stats = stats[stats["date_key"].notna()]
        stats = stats[(stats["date_key"] >= start_dt.strftime("%Y-%m-%d")) & (stats["date_key"] < date)]
        if stats.empty:
            return pd.DataFrame(columns=["player_id", "toi_avg", "games_played"])

        def _toi_to_minutes(value: object) -> float:
            try:
                if value is None:
                    return 0.0
                text = str(value)
                if ":" not in text:
                    return float(text)
                minutes, seconds = text.split(":", 1)
                return float(minutes) + (float(seconds) / 60.0)
            except Exception:
                return 0.0

        stats["toi_min"] = stats["timeOnIce"].map(_toi_to_minutes) if "timeOnIce" in stats.columns else 0.0
        for column in ("player_id", "player", "primary_position"):
            if column not in stats.columns:
                stats[column] = pd.NA
        stats["primary_position"] = stats["primary_position"].astype(str).str.upper().replace({"NAN": ""})
        stats["position"] = stats["primary_position"].map(lambda x: "G" if str(x).startswith("G") else ("D" if str(x).startswith("D") else "F"))
        grouped = stats.groupby(["player_id", "player", "position"], as_index=False).agg(
            games_played=("gamePk", "nunique"),
            toi_total=("toi_min", "sum"),
        )
        grouped["toi_avg"] = grouped["toi_total"] / grouped["games_played"].clip(lower=1)
        return grouped[["player_id", "player", "position", "games_played", "toi_avg"]]
    except Exception:
        return pd.DataFrame(columns=["player_id", "toi_avg", "games_played"])
    try:
        hist = avg_toi_from_processed_shift_files(Path(processed_dir), end_date=date, days=45)
    except Exception:
        return df
    if hist is None or hist.empty:
        return df
    try:
        hist = hist.copy()
        hist["team"] = hist["team"].astype(str).str.upper()
        hist = hist[["team", "player_id", "avg_toi_minutes"]].rename(columns={"avg_toi_minutes": "hist_toi"})
        out = df.merge(hist, on=["team", "player_id"], how="left")
        out["proj_toi"] = pd.to_numeric(out["hist_toi"], errors="coerce").fillna(pd.to_numeric(out.get("proj_toi"), errors="coerce"))
        if out["proj_toi"].isna().any() and {"position"}.issubset(set(out.columns)):
            pos_medians = out.groupby(["team", "position"])["proj_toi"].transform("median")
            out["proj_toi"] = out["proj_toi"].fillna(pos_medians)
        return out.drop(columns=["hist_toi"], errors="ignore")
    except Exception:
        return df


def build_lineup_snapshot(
    team_abbr: str,
    usage_df: Optional[pd.DataFrame] = None,
    date: Optional[str] = None,
    processed_dir: Optional[Path] = None,
    overrides: Optional[Dict] = None,
) -> pd.DataFrame:
    """Return a lineup snapshot with columns: player_id, full_name, position, line_slot, pp_unit, pk_unit, proj_toi, confidence.

    - If usage_df is provided, use infer_lines/project_toi; else build a roster snapshot and project baseline TOI.
    - Overrides may set explicit slots or units for specific players.
    """
    if usage_df is None or usage_df.empty:
        roster = build_roster_snapshot(team_abbr)
        # Build minimal usage proxy and required columns for inference
        roster = roster.rename(columns={"full_name":"full_name","player_id":"player_id","position":"position"}).copy()
        roster["team"] = str(team_abbr).upper()
        history = _recent_toi_history(str(date or "")) if False else _recent_toi_history(str(date or ""))
        if history is not None and not history.empty:
            roster = roster.merge(history[["player_id", "toi_avg"]], on="player_id", how="left")
        if "toi_avg" not in roster.columns:
            roster["toi_avg"] = pd.NA
        median_by_pos = {}
        try:
            for pos in ("F", "D", "G"):
                pos_vals = pd.to_numeric(roster.loc[roster["position"].astype(str).str.upper().eq(pos), "toi_avg"], errors="coerce")
                pos_median = float(pos_vals.dropna().median()) if not pos_vals.dropna().empty else None
                median_by_pos[pos] = pos_median
        except Exception:
            median_by_pos = {"F": 13.5, "D": 18.5, "G": 60.0}
        roster["toi_avg"] = pd.to_numeric(roster["toi_avg"], errors="coerce")
        roster.loc[roster["position"].astype(str).str.upper().eq("G") & roster["toi_avg"].isna(), "toi_avg"] = 60.0
        roster.loc[roster["position"].astype(str).str.upper().eq("D") & roster["toi_avg"].isna(), "toi_avg"] = median_by_pos.get("D") or 18.5
        roster.loc[roster["position"].astype(str).str.upper().eq("F") & roster["toi_avg"].isna(), "toi_avg"] = median_by_pos.get("F") or 13.5
        roster["toi_pp_avg"] = 0.0
        roster["toi_sh_avg"] = 0.0
        df = project_toi(infer_lines(roster))
    else:
        df = usage_df.copy()
        for col in ("toi_avg","toi_pp_avg","toi_sh_avg"):
            if col not in df.columns:
                df[col] = 0.0
        df = project_toi(infer_lines(df))
    df = _apply_shift_history_toi(df, date=str(date or pd.Timestamp.utcnow().date()), processed_dir=processed_dir)
    df["confidence"] = 0.5  # baseline
    overrides = overrides or {}
    # Apply overrides
    if overrides:
        df = df.copy()
        for pid, vals in overrides.items():
            mask = df["player_id"].eq(int(pid))
            for k, v in vals.items():
                if k in df.columns:
                    df.loc[mask, k] = v
    return df[["player_id","full_name","position","line_slot","pp_unit","pk_unit","proj_toi","confidence"]]


def build_lineup_snapshot_from_source(
    team_abbr: str,
    date: str,
    processed_dir: Optional[Path] = None,
    overrides: Optional[Dict] = None,
) -> pd.DataFrame:
    """Build lineup snapshot using an external source (Daily Faceoff) with roster mapping.

    - Fetch lineup items for the team/date
    - Map player names to roster snapshot to resolve `player_id` and `position`
    - Provide reasonable defaults for missing fields; apply overrides if provided
    """
    items = fetch_dailyfaceoff_team_lineups(team_abbr, date)
    roster = build_roster_snapshot(team_abbr)
    name_map = {}
    pos_map = {}
    if not roster.empty:
        tmp = roster.copy()
        tmp["_name_key"] = tmp["full_name"].astype(str).str.strip().str.lower()
        for _, r in tmp.iterrows():
            name_map[str(r["_name_key"])]= int(r["player_id"]) if pd.notnull(r["player_id"]) else None
            pos_map[str(r["_name_key"])]= str(r.get("position",""))
    rows = []
    for it in items:
        nm = str(it.get("player_name",""))
        key = nm.strip().lower()
        pid = name_map.get(key)
        pos = pos_map.get(key) or str(it.get("position",""))
        rows.append({
            "team": str(team_abbr).upper(),
            "player_id": pid,
            "full_name": nm,
            "position": pos,
            "line_slot": it.get("line_slot"),
            "pp_unit": it.get("pp_unit"),
            "pk_unit": it.get("pk_unit"),
            "proj_toi": None,
            "confidence": float(it.get("confidence", 0.5)),
        })
    # Ensure expected columns exist even when rows are empty due to source schema changes
    expected_cols = ["team","player_id","full_name","position","line_slot","pp_unit","pk_unit","proj_toi","confidence"]
    df = pd.DataFrame(rows, columns=expected_cols)
    # Fill projected TOI from actual shift-history averages when available.
    try:
        hist = pd.DataFrame(columns=["team", "player_id", "avg_toi_minutes"])
        if processed_dir is not None:
            hist = avg_toi_from_processed_shift_files(Path(processed_dir), end_date=date, days=45)
        if hist is not None and not hist.empty:
            hist = hist.copy()
            hist["team"] = hist["team"].astype(str).str.upper()
            hist = hist[["team", "player_id", "avg_toi_minutes"]].rename(columns={"avg_toi_minutes": "hist_toi"})
            df = df.merge(hist, on=["team", "player_id"], how="left")
            df["proj_toi"] = pd.to_numeric(df["hist_toi"], errors="coerce")
            df = df.drop(columns=["hist_toi"], errors="ignore")
            if not df.empty and df["proj_toi"].isna().any():
                pos_medians = df.groupby(["team", "position"])["proj_toi"].transform("median")
                df["proj_toi"] = df["proj_toi"].fillna(pos_medians)
        if df["proj_toi"].isna().any() and not roster.empty:
            # Use roster-based inference only for any remaining gaps.
            inf = project_toi(infer_lines(roster.rename(columns={"full_name":"full_name","player_id":"player_id","position":"position"})))
            inf = inf[["player_id","proj_toi"]].dropna()
            df = df.merge(inf, on="player_id", how="left", suffixes=("", "_inf"))
            df["proj_toi"] = df["proj_toi"].fillna(df["proj_toi_inf"])
            df = df.drop(columns=["proj_toi_inf"], errors="ignore")
    except Exception:
        pass
    overrides = overrides or {}
    if overrides:
        for pid, vals in overrides.items():
            mask = df["player_id"].eq(int(pid))
            for k, v in vals.items():
                if k in df.columns:
                    df.loc[mask, k] = v
    return df[["team","player_id","full_name","position","line_slot","pp_unit","pk_unit","proj_toi","confidence"]]


def build_lineup_snapshot_bundle(
    date: str,
    processed_dir: Optional[Path] = None,
    team_abbrs: Optional[List[str]] = None,
    prefer_source: str = "dailyfaceoff",
    debug: bool = False,
) -> pd.DataFrame:
    frames: List[pd.DataFrame] = []
    first_error: Optional[Exception] = None
    for ab in (team_abbrs or []):
        try:
            snap = None
            if prefer_source and str(prefer_source).lower() == "dailyfaceoff":
                try:
                    snap_src = build_lineup_snapshot_from_source(ab, date, processed_dir=processed_dir)
                    if snap_src is not None and not snap_src.empty:
                        snap = snap_src
                except Exception:
                    snap = None
            if snap is None or snap.empty:
                snap = build_lineup_snapshot(ab, date=date, processed_dir=processed_dir)
            if snap is None or snap.empty:
                continue
            snap = snap.copy()
            snap["team"] = ab
            frames.append(snap)
        except Exception as exc:
            if debug and first_error is None:
                first_error = exc
            continue
    if debug and first_error is not None and not frames:
        raise first_error
    if not frames:
        return pd.DataFrame(columns=["player_id","full_name","position","line_slot","pp_unit","pk_unit","proj_toi","confidence","team"])
    return pd.concat(frames, ignore_index=True)


__all__ = ["build_lineup_snapshot", "build_lineup_snapshot_from_source", "build_lineup_snapshot_bundle"]
