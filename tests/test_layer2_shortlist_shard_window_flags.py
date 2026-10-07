"""The served shortlist says when its counters are an older build than its `written_at`.

Lane `layer2-shard-window-flags` (2026-10-07). With `combined_keeps_rows=False` the
writer lands the per-sport shards ~25-30 s before the index; a read in between gets
`written_at` relabelled to the NEW shard stamp while every counter is the PREVIOUS
build's. Measured on the fleet 10-07: web `LAYER2_SHARD_INDEX_STALE` at 18:51:57Z
(index 17:08:27Z, shards 18:51:36Z), and a watcher keyed on `written_at` read the 17:08
build's counters under the 18:51:36Z stamp. Runs the REAL merge, through the route.
"""
from __future__ import annotations

import pipeline.intelligence_state as state

_DATE = "2026-10-07"


def _serve(monkeypatch, shard_stamp):
    index = {
        "written_at": "2026-10-07T17:08:27Z",
        "rows": [],
        "shards": ["wnba"],
        "shard_row_total": 1,
        "rows_player_out_on_feed": 0,
    }
    shard = {
        "written_at": shard_stamp,
        "rows": [{"sport": "wnba", "event_id": "e1", "market": "player_points", "side": "over", "line": 16.5}],
        "positions": [0],
    }

    def _read(path):
        name = str(path).replace("\\", "/").rsplit("/", 1)[-1]
        if name == "layer2_shortlist_2026_10_07.json":
            return index
        if name == "layer2_shortlist_2026_10_07__wnba.json":
            return shard
        return None

    monkeypatch.setattr(state, "read_json_file", _read)
    from syndicate.app import app

    body = app.test_client().get(f"/api/board/layer2-shortlist?sport=all&date={_DATE}").get_json()
    assert body["shortlist_present"] is True
    return body


def test_a_read_between_the_shard_and_index_writes_is_flagged(monkeypatch):
    body = _serve(monkeypatch, "2026-10-07T18:51:36Z")
    assert body["written_at"] == "2026-10-07T18:51:36Z"
    assert body["shard_index_stale"] is True
    # The counters on this payload are dated by THIS, not by `written_at`.
    assert body["index_written_at"] == "2026-10-07T17:08:27Z"
    assert body["rows_from_shards"] is True
    assert body["shards_loaded"] == ["wnba"] and body["shards_missing"] == []


def test_off_is_not_on_a_consistent_build_is_not_flagged(monkeypatch):
    body = _serve(monkeypatch, "2026-10-07T17:08:27Z")
    assert body["shard_index_stale"] is False
    assert body["index_written_at"] == body["written_at"] == "2026-10-07T17:08:27Z"
