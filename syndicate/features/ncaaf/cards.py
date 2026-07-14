from __future__ import annotations

import csv
import re
from typing import Any
from functools import lru_cache
from pathlib import Path

from syndicate.features.ncaaf.sources import available_weeks
from syndicate.features.ncaaf.sources import build_module_links
from syndicate.features.ncaaf.sources import default_season
from syndicate.features.ncaaf.sources import default_week
from syndicate.features.ncaaf.sources import format_moneyline
from syndicate.features.ncaaf.sources import format_num
from syndicate.features.ncaaf.sources import format_pct
from syndicate.features.ncaaf.sources import load_json
from syndicate.features.ncaaf.sources import summary_path
from syndicate.features.shared.discrete_nav import neighboring_values
from syndicate.features.shared.discrete_nav import resolve_selected_value
from syndicate.features.shared.game_board_contract import apply_game_board_contract


_WEEK1_PUBLISHABLE_MATCHUPS = {
    ("Western Michigan", "Michigan State"),
    ("Kennesaw State", "Wake Forest"),
    ("UNLV", "Sam Houston"),
    ("San Jose State", "Central Michigan"),
    ("Tennessee", "Syracuse"),
    ("Ball State", "Purdue"),
    ("Coastal Carolina", "Virginia"),
    ("Eastern Michigan", "Texas State"),
}

_WEEK1_SUPPRESSED_MATCHUPS = {
    ("Tarleton State", "Army"),
    ("Bethune-Cookman", "Florida International"),
    ("Nicholls", "Troy"),
    ("SE Louisiana", "Louisiana Tech"),
    ("Bryant", "New Mexico State"),
}

_WEEK1_COVERAGE_PROFILE = {
    "publishable": {
        "coverage_score": 1.0,
        "coverage_tier": "A",
        "publication_status": "publishable",
        "publication_priority": 3,
    },
    "suppressed": {
        "coverage_score": 0.675,
        "coverage_tier": "C",
        "publication_status": "suppressed",
        "publication_priority": 1,
    },
}


_NCAAF_CARD_CONTRACT_VERSION = "1"


def _processed_artifact_path(*parts: str) -> Path:
    return Path(__file__).resolve().parents[3] / "data" / "ncaaf_source" / "source_artifacts" / "data" / "processed" / Path(*parts)


def _load_csv_rows(path: Path) -> list[dict[str, Any]]:
    try:
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    except Exception:
        return []


def _normalize_text(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


@lru_cache(maxsize=1)
def _team_registry_rows() -> tuple[dict[str, Any], ...]:
    return tuple(_load_csv_rows(_processed_artifact_path("team_registry", "ncaaf_team_registry.csv")))


@lru_cache(maxsize=1)
def _returning_rows() -> tuple[dict[str, Any], ...]:
    return tuple(_load_csv_rows(_processed_artifact_path("returning_production", "ncaaf_returning_production_snapshot.csv")))


@lru_cache(maxsize=1)
def _coach_rows() -> tuple[dict[str, Any], ...]:
    return tuple(_load_csv_rows(_processed_artifact_path("coach_continuity", "ncaaf_coach_continuity_snapshot.csv")))


@lru_cache(maxsize=1)
def _transfer_rows() -> tuple[dict[str, Any], ...]:
    return tuple(_load_csv_rows(_processed_artifact_path("transfers", "ncaaf_transfer_portal_snapshot.csv")))


@lru_cache(maxsize=1)
def _roster_rows() -> tuple[dict[str, Any], ...]:
    return tuple(_load_csv_rows(_processed_artifact_path("roster", "ncaaf_roster_snapshot.csv")))


def _team_registry_index() -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for row in _team_registry_rows():
        if not isinstance(row, dict):
            continue
        for candidate in (
            row.get("team_id"),
            row.get("canonical_team_name"),
            row.get("abbreviation"),
            row.get("display_name"),
            row.get("school_name"),
            row.get("mascot_name"),
        ):
            normalized = _normalize_text(candidate)
            if normalized:
                index.setdefault(normalized, row)
        for alias in str(row.get("aliases") or "").split("|"):
            normalized = _normalize_text(alias)
            if normalized:
                index.setdefault(normalized, row)
    return index


def _resolve_team(team_name: str) -> dict[str, Any] | None:
    return _team_registry_index().get(_normalize_text(team_name))


def _first_row(rows: tuple[dict[str, Any], ...], *, team_id: str | None = None, season: int | None = None, key: str = "team_id") -> dict[str, Any] | None:
    for row in rows:
        if not isinstance(row, dict):
            continue
        if team_id is not None and str(row.get(key) or "").strip() != str(team_id).strip():
            continue
        if season is not None:
            row_season = str(row.get("season") or "").strip()
            if row_season and row_season != str(season):
                continue
        return row
    return None


def _count_rows(rows: tuple[dict[str, Any], ...], *, key: str, team_id: str, season: int | None = None) -> int:
    total = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get(key) or "").strip() != str(team_id).strip():
            continue
        if season is not None:
            row_season = str(row.get("season") or "").strip()
            if row_season and row_season != str(season):
                continue
        total += 1
    return total


