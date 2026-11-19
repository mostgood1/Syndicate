"""Does the LIVE book have an edge? Measured at the price paid, net of fees, event-clustered.

    python scripts/live_book_edge_readout.py                      # read the fleet now; the gate reads the clock
    python scripts/live_book_edge_readout.py --as-of 2026-11-15   # windows ending that slate date
    python scripts/live_book_edge_readout.py --since 2026-11-03   # one window from a slate date instead
    python scripts/live_book_edge_readout.py --no-clock           # the gate reads the last 30 days
    python scripts/live_book_edge_readout.py --payload-json saved.json --json out.json

Lane `portfolio-edge-measurement`, todo #815. The user asked on 2026-11-16 "when can we start to increase
investments?" The `/portfolio` pivot shows a win rate, and a win rate is the wrong instrument: the book buys
mostly favourites and alt lines, so a 57% win rate can lose. This reads the same ledger the pivot reads
(`/api/portfolio/live?on=all&show=all`, the fleet, never the git mirror) and reports what decides scaling.

- **ROI net of fees, with an EVENT-CLUSTERED standard error.** Several bets on one game are one draw of that
  game, so they are not counted as independent (learnings 2026-08-20: row pooling overstated significance 3.4x).
- **Win rate against the BREAKEVEN win rate of the prices paid:** breakeven = fill probability × (1 + fee / stake).
  Excess wins = wins − Σ breakeven, z over Σ be(1 − be).
- **CLV gross AND net of the venue fee, per close scope.** Plus whether the close itself is calibrated on the
  sides this book picks: wins vs Σ close-implied, event-clustered. On 2026-11-16 gross same-book CLV read +1.32 pp,
  while fee-net was −0.30 ± 0.19 pp and the venue close overpriced our sides by 6.6 pp (z −2.94).
- **Stake quartiles and sizing paths.** A dollar ROI below the flat ROI means stake size is hurting. On 2026-11-16
  the top quartile was mostly the live $5-$10 stake band (10-20..11-02), a ~10x multiplier.
- **The scale-up gate, ADOPTED by the user 2026-11-16 ("Adopt as drafted")**
  (findings_2026-11-16_live_book_edge_readout.md). No live stake or cap rises until it passes.
- **The gate's clock** (user 2026-11-16: "Any betting change"): the gate reads the bets SUBMITTED after the last
  live-betting change LOADED on the fleet, from `.syndicate/betting_changes.md` (`scripts/betting_change.py`). While a
  change is pending its load the count is 0. The readout also counts deploys.md entries nothing has classified yet:
  any of them may be a later change, so a non-zero count means the clock may start later than shown. `--since` or
  `--no-clock` override it.

PINNED (2026-11-16 fleet payload, as of 2026-11-15, last 30 = 10-17..11-15): 1,526 bets / 641 events,
$3,006.48 staked, −$218.64, ROI −7.27 ± 2.84%, excess wins −32.5 (z −1.72). `tests/test_live_book_edge_readout.py`
reproduces it from that payload when `SYNDICATE_EDGE_READOUT_PAYLOAD` points at it. The repo is public, so the
payload is not committed.

Read-only: one GET to the fleet. Nothing is written except `--json`.
"""

from __future__ import annotations

import argparse
import collections
import json
import math
import sys
import urllib.request
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LIVE_PATH = "/api/portfolio/live?on=all&show=all"
SCOPE_SAME_BOOK = "same_book"

# The scale-up gate (ADOPTED by the user 2026-11-16, "Adopt as drafted"). Each number is in the findings file.
GATE_MIN_EVENTS = 800
GATE_CLOSE_CALIBRATION_Z = 2.0


@dataclass(frozen=True)
class Bet:
    """One decided live bet, in the units every figure below is computed in."""

    date: str
    event: str
    outcome: str  # won | lost | push
    stake: float
    pnl: float
    fees: float
    p: float  # fill price as a probability
    breakeven: float
    sport: str
    market: str
    venue: str
    path: str  # sizing_basis
    ev_pct: float | None
    scope: str | None  # close_book_scope of a resolved closing mark
    clv_gross: float | None  # probability points, recomputed from fill and close
    clv_net: float | None  # gross less the fee; None when the fee is unknown
    fee_pp: float | None
    close_implied: float | None
    submitted_at: str = ""  # when the order went to the venue; the gate's clock counts from it


