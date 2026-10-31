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
    (absent / unusable = 50; the env may raise it to the CEILING of 100 and no further. User
    2026-10-28, in chat: "we should double the cap to $100/day");
  * the decision ask, as a probability, is inside the pregame executor's live price
    band `[low, high)` (`execute_portfolio.live_price_band()`, the same
    `SYNDICATE_LIVE_PRICE_BAND`; absent/unusable = off, exactly as pregame). User
    2026-10-23 via coordinator 332cb014: "Yes, same band", after a 12c h2h longshot;
  * when `SYNDICATE_LIVE_CELL_GATE=on`, the entry's cell (`kalshi|<sport>|<family>|in_game`) is not
    tripped in the persisted `live_cell_gate` state (READ only: the refresh-worker evaluates; an
    unreadable state refuses `live_cell_gate_unknown`, fail closed; the read is cached 60 s). User
    "Per-cell trip only (C)" via coordinator 332cb014, lane live-cell-scorecard (d57baa09), 2026-10-24.

THE ORDER: 1 contract (or, when `SYNDICATE_INPLAY_ENTRY_ORDER_DOLLARS` is set, as many whole contracts
as that many dollars buys at ask + 1c, capped at $5 per order; `entry_stake`), `immediate_or_cancel` (`kalshi_orders.order_body_v2`
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

THE DECISION RECORD (lane in-game-trading item (e), handed over by syndicate-decision-engine, log
2026-10-30 17:50Z: 170 of 292 settled live fills were in-play, with no record and no
`staked_probability_version`). Every live decision, whether placed or refused, appends ONE line to
`<data root>/reports/intelligence/decision_records/<date>.inplay.jsonl`. That is the pregame
DecisionRecords' directory: export-only allowlisted, and on the fleet's shared data root, so web reads it.
The line carries the fair and its version, the ask and leg, EVERY guard's verdict (each one is evaluated,
not only the first refusal), the sizing rule and its version, and the result. It joins the ledger by
`idempotency_key` (the ledger's own deterministic key, computed from the same request). The ledger row
itself carries `staked_probability_version = "inplay:<fair version>"` and `sizing_basis`.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

RECORD_VERSION = "inplay_decision_record/1"
# 1 = one contract per order (2026-10-23); 2 = SYNDICATE_INPLAY_ENTRY_ORDER_DOLLARS whole contracts (2026-10-28).
SIZING_VERSION = "inplay_entry_stake/2"
POSITION_PREFIX = "ingame:"
DAY_DOLLARS_DEFAULT = 50.0  # absent / unusable env: the original cap, never the ceiling
DAY_DOLLARS_CEILING = 100.0  # user 2026-10-28: "double the cap to $100/day"
ORDER_DOLLARS_CEILING = 5.0
MAX_PRICE_MOVE = 0.01
CELL_GATE_CACHE_S = 60.0
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
        return DAY_DOLLARS_DEFAULT
    return DAY_DOLLARS_DEFAULT if not (v >= 0) else min(v, DAY_DOLLARS_CEILING)


def order_dollars() -> float | None:
    """`SYNDICATE_INPLAY_ENTRY_ORDER_DOLLARS`: target $ per in-game order. Absent / unusable / <= 0 = None
    (the original 1 contract). Clamped to ORDER_DOLLARS_CEILING, which the env cannot raise. User 2026-10-28
    via coordinator 332cb014: "Step up now" (about $3 per order, $50/day cap kept), after 75 one-contract
    fills, +$2.36 after fees on $33.50 (per-bet ROI +5.9% +/- 8.3 SE)."""
    try:
        v = float(str(os.environ.get("SYNDICATE_INPLAY_ENTRY_ORDER_DOLLARS") or "").strip())
    except ValueError:
        return None
    return min(v, ORDER_DOLLARS_CEILING) if v > 0 else None


def entry_stake(ask: float) -> float:
    """Stake for one in-game order at decision ask `ask`: whole contracts priced at ask + MAX_PRICE_MOVE, so
    the submitter's floor at any live ask within 1c lands on that count. At least 1 contract."""
    unit = float(ask) + MAX_PRICE_MOVE
    target = order_dollars()
    if target is None or unit <= 0:
        return round(unit, 4)  # the original single contract, unchanged
    n = max(1, int((target + 1e-9) // unit))
    # +0.0001: n * (ask + 1c) / (ask + 1c) floors to n - 1 in float (2.80 / 0.56 = 4.999...).
    return round(n * unit + 1e-4, 4)


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
    """`price_for(request)`: the LIVE ask of our leg, or None (refuse). No artifact fallback.

    The LEG is given, never read off `request.side`: since 2b7a29c4 the side is the human label
    (`under`, a team's home/away), so `side == "no"` read the YES ask for every NO leg and refused it
    `no_live_price` (7 of 7 NO legs on 2026-10-24 16:18-17:20Z).
    """

    def __init__(self, decision_ask: float, leg: str = "yes"):
        self.decision_ask = float(decision_ask)
        self.leg = "no" if str(leg).strip().lower() == "no" else "yes"

    def __call__(self, request: Any) -> float | None:
        from syndicate.features.shared.kalshi_client import dollars_to_probability, fetch_market

        result = fetch_market(str(getattr(request, "venue_ticker", "") or ""))
        if result.get("status") != "ok":
            return None
        key = f"{self.leg}_ask_dollars"
        live = dollars_to_probability((result.get("market") or {}).get(key))
        if live is None or abs(live - self.decision_ask) > MAX_PRICE_MOVE + 1e-9:
            print(f"[inplay_entries_live] PRICE_MOVED ticker={getattr(request, 'venue_ticker', None)}"
                  f" leg={self.leg} decision={self.decision_ask} live={live}", flush=True)
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
        gate_fn: Callable[[], Mapping[str, Any]] | None = None,
        clock: Callable[[], float] = time.monotonic,
        record_fn: Callable[[str, Mapping[str, Any]], None] | None = None,
    ) -> None:
        self.today_fn = today_fn
        self.orders_fn = orders_fn or _ledger_orders
        self.place_fn = place_fn or _place_live
        self.enabled_fn = enabled_fn
        self.gate_fn = gate_fn or _cell_gate_state
        self.clock = clock
        self.record_fn = record_fn or append_decision_record
        self._gate: tuple[float, Mapping[str, Any]] | None = None

    def _cell_check(self, entry: Mapping[str, Any]) -> tuple[str | None, str | None]:
        """(cell, refusal). cell None = the gate is off; refusal None = allowed."""
        from syndicate.features.shared import live_cell_gate as lcg

        if not lcg.enabled():
            return None, None
        now = self.clock()
        if self._gate is None or now - self._gate[0] >= CELL_GATE_CACHE_S:
            self._gate = (now, dict(self.gate_fn() or {}))
        fam = lcg.family_of({"market": str(entry.get("kind") or "spreads")})
        cell = lcg.cell_key("kalshi", str(entry.get("sport") or "nhl").lower(), fam, "in_game")
        ok, why = lcg.allows(cell, self._gate[1])
        return cell, (None if ok else str(why))

    def __call__(self, entry: Mapping[str, Any]) -> dict[str, Any]:
        if not self.enabled_fn():
            return {"placed": False, "reason": "live_entries_off"}
        day = self.today_fn()
        ticker, leg, ask = str(entry["ticker"]), str(entry["leg"]), float(entry["ask"])
        pk = f"{POSITION_PREFIX}{ticker}:{leg}"
        spend = in_game_spend(self.orders_fn(), day)
        stake = entry_stake(ask)  # whole contracts; 1 unless SYNDICATE_INPLAY_ENTRY_ORDER_DOLLARS is set
        cap = day_budget_dollars()
        band = _price_band()
        cell, cell_refusal = self._cell_check(entry)
        # EVERY guard's verdict, evaluated independently so the record holds all of them; the order of the
        # refusals below is unchanged (the first failing guard is the reason).
        guards: dict[str, dict[str, Any]] = {
            "band": {"verdict": "off"} if band is None else {
                "verdict": "pass" if band[0] - 1e-9 <= ask < band[1] - 1e-9 else "fail", "band": [band[0], band[1]]},
            "cell_gate": {"verdict": "off"} if cell is None else {
                "verdict": "pass" if cell_refusal is None else "fail", "cell": cell, "reason": cell_refusal},
            "ledger": {"verdict": "fail" if pk in spend["position_keys"] else "pass"},
            "axis": {"verdict": "fail" if game_axis(ticker) in spend["held_axes"] else "pass",
                     "axis": "/".join(game_axis(ticker))},
            "day_budget": {"verdict": "fail" if spend["dollars"] + stake > cap + 1e-9 else "pass",
                           "spend": spend["dollars"], "stake": stake, "cap": cap},
        }
        if guards["band"]["verdict"] == "fail":
            result = {"placed": False, "reason": "outside_price_band", "band": f"[{band[0]:.2f},{band[1]:.2f})"}
        elif cell_refusal is not None:
            result = {"placed": False, "reason": cell_refusal}
        elif guards["ledger"]["verdict"] == "fail":
            result = {"placed": False, "reason": "already_in_ledger_today"}
        elif guards["axis"]["verdict"] == "fail":
            result = {"placed": False, "reason": "same_game_axis_held", "axis": guards["axis"]["axis"]}
        elif guards["day_budget"]["verdict"] == "fail":
            result = {"placed": False, "reason": "in_game_day_budget", "spend": spend["dollars"]}
        else:
            result = dict(self.place_fn(ticker=ticker, leg=leg, ask=ask, stake=stake, line=entry.get("line"),
                                        sport=str(entry.get("sport") or "nhl"), market=str(entry.get("kind") or "spreads"),
                                        day=day, spend=spend, game=_game_fields(entry),
                                        provenance=order_provenance(entry)) or {})
        guards["check_order"] = dict(result.pop("check_order", None) or {"verdict": "not_reached"})
        ikey = result.pop("idempotency_key", None) or (result.get("key") if result.get("placed") else None)
        self.record_fn(day, build_decision_record(entry, day=day, stake=stake, cap=cap, spend=spend,
                                                  guards=guards, result=result, idempotency_key=ikey))
        print(f"[inplay_entries_live] LIVE_ENTRY ticker={ticker} leg={leg} ask={ask} stake={stake}"
              f" edge={entry.get('edge')} day_spend={spend['dollars']}/{cap} result={result}"[:500],
              flush=True)
        return result


def _cell_gate_state() -> Mapping[str, Any]:
    from syndicate.features.shared.live_cell_gate import _read_only_gate

    return _read_only_gate()


def _price_band() -> tuple[float, float] | None:
    from pipeline.execute_portfolio import live_price_band

    return live_price_band()


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
                spend: Mapping[str, Any], game: Mapping[str, Any] | None = None,
                provenance: Mapping[str, Any] | None = None) -> dict[str, Any]:
    from syndicate.features.shared.execution_guard import check_order, guarded_submit
    from syndicate.features.shared.execution_ledger import LIVE, OrderRequest, idempotency_key, place_order
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
        staked_probability_version=(provenance or {}).get("staked_probability_version"),
        sizing_basis=(provenance or {}).get("sizing_basis"),
    )
    # The ledger's own key for this request: the decision record joins the ledger row on it.
    ikey = idempotency_key(request)
    # The contract must not change because the label did: refuse if the human side maps to another leg.
    from syndicate.features.shared.kalshi_orders import _side_to_kalshi

    if _side_to_kalshi(request.side, request.market, request.line) != leg:
        return {"placed": False, "reason": f"side_relabel_mismatch: {request.side}/{request.line} != {leg}",
                "idempotency_key": ikey}
    verdict = check_order(request, mode=LIVE, already={"dollars": spend["dollars"], "orders": spend["orders"]})
    checked = {"verdict": "pass" if verdict.get("allowed") else "fail", "reason": verdict.get("reason")}
    if not verdict.get("allowed"):
        return {"placed": False, "reason": verdict.get("reason"), "idempotency_key": ikey, "check_order": checked}
    submit = guarded_submit(ioc_submitter(kalshi_submitter(LivePrice(ask, leg))))
    try:
        record = place_order(request, submit=submit, mode=LIVE)
    except Exception as exc:  # noqa: BLE001 -- a raised send is kept as failed by the ledger
        return {"placed": False, "reason": f"{type(exc).__name__}: {exc}"[:200], "idempotency_key": ikey,
                "check_order": checked}
    if record.get("recorded") is False:
        return {"placed": False, "reason": str(record.get("reason") or record.get("error") or "build_refused"),
                "idempotency_key": ikey, "check_order": checked}
    return {"placed": True, "status": record.get("status"), "key": record.get("idempotency_key"),
            "idempotency_key": record.get("idempotency_key") or ikey, "check_order": checked}


