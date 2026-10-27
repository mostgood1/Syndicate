"""FORWARD CAPTURE of Kalshi same-game combo (MVE) markets: E4 Stage 2's price data (lane
`kalshi-combo-capture`, todo `#742`; E4 is `#740`). Public, unauthenticated GETs only. Places NO order.

WHY FORWARD, AND WHY BY SETTLEMENT TIME. E4 Stage 2 needs executable combo prices joined to legs and
outcomes, and the past is expensive to rebuild. Measured 2026-10-27 between 13:13Z and 14:25Z by this
lane's probes:

    combos CREATED   ~1,000 per 11 s (~330k/h), 97% `is_provisional`: RFQ lookups, almost none traded
    combos SETTLED   22,147 in one 10-min window on KXMVECROSSCATEGORY (~133k/h), 23 pages of 1,000
    global trades    65,191 in the same 10 minutes (66 pages); 11.5% of them combo prints
    kept here        677 of those 22,147 (3%) hold a same-game pair in a sport we model; 9 had volume

A Monday morning is the quiet end. The 24-hour dry run (2026-10-26 15:03Z -> 10-27 03:33Z, NFL Sunday + NBA)
settled 5.48M cross-category combos in 12.5 h (7,909 pages, 3.7 GB wire); 3.36M (61%) held a same-game pair
because a long multi-game parlay almost always does, and 485k of those had volume.

A FINALIZED combo still lists its legs (`mve_selected_legs`), `result`, `last_price_dollars` and
`volume_fp`, but its quote is ZEROED (`yes_bid_dollars`/`yes_ask_dollars` 0.0000 on settled untraded
combos). An untraded kept combo therefore carries no price: it is COUNTED in runs.jsonl and not stored
(`--store-untraded` keeps it). The executable prices are the TRADE PRINTS, read per traded kept combo
(`kalshi_maker_shadow.read_trade_prints`) only up to DEFAULT_TRADES_MAX_LEGS legs: one GET per combo is
unaffordable across 485k a Sunday evening, and a long ticket's pair price cannot be backed out anyway.
Snapshotting every creation would cost ~8k GETs a day and reading the global trade stream ~9.5k on a
Monday morning. Listing SETTLEMENTS sees every combo exactly once, already resolved.

HOW A RUN WORKS. Per combo series, settlement time is swept in contiguous integer-second slices [lo, hi]
from a persisted watermark (`state.json`) up to now - SETTLE_LAG_S. `min_settled_ts`/`max_settled_ts`
filter exactly (0 of 414 rows outside a probed window). The query asks for hi + 1, and a row belongs to the
slice that holds floor(settlement_ts), so a sub-second settlement on a boundary is neither lost nor counted
twice. A slice is ALL OR NOTHING: an unreadable page writes nothing and leaves the watermark where it was,
because a partial listing read as complete is the failure this repo keeps refusing.

SAME GAME. Two legs are the same game when their event tickers share the game segment (`26OCT27SACSAS`)
inside one scope. The scope is the sport for US leagues (`kalshi_catalogue.sport_for_ticker`) and the
COMPETITION for soccer (`kalshi_board_join.soccer_competition_for_series`, which refuses women's and
second-tier families whose club codes collide with the men's). A segment that is not a dated game
(`game_date_from_ticker` and `event_blob_from_ticker`) never pairs, so two futures legs cannot pass as one
game. The whole combo is stored; Stage 2 picks the pair types it tests.

INERT UNTIL `SYNDICATE_KALSHI_COMBO_CAPTURE=on`. Absent means OFF: no request and no file. Enabling it on the
fleet is the user's decision (`#742`). `--enable` exists for a manual dry run only.

Writes only `<data root>/reports/intelligence/kalshi_combo_capture/` (no retention rule matches it):
    combos_<settled UTC date>.jsonl.gz   one row per TRADED kept combo, gzip members appended per slice
    runs.jsonl                           one row per run: GETs, pages, bytes, windows, kept (all) by sport
    collections_<UTC date>.json          the daily `/multivariate_event_collections` snapshot
    state.json                           per-series settlement watermark
Nothing on the request path reads it. Runs at nice 19.

Usage:
    python scripts/kalshi_combo_capture.py run                          # the scheduled job (inert when off)
    python scripts/kalshi_combo_capture.py run --enable --lookback-hours 24 --max-pages 12000  # dry run
    python scripts/kalshi_combo_capture.py report --days 2           # streams; never loads a date into memory
"""
from __future__ import annotations

import argparse
import collections
import contextlib
import datetime as dt
import gzip
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Mapping, NamedTuple, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared import kalshi_maker_shadow as ms  # noqa: E402
from syndicate.features.shared.kalshi_board_join import (  # noqa: E402
    series_competition_verdict,
    soccer_competition_for_series,
)
from syndicate.features.shared.kalshi_catalogue import (  # noqa: E402
    SERIES_OUT_OF_SCOPE,
    event_blob_from_ticker,
    game_date_from_ticker,
    sport_for_ticker,
)
from syndicate.features.shared.kalshi_client import is_combinatorial_series, series_from_ticker  # noqa: E402

RULE_VERSION = "combo-capture-v2"
ENV_FLAG = "SYNDICATE_KALSHI_COMBO_CAPTURE"
STORE_SUBDIR = ("reports", "intelligence", "kalshi_combo_capture")
MODELLED_SPORTS = frozenset({"mlb", "nba", "wnba", "nhl", "nfl", "ncaaf", "ncaab", "soccer"})

