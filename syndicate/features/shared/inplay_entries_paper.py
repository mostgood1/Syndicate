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
    day; at most $50 of would-be stake per day.

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
DAY_BUDGET_DOLLARS = 50.0  # >= the live cap (user 2026-10-23: $50/day), so live never starves
BOOKS_EVERY_S = 60.0
ESPN_EVERY_S = 30.0
MARKOUT_HORIZONS_S = (60, 300)
# KALSHI PUBLIC RATE LIMIT IS SHARED with the live path (LivePrice at submit, the exit loops' quotes, the
# fleet's own Kalshi polling): measured 2026-10-24 00:18Z, this loop's PASS_FAILED 429s came from
# external-api.kalshi.com. So this loop is a polite neighbour: one pass per PASS_EVERY_S (not every 15 s
# thread tick), BATCH_GAP_S between its 50-ticker batches, and a cool-down after any 429.
PASS_EVERY_S = 30.0
BATCH_GAP_S = 0.35
RATE_LIMIT_COOLDOWN_S = 60.0
# ALL-SPORTS EXTENSION (user 2026-10-23, via coordinator 332cb014: "turn it on for all sports").
# Per sport: OddsAPI key, ESPN path, and the score-quiet window. The 180 s window was designed on NHL
# (findings section 6). Basketball scores every ~30 s, so "away from a score" cannot apply there (0 = no
# gate); football and baseball use 120 s. THESE WINDOWS ARE UNTESTED ASSUMPTIONS outside NHL -- the nightly
# sweep (scripts/inplay_rule_sweep.py) is how they get measured. Soccer is NOT included: its moneyline is
# 3-way (draw), which this 2-way no-vig does not price.
SPORTS: dict[str, dict[str, Any]] = {
    "nhl": {"odds": "icehockey_nhl", "espn": "hockey/nhl", "score_quiet_s": 180.0},
    "nba": {"odds": "basketball_nba", "espn": "basketball/nba", "score_quiet_s": 0.0},
    "nfl": {"odds": "americanfootball_nfl", "espn": "football/nfl", "score_quiet_s": 120.0},
    "ncaaf": {"odds": "americanfootball_ncaaf", "espn": "football/college-football", "score_quiet_s": 120.0},
    "mlb": {"odds": "baseball_mlb", "espn": "baseball/mlb", "score_quiet_s": 120.0},
}
ENTRY_SPORTS = tuple(SPORTS)
KINDS = ("spreads", "totals", "h2h")


def oddsapi_url(sport: str) -> str:
    return f"https://api.the-odds-api.com/v4/sports/{SPORTS[sport]['odds']}/odds"


def espn_url(sport: str) -> str:
    return f"https://site.api.espn.com/apis/site/v2/sports/{SPORTS[sport]['espn']}/scoreboard"


ODDSAPI = oddsapi_url("nhl")
ESPN = espn_url("nhl")
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


def book_fair(
    event: Mapping[str, Any], team: str, line: float | None, poll_t: float, *,
    kind: str = "spreads", min_books: int = MIN_BOOKS, max_quote_age_s: float = MAX_BOOK_QUOTE_AGE_S,
) -> tuple[float | None, int]:
    """Median no-vig P(outcome) over fresh books quoting the EXACT same market -> (fair, n_books).

    kind=spreads: P(`team` covers -`line`); kind=totals: P(`team` = "Over"/"Under" at `line`);
    kind=h2h: P(`team` wins), 2-way markets only (a 3-way market with a draw is skipped).
    """
    ps = []
    for bk in event.get("bookmakers") or []:
        for m in bk.get("markets") or []:
            if m.get("key") != kind:
                continue
            if poll_t - (_ts(m.get("last_update")) or 0.0) > max_quote_age_s:
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
                if kind == "spreads":
                    ok = pt is not None and line is not None and abs(pt + line) < 1e-9 and team_match(team, o.get("name"))
                elif kind == "totals":
                    ok = (pt is not None and line is not None and abs(pt - line) < 1e-9
                          and str(o.get("name") or "").strip().lower() == team.strip().lower())
                else:
                    ok = team_match(team, o.get("name"))
                if ok:
                    ps.append(p)
    return (statistics.median(ps) if len(ps) >= min_books else None), len(ps)


