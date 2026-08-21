"""The three causes a live-prop miss can have must be counted separately."""
import pytest
from syndicate.features.shared.live_projection_join import (
    attach_live_projections, build_live_prop_index, _canonical_market,
)

def _snapshot(props):
    return {"games": [{"status": {"abstract": "live", "detailed": "In Progress"},
                       "liveProps": props}]}

def _prop(player, market, line, **kw):
    d = {"playerName": player, "prop": market, "line": line,
         "liveProjection": 1.2, "liveModelProbOver": 0.55, "actualSoFar": 1}
    d.update(kw); return d

def _row(player, market, line):
    return {"kind": "prop", "game": {"state": "live"}, "player_name": player,
            "market": market, "line": line, "projection": {}}

def test_batter_strikeouts_joins_the_sims_hitter_strikeouts_family():
    """`HITTER_PROPS` maps hitter_strikeouts -> batter_strikeouts, and
    batter_strikeouts is a market we pay to fetch every day."""
    assert _canonical_market("batter_strikeouts") == _canonical_market("hitter_strikeouts")
    idx = build_live_prop_index(_snapshot([_prop("Aaron Judge", "hitter_strikeouts", 0.5)]))
    out = attach_live_projections([_row("Aaron Judge", "batter_strikeouts", 0.5)], idx)
    assert out["rows_live_projected"] == 1, out

def test_pitcher_strikeouts_never_merges_with_the_batter_family():
    idx = build_live_prop_index(_snapshot([_prop("Gerrit Cole", "strikeouts", 5.5)]))
    out = attach_live_projections([_row("Gerrit Cole", "batter_strikeouts", 5.5)], idx)
    assert out["rows_live_projected"] == 0
    assert out["miss_no_market_alias"] == 1, out

def test_a_line_the_resim_did_not_price_is_counted_as_a_LINE_miss():
    """batter_hits_runs_rbis is fetched at 1.5/2.5/3.5; the re-sim prices one."""
    idx = build_live_prop_index(_snapshot([_prop("Mookie Betts", "hits_runs_rbis", 1.5)]))
    out = attach_live_projections([_row("Mookie Betts", "batter_hits_runs_rbis", 3.5)], idx)
    assert out["miss_no_line_match"] == 1, out
    assert out["miss_no_market_alias"] == 0, out
    assert out["unmatched_samples"][0]["lens_lines_available"] == [1.5]

def test_a_player_not_in_the_lens_is_counted_as_NOT_LIVE():
    idx = build_live_prop_index(_snapshot([_prop("Mookie Betts", "hits", 0.5)]))
    out = attach_live_projections([_row("Nobody Here", "batter_hits", 0.5)], idx)
    assert out["miss_player_not_live"] == 1, out
    assert out["miss_no_market_alias"] == 0, out

def test_a_genuine_vocabulary_gap_is_still_counted_as_a_MARKET_miss():
    idx = build_live_prop_index(_snapshot([_prop("Mookie Betts", "hits", 0.5)]))
    out = attach_live_projections([_row("Mookie Betts", "batter_home_runs", 0.5)], idx)
    assert out["miss_no_market_alias"] == 1, out
    assert out["miss_no_line_match"] == 0, out

def test_an_older_index_payload_degrades_to_the_old_counter_not_a_crash():
    """The two files deploy as separate blobs onto a long-lived worker."""
    idx = build_live_prop_index(_snapshot([_prop("Mookie Betts", "hits", 0.5)]))
    legacy = {k: v for k, v in idx.items() if k not in {"lines_by_player_market", "players_seen"}}
    out = attach_live_projections([_row("Mookie Betts", "batter_home_runs", 0.5)], legacy)
    assert out["miss_no_market_alias"] == 1, out
