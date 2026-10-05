"""THE SPORT-SCOPED PUBLISH SWITCH IS GONE: no sport's live edges can be switched off.

`[2026-10-05, user directive, lane stop-market-withholding]`: "WE HAVE TO STOP
WITHHOLDING MARKETS! ... each bet is at the line level". These tests pin that
`SYNDICATE_LIVE_GAMELINE_PUBLISH_DISABLED_SPORTS` is inert, and keep the real
caller-path regression (`f5c2468a`'s TypeError) that this file also guarded.
History of why the switch existed:

WHY THIS EXISTS. The MLB live game-line model loses to the market over 252
games / 19 dates (pooled +0.00905, bootstrap-over-games CI [+0.00154,
+0.01686], excludes zero), the deficit is RESOLUTION not calibration, and all
three cheap fixes are closed by measurement -- recalibration capped at 6.5%, no
subpopulation surviving leave-one-date-out, and a model/market blend that is
significantly worse out of sample. So MLB stops publishing edges.

THE TWO THINGS THAT MUST NOT BREAK, and neither is about MLB:

  1. SCOPE. The pre-existing floor `SYNDICATE_LIVE_GAMELINE_MIN_EDGE_PP` is
     GLOBAL and sport-blind. Using it would have silenced WNBA -- whose model
     BEATS the market on the record (-0.12504) -- on MLB-only evidence. Every
     test here that names wnba is guarding that, not padding the count.

  2. MEASUREMENT. A disabled row must still carry `edge_pp` and
     `prob_std_err` and still reach the ledger as non-priceable. Turning
     publication off must not destroy the evidence needed to ever turn it back
     on, including the `pregame_home_win_prob` shrink-toward-prior test that
     only just became possible.
"""

from __future__ import annotations

import json

import pytest

from syndicate.features.shared import board_enrichment
from syndicate.features.shared import live_gameline_join
from syndicate.features.shared.live_gameline_join import (
    REASON_NOT_PRICEABLE,
    attach_live_gamelines,
    build_live_gameline_index,
    price_moneyline,
)

ENV = "SYNDICATE_LIVE_GAMELINE_PUBLISH_DISABLED_SPORTS"

# A big, precise edge: comfortably clears the 2-sigma bar at 120 sims, so
# anything that refuses it is refusing on purpose rather than on precision.
CLEARS_THE_BAR = dict(model_prob=0.75, market_prob=0.50, sims=120)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv(ENV, raising=False)


class TestNoSportCanBeSwitchedOff:
    @pytest.mark.parametrize("raw", ["mlb", "nfl", "mlb,nfl,soccer,wnba,ncaaf"])
    def test_the_old_env_value_withholds_nothing(self, monkeypatch, raw):
        monkeypatch.setenv(ENV, raw)
        for sport in ("mlb", "nfl", "soccer", "wnba", "ncaaf"):
            v = price_moneyline(**CLEARS_THE_BAR, sport=sport)
            assert v["priceable"] is True, sport
            assert v["withheld_reason"] is None, sport

    def test_the_switch_no_longer_exists(self):
        assert not hasattr(live_gameline_join, "publishing_disabled_for_sport")
        assert not hasattr(live_gameline_join, "REASON_PUBLISH_DISABLED")

    def test_a_line_that_fails_its_OWN_precision_bar_is_still_refused(self, monkeypatch):
        """Line-level judgement stays: a tiny edge is refused for being tiny."""
        tiny = price_moneyline(model_prob=0.501, market_prob=0.500, sims=120, sport="nfl")
        assert tiny["withheld_reason"] == REASON_NOT_PRICEABLE


# ------------------------------------------------------------- the real caller

AWAY, HOME = "Colorado Rockies", "San Francisco Giants"


