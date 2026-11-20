"""HOLD-VALUE EXITS -- take profit only when selling beats holding (todo #856, lever L1).

Lane `hold-value-exits` (session ffd41dea). Pre-registration, load plan and 12-08
predictions: `.syndicate/findings_2026-11-20_hold_value_exits.md`.

WHY. Today's live take-profit (`execution_exits.evaluate_exit`, `take_profit`) sells
when the NET bid beats the position's ENTRY cost by a margin. The entry cost says
nothing about what the contract is worth NOW, and the live book's exits sold below
what holding paid: exit price minus settled outcome -2.10 pp [-5.88, +1.69] over
559 bets / 374 events, -3.74 [-8.73, +1.24] since 11-03, with exit fees at
2.45-2.65% of exited stake (`findings_2026-11-18_product_optimization_program.md`
s3.1 L1). Selling is worth it only when the net bid beats what holding is worth.

THE RULE, per position, per evaluation, after today's two rules are computed:

* HOLD VALUE -- the fair probability that our leg settles $1:
  - `consensus`: the executor's plan sighting for `<ticker>|<leg>`
    (`kalshi_maker_pilot._seen`: fair = P(price) x (1 + ev_pct/100), on market fair),
    only when its fair is set, it is at most `max_fair_age_seconds()` old, and the
    game has NOT started. In play the book consensus lags Kalshi (learnings
    2026-10-21), so it is never a hold value there;
  - else `venue_mid`: (our bid + our ask) / 2;
  - else `none`: unknown.
* WOULD EXIT iff `net - hold > exit fee per contract`. An unknown hold value never
  sells (an unknown must not default to the action).
* A `venue_mid` hold can never clear the bid (bid <= mid), so with no fresh pregame
  consensus the rule HOLDS. That is the design, stated before any data.

THE SWITCH, `SYNDICATE_EXIT_HOLD_VALUE`:
  absent / unrecognised -> `off`: today's decision, byte-identical (no key added);
  `shadow` -> today's decisions + the hold-value fields + the shadow log;
  `on`     -> `take_profit` survives only where the position would exit; a position
              it stops reads `hold_value_hold`. `model_fair` is untouched. The shadow
              log keeps running. `on` IS A BETTING CHANGE (a window, the user's call).

THE SHADOW LOG, `reports/intelligence/execution_exits_hold_value/shadow_<UTC date>.jsonl`:
every LIVE position on every exit tick, and PAPER positions only at their first
take-profit / would-exit state (a row per paper position per tick would be
~12 MB/day at 336 positions). `grade_shadow` grades it against settlement under the
rule pre-registered in the findings file (s2.3). It writes nothing anywhere else.
"""

from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

HV_OFF = "off"
HV_SHADOW = "shadow"
HV_ON = "on"

MODE_ENV = "SYNDICATE_EXIT_HOLD_VALUE"
MAX_FAIR_AGE_ENV = "SYNDICATE_EXIT_HOLD_VALUE_MAX_FAIR_AGE_SECONDS"
DEFAULT_MAX_FAIR_AGE_SECONDS = 1800.0

SOURCE_CONSENSUS = "consensus"
SOURCE_MID = "venue_mid"
SOURCE_NONE = "none"

REASON_HOLD = "hold_value_hold"
SHADOW_VERSION = 1
_RULE_TAKE_PROFIT = "take_profit"  # == execution_exits.RULE_TAKE_PROFIT (pinned by a test)
_KALSHI = "kalshi"

# (entry_key, today has take_profit, would exit) states already logged for a PAPER
# position in this process. A restart re-logs one row per state; the grader keeps the
# earliest row, so a duplicate is harmless.
_PAPER_LOGGED: set[tuple[str, bool, bool]] = set()


# --------------------------------------------------------------------------
# Switches
# --------------------------------------------------------------------------


