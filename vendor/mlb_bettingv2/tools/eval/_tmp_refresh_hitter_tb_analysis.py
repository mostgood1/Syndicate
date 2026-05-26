from __future__ import annotations

import argparse
import gzip
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sim_engine.market_pitcher_props import normalize_pitcher_name
from sim_engine.models import (
    BatterProfile,
    Handedness,
    Lineup,
    ManagerProfile,
    ParkFactors,
    PitchType,
    PitcherProfile,
    Player,
    Team,
    TeamRoster,
    UmpireFactors,
    WeatherFactors,
)
from tools.daily_update import _sim_many
from tools.daily_update_multi_profile import (
    _extract_hitter_predictions,
    _get_hitter_prob,
    _is_hitter_prediction_eligible,
    _select_market_side,
)
DEFAULT_DATES = [
    "2025-06-03",
    "2025-09-20",
    "2025-09-16",
    "2025-07-28",
    "2025-07-22",
]
DEFAULT_SOURCE_ROOT = ROOT / "data" / "_tmp_daily_smoke3" / "backfill"
DEFAULT_ARTIFACT_IN = ROOT / "data" / "eval" / "_tmp_hitter_subcap_volume_backfill_analysis.json"
DEFAULT_ARTIFACT_OUT = ROOT / "data" / "eval" / "_tmp_hitter_subcap_volume_backfill_analysis_tb_refresh.json"
DEFAULT_HR_CAL = ROOT / "data" / "tuning" / "hitter_hr_calibration" / "default.json"
DEFAULT_PROPS_CAL = ROOT / "data" / "tuning" / "hitter_props_calibration" / "default.json"
DEFAULT_STAKE_U = 0.25
MARKETS = (
    "hitter_home_runs",
    "hitter_hits",
    "hitter_total_bases",
    "hitter_runs",
    "hitter_rbis",
)
SCENARIOS: Dict[str, Dict[str, Any]] = {
    "official_shared10": {"mode": "shared", "shared_cap": 10},
    "balanced11": {
        "mode": "subcaps",
        "subcaps": {
            "hitter_home_runs": 1,
            "hitter_hits": 5,
            "hitter_total_bases": 2,
            "hitter_runs": 2,
            "hitter_rbis": 1,
        },
    },
    "balanced12_rbi2": {
        "mode": "subcaps",
        "subcaps": {
            "hitter_home_runs": 1,
            "hitter_hits": 5,
            "hitter_total_bases": 2,
            "hitter_runs": 2,
            "hitter_rbis": 2,
        },
    },
    "balanced12_runs3": {
        "mode": "subcaps",
        "subcaps": {
            "hitter_home_runs": 1,
            "hitter_hits": 5,
            "hitter_total_bases": 2,
            "hitter_runs": 3,
            "hitter_rbis": 1,
        },
    },
    "aggressive13": {
        "mode": "subcaps",
        "subcaps": {
            "hitter_home_runs": 1,
            "hitter_hits": 6,
            "hitter_total_bases": 2,
            "hitter_runs": 2,
            "hitter_rbis": 2,
        },
    },
    "tbhr11_rbi0": {
        "mode": "subcaps",
        "subcaps": {
            "hitter_home_runs": 2,
            "hitter_hits": 4,
            "hitter_total_bases": 3,
            "hitter_runs": 2,
            "hitter_rbis": 0,
        },
    },
    "tbhr12_hits5_rbi0": {
        "mode": "subcaps",
        "subcaps": {
            "hitter_home_runs": 2,
            "hitter_hits": 5,
            "hitter_total_bases": 3,
            "hitter_runs": 2,
            "hitter_rbis": 0,
        },
    },
    "tbhr12_runs3_rbi0": {
        "mode": "subcaps",
        "subcaps": {
            "hitter_home_runs": 2,
            "hitter_hits": 4,
            "hitter_total_bases": 3,
            "hitter_runs": 3,
            "hitter_rbis": 0,
        },
    },
    "tbheavy12_rbi0": {
        "mode": "subcaps",
        "subcaps": {
            "hitter_home_runs": 2,
            "hitter_hits": 4,
            "hitter_total_bases": 4,
            "hitter_runs": 2,
            "hitter_rbis": 0,
        },
    },
}


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2), encoding="utf-8")


