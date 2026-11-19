"""A board one web worker built, adopted by the next (lane `board-read-cold-share`, rail monitor I-28).

Fleet web runs 2 gunicorn workers, and on 11-18 5-11 PM CST the memory guard recycled them 82
times. 69 of the 75 cold `board_read`s on the Layer 2 page's query (92%) were a freshly booted
worker building a board the other worker already held. These tests pin the switch:
`SYNDICATE_COMBINED_BOARD_SHARED_COPY` absent = every worker builds its own (the old
behaviour); on = a worker adopts another's copy when it is fresh by its OWN cache's rules.

"Another worker" is simulated by clearing this process's cache: the shared copy is then the
only thing that can save the build, which is exactly a booted worker's position.
"""
from __future__ import annotations

import json
import os
import time

import pytest

from syndicate.features.shared import book_grid_artifact as bga
from syndicate.features.shared import combined_board_shared_copy as shared

DATE = "2026-11-19"
KEY = ((DATE,), "all", None)


@pytest.fixture()
def board(tmp_path, monkeypatch):
    from pipeline import intelligence_state as st

    monkeypatch.setattr(bga, "data_root", lambda: tmp_path / "data")
    monkeypatch.setattr(bga, "_publish_inplay_overlay", lambda path: True)
    bga._INPLAY_READ_CACHE.clear()
    monkeypatch.setenv("SYNDICATE_INTELLIGENCE_COMBINED_BOARD_CACHE_SECONDS", "180")
    monkeypatch.setenv("SYNDICATE_INPLAY_OVERLAY_CACHE_MIN_AGE_SECONDS", "22")
    monkeypatch.delenv("SYNDICATE_INPLAY_OVERLAY_CACHE_EXPIRY", raising=False)
    monkeypatch.delenv("SYNDICATE_INPLAY_OVERLAY", raising=False)
    monkeypatch.delenv(shared.ENV_SWITCH, raising=False)
    share_dir = tmp_path / "shared"
    monkeypatch.setenv(shared.ENV_DIR, str(share_dir))
    shared._reset_for_tests()
    builds: list[str] = []
    monkeypatch.setattr(st, "read_layer2_shortlist", lambda d: None)
    monkeypatch.setattr(st, "_read_single_date_response_for_combining", lambda d: builds.append(d))
    monkeypatch.setattr(st, "board_l2a_fallback_enabled", lambda: True)

    def new_worker():
        """A booted worker: nothing in its own cache."""
        st._COMBINED_INTELLIGENCE_RESPONSE_CACHE.clear()
        st._COMBINED_OVERLAY_MTIME_BY_KEY.clear()

    new_worker()

    class Board:
        pass

    b = Board()
    b.st, b.builds, b.dir, b.new_worker = st, builds, share_dir, new_worker

    def read(**kw):
        payload = st.read_combined_intelligence_response(dates=[DATE], **kw)
        return len(builds), payload

    def land_overlay(mtime):
        bga.write_book_grid_inplay_overlay("ncaaf", DATE, {"written_at": "2026-11-19T23:00:00Z", "cards": []})
        os.utime(bga.book_grid_inplay_artifact_path("ncaaf", DATE), (mtime, mtime))

    def board_path():
        return shared._paths(str(share_dir), KEY)

    def age_copy(seconds):
        """Make the shared copy `seconds` older, the way time would."""
        path, _ = board_path()
        with open(path, "rb") as handle:
            header = json.loads(handle.readline())
            rest = handle.read()
        header["built_at"] -= seconds
        with open(path, "wb") as handle:
            handle.write(json.dumps(header).encode() + b"\n" + rest)

    def foreign_lease(*, alive=True, age=0.0, pid=4242424):
        _, lease_path = board_path()
        share_dir.mkdir(parents=True, exist_ok=True)
        with open(lease_path, "w", encoding="utf-8") as handle:
            json.dump({"pid": pid, "started_at": time.time() - age, "key": repr(KEY)}, handle)
        monkeypatch.setattr(shared, "_pid_alive", lambda p: alive if p == pid else True)
        return lease_path

    b.read, b.land_overlay, b.board_path, b.age_copy, b.foreign_lease = read, land_overlay, board_path, age_copy, foreign_lease
    yield b
    new_worker()
    shared._reset_for_tests()


def _on(monkeypatch):
    monkeypatch.setenv(shared.ENV_SWITCH, "1")


# --- reachability: off != on ---------------------------------------------------------------


