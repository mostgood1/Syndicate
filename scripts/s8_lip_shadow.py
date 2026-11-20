"""S8 -- read-only shadow of Kalshi liquidity-reward capture (lane `s8-lip-shadow`).

PRE-REGISTRATION: `.syndicate/findings_2026-11-20_s8_lip_shadow.md` (pushed to main as 33ba9c394 before the collector
first ran). The scoring rules below ARE the pre-registered rules; `tests/test_s8_lip_shadow.py` pins them.

READ-ONLY. Public GETs to `api.elections.kalshi.com` only: no orders, no account, no auth, no fleet change. It runs on
the host at Idle priority.

Subcommands:
  select   choose the day's book: every active `liquidity` incentive program with >= 6 h left, scored at S=100 per
           side at the reference price, greedy by static $/day per $ of resting capital to a $2,500 budget.
  collect  loop: the book's order books every 60 s, each market's public trades every 5 min (a fifth of the book per
           cycle), a reselect in a background thread at ~06:00 CST daily, a heartbeat file every cycle.

Data (outside the repo): <out>/universe_<UTC>.json, <out>/books_<UTC hour>.jsonl(.gz), <out>/trades_<UTC hour>.jsonl(.gz),
<out>/heartbeat.json.
"""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
import os
import shutil
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

API = "https://api.elections.kalshi.com/trade-api/v2"
S_CONTRACTS = 100
BUDGET_DOLLARS = 2500.0
MIN_HOURS_LEFT = 6.0
TICK = 0.01
BOOK_LEVELS_KEPT = 15
CYCLE_SECONDS = 60.0
TRADE_SLICES = 5  # each market's trades every TRADE_SLICES cycles (5 min)
RESELECT_CST_HOUR = 6
MAX_SNAPSHOT_GAP_S = 120.0
CST = dt.timezone(dt.timedelta(hours=-6))

Level = tuple[float, float]  # (price in dollars, contracts)


# --------------------------------------------------------------------------------------------- scoring (pre-registered)

def parse_book(payload: Mapping[str, Any]) -> tuple[list[Level], list[Level]]:
    """(yes bids, no bids), each sorted best (highest price) first. Accepts `orderbook_fp` (dollar strings) or the
    legacy `orderbook` (integer cents)."""
    ob = payload.get("orderbook_fp") or payload.get("orderbook") or {}

    def side(key: str) -> list[Level]:
        raw = ob.get(key + "_dollars") or ob.get(key) or []
        out: list[Level] = []
        for row in raw:
            try:
                p, q = row[0], row[1]
                price = float(p) if isinstance(p, str) else float(p) / 100.0
                out.append((round(price, 4), float(q)))
            except (TypeError, ValueError, IndexError):
                continue
        return sorted(out, key=lambda lv: -lv[0])

    return side("yes"), side("no")


def reference_price(levels: Sequence[Level], target: float) -> float | None:
    """First level, walking from the best, where cumulative resting size reaches target/5 (help.kalshi.com 13823851).
    If it is never reached, the deepest level. None for an empty side."""
    if not levels:
        return None
    cum = 0.0
    for price, qty in levels:
        cum += qty
        if cum >= target / 5.0:
            return price
    return levels[-1][0]


def others_score(levels: Sequence[Level], ref: float, df: float) -> float:
    """Orders at or better than the reference score 1.0x; worse ones DF**ticks (1 tick = $0.01)."""
    total = 0.0
    for price, qty in levels:
        if price >= ref - 1e-9:
            total += qty
        else:
            total += qty * (df ** round((ref - price) / TICK))
    return total


def snapshot_shares(yes: Sequence[Level], no: Sequence[Level], target: float, df: float, s: float = S_CONTRACTS,
                    yes_on: bool = True, no_on: bool = True) -> dict[str, Any]:
    """Our share on each side for one snapshot, with our order resting at that side's reference price.

    A snapshot pays only if BOTH sides reach the target size (our resting size counts). A side we are not resting on
    (filled, capped) scores 0 but its book still decides whether the snapshot qualifies."""
    yref, nref = reference_price(yes, target), reference_price(no, target)
    y_total = sum(q for _, q in yes) + (s if yes_on else 0.0)
    n_total = sum(q for _, q in no) + (s if no_on else 0.0)
    qualifies = yref is not None and nref is not None and y_total >= target and n_total >= target
    out = {"yes_ref": yref, "no_ref": nref, "qualifies": qualifies, "share_yes": 0.0, "share_no": 0.0}
    if not qualifies:
        return out
    if yes_on:
        out["share_yes"] = s / (others_score(yes, yref, df) + s)
    if no_on:
        out["share_no"] = s / (others_score(no, nref, df) + s)
    return out