def _hand(value: Any, default: str = "R") -> Handedness:
    try:
        return Handedness(str(value or default).upper())
    except Exception:
        return Handedness(default)


def _pitch_type(value: Any) -> PitchType:
    try:
        return PitchType(str(value or "OTHER").upper())
    except Exception:
        return PitchType.OTHER


def _build_batter(row: Dict[str, Any]) -> BatterProfile:
    player = Player(
        mlbam_id=int(row.get("id") or 0),
        full_name=str(row.get("name") or ""),
        primary_position=str(row.get("pos") or ""),
        bat_side=_hand(row.get("bat")),
        throw_side=_hand(row.get("throw")),
    )
    profile = BatterProfile(player=player)
    for key in (
        "k_rate",
        "bb_rate",
        "hbp_rate",
        "hr_rate",
        "inplay_hit_rate",
        "xb_hit_share",
        "triple_share_of_xb",
        "sb_attempt_rate",
        "sb_success_rate",
        "bb_gb_rate",
        "bb_fb_rate",
        "bb_ld_rate",
        "bb_pu_rate",
    ):
        if key in row:
            try:
                setattr(profile, key, float(row.get(key)))
            except Exception:
                pass
    if "bb_inplay_n" in row:
        try:
            profile.bb_inplay_n = int(row.get("bb_inplay_n") or 0)
        except Exception:
            pass
    profile.vs_pitch_type = {_pitch_type(k): float(v) for k, v in (row.get("vs_pitch_type") or {}).items()}
    profile.platoon_mult_vs_lhp = {str(k): float(v) for k, v in (row.get("platoon_mult_vs_lhp") or {}).items()}
    profile.platoon_mult_vs_rhp = {str(k): float(v) for k, v in (row.get("platoon_mult_vs_rhp") or {}).items()}
    profile.statcast_quality_mult = {str(k): float(v) for k, v in (row.get("statcast_quality_mult") or {}).items()}
    profile.vs_pitcher_hr_mult = {int(k): float(v) for k, v in (row.get("vs_pitcher_hr_mult") or {}).items()}
    return profile


def _build_pitcher(row: Dict[str, Any]) -> PitcherProfile:
    player = Player(
        mlbam_id=int(row.get("id") or 0),
        full_name=str(row.get("name") or ""),
        primary_position="P",
        bat_side=_hand(row.get("throw")),
        throw_side=_hand(row.get("throw")),
    )
    profile = PitcherProfile(player=player)
    for key in (
        "k_rate",
        "bb_rate",
        "hbp_rate",
        "hr_rate",
        "inplay_hit_rate",
        "batters_faced",
        "balls_in_play",
        "availability_mult",
        "bb_gb_rate",
        "bb_fb_rate",
        "bb_ld_rate",
        "bb_pu_rate",
        "leverage_skill",
    ):
        if key in row:
            try:
                setattr(profile, key, float(row.get(key)))
            except Exception:
                pass
    for key in (
        "statcast_splits_source",
        "statcast_splits_start_date",
        "statcast_splits_end_date",
        "arsenal_source",
        "role",
    ):
        if key in row:
            try:
                setattr(profile, key, str(row.get(key) or ""))
            except Exception:
                pass
    for key in ("statcast_splits_n_pitches", "arsenal_sample_size", "stamina_pitches", "bb_inplay_n"):
        if key in row:
            try:
                setattr(profile, key, int(float(row.get(key) or 0)))
            except Exception:
                pass
    profile.arsenal = {_pitch_type(k): float(v) for k, v in (row.get("arsenal") or {}).items()}
    profile.pitch_type_whiff_mult = {_pitch_type(k): float(v) for k, v in (row.get("pitch_type_whiff_mult") or {}).items()}
    profile.pitch_type_inplay_mult = {_pitch_type(k): float(v) for k, v in (row.get("pitch_type_inplay_mult") or {}).items()}
    profile.platoon_mult_vs_lhb = {str(k): float(v) for k, v in (row.get("platoon_mult_vs_lhb") or {}).items()}
    profile.platoon_mult_vs_rhb = {str(k): float(v) for k, v in (row.get("platoon_mult_vs_rhb") or {}).items()}
    profile.statcast_quality_mult = {str(k): float(v) for k, v in (row.get("statcast_quality_mult") or {}).items()}
    return profile


