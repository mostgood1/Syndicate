"""Only a model MEASURED to beat the market may move money (lane `sim-sizing-skill-gate`).

`[2026-09-19, user decision "All sports (Recommended)"]`: no sim sizes a stake, vetoes
a price bet or wins a slot in the position cut unless the row's
`projection.model_skill` is `measured` with `verdict_class == beats_market`. The sim
edge stays on the row, shown, ranked and recorded; the money follows price.

At the decision, all 31 `measured_market_skill` entries were `parity` or
`loses_to_market`, and the WNBA backtest (25 dates, 4,297 props) scored the sim at
log-loss 0.858 against the market's 0.682, while the sim owned 57.6% of a
representative stake.

THE INVARIANT: a gated row sizes EXACTLY like the same row with no model edge.
Every test that asserts a change also shows `legacy` restoring the old
behaviour, so the gate is what moved it (off != on).
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.portfolio_commit import (
    _cut_rank_score,
    commit_portfolio,
    sizing_basis_of,
    sizing_inputs_from_row,
)
from syndicate.features.shared.portfolio_settings import PortfolioSettings

GATE_ENV = "SYNDICATE_PORTFOLIO_SIM_SIZING"
FAIR_ENV = "SYNDICATE_PORTFOLIO_MARKET_FAIR_SPORTS"
PRICE_ENV = "SYNDICATE_PORTFOLIO_PRICE_BASIS_SPORTS"

UNMEASURED = {"status": "unmeasured", "verdict": "model never backtested"}
PARITY = {"status": "measured", "verdict_class": "parity", "verdict": "parity with the close"}
LOSES = {"status": "measured", "verdict_class": "loses_to_market", "verdict": "loses to the close"}
NO_CLASS = {"status": "measured", "verdict": "loss to the close, +1.75 MAE"}
BEATS = {"status": "measured", "verdict_class": "beats_market", "verdict": "beats the close"}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    # Production's allowlist (read 2026-09-19): every sport may size on price.
    monkeypatch.setenv(FAIR_ENV, "mlb,nba,wnba,nhl,nfl,ncaaf,ncaab,soccer")
    monkeypatch.delenv(PRICE_ENV, raising=False)
    monkeypatch.delenv(GATE_ENV, raising=False)
    # The shipped static bucket table (empty), never a pulled overlay: deterministic.
    monkeypatch.setenv("SYNDICATE_SKILL_OVERLAY", "off")


def _row(skill=UNMEASURED, **over):
    row = {
        "sport": "wnba",
        "market": "totals",
        "side": "over",
        "line": 170.5,
        "quote": {"price": -110},
        "ev_pct": 4.5,
        "model_edge_pct": 8.0,
        "score": {"score": 5.0, "price_reliability": 1.0},
    }
    if skill is not None:
        row["projection"] = {"model_skill": dict(skill)}
    row.update(over)
    return row


def _commit(rows, **settings):
    return commit_portfolio(
        rows, selected_date="2026-09-19", settings=PortfolioSettings(bankroll_units=1000.0, **settings)
    )


# --- sizing inputs -------------------------------------------------------------


@pytest.mark.parametrize("skill", [None, UNMEASURED, NO_CLASS, PARITY, LOSES], ids=["no_note", "unmeasured", "measured_no_class", "parity", "loses"])
def test_a_model_not_measured_to_beat_the_market_sizes_like_no_model(skill):
    gated, reason = sizing_inputs_from_row(_row(skill=skill))
    no_model, _ = sizing_inputs_from_row(_row(skill=skill, model_edge_pct=None))
    assert reason is None
    assert gated == no_model
    assert gated.model_probability == gated.market_fair_probability
    assert sizing_basis_of(_row(skill=skill)) == "market_fair"


def test_a_model_measured_to_beat_the_market_still_sizes():
    admitted, reason = sizing_inputs_from_row(_row(skill=BEATS))
    assert reason is None
    assert admitted.model_probability == pytest.approx(admitted.market_fair_probability + 0.08)
    assert sizing_basis_of(_row(skill=BEATS)) == "model_edge"


def test_legacy_restores_sim_sizing_so_the_gate_is_what_moved_it(monkeypatch):
    gated, _ = sizing_inputs_from_row(_row())
    monkeypatch.setenv(GATE_ENV, "legacy")
    legacy, _ = sizing_inputs_from_row(_row())
    assert legacy.model_probability == pytest.approx(legacy.market_fair_probability + 0.08)
    assert gated.model_probability != legacy.model_probability
    assert sizing_basis_of(_row()) == "model_edge"


@pytest.mark.parametrize("value", ["", "off", "LEGACYX", "true", "admit"])
def test_only_the_exact_word_legacy_reverts(monkeypatch, value):
    monkeypatch.setenv(GATE_ENV, value)
    assert sizing_basis_of(_row()) == "market_fair"
    monkeypatch.setenv(GATE_ENV, " Legacy ")
    assert sizing_basis_of(_row()) == "model_edge"


# --- the plan ------------------------------------------------------------------


def test_positions_carry_no_sim_share_and_the_plan_counts_why(monkeypatch):
    # Three separate games, so exposure budgeting's correlated-leg decay stays out of it.
    plan = _commit([
        _row(event_id="g1"),
        _row(skill=PARITY, line=171.5, event_id="g2"),
        _row(skill=BEATS, line=172.5, event_id="g3"),
    ])
    positions = {p["line"]: p for p in plan["positions"]}
    assert set(positions) == {170.5, 171.5, 172.5}
    for line in (170.5, 171.5):
        assert positions[line]["attribution"]["sim_share_of_stake"] == 0.0
        assert positions[line]["attribution"]["side_picked_by"] == "price_shopping"
        assert positions[line]["sizing"]["basis"] == "market_fair"
    assert positions[172.5]["attribution"]["sim_share_of_stake"] > 0.0
    # The label rides the POSITION, not only the plan counter: the first production plan
    # (2026-09-19 15:16Z) served `sizing.sim_sizing` None on all 89 positions because the
    # position's `sizing` block copies a fixed key list that did not include it.
    assert positions[170.5]["sizing"]["sim_sizing"] == "gated_unmeasured"
    assert positions[171.5]["sizing"]["sim_sizing"] == "gated_parity"
    assert positions[172.5]["sizing"]["sim_sizing"] == "admitted_beats_market"
    assert plan["sim_sizing"] == {
        "mode": "measured_only",
        "by_basis": {"admitted_beats_market": 1, "gated_parity": 1, "gated_unmeasured": 1},
    }

    monkeypatch.setenv(GATE_ENV, "legacy")
    legacy = _commit([_row()])
    assert legacy["positions"][0]["attribution"]["sim_share_of_stake"] > 0.0
    assert legacy["sim_sizing"]["by_basis"] == {"legacy": 1}


def test_a_sim_can_no_longer_veto_a_price_bet(monkeypatch):
    """Price says +4.5% EV; the sim says -12 points. Legacy sizes it to zero."""
    row = _row(model_edge_pct=-12.0)
    monkeypatch.setenv(GATE_ENV, "legacy")
    assert _commit([row])["refusals"].get("zero_kelly_stake") == 1
    monkeypatch.delenv(GATE_ENV)
    plan = _commit([row])
    assert len(plan["positions"]) == 1
    assert plan["positions"][0]["attribution"]["sim_share_of_stake"] == 0.0


def test_a_sim_can_no_longer_create_a_bet(monkeypatch):
    """No price edge (EV 0) but the sim says +8: legacy bets it on the sim alone."""
    row = _row(ev_pct=0.0)
    monkeypatch.setenv(GATE_ENV, "legacy")
    legacy = _commit([row], min_ev_pct=0.0)
    assert len(legacy["positions"]) == 1
    assert legacy["positions"][0]["attribution"]["side_picked_by"] == "simulation"
    monkeypatch.delenv(GATE_ENV)
    gated = _commit([row], min_ev_pct=0.0)
    assert gated["positions"] == []
    assert gated["refusals"].get("zero_kelly_stake") == 1


# --- the position cut -----------------------------------------------------------


def _scored(value_ev, sim, *, line, **over):
    """A Layer 2 score built with `blended_score`'s own algebra (reliability 0.9)."""
    confidence, freshness, price_rel = 1.0, 0.9, 1.0
    value = value_ev + sim
    return _row(
        line=line,
        ev_pct=value_ev,
        model_edge_pct=sim / 0.125,
        score={
            "score": round(min(value, value * confidence * freshness * price_rel), 4),
            "value_pct": value,
            "ev_component": value_ev,
            "sim_component": sim,
            "book_confidence": confidence,
            "freshness_factor": freshness,
            "price_reliability": price_rel,
        },
        **over,
    )


