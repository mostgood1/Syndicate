"""Per-segment point/margin histograms from the football sim's `quarter_log`.

WHAT THIS EXISTS TO STOP. `simulate_game`
(``syndicate/features/football/sim_engine/smartsim2/game_simulator.py``)
already computes a per-quarter record for every seed -- `home_points`,
`away_points`, `drive_count`, `possession_count`, `start_clock`, `end_clock`
-- and both production generators
(``scripts/generate_smartsim2_nfl_projections.py``,
``scripts/generate_smartsim2_ncaaf_projections.py``) threw ALL of it away,
keeping only ``output.final_score["home"]`` / ``["away"]``. The persisted
artifact was 8 scalars per game and carried no distribution of any kind --
not even the full-game margin histogram the sim had in hand. Half and quarter
markets could not be priced or measured, and the reason was a discard, not a
modelling gap.

This module is the accumulator only. It changes NO served number: nothing
here is read by a pricer yet, and the projection CSV is untouched (see
``smartsim2_projection.write_segment_distributions_artifact``, a SIDECAR).

THE PACKING MIRRORS MLB EXACTLY, on purpose. MLB's sim writes
``segments.{full,first1,first3,first5}``, each with ``total_runs_dist`` /
``run_margin_dist`` as ``{integer outcome: count}`` maps summing to the sim
count, and ``syndicate/features/shared/prop_projections.py`` walks those maps
to price segment totals and spreads. The football names generalise the two
that are sport-specific (``total_points_dist``, ``margin_dist`` -- the latter
is already the soccer name, see ``soccer_live_gameline_source.py``), and the
container shape (``{"sims": N, "segments": {...}}``, ``full`` sitting INSIDE
``segments``) is byte-for-byte the same idea, so a future pricer reuses the
existing walk instead of growing a second one.

MARGIN IS HOME-POSITIVE (``home - away``), matching ``run_margin_dist`` and
``margin_dist``. A pricer's sign convention is the thing most expensive to get
wrong (`#262`), so it is not re-decided here.

OVERTIME -- THE ONE PLACE THIS IS NOT A STRAIGHT COPY OF `quarter_log`.
``simulate_game`` DOES simulate overtime (its OT block sits after the quarter
loop), but it appends nothing to ``quarter_log``: OT drives reach
``drive_log`` / ``possession_log`` and the scoreboard, never a quarter record.
So summing ``quarter_log`` gives the REGULATION score, and the residual
``final_score - sum(quarter_log)`` is exactly the overtime points -- provided
the sim started at kickoff with an empty scoreboard, which every pregame
generator does. That residual is what lets ``h2`` be graded-consistent:

    ``segment_actuals.SEGMENT_PERIODS["nfl"]["h2"] == (3, 4, None)``

where ``None`` means *every* overtime period. This module matches that map
exactly -- ``h1 = q1+q2``, ``h2 = q3+q4+OT`` -- because a distribution binned
differently from the way it is graded is worse than no distribution at all.

A resumed sim (``initial_quarter > 1`` or a carried-in score) cannot separate
overtime from the carried-in points that way, so it is REFUSED by name
(``add()`` returns False and the game is counted in ``skipped``) rather than
silently mislabelled. Live re-sims are the only caller in that state and they
do not build these.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any
from typing import Mapping
from typing import Sequence

# Env flag. ABSENT => OFF => the generators build no accumulator, write no
# sidecar, and the projection CSV they do write is byte-identical to the one
# they wrote before this module existed. That equality is the lane's
# falsification test (`tests/test_football_segment_distributions.py`).
SEGMENT_DISTRIBUTIONS_ENV = "SYNDICATE_FOOTBALL_SEGMENT_DISTRIBUTIONS"

DISTRIBUTION_VERSION = 1
SEGMENT_SOURCE = "quarter_log"

# `full` lives inside `segments` beside the rest, as it does in MLB, so a
# consumer indexes one table rather than special-casing the whole game.
SEGMENT_KEYS: tuple[str, ...] = ("full", "q1", "q2", "q3", "q4", "h1", "h2")

# The quarters each segment spans. Mirrors `segment_actuals._FOOTBALL_SEGMENTS`
# with `None` meaning "every overtime period"; `full` is not in that map (it is
# not a segment there) and is spelled out here because this artifact carries it.
_SEGMENT_QUARTERS: Mapping[str, tuple[int | None, ...]] = {
    "q1": (1,),
    "q2": (2,),
    "q3": (3,),
    "q4": (4,),
    "h1": (1, 2),
    "h2": (3, 4, None),
    "full": (1, 2, 3, 4, None),
}


def segment_distributions_enabled(environ: Mapping[str, str] | None = None) -> bool:
    """OFF unless `SYNDICATE_FOOTBALL_SEGMENT_DISTRIBUTIONS` is truthy.

    Absent is OFF, deliberately and checked against the code's own default
    (CLAUDE.md: *absent != off* is a real failure mode -- the same edit is a
    no-op in one direction and a behaviour change in the other). Nothing reads
    this artifact yet, so OFF costs nothing and ON costs only bytes.
    """
    source = os.environ if environ is None else environ
    raw = str(source.get(SEGMENT_DISTRIBUTIONS_ENV) or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _quarter_points(quarter_log: Sequence[Mapping[str, Any]]) -> dict[int, tuple[int, int]]:
    out: dict[int, tuple[int, int]] = {}
    for entry in quarter_log or ():
        try:
            quarter = int(entry["quarter"])
            home = int(entry["home_points"])
            away = int(entry["away_points"])
        except (KeyError, TypeError, ValueError):
            continue
        prior_home, prior_away = out.get(quarter, (0, 0))
        out[quarter] = (prior_home + home, prior_away + away)
    return out


def segment_points(output: Any) -> dict[str, tuple[int, int]] | None:
    """`{segment: (home_points, away_points)}` for one simulated game.

    Returns None -- never a partially-filled dict -- when the output cannot be
    binned the way `segment_actuals` grades it: a resumed sim, a carried-in
    score, or a quarter log that does not cover regulation. See the module
    docstring; refusing by name beats a silently mislabelled `h2`.

    A quarter in which nobody scored yields ``(0, 0)``, which becomes a
    populated ``0`` bucket downstream. An ABSENT key and a zero bucket mean
    different things and only one of them is true here.
    """
    quarter_log = getattr(output, "quarter_log", None)
    final_score = getattr(output, "final_score", None)
    input_state = getattr(output, "input_state", None) or {}
    if not quarter_log or not isinstance(final_score, Mapping):
        return None

    # Only a from-kickoff, empty-scoreboard run can attribute the residual to
    # overtime. Anything else is refused.
    try:
        initial_quarter = int(input_state.get("initial_quarter", 1) or 1)
        initial_home = int(input_state.get("initial_score_home", 0) or 0)
        initial_away = int(input_state.get("initial_score_away", 0) or 0)
        regulation_quarters = int(input_state.get("quarters", 4) or 4)
    except (AttributeError, TypeError, ValueError):
        return None
    if initial_quarter != 1 or initial_home or initial_away:
        return None

    per_quarter = _quarter_points(quarter_log)
    if any(quarter not in per_quarter for quarter in range(1, regulation_quarters + 1)):
        return None
    if regulation_quarters != 4:
        # The segment map is written in quarters 1-4. A non-standard period
        # count would bin `h1`/`h2` against a scheme nobody grades.
        return None

    try:
        final_home = int(final_score["home"])
        final_away = int(final_score["away"])
    except (KeyError, TypeError, ValueError):
        return None

    regulation_home = sum(per_quarter[q][0] for q in range(1, 5))
    regulation_away = sum(per_quarter[q][1] for q in range(1, 5))
    # THE OVERTIME RESIDUAL. `simulate_game` scores overtime onto the
    # scoreboard without appending a quarter record, so this difference is the
    # OT points and nothing else (the empty-scoreboard guard above is what
    # makes that true). Negative would mean the invariant broke; refuse.
    overtime_home = final_home - regulation_home
    overtime_away = final_away - regulation_away
    if overtime_home < 0 or overtime_away < 0:
        return None
    per_quarter[0] = (overtime_home, overtime_away)  # 0 == "the overtime bucket"

    out: dict[str, tuple[int, int]] = {}
    for segment, quarters in _SEGMENT_QUARTERS.items():
        home = 0
        away = 0
        for quarter in quarters:
            key = 0 if quarter is None else int(quarter)
            quarter_home, quarter_away = per_quarter.get(key, (0, 0))
            home += quarter_home
            away += quarter_away
        out[segment] = (home, away)
    return out


def game_has_overtime(output: Any) -> bool:
    """True when this simulated game went past regulation."""
    points = segment_points(output)
    if points is None:
        return False
    regulation = sum(points[key][0] + points[key][1] for key in ("q1", "q2", "q3", "q4"))
    full_home, full_away = points["full"]
    return (full_home + full_away) != regulation


@dataclass
class _SegmentCounts:
    total_points_dist: dict[int, int] = field(default_factory=dict)
    margin_dist: dict[int, int] = field(default_factory=dict)
    home_points_sum: int = 0
    away_points_sum: int = 0

    def add(self, home: int, away: int) -> None:
        total = home + away
        margin = home - away
        self.total_points_dist[total] = self.total_points_dist.get(total, 0) + 1
        self.margin_dist[margin] = self.margin_dist.get(margin, 0) + 1
        self.home_points_sum += home
        self.away_points_sum += away


@dataclass
class FootballSegmentAccumulator:
    """One per game. `add()` per seed, `payload()` once.

    Holds counts, never the per-seed draws: 14 small int->int maps for a whole
    game regardless of seed count, which is why this is affordable to run
    inside the 4 GB refresh-worker's generator loop. Measured cost is in the
    lane report.
    """

    sims: int = 0
    skipped: int = 0
    overtime_sims: int = 0
    _segments: dict[str, _SegmentCounts] = field(default_factory=dict)
    _seeds_seen: list[int] = field(default_factory=list)

    def add(self, output: Any) -> bool:
        """Fold one `SmartSim2SimulationOutput` in. False == refused, counted."""
        points = segment_points(output)
        if points is None:
            self.skipped += 1
            return False
        for segment in SEGMENT_KEYS:
            home, away = points[segment]
            bucket = self._segments.get(segment)
            if bucket is None:
                bucket = _SegmentCounts()
                self._segments[segment] = bucket
            bucket.add(home, away)
        regulation = sum(points[key][0] + points[key][1] for key in ("q1", "q2", "q3", "q4"))
        if sum(points["full"]) != regulation:
            self.overtime_sims += 1
        self.sims += 1
        seed = getattr(output, "seed", None)
        if isinstance(seed, int):
            self._seeds_seen.append(seed)
        return True

    def _seed_stamp(self) -> dict[str, Any]:
        """WHICH seeds produced this block.

        A single scalar cannot name a 300-seed sweep, and "seed: 300" would
        read as *the* seed rather than the last of a range -- so the stamp is
        the range plus whether it is the contiguous 1..n the generators use.
        `sequential=false` is the flag that says "you cannot reproduce this
        from first/last alone".
        """
        if not self._seeds_seen:
            return {"first": None, "last": None, "count": 0, "sequential": False}
        first = self._seeds_seen[0]
        last = self._seeds_seen[-1]
        sequential = self._seeds_seen == list(range(first, first + len(self._seeds_seen)))
        return {"first": first, "last": last, "count": len(self._seeds_seen), "sequential": sequential}

    def payload(self) -> dict[str, Any] | None:
        """The persisted block, or None when nothing could be folded in."""
        if not self.sims:
            return None
        denominator = float(self.sims)
        segments: dict[str, Any] = {}
        for segment in SEGMENT_KEYS:
            bucket = self._segments[segment]
            entry: dict[str, Any] = {
                # `{outcome: count}`, counts summing to `sims` -- the MLB
                # packing, walked by prop_projections._dist_prob_over/_dist_mean.
                "total_points_dist": dict(sorted(bucket.total_points_dist.items())),
                "margin_dist": dict(sorted(bucket.margin_dist.items())),
                "home_points_mean": round(bucket.home_points_sum / denominator, 4),
                "away_points_mean": round(bucket.away_points_sum / denominator, 4),
            }
            if segment == "h2":
                # NOT a silent regulation-only bin. See the module docstring:
                # `h2` here spans (3, 4, every OT period), which is exactly
                # `segment_actuals.SEGMENT_PERIODS[sport]["h2"]`.
                entry["h2_regulation_only"] = False
            segments[segment] = entry
        return {
            "distribution_version": DISTRIBUTION_VERSION,
            "segment_source": SEGMENT_SOURCE,
            "sims": self.sims,
            "seed": self._seed_stamp(),
            "skipped_sims": self.skipped,
            "overtime_sims": self.overtime_sims,
            "segments": segments,
        }


def segment_distributions_artifact_path(*, season: int, week: int, data_root: Path) -> Path:
    """A SIDECAR beside `smartsim2_projections_{season}_wk{week}.csv`.

    Not a new column on that CSV, and the choice is load-bearing: the CSV is
    read by the live re-sim, the blend, the performance tracker and the board,
    and a JSON-in-a-cell column would change its bytes for every consumer to
    buy nothing any of them read. Same shape as
    `smartsim2_ratings_{season}_wk{week}.json`, which exists next door for the
    same reason.
    """
    return data_root / f"smartsim2_segment_distributions_{season}_wk{week}.json"


def write_segment_distributions_artifact(
    blocks: Mapping[str, Mapping[str, Any]],
    *,
    season: int,
    week: int,
    data_root: Path,
) -> Path:
    """`{game_id: block}` plus the run's own stamp."""
    path = segment_distributions_artifact_path(season=season, week=week, data_root=data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": DISTRIBUTION_VERSION,
        "season": season,
        "week": week,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "games": {str(game_id): block for game_id, block in sorted(blocks.items())},
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=False), encoding="utf-8")
    return path


