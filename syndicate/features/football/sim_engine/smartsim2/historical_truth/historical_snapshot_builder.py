"""Build historical truth snapshots from NFL play-by-play data.

Aggregates nflverse play-by-play into per-drive and per-game truth records and
summary metrics, and adapts them into the existing calibration benchmark
contract without touching the simulator.
"""

from __future__ import annotations

from collections import defaultdict
from statistics import mean
from typing import Any
from typing import Iterable

import pandas as pd

from syndicate.features.football.sim_engine.smartsim2.historical_truth.historical_snapshot_contract import (
    RESULT_END_OF_HALF,
    RESULT_FIELD_GOAL,
    RESULT_MISSED_FIELD_GOAL,
    RESULT_OTHER,
    RESULT_PUNT,
    RESULT_SAFETY,
    RESULT_TOUCHDOWN,
    RESULT_TURNOVER,
    RESULT_TURNOVER_ON_DOWNS,
    HistoricalDriveRecord,
    HistoricalGameRecord,
    HistoricalTruthMetrics,
    HistoricalTruthSnapshot,
)

_FIXED_DRIVE_RESULT_MAP = {
    "touchdown": RESULT_TOUCHDOWN,
    "opp touchdown": RESULT_TURNOVER,
    "field goal": RESULT_FIELD_GOAL,
    "missed field goal": RESULT_MISSED_FIELD_GOAL,
    "punt": RESULT_PUNT,
    "turnover": RESULT_TURNOVER,
    "turnover on downs": RESULT_TURNOVER_ON_DOWNS,
    "end of half": RESULT_END_OF_HALF,
    "end of game": RESULT_END_OF_HALF,
    "safety": RESULT_SAFETY,
}

_SCORING_RESULTS = {RESULT_TOUCHDOWN, RESULT_FIELD_GOAL}


def canonical_drive_result(fixed_drive_result: Any) -> str:
    text = str(fixed_drive_result or "").strip().lower()
    return _FIXED_DRIVE_RESULT_MAP.get(text, RESULT_OTHER)


def _parse_time_of_possession(value: Any) -> int:
    text = str(value or "").strip()
    if not text or ":" not in text:
        return 0
    minutes, _, seconds = text.partition(":")
    try:
        return int(minutes) * 60 + int(seconds)
    except ValueError:
        return 0


def _to_int(value: Any, default: int = 0) -> int:
    try:
        if pd.isna(value):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _safe_mean(values: Iterable[float]) -> float:
    samples = [float(value) for value in values]
    return mean(samples) if samples else 0.0


def build_drive_records(pbp: pd.DataFrame, *, regular_season_only: bool = True) -> list[HistoricalDriveRecord]:
    frame = pbp
    if regular_season_only and "season_type" in frame.columns:
        frame = frame[frame["season_type"] == "REG"]
    frame = frame[frame["posteam"].notna() & frame["fixed_drive"].notna()]

    records: list[HistoricalDriveRecord] = []
    grouped = frame.groupby(["game_id", "fixed_drive"], sort=True)
    for (game_id, fixed_drive), drive in grouped:
        drive = drive.sort_values("play_id")
        first = drive.iloc[0]
        offense = str(first.get("posteam") or "")
        defense = str(first.get("defteam") or "")
        if not offense:
            continue

        result = canonical_drive_result(first.get("fixed_drive_result"))
        plays = _to_int(first.get("drive_play_count"), default=0)
        if plays <= 0:
            play_flags = drive["play"] if "play" in drive.columns else None
            plays = int(play_flags.fillna(0).astype(float).sum()) if play_flags is not None else len(drive)
        seconds = _parse_time_of_possession(first.get("drive_time_of_possession"))

        yardlines = drive["yardline_100"].dropna() if "yardline_100" in drive.columns else pd.Series(dtype=float)
        start_yardline_100 = _to_int(yardlines.iloc[0], default=75) if len(yardlines) else 75
        min_yardline_100 = _to_int(yardlines.min(), default=start_yardline_100) if len(yardlines) else start_yardline_100
        red_zone_entry = min_yardline_100 <= 20 or result == RESULT_TOUCHDOWN
        goal_to_go_entry = min_yardline_100 <= 10 or result == RESULT_TOUCHDOWN

        yards = int(drive["yards_gained"].fillna(0).astype(float).sum()) if "yards_gained" in drive.columns else 0

        score_start = _to_int(first.get("posteam_score"), default=0)
        score_end = _to_int(drive.iloc[-1].get("posteam_score_post"), default=score_start)
        points = max(0, score_end - score_start)
        if points == 0 and result == RESULT_TOUCHDOWN:
            points = 7
        elif points == 0 and result == RESULT_FIELD_GOAL:
            points = 3

        records.append(
            HistoricalDriveRecord(
                drive_id=f"{game_id}-{int(fixed_drive)}",
                game_id=str(game_id),
                season=_to_int(first.get("season"), default=0),
                week=_to_int(first.get("week"), default=0),
                offense_team=offense,
                defense_team=defense,
                quarter_start=max(1, min(5, _to_int(first.get("qtr"), default=1))),
                result=result,
                plays=plays,
                seconds=seconds,
                yards=yards,
                points=points,
                start_yardline_100=max(1, min(99, start_yardline_100)),
                red_zone_entry=bool(red_zone_entry),
                goal_to_go_entry=bool(goal_to_go_entry),
                metadata={"fixed_drive_result": str(first.get("fixed_drive_result") or "")},
            )
        )
    return records


