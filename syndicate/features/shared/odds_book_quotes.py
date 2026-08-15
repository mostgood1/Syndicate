"""Per-book, per-timestamp odds quotes -- the record CLV and best-price work needs.

WHY THIS IS A SEPARATE ARTIFACT FAMILY (#208/#209)
--------------------------------------------------
Every sport's OddsAPI call already returns 5-8 US books per market. Most of our
fetchers then keep exactly one and throw the rest away (#209 Class A), and the
one basketball fetcher that keeps them all writes to a file `odds_history` never
reads (#209 Class B). The consequence measured 2026-08-05: every ROI number in
#186-#204 was graded against one arbitrarily-chosen bookmaker, and closing-line
capture sat at 2.13% (MLB) / 6.85% (WNBA), game markets only.

The obvious fix -- add a `bookmaker` dimension to `odds_history` -- was measured
and rejected. That shard is already 54MB at 3,682 MLB market keys (~14.7KB/key
at 20 history entries); restoring ~5 books to the 3,437 prop keys would put it
near 250MB, written AND published every cycle on 2GB services. Worse, four
existing consumers assume one book per game and would silently pick an arbitrary
one instead of breaking loudly:
  - mlb/cards.py `_tracked_game_lines_index` keys on the team pair only, and its
    commence_time tiebreak ties for every book of the same game;
  - odds_refresh_tracking `_flatten_mlb_game_lines` omits book from `key_cols`,
    so `.first()`/`.last()` in `_persist_tracking_snapshot` would land on
    different books and report a cross-book spread as a line MOVE;
  - live_refresh_loop `_mlb_sim_input_fingerprint_by_game` would fold every
    book's line into one game's hash, so any single book twitching triggers a
    resim -- a resim storm, on the 4GB worker;
  - mlb/cards.py's odds-history movement badges take `next(...)` first-match.

So `odds_history` keeps its current single-book, display-oriented shape, and the
per-book truth lives here instead: one flat JSONL row per (event, book, market,
selection, price) observation, append-only, published cross-service.

WHAT THIS BUYS
--------------
Closing lines stop needing a stamp. `odds_refresh_tracking.py:1599` can only
stamp a close on a pregame->live transition, which it detects from
`commence_time` or live text markers -- and MLB prop keys carry neither (they
are literally `player_name=...|market=...|selection=...`), which is why prop
closing capture is structurally zero rather than merely low. Every row here
carries `commence_time`, so the closing line is simply the last observation
before it: a lookup, not an inference, and correct retroactively for any row
already written.

Dedupe is against the LAST value seen for a quote key, not against the whole
file -- so an unchanged price is not re-appended every 60-second cycle, but a
line that moves away and comes back is still recorded both times. The last-value
map lives in a small sidecar rather than by re-reading the JSONL, because
re-reading a tens-of-MB file every cycle on the odds worker is the same class of
mistake this module exists to avoid.
"""

from __future__ import annotations

import gzip
import json
import os
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

from syndicate.features.shared.opportunity_signals import consensus_vigged_price
from syndicate.features.shared.refresh_state_store import data_root

# Kept deliberately flat and uniform across sports. A consumer that can read
# MLB's rows can read WNBA's without a per-sport branch -- the thing the current
# odds_history snapshot-path routing (one bespoke file list per sport) does not
# give us.
QUOTE_FIELDS: tuple[str, ...] = (
    "captured_at",
    "snapshot_ts",
    # TWO CLOCKS, NEVER CONFLATED.
    #
    # `captured_at` is when OUR loop looked. `book_updated_at` is when the BOOK
    # last moved this number, straight from OddsAPI's per-market `last_update`.
    # They fail independently and the difference is the diagnostic: a price
    # whose book last moved four hours ago but which we polled 30 seconds ago is
    # a DEAD MARKET, and every surface in this repo currently renders it as
    # fresh, because loop time was the only clock available.
    #
    # Deliberately None when the source did not give us one -- NOT defaulted to
    # captured_at. `snapshot_ts` above does fall back to captured_at and is kept
    # only for the consumers written against it; anything reasoning about
    # freshness must read this field and treat None as unknown. Falling back
    # here would silently recreate the exact conflation this exists to remove.
    "book_updated_at",
    "sport",
    "date",
    "kind",
    "event_id",
    "commence_time",
    "home_team",
    "away_team",
    "bookmaker",
    "market",
    "segment",
    "selection",
    "player_name",
    "line",
    "price",
)

# Identity of a quote across time. Everything that distinguishes one price from
# another EXCEPT the price and line themselves, which are what we watch move.
_KEY_FIELDS: tuple[str, ...] = (
    "sport",
    "kind",
    "event_id",
    "bookmaker",
    "segment",
    "market",
    "selection",
    "player_name",
    # `line` belongs here and its absence was a real defect (found by
    # test_line_selects_the_right_total, 2026-08-06). Alternate lines arrive as
    # separate outcomes in one payload, so without it FanDuel's total over 8.5
    # and over 9.0 shared a key and the within-call dedupe dropped the second as
    # a duplicate -- 6 rows considered, 5 appended. Totals 8.5 and 9.0 are
    # different bets, and collapsing them makes the best price across books a
    # comparison of prices for different wagers.
    #
    # Consequence worth knowing: a book MOVING its line now mints a new key
    # rather than updating one, so both observations persist. That is the right
    # behaviour for an append-only log -- movement is read off the time series,
    # not inferred from one mutating row.
    "line",
)


def book_quotes_path(sport: str, date_str: str) -> Path:
    """The WRITE path for a shard. Always the plain `.jsonl`.

    Deliberately not gzip-aware: `append_book_quotes` opens this in "a" mode and
    an append to a gzip member would produce a file that decompresses to the
    first member only. Compression happens to CLOSED shards (see
    `compress_closed_shards`); today's shard is always plain text.
    """
    slug = str(sport or "").strip().lower()
    return data_root() / f"{slug}_source" / "tracking" / "book_quotes" / f"{str(date_str).strip()}.jsonl"


def resolve_book_quotes_path(sport: str, date_str: str) -> Path:
    """The READ path: the plain shard if present, else its compressed form.

    Plain wins when both exist, which is the state during a compaction that has
    written the `.gz` but not yet removed the original. Reading the plain file
    there is not just a tiebreak -- it is the only one of the two guaranteed
    complete at that instant.
    """
    plain = book_quotes_path(sport, date_str)
    if plain.is_file():
        return plain
    packed = plain.with_name(plain.name + ".gz")
    if packed.is_file():
        return packed
    # Neither exists. Return the plain path so callers' `.is_file()` checks read
    # False against the name they expect in logs.
    return plain


def _state_path(sport: str, date_str: str) -> Path:
    return book_quotes_path(sport, date_str).with_suffix(".state.json")


def _open_book_quotes_text(path: Path):
    """Text-mode handle for a shard, transparently decompressing `.gz`.

    Streaming in both cases -- `gzip.open` inflates lazily, so a 5MB `.gz`
    holding 207MB of text still costs one buffer at a time, which is what makes
    `iter_book_quotes`' memory contract survive compression.
    """
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8")
    return path.open("r", encoding="utf-8")


def book_quotes_logical_bytes(path: Path) -> int:
    """UNCOMPRESSED size of a shard, in bytes.

    THIS IS A MEMORY GUARD INPUT, NOT A DISK FIGURE, and the distinction is the
    whole point. `book_quotes_read_affordable` multiplies shard size by 6.3 to
    project resident cost. Feeding it `st_size` for a compressed shard would
    under-report by the compression ratio -- measured 38.7x on
    mlb/2026-08-09 (207.4MB -> 5.4MB) -- so a shard that costs ~1.3GB resident
    would look like a 34MB one and sail through a guard built to stop exactly
    that. The guard would still be there, still be logging, and be blind in the
    one case that matters.

    gzip stores the uncompressed length in the last 4 bytes of the file (ISIZE),
    modulo 2^32. Shards are ~200MB so the modulo never bites, but a wrapped
    value would read as absurdly small -- the dangerous direction -- so it is
    sanity-checked against the compressed size and falls back to a conservative
    over-estimate rather than a permissive under-estimate.
    """
    try:
        stat = path.stat()
    except OSError:
        return 0
    if path.suffix != ".gz":
        return int(stat.st_size)
    try:
        with path.open("rb") as handle:
            handle.seek(-4, os.SEEK_END)
            isize = int.from_bytes(handle.read(4), "little")
    except Exception:
        isize = 0
    # A gzip member never expands, so uncompressed < compressed means ISIZE
    # wrapped (or the file is not what we think). Assume the worst plausible
    # ratio instead of trusting the small number.
    if isize < stat.st_size:
        return int(stat.st_size * _ASSUMED_GZIP_RATIO)
    return isize