def _count_transfer_rows(rows: tuple[dict[str, Any], ...], *, team_id: str, season: int | None = None, direction: str) -> int:
    key = "destination_team_id" if direction == "in" else "origin_team_id"
    return _count_rows(rows, key=key, team_id=team_id, season=season)


def _format_decimal(value: Any, *, places: int = 3) -> str:
    amount = _safe_float(value)
    if amount is None:
        return "-"
    return f"{amount:.{places}f}".rstrip("0").rstrip(".")


def _publication_ready(coverage_tier: str | None) -> bool:
    return str(coverage_tier or "").upper() in {"A", "B"}


def _tier_badges(coverage_tier: str | None) -> list[dict[str, Any]]:
    current = str(coverage_tier or "").upper()
    return [{"label": tier, "active": tier == current} for tier in ("A", "B", "C", "D")]


def _team_context(team_name: str, season: int) -> dict[str, Any]:
    registry_row = _resolve_team(team_name) or {}
    team_id = str(registry_row.get("team_id") or "").strip()
    returning_row = _first_row(_returning_rows(), team_id=team_id, season=season)
    coach_row = _first_row(_coach_rows(), team_id=team_id, season=season)
    roster_count = _count_rows(_roster_rows(), key="team_id", team_id=team_id, season=season)
    transfer_in = _count_transfer_rows(_transfer_rows(), team_id=team_id, season=season, direction="in")
    transfer_out = _count_transfer_rows(_transfer_rows(), team_id=team_id, season=season, direction="out")
    transfer_net = transfer_in - transfer_out
    returning_starter_estimate = _format_decimal(returning_row.get("returning_starter_estimate") if returning_row else None, places=1)
    returning_percent = _format_decimal(returning_row.get("percent_ppa") if returning_row else None, places=3)
    returning_usage = _format_decimal(returning_row.get("usage") if returning_row else None, places=3)
    coach_continuity = _format_decimal(coach_row.get("continuity_score") if coach_row else None, places=3)
    coach_tenure = _format_decimal(coach_row.get("coach_tenure_years") if coach_row else None, places=1)
    return {
        "team_name": team_name,
        "team_id": team_id,
        "abbreviation": str(registry_row.get("abbreviation") or _abbr(team_name)).strip(),
        "conference": str(registry_row.get("conference") or "").strip(),
        "subdivision": str(registry_row.get("subdivision") or "").strip(),
        "returning": {
            "starter_estimate": returning_starter_estimate,
            "percent_ppa": returning_percent,
            "usage": returning_usage,
            "summary": f"{returning_starter_estimate} starters | PPA {returning_percent} | Usage {returning_usage}",
        },
        "coach": {
            "name": str(coach_row.get("head_coach_name") or "").strip() if coach_row else "",
            "continuity_score": coach_continuity,
            "tenure_years": coach_tenure,
            "changed": str(coach_row.get("coach_changed") or "").strip() if coach_row else "",
            "summary": f"{str(coach_row.get('head_coach_name') or 'TBD').strip()} | continuity {coach_continuity} | tenure {coach_tenure}y" if coach_row else "Coach continuity unavailable",
        },
        "transfer": {
            "incoming": transfer_in,
            "outgoing": transfer_out,
            "net": transfer_net,
            "summary": f"{transfer_in} in / {transfer_out} out / net {transfer_net:+d}".replace("+", "") if transfer_in or transfer_out else "No transfer data",
        },
        "roster": {
            "active_count": roster_count,
            "summary": f"{roster_count} active roster entries",
        },
    }


