"""Sample credibility is WIRED, and wiring it changes the stake.

`bankroll_manager.py:210` sizes every board candidate as

    staked_fraction = full_kelly_fraction * multiplier * credibility

where `credibility = _sample_credibility(settled_sample_size)` ramps from a 0.25
floor to 1.0 at 50 settled bets. **No caller ever passed
`settled_sample_size_by_sport`**, so it defaulted to `None`, every sport looked
up 0, and every market sized at the floor -- 1/16 Kelly rather than the intended
1/4.

The hook's own comment said this was "correct while `settled_count` is 0
platform-wide" and that stakes should rise "on evidence rather than on a constant
being edited". Measured 2026-09-04, settlement carried **1,594 settled orders**
(616 in the dominant sport at +5.76% ROI). The caveat had come due.

`test_deriving_the_map_changes_the_stake` is the reachability test and it comes
first on purpose: a wired hook that does not move the number is inert, and
inertness is what this whole file exists to catch.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pipeline.portfolio_commit as runner  # noqa: E402
from syndicate.features.bankroll_manager import (  # noqa: E402
    _MIN_SAMPLE_CREDIBILITY,
    _SAMPLE_SIZE_FOR_FULL_CREDIBILITY,
    _sample_credibility,
    compute_board_stake,
)

CANDIDATE = {
    "model_probability": 0.58,
    "fair_probability": 0.50,
    "decimal_price": 2.05,
    "price_reliability": 1.0,
}


# --- reachability: off != on -------------------------------------------------


def test_deriving_the_map_changes_the_stake():
    """THE test. An unfed sample floors credibility at 0.25; a real sample of 50+
    earns 1.0 -- a 4x stake on identical inputs."""
    floored = compute_board_stake(CANDIDATE, settled_sample_size=0)
    earned = compute_board_stake(CANDIDATE, settled_sample_size=616)
    f = float(floored["stake_fraction"])
    e = float(earned["stake_fraction"])
    assert f > 0.0, "the floor is deliberately non-zero, not a silent 0"
    assert e > f, "wiring the sample must RAISE the stake, or the hook is inert"
    # 0.25 -> 1.00 is 4x IN THE CREDIBILITY TERM, but `compute_bet_size` also
    # caps at `cap_fraction` (3.5% of bankroll per bet), so on a candidate with
    # a real edge the delivered ratio is 3.5x, not 4x. Asserting a bare 4x here
    # would be asserting a number the sizer does not produce.
    assert 3.0 < e / f <= 4.0 + 1e-9, "got %.4f -> %.4f (%.3fx)" % (f, e, e / f)
    assert e <= float(earned["cap_fraction"]) + 1e-9, "the per-bet cap still binds"


def test_the_full_4x_lands_where_the_cap_does_not_bind():
    """On a thin edge the cap is not reached, so credibility delivers its whole
    4x. This is what separates "the cap swallowed it" from "the hook is inert"."""
    thin = dict(CANDIDATE, model_probability=0.515)
    f = float(compute_board_stake(thin, settled_sample_size=0)["stake_fraction"])
    e = float(compute_board_stake(thin, settled_sample_size=616)["stake_fraction"])
    assert f > 0.0 and e < float(compute_board_stake(thin, settled_sample_size=616)["cap_fraction"])
    # `stake_fraction` is stored ROUNDED (0.001875 -> 0.00187), so the ratio of
    # two rounded numbers is 4.0107 rather than 4.0. Compare against the
    # rounding granularity instead of asserting a bare equality the stored
    # values cannot satisfy.
    # `stake_fraction` is stored rounded to 5dp, so `f` carries up to 5e-6 of
    # rounding error and the 4x multiplies it to 2e-5. The true values here are
    # exactly 4x (0.001875 -> 0.0075); the tolerance is the rounding, not slack.
    assert abs(e - 4.0 * f) <= 4 * 5e-6 + 1e-9, (
        "uncapped, credibility delivers 4x within rounding; got %.5f -> %.5f" % (f, e))
    assert 3.9 < e / f < 4.1


def test_the_floor_is_what_an_unfed_hook_produces():
    assert _sample_credibility(0) == _MIN_SAMPLE_CREDIBILITY == 0.25
    assert _sample_credibility(None) == 0.25


def test_credibility_ramps_and_caps():
    assert _sample_credibility(_SAMPLE_SIZE_FOR_FULL_CREDIBILITY) == 1.0
    assert _sample_credibility(616) == 1.0, "past full credibility it must not exceed 1.0"
    half = _sample_credibility(25)
    assert 0.49 < half < 0.51, "the ramp is linear in the sample size"


# --- the derivation ----------------------------------------------------------


def test_it_derives_from_settlement_and_lowercases_the_key(monkeypatch):
    """The consumption site looks the sport up as
    `str(row.get("sport") or "").strip().lower()`. A key that does not match is
    silently 0 -- which is the floor again, i.e. the exact bug, re-created."""
    monkeypatch.setattr(
        "syndicate.features.shared.paper_settlement.settlement_summary",
        lambda *a, **k: {"by_sport": [
            {"key": "MLB", "settled": 616},
            {"key": "Soccer", "settled": 34},
        ]},
    )
    got = runner._settled_sample_size_by_sport()
    assert got == {"mlb": 616, "soccer": 34}


def test_it_drops_unknown_and_zero_buckets(monkeypatch):
    """`unknown` is not a sport, and a 0 contributes nothing but noise."""
    monkeypatch.setattr(
        "syndicate.features.shared.paper_settlement.settlement_summary",
        lambda *a, **k: {"by_sport": [
            {"key": "unknown", "settled": 900},
            {"key": "nhl", "settled": 0},
            {"key": "mlb", "settled": 12},
        ]},
    )
    assert runner._settled_sample_size_by_sport() == {"mlb": 12}


def test_a_settlement_failure_reverts_rather_than_breaking_the_commit(monkeypatch):
    """Returning {} restores the OLD behaviour. Raising would take the whole
    plan down, which is a worse outcome than sizing conservatively."""
    def boom(*a, **k):
        raise RuntimeError("ledger unreadable")

    monkeypatch.setattr(
        "syndicate.features.shared.paper_settlement.settlement_summary", boom)
    assert runner._settled_sample_size_by_sport() == {}


def test_malformed_buckets_do_not_break_the_derivation(monkeypatch):
    monkeypatch.setattr(
        "syndicate.features.shared.paper_settlement.settlement_summary",
        lambda *a, **k: {"by_sport": [
            "not-a-mapping",
            {"key": "mlb", "settled": "not-a-number"},
            {"key": "nfl", "settled": 77},
        ]},
    )
    assert runner._settled_sample_size_by_sport() == {"nfl": 77}


def test_an_absent_by_sport_key_yields_an_empty_map(monkeypatch):
    monkeypatch.setattr(
        "syndicate.features.shared.paper_settlement.settlement_summary",
        lambda *a, **k: {"by_venue": [{"venue": "kalshi", "settled": 474}]},
    )
    assert runner._settled_sample_size_by_sport() == {}


# ---------------------------------------------------------------------------
# THE WIRING ITSELF. Everything above tests the derivation and the sizer in
# ISOLATION -- and a mutation check proved that is not enough: deleting the two
# lines in `run_portfolio_commit` that call the derivation left every test above
# GREEN. A hook can be perfect and still never be called, which is the exact
# failure this whole file was written about.
# ---------------------------------------------------------------------------


def _row():
    return {
        "sport": "mlb",
        "event_id": "evt-1",
        "market": "h2h",
        "side": "home",
        "price": -110,
        "ev_pct": 9.0,
        "model_edge_pct": 8.0,
        "model_probability": 0.58,
        "fair_probability": 0.50,
        "score": {"price_reliability": 1.0},
    }


def test_run_portfolio_commit_ACTUALLY_PASSES_the_derived_map(tmp_path, monkeypatch):
    """Deleting the derivation call must turn THIS red.

    Asserts the value reaching `commit_portfolio`, not the value the helper can
    produce -- those are different claims and only the first one is the fix.
    """
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path))
    monkeypatch.setenv("SYNDICATE_PORTFOLIO_COMMIT_ENABLED", "1")
    monkeypatch.setattr(
        "pipeline.intelligence_state.read_layer2_shortlist",
        lambda date: {"rows": [_row()]},
    )
    monkeypatch.setattr(
        "syndicate.features.shared.paper_settlement.settlement_summary",
        lambda *a, **k: {"by_sport": [{"key": "mlb", "settled": 616}]},
    )

    seen = {}
    real = runner.commit_portfolio

    def spy(rows, **kwargs):
        seen["samples"] = kwargs.get("settled_sample_size_by_sport")
        return real(rows, **kwargs)

    monkeypatch.setattr(runner, "commit_portfolio", spy)
    runner.run_portfolio_commit("2026-08-22")

    assert "samples" in seen, "commit_portfolio was never called"
    assert seen["samples"] == {"mlb": 616}, (
        "the derived per-sport sample must REACH the sizer; got %r" % (seen["samples"],))


def test_an_explicit_map_is_not_overwritten_by_the_derivation(tmp_path, monkeypatch):
    """`None` means "work it out"; a supplied map means the caller has decided.
    Conflating them would make the argument untestable and unoverridable."""
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path))
    monkeypatch.setenv("SYNDICATE_PORTFOLIO_COMMIT_ENABLED", "1")
    monkeypatch.setattr(
        "pipeline.intelligence_state.read_layer2_shortlist",
        lambda date: {"rows": [_row()]},
    )
    monkeypatch.setattr(
        "syndicate.features.shared.paper_settlement.settlement_summary",
        lambda *a, **k: {"by_sport": [{"key": "mlb", "settled": 616}]},
    )

    seen = {}
    real = runner.commit_portfolio

    def spy(rows, **kwargs):
        seen["samples"] = kwargs.get("settled_sample_size_by_sport")
        return real(rows, **kwargs)

    monkeypatch.setattr(runner, "commit_portfolio", spy)
    runner.run_portfolio_commit("2026-08-22", settled_sample_size_by_sport={"mlb": 3})
    assert seen["samples"] == {"mlb": 3}, "an explicit map must win over the derivation"
