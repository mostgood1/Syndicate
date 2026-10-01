"""Refresh Novig's public daily markets snapshot -- on its OWN clock, not
Kalshi's.

THE PIECE THAT MAKES NOVIG'S CLOSING LINE AVAILABLE TO THE BOARD, once
something downstream chooses to read it. `novig_client.fetch_latest_markets_snapshot()`
answers "what did Novig's book close at" for one call; this is what keeps
that answer current and durable across a worker restart, the same role
`kalshi_odds_refresh.py` plays for Kalshi -- read that module first, this one
follows its shape deliberately.

--------------------------------------------------------------------------
THE CADENCE IS NOT KALSHI'S. NOVIG PUBLISHES ONCE A DAY, NOT CONTINUOUSLY.
--------------------------------------------------------------------------

Kalshi's refresh has a per-series clock because Kalshi's own book moves
continuously and a live position needs a fresh quote. Novig's public mirror
is END-OF-DAY tape -- "each day publishes shortly after midnight Eastern,"
per `novig_client.py`'s header -- so there is nothing to gain from polling
more than roughly hourly, and nothing lost by checking that often: the CDN
manifest (`index.json`) is a cheap read, and the actual multi-thousand-row
CSV is only re-fetched when the manifest actually names a NEW date this
process has not already cached.

So this is deliberately SIMPLER than `kalshi_odds_refresh.py`: one clock, no
per-series due-queue, no hot-series shortcut, no per-tick fetch cap. The
thing to get right here is not throughput, it is not hammering a CDN
manifest sixty times an hour for an answer that changes once a day.

--------------------------------------------------------------------------
CACHED MEANS "STILL THE SAME PUBLISHED DAY", NOT "STILL FRESH ENOUGH"
--------------------------------------------------------------------------

`run_novig_odds_refresh` returns `status: "cached"` whenever the last
snapshot it fetched is still the latest one Novig has published -- which,
most of the day, is EVERY call, because Novig only publishes once. A caller
must not read `"cached"` as "this might be a few minutes stale" the way
Kalshi's `"cached"` means that; here it can mean "this is up to ~24 hours
old and that is the freshest Novig has." `is_stale_by_days` on the stored
snapshot (from `fetch_latest_markets_snapshot`) is what actually answers
"how old," and any consumer of this artifact should read that field before
treating the price as current -- the same discipline
`fetch_latest_markets_snapshot`'s own docstring already requires of a direct
caller, now enforced for the CACHED path too.
"""

from __future__ import annotations

import os
import threading
from datetime import datetime, timezone
from typing import Any


def novig_odds_enabled() -> bool:
    """Default ON. Read-only, public, no credential -- same posture
    `kalshi_odds_enabled()` takes for the same reason."""
    raw = os.environ.get("SYNDICATE_NOVIG_ODDS_ENABLED")
    if raw is None:
        return True
    return str(raw).strip().lower() not in {"0", "false", "no", "off"}


# ONE HOUR. Novig publishes once a day; checking the manifest hourly finds a
# new date within an hour of it landing without hammering a CDN read that
# changes once every ~24h the other 23 times. Not a fetch cap the way
# Kalshi's `series_per_tick` is -- there is only ever one thing to fetch.
DEFAULT_CHECK_INTERVAL_SECONDS = 3600
FAILED_RETRY_SECONDS = 600


def check_interval_seconds() -> int:
    raw = os.environ.get("SYNDICATE_NOVIG_ODDS_CHECK_INTERVAL_SECONDS")
    try:
        parsed = int(str(raw).strip())
    except (TypeError, ValueError):
        return DEFAULT_CHECK_INTERVAL_SECONDS
    return parsed if parsed > 0 else DEFAULT_CHECK_INTERVAL_SECONDS


def markets_artifact_path():
    from syndicate.features.shared.refresh_state_store import reports_root

    return reports_root() / "intelligence" / "novig_markets.json"