def snapshot_reward(usd_per_day: float, gap_seconds: float, shares: Mapping[str, Any]) -> float:
    """usd_per_day * w / 86400 * 0.5 * (share_yes + share_no); w capped at MAX_SNAPSHOT_GAP_S, longer gaps earn 0."""
    if gap_seconds is None or gap_seconds <= 0 or gap_seconds > MAX_SNAPSHOT_GAP_S or not shares.get("qualifies"):
        return 0.0
    return usd_per_day * gap_seconds / 86400.0 * 0.5 * (shares["share_yes"] + shares["share_no"])


def m1_fills_side(trade: Mapping[str, Any], side: str, price: float) -> bool:
    """Fill model M1 (pessimistic): a YES bid at P fills on any trade at yes price <= P with taker side `no`; a NO bid
    at Q fills on any trade at yes price >= 1 - Q with taker side `yes`."""
    yp = trade_yes_price(trade)
    if yp is None:
        return False
    if side == "yes":
        return trade.get("taker_side") == "no" and yp <= price + 1e-9
    return trade.get("taker_side") == "yes" and yp >= 1.0 - price - 1e-9


def trade_yes_price(trade: Mapping[str, Any]) -> float | None:
    if trade.get("yes_price_dollars") not in (None, ""):
        try:
            return float(trade["yes_price_dollars"])
        except (TypeError, ValueError):
            return None
    if trade.get("yes_price") is not None:
        try:
            return float(trade["yes_price"]) / 100.0
        except (TypeError, ValueError):
            return None
    return None


def maker_fee(fee_type: str | None, price: float) -> float:
    """Per contract. `quadratic` series charge makers nothing; `quadratic_with_maker_fees` 0.0175 * p * (1 - p)."""
    if fee_type == "quadratic_with_maker_fees":
        return 0.0175 * price * (1.0 - price)
    return 0.0


def program_usd_per_day(program: Mapping[str, Any]) -> float:
    start = parse_ts(program.get("start_date"))
    end = parse_ts(program.get("end_date"))
    days = max(((end - start).total_seconds() / 86400.0) if (start and end) else 1.0, 1.0 / 24.0)
    return float(program.get("period_reward") or 0) / 1e4 / days


def static_entry(program: Mapping[str, Any], yes: Sequence[Level], no: Sequence[Level],
                 s: float = S_CONTRACTS) -> dict[str, Any] | None:
    """Static $/day and resting capital for one market, or None if the snapshot would not pay."""
    target = float(program.get("target_size_fp") or 0)
    df = (program.get("discount_factor_bps") or 0) / 1e4 or 0.5
    sh = snapshot_shares(yes, no, target, df, s)
    if not sh["qualifies"]:
        return None
    usd = program_usd_per_day(program)
    capital = s * (sh["yes_ref"] + sh["no_ref"])
    return {"usd_day_pool": usd, "usd_day_static": usd * 0.5 * (sh["share_yes"] + sh["share_no"]),
            "capital": capital, "yes_ref": sh["yes_ref"], "no_ref": sh["no_ref"], "target": target, "df": df,
            "share_yes": sh["share_yes"], "share_no": sh["share_no"]}


def greedy_book(entries: Iterable[Mapping[str, Any]], budget: float = BUDGET_DOLLARS) -> list[Mapping[str, Any]]:
    """Fill by static $/day per $ of resting capital until the budget is used (entries that do not fit are skipped)."""
    ranked = sorted((e for e in entries if e.get("capital", 0) > 0),
                    key=lambda e: -e["usd_day_static"] / e["capital"])
    book, used = [], 0.0
    for e in ranked:
        if used + e["capital"] > budget:
            continue
        book.append(e)
        used += e["capital"]
    return book


# ---------------------------------------------------------------------------------------------------------- plumbing

def parse_ts(value: Any) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def set_idle_priority() -> None:
    if sys.platform != "win32":
        return
    # The handle types matter on 64-bit Python: with ctypes' default int restype the GetCurrentProcess
    # pseudo-handle (-1) is truncated to 0xFFFFFFFF and SetPriorityClass fails silently (measured 11-20: the
    # collector ran at Normal until set by hand).
    try:
        import ctypes

        k32 = ctypes.windll.kernel32
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        k32.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        k32.SetPriorityClass.restype = ctypes.c_int
        k32.SetPriorityClass(k32.GetCurrentProcess(), 0x40)  # IDLE_PRIORITY_CLASS
    except Exception:  # noqa: BLE001
        pass


