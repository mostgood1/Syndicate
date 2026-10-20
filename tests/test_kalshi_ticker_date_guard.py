"""A live Kalshi order must carry a ticker dated for its own game (user: "Guard + fix the join").

Reachability first: the REAL wrong-game pair from the 2026-10-20 audit
(`UM @ TRO` on 10-24 carrying `KXNCAAFGAME-26OCT29TROYJMU-TROY`) is SENT with the
guard off and refused by name, with nothing written, with it on.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared import kalshi_ticker_date_guard as G
from syndicate.features.shared.execution_ledger import ledger_summary
from syndicate.features.shared.portfolio_settings import PortfolioSettings

_DATE = "2026-10-24"
_WRONG_GAME = "KXNCAAFGAME-26OCT29TROYJMU-TROY"  # measured on the board, 10-20
_RIGHT_GAME = "KXNCAAFGAME-26OCT24UMTROY-TROY"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path))
    for key in (
        "SYNDICATE_EXECUTION_ENABLED",
        "SYNDICATE_EXECUTION_MODE",
        "SYNDICATE_EXECUTION_LIVE_ARMED",
        "SYNDICATE_EXECUTION_VENUE",
        "SYNDICATE_PORTFOLIO_COMMIT_ENABLED",
        "SYNDICATE_REFRESH_STATE_BACKEND",
        "SYNDICATE_EXECUTION_TICKER_DATE_GUARD",
        "SYNDICATE_EXECUTION_BALANCE_CAPS",
    ):
        monkeypatch.delenv(key, raising=False)
    yield


def _row(**overrides):
    row = {
        "sport": "ncaaf",
        "event_id": "evt-um-tro",
        "kind": "game",
        "market": "h2h",
        "segment": "full_game",
        "line": None,
        "player_name": None,
        "home_team": "Troy",
        "away_team": "UM",
        "commence_time": "2026-10-24T19:00:00Z",  # 3 PM ET Saturday
        "side": "home",
        "quote": {"price": -150, "bookmaker": "kalshi"},
        "ev_pct": 3.5,
        "model_edge_pct": 2.0,
        "score": {"score": 5.1, "price_reliability": 0.82},
        "venue_ticker": _WRONG_GAME,
    }
    row.update(overrides)
    return row


def _run(monkeypatch, row, *, switch=None, venue="kalshi"):
    from pipeline import execute_portfolio as runner
    from pipeline import portfolio_commit as commit

    monkeypatch.setenv("SYNDICATE_PORTFOLIO_COMMIT_ENABLED", "1")
    monkeypatch.setattr(
        "pipeline.intelligence_state.read_layer2_shortlist", lambda date: {"rows": [{**row, "suggested": True}]}
    )
    monkeypatch.setattr(
        "syndicate.features.shared.portfolio_commit.resolve_settings",
        lambda: PortfolioSettings(
            bankroll_units=1000.0, max_slate_exposure_fraction=1.0, min_ev_pct=-100.0,
            max_positions=50, min_stake_units=0.0,
        ),
    )
    result = commit.run_portfolio_commit(_DATE)
    assert result["status"] == "ok", result
    plan = result["plan"]
    monkeypatch.setattr("pipeline.portfolio_commit.read_portfolio_plan_for_venue", lambda date, scope: plan)
    monkeypatch.setattr("pipeline.portfolio_commit.read_live_portfolio_plan_for_venue", lambda date, scope: plan)
    monkeypatch.setenv("SYNDICATE_EXECUTION_ENABLED", "1")
    monkeypatch.setenv("SYNDICATE_EXECUTION_MODE", "live")
    monkeypatch.setenv("SYNDICATE_EXECUTION_LIVE_ARMED", "1")
    monkeypatch.setenv("SYNDICATE_EXECUTION_VENUE", venue)
    monkeypatch.setenv("SYNDICATE_EXECUTION_MAX_ORDER_DOLLARS", "1000")
    monkeypatch.setenv("SYNDICATE_EXECUTION_MAX_DAY_DOLLARS", "10000")
    if switch is not None:
        monkeypatch.setenv("SYNDICATE_EXECUTION_TICKER_DATE_GUARD", switch)
    sent: list = []

    def submitter(request):
        sent.append(request)
        return {"status": "filled", "fill_price": 0.6, "fill_stake_dollars": request.requested_stake_dollars}

    monkeypatch.setattr(runner, "_venue_submitter", lambda v: submitter)
    return runner.run_execution(_DATE, venue_scope=venue), sent


# --------------------------------------------------------------------------
# Reachability -- off != on, on the REAL wrong-game pair
# --------------------------------------------------------------------------


def test_off_the_wrong_game_ticker_is_SENT(monkeypatch):
    result, sent = _run(monkeypatch, _row(), switch="off")
    assert len(sent) == 1
    assert sent[0].venue_ticker == _WRONG_GAME
    assert "ticker_date_mismatch" not in result["refused"]


def test_on_the_wrong_game_ticker_is_refused_by_name_and_nothing_is_written(monkeypatch, capsys):
    result, sent = _run(monkeypatch, _row())  # default ON
    assert sent == []
    assert result["refused"] == {"ticker_date_mismatch": 1}
    assert ledger_summary(_DATE)["orders"] == 0
    out = capsys.readouterr().out
    assert "REFUSED_TICKER_DATE_MISMATCH venue=kalshi ticker='KXNCAAFGAME-26OCT29TROYJMU-TROY'" in out
    assert "away='UM' home='Troy'" in out
    assert "detail=ticker=2026-10-29 eastern=2026-10-24" in out


def test_on_the_right_game_ticker_is_placed(monkeypatch):
    result, sent = _run(monkeypatch, _row(venue_ticker=_RIGHT_GAME))
    assert len(sent) == 1
    assert result["refused"] == {}


def test_on_a_missing_commence_time_is_refused_fail_closed(monkeypatch, capsys):
    result, sent = _run(monkeypatch, _row(venue_ticker=_RIGHT_GAME, commence_time=None))
    assert sent == []
    assert result["refused"] == {"ticker_date_unverifiable": 1}
    assert "REFUSED_TICKER_DATE_UNVERIFIABLE" in capsys.readouterr().out


def test_polymarket_is_not_touched(monkeypatch):
    # The guard reads Kalshi's ticker grammar; a Polymarket order goes past it.
    from pipeline import execute_portfolio as runner

    calls: list = []
    monkeypatch.setattr(G, "ticker_date_refusal", lambda *a, **k: calls.append(a) or ("ticker_date_mismatch", "x"))
    _run(monkeypatch, _row(), venue="polymarket")
    assert calls == []


# --------------------------------------------------------------------------
# The date rule itself
# --------------------------------------------------------------------------


def test_an_evening_game_whose_UTC_date_is_the_next_day_matches_on_eastern():
    # 8:30 PM ET Saturday is 00:30Z Sunday: the ticker says Saturday, and so does Eastern.
    assert G.ticker_date_refusal("KXNCAAFGAME-26OCT24UMTROY-TROY", "2026-10-25T00:30:00Z")[0] is None


def test_mlb_tickers_with_a_start_time_parse():
    assert G.ticker_date_refusal("KXMLBRBI-26OCT192008CLETB-TBYDIAZ2-1", "2026-10-20T00:08:00Z")[0] is None


@pytest.mark.parametrize(
    "ticker",
    [
        "KXMVECROSSCATEGORY-S2026BCABC393E3F-E1FE58B60F9",  # no date segment by design: refused, not exempted
        "KXNCAAFGAME",
        "",
        None,
        "KXNCAAFGAME-26FEB30UMTROY-TROY",  # a date shape that is not a date
    ],
)
def test_no_parseable_date_is_unverifiable(ticker):
    assert G.ticker_date_refusal(ticker, "2026-10-24T19:00:00Z")[0] == "ticker_date_unverifiable"


def test_eastern_unavailable_falls_back_to_utc_or_the_day_before(monkeypatch):
    monkeypatch.setattr(G, "_eastern_date", lambda moment: None)
    assert G.ticker_date_refusal("KXNCAAFGAME-26OCT24UMTROY-TROY", "2026-10-25T00:30:00Z")[0] is None  # day before
    assert G.ticker_date_refusal("KXNCAAFGAME-26OCT24UMTROY-TROY", "2026-10-24T19:00:00Z")[0] is None  # same UTC day
    reason, detail = G.ticker_date_refusal("KXNCAAFGAME-26OCT29TROYJMU-TROY", "2026-10-24T19:00:00Z")
    assert reason == "ticker_date_mismatch" and "eastern_unavailable" in detail


def test_the_switch_off_disables_the_rule_itself(monkeypatch):
    monkeypatch.setenv("SYNDICATE_EXECUTION_TICKER_DATE_GUARD", "off")
    assert G.ticker_date_refusal(_WRONG_GAME, "2026-10-24T19:00:00Z") == (None, "guard_off")
