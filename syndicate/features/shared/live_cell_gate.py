"""The per-cell live gate: a cell stops placing live money only on its OWN record, and earns it back on paper.

USER DECISION 2026-10-24 (relayed by the coordinator 332cb014, lane `live-cell-scorecard`): "Per-cell trip
only (C)" -- "Replace the one global stop with per-cell trips: a cell pauses only if its own record is
significantly negative or loses $75; all else stays live. Adds the missing re-arm."

WHAT IT REPLACES. `pipeline/portfolio_commit.live_ev_floor_stop_state`: ONE global stop over the 0% floor's
extras only, cumulative, with no re-arm ("until the key is removed"). It tripped 2026-10-24 03:56Z (103
settled, -19.2%) and, frozen, could never clear. With this gate on, that stop no longer gates the live
plans; every live row -- Suggested AND floor extras -- passes through its cell instead.

CELL = venue x sport x family x phase (`cell_key`), the scorecard's grain without the price bucket.

STATE, per cell, in `intelligence/live_cell_gate_state.json` (refresh-state store):
  armed   -> its live record SINCE `armed_since` (None = all of it) is read every evaluation. It TRIPS when
             EITHER >= TRIP_MIN_BETS settled bets on >= TRIP_MIN_GAMES games have a game-clustered CI90
             on flat ROI wholly below 0, OR its pnl since `armed_since` is <= -TRIP_LOSS_DOLLARS.
  tripped -> its PAPER TWIN since `tripped_at` (paper:<venue> and paper:<venue>:ladder, the books that
             record the same cell at the venue's price) is read. It RE-ARMS when >= REARM_MIN_BETS bets on
             >= REARM_MIN_GAMES games over >= REARM_MIN_DAYS days have a CI95 lower bound on flat ROI
             (net of fees: `pnl_dollars` is) above 0. Re-arming sets `armed_since` = now, so the old live
             record never re-trips it.
Every cell starts ARMED (option C). A cell with no state is armed with `armed_since` None.

ONE WRITER. Only `evaluate` writes, and only the refresh-worker's portfolio commit calls it (cached
EVAL_TTL_SECONDS). `allows` reads: the in-game path (live-odds-worker) may ask without evaluating.

FAIL CLOSED. An unreadable ledger or state (a read that did not return ok) makes every cell `unknown`, and
`allows` refuses it: no live row is placed on a gate that cannot read. A CONFIRMED-absent state file is not
unreadable -- it is the first run, every cell armed.

OFF unless `SYNDICATE_LIVE_CELL_GATE=on` (exact word). Off, nothing here runs and the global stop is
byte-identical.
"""

from __future__ import annotations

import os
import random
import re
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Sequence

MODE_ENV = "SYNDICATE_LIVE_CELL_GATE"
STATE_RELPATH = ("intelligence", "live_cell_gate_state.json")
STATE_VERSION = "live_cell_gate/1"

TRIP_MIN_BETS = 40
TRIP_MIN_GAMES = 15
TRIP_CI = 0.90
TRIP_LOSS_DOLLARS = 75.0
REARM_MIN_BETS = 150
REARM_MIN_GAMES = 40
REARM_MIN_DAYS = 14
REARM_CI = 0.95
RESAMPLES = 1000
SEED = 20261024
EVAL_TTL_SECONDS = 1800.0

LIVE_VENUES = ("kalshi", "polymarket")
SETTLED = ("won", "lost", "push")
REFUSAL = "live_cell_tripped"
REFUSAL_UNKNOWN = "live_cell_gate_unknown"

_CACHE: dict[str, Any] = {}


def enabled() -> bool:
    return str(os.environ.get(MODE_ENV) or "").strip().lower() == "on"


# --------------------------------------------------------------------------- classification
# The scorecard (`scripts/live_cell_scorecard.py`) imports these, so the gate and the report that
# justifies it can never disagree about which cell a bet is in.