def _mlb_lens_snapshot():
    """A live MLB lens WITH the histograms, as `live_lens_loop` publishes it.

    100 sims, hand-countable: P(total > 7.5) = 0.40, P(margin > 0.5) = 0.45.
    Round-tripped through JSON below, so the dist keys are strings exactly as
    the worker reads them off disk.
    """
    return {"games": [{
        "gamePk": 823184, "status": {"abstract": "Live"},
        "matchup": {"away": {"name": AWAY}, "home": {"name": HOME}},
        "gameLens": [{
            "key": "live", "source": "live_mc", "modelHomeWinProb": 0.75, "simsRun": 100,
            "projection": {
                "total": 7.2, "homeMargin": 0.4,
                "totalRunsDist": {5: 10, 6: 20, 7: 30, 8: 20, 9: 15, 10: 5},
                "marginDist": {-3: 10, -2: 15, -1: 20, 0: 10, 1: 20, 2: 15, 3: 10},
            },
        }],
    }]}


def _row(market, *, line=None, market_prob=0.15, sport="mlb"):
    return {"sport": sport, "kind": "game", "market": market, "segment": "full",
            "away_team": AWAY, "home_team": HOME, "line": line,
            "age_seconds": 30.0, "game": {"state": "live"},
            "projection": {"market_fair_prob_over": market_prob}}


def _grid():
    # Every edge here clears the 2-sigma bar at 100 sims by >10pp, so a refusal
    # is the switch and never precision.
    return [_row("h2h", market_prob=0.50), _row("totals", line=7.5), _row("spreads", line=0.5)]


@pytest.fixture
def mlb_lens(tmp_path, monkeypatch):
    live = tmp_path / "live"
    live.mkdir()
    (live / "mlb_live_lens.json").write_text(json.dumps(_mlb_lens_snapshot()), encoding="utf-8")
    monkeypatch.setattr(
        "syndicate.features.shared.refresh_state_store.data_root", lambda: tmp_path)
    return tmp_path


class TestTheRealCallerPath:
    """Through `board_enrichment.attach_live_gamelines_for_sport`, the frame in
    the production traceback -- not `price_moneyline` alone.

    THE DEFECT THESE PIN (2026-09-09 03:58Z .. 2026-09-10): f5c2468a passed
    `sport=` to `price_distribution_market`, which had no such parameter. Every
    test above called the pricer directly and passed; the first live TOTALS or
    SPREADS row raised a TypeError that aborted the WHOLE attach -- h2h
    included -- for MLB and soccer, logged as `BOOK_GRID_LIVE_GAMELINE_FAILURE`
    153 times on refresh-worker. And the h2h call never received `sport`, so the
    switch was inert on the one market it was written for.
    """

    def test_a_live_totals_row_no_longer_aborts_the_attach(self, mlb_lens):
        grid = _grid()
        cov = board_enrichment.attach_live_gamelines_for_sport(
            grid, sport="mlb", selected_date="2026-09-10")
        assert "error" not in cov, cov
        assert cov["rows_live_gameline_considered"] == 3
        # off != on, OFF half: unset env prices every market exactly as before.
        assert cov["rows_live_gameline_edged"] == 3, cov
        for row in grid:
            assert row["live_gameline"]["priceable"] is True, row["market"]

    def test_the_old_env_value_leaves_every_market_priced(self, mlb_lens, monkeypatch):
        monkeypatch.setenv(ENV, "mlb")
        grid = _grid()
        cov = board_enrichment.attach_live_gamelines_for_sport(
            grid, sport="mlb", selected_date="2026-09-10")
        assert "error" not in cov, cov
        assert cov["rows_live_gameline_edged"] == 3, cov
        for row in grid:
            assert row["live_gameline"]["priceable"] is True, row["market"]

    def test_another_sports_distribution_pricing_is_unaffected(self, monkeypatch):
        monkeypatch.setenv(ENV, "mlb")
        snapshot = json.loads(json.dumps(_mlb_lens_snapshot()))
        grid = [_row("totals", line=7.5, sport="wnba")]
        cov = attach_live_gamelines(
            grid, build_live_gameline_index(snapshot, sport="wnba"), sport="wnba")
        assert cov["rows_live_gameline_edged"] == 1, cov
        assert grid[0]["live_gameline"]["priceable"] is True
