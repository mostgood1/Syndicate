"""When a pregame projection may NOT be priced against the market (`#340`).

ONE RULE, ONE PLACE. This existed in `prop_projections.py` and was copied into
`soccer_projections.py`, and WNBA never got it -- so on 2026-08-10 a live WNBA
game served **128 of 128 projected rows with an `edge_vs_line`**, computed from a
pregame mean against a market that had already re-priced on the score, while MLB
suppressed all 862 of its live rows for exactly that reason. Two sports, opposite
answers to the same question, on the same board.

THE MEASUREMENT BEHIND THE RULE, carried from `prop_projections.py` so it does
not get lost again: the sim's payloads are generated before first pitch. Once a
game starts the market re-prices on the actual state and the model does not, so
the difference is not an edge -- it is the score. Found 2026-07-12: an event with
commence 16:07 carried betmgm quotes at 17:35 (away -500) while the sim still
said 0.495, producing a **+23-point "edge" on a coin-flip game**. Game-market
edges spread **-55 to +54** as a result, on moneylines, where books are sharpest.

THE PROJECTION IS STILL SHOWN. A researcher comparing a pregame model against a
live line is a legitimate thing to want. What is withheld is the EDGE NUMBER,
because that number would be meaningless -- and, critically, because it RANKS: an
unsuppressed live edge does not merely display wrong, it sorts to the top of a
board built to surface the biggest edges.

This is deliberately a policy module with no imports. Every sport's projection
attach can depend on it without depending on each other.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# `final`/`completed` are included with the live states on purpose. A finished
# game is not "safe again" -- its market is settled or pulled, and an edge
# against it is worse than a live one, not better.
LIVE_OR_DONE_STATES = frozenset({"live", "in_progress", "final", "completed"})


def game_state_of(row: Mapping[str, Any]) -> str:
    """The row's game state, normalised. Empty string when unknown."""
    game = row.get("game")
    if not isinstance(game, Mapping):
        return ""
    return str(game.get("state") or "").strip().lower()


def live_edge_unavailable_reason(row: Mapping[str, Any]) -> str | None:
    """Why this row must not carry an edge, or None when an edge is allowed.

    UNKNOWN STATE ALLOWS THE EDGE, deliberately. A row whose game state cannot be
    resolved is overwhelmingly a pregame row on a board whose game-state join has
    a gap, and suppressing those would blank the edge column on exactly the days
    the join degrades -- turning an enrichment gap into a silent loss of the
    board's whole purpose. The failure this guards against is a LIVE game
    ranking, and a live game is something the board positively knows.
    """
    state = game_state_of(row)
    if state in LIVE_OR_DONE_STATES:
        return f"game is {state}: a pregame projection cannot be priced against a live market"
    return None