# Combo series swept -> (slice seconds, minimum seconds between sweeps). The two cross-category series settle
# continuously (the `0` shard ~1,000+ a week); the per-sport collections settled nothing over 10-20..10-27
# but list open markets, so they are read four times a day for one page each.
SWEEP_SERIES: dict[str, tuple[int, int]] = {
    "KXMVECROSSCATEGORY": (900, 0),
    "KXMVECROSSCATEGORY0": (3600, 0),
    "KXMVENBASINGLEGAME": (21600, 21600),
    "KXMVENFLSINGLEGAME": (21600, 21600),
    "KXMVESPORTSMULTIGAMEEXTENDED": (21600, 21600),
    "KXMVENBAMULTIGAMEEXTENDED": (21600, 21600),
    "KXMVENFLMULTIGAMEEXTENDED": (21600, 21600),
    "KXMVENFLMULTIGAME": (21600, 21600),
}
# Leg series that carry a game segment but are not a game outcome the platform prices (broadcast mentions).
NON_GAME_SERIES_TOKENS = ("MENTION",)

SETTLE_LAG_S = 300
DEFAULT_LOOKBACK_S = 3600
PAGE_LIMIT = 1000
SLICE_PAGE_CAP = 300  # a slice needing more is split in half (down to MIN_SLICE_S); its pages are DISCARDED
MIN_SLICE_S = 60
# A slice is sized from the last one's page density to need about this many pages. Fixed 900 s slices hit the cap
# 14 times in the 26-hour dry run and threw away 4,200 of 13,467 pages (a split re-reads both halves).
TARGET_SLICE_PAGES = 100
MAX_PAGES_PER_RUN = 900
MAX_RUN_S = 1800
LOCK_STALE_S = 2 * 3600
TRADE_PAUSE_S = 0.12
# One trade-read GET per traded kept combo of at most this many legs (None = all). OFF by default: the listing's
# `last_price` IS the last print (3,774 of 3,778) and 81% of traded combos print once, while a Sunday evening has
# 21.7k traded two-leg combos and 122k of <= 4 legs in 12.5 h, 3-15x the listing's own pages. See attach_trades.
DEFAULT_TRADES_MAX_LEGS: int | None = 0
DAY = 86400


