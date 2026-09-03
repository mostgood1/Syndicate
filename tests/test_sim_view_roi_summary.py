"""Settled ROI split by the sim's own verdict, within sport x market family.

The read side of `order-sim-view`. The write side put `sim_view` on the order;
this is the aggregate that lets `layer2-sim-disagrees`'s pre-registered question
be asked: does a row the sim CONTRADICTS settle worse than one it agrees with,
holding sport and market family fixed, with denominators reported?

Four groups of tests:

  1. the cut itself -- fixed sport and family, denominators, absent-vs-zero
  2. the traps this module has already paid for once -- venue double-counting,
     and `"none"` vs never-recorded
  3. NO SECOND DEFINITION -- ROI here must equal `settlement_summary`'s ROI on
     the same rows, because a cut that cannot be compared to the cuts beside it
     is worth less than no cut
  4. THE REACHABILITY CLAIM IS TRUE -- the published constants are checked
     against the real commit gate, so the payload cannot keep asserting a
     structural fact after the structure changes
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.paper_settlement import (
    SIM_VIEW_EV_CONDITIONED,
    SIM_VIEW_UNREACHABLE,
    SIM_VIEW_UNRECORDED,
    settlement_summary,
    sim_view_roi_summary,
)


def _order(**kw):
    base = {
        "selected_date": "2026-09-03",
        "mode": "paper",
        "venue": "paper",
        "sport": "mlb",
        "market": "h2h",
        "status": "filled",
        "outcome": "won",
        "fill_stake_dollars": 10.0,
        "pnl_dollars": 9.09,
        "sim_view": "agrees",
    }
    base.update(kw)
    return base


def _bucket(result, key):
    for b in result["by_sport_family_verdict"]:
        if b["key"] == key:
            return b
    raise AssertionError(f"no bucket {key!r}; have {[b['key'] for b in result['by_sport_family_verdict']]}")


# ---------------------------------------------------------------------------
# 1. THE CUT
# ---------------------------------------------------------------------------


def test_it_holds_sport_and_family_fixed_and_reports_denominators():
    """The whole point: `agrees` vs `disagrees` INSIDE one sport and family.

    Pooling across families cannot answer it -- `game_line` +13.28% n=296 against
    `game_total` -1.78% n=351 is a real split of the same book that has nothing
    to do with the sim.
    """
    rows = [
        _order(sim_view="agrees", outcome="won", pnl_dollars=9.09),
        _order(sim_view="agrees", outcome="won", pnl_dollars=9.09),
        _order(sim_view="agrees", outcome="lost", pnl_dollars=-10.0),
        _order(sim_view="disagrees", outcome="lost", pnl_dollars=-10.0),
        _order(sim_view="disagrees", outcome="lost", pnl_dollars=-10.0),
    ]
    out = sim_view_roi_summary(orders=rows)

    agrees = _bucket(out, "mlb | game_line | agrees")
    assert agrees["settled"] == 3
    assert agrees["staked_dollars"] == 30.0
    assert agrees["pnl_dollars"] == 8.18
    assert agrees["roi_pct"] == 27.27
    assert agrees["win_pct"] == pytest.approx(66.67)

    disagrees = _bucket(out, "mlb | game_line | disagrees")
    assert disagrees["settled"] == 2
    assert disagrees["roi_pct"] == -100.0

    # The labels are carried as fields, so a consumer never parses the key.
    assert agrees["sport"] == "mlb"
    assert agrees["market_family"] == "game_line"
    assert agrees["sim_view"] == "agrees"


def test_a_percentage_is_absent_rather_than_zero_when_nothing_settled():
    """`0.0%` on zero settled bets and `0.0%` on fifty are the same string and
    opposite facts. Inherited from `_grouped`, pinned here because this cut is
    the one most likely to be read as a finding."""
    out = sim_view_roi_summary(orders=[_order(outcome=None, status="filled")])
    bucket = _bucket(out, "mlb | game_line | agrees")
    assert bucket["settled"] == 0
    assert bucket["pending"] == 1
    assert bucket["roi_pct"] is None
    assert bucket["win_pct"] is None


def test_the_window_and_mode_filters_narrow_the_same_rows_as_the_counts():
    """The ROI must answer the window the reader asked for. A cut silently
    covering the whole ledger while the counts beside it cover seven days reads
    as one payload and is two."""
    rows = [
        _order(selected_date="2026-09-03", mode="paper"),
        _order(selected_date="2026-09-01", mode="paper"),
        _order(selected_date="2026-09-03", mode="live", venue="kalshi"),
    ]
    out = sim_view_roi_summary(selected_dates=["2026-09-03"], mode="paper", orders=rows)
    assert sum(b["orders"] for b in out["by_sport_family_verdict"]) == 1


# ---------------------------------------------------------------------------
# 2. THE TRAPS THIS MODULE HAS ALREADY PAID FOR
# ---------------------------------------------------------------------------


def test_venue_scoped_shadow_copies_are_excluded():
    """THE DOUBLE-COUNT, one level down and harder to see.

    This key carries no venue, so over the full ledger the unrestricted `paper`
    book would be pooled with its own `paper:<venue>` shadow copies -- the same
    decision counted twice. `by_market_family` and `by_sport` are already
    restricted to portfolio rows for exactly this reason; so is this.
    """
    rows = [
        _order(venue="paper"),
        _order(venue="paper:kalshi"),
        _order(venue="paper:polymarket"),
    ]
    out = sim_view_roi_summary(orders=rows)
    assert sum(b["orders"] for b in out["by_sport_family_verdict"]) == 1
    assert sum(b["settled"] for b in out["by_verdict"]) == 1


def test_never_recorded_is_its_own_bucket_and_not_the_verdict_none():
    """`"none"` is the sim ANSWERING that it has no view. `None` is an order
    placed before the field existed. Pooling them would put every pre-`cb223b62`
    bet into a verdict bucket and report the result as a finding about the sim.
    """
    rows = [
        _order(sim_view=None, outcome="lost", pnl_dollars=-10.0),
        _order(sim_view="none", outcome="won", pnl_dollars=9.09),
        _order(sim_view="", outcome="lost", pnl_dollars=-10.0),
    ]
    out = sim_view_roi_summary(orders=rows)
    verdicts = {b["sim_view"]: b for b in out["by_verdict"]}

    assert SIM_VIEW_UNRECORDED in verdicts
    assert "none" in verdicts
    assert verdicts[SIM_VIEW_UNRECORDED]["settled"] == 2, "None and '' are both unrecorded"
    assert verdicts["none"]["settled"] == 1
    assert verdicts[SIM_VIEW_UNRECORDED]["roi_pct"] != verdicts["none"]["roi_pct"]


def test_the_unrecorded_sentinel_cannot_collide_with_a_real_verdict():
    """Every verdict the board can emit is a bare identifier. The sentinel is
    not one, so it can never be shadowed by a verdict added later."""
    from tests.test_order_sim_view import KNOWN_VERDICTS

    assert not SIM_VIEW_UNRECORDED.isidentifier()
    assert SIM_VIEW_UNRECORDED not in KNOWN_VERDICTS
    assert all(v.isidentifier() for v in KNOWN_VERDICTS), (
        "a verdict stopped being a bare identifier -- re-check the sentinel"
    )


# ---------------------------------------------------------------------------
# 3. NO SECOND DEFINITION OF ROI
# ---------------------------------------------------------------------------


def test_roi_matches_settlement_summary_on_the_same_rows():
    """One ROI, or the cuts stop describing the same book.

    `_aggregate` exists in this module precisely so the portfolio total and the
    comparison total could not drift into two slightly different definitions.
    This cut has to land on the same side of that line.
    """
    rows = [
        _order(outcome="won", pnl_dollars=9.09),
        _order(outcome="lost", pnl_dollars=-10.0),
        _order(outcome="push", pnl_dollars=0.0),
        _order(outcome=None, status="filled"),
    ]
    mine = sim_view_roi_summary(orders=rows)["by_verdict"][0]
    theirs = settlement_summary(orders=rows)["total"]

    for field in ("settled", "won", "lost", "push", "pending",
                  "staked_dollars", "pnl_dollars", "roi_pct", "win_pct"):
        assert mine[field] == theirs[field], f"{field} disagrees with settlement_summary"


def test_the_three_way_unsettled_split_is_preserved():
    """`pending`, `unknown` and never-a-position are three states, not two.

    A submit the venue never answered is neither held nor gone, and it is
    exactly the row a person must check before placing anything else.
    """
    rows = [
        _order(outcome=None, status="filled"),
        _order(outcome=None, status="failed"),
    ]
    out = sim_view_roi_summary(orders=rows)
    bucket = _bucket(out, "mlb | game_line | agrees")
    assert bucket["pending"] == 1
    assert bucket["unknown"] == 1
    assert bucket["settled"] == 0


# ---------------------------------------------------------------------------
# 4. THE REACHABILITY CLAIM MUST STAY TRUE
# ---------------------------------------------------------------------------


def _board_row(edge, side="over", projected=51.0, mpo=0.60, basis=None, ev=5.0):
    projection = {"side": "over"}
    if projected is not None:
        projection["projected"] = projected
    if mpo is not None:
        projection["model_prob_over"] = mpo
    if basis:
        projection["basis"] = basis
    return {
        "sport": "ncaaf", "event_id": "e", "market": "totals", "segment": "full_game",
        "side": side, "line": 53.5, "home_team": "H", "away_team": "A",
        "commence_time": "2026-09-04T00:00:00Z",
        "quote": {"price": -110, "fair_probability": 0.52, "bookmaker": "draftkings"},
        "score": {"score": 5.1, "price_reliability": 0.82, "book_confidence": 1.0},
        "ev_pct": ev, "model_edge_pct": edge, "projection": projection,
    }


UNREACHABLE_FIXTURES = {
    "contradicts": _board_row(None, side="under", projected=67.8),
    "live_contradicts": _board_row(None, side="under", projected=67.8, basis="live_resim"),
    "unpriced": _board_row(None),
    "none": _board_row(None, projected=None, mpo=None),
}


def test_the_published_unreachable_set_is_exactly_what_the_gate_refuses():
    """THE PAYLOAD ASSERTS A STRUCTURAL FACT; this keeps it a fact.

    `verdict_reachability.unreachable` tells a reader that four buckets are
    empty BY CONSTRUCTION rather than for want of data. That claim is about the
    COMMIT GATE, which lives in another module and can change without this one
    noticing -- at which point the endpoint would be publishing a confident
    falsehood, and the empty buckets it explains would be quietly wrong.

    So the constant is checked against the gate itself, at several EVs, because
    the refusal must hold at ALL of them and not merely at the one I picked.
    """
    from syndicate.features.shared.portfolio_commit import (
        _sim_view_of,
        commit_portfolio,
        sizing_inputs_from_row,
    )

    assert set(SIM_VIEW_UNREACHABLE) == set(UNREACHABLE_FIXTURES), (
        "the published unreachable set and this test's fixtures disagree -- "
        "one of them is stale"
    )
    for verdict, row in UNREACHABLE_FIXTURES.items():
        assert _sim_view_of(row)["sim_view"] == verdict, f"fixture no longer produces {verdict}"
        # Refused by NAME, and at every EV -- an unreachable verdict that became
        # reachable at a high enough EV would be `ev_conditioned`, not unreachable.
        for ev in (1.0, 5.0, 20.0):
            priced = dict(row, ev_pct=ev)
            inputs, reason = sizing_inputs_from_row(priced)
            assert inputs is None, f"{verdict} became sizable at ev_pct={ev}"
            assert reason == "no_model_edge_pct", f"{verdict} refused as {reason} at ev_pct={ev}"
            assert not commit_portfolio([priced], selected_date="2026-09-03")["positions"]


def test_the_ev_conditioned_set_really_is_ev_conditioned():
    """`disagrees` is NOT unreachable -- it is SELECTED ON EV, which is a
    different and more dangerous thing, because the bucket fills up and looks
    like a fair sample. Refused at low EV, placed at high EV, same edge."""
    from syndicate.features.shared.portfolio_commit import _sim_view_of, commit_portfolio

    for verdict in SIM_VIEW_EV_CONDITIONED:
        basis = "live_resim" if verdict.startswith("live_") else None
        low = _board_row(-2.0, ev=5.0, basis=basis)
        high = _board_row(-2.0, ev=20.0, basis=basis)
        assert _sim_view_of(low)["sim_view"] == verdict
        assert not commit_portfolio([low], selected_date="2026-09-03")["positions"], (
            f"{verdict} at ev 5 should be refused"
        )
        assert commit_portfolio([high], selected_date="2026-09-03")["positions"], (
            f"{verdict} at ev 20 should place"
        )


def test_the_reachability_block_is_carried_in_the_payload():
    """A permanently-empty bucket and a not-yet-populated one look identical.
    The response has to say which it is, or the first reader concludes the join
    is broken -- the same instrument-blindness this repo keeps paying for."""
    block = sim_view_roi_summary(orders=[_order()])["verdict_reachability"]
    assert set(block["unreachable"]) == set(SIM_VIEW_UNREACHABLE)
    assert "no_model_edge_pct" in block["unreachable_reason"]
    assert set(block["ev_conditioned"]) == set(SIM_VIEW_EV_CONDITIONED)
    assert "ev_pct" in block["ev_conditioned_reason"]
    assert block["unrecorded_bucket"] == SIM_VIEW_UNRECORDED
    assert "none" in block["unrecorded_reason"]


def test_the_ev_conditioned_flag_travels_with_the_pooled_bucket():
    """The caveat has to be attached to the number, not only to the docs. A
    figure that needs a caveat and does not carry one gets quoted without it."""
    rows = [
        _order(sim_view="disagrees", outcome="lost", pnl_dollars=-10.0),
        _order(sim_view="agrees", outcome="won", pnl_dollars=9.09),
    ]
    pooled = {b["sim_view"]: b for b in sim_view_roi_summary(orders=rows)["by_verdict"]}
    assert pooled["disagrees"]["ev_conditioned"] is True
    assert pooled["agrees"]["ev_conditioned"] is False
