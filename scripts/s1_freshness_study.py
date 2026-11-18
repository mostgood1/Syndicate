"""Study S1 of the profit learning program: do picks lose because the reference price they beat was STALE?

Lane `s1-freshness-study` (2026-11-18). Plan: `.syndicate/plan_2026-11-18_profit_learning_program.md`, study S1.
Pre-registration and results: `.syndicate/findings_2026-11-18_s1_freshness_study.md`. READ-ONLY.

It reuses Test B's instrument (`scripts/pinnacle_edge_deciles.py`, lane `live-cell-scorecard`, not modified here):
- `capture_age` / `heartbeat_dates`: the age of OUR copy of a reference quote at submit, read from the F0 fetch
  heartbeat (one line per fetch, live from ~18:36Z 2026-10-25). An order with no such heartbeat reads None
  (unknown), never fresh or stale.
- `load_quotes` / `join_order` / `contract_price` (exploratory venue-move section only).

DEFINITIONS (frozen in the pre-registration)
- Population: settled (won / lost / push), filled, staked orders at a venue (live kalshi / polymarket,
  paper:<venue>, paper:<venue>:ladder) with an event_id, PREGAME (live_cell_gate.phase_of == pregame AND
  submitted_at < commence_time). Paper rows deduplicated per (venue, position_key) keeping the first submit
  (live_cell_scorecard's rule); a live row is a real fill and is never deduplicated.
- Primary reference age `pin_age_s`: capture_age with key `pinnacle_events` -- seconds from the last fetch at or
  before submit that SAW Pinnacle on the event, to submit.
- Secondary reference age `cons_age_s`: the same over heartbeats that carry at least one non-venue book (a
  sportsbook fetch, the consensus's source), key `events`. A venue-only capture (books = kalshi / polymarket)
  never refreshes the consensus, so it does not count.
- ROI: flat, fee-net -- mean of pnl_dollars / fill_stake_dollars (pnl_dollars is net of fees on every book).
- Interval: event-clustered (cluster = live_cell_gate.game_of, the event_id), linearised SE, +-1.96 SE. For a
  difference of two means over overlapping sets (fresh is a subset of all) each cluster's influence is
  sum_F (r - m_F) / n_F - sum_A (r - m_A) / n_A, and Var = sum over clusters of its square.
- FIT: submitted < 2026-11-08T00:00Z. TEST: 2026-11-08T00:00Z <= submitted < 2026-11-18T00:00Z.
- N from {1, 2, 5, 10, 15} min: maximise flat ROI(fresh) - flat ROI(stale) on FIT, among N leaving >= 100 orders
  and >= 30 events on each side; ties go to the smaller N.
- PRIMARY: on TEST, D = ROI(fresh-only, age <= N) - ROI(all with a readable age). SURVIVES iff D > 0 and the 95%
  interval's lower bound > 0; otherwise FALSIFIED.

    # FLEET (WSL, fleet venv, refresh-worker env, nice 19). --quotes adds the exploratory venue-move join (slow).
    python scripts/live_cell_scorecard.py dump --out /mnt/c/tmp/s1fresh/ledger.json
    python scripts/s1_freshness_study.py join --ledger /mnt/c/tmp/s1fresh/ledger.json --out /mnt/c/tmp/s1fresh/rows.json [--quotes]
    # anywhere: coverage prints counts only (no outcome); report prints counts and percentages, never dollars
    py -3 scripts/s1_freshness_study.py coverage --rows C:/tmp/s1fresh/rows.json
    py -3 scripts/s1_freshness_study.py report --rows C:/tmp/s1fresh/rows.json [--out-md PATH] [--out-json PATH]
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import pinnacle_edge_deciles as pe  # noqa: E402
from syndicate.features.shared.live_cell_gate import family_of, game_of, parse_ts, phase_of  # noqa: E402

FIT_END = "2026-11-08T00:00:00Z"
TEST_END = "2026-11-18T00:00:00Z"
N_GRID_MIN = (1, 2, 5, 10, 15)
MIN_SIDE_ORDERS = 100
MIN_SIDE_EVENTS = 30
Z95 = 1.96
SETTLED = ("won", "lost", "push")
GRADIENT = ((60.0, "0-1m"), (120.0, "1-2m"), (300.0, "2-5m"), (900.0, "5-15m"), (3600.0, "15-60m"),
            (float("inf"), ">60m"))
BOOTSTRAP_REPS = 2000
BOOTSTRAP_SEED = 20261118


# --------------------------------------------------------------------------- population

def _num(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def drop_reason(order: Mapping[str, Any]) -> str | None:
    """Why an order is outside the population, or None when it is in. Pure."""
    venue = str(order.get("venue"))
    if venue not in pe.BOOKS:
        return "venue"
    if order.get("status") != "filled":
        return "not_filled"
    if order.get("outcome") not in SETTLED:
        return "unsettled"
    stake = _num(order.get("fill_stake_dollars"))
    if not stake or stake <= 0 or _num(order.get("pnl_dollars")) is None:
        return "no_stake_or_pnl"
    if not order.get("event_id"):
        return "no_event"
    sub, ko = parse_ts(order.get("submitted_at")), parse_ts(order.get("commence_time"))
    if sub is None or ko is None:
        return "no_times"
    if sub >= ko or phase_of(order) != "pregame":
        return "in_game"
    return None


def population(orders: Iterable[Mapping[str, Any]]) -> tuple[list[Mapping[str, Any]], dict[str, int]]:
    """The pregame settled venue population, paper deduplicated per (venue, position_key), first submit kept."""
    drops: Counter = Counter()
    kept: list[Mapping[str, Any]] = []
    seen: set = set()
    for order in sorted((o for o in orders if isinstance(o, Mapping)), key=lambda o: str(o.get("submitted_at") or "")):
        reason = drop_reason(order)
        if reason is not None:
            if reason != "venue":
                drops[f"{pe.BOOKS[str(order.get('venue'))]}:{reason}"] += 1
            continue
        book = pe.BOOKS[str(order["venue"])]
        if book != "live":
            key = (str(order["venue"]), order.get("position_key") or order.get("opening_key") or order.get("idempotency_key"))
            if key in seen:
                drops[f"{book}:duplicate_position"] += 1
                continue
            seen.add(key)
        kept.append(order)
    return kept, dict(sorted(drops.items()))


# --------------------------------------------------------------------------- reference age (Test B's reader)

def sportsbook_beat(beat: Mapping[str, Any]) -> bool:
    """A fetch that carried at least one non-venue book: the consensus's source, not a venue-only capture."""
    return bool({str(b).lower() for b in (beat.get("books") or ())} - pe.SELF_VENUES)


