"""Read-only admin view of the odds tracker's steam record: `GET /api/ops/steam/events`.

WHY A SEPARATE BLUEPRINT. `ops.py` belongs to another lane. This route needs only
that blueprint's admin gate, so it imports `_require_admin_token` instead of
editing the file: same `/api/ops/` prefix, same token, same 401/503 answers.

WHY THE ROUTE EXISTS. `odds_refresh_tracking._record_steam_events` writes through
`write_json_file`, which on the keyvalue backend never touches disk. So
`/api/ops/artifacts/export` answered count 0 for `reports/steam/*` on 2026-09-15
while the board carried steam cards. The writer runs inside
`refresh_odds_sources.py` child processes whose output never reaches Render's
logs. Each event's previous and current price exist nowhere else. Lane
`legacy-steam-crossing-delta` needs them to count the steam flags that come only
from a ±100 crossing, before and after its fix.
"""

from __future__ import annotations

import json
import re
from typing import Any

from flask import Blueprint
from flask import jsonify
from flask import request

from syndicate.blueprints.ops import _require_admin_token


ops_steam_bp = Blueprint("ops_steam", __name__)
ops_steam_bp.before_request(_require_admin_token)

_SPORT_SLUG = re.compile(r"[a-z0-9_]{2,32}")
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
# The writer keeps a bounded window per sport per day, so a response is kilobytes
# in practice. This is only a guard.
_RESPONSE_MAX_BYTES = 2_000_000


@ops_steam_bp.get("/api/ops/steam/events")
def api_ops_steam_events() -> Any:
    sport = str(request.args.get("sport") or "").strip().lower()
    date = str(request.args.get("date") or "").strip()
    if not _SPORT_SLUG.fullmatch(sport) or not _ISO_DATE.fullmatch(date):
        return jsonify({"ok": False, "error": "sport (a slug) and date (YYYY-MM-DD) are required."}), 400

    # Imported at call time: the store's reader is resolved per request (tests
    # substitute it), and the path comes from the WRITER's own helper, so the two
    # cannot drift onto different keys.
    from syndicate.features.shared.odds_refresh_tracking import steam_events_path_for_sport
    from syndicate.features.shared.refresh_state_store import read_json_file

    payload = read_json_file(steam_events_path_for_sport(sport, date))
    events = payload.get("events") if isinstance(payload, dict) else None
    if not isinstance(events, list):
        return jsonify({"ok": True, "sport": sport, "date": date, "count": 0, "truncated": False, "events": []})

    events = [event for event in events if isinstance(event, dict)]
    kept: list[dict[str, Any]] = []
    size = 0
    for event in reversed(events):  # newest first, so a cap keeps the newest
        size += len(json.dumps(event, default=str))
        if size > _RESPONSE_MAX_BYTES:
            break
        kept.append(event)
    kept.reverse()
    return jsonify(
        {
            "ok": True,
            "sport": sport,
            "date": date,
            "count": len(kept),
            "truncated": len(kept) < len(events),
            "events": kept,
        }
    )