def test_the_cut_ranks_a_gated_row_without_its_sim_term():
    sim_lifted = _scored(6.0, 1.5, line=170.5, event_id="g1")    # score 6.75, price-only 5.4
    better_price = _scored(7.0, -0.5, line=168.5, event_id="g2")  # score 5.85, price-only 6.3
    assert _cut_rank_score(sim_lifted) == pytest.approx(5.4)
    assert _cut_rank_score(better_price) == pytest.approx(6.3)
    plan = _commit([sim_lifted, better_price], max_positions=1)
    assert [p["line"] for p in plan["positions"]] == [168.5]


def test_legacy_cut_still_ranks_on_the_published_score(monkeypatch):
    monkeypatch.setenv(GATE_ENV, "legacy")
    sim_lifted = _scored(6.0, 1.5, line=170.5, event_id="g1")
    better_price = _scored(7.0, -0.5, line=168.5, event_id="g2")
    assert _cut_rank_score(sim_lifted) == pytest.approx(6.75)
    plan = _commit([sim_lifted, better_price], max_positions=1)
    assert [p["line"] for p in plan["positions"]] == [170.5]


def test_an_admitted_model_keeps_its_published_score_in_the_cut():
    row = _scored(6.0, 1.5, line=170.5)
    row["projection"] = {"model_skill": dict(BEATS)}
    assert _cut_rank_score(row) == pytest.approx(6.75)


