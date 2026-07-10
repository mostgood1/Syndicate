from __future__ import annotations

from pathlib import Path
from datetime import date as _date

from syndicate.features.shared.memory_observability import log_dataframe_memory


NUM_COL_MAP = {
    "PTS": ["PTS", "pts"],
    "REB": ["REB", "reb", "TREB", "treb"],
    "AST": ["AST", "ast"],
    "FG3M": ["FG3M", "fg3m", "FG3M_A"],
    "FG3A": ["FG3A", "fg3a", "threePointersAttempted"],
    "MIN": ["MIN", "min"],
    "STL": ["STL", "stl"],
    "BLK": ["BLK", "blk"],
    "TOV": ["TOV", "tov"],
    "FGM": ["FGM", "fgm"],
    "FGA": ["FGA", "fga"],
    "FG_PCT": ["FG_PCT", "fg_pct"],
    "FTM": ["FTM", "ftm"],
    "FTA": ["FTA", "fta"],
    "FT_PCT": ["FT_PCT", "ft_pct"],
    "OREB": ["OREB", "oreb"],
    "DREB": ["DREB", "dreb"],
    "PF": ["PF", "pf"],
    "PLUS_MINUS": ["PLUS_MINUS", "plus_minus"],
}

DATE_COLS = ["GAME_DATE", "GAME_DATE_EST", "dateGame", "GAME_DATE_PT"]
PLAYER_ID_COLS = ["PLAYER_ID", "player_id", "idPlayer"]
PLAYER_NAME_COLS = ["PLAYER_NAME", "player_name", "namePlayer"]
TEAM_COLS = ["TEAM_ABBREVIATION", "team", "slugTeam"]
MATCHUP_COL = "MATCHUP"


def _boxscore_paths(processed_root: Path) -> list[Path]:
    paths: list[Path] = []
    for candidate in (
        processed_root / "boxscores_history.parquet",
        processed_root / "boxscores_history.csv",
    ):
        if candidate.exists() and candidate.stat().st_size > 0:
            paths.append(candidate)
    for pattern in ("boxscores_*.parquet", "boxscores_*.csv"):
        for candidate in sorted(processed_root.glob(pattern)):
            if candidate.exists() and candidate.stat().st_size > 0:
                paths.append(candidate)
    return paths


def _read_boxscore_frame(path: Path):
    import pandas as pd

    suffix = path.suffix.lower()
    if suffix == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path)


def _load_boxscores_as_player_logs(processed_root: Path):
    import pandas as pd

    frames = []
    for path in _boxscore_paths(processed_root):
        try:
            frame = _read_boxscore_frame(path)
        except Exception:
            continue
        if frame is None or frame.empty:
            continue
        frames.append(frame)

    if not frames:
        return pd.DataFrame()

    df = pd.concat(frames, ignore_index=True)
    log_dataframe_memory("basketball_props_features.boxscores_as_player_logs", df)
    if df.empty:
        return df

    if "date" in df.columns and "GAME_DATE" not in df.columns:
        df["GAME_DATE"] = pd.to_datetime(df["date"], errors="coerce")
    elif "GAME_DATE" in df.columns:
        df["GAME_DATE"] = pd.to_datetime(df["GAME_DATE"], errors="coerce")
    else:
        df["GAME_DATE"] = pd.NaT

    if "TEAM_ABBREVIATION" in df.columns:
        df["TEAM_ABBREVIATION"] = df["TEAM_ABBREVIATION"].astype(str).str.strip().str.upper()
    if "PLAYER_NAME" in df.columns:
        df["PLAYER_NAME"] = df["PLAYER_NAME"].astype(str).str.strip()

    keep = [
        "GAME_DATE",
        "TEAM_ABBREVIATION",
        "PLAYER_ID",
        "PLAYER_NAME",
        "MATCHUP",
        "MIN",
        "PTS",
        "REB",
        "AST",
        "STL",
        "BLK",
        "TOV",
        "FG3M",
        "FG3A",
        "FGA",
        "FGM",
        "FTA",
        "FTM",
        "PF",
        "PLUS_MINUS",
        "OREB",
        "DREB",
    ]
    out = df[[column for column in keep if column in df.columns]].copy()
    if "MATCHUP" not in out.columns:
        out["MATCHUP"] = None
    return out


def _find_col(df, candidates) -> str | None:
    cols = {column.lower(): column for column in df.columns}
    for candidate in candidates:
        if candidate.lower() in cols:
            return cols[candidate.lower()]
    return None


