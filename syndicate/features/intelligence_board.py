"""
Context: Syndicate Simulation System
See: docs/ai_context/architecture.md

Role:
- Builds intelligence board payloads for UI presentation and summaries.

Constraints:
- State-driven execution
- Avoid redundant computation
"""

from __future__ import annotations

import json
import re

from typing import Any, Mapping, Sequence

from syndicate.features.shared.intelligence_evaluation import build_feature_coverage_profile


def _intel_trace(event: str, **fields: Any) -> None:
    try:
        print(f"[INTEL_TRACE] {json.dumps({'event': event, **fields}, sort_keys=True, default=str)}", flush=True)
    except Exception:
        print(f"[INTEL_TRACE] {event}", flush=True)


def _copy_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _safe_text(*values: Any, default: str = "") -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return default


def _number(*values: Any) -> float | None:
    for value in values:
        if value is None or isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).strip()
        if not text:
            continue
        try:
            return float(text.replace("%", ""))
        except Exception:
            continue
    return None


def _movement_summary(item: Mapping[str, Any]) -> str:
    movement = item.get("movement") if isinstance(item.get("movement"), Mapping) else {}
    delta = _number(
        movement.get("delta") if isinstance(movement, Mapping) else None,
        movement.get("edge_delta") if isinstance(movement, Mapping) else None,
        item.get("line_movement_impact"),
        item.get("ev_delta"),
        item.get("ev_change"),
    )
    trend = _safe_text(
        movement.get("trend") if isinstance(movement, Mapping) else None,
        movement.get("recent_movement_trend") if isinstance(movement, Mapping) else None,
        item.get("movement_label"),
        default="flat",
    ).lower()
    if delta is not None and delta != 0:
        prefix = "+" if delta > 0 else ""
        return f"{prefix}{delta:.1f} ({trend})"
    if trend:
        return trend
    return "flat"


def _is_time_like_status(status: str) -> bool:
    if not status:
        return False
    lowered = status.lower()
    return bool(
        re.search(r"\b\d{1,2}:\d{2}\s?(?:am|pm)\b", lowered)
        or re.search(r"\b(?:ct|et|pt|mt|st)\b", lowered)
    )


def _is_pregame_status(status: str) -> bool:
    lowered = status.lower()
    return bool(
        lowered
        and (
            _is_time_like_status(lowered)
            or any(token in lowered for token in ("pre-game", "pregame", "scheduled", "preview", "warmup", "not started", "lineups"))
        )
    )


def _is_live_status(status: str) -> bool:
    lowered = status.lower()
    return bool(
        lowered
        and any(token in lowered for token in ("live", "in progress", "top of", "bottom of", "inning", "quarter", "period", "half"))
    )


def _recommendation_lane(item: Mapping[str, Any]) -> str:
    status = _safe_text(
        item.get("status_display"),
        item.get("status_context"),
        item.get("game_state", {}).get("detailed") if isinstance(item.get("game_state"), Mapping) else None,
        item.get("game_state", {}).get("abstract") if isinstance(item.get("game_state"), Mapping) else None,
        default="",
    ).lower()
    settlement = item.get("settlement") if isinstance(item.get("settlement"), Mapping) else {}
    settlement_status = _safe_text(
        settlement.get("status") if isinstance(settlement, Mapping) else None,
        settlement.get("status_label") if isinstance(settlement, Mapping) else None,
        item.get("settlement_status"),
        item.get("settlement_state"),
        item.get("settlement_label"),
        default="",
    ).lower()
    settlement_result = _safe_text(
        settlement.get("result") if isinstance(settlement, Mapping) else None,
        item.get("settlement_result"),
        item.get("result"),
        default="",
    ).lower()
    if any(token in status for token in ("final", "completed", "settled", "resolved", "graded")):
        return "archived"
    if settlement_status in {"final", "completed", "settled", "resolved", "graded"}:
        return "archived"
    if settlement_result in {"won", "lost", "push", "graded", "final", "completed", "settled", "resolved"}:
        return "archived"
    if _is_pregame_status(status):
        return "pregame"
    if _is_live_status(status) and (
        bool(item.get("is_live"))
        or _safe_text(item.get("live_projection"), default="") not in {"", "-"}
        or _safe_text(item.get("live_total"), default="") not in {"", "-"}
    ):
        return "live"
    if bool(item.get("is_live")) and not _is_pregame_status(status):
        return "live"
    return "pregame"