KALSHI_SPORT = (
    ("KXWNBA", "wnba"), ("KXNBA", "nba"), ("KXMLB", "mlb"), ("KXNFL", "nfl"), ("KXNCAAF", "ncaaf"),
    ("KXNCAAB", "ncaab"), ("KXNHL", "nhl"), ("KXATP", "tennis"), ("KXWTA", "tennis"), ("KXITF", "tennis"),
    ("KXCOD", "esports"), ("KXMVE", "parlay"), ("KXMLS", "soccer"), ("KXBUNDESLIGA", "soccer"),
    ("KXEREDIVISIE", "soccer"), ("KXLALIGA", "soccer"), ("KXLIGUE1", "soccer"), ("KXSERIEA", "soccer"),
    ("KXEPL", "soccer"), ("KXUCL", "soccer"),
)
PM_FAMILY = {"aec": "h2h", "atc": "h2h", "asc": "spread", "tsc": "total", "astatc": "prop"}


def parse_ts(value: Any) -> datetime | None:
    text = str(value or "").replace("Z", "+00:00")
    text = re.sub(r"(\.\d{6})\d+", r"\1", text)  # venue timestamps carry nanoseconds
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _kalshi_sport_series(ticker: str) -> tuple[str, str]:
    series = ticker.split("-")[0].upper()
    for prefix, sport in KALSHI_SPORT:
        if series.startswith(prefix):
            return sport, series[len(prefix):]
    return "other", series


def family_of(r: Mapping[str, Any]) -> str:
    market = str(r.get("market") or "").lower()
    if market:
        if str(r.get("player_name") or "").strip() or market.startswith(("player_", "batter_", "pitcher_")) \
                or market in ("strikeouts", "outs", "receptions"):
            return "prop"
        for key, fam in (("total", "total"), ("spread", "spread"), ("h2h", "h2h")):
            if key in market:
                return fam
        return "other"
    ticker = str(r.get("venue_ticker") or "")
    if r.get("venue") == "polymarket" or ticker[:3] in ("aec", "atc", "asc", "tsc", "ast"):
        return PM_FAMILY.get(ticker.split("-")[0].lower(), "other")
    sport, rest = _kalshi_sport_series(ticker)
    if sport == "parlay":
        return "parlay"
    if rest in ("GAME", "MATCH", "WMATCH", "DOUBLES") or rest.endswith("GAME"):
        return "h2h"
    if "SPREAD" in rest:
        return "spread"
    if "TOTAL" in rest:
        return "total"
    return "prop" if rest else "other"


def sport_of(r: Mapping[str, Any]) -> str:
    sport = str(r.get("sport") or "").lower().strip()
    if sport and sport != "none":
        return sport
    ticker = str(r.get("venue_ticker") or "")
    if ticker.upper().startswith("KX"):
        return _kalshi_sport_series(ticker)[0]
    parts = ticker.split("-")
    return parts[1].lower() if len(parts) > 1 else "?"


def game_of(r: Mapping[str, Any]) -> str:
    if r.get("event_id"):
        return str(r["event_id"])
    ticker = str(r.get("venue_ticker") or "")
    parts = ticker.split("-")
    if ticker.upper().startswith("KX") and len(parts) > 1:
        return "k:" + parts[1]  # date+teams token, shared by every series on the game
    m = re.match(r"^[a-z]+-(.+?-\d{4}-\d{2}-\d{2})", ticker)
    return "p:" + (m.group(1) if m else ticker)


def phase_of(r: Mapping[str, Any]) -> str:
    venue = str(r.get("venue"))
    if venue in LIVE_VENUES:
        # Live phase is the PATH that placed the order: the in-game entry path stamps no ev_pct.
        return "in_game" if r.get("source") != "venue_rebuild" and r.get("ev_pct") is None else "pregame"
    sub, ko = parse_ts(r.get("submitted_at")), parse_ts(r.get("commence_time"))
    return "in_game" if sub and ko and sub >= ko else "pregame"


def cell_key(venue: str, sport: str, family: str, phase: str) -> str:
    return f"{venue}|{sport}|{family}|{phase}"


