"""In-game ENTRY rule, PAPER ONLY (lane in-game-trading).

USER DECISION 2026-10-21 ~22:3xZ (session 15ceeb14): "Build the in-game entry
module PAPER-ONLY (decides and records would-be entries, sends nothing), so
tonight's NHL games measure the exact rule before any live money."

IT CANNOT TRADE. It imports no order, ledger, guard, credential or cancel code;
`tests/test_inplay_entries_paper.py` parses this file and fails on any such
name. Its only outputs are log lines and its own document,
`reports/intelligence/inplay_entries_paper.json`.

THE RULE (the one a live version would use; the 10-20 watch cell, NHL spreads
away from a score change, markout +0.9c [-0.6, +2.4], n=270):
  * Kalshi `KXNHLSPREAD` full-game rung on a game ESPN shows in progress;
  * the game's last ESPN score change is > 180 s old, and our own Kalshi mid
    samples for the rung moved <= 3c over the last 60 s;
  * >= 3 books quote the EXACT line, each market updated <= 120 s before an
    OddsAPI poll that is <= 90 s old; fair = median multiplicative no-vig;
  * edge = fair - ask - Kalshi taker fee (1 contract) >= 0.03 on that leg;
  * would-be order: 1 contract at the ask; at most one per (ticker, leg) per
    day; at most $10 of would-be stake per day.

GRADING, on the same thread: each would-be entry's leg mid at +60 s and +300 s
(markout after fee, the in-play CLV stand-in) and, once Kalshi finalises the
market, its settled P&L for one contract.

MODE (`SYNDICATE_INPLAY_ENTRIES_PAPER`): absent/on -> run; off/0/false/no -> off.
Cost: one OddsAPI NHL spreads call per minute while an NHL game is live,
regions us,eu,uk = 3 credits/call -> ~180 credits/h.
"""

from __future__ import annotations

import json
import os
import statistics
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Sequence

MIN_EDGE = 0.03
MIN_BOOKS = 3
MAX_BOOK_QUOTE_AGE_S = 120.0
MAX_BOOK_POLL_AGE_S = 90.0
SCORE_QUIET_S = 180.0
MID_STABLE_WINDOW_S = 60.0
MID_STABLE_MAX_MOVE = 0.03
DAY_BUDGET_DOLLARS = 10.0
BOOKS_EVERY_S = 60.0
ESPN_EVERY_S = 30.0
MARKOUT_HORIZONS_S = (60, 300)
ODDSAPI = "https://api.the-odds-api.com/v4/sports/icehockey_nhl/odds"
ESPN = "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard"
KALSHI_MARKETS = "https://external-api.kalshi.com/trade-api/v2/markets"


def _float(x: Any) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _ts(s: Any) -> float | None:
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def paper_entries_enabled() -> bool:
    raw = str(os.environ.get("SYNDICATE_INPLAY_ENTRIES_PAPER") or "").strip().lower()
    return raw not in {"off", "0", "false", "no", "disabled"}


def taker_fee_one(price: float) -> float:
    from syndicate.features.shared.venue_fees import kalshi_taker_fee_dollars

    return kalshi_taker_fee_dollars(1, price, fee_multiplier=1.0)


_ALIASES = {"la": "los angeles", "ny": "new york", "st louis": "st. louis"}


def team_match(sub: str, name: str) -> bool:
    s, n = (sub or "").lower().strip(), (name or "").lower()
    s = _ALIASES.get(s, s)
    return bool(s) and (n.startswith(s) or s in n)


def book_fair(event: Mapping[str, Any], team: str, line: float, poll_t: float) -> tuple[float | None, int]:
    """Median no-vig P(`team` covers -`line`) over fresh books with that EXACT line -> (fair, n_books)."""
    ps = []
    for bk in event.get("bookmakers") or []:
        for m in bk.get("markets") or []:
            if m.get("key") != "spreads":
                continue
            if poll_t - (_ts(m.get("last_update")) or 0.0) > MAX_BOOK_QUOTE_AGE_S:
                continue
            oc = m.get("outcomes") or []
            if len(oc) != 2:
                continue
            a, b = oc
            pa, pb = _float(a.get("price")), _float(b.get("price"))
            if not pa or not pb or pa <= 1 or pb <= 1:
                continue
            ia, ib = 1 / pa, 1 / pb
            for o, p in ((a, ia / (ia + ib)), (b, ib / (ia + ib))):
                pt = _float(o.get("point"))
                if pt is not None and abs(pt + line) < 1e-9 and team_match(team, o.get("name")):
                    ps.append(p)
    return (statistics.median(ps) if len(ps) >= MIN_BOOKS else None), len(ps)


