"""NFL game-line projections for the Layer 1 board (`#365`).

Measured live 2026-08-11: NFL rendered **171 rows across 16 games at 0.0%
projection coverage**. Identity, line and odds were complete; the model column
was empty on every row. `board_enrichment.attach_projections` has branches for
wnba, soccer and mlb and falls through for everything else, so NFL had no
projection path at all.

THE SIM IS RICHER THAN WNBA'S, AND THAT CHANGES WHAT IS HONEST TO EMIT.
`smartsim2_preseason_projections_<season>_wk<week>.csv` carries

    margin_mean  total_mean  margin_stdev  total_stdev  home_win_rate

Means AND dispersion, measured across 200-300 seeds. So unlike WNBA -- which
ships means only, and where inventing P(over) would require a variance nobody
measured (`#242`, `#364`) -- NFL can emit real probability-space numbers from
the model's own spread. That is a derivation, not an assumption.

WEEK RESOLUTION IS DELIBERATELY NOT USED.
Two independent reasons, either sufficient:

  - Preseason and regular season both number their weeks from 1, in separate
    file series. "Week 2" is ambiguous without also knowing the season phase.
  - NFL's week resolution is a known-bad input: `current_week.json` reads
    `season 2026, week 1` today, while the games on the board are PRESEASON
    week 2. An earlier audit already recorded NFL week self-pinning to 1.

So this joins on (game date, home, away) instead, resolved through the schedule
files, and never asks what week it is. A wrong week silently returns another
game's projection -- a real number against the wrong fixture.

WHAT IT DELIBERATELY WILL NOT DO: spread probabilities.
A board spreads row carries `line: 6.5` with `sides: ["away", "home"]` and
nothing that says which side the 6.5 belongs to. P(cover) therefore cannot be
computed without guessing the sign, and a guessed sign inverts the edge while
looking entirely plausible. Spreads get the margin mean and `edge_vs_line`; the
probability stays null with a stated reason until that convention is pinned
down. Totals are unambiguous (over means total > line) and h2h is measured
directly by the sim, so both get real probabilities.
"""

from __future__ import annotations

import csv
import glob
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from syndicate.features.shared.team_aliases import teams_match
from syndicate.features.shared.source_roots import preferred_source_roots
from syndicate.features.shared.nfl_preseason_calibration import (
    calibrated_total,
    is_preseason_profile,
    skill_note,
)


