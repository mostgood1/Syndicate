"""The NBA grid's per-row file lookups resolve once per BUILD, and the grid is written in one write (todo #790,
lane nba-grid-per-build-lookups).

Measured on the fleet 2026-11-13: 135,090 of one NBA grid build's 137,279 stat-like calls were three lookups
asked once per priced row -- `season_phase_for_date` and `book_blend_weights` for the game-line and the prop
blend files -- and under refresh-worker's busy board-loop thread each such call is a GIL hand-off. These tests
pin: the scope's own semantics (once per key, private to its thread, dropped on exit or error, off switch);
each lookup answers inside a scope exactly what it answers outside one, resolving once; the env kill switch
still wins inside a scope; the real caller (`attach_nba_game_projections`) resolves once with the scope and
once per row without it (off != on), with identical projections; `build_book_grid_artifact` opens the scope;
and both grid writers write the bytes `json.dump` wrote.
"""
from __future__ import annotations

import copy
import json
import math
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest

from syndicate.features.shared import book_grid_artifact as bga
from syndicate.features.shared import build_lookup_scope as bls
from syndicate.features.shared import nba_game_projections as ngp
from syndicate.features.shared import nba_prop_calibration as cal
from tests.test_basketball_market_board_book_blend import GW, W
from tests.test_nba_layer2_projections import D, _game_row, nba_root  # noqa: F401  (fixture reuse)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv(bls.FLAG, raising=False)
    monkeypatch.delenv(cal.GAME_BLEND_FLAG, raising=False)
    monkeypatch.delenv(cal.BOOK_BLEND_FLAG, raising=False)
    ngp._SEASON_PHASE_CACHE.clear()
    yield
    ngp._SEASON_PHASE_CACHE.clear()


