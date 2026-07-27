"""Layer 1: the full market/odds inventory contract.

This is deliberately NOT a "candidate" (a recommendation/pick). It is a
descriptive record of a single available market/line -- what a real
sportsbook interface would show -- independent of whether anything has an
edge on it. Candidate/recommendation logic (Layer 2, e.g.
`syndicate.features.intelligence.collect_candidates` and its
`UniversalCandidate` wrapper in `intelligence_contracts.py`) is meant to be
built ON TOP of this inventory, ranking and surfacing a subset of it -- it
does not replace or duplicate it.

Row identity for the odds<->sim join is (game_id, market, period, entity),
with entity=None for game-level markets (moneyline/spread/total) and the
player's name for props. A sim row's projection is joined onto every odds
row that shares that identity, regardless of side -- e.g. both the home-ML
and away-ML odds rows for a game join to the same win-probability sim row.
A two-sided market where Over and Under quote against the SAME sim row
(one prop, one total) can still get genuinely complementary probabilities:
if the sim row carries `model_prob_over` (P(outcome > line)) instead of a
flat `sim_projection`, the join derives each side's value from the ODDS
row's own `side` (Over gets `model_prob_over`, Under gets its complement)
and stamps `model_side` with whichever side the sim actually favors, so a
consumer can badge the correct row without any join-key changes.

The join result itself is the player/game-status-awareness signal: an odds
row that can't be matched to a current sim row for the SAME entity, when a
sim row exists for the same market/period under a DIFFERENT entity, means
the sim modeled someone else in that slot (a pitching change, a lineup
swap, a scratched player) -- the world moved since the last sim ran, and
this is flagged as needing a resim rather than silently dropped or shown
as if it were a stable projection.
"""

from __future__ import annotations

from typing import Any

# Canonical fields for a single market/odds inventory row. Kept as a plain
# dict (not a dataclass) -- every consumer in this codebase already reads
# candidate-shaped data via `.get(...)`, and this is meant to be handed
# straight to json.dumps for the board API without a conversion step.
INVENTORY_ROW_FIELDS: frozenset[str] = frozenset(
    {
        # Identity / attribution -- resolved once here, not re-derived downstream
        "sport_slug",
        "game_id",
        "event_id",
        "matchup",
        "commence_time",
        "game_state",  # "pregame" | "live" | "final"
        "market_type",  # "game" | "prop"
        "market",
        "period",  # "full_game" | "first_7" | "bottom_7" | etc
        "side",  # "home"/"away"/"over"/"under"
        "entity",  # player name for props, None for game markets
        "team",
        "opponent_team",
        "line",
        "odds",
        # Sim join result
        "sim_projection",
        # Which side ("over"/"under"/"home"/"away") the sim's own
        # probability actually favors for this market -- same value on
        # both sibling rows of a two-sided market (e.g. both the Over and
        # Under quote for one prop), so a consumer can badge whichever
        # row's own `side` matches. None when the sim row didn't supply a
        # side-aware probability (see model_prob_over below).
        "model_side",
        # The actual projected stat value for a prop (e.g. 4.8 strikeouts),
        # distinct from sim_projection above -- sim_projection is always a
        # 0-1 fraction (win probability/edge, rendered as a percent by the
        # board) for every current market type, game or prop, while this is
        # the model's raw projected count for props specifically. None for
        # game-level markets, which have no equivalent "count" to project.
        "projected_value",
        "sim_source",
        "join_status",  # "matched" | "unmatched_no_sim_coverage" | "unmatched_needs_resim"
        "join_note",
        # Eligibility
        "is_eligible",
    }
)

JOIN_STATUS_MATCHED = "matched"
JOIN_STATUS_NO_SIM_COVERAGE = "unmatched_no_sim_coverage"
JOIN_STATUS_NEEDS_RESIM = "unmatched_needs_resim"


