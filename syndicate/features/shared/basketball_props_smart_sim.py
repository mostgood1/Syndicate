from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime
import importlib
import json
import math
import os
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any


_SMARTSIM_WORKER_STATE: dict[str, object] | None = None
_QUARTERS_CALIBRATION_CACHE_LOCAL: dict[str, dict[str, Any] | None] = {}
_DEFAULT_BLEND_WEIGHTS_CACHE_LOCAL: dict[str, tuple[float, float]] = {}
_TOTALS_CALIBRATION_INDEX_LOCAL: dict[str, list[tuple[object, Path]]] = {}
_TOTALS_CALIBRATION_CACHE_LOCAL: dict[tuple[str, str], dict[str, Any] | None] = {}
_TEAM_ADVANCED_STATS_CACHE_LOCAL: dict[tuple[str, int, str], object] = {}
_PREGAME_EXPECTED_MINUTES_CACHE_LOCAL: dict[tuple[str, str], object] = {}
_MARKET_PLAYER_NAMES_CACHE_LOCAL: dict[tuple[str, str], dict[tuple[str, str], set[str]]] = {}


def _json_default_local(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, set):
        return sorted(value)
    value_type = type(value)
    module_name = str(getattr(value_type, "__module__", ""))
    if module_name.startswith("numpy"):
        item_method = getattr(value, "item", None)
        if callable(item_method):
            try:
                return item_method()
            except Exception:
                pass
        tolist_method = getattr(value, "tolist", None)
        if callable(tolist_method):
            try:
                return tolist_method()
            except Exception:
                pass
    if hasattr(value, "__dict__"):
        try:
            return dict(value.__dict__)
        except Exception:
            pass
    return str(value)


def _json_dumps_safe_local(data: Any) -> str:
    return json.dumps(data, indent=2, default=_json_default_local)


def _smart_sim_file_has_players_local(path: Path) -> bool:
    try:
        if not path.exists() or (not path.is_file()) or path.stat().st_size <= 0:
            return False
        payload = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
        if not isinstance(payload, dict):
            return False
        players = payload.get("players") if isinstance(payload.get("players"), dict) else {}
        home_rows = players.get("home") if isinstance(players.get("home"), list) else []
        away_rows = players.get("away") if isinstance(players.get("away"), list) else []
        return (len(home_rows) + len(away_rows)) > 0
    except Exception:
        return False

_NBA_TEAM_ALIASES_LOCAL = {
    "la lakers": "Los Angeles Lakers",
    "l.a. lakers": "Los Angeles Lakers",
    "lakers": "Los Angeles Lakers",
    "warriors": "Golden State Warriors",
    "clippers": "Los Angeles Clippers",
    "la clippers": "Los Angeles Clippers",
    "l.a. clippers": "Los Angeles Clippers",
    "boston": "Boston Celtics",
    "celtics": "Boston Celtics",
    "atl": "Atlanta Hawks",
    "bos": "Boston Celtics",
    "bkn": "Brooklyn Nets",
    "cha": "Charlotte Hornets",
    "chi": "Chicago Bulls",
    "cle": "Cleveland Cavaliers",
    "dal": "Dallas Mavericks",
    "den": "Denver Nuggets",
    "det": "Detroit Pistons",
    "gsw": "Golden State Warriors",
    "hou": "Houston Rockets",
    "ind": "Indiana Pacers",
    "lac": "Los Angeles Clippers",
    "lal": "Los Angeles Lakers",
    "mem": "Memphis Grizzlies",
    "mia": "Miami Heat",
    "mil": "Milwaukee Bucks",
    "min": "Minnesota Timberwolves",
    "nop": "New Orleans Pelicans",
    "no": "New Orleans Pelicans",
    "nyk": "New York Knicks",
    "okc": "Oklahoma City Thunder",
    "orl": "Orlando Magic",
    "phi": "Philadelphia 76ers",
    "phx": "Phoenix Suns",
    "por": "Portland Trail Blazers",
    "sac": "Sacramento Kings",
    "sas": "San Antonio Spurs",
    "sa": "San Antonio Spurs",
    "tor": "Toronto Raptors",
    "uta": "Utah Jazz",
    "utah": "Utah Jazz",
    "was": "Washington Wizards",
}
_WNBA_TEAM_ALIASES_LOCAL = {
    "atlanta": "Atlanta Dream",
    "dream": "Atlanta Dream",
    "sky": "Chicago Sky",
    "conn": "Connecticut Sun",
    "con": "Connecticut Sun",
    "connecticut": "Connecticut Sun",
    "sun": "Connecticut Sun",
    "dallas": "Dallas Wings",
    "wings": "Dallas Wings",
    "gs": "Golden State Valkyries",
    "gsv": "Golden State Valkyries",
    "golden state": "Golden State Valkyries",
    "valkyries": "Golden State Valkyries",
    "indiana": "Indiana Fever",
    "fever": "Indiana Fever",
    "las": "Los Angeles Sparks",
    "la": "Los Angeles Sparks",
    "los angeles": "Los Angeles Sparks",
    "sparks": "Los Angeles Sparks",
    "lv": "Las Vegas Aces",
    "lva": "Las Vegas Aces",
    "las vegas": "Las Vegas Aces",
    "aces": "Las Vegas Aces",
    "minnesota": "Minnesota Lynx",
    "lynx": "Minnesota Lynx",
    "ny": "New York Liberty",
    "nyl": "New York Liberty",
    "new york": "New York Liberty",
    "liberty": "New York Liberty",
    "pho": "Phoenix Mercury",
    "phoenix": "Phoenix Mercury",
    "mercury": "Phoenix Mercury",
    "sea": "Seattle Storm",
    "seattle": "Seattle Storm",
    "storm": "Seattle Storm",
    "fire": "Portland Fire",
    "tempo": "Toronto Tempo",
    "wsh": "Washington Mystics",
    "washington": "Washington Mystics",
    "mystics": "Washington Mystics",
}
_TEAM_ALIASES_LOCAL = {**_NBA_TEAM_ALIASES_LOCAL, **_WNBA_TEAM_ALIASES_LOCAL}
_NAME_TO_TRI_LOCAL = {
    "Atlanta Hawks": "ATL",
    "Boston Celtics": "BOS",
    "Brooklyn Nets": "BKN",
    "Charlotte Hornets": "CHA",
    "Chicago Bulls": "CHI",
    "Cleveland Cavaliers": "CLE",
    "Dallas Mavericks": "DAL",
    "Denver Nuggets": "DEN",
    "Detroit Pistons": "DET",
    "Golden State Warriors": "GSW",
    "Houston Rockets": "HOU",
    "Indiana Pacers": "IND",
    "Los Angeles Clippers": "LAC",
    "Los Angeles Lakers": "LAL",
    "Memphis Grizzlies": "MEM",
    "Miami Heat": "MIA",
    "Milwaukee Bucks": "MIL",
    "Minnesota Timberwolves": "MIN",
    "New Orleans Pelicans": "NOP",
    "New York Knicks": "NYK",
    "Oklahoma City Thunder": "OKC",
    "Orlando Magic": "ORL",
    "Philadelphia 76ers": "PHI",
    "Phoenix Suns": "PHX",
    "Portland Trail Blazers": "POR",
    "Sacramento Kings": "SAC",
    "San Antonio Spurs": "SAS",
    "Toronto Raptors": "TOR",
    "Utah Jazz": "UTA",
    "Washington Wizards": "WAS",
    "Atlanta Dream": "ATL",
    "Chicago Sky": "CHI",
    "Connecticut Sun": "CON",
    "Dallas Wings": "DAL",
    "Golden State Valkyries": "GSV",
    "Indiana Fever": "IND",
    "Las Vegas Aces": "LVA",
    "Los Angeles Sparks": "LAS",
    "Minnesota Lynx": "MIN",
    "New York Liberty": "NYL",
    "Phoenix Mercury": "PHX",
    "Portland Fire": "POR",
    "Seattle Storm": "SEA",
    "Toronto Tempo": "TOR",
    "Washington Mystics": "WSH",
}
_CANONICAL_BY_LOWER_LOCAL = {value.lower(): value for value in _NAME_TO_TRI_LOCAL}


@dataclass(frozen=True)
class LeagueConfigBridgeLocal:
    code: str
    name: str
    season_start_month: int
    regulation_team_minutes: float
    quarter_minutes: float
    baseline_pace: float
    baseline_off_rating: float
    baseline_def_rating: float
    spread_winprob_sigma: float
    min_event_possessions: float
    min_team_points: float


_NBA_LEAGUE_LOCAL = LeagueConfigBridgeLocal(
    code="nba",
    name="NBA",
    season_start_month=10,
    regulation_team_minutes=240.0,
    quarter_minutes=12.0,
    baseline_pace=100.0,
    baseline_off_rating=110.6,
    baseline_def_rating=110.6,
    spread_winprob_sigma=12.0,
    min_event_possessions=84.0,
    min_team_points=70.0,
)
_WNBA_LEAGUE_LOCAL = LeagueConfigBridgeLocal(
    code="wnba",
    name="WNBA",
    season_start_month=5,
    regulation_team_minutes=200.0,
    quarter_minutes=10.0,
    baseline_pace=79.5,
    baseline_off_rating=101.5,
    baseline_def_rating=101.5,
    spread_winprob_sigma=9.75,
    min_event_possessions=67.5,
    min_team_points=55.0,
)


def _normalize_team_local(name: object) -> str:
    raw = str(name or "").strip()
    key = raw.lower()
    if key in _TEAM_ALIASES_LOCAL:
        return _TEAM_ALIASES_LOCAL[key]
    if key in _CANONICAL_BY_LOWER_LOCAL:
        return _CANONICAL_BY_LOWER_LOCAL[key]
    return raw


def _league_for_code_local(league_code: str | None):
    return _WNBA_LEAGUE_LOCAL if str(league_code or "").strip().lower() == "wnba" else _NBA_LEAGUE_LOCAL


def _league_code_from_source_root_local(source_root: Path) -> str:
    return "wnba" if "wnba" in str(source_root).lower() else "nba"


def _tri_to_espn_local(tri: str, *, league_code: str) -> str:
    value = str(tri or "").strip().upper()
    if str(league_code or "nba").strip().lower() == "wnba":
        return {
            "GSV": "GS",
            "LVA": "LV",
            "LAS": "LA",
            "NYL": "NY",
        }.get(value, value)
    return {
        "GSW": "GS",
        "NOP": "NO",
        "NYK": "NY",
        "UTA": "UTAH",
        "WAS": "WSH",
        "SAS": "SA",
        "PHX": "PHO",
    }.get(value, value)


def _espn_to_tri_local(abbr: str, *, league_code: str) -> str:
    value = str(abbr or "").strip().upper()
    if str(league_code or "nba").strip().lower() == "wnba":
        return {
            "GS": "GSV",
            "LV": "LVA",
            "LA": "LAS",
            "NY": "NYL",
        }.get(value, value)
    return {
        "GS": "GSW",
        "NO": "NOP",
        "NY": "NYK",
        "UTAH": "UTA",
        "WSH": "WAS",
        "SA": "SAS",
        "PHO": "PHX",
    }.get(value, value)


def _espn_sport_path_local(*, league_code: str) -> str:
    return "sports/basketball/wnba" if str(league_code or "nba").strip().lower() == "wnba" else "sports/basketball/nba"


