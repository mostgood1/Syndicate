"""An order records THE SIM'S VERDICT on the row it came from, not just its rating.

`layer2-sim-disagrees` measured 71 of 141 NCAAF totals rows (50%) pointing the
opposite way to the sim, 21 of them carrying a positive score -- and then
declined to put a score penalty on any of it, because the measurement that would
SIZE one does not exist: settled ROI of contradicted rows against agreeing ones,
within a sport and market family. That measurement needs the verdict recorded at
COMMIT TIME; nothing recovers it afterwards, because `sim_view` is a function of
the row's `projection`, `side` and `line` and the plan holding those is rewritten
on every board build.

The suite is in four parts:

  1. the verdict is computed by the BOARD'S OWN function, not a copy of its rule
  2. it survives the position -> OrderRequest -> ledger record chain
  3. absence survives as absence, and `"none"` never collapses into `None`
  4. WHAT IS STILL UNREACHABLE -- the commit gate refuses the exact rows a
     contradiction lives on, so three of the nine verdicts can never appear on
     a stored order and the `contradicts` arm of the pre-registered measurement
     has a structurally empty denominator. Pinned here so that a change to that
     gate turns this file red rather than silently changing what the
     measurement means.
"""

from __future__ import annotations

import pytest

from pipeline.execute_portfolio import _order_from_position
from syndicate.features.shared.execution_ledger import _LEAN_FIELDS, OrderRequest, idempotency_key
from syndicate.features.shared.portfolio_commit import (
    _SIM_VIEW_FIELDS,
    _sim_view_of,
    sizing_inputs_from_row,
)


# EVERY VERDICT THE BOARD CAN PUBLISH, read off `_layer2_board_columns` and
# pinned below. An order carries one of these strings and a settled-ROI split
# groups on them, so the SET is a contract rather than an implementation detail.
KNOWN_VERDICTS = {
    "agrees", "live_agrees",
    "disagrees", "live_disagrees",
    "neutral",
    "contradicts", "live_contradicts",
    # `36161e83`: "the sim has a view it could not PRICE" (typically a
    # one-sided market, so there is no two-sided fair) split away from "the sim
    # has no view at all". Both reach the unreachability test below, because
    # both live in the branch the commit gate refuses.
    "unpriced",
    "none",
}


def _row(**overrides):
    """A Layer 2 shortlist row, in the shape `portfolio_commit` prices."""
    projection = {"side": "over", "projected": 51.0, "model_prob_over": 0.60}
    projection.update(overrides.pop("projection", {}) or {})
    row = {
        "sport": "ncaaf",
        "event_id": "evt-1",
        "market": "totals",
        "segment": "full_game",
        "side": "over",
        "line": 53.5,
        "home_team": "Home",
        "away_team": "Away",
        "quote": {"price": -110, "fair_probability": 0.52, "bookmaker": "draftkings"},
        "score": {"score": 5.1, "price_reliability": 0.82, "book_confidence": 1.0},
        "ev_pct": 5.0,
        "model_edge_pct": 3.0,
        "projection": projection,
    }
    row.update(overrides)
    return row


def _position(**overrides):
    position = {
        "position_key": "pk-1",
        "event_id": "evt-1",
        "market": "totals",
        "side": "over",
        "sport": "ncaaf",
        "price": -110.0,
        "stake_dollars": 5.0,
        "line": 53.5,
    }
    position.update(overrides)
    return position


# ---------------------------------------------------------------------------
# 1. ONE RULE, ONE IMPLEMENTATION
# ---------------------------------------------------------------------------


def test_the_verdict_comes_from_the_boards_own_function():
    """The coupling is the point, so a rename must be a RED TEST here.

    `_sim_view_of` imports `_layer2_board_columns` at module scope with no
    `try` around it, precisely so a rename fails loudly instead of degrading to
    a null verdict on every order. A silent null is indistinguishable from "the
    sim had no view", which is the one distinction these fields exist to carry.
    """
    from syndicate.features.shared import layer2_board

    columns = layer2_board._layer2_board_columns(_row(), {}, {})
    assert "sim_view" in columns, (
        "the board no longer publishes `sim_view` under that name -- "
        "`portfolio_commit._sim_view_of` reads exactly this key"
    )

    # AND THE VOCABULARY, not only the key. `36161e83` split `none` into
    # `none` / `unpriced` hours after this lane opened, expressly because the
    # field was about to be persisted -- and the rename surfaced as a failure
    # in a downstream value assertion rather than at the coupling it actually
    # broke. A new verdict is fine and expected; it just has to be a DECISION,
    # because every stored order is stamped with one of these and a settled-ROI
    # cut groups on them.
    assert KNOWN_VERDICTS == {
        "agrees", "live_agrees",
        "disagrees", "live_disagrees",
        "neutral",
        "contradicts", "live_contradicts",
        "unpriced",
        "none",
    }, (
        "the board's `sim_view` vocabulary changed. Orders are stamped with "
        "these values and grouped on them: update KNOWN_VERDICTS, then check "
        "whether the new verdict can reach an order at all -- see "
        "test_a_contradicted_row_still_cannot_become_an_order"
    )


