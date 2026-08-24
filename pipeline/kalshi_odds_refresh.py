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
from datetime import datetime, timezone
from collections.abc import Mapping
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


DEFAULT_SERIES_PER_TICK = 12

# Total markets kept in the artifact. The keyvalue store refuses at 8MB and
# `layer2_shortlist` already sits at 5.7MB of that budget, so an unbounded
# multi-sport catalogue is a write that starts failing silently one sport from
# now. Trimmed OLDEST-SERIES-FIRST and reported, never silently.
MAX_STORED_MARKETS = 6000


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


def _due_series(state: dict[str, Any], wanted: tuple[str, ...], interval: int) -> list[str]:
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
        if age is None:
            # Never fetched. Sorts ahead of everything -- a series with no
            # prices at all is worth more than a refresh of one that has them.
            due.append((float("inf"), series))
        elif age >= interval:
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
        return {
            "status": "ok",
            "catalogue": int(report.get("count") or 0),
            "prop_series": len(props),
            "game_series": len(games),
            "added": len(added_props.get("added") or {}) + len(added_games.get("added") or {}),
        }
    except Exception as exc:
        return {"status": "error", "reason": f"{type(exc).__name__}: {exc}"}


def run_kalshi_odds_refresh(*, force: bool = False) -> dict[str, Any]:
    """Refresh whichever series are due, merge, record, write.

    Returns EVERY series' markets, not just the ones fetched this call. With a
    per-series clock the alternative is that three quarters of the board's
    Kalshi prices vanish on every tick -- the merge is not an optimisation, it
    is what makes a staggered fetch usable at all.

    `force=True` bypasses the enable flag, the per-series clock and the
    per-tick cap: that is what a manual probe wants.
    """
    if not (force or kalshi_odds_enabled()):
        return {"status": "skipped", "reason": "disabled"}

    # BEFORE `sports_series()` is read, because it decides what that returns.
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

    from syndicate.features.shared.refresh_state_store import read_json_file, write_json_file

    path = markets_artifact_path()
    try:
        state = read_json_file(path) or {}
    except Exception:
        state = {}
    per_series: dict[str, Any] = dict(state.get("series") or {})

    wanted = sports_series()
    interval = refresh_interval_seconds()
    due = wanted if force else _due_series(state, wanted, interval)

    # A failed series backs off on its OWN shorter clock. Without this a venue
    # that is 403ing or rate-limiting us is retried every board build -- every
    # ~2 minutes -- which is how the 2026-08-23 429s happened.
    if not force:
        due = [s for s in due if not _backing_off(per_series.get(s) or {}, interval)]

    cap = series_per_tick()
    fetching = due if force else due[:cap]

    fetched: dict[str, Any] = {}
    for series in fetching:
        result = fetch_series_markets(series)
        markets = result.get("markets") or []
        entry = dict(per_series.get(series) or {})
        entry["attempted_at"] = _now_stamp()
        entry["strategy"] = result.get("strategy")
        entry["reason"] = result.get("reason")
        if markets:
            entry["markets"] = markets
            entry["count"] = len(markets)
            # `fetched_at` moves ONLY on a fetch that returned something. A
            # failure that stamped it would blank this series for an interval
            # AND start its clock, so the next hour would serve zero markets
            # from an artifact that looks fresh.
            entry["fetched_at"] = entry["attempted_at"]
        per_series[series] = entry
        fetched[series] = {"count": len(markets), "strategy": result.get("strategy")}

    # MERGE. Every series' last good markets, whether or not it was fetched now.
    all_markets: list[dict[str, Any]] = []
    staleness: dict[str, int] = {}
    for series in wanted:
        entry = per_series.get(series) or {}
        all_markets.extend(entry.get("markets") or [])
        age = _seconds_since(entry.get("fetched_at"))
        if age is not None:
            staleness[series] = int(age)

    trimmed = 0
    if len(all_markets) > MAX_STORED_MARKETS:
        trimmed = len(all_markets) - MAX_STORED_MARKETS
        all_markets = all_markets[:MAX_STORED_MARKETS]

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
    state["markets"] = all_markets
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
    print(f"[kalshi_odds] BY_GAME_DATE {dates.get('by_date_series')}", flush=True)

    # WHICH FIELD IS THE GAME DATE? Measured 2026-08-23: all 154 markets across
    # two series reported the same `close_time` date, and 137 different pitchers
    # do not all pitch on one day -- so `close_time` is very likely a settlement
    # deadline rather than first pitch, and grouping by it is grouping by the
    # wrong thing. Rather than guess which of `open_time`/`close_time`/
    # `expiration_time`/the ticker carries it, print one market's date fields
    # verbatim and let the next run say. This is the same choice `probe()` made
    # for the price fields, which is what caught the 100x error.
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
        f" reasons={report.get('reasons')}",
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
        # The CLUB CODES, both sides. `event_not_on_our_board` is a count and
        # cannot say which spelling is missing; printing Kalshi's blob beside
        # our board's makes the alias readable instead of guessed at, and a
        # club alias guessed rather than read is how a bet reaches the wrong
        # game.
        if report.get("unmatched_events"):
            print(
                "[kalshi_odds] JOIN_EVENTS"
                f" unmatched={report.get('unmatched_events')}"
                f" board={report.get('board_event_sample')}",
                flush=True,
            )
    return report
