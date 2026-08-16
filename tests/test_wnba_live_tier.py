"""WNBA's published live lens reaches the board's game-line tier.

WHY THIS EXISTS. `attach_live_gamelines_for_sport` was gated `if sport != "mlb"`
on the stated grounds that "the 120-sim re-sim is MLB's" and that WNBA "has no
live tier at all". The first half is still true. **The second went stale.**

Measured on production 2026-08-16 22:2xZ against a real live WNBA slate
(CHI @ SEA 58-53, IND @ ATL 51-58):

  - the live-lens loop already runs for wnba -- `/api/ops/live-lens/status`
    reports `activeSports: ["mlb","wnba","soccer"]`, wnba `ok: true`, on a 60s
    tick, writing the exact path this join reads;
  - 3 of 3 `gameLens` entries carried `modelHomeWinProb`, and the 2 live games
    carried `projection {total, homeMargin, homeScore, awayScore}` re-projected
    off the live score (total 151.17 against a pregame 173.96 at 60-53);
  - and the Layer 1 board served **0 of 521 rows** live-aware across those two
    games, because of the gate rather than the data.

THE FIXTURES BELOW ARE THE REAL SNAPSHOT SHAPE, not an invented one: wnba
carries `away`/`home` at the TOP level with no `matchup` wrapper, stamps
`source: "live_projection"` rather than `live_mc`, and publishes NO `simsRun`.
All three of those were verified against the served payload before this file
was written.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.live_gameline_join import (
    LIVE_STATE_LENS_SOURCE,
    build_live_gameline_index,
    lens_sources_for_sport,
    live_gameline_from_lens,
)


def _wnba_lens(source="live_projection", **over):
    lens = {
        "key": "live",
        "label": "Live",
        "source": source,
        "modelHomeWinProb": 0.2832,
        "projection": {"awayScore": 60.0, "homeMargin": -7.0, "homeScore": 53.0, "total": 151.17},
    }
    lens.update(over)
    return lens


def _wnba_snapshot(**over):
    game = {
        "gamePk": "07748b73",
        # TOP LEVEL, no `matchup` -- this is the shape wnba actually publishes.
        "away": {"abbr": "CHI", "name": "Chicago Sky"},
        "home": {"abbr": "SEA", "name": "Seattle Storm"},
        "away_name": "Chicago Sky",
        "home_name": "Seattle Storm",
        "gameLens": [_wnba_lens()],
    }
    game.update(over)
    return {"games": [game]}


def test_wnba_source_is_accepted_and_mlbs_is_not_weakened():
    assert lens_sources_for_sport("wnba") == ("live_projection",)
    assert lens_sources_for_sport("mlb") == (LIVE_STATE_LENS_SOURCE,)
    # An unknown sport gets MLB's stamp, NOT "anything". A sport whose lens shape
    # nobody has looked at must fail to join and be counted, not be admitted.
    assert lens_sources_for_sport("nhl") == (LIVE_STATE_LENS_SOURCE,)
    assert lens_sources_for_sport(None) == (LIVE_STATE_LENS_SOURCE,)


def test_the_wnba_snapshot_indexes_under_wnba_sources():
    index = build_live_gameline_index(_wnba_snapshot(), sources=lens_sources_for_sport("wnba"))
    assert len(index) == 1
    hit = index[("chicago sky", "seattle storm")]
    assert hit["home_win_prob"] == pytest.approx(0.2832)
    assert hit["total_mean"] == pytest.approx(151.17)
    assert hit["home_margin"] == pytest.approx(-7.0)


def test_the_same_snapshot_indexes_ZERO_under_mlbs_sources():
    """The control, and the reason this is a per-sport table rather than a
    relaxed check: MLB keys on `source` precisely so a lens the re-sim never
    touched cannot be admitted. Widening that check globally would have handed
    MLB every `pregame` lane in its own snapshot."""
    assert build_live_gameline_index(_wnba_snapshot()) == {}


def test_a_pregame_wnba_lane_is_refused():
    """wnba stamps `pregame` on games that have not tipped -- observed on the
    third game of that slate. The stamp is as discriminating for wnba as
    `live_mc` is for mlb; it is simply spelled differently."""
    snap = _wnba_snapshot(gameLens=[_wnba_lens(source="pregame")])
    assert build_live_gameline_index(snap, sources=lens_sources_for_sport("wnba")) == {}


def test_top_level_teams_and_matchup_teams_both_index():
    """MLB nests under `matchup`; wnba does not. Both must work, and a snapshot
    with a PARTIAL matchup must not build a key from two different games."""
    mlb_shaped = {
        "games": [{
            "gamePk": 1,
            "matchup": {"away": {"name": "Chicago Sky"}, "home": {"name": "Seattle Storm"}},
            "gameLens": [_wnba_lens()],
        }]
    }
    assert len(build_live_gameline_index(mlb_shaped, sources=("live_projection",))) == 1

    half = {
        "games": [{
            "gamePk": 1,
            "matchup": {"away": {"name": "Chicago Sky"}},   # home missing
            "away": {"name": "Chicago Sky"},
            "home": {"name": "Seattle Storm"},
            "gameLens": [_wnba_lens()],
        }]
    }
    idx = build_live_gameline_index(half, sources=("live_projection",))
    assert list(idx) == [("chicago sky", "seattle storm")], "partial matchup must fall through whole"


def test_absent_simsRun_survives_the_index_and_is_not_invented():
    """wnba publishes no `simsRun`. It must arrive as None so the precision gate
    withholds by name -- `prob_std_err` returns None rather than 0.0 precisely
    because a 0.0 would read as perfectly precise and make every edge
    priceable. This asserts nothing downstream fabricates an n."""
    index = build_live_gameline_index(_wnba_snapshot(), sources=lens_sources_for_sport("wnba"))
    assert index[("chicago sky", "seattle storm")]["sims_run"] is None


def test_source_filter_still_applies_when_sources_is_omitted():
    """Default stays MLB's, so every existing caller behaves exactly as before."""
    assert live_gameline_from_lens([_wnba_lens()]) is None
    assert live_gameline_from_lens([_wnba_lens(source=LIVE_STATE_LENS_SOURCE)]) is not None
