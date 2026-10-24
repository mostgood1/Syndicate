"""In-game ENTRIES on Kalshi, LIVE -- behind `SYNDICATE_INPLAY_ENTRIES` (lane in-game-trading).

USER DECISION 2026-10-23 (session 15ceeb14, in chat): "Build in-game entries LIVE
behind SYNDICATE_INPLAY_ENTRIES: same rule as the paper one (NHL spreads away from
score, >=3 fresh books, >=3% edge after fee), 1 contract per order, $50/day."

THE RULE IS NOT HERE. `inplay_entries_paper.PaperEntryLoop` decides and books;
this module receives each NEWLY booked entry through its `on_book` hook and,
only when switched on, places it. The paper record and the live order can
therefore never disagree about which bet the rule chose.

OFF BY DEFAULT. Live only when ALL hold, re-read on every entry:
  * `SYNDICATE_INPLAY_ENTRIES` is `on` or `live` (absent / anything else = off);
  * `execution_ledger.execution_mode()` is live AND `live_execution_armed()`;
  * the day's in-game stake + this order <= `SYNDICATE_INPLAY_ENTRY_DAY_DOLLARS`
    (default 50, and 50 is a CEILING the env cannot raise).

THE ORDER: 1 contract, `immediate_or_cancel` (`kalshi_orders.order_body_v2`
honours `time_in_force` on the request; IOC orders carry no kickoff expiry and
cannot rest), at the LIVE ask re-read at submit, refused if it moved more than
1c from the decision ask (never an artifact fallback). Through the executor's own
seams: `execution_guard.check_order` (its venue day caps fed THIS module's
in-game spend: the separate in-game budget the user chose 2026-10-21; per-order
cap, capital checks and all-venues caps still read the whole ledger),
`execution_guard.guarded_submit` (kill switch at the send) and
`execution_ledger.place_order` (build-before-record, write-ahead row,
reconciled by the normal RECONCILE pass: an unfilled IOC reads back `canceled`
and is moved to `rejected`).

Ledger rows: `position_key = "ingame:<ticker>:<leg>"`, market `spreads`, side = the leg.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Mapping, Sequence

POSITION_PREFIX = "ingame:"
DAY_DOLLARS_CEILING = 50.0
MAX_PRICE_MOVE = 0.01
_ON = {"on", "live"}


def entries_switch_on() -> bool:
    return str(os.environ.get("SYNDICATE_INPLAY_ENTRIES") or "").strip().lower() in _ON


def live_entries_enabled() -> bool:
    """Switch on AND the executor itself live and armed. Default False."""
    if not entries_switch_on():
        return False
    from syndicate.features.shared.execution_ledger import LIVE, execution_mode, live_execution_armed

    return execution_mode() == LIVE and bool(live_execution_armed())


def day_budget_dollars() -> float:
    try:
        v = float(str(os.environ.get("SYNDICATE_INPLAY_ENTRY_DAY_DOLLARS") or "").strip())
    except ValueError:
        return DAY_DOLLARS_CEILING
    return DAY_DOLLARS_CEILING if not (v >= 0) else min(v, DAY_DOLLARS_CEILING)


def game_axis(ticker: str) -> tuple[str, str]:
    """(game code, axis) of a full-game Kalshi ticker, the executor's R1 axes: moneyline and spread are
    the MARGIN axis, a total is the TOTAL axis. `KXNBATOTAL-26OCT23DALIND-249` -> ("26OCT23DALIND", "total")."""
    parts = str(ticker or "").split("-")
    game = parts[1] if len(parts) > 1 else ""
    return game, ("total" if parts[0].endswith("TOTAL") else "margin")


def in_game_spend(orders: Sequence[Mapping[str, Any]], day: str) -> dict[str, Any]:
    """Today's live in-game stake and order count, from the ledger (submitted + filled).

    Stake plus the recorded fee, so the $ cap is a cap on cash out. `held_axes` = the (game, axis) pairs
    holding a submitted or filled in-game order today: ONE entry per game axis (user/coordinator
    2026-10-23, after two DAL@IND unders on adjacent lines in 43 s). An IOC that did not fill
    (rejected) holds nothing, so a later signal on that axis may try again.
    """
    dollars, count, keys, axes = 0.0, 0, set(), set()
    for o in orders:
        pk = str(o.get("position_key") or "")
        if not pk.startswith(POSITION_PREFIX) or str(o.get("selected_date") or "") != day:
            continue
        keys.add(pk)
        if str(o.get("status") or "") in {"filled", "submitted"}:
            dollars += float(o.get("fill_stake_dollars") or o.get("requested_stake_dollars") or 0.0)
            dollars += float(o.get("fees_dollars") or 0.0)
            count += 1
            axes.add(game_axis(str(o.get("venue_ticker") or pk[len(POSITION_PREFIX):].rsplit(":", 1)[0])))
    return {"dollars": round(dollars, 4), "orders": count, "position_keys": keys, "held_axes": axes}


class LivePrice:
    """`price_for(request)`: the LIVE ask of our leg, or None (refuse). No artifact fallback."""

    def __init__(self, decision_ask: float):
        self.decision_ask = float(decision_ask)

    def __call__(self, request: Any) -> float | None:
        from syndicate.features.shared.kalshi_client import dollars_to_probability, fetch_market

        result = fetch_market(str(getattr(request, "venue_ticker", "") or ""))
        if result.get("status") != "ok":
            return None
        key = "no_ask_dollars" if str(getattr(request, "side", "")) == "no" else "yes_ask_dollars"
        live = dollars_to_probability((result.get("market") or {}).get(key))
        if live is None or abs(live - self.decision_ask) > MAX_PRICE_MOVE + 1e-9:
            print(f"[inplay_entries_live] PRICE_MOVED ticker={getattr(request, 'venue_ticker', None)}"
                  f" leg={getattr(request, 'side', None)} decision={self.decision_ask} live={live}", flush=True)
            return None
        return live


class _IOC:
    """The request as the order body sees it: identical, plus time_in_force=IOC."""

    time_in_force = "immediate_or_cancel"

    def __init__(self, request: Any):
        self._r = request

    def __getattr__(self, name: str) -> Any:
        return getattr(self._r, name)


def ioc_submitter(base: Any) -> Any:
    """Wrap a two-phase venue adapter so BOTH build and send see the IOC request."""

    def _build(request):
        return base.build(_IOC(request))

    def _submit(request):
        return _build(request)()

    _submit.build = _build
    return _submit


class LiveEntryPlacer:
    """The `on_book` hook. Returns a small dict that is stored on the paper entry."""

    def __init__(
        self,
        *,
        today_fn: Callable[[], str],
        orders_fn: Callable[[], Sequence[Mapping[str, Any]]] | None = None,
        place_fn: Callable[..., Mapping[str, Any]] | None = None,
        enabled_fn: Callable[[], bool] = live_entries_enabled,
    ) -> None:
        self.today_fn = today_fn
        self.orders_fn = orders_fn or _ledger_orders
        self.place_fn = place_fn or _place_live
        self.enabled_fn = enabled_fn

    def __call__(self, entry: Mapping[str, Any]) -> dict[str, Any]:
        if not self.enabled_fn():
            return {"placed": False, "reason": "live_entries_off"}
        day = self.today_fn()
        ticker, leg, ask = str(entry["ticker"]), str(entry["leg"]), float(entry["ask"])
        pk = f"{POSITION_PREFIX}{ticker}:{leg}"
        spend = in_game_spend(self.orders_fn(), day)
        stake = round(ask + MAX_PRICE_MOVE, 4)  # floors to exactly 1 contract at any live ask within 1c
        if pk in spend["position_keys"]:
            result = {"placed": False, "reason": "already_in_ledger_today"}
        elif game_axis(ticker) in spend["held_axes"]:
            result = {"placed": False, "reason": "same_game_axis_held", "axis": "/".join(game_axis(ticker))}
        elif spend["dollars"] + stake > day_budget_dollars() + 1e-9:
            result = {"placed": False, "reason": "in_game_day_budget", "spend": spend["dollars"]}
        else:
            result = dict(self.place_fn(ticker=ticker, leg=leg, ask=ask, stake=stake, line=entry.get("line"),
                                        sport=str(entry.get("sport") or "nhl"), market=str(entry.get("kind") or "spreads"),
                                        day=day, spend=spend, game=_game_fields(entry)) or {})
        print(f"[inplay_entries_live] LIVE_ENTRY ticker={ticker} leg={leg} ask={ask} stake={stake}"
              f" edge={entry.get('edge')} day_spend={spend['dollars']}/{day_budget_dollars()} result={result}"[:500],
              flush=True)
        return result


def _ledger_orders() -> list[Mapping[str, Any]]:
    from syndicate.features.shared.execution_ledger import _load

    return list(_load().get("orders") or [])


def _game_fields(entry: Mapping[str, Any]) -> dict[str, Any]:
    """What the paper rule matched: the OddsAPI event (= the board's event_id), teams, commence, and the
    human side/line (`inplay_entries_paper.human_selection`). Absent fields stay absent."""
    return {k: entry.get(k) for k in ("event_id", "home_team", "away_team", "commence_time", "order_side", "order_line")
            if entry.get(k) is not None}


def _place_live(*, ticker: str, leg: str, ask: float, stake: float, line: Any, day: str,
                sport: str = "nhl", market: str = "spreads",
                spend: Mapping[str, Any], game: Mapping[str, Any] | None = None) -> dict[str, Any]:
    from syndicate.features.shared.execution_guard import check_order, guarded_submit
    from syndicate.features.shared.execution_ledger import LIVE, OrderRequest, place_order
    from syndicate.features.shared.kalshi_orders import kalshi_submitter

    g = dict(game or {})
    side = str(g.get("order_side") or leg)
    order_line = g.get("order_line", line) if "order_side" in g else line
    request = OrderRequest(
        position_key=f"{POSITION_PREFIX}{ticker}:{leg}", selected_date=day, venue="kalshi", sport=sport,
        event_id=str(g.get("event_id") or ticker.rsplit("-", 1)[0]), market=market, side=side,
        requested_price=ask, requested_stake_dollars=stake,
        line=None if order_line is None else float(order_line), book="kalshi", venue_ticker=ticker,
        home_team=g.get("home_team"), away_team=g.get("away_team"), commence_time=g.get("commence_time"),
    )
    # The contract must not change because the label did: refuse if the human side maps to another leg.
    from syndicate.features.shared.kalshi_orders import _side_to_kalshi

    if _side_to_kalshi(request.side, request.market, request.line) != leg:
        return {"placed": False, "reason": f"side_relabel_mismatch: {request.side}/{request.line} != {leg}"}
    verdict = check_order(request, mode=LIVE, already={"dollars": spend["dollars"], "orders": spend["orders"]})
    if not verdict.get("allowed"):
        return {"placed": False, "reason": verdict.get("reason")}
    submit = guarded_submit(ioc_submitter(kalshi_submitter(LivePrice(ask))))
    try:
        record = place_order(request, submit=submit, mode=LIVE)
    except Exception as exc:  # noqa: BLE001 -- a raised send is kept as failed by the ledger
        return {"placed": False, "reason": f"{type(exc).__name__}: {exc}"[:200]}
    if record.get("recorded") is False:
        return {"placed": False, "reason": str(record.get("reason") or record.get("error") or "build_refused")}
    return {"placed": True, "status": record.get("status"), "key": record.get("idempotency_key")}