def hold_value_mode() -> str:
    """`off` unless the switch says exactly `shadow` or `on`. A typo cannot reach `on`."""
    raw = str(os.environ.get(MODE_ENV) or "").strip().lower()
    if raw == HV_ON:
        return HV_ON
    if raw == HV_SHADOW:
        return HV_SHADOW
    return HV_OFF


def max_fair_age_seconds() -> float:
    """How old a plan sighting may be and still be the hold value. Unusable -> 1800."""
    try:
        value = float(str(os.environ.get(MAX_FAIR_AGE_ENV)).strip())
    except (TypeError, ValueError):
        return DEFAULT_MAX_FAIR_AGE_SECONDS
    if not math.isfinite(value) or value < 0:
        return DEFAULT_MAX_FAIR_AGE_SECONDS
    return value


# --------------------------------------------------------------------------
# The hold value
# --------------------------------------------------------------------------


def _as_float(value: Any) -> float | None:
    if isinstance(value, str):
        value = value.strip()
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _price(value: Any) -> float | None:
    parsed = _as_float(value)
    return parsed if parsed is not None and 0.0 < parsed < 1.0 else None


def consensus_sighting(ticker: str, leg: str) -> dict[str, Any] | None:
    """The executor's latest plan sighting of `<ticker>|<leg>`, or None. Never raises.

    Written by `kalshi_maker_pilot.note_plan_sighting` at the top of every live Kalshi
    plan pass (`pipeline/execute_portfolio`) while `SYNDICATE_KALSHI_MAKER_PILOT` is on;
    the exit tick runs earlier in the same tick, in the same process. If the pilot is
    switched off the sightings stop and every hold value falls to the venue mid; the
    tick summary's `by_source` makes that visible.
    """
    try:
        from syndicate.features.shared import kalshi_maker_pilot as pilot

        seen = getattr(pilot, "_seen", None)
        row = seen.get(f"{ticker}|{leg}") if isinstance(seen, Mapping) else None
        return dict(row) if isinstance(row, Mapping) else None
    except Exception:  # noqa: BLE001 -- a missing fair is a mid, never a failed tick
        return None


def leg_ask(market: Mapping[str, Any], leg: str) -> float | None:
    """Our leg's ask: the venue's own ask field when it gives one, else 1 - the other leg's bid."""
    own = _price(market.get(f"{leg}_ask_dollars"))
    if own is not None:
        return own
    other = "no" if leg == "yes" else "yes"
    other_bid = _price(market.get(f"{other}_bid_dollars"))
    return round(1.0 - other_bid, 6) if other_bid is not None else None


def assess(
    position: Any,
    market: Mapping[str, Any],
    *,
    bid: float,
    exit_fee: float,
    net: float,
    in_play: bool | None,
    now: datetime,
    today_rules: Sequence[str],
    sighting_fn: Callable[[str, str], Mapping[str, Any] | None] | None = None,
) -> dict[str, Any]:
    """Would the hold-value rule exit this position now? PURE given `sighting_fn`."""
    contracts = float(getattr(position, "contracts", 0) or 0)
    fee_pc = (float(exit_fee) / contracts) if contracts else 0.0
    ask = leg_ask(market, position.leg)
    mid = round((bid + ask) / 2.0, 6) if ask is not None and ask >= bid - 1e-9 else None

    fair = age = None
    if getattr(position, "family", _KALSHI) == _KALSHI:
        sighting = (sighting_fn or consensus_sighting)(position.ticker, position.leg)
        if sighting:
            fair = _price(sighting.get("fair"))
            at = _as_float(sighting.get("at"))
            if at is not None:
                age = round(now.timestamp() - at, 1)

    if fair is not None and age is not None and -60.0 <= age <= max_fair_age_seconds() and in_play is False:
        source, hold = SOURCE_CONSENSUS, fair
    elif mid is not None:
        source, hold = SOURCE_MID, mid
    else:
        source, hold = SOURCE_NONE, None

    edge = round(net - hold, 6) if hold is not None else None
    would = edge is not None and edge > fee_pc + 1e-9
    return {
        "today_rule": "+".join(today_rules) or None,
        "bid": bid,
        "ask": ask,
        "mid": mid,
        "exit_fee_per_contract": round(fee_pc, 6),
        "net": round(net, 6),
        "hold": hold,
        "source": source,
        "consensus_fair": fair,
        "consensus_age_s": age,
        "hv_edge": edge,
        "threshold": round(fee_pc, 6),
        "would_exit": would,
        "gated": False,
    }


