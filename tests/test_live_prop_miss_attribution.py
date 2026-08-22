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


# --- the two status vocabularies -----------------------------------------

def _status_snap(status):
    return {"games": [{"away_name": "WSH", "home_name": "MIN", "status": status,
        "liveProps": [_prop("Napheesa Collier", "player_points", 19.5)]}]}


def test_a_live_wnba_game_counts_as_live():
    """WNBA's lens writes `status`/`detail`; MLB's writes `abstract`/`detailed`.

    Reading only the MLB pair made `live_games` structurally 0 for WNBA no
    matter how many games were in play -- confirmed in production 2026-08-22
    with two WNBA games live and the lens actively polling both.
    """
    idx = build_live_prop_index(_status_snap(
        {"status": "In Progress", "detail": "Q3 04:12", "final": False}))
    assert idx["live_games"] == 1
    assert list(idx["by_game_state"]) == ["live"]


def test_mlb_status_shape_is_unchanged():
    idx = build_live_prop_index(_status_snap({"abstract": "Live", "detailed": "In Progress"}))
    assert idx["live_games"] == 1


@pytest.mark.parametrize("status,expected_bucket", [
    ({"status": "Final", "detail": "Final", "final": True}, "final"),
    ({"status": "Scheduled", "detail": "7:00 PM ET"}, "pregame"),
    ({"abstract": "Final", "detailed": "Game Over"}, "final"),
])
def test_non_live_states_are_not_counted_live_in_either_vocabulary(status, expected_bucket):
    """FINAL is checked first in both spellings -- mislabelling a finished game
    as live puts guaranteed-null rows into the one bucket that can prove
    anything."""
    idx = build_live_prop_index(_status_snap(status))
    assert idx["live_games"] == 0
    assert list(idx["by_game_state"]) == [expected_bucket]


def test_an_unreadable_status_is_unknown_not_live():
    idx = build_live_prop_index(_status_snap({"someOtherKey": "whatever"}))
    assert idx["live_games"] == 0
    assert list(idx["by_game_state"]) == ["unknown"]


# --- WHY an edge was withheld, not just how many -------------------------
#
# `rows_live_edge_withheld` is one total over three unrelated causes, and the
# soccer reading on production 2026-08-22 16:46Z was the case it cannot
# explain: `projected=114 edged=0 prob_withheld=0`. Every one of those 114 rows
# joined AND carried a live probability AND was priced zero times. The total
# says that happened; it cannot say which of "no fair value on the quote side",
# "the prop is already decided", or "the arithmetic failed" did it -- and those
# have three different owners.
#
# Same contract as the miss counters above: a zero must be attributable.

def test_a_row_with_no_market_fair_value_names_the_quote_side():
    """The live re-sim did its job; the DE-VIG had no answer."""
    # Line ABOVE the fixture's banked `actualSoFar` -- a decided prop is
    # refused earlier and for a different reason, which is exactly the
    # distinction this test exists to make.
    idx = build_live_prop_index(_snapshot([_prop("Aaron Judge", "hitter_strikeouts", 5.5)]))
    row = _row("Aaron Judge", "batter_strikeouts", 5.5)
    row["projection"] = {}          # no `market_fair_prob_over`
    out = attach_live_projections([row], idx)
    assert out["rows_live_projected"] == 1
    assert out["rows_live_edged"] == 0
    assert out["edge_withheld_by_reason"] == {"no_market_fair_value": 1}


def test_a_settled_prop_is_named_as_settled_rather_than_as_a_missing_price():
    """`actualSoFar` past the line: the book has settled, so there is no bet.

    Counted apart from the fair-value case deliberately -- this one is the join
    working exactly as designed and must never be read as a defect.
    """
    idx = build_live_prop_index(
        _snapshot([_prop("Aaron Judge", "hitter_strikeouts", 0.5, actualSoFar=3)])
    )
    row = _row("Aaron Judge", "batter_strikeouts", 0.5)
    row["projection"] = {"market_fair_prob_over": 0.3}
    out = attach_live_projections([row], idx)
    assert out["rows_live_edged"] == 0
    assert out["edge_withheld_by_reason"] == {"over_already_decided": 1}


def test_a_row_that_prices_is_absent_from_the_withheld_split():
    idx = build_live_prop_index(_snapshot([_prop("Aaron Judge", "hitter_strikeouts", 5.5)]))
    row = _row("Aaron Judge", "batter_strikeouts", 5.5)
    row["projection"] = {"market_fair_prob_over": 0.3}
    out = attach_live_projections([row], idx)
    assert out["rows_live_edged"] == 1
    assert out["edge_withheld_by_reason"] == {}


def test_the_split_reconciles_with_the_total_it_explains():
    """A breakdown that does not sum to its total is worse than no breakdown."""
    idx = build_live_prop_index(
        _snapshot(
            [
                _prop("Aaron Judge", "hitter_strikeouts", 5.5),
                _prop("Mookie Betts", "hitter_strikeouts", 0.5, actualSoFar=3),
            ]
        )
    )
    rows = [_row("Aaron Judge", "batter_strikeouts", 5.5)]
    settled = _row("Mookie Betts", "batter_strikeouts", 0.5)
    settled["projection"] = {"market_fair_prob_over": 0.3}
    rows.append(settled)
    out = attach_live_projections(rows, idx)
    assert sum(out["edge_withheld_by_reason"].values()) == out["rows_live_edge_withheld"]
    assert out["edge_withheld_by_reason"] == {
        "no_market_fair_value": 1,
        "over_already_decided": 1,
    }