def decide(
    *,
    market: Mapping[str, Any],
    event: Mapping[str, Any] | None,
    poll_t: float | None,
    since_score_s: float | None,
    mid_move_60s: float | None,
    now_t: float,
) -> dict[str, Any] | None:
    """The entry rule for ONE Kalshi spread rung. PURE. The best qualifying leg, or None."""
    if event is None or poll_t is None or now_t - poll_t > MAX_BOOK_POLL_AGE_S:
        return None
    if since_score_s is None or since_score_s <= SCORE_QUIET_S:
        return None
    if mid_move_60s is None or mid_move_60s > MID_STABLE_MAX_MOVE:
        return None
    if str(market.get("status") or "") != "active":
        return None
    sub = str(market.get("yes_sub_title") or "")
    line = _float(market.get("floor_strike"))
    if " wins by" not in sub or line is None:
        return None
    team = sub.split(" wins by")[0]
    fair, n = book_fair(event, team, line, poll_t)
    if fair is None:
        return None
    best = None
    for leg, ask, p in (("yes", _float(market.get("yes_ask_dollars")), fair),
                        ("no", _float(market.get("no_ask_dollars")), 1 - fair)):
        if ask is None or not (0.05 <= ask <= 0.95):
            continue
        edge = p - ask - taker_fee_one(ask)
        if edge >= MIN_EDGE and (best is None or edge > best["edge"]):
            best = {"leg": leg, "ask": ask, "fair": round(p, 4), "edge": round(edge, 4), "n_books": n,
                    "team": team, "line": line}
    return best


def leg_mid(market: Mapping[str, Any], leg: str) -> float | None:
    ya, yb = _float(market.get("yes_ask_dollars")), _float(market.get("yes_bid_dollars"))
    if ya is None or yb is None or not (0 < yb <= ya < 1):
        return None
    mid = (ya + yb) / 2
    return mid if leg == "yes" else 1 - mid


def _get(url: str, timeout: float = 10.0) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": "syndicate-inplay-entries-paper/1"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 -- fixed https hosts
        return json.loads(r.read().decode("utf-8"))


