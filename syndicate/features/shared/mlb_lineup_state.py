"""Posted-lineup state for an MLB slate — the input the resim trigger never had.

WHY THIS EXISTS (see docs/ai_context/audit_sim_invalidation_rules.md):

`_mlb_sim_input_fingerprint_by_game` hashes four inputs. Three of them —
injuries, odds, overrides — are refreshed independently of the sim. The fourth,
`lineups_last_known_by_team.json`, is written by `daily_update.py` **itself**,
i.e. by the very run the fingerprint is supposed to trigger:

    sim runs -> lineups rewritten -> fingerprint matches -> no resim
             -> lineups never refresh -> no resim

So a lineup change was only ever detected when something *else* (odds churn, an
injury, the tip-off window) already caused a sim that happened to rewrite the
lineup file. Lineup posting was picked up incidentally, never deliberately —
and the incidental path is weak, because `_mlb_sim_odds_fingerprint_slice`
deliberately damps odds churn (#48) to stop it firing on every refresh.

`_fetch_mlb_injuries` is the precedent: it exists because a scratch "not yet
reflected in the posted lineup artifact went undetected between sim runs". The
same fix was never applied to the lineup artifact itself. This is that fix.

It also supplies the thing the audit called the enabler gap: **there was no
concept of a FINAL lineup anywhere in the repo.** Nothing distinguished
projected from posted, so "have final lineups dropped for this game?" could not
be asked. StatsAPI answers it directly — `lineups.homePlayers` carries 9 players
once a lineup is posted and is empty before (verified live 2026-08-08: 15/15
games posted for 08-07, 0/15 for 08-08).

DELIBERATELY NOT A SUBPROCESS, unlike `fetch_mlb_injuries.py`. That one is
isolated because it imports the vendored MLB client and a bug there must not
take down the shared loop. This talks to StatsAPI over urllib with no vendored
import at all, so the isolation buys nothing and would cost a process spawn on
every check — on the worker whose memory ceiling is the binding constraint.

DELIBERATELY A SEPARATE ARTIFACT, not a rewrite of
`lineups_last_known_by_team.json`. That file is owned by the vendored daily
update; writing to it from here would race a pipeline we do not control. This
mirrors the injuries artifact instead: its own file, added as another
fingerprint input.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

STATSAPI_SCHEDULE = "https://statsapi.mlb.com/api/v1/schedule"

# One call covers the whole slate. Per-game feed endpoints would also work and
# would cost ~15 requests instead of 1.
_HYDRATE = "lineups,probablePitcher"


def _ids(players: Any) -> list[int]:
    out: list[int] = []
    for player in players or []:
        if isinstance(player, dict) and player.get("id") is not None:
            try:
                out.append(int(player["id"]))
            except (TypeError, ValueError):
                continue
    return out


def fetch_mlb_lineup_state(date_str: str, *, timeout: float = 20.0) -> dict[str, Any]:
    """Posted-lineup + probable-pitcher state for every game on *date_str*.

    Raises on transport failure — the caller decides what an unresolvable
    schedule means. Returning an empty payload here would be indistinguishable
    from "no games", which is the failure mode this whole audit kept tripping
    over.
    """
    url = (
        f"{STATSAPI_SCHEDULE}?sportId=1"
        f"&date={urllib.parse.quote(str(date_str).strip())}"
        f"&hydrate={urllib.parse.quote(_HYDRATE)}"
    )
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))

    games: dict[str, Any] = {}
    for date_block in (payload.get("dates") or []):
        for game in (date_block.get("games") or []):
            if not isinstance(game, dict):
                continue
            game_pk = str(game.get("gamePk") or "").strip()
            if not game_pk:
                continue
            lineups = game.get("lineups") or {}
            home_order = _ids(lineups.get("homePlayers"))
            away_order = _ids(lineups.get("awayPlayers"))
            teams = game.get("teams") or {}

            def _probable(side: str) -> int | None:
                block = (teams.get(side) or {}).get("probablePitcher") or {}
                try:
                    return int(block["id"]) if block.get("id") is not None else None
                except (TypeError, ValueError):
                    return None

            games[game_pk] = {
                "status": str((game.get("status") or {}).get("detailedState") or "").strip(),
                # BOTH sides required. A half-posted slate is not a posted
                # lineup, and treating it as one would retire the resim that
                # should fire when the second team posts.
                "lineups_posted": bool(home_order and away_order),
                "home_batting_order": home_order,
                "away_batting_order": away_order,
                "home_probable_pitcher": _probable("home"),
                "away_probable_pitcher": _probable("away"),
            }

    return {
        "date": str(date_str),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "games": games,
        "games_total": len(games),
        "games_with_posted_lineups": sum(1 for g in games.values() if g.get("lineups_posted")),
    }


def lineup_slice_for_game(payload: Any, game_pk: str) -> dict[str, Any]:
    """One game's slice, for hashing into the sim-input fingerprint.

    Returns a stable empty shape rather than None when the game is absent, so a
    game missing from the payload hashes consistently instead of making the
    fingerprint jitter between "absent" and "empty".
    """
    games = payload.get("games") if isinstance(payload, dict) else None
    entry = games.get(str(game_pk)) if isinstance(games, dict) else None
    if not isinstance(entry, dict):
        return {
            "lineups_posted": False,
            "home_batting_order": [],
            "away_batting_order": [],
            "home_probable_pitcher": None,
            "away_probable_pitcher": None,
        }
    # `status` is deliberately EXCLUDED from the hash: it churns through
    # Scheduled -> Pre-Game -> Warmup -> In Progress on its own schedule and
    # would fire a resim on every transition, which is the over-simming this
    # work just finished removing. Only the lineup and the starter matter here.
    return {
        "lineups_posted": bool(entry.get("lineups_posted")),
        "home_batting_order": list(entry.get("home_batting_order") or []),
        "away_batting_order": list(entry.get("away_batting_order") or []),
        "home_probable_pitcher": entry.get("home_probable_pitcher"),
        "away_probable_pitcher": entry.get("away_probable_pitcher"),
    }
