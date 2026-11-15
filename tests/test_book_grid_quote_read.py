"""The incremental book-grid quote read (todo #790) returns EXACTLY what the one-pass read returns.

Every equality here is row-for-row and in order, never by count or length: two earlier reductions of this
same stream permuted 2,006 of 5,547 grid rows and re-anchored 972 at identical byte length (see
`freshest_rows_for_grid`), and only a grid-to-grid comparison sees that.
"""

from __future__ import annotations

import functools
import gzip
import json
import os
import random
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from syndicate.features.shared import board_enrichment, book_grid_artifact, book_grid_quote_read
from syndicate.features.shared.book_grid import freshest_rows_for_grid
from syndicate.features.shared.book_grid_quote_read import read_grid_quote_rows
from syndicate.features.shared.odds_book_quotes import book_quotes_path, iter_book_quotes

SPORT, DATE = "ncaaf", "2099-11-14"


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    monkeypatch.delenv(book_grid_quote_read.ENABLED_ENV, raising=False)
    monkeypatch.delenv(book_grid_quote_read.VERIFY_SECONDS_ENV, raising=False)
    book_grid_quote_read.reset_state()
    yield
    book_grid_quote_read.reset_state()


def _shard() -> Path:
    path = book_quotes_path(SPORT, DATE)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _append(text: str | bytes) -> None:
    data = text.encode("utf-8") if isinstance(text, str) else text
    with open(_shard(), "ab") as handle:
        handle.write(data)


def _one_pass() -> tuple[list[dict], int]:
    count = 0

    def _counted():
        nonlocal count
        for row in iter_book_quotes(SPORT, DATE):
            count += 1
            yield row

    return freshest_rows_for_grid(_counted(), report=False), count


def _rows(rng: random.Random, n: int, clock: list[int]) -> list[str]:
    """A change log with every case the reduce decides on: re-quotes, ties, an OLDER quote arriving late,
    line moves (new anchors), priceless rows, an aggregator copy of a venue and the venue's own row,
    empty book/side, and lines that are not rows at all."""
    events = ["e1", "e2", "e3"]
    markets = [("h2h", None), ("spreads", 3.5), ("totals", 48.5)]
    books = ["draftkings", "fanduel", "betmgm", "kalshi", "", "pinnacle"]
    out: list[str] = []
    for _ in range(n):
        clock[0] += rng.choice([0, 1, 1, 2, 5])  # 0 = a same-timestamp tie
        stamp = f"2099-11-14T{(clock[0] // 3600) % 24:02d}:{(clock[0] // 60) % 60:02d}:{clock[0] % 60:02d}Z"
        if rng.random() < 0.05:
            stamp = "2099-11-14T00:00:00Z"  # a late, OLDER quote: must not displace a fresher one
        market, base = rng.choice(markets)
        line = None if base is None else base + rng.choice([-1.0, -0.5, 0.0, 0.0, 0.5, 1.0])
        selection = rng.choice(["home", "away"] if market != "totals" else ["over", "under"])
        if market == "spreads" and selection == "home" and line is not None:
            line = -line
        row = {
            "sport": SPORT, "kind": "game", "event_id": rng.choice(events), "segment": "", "market": market,
            "player_name": "", "selection": selection if rng.random() > 0.02 else "", "line": line,
            "price": rng.choice([-110, -105, 100, 120, -150, None if rng.random() < 0.05 else 105]),
            "bookmaker": rng.choice(books), "book_updated_at": stamp, "snapshot_ts": stamp, "captured_at": stamp,
            "home_team": "Home U", "away_team": "Away St", "commence_time": "2099-11-15T00:00:00Z",
        }
        if row["bookmaker"] == "kalshi" and rng.random() < 0.5:
            row["source"] = "venue_direct"
        out.append(json.dumps(row))
        roll = rng.random()
        if roll < 0.01:
            out.append("")  # blank: skipped, not counted
        elif roll < 0.02:
            out.append('{"price": -110, "bookmak')  # a spliced fragment: counted bad
        elif roll < 0.025:
            out.append("[1, 2, 3]")  # JSON, but not a row: counted bad
    return out


def _check(expected_mode: str | None = None, capsys=None) -> tuple[list[dict], int]:
    rows, count = read_grid_quote_rows(SPORT, DATE)
    reference_rows, reference_count = _one_pass()
    assert rows == reference_rows
    assert count == reference_count
    if expected_mode is not None and capsys is not None:
        out = capsys.readouterr().out
        modes = re.findall(r"BOOK_GRID_QUOTE_READ sport=\S+ date=\S+ mode=(\S+)", out)
        assert modes == [expected_mode], out
    return rows, count