def read_segment_distributions_artifact(*, season: int, week: int, data_root: Path) -> dict[str, Any]:
    """`{game_id: block}`, or {} when absent/unreadable.

    Never raises: this artifact is optional by construction (the flag defaults
    OFF), so an absent file is the NORMAL state and must not be able to break a
    caller that merely asked.
    """
    path = segment_distributions_artifact_path(season=season, week=week, data_root=data_root)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    games = payload.get("games") if isinstance(payload, Mapping) else None
    if not isinstance(games, Mapping):
        return {}
    return {str(game_id): block for game_id, block in games.items()}


# SIM WRITE HISTORY -- todo #807, lane `ncaaf-sim-write-history`.
#
# WHY. The generator rewrites `smartsim2_projections_<s>_wk<w>.csv` and its
# sidecar ONCE A DAY through the week (fleet log 11-06..11-14: one write per
# day at ~16:00Z, both sports), so only the week's LAST write survives. A
# Tuesday or early-Saturday game was priced off a write that is gone by the
# time anyone grades it: todo #805's NCAAF segment grade had to refuse 3,485
# of 6,467 quoted segment markets as `sidecar_written_after_kickoff`, and kept
# 161 of 362 games. A dated copy of every write lets a grader take, per game,
# the last write before its kickoff -- the file the board was serving.
#
# WHERE. `<SYNDICATE_DATA_ROOT>/sim_history/<sport>/`, OUTSIDE every sport
# root, on purpose: `artifact_manifests._load_scanned_manifest` rglobs the
# whole `<sport>_source` tree and files any name containing "projection" or
# "sim" as a PREDICTION, dated from its name -- a copy stamped 20261114 would
# read as a 2026-11-14 prediction. The non-recursive weekly globs
# (`ncaaf/cards.py`, `blueprints/ops.py`, `build_ncaaf_pick_ledger.py`) never
# see it either, and no `artifact_retention` rule matches it, so it is kept.
# NOT in `HOT_ARTIFACT_PATTERNS`: nothing on web reads it; it is a grading
# record read offline from the fleet's disk.
#
# WHAT. One write = the CSV and the sidecar, gzipped, under ONE stamp taken
# from the sidecar's own `generated_at`. The CSV goes first and the sidecar
# second, each by an atomic rename, so a reader that pairs by stamp never sees
# half a write. A write whose sidecar `games` and CSV rows (less the per-row
# `generated_at`) equal the newest kept copy of that week adds nothing: that
# copy already holds what the board served.
SIM_HISTORY_DIRNAME = "sim_history"
_REPO_ROOT = Path(__file__).resolve().parents[3]


