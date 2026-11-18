#!/usr/bin/env python3
"""Momentum lag study -- lane `momentum-lag-study`, 2026-11-17.

QUESTION. OddsJam's "Momentum" tool treats the first sportsbook to move a price
as the true price and tells you to bet a book that is still on the number the
mover just left. Before building anything like it, this asks the cheap
question on data the fleet already holds: when one book moves a PREGAME
two-way (or three-way) price and another book, observed in the SAME fetch, is
still at or better than the mover's pre-move price, does that stale price beat
the close?

DESIGN (pre-registered in
`.syndicate/findings_2026-11-17_momentum_lag_study_preregistration.md`; the
`--pass population` run below printed only population counts before that file
was committed, and `--pass outcome` was run only after):

* Source: `<data_root>/<sport>_source/tracking/book_quotes/<shard>.jsonl[.gz]`
  (the per-book CHANGE log: a row only when a key's (line, price) changes),
  its `.state.json` sidecar (third slot = when the key was LAST OBSERVED, final
  value for the shard) and `tracking/book_quotes_heartbeat/<shard>.jsonl` (one
  line per fetch: which events and which books answered).
* A side = (selection, line) inside a group (event, segment, market, player,
  |line|). Alternate-line markets are excluded. A book's fair at time t is the
  proportional de-vig of its prices on every side of the group, only when it
  prices exactly one line per selection and every key is still alive
  (last observed at/after the instant asked about).
* A MOVE: book L changes a price at fetch t and L's de-vigged fair on side s
  rises by >= theta (side s got shorter at L).
* A LAGGARD instance: another non-exchange book B that (i) answered in the same
  fetch as L's move (heartbeat: B in books, event in events), (ii) did not
  change side s at t, (iii) still had the key alive at t (last observed >= t),
  (iv) quotes s at decimal >= L's pre-move decimal (at or past the number L
  left), (v) has predicted EV = fair_L_new(s) * dec_B - 1 >= E_min, and
  (vi) dec_B in [1.25, 5.0]. One instance per (event, group, side, B): the
  first detection.
* CLOSE: per book, the last pregame price (captured_at <= commence) with the
  key last observed >= commence - 30 min, de-vigged; consensus close = median
  over >= 3 non-exchange books. EV vs close = fair_close(s) * dec_B - 1.
* Statistic: mean EV vs close, event-clustered bootstrap (2,000 resamples,
  seed 20261117), 95% percentile CI.

Only events whose commence_time is >= 6 h in the past are used (learnings
2026-09-21: never grade a close for a game that has not started).

Read-only: reads the fleet data root, writes only to --out. Stdlib only, so it
runs under the fleet's python3 inside WSL without the app's dependencies. Run
it at Idle: `nice -n 19 ionice -c3 python3 scripts/momentum_lag_study.py ...`.
"""
from __future__ import annotations

import argparse
import bisect
import collections
import gzip
import json
import math
import os
import random
import statistics
import struct
import sys
import time
from datetime import datetime

EXCHANGES = frozenset({
    "kalshi", "polymarket", "novig", "prophetx", "betfair_ex_eu", "betfair_ex_uk",
    "betfair_ex_au", "matchbook", "sporttrade",
})
KEY_FIELDS = ("sport", "kind", "event_id", "bookmaker", "segment", "market", "selection", "player_name", "line")
SPORTS_DEFAULT = ("nba", "nhl", "nfl", "ncaaf", "ncaab", "soccer", "mlb", "wnba")
DEC_MIN, DEC_MAX = 1.02, 51.0          # outside this a quote is treated as not offered
OVERROUND_MIN, OVERROUND_MAX = 0.98, 1.25
ENTRY_DEC_MIN, ENTRY_DEC_MAX = 1.25, 5.0
CLOSE_ALIVE_SLACK_S = 1800.0
CLOSE_MIN_BOOKS = 3
COMPLETED_AFTER_S = 6 * 3600.0
CONTROL_LEAD_S = 7200.0                # control arm: a book's price 2 h before start
DELAY_WINDOW_S = 600.0
CONFIRM_MIN_S, CONFIRM_MAX_S = 300.0, 1800.0  # arm B (fanduel-lead-forward): a re-read 5..30 min later
# O'Brien-Fleming two-look boundaries, two-sided alpha 0.05 (z at look 1, look 2).
OBF_BOUNDARY = {1: 2.797, 2: 1.977}
FORWARD_LEADER = "fanduel"
BOOT_N = 2000
BOOT_SEED = 20261117
THETAS = (0.01, 0.02, 0.03, 0.05)

