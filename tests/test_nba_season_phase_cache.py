"""`season_phase_for_date` reads the scoreboard once per file version, not once per row (todo #790, lane
book-grid-overlay-starvation).

Measured on the fleet 2026-11-13: 5,238 calls in one NBA book-grid build, each re-reading and re-parsing the same
ESPN scoreboard file -- 9.2-10.2 s, 43-44% of the build. The phase feeds the game-line book blend's weight
(`served_game_probability(..., phase=...)`), so the cache must return exactly what a fresh read would, and must
see a rewritten file. These tests pin: same answers as the uncached read; one read per (mtime_ns, size); a rewrite
is re-read; the off switch reads every call; and the same through `attach_nba_game_projections` (off != on in
reads, identical projections).
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import pytest

from syndicate.features.shared import nba_game_projections as ngp
from syndicate.features.shared import nba_prop_calibration as cal
from tests.test_nba_layer2_projections import D, _game_row, nba_root  # noqa: F401  (fixture reuse)

FLAG = "SYNDICATE_NBA_SEASON_PHASE_CACHE"


@pytest.fixture(autouse=True)
def _clean_cache(monkeypatch):
    monkeypatch.delenv(FLAG, raising=False)
    ngp._SEASON_PHASE_CACHE.clear()
    yield
    ngp._SEASON_PHASE_CACHE.clear()


def _scoreboard(root: Path, date: str, types) -> Path:
    cache = root / "data" / "processed" / "_espn_cache" / "nba"
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / f"scoreboard_{date.replace('-', '')}.json"
    events = [{"season": {"type": t}} if t is not None else {"season": {}} for t in types]
    path.write_text(json.dumps({"events": events}), encoding="utf-8")
    return path


def _bump_mtime(path: Path, seconds: int = 5) -> None:
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + seconds * 1_000_000_000))


@pytest.fixture
def reads(monkeypatch):
    """Counts actual scoreboard parses (the expensive step)."""
    counter = {"n": 0}
    real = ngp._season_phase_from_file

    def counting(path):
        counter["n"] += 1
        return real(path)

    monkeypatch.setattr(ngp, "_season_phase_from_file", counting)
    return counter


@pytest.mark.parametrize(
    "types, expected",
    [
        ([1, 1], "preseason"),
        ([2], "regular"),
        ([3, 3, 3], "postseason"),
        ([1, 2], None),          # the date's events disagree -> UNKNOWN
        ([None], None),          # no season type at all
        ([], None),              # no events
        ([9], None),             # a type ESPN does not define
    ],
)
def test_cached_answer_equals_a_fresh_read(nba_root, monkeypatch, types, expected):
    path = _scoreboard(nba_root, D, types)
    fresh = ngp._season_phase_from_file(path)
    assert fresh == expected
    first = ngp.season_phase_for_date(D)
    second = ngp.season_phase_for_date(D)
    monkeypatch.setenv(FLAG, "off")
    uncached = ngp.season_phase_for_date(D)
    assert first == second == uncached == expected


def test_corrupt_and_absent_files_answer_none(nba_root):
    path = _scoreboard(nba_root, D, [2])
    path.write_text("{not json", encoding="utf-8")
    assert ngp.season_phase_for_date(D) is None
    assert ngp.season_phase_for_date("2026-01-01") is None  # no file for that date
    assert ngp.season_phase_for_date(None) is None and ngp.season_phase_for_date("") is None


def test_one_parse_per_file_version_not_per_call(nba_root, reads):
    _scoreboard(nba_root, D, [2])
    answers = {ngp.season_phase_for_date(D) for _ in range(500)}
    assert answers == {"regular"}
    assert reads["n"] == 1


def test_the_off_switch_reads_every_call(nba_root, reads, monkeypatch):
    """Reachability: off != on, measured in parses."""
    _scoreboard(nba_root, D, [2])
    monkeypatch.setenv(FLAG, "off")
    for _ in range(5):
        assert ngp.season_phase_for_date(D) == "regular"
    assert reads["n"] == 5
    monkeypatch.delenv(FLAG)
    for _ in range(5):
        assert ngp.season_phase_for_date(D) == "regular"
    assert reads["n"] == 6


def test_a_rewritten_scoreboard_is_read_again(nba_root, reads):
    path = _scoreboard(nba_root, D, [1])
    assert ngp.season_phase_for_date(D) == "preseason"
    _scoreboard(nba_root, D, [2, 2])            # different bytes, different size
    _bump_mtime(path)
    assert ngp.season_phase_for_date(D) == "regular"
    assert reads["n"] == 2


def test_a_same_size_rewrite_with_a_new_mtime_is_read_again(nba_root, reads):
    """Same length, different content: the size alone would serve the stale phase."""
    path = _scoreboard(nba_root, D, [1])
    size = path.stat().st_size
    assert ngp.season_phase_for_date(D) == "preseason"
    _scoreboard(nba_root, D, [3])
    assert path.stat().st_size == size
    _bump_mtime(path)
    assert ngp.season_phase_for_date(D) == "postseason"
    assert reads["n"] == 2


def test_each_date_is_its_own_entry(nba_root, reads):
    _scoreboard(nba_root, D, [1])
    _scoreboard(nba_root, "2026-10-25", [2])
    assert ngp.season_phase_for_date(D) == "preseason"
    assert ngp.season_phase_for_date("2026-10-25") == "regular"
    assert ngp.season_phase_for_date(D) == "preseason"
    assert reads["n"] == 2


def test_the_cache_is_bounded(nba_root, monkeypatch):
    monkeypatch.setattr(ngp, "_SEASON_PHASE_CACHE_MAX", 3)
    for day in range(1, 8):
        date = f"2026-11-{day:02d}"
        _scoreboard(nba_root, date, [2])
        assert ngp.season_phase_for_date(date) == "regular"
        assert len(ngp._SEASON_PHASE_CACHE) <= 3


def test_through_the_game_projection_attach(nba_root, reads, monkeypatch):
    """The real caller: many priced rows, one parse; projections identical with the cache off."""
    from syndicate.features.nba.sources import artifact_processed_root
    from tests.test_basketball_market_board_book_blend import GW

    (artifact_processed_root() / cal.GAME_BLEND_FILE).write_text(
        json.dumps(dict(GW, phase={"preseason": {"default": 0.0}})), encoding="utf-8")
    monkeypatch.delenv(cal.GAME_BLEND_FLAG, raising=False)
    _scoreboard(nba_root, D, [1])
    template = [_game_row("totals_alt", line=229.5) for _ in range(40)]

    rows_on = copy.deepcopy(template)
    ngp.attach_nba_game_projections(rows_on, ngp.load_nba_game_projections(D))
    parses_on = reads["n"]

    monkeypatch.setenv(FLAG, "off")
    rows_off = copy.deepcopy(template)
    ngp.attach_nba_game_projections(rows_off, ngp.load_nba_game_projections(D))
    parses_off = reads["n"] - parses_on

    assert all(r["projection"]["season_phase"] == "preseason" for r in rows_on)
    assert parses_on == 1 and parses_off == 40
    assert [r["projection"] for r in rows_on] == [r["projection"] for r in rows_off]