def _recommendation_card(item: Mapping[str, Any]) -> dict[str, Any]:
    card = _copy_mapping(item)
    if card.get("artifact_features") or card.get("feature_coverage"):
        card["artifact_features"] = dict(card.get("artifact_features") or {})
        card["feature_coverage"] = dict(card.get("feature_coverage") or card.get("artifact_features", {}).get("feature_coverage") or {})
    coverage_profile = build_feature_coverage_profile(card.get("feature_coverage"))
    if coverage_profile:
        card.update(coverage_profile)
    lane = _recommendation_lane(card)
    line = _number(card.get("line"), card.get("line_open"), card.get("market_data", {}).get("current_line") if isinstance(card.get("market_data"), Mapping) else None)
    edge = _number(card.get("edge"), card.get("adjusted_edge"), card.get("expected_value"), card.get("ev_current"))
    provenance = card.get("provenance") if isinstance(card.get("provenance"), Mapping) else {}
    sport_context = card.get("sport_context") if isinstance(card.get("sport_context"), Mapping) else {}
    trace_path = _safe_text(
        provenance.get("source_path") if isinstance(provenance, Mapping) else None,
        provenance.get("source") if isinstance(provenance, Mapping) else None,
        card.get("source_path"),
        card.get("source"),
        card.get("surface_title"),
        default="",
    )
    if not trace_path:
        trace_path = "/".join(
            part
            for part in (
                _safe_text(card.get("sport_slug"), card.get("sport"), default="sport").lower(),
                _safe_text(card.get("surface_key"), default="board"),
                _safe_text(card.get("market_key"), card.get("market"), default="market").lower(),
                _safe_text(card.get("selection"), card.get("pick"), card.get("name"), card.get("player_name"), default="candidate"),
            )
            if part
        )
    trace = {
        "path": trace_path,
        "source": _safe_text(provenance.get("source") if isinstance(provenance, Mapping) else None, card.get("source"), card.get("surface_title"), default=""),
        "source_id": _safe_text(provenance.get("source_id") if isinstance(provenance, Mapping) else None, card.get("candidate_id"), card.get("recommendation_id"), card.get("prediction_id"), default=""),
        "selected_date": _safe_text(provenance.get("selected_date") if isinstance(provenance, Mapping) else None, card.get("selected_date"), card.get("date"), card.get("context_label"), default=""),
        "surface_key": _safe_text(card.get("surface_key"), default=""),
        "surface_title": _safe_text(card.get("surface_title"), default=""),
        "sport_slug": _safe_text(card.get("sport_slug"), card.get("sport"), default="").lower(),
        "selection": _safe_text(card.get("selection"), card.get("pick"), card.get("name"), card.get("player_name"), default=""),
        "market": _safe_text(card.get("market"), card.get("market_label"), card.get("market_key"), default=""),
        "matchup": _safe_text(sport_context.get("matchup") if isinstance(sport_context, Mapping) else None, card.get("matchup"), default=""),
    }
    trace = {key: value for key, value in trace.items() if value}
    # _movement_summary() renders a short human-readable string, but the
    # structured movement object computed upstream by
    # _enrich_candidates_with_odds_history() (previous_line/last_line/delta/
    # trend/percent_change/history) used to get discarded here -- this card
    # is the last stop before the board contract reaches the frontend, and
    # the frontend has no other way to render a real line-movement display
    # without those fields. Keep both: the structured object under
    # "movement", and the short string under "movement_summary".
    movement_context = card.get("movement") if isinstance(card.get("movement"), Mapping) else {}
    card.update(
        {
            "lane": lane,
            "sport": _safe_text(card.get("sport"), card.get("sport_slug"), default="sport").lower(),
            "team": _safe_text(card.get("team"), card.get("team_name"), default="—"),
            "player": _safe_text(card.get("player_name"), card.get("name"), default="—"),
            "market": _safe_text(card.get("market"), card.get("market_label"), default="—"),
            "line": line,
            "movement": {
                "previous_line": movement_context.get("previous_line"),
                "last_line": movement_context.get("last_line"),
                "delta": movement_context.get("delta"),
                "trend": _safe_text(movement_context.get("trend"), movement_context.get("movement"), default="flat"),
                "percent_change": movement_context.get("percent_change"),
                "last_updated": movement_context.get("last_updated"),
                "history": movement_context.get("history") if isinstance(movement_context.get("history"), list) else [],
            },
            "movement_summary": _movement_summary(card),
            "simulated_edge": edge,
            "trace": trace,
            "trace_path": trace.get("path"),
            "publication_priority": card.get("publication_priority"),
        }
    )
    return card


