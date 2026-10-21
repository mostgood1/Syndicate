"""One venue contract, one live order -- whatever the plan calls it (2026-10-21).

Measured on the fleet: KXNBASPREAD-26OCT21DALHOU-HOU10 (away 9.5) bought twice,
11 s apart, from two plan rows labelled `spreads` and `spreads_alt`. Position
identity hashes `market`, so the duplicate check and D1 both missed it.
Reachability first: the same pair SENDS twice with the switch off and once, with
the second refused by name, with it on.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared import execution_ledger as L
from syndicate.features.shared.portfolio_settings import PortfolioSettings

# Far-future, so the ticker-date guard (ticker 99OCT21 == Eastern date of the
# commence) and the after-kickoff block both pass on any day this test runs.
_DATE = "2099-10-21"
_TICKER = "KXNBASPREAD-99OCT21DALHOU-HOU10"
_COMMENCE = "2099-10-22T00:30:00Z"  # 8:30 PM ET 10-21


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
        "SYNDICATE_EXECUTION_VENUE_CONTRACT_DEDUPE",
        "SYNDICATE_EXECUTION_BALANCE_CAPS",
        "SYNDICATE_LIVE_EVENT_CONCENTRATION",
    ):
        monkeypatch.delenv(key, raising=False)
    yield


def _row(market, **overrides):
    row = {
        "sport": "nba",
        "event_id": "evt-dal-hou",
        "kind": "game",
        "market": market,
        "segment": "full_game",
        "line": 9.5,
        "player_name": None,
        "home_team": "Houston Rockets",
        "away_team": "Dallas Mavericks",
        "commence_time": _COMMENCE,
        "side": "away",
        "quote": {"price": 104, "bookmaker": "kalshi"},
        "ev_pct": 3.0,
        "model_edge_pct": 1.0,
        "score": {"score": 5.0, "price_reliability": 0.8},
        "venue_ticker": _TICKER,
    }
    row.update(overrides)
    return row


def _run(monkeypatch, rows, *, switch=None, extra_label=None):
    from pipeline import execute_portfolio as runner
    from pipeline import portfolio_commit as commit

    monkeypatch.setenv("SYNDICATE_PORTFOLIO_COMMIT_ENABLED", "1")
    monkeypatch.setattr(
        "pipeline.intelligence_state.read_layer2_shortlist", lambda date: {"rows": [{**r, "suggested": True} for r in rows]}
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
    if extra_label:
        # The fleet's plan held BOTH labels staked; the sizer here shrinks a second
        # row on the same line below the minimum, so the twin is built from the first
        # position with the other `market` and its own identity, as on the fleet.
        from syndicate.features.shared.portfolio_commit import position_key as _pk

        first = plan["positions"][0]
        twin = dict(first, market=extra_label)
        twin["position_key"] = _pk({**rows[0], "market": extra_label})
        plan["positions"] = [first, twin]
        assert first["position_key"] != twin["position_key"]
    assert len(plan["positions"]) == len(rows) + (1 if extra_label else 0), plan.get("refusals")
    monkeypatch.setattr("pipeline.portfolio_commit.read_portfolio_plan_for_venue", lambda date, scope: plan)
    monkeypatch.setattr("pipeline.portfolio_commit.read_live_portfolio_plan_for_venue", lambda date, scope: plan)
    monkeypatch.setenv("SYNDICATE_EXECUTION_ENABLED", "1")
    monkeypatch.setenv("SYNDICATE_EXECUTION_MODE", "live")
    monkeypatch.setenv("SYNDICATE_EXECUTION_LIVE_ARMED", "1")
    monkeypatch.setenv("SYNDICATE_EXECUTION_VENUE", "kalshi")
    monkeypatch.setenv("SYNDICATE_EXECUTION_MAX_ORDER_DOLLARS", "1000")
    monkeypatch.setenv("SYNDICATE_EXECUTION_MAX_DAY_DOLLARS", "10000")
    if switch is not None:
        monkeypatch.setenv("SYNDICATE_EXECUTION_VENUE_CONTRACT_DEDUPE", switch)
    sent: list = []

    def submitter(request):
        sent.append(request)
        return {"status": "filled", "fill_price": 0.49, "fill_stake_dollars": request.requested_stake_dollars}

    monkeypatch.setattr(runner, "_venue_submitter", lambda v: submitter)
    return runner.run_execution(_DATE, venue_scope="kalshi"), sent


# --------------------------------------------------------------------------
# Reachability -- off != on, the measured pair
# --------------------------------------------------------------------------


def test_off_spreads_and_spreads_alt_on_one_ticker_are_BOTH_sent(monkeypatch):
    result, sent = _run(monkeypatch, [_row("spreads_alt")], switch="off", extra_label="spreads")
    assert len(sent) == 2
    assert {r.venue_ticker for r in sent} == {_TICKER}
    assert "already_held_venue_contract" not in result["refused"]


def test_on_the_second_label_is_refused_by_name_and_nothing_is_written(monkeypatch, capsys):
    result, sent = _run(monkeypatch, [_row("spreads_alt")], extra_label="spreads")  # default ON
    assert len(sent) == 1
    assert result["refused"] == {"already_held_venue_contract": 1}
    live = [o for o in L._load().get("orders") or [] if o.get("mode") == "live"]
    assert len(live) == 1
    out = capsys.readouterr().out
    assert f"REFUSED_HELD_VENUE_CONTRACT venue=kalshi ticker='{_TICKER}'" in out


def test_a_rerun_of_the_same_bet_is_still_a_duplicate_not_this_refusal(monkeypatch):
    from pipeline import execute_portfolio as runner

    result, sent = _run(monkeypatch, [_row("spreads")])
    again = runner.run_execution(_DATE, venue_scope="kalshi")
    assert len(sent) == 1
    assert again["duplicates"] == 1
    assert "already_held_venue_contract" not in again["refused"]


# --------------------------------------------------------------------------
# What counts as the same contract
# --------------------------------------------------------------------------


def _request(**overrides):
    fields = dict(
        position_key="pk-new", selected_date=_DATE, venue="kalshi", sport="nba", event_id="evt-dal-hou",
        market="spreads", side="away", requested_price=0.49, requested_stake_dollars=0.5, line=9.5,
        venue_ticker=_TICKER, commence_time=_COMMENCE,
    )
    fields.update(overrides)
    return L.OrderRequest(**fields)


def _held(**overrides):
    row = {
        "mode": "live", "venue": "kalshi", "venue_ticker": _TICKER, "market": "spreads_alt", "side": "away",
        "line": 9.5, "selected_date": "2099-10-20", "status": "filled", "error": None, "idempotency_key": "other-key",
    }
    row.update(overrides)
    return row


def _seed(monkeypatch, *rows):
    monkeypatch.setattr(L, "_load", lambda: {"orders": [dict(r) for r in rows]})


def test_held_under_another_label_on_another_slate_is_refused(monkeypatch):
    _seed(monkeypatch, _held())
    assert L.held_venue_contract_for(_request()) is not None


@pytest.mark.parametrize(
    "row",
    [
        _held(side="home", line=-9.5),  # the opposite leg of the same ticker is a different contract leg
        _held(venue_ticker="KXNBASPREAD-99OCT21DALHOU-HOU7"),  # another contract
        _held(venue="polymarket"),
        _held(mode="paper"),
        _held(status="rejected"),
        _held(status="failed", error="http_400 insufficient_balance"),  # the venue refused: nothing held
    ],
)
def test_rows_that_are_not_this_contract_leg(monkeypatch, row):
    _seed(monkeypatch, row)
    assert L.held_venue_contract_for(_request()) is None


def test_the_requests_own_key_is_left_to_the_duplicate_path(monkeypatch):
    req = _request()
    _seed(monkeypatch, _held(idempotency_key=L.idempotency_key(req)))
    assert L.held_venue_contract_for(req) is None


def test_the_leg_is_kalshis_own_mapping():
    # spreads and spreads_alt, away 9.5: the same Kalshi leg.
    assert L.venue_leg_of("kalshi", "away", "spreads", 9.5) == L.venue_leg_of("kalshi", "away", "spreads_alt", 9.5)
    assert L.venue_leg_of("kalshi", "over", "totals", 220.5) == "yes"


def test_the_switch_off_disables_the_check_itself(monkeypatch):
    _seed(monkeypatch, _held())
    monkeypatch.setenv("SYNDICATE_EXECUTION_VENUE_CONTRACT_DEDUPE", "off")
    assert L.held_venue_contract_for(_request()) is None
