"""SmartSim 2.0 NFL projection contract.

Defines the data shape SmartSim 2.0 (the Football Core simulator) produces
per game for Syndicate's NFL pipeline, and the on-disk artifact it is
serialized to (``smartsim2_projections_{season}_wk{week}.csv``).

Mirrors ``syndicate/features/ncaaf/smartsim2_projection.py`` -- the
dataclass/reader/writer contract is sport-agnostic (no NCAAF-specific
literals in the original), so this is the same shape, not a new design.
This module does not import or modify anything under
``syndicate/features/football/sim_engine/smartsim2`` -- it is Syndicate-side
glue that *consumes* SmartSim 2.0 as a library (see
``scripts/generate_smartsim2_nfl_projections.py`` for the generation job).
"""

from __future__ import annotations

import csv
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from typing import Sequence

SMARTSIM2_SOURCE_LABEL = "SmartSim 2.0 (shadow)"
SMARTSIM2_PUBLIC_LABEL = "SmartSim 2.0"

PROJECTION_CSV_COLUMNS: tuple[str, ...] = (
    "game_id",
    "season",
    "week",
    "home_team",
    "away_team",
    "home_score_mean",
    "away_score_mean",
    "margin_mean",
    "total_mean",
    "margin_stdev",
    "total_stdev",
    "home_win_rate",
    "seeds_used",
    "profile_name",
    "rating_source",
    "generated_at",
)


@dataclass(frozen=True)
class SmartSimNflProjection:
    game_id: str
    season: int
    week: int
    home_team: str
    away_team: str
    home_score_mean: float
    away_score_mean: float
    margin_mean: float
    total_mean: float
    margin_stdev: float
    total_stdev: float
    home_win_rate: float
    seeds_used: int
    profile_name: str
    rating_source: str
    generated_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_csv_row(self) -> dict[str, str]:
        payload = self.to_dict()
        return {column: str(payload[column]) for column in PROJECTION_CSV_COLUMNS}

    @classmethod
    def from_csv_row(cls, row: dict[str, str]) -> "SmartSimNflProjection":
        return cls(
            game_id=str(row["game_id"]),
            season=int(row["season"]),
            week=int(row["week"]),
            home_team=str(row["home_team"]),
            away_team=str(row["away_team"]),
            home_score_mean=float(row["home_score_mean"]),
            away_score_mean=float(row["away_score_mean"]),
            margin_mean=float(row["margin_mean"]),
            total_mean=float(row["total_mean"]),
            margin_stdev=float(row["margin_stdev"]),
            total_stdev=float(row["total_stdev"]),
            home_win_rate=float(row["home_win_rate"]),
            seeds_used=int(row["seeds_used"]),
            profile_name=str(row["profile_name"]),
            rating_source=str(row["rating_source"]),
            generated_at=str(row["generated_at"]),
        )


def projection_artifact_path(*, season: int, week: int, data_root: Path) -> Path:
    return data_root / f"smartsim2_projections_{season}_wk{week}.csv"


def write_projection_artifact(
    projections: Sequence[SmartSimNflProjection],
    *,
    season: int,
    week: int,
    data_root: Path,
) -> Path:
    path = projection_artifact_path(season=season, week=week, data_root=data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(PROJECTION_CSV_COLUMNS))
        writer.writeheader()
        for projection in projections:
            writer.writerow(projection.to_csv_row())
    return path


def read_projection_artifact(*, season: int, week: int, data_root: Path) -> tuple[SmartSimNflProjection, ...]:
    path = projection_artifact_path(season=season, week=week, data_root=data_root)
    if not path.exists():
        return ()
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return tuple(SmartSimNflProjection.from_csv_row(row) for row in csv.DictReader(handle))


__all__ = [
    "PROJECTION_CSV_COLUMNS",
    "SMARTSIM2_PUBLIC_LABEL",
    "SMARTSIM2_SOURCE_LABEL",
    "SmartSimNflProjection",
    "projection_artifact_path",
    "read_projection_artifact",
    "write_projection_artifact",
]
