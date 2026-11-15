"""In-game fast exit loop -- STAGE 1 (lane in-game-trading).

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

HOW IT SELLS (user decision 2026-10-21 ~21:3xZ, "Exits + tiny entries live").
It never builds or sends an order itself: there is no `place_exit` /
`send_exit_order` call here (the test parses the module). When a LIVE in-play
position triggers a rule in `execution_exits.live_exit_rules()`, it hands that
position's entry order row(s) to the slow tick's own
`execution_exits.run_exit_tick(today, orders=[...])`. That runs the same venue
reconcile, the same live switches (`SYNDICATE_EXIT_MODE=live`,
`SYNDICATE_EXIT_LIVE_ARMED` + the entry arm), the same daily caps
(`live_exit_daily_caps`, 5 sales / $25) and the same `place_exit`. Both callers
are serialised by `execution_exits.EXIT_STATE_LOCK`. Its own document, and
that document's archive lines, are the only files it writes.

MODE (`SYNDICATE_EXIT_FAST_LOOP`):
  absent / `live` -> FOLLOW the slow tick: dispatch live sales when
                     `execution_exits.exit_mode()` is `live`, otherwise paper.
                     (A role-only restart cannot load a new env key, so the
                     switch that already decides live selling decides this too.)
  `paper`         -> mark and book paper triggers only, never dispatch.
  off/0/false/no/disabled -> off.
Any other text is paper.

Document: `reports/intelligence/execution_exits_fast.json`
  marks:  per entry -- samples, first/last mark, high-water net edge, last bid
  exits:  per entry -- the FIRST fast trigger (bid, edge, at), and what the slow
          tick's watch said for the same entry at that moment
  passes: running counters (passes, marks, quote errors) for marks/min
Retention: before each save, entries past the slow document's floor (lookback +
2 days) move to `execution_exits_archive/fast_<YYYY-MM>.jsonl`
(`prune_fast_state`), so the document stays under the 8 MB keyvalue cap.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Sequence

from syndicate.features.shared.execution_exits import (
    KALSHI,
    OpenPosition,
    _archive,
    _float_env,
    _is_in_play,
    _position_date,
    _retention_floor,
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
FAST_LIVE = "live"
FAST_OFF = "off"
_DEFAULT_SECONDS = 15.0
_MIN_SECONDS = 5.0
_DEFAULT_POSITIONS_SECONDS = 60.0
_DEFAULT_PERSIST_SECONDS = 60.0


_OFF_VALUES = frozenset({"off", "0", "false", "no", "disabled"})


def fast_loop_mode() -> str:
    """`off` | `paper` | `live`. `live` only by FOLLOWING the slow tick's own live exit mode."""
    from syndicate.features.shared.execution_exits import EXIT_LIVE, exit_mode

    raw = str(os.environ.get("SYNDICATE_EXIT_FAST_LOOP") or "").strip().lower()
    if raw in _OFF_VALUES:
        return FAST_OFF
    if raw in ("", FAST_LIVE):
        return FAST_LIVE if exit_mode() == EXIT_LIVE else FAST_PAPER
    return FAST_PAPER


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


# The per-entry parts of the document. Every one is keyed by the ENTRY order's key.
_ENTRY_PARTS = ("marks", "exits", "live_dispatch")


def _entry_date(state: Mapping[str, Any], key: str) -> str:
    """The position date for `key`: its mark's (`_position_date`, the slow tick's own), else the trigger's day.

    A mark is always written before an exit or a dispatch for the same entry (`mark_pass`), so the fallback only
    covers a document edited by hand. "" when nothing dates it -- such an entry is KEPT, never dropped unread.
    """
    mark = (state.get("marks") or {}).get(key)
    if isinstance(mark, Mapping):
        return _position_date(mark)
    for part in ("exits", "live_dispatch"):
        row = (state.get(part) or {}).get(key)
        if isinstance(row, Mapping) and row.get("at"):
            return str(row["at"])[:10]
    return ""


