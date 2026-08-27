"""Can every compact game card resolve its live-scoreboard chip?

WHY THIS EXISTS. Twice now the same defect has been found the same way -- a
person looking at the board. 2026-08-22, MLS compact cards showed full club
names; 2026-08-24, La Liga did. Both times the cause was a card that resolved
NO chip and fell through to printing `game.matchup` verbatim, and both times
nothing anywhere reported it. The board looked populated, every count was
healthy, and the only detector was a human noticing that some cards showed
tri-codes and others showed "Real Racing Club de Santander".

THIS MEASURES COVERAGE, IT DOES NOT REIMPLEMENT THE JOIN. `chipForGame`
(intelligence.html) runs in the BROWSER and is the authority. Mirroring its
fuzzy last-resort here would be a second implementation of one number, which
is exactly how two implementations drift apart -- the hazard that retired
`book_grid`. So this deliberately evaluates ONLY the deterministic keys:

    game id  ->  exact matchup text  ->  exact full names  ->  canonical key

and reports everything else as `needs_fallback` -- an honest "this card is
relying on string normalisation to find its chip", NOT a prediction that it
will fail. A card in that bucket may well join in the browser. The point is
that it is one spelling change away from not joining, and that is worth
seeing before a user does.

`no_chip_available` is the sharper number: the fixture has no chip at all in
the window, so no join of any kind can succeed and the card WILL print its
matchup verbatim.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

# Bounded so one bad slate cannot flood the log collector. The samples exist to
# NAME the club that needs an alias -- "Athletic Bilbao" is the whole finding --
# and eight is plenty for that; the counts carry the scale.
_MAX_SAMPLES = 8


def _text(value: Any) -> str:
    return str(value or "").strip()


def _lower(value: Any) -> str:
    return _text(value).lower()


def _chip_indexes(chips: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """The deterministic indexes, built exactly as `loadGameChips` builds them.

    Collisions are dropped from the canonical index for the same reason the
    browser drops them: two chips on one key would attach one game's score to
    another game's card, and a wrong chip is worse than no chip.
    """
    by_id: dict[str, Mapping[str, Any]] = {}
    by_matchup: dict[str, Mapping[str, Any]] = {}
    by_canonical: dict[str, Mapping[str, Any]] = {}
    canonical_collisions: set[str] = set()
    for chip in chips or ():
        if not isinstance(chip, Mapping):
            continue
        sport = _lower(chip.get("sport"))
        key = _text(chip.get("game_key"))
        if key:
            by_id[f"{sport}|{key}"] = chip
        matchup = _lower(chip.get("matchup"))
        if matchup:
            by_matchup[f"{sport}|{matchup}"] = chip
        away = chip.get("away") if isinstance(chip.get("away"), Mapping) else {}
        home = chip.get("home") if isinstance(chip.get("home"), Mapping) else {}
        away_name, home_name = _lower(away.get("name")), _lower(home.get("name"))
        if away_name and home_name:
            by_matchup[f"{sport}|{away_name} @ {home_name}"] = chip
        away_key, home_key = _lower(away.get("key")), _lower(home.get("key"))
        if away_key and home_key:
            canonical = f"{sport}|{away_key} @ {home_key}"
            if canonical in by_canonical:
                canonical_collisions.add(canonical)
            else:
                by_canonical[canonical] = chip
    for collision in canonical_collisions:
        by_canonical.pop(collision, None)
    return {
        "by_id": by_id,
        "by_matchup": by_matchup,
        "by_canonical": by_canonical,
        "canonical_collisions": len(canonical_collisions),
    }


def _card_sport(card: Mapping[str, Any]) -> str:
    return _lower(card.get("sport") or card.get("sport_slug"))


def _card_ids(card: Mapping[str, Any]) -> list[str]:
    return [_text(card.get(field)) for field in ("game_id", "gamePk", "event_id", "game_pk")]


def chip_join_coverage(
    cards: Sequence[Mapping[str, Any]],
    chips: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Per-sport chip resolution for a set of board cards.

    One entry per sport.

    NO PER-LEAGUE BREAKDOWN, deliberately, though soccer is the sport where
    this keeps going wrong and one broken league hiding behind nine healthy
    ones is the exact risk. A board CARD carries `sport`/`sport_slug` and no
    league at all (checked, 2026-08-24), so every row would land in an
    "unknown" bucket -- a breakdown that always says the same thing is noise
    wearing a diagnostic's clothes. `samples` names the fixtures instead, and a
    fixture name identifies its league to any reader. If cards ever carry a
    league, this is the place to add it back.
    """
    indexes = _chip_indexes(chips)
    by_id = indexes["by_id"]
    by_matchup = indexes["by_matchup"]
    by_canonical = indexes["by_canonical"]

    # A fixture with no chip in the window cannot join by ANY route. Tracked
    # separately from "needs_fallback" because the two have different owners:
    # this one is the chip window, that one is the alias map.
    chip_pairs: set[str] = set()
    for chip in chips or ():
        if not isinstance(chip, Mapping):
            continue
        sport = _lower(chip.get("sport"))
        away = chip.get("away") if isinstance(chip.get("away"), Mapping) else {}
        home = chip.get("home") if isinstance(chip.get("home"), Mapping) else {}
        for a, h in (
            (_lower(away.get("key")), _lower(home.get("key"))),
            (_lower(away.get("name")), _lower(home.get("name"))),
        ):
            if a and h:
                chip_pairs.add(f"{sport}|{a}|{h}")

    report: dict[str, Any] = {}
    for card in cards or ():
        if not isinstance(card, Mapping):
            continue
        sport = _card_sport(card)
        if not sport:
            continue
        bucket = report.setdefault(
            sport,
            {
                "cards": 0,
                "by_id": 0,
                "by_matchup": 0,
                "by_canonical": 0,
                "needs_fallback": 0,
                "no_chip_available": 0,
                "unknown_no_key": 0,
                "samples": [],
            },
        )
        bucket["cards"] += 1

        def _hit(kind: str) -> None:
            bucket[kind] += 1

        if any(f"{sport}|{ident}" in by_id for ident in _card_ids(card) if ident):
            _hit("by_id")
            continue
        matchup = _lower(card.get("matchup"))
        if matchup and f"{sport}|{matchup}" in by_matchup:
            _hit("by_matchup")
            continue
        away_key, home_key = _lower(card.get("away_key")), _lower(card.get("home_key"))
        if away_key and home_key and f"{sport}|{away_key} @ {home_key}" in by_canonical:
            _hit("by_canonical")
            continue

        # No deterministic route. Is there a chip for this fixture AT ALL?
        #
        # THREE OUTCOMES, NOT TWO. Without canonical keys on the card we cannot
        # answer the question at all, and answering it anyway is how a
        # diagnostic starts lying: the first version of this reported
        # `no_chip_available` for keyless cards, which asserts a chip does not
        # exist on the strength of not having looked. Keyless is its own
        # bucket, and it should read 0 on any card built after the keys
        # shipped -- a non-zero value means rows are reaching the board from
        # somewhere that does not stamp them.
        if not (away_key and home_key):
            kind = "unknown_no_key"
        elif f"{sport}|{away_key}|{home_key}" in chip_pairs:
            kind = "needs_fallback"
        else:
            kind = "no_chip_available"
        bucket[kind] += 1
        if len(bucket["samples"]) < _MAX_SAMPLES:
            # The SPELLINGS, because the fix is always an alias entry and the
            # alias entry needs the exact string each feed used.
            bucket["samples"].append(
                {
                    "matchup": _text(card.get("matchup")),
                    "away_key": away_key or None,
                    "home_key": home_key or None,
                    "why": kind,
                }
            )
    # `by_sport` is a SEPARATE key rather than the whole return value, so a
    # caller can iterate sports without having to know which top-level keys are
    # not sports. A dict that is "mostly one shape" is how a consumer ends up
    # treating a diagnostic counter as a sport.
    return {
        "by_sport": report,
        "canonical_collisions_dropped": indexes["canonical_collisions"],
    }
