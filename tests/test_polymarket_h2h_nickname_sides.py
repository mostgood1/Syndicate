"""Polymarket writes college h2h outcomes as SCHOOL NICKNAMES, and the money path
could not read them.

MEASURED 2026-09-23 on live-odds-worker: `h2h` built 12 of 58 position-passes;
29 refusals that day were

    POLYMARKET_SIDE_REFUSED slug=aec-cfb-col-bayl-2026-09-26 market='h2h'
      side='home' reason=team_side_not_in_outcomes outcomes=['Buffaloes', 'Bears']

with ZERO `MARKET_NOT_FOUND` / `NO_SLUG` / `ARTIFACT_STALE` / `NOT_ORDERABLE` /
`OUTCOMES_UNREADABLE` -- the slug was in the slate and the resolver simply could
not name our side. Against that row `kalshi_board_join._side_for_team` returns
None for 'Buffaloes', 'Bears' AND both full names, while the BOARD JOIN's own
`team_aliases.teams_match` -- the matcher that chose the slug -- returns away and
home, each uniquely. Two matchers, the money path holding the weaker one: the
`#683` shape one market over.

THE SAFETY PROPERTY IS UNIQUENESS, not the nicknames. An outcome name that
resolves to BOTH board teams must refuse: a team side picked by guess is what
bought TEXAS at the White Sox's price on 2026-08-25.
"""
from __future__ import annotations

import pytest

from tests.test_execute_portfolio import _artifact_env

SLUG = "aec-cfb-col-bayl-2026-09-26"


def _row(outcomes=("Buffaloes", "Bears"), prices=("0.62", "0.38"), slug=SLUG, **extra):
    row = {"slug": slug, "outcomes": list(outcomes), "outcomePrices": list(prices),
           "orderPriceMinTickSize": "0.01", "minimumTradeQty": "1", "orderable": True}
    row.update(extra)
    return row


class _CfbReq:
    """Colorado @ Baylor, and we want the HOME side -- verbatim from the plan."""

    venue_ticker = SLUG
    sport = "ncaaf"
    market = "h2h"
    side = "home"
    home_team = "Baylor Bears"
    away_team = "Colorado Buffaloes"
    line = None
    player_name = None
    requested_price = 0.38
    requested_stake_dollars = 5.0
    position_key = "pk-col-bayl"
    selected_date = "2026-09-23"
    venue = "polymarket"
    event_id = "evt-cfb-1"
    book = None
    segment = None
    commence_time = "2026-09-27T00:00:00Z"


def _resolve(monkeypatch, request=None, **row_kw):
    monkeypatch.setenv("SYNDICATE_POLYMARKET_CROSS_TICKS", "0")
    runner = _artifact_env(monkeypatch, markets=[_row(**row_kw)])
    return runner._polymarket_resolve_market(request or _CfbReq())


# --------------------------------------------------------------------- the fix
def test_a_nickname_only_h2h_resolves_to_our_side(monkeypatch):
    resolved = _resolve(monkeypatch)
    assert resolved is not None, "the production refusal still fires -- the fix is inert"
    assert resolved[4] == 1, "'Bears' is our home team, at index 1"
    assert abs(resolved[1] - 0.38) < 1e-9, "priced off OUR outcome, not the opponent's"


def test_the_away_nickname_resolves_too(monkeypatch):
    class _Away(_CfbReq):
        side = "away"
        requested_price = 0.62
    resolved = _resolve(monkeypatch, _Away())
    assert resolved is not None and resolved[4] == 0
    assert abs(resolved[1] - 0.62) < 1e-9


def test_the_corroborating_away_index_is_now_fed(monkeypatch, capsys):
    """These rows used to refuse BEFORE reaching the yes-leg gate, so the
    corroborator had no witness on them at all."""
    _resolve(monkeypatch, yesLegIndex=0)
    out = capsys.readouterr().out
    assert "POLYMARKET_YES_LEG" in out and "away_index=0" in out


def test_a_venue_yes_leg_that_disagrees_still_refuses(monkeypatch, capsys):
    """The gate keeps working on the markets the fix newly admits: the venue
    says the YES leg is our HOME index while our board says away sits there."""
    assert _resolve(monkeypatch, yesLegIndex=1) is None
    assert "yes_leg_disagrees_with_away_index" in capsys.readouterr().out


# ------------------------------------------------------- the safety property
def test_an_outcome_matching_BOTH_teams_refuses(monkeypatch, capsys):
    """UNIQUE OR NOTHING. Two board teams resolving from one outcome name is
    exactly the ambiguity that must not become a real order."""
    class _Same(_CfbReq):
        home_team = "Baylor Bears"
        away_team = "Baylor Bears"
    assert _resolve(monkeypatch, _Same()) is None
    assert "team_side_not_in_outcomes" in capsys.readouterr().out


def test_a_row_with_no_team_names_refuses(monkeypatch):
    class _NoTeams(_CfbReq):
        home_team = None
        away_team = None
    assert _resolve(monkeypatch, _NoTeams()) is None


def test_an_unrelated_nickname_refuses(monkeypatch):
    assert _resolve(monkeypatch, outcomes=("Gophers", "Badgers")) is None


# ------------------------------------------------- the path that already worked
def test_full_team_names_are_untouched(monkeypatch):
    """MLB h2h resolves through `_side_for_team` and must not change: the
    fallback is only consulted when the first matcher says nothing."""
    from tests.test_execute_portfolio import _PolyReq, _polymarket_row

    runner = _artifact_env(monkeypatch, markets=[
        _polymarket_row(teams=("White Sox", "Rangers"), prices=("0.55", "0.45"))])
    resolved = runner._polymarket_resolve_market(_PolyReq())
    assert resolved is not None and resolved[4] == 0


@pytest.mark.parametrize("name,expected", [("Bears", "home"), ("Buffaloes", "away"), ("Tigers", None)])
def test_the_helper_reports_one_side_or_none(name, expected):
    import pipeline.execute_portfolio as runner

    resolution = {"home_team": "Baylor Bears", "away_team": "Colorado Buffaloes"}
    assert runner._polymarket_team_side(name, resolution, "ncaaf") == expected


def test_the_helper_is_loud_if_the_matcher_cannot_be_imported(monkeypatch, capsys):
    """A swallowed ImportError is how a fallback becomes permanently inert
    while its tests still pass -- they assert a refusal, and everything refuses."""
    import builtins

    import pipeline.execute_portfolio as runner

    real = builtins.__import__

    def _boom(name, *args, **kw):
        if name.endswith("team_aliases"):
            raise ImportError("no team_aliases")
        return real(name, *args, **kw)

    monkeypatch.setattr(builtins, "__import__", _boom)
    assert runner._polymarket_team_side("Bears", {"home_team": "Baylor Bears", "away_team": "X"}, "ncaaf") is None
    assert "TEAM_ALIAS_MATCHER_UNAVAILABLE" in capsys.readouterr().out
