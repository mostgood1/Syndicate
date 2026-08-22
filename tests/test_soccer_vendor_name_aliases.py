"""The six `#503` aliases, each quoted from a production log line.

`#374` added five vendor aliases and its note is explicit that each was
"verified against a real 0-projection fixture on the served board where the sim
HAD the match under its own name". Finding those meant fetching the served
board, then the sim artifacts, then diffing by hand.

`PREGAME_PROJECTION_JOIN` now prints the BOARD spelling and the SIM spelling of
the same unmatched fixture on one line, so the six below are quoted from two
readings (refresh-worker 2026-08-22 17:36:42Z and 17:39:37Z) rather than
reconstructed. That distinction is the whole point: an earlier pass in this same
session guessed `Inter Milan`/`Internazionale` from the git mirror and was
right, and guessed nothing else usefully, because the mirror carries no quote
side at all.

WHAT THIS FILE PINS, and why each part is separate:

  * REACHABILITY FIRST (`off != on`). The model-engine standard requires it for
    anything behind a switch, and an alias map is exactly that: a wrong entry
    and a missing entry both render as a blank projection. The fixture test
    below asserts 0/5 without these entries -- if someone deletes them and the
    test still passes, the test was never measuring them.
  * BOTH SIDES OF EACH PAIR. `canonical_team` must return None for the board
    spelling before, and the club after. A pair where the sim side does NOT
    resolve is an alias pointing at nothing, which fails silently.
  * THE PAIRS THAT ALREADY WORKED ARE ASSERTED TOO, and are NOT in the map.
    Adding a working pair buys nothing and hides which entries are
    load-bearing.
"""

from __future__ import annotations

import json
from pathlib import Path

from syndicate.features.shared.soccer_projections import (
    attach_soccer_projections,
    load_soccer_projections,
)
from syndicate.features.shared.team_aliases import canonical_team, teams_match

DATE = "2026-08-23"

# (league, board spelling, sim spelling) -- both quoted from the same log line.
REPAIRED = [
    ("belgian_pro_league", "Royal Antwerp", "Antwerp"),
    ("bundesliga", "1. FC Köln", "FC Cologne"),
    ("bundesliga", "Hamburger SV", "Hamburg SV"),
    ("bundesliga", "FSV Mainz 05", "Mainz"),
    ("bundesliga", "SC Paderborn", "SC Paderborn 07"),
    ("bundesliga", "Union Berlin", "1. FC Union Berlin"),
]

# Spellings the two feeds already agreed on, from the same fixtures. Present so
# a future change that "fixes" them by adding map entries is visibly redundant.
ALREADY_MATCHED = [
    ("bundesliga", "TSG Hoffenheim", "TSG Hoffenheim"),
    ("bundesliga", "Borussia Dortmund", "Borussia Dortmund"),
    ("bundesliga", "Eintracht Frankfurt", "Eintracht Frankfurt"),
    # Matches on the shared-suffix heuristic, with no map entry.
    ("belgian_pro_league", "Genk", "Racing Genk"),
]

# The five fixtures production named, spelled as each feed spells them.
FIXTURES = [
    ("belgian_pro_league", ("Royal Antwerp", "Genk"), ("Antwerp", "Racing Genk")),
    ("bundesliga", ("1. FC Köln", "TSG Hoffenheim"), ("FC Cologne", "TSG Hoffenheim")),
    ("bundesliga", ("Borussia Dortmund", "Hamburger SV"), ("Borussia Dortmund", "Hamburg SV")),
    ("bundesliga", ("FSV Mainz 05", "SC Paderborn"), ("Mainz", "SC Paderborn 07")),
    ("bundesliga", ("Union Berlin", "Eintracht Frankfurt"), ("1. FC Union Berlin", "Eintracht Frankfurt")),
]


