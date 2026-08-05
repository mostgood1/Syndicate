"""SmartSim 2.0 NFL preseason projection contract.

A parallel, NOT a replacement, for
``syndicate/features/nfl/smartsim2_projection.py``'s regular-season
contract -- imports and extends its column tuple/dataclass rather than
duplicating them, so the two schemas can't silently drift apart, but uses
a distinct filename prefix (``smartsim2_preseason_projections_...``) and
a closed ``week`` domain (1-4, matching ESPN's own preseason week
numbering) so it is never parsed by the regular-season discovery regex in
``syndicate/features/nfl/sources.py`` and never appears in
``available_weeks()``/``week_summaries()`` -- see the injury-adjustment
and week-1-default work earlier this session for why interleaving
preseason into the regular-season week domain (0, negatives, string
labels) is unsafe throughout this codebase.

Real preseason games have no in-preseason play-by-play to rate teams
from (nflverse has zero preseason pbp, confirmed structural). This
contract's extra fields (``nonstarter_participation_share``,
``shrinkage_applied``, ``uncertainty_note``) exist so every preseason
projection is self-documenting about how much real prior-season signal
was shrunk away and why -- see
``scripts/generate_smartsim2_nfl_preseason_projections.py`` for where
these are computed.
"""

from __future__ import annotations

import csv
import re
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from typing import Sequence

from syndicate.features.nfl.smartsim2_projection import PROJECTION_CSV_COLUMNS
from syndicate.features.nfl.smartsim2_projection import SmartSimNflProjection

PRESEASON_PROJECTION_CSV_COLUMNS: tuple[str, ...] = PROJECTION_CSV_COLUMNS + (
    "nonstarter_participation_share",
    "shrinkage_applied",
    "uncertainty_note",
)

_PRESEASON_FILENAME_RE = re.compile(r"^smartsim2_preseason_projections_(?P<season>\d{4})_wk(?P<week>[1-4])\.csv$")


@dataclass(frozen=True)
class SmartSimNflPreseasonProjection(SmartSimNflProjection):
    nonstarter_participation_share: float
    shrinkage_applied: float
    uncertainty_note: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_csv_row(self) -> dict[str, str]:
        payload = self.to_dict()
        return {column: str(payload[column]) for column in PRESEASON_PROJECTION_CSV_COLUMNS}

    @classmethod
    def from_csv_row(cls, row: dict[str, str]) -> "SmartSimNflPreseasonProjection":
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
            nonstarter_participation_share=float(row["nonstarter_participation_share"]),
            shrinkage_applied=float(row["shrinkage_applied"]),
            uncertainty_note=str(row["uncertainty_note"]),
        )


def preseason_projection_artifact_path(*, season: int, week: int, data_root: Path) -> Path:
    return data_root / f"smartsim2_preseason_projections_{season}_wk{week}.csv"


def write_preseason_projection_artifact(
    projections: Sequence[SmartSimNflPreseasonProjection],
    *,
    season: int,
    week: int,
    data_root: Path,
) -> Path:
    path = preseason_projection_artifact_path(season=season, week=week, data_root=data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(PRESEASON_PROJECTION_CSV_COLUMNS))
        writer.writeheader()
        for projection in projections:
            writer.writerow(projection.to_csv_row())
    return path


def read_preseason_projection_artifact(*, season: int, week: int, data_root: Path) -> tuple[SmartSimNflPreseasonProjection, ...]:
    path = preseason_projection_artifact_path(season=season, week=week, data_root=data_root)
    if not path.exists():
        return ()
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return tuple(SmartSimNflPreseasonProjection.from_csv_row(row) for row in csv.DictReader(handle))


def preseason_seasons_and_weeks(data_root: Path) -> dict[int, list[int]]:
    """Every real (season, week) with an already-generated real preseason
    projection artifact on disk -- mirrors the regular-season standalone
    discovery pattern in sources.py, but scoped to this module's own
    filename prefix/week domain so it never touches the regular-season
    scan."""
    result: dict[int, list[int]] = {}
    if not data_root.exists():
        return result
    for path in data_root.glob("smartsim2_preseason_projections_*_wk*.csv"):
        match = _PRESEASON_FILENAME_RE.match(path.name)
        if not match:
            continue
        season = int(match.group("season"))
        week = int(match.group("week"))
        result.setdefault(season, []).append(week)
    for season in result:
        result[season] = sorted(set(result[season]))
    return result


__all__ = [
    "PRESEASON_PROJECTION_CSV_COLUMNS",
    "SmartSimNflPreseasonProjection",
    "preseason_projection_artifact_path",
    "preseason_seasons_and_weeks",
    "read_preseason_projection_artifact",
    "write_preseason_projection_artifact",
]
