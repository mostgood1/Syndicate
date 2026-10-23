"""Fast optimisation loop for the in-game ENTRY rule (lane in-game-trading).

USER DECISION 2026-10-23: "Leave it off; first work on faster optimization of the
entry rule, then revisit." Live entries stay OFF; this replays the rule over every
recorded night (scripts/inplay_recorder.py output, C:/tmp/inplay_<date>/) so a rule
change costs a replay, not a night of games.

WHAT IS REPLAYED: `inplay_entries_paper.decide` -- the function the fleet's paper
loop runs. For speed each Kalshi sample's features are computed ONCE (book fair +
n fresh books, seconds since the game's last ESPN score change with the same
"first sight of a live game = just changed" rule, Kalshi mid range over 60 s,
book-poll age, per-leg ask and edge after fee) and every config filters them;
`tests/test_inplay_rule_sweep.py` checks that filter against `decide()` sample by
sample, so the sweep cannot quietly diverge from the rule it is tuning.

BOOKING: like the paper loop -- the first qualifying sample per (ticker, leg) per
night, 1 contract at the ask; the loop's 15 s cadence is mimicked by thinning the
10 s recorder samples to >= 15 s apart.

OUTCOMES: markout +300 s after fee (our leg's Kalshi mid 300 s later, within 60 s,
minus ask and fee) and settled P&L per contract (Kalshi `result` on the last row).

SELECTION IS WALK-FORWARD BY NIGHT: for night k, the config with the best mean
settled P&L on nights < k (with >= --min-train entries) is chosen, then judged on
night k only. Pooled in-sample tables are printed for orientation and are NOT the
result. Entries within a game are correlated: game counts are printed beside n.

    py -3 scripts/inplay_rule_sweep.py --nights C:/tmp/inplay_2026-10-20 C:/tmp/inplay_2026-10-22
"""

from __future__ import annotations

import argparse
import bisect
import itertools
import json
import statistics
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from syndicate.features.shared import inplay_entries_paper as ip  # noqa: E402

SPORT_PREFIX = {"nhl": "KXNHLSPREAD", "nba": "KXNBASPREAD", "ncaaf": "KXNCAAFSPREAD", "nfl": "KXNFLSPREAD"}
GRID = {
    "min_edge": [0.02, 0.03, 0.05, 0.08, 0.12],
    "score_quiet_s": [60, 180, 300, 600],
    "min_books": [3, 5, 8],
    "mid_max_move": [0.01, 0.02, 0.03, 0.05],
    "legs": [("yes", "no"), ("yes",), ("no",)],
    "ask_band": [(0.05, 0.95), (0.15, 0.85), (0.30, 0.70)],
}
BASELINE = {"min_edge": 0.03, "score_quiet_s": 180, "min_books": 3, "mid_max_move": 0.03,
            "legs": ("yes", "no"), "ask_band": (0.05, 0.95)}


