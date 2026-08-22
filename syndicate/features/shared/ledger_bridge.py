"""Bridge settled results into the portfolio ledger (#216).

THE SPLIT THIS EXISTS TO CROSS
------------------------------
There are two ledgers and `/portfolio` reads only one. The repo says so itself,
in a comment at `syndicate/blueprints/intelligence.py`: `/api/portfolio/bets`
writes `data/prediction_ledger.json`, "the same store /portfolio reads", unlike
`/api/intelligence/portfolio-event`, which writes "a separate evaluation ledger
the Portfolio page never reads".

Both have settlement autoruns and both are enabled
(`EVALUATION_SETTLEMENT_ENABLE_REFRESH_WORKER_AUTORUN`,
`RECONCILIATION_ENABLE_REFRESH_WORKER_AUTORUN`). Production still showed
`settled_count: 0` on five tracked bets.

BRIDGE, DO NOT MERGE
--------------------
Merging the two stores means reconciling two schemas with two writers and two
autoruns, for no gain the user can see. Bridging copies outcomes across on the
key they already share -- `recommendation_id`, which the portfolio's own parlay
legs carry (verified in the live `/api/portfolio/summary` payload).

PARLAYS
-------
A parlay is the case reconciliation structurally cannot handle: it has no single
market to match, so `_match_result_row` never resolves one and it stays pending
forever no matter how many of its legs are decided. That is not a hypothetical --
the one parlay in the live ledger is a 4-leg cross-sport bet sitting at pending.

Settlement rules, which are the actual bookmaker rules and not a simplification:
  - ANY leg loses      -> the parlay loses, immediately, however many legs are
                          still undecided. Waiting for them would be wrong.
  - ALL legs win        -> the parlay wins.
  - a leg pushes/voids  -> that leg drops out and the parlay settles on the rest
                          (a push is not a loss).
  - otherwise           -> still pending, and left alone.

PnL uses the parlay's own stored combined `odds`, not a product recomputed from
legs -- the price was struck as a whole and the book's number is the truth.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping

from syndicate.features.prediction_ledger import load_all_predictions
from syndicate.features.prediction_ledger import record_result

_DECISIVE = {"win", "loss", "push", "void"}
_SETTLED = {"win", "loss"}


def _text(value: Any) -> str:
    return str(value or "").strip().lower()


def _american_profit(odds: Any, stake: Any) -> float | None:
    try:
        price = float(odds)
        wager = float(stake)
    except Exception:
        return None
    if price == 0:
        return None
    return wager * (price / 100.0 if price > 0 else 100.0 / abs(price))


def _recommendation_ids(prediction: Mapping[str, Any]) -> set[str]:
    ids: set[str] = set()
    features = prediction.get("features_snapshot")
    if isinstance(features, Mapping):
        value = _text(features.get("recommendation_id"))
        if value:
            ids.add(value)
    for leg in (prediction.get("legs") or []):
        if isinstance(leg, Mapping):
            value = _text(leg.get("recommendation_id"))
            if value:
                ids.add(value)
    return ids


_AMBIGUOUS = object()


def _first_text(payload: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = _text(payload.get(key))
        if value:
            return value
    return ""


def _line_token(value: Any) -> str:
    try:
        return f"{float(value):g}"
    except (TypeError, ValueError):
        return ""


def _settlement_identity(payload: Mapping[str, Any]) -> str | None:
    """A STABLE identity for the thing that was bet, independent of price.

    WHY THIS EXISTS (`#505`). `recommendation_id` is not stable. It is
    `_stable_id("rec", {...})` over `prediction_id` + the WHOLE recommendation
    payload + artifact_metadata — and `pipeline/intelligence_state.py` says so
    itself: those ids are minted "from a content hash of the full recommendation
    payload (incl. live odds/edge/probability)", which "would mint a fresh 'new'
    pending row almost every cycle purely from ordinary price drift". The board
    re-records 150 recommendations per rebuild.

    So a portfolio bet captures whatever id was on screen at click time, and
    settlement later decides a DIFFERENT snapshot of the same wager. The ids
    never meet. That is the measured `4,560 no_key_match of 8,276` and the
    `matched: 0` this repo already records against the settlement join.

    MODELLED ON THE JOIN THAT WORKS. `clv_opening_ledger._opening_key` solves
    the same identity problem and reports `unkeyable=0` on 1,538 real rows
    today. This is that key with ONE deliberate difference and ONE forced one:

    - **bookmaker REMOVED, deliberately.** An outcome is book-independent: a
      bet on the same side at the same line wins or loses identically at every
      book. Price is book-specific; result is not. Keeping it would split one
      settled outcome across every book that quoted it.
    - **segment REMOVED, and this is forced rather than chosen.** The bet slip
      (`POST /api/portfolio/bets`) captures exactly
      `recommendation_id, pick, line, event_id, game_date` into
      `features_snapshot`. Segment is not among them, so an identity carrying it
      could never match a portfolio bet at all.

    THE COST OF DROPPING SEGMENT, AND WHY IT IS NOT SWALLOWED. A first-half and
    a full-game bet on the same event/market/side/line collapse onto one key.
    `learnings.md` 2026-08-15 is explicit -- **never treat equality of a LABEL
    as identity of a BET** -- so the index below DETECTS that collision and
    refuses to settle from it, rather than picking whichever arrived first.
    """
    event_id = _first_text(payload, "event_id", "game_id")
    market = _first_text(payload, "market", "market_key")
    if not event_id or not market:
        # No identity, no join. Same rule as `_opening_key`: a row that cannot
        # be keyed could never be matched, and guessing one invents a bet.
        return None
    # `side` is what was wagered. The bet slip stores it as `pick` precisely
    # because `selection` holds the player's name on a prop, not the side --
    # that endpoint's own comment says so.
    side = _first_text(payload, "side", "pick")
    # The entity the wager is ON: a player for a prop, a team for a game line.
    # `selection` is last because it is the most overloaded of the aliases.
    entity = _first_text(payload, "player_name", "player", "name", "team", "selection")
    return "|".join(
        (
            f"event_id={event_id}",
            f"market={market.lower()}",
            f"entity={entity.lower()}",
            f"side={side.lower()}",
            f"line={_line_token(payload.get('line'))}",
        )
    )


def _decided_outcome(record: Mapping[str, Any]) -> dict[str, Any] | None:
    result = record.get("result") if isinstance(record.get("result"), Mapping) else record
    outcome = _text(result.get("outcome") or result.get("result") or result.get("grade"))
    if outcome not in _DECISIVE:
        return None
    return {
        "outcome": outcome,
        "closing_price": result.get("closing_price") or result.get("closing_odds"),
        "closing_line": result.get("closing_line"),
    }


def _outcome_by_recommendation(records: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """recommendation_id -> {outcome, closing_price, closing_line} from whatever
    settled records the evaluation ledger holds.

    Kept as the FIRST tier even though `#505` showed the ids drift: when one
    does match it is an exact identity with no inference in it, and matching it
    costs nothing. The identity index below is the fallback, not the
    replacement.
    """
    index: dict[str, dict[str, Any]] = {}
    for record in records or ():
        if not isinstance(record, Mapping):
            continue
        key = _text(record.get("recommendation_id"))
        if not key:
            continue
        decided = _decided_outcome(record)
        if decided is None:
            continue
        index[key] = decided
    return index


def _outcome_by_identity(records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Stable identity -> outcome, with genuine ambiguity marked and refused.

    A key whose settled records DISAGREE on the outcome is stored as
    `_AMBIGUOUS` rather than resolved. That is the `#505` cost of dropping
    `segment` made visible: two different bets collapsed onto one key. Settling
    either from it would be inventing a result, so the caller counts it and
    leaves the position pending.

    Records that AGREE are not ambiguous -- the same wager recorded under many
    drifting `recommendation_id`s is the normal case here, and is exactly what
    this index exists to collapse.
    """
    index: dict[str, Any] = {}
    for record in records or ():
        if not isinstance(record, Mapping):
            continue
        recommendation = record.get("recommendation") if isinstance(record.get("recommendation"), Mapping) else record
        key = _settlement_identity(recommendation)
        if not key:
            continue
        decided = _decided_outcome(record)
        if decided is None:
            continue
        existing = index.get(key)
        if existing is None:
            index[key] = decided
        elif existing is _AMBIGUOUS:
            continue
        elif existing.get("outcome") != decided.get("outcome"):
            index[key] = _AMBIGUOUS
    return index