def failed_assessment(today_rules: Sequence[str], exc: BaseException) -> dict[str, Any]:
    """What an assessment that raised reads as: an UNKNOWN hold value, so it never sells."""
    return {
        "today_rule": "+".join(today_rules) or None,
        "source": SOURCE_NONE,
        "hold": None,
        "would_exit": False,
        "gated": False,
        "error": f"{type(exc).__name__}: {exc}"[:200],
    }


def apply_gate(rules: Sequence[str], assessment: dict[str, Any]) -> tuple[list[str], bool]:
    """ON: drop `take_profit` where the position would not exit. Returns `(rules, gated)`."""
    kept = list(rules)
    if _RULE_TAKE_PROFIT in kept and not assessment.get("would_exit"):
        kept = [r for r in kept if r != _RULE_TAKE_PROFIT]
        assessment["gated"] = True
        return kept, True
    return kept, False


# --------------------------------------------------------------------------
# The shadow log
# --------------------------------------------------------------------------


def shadow_dir() -> Path:
    from syndicate.features.shared.refresh_state_store import reports_root

    return reports_root() / "intelligence" / "execution_exits_hold_value"


def _has_take_profit(rule: Any) -> bool:
    return _RULE_TAKE_PROFIT in str(rule or "").split("+")


class ShadowTick:
    """Collects one exit tick's hold-value rows and counts; `flush` writes them.

    With the switch off it is inert: `observe` does nothing and `flush` returns None,
    so the tick's summary and document are exactly today's.
    """

    def __init__(self, *, at: str, tick: str) -> None:
        self.mode = hold_value_mode()
        self.at = at
        self.tick = tick
        self.rows: list[dict[str, Any]] = []
        self.counts: dict[str, Any] = {
            "assessed": 0,
            "today_take_profit": 0,
            "would_exit": 0,
            "held": 0,
            "gated": 0,
            "by_source": {},
        }

    @property
    def active(self) -> bool:
        return self.mode != HV_OFF

    def observe(self, position: Any, decision: Mapping[str, Any]) -> None:
        if not self.active:
            return
        try:
            self._observe(position, decision)
        except Exception as exc:  # noqa: BLE001 -- a lost log row must never cost the tick
            self.counts["observe_errors"] = int(self.counts.get("observe_errors") or 0) + 1
            self.counts["last_observe_error"] = f"{type(exc).__name__}: {exc}"[:200]

    def _observe(self, position: Any, decision: Mapping[str, Any]) -> None:
        hv = decision.get("hold_value") if isinstance(decision.get("hold_value"), Mapping) else None
        today_rule = hv.get("today_rule") if hv else decision.get("rule")
        today_tp = _has_take_profit(today_rule)
        would = bool(hv and hv.get("would_exit"))
        if hv:
            c = self.counts
            c["assessed"] += 1
            c["by_source"][hv.get("source")] = c["by_source"].get(hv.get("source"), 0) + 1
            if today_tp:
                c["today_take_profit"] += 1
                c["held" if not would else "would_exit"] += 1
            elif would:
                c["would_exit"] += 1
            if hv.get("gated"):
                c["gated"] += 1
        live = str(getattr(position, "mode", "")) == "live"
        if not live:
            if not (today_tp or would):
                return
            state = (str(position.entry_key), today_tp, would)
            if state in _PAPER_LOGGED:
                return
            _PAPER_LOGGED.add(state)
        self.rows.append(self._row(position, decision, hv, today_rule))

    def _row(self, position: Any, decision: Mapping[str, Any], hv: Mapping[str, Any] | None, today_rule: Any) -> dict[str, Any]:
        hv = hv or {}
        return {
            "v": SHADOW_VERSION,
            "at": self.at,
            "tick": self.tick,
            "hv_mode": self.mode,
            "entry_key": position.entry_key,
            "entry_mode": position.mode,
            "family": position.family,
            "ticker": position.ticker,
            "leg": position.leg,
            "sport": position.sport,
            "market": position.market,
            "side": position.side,
            "line": position.line,
            "entry_phase": position.entry_phase,
            "selected_date": position.selected_date,
            "commence_time": position.commence_time,
            "contracts": position.contracts,
            "entry_price": position.entry_price,
            "entry_cost": decision.get("entry_cost_per_contract"),
            "in_play": decision.get("in_play"),
            "reason": decision.get("reason"),
            "today_rule": today_rule,
            "rule": decision.get("rule"),
            "bid": decision.get("bid"),
            "ask": hv.get("ask"),
            "mid": hv.get("mid"),
            "exit_fee_pc": hv.get("exit_fee_per_contract"),
            "net": hv.get("net", decision.get("net_per_contract")),
            "hold": hv.get("hold"),
            "hold_source": hv.get("source"),
            "consensus_fair": hv.get("consensus_fair"),
            "consensus_age_s": hv.get("consensus_age_s"),
            "hv_edge": hv.get("hv_edge"),
            "threshold": hv.get("threshold"),
            "would_exit": hv.get("would_exit") if hv else None,
            "gated": bool(hv.get("gated")) if hv else False,
        }

    def flush(self) -> dict[str, Any] | None:
        """Append this tick's rows. Never raises: the caller is the order-placing tick."""
        if not self.active:
            return None
        written, error = 0, None
        if self.rows:
            try:
                directory = shadow_dir()
                directory.mkdir(parents=True, exist_ok=True)
                with open(directory / f"shadow_{self.at[:10]}.jsonl", "a", encoding="utf-8") as handle:
                    handle.write("".join(json.dumps(r, sort_keys=True, default=str) + "\n" for r in self.rows))
                written = len(self.rows)
            except Exception as exc:  # noqa: BLE001 -- a lost log row must never cost a sale
                error = f"{type(exc).__name__}: {exc}"[:200]
        out = {"mode": self.mode, "rows": written, **self.counts}
        out["by_source"] = dict(sorted(self.counts["by_source"].items(), key=lambda kv: str(kv[0])))
        if error:
            out["write_error"] = error
        return out