@pytest.mark.parametrize("switch, builds_after_recycle", [(None, 2), ("off", 2), ("1", 1)])
def test_off_every_worker_builds_its_own_on_a_new_worker_adopts(board, monkeypatch, capsys, switch, builds_after_recycle):
    if switch is None:
        monkeypatch.delenv(shared.ENV_SWITCH, raising=False)
    else:
        monkeypatch.setenv(shared.ENV_SWITCH, switch)
    first, _ = board.read()
    assert first == 1
    board.new_worker()
    second, _ = board.read()
    assert second == builds_after_recycle
    out = capsys.readouterr().out
    if builds_after_recycle == 1:
        assert "COMBINED_BOARD_SHARED_ADOPTED" in out and "own=empty" in out
    else:
        assert "COMBINED_BOARD_SHARED_" not in out


def test_absent_switch_never_touches_the_filesystem(board):
    board.read()
    board.new_worker()
    board.read()
    assert not board.dir.exists(), "the off path must not even create the directory"


def test_the_adopted_board_is_the_built_board_under_the_builders_stamp(board, monkeypatch):
    _on(monkeypatch)
    _, built = board.read()
    stamp = board.st._COMBINED_INTELLIGENCE_RESPONSE_CACHE[KEY][0]
    board.new_worker()
    builds, adopted = board.read()
    assert builds == 1
    assert adopted == built
    # The TTL counts from the build, not from the load.
    assert board.st._COMBINED_INTELLIGENCE_RESPONSE_CACHE[KEY][0] == stamp


# --- the same freshness rules as the worker's own cache ------------------------------------


def test_a_copy_past_the_ttl_is_not_adopted(board, monkeypatch):
    _on(monkeypatch)
    board.read()
    board.age_copy(181)
    board.new_worker()
    assert board.read()[0] == 2


def test_a_newer_overlay_refuses_a_copy_past_the_overlay_floor(board, monkeypatch):
    _on(monkeypatch)
    board.land_overlay(time.time() - 100)
    board.read()
    board.land_overlay(time.time())
    board.age_copy(30)  # past the 22 s floor
    board.new_worker()
    assert board.read()[0] == 2


def test_a_newer_overlay_inside_the_floor_still_adopts(board, monkeypatch):
    _on(monkeypatch)
    board.land_overlay(time.time() - 100)
    board.read()
    board.land_overlay(time.time())
    board.age_copy(5)  # inside the 22 s floor: the builder's own cache would still serve it
    board.new_worker()
    assert board.read()[0] == 1


def test_an_expired_own_entry_adopts_a_newer_copy_not_an_equal_one(board, monkeypatch):
    _on(monkeypatch)
    board.read()
    # Our own entry is 200 s old and so is the copy (we published it): nothing newer to adopt.
    built_at, payload = board.st._COMBINED_INTELLIGENCE_RESPONSE_CACHE[KEY]
    board.st._COMBINED_INTELLIGENCE_RESPONSE_CACHE[KEY] = (built_at - 200, payload)
    board.age_copy(200)
    assert board.read()[0] == 2
    # Another worker's newer build is adopted by a worker whose own entry expired.
    built_at, payload = board.st._COMBINED_INTELLIGENCE_RESPONSE_CACHE[KEY]
    board.st._COMBINED_INTELLIGENCE_RESPONSE_CACHE[KEY] = (built_at - 200, payload)
    assert board.read()[0] == 2


# --- across workers: one rebuild, and the newest copy while it runs ------------------------


def test_while_another_worker_rebuilds_the_newest_copy_is_served(board, monkeypatch, capsys):
    _on(monkeypatch)
    board.read()
    board.age_copy(200)  # past the TTL, inside TTL x 10
    board.foreign_lease(alive=True)
    board.new_worker()
    assert board.read()[0] == 1
    assert "COMBINED_BOARD_SHARED_SERVED_STALE" in capsys.readouterr().out


def test_another_workers_lease_with_no_young_copy_still_builds(board, monkeypatch):
    _on(monkeypatch)
    board.foreign_lease(alive=True)
    assert board.read()[0] == 1  # nothing to serve: build, as before


def test_a_copy_older_than_ten_ttls_is_never_served_stale(board, monkeypatch):
    _on(monkeypatch)
    board.read()
    board.age_copy(1801)
    board.foreign_lease(alive=True)
    board.new_worker()
    assert board.read()[0] == 2


