from __future__ import annotations

import csv
import json
from pathlib import Path
import re
from typing import Any

from syndicate.features.shared.formatters import format_pct
from syndicate.features.shared.formatters import format_signed_price
from syndicate.features.shared.source_roots import preferred_artifact_roots
from syndicate.features.shared.source_roots import repo_root_from


_SNAPSHOT_RE = re.compile(r"^upcoming_recs_(?P<season>\d{4})_wk(?P<week>\d+)(?P<publish>_publish)?\.csv$")
_SMARTSIM2_PROJECTION_FILENAME_RE = re.compile(r"^smartsim2_projections_(?P<season>\d{4})_wk(?P<week>\d+)\.csv$")


def _source_roots() -> list[Path]:
    return preferred_artifact_roots(
        __file__,
        env_var="SYNDICATE_NFL_SOURCE_ROOT",
        local_dir_name="nfl_source",
    )


def _first_existing_root(roots: list[Path]) -> Path:
    for root in roots:
        try:
            normalized_parts = {part.lower() for part in root.parts}
            if "nfl_source" not in normalized_parts:
                continue
            if any(root.glob("upcoming_recs_*.csv")) or any(root.glob("upcoming_recs_*_publish.csv")):
                return root
        except OSError:
            continue
    return roots[0]


def default_nfl_source_root() -> Path:
    return _first_existing_root(_source_roots())


def data_path(*parts: str) -> Path:
    return default_nfl_source_root().joinpath(*parts)


def _count_csv_rows(path: Path) -> int:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return max(sum(1 for _ in handle) - 1, 0)
    except Exception:
        return 0


def tracked_week() -> dict[str, int] | None:
    path = data_path("current_week.json")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    try:
        season = int(payload.get("season"))
        week = int(payload.get("week"))
    except Exception:
        return None
    return {"season": season, "week": week}


def _smartsim2_standalone_seasons_and_weeks() -> dict[int, list[int]]:
    """Every real (season, week) with an already-generated real Monte
    Carlo projection artifact on disk -- independent of whether
    upcoming_recs_*.csv (the older recommendation-snapshot pipeline) has
    anything for that season. Mirrors
    syndicate.features.ncaaf.cards._smartsim2_standalone_seasons_and_weeks
    exactly, same real reason: upcoming_recs_*.csv is only ever refreshed
    for whichever season that older pipeline still tracks (confirmed:
    2025-only), so a newer season (2026) with real projections but no
    real recs snapshot needs a second, independent real signal."""
    source_root = default_nfl_source_root()
    result: dict[int, list[int]] = {}
    for path in source_root.glob("smartsim2_projections_*_wk*.csv"):
        match = _SMARTSIM2_PROJECTION_FILENAME_RE.match(path.name)
        if not match:
            continue
        season = int(match.group("season"))
        week = int(match.group("week"))
        result.setdefault(season, []).append(week)
    for season in result:
        result[season] = sorted(set(result[season]))
    return result


def week_summaries() -> list[dict[str, Any]]:
    grouped: dict[tuple[int, int], dict[str, Any]] = {}
    source_root = default_nfl_source_root()
    for path in sorted(source_root.glob("upcoming_recs_*.csv")):
        match = _SNAPSHOT_RE.match(path.name)
        if not match:
            continue
        season = int(match.group("season"))
        week = int(match.group("week"))
        is_publish = bool(match.group("publish"))
        key = (season, week)
        summary = grouped.setdefault(
            key,
            {
                "season": season,
                "week": week,
                "count": 0,
                "path": str(path),
                "has_publish": False,
                "has_full": False,
            },
        )
        row_count = _count_csv_rows(path)
        if not is_publish:
            summary["path"] = str(path)
            summary["count"] = row_count
            summary["has_full"] = True
        else:
            summary["has_publish"] = True
            summary["publish_path"] = str(path)
            summary["publish_count"] = row_count
            if not summary["has_full"]:
                summary["path"] = str(path)
                summary["count"] = row_count

    # Union in real projection-artifact weeks not already covered by
    # upcoming_recs_*.csv -- keeps latest_season()/available_weeks()/
    # default_week() (all downstream of this function) consistent with
    # the real data cards.py/picks.py actually render, instead of only
    # ever seeing the older recs-snapshot pipeline's own seasons.
    for season, weeks in _smartsim2_standalone_seasons_and_weeks().items():
        for week in weeks:
            key = (season, week)
            if key not in grouped:
                grouped[key] = {
                    "season": season,
                    "week": week,
                    "count": 1,
                    "path": str(source_root / f"smartsim2_projections_{season}_wk{week}.csv"),
                    "has_publish": False,
                    "has_full": True,
                }

    return sorted(grouped.values(), key=lambda item: (item["season"], item["week"]))


def latest_season() -> int:
    weeks = week_summaries()
    return weeks[-1]["season"] if weeks else 2025


def available_weeks(season: int | None = None) -> list[int]:
    resolved_season = int(season or latest_season())
    return [item["week"] for item in week_summaries() if item["season"] == resolved_season]


def default_week(season: int | None = None) -> int:
    resolved_season = int(season or latest_season())
    weeks = available_weeks(resolved_season)
    # Prefer the real calendar-driven target week (the first real week with
    # an unplayed game) over "last available week" -- once a season's whole
    # schedule has real generated projections (e.g. this session's full 2026
    # backfill), "last available" degenerates to week 18/the season finale
    # even during the preseason, which is a confusing default. The target
    # week also wins when no projection weeks exist yet (previously that
    # early-returned 1, which understated a real mid-season target). Falls
    # back to "last available" once every real game has a final score
    # (nothing left to target) or the real schedule file doesn't exist for
    # this season.
    target = nfl_target_week(resolved_season)
    if target is not None and (not weeks or target in weeks):
        return target
    return weeks[-1] if weeks else 1


