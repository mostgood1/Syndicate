"""Measure how many opportunity rows arrive without usable identity (#222).

WHY THIS EXISTS, AND WHY IT COMES BEFORE THE CONTRACT ITSELF
------------------------------------------------------------
Step 2 of `docs/ai_context/plan_one_opportunity_pipeline.md`, deliberately
sequenced ahead of step 1.

Three times on 2026-08-06 a change passed its tests and did nothing in
production, and each time the only way to find out was to query the live board
and replay it offline. Then a THREE-LINE change (#221, carrying `player_name`
through `_build_prop_dashboard_row`) moved `top_props` from 0 of 14 priced to 12
of 14 -- an enormous effect that had been invisible for as long as it existed,
because nothing counted it.

So: count first, fix second. A number that says *"mlb: 28 rows, 28 missing
market_key"* tells you where the next three-line change is. Without it, the
contract work in step 1 is guesswork about which producers are actually broken.

WHAT IT MEASURES
----------------
Per sport, per lane, the fields the join genuinely needs:
  - `entity_name`  -- a prop cannot be identified without it
  - `market_key`   -- the CANONICAL key ("batter_hits"), never the display
                      string ("Hits"); these are what fail to join
  - event identity -- `event_id`, `game_pk`, or a team pair

`complete` is the count that could be emitted as a valid opportunity today. It is
the number this whole plan is trying to move.

DESIGN NOTES
------------
Never raises: instrumentation that can break the thing it measures is worse than
none -- the same contract `record_oddsapi_quota` states for itself.

Counts are accumulated in-process and flushed to a report, so a lane that runs
many times per request does not write many times. The payload records
`service_role`, because `_finalize_home_prop_rows` runs on BOTH web and
refresh-worker and their disks are separate -- a count read without knowing which
service produced it is not interpretable ([[project-three-service-architecture]]).
"""

from __future__ import annotations

import os
import threading
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

_LOCK = threading.Lock()
_COUNTS: dict[tuple[str, str, str], dict[str, int]] = defaultdict(lambda: defaultdict(int))

_COUNTER_FIELDS = (
    "rows",
    "missing_entity_name",
    "missing_market_key",
    "missing_event_identity",
    "with_quote",
    "complete",
)

_ENTITY_KEYS = ("entity_name", "player_name", "player", "entity")
# Canonical keys only. `market` and `market_label` are display strings and are
# deliberately NOT consulted -- counting them would report the gap as closed
# while the join still fails, which is exactly the failure being measured.
_MARKET_KEY_KEYS = ("market_key", "prop", "prop_market_key", "stat")
_EVENT_KEYS = ("event_id", "game_pk", "gamePk", "game_id")


def _text(row: Mapping[str, Any], keys: Iterable[str]) -> str:
    for key in keys:
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return ""


def _has_event_identity(row: Mapping[str, Any]) -> bool:
    if _text(row, _EVENT_KEYS):
        return True
    home = _text(row, ("home_team", "home_label", "home"))
    away = _text(row, ("away_team", "away_label", "away"))
    return bool(home and away)


def record_rows(rows: Iterable[Mapping[str, Any]], *, sport: Any, lane: str, date_str: Any) -> None:
    """Count identity coverage for one lane's output. Never raises."""
    try:
        slug = str(sport or "").strip().lower() or "unknown"
        key = (slug, str(lane), str(date_str or "")[:10])
        with _LOCK:
            bucket = _COUNTS[key]
            # Every counter present from the first row, always. A defaultdict
            # omits keys that were never incremented, so a perfectly healthy
            # lane would serve `{"rows": 28}` with no `missing_market_key` at
            # all -- indistinguishable from "not measured" to anyone reading the
            # endpoint. Zero has to be visible for a zero to mean anything.
            for counter in _COUNTER_FIELDS:
                bucket.setdefault(counter, 0)
            for row in rows or ():
                if not isinstance(row, Mapping):
                    continue
                bucket["rows"] += 1
                has_entity = bool(_text(row, _ENTITY_KEYS))
                has_market_key = bool(_text(row, _MARKET_KEY_KEYS))
                has_event = _has_event_identity(row)
                if not has_entity:
                    bucket["missing_entity_name"] += 1
                if not has_market_key:
                    bucket["missing_market_key"] += 1
                if not has_event:
                    bucket["missing_event_identity"] += 1
                if row.get("quote"):
                    bucket["with_quote"] += 1
                # What could be emitted as a valid opportunity today. A prop
                # needs an entity; a game market does not, so entity is only
                # required when the row names a player at all -- otherwise every
                # moneyline would count as broken.
                if has_market_key and has_event and (has_entity or not _looks_like_prop(row)):
                    bucket["complete"] += 1
    except Exception:
        return


def _looks_like_prop(row: Mapping[str, Any]) -> bool:
    if _text(row, _ENTITY_KEYS):
        return True
    market = _text(row, ("market_key", "prop", "market", "market_label")).lower()
    return any(token in market for token in ("player", "batter", "pitcher", "prop"))


def snapshot() -> dict[str, Any]:
    with _LOCK:
        by_sport: dict[str, Any] = {}
        for (slug, lane, date_str), bucket in _COUNTS.items():
            by_sport.setdefault(slug, {}).setdefault(date_str, {})[lane] = dict(bucket)
    return {
        "schema": "opportunity_contract_metrics_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        # _finalize_home_prop_rows runs on BOTH web and refresh-worker, and their
        # disks are separate. A count without this is not interpretable.
        "service_role": os.environ.get("SYNDICATE_SERVICE_ROLE")
        or os.environ.get("RENDER_SERVICE_NAME")
        or "unknown",
        "by_sport": by_sport,
    }


def flush() -> dict[str, Any] | None:
    """Persist the current snapshot. Never raises."""
    payload = snapshot()
    try:
        from syndicate.features.shared.refresh_state_store import reports_root, write_json_file

        write_json_file(reports_root() / "opportunity_contract" / "latest.json", payload)
    except Exception:
        return payload
    return payload


def reset() -> None:
    with _LOCK:
        _COUNTS.clear()
