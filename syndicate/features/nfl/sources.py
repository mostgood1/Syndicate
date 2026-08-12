from __future__ import annotations

import csv
import json
import os
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


def nfl_artifact_output_root() -> Path:
    """Where generated NFL artifacts must be WRITTEN. `#389` follow-up.

    MEASURED IN PRODUCTION 2026-08-12. The SmartSim2 generators wrote to

        /opt/render/project/src/data/nfl_source/smartsim2_projections_2026_wk1.csv

    while `run_refresh_worker`'s staleness guard looked at

        /opt/render/project/data/nfl_source/smartsim2_projections_2026_wk1.csv

    `src/data` is the REPO CHECKOUT -- ephemeral, replaced on every deploy.
    `data` is the mounted disk. So every run wrote a real artifact to a
    location nothing reads and every deploy discarded it, the guard never saw
    a fresh file, and the sport stayed permanently stale (~90 relaunches/day
    before `#389` added the backoff).

    **WHY THE WRITER PICKED THE WRONG ONE.** `default_nfl_source_root()` calls
    `_first_existing_root`, which probes each candidate for
    `upcoming_recs_*.csv` and returns the first that HAS it. The repo mirror
    ships that file; the mounted disk does not. So an unrelated artifact's
    presence decided where projections were written.

    That probe is right for READS -- find the root that actually holds the
    thing you want -- and wrong for WRITES, where the answer must be "the
    configured root", not "wherever something else happens to live".
    `source_roots.preferred_artifact_roots` already says this in its own
    comment: *"does this directory contain anything" is not "does it contain
    the file you asked for"*. This is the write-side corollary.

    Deliberately no filesystem probing: env var, else the shared data root.
    `run_refresh_worker._season_projection_artifact_path` calls this same
    function, so the writer and the guard cannot diverge again.
    """
    env_value = str(os.environ.get("SYNDICATE_NFL_SOURCE_ROOT") or "").strip()
    if env_value:
        return Path(env_value).expanduser().resolve()
    from syndicate.features.shared.refresh_state_store import data_root

    return data_root() / "nfl_source"


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

    # KEYED ON `gameday`, NOT `status`. MEASURED 2026-08-08.
    #
    # The status rule returned `min(weeks whose status != "final")`, and NOTHING
    # EVER REWRITES THAT COLUMN: scripts/fetch_nfl_preseason_schedule.py is a
    # manual CLI referenced by no pipeline (confirmed by grep across
    # tools/daily_update.py, scripts/run_refresh_worker.py and
    # scripts/refresh_odds_sources.py). The 2026 file was written 08-05 and
    # still read "Scheduled" for all 49 games on 08-08 -- including week 1's
    # single game, played 08-06 -- so min() returned 1 forever.
    #
    # That is the "week self-pins to 1" defect. Not a hardcode: a min() over a
    # set that never shrinks because nobody refreshes its input.
    #
    # `gameday` needs no refresh to stay correct, so this asks the same question
    # the docstring always did -- "which week should we be preparing for right
    # now" -- against a column that cannot go stale.
    #
    # Deliberately >= today rather than > today: a week whose games are TODAY is
    # the week we are preparing for, and the previous rule agreed (an unplayed
    # game today was not "final").
    from syndicate.features.shared.timezone import central_today_iso

    today = str(central_today_iso() or "").strip()
    weeks_ahead: set[int] = set()
    weeks_unplayed_by_status: set[int] = set()
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                week = int(row.get("week") or 0)
            except (TypeError, ValueError):
                continue
            if week not in (1, 2, 3, 4):
                continue
            gameday = str(row.get("gameday") or "").strip()
            if today and gameday and gameday >= today:
                weeks_ahead.add(week)
            if str(row.get("status") or "").strip().lower() != "final":
                weeks_unplayed_by_status.add(week)
    if weeks_ahead:
        return min(weeks_ahead)
    # No dated row is still ahead. If the file also has no `gameday` at all we
    # cannot answer by date, so fall back to the old status rule rather than
    # silently reporting "preseason is over" from a column we never read.
    # A file WITH gamedays that are all past genuinely means preseason is done.
    return None if _preseason_schedule_has_gamedays(path) else (
        min(weeks_unplayed_by_status) if weeks_unplayed_by_status else None
    )


def _preseason_schedule_has_gamedays(path: Path) -> bool:
    """Does this schedule carry usable `gameday` values at all?

    Separates "preseason is genuinely over" (dated rows, all past) from "this
    file cannot answer by date" (no dates), so the fallback to the stale-status
    rule only fires in the second case.
    """
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                if str(row.get("gameday") or "").strip():
                    return True
    except OSError:
        return False
    return False


