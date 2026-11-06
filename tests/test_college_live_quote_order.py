"""A live college row is not priced against a quote taken before the score the re-sim used (lane wncaab-module, user
2026-11-06 "Yes, do it here").

Measured on the 11-03..11-05 fleet ledgers (`live_gameline_join.REASON_QUOTE_BEHIND_SCORE` has the table): the model
beat the de-vigged market only where the book's quote predated the score the model was handed. These pin the gate:
it is the ORDER of the two clocks, it is college only, unknown refuses, and it changes the board's answer.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.live_gameline_join import (
    REASON_QUOTE_BEHIND_SCORE,
    REASON_QUOTE_OR_SCORE_TIME_ABSENT,
    REASON_STALE_QUOTE,
    attach_live_gamelines,
    build_live_gameline_index,
    quote_behind_score_verdict,
)

SCORE_AT = "2026-11-05T01:00:00+00:00"


@pytest.mark.parametrize("sport", ["ncaab", "wncaab"])
@pytest.mark.parametrize("quote_at,refused", [
    ("2026-11-05 00:59:29+00:00", True),     # 31 s before the score
    ("2026-11-05 00:59:30+00:00", False),    # 30 s before: the measured tolerance
    ("2026-11-05 01:00:00+00:00", False),
    ("2026-11-05 01:06:40+00:00", False),    # 400 s NEWER than the score: a fair comparison
    ("2026-11-05T00:50:00Z", True),          # the other spelling
    ("2026-11-05 00:50:00", True),           # naive reads as UTC
])
def test_a_quote_older_than_the_score_is_refused_and_a_newer_one_is_not(sport, quote_at, refused):
    verdict = quote_behind_score_verdict(quote_at, SCORE_AT, sport=sport)
    if refused:
        assert verdict == {"priceable": False, "withheld_reason": REASON_QUOTE_BEHIND_SCORE,
                           "model_prob": None, "market_prob": None, "edge_pp": None}
    else:
        assert verdict is None


@pytest.mark.parametrize("quote_at,score_at", [(None, SCORE_AT), ("", SCORE_AT), ("2026-11-05 00:59:00+00:00", None),
                                               ("not a time", SCORE_AT)])
def test_an_unknown_time_on_a_college_row_refuses_by_name(quote_at, score_at):
    verdict = quote_behind_score_verdict(quote_at, score_at, sport="ncaab")
    assert verdict["withheld_reason"] == REASON_QUOTE_OR_SCORE_TIME_ABSENT


@pytest.mark.parametrize("sport", ["mlb", "nba", "wnba", "nhl", "nfl", "ncaaf", "soccer", None, ""])
def test_every_other_sport_is_unchanged(sport):
    """Measured for college only; an unmeasured sport must not inherit college's number, nor refuse on absent times."""
    assert quote_behind_score_verdict("2026-11-05 00:40:00+00:00", SCORE_AT, sport=sport) is None
    assert quote_behind_score_verdict(None, None, sport=sport) is None


# ------------------------------------------------------------------------------------- through the join

def _snapshot():
    return {"games": [{
        "home": "Duke Blue Devils", "away": "Army Black Knights",
        "gameLens": [{"key": "live", "source": "live_resim", "modelHomeWinProb": 0.9, "simsRun": 200,
                      "liveStateAsOf": SCORE_AT, "projection": {"total": 140.0, "homeMargin": 12.0}}],
    }]}


def _row(quote_at, age_seconds=20.0):
    return {"kind": "game", "market": "h2h", "segment": "full", "away_team": "Army Black Knights",
            "home_team": "Duke Blue Devils", "age_seconds": age_seconds, "updated_at": quote_at,
            "game": {"state": "live"}, "projection": {"market_fair_prob_over": 0.40}}


def _attach(rows, sport="ncaab"):
    index = build_live_gameline_index(_snapshot(), sources=("live_resim",), sport=sport)
    return attach_live_gamelines(rows, index, sport=sport)


@pytest.mark.parametrize("sport", ["ncaab", "wncaab"])
def test_off_is_not_on_the_same_row_priced_after_the_score_and_refused_before_it(sport):
    after, before = [_row("2026-11-05 01:00:05+00:00")], [_row("2026-11-05 00:58:00+00:00")]
    cov_after = _attach(after, sport)
    cov_before = _attach(before, sport)
    assert after[0]["live_gameline"]["home_win_prob"] == pytest.approx(0.9)
    assert after[0]["live_gameline"].get("edge_pp") is not None
    assert "live_gameline" not in before[0]
    assert cov_before["withheld_by_reason"] == {REASON_QUOTE_BEHIND_SCORE: 1}
    assert REASON_QUOTE_BEHIND_SCORE not in (cov_after.get("withheld_by_reason") or {})


def test_the_age_ceiling_still_applies_to_a_quote_newer_than_the_score():
    """The order gate adds a refusal; it never lifts the 600 s ceiling."""
    rows = [_row("2026-11-05 01:00:05+00:00", age_seconds=900.0)]
    cov = _attach(rows)
    assert cov["withheld_by_reason"] == {REASON_STALE_QUOTE: 1}