def _espn_cache_dir_local(*, processed_root: Path, league_code: str) -> Path:
    cache_dir = processed_root / "_espn_cache" / (str(league_code or "nba").strip().lower() or "nba")
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def _read_json_local(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _write_json_local(path: Path, data: dict[str, Any]) -> None:
    try:
        path.write_text(json.dumps(data), encoding="utf-8")
    except Exception:
        return


def _http_get_json_local(url: str, *, timeout: int = 18) -> dict[str, Any]:
    try:
        import requests

        response = requests.get(
            url,
            headers={"Accept": "application/json", "User-Agent": "syndicate/1.0"},
            timeout=int(timeout),
        )
        if not response.ok:
            return {}
        payload = response.json()
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _espn_scoreboard_local(*, processed_root: Path, date_str: str, league_code: str, force: bool = False) -> dict[str, Any]:
    ymd = str(date_str or "").replace("-", "")
    if not ymd:
        return {}
    cache_path = _espn_cache_dir_local(processed_root=processed_root, league_code=league_code) / f"scoreboard_{ymd}.json"
    if (not force) and cache_path.exists():
        cached = _read_json_local(cache_path)
        if cached:
            return cached
    url = f"https://site.web.api.espn.com/apis/site/v2/{_espn_sport_path_local(league_code=league_code)}/scoreboard?dates={ymd}"
    payload = _http_get_json_local(url, timeout=18)
    if payload:
        _write_json_local(cache_path, payload)
    return payload


def _espn_summary_local(*, processed_root: Path, event_id: str, league_code: str, force: bool = False) -> dict[str, Any]:
    event_key = str(event_id or "").strip()
    if not event_key:
        return {}
    cache_path = _espn_cache_dir_local(processed_root=processed_root, league_code=league_code) / f"summary_{event_key}.json"
    if (not force) and cache_path.exists():
        cached = _read_json_local(cache_path)
        if cached:
            return cached
    url = f"https://site.web.api.espn.com/apis/site/v2/{_espn_sport_path_local(league_code=league_code)}/summary?event={event_key}"
    payload = _http_get_json_local(url, timeout=18)
    if payload:
        _write_json_local(cache_path, payload)
    return payload


def _espn_event_id_for_matchup_local(*, processed_root: Path, date_str: str, home_tri: str, away_tri: str, league_code: str, force_scoreboard: bool = False) -> str | None:
    scoreboard = _espn_scoreboard_local(processed_root=processed_root, date_str=date_str, league_code=league_code, force=bool(force_scoreboard))
    events = scoreboard.get("events") if isinstance(scoreboard, dict) else None
    if not isinstance(events, list):
        return None
    home_code = _tri_to_espn_local(home_tri, league_code=league_code)
    away_code = _tri_to_espn_local(away_tri, league_code=league_code)
    for event in events:
        try:
            competitions = (event or {}).get("competitions") or []
            if not competitions:
                continue
            matchup = competitions[0] or {}
            competitors = matchup.get("competitors") or []
            if len(competitors) < 2:
                continue
            home_team = next((item for item in competitors if str((item or {}).get("homeAway") or "") == "home"), None)
            away_team = next((item for item in competitors if str((item or {}).get("homeAway") or "") == "away"), None)
            if not home_team or not away_team:
                continue
            home_abbr = str(((home_team.get("team") or {}).get("abbreviation")) or "").strip().upper()
            away_abbr = str(((away_team.get("team") or {}).get("abbreviation")) or "").strip().upper()
            if home_abbr == home_code and away_abbr == away_code:
                event_id = str((event or {}).get("id") or "").strip()
                return event_id or None
        except Exception:
            continue
    return None


def _team_last_game_dates_local(games_df):
    import pandas as pd

    df = games_df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.normalize()
    df = df.dropna(subset=["date"]).sort_values("date")
    last_dates: dict[str, datetime] = {}
    for _, row in df.iterrows():
        game_date = row["date"]
        last_dates[str(row.get("home_team") or "")] = game_date
        last_dates[str(row.get("visitor_team") or "")] = game_date
    return last_dates


def _compute_rest_for_matchups_local(matchups_df, history_games_df):
    import pandas as pd

    out = matchups_df.copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.normalize()
    last_dates = _team_last_game_dates_local(history_games_df)
    home_rest: list[int | None] = []
    away_rest: list[int | None] = []
    home_b2b: list[int | None] = []
    away_b2b: list[int | None] = []
    for _, row in out.iterrows():
        game_date = row["date"]
        home_team = str(row.get("home_team") or "")
        away_team = str(row.get("visitor_team") or "")
        home_last = last_dates.get(home_team)
        away_last = last_dates.get(away_team)
        home_days = (game_date - home_last).days if home_last is not None and pd.notna(game_date) else None
        away_days = (game_date - away_last).days if away_last is not None and pd.notna(game_date) else None
        home_rest.append(home_days)
        away_rest.append(away_days)
        home_b2b.append(1 if home_days == 1 else 0 if home_days is not None else None)
        away_b2b.append(1 if away_days == 1 else 0 if away_days is not None else None)
    out["home_rest_days"] = home_rest
    out["visitor_rest_days"] = away_rest
    out["home_b2b"] = home_b2b
    out["visitor_b2b"] = away_b2b
    return out


@dataclass
class TeamContextLocal:
    team: str
    pace: float
    off_rating: float
    def_rating: float
    injuries_out: int = 0
    back_to_back: bool = False
    rest_days: int | None = None
    games_last_3d: int | None = None
    form_7: float | None = None
    form_30: float | None = None


@dataclass
class GameInputsLocal:
    date: str
    home: TeamContextLocal
    away: TeamContextLocal
    market_total: float | None = None
    market_home_spread: float | None = None
    blend_total_market_w: float | None = None
    blend_margin_market_w: float | None = None


@dataclass
class SmartSimConfigLocal:
    n_sims: int = 2000
    seed: int | None = None
    priors_days_back: int = 21
    roster_mode: str = "historical"
    use_pbp: bool = True
    event_cfg: object | None = None


@dataclass(frozen=True)
class EventSimConfigLocal:
    possessions_per_game: float = 98.0
    possessions_jitter: float = 0.06
    base_tov_per_poss: float = 0.125
    base_shooting_foul_per_fga: float = 0.095
    base_nonshooting_foul_per_poss: float = 0.05
    base_oreb_rate: float = 0.24
    base_steal_share_of_tov: float = 0.55
    base_block_rate_on_2pa: float = 0.05
    blowout_margin: int = 18
    blowout_q4_margin: int = 15
    garbage_time_pace_scale: float = 0.94
    garbage_time_eff_scale: float = 0.96
    bench_weight_boost: float = 1.35
    reconcile_points: bool = True
    reconcile_max_changes_per_quarter: int = 12
    record_events: bool = False


@dataclass
class QuarterResultLocal:
    q: int
    home_pts_mu: float
    home_pts_sigma: float
    away_pts_mu: float
    away_pts_sigma: float
    corr: float


@dataclass
class QuarterSummaryLocal:
    quarters: list[QuarterResultLocal]
    final_total_mu: float
    final_total_sigma: float
    final_margin_mu: float
    final_margin_sigma: float
    probs: dict[str, float]
    evs: dict[str, float]


def _norm_name_key(value: object) -> str:
    text = str(value or "").strip().upper()
    if "(" in text:
        text = text.split("(", 1)[0]
    text = text.replace("-", " ")
    try:
        import unicodedata

        text = unicodedata.normalize("NFKD", text)
        text = text.encode("ascii", "ignore").decode("ascii")
    except Exception:
        pass
    text = re.sub(r"[^A-Z0-9\s]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    for suffix in (" JR", " SR", " II", " III", " IV"):
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
    return text


def _resolve_smart_sim_roster_mode_local(*, date_str: str, roster_mode: str | None) -> str:
    mode = str(roster_mode or "historical").strip().lower() or "historical"
    if mode not in {"historical", "pregame", "pregame_safe", "pregame-safe", "safe_pregame", "no_boxscore", "no-boxscore"}:
        return mode
    if mode != "historical":
        return mode
    try:
        import pandas as pd

        target = pd.to_datetime(str(date_str).strip(), errors="coerce")
        today = pd.Timestamp.now().normalize()
        if target is not None and (not pd.isna(target)) and target.normalize() >= today:
            return "pregame"
    except Exception:
        pass
    return mode


def _truthy_mask(values):
    import pandas as pd

    text = values.astype(str).str.strip().str.lower()
    mask = text.isin({"1", "true", "t", "yes", "y", "on"})
    try:
        numeric = pd.to_numeric(values, errors="coerce")
        mask = mask | (numeric.fillna(0.0).astype(float) > 0.5)
    except Exception:
        pass
    return mask


def _build_smart_sim_config_local(*, n_sims: int, seed: int | None, use_pbp: bool, roster_mode: str) -> SmartSimConfigLocal:
    return SmartSimConfigLocal(
        n_sims=int(n_sims),
        seed=seed,
        use_pbp=bool(use_pbp),
        roster_mode=str(roster_mode or "historical"),
        event_cfg=EventSimConfigLocal(),
    )


def _clean_id_str_local(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return re.sub(r"[^0-9A-Za-z_-]", "", text)


def _first_present_float_local(row, *columns: str, default: float = 0.0) -> float:
    for column in columns:
        try:
            if hasattr(row, "get"):
                value = row.get(column)
            else:
                value = row[column]
            numeric = float(value)
            if math.isfinite(numeric):
                return numeric
        except Exception:
            continue
    return float(default)


def _smart_sim_team_players_local(*, props_df, team_tri: str, opp_tri: str, processed_root: Path | None = None, date_str: str | None = None):
    import pandas as pd

    frame = _team_players_from_props_local(
        props_df=props_df,
        team_tri=team_tri,
        opp_tri=opp_tri,
        processed_root=processed_root,
        date_str=date_str,
    )
    if frame is None or getattr(frame, "empty", True):
        return pd.DataFrame()
    out = frame.copy()
    if "team" not in out.columns:
        out["team"] = str(team_tri or "").strip().upper()
    if "player_name" in out.columns:
        out["player_name"] = out["player_name"].astype(str).str.strip()
        out = out[out["player_name"].ne("")].copy()
    if "player_id" not in out.columns:
        out["player_id"] = None
    return out.reset_index(drop=True)


def _build_player_sim_rows_local(*, players_df, team_tri: str, opp_tri: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if players_df is None or getattr(players_df, "empty", True):
        return rows
    for _, row in players_df.iterrows():
        player_name = str(row.get("player_name") or "").strip()
        if not player_name:
            continue
        pts_mean = _first_present_float_local(row, "mean_pts", "pts_mean", "pred_points", "projected_points", "points", default=0.0)
        reb_mean = _first_present_float_local(row, "mean_reb", "reb_mean", "pred_rebounds", "projected_rebounds", "rebounds", default=0.0)
        ast_mean = _first_present_float_local(row, "mean_ast", "ast_mean", "pred_assists", "projected_assists", "assists", default=0.0)
        threes_mean = _first_present_float_local(row, "mean_threes", "threes_mean", "pred_threes", "projected_threes", "threes", default=0.0)
        stl_mean = _first_present_float_local(row, "mean_stl", "stl_mean", "pred_steals", "projected_steals", "steals", default=0.0)
        blk_mean = _first_present_float_local(row, "mean_blk", "blk_mean", "pred_blocks", "projected_blocks", "blocks", default=0.0)
        tov_mean = _first_present_float_local(row, "mean_tov", "tov_mean", "pred_turnovers", "projected_turnovers", "turnovers", default=0.0)
        pra_mean = _first_present_float_local(row, "mean_pra", "pra_mean", default=(pts_mean + reb_mean + ast_mean))
        position = str(row.get("position") or "").strip() or None
        minutes = _first_present_float_local(row, "pred_min", "minutes", "min", "mp", "min_played", "minutes_played", default=-999.0)

        def _sd_for(mean_value: float, key: str) -> float:
            return _first_present_float_local(row, f"sd_{key}", f"{key}_sd", default=max(1.0, abs(float(mean_value)) * 0.25))

        player_dict = {
            "team": str(team_tri or "").strip().upper(),
            "opponent": str(opp_tri or "").strip().upper(),
            "player_name": player_name,
            "player_id": row.get("player_id"),
            "pts_mean": pts_mean,
            "reb_mean": reb_mean,
            "ast_mean": ast_mean,
            "threes_mean": threes_mean,
            "pra_mean": pra_mean,
            "stl_mean": stl_mean,
            "blk_mean": blk_mean,
            "tov_mean": tov_mean,
            "pts_sd": _sd_for(pts_mean, "pts"),
            "reb_sd": _sd_for(reb_mean, "reb"),
            "ast_sd": _sd_for(ast_mean, "ast"),
            "threes_sd": _sd_for(threes_mean, "threes"),
            "pra_sd": _sd_for(pra_mean, "pra"),
            "stl_sd": _sd_for(stl_mean, "stl"),
            "blk_sd": _sd_for(blk_mean, "blk"),
            "tov_sd": _sd_for(tov_mean, "tov"),
            "q_pts": [0, 0, 0, 0],
            "q_reb": [0, 0, 0, 0],
            "q_ast": [0, 0, 0, 0],
            "q_threes": [0, 0, 0, 0],
        }
        if position is not None:
            player_dict["position"] = position
        if minutes > 0:
            player_dict["minutes"] = minutes
        rows.append(player_dict)
    rows.sort(key=lambda item: (float(item.get("pra_mean") or 0.0), float(item.get("pts_mean") or 0.0)), reverse=True)
    return rows


def _simulate_smart_game_local(*, date_str: str, home_tri: str, away_tri: str, props_df=None, quarters=None, market_total=None, market_home_spread=None, cfg=None, excluded_player_keys_by_team=None, pregame_context=None, processed_root: Path | None = None, **_kwargs):
    home_players_df = _smart_sim_team_players_local(props_df=props_df, team_tri=home_tri, opp_tri=away_tri, processed_root=processed_root, date_str=date_str)
    away_players_df = _smart_sim_team_players_local(props_df=props_df, team_tri=away_tri, opp_tri=home_tri, processed_root=processed_root, date_str=date_str)
    home_players = _build_player_sim_rows_local(players_df=home_players_df, team_tri=home_tri, opp_tri=away_tri)
    away_players = _build_player_sim_rows_local(players_df=away_players_df, team_tri=away_tri, opp_tri=home_tri)
    return {
        "date": str(date_str or ""),
        "home": str(home_tri or "").strip().upper(),
        "away": str(away_tri or "").strip().upper(),
        "market_total": market_total,
        "market_home_spread": market_home_spread,
        "quarters": quarters or [],
        "players": {
            "home": home_players,
            "away": away_players,
        },
        "home_team_total_pts_mean": sum(float(row.get("pts_mean") or 0.0) for row in home_players),
        "away_team_total_pts_mean": sum(float(row.get("pts_mean") or 0.0) for row in away_players),
        "excluded_player_keys_by_team": excluded_player_keys_by_team or {},
        "pregame_context": pregame_context or {},
        "n_sims": int(getattr(cfg, "n_sims", 0) or 0),
    }


def _build_local_smart_sim_module(*, processed_root: Path, league_code: str):
    source_root = processed_root.parent.parent if processed_root.parent.name.lower() == "data" else processed_root.parent
    return SimpleNamespace(
        simulate_smart_game=_simulate_smart_game_local,
        paths=SimpleNamespace(data_processed=processed_root, root=source_root),
        _clean_id_str=_clean_id_str_local,
        _norm_player_key=_norm_name_key,
    )


def _clamp_local(value: Any, lo: float, hi: float) -> float:
    try:
        numeric = float(value)
        if numeric < lo:
            return float(lo)
        if numeric > hi:
            return float(hi)
        return float(numeric)
    except Exception:
        return 0.0


def _clamp01_local(value: float) -> float:
    try:
        return float(max(0.0, min(1.0, float(value))))
    except Exception:
        return 0.7


def _high_pace_corr_threshold_local(*, league) -> float:
    return float(getattr(league, "baseline_pace") + 6.0)


def _quarter_duration_scale_local(*, league) -> float:
    try:
        quarter_minutes = float(getattr(league, "quarter_minutes", 12.0))
        return max(0.75, min(1.0, quarter_minutes / 12.0))
    except Exception:
        return 1.0


def _safe_float_local(value, default=None):
    try:
        import numpy as np

        numeric = float(value)
        if np.isfinite(numeric):
            return numeric
        return default
    except Exception:
        return default


def _adjustments_local(ctx: TeamContextLocal) -> float:
    adj = 0.0
    try:
        adj -= 0.5 * max(0, int(ctx.injuries_out or 0))
        if ctx.back_to_back:
            adj -= 0.8
        if ctx.form_7 is not None:
            adj += 0.5 * (_safe_float_local(ctx.form_7, 0.0) or 0.0)
        if ctx.form_30 is not None:
            adj += 0.25 * (_safe_float_local(ctx.form_30, 0.0) or 0.0)
    except Exception:
        pass
    return adj


def _quarter_splits_local(*, league: Any | None = None) -> list[float]:
    try:
        code = str(getattr(league, "code", "") or "").strip().lower()
        if code == "wnba":
            return [0.2425, 0.2475, 0.2525, 0.2575]
    except Exception:
        pass
    return [0.245, 0.245, 0.255, 0.255]


def _load_default_blend_weights_local(*, processed_root: Path) -> tuple[float, float]:
    cache_key = str(processed_root)
    if cache_key in _DEFAULT_BLEND_WEIGHTS_CACHE_LOCAL:
        return _DEFAULT_BLEND_WEIGHTS_CACHE_LOCAL[cache_key]
    total_w = 0.7
    margin_w = 0.95
    try:
        file_path = processed_root / "quarters_blend_weights.json"
        if file_path.exists():
            obj = json.loads(file_path.read_text(encoding="utf-8"))
            if isinstance(obj, dict):
                if obj.get("total_w") is not None:
                    total_w = _clamp01_local(float(obj.get("total_w")))
                if obj.get("margin_w") is not None:
                    margin_w = _clamp01_local(float(obj.get("margin_w")))
    except Exception:
        pass
    _DEFAULT_BLEND_WEIGHTS_CACHE_LOCAL[cache_key] = (float(total_w), float(margin_w))
    return _DEFAULT_BLEND_WEIGHTS_CACHE_LOCAL[cache_key]


def _blend_weights_local(*, processed_root: Path, inp: GameInputsLocal) -> tuple[float, float]:
    total_w, margin_w = _load_default_blend_weights_local(processed_root=processed_root)
    if inp.blend_total_market_w is not None:
        total_w = _clamp01_local(float(inp.blend_total_market_w))
    if inp.blend_margin_market_w is not None:
        margin_w = _clamp01_local(float(inp.blend_margin_market_w))
    return float(total_w), float(margin_w)


def _load_quarters_calibration_local(*, processed_root: Path) -> dict[str, Any] | None:
    cache_key = str(processed_root)
    if cache_key in _QUARTERS_CALIBRATION_CACHE_LOCAL:
        return _QUARTERS_CALIBRATION_CACHE_LOCAL[cache_key]
    try:
        file_path = processed_root / "quarters_calibration.json"
        if not file_path.exists():
            _QUARTERS_CALIBRATION_CACHE_LOCAL[cache_key] = None
            return None
        obj = json.loads(file_path.read_text(encoding="utf-8"))
        _QUARTERS_CALIBRATION_CACHE_LOCAL[cache_key] = obj if isinstance(obj, dict) else None
        return _QUARTERS_CALIBRATION_CACHE_LOCAL[cache_key]
    except Exception:
        _QUARTERS_CALIBRATION_CACHE_LOCAL[cache_key] = None
        return None


def _norm_split_local(value: Any) -> list[float] | None:
    try:
        import numpy as np

        arr = np.asarray(list(value), dtype=float)
        arr = np.where(np.isfinite(arr) & (arr > 0), arr, 0.0)
        total = float(arr.sum())
        if total <= 0 or len(arr.tolist()) != 4:
            return None
        arr = arr / total
        return [float(v) for v in arr.tolist()]
    except Exception:
        return None


def _quarter_splits_for_team_local(*, processed_root: Path, team_tri: str, is_home: bool | None = None) -> list[float]:
    cal = _load_quarters_calibration_local(processed_root=processed_root) or {}
    team = str(team_tri or "").strip().upper()
    try:
        if is_home is not None and isinstance(cal, dict):
            if bool(is_home):
                team_map = cal.get("team_split_home_by_tri")
                league_split = cal.get("league_split_home")
            else:
                team_map = cal.get("team_split_away_by_tri")
                league_split = cal.get("league_split_away")
            if isinstance(team_map, dict) and team in team_map:
                split = _norm_split_local(team_map.get(team))
                if split is not None:
                    return split
            split = _norm_split_local(league_split)
            if split is not None:
                return split
    except Exception:
        pass
    try:
        team_map = cal.get("team_split_by_tri") if isinstance(cal, dict) else None
        if isinstance(team_map, dict) and team in team_map:
            split = _norm_split_local(team_map.get(team))
            if split is not None:
                return split
    except Exception:
        pass
    try:
        split = _norm_split_local(cal.get("league_split") if isinstance(cal, dict) else None)
        if split is not None:
            return split
    except Exception:
        pass
    return _quarter_splits_local(league=league)


def _target_quarter_total_sd_local(*, processed_root: Path, quarter: int) -> float | None:
    try:
        import numpy as np

        cal = _load_quarters_calibration_local(processed_root=processed_root) or {}
        quarter_sd = cal.get("quarter_total_sd") if isinstance(cal, dict) else None
        if not isinstance(quarter_sd, dict):
            return None
        value = float(quarter_sd.get(f"q{int(quarter)}"))
        return value if np.isfinite(value) and value > 0 else None
    except Exception:
        return None


def _sigma_for_quarter_local(mu: float) -> float:
    return max(6.0, min(10.0, 0.9 * math.sqrt(max(1.0, mu))))


def _load_totals_calibration_for_date_local(*, processed_root: Path, date_str: str) -> dict[str, Any] | None:
    import pandas as pd

    try:
        target = pd.to_datetime(date_str).normalize()
    except Exception:
        return None
    key = (str(processed_root), str(target.date()))
    if key in _TOTALS_CALIBRATION_CACHE_LOCAL:
        return _TOTALS_CALIBRATION_CACHE_LOCAL[key]
    cutoff = target - pd.Timedelta(days=1)
    index_key = str(processed_root)
    if index_key not in _TOTALS_CALIBRATION_INDEX_LOCAL:
        idx: list[tuple[object, Path]] = []
        try:
            for file_path in processed_root.glob("calibration_totals_*.json"):
                ds = file_path.name.replace("calibration_totals_", "").replace(".json", "")
                try:
                    dt = pd.to_datetime(ds).normalize()
                except Exception:
                    continue
                idx.append((dt, file_path))
        except Exception:
            idx = []
        _TOTALS_CALIBRATION_INDEX_LOCAL[index_key] = sorted(idx, key=lambda item: item[0])
    best_path = None
    try:
        for dt, file_path in _TOTALS_CALIBRATION_INDEX_LOCAL.get(index_key, []):
            if dt <= cutoff:
                best_path = file_path
            else:
                break
    except Exception:
        best_path = None
    if best_path is None:
        _TOTALS_CALIBRATION_CACHE_LOCAL[key] = None
        return None
    try:
        obj = json.loads(best_path.read_text(encoding="utf-8"))
        _TOTALS_CALIBRATION_CACHE_LOCAL[key] = obj if isinstance(obj, dict) else None
        return _TOTALS_CALIBRATION_CACHE_LOCAL[key]
    except Exception:
        _TOTALS_CALIBRATION_CACHE_LOCAL[key] = None
        return None


def _apply_totals_calibration_local(*, processed_root: Path, date_str: str, home_tri: str, away_tri: str, home_mu: float, away_mu: float) -> tuple[float, float, dict[str, float]]:
    cal = _load_totals_calibration_for_date_local(processed_root=processed_root, date_str=date_str) or {}
    q_biases: dict[str, float] = {}
    try:
        global_map = cal.get("global") if isinstance(cal, dict) else None
        if isinstance(global_map, dict):
            quarter_biases = global_map.get("quarters")
            if isinstance(quarter_biases, dict):
                for key, value in quarter_biases.items():
                    q_biases[str(key)] = _clamp_local(value, -6.0, 6.0)
            sim_quarter_biases = global_map.get("sim_quarters")
            if isinstance(sim_quarter_biases, dict):
                for key, value in sim_quarter_biases.items():
                    kk = str(key)
                    combined = float(q_biases.get(kk, 0.0)) + _clamp_local(value, -6.0, 6.0)
                    q_biases[kk] = _clamp_local(combined, -6.0, 6.0)
            keys = [f"q{i}" for i in range(1, 5) if f"q{i}" in q_biases]
            if len(keys) == 4:
                mean_bias = float(sum(float(q_biases[key]) for key in keys) / 4.0)
                for key in keys:
                    q_biases[key] = _clamp_local(float(q_biases[key]) - mean_bias, -6.0, 6.0)
    except Exception:
        q_biases = {}
    try:
        team_map = cal.get("team") if isinstance(cal, dict) else None
        if isinstance(team_map, dict):
            if home_tri in team_map:
                home_mu += _clamp_local(team_map.get(home_tri), -4.0, 4.0)
            if away_tri in team_map:
                away_mu += _clamp_local(team_map.get(away_tri), -4.0, 4.0)
    except Exception:
        pass
    try:
        global_map = cal.get("global") if isinstance(cal, dict) else None
        if isinstance(global_map, dict):
            game_bias = _clamp_local(global_map.get("game_total_bias", 0.0), -15.0, 15.0)
            game_bias += _clamp_local(global_map.get("sim_game_total_bias", 0.0), -15.0, 15.0)
            game_bias = _clamp_local(game_bias, -15.0, 15.0)
            home_mu += 0.5 * game_bias
            away_mu += 0.5 * game_bias
    except Exception:
        pass
    return float(home_mu), float(away_mu), q_biases


def _simulate_quarters_local(*, processed_root: Path, inp: GameInputsLocal, league, n_samples: int = 5000) -> QuarterSummaryLocal:
    import numpy as np

    home = inp.home
    away = inp.away
    pace = np.mean([
        _safe_float_local(home.pace, getattr(league, "baseline_pace")),
        _safe_float_local(away.pace, getattr(league, "baseline_pace")),
    ])
    try:
        b2b_drag = 0.0
        if bool(home.back_to_back):
            b2b_drag += 1.0
        if bool(away.back_to_back):
            b2b_drag += 1.0
        inj_drag = 0.3 * max(0, int(home.injuries_out or 0)) + 0.3 * max(0, int(away.injuries_out or 0))
        pace = max(getattr(league, "baseline_pace") - 8.0, pace - b2b_drag - inj_drag)
    except Exception:
        pass
    league_avg_rating = getattr(league, "baseline_off_rating")

    def _clip_rating(value: float, lo: float = 95.0, hi: float = 130.0) -> float:
        try:
            return float(max(lo, min(hi, value)))
        except Exception:
            return float(value)

    home_off = _safe_float_local(home.off_rating, league_avg_rating)
    away_off = _safe_float_local(away.off_rating, league_avg_rating)
    home_def = _safe_float_local(home.def_rating, league_avg_rating)
    away_def = _safe_float_local(away.def_rating, league_avg_rating)
    home_eff = _clip_rating(home_off - (away_def - league_avg_rating))
    away_eff = _clip_rating(away_off - (home_def - league_avg_rating))
    home_mu = max(getattr(league, "min_team_points"), (home_eff / 100.0) * pace) + _adjustments_local(home)
    away_mu = max(getattr(league, "min_team_points"), (away_eff / 100.0) * pace) + _adjustments_local(away)
    try:
        home_mu, away_mu, q_biases = _apply_totals_calibration_local(processed_root=processed_root, date_str=inp.date, home_tri=str(home.team).upper(), away_tri=str(away.team).upper(), home_mu=home_mu, away_mu=away_mu)
    except Exception:
        q_biases = {}
    w_total, w_margin = _blend_weights_local(processed_root=processed_root, inp=inp)
    if inp.market_total is not None:
        market_total = float(inp.market_total)
        cur_total_mu = home_mu + away_mu
        blend_total = w_total * market_total + (1.0 - w_total) * cur_total_mu
        scale = blend_total / max(1e-6, cur_total_mu)
        home_mu *= scale
        away_mu *= scale
    cur_total_mu = home_mu + away_mu
    margin_mu = home_mu - away_mu
    if inp.market_home_spread is not None:
        market_spread = float(inp.market_home_spread)
        target_margin_mu = w_margin * (-market_spread) + (1.0 - w_margin) * margin_mu
        home_mu = 0.5 * (cur_total_mu + target_margin_mu)
        away_mu = 0.5 * (cur_total_mu - target_margin_mu)
        min_team_pts = float(getattr(league, "min_team_points"))
        if home_mu < min_team_pts:
            home_mu = min_team_pts
            away_mu = cur_total_mu - home_mu
        if away_mu < min_team_pts:
            away_mu = min_team_pts
            home_mu = cur_total_mu - away_mu
    home_splits = _quarter_splits_for_team_local(processed_root=processed_root, team_tri=home.team, is_home=True)
    away_splits = _quarter_splits_for_team_local(processed_root=processed_root, team_tri=away.team, is_home=False)
    cur_total_mu = float(home_mu + away_mu)
    q_means: list[tuple[float, float]] = []
    for quarter_idx in range(1, 5):
        h_frac = float(home_splits[quarter_idx - 1])
        a_frac = float(away_splits[quarter_idx - 1])
        h_mu_q = float(h_frac * home_mu)
        a_mu_q = float(a_frac * away_mu)
        try:
            bias = q_biases.get(f"q{quarter_idx}") if isinstance(q_biases, dict) else None
            if bias is not None and np.isfinite(float(bias)):
                total_q = float(h_mu_q + a_mu_q)
                if total_q > 1e-6:
                    share_h = float(h_mu_q / total_q)
                    h_mu_q += float(bias) * share_h
                    a_mu_q += float(bias) * (1.0 - share_h)
        except Exception:
            pass
        q_means.append((h_mu_q, a_mu_q))
    try:
        sum_mu = float(sum((h + a) for (h, a) in q_means))
        if sum_mu > 1e-6:
            scale_factor = float(cur_total_mu / sum_mu)
            scale_factor = float(max(0.95, min(1.05, scale_factor)))
            q_means = [(float(h * scale_factor), float(a * scale_factor)) for (h, a) in q_means]
    except Exception:
        pass
    quarters: list[QuarterResultLocal] = []
    for quarter_idx in range(1, 5):
        h_mu_q, a_mu_q = q_means[quarter_idx - 1]
        h_sig_q = _sigma_for_quarter_local(h_mu_q)
        a_sig_q = _sigma_for_quarter_local(a_mu_q)
        try:
            stress = 0.0
            stress += (0.1 if bool(home.back_to_back) else 0.0) + (0.1 * max(0, int(home.injuries_out or 0)))
            stress += (0.1 if bool(away.back_to_back) else 0.0) + (0.1 * max(0, int(away.injuries_out or 0)))
            for form_value in [home.form_7, home.form_30, away.form_7, away.form_30]:
                try:
                    fv = abs(_safe_float_local(form_value, 0.0) or 0.0)
                    stress += 0.05 * min(3.0, fv)
                except Exception:
                    pass
            scale = 1.0 + min(0.35, stress)
            h_sig_q = float(h_sig_q) * scale
            a_sig_q = float(a_sig_q) * scale
        except Exception:
            pass
        corr_q = 0.25
        try:
            if pace >= _high_pace_corr_threshold_local(league=league):
                corr_q = min(0.40, corr_q + 0.10)
        except Exception:
            pass
        try:
            target_sd = _target_quarter_total_sd_local(processed_root=processed_root, quarter=quarter_idx)
            if target_sd is not None:
                sh = float(h_sig_q)
                sa = float(a_sig_q)
                base_total_sd = float(math.sqrt(max(1e-6, (sh * sh) + (sa * sa) + 2.0 * corr_q * sh * sa)))
                if base_total_sd > 1e-6:
                    scale = float(target_sd / base_total_sd)
                    scale = float(max(0.70, min(1.35, scale)))
                    h_sig_q = float(h_sig_q) * scale
                    a_sig_q = float(a_sig_q) * scale
        except Exception:
            pass
        duration_scale = _quarter_duration_scale_local(league=league)
        if duration_scale < 1.0:
            h_sig_q = float(h_sig_q) * float(duration_scale)
            a_sig_q = float(a_sig_q) * float(duration_scale)
        quarters.append(QuarterResultLocal(q=quarter_idx, home_pts_mu=h_mu_q, home_pts_sigma=h_sig_q, away_pts_mu=a_mu_q, away_pts_sigma=a_sig_q, corr=corr_q))
    total_samples = []
    margin_samples = []
    for _ in range(min(5000, max(1000, n_samples))):
        h_sum = 0.0
        a_sum = 0.0
        for quarter in quarters:
            try:
                cov = np.array([
                    [quarter.home_pts_sigma ** 2, quarter.corr * quarter.home_pts_sigma * quarter.away_pts_sigma],
                    [quarter.corr * quarter.home_pts_sigma * quarter.away_pts_sigma, quarter.away_pts_sigma ** 2],
                ])
                chol = np.linalg.cholesky(cov)
                z = np.random.normal(size=(2,))
                v = chol @ z
                h_val = max(0.0, quarter.home_pts_mu + v[0])
                a_val = max(0.0, quarter.away_pts_mu + v[1])
            except Exception:
                h_val = np.random.normal(loc=quarter.home_pts_mu, scale=quarter.home_pts_sigma)
                a_val = np.random.normal(loc=quarter.away_pts_mu, scale=quarter.away_pts_sigma)
            h_sum += h_val
            a_sum += a_val
        total_samples.append(h_sum + a_sum)
        margin_samples.append(h_sum - a_sum)
    total_samples_arr = np.array(total_samples)
    margin_samples_arr = np.array(margin_samples)
    final_total_mu = float(np.mean(total_samples_arr))
    final_total_sigma = float(np.std(total_samples_arr))
    final_margin_mu = float(np.mean(margin_samples_arr))
    final_margin_sigma = float(np.std(margin_samples_arr))
    probs: dict[str, float] = {}
    try:
        probs["p_home_ml"] = float(np.mean(margin_samples_arr > 0.0))
        if inp.market_home_spread is not None:
            hs = float(inp.market_home_spread)
            probs["p_home_cover"] = float(np.mean(margin_samples_arr + hs > 0.0))
            probs["p_away_cover"] = float(np.mean(-margin_samples_arr - hs > 0.0))
        if inp.market_total is not None:
            tot = float(inp.market_total)
            probs["p_total_over"] = float(np.mean(total_samples_arr > tot))
            probs["p_total_under"] = float(np.mean(total_samples_arr < tot))
    except Exception:
        pass

    def _ev(prob: float, amer: float | None) -> float | None:
        try:
            if amer is None:
                dec = 1.909090909
            else:
                a = float(amer)
                dec = (1.0 + a / 100.0) if a > 0 else (1.0 + 100.0 / abs(a))
            return (prob * (dec - 1.0)) - ((1.0 - prob) * 1.0)
        except Exception:
            return None

    evs: dict[str, float] = {}
    try:
        home_ml_ev = _ev(probs.get("p_home_ml", 0.0), None)
        if home_ml_ev is not None:
            evs["ev_home_ml"] = home_ml_ev
        if inp.market_home_spread is not None:
            ph = probs.get("p_home_cover")
            pa = probs.get("p_away_cover")
            if ph is not None:
                ev_home_cover = _ev(ph, -110.0)
                if ev_home_cover is not None:
                    evs["ev_home_cover"] = ev_home_cover
            if pa is not None:
                ev_away_cover = _ev(pa, -110.0)
                if ev_away_cover is not None:
                    evs["ev_away_cover"] = ev_away_cover
        if inp.market_total is not None:
            po = probs.get("p_total_over")
            pu = probs.get("p_total_under")
            if po is not None:
                ev_total_over = _ev(po, -110.0)
                if ev_total_over is not None:
                    evs["ev_total_over"] = ev_total_over
            if pu is not None:
                ev_total_under = _ev(pu, -110.0)
                if ev_total_under is not None:
                    evs["ev_total_under"] = ev_total_under
    except Exception:
        pass
    return QuarterSummaryLocal(quarters=quarters, final_total_mu=final_total_mu, final_total_sigma=final_total_sigma, final_margin_mu=final_margin_mu, final_margin_sigma=final_margin_sigma, probs=probs, evs=evs)


def _period_lines_from_processed_local(*, processed_root: Path, date_str: str, home_tri: str, away_tri: str) -> dict[str, Any] | None:
    import pandas as pd

    file_path = processed_root / f"period_lines_{str(date_str).strip()}.csv"
    if not file_path.exists():
        return None
    try:
        import numpy as np

        df = pd.read_csv(file_path)
        if df is None or df.empty:
            return None
        df = df.copy()
        df["home_tri"] = df.get("home_team", "").astype(str).map(_to_tricode_local)
        df["away_tri"] = df.get("visitor_team", "").astype(str).map(_to_tricode_local)
        match = df[(df["home_tri"] == str(home_tri).upper()) & (df["away_tri"] == str(away_tri).upper())].head(1)
        if match.empty:
            return None
        row = match.iloc[0].to_dict()
        out: dict[str, Any] = {}
        for key, value in row.items():
            if key in {"date", "home_team", "visitor_team", "home_tri", "away_tri"}:
                continue
            try:
                numeric = pd.to_numeric(value, errors="coerce")
                out[key] = float(numeric) if np.isfinite(numeric) else None
            except Exception:
                out[key] = None
        return out
    except Exception:
        return None


def _market_lines_from_processed_odds_local(*, processed_root: Path, date_str: str, home_tri: str, away_tri: str) -> tuple[float | None, float | None]:
    import pandas as pd

    file_path = processed_root / f"game_odds_{str(date_str).strip()}.csv"
    if not file_path.exists():
        return None, None
    try:
        import numpy as np

        df = pd.read_csv(file_path)
        if df is None or df.empty:
            return None, None
        df = df.copy()
        df["home_tri"] = df.get("home_team", "").astype(str).map(_to_tricode_local)
        df["away_tri"] = df.get("visitor_team", "").astype(str).map(_to_tricode_local)
        match = df[(df["home_tri"] == str(home_tri).upper()) & (df["away_tri"] == str(away_tri).upper())].head(1)
        if match.empty:
            return None, None
        row = match.iloc[0]
        total = pd.to_numeric(row.get("total"), errors="coerce")
        spread = pd.to_numeric(row.get("home_spread"), errors="coerce")
        total_v = float(total) if np.isfinite(total) else None
        spread_v = float(spread) if np.isfinite(spread) else None
        return total_v, spread_v
    except Exception:
        return None, None


def _frame_series_local(df, column: str, default: object):
    import pandas as pd

    if df is None:
        return pd.Series(dtype=object)
    if column in getattr(df, "columns", []):
        return df[column]
    return pd.Series([default] * len(df), index=getattr(df, "index", None))


def _normalize_position_local(value: Any) -> str:
    text = str(value or "").strip().upper()
    if not text or text in {"NAN", "NONE"}:
        return ""
    cleaned = text.replace("-", " ").replace("/", " ").replace(",", " ").replace(".", " ")
    parts = [part.strip() for part in cleaned.split() if str(part).strip()]
    for part in parts:
        if part in {"PG", "SG", "G", "GUARD"}:
            return "G"
        if part in {"SF", "PF", "F", "FORWARD"}:
            return "F"
        if part in {"C", "CENTER"}:
            return "C"
    if "PG" in text or "SG" in text or text.startswith("G") or "GUARD" in text:
        return "G"
    if "SF" in text or "PF" in text or text.startswith("F") or "FORWARD" in text:
        return "F"
    if text.endswith("C") or "CENTER" in text:
        return "C"
    return ""


def _to_tricode_local(value: Any) -> str:
    if not value:
        return ""
    normalized = _normalize_team_local(value)
    tricode = _NAME_TO_TRI_LOCAL.get(normalized)
    if tricode:
        return tricode
    raw = str(value).strip().upper()
    if len(raw) == 3:
        return raw
    return raw


def _pick_rosters_file_local(*, processed_root: Path, season: str | None):
    candidates: list[Path] = []
    if season:
        candidates.append(processed_root / f"rosters_{season}.csv")
    candidates.extend(sorted(processed_root.glob("rosters_*.csv"), reverse=True))
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _coalesce_team_player_frames_local(*frames):
    import pandas as pd
    import numpy as np

    usable = [frame.copy() for frame in frames if isinstance(frame, pd.DataFrame) and not frame.empty]
    if not usable:
        return pd.DataFrame()
    comb = pd.concat(usable, ignore_index=True, sort=False)
    if comb.empty:
        return pd.DataFrame()
    if "team" in comb.columns:
        comb["team"] = comb["team"].astype(str).str.upper().str.strip()
        comb.loc[comb["team"].isin({"", "NAN", "NONE"}), "team"] = np.nan
    if "opponent" in comb.columns:
        comb["opponent"] = comb["opponent"].astype(str).str.upper().str.strip()
        comb.loc[comb["opponent"].isin({"", "NAN", "NONE"}), "opponent"] = np.nan
    if "player_name" in comb.columns:
        comb["player_name"] = comb["player_name"].astype(str).str.strip()
        comb.loc[comb["player_name"].isin({"", "NAN", "NONE"}), "player_name"] = np.nan
    if "position" in comb.columns:
        comb["position"] = comb["position"].map(_normalize_position_local)
        comb.loc[comb["position"].eq(""), "position"] = np.nan
    if "player_id" in comb.columns:
        comb["player_id"] = pd.to_numeric(comb["player_id"], errors="coerce")
    key_cols = [column for column in ["player_name", "team"] if column in comb.columns]
    if not key_cols:
        return comb
    comb = comb.dropna(subset=key_cols).copy()
    if comb.empty:
        return pd.DataFrame(columns=key_cols)
    out = comb.groupby(key_cols, sort=False, dropna=False, group_keys=False).apply(lambda group: group.ffill().iloc[-1]).reset_index(drop=True)
    if "position" in out.columns:
        out["position"] = out["position"].map(_normalize_position_local)
    return out


def _load_pregame_expected_minutes_local(*, processed_root: Path, date_str: str):
    import pandas as pd

    cache_key = (str(processed_root), str(date_str).strip())
    cached = _PREGAME_EXPECTED_MINUTES_CACHE_LOCAL.get(cache_key)
    if cached is not None:
        return cached
    file_csv = processed_root / f"pregame_expected_minutes_{str(date_str).strip()}.csv"
    file_parquet = processed_root / f"pregame_expected_minutes_{str(date_str).strip()}.parquet"
    file_path = file_csv if file_csv.exists() else file_parquet
    if file_path is None or (not file_path.exists()):
        df = pd.DataFrame()
        _PREGAME_EXPECTED_MINUTES_CACHE_LOCAL[cache_key] = df
        return df
    try:
        if file_path.suffix.lower() == ".parquet":
            try:
                df = pd.read_parquet(file_path)
            except Exception:
                if file_csv.exists():
                    df = pd.read_csv(file_csv)
                else:
                    df = pd.DataFrame()
        else:
            df = pd.read_csv(file_path)
    except Exception:
        df = pd.DataFrame()
    if df is None or df.empty:
        df = pd.DataFrame()
        _PREGAME_EXPECTED_MINUTES_CACHE_LOCAL[cache_key] = df
        return df
    out = df.copy()
    out.columns = [str(column).strip() for column in out.columns]
    if "team_tri" not in out.columns:
        if "team" in out.columns:
            out = out.rename(columns={"team": "team_tri"})
        elif "team_abbrev" in out.columns:
            out = out.rename(columns={"team_abbrev": "team_tri"})
    if "team_tri" in out.columns:
        out["team_tri"] = out["team_tri"].astype(str).str.upper().str.strip()
    if "player_name" in out.columns:
        out["player_name"] = out["player_name"].astype(str).str.strip()
    if "player_id" in out.columns:
        out["player_id"] = pd.to_numeric(out["player_id"], errors="coerce")
    for column in ["exp_min_mean", "starter_prob", "exp_min_sd", "exp_min_cap"]:
        if column in out.columns:
            out[column] = pd.to_numeric(out[column], errors="coerce")
    if "is_starter" in out.columns:
        try:
            out["is_starter"] = out["is_starter"].astype(bool)
        except Exception:
            out["is_starter"] = out["is_starter"].astype(str).str.strip().str.lower().isin({"true", "1", "yes", "y"})
    keep = [column for column in ["date", "team_tri", "player_id", "player_name", "exp_min_mean", "exp_min_source", "starter_prob", "is_starter", "exp_min_sd", "exp_min_cap", "exp_asof_ts"] if column in out.columns]
    out = out[keep].copy() if keep else pd.DataFrame()
    out = out.dropna(subset=["team_tri"]).copy() if (not out.empty and "team_tri" in out.columns) else out
    _PREGAME_EXPECTED_MINUTES_CACHE_LOCAL[cache_key] = out
    return out


def _merge_pregame_expected_minutes_for_team_local(*, processed_root: Path, team_df, date_str: str, team_tri: str):
    import pandas as pd
    import numpy as np

    diag: dict[str, Any] = {"attempted": True, "applied": False, "date": str(date_str), "team": str(team_tri).upper().strip(), "path": str(processed_root / f"pregame_expected_minutes_{str(date_str).strip()}.csv")}
    if team_df is None or getattr(team_df, "empty", True):
        diag["reason"] = "empty_team_df"
        return (pd.DataFrame() if team_df is None else team_df), diag
    pem = _load_pregame_expected_minutes_local(processed_root=processed_root, date_str=str(date_str))
    if pem is None or pem.empty:
        diag["reason"] = "missing_pregame_expected_minutes"
        return team_df, diag
    team = str(team_tri or "").upper().strip()
    if not team:
        diag["reason"] = "missing_team"
        return team_df, diag
    if "team_tri" not in pem.columns:
        diag["reason"] = "bad_schema"
        return team_df, diag
    pem_t = pem[pem["team_tri"].astype(str).str.upper().str.strip() == team].copy()
    if pem_t.empty:
        diag["reason"] = "team_not_found"
        return team_df, diag
    out = team_df.copy()
    if "player_name" in out.columns:
        out["player_name"] = out["player_name"].astype(str).str.strip()
    out["_pkey"] = _frame_series_local(out, "player_name", "").map(_norm_name_key)
    pem_t["player_name"] = _frame_series_local(pem_t, "player_name", "").astype(str).str.strip()
    pem_t["_pkey"] = _frame_series_local(pem_t, "player_name", "").map(_norm_name_key)
    try:
        if "player_id" in pem_t.columns and pem_t["player_id"].notna().any():
            pem_t = pem_t.sort_values(["player_id", "exp_min_mean"], ascending=[True, False], kind="stable")
            pem_t = pem_t.drop_duplicates(subset=["player_id"], keep="first")
        pem_t = pem_t.sort_values(["_pkey", "exp_min_mean"], ascending=[True, False], kind="stable")
        pem_t = pem_t.drop_duplicates(subset=["_pkey"], keep="first")
    except Exception:
        pass
    cols = [column for column in pem_t.columns if column not in {"date", "team_tri", "player_name"}]
    pid_maps: dict[str, dict[int, Any]] = {}
    key_maps: dict[str, dict[str, Any]] = {}
    try:
        pid_ser = pd.to_numeric(pem_t.get("player_id"), errors="coerce").astype("Int64") if "player_id" in pem_t.columns else pd.Series([], dtype="Int64")
        for column in cols:
            if column == "player_id":
                continue
            if len(pid_ser) and pid_ser.notna().any():
                pid_maps[column] = {int(pid): value for pid, value in zip(pid_ser.tolist(), pem_t[column].tolist()) if pid is not None and not (isinstance(pid, float) and (not np.isfinite(pid)))}
            key_maps[column] = dict(zip(pem_t.get("_pkey", pd.Series([], dtype=str)).astype(str).tolist(), pem_t[column].tolist()))
    except Exception:
        pid_maps = {}
        key_maps = {}
    pid_out = pd.to_numeric(out.get("player_id"), errors="coerce").astype("Int64") if "player_id" in out.columns else pd.Series([pd.NA] * len(out), index=out.index, dtype="Int64")
    for column in cols:
        if column == "_pkey":
            continue
        base = out[column] if column in out.columns else pd.Series([np.nan] * len(out), index=out.index)
        v_pid = pid_out.map(pid_maps[column]) if pid_maps.get(column) else pd.Series([np.nan] * len(out), index=out.index)
        v_key = out["_pkey"].astype(str).map(key_maps[column]) if key_maps.get(column) else pd.Series([np.nan] * len(out), index=out.index)
        filled = base.where(base.notna(), other=v_pid)
        filled = filled.where(filled.notna(), other=v_key)
        out[column] = filled
    try:
        if "exp_min_mean" in out.columns:
            exp = pd.to_numeric(out["exp_min_mean"], errors="coerce")
            diag["matched_exp_min"] = int(exp.notna().sum())
            v_pid = pid_out.map(pid_maps["exp_min_mean"]) if pid_maps.get("exp_min_mean") else pd.Series([np.nan] * len(out), index=out.index)
            v_key = out["_pkey"].astype(str).map(key_maps["exp_min_mean"]) if key_maps.get("exp_min_mean") else pd.Series([np.nan] * len(out), index=out.index)
            diag["matched_pid_n"] = int(v_pid.notna().sum())
            diag["matched_key_n"] = int(v_key.notna().sum())
    except Exception:
        pass
    diag.setdefault("matched_pid_n", 0)
    diag.setdefault("matched_key_n", 0)
    diag["applied"] = True
    out = out.drop(columns=["_pkey"], errors="ignore")
    return out, diag


def _prune_pregame_rotation_pool_local(*, team_df, team_tri: str, min_keep: int = 8, max_keep: int | None = None, protected_names: set[str] | None = None, league_code: str | None = None):
    import pandas as pd
    import numpy as np

    diag: dict[str, Any] = {"attempted": True, "team": str(team_tri).upper().strip(), "applied": False}
    if team_df is None or getattr(team_df, "empty", True):
        diag["reason"] = "empty_team_df"
        return (pd.DataFrame() if team_df is None else team_df), diag
    out = team_df.copy().reset_index(drop=True)
    diag["before_n"] = int(len(out))
    if max_keep is None:
        max_keep = 11 if str(league_code or "").strip().lower() == "wnba" else 13
    max_keep = int(max(max_keep, min_keep))
    diag["max_keep"] = int(max_keep)
    if len(out) <= max_keep:
        diag["reason"] = "pool_already_small"
        return out, diag
    exp = pd.to_numeric(out.get("exp_min_mean"), errors="coerce") if "exp_min_mean" in out.columns else pd.Series([np.nan] * len(out), index=out.index, dtype=float)
    starter_prob = pd.to_numeric(out.get("starter_prob"), errors="coerce") if "starter_prob" in out.columns else pd.Series([np.nan] * len(out), index=out.index, dtype=float)
    roll5 = pd.to_numeric(out.get("roll5_min"), errors="coerce") if "roll5_min" in out.columns else pd.Series([np.nan] * len(out), index=out.index, dtype=float)
    roll10 = pd.to_numeric(out.get("roll10_min"), errors="coerce") if "roll10_min" in out.columns else pd.Series([np.nan] * len(out), index=out.index, dtype=float)
    roll3 = pd.to_numeric(out.get("roll3_min"), errors="coerce") if "roll3_min" in out.columns else pd.Series([np.nan] * len(out), index=out.index, dtype=float)
    lag1 = pd.to_numeric(out.get("lag1_min"), errors="coerce") if "lag1_min" in out.columns else pd.Series([np.nan] * len(out), index=out.index, dtype=float)
    signal_mask = exp.fillna(0.0).gt(0.0) | starter_prob.fillna(0.0).gt(0.0) | roll5.fillna(0.0).gt(0.0) | roll10.fillna(0.0).gt(0.0) | roll3.fillna(0.0).gt(0.0) | lag1.fillna(0.0).gt(0.0)
    diag["signal_n"] = int(signal_mask.sum())
    cand = out.loc[signal_mask].copy() if int(signal_mask.sum()) >= int(min_keep) else out.copy()
    cand["_starter_prob"] = starter_prob.reindex(cand.index).fillna(0.0).astype(float)
    cand["_exp_min_mean"] = exp.reindex(cand.index).fillna(0.0).astype(float)
    cand["_roll5_min"] = roll5.reindex(cand.index).fillna(0.0).astype(float)
    cand["_roll10_min"] = roll10.reindex(cand.index).fillna(0.0).astype(float)
    cand["_roll3_min"] = roll3.reindex(cand.index).fillna(0.0).astype(float)
    cand["_lag1_min"] = lag1.reindex(cand.index).fillna(0.0).astype(float)
    cand["_name"] = _frame_series_local(cand, "player_name", "").astype(str).str.strip()
    protected_keys = {_norm_name_key(name) for name in (protected_names or set()) if str(name or "").strip()}
    cand["_protected"] = cand["_name"].map(_norm_name_key).isin(protected_keys).astype(int)
    keep = cand.sort_values(["_protected", "_starter_prob", "_exp_min_mean", "_roll5_min", "_roll10_min", "_roll3_min", "_lag1_min", "_name"], ascending=[False, False, False, False, False, False, False, True], kind="stable").head(int(max_keep)).drop(columns=["_protected", "_starter_prob", "_exp_min_mean", "_roll5_min", "_roll10_min", "_roll3_min", "_lag1_min", "_name"], errors="ignore").reset_index(drop=True)
    if len(keep) < int(min_keep):
        diag["reason"] = "keep_below_minimum"
        return out, diag
    diag["after_n"] = int(len(keep))
    diag["dropped_n"] = int(max(0, len(out) - len(keep)))
    try:
        keep_names = {str(value).strip() for value in keep.get("player_name", pd.Series(dtype=str)).astype(str).tolist() if str(value).strip()}
        diag["dropped_players"] = [str(value).strip() for value in out.get("player_name", pd.Series(dtype=str)).astype(str).tolist() if str(value).strip() and str(value).strip() not in keep_names][:12]
    except Exception:
        pass
    diag["applied"] = True
    return keep, diag


def _load_market_player_names_by_matchup_local(*, processed_root: Path, raw_root: Path, date_str: str):
    import pandas as pd

    cache_key = (str(processed_root), str(date_str).strip())
    cached = _MARKET_PLAYER_NAMES_CACHE_LOCAL.get(cache_key)
    if cached is not None:
        return cached
    candidates = [raw_root / f"odds_nba_player_props_{str(date_str).strip()}.csv", processed_root / f"oddsapi_player_props_{str(date_str).strip()}.csv"]
    snapshot_path = next((path for path in candidates if path.exists()), None)
    if snapshot_path is None:
        out: dict[tuple[str, str], set[str]] = {}
        _MARKET_PLAYER_NAMES_CACHE_LOCAL[cache_key] = out
        return out
    try:
        odds = pd.read_csv(snapshot_path)
    except Exception:
        out = {}
        _MARKET_PLAYER_NAMES_CACHE_LOCAL[cache_key] = out
        return out
    if odds is None or odds.empty or not {"home_team", "away_team", "player_name"}.issubset(set(odds.columns)):
        out = {}
        _MARKET_PLAYER_NAMES_CACHE_LOCAL[cache_key] = out
        return out
    try:
        tmp = odds.copy()
        tmp["home_tri"] = tmp["home_team"].astype(str).map(lambda value: _to_tricode_local(value) or str(value or "").strip().upper())
        tmp["away_tri"] = tmp["away_team"].astype(str).map(lambda value: _to_tricode_local(value) or str(value or "").strip().upper())
        tmp["player_name"] = tmp["player_name"].astype(str).str.strip()
        tmp = tmp[tmp["home_tri"].astype(str).str.len().gt(0) & tmp["away_tri"].astype(str).str.len().gt(0) & tmp["player_name"].ne("")].copy()
        market_players: dict[tuple[str, str], set[str]] = {}
        for row in tmp[["home_tri", "away_tri", "player_name"]].drop_duplicates().itertuples(index=False):
            key = (str(row.home_tri).upper().strip(), str(row.away_tri).upper().strip())
            market_players.setdefault(key, set()).add(str(row.player_name).strip())
        _MARKET_PLAYER_NAMES_CACHE_LOCAL[cache_key] = market_players
        return market_players
    except Exception:
        out = {}
        _MARKET_PLAYER_NAMES_CACHE_LOCAL[cache_key] = out
        return out


def _market_player_names_for_matchup_local(*, processed_root: Path, raw_root: Path, props_df, date_str: str | None = None, home_tri: str, away_tri: str):
    import pandas as pd

    out: dict[str, set[str]] = {str(home_tri).upper().strip(): set(), str(away_tri).upper().strip(): set()}
    if props_df is None or not isinstance(props_df, pd.DataFrame) or props_df.empty or not {"team", "player_name"}.issubset(set(props_df.columns)):
        return out
    try:
        market_names: set[str] = set()
        ds = str(date_str or "").strip()
        if ds:
            market_names = _load_market_player_names_by_matchup_local(processed_root=processed_root, raw_root=raw_root, date_str=ds).get((str(home_tri).upper().strip(), str(away_tri).upper().strip()), set())
        tmp = props_df.copy()
        tmp["team"] = tmp["team"].astype(str).str.upper().str.strip()
        tmp["player_name"] = tmp["player_name"].astype(str).str.strip()
        tmp = tmp[tmp["player_name"].ne("")].copy()
        if "opponent" in tmp.columns:
            tmp["opponent"] = tmp["opponent"].astype(str).str.upper().str.strip()
            tmp = tmp[((tmp["team"] == str(home_tri).upper().strip()) & (tmp["opponent"] == str(away_tri).upper().strip())) | ((tmp["team"] == str(away_tri).upper().strip()) & (tmp["opponent"] == str(home_tri).upper().strip()))].copy()
        else:
            tmp = tmp[tmp["team"].isin({str(home_tri).upper().strip(), str(away_tri).upper().strip()})].copy()
        if "playing_today" in tmp.columns:
            pt = tmp["playing_today"].astype(str).str.lower().str.strip()
            tmp = tmp[~pt.isin(["false", "0", "no", "n"])].copy()
        if "team_on_slate" in tmp.columns:
            tos = tmp["team_on_slate"].astype(str).str.lower().str.strip()
            tmp = tmp[~tos.isin(["false", "0", "no", "n"])].copy()
        if market_names:
            tmp = tmp[tmp["player_name"].isin(market_names)].copy()
        for team_code, team_rows in tmp.groupby("team"):
            key = str(team_code).upper().strip()
            if key in out:
                out[key].update(str(value).strip() for value in team_rows["player_name"].tolist() if str(value).strip())
    except Exception:
        return out
    return out


def _infer_game_id_local(*, processed_root: Path, date_str: str, home_tri: str, away_tri: str) -> str | None:
    try:
        import pandas as pd

        file_path = processed_root / f"boxscores_{str(date_str).strip()}.csv"
        if not file_path.exists():
            return None
        df = pd.read_csv(file_path, usecols=lambda column: str(column).strip().upper() in {"GAME_ID", "TEAM_ABBREVIATION"})
        if df is None or df.empty:
            return None
        df.columns = [str(column).strip().upper() for column in df.columns]
        if not {"GAME_ID", "TEAM_ABBREVIATION"}.issubset(set(df.columns)):
            return None
        df["TEAM_ABBREVIATION"] = df["TEAM_ABBREVIATION"].astype(str).str.upper().str.strip()
        grouped = df[df["TEAM_ABBREVIATION"].isin({str(home_tri).upper().strip(), str(away_tri).upper().strip()})].dropna(subset=["GAME_ID"]).groupby("GAME_ID")["TEAM_ABBREVIATION"].nunique()
        candidates = grouped[grouped >= 2].index.tolist()
        if not candidates:
            return None
        candidate = candidates[0]
        return str(int(float(candidate))) if str(candidate).strip() else None
    except Exception:
        return None


def _team_players_from_processed_boxscores_local(*, processed_root: Path, date_str: str, home_tri: str, away_tri: str, team_tri: str, game_id: str | None = None):
    import pandas as pd

    try:
        file_path = processed_root / f"boxscores_{str(date_str).strip()}.csv"
        if not file_path.exists():
            return pd.DataFrame()
        df = pd.read_csv(file_path)
        if df is None or df.empty:
            return pd.DataFrame()
        df = df.copy()
        df["TEAM_ABBREVIATION"] = df.get("TEAM_ABBREVIATION", "").astype(str).str.upper().str.strip()
        df["PLAYER_NAME"] = df.get("PLAYER_NAME", "").astype(str).str.strip()
        df["game_id"] = pd.to_numeric(df.get("game_id"), errors="coerce")
        home = str(home_tri or "").strip().upper()
        away = str(away_tri or "").strip().upper()
        team = str(team_tri or "").strip().upper()
        opp = str(away if team == home else home)
        gid = None
        try:
            if game_id is not None and str(game_id).strip() and str(game_id).lower() != "nan":
                gid = int(float(game_id))
        except Exception:
            gid = None
        if gid is None:
            g = df[df["TEAM_ABBREVIATION"].isin([home, away])].dropna(subset=["game_id"]).copy()
            if not g.empty:
                by = g.groupby("game_id")["TEAM_ABBREVIATION"].nunique()
                cand = by[by >= 2].index.tolist()
                if cand:
                    gid = int(float(cand[0]))
        if gid is None:
            return pd.DataFrame()
        team_df = df[(df["game_id"] == gid) & (df["TEAM_ABBREVIATION"] == team)].copy()
        if team_df.empty:
            return pd.DataFrame()
        if "MIN" in team_df.columns:
            try:
                team_df["MIN"] = pd.to_numeric(team_df["MIN"], errors="coerce").fillna(0.0)
                team_df = team_df[team_df["MIN"] > 0].copy()
            except Exception:
                pass
        if team_df.empty:
            return pd.DataFrame()
        out = pd.DataFrame({
            "player_id": pd.to_numeric(team_df.get("PLAYER_ID"), errors="coerce"),
            "player_name": team_df["PLAYER_NAME"],
            "team": team,
            "opponent": opp,
            "position": team_df.get("START_POSITION", "").map(_normalize_position_local) if "START_POSITION" in team_df.columns else "",
            "playing_today": True,
        })
        out = out.dropna(subset=["player_name"]).copy()
        out["player_name"] = out["player_name"].astype(str).str.strip()
        return out[out["player_name"].ne("")].drop_duplicates(subset=["player_name", "team"], keep="last")
    except Exception:
        return pd.DataFrame()


def _team_players_from_processed_rosters_local(*, processed_root: Path, date_str: str, home_tri: str, away_tri: str, team_tri: str):
    import pandas as pd
    import numpy as np

    try:
        team = str(team_tri or "").strip().upper()
        home = str(home_tri or "").strip().upper()
        away = str(away_tri or "").strip().upper()
        if not team:
            return pd.DataFrame()
        opp = str(away if team == home else home)
        season = None
        try:
            date_value = pd.to_datetime(str(date_str), errors="coerce")
            if pd.notna(date_value):
                start_year = int(date_value.year) if int(date_value.month) >= 7 else int(date_value.year) - 1
                season = f"{start_year}-{str(start_year + 1)[-2:]}"
        except Exception:
            season = None
        roster_path = _pick_rosters_file_local(processed_root=processed_root, season=season)
        if roster_path is None or (not roster_path.exists()):
            return pd.DataFrame()
        df = pd.read_csv(roster_path)
        if df is None or df.empty:
            return pd.DataFrame()
        cols = {str(column).upper(): column for column in df.columns}
        pid_col = cols.get("PLAYER_ID")
        name_col = cols.get("PLAYER") or cols.get("PLAYER_NAME")
        tri_col = cols.get("TEAM_ABBREVIATION")
        pos_col = cols.get("POSITION") or cols.get("START_POSITION")
        if not (name_col and tri_col):
            return pd.DataFrame()
        tmp = df[[column for column in [pid_col, name_col, tri_col, pos_col] if column]].copy()
        tmp[tri_col] = tmp[tri_col].astype(str).str.upper().str.strip()
        tmp = tmp[tmp[tri_col] == team].copy()
        if tmp.empty:
            return pd.DataFrame()
        
        # Load active players from league_status if available
        active_players = set()
        try:
            league_status_path = processed_root / f"league_status_{str(date_str).strip()}.csv"
            if league_status_path.exists():
                ldf = pd.read_csv(league_status_path)
                if ldf is not None and not ldf.empty:
                    cols_ls = {str(column).upper(): column for column in ldf.columns}
                    name_col_ls = cols_ls.get("PLAYER_NAME") or cols_ls.get("PLAYER")
                    team_col_ls = cols_ls.get("TEAM_ABBREVIATION") or cols_ls.get("TEAM")
                    playing_col_ls = cols_ls.get("PLAYING_TODAY") or cols_ls.get("PLAYING")
                    if name_col_ls and team_col_ls:
                        tmp_ls = ldf.copy()
                        tmp_ls[team_col_ls] = tmp_ls[team_col_ls].astype(str).str.upper().str.strip()
                        tmp_ls = tmp_ls[tmp_ls[team_col_ls] == team].copy()
                        if playing_col_ls and not tmp_ls.empty:
                            pt = tmp_ls[playing_col_ls].astype(str).str.strip().str.lower()
                            tmp_ls = tmp_ls[pt.isin({"1", "true", "t", "yes", "y"})].copy()
                        active_players = {_norm_name_key(str(value).strip()) for value in tmp_ls[name_col_ls].astype(str).tolist() if str(value).strip()}
        except Exception:
            pass
        
        out = pd.DataFrame({
            "player_id": pd.to_numeric(tmp[pid_col], errors="coerce") if pid_col else np.nan,
            "player_name": tmp[name_col].astype(str).str.strip(),
            "team": team,
            "opponent": opp,
            "position": tmp[pos_col].map(_normalize_position_local) if pos_col else "",
            "playing_today": pd.Series(
                [_norm_name_key(str(pname).strip()) in active_players if active_players else True 
                 for pname in tmp[name_col].astype(str)],
                index=tmp.index
            ),
        })
        out = out.dropna(subset=["player_name"]).copy()
        out = out[out["player_name"].astype(str).str.strip().ne("")].copy()
        return out.drop_duplicates(subset=["player_name", "team"], keep="last")
    except Exception:
        return pd.DataFrame()


def _filter_team_players_against_processed_roster_local(*, processed_root: Path, team_df, date_str: str, home_tri: str, away_tri: str, team_tri: str, min_keep: int = 5):
    import pandas as pd

    if team_df is None or getattr(team_df, "empty", True):
        return pd.DataFrame() if team_df is None else team_df
    try:
        def _league_status_allowed_names() -> set[str]:
            try:
                file_path = processed_root / f"league_status_{str(date_str).strip()}.csv"
                if not file_path.exists():
                    return set()
                ldf = pd.read_csv(file_path, usecols=lambda column: str(column).strip().lower() in {"player_name", "team", "playing_today"})
                if ldf is None or ldf.empty:
                    return set()
                cols = {str(column).strip().lower(): column for column in ldf.columns}
                name_col = cols.get("player_name")
                team_col = cols.get("team")
                if not (name_col and team_col):
                    return set()
                tmp = ldf.copy()
                tmp[team_col] = tmp[team_col].astype(str).str.upper().str.strip()
                tmp[name_col] = tmp[name_col].astype(str).str.strip()
                tmp = tmp[(tmp[team_col] == str(team_tri or "").strip().upper()) & tmp[name_col].ne("")].copy()
                pt_col = cols.get("playing_today")
                if pt_col and not tmp.empty:
                    pt = tmp[pt_col].astype(str).str.strip().str.lower()
                    tmp = tmp[pt.isin({"1", "true", "t", "yes", "y"})].copy()
                return {_norm_name_key(value) for value in tmp[name_col].astype(str).tolist() if str(value).strip()}
            except Exception:
                return set()
        roster = _team_players_from_processed_rosters_local(processed_root=processed_root, date_str=str(date_str), home_tri=str(home_tri), away_tri=str(away_tri), team_tri=str(team_tri))
        if roster is None or roster.empty:
            return team_df
        out = team_df.copy()
        allowed_names = {_norm_name_key(value) for value in roster.get("player_name", pd.Series(dtype=str)).astype(str).tolist() if str(value).strip()}
        allowed_names |= _league_status_allowed_names()
        if not allowed_names:
            return team_df
        names = out.get("player_name", pd.Series(["" for _ in range(len(out))], index=out.index)).astype(str)
        keep = names.map(_norm_name_key).isin(allowed_names)
        kept = out[keep].copy()
        if len(kept) >= int(max(1, min_keep)):
            return kept.reset_index(drop=True)
        return team_df
    except Exception:
        return team_df


def _team_players_from_espn_boxscore_local(*, processed_root: Path, league_code: str, date_str: str, home_tri: str, away_tri: str, team_tri: str, event_id: str | None = None):
    import pandas as pd

    try:
        resolved_event_id = str(event_id or "").strip() or (
            _espn_event_id_for_matchup_local(
                processed_root=processed_root,
                date_str=str(date_str),
                home_tri=str(home_tri),
                away_tri=str(away_tri),
                league_code=league_code,
            )
            or ""
        )
        if not resolved_event_id:
            return pd.DataFrame()
        summary = _espn_summary_local(processed_root=processed_root, event_id=resolved_event_id, league_code=league_code)
        box = (summary or {}).get("boxscore") or {}
        teams = box.get("players") or []
        if not isinstance(teams, list) or not teams:
            return pd.DataFrame()

        target_team = str(team_tri or "").strip().upper()
        rows: list[dict[str, Any]] = []
        for team_payload in teams:
            team = (team_payload or {}).get("team") or {}
            team_abbr = str(team.get("abbreviation") or "").strip().upper()
            resolved_team_tri = _espn_to_tri_local(team_abbr, league_code=league_code) if team_abbr else ""
            if target_team and resolved_team_tri != target_team:
                continue
            stats_groups = (team_payload or {}).get("statistics") or []
            if not isinstance(stats_groups, list):
                continue
            for group in stats_groups:
                athletes = (group or {}).get("athletes") or []
                if not isinstance(athletes, list):
                    continue
                for athlete_payload in athletes:
                    athlete = (athlete_payload or {}).get("athlete") or {}
                    player_name = str(athlete.get("displayName") or "").strip()
                    if not player_name:
                        continue
                    player_id = str(athlete.get("id") or "").strip()
                    rows.append(
                        {
                            "player_name": player_name,
                            "player_id": player_id or None,
                            "team": resolved_team_tri or target_team,
                            "team_tri": resolved_team_tri or target_team,
                        }
                    )
        if not rows:
            return pd.DataFrame()
        out = pd.DataFrame(rows)
        out["player_name"] = out["player_name"].astype(str).str.strip()
        out = out[out["player_name"].ne("")].copy()
        out = out.drop_duplicates(subset=["team_tri", "player_name"], keep="last")
        return out.reset_index(drop=True)
    except Exception:
        return pd.DataFrame()


def _espn_name_to_id_map_for_game_local(*, smart_sim_module, date_str: str, home_tri: str, away_tri: str, event_id: str | None = None) -> dict[tuple[str, str], str]:
    import pandas as pd

    clean_id_str = getattr(smart_sim_module, "_clean_id_str")
    norm_player_key = getattr(smart_sim_module, "_norm_player_key", _norm_name_key)
    source_paths = getattr(smart_sim_module, "paths")

    if not str(event_id or "").strip() and not str(date_str or "").strip():
        return {}

    def _from_pbp_history(lookback_days: int = 120) -> dict[tuple[str, str], str]:
        try:
            fp = source_paths.data_processed / "pbp_espn_history.csv"
            if not fp.exists():
                return {}
            usecols = [
                "date",
                "team",
                "enter_player_id",
                "exit_player_id",
                "enter_player_name",
                "exit_player_name",
            ]
            hist = pd.read_csv(fp, usecols=usecols)
            if hist is None or hist.empty:
                return {}

            teams = {str(home_tri or "").upper().strip(), str(away_tri or "").upper().strip()}
            teams = {team for team in teams if team}
            if teams:
                hist["team"] = hist["team"].astype(str).str.upper().str.strip()
                hist = hist[hist["team"].isin(list(teams))].copy()
            if hist.empty:
                return {}

            try:
                cutoff = pd.to_datetime(str(date_str), errors="coerce")
                if pd.notna(cutoff):
                    start = cutoff - pd.Timedelta(days=int(lookback_days))
                    hist["date"] = pd.to_datetime(hist["date"], errors="coerce")
                    hist = hist[(hist["date"].notna()) & (hist["date"] >= start) & (hist["date"] <= cutoff)].copy()
            except Exception:
                pass
            if hist.empty:
                return {}

            def _rows(id_col: str, name_col: str) -> pd.DataFrame:
                try:
                    df = hist[["team", "date", id_col, name_col]].copy()
                    df["id"] = df[id_col].map(clean_id_str)
                    df["key"] = df[name_col].astype(str).map(norm_player_key)
                    df = df[(df["id"].astype(str).str.len() > 0) & (df["key"].astype(str).str.len() > 0)].copy()
                    df["team"] = df["team"].astype(str).str.upper().str.strip()
                    df["key"] = df["key"].astype(str).str.upper().str.strip()
                    return df[["team", "key", "id", "date"]]
                except Exception:
                    return pd.DataFrame(columns=["team", "key", "id", "date"])

            enter_df = _rows("enter_player_id", "enter_player_name")
            exit_df = _rows("exit_player_id", "exit_player_name")
            combo = pd.concat([enter_df, exit_df], ignore_index=True)
            if combo.empty:
                return {}

            try:
                combo = combo.sort_values(["date"])
            except Exception:
                pass
            combo = combo.drop_duplicates(subset=["team", "key"], keep="last")
            out: dict[tuple[str, str], str] = {}
            for _, row in combo.iterrows():
                team = str(row.get("team") or "").upper().strip()
                key = str(row.get("key") or "").upper().strip()
                player_id = clean_id_str(row.get("id"))
                if team and key and player_id:
                    out[(team, key)] = player_id
            return out
        except Exception:
            return {}

    try:
        eid = str(event_id or "").strip() or (
            _espn_event_id_for_matchup_local(
                processed_root=source_paths.data_processed,
                date_str=str(date_str),
                home_tri=str(home_tri),
                away_tri=str(away_tri),
                league_code=_league_code_from_source_root_local(source_paths.root),
            )
            or ""
        )
        if not eid:
            return _from_pbp_history()
        summary = _espn_summary_local(
            processed_root=source_paths.data_processed,
            event_id=eid,
            league_code=_league_code_from_source_root_local(source_paths.root),
        )
        box = (summary or {}).get("boxscore") or {}
        teams = box.get("players") or []
        if not isinstance(teams, list) or not teams:
            return _from_pbp_history()

        out: dict[tuple[str, str], str] = {}
        for team_payload in teams:
            team = (team_payload or {}).get("team") or {}
            team_abbr = str(team.get("abbreviation") or "").strip().upper()
            team_tri = _espn_to_tri_local(team_abbr, league_code=_league_code_from_source_root_local(source_paths.root)) if team_abbr else ""
            stats_groups = (team_payload or {}).get("statistics") or []
            if not isinstance(stats_groups, list) or not stats_groups:
                continue
            group0 = stats_groups[0] or {}
            athletes = group0.get("athletes") or []
            if not isinstance(athletes, list):
                continue

            for athlete_payload in athletes:
                if not isinstance(athlete_payload, dict):
                    continue
                athlete = athlete_payload.get("athlete") or {}
                player_id = clean_id_str(athlete.get("id"))
                name = str(athlete.get("displayName") or "").strip()
                if not player_id or not name or not team_tri:
                    continue
                key = norm_player_key(name)
                if not key:
                    continue
                out[(str(team_tri).upper().strip(), str(key).upper().strip())] = player_id
        return out or _from_pbp_history()
    except Exception:
        return _from_pbp_history()


def _rotation_sim_minutes_from_history_local(*, smart_sim_module, league_code: str, team_df, date_str: str, home_tri: str, away_tri: str, team_tri: str, lookback_days: int = 28):
    import numpy as np
    import pandas as pd

    read_hist_any = getattr(smart_sim_module, "_read_hist_any")
    roll_minutes_unscaled = getattr(smart_sim_module, "_roll_minutes_unscaled")
    regularize_rotation_minutes = getattr(smart_sim_module, "_regularize_rotation_minutes")
    minutes_caps_from_team_df = getattr(smart_sim_module, "_minutes_caps_from_team_df")
    cap_and_redistribute_minutes = getattr(smart_sim_module, "_cap_and_redistribute_minutes")
    rotation_minutes_signal_guardrail = getattr(smart_sim_module, "_rotation_minutes_signal_guardrail")
    clean_id_str = getattr(smart_sim_module, "_clean_id_str")
    norm_player_key = getattr(smart_sim_module, "_norm_player_key", _norm_name_key)
    source_paths = getattr(smart_sim_module, "paths")

    league = _league_for_code_local(league_code)
    diag: dict[str, Any] = {
        "attempted": True,
        "applied": False,
        "source": "history",
        "team": str(team_tri).upper().strip(),
        "lookback_days": int(lookback_days),
    }
    if team_df is None or getattr(team_df, "empty", True):
        diag["reason"] = "empty_players"
        return None, None, None, diag

    team_u = str(team_tri or "").strip().upper()
    if not team_u:
        diag["reason"] = "missing_team"
        return None, None, None, diag

    st_hist = read_hist_any(
        source_paths.data_processed / "rotation_stints_history.parquet",
        source_paths.data_processed / "rotation_stints_history.csv",
    )
    if st_hist is None or st_hist.empty:
        diag["reason"] = "no_rotation_stints_history"
        return None, None, None, diag

    need = {"team", "duration_sec", "lineup_player_ids"}
    if not need.issubset(set(st_hist.columns)):
        diag["reason"] = "history_missing_columns"
        diag["missing_cols"] = sorted(list(need - set(st_hist.columns)))
        return None, None, None, diag

    st = st_hist.copy()
    st["team"] = st["team"].astype(str).str.upper().str.strip()
    st = st[st["team"] == team_u].copy()
    if st.empty:
        diag["reason"] = "team_not_in_history"
        return None, None, None, diag

    if "date" in st.columns:
        try:
            cutoff = pd.to_datetime(str(date_str), errors="coerce")
            if pd.notna(cutoff):
                start = cutoff - pd.Timedelta(days=int(lookback_days))
                st["date"] = pd.to_datetime(st["date"], errors="coerce")
                st = st[(st["date"].notna()) & (st["date"] >= start) & (st["date"] < cutoff)].copy()
        except Exception:
            pass

    if st.empty:
        diag["reason"] = "no_recent_history"
        return None, None, None, diag

    name_to_id = _espn_name_to_id_map_for_game_local(
        smart_sim_module=smart_sim_module,
        date_str=str(date_str),
        home_tri=str(home_tri),
        away_tri=str(away_tri),
        event_id=None,
    )
    if not name_to_id:
        diag["reason"] = "no_espn_name_map"
        return None, None, None, diag

    tmp = team_df.copy().reset_index(drop=True)
    tmp["_pkey"] = tmp.get("player_name", pd.Series(["" for _ in range(len(tmp))])).map(norm_player_key)
    tmp["_espn_id"] = tmp["_pkey"].map(lambda key: name_to_id.get((team_u, str(key).upper().strip()), ""))
    tmp["_espn_id"] = tmp["_espn_id"].astype(str).replace({"nan": "", "None": ""}).str.strip()

    st2 = st[["team", "duration_sec", "lineup_player_ids"]].copy()
    st2["duration_sec"] = pd.to_numeric(st2["duration_sec"], errors="coerce").fillna(0.0)
    st2["player_id"] = st2["lineup_player_ids"].astype(str).str.split(";")
    st2 = st2.explode("player_id")
    st2["player_id"] = st2["player_id"].map(clean_id_str)
    st2 = st2[st2["player_id"].astype(str).str.len() > 0]
    if st2.empty:
        diag["reason"] = "no_player_ids_in_history"
        return None, None, None, diag

    mins_df = st2.groupby(["team", "player_id"], as_index=False)["duration_sec"].sum()
    mins_df["minutes"] = mins_df["duration_sec"].astype(float) / 60.0
    mins_df = mins_df[mins_df["team"].astype(str).str.upper().str.strip() == team_u].copy()
    if mins_df.empty:
        diag["reason"] = "no_minutes_from_history"
        return None, None, None, diag

    mins_df["minutes"] = pd.to_numeric(mins_df["minutes"], errors="coerce").fillna(0.0).astype(float)
    total_hist = float(mins_df["minutes"].sum())
    if not np.isfinite(total_hist) or total_hist <= 0:
        diag["reason"] = "bad_history_total_minutes"
        return None, None, None, diag
    mins_df["minutes_scaled"] = mins_df["minutes"] * (float(league.regulation_team_minutes) / total_hist)
    id_to_min = dict(zip(mins_df["player_id"].astype(str), mins_df["minutes_scaled"].astype(float)))

    base_w = roll_minutes_unscaled(tmp, date_str=str(date_str), team_tri=team_u)
    sim_min = pd.Series([0.0] * len(tmp), index=tmp.index, dtype=float)
    espn_ids = tmp["_espn_id"].astype(str)
    have = espn_ids.str.len() > 0

    mapped_players = 0
    mapped_minutes_sum = 0.0
    for pid in sorted(set(espn_ids[have].tolist())):
        minutes = float(id_to_min.get(str(pid), 0.0))
        if minutes <= 0:
            continue
        idx = tmp.index[espn_ids == pid]
        if len(idx) == 0:
            continue
        weights = base_w.loc[idx].astype(float)
        weight_sum = float(weights.sum())
        if not np.isfinite(weight_sum) or weight_sum <= 0:
            alloc = pd.Series([minutes / float(len(idx))] * len(idx), index=idx, dtype=float)
        else:
            alloc = (weights / weight_sum) * minutes
        sim_min.loc[idx] = alloc.astype(float)
        mapped_players += int(len(idx))
        mapped_minutes_sum += float(alloc.sum())

    leftover = float(float(league.regulation_team_minutes) - mapped_minutes_sum)
    if leftover > 1e-6:
        weights = base_w.astype(float).clip(lower=0.0)
        weight_sum = float(weights.sum())
        if (not np.isfinite(weight_sum)) or weight_sum <= 0:
            sim_min = sim_min + (float(leftover) / float(max(1, len(sim_min))))
        else:
            sim_min = sim_min + ((weights / weight_sum) * float(leftover))

    total_sim = float(sim_min.sum())
    if np.isfinite(total_sim) and total_sim > 0:
        sim_min = sim_min * (float(league.regulation_team_minutes) / total_sim)

    mapped_frac = float(mapped_minutes_sum) / float(league.regulation_team_minutes) if np.isfinite(mapped_minutes_sum) else 0.0
    sim_min, reg_diag = regularize_rotation_minutes(
        tmp,
        sim_min,
        date_str=str(date_str),
        team_tri=team_u,
        mapped_minutes_frac=mapped_frac,
    )

    caps = minutes_caps_from_team_df(tmp, base_minutes=sim_min)
    sim_min = cap_and_redistribute_minutes(sim_min, total_target=league.regulation_team_minutes, cap=caps, iters=12)

    signal_guard = rotation_minutes_signal_guardrail(
        tmp,
        sim_min,
        date_str=str(date_str),
        team_tri=team_u,
    )
    if not bool(signal_guard.get("ok", True)):
        diag["applied"] = False
        diag["reason"] = str(signal_guard.get("reason") or "rotation_minutes_conflict_with_current_signals")
        diag["signal_guard"] = signal_guard
        return None, None, None, diag

    lineup_pool: list[list[int]] = []
    lineup_w: list[float] = []
    try:
        if {"lineup_player_ids", "duration_sec"}.issubset(set(st.columns)):
            s2 = st.copy()
            s2["duration_sec"] = pd.to_numeric(s2["duration_sec"], errors="coerce").fillna(0.0).astype(float)
            for _, row in s2.iterrows():
                lineup = str(row.get("lineup_player_ids") or "").strip()
                if not lineup:
                    continue
                pids = [pid.strip() for pid in lineup.split(";") if pid.strip()]
                if len(pids) < 5:
                    continue
                idxs: list[int] = []
                for pid in pids:
                    candidates = tmp.index[tmp["_espn_id"].astype(str) == str(pid)].tolist()
                    if candidates:
                        idxs.append(int(candidates[0]))
                idxs_unique = list(dict.fromkeys(idxs))
                if len(idxs_unique) == 5:
                    weight = float(row.get("duration_sec") or 0.0)
                    if weight > 0:
                        lineup_pool.append([int(value) for value in idxs_unique])
                        lineup_w.append(weight)
    except Exception:
        lineup_pool = []
        lineup_w = []

    diag["history_rows"] = int(len(st))
    diag["mapped_players"] = int(mapped_players)
    diag["mapped_minutes"] = float(mapped_minutes_sum)
    diag["expected_minutes_coverage"] = float(reg_diag.get("exp_cov", 0.0))
    diag["regularization_blend"] = float(reg_diag.get("blend", 0.0))
    diag["leftover_minutes"] = float(max(0.0, leftover))
    diag["lineup_pool_n"] = int(len(lineup_pool))
    diag["minutes_cap_mean"] = float(np.mean(caps.to_numpy(dtype=float))) if len(caps) else None
    diag["minutes_cap_max"] = float(np.max(caps.to_numpy(dtype=float))) if len(caps) else None

    try:
        total_target = float(league.regulation_team_minutes)
        mapped_ids = [pid for pid in sorted(set(espn_ids[have].tolist())) if float(id_to_min.get(str(pid), 0.0)) > 0.0]
        mapped_id_n = int(len(mapped_ids))
        frac = float(mapped_minutes_sum) / float(max(1e-6, total_target))
        diag["mapped_id_n"] = mapped_id_n
        diag["mapped_minutes_frac"] = frac
        if mapped_id_n < 5 or frac < 0.50 or int(len(lineup_pool)) < 5:
            diag["applied"] = False
            diag["reason"] = "rotation_mapping_too_sparse"
            return None, None, None, diag
    except Exception:
        diag["applied"] = False
        diag["reason"] = str(diag.get("reason") or "rotation_mapping_guard_failed")
        return None, None, None, diag

    diag["applied"] = True
    diag["sim_minutes_sum"] = float(sim_min.sum())
    lineup_weights = np.asarray(lineup_w, dtype=float) if lineup_w else None
    return sim_min.astype(float), (lineup_pool if lineup_pool else None), lineup_weights, diag


def _rotation_sim_minutes_for_team_local(*, smart_sim_module, league_code: str, team_df, date_str: str, home_tri: str, away_tri: str, team_tri: str, side: str, game_id: str | None):
    read_rotation_stints = getattr(smart_sim_module, "_read_rotation_stints")
    build_player_minutes_from_stints = getattr(smart_sim_module, "_build_player_minutes_from_stints")
    roll_minutes_unscaled = getattr(smart_sim_module, "_roll_minutes_unscaled")
    regularize_rotation_minutes = getattr(smart_sim_module, "_regularize_rotation_minutes")
    minutes_caps_from_team_df = getattr(smart_sim_module, "_minutes_caps_from_team_df")
    cap_and_redistribute_minutes = getattr(smart_sim_module, "_cap_and_redistribute_minutes")

    import numpy as np
    import pandas as pd

    league = _league_for_code_local(league_code)
    diag: dict[str, Any] = {
        "attempted": True,
        "applied": False,
        "side": str(side).lower().strip(),
        "team": str(team_tri).upper().strip(),
        "game_id": str(game_id or "").strip(),
    }
    if team_df is None or getattr(team_df, "empty", True):
        diag["reason"] = "empty_players"
        return None, None, None, diag

    gid = str(game_id or "").strip()
    if not gid:
        sim_min, lineups, lw, diag2 = _rotation_sim_minutes_from_history_local(
            smart_sim_module=smart_sim_module,
            league_code=league_code,
            team_df=team_df,
            date_str=date_str,
            home_tri=home_tri,
            away_tri=away_tri,
            team_tri=team_tri,
        )
        try:
            diag2["fallback_reason"] = "missing_game_id"
        except Exception:
            pass
        return sim_min, lineups, lw, diag2

    stints = read_rotation_stints(gid, side=side)
    if stints is None or stints.empty:
        sim_min, lineups, lw, diag2 = _rotation_sim_minutes_from_history_local(
            smart_sim_module=smart_sim_module,
            team_df=team_df,
            date_str=date_str,
            home_tri=home_tri,
            away_tri=away_tri,
            team_tri=team_tri,
            lookback_days=28,
        )
        diag.update({key: value for key, value in (diag2 or {}).items() if key not in {"attempted", "team"}})
        if diag.get("applied"):
            return sim_min, lineups, lw, diag
        diag["reason"] = str(diag.get("reason") or "missing_stints_file")
        return None, None, None, diag

    eid = ""
    try:
        if "event_id" in stints.columns:
            eid = str(stints["event_id"].dropna().astype(str).head(1).iloc[0] or "").strip()
            if eid:
                diag["event_id"] = eid
    except Exception:
        eid = ""

    mins_df = build_player_minutes_from_stints(stints)
    if mins_df is None or mins_df.empty:
        diag["reason"] = "no_minutes_from_stints"
        return None, None, None, diag

    team_u = str(team_tri or "").strip().upper()
    mins_df = mins_df[mins_df["team"].astype(str).str.upper().str.strip() == team_u].copy()
    if mins_df.empty:
        diag["reason"] = "team_not_in_stints"
        return None, None, None, diag

    name_to_id = _espn_name_to_id_map_for_game_local(
        smart_sim_module=smart_sim_module,
        date_str=str(date_str),
        home_tri=str(home_tri),
        away_tri=str(away_tri),
        event_id=eid or None,
    )
    if not name_to_id:
        diag["reason"] = "no_espn_name_map"
        return None, None, None, diag

    tmp = team_df.copy().reset_index(drop=True)
    tmp["_pkey"] = tmp.get("player_name", pd.Series(["" for _ in range(len(tmp))])).map(_norm_name_key)
    tmp["_espn_id"] = tmp["_pkey"].map(lambda value: name_to_id.get((team_u, str(value).upper().strip()), ""))
    tmp["_espn_id"] = tmp["_espn_id"].astype(str).replace({"nan": "", "None": ""}).str.strip()

    mins_df["player_id"] = mins_df["player_id"].astype(str).map(lambda value: str(value or "").strip().removesuffix(".0") if str(value or "").strip().endswith(".0") else str(value or "").strip())
    mins_df["minutes"] = pd.to_numeric(mins_df["minutes"], errors="coerce").fillna(0.0).astype(float)
    total_raw = float(mins_df["minutes"].sum())
    diag["rotation_total_minutes_raw"] = total_raw
    if (not np.isfinite(total_raw)) or total_raw <= 0 or total_raw < (0.8 * float(league.regulation_team_minutes)) or total_raw > (1.42 * float(league.regulation_team_minutes)):
        sim_min, lineups, lw, diag2 = rotation_sim_minutes_from_history(
            team_df=team_df,
            date_str=date_str,
            home_tri=home_tri,
            away_tri=away_tri,
            team_tri=team_tri,
            lookback_days=28,
        )
        diag.update({key: value for key, value in (diag2 or {}).items() if key not in {"attempted", "team"}})
        diag["applied"] = bool(diag.get("applied", False))
        diag["fallback_reason"] = "bad_rotation_total_minutes"
        diag["reason"] = str(diag.get("reason") or "bad_rotation_total_minutes")
        return sim_min, lineups, lw, diag

    mins_df["minutes_scaled"] = mins_df["minutes"] * (float(league.regulation_team_minutes) / float(total_raw))
    id_to_min = dict(zip(mins_df["player_id"].astype(str), mins_df["minutes_scaled"].astype(float)))
    total_target = float(league.regulation_team_minutes)
    diag["rotation_total_minutes"] = float(total_target)

    base_w = roll_minutes_unscaled(tmp, date_str=str(date_str), team_tri=team_u)
    sim_min = pd.Series([0.0] * len(tmp), index=tmp.index, dtype=float)
    espn_ids = tmp["_espn_id"].astype(str)
    have = espn_ids.str.len() > 0
    mapped_players = 0
    mapped_minutes_sum = 0.0
    for pid in sorted(set(espn_ids[have].tolist())):
        minutes = float(id_to_min.get(str(pid), 0.0))
        if minutes <= 0:
            continue
        idx = tmp.index[espn_ids == pid]
        if len(idx) == 0:
            continue
        weights = base_w.loc[idx].astype(float)
        weight_sum = float(weights.sum())
        if not np.isfinite(weight_sum) or weight_sum <= 0:
            alloc = pd.Series([minutes / float(len(idx))] * len(idx), index=idx, dtype=float)
        else:
            alloc = (weights / weight_sum) * minutes
        sim_min.loc[idx] = alloc.astype(float)
        mapped_players += int(len(idx))
        mapped_minutes_sum += float(alloc.sum())

    diag["mapped_players"] = int(mapped_players)
    diag["mapped_minutes"] = float(mapped_minutes_sum)
    leftover = float(total_target - mapped_minutes_sum)
    diag["leftover_minutes"] = float(leftover)
    if leftover > 1e-6:
        weights = base_w.astype(float).clip(lower=0.0)
        weight_sum = float(weights.sum())
        if (not np.isfinite(weight_sum)) or weight_sum <= 0:
            sim_min = sim_min + (float(leftover) / float(max(1, len(sim_min))))
        else:
            sim_min = sim_min + ((weights / weight_sum) * float(leftover))

    total_sim = float(sim_min.sum())
    if np.isfinite(total_target) and total_target > 0 and np.isfinite(total_sim) and total_sim > 0:
        sim_min = sim_min * (total_target / total_sim)

    mapped_frac = float(mapped_minutes_sum) / float(max(1e-6, total_target))
    sim_min, reg_diag = regularize_rotation_minutes(
        tmp,
        sim_min,
        date_str=str(date_str),
        team_tri=team_u,
        mapped_minutes_frac=mapped_frac,
    )
    caps = minutes_caps_from_team_df(tmp, base_minutes=sim_min)
    sim_min = cap_and_redistribute_minutes(sim_min, total_target=league.regulation_team_minutes, cap=caps, iters=12)

    lineup_pool: list[list[int]] = []
    lineup_w: list[float] = []
    try:
        if {"lineup_player_ids", "duration_sec"}.issubset(set(stints.columns)):
            s2 = stints.copy()
            s2["team"] = s2.get("team", "").astype(str).str.upper().str.strip()
            s2 = s2[s2["team"] == team_u].copy()
            s2["duration_sec"] = pd.to_numeric(s2["duration_sec"], errors="coerce").fillna(0.0).astype(float)
            for _, row in s2.iterrows():
                lineup = str(row.get("lineup_player_ids") or "").strip()
                if not lineup:
                    continue
                pids = [player_id.strip() for player_id in lineup.split(";") if player_id.strip()]
                if len(pids) < 5:
                    continue
                idxs: list[int] = []
                for pid in pids:
                    candidates = tmp.index[tmp["_espn_id"].astype(str) == str(pid)].tolist()
                    if candidates:
                        idxs.append(int(candidates[0]))
                deduped = list(dict.fromkeys(idxs))
                if len(deduped) == 5:
                    lineup_pool.append([int(value) for value in deduped])
                    lineup_w.append(float(row.get("duration_sec") or 0.0))
    except Exception:
        lineup_pool = []
        lineup_w = []

    diag["lineup_pool_n"] = int(len(lineup_pool))
    diag["expected_minutes_coverage"] = float(reg_diag.get("exp_cov", 0.0))
    diag["regularization_blend"] = float(reg_diag.get("blend", 0.0))
    diag["minutes_cap_mean"] = float(np.mean(caps.to_numpy(dtype=float))) if len(caps) else None
    diag["minutes_cap_max"] = float(np.max(caps.to_numpy(dtype=float))) if len(caps) else None
    try:
        mapped_ids = [pid for pid in sorted(set(espn_ids[have].tolist())) if float(id_to_min.get(str(pid), 0.0)) > 0.0]
        mapped_id_n = int(len(mapped_ids))
        frac = float(mapped_minutes_sum) / float(max(1e-6, total_target))
        diag["mapped_id_n"] = mapped_id_n
        diag["mapped_minutes_frac"] = frac
        if mapped_id_n < 5 or frac < 0.50 or int(len(lineup_pool)) < 5:
            diag["applied"] = False
            diag["reason"] = "rotation_mapping_too_sparse"
            return None, None, None, diag
    except Exception:
        diag["applied"] = False
        diag["reason"] = str(diag.get("reason") or "rotation_mapping_guard_failed")
        return None, None, None, diag

    diag["applied"] = True
    diag["sim_minutes_sum"] = float(sim_min.sum())
    lineup_weights = np.asarray(lineup_w, dtype=float) if lineup_w else None
    return sim_min.astype(float), (lineup_pool if lineup_pool else None), lineup_weights, diag


def _player_split_rate_context_local(*, smart_sim_module, date_str: str, team_tri: str, lookback_days: int = 120):
    import numpy as np
    import pandas as pd

    load_player_logs_processed = getattr(smart_sim_module, "_load_player_logs_processed")
    norm_player_key = getattr(smart_sim_module, "_norm_player_key", _norm_name_key)
    parse_min_to_float = getattr(smart_sim_module, "_parse_min_to_float")
    matchup_opponent = getattr(smart_sim_module, "_matchup_opponent")
    matchup_home_flag = getattr(smart_sim_module, "_matchup_home_flag")

    logs = load_player_logs_processed()
    if logs is None or getattr(logs, "empty", True):
        return pd.DataFrame()

    end = pd.to_datetime(str(date_str or ""), errors="coerce")
    if pd.isna(end):
        return pd.DataFrame()

    team_u = str(team_tri or "").strip().upper()
    if not team_u:
        return pd.DataFrame()

    name_col = "PLAYER_NAME" if "PLAYER_NAME" in logs.columns else ("player_name" if "player_name" in logs.columns else None)
    team_col = "TEAM_ABBREVIATION" if "TEAM_ABBREVIATION" in logs.columns else ("team" if "team" in logs.columns else None)
    date_col = "GAME_DATE" if "GAME_DATE" in logs.columns else None
    min_col = "MIN" if "MIN" in logs.columns else ("min" if "min" in logs.columns else None)
    if not name_col or not team_col or not date_col or not min_col:
        return pd.DataFrame()

    stat_cols = {
        "pts": "PTS",
        "reb": "REB",
        "ast": "AST",
        "threes": "FG3M",
        "stl": "STL",
        "blk": "BLK",
        "tov": "TOV",
    }

    keep_cols = [name_col, team_col, date_col, min_col]
    if "MATCHUP" in logs.columns:
        keep_cols.append("MATCHUP")
    for col in stat_cols.values():
        if col in logs.columns:
            keep_cols.append(col)

    ctx = logs[keep_cols].copy()
    ctx[team_col] = ctx[team_col].astype(str).str.upper().str.strip()
    ctx = ctx[ctx[team_col] == team_u].copy()
    if ctx.empty:
        return pd.DataFrame()

    ctx[date_col] = pd.to_datetime(ctx[date_col], errors="coerce")
    start = end - pd.Timedelta(days=int(max(14, lookback_days)))
    ctx = ctx[(ctx[date_col].notna()) & (ctx[date_col] >= start) & (ctx[date_col] < end)].copy()
    if ctx.empty:
        return pd.DataFrame()

    ctx["_pkey"] = ctx[name_col].map(norm_player_key)
    ctx["_min"] = ctx[min_col].map(parse_min_to_float)
    ctx = ctx[np.isfinite(ctx["_min"]) & (ctx["_min"] > 0.0)].copy()
    if ctx.empty:
        return pd.DataFrame()

    if "MATCHUP" in ctx.columns:
        ctx["_opp"] = ctx["MATCHUP"].map(matchup_opponent)
        ctx["_home"] = ctx["MATCHUP"].map(matchup_home_flag)
    else:
        ctx["_opp"] = ""
        ctx["_home"] = None

    for stat, col in stat_cols.items():
        if col in ctx.columns:
            vals = pd.to_numeric(ctx[col], errors="coerce").fillna(0.0).astype(float)
        else:
            vals = pd.Series([0.0] * len(ctx), index=ctx.index, dtype=float)
        ctx[f"_{stat}_pm"] = vals / ctx["_min"].where(ctx["_min"] > 0.0, other=np.nan)
        ctx[f"_{stat}_pm"] = ctx[f"_{stat}_pm"].replace([np.inf, -np.inf], np.nan)

    keep_out = ["_pkey", "_opp", "_home", "_min"] + [f"_{stat}_pm" for stat in stat_cols]
    return ctx[keep_out].copy()


def _player_career_opponent_rate_context_local(*, smart_sim_module, date_str: str, lookback_days: int = 720):
    import numpy as np
    import pandas as pd

    load_player_logs_processed = getattr(smart_sim_module, "_load_player_logs_processed")
    norm_player_key = getattr(smart_sim_module, "_norm_player_key", _norm_name_key)
    parse_min_to_float = getattr(smart_sim_module, "_parse_min_to_float")
    matchup_opponent = getattr(smart_sim_module, "_matchup_opponent")

    logs = load_player_logs_processed()
    if logs is None or getattr(logs, "empty", True):
        return pd.DataFrame()

    end = pd.to_datetime(str(date_str or ""), errors="coerce")
    if pd.isna(end):
        return pd.DataFrame()

    name_col = "PLAYER_NAME" if "PLAYER_NAME" in logs.columns else ("player_name" if "player_name" in logs.columns else None)
    date_col = "GAME_DATE" if "GAME_DATE" in logs.columns else None
    min_col = "MIN" if "MIN" in logs.columns else ("min" if "min" in logs.columns else None)
    if not name_col or not date_col or not min_col:
        return pd.DataFrame()

    stat_cols = {
        "pts": "PTS",
        "reb": "REB",
        "ast": "AST",
        "threes": "FG3M",
        "stl": "STL",
        "blk": "BLK",
        "tov": "TOV",
    }

    keep_cols = [name_col, date_col, min_col]
    if "MATCHUP" in logs.columns:
        keep_cols.append("MATCHUP")
    for col in stat_cols.values():
        if col in logs.columns:
            keep_cols.append(col)

    ctx = logs[keep_cols].copy()
    ctx[date_col] = pd.to_datetime(ctx[date_col], errors="coerce")
    start = end - pd.Timedelta(days=int(max(120, lookback_days)))
    ctx = ctx[(ctx[date_col].notna()) & (ctx[date_col] >= start) & (ctx[date_col] < end)].copy()
    if ctx.empty:
        return pd.DataFrame()

    ctx["_pkey"] = ctx[name_col].map(norm_player_key)
    ctx["_min"] = ctx[min_col].map(parse_min_to_float)
    ctx = ctx[np.isfinite(ctx["_min"]) & (ctx["_min"] > 0.0)].copy()
    if ctx.empty:
        return pd.DataFrame()

    if "MATCHUP" in ctx.columns:
        ctx["_opp"] = ctx["MATCHUP"].map(matchup_opponent)
    else:
        ctx["_opp"] = ""
    ctx["_opp"] = ctx["_opp"].astype(str).str.upper().str.strip()
    ctx = ctx[ctx["_opp"].ne("")].copy()
    if ctx.empty:
        return pd.DataFrame()

    for stat, col in stat_cols.items():
        if col in ctx.columns:
            vals = pd.to_numeric(ctx[col], errors="coerce").fillna(0.0).astype(float)
        else:
            vals = pd.Series([0.0] * len(ctx), index=ctx.index, dtype=float)
        ctx[f"_{stat}_pm"] = vals / ctx["_min"].where(ctx["_min"] > 0.0, other=np.nan)
        ctx[f"_{stat}_pm"] = ctx[f"_{stat}_pm"].replace([np.inf, -np.inf], np.nan)

    keep_out = ["_pkey", "_opp", "_min"] + [f"_{stat}_pm" for stat in stat_cols]
    return ctx[keep_out].copy()


def _opponent_position_rate_context_local(*, smart_sim_module, date_str: str, lookback_days: int = 120):
    import numpy as np
    import pandas as pd

    load_boxscores_history_processed = getattr(smart_sim_module, "_load_boxscores_history_processed")
    opponent_position_rate_context_from_player_logs = getattr(smart_sim_module, "_opponent_position_rate_context_from_player_logs")
    norm_player_key = getattr(smart_sim_module, "_norm_player_key", _norm_name_key)
    parse_min_to_float = getattr(smart_sim_module, "_parse_min_to_float")
    normalize_position = getattr(smart_sim_module, "_normalize_position")
    season_roster_positions = getattr(smart_sim_module, "_season_roster_positions")

    box = load_boxscores_history_processed()
    if box is None or getattr(box, "empty", True):
        return opponent_position_rate_context_from_player_logs(str(date_str or ""), lookback_days=lookback_days)

    end = pd.to_datetime(str(date_str or ""), errors="coerce")
    if pd.isna(end):
        return pd.DataFrame()

    cols = {str(column).upper(): column for column in box.columns}
    gid_col = cols.get("GAME_ID") or cols.get("GAMEID")
    team_col = cols.get("TEAM_ABBREVIATION") or cols.get("TEAM")
    name_col = cols.get("PLAYER_NAME") or cols.get("PLAYER")
    date_col = cols.get("DATE") or cols.get("GAME_DATE")
    min_col = cols.get("MIN")
    pos_col = cols.get("START_POSITION") or cols.get("POSITION")
    pid_col = cols.get("PLAYER_ID")
    if not gid_col or not team_col or not name_col or not date_col or not min_col:
        return opponent_position_rate_context_from_player_logs(str(date_str or ""), lookback_days=lookback_days)

    stat_cols = {
        "pts": cols.get("PTS"),
        "reb": cols.get("REB"),
        "ast": cols.get("AST"),
        "threes": cols.get("FG3M"),
        "stl": cols.get("STL"),
        "blk": cols.get("BLK"),
        "tov": cols.get("TOV"),
    }

    keep_cols = [column for column in [gid_col, team_col, name_col, date_col, min_col, pos_col, pid_col] if column]
    keep_cols.extend([column for column in stat_cols.values() if column])
    ctx = box[keep_cols].copy()
    ctx[date_col] = pd.to_datetime(ctx[date_col], errors="coerce")
    start = end - pd.Timedelta(days=int(max(21, lookback_days)))
    ctx = ctx[(ctx[date_col].notna()) & (ctx[date_col] >= start) & (ctx[date_col] < end)].copy()
    if ctx.empty:
        return opponent_position_rate_context_from_player_logs(str(date_str or ""), lookback_days=lookback_days)

    ctx[team_col] = ctx[team_col].astype(str).str.upper().str.strip()
    ctx[gid_col] = pd.to_numeric(ctx[gid_col], errors="coerce")
    ctx["_pkey"] = ctx[name_col].map(norm_player_key)
    ctx["_min"] = ctx[min_col].map(parse_min_to_float)
    ctx = ctx[np.isfinite(ctx["_min"]) & (ctx["_min"] > 0.0) & ctx[gid_col].notna()].copy()
    if ctx.empty:
        return opponent_position_rate_context_from_player_logs(str(date_str or ""), lookback_days=lookback_days)

    if pos_col:
        ctx["_pos"] = ctx[pos_col].map(normalize_position)
    else:
        ctx["_pos"] = ""

    roster_pos = season_roster_positions(date_str)
    if roster_pos is not None and not getattr(roster_pos, "empty", True):
        pid_lookup: dict[int, str] = {}
        try:
            for _, row in roster_pos.dropna(subset=["player_id"]).iterrows():
                pid_lookup[int(float(row["player_id"]))] = str(row.get("position") or "")
        except Exception:
            pid_lookup = {}
        team_key_lookup = {
            (str(row.get("team") or "").strip().upper(), str(row.get("_pkey") or "").strip().upper()): str(row.get("position") or "")
            for _, row in roster_pos.iterrows()
            if str(row.get("position") or "").strip()
        }

        missing = ctx["_pos"].eq("")
        if missing.any() and pid_col and pid_col in ctx.columns and pid_lookup:
            pid_vals = pd.to_numeric(ctx.loc[missing, pid_col], errors="coerce")
            mapped = pid_vals.map(lambda value: pid_lookup.get(int(float(value)), "") if pd.notna(value) else "")
            ctx.loc[missing, "_pos"] = mapped.fillna("")

        missing = ctx["_pos"].eq("")
        if missing.any() and team_key_lookup:
            ctx.loc[missing, "_pos"] = [
                team_key_lookup.get((str(team).strip().upper(), str(pkey).strip().upper()), "")
                for team, pkey in zip(ctx.loc[missing, team_col], ctx.loc[missing, "_pkey"])
            ]

    ctx = ctx[ctx["_pos"].isin({"G", "F", "C"})].copy()
    if ctx.empty:
        return opponent_position_rate_context_from_player_logs(str(date_str or ""), lookback_days=lookback_days)

    matchup = ctx[[gid_col, team_col]].drop_duplicates().copy()
    opp_map = matchup.merge(matchup, on=gid_col, suffixes=("_team", "_opp"))
    opp_map = opp_map[opp_map[f"{team_col}_team"] != opp_map[f"{team_col}_opp"]].copy()
    opp_map = opp_map.drop_duplicates(subset=[gid_col, f"{team_col}_team"], keep="last")
    opp_map = opp_map.rename(columns={f"{team_col}_team": team_col, f"{team_col}_opp": "_opp"})[[gid_col, team_col, "_opp"]]
    ctx = ctx.merge(opp_map, on=[gid_col, team_col], how="left")
    ctx["_opp"] = ctx["_opp"].astype(str).str.upper().str.strip()
    ctx = ctx[ctx["_opp"].str.len().between(2, 4)].copy()
    if ctx.empty:
        return opponent_position_rate_context_from_player_logs(str(date_str or ""), lookback_days=lookback_days)

    for stat, column in stat_cols.items():
        if column:
            values = pd.to_numeric(ctx[column], errors="coerce").astype(float)
        else:
            values = pd.Series([np.nan] * len(ctx), index=ctx.index, dtype=float)
        ctx[f"_{stat}_pm"] = values / ctx["_min"].where(ctx["_min"] > 0.0, other=np.nan)
        ctx[f"_{stat}_pm"] = ctx[f"_{stat}_pm"].replace([np.inf, -np.inf], np.nan)

    grouped = ctx.groupby(["_opp", "_pos"], dropna=False)
    agg_dict: dict[str, Any] = {"_min": "count"}
    for stat in stat_cols:
        agg_dict[f"_{stat}_pm"] = "mean"
    out = grouped.agg(agg_dict).reset_index().rename(columns={"_min": "_n"})
    if out is None or out.empty:
        return opponent_position_rate_context_from_player_logs(str(date_str or ""), lookback_days=lookback_days)
    return out


def _event_safe_series_local(df, col: str):
    import pandas as pd

    if df is None or getattr(df, "empty", True) or col not in getattr(df, "columns", []):
        return pd.Series([0.0] * (0 if df is None else len(df)), dtype=float)
    return pd.to_numeric(df[col], errors="coerce").fillna(0.0)


def _player_usage_weights_local(*, players, col_pm: str, lineup_idx):
    import numpy as np

    n = int(len(players))
    if n <= 0:
        return np.zeros(0, dtype=float)

    pm = _event_safe_series_local(players, col_pm).to_numpy(dtype=float)
    pm = np.maximum(0.0, np.where(np.isfinite(pm), pm, 0.0))
    pm = np.log1p(pm)

    mins = _event_safe_series_local(players, "_sim_min").to_numpy(dtype=float)
    mins = np.maximum(0.0, np.where(np.isfinite(mins), mins, 0.0))

    weights = np.zeros(n, dtype=float)
    idx = [int(i) for i in (lineup_idx or []) if 0 <= int(i) < n]
    if not idx:
        return weights

    pm_line = pm[idx]
    mins_line = mins[idx]

    mins_floor = np.maximum(1.0, mins_line)
    mins_sum = float(mins_floor.sum())
    if np.isfinite(mins_sum) and mins_sum > 0:
        mins_norm = mins_floor / mins_sum
    else:
        mins_norm = np.full(len(idx), 1.0 / len(idx))

    pm_sum = float(pm_line.sum())

    pred_weight = 0.0
    pred_norm = None
    if col_pm in ("_prior_fga_pm", "_prior_threes_att_pm"):
        try:
            pred = _event_safe_series_local(players, "pred_pts").to_numpy(dtype=float)
            pred = np.maximum(0.0, np.where(np.isfinite(pred), pred, 0.0))
            pred = np.log1p(pred)
            pred_line = pred[idx]
            pred_sum = float(pred_line.sum())
            if np.isfinite(pred_sum) and pred_sum > 0:
                pred_norm = pred_line / pred_sum
                pred_weight = 0.20
        except Exception:
            pred_weight = 0.0
            pred_norm = None

    if (not np.isfinite(pm_sum)) or pm_sum <= 0:
        probs = mins_norm
        if pred_norm is not None and pred_weight > 0:
            probs = pred_weight * pred_norm + (1.0 - pred_weight) * mins_norm
    else:
        pm_norm = pm_line / pm_sum
        pri_weight = 0.75
        base = pri_weight * pm_norm + (1.0 - pri_weight) * mins_norm
        if pred_norm is not None and pred_weight > 0:
            probs = (1.0 - pred_weight) * base + pred_weight * pred_norm
        else:
            probs = base

    probs = np.maximum(0.0, probs)
    total = float(probs.sum())
    if not np.isfinite(total) or total <= 0:
        probs = np.full(len(idx), 1.0 / len(idx))
    else:
        probs = probs / total

    for j, i in enumerate(idx):
        weights[int(i)] = float(probs[j])
    return weights


def _local_event_boxscore_team_players(*, players_df) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if players_df is None or getattr(players_df, "empty", True):
        return rows
    for _, row in players_df.iterrows():
        name = str(row.get("player_name") or "").strip()
        if not name:
            continue
        pts = _first_present_float_local(row, "pred_pts", "mean_pts", "pts_mean", default=0.0)
        reb = _first_present_float_local(row, "pred_reb", "mean_reb", "reb_mean", default=0.0)
        ast = _first_present_float_local(row, "pred_ast", "mean_ast", "ast_mean", default=0.0)
        threes = _first_present_float_local(row, "pred_threes", "mean_threes", "threes_mean", default=0.0)
        stl = _first_present_float_local(row, "pred_stl", "mean_stl", "stl_mean", default=0.0)
        blk = _first_present_float_local(row, "pred_blk", "mean_blk", "blk_mean", default=0.0)
        tov = _first_present_float_local(row, "pred_tov", "mean_tov", "tov_mean", default=0.0)
        rows.append(
            {
                "player_name": name,
                "player_id": row.get("player_id"),
                "pts": int(round(max(0.0, pts))),
                "reb": int(round(max(0.0, reb))),
                "ast": int(round(max(0.0, ast))),
                "threes": int(round(max(0.0, threes))),
                "stl": int(round(max(0.0, stl))),
                "blk": int(round(max(0.0, blk))),
                "tov": int(round(max(0.0, tov))),
                "q_pts": [0, 0, 0, 0],
                "q_reb": [0, 0, 0, 0],
                "q_ast": [0, 0, 0, 0],
                "q_threes": [0, 0, 0, 0],
            }
        )
    return rows


def _local_simulate_pbp_game_boxscore(*, rng=None, home_players=None, away_players=None, cfg=None, home_lineups=None, home_lineup_weights=None, away_lineups=None, away_lineup_weights=None, target_home_points=None, target_away_points=None, quarters=None, home_team_adj=None, away_team_adj=None, **_extra_kwargs):
    hq = [int(round(max(0.0, float(getattr(q, "home_pts_mu", 0.0) or 0.0)))) for q in (quarters or [])[:4]]
    aq = [int(round(max(0.0, float(getattr(q, "away_pts_mu", 0.0) or 0.0)))) for q in (quarters or [])[:4]]
    while len(hq) < 4:
        hq.append(0)
    while len(aq) < 4:
        aq.append(0)
    h_players = _local_event_boxscore_team_players(players_df=home_players)
    a_players = _local_event_boxscore_team_players(players_df=away_players)
    h_box = {"players": h_players, "team_total_pts": int(sum(hq)), "q_segment_pts": [[0, 0, 0, 0] for _ in range(4)], "q_minute_pts": [[0] * 12 for _ in range(4)], "segment_seconds": 180, "minute_seconds": 60, "ot_pts": [], "ot_seconds": 300}
    a_box = {"players": a_players, "team_total_pts": int(sum(aq)), "q_segment_pts": [[0, 0, 0, 0] for _ in range(4)], "q_minute_pts": [[0] * 12 for _ in range(4)], "segment_seconds": 180, "minute_seconds": 60, "ot_pts": [], "ot_seconds": 300}
    return h_box, a_box, hq, aq


def _local_simulate_event_level_boxscore(*, rng=None, home_players=None, away_players=None, home_q_pts=None, away_q_pts=None, cfg=None, home_lineups=None, home_lineup_weights=None, away_lineups=None, away_lineup_weights=None, home_team_adj=None, away_team_adj=None, **_extra_kwargs):
    hq = [int(x) for x in list(home_q_pts or [0, 0, 0, 0])[:4]]
    aq = [int(x) for x in list(away_q_pts or [0, 0, 0, 0])[:4]]
    h_players = _local_event_boxscore_team_players(players_df=home_players)
    a_players = _local_event_boxscore_team_players(players_df=away_players)
    return {"players": h_players, "team_total_pts": int(sum(hq))}, {"players": a_players, "team_total_pts": int(sum(aq))}


_LOCAL_EVENTS_MODULE = SimpleNamespace(
    EventSimConfig=EventSimConfigLocal,
    _player_usage_weights=lambda players, col_pm, lineup_idx: _player_usage_weights_local(players=players, col_pm=col_pm, lineup_idx=lineup_idx),
    simulate_pbp_game_boxscore=_local_simulate_pbp_game_boxscore,
    simulate_event_level_boxscore=_local_simulate_event_level_boxscore,
)


def _call_events_entrypoint_local(*, entrypoint_name: str, kwargs: dict[str, Any]):
    events_module = _LOCAL_EVENTS_MODULE
    sentinel = object()
    original_value = getattr(events_module, "_player_usage_weights", sentinel)
    try:
        setattr(
            events_module,
            "_player_usage_weights",
            lambda players, col_pm, lineup_idx: _player_usage_weights_local(
                players=players,
                col_pm=col_pm,
                lineup_idx=lineup_idx,
            ),
        )
        entrypoint = getattr(events_module, entrypoint_name)
        return entrypoint(**kwargs)
    finally:
        if original_value is sentinel:
            delattr(events_module, "_player_usage_weights")
        else:
            setattr(events_module, "_player_usage_weights", original_value)


def _simulate_pbp_game_boxscore_local(**kwargs):
    return _call_events_entrypoint_local(entrypoint_name="simulate_pbp_game_boxscore", kwargs=kwargs)


def _simulate_event_level_boxscore_local(**kwargs):
    return _call_events_entrypoint_local(entrypoint_name="simulate_event_level_boxscore", kwargs=kwargs)


def _apply_player_priors_local(*, smart_sim_module, team_df, priors, team_tri: str, sim_minutes=None, date_str: str | None = None):
    import numpy as np
    import pandas as pd

    frame_series = getattr(smart_sim_module, "_frame_series")
    frame_numeric_series = getattr(smart_sim_module, "_frame_numeric_series")
    derive_sim_minutes = getattr(smart_sim_module, "_derive_sim_minutes")
    weighted_positive_mean = getattr(smart_sim_module, "_weighted_positive_mean")
    bounded_split_multiplier = getattr(smart_sim_module, "_bounded_split_multiplier")
    normalize_position = getattr(smart_sim_module, "_normalize_position")
    boolish_series = getattr(smart_sim_module, "_boolish_series")
    safe_float = getattr(smart_sim_module, "_safe_float")

    if team_df is None or getattr(team_df, "empty", True):
        return pd.DataFrame()

    out = team_df.copy()
    out["_pkey"] = frame_series(out, "player_name", "").map(_norm_name_key)

    if sim_minutes is not None and len(sim_minutes) == len(out):
        out["_sim_min"] = pd.to_numeric(sim_minutes, errors="coerce").fillna(0.0).astype(float)
    else:
        out["_sim_min"] = derive_sim_minutes(out, date_str=date_str, team_tri=team_tri)

    pred_cols = {
        "pts": "pred_pts",
        "reb": "pred_reb",
        "ast": "pred_ast",
        "threes": "pred_threes",
        "stl": "pred_stl",
        "blk": "pred_blk",
        "tov": "pred_tov",
    }
    sim_min_local = pd.to_numeric(out["_sim_min"], errors="coerce").fillna(0.0).astype(float)
    sim_min_safe = sim_min_local.where(sim_min_local > 0.0, other=1.0)

    for stat, column in pred_cols.items():
        if column in out.columns:
            per_min = pd.to_numeric(out[column], errors="coerce").fillna(0.0).astype(float) / sim_min_safe
            out[f"_pred_{stat}_pm"] = per_min.clip(lower=0.0)
        else:
            out[f"_pred_{stat}_pm"] = 0.0

    def _rate_row(row: pd.Series) -> dict[str, float]:
        try:
            team_u = str(team_tri or "").strip().upper()
            key = str(row.get("_pkey") or "").strip().upper()
            return priors.rates.get((team_u, key), {})
        except Exception:
            return {}

    pri_map = out.apply(_rate_row, axis=1)

    def _get_rate(index: int, key: str) -> float:
        try:
            rates = pri_map.iloc[int(index)]
            return safe_float(rates.get(key), 0.0)
        except Exception:
            return 0.0

    stat_pm_keys = [
        ("pts", "pts_pm"),
        ("reb", "reb_pm"),
        ("ast", "ast_pm"),
        ("stl", "stl_pm"),
        ("blk", "blk_pm"),
        ("tov", "tov_pm"),
        ("threes", "threes_pm"),
        ("threes_att", "threes_att_pm"),
        ("fga", "fga_pm"),
        ("fgm", "fgm_pm"),
        ("fta", "fta_pm"),
        ("ftm", "ftm_pm"),
        ("pf", "pf_pm"),
    ]
    for out_name, pri_key in stat_pm_keys:
        out[f"_prior_{out_name}_pm"] = [float(_get_rate(index, pri_key)) for index in range(len(out))]

    for stat in ("pts", "reb", "ast", "threes", "stl", "blk", "tov"):
        col = f"_prior_{stat}_pm"
        pred_col = f"_pred_{stat}_pm"
        if col in out.columns and pred_col in out.columns:
            out[col] = np.where(out[col] > 0.0, out[col], out[pred_col])

    roll10_min = frame_numeric_series(out, "roll10_min")
    roll5_min = frame_numeric_series(out, "roll5_min")
    split_ctx = _player_split_rate_context_local(
        smart_sim_module=smart_sim_module,
        date_str=str(date_str or ""),
        team_tri=str(team_tri or ""),
    ) if date_str else pd.DataFrame()
    career_opp_ctx = _player_career_opponent_rate_context_local(
        smart_sim_module=smart_sim_module,
        date_str=str(date_str or ""),
    ) if date_str else pd.DataFrame()
    pos_ctx = _opponent_position_rate_context_local(
        smart_sim_module=smart_sim_module,
        date_str=str(date_str or ""),
    ) if date_str else pd.DataFrame()
    split_by_player: dict[str, pd.DataFrame] = {}
    if split_ctx is not None and not split_ctx.empty and "_pkey" in split_ctx.columns:
        for player_key, group in split_ctx.groupby("_pkey"):
            split_by_player[str(player_key)] = group.copy()
    career_opp_by_player: dict[str, pd.DataFrame] = {}
    if career_opp_ctx is not None and not career_opp_ctx.empty and "_pkey" in career_opp_ctx.columns:
        for player_key, group in career_opp_ctx.groupby("_pkey"):
            career_opp_by_player[str(player_key)] = group.copy()
    pos_lookup: dict[tuple[str, str], dict[str, float]] = {}
    if pos_ctx is not None and not pos_ctx.empty:
        for _, row in pos_ctx.iterrows():
            opp_key = str(row.get("_opp") or "").strip().upper()
            pos_key = normalize_position(row.get("_pos"))
            if opp_key and pos_key:
                pos_lookup[(opp_key, pos_key)] = {
                    "n": safe_float(row.get("_n"), 0.0),
                    **{stat: safe_float(row.get(f"_{stat}_pm"), float("nan")) for stat in ("pts", "reb", "ast", "threes", "stl", "blk", "tov")},
                }

    opp_series = out.get("opponent") if "opponent" in out.columns else pd.Series(["" for _ in range(len(out))], index=out.index, dtype=object)
    opp_series = opp_series.astype(str).str.upper().str.strip()
    home_series = boolish_series(out.get("home") if "home" in out.columns else [False] * len(out), out.index)
    pos_series = out.get("position") if "position" in out.columns else pd.Series(["" for _ in range(len(out))], index=out.index, dtype=object)
    pos_series = pos_series.map(normalize_position)

    stat_roll_cols = {
        "pts": ("roll5_pts", "roll10_pts"),
        "reb": ("roll5_reb", "roll10_reb"),
        "ast": ("roll5_ast", "roll10_ast"),
        "threes": ("roll5_threes", "roll10_threes"),
    }
    stat_bounds = {
        "pts": (0.84, 1.18),
        "reb": (0.86, 1.16),
        "ast": (0.84, 1.18),
        "threes": (0.80, 1.22),
        "stl": (0.78, 1.24),
        "blk": (0.78, 1.24),
        "tov": (0.82, 1.20),
    }
    for stat in ("pts", "reb", "ast", "threes", "stl", "blk", "tov"):
        prior_col = f"_prior_{stat}_pm"
        pred_col = f"_pred_{stat}_pm"
        prior_pm = pd.to_numeric(out.get(prior_col), errors="coerce").fillna(0.0).astype(float)
        pred_pm = pd.to_numeric(out.get(pred_col), errors="coerce").fillna(0.0).astype(float)
        updated = prior_pm.copy()
        roll_cols = stat_roll_cols.get(stat)
        if roll_cols is not None:
            roll5_total = pd.to_numeric(out.get(roll_cols[0]), errors="coerce").astype(float) if roll_cols[0] in out.columns else pd.Series([np.nan] * len(out), index=out.index, dtype=float)
            roll10_total = pd.to_numeric(out.get(roll_cols[1]), errors="coerce").astype(float) if roll_cols[1] in out.columns else pd.Series([np.nan] * len(out), index=out.index, dtype=float)
            roll5_pm = (roll5_total / roll5_min.where(roll5_min > 0.0, other=np.nan)).replace([np.inf, -np.inf], np.nan)
            roll10_pm = (roll10_total / roll10_min.where(roll10_min > 0.0, other=np.nan)).replace([np.inf, -np.inf], np.nan)
        else:
            roll5_pm = pd.Series([np.nan] * len(out), index=out.index, dtype=float)
            roll10_pm = pd.Series([np.nan] * len(out), index=out.index, dtype=float)

        lo, hi = stat_bounds[stat]
        for idx in out.index:
            base_rate = float(prior_pm.loc[idx]) if np.isfinite(prior_pm.loc[idx]) else 0.0
            pred_rate = float(pred_pm.loc[idx]) if np.isfinite(pred_pm.loc[idx]) else 0.0
            recent_rate = weighted_positive_mean([(roll10_pm.loc[idx], 0.65), (roll5_pm.loc[idx], 0.35)])
            anchor = weighted_positive_mean([(base_rate, 0.50), (recent_rate, 0.35), (pred_rate, 0.15)])
            if anchor <= 0.0:
                anchor = weighted_positive_mean([(recent_rate, 0.75), (pred_rate, 0.25)])
            if anchor <= 0.0:
                continue

            player_key = str(out.at[idx, "_pkey"] or "").strip().upper()
            player_logs = split_by_player.get(player_key)
            player_career_opp_logs = career_opp_by_player.get(player_key)
            mult = 1.0
            if player_logs is not None and not player_logs.empty:
                opp_key = str(opp_series.loc[idx] or "").strip().upper()
                if opp_key:
                    opp_rows = player_logs[player_logs["_opp"] == opp_key]
                    if not opp_rows.empty:
                        opp_rate = pd.to_numeric(opp_rows.get(f"_{stat}_pm"), errors="coerce").dropna()
                        if not opp_rate.empty:
                            mult *= bounded_split_multiplier(anchor, float(opp_rate.mean()), int(len(opp_rows)), min_games=2, max_games=5, lo=lo, hi=hi)
                if opp_key and player_career_opp_logs is not None and not player_career_opp_logs.empty:
                    career_opp_rows = player_career_opp_logs[player_career_opp_logs["_opp"] == opp_key]
                    if not career_opp_rows.empty:
                        career_opp_rate = pd.to_numeric(career_opp_rows.get(f"_{stat}_pm"), errors="coerce").dropna()
                        if not career_opp_rate.empty:
                            mult *= bounded_split_multiplier(anchor, float(career_opp_rate.mean()), int(len(career_opp_rows)), min_games=3, max_games=12, lo=max(lo, 0.94), hi=min(hi, 1.06))
                venue_rows = player_logs[player_logs["_home"] == bool(home_series.loc[idx])]
                if not venue_rows.empty:
                    venue_rate = pd.to_numeric(venue_rows.get(f"_{stat}_pm"), errors="coerce").dropna()
                    if not venue_rate.empty:
                        mult *= bounded_split_multiplier(anchor, float(venue_rate.mean()), int(len(venue_rows)), min_games=5, max_games=12, lo=max(0.90, lo), hi=min(1.12, hi))
                pos_key = str(pos_series.loc[idx] or "").strip().upper()
                pos_row = pos_lookup.get((opp_key, pos_key)) if opp_key and pos_key else None
                if pos_row is not None:
                    pos_rate = safe_float(pos_row.get(stat), float("nan"))
                    pos_n = int(max(0.0, safe_float(pos_row.get("n"), 0.0)))
                    if np.isfinite(pos_rate) and pos_rate >= 0.0 and pos_n > 0:
                        mult *= bounded_split_multiplier(anchor, float(pos_rate), int(pos_n), min_games=12, max_games=80, lo=max(lo, 0.90 if stat in {"threes", "stl", "blk"} else 0.92), hi=min(hi, 1.10 if stat in {"threes", "stl", "blk"} else 1.08))
            updated.loc[idx] = float(anchor * np.clip(mult, lo, hi))
        out[prior_col] = updated.astype(float)

    try:
        pts_pm = frame_numeric_series(out, "_prior_pts_pm")
        if float(pts_pm.sum()) <= 0:
            out["_prior_pts_pm"] = np.where(sim_min_local > 0, 0.55, 0.0)
    except Exception:
        pass

    active = sim_min_local > 0.5
    pts_pm = frame_numeric_series(out, "_prior_pts_pm")
    threes_pm = frame_numeric_series(out, "_prior_threes_pm")
    try:
        p3 = 3.0 * threes_pm
        pft = 0.18 * pts_pm
        p2 = np.maximum(0.0, pts_pm - p3 - pft)
        fgm2_pm = p2 / 2.0
        fga2_pm = fgm2_pm / 0.50
        fg3a_fallback = (threes_pm / 0.35).clip(lower=0.0, upper=0.65)
        fga_fallback = (fga2_pm + fg3a_fallback).clip(lower=0.05, upper=0.85)
        fta_fallback = (pft / 0.76).clip(lower=0.0, upper=0.35)
    except Exception:
        fga_fallback = (pts_pm / 1.05).clip(lower=0.05, upper=0.85)
        fg3a_fallback = (threes_pm / 0.35).clip(lower=0.0, upper=0.65)
        fta_fallback = (0.18 * fga_fallback).clip(lower=0.0, upper=0.35)

    fga = frame_numeric_series(out, "_prior_fga_pm")
    out["_prior_fga_pm"] = np.where(active & (fga <= 0.0), fga_fallback, fga)
    fg3a = frame_numeric_series(out, "_prior_threes_att_pm")
    out["_prior_threes_att_pm"] = np.where(active & (fg3a <= 0.0), fg3a_fallback, fg3a)
    try:
        out["_prior_threes_att_pm"] = np.minimum(pd.to_numeric(out["_prior_threes_att_pm"], errors="coerce").fillna(0.0).astype(float), 0.9 * pd.to_numeric(out["_prior_fga_pm"], errors="coerce").fillna(0.0).astype(float))
    except Exception:
        pass
    fgm = frame_numeric_series(out, "_prior_fgm_pm")
    fga_now = frame_numeric_series(out, "_prior_fga_pm")
    out["_prior_fgm_pm"] = np.where(active & (fgm <= 0.0), 0.46 * fga_now, fgm)
    fg3m = frame_numeric_series(out, "_prior_threes_pm")
    fg3a_now = frame_numeric_series(out, "_prior_threes_att_pm")
    out["_prior_threes_pm"] = np.where(active & (fg3m <= 0.0), 0.35 * fg3a_now, fg3m)
    fta = frame_numeric_series(out, "_prior_fta_pm")
    out["_prior_fta_pm"] = np.where(active & (fta <= 0.0), fta_fallback, fta)
    ftm = frame_numeric_series(out, "_prior_ftm_pm")
    fta_now = frame_numeric_series(out, "_prior_fta_pm")
    out["_prior_ftm_pm"] = np.where(active & (ftm <= 0.0), 0.76 * fta_now, ftm)

    fga_final = frame_numeric_series(out, "_prior_fga_pm")
    if float((fga_final * sim_min_local).sum()) <= 0:
        out["_prior_fga_pm"] = np.where(sim_min_local > 0, 0.55, 0.0)
        fga_final = pd.to_numeric(out["_prior_fga_pm"], errors="coerce").fillna(0.0).astype(float)
    fg3a_final = frame_numeric_series(out, "_prior_threes_att_pm")
    if float((fg3a_final * sim_min_local).sum()) <= 0:
        out["_prior_threes_att_pm"] = 0.36 * fga_final
    fgm_final = frame_numeric_series(out, "_prior_fgm_pm")
    if float((fgm_final * sim_min_local).sum()) <= 0:
        out["_prior_fgm_pm"] = 0.46 * fga_final
    fg3m_final = frame_numeric_series(out, "_prior_threes_pm")
    if float((fg3m_final * sim_min_local).sum()) <= 0:
        out["_prior_threes_pm"] = 0.35 * pd.to_numeric(out["_prior_threes_att_pm"], errors="coerce").fillna(0.0).astype(float)
    fta_final = frame_numeric_series(out, "_prior_fta_pm")
    if float((fta_final * sim_min_local).sum()) <= 0:
        out["_prior_fta_pm"] = 0.18 * fga_final
    ftm_final = frame_numeric_series(out, "_prior_ftm_pm")
    if float((ftm_final * sim_min_local).sum()) <= 0:
        out["_prior_ftm_pm"] = 0.76 * pd.to_numeric(out["_prior_fta_pm"], errors="coerce").fillna(0.0).astype(float)
    pf = frame_numeric_series(out, "_prior_pf_pm")
    if float(pf.sum()) <= 0:
        out["_prior_pf_pm"] = 0.085
    return out
    try:
        eid = str(event_id or "").strip() or (espn_event_id_for_matchup(str(date_str), home_tri=str(home_tri), away_tri=str(away_tri)) or "")
        if not eid:
            return pd.DataFrame()
        summary = espn_summary(eid)
        box = (summary or {}).get("boxscore") or {}
        teams = box.get("players") or []
        if not isinstance(teams, list) or not teams:
            return pd.DataFrame()
        team = str(team_tri or "").strip().upper()
        opp = str(away_tri if team == str(home_tri).strip().upper() else home_tri).strip().upper()
        rows: list[dict[str, Any]] = []
        for team_payload in teams:
            team_meta = (team_payload or {}).get("team") or {}
            team_abbrev = str(team_meta.get("abbreviation") or "").strip().upper()
            tri = espn_to_tri(team_abbrev) if team_abbrev else ""
            if str(tri).upper().strip() != team:
                continue
            stats_groups = (team_payload or {}).get("statistics") or []
            if not isinstance(stats_groups, list) or not stats_groups:
                continue
            for group in stats_groups:
                athletes = (group or {}).get("athletes") or []
                if not isinstance(athletes, list):
                    continue
                for athlete_payload in athletes:
                    if not isinstance(athlete_payload, dict):
                        continue
                    athlete = athlete_payload.get("athlete") or {}
                    name = str(athlete.get("displayName") or athlete.get("shortName") or "").strip()
                    if not name:
                        continue
                    pos_raw = ((athlete.get("position") or {}).get("abbreviation")) or ((athlete.get("position") or {}).get("name")) or ""
                    rows.append({"player_name": name, "team": team, "opponent": opp, "position": _normalize_position_local(pos_raw), "playing_today": True})
        out = pd.DataFrame(rows)
        if out is None or out.empty:
            return pd.DataFrame()
        return out.drop_duplicates(subset=["player_name", "team"], keep="last")
    except Exception:
        return pd.DataFrame()


def _season_from_date_str_local(*, date_str: str) -> int:
    try:
        import pandas as pd

        ts = pd.to_datetime(str(date_str), errors="coerce")
        if ts is None or pd.isna(ts):
            raise ValueError("bad date")
        return int(ts.year + 1) if int(ts.month) >= 7 else int(ts.year)
    except Exception:
        try:
            return int(str(date_str)[:4])
        except Exception:
            return 0


def _norm_pct01_local(value: Any) -> float:
    try:
        import numpy as np

        numeric = float(value)
        if not np.isfinite(numeric):
            return float("nan")
        if numeric > 1.5:
            numeric = numeric / 100.0
        return float(numeric)
    except Exception:
        return float("nan")


def _load_team_advanced_stats_asof_local(*, processed_root: Path, season: int, as_of_date_str: str):
    import pandas as pd

    cache_key = (str(processed_root), int(season), str(as_of_date_str).strip())
    cached = _TEAM_ADVANCED_STATS_CACHE_LOCAL.get(cache_key)
    if cached is not None:
        return cached
    file_asof = processed_root / f"team_advanced_stats_{int(season)}_asof_{str(as_of_date_str).strip()}.csv"
    file_season = processed_root / f"team_advanced_stats_{int(season)}.csv"
    file_path = file_asof if file_asof.exists() else file_season
    if not file_path.exists():
        _TEAM_ADVANCED_STATS_CACHE_LOCAL[cache_key] = pd.DataFrame()
        return _TEAM_ADVANCED_STATS_CACHE_LOCAL[cache_key]
    try:
        import numpy as np

        df = pd.read_csv(file_path)
        if df is None or df.empty:
            df = pd.DataFrame()
            _TEAM_ADVANCED_STATS_CACHE_LOCAL[cache_key] = df
            return df
        df = df.copy()
        df.columns = [str(column).strip() for column in df.columns]
        team_col = "team" if "team" in df.columns else ("team_tri" if "team_tri" in df.columns else None)
        if team_col is None:
            df = pd.DataFrame()
            _TEAM_ADVANCED_STATS_CACHE_LOCAL[cache_key] = df
            return df
        df[team_col] = df[team_col].astype(str).str.upper().str.strip()
        if team_col != "team":
            df = df.rename(columns={team_col: "team"})
        for column in ["pace", "off_rtg", "def_rtg", "efg_pct", "tov_pct", "orb_pct", "ft_rate", "fg3a_rate", "fg3_pct", "ts_pct", "ast_per_100", "games"]:
            if column in df.columns:
                df[column] = pd.to_numeric(df[column], errors="coerce")
        for column in ["efg_pct", "tov_pct", "orb_pct", "fg3a_rate", "fg3_pct", "ts_pct"]:
            if column in df.columns:
                df[column] = df[column].map(_norm_pct01_local)
        if "ft_rate" in df.columns:
            df["ft_rate"] = df["ft_rate"].map(_norm_pct01_local)
        df = df.replace([np.inf, -np.inf], np.nan)
        df = df.dropna(subset=["team"]).reset_index(drop=True)
        _TEAM_ADVANCED_STATS_CACHE_LOCAL[cache_key] = df
        return df
    except Exception:
        df = pd.DataFrame()
        _TEAM_ADVANCED_STATS_CACHE_LOCAL[cache_key] = df
        return df


def _team_adv_row_local(df, team_tri: str) -> dict[str, float] | None:
    try:
        import numpy as np
    except Exception:
        np = None
    if df is None or getattr(df, "empty", True):
        return None
    team = str(team_tri or "").upper().strip()
    if not team or "team" not in getattr(df, "columns", []):
        return None
    match = df[df["team"].astype(str).str.upper().str.strip() == team]
    if match.empty:
        return None
    row = match.iloc[0].to_dict()
    out: dict[str, float] = {}
    for key in ["pace", "off_rtg", "def_rtg", "efg_pct", "tov_pct", "orb_pct", "ft_rate", "games"]:
        try:
            value = float(row.get(key))
            out[key] = float(value) if (np is None or np.isfinite(value)) else float("nan")
        except Exception:
            out[key] = float("nan")
    return out


def _league_means_local(df, *, league) -> dict[str, float]:
    if df is None or getattr(df, "empty", True):
        return {
            "pace": getattr(league, "baseline_pace"),
            "off_rtg": getattr(league, "baseline_off_rating"),
            "def_rtg": getattr(league, "baseline_def_rating"),
            "tov_pct": 0.135,
            "orb_pct": 0.240,
            "ft_rate": 0.220,
        }

    def _mean_col(column: str, default: float) -> float:
        try:
            import pandas as pd
            import numpy as np

            if column not in df.columns:
                return float(default)
            arr = pd.to_numeric(df[column], errors="coerce").to_numpy(dtype=float)
            mean_val = float(np.nanmean(arr))
            return float(mean_val) if np.isfinite(mean_val) else float(default)
        except Exception:
            return float(default)

    return {
        "pace": _mean_col("pace", getattr(league, "baseline_pace")),
        "off_rtg": _mean_col("off_rtg", getattr(league, "baseline_off_rating")),
        "def_rtg": _mean_col("def_rtg", getattr(league, "baseline_def_rating")),
        "tov_pct": _mean_col("tov_pct", 0.135),
        "orb_pct": _mean_col("orb_pct", 0.240),
        "ft_rate": _mean_col("ft_rate", 0.220),
    }


def _team_adj_from_advanced_stats_local(*, processed_root: Path, date_str: str, home_tri: str, away_tri: str, league) -> tuple[dict[str, float] | None, dict[str, float] | None, float, dict[str, Any]]:
    diag: dict[str, Any] = {"attempted": True, "applied": False, "source": None, "as_of": str(date_str)}
    try:
        import numpy as np

        season = _season_from_date_str_local(date_str=date_str)
        if season <= 0:
            diag["reason"] = "bad_season"
            return None, None, 1.0, diag
        df = _load_team_advanced_stats_asof_local(processed_root=processed_root, season=int(season), as_of_date_str=str(date_str))
        if df is None or df.empty:
            diag["reason"] = "missing_team_advanced_stats"
            return None, None, 1.0, diag
        try:
            diag["source"] = str(df["source"].iloc[0]) if "source" in df.columns and not df["source"].empty else "cache"
        except Exception:
            diag["source"] = "cache"
        home_row = _team_adv_row_local(df, home_tri)
        away_row = _team_adv_row_local(df, away_tri)
        league_means = _league_means_local(df, league=league)
        diag["league"] = league_means
        diag["home"] = home_row
        diag["away"] = away_row
        if not home_row or not away_row:
            diag["reason"] = "team_not_found"
            return None, None, 1.0, diag
        pace_vals = [float(home_row.get("pace", float("nan"))), float(away_row.get("pace", float("nan")))]
        pace_vals = [value for value in pace_vals if np.isfinite(value) and value > 0]
        league_pace = float(league_means.get("pace", getattr(league, "baseline_pace")))
        if pace_vals and np.isfinite(league_pace) and league_pace > 0:
            pace_match = float(np.mean(pace_vals))
            pace_mult = float(np.clip(pace_match / league_pace, 0.92, 1.08))
        else:
            pace_mult = 1.0
        league_off = float(league_means.get("off_rtg", getattr(league, "baseline_off_rating")))
        league_def = float(league_means.get("def_rtg", getattr(league, "baseline_def_rating")))

        def _ratio(value: float, base: float, lo: float, hi: float) -> float:
            try:
                value = float(value)
                base = float(base)
                if (not np.isfinite(value)) or (not np.isfinite(base)) or base <= 0:
                    return 1.0
                return float(np.clip(value / base, lo, hi))
            except Exception:
                return 1.0

        eff_h = _ratio(float(home_row.get("off_rtg", float("nan"))), league_off, 0.85, 1.15) * _ratio(float(away_row.get("def_rtg", float("nan"))), league_def, 0.90, 1.10)
        eff_a = _ratio(float(away_row.get("off_rtg", float("nan"))), league_off, 0.85, 1.15) * _ratio(float(home_row.get("def_rtg", float("nan"))), league_def, 0.90, 1.10)
        eff_h = float(np.clip(eff_h, 0.80, 1.20))
        eff_a = float(np.clip(eff_a, 0.80, 1.20))
        league_tov = float(league_means.get("tov_pct", 0.135))
        league_orb = float(league_means.get("orb_pct", 0.240))
        league_ft = float(league_means.get("ft_rate", 0.220))
        home_adj = {
            "eff_mult": eff_h,
            "tov_mult": _ratio(float(home_row.get("tov_pct", float("nan"))), league_tov, 0.85, 1.15),
            "foul_mult": _ratio(float(home_row.get("ft_rate", float("nan"))), league_ft, 0.80, 1.25),
            "oreb_mult": _ratio(float(home_row.get("orb_pct", float("nan"))), league_orb, 0.75, 1.35),
        }
        away_adj = {
            "eff_mult": eff_a,
            "tov_mult": _ratio(float(away_row.get("tov_pct", float("nan"))), league_tov, 0.85, 1.15),
            "foul_mult": _ratio(float(away_row.get("ft_rate", float("nan"))), league_ft, 0.80, 1.25),
            "oreb_mult": _ratio(float(away_row.get("orb_pct", float("nan"))), league_orb, 0.75, 1.35),
        }
        diag["applied"] = True
        diag["pace_mult"] = pace_mult
        diag["home_adj"] = home_adj
        diag["away_adj"] = away_adj
        return home_adj, away_adj, pace_mult, diag
    except Exception as exc:
        diag["reason"] = str(exc)
        return None, None, 1.0, diag


def _compute_player_priors_cached_local(*, processed_root: Path, asof_date_str: str, days_back: int):
    from . import basketball_props_onnx

    cfg = basketball_props_onnx.PlayerPriorsConfig(days_back=int(days_back))
    return basketball_props_onnx.compute_player_priors_local(
        processed_root=processed_root,
        date_str=str(asof_date_str),
        cfg=cfg,
    )


def _load_smartsim_total_calibration_local(*, processed_root: Path) -> dict[str, Any]:
    file_path = processed_root / "smart_sim_total_calibration.json"
    if not file_path.exists():
        return {}
    try:
        obj = json.loads(file_path.read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _load_intervals_band_calibration_local(*, processed_root: Path) -> dict[str, Any] | None:
    file_path = processed_root / "intervals_band_calibration.json"
    if not file_path.exists():
        return None
    try:
        obj = json.loads(file_path.read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def _load_intervals_time_profile_local(*, processed_root: Path) -> dict[str, Any] | None:
    file_path = processed_root / "intervals_time_profile.json"
    if not file_path.exists():
        return None
    try:
        obj = json.loads(file_path.read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def _load_player_stat_calibration_local(*, processed_root: Path) -> dict[str, Any] | None:
    file_path = processed_root / "player_stat_calibration.json"
    if not file_path.exists():
        return None
    try:
        obj = json.loads(file_path.read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def _team_players_from_props_local(*, props_df, team_tri: str, opp_tri: str, processed_root: Path | None = None, date_str: str | None = None):
    import pandas as pd

    df = props_df.copy() if isinstance(props_df, pd.DataFrame) else pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    if "player_name" not in df.columns:
        return pd.DataFrame()
    if "team" in df.columns:
        df["team"] = df["team"].astype(str).str.upper().str.strip()
    if "opponent" in df.columns:
        df["opponent"] = df["opponent"].astype(str).str.upper().str.strip()
    team_u = str(team_tri or "").upper().strip()
    opp_u = str(opp_tri or "").upper().strip()
    out = pd.DataFrame()
    team_only = pd.DataFrame()
    if "team" in df.columns:
        team_only = df[df["team"] == team_u].copy()
    if ("team" in df.columns) and ("opponent" in df.columns):
        out = df[(df["team"] == team_u) & (df["opponent"] == opp_u)].copy()
    elif {"home_team", "away_team"}.issubset(set(df.columns)):
        tmp = df.copy()
        tmp["home_tri"] = tmp["home_team"].astype(str).map(lambda value: str(_to_tricode_local(value) or str(value or "").strip().upper()).strip().upper())
        tmp["away_tri"] = tmp["away_team"].astype(str).map(lambda value: str(_to_tricode_local(value) or str(value or "").strip().upper()).strip().upper())
        matchup_mask = ((tmp["home_tri"] == team_u) & (tmp["away_tri"] == opp_u)) | ((tmp["home_tri"] == opp_u) & (tmp["away_tri"] == team_u))
        tmp = tmp[matchup_mask].copy()
        if tmp.empty:
            return tmp

        if roster_names:
            tmp_unfiltered = tmp.copy()
            player_keys = tmp["player_name"].astype(str).map(_norm_name_key)
            tmp = tmp[player_keys.isin(roster_names)].copy()
            if tmp.empty:
                # Keep market-derived players when roster normalization removes every row.
                tmp = tmp_unfiltered
            # Merge position data from rosters
            if roster_position_map and "player_name" in tmp.columns:
                tmp["position"] = tmp["player_name"].astype(str).map(lambda pname: roster_position_map.get(_norm_name_key(pname), ""))
                # Clean up empty positions
                tmp.loc[tmp["position"].eq(""), "position"] = None
        if tmp.empty:
            return tmp
        tmp["team"] = team_u
        tmp["opponent"] = opp_u
        out = tmp.copy()
    try:
        if (not team_only.empty) and (out is not None) and (len(out) < 8):
            out = team_only
    except Exception:
        pass
    if (out is None or out.empty) and (not team_only.empty):
        out = team_only
    # Merge position data from rosters (applies to all code paths)
    if processed_root is not None and date_str and not out.empty and 'player_name' in out.columns:
        try:
            roster_df = _team_players_from_processed_rosters_local(processed_root=processed_root, date_str=str(date_str), home_tri=team_u, away_tri=opp_u, team_tri=team_u)
            if roster_df is not None and not roster_df.empty and 'position' in roster_df.columns:
                roster_position_map: dict[str, str] = {}
                for idx, row in roster_df.iterrows():
                    pname = str(row.get('player_name', '')).strip()
                    pos = str(row.get('position', '')).strip()
                    if pname:
                        roster_position_map[_norm_name_key(pname)] = pos
                if roster_position_map:
                    out['position'] = out['player_name'].astype(str).map(lambda pname: roster_position_map.get(_norm_name_key(pname), ''))
                    out.loc[out['position'].eq(''), 'position'] = None
        except Exception:
            pass
    if out.empty:
        return out
    if "playing_today" in out.columns:
        try:
            pt = out["playing_today"].astype(str).str.lower().str.strip()
            out = out[~pt.isin(["false", "0", "no", "n"])].copy()
        except Exception:
            pass
    # Filter to only players with significant playing time (predicted minutes >= 10)
    # This excludes bench players with minimal minutes (typically set to 8.0 or 0)
    if "pred_min" in out.columns and len(out) > 12:  # Only apply filter if we have many players (likely full roster)
        try:
            pred_min = pd.to_numeric(out["pred_min"], errors="coerce").fillna(0)
            out = out[pred_min >= 10.0].copy()
            # If filter removed too many players, relax to pred_min > 0
            if len(out) < 5:
                pred_min = pd.to_numeric(out["pred_min"], errors="coerce").fillna(0)
                out = out[pred_min > 0].copy()
        except Exception:
            pass
    if "player_name" in out.columns:
        out["player_name"] = out["player_name"].astype(str).str.strip()
        out = out[out["player_name"].ne("")].copy()
    try:
        if "player_name" in out.columns:
            if "team" in out.columns:
                out = out.drop_duplicates(subset=["player_name", "team"], keep="last")
            else:
                out = out.drop_duplicates(subset=["player_name"], keep="last")
    except Exception:
        pass
    return out


def _call_source_simulate_smart_game_local(*, smart_sim_module, processed_root: Path, league_code: str, kwargs: dict[str, Any]):
    original_values: dict[str, Any] = {}
    raw_root = processed_root.parent / "raw"
    replacements = {
        "_period_lines_from_processed": lambda date_str, home_tri, away_tri: _period_lines_from_processed_local(
            processed_root=processed_root,
            date_str=date_str,
            home_tri=home_tri,
            away_tri=away_tri,
        ),
        "_market_lines_from_processed_odds": lambda date_str, home_tri, away_tri: _market_lines_from_processed_odds_local(
            processed_root=processed_root,
            date_str=date_str,
            home_tri=home_tri,
            away_tri=away_tri,
        ),
        "_load_smartsim_total_calibration": lambda: _load_smartsim_total_calibration_local(processed_root=processed_root),
        "_team_players_from_props": lambda props_df, team_tri, opp_tri: _team_players_from_props_local(
            props_df=props_df,
            team_tri=team_tri,
            opp_tri=opp_tri,
        ),
        "_coalesce_team_player_frames": lambda *frames: _coalesce_team_player_frames_local(*frames),
        "_infer_game_id": lambda date_str, home_tri, away_tri: _infer_game_id_local(
            processed_root=processed_root,
            date_str=date_str,
            home_tri=home_tri,
            away_tri=away_tri,
        ),
        "_team_players_from_processed_boxscores": lambda date_str, home_tri, away_tri, team_tri, game_id=None: _team_players_from_processed_boxscores_local(
            processed_root=processed_root,
            date_str=date_str,
            home_tri=home_tri,
            away_tri=away_tri,
            team_tri=team_tri,
            game_id=game_id,
        ),
        "_team_players_from_processed_rosters": lambda date_str, home_tri, away_tri, team_tri: _team_players_from_processed_rosters_local(
            processed_root=processed_root,
            date_str=date_str,
            home_tri=home_tri,
            away_tri=away_tri,
            team_tri=team_tri,
        ),
        "_filter_team_players_against_processed_roster": lambda team_df, date_str, home_tri, away_tri, team_tri, min_keep=5: _filter_team_players_against_processed_roster_local(
            processed_root=processed_root,
            team_df=team_df,
            date_str=date_str,
            home_tri=home_tri,
            away_tri=away_tri,
            team_tri=team_tri,
            min_keep=min_keep,
        ),
        "_team_players_from_espn_boxscore": lambda date_str, home_tri, away_tri, team_tri, event_id=None: _team_players_from_espn_boxscore_local(
            processed_root=processed_root,
            league_code=league_code,
            date_str=date_str,
            home_tri=home_tri,
            away_tri=away_tri,
            team_tri=team_tri,
            event_id=event_id,
        ),
        "_espn_name_to_id_map_for_game": lambda date_str, home_tri, away_tri, event_id=None: _espn_name_to_id_map_for_game_local(
            smart_sim_module=smart_sim_module,
            date_str=date_str,
            home_tri=home_tri,
            away_tri=away_tri,
            event_id=event_id,
        ),
        "_merge_pregame_expected_minutes_for_team": lambda team_df, date_str, team_tri: _merge_pregame_expected_minutes_for_team_local(
            processed_root=processed_root,
            team_df=team_df,
            date_str=date_str,
            team_tri=team_tri,
        ),
        "_prune_pregame_rotation_pool": lambda team_df, team_tri, min_keep=8, max_keep=None, protected_names=None: _prune_pregame_rotation_pool_local(
            team_df=team_df,
            team_tri=team_tri,
            min_keep=min_keep,
            max_keep=max_keep,
            protected_names=protected_names,
            league_code=league_code,
        ),
        "_market_player_names_for_matchup": lambda props_df, date_str=None, home_tri="", away_tri="": _market_player_names_for_matchup_local(
            processed_root=processed_root,
            raw_root=raw_root,
            props_df=props_df,
            date_str=date_str,
            home_tri=home_tri,
            away_tri=away_tri,
        ),
        "_rotation_sim_minutes_from_history": lambda team_df, date_str, home_tri, away_tri, team_tri, lookback_days=28: _rotation_sim_minutes_from_history_local(
            smart_sim_module=smart_sim_module,
            league_code=league_code,
            team_df=team_df,
            date_str=date_str,
            home_tri=home_tri,
            away_tri=away_tri,
            team_tri=team_tri,
            lookback_days=lookback_days,
        ),
        "_player_split_rate_context": lambda date_str, team_tri, lookback_days=120: _player_split_rate_context_local(
            smart_sim_module=smart_sim_module,
            date_str=date_str,
            team_tri=team_tri,
            lookback_days=lookback_days,
        ),
        "_player_career_opponent_rate_context": lambda date_str, lookback_days=720: _player_career_opponent_rate_context_local(
            smart_sim_module=smart_sim_module,
            date_str=date_str,
            lookback_days=lookback_days,
        ),
        "_opponent_position_rate_context": lambda date_str, lookback_days=120: _opponent_position_rate_context_local(
            smart_sim_module=smart_sim_module,
            date_str=date_str,
            lookback_days=lookback_days,
        ),
        "simulate_pbp_game_boxscore": lambda **inner_kwargs: _simulate_pbp_game_boxscore_local(**inner_kwargs),
        "simulate_event_level_boxscore": lambda **inner_kwargs: _simulate_event_level_boxscore_local(**inner_kwargs),
        "_rotation_sim_minutes_for_team": lambda team_df, date_str, home_tri, away_tri, team_tri, side, game_id: _rotation_sim_minutes_for_team_local(
            smart_sim_module=smart_sim_module,
            league_code=league_code,
            team_df=team_df,
            date_str=date_str,
            home_tri=home_tri,
            away_tri=away_tri,
            team_tri=team_tri,
            side=side,
            game_id=game_id,
        ),
        "_apply_player_priors": lambda team_df, priors, team_tri, sim_minutes=None, date_str=None: _apply_player_priors_local(
            smart_sim_module=smart_sim_module,
            team_df=team_df,
            priors=priors,
            team_tri=team_tri,
            sim_minutes=sim_minutes,
            date_str=date_str,
        ),
        "_compute_player_priors_cached": lambda asof_date_str, days_back: _compute_player_priors_cached_local(
            processed_root=processed_root,
            asof_date_str=asof_date_str,
            days_back=days_back,
        ),
        "_team_adj_from_advanced_stats": lambda date_str, home_tri, away_tri: _team_adj_from_advanced_stats_local(
            processed_root=processed_root,
            date_str=date_str,
            home_tri=home_tri,
            away_tri=away_tri,
            league=_league_for_code_local(league_code),
        ),
        "_load_intervals_band_calibration": lambda: _load_intervals_band_calibration_local(processed_root=processed_root),
        "_load_intervals_time_profile": lambda: _load_intervals_time_profile_local(processed_root=processed_root),
        "_load_player_stat_calibration": lambda: _load_player_stat_calibration_local(processed_root=processed_root),
    }
    try:
        for name, value in replacements.items():
            original_values[name] = getattr(smart_sim_module, name, None)
            setattr(smart_sim_module, name, value)
        simulate_smart_game = getattr(smart_sim_module, "simulate_smart_game")
        return simulate_smart_game(**kwargs)
    finally:
        for name, value in original_values.items():
            try:
                setattr(smart_sim_module, name, value)
            except Exception:
                pass


def _prune_stale_smart_sim_outputs_local(*, processed_root: Path, date_str: str, expected_matchups: set[tuple[str, str]], out_prefix: str = "smart_sim", remove_all: bool = False) -> int:
    removed = 0
    try:
        out_prefix_s = str(out_prefix or "smart_sim").strip() or "smart_sim"
        expected = {
            f"{out_prefix_s}_{date_str}_{str(home_tri or '').strip().upper()}_{str(away_tri or '').strip().upper()}.json"
            for home_tri, away_tri in (expected_matchups or set())
            if str(home_tri or "").strip() and str(away_tri or "").strip()
        }
        for file_path in processed_root.glob(f"{out_prefix_s}_{date_str}_*.json"):
            if (not remove_all) and file_path.name in expected:
                continue
            try:
                file_path.unlink()
                removed += 1
            except Exception:
                continue
    except Exception:
        return removed
    return removed


def _smart_sim_injuries_excluded_map_for_date_local(*, processed_root: Path, raw_root: Path, date_str: str, props_df):
    import pandas as pd

    out: dict[str, set[str]] = {}
    ds_s = str(date_str).strip()

    def _norm_player_key(value: object) -> str:
        return _norm_name_key(value)

    def _add(tri: str, name: str) -> None:
        team = str(tri or "").strip().upper()
        if not team:
            return
        player_key = _norm_player_key(name)
        if not player_key:
            return
        out.setdefault(team, set()).add(player_key)

    try:
        cutoff_dt = pd.to_datetime(ds_s, errors="coerce")
        cutoff = cutoff_dt if pd.notna(cutoff_dt) else None
    except Exception:
        cutoff = None
    try:
        fresh_cutoff = (cutoff - pd.Timedelta(days=30)) if cutoff is not None else None
    except Exception:
        fresh_cutoff = None

    roster_name_to_tri: dict[str, str] = {}
    ls_allowed: dict[str, set[str]] = {}
    try:
        ls_path = processed_root / f"league_status_{ds_s}.csv"
        if ls_path.exists():
            lsdf = pd.read_csv(ls_path)
            if lsdf is not None and not lsdf.empty:
                if {"team", "player_name"}.issubset(set(lsdf.columns)):
                    tmp = lsdf.copy()
                    tmp["team"] = tmp["team"].astype(str).map(lambda value: str(_to_tricode_local(value) or value or "").strip().upper())
                    tmp["player_name"] = tmp["player_name"].astype(str)
                    for _, row in tmp.iterrows():
                        team = str(row.get("team") or "").strip().upper()
                        player_key = _norm_player_key(row.get("player_name"))
                        if team and player_key:
                            roster_name_to_tri.setdefault(player_key, team)
                    if "playing_today" in tmp.columns:
                        playing_mask = _truthy_mask(tmp["playing_today"])
                        for _, row in tmp[playing_mask].iterrows():
                            team = str(row.get("team") or "").strip().upper()
                            player_key = _norm_player_key(row.get("player_name"))
                            if team and player_key:
                                ls_allowed.setdefault(team, set()).add(player_key)
                        for _, row in tmp[~playing_mask].iterrows():
                            _add(str(row.get("team") or ""), str(row.get("player_name") or ""))
                    elif "injury_status" in tmp.columns:
                        status = tmp["injury_status"].astype(str).str.upper().str.strip()
                        excluded = status.isin({"OUT", "DOUBTFUL", "SUSPENDED", "INACTIVE", "REST"}) | status.str.contains("SEASON", na=False) | status.str.contains("INDEFINITE", na=False)
                        for _, row in tmp[excluded].iterrows():
                            _add(str(row.get("team") or ""), str(row.get("player_name") or ""))
    except Exception:
        roster_name_to_tri = {}
        ls_allowed = {}

    if not roster_name_to_tri:
        try:
            dts = pd.to_datetime(ds_s, errors="coerce")
            season_label = str(int(dts.year)) if not pd.isna(dts) else None
            candidates: list[Path] = []
            if season_label is not None:
                candidates.append(processed_root / f"rosters_{season_label}.csv")
            candidates.extend(sorted(processed_root.glob("rosters_*.csv")))
            seen: set[str] = set()
            for file_path in candidates:
                key = str(file_path)
                if key in seen or not file_path.exists():
                    continue
                seen.add(key)
                rdf = pd.read_csv(file_path)
                if rdf is None or rdf.empty:
                    continue
                cols = {column.upper(): column for column in rdf.columns}
                team_col = cols.get("TEAM_ABBREVIATION") or cols.get("TEAM") or cols.get("TEAM_TRI")
                name_col = cols.get("PLAYER") or cols.get("PLAYER_NAME")
                if not (team_col and name_col):
                    continue
                tmp = rdf[[team_col, name_col]].dropna().copy()
                tmp[team_col] = tmp[team_col].astype(str).str.strip().str.upper()
                for _, row in tmp.iterrows():
                    player_key = _norm_player_key(row.get(name_col))
                    team = str(row.get(team_col) or "").strip().upper()
                    if len(team) != 3:
                        team = str(_to_tricode_local(team) or "").strip().upper()
                    if player_key and team:
                        roster_name_to_tri.setdefault(player_key, team)
                if roster_name_to_tri:
                    break
        except Exception:
            pass

    try:
        excluded_path = processed_root / f"injuries_excluded_{ds_s}.csv"
        if excluded_path.exists():
            df = pd.read_csv(excluded_path)
            if df is not None and not df.empty:
                if "date" in df.columns:
                    df = df.copy()
                    df["date"] = pd.to_datetime(df["date"], errors="coerce")
                    df = df[df["date"].notna()].copy()
                    if cutoff is not None:
                        df = df[df["date"] <= cutoff].copy()
                    if fresh_cutoff is not None and "status" in df.columns:
                        status = df["status"].astype(str).str.upper().str.strip()
                        injury = df.get("injury", "").astype(str).str.upper().str.strip() if "injury" in df.columns else pd.Series([""] * len(df))
                        season_out = status.str.contains("SEASON", na=False) | status.str.contains("INDEFINITE", na=False) | status.str.contains("SEASON-ENDING", na=False)
                        season_out = season_out | injury.str.contains("OUT FOR SEASON", na=False) | injury.str.contains("SEASON-ENDING", na=False) | injury.str.contains("INDEFINITE", na=False)
                        df = df[(df["date"] >= fresh_cutoff) | season_out].copy()
                if "status" in df.columns:
                    status = df["status"].astype(str).str.upper().str.strip()
                    season_out = (status.str.contains("SEASON", na=False) & status.str.contains("OUT", na=False)) | status.str.contains("INDEFINITE", na=False) | status.str.contains("SEASON-ENDING", na=False)
                    df = df[status.isin({"OUT", "DOUBTFUL", "SUSPENDED", "INACTIVE", "REST"}) | season_out].copy()
                team_col = "team_tri" if "team_tri" in df.columns else ("team" if "team" in df.columns else None)
                name_col = "player" if "player" in df.columns else ("player_name" if "player_name" in df.columns else None)
                if team_col and name_col:
                    for _, row in df[[team_col, name_col]].dropna().iterrows():
                        _add(str(row.get(team_col) or ""), str(row.get(name_col) or ""))
    except Exception:
        pass

    try:
        raw_path = raw_root / "injuries.csv"
        if raw_path.exists():
            df = pd.read_csv(raw_path)
            if df is not None and not df.empty:
                if "date" in df.columns:
                    df = df.copy()
                    df["date"] = pd.to_datetime(df["date"], errors="coerce")
                    df = df[df["date"].notna()].copy()
                    if cutoff is not None:
                        df = df[df["date"] <= cutoff].copy()
                    if fresh_cutoff is not None and "status" in df.columns:
                        status0 = df["status"].astype(str).str.upper().str.strip()
                        season_out0 = (status0.str.contains("SEASON", na=False) & status0.str.contains("OUT", na=False)) | status0.str.contains("INDEFINITE", na=False) | status0.str.contains("SEASON-ENDING", na=False)
                        df = df[(df["date"] >= fresh_cutoff) | season_out0].copy()
                    try:
                        df = df.sort_values(["date"]).copy()
                        group_cols = [column for column in ["player", "team"] if column in df.columns]
                        if group_cols:
                            df = df.groupby(group_cols, as_index=False).tail(1).copy()
                    except Exception:
                        pass
                status_col = "status" if "status" in df.columns else ("injury_status" if "injury_status" in df.columns else None)
                name_col = "player" if "player" in df.columns else ("player_name" if "player_name" in df.columns else None)
                team_col = "team" if "team" in df.columns else ("team_tri" if "team_tri" in df.columns else None)
                if status_col and name_col and team_col:
                    status = df[status_col].astype(str).str.upper().str.strip()
                    season_out = (status.str.contains("SEASON", na=False) & status.str.contains("OUT", na=False)) | status.str.contains("INDEFINITE", na=False) | status.str.contains("SEASON-ENDING", na=False)
                    df = df[status.isin({"OUT", "DOUBTFUL", "SUSPENDED", "INACTIVE", "REST"}) | season_out].copy()
                    for _, row in df[[team_col, name_col]].dropna().iterrows():
                        name = str(row.get(name_col) or "")
                        player_key = _norm_player_key(name)
                        team = str(row.get(team_col) or "")
                        if player_key and (player_key in roster_name_to_tri):
                            team = roster_name_to_tri.get(player_key) or team
                        _add(str(team or ""), name)
    except Exception:
        pass

    try:
        if isinstance(props_df, pd.DataFrame) and (not props_df.empty):
            if "team" in props_df.columns and "player_name" in props_df.columns:
                tmp = props_df[["team", "player_name"] + (["playing_today"] if "playing_today" in props_df.columns else [])].copy()
                tmp["team"] = tmp["team"].astype(str).str.strip().str.upper()
                tmp["player_name"] = tmp["player_name"].astype(str).str.strip()
                if "playing_today" in tmp.columns:
                    tmp = tmp[_truthy_mask(tmp["playing_today"]).reindex(tmp.index, fill_value=False)].copy()
                tmp = tmp[tmp["player_name"].ne("")].copy()
                for _, row in tmp.iterrows():
                    team = str(_to_tricode_local(row.get("team")) or row.get("team") or "").strip().upper()
                    player_key = _norm_player_key(row.get("player_name"))
                    if team and player_key and team in out and player_key in out[team]:
                        out[team].discard(player_key)
    except Exception:
        pass

    try:
        for team, names in ls_allowed.items():
            team_key = str(team or "").strip().upper()
            if not team_key or team_key not in out:
                continue
            out[team_key].difference_update(set(str(value or "").strip().upper() for value in names if str(value or "").strip()))
            if not out[team_key]:
                out.pop(team_key, None)
    except Exception:
        pass
    return out


def _smart_sim_worker_init_local(
    date_str: str,
    n_sims: int,
    seed: int | None,
    pbp: bool,
    props_path: str,
    roster_mode: str,
    league_code: str,
    excluded_map: dict[str, set[str]],
    adv_map: dict[str, dict[str, float]],
    game_id_map: dict[tuple[str, str], int],
    name_to_id: dict[str, int],
    team_name_to_id: dict[tuple[str, str], int],
) -> None:
    import pandas as pd

    global _SMARTSIM_WORKER_STATE
    props_df = pd.DataFrame()
    try:
        props_df = pd.read_csv(props_path) if props_path and Path(props_path).exists() else pd.DataFrame()
    except Exception:
        props_df = pd.DataFrame()
    _SMARTSIM_WORKER_STATE = {
        "date_str": str(date_str),
        "n_sims": int(n_sims),
        "seed": seed,
        "pbp": bool(pbp),
        "roster_mode": str(roster_mode or "historical"),
        "league_code": str(league_code or "nba"),
        "props_df": props_df,
        "excluded_map": excluded_map or {},
        "adv_map": adv_map or {},
        "game_id_map": game_id_map or {},
        "name_to_id": name_to_id or {},
        "team_name_to_id": team_name_to_id or {},
    }


def _smart_sim_worker_run_local(job: dict) -> dict:
    import pandas as pd
    import numpy as np

    global _SMARTSIM_WORKER_STATE
    state = _SMARTSIM_WORKER_STATE or {}
    smart_sim_module = _build_local_smart_sim_module(
        processed_root=Path(str(job.get("out_path") or "")).parent,
        league_code=str(state.get("league_code") or "nba"),
    )
    LEAGUE = _league_for_code_local(state.get("league_code"))
    date_s = str(state.get("date_str") or job.get("date_str") or "")
    home_tri = str(job.get("home_tri") or "").strip().upper()
    away_tri = str(job.get("away_tri") or "").strip().upper()
    out_path_s = str(job.get("out_path") or "")
    out_path = Path(out_path_s)

    try:
        market_total = job.get("market_total")
        home_spread = job.get("home_spread")
        market_total_for_quarters = market_total
        if market_total_for_quarters is None:
            try:
                period_lines = _period_lines_from_processed_local(processed_root=out_path.parent, date_str=date_s, home_tri=home_tri, away_tri=away_tri) or {}
                h1 = period_lines.get("h1_total") if isinstance(period_lines, dict) else None
                h1f = float(h1) if h1 is not None else float("nan")
                if np.isfinite(h1f) and h1f > 0:
                    market_total_for_quarters = float(2.0 * h1f)
            except Exception:
                pass
        home_pace = float(job.get("home_pace") or getattr(LEAGUE, "baseline_pace"))
        away_pace = float(job.get("away_pace") or getattr(LEAGUE, "baseline_pace"))
        matchup_pace = float(job.get("matchup_pace") or np.mean([home_pace, away_pace]))
        home_def_rtg = float(job.get("home_def_rtg") or getattr(LEAGUE, "baseline_def_rating"))
        away_def_rtg = float(job.get("away_def_rtg") or getattr(LEAGUE, "baseline_def_rating"))
        home_off_rtg = float(job.get("home_off_rtg") or getattr(LEAGUE, "baseline_off_rating"))
        away_off_rtg = float(job.get("away_off_rtg") or getattr(LEAGUE, "baseline_off_rating"))
        home_outs = int(job.get("home_outs") or 0)
        away_outs = int(job.get("away_outs") or 0)
        home_b2b = bool(job.get("home_b2b") or False)
        away_b2b = bool(job.get("away_b2b") or False)
        home_rest_days = job.get("home_rest_days")
        away_rest_days = job.get("away_rest_days")

        home_ctx = TeamContextLocal(team=home_tri, pace=home_pace, off_rating=home_off_rtg, def_rating=home_def_rtg, injuries_out=home_outs, back_to_back=home_b2b, rest_days=(int(home_rest_days) if home_rest_days is not None else None))
        away_ctx = TeamContextLocal(team=away_tri, pace=away_pace, off_rating=away_off_rtg, def_rating=away_def_rtg, injuries_out=away_outs, back_to_back=away_b2b, rest_days=(int(away_rest_days) if away_rest_days is not None else None))
        qsum = _simulate_quarters_local(processed_root=out_path.parent, inp=GameInputsLocal(date=date_s, home=home_ctx, away=away_ctx, market_total=market_total_for_quarters, market_home_spread=home_spread), league=LEAGUE, n_samples=3000)
        cfg = _build_smart_sim_config_local(n_sims=int(state.get("n_sims") or job.get("n_sims") or 0), seed=state.get("seed"), use_pbp=bool(state.get("pbp")), roster_mode=str(state.get("roster_mode") or job.get("roster_mode") or "historical"))
        pre_ctx = {
            "home_injuries_out": home_outs,
            "away_injuries_out": away_outs,
            "home_pace": float(home_pace) if np.isfinite(float(home_pace)) else None,
            "away_pace": float(away_pace) if np.isfinite(float(away_pace)) else None,
            "home_b2b": home_b2b,
            "away_b2b": away_b2b,
        }
        excluded_map_local = state.get("excluded_map") or {}
        excluded_game = {str(home_tri): set(excluded_map_local.get(home_tri) or set()), str(away_tri): set(excluded_map_local.get(away_tri) or set())}
        out = _call_source_simulate_smart_game_local(
            smart_sim_module=smart_sim_module,
            processed_root=out_path.parent,
            league_code=str(state.get("league_code") or "nba"),
            kwargs={
                "date_str": date_s,
                "home_tri": home_tri,
                "away_tri": away_tri,
                "props_df": state.get("props_df"),
                "quarters": qsum.quarters,
                "market_total": market_total,
                "market_home_spread": home_spread,
                "cfg": cfg,
                "excluded_player_keys_by_team": excluded_game,
                "pregame_context": pre_ctx,
                "processed_root": out_path.parent,
            },
        )

        try:
            name_to_id_local = state.get("name_to_id") or {}
            team_name_to_id_local = state.get("team_name_to_id") or {}
            players = out.get("players") if isinstance(out, dict) else None
            if isinstance(players, dict):
                for side, team_tri in (("home", home_tri), ("away", away_tri)):
                    arr = players.get(side)
                    if not isinstance(arr, list):
                        continue
                    for player_row in arr:
                        if not isinstance(player_row, dict):
                            continue
                        pid = player_row.get("player_id")
                        if pid is None or (isinstance(pid, float) and (not np.isfinite(pid))):
                            name = str(player_row.get("player_name") or "")
                            player_key = _norm_name_key(name) if name else ""
                            if player_key:
                                fixed = team_name_to_id_local.get((team_tri, player_key)) or name_to_id_local.get(player_key)
                                if fixed is not None:
                                    player_row["player_id"] = int(fixed)
                        else:
                            try:
                                player_row["player_id"] = int(pd.to_numeric(pid, errors="coerce"))
                            except Exception:
                                pass
        except Exception:
            pass

        try:
            game_id = (state.get("game_id_map") or {}).get((home_tri, away_tri))
            if game_id is not None and isinstance(out, dict):
                out["game_id"] = int(game_id)
        except Exception:
            pass

        try:
            players_obj = out.get("players") if isinstance(out, dict) else None
            home_players = players_obj.get("home") if isinstance(players_obj, dict) and isinstance(players_obj.get("home"), list) else []
            away_players = players_obj.get("away") if isinstance(players_obj, dict) and isinstance(players_obj.get("away"), list) else []
            if (len(home_players) + len(away_players)) <= 0:
                return {
                    "status": "failed",
                    "home": home_tri,
                    "away": away_tri,
                    "out_path": out_path_s,
                    "error": "smart_sim produced zero player rows",
                }
        except Exception:
            pass

        out_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")
        tmp_path.write_text(_json_dumps_safe_local(out), encoding="utf-8")
        try:
            tmp_path.replace(out_path)
        except Exception:
            out_path.write_text(_json_dumps_safe_local(out), encoding="utf-8")
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass
        return {"status": "wrote", "home": home_tri, "away": away_tri, "out_path": str(out_path)}
    except Exception as exc:
        return {"status": "failed", "home": home_tri, "away": away_tri, "out_path": out_path_s, "error": str(exc)}


def _smart_sim_run_date_local(*, processed_root: Path, raw_root: Path, date_str: str, n_sims: int, seed: int | None, max_games: int | None, overwrite: bool, pbp: bool = True, workers: int | None = None, roster_mode: str = "historical", out_prefix: str = "smart_sim", league_code: str = "nba") -> dict:
    import pandas as pd
    import numpy as np
    from concurrent.futures import ProcessPoolExecutor, as_completed

    to_tricode = _to_tricode_local
    normalize_team = _normalize_team_local
    compute_rest_for_matchups = _compute_rest_for_matchups_local
    LEAGUE = _league_for_code_local(league_code)
    out_prefix_s = str(out_prefix or "smart_sim").strip() or "smart_sim"

    if overwrite:
        for stale_path in processed_root.glob(f"{out_prefix_s}_{date_str}_*.json"):
            try:
                if stale_path.is_file():
                    stale_path.unlink()
            except Exception:
                continue

    pred_path = processed_root / f"predictions_{date_str}.csv"
    if not pred_path.exists():
        return {"date": date_str, "wrote": 0, "skipped": 0, "failures": 0, "reason": f"missing_predictions:{pred_path}"}
    pdf = pd.read_csv(pred_path)
    if pdf is None or pdf.empty:
        return {"date": date_str, "wrote": 0, "skipped": 0, "failures": 0, "reason": f"empty_predictions:{pred_path}"}
    props_path = processed_root / f"props_predictions_{date_str}.csv"
    if not props_path.exists():
        return {"date": date_str, "wrote": 0, "skipped": 0, "failures": 0, "reason": f"missing_props:{props_path}"}
    props_df = pd.read_csv(props_path)
    excluded_map = _smart_sim_injuries_excluded_map_for_date_local(processed_root=processed_root, raw_root=raw_root, date_str=date_str, props_df=props_df)

    odds_df = None
    odds_path = processed_root / f"game_odds_{date_str}.csv"
    if odds_path.exists():
        try:
            odds_df = pd.read_csv(odds_path)
            if odds_df is not None and not odds_df.empty:
                odds_df = odds_df.copy()
                odds_df["home_tri"] = odds_df.get("home_team", "").astype(str).map(to_tricode)
                odds_df["away_tri"] = odds_df.get("visitor_team", "").astype(str).map(to_tricode)
        except Exception:
            odds_df = None

    game_id_map: dict[tuple[str, str], int] = {}
    try:
        pbp_map_path = processed_root / f"pbp_reconcile_{date_str}.csv"
        if pbp_map_path.exists():
            mdf = pd.read_csv(pbp_map_path)
            if mdf is not None and not mdf.empty:
                mdf = mdf.copy()
                mdf["home_tri"] = mdf.get("home_team", "").astype(str).map(to_tricode)
                mdf["away_tri"] = mdf.get("visitor_team", "").astype(str).map(to_tricode)
                mdf["game_id"] = pd.to_numeric(mdf.get("game_id"), errors="coerce")
                mdf = mdf.dropna(subset=["home_tri", "away_tri", "game_id"])
                mdf = mdf.drop_duplicates(subset=["home_tri", "away_tri", "game_id"]).copy()
                for _, row in mdf.iterrows():
                    ht = str(row.get("home_tri") or "").strip().upper()
                    at = str(row.get("away_tri") or "").strip().upper()
                    try:
                        gid = int(row.get("game_id"))
                    except Exception:
                        continue
                    if ht and at:
                        game_id_map[(ht, at)] = gid
                        if (at, ht) not in game_id_map:
                            game_id_map[(at, ht)] = gid
    except Exception:
        game_id_map = {}

    try:
        cards_path = processed_root / f"game_cards_{date_str}.csv"
        if cards_path.exists():
            cdf = pd.read_csv(cards_path)
            if cdf is not None and not cdf.empty:
                cdf = cdf.copy()
                cdf["home_tri"] = cdf.get("home_team", "").astype(str).map(to_tricode)
                cdf["away_tri"] = cdf.get("visitor_team", "").astype(str).map(to_tricode)
                cdf["game_id"] = pd.to_numeric(cdf.get("game_id"), errors="coerce")
                cdf = cdf.dropna(subset=["home_tri", "away_tri", "game_id"])
                for _, row in cdf.iterrows():
                    ht = str(row.get("home_tri") or "").strip().upper()
                    at = str(row.get("away_tri") or "").strip().upper()
                    try:
                        gid = int(row.get("game_id"))
                    except Exception:
                        continue
                    if ht and at and (ht, at) not in game_id_map:
                        game_id_map[(ht, at)] = gid
    except Exception:
        pass

    adv_map: dict[str, dict[str, float]] = {}
    try:
        dts = pd.to_datetime(date_str, errors="coerce")
        season_year = int(dts.year + 1) if (not pd.isna(dts) and int(dts.month) >= 7) else (int(dts.year) if not pd.isna(dts) else None)
    except Exception:
        season_year = None

    def _load_adv_map(season_y: int) -> dict[str, dict[str, float]]:
        out: dict[str, dict[str, float]] = {}
        try:
            file_path = processed_root / f"team_advanced_stats_{int(season_y)}.csv"
            sdf = None
            if file_path.exists():
                try:
                    sdf = pd.read_csv(file_path)
                except Exception:
                    sdf = None
            if sdf is None or sdf.empty:
                return {}
            sdf = sdf.copy()
            sdf["team"] = sdf.get("team", "").astype(str).str.strip().str.upper()
            for _, row in sdf.iterrows():
                team = str(row.get("team") or "").strip().upper()
                if not team:
                    continue
                try:
                    pace_v = float(pd.to_numeric(row.get("pace"), errors="coerce"))
                except Exception:
                    pace_v = float("nan")
                try:
                    def_v = float(pd.to_numeric(row.get("def_rtg"), errors="coerce"))
                except Exception:
                    def_v = float("nan")
                try:
                    off_v = float(pd.to_numeric(row.get("off_rtg"), errors="coerce"))
                except Exception:
                    off_v = float("nan")
                out[team] = {"pace": pace_v, "def_rtg": def_v, "off_rtg": off_v}
        except Exception:
            return {}
        return out

    if season_year is not None:
        adv_map = _load_adv_map(int(season_year))

    def _num(value):
        try:
            numeric = float(pd.to_numeric(value, errors="coerce"))
            return numeric if np.isfinite(numeric) else None
        except Exception:
            return None

    try:
        feats_csv = processed_root / "features.csv"
        feats_parquet = processed_root / "features.parquet"
        if feats_csv.exists():
            hist = pd.read_csv(feats_csv)
        elif feats_parquet.exists():
            hist = pd.read_parquet(feats_parquet)
        else:
            hist = None
        if hist is not None and not hist.empty:
            hist_matchups = hist[[column for column in ["date", "home_team", "visitor_team"] if column in hist.columns]].copy()
            if {"date", "home_team", "visitor_team"}.issubset(set(hist_matchups.columns)):
                hist_matchups["home_team"] = hist_matchups["home_team"].astype(str).map(normalize_team)
                hist_matchups["visitor_team"] = hist_matchups["visitor_team"].astype(str).map(normalize_team)
                matchups = pdf[[column for column in ["date", "home_team", "visitor_team"] if column in pdf.columns]].copy()
                if "date" not in matchups.columns:
                    matchups["date"] = date_str
                matchups["home_team"] = matchups.get("home_team", "").astype(str).map(normalize_team)
                matchups["visitor_team"] = matchups.get("visitor_team", "").astype(str).map(normalize_team)
                rest_df = compute_rest_for_matchups(matchups, hist_matchups)
                if rest_df is not None and not rest_df.empty:
                    rest_cols = [column for column in ["home_rest_days", "visitor_rest_days", "home_b2b", "visitor_b2b"] if column in rest_df.columns]
                    key_cols = [column for column in ["date", "home_team", "visitor_team"] if column in rest_df.columns]
                    if rest_cols and key_cols:
                        pdf = pdf.copy()
                        pdf["date"] = pdf.get("date", date_str)
                        pdf["home_team"] = pdf.get("home_team", "").astype(str).map(normalize_team)
                        pdf["visitor_team"] = pdf.get("visitor_team", "").astype(str).map(normalize_team)
                        rest_df = rest_df.copy()
                        rest_df["date"] = rest_df.get("date", date_str)
                        rest_df["home_team"] = rest_df.get("home_team", "").astype(str).map(normalize_team)
                        rest_df["visitor_team"] = rest_df.get("visitor_team", "").astype(str).map(normalize_team)
                        pdf = pdf.merge(rest_df[key_cols + rest_cols], on=key_cols, how="left")
    except Exception:
        pass

    pdf = pdf.copy()
    pdf["home_tri"] = pdf.get("home_team", "").astype(str).map(to_tricode)
    pdf["away_tri"] = pdf.get("visitor_team", "").astype(str).map(to_tricode)
    pdf = pdf[(pdf["home_tri"].astype(str).str.len() == 3) & (pdf["away_tri"].astype(str).str.len() == 3)].copy()
    if pdf.empty:
        return {"date": date_str, "wrote": 0, "skipped": 0, "failures": 0, "reason": "no_valid_games"}
    failure_path = processed_root / f"{out_prefix_s}_failures_{date_str}.csv"
    try:
        if failure_path.exists() and failure_path.is_file():
            failure_path.unlink()
    except Exception:
        pass
    expected_matchups = {(str(row.get("home_tri") or "").strip().upper(), str(row.get("away_tri") or "").strip().upper()) for _, row in pdf.iterrows() if str(row.get("home_tri") or "").strip() and str(row.get("away_tri") or "").strip()}
    try:
        _prune_stale_smart_sim_outputs_local(processed_root=processed_root, date_str=date_str, expected_matchups=expected_matchups, out_prefix=out_prefix_s, remove_all=bool(overwrite and max_games is not None))
    except Exception:
        pass
    if max_games is not None:
        try:
            pdf = pdf.head(int(max_games))
        except Exception:
            pass

    wrote = 0
    skipped = 0
    failures: list[dict[str, object]] = []
    jobs: list[dict[str, object]] = []
    name_to_id: dict[str, int] = {}
    team_name_to_id: dict[tuple[str, str], int] = {}
    try:
        boxscores_path = processed_root / f"boxscores_{date_str}.csv"
        if boxscores_path.exists():
            bdf = pd.read_csv(boxscores_path)
            if bdf is not None and not bdf.empty and {"PLAYER_NAME", "PLAYER_ID"}.issubset(set(bdf.columns)):
                bdf = bdf.copy()
                bdf["PLAYER_ID"] = pd.to_numeric(bdf["PLAYER_ID"], errors="coerce")
                bdf = bdf.dropna(subset=["PLAYER_ID"])
                bdf["_pkey"] = bdf["PLAYER_NAME"].astype(str).map(_norm_name_key)
                if "TEAM_ABBREVIATION" in bdf.columns:
                    bdf["_tri"] = bdf["TEAM_ABBREVIATION"].astype(str).map(lambda value: to_tricode(str(value)) or str(value))
                    bdf["_tri"] = bdf["_tri"].astype(str).str.upper().str.strip()
                for _, row in bdf.iterrows():
                    try:
                        player_key = str(row.get("_pkey") or "").strip().upper()
                        player_id = int(row.get("PLAYER_ID"))
                        if player_key:
                            name_to_id.setdefault(player_key, player_id)
                        if "_tri" in row and player_key:
                            team = str(row.get("_tri") or "").strip().upper()
                            if team:
                                team_name_to_id.setdefault((team, player_key), player_id)
                    except Exception:
                        continue
    except Exception:
        pass

    try:
        dts = pd.to_datetime(date_str, errors="coerce")
        start_year = int(dts.year) if (not pd.isna(dts) and int(dts.month) >= 7) else (int(dts.year) - 1 if not pd.isna(dts) else None)
        season = f"{start_year}-{str(start_year + 1)[-2:]}" if start_year is not None else None
    except Exception:
        season = None
    roster_file = None
    if season:
        candidate = processed_root / f"rosters_{season}.csv"
        if candidate.exists():
            roster_file = candidate
    if roster_file is None:
        files = list(processed_root.glob("rosters_*.csv"))
        if files:
            files.sort(key=lambda path: path.stat().st_mtime if path.exists() else 0, reverse=True)
            roster_file = files[0]
    try:
        if roster_file is not None and roster_file.exists():
            rdf = pd.read_csv(roster_file)
            if rdf is not None and not rdf.empty:
                cols = {column.upper(): column for column in rdf.columns}
                name_col = cols.get("PLAYER")
                id_col = cols.get("PLAYER_ID")
                tri_col = cols.get("TEAM_ABBREVIATION")
                if name_col and id_col:
                    tmp = rdf[[name_col, id_col] + ([tri_col] if tri_col else [])].copy()
                    tmp[id_col] = pd.to_numeric(tmp[id_col], errors="coerce")
                    tmp = tmp.dropna(subset=[id_col])
                    tmp["_pkey"] = tmp[name_col].astype(str).map(_norm_name_key)
                    if tri_col:
                        tmp["_tri"] = tmp[tri_col].astype(str).map(lambda value: to_tricode(str(value)) or str(value))
                        tmp["_tri"] = tmp["_tri"].astype(str).str.upper().str.strip()
                    for _, row in tmp.iterrows():
                        try:
                            player_key = str(row.get("_pkey") or "").strip().upper()
                            player_id = int(row.get(id_col))
                            if player_key:
                                name_to_id.setdefault(player_key, player_id)
                            if tri_col:
                                team = str(row.get("_tri") or "").strip().upper()
                                if player_key and team:
                                    team_name_to_id.setdefault((team, player_key), player_id)
                        except Exception:
                            continue
    except Exception:
        pass

    for _, row in pdf.iterrows():
        home_tri = str(row.get("home_tri") or "").strip().upper()
        away_tri = str(row.get("away_tri") or "").strip().upper()
        if not home_tri or not away_tri:
            continue
        out_path = processed_root / f"{out_prefix_s}_{date_str}_{home_tri}_{away_tri}.json"
        if overwrite and out_path.exists():
            try:
                out_path.unlink()
            except Exception:
                pass
        if out_path.exists() and (not overwrite):
            if _smart_sim_file_has_players_local(out_path):
                skipped += 1
                continue
            try:
                out_path.unlink()
            except Exception:
                pass
        market_total = _num(row.get("total"))
        home_spread = _num(row.get("home_spread"))
        if (market_total is None or home_spread is None) and (odds_df is not None and not odds_df.empty):
            match = odds_df[(odds_df["home_tri"] == home_tri) & (odds_df["away_tri"] == away_tri)]
            if not match.empty:
                match_row = match.iloc[0]
                if market_total is None:
                    market_total = _num(match_row.get("total"))
                if home_spread is None:
                    home_spread = _num(match_row.get("home_spread"))
        pred_total = _num(row.get("totals"))
        pred_margin = _num(row.get("spread_margin"))
        home_mu = (0.5 * (pred_total + pred_margin)) if (pred_total is not None and pred_margin is not None) else None
        away_mu = (0.5 * (pred_total - pred_margin)) if (pred_total is not None and pred_margin is not None) else None
        try:
            home_pace = float(adv_map.get(home_tri, {}).get("pace"))
        except Exception:
            home_pace = float("nan")
        try:
            away_pace = float(adv_map.get(away_tri, {}).get("pace"))
        except Exception:
            away_pace = float("nan")
        if not np.isfinite(home_pace):
            home_pace = getattr(LEAGUE, "baseline_pace")
        if not np.isfinite(away_pace):
            away_pace = getattr(LEAGUE, "baseline_pace")
        matchup_pace = float(np.mean([home_pace, away_pace])) if (np.isfinite(home_pace) and np.isfinite(away_pace)) else getattr(LEAGUE, "baseline_pace")
        try:
            home_def_rtg = float(adv_map.get(home_tri, {}).get("def_rtg"))
        except Exception:
            home_def_rtg = float("nan")
        try:
            away_def_rtg = float(adv_map.get(away_tri, {}).get("def_rtg"))
        except Exception:
            away_def_rtg = float("nan")
        if not np.isfinite(home_def_rtg):
            home_def_rtg = getattr(LEAGUE, "baseline_def_rating")
        if not np.isfinite(away_def_rtg):
            away_def_rtg = getattr(LEAGUE, "baseline_def_rating")

        def _rating_from_mu(mu: float | None, pace_val: float) -> float:
            try:
                if mu is None or (not np.isfinite(mu)):
                    return float(getattr(LEAGUE, "baseline_off_rating"))
                return float((float(mu) / max(1e-6, float(pace_val))) * 100.0)
            except Exception:
                return float(getattr(LEAGUE, "baseline_off_rating"))

        home_off_rtg = _rating_from_mu(home_mu, matchup_pace)
        away_off_rtg = _rating_from_mu(away_mu, matchup_pace)
        try:
            home_rest_days = int(pd.to_numeric(row.get("home_rest_days"), errors="coerce")) if pd.notna(row.get("home_rest_days")) else None
        except Exception:
            home_rest_days = None
        try:
            away_rest_days = int(pd.to_numeric(row.get("visitor_rest_days"), errors="coerce")) if pd.notna(row.get("visitor_rest_days")) else None
        except Exception:
            away_rest_days = None
        try:
            home_b2b = bool(pd.to_numeric(row.get("home_b2b"), errors="coerce") == 1) if pd.notna(row.get("home_b2b")) else False
        except Exception:
            home_b2b = False
        try:
            away_b2b = bool(pd.to_numeric(row.get("visitor_b2b"), errors="coerce") == 1) if pd.notna(row.get("visitor_b2b")) else False
        except Exception:
            away_b2b = False
        home_outs = int(max(0, min(5, len(excluded_map.get(home_tri, set())))))
        away_outs = int(max(0, min(5, len(excluded_map.get(away_tri, set())))))
        jobs.append({
            "date_str": date_str,
            "home_tri": home_tri,
            "away_tri": away_tri,
            "out_path": str(out_path),
            "roster_mode": str(roster_mode or "historical"),
            "market_total": market_total,
            "home_spread": home_spread,
            "home_pace": float(home_pace),
            "away_pace": float(away_pace),
            "matchup_pace": float(matchup_pace),
            "home_def_rtg": float(home_def_rtg),
            "away_def_rtg": float(away_def_rtg),
            "home_off_rtg": float(home_off_rtg),
            "away_off_rtg": float(away_off_rtg),
            "home_outs": int(home_outs),
            "away_outs": int(away_outs),
            "home_b2b": bool(home_b2b),
            "away_b2b": bool(away_b2b),
            "home_rest_days": home_rest_days,
            "away_rest_days": away_rest_days,
        })

    env_workers = None
    try:
        env_workers = int(os.environ.get("SMARTSIM_WORKERS") or os.environ.get("SMART_SIM_WORKERS") or 0)
    except Exception:
        env_workers = None
    if workers is None:
        workers = env_workers if (env_workers is not None and int(env_workers) > 0) else 1
    try:
        workers = int(workers)
    except Exception:
        workers = 1
    if workers < 1:
        workers = 1

    if jobs:
        if workers == 1 or len(jobs) == 1:
            _smart_sim_worker_init_local(str(date_str), int(n_sims), seed, bool(pbp), str(props_path), str(roster_mode or "historical"), str(league_code or "nba"), excluded_map, adv_map, game_id_map, name_to_id, team_name_to_id)
            for job in jobs:
                result = _smart_sim_worker_run_local(job)
                if result.get("status") == "wrote":
                    wrote += 1
                else:
                    failures.append({"home": result.get("home"), "away": result.get("away"), "error": result.get("error")})
        else:
            worker_count = min(int(workers), int(len(jobs)))
            with ProcessPoolExecutor(max_workers=int(worker_count), initializer=_smart_sim_worker_init_local, initargs=(str(date_str), int(n_sims), seed, bool(pbp), str(props_path), str(roster_mode or "historical"), str(league_code or "nba"), excluded_map, adv_map, game_id_map, name_to_id, team_name_to_id)) as executor:
                futures = [executor.submit(_smart_sim_worker_run_local, job) for job in jobs]
                for future in as_completed(futures):
                    try:
                        result = future.result()
                    except Exception as exc:
                        failures.append({"home": None, "away": None, "error": str(exc)})
                        continue
                    if result.get("status") == "wrote":
                        wrote += 1
                    else:
                        failures.append({"home": result.get("home"), "away": result.get("away"), "error": result.get("error")})

    if failures:
        try:
            pd.DataFrame(failures).to_csv(failure_path, index=False)
        except Exception:
            pass
        return {"date": date_str, "wrote": int(wrote), "skipped": int(skipped), "failures": int(len(failures)), "failures_file": str(failure_path)}
    return {"date": date_str, "wrote": int(wrote), "skipped": int(skipped), "failures": 0}


def _apply_basic_slate_filter(*, preds, processed_root: Path, date_str: str):
    import pandas as pd

    go_path = processed_root / f"game_odds_{date_str}.csv"
    pred_path = processed_root / f"predictions_{date_str}.csv"
    props_path = processed_root / f"oddsapi_player_props_{date_str}.csv"
    if preds is None or getattr(preds, "empty", False) or "team" not in preds.columns:
        return preds

    slate_teams: set[str] = set()
    slate_tricodes: set[str] = set()

    def _add_team(value: object) -> None:
        team = str(value or "").strip().upper()
        if not team:
            return
        slate_teams.add(team)
        tri = _to_tricode_local(team)
        if tri:
            slate_tricodes.add(str(tri).strip().upper())

    def _load_pairs(path: Path, home_candidates: tuple[str, ...], away_candidates: tuple[str, ...]) -> None:
        if not path.exists() or not path.is_file():
            return
        try:
            frame = pd.read_csv(path)
        except Exception:
            return
        if frame is None or frame.empty:
            return
        home_col = next((column for column in home_candidates if column in frame.columns), None)
        away_col = next((column for column in away_candidates if column in frame.columns), None)
        if not home_col or not away_col:
            return
        for _, row in frame.iterrows():
            _add_team(row.get(home_col))
            _add_team(row.get(away_col))

    # Prefer repaired canonical predictions and current props snapshot over game_odds, which may be stale/cross-league.
    _load_pairs(pred_path, ("home_team",), ("visitor_team", "away_team"))
    _load_pairs(props_path, ("home_team",), ("away_team", "visitor_team"))
    _load_pairs(go_path, ("home_team",), ("visitor_team", "away_team"))

    # Keep compatibility with either full names or tricodes in prediction rows.
    slate_all = set(slate_teams) | set(slate_tricodes)
    if not slate_all:
        return preds
    filtered = preds.copy()
    filtered["team"] = filtered["team"].astype(str).str.upper().str.strip()
    filtered["team_tri"] = filtered["team"].map(_to_tricode_local).astype(str).str.upper().str.strip()
    mask = filtered["team"].isin(slate_all) | filtered["team_tri"].isin(slate_all)
    return filtered[mask].drop(columns=["team_tri"], errors="ignore").copy()


def _load_sim_df(*, processed_root: Path, date_str: str, smart_sim_prefix: str):
    import pandas as pd

    sim_rows: list[dict[str, object]] = []
    sim_files = sorted(processed_root.glob(f"{smart_sim_prefix}_{date_str}_*.json"))
    for file_path in sim_files:
        try:
            payload = json.loads(file_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, dict) or payload.get("error"):
            continue
        home_tri = str(payload.get("home") or "").strip().upper()
        away_tri = str(payload.get("away") or "").strip().upper()
        players = payload.get("players") or {}
        for side, team_tri in (("home", home_tri), ("away", away_tri)):
            rows = players.get(side) or []
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                player_name = str(row.get("player_name") or "").strip()
                if not player_name:
                    continue
                try:
                    player_id = int(pd.to_numeric(row.get("player_id"), errors="coerce")) if row.get("player_id") is not None else None
                except Exception:
                    player_id = None
                sim_rows.append(
                    {
                        "team": team_tri,
                        "player_id": player_id,
                        "player_name": player_name,
                        "name_key": _norm_name_key(player_name),
                        "opponent": away_tri if side == "home" else home_tri,
                        "home": side == "home",
                        "mean_pts": row.get("pts_mean"),
                        "mean_reb": row.get("reb_mean"),
                        "mean_ast": row.get("ast_mean"),
                        "mean_threes": row.get("threes_mean"),
                        "mean_pra": row.get("pra_mean"),
                        "mean_stl": row.get("stl_mean"),
                        "mean_blk": row.get("blk_mean"),
                        "mean_tov": row.get("tov_mean"),
                        "sd_pts": row.get("pts_sd"),
                        "sd_reb": row.get("reb_sd"),
                        "sd_ast": row.get("ast_sd"),
                        "sd_threes": row.get("threes_sd"),
                        "sd_pra": row.get("pra_sd"),
                        "sd_stl": row.get("stl_sd"),
                        "sd_blk": row.get("blk_sd"),
                        "sd_tov": row.get("tov_sd"),
                    }
                )
    return pd.DataFrame(sim_rows)


def _merge_smart_sim_into_preds(*, preds, sim_df):
    import pandas as pd
    import numpy as np

    if sim_df is None or sim_df.empty:
        return preds
    sim_df = sim_df.copy()
    sim_df["team"] = sim_df["team"].astype(str).str.upper().str.strip()
    sim_df["name_key"] = sim_df["name_key"].astype(str).str.upper().str.strip()
    if "player_id" in sim_df.columns:
        sim_df["player_id"] = pd.to_numeric(sim_df["player_id"], errors="coerce").astype("Int64")
    for column in [
        "mean_pts", "mean_reb", "mean_ast", "mean_threes", "mean_pra", "mean_stl", "mean_blk", "mean_tov",
        "sd_pts", "sd_reb", "sd_ast", "sd_threes", "sd_pra", "sd_stl", "sd_blk", "sd_tov",
    ]:
        if column in sim_df.columns:
            sim_df[column] = pd.to_numeric(sim_df[column], errors="coerce")
    sim_df_pid = sim_df[sim_df["player_id"].notna()].drop_duplicates(subset=["player_id"], keep="last") if "player_id" in sim_df.columns else pd.DataFrame()
    sim_df_name = sim_df.drop_duplicates(subset=["team", "name_key"], keep="last")

    merged = preds.copy()
    if "team" in merged.columns:
        merged["team"] = merged["team"].astype(str).str.upper().str.strip()
    if "player_name" not in merged.columns:
        merged["player_name"] = None
    merged["_name_key"] = merged["player_name"].astype(str).map(_norm_name_key)
    if ("player_id" in merged.columns) and (not sim_df_pid.empty):
        merged["player_id"] = pd.to_numeric(merged["player_id"], errors="coerce").astype("Int64")
        merged = merged.merge(sim_df_pid, on=["player_id"], how="left", suffixes=("", "_sim"))
    need_name_match = pd.Series([True] * len(merged), index=merged.index)
    if merged.filter(like="_sim").shape[1] > 0:
        need_name_match = ~merged.filter(like="_sim").notna().any(axis=1)
    if bool(need_name_match.any()):
        sub_idx = merged.index[need_name_match]
        by_name = merged.loc[need_name_match].merge(
            sim_df_name,
            left_on=["team", "_name_key"],
            right_on=["team", "name_key"],
            how="left",
            suffixes=("", "_sim2"),
        )
        by_name.index = sub_idx
        for column in [
            "mean_pts", "mean_reb", "mean_ast", "mean_threes", "mean_pra", "mean_stl", "mean_blk", "mean_tov",
            "sd_pts", "sd_reb", "sd_ast", "sd_threes", "sd_pra", "sd_stl", "sd_blk", "sd_tov",
        ]:
            sim2_col = f"{column}_sim2"
            sim_col = f"{column}_sim"
            if sim2_col in by_name.columns:
                if sim_col not in by_name.columns:
                    by_name[sim_col] = np.nan
                by_name[sim_col] = by_name[sim2_col].where(by_name[sim2_col].notna(), by_name[sim_col])
        for base_col in ("player_id", "player_name", "opponent", "home"):
            sim2_col = f"{base_col}_sim2"
            if sim2_col in by_name.columns:
                if base_col not in by_name.columns:
                    by_name[base_col] = np.nan
                by_name[base_col] = by_name[sim2_col].where(by_name[sim2_col].notna(), by_name[base_col])
        update_cols = [column for column in by_name.columns if column.endswith("_sim") and column in merged.columns]
        update_cols.extend([column for column in ("player_id", "player_name", "opponent", "home") if column in merged.columns and column in by_name.columns])
        update_cols = list(dict.fromkeys(update_cols))
        if update_cols:
            merged.loc[sub_idx, update_cols] = by_name[update_cols]
    for column in [
        "mean_pts", "mean_reb", "mean_ast", "mean_threes", "mean_pra", "mean_stl", "mean_blk", "mean_tov",
        "sd_pts", "sd_reb", "sd_ast", "sd_threes", "sd_pra", "sd_stl", "sd_blk", "sd_tov",
    ]:
        sim_col = f"{column}_sim"
        if sim_col in merged.columns:
            if column not in merged.columns:
                merged[column] = np.nan
            merged[column] = merged[sim_col].where(merged[sim_col].notna(), merged[column])
    out = merged.drop(columns=[column for column in merged.columns if column.endswith("_sim") or column in {"_name_key", "name_key"}], errors="ignore")

    existing_ids: set[int] = set()
    if "player_id" in out.columns:
        existing_ids = set(pd.to_numeric(out["player_id"], errors="coerce").dropna().astype(int).tolist())
    sim_add = sim_df_name.copy()
    if "player_id" in sim_add.columns:
        sim_add["player_id"] = pd.to_numeric(sim_add["player_id"], errors="coerce")
        sim_add = sim_add[sim_add["player_id"].isna() | ~sim_add["player_id"].astype("Int64").isin(list(existing_ids))].copy()
    if not sim_add.empty:
        base_columns = list(out.columns)
        append_rows: list[dict[str, object]] = []
        for _, row in sim_add.iterrows():
            append_row = {column: np.nan for column in base_columns}
            for column in base_columns:
                if column in {"team", "player_id", "player_name", "opponent", "home"}:
                    append_row[column] = row.get(column)
                elif column.startswith("mean_") or column.startswith("sd_"):
                    append_row[column] = row.get(column)
            append_rows.append(append_row)
        if append_rows:
            out = pd.concat([out, pd.DataFrame(append_rows)], ignore_index=True)
    return out


def export_props_predictions_with_smart_sim_local(
    *,
    source_root: Path,
    date_str: str,
    out_path: Path,
    smart_sim_n_sims: int,
    smart_sim_pbp: bool,
    smart_sim_workers: int,
    smart_sim_overwrite: bool = False,
) -> tuple[int, Path]:
    import pandas as pd

    from .basketball_props_predictions import _export_props_predictions_without_smart_sim_local

    _, written_path = _export_props_predictions_without_smart_sim_local(
        source_root=source_root,
        date_str=date_str,
        out_path=out_path,
    )
    processed_root = source_root / "data" / "processed"
    preds = pd.read_csv(written_path)
    preds = _apply_basic_slate_filter(preds=preds, processed_root=processed_root, date_str=date_str)
    default_pp = processed_root / f"props_predictions_{date_str}.csv"
    default_pp.parent.mkdir(parents=True, exist_ok=True)
    preds.to_csv(default_pp, index=False)

    roster_mode = _resolve_smart_sim_roster_mode_local(date_str=date_str, roster_mode="historical")
    league_code = _league_code_from_source_root_local(source_root)
    _smart_sim_run_date_local(
        processed_root=processed_root,
        raw_root=source_root / "data" / "raw",
        date_str=date_str,
        n_sims=int(smart_sim_n_sims),
        seed=None,
        max_games=None,
        overwrite=bool(smart_sim_overwrite),
        pbp=bool(smart_sim_pbp),
        workers=int(smart_sim_workers),
        roster_mode=roster_mode,
        out_prefix="smart_sim",
        league_code=league_code,
    )

    sim_df = _load_sim_df(processed_root=processed_root, date_str=date_str, smart_sim_prefix="smart_sim")
    if sim_df is None or sim_df.empty:
        failures_path = processed_root / f"smart_sim_failures_{date_str}.csv"
        reason = f"SmartSim produced no player rows for {date_str}"
        if failures_path.exists() and failures_path.is_file():
            reason = f"{reason}; see {failures_path.name}"
        raise RuntimeError(reason)
    preds = _merge_smart_sim_into_preds(preds=preds, sim_df=sim_df)
    preds.to_csv(written_path, index=False)
    return int(len(preds.index)), written_path