# --------------------------------------------------------------------------
# Grading (pre-registered: findings_2026-11-20_hold_value_exits.md s2.3)
# --------------------------------------------------------------------------

_SETTLE = {"won": 1.0, "lost": 0.0}


def _central_date(stamp: Any) -> str | None:
    try:
        start = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    from zoneinfo import ZoneInfo

    return start.astimezone(ZoneInfo("America/Chicago")).date().isoformat()


def _event_of(order: Mapping[str, Any] | None, ticker: str) -> str:
    event = str((order or {}).get("event_id") or "").strip()
    if event:
        return event
    return ticker.rsplit("-", 1)[0] if "-" in ticker else ticker


def clustered_mean(values: Sequence[float], clusters: Sequence[str]) -> dict[str, Any]:
    """Unit-weight mean with an event-clustered SE (pass B's `clus`) and its 95% CI."""
    n = len(values)
    if not n:
        return {"n": 0, "events": 0, "mean": None, "se": None, "lo": None, "hi": None}
    m = sum(values) / n
    groups: dict[str, float] = {}
    for x, g in zip(values, clusters):
        groups[g] = groups.get(g, 0.0) + (x - m)
    g_count = len(groups)
    if g_count > 1:
        se = math.sqrt(sum(s * s for s in groups.values())) / n * math.sqrt(g_count / (g_count - 1))
    else:
        se = float("nan")
    lo = m - 1.96 * se if math.isfinite(se) else None
    hi = m + 1.96 * se if math.isfinite(se) else None
    return {
        "n": n,
        "events": g_count,
        "mean": round(m, 4),
        "se": round(se, 4) if math.isfinite(se) else None,
        "lo": round(lo, 4) if lo is not None else None,
        "hi": round(hi, 4) if hi is not None else None,
    }


