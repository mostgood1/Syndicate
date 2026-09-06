"""The live game-line staleness gate: a dead quote may not be priced.

WHAT THIS PROTECTS. `attach_live_gamelines` asks whether an edge is bigger than
the model's own noise. Until 2026-09-01 nothing asked whether the PRICE that
edge is measured against still existed. Measured over 12 dates of the retained
MLB ledger (72,587 records, 157 games, h2h against StatsAPI finals):

    quote age    n     model    market   model-minus-market
    <= 120s      954   0.20000  0.17403  +0.02597
    > 1800s      592   0.16459  0.21897  -0.05438

The model does not improve as the quote ages -- the market decays, because a
price that has not moved in half an hour is a bad forecast of an outcome it has
not seen. On the subset the board liked best (late game, `|edge| >= 20pp`) the
MEDIAN quote age was 42.9 minutes and p90 was ~21 hours, and it scored a
fair-odds "return" of +98.7%. That is not an edge; it is the arithmetic of
pricing against a quote nobody could have taken.

THE FIRST TEST HERE IS A REACHABILITY TEST, NOT A CORRECTNESS TEST. `off != on`
comes before "is the answer right", because a gate that never fires passes every
correctness assertion ever written about it. This repo has shipped four inert
features caught by exactly this and nothing else.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.live_gameline_join import (
    REASON_NOT_PRICEABLE,
    REASON_QUOTE_AGE_ABSENT,
    REASON_STALE_QUOTE,
    attach_live_gamelines,
    build_live_gameline_index,
    max_quote_age_seconds,
    quote_age_verdict,
)

FRESH = 30.0
STALE = 4_000.0  # ~67 min; inside the p90..p99 band the ledger actually holds


def _snapshot(prob=0.6842):
    """One live game with a `live_mc` lane -- the shape the index accepts.

    Mirrors `test_live_gameline_join`'s fixture deliberately. `totalRunsDist` /
    `marginDist` are added so the totals and spreads branches are REACHABLE:
    without them those rows refuse for a missing distribution and the
    choke-point test below would pass for the wrong reason.
    """
    return {"games": [{
        "gamePk": 823184,
        "status": {"abstract": "Live"},
        "matchup": {"away": {"name": "Colorado Rockies", "abbr": "COL"},
                    "home": {"name": "San Francisco Giants", "abbr": "SF"}},
        "gameLens": [{
            "key": "live", "source": "live_mc", "modelHomeWinProb": prob,
            "simsRun": 120,
            "projection": {
                "total": 8.5, "homeMargin": 0.7,
                "totalRunsDist": {str(k): 1.0 / 15 for k in range(15)},
                "marginDist": {str(k): 1.0 / 15 for k in range(-7, 8)},
            },
        }],
    }]}


def _row(market="h2h", *, age_seconds=FRESH, market_prob=0.50, line=None):
    row = {
        "kind": "game",
        "market": market,
        "segment": "full",
        "away_team": "Colorado Rockies",
        "home_team": "San Francisco Giants",
        "age_seconds": age_seconds,
        "game": {"state": "live"},
        "projection": {"market_fair_prob_over": market_prob},
    }
    if line is not None:
        row["line"] = line
    return row


def _attach(rows):
    return attach_live_gamelines(rows, build_live_gameline_index(_snapshot()))


class TestReachability:
    """`off != on`. Without this, everything below could be vacuously true."""

    def test_a_stale_quote_is_refused_and_the_same_row_fresh_is_priced(self):
        fresh = _attach([_row(age_seconds=FRESH)])
        stale = _attach([_row(age_seconds=STALE)])

        assert fresh["rows_live_gameline_edged"] == 1
        assert stale["rows_live_gameline_edged"] == 0
        assert stale["withheld_by_reason"] == {REASON_STALE_QUOTE: 1}
        # Both rows were LOOKED AT -- the refusal is a decision, not a skip.
        assert fresh["rows_live_gameline_considered"] == 1
        assert stale["rows_live_gameline_considered"] == 1

    def test_raising_the_ceiling_prices_the_row_the_default_refuses(self, monkeypatch):
        """The knob is load-bearing, so it is exercised in both directions."""
        assert _attach([_row(age_seconds=STALE)])["rows_live_gameline_edged"] == 0
        monkeypatch.setenv("SYNDICATE_LIVE_GAMELINE_MAX_QUOTE_AGE_SECONDS", "99999")
        assert _attach([_row(age_seconds=STALE)])["rows_live_gameline_edged"] == 1


class TestTheChokePoint:
    """Every market the join prices goes through one gate.

    A staleness check placed inside the moneyline branch would leave totals and
    spreads pricing against dead quotes -- `learnings.md`: fix the choke point
    every caller shares, not the one you can see.
    """

    @pytest.mark.parametrize("market,line", [
        ("h2h", None), ("totals", 8.5), ("spreads", 1.5),
        ("totals_alt", 9.5), ("run_line", -1.5),
    ])
    def test_a_stale_quote_is_refused_on_every_priced_market(self, market, line):
        cov = _attach([_row(market, age_seconds=STALE, line=line)])
        assert cov["withheld_by_reason"] == {REASON_STALE_QUOTE: 1}
        assert cov["rows_live_gameline_priceable"] == 0
        # NOT counted as projected: the model never got a say. Folding a market
        # refusal into `projected` would misattribute it to the model.
        assert cov["rows_live_gameline_projected"] == 0


class TestUnknownIsNotPermissive:
    """An absent age must refuse, never pass.

    `learnings.md`: a guard that maps absent onto its permissive branch turns a
    failed join into a relaxed rule with no reason emitted. All 72,587 measured
    production records carried `age_seconds`, so this branch firing in the field
    is a bug report -- which is only true if it refuses.
    """

    @pytest.mark.parametrize("age", [None, "", "300", float("nan"), True])
    def test_an_unusable_age_refuses(self, age):
        verdict = quote_age_verdict(age)
        assert verdict is not None
        assert verdict["priceable"] is False
        assert verdict["withheld_reason"] in {REASON_QUOTE_AGE_ABSENT, REASON_STALE_QUOTE}

    def test_a_row_with_no_age_key_at_all_is_refused_by_name(self):
        row = _row()
        del row["age_seconds"]
        cov = _attach([row])
        assert cov["withheld_by_reason"] == {REASON_QUOTE_AGE_ABSENT: 1}

    def test_a_string_age_is_not_silently_parsed(self):
        """`"300"` is not a number here. Coercing it would let an upstream type
        change decide the gate."""
        assert quote_age_verdict("300")["withheld_reason"] == REASON_QUOTE_AGE_ABSENT


class TestTheGateDoesNotSwallowOtherVerdicts:
    """Freshness and priceability are different questions and stay separate."""

    def test_a_fresh_row_with_a_small_edge_still_refuses_for_precision(self):
        cov = _attach([_row(market_prob=0.67)])
        assert cov["withheld_by_reason"] == {REASON_NOT_PRICEABLE: 1}

    def test_the_boundary_is_inclusive(self):
        ceiling = max_quote_age_seconds()
        assert quote_age_verdict(ceiling) is None
        assert quote_age_verdict(ceiling + 0.001) is not None

    def test_zero_age_is_fresh(self):
        assert quote_age_verdict(0) is None


class TestTheKnob:
    def test_default_is_600_seconds(self):
        assert max_quote_age_seconds() == 600.0

    @pytest.mark.parametrize("raw", ["", "nonsense", "0", "-5"])
    def test_an_unusable_knob_falls_back_to_the_default_rather_than_off(
        self, monkeypatch, raw
    ):
        """A knob that can be typo'd into "no gate" is the shape `#603` shipped
        inert twice with. Non-positive and unparseable both mean "use default"."""
        monkeypatch.setenv("SYNDICATE_LIVE_GAMELINE_MAX_QUOTE_AGE_SECONDS", raw)
        assert max_quote_age_seconds() == 600.0

    def test_a_valid_knob_is_honoured(self, monkeypatch):
        monkeypatch.setenv("SYNDICATE_LIVE_GAMELINE_MAX_QUOTE_AGE_SECONDS", "120")
        assert max_quote_age_seconds() == 120.0


class TestTheAbsoluteEdgeFloor:
    """`min_edge_pp` decouples the publish bar from the sim count.

    The precision gate is `|edge| >= sigma * se * 100`, and `se` shrinks as
    sims rise -- so improving the estimator SILENTLY WIDENS publication. On
    fresh quotes the model is worse than the market in every edge band and
    worst above 20pp, so that widening is strictly harmful. The floor is the
    knob that has to be set before `MLB_LIVE_GAME_MC_SIMS` is raised.
    """

    def test_default_is_off_so_behaviour_is_unchanged(self):
        from syndicate.features.shared.live_gameline_join import min_edge_pp

        assert min_edge_pp() == 0.0
        # An 18.42pp edge at 120 sims prices today and must keep pricing.
        assert _attach([_row(market_prob=0.50)])["rows_live_gameline_edged"] == 1

    def test_the_floor_can_only_tighten_never_loosen(self, monkeypatch):
        """Reachability, both directions, on the SAME row."""
        assert _attach([_row(market_prob=0.50)])["rows_live_gameline_edged"] == 1
        monkeypatch.setenv("SYNDICATE_LIVE_GAMELINE_MIN_EDGE_PP", "25")
        cov = _attach([_row(market_prob=0.50)])
        assert cov["rows_live_gameline_edged"] == 0
        assert cov["withheld_by_reason"] == {REASON_NOT_PRICEABLE: 1}

    def test_a_floor_below_the_precision_bar_changes_nothing(self, monkeypatch):
        """`max` means a slack floor cannot admit a row precision refuses."""
        monkeypatch.setenv("SYNDICATE_LIVE_GAMELINE_MIN_EDGE_PP", "0.5")
        # 0.67 vs 0.6842 is ~1.4pp -- under the ~9pp precision bar at 120 sims.
        cov = _attach([_row(market_prob=0.67)])
        assert cov["rows_live_gameline_edged"] == 0
        assert cov["withheld_by_reason"] == {REASON_NOT_PRICEABLE: 1}

    @pytest.mark.parametrize("raw", ["", "nonsense", "-3", "0"])
    def test_an_unusable_floor_reads_as_off_not_as_a_block(self, monkeypatch, raw):
        from syndicate.features.shared.live_gameline_join import min_edge_pp

        monkeypatch.setenv("SYNDICATE_LIVE_GAMELINE_MIN_EDGE_PP", raw)
        assert min_edge_pp() == 0.0


class TestTheV4LedgerFieldsAreActuallyPOPULATED:
    """Producer -> join -> row -> ledger, asserted on VALUES not on key presence.

    THIS TEST CAUGHT A REAL INERT SHIP. `live_gameline_from_lens` was extended
    and `build_records` was extended, and the fields still arrived as `None`,
    because `_apply_verdict` copies an EXPLICIT key list into
    `row["live_gameline"]` and neither key was on it. Every other test was
    green: the ledger had the columns, the columns were null, and a null is
    indistinguishable from "this game had no clock". `presence != reachability`.
    """

    @staticmethod
    def _record(lens_extra):
        from syndicate.features.shared.live_gameline_ledger import build_records

        lens = {"key": "live", "source": "live_mc", "modelHomeWinProb": 0.6842,
                "simsRun": 120, "projection": {"total": 8.5, "homeMargin": 0.7}}
        lens.update(lens_extra)
        snapshot = {"games": [{
            "gamePk": 823184, "status": {"abstract": "Live"},
            "matchup": {"away": {"name": "Colorado Rockies"},
                        "home": {"name": "San Francisco Giants"}},
            "gameLens": [lens]}]}
        grid = [_row(market_prob=0.50)]
        grid[0]["game"].update(home_score=3, away_score=2)
        attach_live_gamelines(grid, build_live_gameline_index(snapshot))
        return build_records(grid, sport="mlb", date_str="2026-09-01",
                             generated_at="2026-09-01T00:00:00Z")[0]

    def test_the_clock_and_the_pregame_baseline_reach_the_ledger(self):
        rec = self._record({
            "baselineHomeWinProb": 0.5571,
            "progress": {"fraction": 0.55, "inning": 5, "half": "bottom",
                         "outs": 1, "outsRecorded": 28}})
        assert rec["v"] == 4
        assert rec["inning"] == 5
        assert rec["half"] == "bottom"
        assert rec["outs"] == 1
        assert rec["outs_recorded"] == 28
        assert rec["progress_fraction"] == 0.55
        assert rec["pregame_home_win_prob"] == 0.5571

    def test_a_snapshot_written_before_v4_degrades_to_the_old_behaviour(self):
        """Null clock, null baseline, and the probability UNCHANGED. An old
        snapshot must not become a wrong number -- only a less-annotated one."""
        rec = self._record({})
        assert rec["inning"] is None
        assert rec["pregame_home_win_prob"] is None
        # WAS 0.6842 -- the RAW `k/n` the snapshot carries. The ledger records
        # what was PUBLISHED, which is now the Agresti-Coull estimate the
        # interval was always computed from: (0.6842*120 + 2)/124 = 0.678258.
        # The ledger grading the published number rather than an internal one is
        # the point -- a ledger that stored a value the board never showed could
        # not be used to judge the board.
        assert rec["model_home_win_prob"] == pytest.approx(0.678258, abs=1e-6)
        assert rec["priceable"] is True


class TestTheScorerSaysWhatItIsWithoutASample:
    """`scorer_contract` must reach the payload on EVERY branch.

    MEASURED 2026-09-01T16:56:16Z, 56 seconds after the staleness gate went
    live: the board carried 300 pregame rows, `book_grid_artifact` took its
    `no_final_games_on_this_grid` branch, and the served block was exactly
    ['enabled', 'finals_index', 'games_with_outcome', 'reason']. No
    `fresh_quote_seconds`, no `scored_markets`. So "the new scorer shipped and
    had nothing to score" and "the new scorer did not ship" were the same null,
    and the deploy could not be verified until a game finished.

    A healthy reading is evidence only once you know what makes it read
    unhealthy. These are constants; they never needed a sample.
    """

    def test_the_capabilities_are_constants_and_need_no_records(self):
        from syndicate.features.shared.live_gameline_score import (
            SCORER_CONTRACT, scorer_capabilities,
        )

        caps = scorer_capabilities()
        assert caps["scorer_contract"] == SCORER_CONTRACT
        assert caps["scored_markets"] == ["h2h"]
        assert caps["fresh_quote_seconds"] == 120.0
        assert "le_120s" in caps["quote_age_buckets"]
        assert "gt_1800s" in caps["quote_age_buckets"]

    def test_the_no_finals_branch_carries_the_stamp(self):
        """THE REGRESSION TEST FOR THE REAL DEFECT.

        A grid of pregame rows is the normal mid-slate state. The exact payload
        production served at 16:56:16Z was
        ['enabled', 'finals_index', 'games_with_outcome', 'reason'] -- this
        asserts the two keys that were missing from it.
        """
        from syndicate.features.shared.book_grid_artifact import score_block_for_grid

        pregame = [{"kind": "game", "market": "h2h", "segment": "full",
                    "away_team": "Colorado Rockies",
                    "home_team": "San Francisco Giants",
                    "game": {"state": "pregame", "home_score": None,
                             "away_score": None}}]
        block = score_block_for_grid(pregame, sport="mlb", date_str="2026-09-01")
        assert block["reason"] == "no_final_games_on_this_grid"
        assert block["games_with_outcome"] == 0
        assert block["scorer_contract"] is not None, (
            f"no scorer_contract in {sorted(block)} -- the payload cannot say "
            f"whether this scorer is deployed")
        assert block["fresh_quote_seconds"] == 120.0
        assert block["scored_markets"] == ["h2h"]

    def test_the_error_branch_also_carries_the_stamp(self, monkeypatch):
        """A scorer that threw still has an identity. Without this, an exception
        and an old deploy look the same from the payload."""
        import syndicate.features.shared.live_gameline_score as mod
        from syndicate.features.shared.book_grid_artifact import score_block_for_grid

        def boom(*_a, **_k):
            raise RuntimeError("synthetic")

        monkeypatch.setattr(mod, "build_finals_index", boom)
        block = score_block_for_grid([], sport="mlb", date_str="2026-09-01")
        assert "error" in block and "RuntimeError" in block["error"]
        assert block["scorer_contract"] is not None
        assert block["fresh_quote_seconds"] == 120.0

    def test_the_block_never_raises(self, monkeypatch):
        """The board is the product; this is instrumentation."""
        import syndicate.features.shared.live_gameline_score as mod
        from syndicate.features.shared.book_grid_artifact import score_block_for_grid

        monkeypatch.setattr(mod, "build_finals_index",
                            lambda *a, **k: (_ for _ in ()).throw(ValueError("x")))
        assert score_block_for_grid(None, sport="mlb", date_str="bad-date")["enabled"] is True

    def test_score_ledger_records_still_reports_its_own_markets(self):
        """The stamp must not shadow the scorer's own output when it ran."""
        from syndicate.features.shared.live_gameline_score import score_ledger_records

        out = score_ledger_records(
            [{"market": "h2h", "game_pk": "1", "model_home_win_prob": 0.6,
              "market_fair_prob": 0.5, "priceable": True, "recorded_at": "2026-09-01T00:00:00Z",
              "quote_age_seconds": 30.0}],
            {"1": True},
        )
        assert out["scored_markets"] == ["h2h"]
        assert out["fresh_quote_seconds"] == 120.0
        assert out["games_with_outcome"] == 1
