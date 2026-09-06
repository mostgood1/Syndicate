"""Two feeds spelling one player differently must produce ONE grid row.

WHY THIS FILE EXISTS. Measured on production 2026-09-06 (artifact
`written_at 2026-09-06T14:44:08Z`, `/api/board/layer2-shortlist?date=2026-09-06
&sport=mlb&limit=2000`, 1,996 MLB rows): **25 `_row_key` collisions, all 25 a
diacritic spelling pair**, six players. The two rows were separately stakeable
and resolved to the same Kalshi ticker, and on **16 of the 25** the price
stranded on the second row BEAT the first row's `best_any_book`.

THE FIRST ASSERTION IN THIS FILE IS A REACHABILITY TEST, not a correctness one:
it pins that folding CHANGES the grid (`off != on`). A correctness test that
passes with the fold reverted proves nothing, and this repo has shipped four
inert fixes that read as working.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.book_grid import (
    _instance_display_name,
    _instance_key,
    _line_group_key,
    build_book_grid,
)

ASCII = "Julio Rodriguez"
ACCENT = "Julio Rodríguez"


def _quote(book: str, name: str, price: int, side: str = "over", line: float = 0.5):
    return {
        "sport": "mlb",
        "kind": "prop",
        "event_id": "E1",
        "segment": "full",
        "market": "batter_hits",
        "player_name": name,
        "selection": side,
        "line": line,
        "price": price,
        "bookmaker": book,
        "observed_at": "2026-09-06T14:00:00Z",
    }


def _grid_for(kalshi_name: str):
    return build_book_grid(
        [
            _quote("draftkings", ASCII, -214),
            _quote("betmgm", ASCII, -220),
            _quote("kalshi", kalshi_name, -194),
        ]
    )


# --------------------------------------------------------------------------
# REACHABILITY -- the fold must be the thing that changes the answer.
# --------------------------------------------------------------------------


def test_the_fold_is_reachable_off_differs_from_on():
    """`off != on`, on the real `build_book_grid` over the real defect shape."""
    agree = _grid_for(ASCII)
    differ = _grid_for(ACCENT)

    # The control: when the feeds already agree there was never a split.
    assert len(agree) == 1
    assert sorted(agree[0]["books"]) == ["betmgm", "draftkings", "kalshi"]

    # The fix: one accent apart is now the SAME instance, not two.
    assert len(differ) == 1, "a diacritic still splits one bet into two grid rows"
    assert sorted(differ[0]["books"]) == ["betmgm", "draftkings", "kalshi"]


def test_the_stranded_price_actually_reaches_the_merged_row():
    """Merging is only worth anything if the price arrives with it.

    The production consequence was NOT the duplicate row per se -- it was that
    `best_any_book` on the surviving row was not the best price available.
    """
    row = _grid_for(ACCENT)[0]
    prices = {book: cell["over"]["price"] for book, cell in row["cells"].items()}
    assert prices == {"draftkings": -214, "betmgm": -220, "kalshi": -194}


# --------------------------------------------------------------------------
# THE NAME IS A LABEL, THE KEY IS AN IDENTITY -- they must not become one.
# --------------------------------------------------------------------------


def test_the_row_keeps_a_real_display_name_not_the_folded_key_term():
    """A folded key must not put `julio rodriguez` on the board."""
    row = _grid_for(ACCENT)[0]
    assert row["player_name"] in {ASCII, ACCENT}
    assert row["player_name"] != "julio rodriguez"


def test_display_name_is_the_majority_spelling():
    """Two books say ASCII, one says ACCENT -> the board shows ASCII."""
    assert _grid_for(ACCENT)[0]["player_name"] == ASCII


def test_display_name_is_order_independent():
    """Same inputs in any order pick the same label.

    A display name that flips between builds churns the UI and makes
    `_line_group_key` and `layer2_shortlist._classify_stale_row` -- both of
    which read this field off the grid row -- non-deterministic.
    """
    rows = [_quote("kalshi", ACCENT, -194), _quote("draftkings", ASCII, -214)]
    first = _instance_display_name(rows)
    second = _instance_display_name(list(reversed(rows)))
    assert first == second, "display name depends on iteration order"
    # One each, so the tie-break decides -- and it must be the LEXICOGRAPHIC one.
    assert first == sorted({ASCII, ACCENT})[0]


def test_display_name_is_none_when_nothing_names_a_player():
    """A game line has no player, and must not acquire an empty-string one."""
    assert _instance_display_name([{"market": "totals"}]) is None
    assert _instance_display_name([]) is None


# --------------------------------------------------------------------------
# THE FOLD MUST NOT REACH FURTHER THAN THE SPELLING.
# --------------------------------------------------------------------------


def test_two_different_players_are_still_two_instances():
    """The fold collapses spellings of ONE name, never two humans."""
    grid = build_book_grid(
        [
            _quote("draftkings", "Julio Rodriguez", -214),
            _quote("draftkings", "Jose Ramirez", -150),
        ]
    )
    assert len(grid) == 2
    assert {row["player_name"] for row in grid} == {"Julio Rodriguez", "Jose Ramirez"}


@pytest.mark.parametrize(
    "field, other",
    [
        ("event_id", "E2"),
        ("market", "batter_home_runs"),
        ("segment", "first5"),
        ("kind", "game"),
        ("sport", "nba"),
    ],
)
def test_every_other_instance_field_still_separates(field, other):
    """Only `player_name` is folded; the rest of the identity is untouched."""
    a = _quote("draftkings", ASCII, -214)
    b = dict(_quote("kalshi", ASCII, -194), **{field: other})
    assert _instance_key(a) != _instance_key(b)
    assert len(build_book_grid([a, b])) == 2


def test_line_group_key_folds_the_same_way():
    """`drop_superseded_lines` must not prune across a spelling either."""
    assert _line_group_key({"player_name": ASCII}) == _line_group_key(
        {"player_name": ACCENT}
    )
    assert _line_group_key({"player_name": "Jose Ramirez"}) != _line_group_key(
        {"player_name": ASCII}
    )
