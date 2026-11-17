"""MLB's live player-exit gate (lane live-player-exit-gate, user 2026-11-16).

Called once per game per live-lens tick by `live_lens_port.app_slice._live_lens_payload`, on the statsapi
``feed/live`` that tick already loaded (no extra GET). The detector is
`live_player_status.exits_from_mlb_feed`: a STARTER who left for injury or was ejected.

NOT MODELLED, so the game is refused. `app_slice._live_mc_projection` builds the live Monte Carlo from the
PREGAME roster snapshot (`sim_context["roster_snapshot"]`): the departed batter keeps his lineup slot in every
sim. On the mound, only the FIELDING team's current pitcher is passed (`LiveSituation.<side>_pitcher_id`), and
the other team falls back to its starter (`sim_engine/live_mc.estimate_live` -> `_default_pitcher_id`), so an
injured starter is back on the mound in the sims whenever his team is batting. Both are the user's 11-16 rule
for an exit the engine does not model: refuse the game's live lines.

A ROUTINE substitution (pinch-hitter, defensive replacement, pitching change) is not an exit and changes
nothing here: that is the behaviour before this module.

PROPS: an out batter's or pitcher's own props are already withheld upstream of the board
(`cards._live_hitter_removed` / `_live_pitcher_prop_row_actionable`), and the producer also drops his live
prop rows here, so his props never price off a sim that still has him batting.
"""

from __future__ import annotations

from typing import Any, Mapping

from syndicate.features.shared import live_player_status as lps

REASON_KEY_PLAYER_OUT = lps.REASON_KEY_PLAYER_OUT


def new_tally() -> dict[str, Any]:
    return {"enabled": lps.gate_enabled(), "read": 0, "unreadable": 0, "players_out": 0,
            "key_players_out": 0, "refused_games": 0, "props_dropped": 0}


def read_exits(feed: Any, tally: dict[str, Any]) -> lps.GameExitStatus | None:
    """The game's exit status, or None when the gate is off / the feed unreadable / the game not in play."""
    if not tally.get("enabled"):
        return None
    if not isinstance(feed, Mapping):
        tally["unreadable"] += 1
        return None
    try:
        status = lps.exits_from_mlb_feed(feed)
    except Exception:  # noqa: BLE001 -- the gate never costs the tick a game
        tally["unreadable"] += 1
        return None
    if not status.in_progress:
        return None
    tally["read"] += 1
    return status


def players_out_rows(status: lps.GameExitStatus) -> list[dict[str, Any]]:
    """Published as the game's `playersOut`. MLB marks every exit unmodelled (see the module docstring)."""
    return [{**p.__dict__, "modelled": False} for p in status.players_out]


def refusal_detail(status: lps.GameExitStatus | None) -> str | None:
    refusal = lps.gameline_refusal(status)
    return ",".join(refusal["players"]) if refusal else None


def drop_out_player_props(rows: list[Any], status: lps.GameExitStatus | None, tally: dict[str, Any]) -> list[Any]:
    if status is None or not status.players_out:
        return rows
    kept: list[Any] = []
    for row in rows:
        name = str((row or {}).get("playerName") or (row or {}).get("player_name") or "") if isinstance(row, Mapping) else ""
        if name and status.player_is_out(name) is not None:
            tally["props_dropped"] += 1
            continue
        kept.append(row)
    return kept


def record(game_pk: Any, status: lps.GameExitStatus | None, tally: dict[str, Any]) -> str | None:
    """Count the game and log a refusal. Returns the refusal detail (None = priced)."""
    if status is None:
        return None
    tally["players_out"] += len(status.players_out)
    tally["key_players_out"] += len(status.key_players_out)
    detail = refusal_detail(status)
    if detail:
        tally["refused_games"] += 1
        print(f"[mlb_live_lens] KEY_PLAYER_OUT_REFUSED gamePk={game_pk} {status.away_team} @ {status.home_team} "
              f"players={detail}", flush=True)
    return detail


def log_tick(tally: Mapping[str, Any]) -> None:
    if tally.get("read") or tally.get("unreadable"):
        print("[mlb_live_lens] PLAYER_EXIT_TICK " + " ".join(f"{k}={v}" for k, v in tally.items()), flush=True)