def _build_ncaaf_card_contract(row: dict[str, Any], week: int, *, season: int) -> dict[str, Any]:
    home_team = str(row.get("home_team") or "Home").strip() or "Home"
    away_team = str(row.get("away_team") or "Away").strip() or "Away"
    publication_profile = _week1_publication_profile(away_team, home_team, week)
    coverage_score = publication_profile.get("coverage_score")
    coverage_tier = publication_profile.get("coverage_tier")
    publication_status = publication_profile.get("publication_status")
    publication_priority = publication_profile.get("publication_priority")
    publication_ready = _publication_ready(coverage_tier)
    home_context = _team_context(home_team, season)
    away_context = _team_context(away_team, season)
    matchup_context = [
        {
            "label": "Returning production",
            "home": home_context["returning"]["summary"],
            "away": away_context["returning"]["summary"],
            "detail": "Starter estimate, production share, and usage from the published snapshot.",
        },
        {
            "label": "Coach continuity",
            "home": home_context["coach"]["summary"],
            "away": away_context["coach"]["summary"],
            "detail": "Continuity score and tenure from the published coach snapshot.",
        },
        {
            "label": "Transfer activity",
            "home": home_context["transfer"]["summary"],
            "away": away_context["transfer"]["summary"],
            "detail": "Incoming, outgoing, and net transfer counts.",
        },
        {
            "label": "Roster base",
            "home": home_context["roster"]["summary"],
            "away": away_context["roster"]["summary"],
            "detail": "Active roster snapshot rows linked to each team.",
        },
    ]
    return {
        "version": _NCAAF_CARD_CONTRACT_VERSION,
        "summary": {
            "coverage_score": coverage_score,
            "coverage_tier": coverage_tier,
            "publication_status": publication_status,
            "publication_priority": publication_priority,
            "publication_ready": publication_ready,
            "ready_label": "Publication ready" if publication_ready else "Publication blocked",
            "tier_badges": _tier_badges(coverage_tier),
        },
        "teams": {
            "home": home_context,
            "away": away_context,
        },
        "context_sections": matchup_context,
    }


def _abbr(team: str) -> str:
    tokens = [token for token in str(team or "").replace("&", " ").split() if token]
    if not tokens:
        return "TBD"
    if len(tokens) == 1:
        return tokens[0][:3].upper()
    return "".join(token[0] for token in tokens[:3]).upper()


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except Exception:
        return None


def _stake_text(value: Any) -> str:
    amount = _safe_float(value)
    return f"${amount:.2f}" if amount is not None else "-"


def _kelly_text(value: Any) -> str:
    amount = _safe_float(value)
    return f"{amount * 100:.1f}%" if amount is not None else "-"


def _week_label(week: int, *, season: int | None = None) -> str:
    resolved_season = int(season) if season is not None else default_season()
    return f"{resolved_season} Week {week}"


def _week1_publication_profile(away_team: str, home_team: str, week: int) -> dict[str, Any]:
    if week != 1:
        return {}
    matchup = (away_team, home_team)
    if matchup in _WEEK1_PUBLISHABLE_MATCHUPS:
        return dict(_WEEK1_COVERAGE_PROFILE["publishable"])
    if matchup in _WEEK1_SUPPRESSED_MATCHUPS:
        return dict(_WEEK1_COVERAGE_PROFILE["suppressed"])
    return {}


