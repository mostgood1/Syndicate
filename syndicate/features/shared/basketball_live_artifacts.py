from __future__ import annotations

import json
import unicodedata
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except Exception:
        return None


def _canonical_game_id(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    digits = "".join(ch for ch in text if ch.isdigit())
    if digits:
        return digits.lstrip("0") or "0"
    return text.upper()


def _canonical_tri(value: Any) -> str:
    return str(value or "").strip().upper()


def _normalize_name(value: Any) -> str:
    # Phase C (Layer 2 task): diacritic-stripping added to match
    # mlb/cards.py's proven _normalize_live_name -- the same class of
    # cross-source spelling mismatch (a name typed/encoded with accents in
    # one artifact, without in another) that needed it there is equally
    # possible here, since this key is shared, generic infra used by both
    # WNBA and NBA.
    text = " ".join(str(value or "").strip().upper().split())
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


# Follow-up to the above: proactive hardening, not (yet) wired to a live
# matcher. No cross-source basketball player-name matching exists in this
# codebase today (confirmed while investigating the Layer 2 WNBA/NBA prop
# identity gap this session) -- but the same class of mismatch
# mlb/cards.py's _market_name_variants already had to fix in production (a
# nickname spelled differently across two data sources) is just as possible
# here, and this module is exactly where a future matcher (e.g. resolving a
# free-text-parsed prop name against a roster/boxscore) would reach for it.
# Rather than wait for a real miss the way MLB's table did, this gets built
# now -- with real, well-established English nickname pairs, not guessed
# player-specific nicknames.
#
# Several of these are genuinely ambiguous between a men's and a women's
# full name, since this module covers both NBA and WNBA rosters -- e.g.
# "Steph" is short for Stephanie in the WNBA, but for NBA guard Stephen
# Curry, "Steph" is short for Stephen, not Stephanie. Picking one expansion
# and forcing it would be WRONG for the other league's player of the same
# nickname. So ambiguous entries map to every plausible expansion (a tuple,
# not a single string) -- a real matcher must check each variant against
# the specific roster it's resolving against and only accept whichever one
# actually exists there, never assume the first entry.
_BASKETBALL_FIRST_NAME_ALIASES: dict[str, tuple[str, ...]] = {
    "mike": ("michael",),
    "michael": ("mike",),
    "nick": ("nicholas",),
    "nicholas": ("nick",),
    "matt": ("matthew",),
    "matthew": ("matt",),
    "will": ("william",),
    "william": ("will",),
    "tony": ("anthony",),
    "anthony": ("tony",),
    "zach": ("zachary",),
    "zack": ("zachary",),
    "zachary": ("zach",),
    "josh": ("joshua",),
    "joshua": ("josh",),
    "rob": ("robert",),
    "bob": ("robert",),
    "robert": ("rob", "bob"),
    "cam": ("cameron",),
    "cameron": ("cam",),
    "jen": ("jennifer",),
    "jennifer": ("jen",),
    "liz": ("elizabeth",),
    "beth": ("elizabeth",),
    "elizabeth": ("liz", "beth", "eliza"),
    "abby": ("abigail",),
    "abigail": ("abby",),
    "gabby": ("gabrielle", "gabriela"),
    "gabrielle": ("gabby",),
    "gabriela": ("gabby",),
    "maddie": ("madison",),
    "madison": ("maddie",),
    "vic": ("victoria",),
    "tori": ("victoria",),
    "victoria": ("vic", "tori"),
    "jackie": ("jacqueline",),
    "jacqueline": ("jackie",),
    "becca": ("rebecca",),
    "rebecca": ("becca",),
    "kenzie": ("mackenzie",),
    "mackenzie": ("kenzie",),
    "katie": ("katherine", "kathryn"),
    "kate": ("katherine", "kathryn"),
    "katherine": ("katie", "kate"),
    "kathryn": ("katie", "kate"),
    # Genuinely ambiguous between two (or more) real full names -- see the
    # module comment above. Every plausible expansion is listed; none is
    # preferred over another.
    "alex": ("alexander", "alexandra", "alexis"),
    "alexander": ("alex",),
    "alexandra": ("alex",),
    "alexis": ("alex",),
    "chris": ("christopher", "christina", "christine"),
    "christopher": ("chris",),
    "christina": ("chris",),
    "christine": ("chris",),
    "sam": ("samuel", "samantha"),
    "samuel": ("sam",),
    "samantha": ("sam",),
    "steph": ("stephanie", "stephen", "stephon"),
    "stephanie": ("steph",),
    "stephen": ("steph",),
    "stephon": ("steph",),
    "dom": ("dominic", "dominique"),
    "dominic": ("dom",),
    "dominique": ("dom",),
    "pat": ("patrick", "patricia"),
    "patrick": ("pat",),
    "patricia": ("pat",),
}


def _name_variants(value: Any) -> list[str]:
    """Normalized name plus plausible nickname/full-name variants.

    Mirrors mlb/cards.py's _market_name_variants shape (normalized base +
    swapped-first-token variants) so a future matcher can try each
    candidate against a known name the same way MLB already does -- see
    _BASKETBALL_FIRST_NAME_ALIASES above for why some entries expand to
    more than one candidate.
    """
    base = _normalize_name(value)
    if not base:
        return []
    variants = [base]
    tokens = base.split()
    if len(tokens) >= 2:
        first_token = tokens[0].lower()
        for candidate in _BASKETBALL_FIRST_NAME_ALIASES.get(first_token, ()):
            variant = " ".join([candidate.upper()] + tokens[1:])
            if variant not in variants:
                variants.append(variant)
    return variants


def _canonical_stat(value: Any) -> str:
    raw = str(value or "").strip().lower()
    mapping = {
        "points": "pts",
        "point": "pts",
        "pts": "pts",
        "rebounds": "reb",
        "rebound": "reb",
        "reb": "reb",
        "assists": "ast",
        "assist": "ast",
        "ast": "ast",
        "3pm": "threes",
        "3pt": "threes",
        "threes": "threes",
        "steals": "stl",
        "stl": "stl",
        "blocks": "blk",
        "blk": "blk",
        "turnovers": "tov",
        "tov": "tov",
        "pra": "pra",
        "pr": "pr",
        "pa": "pa",
        "ra": "ra",
    }
    return mapping.get(raw, raw)


def _read_jsonl_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists() or not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                raw = str(line or "").strip()
                if not raw:
                    continue
                try:
                    payload = json.loads(raw)
                except Exception:
                    continue
                if isinstance(payload, dict):
                    rows.append(payload)
    except Exception:
        return []
    return rows


def _read_live_snapshot_payload(path: Path) -> dict[str, Any] | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        for line in reversed(path.read_text(encoding="utf-8").splitlines()):
            raw = str(line or "").strip()
            if not raw:
                continue
            try:
                record = json.loads(raw)
            except Exception:
                continue
            if isinstance(record, dict) and isinstance(record.get("payload"), dict):
                payload = record.get("payload")
                if isinstance(payload, dict):
                    return payload
            if isinstance(record, dict) and isinstance(record.get("games"), list):
                return record
    except Exception:
        return None
    return None


def _line_map_has_values(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    return any(_safe_float(item) is not None for item in value.values())


def _game_has_live_line_coverage(game: dict[str, Any]) -> bool:
    for key in ("total", "home_spread", "away_spread", "home_ml", "away_ml"):
        if _safe_float(game.get(key)) is not None:
            return True
    lines = game.get("lines") if isinstance(game.get("lines"), dict) else {}
    for key in ("total", "home_spread", "away_spread", "home_ml", "away_ml"):
        if _safe_float(lines.get(key)) is not None:
            return True
    return _line_map_has_values(lines.get("period_totals")) or _line_map_has_values(lines.get("period_spreads"))


def _merge_live_lines_game(primary: dict[str, Any], secondary: dict[str, Any]) -> dict[str, Any]:
    merged = dict(primary)
    merged["found"] = bool(primary.get("found")) or bool(secondary.get("found"))

    for key in ("total", "home_spread", "away_spread", "home_ml", "away_ml"):
        if merged.get(key) is None and secondary.get(key) is not None:
            merged[key] = secondary.get(key)

    primary_lines = primary.get("lines") if isinstance(primary.get("lines"), dict) else {}
    secondary_lines = secondary.get("lines") if isinstance(secondary.get("lines"), dict) else {}
    merged_lines = dict(primary_lines)

    for key in ("total", "home_spread", "away_spread", "home_ml", "away_ml"):
        if merged_lines.get(key) is None and secondary_lines.get(key) is not None:
            merged_lines[key] = secondary_lines.get(key)

    for key in ("period_totals", "period_spreads"):
        merged_periods = dict(primary_lines.get(key) or {}) if isinstance(primary_lines.get(key), dict) else {}
        secondary_periods = secondary_lines.get(key) if isinstance(secondary_lines.get(key), dict) else {}
        for period_key, period_value in secondary_periods.items():
            if period_key not in merged_periods and period_value is not None:
                merged_periods[period_key] = period_value
        merged_lines[key] = merged_periods

    merged["lines"] = merged_lines
    return merged


def _build_signal_live_lines_payload(
    *,
    signal_path: Path,
    date_str: str,
    include_period_totals: bool,
    source: str,
    id_index: dict[str, str],
    matchup_index: dict[tuple[str, str], str],
) -> dict[str, Any] | None:
    rows = _read_jsonl_rows(signal_path)
    if not rows:
        return None

    games_out: dict[str, dict[str, Any]] = {}
    for row in rows:
        event_id = _event_id_for_row(row, id_index=id_index, matchup_index=matchup_index)
        if not event_id:
            continue
        market = str(row.get("market") or "").strip().lower()
        line_value = _safe_float(row.get("live_line") if row.get("live_line") is not None else row.get("line"))
        if line_value is None:
            continue
        current = games_out.setdefault(
            event_id,
            {
                "event_id": event_id,
                "found": False,
                "total": None,
                "home_spread": None,
                "away_spread": None,
                "home_ml": None,
                "away_ml": None,
                "lines": {
                    "total": None,
                    "home_spread": None,
                    "away_spread": None,
                    "home_ml": None,
                    "away_ml": None,
                    "period_totals": {},
                    "period_spreads": {},
                },
            },
        )
        lines = current["lines"] if isinstance(current.get("lines"), dict) else {}
        if market == "total":
            current["found"] = True
            current["total"] = line_value
            lines["total"] = line_value
        elif market in {"spread", "home_spread", "away_spread"}:
            current["found"] = True
            side = str(row.get("side") or row.get("selection") or "").strip().upper()
            if market == "away_spread" or side == "AWAY":
                current["away_spread"] = line_value
                lines["away_spread"] = line_value
                current["home_spread"] = -line_value
                lines["home_spread"] = -line_value
            else:
                current["home_spread"] = line_value
                lines["home_spread"] = line_value
                current["away_spread"] = -line_value
                lines["away_spread"] = -line_value
        elif market in {"moneyline", "home_ml", "away_ml"}:
            current["found"] = True
            side = str(row.get("side") or row.get("selection") or "").strip().upper()
            if market == "away_ml" or side == "AWAY":
                current["away_ml"] = line_value
                lines["away_ml"] = line_value
            else:
                current["home_ml"] = line_value
                lines["home_ml"] = line_value
        elif include_period_totals and market in {"quarter_total", "period_total", "q_total"}:
            horizon = str(row.get("horizon") or row.get("period") or "").strip().lower()
            if horizon:
                current["found"] = True
                period_totals = lines.get("period_totals") if isinstance(lines.get("period_totals"), dict) else {}
                period_totals[horizon] = line_value
                lines["period_totals"] = period_totals
        elif include_period_totals and market in {"quarter_spread", "period_spread", "q_spread"}:
            horizon = str(row.get("horizon") or row.get("period") or "").strip().lower()
            if horizon:
                current["found"] = True
                period_spreads = lines.get("period_spreads") if isinstance(lines.get("period_spreads"), dict) else {}
                period_spreads[horizon] = line_value
                lines["period_spreads"] = period_spreads

    games = [game for game in games_out.values() if bool(game.get("found"))]
    if not games:
        return None

    return {
        "ok": True,
        "date": date_str,
        "requested_date": date_str,
        "lookahead_applied": False,
        "include_period_totals": bool(include_period_totals),
        "source": source,
        "games": games,
        "generated_at": _generated_at_for([signal_path]),
    }


def _generated_at_for(paths: list[Path]) -> str:
    mtimes: list[float] = []
    for path in paths:
        try:
            mtimes.append(float(path.stat().st_mtime))
        except Exception:
            continue
    if not mtimes:
        return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    return datetime.fromtimestamp(max(mtimes), tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _matchup_from_game(game: dict[str, Any]) -> tuple[str, str]:
    away = _canonical_tri(
        game.get("away_tri")
        or ((game.get("away") or {}).get("abbr") if isinstance(game.get("away"), dict) else "")
        or game.get("away")
    )
    home = _canonical_tri(
        game.get("home_tri")
        or ((game.get("home") or {}).get("abbr") if isinstance(game.get("home"), dict) else "")
        or game.get("home")
    )
    return away, home


def _build_event_index(event_games: dict[str, dict[str, Any]]) -> tuple[dict[str, str], dict[tuple[str, str], str]]:
    id_index: dict[str, str] = {}
    matchup_index: dict[tuple[str, str], str] = {}
    for event_id, game in event_games.items():
        identifiers = {
            str(event_id or "").strip(),
            str(game.get("event_id") or "").strip(),
            str(game.get("gamePk") or "").strip(),
            str(game.get("game_id") or "").strip(),
        }
        for identifier in identifiers:
            if not identifier:
                continue
            id_index[identifier] = event_id
            canonical = _canonical_game_id(identifier)
            if canonical:
                id_index[canonical] = event_id
        away, home = _matchup_from_game(game)
        if away and home:
            matchup_index[(away, home)] = event_id
    return id_index, matchup_index


def _event_id_for_row(
    row: dict[str, Any],
    *,
    id_index: dict[str, str],
    matchup_index: dict[tuple[str, str], str],
) -> str:
    for key in ("event_id", "game_id", "game_id_canon"):
        raw = str(row.get(key) or "").strip()
        if raw and raw in id_index:
            return id_index[raw]
        canonical = _canonical_game_id(raw)
        if canonical and canonical in id_index:
            return id_index[canonical]

    away = _canonical_tri(row.get("away"))
    home = _canonical_tri(row.get("home"))
    if not away or not home:
        team = _canonical_tri(row.get("team") or row.get("team_tri"))
        opponent = _canonical_tri(row.get("opponent") or row.get("opponent_tri"))
        home_flag = str(row.get("home") or "").strip().lower()
        if team and opponent and home_flag in {"0", "1", "true", "false"}:
            is_home = home_flag in {"1", "true"}
            home = team if is_home else opponent
            away = opponent if is_home else team
    if away and home:
        return matchup_index.get((away, home), "")
    return ""


def resolve_event_ids_from_games(
    event_games: dict[str, dict[str, Any]],
    requested_event_ids: list[str],
) -> list[str]:
    if not event_games or not requested_event_ids:
        return []

    id_index, _matchup_index = _build_event_index(event_games)
    resolved_event_ids: list[str] = []
    for requested_event_id in requested_event_ids:
        requested = str(requested_event_id or "").strip()
        if not requested:
            continue
        matched_event_id = id_index.get(requested) or id_index.get(_canonical_game_id(requested)) or requested
        game = event_games.get(matched_event_id)
        if not isinstance(game, dict):
            continue
        canonical_event_id = str(game.get("event_id") or game.get("gamePk") or game.get("game_id") or matched_event_id).strip()
        if canonical_event_id and canonical_event_id not in resolved_event_ids:
            resolved_event_ids.append(canonical_event_id)
    return resolved_event_ids


def _latest_projection_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        if str(row.get("market") or "").strip().lower() != "player_prop":
            continue
        name_key = _normalize_name(row.get("name_key") or row.get("player"))
        stat_key = _canonical_stat(row.get("stat"))
        game_key = _canonical_game_id(row.get("game_id_canon") or row.get("game_id") or row.get("event_id"))
        if not name_key or not stat_key or not game_key:
            continue
        grouped[(game_key, name_key, stat_key)] = row
    return list(grouped.values())


def build_live_player_lens_payload_from_artifacts(
    *,
    processed_root: Path,
    date_str: str,
    event_games: dict[str, dict[str, Any]],
    source: str,
) -> dict[str, Any] | None:
    projection_path = processed_root / f"live_lens_projections_{date_str}.jsonl"
    rows = _latest_projection_rows(_read_jsonl_rows(projection_path))
    if not rows or not event_games:
        return None

    id_index, matchup_index = _build_event_index(event_games)
    grouped_rows: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        event_id = _event_id_for_row(row, id_index=id_index, matchup_index=matchup_index)
        if not event_id:
            continue
        game = event_games.get(event_id) or {}
        team_tri = _canonical_tri(row.get("team") or row.get("team_tri"))
        opponent_tri = _canonical_tri(row.get("opponent") or row.get("opponent_tri"))
        if not team_tri or not opponent_tri:
            away_tri, home_tri = _matchup_from_game(game)
            home_flag = str(row.get("home") or "").strip().lower()
            if home_flag in {"0", "1", "true", "false"}:
                is_home = home_flag in {"1", "true"}
                team_tri = home_tri if is_home else away_tri
                opponent_tri = away_tri if is_home else home_tri
        stat = _canonical_stat(row.get("stat"))
        line_value = _safe_float(row.get("line") if row.get("line") is not None else row.get("live_line"))
        price_over = _safe_float(row.get("price_over"))
        price_under = _safe_float(row.get("price_under"))
        price_value = _safe_float(row.get("price"))
        if line_value is not None and abs(line_value) < 0.001 and not any(
            value is not None and abs(value) > 0.001 for value in (price_over, price_under, price_value)
        ):
            continue
        live_projection = _safe_float(
            row.get("live_projection")
            if row.get("live_projection") is not None
            else (row.get("proj") if row.get("proj") is not None else row.get("pred"))
        )
        # Pregame and live-adjusted sim means are genuinely distinct concepts
        # (Layer 2 board's "Projection" vs "Live projection") -- they must
        # NOT be merged into one value here. sim_mu_adjusted falls back to
        # sim_mu only when no live-adjusted value exists at all (e.g. a
        # pregame-only row), never the other way around.
        sim_mu_pregame = _safe_float(row.get("sim_mu"))
        sim_mu_adjusted = _safe_float(
            row.get("sim_mu_adjusted")
            if row.get("sim_mu_adjusted") is not None
            else row.get("sim_mu")
        )
        rendered_row: dict[str, Any] = {
            "player": str(row.get("player") or row.get("name_key") or "").strip(),
            "player_id": row.get("player_id"),
            "team_tri": team_tri or None,
            "opponent_tri": opponent_tri or None,
            "event_id": event_id,
            "stat": stat,
            "line": line_value,
            "line_live": line_value,
            "line_source": "live_lens_projection_artifact",
            "lean": str(row.get("side") or row.get("selection") or "").strip().upper() or None,
            "ev_side": str(row.get("side") or row.get("selection") or "").strip().upper() or None,
            "price_over": price_over,
            "price_under": price_under,
            "price": price_value,
            "ev": _safe_float(row.get("ev")),
            "win_prob": _safe_float(row.get("win_prob") if row.get("win_prob") is not None else row.get("p_win")),
            "recommendation_priority_score": _safe_float(
                row.get("recommendation_priority_score") if row.get("recommendation_priority_score") is not None else row.get("edge")
            ),
            "klass": str(row.get("klass") or "WATCH").strip().upper() or "WATCH",
            "actual": _safe_float(row.get("actual")),
            "pace_proj": _safe_float(row.get("pace_proj") if row.get("pace_proj") is not None else live_projection),
            "pace_vs_line": None,
            "sim_mu": sim_mu_pregame,
            "sim_mu_adjusted": sim_mu_adjusted,
            "live_projection": live_projection,
            "liveProjection": live_projection,
        }
        if line_value is not None and live_projection is not None:
            live_edge = round(live_projection - line_value, 3)
            rendered_row["live_edge"] = live_edge
            rendered_row["liveEdge"] = live_edge
            rendered_row["pace_vs_line"] = live_edge
        if line_value is not None and sim_mu_adjusted is not None:
            sim_vs_line = round(sim_mu_adjusted - line_value, 3)
            rendered_row["sim_vs_line"] = sim_vs_line
            rendered_row["sim_vs_line_adjusted"] = sim_vs_line
        grouped_rows.setdefault(event_id, []).append(rendered_row)

    if not grouped_rows:
        return None

    games: list[dict[str, Any]] = []
    for event_id, rows_for_event in grouped_rows.items():
        game = event_games.get(event_id) or {}
        away_tri, home_tri = _matchup_from_game(game)
        rows_for_event.sort(
            key=lambda row: (
                -abs(_safe_float(row.get("recommendation_priority_score")) or 0.0),
                -abs(_safe_float(row.get("live_edge")) or 0.0),
                str(row.get("player") or ""),
            )
        )
        games.append(
            {
                "event_id": event_id,
                "game_id": game.get("gamePk") or game.get("game_id"),
                "home": home_tri or None,
                "away": away_tri or None,
                "status": game.get("status") if isinstance(game.get("status"), dict) else {},
                "rows": rows_for_event,
            }
        )

    return {
        "ok": True,
        "date": date_str,
        "requested_date": date_str,
        "lookahead_applied": False,
        "source": source,
        "games": games,
        "generated_at": _generated_at_for([projection_path]),
    }


def build_live_lines_payload_from_artifacts(
    *,
    processed_root: Path,
    date_str: str,
    event_games: dict[str, dict[str, Any]],
    include_period_totals: bool,
    source: str,
) -> dict[str, Any] | None:
    snapshot_path = processed_root / "live_snapshots" / f"live_lines_{date_str}.jsonl"
    signal_path = processed_root / f"live_lens_signals_{date_str}.jsonl"
    if not event_games:
        return None

    id_index, matchup_index = _build_event_index(event_games)

    snapshot_payload = _read_live_snapshot_payload(snapshot_path)
    snapshot_games = snapshot_payload.get("games") if isinstance(snapshot_payload, dict) and isinstance(snapshot_payload.get("games"), list) else []
    snapshot_result: dict[str, Any] | None = None
    if snapshot_games:
        filtered_games: list[dict[str, Any]] = []
        for game in snapshot_games:
            if not isinstance(game, dict):
                continue
            event_id = _event_id_for_row(game, id_index=id_index, matchup_index=matchup_index)
            if not event_id:
                continue
            normalized_game = dict(game)
            normalized_game["event_id"] = event_id
            filtered_games.append(normalized_game)
        if filtered_games and any(_game_has_live_line_coverage(game) for game in filtered_games):
            snapshot_result = {
                "ok": True,
                "date": str((snapshot_payload or {}).get("date") or date_str),
                "requested_date": date_str,
                "lookahead_applied": False,
                "include_period_totals": bool(include_period_totals),
                "source": "syndicate_live_snapshot_artifact",
                "games": filtered_games,
                "generated_at": str((snapshot_payload or {}).get("generated_at") or _generated_at_for([snapshot_path])),
            }

    signal_result = _build_signal_live_lines_payload(
        signal_path=signal_path,
        date_str=date_str,
        include_period_totals=bool(include_period_totals),
        source=source,
        id_index=id_index,
        matchup_index=matchup_index,
    )

    if snapshot_result and signal_result:
        snapshot_games_by_event = {
            str(game.get("event_id") or "").strip(): game
            for game in snapshot_result.get("games") or []
            if isinstance(game, dict) and str(game.get("event_id") or "").strip()
        }
        signal_games_by_event = {
            str(game.get("event_id") or "").strip(): game
            for game in signal_result.get("games") or []
            if isinstance(game, dict) and str(game.get("event_id") or "").strip()
        }
        ordered_event_ids: list[str] = []
        for payload in (snapshot_result, signal_result):
            for game in payload.get("games") or []:
                if not isinstance(game, dict):
                    continue
                event_id = str(game.get("event_id") or "").strip()
                if event_id and event_id not in ordered_event_ids:
                    ordered_event_ids.append(event_id)
        return {
            **snapshot_result,
            "games": [
                _merge_live_lines_game(snapshot_games_by_event[event_id], signal_games_by_event[event_id])
                if event_id in snapshot_games_by_event and event_id in signal_games_by_event
                else dict(snapshot_games_by_event.get(event_id) or signal_games_by_event.get(event_id) or {})
                for event_id in ordered_event_ids
                if event_id in snapshot_games_by_event or event_id in signal_games_by_event
            ],
            "generated_at": str(snapshot_result.get("generated_at") or signal_result.get("generated_at") or _generated_at_for([snapshot_path, signal_path])),
        }

    if snapshot_result:
        return snapshot_result
    return signal_result