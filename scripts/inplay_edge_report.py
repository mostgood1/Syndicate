"""In-play edge report over scripts/inplay_recorder.py output (lane in-game-trading).

Question: during live games, how often is a Kalshi side positive AFTER the taker
fee at Kalshi's own ask, measured against the in-play sportsbook consensus, and
how long does it stay positive?

Fair price
  per bookmaker: multiplicative no-vig over the two outcomes of the SAME line;
  consensus = median across books carrying that exact line (>= --min-books);
  pinnacle = Pinnacle's own no-vig price, reported beside it.
  A Kalshi sample is compared only with a book poll at most --max-book-age s old.

Lines
  h2h: Kalshi "<team> wins" vs book h2h.
  spreads: Kalshi "<team> wins by over L" (floor_strike L) vs book spread -L for that team.
  totals: Kalshi "Over L" vs book totals Over L.
  Rungs with no exact book line are counted as unpriceable, never interpolated.

Edge
  YES: fair - yes_ask - fee(yes_ask);  NO: (1 - fair) - no_ask - fee(no_ask).
  Fee = Kalshi taker fee for --contracts contracts, divided back to one contract,
  with the series' own fee_multiplier (public GET /series/<series>).

Episodes
  Consecutive samples of one (ticker, side) with edge > threshold. An episode
  ends when the side is not positive at the next sample. For each ending we say
  WHO moved: the venue ask (venue caught up) or the book fair (the book was the
  stale one), whichever moved more toward the other.

Read-only. Prints denominators and time windows.
"""

from __future__ import annotations

import argparse
import bisect
import json
import statistics
import sys
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from syndicate.features.shared.venue_fees import kalshi_taker_fee_dollars  # noqa: E402

SERIES_URL = "https://external-api.kalshi.com/trade-api/v2/series/{}"


def ts(s: str) -> float:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def iso(t: float) -> str:
    return datetime.utcfromtimestamp(t).strftime("%H:%M:%SZ")


