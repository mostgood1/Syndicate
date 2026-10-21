"""In-game fast exit loop -- STAGE 1, PAPER ONLY (lane in-game-trading).

WHY IT EXISTS. The exit check (`execution_exits.run_exit_tick`) runs inside the
placer's execution tick: 300 s by default and measured at 5-15 min between
EXIT_TICK lines on 2026-10-20. In play, Kalshi re-prices a score within ~10 s
(measured the same night: TOR@CBJ's goal was in Kalshi's ask 34 s before ESPN
showed it, and the ask changed every 10-11 s at p50 on NHL game lines). A
take-profit that is only looked at every 5-15 minutes sells whatever the price
happens to be at that moment, not when the price crossed the line.

WHAT IT DOES. Every `SYNDICATE_EXIT_FAST_LOOP_SECONDS` (default 15) it marks
every IN-PLAY Kalshi position from the public batched quote and runs the SAME
rule the slow tick runs (`execution_exits.evaluate_exit`, same margin env). The
first trigger per entry is booked as a FAST paper exit in its own document.

WHAT IT NEVER DOES. It imports no order, credential or cancel code: there is no
`place_exit` call here, so this module cannot sell. It never writes
`execution_exits.json` (the slow tick's document, lane kalshi-exit-path): it
only READS that document, to net out positions a live exit already sold. Going
live is a separate change and a separate user decision.

PAPER BY DEFAULT (user decision 2026-10-21, "Default to paper"): absent means
paper, because the supervisor derives a role's env once at `up` and a
role-only restart could not load a new key. `off` / `0` / `false` / `no` /
`disabled` turn it off. There is NO live value: any other text is paper, and
paper has no order path to reach.

Document: `reports/intelligence/execution_exits_fast.json`
  marks:  per entry -- samples, first/last mark, high-water net edge, last bid
  exits:  per entry -- the FIRST fast trigger (bid, edge, at), and what the slow
          tick's watch said for the same entry at that moment
  passes: running counters (passes, marks, quote errors) for marks/min
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Sequence

from syndicate.features.shared.execution_exits import (
    KALSHI,
    OpenPosition,
    _float_env,
    _is_in_play,
    evaluate_exit,
    fair_margin,
    fetch_quotes,
    load_state,
    net_of_live_sales,
    open_positions,
    round_trip_pnl,
    take_profit_margin,
)

FAST_PAPER = "paper"
_DEFAULT_SECONDS = 15.0
_MIN_SECONDS = 5.0
_DEFAULT_POSITIONS_SECONDS = 60.0
_DEFAULT_PERSIST_SECONDS = 60.0


_OFF_VALUES = frozenset({"off", "0", "false", "no", "disabled"})


def fast_loop_mode() -> str:
    """`off` only when explicitly turned off; otherwise `paper`. Never `live`."""
    raw = str(os.environ.get("SYNDICATE_EXIT_FAST_LOOP") or "").strip().lower()
    return "off" if raw in _OFF_VALUES else FAST_PAPER


def fast_loop_seconds() -> float:
    return max(_MIN_SECONDS, _float_env("SYNDICATE_EXIT_FAST_LOOP_SECONDS", _DEFAULT_SECONDS))


def positions_refresh_seconds() -> float:
    return max(fast_loop_seconds(), _float_env("SYNDICATE_EXIT_FAST_POSITIONS_SECONDS", _DEFAULT_POSITIONS_SECONDS))


def fast_path():
    from syndicate.features.shared.refresh_state_store import reports_root

    return reports_root() / "intelligence" / "execution_exits_fast.json"


def _empty() -> dict[str, Any]:
    return {"version": 1, "marks": {}, "exits": {}, "passes": {"n": 0, "marks": 0, "quote_errors": 0, "since": None}}


def load_fast_state() -> dict[str, Any]:
    from syndicate.features.shared.refresh_state_store import read_json_file_result

    payload, read_ok = read_json_file_result(fast_path())
    if not read_ok:
        raise RuntimeError("execution_exits_fast_unreadable")
    state = dict(payload or {})
    for key, value in _empty().items():
        if not isinstance(state.get(key), type(value)):
            state[key] = value
    return state


def persist_fast_state(state: Mapping[str, Any]) -> None:
    from syndicate.features.shared.refresh_state_store import write_json_file

    write_json_file(fast_path(), dict(state))


def in_play_kalshi_positions(
    orders: Sequence[Mapping[str, Any]], *, today: str, exits_state: Mapping[str, Any], now: datetime
) -> list[OpenPosition]:
    """Open Kalshi positions whose game has started, net of live sales. PURE."""
    positions, _skipped = open_positions(orders, today=today)
    positions, _sold = net_of_live_sales(positions, exits_state)
    return [p for p in positions if p.family == KALSHI and _is_in_play(p.commence_time, now) is True]


def mark_pass(
    state: dict[str, Any],
    positions: Sequence[OpenPosition],
    quotes: Mapping[str, Any],
    *,
    slow_watch: Mapping[str, Any],
    now: datetime,
) -> dict[str, Any]:
    """Mark `positions` against `quotes` and book first triggers. Mutates `state`. PURE otherwise.

    Returns the pass summary. The rule and both margins are the slow tick's own.
    """
    stamp = now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    markets = quotes.get("markets") or {}
    margin, buffer = take_profit_margin(), fair_margin()
    reasons: dict[str, int] = {}
    new_exits = 0
    marked = 0
    for p in positions:
        decision = evaluate_exit(p, markets.get(p.ticker), margin=margin, fair_buffer=buffer, now=now)
        reasons[decision["reason"]] = reasons.get(decision["reason"], 0) + 1
        edge = decision.get("edge_per_contract")
        row = state["marks"].setdefault(
            p.entry_key,
            {"ticker": p.ticker, "leg": p.leg, "mode": p.mode, "contracts": p.contracts, "entry_price": p.entry_price,
             "entry_fee_dollars": p.entry_fee_dollars, "commence_time": p.commence_time, "sport": p.sport,
             "market": p.market, "selected_date": p.selected_date, "samples": 0, "first_mark": stamp, "hwm_edge": None},
        )
        row["last_mark"] = stamp
        row["last_reason"] = decision["reason"]
        if edge is None:
            continue
        marked += 1
        row["samples"] = int(row.get("samples") or 0) + 1
        row["last_bid"] = decision.get("bid")
        row["last_edge"] = edge
        if row.get("hwm_edge") is None or edge > float(row["hwm_edge"]):
            row["hwm_edge"], row["hwm_bid"], row["hwm_at"] = edge, decision.get("bid"), stamp
        if not decision.get("rule") or p.entry_key in state["exits"]:
            continue
        slow = slow_watch.get(p.entry_key) or {}
        state["exits"][p.entry_key] = {
            "ticker": p.ticker, "leg": p.leg, "mode": p.mode, "rule": decision.get("rule"), "at": stamp,
            "contracts": p.contracts, "entry_price": p.entry_price, "bid": decision.get("bid"),
            "bid_size": decision.get("bid_size"), "net_per_contract": decision.get("net_per_contract"),
            "edge_per_contract": edge, "margin": margin,
            "paper_pnl_dollars": round_trip_pnl(p, float(decision["bid"]), float(decision["exit_fee_dollars"])),
            # What the SLOW tick had seen for this entry when the fast loop fired.
            "slow_last_seen": slow.get("last_seen"), "slow_last_reason": slow.get("last_reason"),
            "slow_hwm_edge": slow.get("hwm_edge"),
        }
        new_exits += 1
        print(
            f"[execution_exits_fast] FAST_EXIT_PAPER entry={p.entry_key} mode={p.mode} ticker={p.ticker} leg={p.leg}"
            f" rule={decision.get('rule')} contracts={p.contracts} entry={p.entry_price} bid={decision.get('bid')}"
            f" edge={edge} slow_last_reason={slow.get('last_reason')} slow_last_seen={slow.get('last_seen')}",
            flush=True,
        )
    passes = state["passes"]
    passes["n"] = int(passes.get("n") or 0) + 1
    passes["marks"] = int(passes.get("marks") or 0) + marked
    passes["quote_errors"] = int(passes.get("quote_errors") or 0) + len(quotes.get("errors") or [])
    passes["since"] = passes.get("since") or stamp
    state["updated_at"] = stamp
    return {"positions": len(positions), "marked": marked, "reasons": reasons, "new_exits": new_exits,
            "quote_errors": len(quotes.get("errors") or [])}


class FastExitLoop:
    """The loop body, with its clocks, so the worker thread stays three lines."""

    def __init__(
        self,
        *,
        today_fn: Callable[[], str],
        orders_fn: Callable[[], Sequence[Mapping[str, Any]]] | None = None,
        quotes_fn: Callable[[Sequence[str]], Mapping[str, Any]] | None = None,
        exits_state_fn: Callable[[], Mapping[str, Any]] | None = None,
        persist: Callable[[Mapping[str, Any]], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.today_fn = today_fn
        self.orders_fn = orders_fn or _ledger_orders
        self.quotes_fn = quotes_fn or fetch_quotes
        self.exits_state_fn = exits_state_fn or load_state
        self.persist = persist or persist_fast_state
        self.clock = clock
        self.state: dict[str, Any] | None = None
        self.positions: list[OpenPosition] = []
        self.slow_watch: Mapping[str, Any] = {}
        self._positions_at: float | None = None
        self._persist_at: float | None = None
        self._dirty = False
        self._summary_at: float | None = None
        self._window = {"passes": 0, "marked": 0, "new_exits": 0, "quote_errors": 0}

    def step(self, now: datetime | None = None) -> dict[str, Any]:
        if fast_loop_mode() != FAST_PAPER:
            return {"status": "off"}
        now = now or datetime.now(timezone.utc)
        t = self.clock()
        if self.state is None:
            self.state = load_fast_state()
        if self._positions_at is None or t - self._positions_at >= positions_refresh_seconds():
            exits_state = self.exits_state_fn()
            self.slow_watch = dict(exits_state.get("watch") or {})
            self.positions = in_play_kalshi_positions(
                list(self.orders_fn()), today=self.today_fn(), exits_state=exits_state, now=now
            )
            self._positions_at = t
        if not self.positions:
            return {"status": "idle", "positions": 0}
        quotes = self.quotes_fn(sorted({p.ticker for p in self.positions}))
        summary = mark_pass(self.state, self.positions, quotes, slow_watch=self.slow_watch, now=now)
        self._dirty = True
        for k in self._window:
            self._window[k] += summary.get(k, 1 if k == "passes" else 0)
        if summary["new_exits"] or self._persist_at is None or t - self._persist_at >= _DEFAULT_PERSIST_SECONDS:
            self.persist(self.state)
            self._persist_at, self._dirty = t, False
        if self._summary_at is None or t - self._summary_at >= 60:
            w = self._window
            print(
                f"[execution_exits_fast] FAST_EXIT_PASS mode=paper positions={summary['positions']} passes={w['passes']}"
                f" marks={w['marked']} new_paper_exits={w['new_exits']} quote_errors={w['quote_errors']}"
                f" reasons={summary['reasons']} interval_s={fast_loop_seconds():.0f}",
                flush=True,
            )
            self._summary_at = t
            self._window = {k: 0 for k in self._window}
        return {"status": "ok", **summary}


def _ledger_orders() -> list[Mapping[str, Any]]:
    from syndicate.features.shared.execution_ledger import _load

    return list(_load().get("orders") or [])
