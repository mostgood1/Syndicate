from __future__ import annotations

from pathlib import Path
import json
import re
from typing import Any

from syndicate.features.shared.formatters import format_num
from syndicate.features.shared.formatters import format_pct
from syndicate.features.shared.formatters import format_signed_price
from syndicate.features.shared.source_roots import preferred_artifact_roots
from syndicate.features.shared.source_roots import preferred_source_roots


_SEASON_PATTERN = re.compile(r"college_football_betting_lines_(\d{4})\.csv", re.IGNORECASE)


def _source_roots() -> list[Path]:
    return preferred_source_roots(
        __file__,
        env_var="SYNDICATE_NCAAF_SOURCE_ROOT",
        local_dir_name="ncaaf_source",
    )


def default_ncaaf_source_root() -> Path:
    return _source_roots()[0]


def _artifact_roots() -> list[Path]:
    return preferred_artifact_roots(
        __file__,
        env_var="SYNDICATE_NCAAF_SOURCE_ROOT",
        local_dir_name="ncaaf_source",
    )


def data_path(*parts: str) -> Path:
    roots = _source_roots()
    if roots:
        return roots[0] / "data" / Path(*parts)
    return Path(__file__).resolve().parents[3] / "data" / "ncaaf_source" / "data" / Path(*parts)


def ncaaf_source_artifacts_data_path(*parts: str) -> Path:
    return default_ncaaf_source_root() / "source_artifacts" / "data" / Path(*parts)


def player_identity_snapshot_path() -> Path:
    return ncaaf_source_artifacts_data_path("processed", "player_identity", "ncaaf_player_identity_snapshot.csv")


def roster_snapshot_path() -> Path:
    return ncaaf_source_artifacts_data_path("processed", "roster", "ncaaf_roster_snapshot.csv")


def player_game_stats_snapshot_path() -> Path:
    return ncaaf_source_artifacts_data_path("processed", "player_game_stats", "ncaaf_player_game_stats_snapshot.csv")


def transfer_portal_snapshot_path() -> Path:
    return ncaaf_source_artifacts_data_path("processed", "transfers", "ncaaf_transfer_portal_snapshot.csv")


def team_registry_snapshot_path() -> Path:
    return ncaaf_source_artifacts_data_path("processed", "team_registry", "ncaaf_team_registry_snapshot.csv")


def returning_production_snapshot_path() -> Path:
    return ncaaf_source_artifacts_data_path("processed", "returning_production", "ncaaf_returning_production_snapshot.csv")


def coach_continuity_snapshot_path() -> Path:
    return ncaaf_source_artifacts_data_path("processed", "coach_continuity", "ncaaf_coach_continuity_snapshot.csv")


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def load_summary_index() -> dict[str, Any] | None:
    return load_json(data_path("recommendations_summary", "index.json"))


def _legacy_default_season_from_summary_index() -> int | None:
    """The original default_season() implementation -- a regex scan over
    the recommendations-summary index's fetch stdout/stderr text, tied to
    the same old data pipeline as week_summaries(). Kept as a fallback
    only (see default_season() below) since it has no way to see real
    SmartSim2-only seasons (e.g. 2026, which the legacy engine has no
    recs data for at all)."""
    payload = load_summary_index() or {}
    weeks = payload.get("weeks") if isinstance(payload.get("weeks"), list) else []
    for week in weeks:
        if not isinstance(week, dict):
            continue
        fetch = week.get("fetch") if isinstance(week.get("fetch"), dict) else {}
        for key in ("stdout", "stderr"):
            text = fetch.get(key)
            if not isinstance(text, str):
                continue
            match = _SEASON_PATTERN.search(text)
            if match:
                return int(match.group(1))
    generated_utc = payload.get("generated_utc")
    if isinstance(generated_utc, str) and len(generated_utc) >= 4 and generated_utc[:4].isdigit():
        return int(generated_utc[:4])
    return None


