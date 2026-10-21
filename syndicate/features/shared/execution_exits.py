"""The EXIT path: sell a held Kalshi contract before it settles.

Until this module every position was held to settlement -- the system could
buy and could cancel a resting buy, and nothing could SELL. Verified
2026-10-19: no sell/close/take-profit code existed; `kalshi_orders._side_to_kalshi`
is buy-only and the only venue writes outside placement were cancels.

POLYMARKET IS WATCHED IN PAPER TOO `[2026-10-19]`, through one signed book read
per market. Only legs the side's NAME or the venue states (over/under/yes/no,
`held_side`) are mapped; team sides are counted `polymarket_team_leg_unresolved`
and never guessed. A live Polymarket sale is NOT built (`venue_live_exit_unbuilt`).

--------------------------------------------------------------------------
PAPER FIRST, AND PAPER IS THE DEFAULT
--------------------------------------------------------------------------

`SYNDICATE_EXIT_MODE` is `paper` unless it says `off` or `live`. Paper sends
nothing: it watches every open Kalshi position, records the best bid it could
have sold into (a high-water mark), and books the FIRST time a rule would have
fired as a paper exit. `exit_counterfactual` then grades that exit against what
holding to settlement actually paid. A week of that is the evidence for or
against going live, and for which margin.

Live needs ALL of: `SYNDICATE_EXIT_MODE=live`, `SYNDICATE_EXIT_LIVE_ARMED`,
the entry path's own `SYNDICATE_EXECUTION_LIVE_ARMED`, a clear kill switch, and
the venue confirming it holds the contracts. Absent any one, nothing is sent.

--------------------------------------------------------------------------
ITS OWN DOCUMENT AND ITS OWN KEY SPACE
--------------------------------------------------------------------------

Exits are NOT rows in `execution_ledger.json`, and that is structural rather
than a convention a caller has to remember:

* `execution_guard.spent_today` sums that ledger, so an exit row there would be
  charged against the ENTRY caps -- a sale would reduce what may be bought.
* `unreconciled_orders` gates every live entry run on that ledger, so a resting
  sell would freeze buying on both venues.
* `reconcile_live_orders`' orphan scan claims any venue order whose
  `client_order_id` is 24 hex chars (`_is_our_key`). An exit key is 24 chars
  starting with `x`, so that scan never mistakes a sale for a missing entry.

The exit key is derived from the ENTRY key, so one entry has exactly one exit
and a recomputed decision is a duplicate, not a second sale.

--------------------------------------------------------------------------
THE SAME DISCIPLINE AS `place_order`, FOR THE LIVE HALF
--------------------------------------------------------------------------

Build (refusals write nothing) -> write-ahead `submitted` row -> send ->
complete from the venue's answer. A send that raised stays `failed` and blocks
a re-send of that exit until `reconcile_exit_orders` asks the venue. Any exit
in `submitted`/`failed` blocks every NEW live exit, for the reason an
unreconciled entry blocks every new entry.

SETTLEMENT KNOWS ABOUT SALES (2026-10-19, lane kalshi-exit-settlement):
`venue_settlement.settle_from_venue` reads this document's LIVE rows by
`exit_idempotency_key(entry_key)` and grades a sold entry from both fills
(`exit_adjusted_pnl`); a live exit still `submitted`/`failed` defers the grade,
and paper rows are never read. `paper_settlement.settle_orders`' 24h inference
fallback applies the same rules. NOT YET SAFE TO ARM regardless -- see
`LIVE_BLOCKERS` for what remains.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import urllib.parse
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

EXIT_OFF = "off"
EXIT_PAPER = "paper"
EXIT_LIVE = "live"

EXIT_PAPER_FILLED = "paper_filled"
EXIT_SUBMITTED = "submitted"
EXIT_FILLED = "filled"
EXIT_REJECTED = "rejected"
EXIT_FAILED = "failed"
EXIT_DEAD = "dead"  # the venue cancelled it with nothing traded (IOC miss)

RULE_TAKE_PROFIT = "take_profit"
RULE_MODEL_FAIR = "model_fair"

# What must be true before live exits are armed, beyond the switches. Printed
# on every live refusal so a person flipping the switch reads it.
#
# CLEARED 2026-10-19: "venue_settlement grades an entry from Kalshi's settlement
# record, which does not know the position was sold first" -- settlement is now
# exit-aware (`venue_settlement.exit_adjusted_pnl`), and so is the 24h INFERENCE
# fallback in `paper_settlement.settle_orders` (same helpers, same defer rule).
# EMPTY since 2026-10-19 22:42:59Z: the v2 sell body was ACCEPTED and FILLED on a
# real one-contract sale (Thornton NO, order 01a15655-1d08-7994-88cc-6fdecbd1b87f:
# `buy yes` @ limit 0.14 filled 0.13 = NO sold @ 0.87, fee $0.008, venue holding
# -5 -> -4; deploys.md 2026-10-19 22:42Z). Arming live exits is still the user's call.
LIVE_BLOCKERS: tuple[str, ...] = ()

_DEFAULT_TAKE_PROFIT_MARGIN = 0.08
_DEFAULT_LOOKBACK_DAYS = 3
_WATCH_RETENTION_DAYS = 14
_MAX_TICKERS_PER_TICK = 400
_QUOTE_CHUNK = 50
# Polymarket books are one SIGNED read per market (5 s timeout each), so they are
# bounded separately and much lower than Kalshi's batched public read.
_MAX_POLYMARKET_BOOKS_PER_TICK = 40
# Unfilled (dead) immediate-or-cancel sales per entry before it stops re-sending.
_MAX_DEAD_RETRIES = 3

KALSHI = "kalshi"
POLYMARKET = "polymarket"
# The margins the readout replays against each position's high-water mark.
COUNTERFACTUAL_MARGINS = (0.02, 0.04, 0.06, 0.08, 0.10, 0.15, 0.20, 0.30)


class ExitBuildError(ValueError):
    """The exit cannot become a valid order. Raised BEFORE anything is sent."""

    venue_contacted = False


# --------------------------------------------------------------------------
# Switches
# --------------------------------------------------------------------------


def exit_mode() -> str:
    """`paper` unless explicitly `off` or `live`. A typo cannot reach `live`."""
    raw = str(os.environ.get("SYNDICATE_EXIT_MODE") or "").strip().lower()
    if raw == EXIT_LIVE:
        return EXIT_LIVE
    if raw == EXIT_OFF:
        return EXIT_OFF
    return EXIT_PAPER


def exit_live_armed() -> bool:
    """The exit's OWN arm AND the entry path's arm. Checked per order."""
    from syndicate.features.shared.execution_ledger import live_execution_armed

    raw = str(os.environ.get("SYNDICATE_EXIT_LIVE_ARMED") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"} and live_execution_armed()


def _float_env(name: str, default: float) -> float:
    try:
        value = float(str(os.environ.get(name)).strip())
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) else default


def take_profit_margin() -> float:
    """Dollars per contract, NET of the entry fee and the exit fee."""
    return _float_env("SYNDICATE_EXIT_TAKE_PROFIT_MARGIN", _DEFAULT_TAKE_PROFIT_MARGIN)


def fair_margin() -> float:
    """How far past model fair the net bid must be. 0.0 = at fair."""
    return _float_env("SYNDICATE_EXIT_FAIR_MARGIN", 0.0)


def live_exit_rules() -> frozenset[str]:
    """Which rules may SELL for real. Default: `take_profit` only.

    User decision 2026-10-20 ~22:2xZ ("Arm take-profit tonight"): live selling for
    the take-profit rule only. A `model_fair` trigger on a live position keeps
    being booked as a paper exit, so its counterfactual continues.
    """
    raw = str(os.environ.get("SYNDICATE_EXIT_LIVE_RULES") or RULE_TAKE_PROFIT)
    return frozenset(part.strip() for part in raw.split(",") if part.strip())


def live_exit_daily_caps() -> tuple[int, float]:
    """`(max live sales per UTC day, max sale notional $ per UTC day)`.

    Defaults 5 sales / $25: held stakes are $0.5-$10, so the dollar cap binds
    after a few of the larger positions and the count cap after five small ones.
    """
    count = int(_float_env("SYNDICATE_EXIT_LIVE_MAX_PER_DAY", 5))
    dollars = _float_env("SYNDICATE_EXIT_LIVE_MAX_DOLLARS_PER_DAY", 25.0)
    return max(0, count), max(0.0, dollars)


def _live_exits_today(state: Mapping[str, Any], day: str) -> tuple[int, float]:
    """Live sales SENT on `day` (UTC): count and notional (contracts x limit).

    Every sent row counts -- submitted, failed or filled -- because a sale whose
    outcome is unknown may have traded, the same reason `spent_today` charges an
    entry that might have filled.
    """
    count, dollars = 0, 0.0
    for row in (state.get("exits") or {}).values():
        if row.get("mode") != EXIT_LIVE or not str(row.get("submitted_at") or "").startswith(day):
            continue
        if row.get("status") in {EXIT_REJECTED, EXIT_DEAD}:
            continue
        count += 1
        dollars += float(row.get("requested_contracts") or 0) * float(row.get("limit_price") or row.get("bid") or 0)
    return count, round(dollars, 4)


def lookback_days() -> int:
    return max(1, int(_float_env("SYNDICATE_EXIT_LOOKBACK_DAYS", _DEFAULT_LOOKBACK_DAYS)))


# --------------------------------------------------------------------------
# Storage -- NO DATE TOKEN, for the reason `execution_ledger._ledger_path` gives
# --------------------------------------------------------------------------


def exits_path() -> Path:
    from syndicate.features.shared.refresh_state_store import reports_root

    return reports_root() / "intelligence" / "execution_exits.json"


def _archive_dir() -> Path:
    from syndicate.features.shared.refresh_state_store import reports_root

    return reports_root() / "intelligence" / "execution_exits_archive"


def _empty_state() -> dict[str, Any]:
    return {"version": 1, "watch": {}, "exits": {}}


def load_state() -> dict[str, Any]:
    from syndicate.features.shared.refresh_state_store import read_json_file_result

    payload, read_ok = read_json_file_result(exits_path())
    if not read_ok:
        # An unreadable document is not an empty one: writing an empty one back
        # would erase every exit and every high-water mark.
        raise RuntimeError("execution_exits_unreadable")
    state = dict(payload or {})
    base = _empty_state()
    for key, value in base.items():
        if not isinstance(state.get(key), type(value)):
            state[key] = value
    return state


def _persist(state: Mapping[str, Any]) -> None:
    from syndicate.features.shared.refresh_state_store import write_json_file

    write_json_file(exits_path(), dict(state))


def _archive(rows: Sequence[Mapping[str, Any]]) -> None:
    """Append pruned watch rows to disk BEFORE the document that omits them."""
    if not rows:
        return
    directory = _archive_dir()
    directory.mkdir(parents=True, exist_ok=True)
    by_month: dict[str, list[str]] = {}
    for row in rows:
        month = str(row.get("selected_date") or "")[:7]
        month = month if re.fullmatch(r"\d{4}-\d{2}", month) else "undated"
        by_month.setdefault(month, []).append(json.dumps(row, sort_keys=True, default=str) + "\n")
    for month, lines in sorted(by_month.items()):
        with open(directory / f"watch_{month}.jsonl", "a", encoding="utf-8") as handle:
            handle.write("".join(lines))
            handle.flush()
            os.fsync(handle.fileno())


def archived_watch_rows() -> list[dict[str, Any]]:
    directory = _archive_dir()
    if not directory.is_dir():
        return []
    latest: dict[str, dict[str, Any]] = {}
    for path in sorted(directory.glob("watch_*.jsonl")):
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict) and row.get("entry_key"):
                    latest[str(row["entry_key"])] = row
    return list(latest.values())


# --------------------------------------------------------------------------
# Identity
# --------------------------------------------------------------------------


def exit_idempotency_key(entry_key: str) -> str:
    """24 chars, `x` + 23 hex. Never all-hex, so `_is_our_key` is False on it."""
    digest = hashlib.sha1(f"exit|v1|{entry_key}".encode("utf-8")).hexdigest()
    return "x" + digest[:23]


def is_exit_key(value: Any) -> bool:
    text = str(value or "").strip()
    return len(text) == 24 and text[0] == "x" and all(c in "0123456789abcdef" for c in text[1:])


# --------------------------------------------------------------------------
# (1) The open-position ledger
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class OpenPosition:
    """One held Kalshi contract position, derived from one filled entry order."""

    entry_key: str
    mode: str
    venue: str
    ticker: str  # Kalshi ticker, or the Polymarket market slug
    leg: str  # "yes" | "no" -- the contract we HOLD
    contracts: float
    entry_price: float  # probability, our leg
    entry_fee_dollars: float
    entry_fee_estimated: bool
    selected_date: str
    commence_time: str | None
    sport: str | None
    market: str | None
    side: str | None
    line: float | None
    player_name: str | None
    model_probability: float | None  # raw model view at entry; None = no view
    family: str = KALSHI  # which venue's book the position trades on

    @property
    def entry_cost_per_contract(self) -> float:
        return self.entry_price + (self.entry_fee_dollars / self.contracts if self.contracts else 0.0)


def _as_float(value: Any) -> float | None:
    if isinstance(value, str):
        value = value.strip().replace("+", "")
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _probability(value: Any) -> float | None:
    from syndicate.features.shared.execution_ledger import _price_as_probability

    return _price_as_probability(value)


# Polymarket legs this module may name: ONLY a leg the side's NAME states, or one
# the venue stated (`held_side`, `POSITION_RESOLUTION_SIDE_LONG/SHORT`). A TEAM
# side is never mapped: the venue's `outcomes` array is unordered (3 of 8 h2h
# legs measured wrong 2026-08-28, `polymarket_us_orders.outcome_side_for_index`),
# and a paper exit read off the other leg's bid would fabricate the counterfactual.
_POLYMARKET_NAMED_LEGS = {"yes": "yes", "over": "yes", "long": "yes", "no": "no", "under": "no", "short": "no"}


def exit_family(order: Mapping[str, Any]) -> str | None:
    """`kalshi` / `polymarket` for an order this module can watch, else None."""
    venue = str(order.get("venue") or "").strip().lower()
    if not str(order.get("venue_ticker") or "").strip():
        return None
    if KALSHI in venue:
        return KALSHI
    if POLYMARKET in venue:
        return POLYMARKET
    return None


def contract_leg(order: Mapping[str, Any]) -> str | None:
    """The contract the entry BOUGHT, through the same mapping that built it."""
    if exit_family(order) == POLYMARKET:
        held = str(order.get("held_side") or "").strip().lower().replace("position_resolution_side_", "")
        named = _POLYMARKET_NAMED_LEGS.get(str(order.get("side") or "").strip().lower())
        return _POLYMARKET_NAMED_LEGS.get(held) or named
    from syndicate.features.shared.kalshi_orders import OrderBuildError, _side_to_kalshi

    try:
        return _side_to_kalshi(order.get("side"), order.get("market"), order.get("line"))
    except OrderBuildError:
        return None


def model_probability_at_entry(order: Mapping[str, Any], price: float) -> float | None:
    """`fair + model_edge_pct/100`, exactly as `sizing_inputs_from_row` derives it.

    RAW, not the fitted blend -- the blend's beta is not on the order. None when
    the order carries no model view; a market-only row has no fair to sell at.
    """
    edge = _as_float(order.get("model_edge_pct"))
    ev = _as_float(order.get("ev_pct"))
    if edge is None or ev is None or not (0.0 < price < 1.0):
        return None
    profit = (1.0 - price) / price
    fair = (ev / 100.0 + 1.0) / (profit + 1.0)
    model = fair + edge / 100.0
    return round(model, 4) if 0.0 < model < 1.0 else None


def _is_kalshi_order(order: Mapping[str, Any]) -> bool:
    return exit_family(order) == KALSHI


def _position_date(order: Mapping[str, Any]) -> str:
    """The date the lookback is measured from: the GAME's, not the slate's.

    Live places FORWARD bets -- the shortlist keeps NFL/NCAAF/soccer games up to
    six days out (todo #707) -- so a fill on Monday's slate for Saturday's game
    has `selected_date` Monday. Keyed on that, it left the watch on Thursday,
    before kickoff, exactly when an exit matters most. The later of the two dates
    keeps it; an unreadable `commence_time` falls back to the slate date.
    """
    slate = str(order.get("selected_date") or "")
    try:
        start = datetime.fromisoformat(str(order.get("commence_time") or "").replace("Z", "+00:00"))
    except ValueError:
        return slate
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    game = start.astimezone(timezone.utc).date().isoformat()
    return max(slate, game)


def open_positions(
    orders: Iterable[Mapping[str, Any]], *, today: str, lookback: int | None = None
) -> tuple[list[OpenPosition], dict[str, int]]:
    """Every filled, ungraded Kalshi or Polymarket entry inside the lookback, as a position.

    LIVE rows are real contracts; PAPER rows (`paper:kalshi`) are the paper
    book's. Both are watched -- the paper book is where a week of counterfactual
    has enough rows to say anything -- and every reading keeps `mode` so the two
    are never pooled by accident. Returns `(positions, skipped_by_reason)`.
    """
    window = lookback if lookback is not None else lookback_days()
    try:
        floor = (date.fromisoformat(today) - timedelta(days=window)).isoformat()
    except ValueError:
        floor = ""
    positions: list[OpenPosition] = []
    skipped: dict[str, int] = {}

    def _skip(reason: str) -> None:
        skipped[reason] = skipped.get(reason, 0) + 1

    for order in orders:
        family = exit_family(order) if isinstance(order, Mapping) else None
        if family is None:
            continue
        if str(order.get("status") or "") != "filled":
            continue
        if order.get("outcome") not in (None, ""):
            continue
        if _position_date(order) < floor:
            _skip("outside_lookback")
            continue
        key = str(order.get("idempotency_key") or "").strip()
        if not key:
            _skip("no_idempotency_key")
            continue
        leg = contract_leg(order)
        if leg is None:
            _skip("polymarket_team_leg_unresolved" if family == POLYMARKET else "unmappable_leg")
            continue
        price = _probability(order.get("fill_price"))
        if price is None:
            price = _probability(order.get("requested_price"))
        stake = _as_float(order.get("fill_stake_dollars"))
        if stake is None:
            stake = _as_float(order.get("requested_stake_dollars"))
        if price is None or not (0.0 < price < 1.0) or not stake or stake <= 0:
            _skip("no_fill_price_or_stake")
            continue
        mode = str(order.get("mode") or "")
        contracts = stake / price
        # A live KALSHI fill is whole contracts; the stake/price division carries
        # the venue's rounding of fill cost, so snap rather than floor. Polymarket
        # quantities are fractional and stay as they are.
        if mode == "live" and family == KALSHI:
            contracts = float(round(contracts))
            if contracts < 1:
                _skip("below_one_contract")
                continue
        fee = _as_float(order.get("fees_dollars"))
        estimated = fee is None
        if fee is None:
            fee = estimate_fee(family, str(order.get("venue_ticker")), contracts, price)
        positions.append(
            OpenPosition(
                entry_key=key,
                mode=mode,
                venue=str(order.get("venue") or ""),
                ticker=str(order.get("venue_ticker")).strip(),
                leg=leg,
                contracts=round(contracts, 4),
                entry_price=round(price, 4),
                entry_fee_dollars=round(fee, 4),
                entry_fee_estimated=estimated,
                selected_date=str(order.get("selected_date") or ""),
                commence_time=order.get("commence_time"),
                sport=order.get("sport"),
                market=order.get("market"),
                side=order.get("side"),
                line=_as_float(order.get("line")),
                player_name=order.get("player_name"),
                model_probability=model_probability_at_entry(order, price),
                family=family,
            )
        )
    return positions, skipped


def estimate_fee(family: str, ticker: str, contracts: float, price: float) -> float:
    """The venue's own fee shape: Kalshi quadratic per series, Polymarket flat on notional."""
    if family == POLYMARKET:
        from syndicate.features.shared.venue_fees import polymarket_fee_dollars

        if not (0.0 < price < 1.0) or contracts <= 0:
            return 0.0
        return round(polymarket_fee_dollars(contracts, price), 4)
    return estimate_kalshi_fee(ticker, contracts, price)


def estimate_kalshi_fee(ticker: str, contracts: float, price: float) -> float:
    """Taker fee for `contracts` at `price`, from the series' own multiplier.

    Unresolved series are charged the full rate (`taker_fee_per_contract`'s
    rule: understating a fee invents edge).
    """
    from syndicate.features.shared.venue_fees import taker_fee_per_contract

    if not (0.0 < price < 1.0) or contracts <= 0:
        return 0.0
    per_contract, _basis, _bound = taker_fee_per_contract("kalshi", price, venue_ref=ticker)
    return round(per_contract * contracts, 4)


# --------------------------------------------------------------------------
# Venue reads
# --------------------------------------------------------------------------


def fetch_quotes(tickers: Sequence[str]) -> dict[str, Any]:
    """Current markets for `tickers`, batched through `GET /markets?tickers=`.

    MEASURED 2026-10-19 from a dev box: `?tickers=A,B,C` returned exactly those
    three markets. Public, unauthenticated, no order capability. Returns
    `{"markets": {ticker: normalized}, "errors": [...], "requested": n}`; a
    ticker absent from `markets` is UNQUOTED, never zero.
    """
    from syndicate.features.shared.kalshi_client import _BASE_URLS, _MARKETS_PATH, _get, normalize_market

    unique = sorted({str(t).strip() for t in tickers if str(t or "").strip()})
    markets: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for start in range(0, len(unique), _QUOTE_CHUNK):
        chunk = unique[start : start + _QUOTE_CHUNK]
        query = urllib.parse.urlencode({"tickers": ",".join(chunk), "limit": len(chunk)})
        last_error = ""
        for base in _BASE_URLS:
            try:
                payload = _get(f"{base}{_MARKETS_PATH}?{query}")
            except Exception as exc:  # noqa: BLE001 -- next base, then a named error
                last_error = f"{type(exc).__name__}: {exc}"[:200]
                continue
            for raw in payload.get("markets") or []:
                if isinstance(raw, Mapping) and raw.get("ticker") in chunk:
                    markets[str(raw["ticker"])] = normalize_market(raw)
            last_error = ""
            break
        if last_error:
            errors.append(last_error)
    return {"markets": markets, "errors": errors, "requested": len(unique)}


def _book_price(level: Any) -> tuple[float, float] | None:
    try:
        px = level["px"]
        return float(px["value"] if isinstance(px, Mapping) else px), float(level["qty"])
    except (KeyError, TypeError, ValueError):
        return None


def normalize_polymarket_book(slug: str, book: Mapping[str, Any]) -> dict[str, Any]:
    """A Polymarket US book in the shape `evaluate_exit` reads off a Kalshi market.

    MEASURED 2026-10-19 on the fleet: `{bids, offers, state, marketSlug, stats,
    transactTime}`, levels `{px: {value: "0.5700"}, qty: "2983.63"}`, state
    `MARKET_STATE_OPEN` / `MARKET_STATE_EXPIRED`. The book is YES-quoted ("price
    is always the YES price"), so a YES holding sells into the best bid and a NO
    holding at `1 - best offer`.
    """
    bids, offers = book.get("bids") or [], book.get("offers") or []
    bid = _book_price(bids[0]) if bids else None
    offer = _book_price(offers[0]) if offers else None
    state = str(book.get("state") or "")
    if state == "MARKET_STATE_OPEN":
        status = "active"
    else:
        status = state.replace("MARKET_STATE_", "").lower() or "status_unread"
    return {
        "ticker": slug,
        "status": status,
        "yes_bid_dollars": bid[0] if bid else None,
        "no_bid_dollars": round(1.0 - offer[0], 6) if offer else None,
        "yes_bid_size_fp": bid[1] if bid else None,
        "yes_ask_size_fp": offer[1] if offer else None,
        "venue_state": state or None,
    }


def fetch_polymarket_quotes(slugs: Sequence[str]) -> dict[str, Any]:
    """One SIGNED book read per slug, through the order module's own reader.

    Same return shape as `fetch_quotes`. Bounded by `_MAX_POLYMARKET_BOOKS_PER_TICK`;
    the rest are reported `unread_over_cap`, never as quoted.
    """
    from syndicate.features.shared.polymarket_us_orders import _read_book

    unique = sorted({str(s).strip() for s in slugs if str(s or "").strip()})
    markets: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for slug in unique[:_MAX_POLYMARKET_BOOKS_PER_TICK]:
        try:
            data = _read_book(slug)
        except Exception as exc:  # noqa: BLE001 -- one unreadable book is one unquoted slug
            errors.append(f"{slug}: {type(exc).__name__}")
            continue
        book = data.get("marketData", data) if isinstance(data, Mapping) else {}
        if isinstance(book, Mapping):
            markets[slug] = normalize_polymarket_book(slug, book)
    return {
        "markets": markets,
        "errors": errors,
        "requested": len(unique),
        "unread_over_cap": max(0, len(unique) - _MAX_POLYMARKET_BOOKS_PER_TICK),
    }


def _positions_url(cursor: str = "") -> str:
    from syndicate.features.shared.kalshi_orders import _read_base

    path = (os.environ.get("KALSHI_POSITIONS_PATH") or "/portfolio/positions").strip()
    path = path if path.startswith("/") else f"/{path}"
    url = f"{_read_base().rstrip('/')}{path}?limit=1000&count_filter=position"
    if cursor:
        url += f"&cursor={urllib.parse.quote(cursor, safe='')}"
    return url


def _signed_position(row: Mapping[str, Any]) -> float | None:
    """Kalshi's net position: positive = YES contracts held, negative = NO."""
    for field in ("position_fp", "position"):
        value = _as_float(row.get(field))
        if value is not None:
            return value
    return None


def fetch_venue_positions(*, max_pages: int = 10) -> dict[str, Any]:
    """What Kalshi says this account HOLDS, per ticker. Read-only, signed.

        GET /trade-api/v2/portfolio/positions

    `{"status": "ok", "positions": {ticker: signed contracts}}` or a NAMED
    failure. A failed read is never "holds nothing" -- live exits refuse on it.
    """
    from syndicate.features.shared.kalshi_auth import signed_request

    held: dict[str, float] = {}
    unread_shape = 0
    cursor = ""
    for _ in range(max_pages):
        try:
            payload = signed_request("GET", _positions_url(cursor))
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "reason": f"{type(exc).__name__}: {exc}"[:300]}
        rows = payload.get("market_positions")
        if not isinstance(rows, list):
            return {"status": "error", "reason": f"unexpected_shape:{sorted(payload)[:6]}"}
        for row in rows:
            if not isinstance(row, Mapping) or not row.get("ticker"):
                continue
            signed = _signed_position(row)
            if signed is None:
                unread_shape += 1
                continue
            if signed:
                held[str(row["ticker"])] = signed
        cursor = str(payload.get("cursor") or "")
        if not cursor:
            return {"status": "ok", "positions": held, "unreadable_rows": unread_shape}
    return {"status": "error", "reason": "page_limit", "positions": held}


