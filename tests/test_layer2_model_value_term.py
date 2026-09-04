"""Rank a model-priced row on its EDGE, or on its EV?

EV IS EDGE DIVIDED BY THE PRICE. `_model_value_ev` returns
`expected_value_pct(price, model_prob)`, and near fair that is `edge / p`.
Measured on the served shortlist 2026-08-31:

    edge 10.18 -> ev 85.13   ratio  8.36   1/p =  9.62  (p=0.104)
    edge  4.11 -> ev 50.92   ratio 12.39   1/p = 14.99  (p=0.067)
    edge 12.43 -> ev 41.80   ratio  3.36   1/p =  4.18  (p=0.239)

So a SMALLER edge on a LONGER shot outranks a bigger one on a shorter shot --
4.11 points at 6.7% beats 12.43 at 24%. 23 of the top 25 were `hr_1plus`.

THE STRUCTURAL DEFECT, raised by the session that WROTE the EV path against
their own work: `blended_score` CAPS the model's influence when it arrives as
`model_edge` (`_MODEL_EDGE_MAX_POINTS`, `_SCORE_SIM_CAP_PCT`), and the same
information was then routed through `value_ev`, which has NO cap.

**THE DEFAULT IS NOW `edge`, BY USER DECISION `[2026-08-31: "rank on edge, flip
the default"]`**, superseding `[2026-08-30: "Price EV vs the model everywhere"]`
FOR THE RANKING TERM ONLY.

It shipped defaulting to the OLD behaviour first and that ordering is the point:
two Claude sessions agreeing does not reverse a user's decision, so the flag
existed to make the alternative measurable and put it to them. The default moved
only after they ruled. `=ev` is now the reverse-out, not the opt-in.
"""
from __future__ import annotations

import pytest

from syndicate.features.shared import layer2_board as lb


def test_the_default_is_edge_by_user_decision(monkeypatch):
    """`[2026-08-31]`. Absent means EDGE."""
    monkeypatch.delenv("SYNDICATE_LAYER2_MODEL_VALUE_TERM", raising=False)
    assert lb._model_value_term() == "edge"


@pytest.mark.parametrize("raw", ["", "edge", "EDGE", " Edge ", "banana", "0", "true"])
def test_unknown_cannot_silently_restore_the_amplification(monkeypatch, raw):
    """Only the exact word `ev` reverts. An unrecognised value must NOT land on
    the 1/p-amplified branch -- unknown falling to the permissive side is how a
    scoring regression arrives with nobody having chosen it."""
    monkeypatch.setenv("SYNDICATE_LAYER2_MODEL_VALUE_TERM", raw)
    assert lb._model_value_term() == "edge"


@pytest.mark.parametrize("raw", ["ev", "EV", " Ev "])
def test_the_reverse_out_still_works_without_a_deploy(monkeypatch, raw):
    """The 08-30 behaviour stays one env var away, in case the re-ranked board
    is worse in a way the simulation did not show."""
    monkeypatch.setenv("SYNDICATE_LAYER2_MODEL_VALUE_TERM", raw)
    assert lb._model_value_term() == "ev"


def test_the_two_bases_are_distinct_strings():
    """`#242`: the row must STATE which term ranked it, and the units genuinely
    differ -- probability points vs EV percent -- so the basis is load-bearing
    rather than decorative."""
    assert lb.EV_BASIS_MODEL_EDGE != lb.EV_BASIS_MODEL
    assert lb.EV_BASIS_MODEL_EDGE != lb.EV_BASIS_MARKET
    assert lb.EV_BASIS_MODEL_EDGE == "model_edge"


def test_ev_pct_is_not_the_field_being_changed():
    """`portfolio_commit` back-derives the market fair from `ev_pct`
    (`fair = (ev_pct/100 + 1)/(profit + 1)`) and refuses a row
    `no_model_edge_pct` at Kelly 0. A probability-scale number leaking into that
    field would corrupt the SIZER, not merely re-rank the board.

    Pinned by reading the source: the swap must touch `value_ev` only.
    """
    src = "".join(open(lb.__file__, encoding="utf-8").readlines())
    marker = 'if _model_value_term() == "edge" and model_edge is not None:'
    assert marker in src, "the value-term branch is gone"
    after = src[src.index(marker): src.index(marker) + 400]
    # `value_ev` is assigned FROM the model edge. Deliberately not pinned to an
    # exact literal: `2026-09-04` wrapped it in `_compress_model_value(...)` to
    # bound the ranking contribution, and a source-text pin failed on a change
    # that PRESERVED this test's whole intent. Pin the property -- the edge
    # reaches `value_ev` and nothing else -- not the spelling.
    assert "value_ev" in after and "model_edge" in after, after
    assert 'candidate["ev_pct"] = model_edge' not in src, (
        "the edge leaked into ev_pct -- portfolio_commit would re-derive a "
        "fair from a probability-scale number"
    )
    # The load-bearing half, stated positively: `ev_pct` carries the MARKET EV.
    assert 'candidate["ev_pct"] = ev' in src
    assert 'candidate["ev_pct"] = value_ev' not in src