def cell_of_order(order: Mapping[str, Any]) -> str:
    venue = str(order.get("venue") or "")
    base = venue.split(":")[1] if venue.startswith("paper:") else venue
    return cell_key(base, sport_of(order), family_of(order), phase_of(order))


def cell_of_row(row: Mapping[str, Any], venue: str, phase: str = "pregame") -> str:
    """A plan row's cell. The pregame live plans place pregame only (in-play rows are refused upstream)."""
    return cell_key(venue, sport_of(row), family_of(row), phase)


# --------------------------------------------------------------------------- statistics

def flat_ci(bets: Sequence[Mapping[str, Any]], level: float, reps: int = RESAMPLES, seed: int = SEED) -> tuple[float, float] | None:
    """Game-clustered bootstrap percentile CI on flat ROI (mean of pnl/stake). None below 2 games."""
    by_game: dict[str, list[float]] = defaultdict(list)
    for b in bets:
        by_game[b["game"]].append(b["ret"])
    games = list(by_game.values())
    if len(games) < 2:
        return None
    rng = random.Random(seed)
    means = []
    for _ in range(reps):
        total, n = 0.0, 0
        for _g in range(len(games)):
            g = games[rng.randrange(len(games))]
            total += sum(g)
            n += len(g)
        means.append(total / n)
    means.sort()
    lo = means[int(reps * (1 - level) / 2)]
    hi = means[int(reps * (1 + level) / 2) - 1]
    return lo, hi


def _bet(order: Mapping[str, Any]) -> dict[str, Any] | None:
    if order.get("status") != "filled" or order.get("outcome") not in SETTLED:
        return None
    try:
        stake = float(order.get("fill_stake_dollars") or 0.0)
        pnl = float(order.get("pnl_dollars"))
    except (TypeError, ValueError):
        return None
    if stake <= 0:
        return None
    return {"cell": cell_of_order(order), "game": game_of(order), "stake": stake, "pnl": pnl, "ret": pnl / stake,
            "submitted_at": parse_ts(order.get("submitted_at")), "date": str(order.get("selected_date") or ""),
            "key": (str(order.get("venue")), order.get("position_key") or order.get("idempotency_key"))}


