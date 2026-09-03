from __future__ import annotations

from datetime import date
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


def ncaaf_player_props_path(season: int, week: int) -> Path:
    """The captured OddsAPI player-prop CSV for one (season, week).

    UNDER `data/processed/`, AND THAT IS LOAD-BEARING. The hot-artifact
    allowlist already carries `*_source/data/processed/oddsapi_player_props_*.csv`
    (`artifact_publisher.HOT_ARTIFACT_PATTERNS`), so writing here means the
    capture can cross from the worker to web with NO allowlist change.

    Verified against the real matcher, not by reading the pattern:

        ncaaf_source/data/processed/oddsapi_player_props_2026_wk1.csv  ALLOWED
        ncaaf_source/data/oddsapi_player_props_2026_wk1.csv            blocked
        ncaaf_source/source_artifacts/oddsapi_player_props_2026_wk1.csv blocked

    NFL sits at `nfl_source/oddsapi_player_props_*.csv` with its OWN
    single-sport pattern line, added because its writer had already chosen a
    shallower path. Do not copy that shape here -- it needs an allowlist edit
    and this does not.
    """
    return data_path("processed", f"oddsapi_player_props_{int(season)}_wk{int(week)}.csv")


def player_game_stats_snapshot_path() -> Path:
    return ncaaf_source_artifacts_data_path("processed", "player_game_stats", "ncaaf_player_game_stats_snapshot.csv")


def transfer_portal_snapshot_path() -> Path:
    return ncaaf_source_artifacts_data_path("processed", "transfers", "ncaaf_transfer_portal_snapshot.csv")


def team_registry_snapshot_path() -> Path:
    return ncaaf_source_artifacts_data_path("processed", "team_registry", "ncaaf_team_registry_snapshot.csv")


def returning_production_snapshot_path() -> Path:
    return ncaaf_source_artifacts_data_path("processed", "returning_production", "ncaaf_returning_production_snapshot.csv")