def _leg_outcome(
    leg: Mapping[str, Any],
    index: Mapping[str, dict[str, Any]],
    identity_index: Mapping[str, Any] | None = None,
) -> str | None:
    existing = _text(leg.get("outcome") or leg.get("result"))
    if existing in _DECISIVE:
        return existing
    resolved = index.get(_text(leg.get("recommendation_id")))
    if resolved:
        return resolved["outcome"]
    if not identity_index:
        return None
    # `#505`: a parlay is the case that needed this most. Reconciliation cannot
    # settle a parlay at all -- it has no single market to match -- so the legs'
    # `recommendation_id`s were the ONLY route, and those drift with price. A
    # leg carries the same shape as a straight bet, so it keys the same way.
    outcome, _reason = _resolve_by_identity(leg, identity_index)
    return outcome


def settle_parlay_outcome(
    legs: Iterable[Mapping[str, Any]],
    index: Mapping[str, dict[str, Any]],
    identity_index: Mapping[str, Any] | None = None,
) -> str | None:
    """Bookmaker parlay rules. None means genuinely undecided -- leave pending.

    `identity_index` is optional so every existing caller and test keeps working
    unchanged; without it this behaves exactly as it did before `#505`.
    """
    legs = [leg for leg in (legs or ()) if isinstance(leg, Mapping)]
    if not legs:
        return None
    outcomes = [_leg_outcome(leg, index, identity_index) for leg in legs]
    if any(outcome == "loss" for outcome in outcomes):
        # Decided the moment ONE leg loses; the rest cannot rescue it.
        return "loss"
    live = [outcome for outcome in outcomes if outcome not in {"push", "void"}]
    if not live:
        # Every leg pushed or voided: stake returned, not a win.
        return "push"
    if all(outcome == "win" for outcome in live):
        return "win"
    return None