def sim_history_dir(*, sport: str, data_root: Path | None = None) -> Path:
    """`<SYNDICATE_DATA_ROOT>/sim_history/<sport>` (repo `data/` when the env is unset)."""
    if data_root is None:
        override = str(os.environ.get("SYNDICATE_DATA_ROOT") or "").strip()
        data_root = Path(override).expanduser() if override else _REPO_ROOT / "data"
    return Path(data_root) / SIM_HISTORY_DIRNAME / sport


def _history_stamp(generated_at: str) -> str:
    moment = datetime.fromisoformat(str(generated_at).replace("Z", "+00:00"))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def sim_history_names(*, season: int, week: int, stamp: str) -> tuple[str, str]:
    """`(csv_name, sidecar_name)` of one kept write."""
    return (
        f"smartsim2_projections_{season}_wk{week}.{stamp}.csv.gz",
        f"smartsim2_segment_distributions_{season}_wk{week}.{stamp}.json.gz",
    )


def _csv_rows_less_stamp(data: bytes) -> list[dict[str, str]]:
    import csv
    import io

    rows = list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))
    for row in rows:
        row.pop("generated_at", None)
    return rows


def _write_gzip_atomic(path: Path, data: bytes) -> None:
    import gzip

    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(gzip.compress(data, mtime=0))
    os.replace(tmp, path)


