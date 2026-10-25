"""Kalshi market-wide price map (Test A, lane pm-trader-strategies, 2026-10-24).

Is there ANY structural edge -- by price bucket x taker/maker x game phase -- in
the sports series Syndicate trades, under TODAY's Kalshi fees? Pre-registered in
`.syndicate/findings_2026-10-24_kalshi_market_price_map.md` BEFORE this ran; the
constants below are that registration and must not be re-tuned after a look.

Reads only Kalshi's PUBLIC, unauthenticated GET endpoints (`/series`,
`/markets`, `/historical/markets`, `/markets/trades`, `/historical/trades`,
`/historical/cutoff`). No credential, no order path, nothing in `syndicate/`.

    py -3 scripts/kalshi_market_price_map.py fetch  --out C:/tmp/kalshi_price_map
    py -3 scripts/kalshi_market_price_map.py report --out C:/tmp/kalshi_price_map

`fetch` is resumable (one file per sampled game) and lowers its own priority to
Idle (Windows) / nice 19. Kalshi caps unauthenticated reads at about 4 req/s and
parallel requests only draw 429s, so it is single-threaded and paced.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = "https://api.elections.kalshi.com/trade-api/v2"
SEED = 20261024
WINDOW_START = datetime(2025, 7, 1, tzinfo=timezone.utc)
SPLIT = datetime(2026, 9, 1, tzinfo=timezone.utc)
WINDOW_END = datetime(2026, 10, 24, 23, 59, 59, tzinfo=timezone.utc)
GAMES_PER_SPORT_HALF = 350
SPREADS_PER_GAME = 2
TOTALS_PER_GAME = 2
PRINTS_PER_WINDOW = 100
MIN_GAMES = 300
BOOT_DRAWS = 2000

# Nominal game length (start = end - D). Absorbed by the +-45 min exclusion band.
DURATION_H = {"nfl": 3.25, "ncaaf": 3.5, "nba": 2.4, "nhl": 2.6, "mlb": 2.9, "soccer": 1.95}
SOCCER_LEAGUES = ("EPL", "LALIGA", "SERIEA", "BUNDESLIGA", "LIGUE1", "UCL", "MLS")
SPORT_PREFIXES = {
    "nfl": ("NFL",), "ncaaf": ("NCAAF",), "nba": ("NBA",), "nhl": ("NHL",), "mlb": ("MLB",),
    "soccer": SOCCER_LEAGUES,
}
FAMILIES = ("GAME", "SPREAD", "TOTAL")
BUCKETS = ((0.01, 0.10), (0.10, 0.25), (0.25, 0.40), (0.40, 0.55), (0.55, 0.70),
           (0.70, 0.85), (0.85, 0.95), (0.95, 1.00))
PHASES = ("pregame", "in_play", "final")
SIDES = ("taker", "maker")
TAKER_COEF = 0.07
MAKER_COEF = 0.0175


def series_for(sport: str) -> list[tuple[str, str]]:
    return [(f"KX{p}{fam}", fam.lower()) for p in SPORT_PREFIXES[sport] for fam in FAMILIES]


def parse_ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def bucket_of(q: float) -> str | None:
    for lo, hi in BUCKETS:
        if lo <= q < hi:
            return f"{round(lo * 100)}-{round(hi * 100)}"
    return None


def phase_of(t: datetime, end: datetime, sport: str) -> str | None:
    d = timedelta(hours=DURATION_H[sport])
    if t >= end:
        return None
    if t >= end - timedelta(minutes=15):
        return "final"
    if t < end - d - timedelta(minutes=45):
        return "pregame"
    if t >= end - d + timedelta(minutes=15):
        return "in_play"
    return None


def fee(q: float, mult: float, coef: float) -> float:
    return coef * mult * q * (1.0 - q)


def positions(print_: dict, result: str, fee_type: str, mult: float, maker_fee_on: bool = True):
    """The taker and maker positions of one print: (side, price, return per contract)."""
    yes = float(print_["yes_price"])
    taker_yes = print_["taker_side"] == "yes"
    won_yes = result == "yes"
    tq = yes if taker_yes else 1.0 - yes
    t_won = won_yes if taker_yes else not won_yes
    mq = 1.0 - tq
    m_won = not t_won
    maker_coef = MAKER_COEF if (maker_fee_on and fee_type == "quadratic_with_maker_fees") else 0.0
    return (
        ("taker", tq, (1.0 if t_won else 0.0) - tq - fee(tq, mult, TAKER_COEF)),
        ("maker", mq, (1.0 if m_won else 0.0) - mq - fee(mq, mult, maker_coef)),
    )


# ---------------------------------------------------------------- fetch

class Client:
    def __init__(self, min_interval: float = 0.26):
        self.min_interval = min_interval
        self.last = 0.0
        self.n = 0
        self.n429 = 0

    def get(self, path: str) -> dict:
        backoff = 1.0
        while True:
            wait = self.min_interval - (time.monotonic() - self.last)
            if wait > 0:
                time.sleep(wait)
            self.last = time.monotonic()
            self.n += 1
            try:
                req = urllib.request.Request(BASE + path, headers={"User-Agent": "syndicate-research/1"})
                with urllib.request.urlopen(req, timeout=30) as r:
                    return json.load(r)
            except urllib.error.HTTPError as e:
                if e.code == 429 or e.code >= 500:
                    self.n429 += e.code == 429
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 60)
                    continue
                if e.code == 404:
                    return {}
                raise
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                time.sleep(backoff)
                backoff = min(backoff * 2, 60)


def lower_priority() -> str:
    if os.name == "nt":
        import ctypes
        k = ctypes.windll.kernel32
        # The pseudo-handle is (HANDLE)-1; with ctypes' default c_int it is passed truncated
        # and SetPriorityClass fails silently (measured: ok=False, class=0x0 on the first run).
        k.GetCurrentProcess.restype = ctypes.c_void_p
        k.SetPriorityClass.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
        k.GetPriorityClass.argtypes = (ctypes.c_void_p,)
        h = k.GetCurrentProcess()
        ok = k.SetPriorityClass(h, 0x40)  # IDLE_PRIORITY_CLASS
        return f"SetPriorityClass ok={bool(ok)} class=0x{k.GetPriorityClass(h):x}"
    os.nice(19)
    return f"nice={os.nice(0)}"


def list_markets(c: Client, series: str) -> list[dict]:
    out = []
    for path in ("/historical/markets", "/markets"):
        cur = ""
        while True:
            q = f"{path}?series_ticker={series}&limit=1000" + ("&status=settled" if path == "/markets" else "")
            d = c.get(q + (f"&cursor={cur}" if cur else ""))
            ms = d.get("markets") or []
            for m in ms:
                out.append({k: m.get(k) for k in ("ticker", "event_ticker", "close_time", "result")})
            cur = d.get("cursor")
            if not cur or not ms:
                break
    seen, uniq = set(), []
    for m in out:
        if m["ticker"] not in seen:
            seen.add(m["ticker"])
            uniq.append(m)
    return uniq


def build_games(markets_by_series: dict, sport: str) -> dict:
    """game key -> {end, half, markets: {family: [market...]}}; end from the moneyline close."""
    games: dict = defaultdict(lambda: {"markets": defaultdict(list)})
    for (series, fam), ms in markets_by_series.items():
        for m in ms:
            suffix = m["event_ticker"][len(series) + 1:]
            g = games[(sport, suffix)]
            m = dict(m, series=series)
            g["markets"][fam].append(m)
    out = {}
    for key, g in games.items():
        ml = [m for m in g["markets"].get("game", []) if m.get("close_time") and m.get("result") in ("yes", "no")]
        if not ml:
            continue
        end = max(parse_ts(m["close_time"]) for m in ml)
        if not (WINDOW_START <= end <= WINDOW_END):
            continue
        out[key] = {"end": end, "half": "discover" if end < SPLIT else "confirm", "markets": g["markets"]}
    return out


def sample_games(games: dict, sport: str, rng: random.Random) -> list:
    picked = []
    for half in ("discover", "confirm"):
        keys = sorted(k for k, g in games.items() if g["half"] == half)
        rng.shuffle(keys)
        picked += keys[:GAMES_PER_SPORT_HALF]
    return picked


def anchors(end: datetime, sport: str) -> list[datetime]:
    d = timedelta(hours=DURATION_H[sport])
    start = end - d
    return [start - timedelta(hours=12), start - timedelta(hours=3), start - timedelta(minutes=45),
            end - d / 2, end - timedelta(minutes=15), end - timedelta(minutes=4)]


def fetch_window(c: Client, ticker: str, at: datetime, trades_cutoff: datetime) -> list[dict]:
    path = "/historical/trades" if at < trades_cutoff else "/markets/trades"
    d = c.get(f"{path}?ticker={ticker}&limit={PRINTS_PER_WINDOW}&max_ts={int(at.timestamp())}")
    rows = []
    for t in d.get("trades") or []:
        rows.append({"id": t["trade_id"], "t": t["created_time"], "yes_price": float(t["yes_price_dollars"]),
                     "count": float(t.get("count_fp") or 0), "taker_side": t["taker_side"],
                     "block": bool(t.get("is_block_trade"))})
    return rows


def cmd_fetch(args) -> int:
    out = Path(args.out)
    (out / "games").mkdir(parents=True, exist_ok=True)
    print(f"[price_map] {lower_priority()}", flush=True)
    c = Client()
    cutoff = c.get("/historical/cutoff")
    trades_cutoff = parse_ts(cutoff["trades_created_ts"])
    rng = random.Random(SEED)
    fees, plan = {}, []
    for sport in args.sports.split(","):
        mfile = out / f"markets_{sport}.json"
        if mfile.exists():
            by_series = {tuple(k.split("|")): v for k, v in json.loads(mfile.read_text()).items()}
        else:
            by_series = {}
            for series, fam in series_for(sport):
                s = c.get(f"/series/{series}").get("series") or {}
                if not s.get("fee_type"):
                    print(f"[price_map] SKIP series={series} fee unreadable", flush=True)
                    continue
                fees[series] = (s["fee_type"], float(s.get("fee_multiplier") or 1))
                by_series[(series, fam)] = list_markets(c, series)
                print(f"[price_map] listed series={series} markets={len(by_series[(series, fam)])} req={c.n}", flush=True)
            mfile.write_text(json.dumps({"|".join(k): v for k, v in by_series.items()}))
        ffile = out / "series_fees.json"
        allfees = json.loads(ffile.read_text()) if ffile.exists() else {}
        allfees.update({k: list(v) for k, v in fees.items()})
        ffile.write_text(json.dumps(allfees))
        games = build_games(by_series, sport)
        keys = sample_games(games, sport, rng)
        halves = defaultdict(int)
        for k in games.values():
            halves[k["half"]] += 1
        print(f"[price_map] sport={sport} games={dict(halves)} sampled={len(keys)}", flush=True)
        plan += [(k, games[k]) for k in keys]
    allfees = json.loads((out / "series_fees.json").read_text())
    for i, ((sport, suffix), g) in enumerate(plan):
        gfile = out / "games" / f"{sport}_{suffix}.json"
        if gfile.exists():
            continue
        grng = random.Random(f"{SEED}|{sport}|{suffix}")
        chosen = []
        ml = [m for m in g["markets"]["game"] if m.get("result") in ("yes", "no")]
        chosen.append(("game", grng.choice(sorted(ml, key=lambda m: m["ticker"]))))
        for fam, n in (("spread", SPREADS_PER_GAME), ("total", TOTALS_PER_GAME)):
            pool = sorted(g["markets"].get(fam, []), key=lambda m: m["ticker"])
            for m in grng.sample(pool, min(n, len(pool))):
                chosen.append((fam, m))
        rec = {"sport": sport, "game": suffix, "end": g["end"].isoformat(), "half": g["half"], "markets": []}
        for fam, m in chosen:
            ft, mult = allfees.get(m["series"], (None, None))
            prints = {}
            if m.get("result") in ("yes", "no") and ft:
                for at in anchors(g["end"], sport):
                    for p in fetch_window(c, m["ticker"], at, trades_cutoff):
                        prints[p["id"]] = p
            rec["markets"].append({"ticker": m["ticker"], "family": fam, "series": m["series"],
                                   "result": m.get("result"), "close_time": m.get("close_time"),
                                   "fee_type": ft, "mult": mult, "prints": list(prints.values())})
        tmp = gfile.with_suffix(".tmp")
        tmp.write_text(json.dumps(rec))
        tmp.replace(gfile)
        if i % 25 == 0:
            print(f"[price_map] game {i + 1}/{len(plan)} {sport} {suffix} req={c.n} 429={c.n429}", flush=True)
    print(f"[price_map] DONE games={len(plan)} req={c.n} 429={c.n429}", flush=True)
    return 0


# ---------------------------------------------------------------- report

def cell_key(side, bucket, phase, extra=None):
    return (side, bucket, phase) if extra is None else (side, bucket, phase, extra)


def accumulate(rec: dict, maker_fee_on: bool = True):
    """Per-game sums per cell: {cell: [sum_r, n, sum_r_count, sum_count, sum_q_count]} plus exclusion counts."""
    sport = rec["sport"]
    end = parse_ts(rec["end"])
    cells: dict = defaultdict(lambda: [0.0, 0, 0.0, 0.0, 0.0])
    excl = defaultdict(int)
    for m in rec["markets"]:
        if m["result"] not in ("yes", "no"):
            excl["result_not_binary"] += 1
            continue
        mclose = parse_ts(m["close_time"]) if m.get("close_time") else end
        for p in m["prints"]:
            t = parse_ts(p["t"])
            if p.get("block"):
                excl["block"] += 1
                continue
            if t >= mclose:
                excl["after_market_close"] += 1
                continue
            ph = phase_of(t, end, sport)
            if ph is None:
                excl["phase_band"] += 1
                continue
            for side, q, r in positions(p, m["result"], m["fee_type"], m["mult"] or 1.0, maker_fee_on):
                b = bucket_of(q)
                if b is None:
                    excl["price_out_of_range"] += 1
                    continue
                for key in (cell_key(side, b, ph), cell_key(side, b, ph, "sport:" + sport),
                            cell_key(side, b, ph, "family:" + m["family"])):
                    s = cells[key]
                    s[0] += r
                    s[1] += 1
                    s[2] += r * p["count"]
                    s[3] += p["count"]
                    s[4] += q * p["count"]
    return cells, excl


def bootstrap_ci(sums, counts, draws=BOOT_DRAWS, seed=SEED):
    """Game-clustered bootstrap of sum(sums)/sum(counts); returns (mean, lo, hi)."""
    import numpy as np
    s = np.asarray(sums, float)
    n = np.asarray(counts, float)
    if n.sum() == 0:
        return None, None, None
    rng = np.random.default_rng(seed)
    g = len(s)
    w = rng.multinomial(g, np.full(g, 1.0 / g), size=draws)
    num = w @ s
    den = w @ n
    with np.errstate(invalid="ignore", divide="ignore"):
        est = num / den
    est = est[np.isfinite(est)]
    return float(s.sum() / n.sum()), float(np.percentile(est, 2.5)), float(np.percentile(est, 97.5))


def verdict(disc_games, conf_games, disc_mean, conf_lo, conf_hi):
    if disc_games < MIN_GAMES or conf_games < MIN_GAMES:
        return "INSUFFICIENT"
    if conf_lo is not None and conf_lo > 0 and disc_mean is not None and disc_mean > 0:
        return "STRUCTURAL EDGE"
    if conf_hi is not None and conf_hi <= 0:
        return "FALSIFIED"
    return "OPEN"


def cmd_report(args) -> int:
    out = Path(args.out)
    per_half = {"discover": defaultdict(dict), "confirm": defaultdict(dict)}
    excl_total = defaultdict(int)
    games_n = defaultdict(int)
    prints_n = 0
    for f in sorted((out / "games").glob("*.json")):
        rec = json.loads(f.read_text())
        games_n[(rec["sport"], rec["half"])] += 1
        prints_n += sum(len(m["prints"]) for m in rec["markets"])
        cells, excl = accumulate(rec, maker_fee_on=not args.maker_fee_zero)
        for k, v in excl.items():
            excl_total[k] += v
        gid = f"{rec['sport']}_{rec['game']}"
        for key, s in cells.items():
            per_half[rec["half"]][key][gid] = s
    lines = [f"# Kalshi price map report ({'maker fee 0 sensitivity' if args.maker_fee_zero else 'primary'})", "",
             f"games by sport x half: {dict(sorted(games_n.items()))}; prints read: {prints_n}; excluded: {dict(excl_total)}", ""]
    rows = []
    keys = sorted(set(per_half["discover"]) | set(per_half["confirm"]), key=lambda k: (len(k), str(k)))
    for key in keys:
        res = {}
        for half in ("discover", "confirm"):
            d = per_half[half].get(key, {})
            vals = list(d.values())
            mean, lo, hi = bootstrap_ci([v[0] for v in vals], [v[1] for v in vals]) if vals else (None, None, None)
            sc = sum(v[3] for v in vals)
            roi = (sum(v[2] for v in vals) / sum(v[4] for v in vals)) if vals and sum(v[4] for v in vals) else None
            res[half] = {"games": len(vals), "prints": int(sum(v[1] for v in vals)), "mean": mean, "lo": lo, "hi": hi,
                         "cw_mean": (sum(v[2] for v in vals) / sc) if sc else None, "roi": roi}
        v = verdict(res["discover"]["games"], res["confirm"]["games"], res["discover"]["mean"],
                    res["confirm"]["lo"], res["confirm"]["hi"])
        rows.append((key, res, v))
    c = lambda x: "" if x is None else f"{x * 100:+.2f}"
    for scope in ("PRIMARY", "sport", "family"):
        lines += [f"## {scope}", "",
                  "| side | bucket | phase | scope | DISC games | DISC mean c | CONF games | CONF prints | CONF mean c [95% CI] | CONF contract-wtd c | CONF ROI % | verdict |",
                  "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for key, res, v in rows:
            extra = key[3] if len(key) == 4 else ""
            if (scope == "PRIMARY") != (extra == "") or (extra and not extra.startswith(scope)):
                continue
            d, cf = res["discover"], res["confirm"]
            lines.append(f"| {key[0]} | {key[1]} | {key[2]} | {extra or 'pooled'} | {d['games']} | {c(d['mean'])} | "
                         f"{cf['games']} | {cf['prints']} | {c(cf['mean'])} [{c(cf['lo'])}, {c(cf['hi'])}] | "
                         f"{c(cf['cw_mean'])} | {c(cf['roi'])} | {v} |")
        lines.append("")
    passes = [k for k, _, v in rows if v == "STRUCTURAL EDGE" and len(k) == 3]
    lines.append(f"PRIMARY cells reaching STRUCTURAL EDGE: {len(passes)} {passes}")
    lines.append("KILL: no primary cell passes." if not passes else "KILL not met.")
    text = "\n".join(lines) + "\n"
    dest = out / ("report_makerfee0.md" if args.maker_fee_zero else "report.md")
    dest.write_text(text, encoding="utf-8")
    (out / ("report_makerfee0.json" if args.maker_fee_zero else "report.json")).write_text(
        json.dumps([[list(k), r, v] for k, r, v in rows]))
    print(text)
    return 0


# ---------------------------------------------------------------- recheck (NOT pre-registered)
#
# The registered design anchors its in-play windows and phases on the game's ACTUAL end.
# That is look-ahead: "this game ends within 15 minutes" is unknown in real time, and it
# selects games with no comeback, overtime or extra innings, i.e. games the leader wins.
# The recheck re-samples MONEYLINES only, at windows anchored on the SCHEDULED start,
# `expected_expiration_time - 3h` (set before the game; MLB tickers carry the start time and
# agree), and keeps only windows whose anchor is before the market closed. So every print
# is one a trader could have seen while the game was still undecided, at a known elapsed time.

SCHEDULE_OFFSET = timedelta(hours=3)
RECHECK_FRACTIONS = (0.25, 0.5, 0.75, 0.9, 1.0, 1.1)


def elapsed_phase(t: datetime, start: datetime, sport: str) -> str | None:
    e = (t - start) / timedelta(hours=DURATION_H[sport])
    if t < start - timedelta(minutes=45):
        return "pregame"
    if e < 0.1:
        return None
    if e < 0.5:
        return "early"
    if e < 0.85:
        return "mid"
    return "late"


def cmd_recheck(args) -> int:
    out = Path(args.out)
    rdir = out / "recheck"
    rdir.mkdir(exist_ok=True)
    print(f"[price_map] recheck {lower_priority()}", flush=True)
    c = Client()
    trades_cutoff = parse_ts(c.get("/historical/cutoff")["trades_created_ts"])
    files = sorted((out / "games").glob("*.json"))
    for i, f in enumerate(files):
        dest = rdir / f.name
        if dest.exists():
            continue
        rec = json.loads(f.read_text())
        m = next(x for x in rec["markets"] if x["family"] == "game")
        meta = (c.get(f"/markets/{m['ticker']}").get("market")
                or c.get(f"/historical/markets/{m['ticker']}").get("market") or {})
        exp = meta.get("expected_expiration_time")
        row = {"sport": rec["sport"], "game": rec["game"], "half": rec["half"], "ticker": m["ticker"],
               "result": m["result"], "fee_type": m["fee_type"], "mult": m["mult"],
               "close_time": m["close_time"], "expected_expiration_time": exp, "windows": []}
        if exp and m["result"] in ("yes", "no") and m["fee_type"]:
            start = parse_ts(exp) - SCHEDULE_OFFSET
            close = parse_ts(m["close_time"])
            d = timedelta(hours=DURATION_H[rec["sport"]])
            for fr in RECHECK_FRACTIONS:
                at = start + d * fr
                if at >= close:
                    continue
                row["windows"].append({"at": at.isoformat(), "fraction": fr,
                                       "prints": fetch_window(c, m["ticker"], at, trades_cutoff)})
        tmp = dest.with_suffix(".tmp")
        tmp.write_text(json.dumps(row))
        tmp.replace(dest)
        if i % 100 == 0:
            print(f"[price_map] recheck {i + 1}/{len(files)} req={c.n} 429={c.n429}", flush=True)
    print(f"[price_map] recheck DONE req={c.n} 429={c.n429}", flush=True)
    return 0


def recheck_cells(row: dict, maker_fee_on: bool = True):
    cells: dict = defaultdict(lambda: [0.0, 0, 0.0, 0.0, 0.0])
    if not row.get("expected_expiration_time") or row["result"] not in ("yes", "no"):
        return cells
    start = parse_ts(row["expected_expiration_time"]) - SCHEDULE_OFFSET
    seen = set()
    for w in row["windows"]:
        for p in w["prints"]:
            if p["id"] in seen or p.get("block"):
                continue
            seen.add(p["id"])
            ph = elapsed_phase(parse_ts(p["t"]), start, row["sport"])
            if ph is None:
                continue
            for side, q, r in positions(p, row["result"], row["fee_type"], row["mult"] or 1.0, maker_fee_on):
                b = bucket_of(q)
                if b is None:
                    continue
                s = cells[(side, b, ph)]
                s[0] += r
                s[1] += 1
                s[2] += r * p["count"]
                s[3] += p["count"]
                s[4] += q * p["count"]
    return cells


def end_anchored_moneyline_cells(rec: dict):
    """The registered (end-anchored) cells restricted to the moneyline, for a like-for-like comparison."""
    only_ml = dict(rec, markets=[m for m in rec["markets"] if m["family"] == "game"])
    cells, _ = accumulate(only_ml)
    return {k: v for k, v in cells.items() if len(k) == 3}


def cmd_recheck_report(args) -> int:
    out = Path(args.out)
    arms = {"end-anchored (registered), moneyline": defaultdict(lambda: defaultdict(dict)),
            "start-anchored (recheck), moneyline": defaultdict(lambda: defaultdict(dict))}
    durations = defaultdict(list)
    for f in sorted((out / "recheck").glob("*.json")):
        row = json.loads(f.read_text())
        gid = f"{row['sport']}_{row['game']}"
        rec = json.loads((out / "games" / f.name).read_text())
        if row.get("expected_expiration_time"):
            durations[row["sport"]].append(
                (parse_ts(row["close_time"]) - (parse_ts(row["expected_expiration_time"]) - SCHEDULE_OFFSET)) / timedelta(hours=1))
        for key, s in end_anchored_moneyline_cells(rec).items():
            arms["end-anchored (registered), moneyline"][rec["half"]][key][gid] = s
        for key, s in recheck_cells(row).items():
            arms["start-anchored (recheck), moneyline"][row["half"]][key][gid] = s
    import statistics
    lines = ["# Recheck: end-anchored vs start-anchored phases (moneyline only; NOT pre-registered)", "",
             "Hours from scheduled start (expected_expiration_time - 3h) to moneyline close, per sport (p10 / median / p90):", ""]
    for sp, v in sorted(durations.items()):
        v = sorted(v)
        lines.append(f"- {sp}: n={len(v)} p10={v[len(v) // 10]:.2f} median={statistics.median(v):.2f} p90={v[9 * len(v) // 10]:.2f}")
    c = lambda x: "" if x is None else f"{x * 100:+.2f}"
    for arm, halves in arms.items():
        lines += ["", f"## {arm}", "",
                  "| side | bucket | phase | DISC games | DISC mean c | CONF games | CONF mean c [95% CI] | verdict |",
                  "|---|---|---|---|---|---|---|---|"]
        keys = sorted(set(halves["discover"]) | set(halves["confirm"]), key=lambda k: (k[2], k[0], k[1]))
        for key in keys:
            res = {}
            for half in ("discover", "confirm"):
                vals = list(halves[half].get(key, {}).values())
                res[half] = (len(vals),) + (bootstrap_ci([v[0] for v in vals], [v[1] for v in vals]) if vals else (None, None, None))
            (dg, dm, _, _), (cg, cm, clo, chi) = res["discover"], res["confirm"]
            v = verdict(dg, cg, dm, clo, chi)
            lines.append(f"| {key[0]} | {key[1]} | {key[2]} | {dg} | {c(dm)} | {cg} | {c(cm)} [{c(clo)}, {c(chi)}] | {v} |")
    text = "\n".join(lines) + "\n"
    (out / "recheck_report.md").write_text(text, encoding="utf-8")
    print(text)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("--out", required=True)
    f.add_argument("--sports", default="nfl,ncaaf,nba,nhl,mlb,soccer")
    r = sub.add_parser("report")
    r.add_argument("--out", required=True)
    r.add_argument("--maker-fee-zero", action="store_true")
    for name in ("recheck", "recheck-report"):
        sub.add_parser(name).add_argument("--out", required=True)
    a = ap.parse_args(argv)
    return {"fetch": cmd_fetch, "report": cmd_report, "recheck": cmd_recheck,
            "recheck-report": cmd_recheck_report}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