def prune_fast_state(state: dict[str, Any], today: str) -> int:
    """Move entries whose position is past the slow document's retention floor to the archive. Returns how many.

    THE DOCUMENT WAS NEVER PRUNED. MEASURED 2026-11-14 (lane `fast-exit-state-size`): the stored copy was 8,388,431
    bytes compact -- marks 5.24 MB, exits 3.06 MB, 10,801 entries back to 10-18 -- against the 8,388,608-byte
    keyvalue cap, and every save from 17:00:32Z was refused (1,163 by 22:55Z). Sales were NOT blocked: `step` sends
    before it saves. But each refusal reloaded the stale copy, so the fast paper record since the last accepted save
    was lost and the pass summary never printed.

    THE SLOW DOCUMENT'S RULE (`execution_exits._retention_floor`, lookback + 2 days, `506973f97`). A position older
    than the lookback is never in play again for this loop (`open_positions` drops it), so nothing here reads its
    mark or its first trigger again. The rows go to `execution_exits_archive/fast_<YYYY-MM>.jsonl`, one line per
    entry with all its parts, BEFORE the save that omits them; a refused save re-archives them next time, and a
    reader keeps the newest line per `entry_key`. Dry run on the 11-14 stored copy: 8,388,431 -> 1,220,006 bytes.
    """
    floor = _retention_floor(today)
    if floor is None:
        return 0
    keys: set[str] = set()
    for part in _ENTRY_PARTS:
        if isinstance(state.get(part), dict):
            keys.update(state[part])
    dated = {k: _entry_date(state, k) for k in keys}
    stale = sorted(k for k, d in dated.items() if d and d < floor)
    if not stale:
        return 0
    rows = []
    for k in stale:
        mark = (state.get("marks") or {}).get(k)
        row: dict[str, Any] = {
            "entry_key": k,
            "position_date": dated[k],
            # `_archive` files a row by its `selected_date` month; the position date stands in when the mark has none.
            "selected_date": (mark.get("selected_date") if isinstance(mark, Mapping) else None) or dated[k],
        }
        for part in _ENTRY_PARTS:
            if k in (state.get(part) or {}):
                row[part] = state[part][k]
        rows.append(row)
    _archive(rows, prefix="fast")
    for part in _ENTRY_PARTS:
        bucket = state.get(part)
        if isinstance(bucket, dict):
            for k in stale:
                bucket.pop(k, None)
    return len(stale)


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
    triggered: list[tuple[str, str, str]] = []  # (entry_key, rule, position mode), EVERY trigger this pass
    settled: list[str] = []  # entry_keys whose market is closed: nothing left to mark
    for p in positions:
        decision = evaluate_exit(p, markets.get(p.ticker), margin=margin, fair_buffer=buffer, now=now)
        reasons[decision["reason"]] = reasons.get(decision["reason"], 0) + 1
        if decision["reason"] in ("market_finalized", "market_settled", "market_expired", "market_closed"):
            settled.append(p.entry_key)
        if decision.get("rule"):
            triggered.append((p.entry_key, str(decision["rule"]), p.mode))
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
            "quote_errors": len(quotes.get("errors") or []), "triggered": triggered, "settled": settled}


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
        dispatch_fn: Callable[..., Mapping[str, Any]] | None = None,
    ) -> None:
        self.today_fn = today_fn
        self.orders_fn = orders_fn or _ledger_orders
        self.quotes_fn = quotes_fn or fetch_quotes
        self.exits_state_fn = exits_state_fn or load_state
        self.persist = persist or persist_fast_state
        self.clock = clock
        # THE ONLY SELLING ROUTE: the slow tick's own pass, over just the triggered rows.
        self.dispatch_fn = dispatch_fn or _run_exit_tick
        self._orders_by_key: dict[str, Mapping[str, Any]] = {}
        self._dispatched: set[str] = set()
        self._settled: set[str] = set()
        self.state: dict[str, Any] | None = None
        self.positions: list[OpenPosition] = []
        self.slow_watch: Mapping[str, Any] = {}
        self._positions_at: float | None = None
        self._persist_at: float | None = None
        self._dirty = False
        self._summary_at: float | None = None
        self._window = {"passes": 0, "marked": 0, "new_exits": 0, "quote_errors": 0}

    def step(self, now: datetime | None = None) -> dict[str, Any]:
        mode = fast_loop_mode()
        if mode == FAST_OFF:
            return {"status": "off"}
        now = now or datetime.now(timezone.utc)
        t = self.clock()
        if self.state is None:
            self.state = load_fast_state()
        if self._positions_at is None or t - self._positions_at >= positions_refresh_seconds():
            exits_state = self.exits_state_fn()
            self.slow_watch = dict(exits_state.get("watch") or {})
            orders = list(self.orders_fn())
            self._orders_by_key = {str(o.get("idempotency_key") or ""): o for o in orders if isinstance(o, Mapping)}
            self.positions = [
                p for p in in_play_kalshi_positions(orders, today=self.today_fn(), exits_state=exits_state, now=now)
                if p.entry_key not in self._settled
            ]
            self._positions_at = t
        if not self.positions:
            return {"status": "idle", "positions": 0}
        quotes = self.quotes_fn(sorted({p.ticker for p in self.positions}))
        summary = mark_pass(self.state, self.positions, quotes, slow_watch=self.slow_watch, now=now)
        if summary["settled"]:  # a closed market is never re-quoted
            self._settled.update(summary["settled"])
            self.positions = [p for p in self.positions if p.entry_key not in self._settled]
        summary["live_dispatched"] = self._dispatch_live(summary["triggered"], now) if mode == FAST_LIVE else 0
        self._dirty = True
        for k in self._window:
            self._window[k] += summary.get(k, 1 if k == "passes" else 0)
        if summary["new_exits"] or self._persist_at is None or t - self._persist_at >= _DEFAULT_PERSIST_SECONDS:
            today = self.today_fn()
            pruned = prune_fast_state(self.state, today)
            if pruned:
                print(
                    f"[execution_exits_fast] FAST_STATE_PRUNED entries={pruned} floor={_retention_floor(today)}"
                    f" kept={len(self.state.get('marks') or {})}",
                    flush=True,
                )
            self.persist(self.state)
            self._persist_at, self._dirty = t, False
        if self._summary_at is None or t - self._summary_at >= 60:
            w = self._window
            print(
                f"[execution_exits_fast] FAST_EXIT_PASS mode={mode} positions={summary['positions']} passes={w['passes']}"
                f" marks={w['marked']} new_paper_exits={w['new_exits']} quote_errors={w['quote_errors']}"
                f" reasons={summary['reasons']} interval_s={fast_loop_seconds():.0f}",
                flush=True,
            )
            self._summary_at = t
            self._window = {k: 0 for k in self._window}
        return {"status": "ok", **summary}

    def _dispatch_live(self, triggered: Sequence[tuple[str, str, str]], now: datetime) -> int:
        """Hand LIVE positions whose trigger is an ARMED live rule to the slow tick's pass. Returns how many."""
        from syndicate.features.shared.execution_exits import live_exit_rules

        armed = live_exit_rules()
        keys = [
            k for k, rule, pmode in triggered
            if pmode == "live" and set(rule.split("+")) & armed and k not in self._dispatched and k in self._orders_by_key
        ]
        if not keys:
            return 0
        self._dispatched.update(keys)  # one dispatch per entry; the slow tick still watches it afterwards
        rows = [self._orders_by_key[k] for k in keys]
        stamp = now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            result = dict(self.dispatch_fn(today=self.today_fn(), orders=rows) or {})
        except Exception as exc:  # noqa: BLE001 -- the slow tick will still see it
            result = {"status": "error", "error": f"{type(exc).__name__}: {exc}"[:200]}
        for k in keys:
            self.state.setdefault("live_dispatch", {})[k] = {
                "at": stamp, "status": result.get("status"), "live_exits": result.get("live_exits"),
                "reasons": result.get("reasons"), "error": result.get("error"),
            }
        self._positions_at = None  # re-read positions next pass so a sale nets out
        print(
            f"[execution_exits_fast] FAST_EXIT_LIVE_DISPATCH entries={keys} status={result.get('status')}"
            f" mode={result.get('mode')} live_exits={result.get('live_exits')} reasons={result.get('reasons')}"
            f" error={result.get('error')}",
            flush=True,
        )
        return len(keys)


def _run_exit_tick(**kwargs: Any) -> Mapping[str, Any]:
    from syndicate.features.shared.execution_exits import run_exit_tick

    return run_exit_tick(**kwargs)


def _ledger_orders() -> list[Mapping[str, Any]]:
    from syndicate.features.shared.execution_ledger import _load

    return list(_load().get("orders") or [])