def index_beats(beats: Mapping[tuple, list]) -> dict[tuple, dict[str, dict[str, list]]]:
    """(sport, day) -> {"pin": event -> beats listing it as a Pinnacle event, "cons": event -> sportsbook beats
    listing it}. capture_age skips every line that does not list the event, so handing it only those lines is the
    same answer, minus a scan of every fetch of the day per order."""
    out: dict[tuple, dict[str, dict[str, list]]] = {}
    for key, lines in beats.items():
        pin: dict[str, list] = defaultdict(list)
        cons: dict[str, list] = defaultdict(list)
        for beat in lines:
            for event in beat.get("pinnacle_events") or ():
                pin[str(event)].append(beat)
            if sportsbook_beat(beat):
                for event in beat.get("events") or ():
                    cons[str(event)].append(beat)
        out[key] = {"pin": pin, "cons": cons}
    return out


def reference_ages(order: Mapping[str, Any], indexed: Mapping[tuple, Mapping[str, Mapping[str, list]]]) -> dict[str, Any]:
    sport, event = str(order.get("sport") or "").lower(), str(order.get("event_id") or "")
    days = sorted(pe.heartbeat_dates(order))
    pin = [b for d in days for b in (indexed.get((sport, d)) or {}).get("pin", {}).get(event, [])]
    cons = [b for d in days for b in (indexed.get((sport, d)) or {}).get("cons", {}).get(event, [])]
    return {"pin_age_s": pe.capture_age(order, pin, key="pinnacle_events"),
            "cons_age_s": pe.capture_age(order, cons, key="events")}


# --------------------------------------------------------------------------- exploratory: the venue's own move

def _last_price(series: Sequence[tuple], at: datetime, book: str, selection: str, line: Any) -> float | None:
    price = None
    for captured, _updated, bk, sel, ln, raw in series:
        if captured is None or captured > at:
            break
        if bk == book and sel == selection and ln == line:
            price = pe.contract_price(raw)
    return price