_TS_CACHE: dict[str, float | None] = {}


def parse_ts(value) -> float | None:
    if value is None:
        return None
    s = str(value)
    if s in _TS_CACHE:
        return _TS_CACHE[s]
    try:
        out = datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:
        out = None
    _TS_CACHE[s] = out
    return out


def to_dec(american) -> float | None:
    try:
        a = float(american)
    except Exception:
        return None
    if a == 0 or a != a:
        return None
    d = 1.0 + a / 100.0 if a > 0 else 1.0 + 100.0 / (-a)
    return d if DEC_MIN <= d <= DEC_MAX else None


def norm_line(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        f = float(value)
    except Exception:
        return None
    return None if f != f else f


def quote_key(row: dict) -> str:
    # Mirrors odds_book_quotes._quote_key exactly (json-loaded floats included).
    return "|".join(str(row.get(field) or "") for field in KEY_FIELDS)


def gzip_isize(path: str) -> int | None:
    try:
        with open(path, "rb") as fh:
            fh.seek(-4, os.SEEK_END)
            return struct.unpack("<I", fh.read(4))[0]
    except Exception:
        return None


def shard_files(root: str, sport: str) -> list[tuple[str, str]]:
    """(shard, path) using the reader's rule: plain wins unless the .gz is provably fuller."""
    d = os.path.join(root, f"{sport}_source", "tracking", "book_quotes")
    if not os.path.isdir(d):
        return []
    names = set(os.listdir(d))
    shards = sorted({n[: -len(".jsonl")] for n in names if n.endswith(".jsonl")}
                    | {n[: -len(".jsonl.gz")] for n in names if n.endswith(".jsonl.gz")})
    out = []
    for shard in shards:
        plain = os.path.join(d, shard + ".jsonl")
        packed = plain + ".gz"
        if os.path.isfile(plain):
            path = plain
            if os.path.isfile(packed):
                isize = gzip_isize(packed)
                if isize is not None and isize > os.path.getsize(plain):
                    path = packed
        else:
            path = packed
        out.append((shard, path))
    return out


def open_text(path: str):
    if path.endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")
    return open(path, encoding="utf-8", errors="replace")


def load_state_last_seen(root: str, sport: str, shard: str) -> dict[str, float]:
    p = os.path.join(root, f"{sport}_source", "tracking", "book_quotes", shard + ".state.json")
    try:
        with open(p, encoding="utf-8") as fh:
            raw = json.load(fh)
    except Exception:
        return {}
    out = {}
    for k, v in raw.items():
        if isinstance(v, list) and len(v) >= 3 and v[2]:
            t = parse_ts(v[2])
            if t is not None:
                out[k] = t
    return out


def load_heartbeat(root: str, sport: str, shard: str) -> tuple[dict[str, tuple[frozenset, frozenset]], list[tuple[float, str]]]:
    p = os.path.join(root, f"{sport}_source", "tracking", "book_quotes_heartbeat", shard + ".jsonl")
    by_cap: dict[str, tuple[frozenset, frozenset]] = {}
    ordered: list[tuple[float, str]] = []
    if not os.path.isfile(p):
        return by_cap, ordered
    with open(p, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                r = json.loads(line)
            except Exception:
                continue
            cap = r.get("captured_at")
            if not cap:
                continue
            ev = frozenset(r.get("events") or ())
            bk = frozenset(r.get("books") or ())
            if cap in by_cap:  # two writers, same instant: union
                e0, b0 = by_cap[cap]
                ev, bk = e0 | ev, b0 | bk
            by_cap[cap] = (ev, bk)
            t = parse_ts(cap)
            if t is not None:
                ordered.append((t, cap))
    ordered.sort()
    return by_cap, ordered


class Side:
    __slots__ = ("times", "decs", "caps", "key", "last_seen")

    def __init__(self, key: str):
        self.times: list[float] = []
        self.decs: list[float | None] = []
        self.caps: list[str] = []
        self.key = key
        self.last_seen: float | None = None

    def at(self, t: float, strict: bool = False, alive_from: float | None = None) -> float | None:
        i = bisect.bisect_left(self.times, t) if strict else bisect.bisect_right(self.times, t)
        if i == 0:
            return None
        if alive_from is not None and (self.last_seen is None or self.last_seen < alive_from):
            return None
        return self.decs[i - 1]

    def changed_at(self, t: float) -> bool:
        i = bisect.bisect_left(self.times, t)
        return i < len(self.times) and self.times[i] == t

    def next_change_after(self, t: float) -> tuple[float, float | None] | None:
        i = bisect.bisect_right(self.times, t)
        return (self.times[i], self.decs[i]) if i < len(self.times) else None


def book_fair(sides: dict, n_sel: int, t: float, strict: bool, alive_from: float | None):
    vals = {}
    for side, sd in sides.items():
        d = sd.at(t, strict=strict, alive_from=alive_from)
        if d is not None:
            vals[side] = d
    if len(vals) != n_sel or len({s[0] for s in vals}) != n_sel:
        return None, None
    inv = {s: 1.0 / d for s, d in vals.items()}
    tot = sum(inv.values())
    if not (OVERROUND_MIN <= tot <= OVERROUND_MAX):
        return None, None
    return {s: v / tot for s, v in inv.items()}, vals


def boot_ci(pairs: list[tuple[str, float]], n: int = BOOT_N, seed: int = BOOT_SEED) -> dict:
    if not pairs:
        return {"n": 0, "clusters": 0, "mean": None, "lo": None, "hi": None}
    agg: dict[str, list[float]] = collections.defaultdict(lambda: [0.0, 0])
    for c, v in pairs:
        a = agg[c]
        a[0] += v
        a[1] += 1
    clusters = list(agg.values())
    total = sum(a[0] for a in clusters)
    count = sum(a[1] for a in clusters)
    rng = random.Random(seed)
    k = len(clusters)
    stats = []
    for _ in range(n):
        s = c_ = 0
        for a in rng.choices(clusters, k=k):
            s += a[0]
            c_ += a[1]
        stats.append(s / c_)
    stats.sort()
    mean = total / count
    se = statistics.pstdev(stats)
    return {"n": count, "clusters": k, "mean": mean,
            "lo": stats[int(0.025 * n)], "hi": stats[int(0.975 * n) - 1],
            "se": se, "z": (mean / se) if se > 0 else None}


def process_shard(root: str, sport: str, shard: str, path: str, now: float, theta_min: float,
                  e_min: float, want_outcome: bool, acc: dict) -> None:
    last_seen = load_state_last_seen(root, sport, shard)
    hb_by_cap, hb_ordered = load_heartbeat(root, sport, shard)
    hb_times = [t for t, _ in hb_ordered]
    groups: dict[tuple, dict[str, dict[tuple, Side]]] = collections.defaultdict(lambda: collections.defaultdict(dict))
    commence: dict[str, float] = {}
    kinds: dict[tuple, str] = {}
    rows = kept = 0
    with open_text(path) as fh:
        for line in fh:
            rows += 1
            try:
                r = json.loads(line)
            except Exception:
                continue
            market = str(r.get("market") or "")
            if "alt" in market.lower():
                continue
            ev = r.get("event_id")
            book = r.get("bookmaker")
            sel = r.get("selection")
            if not ev or not book or not sel:
                continue
            ct = parse_ts(r.get("commence_time"))
            cap = r.get("captured_at")
            t = parse_ts(cap)
            if ct is None or t is None or ct > now - COMPLETED_AFTER_S or t > ct:
                continue
            ln = norm_line(r.get("line"))
            gkey = (ev, r.get("segment") or "full", market, r.get("player_name") or "",
                    None if ln is None else abs(ln))
            side = (str(sel).lower(), ln)
            bsides = groups[gkey][book]
            sd = bsides.get(side)
            if sd is None:
                sd = bsides[side] = Side(quote_key(r))
                sd.last_seen = last_seen.get(sd.key)
            sd.times.append(t)
            sd.decs.append(to_dec(r.get("price")))
            sd.caps.append(cap)
            commence[ev] = ct
            kinds[gkey] = "prop" if r.get("player_name") else "game"
            kept += 1
    cov = acc["coverage"][sport]
    cov["shards"] += 1
    cov["rows"] += rows
    cov["pregame_rows"] += kept
    if kept:
        cov["shards_with_completed_pregame"] += 1
        cov["dates"].add(shard)
        if hb_by_cap:
            cov["dates_with_heartbeat"].add(shard)
        if last_seen:
            cov["dates_with_last_seen"].add(shard)
    cov["events"] |= {f"{sport}|{e}" for e in commence}

    for gkey, books in groups.items():
        for sides in books.values():
            for sd in sides.values():
                order = sorted(range(len(sd.times)), key=sd.times.__getitem__)
                sd.times = [sd.times[i] for i in order]
                sd.decs = [sd.decs[i] for i in order]
                sd.caps = [sd.caps[i] for i in order]
        sels = {s[0] for sides in books.values() for s in sides}
        n_sel = len(sels)
        if n_sel < 2:
            continue
        ev = gkey[0]
        ct = commence[ev]
        cluster = f"{sport}|{ev}"
        kind = kinds.get(gkey, "game")

        # ---- close (computed for coverage in both passes; EV only in outcome) ----
        close_fairs: dict[tuple, list[float]] = collections.defaultdict(list)
        pin_close = None
        for book, sides in books.items():
            if book in EXCHANGES:
                continue
            fair, _ = book_fair(sides, n_sel, ct, strict=False, alive_from=ct - CLOSE_ALIVE_SLACK_S)
            if fair is None:
                continue
            for s, p in fair.items():
                close_fairs[s].append(p)
            if book == "pinnacle":
                pin_close = fair
        close = {s: statistics.median(v) for s, v in close_fairs.items() if len(v) >= CLOSE_MIN_BOOKS}

        # ---- control arm: every sportsbook price 2 h before start ----
        if want_outcome and close and (acc["detected_after"] is None or ct >= acc["detected_after"]):
            tc = ct - CONTROL_LEAD_S
            for book, sides in books.items():
                if book in EXCHANGES:
                    continue
                for s, sd in sides.items():
                    if s not in close:
                        continue
                    d = sd.at(tc, alive_from=tc)
                    if d is None or not (ENTRY_DEC_MIN <= d <= ENTRY_DEC_MAX):
                        continue
                    acc["control"].append((cluster, close[s] * d - 1.0, sport, kind))

        # ---- moves and laggards ----
        for lbook, lsides in books.items():
            ltimes = sorted({t for sd in lsides.values() for t in sd.times})
            for t in ltimes:
                new_fair, new_vals = book_fair(lsides, n_sel, t, strict=False, alive_from=t)
                if new_fair is None:
                    continue
                old_fair, old_vals = book_fair(lsides, n_sel, t, strict=True, alive_from=t)
                if old_fair is None:
                    continue
                for s, pn in new_fair.items():
                    if s not in old_fair:
                        continue
                    move = pn - old_fair[s]
                    if move < theta_min:
                        continue
                    sd_l = lsides[s]
                    if not sd_l.changed_at(t) and not any(x.changed_at(t) for x in lsides.values()):
                        continue
                    cap = None
                    for x in lsides.values():
                        i = bisect.bisect_left(x.times, t)
                        if i < len(x.times) and x.times[i] == t:
                            cap = x.caps[i]
                            break
                    acc["moves"][sport] += 1
                    for th in THETAS:
                        if move >= th:
                            acc["moves_by_theta"][(sport, th)] += 1
                    hb = hb_by_cap.get(cap) if cap else None
                    dec_l_old = old_vals[s]
                    # books already at or shorter than L's new price on s (co-movers)
                    co = 0
                    for b2, s2 in books.items():
                        if b2 == lbook or s not in s2:
                            continue
                        d2 = s2[s].at(t, alive_from=t)
                        if d2 is not None and d2 <= new_vals[s] + 1e-9:
                            co += 1
                    for bbook, bsides in books.items():
                        if bbook == lbook:
                            continue
                        sd_b = bsides.get(s)
                        if sd_b is None:
                            continue
                        venue = "exchange" if bbook in EXCHANGES else "sportsbook"
                        reason = None
                        if hb is None:
                            reason = "no_heartbeat_for_fetch"
                        elif bbook not in hb[1] or ev not in hb[0]:
                            reason = "B_not_in_same_fetch"
                        if sd_b.changed_at(t):
                            reason = reason or "B_changed_same_fetch"
                        d_b = sd_b.at(t)
                        if d_b is None:
                            continue
                        if sd_b.last_seen is None or sd_b.last_seen < t:
                            reason = reason or "B_key_not_alive"
                        if d_b + 1e-9 < dec_l_old:
                            continue  # B is not on the number L left
                        ev_pred = pn * d_b - 1.0
                        if ev_pred < e_min:
                            continue
                        if not (ENTRY_DEC_MIN <= d_b <= ENTRY_DEC_MAX):
                            reason = reason or "entry_price_out_of_band"
                        ikey = (sport, ev, gkey, s, bbook)
                        if ikey in acc["seen"]:
                            continue
                        if acc["detected_after"] is not None and t < acc["detected_after"]:
                            # Forward reads (lane fanduel-lead-forward): a detection before the registration
                            # instant is not counted and does not consume the bet's first detection.
                            continue
                        if reason:
                            # Counted, not kept: a later detection of the same bet may still qualify.
                            acc["excluded"][(venue, reason, move >= theta_min and "any")] += 1
                            continue
                        acc["seen"].add(ikey)
                        inst = {
                            "sport": sport, "shard": shard, "event": ev, "cluster": cluster, "kind": kind,
                            "market": gkey[2], "segment": gkey[1], "side": s[0], "line": s[1],
                            "leader": lbook, "leader_venue": "exchange" if lbook in EXCHANGES else "sportsbook",
                            "laggard": bbook, "venue": venue, "move": move,
                            "dec_l_old": dec_l_old, "dec_l_new": new_vals[s], "dec_b": d_b,
                            "ev_pred": ev_pred, "lead_min": (ct - t) / 60.0, "co_movers": co,
                            "t_detect": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t)),
                            "excluded": reason, "has_close": s in close, "has_pin_close": bool(pin_close and s in pin_close),
                        }
                        nxt = sd_b.next_change_after(t)
                        if nxt and nxt[0] <= ct:
                            inst["b_next_change_min"] = (nxt[0] - t) / 60.0
                            inst["b_next_dec"] = nxt[1]
                        if want_outcome:
                            if s in close:
                                inst["ev_close"] = close[s] * d_b - 1.0
                            if pin_close and s in pin_close:
                                inst["ev_pin_close"] = pin_close[s] * d_b - 1.0
                            # delayed entry: B's price at the next fetch it answered within 10 min
                            j = bisect.bisect_right(hb_times, t)
                            while j < len(hb_times) and hb_times[j] - t <= DELAY_WINDOW_S:
                                evs, bks = hb_by_cap[hb_ordered[j][1]]
                                if bbook in bks and ev in evs:
                                    t2 = hb_times[j]
                                    d2 = sd_b.at(t2, alive_from=t2)
                                    inst["delayed_min"] = (t2 - t) / 60.0
                                    inst["delayed_dec"] = d2
                                    if d2 is not None and s in close:
                                        inst["ev_close_delayed"] = close[s] * d2 - 1.0
                                    break
                                j += 1
                            # STILL-THERE entry (lane fanduel-lead-forward, arm B): the first fetch B answered
                            # for this event at least CONFIRM_MIN_S and at most CONFIRM_MAX_S after the move,
                            # before the start. OddsAPI's copy of a book is at most ~4.7 min old (p99 by book,
                            # worst Bovada; FanDuel 1.8; NBA/NFL/NHL 11-12..11-15), so a fetch >= 5 min on that
                            # still shows B's old price is a re-read of the book, not the same stale copy. Bet only if B is at or better than the
                            # entry price then; "moved" / "gone" / "no_fetch" are no bet.
                            inst["confirm_status"] = "no_fetch"
                            j = bisect.bisect_left(hb_times, t + CONFIRM_MIN_S)
                            while j < len(hb_times) and hb_times[j] - t <= CONFIRM_MAX_S and hb_times[j] <= ct:
                                evs, bks = hb_by_cap[hb_ordered[j][1]]
                                if bbook in bks and ev in evs:
                                    t3 = hb_times[j]
                                    d3 = sd_b.at(t3, alive_from=t3)
                                    inst["confirm_min"] = (t3 - t) / 60.0
                                    if d3 is None:
                                        inst["confirm_status"] = "gone"
                                    elif d3 + 1e-9 < d_b:
                                        inst["confirm_status"] = "moved"
                                    else:
                                        inst["confirm_status"] = "confirmed"
                                        inst["confirm_dec"] = d3
                                        if s in close:
                                            inst["ev_close_confirmed"] = close[s] * d3 - 1.0
                                    break
                                j += 1
                        acc["instances"].append(inst)


