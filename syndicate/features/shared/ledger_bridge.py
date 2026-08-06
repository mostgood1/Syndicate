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


def _outcome_by_recommendation(records: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """recommendation_id -> {outcome, closing_price, closing_line} from whatever
    settled records the evaluation ledger holds."""
    index: dict[str, dict[str, Any]] = {}
    for record in records or ():
        if not isinstance(record, Mapping):
            continue
        key = _text(record.get("recommendation_id"))
        if not key:
            continue
        result = record.get("result") if isinstance(record.get("result"), Mapping) else record
        outcome = _text(result.get("outcome") or result.get("result") or result.get("grade"))
        if outcome not in _DECISIVE:
            continue
        index[key] = {
            "outcome": outcome,
            "closing_price": result.get("closing_price") or result.get("closing_odds"),
            "closing_line": result.get("closing_line"),
        }
    return index


def _leg_outcome(leg: Mapping[str, Any], index: Mapping[str, dict[str, Any]]) -> str | None:
    existing = _text(leg.get("outcome") or leg.get("result"))
    if existing in _DECISIVE:
        return existing
    resolved = index.get(_text(leg.get("recommendation_id")))
    return resolved["outcome"] if resolved else None


def settle_parlay_outcome(legs: Iterable[Mapping[str, Any]], index: Mapping[str, dict[str, Any]]) -> str | None:
    """Bookmaker parlay rules. None means genuinely undecided -- leave pending."""
    legs = [leg for leg in (legs or ()) if isinstance(leg, Mapping)]
    if not legs:
        return None
    outcomes = [_leg_outcome(leg, index) for leg in legs]
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


def bridge_settled_results(
    *,
    evaluation_records: Iterable[Mapping[str, Any]] | None = None,
    ledger_path: Path | str | None = None,
) -> dict[str, Any]:
    """Copy decided outcomes into the portfolio ledger. Idempotent.

    Never raises: this runs inside a worker autorun, and a bridging failure must
    not take down settlement or the refresh cycle around it.
    """
    summary: dict[str, Any] = {"straight_settled": 0, "parlays_settled": 0, "skipped": 0, "errors": []}
    try:
        index = _outcome_by_recommendation(evaluation_records or [])
        predictions = load_all_predictions(ledger_path=Path(ledger_path) if ledger_path else None)

        for prediction in predictions:
            result = prediction.get("result") if isinstance(prediction.get("result"), Mapping) else None
            if result and _text(result.get("outcome")) in _DECISIVE:
                continue

            is_parlay = _text(prediction.get("bet_type")) == "parlay"
            legs = prediction.get("legs") if isinstance(prediction.get("legs"), list) else []

            if is_parlay:
                outcome = settle_parlay_outcome(legs, index)
            else:
                match = next((index[key] for key in _recommendation_ids(prediction) if key in index), None)
                outcome = match["outcome"] if match else None

            if outcome is None:
                summary["skipped"] += 1
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
