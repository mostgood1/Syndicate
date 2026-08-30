"""The live game-line model is scored against realised outcomes, vs the market.

WHY THIS EXISTS. `live-game-line-projection` closed with the ledger proven able
to produce a sample and its edges **unscored** — nobody had measured whether
those probabilities were RIGHT.

WHY WORKER-SIDE. Measured 2026-08-17 01:0xZ: the ledger matches zero
`HOT_ARTIFACT_PATTERNS` (export → `count 0`, stream → refused), both endpoints
read the serving service's disk rather than the worker's, and a FINISHED game
retains no model probability on any served surface (`{final: 14, live: 1}` →
model_prob rows `{live: 12}`). There is no retrospective path, so the score is
computed where the sample lives and rides an already-published artifact.

THE ASSERTION THAT MATTERS is that model and market are scored on **identical
rows**. A Brier score alone is worthless — predicting the market's own number
scores well and adds nothing.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.live_gameline_score import (
    build_finals_index,
    score_ledger_records,
)


def _grid_row(pk, state, home, away):
    return {"game_pk": pk, "game": {"state": state, "home_score": home, "away_score": away}}


def _rec(pk, model, market=None, priceable=True, at="2026-08-16T22:00:00Z",
         market_key="h2h"):
    """One ledger record.

    NOTE THE TWO DIFFERENT SENSES OF "market" HERE, because they were a genuine
    trap: `market` is the market's PRICE (`market_fair_prob`), while
    `market_key` is WHICH MARKET the row is (`h2h`, `totals`, `spreads`). The
    ledger field carrying the price is `market_fair_prob` and the one carrying
    the kind is `market`; the parameter names are deliberately not symmetrical
    so a call site cannot mean one and pass the other.

    `market_key` defaults to `h2h` because that is the only market whose
    probability the scorer can compare against a home-win outcome, and because
    every test written before 2026-08-30 set no market at all and meant `h2h`.
    Pass it EXPLICITLY -- including `None` -- to exercise the refusing branch.
    """
    return {
        "game_pk": pk,
        "recorded_at": at,
        "market": market_key,
        "model_home_win_prob": model,
        "market_fair_prob": market,
        "priceable": priceable,
    }


def test_finals_index_takes_only_decided_final_games():
    grid = [
        _grid_row("g1", "final", 5, 3),   # home won
        _grid_row("g2", "final", 2, 7),   # home lost
        _grid_row("g3", "live", 1, 1),    # not final
        _grid_row("g4", "final", 4, 4),   # level -- a BAD ROW in baseball
        _grid_row("g5", "final", None, 2),
    ]
    assert build_finals_index(grid, sport="mlb") == {"g1": True, "g2": False}


def test_a_tie_is_never_coerced_into_a_winner():
    """Baseball does not tie, so an equal-score final is a BAD ROW. Guessing a
    winner from it would inject a fabricated outcome into the score."""
    assert build_finals_index([_grid_row("g", "final", 3, 3)], sport="mlb") == {}


def test_a_soccer_draw_is_a_real_outcome_and_is_scored_as_not_a_home_win():
    """THE REGRESSION THIS FILE EXISTS TO HOLD. Dropping draws conditioned the
    soccer population on the OUTCOME VARIABLE ITSELF -- measured 2026-08-27,
    17-38% of matches per date silently removed. A draw is not a missing
    outcome; for "did the home side win" it is a well-defined False."""
    assert build_finals_index([_grid_row("g", "final", 1, 1)], sport="soccer") == {"g": False}


def test_the_same_grid_scores_differently_for_mlb_and_soccer():
    """OFF != ON. Without this, a sport-blind implementation still passes every
    other test in this file."""
    grid = [_grid_row("g1", "final", 2, 1), _grid_row("g2", "final", 1, 1)]
    assert build_finals_index(grid, sport="mlb") == {"g1": True}
    assert build_finals_index(grid, sport="soccer") == {"g1": True, "g2": False}


def test_an_unknown_sport_does_not_get_the_permissive_branch():
    """A sport in neither table must be SKIPPED and COUNTED, never folded into
    the draw-bearing branch -- calling a level final "not a home win" for a
    sport that cannot draw would fabricate the outcome the original rule feared.
    """
    diag = {}
    assert build_finals_index([_grid_row("g", "final", 1, 1)], diagnostics=diag) == {}
    assert diag["sport_known"] is False
    assert diag["draws_scored_as_not_a_home_win"] is False
    assert diag["finals_skipped_level_sport_unknown"] == 1
    assert diag["finals_skipped_level"] == 0


def test_the_level_final_counters_make_an_exclusion_visible():
    """The exclusion went unnoticed for weeks because nothing counted it."""
    grid = [_grid_row("g1", "final", 3, 1), _grid_row("g2", "final", 2, 2)]
    diag = {}
    build_finals_index(grid, sport="mlb", diagnostics=diag)
    assert (diag["finals_seen"], diag["finals_level"], diag["finals_skipped_level"]) == (2, 1, 1)
    diag2 = {}
    build_finals_index(grid, sport="soccer", diagnostics=diag2)
    assert (diag2["finals_seen"], diag2["finals_level"], diag2["finals_skipped_level"]) == (2, 1, 0)


def test_model_and_market_are_scored_on_identical_rows():
    """The load-bearing assertion. If the market were scored on a different
    population the comparison would be meaningless, and it would still LOOK
    like a number.

    NOTE its blind spot, found 2026-08-27: EVERY record in this fixture carries
    a market price, so the populations cannot diverge here no matter what the
    implementation does. It asserted a property on data that could not violate
    it, and passed for weeks while production ran n 94 vs 90. The real
    regression test is the one below.
    """
    finals = {"g1": True, "g2": False}
    recs = [_rec("g1", 0.80, 0.60), _rec("g2", 0.30, 0.40)]
    out = score_ledger_records(recs, finals)
    assert out["all_records"]["model"]["n"] == out["all_records"]["market"]["n"] == 2
    # model: (0.8-1)^2 + (0.3-0)^2 = 0.04 + 0.09 -> 0.065
    assert out["all_records"]["model"]["brier"] == pytest.approx(0.065)
    # market: (0.6-1)^2 + (0.4-0)^2 = 0.16 + 0.16 -> 0.16
    assert out["all_records"]["market"]["brier"] == pytest.approx(0.16)
    # NEGATIVE means the model beat the market.
    assert out["all_records"]["model_minus_market_brier"] == pytest.approx(-0.095)


def test_the_difference_is_paired_when_a_row_carries_no_market_price():
    """THE REGRESSION. `market_fair_prob` can be absent where
    `model_home_win_prob` is not, so the market list is a SUBSET of the model
    list. Subtracting their Briers spans two different row sets and describes no
    population at all. Measured on pooled MLB `last_per_game` 2026-08-27:
    model n 94 vs market n 90.
    """
    finals = {"g1": True, "g2": False}
    recs = [_rec("g1", 0.80, 0.60), _rec("g2", 0.30, None)]
    block = score_ledger_records(recs, finals)["all_records"]

    # The populations really do diverge on this fixture ...
    assert block["model"]["n"] == 2
    assert block["market"]["n"] == 1
    assert block["rows_without_market_prob"] == 1

    # ... and the difference is taken ONLY on the row both sides have.
    assert block["model_paired"]["n"] == 1
    assert block["populations_matched"] is True
    # paired model: (0.8-1)^2 = 0.04   market: (0.6-1)^2 = 0.16  -> -0.12
    assert block["model_paired"]["brier"] == pytest.approx(0.04)
    assert block["model_minus_market_brier"] == pytest.approx(-0.12)
    # The pre-fix value was model_all(0.065) - market(0.16) = -0.095. If this
    # ever reads -0.095 again the pairing has been lost.
    assert block["model_minus_market_brier"] != pytest.approx(-0.095)

    # `model` is deliberately UNCHANGED -- the model's score over all its rows
    # is a real quantity, it is just not what the difference may use.
    assert block["model"]["brier"] == pytest.approx(0.065)


def test_every_population_is_paired_not_just_all_records():
    """`last_per_game` was the cut that got quoted, and `priceable_only` only
    LOOKED immune (25,504/25,504) because priceable rows happen to carry a
    price. That is a property of the data, not a guarantee."""
    finals = {"g1": True, "g2": False}
    recs = [_rec("g1", 0.80, 0.60), _rec("g2", 0.30, None)]
    out = score_ledger_records(recs, finals)
    for cut in ("all_records", "last_per_game", "priceable_only"):
        block = out[cut]
        assert block["populations_matched"] is True, cut
        assert block["model_paired"]["n"] == block["market"]["n"], cut


def test_a_record_whose_game_has_no_outcome_is_counted_not_dropped():
    """"We had no outcome" and "the model was wrong" must never look alike."""
    out = score_ledger_records([_rec("unknown", 0.7, 0.6)], {"g1": True})
    assert out["all_records"]["model"]["n"] == 0
    assert out["unscored"]["no_final_outcome_for_game"] == 1
    assert out["records_considered"] == 1


def test_a_certainty_is_refused_rather_than_scored():
    """A stored 0.0 or 1.0 is a certainty no 120-sim estimator can express, so
    it is far likelier a sentinel or unit error than a forecast. Scoring it
    would hand the model a perfect or maximally-wrong Brier for free."""
    out = score_ledger_records(
        [_rec("g1", 0.0, 0.5), _rec("g1", 1.0, 0.5), _rec("g1", 1.5, 0.5)], {"g1": True}
    )
    assert out["all_records"]["model"]["n"] == 0
    assert out["unscored"]["record_carries_no_model_probability"] == 3


def test_last_per_game_uses_recorded_at_not_file_order():
    """The ledger is append-only so the two normally agree -- but a merged or
    re-pulled file would silently make file order meaningless."""
    finals = {"g1": True}
    recs = [
        _rec("g1", 0.90, 0.5, at="2026-08-16T23:00:00Z"),   # latest, listed FIRST
        _rec("g1", 0.10, 0.5, at="2026-08-16T21:00:00Z"),
    ]
    out = score_ledger_records(recs, finals)
    assert out["last_per_game"]["model"]["n"] == 1
    # 0.90 is the last word -> (0.9-1)^2 = 0.01
    assert out["last_per_game"]["model"]["brier"] == pytest.approx(0.01)
    assert out["all_records"]["model"]["n"] == 2


def test_priceable_only_measures_the_gate_and_all_records_measures_the_model():
    """`priceable` is a FIELD not a filter, exactly so both are available."""
    finals = {"g1": True, "g2": True}
    recs = [_rec("g1", 0.9, 0.5, priceable=True), _rec("g2", 0.1, 0.5, priceable=False)]
    out = score_ledger_records(recs, finals)
    assert out["priceable_only"]["model"]["n"] == 1
    assert out["all_records"]["model"]["n"] == 2
    assert out["priceable_only"]["model"]["brier"] < out["all_records"]["model"]["brier"]


def test_an_empty_sample_reports_None_not_zero():
    """A 0.0 Brier reads as a perfect model. Empty must be None."""
    out = score_ledger_records([], {"g1": True})
    assert out["all_records"]["model"]["brier"] is None
    assert out["all_records"]["model"]["n"] == 0
    assert out["all_records"]["model_minus_market_brier"] is None


def test_a_row_with_no_market_price_still_scores_the_model():
    """The model population must not shrink just because a market number is
    missing -- but the COMPARISON must then decline rather than compare across
    different rows."""
    out = score_ledger_records([_rec("g1", 0.8, None)], {"g1": True})
    assert out["all_records"]["model"]["n"] == 1
    assert out["all_records"]["market"]["n"] == 0
    assert out["all_records"]["model_minus_market_brier"] is None


def test_a_final_with_no_numeric_score_is_counted_not_dropped_in_silence():
    """The LARGEST cause of a capped `games_with_outcome`, and until this
    counter existed it was the only path in the scorer that incremented
    nothing.

    Measured on production 2026-08-29 (`date=2026-08-28`): 15 games on the
    grid, 12 `final`, and exactly ONE carrying numeric scores -- the other 11
    nulled upstream by `game_chip_scoreboard`'s `level_final_impossible_for_sport`.
    Every counter that existed read healthy at that instant (`finals_seen: 196`,
    `finals_level: 0`, `finals_skipped_level: 0`), so the diagnostics pointed at
    the ledger and the join, which were both fine.
    """
    grid = [
        _grid_row("g1", "final", 5, 3),        # scoreable
        _grid_row("g2", "final", None, None),  # score nulled upstream
        _grid_row("g3", "final", None, None),  # ditto, a DIFFERENT game
        _grid_row("g4", "final", "", 2),       # half-present is still unusable
    ]
    diag = {}
    assert build_finals_index(grid, sport="mlb", diagnostics=diag) == {"g1": True}
    # off != on: the counter is producible ONLY by the new branch. Asserting
    # the old behaviour (absent key / silent zero) must fail here.
    assert diag["finals_skipped_no_numeric_score"] == 3
    assert diag["finals_skipped_no_numeric_score_games"] == 3
    # The counters now ACCOUNT for every final row on the grid, which is the
    # property that makes a cap attributable from the payload alone.
    assert diag["finals_seen"] + diag["finals_skipped_no_numeric_score"] == 4


def test_the_skipped_counters_separate_rows_from_games():
    """`finals_seen` counts ROWS -- 196 rows was ONE game on 2026-08-28. A row
    count cannot answer "how many games did we lose?", so the games are counted
    separately rather than inferred from a ratio that does not hold."""
    grid = [_grid_row("g1", "final", None, None) for _ in range(40)]
    grid += [_grid_row("g2", "final", None, None) for _ in range(160)]
    diag = {}
    assert build_finals_index(grid, sport="mlb", diagnostics=diag) == {}
    assert diag["finals_skipped_no_numeric_score"] == 200      # rows
    assert diag["finals_skipped_no_numeric_score_games"] == 2  # games


def test_a_game_indexed_from_another_row_is_not_reported_as_lost():
    """Reported NET of the index. A game skipped on one row and indexed from
    another was never lost, and counting it would overstate the damage."""
    grid = [_grid_row("g1", "final", None, None), _grid_row("g1", "final", 6, 2)]
    diag = {}
    assert build_finals_index(grid, sport="mlb", diagnostics=diag) == {"g1": True}
    assert diag["finals_skipped_no_numeric_score"] == 1       # the row happened
    assert diag["finals_skipped_no_numeric_score_games"] == 0  # the game did not


def test_the_new_counter_recovers_no_games_and_moves_no_number():
    """A pure diagnostic. The scores are absent upstream and refusing them is
    correct -- this must not change a single scored value."""
    grid = [
        _grid_row("g1", "final", 5, 3),
        _grid_row("g2", "final", None, None),
        _grid_row("g3", "final", 2, 2),
    ]
    finals = build_finals_index(grid, sport="mlb")
    assert finals == {"g1": True}
    scored = score_ledger_records(
        [_rec("g1", 0.6, 0.55), _rec("g2", 0.7, 0.5), _rec("g3", 0.4, 0.45)], finals
    )
    assert scored["games_with_outcome"] == 1
    assert scored["all_records"]["model"]["n"] == 1
    assert scored["unscored"]["no_final_outcome_for_game"] == 2


# --------------------------------------------------------------------------
# THE MARKET FILTER. Defect found 2026-08-30: `score_ledger_records` had no
# market branch and scored every record against `won = did the home team win`,
# while the ledger carries three markets by design. On the served MLB board that
# day, 1 of the 6 rows with a `live_gameline` block was h2h -- so ~5/6 of the
# scored sample was P(over) or P(home covers) compared against a home win.
#
# THESE FIXTURES CONTAIN THE ROWS THAT MAKE THE PROPERTY VIOLABLE. The lesson is
# recorded in `learnings.md` 2026-08-27 against THIS FILE: the previous
# "load-bearing assertion" passed for weeks while production ran n 94 vs 90,
# because no fixture row could break it. Every test below fails on pre-fix code.
# --------------------------------------------------------------------------


def test_a_totals_record_is_not_scored_against_a_home_win():
    """THE REGRESSION. A totals row's probability is P(over), not P(home wins).

    Pre-fix this returned n=2 and a Brier blended from two different questions.
    """
    finals = {"g1": True}
    recs = [
        _rec("g1", 0.80, 0.60, market_key="h2h"),
        _rec("g1", 0.3167, 0.4425, market_key="totals"),
    ]
    out = score_ledger_records(recs, finals)

    # Only the h2h row is scored, in every cut.
    for cut in ("all_records", "last_per_game", "priceable_only"):
        assert out[cut]["model"]["n"] == 1, cut
        assert out[cut]["market"]["n"] == 1, cut
        # ... and it is the h2h row, not whichever survived: (0.8-1)^2 = 0.04
        assert out[cut]["model"]["brier"] == pytest.approx(0.04), cut

    # The refusal is COUNTED and named, never silent.
    assert out["unscored"]["market_probability_is_not_a_home_win_probability"] == 1
    assert out["records_considered"] == 2


def test_spreads_run_line_and_alt_lines_are_all_refused():
    """The refusing set is imported from the producer, not re-typed.

    A hand-written copy was wrong on the first attempt -- it had `spread` and
    lacked `run_line` and `ats`, so an MLB run-line row would have fallen
    through to `unknown` and been reported as an unclassified-market bug rather
    than the known, priced, unscoreable row it is.
    """
    finals = {"g1": True}
    kinds = ["totals", "totals_alt", "alternate_totals", "total",
             "spreads", "spreads_alt", "alternate_spreads", "run_line", "ats"]
    out = score_ledger_records(
        [_rec("g1", 0.4, 0.5, market_key=k) for k in kinds], finals
    )
    assert out["all_records"]["model"]["n"] == 0
    assert out["unscored"]["market_probability_is_not_a_home_win_probability"] == len(kinds)
    # None of them landed in the "nobody classified this" bucket.
    assert "record_carries_no_recognised_market" not in out["unscored"]


@pytest.mark.parametrize("absent", [None, "", "   "])
def test_an_absent_market_is_refused_not_treated_as_h2h(absent):
    """UNKNOWN MUST NOT DEFAULT PERMISSIVE.

    Every record `build_records` writes carries `market`, so a null here is a
    real anomaly. Mapping it onto the scoring branch would turn a failed
    classification into a silently relaxed rule -- and it would be scored
    against a home win, which is the exact defect this filter exists to stop.
    """
    out = score_ledger_records([_rec("g1", 0.8, 0.6, market_key=absent)], {"g1": True})
    assert out["all_records"]["model"]["n"] == 0
    assert out["unscored"]["record_carries_no_recognised_market"] == 1
    assert out["records_by_market"]["<absent>"] == 1


def test_an_unrecognised_market_is_reported_separately_from_a_known_one():
    """Two different facts. "A totals row we cannot score yet" is expected; "a
    market nobody classified" is a bug report, and collapsing them into one
    counter would hide the second behind the volume of the first."""
    finals = {"g1": True}
    out = score_ledger_records(
        [_rec("g1", 0.4, 0.5, market_key="totals"),
         _rec("g1", 0.4, 0.5, market_key="btts")], finals)
    assert out["unscored"]["market_probability_is_not_a_home_win_probability"] == 1
    assert out["unscored"]["record_carries_no_recognised_market"] == 1


def test_games_with_outcome_counts_only_games_with_a_scoreable_market():
    """`games_with_outcome` fed the pooled history and was the headline
    denominator. A game whose only records are totals rows contributed to it
    while contributing nothing scoreable -- so the reported game count was
    larger than the population the Brier actually rested on."""
    finals = {"g1": True, "g2": True}
    recs = [
        _rec("g1", 0.80, 0.60, market_key="h2h"),
        _rec("g2", 0.30, 0.50, market_key="totals"),   # g2 has NO h2h row
    ]
    out = score_ledger_records(recs, finals)
    assert out["games_with_outcome"] == 1


def test_the_market_mix_is_reported_so_the_sample_is_never_opaque():
    """The defect was invisible for weeks because nothing said what the sample
    was MADE OF. `records_by_market` is that reading."""
    finals = {"g1": True}
    recs = ([_rec("g1", 0.8, 0.6, market_key="h2h")] * 2
            + [_rec("g1", 0.3, 0.5, market_key="totals")] * 3
            + [_rec("g1", 0.3, 0.5, market_key="spreads")] * 2)
    out = score_ledger_records(recs, finals)
    assert out["records_by_market"] == {"h2h": 2, "totals": 3, "spreads": 2}
    assert out["scored_markets"] == ["h2h"]