def _dedupe_line_token(value: Any) -> str:
    if value in (None, "", "-"):
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value).strip().lower()
    return str(int(number)) if number.is_integer() else str(number)


# 2026-07-27, user-reported: "Tyler Phillips outs is listed twice from two
# sources." Confirmed on the live board -- the "Pitcher top props" rail emits
# {market: "outs recorded", selection: "Over 15+"} and the props-artifact
# candidates emit {market: "pitcher outs", selection: "OVER Tyler Phillips"}
# for the SAME bet (same player, matchup, line 14.5, odds -130). The #29 core
# key compared raw market and selection strings, so the pair could never
# collide. Same class observed for Peterson and Keller in the same snapshot.
#
# The fix canonicalizes the two fields the sources disagree on:
#   market  -> role prefix (pitcher/hitter/batter) stripped + synonym-mapped,
#              so "outs recorded" and "pitcher outs" both key as "outs";
#   selection -> collapsed to its side token (over/under) -- but ONLY when the
#              item carries a player subject, so game markets ("Home ML",
#              "Over 8.5" totals) keep their full selection and today's
#              behavior exactly.
# Lines stay the #29 wildcard: Ohtani-style pitcher-Ks vs batter-Ks for the
# same player survive because their lines differ and both are present.
_MARKET_FAMILY_SYNONYMS = {
    "outs recorded": "outs",
    "walks allowed": "walks",
}
_ROLE_PREFIXES = ("pitcher ", "hitter ", "batter ")


def _canonical_market_family(market: str) -> str:
    text = " ".join(str(market or "").strip().lower().replace("+", " ").split())
    for prefix in _ROLE_PREFIXES:
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    return _MARKET_FAMILY_SYNONYMS.get(text, text)


def _selection_side(selection: str) -> str | None:
    token = str(selection or "").strip().lower().split(" ", 1)[0] if selection else ""
    return token if token in ("over", "under") else None



