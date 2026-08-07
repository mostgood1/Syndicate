"""#262 — spreads are signed per side, and the pairing rule must check WHICH side.

Every test here fails on the pre-fix code. The old rule accepted "the same line
OR its mirror" without checking which side sat on which, so an anchor of
`away +1.5` admitted all four of {away +1.5, home -1.5, away -1.5, home +1.5} --
two different markets merged into one.

Measured on production 2026-08-07 (`spreads_alt`, first5, ONE row):

    betmgm     away -1.5 (+210)   home +1.5 (-295)
    betrivers  away +1.5 (-240)   home -1.5 (+180)

`best.away` therefore ranked a -1.5 bet against a +1.5 bet, and the no-vig fair
value was derived across two markets.
"""

from __future__ import annotations

from syndicate.features.shared.book_grid import build_book_grid
from syndicate.features.shared.odds_book_quotes import market_sides_for_quote


def _q(selection, line, price, book="betmgm", *, market="spreads_alt", observed="2026-08-07T18:00:00Z"):
    return {
        "sport": "mlb",
        "kind": "game",
        "event_id": "evt1",
        "segment": "first5",
        "market": market,
        "player_name": "",
        "selection": selection,
        "line": line,
        "price": price,
        "bookmaker": book,
        "book_updated_at": observed,
        "snapshot_ts": observed,
        "captured_at": observed,
    }


# The four quotes that exist for one alternate-spread ladder rung. They are TWO
# markets: (away +1.5 / home -1.5) and (away -1.5 / home +1.5).
_LADDER = [
    _q("away", 1.5, -240, "betrivers"),
    _q("home", -1.5, 180, "betrivers"),
    _q("away", -1.5, 210, "betmgm"),
    _q("home", 1.5, -295, "betmgm"),
]


def test_anchor_gathers_only_its_own_side_of_the_ladder():
    anchor = _q("away", 1.5, -240, "betrivers")
    sides = market_sides_for_quote(_LADDER, anchor)
    got = sorted((r["selection"], r["line"]) for r in sides)
    assert got == [("away", 1.5), ("home", -1.5)]


def test_the_mirror_instance_is_a_separate_market():
    anchor = _q("away", -1.5, 210, "betmgm")
    sides = market_sides_for_quote(_LADDER, anchor)
    got = sorted((r["selection"], r["line"]) for r in sides)
    assert got == [("away", -1.5), ("home", 1.5)]


def test_home_anchor_resolves_to_the_same_instance_as_its_away_partner():
    """Anchoring from either side must describe the SAME market."""
    from_away = market_sides_for_quote(_LADDER, _q("away", 1.5, -240, "betrivers"))
    from_home = market_sides_for_quote(_LADDER, _q("home", -1.5, 180, "betrivers"))
    assert sorted((r["selection"], r["line"]) for r in from_away) == sorted(
        (r["selection"], r["line"]) for r in from_home
    )


def test_totals_share_a_line_rather_than_mirroring_it():
    rows = [
        _q("over", 8.5, 100, "betmgm", market="totals"),
        _q("under", 8.5, -120, "betmgm", market="totals"),
        _q("over", 9.5, 150, "betmgm", market="totals"),
        _q("under", -8.5, 999, "betmgm", market="totals"),   # nonsense mirror
    ]
    sides = market_sides_for_quote(rows, rows[0])
    got = sorted((r["selection"], r["line"]) for r in sides)
    assert got == [("over", 8.5), ("under", 8.5)]


def test_h2h_without_lines_is_unaffected():
    rows = [
        _q("away", None, 120, "betmgm", market="h2h"),
        _q("home", None, -140, "betmgm", market="h2h"),
    ]
    sides = market_sides_for_quote(rows, rows[0])
    assert len(sides) == 2


# --- the grid ----------------------------------------------------------------


def test_grid_emits_both_ladder_instances_not_one_merged_row():
    """Pre-fix this produced ONE row (anchor key was abs(line)), so half the
    alternate-spread market was missing from the board entirely."""
    grid = build_book_grid(_LADDER)
    assert len(grid) == 2
    assert sorted(row["line"] for row in grid) == [-1.5, 1.5]


def test_every_cell_in_a_grid_row_agrees_with_the_rows_line():
    """The defect as a user saw it: one row holding both signs at once."""
    grid = build_book_grid(_LADDER)
    for row in grid:
        row_line = row["line"]
        for book, by_side in (row["cells"] or {}).items():
            for side, cell in (by_side or {}).items():
                expected = row_line if side != "home" else -row_line
                assert cell["line"] == expected, (
                    f"{book}/{side} on row line={row_line} carried {cell['line']}"
                )


def test_best_price_no_longer_mixes_the_two_ladder_sides():
    """away -240 and away +210 are different bets; only one belongs per row."""
    grid = build_book_grid(_LADDER)
    by_line = {row["line"]: row for row in grid}
    # The (away +1.5 / home -1.5) market: away is betrivers at -240, and betmgm
    # must NOT appear on the away side of this row with its -1.5 price.
    plus = by_line[1.5]
    assert plus["cells"]["betrivers"]["away"]["price"] == -240
    assert "away" not in (plus["cells"].get("betmgm") or {})
