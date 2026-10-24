"""Polymarket signed spreads resolve to an order side -- behind a switch, on the
venue's REAL shapes, refusing (never flipping) on any disagreement.

Shapes are the fleet slate's (2026-10-24T00:3xZ) and the polarity is the venue
catalogue's (`marketSides[i].team` / `.long`, 1,442 of 1,442 sides over 10
events): `outcomes[0]` is the slug's FIRST club at the slug's signed line and is
the YES (`long`) leg; `outcomes[1]` is the second club at the opposite sign.

    asc-nba-min-orl-2026-10-23-neg-12pt5  outcomes ["-12.50","+12.50"]
      MIN (away, slug-first) -12.5 = YES     ORL (home) +12.5 = NO

`SYNDICATE_POLYMARKET_SPREAD_ORDERS` absent = today's refusal; that is the
reachability pair (off != on).
"""
from __future__ import annotations

import pytest

from syndicate.features.shared.polymarket_us_orders import order_body
from tests.test_execute_portfolio import _artifact_env

NEG = "asc-nba-min-orl-2026-10-23-neg-12pt5"
POS = "asc-nba-min-orl-2026-10-23-pos-12pt5"


def _row(slug=NEG, outcomes=("-12.50", "+12.50"), prices=("0.32", "0.71"), **extra):
    row = {"slug": slug, "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_SPREAD",
           "outcomes": list(outcomes), "outcomePrices": list(prices),
           "line": -12.5 if "-neg-" in slug else 12.5,
           "orderPriceMinTickSize": "0.01", "minimumTradeQty": "0.01",
           "orderable": True, "yesLegIndex": 0, "yesLegReason": None}
    row.update(extra)
    return row


def _req(side="away", line=-12.5, slug=NEG, price=0.32, **over):
    attrs = dict(
        venue_ticker=slug, sport="nba", market="spreads", player_name=None,
        line=line, side=side, home_team="Orlando Magic",
        away_team="Minnesota Timberwolves", requested_price=price,
        requested_stake_dollars=5.0, position_key=f"pk-{side}-{line}",
        selected_date="2026-10-23", venue="polymarket",
        event_id="7763ba1c6e1e163be38cbe1b880d4cd9", book=None, segment=None,
        commence_time="2026-10-23T23:10:00Z",
    )
    attrs.update(over)
    return type("SpreadReq", (), attrs)()


def _resolve(monkeypatch, request, *, on=True, **row_kw):
    monkeypatch.setenv("SYNDICATE_POLYMARKET_CROSS_TICKS", "0")
    if on:
        monkeypatch.setenv("SYNDICATE_POLYMARKET_SPREAD_ORDERS", "on")
    else:
        monkeypatch.delenv("SYNDICATE_POLYMARKET_SPREAD_ORDERS", raising=False)
    runner = _artifact_env(monkeypatch, markets=[_row(**row_kw)])
    return runner._polymarket_resolve_market(request)


def _body(request, resolved):
    slug, price, tick, min_qty, outcome_index, (yes_leg_index, yes_leg_reason) = resolved
    return order_body(request, market_slug=slug, price_dollars=price, tick_size=tick,
                      minimum_trade_qty=min_qty, outcome_index=outcome_index,
                      yes_leg_index=yes_leg_index, yes_leg_reason=yes_leg_reason)


# ------------------------------------------------------------- reachability
def test_absent_switch_keeps_todays_refusal(monkeypatch, capsys):
    assert _resolve(monkeypatch, _req(), on=False) is None
    assert "reason=spread_side_needs_verified_team_mapping" in capsys.readouterr().out


def test_switch_on_resolves_the_same_row(monkeypatch):
    assert _resolve(monkeypatch, _req()) is not None, "the switch is inert"


# ------------------------------------------------------------- the rule
def test_away_slug_first_club_buys_yes_at_its_own_handicap(monkeypatch):
    request = _req("away", -12.5)
    resolved = _resolve(monkeypatch, request)
    assert resolved[0] == NEG
    assert resolved[4] == 0 and resolved[5] == (0, "signed_spread_slot")
    assert abs(resolved[1] - 0.32) < 1e-9
    assert _body(request, resolved)["outcomeSide"] == "OUTCOME_SIDE_YES"


def test_home_second_club_buys_no_on_the_market_stating_the_other_sign(monkeypatch):
    request = _req("home", 12.5, price=0.71)
    resolved = _resolve(monkeypatch, request)
    assert resolved is not None
    assert resolved[4] == 1
    assert abs(resolved[1] - 0.71) < 1e-9, "priced off ORL's +12.50, not MIN's -12.50"
    body = _body(request, resolved)
    assert body["outcomeSide"] == "OUTCOME_SIDE_NO"


def test_a_team_name_side_maps_to_its_slot(monkeypatch):
    request = _req("Orlando Magic", 12.5, price=0.71)
    resolved = _resolve(monkeypatch, request)
    assert resolved is not None and resolved[4] == 1


# ------------------------------------------- the opposite-side guard: refuse, never flip
@pytest.mark.parametrize(
    "request_kw, row_kw, reason",
    [
        # ORL +12.5 sent to `pos-12pt5`, where +12.5 is MIN's handicap.
        (dict(side="home", line=12.5, slug=POS, price=0.06),
         dict(slug=POS, outcomes=("+12.50", "-12.50"), prices=("0.95", "0.06")),
         "spread_slug_line_is_not_our_clubs_line"),
        # Outcome array reordered against the slug's own sign.
        (dict(side="away", line=-12.5),
         dict(outcomes=("+12.50", "-12.50"), prices=("0.71", "0.32")),
         "spread_outcome_in_our_slot_is_not_our_line"),
        # Our clubs the other way round from the slug.
        (dict(side="away", line=-12.5, home_team="Minnesota Timberwolves", away_team="Orlando Magic"),
         {}, "spread_slug_clubs_are_not_our_away_home"),
        # A quarter spread is not the game's.
        (dict(side="away", line=-2.5, slug="asc-nba-min-orl-2026-10-23-q4-neg-2pt5"),
         dict(slug="asc-nba-min-orl-2026-10-23-q4-neg-2pt5", outcomes=("-2.50", "+2.50")),
         "spread_slug_is_a_segment"),
        # A league whose spreads were not in the measurement.
        (dict(side="away", line=-3.5, slug="asc-ncaab-duke-unc-2026-11-20-neg-3pt5", sport="ncaab",
              home_team="North Carolina Tar Heels", away_team="Duke Blue Devils"),
         dict(slug="asc-ncaab-duke-unc-2026-11-20-neg-3pt5", outcomes=("-3.50", "+3.50")),
         "spread_side_needs_verified_team_mapping"),
    ],
)
def test_a_wrong_mapping_refuses(monkeypatch, capsys, request_kw, row_kw, reason):
    assert _resolve(monkeypatch, _req(**request_kw), **row_kw) is None
    assert f"reason={reason}" in capsys.readouterr().out


@pytest.mark.parametrize("venue_yes", [1, None, "x"])
def test_venue_yes_leg_must_be_the_slug_first_leg(monkeypatch, capsys, venue_yes):
    assert _resolve(monkeypatch, _req(), yesLegIndex=venue_yes) is None
    assert "reason=spread_yes_leg_is_not_the_slug_first_leg" in capsys.readouterr().out
