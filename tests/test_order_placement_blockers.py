"""The three reasons no order has ever reached a venue from this system.

MEASURED 2026-08-25 14:57:34Z -- three live attempts, three distinct causes:

  polymarket  totals under 8.5 · CIN @ SF   OrderBuildError: market_unresolved_for_position
  polymarket  h2h home · TEX @ CWS          OrderBuildError: market_unresolved_for_position
  kalshi      h2h home · TEX @ CWS          OrderBuildError: no_live_price: None

The wrong-game key (`#547`) is pinned in `test_polymarket_resolver_wrong_game`.
These pin the two that BLOCKED placement outright, plus the aggregator-duplicate
rule that would have let one venue quote two different numbers.
"""

from __future__ import annotations

import pytest


# --- 1. Polymarket: `venue_ticker` carries a dict, not a slug ---------------


class _Req:
    def __init__(self, venue_ticker, side="under", requested_price=-115.0):
        self.venue_ticker = venue_ticker
        self.side = side
        self.requested_price = requested_price
        self.sport = "mlb"
        self.market = "totals"
        self.line = 8.5


def _slug_seen(monkeypatch, venue_ticker):
    """Run the resolver far enough to see which slug it looked up.

    Asserted on the SLUG rather than on a fully resolved order: the defect is
    the slug extraction, and driving the whole chain would couple this test to
    side-resolution and staleness rules it is not about.
    """
    from pipeline import execute_portfolio as mod

    seen = {}

    def fake_read(_path):
        return {"fetched_at": 1787600000.0, "markets": []}

    monkeypatch.setattr(
        "syndicate.features.shared.refresh_state_store.read_json_file", fake_read
    )
    mod._polymarket_resolve_market(_Req(venue_ticker))
    return seen


def test_a_dict_venue_ticker_yields_its_SLUG_not_a_stringified_dict(monkeypatch, capsys):
    """`venue_scope.py:190` stamps `ticker_resolver(row)` verbatim, and
    `polymarket_ticker_resolver` returns a dict because `order_body` refuses to
    infer tick size and minimum quantity. `str(a_dict)` is TRUTHY, so the
    no-slug guard never fired and the STRINGIFIED DICT was looked up as a slug --
    matching nothing, every time, on every Polymarket order ever attempted.
    """
    from pipeline import execute_portfolio as mod

    slug = "tsc-mlb-cin-sf-2026-08-25-8pt5"
    monkeypatch.setattr(
        "syndicate.features.shared.refresh_state_store.read_json_file",
        lambda _p: {"fetched_at": 1787600000.0, "markets": []},
    )
    mod._polymarket_resolve_market(
        _Req({"slug": slug, "tick_size": 0.005, "minimum_trade_qty": 0.01})
    )
    out = capsys.readouterr().out

    # The bare slug reached the lookup...
    assert f"slug={slug}" in out
    # ...and NOT the stringified dict, which is what used to get there.
    assert "tick_size" not in out
    assert "POLYMARKET_NO_SLUG" not in out


def test_a_bare_string_venue_ticker_still_works(monkeypatch, capsys):
    """A hand-built request or an older plan stamps a plain slug. Reading the
    dict first must not break that path."""
    from pipeline import execute_portfolio as mod

    slug = "tsc-mlb-cin-sf-2026-08-25-8pt5"
    monkeypatch.setattr(
        "syndicate.features.shared.refresh_state_store.read_json_file",
        lambda _p: {"fetched_at": 1787600000.0, "markets": []},
    )
    mod._polymarket_resolve_market(_Req(slug))
    out = capsys.readouterr().out

    assert f"slug={slug}" in out
    assert "POLYMARKET_NO_SLUG" not in out


def test_a_dict_with_no_slug_refuses_and_SAYS_which_shape_it_saw(monkeypatch, capsys):
    from pipeline import execute_portfolio as mod

    assert mod._polymarket_resolve_market(_Req({"tick_size": 0.005})) is None
    out = capsys.readouterr().out
    assert "POLYMARKET_NO_SLUG" in out
    # The type is on the line, because "unset" and "set to a shape I cannot
    # read" were the same message and are different bugs.
    assert "type=dict" in out


# --- 2. Kalshi: a moneyline has no line, and that made it unkeyable ---------


def test_a_moneyline_is_KEYABLE_on_both_sides():
    """`float(match.get("line"))` in a try/except returned None for an h2h, so
    no ticker was ever stamped and `_kalshi_price_for` refused with
    `no_live_price: None` -- the trailing None being the absent ticker."""
    from syndicate.features.shared.kalshi_board_join import _match_key, _row_key

    match = {"board_event_id": "evt-tex-cws", "market": "h2h",
             "player_name": None, "line": None, "board_side": "home"}
    row = {"event_id": "evt-tex-cws", "market": "h2h", "player_name": None,
           "line": None, "side": "home", "sport": "mlb"}

    assert _match_key(match) is not None
    assert _match_key(match) == _row_key(row)


def test_a_moneyline_ticker_now_resolves_end_to_end():
    from syndicate.features.shared.kalshi_board_join import kalshi_ticker_resolver

    resolve = kalshi_ticker_resolver([{
        "board_event_id": "evt-tex-cws", "ticker": "KXMLBGAME-TEXCWS-TEX",
        "market": "h2h", "player_name": None, "line": None, "board_side": "home",
    }])
    assert resolve({"event_id": "evt-tex-cws", "market": "h2h", "player_name": None,
                    "line": None, "side": "home", "sport": "mlb"}) == "KXMLBGAME-TEXCWS-TEX"