def reconcile_positions(
    positions: Sequence[OpenPosition], venue: Mapping[str, Any] | None
) -> dict[str, Any]:
    """LIVE ledger positions against the venue's book, per ticker.

    Ledger net is YES contracts minus NO contracts, which is how Kalshi nets a
    ticker. `sellable[entry_key]` is what a live exit may sell: the ledger's
    contracts, capped by what the venue says is held on that leg. Paper rows are
    not compared -- the venue never held them.
    """
    live = [p for p in positions if p.mode == "live" and p.family == KALSHI]
    report: dict[str, Any] = {"live_positions": len(live), "status": "skipped", "mismatches": [], "sellable": {}}
    if not live:
        report["status"] = "no_live_positions"
        return report
    if not venue or venue.get("status") != "ok":
        report["status"] = "venue_unread"
        report["reason"] = (venue or {}).get("reason")
        return report
    held = venue.get("positions") or {}
    ledger_net: dict[str, float] = {}
    for p in live:
        ledger_net[p.ticker] = ledger_net.get(p.ticker, 0.0) + (p.contracts if p.leg == "yes" else -p.contracts)
    for ticker, net in sorted(ledger_net.items()):
        at_venue = float(held.get(ticker, 0.0))
        if abs(at_venue - net) > 1e-6:
            report["mismatches"].append({"ticker": ticker, "ledger": net, "venue": at_venue})
    # Allocate the venue's holding across our entries on that ticker in order.
    remaining = {t: float(held.get(t, 0.0)) for t in ledger_net}
    for p in live:
        on_leg = remaining.get(p.ticker, 0.0)
        available = on_leg if p.leg == "yes" else -on_leg
        size = max(0.0, min(p.contracts, available))
        report["sellable"][p.entry_key] = size
        remaining[p.ticker] = on_leg - (size if p.leg == "yes" else -size)
    report["status"] = "ok" if not report["mismatches"] else "mismatch"
    return report