@pytest.mark.parametrize(
    "expected, row",
    [
        # A RATING claim: the sim likes / dislikes this side vs. the price.
        ("agrees", _row(model_edge_pct=3.0)),
        ("disagrees", _row(model_edge_pct=-1.0)),
        # Exactly zero is the sim DECLINING a view, not endorsing one.
        ("neutral", _row(model_edge_pct=0.0)),
        # A DIRECTION claim: projection points the other way from the side.
        ("contradicts", _row(model_edge_pct=None, side="under", projection={"projected": 67.8})),
        # NO PRICED EDGE, BUT THE SIM DID HAVE A VIEW -- typically a one-sided
        # market, so there is no two-sided fair to price against. `36161e83`
        # split this away from `none` precisely so this field could be
        # persisted without conflating the two.
        ("unpriced", _row(model_edge_pct=None, projection={"projected": None})),
        # NO MODEL AT ALL. Every model number has to be gone, not just the
        # edge -- a `projected` or a `model_prob_over` is enough to make it
        # `unpriced`.
        ("none", _row(model_edge_pct=None, projection={"projected": None, "model_prob_over": None})),
        # Same verdicts, from the LIVE re-sim, and they must say so.
        ("live_agrees", _row(model_edge_pct=3.0, projection={"basis": "live_resim"})),
        ("live_disagrees", _row(model_edge_pct=-1.0, projection={"basis": "live_resim"})),
    ],
)
def test_every_verdict_class_reaches_the_position(expected, row):
    assert _sim_view_of(row)["sim_view"] == expected


def test_the_gap_is_carried_only_on_a_contradiction():
    """`sim_line_gap` is `projected - line` and means nothing off a contradiction."""
    contradicted = _sim_view_of(
        _row(model_edge_pct=None, side="under", projection={"projected": 67.8})
    )
    assert contradicted["sim_view"] == "contradicts"
    assert contradicted["sim_line_gap"] == pytest.approx(67.8 - 53.5)

    assert _sim_view_of(_row(model_edge_pct=3.0))["sim_line_gap"] is None


def test_railed_is_orthogonal_to_the_verdict():
    """A row can be `agrees` AND railed; folding them loses whichever came second.

    `WIN% 0%` sat beside a recommended moneyline on the served board 2026-09-03
    (Rutgers, -3233). The sim did not dissent there -- it returned a certainty,
    and nothing in `agrees`/`disagrees`/`none` describes that.
    """
    railed = _sim_view_of(_row(model_edge_pct=3.0, projection={"model_prob_over": 0.995}))
    assert railed["sim_view"] == "agrees"
    assert railed["sim_probability_railed"] is True

    on_scale = _sim_view_of(_row(model_edge_pct=3.0, projection={"model_prob_over": 0.60}))
    assert on_scale["sim_probability_railed"] is False


# ---------------------------------------------------------------------------
# 2. THE CHAIN: position -> OrderRequest -> persisted record
# ---------------------------------------------------------------------------


def test_the_boundary_that_dropped_the_model_fields_does_not_drop_these():
    """`_order_from_position` builds from an explicit field list.

    That list is exactly where `model_edge_pct` and `ev_pct` were being lost
    before `04187cdf`, with everything upstream correct -- so it is where these
    are most likely to be lost too.
    """
    request = _order_from_position(
        _position(sim_view="contradicts", sim_line_gap=14.3, sim_probability_railed=True),
        "2026-09-03",
        "paper",
    )
    assert request is not None
    assert request.sim_view == "contradicts"
    assert request.sim_line_gap == pytest.approx(14.3)
    assert request.sim_probability_railed is True