def test_an_UNPARSEABLE_line_still_refuses():
    """"No line" and "a line I could not read" are different facts and only the
    first is safe to key. The first attempt used a module-level NaN sentinel,
    which is wrong: one NaN object matches itself by identity, so two unreadable
    rows would have paired with each other."""
    from syndicate.features.shared.kalshi_board_join import _row_key

    assert _row_key({"event_id": "e1", "market": "h2h", "player_name": None,
                     "line": "not-a-number", "side": "home", "sport": "mlb"}) is None


def test_a_moneyline_in_one_game_does_not_answer_for_another():
    """The reason keying None is safe at all: `#547` put the game first."""
    from syndicate.features.shared.kalshi_board_join import kalshi_ticker_resolver

    resolve = kalshi_ticker_resolver([
        {"board_event_id": "evt-a", "ticker": "KX-A", "market": "h2h",
         "player_name": None, "line": None, "board_side": "home"},
        {"board_event_id": "evt-b", "ticker": "KX-B", "market": "h2h",
         "player_name": None, "line": None, "board_side": "home"},
    ])
    base = {"market": "h2h", "player_name": None, "line": None,
            "side": "home", "sport": "mlb"}
    assert resolve({**base, "event_id": "evt-a"}) == "KX-A"
    assert resolve({**base, "event_id": "evt-b"}) == "KX-B"


# --- 3. One venue, one price source ----------------------------------------


def test_the_aggregators_copy_of_a_direct_feed_venue_is_dropped(capsys):
    """`[USER DECISION 2026-08-25]`. The direct feed writes
    `bookmaker="kalshi"/"polymarket"`; an OddsAPI row under the same name puts a
    second, different number for the same venue into the same de-vig."""
    from syndicate.features.shared.book_grid import freshest_rows_for_grid

    rows = [
        {"bookmaker": "draftkings", "selection": "home", "price": -110},
        {"bookmaker": "kalshi", "selection": "home", "price": -105},
        {"bookmaker": "polymarket", "selection": "home", "price": -108},
        {"bookmaker": "novig", "selection": "home", "price": -102},
        {"bookmaker": "prophetx", "selection": "home", "price": -101},
    ]
    kept = [r["bookmaker"] for r in freshest_rows_for_grid(rows)]

    assert "kalshi" not in kept
    assert "polymarket" not in kept
    # novig and prophetx have NO direct feed, so dropping them would end their
    # paper books entirely. Explicitly kept.
    assert "novig" in kept and "prophetx" in kept
    assert "draftkings" in kept
    # Counted, never silent: whether OddsAPI supplies these at all was an open
    # question, and a zero on this line answers it.
    assert "AGGREGATOR_DUPLICATE_DROPPED rows=2" in capsys.readouterr().out


def test_a_blank_bookmaker_is_kept_because_it_can_still_anchor_a_line():
    """`freshest_rows_for_grid`'s own rule. The permissive direction here KEEPS
    a row, which is the opposite of `is_bettable` and deliberately so."""
    from syndicate.features.shared.book_grid import freshest_rows_for_grid

    kept = freshest_rows_for_grid([{"bookmaker": "", "selection": "home", "price": -110}])
    assert len(kept) == 1


# --- 1b. the layer the first fix MISSED ------------------------------------


def test_the_dict_is_normalised_where_the_ORDER_REQUEST_is_built():
    """`execute_portfolio.py:99` did `str(position.get("venue_ticker"))`, so a
    Polymarket dict became the string "{'slug': ..., 'tick_size': ...}" BEFORE
    any resolver saw it.

    The first fix read the dict inside `_polymarket_resolve_market` -- one layer
    too late, because `str()` had already run and `isinstance(raw, Mapping)` was
    False on a string that merely looked like a dict. MEASURED 2026-08-25
    15:50:40Z, on the deploy that was supposed to have fixed it:

        POLYMARKET_MARKET_NOT_FOUND
          slug={'slug': 'aec-mlb-tex-cws-2026-08-25', 'tick_size': 0.005, ...}

    This pins the boundary, which is where the shape is actually decided.
    """
    from pipeline.execute_portfolio import _venue_ticker_of

    slug = "aec-mlb-tex-cws-2026-08-25"
    assert _venue_ticker_of(
        {"venue_ticker": {"slug": slug, "tick_size": 0.005, "minimum_trade_qty": 0.01}}
    ) == slug
    # Kalshi's string ticker is untouched.
    assert _venue_ticker_of({"venue_ticker": "KXMLBGAME-TEXCWS-TEX"}) == "KXMLBGAME-TEXCWS-TEX"
    assert _venue_ticker_of({}) is None
    # A dict with no slug is not a contract id. Returning "{}" would be the same
    # truthy-garbage bug in a smaller costume.
    assert _venue_ticker_of({"venue_ticker": {"tick_size": 0.005}}) is None


def test_the_normalised_ticker_is_a_STRING_as_its_type_claims():
    """`OrderRequest.venue_ticker` is `str | None`. Storing a dict there worked
    only because Python does not enforce it, and every reader downstream assumed
    the annotation."""
    from pipeline.execute_portfolio import _venue_ticker_of

    got = _venue_ticker_of({"venue_ticker": {"slug": "aec-mlb-tex-cws-2026-08-25"}})
    assert isinstance(got, str)