# --------------------------------------------------------------------------
# (3) The take-profit rule
# --------------------------------------------------------------------------


def leg_bid(market: Mapping[str, Any], leg: str) -> float | None:
    """The best bid for the contract we hold -- the price a sale gets."""
    raw = market.get("yes_bid_dollars" if leg == "yes" else "no_bid_dollars")
    price = _as_float(raw)
    return price if price is not None and 0.0 < price < 1.0 else None


def _is_in_play(commence_time: Any, now: datetime) -> bool | None:
    try:
        start = datetime.fromisoformat(str(commence_time).replace("Z", "+00:00"))
    except ValueError:
        return None
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    return now >= start


def evaluate_exit(
    position: OpenPosition,
    market: Mapping[str, Any] | None,
    *,
    margin: float,
    fair_buffer: float,
    now: datetime,
) -> dict[str, Any]:
    """Would we sell this position now, and at what? PURE.

    Both rules compare NET figures. `net_per_contract` is the bid less the exit
    fee; `entry_cost_per_contract` is the fill plus the entry fee. So
    `take_profit` fires when the round trip clears `margin` dollars per contract
    after BOTH fees, and `model_fair` when the net bid is at least the model's
    own probability -- the price we bought because we thought it was too low has
    reached what we thought it was worth.
    """
    base: dict[str, Any] = {
        "entry_key": position.entry_key,
        "ticker": position.ticker,
        "leg": position.leg,
        "mode": position.mode,
        "in_play": _is_in_play(position.commence_time, now),
        "rule": None,
    }
    if market is None:
        return {**base, "reason": "unquoted"}
    status = str(market.get("status") or "").strip().lower()
    if status not in {"active", "open"}:
        return {**base, "reason": f"market_{status or 'status_unread'}"}
    bid = leg_bid(market, position.leg)
    if bid is None:
        return {**base, "reason": "no_bid"}
    exit_fee = estimate_fee(position.family, position.ticker, position.contracts, bid)
    net = bid - (exit_fee / position.contracts if position.contracts else 0.0)
    cost = position.entry_cost_per_contract
    rules = []
    if net - cost >= margin - 1e-9:
        rules.append(RULE_TAKE_PROFIT)
    fair = position.model_probability
    if fair is not None and net >= fair + fair_buffer - 1e-9:
        rules.append(RULE_MODEL_FAIR)
    return {
        **base,
        "reason": "triggered" if rules else "below_threshold",
        "rule": "+".join(rules) or None,
        "bid": bid,
        # Size at the touch we would hit. A NO bid IS the YES ask, so its depth
        # is the YES ask size.
        "bid_size": _as_float(market.get("yes_bid_size_fp" if position.leg == "yes" else "yes_ask_size_fp")),
        "exit_fee_dollars": round(exit_fee, 4),
        "net_per_contract": round(net, 4),
        "entry_cost_per_contract": round(cost, 4),
        "edge_per_contract": round(net - cost, 4),
        "fair": fair,
        "fair_source": "entry_model_raw" if fair is not None else None,
        "margin": margin,
    }