# --------------------------------------------------------------------------- the decision record


def order_provenance(entry: Mapping[str, Any]) -> dict[str, str]:
    """What the ledger row carries about its decision, in the pregame fields (`OrderRequest`, todo #722)."""
    from syndicate.features.shared.inplay_entries_paper import FAIR_VERSION

    return {"staked_probability_version": f"inplay:{entry.get('fair_version') or FAIR_VERSION}",
            "sizing_basis": "inplay_one_contract" if order_dollars() is None else "inplay_order_dollars"}


def build_decision_record(entry: Mapping[str, Any], *, day: str, stake: float, cap: float, spend: Mapping[str, Any],
                          guards: Mapping[str, Any], result: Mapping[str, Any],
                          idempotency_key: str | None = None) -> dict[str, Any]:
    """ONE live in-play decision, placed or refused. PURE apart from reading the sizing env."""
    from syndicate.features.shared.inplay_entries_paper import FAIR_VERSION, rule_params

    ticker, leg, ask = str(entry["ticker"]), str(entry["leg"]), float(entry["ask"])
    sport = str(entry.get("sport") or "nhl")
    prov = order_provenance(entry)
    unit = ask + MAX_PRICE_MOVE
    return {
        "version": RECORD_VERSION,
        "decided_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "selected_date": day,
        "decision_id": entry.get("key"),  # the paper entry's key: <day>:<ticker>:<leg>
        "idempotency_key": idempotency_key,  # the ledger row's key; None when no order request was built
        "position_key": f"{POSITION_PREFIX}{ticker}:{leg}",
        "venue": "kalshi", "venue_ticker": ticker, "leg": leg, "sport": sport, "kind": entry.get("kind"),
        "line": entry.get("line"), "team": entry.get("team"),
        "game": _game_fields(entry),
        "fair": {"p": entry.get("fair"), "version": entry.get("fair_version") or FAIR_VERSION,
                 "n_books": entry.get("n_books"), "edge": entry.get("edge"), "fee": entry.get("fee"),
                 "since_score_s": entry.get("since_score_s"), "mid_move_60s": entry.get("mid_move_60s"),
                 "rule": rule_params(sport), "booked_at": entry.get("at")},
        "ask": ask,
        "guards": dict(guards),
        "sizing": {"version": SIZING_VERSION, "basis": prov["sizing_basis"], "order_dollars": order_dollars(),
                   "order_dollars_ceiling": ORDER_DOLLARS_CEILING, "stake": stake,
                   "contracts": max(1, round(stake / unit)) if unit > 0 else None,
                   "day_cap": cap, "day_cap_ceiling": DAY_DOLLARS_CEILING,
                   "day_spend_before": spend.get("dollars"), "day_orders_before": spend.get("orders")},
        "staked_probability_version": prov["staked_probability_version"],
        "result": dict(result),
    }