class PaperEntryLoop:
    """Polled from the fast exit thread. ESPN every 30 s, books every 60 s, Kalshi every pass."""

    def __init__(
        self,
        *,
        today_fn: Callable[[], str],
        clock: Callable[[], float] = time.time,
        get: Callable[[str], Any] = _get,
        tickers_fn: Callable[[str], list[str]] | None = None,
        load: Callable[[], dict[str, Any]] | None = None,
        persist: Callable[[Mapping[str, Any]], None] | None = None,
    ) -> None:
        self.today_fn, self.clock, self.get = today_fn, clock, get
        self.tickers_fn = tickers_fn or _nhl_spread_tickers
        self.load = load or _load_doc
        self.persist = persist or _persist_doc
        self.doc: dict[str, Any] | None = None
        self.books: dict[str, Any] = {}
        self.books_t: float | None = None
        self.espn: dict[str, Any] = {}
        self.espn_t: float | None = None
        self.last_score: dict[str, tuple] = {}
        self.score_change_t: dict[str, float] = {}
        self.mids: dict[str, list[tuple[float, float]]] = defaultdict(list)
        self.summary_t: float | None = None
        self.window = {"passes": 0, "considered": 0, "signals": 0, "booked": 0}

    # -- inputs ---------------------------------------------------------------
    def _refresh_espn(self, t: float) -> None:
        if self.espn_t is not None and t - self.espn_t < ESPN_EVERY_S:
            return
        d = self.get(ESPN) or {}
        self.espn_t = t
        games = {}
        for ev in d.get("events") or []:
            comp = (ev.get("competitions") or [{}])[0]
            st = ((comp.get("status") or ev.get("status") or {}).get("type") or {}).get("state")
            teams = {(x.get("team") or {}).get("abbreviation"): x.get("score") for x in comp.get("competitors") or []}
            key = "|".join(sorted(k or "" for k in teams))
            score = tuple(sorted((k or "", v) for k, v in teams.items()))
            if key in self.last_score and self.last_score[key] != score:
                self.score_change_t[key] = t
            elif key not in self.last_score and st == "in":
                # First sight of a game already in play (a restart mid-game): we did not see
                # its last score change, so treat it as just now rather than as quiet.
                self.score_change_t[key] = t
            self.last_score[key] = score
            games[key] = {"state": st, "abbrs": [k for k in teams if k]}
        self.espn = games

    def _refresh_books(self, t: float) -> None:
        if self.books_t is not None and t - self.books_t < BOOKS_EVERY_S:
            return
        self.books_t = t
        key = os.environ.get("ODDS_API_KEY") or ""
        if not key:
            self.books = {}
            return
        q = urllib.parse.urlencode({"apiKey": key, "regions": "us,eu,uk", "markets": "spreads", "oddsFormat": "decimal"})
        rows = self.get(f"{ODDSAPI}?{q}") or []
        now_iso = _iso(t)
        self.books = {e["id"]: e for e in rows if str(e.get("commence_time") or "") <= now_iso}

    def _game_key(self, ticker: str) -> str | None:
        parts = ticker.split("-")
        code = parts[1][7:] if len(parts) > 1 else ""
        hits = [k for k, g in self.espn.items() if g["abbrs"] and all(a in code for a in g["abbrs"])]
        return max(hits, key=len) if hits else None

    def _event_for(self, subs: set[str]) -> Mapping[str, Any] | None:
        for e in self.books.values():
            names = (e.get("home_team"), e.get("away_team"))
            if len(subs) >= 2 and all(any(team_match(s, n) for n in names) for s in subs):
                return e
        return None

    def _quotes(self, tickers: Sequence[str]) -> dict[str, Mapping[str, Any]]:
        out: dict[str, Mapping[str, Any]] = {}
        for i in range(0, len(tickers), 50):
            d = self.get(KALSHI_MARKETS + "?limit=100&tickers=" + ",".join(tickers[i:i + 50])) or {}
            for m in d.get("markets") or []:
                out[str(m.get("ticker"))] = m
        return out

    # -- grading ----------------------------------------------------------------
    def _grade(self, entries: dict[str, Any], markets: Mapping[str, Mapping[str, Any]], t: float) -> None:
        for e in entries.values():
            m = markets.get(e["ticker"])
            if m is None:
                continue
            for h in MARKOUT_HORIZONS_S:
                k = f"markout_{h}"
                if e.get(k) is None and t - e["t"] >= h:
                    mid = leg_mid(m, e["leg"])
                    if mid is not None and t - e["t"] <= h + 120:  # too late a read is not this horizon
                        e[k] = round(mid - e["ask"] - e["fee"], 4)
            res = str(m.get("result") or "")
            if e.get("settled") is None and res in ("yes", "no"):
                won = 1.0 if res == e["leg"] else 0.0
                e["settled"] = res
                e["pnl_1c"] = round(won - e["ask"] - e["fee"], 4)

    # -- the pass -----------------------------------------------------------------
    def step(self) -> dict[str, Any]:
        if not paper_entries_enabled():
            return {"status": "off"}
        t = self.clock()
        if self.doc is None:
            self.doc = self.load()
        day = self.today_fn()
        entries = self.doc.setdefault("entries", {})
        open_tickers = sorted({e["ticker"] for e in entries.values() if e.get("settled") is None})
        self._refresh_espn(t)
        live_games = {k for k, g in self.espn.items() if g["state"] == "in"}
        tickers = [tk for tk in self.tickers_fn(day) if self._game_key(tk) in live_games] if live_games else []
        if not tickers and not open_tickers:
            return {"status": "idle", "reason": "no_live_nhl_game"}
        if live_games:
            self._refresh_books(t)
        markets = self._quotes(sorted(set(tickers) | set(open_tickers)))
        self._grade(entries, markets, t)
        subs_by_event: dict[str, set] = defaultdict(set)
        for m in markets.values():
            sub = str(m.get("yes_sub_title") or "")
            if " wins by" in sub:
                subs_by_event[str(m.get("event_ticker"))].add(sub.split(" wins by")[0])
        spent = sum(e["ask"] for e in entries.values() if e.get("day") == day)
        self.window["passes"] += 1
        out = {"status": "ok", "tickers": len(tickers), "signals": 0, "booked": 0}
        for tk in tickers:
            m = markets.get(tk)
            if m is None:
                continue
            mid = leg_mid(m, "yes")
            if mid is not None:
                xs = self.mids[tk]
                xs.append((t, mid))
                del xs[:-16]
            win = [v for (tt, v) in self.mids[tk] if t - tt <= MID_STABLE_WINDOW_S]
            move = (max(win) - min(win)) if len(win) >= 2 else None
            gk = self._game_key(tk)
            since = (t - self.score_change_t[gk]) if gk in self.score_change_t else (float("inf") if gk else None)
            self.window["considered"] += 1
            d = decide(market=m, event=self._event_for(subs_by_event.get(str(m.get("event_ticker")), set())),
                       poll_t=self.books_t if self.books else None, since_score_s=since, mid_move_60s=move, now_t=t)
            if d is None:
                continue
            out["signals"] += 1
            self.window["signals"] += 1
            key = f"{day}:{tk}:{d['leg']}"
            refused = None
            if key in entries:
                refused = "already_today"
            elif spent + d["ask"] > DAY_BUDGET_DOLLARS + 1e-9:
                refused = "day_budget"
            if refused is None:
                entries[key] = {
                    "day": day, "t": t, "at": _iso(t), "ticker": tk, "leg": d["leg"], "ask": d["ask"],
                    "fee": round(taker_fee_one(d["ask"]), 4), "fair": d["fair"], "edge": d["edge"],
                    "n_books": d["n_books"], "line": d["line"], "team": d["team"],
                    "since_score_s": None if since is None else round(min(since, 1e9)),
                    "mid_move_60s": None if move is None else round(move, 4),
                    "markout_60": None, "markout_300": None, "settled": None, "pnl_1c": None,
                }
                spent += d["ask"]
                out["booked"] += 1
                self.window["booked"] += 1
            print(
                f"[inplay_entries_paper] WOULD_ENTER ticker={tk} leg={d['leg']} ask={d['ask']} fair={d['fair']}"
                f" edge={d['edge']} books={d['n_books']} since_score_s={since if since is None else round(min(since, 1e9))}"
                f" mid_move_60s={move} booked={refused is None} refused={refused} day_spend={round(spent, 2)}",
                flush=True,
            )
        self.doc["updated_at"] = _iso(t)
        self.persist(self.doc)
        if self.summary_t is None or t - self.summary_t >= 300:
            graded = [e for e in entries.values() if e.get("markout_300") is not None]
            settled = [e for e in entries.values() if e.get("pnl_1c") is not None]
            print(
                f"[inplay_entries_paper] ENTRY_PASS live_games={len(live_games)} {self.window}"
                f" entries_total={len(entries)} markout300_n={len(graded)}"
                f" markout300_mean={round(sum(e['markout_300'] for e in graded) / len(graded), 4) if graded else None}"
                f" settled_n={len(settled)} pnl_1c_sum={round(sum(e['pnl_1c'] for e in settled), 4) if settled else None}",
                flush=True,
            )
            self.summary_t = t
            self.window = {k: 0 for k in self.window}
        return out


def _doc_path():
    from syndicate.features.shared.refresh_state_store import reports_root

    return reports_root() / "intelligence" / "inplay_entries_paper.json"


def _load_doc() -> dict[str, Any]:
    from syndicate.features.shared.refresh_state_store import read_json_file_result

    payload, ok = read_json_file_result(_doc_path())
    if not ok:
        raise RuntimeError("inplay_entries_paper_unreadable")
    doc = dict(payload or {})
    if not isinstance(doc.get("entries"), dict):
        doc["entries"] = {}
    return doc


def _persist_doc(doc: Mapping[str, Any]) -> None:
    from syndicate.features.shared.refresh_state_store import write_json_file

    write_json_file(_doc_path(), dict(doc))


def _nhl_spread_tickers(day: str) -> list[str]:
    from pathlib import Path

    from syndicate.features.shared.refresh_state_store import reports_root

    p = Path(reports_root()) / "intelligence" / "venue_odds" / f"kalshi__nhl__{day.replace('-', '_')}.json"
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return sorted(t for t, v in (payload.get("markets") or {}).items() if v.get("market") == "spreads")
