"""The live game-line ledger records the OPEN half of CLV, and only movement.

Lane `live-game-line-projection`, for `clv-without-settlement`. Evidence:
`.syndicate/lanes.md` handoff, 2026-08-16.

The load-bearing tests are DEDUPLICATION and NON-FATALITY. The board rebuilds
every few minutes; a recorder that writes unconditionally multiplies the file by
the build rate for no information, and one that raises takes down the product to
protect instrumentation for a measurement nobody has computed yet.
"""

from __future__ import annotations

import json

import pytest

from syndicate.features.shared.live_gameline_ledger import (
    LEDGER_VERSION,
    append_records,
    build_records,
    read_last_by_key,
    record_key,
)


def _row(*, priceable=True, model=0.6, market=0.4069, edge=19.31, segment="full",
         books=("pinnacle", "fanduel"), game_pk=824966, reason=None,
         market_key="h2h", line=None):
    return {
        "kind": "game", "market": market_key, "segment": segment, "line": line,
        "event_id": "1145a9db", "home_team": "Athletics", "away_team": "Texas Rangers",
        "books": list(books), "age_seconds": 42.5, "updated_at": "2026-08-16T02:00:00Z",
        "game": {"state": "live", "home_score": 3, "away_score": 1},
        "live_gameline": {
            "game_pk": game_pk, "priceable": priceable, "model_prob": model,
            "market_prob": market, "edge_pp": edge, "prob_std_err": 0.04405,
            "sims_run": 120, "as_of": None, "carried_forward": False,
            "withheld_reason": reason, "sigma": 2.0,
        },
    }


class TestBuildRecords:
    def test_records_a_priceable_row_with_the_join_key_and_the_open_half(self):
        rec = build_records([_row()], sport="mlb", date_str="2026-08-15")[0]
        assert rec["v"] == LEDGER_VERSION
        # identity a close can be joined to
        assert (rec["game_pk"], rec["event_id"], rec["segment"]) == (824966, "1145a9db", "full")
        # the open half
        assert (rec["model_home_win_prob"], rec["market_fair_prob"], rec["edge_pp"]) == (0.6, 0.4069, 19.31)
        # what makes it interpretable later
        assert rec["sims_run"] == 120 and rec["prob_std_err"] == 0.04405
        assert rec["quote_age_seconds"] == 42.5

    def test_a_WITHHELD_row_IS_recorded_in_v2_carrying_its_reason(self):
        """v1 skipped these and therefore recorded nothing at all.

        Measured 2026-08-16 03:00Z on a live slate: considered 8, projected 2,
        **priceable 0**. v1's population was empty on a real slate, so the file
        could never answer anything. `priceable` survives as a field, which is
        what keeps v1's question askable over a v2 file.
        """
        rec = build_records([_row(priceable=False, reason="prob_interval_swamps_edge")],
                            sport="mlb", date_str="2026-08-15")[0]
        assert rec["priceable"] is False
        assert rec["withheld_reason"] == "prob_interval_swamps_edge"
        assert rec["model_home_win_prob"] == 0.6

    def test_a_row_the_join_never_projected_is_still_not_recorded(self):
        """Wrong segment / no live projection never get a `live_gameline` block.

        The gate is the block's PRESENCE, so those rows stay out without a second
        rule here re-deciding what the join already decided.
        """
        row = _row()
        row.pop("live_gameline")
        assert build_records([row], sport="mlb", date_str="d") == []

    def test_sharp_books_and_pinnacle_are_flagged_separately(self):
        """`state.md`'s 100% sharp coverage is the sharp SET; Pinnacle
        specifically was 15/30 in production, so the join must know which."""
        rec = build_records([_row(books=("novig", "fanduel"))], sport="mlb", date_str="d")[0]
        assert rec["sharp_books"] == ["novig"] and rec["has_pinnacle"] is False
        rec2 = build_records([_row(books=("pinnacle", "novig"))], sport="mlb", date_str="d")[0]
        assert rec2["has_pinnacle"] is True

    @pytest.mark.parametrize("grid", [None, [], "rows", [None], [{}], [{"live_gameline": None}]])
    def test_malformed_grid_is_empty_not_an_exception(self, grid):
        assert build_records(grid, sport="mlb", date_str="d") == []