class Client:
    """Public GETs with a minimum spacing and backoff on 429/5xx. Read-only by construction (no other verb exists)."""

    def __init__(self, spacing: float):
        self.spacing = spacing
        self._last = 0.0
        self._lock = threading.Lock()
        self.errors = 0

    def get(self, path: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
        for attempt in range(6):
            with self._lock:
                wait = self._last + self.spacing - time.monotonic()
                if wait > 0:
                    time.sleep(wait)
                self._last = time.monotonic()
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=30) as r:
                    return json.load(r)
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503, 504):
                    time.sleep(2.0 * (attempt + 1))
                    continue
                self.errors += 1
                raise
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                time.sleep(2.0 * (attempt + 1))
        self.errors += 1
        raise RuntimeError(f"gave up on {path}")


def active_programs(client: Client, now: dt.datetime) -> list[dict[str, Any]]:
    out, cursor = [], ""
    for _ in range(500):
        params: dict[str, Any] = {"status": "active", "limit": 1000}
        if cursor:
            params["cursor"] = cursor
        page = client.get("/incentive_programs", params)
        out += page.get("incentive_programs") or []
        cursor = page.get("next_cursor") or ""
        if not cursor:
            break
    live = []
    for p in out:
        if p.get("incentive_type") != "liquidity":
            continue
        start, end = parse_ts(p.get("start_date")), parse_ts(p.get("end_date"))
        if not start or not end or not (start <= now < end):
            continue
        if (end - now).total_seconds() < MIN_HOURS_LEFT * 3600:
            continue
        live.append(p)
    return live


def select_universe(client: Client, out_dir: Path, log=print) -> Path:
    now = utcnow()
    programs = active_programs(client, now)
    log(f"[s8] select: {len(programs)} active liquidity programs with >= {MIN_HOURS_LEFT:g} h left")
    entries = []
    for i, p in enumerate(programs):
        if i % 1000 == 0:
            log(f"[s8] select: {i} of {len(programs)} books read, {len(entries)} payable so far")
        try:
            yes, no = parse_book(client.get(f"/markets/{p['market_ticker']}/orderbook"))
        except Exception as e:  # noqa: BLE001
            log(f"[s8] select: book {p.get('market_ticker')} failed: {str(e)[:80]}")
            continue
        e = static_entry(p, yes, no)
        if e is None:
            continue
        e.update({"ticker": p["market_ticker"], "event_ticker": p.get("event_ticker"),
                  "series_ticker": p.get("series_ticker"), "period_reward": p.get("period_reward"),
                  "program_start": p.get("start_date"), "program_end": p.get("end_date"), "program_id": p.get("id")})
        entries.append(e)
    book = greedy_book(entries)
    fee_types: dict[str, Any] = {}
    for e in book:
        s = e.get("series_ticker")
        if s and s not in fee_types:
            try:
                fee_types[s] = (client.get(f"/series/{s}").get("series") or {}).get("fee_type")
            except Exception:  # noqa: BLE001
                fee_types[s] = None
        e["fee_type"] = fee_types.get(s)
    path = out_dir / f"universe_{now.strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps({"selected_at": now.isoformat(), "budget": BUDGET_DOLLARS, "s": S_CONTRACTS,
                                "candidates": len(entries), "programs": len(programs), "book": book},
                               indent=1), encoding="utf-8")
    log(f"[s8] select: {len(entries)} payable, book {len(book)} markets, capital "
        f"{sum(e['capital'] for e in book):.0f}, static {sum(e['usd_day_static'] for e in book):.0f} $/day -> {path.name}")
    return path


