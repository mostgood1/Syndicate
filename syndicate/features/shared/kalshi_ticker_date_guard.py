"""A live Kalshi order must be for the game it says it is for: ticker date == game date.

USER DECISION 2026-10-20 ~18:45Z (relayed from session 332cb014's chat): "Guard +
fix the join" -- "refuse any live order whose ticker date doesn't match the game's
date, by name, before anything is sent (fail-closed, small change in the
executor) ... The guard deploys first, on its own." Lane
future-dated-live-orders-scope; the join fix is the audit session's.

WHY. `findings_2026-10-20_one_engine_audit.md` section 0: 35 of 87 board Kalshi
tickers (40%) carried ANOTHER game's date -- e.g. `UM @ TRO` on 10-24 carrying
`KXNCAAFGAME-26OCT29TROYJMU-TROY`, suggested=True. Re-measured on the fleet's
10-20 board: 38 of 106 `venue_ref` tickers. The executor's ticker comes from
`kalshi_board_join` (event-id keyed) and was right today, but nothing on the
order path refused a mismatch if that join slipped -- and a wrong-game ticker is
a real bet on a different game, the worst failure an order can have.

THE DATE IS READ WITH THE JOIN'S OWN DECODER (`kalshi_catalogue.game_date_from_ticker`),
not a second parser: `learnings.md` -- the order path may not re-derive a match
the join already made with its own logic.

KALSHI DATES GAMES IN US/EASTERN (`kalshi_catalogue.event_start_from_ticker`:
`26SEP041915DETCLEG2` is 19:15 Eastern, verified to the minute against the
board). So the game's `commence_time` is converted to America/New_York and the
two dates must be EQUAL. Only if the Eastern conversion itself is unavailable
does the guard accept the UTC date or the day before -- the window a US evening
game can occupy -- and it says so in the reason detail.

FAIL CLOSED. No `commence_time`, or a ticker with no parseable date segment, is
`ticker_date_unverifiable`, not a pass. No series is exempted: of the 48 Kalshi
series in the live ledger (enumerated 2026-10-20), 46 carry `YYMONDD`; the two
that do not are KXMVE* multi-game combos (7 rows, Aug-Sep), none of which came
through the plan executor (no sport, market or position_key on any of them).

Switch `SYNDICATE_EXECUTION_TICKER_DATE_GUARD`, default ON; `off` restores the
unguarded path (for the reachability test and an emergency revert).
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from typing import Any

REFUSAL_MISMATCH = "ticker_date_mismatch"
REFUSAL_UNVERIFIABLE = "ticker_date_unverifiable"


def ticker_date_guard_enabled() -> bool:
    raw = str(os.environ.get("SYNDICATE_EXECUTION_TICKER_DATE_GUARD") or "").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _commence_utc(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _eastern_date(moment: datetime) -> date | None:
    try:
        from zoneinfo import ZoneInfo

        return moment.astimezone(ZoneInfo("America/New_York")).date()
    except Exception:  # noqa: BLE001 -- tzdata missing: the caller falls back, loudly
        return None


# THE PLACEHOLDER EXCEPTION'S KALSHI READ  [2026-10-20, user decision "Narrow
# exception", todo #710; loaned to lane ncaaf-commence-time-wrong by this lane].
# One signed GET per ticker, bounded, cached so a retried position in the same
# pass adds no call. Only ever reached on a one-day-early NCAAF mismatch.
_PLACEHOLDER_GET_SECONDS = 3.0
_PLACEHOLDER_CACHE_SECONDS = 600.0
_placeholder_market_cache: dict[str, tuple[float, Any]] = {}


def _placeholder_kalshi_time(ticker: Any) -> Any:
    import time

    from syndicate.features.shared.kalshi_placeholder_date import kalshi_event_time

    key = str(ticker or "").strip().upper()
    held = _placeholder_market_cache.get(key)
    if held is not None and time.monotonic() - held[0] < _PLACEHOLDER_CACHE_SECONDS:
        return held[1]
    moment = None
    try:
        from syndicate.features.shared.kalshi_client import fetch_market, request_budget

        with request_budget(_PLACEHOLDER_GET_SECONDS):
            result = fetch_market(key)
        if result.get("status") == "ok":
            moment = kalshi_event_time(result.get("market"))
    except Exception:  # noqa: BLE001 -- an unreadable GET keeps the refusal
        moment = None
    _placeholder_market_cache[key] = (time.monotonic(), moment)
    return moment


def ticker_date_refusal(
    ticker: Any,
    commence_time: Any,
    *,
    away_team: Any = None,
    home_team: Any = None,
    sport: Any = None,
    kalshi_time: Any = None,
) -> tuple[str | None, str]:
    """`(None, detail)` when the ticker's date is the game's date; else `(reason, detail)`.

    The keyword-only arguments exist for ONE exception (`kalshi_placeholder_date`):
    absent, behaviour is exactly as before.
    """
    if not ticker_date_guard_enabled():
        return None, "guard_off"
    from syndicate.features.shared.kalshi_catalogue import game_date_from_ticker

    ticker_date = game_date_from_ticker(ticker)
    if ticker_date is None:
        return REFUSAL_UNVERIFIABLE, "no_date_segment_in_ticker"
    start = _commence_utc(commence_time)
    if start is None:
        return REFUSAL_UNVERIFIABLE, "no_commence_time"
    eastern = _eastern_date(start)
    if eastern is not None:
        if eastern.isoformat() == ticker_date:
            return None, f"eastern={eastern.isoformat()}"
        if (
            away_team
            and home_team
            and (eastern - timedelta(days=1)).isoformat() == ticker_date
            and str(ticker or "").strip().upper().startswith("KXNCAAF")
        ):
            from syndicate.features.shared.kalshi_placeholder_date import placeholder_one_day_early

            moment = kalshi_time if kalshi_time is not None else _placeholder_kalshi_time(ticker)
            accepted, why = placeholder_one_day_early(
                ticker,
                eastern_game_date=eastern,
                away_team=away_team,
                home_team=home_team,
                sport=sport,
                kalshi_time=moment,
            )
            if accepted:
                print(
                    "[kalshi_ticker_date_guard] TICKER_DATE_PLACEHOLDER_ACCEPTED"
                    f" ticker={ticker!r} kalshi_time={moment.isoformat() if moment else None}"
                    f" away={away_team!r} home={home_team!r} {why}",
                    flush=True,
                )
                return None, why
            return REFUSAL_MISMATCH, f"ticker={ticker_date} eastern={eastern.isoformat()} placeholder={why}"
        return REFUSAL_MISMATCH, f"ticker={ticker_date} eastern={eastern.isoformat()}"
    utc_day = start.astimezone(timezone.utc).date()
    allowed = {utc_day.isoformat(), (utc_day - timedelta(days=1)).isoformat()}
    if ticker_date in allowed:
        return None, f"eastern_unavailable utc={utc_day.isoformat()}"
    return REFUSAL_MISMATCH, f"ticker={ticker_date} eastern_unavailable utc={utc_day.isoformat()}"
