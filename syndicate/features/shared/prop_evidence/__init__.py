"""Player-prop evidence for Ask the Syndicate, one provider per sport.

    from syndicate.features.shared.prop_evidence import build_prop_evidence

    evidence = build_prop_evidence(board_row, selected_date="2026-09-17")
    section = evidence.to_section() if evidence else None

`build_prop_evidence` returns None for a row that is not a player prop or a sport
with no provider. MLB is answered by its own reference fetchers in
`ask_the_syndicate_data.py` (their tables carry the same `layer` tags), plus the
shared `track_record` layer; see `docs/ai_context/prop_evidence_reference.md`.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from syndicate.features.shared.prop_evidence.contract import (
    ABSENT_PROVIDER_ERROR,
    LAYER_ORDER,
    SCHEMA,
    Layer,
    PropEvidence,
    PropSubject,
    absent,
)

logger = logging.getLogger(__name__)


def _basketball(subject: PropSubject) -> PropEvidence:
    from syndicate.features.shared.prop_evidence import basketball

    return basketball.build(subject)


def _nfl(subject: PropSubject) -> PropEvidence:
    from syndicate.features.shared.prop_evidence import football

    return football.build_nfl(subject)


def _ncaaf(subject: PropSubject) -> PropEvidence:
    from syndicate.features.shared.prop_evidence import football

    return football.build_ncaaf(subject)


def _nhl(subject: PropSubject) -> PropEvidence:
    from syndicate.features.shared.prop_evidence import nhl

    return nhl.build(subject)


def _soccer(subject: PropSubject) -> PropEvidence:
    from syndicate.features.shared.prop_evidence import soccer

    return soccer.build(subject)


PROVIDERS: dict[str, Callable[[PropSubject], PropEvidence]] = {
    "wnba": _basketball,
    "nba": _basketball,
    "nfl": _nfl,
    "ncaaf": _ncaaf,
    "nhl": _nhl,
    "soccer": _soccer,
}

# Sports with no provider, and why. NCAAB has no player model and no prop odds
# capture (`fetch_basketball_oddsapi_props_local.py` covers NBA/WNBA only), so
# there is nothing to read; inventing evidence for it is the failure this
# package exists to prevent. MLB is served by its reference fetchers.
NO_PROVIDER: dict[str, str] = {
    "ncaab": "no_producer:no NCAAB player model or prop capture exists",
    "mlb": "served_by_reference_fetchers",
}


def build_prop_evidence(row: dict[str, Any], *, selected_date: str) -> PropEvidence | None:
    """Evidence for one board prop row, or None. Never raises."""
    subject = PropSubject.from_board_row(row, selected_date=selected_date)
    if subject is None:
        return None
    provider = PROVIDERS.get(subject.sport)
    if provider is None:
        return None
    try:
        return provider(subject)
    except Exception:
        logger.exception("prop_evidence provider for %s raised on %r %r", subject.sport, subject.player_name, subject.market)
        evidence = PropEvidence(subject=subject, provider=f"{subject.sport}:error")
        for layer in LAYER_ORDER:
            evidence.set(absent(layer, f"{ABSENT_PROVIDER_ERROR}:see web log"))
        return evidence


__all__ = [
    "LAYER_ORDER",
    "Layer",
    "NO_PROVIDER",
    "PROVIDERS",
    "PropEvidence",
    "PropSubject",
    "SCHEMA",
    "build_prop_evidence",
]