def _collapse_games(summary: dict[str, Any], week: int, *, limit: int = 16) -> list[dict[str, Any]]:
    results = summary.get("results") if isinstance(summary.get("results"), list) else []
    best_rows: dict[tuple[str, str], dict[str, Any]] = {}
    for row in results:
        if not isinstance(row, dict):
            continue
        home_team = str(row.get("home_team") or "").strip()
        away_team = str(row.get("away_team") or "").strip()
        if not home_team or not away_team:
            continue
        key = (away_team, home_team)
        current = best_rows.get(key)
        candidate_edge = _safe_float(row.get("edge")) or float("-inf")
        if current is None:
            best_rows[key] = row
            continue
        current_edge = _safe_float(current.get("edge")) or float("-inf")
        if candidate_edge > current_edge:
            best_rows[key] = row
            continue
        candidate_stake = _safe_float(row.get("stake")) or 0.0
        current_stake = _safe_float(current.get("stake")) or 0.0
        if candidate_edge == current_edge and candidate_stake > current_stake:
            best_rows[key] = row

    ordered_rows = sorted(
        best_rows.values(),
        key=lambda row: ((_safe_float(row.get("edge")) or 0.0), (_safe_float(row.get("stake")) or 0.0)),
        reverse=True,
    )
    games: list[dict[str, Any]] = []
    for row in ordered_rows[:limit]:
        home_team = str(row.get("home_team") or "Home").strip() or "Home"
        away_team = str(row.get("away_team") or "Away").strip() or "Away"
        home_abbr = _abbr(home_team)
        away_abbr = _abbr(away_team)
        market = str(row.get("market") or "ML").strip().upper() or "ML"
        side = str(row.get("side") or "Home").strip() or "Home"
        provider = str(row.get("provider") or "Book").strip() or "Book"
        price = format_moneyline(row.get("price_american"))
        model_prob = format_pct(row.get("model_prob"))
        implied_prob = format_pct(row.get("implied_prob"))
        edge = format_pct(row.get("edge"))
        stake = _stake_text(row.get("stake"))
        favored_team = home_team if side.lower() == "home" else away_team
        ncaaf_card = _build_ncaaf_card_contract(row, week, season=default_season())
        games.append(
            {
                "gamePk": f"{week}_{away_team}_{home_team}".replace(" ", "_"),
                "card_variant": "ncaaf_main",
                "away": {"abbr": away_abbr, "name": away_team},
                "home": {"abbr": home_abbr, "name": home_team},
                "href": f"/ncaaf/game/{f'{week}_{away_team}_{home_team}'.replace(' ', '_')}?week={week}",
                "href_label": "Open NCAAF game detail",
                "status": f"Week {week}",
                "detail": "Historical summary",
                "summary": f"{favored_team} is the best {market} recommendation from {provider} at {price} with modeled edge {edge}.",
                **ncaaf_card.get("summary", {}),
                "ncaaf_card": ncaaf_card,
                "metrics": [
                    {"label": "Model", "value": model_prob},
                    {"label": "Implied", "value": implied_prob},
                    {"label": "Price", "value": price},
                    {"label": "Stake", "value": stake},
                    {"label": "Edge", "value": edge},
                ],
                "panels": [
                    {
                        "eyebrow": "Official card",
                        "title": provider,
                        "body": "The first NCAAF cards board groups the weekly recommendations summary into one best available recommendation per matchup.",
                        "items": [
                            f"Market: {market}",
                            f"Side: {side}",
                            f"Stake: {stake}",
                        ],
                    },
                    {
                        "eyebrow": "Model vs price",
                        "title": f"Model {model_prob} | Implied {implied_prob}",
                        "body": f"Best listed price is {price} from {provider}, producing modeled edge {edge}.",
                        "items": [
                            f"Kelly fraction: {_kelly_text(row.get('kelly_f'))}",
                            f"Raw edge multiple: {format_num(row.get('edge'))}",
                            f"Recommendation: {favored_team}",
                        ],
                    },
                    {
                        "eyebrow": "Game context",
                        "title": _week_label(week),
                        "body": f"{away_team} at {home_team} from the stored NCAAF recommendations summary.",
                        "items": [
                            f"Provider: {provider}",
                            "Current source artifacts are offseason weekly snapshots rather than live slate data.",
                        ],
                    },
                ],
                "market_tiles": [
                    {"label": "Coverage", "title": _format_decimal(ncaaf_card["summary"]["coverage_score"], places=3), "sub": ncaaf_card["summary"]["ready_label"]},
                    {"label": "Tier", "title": str(ncaaf_card["summary"]["coverage_tier"] or "-").upper(), "sub": "SmartSim tier"},
                    {"label": "Status", "title": str(ncaaf_card["summary"]["publication_status"] or "-").title(), "sub": "Publication state"},
                    {"label": "Priority", "title": str(ncaaf_card["summary"]["publication_priority"] or "-"), "sub": "Board order"},
                ],
            }
        )
    return games


