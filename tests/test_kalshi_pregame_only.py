"""A live Kalshi ENTRY is refused once its game has started (user: "Block after kickoff").

Measured 2026-10-20: a plan built at 23:02:14Z placed KXNCAAFSPREAD-26OCT20MOSUDEL-DEL4
(11 @0.50) and DEL3 at 23:07-23:09Z, after a 23:00Z kickoff, on pregame fair prices.
Reachability first: the same after-kickoff position is SENT with the switch off and
refused by name, with nothing written, with it on.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from syndicate.features.shared.execution_ledger import ledger_summary
from syndicate.features.shared.portfolio_settings import PortfolioSettings

_DATE = "2026-10-20"
_TICKER = "KXNCAAFSPREAD-26OCT20MOSUDEL-DEL4"


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
        "SYNDICATE_EXECUTION_KALSHI_PREGAME_ONLY",
        "SYNDICATE_EXECUTION_TICKER_DATE_GUARD",
        "SYNDICATE_EXECUTION_BALANCE_CAPS",
    ):
        monkeypatch.delenv(key, raising=False)
    # The ticker-date guard is not under test here; its own file covers it.
    monkeypatch.setenv("SYNDICATE_EXECUTION_TICKER_DATE_GUARD", "off")
    yield


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _row(**overrides):
    row = {
        "sport": "ncaaf",
        "event_id": "evt-mosu-del",
        "kind": "game",
        "market": "spreads",
        "segment": "full_game",
        "line": -3.5,
        "player_name": None,
        "home_team": "Delaware Blue Hens",
        "away_team": "Missouri State Bears",
        "commence_time": _iso(datetime.now(timezone.utc) - timedelta(minutes=7)),  # kicked off 7 min ago
        "side": "home",
        "quote": {"price": 100, "bookmaker": "kalshi"},
        "ev_pct": 3.5,
        "model_edge_pct": 2.0,
        "score": {"score": 5.1, "price_reliability": 0.82},
        "venue_ticker": _TICKER,
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
        monkeypatch.setenv("SYNDICATE_EXECUTION_KALSHI_PREGAME_ONLY", switch)
    sent: list = []

    def submitter(request):
        sent.append(request)
        return {"status": "filled", "fill_price": 0.5, "fill_stake_dollars": request.requested_stake_dollars}

    monkeypatch.setattr(runner, "_venue_submitter", lambda v: submitter)
    return runner.run_execution(_DATE, venue_scope=venue), sent


# --------------------------------------------------------------------------
# Reachability -- off != on, the measured case (7 min after kickoff)
# --------------------------------------------------------------------------


def test_off_an_entry_after_kickoff_is_SENT(monkeypatch):
    result, sent = _run(monkeypatch, _row(), switch="off")
    assert len(sent) == 1
    assert "game_started" not in result["refused"]


def test_on_an_entry_after_kickoff_is_refused_by_name_and_nothing_is_written(monkeypatch, capsys):
    result, sent = _run(monkeypatch, _row())  # default ON
    assert sent == []
    assert result["refused"] == {"game_started": 1}
    assert ledger_summary(_DATE)["orders"] == 0
    out = capsys.readouterr().out
    assert "REFUSED_AFTER_COMMENCE venue=kalshi reason=game_started" in out
    assert f"ticker='{_TICKER}'" in out


def test_on_a_pregame_entry_is_placed(monkeypatch):
    later = _iso(datetime.now(timezone.utc) + timedelta(hours=3))
    result, sent = _run(monkeypatch, _row(commence_time=later))
    assert len(sent) == 1
    assert result["refused"] == {}


@pytest.mark.parametrize("commence", [None, "", "not-a-time"])
def test_on_an_unknown_kickoff_is_refused(monkeypatch, commence):
    result, sent = _run(monkeypatch, _row(commence_time=commence))
    assert sent == []
    assert result["refused"] == {"commence_unknown": 1}


def test_exactly_at_kickoff_is_started(monkeypatch):
    # Polymarket's rule is `now >= commence`: kickoff itself is in-play.
    from syndicate.features.shared import polymarket_us_orders as P

    start = datetime(2026, 10, 20, 23, 0, tzinfo=timezone.utc)

    class _R:
        commence_time = "2026-10-20T23:00:00Z"

    with pytest.raises(P.OrderBuildError, match="^game_started"):
        P._refuse_after_commence(_R(), now=start)


def test_polymarket_entries_do_not_pass_through_this_block(monkeypatch, capsys):
    # Polymarket refuses after commence inside its own builder; this block is Kalshi's.
    _run(monkeypatch, _row(venue_ticker=None), venue="polymarket")
    assert "REFUSED_AFTER_COMMENCE" not in capsys.readouterr().out
