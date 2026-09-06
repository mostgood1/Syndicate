"""Refresh Kalshi's own prices for the sports series, on a schedule.

THE PIECE THAT MAKES KALSHI A REAL PRICE SOURCE. `kalshi_discovery` answers
"what does Kalshi list" once per boot; this keeps the PRICES current, which is
what a portfolio decision actually needs. A price fetched at boot and reused for
four hours is not a quote, it is a memory.

--------------------------------------------------------------------------
TWO FETCH STRATEGIES, AND IT REPORTS WHICH ONE WORKED
--------------------------------------------------------------------------

The unfiltered listing is 99.5% multi-leg parlay combinations (39,793 of the
first 40,000, measured 2026-08-23) and it TRUNCATES before reaching most single
markets. So paging everything is not viable: it measures the page cap, not the
catalogue.

The obvious fix is to ask for one series at a time. Whether `series_ticker` is
accepted as a query parameter is NOT something I have verified -- and the
failure mode if it is silently ignored is the worst kind: the request succeeds,
returns the unfiltered firehose, and the first page is all parlays, so the
series looks empty. That reads as "Kalshi delisted it" and is wrong.

So the fetch tries the filter and CHECKS whether it was honoured, by looking at
what came back rather than at the status code. `strategy` on the result says
which path produced the data, and a filter that was ignored is reported as
ignored rather than counted as an empty series.

--------------------------------------------------------------------------
KALSHI KEEPS ITS OWN CLOCK
--------------------------------------------------------------------------

This used to run once per board build, ~every 3 minutes, because that is when
the caller happened to call it. That is the wrong owner of the cadence in both
directions: OddsAPI's rate limit is what throttles the board build, and Kalshi
is not OddsAPI -- but Kalshi has its own limit, and an unpaced loop over its
series is what produced the `http_429`s on 2026-08-23.

So the interval is stated here, defaults to hourly, and is enforced against a
PERSISTED stamp rather than a process-local one: a worker restart must not
reset the clock and re-fetch, or the cadence is "hourly, plus once per deploy".

When the interval has not elapsed, this returns the LAST FETCHED MARKETS from
the artifact rather than an empty list. `status` says `cached` so the difference
is visible, but the board still gets prices -- skipping the join for 57 minutes
out of every hour would be a strictly worse board in exchange for nothing.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from collections.abc import Mapping, Sequence
from typing import Any

def default_sports_series() -> tuple[str, ...]:
    """Every series we price: hand-registered PLUS auto-discovered.

    Adding a sport is one registry line, and discovery adds the rest from
    Kalshi's own catalogue. The fetch, the join and the venue scope all read
    this one function, so none of them can drift from the others.
    """
    from syndicate.features.shared.kalshi_catalogue import all_series

    return tuple(sorted(all_series()))


def sports_series() -> tuple[str, ...]:
    """The series to price. Overridable WITHOUT a deploy.

    `discover()` finds new series at runtime, and the useful response is to
    start pricing them -- which should not need a code change, because the
    history a new series accumulates only starts when we first ask for it. A
    dashboard env var costs nothing; a `render.yaml` edit fires `blueprint_sync`
    and rewrites every key on every service (`#284`).
    """
    raw = str(os.environ.get("SYNDICATE_KALSHI_SERIES") or "").strip()
    if not raw:
        return default_sports_series()
    parsed = tuple(part.strip().upper() for part in raw.split(",") if part.strip())
    # An override that parses to nothing is a typo, not an instruction to price
    # nothing. Falling through to an empty tuple would silently stop the feed.
    return parsed or default_sports_series()


def kalshi_odds_enabled() -> bool:
    """Default ON. Read-only price data, no credential, nothing tradeable."""
    raw = os.environ.get("SYNDICATE_KALSHI_ODDS_ENABLED")
    if raw is None:
        return True
    return str(raw).strip().lower() not in {"0", "false", "no", "off"}


# TWO MINUTES, not an hour. The hourly default was written when the only
# consumer was a next-day opening line, and it is the wrong number entirely for
# acting on a live game: a rebounds line moves every possession, and a price
# fetched an hour ago is a memory being sent as a limit order.
#
# Affordable now because reads are SIGNED -- the 429s that forced pacing were
# on the anonymous quota. Per-series, so the cost is one call per series per
# interval and the per-tick cap only smooths the burst.
DEFAULT_REFRESH_INTERVAL_SECONDS = 120
# A failed fetch retries sooner than a successful one -- but not immediately.
FAILED_RETRY_SECONDS = 600


def refresh_interval_seconds() -> int:
    """How often to hit Kalshi. Hourly unless told otherwise.

    A bad value falls back to the default rather than to 0. `int("")` raising
    into a bare except that returns 0 would turn a typo into an unpaced loop
    against a venue that rate-limits us -- the failure this gate exists for.
    """
    raw = os.environ.get("SYNDICATE_KALSHI_REFRESH_INTERVAL_SECONDS")
    try:
        parsed = int(str(raw).strip())
    except (TypeError, ValueError):
        return DEFAULT_REFRESH_INTERVAL_SECONDS
    return parsed if parsed >= 0 else DEFAULT_REFRESH_INTERVAL_SECONDS


def markets_from_state(payload: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """Every stored market, merged from the per-series entries.

    The artifact stores markets ONCE, under `series[<ticker>]["markets"]`.
    It used to also store the concatenation under `markets`, which doubled a
    document that has a hard 8MB ceiling and took it to 13.3MB -- at which
    point the store refused and the artifact stopped being written entirely.

    Falls back to a legacy top-level `markets` key so a payload written before
    this change still reads, rather than a deploy silently emptying the board.
    """
    if not payload:
        return []
    series = payload.get("series")
    if isinstance(series, Mapping):
        out: list[dict[str, Any]] = []
        for entry in series.values():
            if isinstance(entry, Mapping):
                out.extend(entry.get("markets") or [])
        if out:
            return out
    legacy = payload.get("markets")
    return list(legacy) if isinstance(legacy, list) else []


def markets_artifact_path():
    from syndicate.features.shared.refresh_state_store import reports_root

    return reports_root() / "intelligence" / "kalshi_markets.json"


def _seconds_since(stamp: Any) -> float | None:
    if not stamp:
        return None
    try:
        parsed = datetime.strptime(str(stamp), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None
    return (datetime.now(timezone.utc) - parsed).total_seconds()


def fetch_series_markets(series: str) -> dict[str, Any]:
    """One series' current markets, by whichever strategy actually works.

    Returns `{"markets": [...], "strategy": ..., "reason": ...}` and never
    raises: one series failing must not cost the others their prices.
    """
    from syndicate.features.shared.kalshi_client import (
        KalshiError,
        fetch_series,
        series_from_ticker,
    )

    try:
        report = fetch_series(series)
    except KalshiError as exc:
        return {"markets": [], "strategy": "failed", "reason": str(exc)}

    # A BUDGET STOP IS NOT AN EMPTY BOOK. `fetch_markets` returns a PARTIAL
    # result rather than raising, and the caller below treats an empty
    # successful read as "no open markets" and lets the series go dormant for an
    # hour. Naming it here keeps `read_succeeded` False so a truncated fetch can
    # never blank a series off the board.
    if report.get("budget_exceeded"):
        return {"markets": [], "strategy": "budget", "reason": "request_budget_exhausted"}

    markets = report.get("markets") or []
    # DID THE FILTER ACTUALLY APPLY? Checked against the data, not the status
    # code. If the API ignored `series_ticker` we get the unfiltered firehose,
    # whose first page is parlays -- which would look like an empty series.
    matching = [m for m in markets if series_from_ticker(m.get("ticker")) == series]
    if markets and not matching:
        return {
            "markets": [],
            "strategy": "filter_ignored",
            "reason": f"asked for {series}, got {len(markets)} markets none of which are in it",
            "returned": len(markets),
        }
    return {
        "markets": matching,
        "strategy": "series_filter",
        "truncated": bool(report.get("truncated")),
    }


# RAISED FROM 12, because the cap was doing a job that now has its own tool.
#
# 12 was never a rate limit -- it was the ONLY burst control, chosen so thirty
# HTTP calls could not leave in one second (the 2026-08-23 http_429s). With
# explicit spacing below, the burst is bounded by time rather than by count,
# so the cap can be what it should always have been: how much of the book we
# refresh per tick.
#
# THESE CALLS ARE FREE. Kalshi and Polymarket are direct APIs, unlike OddsAPI
# whose per-call cost is what paces the rest of the board build. So the right
# cadence here is "as often as the venue tolerates", and fresher exchange
# prices are also what lets us lean less on the metered feed over time.
#
# 60 x 150ms = 9 seconds of wall clock per tick, which a worker can absorb.
#
# RAISED TO 150 on 2026-08-25, because the registry grew and the cap became the
# binding constraint on freshness rather than the rate limit. Measured that
# evening: `AUTO_SERIES game_series=204 total_discovered=212` after the soccer
# competitions registered, against 60 slots per 120s tick -- a full sweep took
# roughly SEVEN MINUTES, so a live line could be seven minutes old before it
# was even looked at.
#
# The bound that matters is the RATE, not the count: 150 x 150ms = 22.5s of
# wall clock per tick inside a 120s cadence, still ~6.7 requests/second
# sustained, an order of magnitude under the burst that drew the 429. Dormant
# series cost nothing here -- they are backed off to hourly by
# `DEFAULT_DORMANT_INTERVAL_SECONDS` -- so in practice this is "every live
# series, every tick", which is what the user asked for and what free calls
# make affordable.
DEFAULT_SERIES_PER_TICK = 150

# Minimum gap between two series fetches, in milliseconds.
#
# THE THING THE CAP WAS STANDING IN FOR. `#` 2026-08-23: an unpaced loop put
# thirty requests out in about a second and Kalshi answered http_429. A cap
# fixes that only by accident -- it bounds the COUNT, not the RATE, so raising
# it for freshness would have reintroduced the burst exactly.
#
# 150ms is ~6.7 requests/second sustained, an order of magnitude below the
# burst that drew the 429 and slow enough that a much larger cap stays safe.
DEFAULT_REQUEST_SPACING_MS = 150

# How often a DORMANT series may be re-fetched -- one whose last successful
# read returned zero markets.
#
# THIS IS WHERE THE BUDGET WAS GOING. Measured 2026-08-25T16:41:09Z, all twelve
# slots in a tick went to `KXATTENDMLB`, `KXMLBASGAME`, `KXMVENBASINGLEGAME`,
# `KXNBA1HSPREAD` and friends -- attendance markets, the All-Star game, parlays
# and NBA quarter lines in AUGUST, every one returning zero -- while live
# series sat 39.6 hours stale.
#
# `d58cb0b8c` stopped them monopolising the queue. This stops them CONSUMING it
# at all on most ticks: an out-of-season series is worth checking hourly, not
# every two minutes, and the budget it frees goes to series that have markets.
# The effective per-tick load becomes "the series that are actually live",
# which is what makes a high cadence affordable.
DEFAULT_DORMANT_INTERVAL_SECONDS = 3600

# Total markets kept in the artifact. The keyvalue store refuses at 8MB and
# `layer2_shortlist` already sits at 5.7MB of that budget, so an unbounded
# multi-sport catalogue is a write that starts failing silently one sport from
# now. Trimmed OLDEST-SERIES-FIRST and reported, never silently.
MAX_STORED_MARKETS = 6000

# The slots each SPORT is guaranteed before the rest compete on staleness.
# 6,000 / 300 supports 20 sports, comfortably above the eight this platform
# carries, so the floor can never oversubscribe the budget.
PER_SPORT_FLOOR_MARKETS = 300

# Board-demand samples kept, and how far back they count. Sized so a full slate
# observed within the window survives a run of smaller future-date builds
# between it and the next trim -- which is exactly what overwrote it once.
_DEMAND_SAMPLE_LIMIT = 12
_DEMAND_WINDOW_SECONDS = 6 * 3600

# Markets kept per series in the JOIN'S WORKING SET.
#
# MEASURED 2026-08-25T17:53:48Z, the tick after the queue started rotating:
#
#   KEYVALUE_WRITE_REJECTED size_bytes=13315551 max_bytes=8388608
#   WRITE_FAILED ... Shrink the payload rather than raising the ceiling
#   COMPOSITION under=series KXNCAAFSPREAD=2306569 KXNCAAFWINS=645981
#                            KXNCAAFGAME=635691 KXNCAAFAWARD=506778
#
# The artifact stopped being written AT ALL, so the board fell back to the
# last good write. One series -- `KXNCAAFSPREAD`, a spread ladder with every
# rung of every game -- was 2.3MB on its own.
#
# THIS BOUND IS SAFE ONLY BECAUSE CAPTURE MOVED. `venue_daily_odds` records
# every market the venue lists, dated and split per sport, and wrote fine on
# the same tick (`files=23`). So this artifact no longer has to be the record
# of what Kalshi offers -- it is the working set the JOIN prices against, and a
# working set may be bounded where a record may not. That separation is what
# the capture-first layer bought.
MAX_MARKETS_PER_SERIES = 400
# How many capped series `PRECAP_CUT_BY_DATE` names. The count of capped series
# and the total cut are ALWAYS printed, so this bounds the log without letting a
# partial list impersonate a complete one.
MAX_CAP_COST_SERIES = 12


def request_spacing_seconds() -> float:
    """Seconds to wait between two series fetches. Never negative."""
    raw = os.environ.get("SYNDICATE_KALSHI_REQUEST_SPACING_MS")
    try:
        parsed = float(str(raw).strip())
    except (TypeError, ValueError):
        parsed = float(DEFAULT_REQUEST_SPACING_MS)
    if parsed != parsed or parsed < 0:
        # A bad value must not become an UNPACED loop -- that is the failure
        # this exists to prevent, so it falls back rather than to zero.
        parsed = float(DEFAULT_REQUEST_SPACING_MS)
    return parsed / 1000.0


def dormant_interval_seconds() -> int:
    """How often a series whose last read returned nothing may be re-checked."""
    raw = os.environ.get("SYNDICATE_KALSHI_DORMANT_INTERVAL_SECONDS")
    try:
        parsed = int(str(raw).strip())
    except (TypeError, ValueError):
        return DEFAULT_DORMANT_INTERVAL_SECONDS
    return parsed if parsed >= 0 else DEFAULT_DORMANT_INTERVAL_SECONDS


DEFAULT_REFRESH_BUDGET_SECONDS = 30
# Discovery's slice of a tick. Small on purpose: it is a catalogue refresh, and
# the prices are what the board reads.
DISCOVERY_BUDGET_SECONDS = 5.0


def refresh_budget_seconds() -> float:
    """AGGREGATE wall-clock this refresh may spend on venue requests. 0 = off.

    SIZED FROM MEASUREMENT, not picked (2026-09-02, lane
    `kalshi-discovery-deadline`). A COLD tick -- every series due, so
    `series_per_tick()` = 150 of them -- cost **50.1s** with spacing forced to
    0, and ~72s at the default 150ms spacing. Nothing measured that, and
    `max_pages` cannot: it bounds ONE call's paging, and this loop makes 150
    calls.

    30s admits roughly 30 / (0.24s request + 0.15s spacing) ~= 77 series, so a
    cold start DRAINS OVER ~2 TICKS instead of blocking one board build for a
    minute-plus, and a warm tick (a handful of series due) never approaches it.
    Raise it deliberately against those numbers; do not raise it because a tick
    got truncated once -- truncation here is the design working.
    """
    raw = os.environ.get("SYNDICATE_KALSHI_REFRESH_BUDGET_SECONDS")
    if raw is None or not str(raw).strip():
        return float(DEFAULT_REFRESH_BUDGET_SECONDS)
    try:
        parsed = float(str(raw).strip())
    except (TypeError, ValueError):
        return float(DEFAULT_REFRESH_BUDGET_SECONDS)
    return parsed if parsed >= 0 else float(DEFAULT_REFRESH_BUDGET_SECONDS)


def series_per_tick() -> int:
    """How many series may be fetched in ONE call to this function.

    NOT a rate limit and not the cadence -- `refresh_interval_seconds` is the
    cadence, per series. This only stops thirty HTTP calls leaving in one
    second, which is what produced the 2026-08-23 `http_429`s. The board build
    runs every ~2 minutes, so a due queue of any realistic size still drains
    inside one interval; this just spreads it out.
    """
    raw = os.environ.get("SYNDICATE_KALSHI_SERIES_PER_TICK")
    try:
        parsed = int(str(raw).strip())
    except (TypeError, ValueError):
        return DEFAULT_SERIES_PER_TICK
    return parsed if parsed > 0 else DEFAULT_SERIES_PER_TICK


def hot_refresh_interval_seconds() -> int:
    """How often a HOT series may be re-fetched. Much shorter than the rest.

    A series carrying real money is not the same kind of thing as one of the
    142 game-line series we have never priced, and giving them one clock is
    what produced ~26-minute-old quotes on the only markets that mattered.
    """
    raw = (os.environ.get("SYNDICATE_KALSHI_HOT_REFRESH_SECONDS") or "").strip()
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        return 30
    return parsed if parsed > 0 else 30


def hot_series() -> set[str]:
    """Series we have MONEY or a POSITION in, and must not price off a stale quote.

    THE ECONOMY PROBLEM, measured 2026-08-24: 155 series against a cap of 12 a
    tick means ~13 ticks to sweep, so any given quote can be ~26 minutes old.
    That is harmless for a series nobody is trading and unacceptable for one
    with a resting order against it -- and the old queue could not tell them
    apart, because it ordered by AGE alone.

    Derived from the LEDGER rather than configured, so it follows the money
    automatically: a series stops being hot when its order stops being open,
    with no list for anyone to update. `SYNDICATE_KALSHI_HOT_SERIES` adds to it
    for a series we want watched before we have traded it.

    Fails to the EMPTY SET, never to an exception: a hot list we cannot compute
    must degrade to the ordinary schedule, not stop the refresh.
    """
    found: set[str] = set()

    extra = (os.environ.get("SYNDICATE_KALSHI_HOT_SERIES") or "").strip()
    for token in extra.replace(",", " ").split():
        if token:
            found.add(token.strip().upper())

    try:
        from syndicate.features.shared.execution_ledger import (
            STATUS_FILLED,
            STATUS_SUBMITTED,
            _load,
        )
        from syndicate.features.shared.kalshi_client import series_from_ticker

        for order in (_load().get("orders") or []):
            # OPEN means the venue may still act on it, or we hold it and it is
            # not yet graded. A rejected or failed order is not money at risk.
            if str(order.get("status") or "") not in {STATUS_SUBMITTED, STATUS_FILLED}:
                continue
            if order.get("outcome"):
                # Already graded -- the price no longer decides anything.
                continue
            series = series_from_ticker(order.get("venue_ticker"))
            if series:
                found.add(str(series).strip().upper())
    except Exception as exc:
        print(
            f"[kalshi_odds] HOT_SERIES_UNAVAILABLE {type(exc).__name__}: {exc}",
            flush=True,
        )

    return found


def _is_dormant(entry: Mapping[str, Any]) -> bool:
    """Did this series' last successful read return nothing?

    `count` is stamped on every successful read, including an empty one, so
    `count == 0` is a POSITIVE statement ("we asked and there was nothing")
    rather than an absence. A series never fetched has no `count` and is NOT
    dormant -- it is unknown, and unknown must be asked at the normal cadence
    or a new series would wait an hour to be seen for the first time.
    """
    count = entry.get("count")
    return isinstance(count, int) and count == 0


def _due_series(
    state: dict[str, Any],
    wanted: tuple[str, ...],
    interval: int,
    *,
    dormant_interval: int | None = None,
) -> list[str]:
    """Which series have not been fetched within `interval`, oldest first.

    PER SERIES, which is the whole economy of this design. A single whole-fetch
    clock means the cost of adding a sport is a bigger burst on the same
    schedule; a per-series clock means the cost is exactly one more call per
    interval, and the per-tick cap decides only how bursty that is.

    Oldest first so a series that has been waiting cannot be starved by one that
    was just added -- with a cap and no ordering, the alphabetically-first N
    would refresh forever and the rest never would.
    """
    per_series = state.get("series") or {}
    due: list[tuple[float, str]] = []
    for series in wanted:
        entry = per_series.get(series) or {}
        age = _seconds_since(entry.get("fetched_at"))
        # A DORMANT SERIES WAITS LONGER. Its last successful read returned
        # nothing, so re-asking every two minutes spends the tick budget to
        # confirm that August still has no NBA quarter lines. Hourly is enough,
        # and the budget it frees goes to series that have markets -- which is
        # what makes a high cadence affordable on a free API.
        due_after = interval
        if dormant_interval is not None and _is_dormant(entry):
            due_after = max(interval, dormant_interval)
        if age is None:
            # Never fetched. Sorts ahead of everything -- a series with no
            # prices at all is worth more than a refresh of one that has them.
            due.append((float("inf"), series))
        elif age >= due_after:
            due.append((age, series))
    due.sort(key=lambda item: -item[0])
    return [series for _age, series in due]


def _backing_off(entry: Mapping[str, Any], interval: int) -> bool:
    """Did this series' LAST ATTEMPT fail, recently enough to wait?

    A failure is `attempted_at` moving without `fetched_at` moving with it --
    the two stamps are equal on success, so "the last attempt failed" is exactly
    "they disagree". Stated this way rather than as a chain of conditions
    because the chain it replaced was unreadable and I could not convince myself
    it was right.

    Failures back off on their own shorter clock. Ungated, a series that is
    403ing or rate-limiting us is retried every board build -- every ~2 minutes
    -- which is how the 2026-08-23 429s happened.
    """
    attempted = entry.get("attempted_at")
    if not attempted or attempted == entry.get("fetched_at"):
        return False
    since = _seconds_since(attempted)
    return since is not None and since < min(interval, FAILED_RETRY_SECONDS)


# Discovery has run in THIS process. Module-level because `_DISCOVERED` is
# module-level: registration does not cross the process boundary, and that is
# exactly the bug this exists to fix.
_DISCOVERY_DONE = False


def _unregistered_sport_series(
    titles: Mapping[str, Any],
    props: Mapping[str, Any],
    games: Mapping[str, Any],
) -> list[dict[str, str]]:
    """Series whose ticker names a sport we model but which nothing registered.

    The work list for coverage we do not even ATTEMPT. Bounded and sorted so
    the line stays readable; the count rides on the result so a truncated
    sample cannot read as the whole gap.
    """
    from syndicate.features.shared.kalshi_catalogue import (
        SERIES_OUT_OF_SCOPE,
        sport_for_ticker,
    )

    registered = {str(k).upper() for k in props} | {str(k).upper() for k in games}
    out: list[dict[str, str]] = []
    for ticker, title in (titles or {}).items():
        key = str(ticker or "").strip().upper()
        if not key or key in registered or key in SERIES_OUT_OF_SCOPE:
            continue
        sport = sport_for_ticker(key)
        if not sport:
            continue
        out.append({"series": key, "sport": sport, "title": str(title or "")[:60]})
    out.sort(key=lambda row: (row["sport"], row["series"]))
    return out


def ensure_series_discovered(*, force: bool = False) -> dict[str, Any]:
    """Register every series Kalshi lists that we can price, IN THIS PROCESS.

    THE BUG THIS FIXES, measured 2026-08-24T01:35:57Z:

        BOARD_JOIN kalshi_markets=203 board_rows=513 matched=0
          reasons={'market_is_for_another_date': 67, 'no_matching_board_row': 136}

    203 markets from SEVEN hand-registered series, and not one game line among
    them -- no `game_lines_disabled` in the refusals at all, on a build where
    the flag was on. Discovery had run, found football and NBA and registered
    thirteen series... on live-odds-worker, which does not do the join. The
    join runs here, on refresh-worker, where `_DISCOVERED` was empty.

    `register_discovered` writes to a module-level dict, so a boot-time call in
    one worker is invisible to the other. Putting discovery in the REFRESH
    rather than in a worker's boot means any process that prices Kalshi gets
    the same series list, which is what `default_sports_series`'s docstring
    already promised: "The fetch, the join and the venue scope all read this
    one function, so none of them can drift."

    Once per process. The catalogue is 13,389 series and changes on the order
    of days, so re-reading it every two minutes would be a lot of bytes to
    re-learn the same thing -- and a failure here must never take down a
    refresh that can still run on the hand-registered series.
    """
    global _DISCOVERY_DONE
    if _DISCOVERY_DONE and not force:
        return {"status": "skipped", "reason": "already_discovered"}

    try:
        from syndicate.features.shared.kalshi_catalogue import (
            auto_game_series_from_catalogue,
            auto_series_from_catalogue,
            register_discovered,
        )
        from syndicate.features.shared.kalshi_client import discover_series

        report = discover_series()
        if report.get("status") != "ok":
            # NOT marked done: a failed catalogue read must be retried, or one
            # 429 at boot leaves the process pricing seven series forever.
            return {"status": "error", "reason": str(report.get("errors") or "catalogue_unavailable")}

        titles = report.get("titles") or {}
        props = auto_series_from_catalogue(titles)
        games = auto_game_series_from_catalogue(titles)
        added_props = register_discovered(props)
        added_games = register_discovered(games)
        _DISCOVERY_DONE = True

        # WHAT THE CATALOGUE LISTS AND WE NEVER FETCH.
        #
        # Registration is the FIRST gate: a series that does not register is
        # never added to `sports_series()`, never fetched, and therefore
        # invisible to every counter downstream -- it cannot appear in
        # `unreadable_title`, in `BOARD_JOIN` reasons, or anywhere else. The
        # only symptom is a board row that never gets a price, which reads as
        # "Kalshi does not offer this".
        #
        # That is exactly how `KXMLBGAME` hid: its title is "Professional
        # Baseball Game", `_GAME_CORE` had no entry for the bare word "game",
        # and the moneyline -- the single most valuable market on the venue --
        # was unreachable across every sport until a user found a live market
        # the diagnostics said did not exist.
        #
        # MEASURED 2026-08-25: `KXMLBTOTAL` appears NOWHERE in the logs, while
        # `KXWNBATOTAL` fetches 45 markets. A board row for `totals over 7.5`
        # on an MLB game therefore has no Kalshi market to join to, and the
        # order fails `no_live_price` -- which is what every Kalshi order today
        # did.
        #
        # So: name the sport-token series the catalogue carries that we did NOT
        # register, with their titles, so the next grammar is written from
        # Kalshi's own words rather than from a guess about them.
        unregistered = _unregistered_sport_series(titles, props, games)
        if unregistered:
            print(
                "[kalshi_odds] SERIES_UNREGISTERED"
                f" n={len(unregistered)}"
                f" sample={unregistered[:14]}",
                flush=True,
            )

        return {
            "status": "ok",
            "catalogue": int(report.get("count") or 0),
            "prop_series": len(props),
            "game_series": len(games),
            "added": len(added_props.get("added") or {}) + len(added_games.get("added") or {}),
            "unregistered": len(unregistered),
        }
    except Exception as exc:
        return {"status": "error", "reason": f"{type(exc).__name__}: {exc}"}


def _sport_slot_caps(
    sports: list[str],
    demand: Mapping[str, int] | None,
) -> dict[str, int] | None:
    """How many of `MAX_STORED_MARKETS` each sport may take, by BOARD DEMAND.

    A FLAT FLOOR IS THE WRONG SHAPE, and this is the failure the flat one could
    not see. Measured 2026-08-27 during NCAAF opening week, with the floor
    already live:

        kept_by_sport={mlb: 648, nba: 6, ncaaf: 1896, nfl: 2083, soccer: 1067, wnba: 300}
        board demand  ={mlb: 400, soccer: 400, wnba: 400, nfl: 88, ncaaf: 42}

    ~4,000 of 6,000 slots held markets for 130 board rows while 1,200 rows
    shared the rest, because Kalshi's far-dated football catalogue is FRESH and
    staleness ordering rewards that. `BOARD_JOIN matched` fell 210 -> 5 under
    the pure-staleness trim that preceded the floor, and the floor recovered it
    only to 13-24. Freshness is not relevance: a market for a game three weeks
    out is perfectly fresh and cannot be joined to today's board.

    THE FLOOR SURVIVES AS A MINIMUM, deliberately. Demand is measured from the
    LAST join, so a sport whose slate opens between cycles has demand 0 and
    would otherwise be locked out of the working set that would let it be
    joined at all -- a self-fulfilling zero. The floor is what stops that.

    Returns None when there is no demand signal, which keeps the caller on the
    flat-floor path rather than inventing a distribution from nothing.
    """
    totals = {
        sport: int(count)
        for sport, count in (demand or {}).items()
        if isinstance(count, (int, float)) and int(count) > 0
    }
    if not totals or not sports:
        return None

    floor_total = min(len(sports) * PER_SPORT_FLOOR_MARKETS, MAX_STORED_MARKETS)
    remaining = max(0, MAX_STORED_MARKETS - floor_total)
    demand_total = sum(totals.get(sport, 0) for sport in sports)

    caps: dict[str, int] = {}
    for sport in sports:
        share = 0
        if demand_total > 0:
            share = int(remaining * (totals.get(sport, 0) / demand_total))
        caps[sport] = min(PER_SPORT_FLOOR_MARKETS, MAX_STORED_MARKETS) + share
    return caps


def _trim_to_storage_bounds(
    per_series_markets: list[tuple[float, str, list[dict[str, Any]]]],
    demand: Mapping[str, int] | None = None,
) -> tuple[list[dict[str, Any]], int, dict[str, int]]:
    """Fit the working set into `MAX_STORED_MARKETS`, guaranteeing each sport a floor.

    EXTRACTED SO IT CAN BE TESTED. It was inline in a 200-line function, and the
    first test written against it had to `skip` -- a green test that proves
    nothing, which is the failure this module's own comments keep naming.

    STALENESS IS THE RIGHT ORDER AND THE WRONG BUDGET. Freshest-first is what
    the trim always claimed, and it is correct for choosing WITHIN a sport. It
    is wrong ACROSS sports: MLB carries 14 registered series, so on volume alone
    it can fill all 6,000 slots and every soccer market falls off -- not because
    it is stale, but because it queued behind a bigger sport.

    MEASURED 2026-08-27: kalshi served 173 soccer quotes at 15:0xZ
    (`h2h_keyed_by_team:149`) and ZERO an hour later
    (`no_kalshi_market_classified_to_this_sport`) while its MLB set was 2,189
    keys. `selected_by_sport['soccer']` carried no kalshi entry at all, and a
    board cannot price a venue that appears and disappears.

    THE FLOOR IS A GUARANTEE, NEVER A RESERVATION. A sport with fewer markets
    than the floor takes what it has and the unused slots go to whoever else
    wants them -- holding them empty would trade one sport's starvation for
    everyone's.

    Returns `(markets, trimmed, kept_by_sport)`; the caller reports all three.
    """
    from syndicate.features.shared.kalshi_catalogue import sport_for_series

    ordered = sorted(per_series_markets, key=lambda item: item[0])
    all_markets: list[dict[str, Any]] = []
    kept_by_sport: dict[str, int] = {}
    trimmed = 0
    remainder: list[tuple[str, list[dict[str, Any]]]] = []

    sport_of = {
        series: (str(sport_for_series(series) or "").strip().lower() or "unmapped")
        for _age, series, _m in ordered
    }
    caps = _sport_slot_caps(sorted(set(sport_of.values())), demand)

    for _age, series, markets in ordered:
        sport = sport_of[series]
        held = kept_by_sport.get(sport, 0)
        # DEMAND-WEIGHTED when the last join told us what the board asks for,
        # flat floor when it did not. Either way the FLOOR is the minimum, so a
        # sport whose slate opens between cycles is never locked out.
        allowance = caps.get(sport, PER_SPORT_FLOOR_MARKETS) if caps else PER_SPORT_FLOOR_MARKETS
        room = min(
            max(0, allowance - held),
            max(0, MAX_STORED_MARKETS - len(all_markets)),
        )
        take = markets[:room] if room else []
        if take:
            all_markets.extend(take)
            kept_by_sport[sport] = held + len(take)
        if len(take) < len(markets):
            # Whatever the floor did not take is still eligible below, in the
            # same staleness order -- never dropped here. The SPORT is carried
            # through rather than re-derived, so the second pass can keep the
            # tally honest without calling `sport_for_series` twice per series.
            remainder.append((sport, markets[len(take):]))

    for sport, markets in remainder:
        if len(all_markets) >= MAX_STORED_MARKETS:
            trimmed += len(markets)
            continue
        room = MAX_STORED_MARKETS - len(all_markets)
        if len(markets) > room:
            trimmed += len(markets) - room
            markets = markets[:room]
        all_markets.extend(markets)
        # COUNTED HERE TOO, and this is a bug fix rather than a nicety. The
        # first cut updated the tally only in the FLOOR pass, so production
        # printed `kept=6000 ... kept_by_sport={...}` summing to 1,506 -- a
        # reader had every reason to think 4,494 markets had vanished. A
        # breakdown that does not reconcile with its own total is the
        # "count that looks like coverage" failure this file keeps naming,
        # and it was in the line written to prove the floor worked.
        kept_by_sport[sport] = kept_by_sport.get(sport, 0) + len(markets)

    return all_markets, trimmed, kept_by_sport


def run_kalshi_odds_refresh(*, force: bool = False) -> dict[str, Any]:
    """Bounded wrapper. The AGGREGATE budget lives here, at the only place that
    knows a whole tick is one unit of work -- `max_pages` bounds one call's
    paging and this loop makes up to `series_per_tick()` (150) of them.

    Applied for EVERY caller (`intelligence_state`'s board build,
    `run_live_odds_refresh_worker`, `venue_odds_loop`) rather than at each call
    site, so a new caller inherits the bound instead of having to remember it.
    """
    from syndicate.features.shared.kalshi_client import request_budget

    budget = refresh_budget_seconds()
    if budget <= 0:
        return _run_kalshi_odds_refresh_unbounded(force=force)
    with request_budget(budget):
        return _run_kalshi_odds_refresh_unbounded(force=force)


def _run_kalshi_odds_refresh_unbounded(*, force: bool = False) -> dict[str, Any]:
    """Refresh whichever series are due, merge, record, write.

    Returns EVERY series' markets, not just the ones fetched this call. With a
    per-series clock the alternative is that three quarters of the board's
    Kalshi prices vanish on every tick -- the merge is not an optimisation, it
    is what makes a staggered fetch usable at all.

    `force=True` bypasses the enable flag, the per-series clock and the
    per-tick cap: that is what a manual probe wants.
    """
    from syndicate.features.shared.kalshi_client import budget_remaining, request_budget
    if not (force or kalshi_odds_enabled()):
        return {"status": "skipped", "reason": "disabled"}

    # BEFORE `sports_series()` is read, because it decides what that returns.
    # DISCOVERY GETS A SHARE, NOT THE WHOLE TICK. It runs before the price
    # loop, so without its own sub-budget one slow catalogue call spends
    # everything and the series fetches -- the actual work -- get nothing.
    # Observed exactly that while testing this wiring: a discovery timeout left
    # `BUDGET_STOP fetched=0 unattempted=25`. `request_budget` nests by keeping
    # the TIGHTER deadline, so this can only ever shrink the outer bound.
    _tick_budget = refresh_budget_seconds()
    if _tick_budget > 0:
        with request_budget(min(DISCOVERY_BUDGET_SECONDS, _tick_budget * 0.2)):
            discovery = ensure_series_discovered()
    else:
        discovery = ensure_series_discovered()
    if discovery.get("status") == "ok":
        print(
            f"[kalshi_odds] SERIES_DISCOVERY catalogue={discovery.get('catalogue')}"
            f" prop_series={discovery.get('prop_series')}"
            f" game_series={discovery.get('game_series')}"
            f" added={discovery.get('added')}",
            flush=True,
        )
    elif discovery.get("status") == "error":
        # Named, and NOT fatal -- the hand-registered series still price.
        print(
            f"[kalshi_odds] SERIES_DISCOVERY_FAILED reason={discovery.get('reason')}",
            flush=True,
        )

    from syndicate.features.shared.kalshi_catalogue import game_date_from_ticker
    from syndicate.features.shared.refresh_state_store import read_json_file, write_json_file

    path = markets_artifact_path()
    try:
        state = read_json_file(path) or {}
    except Exception:
        state = {}
    per_series: dict[str, Any] = dict(state.get("series") or {})

    wanted = sports_series()
    interval = refresh_interval_seconds()

    # HOT FIRST, on their own shorter clock. Without this a series with a
    # resting order waits behind up to 150 nobody is trading, because the queue
    # ordered by age alone and could not tell the two apart.
    hot = hot_series() & set(wanted)
    hot_due = (
        list(hot)
        if force
        else _due_series(state, tuple(sorted(hot)), hot_refresh_interval_seconds())
    )
    due = (
        wanted
        if force
        else _due_series(state, wanted, interval, dormant_interval=dormant_interval_seconds())
    )

    # A failed series backs off on its OWN shorter clock. Without this a venue
    # that is 403ing or rate-limiting us is retried every board build -- every
    # ~2 minutes -- which is how the 2026-08-23 429s happened.
    if not force:
        due = [s for s in due if not _backing_off(per_series.get(s) or {}, interval)]

    cap = series_per_tick()
    if force:
        fetching = due
    else:
        # Hot series are fetched IN ADDITION to the cap, not out of it. They
        # are few -- bounded by the per-day order cap -- and letting them
        # consume the cold budget would starve discovery of exactly the markets
        # we are not yet trading but might.
        cold = [s for s in due if s not in set(hot_due)]
        fetching = hot_due + cold[:cap]
    if hot_due:
        print(
            f"[kalshi_odds] HOT_SERIES n={len(hot_due)} series={sorted(hot_due)[:8]}"
            f" interval_s={hot_refresh_interval_seconds()}",
            flush=True,
        )

    fetched: dict[str, Any] = {}
    spacing = request_spacing_seconds()
    budget_stopped = 0
    for index, series in enumerate(fetching):
        # BEFORE the request, not after. A series we never attempt keeps its old
        # `attempted_at`, so it stays DUE and the next tick picks it up -- the
        # queue drains rather than skipping. Stamping it here, or letting a
        # partial fetch through, would mark it a successful empty read and take
        # it off the board for `dormant_interval_seconds`.
        remaining = budget_remaining()
        if remaining is not None and remaining <= 0.0:
            budget_stopped = len(fetching) - index
            break
        # SPACING, NOT A SMALLER CAP. The cap bounds how many; only this bounds
        # how FAST, and the 2026-08-23 http_429s came from rate, not count.
        # Skipped before the first call so a one-series tick pays nothing.
        if index and spacing:
            time.sleep(spacing)
        result = fetch_series_markets(series)
        if result.get("strategy") == "budget":
            # Belt and braces: the pre-check above should mean we never get
            # here. Write NO state for this series and stop.
            budget_stopped = len(fetching) - index
            break
        markets = result.get("markets") or []
        entry = dict(per_series.get(series) or {})
        entry["attempted_at"] = _now_stamp()
        entry["strategy"] = result.get("strategy")
        entry["reason"] = result.get("reason")
        # AN EMPTY SERIES IS A SUCCESSFUL READ OF AN EMPTY BOOK, and telling
        # that apart from a FAILED read is what keeps this queue moving.
        #
        # `fetched_at` used to move only when markets came back. The intent was
        # right -- a failure that stamped it would blank the series for an
        # interval AND start its clock. But a series that genuinely has no open
        # markets never got stamped either, so `_due_series` saw `age=None`,
        # sorted it at `inf` ahead of everything, and it returned to the front
        # of the queue on EVERY tick, forever. Backoff cannot absorb that: it
        # lasts `min(interval, FAILED_RETRY_SECONDS)` and ticks are ~15 minutes
        # apart, so it has always expired.
        #
        # MEASURED 2026-08-25T16:41:09Z and again at 16:56:45Z, identical:
        #
        #   TICK series_wanted=191 due=191 fetched=12 cap=12 markets=883
        #     this_tick={'KXATTENDMLB': (0,'series_filter'),
        #                'KXMLBASGAME': (0,'series_filter'),
        #                'KXMVENBASINGLEGAME': (0,'series_filter'),
        #                'KXNBA1HSPREAD': (0,'series_filter'), ...}  ALL ZERO
        #     oldest_s=142655
        #
        # Twelve of twelve slots spent on attendance markets, the All-Star
        # game, parlay series and NBA quarter lines in AUGUST -- while the
        # oldest live series sat 39.6 HOURS stale. The whole per-tick budget,
        # every tick, on series that can never return anything this month.
        #
        # It also inverts the economy of auto-discovery: every newly registered
        # out-of-season series joins the permanent front of the queue, so
        # REGISTERING MORE SERIES MAKES COVERAGE WORSE. That is the mechanism
        # behind "whack-a-mole" -- not a missing grammar, a starved queue.
        #
        # So the stamp follows the READ, not the payload: a strategy that ran
        # and returned an empty list is fetched. `filter_ignored` and `failed`
        # still leave the stamps disagreeing, which is what `_backing_off`
        # reads, so a real failure behaves exactly as before.
        read_succeeded = result.get("strategy") == "series_filter"
        if markets:
            entry["markets"] = markets
            entry["count"] = len(markets)
        elif read_succeeded:
            # Keep the last known markets rather than blanking: an empty read
            # is "nothing open right now", not "the previous prices were
            # wrong". `_seconds_since(fetched_at)` still ages them, and the
            # merge reports `oldest_s`, so staleness stays visible.
            entry["count"] = 0
        if markets or read_succeeded:
            entry["fetched_at"] = entry["attempted_at"]
        per_series[series] = entry
        fetched[series] = {"count": len(markets), "strategy": result.get("strategy")}

    if budget_stopped:
        # VISIBLE, or a shrinking tick looks like a shrinking venue. The
        # un-attempted series keep their old stamps and are still due next tick.
        print(
            f"[kalshi_odds] BUDGET_STOP budget_s={refresh_budget_seconds()}"
            f" fetched={len(fetched)} unattempted={budget_stopped}"
            f" of={len(fetching)}",
            flush=True,
        )

    # MERGE. Every series' last good markets, whether or not it was fetched now.
    #
    # PER-SERIES BOUND FIRST, so one ladder cannot crowd out a whole sport.
    staleness: dict[str, int] = {}
    per_series_markets: list[tuple[float, str, list[dict[str, Any]]]] = []
    # EVERY MARKET, BEFORE ANY BOUND. This is what the daily book records, and
    # keeping it separate is the whole justification for bounding the working
    # set at all -- see `_record_daily_book`.
    full_markets: list[dict[str, Any]] = []
    trimmed = 0
    # WHAT THE PER-SERIES CAP COSTS, BY DATE, MEASURED ON THE MARKETS IT CUTS.
    #
    # `BY_GAME_DATE` is built from the WORKING SET, so it can only ever show
    # SURVIVORS. Reading the cut markets' dates off the kept markets' dates is
    # the same inference that produced `#370` and its diagnostic sequel: a
    # number that describes one population being read as if it described
    # another. This counts the cut ones directly, which is the only way the
    # question is answerable.
    #
    # It exists to gate a change rather than to decorate the log. Measured
    # 2026-08-26T01:49:32Z, `trimmed=8744` of 14,744 fetched -- 59% discarded
    # before the join runs -- with `KXMLBHRR` 1147 -> 400, `KXMLBTB` 879 -> 400
    # and `KXMLBHIT` 744 -> 400, all three series dated entirely to the board's
    # own slate. IF those cuts are mostly the board's date, re-prioritising
    # eviction recovers ~1,600 joinable markets; if they are mostly lookahead,
    # it recovers close to nothing. Same code either way, opposite verdicts, and
    # nothing already logged separates them.
    cap_cost: list[tuple[int, str, int, dict[str, int]]] = []
    for series in wanted:
        entry = per_series.get(series) or {}
        markets = list(entry.get("markets") or [])
        full_markets.extend(markets)
        if len(markets) > MAX_MARKETS_PER_SERIES:
            trimmed += len(markets) - MAX_MARKETS_PER_SERIES
            # THE CUT SLICE, before it stops existing. Dated with the SAME
            # function the join uses, so the two numbers are comparable; an
            # undatable ticker is named rather than dropped, for the reason
            # `board_by_game_date` gives at length.
            cut_dates: dict[str, int] = {}
            for cut_market in markets[MAX_MARKETS_PER_SERIES:]:
                cut_date = game_date_from_ticker(cut_market.get("ticker")) or "<undatable_ticker>"
                cut_dates[cut_date] = cut_dates.get(cut_date, 0) + 1
            cap_cost.append(
                (len(markets) - MAX_MARKETS_PER_SERIES, series, len(markets), cut_dates)
            )
            markets = markets[:MAX_MARKETS_PER_SERIES]
        age = _seconds_since(entry.get("fetched_at"))
        if age is not None:
            staleness[series] = int(age)
        per_series_markets.append((age if age is not None else float("inf"), series, markets))

    # BIGGEST LOSSES FIRST, and BOUNDED -- a per-tick line naming every capped
    # series would be the `MAX_UNREADABLE_SAMPLES` mistake again, where the
    # noisiest families reached the cap first and the interesting ones were
    # counted but never sampled. The TOTAL is always reported, so a bounded list
    # cannot read as a complete one.
    if cap_cost:
        cap_cost.sort(reverse=True)
        shown = cap_cost[:MAX_CAP_COST_SERIES]
        print(
            f"[kalshi_odds] PRECAP_CUT_BY_DATE capped_series={len(cap_cost)}"
            f" cut_total={sum(item[0] for item in cap_cost)}"
            f" shown={len(shown)}"
            f" detail={ {series: {'fetched': fetched, 'cut': cut_n, 'cut_by_date': dates} for cut_n, series, fetched, dates in shown} }",
            flush=True,
        )

    # THE TRIM IS BY STALENESS, WHICH IS WHAT THIS ALWAYS CLAIMED TO DO.
    #
    # It said "Trimmed OLDEST-SERIES-FIRST and reported, never silently" and
    # the code was `all_markets[:MAX_STORED_MARKETS]` -- the alphabetically
    # FIRST N, because `sports_series()` returns `sorted(...)`. `KXWNBA*` sorts
    # last, so the first thing a trim deleted was every WNBA market, silently,
    # while the comment said otherwise. Measured 2026-08-25T17:53:47Z:
    # `markets=6000 trimmed=605` with NCAAF alone contributing thousands.
    #
    # Freshest series are kept: a stale series' prices are the least useful
    # thing in the working set, which is the claim the docstring was making.
    all_markets, trimmed_now, kept_by_sport = _trim_to_storage_bounds(
        per_series_markets,
        demand=state.get("board_demand") if isinstance(state.get("board_demand"), Mapping) else None,
    )
    trimmed += trimmed_now
    if trimmed_now:
        print(
            f"[kalshi_odds] TRIM_BY_SPORT kept={len(all_markets)} trimmed={trimmed_now}"
            f" floor={PER_SPORT_FLOOR_MARKETS}"
            f" demand={dict(sorted((state.get('board_demand') or {}).items())) or None}"
            f" kept_by_sport={dict(sorted(kept_by_sport.items()))}",
            flush=True,
        )

    # THE COMPLETE SET, NOT THE WORKING SET.
    #
    # This was called with `all_markets` -- AFTER the per-series cap and the
    # staleness trim -- which quietly voided the argument that justified those
    # bounds. `6145522ee` said the 400-per-series cap "is safe ONLY because
    # capture moved: `venue_daily_odds` records every market the venue lists".
    # It did not: measured 2026-08-25T18:33:55Z, `trimmed=2121` markets never
    # reached the record, and `KXNCAAFSPREAD`'s ladder was truncated 1994 -> 400
    # in the one place that is supposed to keep whole ladders.
    #
    # A record that inherits the working set's bounds is not a record, and the
    # bound it was used to justify becomes real data loss. The two read from
    # different lists, and this call is placed BEFORE the persistence bound
    # below so that ordering is a fact rather than a comment.
    _record_daily_book(full_markets)

    # NOW SHRINK WHAT IS PERSISTED, having already recorded the whole book.
    #
    # The 400-per-series cap was applied only when BUILDING the working set;
    # `per_series[<ticker>]["markets"]` still held every market with every
    # field, and that dict is what gets written. MEASURED 2026-08-25T18:53:11Z:
    #
    #   KEYVALUE_WRITE_REJECTED size_bytes=8701075 max_bytes=8388608
    #   COMPOSITION series=9196911
    #     KXNCAAFSPREAD=2306201 KXNFLSPREAD=903759 KXNCAAFWINS=645977 ...
    #
    # So the artifact could not be written, `fetched_at` never persisted, and
    # the queue re-fetched the SAME 60 series every tick -- 18:42:40 and
    # 18:53:10 fetched byte-identical lists while `oldest_s` merely aged
    # (146660 -> 147291). A rotation that cannot record its own progress does
    # not rotate.
    #
    # A LEAN ROW, WHICH IS WHAT THE REFUSAL ITSELF PRESCRIBES: "Shrink the
    # payload rather than raising the ceiling". `normalize_market` keeps ~29
    # fields for diagnosis -- bids, volumes, open interest, liquidity, strike
    # type, `missing_fields` -- and the join reads `yes_american`/`no_american`,
    # the classifier reads ticker/series/title, the price lookup reads the ask
    # dollars, and the snapshot reads `close_time`. Nothing downstream of here
    # reads the rest, and the full row survives in the daily book.
    #
    # NOT FILTERED BY GAME DATE, and that was tried and reverted. Dropping
    # undated markets looked attractive -- futures can never match a board row
    # -- but PLAYER PROPS SKIP THE JOIN'S DATE CHECK ENTIRELY (it lives inside
    # the `needs_event_identity` branch), so a prop whose ticker shape does not
    # parse would have been silently dropped from the venue we actually trade.
    # Six tests caught it. Size is a size problem; solve it by size.
    #
    # Safe only because `_record_daily_book(full_markets)` runs ABOVE, on the
    # unbounded, unshrunk set.
    for series in list(per_series):
        entry = per_series.get(series) or {}
        markets = entry.get("markets") or []
        if not markets:
            continue
        if len(markets) > MAX_MARKETS_PER_SERIES:
            markets = markets[:MAX_MARKETS_PER_SERIES]
        entry["markets"] = [_lean_market(m) for m in markets]

    print(
        "[kalshi_odds] TICK"
        f" series_wanted={len(wanted)}"
        f" due={len(due)}"
        f" fetched={len(fetching)}"
        f" cap={cap}"
        f" interval_s={interval}"
        f" markets={len(all_markets)}"
        # Per series, with the STRATEGY beside each count -- a zero from a
        # working filter and a zero from an ignored one are different facts.
        f" this_tick={ {k: (v['count'], v['strategy']) for k, v in fetched.items()} }"
        # How old the OLDEST price in the merged set is. A merged artifact hides
        # staleness by construction unless it is stated.
        f" oldest_s={max(staleness.values()) if staleness else None}"
        f" trimmed={trimmed}",
        flush=True,
    )

    if not all_markets:
        print("[kalshi_odds] EMPTY no series has any markets yet", flush=True)
        state["series"] = per_series
        try:
            write_json_file(path, state)
        except Exception as exc:
            print(f"[kalshi_odds] WRITE_FAILED error={exc}", flush=True)
        return {"status": "empty", "markets": [], "per_series": fetched}

    if fetching:
        # SAMPLE TITLES from what was just fetched, one per series. The title
        # grammar is the last unverified assumption in the chain: `parse_prop_title`
        # reads "Player: N+ stat?" and REFUSES anything else rather than
        # guessing, so a series whose titles are worded differently prices
        # nothing and says so only as a refusal count. One printed title turns
        # that into a one-line fix.
        _seen: set[str] = set()
        for _market in all_markets:
            _series = str(_market.get("series") or "")
            if _series in _seen:
                continue
            _seen.add(_series)
            print(
                f"[kalshi_odds] TITLE {_series} :: {str(_market.get('title'))[:80]!r}"
                f" ticker={_market.get('ticker')}",
                flush=True,
            )

        # Only record history when something was actually re-fetched. Recording
        # on every tick would append the same merged snapshot ~30 times an hour
        # and the "price moved" test would still be doing the real work -- but
        # the `unchanged` counter would stop meaning anything.
        record_and_report(all_markets)
        report_catalogue_gaps(all_markets)

    state["series"] = per_series
    # THE MERGED LIST IS NOT PERSISTED. It is `per_series`' markets
    # concatenated, so storing both wrote the same payload twice -- measured
    # `series=7399941` plus `markets=6682458`, which is how a 13.3MB document
    # exceeded an 8MB ceiling and stopped being written at all. Readers get it
    # from `markets_from_state`.
    state.pop("markets", None)
    state["count"] = len(all_markets)
    state["fetched_at"] = _now_stamp()
    state["staleness_seconds"] = staleness
    try:
        write_json_file(path, state)
    except Exception as exc:
        print(f"[kalshi_odds] WRITE_FAILED error={exc}", flush=True)

    return {
        "status": "ok" if fetching else "cached",
        "markets": all_markets,
        "per_series": fetched,
        "staleness_seconds": staleness,
    }


def report_catalogue_gaps(markets: list[dict[str, Any]]) -> dict[str, Any]:
    """What Kalshi lists that we cannot price yet, by series, with an example.

    THE WORK QUEUE for covering more sports, and the reason this runs at all: a
    count of unmapped markets says nothing actionable, while a series name
    beside a sample title says exactly which registry line to add.
    """
    from syndicate.features.shared.kalshi_catalogue import classify_market, unmapped_series

    priced = sum(1 for m in markets if classify_market(m).get("status") == "ok")
    gaps = unmapped_series(markets)
    print(
        f"[kalshi_odds] CATALOGUE priced={priced} of {len(markets)} gaps={len(gaps)}",
        flush=True,
    )
    for series, info in list(gaps.items())[:5]:
        print(
            "[kalshi_odds] GAP"
            f" series={series}"
            f" count={info.get('count')}"
            f" reason={info.get('reason')}"
            f" detail={info.get('detail')}"
            f" sample={info.get('sample_title')!r}",
            flush=True,
        )
    return gaps


# The fields anything downstream of the artifact actually reads. Everything
# else `normalize_market` carries exists for DIAGNOSIS at fetch time and is
# already in the daily book, which is the record.
_LEAN_MARKET_FIELDS = (
    "ticker",
    "event_ticker",
    "series",
    "title",
    "yes_sub_title",
    "no_sub_title",
    "status",
    "yes_ask_dollars",
    "no_ask_dollars",
    "yes_american",
    "no_american",
    "yes_probability",
    "no_probability",
    "close_time",
)


def _lean_market(market: Mapping[str, Any]) -> dict[str, Any]:
    """One market, reduced to what the join, the price lookup and the snapshot
    read. See the size note at the persistence bound."""
    return {field: market.get(field) for field in _LEAN_MARKET_FIELDS}


def _record_daily_book(markets: list[dict[str, Any]]) -> None:
    """Write the venue-native daily odds files. Never fatal.

    CAPTURE-FIRST, and that is the whole point: this records EVERY market the
    fetch returned, including the ones the board join refuses. Today an
    unparsed family is invisible -- not refused, not counted, not stored -- so
    the only way to find it is for a human to notice it on the venue's site.
    Here it becomes a counted row carrying its raw title.

    Non-fatal by construction. A history write failing must not cost the board
    the prices it just fetched, and it is REPORTED rather than swallowed: a
    silent failure here looks exactly like a venue that lists nothing.
    """
    try:
        from syndicate.features.shared.venue_daily_odds import (
            kalshi_daily_rows,
            record_venue_book,
        )

        # Kalshi's markets come straight from the tick that just fetched them,
        # so the source stamp is now. Passed anyway rather than omitted: the
        # field exists to say whether the feed advanced, and a recorder that
        # only sometimes receives it cannot answer that for every venue.
        from syndicate.features.shared.venue_daily_odds import _utc_now

        report = record_venue_book(
            "kalshi", kalshi_daily_rows(markets), source_fetched_at=_utc_now()
        )
    except Exception as exc:
        print(f"[kalshi_odds] DAILY_BOOK_FAILED {type(exc).__name__}: {exc}", flush=True)
        return
    print(
        "[kalshi_odds] DAILY_BOOK"
        f" status={report.get('status')}"
        f" files={report.get('files')}"
        f" errors={report.get('file_errors')}"
        f" listed={report.get('listed')}"
        f" parsed={report.get('parsed')}"
        f" opened={report.get('opened')}"
        f" appended={report.get('appended')}"
        # The counters that make `appended=0` readable -- no id, no price, and
        # nothing moved are three different problems with three different
        # fixes. Polymarket's book read `appended=0` for a whole day and this
        # line could not have said which.
        f" unchanged={report.get('unchanged')}"
        f" unpriced={report.get('unpriced')}"
        f" no_id={report.get('skipped_no_id')}"
        # Rows with no readable sport or game date -- futures land here, which
        # is correct: a season-long market has no game day to be filed under.
        f" undated={report.get('undated')}"
        # Sports we do not model, counted by name. Polymarket's soccer league
        # codes surface here -- real markets in a sport we DO model, under
        # names we have not yet read.
        f" skipped={report.get('skipped_total')}"
        f" skipped_by_sport={report.get('skipped_by_sport')}"
        # THE COVERAGE GAP, BY FAMILY. Empty means every market Kalshi listed
        # for these sports was named, which has never yet been true.
        f" unparsed={report.get('unparsed_by_family')}"
        f" detail={report.get('detail')}",
        flush=True,
    )


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def record_and_report(markets: list[dict[str, Any]]) -> dict[str, Any]:
    """Keep the price point, then say what has moved and what closes when.

    Wrapped and non-fatal: a history write failing must not cost the board the
    prices it just fetched. It is reported rather than swallowed -- a silent
    history failure looks identical to "nothing has moved yet" forever.
    """
    from syndicate.features.shared.kalshi_board import (
        board_by_game_date,
        movement_report,
        record_snapshot,
    )

    try:
        recorded = record_snapshot(markets)
    except Exception as exc:
        print(f"[kalshi_odds] HISTORY_FAILED error={exc}", flush=True)
        return {"status": "error"}

    print(
        "[kalshi_odds] HISTORY"
        f" status={recorded.get('status')}"
        f" opened={recorded.get('opened')}"
        f" appended={recorded.get('appended')}"
        f" unchanged={recorded.get('unchanged')}"
        f" tickers={recorded.get('tickers')}"
        f" trimmed_points={recorded.get('trimmed_points')}"
        f" trimmed_tickers={recorded.get('trimmed_tickers')}",
        flush=True,
    )

    dates = board_by_game_date(markets)
    # BOTH GROUPINGS, side by side, because the GAP between them is the finding.
    # `BY_GAME_DATE` used to be grouped on `close_time` -- a settlement deadline
    # up to four days after first pitch (`#370`). On 2026-08-25 a reader took
    # three of these readings whose earliest key was `2026-08-27`, concluded the
    # working set held nothing for the board's date, and started designing a
    # bound on that; two of that date's markets were in the very same set. A
    # name and a field disagreed and one printed number could not show it.
    print(f"[kalshi_odds] BY_GAME_DATE {dates.get('by_date_series')}", flush=True)
    print(f"[kalshi_odds] BY_CLOSE_DATE {dates.get('by_close_date')}", flush=True)

    # WHICH FIELD IS THE GAME DATE? ANSWERED: the TICKER's event segment does,
    # and no time field does. This probe asked the question -- measured
    # 2026-08-23, all 154 markets across two series reported the same
    # `close_time` date and 137 different pitchers do not all pitch on one day
    # -- and `game_date_from_ticker` is the answer it produced.
    #
    # It stays because the answer needs to keep being visible. One line per
    # series carries the ticker and all three time fields together, so the
    # four-day gap is READABLE per market rather than inferable from the two
    # histograms above. The cost of it not being readable is recorded there.
    seen_series: set[str] = set()
    for market in markets:
        series = str(market.get("series") or "")
        if series in seen_series:
            continue
        seen_series.add(series)
        print(
            "[kalshi_odds] DATE_FIELDS"
            f" series={series}"
            f" ticker={market.get('ticker')}"
            f" event_ticker={market.get('event_ticker')}"
            f" open={market.get('open_time')}"
            f" close={market.get('close_time')}"
            f" expiration={market.get('expiration_time')}"
            f" title={str(market.get('title'))[:70]!r}",
            flush=True,
        )
        if len(seen_series) >= 3:
            break

    try:
        moves = movement_report(top=8)
    except Exception as exc:
        print(f"[kalshi_odds] MOVES_FAILED error={exc}", flush=True)
        return recorded

    print(
        "[kalshi_odds] MOVES"
        f" tracked={moves.get('tickers')}"
        f" moved={moves.get('moved')}"
        f" unmoved={moves.get('unmoved')}"
        # `too_new` is NOT folded into `unmoved`: one observation means we have
        # not watched long enough, which licenses waiting, while unmoved licenses
        # concluding. Same number, opposite decision.
        f" too_new={moves.get('too_new')}",
        flush=True,
    )
    for mover in (moves.get("movers") or [])[:5]:
        print(
            "[kalshi_odds] MOVER"
            f" {mover.get('ticker')}"
            f" open={mover.get('opening_yes')}"
            f" now={mover.get('current_yes')}"
            f" move_pts={mover.get('move_points')}"
            f" n={mover.get('observations')}"
            f" since={mover.get('opened_at')}",
            flush=True,
        )
    return recorded


def join_to_board(
    markets: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    *,
    selected_date: str | None = None,
) -> dict[str, Any]:
    """Pair Kalshi's real prices with the board, and report the coverage.

    THE NUMBER THIS WHOLE THREAD HAS BEEN CHASING. Every Kalshi coverage figure
    reported before this one was OddsAPI's view of Kalshi -- game lines only,
    1.2-3.8% of the board. This is the first that is about Kalshi.
    """
    from syndicate.features.shared.kalshi_board_join import join_kalshi_to_board

    report = join_kalshi_to_board(markets, rows, selected_date=selected_date)
    print(
        "[kalshi_odds] BOARD_JOIN"
        f" kalshi_markets={report.get('kalshi_markets')}"
        f" board_rows={report.get('board_rows')}"
        f" matched={report.get('matched')}"
        # Named refusals: "Kalshi has nothing we bet" and "our join is broken"
        # must never share a number. That confusion is #505.
        f" reasons={report.get('reasons')}"
        # WHICH SERIES A SEGMENT ROW ACTUALLY MET, both directions. Kalshi lists
        # `KXMLBF5TOTAL-...-5` ("First 5 innings: Over 4.5") and
        # `KXMLBTOTAL-...-5` ("Over 4.5 runs scored") for the SAME game at the
        # SAME strike, and `_row_market()` strips the segment on purpose so both
        # key as (event,'totals',4.5). `_segments_agree` separates them -- but
        # until these were printed, "which contract priced this row" was an
        # inference. Refusals are printed BESIDE matches because
        # `segment_has_no_matching_series: 0` was read three different ways in
        # one day for want of a denominator.
        f" segment_matched={report.get('segment_matched_series')}"
        f" segment_refused={report.get('segment_refused_series')}"
        # ALT/MAIN COLLAPSE RATE. `_row_market()` also strips the `_alt` suffix,
        # so a main-line row and an alternate row for one bet now key
        # identically and `_collapse_duplicate_bets` picks one. This is the rate
        # that tie-break decides; it was returned in the report and printed
        # NOWHERE, so the guard's frequency was unmeasurable in production.
        # Replay measured ~1 per 78 collapsed keys -- a ZERO here is worth a
        # second look, not a celebration.
        f" alt_main_collisions={report.get('alt_main_collisions')}",
        flush=True,
    )
    # On a zero-match join, print BOTH SIDES' keys. A count of failures with no
    # way to see the mismatch is the `#505` report, and it took weeks to resolve
    # precisely because nobody could see which field disagreed.
    if not report.get("matched"):
        print(
            "[kalshi_odds] JOIN_KEYS"
            f" kalshi={report.get('kalshi_key_sample')}"
            f" board={report.get('board_key_sample')}"
            f" board_markets={report.get('board_market_vocabulary')}",
            flush=True,
        )
    # THE CLUB CODES, WHENEVER THERE ARE ANY -- NOT ONLY ON A ZERO-MATCH JOIN.
    #
    # This sat inside the `if not matched` block above, and that is precisely
    # why the Kalshi game-line gap stayed invisible. MEASURED 2026-08-25
    # 15:56:35Z:
    #
    #   BOARD_JOIN kalshi_markets=883 board_rows=1290 matched=5
    #     reasons={'event_not_on_our_board': 20, ...}
    #
    # Five player props matched, so `matched` was truthy and the samples never
    # printed -- while all 20 GAME LINES failed event resolution and nothing
    # said which club codes they were. A partial match is the normal state and
    # it was the one state that suppressed the diagnostic.
    #
    # `game_lines_disabled` is ABSENT from those reasons, which is the reading
    # that matters: that counter fires only for a game line whose event
    # RESOLVED, so its absence means zero resolved. Turning
    # `SYNDICATE_KALSHI_GAME_LINES` on would price nothing.
    #
    # WHAT THIS LINE THEN MEASURED, 2026-08-25T16:14:40Z -- and it was NOT the
    # club-code alias gap predicted here:
    #
    #   JOIN_EVENTS unmatched=[{'kalshi': 'ATLMIL',
    #       'ticker': 'KXMLBSPREAD-26AUG231910ATLMIL-MIL4', 'sport': 'mlb'}, ...]
    #
    # Every sample was `ATLMIL` on `26AUG23` -- Atlanta at Milwaukee, two days
    # stale, and a blob the resolver reads correctly. The refusals were dated,
    # not misspelled. Two separate defects made that look like an alias gap,
    # both since fixed in `kalshi_board_join.py`: the date check sat BELOW the
    # resolver, so a stale game could only fail as `event_not_on_our_board`;
    # and the sample was bounded on markets rather than on distinct blobs, so
    # one game consumed all eight slots.
    #
    # The prediction may still be right for the remaining refusals -- it is
    # simply not yet evidence. With the date checked first, whatever
    # `event_not_on_our_board` still counts is an alias gap, and THAT is when
    # this line becomes the work list it was built to be.
    # THE GRAMMAR WORK LIST. `unreadable_title` is the single largest refusal
    # on an MLB slate (216 of 883, 2026-08-25T16:14:40Z) and the one that hides
    # the h2h path: `KXMLBGAME` -- the moneyline series, and the market the
    # rejected live Kalshi order wanted -- has no title grammar at all, so
    # every one of its markets refuses here and no game line ever reaches the
    # resolver. One title per series, so a new market family is visible rather
    # than buried under whichever series is largest.
    if report.get("unreadable_titles"):
        print(
            "[kalshi_odds] JOIN_TITLES"
            f" unreadable={report.get('unreadable_titles')}"
            # The COMPLETE per-series count, which the bounded sample cannot
            # give: it answers "is this market family refusing here at all",
            # where the sample can only answer "what does one of them say".
            f" by_series={report.get('unreadable_by_series')}",
            flush=True,
        )
    if report.get("unmatched_events"):
        print(
            "[kalshi_odds] JOIN_EVENTS"
            f" unmatched={report.get('unmatched_events')}"
            f" board={report.get('board_event_sample')}",
            flush=True,
        )
    _record_board_demand(rows)
    _capture_kalshi_quotes(report, rows, selected_date=selected_date)
    return report


def _capture_kalshi_quotes(
    report: Mapping[str, Any],
    board_rows: Sequence[Mapping[str, Any]],
    *,
    selected_date: str | None,
) -> None:
    """Write Kalshi's matched prices into `book_quotes`. `#617`.

    WHY HERE. This is the one place that holds Kalshi's own prices already
    paired to board rows. `book_quotes` is otherwise fed from OddsAPI, which
    carries GAME LINES ONLY for exchanges -- measured on MLB 2026-08-31,
    26,710 exchange quotes on game markets and **ZERO on prop markets**, while
    Kalshi filled 23 real MLB prop orders the same day. Anything that reads
    `book_quotes` has been blind to exchange prop prices.

    THIS CHANGES NOTHING THE BOARD RANKS. It only makes the prices visible to
    whatever reads the quote log, which is what turns the prop-side value of
    price-shopping from unmeasurable into measurable. The board change, if the
    measurement justifies one, is a separate decision.

    PER SPORT, because `book_quotes` is sharded per sport. **A match does NOT
    carry a sport** -- verified, neither `matches.append` block writes one -- so
    it is looked up from the BOARD ROW the match paired with, by
    `board_event_id`. That is the same row the join keyed on, so the sport is
    the board's own and not a second derivation. A match whose event is not in
    the board index is dropped rather than filed under a guess: a quote in the
    wrong shard is worse than a missing one, because it would later be read as
    another sport's price.

    NEVER RAISES. The quote log is instrumentation; the join is the product.
    Same contract `append_book_quotes` itself keeps, and the same reason.
    """
    try:
        matches = report.get("matches") if isinstance(report, Mapping) else None
        if not matches:
            return
        from syndicate.features.shared.book_shortlist import (
            QUOTE_SOURCE_FIELD,
            QUOTE_SOURCE_VENUE_DIRECT,
        )
        from syndicate.features.shared.odds_book_quotes import (
            append_book_quotes,
            quote_rows_from_kalshi_matches,
        )

        sport_by_event: dict[str, str] = {}
        for row in board_rows or ():
            if not isinstance(row, Mapping):
                continue
            event_id = str(row.get("event_id") or "").strip()
            sport = str(row.get("sport") or "").strip().lower()
            if event_id and sport:
                sport_by_event.setdefault(event_id, sport)

        by_sport: dict[str, list[dict[str, Any]]] = {}
        no_sport = 0
        for match in matches:
            if not isinstance(match, Mapping):
                continue
            sport = sport_by_event.get(str(match.get("board_event_id") or "").strip())
            if not sport:
                no_sport += 1
                continue
            by_sport.setdefault(sport, []).append(dict(match))

        captured = 0
        appended_by_sport: dict[str, int] = {}
        game_line_rows = 0
        for sport, sport_matches in by_sport.items():
            # GAME LINES FOR SOCCER ONLY -- see `_GAME_LINE_CAPTURE_SPORTS`.
            # Soccer's venue matches are ALL game lines (h2h/totals: a club
            # is not a player), so the props-only bound discarded 51 of 51
            # matched soccer markets on 2026-09-01T23:41Z while the sport has
            # zero OddsAPI exchange rows to collide with.
            from syndicate.features.shared.odds_book_quotes import (
                sport_allows_game_line_capture,
            )

            rows = quote_rows_from_kalshi_matches(
                sport_matches,
                allow_game_lines=sport_allows_game_line_capture(sport),
            )
            if not rows:
                continue
            result = append_book_quotes(
                sport=sport,
                date_str=str(selected_date or "").strip(),
                rows=rows,
                captured_at=_now_stamp(),
                # STAMP THE PROVENANCE, or the grid throws these away.
                #
                # `book_grid` refuses a row whose bookmaker is a direct-feed
                # venue, to keep the 2026-08-25 "one price source per venue"
                # invariant against OddsAPI's copy of kalshi/polymarket. A quote
                # row carries no source field, so measured 2026-09-01 that
                # refusal could not tell THESE rows -- the venue's own prices --
                # from the aggregator's, and discarded both: Layer 1 and the
                # book-grid saw no exchange at all.
                #
                # `drop_from_grid` now asks for provenance instead of the name,
                # and absent still means dropped, so this stamp is what actually
                # lets a directly-observed price reach a board.
                extra={QUOTE_SOURCE_FIELD: QUOTE_SOURCE_VENUE_DIRECT},
            )
            _n = int((result or {}).get("appended") or 0)
            captured += _n
            if _n:
                appended_by_sport[sport] = appended_by_sport.get(sport, 0) + _n
            game_line_rows += sum(1 for r in rows if not r.get("player_name"))
        # ONE LINE, ALWAYS, INCLUDING THE ZEROES. `no_sport` and an empty
        # `by_sport` are different failures -- "the match carries no sport" and
        # "the join produced nothing" -- and a line that printed only on
        # success could not tell them apart.
        print(
            "[kalshi_odds] QUOTE_CAPTURE"
            # `sports=` LISTS SPORTS WITH MATCHES, NOT SPORTS WITH ROWS, and
            # that ambiguity cost a wrong reading on 2026-09-01: soccer sat in
            # this field for hours while contributing zero quotes, which reads
            # as working capture. `appended_by_sport` is the discriminating
            # field -- a sport present in `sports` and absent here matched and
            # wrote nothing.
            f" matches={len(matches)} sports={sorted(by_sport)}"
            f" appended={captured} appended_by_sport={appended_by_sport}"
            f" game_lines={game_line_rows} no_sport={no_sport}",
            flush=True,
        )
    except Exception as exc:  # noqa: BLE001 -- instrumentation must not fail the join
        print(f"[kalshi_odds] QUOTE_CAPTURE_FAILED {type(exc).__name__}: {exc}", flush=True)


def _record_board_demand(rows: list[dict[str, Any]]) -> None:
    """Persist how many board rows each sport asked for, for the NEXT trim.

    THE WORKING SET HAD NO NOTION OF WHICH SPORTS HAVE GAMES TODAY, and that is
    what `_sport_slot_caps` needs to fix it. The demand lives here rather than
    being passed in because this is the only place that sees the board and the
    catalogue in the same breath -- the trim runs during the REFRESH, before any
    join, so it cannot ask the question itself.

    ONE CYCLE OF LAG, ACCEPTED. The trim reads the previous join's demand. Board
    composition changes across hours, not minutes, and the flat floor underneath
    covers the one case where lag bites: a sport whose slate opens between
    cycles has no demand yet and still gets its floor.

    NEVER RAISES, and never on the write either. A demand signal is an
    optimisation; losing it costs a flat-floor cycle, while an exception here
    would cost the join that produced it.
    """
    try:
        counts: dict[str, int] = {}
        for row in rows or []:
            sport = str((row or {}).get("sport") or "").strip().lower()
            if sport:
                counts[sport] = counts.get(sport, 0) + 1
        if not counts:
            return
        from syndicate.features.shared.refresh_state_store import read_json_file, write_json_file

        path = markets_artifact_path()
        state = read_json_file(path) or {}
        if not isinstance(state, dict):
            return
        # PER-SPORT MAX OVER A WINDOW, NOT LAST-WRITE-WINS.
        #
        # Overwriting was wrong and production showed it within two cycles.
        # `join_to_board` runs on EVERY build, and the builds alternate between
        # the full slate and a smaller future-date board:
        #
        #   20:14:31Z demand={mlb: 400, ncaaf: 42, nfl: 102, soccer: 400, wnba: 400}
        #   20:25:54Z demand={ncaaf: 42, soccer: 400}          <- 442-row build
        #             kept_by_sport={... wnba: 300}            <- back to bare floor
        #
        # A board that simply does not MENTION a sport is not evidence that the
        # sport has no demand, but last-write-wins reads it as exactly that, and
        # WNBA fell 534 -> 300 on a build that was never about WNBA.
        #
        # Max-over-window is stable against that and still DECAYS: a sport whose
        # slate ends stops appearing in new samples and ages out of the window,
        # rather than holding slots forever the way a plain merge would.
        now = time.time()
        samples = [
            sample
            for sample in (state.get("board_demand_samples") or [])
            if isinstance(sample, Mapping)
            and isinstance(sample.get("at"), (int, float))
            and (now - float(sample["at"])) <= _DEMAND_WINDOW_SECONDS
        ]
        samples.append({"at": now, "counts": counts})
        samples = samples[-_DEMAND_SAMPLE_LIMIT:]

        merged: dict[str, int] = {}
        for sample in samples:
            for sport, value in (sample.get("counts") or {}).items():
                try:
                    merged[sport] = max(merged.get(sport, 0), int(value))
                except (TypeError, ValueError):
                    continue

        state["board_demand_samples"] = samples
        state["board_demand"] = merged
        state["board_demand_at"] = _now_stamp()
        write_json_file(path, state)
        print(
            f"[kalshi_odds] BOARD_DEMAND seen={dict(sorted(counts.items()))}"
            f" merged={dict(sorted(merged.items()))} samples={len(samples)}",
            flush=True,
        )
    except Exception as exc:  # noqa: BLE001 -- an optimisation must not cost the join
        print(f"[kalshi_odds] BOARD_DEMAND_FAILED {type(exc).__name__}: {exc}", flush=True)