def _index(tmp_path: Path):
    by_league: dict[str, list[tuple[str, str]]] = {}
    for league, _board, sim in FIXTURES:
        by_league.setdefault(league, []).append(sim)
    for league, sims in by_league.items():
        path = tmp_path / league / "api" / "recommendations" / f"recommendations_{DATE}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "league": league,
                    "generated_at": "2026-08-22T17:00:00",
                    "matches": [
                        {
                            "match_id": f"{league}-{i}",
                            "event_id": f"espn-{league}-{i}",
                            "league": league,
                            "matchup": {"home_team": home, "away_team": away},
                            "win_probability": {"home": 0.45, "draw": 0.28, "away": 0.27},
                        }
                        for i, (home, away) in enumerate(sims)
                    ],
                }
            ),
            encoding="utf-8",
        )
    return load_soccer_projections([tmp_path], DATE, window_dates=[DATE])


def _grid():
    return [
        {
            "sport": "soccer",
            "kind": "game",
            "market": "h2h",
            "league": league,
            "event_id": f"oddsapi-{i}",
            "home_team": board[0],
            "away_team": board[1],
            "line": None,
        }
        for i, (league, board, _sim) in enumerate(FIXTURES)
    ]


def test_every_repaired_pair_now_names_one_club() -> None:
    for league, board, sim in REPAIRED:
        assert teams_match("soccer", board, sim), f"{league}: {board!r} != {sim!r}"


def test_the_sim_side_of_every_alias_resolves_to_a_real_club() -> None:
    """An alias whose TARGET does not resolve is an entry pointing at nothing.

    `_soccer_alias_to_name` only registers a vendor alias when
    `mapping.get(normalize(espn_name))` finds something, so a typo in the value
    makes the whole entry a silent no-op.
    """
    for league, _board, sim in REPAIRED:
        assert canonical_team("soccer", sim) is not None, f"{league}: sim side {sim!r} unresolvable"


def test_the_pairs_that_already_agreed_are_not_in_the_map() -> None:
    """They match without help, so an entry would be dead weight that reads as live."""
    from syndicate.features.shared.team_aliases import _SOCCER_VENDOR_NAME_ALIASES

    for league, board, sim in ALREADY_MATCHED:
        assert teams_match("soccer", board, sim), f"{league}: {board!r} != {sim!r}"
        assert board.lower() not in _SOCCER_VENDOR_NAME_ALIASES, board


def test_one_bad_name_costs_the_WHOLE_fixture() -> None:
    """`match_for` requires both sides, which is why one alias recovers 500+ rows.

    `Royal Antwerp v Genk` missed although Genk matches fine. Stated as a test
    because it is the non-obvious economics of this map: fixtures are the unit
    of loss, not clubs.
    """
    assert teams_match("soccer", "Genk", "Racing Genk")
    assert not teams_match("soccer", "Royal Antwerp", "Racing Genk")


def test_all_five_production_fixtures_join(tmp_path: Path) -> None:
    coverage = attach_soccer_projections(_grid(), _index(tmp_path))
    assert coverage["rows_with_projection"] == 5, coverage["unmatched_fixture_sample"]
    assert coverage["unmatched_match_rows"] == 0
    assert coverage["unmatched_fixture_sample"] == []


def test_REACHABILITY_without_the_map_entries_none_of_them_join(tmp_path: Path, monkeypatch) -> None:
    """off != on. Without this, the test above passes on a map that does nothing.

    Measured against the real map: 0 of 5 join without these entries, 5 of 5
    with them, and the unmatched fixture strings reproduce the production line
    character for character.
    """
    import syndicate.features.shared.team_aliases as aliases

    monkeypatch.setattr(aliases, "_SOCCER_VENDOR_NAME_ALIASES", {}, raising=True)
    aliases._soccer_alias_to_name.cache_clear()
    try:
        coverage = attach_soccer_projections(_grid(), _index(tmp_path))
        assert coverage["rows_with_projection"] == 0
        assert coverage["unmatched_match_rows"] == 5
        assert coverage["unmatched_fixture_sample"] == [
            "belgian_pro_league|Royal Antwerp v Genk",
            "bundesliga|1. FC Köln v TSG Hoffenheim",
            "bundesliga|Borussia Dortmund v Hamburger SV",
            "bundesliga|FSV Mainz 05 v SC Paderborn",
            "bundesliga|Union Berlin v Eintracht Frankfurt",
        ]
    finally:
        # The map is `lru_cache`d, so a stale empty build would poison every
        # later test in the process.
        aliases._soccer_alias_to_name.cache_clear()
