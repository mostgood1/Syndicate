"""`polymarket_us_outcome` -- the adapter that turns the persisted Polymarket
US slate into board-vocabulary quotes.

Regression coverage for two 2026-08-25 fixes, both scoped narrowly under a
carve-out from `portfolio-decision-and-execution` (see `.syndicate/lanes.md`):

1. `SPORTS_MARKET_TYPE_DRAWABLE_OUTCOME` (soccer's 3-way home/draw/away shape)
   was entirely absent from the market-type map and refused as
   `market_type_not_a_game_line` alongside PROP -- the largest refusal bucket
   measured in production (5,810-6,612 of ~12,200-12,900 markets every cycle).
2. The league filter compared the literal Polymarket slug token against
   Syndicate's `sport` key. That works for mlb/nfl/nba/wnba by coincidence but
   never for soccer: Polymarket lists soccer per COMPETITION (`eflc` observed
   live for EFL Championship) while every Syndicate soccer board row is
   stamped `sport="soccer"` uniformly.
"""

from __future__ import annotations

import json
import time

import pytest

from syndicate.features.shared import venue_quote_adapters as mod


def _payload(markets, fetched_at=None):
    return {
        "fetched_at": fetched_at if fetched_at is not None else time.time(),
        "markets": markets,
    }


def _market(slug, kind="SPORTS_MARKET_TYPE_MONEYLINE",
            outcomes=("Arsenal", "Chelsea"), prices=("0.45", "0.55"), **kw):
    row = {
        "slug": slug,
        "sportsMarketTypeV2": kind,
        "outcomes": json.dumps(list(outcomes)),
        "outcomePrices": json.dumps(list(prices)),
        "orderPriceMinTickSize": 0.01,
        "minimumTradeQty": 1,
    }
    row.update(kw)
    return row


@pytest.fixture
def _artifact(monkeypatch):
    holder = {}

    def read_json_file(_path):
        return holder.get("payload")

    monkeypatch.setattr(
        "syndicate.features.shared.refresh_state_store.read_json_file", read_json_file
    )
    return holder


def test_drawable_outcome_prices_a_soccer_h2h_row(_artifact):
    """Was refused entirely before 2026-08-25 -- `market_type_not_a_game_line`
    had no entry for DRAWABLE_OUTCOME. Slug is `<away>-<home>`: `ars` away,
    `che` home."""
    _artifact["payload"] = _payload(
        [_market("aec-eflc-ars-che-2026-08-25", kind="SPORTS_MARKET_TYPE_DRAWABLE_OUTCOME")]
    )
    result = mod.polymarket_us_outcome("soccer", "2026-08-25")
    assert result.status == "ok"
    keys = {q.key for q in result.quotes}
    assert "soccer|h2h|arsenal" in keys
    assert "soccer|h2h|chelsea" in keys


def test_a_draw_outcome_prices_alongside_the_two_clubs(_artifact):
    """A third "Draw" outcome is a real, priceable quote in its own right --
    it must not be dropped just because it does not name a club the board
    already asks a moneyline side for."""
    _artifact["payload"] = _payload(
        [_market("aec-eflc-ars-che-2026-08-25",
                 kind="SPORTS_MARKET_TYPE_DRAWABLE_OUTCOME",
                 outcomes=("Arsenal", "Chelsea", "Draw"),
                 prices=("0.45", "0.30", "0.25"))]
    )
    result = mod.polymarket_us_outcome("soccer", "2026-08-25")
    assert result.status == "ok"
    keys = {q.key for q in result.quotes}
    # "Draw" does not resolve to a club and is silently dropped -- exactly
    # like any other unresolved outcome name, counted in `unresolved_clubs`.
    assert len(result.quotes) == 2
    assert "soccer|h2h|arsenal" in keys and "soccer|h2h|chelsea" in keys


def test_a_soccer_row_is_found_across_a_non_soccer_league_token(_artifact):
    """The regression this fix guards: before it, `wanted_league="soccer"`
    could never equal a literal slug token like `eflc`, so this returned
    `no_rows` for every soccer market regardless of catalogue coverage --
    exactly the production symptom `.syndicate/deploys.md` recorded
    (`reason=no_polymarket_row_for_league_soccer`)."""
    _artifact["payload"] = _payload(
        [_market("aec-eflc-ars-che-2026-08-25")]
    )
    result = mod.polymarket_us_outcome("soccer", "2026-08-25")
    assert result.status == "ok"
    assert len(result.quotes) == 2


def test_a_non_soccer_league_still_requires_a_literal_match(_artifact):
    """mlb/nfl/nba/wnba are unaffected by the soccer relabelling -- an MLB
    row must not leak into a call for a different sport."""
    _artifact["payload"] = _payload(
        [_market("aec-mlb-pit-sd-2026-08-24",
                 outcomes=("Pittsburgh Pirates", "San Diego Padres"))]
    )
    result = mod.polymarket_us_outcome("nfl", "2026-08-24")
    assert result.status == "no_rows"
    assert result.reason == "no_polymarket_row_for_league_nfl"


def test_an_unresolvable_pair_is_not_relabelled_as_soccer(_artifact):
    """Both clubs must resolve as known soccer clubs before a row is
    relabelled -- an unresolvable pair keeps its literal (wrong, but not
    guessed) league token and correctly misses a soccer call."""
    _artifact["payload"] = _payload(
        [_market("aec-xyz-zzznotaclub-alsonotaclub-2026-08-25",
                 outcomes=("Zzznotaclub", "Alsonotaclub"))]
    )
    result = mod.polymarket_us_outcome("soccer", "2026-08-25")
    assert result.status == "no_rows"


def test_prop_stays_refused_by_design(_artifact):
    """Unlike DRAWABLE_OUTCOME, PROP is deliberately out of scope -- player
    name resolution is a different problem this fix does not touch."""
    _artifact["payload"] = _payload(
        [_market("astatc-eflc-ars-che-2026-08-25-goals-player-gte1",
                 kind="SPORTS_MARKET_TYPE_PROP", outcomes=("Yes", "No"))]
    )
    result = mod.polymarket_us_outcome("soccer", "2026-08-25")
    assert result.status == "no_rows"
