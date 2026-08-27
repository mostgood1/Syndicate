"""NCAAF must fill the SHARED contract's `predictions`, not just its own display list.

MEASURED ON PRODUCTION 2026-08-27, all 51 week-1 cards. The numbers were on the
card the whole time -- and in the wrong place:

    shared_predictions.home_mean     null   |  metrics["Home mean"]        30.3
    shared_predictions.away_mean     null   |  metrics["Away mean"]        20.0
    shared_predictions.margin_mean   null   |  metrics["Projected spread"] TCU by 10.3
    shared_predictions.total_mean    null   |  metrics["Projected total"]  50.3
    shared_predictions...home_win     0.8   |  the ONLY field that was set

`metrics` is a DISPLAY list of label/value pairs. `shared_predictions` is what
Layer 1, Layer 2, the compact cards and the market board read, so every
cross-sport consumer saw a projected score of nothing and no projected spread
or total -- on a betting product, the two numbers a line is compared against.

`publication_adapter._shared_predictions` reads `predictions`, `sim.score`,
`score` and `sim.periods.full`. NCAAF set NONE of them. Its own docstring
records the identical defect for NFL one sport over, which is why these tests
assert the CONTRACT rather than the card's internals.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.publication_adapter import _shared_predictions


def _ncaaf_card(**overrides):
    """The shape `ncaaf/cards.py` now emits, with the real TCU/UNC numbers."""
    card = {
        "predictions": {
            "home_mean": 30.3,
            "away_mean": 20.0,
            "margin_mean": 10.263,
            "total_mean": 50.337,
            "margin_stdev": 13.291,
            "total_stdev": 11.719,
            "probabilities": {
                "home_win": 0.8,
                "away_win": 0.2,
                "home_cover": 0.5324,
                "away_cover": 0.4676,
                "total_over": 0.6165,
                "total_under": 0.3835,
            },
        }
    }
    card.update(overrides)
    return card


def test_all_four_projection_fields_reach_the_contract():
    """The measured failure, pinned as the four fields that were null."""
    shared = _shared_predictions(_ncaaf_card())
    assert shared["home_mean"] == pytest.approx(30.3)
    assert shared["away_mean"] == pytest.approx(20.0)
    assert shared["margin_mean"] == pytest.approx(10.263)
    assert shared["total_mean"] == pytest.approx(50.337)


def test_cover_and_total_probabilities_reach_the_contract():
    """`home_win` was the ONLY probability production served; the rest were null."""
    probs = _shared_predictions(_ncaaf_card())["probabilities"]
    for key in ("home_win", "away_win", "home_cover", "away_cover", "total_over", "total_under"):
        assert probs.get(key) is not None, f"{key} is null in the shared contract"
    assert probs["home_cover"] + probs["away_cover"] == pytest.approx(1.0, abs=1e-3)
    assert probs["total_over"] + probs["total_under"] == pytest.approx(1.0, abs=1e-3)


def test_a_card_with_no_projection_still_yields_nulls_not_zeros():
    """ABSENT MUST STAY ABSENT. A zeroed projection reads as a real one.

    `model_engine_standard.md` exists because a neutral default is
    indistinguishable from a working value at every level except the data.
    """
    shared = _shared_predictions({"predictions": {}})
    assert shared.get("home_mean") is None
    assert shared.get("total_mean") is None
    assert shared.get("margin_mean") is None


def test_margin_and_total_derive_when_only_the_score_means_are_present():
    """The adapter's documented last resort, kept working for NCAAF.

    A projected total IS the sum of the projected scores and a projected margin
    IS their difference, so a producer supplying only the two means still
    yields four usable fields.
    """
    shared = _shared_predictions({"predictions": {"home_mean": 30.0, "away_mean": 20.0}})
    assert shared["total_mean"] == pytest.approx(50.0)
    assert shared["margin_mean"] == pytest.approx(10.0)


def test_a_real_producer_value_is_never_overwritten_by_the_derived_one():
    """Ordering matters: derivation may only fill a hole.

    The sim's `margin_mean` is the mean of simulated margins, which is not
    obliged to equal home_mean - away_mean once each is rounded for display.
    The producer's number must win.
    """
    shared = _shared_predictions(
        {"predictions": {"home_mean": 30.3, "away_mean": 20.0, "margin_mean": 10.263, "total_mean": 50.337}}
    )
    assert shared["margin_mean"] == pytest.approx(10.263)
    assert shared["total_mean"] == pytest.approx(50.337)


# ---------------------------------------------------------------------------
# THE PRODUCER SIDE. The tests above exercise the ADAPTER with a hand-built
# card, which proves the mapping and NOT that NCAAF feeds it. A first version
# of this fix defined the block in one builder and referenced it from another
# -- a NameError that every adapter test above passed straight through.
# ---------------------------------------------------------------------------

import ast as _ast

from syndicate.features.ncaaf import cards as _ncaaf_cards


class _Projection:
    home_score_mean = 30.3
    away_score_mean = 20.037
    margin_mean = 10.263
    total_mean = 50.337
    margin_stdev = 13.291
    total_stdev = 11.719
    home_win_rate = 0.8


def test_helper_publishes_all_four_means_from_a_projection():
    block = _ncaaf_cards._ncaaf_shared_predictions_block(_Projection())
    assert block["home_mean"] == pytest.approx(30.3)
    assert block["away_mean"] == pytest.approx(20.037)
    assert block["margin_mean"] == pytest.approx(10.263)
    assert block["total_mean"] == pytest.approx(50.337)
    assert block["probabilities"]["home_win"] == pytest.approx(0.8)
    assert block["probabilities"]["away_win"] == pytest.approx(0.2)


def test_cover_probabilities_need_a_market_line_and_stay_none_without_one():
    """Absent must stay absent -- never a neutral 0.5 that reads as a real edge."""
    without = _ncaaf_cards._ncaaf_shared_predictions_block(_Projection())
    assert without["probabilities"]["home_cover"] is None
    assert without["probabilities"]["total_over"] is None

    with_lines = _ncaaf_cards._ncaaf_shared_predictions_block(
        _Projection(), market_margin=-9.18, market_total=46.86
    )
    assert with_lines["probabilities"]["home_cover"] is not None
    assert with_lines["probabilities"]["total_over"] is not None
    # The model's total (50.3) is well above the market line (46.9), so over
    # must be the favoured side. A sign flip here would invert every total edge.
    assert with_lines["probabilities"]["total_over"] > 0.5


def test_a_projection_of_none_yields_an_empty_block_not_zeros():
    assert _ncaaf_cards._ncaaf_shared_predictions_block(None) == {}


def test_every_ncaaf_card_contract_builder_calls_the_helper():
    """THE REACHABILITY GUARD, and the reason it is structural.

    There are three NCAAF card-contract builders. A per-site copy of this logic
    is how one of them silently keeps the old all-null behaviour, and no
    output-level test would catch it unless it happened to exercise that exact
    builder. This asserts the call exists in each one.
    """
    source = Path(_ncaaf_cards.__file__).read_text(encoding="utf-8")
    tree = _ast.parse(source)
    builders = {
        "_build_ncaaf_card_contract",
        "_build_smartsim_ncaaf_card_contract",
        "_build_smartsim2_standalone_ncaaf_card_contract",
    }
    seen = set()
    for node in _ast.walk(tree):
        if isinstance(node, _ast.FunctionDef) and node.name in builders:
            calls = {
                n.func.id
                for n in _ast.walk(node)
                if isinstance(n, _ast.Call) and isinstance(n.func, _ast.Name)
            }
            if "_ncaaf_shared_predictions_block" in calls:
                seen.add(node.name)
    assert seen == builders, f"builders NOT publishing shared predictions: {sorted(builders - seen)}"


def test_predictions_is_a_TOP_LEVEL_key_of_every_builder_s_returned_game():
    """PLACEMENT, not presence -- the gap that shipped a no-op to production.

    The first cut put `predictions` inside the `ncaaf_card` sub-dict. Every
    test above passed, the deploy went out clean, and production still served
    `shared_predictions.margin_mean` null on 51/51 -- because
    `publication_adapter._shared_predictions` reads `game["predictions"]` at the
    TOP level and nothing reads `game["ncaaf_card"]["predictions"]`.

    "The builder calls the helper" was true and useless. This asserts the key
    lands where the reader looks.
    """
    source = Path(_ncaaf_cards.__file__).read_text(encoding="utf-8")
    tree = _ast.parse(source)
    builders = {
        "_build_ncaaf_card_contract",
        "_build_smartsim_ncaaf_card_contract",
        "_build_smartsim2_standalone_ncaaf_card_contract",
    }
    checked = set()
    for node in _ast.walk(tree):
        if not (isinstance(node, _ast.FunctionDef) and node.name in builders):
            continue
        for ret in (n for n in _ast.walk(node) if isinstance(n, _ast.Return)):
            if not isinstance(ret.value, _ast.Dict):
                continue
            top_keys = {
                k.value for k in ret.value.keys
                if isinstance(k, _ast.Constant) and isinstance(k.value, str)
            }
            if "ncaaf_card" in top_keys or "scoreboard" in top_keys:
                assert "predictions" in top_keys, (
                    f"{node.name} returns a game dict whose TOP-LEVEL keys do not include "
                    f"'predictions'; the adapter will not see it. keys={sorted(top_keys)[:12]}"
                )
                checked.add(node.name)
    assert checked == builders, f"never verified the returned dict for: {sorted(builders - checked)}"


# ---------------------------------------------------------------------------
# THE ENGINE PATH. Found by session syndicate-27 while fixing a NameError I
# introduced in 16673341: two of three builders passed a bare `projection` that
# they never bind. Their fix (`row.get("projection")`) was right; their question
# was whether `{}` is the intended end state for those paths.
#
# BET ROW: yes. A wager is not a game projection.
# ENGINE ROW: no. It carries the projection in COLUMNS -- predicted_home_points,
# predicted_away_points, predicted_total_points, predicted_win_margin,
# home_win_prob -- just not in the shape the helper reads. It was never a data
# gap.
# ---------------------------------------------------------------------------

def _engine_row(**overrides):
    row = {
        "predicted_home_points": "31.4",
        "predicted_away_points": "24.1",
        "predicted_total_points": "55.5",
        "predicted_win_margin": "7.3",
        "home_win_prob": "0.63",
    }
    row.update(overrides)
    return row


def test_an_engine_row_publishes_a_real_projection():
    block = _ncaaf_cards._ncaaf_shared_predictions_block(
        _ncaaf_cards._engine_row_projection(_engine_row())
    )
    assert block["home_mean"] == pytest.approx(31.4)
    assert block["away_mean"] == pytest.approx(24.1)
    assert block["margin_mean"] == pytest.approx(7.3)
    assert block["total_mean"] == pytest.approx(55.5)
    assert block["probabilities"]["home_win"] == pytest.approx(0.63)


def test_the_margin_is_derived_when_the_column_is_absent():
    row = _engine_row()
    row.pop("predicted_win_margin")
    block = _ncaaf_cards._ncaaf_shared_predictions_block(_ncaaf_cards._engine_row_projection(row))
    assert block["margin_mean"] == pytest.approx(7.3)


def test_engine_rows_have_no_dispersion_so_cover_probabilities_stay_none():
    """A cover probability needs a stdev. Computing one from a fabricated
    spread would put a number on the board that no model produced."""
    block = _ncaaf_cards._ncaaf_shared_predictions_block(
        _ncaaf_cards._engine_row_projection(_engine_row()),
        market_margin=5.5, market_total=52.5,
    )
    assert block["probabilities"]["home_cover"] is None
    assert block["probabilities"]["total_over"] is None


def test_a_row_with_no_prediction_columns_yields_no_projection():
    assert _ncaaf_cards._engine_row_projection({}) is None
    assert _ncaaf_cards._ncaaf_shared_predictions_block(None) == {}


def test_no_builder_passes_a_name_it_does_not_bind():
    """THE NameError, pinned. Two of three builders passed a bare `projection`
    that neither binds, so every call raised. It survived review because all
    three call sites read identically and one of them really is correct."""
    import ast as _a
    tree = _a.parse(Path(_ncaaf_cards.__file__).read_text(encoding="utf-8"))
    for node in _a.walk(tree):
        if not (isinstance(node, _a.FunctionDef) and node.name.startswith("_build_")):
            continue
        bound = {a.arg for a in node.args.args} | {
            t.id for n in _a.walk(node) for t in _a.walk(n)
            if isinstance(t, _a.Name) and isinstance(t.ctx, _a.Store)
        }
        for call in (n for n in _a.walk(node) if isinstance(n, _a.Call)):
            if isinstance(call.func, _a.Name) and call.func.id == "_ncaaf_shared_predictions_block":
                for arg in call.args:
                    if isinstance(arg, _a.Name):
                        assert arg.id in bound, (
                            f"{node.name} passes unbound name {arg.id!r} -- NameError at runtime"
                        )