# The fields a board join actually needs from a CLOSING LINE -- deliberately
# NOT every field `normalize_market_row` produces. Measured 2026-08-24, the
# very next cycle after the Decimal fix above: a full day's ~29,469-row
# catalogue serialized to 9,128,668 bytes, over `refresh_state_store`'s
# ~8MB keyvalue ceiling (#60 in docs/ai_context/todo.md -- "shrink the
# payload... rather than raising the ceiling", enforced exactly because three
# prior outages were each an unbounded payload in different clothes). This is
# the shrink: `date` is dropped because it is 100% redundant with the
# snapshot's own top-level `date` (every row in one day's markets.csv shares
# it); `open_probability`/`high_probability`/`low_probability` are dropped
# because they are the day's INTRADAY movement, and this module's whole
# purpose (see file header) is the CLOSING line, not a trade history --
# `fetch_latest_markets_snapshot()` still returns the full OHLC row directly
# to any caller that wants it, this trim applies ONLY to what gets persisted
# to (and returned alongside) the shared artifact.
_MARKET_ROW_KEYS_TO_PERSIST = (
    "market_id",
    "report_ticker",
    "open_interest",
    "daily_volume",
    "close_probability",
    "close_american",
    "status",
    "traded_today",
)


def _trimmed_for_storage(market: dict[str, Any]) -> dict[str, Any]:
    return {key: market.get(key) for key in _MARKET_ROW_KEYS_TO_PERSIST}


def _json_safe(value: Any) -> Any:
    """Recursively replace `Decimal` with its exact string form so
    `write_json_file`'s plain `json.dumps` can serialize it.

    Measured 2026-08-24, first production cycle: `normalize_market_row`
    deliberately returns `Decimal` for `open_interest`/`daily_volume` (see
    its docstring -- the same precision discipline `cash_units_for_stake`
    was fixed for), and that Decimal rode all the way into `state["snapshot"]`
    unconverted, so every write of this artifact failed with `Object of type
    Decimal is not JSON serializable` -- the fetch succeeded (REFRESHED,
    count=29469) but nothing was ever persisted to disk. `str(Decimal(...))`
    round-trips exactly (unlike `float`, which is the precision loss this
    Decimal choice exists to avoid) -- a reader that needs to compute with it
    calls `Decimal(value)` again, same as it would with the in-process
    normalized row.
    """
    from decimal import Decimal

    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _persistable(state: dict[str, Any]) -> dict[str, Any]:
    """What actually gets written: JSON-safe, with the snapshot's large values
    (in practice `markets`) deflated by the board's own lossless codec.

    Measured 2026-10-01 on the local production fleet: Novig's 2026-09-30 tape
    is 49,094 rows (28,792 of them COMBO), and even trimmed to
    `_MARKET_ROW_KEYS_TO_PERSIST` the payload was 10,601,014 bytes against the
    8,388,608 keyvalue ceiling. Every write was refused (`KEYVALUE_WRITE_REJECTED`,
    21x), so the state never persisted, every hourly check re-fetched the whole
    CSV (`previous_date=None` on every REFRESHED), and nothing downstream could
    ever have read a closing line. The trim was sized for 29,469 rows in August;
    another field cut would only buy time against a catalogue that keeps
    growing. Compression is lossless -- every row is kept, COMBO included -- and
    homogeneous records like these are what deflate best (`_compress_oversized_values`
    measured 14x on board snapshots).

    `date`, `checked_at` and the other small fields stay plain, so the cadence
    check and a `KEYVALUE_PAYLOAD_COMPOSITION` line still read them directly.
    """
    from pipeline.intelligence_state import _compress_oversized_values

    out = _json_safe(state)
    snapshot = out.get("snapshot")
    if isinstance(snapshot, dict):
        out["snapshot"] = _compress_oversized_values(snapshot)
    return out


