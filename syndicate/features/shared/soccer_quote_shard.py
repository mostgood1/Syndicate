"""Which `book_quotes` shard date a soccer quote row is filed under.

Lane evening-utc-date-split (2026-11-23). Soccer's two OddsAPI quote writers,
`scripts/fetch_soccer_oddsapi_odds_local.py` and
`scripts/fetch_soccer_oddsapi_props_local.py`, shard by `commence_time[:10]`, the
UTC day. NCAAF and NFL shard by `odds_book_quotes.kickoff_shard_date`, the
Central day, and so does everything that reads a soccer slate: its live state,
the 2-minute live autorun and the live rail.

**WHY IT MATTERS.** The book grid is built from ONE shard per date. A soccer
kickoff after 6 PM Central (7 PM in summer) lands in the NEXT day's shard and
grid, while its live state stays on the Central day. Measured 2026-11-22, Real
Salt Lake @ Vancouver (MLS, 7:30 PM CT = 01:30Z on the 23rd):

- the 11-22 live-gameline index held the match in all 10 of its builds from
  01:42Z to 03:25Z (`indexed=1`), but considered only 2 rows: two Kalshi rows,
  which land on the Central day;
- its 473 OddsAPI rows were in `book_grid_2026-11-23`, whose builds had an
  empty index (`considered=0`).

So the match had no live model and placed 0 orders.

**THE SWITCH.** `SYNDICATE_SOCCER_QUOTE_SHARD_CENTRAL`. When it is absent, the
writers keep today's UTC shard. It is a BETTING CHANGE (it puts a live model on
matches that had none), so it loads only in a betting-change window.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Mapping

SOCCER_QUOTE_SHARD_CENTRAL_ENV = "SYNDICATE_SOCCER_QUOTE_SHARD_CENTRAL"


def soccer_quote_shard_central_enabled() -> bool:
    """Absent = OFF (UTC shard, today's behaviour). Only `1/on/true/yes` turns it on."""
    return str(os.environ.get(SOCCER_QUOTE_SHARD_CENTRAL_ENV) or "").strip().lower() in {"1", "on", "true", "yes"}


def soccer_quote_shard_date(row: Mapping[str, Any], *, now: datetime) -> str:
    """The shard date for one soccer quote row.

    Off: `commence_time[:10]`, or now's UTC date when the row has no kickoff.
    That is the writers' old inline expression, byte for byte.

    On: the Central kickoff day (`kickoff_shard_date`), or now's Central date
    when the row has no kickoff. A row with no kickoff is still kept: NCAAF drops
    one, but changing that is not this switch's job.
    """
    if not soccer_quote_shard_central_enabled():
        return str(row.get("commence_time") or "")[:10] or now.date().isoformat()

    from syndicate.features.shared.odds_book_quotes import kickoff_shard_date
    from syndicate.features.shared.timezone import central_date_from_iso

    central = kickoff_shard_date(row)
    if central:
        return central
    instant = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    today = central_date_from_iso(instant.astimezone(timezone.utc).isoformat())
    return today.isoformat() if today is not None else instant.date().isoformat()


def utc_shard_date(row: Mapping[str, Any]) -> str | None:
    """The shard a row's kickoff WOULD have under the old UTC key, or None."""
    text = str(row.get("commence_time") or "").strip()[:10]
    return text if len(text) == 10 and text[4] == "-" and text[7] == "-" else None