def ts(s: str) -> float:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def load_night(d: Path, sports: list[str]) -> list[dict]:
    """Per-sample feature rows for every spread rung of `sports` while its game is in play."""
    prefixes = tuple(SPORT_PREFIX[s] for s in sports)
    books = defaultdict(list)  # sport -> [(t, {id: event})]
    for line in open(d / "books.jsonl", encoding="utf-8"):
        r = json.loads(line)
        if r.get("sport") in sports:
            books[r["sport"]].append((ts(r["ts"]), {e["id"]: e for e in r.get("events") or []}))
    for s in books:
        books[s].sort(key=lambda x: x[0])
    btimes = {s: [x[0] for x in v] for s, v in books.items()}

    # ESPN: per (sport, abbr-set) the score-change times and in-play intervals, with first-sight-in = change.
    changes, live_from, abbrs = defaultdict(list), {}, {}
    last = {}
    for line in open(d / "espn.jsonl", encoding="utf-8"):
        r = json.loads(line)
        if r.get("sport") not in sports:
            continue
        ab = tuple(sorted((x.get("abbr") or "") for x in r.get("teams") or []))
        key = (r["sport"], ab)
        abbrs[key] = ab
        sc = tuple(sorted(((x.get("abbr") or ""), x.get("score")) for x in r.get("teams") or []))
        t = ts(r["ts"])
        if r.get("state") == "in":
            if key not in live_from:
                live_from[key] = t
                changes[key].append(t)  # first sight of a live game: treat as just changed
            elif key in last and last[key] != sc:
                changes[key].append(t)
        last[key] = sc

    def game_key(sport: str, ticker: str):
        code = ticker.split("-")[1][7:] if "-" in ticker else ""
        hits = [k for k in abbrs if k[0] == sport and k[1] and all(a and a in code for a in k[1])]
        return max(hits, key=lambda k: sum(len(a) for a in k[1])) if hits else None

    series = defaultdict(list)
    result = {}
    for line in open(d / "kalshi.jsonl", encoding="utf-8"):
        r = json.loads(line)
        t = r.get("t") or ""
        if not t.startswith(prefixes):
            continue
        if r.get("res") in ("yes", "no"):
            result[t] = r["res"]
        if r.get("st") == "active":
            series[t].append((ts(r["ts"]), r))

    rows = []
    for ticker, samples in series.items():
        sport = next(s for s, p in SPORT_PREFIX.items() if ticker.startswith(p))
        gk = game_key(sport, ticker)
        if gk is None or gk not in live_from:
            continue
        samples.sort(key=lambda x: x[0])
        mids = [(t, (f(r["ya"]) + f(r["yb"])) / 2) for t, r in samples
                if f(r.get("ya")) is not None and f(r.get("yb")) is not None and 0 < f(r["yb"]) <= f(r["ya"]) < 1]
        mt = [m[0] for m in mids]
        last_t = None
        for t, r in samples:
            if t < live_from[gk] or (last_t is not None and t - last_t < 15):
                continue
            last_t = t
            i = bisect.bisect_right(btimes.get(sport, []), t) - 1
            if i < 0:
                continue
            poll_t, evs = books[sport][i]
            sub = str(r.get("sub") or "")
            line_v = f(r.get("fs"))
            if " wins by" not in sub or line_v is None:
                continue
            team = sub.split(" wins by")[0]
            event = next((e for e in evs.values()
                          if any(ip.team_match(team, n) for n in (e.get("home_team"), e.get("away_team")))), None)
            if event is None:
                continue
            fair, n = ip.book_fair(event, team, line_v, poll_t, min_books=1)
            if fair is None:
                continue
            lo = bisect.bisect_left(mt, t - ip.MID_STABLE_WINDOW_S)
            hi = bisect.bisect_right(mt, t)
            win = [m[1] for m in mids[lo:hi]]
            move = (max(win) - min(win)) if len(win) >= 2 else None
            prior = [c for c in changes[gk] if c <= t]
            since = (t - prior[-1]) if prior else None
            j = bisect.bisect_left(mt, t + 300)
            mid300 = mids[j][1] if j < len(mids) and mids[j][0] - (t + 300) <= 60 else None
            for leg, ask, p in (("yes", f(r.get("ya")), fair), ("no", f(r.get("na")), 1 - fair)):
                if ask is None or not (0 < ask < 1):
                    continue
                fee = ip.taker_fee_one(ask)
                res = result.get(ticker)
                rows.append({
                    "night": d.name, "sport": sport, "game": f"{sport}:{'|'.join(gk[1])}", "ticker": ticker,
                    "t": t, "leg": leg, "ask": ask, "fee": fee, "fair": p, "edge": p - ask - fee, "n_books": n,
                    "since": since, "move": move, "poll_age": t - poll_t,
                    "markout300": None if mid300 is None else ((mid300 if leg == "yes" else 1 - mid300) - ask - fee),
                    "pnl": None if res is None else ((1.0 if res == leg else 0.0) - ask - fee),
                    # what decide() needs, for the equivalence test
                    "_market": {"status": "active", "yes_sub_title": sub, "floor_strike": line_v,
                                "yes_ask_dollars": r.get("ya"), "no_ask_dollars": r.get("na")},
                    "_event": event, "_poll_t": poll_t,
                })
    return rows


def qualifies(row: dict, cfg: dict) -> bool:
    """The fast filter. Must agree with ip.decide for this row's leg (tested)."""
    lo, hi = cfg["ask_band"]
    return (row["poll_age"] <= ip.MAX_BOOK_POLL_AGE_S
            and row["since"] is not None and row["since"] > cfg["score_quiet_s"]
            and row["move"] is not None and row["move"] <= cfg["mid_max_move"]
            and row["n_books"] >= cfg["min_books"]
            and row["leg"] in cfg["legs"] and lo <= row["ask"] <= hi
            and row["edge"] >= cfg["min_edge"])


def to_params(cfg: dict) -> dict:
    return {"min_edge": cfg["min_edge"], "score_quiet_s": cfg["score_quiet_s"], "min_books": cfg["min_books"],
            "mid_max_move": cfg["mid_max_move"], "legs": cfg["legs"], "ask_lo": cfg["ask_band"][0],
            "ask_hi": cfg["ask_band"][1]}


def book(rows: list[dict], cfg: dict) -> list[dict]:
    """First qualifying sample per (night, ticker, leg)."""
    seen, out = set(), []
    for r in rows:
        k = (r["night"], r["ticker"], r["leg"])
        if k in seen or not qualifies(r, cfg):
            continue
        seen.add(k)
        out.append(r)
    return out