def _as_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def bets_from_orders(orders: Iterable[Mapping[str, Any]]) -> list[Bet]:
    """Decided live positions with a usable stake and fill price.

    `is_position` is the `/portfolio` pivot's own predicate, so the counts here are the pivot's. A push counts in
    ROI (its stake and P&L are real) and not in win rate.
    """
    from syndicate.features.prediction_ledger import _clv_pct_from_prices, _implied_from_price
    from syndicate.features.shared.execution_ledger import _price_as_probability
    from syndicate.features.shared.order_clv import fee_net_clv_pct, fee_pp_for_order
    from syndicate.features.shared.portfolio_periods import is_position

    out: list[Bet] = []
    for order in orders:
        if not isinstance(order, Mapping) or not is_position(order):
            continue
        outcome = str(order.get("outcome") or "")
        if outcome not in ("won", "lost", "push"):
            continue
        stake = _as_float(order.get("fill_stake_dollars")) or 0.0
        p = _price_as_probability(order.get("fill_price"))
        if stake <= 0 or p is None or not 0.0 < p < 1.0:
            continue
        fees = _as_float(order.get("fees_dollars")) or 0.0
        # THE EXIT FEE TOO [2026-11-19, lane portfolio-monitor, hand-off L6 from product-optimization-program].
        # On a position the exit lane sold, `fees_dollars` holds the ENTRY fee only (558 of 560 exited rows on
        # 11-18); the exit fee is inside `pnl_dollars` but was missing here, so the fee, fee-% and "ROI before
        # fees" fields understated fees by 0.83-0.95 pp (ROI itself, from P&L, was right). `exit_applied` carries
        # both halves, so they are taken from it and nothing is counted twice.
        exit_applied = order.get("exit_applied") if isinstance(order.get("exit_applied"), Mapping) else None
        if exit_applied is not None:
            entry_fee = _as_float(exit_applied.get("entry_fee_dollars"))
            exit_fee = _as_float(exit_applied.get("exit_fee_dollars")) or 0.0
            fees = (entry_fee if entry_fee is not None else fees) + exit_fee
        mark = order.get("closing_mark") if isinstance(order.get("closing_mark"), Mapping) else {}
        scope = clv_gross = clv_net = fee_pp = close_implied = None
        if str(mark.get("reason") or "") == "resolved" and mark.get("close_price") is not None:
            # Absent scope is same-book (`order_clv._scope_of`). The gross is RECOMPUTED from the prices: live marks
            # stamped before todo #719 read a contract price as American odds.
            scope = str(mark.get("close_book_scope") or SCOPE_SAME_BOOK)
            clv_gross = _clv_pct_from_prices(order.get("fill_price"), mark.get("close_price"))
            clv_net = fee_net_clv_pct(order, clv_gross)
            fee_pp = fee_pp_for_order(order)
            close_implied = _implied_from_price(mark.get("close_price"))
        out.append(
            Bet(
                date=str(order.get("selected_date") or ""),
                event=str(order.get("event_id") or order.get("position_key") or order.get("idempotency_key") or ""),
                outcome=outcome,
                stake=stake,
                pnl=_as_float(order.get("pnl_dollars")) or 0.0,
                fees=fees,
                p=p,
                breakeven=min(0.999, p * (1.0 + fees / stake)),
                sport=str(order.get("sport") or ""),
                market=str(order.get("market") or ""),
                venue=str(order.get("venue") or ""),
                path=str(order.get("sizing_basis") or "none"),
                ev_pct=_as_float(order.get("ev_pct")),
                scope=scope,
                clv_gross=clv_gross,
                clv_net=clv_net,
                fee_pp=fee_pp,
                close_implied=close_implied,
                submitted_at=str(order.get("submitted_at") or ""),
            )
        )
    return out


def _clustered_mean(values_by_event: Mapping[str, Sequence[float]]) -> tuple[float | None, float | None, int]:
    """Mean over ROWS, with the SE clustered by event. (mean, se, events)."""
    flat = [v for vs in values_by_event.values() for v in vs]
    if not flat:
        return None, None, 0
    mean = sum(flat) / len(flat)
    resid = [sum(v - mean for v in vs) for vs in values_by_event.values()]
    se = math.sqrt(sum(r * r for r in resid)) / len(flat) if len(resid) > 1 else None
    return mean, se, len(values_by_event)


