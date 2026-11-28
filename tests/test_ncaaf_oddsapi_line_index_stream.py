"""The NCAAF line index, read streamed and append-aware, against the reader it replaced.

[2026-11-27, lane ncaaf-cards-build-cost] `oddsapi_lines.load_week_line_index`
used to read every row of the week's quote shards into one list (174 MB / 382,883
lines for week 13 on the fleet) before collapsing it: +940-984 MB of peak RSS and
2.5-2.9 s on every NCAAF cards build. It now collapses rows as it reads them and,
for a plain (append-only) shard, parses only the bytes appended since the last read.

The contract is that the INDEX IS UNCHANGED, including its key order. So every test
here builds the same shards and compares the new reader with a verbatim copy of the
old one (`_old_*` below, from `oddsapi_lines.py` at `e908a5fda`), over the cases the
old text-mode reader had an answer for: repeats, other segments and kinds, blank and
unparseable lines, CRLF and lone CR, a BOM, a torn last line, undecodable bytes,
appends, an `os.replace`, an in-place rewrite, and `.gz` shards.

Team names go through a small fake resolver: the registry CSV lives under `data/`,
which a session worktree does not carry, and the collapse is what is under test.
"""

from __future__ import annotations

import gzip
import json
import os
import re
import statistics
import tracemalloc
from pathlib import Path
from typing import Any

import pytest

from syndicate.features.ncaaf import oddsapi_lines as ol
from syndicate.features.shared import odds_book_quotes as obq

_TEAMS = {
    "Alpha Aces": "Alpha",
    "Beta Bees": "Beta",
    "Delta Dogs": "Delta",
    "Echo Eels": "Echo",
    "Fox Ferrets": "Fox",
    "Golf Geese": "Golf",
}