def summary(entries: list[dict]) -> dict:
    pn = [e["pnl"] for e in entries if e["pnl"] is not None]
    mk = [e["markout300"] for e in entries if e["markout300"] is not None]
    return {"n": len(entries), "games": len({e["game"] for e in entries}),
            "pnl_mean": statistics.mean(pn) if pn else None, "pnl_n": len(pn),
            "mk300_mean": statistics.mean(mk) if mk else None, "mk_n": len(mk)}


def fmt(s: dict) -> str:
    p = "  -   " if s["pnl_mean"] is None else f"{s['pnl_mean']:+.4f}"
    m = "  -   " if s["mk300_mean"] is None else f"{s['mk300_mean']:+.4f}"
    return f"n={s['n']:4d} games={s['games']:3d} pnl/ct={p} (n={s['pnl_n']}) mk300={m} (n={s['mk_n']})"


def cfg_name(c: dict) -> str:
    return (f"edge>={c['min_edge']} quiet>{c['score_quiet_s']}s books>={c['min_books']} move<={c['mid_max_move']}"
            f" legs={'+'.join(c['legs'])} ask{c['ask_band'][0]}-{c['ask_band'][1]}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--nights", nargs="+", required=True)
    ap.add_argument("--sports", default="nhl")
    ap.add_argument("--min-train", type=int, default=10)
    ap.add_argument("--top", type=int, default=12)
    a = ap.parse_args()
    sports = [s.strip() for s in a.sports.split(",") if s.strip()]
    nights = sorted(Path(n) for n in a.nights)
    loosest = {k: (min(v) if k in ("min_edge", "score_quiet_s", "min_books") else max(v))
               for k, v in GRID.items() if k not in ("legs", "ask_band")}
    loosest.update({"legs": ("yes", "no"), "ask_band": (min(b[0] for b in GRID["ask_band"]), max(b[1] for b in GRID["ask_band"]))})
    by_night = {}
    for n in nights:
        rows = load_night(n, sports)
        # No config can book a row the LOOSEST config rejects, so dropping those first changes nothing.
        by_night[n.name] = sorted((r for r in rows if qualifies(r, loosest)), key=lambda r: r["t"])
        print(f"  {n.name}: {len(rows)} raw feature rows -> {len(by_night[n.name])} candidate rows", flush=True)
    for k, v in by_night.items():
        print(f"NIGHT {k}: {len(v)} feature rows, {len({r['ticker'] for r in v})} rungs, "
              f"{len({r['game'] for r in v})} games ({','.join(sports)})")
    configs = [dict(zip(GRID, vals)) for vals in itertools.product(*GRID.values())]
    print(f"GRID: {len(configs)} configs\n")

    print("BASELINE (the paper rule as deployed):")
    for k, v in by_night.items():
        print(f"  {k}: {fmt(summary(book(v, BASELINE)))}")
    print(f"  pooled: {fmt(summary([e for v in by_night.values() for e in book(v, BASELINE)]))}\n")

    per = {i: {k: summary(book(v, c)) for k, v in by_night.items()} for i, c in enumerate(configs)}
    names = list(by_night)
    print("WALK-FORWARD (select on earlier nights by settled pnl/contract, judge on the next night only):")
    for idx in range(1, len(names)):
        train, test = names[:idx], names[idx]

        def train_score(i):
            ents = sum(per[i][n]["pnl_n"] for n in train)
            if ents < a.min_train:
                return None
            return sum((per[i][n]["pnl_mean"] or 0) * per[i][n]["pnl_n"] for n in train) / ents

        scored = [(train_score(i), i) for i in per if train_score(i) is not None]
        if not scored:
            print(f"  test {test}: no config with >= {a.min_train} settled training entries")
            continue
        best = max(scored)[1]
        print(f"  train {train} -> chose [{cfg_name(configs[best])}] train pnl/ct={max(scored)[0]:+.4f}")
        print(f"     TEST {test}: {fmt(per[best][test])}")
        print(f"     baseline on {test}: {fmt(summary(book(by_night[test], BASELINE)))}")
    print()

    pooled = []
    for i, c in enumerate(configs):
        ents = [e for v in by_night.values() for e in book(v, c)]
        s = summary(ents)
        if s["pnl_n"] >= 20:
            signs = [per[i][n]["pnl_mean"] for n in names]
            pooled.append((s["pnl_mean"], i, s, signs))
    pooled.sort(reverse=True)
    print(f"IN-SAMPLE POOLED TOP {a.top} (orientation only -- NOT the result; >= 20 settled):")
    for pm, i, s, signs in pooled[:a.top]:
        sg = " ".join("  .  " if x is None else f"{x:+.3f}" for x in signs)
        print(f"  {fmt(s)}  per-night [{sg}]  {cfg_name(configs[i])}")
    pos_all = [p for p in pooled if all(x is not None and x > 0 for x in p[3])]
    print(f"\nconfigs positive on EVERY night (>=20 settled pooled): {len(pos_all)} of {len(pooled)} eligible")
    return 0


if __name__ == "__main__":
    sys.exit(main())
