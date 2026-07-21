"""Print whether any game is currently live for a sport/date, as JSON on stdout.

Isolated in its own process (invoked via subprocess by
syndicate/features/shared/live_refresh_loop.py) so a network hiccup or
malformed response can't take down the shared live-refresh loop every
sport's adaptive phase decision depends on. Mirrors
fetch_mlb_live_game_pks_for_date.py's pattern and reasoning, using ESPN's
public unauthenticated scoreboard API (already used elsewhere in this repo,
e.g. syndicate/features/wnba/cards.py's _public_scoreboard_live_state_payload)
as the independent, authoritative signal for WNBA/NBA/NHL, decoupled from
each sport's own locally-written live-state artifact whose generation
cadence/timing can lag actual game state.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

_ESPN_SPORT_LEAGUE = {
    "wnba": ("basketball", "wnba"),
    "nba": ("basketball", "nba"),
    "nhl": ("hockey", "nhl"),
    # Soccer leagues, one entry per league (mirrors
    # syndicate/features/soccer/ingestion/espn_lineups.LEAGUE_ESPN_SLUGS --
    # not imported directly so this script stays a standalone, dependency-free
    # subprocess target per its own module docstring above).
    "epl": ("soccer", "eng.1"),
    "la_liga": ("soccer", "esp.1"),
    "bundesliga": ("soccer", "ger.1"),
    "serie_a": ("soccer", "ita.1"),
    "ligue_1": ("soccer", "fra.1"),
    "mls": ("soccer", "usa.1"),
    "eredivisie": ("soccer", "ned.1"),
    "primeira_liga": ("soccer", "por.1"),
    "championship": ("soccer", "eng.2"),
    "belgian_pro_league": ("soccer", "bel.1"),
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sport", required=True, choices=sorted(_ESPN_SPORT_LEAGUE.keys()))
    parser.add_argument("--date", required=True)
    args = parser.parse_args()

    sport_slug, league_slug = _ESPN_SPORT_LEAGUE[str(args.sport)]
    try:
        parsed = datetime.strptime(str(args.date).strip(), "%Y-%m-%d")
    except ValueError:
        print(json.dumps({"error": f"invalid date: {args.date}"}), file=sys.stderr)
        return 1
    compact_date = parsed.strftime("%Y%m%d")

    url = (
        f"https://site.api.espn.com/apis/site/v2/sports/{sport_slug}/{league_slug}/scoreboard"
        f"?dates={urllib.parse.quote(compact_date)}"
    )
    request_obj = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json,text/plain,*/*"},
    )
    try:
        with urllib.request.urlopen(request_obj, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}), file=sys.stderr)
        return 1

    events = payload.get("events") if isinstance(payload, dict) else None
    live_event_ids: list[str] = []
    if isinstance(events, list):
        for event in events:
            if not isinstance(event, dict):
                continue
            status = event.get("status") if isinstance(event.get("status"), dict) else {}
            status_type = status.get("type") if isinstance(status.get("type"), dict) else {}
            in_progress = str(status_type.get("state") or "").strip().lower() == "in"
            if in_progress:
                event_id = str(event.get("id") or "").strip()
                if event_id:
                    live_event_ids.append(event_id)

    print(json.dumps({"live_event_ids": live_event_ids}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