# ------------------------------------------------------------------ small helpers
def _f(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out else None


def capture_enabled(environ: Mapping[str, str] | None = None) -> bool:
    raw = str((os.environ if environ is None else environ).get(ENV_FLAG) or "").strip().lower()
    return raw in {"1", "on", "true", "yes"}


def data_root() -> Path:
    override = str(os.environ.get("SYNDICATE_DATA_ROOT") or "").strip()
    return Path(override).expanduser().resolve() if override else REPO_ROOT / "data"


def store_dir(root: Path) -> Path:
    return Path(root).joinpath(*STORE_SUBDIR)


def utc_date(epoch: float) -> str:
    return dt.datetime.fromtimestamp(epoch, dt.timezone.utc).date().isoformat()


def _nice() -> None:
    try:
        os.nice(19)
    except (AttributeError, OSError):
        pass


# ------------------------------------------------------------------ same-game filter
def leg_scope(ticker: Any) -> tuple[str, str | None] | None:
    """(sport, soccer competition or None) for a leg in a sport we model, else None."""
    series = series_from_ticker(str(ticker or "").strip().upper())
    if not series or series.startswith("KXMVE") or is_combinatorial_series(series):
        return None
    if series in SERIES_OUT_OF_SCOPE or any(token in series for token in NON_GAME_SERIES_TOKENS):
        return None
    league = soccer_competition_for_series(series)
    if league:
        return "soccer", league
    sport = sport_for_ticker(series)
    if sport in MODELLED_SPORTS and series_competition_verdict(series, sport) is None:
        return sport, None
    return None


def leg_game(ticker: Any) -> str | None:
    """The game segment (`26OCT27SACSAS`) when it is a dated game, else None."""
    text = str(ticker or "").strip().upper()
    if game_date_from_ticker(text) is None or event_blob_from_ticker(text) is None:
        return None
    return text.split("-")[1]


def annotate_leg(leg: Mapping[str, Any]) -> dict[str, Any]:
    event = str(leg.get("event_ticker") or "").strip()
    market = str(leg.get("market_ticker") or "").strip()
    key = event or market
    scope = leg_scope(key)
    return {
        "event_ticker": event,
        "market_ticker": market,
        "side": leg.get("side"),
        "sport": scope[0] if scope else None,
        "league": scope[1] if scope else None,
        "game": leg_game(key) if scope else None,
    }


def groups_of(legs: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Same-game groups of two or more annotated legs, one per (sport, league, game)."""
    by_game: dict[tuple[str, str, str], list[int]] = {}
    for index, leg in enumerate(legs):
        if leg.get("sport") and leg.get("game"):
            by_game.setdefault((leg["sport"], leg.get("league") or "", leg["game"]), []).append(index)
    return [
        {"sport": sport, "league": league or None, "game": game, "legs": indexes}
        for (sport, league, game), indexes in sorted(by_game.items())
        if len(indexes) >= 2
    ]


def same_game_groups(raw_legs: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return groups_of([annotate_leg(leg) for leg in raw_legs if isinstance(leg, Mapping)])


def combo_row(raw: Mapping[str, Any], captured_at: str) -> dict[str, Any] | None:
    """The stored row for a combo holding a same-game pair in a sport we model, else None."""
    raw_legs = raw.get("mve_selected_legs")
    if not isinstance(raw_legs, list) or len(raw_legs) < 2:
        return None
    legs = [annotate_leg(leg) for leg in raw_legs if isinstance(leg, Mapping)]
    groups = groups_of(legs)
    if not groups:
        return None
    ticker = str(raw.get("ticker") or "")
    volume = _f(raw.get("volume_fp"))
    traded = bool(volume and volume > 0)
    return {
        "rule_version": RULE_VERSION,
        "captured_at": captured_at,
        "ticker": ticker,
        "event_ticker": raw.get("event_ticker"),
        "series": series_from_ticker(ticker),
        "collection": raw.get("mve_collection_ticker"),
        "status": raw.get("status"),
        "result": raw.get("result"),
        "is_provisional": raw.get("is_provisional"),
        "created_time": raw.get("created_time"),
        "open_time": raw.get("open_time"),
        "close_time": raw.get("close_time"),
        "expected_expiration_time": raw.get("expected_expiration_time"),
        "settlement_ts": raw.get("settlement_ts"),
        "volume_fp": volume,
        "open_interest_fp": _f(raw.get("open_interest_fp")),
        # As listed at capture. Kalshi zeroes these on a finalized combo; the prices are `trades`.
        "quote_at_capture": {
            "yes_bid": _f(raw.get("yes_bid_dollars")),
            "yes_ask": _f(raw.get("yes_ask_dollars")),
            "no_bid": _f(raw.get("no_bid_dollars")),
            "no_ask": _f(raw.get("no_ask_dollars")),
            "yes_bid_size": _f(raw.get("yes_bid_size_fp")),
            "yes_ask_size": _f(raw.get("yes_ask_size_fp")),
            "last_price": _f(raw.get("last_price_dollars")),
            "previous_yes_bid": _f(raw.get("previous_yes_bid_dollars")),
            "previous_yes_ask": _f(raw.get("previous_yes_ask_dollars")),
            "previous_price": _f(raw.get("previous_price_dollars")),
        },
        "n_legs": len(legs),
        "legs": legs,
        "same_game": groups,
        "sports": sorted({group["sport"] for group in groups}),
        "traded": traded,
        "trades_status": "pending" if traded else "not_traded",
        "trades": None,
    }


# ------------------------------------------------------------------ requests
class CountingGet:
    """Wraps the PUBLIC transport and counts every request by kind: the dry run's GETs/day instrument."""

    def __init__(self, transport: Callable[..., Any]):
        self.transport = transport
        self.calls: collections.Counter[str] = collections.Counter()

    def __call__(self, path: str, params: Mapping[str, Any] | None = None) -> Any:
        if path.startswith("/markets/trades"):
            kind = "trades"
        elif path.startswith("/multivariate_event_collections"):
            kind = "collections"
        else:
            kind = "markets"
        self.calls[kind] += 1
        return self.transport(path, params)


class RunBudget:
    def __init__(self, max_pages: int, max_seconds: float, clock: Callable[[], float] = time.monotonic):
        self.max_pages = int(max_pages)
        self.clock = clock
        self.deadline = clock() + float(max_seconds)
        self.pages = 0
        self.stopped = False

    def allow(self, pages: int = 1) -> bool:
        if self.pages + pages > self.max_pages or self.clock() >= self.deadline:
            self.stopped = True
            return False
        return True

    def spend(self) -> None:
        self.pages += 1


class SliceUnreadable(Exception):
    pass


class SliceTooLarge(Exception):
    pass


class BudgetStop(Exception):
    pass


# `sweep_slice` tallies every kept combo into its stats under "<kind>:<name>" keys; a run unpacks them here.
TALLY_KEYS = {"sport": "kept_by_sport", "sport_traded": "kept_traded_by_sport", "legs_traded": "kept_traded_by_legs",
              "league": "kept_by_league", "trades": "trades"}


class EncodedRow(NamedTuple):
    """A kept row already serialised for the store, with the settlement date it is filed under. As a dict a
    stored row took 8.9 KB of Python memory against 1.9 KB of JSON (20,000 rows settled 09-28, measured on the
    fleet 2026-10-27). That is why the first backfill run peaked at 2.5 GB: Kalshi's listing a month back holds
    traded combos only (379,393 of 379,410 kept), so every kept row was held whole until its slice ended."""
    date: str
    line: str


def encode_row(row: Mapping[str, Any]) -> str:
    return json.dumps(row, sort_keys=True, separators=(",", ":"))


def store_date(row: Mapping[str, Any]) -> str:
    return utc_date(ms.ts(row.get("settlement_ts")) or ms.ts(row.get("close_time")) or time.time())


def wants_trade_read(row: Mapping[str, Any], max_legs: int | None) -> bool:
    return bool(row.get("traded")) and (max_legs is None or int(row.get("n_legs") or 0) <= max_legs)


def tally(stats: collections.Counter, row: Mapping[str, Any]) -> None:
    traded = bool(row.get("traded"))
    stats["kept_traded"] += traded
    if traded:
        stats[f"legs_traded:{legs_bucket(row.get('n_legs'))}"] += 1
    for sport in row.get("sports") or ():
        stats[f"sport:{sport}"] += 1
        if traded:
            stats[f"sport_traded:{sport}"] += 1
    for league in {g["league"] for g in row.get("same_game") or () if g.get("league")}:
        stats[f"league:{league}"] += 1


def sweep_slice(get: Callable[..., Any], series: str, lo: int, hi: int, *, budget: RunBudget,
                captured_at: str, page_cap: int = SLICE_PAGE_CAP, keep_untraded: bool = True,
                trades_max_legs: int | None = None) -> tuple[list[dict[str, Any] | EncodedRow], collections.Counter]:
    """Every kept combo of `series` settled in the integer seconds [lo, hi]. All or nothing: raises rather
    than return a partial slice. Every kept combo is TALLIED; an untraded one is returned only with
    `keep_untraded` (holding a peak slice's 180k untraded rows took 1.25 GB). Only a row that may get a trade
    read (`trades_max_legs`, as in `attach_trades`) stays a dict; every other one is returned as its
    EncodedRow, its `trades_status` already final."""
    kept: dict[str, dict[str, Any] | EncodedRow] = {}
    seen: set[str] = set()
    stats: collections.Counter[str] = collections.Counter()
    cursor: str | None = None
    while True:
        if stats["pages"] >= page_cap:
            raise SliceTooLarge(f"{series} [{lo},{hi}] > {page_cap} pages")
        if not budget.allow():
            raise BudgetStop(f"{series} [{lo},{hi}] after {budget.pages} pages")
        params: dict[str, Any] = {"series_ticker": series, "min_settled_ts": int(lo), "max_settled_ts": int(hi) + 1,
                                  "limit": PAGE_LIMIT}
        if cursor:
            params["cursor"] = cursor
        doc = get("/markets", params)
        budget.spend()
        stats["pages"] += 1
        markets = doc.get("markets") if isinstance(doc, dict) else None
        if not isinstance(markets, list):
            raise SliceUnreadable(f"{series} [{lo},{hi}] page {stats['pages']}: {type(doc).__name__}")
        for raw in markets:
            if not isinstance(raw, Mapping):
                continue
            stats["rows"] += 1
            settled = ms.ts(raw.get("settlement_ts"))
            if settled is None:
                stats["no_settlement_ts"] += 1
            elif not lo <= int(settled) <= hi:
                stats["outside_slice"] += 1
                continue
            row = combo_row(raw, captured_at)
            if row is None or row["ticker"] in seen:
                continue
            seen.add(row["ticker"])
            tally(stats, row)
            if not (row["traded"] or keep_untraded):
                continue
            if wants_trade_read(row, trades_max_legs):
                kept[row["ticker"]] = row
                continue
            if row["traded"]:
                row["trades_status"] = "skipped"
                stats["trades:trades_skipped"] += 1
            kept[row["ticker"]] = EncodedRow(store_date(row), encode_row(row))
        cursor = doc.get("cursor") or None
        if not cursor or not markets:
            break
    stats["kept"] = len(seen)
    return list(kept.values()), stats


def sweep_window(get: Callable[..., Any], series: str, lo: int, hi: int, *, budget: RunBudget,
                 captured_at: str, page_cap: int = SLICE_PAGE_CAP, keep_untraded: bool = True,
                 trades_max_legs: int | None = None) -> tuple[list[dict[str, Any] | EncodedRow], collections.Counter]:
    """`sweep_slice`, halving a slice that needs more than `page_cap` pages."""
    kw = {"budget": budget, "captured_at": captured_at, "page_cap": page_cap, "keep_untraded": keep_untraded,
          "trades_max_legs": trades_max_legs}
    try:
        return sweep_slice(get, series, lo, hi, **kw)
    except SliceTooLarge:
        if hi - lo + 1 < 2 * MIN_SLICE_S:
            raise
        mid = lo + (hi - lo) // 2
        rows_a, stats_a = sweep_window(get, series, lo, mid, **kw)
        rows_b, stats_b = sweep_window(get, series, mid + 1, hi, **kw)
        stats_a.update(stats_b)
        stats_a["splits"] += 1
        stats_a["discarded_pages"] += page_cap
        return rows_a + rows_b, stats_a


def attach_trades(get: Callable[..., Any], rows: Iterable[dict[str, Any] | EncodedRow], pause: float = TRADE_PAUSE_S,
                  max_legs: int | None = None, budget: RunBudget | None = None) -> collections.Counter:
    """Public trade prints for each kept combo with volume; `trades_status` says what came back.

    `max_legs` bounds the one-GET-per-combo trade read to tickets of at most that many legs (0 = none, None = all).
    Every trade GET is charged to `budget`, so a run stays bounded; a row the budget cannot reach says
    `skipped_budget`. Measured 2026-10-26 15:03Z -> 10-27 03:33Z: 485k traded kept combos, 122k of them <= 4 legs.
    On the 3,778 read 14:35-18:34Z, `last_price` equalled the last print in 3,774, the prints summed to `volume`
    in all, 81% had one print, and the first print came a median 24 s (p90 113 s) after `created_time`. A
    skipped row keeps `last_price`, `volume` and `created_time`."""
    stats: collections.Counter[str] = collections.Counter()
    charged = get
    if budget is not None:
        def charged(path: str, params: Mapping[str, Any] | None = None) -> Any:
            budget.spend()
            return get(path, params)
    for row in rows:
        if isinstance(row, EncodedRow) or not row.get("traded"):  # an EncodedRow's trades_status is final
            continue
        if max_legs is not None and int(row.get("n_legs") or 0) > max_legs:
            row["trades_status"] = "skipped"
            stats["trades_skipped"] += 1
            continue
        if budget is not None and not budget.allow():
            row["trades_status"] = "skipped_budget"
            stats["trades_skipped_budget"] += 1
            continue
        hi = ms.ts(row.get("settlement_ts")) or ms.ts(row.get("close_time")) or time.time()
        lo = ms.ts(row.get("created_time")) or ms.ts(row.get("open_time")) or hi - 30 * DAY
        prints = ms.read_trade_prints(row["ticker"], lo, hi, get=charged, pause=pause)
        if prints is None:
            row["trades_status"] = "unreadable"
            stats["trades_unreadable"] += 1
            continue
        row["trades"] = [
            {"t": ms.iso(p["t"]), "yes": p.get("yes"), "no": p.get("no"), "count": _f(p.get("count")),
             "taker_side": p.get("taker_side")}
            for p in prints
        ]
        row["trades_status"] = "ok" if prints else "empty"
        stats["trades_ok" if prints else "trades_empty"] += 1
        stats["prints"] += len(prints)
    return stats


# ------------------------------------------------------------------ store
def combos_path(root: Path, date: str) -> Path:
    return store_dir(root) / f"combos_{date}.jsonl.gz"


def append_rows(root: Path, rows: Sequence[Mapping[str, Any] | EncodedRow]) -> dict[str, int]:
    """Append rows to their settlement date's file, one gzip member per call (readers see one stream). Written
    in chunks, so a slice's text is never joined into one more copy."""
    by_date: dict[str, list[str]] = collections.defaultdict(list)
    for row in rows:
        if isinstance(row, EncodedRow):
            by_date[row.date].append(row.line)
        else:
            by_date[store_date(row)].append(encode_row(row))
    for date, lines in by_date.items():
        path = combos_path(root, date)
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(path, "at", encoding="utf-8") as fh:
            for i in range(0, len(lines), 5000):
                fh.write("".join(line + "\n" for line in lines[i:i + 5000]))
    return {date: len(lines) for date, lines in by_date.items()}


def iter_combos(root: Path, date: str) -> Iterator[dict[str, Any]]:
    """Stored combos of one settlement date, STREAMED, one per ticker (a crash between write and watermark can
    repeat a slice; the first row wins). Never collect a date into memory: the 2026-10-26 Sunday kept 3.36M
    combos in 12.5 h, and holding them took 9 GB."""
    path = combos_path(root, date)
    if not path.is_file():
        return
    seen: set[str] = set()
    try:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict) and row.get("ticker") and row["ticker"] not in seen:
                    seen.add(row["ticker"])
                    yield row
    except (OSError, EOFError):
        return


def load_combos(root: Path, dates: Iterable[str]) -> list[dict[str, Any]]:
    """`iter_combos` collected, for a consumer that needs the rows (Stage 2 on a traded-only store)."""
    return [row for date in dates for row in iter_combos(root, date)]


def legs_bucket(n_legs: Any) -> str:
    n = int(n_legs or 0)
    return f"{n:02d}" if n <= 10 else ("11-15" if n <= 15 else "16+")


@contextlib.contextmanager
def run_lock(store: Path):
    """One run at a time on one store (the supervisor and a manual run must not share a watermark). Ages are
    wall clock, never a run's injected `now`."""
    store.mkdir(parents=True, exist_ok=True)
    path = store / ".lock"
    held = False
    for _ in range(2):
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                age = time.time() - path.stat().st_mtime
            except OSError:
                age = 0.0
            if age > LOCK_STALE_S:
                with contextlib.suppress(OSError):
                    path.unlink()
                continue
            break
        with os.fdopen(fd, "w") as fh:
            fh.write(json.dumps({"pid": os.getpid(), "at": ms.iso(time.time())}))
        held = True
        break
    try:
        yield held
    finally:
        if held:
            with contextlib.suppress(OSError):
                path.unlink()


def snapshot_collections(get: Callable[..., Any], root: Path, date: str, max_pages: int = 40) -> dict[str, Any]:
    """`/multivariate_event_collections` once a day: which combo series exist and which this job sweeps."""
    items: list[dict[str, Any]] = []
    cursor: str | None = None
    complete = False
    for _ in range(max_pages):
        params: dict[str, Any] = {"limit": 200}
        if cursor:
            params["cursor"] = cursor
        doc = get("/multivariate_event_collections", params)
        page = doc.get("multivariate_contracts") if isinstance(doc, dict) else None
        if not isinstance(page, list):
            break
        for c in page:
            if isinstance(c, Mapping):
                items.append({
                    "collection_ticker": c.get("collection_ticker"),
                    "series_ticker": c.get("series_ticker"),
                    "open_date": c.get("open_date"),
                    "close_date": c.get("close_date"),
                    "associated_event_tickers": c.get("associated_event_tickers") or [],
                })
        cursor = doc.get("cursor") or None
        if not cursor or not page:
            complete = True
            break
    series = collections.Counter(str(c.get("series_ticker")) for c in items)
    snapshot = {
        "date": date,
        "complete": complete,
        "collections": len(items),
        "by_series": dict(sorted(series.items())),
        "unswept_series": sorted(s for s in series if s not in SWEEP_SERIES),
        "items": items,
    }
    ms.save_json(store_dir(root) / f"collections_{date}.json", snapshot)
    return {k: v for k, v in snapshot.items() if k != "items"}


def _http_bytes() -> dict[str, int]:
    try:
        from syndicate.features.shared import http_compression
    except Exception:
        return {}
    stats = http_compression.stats()
    return {k: int(stats.get(k) or 0) for k in ("wire_bytes_external", "decoded_bytes_external")}


# ------------------------------------------------------------------ run
def run(root: Path, *, get: Callable[..., Any] = ms.public_get_json, now: float | None = None,
        enabled: bool | None = None, lookback_s: int = DEFAULT_LOOKBACK_S, max_pages: int = MAX_PAGES_PER_RUN,
        max_seconds: float = MAX_RUN_S, series: Mapping[str, tuple[int, int]] = SWEEP_SERIES,
        invoker: str = "cli", trade_pause: float = TRADE_PAUSE_S, page_cap: int = SLICE_PAGE_CAP,
        snapshot: bool = True, trades_max_legs: int | None = DEFAULT_TRADES_MAX_LEGS,
        store_untraded: bool = False) -> dict[str, Any]:
    if not (capture_enabled() if enabled is None else enabled):
        print(f"[kalshi_combo_capture] OFF ({ENV_FLAG} is not on): no request, no file", flush=True)
        return {"status": "off"}
    now = time.time() if now is None else float(now)
    store = store_dir(root)
    with run_lock(store) as held:
        if not held:
            print(f"[kalshi_combo_capture] LOCKED: another run holds {store / '.lock'}", flush=True)
            return {"status": "locked"}
        return _run_locked(root, get=get, now=now, lookback_s=lookback_s, max_pages=max_pages,
                           max_seconds=max_seconds, series=series, invoker=invoker, trade_pause=trade_pause,
                           page_cap=page_cap, snapshot=snapshot, trades_max_legs=trades_max_legs,
                           store_untraded=store_untraded)


def _run_locked(root: Path, *, get, now, lookback_s, max_pages, max_seconds, series, invoker, trade_pause,
                page_cap, snapshot, trades_max_legs, store_untraded) -> dict[str, Any]:
    started = time.monotonic()
    store = store_dir(root)
    state_path = store / "state.json"
    state = ms.load_json(state_path, {})
    if not isinstance(state, dict):
        state = {}
    state.setdefault("series", {})
    counting = CountingGet(get)
    budget = RunBudget(max_pages, max_seconds)
    bytes_before = _http_bytes()
    captured_at = ms.iso(now)
    summary: dict[str, Any] = {"run_at": captured_at, "rule_version": RULE_VERSION, "invoker": invoker,
                               "trades_max_legs": trades_max_legs, "store_untraded": store_untraded, "series": {},
                               "kept_by_sport": collections.Counter(), "kept_traded_by_sport": collections.Counter(),
                               "kept_traded_by_legs": collections.Counter(), "kept_by_league": collections.Counter(),
                               "trades": collections.Counter(), "written": collections.Counter(), "errors": []}

    today = utc_date(now)
    if snapshot and state.get("collections_date") != today:
        snap = snapshot_collections(counting, root, today)
        summary["collections"] = snap
        if snap.get("complete"):
            state["collections_date"] = today

    end = int(now) - SETTLE_LAG_S
    for name, (slice_s, interval_s) in series.items():
        st = state["series"].setdefault(name, {})
        info = collections.Counter()
        record: dict[str, Any] = {"from": None, "to": None}
        if interval_s and now - float(st.get("last_sweep_at") or 0) < interval_s:
            record["skipped"] = "interval"
            summary["series"][name] = record
            continue
        swept = int(st.get("swept_to") or (end - int(lookback_s)))
        record["from"] = ms.iso(swept + 1)
        while swept < end and not budget.stopped:
            span = int(slice_s)
            density = float(st.get("pages_per_s") or 0.0)
            if density > 0:
                span = max(MIN_SLICE_S, min(span, int(TARGET_SLICE_PAGES / density)))
            lo, hi = swept + 1, min(swept + span, end)
            if end - hi < MIN_SLICE_S:  # fold a short remainder in rather than read it as its own slice
                hi = end
            # Stop BEFORE a slice the budget cannot finish: a slice cut short is discarded, pages and all.
            if not budget.allow(int(st.get("last_slice_pages") or 1)):
                break
            try:
                # An untraded finalized combo's quote is zeroed: it carries no price, so it is tallied, not stored.
                rows, stats = sweep_window(counting, name, lo, hi, budget=budget, captured_at=captured_at,
                                           page_cap=page_cap, keep_untraded=store_untraded,
                                           trades_max_legs=trades_max_legs)
            except BudgetStop:
                break
            except (SliceUnreadable, SliceTooLarge) as exc:
                summary["errors"].append(f"{type(exc).__name__}: {exc}")
                break
            trade_stats = attach_trades(counting, rows, pause=trade_pause, max_legs=trades_max_legs, budget=budget)
            summary["trades"].update(trade_stats)
            for date, n in append_rows(root, rows).items():
                summary["written"][date] += n
            for key, n in stats.items():
                kind, _, label = key.partition(":")
                if label:
                    summary[TALLY_KEYS[kind]][label] += n
                else:
                    info[key] += n
            info["slices"] += 1
            swept = hi
            st["swept_to"] = hi
            st["last_slice_pages"] = int(stats["pages"])
            if hi - lo + 1 >= MIN_SLICE_S:  # a slice costs >= 1 page, so a seconds-long one overstates density
                st["pages_per_s"] = int(stats["pages"]) / (hi - lo + 1)
            ms.save_json(state_path, state)
        if swept >= end:
            st["last_sweep_at"] = now
            ms.save_json(state_path, state)
        record["to"] = ms.iso(swept)
        record["seconds_covered"] = max(0, swept + 1 - int(ms.ts(record["from"]) or swept + 1))
        record.update(dict(info))
        summary["series"][name] = record

    ms.save_json(state_path, state)
    bytes_after = _http_bytes()
    summary["http_bytes"] = {k: bytes_after.get(k, 0) - bytes_before.get(k, 0) for k in bytes_after}
    summary["gets"] = dict(counting.calls)
    summary["gets_total"] = sum(counting.calls.values())
    summary["pages"] = budget.pages
    summary["budget_stopped"] = budget.stopped
    summary["seconds"] = round(time.monotonic() - started, 1)
    summary["finished_at"] = ms.iso(time.time())
    summary["status"] = "errors" if summary["errors"] else ("budget_stopped" if budget.stopped else "ok")
    for key in ("kept_by_sport", "kept_traded_by_sport", "kept_traded_by_legs", "kept_by_league", "trades", "written"):
        summary[key] = dict(sorted(summary[key].items()))
    with (store / "runs.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(summary, sort_keys=True) + "\n")
    print(f"[kalshi_combo_capture] {summary['status']} gets={summary['gets_total']} pages={summary['pages']} "
          f"kept={summary['kept_by_sport']} traded={summary['kept_traded_by_sport']} "
          f"prints={summary['trades'].get('prints', 0)} errors={len(summary['errors'])} {summary['seconds']}s",
          flush=True)
    return summary


# ------------------------------------------------------------------ report
def read_runs(root: Path) -> list[dict[str, Any]]:
    path = store_dir(root) / "runs.jsonl"
    rows: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
    except OSError:
        pass
    return rows


def report(root: Path, dates: Sequence[str]) -> dict[str, Any]:
    """Cost and kept combos per covered day (from runs.jsonl, which counts what a run did not store), and the
    STORED combos per settlement date (streamed)."""
    runs = read_runs(root)
    gets = collections.Counter()
    covered = 0
    wire = decoded = pages = 0
    kept = {key: collections.Counter() for key in ("kept_by_sport", "kept_traded_by_sport", "kept_traded_by_legs")}
    for r in runs:
        gets.update(r.get("gets") or {})
        pages += int(r.get("pages") or 0)
        wire += int((r.get("http_bytes") or {}).get("wire_bytes_external") or 0)
        decoded += int((r.get("http_bytes") or {}).get("decoded_bytes_external") or 0)
        covered += int(((r.get("series") or {}).get("KXMVECROSSCATEGORY") or {}).get("seconds_covered") or 0)
        for key, counter in kept.items():
            counter.update(r.get(key) or {})
    days_covered = covered / DAY if covered else 0.0
    per_day = (lambda x: round(x / days_covered, 1) if days_covered else None)
    by_date: dict[str, Any] = {}
    for date in dates:
        n = prints = pure_traded = 0
        sport, traded, league, two_leg, status, traded_legs, results = (collections.Counter() for _ in range(7))
        for row in iter_combos(root, date):
            n += 1
            status[row.get("trades_status")] += 1
            results[row.get("result") or "unset"] += 1
            legs = int(row.get("n_legs") or 0)
            if row.get("traded"):
                traded_legs[legs] += 1
                pure_traded += sum(len(g.get("legs") or ()) for g in row.get("same_game") or ()) == legs
            for s in row.get("sports") or ():
                sport[s] += 1
                traded[s] += bool(row.get("traded"))
                two_leg[s] += legs == 2
            for g in row.get("same_game") or ():
                if g.get("league"):
                    league[g["league"]] += 1
            prints += len(row.get("trades") or ())
        # What a trade read costs at each `--trades-max-legs`: one GET per traded combo at or under the bound.
        traded_at_most = {k: sum(c for legs, c in traded_legs.items() if legs <= k) for k in (2, 3, 4, 5, 6, 8, 10)}
        by_date[date] = {"stored": n, "by_sport": dict(sport.most_common()), "traded_by_sport": dict(traded.most_common()),
                         "two_leg_by_sport": dict(two_leg.most_common()), "soccer_by_league": dict(league.most_common()),
                         "prints": prints, "trades_status": dict(status), "results": dict(results.most_common()),
                         "traded_total": sum(traded_legs.values()), "traded_at_most_legs": traded_at_most,
                         "traded_every_leg_same_game": pure_traded}
    return {
        "runs": len(runs),
        "cross_category_days_covered": round(days_covered, 3),
        "gets": dict(gets), "gets_total": sum(gets.values()), "pages": pages,
        "gets_per_day": per_day(sum(gets.values())), "pages_per_day": per_day(pages),
        "wire_mb_per_day": per_day(wire / 1e6), "decoded_mb_per_day": per_day(decoded / 1e6),
        **{f"{key}_per_day": {k: per_day(v) for k, v in sorted(counter.items())} for key, counter in kept.items()},
        "by_settlement_date": by_date,
    }


# A run whose kept combos were (nearly) all traded read a listing Kalshi had already purged of untraded combos;
# one where most were untraded read rows still listed. Runs keeping fewer combos than this are not evidence.
PURGED_SHARE = 0.99
UNPURGED_SHARE = 0.5
MIN_KEPT_FOR_SHARE = 1000


def forward_status(root: Path, now: float | None = None) -> dict[str, Any]:
    """The two readings `#742` owes, read-only from runs.jsonl and the store.

    `purge`: untraded combos leave the listing some age after settlement. Every run that kept only traded
    combos bounds that age from ABOVE by its youngest row's age (run time - newest settlement swept); every run
    that still saw mostly untraded ones bounds it from BELOW the same way. Measured 10-27: all-traded 20 days back.

    `first_full_forward_day`: the first UTC settlement date that starts after the sweep first caught up (its first
    run ending `ok`) and that the watermark has passed, with its stored rows and results, and the GETs and
    kept counts of the runs whose windows overlap it, prorated by settlement seconds."""
    now = time.time() if now is None else float(now)
    windows = []
    for r in sorted(read_runs(root), key=lambda r: str(r.get("run_at"))):
        s = (r.get("series") or {}).get("KXMVECROSSCATEGORY") or {}
        lo, hi, at = ms.ts(s.get("from")), ms.ts(s.get("to")), ms.ts(r.get("run_at"))
        if lo is None or hi is None or at is None or hi < lo:
            continue
        windows.append((r, s, int(lo), int(hi), at))
    invokers = collections.Counter(str(r.get("invoker")) for r, *_ in windows)
    out: dict[str, Any] = {"now": ms.iso(now), "runs": len(windows), "invokers": dict(invokers), "met": False}
    if not windows:
        return out
    last_r, last_s, _, last_hi, _ = windows[-1]
    swept_to = max(hi for *_, hi, _ in windows)
    out["last_run"] = {"run_at": last_r.get("run_at"), "status": last_r.get("status"), "invoker": last_r.get("invoker"),
                       "swept_to": ms.iso(swept_to), "lag_hours": round((now - swept_to) / 3600, 2)}

    upper, lower, boundary = [], [], []
    for r, s, lo, hi, at in windows:
        kept = int(s.get("kept") or 0)
        if kept < MIN_KEPT_FOR_SHARE:
            continue
        share = int(s.get("kept_traded") or 0) / kept
        youngest = (at - hi) / 3600
        if share >= PURGED_SHARE:
            upper.append((youngest, hi))
        elif share <= UNPURGED_SHARE:
            lower.append((youngest, hi))
        else:
            boundary.append({"run_at": r.get("run_at"), "settled": [ms.iso(lo), ms.iso(hi)], "share": round(share, 3),
                             "age_hours": [round(youngest, 1), round((at - lo) / 3600, 1)]})
    purge = {"purged_runs": len(upper), "unpurged_runs": len(lower), "boundary_runs": boundary,
             "age_hours_above": round(max(lower)[0], 1) if lower else None,
             "age_hours_at_most": round(min(upper)[0], 1) if upper else None}
    out["purge"] = purge

    ok = [(r, hi) for r, _, _, hi, _ in windows if r.get("status") == "ok"]
    day = None
    if ok:
        caught_r, caught_hi = ok[0]
        out["caught_up"] = {"run_at": caught_r.get("run_at"), "swept_to": ms.iso(caught_hi)}
        start = (caught_hi // DAY + 1) * DAY
        if swept_to >= start + DAY - 1:
            day = utc_date(start)
            gets = pages = 0.0
            kept_sport, traded_sport = collections.Counter(), collections.Counter()
            overlapping = 0
            for r, s, lo, hi, _ in windows:
                overlap = min(hi, start + DAY - 1) - max(lo, start) + 1
                if overlap <= 0:
                    continue
                share = overlap / (hi - lo + 1)
                overlapping += 1
                gets += share * int(r.get("gets_total") or 0)
                pages += share * int(r.get("pages") or 0)
                for k, v in (r.get("kept_by_sport") or {}).items():
                    kept_sport[k] += share * v
                for k, v in (r.get("kept_traded_by_sport") or {}).items():
                    traded_sport[k] += share * v
            out["day"] = {"date": day, "runs_overlapping": overlapping, "gets_prorated": round(gets),
                          "pages_prorated": round(pages),
                          "kept_by_sport_prorated": {k: round(v) for k, v in kept_sport.most_common()},
                          "kept_traded_by_sport_prorated": {k: round(v) for k, v in traded_sport.most_common()},
                          **report(root, [day])["by_settlement_date"][day]}
    out["first_full_forward_day"] = day
    out["met"] = bool(day and purge["age_hours_above"] is not None and purge["age_hours_at_most"] is not None)
    return out


# ------------------------------------------------------------------ cli
def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="sweep newly settled combos (inert unless the env flag is on)")
    r.add_argument("--data-root", default=None, help="defaults to SYNDICATE_DATA_ROOT")
    r.add_argument("--enable", action="store_true", help=f"manual dry run: ignore {ENV_FLAG}")
    r.add_argument("--lookback-hours", type=float, default=DEFAULT_LOOKBACK_S / 3600,
                   help="first run only: how far back the watermark starts")
    r.add_argument("--max-pages", type=int, default=MAX_PAGES_PER_RUN)
    r.add_argument("--max-seconds", type=float, default=MAX_RUN_S)
    r.add_argument("--invoker", default="cli")
    r.add_argument("--trades-max-legs", type=int, default=DEFAULT_TRADES_MAX_LEGS,
                   help=f"read trade prints only for traded combos of at most N legs (0 = none, -1 = all; "
                        f"default {DEFAULT_TRADES_MAX_LEGS})")
    r.add_argument("--store-untraded", action="store_true",
                   help="also store kept combos with no volume (their finalized quote is zeroed; default: count only)")
    p = sub.add_parser("report", help="GETs per covered day and kept combos per settlement date / sport")
    p.add_argument("--data-root", default=None)
    p.add_argument("--days", type=int, default=2)
    p.add_argument("--date", action="append", default=None, help="settlement date(s), repeatable")
    st = sub.add_parser("status", help="read-only: purge-age bracket and the first full forward day (#742 readings)")
    st.add_argument("--data-root", default=None)
    args = ap.parse_args(argv)
    root = Path(args.data_root).expanduser().resolve() if args.data_root else data_root()
    if args.cmd == "run":
        _nice()
        summary = run(root, enabled=True if args.enable else None, lookback_s=int(args.lookback_hours * 3600),
                      max_pages=args.max_pages, max_seconds=args.max_seconds, invoker=args.invoker,
                      trades_max_legs=None if args.trades_max_legs < 0 else args.trades_max_legs,
                      store_untraded=args.store_untraded)
        return 1 if summary.get("status") == "errors" else 0
    if args.cmd == "status":
        print(json.dumps(forward_status(root), indent=1, sort_keys=True))
        return 0
    today = dt.datetime.now(dt.timezone.utc).date()
    dates = args.date or [(today - dt.timedelta(days=d)).isoformat() for d in range(args.days - 1, -1, -1)]
    print(json.dumps(report(root, dates), indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
