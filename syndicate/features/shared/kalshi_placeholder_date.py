"""Kalshi's placeholder-dated NCAAF games: ONE predicate for the order guard and the board.

USER DECISION 2026-10-20 ~22:20Z (session 332cb014's chat, relayed verbatim):
"Narrow exception (Recommended)" -- "Accept a ticker dated exactly one day early
only when Kalshi's own time is that shared placeholder (03:00Z) AND both team
codes match the game. Applies to the order guard and the board join alike. Every
other mismatch is still refused." Lane `ncaaf-commence-time-wrong`, todo `#710`.

WHY. Kalshi lists FBS games before TV kickoff times exist, dated the Friday with
a shared placeholder time, and does not re-date them. Measured 2026-10-20 ~22Z on
every open `KXNCAAFGAME` event: 65 carry `expected_expiration_time` at T03:00:00Z
-- 29 `26OCT23` (-> 10-24T03:00Z) and 32 `26OCT30` (-> 10-31T03:00Z) among them.
Oregon @ Illinois is `KXNCAAFGAME-26OCT23OREILL`, rules "originally scheduled for
Oct 23", while ESPN (`timeValid: True`), CFBD (`startTimeTBD: False`) and OddsAPI
all say Saturday 10-24 19:00Z. The ticker-date guard refused that correct
contract twice on 10-20, and the board fan-in refused its quotes.

THE FOUR CONDITIONS, all required, each refused by name otherwise:

  1. an NCAAF Kalshi ticker (`KXNCAAF` prefix) -- the measured population; the
     derivation in (3) is not verified elsewhere (NBA has 4 markets at 42h);
  2. ticker date == the game's US/Eastern date MINUS EXACTLY ONE DAY;
  3. Kalshi's own event time == (ticker date + 1)T03:00:00Z. Read from
     `expected_expiration_time` / `occurrence_datetime` when the caller has them
     (the guard's GET), else derived as `close_time - 45h` (the board's stored
     lean market carries only `close_time`). Measured: close - expected = 45h on
     448/448 open NCAAF markets, and occurrence == expected on 448/448. If Kalshi
     changes that offset, the derived time stops landing on 03:00Z and the
     exception stops firing -- it fails CLOSED;
  4. the ticker's team blob matches THIS game's away+home teams
     (`kalshi_catalogue.match_event_blob`, the join's own matcher; an unresolved
     code is a refusal, e.g. `MOHCMU` today).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping

PLACEHOLDER_HOUR_UTC = 3
CLOSE_AFTER_EVENT = timedelta(hours=45)
NCAAF_TICKER_PREFIX = "KXNCAAF"


def _utc(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment.astimezone(timezone.utc) if moment.tzinfo else None


def eastern_game_date(commence_time: Any) -> date | None:
    """The game's US/Eastern calendar date -- the calendar Kalshi dates games in."""
    start = _utc(commence_time)
    if start is None:
        return None
    try:
        from zoneinfo import ZoneInfo

        return start.astimezone(ZoneInfo("America/New_York")).date()
    except Exception:  # noqa: BLE001 -- no tzdata: unknown, so no exception
        return None


def kalshi_event_time(market: Mapping[str, Any] | None) -> datetime | None:
    """Kalshi's own time for the event: the stated field, else `close_time - 45h`."""
    if not isinstance(market, Mapping):
        return None
    for field in ("expected_expiration_time", "occurrence_datetime"):
        stated = _utc(market.get(field))
        if stated is not None:
            return stated
    closes = _utc(market.get("close_time"))
    return closes - CLOSE_AFTER_EVENT if closes is not None else None


def placeholder_one_day_early(
    ticker: Any,
    *,
    eastern_game_date: date | str | None,
    away_team: Any,
    home_team: Any,
    sport: Any,
    kalshi_time: datetime | None,
) -> tuple[bool, str]:
    """`(True, detail)` only when all four conditions hold; else `(False, reason)`."""
    from syndicate.features.shared.kalshi_catalogue import (
        event_blob_from_ticker,
        game_date_from_ticker,
        match_event_blob,
    )

    text = str(ticker or "").strip().upper()
    if not text.startswith(NCAAF_TICKER_PREFIX):
        return False, "not_ncaaf_ticker"
    ticker_date = game_date_from_ticker(text)
    if ticker_date is None or eastern_game_date is None:
        return False, "undated"
    try:
        eastern = (
            eastern_game_date
            if isinstance(eastern_game_date, date)
            else date.fromisoformat(str(eastern_game_date).strip()[:10])
        )
        ticker_day = date.fromisoformat(ticker_date)
    except ValueError:
        return False, "undated"
    if eastern - ticker_day != timedelta(days=1):
        return False, f"not_one_day_early ticker={ticker_day} eastern={eastern}"
    expected = datetime(
        eastern.year, eastern.month, eastern.day, PLACEHOLDER_HOUR_UTC, tzinfo=timezone.utc
    )
    if kalshi_time is None:
        return False, "kalshi_time_unknown"
    if kalshi_time != expected:
        return False, f"not_placeholder kalshi_time={kalshi_time.isoformat()}"
    blob = event_blob_from_ticker(text)
    if not blob or not away_team or not home_team:
        return False, "teams_unknown"
    verdict = match_event_blob(
        blob, [{"away_team": away_team, "home_team": home_team}], sport=sport or "ncaaf"
    )
    if str(verdict.get("status") or "") != "ok":
        return False, f"teams_not_matched blob={blob} status={verdict.get('status')}"
    return True, f"placeholder_one_day_early ticker={ticker_day} eastern={eastern} blob={blob}"
