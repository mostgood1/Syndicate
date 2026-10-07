"""A Layer 2 board read never mixes builds: shards are build-scoped, the index flips last.

Lane `layer2-shard-generations` (2026-10-07). Shards used to be overwritten IN PLACE, one
sport at a time, ~25-30 s before the index. Every read in that window merged two builds by
position and served the previous build's counters under the new `written_at`. Measured on
the fleet 10-07: web `LAYER2_SHARD_MERGE rows=3934/5359` at 18:51:49Z, soccer and wnba
still on the 17:08 build. a2a7621b only FLAGGED it (`shard_index_stale`, caught true at
21:30:56Z). These run the real writer and the real reader over an in-memory store.
"""
from __future__ import annotations

import pytest

import pipeline.intelligence_state as istate
from syndicate.features.shared import refresh_state_store

_DATE = "2026-10-07"


class _Store:
    def __init__(self):
        self.data: dict[str, dict] = {}
        self.on_write = None

    def read(self, path):
        value = self.data.get(str(path))
        return dict(value) if isinstance(value, dict) else None

    def write(self, path, payload):
        self.data[str(path)] = dict(payload)
        if self.on_write is not None:
            self.on_write(str(path))

    def delete(self, path):
        self.data.pop(str(path), None)

    def shard_keys(self):
        return sorted(k for k in self.data if "__" in k.replace("\\", "/").rsplit("/", 1)[-1])


@pytest.fixture
def store(monkeypatch):
    s = _Store()
    monkeypatch.setattr(istate, "read_json_file", s.read)
    monkeypatch.setattr(istate, "write_json_file", s.write)
    monkeypatch.setattr(refresh_state_store, "delete_text_file", s.delete)
    # The fleet's configuration: rows and cards live ONLY in the shards.
    monkeypatch.setenv("SYNDICATE_LAYER2_COMBINED_ROWS", "0")
    monkeypatch.setenv("SYNDICATE_LAYER2_CARDS_INLINE", "0")
    monkeypatch.delenv("SYNDICATE_LAYER2_SHARD_GENERATIONS", raising=False)
    return s


def _build(tag, sports=("mlb", "soccer", "wnba"), per_sport=2, out_on_feed=0):
    rows, cards = [], []
    for n in range(per_sport):
        for sport in sports:
            rows.append({"sport": sport, "event_id": f"{tag}-{sport}-{n}", "market": "h2h", "side": "home", "line": str(n)})
            cards.append({"sport": sport, "pick_id": f"{tag}-{sport}-{n}"})
    return {"rows": rows, "cards": cards, "rows_player_out_on_feed": out_on_feed, "build_tag": tag}


def _tags(payload):
    return {str(r["event_id"]).split("-", 1)[0] for r in payload.get("rows") or []}


def test_a_read_during_the_write_sees_one_whole_build(store):
    istate.write_layer2_shortlist(_DATE, _build("old", out_on_feed=0))
    seen = []

    def read_mid_write(path):
        seen.append(istate.read_layer2_shortlist(_DATE))

    store.on_write = read_mid_write
    istate.write_layer2_shortlist(_DATE, _build("new", out_on_feed=4))
    store.on_write = None

    assert len(seen) >= 6, "the probe must actually have read between the shard writes"
    index_flip = next(i for i, p in enumerate(seen) if _tags(p) == {"new"})
    for payload in seen[:index_flip]:
        # Every read before the index flips is the OLD build -- rows, cards AND counters.
        assert _tags(payload) == {"old"}
        assert payload["rows_player_out_on_feed"] == 0
        assert {c["pick_id"].split("-", 1)[0] for c in payload.get("cards") or []} == {"old"}
        assert not payload.get("shard_index_stale")
    assert index_flip >= 6, "the old build must be served through every shard write"
    for payload in seen[index_flip:]:
        assert _tags(payload) == {"new"} and payload["rows_player_out_on_feed"] == 4
    final = istate.read_layer2_shortlist(_DATE)
    assert len(final["rows"]) == 6 and len(final["cards"]) == 6
    assert final["shards_missing"] == []


def test_the_ranking_survives_the_build_scoped_merge(store):
    build = _build("only")
    istate.write_layer2_shortlist(_DATE, build)
    got = istate.read_layer2_shortlist(_DATE)
    assert [r["event_id"] for r in got["rows"]] == [r["event_id"] for r in build["rows"]]


def test_only_the_current_and_previous_generations_are_kept(store):
    for tag in ("b1", "b2", "b3", "b4"):
        istate.write_layer2_shortlist(_DATE, _build(tag))
    index = store.read(istate._layer2_shortlist_path(_DATE))
    gens = {k.rsplit("__g", 1)[-1].split(".")[0] for k in store.shard_keys() if "__g" in k}
    assert gens == {index["shard_generation"], index["shard_generation_previous"]}
    # 3 sports x (rows + cards) x 2 generations
    assert len(store.shard_keys()) == 12


def test_the_legacy_in_place_keys_are_cleaned_once_no_reader_can_need_them(store, monkeypatch):
    monkeypatch.setenv("SYNDICATE_LAYER2_SHARD_GENERATIONS", "0")
    istate.write_layer2_shortlist(_DATE, _build("legacy"))
    legacy = list(store.shard_keys())
    assert legacy and not any("__g" in k for k in legacy)
    monkeypatch.delenv("SYNDICATE_LAYER2_SHARD_GENERATIONS")
    istate.write_layer2_shortlist(_DATE, _build("g1"))
    # First generation build: the legacy keys STAY (an old-code reader may still use them).
    assert all(k in store.data for k in legacy)
    istate.write_layer2_shortlist(_DATE, _build("g2"))
    assert not any(k in store.data for k in legacy)


def test_off_is_not_on_the_kill_switch_writes_in_place_keys(store, monkeypatch):
    """Reachability: with the switch off, the writer is exactly the old in-place writer
    -- so the guarantees above are the generation path's doing."""
    monkeypatch.setenv("SYNDICATE_LAYER2_SHARD_GENERATIONS", "0")
    istate.write_layer2_shortlist(_DATE, _build("a"))
    index = store.read(istate._layer2_shortlist_path(_DATE))
    assert "shard_generation" not in index
    assert not any("__g" in k for k in store.shard_keys())
    assert _tags(istate.read_layer2_shortlist(_DATE)) == {"a"}


def test_an_index_from_before_this_change_still_reads_the_in_place_keys(store, monkeypatch):
    monkeypatch.setenv("SYNDICATE_LAYER2_SHARD_GENERATIONS", "0")
    istate.write_layer2_shortlist(_DATE, _build("pre"))
    monkeypatch.delenv("SYNDICATE_LAYER2_SHARD_GENERATIONS")
    got = istate.read_layer2_shortlist(_DATE)
    assert _tags(got) == {"pre"} and len(got["cards"]) == 6
