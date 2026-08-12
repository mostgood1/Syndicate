"""`#407` -- per-book columns, sortable headers, and a game selector on Layer 1.

WHY THIS PAGE AND NOT `book_grid`. Measured on production 2026-08-12, core game
rows across four sports:

    sport   core  proj  modelled_fair  consensus  two-sided
    mlb      341   326        0           341        341
    wnba      40    37        0            40         40
    nfl      126   126        0           126        126
    soccer   275   205        0           275        275

`book_grid.html:590` reaches Fair only via `modelled_fair` or
`proj.market_fair_prob_over`. `modelled_fair` is **0 on all 782 core rows** --
two-sided markets skip the margin model by design -- so `book_grid`'s Fair column
is not "blank for WNBA", it is structurally blank everywhere, always. Its tooltip
compounds it: "no two-sided market, so no-vig fair value cannot be computed" on
782 rows that are ALL two-sided with both sides priced.

`layer1_board` reaches all 782 through its consensus-devig tier, and after `#364`
/`#365` it also carries projections on 694 of them. It is strictly better on
data; the only thing `book_grid` had was the per-book layout. So the layout moves
here rather than the fair-value logic moving there -- two implementations of one
number is how these drifted apart in the first place.

THE BUG THIS ALMOST SHIPPED WITH, because it is the failure mode the whole
session has been about: `sortValue` read the price maps with `projSide(r)`, but
`projection.side` is a LABEL ("Dallas Wings", "over") while `best`/`consensus`/
`modelled_fair` are keyed by the row's own side tokens (`home`/`away`/`over`/
`under`). Every price key returned undefined -> null -> nulls sort last -> the
order never changed. The arrows flipped and the board did not move. Caught by
asserting the column is MONOTONIC after a click, not that the header is
clickable.
"""

from __future__ import annotations

import pathlib
import re

_TEMPLATE = (
    pathlib.Path(__file__).resolve().parents[1]
    / "syndicate" / "templates" / "shared" / "layer1_board.html"
)


def _html() -> str:
    return _TEMPLATE.read_text(encoding="utf-8")


def test_price_columns_sort_on_the_rows_own_side_not_the_projections():
    """The keyspace bug, asserted directly.

    `projection.side` and the price maps do not share a keyspace. If `sortValue`
    ever reads `best`/`consensus`/`modelled_fair` with the projection's side
    again, sorting silently becomes a no-op.
    """
    html = _html()
    start = html.index("function sortValue")
    body = html[start:start + 2600]
    assert "var priceSide = (r.sides || [])[0];" in body
    for expr in ("(r.best || {})[priceSide]", "(r.consensus || {})[priceSide]",
                 "(r.modelled_fair || {})[priceSide]", "noVigFair(r, priceSide)"):
        assert expr in body, f"price lookup not on the row's own side: {expr}"
    # The projection side must not reach any price map.
    assert "(r.best || {})[side]" not in body
    assert "(r.consensus || {})[side]" not in body


def test_nulls_sort_last_in_both_directions():
    # A blank is not a small number. Flipping the arrow must not promote every
    # row that has no value to the top.
    body = _html()
    start = body.index("function sortRows")
    seg = body[start:start + 900]
    assert "if (an && bn) { return 0; }" in seg
    assert "if (an) { return 1; }" in seg
    assert "if (bn) { return -1; }" in seg


def test_book_columns_are_per_card_not_board_wide():
    # MLB carries 37 books. A board-wide column set would put an empty column on
    # every game that lacks a book and make every card unreadable.
    html = _html()
    assert "function booksFor(rows)" in html
    assert "booksFor(visible)" in html, "the book set must come from the rows actually shown"


def test_book_cells_are_keyed_by_book_AND_side():
    # A row renders one <tr> per side. Reading `cells[book]` flat would print the
    # over price on the under row.
    html = _html()
    assert "((r.cells || {})[bk] || {})[side]" in html


def test_book_columns_are_not_sortable():
    """Carried from `book_grid`'s reasoning, deliberately.

    Sorting the grid by one book's price reorders every row by a number most of
    them do not carry, which looks like a ranking and is not one.
    """
    html = _html()
    head = html[html.index("var SORT_COLS"):html.index("function cardHtml")]
    keys = re.findall(r'\["(\w+)",', head)
    assert set(keys) <= {"mkt", "side", "proj", "edge", "best", "fair", "cons"}
    # The book header cells carry no sort key.
    assert '\'<th class="l1-book">\' + esc(b) + "</th>"' in html


def test_the_bare_book_count_column_is_gone():
    # `books_quoting` said HOW MANY; the columns say WHICH and at what price.
    assert '"<td>" + (r.books_quoting || 0) + "</td>"' not in _html()


def test_the_game_selector_keys_on_event_id():
    # Two games can share a tri-code matchup label across a multi-day soccer
    # window; a label key would silently merge them.
    html = _html()
    assert "function renderGames" in html
    assert 'data-game="' + "' + esc(id) + '" in html or "esc(id)" in html
    assert 'String(g.event_id || "") === state.game' in html, "filter must compare event_id"


def test_every_render_helper_is_actually_called():
    # This session produced several fixes that existed and never ran.
    html = _html()
    for name in ("renderGames", "sortRows", "booksFor", "sortHead"):
        assert f"function {name}" in html, f"{name} missing"
        assert html.count(name + "(") >= 2, f"{name} declared but never called"


def test_sort_headers_are_rewired_after_every_render():
    # The table is new DOM on each render; handlers bound once would stop
    # working the moment any tab is clicked -- the same trap the slip buttons
    # already document.
    html = _html()
    assert 'querySelectorAll("th[data-sort]")' in html