def summarize(acc: dict, theta: float, want_outcome: bool) -> dict:
    out: dict = {"coverage": {}, "population": {}, "params": {"theta_primary": theta}}
    for sport, c in sorted(acc["coverage"].items()):
        inter = c["dates"] & c["dates_with_heartbeat"] & c["dates_with_last_seen"]
        out["coverage"][sport] = {
            "shards": c["shards"], "rows": c["rows"], "pregame_rows_completed": c["pregame_rows"],
            "dates_with_completed_pregame": len(c["dates"]), "dates_with_heartbeat": len(c["dates_with_heartbeat"] & c["dates"]),
            "dates_with_last_seen": len(c["dates_with_last_seen"] & c["dates"]), "intersection_dates": len(inter),
            "intersection_first": min(inter) if inter else None, "intersection_last": max(inter) if inter else None,
            "events": len(c["events"]), "moves_ge_1pp": acc["moves"][sport],
            "moves_by_theta": {str(th): acc["moves_by_theta"][(sport, th)] for th in THETAS},
        }
    inst = acc["instances"]
    excl = collections.Counter({f"{v}|{r}": n for (v, r, _), n in acc["excluded"].items()})
    for i in inst:
        excl[f"{i['venue']}|eligible(first detection kept)"] += 1
    out["population"]["detections_by_venue_and_exclusion"] = dict(sorted(excl.items()))

    def eligible(i, th, venue="sportsbook", leader_venue="sportsbook"):
        return (i["venue"] == venue and not i["excluded"] and i["move"] >= th
                and (leader_venue is None or i["leader_venue"] == leader_venue))

    for th in THETAS:
        el = [i for i in inst if eligible(i, th)]
        out["population"][f"primary_like_theta_{th}"] = {
            "instances": len(el), "events": len({i["cluster"] for i in el}),
            "with_close": sum(1 for i in el if i["has_close"]),
            "events_with_close": len({i["cluster"] for i in el if i["has_close"]}),
            "by_sport": dict(collections.Counter(i["sport"] for i in el if i["has_close"])),
            "by_kind": dict(collections.Counter(i["kind"] for i in el if i["has_close"])),
        }
    xl = [i for i in inst if eligible(i, theta, leader_venue="exchange") and i["has_close"]]
    out["population"]["leader_exchange_laggard_sportsbook_theta_primary"] = {
        "instances": len(xl), "events": len({i["cluster"] for i in xl})}
    prim = [i for i in inst if eligible(i, theta) and i["has_close"]]
    if prim:
        evp = sorted(i["ev_pred"] for i in prim)
        mv = sorted(i["move"] for i in prim)
        lead = sorted(i["lead_min"] for i in prim)
        q = lambda xs, p: xs[min(len(xs) - 1, int(p * len(xs)))]
        out["population"]["primary_shape"] = {
            "ev_pred_p10_p50_p90": [q(evp, .1), q(evp, .5), q(evp, .9)],
            "move_p10_p50_p90": [q(mv, .1), q(mv, .5), q(mv, .9)],
            "lead_min_p10_p50_p90": [q(lead, .1), q(lead, .5), q(lead, .9)],
            "leaders": dict(collections.Counter(i["leader"] for i in prim).most_common(12)),
            "laggards": dict(collections.Counter(i["laggard"] for i in prim).most_common(12)),
            "co_movers_0_share": sum(1 for i in prim if i["co_movers"] == 0) / len(prim),
            "b_moved_before_close_share": sum(1 for i in prim if "b_next_change_min" in i) / len(prim),
        }
    if not want_outcome:
        return out

    res: dict = {}
    pairs = lambda xs, f="ev_close": [(i["cluster"], i[f]) for i in xs if i.get(f) is not None]
    res["PRIMARY"] = boot_ci(pairs(prim))
    res["PRIMARY_ev_pred_mean"] = statistics.fmean(i["ev_pred"] for i in prim) if prim else None
    res["control_all_sportsbook_prices_2h_out"] = boot_ci([(c, v) for c, v, _, _ in acc["control"]])
    sec = {}
    for sport in sorted({i["sport"] for i in prim}):
        sec[f"sport={sport}"] = boot_ci(pairs([i for i in prim if i["sport"] == sport]))
        sec[f"control sport={sport}"] = boot_ci([(c, v) for c, v, sp, _ in acc["control"] if sp == sport])
    for kind in ("game", "prop"):
        sec[f"kind={kind}"] = boot_ci(pairs([i for i in prim if i["kind"] == kind]))
    for th in THETAS:
        sec[f"theta>={th}"] = boot_ci(pairs([i for i in inst if eligible(i, th) and i["has_close"]]))
    sec["delayed_entry(next fetch <=10min)"] = boot_ci(pairs(prim, "ev_close_delayed"))
    sec["delayed_entry_gone_share"] = (sum(1 for i in prim if "delayed_min" in i and i.get("delayed_dec") is None)
                                       / max(1, sum(1 for i in prim if "delayed_min" in i)))
    sec["pinnacle_close"] = boot_ci(pairs(prim, "ev_pin_close"))
    sec["co_movers=0 (leader alone)"] = boot_ci(pairs([i for i in prim if i["co_movers"] == 0]))
    sec["co_movers>=1"] = boot_ci(pairs([i for i in prim if i["co_movers"] >= 1]))
    for lo, hi in ((0, 30), (30, 120), (120, 600), (600, 1e9)):
        sec[f"lead_min[{lo},{hi})"] = boot_ci(pairs([i for i in prim if lo <= i["lead_min"] < hi]))
    for who in ("leader", "laggard"):
        for book, _n in collections.Counter(i[who] for i in prim).most_common(6):
            sec[f"{who}={book}"] = boot_ci(pairs([i for i in prim if i[who] == book]))
    if "leader=pinnacle" not in sec:
        sec["leader=pinnacle"] = boot_ci(pairs([i for i in prim if i["leader"] == "pinnacle"]))
    exch = [i for i in inst if eligible(i, theta, venue="exchange", leader_venue=None) and i["has_close"]]
    sec["laggard=exchange (kalshi/polymarket/...), any leader"] = boot_ci(pairs(exch))
    xlead = [i for i in inst if eligible(i, theta, leader_venue="exchange") and i["has_close"]]
    sec["leader=exchange, laggard=sportsbook"] = boot_ci(pairs(xlead))
    res["secondary"] = sec
    res["ev_pred_vs_close_capture"] = (res["PRIMARY"]["mean"] / res["PRIMARY_ev_pred_mean"]
                                       if prim and res["PRIMARY"]["mean"] is not None and res["PRIMARY_ev_pred_mean"] else None)
    conv = [i for i in prim if "b_next_dec" in i and i["b_next_dec"] is not None]
    res["laggard_next_move_toward_leader_share"] = (sum(1 for i in conv if i["b_next_dec"] < i["dec_b"]) / len(conv)) if conv else None
    out["outcome"] = res
    return out