def classify(market: Mapping[str, Any]) -> tuple[str, str, float | None] | None:
    """(kind, label, line) for a full-game Kalshi market, or None.

    `X wins by over L` -> spreads (X, L); `Over L ...` on a ...TOTAL family -> totals ("Over", L);
    a ...GAME family whose subtitle names a team -> h2h (team, None). A tie/draw leg is never h2h.
    """
    sub = str(market.get("yes_sub_title") or "")
    line = _float(market.get("floor_strike"))
    fam = str(market.get("ticker") or "").split("-")[0]
    if " wins by" in sub and line is not None:
        return "spreads", sub.split(" wins by")[0], line
    if sub.lower().startswith("over") and line is not None and fam.endswith("TOTAL"):
        return "totals", "Over", line
    if fam.endswith("GAME") and sub and "tie" not in sub.lower() and "draw" not in sub.lower():
        return "h2h", sub, None
    return None


def human_selection(kind: str, team: str, line: float | None, leg: str, event: Mapping[str, Any]) -> tuple[str, float | None]:
    """(side, line) the way PREGAME orders carry them, so the portfolio can say what was bought. PURE.

    Must map back to the SAME Kalshi contract through kalshi_orders._side_to_kalshi:
      totals : YES -> ("over", L)            NO -> ("under", L)
      spreads: YES -> (named team home/away, -L)   NO -> (OTHER team home/away, +L)
               (`_spread_side_from_line`: negative line -> YES, positive -> NO)
      h2h    : YES -> (named team home/away, None)  NO -> ("no", None) -- home/away on a moneyline
               ALWAYS means YES on the ticker's team, so a NO leg cannot be relabelled without
               buying the opposite contract; it stays "no" and the row's teams say which game.
    """
    is_home = team_match(team, event.get("home_team")) and not team_match(team, event.get("away_team"))
    named, other = ("home", "away") if is_home else ("away", "home")
    if kind == "totals":
        return ("over" if leg == "yes" else "under"), line
    if kind == "spreads":
        return (named, -abs(float(line))) if leg == "yes" else (other, abs(float(line)))
    return (named, None) if leg == "yes" else ("no", None)