class TestDeduplication:
    """The reason the file does not grow by the build rate."""

    def test_an_unchanged_market_is_not_rewritten(self, tmp_path):
        p = tmp_path / "led.jsonl"
        recs = build_records([_row()], sport="mlb", date_str="d")
        assert append_records(p, recs)["written"] == 1
        second = append_records(p, build_records([_row()], sport="mlb", date_str="d"))
        assert second["written"] == 0 and second["skipped_unchanged"] == 1
        assert len(p.read_text(encoding="utf-8").strip().splitlines()) == 1

    def test_a_MOVED_market_is_appended_so_the_file_is_a_movement_history(self, tmp_path):
        p = tmp_path / "led.jsonl"
        append_records(p, build_records([_row(market=0.4069)], sport="mlb", date_str="d"))
        out = append_records(p, build_records([_row(market=0.4500)], sport="mlb", date_str="d"))
        assert out["written"] == 1
        lines = p.read_text(encoding="utf-8").strip().splitlines()
        assert [json.loads(x)["market_fair_prob"] for x in lines] == [0.4069, 0.4500]

    def test_crossing_the_noise_bar_is_MOVEMENT_even_with_identical_numbers(self, tmp_path):
        """`priceable` depends on `sims_run` through the standard error, and
        `sims_run` is not one of the compared numbers. Without `priceable` in the
        comparison, the moment a row becomes publishable would be dropped as
        'unchanged' — which is the single event this file exists to timestamp."""
        p = tmp_path / "led.jsonl"
        append_records(p, build_records([_row(priceable=False, reason="prob_interval_swamps_edge")],
                                        sport="mlb", date_str="d"))
        out = append_records(p, build_records([_row(priceable=True)], sport="mlb", date_str="d"))
        assert out["written"] == 1 and out["skipped_unchanged"] == 0
        lines = p.read_text(encoding="utf-8").strip().splitlines()
        assert [json.loads(x)["priceable"] for x in lines] == [False, True]

    def test_the_same_game_on_a_different_segment_is_a_different_record(self, tmp_path):
        p = tmp_path / "led.jsonl"
        recs = build_records([_row(segment="full"), _row(segment="first5")],
                             sport="mlb", date_str="d")
        assert append_records(p, recs)["written"] == 2

    def test_two_totals_lines_on_one_game_are_different_records(self, tmp_path):
        """A LATENT COLLISION CLOSED 2026-08-30 -- not an observed one, and the
        distinction is deliberate. A totals market is one market PER LINE and the
        lines carry different probabilities (the served MLB board that day quoted
        9.5 / 9.0 / 8.5 at 0.3167 / 0.3167 / 0.45), but production was NOT
        colliding them: `books_key` is built from the books quoting that line, so
        it varied with the line and stood in for it. 0 collisions across the 6
        live records checked.

        This fixture makes the book sets IDENTICAL, which is what production does
        not guarantee. That is the whole point -- it is the case the old key
        could not survive, and it cannot arise from a fixture that lets
        `books_key` do the separating.
        """
        p = tmp_path / "led.jsonl"
        rows = [_row(market_key="totals", line=9.5, model=0.3167),
                _row(market_key="totals", line=9.0, model=0.3167),
                _row(market_key="totals", line=8.5, model=0.45)]
        recs = build_records(rows, sport="mlb", date_str="d")
        assert len({record_key(r) for r in recs}) == 3
        assert append_records(p, recs)["written"] == 3

    def test_the_line_is_recorded_so_a_totals_probability_can_be_scored_later(self):
        """`live_gameline_score` can compare a home-win probability to a final,
        but P(over) means nothing without the number it is over. The line was
        absent until v3, which is why totals rows are refused rather than scored
        -- historical records cannot be repaired, the line is not recoverable
        from the stored probability."""
        rec = build_records([_row(market_key="totals", line=9.5)],
                            sport="mlb", date_str="d")[0]
        assert rec["line"] == 9.5
        assert rec["market"] == "totals"

    def test_a_line_of_zero_is_kept_and_is_not_the_same_key_as_no_line(self):
        """0.0 is a real spread. Coercing it with `or ""` would fold a pick-em
        onto the absent-line key -- the falsy-zero trap."""
        a = build_records([_row(market_key="spreads", line=0.0)], sport="mlb", date_str="d")[0]
        b = build_records([_row(market_key="spreads", line=None)], sport="mlb", date_str="d")[0]
        assert a["line"] == 0.0
        assert record_key(a) != record_key(b)

    def test_differing_book_sets_do_not_collapse_onto_each_other(self, tmp_path):
        """Same market, different book consensus, genuinely different prices --
        keying without the book set would keep only whichever was written last."""
        p = tmp_path / "led.jsonl"
        a = _row(books=("pinnacle",), market=0.40)
        b = _row(books=("fanduel",), market=0.44)
        assert record_key(build_records([a], sport="mlb", date_str="d")[0]) != \
               record_key(build_records([b], sport="mlb", date_str="d")[0])
        assert append_records(p, build_records([a, b], sport="mlb", date_str="d"))["written"] == 2