def test_chunked_appends_match_the_one_pass_read_after_every_chunk(capsys):
    rng = random.Random(790)
    clock = [0]
    _append("\n".join(_rows(rng, 400, clock)) + "\n")
    _check("fresh:new", capsys)
    for _ in range(25):
        _append("\n".join(_rows(rng, rng.randint(0, 60), clock)) + "\n")
        _check("incremental", capsys)
    rows, count = _check()
    assert 0 < len(rows) < count  # the reduce actually reduced, so equality above was not vacuous


def test_new_rows_counts_only_the_appended_lines(capsys):
    rng = random.Random(1)
    clock = [0]
    _append("".join(line + "\n" for line in _rows(rng, 50, clock) if line.startswith("{\"sport\"")))
    read_grid_quote_rows(SPORT, DATE)
    capsys.readouterr()
    _append("".join(line + "\n" for line in _rows(rng, 7, clock) if line.startswith("{\"sport\"")))
    read_grid_quote_rows(SPORT, DATE)
    out = capsys.readouterr().out
    assert re.search(r"mode=incremental new_rows=7 ", out), out


def test_crlf_and_lone_cr_split_like_a_text_mode_read():
    rng = random.Random(2)
    clock = [0]
    lines = _rows(rng, 120, clock)
    _append("\r\n".join(lines[:40]) + "\r\n")
    _check()
    # A lone "\r" ends a line in a text-mode read; it must here too.
    _append("\r".join(lines[40:80]) + "\n")
    _check()
    _append("\n".join(lines[80:]) + "\n")
    _check()


def test_a_line_still_being_written_waits_for_its_newline():
    rng = random.Random(3)
    clock = [0]
    good = [line for line in _rows(rng, 80, clock) if line.startswith("{\"sport\"")]
    _append("\n".join(good[:60]) + "\n")
    _check()
    partial = good[60]
    _append(partial[:25])  # a writer mid-append
    rows, count = read_grid_quote_rows(SPORT, DATE)
    reference_rows = freshest_rows_for_grid((json.loads(line) for line in good[:60]), report=False)
    assert rows == reference_rows and count == 60
    _append(partial[25:] + "\n" + "\n".join(good[61:]) + "\n")
    _check()