def default_season() -> int:
    """Real active season -- delegates to cards.py's
    _resolve_ncaaf_active_season_and_weeks() (unions the legacy engine's
    own weeks with real SmartSim2 projection-artifact weeks, so a season
    the engine has no recs data for -- e.g. 2026 -- still resolves
    correctly once real SmartSim2 projections exist for it). Confirmed
    real bug this was fixing: before this, default_season() (used by
    /ncaaf/hub, picks.py, build_module_links) returned 2025 even though
    cards.py's own separate resolver already found 2026 -- the two were
    never wired together. Local import to avoid a circular import (cards.py
    imports several functions from this module at load time); by the time
    anything actually CALLS default_season(), cards.py is already loaded."""
    from syndicate.features.ncaaf.cards import _resolve_ncaaf_active_season_and_weeks

    active_season, _weeks = _resolve_ncaaf_active_season_and_weeks()
    if active_season:
        return active_season
    return _legacy_default_season_from_summary_index() or 2025


def week_summaries() -> list[dict[str, Any]]:
    payload = load_summary_index() or {}
    weeks = payload.get("weeks") if isinstance(payload.get("weeks"), list) else []
    resolved_default_season = default_season()
    output: list[dict[str, Any]] = []
    for week in weeks:
        if not isinstance(week, dict):
            continue
        try:
            week_number = int(week.get("week"))
        except Exception:
            continue
        try:
            count = int(week.get("count") or 0)
        except Exception:
            count = 0
        fetch = week.get("fetch") if isinstance(week.get("fetch"), dict) else {}
        output.append(
            {
                "week": week_number,
                "season": int(week.get("season") or resolved_default_season),
                "count": count,
                "path": str(week.get("path") or summary_path(week_number)),
                "fetch_rc": fetch.get("rc"),
                "has_data": count > 0,
            }
        )
    return sorted(output, key=lambda item: item["week"])


def available_weeks() -> list[int]:
    return [item["week"] for item in week_summaries() if item["has_data"]]


def default_week() -> int:
    weeks = available_weeks()
    # Mirror cards.py's _ncaaf_default_active_week: available_weeks() comes
    # from the legacy recommendations_summary index, which can be empty for
    # a season that has real SmartSim2 projections (confirmed live: an empty
    # recommendations_summary/ directory pinned the Layer 2 NCAAF context to
    # week 1 via the bare fallback below). The real schedule-driven target
    # week outranks it whenever the schedule is loadable.
    target = ncaaf_target_week(default_season())
    if target is not None and (not weeks or target in weeks):
        return target
    return weeks[-1] if weeks else 1


def summary_path(week: int) -> Path:
    return data_path("recommendations_summary", f"week_{week}.json")


def format_moneyline(value: Any) -> str:
    return format_signed_price(value)


def build_module_links(selected_week: int, active_label: str, *, season: int | None = None) -> list[dict[str, Any]]:
    resolved_season = int(season) if season is not None else default_season()
    betting_href = f"/ncaaf/season/{resolved_season}/betting-card?week={selected_week}"
    links = [
        ("Cards", f"/ncaaf/cards?week={selected_week}"),
        ("Betting Card", betting_href),
        ("Picks", f"/ncaaf/picks?week={selected_week}"),
        ("Live Lens", f"/ncaaf/live-lens?week={selected_week}"),
        ("Daily Archive", f"/ncaaf/archive?week={selected_week}"),
        ("Hub", "/ncaaf/hub"),
    ]
    return [{"label": label, "href": href, "active": label == active_label} for label, href in links]