def test_all_three_are_persisted_and_not_only_carried():
    """`record_order` writes `{k: record[k] for k in _LEAN_FIELDS}`.

    A field absent from that tuple is computed, copied onto the request, put in
    the record -- and then dropped on the way to the store, with every layer
    above it looking correct. Presence on the dataclass is not persistence.
    """
    for field in _SIM_VIEW_FIELDS:
        assert field in _LEAN_FIELDS, f"{field} is carried but never stored"


def test_the_record_round_trips_through_the_store(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path))
    monkeypatch.delenv("SYNDICATE_REFRESH_STATE_BACKEND", raising=False)
    from syndicate.features.shared.execution_ledger import _load, record_order

    record_order(
        OrderRequest(
            position_key="pk-round-trip",
            selected_date="2026-09-03",
            venue="paper",
            sport="ncaaf",
            event_id="evt-1",
            market="totals",
            side="over",
            requested_price=-110.0,
            requested_stake_dollars=5.0,
            sim_view="disagrees",
            sim_probability_railed=False,
        )
    )
    stored = [
        o
        for o in (_load().get("orders") or [])
        if o.get("position_key") == "pk-round-trip"
    ]
    assert len(stored) == 1
    assert stored[0]["sim_view"] == "disagrees"
    assert stored[0]["sim_probability_railed"] is False
    assert stored[0]["sim_line_gap"] is None


# ---------------------------------------------------------------------------
# 3. ABSENCE SURVIVES AS ABSENCE
# ---------------------------------------------------------------------------


def test_none_the_string_is_not_none_the_absence():
    """The whole point of the column, and the easiest thing to destroy.

    `"none"` is the sim ANSWERING that it has no view on this row. `None` is the
    order predating the field. Reporting a settled ROI for "no sim view" that
    silently includes every pre-2026-09-03 bet would be the wrong number with no
    way to notice.
    """
    said_none = _order_from_position(_position(sim_view="none"), "2026-09-03", "paper")
    never_asked = _order_from_position(_position(), "2026-09-03", "paper")

    assert said_none.sim_view == "none"
    assert never_asked.sim_view is None
    assert said_none.sim_view != never_asked.sim_view


def test_a_missing_verdict_never_becomes_the_string_None():
    """A `str()` cast would put the literal "None" in the ledger, and a later
    `GROUP BY sim_view` would show it as a verdict nobody ever wrote."""
    request = _order_from_position(_position(sim_view=None), "2026-09-03", "paper")
    assert request.sim_view is None

    blank = _order_from_position(_position(sim_view="   "), "2026-09-03", "paper")
    assert blank.sim_view is None


def test_railed_stays_tri_state_across_the_boundary():
    """`None` must not be folded onto `False`.

    `False` says the rail check RAN and the probability was on-scale; `None`
    says it never ran. Mapping absent onto the permissive branch would report a
    check that never happened as a check that passed.
    """
    assert _order_from_position(_position(), "2026-09-03", "paper").sim_probability_railed is None
    assert (
        _order_from_position(
            _position(sim_probability_railed=False), "2026-09-03", "paper"
        ).sim_probability_railed
        is False
    )
    assert (
        _order_from_position(
            _position(sim_probability_railed=True), "2026-09-03", "paper"
        ).sim_probability_railed
        is True
    )


def test_a_malformed_row_is_still_a_real_verdict():
    """A row the board can READ but has nothing to say about answers `"none"`.

    Junk in `quote`/`score` does not stop the verdict being computed --
    `_layer2_board_columns` guards both -- so this is the sim answering, and it
    must not be confused with the `None` below.
    """
    assert _sim_view_of({"quote": "not a mapping", "score": None}) == {
        "sim_view": "none",
        "sim_line_gap": None,
        "sim_probability_railed": False,
    }


def test_a_verdict_that_RAISED_records_absence_not_the_string_none(monkeypatch):
    """The `except` branch, exercised rather than assumed.

    `off != on`: a defensive branch nothing can reach is decoration, and one
    that silently returns the wrong sentinel is worse than no branch at all.
    The failure has to read as "we never got a verdict" (`None`), never as "the
    sim was asked and had none" (`"none"`) -- those are different rows in any
    settled-ROI cut.
    """
    from syndicate.features.shared import portfolio_commit

    def _boom(*_args, **_kwargs):
        raise RuntimeError("board column builder blew up")

    monkeypatch.setattr(portfolio_commit, "_layer2_board_columns", _boom)
    assert portfolio_commit._sim_view_of(_row()) == {
        "sim_view": None,
        "sim_line_gap": None,
        "sim_probability_railed": None,
    }