def round_trip_pnl(position: Mapping[str, Any] | OpenPosition, bid: float, exit_fee: float) -> float:
    p = asdict(position) if isinstance(position, OpenPosition) else position
    contracts = float(p["contracts"])
    return round(contracts * (bid - float(p["entry_price"])) - float(p["entry_fee_dollars"]) - exit_fee, 4)


# --------------------------------------------------------------------------
# (2) The sell-to-close order: build, write-ahead, send, complete, reconcile
# --------------------------------------------------------------------------


def exit_order_body(position: OpenPosition, *, bid: float, count: int) -> dict[str, Any]:
    """The v2 SELL body. PURE.

    `POST /portfolio/events/orders` is quoted entirely from the YES leg
    (`kalshi_orders.order_body_v2`): an entry on YES was a `bid`, an entry on NO
    an `ask` at the complement. Closing reverses that -- a YES holding is sold
    as an `ask` at the YES bid, a NO holding as a `bid` at `1 - no_bid`, which
    is the same trade quoted from the other leg.

    `reduce_only` is what makes it a CLOSE: the venue may only shrink the
    position, so a mis-sized or repeated sale cannot open the opposite one.
    `immediate_or_cancel` so a sale never rests at a stale bid; both values are
    env-overridable because neither has been accepted by this endpoint yet.
    """
    if count < 1:
        raise ExitBuildError(f"exit_below_one_contract: {count}")
    if not (0.0 < bid < 1.0):
        raise ExitBuildError(f"exit_price_out_of_range: {bid}")
    from syndicate.features.shared.kalshi_orders import _SUBACCOUNT_OMITTED, _v2_exchange_index, _v2_subaccount

    if position.leg == "yes":
        book_side, quote = "ask", bid
    elif position.leg == "no":
        book_side, quote = "bid", round(1.0 - bid, 4)
    else:
        raise ExitBuildError(f"exit_unknown_leg: {position.leg!r}")
    body: dict[str, Any] = {
        "ticker": position.ticker,
        "client_order_id": exit_idempotency_key(position.entry_key),
        "side": book_side,
        "count": f"{int(count):.2f}",
        "price": f"{quote:.4f}",
        "time_in_force": (os.environ.get("KALSHI_EXIT_TIME_IN_FORCE") or "immediate_or_cancel").strip(),
        "self_trade_prevention_type": "taker_at_cross",
        "post_only": False,
        "cancel_order_on_pause": True,
        "reduce_only": True,
        "exchange_index": _v2_exchange_index(),
    }
    subaccount = _v2_subaccount()
    if subaccount is not _SUBACCOUNT_OMITTED:
        body["subaccount"] = subaccount
    return body