def _clamp_week(selected_week: int) -> int:
    return resolve_selected_value(selected_week, available_weeks(), 1)


def build_cards_page_context(selected_week: int) -> dict[str, Any]:
    season = default_season()
    resolved_week = _clamp_week(selected_week or default_week())
    betting_href = f"/ncaaf/season/{season}/betting-card?week={resolved_week}"
    path = summary_path(resolved_week)
    summary = load_json(path) or {}
    games = _collapse_games(summary, resolved_week)
    using_sample_data = False

    weeks = available_weeks()
    prev_week, next_week = neighboring_values(weeks, resolved_week, fallback=resolved_week)
    return apply_game_board_contract(
        {
            "date": _week_label(resolved_week, season=season),
            "requested_date": _week_label(selected_week, season=season),
            "prev_date": str(prev_week),
            "next_date": str(next_week),
            "control_action": "/ncaaf/cards",
            "controls_prev_href": f"/ncaaf/cards?week={prev_week}",
            "controls_next_href": f"/ncaaf/cards?week={next_week}",
            "control_label": "Week",
            "control_type": "number",
            "control_name": "week",
            "control_value": str(resolved_week),
            "module_links": build_module_links(resolved_week, "Cards"),
            "games": games,
            "scoreboard_items": [
                {
                    "target_id": f"game-{game['gamePk']}",
                    "label": f"{game['away']['abbr']} @ {game['home']['abbr']}",
                    "status": game["status"],
                }
                for game in games
            ],
            "source_path": str(path),
            "source_title": "NCAAF recommendations summary" if games else "NCAAF cards unavailable",
            "empty_state": {
                "eyebrow": "NCAAF cards",
                "title": "No game cards were available for this week",
                "body": "The cards board only renders saved NCAAF recommendation summary rows, and none were available for the requested week.",
                "list_items": [
                    f"Requested week: {selected_week}",
                    f"Resolved week: {resolved_week}",
                ],
            } if not games else None,
            "using_sample_data": using_sample_data,
            "route_path": "/ncaaf/cards",
            "intro_title": "NCAAF Cards",
            "intro_body": "NCAAF enters the shared game-board contract with a first weekly cards surface built from stored recommendation summary artifacts in the source app.",
            "cards_control_links": [
                {"label": "Betting Card", "href": betting_href},
                {"label": "Picks", "href": f"/ncaaf/picks?week={resolved_week}"},
                {"label": "Live Lens", "href": f"/ncaaf/live-lens?week={resolved_week}"},
            ],
            "header_stats": [
                {"label": "Games", "value": str(len(games))},
                {"label": "Rows", "value": str(len(summary.get('results') or []))},
                {"label": "Weeks", "value": str(len(weeks) or "-")},
                {"label": "Source", "value": "Summary" if games else "No data"},
            ],
            "cards_stylesheet": None,
            "cards_grid_class": "cards-grid",
            "show_source_summary": True,
            "show_intro": True,
            "teaser": {
                "label": "NCAAF picks",
                "body": "Use the picks board for the ranked weekly recommendation rows behind these matchup cards.",
                "href": f"/ncaaf/picks?week={resolved_week}",
                "cta": "Open NCAAF picks",
            },
            "active_sport_name": "NCAAF",
        },
        sport="ncaaf",
        module="cards",
        source_kind="artifact_backed",
        live_lens_integrated=False,
    )