FORWARD_MIN_EVENTS_LOOK1 = 200


def forward_read(acc: dict, theta: float, look: int | None) -> dict:
    """The registered read of lane `fanduel-lead-forward`
    (`.syndicate/findings_2026-11-17_fanduel_lead_forward_preregistration.md`).

    Arm A: the in-sample FanDuel cell's exact definition (primary instance, leader == fanduel), EV vs the
    consensus close at the move's fetch. Arm B: the same bets, entered only if B still quotes the entry price or
    better at the first fetch it answered 5..30 min later, EV at that price. z = mean / bootstrap SE (event
    clusters). Boundaries are O'Brien-Fleming for two looks (2.797, 1.977). `look=None` labels a prior read.
    """
    inst = acc["instances"]
    base = [i for i in inst if i["venue"] == "sportsbook" and i["leader_venue"] == "sportsbook"
            and not i["excluded"] and i["move"] >= theta and i["has_close"]]
    fd = [i for i in base if i["leader"] == FORWARD_LEADER]
    pairs = lambda xs, f: [(i["cluster"], i[f]) for i in xs if i.get(f) is not None]
    a = boot_ci(pairs(fd, "ev_close"))
    b = boot_ci(pairs(fd, "ev_close_confirmed"))
    out = {
        "look": look, "boundary_z": OBF_BOUNDARY.get(look) if look else None,
        "arm_A_replication": a, "arm_B_still_there_5_30min": b,
        "arm_B_status": dict(collections.Counter(i.get("confirm_status") for i in fd)),
        "arm_B_same_bets_at_move_fetch": boot_ci([(i["cluster"], i["ev_close"]) for i in fd
                                                  if i.get("ev_close_confirmed") is not None]),
        "context_all_leaders_primary": boot_ci(pairs(base, "ev_close")),
        # Descriptive only: where arm A's effect sits by re-read status (in-sample it sat in "no_fetch").
        "arm_A_by_confirm_status": {st: boot_ci(pairs([i for i in fd if i.get("confirm_status") == st], "ev_close"))
                                    for st in ("confirmed", "moved", "gone", "no_fetch")},
        "fd_by_sport": {sp: boot_ci(pairs([i for i in fd if i["sport"] == sp], "ev_close"))
                        for sp in sorted({i["sport"] for i in fd})},
        "detection_window": [min((i["t_detect"] for i in fd), default=None), max((i["t_detect"] for i in fd), default=None)],
    }
    if not look:
        return out
    bound = OBF_BOUNDARY[look]
    if look == 1 and a["clusters"] < FORWARD_MIN_EVENTS_LOOK1:
        out["verdict"] = f"LOOK1_SKIPPED (arm A has {a['clusters']} events < {FORWARD_MIN_EVENTS_LOOK1}); read again at look 2"
        return out
    a_real = a["z"] is not None and a["z"] >= bound
    b_real = b["z"] is not None and b["z"] >= bound
    a_futile = a["hi"] is not None and a["hi"] < 0
    if a_real and b_real:
        verdict = "PROCEED: A and B both cross the boundary -> design an outcome-graded feed test"
    elif a_real and look == 1:
        verdict = "A REAL (stop A); B not yet -> read B again at look 2"
    elif a_real:
        verdict = "REAL_NOT_ACTIONABLE: A crosses, B does not -> no feed; the result is a prior for the steam expert"
    elif a_futile:
        verdict = "KILL: arm A's 95% CI upper bound < 0 -> the FanDuel lead was chance"
    elif look == 1:
        verdict = "CONTINUE: neither boundary nor futility -> read at look 2"
    else:
        verdict = "KILL: arm A misses the look-2 boundary -> the FanDuel lead was not shown"
    out["verdict"] = verdict
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--pass", dest="which", choices=("population", "outcome"), required=True)
    ap.add_argument("--root", default=os.environ.get("SYNDICATE_DATA_ROOT") or os.path.expanduser("~/syndicate-prod/data"))
    ap.add_argument("--sports", default=",".join(SPORTS_DEFAULT))
    ap.add_argument("--theta", type=float, default=0.02, help="primary move threshold (de-vigged prob)")
    ap.add_argument("--e-min", type=float, default=0.01, help="minimum predicted EV vs the mover's new fair")
    ap.add_argument("--now", default=None, help="ISO instant treated as now (default: wall clock)")
    ap.add_argument("--out", default=None, help="write the summary (+ instances for outcome) here")
    ap.add_argument("--detected-after", default=None,
                    help="ISO instant: count only detections at or after it (forward reads; control = events starting after it)")
    ap.add_argument("--forward-look", type=int, choices=(1, 2), default=None,
                    help="apply the fanduel-lead-forward look's boundary and print its verdict")
    args = ap.parse_args(argv)
    now = parse_ts(args.now) if args.now else time.time()
    want_outcome = args.which == "outcome"
    acc = {
        "detected_after": parse_ts(args.detected_after) if args.detected_after else None,
        "coverage": collections.defaultdict(lambda: {"shards": 0, "rows": 0, "pregame_rows": 0, "shards_with_completed_pregame": 0,
                                                     "dates": set(), "dates_with_heartbeat": set(), "dates_with_last_seen": set(),
                                                     "events": set()}),
        "moves": collections.Counter(), "moves_by_theta": collections.Counter(),
        "instances": [], "seen": set(), "control": [], "excluded": collections.Counter(),
    }
    t0 = time.time()
    for sport in [s.strip() for s in args.sports.split(",") if s.strip()]:
        for shard, path in shard_files(args.root, sport):
            process_shard(args.root, sport, shard, path, now, min(THETAS), args.e_min, want_outcome, acc)
            _TS_CACHE.clear()
        print(f"[momentum_lag_study] {sport} done at +{time.time() - t0:.0f}s instances={len(acc['instances'])}", file=sys.stderr, flush=True)
    summary = summarize(acc, args.theta, want_outcome)
    if want_outcome:
        summary["fanduel_forward"] = forward_read(acc, args.theta, args.forward_look)
    summary["params"].update({"pass": args.which, "now": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
                              "e_min": args.e_min, "root": args.root, "elapsed_s": round(time.time() - t0, 1),
                              "detected_after": args.detected_after, "forward_look": args.forward_look})
    text = json.dumps(summary, indent=1, default=str)
    print(text)
    if args.out:
        os.makedirs(args.out, exist_ok=True)
        with open(os.path.join(args.out, f"summary_{args.which}.json"), "w", encoding="utf-8") as fh:
            fh.write(text)
        if want_outcome:
            with open(os.path.join(args.out, "instances.jsonl"), "w", encoding="utf-8") as fh:
                for i in acc["instances"]:
                    fh.write(json.dumps(i, default=str) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
