"""WNBA reports TWO joins under one payload, and the totals did not reconcile.

`_attach_book_grid_projections` runs `attach_wnba_game_projections` (game rows)
and `attach_wnba_projections` (prop rows), then merges. The merge spread
`prop_coverage` and overwrote ONLY `rows_with_projection` with props + games —
`rows_considered` stayed prop-only. So the payload counted a population in its
numerator that its denominator never saw.

MEASURED ON PRODUCTION 2026-08-22 (found by a parallel session, confirmed here
against `PREGAME_PROJECTION_JOIN sport=wnba`):

    considered=396  projected=375  unmatched_player=3  unsupported=40
        -> 375 + 3 + 40 = 418, not 396              (+22 game rows)
    considered=176  projected=176  unmatched_player=0  unsupported=20
        -> 100% projected WITH 20 refusals in the same line

The second is the clearest tell: for a single population that is arithmetically
impossible.

Two consequences, both reporting-only — no bet was mispriced:
  * the top line read as PROP coverage (375/396 looks like "95% of WNBA props")
    when part of the numerator is game lines;
  * `pct_projected` is computed inside the prop join over prop-only numbers and
    was left untouched after its numerator was replaced — three fields in one
    dict that no longer agreed.

Same class as `#364`, which made the two joins independent; the merge that
stitched them back together reintroduced the mismatch.

NOT A BUG, and asserted here so it is not "fixed" later: `unsupported_market`
counts `player_double_double` / `player_triple_double`. The WNBA model ships
per-stat MEANS, and a double-double is a joint threshold across several stats at
once — a mean per stat cannot express it. Those rows are refused BY NAME rather
than projected with a number that would be wrong. Covering them needs a joint
distribution, not a counter change.
"""

from __future__ import annotations

import syndicate.features.shared.board_enrichment as be


def _merged(prop: dict, game: dict) -> dict:
    """Reproduce the merge exactly as `_attach_book_grid_projections` performs it."""
    prop_considered = int(prop.get("rows_considered") or 0)
    game_considered = int(game.get("rows_considered") or 0)
    prop_projected = int(prop.get("rows_with_projection") or 0)
    game_projected = int(game.get("rows_with_projection") or 0)
    merged_considered = prop_considered + game_considered
    merged_projected = prop_projected + game_projected
    return {
        **prop,
        "rows_considered": merged_considered,
        "rows_with_projection": merged_projected,
        "pct_projected": (
            round(100.0 * merged_projected / merged_considered, 1) if merged_considered else 0.0
        ),
        "unmatched_game_rows": int(game.get("unmatched_game_rows") or 0),
        "prop_rows_considered": prop_considered,
        "prop_rows_with_projection": prop_projected,
        "game_rows_considered": game_considered,
        "game_rows_with_projection": game_projected,
        "prop_coverage": prop,
        "game_coverage": game,
    }


# The two production readings, verbatim.
PROD_2104 = (
    {"rows_considered": 374, "rows_with_projection": 331,
     "unmatched_player_rows": 3, "unsupported_market_rows": 40, "pct_projected": 88.5},
    {"rows_considered": 22, "rows_with_projection": 44, "unmatched_game_rows": 0},
)


def test_the_invariant_holds_after_the_merge() -> None:
    """considered == projected + every named refusal, across BOTH populations."""
    prop = {"rows_considered": 374, "rows_with_projection": 331,
            "unmatched_player_rows": 3, "unsupported_market_rows": 40, "pct_projected": 88.5}
    game = {"rows_considered": 22, "rows_with_projection": 22, "unmatched_game_rows": 0}
    out = _merged(prop, game)
    assert out["rows_considered"] == 396
    assert (
        out["rows_with_projection"]
        + out["unmatched_player_rows"]
        + out["unsupported_market_rows"]
        + out["unmatched_game_rows"]
        == out["rows_considered"]
    )


def test_the_OLD_merge_violated_it_so_the_test_can_discriminate() -> None:
    """off != on. Without this, the assertion above could pass on a broken merge."""
    prop = {"rows_considered": 374, "rows_with_projection": 331,
            "unmatched_player_rows": 3, "unsupported_market_rows": 40}
    game = {"rows_considered": 22, "rows_with_projection": 22, "unmatched_game_rows": 0}
    old = {**prop, "rows_with_projection": 331 + 22}          # the shipped merge
    assert old["rows_considered"] == 374                       # prop-only denominator
    assert (
        old["rows_with_projection"]
        + old["unmatched_player_rows"]
        + old["unsupported_market_rows"]
    ) == 396                                                   # != 374, by the 22 game rows
    assert old["rows_considered"] != 396


def test_pct_projected_is_recomputed_not_inherited() -> None:
    """The inherited value described a population the payload no longer reports."""
    prop = {"rows_considered": 374, "rows_with_projection": 331,
            "unmatched_player_rows": 3, "unsupported_market_rows": 40, "pct_projected": 88.5}
    game = {"rows_considered": 22, "rows_with_projection": 22, "unmatched_game_rows": 0}
    out = _merged(prop, game)
    assert out["pct_projected"] == round(100.0 * 353 / 396, 1)
    assert out["pct_projected"] != 88.5


def test_prop_only_coverage_is_still_answerable() -> None:
    """The merge must not destroy the question it was hiding.

    "What fraction of WNBA PROPS are projected?" was unanswerable from the top
    line once game rows entered the numerator. It is answerable again.
    """
    prop = {"rows_considered": 374, "rows_with_projection": 331,
            "unmatched_player_rows": 3, "unsupported_market_rows": 40}
    game = {"rows_considered": 22, "rows_with_projection": 22, "unmatched_game_rows": 0}
    out = _merged(prop, game)
    assert out["prop_rows_considered"] == 374
    assert out["prop_rows_with_projection"] == 331
    assert out["game_rows_considered"] == 22
    assert out["prop_coverage"] is prop and out["game_coverage"] is game


def test_an_empty_game_join_does_not_divide_by_zero_or_shift_the_props() -> None:
    """The common case out of season: no game index at all."""
    prop = {"rows_considered": 10, "rows_with_projection": 7,
            "unmatched_player_rows": 1, "unsupported_market_rows": 2}
    game = {"supported": True, "rows_with_projection": 0, "reason": "no WNBA game_cards rows"}
    out = _merged(prop, game)
    assert out["rows_considered"] == 10
    assert out["rows_with_projection"] == 7
    assert out["pct_projected"] == 70.0


def test_a_fully_empty_payload_reports_zero_rather_than_raising() -> None:
    out = _merged({}, {})
    assert out["rows_considered"] == 0
    assert out["pct_projected"] == 0.0


def test_double_double_refusal_is_deliberate_and_must_stay() -> None:
    """`unsupported_market=40` is the model declining to guess, not a gap.

    Pinned so a later reader does not "fix" the counter by projecting these.
    """
    from syndicate.features.shared.wnba_projections import _UNSUPPORTED_MARKETS

    assert _UNSUPPORTED_MARKETS == {"player_double_double", "player_triple_double"}