def summarize(bets: Sequence[Bet]) -> dict[str, Any] | None:
    """Dollar ROI (event-clustered SE), flat ROI, win rate vs breakeven, excess wins, fees."""
    if not bets:
        return None
    staked = sum(b.stake for b in bets)
    pnl = sum(b.pnl for b in bets)
    roi = pnl / staked
    by_event: dict[str, float] = collections.defaultdict(float)
    for b in bets:
        by_event[b.event] += b.pnl - roi * b.stake
    se = math.sqrt(sum(v * v for v in by_event.values())) / staked
    decided = [b for b in bets if b.outcome != "push"]
    wins = sum(1 for b in decided if b.outcome == "won")
    expected = sum(b.breakeven for b in decided)
    variance = sum(b.breakeven * (1 - b.breakeven) for b in decided)
    fees = sum(b.fees for b in bets)
    return {
        "bets": len(bets),
        "events": len(by_event),
        "staked": round(staked, 2),
        "pnl": round(pnl, 2),
        "roi_pct": round(100 * roi, 2),
        "roi_se_pct": round(100 * se, 2),
        "roi_lo95_pct": round(100 * (roi - 1.96 * se), 2),
        "roi_hi95_pct": round(100 * (roi + 1.96 * se), 2),
        "flat_roi_pct": round(100 * sum(b.pnl / b.stake for b in bets) / len(bets), 2),
        "win_pct": round(100 * wins / len(decided), 1) if decided else None,
        "breakeven_win_pct": round(100 * expected / len(decided), 1) if decided else None,
        "excess_wins": round(wins - expected, 1),
        "excess_z": round((wins - expected) / math.sqrt(variance), 2) if variance > 0 else None,
        "fees": round(fees, 2),
        "fee_pct_of_stake": round(100 * fees / staked, 2),
        "roi_before_fees_pct": round(100 * (pnl + fees) / staked, 2),
    }


def clv_summary(bets: Sequence[Bet]) -> dict[str, dict[str, Any]]:
    """Per close scope: gross CLV, fee, net CLV (clustered SE), and the close's calibration on our sides."""
    out: dict[str, dict[str, Any]] = {}
    scopes = sorted({b.scope for b in bets if b.scope and b.clv_gross is not None})
    for scope in scopes:
        rows = [b for b in bets if b.scope == scope and b.clv_gross is not None]
        gross: dict[str, list[float]] = collections.defaultdict(list)
        net: dict[str, list[float]] = collections.defaultdict(list)
        calib: dict[str, list[float]] = collections.defaultdict(list)
        fees: list[float] = []
        for b in rows:
            gross[b.event].append(b.clv_gross)
            if b.clv_net is not None:
                net[b.event].append(b.clv_net)
            if b.fee_pp is not None:
                fees.append(b.fee_pp)
            if b.outcome != "push" and b.close_implied is not None:
                calib[b.event].append((1.0 if b.outcome == "won" else 0.0) - b.close_implied)
        g_mean, g_se, _ = _clustered_mean(gross)
        n_mean, n_se, _ = _clustered_mean(net)
        c_mean, c_se, c_events = _clustered_mean(calib)
        out[scope] = {
            "bets": len(rows),
            "events": len(gross),
            "clv_gross_pp": _r(g_mean, 2),
            "clv_gross_se_pp": _r(g_se, 2),
            "beat_close_pct": round(100 * sum(1 for b in rows if b.clv_gross > 0) / len(rows), 1),
            "fee_pp": _r(sum(fees) / len(fees), 2) if fees else None,
            "clv_net_bets": sum(len(v) for v in net.values()),
            "clv_net_pp": _r(n_mean, 2),
            "clv_net_se_pp": _r(n_se, 2),
            # Positive = we won MORE than the close implied; a calibrated close is ~0 here.
            "wins_minus_close_pp": _r(100 * c_mean, 2) if c_mean is not None else None,
            "wins_minus_close_z": _r(c_mean / c_se, 2) if c_mean is not None and c_se else None,
            "calibration_events": c_events,
        }
    return out


def _r(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)


def stake_quartiles(bets: Sequence[Bet]) -> list[dict[str, Any]]:
    if len(bets) < 4:
        return []
    ordered = sorted(bets, key=lambda b: b.stake)
    total = sum(b.stake for b in bets)
    size = len(ordered) // 4
    out = []
    for i in range(4):
        chunk = ordered[i * size:(i + 1) * size if i < 3 else len(ordered)]
        s = summarize(chunk) or {}
        out.append({
            "quartile": f"Q{i + 1}",
            "stake_from": round(chunk[0].stake, 2),
            "stake_to": round(chunk[-1].stake, 2),
            "dollar_share_pct": round(100 * sum(b.stake for b in chunk) / total, 1),
            **s,
        })
    return out