def _to_minutes(value):
    import numpy as np
    import pandas as pd

    if pd.isna(value):
        return np.nan
    text = str(value).strip()
    if not text:
        return np.nan
    try:
        if text.upper().startswith("PT") and "M" in text.upper():
            import re

            match = re.match(r"^PT\s*(\d+(?:\.\d+)?)\s*M\s*(\d+(?:\.\d+)?)?\s*S?\s*$", text.upper())
            if match:
                minutes = float(match.group(1))
                seconds = float(match.group(2) or 0.0)
                out = minutes + seconds / 60.0
                return float(out) if np.isfinite(out) else np.nan
    except Exception:
        pass
    if ":" in text:
        try:
            minutes_text, seconds_text = text.split(":", 1)
            minutes = pd.to_numeric(minutes_text, errors="coerce")
            seconds = pd.to_numeric(seconds_text, errors="coerce")
            if pd.isna(minutes) or pd.isna(seconds):
                return np.nan
            out = float(minutes) + float(seconds) / 60.0
            return float(out) if np.isfinite(out) else np.nan
        except Exception:
            return np.nan
    out = pd.to_numeric(text, errors="coerce")
    if pd.isna(out):
        return np.nan
    out_f = float(out)
    return float(out_f) if np.isfinite(out_f) else np.nan


def _parse_matchup_context(value: object) -> tuple[float, str | None]:
    text = str(value or "").strip().upper()
    if not text:
        return 0.0, None
    if " VS. " in text:
        _, right = text.split(" VS. ", 1)
        return 1.0, right.strip() or None
    if " VS " in text:
        _, right = text.split(" VS ", 1)
        return 1.0, right.strip() or None
    if " @ " in text:
        _, right = text.split(" @ ", 1)
        return 0.0, right.strip() or None
    return 0.0, None


def load_player_logs_local(*, processed_root: Path):
    import pandas as pd

    parquet_path = processed_root / "player_logs.parquet"
    csv_path = processed_root / "player_logs.csv"
    if parquet_path.exists():
        try:
            return pd.read_parquet(parquet_path)
        except Exception as exc:
            if csv_path.exists():
                return pd.read_csv(csv_path)
            raise RuntimeError(
                f"Failed to read {parquet_path} and CSV fallback missing. Install pyarrow/fastparquet or provide player_logs.csv. Original error: {exc}"
            )
    if csv_path.exists():
        return pd.read_csv(csv_path)
    fallback = _load_boxscores_as_player_logs(processed_root)
    if isinstance(fallback, pd.DataFrame) and not fallback.empty:
        return fallback
    raise FileNotFoundError("player_logs not found; run fetch-player-logs")


