"""Per-GAME concentration for LIVE venue orders (lane `live-event-concentration`, todo `#711`).

USER DECISION 2026-10-21 ~00:55Z (relayed verbatim by session 332cb014): "Build
it (Recommended)" -- R1 + R2 in the executor, which sees held bets, with the
reachability tests; live only on a later yes.

WHY. Measured on the live Kalshi book 10-20 (findings_2026-10-20_live_event_
concentration.md): 62.5% of stake sat in games holding more than one position,
44.7% in several lines on ONE outcome. OKC@SAS carried OKC +20.5 ($10 @ -1329),
SAS +17.5 ($10 @ -809), OKC +16.5 and OKC -3.5 at once. Those legs came from
THREE executor passes (21:35Z, 00:13Z, 00:36Z). Each build sees a new line and
so a new `position_key`, and D1 (`held_position_for`) matches the key only. The
plan's own per-game budget (`bankroll_manager.apply_exposure_budgets`) cannot
see the passes, and the $5-10 stake band re-dollars every leg from full Kelly
read before that budget's decay. So the check lives HERE, against the held book.

THE RULE, LIVE mode only:

Both rules read the held book POOLED ACROSS LIVE VENUES (Kalshi + Polymarket), by
`event_id`: the same game is the same risk on either exchange.

- R1 ONE LEG PER GAME AXIS. The axis is the outcome a leg rides on: margin
  (spreads, alt spreads, moneyline of one game), total, one team's total, or
  one player's stat, each per segment. If a LIVE order on the same event
  and axis may be held, on EITHER venue, a new leg is refused `axis_held_live`. The held
  leg stands because it cannot be unwound here. The same `position_key` is NOT
  this rule: that is the same bet, and the duplicate / D1 paths own it.
  A TINY held leg does not claim its axis [user 2026-10-22 ~21:40Z, relayed by
  332cb014: "Ignore tiny held legs"]: a held leg staked under
  `SYNDICATE_LIVE_EVENT_AXIS_MIN_HELD_DOLLARS` (default $1) does not block a new
  leg on that axis. Measured the first live R1 refusal: a 1-contract $0.48 UConn
  -15.5 spread from 10-20 blocked a $5 UConn moneyline. Tiny legs still count
  toward R2's dollars.
- R2 A DOLLAR CAP PER GAME, held bets included: when the game already holds a
  leg, the order is placed at `min(stake, cap - held)`. It is refused
  `event_exposure_cap` when that room cannot buy one contract at the order's
  price. A game's first leg is not capped here (the order cap and the band
  bound it).

NOT a market, sport or family exclusion, and no count cap. An event's ONLY leg
is never touched, so every line is still its own decision ("every line is its
own decision", learnings.md). A leg competes only with legs on the same game.

`SYNDICATE_LIVE_EVENT_CONCENTRATION` = off (absent, today's behaviour) |
shadow (logs the verdict, changes nothing) | on. Any other value is OFF and
says so: a typo must not silently arm a rule that moves real stakes.
`SYNDICATE_LIVE_EVENT_MAX_DOLLARS` (default 15 = one max band leg plus one min).
`SYNDICATE_LIVE_EVENT_AXIS_MIN_HELD_DOLLARS` (default 1; 0 = every held leg blocks its axis).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

MODE_ENV = "SYNDICATE_LIVE_EVENT_CONCENTRATION"
MAX_DOLLARS_ENV = "SYNDICATE_LIVE_EVENT_MAX_DOLLARS"
DEFAULT_MAX_DOLLARS = 15.0
AXIS_MIN_HELD_ENV = "SYNDICATE_LIVE_EVENT_AXIS_MIN_HELD_DOLLARS"
DEFAULT_AXIS_MIN_HELD_DOLLARS = 1.0

REFUSAL_AXIS_HELD = "axis_held_live"
REFUSAL_EVENT_CAP = "event_exposure_cap"

VERDICT_PASS = "pass"
VERDICT_SAME_BET = "same_bet"
VERDICT_TRIM = "trim"

_MODES = ("off", "shadow", "on")

# Every market string a live venue plan may carry must land on a named axis.
# `tests/test_event_concentration.py` gates this list: a new market that falls
# through to `other` fails the test rather than going ungrouped in silence.
_MARGIN_MARKETS = ("h2h", "h2h_3_way", "moneyline", "ml", "spreads", "spreads_alt", "alternate_spreads", "draw_no_bet")
_TOTAL_MARKETS = ("totals", "totals_alt", "alternate_totals")
_TEAM_TOTAL_MARKETS = ("team_totals", "team_total", "alternate_team_totals")
_PROP_PREFIXES = ("player_", "batter_", "pitcher_")
_PROP_MARKETS = ("outs", "anytime_goalscorer")
# Game-level markets on their own outcome (not margin, not the points total):
# both teams to score, and corners -- whose main and alternate lines share one axis.
_OWN_AXIS_MARKETS = {"btts": "btts", "totals_corners": "corners", "alternate_totals_corners": "corners"}


def mode() -> str:
    raw = str(os.environ.get(MODE_ENV) or "").strip().lower()
    return raw if raw in _MODES else "off"


def mode_invalid() -> str | None:
    """The raw value when it is set but not a known mode (it then reads as off)."""
    raw = str(os.environ.get(MODE_ENV) or "").strip().lower()
    return raw if raw and raw not in _MODES else None


def max_event_dollars() -> float:
    raw = str(os.environ.get(MAX_DOLLARS_ENV) or "").strip()
    try:
        value = float(raw) if raw else DEFAULT_MAX_DOLLARS
    except ValueError:
        return DEFAULT_MAX_DOLLARS
    if value != value or value <= 0 or value == float("inf"):
        return DEFAULT_MAX_DOLLARS
    return value


def axis_min_held_dollars() -> float:
    """Held legs staked below this do not claim their axis for R1. 0 = all do.

    Unparseable, negative, NaN or infinite -> the $1 default, never "ignore
    everything": an unknown must not widen what gets through.
    """
    raw = str(os.environ.get(AXIS_MIN_HELD_ENV) or "").strip()
    try:
        value = float(raw) if raw else DEFAULT_AXIS_MIN_HELD_DOLLARS
    except ValueError:
        return DEFAULT_AXIS_MIN_HELD_DOLLARS
    if value != value or value < 0 or value == float("inf"):
        return DEFAULT_AXIS_MIN_HELD_DOLLARS
    return value


def _get(obj: Any, name: str) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(name)
    return getattr(obj, name, None)


# Segment suffixes the venue order path uses (`kalshi_orders._TEAM_SIDED_MARKETS`:
# `h2h_h1`, `h2h_p2`) beyond the catalogue's own vocabulary.
_EXTRA_SEGMENT_SUFFIX = {"h1": "1h", "h2": "2h", "p1": "p1", "p2": "p2", "p3": "p3"}


def _suffixes() -> dict[str, str]:
    from syndicate.features.shared.kalshi_catalogue import _MARKET_SUFFIX_SEGMENT

    return {**_EXTRA_SEGMENT_SUFFIX, **_MARKET_SUFFIX_SEGMENT}


def _segment(obj: Any) -> str:
    from syndicate.features.shared.kalshi_catalogue import segment_for_board_row

    market = str(_get(obj, "market") or "").strip().lower()
    if not str(_get(obj, "segment") or "").strip():
        for suffix, segment in _EXTRA_SEGMENT_SUFFIX.items():
            if market.endswith("_" + suffix):
                return segment
    row = {"segment": _get(obj, "segment"), "market": market}
    return str(segment_for_board_row(row) or "full")


def _base_market(market: str) -> str:
    """`totals_1st_5_innings` -> `totals`, `h2h_q1` -> `h2h`: the segment is keyed apart."""
    for suffix in _suffixes():
        if market.endswith("_" + suffix):
            return market[: -len(suffix) - 1]
    return market


def axis_kind(market: Any, player_name: Any = None) -> str:
    """`margin` | `total` | `teamtotal` | `prop` | `btts` | `corners` | `other` for one market string."""
    base = _base_market(str(market or "").strip().lower())
    if base in _OWN_AXIS_MARKETS:
        return _OWN_AXIS_MARKETS[base]
    if str(player_name or "").strip() or base.startswith(_PROP_PREFIXES) or base in _PROP_MARKETS:
        return "prop"
    if base in _TEAM_TOTAL_MARKETS:
        return "teamtotal"
    if base in _MARGIN_MARKETS:
        return "margin"
    if base in _TOTAL_MARKETS:
        return "total"
    return "other"


def axis_key(obj: Any) -> str:
    """The outcome one leg rides on: a pure function of the bet's identity.

    `other` keys on the market itself, so an unclassified market groups only
    with itself (the narrowest grouping, never a wider one by accident).
    """
    market = str(_get(obj, "market") or "").strip().lower()
    player = str(_get(obj, "player_name") or "").strip().lower()
    kind = axis_kind(market, player)
    seg = _segment(obj)
    if kind == "prop":
        return f"prop|{_base_market(market)}|{player}|{seg}"
    if kind == "teamtotal":
        return f"teamtotal|{str(_get(obj, 'side') or '').strip().lower()}|{seg}"
    if kind in ("margin", "total", "btts", "corners"):
        return f"{kind}|{seg}"
    return f"other|{market}|{seg}"


def _stake(order: Mapping[str, Any]) -> float:
    for key in ("fill_stake_dollars", "requested_stake_dollars"):
        try:
            value = float(order.get(key))
        except (TypeError, ValueError):
            continue
        if value == value and value > 0:
            return value
    return 0.0


def contract_cost(american: Any) -> float | None:
    """One contract's price in dollars (= implied probability) from an American price."""
    try:
        price = float(american)
    except (TypeError, ValueError):
        return None
    if price <= -100:
        return -price / (-price + 100.0)
    if price >= 100:
        return 100.0 / (price + 100.0)
    return None


