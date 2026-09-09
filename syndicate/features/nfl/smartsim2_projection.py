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
import json
from dataclasses import asdict
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any
from typing import Mapping
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


def ratings_artifact_path(*, season: int, week: int, data_root: Path) -> Path:
    """Where the live re-sim reads the ratings the PREGAME projection used.

    WHY THIS EXISTS. `team_rating()` needs `load_pbp_plays()` twice -- measured
    98 MB / 48,771 rows / 2.29 s PER SEASON, so ~4.6 s and ~190 MB of reads for
    one call. A live tick cannot pay that on a cadence (`#241`: periodic worker
    work is never free, and it restart-looped production), and paying it once
    per process is affordable but does not fix the real problem.

    THE REAL PROBLEM IS DRIFT, NOT COST. NCAAF's live re-sim routes ratings
    "THROUGH THE GENERATOR'S OWN FUNCTION, so the centring and the defense
    negation cannot drift from the pregame projection this re-sim exists to
    update" -- it can do that cheaply because SP+ is already a cached artifact.
    NFL computed its ratings from play-by-play inside the generator and threw
    them away; only `rating_source` survived on the projection row. A re-sim
    that recomputed them could silently disagree with the number it is
    updating, and NEITHER the live-re-sim flag NOR `UNINFORMATIVE_BAND` would
    catch that: they gate the probability, not its provenance.

    Written beside the projections, from the SAME `current_plays`/`prior_plays`
    in the same run, so the two cannot disagree by construction.
    """
    return data_root / f"smartsim2_ratings_{season}_wk{week}.json"


def write_ratings_artifact(
    ratings: Mapping[str, tuple[float, float, str]],
    *,
    season: int,
    week: int,
    data_root: Path,
) -> Path:
    """`{team: {offense, defense, rating_source}}` plus the run's own stamp.

    `rating_source` is carried PER TEAM rather than once for the file: the
    generator falls back per team (`current_season_rolling` /
    `prior_season_fallback` / `neutral_no_data`), so a single file-level tag
    would report the first team's provenance for all of them. A team on
    `neutral_no_data` is exactly the case a reader must be able to see.
    """
    path = ratings_artifact_path(season=season, week=week, data_root=data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "season": season,
        "week": week,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "teams": {
            str(team): {
                "offense": round(float(offense), 6),
                "defense": round(float(defense), 6),
                "rating_source": str(source),
            }
            for team, (offense, defense, source) in sorted(ratings.items())
        },
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def read_ratings_artifact(*, season: int, week: int, data_root: Path) -> dict[str, tuple[float, float]]:
    """`{team: (offense, defense)}` for the live re-sim, or {} when absent.

    Returns the shape `build_live_lens_snapshot(ratings=...)` wants. An absent
    or unreadable file yields {} rather than raising, so the tick refuses each
    game by name (`no_pregame_ratings`) instead of the whole tick vanishing --
    a tick that disappears is indistinguishable from one that had no games.
    """
    path = ratings_artifact_path(season=season, week=week, data_root=data_root)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out: dict[str, tuple[float, float]] = {}
    for team, entry in (payload.get("teams") or {}).items():
        try:
            out[str(team)] = (float(entry["offense"]), float(entry["defense"]))
        except (KeyError, TypeError, ValueError):
            continue
    return out


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


# SEGMENT DISTRIBUTIONS -- an ADDITIVE SIDECAR, not a column. `#S1`.
#
# The sim already computed per-quarter scoring for every seed and both
# generators discarded it, so the persisted artifact was 8 scalars per game
# with no distribution of any kind. These re-export the sidecar writer/reader
# from `syndicate/features/shared/football_segment_distributions.py` (one
# implementation, shared with NCAAF, so the two sports cannot bin `h1`/`h2`
# differently) and are the projection contract's entry point to it.
#
# `PROJECTION_CSV_COLUMNS` and `SmartSimNflProjection` are UNCHANGED: same
# fields, same order, same values. With the flag off nothing here is called
# and the CSV is byte-identical to the pre-change one.
from syndicate.features.shared.football_segment_distributions import (  # noqa: E402
    read_segment_distributions_artifact,
    segment_distributions_artifact_path,
    write_segment_distributions_artifact,
)


__all__ = [
    "PROJECTION_CSV_COLUMNS",
    "SMARTSIM2_PUBLIC_LABEL",
    "SMARTSIM2_SOURCE_LABEL",
    "SmartSimNflProjection",
    "projection_artifact_path",
    "read_projection_artifact",
    "read_segment_distributions_artifact",
    "segment_distributions_artifact_path",
    "write_projection_artifact",
    "write_segment_distributions_artifact",
]
