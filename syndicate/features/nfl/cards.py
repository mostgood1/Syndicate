from __future__ import annotations

import csv
import glob
import json
import os
import re
import statistics
from datetime import datetime
from datetime import timezone
from functools import lru_cache
from typing import Any

from syndicate.features.nfl.props import nfl_prop_display_stat
from syndicate.features.nfl.props import nfl_props_key
from syndicate.features.nfl.props import nfl_props_rows_for_week
from syndicate.features.nfl.smartsim2_projection import read_projection_artifact
from syndicate.features.nfl.sources import available_weeks
from syndicate.features.nfl.sources import build_module_links
from syndicate.features.nfl.sources import default_nfl_source_root
from syndicate.features.nfl.sources import default_week
from syndicate.features.nfl.sources import latest_season
from syndicate.features.nfl.sources import real_schedule_path
from syndicate.features.nfl.sources import recommendation_path
from syndicate.features.nfl.props import nfl_prop_recommendations_for_matchup
from syndicate.features.shared.discrete_nav import neighboring_values
from syndicate.features.shared.discrete_nav import resolve_selected_value
from syndicate.features.shared.football_cards import cover_probability
from syndicate.features.shared.football_cards import football_market_tiles
from syndicate.features.shared.football_cards import football_shared_predictions
from syndicate.features.shared.football_cards import format_kickoff_label
from syndicate.features.shared.formatters import format_pct
from syndicate.features.shared.game_board_contract import apply_game_board_contract
from syndicate.features.shared.market_inventory import join_odds_to_sim
from syndicate.features.shared.team_aliases import canonical_team
from syndicate.features.shared.team_branding import read_team_branding_snapshot


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except Exception:
        return None


def _format_num(value: Any, digits: int = 1) -> str:
    number = _safe_float(value)
    if number is None:
        return "-"
    return f"{number:.{digits}f}"


def _format_signed(value: Any, digits: int = 1) -> str:
    number = _safe_float(value)
    if number is None:
        return "-"
    return f"{number:+.{digits}f}"


def _format_pct(value: Any) -> str:
    number = _safe_float(value)
    if number is None:
        return "-"
    return f"{number * 100:.1f}%"


def _format_moneyline(value: Any) -> str:
    number = _safe_float(value)
    if number is None:
        return "-"
    rounded = int(round(number))
    return f"+{rounded}" if rounded > 0 else str(rounded)


def _safe_text(value: Any, fallback: str = "") -> str:
    text = str(value or "").strip()
    return text or fallback


def _format_ev_pct(value: Any) -> str:
    number = _safe_float(value)
    if number is None:
        return "-"
    return f"{number:.1f}%"


def _confidence_rank(value: Any) -> int:
    label = _safe_text(value).lower()
    if label == "high":
        return 3
    if label == "medium":
        return 2
    if label == "low":
        return 1
    return 0


def _team_abbr(team_name: str) -> str:
    tokens = [token for token in team_name.replace(".", " ").split() if token]
    initials = "".join(token[0] for token in tokens if token and token[0].isalpha()).upper()
    if len(initials) >= 2:
        return initials[:3]
    letters = "".join(char for char in team_name.upper() if char.isalpha())
    return (letters[:3] or "TEAM")


