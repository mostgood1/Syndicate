"""Layer 1 market/odds inventory for soccer -- one board per league, built
the same way as syndicate/features/mlb/cards.py's build_mlb_market_board:
raw odds rows joined against SoccerSim's projections via the shared
market_inventory.join_odds_to_sim contract, so every quoted line shows up
regardless of whether SoccerSim has coverage for it.

Soccer's board is WEEK-scoped, not single-date-scoped like MLB/NBA/WNBA
(2026-07-24 fix -- soccer's own cards/props pages already think in game
weeks, and its raw odds feed is a single rolling "current odds" file that
captures every upcoming event across the whole week at once, days ahead of
kickoff, not one day at a time). A single `selected_date`'s own
recommendations_{date}.json snapshot can legitimately be empty/stale even
when an adjacent date's snapshot already has real data for that same
match (confirmed in production: recommendations_2026-07-23.json had 0
matches while recommendations_2026-07-22.json's own snapshot already
covered both 07-22 and 07-23 kickoffs) -- so matches are aggregated across
every available snapshot date in a window around selected_date, not read
from a single file.

Kept as its own module rather than folded into cards.py: cards.py's
week-scoped context-building already re-derives week/season from a
schedule artifact for its own (different) rendering needs; this module
only needs recommendations_payload's per-match sim fields
(win_probability/total_distribution/top_props), which is simpler to
aggregate directly across dates than to route through cards.py's
week-object machinery.
"""

from __future__ import annotations

from collections import OrderedDict
from datetime import date, timedelta
from pathlib import Path
import time
import unicodedata
from typing import Any

from syndicate.features.shared.market_inventory import join_odds_to_sim
from syndicate.features.shared.market_inventory import JOIN_STATUS_NEEDS_RESIM
from syndicate.features.shared.odds_control_plane import load_odds_history_payload_for_sport
from syndicate.features.shared.odds_control_plane import resolve_current_shard_key
from syndicate.features.soccer.features.team_names import match_team_name
from syndicate.features.soccer.sources import available_dates
from syndicate.features.soccer.sources import default_season
from syndicate.features.soccer.sources import game_odds_path
from syndicate.features.soccer.sources import game_odds_rows
from syndicate.features.soccer.sources import normalize_league
from syndicate.features.soccer.sources import props_odds_path
from syndicate.features.soccer.sources import props_odds_rows
from syndicate.features.soccer.sources import recommendations_payload
from syndicate.features.soccer.sources import roster_rows
from syndicate.features.soccer.sources import team_by_name


# How many days around the selected date to aggregate matches/props from --
# wide enough to comfortably cover a full MLS game week (typically 3-4
# match days) plus some lookahead for "odds days ahead of kickoff", without
# scanning a league's entire season history on every board request.
_WEEK_LOOKBACK_DAYS = 3
_WEEK_LOOKAHEAD_DAYS = 10


def _soccer_relevant_dates(league: str, selected_date: str) -> list[str]:
    try:
        base = date.fromisoformat(selected_date)
    except ValueError:
        return [selected_date]
    window = {
        (base + timedelta(days=offset)).isoformat()
        for offset in range(-_WEEK_LOOKBACK_DAYS, _WEEK_LOOKAHEAD_DAYS + 1)
    }
    available = set(available_dates(league))
    relevant = sorted(window & available)
    return relevant or [selected_date]


def _soccer_week_matches(league: str, selected_date: str) -> list[dict[str, Any]]:
    """Every match known across recommendations snapshots near
    selected_date, deduped by event_id. Dates are scanned oldest-to-newest
    so a later (fresher) snapshot's version of a match overwrites an
    earlier one rather than the reverse.
    """
    matches_by_event: dict[str, dict[str, Any]] = {}
    for date_str in _soccer_relevant_dates(league, selected_date):
        payload = recommendations_payload(league, date_str) or {}
        matches = payload.get("matches") if isinstance(payload.get("matches"), list) else []
        for match in matches:
            if not isinstance(match, dict):
                continue
            event_id = str(match.get("event_id") or match.get("match_id") or "").strip()
            if event_id:
                matches_by_event[event_id] = match
    return list(matches_by_event.values())