def pace_snapshot_path() -> Path:
    """Per-team offensive seconds-per-play, built from CFBD `/drives`.

    `#457`/`state.md` recorded `pace` as NULL AT SOURCE. It was worse than null:
    with no block, `drive_priors._pace_index` falls back to **24.0 s/play**, so
    EVERY NCAAF game ran at `pace_index = +0.400` while the real 2025 league
    mean is 26.56 (sd 2.08, range 21.0..33.4 over 266 teams / 37,263 drives).
    A constant is not a neutral default here -- it pinned every game 18% faster
    than the average team actually plays.
    """
    return ncaaf_source_artifacts_data_path("processed", "pace", "ncaaf_pace_snapshot.csv")


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
    exactly: the lowest week number in the real schedule with any game whose
    real `completed` field is False. None if the season isn't loaded yet, or
    every loaded game is already marked completed.

    READS THE PUBLISHED ARTIFACT FIRST, and falls back to the raw CFBD games
    cache. The rule below is unchanged; only where the counts come from moved.

    WHY THE ARTIFACT HAD TO EXIST. The fallback is
    `historical_truth/games_{season}.json.gz`, which `ensure_games_cached`
    writes ONCE and never refreshes. Measured 2026-09-01: written 2026-07-21,
    888 games, `completed: False` on 888 of 888 -- so this function returned 1
    for the whole 2026 season, and `_week_is_within_pregame_window` trimmed the
    board to `week <= 1` while artifacts existed for weeks 1-13 and 15.

    Refreshing that cache fixes the WORKER's copy only: web and worker do not
    share a disk, and the gzip cannot be published across (a sub-4MB file goes
    up as UTF-8 text and a `.gz` fails `SKIP_READ_FAILED`). So the worker
    derives `week_state` -- small, JSON, publishable -- and this reads it. Web
    never calls CFBD, which is the worker/web split rather than an exception
    to it.

    ORDER MATTERS AND IS NOT A PREFERENCE. The fallback is the STALE source by
    construction; reading it first would mean the artifact never had an effect
    and this change would be inert while looking wired.
    """
    from syndicate.features.ncaaf.week_state import read_week_state, target_week_from_state

    from_artifact = target_week_from_state(read_week_state(season))
    if from_artifact is not None:
        return from_artifact

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

def fbs_relevant(row: object) -> bool:
    """Is this schedule row on the FBS board -- at least ONE side FBS?

    WIDENED 2026-09-03 FROM "BOTH SIDES FBS" `[user decision]`. The old gate hid
    7 of the 11 NCAAF games on the 2026-09-03 board: every FBS-vs-FCS game got
    no scoreboard chip at all, so its card fell back to rendering
    "Arkansas Pine Bluff Golden Lions @ Missouri Tigers" where every other sport
    shows tri-codes, a score and a clock. User-reported.

    MEASURED BEFORE WIDENING, 2026 schedule, 888 rows -- the classification data
    is complete and there is nothing to guess:

        ('fbs', 'fbs')  761        ('fbs', 'fcs')  127
        ('fcs', 'fbs')    0        ('fcs', 'fcs')    0

    No nulls, and the FCS side is always the visitor -- CFBD publishes the FBS
    schedule, so an FCS team appears only as somebody's opponent. All seven of
    2026-09-03's FCS visitors resolve in the team registry with a `team_id` and
    a logo, so the ESPN live-score join (which keys on that id) works for them
    and the chips get real scores rather than permanent dashes.

    UNKNOWN IS NOT FBS. An absent or unrecognised classification returns False
    rather than falling through to the permissive branch: a guard that maps
    "I could not tell" onto "allow" turns a data gap into a silently relaxed
    rule. Today nothing takes that branch; if the feed ever stops publishing
    classifications, this narrows rather than floods, and narrowing is visible.

    NOT USED BY `_smartsim2_standalone_rows`, AND THAT ASYMMETRY IS DELIBERATE.
    That function builds CARDS by joining SmartSim 2.0 projections, and the
    projection index for 2026 week 1 holds exactly 51 entries against exactly 51
    FBS-vs-FBS games -- the sim does not cover FCS opponents. A chip needs teams,
    a kickoff and a score; a card needs a model. Widening the card builder would
    manufacture cards with no projection behind them, which is a worse product
    than a full-name label. So: cards stay FBS-vs-FBS, chips do not.
    """
    if not isinstance(row, dict):
        return False
    home = str(row.get("homeClassification") or "").strip().lower()
    away = str(row.get("awayClassification") or "").strip().lower()
    return "fbs" in (home, away)


def ncaaf_week_and_card_keys_for_date(season: int, date_text: str) -> tuple[int, set[str]] | None:
    """(week, card gamePk keys) for the real NCAAF games on `date_text`.

    THE NCAAF HALF OF THE #273 FIX, REWRITTEN 2026-08-29 BECAUSE THE FIRST
    VERSION NEVER WORKED IN PRODUCTION.

    `_NCAAFDataProvider.games()` opens with a `return []` when this returns
    None, and `build_game_chips` resolves context with NO week -- so whatever
    this function cannot answer, NCAAF contributes ZERO chips for. Zero chips
    is indistinguishable from "no slate", which is how this stayed invisible
    twice.

    ------------------------------------------------------------------
    WHY THE cfbd_lines VERSION COULD NEVER HAVE WORKED
    ------------------------------------------------------------------

    It joined ESPN event ids -> `cfbd_lines_{season}_wk{week}.json` -> card
    keys. That file **has no producer on any service and exists in git at no
    SHA** -- not this session's finding but `#557`'s, already written into
    `ncaaf/cards.py`: *"`fetch_ncaaf_market_lines.py` and `fetch_cfbd_lines.py`
    have zero callers, and no `cfbd_lines_*.json` exists in git at any SHA."*
    It is absent from `HOT_ARTIFACT_PATTERNS` too, so nothing can publish it
    worker->web either.

    So the loop over weeks 1..20 found no file, `best` stayed None, and NCAAF
    served 0 chips on every service on every date. Measured on production
    2026-08-29T16:5xZ, with a game visibly in progress:
    `/api/board/game-chips?sports=ncaaf` -> **0 chips**, `source:
    inline_artifact_stale` (i.e. web computed it inline, on current code), while
    soccer/mlb/wnba each joined 400/400 rows. Layer 2's 82 NCAAF rows therefore
    carried `game_state: None`, because `layer2_board` sets it only `if game:`.

    **The previous fix replaced an unconditional `return []` with a conditional
    one whose condition is never true in production.** It read as fixed, and its
    own docstring said so.

    **AND THE LOCAL EVIDENCE ARGUED FOR KEEPING IT.** On a dev checkout
    `build_game_chips` returns 8 correct live chips, because `data/ncaaf_source/`
    holds an UNTRACKED `cfbd_lines_2026_wk*.json` mirror. `git ls-files` returns
    0 for that glob. This is exactly the `CLAUDE.md` rule that `data/**` in git
    is a lossy mirror and never evidence about production.

    ------------------------------------------------------------------
    WHAT THIS READS INSTEAD: THE SCHEDULE THE CARDS ARE BUILT FROM
    ------------------------------------------------------------------

    The card key is not a lookup, it is a FORMULA, and it is built from the
    season schedule in `cards.py`:

        gamePk = f"{week}_{away_team}_{home_team}".replace(" ", "_")

    over `load_games_season(season)`, keeping rows where `week` matches and the
    game is on the FBS board (`fbs_relevant`). Reconstructing it from that same
    source with that same filter is exact by construction rather than by join --
    there is no id to match, no name to normalise, and no second artifact that
    has to exist. It also removes the last consumer of `cfbd_lines_*.json` from
    the chips path.

    A CLASSIFICATION FILTER IS STILL LOAD-BEARING and is why this cannot just
    return every schedule row for the date: the board is a curated subset (cfbd
    lists 99 week-1 games), and a key the board never built would filter every
    game out of the chip list.

    **WIDENED 2026-09-03 from BOTH-sides-FBS to `fbs_relevant` (at least one
    side)** `[user decision]`, which deliberately makes this set a SUPERSET of
    what `_smartsim2_standalone_rows` builds cards for. See `fbs_relevant` for
    the measurement and for why cards and chips no longer share one gate. The
    two consumers both stay correct under a wider set: `cards.py` filters the
    chip list with it, which is the point; `home.py:6613` intersects it with
    cards that already exist, so a key with no card simply never matches.

    ------------------------------------------------------------------
    THE DATE IS COMPARED IN CENTRAL, AND THE UTC PREFIX IS A REAL BUG
    ------------------------------------------------------------------

    The old docstring avoided date comparison over a UTC-boundary worry. That
    worry was RIGHT and a first cut of this rewrite reproduced the bug: matching
    `startDate[:10]` returned **7** of Saturday 08-29's **8** games, silently
    dropping MEM @ UNLV, which kicks 9pm Central and is therefore
    `2026-08-30T02:00Z`. The board's date is Central (`central_today_iso`), so a
    UTC prefix moves every late-evening game to the following day -- and on a
    football Saturday the late window is the marquee one.

    `central_date_from_iso` exists for precisely this and carries its own
    measurement (WNBA, 2026-07-21). Reused rather than re-derived.

    None when the schedule cannot be read or carries no FBS game on the date.
    """
    date_value = str(date_text or "").strip()[:10]
    if len(date_value) != 10:
        return None
    try:
        target_day = date.fromisoformat(date_value)
    except ValueError:
        return None

    from syndicate.features.football.sim_engine.smartsim2.historical_truth.ncaaf_historical_loader import load_games_season
    from syndicate.features.shared.timezone import central_date_from_iso

    try:
        schedule = load_games_season(season)
    except Exception:
        return None

    keys_by_week: dict[int, set[str]] = {}
    for game in schedule:
        if not isinstance(game, dict):
            continue
        # CENTRAL, never the UTC prefix -- see the docstring. A 9pm Central
        # kickoff is the next UTC day, and prefix matching drops it.
        if central_date_from_iso(game.get("startDate")) != target_day:
            continue
        # DELIBERATELY WIDER than `_smartsim2_standalone_rows`, which needs a
        # SmartSim 2.0 projection and so stays FBS-vs-FBS. A chip needs teams,
        # a kickoff and a score. See `fbs_relevant`.
        if not fbs_relevant(game):
            continue
        home_team = str(game.get("homeTeam") or "").strip()
        away_team = str(game.get("awayTeam") or "").strip()
        if not home_team or not away_team:
            continue
        try:
            week = int(game.get("week"))
        except (TypeError, ValueError):
            continue
        keys_by_week.setdefault(week, set()).add(
            f"{week}_{away_team}_{home_team}".replace(" ", "_")
        )

    if not keys_by_week:
        return None
    # A date's games belong to one week in practice; take the week carrying the
    # most of them rather than the lowest number, so a stray cross-week fixture
    # cannot capture the date.
    week = max(keys_by_week, key=lambda item: (len(keys_by_week[item]), -item))
    return week, keys_by_week[week]