def _summary(bets: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    n = len(bets)
    return {"n": n, "games": len({b["game"] for b in bets}), "pnl": round(sum(b["pnl"] for b in bets), 2),
            "roi_flat": round(100 * sum(b["ret"] for b in bets) / n, 2) if n else None}


def trip_verdict(bets: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    """The trip, or None. Loss first (cheap); the CI only once its preconditions hold."""
    s = _summary(bets)
    if s["n"] and s["pnl"] <= -TRIP_LOSS_DOLLARS:
        return {**s, "reason": "loss", "ci90": None}
    if s["n"] >= TRIP_MIN_BETS and s["games"] >= TRIP_MIN_GAMES and s["roi_flat"] < 0:
        ci = flat_ci(bets, TRIP_CI)
        if ci is not None and ci[1] < 0:
            return {**s, "reason": "ci90_below_zero", "ci90": [round(100 * ci[0], 1), round(100 * ci[1], 1)]}
    return None


def rearm_verdict(bets: Sequence[Mapping[str, Any]], tripped_at: datetime, now: datetime) -> dict[str, Any] | None:
    s = _summary(bets)
    days = (now - tripped_at).total_seconds() / 86400.0
    if s["n"] < REARM_MIN_BETS or s["games"] < REARM_MIN_GAMES or days < REARM_MIN_DAYS or s["roi_flat"] <= 0:
        return None
    ci = flat_ci(bets, REARM_CI)
    if ci is None or ci[0] <= 0:
        return None
    return {**s, "days": round(days, 1), "ci95": [round(100 * ci[0], 1), round(100 * ci[1], 1)]}


# --------------------------------------------------------------------------- evaluation

def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def evaluate(orders: Iterable[Mapping[str, Any]], state: Mapping[str, Any] | None, now: datetime) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """(new state, events). Pure: no I/O. `state` None = first run, every cell armed."""
    cells: dict[str, dict[str, Any]] = {k: dict(v) for k, v in ((state or {}).get("cells") or {}).items()}
    live: dict[str, list[dict]] = defaultdict(list)
    twin: dict[str, list[dict]] = defaultdict(list)
    seen_twin: set = set()
    for order in sorted(orders, key=lambda o: str(o.get("submitted_at") or "")):
        venue = str(order.get("venue") or "")
        bet = _bet(order)
        if bet is None:
            continue
        if venue in LIVE_VENUES:
            live[bet["cell"]].append(bet)
        elif venue.startswith("paper:") and venue.split(":")[1] in LIVE_VENUES and (
                venue.count(":") == 1 or venue.endswith(":ladder")):
            if bet["key"] in seen_twin:
                continue
            seen_twin.add(bet["key"])
            twin[bet["cell"]].append(bet)
    events: list[dict[str, Any]] = []
    for cell in sorted(set(live) | set(cells)):
        entry = cells.get(cell) or {"status": "armed", "armed_since": None}
        if entry.get("status") == "tripped":
            tripped_at = parse_ts(entry.get("tripped_at")) or now
            fresh = [b for b in twin.get(cell, ()) if b["submitted_at"] and b["submitted_at"] >= tripped_at]
            verdict = rearm_verdict(fresh, tripped_at, now)
            entry["twin"] = _summary(fresh)
            if verdict is not None:
                entry = {"status": "armed", "armed_since": _iso(now), "rearmed": verdict,
                         "previous_trip": {k: entry.get(k) for k in ("tripped_at", "trip")}}
                events.append({"event": "CELL_REARM", "cell": cell, **verdict})
        else:
            since = parse_ts(entry.get("armed_since"))
            bets = [b for b in live.get(cell, ()) if since is None or (b["submitted_at"] and b["submitted_at"] >= since)]
            verdict = trip_verdict(bets)
            entry["live"] = _summary(bets)
            if verdict is not None:
                entry = {"status": "tripped", "tripped_at": _iso(now), "trip": verdict,
                         "armed_since": entry.get("armed_since")}
                events.append({"event": "CELL_TRIP", "cell": cell, **verdict})
        cells[cell] = entry
    return {"version": STATE_VERSION, "evaluated_at": _iso(now), "cells": cells}, events


def _state_path():
    from syndicate.features.shared.refresh_state_store import reports_root

    return reports_root().joinpath(*STATE_RELPATH)


def _read_state() -> tuple[dict | None, bool]:
    from syndicate.features.shared.refresh_state_store import read_json_file_result

    return read_json_file_result(_state_path())[:2]


def _read_orders() -> list | None:
    from syndicate.features.shared import execution_ledger
    from syndicate.features.shared.refresh_state_store import read_json_file_result

    if read_json_file_result(execution_ledger._ledger_path())[1] is not True:
        return None
    return execution_ledger.full_history_orders()


def _log(line: str) -> None:
    print(f"[live_cell_gate] {line}", flush=True)


def refresh(*, force: bool = False, now: datetime | None = None, orders_fn=None, read_state_fn=None,
            write_state_fn=None) -> dict[str, Any]:
    """Evaluate (cached EVAL_TTL_SECONDS) and persist. Returns {"cells":..., "unknown": reason|None}."""
    clock = time.time()
    cached = _CACHE.get("state")
    if cached is not None and not force and clock - float(_CACHE.get("at") or 0) < EVAL_TTL_SECONDS:
        return cached
    now = now or datetime.now(timezone.utc)
    result: dict[str, Any]
    try:
        state, ok = (read_state_fn or _read_state)()
        if ok is not True:
            raise RuntimeError("state read not ok")
        orders = (orders_fn or _read_orders)()
        if orders is None:
            raise RuntimeError("ledger live document read not ok")
        new_state, events = evaluate(orders, state, now)
        for e in events:
            detail = " ".join(f"{k}={v}" for k, v in e.items() if k not in ("event", "cell"))
            _log(f"{e['event']} cell={e['cell']} {detail}")
        if write_state_fn is not None:
            write_state_fn(new_state)
        else:
            from syndicate.features.shared.refresh_state_store import write_json_file

            write_json_file(_state_path(), new_state)
        tripped = sorted(c for c, v in new_state["cells"].items() if v.get("status") == "tripped")
        _log(f"LIVE_CELL_GATE cells={len(new_state['cells'])} tripped={len(tripped)} events={len(events)} "
             f"tripped_cells={tripped}"[:900])
        result = {"cells": new_state["cells"], "unknown": None}
    except Exception as exc:
        reason = f"{type(exc).__name__}: {exc}"[:160]
        _log(f"CELL_GATE_UNKNOWN error={reason} -- every cell refuses until the gate can read (fail closed)")
        result = {"cells": {}, "unknown": reason}
    _CACHE.update({"state": result, "at": clock})
    return result


def allows(cell: str, gate: Mapping[str, Any] | None = None) -> tuple[bool, str | None]:
    """(allowed, refusal). Reads the last evaluation; never evaluates. Unknown refuses (fail closed)."""
    gate = gate if gate is not None else _CACHE.get("state") or _read_only_gate()
    if gate.get("unknown"):
        return False, REFUSAL_UNKNOWN
    entry = (gate.get("cells") or {}).get(cell)
    if entry and entry.get("status") == "tripped":
        return False, REFUSAL
    return True, None


#: How old the persisted evaluation may be before a READ-ONLY consumer treats the gate as unknown. The refresh-worker
#: re-evaluates on every portfolio commit with live plans (cached EVAL_TTL_SECONDS), many times an hour on a slate.
READ_ONLY_MAX_AGE_SECONDS = 3 * 3600.0


def _read_only_gate(*, now: datetime | None = None, read_state_fn=None) -> dict[str, Any]:
    """For a process that does not evaluate (the in-game path): the persisted state, FAIL CLOSED.

    ABSENT IS NOT "ALL ARMED" HERE [2026-10-25, raised by lane in-game-trading 4 min after the first fleet up]. For the
    evaluator a confirmed-absent state is its first run. For a reader it means the evaluator has not reached the state
    -- never run, or not since READ_ONLY_MAX_AGE_SECONDS -- and reading that as "every cell armed" would make the gate
    silently inert while looking on. So absent, undated or stale -> unknown -> `allows` refuses.
    """
    try:
        state, ok = (read_state_fn or _read_state)()
        if ok is not True:
            return {"cells": {}, "unknown": "state read not ok"}
        if not state:
            return {"cells": {}, "unknown": "state absent (the refresh-worker has not evaluated)"}
        evaluated = parse_ts(state.get("evaluated_at"))
        age = None if evaluated is None else ((now or datetime.now(timezone.utc)) - evaluated).total_seconds()
        if age is None or age > READ_ONLY_MAX_AGE_SECONDS:
            return {"cells": {}, "unknown": f"state stale (evaluated_at={state.get('evaluated_at')})"}
        return {"cells": state.get("cells") or {}, "unknown": None}
    except Exception as exc:
        return {"cells": {}, "unknown": f"{type(exc).__name__}: {exc}"[:160]}


def filter_rows(rows: Sequence[Mapping[str, Any]], *, venue: str, gate: Mapping[str, Any]) -> tuple[list, dict[str, int]]:
    """The rows whose cell is armed, and refusal counts (the plan's `sum(refusals) + positions` contract)."""
    kept: list = []
    refused: dict[str, int] = defaultdict(int)
    for row in rows or ():
        ok, reason = allows(cell_of_row(row, venue), gate)
        if ok:
            kept.append(row)
        else:
            refused[reason] += 1
    return kept, dict(refused)


def reset_cache() -> None:
    """Tests only."""
    _CACHE.clear()