def fnum(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def series_multiplier(series: str, cache: dict) -> float:
    if series not in cache:
        try:
            with urllib.request.urlopen(SERIES_URL.format(series), timeout=15) as r:
                d = json.loads(r.read())
            cache[series] = float((d.get("series") or d)["fee_multiplier"])
        except Exception as e:  # noqa: BLE001
            print(f"FEE_READ_FAILED series={series} err={e!r} -> refusing to price", flush=True)
            cache[series] = None
    return cache[series]


def devig(a: float, b: float):
    if not a or not b or a <= 1 or b <= 1:
        return None
    pa, pb = 1 / a, 1 / b
    return pa / (pa + pb)


def book_fairs(event: dict, poll_t: float | None = None, max_quote_age: float | None = None) -> dict:
    """{(kind, team_or_side, line): {book: p}} for one OddsAPI event.

    A market whose own last_update is more than `max_quote_age` s before the
    poll is dropped: in play, a book that has not moved for minutes is either
    suspended or still showing its pregame price, and either would drag the
    consensus toward a stale number. 3-way (draw) markets are skipped.
    """
    out: dict = defaultdict(dict)
    for bk in event.get("bookmakers", []):
        for m in bk.get("markets", []):
            if poll_t is not None and max_quote_age is not None and m.get("last_update"):
                if poll_t - ts(m["last_update"]) > max_quote_age:
                    continue
            oc = m.get("outcomes") or []
            if len(oc) != 2:
                continue
            a, b = oc
            p = devig(a.get("price"), b.get("price"))
            if p is None:
                continue
            if m["key"] == "h2h":
                out[("h2h", a["name"], None)][bk["key"]] = p
                out[("h2h", b["name"], None)][bk["key"]] = 1 - p
            elif m["key"] == "spreads":
                out[("spreads", a["name"], a.get("point"))][bk["key"]] = p
                out[("spreads", b["name"], b.get("point"))][bk["key"]] = 1 - p
            elif m["key"] == "totals":
                for o, q in ((a, p), (b, 1 - p)):
                    out[("totals", o["name"], o.get("point"))][bk["key"]] = q
    return out


def team_match(sub: str, name: str) -> bool:
    s, n = (sub or "").lower().strip(), (name or "").lower()
    if not s:
        return False
    alias = {"la": "los angeles", "ny": "new york"}
    s = alias.get(s, s)
    return n.startswith(s) or s in n


def _corr(xs, ys):
    n = len(xs)
    if n < 8:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    return sxy / (sxx * syy) ** 0.5 if sxx > 0 and syy > 0 else None


def lead_lag(series: dict) -> None:
    """Who moves first: Kalshi mid or the book consensus?

    Resampled at each book poll (the coarser clock): the Kalshi mid is the last
    sample at or before the poll. corr(dKalshi[i], dFair[i+k]) for k in -2..2
    polls. A peak at k>0 means Kalshi moves FIRST (books follow); k<0 means the
    books move first and Kalshi follows. Pooled across tickers.
    """
    pooled = {k: ([], []) for k in (-2, -1, 0, 1, 2)}
    gaps, spreads = [], []
    for t, rows in series.items():
        by_poll = {}
        for tt, mid, fair, bt, spr in rows:
            by_poll[bt] = (mid, fair)  # last sample per poll wins
            spreads.append(spr)
        polls = sorted(by_poll)
        mids = [by_poll[p][0] for p in polls]
        fairs = [by_poll[p][1] for p in polls]
        gaps += [abs(m - f) for m, f in zip(mids, fairs)]
        dk = [mids[i + 1] - mids[i] for i in range(len(mids) - 1)]
        df = [fairs[i + 1] - fairs[i] for i in range(len(fairs) - 1)]
        for k in pooled:
            for i in range(len(dk)):
                j = i + k
                if 0 <= j < len(df):
                    pooled[k][0].append(dk[i])
                    pooled[k][1].append(df[j])
    if not gaps:
        print("LEAD_LAG: no priced series")
        return
    gaps.sort()
    spreads.sort()
    print(f"KALSHI MID vs BOOK FAIR |gap|: n={len(gaps)} p50={gaps[len(gaps)//2]:.3f} p90={gaps[int(len(gaps)*0.9)]:.3f}  "
          f"Kalshi bid-ask spread p50={spreads[len(spreads)//2]:.3f} p90={spreads[int(len(spreads)*0.9)]:.3f}")
    print("LEAD_LAG corr(dKalshi[i], dFair[i+k]) per book poll (k>0: Kalshi first):  " + "  ".join(
        f"k={k:+d}: {(_corr(*pooled[k]) or float('nan')):+.2f} (n={len(pooled[k][0])})" for k in sorted(pooled)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--max-book-age", type=float, default=90.0)
    ap.add_argument("--min-books", type=int, default=3)
    ap.add_argument("--max-quote-age", type=float, default=120.0, help="drop a book market not updated within this many s of the poll")
    ap.add_argument("--contracts", type=int, default=10)
    ap.add_argument("--thresholds", default="0,0.01,0.02,0.03")
    ap.add_argument("--json-out")
    a = ap.parse_args()
    d = Path(a.dir)
    thresholds = [float(x) for x in a.thresholds.split(",")]

    # Book polls: per sport, sorted list of (t, {event_id: event}).
    books = defaultdict(list)
    for line in open(d / "books.jsonl", encoding="utf-8"):
        r = json.loads(line)
        books[r["sport"]].append((ts(r["ts"]), {e["id"]: e for e in r["events"]}))
    for s in books:
        books[s].sort(key=lambda x: x[0])
    btimes = {s: [x[0] for x in v] for s, v in books.items()}

    # Kalshi samples grouped by event, then ticker.
    kal = defaultdict(lambda: defaultdict(list))
    meta = {}
    for line in open(d / "kalshi.jsonl", encoding="utf-8"):
        r = json.loads(line)
        if r.get("st") != "active":
            continue
        kal[r["ev"]][r["t"]].append(r)
        meta[r["t"]] = r

    fee_cache: dict = {}
    sport_of = lambda ev: "nba" if ev.startswith("KXNBA") else ("nhl" if ev.startswith("KXNHL") else None)  # noqa: E731

    # Map Kalshi game key (ticker middle, e.g. 26OCT20ANANYI) -> OddsAPI event id via h2h subs.
    game_subs = defaultdict(set)
    for ev, tick in kal.items():
        if ev.split("-")[0].endswith("GAME"):
            for t in tick:
                game_subs[ev.split("-", 1)[1]].add(meta[t].get("sub"))
    all_events = {}
    for s, polls in books.items():
        for _, evs in polls:
            for eid, e in evs.items():
                all_events[eid] = (s, e)
    game_to_event = {}
    for g, subs in game_subs.items():
        for eid, (s, e) in all_events.items():
            names = (e.get("home_team"), e.get("away_team"))
            if all(any(team_match(sub, n) for n in names) for sub in subs) and len(subs) == 2:
                game_to_event[g] = eid

    stats = {"samples": Counter(), "priced": Counter(), "unpriceable": Counter(), "stale_book": Counter()}
    pos = {th: Counter() for th in thresholds}
    episodes = []  # dicts
    cadence = defaultdict(list)  # family -> seconds between ask changes
    window = [None, None]
    per_game = defaultdict(lambda: Counter())
    series = defaultdict(list)  # ticker -> [(t, kalshi_mid, book_fair, book_poll_t, spread)]

    for ev, ticks in kal.items():
        family = ev.split("-")[0]
        sport = sport_of(ev)
        g = ev.split("-", 1)[1]
        eid = game_to_event.get(g)
        mult = series_multiplier(family, fee_cache)
        for t, rows in ticks.items():
            rows.sort(key=lambda r: r["ts"])
            last_change, last_ask = None, None
            open_ep = {"yes": None, "no": None}
            for r in rows:
                tt = ts(r["ts"])
                ya, na = fnum(r.get("ya")), fnum(r.get("na"))
                if eid is None or sport not in books:
                    stats["unpriceable"][family + ":no_book_event"] += 1
                    continue
                i = bisect.bisect_right(btimes[sport], tt) - 1
                if i < 0:
                    continue
                bt, evs = books[sport][i]
                e = evs.get(eid)
                if e is None:  # not live in that poll (pregame or finished)
                    continue
                stats["samples"][family] += 1
                # Ask-change cadence IN PLAY only (pregame books barely move).
                if (ya, na) != last_ask:
                    if last_change is not None:
                        cadence[family].append(tt - last_change)
                    last_change, last_ask = tt, (ya, na)
                if tt - bt > a.max_book_age:
                    stats["stale_book"][family] += 1
                    continue
                window[0] = tt if window[0] is None else min(window[0], tt)
                window[1] = tt if window[1] is None else max(window[1], tt)
                fairs = book_fairs(e, bt, a.max_quote_age)
                sub, fs = r.get("sub") or "", fnum(r.get("fs"))
                if family.endswith("GAME"):
                    key = next((k for k in fairs if k[0] == "h2h" and team_match(sub, k[1])), None)
                elif family.endswith("SPREAD"):
                    team = sub.split(" wins by")[0]
                    key = next((k for k in fairs if k[0] == "spreads" and team_match(team, k[1]) and k[2] is not None and abs(k[2] + fs) < 1e-6), None)
                elif family.endswith("TOTAL"):
                    key = next((k for k in fairs if k[0] == "totals" and k[1] == "Over" and k[2] is not None and abs(k[2] - fs) < 1e-6), None)
                else:
                    key = None
                bk = fairs.get(key) if key else None
                if not bk or len(bk) < a.min_books:
                    stats["unpriceable"][family + (":no_line" if not bk else ":few_books")] += 1
                    continue
                fair = statistics.median(bk.values())
                pin = bk.get("pinnacle")
                yb = fnum(r.get("yb"))
                if ya is not None and yb is not None and 0 < yb <= ya < 1:
                    series[t].append((tt, (ya + yb) / 2, fair, bt, ya - yb))
                stats["priced"][family] += 1
                per_game[g]["priced"] += 1
                for side, ask, p in (("yes", ya, fair), ("no", na, 1 - fair)):
                    if ask is None or not (0 < ask < 1) or mult is None:
                        continue
                    fee = kalshi_taker_fee_dollars(a.contracts, ask, fee_multiplier=mult) / a.contracts
                    edge = p - ask - fee
                    pin_edge = None if pin is None else ((pin if side == "yes" else 1 - pin) - ask - fee)
                    for th in thresholds:
                        if edge > th:
                            pos[th][family] += 1
                    ep = open_ep[side]
                    if edge > 0:
                        if ep is None:
                            open_ep[side] = {"ticker": t, "side": side, "start": tt, "end": tt, "n": 1, "max_edge": edge,
                                             "ask0": ask, "fair0": p, "pin_edge0": pin_edge, "game": g, "family": family}
                        else:
                            ep["end"], ep["n"] = tt, ep["n"] + 1
                            ep["max_edge"] = max(ep["max_edge"], edge)
                    elif ep is not None:
                        ep["close_ask"], ep["close_fair"] = ask, p
                        dv, db = abs(ask - ep["ask0"]), abs(p - ep["fair0"])
                        ep["ended_by"] = "venue" if dv > db else ("book" if db > dv else "both")
                        ep["dur"] = ep["end"] - ep["start"]
                        episodes.append(ep)
                        open_ep[side] = None
            for ep in open_ep.values():
                if ep is not None:
                    ep["ended_by"], ep["dur"] = "open_at_end", ep["end"] - ep["start"]
                    episodes.append(ep)

    tot = sum(stats["priced"].values())
    print(f"WINDOW {iso(window[0]) if window[0] else '-'}..{iso(window[1]) if window[1] else '-'}  "
          f"games mapped {len(game_to_event)}/{len(game_subs)}  fee multipliers {fee_cache}")
    print(f"IN-PLAY KALSHI SAMPLES (book event live): {dict(stats['samples'])}")
    print(f"  stale book (> {a.max_book_age}s): {dict(stats['stale_book'])}")
    print(f"  unpriceable: {dict(stats['unpriceable'])}")
    print(f"  PRICED samples: {dict(stats['priced'])}  total {tot}  (x2 sides = {2*tot} side-samples)")
    for th in thresholds:
        n = sum(pos[th].values())
        print(f"  edge > {th:.0%} after fee: {n}/{2*tot} side-samples = {n/max(1,2*tot):.2%}  by family {dict(pos[th])}")
    print(f"EPISODES (edge > 0): {len(episodes)}")
    for fam in sorted({e['family'] for e in episodes}):
        es = [e for e in episodes if e["family"] == fam]
        durs = sorted(e["dur"] for e in es)
        ends = Counter(e["ended_by"] for e in es)
        big = [e for e in es if e["max_edge"] > 0.02]
        print(f"  {fam}: n={len(es)} dur p50={durs[len(durs)//2]:.0f}s p90={durs[int(len(durs)*0.9)]:.0f}s max={durs[-1]:.0f}s "
              f"ended_by={dict(ends)}  max_edge>2%: {len(big)}  single-sample: {sum(1 for e in es if e['n']==1)}")
    for fam, c in sorted(cadence.items()):
        c = sorted(c)
        if c:
            print(f"KALSHI ASK CHANGE INTERVAL {fam}: n={len(c)} p10={c[len(c)//10]:.0f}s p50={c[len(c)//2]:.0f}s p90={c[int(len(c)*0.9)]:.0f}s")
    lead_lag(series)
    top = sorted(episodes, key=lambda e: -e["max_edge"])[:15]
    print("TOP EPISODES:")
    for e in top:
        print(f"  {e['ticker']} {e['side']} {iso(e['start'])} dur={e['dur']:.0f}s n={e['n']} max_edge={e['max_edge']:+.3f} "
              f"ask0={e['ask0']} fair0={e['fair0']:.3f} pin_edge0={e['pin_edge0'] if e['pin_edge0'] is None else round(e['pin_edge0'],3)} ended_by={e['ended_by']}")
    if a.json_out:
        Path(a.json_out).write_text(json.dumps({"episodes": episodes, "stats": {k: dict(v) for k, v in stats.items()},
                                                "pos": {str(k): dict(v) for k, v in pos.items()}}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