def held_live_orders(
    orders: Iterable[Mapping[str, Any]], *, event_id: str, venue: str | None = None
) -> list[Mapping[str, Any]]:
    """LIVE orders on this event that a venue may hold, any slate, EVERY venue.

    POOLED ACROSS VENUES [2026-10-21, requested by session 332cb014]: one game is
    one risk whichever exchange holds the leg, and `event_id` is the board's own
    id on both (measured: OKC@SAS, SF@ATL and PITT@MIA carry the same id on the
    Kalshi and Polymarket ledger rows). Measured the same night: SF@ATL under
    49.5 held on Kalshi (21:36Z) AND Polymarket (02:00:59Z), which D1 cannot see
    because its key includes the venue. `venue` narrows to one venue (tests only).

    "May be held" is the ledger's own predicate (`_blocks_a_new_attempt`) minus
    `execution_guard.is_non_position`, exactly as D1's `held_position_for` reads
    it. Exit (sell) rows are not entries and are skipped. An exited entry still
    counts, which over-counts room after a sale: conservative, and owned by
    `kalshi-exit-path` if it should change.
    """
    from syndicate.features.shared.execution_exits import is_exit_key
    from syndicate.features.shared.execution_guard import is_non_position
    from syndicate.features.shared.execution_ledger import LIVE, _blocks_a_new_attempt

    held = []
    for order in orders or ():
        if not isinstance(order, Mapping):
            continue
        if str(order.get("mode") or "") != LIVE:
            continue
        if venue is not None and str(order.get("venue") or "") != venue:
            continue
        if str(order.get("event_id") or "") != event_id:
            continue
        if is_exit_key(order.get("idempotency_key")):
            continue
        if _blocks_a_new_attempt(order) and not is_non_position(order):
            held.append(order)
    return held