def test_a_replaced_or_rewritten_file_starts_over(capsys):
    rng = random.Random(4)
    clock = [0]
    path = _shard()
    _append("\n".join(_rows(rng, 100, clock)) + "\n")
    _check("fresh:new", capsys)

    # Replaced (the sanitize pass and a whole-file pull both os.replace): new inode.
    other = path.with_name(path.name + ".tmp")
    other.write_text("\n".join(_rows(rng, 90, clock)) + "\n", encoding="utf-8")
    os.replace(other, path)
    _check("fresh:replaced", capsys)

    # Shrunk in place.
    data = path.read_bytes()
    with open(path, "r+b") as handle:
        handle.truncate(data.rfind(b"\n", 0, len(data) // 2) + 1)
    _check("fresh:shrunk", capsys)

    # Rewritten in place, same inode, LONGER than before: only the head/tail guards can see it.
    data = path.read_bytes()
    with open(path, "r+b") as handle:
        handle.seek(0)
        handle.write(b"[0]" + b" " * (data.index(b"\n") - 3))
        handle.seek(0, os.SEEK_END)
        handle.write(("\n".join(_rows(rng, 30, clock)) + "\n").encode("utf-8"))
    _check("fresh:head_changed", capsys)


def test_mutating_returned_rows_never_reaches_the_next_build():
    rng = random.Random(5)
    clock = [0]
    _append("\n".join(_rows(rng, 200, clock)) + "\n")
    rows, _ = read_grid_quote_rows(SPORT, DATE)
    for row in rows:
        row["price"] = 99999
        row["poisoned"] = True
    _append("\n".join(_rows(rng, 5, clock)) + "\n")
    _check()


def test_no_parsed_row_is_held_between_builds():
    rng = random.Random(6)
    clock = [0]
    _append("\n".join(_rows(rng, 300, clock)) + "\n")
    read_grid_quote_rows(SPORT, DATE)
    (state,) = book_grid_quote_read._STATES.values()
    reducer = state.reducer
    assert all(type(v) is tuple and type(v[0]) is int and type(v[1]) is str for v in reducer.freshest.values())
    assert all(type(v) is int for v in reducer.anchors.values())
    assert not any(isinstance(getattr(state, name), (dict, list)) for name in ("starts", "lengths"))


def test_the_periodic_check_matches_and_says_so(monkeypatch, capsys):
    monkeypatch.setenv(book_grid_quote_read.VERIFY_SECONDS_ENV, "0")
    rng = random.Random(7)
    clock = [0]
    _append("\n".join(_rows(rng, 150, clock)) + "\n")
    _check()
    _append("\n".join(_rows(rng, 30, clock)) + "\n")
    _check()
    out = capsys.readouterr().out
    assert out.count("verify=match") == 2, out
    assert "MISMATCH" not in out


def test_a_failed_check_serves_the_reference_and_turns_the_read_off(monkeypatch, capsys):
    monkeypatch.setenv(book_grid_quote_read.VERIFY_SECONDS_ENV, "0")
    rng = random.Random(8)
    clock = [0]
    _append("\n".join(_rows(rng, 150, clock)) + "\n")
    read_grid_quote_rows(SPORT, DATE)
    # Corrupt the kept state the way a reducer bug would: forget the anchors.
    (state,) = book_grid_quote_read._STATES.values()
    state.reducer.anchors.clear()
    state.reducer.anchor_indices.clear()
    _append("\n".join(_rows(rng, 20, clock)) + "\n")
    capsys.readouterr()
    _check()  # still the reference's rows
    out = capsys.readouterr().out
    assert "BOOK_GRID_QUOTE_READ_VERIFY" in out and "result=MISMATCH" in out
    _append("\n".join(_rows(rng, 5, clock)) + "\n")
    _check("full:disabled_after_mismatch", capsys)


def test_a_gz_shard_takes_the_one_pass_read(capsys):
    rng = random.Random(9)
    clock = [0]
    text = "\n".join(_rows(rng, 80, clock)) + "\n"
    packed = _shard().with_name(_shard().name + ".gz")
    packed.write_bytes(gzip.compress(text.encode("utf-8")))
    _check("full:gz", capsys)


@pytest.mark.parametrize("switch, mode", [("1", "incremental"), ("0", None)])
def test_off_is_not_on_through_the_real_builder(monkeypatch, capsys, switch, mode):
    """REACHABILITY: the switch changes which read runs (and only that) inside `build_book_grid_artifact`."""
    monkeypatch.setenv(book_grid_quote_read.ENABLED_ENV, switch)
    for name in ("attach_game_state", "attach_projections", "attach_margin_model",
                 "attach_live_game_state_from_lens", "attach_live_projections_for_sport",
                 "attach_live_gamelines_for_sport"):
        monkeypatch.setattr(board_enrichment, name, lambda grid, **kwargs: {})
    monkeypatch.setattr(book_grid_artifact, "_remember_inplay_rows", lambda *a, **k: None)
    import syndicate.features.shared.live_gameline_accuracy as accuracy
    import syndicate.features.shared.live_gameline_ledger as ledger

    monkeypatch.setattr(ledger, "record_live_gamelines", lambda grid, **k: {})
    monkeypatch.setattr(accuracy, "record_live_gameline_score", lambda *a, **k: {})
    monkeypatch.setattr(book_grid_artifact, "score_block_for_grid", lambda grid, **k: {})
    monkeypatch.setattr(book_grid_artifact, "live_gameline_build_line", lambda *a, **k: "")
    # One clock for every build, so ages and staleness compare across the two reads.
    frozen = datetime(2099, 11, 14, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(book_grid_artifact, "build_book_grid",
                        functools.partial(book_grid_artifact.build_book_grid, now=frozen))

    rng = random.Random(10)
    clock = [0]
    _append("\n".join(_rows(rng, 300, clock)) + "\n")
    book_grid_artifact.build_book_grid_artifact(SPORT, DATE)
    _append("\n".join(_rows(rng, 40, clock)) + "\n")
    capsys.readouterr()
    payload = book_grid_artifact.build_book_grid_artifact(SPORT, DATE)
    out = capsys.readouterr().out
    modes = re.findall(r"BOOK_GRID_QUOTE_READ sport=\S+ date=\S+ mode=(\S+)", out)
    assert modes == ([mode] if mode else []), out
    assert bool(book_grid_quote_read._STATES) is (switch == "1")

    # And the grid is the one-pass grid either way.
    monkeypatch.setenv(book_grid_quote_read.ENABLED_ENV, "0")
    reference = book_grid_artifact.build_book_grid_artifact(SPORT, DATE)
    for field in ("rows", "source_quote_rows", "source_rows_kept", "rows_total", "summary"):
        assert payload[field] == reference[field], field