def archive_sim_write(
    *,
    projections_csv: Path,
    sidecar: Path,
    season: int,
    week: int,
    history_dir: Path,
) -> Path | None:
    """Keep one dated copy of this week's write. Returns the kept sidecar's path,
    or None when the newest kept copy of the week already holds the same content."""
    import gzip

    sidecar_bytes = Path(sidecar).read_bytes()
    csv_bytes = Path(projections_csv).read_bytes()
    payload = json.loads(sidecar_bytes.decode("utf-8"))
    stamp = _history_stamp(payload["generated_at"])
    csv_name, sidecar_name = sim_history_names(season=season, week=week, stamp=stamp)
    history_dir = Path(history_dir)
    history_dir.mkdir(parents=True, exist_ok=True)
    if (history_dir / sidecar_name).exists():
        return None  # this exact write is already kept
    # `..._wk1.` cannot match `..._wk10.`: the dot ends the week number. The
    # fixed-width stamp sorts as time.
    prefix = f"smartsim2_segment_distributions_{season}_wk{week}."
    stamps = sorted(p.name[len(prefix): -len(".json.gz")] for p in history_dir.glob(prefix + "*.json.gz"))
    if stamps:
        prior_csv_name, prior_sidecar_name = sim_history_names(season=season, week=week, stamp=stamps[-1])
        try:
            prior = json.loads(gzip.decompress((history_dir / prior_sidecar_name).read_bytes()).decode("utf-8"))
            prior_rows = _csv_rows_less_stamp(gzip.decompress((history_dir / prior_csv_name).read_bytes()))
        except (OSError, ValueError, EOFError):
            prior, prior_rows = None, None
        if (
            isinstance(prior, Mapping)
            and prior.get("games") == payload.get("games")
            and prior_rows == _csv_rows_less_stamp(csv_bytes)
        ):
            return None
    _write_gzip_atomic(history_dir / csv_name, csv_bytes)
    _write_gzip_atomic(history_dir / sidecar_name, sidecar_bytes)
    return history_dir / sidecar_name


__all__ = [
    "DISTRIBUTION_VERSION",
    "FootballSegmentAccumulator",
    "SEGMENT_DISTRIBUTIONS_ENV",
    "SEGMENT_KEYS",
    "SEGMENT_SOURCE",
    "SIM_HISTORY_DIRNAME",
    "archive_sim_write",
    "game_has_overtime",
    "read_segment_distributions_artifact",
    "segment_distributions_artifact_path",
    "segment_distributions_enabled",
    "segment_points",
    "sim_history_dir",
    "sim_history_names",
    "write_segment_distributions_artifact",
]
