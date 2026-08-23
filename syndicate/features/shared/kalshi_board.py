"""A Kalshi-native board: its markets by game date, and how they have MOVED.

WHY THIS IS NOT THE LAYER 2 BOARD. The main board is built for one slate date
from OddsAPI, and at 04:22 it had rolled to European soccer while Kalshi was
already quoting the next MLB slate. Waiting for those two to align is waiting on
a clock. Kalshi lists tomorrow NOW, so tomorrow's Kalshi board can exist now --
and every hour it exists is an hour of line movement we would otherwise never
see, because a price nobody recorded cannot be compared to anything later.

--------------------------------------------------------------------------
THE OPENING LINE IS THE POINT, AND IT MUST BE IMMUTABLE
--------------------------------------------------------------------------

CLV is the closing price against the price we took, and it is only worth
measuring against a reference that is genuinely EARLY. OddsAPI's opening is
whenever we happened to poll it; Kalshi lists lookahead markets days out, so the
first price we record here really is near the open.

That makes the opening the most valuable number in this file, which is why it is
stored as its OWN immutable field rather than as `points[0]`. The bounded window
trims oldest-first, and oldest-first is exactly the opening -- so a naive
"movement since the first point I still have" silently becomes "movement since
some arbitrary Tuesday" once the window fills, with no visible change in the
number it produces. `opened_at`/`opening_yes` are written once, on first sight,
and never rewritten.

--------------------------------------------------------------------------
MOVEMENT NEEDS HISTORY, AND HISTORY NEEDS A BOUND
--------------------------------------------------------------------------

Bounded, because `shadow_candidate_ledger`'s 4.9GB chunk incident is what an
append-forever price log becomes. Two limits, both enforced here rather than
trusted to a caller: `_MAX_POINTS_PER_TICKER` keeps each series short, and
`_MAX_TICKERS` caps the document. Trimming is REPORTED, never silent -- a
history that quietly forgets is worse than one that refuses to grow, because
the gap is invisible in the movement number it produces.

The path carries NO DATE TOKEN. A date-tokened path takes the keyvalue store's
10-day TTL, and the whole point of this file is the comparison ACROSS days.
`execution_ledger` and `portfolio_settings` make the same choice for the same
reason.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

__all__ = [
    "record_snapshot",
    "movement_report",
    "board_by_game_date",
    "opening_line",
    "kalshi_board_path",
]

# A point is only appended when the price MOVED, so 48 points is 48 moves, not
# 48 fetches -- comfortably more than a market makes in the days it is listed.
_MAX_POINTS_PER_TICKER = 48
_MAX_TICKERS = 4000


def kalshi_board_path():
    from syndicate.features.shared.refresh_state_store import reports_root

    # NO DATE TOKEN -- see the module docstring. This file exists to compare
    # across days and a 10-day TTL would delete exactly that.
    return reports_root() / "intelligence" / "kalshi_market_history.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _as_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return None if parsed != parsed else parsed


def record_snapshot(
    markets: Sequence[Mapping[str, Any]], *, now: str | None = None
) -> dict[str, Any]:
    """Append one price point per market whose price changed. Returns counters.

    Counters are returned ALWAYS, including the zeroes. A counter that only
    appears when it fires cannot distinguish "ran and nothing changed" from
    "never ran" -- the lesson `#373`/`#381`/`#397`/`#400` each learned
    separately.
    """
    from syndicate.features.shared.refresh_state_store import read_json_file, write_json_file

    stamp = now or _utc_now()
    path = kalshi_board_path()
    try:
        state = read_json_file(path) or {}
    except Exception:
        state = {}
    series: dict[str, Any] = state.get("tickers") or {}

    appended = 0
    unchanged = 0
    opened = 0
    trimmed_points = 0
    for market in markets:
        ticker = str(market.get("ticker") or "").strip()
        if not ticker:
            continue
        yes = _as_float(market.get("yes_ask_dollars"))
        no = _as_float(market.get("no_ask_dollars"))
        if yes is None and no is None:
            continue

        entry = series.get(ticker)
        if entry is None:
            # FIRST SIGHT. On a lookahead market this is the opening line in the
            # sense CLV needs -- days before the game, not whenever the board
            # happened to be built. Written once here and never again.
            entry = {
                "points": [],
                "title": market.get("title"),
                "series": market.get("series"),
                "close_time": market.get("close_time"),
                "opened_at": stamp,
                "opening_yes": yes,
                "opening_no": no,
            }
            series[ticker] = entry
            opened += 1
        else:
            # Metadata refreshes; the opening never does.
            if market.get("close_time"):
                entry["close_time"] = market.get("close_time")

        history = entry.setdefault("points", [])
        # Only append when the price actually MOVED. A point per fetch with an
        # identical price is storage spent to record that nothing happened, and
        # it would push the real moves out of a bounded window.
        if history and history[-1].get("yes") == yes and history[-1].get("no") == no:
            unchanged += 1
            entry["last_seen"] = stamp
            continue
        history.append({"ts": stamp, "yes": yes, "no": no})
        entry["last_seen"] = stamp
        appended += 1
        if len(history) > _MAX_POINTS_PER_TICKER:
            dropped = len(history) - _MAX_POINTS_PER_TICKER
            # OLDEST out, and counted. Safe for the movement number only because
            # the opening lives in `opening_yes`, not in `points[0]`.
            entry["points"] = history[-_MAX_POINTS_PER_TICKER:]
            trimmed_points += dropped

    trimmed_tickers = 0
    if len(series) > _MAX_TICKERS:
        # Keep the most recently seen. Arbitrary but stated, and reported.
        ordered = sorted(
            series.items(),
            key=lambda kv: str(kv[1].get("last_seen") or kv[1].get("opened_at") or ""),
            reverse=True,
        )
        trimmed_tickers = len(series) - _MAX_TICKERS
        series = dict(ordered[:_MAX_TICKERS])

    state["tickers"] = series
    state["updated_at"] = stamp
    try:
        write_json_file(path, state)
    except Exception as exc:
        return {"status": "error", "reason": f"{type(exc).__name__}: {exc}"}

    return {
        "status": "ok",
        "appended": appended,
        "unchanged": unchanged,
        "opened": opened,
        "tickers": len(series),
        "trimmed_points": trimmed_points,
        "trimmed_tickers": trimmed_tickers,
    }


def opening_line(ticker: str) -> dict[str, Any] | None:
    """The first price we ever saw for `ticker`, or None if we never saw one.

    None means "not tracked", and callers must not read it as "no movement".
    Separated out because this is what a CLV grade needs, and it needs it by
    ticker rather than as part of a top-N report.
    """
    from syndicate.features.shared.refresh_state_store import read_json_file

    try:
        state = read_json_file(kalshi_board_path()) or {}
    except Exception:
        return None
    entry = (state.get("tickers") or {}).get(str(ticker))
    if not entry:
        return None
    return {
        "ticker": str(ticker),
        "opening_yes": entry.get("opening_yes"),
        "opening_no": entry.get("opening_no"),
        "opened_at": entry.get("opened_at"),
        "observations": len(entry.get("points") or []),
    }


def movement_report(*, top: int = 10) -> dict[str, Any]:
    """Which markets have moved most since their OPENING.

    Movement is in PROBABILITY POINTS, not price difference: Kalshi prices are
    dollars of probability, so the subtraction is meaningful directly -- unlike
    American odds, where it never is.
    """
    from syndicate.features.shared.refresh_state_store import read_json_file

    try:
        state = read_json_file(kalshi_board_path()) or {}
    except Exception:
        return {"tickers": 0, "moved": 0, "unmoved": 0, "too_new": 0, "movers": []}

    movers: list[dict[str, Any]] = []
    tracked = 0
    too_new = 0
    unmoved = 0
    for ticker, entry in (state.get("tickers") or {}).items():
        points = entry.get("points") or []
        tracked += 1
        opening = entry.get("opening_yes")
        if opening is None or not points:
            continue
        if len(points) < 2:
            # One point is a price, not a movement. Counted as tracked and as
            # `too_new`, never as a 0.0 mover -- reporting it as zero would put
            # "we have not watched this long enough" and "this has not moved"
            # in one bucket, and those license opposite decisions.
            too_new += 1
            continue
        last = points[-1]
        if last.get("yes") is None:
            continue
        delta = round((last["yes"] - opening) * 100.0, 2)
        if delta == 0.0:
            unmoved += 1
        movers.append(
            {
                "ticker": ticker,
                "title": entry.get("title"),
                "close_time": entry.get("close_time"),
                "opening_yes": opening,
                "current_yes": last.get("yes"),
                "move_points": delta,
                "observations": len(points),
                "opened_at": entry.get("opened_at"),
            }
        )

    movers.sort(key=lambda m: -abs(m["move_points"]))
    return {
        "tickers": tracked,
        "moved": len([m for m in movers if m["move_points"] != 0.0]),
        "unmoved": unmoved,
        "too_new": too_new,
        "movers": movers[:top],
    }


def board_by_game_date(markets: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Kalshi's markets grouped by the DAY they close -- i.e. by game date.

    Grouped on the date part only. A night game closes after midnight UTC, so an
    exact timestamp would scatter one slate across two days -- `#370`'s bug in a
    new place.
    """
    by_date: dict[str, int] = {}
    by_date_series: dict[str, dict[str, int]] = {}
    for market in markets:
        close_date = str(market.get("close_time") or "")[:10] or "<no_close_time>"
        by_date[close_date] = by_date.get(close_date, 0) + 1
        series = str(market.get("series") or "") or "<absent>"
        by_date_series.setdefault(close_date, {})
        by_date_series[close_date][series] = by_date_series[close_date].get(series, 0) + 1
    return {
        "by_date": dict(sorted(by_date.items())),
        "by_date_series": {k: dict(sorted(v.items())) for k, v in sorted(by_date_series.items())},
    }
