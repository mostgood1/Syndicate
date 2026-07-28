"""Canonical MLB live/pregame/final classification from StatsAPI status fields.

#100. At least ~10 places across mlb/cards.py, home.py, and intelligence.py
independently decided "is this game live" from MLB StatsAPI status data, and
several checked only status.abstract/abstractGameState, which reads "Live"
during warmup -- before the game has actually started (confirmed real
production data: BAL @ DET reporting status.abstract "Live" / status.detailed
"Warmup"). detailedState is required to catch that; this module is the one
shared implementation intelligence.py's _mlb_candidate_live_state already got
right. Do not reintroduce an abstract-only check at a new call site.

No other repo imports on purpose -- mlb/cards.py, home.py, and intelligence.py
all need to import this at module level, and the three already have a
function-local-import-only relationship with each other to avoid circularity.
"""

from __future__ import annotations

from typing import Any

_MLB_NON_LIVE_DETAILED_STATES = {"pre-game", "scheduled", "preview", "warmup"}
_MLB_FINAL_DETAILED_STATES = {"final", "game over", "completed", "completed early"}


def _is_final_text(abstract: str, detailed: str) -> bool:
    # mlb/cards.py's _cards_status_is_final (kept as the more-complete
    # implementation while consolidating #100) used a substring match on
    # "final" plus an explicit "completed early" (rain-shortened games) --
    # more permissive than a plain exact-match set, and safe given MLB's
    # detailedState vocabulary is small and fixed.
    return abstract == "final" or "final" in detailed or detailed in _MLB_FINAL_DETAILED_STATES


def mlb_status_is_live(abstract_state: Any, detailed_state: Any) -> bool:
    abstract = str(abstract_state or "").strip().lower()
    detailed = str(detailed_state or "").strip().lower()
    if _is_final_text(abstract, detailed):
        return False
    if detailed:
        return detailed not in _MLB_NON_LIVE_DETAILED_STATES
    # No detailedState available -- abstract is the best signal there is, and
    # it is only wrong (warmup) in the specific case detailedState resolves.
    return abstract == "live"


def mlb_status_is_final(abstract_state: Any, detailed_state: Any) -> bool:
    abstract = str(abstract_state or "").strip().lower()
    detailed = str(detailed_state or "").strip().lower()
    return _is_final_text(abstract, detailed)
