"""ONE resolution of an odds-feed NBA player name to the ENGINE's spelling, stamped on the row
`[2026-11-10, lane nba-prop-engine-name-join]`.

WHY. A book prints "Herb Jones"; the engine (cards_sim_detail, player_ids.csv, the box scores) prints
"Herbert Jones". Every name-keyed join on an NBA prop row used its OWN key on the book's spelling, and none
of those keys knows the engine's aliases:

  * pregame sim projection  `nba_projections._match_player`        `_norm_name` (keeps "jr", no nicknames)
  * headshot / player side  `home._basketball_resolve_player_id`   `_mlb_name_key` (lowercase only)
  * recent form, matchup    `prop_evidence` `names_match`           suffix-loose, no nicknames
  * vs-position sentence    `basketball_vs_position_text`           same

So a split player lost the sim projection, the ladder, the model edge, the face, the side and the recent
form, while the LIVE join (`live_projection_join._resolve_player`, `e2558013c`) already resolved him.
Measured on the fleet, 11-04..11-09 book grids (fleet code 564f8dbde): 15 player-slates and 610 prop rows
missed the sim only by spelling, every one resolving uniquely under the engine key, 0 ambiguous:
C.J./CJ McCollum, Carlton/Bub Carrington, Herb/Herbert Jones, Paul Reed Jr/Paul Reed, R.J./RJ Barrett,
A.J./AJ Green, Derrick Jones/Derrick Jones Jr., Ron/Ronald Holland II.

THE RULE, the live join's, so the two can never disagree about who a player is:
  1. the row's own name, exact (`prop_projections._norm_name`), always first: a row that joins today is
     never touched, and nothing is stamped on it;
  2. only when NO engine player carries that exact key, the engine's canonical key
     (`live_projection_join._canonical_player`: suffixes dropped, accents folded, the engine's nickname
     aliases applied), and only when it names EXACTLY ONE engine player;
  3. two engine players under one canonical key is a real ambiguity ("Gary Payton" vs "Gary Payton II"),
     so neither is chosen and the miss stands.

`player_name` itself is NOT rewritten. It is the bet's identity (`layer2_ledger.pick_id`), the venue and
odds-history join key and the board's display name. The resolution rides beside it in
`ENGINE_NAME_FIELD`, present only on a row the rule above resolved, and readers that join to ENGINE data
read `engine_player_name(row)`.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

#: Stamped on a row ONLY when its exact name missed and the engine key named exactly one engine player.
ENGINE_NAME_FIELD = "engine_player_name"

#: Outcomes of `resolve_engine_name`, counted by the stamping caller.
EXACT = "exact"
ALIAS = "alias"
AMBIGUOUS = "ambiguous"
ABSENT = "absent"
NO_NAME = "no_name"


def exact_key(value: Any) -> str:
    """The exact join key every NBA prop join already uses (accent-folded, lowercase, punctuation-free)."""
    from syndicate.features.shared.prop_projections import _norm_name

    return _norm_name(value)


def engine_key(value: Any) -> str:
    """The basketball engine's canonical player key. ONE definition, the live join's, imported not copied."""
    from syndicate.features.shared.live_projection_join import _canonical_player

    return _canonical_player(value)


def resolve_engine_name(name: Any, engine_names: Iterable[str]) -> tuple[str | None, str]:
    """`(engine name to stamp or None, outcome)` for one odds-feed name against a set of engine names.

    A name is returned ONLY for `ALIAS`: an `EXACT` row already joins under its own name, so returning
    nothing there is what keeps every currently-joining row byte-identical.
    """
    if not exact_key(name):
        return None, NO_NAME
    names = [str(n) for n in engine_names if str(n or "").strip()]
    wanted = exact_key(name)
    if any(exact_key(n) == wanted for n in names):
        return None, EXACT
    canonical = engine_key(name)
    if not canonical:
        return None, ABSENT
    by_exact: dict[str, str] = {}
    for candidate in names:
        if engine_key(candidate) == canonical:
            by_exact.setdefault(exact_key(candidate), candidate)
    if len(by_exact) == 1:
        return next(iter(by_exact.values())), ALIAS
    if len(by_exact) > 1:
        return None, AMBIGUOUS
    return None, ABSENT


def engine_player_name(row: Mapping[str, Any] | None) -> str:
    """The name to join ENGINE data on: the stamped engine spelling if the row has one, else its own."""
    if not isinstance(row, Mapping):
        return ""
    stamped = str(row.get(ENGINE_NAME_FIELD) or "").strip()
    return stamped or str(row.get("player_name") or "").strip()


def join_name_candidates(row: Mapping[str, Any] | None) -> tuple[str, ...]:
    """The names to try, in order, against a name-keyed file whose spelling is NOT always the engine's: the
    engine spelling first, then the row's own.

    `player_ids.csv` (face and side) holds most players in the engine's spelling, but not all. Measured on the
    fleet 2026-11-11 over 10 split players: 9 resolve a player id only under the engine spelling (Derrick Jones
    Jr., AJ Green, Herbert Jones...), and Bobby Portis only under the book's ("BOBBY PORTIS"). Reading the
    engine spelling alone cost his rows their face once `engine_player_name` was stamped (todo #775).
    """
    if not isinstance(row, Mapping):
        return ()
    names: list[str] = []
    for name in (engine_player_name(row), str(row.get("player_name") or "").strip()):
        if name and name not in names:
            names.append(name)
    return tuple(names)


__all__ = [
    "ABSENT",
    "ALIAS",
    "AMBIGUOUS",
    "ENGINE_NAME_FIELD",
    "EXACT",
    "NO_NAME",
    "engine_key",
    "engine_player_name",
    "exact_key",
    "join_name_candidates",
    "resolve_engine_name",
]