def decide(
    *,
    market: Mapping[str, Any],
    event: Mapping[str, Any] | None,
    poll_t: float | None,
    since_score_s: float | None,
    mid_move_60s: float | None,
    now_t: float,
    params: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """The entry rule for ONE Kalshi full-game market (spread rung, total rung or moneyline). PURE.
    The best qualifying leg, or None.

    `params` overrides the module constants (min_edge, min_books, score_quiet_s,
    mid_max_move, max_book_quote_age_s, max_book_poll_age_s, legs, ask_lo, ask_hi)
    so `scripts/inplay_rule_sweep.py` replays THIS function, not a copy. Absent = today's rule.
    """
    pr = dict(params or {})
    if event is None or poll_t is None or now_t - poll_t > pr.get("max_book_poll_age_s", MAX_BOOK_POLL_AGE_S):
        return None
    if since_score_s is None or since_score_s <= pr.get("score_quiet_s", SCORE_QUIET_S):
        return None
    if mid_move_60s is None or mid_move_60s > pr.get("mid_max_move", MID_STABLE_MAX_MOVE):
        return None
    if str(market.get("status") or "") != "active":
        return None
    cls = classify(market)
    if cls is None or cls[0] not in pr.get("kinds", KINDS):
        return None
    kind, team, line = cls
    fair, n = book_fair(event, team, line, poll_t, kind=kind, min_books=int(pr.get("min_books", MIN_BOOKS)),
                        max_quote_age_s=float(pr.get("max_book_quote_age_s", MAX_BOOK_QUOTE_AGE_S)))
    if fair is None:
        return None
    best = None
    legs = pr.get("legs", ("yes", "no"))
    lo, hi = float(pr.get("ask_lo", 0.05)), float(pr.get("ask_hi", 0.95))
    min_edge = float(pr.get("min_edge", MIN_EDGE))
    for leg, ask, p in (("yes", _float(market.get("yes_ask_dollars")), fair),
                        ("no", _float(market.get("no_ask_dollars")), 1 - fair)):
        if leg not in legs or ask is None or not (lo <= ask <= hi):
            continue
        edge = p - ask - taker_fee_one(ask)
        if edge >= min_edge and (best is None or edge > best["edge"]):
            best = {"leg": leg, "ask": ask, "fair": round(p, 4), "edge": round(edge, 4), "n_books": n,
                    "team": team, "line": line, "kind": kind}
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


def _get_odds(url: str, sport: str, timeout: float = 10.0) -> Any:
    """An OddsAPI call that the fleet's quota telemetry SEES (coordinator ask 2026-10-23).

    Same request as `_get`, plus `oddsapi_quota.record_oddsapi_quota(headers, sport, endpoint=url)`:
    the fleet's per-sport / per-hour / per-family attribution (compare-and-swap, never raises).
    The endpoint is redacted centrally there (`_sanitize_endpoint` strips apiKey).
    """
    req = urllib.request.Request(url, headers={"User-Agent": "syndicate-inplay-entries-paper/1"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 -- fixed https host
        body = json.loads(r.read().decode("utf-8"))
        headers = dict(r.headers.items())
    try:
        from syndicate.features.shared.oddsapi_quota import record_oddsapi_quota

        record_oddsapi_quota(headers, sport=sport, endpoint=url)
    except Exception:  # noqa: BLE001 -- metering must never break the measurement it meters
        pass
    return body


class PaperEntryLoop:
    """Polled from the fast exit thread. Per sport: ESPN every 30 s, books every 60 s, Kalshi every pass.

    `sports` defaults to NHL only (the original cell); the worker passes ENTRY_SPORTS.
    """

    def __init__(
        self,
        *,
        today_fn: Callable[[], str],
        clock: Callable[[], float] = time.time,
        get: Callable[[str], Any] = _get,
        tickers_fn: Callable[[str], list[str]] | None = None,
        load: Callable[[], dict[str, Any]] | None = None,
        persist: Callable[[Mapping[str, Any]], None] | None = None,
        on_book: Callable[[Mapping[str, Any]], Mapping[str, Any] | None] | None = None,
        get_odds: Callable[[str, str], Any] | None = None,
        sports: Sequence[str] = ("nhl",),
    ) -> None:
        self.today_fn, self.clock, self.get = today_fn, clock, get
        # OddsAPI calls are METERED by default. An injected `get` (tests) keeps its own odds path unmetered.
        self.get_odds = get_odds or (_get_odds if get is _get else (lambda url, sport: get(url)))
        self.sports = tuple(s for s in sports if s in SPORTS)
        self.tickers_fn = tickers_fn or _sport_tickers
        self.load = load or _load_doc
        self.persist = persist or _persist_doc
        # Called with each NEWLY booked entry. This module never sends anything;
        # a caller that does (inplay_entries_live, behind its own switch) receives
        # exactly the entries this rule booked, so the two cannot drift apart.
        self.on_book = on_book
        self.doc: dict[str, Any] | None = None
        self.books: dict[str, dict[str, Any]] = {}  # sport -> {event id: event}
        self.books_t: dict[str, float] = {}
        self.espn: dict[str, dict[str, Any]] = {}  # sport -> {game key: {...}}
        self.espn_t: dict[str, float] = {}
        self.last_score: dict[str, tuple] = {}
        self.score_change_t: dict[str, float] = {}
        self.mids: dict[str, list[tuple[float, float]]] = defaultdict(list)
        self.summary_t: float | None = None
        self.last_pass_t: float | None = None
        self.cooldown_until: float = 0.0
        self.sleep: Callable[[float], None] = time.sleep
        self.window = {"passes": 0, "considered": 0, "signals": 0, "booked": 0}

    # -- inputs ---------------------------------------------------------------
    def _refresh_espn(self, sport: str, t: float) -> None:
        if sport in self.espn_t and t - self.espn_t[sport] < ESPN_EVERY_S:
            return
        d = self.get(espn_url(sport)) or {}
        self.espn_t[sport] = t
        games = {}
        for ev in d.get("events") or []:
            comp = (ev.get("competitions") or [{}])[0]
            st = ((comp.get("status") or ev.get("status") or {}).get("type") or {}).get("state")
            teams = {(x.get("team") or {}).get("abbreviation"): x.get("score") for x in comp.get("competitors") or []}
            key = sport + ":" + "|".join(sorted(k or "" for k in teams))
            score = tuple(sorted((k or "", v) for k, v in teams.items()))
            if key in self.last_score and self.last_score[key] != score:
                self.score_change_t[key] = t
            elif key not in self.last_score and st == "in":
                # First sight of a game already in play (a restart mid-game): we did not see
                # its last score change, so treat it as just now rather than as quiet.
                self.score_change_t[key] = t
            self.last_score[key] = score
            games[key] = {"state": st, "abbrs": [k for k in teams if k]}
        self.espn[sport] = games

    def _refresh_books(self, sport: str, t: float) -> None:
        if sport in self.books_t and t - self.books_t[sport] < BOOKS_EVERY_S:
            return
        self.books_t[sport] = t
        key = os.environ.get("ODDS_API_KEY") or ""
        if not key:
            self.books[sport] = {}
            return
        q = urllib.parse.urlencode({"apiKey": key, "regions": "us,eu,uk", "markets": ",".join(KINDS),
                                    "oddsFormat": "decimal"})
        rows = self.get_odds(f"{oddsapi_url(sport)}?{q}", sport) or []
        now_iso = _iso(t)
        self.books[sport] = {e["id"]: e for e in rows if str(e.get("commence_time") or "") <= now_iso}

    def _game_key(self, sport: str, ticker: str) -> str | None:
        parts = ticker.split("-")
        code = parts[1][7:] if len(parts) > 1 else ""
        games = (self.espn.get(sport) or {}).items()
        hits = [k for k, g in games if g["abbrs"] and all(a in code for a in g["abbrs"])]
        return max(hits, key=len) if hits else None

    def _event_for(self, sport: str, subs: set[str]) -> Mapping[str, Any] | None:
        """The ONE live book event every known team name of this game matches, else None.

        One name is enough (a game where Kalshi listed a single moneyline side, or a totals-only game
        whose spread rungs name one team), but only when it picks out exactly one live event: "New York"
        can be two different games, and an ambiguous match is a refusal, not a guess.
        """
        if not subs:
            return None
        hits = [e for e in (self.books.get(sport) or {}).values()
                if all(any(team_match(s, n) for n in (e.get("home_team"), e.get("away_team"))) for s in subs)]
        return hits[0] if len(hits) == 1 else None

    def _quotes(self, tickers: Sequence[str]) -> dict[str, Mapping[str, Any]]:
        out: dict[str, Mapping[str, Any]] = {}
        for n, i in enumerate(range(0, len(tickers), 50)):
            if n:
                self.sleep(BATCH_GAP_S)  # spread the burst: the public limit is shared with the live path
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
        if t < self.cooldown_until:
            return {"status": "cooldown", "until": self.cooldown_until}
        if self.last_pass_t is not None and t - self.last_pass_t < PASS_EVERY_S:
            return {"status": "waiting"}
        self.last_pass_t = t
        try:
            return self._step(t)
        except Exception as exc:
            if getattr(exc, "code", None) == 429:
                self.cooldown_until = t + RATE_LIMIT_COOLDOWN_S
            raise

    def _step(self, t: float) -> dict[str, Any]:
        if self.doc is None:
            self.doc = self.load()
        day = self.today_fn()
        entries = self.doc.setdefault("entries", {})
        open_tickers = sorted({e["ticker"] for e in entries.values() if e.get("settled") is None})
        live_games: set[str] = set()
        tickers: list[tuple[str, str]] = []  # (sport, ticker)
        for sport in self.sports:
            self._refresh_espn(sport, t)
            live = {k for k, g in (self.espn.get(sport) or {}).items() if g["state"] == "in"}
            if not live:
                continue
            live_games |= live
            tickers += [(sport, tk) for tk in self.tickers_fn(day, sport) if self._game_key(sport, tk) in live]
            self._refresh_books(sport, t)
        if not tickers and not open_tickers:
            return {"status": "idle", "reason": "no_live_game"}
        markets = self._quotes(sorted({tk for _, tk in tickers} | set(open_tickers)))
        self._grade(entries, markets, t)
        # Team names per GAME (ticker game code), from moneyline and spread subtitles: a total's subtitle
        # names no team, so it finds its book event through its game's other markets.
        subs_by_game: dict[str, set] = defaultdict(set)
        for m in markets.values():
            cls = classify(m)
            if cls and cls[0] in ("h2h", "spreads"):
                parts = str(m.get("ticker") or "").split("-")
                if len(parts) > 1:
                    subs_by_game[parts[1]].add(cls[1])
        spent = sum(e["ask"] for e in entries.values() if e.get("day") == day)
        self.window["passes"] += 1
        out = {"status": "ok", "tickers": len(tickers), "signals": 0, "booked": 0}
        for sport, tk in tickers:
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
            gk = self._game_key(sport, tk)
            since = (t - self.score_change_t[gk]) if gk in self.score_change_t else (float("inf") if gk else None)
            self.window["considered"] += 1
            game_code = tk.split("-")[1] if "-" in tk else ""
            ev = self._event_for(sport, subs_by_game.get(game_code, set()))
            d = decide(market=m, event=ev,
                       poll_t=self.books_t.get(sport) if self.books.get(sport) else None, since_score_s=since,
                       mid_move_60s=move, now_t=t, params={"score_quiet_s": SPORTS[sport]["score_quiet_s"]})
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
                    "n_books": d["n_books"], "line": d["line"], "team": d["team"], "kind": d["kind"],
                    "sport": sport,
                    # The game, the way pregame orders carry it (portfolio display + R2 per-game pooling):
                    # event_id IS the OddsAPI event id, which the board keys on.
                    "event_id": (ev or {}).get("id"), "home_team": (ev or {}).get("home_team"),
                    "away_team": (ev or {}).get("away_team"), "commence_time": (ev or {}).get("commence_time"),
                    "order_side": human_selection(d["kind"], d["team"], d["line"], d["leg"], ev or {})[0],
                    "order_line": human_selection(d["kind"], d["team"], d["line"], d["leg"], ev or {})[1],
                    "since_score_s": None if since is None else round(min(since, 1e9)),
                    "mid_move_60s": None if move is None else round(move, 4),
                    "markout_60": None, "markout_300": None, "settled": None, "pnl_1c": None,
                }
                spent += d["ask"]
                out["booked"] += 1
                self.window["booked"] += 1
                if self.on_book is not None:
                    try:
                        entries[key]["live"] = dict(self.on_book(dict(entries[key], key=key)) or {})
                    except Exception as exc:  # noqa: BLE001 -- the paper record must survive the hook
                        entries[key]["live"] = {"placed": False, "reason": f"{type(exc).__name__}: {exc}"[:200]}
            print(
                f"[inplay_entries_paper] WOULD_ENTER sport={sport} kind={d['kind']} ticker={tk} leg={d['leg']} ask={d['ask']} fair={d['fair']}"
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


def _sport_tickers(day: str, sport: str = "nhl") -> list[str]:
    """Full-game Kalshi tickers (spreads, totals, h2h) of `sport` on `day`, from the fleet's venue_odds file."""
    from pathlib import Path

    from syndicate.features.shared.refresh_state_store import reports_root

    p = Path(reports_root()) / "intelligence" / "venue_odds" / f"kalshi__{sport}__{day.replace('-', '_')}.json"
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return sorted(t for t, v in (payload.get("markets") or {}).items() if v.get("market") in KINDS)
