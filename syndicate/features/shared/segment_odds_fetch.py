"""Per-event QUARTER/HALF odds capture, shared by every football fetcher.

WHY THIS EXISTS, and why it is one module rather than a copy per sport.

    Measured 2026-09-05 on production `ncaaf_source/tracking/book_quotes`:
    **153,723 of 153,723 rows carried `segment == "full"`** across 61 events and
    25+ books. NCAAF has never captured a single half or quarter price.

The two masks over the same defect:

  * **NCAAF never asks.** `fetch_ncaaf_oddsapi_game_lines.py` requests
    `full_game_market_keys(("h2h","spreads","totals"))` and nothing else.
  * **NFL asks in a `market_map` that only ever TAGS.**
    `_nfl_segment_market_map()` in `fetch_nfl_team_odds_local.py` builds all 36
    segment keys and its docstring claims they are used *"both to REQUEST the
    keys and to TAG the returned quotes so the two cannot drift"*. They are not.
    `main()` calls `fetch_odds(api_key=..., region=...)` and never passes
    `markets=`, so the literal default `"h2h,spreads,totals"` goes out. The map
    reaches `quote_rows_from_oddsapi_events` only, where a key that never
    arrived can never be tagged. **Dead code that reads as alive, with a
    docstring asserting the opposite of the behaviour.**

THE BULK ENDPOINT DOES NOT SERVE THESE MARKETS. This is not a guess and it is
not new: `fetch_soccer_oddsapi_odds_local.py:116-139` records the live failure
verbatim -- merging segment keys into `markets=` on `/sports/{key}/odds`
returned `HTTP 422 INVALID_MARKET` for every league and every call, killing all
soccer capture for nine days in August. `fetch_ncaaf_oddsapi_props_local.py:294`
records the same thing for NCAAF props. So copying NFL's pattern would ship
nothing; the request has to move to `/sports/{key}/events/{id}/odds`.

**AND THE PER-EVENT ROUTE DEMONSTRABLY WORKS FOR FOOTBALL.** The one football
fetcher that ever used it -- `fetch_nfl_preseason_odds.py`, per-event, 36
segment keys -- captured, on production NFL shards:

    2026-08-23   14,502 rows   6,603 NONFULL (45.53%)   10 books   4 events
                 h1 1,281 | h2 2,721 | q1 290 | q2 522 | q3 1,201 | q4 588
    2026-08-16    6,681 rows   1,340 NONFULL (20.06%)    5 books   2 events

That is the falsification test for this whole design, and it came back
negative: the books price football halves and quarters, richly, and the
per-event route delivers them.

---

BILLING, which is what shapes every default here.

OddsAPI bills a per-event odds call at **markets x regions**. The repo already
encodes the consequence and it is easy to get wrong:
`shared/odds_regions.py` exists precisely to keep the widened
`SYNDICATE_LIVE_ODDS_GAME_LINE_REGIONS` (`eu,us_ex`) on the CHEAP side of the
split -- *"the one costing ~1M rather than ~30K"*. MLB obeys this: its bulk
slate call is widened, and `_fetch_live_event_odds` is handed the RAW `regions`
(`fetch_mlb_oddsapi_local.py:1302`), i.e. `us` alone.

**So this module takes its regions from its OWN key and defaults to `us`.** It
deliberately does NOT call `game_line_regions()`. Reading the shared knob here
would silently triple the bill of the most expensive call on the platform,
which is the exact mistake `odds_regions.py` was written to prevent.

Cost of the shipped NCAAF default, measured inputs throughout:

    unit          3 markets (h2h/spreads/totals, NO alternates) x 1 region
                  = 3 credits per event per sweep
    concurrency   NCAAF kickoffs are CLUSTERED, so the live tier is priced by
                  peak concurrency, not slate size. Production
                  `/ncaaf/api/cards`, US-slate 2026-09-05 (42 kickoffs):
                      in_play (3h30)  PEAK 14   mean 10.49
                      h1_live (1h45)  PEAK 12   mean  5.99
                  A blanket "every event every 2 min" would be 42 x 3 x 30 =
                  3,780 credits/hr; scoping to the h1 window is 5.99 x 3 x 24 =
                  ~431 credits/hr. **A 8.8x reduction at the mean, and it is
                  the scoping that buys it, not the market count.**

WHY THE LIVE WINDOW IS 1h45 AND NOT "WHILE THE GAME IS ON". A first-half line
only exists between kickoff and halftime -- after that the market is settled and
delisted, and every further call buys nothing. Scoping the h1 tier to the h1
market's own life is therefore not a compromise on coverage; a longer window is
strictly wasted credits. The window is a knob so a quarters tier (which does
live the whole game) can widen it without a code change.

ALTERNATES ARE EXCLUDED, on purpose. They were ~60% of the NFL preseason
segment rows above (`h2/spreads_alt` 1,058 of 6,603 on 08-23), they triple the
per-call bill, and `period_lines.py:92-100` filters them straight back out.

---

DEFAULT OFF, and stating that plainly because `CLAUDE.md` requires it:
**absent means OFF here.** `segment_markets_for()` returns `{}` when
`SYNDICATE_<SPORT>_SEGMENT_MARKETS` is unset, so deploying this module changes
no behaviour and spends no credit until someone sets the key. That is
deliberate: a segment quote becomes a board row, and a board row can become a
stakeable order, and the settlement key had no segment dimension until
`bet_status.segment_refusal` -- a segment order inherited the WHOLE-GAME actual.
Capture must not outrun grading.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

from syndicate.features.shared.market_segments import segment_market_keys

#: The bases requested per segment. NOT `alternate_*` -- see the module
#: docstring for the measurement that settles it.
DEFAULT_BASES: tuple[str, ...] = ("h2h", "spreads", "totals")

#: `kickoff - now <= this` puts an event in the pregame tier. 6h.
DEFAULT_PREGAME_WINDOW_SECONDS = 6 * 3600

#: `now - kickoff <= this` keeps an event in the live tier. 1h45 -- the life of
#: a first-half market, not the life of the game.
DEFAULT_LIVE_WINDOW_SECONDS = 105 * 60

#: A circuit breaker, not a tuning knob. The cost of this tier is linear in
#: events and the slate is supplied by a vendor; a bad slate response must not
#: be able to spend an unbounded number of credits. Trips loudly.
DEFAULT_MAX_EVENTS = 40


def _env_get(name: str, env: Mapping[str, str] | None = None) -> str:
    source = os.environ if env is None else env
    return str(source.get(name) or "").strip()


def _env_int(name: str, default: int, env: Mapping[str, str] | None = None) -> int:
    raw = _env_get(name, env)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value >= 0 else default


def env_prefix(sport: str) -> str:
    return f"SYNDICATE_{str(sport or '').strip().upper()}_SEGMENT"


def configured_segments(sport: str, *, env: Mapping[str, str] | None = None) -> tuple[str, ...]:
    """Which segments this sport is configured to capture. **Empty = OFF.**

    `SYNDICATE_NCAAF_SEGMENT_MARKETS`:
        unset / ""   -> ()            capture disabled, no call, no credit
        "h1"         -> ("h1",)
        "h1,h2"      -> ("h1", "h2")
        "all"        -> every segment the sport declares in `SPORT_SEGMENTS`

    An unknown token is DROPPED rather than guessed, matching
    `market_segments.segment_market_keys`, and dropping every token leaves the
    tier off rather than falling back to something expensive.
    """
    raw = _env_get(f"{env_prefix(sport)}_MARKETS", env).lower()
    if not raw:
        return ()
    declared = tuple(
        seg for seg, _ in
        {spec[0]: None for spec in segment_market_keys(sport).values()}.items()
    )
    if raw == "all":
        return declared
    wanted = [token.strip() for token in raw.split(",") if token.strip()]
    return tuple(token for token in wanted if token in declared)


def segment_markets_for(sport: str, *, env: Mapping[str, str] | None = None) -> dict[str, tuple[str, str]]:
    """market key -> (segment, canonical market) for the configured segments.

    Returns `{}` when disabled. Built from the SHARED vocabulary
    (`market_segments`), never a local literal list -- `learnings.md`
    2026-08-23 makes a module holding its own market names FORBIDDEN, because
    it will drift from `market_keys` silently.
    """
    segments = configured_segments(sport, env=env)
    if not segments:
        return {}
    bases = _env_get(f"{env_prefix(sport)}_BASES", env)
    base_tuple = tuple(b.strip() for b in bases.split(",") if b.strip()) if bases else DEFAULT_BASES
    return segment_market_keys(sport, segments=segments, bases=base_tuple)


def segment_regions(sport: str, *, env: Mapping[str, str] | None = None) -> str:
    """Regions for the PER-EVENT call. Defaults to `us`, and is deliberately
    NOT `game_line_regions()`.

    See the module docstring: the shared game-line knob widens to `eu,us_ex`,
    and applying it here would multiply the bill of the most expensive call on
    the platform by 3 with no line of code saying so.
    """
    return _env_get(f"{env_prefix(sport)}_REGIONS", env) or "us"


def _parse_commence(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def events_in_window(
    events: Sequence[Mapping[str, Any]],
    *,
    sport: str,
    now: datetime | None = None,
    env: Mapping[str, str] | None = None,
) -> tuple[list[Mapping[str, Any]], dict[str, Any]]:
    """The events worth a per-event segment call right now, plus the counters.

    An event is in scope when it sits inside EITHER tier:

        pregame :  0 <= (kickoff - now) <= pregame_window
        live    :  0 <  (now - kickoff) <= live_window

    Both counters are returned separately because they are priced differently
    and the report has to be able to say which tier spent the credits.

    An event with no parsable `commence_time` is EXCLUDED and counted. It
    cannot be placed in either tier, and including it would mean paying for a
    call whose scoping is unknown -- `learnings.md`: an unknown must not
    default to the permissive branch.
    """
    moment = now or datetime.now(tz=timezone.utc)
    pregame_window = _env_int(f"{env_prefix(sport)}_PREGAME_WINDOW_SECONDS", DEFAULT_PREGAME_WINDOW_SECONDS, env)
    live_window = _env_int(f"{env_prefix(sport)}_LIVE_WINDOW_SECONDS", DEFAULT_LIVE_WINDOW_SECONDS, env)
    max_events = _env_int(f"{env_prefix(sport)}_MAX_EVENTS", DEFAULT_MAX_EVENTS, env)

    scoped: list[tuple[float, Mapping[str, Any], str]] = []
    stats = {
        "considered": len(events),
        "pregame": 0,
        "live": 0,
        "out_of_window": 0,
        "no_commence_time": 0,
        "capped": 0,
        "pregame_window_seconds": pregame_window,
        "live_window_seconds": live_window,
        "max_events": max_events,
    }
    for event in events:
        kickoff = _parse_commence(event.get("commence_time"))
        if kickoff is None:
            stats["no_commence_time"] += 1
            continue
        until = (kickoff - moment).total_seconds()
        if 0 <= until <= pregame_window:
            tier = "pregame"
        elif -live_window <= until < 0:
            tier = "live"
        else:
            stats["out_of_window"] += 1
            continue
        stats[tier] += 1
        # Sorted by |until| so that if the cap trips, the events kept are the
        # ones closest to kickoff -- the ones whose prices are moving.
        scoped.append((abs(until), event, tier))

    scoped.sort(key=lambda item: item[0])
    if len(scoped) > max_events:
        stats["capped"] = len(scoped) - max_events
        scoped = scoped[:max_events]
    return [event for _, event, _ in scoped], stats


def estimated_credits(n_events: int, n_markets: int, regions: str) -> int:
    """OddsAPI bills a per-event odds call at markets x regions.

    Reported BEFORE the calls go out so a misconfiguration is visible in the
    log as a number rather than as a quota reading three hours later.
    """
    region_count = len([r for r in str(regions or "").split(",") if r.strip()]) or 1
    return int(n_events) * int(n_markets) * region_count


def fetch_event_segments(
    *,
    api_key: str,
    sport: str,
    sport_key: str,
    base_url: str,
    events: Sequence[Mapping[str, Any]],
    session: Any = None,
    now: datetime | None = None,
    env: Mapping[str, str] | None = None,
    timeout: int = 20,
    log_prefix: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Per-event segment odds for the in-window events. Never raises.

    Returns `(payloads, stats)`. `payloads` is the same
    list-of-events-carrying-bookmakers shape the bulk endpoint returns, so a
    caller hands it straight to `quote_rows_from_oddsapi_events` with the
    segment market map -- no second parser.

    A per-event failure is per-event: one 422 or timeout must not cost the
    other events on the slate, which is how
    `fetch_nfl_preseason_odds.py:336-341` already handles it.
    """
    import requests

    prefix = log_prefix or f"[{sport}_odds]"
    market_map = segment_markets_for(sport, env=env)
    stats: dict[str, Any] = {
        "enabled": bool(market_map),
        "segments": list(configured_segments(sport, env=env)),
        "markets": len(market_map),
        "requested_events": 0,
        "ok_events": 0,
        "failed_events": 0,
        "estimated_credits": 0,
    }
    if not market_map:
        # Absent means OFF, and it says so rather than returning a silent [].
        print(f"{prefix} SEGMENT_CAPTURE disabled ({env_prefix(sport)}_MARKETS unset)", flush=True)
        return [], stats

    scoped, window_stats = events_in_window(events, sport=sport, now=now, env=env)
    stats.update(window_stats)
    regions = segment_regions(sport, env=env)
    markets_csv = ",".join(sorted(market_map.keys()))
    stats["requested_events"] = len(scoped)
    stats["regions"] = regions
    stats["estimated_credits"] = estimated_credits(len(scoped), len(market_map), regions)

    print(
        f"{prefix} SEGMENT_PLAN segments={','.join(stats['segments'])} "
        f"markets={len(market_map)} regions={regions} considered={window_stats['considered']} "
        f"pregame={window_stats['pregame']} live={window_stats['live']} "
        f"out_of_window={window_stats['out_of_window']} no_commence={window_stats['no_commence_time']} "
        f"capped={window_stats['capped']} events={len(scoped)} "
        f"est_credits={stats['estimated_credits']}",
        flush=True,
    )
    if not scoped:
        return [], stats

    from syndicate.features.shared.oddsapi_quota import record_oddsapi_quota

    http = session or requests
    payloads: list[dict[str, Any]] = []
    for event in scoped:
        event_id = str(event.get("id") or "").strip()
        if not event_id:
            stats["failed_events"] += 1
            continue
        try:
            response = http.get(
                f"{str(base_url).rstrip('/')}/sports/{sport_key}/events/{event_id}/odds",
                params={
                    "apiKey": api_key,
                    "regions": regions,
                    "markets": markets_csv,
                    "oddsFormat": "american",
                },
                timeout=timeout,
            )
            # Recorded BEFORE the status check: a 4xx still carries the quota
            # headers, and an unattributed spend is how an unreadable cost
            # model is born. `response.url` so the recorder sees the markets
            # that actually went out; it redacts apiKey itself.
            record_oddsapi_quota(response.headers, sport=sport, endpoint=response.url)
            if getattr(response, "status_code", 200) >= 400:
                stats["failed_events"] += 1
                stats.setdefault("last_error", f"HTTP {response.status_code}: {str(response.text)[:200]}")
                continue
            payload = response.json()
        except Exception as exc:  # noqa: BLE001
            stats["failed_events"] += 1
            stats.setdefault("last_error", f"{type(exc).__name__}: {exc}")
            continue
        if isinstance(payload, dict) and payload.get("id"):
            payloads.append(payload)
            stats["ok_events"] += 1
        else:
            stats["failed_events"] += 1

    print(
        f"{prefix} SEGMENT_FETCH ok={stats['ok_events']} failed={stats['failed_events']} "
        f"of={len(scoped)} est_credits={stats['estimated_credits']}"
        + (f" last_error={stats['last_error']!r}" if stats.get("last_error") else ""),
        flush=True,
    )
    return payloads, stats


def merged_market_map(
    full_map: Mapping[str, tuple[str, str]],
    sport: str,
    *,
    env: Mapping[str, str] | None = None,
) -> dict[str, tuple[str, str]]:
    """Full-game keys plus the configured segment keys, for ONE tagging pass.

    `quote_rows_from_oddsapi_events` DROPS any market key absent from the map,
    so the union is what lets a caller concatenate bulk payloads and per-event
    payloads and run a single pass over both. `_KEY_FIELDS` in
    `odds_book_quotes` carries `segment`, so a full-game row and an `h1` row on
    the same event/book/market are distinct keys and neither displaces the
    other.
    """
    return {**dict(full_map), **segment_markets_for(sport, env=env)}