# --- the self-updating half: the daily scorecard's validated pockets -------------


def _bucket_factor_returns(monkeypatch, value):
    from syndicate.features.shared import measured_bucket_skill

    def fake(view, **_):
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(measured_bucket_skill, "bucket_factor", fake)


def test_a_validated_skill_pocket_earns_sizing_without_a_code_change(monkeypatch):
    gated, _ = sizing_inputs_from_row(_row())
    assert gated.model_probability == gated.market_fair_probability
    _bucket_factor_returns(monkeypatch, 1.0)
    admitted, _ = sizing_inputs_from_row(_row())
    assert admitted.model_probability == pytest.approx(admitted.market_fair_probability + 0.08)
    plan = _commit([_row()])
    assert plan["sim_sizing"]["by_basis"] == {"admitted_validated_pocket": 1}
    assert plan["positions"][0]["attribution"]["sim_share_of_stake"] > 0.0


@pytest.mark.parametrize("factor", [0.8, None, RuntimeError("overlay unreadable")], ids=["validated_loss", "no_bucket", "lookup_raises"])
def test_anything_but_a_clean_pocket_stays_gated(monkeypatch, factor):
    _bucket_factor_returns(monkeypatch, factor)
    inputs, _ = sizing_inputs_from_row(_row())
    assert inputs.model_probability == inputs.market_fair_probability
    assert _commit([_row()])["sim_sizing"]["by_basis"] == {"gated_unmeasured": 1}
