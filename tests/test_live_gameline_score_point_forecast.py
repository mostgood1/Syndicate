"""Scorer contract 3: totals and spreads are scored on the POINT FORECAST.

WHY THIS FILE EXISTS. From 2026-08-30 the live game-line scorer refused totals
and spreads by name, because comparing an informative model probability to a
-110/-110 de-vig (~0.50 whatever the line is) had produced a fake ~90% ATS
result. The correct formulation was established in `816c93c0` and implemented
first in `scripts/bucket_realised_performance.py`: THE LINE IS THE MARKET'S
VIEW, so score the model's own mean against the line on the actual total or
margin, with a 0.50 directional baseline. This file holds that rule in the
worker-side scorer, and holds three invariants beside it:

  * a row without the mean is UNMEASURED by name, never a probability
    comparison as a substitute;
  * a row whose segment is not the full game is resolved ONLY through a
    segment-actual reader, never against the full-game final;
  * the h2h arithmetic is byte-for-byte contract 2, so the retained h2h
    history stays poolable across the version bump.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared import live_gameline_score as mod
from syndicate.features.shared.live_gameline_score import (
    SCORER_CONTRACT,
    build_final_scores_index,
    build_finals_index,
    finals_from_scores,
    score_ledger_records,
    scorer_capabilities,
)

# One decided MLB final: away 4, home 6 -> total 10, home margin +2.
FINALS = {"g1": True}
SCORES = {"g1": (4.0, 6.0)}


def _pf(pk, market, line, *, total=None, margin=None, segment="full", priceable=True,
        age=30.0, at="2026-09-08T02:00:00Z", market_prob=0.5, event_id=None):
    """A line-priced ledger row (v5 shape). `market_fair_prob` is set to the
    ~0.50 the book quotes precisely so a test can prove it is never read."""
    return {
        "game_pk": pk,
        "event_id": event_id,
        "recorded_at": at,
        "segment": segment,
        "market": market,
        "line": line,
        "model_home_win_prob": 0.62,        # P(over)/P(cover) -- must NOT be scored
        "market_fair_prob": market_prob,
        "model_total_mean": total,
        "model_margin_mean": margin,
        "priceable": priceable,
        "quote_age_seconds": age,
    }


def _h2h(pk, model, market=None, *, priceable=True, age=30.0,
         at="2026-09-08T02:00:00Z", segment="full"):
    return {
        "game_pk": pk, "recorded_at": at, "market": "h2h", "segment": segment,
        "model_home_win_prob": model, "market_fair_prob": market,
        "priceable": priceable, "quote_age_seconds": age,
    }


def _score(recs, **kw):
    return score_ledger_records(recs, FINALS, final_scores=SCORES, **kw)


# --------------------------------------------------------------------------
# THE VERSION. A rule change without a bump would be pooled into the old era.
# --------------------------------------------------------------------------


def test_the_scorer_version_is_bumped_and_visible_without_a_sample():
    assert SCORER_CONTRACT == 3
    caps = scorer_capabilities()
    assert caps["scorer_contract"] == 3
    # h2h is still the ONLY probability-scored market ...
    assert caps["scored_markets"] == ["h2h"]
    # ... and the line-priced families are declared beside it, with their rule.
    assert caps["point_forecast_markets"] == ["spreads", "totals"]
    assert caps["point_forecast_baseline"] == 0.5
    assert caps["quote_age_cumulative_buckets"] == ["le_120s", "le_600s", "all"]


def test_the_board_block_stamps_the_new_version_on_the_no_finals_branch():
    from syndicate.features.shared.book_grid_artifact import score_block_for_grid

    block = score_block_for_grid([], sport="mlb", date_str="2026-09-08")
    assert block["scorer_contract"] == 3
    assert block["point_forecast_markets"] == ["spreads", "totals"]


# --------------------------------------------------------------------------
# TOTALS: the model's mean vs the line on the actual total.
# --------------------------------------------------------------------------


def test_totals_over_is_a_hit_when_the_model_leaned_over_and_the_total_went_over():
    out = _score([_pf("g1", "totals", 8.5, total=9.4)])       # actual 10 > 8.5
    block = out["point_forecast"]["totals"]["all_records"]
    assert (block["n"], block["hits"], block["hit_rate"]) == (1, 1, 1.0)
    assert block["baseline"] == 0.5
    assert block["model_minus_baseline_pp"] == pytest.approx(50.0)
    # point error: |9.4-10| = 0.6 vs |8.5-10| = 1.5 -> the model was closer
    assert block["model_mae"] == pytest.approx(0.6)
    assert block["line_mae"] == pytest.approx(1.5)
    assert block["model_minus_line_mae"] == pytest.approx(-0.9)
    assert out["unmeasured"] == {}


def test_totals_under_lean_on_an_over_result_is_a_miss():
    out = _score([_pf("g1", "totals", 10.5, total=9.0)])      # actual 10 < 10.5, model said under
    block = out["point_forecast"]["totals"]["all_records"]
    assert (block["n"], block["hits"], block["hit_rate"]) == (1, 1, 1.0)   # under was RIGHT
    out = _score([_pf("g1", "totals", 10.5, total=11.0)])     # model said over, total went under
    block = out["point_forecast"]["totals"]["all_records"]
    assert (block["n"], block["hits"], block["hit_rate"]) == (1, 0, 0.0)
    assert block["model_minus_baseline_pp"] == pytest.approx(-50.0)


def test_a_totals_push_is_not_an_observation():
    out = _score([_pf("g1", "totals", 10.0, total=9.4)])      # actual 10 == line
    assert out["point_forecast"]["totals"]["all_records"]["n"] == 0
    assert out["unmeasured"] == {"push_actual_landed_on_the_line": 1}


# --------------------------------------------------------------------------
# SPREADS: home-positive margin vs the away-frame line; home covers when
# margin > line (`live_gameline_join.price_distribution_market`).
# --------------------------------------------------------------------------


def test_spreads_cover_when_the_model_backed_home_and_home_beat_the_line():
    out = _score([_pf("g1", "spreads", 1.5, margin=2.5)])     # actual margin 2 > 1.5
    block = out["point_forecast"]["spreads"]["all_records"]
    assert (block["n"], block["hits"]) == (1, 1)
    assert block["model_mae"] == pytest.approx(0.5)            # |2.5-2|
    assert block["line_mae"] == pytest.approx(0.5)             # |1.5-2|


def test_spreads_no_cover_when_the_model_backed_home_and_home_fell_short():
    out = _score([_pf("g1", "spreads", 2.5, margin=3.5)])     # actual margin 2 < 2.5
    block = out["point_forecast"]["spreads"]["all_records"]
    assert (block["n"], block["hits"]) == (1, 0)
    # ... and the away lean on the same line is the mirror image.
    out = _score([_pf("g1", "spreads", 2.5, margin=1.0)])
    assert out["point_forecast"]["spreads"]["all_records"]["hits"] == 1


def test_a_spreads_push_is_not_an_observation():
    out = _score([_pf("g1", "spreads", 2.0, margin=3.0)])     # actual margin 2 == line
    assert out["point_forecast"]["spreads"]["all_records"]["n"] == 0
    assert out["unmeasured"] == {"push_actual_landed_on_the_line": 1}


def test_run_line_and_alt_aliases_score_as_spreads_and_totals():
    """The alias sets come from the producer; an MLB run-line row must land in
    the spreads family, not in `unknown`."""
    out = _score([
        _pf("g1", "run_line", 1.5, margin=2.5),
        _pf("g1", "alternate_totals", 8.5, total=9.0),
    ])
    assert out["point_forecast"]["spreads"]["all_records"]["n"] == 1
    assert out["point_forecast"]["totals"]["all_records"]["n"] == 1
    assert out["records_by_market"] == {"run_line": 1, "alternate_totals": 1}
    assert "record_carries_no_recognised_market" not in out["unscored"]


# --------------------------------------------------------------------------
# UNMEASURED, BY NAME. A row that produced no observation says why.
# --------------------------------------------------------------------------


def test_a_row_without_the_mean_is_unmeasured_never_a_probability_comparison():
    """THE INVARIANT FROM 816c93c0. No mean -> no measurement. The row carries
    a perfectly usable `model_home_win_prob` (P(over)) and a `market_fair_prob`,
    and neither may be used as a substitute."""
    out = _score([_pf("g1", "totals", 8.5, total=None),
                  _pf("g1", "spreads", 1.5, margin=None)])
    assert out["unmeasured"] == {"record_carries_no_model_point_forecast": 2}
    assert out["point_forecast"]["totals"]["all_records"]["n"] == 0
    assert out["point_forecast"]["spreads"]["all_records"]["n"] == 0
    # ... and NOTHING reached the h2h Brier either.
    assert out["all_records"]["model"]["n"] == 0


def test_market_fair_prob_is_never_read_on_a_line_priced_row():
    """OFF != ON, in the direction that matters: a wild market probability on
    a totals row must move nothing. If it ever does, a de-vigged ~0.50 has
    crept back into the comparison."""
    quiet = _score([_pf("g1", "totals", 8.5, total=9.4, market_prob=0.5)])
    wild = _score([_pf("g1", "totals", 8.5, total=9.4, market_prob=0.01)])
    assert quiet["point_forecast"] == wild["point_forecast"]
    assert quiet["all_records"] == wild["all_records"]


def test_a_row_without_a_line_is_unmeasured():
    out = _score([_pf("g1", "totals", None, total=9.4)])
    assert out["unmeasured"] == {"record_carries_no_line": 1}


def test_a_model_sitting_exactly_on_the_line_has_no_lean():
    out = _score([_pf("g1", "totals", 9.5, total=9.5)])
    assert out["unmeasured"] == {"model_mean_equals_the_line": 1}


def test_no_final_is_named_for_a_line_priced_row_too():
    out = _score([_pf("nope", "totals", 8.5, total=9.4)])
    assert out["unmeasured"] == {"no_final_outcome_for_game": 1}
    # the h2h refusal table is untouched by it
    assert out["unscored"] == {}


def test_a_caller_passing_only_home_won_finals_gets_no_final_score_not_a_guess():
    """The legacy signature (`finals` only) still works for h2h and says, by
    name, that totals/spreads had no score to resolve against."""
    out = score_ledger_records(
        [_pf("g1", "totals", 8.5, total=9.4), _h2h("g1", 0.7, 0.6)], FINALS
    )
    assert out["unmeasured"] == {"no_final_score_for_game": 1}
    assert out["all_records"]["model"]["n"] == 1


def test_a_numeric_string_line_is_a_line():
    """`line` reaches the ledger from the grid row verbatim, and the harness
    this mirrors accepts "9.5". Refusing it would read as an unfed field."""
    out = _score([_pf("g1", "totals", "8.5", total=9.4)])
    assert out["point_forecast"]["totals"]["all_records"]["n"] == 1


# --------------------------------------------------------------------------
# SEGMENTS. A first-five forecast is never graded on nine innings.
# --------------------------------------------------------------------------


def test_a_segment_row_without_a_reader_is_unmeasured_not_graded_on_the_full_final():
    out = _score([
        _pf("g1", "totals", 4.5, total=5.2, segment="first5"),
        _pf("g1", "spreads", 0.5, margin=1.1, segment="first5"),
        _h2h("g1", 0.7, 0.6, segment="first5"),
    ])
    assert out["unmeasured"] == {"segment_actual_unavailable": 3}
    assert out["point_forecast"]["totals"]["all_records"]["n"] == 0
    assert out["all_records"]["model"]["n"] == 0
    assert out["segment_actuals_supplied"] is False


def test_a_segment_row_is_scored_against_the_segment_actual_when_a_reader_exists():
    """The interface: `(game_key, segment) -> (away, home)` at the end of that
    segment, or None. The full-game final (4-6, total 10) would call this
    totals row a hit; the first-five actual (1-2, total 3) makes it a miss."""
    def reader(key, segment):
        return (1.0, 2.0) if (key, segment) == ("g1", "first5") else None

    out = _score([_pf("g1", "totals", 4.5, total=5.2, segment="first5"),
                  _pf("g1", "spreads", 0.5, margin=1.1, segment="first5"),
                  _h2h("g1", 0.7, 0.6, segment="first5")],
                 segment_actuals=reader)
    assert out["unmeasured"] == {}
    assert out["segment_actuals_supplied"] is True
    totals = out["point_forecast"]["totals"]["all_records"]
    assert (totals["n"], totals["hits"]) == (1, 0)                 # 3 < 4.5, model said over
    spreads = out["point_forecast"]["spreads"]["all_records"]
    assert (spreads["n"], spreads["hits"]) == (1, 1)               # margin 1 > 0.5
    assert out["point_forecast"]["totals"]["records_by_segment"] == {"first5": 1}
    # the h2h segment row scores on the segment (home led 2-1 after five)
    assert out["all_records"]["model"]["n"] == 1
    assert out["all_records"]["model"]["brier"] == pytest.approx((0.7 - 1) ** 2)


def test_a_mapping_is_accepted_as_the_reader_and_a_level_segment_is_a_push_for_h2h():
    table = {("g1", "first5"): (2.0, 2.0)}
    out = _score([_pf("g1", "totals", 3.5, total=5.0, segment="first5"),
                  _h2h("g1", 0.7, 0.6, segment="first5")],
                 segment_actuals=table)
    assert out["point_forecast"]["totals"]["all_records"]["hits"] == 1   # 4 > 3.5
    assert out["unmeasured"] == {"segment_actual_level_for_h2h": 1}


def test_the_reader_is_tried_on_every_identifier_never_a_or_b():
    """The same join lesson the finals index paid for twice."""
    table = {("ev-9", "first5"): (0.0, 1.0)}
    out = _score([_pf("g1", "totals", 0.5, total=1.2, segment="first5", event_id="ev-9")],
                 segment_actuals=table)
    assert out["point_forecast"]["totals"]["all_records"]["n"] == 1


def test_a_segment_row_never_needs_the_full_game_final():
    """A first-five actual exists once the fifth inning ends; the game need
    not be over. Nothing about the segment path may consult `finals`."""
    out = score_ledger_records(
        [_pf("live-game", "totals", 4.5, total=5.2, segment="first5")],
        {}, final_scores={}, segment_actuals={("live-game", "first5"): (3.0, 2.0)},
    )
    assert out["point_forecast"]["totals"]["all_records"]["hits"] == 1   # 5 > 4.5


# --------------------------------------------------------------------------
# QUOTE AGE. Conditioning is mandatory; a pooled number hides the age mix.
# --------------------------------------------------------------------------


def test_point_forecast_blocks_carry_the_quote_age_buckets_disjoint_and_cumulative():
    out = _score([
        _pf("g1", "totals", 8.5, total=9.4, age=30.0),      # hit, fresh
        _pf("g1", "totals", 8.5, total=7.0, age=400.0),     # miss, <=600
        _pf("g1", "totals", 8.5, total=9.4, age=5000.0),    # hit, stale
        _pf("g1", "totals", 8.5, total=9.4, age=None),      # hit, age absent
    ])
    fam = out["point_forecast"]["totals"]
    assert fam["quote_age_absent"] == 1
    assert fam["fresh_quotes_only"]["n"] == 1
    assert fam["by_quote_age"]["le_120s"]["n"] == 1
    assert fam["by_quote_age"]["300_600s"]["n"] == 1
    assert fam["by_quote_age"]["gt_1800s"]["n"] == 1
    assert fam["by_quote_age"]["120_300s"]["n"] == 0
    cum = fam["by_quote_age_cumulative"]
    assert [cum[k]["n"] for k in ("le_120s", "le_600s", "all")] == [1, 2, 4]
    assert cum["le_120s"]["hit_rate"] == 1.0
    assert cum["le_600s"]["hit_rate"] == 0.5
    assert cum["all"]["hit_rate"] == 0.75
    assert fam["all_records"] == cum["all"]


def test_h2h_also_reports_the_cumulative_quote_age_view():
    out = _score([_h2h("g1", 0.9, 0.6, age=30.0), _h2h("g1", 0.2, 0.6, age=400.0),
                  _h2h("g1", 0.2, 0.6, age=None)])
    cum = out["by_quote_age_cumulative"]
    assert [cum[k]["model"]["n"] for k in ("le_120s", "le_600s", "all")] == [1, 2, 3]
    assert cum["le_120s"]["model"]["brier"] == pytest.approx(0.01)
    assert cum["all"]["populations_matched"] is True


# --------------------------------------------------------------------------
# POPULATIONS AND THE INDEPENDENT UNIT.
# --------------------------------------------------------------------------


def test_last_per_game_takes_the_latest_stamp_and_the_se_is_on_games_not_rows():
    recs = [_pf("g1", "totals", 8.5, total=9.4, at="2026-09-08T01:00:00Z"),
            _pf("g1", "totals", 8.5, total=7.9, at="2026-09-08T03:00:00Z"),   # latest: under
            _pf("g1", "totals", 8.5, total=9.4, at="2026-09-08T02:00:00Z")]
    fam = _score(recs)["point_forecast"]["totals"]
    assert fam["all_records"]["n"] == 3 and fam["all_records"]["games"] == 1
    assert fam["last_per_game"]["n"] == 1
    assert fam["last_per_game"]["hits"] == 0          # the last word was under; total went over
    assert fam["games_with_outcome"] == 1
    # Three rows of one game are ONE observation's worth of sigma.
    import math
    rate = 2 / 3
    assert fam["all_records"]["se_pp_on_games"] == pytest.approx(
        round(math.sqrt(rate * (1 - rate) / 1) * 100, 3))


def test_priceable_only_is_a_field_not_a_filter_for_line_priced_rows_too():
    fam = _score([_pf("g1", "totals", 8.5, total=9.4, priceable=True),
                  _pf("g1", "totals", 8.5, total=7.0, priceable=False)])["point_forecast"]["totals"]
    assert fam["all_records"]["n"] == 2
    assert fam["priceable_only"]["n"] == 1
    assert fam["priceable_only"]["hits"] == 1


def test_an_empty_family_reports_none_not_zero():
    out = _score([])
    block = out["point_forecast"]["spreads"]["all_records"]
    assert block["n"] == 0 and block["hit_rate"] is None
    assert block["model_minus_baseline_pp"] is None and block["model_mae"] is None


# --------------------------------------------------------------------------
# h2h IS UNCHANGED. The retained history pools across this bump on h2h only
# because these numbers did not move.
# --------------------------------------------------------------------------


def test_h2h_arithmetic_is_byte_identical_with_and_without_the_new_inputs():
    recs = [_h2h("g1", 0.80, 0.60), _h2h("g1", 0.30, None, priceable=False),
            _h2h("g2", 0.55, 0.50)]
    finals = {"g1": True, "g2": False}
    legacy = score_ledger_records(recs, finals)
    new = score_ledger_records(recs, finals, final_scores={"g1": (3, 5), "g2": (4, 1)},
                               segment_actuals={})
    for cut in ("all_records", "last_per_game", "priceable_only", "fresh_quotes_only",
                "by_quote_age"):
        assert legacy[cut] == new[cut], cut
    assert legacy["games_with_outcome"] == new["games_with_outcome"] == 2
    assert legacy["all_records"]["model"]["brier"] == pytest.approx(
        ((0.8 - 1) ** 2 + (0.3 - 1) ** 2 + (0.55 - 0) ** 2) / 3)
    assert legacy["all_records"]["model_minus_market_brier"] == pytest.approx(
        round(((0.8 - 1) ** 2 + (0.55) ** 2) / 2 - ((0.6 - 1) ** 2 + 0.5 ** 2) / 2, 5))


def test_games_with_outcome_still_counts_h2h_games_only():
    """It is the denominator the retained history pools on. A game with only
    totals rows reports under `point_forecast.totals.games_with_outcome`."""
    out = _score([_pf("g1", "totals", 8.5, total=9.4)])
    assert out["games_with_outcome"] == 0
    assert out["point_forecast"]["totals"]["games_with_outcome"] == 1


# --------------------------------------------------------------------------
# THE SCORES INDEX, and the board block end to end.
# --------------------------------------------------------------------------


def _grid_row(pk, state, home, away, **extra):
    return {"game_pk": pk, "game": {"state": state, "home_score": home, "away_score": away}, **extra}


def test_the_scores_index_and_the_home_won_index_agree_on_which_finals_exist():
    grid = [_grid_row("g1", "final", 6, 4), _grid_row("g2", "final", 2, 2),
            _grid_row("g3", "live", 1, 0), _grid_row("g4", "final", None, 3)]
    scores = build_final_scores_index(grid, sport="mlb")
    assert scores == {"g1": (4.0, 6.0)}                 # (away, home); the MLB tie is a bad row
    assert finals_from_scores(scores) == build_finals_index(grid, sport="mlb") == {"g1": True}
    soccer = build_final_scores_index(grid, sport="soccer")
    assert soccer == {"g1": (4.0, 6.0), "g2": (2.0, 2.0)}   # a draw is a real total and margin
    assert finals_from_scores(soccer) == {"g1": True, "g2": False}


def test_the_board_block_scores_totals_and_spreads_from_the_grid_finals(monkeypatch):
    """End to end through `score_block_for_grid`: the grid's final supplies the
    scores, the ledger supplies the rows, and the payload carries the version,
    the families, the unmeasured reasons and the quote-age buckets."""
    import syndicate.features.shared.live_gameline_ledger as ledger
    from syndicate.features.shared.book_grid_artifact import score_block_for_grid

    rows = [
        _pf("g1", "totals", 8.5, total=9.4),
        _pf("g1", "spreads", 1.5, margin=2.5),
        _pf("g1", "totals", 8.5, total=None),
        _pf("g1", "totals", 4.5, total=5.0, segment="first5"),
        _h2h("g1", 0.7, 0.6),
    ]
    monkeypatch.setattr(ledger, "read_records", lambda _path: rows)
    block = score_block_for_grid([_grid_row("g1", "final", 6, 4)], sport="mlb",
                                 date_str="2026-09-08")
    assert block["scorer_contract"] == 3
    assert block["games_with_outcome"] == 1
    assert block["point_forecast"]["totals"]["all_records"]["hits"] == 1
    assert block["point_forecast"]["spreads"]["all_records"]["hits"] == 1
    assert block["unmeasured"] == {"record_carries_no_model_point_forecast": 1,
                                   "segment_actual_unavailable": 1}
    assert block["segment_actuals_supplied"] is False
    assert "le_120s" in block["point_forecast"]["totals"]["by_quote_age_cumulative"]
    assert block["all_records"]["model"]["n"] == 1


def test_the_retained_history_row_carries_the_version_and_the_new_blocks():
    """The accuracy allowlist drops anything unnamed. Without `scorer_contract`
    a reader cannot split the file by era; without `point_forecast` the
    totals/spreads outcomes are overwritten by the next build."""
    from syndicate.features.shared import live_gameline_accuracy as acc

    score = {"games_with_outcome": 1, "records_considered": 5, "scorer_contract": 3,
             "point_forecast_markets": ["spreads", "totals"],
             "unmeasured": {"push_actual_landed_on_the_line": 1},
             "point_forecast": {"totals": {"all_records": {"n": 3}}},
             "by_quote_age_cumulative": {"le_120s": {}},
             "priceable_only": {"model": {"brier": 0.2, "n": 2}}}
    row = acc.build_row(score, sport="mlb", date_str="2026-09-08")
    assert row["scorer_contract"] == 3
    assert row["unmeasured"] == {"push_actual_landed_on_the_line": 1}
    assert row["point_forecast"]["totals"]["all_records"]["n"] == 3
    assert row["point_forecast_markets"] == ["spreads", "totals"]
    assert "le_120s" in row["by_quote_age_cumulative"]


def test_the_rule_mirrors_the_research_harness_exactly():
    """`bucket_realised_performance.point_forecast_side` is the formulation of
    record. Both must agree on every case, including push and no-lean."""
    import importlib.util
    import pathlib

    path = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "bucket_realised_performance.py"
    spec = importlib.util.spec_from_file_location("brp", path)
    brp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(brp)

    cases = [("totals", 8.5, 9.4), ("totals", 10.5, 11.0), ("totals", 10.0, 9.4),
             ("totals", 9.5, 9.5), ("spreads", 1.5, 2.5), ("spreads", 2.5, 3.5),
             ("spreads", 2.0, 3.0), ("spreads", 2.5, 1.0)]
    for market, line, mean in cases:
        rec = _pf("g1", market, line, total=mean if market == "totals" else None,
                  margin=mean if market == "spreads" else None)
        harness_won, harness_ok = brp.point_forecast_side(rec, (4, 6))
        block = _score([rec])["point_forecast"][market]["all_records"]
        assert block["n"] == (1 if harness_ok else 0), (market, line, mean)
        if harness_ok:
            assert bool(block["hits"]) is bool(harness_won), (market, line, mean)