# Only used when a gzip trailer cannot be trusted. Set well ABOVE the measured
# 38.7x so the fallback errs toward refusing a read, never toward admitting one
# that will not fit.
_ASSUMED_GZIP_RATIO = 50


def _coerce_price(value: Any) -> int | None:
    """American odds as an int. MLB's fetcher stores them as strings ("+410"),
    basketball's as ints, soccer's as floats -- normalise so a cross-sport
    consumer never has to care."""
    if value is None:
        return None
    text = str(value).strip().replace("+", "")
    if not text:
        return None
    try:
        return int(round(float(text)))
    except Exception:
        return None


def _coerce_line(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except Exception:
        return None


def _normalize(row: Mapping[str, Any], *, sport: str, date_str: str, captured_at: str) -> dict[str, Any] | None:
    bookmaker = str(row.get("bookmaker") or row.get("book") or "").strip().lower()
    market = str(row.get("market") or "").strip()
    if not bookmaker or not market:
        return None
    price = _coerce_price(row.get("price") if "price" in row else row.get("odds"))
    line = _coerce_line(row.get("line") if "line" in row else row.get("point"))
    # A row with neither a price nor a line records nothing about the market.
    if price is None and line is None:
        return None
    player = str(row.get("player_name") or row.get("player") or "").strip()
    # See QUOTE_FIELDS: this one stays None when the source has no book clock.
    book_updated_at = str(
        row.get("book_updated_at") or row.get("last_update") or row.get("snapshot_ts") or ""
    ).strip() or None
    out = {
        "captured_at": captured_at,
        "snapshot_ts": str(row.get("snapshot_ts") or row.get("last_update") or captured_at),
        "book_updated_at": book_updated_at,
        "sport": str(sport or "").strip().lower(),
        "date": str(date_str).strip(),
        "kind": str(row.get("kind") or ("prop" if player else "game")),
        "event_id": str(row.get("event_id") or "").strip() or None,
        "commence_time": str(row.get("commence_time") or "").strip() or None,
        "home_team": str(row.get("home_team") or "").strip() or None,
        "away_team": str(row.get("away_team") or "").strip() or None,
        "bookmaker": bookmaker,
        "market": market,
        "segment": str(row.get("segment") or "full").strip() or "full",
        "selection": str(row.get("selection") or row.get("side") or row.get("outcome_name") or "").strip() or None,
        "player_name": player or None,
        "line": line,
        "price": price,
    }
    return out


def _quote_key(row: Mapping[str, Any]) -> str:
    return "|".join(str(row.get(field) or "") for field in _KEY_FIELDS)


def _load_state(path: Path) -> dict[str, list[Any]]:
    try:
        if path.is_file():
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                return {str(key): list(value) for key, value in loaded.items() if isinstance(value, (list, tuple))}
    except Exception:
        pass
    return {}


def _write_state(path: Path, state: Mapping[str, Any]) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(state, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, path)


def quote_key(row: Mapping[str, Any]) -> str:
    """Public alias for the log's identity key, so consumers can join a grid
    cell back to `read_quote_last_seen()` without reaching into a private."""
    return _quote_key(row)


def read_quote_last_seen(sport: str, date_str: str) -> dict[str, str]:
    """`_quote_key` -> ISO timestamp we last OBSERVED that market.

    The companion to the change log. `book_age_seconds` and
    `capture_age_seconds` on a quote both answer "when did this price last
    MOVE"; this answers "when did we last look", and only the second one is a
    staleness measure. A market can be legitimately motionless for twelve hours
    and still be perfectly fresh.

    Empty for any date whose state file predates this (2-element entries), which
    is the correct degraded answer -- unknown, not zero, and callers must not
    read a missing entry as stale.
    """
    out: dict[str, str] = {}
    for key, value in _load_state(_state_path(sport, date_str)).items():
        if isinstance(value, (list, tuple)) and len(value) >= 3 and value[2]:
            out[str(key)] = str(value[2])
    return out


def append_book_quotes(
    *,
    sport: str,
    date_str: str,
    rows: Iterable[Mapping[str, Any]],
    captured_at: str,
    publish: bool = True,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Append every quote whose (line, price) differs from that key's last
    observation. Never raises: a quotes-log failure must not fail an odds
    refresh, exactly as the #207 diagnostic must not.

    `extra` stamps constant fields onto every row -- soccer's `league`, which is
    the one dimension a single `sport` slug cannot express, since all eight
    leagues share the `soccer_source` tree.
    """
    try:
        path = book_quotes_path(sport, date_str)
        path.parent.mkdir(parents=True, exist_ok=True)
        state_path = _state_path(sport, date_str)
        state = _load_state(state_path)

        appended: list[dict[str, Any]] = []
        seen_this_call: set[str] = set()
        considered = 0
        observed = 0
        for raw in rows or ():
            if not isinstance(raw, Mapping):
                continue
            considered += 1
            normalized = _normalize(raw, sport=sport, date_str=date_str, captured_at=captured_at)
            if normalized is None:
                continue
            for field, value in (extra or {}).items():
                normalized.setdefault(str(field), value)
            key = _quote_key(normalized)
            # Two books can legitimately post the same key twice in one payload
            # (alternate lines arrive as separate outcomes); keep the first.
            if key in seen_this_call:
                continue
            seen_this_call.add(key)
            observed += 1
            previous = state.get(key) or []
            current = [normalized.get("line"), normalized.get("price")]
            # LAST-SEEN, third slot. This log is a CHANGE log by design: a price
            # that has not moved writes no row, so the newest row for a key keeps
            # its ORIGINAL `book_updated_at` and `captured_at`. Both age fields
            # downstream are therefore "time since this price last MOVED", not
            # "time since we last LOOKED" -- and nothing recorded the latter at
            # all, so a stable market and a market we stopped observing were
            # indistinguishable.
            #
            # That is what made the served board look 11.9h stale: measured
            # 2026-08-08, all 100 MLB rows carried book ages inside a 1.2-minute
            # window ~11.9h wide, growing with wall-clock across rebuilds of a
            # 1.4-minute-old artifact. Not a capture outage -- the change log
            # working exactly as specified, read as if it were a freshness clock.
            #
            # Kept as a third element rather than a dict so every existing
            # 2-element state file still loads and compares correctly: the
            # equality check below slices to the first two.
            if list(previous[:2]) == current:
                state[key] = current + [captured_at]
                continue
            state[key] = current + [captured_at]
            appended.append(normalized)

        if appended:
            with path.open("a", encoding="utf-8") as handle:
                for row in appended:
                    handle.write(json.dumps(row, separators=(",", ":")) + "\n")
        # Written whenever anything was OBSERVED, not only when something
        # changed. Previously this was inside `if appended`, so a refresh that
        # confirmed every price unchanged left no trace it had run -- which is
        # precisely the evidence needed to tell "stable" from "stopped looking".
        if appended or observed:
            _write_state(state_path, state)

        result = {
            "path": str(path),
            "considered": int(considered),
            "appended": int(len(appended)),
            "tracked_keys": int(len(state)),
            "books": sorted({str(row.get("bookmaker")) for row in appended}),
        }
        published = None
        if publish and appended:
            try:
                from syndicate.features.shared.artifact_publisher import publish_hot_artifact

                published = publish_hot_artifact(path)
            except Exception as exc:
                published = f"failed {type(exc).__name__}: {exc}"
        result["published"] = published
        print(f"[odds_book_quotes] {json.dumps(result, sort_keys=True)}", flush=True)
        return result
    except Exception as exc:
        print(f"[odds_book_quotes] FAILED sport={sport} date={date_str} error={type(exc).__name__}: {exc}", flush=True)
        return {"error": f"{type(exc).__name__}: {exc}", "appended": 0}


def quote_rows_from_oddsapi_events(
    events: Iterable[Mapping[str, Any]],
    *,
    market_map: Mapping[str, str] | None = None,
    segment: str = "full",
) -> list[dict[str, Any]]:
    """Flatten the standard OddsAPI `event -> bookmakers -> markets -> outcomes`
    nesting into quote rows, keeping EVERY book.

    Shared by the fetchers whose only book-handling code is a
    `_choose_bookmaker` that returns one book and drops the rest -- NFL props,
    NFL team odds and NCAAF props all carry a byte-identical copy of that
    function (#209 Class A). They keep their single-book CSV; this gives the
    quote log the other four-to-seven books the same paid-for response already
    contained.

    `market_map` restricts and renames markets (the caller's own canonical
    names); omit it to keep every market under its raw OddsAPI key.

    A market_map VALUE MAY BE `(segment, market_name)` INSTEAD OF A STRING
    (`#343`). That is how every sport other than MLB gets interval capture: the
    OddsAPI key already says which interval it is -- `totals_q1`, `h2h_1st_5_innings`
    -- so the segment is derivable per market rather than fixed per call, and
    `market_segments.segment_market_keys()` hands the caller exactly this shape.

    The `segment=` argument stays as the default for string-valued entries, so
    existing callers are unaffected. It is deliberately NOT the fallback for a
    tuple entry: a caller that requests `totals_q1` and then tags it `full`
    would show a first-quarter total as a full-game line, which is worse than
    never asking.
    """
    rows: list[dict[str, Any]] = []
    for event in events or ():
        if not isinstance(event, Mapping):
            continue
        home_team = str(event.get("home_team") or "").strip()
        away_team = str(event.get("away_team") or "").strip()
        event_id = str(event.get("id") or event.get("event_id") or "").strip() or None
        commence_time = event.get("commence_time")
        for bookmaker in (event.get("bookmakers") or []):
            if not isinstance(bookmaker, Mapping):
                continue
            book_key = str(bookmaker.get("key") or bookmaker.get("title") or "").strip()
            if not book_key:
                continue
            for market in (bookmaker.get("markets") or []):
                if not isinstance(market, Mapping):
                    continue
                raw_key = str(market.get("key") or "").strip()
                row_segment = segment
                if market_map is not None:
                    if raw_key not in market_map:
                        continue
                    mapped = market_map[raw_key]
                    if isinstance(mapped, (tuple, list)) and len(mapped) == 2:
                        row_segment = str(mapped[0] or "full")
                        market_name = str(mapped[1])
                    else:
                        market_name = str(mapped)
                else:
                    market_name = raw_key
                if not market_name:
                    continue
                for outcome in (market.get("outcomes") or []):
                    if not isinstance(outcome, Mapping):
                        continue
                    name = str(outcome.get("name") or "").strip()
                    description = str(outcome.get("description") or "").strip()
                    lowered = name.lower()
                    if lowered.startswith("over"):
                        selection = "over"
                    elif lowered.startswith("under"):
                        selection = "under"
                    elif home_team and name == home_team:
                        selection = "home"
                    elif away_team and name == away_team:
                        selection = "away"
                    else:
                        selection = lowered or None
                    # For player markets OddsAPI puts the player in
                    # `description` and the side in `name`; for team markets
                    # `description` is absent and `name` IS the team.
                    player = description if description and description not in {home_team, away_team} else ""
                    rows.append(
                        {
                            "kind": "prop" if player else "game",
                            "event_id": event_id,
                            "commence_time": commence_time,
                            "home_team": home_team or None,
                            "away_team": away_team or None,
                            "bookmaker": book_key,
                            "market": market_name,
                            "segment": row_segment,
                            "selection": selection,
                            "player_name": player or None,
                            "line": outcome.get("point"),
                            "price": outcome.get("price"),
                            "snapshot_ts": market.get("last_update") or bookmaker.get("last_update"),
                        }
                    )
    return rows


# #252. Identity-keyed cache for the parsed shard.
#
# This function had NO cache and exactly one caller -- quote_ref_for_bet, as its
# FIRST statement -- and that caller runs inside a `for row in rows:` loop at
# three sites in quote_enrichment.py. So every enriched row re-read and
# re-parsed the whole shard. MLB's is 90,155,656 bytes / ~122k rows, and a board
# build enriches ~200 candidates: ~200 complete materialisations of a 122k-dict
# list, per build. `_QUOTE_CACHE_KEY` in quote_enrichment.py has been declared
# and unused since #215 -- the original author anticipated exactly this.
#
# That is the mechanism behind refresh-worker's OOM curve: MLB's hydrated
# overview measured +2.9GB in 73s (2026-08-07) that never came back down.
# Nothing was retained -- hundreds of large short-lived allocations fragment
# pymalloc arenas and glibc does not return them to the OS, so `anon` ratchets
# and looks exactly like a leak. This is also why tracemalloc could never see
# it: each parse is freed before the next begins, so PEAK barely moves while
# RSS climbs (see handoff_refresh_worker_oom.md's methodology note).
#
# Keyed on (path, mtime_ns, size), not a TTL, so a rewritten or appended shard
# invalidates itself and a stale copy can never be served. The mtime-churn trap
# that defeated _JSONL_ROWS_CACHE for odds_events does NOT apply here: on
# refresh-worker this file is mutated only by the artifact pull, which runs
# before the board build, so the shard is stable for the whole build.
#
# BOUNDED BY BYTES, NOT BY ENTRY COUNT.
#
# This was `_BOOK_QUOTES_CACHE_MAX_ENTRIES = 2` -- "one live sport plus one".
# That is a COUNT bound on a value whose size varies by two orders of magnitude
# between sports, and the postmortem's rule for worker caches is explicit:
# "any worker cache gets a byte budget and an eviction log, never a bare entry
# count." `_MLB_CARDS_CONTEXT_CACHE_MAX_ENTRIES` was the same shape and stayed
# invisible for three weeks.
#
# WHY IT MATTERED. Two entries was sized on refresh-worker (4Gi). MEASURED
# 2026-08-08, live-odds-worker (2Gi) died with:
#
#     PEAK rss 1768MB against a 2048MB limit, lethal ~1548MB
#       pid=39  1004.7MB  run_live_odds_refresh_worker.py   <- the parent
#       pid=557  636.8MB  refresh_mlb_oddsapi.py            <- spawned refresh
#
# A read costs ~6.3x the shard's file size and is never returned to the OS
# (postmortem section 1.1d, reproduced independently 2026-08-08). Production's
# MLB shard is ~90MB, so ONE cached copy is ~570MB and two is ~1.14GB -- which
# is essentially the whole parent. On a 4Gi worker that is affordable; on a 2Gi
# service it leaves under 1GB for a subprocess that needs 640MB.
#
# WHAT EVICTION ACTUALLY BUYS, stated precisely because the obvious reading is
# wrong: freeing an entry does NOT return memory to the OS. It lets the next
# read REUSE those arenas instead of growing new ones, so the retained set
# plateaus at roughly one shard rather than two. The win is the plateau, not a
# reclaim -- do not expect RSS to drop when an eviction is logged.
#
# The budget is an ESTIMATE from file size, not sys.getsizeof: a shallow sizeof
# on a 122k-dict list undercounts badly, and the file size is already in the
# cache key, so this costs nothing.
_BOOK_QUOTES_CACHE: "OrderedDict[tuple[str, int, int], list[dict[str, Any]]]" = OrderedDict()

# Which key resolved each `quote_ref_for_bet` call, and how many rows it had to
# walk to find out. Counted PER CALL, never per row: the loop below runs ~122k
# times per candidate and an increment inside it would be part of the cost it is
# supposed to measure.
#
# The reason-split is the point, not the total. `event` is the cheap key;
# `teams` means the cheap key missed and every row fell through to alias
# resolution. A join can fail the same way silently (a null) or expensively (a
# full scan), and only the by-reason count distinguishes "the join is broken"
# from "the key is wrong" -- which is also what makes it a regression guard
# after any fix, not just a diagnostic before one.
_QUOTE_JOIN_STATS: dict[str, int] = {}


def reset_quote_join_stats() -> dict[str, int]:
    """Return the counts so far and start a fresh window."""
    snapshot = dict(_QUOTE_JOIN_STATS)
    _QUOTE_JOIN_STATS.clear()
    return snapshot


def _bump(key: str, amount: int = 1) -> None:
    _QUOTE_JOIN_STATS[key] = _QUOTE_JOIN_STATS.get(key, 0) + amount

# Measured multiplier from file bytes to resident bytes (6.3x, twice).
_BOOK_QUOTES_RSS_PER_FILE_BYTE = 6.3

# Sized for the SMALLEST container that runs this, not the largest -- 2Gi.
# Post-restart that service sits at ~426MB with the subprocess absent, and the
# MLB odds refresh needs ~640MB, so the parent must stay under roughly 900MB to
# survive it. That leaves ~500MB for this cache, which admits one MLB shard and
# evicts anything beyond it.
_BOOK_QUOTES_CACHE_MAX_RSS_BYTES = 500 * 1024 * 1024


def book_quotes_read_affordable(sport: str, date_str: str) -> tuple[bool, dict[str, Any]]:
    """Can THIS process afford to read this shard, or must the caller degrade?

    Measured 2026-08-10. `/api/board/book-grid` took 22.2s and returned 2.69MB,
    and web OOM-killed twice within ~60s of a call -- once on the user's own
    session, once on mine. The arithmetic is not close:

        web container                 2Gi
        WEB_CONCURRENCY               2 gunicorn workers, EACH with its own cache
        production MLB shard          ~90MB on disk
        resident cost                 x6.3 = ~570MB, never returned to the OS
        two workers holding one each  ~1.14GB
        + web baseline                ~426MB
                                      ~1.57GB   vs lethal ~1.55GB

    The existing 500MB budget is correct and was reasoned for live-odds-worker,
    which runs ONE process. Web runs `WEB_CONCURRENCY` of them, so the effective
    ceiling per process is that budget divided by the worker count -- and the
    eviction loop keeps `len > 1`, so one shard stays resident BETWEEN requests
    and the second caller lands on an already-loaded box.

    Returns (affordable, facts). `facts` is what the caller shows the user
    instead of dying: a degraded board that explains itself beats a 24-second
    outage every time someone opens the page. That is `CLAUDE.md`'s rule -- if
    data is missing at request time the correct behaviour is a degraded state,
    not an on-request backfill -- applied to "too expensive" as well as
    "absent".
    """
    path = resolve_book_quotes_path(sport, date_str)
    # LOGICAL, not on-disk. A compressed shard costs its UNCOMPRESSED size in
    # this projection -- see book_quotes_logical_bytes for why using st_size
    # here would silently disarm this guard.
    file_bytes = book_quotes_logical_bytes(path) if path.is_file() else 0
    try:
        workers = max(1, int(str(os.environ.get("WEB_CONCURRENCY") or "1").strip() or "1"))
    except ValueError:
        workers = 1
    per_process_budget = int(_BOOK_QUOTES_CACHE_MAX_RSS_BYTES / workers)
    projected = int(file_bytes * _BOOK_QUOTES_RSS_PER_FILE_BYTE)
    facts = {
        "shard_bytes": file_bytes,
        "projected_resident_bytes": projected,
        "per_process_budget_bytes": per_process_budget,
        "web_concurrency": workers,
        "multiplier": _BOOK_QUOTES_RSS_PER_FILE_BYTE,
    }
    # A shard already in cache costs nothing more to read -- refusing then would
    # degrade the board for no memory saved.
    cache_key = _book_quotes_cache_key(path)
    if cache_key is not None and cache_key in _BOOK_QUOTES_CACHE:
        facts["already_cached"] = True
        return True, facts
    affordable = projected <= per_process_budget
    if not affordable:
        print(
            f"[odds_book_quotes] BOOK_QUOTES_READ_REFUSED sport={sport} date={date_str} "
            f"shard_mb={file_bytes / (1024 * 1024):.1f} projected_mb={projected / (1024 * 1024):.1f} "
            f"budget_mb={per_process_budget / (1024 * 1024):.1f} web_concurrency={workers}",
            flush=True,
        )
    return affordable, facts


def _book_quotes_cache_estimated_bytes() -> int:
    """Estimated resident cost of everything currently cached.

    The third element of each key is the shard's file size, so this needs no
    measurement pass over the values.
    """
    return int(sum(key[2] for key in _BOOK_QUOTES_CACHE) * _BOOK_QUOTES_RSS_PER_FILE_BYTE)


def _evict_book_quotes_over_budget() -> None:
    """Evict least-recently-used until the estimate is within budget.

    Logged, per the same rule: a cache that evicts silently cannot be
    distinguished from one that is simply never hit, and "is the cache
    working?" then has no answer short of a heap dump.
    """
    while len(_BOOK_QUOTES_CACHE) > 1 and _book_quotes_cache_estimated_bytes() > _BOOK_QUOTES_CACHE_MAX_RSS_BYTES:
        evicted_key, _ = _BOOK_QUOTES_CACHE.popitem(last=False)
        print(
            "[odds_book_quotes] CACHE_EVICT "
            + json.dumps(
                {
                    "evicted_path": str(evicted_key[0]),
                    "evicted_file_bytes": int(evicted_key[2]),
                    "entries_after": len(_BOOK_QUOTES_CACHE),
                    "estimated_rss_mb_after": round(_book_quotes_cache_estimated_bytes() / (1024 * 1024), 1),
                    "budget_mb": round(_BOOK_QUOTES_CACHE_MAX_RSS_BYTES / (1024 * 1024), 1),
                },
                sort_keys=True,
            ),
            flush=True,
        )


def _book_quotes_cache_key(path: Path) -> tuple[str, int, int] | None:
    """(path, mtime_ns, LOGICAL bytes).

    The third element is consumed by `_book_quotes_cache_estimated_bytes` as a
    resident-cost proxy, so it has to be the uncompressed size for the same
    reason the affordability guard does -- a `.gz` entry keyed by its on-disk
    size would let the cache hold ~39x what its budget believes, and the
    eviction loop would never fire.

    Identity is still (path, mtime, size): a `.gz` and its plain original are
    different paths, so a compaction can never serve a stale entry under the
    new name.
    """
    try:
        stat = path.stat()
    except Exception:
        return None
    return (str(path), stat.st_mtime_ns, book_quotes_logical_bytes(path))


def iter_book_quotes(sport: str, date_str: str) -> Iterator[dict[str, Any]]:
    """Stream a shard's rows one at a time. NOT cached, by design (`#331`).

    `read_book_quotes` returns -- and caches -- the whole list, which is right
    for callers that scan a shard repeatedly inside one request. It is wrong for
    the book-grid pivot: that reads a shard ONCE per tick, and holding 478,782
    parsed dicts (measured 2026-08-09, MLB) costs ~1.3GB that the cache then
    keeps alive afterwards.

    Yielding leaves peak memory to whatever the CONSUMER retains, so pairing
    this with `freshest_rows_for_grid` bounds the pivot by market count instead
    of by quote-event count.

    Partial reads are not swallowed. A transient IO error mid-file raises here
    rather than silently ending the iteration, because a short read that looks
    like a complete one would make a truncated board indistinguishable from a
    quiet one -- the same failure `read_book_quotes` avoids by not caching a
    partial result.
    """
    path = resolve_book_quotes_path(sport, date_str)
    if not path.is_file():
        return
    with _open_book_quotes_text(path) as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except Exception:
                continue
            if isinstance(parsed, dict):
                yield parsed


def read_book_quotes(sport: str, date_str: str) -> list[dict[str, Any]]:
    """Every parsed row of a sport/date book-quotes shard.

    Returns the CACHED list itself, not a copy: a defensive copy of 122k dicts
    per call would reintroduce most of the allocation cost this cache exists to
    remove. Every caller in the tree treats these rows as read-only (they filter
    and `dict(...)` the few they keep), which is the contract that makes that
    safe -- do not mutate the returned rows in place.
    """
    path = resolve_book_quotes_path(sport, date_str)
    cache_key = _book_quotes_cache_key(path)
    if cache_key is not None:
        cached = _BOOK_QUOTES_CACHE.get(cache_key)
        if cached is not None:
            _BOOK_QUOTES_CACHE.move_to_end(cache_key)
            return cached

    rows: list[dict[str, Any]] = []
    try:
        if not path.is_file():
            return rows
        with _open_book_quotes_text(path) as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    parsed = json.loads(line)
                except Exception:
                    continue
                if isinstance(parsed, dict):
                    rows.append(parsed)
    except Exception:
        # Deliberately NOT cached: a partial read from a transient IO error must
        # not become the answer every subsequent caller gets until the file
        # changes again.
        return rows

    if cache_key is not None:
        # Re-stat and only cache when the file has not changed underneath the
        # read. An append during parsing would otherwise be cached under the
        # pre-read identity and served as complete until the NEXT change.
        if _book_quotes_cache_key(path) == cache_key:
            _BOOK_QUOTES_CACHE[cache_key] = rows
            _BOOK_QUOTES_CACHE.move_to_end(cache_key)
            # Never evicts the entry just inserted (the loop keeps at least one):
            # a shard larger than the whole budget must still be served from
            # cache for the duration of THIS build, or we reintroduce the
            # per-row re-read that #252 exists to stop.
            _evict_book_quotes_over_budget()
    return rows


def closing_quotes(rows: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """The last observation of each quote key strictly before its own
    commence_time -- the textbook closing line, as a lookup rather than the
    transition-stamp inference `odds_refresh_tracking` has to make.

    Rows whose commence_time is missing or unparseable are skipped rather than
    guessed at: #82's rule, and the reason the existing stamp deliberately
    leaves closing_line unset instead of recording an in-play number.
    """
    best: dict[str, dict[str, Any]] = {}
    for row in rows or ():
        if not isinstance(row, Mapping):
            continue
        commence = str(row.get("commence_time") or "").strip()
        observed = str(row.get("snapshot_ts") or row.get("captured_at") or "").strip()
        if not commence or not observed:
            continue
        if observed >= commence:
            continue
        key = _quote_key(row)
        previous = best.get(key)
        if previous is None or observed > str(previous.get("snapshot_ts") or previous.get("captured_at") or ""):
            best[key] = dict(row)
    return best


def best_price_by_market(rows: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Best available American price per (event, market, segment, selection,
    player, line), across books -- the join #206 wanted for re-grading and could
    not do while only one book survived capture.

    "Best" is the highest payout for the bettor: for positive American odds the
    larger number, for negative the one closer to zero. Comparing raw ints gets
    that right in both cases, which is the one thing worth stating explicitly
    since it looks like it should need a branch.
    """
    best: dict[str, dict[str, Any]] = {}
    for row in rows or ():
        if not isinstance(row, Mapping):
            continue
        price = row.get("price")
        if price is None:
            continue
        key = "|".join(
            str(row.get(field) or "")
            for field in ("sport", "kind", "event_id", "segment", "market", "selection", "player_name", "line")
        )
        previous = best.get(key)
        if previous is None or int(price) > int(previous.get("price") or -10**9):
            best[key] = dict(row)
    return best


def market_key_for_quote(row: Mapping[str, Any]) -> str:
    """The cross-book identity of a market: everything except which book quoted
    it. Same key `best_price_by_market` groups on, exposed so callers can look a
    market up without reimplementing (and drifting from) the field list."""
    return "|".join(
        str(row.get(field) or "")
        for field in ("sport", "kind", "event_id", "segment", "market", "selection", "player_name", "line")
    )


def _age_seconds(timestamp: Any, *, now: datetime) -> int | None:
    text = str(timestamp or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max(0, int((now - parsed).total_seconds()))


def _implied_probability(price: int) -> float:
    return (100.0 / (price + 100.0)) if price > 0 else (abs(price) / (abs(price) + 100.0))


# Both sides of a book's own market must be observed within this window to be
# de-vigged together. Generous enough for a quiet pregame market, far tighter
# than the hours that separate a stale leg from a live one.
_FAIR_PAIR_TOLERANCE_S = 600.0
# Below this the "market" contains a dead leg rather than an opportunity.
_IMPLAUSIBLE_HOLD_PCT = -5.0


def _epoch_seconds(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def _line_value(row: Mapping[str, Any]) -> float | None:
    try:
        value = float(row.get("line"))
    except (TypeError, ValueError):
        return None
    return None if value != value else value  # NaN is written for line-less markets


def market_sides_for_quote(
    rows: Iterable[Mapping[str, Any]], chosen: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Every side of the ONE market `chosen` belongs to (#238).

    Needed because a fair (no-vig) probability cannot be derived from one side.
    `market_key_for_quote` deliberately includes `selection`, so over and under
    are different keys; this is its counterpart -- same market instance, all
    sides.

    The line rule is where this gets got wrong, and it is not a detail:
      - over/under share a line (both sit on 8.5);
      - spreads are SIGNED per side, so home -1.5 pairs with away **+1.5**.
        Pairing on an equal line manufactured 716 "arbitrages" out of bets that
        are not opposite sides of anything (measured 2026-08-06);
      - h2h has no line at all, and its 3-way form has a draw leg that must be
        included or the sides sum to less than a market and the "fair" price is
        wrong in the bettor's favour -- the most dangerous direction.
    """
    base = tuple(
        str(chosen.get(field) or "")
        for field in ("sport", "kind", "event_id", "segment", "market", "player_name")
    )
    chosen_line = _line_value(chosen)
    chosen_selection = str(chosen.get("selection") or "").strip().lower()
    sides: list[dict[str, Any]] = []
    for row in rows or ():
        if not isinstance(row, Mapping) or row.get("price") is None:
            continue
        if tuple(str(row.get(field) or "") for field in
                 ("sport", "kind", "event_id", "segment", "market", "player_name")) != base:
            continue
        line = _line_value(row)
        if chosen_line is None:
            if line is not None:
                continue
        elif line is None:
            continue
        else:
            expected = _expected_line_for_side(
                chosen_line, chosen_selection, str(row.get("selection") or "").strip().lower()
            )
            if expected is None or abs(line - expected) > 1e-9:
                continue
        sides.append(dict(row))
    return sides


# Sides whose handicap MIRRORS. Everything else (over/under, and any pairing we
# have not measured) shares one line.
_MIRRORED_SIDES = frozenset({"away", "home"})


def _expected_line_for_side(
    chosen_line: float, chosen_selection: str, selection: str
) -> float | None:
    """The line `selection` must sit on to belong to `chosen`'s market instance.

    #262. The previous rule accepted "the same line OR its mirror" without
    checking WHICH SIDE was on which. For an anchor of `away +1.5` that admits
    all four of {away +1.5, home -1.5, away -1.5, home +1.5} -- but those are
    TWO different markets, and the caller then keeps one quote per (book, side)
    across both of them.

    Measured on production 2026-08-07 (`spreads_alt`, first5, one row):

        betmgm     away -1.5 (+210)   home +1.5 (-295)
        betrivers  away +1.5 (-240)   home -1.5 (+180)

    so `best.away` ranked a -1.5 bet against a +1.5 bet as if interchangeable,
    and the no-vig fair value derived from those sides was computed across two
    markets. The docstring above already said "spreads are SIGNED per side"; the
    code only checked the magnitude.

    Returns None when the side is unusable, so the caller drops the row rather
    than guessing.
    """
    if not selection:
        return None
    if selection == chosen_selection:
        return chosen_line
    if {selection, chosen_selection} == _MIRRORED_SIDES:
        return -chosen_line
    return chosen_line


def _fair_value_fields(
    market_sides: Iterable[Mapping[str, Any]],
    *,
    selection: Any,
    price: int,
    best_price: int,
) -> dict[str, Any]:
    """No-vig fair probability for `selection`, plus what it implies (#238)."""
    from syndicate.features.shared.opportunity_signals import (
        american_price,
        consensus_fair_probability,
        expected_value_pct,
        hold_pct,
    )

    freshest: dict[tuple[str, str], tuple[str, int]] = {}
    for row in market_sides or ():
        book = str(row.get("bookmaker") or "")
        sel = str(row.get("selection") or "")
        if not book or not sel:
            continue
        observed = str(row.get("book_updated_at") or row.get("snapshot_ts") or row.get("captured_at") or "")
        previous = freshest.get((book, sel))
        if previous is None or observed >= previous[0]:
            try:
                freshest[(book, sel)] = (observed, int(row["price"]))
            except (TypeError, ValueError, KeyError):
                continue

    by_book: dict[str, dict[str, int]] = {}
    for (book, sel), (_observed, book_price) in freshest.items():
        by_book.setdefault(book, {})[sel] = book_price

    # SIMULTANEITY. The shard is an append-only log over the whole day including
    # live play, so a book's "latest" over can be hours away from its latest
    # under. De-vigging those together is not de-vigging a market, it is mixing
    # two game states -- and it does not fail quietly: on production rows this
    # produced Myles Straw at -33% hold / +135% EV and Max Clark at -18% / +47%,
    # numbers that would have gone straight to the top of the board.
    for book in list(by_book):
        stamps = [
            _epoch_seconds(freshest[(book, sel)][0])
            for sel in by_book[book]
            if (book, sel) in freshest
        ]
        usable = [stamp for stamp in stamps if stamp is not None]
        if len(usable) != len(by_book[book]) or (usable and max(usable) - min(usable) > _FAIR_PAIR_TOLERANCE_S):
            del by_book[book]

    wanted = str(selection or "")
    consensus = consensus_fair_probability(by_book)
    if not consensus or wanted not in consensus:
        return {"fair_probability": None, "fair_price": None, "hold_pct": None, "sides_quoted": 0}

    fair = consensus[wanted]
    # Hold is quoted from the BEST price on each side -- the market a bettor who
    # shops can actually get, not any single book's margin.
    best_by_selection: dict[str, int] = {}
    for (_book, sel), (_observed, book_price) in freshest.items():
        current = best_by_selection.get(sel)
        if current is None or _implied_probability(book_price) < _implied_probability(current):
            best_by_selection[sel] = book_price

    hold = hold_pct(list(best_by_selection.values()))
    # A genuine arbitrage is SMALL -- the one real arb measured in production was
    # -0.97%. A double-digit negative hold is not a gift, it is a dead leg on one
    # side, and publishing the fair price derived from it would put the most
    # wrong rows at the very top of the board (EV ranks descending).
    if hold is not None and hold < _IMPLAUSIBLE_HOLD_PCT:
        return {"fair_probability": None, "fair_price": None, "hold_pct": None, "sides_quoted": 0}

    return {
        "fair_probability": round(fair, 6),
        "fair_price": american_price(fair),
        "hold_pct": hold,
        "sides_quoted": len(consensus),
        "ev_pct": expected_value_pct(price, fair),
        "best_ev_pct": expected_value_pct(best_price, fair),
    }


def quote_ref(
    quotes_for_market: Iterable[Mapping[str, Any]],
    *,
    chosen_bookmaker: str | None = None,
    now: datetime | None = None,
    market_sides: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """The board/ledger-facing description of a price: which book, what number,
    when that book moved it, and how it compares to everyone else quoting it.

    This is the object the read path never had. A Layer 2 candidate row is built
    from display_pick/ev_pct/p_win/market_label/selection and carries no price,
    no book and no timestamp -- which is why "which book has the edge" had
    nowhere to live and CLV had no opening price to record.

    `consensus_price` is here on purpose and matters as much as `price`. A best
    price 40 points clear of every other book is usually a stale or erroneous
    line rather than an edge; `price_rank: 1` alone is not evidence, and
    `price_rank: 1` against a tight consensus of six books is. Surfacing rank
    without consensus would invite exactly the wrong read.

    Pass `chosen_bookmaker` to describe a price we actually took (a logged bet);
    omit it to describe the best available.
    """
    rows = [row for row in (quotes_for_market or ()) if isinstance(row, Mapping) and row.get("price") is not None]
    if not rows:
        return None
    now = now or datetime.now(timezone.utc)

    ranked = sorted(rows, key=lambda row: int(row["price"]), reverse=True)
    chosen = None
    if chosen_bookmaker:
        wanted = str(chosen_bookmaker).strip().lower()
        chosen = next((row for row in ranked if str(row.get("bookmaker") or "").lower() == wanted), None)
    if chosen is None:
        chosen = ranked[0]

    price = int(chosen["price"])
    # Mean implied probability across books, converted back to a price-like
    # number. Averaging American odds directly is meaningless (the scale is
    # discontinuous at +/-100); averaging implied probability is not.
    #
    # Owned by `opportunity_signals` since 2026-08-15. This was hand-rolled here
    # AND in `book_grid`, and both copies disagreed with the owning converter at
    # the boundary (-100 vs +100 at exactly even money; ZeroDivisionError where
    # `american_price` refuses). Note this is the VIGGED average -- the no-vig
    # fair for the same market is `fair_fields` immediately below, and the two
    # must never be read as the same number.
    consensus_price = consensus_vigged_price(row["price"] for row in ranked)

    # #238: no-vig fair value, when the opposing side(s) were supplied. Absent
    # rather than guessed when they were not -- a one-sided "fair" price is just
    # the vigged price with a reassuring name on it.
    fair_fields = (
        _fair_value_fields(
            market_sides,
            selection=chosen.get("selection"),
            price=price,
            best_price=int(ranked[0]["price"]),
        )
        if market_sides is not None
        else {}
    )

    return {
        "bookmaker": chosen.get("bookmaker"),
        "price": price,
        "line": chosen.get("line"),
        **fair_fields,
        "book_updated_at": chosen.get("book_updated_at"),
        "captured_at": chosen.get("captured_at"),
        "book_age_seconds": _age_seconds(chosen.get("book_updated_at"), now=now),
        "capture_age_seconds": _age_seconds(chosen.get("captured_at"), now=now),
        "price_rank": ranked.index(chosen) + 1,
        "books_quoting": len(ranked),
        "best_price": int(ranked[0]["price"]),
        "best_bookmaker": ranked[0].get("bookmaker"),
        "consensus_price": consensus_price,
        # Absent, not zero, when the consensus refused -- a 0.0 would read as
        # "the best price IS the consensus", the opposite of "no consensus".
        "edge_vs_consensus_pct": (
            round((_implied_probability(consensus_price) - _implied_probability(price)) * 100, 2)
            if consensus_price is not None
            else None
        ),
        "alternatives": [
            {"bookmaker": row.get("bookmaker"), "price": int(row["price"]), "line": row.get("line")}
            for row in ranked
        ],
    }


def _normalize_token(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().replace("_", " ").replace("-", " ").split())


# `#414`. The identity scan was the whole board-build cost, measured rather than
# guessed: eight production samples fit `total_s = 19.86s per million rows
# walked`, intercept -1.07s, R^2 = 0.918. Every call walked the full shard
# (82,956-85,948 rows), because identity was decided by a linear pass.
#
# WHY AN INDEX IS SAFE HERE, INCLUDING FOR TEAMS. `event_id` and `player_name`
# are exact-token compares, so they are ordinary dict keys. Teams are NOT --
# `_row_teams_match` delegates to the per-sport alias maps, and "chc" vs
# "chicago cubs" is exactly the gap that made a pure string heuristic fail
# (0 of 108 candidates priced, 2026-08-06). But that predicate reads ONLY
# `row["home_team"]` and `row["away_team"]`, so two rows carrying the same pair
# can never disagree. A shard holds ~15 distinct pairs against ~83k rows, so the
# fuzzy matcher runs once per PAIR instead of once per ROW, with identical
# results. Nothing about identity is loosened.
#
# Lifetime is tied to the rows cache by construction: same key, and any key not
# present in `_BOOK_QUOTES_CACHE` is dropped. The index can never outlive or
# disagree with the rows it describes, so a compaction or mtime change
# invalidates both together. It stores row POSITIONS, not rows.
_BOOK_QUOTES_INDEX_CACHE: "OrderedDict[tuple[str, int, int], dict[str, Any]]" = OrderedDict()


def _build_quote_shard_index(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_event: dict[str, list[int]] = {}
    by_player: dict[str, list[int]] = {}
    team_groups: dict[tuple[str, str], list[int]] = {}
    for position, row in enumerate(rows):
        event_token = _normalize_token(row.get("event_id"))
        if event_token:
            by_event.setdefault(event_token, []).append(position)
        player_token = _normalize_token(row.get("player_name"))
        if player_token:
            by_player.setdefault(player_token, []).append(position)
        pair = (str(row.get("home_team") or ""), str(row.get("away_team") or ""))
        if pair != ("", ""):
            team_groups.setdefault(pair, []).append(position)
    return {"by_event": by_event, "by_player": by_player, "team_groups": team_groups}


def _quote_shard_index(rows: list[dict[str, Any]], cache_key: tuple[str, int, int] | None) -> dict[str, Any]:
    if cache_key is None:
        # Unkeyable path (missing file stat). Build once, do not cache -- an
        # unkeyed entry could never be invalidated.
        return _build_quote_shard_index(rows)
    cached = _BOOK_QUOTES_INDEX_CACHE.get(cache_key)
    if cached is not None:
        _BOOK_QUOTES_INDEX_CACHE.move_to_end(cache_key)
        return cached
    index = _build_quote_shard_index(rows)
    _BOOK_QUOTES_INDEX_CACHE[cache_key] = index
    for stale in [key for key in _BOOK_QUOTES_INDEX_CACHE if key not in _BOOK_QUOTES_CACHE]:
        _BOOK_QUOTES_INDEX_CACHE.pop(stale, None)
    return index


def quote_ref_for_bet(
    *,
    sport: Any,
    date_str: Any,
    event_id: Any = None,
    market: Any = None,
    selection: Any = None,
    line: Any = None,
    player_name: Any = None,
    bookmaker: Any = None,
    home_team: Any = None,
    away_team: Any = None,
    matchup: Any = None,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Resolve the quote a bet was struck against.

    IDENTITY IS A HARD FILTER. An earlier version narrowed progressively with a
    `narrowed or candidates` fallback at every step, so a bet whose event did
    not match simply fell through to the whole day's rows and came back with
    some *other* game's price. That is strictly worse than returning nothing:
    a missing quote is visibly missing, a wrong one silently misprices the card
    and, once #213 records it at bet time, poisons CLV. Verified against
    production 2026-08-06, where MLB candidates carry a StatsAPI gamePk
    (`824804`) while quotes carry an OddsAPI event hash, so EVERY MLB row hit
    that fallback.

    So at least one identity signal must actually match:
      - `event_id`, when both sides carry the same id space;
      - `player_name`, which is the reliable cross-sport join for props and
        the one field board rows and quote rows word identically;
      - both teams, tolerating tri-code vs full-name (board rows say
        "LAA @ BAL", quote rows say "Baltimore Orioles").
    If none matches, return None.

    Market/selection/line stay SOFT after that, because the board's wording is
    not OddsAPI's ("moneyline" vs "h2h", a team name vs "home") and narrowing
    to nothing on a vocabulary difference would throw away a correct match.
    """
    rows = read_book_quotes(str(sport or ""), str(date_str or ""))
    if not rows:
        return None

    wanted_event = _normalize_token(event_id)
    wanted_player = _normalize_token(player_name)
    wanted_teams = _team_tokens(home_team, away_team, matchup)

    # `#414`. Narrow to rows that COULD match before testing anything. A row can
    # only be identified by an exact `event_id`, an exact `player_name`, or a
    # team pair the alias matcher accepts -- so any row outside this union would
    # have failed all three predicates anyway, and skipping it changes nothing.
    index = _quote_shard_index(rows, _book_quotes_cache_key(resolve_book_quotes_path(str(sport or ""), str(date_str or ""))))
    positions: set[int] = set()
    if wanted_event:
        positions.update(index["by_event"].get(wanted_event, ()))
    if wanted_player:
        positions.update(index["by_player"].get(wanted_player, ()))
    if wanted_teams:
        # Once per distinct pair (~15 a slate), not once per row (~83k). Same
        # predicate, same inputs -- `_row_teams_match` reads only these two
        # fields, so every row in a group gets the answer its pair earned.
        for (home_value, away_value), group in index["team_groups"].items():
            if _row_teams_match({"home_team": home_value, "away_team": away_value}, wanted_teams, sport):
                positions.update(group)

    identified: list[Mapping[str, Any]] = []
    hit_event = hit_player = hit_teams = 0
    # Sorted, so `identified` keeps shard order exactly as the full scan left it.
    # Downstream narrowing and best-price selection are order-sensitive at the
    # tie, and this is a join whose wrong answers are silent.
    for position in sorted(positions):
        row = rows[position]
        if wanted_event and _normalize_token(row.get("event_id")) == wanted_event:
            identified.append(row)
            hit_event += 1
            continue
        if wanted_player and _normalize_token(row.get("player_name")) == wanted_player:
            identified.append(row)
            hit_player += 1
            continue
        if wanted_teams and _row_teams_match(row, wanted_teams, sport):
            identified.append(row)
            hit_teams += 1
    # Per call, not per row -- see _QUOTE_JOIN_STATS. `rows_walked` still means
    # rows actually walked, so the metric stays honest across this change: it
    # was len(rows) when identity needed a full scan and is now the candidate
    # union. `shard_rows` carries what the full scan would have cost, so the
    # ratio between them is readable on the same line rather than needing a
    # before/after deploy to see.
    _bump("calls")
    _bump("rows_walked", len(positions))
    _bump("shard_rows", len(rows))
    if hit_event:
        _bump("by_event")
    elif hit_player:
        _bump("by_player")
    elif hit_teams:
        # The expensive path: the cheap key missed and every row was alias-resolved.
        _bump("by_teams_fallthrough")
    else:
        _bump("no_identity")
    if not identified:
        return None

    candidates = list(identified)
    wanted_market = _normalize_token(market)
    if wanted_market:
        narrowed = [
            row for row in candidates
            if _normalize_token(row.get("market")) == wanted_market
            or _MARKET_ALIASES.get(wanted_market) == _normalize_token(row.get("market"))
        ]
        candidates = narrowed or candidates
    wanted_selection = _normalize_token(selection)
    if wanted_selection:
        narrowed = [row for row in candidates if _selection_matches(row, wanted_selection)]
        candidates = narrowed or candidates
    line_value = _coerce_line(line)
    if line_value is not None:
        narrowed = [row for row in candidates if _coerce_line(row.get("line")) == line_value]
        candidates = narrowed or candidates

    grouped = quotes_by_market(candidates)
    if not grouped:
        return None
    # Narrowing can still leave more than one market (no line given, several
    # alternates). Prefer the one the most books quote -- the main line.
    best_key = max(grouped, key=lambda key: len(grouped[key]))
    chosen_market = grouped[best_key]
    # #238: hand the opposing side(s) in so the quote can carry a no-vig fair
    # price. Sourced from `identified` rather than `candidates`, because the
    # market/selection/line narrowing above has by then filtered the other side
    # out by construction -- it narrows TO one selection, which is exactly what
    # de-vigging needs the complement of.
    return quote_ref(
        chosen_market,
        chosen_bookmaker=bookmaker,
        now=now,
        market_sides=market_sides_for_quote(identified, chosen_market[0]),
    )


def _team_tokens(home_team: Any, away_team: Any, matchup: Any) -> set[str]:
    """Whatever team identifiers a caller could supply, as comparable tokens.

    Board rows carry `matchup` as "AWAY @ HOME" tri-codes and often no
    home_team/away_team at all, so the matchup string has to be split.
    """
    tokens = {_normalize_token(home_team), _normalize_token(away_team)}
    text = str(matchup or "").strip()
    if text:
        for part in text.replace(" vs ", " @ ").split("@"):
            token = _normalize_token(part)
            if token:
                tokens.add(token)
    return {token for token in tokens if token}


def _row_teams_match(row: Mapping[str, Any], wanted: set[str], sport: Any) -> bool:
    """True when BOTH of a quote row's teams are named by the caller.

    Both, not either: one shared team is not a game -- two clubs play twice in a
    series, and an either-match would join a Tuesday bet to a Wednesday price.

    Resolution is delegated to team_aliases, which uses the real per-sport maps.
    A pure string heuristic cannot do this: "chc" is neither a prefix of
    "chicago" nor the initials of "chicago cubs", and that single gap is why
    0 of 108 board candidates carried a quote in production on 2026-08-06.
    """
    from syndicate.features.shared.team_aliases import teams_match

    matched = 0
    for key in ("home_team", "away_team"):
        row_team = row.get(key)
        if not str(row_team or "").strip():
            continue
        if any(teams_match(sport, token, row_team) for token in wanted):
            matched += 1
    return matched >= 2


def _selection_matches(row: Mapping[str, Any], wanted: str) -> bool:
    row_selection = _normalize_token(row.get("selection"))
    if not row_selection:
        return False
    if row_selection == wanted:
        return True
    # Board picks read "Under 0" / "Over 1.5"; quote rows say "under"/"over".
    if wanted.startswith(row_selection) or row_selection.startswith(wanted.split()[0]):
        return True
    if _normalize_token(row.get("home_team")) == wanted and row_selection == "home":
        return True
    if _normalize_token(row.get("away_team")) == wanted and row_selection == "away":
        return True
    return False


# Board wording -> OddsAPI market key. Only the collisions that actually occur;
# an unknown market simply fails to narrow rather than mismatching.
_MARKET_ALIASES: dict[str, str] = {
    "moneyline": "h2h",
    "ml": "h2h",
    "money line": "h2h",
    "spread": "spreads",
    "ats": "spreads",
    "run line": "spreads",
    "puck line": "spreads",
    "total": "totals",
    "over under": "totals",
    "ou": "totals",
}


def quotes_by_market(rows: Iterable[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Group quote rows by cross-book market identity, keeping only the freshest
    observation per book so `quote_ref` compares one price per book rather than
    every price each book has posted today."""
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows or ():
        if not isinstance(row, Mapping) or row.get("price") is None:
            continue
        key = (market_key_for_quote(row), str(row.get("bookmaker") or ""))
        observed = str(row.get("book_updated_at") or row.get("snapshot_ts") or row.get("captured_at") or "")
        previous = latest.get(key)
        if previous is None or observed >= str(
            previous.get("book_updated_at") or previous.get("snapshot_ts") or previous.get("captured_at") or ""
        ):
            latest[key] = dict(row)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for (market, _book), row in latest.items():
        grouped.setdefault(market, []).append(row)
    return grouped


# ---------------------------------------------------------------------------
# Compaction: gzip CLOSED shards in place.
#
# WHY COMPRESS RATHER THAN DELETE OR DOWNSAMPLE. `book_quotes` is the largest
# family on every disk (1.3GB on web, 196.4 MB/day of new data measured
# 2026-08-12) and it is also the one family that genuinely cannot be
# regenerated -- a price at a moment is gone once it is gone, and settlement and
# CLV both read the history. That tension is what made retention hard.
#
# It dissolves on measurement. These shards are dense in INFORMATION and highly
# redundant in TEXT: 99.5% of rows carry a genuine price change (the writer
# already dedupes unchanged prices -- see `_KEY_FIELDS`), but every line repeats
# the same 17 keys, the same team names and near-identical timestamps. Measured
# on mlb/2026-08-09:
#
#     raw 207.4 MB  ->  gzip -6  5.4 MB   (38.7x, 4.9s single pass)
#
#     book_quotes steady state at 196.4 MB/day
#        30d     raw   5.8 GB      gzipped   0.1 GB
#       120d     raw  23.0 GB      gzipped   0.6 GB
#       365d     raw  70.0 GB      gzipped   1.8 GB
#
# So a FULL YEAR of captures costs less disk than three days does today, with
# every tick preserved exactly. Downsampling (keep open/close + N ticks) would
# also have worked and was the obvious move before this was measured -- it is
# strictly worse, because it throws away real price movement to buy space that
# compression gives for free.
#
# NOT APPLIED TO TODAY'S SHARD. It is append-only and still being written;
# appending to a gzip member yields a file that decompresses to the first member
# only. `book_quotes_path` therefore stays plain-text and this only ever touches
# dates strictly before today.
# ---------------------------------------------------------------------------

_COMPRESS_CHUNK_BYTES = 8 * 1024 * 1024


def _shard_date(path: Path) -> str:
    return path.name.split(".", 1)[0]


def compress_closed_shards(
    *,
    sport: str,
    today: str,
    apply: bool = False,
    min_age_days: int = 1,
) -> dict[str, Any]:
    """Gzip every `book_quotes` shard older than `min_age_days`.

    DRY RUN BY DEFAULT. `apply=False` reports what it would do and touches
    nothing.

    The original is removed only after the compressed copy has been read back
    and confirmed to hold the same number of lines. That verification is not
    ceremony: Render is the source of truth and the git tree is a lossy mirror,
    so for these files the copy on this disk may be the only one in existence.
    A compaction that half-worked and then deleted its input would be
    indistinguishable from a capture outage weeks later, when someone tries to
    settle against it.
    """
    from datetime import date as _date

    root = book_quotes_path(sport, today).parent
    result: dict[str, Any] = {
        "sport": sport,
        "apply": bool(apply),
        "compressed": [],
        "skipped": {},
        "bytes_before": 0,
        "bytes_after": 0,
    }
    if not root.is_dir():
        result["skipped"]["no_directory"] = 1
        return result

    def _skip(reason: str) -> None:
        result["skipped"][reason] = int(result["skipped"].get(reason, 0)) + 1

    try:
        today_date = _date.fromisoformat(str(today).strip())
    except ValueError:
        result["skipped"]["bad_today"] = 1
        return result

    for path in sorted(root.glob("*.jsonl")):
        try:
            shard_date = _date.fromisoformat(_shard_date(path))
        except ValueError:
            # Undated or oddly-named: never guess. An unrecognised name is not
            # evidence the file is disposable.
            _skip("undated")
            continue
        if (today_date - shard_date).days < max(1, int(min_age_days)):
            _skip("too_recent")
            continue
        packed = path.with_name(path.name + ".gz")
        if packed.exists():
            _skip("already_compressed")
            continue

        raw_bytes = path.stat().st_size
        result["bytes_before"] += raw_bytes
        if not apply:
            result["compressed"].append({"path": str(path), "bytes_before": raw_bytes, "dry_run": True})
            continue

        tmp = packed.with_name(packed.name + ".tmp")
        try:
            source_lines = 0
            with path.open("rb") as src, gzip.open(tmp, "wb", compresslevel=6) as dst:
                while True:
                    chunk = src.read(_COMPRESS_CHUNK_BYTES)
                    if not chunk:
                        break
                    source_lines += chunk.count(b"\n")
                    dst.write(chunk)
            # Read the compressed copy back before trusting it.
            packed_lines = 0
            with gzip.open(tmp, "rb") as check:
                while True:
                    chunk = check.read(_COMPRESS_CHUNK_BYTES)
                    if not chunk:
                        break
                    packed_lines += chunk.count(b"\n")
            if packed_lines != source_lines:
                tmp.unlink(missing_ok=True)
                _skip("verify_line_count_mismatch")
                print(
                    f"[odds_book_quotes] COMPACT_VERIFY_FAILED path={path} "
                    f"source_lines={source_lines} packed_lines={packed_lines} -- ORIGINAL KEPT",
                    flush=True,
                )
                continue
            os.replace(tmp, packed)
            path.unlink()
        except Exception as exc:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            _skip(f"error:{type(exc).__name__}")
            print(f"[odds_book_quotes] COMPACT_FAILED path={path} error={type(exc).__name__}: {exc}", flush=True)
            continue

        after = packed.stat().st_size
        result["bytes_after"] += after
        result["compressed"].append(
            {"path": str(packed), "bytes_before": raw_bytes, "bytes_after": after, "lines": source_lines}
        )

    if not apply:
        result["bytes_after"] = 0
    saved = result["bytes_before"] - result["bytes_after"]
    result["bytes_saved"] = saved if apply else None
    print(
        "[odds_book_quotes] COMPACT "
        + json.dumps(
            {
                "sport": sport,
                "apply": bool(apply),
                "files": len(result["compressed"]),
                "mb_before": round(result["bytes_before"] / (1024 * 1024), 1),
                "mb_after": round(result["bytes_after"] / (1024 * 1024), 1),
                "skipped": result["skipped"],
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return result