def _normalize_entity(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text.casefold() or None


def _row_key(row: dict[str, Any]) -> tuple[Any, Any, Any, str | None]:
    return (
        row.get("game_id"),
        str(row.get("market") or "").strip().casefold(),
        str(row.get("period") or "full_game").strip().casefold(),
        _normalize_entity(row.get("entity")),
    )


def _market_period_key(row: dict[str, Any]) -> tuple[Any, Any, Any]:
    """Same as _row_key but without entity -- used to detect "a sim row
    exists for this market/period, just under a different entity" (the
    needs-resim case) versus "no sim coverage for this market at all"."""
    key = _row_key(row)
    return key[0], key[1], key[2]


def join_odds_to_sim(odds_rows: list[dict[str, Any]], sim_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Join raw odds rows to sim projections by (game_id, market, period,
    entity). Returns one inventory row per input odds row -- every quoted
    line is preserved regardless of whether a sim covers it.
    """
    sim_by_key: dict[tuple[Any, Any, Any, str | None], dict[str, Any]] = {}
    # Maps normalized entity -> original display text, per (game, market,
    # period), so a mismatch note can show the human-readable name rather
    # than the casefolded matching key.
    sim_entities_by_market_period: dict[tuple[Any, Any, Any], dict[str | None, Any]] = {}
    for sim_row in sim_rows:
        if not isinstance(sim_row, dict):
            continue
        key = _row_key(sim_row)
        sim_by_key[key] = sim_row
        market_period_key = _market_period_key(sim_row)
        sim_entities_by_market_period.setdefault(market_period_key, {})[key[3]] = sim_row.get("entity")

    inventory: list[dict[str, Any]] = []
    for odds_row in odds_rows:
        if not isinstance(odds_row, dict):
            continue
        key = _row_key(odds_row)
        sim_match = sim_by_key.get(key)

        join_status: str
        join_note: str | None = None
        sim_projection: Any = None
        model_side: Any = None
        projected_value: Any = None
        sim_source: Any = None

        if sim_match is not None:
            join_status = JOIN_STATUS_MATCHED
            model_prob_over = sim_match.get("model_prob_over")
            if isinstance(model_prob_over, (int, float)) and odds_row.get("side") in ("over", "under"):
                # A side-aware sim row (e.g. a two-sided prop/total) carries
                # ONE probability of the "over" outcome; the matching Over
                # and Under odds rows share this same sim row (same join
                # key, no side component -- see module docstring), so the
                # complementary value for each is derived here from the
                # ODDS row's own side rather than baked into the sim row.
                probability_over = max(0.0, min(1.0, float(model_prob_over)))
                sim_projection = probability_over if odds_row.get("side") == "over" else 1.0 - probability_over
                model_side = "over" if probability_over >= 0.5 else "under"
            else:
                sim_projection = sim_match.get("sim_projection")
                model_side = sim_match.get("model_side")
            projected_value = sim_match.get("projected_value")
            sim_source = sim_match.get("sim_source")
        else:
            market_period_key = _market_period_key(odds_row)
            other_entities = sim_entities_by_market_period.get(market_period_key, {})
            other_normalized_keys = set(other_entities) - {key[3]}
            # Any sim coverage for this exact market/period under a
            # DIFFERENT entity means the sim modeled someone else in this
            # slot -- the world changed since the sim last ran.
            if other_normalized_keys:
                join_status = JOIN_STATUS_NEEDS_RESIM
                modeled_entity = other_entities.get(next(iter(other_normalized_keys)))
                join_note = (
                    f"Sim projected {modeled_entity or 'a different entity'} for this market; "
                    f"current odds show {odds_row.get('entity') or 'a different entity'} -- resim needed."
                )
            else:
                join_status = JOIN_STATUS_NO_SIM_COVERAGE

        is_eligible = join_status != JOIN_STATUS_NEEDS_RESIM

        row = {field: odds_row.get(field) for field in INVENTORY_ROW_FIELDS if field in odds_row}
        row.update(
            {
                "sim_projection": sim_projection,
                "model_side": model_side,
                "projected_value": projected_value,
                "sim_source": sim_source,
                "join_status": join_status,
                "join_note": join_note,
                "is_eligible": is_eligible,
            }
        )
        inventory.append(row)

    return inventory