def ncaaf_target_week(season: int) -> int | None:
    """Real calendar-driven "which week should we be preparing simulations
    for right now" -- mirrors syndicate.features.nfl.sources.nfl_target_week
    exactly: the lowest week number in the real schedule
    (historical_truth/games_{season}.json.gz, via load_games_season) with
    any game whose real `completed` field is False. None if the season
    isn't loaded yet, or every loaded game is already marked completed."""
    from syndicate.features.football.sim_engine.smartsim2.historical_truth.ncaaf_historical_loader import load_games_season

    try:
        games = load_games_season(season)
    except Exception:
        return None
    weeks_with_unplayed_games: set[int] = set()
    for game in games:
        if not isinstance(game, dict):
            continue
        if game.get("completed"):
            continue
        week = game.get("week")
        try:
            weeks_with_unplayed_games.add(int(week))
        except (TypeError, ValueError):
            continue
    return min(weeks_with_unplayed_games) if weeks_with_unplayed_games else None

def ncaaf_week_and_card_keys_for_date(season: int, date_text: str) -> tuple[int, set[str]] | None:
    """(week, card gamePk keys) for the real NCAAF games on `date_text`.

    THE NCAAF HALF OF THE #273 FIX. `_NCAAFDataProvider.games()` opened with
    ``if context.week is None: return []``, and `build_game_chips` resolves
    context with NO week -- so NCAAF contributed ZERO chips on every date,
    forever. MEASURED on production: 0 chips on 09-05 and 09-12 while ESPN had
    68 and 80 real games. Silent, because zero chips is indistinguishable from
    no slate.

    DELIBERATELY NOT A COPY OF EITHER NFL RESOLVER, because NCAAF's data shape
    differs from both and the difference was measured, not assumed:

    * NCAAF cards carry a SYNTHETIC key -- ``f"{week}_{away}_{home}"`` with
      spaces underscored (`1_North_Carolina_TCU`), built in three places in
      cards.py. It is neither an ESPN numeric id nor an nflverse id, and the
      card carries no date field at all, so neither NFL approach ports over.
    * `cfbd_lines_{season}_wk{week}.json` is the bridge: it carries an
      ESPN-compatible numeric ``id``, the ``week``, ``startDate``, and both
      team names -- enough to reconstruct the card key AND join to ESPN.

    So this joins ESPN event ids -> cfbd rows -> reconstructed card keys, and
    the date is never compared to a date (same property that makes the NFL
    preseason resolver immune to the UTC/local boundary: cfbd's ``startDate``
    is UTC and is deliberately NOT used for matching).

    Note the card set is a CURATED SUBSET: cfbd lists 99 week-1 games and the
    board builds 16 cards. Measured join rate on 2026 week 1: 16/16 cards
    resolved. So a correct result here is "the cards whose games fall on this
    date", never "every game ESPN lists".

    None if no cfbd week contains any of the date's ESPN ids.
    """
    date_value = str(date_text or "").strip()
    if not date_value:
        return None
    try:
        from syndicate.features.shared.schedule_adapter import fetch_schedule_for_date

        events = fetch_schedule_for_date("ncaaf", date_value)
    except Exception:
        return None
    event_ids = {str(getattr(event, "event_id", "") or "").strip() for event in events}
    event_ids.discard("")
    if not event_ids:
        return None

    data_root = default_ncaaf_source_root() / "data"
    best: tuple[int, set[str]] | None = None
    for week in range(1, 21):
        path = data_root / f"cfbd_lines_{season}_wk{week}.json"
        if not path.exists():
            continue
        try:
            with path.open("r", encoding="utf-8") as handle:
                rows = json.load(handle)
        except Exception:
            continue
        if not isinstance(rows, list):
            continue
        keys: set[str] = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            if str(row.get("id") or "").strip() not in event_ids:
                continue
            away = str(row.get("awayTeam") or "").strip()
            home = str(row.get("homeTeam") or "").strip()
            row_week = row.get("week")
            if not away or not home or row_week is None:
                continue
            keys.add(f"{row_week}_{away}_{home}".replace(" ", "_"))
        # The date's games can only belong to one cfbd week in practice; take
        # the week that matched the most of them rather than the first file
        # that happened to match one.
        if keys and (best is None or len(keys) > len(best[1])):
            best = (week, keys)
    return best