def _bet_identity_payload(prediction: Mapping[str, Any]) -> dict[str, Any]:
    """One flat payload to key a portfolio bet from.

    The bet slip splits a wager's identity across two places: `features_snapshot`
    carries `event_id`, `line` and `pick`, while `market` and `selection` sit at
    the top level. Neither alone can produce an identity, so this merges them,
    with `features_snapshot` winning on conflict because it is the more specific
    record of what was actually wagered.
    """
    merged: dict[str, Any] = {
        key: prediction.get(key)
        for key in ("sport", "market", "selection", "line", "event_id", "side", "pick")
        if prediction.get(key) is not None
    }
    features = prediction.get("features_snapshot")
    if isinstance(features, Mapping):
        for key, value in features.items():
            if value is not None:
                merged[key] = value
    return merged


def _resolve_by_identity(payload: Mapping[str, Any], identity_index: Mapping[str, Any]) -> tuple[str | None, str]:
    """(outcome, reason). Refuses an ambiguous key rather than guessing."""
    key = _settlement_identity(_bet_identity_payload(payload))
    if not key:
        return None, "unkeyable_bet"
    resolved = identity_index.get(key)
    if resolved is None:
        return None, "no_settled_match"
    if resolved is _AMBIGUOUS:
        # Two settled records disagree under this key -- the collapsed-segment
        # case. Settling from it would invent a result.
        return None, "identity_ambiguous"
    return resolved["outcome"], "matched"


