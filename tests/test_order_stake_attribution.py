"""An order records WHICH CHANNEL put the money there, not only what the sim thought.

WHY. `_SCORE_SIM_WEIGHT`'s own gate for being raised off 0.0 is "settled > 0 AND
CLV decomposed by component". As of 2026-09-04 the paper book has **638 settled
bets**, so the first half is met -- and the second half could not be run at ANY
settled count, because `stake_attribution` computes the decomposition on the plan
position and it was dropped at the `OrderRequest` boundary. The weight has been
0.125 since 2026-08-2x on a SCREEN (`score_sim_weight_impact.py`: 0/286
negative-EV rows promoted), never on the gate.

`sim_view` says what the sim THOUGHT. These say what it DID:

    stake_fraction_ev_only   what PRICE alone would have staked
    sim_share_of_stake       the sim's share of what was actually staked
    side_picked_by           "simulation" exactly when the EV-only stake is ZERO
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.execute_portfolio import _order_from_position  # noqa: E402
from syndicate.features.shared.execution_ledger import (  # noqa: E402
    _LEAN_FIELDS,
    idempotency_key,
)


def _position(**attribution):
    return {
        "sport": "mlb", "market": "h2h", "side": "away", "event_id": "e1",
        "position_key": "pk1", "home_team": "H", "away_team": "A",
        "book": "novig", "price": 120.0, "stake_dollars": 2.11, "segment": "full",
        "attribution": dict(attribution) if attribution else None,
    }


def test_the_three_fields_are_PERSISTED_not_just_carried():
    """A field the ledger drops is a field the ROI split cannot read, and the
    split is the entire reason these exist."""
    for name in ("side_picked_by", "stake_fraction_ev_only", "sim_share_of_stake"):
        assert name in _LEAN_FIELDS, f"{name} is not persisted"


def test_it_reads_the_NESTED_attribution_block():
    """THE DISCRIMINATING TEST. `portfolio_commit` puts these under
    `position["attribution"]`, NOT at the top level. A flat `position.get(...)`
    parses, ships, and reads None forever -- the column would look present and
    be inert, which is this repo's most-repeated failure."""
    order = _order_from_position(_position(
        side_picked_by="price_shopping",
        stake_fraction_ev_only=0.001328,
        sim_share_of_stake=0.9052,
    ), "2026-09-04", "paper")
    assert order.side_picked_by == "price_shopping"
    assert order.stake_fraction_ev_only == 0.001328
    assert order.sim_share_of_stake == 0.9052


def test_a_ZERO_ev_only_stake_survives_as_zero():
    """`stake_fraction_ev_only == 0.0` is not missing data -- it is the DEFINITION
    of `side_picked_by == "simulation"`: price alone would have staked nothing, so
    the position exists only because the model said so. Mapping it to None would
    erase exactly the rows the gate is about."""
    order = _order_from_position(_position(
        side_picked_by="simulation",
        stake_fraction_ev_only=0.0,
        sim_share_of_stake=1.0,
    ), "2026-09-04", "paper")
    assert order.stake_fraction_ev_only == 0.0, "a real zero was turned into None"
    assert order.side_picked_by == "simulation"
    assert order.sim_share_of_stake == 1.0


def test_no_attribution_block_records_ABSENCE_not_a_guess():
    """Orders placed before this shipped have none, and an absent channel must
    read as absent rather than be invented -- the same contract `model_edge_pct`
    already follows."""
    order = _order_from_position(_position(), "2026-09-04", "paper")
    assert order.side_picked_by is None
    assert order.stake_fraction_ev_only is None
    assert order.sim_share_of_stake is None


def test_junk_does_not_become_a_number():
    order = _order_from_position(_position(
        side_picked_by=None, stake_fraction_ev_only="", sim_share_of_stake="soon",
    ), "2026-09-04", "paper")
    assert order.stake_fraction_ev_only is None
    assert order.sim_share_of_stake is None


def test_they_are_NOT_in_the_idempotency_key():
    """A re-sized row is the same bet. If attribution entered the key, every
    board rebuild would mint a duplicate order."""
    base = _position(side_picked_by="price_shopping", stake_fraction_ev_only=0.0013,
                     sim_share_of_stake=0.90)
    other = _position(side_picked_by="simulation", stake_fraction_ev_only=0.0,
                      sim_share_of_stake=1.0)
    assert (
        idempotency_key(_order_from_position(base, "2026-09-04", "paper"))
        == idempotency_key(_order_from_position(other, "2026-09-04", "paper"))
    )