def build_game_records(pbp: pd.DataFrame, *, regular_season_only: bool = True) -> list[HistoricalGameRecord]:
    frame = pbp
    if regular_season_only and "season_type" in frame.columns:
        frame = frame[frame["season_type"] == "REG"]

    drive_counts: dict[str, int] = defaultdict(int)
    with_drives = frame[frame["fixed_drive"].notna() & frame["posteam"].notna()]
    for game_id, drives in with_drives.groupby("game_id")["fixed_drive"]:
        drive_counts[str(game_id)] = int(drives.nunique())

    records: list[HistoricalGameRecord] = []
    for game_id, game in frame.groupby("game_id", sort=True):
        game = game.sort_values("play_id")
        last = game.iloc[-1]
        home_team = str(last.get("home_team") or "")
        away_team = str(last.get("away_team") or "")
        home_final = _to_int(game["total_home_score"].dropna().max(), default=0)
        away_final = _to_int(game["total_away_score"].dropna().max(), default=0)

        home_quarters: list[int] = []
        away_quarters: list[int] = []
        previous_home = 0
        previous_away = 0
        for quarter in range(1, 5):
            in_quarter = game[game["qtr"].fillna(0).astype(float) <= quarter]
            home_cum = _to_int(in_quarter["total_home_score"].dropna().max(), default=previous_home) if len(in_quarter) else previous_home
            away_cum = _to_int(in_quarter["total_away_score"].dropna().max(), default=previous_away) if len(in_quarter) else previous_away
            home_quarters.append(max(0, home_cum - previous_home))
            away_quarters.append(max(0, away_cum - previous_away))
            previous_home = home_cum
            previous_away = away_cum

        records.append(
            HistoricalGameRecord(
                game_id=str(game_id),
                season=_to_int(last.get("season"), default=0),
                week=_to_int(last.get("week"), default=0),
                home_team=home_team,
                away_team=away_team,
                home_points=home_final,
                away_points=away_final,
                quarter_home_points=tuple(home_quarters),  # type: ignore[arg-type]
                quarter_away_points=tuple(away_quarters),  # type: ignore[arg-type]
                drives=drive_counts.get(str(game_id), 0),
                metadata={"overtime_points": max(0, (home_final + away_final) - (sum(home_quarters) + sum(away_quarters)))},
            )
        )
    return records


def compute_truth_metrics(
    drive_records: list[HistoricalDriveRecord],
    game_records: list[HistoricalGameRecord],
) -> HistoricalTruthMetrics:
    drive_count = len(drive_records) or 1

    def result_rate(result: str) -> float:
        return sum(1 for record in drive_records if record.result == result) / drive_count

    red_zone_entries = [record for record in drive_records if record.red_zone_entry]
    red_zone_scores = [record for record in red_zone_entries if record.result in _SCORING_RESULTS]

    quarter_totals: list[float] = []
    for quarter_index in range(4):
        quarter_totals.append(
            _safe_mean(
                record.quarter_home_points[quarter_index] + record.quarter_away_points[quarter_index]
                for record in game_records
            )
        )

    return HistoricalTruthMetrics(
        possessions_per_game=_safe_mean(record.drives for record in game_records),
        plays_per_drive=_safe_mean(record.plays for record in drive_records),
        seconds_per_drive=_safe_mean(record.seconds for record in drive_records),
        yards_per_drive=_safe_mean(record.yards for record in drive_records),
        touchdown_rate=result_rate(RESULT_TOUCHDOWN),
        field_goal_rate=result_rate(RESULT_FIELD_GOAL),
        missed_field_goal_rate=result_rate(RESULT_MISSED_FIELD_GOAL),
        punt_rate=result_rate(RESULT_PUNT),
        turnover_rate=result_rate(RESULT_TURNOVER),
        turnover_on_downs_rate=result_rate(RESULT_TURNOVER_ON_DOWNS),
        end_of_half_rate=result_rate(RESULT_END_OF_HALF),
        red_zone_entry_rate=len(red_zone_entries) / drive_count,
        red_zone_conversion_rate=(len(red_zone_scores) / len(red_zone_entries)) if red_zone_entries else 0.0,
        quarter_scoring=tuple(quarter_totals),  # type: ignore[arg-type]
        game_totals=_safe_mean(record.total_points for record in game_records),
        drive_sample_size=len(drive_records),
        game_sample_size=len(game_records),
    )


def build_historical_truth_snapshot(
    pbp: pd.DataFrame,
    *,
    seasons: Iterable[int],
    source_name: str = "nflverse play-by-play",
    regular_season_only: bool = True,
    league: str = "nfl",
) -> HistoricalTruthSnapshot:
    """Build a league-agnostic truth snapshot from a canonicalized pbp-shaped frame.

    ``league`` defaults to "nfl" so every existing call site is unaffected;
    the NCAAF loader passes ``league="ncaaf"`` after canonicalizing CFBD
    drives/plays/games into the same frame shape (see
    ``ncaaf_historical_loader.canonicalize_ncaaf_frame``). The drive/game
    aggregation and metrics logic below is shared, untouched, football-core
    code — only the input frame and the drive-result vocabulary differ.
    """
    drive_records = build_drive_records(pbp, regular_season_only=regular_season_only)
    game_records = build_game_records(pbp, regular_season_only=regular_season_only)
    metrics = compute_truth_metrics(drive_records, game_records)
    return HistoricalTruthSnapshot(
        league=league,
        seasons=tuple(sorted(set(int(season) for season in seasons))),
        source_name=source_name,
        drive_records=tuple(drive_records),
        game_records=tuple(game_records),
        metrics=metrics,
        metadata={"regular_season_only": regular_season_only},
    )


__all__ = [
    "build_drive_records",
    "build_game_records",
    "build_historical_truth_snapshot",
    "canonical_drive_result",
    "compute_truth_metrics",
]
