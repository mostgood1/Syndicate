"""The published projection artifact: what the WORKER computes and the WEB serves.

Why this exists
---------------
`/nfl/fantasy` originally ran the whole projection inside the request handler.
That is a worker-split violation (``CLAUDE.md``: the web service "does no heavy
computation ... only reads precomputed artifacts"), and it was not a theoretical
one -- the engine reads ~61 MB of raw nflverse play-by-play, rosters and depth
charts, takes ~3 s for a full season, and **none of those files are on the web
dyno's disk**. Render disks are per-service. Measured 2026-08-21:
``nfl_source/tracking/nflverse/schedules_games.csv`` returns count 0 from
``/api/ops/artifacts/export`` on a pattern that was ALREADY allowlisted, against
a control (``oddsapi_player_props_*.csv``) returning 14. So the route did not
degrade on production -- it raised, and all three routes 500'd.

So the worker computes once and publishes this, and the web reads it.

The one design decision worth stating
-------------------------------------
**The artifact stores STAT LINES, not fantasy points.** A stat line is
scoring-independent; points are not. Storing points would mean either three
artifacts (PPR / half / standard) or freezing the league format at build time.
Storing the line means one artifact serves every scoring profile, because
``score_stat_line`` is a pure function applied at request time -- which is
cheap, and is exactly the "light transformation for display" the web service is
allowed to do.

Why the layout is columnar
--------------------------
``artifact_publisher._PUBLISH_MAX_BYTES`` is **12 MB** per file, and this
carries a full season plus all 18 weeks for ~600 players. A row-per-player
mapping repeats every key ~11,000 times and does not fit. Declaring the column
order once and shipping arrays of numbers does, with room to spare.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from functools import lru_cache
import json
from pathlib import Path
from typing import Any
from typing import Sequence

from syndicate.features.nfl.fantasy_projection import PlayerProjection


ARTIFACT_VERSION = 1

#: Stat keys carried per projected line, in the order the numeric arrays use.
#: Anything ``score_stat_line`` reads must be here or it silently scores zero,
#: so this is derived from the scorer's own vocabulary rather than hand-listed.
STAT_COLUMNS: tuple[str, ...] = (
    "passing_yards",
    "passing_tds",
    "interceptions",
    "passing_2pt",
    "rushing_yards",
    "rushing_tds",
    "rushing_2pt",
    "receptions",
    "receiving_yards",
    "receiving_tds",
    "receiving_2pt",
    "fumbles_lost",
    "fg_made_0_39",
    "fg_made_40_49",
    "fg_made_50_plus",
    "fg_missed",
    "pat_made",
    "pat_missed",
    "dst_sacks",
    "dst_interceptions",
    "dst_fumble_recoveries",
    "dst_safeties",
    "dst_touchdowns",
    "dst_blocked_kicks",
    "dst_points_allowed",
    # Not scored, but shown on the surface and cheap to carry.
    "targets",
    "carries",
    "pass_attempts",
)


def artifact_path(season: int) -> Path:
    from syndicate.features.nfl.sources import default_nfl_source_root

    return default_nfl_source_root() / "fantasy" / f"nfl_fantasy_projections_{season}.json"


def artifact_output_path(season: int) -> Path:
    """Where the WORKER writes it -- the mounted disk, not the checkout."""
    from syndicate.features.nfl.sources import nfl_artifact_output_root

    return nfl_artifact_output_root() / "fantasy" / f"nfl_fantasy_projections_{season}.json"


#: Decimal places for a PER-GAME stat. Four, not two, and the difference is
#: measurable: a per-game touchdown rate is ~0.3, so 2dp leaves up to 0.005 of
#: error, which a 6-point touchdown over a 17-game season turns into ~0.5
#: points per field -- about 1 point on a 300-point projection. 4dp drops that
#: below 0.01 and costs ~0.4 MB against a 12 MB publish ceiling.
_STAT_DECIMALS = 4


def _round(value: float) -> float:
    return round(float(value), _STAT_DECIMALS)


def _multiplier(entry: PlayerProjection) -> float:
    """What the engine multiplied a PER-GAME line by to produce this row.

    READ OFF THE ROW, NOT RE-DERIVED. ``fantasy_points`` and
    ``points_per_game`` are both produced by the engine with the same scale
    factor, so their ratio IS that factor for every row shape.

    The first version re-implemented the rule instead ("season rows scale by
    games, weekly rows by games/17") and was wrong for exactly one shape:
    weekly D/ST rows scale by 1.0, because `_project_dst` sets `games = 1.0`
    for a single week rather than carrying a season estimate. That produced a
    ~1.1-point error on weekly defenses -- 5% of a weekly score -- while season
    rows looked perfect. Re-deriving a rule the data already states is how a
    special case gets missed.
    """
    if entry.points_per_game:
        return float(entry.fantasy_points) / float(entry.points_per_game)
    return float(entry.games) if entry.week is None else 1.0


def _encode_rows(projections: Sequence[PlayerProjection], index: dict[str, int]) -> list[list[Any]]:
    """Store the PER-GAME line plus its multiplier, never the scaled line.

    SCORING IS NOT LINEAR IN THE STAT LINE, so the scale a line is stored at is
    load-bearing. Every term is linear except `dst_points_allowed`, which runs
    through the points-allowed ladder -- and a ladder applied to a SEASON total
    is meaningless. Storing a season line and scoring it read a defense as
    having allowed ~380 points in one game (bottom band, -5) instead of ~22
    (+0 to +1). Measured: an 8.49-point error on every D/ST, identical under all
    three scoring profiles, which is the tell that the term is
    scoring-independent.

    Per-game storage makes the decode exact for linear and non-linear terms
    alike: score the per-game line, then multiply the POINTS.
    """
    rows: list[list[Any]] = []
    for entry in projections:
        position = index.get(entry.player_id)
        if position is None:
            continue
        scale = _multiplier(entry)
        line = [
            position,
            _round(entry.games),
            round(scale, 4),
            _round(entry.points_per_game_sd),
        ]
        line.extend(
            _round(entry.stat_line.get(name, 0.0) / scale if scale else 0.0)
            for name in STAT_COLUMNS
        )
        rows.append(line)
    return rows


def build_artifact_payload(
    season: int,
    season_projections: Sequence[PlayerProjection],
    weekly: dict[int, Sequence[PlayerProjection]],
    basis: dict[str, Any],
) -> dict[str, Any]:
    """Serialise one season plus every week into the published shape."""
    identities: list[dict[str, Any]] = []
    index: dict[str, int] = {}
    for entry in season_projections:
        if entry.player_id in index:
            continue
        index[entry.player_id] = len(identities)
        identities.append(
            {
                "id": entry.player_id,
                "name": entry.name,
                "team": entry.team,
                "pos": entry.position,
                "basis": entry.basis,
            }
        )
    # A player can appear in a week and not in the season list only if the
    # season run dropped him as near-zero; keep him rather than lose the row.
    for rows in weekly.values():
        for entry in rows:
            if entry.player_id in index:
                continue
            index[entry.player_id] = len(identities)
            identities.append(
                {
                    "id": entry.player_id,
                    "name": entry.name,
                    "team": entry.team,
                    "pos": entry.position,
                    "basis": entry.basis,
                }
            )

    return {
        "artifact_version": ARTIFACT_VERSION,
        "season": season,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "engine": "nfl_fantasy_opportunity_v1",
        "basis": basis,
        "row_columns": ["player", "games", "multiplier", "ppg_sd"] + list(STAT_COLUMNS),
        "row_note": "stat columns are PER-GAME; multiply POINTS by `multiplier`, never the line before scoring",
        "players": identities,
        "season_rows": _encode_rows(season_projections, index),
        "week_rows": {
            str(week): _encode_rows(rows, index) for week, rows in sorted(weekly.items())
        },
        "week_opponents": {
            str(week): {
                entry.player_id: entry.opponent for entry in rows if entry.opponent
            }
            for week, rows in sorted(weekly.items())
        },
    }


@dataclass(frozen=True)
class ProjectionArtifact:
    """A published projection, decoded but NOT yet scored."""

    season: int
    generated_at: str
    basis: dict[str, Any]
    players: list[dict[str, Any]]
    season_rows: list[list[Any]]
    week_rows: dict[int, list[list[Any]]]
    week_opponents: dict[int, dict[str, str]]
    path: str

    def rows_for(self, week: int | None) -> list[list[Any]]:
        if week is None:
            return self.season_rows
        return self.week_rows.get(week, [])

    def to_projections(self, week: int | None) -> list[PlayerProjection]:
        """Decode back into ``PlayerProjection`` objects, unscored.

        ``fantasy_points``/``floor``/``ceiling`` are left at zero here on
        purpose -- they depend on the scoring profile, which is a request-time
        choice. ``fantasy.score_projections`` fills them in.
        """
        out: list[PlayerProjection] = []
        opponents = self.week_opponents.get(week or -1, {})
        for row in self.rows_for(week):
            identity = self.players[int(row[0])]
            per_game = {
                name: float(row[4 + offset]) for offset, name in enumerate(STAT_COLUMNS)
            }
            # `dst_points_allowed` IS DST-ONLY, AND THIS LINE IS NOT COSMETIC.
            #
            # Scoring is linear in every stat except this one, which runs
            # through the points-allowed ladder -- and the ladder's value AT
            # ZERO is the shutout bonus, +10. A columnar artifact makes every
            # column present for every row, so decoding a quarterback with
            # `dst_points_allowed: 0.0` awarded him ten points for a shutout he
            # was not involved in. Measured: EVERY row 10.1 too high, uniformly,
            # across all six positions.
            #
            # The engine's own lines simply do not carry the key for offensive
            # players, and `score_stat_line` correctly distinguishes absent from
            # zero. Restoring that distinction here is the fix. It is the
            # `.get(key, neutral_default)` failure in `model_engine_standard.md`
            # s4.2 wearing a different hat: 0.0 LOOKED neutral and was the most
            # rewarded value on the ladder.
            if identity["pos"] != "DST":
                per_game.pop("dst_points_allowed", None)
            out.append(
                PlayerProjection(
                    player_id=identity["id"],
                    name=identity["name"],
                    team=identity["team"],
                    position=identity["pos"],
                    season=self.season,
                    games=float(row[1]),
                    # `stat_line` is restored to the SCALED line the surface
                    # displays; `per_game_line` rides in `basis` so the scorer
                    # can evaluate the ladder at the right scale.
                    stat_line={name: value * float(row[2]) for name, value in per_game.items()},
                    fantasy_points=0.0,
                    points_per_game=0.0,
                    points_per_game_sd=float(row[3]),
                    season_points_sd=0.0,
                    floor=0.0,
                    ceiling=0.0,
                    basis=dict(identity.get("basis") or {})
                    | {"_per_game_line": per_game, "_multiplier": float(row[2])},
                    week=week,
                    opponent=opponents.get(identity["id"]),
                )
            )
        return out


def _artifact_fingerprint(path: Path) -> tuple[float, int] | None:
    """``(mtime, size)`` for the artifact, or ``None`` when it is absent."""
    try:
        stat = path.stat()
    except OSError:
        return None
    return (stat.st_mtime, stat.st_size)


def load_projection_artifact(season: int) -> ProjectionArtifact | None:
    """Read the published artifact, or ``None`` when it is not on this substrate.

    ``None`` is a first-class answer and callers must render a degraded state
    from it. It must never become an exception, and it must never trigger an
    on-request rebuild -- both were how the pre-artifact version 500'd on
    production (``CLAUDE.md``: "If data is missing at request time, the correct
    behavior is a degraded/empty UI state, not an on-request backfill").

    **THE CACHE IS KEYED ON THE FILE'S FINGERPRINT, NOT ON THE SEASON, AND THAT
    IS THE WHOLE POINT.** A plain ``@lru_cache(season)`` here is actively wrong
    on this service: artifacts arrive by being PUSHED from the worker at any
    moment, so a web process that answered one request before the first publish
    caches ``None`` and keeps serving the empty state until it restarts.
    Measured on production 2026-08-21 -- the publish returned `PUBLISH_OK`,
    `/api/ops/artifacts/export` confirmed the file on disk with count 1, and
    `/nfl/api/fantasy/draft-board` still reported `available: false`. Nothing
    was wrong except that the answer had been memoised before it existed.
    Fingerprinting means the next publish invalidates the entry by itself.
    """
    path = artifact_path(season)
    fingerprint = _artifact_fingerprint(path)
    if fingerprint is None:
        return None
    return _load_projection_artifact(season, str(path), fingerprint)


@lru_cache(maxsize=8)
def _load_projection_artifact(
    season: int, path_text: str, fingerprint: tuple[float, int]
) -> ProjectionArtifact | None:
    path = Path(path_text)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if int(payload.get("artifact_version") or 0) != ARTIFACT_VERSION:
        return None
    return ProjectionArtifact(
        season=int(payload.get("season") or season),
        generated_at=str(payload.get("generated_at") or ""),
        basis=payload.get("basis") or {},
        players=list(payload.get("players") or []),
        season_rows=list(payload.get("season_rows") or []),
        week_rows={int(key): value for key, value in (payload.get("week_rows") or {}).items()},
        week_opponents={
            int(key): dict(value) for key, value in (payload.get("week_opponents") or {}).items()
        },
        path=str(path),
    )


load_projection_artifact.cache_clear = _load_projection_artifact.cache_clear  # type: ignore[attr-defined]


def artifact_substrate(season: int) -> dict[str, Any]:
    path = artifact_path(season)
    artifact = load_projection_artifact(season)
    return {
        "path": str(path),
        "exists": path.is_file(),
        "bytes": path.stat().st_size if path.is_file() else 0,
        "generated_at": artifact.generated_at if artifact else None,
        "players": len(artifact.players) if artifact else 0,
        "weeks": sorted(artifact.week_rows) if artifact else [],
    }