def _soccer_week_props_rows(league: str, selected_date: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for date_str in _soccer_relevant_dates(league, selected_date):
        rows.extend(dict(row) for row in props_odds_rows(league, date_str))
    return rows


_GAME_STATE_BY_STATUS = {"pre": "pregame", "in": "live", "post": "final"}

# Only markets where SoccerSim exposes a genuine 0-1 probability (not a raw
# projected count) are wired to sim_projection -- the board's frontend
# formats sim_projection as a percentage uniformly across every sport, so a
# raw expected-count value (e.g. expected_shots_on_target) would render as
# a nonsensical percentage. Shots/shots-on-target props still appear on the
# board as real quoted lines, just correctly flagged as unmodeled
# (no_sim_coverage) rather than mis-rendered.
_PROP_MARKET_KEY_TO_TOP_PROPS_FIELD = {
    "player_goal_scorer_anytime": "anytime_scorer_probability",
}


def _normalize_soccer_name(value: Any) -> str:
    text = " ".join(str(value or "").strip().lower().split())
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except Exception:
        return None


def _soccer_odds_history_key(row: dict[str, Any]) -> str:
    # Mirrors odds_refresh_tracking._odds_history_market_key's field order
    # exactly (event_id, home_team, away_team, market, side, book) for the
    # subset of columns a soccer game-odds row actually carries -- values
    # are NOT case-folded, matching the write side, which stores them
    # exactly as they appear in the raw CSV.
    parts: list[str] = []
    for key in ("event_id", "home_team", "away_team", "market", "side", "book"):
        value = str(row.get(key) or "").strip()
        if value:
            parts.append(f"{key}={value}")
    return "|".join(parts)


def _soccer_odds_event_for_match(
    *, home_team: str, away_team: str, game_odds_rows_all: list[dict[str, Any]]
) -> tuple[str, str, str] | None:
    """Resolve which event in the raw odds feed corresponds to this sim
    match, and return (odds_event_id, odds_home_team, odds_away_team) --
    all three exactly as they appear on the odds feed's own rows, not the
    sim's.

    The odds feed's own event_id is an Odds-API-internal hash (e.g.
    "a86289ceba2168f9574ec8fccf0305b7"), completely unrelated to the sim's
    ESPN-sourced numeric event_id (e.g. "761685") -- these were being
    compared directly before this fix and could never match. Team names
    also differ between the two sources (ESPN's "Red Bull New York" vs the
    Odds API's "New York Red Bulls"), so the match is done via the same
    fuzzy match_team_name() used elsewhere in this codebase for the same
    cross-source problem (see build_soccer_picks.py's own home/away
    matching, which is exact-string and has the identical gap -- this
    match is a strict improvement, not a new approach).
    """
    events: dict[str, tuple[str, str]] = {}
    for row in game_odds_rows_all:
        row_event_id = str(row.get("event_id") or "").strip()
        row_home = str(row.get("home_team") or "").strip()
        row_away = str(row.get("away_team") or "").strip()
        if row_event_id and row_home and row_away:
            events.setdefault(row_event_id, (row_home, row_away))
    if not events:
        return None
    home_names = [pair[0] for pair in events.values()]
    matched_home = match_team_name(home_team, home_names)
    if matched_home is None:
        return None
    candidate_event_ids = [event_id for event_id, pair in events.items() if pair[0] == matched_home]
    away_names = [events[event_id][1] for event_id in candidate_event_ids]
    matched_away = match_team_name(away_team, away_names)
    if matched_away is None:
        return None
    for event_id in candidate_event_ids:
        if events[event_id][1] == matched_away:
            return event_id, matched_home, matched_away
    return None


def _soccer_market_board_game_rows_for_match(
    *, game_id: str, odds_event_id: str, game_odds_rows_all: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[tuple[str, str], dict[str, Any]]]:
    """Raw game-market (h2h/totals/spreads) odds rows for one match.

    The Odds API's outcome "side" for h2h/spreads is the literal team name
    (or "Draw"), not the string "home"/"away"/"draw" -- normalized here
    against THIS ROW'S OWN home_team/away_team columns (an exact-string
    comparison is safe and correct at this level, since both sides come
    from the same odds-feed row and therefore share the same naming
    convention; the fuzzy cross-source match already happened one level up
    in _soccer_odds_event_for_match to resolve odds_event_id itself).

    Multiple bookmakers quote the same market -- the first one encountered
    per (market, side) is kept (matching how build_mlb_market_board
    surfaces one representative price per market rather than every book),
    and the picked row is returned alongside so its exact "book" value can
    be reused to look up line movement for that same quote.
    """
    odds_rows: list[dict[str, Any]] = []
    picked_by_market_side: dict[tuple[str, str], dict[str, Any]] = {}
    for row in game_odds_rows_all:
        if str(row.get("event_id") or "").strip() != odds_event_id:
            continue
        market = str(row.get("market") or "").strip().lower()
        raw_side = str(row.get("side") or "").strip()
        row_home = str(row.get("home_team") or "").strip()
        row_away = str(row.get("away_team") or "").strip()
        price = _safe_float(row.get("price"))
        if price is None:
            continue
        line = _safe_float(row.get("line"))

        if market == "h2h":
            if raw_side.lower() == "draw":
                side = "draw"
            elif raw_side == row_home:
                side = "home"
            elif raw_side == row_away:
                side = "away"
            else:
                continue
            board_key = ("h2h", side)
            if board_key in picked_by_market_side:
                continue
            picked_by_market_side[board_key] = row
            odds_rows.append(
                {
                    "game_id": game_id,
                    "market": f"moneyline_{side}",
                    "period": "full_game",
                    "entity": None,
                    "side": side,
                    "odds": price,
                    "market_type": "game",
                }
            )
        elif market == "totals":
            side = raw_side.lower()
            if side not in ("over", "under"):
                continue
            board_key = ("totals", side)
            if board_key in picked_by_market_side:
                continue
            picked_by_market_side[board_key] = row
            odds_rows.append(
                {
                    "game_id": game_id,
                    "market": "total",
                    "period": "full_game",
                    "entity": None,
                    "side": side,
                    "line": line,
                    "odds": price,
                    "market_type": "game",
                }
            )
        elif market == "spreads":
            if raw_side == row_home:
                side = "home"
            elif raw_side == row_away:
                side = "away"
            else:
                continue
            board_key = ("spreads", side)
            if board_key in picked_by_market_side:
                continue
            picked_by_market_side[board_key] = row
            odds_rows.append(
                {
                    "game_id": game_id,
                    "market": "spread",
                    "period": "full_game",
                    "entity": None,
                    "side": side,
                    "line": line,
                    "odds": price,
                    "market_type": "game",
                }
            )
    return odds_rows, picked_by_market_side


def _soccer_market_board_sim_rows_for_match(*, event_id: str, match: dict[str, Any]) -> list[dict[str, Any]]:
    sim_rows: list[dict[str, Any]] = []
    win_probability = match.get("win_probability") if isinstance(match.get("win_probability"), dict) else {}
    for side in ("home", "draw", "away"):
        probability = win_probability.get(side)
        if probability is not None:
            sim_rows.append(
                {
                    "game_id": event_id,
                    "market": f"moneyline_{side}",
                    "period": "full_game",
                    "entity": None,
                    "sim_projection": probability,
                    "sim_source": "soccersim",
                }
            )
    total_distribution = match.get("total_distribution") if isinstance(match.get("total_distribution"), dict) else {}
    over_probability = total_distribution.get("over_2_5_probability")
    if over_probability is not None:
        sim_rows.append(
            {
                "game_id": event_id,
                "market": "total",
                "period": "full_game",
                "entity": None,
                "sim_projection": over_probability,
                "sim_source": "soccersim",
            }
        )
    return sim_rows


def _soccer_market_board_prop_rows_for_match(
    *, game_id: str, odds_event_id: str, match: dict[str, Any], props_rows_all: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    odds_rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in props_rows_all:
        if str(row.get("event_id") or "").strip() != odds_event_id:
            continue
        player = str(row.get("player") or "").strip()
        market_label = str(row.get("market") or "").strip()
        if not player or not market_label:
            continue
        line = _safe_float(row.get("line"))
        over_price = _safe_float(row.get("over_price"))
        under_price = _safe_float(row.get("under_price"))
        dedupe_key = (player, market_label, str(row.get("market_key") or ""))
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        if over_price is not None:
            odds_rows.append(
                {
                    "game_id": game_id,
                    "market": market_label,
                    "period": "full_game",
                    "entity": player,
                    "side": "over",
                    "line": line,
                    "odds": over_price,
                    "market_type": "prop",
                }
            )
        if under_price is not None:
            odds_rows.append(
                {
                    "game_id": game_id,
                    "market": market_label,
                    "period": "full_game",
                    "entity": player,
                    "side": "under",
                    "line": line,
                    "odds": under_price,
                    "market_type": "prop",
                }
            )

    # The sim's player names come from American Soccer Analysis, a
    # different provider than the Odds API props feed -- join_odds_to_sim's
    # entity matching is a bare .casefold() (see market_inventory.py), which
    # does not strip accents/diacritics, so "Kevin Denkey" (one provider)
    # and "Kévin Denkey" (the other) would silently fail to join even
    # though they're the same player. Resolved the same way the game-level
    # team-name mismatch was: if this sim player's normalized name matches
    # one of THIS match's own quoted odds players, the sim row is labeled
    # with the odds feed's own spelling so the join lines up exactly;
    # otherwise the sim's own spelling is kept (harmless -- with no
    # matching odds row it can never join to anything anyway).
    odds_player_by_normalized = {_normalize_soccer_name(row["entity"]): row["entity"] for row in odds_rows}

    sim_rows: list[dict[str, Any]] = []
    top_props = match.get("top_props") if isinstance(match.get("top_props"), list) else []
    for prop_row in top_props:
        if not isinstance(prop_row, dict):
            continue
        market_key = str(prop_row.get("market_key") or "").strip()
        # top_props doesn't carry the raw feed's market_key today -- the
        # only currently-wired mapping (anytime goalscorer) is looked up by
        # a dedicated probability field instead of a market_key match, so
        # this loop covers that one case explicitly rather than a generic
        # per-market_key scan.
        player_name = str(prop_row.get("player_name") or "").strip()
        if not player_name:
            continue
        entity_name = odds_player_by_normalized.get(_normalize_soccer_name(player_name), player_name)
        anytime_probability = prop_row.get("anytime_scorer_probability")
        if anytime_probability is not None:
            sim_rows.append(
                {
                    "game_id": game_id,
                    "market": "Anytime Goalscorer",
                    "period": "full_game",
                    "entity": entity_name,
                    "sim_projection": anytime_probability,
                    "sim_source": "soccersim",
                }
            )
    return odds_rows, sim_rows


def _soccer_headshot_lookup(league: str) -> dict[str, str]:
    season = default_season(league)
    lookup: dict[str, str] = {}
    for row in roster_rows(league, season):
        headshot_url = str(row.get("headshot_url") or "").strip()
        player_name = row.get("player_name")
        if headshot_url and player_name:
            lookup[_normalize_soccer_name(player_name)] = headshot_url
    return lookup


def _soccer_odds_history_payload(selected_date: str) -> dict[str, Any]:
    shard_key = resolve_current_shard_key("soccer", selected_date)
    payload = load_odds_history_payload_for_sport("soccer", shard_key)
    return payload if isinstance(payload, dict) else {}


def _soccer_hydrate_market_board_line_movement(row: dict[str, Any], entry: dict[str, Any] | None) -> None:
    if not isinstance(entry, dict):
        return
    last_line = entry.get("last_line")
    previous_line = entry.get("previous_line")
    if last_line is None and previous_line is None:
        return
    row["line_last"] = last_line
    row["line_previous"] = previous_line
    delta = entry.get("delta")
    if delta is None and last_line is not None and previous_line is not None:
        try:
            delta = float(last_line) - float(previous_line)
        except (TypeError, ValueError):
            delta = None
    row["line_delta"] = delta
    row["line_trend"] = entry.get("movement") or "flat"


_SOCCER_MARKET_BOARD_CACHE_TTL_SECONDS = 60
_SOCCER_MARKET_BOARD_CACHE: "OrderedDict[tuple[Any, ...], dict[str, Any]]" = OrderedDict()
_SOCCER_MARKET_BOARD_CACHE_MAX_ENTRIES = 32


def _soccer_cache_bucket() -> int:
    return int(time.time() // _SOCCER_MARKET_BOARD_CACHE_TTL_SECONDS)


def clear_soccer_market_board_cache() -> None:
    """Drop every cached board. Used by the autouse test fixture in
    tests/conftest.py -- the key's artifact signatures are all 0 in a
    checkout (the real CSVs don't exist), so without this two tests using
    the same league/date within one 60s bucket would leak results.
    """
    _SOCCER_MARKET_BOARD_CACHE.clear()


def _soccer_path_signature(path: Path | None) -> int:
    # Mirrors mlb/cards.py's _path_cache_signature.
    if path is None:
        return 0
    try:
        if not path.exists() or not path.is_file():
            return 0
        stat = path.stat()
        return int((stat.st_mtime_ns << 16) ^ int(stat.st_size))
    except OSError:
        return 0


def _soccer_market_board_cache_key(league: str, selected_date: str) -> tuple[Any, ...]:
    """Wall-clock-TTL + artifact-signature key for one league's board.

    Keyed on the odds inputs the build READS and never writes -- the rolling
    game_odds_current.csv plus each relevant date's props CSV. MLB learned
    this the hard way (see build_mlb_market_board): including a file the
    build itself rewrites makes every call invalidate the entry it just
    wrote, producing a cache that can never hit.
    """
    props_signature = tuple(
        _soccer_path_signature(props_odds_path(league, date_str))
        for date_str in _soccer_relevant_dates(league, selected_date)
    )
    return (
        "soccer_market_board",
        league,
        selected_date,
        _soccer_cache_bucket(),
        _soccer_path_signature(game_odds_path(league)),
        props_signature,
    )


def build_soccer_market_board(league: str, selected_date: str) -> dict[str, Any]:
    """Layer 1 market/odds inventory for one soccer league's current game
    week (see module docstring for why this is week- rather than
    single-date-scoped) -- game markets (moneyline/total/spread) and player
    props, joined against SoccerSim's per-match projections, sportsbook-
    style.

    Cached on a wall-clock TTL + artifact signature, for the same reason
    build_mlb_market_board is: soccer_needs_resim_event_ids reaches this
    from the live-refresh tick, and an uncached full board assembly on a
    worker's main loop is exactly what OOM-killed the 2GB refresh-worker on
    2026-07-25. A join-mismatch gate does not need a freshly assembled
    board every tick.
    """
    league = normalize_league(league)
    cache_key = _soccer_market_board_cache_key(league, selected_date)
    cached_board = _SOCCER_MARKET_BOARD_CACHE.get(cache_key)
    if cached_board is not None:
        _SOCCER_MARKET_BOARD_CACHE.move_to_end(cache_key)
        return cached_board
    matches = _soccer_week_matches(league, selected_date)
    game_odds_rows_all = [dict(row) for row in game_odds_rows(league)]
    props_rows_all = _soccer_week_props_rows(league, selected_date)
    headshot_lookup = _soccer_headshot_lookup(league)
    odds_history = _soccer_odds_history_payload(selected_date)
    odds_history_markets = odds_history.get("markets") if isinstance(odds_history.get("markets"), dict) else {}

    board_games: list[dict[str, Any]] = []
    for match in matches:
        if not isinstance(match, dict):
            continue
        event_id = str(match.get("event_id") or match.get("match_id") or "").strip()
        if not event_id:
            continue
        matchup = match.get("matchup") if isinstance(match.get("matchup"), dict) else {}
        home_team = str(matchup.get("home_team") or "").strip()
        away_team = str(matchup.get("away_team") or "").strip()
        status_state = str(match.get("status_state") or "pre").strip().lower()
        game_state = _GAME_STATE_BY_STATUS.get(status_state, "pregame")

        # The odds feed's event_id/team-name spellings are foreign to the
        # sim's (see _soccer_odds_event_for_match's docstring) -- resolve
        # which odds-feed event (if any) is this match before filtering any
        # raw odds/props rows by it.
        resolved_odds_event = _soccer_odds_event_for_match(
            home_team=home_team, away_team=away_team, game_odds_rows_all=game_odds_rows_all
        )
        odds_event_id = resolved_odds_event[0] if resolved_odds_event else None

        if odds_event_id:
            game_odds, picked_game_rows = _soccer_market_board_game_rows_for_match(
                game_id=event_id, odds_event_id=odds_event_id, game_odds_rows_all=game_odds_rows_all
            )
            prop_odds, prop_sim = _soccer_market_board_prop_rows_for_match(
                game_id=event_id, odds_event_id=odds_event_id, match=match, props_rows_all=props_rows_all
            )
        else:
            game_odds, picked_game_rows = [], {}
            prop_odds, prop_sim = [], []
        game_sim = _soccer_market_board_sim_rows_for_match(event_id=event_id, match=match)
        inventory = join_odds_to_sim(game_odds + prop_odds, game_sim + prop_sim)

        for row in inventory:
            if row.get("market_type") == "prop":
                entity_name = row.get("entity")
                if entity_name:
                    headshot_url = headshot_lookup.get(_normalize_soccer_name(entity_name))
                    if headshot_url:
                        row["headshot_url"] = headshot_url
            elif row.get("market_type") == "game" and odds_history_markets:
                raw_market = row.get("market")
                side = row.get("side")
                market_label = {"moneyline_home": "h2h", "moneyline_draw": "h2h", "moneyline_away": "h2h", "total": "totals", "spread": "spreads"}.get(raw_market, raw_market)
                picked_row = picked_game_rows.get((market_label, side)) if market_label and side else None
                if picked_row is not None:
                    key = _soccer_odds_history_key(picked_row)
                    entry = odds_history_markets.get(key) if key else None
                    _soccer_hydrate_market_board_line_movement(row, entry)
            if row.get("market") in ("moneyline_home", "moneyline_draw", "moneyline_away"):
                row["market"] = "Moneyline"
            elif row.get("market") == "total":
                row["market"] = "Total"
            elif row.get("market") == "spread":
                row["market"] = "Spread"

        away_logo = None
        home_logo = None
        if away_team:
            away_directory = team_by_name(league, away_team)
            away_logo = str(away_directory.get("logo_url") or "").strip() or None if away_directory else None
        if home_team:
            home_directory = team_by_name(league, home_team)
            home_logo = str(home_directory.get("logo_url") or "").strip() or None if home_directory else None

        board_games.append(
            {
                "gamePk": event_id,
                "matchup": f"{away_team} @ {home_team}" if away_team and home_team else event_id,
                "away_abbr": away_team,
                "home_abbr": home_team,
                "away_logo": away_logo,
                "home_logo": home_logo,
                "game_state": game_state,
                "startTime": match.get("kickoff"),
                "rows": inventory,
            }
        )

    board = {
        "date": selected_date,
        "league": league,
        "games": board_games,
    }
    _SOCCER_MARKET_BOARD_CACHE[cache_key] = board
    _SOCCER_MARKET_BOARD_CACHE.move_to_end(cache_key)
    while len(_SOCCER_MARKET_BOARD_CACHE) > _SOCCER_MARKET_BOARD_CACHE_MAX_ENTRIES:
        _SOCCER_MARKET_BOARD_CACHE.popitem(last=False)
    return board


def soccer_needs_resim_event_ids(league: str, selected_date: str) -> list[str]:
    """Event IDs where the market board's odds<->sim join found a
    needs-resim mismatch: the book quotes an entity the sim did not project
    for that market, while a DIFFERENT entity was projected -- e.g. a
    lineup change SoccerSim has not re-run against yet.

    Soccer's counterpart to mlb_needs_resim_game_pks. Detection of this
    state was already shared (market_inventory computes it for every
    sport), but only MLB ever acted on it, so soccer's mismatched props
    stayed suppressed (is_eligible false) indefinitely -- 428 such rows on
    the MLS board on 2026-07-25. Reads through build_soccer_market_board's
    cache, so calling this on a tick is cheap between rebuilds.
    """
    board = build_soccer_market_board(league, selected_date)
    games = board.get("games") if isinstance(board.get("games"), list) else []
    event_ids: set[str] = set()
    for game in games:
        if not isinstance(game, dict):
            continue
        rows = game.get("rows") if isinstance(game.get("rows"), list) else []
        if any(isinstance(row, dict) and row.get("join_status") == JOIN_STATUS_NEEDS_RESIM for row in rows):
            event_id = str(game.get("gamePk") or "").strip()
            if event_id:
                event_ids.add(event_id)
    return sorted(event_ids)