def by_dimension(bets: Sequence[Bet], field: str, *, min_bets: int = 15) -> list[dict[str, Any]]:
    """Evidence for PER-LINE fixes only -- never a market or sport switch (learnings line 1056)."""
    groups: dict[str, list[Bet]] = collections.defaultdict(list)
    for b in bets:
        groups[str(getattr(b, field))].append(b)
    rows = [
        {field: key, **(summarize(group) or {})}
        for key, group in groups.items()
        if len(group) >= min_bets
    ]
    return sorted(rows, key=lambda r: -r.get("staked", 0))


def gate(bets: Sequence[Bet]) -> dict[str, Any]:
    """The ADOPTED scale-up gate's conditions over this window. A readout: no code acts on it."""
    s = summarize(bets) or {}
    clv = clv_summary(bets).get(SCOPE_SAME_BOOK) or {}
    quartiles = stake_quartiles(bets)
    conditions = []

    events = s.get("events", 0)
    conditions.append({
        "name": "1 enough independent events",
        "pass": events >= GATE_MIN_EVENTS,
        "reading": f"{events} events (need >= {GATE_MIN_EVENTS})",
    })
    lo95, excess = s.get("roi_lo95_pct"), s.get("excess_wins")
    conditions.append({
        "name": "2 results: ROI lower 95% bound > 0 and excess wins >= 0",
        "pass": lo95 is not None and lo95 > 0 and excess is not None and excess >= 0,
        "reading": f"ROI {s.get('roi_pct')} +- {s.get('roi_se_pct')}% (lower {lo95}%), excess wins {excess}",
    })
    net, calib_z = clv.get("clv_net_pp"), clv.get("wins_minus_close_z")
    roi = s.get("roi_pct")
    agrees = net is not None and roi is not None and (net > 0) == (roi > 0)
    calibrated = calib_z is not None and abs(calib_z) < GATE_CLOSE_CALIBRATION_Z
    conditions.append({
        "name": "3 instrument: fee-net same-book CLV agrees in sign with results, against a calibrated close",
        "pass": agrees and calibrated,
        "reading": (
            f"fee-net CLV {net} pp vs ROI {roi}%; close calibration "
            f"{clv.get('wins_minus_close_pp')} pp (z {calib_z}, need |z| < {GATE_CLOSE_CALIBRATION_Z})"
        ),
    })
    top = quartiles[-1] if quartiles else {}
    conditions.append({
        "name": "4 sizing earns its keep: top stake quartile ROI >= flat ROI",
        "pass": bool(top) and top.get("roi_pct") is not None and top["roi_pct"] >= s.get("flat_roi_pct", math.inf),
        "reading": f"Q4 ROI {top.get('roi_pct')}% vs flat ROI {s.get('flat_roi_pct')}%",
    })
    return {
        "status": "ADOPTED 2026-11-16 (user) -- a readout; no code acts on it",
        "all_pass": all(c["pass"] for c in conditions),
        "conditions": conditions,
        "note": "Condition 5 (step caps one at a time, step back below zero) is a procedure, not a reading.",
    }


def window_bets(bets: Sequence[Bet], start: str, end: str) -> list[Bet]:
    return [b for b in bets if start <= b.date <= end]


def default_windows(as_of: str) -> list[tuple[str, str, str]]:
    end = date.fromisoformat(as_of)
    return [
        ("last 7", (end - timedelta(days=6)).isoformat(), as_of),
        ("last 30", (end - timedelta(days=29)).isoformat(), as_of),
        ("month to date", end.replace(day=1).isoformat(), as_of),
        ("all", "0000-00-00", as_of),
    ]


def _utc(value: str | None) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    text = text[:-1] + "+00:00" if text.endswith("Z") else text
    head, dot, rest = text.partition(".")
    if dot:  # the venue stamps up to nanoseconds; fromisoformat takes microseconds
        digits = rest[: len(rest) - len(rest.lstrip("0123456789"))]  # the fraction only, not the offset
        text = f"{head}.{digits[:6]}{rest[len(digits):]}"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else None


def clock_bets(bets: Sequence[Bet], start: str) -> tuple[list[Bet], int]:
    """Bets submitted at or after `start`, and how many carry no readable submit time (they never count)."""
    since = _utc(start)
    if since is None:
        raise ValueError(f"clock start {start!r} is not a UTC instant")
    kept, unknown = [], 0
    for bet in bets:
        moment = _utc(bet.submitted_at)
        if moment is None:
            unknown += 1
        elif moment >= since:
            kept.append(bet)
    return kept, unknown