def _build_team_roster(side: Dict[str, Any]) -> TeamRoster:
    team = Team(
        team_id=int((side.get("team") or {}).get("team_id") or 0),
        name=str((side.get("team") or {}).get("name") or ""),
        abbreviation=str((side.get("team") or {}).get("abbreviation") or ""),
    )
    manager_data = side.get("manager") or {}
    manager_kwargs = {
        key: manager_data[key]
        for key in ManagerProfile.__dataclass_fields__.keys()
        if key in manager_data
    }
    manager = ManagerProfile(**manager_kwargs)
    lineup = Lineup(
        batters=[_build_batter(row) for row in (side.get("lineup") or [])],
        pitcher=_build_pitcher(side.get("starter_profile") or {}),
        bench=[_build_batter(row) for row in (side.get("bench") or [])],
        bullpen=[_build_pitcher(row) for row in (side.get("bullpen_profiles") or [])],
    )
    return TeamRoster(team=team, manager=manager, lineup=lineup)


def _weather_from_sim(sim_doc: Dict[str, Any]) -> WeatherFactors:
    data = sim_doc.get("weather") or {}
    return WeatherFactors(
        source=str(data.get("source") or ""),
        condition=str(data.get("condition") or ""),
        temperature_f=data.get("temperature_f"),
        wind_speed_mph=data.get("wind_speed_mph"),
        wind_direction=str(data.get("wind_direction") or ""),
        wind_raw=str(data.get("wind_raw") or ""),
        is_dome=data.get("is_dome"),
    )


def _park_from_sim(sim_doc: Dict[str, Any]) -> ParkFactors:
    data = sim_doc.get("park") or {}
    mult = data.get("multipliers") or {}
    return ParkFactors(
        source=str(data.get("source") or ""),
        venue_id=data.get("venue_id"),
        venue_name=str(data.get("venue_name") or ""),
        roof_type=str(data.get("roof_type") or ""),
        roof_status=str(data.get("roof_status") or ""),
        left_line=data.get("left_line"),
        center=data.get("center"),
        right_line=data.get("right_line"),
        hr_mult_override=mult.get("hr_mult"),
        inplay_hit_mult_override=mult.get("inplay_hit_mult"),
        xb_share_mult_override=mult.get("xb_share_mult"),
    )


def _umpire_from_sim(sim_doc: Dict[str, Any]) -> UmpireFactors:
    data = sim_doc.get("umpire") or {}
    return UmpireFactors(
        source=str(data.get("source") or ""),
        home_plate_umpire_id=data.get("home_plate_umpire_id"),
        home_plate_umpire_name=str(data.get("home_plate_umpire_name") or ""),
        called_strike_mult=float(data.get("called_strike_mult") or 1.0),
    )


def _game_sort_key(path: Path) -> Tuple[int, str]:
    name = path.name
    try:
        prefix = name.split("_", 2)[1]
        return int(prefix), name
    except Exception:
        return (10**9, name)


def _find_date_root(date: str, source_roots: List[Path]) -> Optional[Path]:
    for source_root in source_roots:
        day_root = source_root / date / "hitter"
        sim_dir = day_root / "sims" / date
        snap_dir = day_root / "snapshots" / date
        if sim_dir.exists() and snap_dir.exists():
            return source_root
    return None


def _iter_game_pairs(date: str, source_root: Path) -> Iterable[Tuple[Path, Path]]:
    day_root = source_root / date / "hitter"
    sim_dir = day_root / "sims" / date
    snap_dir = day_root / "snapshots" / date
    for sim_path in sorted(sim_dir.glob("sim_*.json"), key=_game_sort_key):
        roster_name = sim_path.name.replace("sim_", "roster_", 1)
        roster_path = snap_dir / roster_name
        if roster_path.exists():
            yield sim_path, roster_path