def _normalize_branding_key(text: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


@lru_cache(maxsize=1)
def _team_branding_index() -> dict[str, Any]:
    path = default_nfl_source_root() / "source_artifacts" / "data" / "processed" / "team_branding" / "nfl_team_branding.csv"
    rows = read_team_branding_snapshot(path)
    index: dict[str, Any] = {}
    for row in rows:
        for key in (row.display_name, row.location, row.abbreviation):
            normalized = _normalize_branding_key(key)
            if normalized:
                index.setdefault(normalized, row)
    return index


def _resolve_branding(team_name: str) -> Any | None:
    """Branding row for a team token, resolving nflverse codes to ESPN ones.

    THE SNAPSHOT AND THE PROJECTION SPEAK DIFFERENT VOCABULARIES, and this is
    the SECOND time that has cost something. `nfl_team_branding.csv` is keyed
    the way ESPN writes abbreviations -- `LAR`, `WSH` -- while the smartsim2
    projection artifact carries nflverse's, which are `LA` and `WAS`. All 32
    teams are in the file; two of them were simply unreachable by the name the
    card asks with.

    MEASURED ON PRODUCTION 2026-09-08, the served `/nfl/cards` compact strip:
    **30 of 32 crest rows** carried an `<img>`; the two that fell back to text
    were exactly `LA` and `WAS`. NCAAF is 102/102 on the same surface, so this
    was a real parity shortfall and not a cosmetic one. `brokenImgs` was 0 --
    no URL was wrong, the lookup just never got that far.

    `state.md [nfl-board-projection-coverage]` records the identical alias gap
    biting the PROJECTION join a week ago ("nflverse writes the Rams `LA`;
    `_NFL_ALIAS_TO_NAME` knew only `LAR`", and `WAS` not `WSH`). That was fixed
    in `team_aliases`, and this call site was never routed through the fix --
    which is `#334`'s lesson exactly: fix the choke point every caller shares,
    or the ones you did not look at keep the old behaviour.

    SO THIS ADDS NO SECOND TABLE. `canonical_team` is the one map, it already
    resolves all four spellings, and it takes a tri-code or a full name in
    either direction. A private copy here is the drift that module exists to
    prevent.
    """
    index = _team_branding_index()
    direct = index.get(_normalize_branding_key(team_name))
    if direct is not None:
        return direct
    canonical = canonical_team("nfl", team_name)
    if not canonical:
        return None
    return index.get(_normalize_branding_key(canonical))


def _format_game_date(value: Any) -> str:
    raw = _safe_text(value, "TBD")
    return raw[:10] if len(raw) >= 10 else raw


@lru_cache(maxsize=64)
def _read_snapshot_rows(season: int, week: int) -> tuple[dict[str, Any], ...]:
    path = recommendation_path(week, season=season)
    if not path.exists():
        return ()
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return tuple(row for row in csv.DictReader(handle) if isinstance(row, dict))
    except Exception:
        return ()


def _snapshot_source_path(season: int, week: int) -> str:
    return str(recommendation_path(week, season=season))


def _row_sort_key(row: dict[str, Any]) -> tuple[int, float, str]:
    ev_pct = _safe_float(row.get("ev_pct"))
    return (
        _confidence_rank(row.get("confidence")),
        ev_pct if ev_pct is not None else float("-inf"),
        _safe_text(row.get("type")).upper(),
    )


def _group_snapshot_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        away_team = _safe_text(row.get("away_team"), "Away")
        home_team = _safe_text(row.get("home_team"), "Home")
        game_date = _format_game_date(row.get("game_date"))
        grouped.setdefault((game_date, away_team, home_team), []).append(row)

    bundles: list[dict[str, Any]] = []
    for (game_date, away_team, home_team), matchup_rows in grouped.items():
        ordered_rows = sorted(matchup_rows, key=_row_sort_key, reverse=True)
        top_row = ordered_rows[0] if ordered_rows else {}
        confidence = _safe_text(top_row.get("confidence"), "Snapshot")
        top_ev = _safe_float(top_row.get("ev_pct"))
        type_scores: dict[str, float] = {}
        for row in ordered_rows:
            type_name = _safe_text(row.get("type"), "Recommendation").upper()
            ev_pct = _safe_float(row.get("ev_pct"))
            if type_name not in type_scores or ((ev_pct if ev_pct is not None else float("-inf")) > type_scores[type_name]):
                type_scores[type_name] = ev_pct if ev_pct is not None else float("-inf")
        bundles.append(
            {
                "game_date": game_date,
                "away_team": away_team,
                "home_team": home_team,
                "rows": ordered_rows,
                "top_row": top_row,
                "top_ev": top_ev,
                "confidence": confidence,
                "moneyline_ev": type_scores.get("MONEYLINE"),
                "spread_ev": type_scores.get("SPREAD"),
                "total_ev": type_scores.get("TOTAL"),
            }
        )
    return bundles


def _official_items(rows: list[dict[str, Any]]) -> list[str]:
    items: list[str] = []
    for row in rows[:3]:
        rec_type = _safe_text(row.get("type"), "Recommendation").title()
        ev_pct = _format_ev_pct(row.get("ev_pct"))
        confidence = _safe_text(row.get("confidence"), "Unranked").title()
        odds = _format_moneyline(row.get("odds"))
        items.append(f"{rec_type}: {ev_pct} EV | {confidence} | Odds {odds}")
    if not items:
        items.append("No stored recommendation rows were available for this matchup.")
    return items


def _top_play_rows(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    top_rows: list[dict[str, str]] = []
    for row in rows[:4]:
        confidence = _safe_text(row.get("confidence"), "Unranked").title()
        odds = _format_moneyline(row.get("odds"))
        top_rows.append(
            {
                "name": _safe_text(row.get("type"), "Recommendation").title(),
                "value": _format_ev_pct(row.get("ev_pct")),
                "detail": f"{confidence} | Odds {odds}",
            }
        )
    return top_rows


def _sort_bundles(bundles: list[dict[str, Any]], sort: str) -> list[dict[str, Any]]:
    normalized_sort = _safe_text(sort, "date").lower()

    def _metric(bundle: dict[str, Any], key: str) -> float:
        value = _safe_float(bundle.get(key))
        return value if value is not None else float("-inf")

    if normalized_sort == "winner":
        return sorted(bundles, key=lambda bundle: (_metric(bundle, "moneyline_ev"), _metric(bundle, "top_ev")), reverse=True)
    if normalized_sort == "ats":
        return sorted(bundles, key=lambda bundle: (_metric(bundle, "spread_ev"), _metric(bundle, "top_ev")), reverse=True)
    if normalized_sort == "total":
        return sorted(bundles, key=lambda bundle: (_metric(bundle, "total_ev"), _metric(bundle, "top_ev")), reverse=True)
    return sorted(bundles, key=lambda bundle: (bundle.get("game_date") or "", -_metric(bundle, "top_ev")))


def _available_card_weeks(season: int | None = None) -> list[int]:
    resolved_season = int(season or latest_season())
    return sorted(week for week in available_weeks(resolved_season) if int(week) > 0)


def _resolved_week(selected_week: int, *, season: int | None = None) -> int:
    resolved_season = int(season or latest_season())
    try:
        requested_week = int(selected_week)
    except Exception:
        requested_week = int(default_week(resolved_season))
    return resolve_selected_value(requested_week, _available_card_weeks(resolved_season), default_week(resolved_season))


@lru_cache(maxsize=8)
def _nfl_schedule_kickoffs(season: int) -> dict[str, dict[str, Any]]:
    """{game_id: {kickoff, venue}} from `schedule_{season}.csv`.

    KICKOFF AND VENUE WERE ON DISK AND NEVER ON THE CARD. NCAAF's compact strip
    leads with a kickoff line and its main card carries a Venue row; NFL's card
    had neither key, so the shared football templates would have shown the
    card's `detail` ("SmartSim 2.0") where the kickoff belongs.

    `gametime` IS US-EASTERN, NOT UTC, and only for the REGULAR season.
    `nfl/sources.py` records the measurement that establishes it: regular-season
    `gameday`/`gametime` are US-local and agree with ESPN exactly on 2026 week 1
    (the CSV's four gamedays split 16 games 1/1/13/1 and ESPN returns the same),
    while the PRESEASON file's `gameday` is a UTC date. This reads the
    regular-season file only, so the Eastern anchor is the correct one -- and it
    is verified rather than assumed: `2026_01_NE_SEA` is `2026-09-09 20:20`
    here and ESPN's own `startTime` for that game is `2026-09-10T00:20Z`, which
    is the same instant.

    A row with no usable date is SKIPPED, never defaulted -- an absent kickoff
    renders as no kickoff line, which is honest; a defaulted one renders as a
    confident wrong time.
    """
    out: dict[str, dict[str, Any]] = {}
    try:
        from zoneinfo import ZoneInfo

        eastern = ZoneInfo("America/New_York")
    except Exception:  # noqa: BLE001 -- a kickoff label must never cost the board
        return out
    path = real_schedule_path(int(season))
    if not path.exists():
        return out
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                game_id = str(row.get("game_id") or "").strip()
                gameday = str(row.get("gameday") or "").strip()
                if not game_id or not gameday:
                    continue
                gametime = str(row.get("gametime") or "").strip() or "00:00"
                try:
                    local = datetime.strptime(f"{gameday} {gametime}", "%Y-%m-%d %H:%M").replace(tzinfo=eastern)
                except ValueError:
                    continue
                out[game_id] = {
                    "kickoff": local.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                    "venue": str(row.get("stadium") or "").strip() or None,
                }
    except Exception:  # noqa: BLE001
        return out
    return out


# The NFL card contract, mirroring `ncaaf_card`. Bumped when a template-visible
# key is added or removed, never for a value change.
_NFL_CARD_CONTRACT_VERSION = 1


def _nfl_market_margin_and_total(lines_entry: dict[str, Any] | None) -> tuple[float | None, float | None]:
    """(home margin, game total) from a `real_betting_lines` entry.

    SIGN, and it is the whole reason this is a function rather than two
    `.get()` calls at each call site. `run_line.home` is a BOOK HOME SPREAD --
    NEGATIVE when the home side is favoured (`-3.5` = home by 3.5). Every
    consumer in the football card family works in HOME MARGIN, where POSITIVE
    means home is favoured: `football_market_tiles`, `football_shared_predictions`
    and `_ncaaf_cover_probability` all take one. So this negates.

    Getting it backwards yields entirely plausible numbers pointing at the
    wrong team. `state.md` records a whole NFL analysis lost to exactly this
    confusion over nflverse's `spread_line`, and `ncaaf/cards.py` states the
    same convention for the same reason.
    """
    entry = lines_entry if isinstance(lines_entry, dict) else {}
    run_line = entry.get("run_line") if isinstance(entry.get("run_line"), dict) else {}
    total_runs = entry.get("total_runs") if isinstance(entry.get("total_runs"), dict) else {}
    book_home_spread = _safe_float(run_line.get("home"))
    market_margin = None if book_home_spread is None else -book_home_spread
    return market_margin, _safe_float(total_runs.get("line"))


def _nfl_team_context_items(
    season: int,
    week: int,
    *,
    away_abbr: str,
    home_abbr: str,
    away_name: str,
    home_name: str,
) -> list[dict[str, str]]:
    """Per-side game context for the card's Team Context panel.

    REAL AND ALREADY IN PRODUCTION, which is the only reason this panel is
    populated at all rather than left as an honest empty state.
    `nfl/game_context.py` reads `schedule_{season}.csv` -- the file its own
    docstring calls out as the one source that exists on Render, against the
    gitignored nflverse dump that does not -- and derives each side's implied
    team total from the closing spread and total. That module was built for the
    prop model; nothing on the board had ever read it.

    NCAAF's equivalent panel carries returning production, portal impact and
    coach continuity. Those have no NFL analogue and are NOT faked here: the
    panel shows what this sport actually knows about the two teams, and shows
    nothing when the schedule row carries no closing line (`game_context`
    skips such a row rather than defaulting it to zero).
    """
    try:
        from syndicate.features.nfl.game_context import team_context
    except Exception:  # noqa: BLE001 -- a context panel must never cost the board
        return []
    items: list[dict[str, str]] = []
    for abbr, name in ((away_abbr, away_name), (home_abbr, home_name)):
        try:
            context = team_context(season, week, abbr)
        except Exception:  # noqa: BLE001
            context = None
        if not isinstance(context, dict):
            continue
        implied = _safe_float(context.get("implied_total"))
        favoured_by = _safe_float(context.get("favoured_by"))
        if implied is None:
            continue
        side = "Home" if context.get("is_home") else "Away"
        # `favoured_by` is this team's own margin, positive when IT is
        # favoured -- already flipped for the away side by `game_context`.
        if favoured_by is None:
            line_text = "no closing line"
        elif favoured_by > 0:
            line_text = f"favoured by {favoured_by:.1f}"
        elif favoured_by < 0:
            line_text = f"underdog by {abs(favoured_by):.1f}"
        else:
            line_text = "pick'em"
        items.append(
            {
                "label": name,
                "value": f"Implied {implied:.1f}",
                "detail": f"{side} side, {line_text}, game total {_format_num(context.get('game_total'))}",
            }
        )
    return items


def _nfl_spread_text(margin: float | None, *, away_name: str, home_name: str) -> str:
    """A home-relative margin rendered the way a spread is read aloud.

    POSITIVE = home favoured, on both the model's number and the market's, so
    one function serves both and they cannot disagree about which side a sign
    points at.
    """
    if margin is None:
        return "No line"
    if margin == 0:
        return "Pick'em"
    favourite = home_name if margin > 0 else away_name
    return f"{favourite} -{abs(margin):.1f}"


def _nfl_matchup_context_items(
    *,
    away_name: str,
    home_name: str,
    market_margin: float | None,
    market_total: float | None,
    model_margin: float | None,
    model_total: float | None,
) -> list[dict[str, str]]:
    """The model against the market, side by side, for the Matchup panel.

    Both margins are HOME-RELATIVE (see `_nfl_market_margin_and_total`), so the
    difference is signed the same way: positive means the model likes the HOME
    side more than the book does.
    """
    items: list[dict[str, str]] = []
    if model_margin is not None or market_margin is not None:
        if market_margin is not None and model_margin is not None:
            market_text = _nfl_spread_text(market_margin, away_name=away_name, home_name=home_name)
            detail = f"Market {market_text} \u00b7 model {model_margin - market_margin:+.1f} vs market"
        else:
            detail = "No book has quoted this game yet"
        items.append(
            {
                "label": "Spread",
                "value": _nfl_spread_text(model_margin, away_name=away_name, home_name=home_name),
                "detail": detail,
            }
        )
    if model_total is not None or market_total is not None:
        if market_total is not None and model_total is not None:
            detail = f"Market {market_total:.1f} \u00b7 model {model_total - market_total:+.1f} vs market"
        else:
            detail = "No book has quoted this game yet"
        items.append(
            {
                "label": "Total",
                "value": f"{model_total:.1f}" if model_total is not None else "No model total",
                "detail": detail,
            }
        )
    return items


def _nfl_card_block(
    *,
    season: int,
    week: int,
    away_name: str,
    home_name: str,
    away_abbr: str,
    home_abbr: str,
    away_branding: Any,
    home_branding: Any,
    scoreboard: dict[str, Any],
    team_context_items: list[dict[str, str]] | None = None,
    matchup_context_items: list[dict[str, str]] | None = None,
    smartsim_reasons: list[dict[str, str]] | None = None,
    summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The `nfl_card` block, shaped exactly like NCAAF's `ncaaf_card`.

    THE TEMPLATES ARE THE CONTRACT AND THEY ARE SHARED.
    `shared/_game_card_ncaaf.html` and `shared/_scoreboard_strip_ncaaf.html`
    serve BOTH football codes (see their headers); they resolve their card
    block from `ncaaf_card` or `nfl_card`, so this shape is not optional
    decoration -- a missing `scoreboard` makes the main card fall back to the
    generic partial and the compact card render without its numbers.

    WHAT IS DELIBERATELY ABSENT. `rank`, `conference` and `school_name` are
    NCAAF's; an NFL team has none of them and the templates now omit the row
    rather than printing a dash. `coverage_score` / `coverage_tier` come from
    NCAAF's publication audit, which NFL has no equivalent of -- reported as
    `None`/`"projection_only"` rather than a fabricated grade.
    """
    away_context = {
        "abbreviation": away_abbr,
        "logo_url": away_branding.logo_url if away_branding else None,
        "primary_color": away_branding.primary_color if away_branding else None,
        "secondary_color": away_branding.secondary_color if away_branding else None,
    }
    home_context = {
        "abbreviation": home_abbr,
        "logo_url": home_branding.logo_url if home_branding else None,
        "primary_color": home_branding.primary_color if home_branding else None,
        "secondary_color": home_branding.secondary_color if home_branding else None,
    }
    return {
        "version": _NFL_CARD_CONTRACT_VERSION,
        "sport_label": "NFL",
        "summary": summary
        or {
            "coverage_score": None,
            "coverage_tier": "projection_only",
            "publication_status": "publishable",
            "publication_priority": None,
            "publication_ready": True,
            "ready_label": "Publication ready",
            "tier_badges": [{"label": "SmartSim 2.0", "active": True}],
        },
        "teams": {"home": home_context, "away": away_context},
        "scoreboard": scoreboard,
        "scoreboard_header": {
            "away": dict(away_context),
            "home": dict(home_context),
            "kickoff": scoreboard.get("kickoff"),
            "kickoff_label": scoreboard.get("kickoff_label") or scoreboard.get("kickoff"),
            "venue": scoreboard.get("venue"),
            "status": f"Week {week}",
            "status_detail": scoreboard.get("source_label"),
        },
        "team_context": {
            "items": list(team_context_items or []),
            "summary": "Each side's implied team total, derived from the closing spread and game total.",
        },
        "matchup_context": {
            "items": list(matchup_context_items or []),
            "summary": "The model's spread and total against the book's.",
        },
        "smartsim_reasons": list(smartsim_reasons or []),
        "context_sections": [],
    }


def _game_from_snapshot_bundle(bundle: dict[str, Any], season: int, week: int) -> dict[str, Any]:
    away_team = _safe_text(bundle.get("away_team"), "Away")
    home_team = _safe_text(bundle.get("home_team"), "Home")
    away_abbr = _team_abbr(away_team)
    home_abbr = _team_abbr(home_team)
    away_branding = _resolve_branding(away_team)
    home_branding = _resolve_branding(home_team)
    game_date = _safe_text(bundle.get("game_date"), "TBD")
    ordered_rows = bundle.get("rows") if isinstance(bundle.get("rows"), list) else []
    top_row = bundle.get("top_row") if isinstance(bundle.get("top_row"), dict) else {}
    top_ev = _safe_float(bundle.get("top_ev"))
    top_type = _safe_text(top_row.get("type"), "Recommendation").title()
    confidence = _safe_text(bundle.get("confidence"), "Snapshot").title()
    game_pk = f"{season}-{week}-{game_date}-{away_abbr}-{home_abbr}".replace(" ", "-")
    snapshot_prop_recommendations = nfl_prop_recommendations_for_matchup(
        season,
        week,
        away_full_name=away_team,
        home_full_name=home_team,
    )
    summary = (
        f"Stored weekly recommendation rows for {away_team} at {home_team}. "
        f"Top signal: {top_type} at {_format_ev_pct(top_ev)} EV."
    )
    # sim/betting/probability_rows are deliberately NOT set here (unlike
    # _game_from_smartsim_projection/_game_from_preseason_projection below and
    # in preseason_cards.py): the legacy upcoming_recs_*.csv snapshot this
    # path reads carries only type/confidence/ev_pct/odds per recommendation
    # row -- no home/away score projection, no numeric spread/total line
    # value, and no which-side-of-the-game the odds/confidence apply to.
    # There is no real, non-fabricated way to populate a projected score, a
    # market home_spread/total, or a home win probability from this data
    # shape, so the Box Score/Game tabs correctly fall back to their generic
    # "unavailable" empty states for this (historical, 2025-only) path
    # rather than inventing numbers.
    # A SCOREBOARD WITH NO PROJECTION IN IT, and that is the honest shape for
    # this path. The comment above records why: the legacy `upcoming_recs_*.csv`
    # snapshot carries type/confidence/ev_pct/odds per recommendation row and
    # NOTHING that could become a projected score, a market line or a win
    # probability. The football templates omit each fact whose value is absent,
    # so this card renders crests, abbreviations and a real kickoff -- and no
    # numbers it does not have. That is a strictly better compact card than the
    # generic strip's two paragraphs of prose, without inventing anything.
    schedule_row = _nfl_schedule_kickoffs(season).get(game_pk) or {}
    kickoff = schedule_row.get("kickoff") or ""
    snapshot_scoreboard = {
        "source_label": confidence,
        "kickoff": kickoff or game_date,
        "kickoff_label": format_kickoff_label(kickoff) or game_date,
        "venue": schedule_row.get("venue") or "Venue unavailable",
    }
    return {
        "gamePk": game_pk,
        # See `_game_from_smartsim_projection` for the measurement behind this
        # string. BOTH builders move, not just the one that serves the current
        # season: a board that changes shape depending on which artifact backed
        # it is the same class of defect as a board that never changes shape at
        # all, and this path still serves every stored 2025 week.
        "card_variant": "nfl_main",
        "away": {
            "abbr": away_abbr,
            "name": away_team,
            "logo_url": away_branding.logo_url if away_branding else None,
            "primary_color": away_branding.primary_color if away_branding else None,
            "secondary_color": away_branding.secondary_color if away_branding else None,
        },
        "home": {
            "abbr": home_abbr,
            "name": home_team,
            "logo_url": home_branding.logo_url if home_branding else None,
            "primary_color": home_branding.primary_color if home_branding else None,
            "secondary_color": home_branding.secondary_color if home_branding else None,
        },
        "href": f"/nfl/game/{game_pk}?season={season}&week={week}",
        "href_label": "Open NFL game detail",
        "status": f"Week {week}",
        "detail": game_date,
        # Attached on BOTH card paths, not just the SmartSim2 one that serves
        # 2026. A season with a stored recs snapshot never reaches the fallback,
        # so attaching only there would have left every such week without props
        # while looking, from the served payload, exactly like a week that had
        # none to show. Omitted entirely when empty -- see the SmartSim path.
        **({"prop_recommendations": snapshot_prop_recommendations} if any(snapshot_prop_recommendations.values()) else {}),
        "summary": summary,
        "metrics": [
            {"label": "Kickoff", "value": game_date},
            {"label": "Signals", "value": str(len(ordered_rows))},
            {"label": "Top EV", "value": _format_ev_pct(top_ev)},
            {"label": "Best signal", "value": top_type},
        ],
        "shared_top_play_rows": _top_play_rows(ordered_rows),
        "nfl_card": _nfl_card_block(
            season=season,
            week=week,
            away_name=away_team,
            home_name=home_team,
            away_abbr=away_abbr,
            home_abbr=home_abbr,
            away_branding=away_branding,
            home_branding=home_branding,
            scoreboard=snapshot_scoreboard,
            summary={
                "coverage_score": None,
                "coverage_tier": "snapshot_only",
                "publication_status": "publishable",
                "publication_priority": None,
                "publication_ready": True,
                "ready_label": "Stored weekly snapshot",
                "tier_badges": [{"label": "Snapshot", "active": True}],
            },
        ),
        "panels": [
            {
                "eyebrow": "Weekly snapshot",
                "title": confidence,
                "body": "NFL cards now summarize the stored weekly recommendation snapshot for this matchup instead of proxying the sibling source app.",
                "items": _official_items(ordered_rows),
            },
            {
                "eyebrow": "Signal mix",
                "title": f"Top EV {_format_ev_pct(top_ev)} | {len(ordered_rows)} stored rows",
                "body": "Snapshot rows are grouped by matchup so cards, game detail, and live lens can share the same local weekly artifact lane.",
                "items": [
                    f"Moneyline rows: {sum(1 for row in ordered_rows if _safe_text(row.get('type')).upper() == 'MONEYLINE')}",
                    f"Spread rows: {sum(1 for row in ordered_rows if _safe_text(row.get('type')).upper() == 'SPREAD')}",
                    f"Total rows: {sum(1 for row in ordered_rows if _safe_text(row.get('type')).upper() == 'TOTAL')}",
                ],
            },
            {
                "eyebrow": "Game context",
                "title": f"{season} Week {week}",
                "body": f"{away_team} at {home_team} on {game_date}.",
                "items": [
                    f"Teams: {away_team} at {home_team}",
                    f"Snapshot-backed game key: {game_pk}",
                    "Pick-side fields are not preserved in the weekly snapshot, so this board summarizes stored signal types and EV instead of full source-card parity.",
                ],
            },
        ],
    }


def _game_from_smartsim_projection(projection: Any, season: int, week: int) -> dict[str, Any]:
    """Real-data fallback for a week with no upcoming_recs_*.csv snapshot
    but a real generated SmartSimNflProjection (e.g. a new season the
    older recs-snapshot pipeline has never been refreshed for) -- mirrors
    _game_from_snapshot_bundle's exact output shape, mirroring
    syndicate.features.ncaaf.cards's own engine/SmartSim2-standalone
    split for the same reason."""
    away_team = str(projection.away_team or "Away").strip() or "Away"
    home_team = str(projection.home_team or "Home").strip() or "Home"
    away_branding = _resolve_branding(away_team)
    home_branding = _resolve_branding(home_team)
    away_abbr = away_branding.abbreviation if away_branding else _team_abbr(away_team)
    home_abbr = home_branding.abbreviation if home_branding else _team_abbr(home_team)
    away_name = away_branding.display_name if away_branding else away_team
    home_name = home_branding.display_name if home_branding else home_team
    margin = projection.margin_mean
    if margin > 0:
        spread_label = f"{home_name} by {abs(margin):.1f}"
    elif margin < 0:
        spread_label = f"{away_name} by {abs(margin):.1f}"
    else:
        spread_label = "Pick'em"
    win_probability = format_pct(projection.home_win_rate)
    game_pk = str(projection.game_id or f"{season}-{week}-{away_abbr}-{home_abbr}").replace(" ", "-")
    summary = (
        f"SmartSim 2.0 projects {home_name} {round(projection.home_score_mean, 1)} - {round(projection.away_score_mean, 1)} {away_name} "
        f"with a projected total of {round(projection.total_mean, 1)} and a home win probability of {win_probability}. "
        f"No stored recommendation snapshot exists for this week yet."
    )
    # Real data plumbing for the shared board contract's Box Score/Game/Props
    # tabs (game_board_contract.py's _build_period_rows/_build_probability_rows/
    # _build_box_sections all read these keys, unconditionally, for every
    # sport -- NFL just never set them, so real projection data never reached
    # those tabs even though it was computed right here). p_home_win is the
    # model's own win probability (never fabricated), always included;
    # home_spread/total are only ever set when a real quoted market line was
    # found for this exact matchup -- never fabricated when absent.
    lines_entry = _nfl_real_lines_for_matchup(season, away_full_name=away_name, home_full_name=home_name)
    betting: dict[str, Any] = {"p_home_win": projection.home_win_rate}
    if lines_entry:
        run_line = lines_entry.get("run_line") if isinstance(lines_entry.get("run_line"), dict) else {}
        total_runs = lines_entry.get("total_runs") if isinstance(lines_entry.get("total_runs"), dict) else {}
        if run_line.get("home") is not None:
            betting["home_spread"] = run_line.get("home")
        if total_runs.get("line") is not None:
            betting["total"] = total_runs.get("line")
    # prop_recommendations. This was deliberately left UNSET for as long as NFL
    # cards existed, and the reason was sound: the prop feed carries a player's
    # name but no home/away side, `_build_prop_rows` needs rows split into
    # "away"/"home" lists, and there was "no reliable real source here for that
    # split". Forcing a guess would mis-attribute a real prop to the wrong team.
    #
    # THAT REASON EXPIRED, and only the source changed -- not the standard.
    # Measured on production 2026-08-27, the feed is still exactly as described:
    # `team` is empty in 0 of 294 real week-1 rows. What is new is that the
    # roster snapshot is now built, published and present on the web service's
    # disk (654,176 B), so the split is a JOIN against a real artifact rather
    # than an inference from the odds row. `nfl_prop_recommendations_for_matchup`
    # refuses on an unresolved name, a name that collides across teams, and --
    # the one that makes mis-attribution structurally impossible -- any player
    # whose roster team is not one of THIS game's two teams.
    #
    # Empty is still a first-class outcome: no roster artifact, or no capture
    # for this week, yields {} and the card falls back to the same honest "no
    # props" empty state it has always shown.
    prop_recommendations = nfl_prop_recommendations_for_matchup(
        season,
        week,
        away_full_name=away_name,
        home_full_name=home_name,
    )
    # THE MARKET LINE, IN HOME-MARGIN UNITS. `betting` above stores the BOOK's
    # own home spread (negative = home favoured) because that is what
    # `_shared_markets` publishes; every football CARD helper works in home
    # margin instead. One conversion, named, rather than a sign flip inline at
    # three call sites.
    market_margin, market_total = _nfl_market_margin_and_total(lines_entry)
    schedule_row = _nfl_schedule_kickoffs(season).get(game_pk) or {}
    kickoff = schedule_row.get("kickoff") or ""
    scoreboard = {
        "home_points": round(projection.home_score_mean, 1),
        "away_points": round(projection.away_score_mean, 1),
        "total_points": round(projection.total_mean, 1),
        "spread_label": spread_label,
        # THE SAME FACT, ABBREVIATED, FOR THE COMPACT CARD ONLY.
        # `.cards-strip-pregame-fact` clips with no wrap and no ellipsis;
        # measured in a browser on the rebuilt strip, "Seattle Seahawks by 0.3"
        # rendered as "Seattle Seah..." and "Chicago Bears by 2.2" as
        # "Chicago Bea...". NCAAF never hit this because its label carries a
        # SCHOOL name ("TCU by 12.3"), which is already short.
        #
        # The full-name label is KEPT and still what the main card's "Projected
        # spread" callout shows -- that panel has the room, and a card that has
        # room should print the team's name. Two labels, one number, chosen by
        # the surface's width; `ncaaf/cards.py:_market_metric_row` records the
        # same trade for the same reason.
        "spread_label_short": (
            "Pick'em"
            if projection.margin_mean == 0
            else f"{home_abbr if projection.margin_mean > 0 else away_abbr} by {abs(projection.margin_mean):.1f}"
        ),
        "win_probability": win_probability,
        "home_win_probability": projection.home_win_rate,
        "source_label": "SmartSim 2.0",
        "kickoff": kickoff,
        "kickoff_label": format_kickoff_label(kickoff) or "Kickoff unavailable",
        "venue": schedule_row.get("venue") or "Venue unavailable",
        "market_margin": market_margin,
        "market_total": market_total,
        "smartsim2_available": True,
        "smartsim2_margin": projection.margin_mean,
        "smartsim2_margin_stdev": projection.margin_stdev,
        "smartsim2_total_points": projection.total_mean,
        "smartsim2_total_stdev": projection.total_stdev,
    }
    return {
        "gamePk": game_pk,
        # `nfl_main`, not `shared_default`. This one string is the whole
        # dispatch: `shared/_game_card.html` and `shared/_scoreboard_strip.html`
        # branch on `card_variant` and nothing else, so every NFL board card
        # fell through to the GENERIC partials while NCAAF's reached the
        # football ones. Measured in a browser against production 2026-09-07,
        # the two served pages side by side:
        #
        #   compact card height   NCAAF 181px uniform x51 | NFL 643-1085px,
        #                                                   16 distinct heights
        #   crest <img> in strip  NCAAF 102               | NFL 0
        #
        # 16 distinct heights on 16 cards is the direct evidence: each card was
        # being sized by a different-length paragraph of prose (`game.summary`
        # plus the first panel's body, both rendered unconditionally by
        # `_scoreboard_strip_generic.html`).
        "card_variant": "nfl_main",
        "away": {
            "abbr": away_abbr,
            "name": away_name,
            "logo_url": away_branding.logo_url if away_branding else None,
            "primary_color": away_branding.primary_color if away_branding else None,
            "secondary_color": away_branding.secondary_color if away_branding else None,
        },
        "home": {
            "abbr": home_abbr,
            "name": home_name,
            "logo_url": home_branding.logo_url if home_branding else None,
            "primary_color": home_branding.primary_color if home_branding else None,
            "secondary_color": home_branding.secondary_color if home_branding else None,
        },
        "href": f"/nfl/game/{game_pk}?season={season}&week={week}",
        "href_label": "Open NFL game detail",
        "status": f"Week {week}",
        "detail": "SmartSim 2.0",
        # Only when there is something real to show. `_build_prop_rows` treats a
        # missing key and an empty one identically, and this card family's
        # contract -- pinned by test_nfl_market_board -- is that a key is ABSENT
        # rather than empty when no real source backs it. An empty dict here
        # would read as "props were considered and there are none", which is a
        # different claim from "this week has no capture".
        **({"prop_recommendations": prop_recommendations} if any(prop_recommendations.values()) else {}),
        "summary": summary,
        "metrics": [
            {"label": "Home mean", "value": round(projection.home_score_mean, 1)},
            {"label": "Away mean", "value": round(projection.away_score_mean, 1)},
            {"label": "Projected spread", "value": spread_label},
            {"label": "Win probability", "value": win_probability},
        ],
        "sim": {
            "periods": {
                "full": {
                    "away_mean": projection.away_score_mean,
                    "home_mean": projection.home_score_mean,
                    "total_mean": projection.total_mean,
                    "margin_mean": projection.margin_mean,
                    "p_home_win": projection.home_win_rate,
                }
            },
            "score": {"away_mean": projection.away_score_mean, "home_mean": projection.home_score_mean},
        },
        "betting": betting,
        # TOP LEVEL, beside `nfl_card` and NOT inside it.
        # `publication_adapter._shared_predictions` reads `game["predictions"]`.
        # NCAAF's first cut of the same block went inside its sport key, where
        # nothing reads it -- production deployed clean and still served 0/51
        # non-null means. NFL's four MEANS were already arriving via the
        # `sim.periods.full` fallback, which is why the gap here was the two
        # PROBABILITY legs only: `home_cover` and `total_over` were null on
        # 16/16 served cards while the same payload carried
        # `markets.spread.home -3.5` and `markets.total.line 44.5`.
        "predictions": football_shared_predictions(
            projection, market_margin=market_margin, market_total=market_total
        ),
        # THE MODEL AGAINST THE MARKET. These four tiles were `Home mean /
        # Away mean / Projected spread / Win probability` -- byte-identical to
        # this card's own `metrics` list rendered directly above them, so the
        # market row restated the projection twice and showed the book's number
        # nowhere.
        "market_tiles": football_market_tiles(
            # ABBREVIATIONS, not display names, and the constraint is width not
            # taste. `.cards-market-tile` shows roughly six characters at the
            # tile's value size; NCAAF passes school names, which are already
            # short ("TCU -12.3"), while an NFL display name is not
            # ("Seattle Seahawks -3.5" overruns the neighbouring tile). The
            # same measurement that set `_market_metric_row`'s compact format
            # in `ncaaf/cards.py` applies here, and "SEA -3.5" is unambiguous
            # with "NE @ SEA" printed directly above it.
            home_team=home_abbr,
            away_team=away_abbr,
            market_margin=market_margin,
            market_total=market_total,
            market_book_count=0,
            market_source="real_betting_lines" if lines_entry else None,
            model_margin=projection.margin_mean,
            model_total=projection.total_mean,
            home_win_rate=projection.home_win_rate,
        ),
        "nfl_card": _nfl_card_block(
            season=season,
            week=week,
            away_name=away_name,
            home_name=home_name,
            away_abbr=away_abbr,
            home_abbr=home_abbr,
            away_branding=away_branding,
            home_branding=home_branding,
            scoreboard=scoreboard,
            team_context_items=_nfl_team_context_items(
                season,
                week,
                away_abbr=away_abbr,
                home_abbr=home_abbr,
                away_name=away_name,
                home_name=home_name,
            ),
            matchup_context_items=_nfl_matchup_context_items(
                away_name=away_name,
                home_name=home_name,
                market_margin=market_margin,
                market_total=market_total,
                model_margin=projection.margin_mean,
                model_total=projection.total_mean,
            ),
        ),
        "probability_rows": [
            {
                "label": "Full Game",
                "away_pct": (1.0 - projection.home_win_rate) * 100.0,
                "home_pct": projection.home_win_rate * 100.0,
                "summary": f"Home win probability {win_probability}",
            }
        ],
        "shared_top_play_rows": [],
        "panels": [
            {
                "eyebrow": "SmartSim 2.0",
                "title": "Projection contract",
                "body": "No stored NFL weekly recommendation snapshot exists for this week yet, so this card shows SmartSim 2.0's own real Monte Carlo projection directly, unblended.",
                "items": [
                    f"Home mean: {round(projection.home_score_mean, 1)}",
                    f"Away mean: {round(projection.away_score_mean, 1)}",
                    f"Projected spread: {spread_label}",
                    f"Projected total: {round(projection.total_mean, 1)}",
                    f"Win probability: {win_probability}",
                ],
            },
            {
                "eyebrow": "Game context",
                "title": f"{season} Week {week}",
                "body": f"{away_name} at {home_name}.",
                "items": [
                    f"Teams: {away_name} at {home_name}",
                    f"Projection source: SmartSim 2.0 ({projection.rating_source})",
                    f"Real game id: {game_pk}",
                ],
            },
        ],
    }


def build_cards_page_context(selected_week: int, *, season: int | None = None, sort: str = "date") -> dict[str, Any]:
    resolved_season = int(season or latest_season())
    resolved_week = _resolved_week(selected_week or default_week(resolved_season), season=resolved_season)
    season = resolved_season
    rows = list(_read_snapshot_rows(season, resolved_week))
    bundles = _sort_bundles(_group_snapshot_rows(rows), sort)
    games = [_game_from_snapshot_bundle(bundle, season, resolved_week) for bundle in bundles]
    using_smartsim_fallback = False
    if not games:
        # No stored recs snapshot for this (season, week) -- real, e.g.
        # for a season the older recs-snapshot pipeline has never been
        # refreshed for (2026) -- fall back to the real generated
        # SmartSim2 projection artifact before giving up to an empty
        # state, mirroring NCAAF cards.py's own engine/SmartSim2-standalone
        # split.
        projections = read_projection_artifact(season=season, week=resolved_week, data_root=default_nfl_source_root())
        if projections:
            games = [_game_from_smartsim_projection(projection, season, resolved_week) for projection in projections]
            using_smartsim_fallback = True
    using_sample_data = False

    # ---------------------------------------------------------------------
    # LIVE GAME STATE. Without this the NFL regular-season board is
    # PERMANENTLY PREGAME.
    #
    # `live_game_state.py` has existed for weeks and its ONLY callers were
    # `preseason_cards.py` (always `SEASONTYPE_PRESEASON`) and an unrelated
    # fantasy-news module. `scripts/poll_nfl_live_state.py`'s own docstring
    # says so outright: "the regular season is not wired at all". Neither
    # builder above ever set `game["live_state"]` -- which is the key
    # `publication_adapter._shared_game_state` reads to produce
    # `shared_is_live` / `shared_game_state`, the fields the card template
    # already branches on.
    #
    # MEASURED 2026-08-13, the defect this closes: 117 live in-game NFL
    # market rows with `state=pregame, score=-` while ESPN had two of those
    # games in Q1. Measured again 2026-09-07: 71 NFL board rows, all
    # pregame, zero live.
    #
    # SEASONTYPE_REGULAR, not PRESEASON. The constant has been defined and
    # unused since the preseason work -- passing the wrong one here would
    # fetch a scoreboard for the wrong season type and the join would match
    # nothing, which looks exactly like "no games are live".
    #
    # NEVER FATAL. A cards page that renders without live state is degraded;
    # one that 500s because ESPN was slow is broken. The coverage counts are
    # printed rather than swallowed, because "the join found nothing" and
    # "the join worked and every game is pregame" produce the same board and
    # are different defects.
    if games:
        try:
            from syndicate.features.nfl.live_game_state import (
                SEASONTYPE_REGULAR,
                attach_nfl_live_game_state,
                nfl_game_state_index,
            )

            coverage = attach_nfl_live_game_state(
                games,
                nfl_game_state_index(season, resolved_week,
                                     seasontype=SEASONTYPE_REGULAR),
            )
            # KICKOFF, SECOND SOURCE. `_nfl_schedule_kickoffs` is the primary
            # one and it needs no network, but a card whose `game_id` is not in
            # `schedule_{season}.csv` would otherwise show "Kickoff unavailable"
            # where the compact strip's head goes. ESPN has just been asked for
            # this exact week, so its `startTime` is free here.
            #
            # `setdefault` semantics by hand: this only ever FILLS a hole. A
            # kickoff already read from the schedule wins, because that file is
            # the source of record for the board's own week model.
            for game in games:
                card = game.get("nfl_card")
                board = card.get("scoreboard") if isinstance(card, dict) else None
                if not isinstance(board, dict) or board.get("kickoff"):
                    continue
                start_time = game.get("startTime")
                if not start_time:
                    continue
                board["kickoff"] = start_time
                board["kickoff_label"] = format_kickoff_label(start_time) or board.get("kickoff_label")
            print(f"[nfl_cards] LIVE_STATE season={season} week={resolved_week} "
                  f"{coverage}", flush=True)
        except Exception as exc:
            print(f"[nfl_cards] LIVE_STATE_FAILED season={season} "
                  f"week={resolved_week} error={type(exc).__name__}: {exc}",
                  flush=True)

    weeks = _available_card_weeks(season)
    prev_week, next_week = neighboring_values(weeks, resolved_week, fallback=resolved_week)
    scoreboard_items = [
        {
            "target_id": f"game-{game['gamePk']}",
            "label": f"{game['away']['abbr']} @ {game['home']['abbr']}",
            "status": game["status"],
        }
        for game in games
    ]
    if using_smartsim_fallback:
        source_path = str(default_nfl_source_root() / f"smartsim2_projections_{season}_wk{resolved_week}.csv")
        source_title = "NFL SmartSim 2.0 standalone projections"
    else:
        source_path = _snapshot_source_path(season, resolved_week)
        source_title = "NFL weekly recommendation snapshot" if games else "NFL cards unavailable"
    return apply_game_board_contract(
        {
            "date": f"{season} Week {resolved_week}",
            "requested_date": f"{season} Week {selected_week}",
            "prev_date": str(prev_week),
            "next_date": str(next_week),
            "control_action": "/nfl/cards",
            "controls_prev_href": f"/nfl/cards?season={season}&week={prev_week}",
            "controls_next_href": f"/nfl/cards?season={season}&week={next_week}",
            "control_label": "Week",
            "control_type": "number",
            "control_name": "week",
            "control_value": str(resolved_week),
            "hidden_fields": [{"name": "season", "value": str(season)}],
            "module_links": build_module_links(resolved_week, "Cards", season=season),
            "games": games,
            "scoreboard_items": scoreboard_items,
            "source_path": source_path,
            "source_title": source_title,
            "empty_state": {
                "eyebrow": "NFL cards",
                "title": "No game cards were available for this week",
                "body": "Neither a stored NFL weekly recommendation snapshot nor a real SmartSim 2.0 projection artifact was available for the requested season and week.",
                "list_items": [
                    f"Season: {season}",
                    f"Week: {selected_week}",
                ],
            } if not games else None,
            "using_sample_data": using_sample_data,
            "route_path": "/nfl/cards",
            "intro_title": "NFL Cards",
            "intro_body": "NFL cards now aggregate stored weekly recommendation snapshots into a shared matchup board, so cards, game detail, and live lens can run from the local mirror lane. Falls back to real SmartSim 2.0 projections when no stored snapshot exists for a week yet.",
            "cards_control_links": [
                {"label": "Betting Card", "href": f"/nfl/season/{season}/betting-card?week={resolved_week}"},
                {"label": "Picks", "href": f"/nfl/picks?season={season}&week={resolved_week}"},
                {"label": "Live Lens", "href": f"/nfl/live-lens?season={season}&week={resolved_week}"},
            ],
            "header_stats": [
                {"label": "Games", "value": str(len(games))},
                {"label": "Season", "value": str(season)},
                {"label": "Week", "value": str(resolved_week)},
                {"label": "Source", "value": "SmartSim 2.0" if using_smartsim_fallback else ("Snapshot" if games else "No data")},
            ],
            "cards_stylesheet": None,
            "cards_grid_class": "cards-grid",
            "show_source_summary": True,
            "show_intro": True,
            "active_sport_name": "NFL",
        },
        sport="nfl",
        module="cards",
        source_kind="local_artifact",
        live_lens_integrated=False,
    )


# ---------------------------------------------------------------------------
# Market board (Layer 1) -- real market odds joined against real SmartSim 2.0
# projections (syndicate/features/nfl/smartsim2_projection.py, generated by
# scripts/generate_smartsim2_nfl_projections.py). Independent of the
# recs-snapshot-based build_cards_page_context above -- that page's data
# source and this one aren't related, deliberately not touched here.
# ---------------------------------------------------------------------------


def nfl_projection_available_weeks(season: int) -> list[int]:
    """Weeks that actually have a generated smartsim2_projections_{season}_wk*.csv
    artifact -- NOT syndicate.features.nfl.sources.available_weeks(), which
    tracks the unrelated upcoming_recs_*.csv snapshot (only weeks 17/19/21
    exist there for season 2025) and would silently break market-board
    week navigation for any week this session generated projections for."""
    pattern = str(default_nfl_source_root() / f"smartsim2_projections_{season}_wk*.csv")
    weeks: list[int] = []
    for path in glob.glob(pattern):
        match = re.search(r"_wk(\d+)\.csv$", path)
        if match:
            weeks.append(int(match.group(1)))
    return sorted(set(weeks))


@lru_cache(maxsize=8)
def _nfl_real_lines_index(season: int) -> dict[str, dict[str, Any]]:
    """Latest real quoted line per matchup, keyed by "{away} @ {home}" full
    team names -- merges every daily real_betting_lines_{season}_*.json
    file's "lines" dict in filename (date) order, so the freshest quote for
    each matchup wins. That is the correct semantic for the current-week
    board. Caveat (verified 2026-08-02): a single file's 272 keys are
    unique -- regular-season divisional rematches swap venues so "{away} @
    {home}" never collides during the regular season -- but a PLAYOFF game
    repeating a regular-season venue pairing shares its key, so once
    January files land, a past regular-season week's entry is retroactively
    the playoff quote. Historical/backtest consumers must read the dated
    file for the day in question instead of this merged index."""
    index: dict[str, dict[str, Any]] = {}
    pattern = os.path.join(str(default_nfl_source_root()), f"real_betting_lines_{season}_*.json")
    for path in sorted(glob.glob(pattern)):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception:
            continue
        lines = payload.get("lines") if isinstance(payload, dict) else None
        if isinstance(lines, dict):
            index.update(lines)
    return index


def _nfl_real_lines_for_matchup(season: int, *, away_full_name: str, home_full_name: str) -> dict[str, Any] | None:
    return _nfl_real_lines_index(season).get(f"{away_full_name} @ {home_full_name}")


def _nfl_cover_probability(*, line: float, mean: float | None, stdev: float | None) -> float | None:
    """Delegates to `shared/football_cards.cover_probability`.

    This was a verbatim copy of NCAAF's, and its own docstring said so
    ("mirrors ..._ncaaf_cover_probability exactly"). A copy that ANNOUNCES it
    is a copy is still a copy -- and the two boards did diverge, in the CALLER
    rather than here: NCAAF fed it a market line from the card builder and
    published `home_cover`/`total_over` on 51/51 cards, while NFL never called
    it from the card builder at all and published null on 16/16.
    """
    return cover_probability(line=line, mean=mean, stdev=stdev)


_NFL_MARKET_BOARD_DISPLAY_LABELS = {
    "moneyline_home": "Moneyline",
    "moneyline_away": "Moneyline",
    "spread_home": "Spread",
    "spread_away": "Spread",
    "total": "Total",
}


def _nfl_prices_from_lines_entry(lines_entry: dict[str, Any] | None, *, home_full_name: str, away_full_name: str) -> dict[str, Any]:
    """Per-side spread/total prices (and the away spread line) for one
    real_betting_lines entry. The flat run_line/total_runs fields only carry
    the home line and the over/under prices; the per-side spread prices live
    in the raw ``markets`` passthrough (keys ``spreads``/``totals``, outcomes
    keyed by full team name / Over / Under)."""
    entry = lines_entry if isinstance(lines_entry, dict) else {}
    total_runs = entry.get("total_runs") if isinstance(entry.get("total_runs"), dict) else {}
    result: dict[str, Any] = {
        "spread_home_line": (entry.get("run_line") or {}).get("home") if isinstance(entry.get("run_line"), dict) else None,
        "spread_away_line": None,
        "spread_home_price": None,
        "spread_away_price": None,
        "total_over_price": total_runs.get("over"),
        "total_under_price": total_runs.get("under"),
    }
    markets = entry.get("markets") if isinstance(entry.get("markets"), list) else []
    for market in markets:
        if not isinstance(market, dict):
            continue
        outcomes = market.get("outcomes") if isinstance(market.get("outcomes"), list) else []
        market_key = market.get("key")
        if market_key == "spreads":
            for outcome in outcomes:
                if not isinstance(outcome, dict):
                    continue
                name = str(outcome.get("name") or "")
                if name == home_full_name:
                    result["spread_home_price"] = outcome.get("price")
                    if outcome.get("point") is not None:
                        result["spread_home_line"] = outcome.get("point")
                elif name == away_full_name:
                    result["spread_away_price"] = outcome.get("price")
                    if outcome.get("point") is not None:
                        result["spread_away_line"] = outcome.get("point")
        elif market_key == "totals":
            for outcome in outcomes:
                if not isinstance(outcome, dict):
                    continue
                name = str(outcome.get("name") or "").strip().lower()
                if name == "over" and outcome.get("price") is not None:
                    result["total_over_price"] = outcome.get("price")
                elif name == "under" and outcome.get("price") is not None:
                    result["total_under_price"] = outcome.get("price")
    if result["spread_away_line"] is None and result["spread_home_line"] is not None:
        try:
            result["spread_away_line"] = -float(result["spread_home_line"])
        except (TypeError, ValueError):
            result["spread_away_line"] = None
    return result


def _nfl_market_board_rows_for_game(
    *,
    game_id: Any,
    home_moneyline: Any,
    away_moneyline: Any,
    spread_line: Any,
    total_line: Any,
    model_margin: Any,
    model_total: Any,
    model_margin_stdev: Any,
    model_total_stdev: Any,
    home_win_probability: Any,
    spread_away_line: Any = None,
    spread_home_price: Any = None,
    spread_away_price: Any = None,
    total_over_price: Any = None,
    total_under_price: Any = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Raw odds + sim rows for one NFL game's moneyline/spread/total
    markets -- mirrors syndicate.features.ncaaf.cards._ncaaf_market_board_rows_for_game.
    No player-prop rows: no props pipeline exists for NFL yet.

    ``spread_line`` is bet notation (home -10.5 = home must win by more than
    10.5), so the margin threshold for the cover probability is its NEGATION
    -- the first pass used it directly, which turned a big favorite's cover
    probability into near-certainty (P(margin > -10.5) instead of
    P(margin > +10.5)). NCAAF's builder negates its CFBD spread the same way
    (market_margin = -mean(spreads))."""
    odds_rows: list[dict[str, Any]] = []
    sim_rows: list[dict[str, Any]] = []

    home_prob = None
    try:
        home_prob = float(home_win_probability) if home_win_probability is not None else None
    except (TypeError, ValueError):
        home_prob = None
    if home_moneyline is not None and away_moneyline is not None:
        odds_rows.append({"game_id": game_id, "market": "moneyline_home", "period": "full_game", "entity": None, "side": "home", "odds": home_moneyline, "market_type": "game"})
        odds_rows.append({"game_id": game_id, "market": "moneyline_away", "period": "full_game", "entity": None, "side": "away", "odds": away_moneyline, "market_type": "game"})
        if home_prob is not None:
            model_side = "home" if home_prob >= 0.5 else "away"
            sim_rows.append({"game_id": game_id, "market": "moneyline_home", "period": "full_game", "entity": None, "sim_projection": home_prob, "model_side": model_side, "sim_source": "nfl_model"})
            sim_rows.append({"game_id": game_id, "market": "moneyline_away", "period": "full_game", "entity": None, "sim_projection": 1.0 - home_prob, "model_side": model_side, "sim_source": "nfl_model"})

    try:
        home_spread = float(spread_line) if spread_line is not None else None
    except (TypeError, ValueError):
        home_spread = None
    if home_spread is not None:
        try:
            away_spread = float(spread_away_line) if spread_away_line is not None else -home_spread
        except (TypeError, ValueError):
            away_spread = -home_spread
        odds_rows.append({"game_id": game_id, "market": "spread_home", "period": "full_game", "entity": None, "side": "home", "line": home_spread, "odds": spread_home_price, "market_type": "game"})
        odds_rows.append({"game_id": game_id, "market": "spread_away", "period": "full_game", "entity": None, "side": "away", "line": away_spread, "odds": spread_away_price, "market_type": "game"})
        if model_margin is not None:
            cover_prob = _nfl_cover_probability(line=-home_spread, mean=model_margin, stdev=model_margin_stdev)
            model_side = None if cover_prob is None else ("home" if cover_prob >= 0.5 else "away")
            sim_rows.append({"game_id": game_id, "market": "spread_home", "period": "full_game", "entity": None, "sim_projection": cover_prob, "model_side": model_side, "projected_value": model_margin, "sim_source": "nfl_model"})
            sim_rows.append({"game_id": game_id, "market": "spread_away", "period": "full_game", "entity": None, "sim_projection": None if cover_prob is None else 1.0 - cover_prob, "model_side": model_side, "projected_value": model_margin, "sim_source": "nfl_model"})

    try:
        total_line_value = float(total_line) if total_line is not None else None
    except (TypeError, ValueError):
        total_line_value = None
    if total_line_value is not None:
        odds_rows.append({"game_id": game_id, "market": "total", "period": "full_game", "entity": None, "side": "over", "line": total_line_value, "odds": total_over_price, "market_type": "game"})
        odds_rows.append({"game_id": game_id, "market": "total", "period": "full_game", "entity": None, "side": "under", "line": total_line_value, "odds": total_under_price, "market_type": "game"})
        if model_total is not None:
            over_prob = _nfl_cover_probability(line=total_line_value, mean=model_total, stdev=model_total_stdev)
            # One sim row serves both Over and Under odds rows (same join
            # key); join_odds_to_sim derives each side's probability from
            # model_prob_over -- the same two-sided contract MLB uses.
            sim_rows.append({"game_id": game_id, "market": "total", "period": "full_game", "entity": None, "model_prob_over": over_prob, "projected_value": model_total, "sim_source": "nfl_model"})

    return odds_rows, sim_rows


def build_nfl_market_board(season: int, week: int) -> dict[str, Any]:
    """Layer 1 market/odds inventory for NFL game markets (moneyline,
    spread, total) plus player props -- mirrors
    syndicate.features.ncaaf.cards.build_ncaaf_market_board. Games and the
    game-market model signal come from the real SmartSim 2.0 projection
    artifact for this (season, week) -- see
    scripts/generate_smartsim2_nfl_projections.py; real market lines come
    from _nfl_real_lines_index; player-prop rows come from
    syndicate.features.nfl.props (real quoted lines joined against a real
    season-to-date player rate, not a trained model -- see that module's
    docstring)."""
    projections = read_projection_artifact(season=season, week=week, data_root=default_nfl_source_root())
    weeks = nfl_projection_available_weeks(season)
    props_odds_rows, props_sim_rows = nfl_props_rows_for_week(season, week)

    board_games: list[dict[str, Any]] = []
    for projection in projections:
        home_branding = _resolve_branding(projection.home_team)
        away_branding = _resolve_branding(projection.away_team)
        home_full_name = home_branding.display_name if home_branding else projection.home_team
        away_full_name = away_branding.display_name if away_branding else projection.away_team
        home_abbr = home_branding.abbreviation if home_branding else _team_abbr(projection.home_team)
        away_abbr = away_branding.abbreviation if away_branding else _team_abbr(projection.away_team)

        lines_entry = _nfl_real_lines_for_matchup(season, away_full_name=away_full_name, home_full_name=home_full_name)
        moneyline = (lines_entry or {}).get("moneyline") or {}
        total_runs = (lines_entry or {}).get("total_runs") or {}
        prices = _nfl_prices_from_lines_entry(lines_entry, home_full_name=home_full_name, away_full_name=away_full_name)

        odds_rows, sim_rows = _nfl_market_board_rows_for_game(
            game_id=projection.game_id,
            home_moneyline=moneyline.get("home"),
            away_moneyline=moneyline.get("away"),
            spread_line=prices.get("spread_home_line"),
            total_line=total_runs.get("line"),
            model_margin=projection.margin_mean,
            model_total=projection.total_mean,
            model_margin_stdev=projection.margin_stdev,
            model_total_stdev=projection.total_stdev,
            home_win_probability=projection.home_win_rate,
            spread_away_line=prices.get("spread_away_line"),
            spread_home_price=prices.get("spread_home_price"),
            spread_away_price=prices.get("spread_away_price"),
            total_over_price=prices.get("total_over_price"),
            total_under_price=prices.get("total_under_price"),
        )

        # Attach this game's player-prop rows -- matched by real team full
        # names (the props feed carries no game id of its own), then
        # remapped onto this game's real game_id so join_odds_to_sim treats
        # them as one game's full inventory alongside the game markets.
        props_key = nfl_props_key(away_full_name, home_full_name)
        for row in props_odds_rows:
            if row.get("game_id") == props_key:
                odds_rows.append({**row, "game_id": projection.game_id})
        for row in props_sim_rows:
            if row.get("game_id") == props_key:
                sim_rows.append({**row, "game_id": projection.game_id})

        inventory = join_odds_to_sim(odds_rows, sim_rows)
        for row in inventory:
            if row.get("market_type") == "prop":
                # Prop rows were joined on a ::player-disambiguated market
                # key (see props.py's _nfl_prop_join_market_key -- same fix
                # MLB's hitter props needed) -- strip it back to the clean
                # stat name for display now that the join is done.
                row["market"] = nfl_prop_display_stat(row.get("market"))
            else:
                row["market"] = _NFL_MARKET_BOARD_DISPLAY_LABELS.get(row.get("market"), row.get("market"))

        board_games.append(
            {
                "gamePk": projection.game_id,
                "matchup": f"{away_abbr} @ {home_abbr}",
                "away_abbr": away_abbr,
                "home_abbr": home_abbr,
                "away_logo": away_branding.logo_url if away_branding else None,
                "home_logo": home_branding.logo_url if home_branding else None,
                # Overwritten below from real ESPN state. Kept as the literal
                # default so a game the live join does not match still carries
                # a valid value rather than a missing key.
                "game_state": "pregame",
                "rows": inventory,
            }
        )

    # THE SECOND INSTANCE OF THE SAME DEFECT, on a different route. `/nfl/cards`
    # was permanently pregame because nothing set `live_state`; this board was
    # permanently pregame because it hardcodes the string outright. Fixing only
    # the first would leave two NFL surfaces disagreeing about whether the same
    # game is live -- which is worse than both being wrong the same way, because
    # it reads as a data problem rather than a wiring one.
    #
    # Same rules: SEASONTYPE_REGULAR, never fatal, coverage printed. The lookup
    # is by matchup rather than by `live_state`, because these rows are not game
    # cards and never go through `publication_adapter`.
    if board_games:
        try:
            from syndicate.features.nfl.live_game_state import (
                SEASONTYPE_REGULAR,
                nfl_game_state_index,
            )

            index = nfl_game_state_index(season, week, seasontype=SEASONTYPE_REGULAR)
            matched = 0
            for entry in board_games:
                row = index.get(str(entry.get("matchup") or "")) or index.get(
                    f"{entry.get('away_abbr')} @ {entry.get('home_abbr')}")
                # `dict`, not `Mapping`: this module imports only `Any` from
                # typing, and `nfl_game_state_index` is annotated
                # `dict[str, dict[str, Any]]`. A bare `Mapping` here compiled
                # fine and would have raised NameError on the first live game
                # -- the third time today a missing import passed py_compile
                # and would have failed at runtime.
                if not isinstance(row, dict):
                    continue
                state = str(row.get("state") or "").strip().lower()
                if state:
                    entry["game_state"] = state
                    matched += 1
            print(f"[nfl_market_board] LIVE_STATE season={season} week={week} "
                  f"games={len(board_games)} matched={matched} index={len(index)}",
                  flush=True)
        except Exception as exc:
            print(f"[nfl_market_board] LIVE_STATE_FAILED season={season} week={week} "
                  f"error={type(exc).__name__}: {exc}", flush=True)

    return {
        "season": season,
        "week": week,
        "available_weeks": weeks,
        "games": board_games,
        "using_sample_data": False,
        "source_path": str(default_nfl_source_root() / f"smartsim2_projections_{season}_wk{week}.csv"),
    }