def snapshot_from_state(state: Any) -> dict[str, Any] | None:
    """The stored snapshot with its rows expanded. THE way to read this
    artifact: a reader that takes `state["snapshot"]["markets"]` directly gets
    the compressed envelope, not rows. None when there is no snapshot, or when
    it cannot be decoded (an unknown codec or corrupt data refuses rather than
    returning a half-decoded dict -- see `_decompress_oversized_values`)."""
    from pipeline.intelligence_state import _decompress_oversized_values

    snapshot = state.get("snapshot") if isinstance(state, dict) else None
    if not isinstance(snapshot, dict):
        return None
    return _decompress_oversized_values(snapshot)


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _seconds_since(stamp: Any) -> float | None:
    if not stamp:
        return None
    try:
        parsed = datetime.strptime(str(stamp), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None
    return (datetime.now(timezone.utc) - parsed).total_seconds()


def _due_to_check(state: dict[str, Any], interval: int) -> bool:
    """Has enough time passed since the last MANIFEST check to look again?

    Distinct from "has enough time passed to re-fetch the CSV" -- the
    manifest is cheap and checked on this clock; the multi-thousand-row CSV
    is fetched only when the manifest actually names a date we do not have,
    regardless of this clock.
    """
    last_checked = state.get("checked_at")
    age = _seconds_since(last_checked)
    if age is None:
        return True
    if state.get("last_check_failed") and age < min(interval, FAILED_RETRY_SECONDS):
        return False
    return age >= interval


def run_novig_odds_refresh(*, force: bool = False) -> dict[str, Any]:
    """Check Novig's manifest; fetch a new snapshot only if one has actually
    published since the last successful fetch; always return the best
    snapshot on hand.

    `force=True` bypasses the enable flag and the check-interval clock --
    what a manual probe wants, matching `run_kalshi_odds_refresh`'s
    `force` contract.
    """
    if not (force or novig_odds_enabled()):
        return {"status": "skipped", "reason": "disabled"}

    from syndicate.features.shared.refresh_state_store import read_json_file, write_json_file

    path = markets_artifact_path()
    try:
        state = read_json_file(path) or {}
    except Exception:
        state = {}
    if state.get("snapshot") is not None:
        expanded = snapshot_from_state(state)
        if expanded is None:
            # Undecodable: drop it and refetch rather than serve an envelope.
            print("[novig_odds] STORED_SNAPSHOT_UNREADABLE effect=refetch", flush=True)
            state.pop("snapshot", None)
            state.pop("checked_at", None)
        else:
            state["snapshot"] = expanded

    interval = check_interval_seconds()
    if not force and not _due_to_check(state, interval):
        cached_date = (state.get("snapshot") or {}).get("date")
        print(
            f"[novig_odds] CACHED snapshot_date={cached_date}"
            f" checked_at={state.get('checked_at')} interval_s={interval}",
            flush=True,
        )
        return {"status": "cached", "snapshot": state.get("snapshot")}

    from syndicate.features.shared.novig_client import fetch_latest_markets_snapshot

    state["checked_at"] = _now_stamp()

    result = fetch_latest_markets_snapshot()
    if result.get("status") != "ok":
        state["last_check_failed"] = True
        state["last_check_reason"] = result.get("reason")
        print(f"[novig_odds] CHECK_FAILED reason={result.get('reason')}", flush=True)
        try:
            write_json_file(path, _persistable(state))
        except Exception as exc:
            print(f"[novig_odds] WRITE_FAILED error={exc}", flush=True)
        # The LAST GOOD snapshot, if there is one -- a manifest hiccup must
        # not blank out yesterday's perfectly good close.
        return {"status": "error", "reason": result.get("reason"), "snapshot": state.get("snapshot")}

    state["last_check_failed"] = False
    existing_date = (state.get("snapshot") or {}).get("date")
    new_date = result.get("date")

    if new_date == existing_date and not force:
        # The manifest was checked and Novig has not published a newer day.
        # The CSV itself is NOT re-fetched -- there is nothing new in it.
        print(
            f"[novig_odds] UNCHANGED snapshot_date={new_date} count={result.get('count')}",
            flush=True,
        )
        try:
            write_json_file(path, _persistable(state))
        except Exception as exc:
            print(f"[novig_odds] WRITE_FAILED error={exc}", flush=True)
        return {"status": "cached", "snapshot": state.get("snapshot")}

    # Trim BEFORE persisting -- see `_trimmed_for_storage`'s docstring-comment
    # above. `result["markets"]` (the return value) is reassigned to the same
    # trimmed rows so the artifact and the direct caller see one consistent
    # shape, not a richer in-memory result than what actually got stored.
    result["markets"] = [_trimmed_for_storage(m) for m in (result.get("markets") or [])]
    state["snapshot"] = result
    try:
        write_json_file(path, _persistable(state))
    except Exception as exc:
        print(f"[novig_odds] WRITE_FAILED error={exc}", flush=True)

    print(
        "[novig_odds] REFRESHED"
        f" date={new_date}"
        f" previous_date={existing_date}"
        f" count={result.get('count')}"
        f" is_stale_by_days={result.get('is_stale_by_days')}"
        f" status_filter={result.get('status_filter')}",
        flush=True,
    )

    # A per-report-ticker breakdown, the same "make the coverage legible"
    # instinct `kalshi_odds_refresh.report_catalogue_gaps` has -- a bare
    # count says nothing actionable about what Novig actually lists.
    by_ticker: dict[str, int] = {}
    for market in result.get("markets") or []:
        ticker = str(market.get("report_ticker") or "<absent>")
        by_ticker[ticker] = by_ticker.get(ticker, 0) + 1
    top = sorted(by_ticker.items(), key=lambda kv: -kv[1])[:10]
    print(f"[novig_odds] BY_REPORT_TICKER {top}", flush=True)

    return {"status": "ok", "snapshot": result}


def start_background_loop_if_enabled() -> bool:
    """A daemon thread that calls `run_novig_odds_refresh()` on its own
    hourly clock for the life of the process -- the actual "keep this
    current" piece, not a one-shot boot probe.

    NOT a tick inside `run_refresh_worker.py`'s own main loop -- that loop is
    Kalshi's real-money live-trading cadence, and this lane holds only a
    NARROW claim on that file for small, additive, boot-time hooks (see
    `.syndicate/lanes.md`). A self-contained background thread, the same
    pattern `syndicate/app.py::_bootstrap_render_data` already uses for its
    own periodic-shaped work, gets genuine hourly recurrence without
    widening this lane's footprint in a file another lane depends on for
    something with real money behind it.

    **OFF BY DEFAULT** (`SYNDICATE_NOVIG_ODDS_REFRESH_ON_BOOT`) even though
    `novig_odds_enabled()` itself defaults on -- a NEW recurring background
    job touching a shared worker process for the first time gets one
    deliberate opt-in before it becomes unconditional, matching this repo's
    own measure-before-you-trust-it culture. Once the first real cycle's
    logs are read, flipping this to "on" is a plain env-var change.

    Returns whether the thread was actually started, so the caller can log
    it as a real fact rather than assuming.
    """
    raw = os.environ.get("SYNDICATE_NOVIG_ODDS_REFRESH_ON_BOOT")
    if raw is None or str(raw).strip().lower() in {"0", "false", "no", "off"}:
        return False

    def _loop() -> None:
        import time

        while True:
            try:
                run_novig_odds_refresh()
            except Exception as exc:  # noqa: BLE001 -- a loop iteration must never kill the thread
                print(f"[novig_odds] LOOP_ITERATION_FAILED {type(exc).__name__}: {exc}", flush=True)
            time.sleep(check_interval_seconds())

    threading.Thread(target=_loop, name="novig-odds-refresh", daemon=True).start()
    print("[novig_odds] BACKGROUND_LOOP_STARTED", flush=True)
    return True
