"""Read-time refresh of LIVE PROJ. / LIVE ACTUAL on live NBA props (lane nba-live-proj-actuals).

NBA's two live columns were only written by the Layer 2 build, which publishes ~6.5 min after a join that runs
every ~9 min. On 2026-11-05 00:49Z three of five live games had none: the 00:41:34Z join ran before the re-sim
reached them at 00:44:01Z. The live lens on the web's own box already carried their props. These tests pin that
the web now reads the lens at request time, keyed exactly as the build's join keys, and touches nothing else."""
from __future__ import annotations

import pytest

import syndicate.blueprints.intelligence as bp
from syndicate.features.shared import live_projection_join as lpj

LENS = {
    "date": "2026-11-04",
    "generated_at": "2026-11-04T18:50:30-06:00",
    "games": [{
        "status": "Live",
        "liveProps": [
            {"playerName": "Alex Sarr", "prop": "player_rebounds", "line": 5.5, "liveProjection": 6.04,
             "liveModelProbOver": 0.61, "actualSoFar": 2.0, "simsRun": 100, "side": "home"},
            {"playerName": "Trae Young", "prop": "player_points", "line": 15.5, "liveProjection": 17.36,
             "liveModelProbOver": 0.62, "actualSoFar": 0.0, "simsRun": 100, "side": "away"},
            {"playerName": "Trae Young", "prop": "player_points", "line": 16.5, "liveProjection": 17.36,
             "liveModelProbOver": 0.55, "actualSoFar": 0.0, "simsRun": 100, "side": "away"},
        ],
    }],
}


def _prop(**overrides) -> dict:
    row = {"sport": "nba", "sport_slug": "nba", "is_live": True, "game_date": "2026-11-04",
           "player_name": "Alex Sarr", "market": "player_rebounds", "line": 5.5, "side": "over"}
    row.update(overrides)
    return row


@pytest.fixture(autouse=True)
def lens(monkeypatch):
    """The lens as web reads it (keyvalue-aware `read_json_file`); the per-process index cache cleared both sides."""
    state = {"snapshot": LENS, "reads": 0}

    def read(path):
        state["reads"] += 1
        assert path.name == "nba_live_lens.json"
        return state["snapshot"]

    monkeypatch.setattr(bp, "read_json_file", read)
    bp._LENS_PROP_INDEX_CACHE.clear()
    yield state
    bp._LENS_PROP_INDEX_CACHE.clear()


def test_a_live_nba_prop_the_build_left_blank_gets_the_lens_numbers():
    payload = {"ranked_all": [_prop()]}
    counts = bp._refresh_lens_prop_live_columns(payload)
    row = payload["ranked_all"][0]
    assert row["live_projection"] == 6.04 and row["live_total"] == 6.04 and row["actual"] == 2.0
    assert counts["nba"] == {"considered": 1, "matched": 1, "refreshed": 1, "no_lens_for_date": 0}


def test_a_stale_build_value_is_replaced_and_a_real_zero_actual_is_kept():
    payload = {"ranked_all": [_prop(player_name="Trae Young", market="player_points", line=15.5,
                                    live_projection=11.0, actual=None)]}
    bp._refresh_lens_prop_live_columns(payload)
    row = payload["ranked_all"][0]
    assert row["live_projection"] == 17.36 and row["actual"] == 0.0  # 0 points so far is a fact, not a blank


def test_it_is_the_build_joins_own_key():
    """Whatever row the build's join attaches, the read-time refresh attaches -- including a miss on the line."""
    indexed = lpj.build_live_prop_index(LENS)
    for player, market, line in [("Alex Sarr", "player_rebounds", 5.5), ("alex sarr", "player_rebounds", "5.5"),
                                 ("Trae Young", "player_points", 16.5), ("Trae Young", "player_points", 14.5),
                                 ("Nobody", "player_points", 15.5)]:
        grid = [{"kind": "prop", "game": {"state": "live"}, "player_name": player, "market": market, "line": line}]
        lpj.attach_live_projections(grid, indexed)
        hit = lpj.live_prop_hit(indexed, player, market, line)
        joined = (grid[0].get("projection") or {}).get("live_projected")
        assert (hit["live_projection"] if hit else None) == joined


@pytest.mark.parametrize("row", [
    _prop(is_live=False),                                # pregame rows keep the pregame tier
    _prop(sport="mlb", sport_slug="mlb"),                # another sport's own refresh owns its rows
    _prop(player_name=None, candidate_type="game", market="totals", line=220.5),  # game lines are priced, not refreshed
])
def test_rows_outside_scope_are_untouched(row):
    before = dict(row)
    payload = {"ranked_all": [row]}
    bp._refresh_lens_prop_live_columns(payload)
    assert payload["ranked_all"][0] == before


def test_a_lens_for_another_date_or_with_no_date_joins_nothing(lens):
    for snapshot in ({**LENS, "date": "2026-11-03"}, {k: v for k, v in LENS.items() if k != "date"}, None):
        bp._LENS_PROP_INDEX_CACHE.clear()
        lens["snapshot"] = snapshot
        payload = {"ranked_all": [_prop()]}
        counts = bp._refresh_lens_prop_live_columns(payload)
        assert "live_projection" not in payload["ranked_all"][0]
        assert counts["nba"]["no_lens_for_date"] == 1 and counts["nba"]["matched"] == 0


def test_a_row_the_lens_does_not_carry_keeps_what_the_build_gave_it():
    payload = {"ranked_all": [_prop(player_name="Somebody Else", live_projection=3.3, actual=1.0)]}
    bp._refresh_lens_prop_live_columns(payload)
    assert payload["ranked_all"][0]["live_projection"] == 3.3 and payload["ranked_all"][0]["actual"] == 1.0


def test_one_lens_read_per_request_and_one_count_per_row_object(lens):
    row = _prop()
    payload = {"ranked_all": [row, _prop(player_name="Trae Young", market="player_points", line=15.5)],
               "top_opportunities": [row], "by_sport": {"nba": [row]}}
    counts = bp._refresh_lens_prop_live_columns(payload)
    assert lens["reads"] == 1 and counts["nba"]["considered"] == 2


def test_the_index_is_reused_for_a_few_seconds_then_reread(lens):
    bp._lens_prop_index("nba", now=1000.0)
    bp._lens_prop_index("nba", now=1000.0 + bp._LENS_PROP_INDEX_TTL_SECONDS - 1)
    assert lens["reads"] == 1
    bp._lens_prop_index("nba", now=1000.0 + bp._LENS_PROP_INDEX_TTL_SECONDS + 1)
    assert lens["reads"] == 2


def test_the_serve_path_runs_it_and_a_failure_never_breaks_the_board(monkeypatch):
    payload = {"ranked_all": [_prop()]}
    bp._refresh_live_columns_from_artifact(payload)
    assert payload["ranked_all"][0]["live_projection"] == 6.04

    def boom(_sport, **_k):
        raise RuntimeError("keyvalue down")
    monkeypatch.setattr(bp, "_lens_prop_index", boom)
    payload = {"ranked_all": [_prop()]}
    bp._refresh_live_columns_from_artifact(payload)  # must not raise
    assert "live_projection" not in payload["ranked_all"][0]