def preseason_week_for_date(season: int, date_text: str) -> int | None:
    """Which preseason week contains `date_text`, a US-local (Central) board date?

    ADDITIVE. preseason_target_week() above answers a DIFFERENT question --
    "which week are we preparing for right now" -- and its seven callers all
    genuinely want that global answer. This is the per-request question the
    board needs, and it is deliberately a separate function so that adding it
    changes nothing for them.

    RESOLVED BY GAME ID, NOT BY DATE ARITHMETIC, and that is the entire point.
    The CSV's `gameday` is a UTC date while ESPN buckets by US-local date, so
    CAR @ ARI is `2026-08-07` in the CSV and `08-06` to ESPN -- a 00:00Z
    kickoff. Joining ESPN's event ids to the `game_id` column sidesteps the
    conversion completely, because an id carries no timezone and so cannot be
    off by one day. MEASURED across 2026-08-05..08-24: all 30 ids ESPN returned
    in that window resolved to a CSV week, with zero unknown ids.

    None whenever we cannot answer -- ESPN unreachable, no games that date, or
    no returned id present in the CSV -- so callers fall back to
    preseason_target_week() and behave exactly as they did before.
    """
    date_value = str(date_text or "").strip()
    if not date_value:
        return None
    path = real_preseason_schedule_path(int(season))
    if not path.exists():
        return None
    try:
        from syndicate.features.shared.schedule_adapter import fetch_schedule_for_date

        events = fetch_schedule_for_date("nfl", date_value)
    except Exception:
        return None
    event_ids = {str(getattr(event, "event_id", "") or "").strip() for event in events}
    event_ids.discard("")
    if not event_ids:
        return None

    weeks: list[int] = []
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                if str(row.get("game_id") or "").strip() not in event_ids:
                    continue
                try:
                    week = int(row.get("week") or 0)
                except (TypeError, ValueError):
                    continue
                if week in (1, 2, 3, 4):
                    weeks.append(week)
    except OSError:
        return None
    if not weeks:
        return None
    # A date never spans two preseason weeks in practice (confirmed across the
    # whole 2026 window), but ESPN can carry a rescheduled game, so pick the
    # week most of the date's games belong to and break a tie on the lower week
    # rather than letting one stray row decide the whole card set.
    return min(sorted(set(weeks)), key=lambda week: (-weeks.count(week), week))


def regular_season_game_ids_for_date(season: int, date_text: str) -> tuple[int, set[str]] | None:
    """(week, game_ids) for the real regular-season games on `date_text`.

    THE COMPANION TO preseason_week_for_date(), AND IT WORKS THE OPPOSITE WAY
    ROUND ON PURPOSE. That one joins ESPN event ids because the preseason CSV's
    dates are unusable; this one reads `gameday` directly and must NOT go
    through ESPN ids at all. Two measured reasons:

    1. THE TWO NFL SCHEDULE FILES USE DIFFERENT DATE CONVENTIONS. Preseason
       `gameday` is a UTC date (CAR @ ARI is `2026-08-07`, `gametime` 00:00,
       and ESPN buckets it under 08-06). Regular-season `gameday` is the
       US-LOCAL date (`2026-09-09`, `gametime` 20:20) and agrees with ESPN
       exactly -- verified on 2026 week 1, where the CSV's four gamedays split
       16 games 1/1/13/1 and ESPN returns 1/1/13/1 for those same dates. So
       here the date column is already the right answer and needs no
       translation.
    2. THE ID SPACES DO NOT MEET. The regular-season file is nflverse-keyed
       (`2026_01_NE_SEA`); ESPN's are numeric (`401873271`). Filtering
       regular-season cards against ESPN ids would match NOTHING, and the
       board's filter deliberately fails CLOSED on "ESPN answered but nothing
       matched" -- so routing this through it would blank the entire regular
       season. Returning the ids lets the caller filter in the card's own id
       space.

    None if the file is missing or no regular-season game falls on that date.
    """
    date_value = str(date_text or "").strip()
    if not date_value:
        return None
    path = real_schedule_path(int(season))
    if not path.exists():
        return None

    game_ids: set[str] = set()
    weeks: list[int] = []
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                if str(row.get("gameday") or "").strip() != date_value:
                    continue
                game_id = str(row.get("game_id") or "").strip()
                try:
                    week = int(row.get("week") or 0)
                except (TypeError, ValueError):
                    continue
                if not game_id or week <= 0:
                    continue
                game_ids.add(game_id)
                weeks.append(week)
    except OSError:
        return None
    if not game_ids or not weeks:
        return None
    # A single date can legitimately carry two weeks only around a Thursday
    # opener; take the week most of the date's games belong to.
    week = min(sorted(set(weeks)), key=lambda value: (-weeks.count(value), value))
    return week, game_ids


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
