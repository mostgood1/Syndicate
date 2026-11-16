"""Soccer's live player-exit gate (lane live-player-exit-gate, user 2026-11-16).

Called by `scripts/poll_soccer_live_state.poll_league` on each in-play match, with the ESPN summary the poller
already fetched (no extra GET). The detector is `live_player_status.exits_from_espn_summary("soccer", ...)`:

  - ``red_card`` (keyEvent type exactly "Red Card"), KEY. The live sim MODELS it: `live_lens.apply_red_card_penalty`
    lowers the carded team's ratings for the rest of the match, and the projection says so
    (`home_red_card_applied` / `away_red_card_applied`). A red card the projection applied is MODELLED and the
    match stays PRICED -- the rule the user set for an engine-modelled exit (11-16, "No, keep pricing").
  - ``keeper_change`` (the starting keeper subbed off), KEY. The sim has no keeper in it, so it is NOT modelled:
    the match is refused (`liveRefusal = key_player_out`), `soccer_live_gameline_source.soccer_live_gameline_index`
    skips it, and the in-play entry hold fails on it.

An out player's live PROPS: under the ``on_pitch`` lineup basis the prop sim already gives anyone subbed off or
sent off a remainder of 0 (`live_lens._live_lineup`), an exact price, so those rows stay. Under the ``squad``
basis (no on-pitch read) the out player still shares the remainder, so the row is marked
``notPricedReason = player_out`` and `soccer_live_prop_index` skips it.

`playersOut` is published on every in-play match the summary could be read for; a match whose summary was
unreadable gets none, and the hold answers `unknown` for it (the pre-gate behaviour).
"""

from __future__ import annotations

from typing import Any, Mapping

from syndicate.features.shared import live_player_status as lps

REASON_KEY_PLAYER_OUT = lps.REASON_KEY_PLAYER_OUT
NOT_PRICED_PLAYER_OUT = "player_out"


def _side_by_abbrev(summary: Mapping[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for comp in lps._competition(summary).get("competitors") or []:
        abbr = str(((comp.get("team") or {}).get("abbreviation")) or "")
        side = str(comp.get("homeAway") or "")
        if abbr and side in ("home", "away"):
            out[abbr] = side
    return out


def new_tally() -> dict[str, Any]:
    return {"enabled": lps.gate_enabled(), "read": 0, "unreadable": 0, "players_out": 0,
            "key_players_out": 0, "modelled": 0, "refused_games": 0, "props_refused": 0}


def apply_player_exits(game: dict[str, Any], summary: Any, tally: dict[str, Any] | None = None) -> dict[str, Any]:
    """Publish `playersOut` on one in-play match; refuse it when a key exit is not modelled. Never raises."""
    tally = tally if tally is not None else new_tally()
    if not tally.get("enabled"):
        return tally
    if not isinstance(summary, Mapping):
        tally["unreadable"] += 1
        return tally
    try:
        status = lps.exits_from_espn_summary("soccer", summary, game_id=str(game.get("event_id") or "") or None)
    except Exception:  # noqa: BLE001 -- the gate never costs the tick a match
        tally["unreadable"] += 1
        return tally
    if not status.in_progress:
        return tally
    tally["read"] += 1
    projection = game.get("projection") if isinstance(game.get("projection"), Mapping) else None
    sides = _side_by_abbrev(summary)
    out: list[dict[str, Any]] = []
    unmodelled: list[str] = []
    for p in status.players_out:
        row = dict(p.__dict__)
        side = sides.get(p.team)
        row["modelled"] = bool(p.reason == "red_card" and projection is not None and side
                               and projection.get(f"{side}_red_card_applied"))
        out.append(row)
        if p.key:
            tally["key_players_out"] += 1
            if row["modelled"]:
                tally["modelled"] += 1
            else:
                unmodelled.append(f"{p.team}:{p.player}:{p.reason}")
    tally["players_out"] += len(out)
    game["playersOut"] = out
    if unmodelled:
        game["liveRefusal"] = REASON_KEY_PLAYER_OUT
        game["liveRefusalDetail"] = ",".join(unmodelled)
        tally["refused_games"] += 1
        print(f"[soccer_live_state] KEY_PLAYER_OUT_REFUSED league={game.get('league')} event={game.get('event_id')} "
              f"{game.get('away_team')} @ {game.get('home_team')} players={unmodelled}", flush=True)
    tally["props_refused"] += refuse_out_player_props(game, status)
    return tally


def refuse_out_player_props(game: dict[str, Any], status: lps.GameExitStatus) -> int:
    """Mark an out player's prop rows unpriced unless the prop sim already took him off (``on_pitch`` basis)."""
    refused = 0
    for row in game.get("live_player_props") or []:
        if not isinstance(row, dict) or row.get("lineup_basis") == "on_pitch":
            continue
        if status.player_is_out(str(row.get("player_name") or "")) is not None:
            row["notPricedReason"] = NOT_PRICED_PLAYER_OUT
            refused += 1
    return refused


def log_tick(tally: Mapping[str, Any]) -> None:
    if tally.get("read") or tally.get("unreadable"):
        print("[soccer_live_state] PLAYER_EXIT_TICK " + " ".join(f"{k}={v}" for k, v in tally.items()), flush=True)
