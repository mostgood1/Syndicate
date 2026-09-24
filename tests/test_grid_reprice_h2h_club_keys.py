"""The GRID re-price must speak the moneyline's club vocabulary, not only its role.

WHY THIS EXISTS. `apply_venue_quotes_to_grid` is the pass that runs BEFORE
`attach_live_gamelines`, so its re-stamped age is the only one the live
game-line join can ever see. It built its candidate keys from the ROLE alone:

    candidates = [quote_key(sport, market, side_key, line)]        # mlb|h2h|home
    if role_keyed and row_game: candidates.append(... row_game)    # role + game

and `_ROLE_KEYED_MARKETS` does not contain `h2h`, so a moneyline never left the
first shape. Kalshi keys a moneyline by the CLUB -- `mlb|h2h|new york yankees`
-- so the two halves of the join could not meet.

`_candidate_keys`, on the `apply_venue_quotes` path, HAS offered the club and
token shapes since 2026-08-25. That path runs AFTER the join.

MEASURED on production 2026-09-23T23:2x-23:4xZ, MLB:

    GRID_REPRICE   sides_seen=6517  repriced=60      (before the join)
    VENUE_REPRICE  rows_in=12205    stamped=4315     (after it)

    LIVE_GAMELINE_JOIN sport=mlb considered=413 projected=0 priceable=0
      withheld=413  why={'quote_older_than_live_pricing_ceiling': 61, ...}

All 61 full-game live rows refused against a 120s ceiling while Kalshi's own
quotes for those fixtures were 22.8s old.
"""

from __future__ import annotations

import time

import pytest

from syndicate.features.shared.venue_quote_adapters import quote_key
from syndicate.features.shared.venue_quote_fanin import (
    Quote,
    _h2h_alias_keys,
    apply_venue_quotes_to_grid,
)


def _quote(key, source="kalshi", american=-122, *, age=23.0, market="h2h", line=None, side="home"):
    return Quote(
        key=key,
        source=source,
        sport="mlb",
        market=market,
        side=side,
        probability=0.55,
        american=american,
        line=line,
        fetched_at=time.time() - age,
        venue_ref=f"{source}-ref",
    )


def _grid_row(
    *,
    home="New York Yankees",
    away="Tampa Bay Rays",
    market="h2h",
    line=None,
    sides=("home",),
    book_age=206.0,
):
    """A live MLB grid row in the shape `book_grid` writes.

    `book_age=206.0` is the real number: on 2026-09-23 the sportsbook
    `seen_age` across all 202 live MLB game rows was p25=p50=p75=max=206s.
    """
    return {
        "sport": "mlb",
        "market": market,
        "line": line,
        "sides": list(sides),
        "home_team": home,
        "away_team": away,
        "event_id": "evt-1",
        "game": {"state": "live"},
        "best": {
            side: {"price": -110, "bookmaker": "draftkings", "age_seconds": book_age}
            for side in sides
        },
    }


def _collected(*quotes):
    return {"quotes": {q.key: q for q in quotes}, "by_source": {}}


# ---------------------------------------------------------------------------
# REACHABILITY FIRST: off != on. The role key alone must NOT reach a
# club-keyed quote, and the alias keys must.
# ---------------------------------------------------------------------------


def test_the_role_key_alone_cannot_name_a_club_keyed_moneyline():
    """The exact gap, stated as the pre-fix candidate set.

    This is the `off` half of `off != on`: what the grid path built before is
    reproduced here literally, and it does not contain the key Kalshi publishes.
    """
    row = _grid_row()
    old_candidates = [str(quote_key("mlb", "h2h", "home", None))]

    kalshi_key = str(quote_key("mlb", "h2h", "new york yankees", None))

    assert old_candidates == ["mlb|h2h|home"]
    assert kalshi_key not in old_candidates

    new_candidates = old_candidates + _h2h_alias_keys(
        row, "mlb", "h2h", "home", old_candidates
    )
    assert kalshi_key in new_candidates