def send_exit_order(body: Mapping[str, Any]) -> dict[str, Any]:
    """Send one sell. Raises on failure (the row stays `failed` for reconcile)."""
    from syndicate.features.shared.kalshi_auth import signed_request
    from syndicate.features.shared.kalshi_orders import _orders_url, _unwrap_order, venue_order_view

    url = _orders_url()
    print(
        f"[execution_exits] EXIT_SUBMIT url={url} ticker={body.get('ticker')} side={body.get('side')}"
        f" count={body.get('count')} price={body.get('price')} tif={body.get('time_in_force')}"
        f" reduce_only={body.get('reduce_only')} client_order_id={body.get('client_order_id')}",
        flush=True,
    )
    response = signed_request("POST", url, body=dict(body))
    order = _unwrap_order(response) or {}
    return _exit_view(order)


def _exit_view(order: Mapping[str, Any]) -> dict[str, Any]:
    """`venue_order_view` plus the `outcome_side` the fill cost is quoted on."""
    from syndicate.features.shared.kalshi_orders import venue_order_view

    view = venue_order_view(order)
    view["outcome_side"] = order.get("outcome_side")
    return view


def _exit_row_from_view(row: dict[str, Any], view: Mapping[str, Any], position: Mapping[str, Any]) -> None:
    """Close a write-ahead exit row with what the VENUE says happened."""
    state = str(view.get("state") or "unknown")
    filled = view.get("filled_count") or 0
    row["venue_order_id"] = view.get("order_id") or row.get("venue_order_id")
    row["venue_status"] = view.get("venue_status")
    row["venue_resolved_at"] = _utc_now()
    if state == "filled" and filled:
        # THE PRICE WE RECEIVED, ON OUR LEG. Kalshi reports the fill cost on the
        # order's `outcome_side`, which is never the leg we sold:
        #   NO held  -> close books as `buy yes`  (outcome_side=yes): NO price = 1 - cost
        #   YES held -> close books as `sell yes` (outcome_side=no):  YES price = 1 - cost
        # MEASURED 2026-10-21: DEL4 (YES x11) recorded the NO-side 0.35 as our
        # fill, so settlement understated the entry by 11 x 0.30. The conversion
        # used to look only at our leg and was right for NO closes by accident.
        # An unknown outcome_side leaves the fill UNPRICED (reconciled later),
        # never guessed.
        cost = _as_float(view.get("fill_cost_dollars"))
        traded = cost / filled if cost is not None and filled else None
        reported = str(view.get("outcome_side") or "").strip().lower()
        leg = str(position.get("leg") or "").strip().lower()
        if traded is not None:
            if reported in {"yes", "no"} and leg in {"yes", "no"}:
                traded = round(traded if reported == leg else 1.0 - traded, 4)
            else:
                traded = None
        row["status"] = EXIT_FILLED
        row["filled_contracts"] = filled
        row["fill_price"] = traded
        row["exit_fee_dollars"] = _as_float(view.get("fees_dollars"))
    elif state == "dead":
        row["status"] = EXIT_DEAD
        row["filled_contracts"] = 0
    else:
        row["status"] = EXIT_SUBMITTED