class TestDurability:
    def test_a_truncated_final_line_does_not_discard_the_history(self, tmp_path):
        """Expected after a SIGKILL mid-append, and this worker is OOM-killed."""
        p = tmp_path / "led.jsonl"
        append_records(p, build_records([_row()], sport="mlb", date_str="d"))
        with p.open("a", encoding="utf-8") as h:
            h.write('{"game_pk": 999, "segm')
        assert len(read_last_by_key(p)) == 1

    def test_an_unwritable_path_returns_an_error_and_does_not_raise(self, tmp_path):
        """A ledger failure must never take down the board build."""
        target = tmp_path / "afile"
        target.write_text("x", encoding="utf-8")
        out = append_records(target / "nested" / "led.jsonl",
                             build_records([_row()], sport="mlb", date_str="d"))
        assert out["written"] == 0 and "error" in out

    def test_the_build_cap_is_reported_not_silent(self, tmp_path):
        """A silent cap reads as 'that is all that happened'."""
        p = tmp_path / "led.jsonl"
        rows = [_row(game_pk=i) for i in range(600)]
        out = append_records(p, build_records(rows, sport="mlb", date_str="d"))
        assert out["truncated_build_cap"] == 100 and out["written"] == 500

    def test_the_kill_switch_writes_nothing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MLB_LIVE_GAMELINE_LEDGER_ENABLED", "0")
        p = tmp_path / "led.jsonl"
        out = append_records(p, build_records([_row()], sport="mlb", date_str="d"))
        assert out["enabled"] is False and out["written"] == 0 and not p.exists()


# ---------------------------------------------------------------------------
# THE MARKET BASELINE. Measured 2026-09-06 on NCAAF's accuracy artifact, n=5
# finalised games: model brier 0.17494 / mae 0.20333, market brier NULL n=0.
# A model score with no market score beside it cannot answer the only question
# that matters -- does it beat the close -- so the live probability was
# unmeasurable rather than merely unmeasured.
# ---------------------------------------------------------------------------
from syndicate.features.shared.live_gameline_ledger import _devig_home_prob, _market_fair_prob


def test_the_devig_matches_a_hand_computed_market_price():
    """-2128 / +1106 was the real WSU @ WASH consensus on 2026-09-06.

    Hand-computed: implied 0.9551 / 0.0829, overround 1.0380, fair 0.9201.
    Pinned against the arithmetic rather than against the function's own output,
    which would only assert that it is self-consistent.
    """
    assert round(_devig_home_prob({"home": -2128, "away": 1106}), 4) == 0.9201
    assert round(_devig_home_prob({"home": -110, "away": -110}), 4) == 0.5