def dedupe_recommendation_items(items: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Collapse the same underlying pick arriving in different shapes (#29).

    A pick reaches the board twice: as the full candidate (~100 keys, carries
    recommendation_id, confidence as a "38%" string) and as a reduced
    blotter/ranked row (~35 keys, no recommendation_id, confidence as 38.0).
    `_recommendation_sources` concatenates several response keys, so both land
    in one list and the board rendered each pick twice.

    The previous key joined id/name/market parts with `if part`, which DROPPED
    empty components instead of holding their position -- so the two shapes
    produced keys of different arity ("<recid>|over 0.5|hitter home runs" vs
    "over 0.5|hitter home runs") and could never collide however obviously
    identical the pick was. Keying on identifiers that only ONE representation
    carries cannot dedupe across representations. The same broken key existed
    in a second copy in pipeline/intelligence_state.py; both now call this.

    Two passes, both needed:
      1. An explicit id match is authoritative when both sides carry one.
      2. Otherwise the semantic identity every shape can express.

    `line` is handled separately and deliberately, because putting it in the
    tuple reproduces the original bug one field over: the reduced row often has
    no line, so the tuples differed only by '0.5' vs '', and nothing matched.
    Any field only one representation carries is unusable as a hard key
    component. So the core identity excludes the line, and the line is compared
    as a wildcard: a missing line on either side still matches, while two
    genuinely different lines on the same player+market+selection stay distinct.
    The core mirrors the identity used by collect_candidates and
    _drop_entityless_prop_duplicates in syndicate/features/intelligence.py, so
    they agree on what "the same pick" means, and selection is included so Over
    and Under never collapse into each other.
    """
    deduped: list[Mapping[str, Any]] = []
    seen_ids: set[str] = set()
    seen_lines_by_core: dict[tuple[str, ...], set[str]] = {}
    for item in items:
        if not isinstance(item, Mapping):
            continue
        explicit_ids = [
            value
            for value in (
                _safe_text(item.get("recommendation_id"), default="").strip().lower(),
                _safe_text(item.get("candidate_id"), default="").strip().lower(),
                _safe_text(item.get("prediction_id"), default="").strip().lower(),
            )
            if value
        ]
        if any(value in seen_ids for value in explicit_ids):
            continue

        selection = _safe_text(item.get("selection"), item.get("pick"), default="").strip().lower()
        player_subject = _safe_text(item.get("player_name"), default="").strip().lower()
        side = _selection_side(selection)
        # Side-collapse only with a real player subject (see the
        # canonicalization comment above): "OVER Tyler Phillips" and
        # "Over 15+" are the same side of the same prop, while a game total's
        # "over 8.5" must keep its full selection.
        selection_component = side if (player_subject and side) else selection
        core = (
            _safe_text(item.get("sport_slug"), item.get("sport"), default="").strip().lower(),
            _safe_text(item.get("matchup"), default="").strip().lower(),
            _canonical_market_family(_safe_text(item.get("market"), item.get("market_label"), item.get("market_key"), default="")),
            player_subject or _safe_text(item.get("name"), default=selection).strip().lower(),
            selection_component,
        )
        line_token = _dedupe_line_token(item.get("line"))
        if any(core):
            seen_line_tokens = seen_lines_by_core.get(core)
            if seen_line_tokens is not None and (
                not line_token or "" in seen_line_tokens or line_token in seen_line_tokens
            ):
                continue
            seen_lines_by_core.setdefault(core, set()).add(line_token)

        seen_ids.update(explicit_ids)
        deduped.append(item)
    return deduped


def _recommendation_sources(payload: Mapping[str, Any] | None) -> list[Mapping[str, Any]]:
    current = _copy_mapping(payload)
    sources: list[Mapping[str, Any]] = []

    # Both early returns used to hand back `sources` raw, skipping the dedup at
    # the bottom of this function entirely -- so whenever an upstream key was
    # already populated (the common case: response["recommendations"] carrying
    # both the full candidates and the reduced blotter rows), every duplicate
    # went straight through no matter how the dedup key was written. Fixing the
    # key alone did nothing until these returns went through it too (#29).
    board = current.get("board") if isinstance(current.get("board"), Mapping) else None
    if isinstance(board, Mapping):
        top_overall = board.get("top_overall")
        if isinstance(top_overall, list):
            sources.extend(item for item in top_overall if isinstance(item, Mapping))
        if sources:
            return dedupe_recommendation_items(sources)

    direct_recommendations = current.get("recommendations")
    if isinstance(direct_recommendations, list):
        sources.extend(item for item in direct_recommendations if isinstance(item, Mapping))
        if sources:
            return dedupe_recommendation_items(sources)

    response = current.get("response") if isinstance(current.get("response"), Mapping) else None
    if isinstance(response, Mapping):
        response_recommendations = response.get("recommendations")
        if isinstance(response_recommendations, list):
            sources.extend(item for item in response_recommendations if isinstance(item, Mapping))

    analysis = current.get("analysis") if isinstance(current.get("analysis"), Mapping) else None
    if isinstance(analysis, Mapping):
        analysis_recommendations = analysis.get("recommendations")
        if isinstance(analysis_recommendations, list):
            sources.extend(item for item in analysis_recommendations if isinstance(item, Mapping))
        top_live_opportunities = analysis.get("top_live_opportunities")
        if isinstance(top_live_opportunities, list):
            sources.extend(item for item in top_live_opportunities if isinstance(item, Mapping))

    top_opportunities = current.get("top_opportunities")
    if isinstance(top_opportunities, list):
        sources.extend(item for item in top_opportunities if isinstance(item, Mapping))

    return dedupe_recommendation_items(sources)


def build_intelligence_board_contract(response: Mapping[str, Any] | None) -> dict[str, Any]:
    payload = _copy_mapping(response)
    recommendations = _recommendation_sources(payload)
    cards = [_recommendation_card(item) for item in recommendations if isinstance(item, Mapping)]
    cards.sort(
        key=lambda card: (
            int(_number(card.get("publication_priority")) or 0),
            _number(card.get("coverage_score")) or 0.0,
            # A candidate whose advanced inputs are missing or unpublished is
            # less trustworthy than one whose inputs are ready, regardless of
            # how large its raw edge looks -- that is the whole point of the
            # readiness gate. It was expressed nowhere in this ordering, and in
            # the scorer only as a <=0.05 nudge to confidence, far too small to
            # act as a gate. Sorting on it above `score` is what actually makes
            # "prioritise ready advanced inputs" true.
            bool(card.get("advanced_ready")),
            # `score` is the pipeline's composite judgement -- edge x confidence
            # minus the tier penalty, plus the risk-profile and market-focus
            # adjustments. It was absent from this sort entirely, so every
            # scoring decision the pipeline made was discarded at presentation
            # time and the board ranked on raw simulated_edge instead. That is
            # why a "highest confidence" query and a "highest upside" query
            # returned identical orderings even once the scorer told them apart.
            # It sits above simulated_edge and confidence deliberately: both are
            # components already folded into score, so consulting them first let
            # a single raw component outvote the composite.
            _number(card.get("score")) or 0.0,
            _number(card.get("simulated_edge")) or 0.0,
            # confidence can be a display-formatted percent string (e.g.
            # "63.0%", from MLB HR Targets fallback candidates --
            # intelligence.py's _mlb_hr_targets_candidates) rather than a bare
            # float; a plain float() crashed the whole board-publish call
            # whenever one of these reached this sort. _number() (defined
            # above) already strips "%" and tolerates "-"/empty by returning
            # None.
            _number(card.get("confidence")) or 0.0,
            # source_summary_score is the qualitative read of a basketball
            # prop's recent-form writeup (does the text argue FOR or AGAINST
            # the pick), clamped to [-3.0, 3.0] and, until now, computed and
            # displayed but never ranked on -- so two props identical on edge
            # and confidence ordered arbitrarily even when one writeup argued
            # against itself.
            #
            # It goes last, as a tiebreaker, on purpose. Folding it into
            # `score` instead was tried and regressed
            # test_intelligence_query_prioritizes_ready_advanced_inputs: at full
            # weight a WNBA summary outranked an advanced-ready NBA candidate,
            # i.e. a qualitative text signal overrode a data-readiness one.
            # Picking a smaller weight would just be fitting a magic number to
            # the tests. As a tiebreaker it only speaks when the quantitative
            # signals above are genuinely equal, which is the case it exists
            # for. 0.0 for non-basketball and non-prop candidates by
            # construction, so it is inert everywhere else.
            _number(card.get("source_summary_score")) or 0.0,
        ),
        reverse=True,
    )
    lane_counts = {
        "live": sum(1 for card in cards if card.get("lane") == "live"),
        "pregame": sum(1 for card in cards if card.get("lane") == "pregame"),
        "archived": sum(1 for card in cards if card.get("lane") == "archived"),
    }
    active_lanes = [lane for lane in ("live", "pregame") if lane_counts.get(lane)]
    board_summary = {
        "headline": _safe_text(payload.get("headline"), payload.get("summary"), default="The Syndicate board"),
        "recommendation_count": len(cards),
        "live_count": lane_counts["live"],
        "pregame_count": lane_counts["pregame"],
        "archived_count": lane_counts["archived"],
        "active_lanes": active_lanes,
    }
    _intel_trace(
        "board_input",
        opportunities_received=len(recommendations),
        cards=len(cards),
        lane_counts=lane_counts,
        active_lanes=active_lanes,
    )
    waterfall = [
        {"step": "source_response", "count": len(recommendations), "label": "Raw response recommendations"},
        {"step": "normalized_cards", "count": len(cards), "label": "Deduped board cards"},
        {"step": "live_lane", "count": lane_counts["live"], "label": "Live recommendations"},
        {"step": "pregame_lane", "count": lane_counts["pregame"], "label": "Pregame recommendations"},
        {"step": "archived_lane", "count": lane_counts["archived"], "label": "Archived recommendations"},
    ]
    return {
        "schema": "intelligence_board_v1",
        "card_fields": ["sport", "team", "player", "market", "line", "projected", "live_projection", "actual", "status_display", "movement", "movement_summary", "simulated_edge", "trace_path", "game_pk", "coverage_score", "coverage_tier", "coverage_warnings", "publication_status", "publication_priority"],
        "recommendation_count": len(cards),
        "lane_counts": lane_counts,
        "active_lanes": active_lanes,
        "board_summary": board_summary,
        "cards": cards,
        "waterfall": waterfall,
    }


__all__ = ["build_intelligence_board_contract"]