def venue_move(order: Mapping[str, Any], series: Sequence[tuple], ref_at: datetime | None,
               ref_fair: float | None) -> dict[str, Any]:
    """Did OUR venue's logged quote on our side move toward or away from the reference fair between the reference
    fetch (ref_at) and submit? EXPLORATORY. toward / away / flat / no_venue_quote / no_reference."""
    sub = parse_ts(order.get("submitted_at"))
    if sub is None or ref_at is None or ref_fair is None:
        return {"move": "no_reference"}
    venue = "kalshi" if "kalshi" in str(order.get("venue")) else "polymarket"
    side, line = str(order.get("side") or "").lower(), pe._line(order.get("line"))
    v0 = _last_price(series, ref_at, venue, side, line)
    v1 = _last_price(series, sub, venue, side, line)
    if v0 is None or v1 is None:
        return {"move": "no_venue_quote"}
    if abs(v1 - v0) < 1e-9:
        return {"move": "flat", "v0": v0, "v1": v1}
    toward = (v1 - v0) * (ref_fair - v0) > 0
    return {"move": "toward" if toward else "away", "v0": v0, "v1": v1}


# --------------------------------------------------------------------------- rows

def study_row(order: Mapping[str, Any], ages: Mapping[str, Any], move: Mapping[str, Any] | None = None) -> dict[str, Any]:
    stake, pnl = float(order["fill_stake_dollars"]), float(order["pnl_dollars"])
    sub = parse_ts(order.get("submitted_at"))
    return {"book": pe.BOOKS[str(order["venue"])], "venue": "kalshi" if "kalshi" in str(order["venue"]) else "polymarket",
            "sport": str(order.get("sport") or "").lower(), "family": family_of(order), "game": game_of(order),
            "submitted": sub.isoformat() if sub else None, "day": sub.date().isoformat() if sub else None,
            "outcome": order.get("outcome"), "stake": stake, "pnl": pnl, "ret": pnl / stake,
            "fees": _num(order.get("fees_dollars")) or 0.0, "ev_pct": _num(order.get("ev_pct")),
            "pin_age_s": ages.get("pin_age_s"), "cons_age_s": ages.get("cons_age_s"),
            "move": (move or {}).get("move")}


def window_of(row: Mapping[str, Any], first_beat: str | None) -> str:
    sub = parse_ts(row.get("submitted"))
    if sub is None:
        return "none"
    if first_beat and sub < parse_ts(first_beat):
        return "pre_heartbeat"
    if sub < parse_ts(FIT_END):
        return "FIT"
    if sub < parse_ts(TEST_END):
        return "TEST"
    return "after_TEST"


# --------------------------------------------------------------------------- statistics