def test_a_priced_market_probability_always_WINS_over_the_devig():
    """MLB/WNBA/soccer records must be byte-identical after this change.

    The fallback exists for a sport whose projection carries no market price; it
    must never quietly re-baseline a sport that already had one, because that
    would move a published accuracy series without anything announcing it.
    """
    lg = {"market_prob": 0.77}
    row = {"market": "h2h", "consensus": {"home": -2128, "away": 1106}}
    assert _market_fair_prob(lg, row) == 0.77


def test_the_fallback_fires_only_for_FULL_GAME_h2h():
    """`consensus` on a totals or spreads row is over/under or cover pricing.

    Calling either P(home) would score a probability against an event it does
    not describe -- the exact defect `_SCOREABLE_MARKETS` exists to refuse. A
    segment row is refused for the same reason: a first5 price is not a
    full-game win probability.
    """
    cons = {"home": -2128, "away": 1106}
    assert _market_fair_prob({}, {"market": "h2h", "consensus": cons}) is not None
    assert _market_fair_prob({}, {"market": "totals", "consensus": cons}) is None
    assert _market_fair_prob({}, {"market": "spreads", "consensus": cons}) is None
    assert _market_fair_prob({}, {"market": "h2h", "segment": "first5", "consensus": cons}) is None


def test_an_unusable_consensus_yields_NONE_not_a_confident_number():
    """A one-sided or degenerate book is not a market price.

    Returning 0.0/1.0 here would enter the accuracy series as a market that was
    certain and, when it lost, take the market's log loss to infinity -- a
    baseline destroyed by a missing quote rather than by being wrong.
    """
    assert _market_fair_prob({}, {"market": "h2h", "consensus": {"home": -2128}}) is None
    assert _market_fair_prob({}, {"market": "h2h", "consensus": {}}) is None
    assert _market_fair_prob({}, {"market": "h2h"}) is None
    assert _devig_home_prob({"home": 0, "away": 0}) is None


def test_build_records_ACTUALLY_USES_the_devig_fallback():
    """REACHABILITY, and it is here because the first version of these tests had
    none.

    The helper tests above all passed with the fallback DISCONNECTED from
    `build_records` -- a five-line mutation left 26 tests green, so the fix could
    have shipped inert with a full suite vouching for it. Exercising the helpers
    proves they compute; only this proves the record carries the result.
    """
    from syndicate.features.shared.live_gameline_ledger import build_records

    row = {
        "sport": "ncaaf", "market": "h2h", "segment": "full",
        "home_team": "Washington", "away_team": "Washington State",
        "event_id": "evt-1",
        # The real WSU @ WASH consensus, 2026-09-06.
        "consensus": {"home": -2128, "away": 1106},
        # A projected live row whose PRICER refused: exactly NCAAF's shape --
        # `market_prob` None because `market_fair_prob_over` is absent upstream.
        "live_gameline": {
            "model_prob": 0.9917, "market_prob": None, "priceable": False,
            "withheld_reason": "no_two_sided_market_price", "sims_run": 120,
        },
        "projection": {"live_aware": True},
    }
    recs = build_records([row], sport="ncaaf", date_str="2026-09-06")
    assert len(recs) == 1, "the row must be recorded at all"
    rec = recs[0]
    assert rec["model_home_win_prob"] == 0.9917
    assert rec["market_fair_prob"] == pytest.approx(0.9201, abs=5e-5), (
        "the record must carry the de-vigged market baseline, not the pricer's None"
    )
    # And the pricing verdict is untouched -- this is a MEASUREMENT fix.
    assert rec["priceable"] is False
    assert rec["withheld_reason"] == "no_two_sided_market_price"