def recommendation_path(week: int, season: int | None = None) -> Path:
    resolved_season = int(season or latest_season())
    full = data_path(f"upcoming_recs_{resolved_season}_wk{week}.csv")
    if full.exists():
        return full
    publish = data_path(f"upcoming_recs_{resolved_season}_wk{week}_publish.csv")
    return publish


def build_module_links(selected_week: int, active_label: str, *, season: int | None = None) -> list[dict[str, Any]]:
    resolved_season = int(season or latest_season())
    links = [
        ("Cards", f"/nfl/cards?season={resolved_season}&week={selected_week}"),
        ("Betting Card", f"/nfl/season/{resolved_season}/betting-card?week={selected_week}"),
        ("Picks", f"/nfl/picks?season={resolved_season}&week={selected_week}"),
        ("Live Lens", f"/nfl/live-lens?season={resolved_season}&week={selected_week}"),
        ("Daily Archive", f"/nfl/archive?season={resolved_season}&week={selected_week}"),
        # These two real pages (build_nfl_props_page_context / build_nfl_market_board,
        # both already live behind /nfl/props and /nfl/market-board) had no
        # nav link into them from anywhere in this module's own link list --
        # orphaned pages, reachable only by typing the URL directly.
        ("Props", f"/nfl/props?season={resolved_season}&week={selected_week}"),
        ("Market Board", f"/nfl/market-board?season={resolved_season}&week={selected_week}"),
        ("Hub", "/nfl/hub"),
    ]
    return [{"label": label, "href": href, "active": label == active_label} for label, href in links]


def format_odds(value: Any) -> str:
    return format_signed_price(value)


def real_schedule_path(season: int) -> Path:
    return data_path(f"schedule_{season}.csv")


def nfl_target_week(season: int) -> int | None:
    """Real calendar-driven "which week should we be preparing simulations
    for right now" -- the lowest week number in the real schedule
    (data/nfl_source/schedule_{season}.csv) with any game not yet played
    (away_score/home_score both blank). None if the file doesn't exist, or
    every loaded game already has a real final score (nothing left to
    prepare for this season). Deliberately NOT calendar-arithmetic (e.g.
    "today's date implies week N") -- real scores are the ground truth for
    "has this week happened yet," not a date guess, since bye weeks and
    schedule changes make date math unreliable."""
    path = real_schedule_path(season)
    if not path.exists():
        return None
    weeks_with_unplayed_games: set[int] = set()
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                week = int(row.get("week") or 0)
            except (TypeError, ValueError):
                continue
            home_score = (row.get("home_score") or "").strip()
            away_score = (row.get("away_score") or "").strip()
            if not home_score and not away_score:
                weeks_with_unplayed_games.add(week)
    return min(weeks_with_unplayed_games) if weeks_with_unplayed_games else None


def real_preseason_schedule_path(season: int) -> Path:
    return data_path(f"schedule_preseason_{season}.csv")


def preseason_target_week(season: int) -> int | None:
    """Same real, score-driven intent as nfl_target_week() -- "which week
    should we be preparing for right now" -- scoped to the real preseason
    schedule (data/nfl_source/schedule_preseason_{season}.csv, see
    scripts/fetch_nfl_preseason_schedule.py) and its closed week domain
    (1-4, ESPN's own preseason week numbering). None if the file doesn't
    exist, or every loaded game is already final.

    Deliberately keyed on ``status`` rather than blank home_score/away_score
    (the convention nfl_target_week() uses against the nflverse-sourced
    regular-season schedule): confirmed live that
    fetch_nfl_preseason_schedule.py's ESPN source writes "0"/"0" for a
    not-yet-played game, not blank -- a blank-score check against real
    preseason data always found zero "unplayed" games and returned None
    unconditionally, which silently defeated this function for every real
    2026 preseason week (and, downstream, the odds-refresh gating in
    refresh_odds_sources.py, the resim autorun in run_refresh_worker.py,
    and Layer 2 candidate generation in blueprints/home.py -- all three
    call this). ESPN's own status string is "Final" for a completed game
    (confirmed against the real 2025 preseason schedule) and anything else
    ("Scheduled", "In Progress", blank in a test fixture) for one that
    is not, which is the actually-reliable signal here."""
    path = real_preseason_schedule_path(season)
    if not path.exists():
        return None
    weeks_with_unplayed_games: set[int] = set()
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                week = int(row.get("week") or 0)
            except (TypeError, ValueError):
                continue
            if week not in (1, 2, 3, 4):
                continue
            status = str(row.get("status") or "").strip().lower()
            if status != "final":
                weeks_with_unplayed_games.add(week)
    return min(weeks_with_unplayed_games) if weeks_with_unplayed_games else None


def build_preseason_module_links(selected_week: int, active_label: str, *, season: int | None = None) -> list[dict[str, Any]]:
    """Preseason's own nav -- deliberately NOT a branch inside
    build_module_links() above, since preseason's week domain (1-4) and
    route family (/nfl/preseason/...) are completely separate from the
    regular-season one that function already serves."""
    resolved_season = int(season or latest_season())
    links = [
        ("Preseason Cards", f"/nfl/preseason/cards?season={resolved_season}&week={selected_week}"),
        ("Preseason Market Board", f"/nfl/preseason/market-board?season={resolved_season}&week={selected_week}"),
        ("Hub", "/nfl/hub"),
    ]
    return [{"label": label, "href": href, "active": label == active_label} for label, href in links]