def _first(rows: Sequence[Mapping[str, Any]], pred: Callable[[Mapping[str, Any]], bool]) -> Mapping[str, Any] | None:
    for row in rows:
        if pred(row):
            return row
    return None


def _arms(
    rows: Sequence[Mapping[str, Any]],
    outcome: str,
    would: Callable[[Mapping[str, Any]], bool],
) -> dict[str, Any] | None:
    """One entry's two arms under a would-exit predicate. None when today's rule never fired."""
    t1 = _first(rows, lambda r: _has_take_profit(r.get("today_rule")) and _as_float(r.get("net")) is not None)
    if t1 is None:
        return None
    t1_at = str(t1.get("at"))
    held_at_t1 = not would(t1)
    later = [r for r in rows if str(r.get("at")) >= t1_at]
    t2 = _first(
        later,
        lambda r: _has_take_profit(r.get("today_rule")) and would(r) and _as_float(r.get("net")) is not None,
    )
    value_today = float(t1["net"])
    value_new = float(t2["net"]) if t2 is not None else _SETTLE[outcome]
    return {
        "differ": held_at_t1,
        "value_today": value_today,
        "value_new": value_new,
        "emh_pp": round(100.0 * (value_today - value_new), 4),
        "t1": t1,
        "t2_at": t2.get("at") if t2 is not None else None,
        "observed_after_t1": any(str(r.get("at")) > t1_at for r in rows),
    }


def _would_registered(row: Mapping[str, Any]) -> bool:
    return bool(row.get("would_exit"))


def _would_break_even(row: Mapping[str, Any]) -> bool:
    edge = _as_float(row.get("hv_edge"))
    return edge is not None and edge > 1e-9


def _lodo(values: Sequence[float], dates: Sequence[str]) -> dict[str, float]:
    out: dict[str, float] = {}
    for d in sorted(set(dates)):
        kept = [v for v, dd in zip(values, dates) if dd != d]
        if kept:
            out[d] = round(sum(kept) / len(kept), 4)
    return out