def place_exit(
    state: dict[str, Any],
    position: OpenPosition,
    decision: Mapping[str, Any],
    *,
    sellable: float | None,
    send: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None,
    persist: Callable[[Mapping[str, Any]], None] | None = None,
    read_back: Callable[[str], Mapping[str, Any]] | None = None,
    max_contracts: int | None = None,
    limit_price: float | None = None,
    purpose: str | None = None,
) -> dict[str, Any]:
    """The live seam. Every refusal returns `{"refused": token}` and writes nothing.

    `max_contracts` caps the sale below the holding (a one-contract verification
    sale); `limit_price` is our leg's sell limit when it should sit below the
    quoted bid (marketable through a one-tick move). Both default to selling the
    whole sellable holding at the bid.

    Order is the safety argument, as in `place_order`: switches and size are
    checked and the body BUILT first (a refusal leaves no row), then the row is
    persisted `submitted`, THEN sent, then completed.
    """
    from syndicate.features.shared.execution_guard import kill_switch_engaged

    exits = state.setdefault("exits", {})
    key = exit_idempotency_key(position.entry_key)
    existing = exits.get(key)
    if existing is not None and existing.get("mode") == EXIT_PAPER:
        # The paper decision on this entry is kept on the live row (below); it
        # must not read as a duplicate of a sale that never happened.
        existing = None
    if existing is not None and existing.get("status") not in {EXIT_REJECTED, EXIT_DEAD}:
        return {"refused": "duplicate", "row": existing}
    if exit_mode() != EXIT_LIVE:
        return {"refused": "exit_mode_not_live"}
    if position.mode != "live":
        return {"refused": "paper_position"}
    if position.family != KALSHI:
        # Only Kalshi's sell body exists. A Polymarket close is a different
        # contract (`ORDER_ACTION_SELL` on the held `outcomeSide`) and is not built.
        return {"refused": "venue_live_exit_unbuilt"}
    if not exit_live_armed():
        return {"refused": "exit_not_armed"}
    switch = kill_switch_engaged()
    if switch.get("engaged"):
        return {"refused": f"kill_switch:{switch.get('source')}"}
    if unreconciled_exits(state):
        return {"refused": "unreconciled_exits"}
    cap = position.contracts if max_contracts is None else min(position.contracts, float(max_contracts))
    count = int(math.floor(min(cap, sellable or 0.0)))
    try:
        price = float(decision["bid"]) if limit_price is None else float(limit_price)
        body = exit_order_body(position, bid=price, count=count)
    except (ExitBuildError, KeyError, TypeError, ValueError) as exc:
        return {"refused": str(exc).split(":", 1)[0] or type(exc).__name__}

    row = {
        **_exit_row_base(position, decision),
        "exit_key": key,
        "mode": EXIT_LIVE,
        "status": EXIT_SUBMITTED,
        "requested_contracts": count,
        "limit_price": price,
        "purpose": purpose,
        "submitted_at": _utc_now(),
        "venue_order_id": None,
        "error": None,
    }
    paper = exits.get(key)
    if paper is not None and paper.get("mode") == EXIT_PAPER:
        row["paper_decision"] = {
            k: paper.get(k) for k in ("decided_at", "rule", "bid", "edge_per_contract", "realized_pnl_dollars", "in_play")
        }
    if existing is not None:
        row["prior_attempts"] = (existing.get("prior_attempts") or []) + [
            {k: existing.get(k) for k in ("status", "submitted_at", "venue_order_id", "error")}
        ]
    exits[key] = row
    (persist or _persist)(state)  # WRITE-AHEAD: on disk before the send

    try:
        view = (send or send_exit_order)(body)
    except Exception as exc:  # noqa: BLE001 -- may have reached the venue
        contacted = bool(getattr(exc, "venue_contacted", True))
        row["status"] = EXIT_FAILED if contacted else EXIT_REJECTED
        row["error"] = f"{type(exc).__name__}: {exc}"[:400]
        (persist or _persist)(state)
        return {"placed": False, "row": row}
    _exit_row_from_view(row, view, asdict(position))
    if row.get("status") == EXIT_FILLED and row.get("fill_price") is None and row.get("venue_order_id"):
        # THE CREATE RESPONSE DOES NOT PRICE THE FILL. Measured on the first real
        # sale (2026-10-19 22:42:59Z): the POST answered `filled_count=1` with no
        # fill cost, fee or status; the same order read back 34 s later carried
        # `taker_fill_cost_dollars` and `taker_fees_dollars`. Read it back now --
        # an unpriced fill is unreconciled, and settlement refuses to grade it.
        from syndicate.features.shared.kalshi_orders import fetch_order, venue_order_view

        try:
            got = (read_back or fetch_order)(str(row["venue_order_id"]))
            if got.get("status") == "ok":
                _exit_row_from_view(row, _exit_view(got.get("order") or {}), asdict(position))
        except Exception as exc:  # noqa: BLE001 -- reconcile_exit_orders retries it
            row["read_back_error"] = f"{type(exc).__name__}: {exc}"[:200]
    (persist or _persist)(state)
    return {"placed": True, "row": row}