def flat(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Flat fee-net ROI with its event-clustered SE and 95% interval, in percent."""
    n = len(rows)
    if not n:
        return {"n": 0, "events": 0, "roi": None, "se": None, "lo": None, "hi": None}
    mean = sum(r["ret"] for r in rows) / n
    resid: dict[str, float] = defaultdict(float)
    for r in rows:
        resid[r["game"]] += r["ret"] - mean
    se = math.sqrt(sum(v * v for v in resid.values())) / n if len(resid) > 1 else None
    return {"n": n, "events": len(resid), "roi": 100 * mean, "se": None if se is None else 100 * se,
            "lo": None if se is None else 100 * (mean - Z95 * se), "hi": None if se is None else 100 * (mean + Z95 * se)}


def clustered_diff(xs: Sequence[Mapping[str, Any]], ys: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """mean(xs) - mean(ys) in percent, event-clustered; xs and ys may overlap (linearised influence per cluster)."""
    if not xs or not ys:
        return {"d": None, "se": None, "lo": None, "hi": None}
    mx = sum(r["ret"] for r in xs) / len(xs)
    my = sum(r["ret"] for r in ys) / len(ys)
    u: dict[str, float] = defaultdict(float)
    for r in xs:
        u[r["game"]] += (r["ret"] - mx) / len(xs)
    for r in ys:
        u[r["game"]] -= (r["ret"] - my) / len(ys)
    se = math.sqrt(sum(v * v for v in u.values())) if len(u) > 1 else None
    d = mx - my
    return {"d": 100 * d, "se": None if se is None else 100 * se,
            "lo": None if se is None else 100 * (d - Z95 * se), "hi": None if se is None else 100 * (d + Z95 * se)}


def bootstrap_diff(fresh_flags: Sequence[tuple[str, float, bool]], reps: int = BOOTSTRAP_REPS,
                   seed: int = BOOTSTRAP_SEED) -> tuple[float, float] | None:
    """Seeded event-cluster bootstrap 95% percentile interval of mean(fresh) - mean(all). A CHECK, not the
    registered interval. Input: (game, ret, is_fresh)."""
    by_game: dict[str, list[tuple[float, bool]]] = defaultdict(list)
    for game, ret, fresh in fresh_flags:
        by_game[game].append((ret, fresh))
    games = [(sum(r for r, _ in g), len(g), sum(r for r, f in g if f), sum(1 for _, f in g if f))
             for g in by_game.values()]
    if len(games) < 2:
        return None
    rng = random.Random(seed)
    out = []
    for _ in range(reps):
        ta = na = tf = nf = 0.0
        for _g in range(len(games)):
            a, b, c, d = games[rng.randrange(len(games))]
            ta, na, tf, nf = ta + a, na + b, tf + c, nf + d
        if na and nf:
            out.append(100 * (tf / nf - ta / na))
    out.sort()
    if not out:
        return None
    return out[int(len(out) * 0.025)], out[int(len(out) * 0.975) - 1]


def fresh_split(rows: Sequence[Mapping[str, Any]], key: str, n_min: int) -> tuple[list, list]:
    fresh = [r for r in rows if r.get(key) is not None and r[key] <= 60.0 * n_min]
    stale = [r for r in rows if r.get(key) is not None and r[key] > 60.0 * n_min]
    return fresh, stale


def fit_n(rows: Sequence[Mapping[str, Any]], key: str) -> dict[str, Any]:
    """The FIT step: fresh - stale flat ROI per candidate N, and the chosen N (None when no N qualifies)."""
    table, chosen, best = [], None, None
    for n_min in N_GRID_MIN:
        fresh, stale = fresh_split(rows, key, n_min)
        f, s = flat(fresh), flat(stale)
        ok = (f["n"] >= MIN_SIDE_ORDERS and s["n"] >= MIN_SIDE_ORDERS
              and f["events"] >= MIN_SIDE_EVENTS and s["events"] >= MIN_SIDE_EVENTS)
        diff = clustered_diff(fresh, stale)
        table.append({"n_min": n_min, "fresh": f, "stale": s, "diff": diff, "qualifies": ok})
        if ok and diff["d"] is not None and (best is None or diff["d"] > best):
            best, chosen = diff["d"], n_min
    return {"key": key, "table": table, "chosen_n_min": chosen}


def test_n(rows: Sequence[Mapping[str, Any]], key: str, n_min: int | None) -> dict[str, Any]:
    """The TEST step: fresh-only vs all (both among rows with a readable age) and the registered verdict."""
    readable = [r for r in rows if r.get(key) is not None]
    out: dict[str, Any] = {"key": key, "n_min": n_min, "all": flat(readable)}
    if n_min is None:
        return {**out, "verdict": "NOT TESTABLE (no N qualified on FIT)"}
    fresh, stale = fresh_split(readable, key, n_min)
    diff = clustered_diff(fresh, readable)
    fresh_ids = {id(r) for r in fresh}
    boot = bootstrap_diff([(r["game"], r["ret"], id(r) in fresh_ids) for r in readable]) if fresh else None
    survives = diff["d"] is not None and diff["lo"] is not None and diff["d"] > 0 and diff["lo"] > 0
    return {**out, "fresh": flat(fresh), "stale": flat(stale), "diff": diff,
            "fresh_minus_stale": clustered_diff(fresh, stale), "bootstrap_check": boot,
            "fresh_share_pct": 100 * len(fresh) / len(readable) if readable else None,
            "verdict": "SURVIVES" if survives else "FALSIFIED"}


def bucket_of(age_s: float | None) -> str:
    return "unknown" if age_s is None else next(name for limit, name in GRADIENT if age_s <= limit)


def gradient(rows: Sequence[Mapping[str, Any]], key: str) -> dict[str, Any]:
    groups: dict[str, list] = defaultdict(list)
    for r in rows:
        groups[bucket_of(r.get(key))].append(r)
    order = [name for _, name in GRADIENT] + ["unknown"]
    return {name: flat(groups.get(name, [])) for name in order}


def ev_mean(rows: Sequence[Mapping[str, Any]]) -> float | None:
    evs = [r["ev_pct"] for r in rows if r.get("ev_pct") is not None]
    return sum(evs) / len(evs) if evs else None


def dollar_roi_pct(rows: Sequence[Mapping[str, Any]]) -> float | None:
    staked = sum(r["stake"] for r in rows)
    return 100 * sum(r["pnl"] for r in rows) / staked if staked else None


SLICES = (("live", lambda r: r["book"] == "live"), ("paper (twin + ladder)", lambda r: r["book"] in ("paper", "ladder")),
          ("paper twin", lambda r: r["book"] == "paper"), ("ladder", lambda r: r["book"] == "ladder"),
          ("kalshi", lambda r: r["venue"] == "kalshi"), ("polymarket", lambda r: r["venue"] == "polymarket"))


def report(rows: Sequence[Mapping[str, Any]], meta: Mapping[str, Any]) -> dict[str, Any]:
    first_beat = meta.get("first_heartbeat_at")
    win: dict[str, list] = defaultdict(list)
    for r in rows:
        win[window_of(r, first_beat)].append(r)
    fit_rows, test_rows = win["FIT"], win["TEST"]
    out: dict[str, Any] = {"windows": {k: len(v) for k, v in sorted(win.items())}}
    for arm, key in (("primary", "pin_age_s"), ("secondary", "cons_age_s")):
        fit = fit_n(fit_rows, key)
        test = test_n(test_rows, key, fit["chosen_n_min"])
        slices = {}
        if fit["chosen_n_min"] is not None:
            for name, pred in SLICES:
                part = [r for r in test_rows if pred(r)]
                slices[name] = test_n(part, key, fit["chosen_n_min"])
        readable_test = [r for r in test_rows if r.get(key) is not None]
        fresh = fresh_split(readable_test, key, fit["chosen_n_min"])[0] if fit["chosen_n_min"] else []
        out[arm] = {"fit": fit, "test": test, "test_slices": slices,
                    "gradient": {"TEST": gradient(test_rows, key), "FIT": gradient(fit_rows, key),
                                 "FIT+TEST": gradient(fit_rows + test_rows, key)},
                    "diagnostics": {"ev_mean_all": ev_mean(readable_test), "ev_mean_fresh": ev_mean(fresh),
                                    "dollar_roi_all_pct": dollar_roi_pct(readable_test),
                                    "dollar_roi_fresh_pct": dollar_roi_pct(fresh)}}
    moves: dict[str, Any] = {}
    for label, part in (("TEST", test_rows), ("FIT+TEST", fit_rows + test_rows)):
        groups: dict[str, list] = defaultdict(list)
        for r in part:
            if r.get("pin_age_s") is not None:
                groups[r.get("move") or "not_joined"].append(r)
        moves[label] = {k: flat(v) for k, v in sorted(groups.items())}
    out["exploratory_venue_move"] = moves
    return out


# --------------------------------------------------------------------------- coverage (counts only, no outcome)

def _dates_summary(days: Iterable[str]) -> dict[str, Any]:
    ds = sorted({d for d in days if d})
    if not ds:
        return {"dates": 0, "first": None, "last": None, "gaps": []}
    first, last = date.fromisoformat(ds[0]), date.fromisoformat(ds[-1])
    have = set(ds)
    gaps = [(first + timedelta(days=i)).isoformat() for i in range((last - first).days + 1)
            if (first + timedelta(days=i)).isoformat() not in have]
    return {"dates": len(ds), "first": ds[0], "last": ds[-1], "gaps": gaps}


def coverage(rows: Sequence[Mapping[str, Any]], meta: Mapping[str, Any]) -> dict[str, Any]:
    first_beat = meta.get("first_heartbeat_at")
    order_days = {r["day"] for r in rows}
    beat_days = {d for days in (meta.get("heartbeat_days") or {}).values() for d in days}
    shard_days = {d for days in (meta.get("shard_days") or {}).values() for d in days}
    readable = {r["day"] for r in rows if r.get("pin_age_s") is not None}
    fam = {"orders (pregame settled population, submit UTC date)": _dates_summary(order_days),
           "fetch heartbeat (any sport, shard date)": _dates_summary(beat_days),
           "orders with a readable Pinnacle capture age": _dates_summary(readable)}
    if shard_days:
        fam["book_quotes shards read (exploratory)"] = _dates_summary(shard_days)
    inter = order_days & beat_days & (shard_days or beat_days)
    counts: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        w = window_of(r, first_beat)
        c = counts[f"{w}|{r['book']}|{r['venue']}"]
        c["n"] += 1
        c["pin_known"] += r.get("pin_age_s") is not None
        c["cons_known"] += r.get("cons_age_s") is not None
        c["move_joined"] += r.get("move") in ("toward", "away", "flat")
    sports: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        if window_of(r, first_beat) in ("FIT", "TEST"):
            s = sports[r["sport"]]
            s["n"] += 1
            s["pin_known"] += r.get("pin_age_s") is not None
            s["cons_known"] += r.get("cons_age_s") is not None
    ages: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        w = window_of(r, first_beat)
        if w in ("FIT", "TEST"):
            ages[f"{w}|pin"][bucket_of(r.get("pin_age_s"))] += 1
            ages[f"{w}|cons"][bucket_of(r.get("cons_age_s"))] += 1
    fresh_n: dict[str, dict[int, Counter]] = defaultdict(lambda: defaultdict(Counter))
    for r in rows:
        w = window_of(r, first_beat)
        if w not in ("FIT", "TEST"):
            continue
        for key in ("pin_age_s", "cons_age_s"):
            if r.get(key) is None:
                continue
            for n_min in N_GRID_MIN:
                side = "fresh" if r[key] <= 60.0 * n_min else "stale"
                fresh_n[f"{w}|{key}"][n_min][side] += 1
    events: dict[str, dict[int, dict[str, set]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(set)))
    for r in rows:
        w = window_of(r, first_beat)
        if w in ("FIT", "TEST") and r.get("pin_age_s") is not None:
            for n_min in N_GRID_MIN:
                events[w][n_min]["fresh" if r["pin_age_s"] <= 60.0 * n_min else "stale"].add(r["game"])
    return {"families": fam, "intersection_dates": len(inter),
            "intersection": _dates_summary(inter), "first_heartbeat_at": first_beat,
            "by_window_book_venue": {k: dict(v) for k, v in sorted(counts.items())},
            "by_sport_fit_test": {k: dict(v) for k, v in sorted(sports.items())},
            "age_buckets": {k: dict(v) for k, v in sorted(ages.items())},
            "fresh_stale_counts": {k: {n: dict(c) for n, c in v.items()} for k, v in sorted(fresh_n.items())},
            "pin_fresh_stale_events": {w: {n: {s: len(g) for s, g in d.items()} for n, d in v.items()}
                                       for w, v in sorted(events.items())},
            "drops": meta.get("drops")}


# --------------------------------------------------------------------------- rendering (counts and % only)

def _pct(v: float | None, digits: int = 2) -> str:
    return "n/a" if v is None else f"{v:+.{digits}f}"


def _ci(s: Mapping[str, Any]) -> str:
    return "n/a" if s.get("lo") is None else f"[{s['lo']:+.2f}, {s['hi']:+.2f}]"


def _flat_cells(s: Mapping[str, Any]) -> str:
    return f"{s['n']} / {s['events']} | {_pct(s['roi'])}% | {_ci(s)}"


def render_coverage(cov: Mapping[str, Any]) -> str:
    lines = ["# S1 coverage (counts only)", "", "| family | dates | first | last | gaps |", "|---|---|---|---|---|"]
    for name, s in cov["families"].items():
        lines.append(f"| {name} | {s['dates']} | {s['first']} | {s['last']} | {', '.join(s['gaps']) or 'none'} |")
    i = cov["intersection"]
    lines += ["", f"Intersection of the families: {i['dates']} dates ({i['first']}..{i['last']}); first heartbeat "
              f"{cov['first_heartbeat_at']}", "", "| window / book / venue | n | Pinnacle age known | consensus age known |"
              " venue move joined |", "|---|---|---|---|---|"]
    for k, c in cov["by_window_book_venue"].items():
        lines.append(f"| {k} | {c.get('n', 0)} | {c.get('pin_known', 0)} | {c.get('cons_known', 0)} | {c.get('move_joined', 0)} |")
    lines += ["", "| sport (FIT+TEST) | n | Pinnacle age known | consensus age known |", "|---|---|---|---|"]
    for k, c in cov["by_sport_fit_test"].items():
        lines.append(f"| {k} | {c.get('n', 0)} | {c.get('pin_known', 0)} | {c.get('cons_known', 0)} |")
    buckets = [name for _, name in GRADIENT] + ["unknown"]
    lines += ["", "| window / age | " + " | ".join(buckets) + " |", "|---" * (len(buckets) + 1) + "|"]
    for k, c in cov["age_buckets"].items():
        lines.append(f"| {k} | " + " | ".join(str(c.get(b, 0)) for b in buckets) + " |")
    lines += ["", "| window / age key | " + " | ".join(f"N={n} fresh/stale" for n in N_GRID_MIN) + " |",
              "|---" * (len(N_GRID_MIN) + 1) + "|"]
    for k, v in cov["fresh_stale_counts"].items():
        lines.append(f"| {k} | " + " | ".join(f"{v.get(n, {}).get('fresh', 0)}/{v.get(n, {}).get('stale', 0)}"
                                               for n in N_GRID_MIN) + " |")
    lines += ["", "| window, Pinnacle age | " + " | ".join(f"N={n} fresh/stale events" for n in N_GRID_MIN) + " |",
              "|---" * (len(N_GRID_MIN) + 1) + "|"]
    for w, v in cov["pin_fresh_stale_events"].items():
        lines.append(f"| {w} | " + " | ".join(f"{v.get(n, {}).get('fresh', 0)}/{v.get(n, {}).get('stale', 0)}"
                                              for n in N_GRID_MIN) + " |")
    lines += ["", f"drops: {cov['drops']}"]
    return "\n".join(lines)


def render_report(rep: Mapping[str, Any]) -> str:
    lines = ["# S1 report (flat fee-net ROI per bet, %, event-clustered 95%)", "", f"windows: {rep['windows']}", ""]
    for arm in ("primary", "secondary"):
        a = rep[arm]
        fit, test = a["fit"], a["test"]
        lines += [f"## {arm} ({fit['key']})", "", "### FIT: choose N", "",
                  "| N min | fresh n / events | fresh ROI | stale n / events | stale ROI | fresh - stale [95%] | qualifies |",
                  "|---|---|---|---|---|---|---|"]
        for t in fit["table"]:
            f, s, d = t["fresh"], t["stale"], t["diff"]
            lines.append(f"| {t['n_min']} | {f['n']} / {f['events']} | {_pct(f['roi'])}% | {s['n']} / {s['events']} |"
                         f" {_pct(s['roi'])}% | {_pct(d['d'])} {_ci(d)} | {t['qualifies']} |")
        lines += ["", f"chosen N = {fit['chosen_n_min']} min", "", "### TEST", ""]
        if test.get("fresh") is None:
            lines += [f"verdict: {test['verdict']}", ""]
            continue
        d, fs = test["diff"], test["fresh_minus_stale"]
        boot = test["bootstrap_check"]
        lines += ["| set | n / events | ROI | 95% |", "|---|---|---|---|",
                  f"| all (readable age) | {_flat_cells(test['all'])} |", f"| fresh-only | {_flat_cells(test['fresh'])} |",
                  f"| stale | {_flat_cells(test['stale'])} |", "",
                  f"**D = fresh-only - all: {_pct(d['d'])} pp {_ci(d)} (se {_pct(d['se'])})** -- verdict **{test['verdict']}**",
                  f"fresh - stale: {_pct(fs['d'])} pp {_ci(fs)}; fresh share {_pct(test['fresh_share_pct'], 1)}%; "
                  f"bootstrap check of D (seeded, not registered): "
                  f"{'n/a' if not boot else f'[{boot[0]:+.2f}, {boot[1]:+.2f}]'}", "",
                  "| TEST slice | all n / events | all ROI | fresh n / events | fresh ROI | D [95%] |",
                  "|---|---|---|---|---|---|"]
        for name, s in a["test_slices"].items():
            if s.get("fresh") is None:
                lines.append(f"| {name} | {s['all']['n']} / {s['all']['events']} | {_pct(s['all']['roi'])}% | n/a | n/a | n/a |")
                continue
            lines.append(f"| {name} | {s['all']['n']} / {s['all']['events']} | {_pct(s['all']['roi'])}% |"
                         f" {s['fresh']['n']} / {s['fresh']['events']} | {_pct(s['fresh']['roi'])}% |"
                         f" {_pct(s['diff']['d'])} {_ci(s['diff'])} |")
        g = a["gradient"]
        lines += ["", "| age bucket | TEST n / ev | TEST ROI [95%] | FIT n / ev | FIT ROI [95%] | FIT+TEST n / ev | FIT+TEST ROI [95%] |",
                  "|---|---|---|---|---|---|---|"]
        for b in g["TEST"]:
            cells = []
            for w in ("TEST", "FIT", "FIT+TEST"):
                s = g[w][b]
                cells.append(f"{s['n']} / {s['events']} | {_pct(s['roi'])}% {_ci(s)}")
            lines.append(f"| {b} | " + " | ".join(cells) + " |")
        dg = a["diagnostics"]
        lines += ["", f"diagnostics (TEST): mean ev_pct all {_pct(dg['ev_mean_all'])} vs fresh {_pct(dg['ev_mean_fresh'])}; "
                  f"dollar ROI all {_pct(dg['dollar_roi_all_pct'])}% vs fresh {_pct(dg['dollar_roi_fresh_pct'])}%", ""]
    lines += ["## EXPLORATORY: the venue's own quote between the reference fetch and submit (rows with a Pinnacle age)", "",
              "| window | move | n / events | ROI | 95% |", "|---|---|---|---|---|"]
    for w, groups in rep["exploratory_venue_move"].items():
        for k, s in groups.items():
            lines.append(f"| {w} | {k} | {_flat_cells(s)} |")
    return "\n".join(lines)


# --------------------------------------------------------------------------- commands

def cmd_join(args) -> int:
    try:
        os.nice(19)
    except (AttributeError, OSError):
        pass
    raw = json.loads(Path(args.ledger).read_text(encoding="utf-8"))
    orders, drops = population(raw.get("orders", []) if isinstance(raw, Mapping) else raw)
    beats = pe.load_heartbeats(orders)
    indexed = index_beats(beats)
    stamps = [parse_ts(b.get("captured_at")) for lines in beats.values() for b in lines]
    stamps = [s for s in stamps if s is not None]
    meta: dict[str, Any] = {"drops": drops, "first_heartbeat_at": min(stamps).isoformat() if stamps else None,
                            "heartbeat_days": {}, "shard_days": {}}
    for (sport, day), lines in sorted(beats.items()):
        if lines:
            meta["heartbeat_days"].setdefault(sport, []).append(day)
    ages = [reference_ages(o, indexed) for o in orders]
    moves: list[dict | None] = [None] * len(orders)
    if args.quotes:
        from syndicate.features.shared.odds_book_quotes import kickoff_shard_date, resolve_book_quotes_path

        want = [i for i, a in enumerate(ages) if a["pin_age_s"] is not None and str(orders[i].get("side") or "").lower() in pe.OPPOSITE]
        subset = [orders[i] for i in want]
        for o in subset:
            ko = parse_ts(o.get("commence_time"))
            for day in {kickoff_shard_date({"commence_time": o.get("commence_time")}), ko.date().isoformat() if ko else None} - {None}:
                sport = str(o["sport"]).lower()
                if day not in meta["shard_days"].get(sport, []) and resolve_book_quotes_path(sport, day).is_file():
                    meta["shard_days"].setdefault(sport, []).append(day)
        quotes = pe.load_quotes(subset)
        for i in want:
            o = orders[i]
            joined = pe.join_order(o, quotes)
            ref = joined.get("at_submit") or joined.get("cons_submit")
            sub = parse_ts(o.get("submitted_at"))
            ref_at = sub - timedelta(seconds=ages[i]["pin_age_s"]) if sub else None
            series = quotes.get(pe.quote_key(o.get("event_id"), o.get("market"), o.get("segment"), o.get("player_name"))) or []
            moves[i] = venue_move(o, series, ref_at, ref["fair"] if ref else None)
    rows = [study_row(o, a, m) for o, a, m in zip(orders, ages, moves)]
    Path(args.out).write_text(json.dumps({"meta": meta, "rows": rows}), encoding="utf-8")
    print(f"S1_JOIN orders={len(orders)} pin_known={sum(a['pin_age_s'] is not None for a in ages)} "
          f"cons_known={sum(a['cons_age_s'] is not None for a in ages)} "
          f"move_joined={sum(1 for m in moves if m and m.get('move') in ('toward', 'away', 'flat'))} "
          f"heartbeat_files={sum(1 for v in beats.values() if v)} -> {args.out}", flush=True)
    return 0


def _load_rows(path: str) -> tuple[list[dict], dict]:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    return doc["rows"], doc["meta"]


def cmd_coverage(args) -> int:
    rows, meta = _load_rows(args.rows)
    sys.stdout.write(render_coverage(coverage(rows, meta)) + "\n")
    return 0


def cmd_report(args) -> int:
    rows, meta = _load_rows(args.rows)
    cov = render_coverage(coverage(rows, meta))
    rep = report(rows, meta)
    md = cov + "\n\n" + render_report(rep)
    if args.out_json:
        Path(args.out_json).write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
    if args.out_md:
        Path(args.out_md).write_text(md, encoding="utf-8")
    sys.stdout.write(md + "\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    j = sub.add_parser("join")
    j.add_argument("--ledger", required=True)
    j.add_argument("--out", required=True)
    j.add_argument("--quotes", action="store_true", help="also join book_quotes for the exploratory venue move (slow)")
    c = sub.add_parser("coverage")
    c.add_argument("--rows", required=True)
    r = sub.add_parser("report")
    r.add_argument("--rows", required=True)
    r.add_argument("--out-md", default=None)
    r.add_argument("--out-json", default=None)
    args = parser.parse_args(argv)
    return {"join": cmd_join, "coverage": cmd_coverage, "report": cmd_report}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