def test_a_club_keyed_kalshi_moneyline_now_reprices_the_grid_row():
    """The `on` half, end to end through the real function."""
    grid = [_grid_row()]
    kalshi_key = str(quote_key("mlb", "h2h", "new york yankees", None))

    result = apply_venue_quotes_to_grid(
        grid,
        "mlb",
        "2026-09-23",
        collected=_collected(_quote(kalshi_key, age=23.0)),
    )

    side = grid[0]["best"]["home"]
    assert result["repriced"] == 1
    assert side["price"] == -122
    assert side["price_source"] == "kalshi"
    # PRICE AND AGE MOVE TOGETHER. The age is what the live game-line join
    # reads, and 23s clears MLB's 120s ceiling where 206s does not.
    assert side["age_seconds"] == pytest.approx(23.0, abs=3.0)
    assert side["age_seconds"] < 120.0


def test_the_nickname_alone_also_reaches_the_row():
    """Kalshi names a moneyline "Yankees win", not "New York Yankees win"."""
    grid = [_grid_row()]
    result = apply_venue_quotes_to_grid(
        grid,
        "mlb",
        "2026-09-23",
        collected=_collected(_quote(str(quote_key("mlb", "h2h", "yankees", None)))),
    )
    assert result["repriced"] == 1
    assert grid[0]["best"]["home"]["price_source"] == "kalshi"


# ---------------------------------------------------------------------------
# THE SAFETY PROPERTY, carried over from `_candidate_keys`: an ambiguous token
# names NEITHER side and must never be offered.
# ---------------------------------------------------------------------------


def test_an_ambiguous_city_token_is_never_offered():
    """"chicago" sits inside both Chicago clubs, so on a Cubs/White Sox game it
    names neither. Guessing is a bet on the wrong team half the time."""
    row = _grid_row(home="Chicago Cubs", away="Chicago White Sox")
    keys = _h2h_alias_keys(row, "mlb", "h2h", "home", [])

    assert str(quote_key("mlb", "h2h", "chicago", None)) not in keys
    # The unambiguous ones are still offered.
    assert str(quote_key("mlb", "h2h", "chicago cubs", None)) in keys
    assert str(quote_key("mlb", "h2h", "cubs", None)) in keys


def test_an_ambiguous_token_does_not_reprice_the_row():
    """The safety property through the real function, not only the key list."""
    grid = [_grid_row(home="Chicago Cubs", away="Chicago White Sox")]
    result = apply_venue_quotes_to_grid(
        grid,
        "mlb",
        "2026-09-23",
        collected=_collected(_quote(str(quote_key("mlb", "h2h", "chicago", None)))),
    )
    assert result["repriced"] == 0
    assert grid[0]["best"]["home"]["price"] == -110
    assert grid[0]["best"]["home"]["age_seconds"] == pytest.approx(206.0)


def test_an_unresolvable_team_yields_no_key_at_all():
    """No club, no second key -- never a bare team string as a fallback. An
    unresolved name would build a key that matches nothing and hide the fact
    that the row could not be placed."""
    row = _grid_row(home="Not A Real Club")
    keys = _h2h_alias_keys(row, "mlb", "h2h", "home", [])

    assert keys == []
    for token in ("not", "a", "real", "club"):
        assert str(quote_key("mlb", "h2h", token, None)) not in keys


# ---------------------------------------------------------------------------
# ADDITIVE BY CONSTRUCTION -- this may only ADD matches.
# ---------------------------------------------------------------------------


def test_a_role_keyed_quote_still_wins_first():
    """Every match that worked before still works, and still resolves first."""
    grid = [_grid_row()]
    role_key = str(quote_key("mlb", "h2h", "home", None))
    club_key = str(quote_key("mlb", "h2h", "new york yankees", None))

    result = apply_venue_quotes_to_grid(
        grid,
        "mlb",
        "2026-09-23",
        collected=_collected(
            _quote(role_key, american=-150, age=23.0),
            _quote(club_key, american=-122, age=23.0),
        ),
    )
    assert result["repriced"] == 1
    # The ROLE key is tried first, so its price is the one that lands.
    assert grid[0]["best"]["home"]["price"] == -150


