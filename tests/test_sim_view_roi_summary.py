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
     against the real commit gate, with the allowlist env SET EXPLICITLY in
     each state, so the payload cannot assert something only CI's env makes true
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.paper_settlement import (
    SIM_VIEW_EV_CONDITIONED,
    SIM_VIEW_MARKET_FAIR_ONLY,
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


def test_LIVE_orders_are_in_the_cut_and_only_PAPER_scoped_ones_are_excluded():
    """THE RESTRICTION MUST NOT SWALLOW REAL MONEY, and it would be silent.

    `book_of` keys on a `paper:` prefix, and `run_execution` adds that prefix
    ONLY in paper mode (`execute_portfolio.py:420-431` -- in live mode the venue
    IS the scope, because suffixing produced `kalshi:kalshi` and resolved to no
    adapter). So a live order books under the bare venue and belongs to the
    portfolio book.

    Pinned because the failure would be invisible: if that suffix rule ever
    applied in live mode, this cut would quietly stop counting every real-money
    bet while still returning a confident, well-formed ROI for the paper ones.

    (Recorded 2026-09-03: a parallel lane's log entry stated that live runs book
    under `paper:kalshi`/`paper:polymarket`. They do not -- that describes the
    PAPER scoped case. Re-derived here rather than taken on trust, because it
    decides whether this cut can see live money at all.)
    """
    live = [
        _order(mode="live", venue="kalshi", outcome="won", pnl_dollars=9.09),
        _order(mode="live", venue="polymarket", outcome="lost", pnl_dollars=-10.0),
    ]
    out = sim_view_roi_summary(orders=live)
    assert sum(b["settled"] for b in out["by_sport_family_verdict"]) == 2, (
        "live orders were excluded from the ROI cut -- the portfolio-rows "
        "restriction is swallowing real money"
    )

    # ...while the PAPER venue-scoped shadow copies still are excluded.
    shadow = [_order(mode="paper", venue="paper:kalshi", outcome="won", pnl_dollars=9.09)]
    assert not sim_view_roi_summary(orders=shadow)["by_sport_family_verdict"]


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


MARKET_FAIR_ONLY_FIXTURES = {
    "contradicts": _board_row(None, side="under", projected=67.8),
    "live_contradicts": _board_row(None, side="under", projected=67.8, basis="live_resim"),
    "unpriced": _board_row(None),
    "none": _board_row(None, projected=None, mpo=None),
}

_ALLOWLIST = "SYNDICATE_PORTFOLIO_MARKET_FAIR_SPORTS"
_IN_PLAY = "SYNDICATE_PORTFOLIO_IN_PLAY_MARKET_FAIR"


def test_the_market_fair_only_set_is_exactly_the_rows_with_no_sim_edge(monkeypatch):
    """THE PAYLOAD ASSERTS A FACT ABOUT FOUR BUCKETS; this keeps it one.

    `verdict_reachability.market_fair_only` tells a reader that every order in
    those buckets was sized on market fair, never on the sim's edge. Checked
    against the commit gate itself, IN BOTH ALLOWLIST STATES, SET EXPLICITLY.

    The sentence this replaced said the buckets were "structurally empty and
    stay empty", and its test read the allowlist env implicitly. CI leaves that
    env absent, so the test stayed green while production (every sport
    allowlisted, 2026-09-16) held 324 orders in the buckets it called empty.
    A test of a claim that depends on configuration must set the configuration.
    """
    from syndicate.features.shared.portfolio_commit import (
        _sim_view_of,
        commit_portfolio,
        sizing_basis_of,
        sizing_inputs_from_row,
    )

    assert set(SIM_VIEW_MARKET_FAIR_ONLY) == set(MARKET_FAIR_ONLY_FIXTURES), (
        "the published market_fair_only set and this test's fixtures disagree -- "
        "one of them is stale"
    )
    monkeypatch.delenv(_IN_PLAY, raising=False)
    for verdict, row in MARKET_FAIR_ONLY_FIXTURES.items():
        assert _sim_view_of(row)["sim_view"] == verdict, f"fixture no longer produces {verdict}"
        assert sizing_basis_of(row) == "market_fair", verdict

        # Sport NOT allowlisted: refused by name, at every EV.
        monkeypatch.delenv(_ALLOWLIST, raising=False)
        for ev in (1.0, 5.0, 20.0):
            priced = dict(row, ev_pct=ev)
            inputs, reason = sizing_inputs_from_row(priced)
            assert inputs is None, f"{verdict} became sizable at ev_pct={ev} with no allowlist"
            assert reason == "no_model_edge_pct", f"{verdict} refused as {reason} at ev_pct={ev}"
            assert not commit_portfolio([priced], selected_date="2026-09-03")["positions"]

        # Sport allowlisted, pregame: it REACHES AN ORDER, and on market fair.
        monkeypatch.setenv(_ALLOWLIST, row["sport"])
        inputs, reason = sizing_inputs_from_row(row)
        assert inputs is not None and reason is None, f"{verdict} refused as {reason} when allowlisted"
        positions = commit_portfolio([row], selected_date="2026-09-03")["positions"]
        assert positions, f"{verdict} did not place when allowlisted"
        assert positions[0]["sizing"]["basis"] == "market_fair"
        assert positions[0]["sim_view"] == verdict

        # Sport allowlisted, in play: refused unless in-play market fair is allowed.
        live = dict(row, market_state="live", is_live=True)
        out = commit_portfolio([live], selected_date="2026-09-03")
        assert not out["positions"], f"{verdict} placed in play"
        assert out["refusals"].get("in_play_market_fair") == 1, out["refusals"]


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
    """The buckets cannot say what they hold about themselves: a
    `contradicts` bucket and an `agrees` bucket read alike, and were sized on
    different things. The response has to say so beside the numbers."""
    block = sim_view_roi_summary(orders=[_order()])["verdict_reachability"]
    # The false sentence is gone, not kept alongside the true one.
    assert "unreachable" not in block
    assert "unreachable_reason" not in block
    assert set(block["market_fair_only"]) == set(SIM_VIEW_MARKET_FAIR_ONLY)
    assert "SYNDICATE_PORTFOLIO_MARKET_FAIR_SPORTS" in block["market_fair_only_reason"]
    assert "in_play_market_fair" in block["market_fair_only_reason"]
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


def test_the_market_fair_only_flag_is_on_the_cross_and_the_pooled_buckets():
    """On the CROSS too, because the cross is the cut that gets quoted."""
    rows = [
        _order(sim_view="contradicts", market="totals", outcome="won", pnl_dollars=9.09),
        _order(sim_view="agrees", market="totals", outcome="lost", pnl_dollars=-10.0),
        _order(sim_view="none", outcome="won", pnl_dollars=9.09),
        _order(sim_view=None, outcome="won", pnl_dollars=9.09),
    ]
    out = sim_view_roi_summary(orders=rows)
    assert _bucket(out, "mlb | game_total | contradicts")["market_fair_only"] is True
    assert _bucket(out, "mlb | game_line | none")["market_fair_only"] is True
    assert _bucket(out, "mlb | game_total | agrees")["market_fair_only"] is False
    # Never recorded is not a verdict, so it is not claimed to be market fair.
    assert _bucket(out, f"mlb | game_line | {SIM_VIEW_UNRECORDED}")["market_fair_only"] is False
    pooled = {b["sim_view"]: b for b in out["by_verdict"]}
    assert pooled["contradicts"]["market_fair_only"] is True
    assert pooled["none"]["market_fair_only"] is True
    assert pooled["agrees"]["market_fair_only"] is False
    assert pooled[SIM_VIEW_UNRECORDED]["market_fair_only"] is False


# ---------------------------------------------------------------------------
# 5. THE SAMPLE IS DECISIONS, NOT ROWS
# ---------------------------------------------------------------------------


def _bet(event_id="evt-sat", side="over", line=53.5, selected_date="2026-09-16", **kw):
    """A keyable NCAAF order: the same bet on another slate date is another ROW."""
    base = dict(
        sport="ncaaf", market="totals", segment="full_game", event_id=event_id,
        side=side, line=line, book="draftkings", selected_date=selected_date,
        sim_view="none", outcome="won", pnl_dollars=9.09,
        idempotency_key=f"{event_id}|{side}|{line}|{selected_date}",
    )
    base.update(kw)
    return _order(**base)


def test_one_bet_on_three_slate_dates_is_three_rows_and_one_decision():
    """Measured 2026-09-17: 40 of 77 NCAAF bets sat on 2-3 slate dates' plans.
    Rows share one outcome, so they are one trial."""
    rows = [_bet(selected_date=d) for d in ("2026-09-15", "2026-09-16", "2026-09-17")]
    out = sim_view_roi_summary(orders=rows)
    bucket = _bucket(out, "ncaaf | game_total | none")
    assert (bucket["orders"], bucket["settled"]) == (3, 3)
    assert (bucket["decisions"], bucket["settled_decisions"]) == (1, 1)
    pooled = {b["sim_view"]: b for b in out["by_verdict"]}
    assert (pooled["none"]["decisions"], pooled["none"]["settled_decisions"]) == (1, 1)
    assert out["sample"]["decisions"] == 1


def test_a_different_line_or_side_is_a_different_decision():
    rows = [_bet(), _bet(line=54.5), _bet(side="under"), _bet(event_id="evt-other")]
    bucket = _bucket(sim_view_roi_summary(orders=rows), "ncaaf | game_total | none")
    assert (bucket["orders"], bucket["decisions"]) == (4, 4)


def test_settled_decisions_uses_the_same_settled_rule_as_the_row_counts():
    """A bet with one graded row and one pending row is settled once, and the
    pending-only bet is not settled at all -- `_grouped`'s rule, not a second one."""
    rows = [
        _bet(selected_date="2026-09-16"),
        _bet(selected_date="2026-09-17", outcome=None, status="filled", pnl_dollars=None),
        _bet(event_id="evt-pending", outcome=None, status="filled", pnl_dollars=None),
    ]
    bucket = _bucket(sim_view_roi_summary(orders=rows), "ncaaf | game_total | none")
    assert (bucket["orders"], bucket["settled"], bucket["pending"]) == (3, 1, 2)
    assert (bucket["decisions"], bucket["settled_decisions"]) == (2, 1)


def test_the_decision_counts_do_not_change_roi_or_row_counts():
    """Added BESIDE the row-based money, never instead of it: the same bet at two
    prices on two slate dates is still two stakes and two P&Ls."""
    rows = [_bet(selected_date="2026-09-15", pnl_dollars=9.09),
            _bet(selected_date="2026-09-16", pnl_dollars=8.33)]
    bucket = sim_view_roi_summary(orders=rows)["by_verdict"][0]
    theirs = settlement_summary(orders=rows)["total"]
    for field in ("settled", "won", "lost", "push", "pending",
                  "staked_dollars", "pnl_dollars", "roi_pct", "win_pct"):
        assert bucket[field] == theirs[field], f"{field} disagrees with settlement_summary"
    assert (bucket["settled"], bucket["settled_decisions"]) == (2, 1)


def test_a_bet_whose_verdict_changed_between_slate_dates_is_counted_and_named():
    """`sim_view` is recomputed per slate date, so one bet can be `unpriced` on
    Wednesday and `contradicts` on Thursday. It sits in both buckets; the payload
    says how many bets do, so the buckets are not read as independent."""
    rows = [_bet(sim_view="unpriced", selected_date="2026-09-16"),
            _bet(sim_view="contradicts", selected_date="2026-09-17"),
            _bet(event_id="evt-steady", sim_view="unpriced")]
    out = sim_view_roi_summary(orders=rows)
    assert _bucket(out, "ncaaf | game_total | unpriced")["decisions"] == 2
    assert _bucket(out, "ncaaf | game_total | contradicts")["decisions"] == 1
    assert out["sample"]["decisions"] == 2
    assert out["sample"]["decisions_in_more_than_one_verdict"] == 1
    assert "selected_date" in out["sample"]["reason"]


def test_an_unkeyable_row_is_its_own_decision_and_never_merged():
    """No event_id: the key falls back to the row's own identity, as
    `settled_decisions_by_sport` does -- dropping it would UNDERSTATE the sample."""
    rows = [_order(idempotency_key="a"), _order(idempotency_key="b")]
    bucket = _bucket(sim_view_roi_summary(orders=rows), "mlb | game_line | agrees")
    assert (bucket["orders"], bucket["decisions"]) == (2, 2)


def test_the_cut_uses_the_credibility_samples_decision_key():
    """One identity, not two: the same settled rows give the same distinct count
    through `settled_decisions_by_sport`."""
    from syndicate.features.shared.paper_settlement import settled_decisions_by_sport

    rows = [_bet(selected_date=d) for d in ("2026-09-15", "2026-09-16")] + [_bet(line=54.5)]
    out = sim_view_roi_summary(orders=rows)
    assert out["sample"]["decisions"] == settled_decisions_by_sport(rows)["ncaaf"] == 2
