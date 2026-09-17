# -*- coding: utf-8 -*-
"""A per-tick history of the live projection, kept INSIDE the live_state artifact.

WHY THIS EXISTS. `live_state_<date>.json` carries only the matches IN PLAY at the tick that wrote it, so a
match's projections vanish from it minutes after full time -- measured 2026-09-17 22:01:52Z: la_liga's file
for a date with two completed matches had `games: []` and only `match_box` finals, about 45 minutes after
the last whistle. Any forward grade of a LIVE number (H32: published corners vs the sim's kept corners) has
to capture snapshots while matches are in play, which made the evidence depend on an external scheduler
polling every 15 minutes. This moves the capture to where the code already runs: each tick appends its own
compact row and carries every earlier row forward, so a puller only has to arrive before the family's 8-day
retention instead of within the hour.

CARRIED INSIDE live_state, NOT IN A NEW FILE, for the reason `match_box` gives in the same payload:
`soccer_source/*/api/live_state/live_state_*.json` is already in `HOT_ARTIFACT_PATTERNS`, and a new path
would need an allowlist entry in `artifact_publisher.py` -- claimed by four other open lanes at this writing
-- while an unallowlisted artifact cannot reach web at all. A separate `tracking/live_projections/` family
is the better long-term shape and needs those lanes' agreement plus a retention rule; it is written up in
`.syndicate/log/2026-09-17.md` rather than half-built here.

WHAT A ROW IS. Both corners arms (published and the sim's kept value), the audit's state, the clock, corners
so far, the score, and the goals arm -- enough for H32 to grade from the artifact alone, with no replay and
no ratings question. Nothing here recomputes anything: it copies fields that the tick already produced.

CAP. `MAX_ROWS_PER_MATCH` rows per match, oldest dropped. At the live loop's ~60 s cadence that is four
hours, which covers a 90-minute match and its stoppage several times over; the cap exists so a stuck poller
cannot grow one artifact without bound (`#241`: worker periodic work is never free).
"""
from __future__ import annotations

from typing import Any, Mapping

HISTORY_KEY = "projection_history"
MAX_ROWS_PER_MATCH = 240

_GAME_FIELDS = ("status_display_clock", "half", "clock_remaining", "score_home", "score_away",
                "home_corners_so_far", "away_corners_so_far",
                # SHOTS AND ON-TARGET, added 2026-09-17 at lane `soccer-shot-on-target-definition`'s request
                # (session a1e40980). Its production evidence existed ONLY while the match was in play: at
                # full time the served game page drops the live box entirely (`rows: []`, measured 21:28:49Z),
                # so the counts became unreadable within the hour -- the same disappearance this block exists
                # to stop. Per-tick rows turn that class of verification from "be watching at the right
                # minute" into "read the artifact tomorrow".
                #
                # `*_shots_on_target_so_far` IS A COMMENTARY-DERIVED LOWER BOUND ON ESPN'S OWN FIGURE, not
                # ESPN's stat: measured per team over 48 team-matches, exact on 39, short on 9, never over,
                # 0.25 per team per match (that lane, 2026-09-17). Anyone reading this column later must not
                # treat it as the box score's number.
                "home_shots_so_far", "away_shots_so_far",
                "home_shots_on_target_so_far", "away_shots_on_target_so_far")
_PROJECTION_FIELDS = ("corners_basis", "projected_total_corners", "projected_home_corners",
                      "projected_away_corners", "sim_projected_total_corners",
                      "sim_projected_home_corners", "sim_projected_away_corners", "projected_final_total")


def history_row(game: Mapping[str, Any], generated_at: str) -> dict[str, Any]:
    """One tick's compact record for one match. Copies fields; computes nothing."""
    projection = game.get("projection") or {}
    audit = game.get("live_corners") or {}
    row: dict[str, Any] = {"generated_at": generated_at}
    row.update({key: game.get(key) for key in _GAME_FIELDS})
    row.update({key: projection.get(key) for key in _PROJECTION_FIELDS})
    row["live_corners_state"] = audit.get("state")
    row["share_remaining"] = audit.get("share_remaining")
    row["pregame_total"] = audit.get("pregame_total")
    return row


def merge_history(previous: Any, games: Mapping[str, Any], generated_at: str,
                  *, max_rows: int = MAX_ROWS_PER_MATCH) -> dict[str, list[dict[str, Any]]]:
    """Prior rows (including for matches that have since finished) plus this tick's, capped per match.

    A match that has left `games` KEEPS its rows: carrying them forward is the entire point, because that
    is the evidence the old artifact threw away. Re-running the same tick does not duplicate a row: a row
    whose `generated_at` matches the newest stored one for that match is skipped.
    """
    merged: dict[str, list[dict[str, Any]]] = {}
    if isinstance(previous, Mapping):
        for match_id, rows in previous.items():
            if isinstance(rows, list):
                merged[str(match_id)] = [r for r in rows if isinstance(r, Mapping)][-max_rows:]
    for match_id, game in (games or {}).items():
        if not isinstance(game, Mapping):
            continue
        rows = merged.setdefault(str(match_id), [])
        if rows and str(rows[-1].get("generated_at") or "") == str(generated_at):
            continue
        rows.append(history_row(game, generated_at))
        if len(rows) > max_rows:
            del rows[: len(rows) - max_rows]
    return merged


def history_from_payload(payload: Any) -> Any:
    """The stored history in a previously written live_state payload, or None."""
    if isinstance(payload, Mapping):
        stored = payload.get(HISTORY_KEY)
        if isinstance(stored, Mapping):
            return stored
    return None