def _counter(monkeypatch, module, name):
    count = {"n": 0}
    real = getattr(module, name)

    def counting(*args, **kwargs):
        count["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(module, name, counting)
    return count


def _scoreboard(root: Path, date: str, season_type: int) -> None:
    cache = root / "data" / "processed" / "_espn_cache" / "nba"
    cache.mkdir(parents=True, exist_ok=True)
    (cache / f"scoreboard_{date.replace('-', '')}.json").write_text(
        json.dumps({"events": [{"season": {"type": season_type}}]}), encoding="utf-8")


def _blend_files(game=GW, prop=W) -> Path:
    from syndicate.features.nba.sources import artifact_processed_root

    root = artifact_processed_root()
    root.mkdir(parents=True, exist_ok=True)
    if game is not None:
        (root / cal.GAME_BLEND_FILE).write_text(json.dumps(game), encoding="utf-8")
    if prop is not None:
        (root / cal.BOOK_BLEND_FILE).write_text(json.dumps(prop), encoding="utf-8")
    return root


# --------------------------------------------------------------------------------------------------------------
# The scope itself
# --------------------------------------------------------------------------------------------------------------


def test_outside_a_scope_every_ask_computes():
    calls = []
    for _ in range(3):
        assert bls.scoped_lookup("ns", "k", lambda: calls.append(1) or "v") == "v"
    assert len(calls) == 3
    assert not bls.lookup_scope_active()


def test_inside_a_scope_each_key_computes_once():
    calls = []

    def compute(tag):
        calls.append(tag)
        return tag.upper()

    with bls.lookup_scope():
        assert bls.lookup_scope_active()
        answers = [bls.scoped_lookup("ns", key, lambda key=key: compute(key)) for key in ["a", "b", "a", "b", "a"]]
        assert bls.scoped_lookup("other", "a", lambda: compute("other-a")) == "OTHER-A"  # namespaces are separate
    assert answers == ["A", "B", "A", "B", "A"]
    assert calls == ["a", "b", "other-a"]


def test_a_none_answer_is_remembered_too():
    calls = []
    with bls.lookup_scope():
        for _ in range(4):
            assert bls.scoped_lookup("ns", "k", lambda: calls.append(1)) is None
    assert len(calls) == 1


def test_the_memo_is_dropped_on_exit_and_on_error():
    calls = []
    with bls.lookup_scope():
        bls.scoped_lookup("ns", "k", lambda: calls.append(1))
    assert not bls.lookup_scope_active()
    with pytest.raises(RuntimeError):
        with bls.lookup_scope():
            bls.scoped_lookup("ns", "k", lambda: calls.append(2))
            raise RuntimeError("build failed")
    assert not bls.lookup_scope_active()
    bls.scoped_lookup("ns", "k", lambda: calls.append(3))
    assert calls == [1, 2, 3]  # each scope computed afresh; outside, it computes


def test_a_nested_scope_shares_the_outer_memo():
    calls = []
    with bls.lookup_scope():
        bls.scoped_lookup("ns", "k", lambda: calls.append("outer"))
        with bls.lookup_scope():
            bls.scoped_lookup("ns", "k", lambda: calls.append("inner"))
        assert bls.lookup_scope_active()  # leaving the inner scope kept the outer one
        bls.scoped_lookup("ns", "k", lambda: calls.append("after"))
    assert calls == ["outer"]


def test_the_off_switch_makes_the_scope_a_no_op(monkeypatch):
    monkeypatch.setenv(bls.FLAG, "off")
    calls = []
    with bls.lookup_scope():
        assert not bls.lookup_scope_active()
        for _ in range(3):
            bls.scoped_lookup("ns", "k", lambda: calls.append(1))
    assert len(calls) == 3


def test_another_thread_never_sees_the_scope():
    """The board loop runs the same lookups on its own thread: it must not read a grid build's memo."""
    seen = {}
    calls = []
    with bls.lookup_scope():
        bls.scoped_lookup("ns", "k", lambda: calls.append("main"))

        def other():
            seen["active"] = bls.lookup_scope_active()
            bls.scoped_lookup("ns", "k", lambda: calls.append("thread"))
            bls.scoped_lookup("ns", "k", lambda: calls.append("thread"))

        worker = threading.Thread(target=other)
        worker.start()
        worker.join()
    assert seen["active"] is False
    assert calls == ["main", "thread", "thread"]


# --------------------------------------------------------------------------------------------------------------
# The three lookups
# --------------------------------------------------------------------------------------------------------------


def test_book_blend_weights_resolves_once_per_file_inside_a_scope(nba_root, monkeypatch):
    _blend_files()
    resolves = _counter(monkeypatch, cal, "_resolve_book_blend")
    outside_game = cal.book_blend_weights(filename=cal.GAME_BLEND_FILE, flag=cal.GAME_BLEND_FLAG)
    outside_prop = cal.book_blend_weights()
    assert outside_game[1] == "ok" and outside_prop[1] == "ok"
    assert resolves["n"] == 2
    with bls.lookup_scope():
        for _ in range(50):
            assert cal.book_blend_weights(filename=cal.GAME_BLEND_FILE, flag=cal.GAME_BLEND_FLAG) == outside_game
            assert cal.book_blend_weights() == outside_prop
    assert resolves["n"] == 2 + 2  # one per file, not one per call


def test_the_env_kill_switch_still_wins_inside_a_scope(nba_root):
    _blend_files()
    with bls.lookup_scope():
        assert cal.book_blend_weights(env={})[1] == "ok"
        assert cal.book_blend_weights(env={cal.BOOK_BLEND_FLAG: "off"}) == (None, f"{cal.BOOK_BLEND_FLAG} off")
        assert cal.book_blend_weights(env={})[1] == "ok"


def test_an_explicit_processed_root_is_its_own_entry(nba_root, tmp_path):
    other = tmp_path / "other_processed"
    other.mkdir()
    (other / cal.BOOK_BLEND_FILE).write_text(json.dumps(dict(W, w={"pts": 0.7})), encoding="utf-8")
    _blend_files()
    with bls.lookup_scope():
        default_root = cal.book_blend_weights()
        explicit = cal.book_blend_weights(other)
    assert default_root[0] == {"pts": 0.0, "reb": 0.1}
    assert explicit[0] == {"pts": 0.7}


def test_a_file_written_mid_build_is_seen_by_the_next_build(nba_root):
    """Freshness is per build: inside one build every row sees one answer; the next build looks again."""
    with bls.lookup_scope():
        assert cal.book_blend_weights() == (None, "book-blend file absent")
        _blend_files(game=None)
        assert cal.book_blend_weights() == (None, "book-blend file absent")
    with bls.lookup_scope():
        assert cal.book_blend_weights()[1] == "ok"


def test_season_phase_finds_the_file_once_per_date_inside_a_scope(nba_root, monkeypatch):
    _scoreboard(nba_root, D, 1)
    _scoreboard(nba_root, "2026-10-05", 2)
    finds = _counter(monkeypatch, ngp, "nba_processed_file")
    assert ngp.season_phase_for_date(D) == "preseason"
    assert ngp.season_phase_for_date(D) == "preseason"
    assert finds["n"] == 2  # outside a scope: every call, as before
    with bls.lookup_scope():
        for _ in range(100):
            assert ngp.season_phase_for_date(D) == "preseason"
            assert ngp.season_phase_for_date(f"{D}T23:10:00Z") == "preseason"  # same date, same entry
            assert ngp.season_phase_for_date("2026-10-05") == "regular"
        assert ngp.season_phase_for_date("2026-01-01") is None  # no scoreboard
        assert ngp.season_phase_for_date(None) is None
    assert finds["n"] == 2 + 3


def test_through_the_game_projection_attach_off_differs_from_on(nba_root, monkeypatch):
    """The real caller, many priced rows: one resolve of each lookup with the scope, one per row without it,
    and identical projections either way."""
    _blend_files(game=dict(GW, phase={"preseason": {"default": 0.0}}))
    _scoreboard(nba_root, D, 1)
    finds = _counter(monkeypatch, ngp, "nba_processed_file")
    resolves = _counter(monkeypatch, cal, "_resolve_book_blend")
    template = [_game_row("totals_alt", line=229.5) for _ in range(40)]
    index = ngp.load_nba_game_projections(D)
    base_finds = finds["n"]

    rows_on = copy.deepcopy(template)
    with bls.lookup_scope():
        ngp.attach_nba_game_projections(rows_on, index)
    on = (finds["n"] - base_finds, resolves["n"])

    monkeypatch.setenv(bls.FLAG, "off")
    rows_off = copy.deepcopy(template)
    with bls.lookup_scope():
        ngp.attach_nba_game_projections(rows_off, index)
    off = (finds["n"] - base_finds - on[0], resolves["n"] - on[1])

    assert all(r["projection"]["season_phase"] == "preseason" for r in rows_on)
    assert on == (1, 1)
    assert off == (40, 40)
    assert [r["projection"] for r in rows_on] == [r["projection"] for r in rows_off]


def test_build_book_grid_artifact_opens_the_scope(monkeypatch):
    seen = []

    def fake_build(sport, date_str, *, max_rows):
        seen.append((sport, date_str, max_rows, bls.lookup_scope_active()))
        return {"rows": []}

    monkeypatch.setattr(bga, "_build_book_grid_artifact", fake_build)
    assert bga.build_book_grid_artifact("nba", D, max_rows=7) == {"rows": []}
    assert not bls.lookup_scope_active()
    monkeypatch.setenv(bls.FLAG, "off")
    bga.build_book_grid_artifact("nba", D)
    assert seen == [("nba", D, 7, True), ("nba", D, bga.BOOK_GRID_ARTIFACT_MAX_ROWS, False)]


# --------------------------------------------------------------------------------------------------------------
# One write, same bytes
# --------------------------------------------------------------------------------------------------------------

PAYLOAD = {
    "generated_at": datetime(2026, 11, 13, 21, 30, tzinfo=timezone.utc),  # default=str
    "player": "Nikola Jokić",
    "note": "line — moved \U0001F3C0 \"quoted\" back\\slash\nnewline\ttab",
    "nan": math.nan,
    "inf": math.inf,
    "ninf": -math.inf,
    "floats": [0.1, 1e-07, 1e22, -0.0, 2.5],
    "ints": [0, -1, 2**63, True, False, None],
    "tuple": (1, "two", 3.0),
    "path": Path("a") / "b",
    1: "int key",
    2.5: "float key",
    None: "none key",
    False: "bool key",
    "rows": [{"cells": {"dk": {"over": {"price": -110, "line": math.nan}}}} for _ in range(3)],
}


def _json_dump_bytes(tmp_path: Path, payload) -> bytes:
    ref = tmp_path / "reference.json"
    with ref.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, default=str)
    return ref.read_bytes()