# ---------------------------------------------------------------------------
# 4. THE HAZARD, AND WHAT IS STILL UNREACHABLE
# ---------------------------------------------------------------------------


def test_the_verdict_is_not_part_of_a_bets_identity():
    """`idempotency_key` must be blind to these, or a re-scored row mints a new
    key and the same bet is placed twice. It is built from an explicit field
    list, so this holds by construction -- pinned because the cost of it not
    holding is a duplicate bet with real money behind it."""
    absent = _order_from_position(_position(), "2026-09-03", "paper")
    present = _order_from_position(
        _position(sim_view="agrees", sim_line_gap=9.9, sim_probability_railed=True),
        "2026-09-03",
        "paper",
    )
    different = _order_from_position(
        _position(sim_view="contradicts", sim_line_gap=-3.1, sim_probability_railed=False),
        "2026-09-03",
        "paper",
    )
    assert idempotency_key(absent) == idempotency_key(present) == idempotency_key(different)


def test_a_contradicted_row_still_cannot_become_an_order():
    """THREE OF THE NINE VERDICTS HAVE A STRUCTURALLY EMPTY DENOMINATOR.

    `contradicts`, `unpriced` and `none` are computed in exactly the branch
    where `model_edge_pct` is None, and `sizing_inputs_from_row` refuses that
    row BY NAME (`no_model_edge_pct`) before anything is sized. So persisting
    the verdict is NECESSARY and NOT SUFFICIENT: `contradicts`-vs-`agrees`
    settled ROI cannot accumulate at all while this gate stands, no matter how
    long the ledger runs. Only `agrees`, `disagrees` and `neutral` (and their
    `live_` forms) can ever appear on a stored order.

    Asserted rather than written down, so that changing the gate turns this red
    and whoever changes it reads the note instead of quietly redefining what the
    measurement is measuring.
    """
    for verdict, row in (
        ("contradicts", _row(model_edge_pct=None, side="under", projection={"projected": 67.8})),
        ("unpriced", _row(model_edge_pct=None, projection={"projected": None})),
        ("none", _row(model_edge_pct=None, projection={"projected": None, "model_prob_over": None})),
    ):
        assert _sim_view_of(row)["sim_view"] == verdict
        inputs, reason = sizing_inputs_from_row(row)
        assert inputs is None
        assert reason == "no_model_edge_pct"


def test_the_disagrees_arm_is_conditioned_on_ev_not_merely_present():
    """A DISAGREEMENT ONLY REACHES THE BOOK IF A LARGE EV CARRIES IT.

    Unlike `contradicts`, `disagrees` rows can be placed -- but not uniformly.
    `sizing_inputs_from_row` admits any negative edge, and the stake gates then
    refuse the row (`below_min_stake`, then `zero_kelly_stake`) as the sim's
    probability falls below what the price implies. Measured through the real
    `commit_portfolio` at price -110, default settings:

        ev_pct   most-negative model_edge_pct that still places
           5.0   -0.5      (-1.0 refused below_min_stake)
          10.0   -2.0      (-5.0 refused below_min_stake)
          20.0   -5.0      (nothing in range refused)

    So `disagrees` orders are a BIASED SAMPLE of disagreements: they are the
    ones paired with a big EV. Any ROI comparison against `agrees` has to
    control for `ev_pct` -- which is on the order, from `04187cdf` -- or it is
    measuring the EV gap and calling it a sim effect.
    """
    from syndicate.features.shared.portfolio_commit import commit_portfolio

    def places(edge, ev):
        row = _row(model_edge_pct=edge, ev_pct=ev)
        result = commit_portfolio([row], selected_date="2026-09-03")
        return bool(result.get("positions"))

    # An agreement places at either EV; a like-sized disagreement does not.
    assert places(3.0, 5.0)
    assert places(-0.5, 5.0), "a mild disagreement, well funded by EV, is placeable"
    assert not places(-2.0, 5.0), "the same disagreement at low EV is refused"
    assert places(-2.0, 20.0), "and placeable again once the EV is large enough"