def test_non_h2h_markets_gain_no_alias_keys():
    """Totals and spreads are role-keyed on both sides of the join already;
    widening them here would be a change nobody measured."""
    row = _grid_row(market="totals", line=8.5, sides=("over",))
    assert _h2h_alias_keys(row, "mlb", "totals", "over", []) == []
    assert _h2h_alias_keys(row, "mlb", "spreads", "home", []) == []
    assert _h2h_alias_keys(row, "mlb", "totals_alt", "under", []) == []


def test_a_key_the_caller_already_holds_is_not_repeated():
    row = _grid_row()
    club_key = str(quote_key("mlb", "h2h", "new york yankees", None))
    keys = _h2h_alias_keys(row, "mlb", "h2h", "home", [club_key])
    assert club_key not in keys


def test_the_away_side_names_the_away_club():
    row = _grid_row()
    keys = _h2h_alias_keys(row, "mlb", "h2h", "away", [])
    assert str(quote_key("mlb", "h2h", "tampa bay rays", None)) in keys
    assert str(quote_key("mlb", "h2h", "new york yankees", None)) not in keys


# ---------------------------------------------------------------------------
# THE INSTRUMENT. `404d2194` shipped this fix and measured nothing, and the
# counter reached for as the explanation was withdrawn. The per-shape funnel
# exists so the next reading cannot be ambiguous in the same way.
# ---------------------------------------------------------------------------


def test_the_shape_funnel_separates_no_match_from_discarded_match():
    """`offered -> present -> taken -> repriced`, per shape, plus `live_*`.

    The discrimination is the point: `role` and `token` are OFFERED here and
    never PRESENT, because nothing in the pool answers them -- that is the
    "matches nothing" signature. `club` walks the whole funnel.
    """
    grid = [_grid_row(), _grid_row(home="Boston Red Sox", away="Baltimore Orioles")]
    grid[1]["event_id"] = "evt-bos-bal"
    club_key = str(quote_key("mlb", "h2h", "new york yankees", None))

    result = apply_venue_quotes_to_grid(
        grid, "mlb", "2026-09-24",
        collected=_collected(_quote(club_key, age=23.0)),
    )

    shapes = result["venue_key_shape"]
    assert shapes["club"]["offered"] >= 1
    assert shapes["club"]["present"] == 1
    assert shapes["club"]["taken"] == 1
    assert shapes["club"]["repriced"] == 1
    # The live mirror exists, because the live rows are the population the
    # game-line join's staleness refusal is actually about.
    assert shapes["club"]["live_repriced"] == 1

    # OFFERED BUT NEVER PRESENT -- nothing in the pool answers these.
    assert shapes["role"]["offered"] >= 1
    assert "present" not in shapes["role"]
    assert "present" not in shapes.get("token", {})


def test_a_shape_that_wins_but_cannot_move_the_age_is_named_separately():
    """`taken` without `repriced` is the third explanation, and it has to be
    distinguishable: the row keeps its book age, so the live game-line join
    downstream still sees the stale number."""
    # The book is FRESHER than the venue, so the reprice is declined.
    grid = [_grid_row(book_age=5.0)]
    club_key = str(quote_key("mlb", "h2h", "new york yankees", None))

    result = apply_venue_quotes_to_grid(
        grid, "mlb", "2026-09-24",
        collected=_collected(_quote(club_key, age=200.0)),
    )

    shapes = result["venue_key_shape"]
    assert result["repriced"] == 0
    assert shapes["club"]["taken"] == 1
    assert shapes["club"].get("repriced", 0) == 0
    assert shapes["club"]["dropped_book_fresher"] == 1
