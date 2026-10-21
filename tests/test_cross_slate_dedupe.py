"""One bet, one live order, however many slates plan it (todo #707, D1).

`idempotency_key` hashes `selected_date`, and the Layer 2 shortlist keeps
NFL/NCAAF/soccer games up to six days out, so the same bet on Thursday's and
Friday's slates was two keys and two live orders. `held_position_for` refuses the
second by name. Reachability first (T1): with the switch off the second order IS
sent; with it on it is refused and nothing is written.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared import execution_ledger as L
from syndicate.features.shared.execution_ledger import ledger_summary
from syndicate.features.shared.portfolio_settings import PortfolioSettings

_TICKER = "KXNCAAFSPREAD-26OCT24AAABBB-AAA14"
_DAY1 = "2026-10-22"
_DAY2 = "2026-10-23"


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
        "SYNDICATE_EXECUTION_CROSS_SLATE_DEDUPE",
        "SYNDICATE_EXECUTION_BALANCE_CAPS",
    ):
        monkeypatch.delenv(key, raising=False)
    yield


def _row(**overrides):
    # A Saturday NCAAF spread, planned from Thursday on: the case that repeats.
    row = {
        "sport": "ncaaf",
        "event_id": "evt-ncaaf-1",
        "kind": "game",
        "market": "spreads",
        "segment": "full_game",
        "line": -14.5,
        "player_name": None,
        "home_team": "AAA",
        "away_team": "BBB",
        "commence_time": "2026-10-24T19:00:00Z",
        "side": "home",
        "quote": {"price": 108, "bookmaker": "kalshi"},
        "ev_pct": 3.5,
        "model_edge_pct": 2.0,
        "score": {"score": 5.1, "price_reliability": 0.82},
        "venue_ticker": _TICKER,
    }
    row.update(overrides)
    return row


def _plan_for(monkeypatch, rows):
    monkeypatch.setenv("SYNDICATE_PORTFOLIO_COMMIT_ENABLED", "1")
    monkeypatch.setattr(
        "pipeline.intelligence_state.read_layer2_shortlist",
        lambda date: {"rows": [{**r, "suggested": True} for r in rows]},
    )
    from pipeline import portfolio_commit as commit

    monkeypatch.setattr(
        "syndicate.features.shared.portfolio_commit.resolve_settings",
        lambda: PortfolioSettings(
            bankroll_units=1000.0,
            max_slate_exposure_fraction=1.0,
            min_ev_pct=-100.0,
            max_positions=50,
            min_stake_units=0.0,
        ),
    )
    result = commit.run_portfolio_commit(_DAY1)
    assert result["status"] == "ok", result
    plan = result["plan"]
    # The SAME plan is served for every slate date: that is the forward bet
    # being planned again on the next day's slate.
    monkeypatch.setattr("pipeline.portfolio_commit.read_portfolio_plan_for_venue", lambda date, scope: plan)
    monkeypatch.setattr("pipeline.portfolio_commit.read_live_portfolio_plan_for_venue", lambda date, scope: plan)
    return plan


def _arm_live(monkeypatch):
    monkeypatch.setenv("SYNDICATE_EXECUTION_ENABLED", "1")
    monkeypatch.setenv("SYNDICATE_EXECUTION_MODE", "live")
    monkeypatch.setenv("SYNDICATE_EXECUTION_LIVE_ARMED", "1")
    monkeypatch.setenv("SYNDICATE_EXECUTION_VENUE", "kalshi")
    monkeypatch.setenv("SYNDICATE_EXECUTION_MAX_ORDER_DOLLARS", "1000")
    monkeypatch.setenv("SYNDICATE_EXECUTION_MAX_DAY_DOLLARS", "10000")


def _recording_submitter(monkeypatch, status="filled"):
    from pipeline import execute_portfolio as runner

    sent: list = []

    def submitter(request):
        sent.append(request)
        return {"status": status, "fill_price": 0.48, "fill_stake_dollars": request.requested_stake_dollars}

    monkeypatch.setattr(runner, "_venue_submitter", lambda venue: submitter)
    return sent


def _two_slates(monkeypatch, *, switch: str | None, status="filled"):
    from pipeline import execute_portfolio as runner

    _plan_for(monkeypatch, [_row()])
    _arm_live(monkeypatch)
    if switch is not None:
        monkeypatch.setenv("SYNDICATE_EXECUTION_CROSS_SLATE_DEDUPE", switch)
    sent = _recording_submitter(monkeypatch, status=status)
    first = runner.run_execution(_DAY1, venue_scope="kalshi")
    second = runner.run_execution(_DAY2, venue_scope="kalshi")
    return first, second, sent


# --------------------------------------------------------------------------
# T1 -- reachability: off != on
# --------------------------------------------------------------------------


def test_T1_off_the_same_bet_is_ordered_again_on_the_next_slate(monkeypatch):
    # The venue-contract dedupe (2026-10-21) would also catch this pair -- same bet,
    # same ticker. Held off here so this arm measures D1 alone.
    monkeypatch.setenv("SYNDICATE_EXECUTION_VENUE_CONTRACT_DEDUPE", "off")
    first, second, sent = _two_slates(monkeypatch, switch="off")
    assert first["placed"] == 1
    # THE DEFECT, reproduced: a second live order for the same bet.
    assert second["placed"] == 1
    assert len(sent) == 2
    assert "already_held_other_slate" not in second["refused"]


def test_T1_on_the_next_slate_is_refused_by_name_and_nothing_is_written(monkeypatch, capsys):
    first, second, sent = _two_slates(monkeypatch, switch=None)  # default ON
    assert first["placed"] == 1
    assert second["placed"] == 0
    assert second["refused"] == {"already_held_other_slate": 1}
    assert len(sent) == 1
    assert ledger_summary(_DAY2)["orders"] == 0
    out = capsys.readouterr().out
    assert "REFUSED_HELD_OTHER_SLATE venue=kalshi" in out


def test_T1_the_same_slate_re_run_is_still_a_duplicate_not_this_refusal(monkeypatch):
    # The existing per-slate idempotency keeps its own counter: D1 only looks
    # at OTHER slates, so it cannot mask a re-run.
    from pipeline import execute_portfolio as runner

    _plan_for(monkeypatch, [_row()])
    _arm_live(monkeypatch)
    sent = _recording_submitter(monkeypatch)
    runner.run_execution(_DAY1, venue_scope="kalshi")
    again = runner.run_execution(_DAY1, venue_scope="kalshi")
    assert again["duplicates"] == 1
    assert "already_held_other_slate" not in again["refused"]
    assert len(sent) == 1


# --------------------------------------------------------------------------
# What counts as held
# --------------------------------------------------------------------------


def _request(**overrides):
    fields = dict(
        position_key="pk-1",
        selected_date=_DAY2,
        venue="kalshi",
        sport="ncaaf",
        event_id="evt-ncaaf-1",
        market="spreads",
        side="home",
        requested_price=0.48,
        requested_stake_dollars=5.0,
        line=-14.5,
        venue_ticker=_TICKER,
        commence_time="2026-10-24T19:00:00Z",
    )
    fields.update(overrides)
    return L.OrderRequest(**fields)


def _seed(monkeypatch, *rows):
    monkeypatch.setattr(L, "_load", lambda: {"orders": [dict(r) for r in rows]})


def _held(**overrides):
    row = {
        "mode": "live",
        "venue": "kalshi",
        "position_key": "pk-1",
        "selected_date": _DAY1,
        "status": "filled",
        "error": None,
    }
    row.update(overrides)
    return row


@pytest.mark.parametrize("status", ["filled", "submitted"])
def test_a_filled_or_resting_order_on_another_slate_is_held(monkeypatch, status):
    _seed(monkeypatch, _held(status=status))
    assert L.held_position_for(_request()) is not None


def test_a_timed_out_failed_order_is_held_because_it_may_have_landed(monkeypatch):
    _seed(monkeypatch, _held(status="failed", error="ReadTimeout"))
    assert L.held_position_for(_request()) is not None


@pytest.mark.parametrize(
    "row",
    [
        _held(status="rejected"),
        _held(status="failed", error="http_400 insufficient_balance"),  # the venue refused: no contract
        _held(mode="paper"),
        _held(venue="polymarket"),
        _held(position_key="pk-other"),  # a moved line is a different bet
        _held(selected_date=_DAY2),  # same slate: idempotency_key's job
    ],
)
def test_rows_that_do_not_hold_this_bet(monkeypatch, row):
    _seed(monkeypatch, row)
    assert L.held_position_for(_request()) is None


def test_a_pre_2026_08_30_row_matches_through_the_legacy_key(monkeypatch):
    _seed(monkeypatch, _held(position_key="legacy-pk"))
    assert L.held_position_for(_request(legacy_position_key="legacy-pk")) is not None


def test_the_switch_off_disables_the_check_itself(monkeypatch):
    _seed(monkeypatch, _held())
    monkeypatch.setenv("SYNDICATE_EXECUTION_CROSS_SLATE_DEDUPE", "off")
    assert L.held_position_for(_request()) is None
