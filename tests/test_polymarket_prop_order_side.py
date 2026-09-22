"""Polymarket `gte<N>` player props resolve to an order side, by the slug's grammar.

MEASURED 2026-09-22 15:57:22Z on live-odds-worker, the first Polymarket pass after
`commence_time` stopped masking it:

    POLYMARKET_SIDE_REFUSED slug=astatc-mlb-az-col-2026-09-22-k-micsor-gte5
      market='strikeouts' side='over' reason=yes_no_market_subject_is_not_our_side
      outcomes=['Yes', 'No']

`_polymarket_resolve_market` had branches for totals, spreads and team markets and
NONE for player props. A prop fell into the team matcher (a player is not in
`['Yes','No']`) and then into the soccer subject rule (is the slug's subject our
TEAM?), so every Polymarket player prop refused.

"At least N" is the board's OVER of N-0.5 by the slug's own construction -- the
board join prices it that way (`_prop_probability_for_side`) -- so over buys `Yes`
and under buys `No`. A count has no draw leg, so `No` is exactly the under.
"""
from __future__ import annotations

from syndicate.features.shared.polymarket_us_orders import order_body
from tests.test_execute_portfolio import _artifact_env

SLUG = "astatc-mlb-az-col-2026-09-22-k-micsor-gte5"


def _row(outcomes=("Yes", "No"), prices=("0.52", "0.48"), slug=SLUG, **extra):
    row = {"slug": slug, "outcomes": list(outcomes), "outcomePrices": list(prices),
           "orderPriceMinTickSize": "0.01", "minimumTradeQty": "1", "orderable": True}
    row.update(extra)
    return row


class _PropReq:
    venue_ticker = SLUG
    sport = "mlb"
    market = "strikeouts"
    player_name = "Michael Soroka"
    line = 4.5
    side = "over"
    home_team = "Colorado Rockies"
    away_team = "Arizona Diamondbacks"
    requested_price = 0.52
    requested_stake_dollars = 5.0
    position_key = "pk-soroka-k"
    selected_date = "2026-09-22"
    venue = "polymarket"
    event_id = "afbac30624ec"
    book = None
    segment = None
    commence_time = "2026-09-23T00:40:00Z"


def _resolve(monkeypatch, request=None, **row_kw):
    monkeypatch.setenv("SYNDICATE_POLYMARKET_CROSS_TICKS", "0")
    runner = _artifact_env(monkeypatch, markets=[_row(**row_kw)])
    return runner._polymarket_resolve_market(request or _PropReq())


def _body_for(request, resolved):
    slug, price, tick, min_qty, outcome_index, (yes_leg_index, yes_leg_reason) = resolved
    return order_body(request, market_slug=slug, price_dollars=price, tick_size=tick,
                      minimum_trade_qty=min_qty, outcome_index=outcome_index,
                      yes_leg_index=yes_leg_index, yes_leg_reason=yes_leg_reason)


# ------------------------------------------------------------------ the fix
def test_over_resolves_to_the_yes_outcome_and_a_yes_order(monkeypatch, capsys):
    resolved = _resolve(monkeypatch)
    assert resolved is not None, "the production refusal still fires -- the fix is inert"
    assert resolved[4] == 0 and resolved[5] == (0, "gte_prop_yes_by_name")
    assert abs(resolved[1] - 0.52) < 1e-9, "priced off the Yes outcome"
    body = _body_for(_PropReq(), resolved)
    assert body["outcomeSide"] == "OUTCOME_SIDE_YES"
    assert body["price"]["value"] == "0.52"
    assert "yes_no_market_subject_is_not_our_side" not in capsys.readouterr().out


def test_under_resolves_to_the_no_outcome_and_a_no_order(monkeypatch):
    class _Under(_PropReq):
        side = "under"
        requested_price = 0.48
    resolved = _resolve(monkeypatch, _Under())
    assert resolved is not None
    assert resolved[4] == 1, "No sits at index 1"
    assert abs(resolved[1] - 0.48) < 1e-9, "priced off the No outcome, not Yes"
    body = _body_for(_Under(), resolved)
    assert body["outcomeSide"] == "OUTCOME_SIDE_NO"
    # A NO order is sent at the YES price (1 - 0.48), the venue's convention.
    assert body["price"]["value"] == "0.52"


def test_the_yes_leg_is_found_by_name_when_the_array_is_reversed(monkeypatch):
    resolved = _resolve(monkeypatch, outcomes=("No", "Yes"), prices=("0.48", "0.52"))
    assert resolved is not None
    assert resolved[4] == 1 and resolved[5][0] == 1
    assert abs(resolved[1] - 0.52) < 1e-9


def test_a_batter_prop_resolves_too(monkeypatch):
    class _Hits(_PropReq):
        venue_ticker = "astatc-mlb-sd-cin-2026-09-22-hits-jacmer-gte2"
        market = "batter_hits"
        player_name = "Jackson Merrill"
        line = 1.5
    resolved = _resolve(monkeypatch, _Hits(), slug="astatc-mlb-sd-cin-2026-09-22-hits-jacmer-gte2")
    assert resolved is not None and resolved[4] == 0


def test_a_venue_yes_leg_that_agrees_is_accepted(monkeypatch):
    assert _resolve(monkeypatch, yesLegIndex=0) is not None


# ------------------------------------------------------------ the refusals
def test_a_venue_yes_leg_that_DISAGREES_refuses(monkeypatch, capsys):
    """The venue says the long token is the `No` outcome: buying YES would buy
    the other side. Refused, never guessed."""
    assert _resolve(monkeypatch, yesLegIndex=1) is None
    assert "prop_yes_leg_disagrees_with_venue" in capsys.readouterr().out


def test_a_slug_for_another_line_refuses(monkeypatch, capsys):
    class _Line(_PropReq):
        line = 5.5  # gte5 is over 4.5, not 5.5
    assert _resolve(monkeypatch, _Line()) is None
    assert "prop_slug_line_disagrees" in capsys.readouterr().out


def test_a_slug_for_another_player_refuses(monkeypatch, capsys):
    class _Other(_PropReq):
        player_name = "Payton Tolle"
    assert _resolve(monkeypatch, _Other()) is None
    assert "prop_slug_player_disagrees" in capsys.readouterr().out


def test_a_slug_for_another_market_refuses(monkeypatch, capsys):
    class _Market(_PropReq):
        market = "outs"
    assert _resolve(monkeypatch, _Market()) is None
    assert "prop_slug_market_disagrees" in capsys.readouterr().out


def test_outcomes_that_are_not_yes_no_refuse(monkeypatch, capsys):
    assert _resolve(monkeypatch, outcomes=("Over", "Under")) is None
    assert "prop_outcomes_not_yes_no" in capsys.readouterr().out


def test_a_team_side_on_a_prop_slug_refuses(monkeypatch, capsys):
    class _Home(_PropReq):
        side = "home"
    assert _resolve(monkeypatch, _Home()) is None
    assert "prop_side_not_over_under" in capsys.readouterr().out


def test_game_line_markets_never_take_the_prop_branch():
    import pipeline.execute_portfolio as runner
    assert runner._polymarket_gte_prop("tsc-mlb-cws-kc-2026-09-22-8pt5", "totals") is None
    assert runner._polymarket_gte_prop(SLUG, "strikeouts") == {
        "market": "strikeouts", "token": "micsor", "line": 4.5,
    }