def _as_float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _norm(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _normal_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


@dataclass
class NflGameProjectionIndex:
    by_date_teams: dict[tuple[str, str, str], dict[str, Any]] = field(default_factory=dict)
    games: int = 0
    sources: list[str] = field(default_factory=list)

    def lookup(self, game_date: str, home: Any, away: Any) -> dict[str, Any] | None:
        date_key = str(game_date or "")[:10]
        if not date_key:
            return None
        h, a = _norm(home), _norm(away)
        if not (h and a):
            return None
        direct = self.by_date_teams.get((date_key, h, a))
        if direct is not None:
            return direct
        # The board carries full names ("Cincinnati Bengals"); the sim carries
        # tri-codes ("CIN"). `teams_match` bridges them (verified 8/8 on this
        # slate). Restricted to the SAME DATE, and only when exactly one
        # candidate matches -- an ambiguous match is a blank, never a guess.
        hits = [
            entry
            for (d, index_home, index_away), entry in self.by_date_teams.items()
            if d == date_key
            and teams_match("nfl", h, index_home)
            and teams_match("nfl", a, index_away)
        ]
        return hits[0] if len(hits) == 1 else None


def _source_roots() -> list[Path]:
    return preferred_source_roots(
        __file__, env_var="SYNDICATE_NFL_SOURCE_ROOT", local_dir_name="nfl_source"
    )


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return list(csv.DictReader(text.splitlines()))


def load_nfl_game_projections(selected_date: str) -> NflGameProjectionIndex:
    """Index SmartSim2 projections by (game date, home, away).

    Reads BOTH the preseason and regular-season file series for the season, and
    both schedule files, because the board does not know or care which phase it
    is showing -- it only knows the date.
    """
    index = NflGameProjectionIndex()
    season = str(selected_date or "")[:4]
    if not season.isdigit():
        return index

    # game_id -> gameday, from whichever schedule files exist.
    gameday_by_id: dict[str, str] = {}
    home_by_id: dict[str, str] = {}
    away_by_id: dict[str, str] = {}
    for root in _source_roots():
        for name in (f"schedule_preseason_{season}.csv", f"schedule_{season}.csv"):
            for row in _read_csv_rows(root / name):
                gid = str(row.get("game_id") or "").strip()
                day = str(row.get("gameday") or "").strip()[:10]
                if gid and day:
                    gameday_by_id.setdefault(gid, day)
                    home_by_id.setdefault(gid, _norm(row.get("home_team")))
                    away_by_id.setdefault(gid, _norm(row.get("away_team")))

    seen_files: set[str] = set()
    for root in _source_roots():
        patterns = (
            str(root / f"smartsim2_preseason_projections_{season}_wk*.csv"),
            str(root / f"smartsim2_projections_{season}_wk*.csv"),
        )
        for pattern in patterns:
            for path_text in sorted(glob.glob(pattern)):
                if Path(path_text).name in seen_files:
                    continue
                seen_files.add(Path(path_text).name)
                for row in _read_csv_rows(Path(path_text)):
                    gid = str(row.get("game_id") or "").strip()
                    day = gameday_by_id.get(gid, "")
                    home = _norm(row.get("home_team")) or home_by_id.get(gid, "")
                    away = _norm(row.get("away_team")) or away_by_id.get(gid, "")
                    if not (day and home and away):
                        # No date means no safe join -- a projection matched on
                        # teams alone can land on the wrong meeting of a pair
                        # that plays twice in a season.
                        continue
                    entry = {
                        "margin_mean": _as_float(row.get("margin_mean")),
                        "total_mean": _as_float(row.get("total_mean")),
                        "margin_stdev": _as_float(row.get("margin_stdev")),
                        "total_stdev": _as_float(row.get("total_stdev")),
                        "home_win_rate": _as_float(row.get("home_win_rate")),
                        "generated_at": str(row.get("generated_at") or "").strip(),
                        "profile": str(row.get("profile_name") or "").strip(),
                    }
                    index.by_date_teams[(day, home, away)] = entry
                index.sources.append(Path(path_text).name)
    index.games = len(index.by_date_teams)
    return index


def attach_nfl_game_projections(
    grid: Iterable[Mapping[str, Any]], index: NflGameProjectionIndex
) -> dict[str, Any]:
    """Stamp `projection` onto NFL full-game h2h/spreads/totals rows."""
    considered = 0
    attached = 0
    unmatched = 0
    non_full_segment = 0
    # One entry per GAME, not per row: a slate with eight alternate totals on one
    # fixture would otherwise count that fixture eight times and manufacture the
    # unanimity the warning is meant to detect.
    total_edge_by_game: dict[tuple[str, str, str], float] = {}

    for row in grid:
        if str(row.get("kind") or "") == "prop":
            continue
        market = str(row.get("market") or "").strip().lower()
        if market not in {"h2h", "spreads", "totals"}:
            continue
        considered += 1
        if str(row.get("segment") or "full").strip().lower() not in {"", "full"}:
            # margin/total means are full-game; a quarter market is a different bet.
            non_full_segment += 1
            continue
        game_date = str(row.get("commence_time") or "")[:10]
        entry = index.lookup(game_date, row.get("home_team"), row.get("away_team"))
        if entry is None:
            unmatched += 1
            continue

        projection: dict[str, Any] | None = None
        if market == "h2h":
            prob = entry.get("home_win_rate")
            if prob is not None:
                projection = {
                    "model_prob_over": round(float(prob), 4),
                    "side": str(row.get("home_team") or "").strip(),
                    "projected": entry.get("margin_mean"),
                    "basis": "smartsim2_home_win_rate",
                    "source": "nfl_smartsim2",
                    "generated_at": entry.get("generated_at"),
                }
                note = skill_note(entry.get("profile"), "h2h")
                if note:
                    # `#367`: measured corr(projection, actual margin) = -0.047
                    # over 146 preseason games. `home_win_rate` derives from that
                    # margin model, so this probability carries no information.
                    # Shown WITH its skill rather than silently, because a bare
                    # 0.53 reads as a real read on the game.
                    projection["model_skill"] = note
        elif market == "totals":
            mean = entry.get("total_mean")
            stdev = entry.get("total_stdev")
            line = _as_float(row.get("line"))
            raw_mean = mean
            mean = calibrated_total(mean, entry.get("profile"))
            if mean is not None:
                projection = {
                    "projected": round(mean, 3),
                    "side": "over",
                    "basis": "smartsim2_total_mean",
                    "source": "nfl_smartsim2",
                    "generated_at": entry.get("generated_at"),
                    "model_prob_over": None,
                }
                if is_preseason_profile(entry.get("profile")):
                    # The raw model output stays visible next to the corrected
                    # one -- a calibration that hides what it changed is
                    # indistinguishable from a model that was always right.
                    projection["projected_raw"] = round(float(raw_mean), 3)
                    projection["calibrated"] = True
                    projection["calibration_points"] = round(float(raw_mean) - float(mean), 3)
                    projection["model_skill"] = skill_note(entry.get("profile"), "totals")
                if line is not None:
                    projection["edge_vs_line"] = round(mean - line, 3)
                    total_edge_by_game.setdefault(
                        (game_date, _norm(row.get("home_team")), _norm(row.get("away_team"))),
                        round(mean - line, 3),
                    )
                    # Real derivation, not an assumption: the stdev is the sim's
                    # own dispersion across its seeds. Over means total > line,
                    # which needs no side convention.
                    if stdev and stdev > 0:
                        projection["model_prob_over"] = round(
                            1.0 - _normal_cdf((line - mean) / stdev), 4
                        )
                        projection["basis"] = "smartsim2_total_normal"
        else:  # spreads
            mean = entry.get("margin_mean")
            line = _as_float(row.get("line"))
            if mean is not None:
                projection = {
                    "projected": round(mean, 3),
                    "side": str(row.get("home_team") or "").strip(),
                    "basis": "smartsim2_margin_mean",
                    "source": "nfl_smartsim2",
                    "generated_at": entry.get("generated_at"),
                    "model_prob_over": None,
                    "edge_vs_market_pct": None,
                    # See the module docstring: the row's `line` does not say
                    # which side it belongs to, and a guessed sign inverts the
                    # edge while looking plausible.
                    "probability_unavailable_reason": "spread row does not state which side its line belongs to",
                }
                if line is not None:
                    projection["edge_vs_line"] = round(mean - line, 3)

        if projection is None:
            continue
        row["projection"] = projection  # type: ignore[index]
        attached += 1

    coverage: dict[str, Any] = {
        "supported": True,
        "rows_considered": considered,
        "rows_with_projection": attached,
        "unmatched_game_rows": unmatched,
        "non_full_segment_rows": non_full_segment,
        "games_in_index": index.games,
        "source_artifacts": index.sources[:8],
    }
    warning = _slate_bias_warning(list(total_edge_by_game.values()))
    if warning:
        coverage["calibration_warning"] = warning
    return coverage


def _slate_bias_warning(edges: list[float]) -> dict[str, Any] | None:
    """A slate where EVERY edge points the same way is bias, not opportunity.

    Measured on the 2026 preseason slate the day this shipped: 16 of 16 totals
    projected OVER the market, mean +6.47, range +1.4 to +10.1. The cause is not
    subtle -- preseason starters play a fraction of the snaps, so real totals run
    far below regular-season levels, and `nfl_preseason_v1` was emitting
    regular-season-shaped means (41.9-47.6) against a market pricing 36.0-40.5.

    Unqualified, that renders as sixteen green +6.5 edges and reads as a
    goldmine. A model disagreeing with every price on the board in the same
    direction is the signature of a miscalibrated model, and the board should
    say so rather than let the reader discover it with money.

    Deliberately a WARNING and not a suppression: the projection is what the
    model actually says, and hiding it would be its own kind of lie. This makes
    the pattern impossible to miss instead of impossible to see.
    """
    if len(edges) < 6:
        return None
    positive = sum(1 for e in edges if e > 0)
    negative = sum(1 for e in edges if e < 0)
    if positive != len(edges) and negative != len(edges):
        return None
    mean_edge = sum(edges) / len(edges)
    if abs(mean_edge) < 1.0:
        return None
    return {
        "kind": "unanimous_total_edge",
        "games": len(edges),
        "direction": "over" if positive == len(edges) else "under",
        "mean_edge": round(mean_edge, 2),
        "detail": (
            f"every one of {len(edges)} totals projects "
            f"{'above' if positive == len(edges) else 'below'} the market "
            f"(mean {mean_edge:+.2f}). A model that disagrees with every price in "
            "the same direction is miscalibrated, not profitable."
        ),
    }