def unreconciled_exits(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Live exits whose venue outcome is not fully known: in flight, failed, or
    filled with no price (a fill settlement cannot grade)."""
    return [
        row
        for row in (state.get("exits") or {}).values()
        if row.get("mode") == EXIT_LIVE
        and (
            row.get("status") in {EXIT_SUBMITTED, EXIT_FAILED}
            or (row.get("status") == EXIT_FILLED and row.get("fill_price") is None)
        )
    ]


def reconcile_exit_orders(
    state: dict[str, Any],
    *,
    fetch_one: Callable[[str], Mapping[str, Any]] | None = None,
    fetch_book: Callable[[], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Ask the venue about every live exit in `submitted`/`failed`.

    With an order id, read that order. Without one (a lost response), look for
    our `client_order_id` on the venue's own book -- the exit key -- and an
    exit the book does not show stays `failed`: absence from one read is not
    proof it never landed.
    """
    from syndicate.features.shared.kalshi_orders import fetch_order, fetch_orders, venue_order_view

    pending = unreconciled_exits(state)
    if not pending:
        return {"checked": 0, "changed": 0}
    changed = 0
    book: dict[str, Mapping[str, Any]] | None = None
    for row in pending:
        order: Mapping[str, Any] | None = None
        if row.get("venue_order_id"):
            result = (fetch_one or fetch_order)(str(row["venue_order_id"]))
            if result.get("status") == "ok":
                order = result.get("order") or {}
        else:
            if book is None:
                listing = (fetch_book or (lambda: fetch_orders(limit=100)))()
                book = {
                    str(o.get("client_order_id")): o
                    for o in (listing.get("orders") or [])
                    if isinstance(o, Mapping) and is_exit_key(o.get("client_order_id"))
                }
            order = book.get(str(row.get("exit_key")))
        if order is None:
            continue
        before = row.get("status")
        _exit_row_from_view(row, _exit_view(order), row)
        changed += int(row.get("status") != before)
    return {"checked": len(pending), "changed": changed}


# --------------------------------------------------------------------------
# The tick
# --------------------------------------------------------------------------


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _exit_row_base(position: OpenPosition, decision: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "entry_key": position.entry_key,
        "entry_mode": position.mode,
        "venue": position.venue,
        "family": position.family,
        "ticker": position.ticker,
        "leg": position.leg,
        "sport": position.sport,
        "market": position.market,
        "side": position.side,
        "line": position.line,
        "player_name": position.player_name,
        "selected_date": position.selected_date,
        "commence_time": position.commence_time,
        "contracts": position.contracts,
        "entry_price": position.entry_price,
        "entry_fee_dollars": position.entry_fee_dollars,
        "rule": decision.get("rule"),
        "decided_at": _utc_now(),
        "in_play": decision.get("in_play"),
        "bid": decision.get("bid"),
        "exit_fee_dollars": decision.get("exit_fee_dollars"),
        "net_per_contract": decision.get("net_per_contract"),
        "edge_per_contract": decision.get("edge_per_contract"),
        "fair": decision.get("fair"),
        "fair_source": decision.get("fair_source"),
        "margin": decision.get("margin"),
    }


def net_of_live_sales(
    positions: Sequence[OpenPosition], state: Mapping[str, Any]
) -> tuple[list[OpenPosition], int]:
    """Positions reduced by any FILLED live exit on them. Returns `(held, fully_sold)`.

    The entry row still says what was BOUGHT; after a sale the venue holds less,
    and comparing the entry against the venue would read as a mismatch on every
    tick. The entry fee is apportioned to what is still held.
    """
    exits = state.get("exits") or {}
    held: list[OpenPosition] = []
    fully_sold = 0
    for p in positions:
        row = exits.get(exit_idempotency_key(p.entry_key))
        sold = _as_float((row or {}).get("filled_contracts")) if row else None
        if not row or row.get("mode") != EXIT_LIVE or row.get("status") != EXIT_FILLED or not sold:
            held.append(p)
            continue
        remaining = round(p.contracts - sold, 4)
        if remaining <= 0:
            fully_sold += 1
            continue
        held.append(replace(p, contracts=remaining, entry_fee_dollars=round(p.entry_fee_dollars * remaining / p.contracts, 4)))
    return held, fully_sold


def _update_watch(watch: dict[str, Any], position: OpenPosition, decision: Mapping[str, Any], now: str) -> None:
    row = watch.get(position.entry_key)
    if row is None:
        row = {
            **{k: v for k, v in asdict(position).items() if k != "entry_key"},
            "entry_key": position.entry_key,
            "first_seen": now,
            "samples": 0,
            "hwm_edge": None,
        }
        watch[position.entry_key] = row
    row["last_seen"] = now
    row["last_reason"] = decision.get("reason")
    edge = decision.get("edge_per_contract")
    if edge is None:
        return
    row["samples"] = int(row.get("samples") or 0) + 1
    row["last_bid"] = decision.get("bid")
    row["last_edge"] = edge
    if row.get("hwm_edge") is None or edge > float(row["hwm_edge"]):
        row["hwm_edge"] = edge
        row["hwm_bid"] = decision.get("bid")
        row["hwm_at"] = now
        row["hwm_in_play"] = decision.get("in_play")
    if position.model_probability is not None:
        reached = decision.get("net_per_contract", 0) >= position.model_probability
        if reached and not row.get("fair_reached_at"):
            row["fair_reached_at"] = now


def _prune_watch(state: dict[str, Any], today: str) -> int:
    try:
        floor = (date.fromisoformat(today) - timedelta(days=_WATCH_RETENTION_DAYS)).isoformat()
    except ValueError:
        return 0
    watch = state.get("watch") or {}
    stale = [k for k, row in watch.items() if _position_date(row) < floor]
    if not stale:
        return 0
    _archive([watch[k] for k in stale])  # moved, never dropped
    for k in stale:
        watch.pop(k, None)
    return len(stale)


def run_exit_tick(
    *,
    today: str,
    orders: Sequence[Mapping[str, Any]] | None = None,
    quotes: Callable[[Sequence[str]], Mapping[str, Any]] | None = None,
    polymarket_quotes: Callable[[Sequence[str]], Mapping[str, Any]] | None = None,
    venue_positions: Callable[[], Mapping[str, Any]] | None = None,
    now: datetime | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    """One pass: positions -> venue reconcile -> quotes -> rules -> exits.

    Never raises past a named status; the caller is the order-placing tick.
    """
    mode = exit_mode()
    if mode == EXIT_OFF:
        return {"status": "off"}
    stamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    now_text = stamp.strftime("%Y-%m-%dT%H:%M:%SZ")

    if orders is None:
        from syndicate.features.shared.execution_ledger import _load

        orders = list(_load().get("orders") or [])
    state = load_state()

    positions, skipped = open_positions(orders, today=today)
    positions, fully_sold = net_of_live_sales(positions, state)
    if fully_sold:
        skipped["sold_live"] = fully_sold
    if len(positions) > _MAX_TICKERS_PER_TICK:
        # Newest first: the slate about to start beats one already settled.
        skipped["over_tick_cap"] = len(positions) - _MAX_TICKERS_PER_TICK
        positions = sorted(positions, key=lambda p: p.selected_date, reverse=True)[:_MAX_TICKERS_PER_TICK]

    venue_report: dict[str, Any] = {"status": "no_live_positions"}
    if any(p.mode == "live" and p.family == KALSHI for p in positions):
        venue = (venue_positions or fetch_venue_positions)()
        venue_report = reconcile_positions(positions, venue)
        if mode == EXIT_LIVE:
            try:
                venue_report["exit_reconcile"] = reconcile_exit_orders(state)
            except Exception as exc:  # noqa: BLE001
                venue_report["exit_reconcile"] = {"error": f"{type(exc).__name__}: {exc}"[:200]}

    kalshi_tickers = [p.ticker for p in positions if p.family == KALSHI]
    polymarket_slugs = [p.ticker for p in positions if p.family == POLYMARKET]
    quoted = (quotes or fetch_quotes)(kalshi_tickers) if kalshi_tickers else {"markets": {}, "errors": []}
    pm_quoted = (
        (polymarket_quotes or fetch_polymarket_quotes)(polymarket_slugs)
        if polymarket_slugs
        else {"markets": {}, "errors": []}
    )
    # Keyed by venue as well as id: a wrong-venue bid is the one error to rule out.
    markets = {(KALSHI, k): v for k, v in (quoted.get("markets") or {}).items()}
    markets.update({(POLYMARKET, k): v for k, v in (pm_quoted.get("markets") or {}).items()})

    margin, buffer = take_profit_margin(), fair_margin()
    watch = state["watch"]
    exits = state["exits"]
    reasons: dict[str, int] = {}
    new_paper = 0
    live_results: dict[str, int] = {}
    for position in positions:
        decision = evaluate_exit(
            position, markets.get((position.family, position.ticker)), margin=margin, fair_buffer=buffer, now=stamp
        )
        reasons[decision["reason"]] = reasons.get(decision["reason"], 0) + 1
        _update_watch(watch, position, decision, now_text)
        if not decision.get("rule"):
            continue
        key = exit_idempotency_key(position.entry_key)
        live_skip = None
        if position.mode == "live" and mode == EXIT_LIVE:
            rules = set(str(decision.get("rule") or "").split("+"))
            prior = exits.get(key) or {}
            sold_live = prior.get("mode") == EXIT_LIVE and prior.get("status") not in {EXIT_DEAD, EXIT_REJECTED}
            # An unfilled (dead) IOC may be re-sent, but only by an ARMED rule and
            # only `_MAX_DEAD_RETRIES` times per entry. MEASURED 2026-10-21: the old
            # `sold_live` short-circuit skipped the rule check for any entry with a
            # live row, so model_fair alone re-sent 5x, 9x, and filled once.
            unfilled_tries = (1 + len(prior.get("prior_attempts") or [])) if prior.get("status") == EXIT_DEAD else 0
            cap_count, cap_dollars = live_exit_daily_caps()
            used_count, used_dollars = _live_exits_today(state, _utc_now()[:10])  # same clock as submitted_at
            notional = float(position.contracts) * float(decision.get("bid") or 0.0)
            if sold_live:
                live_skip = None  # place_exit answers `duplicate`
            elif not rules & live_exit_rules():
                live_skip = "rule_not_armed"
            elif unfilled_tries >= _MAX_DEAD_RETRIES:
                live_skip = "unfilled_retry_limit"
            elif used_count >= cap_count:
                live_skip = "daily_count_cap"
            elif used_dollars + notional > cap_dollars + 1e-9:
                live_skip = "daily_dollar_cap"
        if position.mode == "live" and mode == EXIT_LIVE and live_skip is None:
            outcome = place_exit(
                state,
                position,
                decision,
                sellable=(venue_report.get("sellable") or {}).get(position.entry_key),
                persist=_persist if persist else (lambda _s: None),
            )
            token = "placed" if outcome.get("placed") else str(outcome.get("refused") or "failed")
            live_results[token] = live_results.get(token, 0) + 1
            if outcome.get("placed"):
                row = outcome.get("row") or {}
                print(
                    f"[execution_exits] EXIT_LIVE entry={position.entry_key} ticker={position.ticker} leg={position.leg}"
                    f" rule={decision.get('rule')} status={row.get('status')} contracts={row.get('requested_contracts')}"
                    f" filled={row.get('filled_contracts')} fill_price={row.get('fill_price')}"
                    f" fee={row.get('exit_fee_dollars')} order={row.get('venue_order_id')}",
                    flush=True,
                )
            continue
        if live_skip is not None:
            live_results[live_skip] = live_results.get(live_skip, 0) + 1
        if key in exits:
            continue  # one exit per entry: the first trigger is the paper sale
        exits[key] = {
            **_exit_row_base(position, decision),
            "exit_key": key,
            "mode": EXIT_PAPER,
            "status": EXIT_PAPER_FILLED,
            "realized_pnl_dollars": round_trip_pnl(position, float(decision["bid"]), float(decision["exit_fee_dollars"])),
        }
        new_paper += 1
        print(
            f"[execution_exits] EXIT_PAPER entry={position.entry_key} venue={position.family} mode={position.mode}"
            f" ticker={position.ticker} leg={position.leg} rule={decision.get('rule')}"
            f" contracts={position.contracts} entry={position.entry_price} bid={decision.get('bid')}"
            f" edge={decision.get('edge_per_contract')} fair={decision.get('fair')}"
            f" in_play={decision.get('in_play')} pnl={exits[key]['realized_pnl_dollars']}",
            flush=True,
        )

    pruned = _prune_watch(state, today)
    summary = {
        "status": "ok",
        "mode": mode,
        "at": now_text,
        "positions": len(positions),
        "live_positions": sum(1 for p in positions if p.mode == "live"),
        "by_venue": {fam: sum(1 for p in positions if p.family == fam) for fam in (KALSHI, POLYMARKET)},
        "skipped": skipped,
        "quoted": len(markets),
        "quote_errors": len(quoted.get("errors") or []) + len(pm_quoted.get("errors") or []),
        "polymarket_quoted": len(pm_quoted.get("markets") or {}),
        "polymarket_unread_over_cap": pm_quoted.get("unread_over_cap", 0),
        "reasons": dict(sorted(reasons.items())),
        "new_paper_exits": new_paper,
        "live_exits": live_results,
        "venue_reconcile": {k: v for k, v in venue_report.items() if k != "sellable"},
        "margin": margin,
        "fair_buffer": buffer,
        "watching": len(watch),
        "pruned": pruned,
    }
    state["last_tick"] = summary
    state["updated_at"] = now_text
    if persist:
        _persist(state)
    return summary


def exit_tick_line(summary: Mapping[str, Any]) -> str:
    vr = summary.get("venue_reconcile") or {}
    return (
        f"[live_odds_worker] EXIT_TICK status={summary.get('status')} mode={summary.get('mode')}"
        f" positions={summary.get('positions')} live={summary.get('live_positions')}"
        f" by_venue={summary.get('by_venue')} pm_quoted={summary.get('polymarket_quoted')}"
        f" quoted={summary.get('quoted')} quote_errors={summary.get('quote_errors')}"
        f" reasons={summary.get('reasons')} new_paper_exits={summary.get('new_paper_exits')}"
        f" live_exits={summary.get('live_exits')} venue={vr.get('status')}"
        f" mismatches={len(vr.get('mismatches') or [])} margin={summary.get('margin')}"
        f" watching={summary.get('watching')} skipped={summary.get('skipped')}"
    )


# --------------------------------------------------------------------------
# The counterfactual readout: exit vs hold-to-settle
# --------------------------------------------------------------------------

_SETTLE_VALUE = {"won": 1.0, "lost": 0.0}


def _hold_pnl(row: Mapping[str, Any], outcome: str) -> float:
    value = _SETTLE_VALUE[outcome]
    return float(row["contracts"]) * (value - float(row["entry_price"])) - float(row["entry_fee_dollars"])


def _bucket() -> dict[str, Any]:
    return {"n": 0, "exit_pnl": 0.0, "hold_pnl": 0.0, "delta": 0.0, "exit_better": 0, "hold_better": 0}


def _add(bucket: dict[str, Any], exit_pnl: float, hold_pnl: float) -> None:
    bucket["n"] += 1
    bucket["exit_pnl"] += exit_pnl
    bucket["hold_pnl"] += hold_pnl
    bucket["delta"] += exit_pnl - hold_pnl
    bucket["exit_better"] += int(exit_pnl > hold_pnl)
    bucket["hold_better"] += int(hold_pnl > exit_pnl)


def _rounded(buckets: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        k: {kk: (round(vv, 2) if isinstance(vv, float) else vv) for kk, vv in v.items()}
        for k, v in sorted(buckets.items())
    }


def exit_counterfactual(
    state: Mapping[str, Any],
    orders: Iterable[Mapping[str, Any]],
    *,
    archived_watch: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Every recorded exit, graded against holding to settlement.

    Only entries the ledger has GRADED `won`/`lost` count; a push, a void or an
    ungraded entry is counted under `pending`/`ungradable`, never as a zero.
    `by_margin` replays each watched position's high-water net edge against
    `COUNTERFACTUAL_MARGINS`: a margin the position reached is credited exactly
    that margin (a LOWER BOUND -- the real crossing bid may have been higher).
    """
    outcome_by_key: dict[str, str] = {}
    for order in orders:
        key = str(order.get("idempotency_key") or "")
        if key:
            outcome_by_key[key] = str(order.get("outcome") or "")

    pending = ungradable = manual = 0
    by_rule: dict[str, dict[str, Any]] = {}
    by_mode: dict[str, dict[str, Any]] = {}
    by_phase: dict[str, dict[str, Any]] = {}
    by_sport: dict[str, dict[str, Any]] = {}
    by_venue: dict[str, dict[str, Any]] = {}
    for row in (state.get("exits") or {}).values():
        if row.get("purpose"):
            # A one-off operator sale (`exit_sell_once`), not a rule's decision:
            # it says nothing about whether the RULE beats holding.
            manual += 1
            continue
        outcome = outcome_by_key.get(str(row.get("entry_key") or ""), "")
        if not outcome:
            pending += 1
            continue
        if outcome not in _SETTLE_VALUE or row.get("status") not in {EXIT_PAPER_FILLED, EXIT_FILLED}:
            ungradable += 1
            continue
        exit_pnl = float(row.get("realized_pnl_dollars") or 0.0)
        hold = _hold_pnl(row, outcome)
        if row.get("status") == EXIT_FILLED:
            # Compare the contracts actually SOLD against holding those same
            # contracts -- a one-contract sale of five is not a five-contract exit.
            sold = _as_float(row.get("filled_contracts")) or 0.0
            fill = _as_float(row.get("fill_price"))
            contracts = float(row.get("contracts") or 0.0)
            if not sold or fill is None or contracts <= 0:
                ungradable += 1
                continue
            share = min(sold, contracts) / contracts
            entry_fee = float(row.get("entry_fee_dollars") or 0.0) * share
            exit_pnl = sold * (fill - float(row["entry_price"])) - float(row.get("exit_fee_dollars") or 0.0) - entry_fee
            hold = sold * (_SETTLE_VALUE[outcome] - float(row["entry_price"])) - entry_fee
        mode = f"{row.get('entry_mode')}/{row.get('mode')}"
        phase = {True: "in_play", False: "pregame"}.get(row.get("in_play"), "unknown")
        for buckets, label in (
            (by_rule, str(row.get("rule"))),
            (by_mode, mode),
            (by_phase, phase),
            (by_sport, str(row.get("sport") or "?")),
            (by_venue, str(row.get("family") or KALSHI)),
        ):
            _add(buckets.setdefault(label, _bucket()), exit_pnl, hold)

    watch_rows = list(archived_watch) + list((state.get("watch") or {}).values())
    seen: dict[str, Mapping[str, Any]] = {str(r.get("entry_key")): r for r in watch_rows if r.get("entry_key")}
    by_margin: dict[str, dict[str, Any]] = {}
    graded_watch = 0
    for key, row in seen.items():
        outcome = outcome_by_key.get(key, "")
        if outcome not in _SETTLE_VALUE or row.get("hwm_edge") is None:
            continue
        graded_watch += 1
        hold = _hold_pnl(row, outcome)
        for m in COUNTERFACTUAL_MARGINS:
            label = f"{row.get('family') or KALSHI}/{row.get('mode')}@{m:.2f}"
            bucket = by_margin.setdefault(label, {**_bucket(), "triggered": 0})
            if float(row["hwm_edge"]) >= m - 1e-9:
                bucket["triggered"] += 1
                _add(bucket, float(row["contracts"]) * m, hold)
            else:
                _add(bucket, hold, hold)
    return {
        "exits": len(state.get("exits") or {}),
        "graded": sum(b["n"] for b in by_mode.values()),
        "pending": pending,
        "ungradable": ungradable,
        "manual_excluded": manual,
        "by_rule": _rounded(by_rule),
        "by_mode": _rounded(by_mode),
        "by_phase": _rounded(by_phase),
        "by_sport": _rounded(by_sport),
        "by_venue": _rounded(by_venue),
        "watched_graded": graded_watch,
        "by_margin": _rounded(by_margin),
    }