def bridge_settled_results(
    *,
    evaluation_records: Iterable[Mapping[str, Any]] | None = None,
    ledger_path: Path | str | None = None,
) -> dict[str, Any]:
    """Copy decided outcomes into the portfolio ledger. Idempotent.

    Never raises: this runs inside a worker autorun, and a bridging failure must
    not take down settlement or the refresh cycle around it.
    """
    summary: dict[str, Any] = {
        "straight_settled": 0,
        "parlays_settled": 0,
        "skipped": 0,
        # `#505`: WHY a row missed, not just how many. The settlement join has
        # reported bare counts throughout -- this repo's own note on it reads
        # "4,560 no_key_match of 8,276 WITH NO PER-REASON BREAKDOWN DEEPER THAN
        # THE NAME" -- which is why `skipped: 25131` on 2026-08-22 could not
        # distinguish "the window held no settled records" from "the ids drift".
        # `clv_join` already works this way and that is why its coverage is
        # arguable. Same discipline here.
        "matched_by_id": 0,
        "matched_by_identity": 0,
        "skip_reasons": {
            "no_settled_match": 0,
            "unkeyable_bet": 0,
            "identity_ambiguous": 0,
            "parlay_legs_undecided": 0,
        },
        "index_sizes": {"by_id": 0, "by_identity": 0, "ambiguous": 0},
        "errors": [],
    }
    try:
        records = list(evaluation_records or [])
        index = _outcome_by_recommendation(records)
        identity_index = _outcome_by_identity(records)
        summary["index_sizes"] = {
            "by_id": len(index),
            "by_identity": sum(1 for value in identity_index.values() if value is not _AMBIGUOUS),
            "ambiguous": sum(1 for value in identity_index.values() if value is _AMBIGUOUS),
        }
        predictions = load_all_predictions(ledger_path=Path(ledger_path) if ledger_path else None)

        for prediction in predictions:
            result = prediction.get("result") if isinstance(prediction.get("result"), Mapping) else None
            if result and _text(result.get("outcome")) in _DECISIVE:
                continue

            is_parlay = _text(prediction.get("bet_type")) == "parlay"
            legs = prediction.get("legs") if isinstance(prediction.get("legs"), list) else []

            reason = "no_settled_match"
            if is_parlay:
                outcome = settle_parlay_outcome(legs, index, identity_index)
                if outcome is None:
                    reason = "parlay_legs_undecided"
            else:
                # TIER 1: exact id. No inference in it, so it wins when present.
                match = next((index[key] for key in _recommendation_ids(prediction) if key in index), None)
                if match is not None:
                    summary["matched_by_id"] += 1
                    outcome = match["outcome"]
                else:
                    # TIER 2: stable identity. The bet's own fields live across
                    # `features_snapshot` and the top level, so merge them --
                    # `event_id`/`line`/`pick` are in the former, `market`/
                    # `selection` in the latter, and the identity needs both.
                    outcome, reason = _resolve_by_identity(prediction, identity_index)
                    if outcome is not None:
                        summary["matched_by_identity"] += 1

            if outcome is None:
                summary["skipped"] += 1
                if reason in summary["skip_reasons"]:
                    summary["skip_reasons"][reason] += 1
                continue

            pnl: float | None = None
            stake = prediction.get("stake")
            if outcome == "loss" and stake is not None:
                try:
                    pnl = -float(stake)
                except Exception:
                    pnl = None
            elif outcome == "win":
                pnl = _american_profit(prediction.get("odds"), stake)
            elif outcome in {"push", "void"}:
                pnl = 0.0

            quote = prediction.get("quote") if isinstance(prediction.get("quote"), Mapping) else {}
            single = None if is_parlay else next(
                (index[key] for key in _recommendation_ids(prediction) if key in index), None
            )
            try:
                record_result(
                    prediction_id=prediction.get("id"),
                    outcome=outcome,
                    pnl=pnl,
                    # A parlay has no single closing price -- its legs each have
                    # their own -- so CLV is left unset rather than invented from
                    # one arbitrary leg.
                    original_price=None if is_parlay else (quote.get("price") or prediction.get("odds")),
                    closing_price=None if is_parlay else (single or {}).get("closing_price"),
                    closing_line=None if is_parlay else (single or {}).get("closing_line"),
                    ledger_path=Path(ledger_path) if ledger_path else None,
                )
            except Exception as exc:  # noqa: BLE001
                summary["errors"].append(f"{prediction.get('id')}: {type(exc).__name__}: {exc}")
                continue
            summary["parlays_settled" if is_parlay else "straight_settled"] += 1
    except Exception as exc:  # noqa: BLE001
        summary["errors"].append(f"{type(exc).__name__}: {exc}")
    return summary