class HourlyWriter:
    def __init__(self, out_dir: Path, prefix: str):
        self.out_dir, self.prefix = out_dir, prefix
        self.hour = None
        self.fh = None

    def write(self, record: Mapping[str, Any]) -> None:
        hour = utcnow().strftime("%Y%m%d%H")
        if hour != self.hour:
            self.close()
            self.hour = hour
            self.fh = open(self.out_dir / f"{self.prefix}_{hour}.jsonl", "a", encoding="utf-8")
        self.fh.write(json.dumps(record, separators=(",", ":")) + "\n")

    def close(self) -> None:
        if self.fh is None:
            return
        self.fh.close()
        src = self.out_dir / f"{self.prefix}_{self.hour}.jsonl"
        try:
            with open(src, "rb") as f_in, gzip.open(str(src) + ".gz", "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
            src.unlink()
        except OSError:
            pass
        self.fh = None


def collect(out_dir: Path, hours: float, log=print) -> int:
    set_idle_priority()
    client = Client(spacing=0.15)
    select_client = Client(spacing=0.35)
    universe_path = select_universe(client, out_dir, log)
    state = {"universe": json.loads(universe_path.read_text(encoding="utf-8")), "path": universe_path.name,
             "selecting": False, "last_select_cst_date": dt.datetime.now(CST).date().isoformat()}
    books_w, trades_w = HourlyWriter(out_dir, "books"), HourlyWriter(out_dir, "trades")
    last_trade_ts: dict[str, int] = {}
    seen_trades: set[str] = set()
    stop_at = time.time() + hours * 3600
    cycle = 0

    def reselect() -> None:
        try:
            path = select_universe(select_client, out_dir, log)
            state["universe"] = json.loads(path.read_text(encoding="utf-8"))
            state["path"] = path.name
        except Exception as e:  # noqa: BLE001
            log(f"[s8] reselect failed: {str(e)[:120]}")
        finally:
            state["selecting"] = False

    while time.time() < stop_at:
        t0 = time.time()
        now_cst = dt.datetime.now(CST)
        if (now_cst.hour >= RESELECT_CST_HOUR and now_cst.date().isoformat() != state["last_select_cst_date"]
                and not state["selecting"]):
            state["selecting"] = True
            state["last_select_cst_date"] = now_cst.date().isoformat()
            threading.Thread(target=reselect, daemon=True).start()
        book = list(state["universe"].get("book") or [])
        ok = err = trades_new = 0
        now = utcnow()
        for i, m in enumerate(book):
            end = parse_ts(m.get("program_end"))
            if end and now >= end:
                continue
            tk = m["ticker"]
            try:
                yes, no = parse_book(client.get(f"/markets/{tk}/orderbook"))
                books_w.write({"t": round(time.time(), 1), "tk": tk, "y": yes[:BOOK_LEVELS_KEPT],
                               "n": no[:BOOK_LEVELS_KEPT]})
                ok += 1
            except Exception:  # noqa: BLE001
                err += 1
            if i % TRADE_SLICES == cycle % TRADE_SLICES:
                since = last_trade_ts.get(tk, int(time.time()) - 600)
                try:
                    page = client.get("/markets/trades", {"ticker": tk, "min_ts": since, "limit": 1000})
                    for tr in page.get("trades") or []:
                        tid = str(tr.get("trade_id"))
                        if tid in seen_trades:
                            continue
                        seen_trades.add(tid)
                        trades_w.write({"tk": tk, **tr})
                        trades_new += 1
                    last_trade_ts[tk] = int(time.time()) - 30
                except Exception:  # noqa: BLE001
                    err += 1
        cycle += 1
        (out_dir / "heartbeat.json").write_text(json.dumps({
            "at": utcnow().isoformat(), "cycle": cycle, "universe": state["path"], "markets": len(book),
            "books_ok": ok, "errors": err, "trades_new": trades_new, "selecting": state["selecting"],
            "cycle_s": round(time.time() - t0, 1), "pid": os.getpid()}), encoding="utf-8")
        if len(seen_trades) > 200_000:
            seen_trades.clear()
        time.sleep(max(0.0, CYCLE_SECONDS - (time.time() - t0)))
    books_w.close()
    trades_w.close()
    log("[s8] collect: stopped at the hour limit")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s1 = sub.add_parser("select")
    s1.add_argument("--out", default=r"C:\tmp\pfmon\s8")
    s2 = sub.add_parser("collect")
    s2.add_argument("--out", default=r"C:\tmp\pfmon\s8")
    s2.add_argument("--hours", type=float, default=124.0)
    args = ap.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    def log(msg: str) -> None:
        line = f"{utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')} {msg}"
        print(line, flush=True)
        with open(out / "s8.log", "a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    if args.cmd == "select":
        set_idle_priority()
        select_universe(Client(spacing=0.15), out, log)
        return 0
    return collect(out, args.hours, log)


if __name__ == "__main__":
    raise SystemExit(main())
