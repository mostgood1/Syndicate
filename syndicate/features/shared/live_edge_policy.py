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


def projection_is_live_aware(row: Mapping[str, Any]) -> bool:
    """True when this row's projection knows the current game state.

    Set by `live_projection_join` when the live re-sim's number is overlaid.
    Read here rather than inferred, because "the model is live" is a fact about
    the PROJECTION and not about the game -- the same live game carries both
    kinds of row while the join is partial.
    """
    projection = row.get("projection")
    if not isinstance(projection, Mapping):
        return False
    return bool(projection.get("live_aware"))


def live_edge_unavailable_reason(row: Mapping[str, Any]) -> str | None:
    """Why this row must not carry an edge, or None when an edge is allowed.

    THE PREDICATE IS THE PROJECTION'S BASIS, NOT THE GAME'S STATE. That
    distinction is the whole point: what makes a live edge meaningless is that
    the MODEL is pregame while the market has re-priced. A projection that
    itself knows the score -- MLB's live re-sim, joined by
    `live_projection_join` -- priced against a live market is not the failure
    this guards against; it is precisely the thing worth ranking, and refusing
    it would discard the only genuinely live signal on the board.

    Originally this keyed on game state alone. That was right while nothing
    joined a live model, and it silently became wrong the moment one did.

    FINAL/COMPLETED STILL REFUSE, even live-aware. A settled or pulled market
    has no price to beat; an edge against it is worse than a live one, not
    better, and no amount of model freshness rescues it.

    UNKNOWN STATE ALLOWS THE EDGE, deliberately. A row whose game state cannot be
    resolved is overwhelmingly a pregame row on a board whose game-state join has
    a gap, and suppressing those would blank the edge column on exactly the days
    the join degrades -- turning an enrichment gap into a silent loss of the
    board's whole purpose. The failure this guards against is a LIVE game
    ranking, and a live game is something the board positively knows.
    """
    state = game_state_of(row)
    if state not in LIVE_OR_DONE_STATES:
        return None
    if state in {"final", "completed"}:
        return f"game is {state}: the market is settled, so there is no price to beat"
    if projection_is_live_aware(row):
        return None
    return f"game is {state}: a pregame projection cannot be priced against a live market"