@pytest.mark.parametrize("alive, age", [(False, 0.0), (True, shared.LEASE_SECONDS + 1)])
def test_a_dead_or_expired_lease_is_taken_over_and_released(board, monkeypatch, alive, age):
    _on(monkeypatch)
    lease_path = board.foreign_lease(alive=alive, age=age)
    assert board.read()[0] == 1
    assert not os.path.exists(lease_path), "the builder releases the lease after publishing"
    assert os.path.exists(board.board_path()[0])


def test_a_lease_this_process_left_behind_is_taken_over(board, monkeypatch):
    _on(monkeypatch)
    board.read()
    board.age_copy(200)
    board.foreign_lease(pid=os.getpid())  # e.g. this worker's build raised before publishing
    board.new_worker()
    assert board.read()[0] == 2


def test_the_warmer_adopts_another_workers_rebuild_instead_of_building(board, monkeypatch, capsys):
    st = board.st
    _on(monkeypatch)
    st._COMBINED_BOARD_ACTIVE_KEYS.clear()
    monkeypatch.setattr(st, "_ensure_combined_board_overlay_warmer", lambda: None)
    board.land_overlay(time.time() - 100)
    _, payload = board.read()
    assert KEY in st._COMBINED_BOARD_ACTIVE_KEYS
    built_at, own = st._COMBINED_INTELLIGENCE_RESPONSE_CACHE[KEY]
    st._COMBINED_INTELLIGENCE_RESPONSE_CACHE[KEY] = (built_at - 60, own)
    newer = time.time()
    board.land_overlay(newer - 3)
    # The other worker already rebuilt against the new overlay.
    other = dict(payload, built_by="other")
    assert shared.publish(KEY, built_at=newer, overlay_mtime=newer - 3, payload=other, rows=0, lease=None)
    capsys.readouterr()
    st._warm_combined_board_overlays_once()
    assert len(board.builds) == 1
    assert st._COMBINED_INTELLIGENCE_RESPONSE_CACHE[KEY][1].get("built_by") == "other"
    assert "COMBINED_BOARD_SHARED_ADOPTED" in capsys.readouterr().out


# --- a bad copy is a miss, never an error ---------------------------------------------------


def test_a_corrupt_copy_is_a_miss(board, monkeypatch):
    _on(monkeypatch)
    board.read()
    path, _ = board.board_path()
    with open(path, "r+b") as handle:
        handle.seek(-20, os.SEEK_END)
        handle.write(b"\x00" * 20)
    board.new_worker()
    assert board.read()[0] == 2


def test_a_copy_of_another_key_is_never_adopted(board, monkeypatch):
    _on(monkeypatch)
    board.read()
    path, _ = board.board_path()
    with open(path, "rb") as handle:
        header = json.loads(handle.readline())
        rest = handle.read()
    header["key"] = repr((("2026-11-20",), "all", None))
    with open(path, "wb") as handle:
        handle.write(json.dumps(header).encode() + b"\n" + rest)
    board.new_worker()
    assert board.read()[0] == 2


def test_an_older_build_never_replaces_a_newer_copy(board, monkeypatch):
    _on(monkeypatch)
    now = time.time()
    assert shared.publish(KEY, built_at=now, overlay_mtime=0.0, payload={"v": "new"}, rows=0, lease=None)
    assert not shared.publish(KEY, built_at=now - 10, overlay_mtime=0.0, payload={"v": "old"}, rows=0, lease=None)
    copy = shared.adopt_fresh(KEY, newer_than=None, newest_overlay=0.0, ttl_s=180, overlay_min_age_s=22)
    assert copy is not None and copy.payload == {"v": "new"}


def test_cleanup_removes_only_copies_no_reader_may_use(board, monkeypatch):
    _on(monkeypatch)
    board.dir.mkdir(parents=True)
    old, fresh = board.dir / "old.board", board.dir / "fresh.board"
    for p in (old, fresh):
        p.write_bytes(b"x")
    os.utime(old, (time.time() - 3600, time.time() - 3600))
    assert shared._cleanup(str(board.dir), keep_seconds=1860) == 1
    assert fresh.exists() and not old.exists()


@pytest.mark.skipif(os.name != "posix", reason="ownership and mode checks are POSIX")
def test_a_directory_others_can_write_is_refused(board, monkeypatch, capsys):
    _on(monkeypatch)
    board.dir.mkdir(parents=True)
    os.chmod(board.dir, 0o777)
    board.read()
    board.new_worker()
    assert board.read()[0] == 2
    assert "COMBINED_BOARD_SHARED_OFF" in capsys.readouterr().out
