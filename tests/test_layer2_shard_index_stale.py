"""The shard set can be NEWER than the combined key that indexes it.

Reproduces the 2026-08-31 production incident: `_write_layer2_shards` runs before
`write_json_file(combined)` with no rollback, so a refused combined write leaves
the shards advanced and `shard_row_total` frozen. The merge used to size its slot
array from that frozen total and DISCARD every row above it -- 2,917 rows and all
of NCAAF, on a board that reported itself healthy.

The rule these lock in: a refused write leaves the board STALE, never WRONG.
"""
from __future__ import annotations

import pipeline.intelligence_state as istate


def _row(sport: str, n: int) -> dict:
    return {"sport": sport, "event_id": f"{sport}-{n}", "market": "h2h", "side": "home", "line": str(n)}


def _install_shards(monkeypatch, shards: dict[str, dict]) -> None:
    """Serve shard payloads by sport, keyed off the path the merge asks for."""
    def fake_path(selected_date: str, sport: str):
        return f"/shard/{selected_date}/{sport}"

    def fake_read(path):
        sport = str(path).rsplit("/", 1)[-1]
        return shards.get(sport)

    monkeypatch.setattr(istate, "_layer2_shortlist_shard_path", fake_path)
    monkeypatch.setattr(istate, "read_json_file", fake_read)


def _shard(sport, rows, positions, written_at):
    return {"sport": sport, "rows": rows, "positions": positions, "written_at": written_at}


def test_stale_index_no_longer_discards_the_rows_above_it(monkeypatch, capsys):
    """THE INCIDENT. Index frozen at 3; shards hold 6 rows across 3 sports.

    Under the old code `total` was 3, so positions 3/4/5 failed `position < total`
    and were dropped -- and because the board is ranked globally, the sport whose
    rows all sat high (here ncaaf) vanished completely.
    """
    _install_shards(monkeypatch, {
        "mlb": _shard("mlb", [_row("mlb", 0), _row("mlb", 1)], [0, 1], "T1"),
        "soccer": _shard("soccer", [_row("soccer", 2), _row("soccer", 3)], [2, 3], "T1"),
        "ncaaf": _shard("ncaaf", [_row("ncaaf", 4), _row("ncaaf", 5)], [4, 5], "T1"),
    })
    payload = {"shard_row_total": 3, "written_at": "T0"}  # <- the frozen index

    out = istate._merge_layer2_shards("2026-08-31", payload, ["mlb", "soccer", "ncaaf"])

    assert len(out["rows"]) == 6, "rows above the stale total must NOT be discarded"
    assert {r["sport"] for r in out["rows"]} == {"mlb", "soccer", "ncaaf"}, "no sport may vanish"
    assert [r["event_id"] for r in out["rows"]] == [
        "mlb-0", "mlb-1", "soccer-2", "soccer-3", "ncaaf-4", "ncaaf-5",
    ], "global ranking order must survive the merge"
    assert out["shard_index_stale"] is True
    assert "LAYER2_SHARD_INDEX_STALE" in capsys.readouterr().out


def test_the_served_written_at_comes_from_the_shards_not_the_stale_index(monkeypatch):
    """The corrupted board reported 18:02:05Z while serving 18:25 rows.

    That is what made it unfalsifiable -- every post-deploy check on this board
    keys on `written_at`, so a watcher polling for a change saw none.
    """
    _install_shards(monkeypatch, {
        "mlb": _shard("mlb", [_row("mlb", 0), _row("mlb", 1)], [0, 1], "2026-08-31T18:25:44Z"),
    })
    payload = {"shard_row_total": 1, "written_at": "2026-08-31T18:02:05Z"}

    out = istate._merge_layer2_shards("2026-08-31", payload, ["mlb"])

    assert out["written_at"] == "2026-08-31T18:25:44Z", "date the rows by the shards they came from"
    assert out["index_written_at"] == "2026-08-31T18:02:05Z", "the stale index stamp stays readable"


def test_a_consistent_set_is_completely_unchanged(monkeypatch, capsys):
    """The fix must be inert when the index and shards agree -- which is always,
    except after a refused write. No new log line, no stale flag."""
    _install_shards(monkeypatch, {
        "mlb": _shard("mlb", [_row("mlb", 0), _row("mlb", 1)], [0, 1], "T1"),
        "soccer": _shard("soccer", [_row("soccer", 2)], [2], "T1"),
    })
    payload = {"shard_row_total": 3, "written_at": "T1"}

    out = istate._merge_layer2_shards("2026-08-31", payload, ["mlb", "soccer"])

    assert len(out["rows"]) == 3
    assert out["shard_index_stale"] is False
    assert "index_written_at" not in out, "an agreeing set must not be re-dated"
    printed = capsys.readouterr().out
    assert "LAYER2_SHARD_INDEX_STALE" not in printed
    assert "LAYER2_SHARD_MERGE" not in printed, "a clean merge stays silent"


def test_a_missing_shard_still_leaves_its_hole(monkeypatch):
    """`index_total` must WIN when it is larger. Shrinking the board to the rows
    that happen to have loaded would hide a missing shard -- the same silent
    truncation, in the other direction."""
    _install_shards(monkeypatch, {
        "mlb": _shard("mlb", [_row("mlb", 0)], [0], "T1"),
        # soccer's key is absent
    })
    payload = {"shard_row_total": 9, "written_at": "T1"}

    out = istate._merge_layer2_shards("2026-08-31", payload, ["mlb", "soccer"])

    assert out["shards_missing"] == ["soccer"]
    assert out["shard_index_stale"] is False, "a missing shard is not a stale index"
    assert len(out["rows"]) == 1


def test_a_bool_position_cannot_place_a_row(monkeypatch):
    """bool is an int in Python, so `True` would silently place a row at index 1
    and displace the real one. It must count as unplaceable instead."""
    _install_shards(monkeypatch, {
        "mlb": _shard("mlb", [_row("mlb", 0), _row("mlb", 1)], [0, True], "T1"),
    })
    payload = {"shard_row_total": 2, "written_at": "T1"}

    out = istate._merge_layer2_shards("2026-08-31", payload, ["mlb"])

    assert [r["event_id"] for r in out["rows"]] == ["mlb-0"], "True must not place a row at 1"


def test_stale_stamp_alone_is_enough_to_flag_it(monkeypatch, capsys):
    """A rebuild that happens to produce the SAME row count still leaves the
    index behind. Row count is not the discriminator; the stamp is."""
    _install_shards(monkeypatch, {
        "mlb": _shard("mlb", [_row("mlb", 0), _row("mlb", 1)], [0, 1], "T2"),
    })
    payload = {"shard_row_total": 2, "written_at": "T1"}

    out = istate._merge_layer2_shards("2026-08-31", payload, ["mlb"])

    assert out["shard_index_stale"] is True, "same total, different build -- still stale"
    assert "LAYER2_SHARD_INDEX_STALE" in capsys.readouterr().out