def grade_shadow(
    rows: Iterable[Mapping[str, Any]],
    orders: Iterable[Mapping[str, Any]],
    exit_rows: Iterable[Mapping[str, Any]] = (),
    *,
    end_utc: str = "2026-12-07T05:59:59Z",
    last_game_date: str = "2026-12-06",
    min_events: int = 60,
    min_positions: int = 80,
) -> dict[str, Any]:
    """The pre-registered grade. PURE. See the findings file s2.3 for every definition."""
    order_by_key = {str(o.get("idempotency_key") or ""): o for o in orders if isinstance(o, Mapping)}
    window = sorted(
        (r for r in rows if isinstance(r, Mapping) and str(r.get("at") or "") <= end_utc and r.get("entry_key")),
        key=lambda r: (str(r.get("at")), str(r.get("tick") or "")),
    )
    start_utc = str(window[0]["at"]) if window else None

    # I1: the structural invariant.
    i1 = sum(1 for r in window if r.get("hold_source") == SOURCE_MID and r.get("would_exit"))

    by_entry: dict[str, list[Mapping[str, Any]]] = {}
    for r in window:
        by_entry.setdefault(str(r["entry_key"]), []).append(r)

    # I2: every live take-profit sale in the window has a shadow row at its tick.
    sales = [
        x for x in exit_rows
        if isinstance(x, Mapping) and x.get("mode") == "live" and _has_take_profit(x.get("rule"))
        and start_utc is not None and start_utc <= str(x.get("submitted_at") or "") <= end_utc
    ]
    seen_sales = 0
    for x in sales:
        sub = str(x.get("submitted_at"))
        try:
            floor = datetime.fromisoformat(sub.replace("Z", "+00:00")).timestamp() - 900
        except ValueError:
            continue
        for r in by_entry.get(str(x.get("entry_key")), []):
            try:
                ts = datetime.fromisoformat(str(r.get("at")).replace("Z", "+00:00")).timestamp()
            except ValueError:
                continue
            if _has_take_profit(r.get("today_rule")) and str(r.get("at")) <= sub and ts >= floor:
                seen_sales += 1
                break
    i2_share = (seen_sales / len(sales)) if sales else None

    def population(entry_mode_live: bool) -> dict[str, Any]:
        primary: list[dict[str, Any]] = []
        be: list[dict[str, Any]] = []
        fired = held = 0
        excluded: dict[str, int] = {}
        for key, entry_rows in by_entry.items():
            first = entry_rows[0]
            is_live = first.get("entry_mode") == "live"
            if is_live != entry_mode_live or first.get("family") != _KALSHI or first.get("entry_phase") != "pregame":
                continue
            game_date = _central_date(first.get("commence_time"))
            if game_date is None or game_date > last_game_date:
                excluded["game_after_window_or_undated"] = excluded.get("game_after_window_or_undated", 0) + 1
                continue
            order = order_by_key.get(key)
            outcome = str((order or {}).get("outcome") or "")
            t1 = _first(entry_rows, lambda r: _has_take_profit(r.get("today_rule")) and _as_float(r.get("net")) is not None)
            if t1 is None:
                continue
            fired += 1  # S1 counts every fired entry, graded or not
            if not _would_registered(t1):
                held += 1
            if outcome not in _SETTLE:
                reason = "no_ledger_row" if order is None else f"outcome_{outcome or 'ungraded'}"
                excluded[reason] = excluded.get(reason, 0) + 1
                continue
            arms = _arms(entry_rows, outcome, _would_registered)
            if arms is None:
                continue
            base = {
                "entry_key": key,
                "event": _event_of(order, str(first.get("ticker") or "")),
                "game_date": game_date,
                "contracts": float(first.get("contracts") or 0.0),
                "outcome": outcome,
            }
            if arms["differ"]:
                primary.append({**base, **{k: v for k, v in arms.items() if k != "t1"},
                                "t1_source": arms["t1"].get("hold_source"), "t1_in_play": arms["t1"].get("in_play")})
            arms_be = _arms(entry_rows, outcome, _would_break_even)
            if arms_be is not None and arms_be["differ"]:
                be.append({**base, "emh_pp": arms_be["emh_pp"]})
        return {"P": primary, "BE": be, "fired": fired, "held_at_t1": held, "excluded": excluded}

    live = population(True)
    paper = population(False)
    P = live["P"]
    values = [p["emh_pp"] for p in P]
    clusters = [p["event"] for p in P]
    headline = clustered_mean(values, clusters)
    lodo = _lodo(values, [p["game_date"] for p in P])

    # S2: contract-weighted mean.
    weight = sum(p["contracts"] for p in P)
    s2 = round(sum(p["emh_pp"] * p["contracts"] for p in P) / weight, 4) if weight else None
    # S5: splits at T1.
    s5: dict[str, Any] = {}
    for label, key in (("by_t1_source", "t1_source"), ("by_t1_in_play", "t1_in_play")):
        groups: dict[str, list[dict[str, Any]]] = {}
        for p in P:
            groups.setdefault(str(p.get(key)), []).append(p)
        s5[label] = {g: clustered_mean([x["emh_pp"] for x in xs], [x["event"] for x in xs]) for g, xs in sorted(groups.items())}
    # S6: actual live fills vs the shadow's net at T1.
    fills = {
        str(x.get("entry_key")): x for x in exit_rows
        if isinstance(x, Mapping) and x.get("mode") == "live" and x.get("status") == "filled"
    }
    s6_diffs = []
    for p in P:
        x = fills.get(p["entry_key"])
        fill = _as_float((x or {}).get("fill_price"))
        sold = _as_float((x or {}).get("filled_contracts"))
        fee = _as_float((x or {}).get("exit_fee_dollars")) or 0.0
        if fill is not None and sold:
            s6_diffs.append(100.0 * ((fill - fee / sold) - p["value_today"]))
    # S7: hold-source coverage over live pregame-entry assessed rows.
    s7: dict[str, int] = {}
    for r in window:
        if r.get("entry_mode") == "live" and r.get("entry_phase") == "pregame" and r.get("hold_source"):
            s7[str(r["hold_source"])] = s7.get(str(r["hold_source"]), 0) + 1
    # S8: consensus at T1, never observed afterwards.
    s8 = sum(1 for p in P if p.get("t1_source") == SOURCE_CONSENSUS and not p.get("observed_after_t1"))

    if i1 or (i2_share is not None and i2_share < 0.95):
        verdict = "INVALID"
    elif headline["events"] < min_events or headline["n"] < min_positions:
        verdict = "INSUFFICIENT"
    elif headline["mean"] is not None and headline["mean"] >= 0:
        verdict = "AGAINST"
    elif lodo and all(v < 0 for v in lodo.values()):
        verdict = "SUPPORT"
        verdict += " (STRONG)" if headline["hi"] is not None and headline["hi"] < 0 else " (WEAK: CI spans 0)"
    else:
        verdict = "INCONCLUSIVE"

    return {
        "verdict": verdict,
        "window": {"start_utc": start_utc, "end_utc": end_utc, "last_game_date": last_game_date, "rows": len(window)},
        "minimum_sample": {"events": min_events, "positions": min_positions},
        "instrument": {
            "I1_mid_rows_that_would_exit": i1,
            "I2_live_take_profit_sales": len(sales),
            "I2_sales_with_a_shadow_row": seen_sales,
            "I2_share": round(i2_share, 4) if i2_share is not None else None,
        },
        "primary": {
            "metric": "exit-minus-hold pp per contract, flat per position, over P (today sells at T1, the rule holds)",
            **headline,
            "lodo": lodo,
            "lodo_all_negative": bool(lodo) and all(v < 0 for v in lodo.values()),
        },
        "secondary": {
            "S1_first_take_profit_fires": live["fired"],
            "S1_held_at_t1": live["held_at_t1"],
            "S1_share_held": round(live["held_at_t1"] / live["fired"], 4) if live["fired"] else None,
            "S2_contract_weighted_mean": s2,
            "S3_paper": clustered_mean([p["emh_pp"] for p in paper["P"]], [p["event"] for p in paper["P"]]),
            "S4_break_even_variant": clustered_mean([p["emh_pp"] for p in live["BE"]], [p["event"] for p in live["BE"]]),
            "S5": s5,
            "S6_actual_fill_minus_shadow_net_pp": (
                {"n": len(s6_diffs), "mean": round(sum(s6_diffs) / len(s6_diffs), 4)} if s6_diffs else {"n": 0, "mean": None}
            ),
            "S7_live_pregame_rows_by_hold_source": dict(sorted(s7.items())),
            "S8_consensus_t1_unobserved_after": s8,
            "S8_flag": bool(P) and s8 > 0.10 * len(P),
        },
        "excluded": {"live": live["excluded"], "paper": paper["excluded"]},
        "positions": [{k: v for k, v in p.items() if k not in {"t1"}} for p in P],
    }


def read_shadow_rows(directory: Path | None = None) -> list[dict[str, Any]]:
    """Every row of every `shadow_*.jsonl` under `directory` (default: the fleet's)."""
    base = directory or shadow_dir()
    rows: list[dict[str, Any]] = []
    if not base.is_dir():
        return rows
    for path in sorted(base.glob("shadow_*.jsonl")):
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
    return rows