def test_one_write_is_byte_identical_to_json_dump(tmp_path):
    out = tmp_path / "once.json"
    bga._write_json_once(out, PAYLOAD)
    assert out.read_bytes() == _json_dump_bytes(tmp_path, PAYLOAD)


def test_both_grid_writers_write_once_and_the_same_bytes(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("SYNDICATE_INPLAY_OVERLAY", "off")
    writes = _counter(monkeypatch, bga, "_write_json_once")
    grid_path = bga.write_book_grid_artifact("nba", D, dict(PAYLOAD))
    overlay_path = bga.write_book_grid_inplay_overlay("nba", D, dict(PAYLOAD))
    expected = _json_dump_bytes(tmp_path, dict(PAYLOAD))
    assert writes["n"] == 2
    assert grid_path.read_bytes() == expected
    assert overlay_path.read_bytes() == expected
    assert not list(grid_path.parent.glob("*.tmp"))


def test_a_payload_that_cannot_be_encoded_leaves_no_partial_file(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("SYNDICATE_INPLAY_OVERLAY", "off")
    circular: dict = {}
    circular["self"] = circular
    with pytest.raises(ValueError):
        bga.write_book_grid_artifact("nba", D, circular)
    grid_dir = bga.book_grid_artifact_path("nba", D).parent
    assert not grid_dir.exists() or not list(grid_dir.iterdir())
