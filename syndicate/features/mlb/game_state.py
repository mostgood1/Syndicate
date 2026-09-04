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


def mlb_feed_payload_is_final(payload: Any) -> bool:
    """True when a cached `feed/live` document records a COMPLETED game.

    The terminal test the cache readers need. A final payload can never go
    stale, so it may be reused forever; anything else is a snapshot of a
    moment and stops being true the instant the game moves on.
    """
    game_data = payload.get("gameData") if isinstance(payload, dict) else None
    status = game_data.get("status") if isinstance(game_data, dict) else None
    if not isinstance(status, dict):
        return False
    return mlb_status_is_final(status.get("abstractGameState"), status.get("detailedState"))


def mlb_feed_live_is_refreshable(
    selected_date: Any,
    today_iso: Any,
    *,
    in_request_context: bool,
) -> bool:
    """May a `feed/live` payload for `selected_date` be re-fetched from StatsAPI?

    TODAY, ALWAYS -- that is what both readers already did.

    YESTERDAY, OFF THE REQUEST PATH -- and this clause is the whole point.
    The slate date rolls at MIDNIGHT CENTRAL while west-coast games are still
    being played, so a game that ends after the roll can only ever be recorded
    by a build for YESTERDAY's slate. Gating on `== today` refuses exactly
    those games, permanently: a past date's artifact is not rebuilt later, so
    whatever that one post-roll build saw is what the date keeps forever.

    Measured 2026-09-03 (`lane mlb-feed-live-terminal-refresh`): ATH @ SEA
    went final 05:05Z and STL @ LAD 05:09Z, both AFTER the 05:00Z Central
    roll. The board artifact was built at 05:33:14Z -- 24 and 28 minutes later
    -- and published both as unfinished, so `live_gameline_score` scored 7 of
    a 9-game slate that had 9 finals.

    NOTHING OLDER, ever. Two days is the whole window in which a cached
    non-final payload can still be resolved by a live endpoint; past that it
    is history and belongs to the archive, not to StatsAPI.

    NEVER INSIDE A WEB REQUEST. `_mlb_feed_live_payload` runs on the request
    path, where the cache file matches no `HOT_ARTIFACT_PATTERNS` and so
    misses every time -- each miss an HTTPS call. That is the measured cause
    of `/healthz` missing Render's 5s timeout and gunicorn being SIGTERM'd
    three times in five minutes. Widening the window there would buy a
    correctness fix with an outage, so the caller passes
    `has_request_context()` and the extra day exists only for workers.

    NOT `_render_web_dyno()` -- but not for the reason first written here.
    That helper is CORRECT: `SYNDICATE_WEB_DYNO` is `true` on web and `false`
    on BOTH workers, live and in `render.yaml` alike (re-read 2026-09-04 WITH
    PAGINATION; the first read was one 100-key page of refresh-worker's 153
    and reported a drift that does not exist). Independently confirmed from
    refresh-worker's own logs: `[mlb_cards] FEED_LIVE_PRUNE`, which sits
    behind `not _render_web_dyno()`, emits there every build.

    `has_request_context()` is preferred on the merits instead. The
    constraint is *"do not add network to a REQUEST path"*, and that is what
    this asks; service identity is a proxy for it. `_mlb_feed_live_payload`
    is called from both the web request path and worker code, so the precise
    question is which of those two is calling right now -- not which service
    the process belongs to.
    """
    selected = str(selected_date or "").strip()
    today = str(today_iso or "").strip()
    if not selected or not today:
        return False
    if selected == today:
        return True
    if in_request_context:
        return False
    from datetime import date, timedelta

    try:
        return date.fromisoformat(selected) == date.fromisoformat(today) - timedelta(days=1)
    except ValueError:
        return False