def build_features_for_date_local(*, processed_root: Path, date: str, windows: list[int] | None = None, players: list[int] | None = None):
    import numpy as np
    import pandas as pd

    windows = windows or [3, 5, 10]
    logs = load_player_logs_local(processed_root=processed_root).copy()
    dcol = _find_col(logs, DATE_COLS)
    pid = _find_col(logs, PLAYER_ID_COLS)
    pname = _find_col(logs, PLAYER_NAME_COLS)
    tcol = _find_col(logs, TEAM_COLS)
    matchup_col = _find_col(logs, [MATCHUP_COL])

    pts = _find_col(logs, NUM_COL_MAP["PTS"])
    reb = _find_col(logs, NUM_COL_MAP["REB"])
    ast = _find_col(logs, NUM_COL_MAP["AST"])
    fg3m = _find_col(logs, NUM_COL_MAP["FG3M"])
    fg3a = _find_col(logs, NUM_COL_MAP["FG3A"])
    minc = _find_col(logs, NUM_COL_MAP["MIN"])
    stl = _find_col(logs, NUM_COL_MAP["STL"])
    blk = _find_col(logs, NUM_COL_MAP["BLK"])
    tov = _find_col(logs, NUM_COL_MAP["TOV"])
    fgm = _find_col(logs, NUM_COL_MAP["FGM"])
    fga = _find_col(logs, NUM_COL_MAP["FGA"])
    fg_pct = _find_col(logs, NUM_COL_MAP["FG_PCT"])
    ftm = _find_col(logs, NUM_COL_MAP["FTM"])
    fta = _find_col(logs, NUM_COL_MAP["FTA"])
    ft_pct = _find_col(logs, NUM_COL_MAP["FT_PCT"])
    oreb = _find_col(logs, NUM_COL_MAP["OREB"])
    dreb = _find_col(logs, NUM_COL_MAP["DREB"])
    pf = _find_col(logs, NUM_COL_MAP["PF"])
    plus_minus = _find_col(logs, NUM_COL_MAP["PLUS_MINUS"])

    for column in [pid, pname, tcol, dcol, pts, reb, ast, fg3m]:
        if column is None:
            raise ValueError("Missing required columns in player_logs")

    logs[dcol] = pd.to_datetime(logs[dcol])
    target_date = pd.to_datetime(date)
    hist = logs[logs[dcol] < target_date].copy()
    if players is not None:
        hist = hist[hist[pid].isin(players)].copy()
    if minc is not None and minc in hist.columns:
        hist[minc] = pd.to_numeric(hist[minc], errors="coerce")
        hist = hist[hist[minc].fillna(0.0) > 0.0].copy()

    def _season_year(value) -> int | None:
        try:
            ts = pd.to_datetime(value, errors="coerce")
            if pd.isna(ts):
                return None
            return int(ts.year) if int(ts.month) >= 5 else int(ts.year) - 1
        except Exception:
            return None

    current_season_year = _season_year(target_date)
    if current_season_year is not None and pid is not None and pid in logs.columns and minc is not None and minc in logs.columns:
        logs["__season_year"] = logs[dcol].map(_season_year)
        played = logs[pd.to_numeric(logs[minc], errors="coerce").fillna(0.0) > 0.0].copy()
        if not played.empty:
            player_frames: list[pd.DataFrame] = []
            player_ids = hist[pid].dropna().unique().tolist() if not hist.empty else []
            if not player_ids:
                player_ids = played[pid].dropna().unique().tolist()
            for player_id in player_ids:
                player_current = played[(played[pid] == player_id) & (played["__season_year"] == current_season_year)].copy()
                if not player_current.empty:
                    player_frames.append(player_current)
                    continue
                player_prior = played[(played[pid] == player_id) & (played["__season_year"].notna()) & (played["__season_year"] < current_season_year)].copy()
                if player_prior.empty:
                    continue
                fallback_season_year = int(player_prior["__season_year"].max())
                player_prior = player_prior[player_prior["__season_year"] == fallback_season_year].copy()
                if not player_prior.empty:
                    player_frames.append(player_prior)
            if player_frames:
                hist = pd.concat(player_frames, ignore_index=True)
                log_dataframe_memory("basketball_props_features.player_history_concat", hist)

    stat_cols = [pts, reb, ast, fg3m, fg3a, stl, blk, tov, fgm, fga, fg_pct, ftm, fta, ft_pct, oreb, dreb, pf, plus_minus]
    for column in stat_cols:
        if column is not None and column in hist.columns:
            hist[column] = pd.to_numeric(hist[column], errors="coerce")

    if minc is not None and minc in hist.columns:
        hist[minc] = hist[minc].apply(_to_minutes)
    else:
        hist[minc] = np.nan
    hist.sort_values([pid, dcol], inplace=True)

    stat_map = {
        "pts": pts, "reb": reb, "ast": ast, "threes": fg3m,
        "fg3a": fg3a,
        "stl": stl, "blk": blk, "tov": tov,
        "fgm": fgm, "fga": fga, "fg_pct": fg_pct,
        "ftm": ftm, "fta": fta, "ft_pct": ft_pct,
        "oreb": oreb, "dreb": dreb,
        "pf": pf, "plus_minus": plus_minus,
    }

    rows = []
    grp = hist.groupby(pid, sort=False)
    for player_id, group in grp:
        group = group.copy()
        group["minutes"] = group[minc]
        denom = group["minutes"].replace(0, np.nan)
        group["season_game_number"] = np.arange(1, len(group) + 1, dtype=float)
        group["days_rest"] = group[dcol].diff().dt.days.astype(float)

        recent_7 = []
        recent_14 = []
        dates = pd.to_datetime(group[dcol])
        for index, game_date in enumerate(dates):
            prior = dates.iloc[:index]
            if len(prior) == 0:
                recent_7.append(0.0)
                recent_14.append(0.0)
                continue
            delta_days = (game_date - prior).dt.days
            recent_7.append(float(((delta_days > 0) & (delta_days <= 7)).sum()))
            recent_14.append(float(((delta_days > 0) & (delta_days <= 14)).sum()))
        group["games_last7"] = recent_7
        group["games_last14"] = recent_14

        if matchup_col is not None and matchup_col in group.columns:
            matchup_context = group[matchup_col].apply(_parse_matchup_context)
            group["is_home"] = matchup_context.map(lambda item: item[0]).astype(float)
            group["opp_team"] = matchup_context.map(lambda item: item[1])
        else:
            group["is_home"] = 0.0
            group["opp_team"] = None

        group["_pts_per_min"] = group[pts] / denom
        group["_reb_per_min"] = group[reb] / denom
        group["_ast_per_min"] = group[ast] / denom
        group["_fg3m_per_min"] = group[fg3m] / denom
        group["_fg3a_per_min"] = group[fg3a] / denom if fg3a is not None and fg3a in group.columns else np.nan
        group["_fga_per_min"] = group[fga] / denom if fga is not None and fga in group.columns else np.nan
        group["_fta_per_min"] = group[fta] / denom if fta is not None and fta in group.columns else np.nan
        group["_tov_per_min"] = group[tov] / denom if tov is not None and tov in group.columns else np.nan
        if (fga is not None and fga in group.columns) and (fta is not None and fta in group.columns) and (tov is not None and tov in group.columns):
            group["_usage_per_min"] = (group[fga] + 0.44 * group[fta] + group[tov]) / denom
        else:
            group["_usage_per_min"] = np.nan

        derived_map = {
            "pts_per_min": "_pts_per_min",
            "reb_per_min": "_reb_per_min",
            "ast_per_min": "_ast_per_min",
            "fg3m_per_min": "_fg3m_per_min",
            "fg3a_per_min": "_fg3a_per_min",
            "fga_per_min": "_fga_per_min",
            "fta_per_min": "_fta_per_min",
            "tov_per_min": "_tov_per_min",
            "usage_per_min": "_usage_per_min",
        }
        rec = {
            "player_id": player_id,
            "player_name": group.iloc[-1][_find_col(hist, PLAYER_NAME_COLS)] if _find_col(hist, PLAYER_NAME_COLS) else None,
            "team": group.iloc[-1][_find_col(hist, TEAM_COLS)] if _find_col(hist, TEAM_COLS) else None,
            "asof_date": target_date.date(),
            "is_home": 0.0,
            "days_rest": float((target_date.normalize() - group[dcol].iloc[-1].normalize()).days) if len(group) > 0 else np.nan,
            "games_last7": float(((target_date - group[dcol]) <= pd.Timedelta(days=7)).sum()) if len(group) > 0 else 0.0,
            "games_last14": float(((target_date - group[dcol]) <= pd.Timedelta(days=14)).sum()) if len(group) > 0 else 0.0,
            "season_game_number": float(len(group) + 1),
        }

        for stat_name, stat_col in stat_map.items():
            rec[f"lag1_{stat_name}"] = group[stat_col].iloc[-1] if stat_col is not None and stat_col in group.columns and len(group) > 0 else np.nan
        rec["lag1_min"] = group["minutes"].iloc[-1] if len(group) > 0 else np.nan
        for feat_name, feat_col in derived_map.items():
            rec[f"lag1_{feat_name}"] = group[feat_col].iloc[-1] if feat_col in group.columns and len(group) > 0 else np.nan

        rec["b2b"] = float((group[dcol].iloc[-1] - group[dcol].iloc[-2]).days == 1) if len(group) >= 2 else 0.0
        for window in windows:
            rec[f"roll{window}_min"] = group["minutes"].rolling(window, min_periods=1).mean().iloc[-1]
            rec[f"roll{window}_min_std"] = group["minutes"].rolling(window, min_periods=2).std().iloc[-1]
            for stat_name, stat_col in stat_map.items():
                rec[f"roll{window}_{stat_name}"] = group[stat_col].rolling(window, min_periods=1).mean().iloc[-1] if stat_col is not None and stat_col in group.columns else np.nan
            for feat_name, feat_col in derived_map.items():
                if feat_col in group.columns:
                    rec[f"roll{window}_{feat_name}"] = group[feat_col].rolling(window, min_periods=1).mean().iloc[-1]
                    rec[f"roll{window}_{feat_name}_std"] = group[feat_col].rolling(window, min_periods=2).std().iloc[-1]
                else:
                    rec[f"roll{window}_{feat_name}"] = np.nan
                    rec[f"roll{window}_{feat_name}_std"] = np.nan
        rows.append(rec)
    out = pd.DataFrame(rows)
    log_dataframe_memory("basketball_props_features.output", out)
    return out