def _build_sim_obj(sim_doc: Dict[str, Any], roster_doc: Dict[str, Any], sims: int, workers: int, hr_cal: Dict[str, Any], props_cal: Dict[str, Any]) -> Dict[str, Any]:
    away = _build_team_roster(roster_doc["away"])
    home = _build_team_roster(roster_doc["home"])
    sim_out = _sim_many(
        away,
        home,
        sims=int(sims),
        seed=1337,
        workers=int(workers),
        weather=_weather_from_sim(sim_doc),
        park=_park_from_sim(sim_doc),
        umpire=_umpire_from_sim(sim_doc),
        hitter_hr_top_n=24,
        hitter_props_top_n=24,
        hitter_hr_prob_calibration=hr_cal,
        hitter_props_prob_calibration=props_cal,
        cfg_kwargs={"bip_roe_rate": 0.015, "bip_fc_rate": 0.05},
    )
    return {
        "date": sim_doc.get("date"),
        "game_pk": sim_doc.get("game_pk"),
        "away": sim_doc.get("away"),
        "home": sim_doc.get("home"),
        "schedule": sim_doc.get("schedule"),
        "sim": sim_out,
    }


def _odds_by_date(date: str) -> Dict[str, Any]:
    token = date.replace("-", "_")
    path = ROOT / "data" / "market" / "oddsapi" / f"oddsapi_hitter_props_{token}.json"
    payload = (_read_json(path).get("hitter_props") or {}) if path.exists() else {}
    return {normalize_pitcher_name(str(name)): markets for name, markets in payload.items()}


def _base_row(sim_obj: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "date": str(sim_obj.get("date") or ""),
        "game_pk": sim_obj.get("game_pk"),
        "away": (sim_obj.get("away") or {}).get("name"),
        "home": (sim_obj.get("home") or {}).get("name"),
        "away_abbr": (sim_obj.get("away") or {}).get("abbreviation"),
        "home_abbr": (sim_obj.get("home") or {}).get("abbreviation"),
        "double_header": ((sim_obj.get("schedule") or {}).get("double_header")),
        "game_number": ((sim_obj.get("schedule") or {}).get("game_number")),
    }


