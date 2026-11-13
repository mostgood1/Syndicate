"""NFL quarter/half skill grade (lane nfl-segment-skill, todo #752).

Covers the grader's arithmetic (`scripts/nfl_segment_skill.py`), the registry entries it
produced (`measured_market_skill`), and the served path: an NFL segment row must reach
`attach_projection_skill` WITHOUT a producer note, so the registry decides it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import nfl_segment_skill as G  # noqa: E402
from syndicate.features.shared import measured_market_skill as mms  # noqa: E402

SEGMENTS = ("h1", "h2", "q1", "q2", "q3", "q4")


# ---------------------------------------------------------------- grader ----
def test_devig_pair_is_proportional():
    assert G.devig_pair(-110, -110) == pytest.approx(0.5)
    a, b = 150 / 250, 100 / 230  # -150 / +130
    assert G.devig_pair(-150, 130) == pytest.approx(a / (a + b))
    assert G.devig_pair(None, -110) is None
    assert G.american_to_prob(50) is None  # not an American price


def test_frame_line_puts_spreads_in_the_away_frame():
    assert G.frame_line("spreads", "home", 6.5) == -6.5
    assert G.frame_line("spreads", "away", -6.5) == -6.5
    assert G.frame_line("totals", "over", 9.5) == 9.5
    assert G.frame_line("h2h", "home", None) == 0.0
    assert G.frame_line("totals", "over", None) is None


def _q(book, cap, sel, line, price, *, market="totals", segment="q1", start="2026-11-08T18:00:00Z", event="e1"):
    return {"kind": "game", "event_id": event, "segment": segment, "market": market, "bookmaker": book,
            "captured_at": cap, "commence_time": start, "selection": sel, "line": line, "price": price,
            "home_team": "Detroit Lions", "away_team": "Miami Dolphins"}


def test_consensus_uses_each_books_last_pregame_pair_at_the_modal_line():
    quotes = [
        _q("a", "2026-11-08T12:00:00Z", "over", 10.5, -150), _q("a", "2026-11-08T12:00:00Z", "under", 10.5, 120),
        # book a's LATER snapshot replaces its earlier one
        _q("a", "2026-11-08T17:30:00Z", "over", 9.5, -110), _q("a", "2026-11-08T17:30:00Z", "under", 9.5, -110),
        _q("b", "2026-11-08T17:40:00Z", "over", 9.5, -120), _q("b", "2026-11-08T17:40:00Z", "under", 9.5, 100),
        _q("c", "2026-11-08T17:40:00Z", "over", 10.5, -105), _q("c", "2026-11-08T17:40:00Z", "under", 10.5, -115),
        # after kickoff: never counted
        _q("b", "2026-11-08T18:05:00Z", "over", 9.5, 400), _q("b", "2026-11-08T18:05:00Z", "under", 9.5, -600),
    ]
    got = G.consensus_markets(quotes)[("e1", "q1", "totals")]
    assert got["line"] == 9.5
    assert got["books_at_line"] == 2 and got["books"] == 3
    assert got["market_prob"] == pytest.approx((0.5 + G.devig_pair(-120, 100)) / 2)


def test_consensus_pairs_spread_sides_across_the_sign_flip():
    quotes = [_q("a", "2026-11-08T17:00:00Z", "home", 3.5, -110, market="spreads"),
              _q("a", "2026-11-08T17:00:00Z", "away", -3.5, -110, market="spreads")]
    got = G.consensus_markets(quotes)[("e1", "q1", "spreads")]
    assert got["line"] == -3.5 and got["market_prob"] == pytest.approx(0.5)


def test_segment_outcome_matches_the_grid_conventions():
    assert G.segment_outcome("totals", 9.5, 7, 3) == 1
    assert G.segment_outcome("totals", 10.0, 7, 3) is None
    assert G.segment_outcome("spreads", -3.5, 7, 10) == 1   # away -3.5: home lost by 3, covers
    assert G.segment_outcome("spreads", -3.5, 3, 10) == 0
    assert G.segment_outcome("h2h", 0.0, 7, 7) is None
    assert G.segment_outcome("h2h", 0.0, 0, 3) == 0


def test_clustered_ci_resamples_games_and_is_reproducible():
    obs = [{"game": "g1", "v": 1.0}, {"game": "g1", "v": 1.0}, {"game": "g2", "v": 0.0}]
    one = G.clustered_ci(obs, lambda o: o["v"], reps=500, seed=1)
    assert one == G.clustered_ci(obs, lambda o: o["v"], reps=500, seed=1)
    assert one[0] == pytest.approx(2 / 3)
    assert 0.0 <= one[1] <= one[0] <= one[2] <= 1.0


def test_build_observations_prices_with_production_arithmetic(tmp_path):
    from syndicate.features.ncaaf.segment_projections import probability_above
    from syndicate.features.shared.nfl_segment_projections import load_nfl_segment_blocks

    seg = {"total_points_dist": {"3": 30, "7": 40, "14": 30}, "margin_dist": {"-7": 30, "0": 20, "7": 50},
           "home_points_mean": 5.0, "away_points_mean": 3.0}
    payload = {"games": {"2026_10_MIA_DET": {"sims": 100, "segments": {"q1": seg, "full": seg}}}}
    (tmp_path / "smartsim2_segment_distributions_2026_wk10.json").write_text(json.dumps(payload), encoding="utf-8")
    blocks = load_nfl_segment_blocks([tmp_path])
    quotes = [_q("a", "2026-11-08T17:00:00Z", "over", 9.5, -110), _q("a", "2026-11-08T17:00:00Z", "under", 9.5, -110),
              _q("a", "2026-11-08T17:00:00Z", "home", 0.0, -110, market="h2h"),
              _q("a", "2026-11-08T17:00:00Z", "away", 0.0, -110, market="h2h")]
    consensus = G.consensus_markets(quotes)
    from syndicate.features.shared.nfl_segment_projections import _team_key

    box = {"home": [7, 0, 3, 3], "away": [7, 3, 10, 3], "final": True}
    lines ={f"{_team_key('Detroit Lions')}|{_team_key('Miami Dolphins')}|2026-11-08": box}
    obs, refused = G.build_observations(consensus, blocks, lines)
    assert refused == {"push": 1}  # the q1 moneyline: 7-7
    (only,) = obs
    assert only["market"] == "totals" and only["y"] == 1  # 14 > 9.5
    assert only["p_model"] == pytest.approx(probability_above(seg["total_points_dist"], 9.5)[0])
    assert only["p_market"] == pytest.approx(0.5)


# -------------------------------------------------------------- registry ----
@pytest.mark.parametrize("market", ["totals", "spreads", "h2h"])
@pytest.mark.parametrize("segment", SEGMENTS)
def test_every_nfl_segment_market_has_a_pregame_note(market, segment):
    note = mms.skill_note(sport="nfl", market=market, segment=segment, phase=mms.PHASE_PREGAME)
    assert note is not None
    entry = mms.MEASURED_MARKET_SKILL[("nfl", market, segment, mms.PHASE_PREGAME)]
    for key in mms.REQUIRED_ENTRY_KEYS:
        assert entry[key] not in (None, "")
    lo, hi = entry["ci95"]
    expected = mms.VERDICT_LOSES if lo > 0 else (mms.VERDICT_BEATS if hi < 0 else mms.VERDICT_PARITY)
    assert entry["verdict_class"] == expected
    # The pregame note never labels a live re-sim.
    assert mms.skill_note(sport="nfl", market=market, segment=segment, phase=mms.PHASE_LIVE) is None


def test_only_the_established_moneyline_loss_moves_the_rank():
    h2h = mms.skill_note(sport="nfl", market="h2h", segment="q2", phase=mms.PHASE_PREGAME)
    assert h2h["established_loss_rel"] == pytest.approx(round(0.00167 / 0.22056, 5))
    assert mms.skill_reliability({**h2h, "status": "measured"}) < 1.0
    for market in ("totals", "spreads"):
        note = mms.skill_note(sport="nfl", market=market, segment="h1", phase=mms.PHASE_PREGAME)
        assert note["established_loss_rel"] == 0.0
        assert mms.skill_reliability({**note, "status": "measured"}) == 1.0


# ---------------------------------------------------------- served path ----
def _priced_grid(tmp_path):
    from syndicate.features.shared.nfl_segment_projections import attach_nfl_segment_projections, load_nfl_segment_blocks

    seg = {"total_points_dist": {"7": 40, "10": 30, "14": 30}, "margin_dist": {"-3": 30, "0": 20, "3": 30, "7": 20},
           "home_points_mean": 6.0, "away_points_mean": 5.0}
    payload = {"games": {"2026_05_TB_DAL": {"sims": 100, "segments": {"q1": seg, "q2": seg, "full": seg}}}}
    (tmp_path / "smartsim2_segment_distributions_2026_wk5.json").write_text(json.dumps(payload), encoding="utf-8")
    base = {"kind": "game", "home_team": "Dallas Cowboys", "away_team": "Tampa Bay Buccaneers",
            "commence_time": "2026-10-09T00:15:00Z"}
    rows = [dict(base, market="totals", segment="q1", line=10.5),
            dict(base, market="h2h", segment="q2", line=None),
            dict(base, market="spreads", segment="full", line=1.5,
                 projection={"projected": 1.0, "model_prob_over": None, "model_skill": {"verdict": "full-game own"}})]
    attach_nfl_segment_projections(rows, load_nfl_segment_blocks([tmp_path]))
    return rows


def test_segment_rows_reach_the_registry_without_a_producer_note(tmp_path):
    from syndicate.features.shared.projection_skill import attach_projection_skill

    total, h2h, full_spread = _priced_grid(tmp_path)
    # Reachability: the producer no longer pre-empts the registry (it used to stamp
    # {"state": "unmeasured"}, which projection_skill relabelled "measured" with no loss).
    assert "model_skill" not in total["projection"] and "model_skill" not in h2h["projection"]
    assert full_spread["projection"]["model_skill"] == {"verdict": "full-game own"}
    coverage = attach_projection_skill([total, h2h, full_spread], sport="nfl")
    assert coverage["rows_with_measured_skill_from_registry"] == 2
    assert total["projection"]["model_skill"]["verdict_class"] == mms.VERDICT_PARITY
    assert h2h["projection"]["model_skill"]["verdict_class"] == mms.VERDICT_LOSES
    assert mms.skill_reliability(h2h["projection"]["model_skill"]) < 1.0
    assert mms.skill_reliability(total["projection"]["model_skill"]) == 1.0