@dataclass(frozen=True)
class Verdict:
    action: str  # pass | same_bet | trim | refuse
    reason: str | None
    stake: float
    held_dollars: float
    room: float | None
    axis: str
    blocking_key: str | None = None


def verdict_for(
    request: Any,
    held: Iterable[Mapping[str, Any]],
    *,
    cap: float,
    placed_this_pass: Iterable[Mapping[str, Any]] = (),
    axis_min_held: float | None = None,
) -> Verdict:
    """R1 then R2 for one order request against what is held on its game.

    `placed_this_pass` = orders this executor loop already sent, as
    `{position_key, market, segment, player_name, side, requested_stake_dollars}`.
    It is counted even if the ledger read has not caught up yet, and de-duplicated
    against the ledger by `position_key`.
    `axis_min_held` = the R1 tiny-leg line; None reads the env (default $1).
    """
    stake = float(_get(request, "requested_stake_dollars") or 0.0)
    own_keys = {str(_get(request, "position_key") or "").strip(), str(_get(request, "legacy_position_key") or "").strip()}
    own_keys.discard("")
    axis = axis_key(request)
    by_key: dict[str, Mapping[str, Any]] = {}
    for order in list(held) + list(placed_this_pass or ()):
        key = str(order.get("position_key") or "").strip() or f"_anon{id(order)}"
        by_key.setdefault(key, order)
    if own_keys & set(by_key):
        # The same bet: the duplicate path (same slate) or D1 (other slate) owns it.
        return Verdict(VERDICT_SAME_BET, None, stake, 0.0, None, axis)
    held_dollars = round(sum(_stake(o) for o in by_key.values()), 2)
    min_held = axis_min_held_dollars() if axis_min_held is None else float(axis_min_held)
    for key, order in by_key.items():
        if axis_key(order) == axis and _stake(order) >= min_held:
            return Verdict("refuse", REFUSAL_AXIS_HELD, 0.0, held_dollars, None, axis, blocking_key=key)
    if held_dollars <= 0:
        # The game's ONLY leg: concentration needs a second one. Never touched.
        return Verdict(VERDICT_PASS, None, stake, held_dollars, None, axis)
    room = round(cap - held_dollars, 2)
    if stake <= room:
        return Verdict(VERDICT_PASS, None, stake, held_dollars, room, axis)
    one = contract_cost(_get(request, "requested_price"))
    if one is None or room < one:
        return Verdict("refuse", REFUSAL_EVENT_CAP, 0.0, held_dollars, room, axis)
    return Verdict(VERDICT_TRIM, None, round(room, 2), held_dollars, room, axis)