def _collect_rows_for_date(date: str, sim_objs: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    odds = _odds_by_date(date)
    rows: List[Dict[str, Any]] = []
    raw_counts = {market: 0 for market in MARKETS}
    market_specs = {
        "batter_home_runs": ("hitter_home_runs", "Hitter HRs"),
        "batter_hits": ("hitter_hits", "Hitter Hits"),
        "batter_total_bases": ("hitter_total_bases", "Hitter Total Bases"),
        "batter_runs_scored": ("hitter_runs", "Hitter Runs"),
        "batter_rbis": ("hitter_rbis", "Hitter RBIs"),
    }
    for sim_obj in sim_objs:
        pred = _extract_hitter_predictions(sim_obj)
        base = _base_row(sim_obj)
        for player_key, rec in pred.items():
            if not _is_hitter_prediction_eligible(rec):
                continue
            markets = odds.get(player_key)
            if not isinstance(markets, dict):
                continue
            for market_key, (market_name, market_label) in market_specs.items():
                props_market = markets.get(market_key) or {}
                line = props_market.get("line")
                if line is None:
                    continue
                try:
                    line_value = float(line)
                except Exception:
                    continue
                p_over = _get_hitter_prob(market_key, line_value, rec)
                if p_over is None:
                    continue
                side_pick = _select_market_side(
                    float(p_over),
                    props_market.get("over_odds"),
                    props_market.get("under_odds"),
                    0.0,
                )
                if side_pick is None:
                    continue
                raw_counts[market_name] = int(raw_counts.get(market_name, 0) + 1)
                rows.append(
                    {
                        **base,
                        "market": market_name,
                        "market_label": market_label,
                        "player_name": rec.get("name"),
                        "team": rec.get("team"),
                        "prop": market_key,
                        "selection": side_pick["selection"],
                        "edge": float(side_pick["edge"]),
                        "market_line": float(line_value),
                        "model_prob_over": float(p_over),
                        "selected_side_market_prob": float(side_pick["selected_side_market_prob"]),
                        "odds": side_pick["odds"],
                        "stake_u": float(DEFAULT_STAKE_U),
                    }
                )
    return rows, raw_counts


def _rank_rows(rows: Iterable[Dict[str, Any]], cap: Optional[int] = None) -> List[Dict[str, Any]]:
    ranked = sorted(
        [dict(row) for row in rows],
        key=lambda row: (float(row.get("edge") or 0.0), float(row.get("model_prob_over") or 0.0)),
        reverse=True,
    )
    if cap is not None:
        ranked = ranked[: int(cap)]
    for idx, row in enumerate(ranked, start=1):
        row["rank"] = int(idx)
    return ranked


def _select_rows(rows: List[Dict[str, Any]], scenario: Dict[str, Any]) -> List[Dict[str, Any]]:
    if str(scenario.get("mode") or "") == "shared":
        return _rank_rows(rows, int(scenario.get("shared_cap") or 0))
    selected: List[Dict[str, Any]] = []
    subcaps = scenario.get("subcaps") or {}
    for market in MARKETS:
        selected.extend(_rank_rows([row for row in rows if row.get("market") == market], int(subcaps.get(market) or 0)))
    return _rank_rows(selected, None)


def _load_game_actuals(date: str, game_pk: int) -> Dict[str, Dict[str, Dict[str, int]]]:
    path = ROOT / "data" / "raw" / "statsapi" / "feed_live" / "2025" / date / f"{int(game_pk)}.json.gz"
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        doc = json.load(fh)
    teams = (((doc.get("liveData") or {}).get("boxscore") or {}).get("teams") or {})
    out: Dict[str, Dict[str, Dict[str, int]]] = {"away": {}, "home": {}}
    for side in ("away", "home"):
        players = ((teams.get(side) or {}).get("players") or {})
        side_map: Dict[str, Dict[str, int]] = {}
        for raw_player in players.values():
            person = raw_player.get("person") or {}
            name_key = normalize_pitcher_name(str(person.get("fullName") or ""))
            if not name_key:
                continue
            batting = (raw_player.get("stats") or {}).get("batting") or {}
            hits = int(batting.get("hits") or batting.get("H") or 0)
            doubles = int(batting.get("doubles") or batting.get("2B") or 0)
            triples = int(batting.get("triples") or batting.get("3B") or 0)
            home_runs = int(batting.get("homeRuns") or batting.get("HR") or 0)
            runs = int(batting.get("runs") or batting.get("R") or 0)
            rbis = int(batting.get("rbi") or batting.get("RBI") or 0)
            total_bases = int(hits + doubles + 2 * triples + 3 * home_runs)
            side_map[name_key] = {
                "hits": hits,
                "home_runs": home_runs,
                "total_bases": total_bases,
                "runs": runs,
                "rbis": rbis,
            }
        out[side] = side_map
    return out


def _market_actual_value(market: str, actuals: Dict[str, int]) -> int:
    if market == "hitter_home_runs":
        return int(actuals.get("home_runs") or 0)
    if market == "hitter_hits":
        return int(actuals.get("hits") or 0)
    if market == "hitter_total_bases":
        return int(actuals.get("total_bases") or 0)
    if market == "hitter_runs":
        return int(actuals.get("runs") or 0)
    if market == "hitter_rbis":
        return int(actuals.get("rbis") or 0)
    return 0


def _profit_from_american(stake_u: float, odds: Any) -> float:
    odd = float(odds)
    if odd > 0:
        return float(stake_u) * odd / 100.0
    return float(stake_u) * 100.0 / abs(odd)


def _settle_row(row: Dict[str, Any], actual_cache: Dict[Tuple[str, int], Dict[str, Dict[str, Dict[str, int]]]]) -> Dict[str, Any]:
    date = str(row.get("date") or "")
    game_pk = int(row.get("game_pk") or 0)
    cache_key = (date, game_pk)
    if cache_key not in actual_cache:
        actual_cache[cache_key] = _load_game_actuals(date, game_pk)
    team = str(row.get("team") or "")
    if team == str(row.get("away_abbr") or ""):
        side = "away"
    elif team == str(row.get("home_abbr") or ""):
        side = "home"
    else:
        side = "away"
    player_key = normalize_pitcher_name(str(row.get("player_name") or ""))
    actuals = ((actual_cache[cache_key].get(side) or {}).get(player_key))
    settled = dict(row)
    if not isinstance(actuals, dict):
        settled["settled"] = False
        settled["missing_actual"] = True
        return settled
    actual_value = _market_actual_value(str(row.get("market") or ""), actuals)
    line = float(row.get("market_line") or 0.0)
    selection = str(row.get("selection") or "")
    win = actual_value > line if selection == "over" else actual_value < line
    profit_u = _profit_from_american(float(row.get("stake_u") or DEFAULT_STAKE_U), row.get("odds")) if win else -float(row.get("stake_u") or DEFAULT_STAKE_U)
    settled.update(
        {
            "settled": True,
            "missing_actual": False,
            "actual_value": int(actual_value),
            "win": bool(win),
            "profit_u": float(profit_u),
        }
    )
    return settled


def _summary(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    stake_u = float(sum(float(row.get("stake_u") or 0.0) for row in rows))
    profit_u = float(sum(float(row.get("profit_u") or 0.0) for row in rows))
    wins = int(sum(1 for row in rows if bool(row.get("win"))))
    losses = int(sum(1 for row in rows if row.get("settled") and not bool(row.get("win"))))
    return {
        "n": int(len(rows)),
        "wins": wins,
        "losses": losses,
        "stake_u": round(stake_u, 4),
        "profit_u": round(profit_u, 4),
        "roi": (round(profit_u / stake_u, 4) if stake_u > 0 else None),
    }


def _per_market_summary(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for market in MARKETS:
        out[market] = _summary([row for row in rows if row.get("market") == market])
    return out


def _scenario_report(name: str, scenario: Dict[str, Any], rows_by_date: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    actual_cache: Dict[Tuple[str, int], Dict[str, Dict[str, Dict[str, int]]]] = {}
    selected_all: List[Dict[str, Any]] = []
    settled_all: List[Dict[str, Any]] = []
    date_reports: List[Dict[str, Any]] = []
    for date, rows in rows_by_date.items():
        selected = _select_rows(rows, scenario)
        settled = [_settle_row(row, actual_cache) for row in selected]
        settled_ok = [row for row in settled if row.get("settled")]
        selected_all.extend(selected)
        settled_all.extend(settled_ok)
        date_reports.append(
            {
                "date": date,
                "selected_n": int(len(selected)),
                "settled_n": int(len(settled_ok)),
                "missing_actual_n": int(sum(1 for row in settled if row.get("missing_actual"))),
                "summary": _summary(settled_ok),
                "market_summary": _per_market_summary(settled_ok),
                "sample_hr_tb_picks": [
                    {
                        "player_name": row.get("player_name"),
                        "team": row.get("team"),
                        "market": row.get("market"),
                        "selection": row.get("selection"),
                        "market_line": row.get("market_line"),
                        "odds": row.get("odds"),
                        "actual_value": row.get("actual_value"),
                        "profit_u": row.get("profit_u"),
                    }
                    for row in settled_ok
                    if str(row.get("market") or "") in ("hitter_home_runs", "hitter_total_bases")
                ][:10],
            }
        )
    return {
        "scenario": scenario,
        "overall": _summary(settled_all),
        "market_summary": _per_market_summary(settled_all),
        "selected_n": int(len(selected_all)),
        "settled_n": int(len(settled_all)),
        "missing_actual_n": int(len(selected_all) - len(settled_all)),
        "date_reports": date_reports,
        "sample_hr_tb_picks": [
            {
                "date": row.get("date"),
                "player_name": row.get("player_name"),
                "team": row.get("team"),
                "market": row.get("market"),
                "selection": row.get("selection"),
                "market_line": row.get("market_line"),
                "odds": row.get("odds"),
                "actual_value": row.get("actual_value"),
                "profit_u": row.get("profit_u"),
            }
            for row in settled_all
            if str(row.get("market") or "") in ("hitter_home_runs", "hitter_total_bases")
        ][:25],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Refresh hitter subcap backfill with TB support from saved roster snapshots.")
    ap.add_argument("--date", action="append", dest="dates", help="Specific date to include (can be passed multiple times).")
    ap.add_argument("--sims", type=int, default=50)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--source-root", action="append", dest="source_roots", help="Root containing <date>/hitter/sims and snapshots. Can be passed multiple times.")
    ap.add_argument("--artifact-in", default=str(DEFAULT_ARTIFACT_IN))
    ap.add_argument("--artifact-out", default=str(DEFAULT_ARTIFACT_OUT))
    args = ap.parse_args()

    dates = list(args.dates or DEFAULT_DATES)
    source_roots = [Path(str(p)) for p in (args.source_roots or [str(DEFAULT_SOURCE_ROOT)])]
    artifact_in = Path(str(args.artifact_in))
    artifact_out = Path(str(args.artifact_out))
    hr_cal = _read_json(DEFAULT_HR_CAL)
    props_cal = _read_json(DEFAULT_PROPS_CAL)
    prior = _read_json(artifact_in) if artifact_in.exists() else {}
    historical = prior.get("historical_validation44") if isinstance(prior, dict) else None

    recomputed_rows_by_date: Dict[str, List[Dict[str, Any]]] = {}
    raw_counts_by_date: Dict[str, Dict[str, int]] = {}
    games_by_date: Dict[str, int] = {}
    source_root_by_date: Dict[str, str] = {}

    for date in dates:
        source_root = _find_date_root(date, source_roots)
        if source_root is None:
            raise SystemExit(f"No source root found for date {date}. Checked: {', '.join(str(p) for p in source_roots)}")
        sim_objs: List[Dict[str, Any]] = []
        game_n = 0
        for sim_path, roster_path in _iter_game_pairs(date, source_root):
            sim_doc = _read_json(sim_path)
            roster_doc = _read_json(roster_path)
            sim_obj = _build_sim_obj(sim_doc, roster_doc, int(args.sims), int(args.workers), hr_cal, props_cal)
            sim_objs.append(sim_obj)
            game_n += 1
            print(f"[{date}] recomputed game {game_n}: {sim_path.name}")
        rows, raw_counts = _collect_rows_for_date(date, sim_objs)
        recomputed_rows_by_date[date] = rows
        raw_counts_by_date[date] = raw_counts
        games_by_date[date] = game_n
        source_root_by_date[date] = str(source_root)
        print(f"[{date}] games={game_n} raw_rows={len(rows)} tb_rows={raw_counts.get('hitter_total_bases', 0)} hr_rows={raw_counts.get('hitter_home_runs', 0)}")

    aligned = {
        "dates": dates,
        "sims": int(args.sims),
        "workers": int(args.workers),
        "source_roots": [str(p) for p in source_roots],
        "source_root_by_date": source_root_by_date,
        "raw_candidate_counts_by_date": raw_counts_by_date,
        "games_by_date": games_by_date,
        "scenarios": {
            name: _scenario_report(name, scenario, recomputed_rows_by_date)
            for name, scenario in SCENARIOS.items()
        },
    }

    out = {
        "historical_validation44": historical,
        "aligned_hitter_backfill_tb_refresh": aligned,
        "notes": [
            "This refresh rebuilds the selected hitter backfill dates from saved roster snapshots instead of the stale sim JSON payloads.",
            "The prior backfill files were missing total_bases_*plus top-N fields, which suppressed hitter_total_bases recommendations even when OddsAPI total-bases markets existed.",
            "Historical validation44 results are carried forward unchanged from the prior artifact.",
        ],
    }
    _write_json(artifact_out, out)
    print(f"Wrote: {artifact_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