def records_path(day: str, root: Path | None = None) -> Path:
    """`<data root>/reports/intelligence/decision_records/<day>.inplay.jsonl`, beside the pregame records."""
    from syndicate.features.shared.decision_record import records_dir

    return records_dir(root) / f"{day}.inplay.jsonl"


def append_decision_record(day: str, record: Mapping[str, Any], root: Path | None = None) -> None:
    """Append one line. Never raises into the placer: the order has already been decided (or sent)."""
    try:
        path = records_path(day, root)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(dict(record), separators=(",", ":"), default=str) + "\n")
    except Exception as exc:  # noqa: BLE001
        print(f"[inplay_entries_live] DECISION_RECORD_WRITE_FAILED day={day} key={record.get('idempotency_key')}"
              f" error={type(exc).__name__}: {exc}"[:300], flush=True)


def read_decision_records(day: str, root: Path | None = None) -> list[dict[str, Any]]:
    """Every line of a day's in-play records, in write order. A torn line is skipped."""
    try:
        text = records_path(day, root).read_text(encoding="utf-8")
    except OSError:
        return []
    out = []
    for raw in text.splitlines():
        try:
            rec = json.loads(raw)
        except ValueError:
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


def records_by_idempotency_key(days: Sequence[str], root: Path | None = None) -> dict[str, dict[str, Any]]:
    """{ledger idempotency_key: record} over `days`: the join for settled in-play fills."""
    return {str(r["idempotency_key"]): r for d in days for r in read_decision_records(d, root)
            if r.get("idempotency_key")}