def _key_fn(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


# --------------------------------------------------------------------------
# The reader this replaced, verbatim apart from taking its path and resolver.
# --------------------------------------------------------------------------

def _old_iter_quote_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        opener = gzip.open if str(path).endswith(".gz") else open
        with opener(path, "rt", encoding="utf-8") as handle:  # type: ignore[operator]
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
    except Exception:
        return []
    return rows


def _old_latest_per_key(rows):
    latest: dict[tuple, dict[str, Any]] = {}
    for row in rows:
        if str(row.get("kind") or "game") != "game":
            continue
        if str(row.get("segment") or ol.SEGMENT_FULL) != ol.SEGMENT_FULL:
            continue
        key = (
            str(row.get("home_team") or ""),
            str(row.get("away_team") or ""),
            str(row.get("market") or ""),
            str(row.get("selection") or ""),
            str(row.get("bookmaker") or ""),
        )
        latest[key] = dict(row)
    return latest


def _old_build_line_index(rows, *, key_fn):
    latest = _old_latest_per_key(rows)
    per_game: dict[tuple[str, str], dict[str, Any]] = {}
    for (home_raw, away_raw, market, selection, book), row in latest.items():
        home = ol.resolve_team(home_raw)
        away = ol.resolve_team(away_raw)
        if not home or not away:
            continue
        key = (key_fn(home), key_fn(away))
        bucket = per_game.setdefault(
            key,
            {"spreads": {}, "totals": [], "h2h": {}, "home_name": home, "away_name": away},
        )
        line = ol._as_float(row.get("line"))
        price = row.get("price")
        side = ol._selection_side(selection, home_raw=home_raw, away_raw=away_raw)
        if market == ol.MARKET_SPREADS and line is not None:
            if side == "home":
                bucket["spreads"][book] = line
        elif market == ol.MARKET_TOTALS and line is not None:
            if side == "over":
                bucket["totals"].append(line)
        elif market == ol.MARKET_H2H and price is not None:
            if side in ("home", "away"):
                bucket["h2h"].setdefault(book, {})[side] = price
    index: dict[tuple[str, str], dict[str, Any]] = {}
    for key, bucket in per_game.items():
        spreads = list(bucket["spreads"].values())
        totals = list(bucket["totals"])
        home_ml = away_ml = None
        for _book, prices in bucket["h2h"].items():
            if prices.get("home") is not None and prices.get("away") is not None:
                home_ml = prices.get("home")
                away_ml = prices.get("away")
                break
        index[key] = {
            "market_margin": (-statistics.mean(spreads)) if spreads else None,
            "market_total": statistics.mean(totals) if totals else None,
            "home_moneyline": home_ml,
            "away_moneyline": away_ml,
            "book_count": len(set(bucket["spreads"]) | set(bucket["h2h"])),
            "source": "oddsapi_book_quotes",
        }
    return index


def _old_load(paths: dict[str, Path], dates) -> dict:
    rows: list[dict[str, Any]] = []
    for date_str in dict.fromkeys(str(d).strip() for d in dates if d):
        path = paths.get(date_str)
        if not path or not Path(path).is_file():
            continue
        rows.extend(_old_iter_quote_rows(path))
    if not rows:
        return {}
    return _old_build_line_index(rows, key_fn=_key_fn)


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    ol.clear_shard_cache()
    monkeypatch.setattr(ol, "resolve_team", lambda name: _TEAMS.get(str(name or "").strip()))
    yield
    ol.clear_shard_cache()


@pytest.fixture
def shards(monkeypatch, tmp_path):
    paths: dict[str, Path] = {}

    def _resolve(sport: str, date_str: str) -> Path:
        return paths.get(str(date_str).strip(), tmp_path / f"absent_{date_str}.jsonl")

    monkeypatch.setattr(obq, "resolve_book_quotes_path", _resolve)
    return paths


def _quote(home, away, market, selection, book, *, line=None, price=None, segment="full", kind="game", seq=0):
    return {
        "kind": kind,
        "segment": segment,
        "home_team": home,
        "away_team": away,
        "market": market,
        "selection": selection,
        "bookmaker": book,
        "line": line,
        "price": price,
        "captured_at": f"2026-11-27T12:{seq % 60:02d}:00Z",
    }


def _line(row, *, ensure_ascii: bool = True) -> bytes:
    return (json.dumps(row, separators=(",", ":"), ensure_ascii=ensure_ascii) + "\n").encode("utf-8")


def _slate_bytes(seq_start: int = 0, books=("dk", "fd", "mgm")) -> bytes:
    """A shard's worth of rows: three games, three markets, repeats that move the line."""
    out = bytearray()
    seq = seq_start
    games = [("Alpha Aces", "Beta Bees"), ("Delta Dogs", "Echo Eels"), ("Fox Ferrets", "Golf Geese")]
    for step in range(3):
        for home, away in games:
            for book in books:
                seq += 1
                spread = -3.5 - 0.5 * step
                out += _line(_quote(home, away, "spreads", "home", book, line=spread, price=-110, seq=seq))
                out += _line(_quote(home, away, "spreads", "away", book, line=-spread, price=-110, seq=seq))
                out += _line(_quote(home, away, "totals", "over", book, line=52.5 + step, price=-112, seq=seq))
                out += _line(_quote(home, away, "totals", "under", book, line=52.5 + step, price=-108, seq=seq))
                out += _line(_quote(home, away, "h2h", "home", book, price=-160 - 10 * step, seq=seq))
                out += _line(_quote(home, away, "h2h", "away", book, price=140 + 10 * step, seq=seq))
                # Rows the collapse must skip: another segment, a prop.
                out += _line(_quote(home, away, "totals", "over", book, line=24.5, price=-110, segment="h1", seq=seq))
                out += _line(_quote(home, away, "player_pass_yds", "over", book, line=250.5, kind="prop", seq=seq))
    # A team the resolver does not know: dropped by both readers.
    out += _line(_quote("Zulu Zebras", "Alpha Aces", "spreads", "home", "dk", line=1.5, price=-110))
    return bytes(out)


def _write(path: Path, data: bytes, mode: str = "wb") -> None:
    with open(path, mode) as handle:
        handle.write(data)


def _new(dates) -> dict:
    return ol.load_week_line_index(2026, 13, key_fn=_key_fn, kickoff_dates=dates)


def _same(new: dict, old: dict) -> None:
    assert list(new.items()) == list(old.items())
    assert json.dumps(list(new.items())) == json.dumps(list(old.items()))


def _read_stats(capsys) -> dict[str, int]:
    lines = [line for line in capsys.readouterr().out.splitlines() if "LINE_INDEX_READ" in line]
    assert lines, "the LINE_INDEX_READ line was not printed"
    return {k: int(v) for k, v in re.findall(r"(\w+)=(\d+)", lines[-1]) if k not in ("season", "week")}


# --------------------------------------------------------------------------
# the index itself
# --------------------------------------------------------------------------

def test_a_mixed_two_date_week_matches_the_old_reader(shards, tmp_path):
    first = tmp_path / "2026-11-27.jsonl"
    second = tmp_path / "2026-11-28.jsonl"
    junk = (
        b"\n   \n"                       # blank lines
        b"not json at all\n"
        b"[1, 2, 3]\n"                   # JSON, not an object
        + _line(_quote("Alpha Aces", "Beta Bees", "spreads", "home", "dk", line=-7.0, price=-110))[:-1]
        + _line(_quote("Delta Dogs", "Echo Eels", "spreads", "home", "dk", line=-1.0, price=-110))  # glued: one bad line
    )
    _write(first, b"\xef\xbb\xbf" + _slate_bytes() + junk)
    # CRLF rows, a lone CR between two rows, and a last row with no newline.
    crlf = _line(_quote("Alpha Aces", "Beta Bees", "spreads", "home", "br", line=-6.5, price=-105)).replace(b"\n", b"\r\n")
    lone_cr = (
        _line(_quote("Delta Dogs", "Echo Eels", "totals", "over", "br", line=60.5, price=-110))[:-1]
        + b"\r"
        + _line(_quote("Delta Dogs", "Echo Eels", "spreads", "home", "br", line=-2.5, price=-110))
    )
    last = _line(_quote("Fox Ferrets", "Golf Geese", "h2h", "home", "br", price=-300))[:-1]
    _write(second, _slate_bytes(seq_start=500, books=("dk", "br")) + crlf + lone_cr + last)
    shards.update({"2026-11-27": first, "2026-11-28": second})

    dates = ["2026-11-25", "2026-11-27", "2026-11-28", "2026-11-27", "", "2026-11-29"]
    old = _old_load(shards, dates)
    assert old, "fixture produced an empty index: the comparison would be vacuous"
    _same(_new(dates), old)
    # Warm: same answer from the cache.
    _same(_new(dates), old)


def test_the_rows_entry_point_is_unchanged(shards, tmp_path):
    rows = _old_iter_quote_rows_from_bytes(tmp_path, _slate_bytes())
    _same(ol.build_line_index(rows, key_fn=_key_fn), _old_build_line_index(rows, key_fn=_key_fn))


def _old_iter_quote_rows_from_bytes(tmp_path: Path, data: bytes) -> list[dict[str, Any]]:
    path = tmp_path / "rows.jsonl"
    _write(path, data)
    return _old_iter_quote_rows(path)


def test_no_shard_and_empty_shards_give_an_empty_index(shards, tmp_path):
    assert _new(["2026-11-27"]) == {} == _old_load(shards, ["2026-11-27"])
    empty = tmp_path / "2026-11-27.jsonl"
    _write(empty, b"")
    shards["2026-11-27"] = empty
    assert _new(["2026-11-27"]) == {} == _old_load(shards, ["2026-11-27"])
    _write(empty, b"\n\nnot json\n")
    assert _new(["2026-11-27"]) == {} == _old_load(shards, ["2026-11-27"])


# --------------------------------------------------------------------------
# appends: the part that is cached
# --------------------------------------------------------------------------

def test_appends_cut_anywhere_match_a_full_read_and_only_the_first_read_is_full(shards, tmp_path, capsys):
    path = tmp_path / "2026-11-28.jsonl"
    shards["2026-11-28"] = path
    data = _slate_bytes() + _slate_bytes(seq_start=900, books=("dk", "fd", "br"))
    # Cut points mid-line, on a newline, one byte short of the end, and at the end.
    cuts = sorted({1, 37, 400, 401, len(data) // 3, len(data) // 2 + 5, len(data) - 1, len(data)})
    written = 0
    reads = []
    for cut in cuts:
        _write(path, data[written:cut], mode="ab")
        written = cut
        _same(_new(["2026-11-28"]), _old_load(shards, ["2026-11-28"]))
        reads.append(_read_stats(capsys))
    assert reads[0]["full_reads"] == 1
    assert all(r["full_reads"] == 0 for r in reads[1:]), reads
    # Off != on: later reads reused what earlier reads parsed.
    assert reads[-1]["reused_bytes"] > 0
    assert reads[-1]["reused_bytes"] + reads[-1]["parsed_bytes"] == len(data)


def test_a_torn_utf8_tail_drops_the_date_then_recovers_like_the_old_reader(shards, tmp_path):
    path = tmp_path / "2026-11-28.jsonl"
    shards["2026-11-28"] = path
    _write(path, _slate_bytes())
    _same(_new(["2026-11-28"]), _old_load(shards, ["2026-11-28"]))
    accented = _line(
        _quote("Alpha Aces", "Beta Bees", "spreads", "home", "caf\u00e9", line=-9.5, price=-110), ensure_ascii=False
    )
    cut = accented.index("\u00e9".encode("utf-8")) + 1   # half of a two-byte character
    _write(path, accented[:cut], mode="ab")
    assert _old_load(shards, ["2026-11-28"]) == {}
    _same(_new(["2026-11-28"]), {})
    _write(path, accented[cut:], mode="ab")
    old = _old_load(shards, ["2026-11-28"])
    assert old
    _same(_new(["2026-11-28"]), old)


def test_an_undecodable_complete_line_drops_the_date_for_as_long_as_it_is_there(shards, tmp_path):
    first = tmp_path / "2026-11-27.jsonl"
    second = tmp_path / "2026-11-28.jsonl"
    shards.update({"2026-11-27": first, "2026-11-28": second})
    _write(first, _slate_bytes())
    _write(second, _slate_bytes(seq_start=300, books=("br",)))
    dates = ["2026-11-27", "2026-11-28"]
    _same(_new(dates), _old_load(shards, dates))
    _write(second, b'{"kind":"game","bookmaker":"\xff\xfe"}\n', mode="ab")
    for extra in range(3):
        old = _old_load(shards, dates)
        assert old  # the other date still counts
        _same(_new(dates), old)
        _write(second, _line(_quote("Alpha Aces", "Beta Bees", "h2h", "home", f"x{extra}", price=-120)), mode="ab")


def test_a_replaced_shard_is_read_from_scratch(shards, tmp_path, capsys):
    path = tmp_path / "2026-11-28.jsonl"
    shards["2026-11-28"] = path
    _write(path, _slate_bytes())
    _new(["2026-11-28"])
    capsys.readouterr()
    replacement = tmp_path / "replacement.tmp"
    _write(replacement, _slate_bytes(seq_start=77, books=("fd", "mgm", "dk", "br")))
    os.replace(replacement, path)
    _same(_new(["2026-11-28"]), _old_load(shards, ["2026-11-28"]))
    assert _read_stats(capsys)["full_reads"] == 1


def test_a_shard_rewritten_in_place_is_read_from_scratch(shards, tmp_path, capsys):
    """Same inode, longer than before, different bytes just before the old offset."""
    path = tmp_path / "2026-11-28.jsonl"
    shards["2026-11-28"] = path
    original = _slate_bytes()
    _write(path, original)
    _new(["2026-11-28"])
    capsys.readouterr()
    rewritten = original[: len(original) // 2] + _slate_bytes(seq_start=11, books=("br", "dk"))
    assert len(rewritten) > len(original)
    with open(path, "r+b") as handle:
        handle.seek(0)
        handle.write(rewritten)
        handle.truncate()
    _same(_new(["2026-11-28"]), _old_load(shards, ["2026-11-28"]))
    assert _read_stats(capsys)["full_reads"] == 1


def test_a_shorter_shard_is_read_from_scratch(shards, tmp_path):
    path = tmp_path / "2026-11-28.jsonl"
    shards["2026-11-28"] = path
    _write(path, _slate_bytes() + _slate_bytes(seq_start=40))
    _new(["2026-11-28"])
    _write(path, _slate_bytes(seq_start=5, books=("br",)))
    _same(_new(["2026-11-28"]), _old_load(shards, ["2026-11-28"]))


# --------------------------------------------------------------------------
# compacted shards
# --------------------------------------------------------------------------

def test_a_gz_shard_matches_is_reused_and_is_reread_when_replaced(shards, tmp_path, capsys):
    packed = tmp_path / "2026-11-27.jsonl.gz"
    tail = _line(_quote("Echo Eels", "Delta Dogs", "h2h", "away", "dk", price=125))[:-1]
    with gzip.open(packed, "wb") as handle:
        handle.write(_slate_bytes() + tail)
    shards["2026-11-27"] = packed
    old = _old_load(shards, ["2026-11-27"])
    assert old
    _same(_new(["2026-11-27"]), old)
    assert _read_stats(capsys)["full_reads"] == 1
    _same(_new(["2026-11-27"]), old)
    assert _read_stats(capsys)["full_reads"] == 0
    staged = tmp_path / "staged.gz"
    with gzip.open(staged, "wb") as handle:
        handle.write(_slate_bytes(seq_start=9, books=("br",)))
    os.replace(staged, packed)
    _same(_new(["2026-11-27"]), _old_load(shards, ["2026-11-27"]))
    assert _read_stats(capsys)["full_reads"] == 1


def test_a_truncated_gz_drops_the_date_like_the_old_reader(shards, tmp_path):
    packed = tmp_path / "2026-11-27.jsonl.gz"
    whole = tmp_path / "whole.gz"
    with gzip.open(whole, "wb") as handle:
        handle.write(_slate_bytes() * 3)
    _write(packed, whole.read_bytes()[:-200])
    shards["2026-11-27"] = packed
    assert _old_load(shards, ["2026-11-27"]) == {}
    _same(_new(["2026-11-27"]), {})


# --------------------------------------------------------------------------
# the cache itself
# --------------------------------------------------------------------------

def test_the_cache_holds_at_most_its_limit_and_stays_right_past_it(shards, tmp_path):
    dates = [f"2026-10-{day:02d}" for day in range(1, ol._SHARD_CACHE_LIMIT + 6)]
    for offset, date_str in enumerate(dates):
        path = tmp_path / f"{date_str}.jsonl"
        _write(path, _slate_bytes(seq_start=offset * 10, books=("dk", f"b{offset}")))
        shards[date_str] = path
    _same(_new(dates), _old_load(shards, dates))
    assert len(ol._SHARD_COLLAPSES) == ol._SHARD_CACHE_LIMIT
    _same(_new(dates[:3]), _old_load(shards, dates[:3]))


def test_the_cached_collapse_is_never_mutated_by_a_later_read(shards, tmp_path):
    path = tmp_path / "2026-11-28.jsonl"
    shards["2026-11-28"] = path
    _write(path, _slate_bytes())
    _new(["2026-11-28"])
    state = ol._SHARD_COLLAPSES[str(path)]
    before = dict(state.latest)
    _write(path, _slate_bytes(seq_start=200, books=("br",)), mode="ab")
    _write(path, _line(_quote("Alpha Aces", "Beta Bees", "h2h", "home", "zz", price=-101))[:-1], mode="ab")
    _new(["2026-11-28"])
    assert state.latest == before


def test_the_reader_never_holds_the_shard_as_rows(shards, tmp_path):
    """The point of the change: peak memory tracks the distinct keys, not the shard."""
    path = tmp_path / "2026-11-28.jsonl"
    shards["2026-11-28"] = path
    _write(path, b"".join(_slate_bytes(seq_start=s * 1000) for s in range(40)))
    tracemalloc.start()
    try:
        tracemalloc.reset_peak()
        old = _old_load(shards, ["2026-11-28"])
        _, old_peak = tracemalloc.get_traced_memory()
        tracemalloc.reset_peak()
        new = _new(["2026-11-28"])
        _, new_peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    _same(new, old)
    assert new_peak * 10 < old_peak, (new_peak, old_peak)
