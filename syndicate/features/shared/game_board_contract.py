from __future__ import annotations

import os
import re
from typing import Any

from syndicate.features.shared.publication_adapter import normalize_publication_game
from syndicate.features.shared.simulation_adapter import build_simulation_contract_from_context


def _sim_payload(game: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(game, dict):
        return {}
    nested = game.get("sim")
    if isinstance(nested, dict) and nested:
        return nested
    return game


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except Exception:
        return None


# ONE null placeholder for every board surface. Measured 2026-08-14: the same
# missing value rendered as "-" on NCAAF (11 template sites), as an EMPTY CELL
# on the generic card (Jinja's silent undefined), and as "-" in MLB's JS
# renderer -- so "no data" looked like three different things depending on
# which fork you were looking at, and one of the three looked like nothing at
# all. The em dash is what `intelligence.html` already treats as the null
# marker (it reads both forms), so this converges on what the platform
# half-had rather than inventing a fourth.
#
# Deliberately NOT a general "-" ban: `-` stays correct as a minus sign, as a
# scoreline separator, and inside any per-sport producer whose own consumers
# compare against it (`wnba/cards.py`, `soccer/team.py` and the bespoke JS
# renderers all do). This constant governs the SHARED CONTRACT's output.
NULL_PLACEHOLDER = "—"


def _safe_text(value: Any, fallback: str = NULL_PLACEHOLDER) -> str:
    text = str(value or "").strip()
    return text or fallback


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def _metric_lookup(metrics: list[dict[str, Any]], label: str) -> str | None:
    wanted = label.strip().lower()
    for metric in metrics:
        current = str(metric.get("label") or "").strip().lower()
        if current == wanted:
            return str(metric.get("value") or "").strip() or None
    return None


def _render_web_dyno() -> bool:
    # RENDER / RENDER_EXTERNAL_URL / RENDER_SERVICE_ID are injected by Render
    # on every service type (web *and* background workers), so they can't
    # distinguish "am I the request-serving web dyno" from "am I a worker
    # script calling into this shared module". This is used across every
    # sport's card board (see should_include_simulation_contract below), so
    # the ambiguity made worker-side calls skip the heavier
    # simulation_contract build meant to happen off the request path, for
    # every sport that uses this shared contract layer. Same root cause and
    # fix as the per-sport copies (wnba/cards.py, nba/cards.py, mlb/cards.py).
    # SYNDICATE_WEB_DYNO is an explicit, unambiguous override set only on the
    # web service in render.yaml; fall back to the old heuristic when unset
    # (local dev, other hosts).
    explicit = str(os.environ.get("SYNDICATE_WEB_DYNO") or "").strip().lower()
    if explicit:
        return explicit in {"1", "true", "yes", "on"}
    return bool(
        str(os.environ.get("RENDER") or "").strip().lower() in {"1", "true", "yes", "on"}
        or str(os.environ.get("RENDER_EXTERNAL_URL") or "").strip()
        or str(os.environ.get("RENDER_SERVICE_ID") or "").strip()
    )


def _team_side(game: dict[str, Any], side: str) -> dict[str, Any]:
    # Most sports' game objects represent "home"/"away" as a dict
    # ({"abbr": "BOS", "name": "..."}). WNBA's source-mode game builder
    # (_source_game_from_row) represents them as a bare tri-code string
    # instead -- every `.get(side, {}).get("abbr")` in this module assumed
    # the dict shape and crashed with AttributeError the moment a
    # string-shaped game reached it (first hit when WNBA's home-dashboard
    # games started running through this module's normalization).
    value = game.get(side)
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        return {"abbr": value.strip(), "name": value.strip()}
    return {}


def _infer_live_state(game: dict[str, Any]) -> bool:
    # game.get("status") is a dict on every normalized game shape (e.g.
    # {"in_progress": True, "final": False, "detailed": "Q3 4:12"}) -- this
    # used to str()-format that whole dict into the text haystack below
    # instead of reading its actual in_progress/final booleans, so whether a
    # game was detected as live depended on Python's dict-repr happening to
    # contain a lucky substring match rather than the real signal. Read the
    # structured booleans first; only fall back to the text heuristic (kept
    # for sources that never got a proper live_state) when neither the
    # status dict nor live_state carries them.
    status = game.get("status") if isinstance(game.get("status"), dict) else {}
    live_state = game.get("live_state") if isinstance(game.get("live_state"), dict) else {}
    in_progress = status.get("in_progress")
    if in_progress is None:
        in_progress = live_state.get("in_progress")
    final = status.get("final")
    if final is None:
        final = live_state.get("final")
    if final is not None or in_progress is not None:
        if bool(final):
            return False
        if in_progress is not None:
            return bool(in_progress)
    haystack = " ".join(
        [
            str(status.get("detailed") or status.get("detail") or status.get("status") or ""),
            str(game.get("detail") or ""),
            str(game.get("summary") or ""),
        ]
    ).lower()
    # Bare substring checks (see soccer's every-game-shows-live report, #160):
    # short/ambiguous tokens like "ot" match constantly inside ordinary
    # prose that has nothing to do with overtime -- "not been simulated
    # yet", "total {value}" both contain "ot", so every unsimulated or
    # already-simulated soccer game (whose summary/detail text is the only
    # thing in this haystack, since soccer's status field is a plain
    # display string rather than a structured dict) silently came back
    # live=True. Word-boundary match every token, not just the short ones,
    # so a longer token embedded in a longer word ("delivered" containing
    # "live") can't false-positive either.
    live_tokens = ("live", "in progress", "in-progress", "quarter", "period", "inning", "ot", "halftime", "intermission")
    final_tokens = ("final", "closed", "scheduled", "preview", "pregame", "historical", "processed artifact")
    def _has_token(token: str) -> bool:
        return re.search(rf"\b{re.escape(token)}\b", haystack) is not None
    if any(_has_token(token) for token in final_tokens):
        return False
    return any(_has_token(token) for token in live_tokens)


def _format_pct(value: float | None) -> str:
    if value is None:
        return NULL_PLACEHOLDER
    return f"{value * 100:.1f}%"


def _format_num(value: float | None) -> str:
    if value is None:
        return NULL_PLACEHOLDER
    return f"{value:.1f}"


def _format_signed_num(value: float | None) -> str:
    if value is None:
        return NULL_PLACEHOLDER
    return f"{value:+.1f}"


def _period_label(key: str) -> str:
    normalized = str(key or "").strip().lower()
    mapping = {
        "q1": "First 1",
        "q2": "First 2",
        "q3": "First 3",
        "q4": "First 4",
        "p1": "Period 1",
        "p2": "Period 2",
        "p3": "Period 3",
        "f1": "First 1",
        "f3": "First 3",
        "f5": "First 5",
        "f7": "First 7",
        "full": "Full Game",
        "h1": "1st Half",
        "h2": "2nd Half",
        "ht": "Halftime",
        "ft": "Full Time",
    }
    return mapping.get(normalized, str(key or "Period").upper())


def _build_period_rows(game: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    sim = _sim_payload(game)
    periods = sim.get("periods") if isinstance(sim.get("periods"), dict) else {}
    betting = game.get("betting") if isinstance(game.get("betting"), dict) else {}
    away_abbr = _safe_text(_team_side(game, "away").get("abbr"), "AWY")
    home_abbr = _safe_text(_team_side(game, "home").get("abbr"), "HME")
    betting_total = _safe_float(betting.get("total"))
    betting_home_spread = _safe_float(betting.get("home_spread"))
    betting_p_home_win = betting.get("p_home_win")
    betting_p_away_win = betting.get("p_away_win")
    # betting_total/betting_home_spread are the game's ONE full-game market
    # line -- when periods is per-quarter/half sim data (e.g. WNBA's
    # q1/q2/q3/q4), comparing each individual period's much-smaller
    # projected total/margin against that same full-game line produced a
    # nonsensical "edge" on every row (a ~40-point quarter projection
    # diffed against a ~165-point full-game total). Only a period whose own
    # projection already represents the whole game should be compared
    # against the market line; every individual sub-period gets NULL_PLACEHOLDER for
    # market/best_edge instead, and a genuine full-game aggregate row
    # (summed across all periods) is appended below so there's still
    # exactly one row with a valid sim-vs-line comparison.
    period_entries = [(key, value) for key, value in periods.items() if isinstance(value, dict)]
    single_period_is_full_game = len(period_entries) <= 1
    aggregate_away_mean = 0.0
    aggregate_home_mean = 0.0
    has_aggregate = False
    for key, value in period_entries:
        away_mean = _safe_float(value.get("away_mean"))
        home_mean = _safe_float(value.get("home_mean"))
        total_mean = _safe_float(value.get("total_mean"))
        margin_mean = _safe_float(value.get("margin_mean"))
        if (away_mean is None or home_mean is None) and total_mean is not None and margin_mean is not None:
            away_mean = round((total_mean - margin_mean) / 2.0, 3)
            home_mean = round((total_mean + margin_mean) / 2.0, 3)
        if total_mean is None and away_mean is not None and home_mean is not None:
            total_mean = away_mean + home_mean
        if away_mean is not None:
            aggregate_away_mean += away_mean
            has_aggregate = True
        if home_mean is not None:
            aggregate_home_mean += home_mean
            has_aggregate = True
        # MEASURED 2026-08-14 by driving this function with a known game: a
        # 21.0-24.0 projection produced away_pct 46.67 / home_pct 53.33 --
        # exactly the share of projected POINTS -- and the template renders
        # that pair in `.cards-prob-bar`, under a panel titled "Period win
        # probabilities". A 3-point favourite is not a 53.3% favourite; a real
        # win probability there is nearer 60%. Worse, when the game DID carry
        # p_home_win = 0.62 the bar still drew 53.3% while the row's own
        # `home_win` text said 62.0% -- the two-numbers-on-one-card defect the
        # UI audit found on soccer, in the shared contract, on every sport.
        #
        # So the pair is now the WIN PROBABILITY or nothing. A projection with
        # no probability attached renders no bar (the template suppresses it),
        # which is the point of this lane: absent renders as absent, and a
        # quantity is never displayed under another quantity's name.
        p_home_win = _safe_float(value.get("p_home_win"))
        p_away_win = _safe_float(value.get("p_away_win"))
        if p_away_win is None and p_home_win is not None:
            p_away_win = 1.0 - p_home_win
        if p_home_win is None and p_away_win is not None:
            p_home_win = 1.0 - p_away_win
        away_pct = (p_away_win * 100.0) if p_away_win is not None else None
        home_pct = (p_home_win * 100.0) if p_home_win is not None else None
        market_value = NULL_PLACEHOLDER
        best_edge_value = NULL_PLACEHOLDER
        if single_period_is_full_game:
            market_bits: list[str] = []
            edge_bits: list[str] = []
            if betting_home_spread is not None:
                market_bits.append(f"ATS {home_abbr} {_format_signed_num(betting_home_spread)}")
                if margin_mean is not None:
                    edge_bits.append(f"ATS {_format_signed_num(margin_mean + betting_home_spread)}")
            if betting_total is not None:
                market_bits.append(f"Total {_format_num(betting_total)}")
                if total_mean is not None:
                    edge_bits.append(f"Total {_format_signed_num(total_mean - betting_total)}")
            market_value = " | ".join(market_bits) if market_bits else (_metric_lookup(game.get("metrics", []), "Spread") or _metric_lookup(game.get("metrics", []), "Total") or NULL_PLACEHOLDER)
            best_edge_value = " | ".join(edge_bits) if edge_bits else (_metric_lookup(game.get("metrics", []), "Edge") or NULL_PLACEHOLDER)
        rows.append(
            {
                "label": _period_label(str(key)),
                "main": f"{away_abbr} {_format_num(away_mean)} - {home_abbr} {_format_num(home_mean)}",
                "subtitle": f"Projected total {_format_num(total_mean)}",
                "away_pct": away_pct,
                "home_pct": home_pct,
                "home_win": _format_pct(p_home_win),
                "market": market_value,
                "best_edge": best_edge_value,
            }
        )
    if len(period_entries) > 1 and has_aggregate:
        aggregate_total = round(aggregate_away_mean + aggregate_home_mean, 3)
        aggregate_margin = round(aggregate_home_mean - aggregate_away_mean, 3)
        aggregate_total_pct = aggregate_away_mean + aggregate_home_mean
        # Same correction as the per-period rows above: this pair fed the win
        # bar with a share of projected points. The game-level probability, if
        # one exists, is on `betting` -- read it there rather than inventing a
        # split from the scoreline.
        aggregate_p_home = _safe_float(betting_p_home_win)
        aggregate_p_away = _safe_float(betting_p_away_win)
        if aggregate_p_away is None and aggregate_p_home is not None:
            aggregate_p_away = 1.0 - aggregate_p_home
        if aggregate_p_home is None and aggregate_p_away is not None:
            aggregate_p_home = 1.0 - aggregate_p_away
        away_pct = (aggregate_p_away * 100.0) if aggregate_p_away is not None else None
        home_pct = (aggregate_p_home * 100.0) if aggregate_p_home is not None else None
        market_bits = []
        edge_bits = []
        if betting_home_spread is not None:
            market_bits.append(f"ATS {home_abbr} {_format_signed_num(betting_home_spread)}")
            edge_bits.append(f"ATS {_format_signed_num(aggregate_margin + betting_home_spread)}")
        if betting_total is not None:
            market_bits.append(f"Total {_format_num(betting_total)}")
            edge_bits.append(f"Total {_format_signed_num(aggregate_total - betting_total)}")
        rows.append(
            {
                "label": "Full Game",
                "main": f"{away_abbr} {_format_num(aggregate_away_mean)} - {home_abbr} {_format_num(aggregate_home_mean)}",
                "subtitle": f"Projected total {_format_num(aggregate_total)}",
                "away_pct": away_pct,
                "home_pct": home_pct,
                # Was `home_pct / 100.0` -- i.e. the share of projected points
                # printed as "Home win NN%". It is a probability or it is
                # absent; it is never a scoreline in disguise.
                "home_win": _format_pct(home_pct / 100.0) if home_pct is not None else NULL_PLACEHOLDER,
                "market": " | ".join(market_bits) if market_bits else (_metric_lookup(game.get("metrics", []), "Spread") or _metric_lookup(game.get("metrics", []), "Total") or NULL_PLACEHOLDER),
                "best_edge": " | ".join(edge_bits) if edge_bits else (_metric_lookup(game.get("metrics", []), "Edge") or NULL_PLACEHOLDER),
            }
        )
    if not rows:
        away_score = _metric_lookup(game.get("metrics", []), "Pred score") or game.get("summary")
        # sim.periods is the primary source for per-quarter/half win split, but
        # when it's empty (e.g. the sim engine's period-summary step didn't
        # produce output for this game) the game-level model win probability
        # already sitting in betting.p_home_win/p_away_win is a real, available
        # substitute for the flat 50/50 this used to fall back to -- using it
        # here means "betting %" only ever reads blank when there's truly no
        # market/model probability anywhere on the game, not whenever periods
        # happens to be empty.
        p_home_win, p_away_win, p_draw = _game_win_probabilities(game)
        home_win_text = _format_pct(p_home_win) if p_home_win is not None else (
            _metric_lookup(game.get("metrics", []), "Home win") or _metric_lookup(game.get("metrics", []), "Win prob") or NULL_PLACEHOLDER
        )
        rows.append(
            {
                "label": "Full Game",
                "main": away_score or game.get("summary") or "Game outlook unavailable",
                "subtitle": game.get("detail") or game.get("status") or NULL_PLACEHOLDER,
                "away_pct": (p_away_win * 100.0) if p_away_win is not None else None,
                "home_pct": (p_home_win * 100.0) if p_home_win is not None else None,
                "draw_pct": (p_draw * 100.0) if p_draw is not None else None,
                "home_win": home_win_text,
                "market": _metric_lookup(game.get("metrics", []), "Spread") or _metric_lookup(game.get("metrics", []), "Total") or NULL_PLACEHOLDER,
                "best_edge": _metric_lookup(game.get("metrics", []), "Edge") or NULL_PLACEHOLDER,
            }
        )
    return rows


def _game_win_probabilities(game: dict[str, Any]) -> tuple[float | None, float | None, float | None]:
    """(home, away, draw) win probability for the game, or Nones.

    Order matters and it is the fix for the UI audit's "two conflicting
    home-win numbers on one soccer card". Those two numbers were not a
    rounding artifact: the TILES show the sim's three-way win probability
    (`sim.win_probability`, home/draw/away) while the BAR showed
    `betting.p_home_win`, which soccer's `_market_data_for_match` builds from
    the picks rows' `market_probability` -- the MARKET's implied number. Two
    different quantities, both correct, ~250px apart under the same word.

    The sim is preferred here so the bar agrees with the tiles above it, and
    the market number is the fallback for sports that publish no sim split.
    A three-way market keeps its draw rather than being renormalised into a
    two-way one, which is what made the soccer bar disagree by ~4 points even
    when both sides were "right".
    """
    sim = game.get("sim") if isinstance(game.get("sim"), dict) else {}
    win = sim.get("win_probability") if isinstance(sim.get("win_probability"), dict) else {}
    p_home = _safe_float(win.get("home"))
    p_away = _safe_float(win.get("away"))
    p_draw = _safe_float(win.get("draw"))
    if p_home is None and p_away is None:
        betting = game.get("betting") if isinstance(game.get("betting"), dict) else {}
        p_home = _safe_float(betting.get("p_home_win"))
        p_away = _safe_float(betting.get("p_away_win"))
        p_draw = _safe_float(betting.get("p_draw"))
    # Complete a two-way pair only when there is no draw in play. Doing this
    # on a three-way market is exactly how a 77.3% home win became 81.1%.
    if p_draw is None:
        if p_home is None and p_away is not None:
            p_home = 1.0 - p_away
        if p_away is None and p_home is not None:
            p_away = 1.0 - p_home
    return p_home, p_away, p_draw


def _build_probability_rows(game: dict[str, Any], period_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    existing = game.get("probability_rows") if isinstance(game.get("probability_rows"), list) else []
    rows: list[dict[str, Any]] = []
    for row in existing:
        if not isinstance(row, dict):
            continue
        # `_safe_float(...) or 50.0` mapped a genuine 0.0 onto 50.0 as well as
        # a missing value -- measured: a row carrying a real 0% home win came
        # out of the period path as a 50/50 while the probability path kept
        # the 0.0, so one card disagreed with itself. `is None` is the test,
        # not falsiness.
        away_pct = _safe_float(row.get("away_pct"))
        home_pct = _safe_float(row.get("home_pct"))
        if home_pct is None and away_pct is not None:
            home_pct = max(0.0, 100.0 - away_pct)
        if away_pct is None and home_pct is not None:
            away_pct = max(0.0, 100.0 - home_pct)
        draw_pct = _safe_float(row.get("draw_pct"))
        rows.append(
            {
                "label": _safe_text(row.get("label"), "Full Game"),
                "away_pct": away_pct,
                "home_pct": home_pct,
                "draw_pct": draw_pct,
                "summary": _safe_text(row.get("summary"), "Probability split unavailable"),
            }
        )
    if rows:
        return rows
    fallback: list[dict[str, Any]] = []
    for row in period_rows:
        # Carries the period rows' pair through as-is, including None. A row
        # with no probability produces no bar rather than a centred one; see
        # the note on the period rows above.
        fallback.append(
            {
                "label": row.get("label") or "Full Game",
                "away_pct": _safe_float(row.get("away_pct")),
                "home_pct": _safe_float(row.get("home_pct")),
                "draw_pct": _safe_float(row.get("draw_pct")),
                "summary": f"Home win {row.get('home_win') or '-'}",
            }
        )
    return fallback[:5]


def _build_total_rows(period_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    numeric_totals = []
    for row in period_rows:
        subtitle = str(row.get("subtitle") or "")
        marker = subtitle.lower().split("projected total ")
        total = _safe_float(marker[-1]) if marker else None
        numeric_totals.append(total or 0.0)
    max_total = max(numeric_totals) if numeric_totals else 0.0
    out: list[dict[str, Any]] = []
    for idx, row in enumerate(period_rows):
        total = numeric_totals[idx] if idx < len(numeric_totals) else 0.0
        width = (total / max_total * 100.0) if max_total > 0 else 0.0
        out.append(
            {
                "label": row.get("label") or "Full Game",
                "summary": row.get("subtitle") or "Projected total unavailable",
                "bins": [{"width": width, "total": _format_num(total), "pct": f"{width:.1f}"}] if width > 0 else [],
            }
        )
    return out


def _rows_from_table_groups(table_groups: list[dict[str, Any]], *, limit: int = 6) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for group in table_groups:
        if not isinstance(group, dict):
            continue
        heading = _safe_text(group.get("heading"), "Board")
        for row in group.get("rows") or []:
            if not isinstance(row, dict):
                continue
            rows.append(
                {
                    "heading": heading,
                    "name": _safe_text(row.get("name"), "Play"),
                    "detail": _safe_text(row.get("detail"), ""),
                    "value": _safe_text(row.get("value"), NULL_PLACEHOLDER),
                }
            )
            if len(rows) >= limit:
                return rows
    return rows


def _build_top_play_rows(game: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for panel in game.get("panels") or []:
        if not isinstance(panel, dict):
            continue
        heading = _safe_text(panel.get("title"), panel.get("eyebrow") or "Top plays")
        rows.extend(_rows_from_table_groups(panel.get("table_groups") or [], limit=max(0, 6 - len(rows))))
        if len(rows) >= 6:
            break
        for item in panel.get("items") or []:
            item_text = _safe_text(item, "")
            if not item_text:
                continue
            rows.append({"heading": heading, "name": item_text, "detail": _safe_text(panel.get("body"), ""), "value": heading})
            if len(rows) >= 6:
                break
        if len(rows) >= 6:
            break
    return rows


def _build_prop_rows(game: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    prop_recs = game.get("prop_recommendations") if isinstance(game.get("prop_recommendations"), dict) else {}
    for side_key, team_abbr in (("away", _safe_text(_team_side(game, "away").get("abbr"), "Away")), ("home", _safe_text(_team_side(game, "home").get("abbr"), "Home"))):
        for row in prop_recs.get(side_key) or []:
            if not isinstance(row, dict):
                continue
            rows.append(
                {
                    "heading": f"{team_abbr} props",
                    "team": team_abbr,
                    "name": _safe_text(row.get("player") or row.get("display_pick"), "Prop"),
                    "detail": _safe_text(row.get("display_pick") or row.get("market"), ""),
                    "value": _safe_text(row.get("tier") or row.get("line") or row.get("price"), NULL_PLACEHOLDER),
                    "photo": row.get("photo") or row.get("player_photo") or row.get("headshot_url"),
                    "headshot_url": row.get("headshot_url") or row.get("photo") or row.get("player_photo"),
                    "pick": _safe_text(row.get("display_pick") or row.get("pick") or row.get("selection"), ""),
                    "market": _safe_text(row.get("market") or row.get("market_label") or row.get("type_label"), ""),
                    "line": row.get("line"),
                    "market_line": _first_present(row.get("market_line"), row.get("line")),
                    "actual": _first_present(row.get("actual"), row.get("actual_value"), row.get("actual_total")),
                    "projected": _first_present(row.get("projected"), row.get("projection"), row.get("model_mean")),
                    "live_projection": _first_present(row.get("live_projection"), row.get("liveProjection"), row.get("projection_live")),
                    "odds": row.get("price") or row.get("odds") or row.get("price_american"),
                    "confidence": row.get("confidence") or row.get("prob") or row.get("win_prob"),
                    "selection": row.get("selection") or row.get("side"),
                    "game_state": row.get("game_state") or row.get("state") or row.get("status") or row.get("status_label"),
                    "live_total": _first_present(row.get("live_total"), row.get("live_total_line")),
                    "live_total_line": _first_present(row.get("live_total_line"), row.get("live_line_total")),
                    "outcome_state": row.get("outcome_state") or row.get("actual_result") or row.get("result"),
                    "outcome_label": row.get("outcome_label"),
                }
            )
            if len(rows) >= 8:
                return rows
    if rows:
        return rows
    for panel in game.get("panels") or []:
        if not isinstance(panel, dict):
            continue
        title = f"{str(panel.get('eyebrow') or '')} {str(panel.get('title') or '')}".lower()
        if "prop" not in title:
            continue
        rows.extend(_rows_from_table_groups(panel.get("table_groups") or [], limit=max(0, 8 - len(rows))))
        for item in panel.get("items") or []:
            item_text = _safe_text(item, "")
            if not item_text:
                continue
            rows.append({"heading": _safe_text(panel.get("title"), "Props"), "name": item_text, "detail": _safe_text(panel.get("body"), ""), "value": _safe_text(panel.get("eyebrow"), "Props")})
            if len(rows) >= 8:
                return rows
    return rows


def _build_box_sections(game: dict[str, Any]) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    sim = _sim_payload(game)
    score = sim.get("score") if isinstance(sim.get("score"), dict) else {}
    away_abbr = _safe_text(_team_side(game, "away").get("abbr"), "AWY")
    home_abbr = _safe_text(_team_side(game, "home").get("abbr"), "HME")
    away_mean = _safe_float(score.get("away_mean"))
    home_mean = _safe_float(score.get("home_mean"))
    if away_mean is not None or home_mean is not None:
        sections.append(
            {
                "title": "Sim game box",
                "body": "Pregame and in-play sim scoring expectations stay pinned in the box score tab.",
                "rows": [
                    {"name": away_abbr, "detail": _team_side(game, "away").get("name") or away_abbr, "value": _format_num(away_mean)},
                    {"name": home_abbr, "detail": _team_side(game, "home").get("name") or home_abbr, "value": _format_num(home_mean)},
                ],
            }
        )
    for panel in game.get("panels") or []:
        if not isinstance(panel, dict):
            continue
        title = f"{str(panel.get('eyebrow') or '')} {str(panel.get('title') or '')}".lower()
        if "sim" not in title and "box" not in title and "player outcome" not in title:
            continue
        rows = _rows_from_table_groups(panel.get("table_groups") or [], limit=6)
        if rows:
            sections.append(
                {
                    "title": _safe_text(panel.get("title"), "Sim detail"),
                    "body": _safe_text(panel.get("body"), ""),
                    "rows": rows,
                }
            )
        if len(sections) >= 2:
            break
    if not sections:
        sections.append(
            {
                "title": "Box score unavailable",
                "body": "This sport has not shipped a live box-score lane into the shared board yet, so only the game summary is currently available.",
                "rows": [],
            }
        )
    return sections


def _normalize_game(game: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(game, dict):
        return game
    if str(game.get("card_variant") or "") == "mlb_main":
        return game
    normalized = dict(game)
    metrics = normalized.get("metrics") if isinstance(normalized.get("metrics"), list) else []
    period_rows = _build_period_rows(normalized)
    normalized.setdefault("market_tiles", [{"label": metric.get("label"), "title": metric.get("value"), "sub": f"{_safe_text(_team_side(normalized, 'away').get('abbr'), 'AWY')} @ {_safe_text(_team_side(normalized, 'home').get('abbr'), 'HME')}"} for metric in metrics[:4]])
    normalized["shared_is_live"] = _infer_live_state(normalized)
    normalized["shared_period_rows"] = period_rows
    normalized["shared_probability_rows"] = _build_probability_rows(normalized, period_rows)
    normalized["shared_total_rows"] = _build_total_rows(period_rows)
    normalized["shared_box_sections"] = _build_box_sections(normalized)
    normalized["shared_prop_rows"] = _build_prop_rows(normalized)
    # Real bug found 2026-07-23: this used to unconditionally overwrite
    # shared_top_play_rows with the generic panels-derived version, even
    # when the sport's own cards.py already built a real one from
    # structured data. NFL's cards.py builds genuine EV/odds/confidence
    # rows here (_top_play_rows in nfl/cards.py) that were silently
    # discarded on every request, replaced by free-text scraped off
    # display panels -- the only escape hatch was the card_variant ==
    # "mlb_main" early-return above, which NFL doesn't use. Preserve a
    # non-empty incoming list instead of clobbering it, mirroring the
    # market_tiles .setdefault(...) pattern just above.
    existing_top_play_rows = normalized.get("shared_top_play_rows")
    if not (isinstance(existing_top_play_rows, list) and existing_top_play_rows):
        normalized["shared_top_play_rows"] = _build_top_play_rows(normalized)
    if normalized["shared_is_live"] and not normalized.get("market_tiles") and period_rows:
        normalized["market_tiles"] = [
            {
                "label": str(row.get("label") or "Live"),
                "title": str(row.get("main") or row.get("subtitle") or "Live game lens"),
                "sub": str(row.get("subtitle") or normalized.get("detail") or normalized.get("summary") or "Live game lens"),
            }
            for row in period_rows[:4]
            if isinstance(row, dict)
        ]
    normalized["shared_tab_game_title"] = "Live game lens" if normalized["shared_is_live"] else "Period odds and game lens"
    normalized["shared_tab_props_title"] = "Live props" if normalized["shared_is_live"] else "Official and playable props"
    return normalized


def _normalize_games(games: list[dict[str, Any]], *, sport: str | None = None) -> list[dict[str, Any]]:
    return [normalize_publication_game(_normalize_game(game), sport=sport) for game in games if isinstance(game, dict)]


def _log_board_contract_memory(stage: str, **extra: Any) -> None:
    # #75. Stage samples inside build_cards_page_context proved the refresh-worker
    # OOM happens *inside this function*: the worker logged
    # cards_context_result_assembled and was then oomKilled at 4Gi before
    # cards_context_board_contract_applied, twice, at the same statement.
    #
    # Two candidates live in here -- _normalize_games and
    # build_simulation_contract_from_context -- and these three samples say
    # which. Note simulation_contract is built only when NOT a web dyno, which
    # is why /mlb/api/cards serves a 2.3MB payload from web while the worker
    # dies building the same board.
    #
    # Worker-only, for the same reason as the cards_context_* samples.
    if _render_web_dyno():
        return
    try:
        from syndicate.features.shared.memory_observability import log_container_memory

        log_container_memory(f"board_contract_{stage}", **extra)
    except Exception:
        pass


def apply_game_board_contract(
    context: dict[str, Any],
    *,
    sport: str,
    module: str,
    surface: str | None = None,
    schema: str = "game_board_v1",
    source_kind: str = "artifact_backed",
    live_lens_integrated: bool = True,
    include_simulation_contract: bool | None = None,
) -> dict[str, Any]:
    out = dict(context)
    normalized_sport = str(sport or "sport").strip().lower() or "sport"
    games = out.get("games") if isinstance(out.get("games"), list) else []
    _log_board_contract_memory("begin", sport=normalized_sport, game_count=len(games))
    out["games"] = _normalize_games(games, sport=normalized_sport)
    _log_board_contract_memory("games_normalized", sport=normalized_sport, game_count=len(games))
    out.setdefault("show_app_header", False)
    out.setdefault(
        "show_standalone_cards_header",
        str(module or "").strip().lower() in {"cards", "game_detail", "season_review"},
    )
    out.setdefault("active_sport_slug", normalized_sport)
    out.setdefault("active_sport_name", normalized_sport.upper())
    out.setdefault("show_intro", False)
    out.setdefault("show_source_summary", False)
    if not out.get("control_action"):
        out["control_action"] = out.get("route_path")
    if not out.get("control_value"):
        out["control_value"] = out.get("date")
    if not out.get("control_label"):
        out["control_label"] = "Date"
    if not out.get("control_type"):
        out["control_type"] = "date"
    if not out.get("control_name"):
        out["control_name"] = "date"
    out.setdefault("page_body_class", f"cards-body syndicate-{normalized_sport}-cards-page")
    out.setdefault("page_shell_class", f"syndicate-{normalized_sport}-cards-shell")
    out.setdefault("cards_grid_class", "mlb-cards-grid")
    out.setdefault("cards_stylesheet", f"{normalized_sport}/cards.css")
    should_include_simulation_contract = include_simulation_contract
    if should_include_simulation_contract is None:
        # #75/#43. Default OFF. This used to default to "build it whenever we
        # are not the web dyno", which meant the refresh-worker built it for
        # every sport, every cycle -- and NOTHING reads it. The only other
        # reference to a "simulation_contract" key in syndicate/ is
        # ask_the_syndicate_adapter.py, which reads it off the daily_update
        # payload, a different structure. The web dyno never built it, so no
        # template can depend on it either.
        #
        # It is also the most expensive thing on the path: it was 99.8% of the
        # page context's deep size locally, it is absent from the persisted
        # board payload, and the OOM that took the worker down all day died
        # inside build_simulation_contract_from_context. Post-fix the worker
        # still plateaued at ~2.7GB, which left too little headroom for a board
        # build to run alongside an MLB sim -- DEFERRED_BOARD_BUILD
        # reason=sim_subprocess_resident_and_no_headroom, 16 cycles in a row.
        #
        # Callers that genuinely want it can still pass include_simulation_contract=True.
        should_include_simulation_contract = False
    if should_include_simulation_contract:
        out["simulation_contract"] = build_simulation_contract_from_context(
            out,
            sport=normalized_sport,
            selection=out.get("control_value") or out.get("date") or out.get("requested_date"),
        )
        _log_board_contract_memory("simulation_contract_built", sport=normalized_sport)
    else:
        out.pop("simulation_contract", None)
    resolved_surface = str(surface or f"{normalized_sport}_dense_board_v1").strip() or f"{normalized_sport}_dense_board_v1"
    out["board_contract"] = {
        "schema": schema,
        "surface": resolved_surface,
        "sport": normalized_sport,
        "module": str(module or "board").strip().lower() or "board",
        "source_kind": source_kind,
        "live_lens_integrated": bool(live_lens_integrated),
    }
    return out


def build_game_board_api_payload(context: dict[str, Any]) -> dict[str, Any]:
    games = context.get("games", [])
    using_sample_data = context.get("using_sample_data", False)
    source_path = context.get("source_path")
    requested_date = context.get("requested_date", context["date"])
    pregame_portfolio = context.get("pregame_portfolio")
    if not isinstance(pregame_portfolio, dict):
        pregame_portfolio = {"enabled": False, "selected": 0, "candidates": 0}
    payload = {
        "date": context["date"],
        "requested_date": requested_date,
        "lookahead_applied": bool(context.get("lookahead_applied", False)),
        "pregame_portfolio": pregame_portfolio,
        "games": games,
        "scoreboard": context.get("scoreboard_items", []),
        "using_sample_data": using_sample_data,
        "usingSampleData": using_sample_data,
        "hasSampleData": not bool(using_sample_data),
        "hasArtifactData": not bool(using_sample_data),
        "source_path": source_path,
        "sourcePath": source_path,
        "board_contract": context.get("board_contract", {}),
    }
    if "prev_date" in context or "next_date" in context:
        payload["nav"] = {
            "prevDate": context.get("prev_date"),
            "nextDate": context.get("next_date"),
        }
    optional_keys = (
        "header_stats",
        "source_title",
        "empty_state",
        "has_games_on_slate",
        "route_path",
        "module_links",
        "teaser",
        "control_action",
        "controls_prev_href",
        "controls_next_href",
        "control_value",
        "control_label",
        "control_type",
        "control_name",
        "hidden_fields",
        "generatedAt",
        "generated_at",
        "oddsRefreshedAt",
        "odds_refreshed_at",
        "live_lens_contract",
        "refresh_policy",
        "counts",
        "app",
        "dataRoot",
        "liveLensDir",
        "optimizationRegime",
        "performance",
    )
    for key in optional_keys:
        if key in context:
            payload[key] = context.get(key)
    return payload


def build_single_game_board_context(
    *,
    selected_date: str,
    prev_date: str,
    next_date: str,
    game: dict[str, Any],
    game_pk: str | int,
    module_links: list[dict[str, Any]],
    source_path: str,
    source_title: str,
    using_sample_data: bool,
    route_path: str,
    intro_title: str,
    intro_body: str,
    teaser: dict[str, Any],
    cards_grid_class: str,
    cards_stylesheet: str,
    sport: str,
    module: str,
    header_stats: list[dict[str, str]] | None = None,
    control_action: str | None = None,
    controls_prev_href: str | None = None,
    controls_next_href: str | None = None,
    control_value: str | None = None,
    control_label: str | None = None,
    control_type: str | None = None,
    control_name: str | None = None,
    hidden_fields: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    scoreboard_items = [
        {
            "target_id": f"game-{game['gamePk']}",
            "label": f"{game['away']['abbr']} @ {game['home']['abbr']}",
            "status": game["detail"],
        }
    ]
    return apply_game_board_contract(
        {
            "date": selected_date,
            "prev_date": prev_date,
            "next_date": next_date,
            "module_links": module_links,
            "games": [game],
            "scoreboard_items": scoreboard_items,
            "source_path": source_path,
            "using_sample_data": using_sample_data,
            "source_title": source_title,
            "header_stats": header_stats
            or [
                {"label": "Game", "value": str(game_pk)},
                {"label": "Away", "value": game["away"]["abbr"]},
                {"label": "Home", "value": game["home"]["abbr"]},
            ],
            "route_path": route_path,
            "intro_title": intro_title,
            "intro_body": intro_body,
            "cards_grid_class": cards_grid_class,
            "cards_stylesheet": cards_stylesheet,
            "teaser": teaser,
            "control_action": control_action,
            "controls_prev_href": controls_prev_href,
            "controls_next_href": controls_next_href,
            "control_value": control_value,
            "control_label": control_label,
            "control_type": control_type,
            "control_name": control_name,
            "hidden_fields": list(hidden_fields or []),
        },
        sport=sport,
        module=module,
    )