def build_report(
    orders: Iterable[Mapping[str, Any]],
    *,
    as_of: str | None = None,
    since: str | None = None,
    clock: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """`clock` (from `read_clock`: start, change_id, what, pending, unclassified) moves the gate onto the bets
    submitted after the last live-betting change. `since` wins over it."""
    bets = bets_from_orders(orders)
    if as_of is None:
        dates = sorted(b.date for b in bets if b.date)
        as_of = dates[-1] if dates else date.today().isoformat()
    windows = [("since " + since, since, as_of)] if since else default_windows(as_of)
    rows = [{"window": n, "from": a, "to": b, **(summarize(window_bets(bets, a, b)) or {})} for n, a, b in windows]
    clock_info = None
    if clock and not since:
        focus, unknown = clock_bets(bets, clock["start"])
        label, start, end = f"since {clock['change_id']}", clock["start"], "now"
        rows.append({"window": label, "from": start, "to": end, **(summarize(focus) or {})})
        clock_info = {
            **{k: clock.get(k) for k in ("start", "change_id", "what", "pending", "unclassified", "ledger")},
            "events": (summarize(focus) or {}).get("events", 0),
            "need": GATE_MIN_EVENTS,
            "bets_without_submit_time": unknown,
        }
    else:
        # The gate and the breakdowns read ONE window: --since, else the last 30 days.
        label, start, end = windows[0] if since else windows[1]
        focus = window_bets(bets, start, end)
    return {
        "as_of": as_of,
        "windows": rows,
        "clock": clock_info,
        "focus": {"window": label, "from": start, "to": end},
        "clv": clv_summary(focus),
        "stake_quartiles": stake_quartiles(focus),
        "by_path": by_dimension(focus, "path", min_bets=1),
        "by_venue": by_dimension(focus, "venue", min_bets=1),
        "by_sport": by_dimension(focus, "sport"),
        "by_market": by_dimension(focus, "market"),
        "gate": gate(focus),
    }


def fetch_live_orders(base_url: str | None = None, *, timeout: float = 120.0) -> tuple[list[dict[str, Any]], str]:
    """GET the fleet's live ledger. The token is resolved by `_base_url` and never printed."""
    scripts = str(ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    from _base_url import admin_token, default_base_url

    base = (base_url or default_base_url()).rstrip("/")
    token = admin_token(base)
    request = urllib.request.Request(base + LIVE_PATH, headers={"X-Admin-Token": token} if token else {})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read())
    return list(payload.get("orders") or []), base


def _fmt(s: Mapping[str, Any]) -> str:
    if not s.get("bets"):
        return "no decided bets"
    return (
        f"{s['bets']:5d} bets {s['events']:4d} ev ${s['staked']:9.2f} P&L {s['pnl']:+9.2f}"
        f"  ROI {s['roi_pct']:+6.2f} +- {s['roi_se_pct']:4.2f}%  flat {s['flat_roi_pct']:+6.2f}%"
        f"  win {s['win_pct']} vs be {s['breakeven_win_pct']}  excess {s['excess_wins']:+.1f} (z {s['excess_z']})"
        f"  fees ${s['fees']:.2f}"
    )


def render(report: Mapping[str, Any]) -> str:
    lines = [f"LIVE BOOK EDGE READOUT  as of slate {report['as_of']}  (ROI net of fees; +- = 1 event-clustered SE)"]
    for w in report["windows"]:
        lines.append(f"  {w['window']:14s} {w['from']}..{w['to']}  {_fmt(w)}")
    c = report.get("clock")
    if c:
        state = "PENDING a load, so the count is 0" if c.get("pending") else f"{c['events']} of {c['need']} events"
        lines.append(f"\nCLOCK (user 11-16: any betting change restarts it): {state}")
        lines.append(f"  starts {c['start']} at {c['change_id']}: {c['what']}")
        if c.get("unclassified"):
            lines.append(
                f"  WARNING: {c['unclassified']} deploys.md load(s) since coverage are unclassified -- the clock may start"
                " later. Run: python scripts/betting_change.py candidates"
            )
        if c.get("bets_without_submit_time"):
            lines.append(f"  {c['bets_without_submit_time']} decided bets carry no readable submitted_at (never counted)")
        if c.get("ledger"):
            lines.append(f"  ledger: {c['ledger']}")
    f = report["focus"]
    lines.append(f"\nFOCUS: {f['window']} ({f['from']}..{f['to']})")
    lines.append("  CLV by close scope (probability points):")
    for scope, c in report["clv"].items():
        lines.append(
            f"    {scope:22s} n={c['bets']:4d} gross {c['clv_gross_pp']:+.2f}  fee {c['fee_pp']}  "
            f"NET {c['clv_net_pp']} +- {c['clv_net_se_pp']} (n={c['clv_net_bets']})  "
            f"close calibration: wins - close-implied {c['wins_minus_close_pp']} pp (z {c['wins_minus_close_z']})"
        )
    lines.append("  Stake quartiles:")
    for q in report["stake_quartiles"]:
        lines.append(f"    {q['quartile']} ${q['stake_from']:.2f}-{q['stake_to']:.2f} ({q['dollar_share_pct']:4.1f}% of $)  {_fmt(q)}")
    for title, key in (("Sizing path", "by_path"), ("Venue", "by_venue")):
        lines.append(f"  {title}:")
        for row in report[key]:
            lines.append(f"    {row[key[3:]]:22s} {_fmt(row)}")
    lines.append("  Sport / market (>= 15 bets; evidence for per-LINE fixes, never a switch):")
    for key in ("by_sport", "by_market"):
        for row in report[key]:
            lines.append(f"    {row[key[3:]]:22s} {_fmt(row)}")
    g = report["gate"]
    lines.append(f"\nSCALE-UP GATE ({g['status']}): {'ALL PASS' if g['all_pass'] else 'NOT MET'}")
    for c in g["conditions"]:
        lines.append(f"  [{'pass' if c['pass'] else 'FAIL'}] {c['name']}: {c['reading']}")
    lines.append(f"  {g['note']}")
    return "\n".join(lines)


def _ledger_note() -> str:
    """Which checkout the register and deploys.md were read from, and whether origin/main is ahead (no fetch)."""
    import subprocess

    def git(*cmd: str) -> str:
        try:
            done = subprocess.run(["git", "-C", str(ROOT), *cmd], capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.SubprocessError):
            return ""
        return done.stdout.strip() if done.returncode == 0 else ""

    head = git("rev-parse", "--short", "HEAD")
    behind = git("rev-list", "--count", "HEAD..origin/main")
    note = f"{ROOT} at {head or '?'}"
    if behind and behind != "0":
        note += f"; origin/main is {behind} commit(s) ahead as last fetched -- pull before trusting the clock"
    return note


def read_clock(register: Path, deploys: Path) -> dict[str, Any] | None:
    """The gate's clock from the betting-change register, or None when there is no register or no change in it."""
    if not register.exists():
        print(f"no betting-change register at {register}: the gate reads the last 30 days", flush=True)
        return None
    scripts = str(ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import betting_change as bc

    changes, coverage = bc.parse_register(register.read_text(encoding="utf-8"))
    start = bc.clock_start(changes)
    if start is None:
        return None
    unclassified = None
    if coverage and deploys.exists():
        unclassified = len(bc.candidates(changes, deploys.read_text(encoding="utf-8"), coverage))
    return {
        "start": start.start,
        "change_id": start.change.id,
        "what": start.change.what,
        "pending": start.pending,
        "unclassified": unclassified,
        "ledger": _ledger_note(),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--payload-json", help="a saved /api/portfolio/live payload instead of reading the fleet")
    parser.add_argument("--base-url", help="default: scripts/_base_url.py (the fleet)")
    parser.add_argument("--as-of", help="last slate date in every window (default: the latest decided bet)")
    parser.add_argument("--since", help="one window from this slate date instead of the clock")
    parser.add_argument("--no-clock", action="store_true", help="the gate reads the last 30 days, not the clock")
    parser.add_argument("--register", default=str(ROOT / ".syndicate" / "betting_changes.md"))
    parser.add_argument("--deploys", default=str(ROOT / ".syndicate" / "deploys.md"))
    parser.add_argument("--json", help="also write the report as JSON here")
    args = parser.parse_args(argv)

    if args.payload_json:
        payload = json.loads(Path(args.payload_json).read_text(encoding="utf-8"))
        orders, source = list(payload.get("orders") or []), args.payload_json
    else:
        orders, source = fetch_live_orders(args.base_url)
    clock = None if (args.since or args.no_clock) else read_clock(Path(args.register), Path(args.deploys))
    report = build_report(orders, as_of=args.as_of, since=args.since, clock=clock)
    report["source"] = source
    report["orders_read"] = len(orders)
    print(f"source {source}: {len(orders)} live orders", flush=True)
    print(render(report), flush=True)
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
