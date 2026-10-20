"""The paper LADDER: Kalshi/Polymarket paper books below today's floor, paper only.

User decision 2026-10-20 (relayed by session b87af0fc): "yes - but we should reconsider
the floors". These tests pin that the ladder is reachable (off != on), that it never
changes the live or paper2 plans, that it books only `paper:<venue>:ladder` rows with
band tags, and that the pre-registered forward test cannot read it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from syndicate.features.shared import paper_ladder
from syndicate.features.shared.portfolio_settings import PortfolioSettings

_DATE = "2026-08-22"
_TICKER = "KXNCAAFGAME-26AUG22-HOME"


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
        "SYNDICATE_PAPER2_VENUES",
        "SYNDICATE_PAPER2_VENUE",
        "SYNDICATE_PAPER_LADDER",
        "SYNDICATE_PAPER_ALONGSIDE_LIVE",
    ):
        monkeypatch.delenv(key, raising=False)
    yield


def _settings() -> PortfolioSettings:
    return PortfolioSettings(
        bankroll_units=1000.0, max_slate_exposure_fraction=1.0, min_ev_pct=-100.0,
        max_positions=50, min_stake_units=0.0,
    )


def _board_row(event_id: str, *, kalshi: int, suggested: bool, reasons=None, stamp=True):
    """A shortlist row: 0.75% at DK -110, Kalshi quoted at `kalshi` (see test_kalshi_plan_placeable)."""
    row = {
        "sport": "ncaaf", "event_id": event_id, "kind": "game", "market": "h2h",
        "segment": "full_game", "line": None, "player_name": None,
        "home_team": f"Home {event_id}", "away_team": f"Away {event_id}",
        "commence_time": "2026-08-22T23:05:00Z", "side": "home",
        "quote": {"price": -110, "bookmaker": "draftkings", "book_prices": {"draftkings": -110, "kalshi": kalshi}},
        "ev_pct": 0.75, "model_edge_pct": 4.0,
        "score": {"score": 5.0, "price_reliability": 0.82},
        "suggested": suggested,
    }
    if stamp:
        row["suggested_reasons"] = [] if suggested else list(reasons or [])
    return row


BOARD = [
    # Staked by paper2 (Suggested, ~+1.1% net at Kalshi -102): the ladder must NOT book it.
    _board_row("staked", kalshi=-102, suggested=True),
    # Refused ONLY by the EV floor: the ladder's population.
    _board_row("floor-1to2", kalshi=-102, suggested=False, reasons=["ev_below_min"]),
    _board_row("floor-m1to0", kalshi=-105, suggested=False, reasons=["ev_below_min", "ev_net_of_fee_below_min"]),
    _board_row("floor-too-low", kalshi=-115, suggested=False, reasons=["ev_below_min"]),
    # Refused for a NON-EV reason, or never stamped: never on the ladder.
    _board_row("single-book", kalshi=-102, suggested=False, reasons=["ev_below_min", "single_book_fair"]),
    _board_row("no-stamp", kalshi=-102, suggested=False, stamp=False),
]


def _run_commit(monkeypatch, *, ladder: str | None = None):
    monkeypatch.setenv("SYNDICATE_PORTFOLIO_COMMIT_ENABLED", "1")
    monkeypatch.setenv("SYNDICATE_PAPER2_VENUES", "kalshi")
    if ladder is None:
        monkeypatch.delenv("SYNDICATE_PAPER_LADDER", raising=False)
    else:
        monkeypatch.setenv("SYNDICATE_PAPER_LADDER", ladder)
    monkeypatch.setattr(
        "pipeline.intelligence_state.read_layer2_shortlist", lambda date: {"rows": [dict(r) for r in BOARD]}
    )
    from pipeline import portfolio_commit as mod

    monkeypatch.setattr(mod, "resolve_settings", lambda: _settings())
    monkeypatch.setattr("syndicate.features.shared.portfolio_commit.resolve_settings", lambda: _settings())
    monkeypatch.setattr(
        mod,
        "_venue_price_resolver",
        lambda venue, date=None: (
            ((lambda row: (row.get("quote") or {}).get("book_prices", {}).get("kalshi")), (lambda row: _TICKER))
            if venue == "kalshi" else (None, None)
        ),
    )
    result = mod.run_portfolio_commit(_DATE, settled_sample_size_by_sport={})
    assert result["status"] == "ok", result
    return mod, result


def _ids(plan) -> set:
    return {p.get("event_id") for p in (plan or {}).get("positions") or []}


def _strip_volatile(plan):
    return [
        {k: v for k, v in p.items() if k not in {"committed_at"}}
        for p in (plan or {}).get("positions") or []
    ]


# --------------------------------------------------------------------------
# Units
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "net,band",
    [(5.0, "ge2"), (2.0, "ge2"), (1.999, "1to2"), (1.0, "1to2"), (0.5, "0to1"), (0.0, "0to1"),
     (-0.01, "m1to0"), (-1.0, "m1to0"), (-1.01, None), (None, None)],
)
def test_bands(net, band):
    assert paper_ladder.ev_band(net) == band


def test_eligibility_takes_only_the_ev_floor_reasons():
    assert paper_ladder.ladder_reason({"suggested": True}) == "suggested_not_staked"
    assert paper_ladder.ladder_reason({"suggested": False, "suggested_reasons": ["ev_below_min"]}) == "below_suggested_floor"
    assert paper_ladder.ladder_reason(
        {"suggested": False, "suggested_reasons": ["ev_below_min", "ev_net_of_fee_below_min"]}
    ) == "below_suggested_floor"
    assert paper_ladder.ladder_reason({"suggested": False, "suggested_reasons": ["implausible_book"]}) is None
    assert paper_ladder.ladder_reason({"suggested": False, "suggested_reasons": ["ev_below_min", "suspect_stale_quote"]}) is None
    # Unknown is not permissive.
    assert paper_ladder.ladder_reason({"suggested": False}) is None
    assert paper_ladder.ladder_reason({"suggested": False, "suggested_reasons": []}) is None


# --------------------------------------------------------------------------
# Reachability, and the plans live reads are unchanged
# --------------------------------------------------------------------------


def test_off_writes_no_ladder_and_on_writes_one(monkeypatch):
    mod, result = _run_commit(monkeypatch, ladder="off")
    assert result["ladder_plans"] == {}
    assert mod.read_ladder_plan_for_venue(_DATE, "kalshi") is None

    mod, result = _run_commit(monkeypatch)
    assert set(result["ladder_plans"]) == {"kalshi"}
    assert mod.read_ladder_plan_for_venue(_DATE, "kalshi")["positions"]


def test_live_and_paper2_plans_are_identical_with_the_ladder_on_or_off(monkeypatch):
    mod, _ = _run_commit(monkeypatch, ladder="off")
    live_off = mod.read_live_portfolio_plan_for_venue(_DATE, "kalshi")
    paper2_off = mod.read_portfolio_plan_for_venue(_DATE, "kalshi")
    main_off = mod.read_portfolio_plan(_DATE)

    mod, _ = _run_commit(monkeypatch)
    assert _strip_volatile(mod.read_live_portfolio_plan_for_venue(_DATE, "kalshi")) == _strip_volatile(live_off)
    assert _strip_volatile(mod.read_portfolio_plan_for_venue(_DATE, "kalshi")) == _strip_volatile(paper2_off)
    assert _strip_volatile(mod.read_portfolio_plan(_DATE)) == _strip_volatile(main_off)
    # And the Suggested-only books never saw a floor row.
    assert _ids(paper2_off) == {"staked"}


def test_the_ladder_is_the_complement_banded_and_flat(monkeypatch):
    mod, _ = _run_commit(monkeypatch)
    ladder = mod.read_ladder_plan_for_venue(_DATE, "kalshi")
    by_id = {p["event_id"]: p for p in ladder["positions"]}
    assert set(by_id) == {"floor-1to2", "floor-m1to0"}, ladder
    assert by_id["floor-1to2"]["ev_band"] == "1to2"
    assert by_id["floor-m1to0"]["ev_band"] == "m1to0"
    assert {p["ladder_reason"] for p in by_id.values()} == {"below_suggested_floor"}
    assert {p["stake_dollars"] for p in by_id.values()} == {1.0}
    assert {p["stake_basis"] for p in by_id.values()} == {"flat_1"}
    assert {p["venue_ticker"] for p in by_id.values()} == {_TICKER}
    assert ladder["refusals"]["staked_by_venue_book"] == 1
    assert ladder["refusals"]["below_ladder_floor"] == 1
    assert ladder["bands"] == {"1to2": 1, "m1to0": 1}


# --------------------------------------------------------------------------
# Execution: paper only, its own venue, tagged
# --------------------------------------------------------------------------


def _live_env(monkeypatch):
    monkeypatch.setenv("SYNDICATE_EXECUTION_ENABLED", "1")
    monkeypatch.setenv("SYNDICATE_EXECUTION_MODE", "live")
    monkeypatch.setenv("SYNDICATE_EXECUTION_LIVE_ARMED", "1")
    monkeypatch.setenv("SYNDICATE_EXECUTION_VENUE", "kalshi,polymarket")


def _rows(venue=None):
    from syndicate.features.shared.execution_ledger import _load

    return [o for o in _load().get("orders") or [] if venue is None or o.get("venue") == venue]


def test_inline_books_paper_ladder_rows_with_band_tags(monkeypatch):
    from pipeline import execute_portfolio as runner
    from syndicate.features.shared import execution_ledger

    _run_commit(monkeypatch)
    _live_env(monkeypatch)

    def explode(*a, **k):
        raise AssertionError("the ladder must never reach a venue")

    monkeypatch.setattr(runner, "_venue_submitter", explode)
    monkeypatch.setattr(execution_ledger, "reconcile_live_orders", explode)

    result = runner.run_execution(_DATE, inline=True, venue_scope="kalshi", book="ladder")
    assert result["status"] == "ok", result
    assert result["mode"] == "paper"
    assert result["venue"] == "paper:kalshi:ladder"
    assert result["plan_source"] == "ladder"
    assert result["placed"] == 2
    rows = _rows("paper:kalshi:ladder")
    assert {o["mode"] for o in rows} == {"paper"}
    assert {o["ev_band"] for o in rows} == {"1to2", "m1to0"}
    assert {o["selection"] for o in rows} == {"ladder"}
    assert {o["ladder_reason"] for o in rows} == {"below_suggested_floor"}
    assert {o["stake_basis"] for o in rows} == {"flat_1"}
    assert {o["requested_stake_dollars"] for o in rows} == {1.0}
    assert all(o["ev_net_pct"] is not None and o["paper_alongside_live"] is True for o in rows)
    # Nothing else was written.
    assert len(_rows()) == 2


def test_live_mode_refuses_the_ladder(monkeypatch):
    from pipeline import execute_portfolio as runner

    _run_commit(monkeypatch)
    _live_env(monkeypatch)
    result = runner.run_execution(_DATE, venue_scope="kalshi", book="ladder")
    assert result["status"] == "skipped"
    assert result["reason"] == "ladder_is_paper_only"
    assert _rows() == []
    # And with the alongside switch off, the inline refusal stands as before.
    monkeypatch.setenv("SYNDICATE_PAPER_ALONGSIDE_LIVE", "off")
    off = runner.run_execution(_DATE, inline=True, venue_scope="kalshi", book="ladder")
    assert off["reason"] == "live_mode_refused_inline"
    assert _rows() == []


def test_a_bet_the_venue_book_holds_is_not_booked_on_the_ladder(monkeypatch):
    """Across builds: paper:kalshi took this bet earlier on the slate, then it fell below the floor."""
    from pipeline import execute_portfolio as runner
    from syndicate.features.shared.execution_ledger import OrderRequest, place_order

    mod, _ = _run_commit(monkeypatch)
    ladder = mod.read_ladder_plan_for_venue(_DATE, "kalshi")
    held = next(p for p in ladder["positions"] if p["event_id"] == "floor-1to2")
    place_order(
        OrderRequest(
            position_key=held["position_key"], selected_date=_DATE, venue="paper:kalshi", sport="ncaaf",
            event_id="floor-1to2", market="h2h", side="home", requested_price=-102.0, requested_stake_dollars=3.0,
        ),
        mode="paper",
    )
    _live_env(monkeypatch)
    result = runner.run_execution(_DATE, inline=True, venue_scope="kalshi", book="ladder")
    assert result["placed"] == 1
    assert result["refused"].get("held_by_venue_book") == 1
    assert {o["event_id"] for o in _rows("paper:kalshi:ladder")} == {"floor-m1to0"}


def test_a_rerun_books_nothing_new(monkeypatch):
    from pipeline import execute_portfolio as runner

    _run_commit(monkeypatch)
    _live_env(monkeypatch)
    runner.run_execution(_DATE, inline=True, venue_scope="kalshi", book="ladder")
    again = runner.run_execution(_DATE, inline=True, venue_scope="kalshi", book="ladder")
    assert again["placed"] == 0 and again["duplicates"] == 2
    assert len(_rows("paper:kalshi:ladder")) == 2


# --------------------------------------------------------------------------
# Wiring and the readers that must NOT see it
# --------------------------------------------------------------------------


def test_the_ladder_has_a_caller():
    import inspect

    import pipeline.intelligence_state as state

    source = inspect.getsource(state)
    assert 'commit_result.get("ladder_plans")' in source
    assert 'venue_scope=venue_scope, book="ladder"' in source


def test_the_preregistered_forward_test_cannot_read_ladder_rows():
    """The forward test (16888bb6) selects venues by EXACT name. A ladder venue in any of its
    lists would silently widen a pre-registered population."""
    source = Path(__file__).resolve().parents[1].joinpath("scripts", "paper_bet_optimization.py").read_text(encoding="utf-8")
    names = set()
    for const in ("PRIMARY", "SECONDARY", "LIVE"):
        match = re.search(rf"^{const}\s*=\s*\(([^)]*)\)", source, re.MULTILINE)
        assert match, const
        names |= set(re.findall(r'"([^"]+)"', match.group(1)))
    assert names and not any(name.endswith(":ladder") for name in names)
    for venue in paper_ladder.LADDER_VENUES:
        assert paper_ladder.ladder_venue_name(venue) not in names


# --------------------------------------------------------------------------
# The pre-registered readout
# --------------------------------------------------------------------------


def _readout():
    import importlib.util

    path = Path(__file__).resolve().parents[1] / "scripts" / "paper_ladder_readout.py"
    spec = importlib.util.spec_from_file_location("paper_ladder_readout", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _order(venue, band=None, *, key="k", event="e", outcome="won", pnl=0.9, stake=1.0, date="2026-10-21"):
    return {
        "mode": "paper", "status": "filled", "venue": venue, "ev_band": band, "position_key": key,
        "event_id": event, "outcome": outcome, "pnl_dollars": pnl, "requested_stake_dollars": stake,
        "selected_date": date, "submitted_at": "2026-10-21T15:00:00Z",
    }


def test_readout_dedupes_to_the_venue_book_and_ignores_other_books():
    ro = _readout()
    orders = [
        _order("paper:kalshi:ladder", "1to2", key="same"),
        _order("paper:kalshi", key="same"),
        _order("paper:kalshi:ladder", "0to1", key="other"),
        _order("paper", key="x"), _order("kalshi", key="y") | {"mode": "live"},
        _order("paper:kalshi:ladder", "0to1", key="old") | {"submitted_at": "2026-10-19T00:00:00Z"},
    ]
    pop = ro.settled_population(orders, ro.DEFAULT_SINCE)
    assert sorted((r["venue"], r["band"]) for r in pop) == [("kalshi", "0to1"), ("kalshi", "venue_book")]


def test_readout_rule_needs_events_roi_and_clv():
    ro = _readout()
    assert ro.verdict("1to2", (5.0, 1.0, 500, 50), (1.0, 0.5, 50, 50)).startswith("INSUFFICIENT")
    assert ro.verdict("1to2", (5.0, 2.0, 500, 150), (1.0, 0.5, 50, 50)).startswith("CANDIDATE")
    assert ro.verdict("1to2", (5.0, 2.0, 500, 150), (-0.5, 0.5, 50, 50)).startswith("NO CHANGE")
    assert ro.verdict("0to1", (-6.0, 2.0, 500, 150), (None, None, 0, 0)).startswith("AGAINST")
    assert ro.verdict("venue_book", (-6.0, 2.0, 500, 150), (None, None, 0, 0)).startswith("AGAINST THE CURRENT FLOOR")
