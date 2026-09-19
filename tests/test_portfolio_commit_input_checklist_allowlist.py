"""The portfolio input checklist must follow the market-fair allowlist, not fight it.

INCIDENT 2026-09-16 (lane `portfolio-no-family-exclusion`, `deploys.md` 17:28:19Z). The user
decided EV-only staking in every sport, so `SYNDICATE_PORTFOLIO_MARKET_FAIR_SPORTS` was set to
all eight. The checklist stripped `model_edge_pct` from its canonical MLB row and REQUIRED the
refusal `no_model_edge_pct`; with MLB allowlisted the row was sized on market fair instead, the
checklist failed, and `intelligence_state` skipped EVERY portfolio commit until the env was
reverted. `test_market_fair_sizing.py` covered the checklist with the feature OFF only -- and its
own docstring named exactly this failure.

THE CONTRACT, both halves gated:
  * a sport ON the allowlist: a row missing `model_edge_pct` must be SIZED (on market fair);
  * a sport OFF the allowlist: it must be refused `no_model_edge_pct`, never sized on a default.
The second half is probed with a sport that can never be allowlisted, so it stays enforced even
when every real sport is on the list.
"""

from __future__ import annotations

import pytest

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

@pytest.fixture(autouse=True)
def _sim_sizing_legacy(monkeypatch):
    """These tests pin the sizing MECHANICS of a model that is allowed to size.
    WHETHER a model may size (only one measured to beat the market) is
    `test_portfolio_sim_skill_gate.py`'s business (lane `sim-sizing-skill-gate`)."""
    monkeypatch.setenv("SYNDICATE_PORTFOLIO_SIM_SIZING", "legacy")


ENV = "SYNDICATE_PORTFOLIO_MARKET_FAIR_SPORTS"
ALL_SPORTS = "mlb,nba,wnba,nhl,nfl,ncaaf,ncaab,soccer"


def _run():
    from scripts.portfolio_commit_input_checklist import run_checklist

    return run_checklist()


def _model_edge_lines(lines):
    return [line for line in lines if "missing model_edge_pct" in line]


def test_the_checklist_PASSES_with_every_sport_allowlisted(monkeypatch):
    """Red against the 2026-09-16 checklist: this is the production configuration that
    stopped every portfolio commit."""
    monkeypatch.setenv(ENV, ALL_SPORTS)
    ok, lines = _run()
    assert ok, "\n".join(lines)


def test_with_the_canonical_sport_allowlisted_the_stripped_row_must_SIZE(monkeypatch):
    monkeypatch.setenv(ENV, "mlb")
    ok, lines = _run()
    assert ok, "\n".join(lines)
    canonical = [line for line in _model_edge_lines(lines) if "sized" in line]
    assert canonical and canonical[0].startswith("ok"), "\n".join(lines)


def test_the_refusal_contract_is_still_gated_when_every_sport_is_allowlisted(monkeypatch):
    monkeypatch.setenv(ENV, ALL_SPORTS)
    ok, lines = _run()
    refused = [line for line in _model_edge_lines(lines) if "want 'no_model_edge_pct'" in line]
    assert refused and all(line.startswith("ok") for line in refused), "\n".join(lines)


def test_with_the_feature_off_the_refusal_contract_is_unchanged(monkeypatch):
    monkeypatch.delenv(ENV, raising=False)
    ok, lines = _run()
    assert ok, "\n".join(lines)
    assert not [line for line in _model_edge_lines(lines) if "sized" in line and line.startswith("ok")], "\n".join(lines)


def test_MUTATION_a_sizer_that_sizes_a_non_allowlisted_row_on_a_default_FAILS(monkeypatch):
    """The gate must still catch the thing it exists for."""
    import scripts.portfolio_commit_input_checklist as checklist
    from syndicate.features.shared.portfolio_commit import sizing_inputs_from_row as real

    monkeypatch.delenv(ENV, raising=False)
    canonical_inputs, _ = real(dict(checklist.CANONICAL_ROW))

    def sizes_everything(row):
        if row.get("model_edge_pct") is None and "quote" in row and "ev_pct" in row and "score" in row:
            return canonical_inputs, None
        return real(row)

    monkeypatch.setattr(checklist, "sizing_inputs_from_row", sizes_everything)
    ok, lines = _run()
    assert not ok, "\n".join(lines)


def test_MUTATION_a_sizer_that_refuses_an_allowlisted_row_FAILS(monkeypatch):
    import scripts.portfolio_commit_input_checklist as checklist
    from syndicate.features.shared.portfolio_commit import sizing_inputs_from_row as real

    monkeypatch.setenv(ENV, "mlb")

    def refuses_missing_edge(row):
        if row.get("model_edge_pct") is None:
            return None, "no_model_edge_pct"
        return real(row)

    monkeypatch.setattr(checklist, "sizing_inputs_from_row", refuses_missing_edge)
    ok, lines = _run()
    assert not ok, "\n".join(lines)
