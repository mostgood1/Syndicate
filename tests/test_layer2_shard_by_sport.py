"""The board is one key per sport, and the merge restores its RANKING.

WHY, measured 2026-08-31. The 8MB keyvalue ceiling is PER KEY, so a single
combined key makes every sport compete for one budget:

    3 active sports   1,180 rows   5,806,147 bytes   69.2% of ceiling
    measured 4,920 bytes/row -- the 400/sport cap was sized on ~1.0 KB/row,
    understating it by 4.8x

so six sports computes to ~11.8MB and eight to ~15.7MB. That does not break the
board -- `_shed_rows_to_fit_keyvalue` drops the lowest-ranked rows and stamps it
-- it makes the CAP A LIE: at six sports roughly half is shed, so a configured
400 becomes ~200 and one sport's slate shrinks another's.

THE TWO PROPERTIES THAT MATTER, one test each:

1. **Order is preserved exactly.** Shards carry each row's GLOBAL index.
   Concatenating sport-by-sport would order the board "all of mlb, then all of
   soccer" -- populated, plausible, and wrong in the one way a RANKED board
   must never be wrong.
2. **No deploy order can empty the board.** Rows on the combined key WIN, and
   the writer keeps filling them until an env flag says otherwise. So a new
   reader against an old writer, and an old reader against a new writer, both
   still see rows.
"""
from __future__ import annotations

import json

import pytest

import pipeline.intelligence_state as st


@pytest.fixture
def store(monkeypatch, tmp_path):
    """An in-memory keyvalue stand-in, keyed by path like the real one."""
    kv: dict[str, dict] = {}
    monkeypatch.setattr(st, "reports_root", lambda: tmp_path)
    monkeypatch.setattr(st, "write_json_file", lambda p, v: kv.__setitem__(str(p), json.loads(json.dumps(v, default=str))))
    monkeypatch.setattr(st, "read_json_file", lambda p: kv.get(str(p)))
    return kv


def _rows():
    """A RANKED board, interleaved by sport on purpose."""
    return [
        {"sport": "mlb", "rank": 0}, {"sport": "soccer", "rank": 1},
        {"sport": "mlb", "rank": 2}, {"sport": "ncaaf", "rank": 3},
        {"sport": "soccer", "rank": 4}, {"sport": "mlb", "rank": 5},
    ]


def test_shards_are_written_one_per_sport(store, monkeypatch):
    monkeypatch.delenv("SYNDICATE_LAYER2_COMBINED_ROWS", raising=False)
    st.write_layer2_shortlist("2026-08-31", {"rows": _rows()})
    names = sorted(k.rsplit("__", 1)[-1] for k in store if "__" in k)
    assert names == ["mlb.json", "ncaaf.json", "soccer.json"]


def test_the_combined_key_still_carries_rows_by_default(store, monkeypatch):
    """THE DEPLOY-ORDER GUARD. Default must be a no-op for every existing
    reader -- shards land and are provable while nothing depends on them."""
    monkeypatch.delenv("SYNDICATE_LAYER2_COMBINED_ROWS", raising=False)
    st.write_layer2_shortlist("2026-08-31", {"rows": _rows()})
    got = st.read_layer2_shortlist("2026-08-31")
    assert [r["rank"] for r in got["rows"]] == [0, 1, 2, 3, 4, 5]
    assert not got.get("rows_from_shards"), "the merge must not run while rows are present"


def test_with_the_flag_off_the_merge_restores_exact_ranking(store, monkeypatch):
    """THE PROPERTY THAT MATTERS. Concatenation would give
    [0,2,5, 3, 1,4] -- mlb, then ncaaf, then soccer. It must give [0..5]."""
    monkeypatch.setenv("SYNDICATE_LAYER2_COMBINED_ROWS", "0")
    st.write_layer2_shortlist("2026-08-31", {"rows": _rows()})
    combined = st.read_json_file(st._layer2_shortlist_path("2026-08-31"))
    assert combined["rows"] == [], "the headroom unlock did not empty the combined key"
    got = st.read_layer2_shortlist("2026-08-31")
    assert got["rows_from_shards"] is True
    assert [r["rank"] for r in got["rows"]] == [0, 1, 2, 3, 4, 5]
    assert [r["sport"] for r in got["rows"]] == ["mlb", "soccer", "mlb", "ncaaf", "soccer", "mlb"]


def test_a_missing_shard_costs_only_its_own_rows(store, monkeypatch, capsys):
    """The rest of the board keeps its relative order, and the loss is NAMED --
    "this sport is quiet" and "this sport's key did not load" are different."""
    monkeypatch.setenv("SYNDICATE_LAYER2_COMBINED_ROWS", "0")
    st.write_layer2_shortlist("2026-08-31", {"rows": _rows()})
    del store[str(st._layer2_shortlist_shard_path("2026-08-31", "soccer"))]
    got = st.read_layer2_shortlist("2026-08-31")
    assert [r["rank"] for r in got["rows"]] == [0, 2, 3, 5]
    assert got["shards_missing"] == ["soccer"]
    assert "LAYER2_SHARD_MERGE" in capsys.readouterr().out


def test_a_shard_write_failure_degrades_to_todays_behaviour(store, monkeypatch):
    """A shard failure must never cost the COMBINED write -- that is the
    artifact everything reads. It degrades to exactly the pre-shard board."""
    monkeypatch.setenv("SYNDICATE_LAYER2_COMBINED_ROWS", "0")
    monkeypatch.setattr(st, "_shard_rows_by_sport", lambda rows: (_ for _ in ()).throw(RuntimeError("boom")))
    st.write_layer2_shortlist("2026-08-31", {"rows": _rows()})
    got = st.read_layer2_shortlist("2026-08-31")
    assert [r["rank"] for r in got["rows"]] == [0, 1, 2, 3, 4, 5], (
        "a shard failure emptied the board instead of falling back"
    )


def test_the_flag_rejects_unknown_values_permissively_toward_safety(monkeypatch):
    """Absent or unrecognised must mean KEEP the rows -- the safe side."""
    for off in ("0", "false", "no", "off"):
        monkeypatch.setenv("SYNDICATE_LAYER2_COMBINED_ROWS", off)
        assert st._layer2_combined_keeps_rows() is False
    for on in ("1", "true", "yes", "banana", ""):
        monkeypatch.setenv("SYNDICATE_LAYER2_COMBINED_ROWS", on)
        assert st._layer2_combined_keeps_rows() is True
