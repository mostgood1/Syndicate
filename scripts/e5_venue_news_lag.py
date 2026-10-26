"""E5: after availability news, do Kalshi / Polymarket move LATER than the books? (lane `e5-venue-news-lag`).

Decision Engine plan §4 E5. PRE-REGISTERED in `.syndicate/findings_2026-10-26_e5_venue_news_lag_preregistration.md`
(`d9ce947f`, amendment A1 `0a9b9fed`) before any news x venue or news x book join. Every constant below is the
registered one; change one only through a dated amendment in that file.

READ-ONLY. Reads the fleet data root and sends only unauthenticated GETs to Kalshi's PUBLIC API (1-minute
candlesticks, market metadata). Imports no order, execution or credential code.

    nice -n 19 python3 scripts/e5_venue_news_lag.py --data-root ~/syndicate-prod/data \
        --out /mnt/c/tmp/e5/report.json --cache /mnt/c/tmp/e5/kcache

Clocks: Kalshi = its public 1-min candles (our venue logs keep only the newest 48 points); Polymarket = our own
`venue_odds/polymarket__*` points (no public history); books = `book_quotes` snapshots, a move bracketed by the
previous h2h snapshot of the sport (early) and its own snapshot (late), midpoint primary.
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import random
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from bisect import bisect_left, bisect_right
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.basketball_props_availability import player_key  # noqa: E402
from syndicate.features.shared.news_availability import availability_status, team_key  # noqa: E402
from syndicate.features.shared.opportunity_signals import devig  # noqa: E402
from syndicate.features.shared.venue_fees import taker_fee_per_contract  # noqa: E402

UTC = timezone.utc
ET = ZoneInfo("America/New_York")

# ----------------------------------------------------------------------------- registered constants
SPORTS = ("nba", "nfl", "nhl", "wnba", "mlb")
WINDOW_START = datetime(2026, 10, 13, 19, 31, tzinfo=UTC)
WINDOW_END = datetime(2026, 10, 26, 18, 0, tzinfo=UTC)
NEXT_GAME = timedelta(days=8)
T0_GAP_MAX = timedelta(minutes=25)
BURST = timedelta(minutes=30)
W_MAX = timedelta(minutes=120)
T_END = timedelta(minutes=60)
VENUE_MOVE = 0.02
BOOK_MOVE = 0.01
PLACEBO_OFFSET = timedelta(minutes=60)
PLACEBO_WINDOW = timedelta(minutes=15)
HORIZONS_MIN = (1, 5, 15)
BOOK_FRESH = timedelta(minutes=120)
KALSHI_LOOKBACK = timedelta(hours=24)
PM_ORIENT_LEAD = timedelta(minutes=30)
PM_AMBIGUOUS = 0.08
PM_TAIL = timedelta(minutes=15)
MIN_BOOKS = 2
KILL_LAG_MIN = 2.0
MIN_UNITS, MIN_GAMES = 30, 15
BOOT_DRAWS, SEED = 2000, 20261026

KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"
KALSHI_ML_SERIES = {"nba": "KXNBAGAME", "nfl": "KXNFLGAME", "nhl": "KXNHLGAME", "mlb": "KXMLBGAME",
                    "wnba": "KXWNBAGAME"}
# Venues and exchanges in OddsAPI's bookmaker list: never part of a BOOK set.
NON_BOOKS = {"kalshi", "polymarket", "polymarket_us", "prophetx", "novig", "sporttrade", "betfair_ex_eu",
             "betfair_ex_uk", "betfair_ex_au", "matchbook", "smarkets", "betopenly"}


def parse_ts(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    opener = gzip.open if path.suffix == ".gz" else open
    try:
        with opener(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if isinstance(rec, dict):
                    yield rec
    except (OSError, EOFError):
        return


def unplayable(status: object) -> bool:
    return availability_status(status) is not None


def minutes(delta: timedelta) -> float:
    return delta.total_seconds() / 60.0


# ============================================================================= 1. events


def collector_runs(root: Path, log_path: Path | None = None) -> tuple[dict[str, list[datetime]], str]:
    """Collector run times per feed key (`nba_injuries`, ..., `nhl_gameinfo`).

    Amendment A3: from the collector's own log (`NEWS_COLLECT {json}` per run, quiet runs included); a run counts for
    a feed when its `results` carry the feed and its `errors` do not name it. Fallback (A2): the union of `captured_at`
    over every news log, for every feed -- each log is append-on-change, so it misses quiet runs."""
    runs: dict[str, set[datetime]] = defaultdict(set)
    if log_path and log_path.exists():
        with log_path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if not line.startswith("NEWS_COLLECT "):
                    continue
                try:
                    doc = json.loads(line[len("NEWS_COLLECT "):])
                except ValueError:
                    continue
                t = parse_ts(doc.get("captured_at"))
                errors = doc.get("errors") or {}
                for feed in (doc.get("results") or {}):
                    if t and feed not in errors:
                        runs[feed].add(t)
        if runs:
            return {k: sorted(v) for k, v in runs.items()}, "collector_log"
    stamps: set[datetime] = set()
    for path in (root / "news").glob("*/*/*.jsonl"):
        for rec in _read_jsonl(path):
            t = parse_ts(rec.get("captured_at"))
            if t:
                stamps.add(t)
    union = sorted(stamps)
    return defaultdict(lambda: union), "union_of_news_logs"


def _next_run(runs: list[datetime], t: datetime) -> datetime | None:
    i = bisect_right(runs, t)
    return runs[i] if i < len(runs) else None


def _prev_run(runs: list[datetime], t: datetime) -> datetime | None:
    i = bisect_left(runs, t) - 1
    return runs[i] if i >= 0 else None


def injury_events(records: list[dict[str, Any]], sport: str, all_runs: list[datetime]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Name-level playability flips against the last CONFIRMED state (prereg §1, amendment A2).

    State is keyed by (team_key, player_key), so ESPN's athlete-id churn (a same-run `new` for one id and `cleared`
    for another id of the same name) nets to no change. A flip must still hold at the next collector run (a run with
    no record for this sport changed nothing, so it holds), else it is a `flap` and the confirmed state stands."""
    runs: dict[datetime, list[dict[str, Any]]] = defaultdict(list)
    for rec in records:
        t = parse_ts(rec.get("captured_at"))
        if t:
            runs[t].append(rec)
    order = sorted(runs)
    by_id: dict[str, tuple[tuple[str, str], object]] = {}
    ids_of: dict[tuple[str, str], set[str]] = defaultdict(set)
    confirmed: dict[tuple[str, str], bool] = {}
    display: dict[tuple[str, str], tuple[str, str]] = {}

    def flag(name: tuple[str, str]) -> bool:
        return any(unplayable(by_id[i][1]) for i in ids_of.get(name, ()) if i in by_id)

    counts = {"runs_with_records": len(order), "candidates": 0, "flap": 0, "no_next_run": 0, "t0_uncertain": 0,
              "outside_window": 0, "events": 0}
    events: list[dict[str, Any]] = []
    pending: dict[tuple[str, str], dict[str, Any]] = {}

    def confirm(name: tuple[str, str]) -> None:
        p = pending.pop(name)
        confirmed[name] = p["flag"]
        if p["uncertain"]:
            counts["t0_uncertain"] += 1
        elif not (WINDOW_START <= p["t0"] <= WINDOW_END):
            counts["outside_window"] += 1
        else:
            events.append({"sport": sport, "kind": "to_out" if p["flag"] else "to_in", "source": "espn_injuries",
                           "player": display[name][0], "player_key": name[1], "team": display[name][1],
                           "team_key": name[0], "t0": p["t0"]})

    for k, t in enumerate(order):
        for name in [n for n, p in pending.items() if p["next"] is not None and p["next"] < t]:
            confirm(name)  # its next run wrote nothing for this sport: the state held
        touched: set[tuple[str, str]] = set()
        for rec in runs[t]:
            name = (team_key(sport, rec.get("team")), player_key(rec.get("athlete")))
            if not name[0] or not name[1]:
                continue
            touched.add(name)
            display[name] = (str(rec.get("athlete") or ""), str(rec.get("team") or ""))
            aid = str(rec.get("athlete_id") or f"{name}")
            old = by_id.get(aid)
            if old and old[0] != name:
                ids_of[old[0]].discard(aid)
            if rec.get("event") == "cleared":
                by_id.pop(aid, None)
                ids_of[name].discard(aid)
            else:
                by_id[aid] = (name, rec.get("status"))
                ids_of[name].add(aid)
        for name in [n for n, p in pending.items() if p["next"] == t]:
            if flag(name) == pending[name]["flag"]:
                confirm(name)
            else:
                pending.pop(name)
                counts["flap"] += 1
        if k == 0:  # the first run per sport is a baseline, never an event
            for name in touched:
                confirmed[name] = flag(name)
            continue
        for name in touched:
            if name in pending:
                continue
            now = flag(name)
            if now != confirmed.get(name, False):
                counts["candidates"] += 1
                prev = _prev_run(all_runs, t)
                pending[name] = {"flag": now, "t0": t, "next": _next_run(all_runs, t),
                                 "uncertain": prev is None or t - prev > T0_GAP_MAX}
    for name in list(pending):
        if pending[name]["next"] is None:
            pending.pop(name)
            counts["no_next_run"] += 1
        else:
            confirm(name)
    counts["events"] = len(events)
    return events, counts


def scratch_events(records: list[dict[str, Any]], all_runs: list[datetime]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """NHL: first sighting of (game, player) in a scratch list; dropped as `flap` if absent at the game's last
    capture before puck drop."""
    by_game: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for rec in records:
        if parse_ts(rec.get("captured_at")):
            by_game[str(rec.get("game_id"))].append(rec)
    counts = {"candidates": 0, "flap": 0, "t0_uncertain": 0, "events": 0}
    events = []
    for game_id, recs in by_game.items():
        recs.sort(key=lambda r: parse_ts(r["captured_at"]))
        start = parse_ts(recs[-1].get("start_utc"))
        before = [r for r in recs if start is None or parse_ts(r["captured_at"]) < start]
        if not before:
            continue
        last = before[-1]
        last_names = {player_key(i.get("name")) for side in ("away", "home")
                      for i in (last.get(f"{side}_scratches") or []) if isinstance(i, dict)}
        seen: set[str] = set()
        for rec in before:
            t = parse_ts(rec["captured_at"])
            for side in ("away", "home"):
                for item in rec.get(f"{side}_scratches") or []:
                    if not isinstance(item, dict) or not item.get("name"):
                        continue
                    pk = player_key(item["name"])
                    if pk in seen:
                        continue
                    seen.add(pk)
                    counts["candidates"] += 1
                    if pk not in last_names:
                        counts["flap"] += 1
                        continue
                    prev = _prev_run(all_runs, t)
                    if prev is None or t - prev > T0_GAP_MAX:
                        counts["t0_uncertain"] += 1
                        continue
                    events.append({"sport": "nhl", "kind": "to_out", "source": "nhl_scratch", "player": item["name"],
                                   "player_key": pk, "team": rec.get(side), "team_key": team_key("nhl", rec.get(side)),
                                   "t0": t, "game_start": start, "game_teams": (rec.get("away"), rec.get("home"))})
    events = [e for e in events if WINDOW_START <= e["t0"] <= WINDOW_END]
    counts["events"] = len(events)
    return events, counts


# ============================================================================= 2. books


class Books:
    """One sport's book quotes: games, h2h records, the sport-wide h2h snapshot clock, and prop keys for the
    players named in events."""

    def __init__(self, sport: str) -> None:
        self.sport = sport
        self.games: dict[str, dict[str, Any]] = {}
        self.h2h: dict[str, list[tuple[datetime, str, str, float]]] = defaultdict(list)
        self.snapshots: list[datetime] = []
        self.props: dict[tuple[str, str], list[tuple[datetime, str, str, str, Any, float]]] = defaultdict(list)
        self.files: list[str] = []

    def load(self, root: Path, lo: str, hi: str, players: set[str]) -> None:
        directory = root / f"{self.sport}_source" / "tracking" / "book_quotes"
        groups: dict[str, list[Path]] = defaultdict(list)
        for path in sorted(directory.glob("*.jsonl*")):
            if path.name.endswith(".state.json"):
                continue
            name = path.name.split(".jsonl")[0]
            week = name.split("_wk")[-1] if "_wk" in name else ""
            # NFL weeks 5-8 hold every game an event in the window can reach (week 1 kicked off 2026-09-10).
            if (week.isdigit() and 5 <= int(week) <= 8) or lo <= name <= hi:
                groups[name].append(path)
        seen: set[tuple] = set()
        snaps: set[datetime] = set()
        for name, paths in sorted(groups.items()):
            self.files.append(name)
            for path in paths:
                for r in _read_jsonl(path):
                    if r.get("price") is None or str(r.get("bookmaker") or "").lower() in NON_BOOKS:
                        continue
                    ts = parse_ts(r.get("snapshot_ts")) or parse_ts(r.get("captured_at"))
                    if ts is None:
                        continue
                    eid = str(r.get("event_id"))
                    kind, market = r.get("kind"), r.get("market")
                    if kind == "game" and market == "h2h" and (r.get("segment") in (None, "full")):
                        key = (eid, ts, r.get("bookmaker"), r.get("selection"), r.get("price"))
                        if key in seen:
                            continue
                        seen.add(key)
                        snaps.add(ts)
                        self.games.setdefault(eid, {"home": r.get("home_team"), "away": r.get("away_team"),
                                                    "commence": parse_ts(r.get("commence_time"))})
                        try:
                            self.h2h[eid].append((ts, str(r["bookmaker"]), str(r.get("selection")), float(r["price"])))
                        except (TypeError, ValueError):
                            continue
                    elif kind == "prop":
                        pk = player_key(r.get("player_name"))
                        if pk not in players:
                            continue
                        key = (eid, ts, r.get("bookmaker"), market, r.get("selection"), r.get("line"), pk, r.get("price"))
                        if key in seen:
                            continue
                        seen.add(key)
                        try:
                            self.props[(eid, pk)].append((ts, str(r["bookmaker"]), str(market), str(r.get("selection")),
                                                          r.get("line"), float(r["price"])))
                        except (TypeError, ValueError):
                            continue
        for rows in self.h2h.values():
            rows.sort()
        for rows in self.props.values():
            rows.sort()
        self.snapshots = sorted(snaps)

    def next_game(self, tkey: str, t0: datetime) -> str | None:
        best = None
        for eid, g in self.games.items():
            c = g["commence"]
            if not c or not (t0 < c <= t0 + NEXT_GAME):
                continue
            if tkey and tkey in (team_key(self.sport, g["home"]), team_key(self.sport, g["away"])):
                if best is None or c < self.games[best]["commence"]:
                    best = eid
        return best

    def game_for_scratch(self, ev: dict[str, Any]) -> str | None:
        start = ev.get("game_start")
        want = {team_key("nhl", x) for x in ev.get("game_teams") or ()}
        for eid, g in self.games.items():
            c = g["commence"]
            if start and c and abs(c - start) <= timedelta(hours=3) and \
                    {team_key("nhl", g["home"]), team_key("nhl", g["away"])} == want:
                return eid
        return None

    def team_side(self, eid: str, tkey: str) -> str | None:
        g = self.games[eid]
        if team_key(self.sport, g["home"]) == tkey:
            return "home"
        if team_key(self.sport, g["away"]) == tkey:
            return "away"
        return None

    def prev_snapshot(self, t: datetime) -> datetime | None:
        i = bisect_right(self.snapshots, t - timedelta(microseconds=1)) - 1
        return self.snapshots[i] if i >= 0 else None

    def alive_before(self, t0: datetime) -> bool:
        i = bisect_right(self.snapshots, t0) - 1
        return i >= 0 and t0 - self.snapshots[i] <= BOOK_FRESH


def book_timelines(rows: list[tuple[datetime, str, str, float]], side: str) -> dict[str, list[tuple[datetime, float]]]:
    """book -> [(snapshot, Shin-devigged probability of `side`)] at each time either selection changed."""
    out: dict[str, list[tuple[datetime, float]]] = defaultdict(list)
    latest: dict[str, dict[str, float]] = defaultdict(dict)
    for ts, book, selection, price in rows:
        latest[book][selection] = price
        pair = latest[book]
        if "home" in pair and "away" in pair:
            probs = devig([pair["home"], pair["away"]], method="shin")
            if probs:
                p = probs[0] if side == "home" else probs[1]
                if out[book] and out[book][-1][0] == ts:
                    out[book][-1] = (ts, p)
                else:
                    out[book].append((ts, p))
    return dict(out)


def value_at(series: list[tuple[datetime, Any]], t: datetime) -> Any:
    """Last value at or before t (forward fill); None if the series starts after t."""
    i = bisect_right([s[0] for s in series], t) - 1
    return series[i][1] if i >= 0 else None


def consensus_at(timelines: dict[str, list[tuple[datetime, float]]], books: Iterable[str], t: datetime) -> float | None:
    vals = [v for v in (value_at(timelines[b], t) for b in books if b in timelines) if v is not None]
    return statistics.median(vals) if vals else None


def book_first_move(timelines: dict[str, list[tuple[datetime, float]]], books: list[str], t0: datetime,
                    stop: datetime, s: int, prev_snapshot: Callable[[datetime], datetime | None]) -> dict[str, Any] | None:
    """First snapshot in (t0, stop] at which ANY single book moved >= BOOK_MOVE in direction s from its t0 value."""
    best: tuple[datetime, str] | None = None
    for b in books:
        base = value_at(timelines[b], t0)
        if base is None:
            continue
        for ts, p in timelines[b]:
            if ts <= t0:
                continue
            if ts > stop:
                break
            if s * (p - base) >= BOOK_MOVE:
                if best is None or ts < best[0]:
                    best = (ts, b)
                break
    if best is None:
        return None
    late = best[0]
    early = prev_snapshot(late) or late
    early = max(early, t0)
    return {"book": best[1], "late": late, "early": early, "mid": early + (late - early) / 2}


# ============================================================================= 3. venues


def label_matches(label: object, team_name: object) -> bool:
    """Kalshi team label vs a full team name: `Utah` ~ `Utah Jazz`, `Los Angeles L` ~ `Los Angeles Lakers`,
    `Chicago WS` ~ `Chicago White Sox` (a trailing all-caps token of <= 2 letters = the next words' initials)."""
    lab = " ".join(str(label or "").replace(".", "").split())
    name = " ".join(str(team_name or "").replace(".", "").split())
    if not lab or not name:
        return False
    toks = lab.split(" ")
    initials = None
    if len(toks) > 1 and toks[-1].isupper() and toks[-1].isalpha() and len(toks[-1]) <= 2:
        initials, toks = toks[-1], toks[:-1]
    prefix = " ".join(toks).upper()
    up = name.upper()
    if not (up == prefix or up.startswith(prefix + " ")):
        return False
    if initials is None:
        return True
    rest = up[len(prefix):].split()
    return "".join(w[0] for w in rest[:len(initials)]) == initials.upper()


def kalshi_ml_markets(root: Path, sport: str, commence: datetime) -> dict[str, list[dict[str, Any]]]:
    """event ticker -> its moneyline markets from our venue_odds files for the plausible game dates."""
    series = KALSHI_ML_SERIES.get(sport)
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen: set[str] = set()
    days = {commence.astimezone(ET).date(), commence.date(), (commence - timedelta(hours=12)).astimezone(ET).date()}
    for day in sorted(days):
        path = root / "reports" / "intelligence" / "venue_odds" / f"kalshi__{sport}__{day.isoformat().replace('-', '_')}.json"
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for ticker, m in (doc.get("markets") or {}).items():
            if ticker in seen or m.get("family") != series:
                continue
            seen.add(ticker)
            out[str(m.get("event") or ticker.rsplit("-", 1)[0])].append(
                {"ticker": ticker, "label": m.get("player"), "opened_at": m.get("opened_at")})
    return dict(out)


def match_kalshi_event(events: dict[str, list[dict[str, Any]]], home: str, away: str) -> tuple[str, dict[str, str]] | None:
    """The one event whose exactly-two markets match home and away, one each; side -> ticker."""
    hits = []
    for event, ms in events.items():
        if len(ms) != 2:
            continue
        h = [m for m in ms if label_matches(m["label"], home)]
        a = [m for m in ms if label_matches(m["label"], away)]
        if len(h) == 1 and len(a) == 1 and h[0] is not a[0]:
            hits.append((event, {"home": h[0]["ticker"], "away": a[0]["ticker"]}))
    return hits[0] if len(hits) == 1 else None


def kalshi_prop_markets(root: Path, sport: str, commence: datetime, pk: str) -> list[dict[str, Any]]:
    out = []
    days = {commence.astimezone(ET).date(), commence.date()}
    for day in sorted(days):
        path = root / "reports" / "intelligence" / "venue_odds" / f"kalshi__{sport}__{day.isoformat().replace('-', '_')}.json"
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for ticker, m in (doc.get("markets") or {}).items():
            if str(m.get("market") or "").startswith("player_") and player_key(m.get("player")) == pk:
                out.append({"ticker": ticker, "opened_at": parse_ts(m.get("opened_at")), "market": m.get("market")})
    return out


def pm_ml_market(root: Path, sport: str, kalshi_event: str) -> tuple[str, dict[str, Any]] | None:
    """The Polymarket moneyline whose slug team codes equal the Kalshi event's code part (amendment A1.3)."""
    code_part = kalshi_event.split("-", 1)[1][7:] if "-" in kalshi_event else ""   # 26OCT25 + LALUTA
    date_part = kalshi_event.split("-", 1)[1][:7] if "-" in kalshi_event else ""
    try:
        day = datetime.strptime(date_part, "%y%b%d").date()
    except ValueError:
        return None
    path = root / "reports" / "intelligence" / "venue_odds" / f"polymarket__{sport}__{day.isoformat().replace('-', '_')}.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    hits = []
    for slug, m in (doc.get("markets") or {}).items():
        if m.get("market") != "h2h":
            continue
        codes = str(m.get("event") or "").split("-")
        if len(codes) == 2 and (codes[0] + codes[1]).upper() == code_part.upper():
            hits.append((slug, m))
    return hits[0] if len(hits) == 1 else None


class Kalshi:
    """Unauthenticated GETs to Kalshi's public API, rate-limited, with an on-disk cache."""

    def __init__(self, cache: Path | None, offline: bool = False, min_interval: float = 0.15) -> None:
        self.cache, self.offline, self.min_interval = cache, offline, min_interval
        self.last, self.calls, self.cache_hits = 0.0, 0, 0
        if cache:
            cache.mkdir(parents=True, exist_ok=True)

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = KALSHI_BASE + path + ("?" + urllib.parse.urlencode(params) if params else "")
        key = None
        if self.cache:
            import hashlib
            key = self.cache / (hashlib.sha256(url.encode()).hexdigest()[:32] + ".json")
            if key.exists():
                self.cache_hits += 1
                try:
                    return json.loads(key.read_text(encoding="utf-8"))
                except ValueError:
                    pass
        if self.offline:
            return {}
        backoff = 1.0
        while True:
            wait = self.min_interval - (time.monotonic() - self.last)
            if wait > 0:
                time.sleep(wait)
            self.last = time.monotonic()
            self.calls += 1
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "syndicate-research/1"})
                with urllib.request.urlopen(req, timeout=30) as r:
                    body = json.load(r)
                break
            except urllib.error.HTTPError as e:
                if e.code == 429 or e.code >= 500:
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 60)
                    continue
                body = {}
                break
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                time.sleep(backoff)
                backoff = min(backoff * 2, 60)
        if key is not None:
            key.write_text(json.dumps(body), encoding="utf-8")
        return body

    def candles(self, ticker: str, start: datetime, end: datetime) -> list[tuple[datetime, float | None, float | None]]:
        series = ticker.split("-")[0]
        body = self.get(f"/series/{series}/markets/{ticker}/candlesticks",
                        {"start_ts": int(start.timestamp()), "end_ts": int(end.timestamp()), "period_interval": 1})
        out = []
        for c in body.get("candlesticks") or []:
            def close(side: str) -> float | None:
                v = (c.get(side) or {}).get("close_dollars")
                try:
                    return float(v) if v is not None else None
                except (TypeError, ValueError):
                    return None
            out.append((datetime.fromtimestamp(int(c["end_period_ts"]), UTC), close("yes_bid"), close("yes_ask")))
        out.sort(key=lambda x: x[0])
        return out

    def result(self, ticker: str) -> str | None:
        m = self.get(f"/markets/{ticker}").get("market") or {}
        return m.get("result") or None


def kalshi_mid(c: tuple[datetime, float | None, float | None] | None) -> float | None:
    if not c or c[1] is None or c[2] is None or c[1] <= 0 or c[2] >= 1 or c[2] < c[1]:
        return None
    return (c[1] + c[2]) / 2


def candle_at(candles: list[tuple[datetime, float | None, float | None]], t: datetime):
    i = bisect_right([c[0] for c in candles], t) - 1
    return candles[i] if i >= 0 else None


def series_first_move(series: list[tuple[datetime, float | None]], v0: float, s: int, start: datetime,
                      stop: datetime, threshold: float) -> datetime | None:
    for ts, v in series:
        if ts <= start or v is None:
            continue
        if ts > stop:
            break
        if s * (v - v0) >= threshold:
            return ts
    return None


def any_move(series: list[tuple[datetime, float | None]], v0: float | None, start: datetime, stop: datetime,
             threshold: float) -> bool:
    """Own-prop arm: a move of either sign >= threshold, or the quote withdrawn (mid None), in (start, stop]."""
    for ts, v in series:
        if ts <= start:
            continue
        if ts > stop:
            break
        if v is None or v0 is None or abs(v - v0) >= threshold:
            return True
    return False


# ============================================================================= 4. per-unit measures


def ev(q: float | None, price: float | None, venue: str, ticker: str | None) -> float | None:
    if q is None or price is None or not (0 < price < 1):
        return None
    fee = taker_fee_per_contract(venue, price, venue_ref=ticker)[0]
    return q / (price + fee) - 1


def measure_venue(series: list[tuple[datetime, float | None]], exec_price: Callable[[datetime], float | None],
                  truth: Callable[[datetime], float | None], unit: dict[str, Any], book_move: dict[str, Any] | None,
                  book_move_pl: dict[str, Any] | None, venue: str, ticker: str | None) -> dict[str, Any]:
    """Every registered measure for one unit at one venue. `series` = (t, team-side price);
    `exec_price(t)` = the executable price of the NEWS-FAVOURED side at t; `truth(t)` = that side's book consensus."""
    t0, s, W, t_end = unit["t0"], unit["s"], unit["W"], unit["t_end"]
    v0 = value_at(series, t0)
    out: dict[str, Any] = {"v0": v0}
    if v0 is None:
        return out
    tau_v = series_first_move(series, v0, s, t0, t0 + W, VENUE_MOVE)
    out["tau_v_min"] = None if tau_v is None else round(minutes(tau_v - t0), 2)
    if book_move:
        for bound in ("early", "mid", "late"):
            tb = book_move[bound]
            lag = minutes((tau_v if tau_v is not None else t0 + W) - tb)
            out[f"lag_{bound}"] = round(lag, 2)
        out["lag_censored"] = tau_v is None
    v1, vend = value_at(series, t0 + timedelta(minutes=1)), value_at(series, t_end)
    out["drift"] = None if v1 is None or vend is None else round(s * (vend - v1), 4)
    vpre = value_at(series, t0 - timedelta(minutes=60))
    # DIAGNOSTIC (post hoc, not a registered measure): the team-side price at t0-60 / t0+1 / t_end.
    out.update(v_pre60=vpre, v_1=v1, v_end=vend)
    if vpre is not None and vend is not None and s * (vend - vpre) >= VENUE_MOVE:
        out["pre_share"] = round(s * (v0 - vpre) / (s * (vend - vpre)), 3)
    q = truth(t_end)
    p0 = t0 - PLACEBO_OFFSET
    q_pl = truth(min(p0 + T_END, t_end))
    for h in HORIZONS_MIN:
        out[f"ev_{h}"] = ev(q, exec_price(t0 + timedelta(minutes=h)), venue, ticker)
        out[f"ev_pl_{h}"] = ev(q_pl, exec_price(p0 + timedelta(minutes=h)), venue, ticker)
        if out[f"ev_{h}"] is not None and out[f"ev_pl_{h}"] is not None:
            out[f"ev_inc_{h}"] = out[f"ev_{h}"] - out[f"ev_pl_{h}"]
    out["moved_15"] = tau_v is not None and tau_v <= t0 + PLACEBO_WINDOW
    vp = value_at(series, p0)
    if vp is not None:
        out["moved_15_pl"] = series_first_move(series, vp, s, p0, p0 + PLACEBO_WINDOW, VENUE_MOVE) is not None
    out["book_moved_15"] = bool(book_move and book_move["late"] <= t0 + PLACEBO_WINDOW)
    out["book_moved_15_pl"] = bool(book_move_pl)
    return out


# ============================================================================= 5. statistics


def cluster_boot(rows: list[dict[str, Any]], field: str, stat: str = "mean", draws: int = BOOT_DRAWS,
                 seed: int = SEED) -> dict[str, Any]:
    by_game: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        v = r.get(field)
        if v is None or isinstance(v, bool) and stat != "share":
            continue
        by_game[str(r["game"])].append(float(v))
    games = sorted(by_game)
    vals = [v for g in games for v in by_game[g]]
    if not vals:
        return {"n": 0, "games": 0}
    fn = statistics.median if stat == "median" else statistics.mean
    rng = random.Random(seed)
    boots = []
    for _ in range(draws):
        pick = [v for _g in range(len(games)) for v in by_game[games[rng.randrange(len(games))]]]
        if pick:
            boots.append(fn(pick))
    boots.sort()
    lo, hi = boots[int(0.025 * len(boots))], boots[min(len(boots) - 1, int(0.975 * len(boots)))]
    return {"n": len(vals), "games": len(games), stat: round(fn(vals), 4), "ci95": [round(lo, 4), round(hi, 4)]}


def verdict(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """The registered kill rule and recommendation mapping (prereg §5), for one venue's primary units."""
    lag = {b: cluster_boot([r for r in rows if r.get(f"lag_{b}") is not None], f"lag_{b}", "median")
           for b in ("early", "mid", "late")}
    drift = cluster_boot(rows, "drift", "mean")
    evs = {h: cluster_boot(rows, f"ev_{h}", "mean") for h in HORIZONS_MIN}
    incs = {h: cluster_boot(rows, f"ev_inc_{h}", "mean") for h in HORIZONS_MIN}
    n_units = len({(r["unit_id"]) for r in rows})
    n_games = len({r["game"] for r in rows})
    out: dict[str, Any] = {"units": n_units, "games": n_games, "lag": lag, "drift": drift, "ev": evs, "ev_increment": incs}
    if n_units < MIN_UNITS or n_games < MIN_GAMES or lag["mid"].get("n", 0) == 0:
        out["verdict"] = "UNDERPOWERED"
        return out
    kill_a = {b: lag[b]["median"] < KILL_LAG_MIN for b in lag if lag[b].get("n")}
    kill_b = drift.get("n", 0) == 0 or drift["ci95"][0] <= 0
    out["kill_lag"], out["kill_symmetric"] = kill_a, kill_b
    if not kill_b and len(set(kill_a.values())) > 1:
        out["verdict"] = "UNRESOLVED"
    elif kill_a.get("mid") or kill_b:
        out["verdict"] = "KILL"
    else:
        timing = any(incs[h].get("n") and incs[h]["ci95"][0] > 0 and evs[h].get("n") and evs[h]["mean"] > 0
                     and evs[h]["ci95"][0] > 0 for h in (1, 5))
        out["verdict"] = "PASS_TIMING_STRATEGY" if timing else "PASS_CANCEL_PROTECTION_ONLY"
    return out


# ============================================================================= 6. driver


def build_units(events: list[dict[str, Any]], books: Books, run_time: datetime) -> tuple[list[dict[str, Any]], dict[str, int]]:
    counts = {"no_next_game": 0, "mixed_burst": 0, "merged": 0, "not_commenced": 0}
    keyed: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for ev_ in events:
        eid = books.game_for_scratch(ev_) if ev_["source"] == "nhl_scratch" else books.next_game(ev_["team_key"], ev_["t0"])
        if not eid:
            counts["no_next_game"] += 1
            continue
        keyed[(eid, ev_["team_key"])].append(ev_)
    units = []
    for (eid, tkey), evs in keyed.items():
        evs.sort(key=lambda e: e["t0"])
        bursts: list[list[dict[str, Any]]] = []
        for e in evs:
            if bursts and e["t0"] - bursts[-1][0]["t0"] <= BURST:
                bursts[-1].append(e)
                counts["merged"] += 1
            else:
                bursts.append([e])
        for b in bursts:
            kinds = {e["kind"] for e in b}
            if len(kinds) > 1:
                counts["mixed_burst"] += 1
                continue
            g = books.games[eid]
            t0 = b[0]["t0"]
            if g["commence"] is None or g["commence"] > run_time:
                counts["not_commenced"] += 1
                continue
            kind = b[0]["kind"]
            units.append({"unit_id": f"{books.sport}:{eid}:{tkey}:{t0.isoformat()}", "sport": books.sport, "game": eid,
                          "team_key": tkey, "kind": kind, "s": -1 if kind == "to_out" else 1, "t0": t0,
                          "W": min(W_MAX, g["commence"] - t0), "t_end": min(t0 + T_END, g["commence"] - timedelta(minutes=1)),
                          "commence": g["commence"], "players": [e["player"] for e in b],
                          "player_keys": [e["player_key"] for e in b], "sources": sorted({e["source"] for e in b})})
    return units, counts


def nba_official_out(root: Path) -> set[tuple[str, str]]:
    """(game date, player_key) rows of the date-granular official snapshot that say OUT."""
    import csv
    out: set[tuple[str, str]] = set()
    try:
        with (root / "nba_source" / "data" / "raw" / "injuries.csv").open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                if "OUT" in str(row.get("status") or "").upper():
                    out.add((str(row.get("date") or ""), player_key(row.get("player"))))
    except OSError:
        pass
    return out


def analyze(root: Path, kalshi: Kalshi, sports: Iterable[str] = SPORTS, log: Callable[[str], None] = print,
            collector_log: Path | None = None) -> dict[str, Any]:
    report: dict[str, Any] = {"prereg": "d9ce947f + A1 0a9b9fed", "window": [WINDOW_START.isoformat(), WINDOW_END.isoformat()],
                              "coverage": {}, "counts": {}, "rows": []}
    lo = (WINDOW_START - timedelta(days=1)).date().isoformat()
    hi = (WINDOW_END + timedelta(days=2)).date().isoformat()
    official = nba_official_out(root)
    feed_runs, run_source = collector_runs(root, collector_log)
    report["coverage"]["collector_runs"] = {"source": run_source}
    for feed in [f"{s}_injuries" for s in sports] + (["nhl_gameinfo"] if "nhl" in sports else []):
        rr = feed_runs[feed]
        gaps = [b - a for a, b in zip(rr, rr[1:])]
        report["coverage"]["collector_runs"][feed] = {
            "n": len(rr), "first": rr[0].isoformat() if rr else None, "last": rr[-1].isoformat() if rr else None,
            "gaps_over_25min": sum(1 for g in gaps if g > T0_GAP_MAX),
            "minutes_in_gaps_over_25min": round(sum(minutes(g) for g in gaps if g > T0_GAP_MAX))}
    log(f"E5_RUNS {json.dumps(report['coverage']['collector_runs'])}")
    run_time = datetime.now(UTC)
    for sport in sports:
        inj_files = sorted((root / "news" / sport / "injuries").glob("*.jsonl"))
        records = [r for f in inj_files for r in _read_jsonl(f)]
        events, c_inj = injury_events(records, sport, feed_runs[f"{sport}_injuries"])
        c_scr: dict[str, int] = {}
        if sport == "nhl":
            gi = [r for f in sorted((root / "news" / "nhl" / "gameinfo").glob("*.jsonl")) for r in _read_jsonl(f)]
            scr, c_scr = scratch_events(gi, feed_runs["nhl_gameinfo"])
            events += scr
        books = Books(sport)
        books.load(root, lo, hi, {e["player_key"] for e in events})
        units, c_units = build_units(events, books, run_time)
        cov = {"news_files": [f.stem for f in inj_files], "book_files": books.files,
               "venue_odds_kalshi": sorted(p.stem.split("__")[-1] for p in (root / "reports" / "intelligence" / "venue_odds").glob(f"kalshi__{sport}__*.json")),
               "venue_odds_polymarket": sorted(p.stem.split("__")[-1] for p in (root / "reports" / "intelligence" / "venue_odds").glob(f"polymarket__{sport}__*.json"))}
        report["coverage"][sport] = cov
        counts: dict[str, Any] = {"injury": c_inj, "scratch": c_scr, "units": c_units, "units_built": len(units),
                                  "events_by_kind": {k: sum(1 for e in events if e["kind"] == k) for k in ("to_out", "to_in")}}
        stage = defaultdict(int)
        log(f"E5_COVERAGE sport={sport} news={cov['news_files'][:1]}..{cov['news_files'][-1:]} n={len(cov['news_files'])} "
            f"book_files={len(books.files)} kalshi_files={len(cov['venue_odds_kalshi'])} pm_files={len(cov['venue_odds_polymarket'])} "
            f"events={len(events)} units={len(units)}")
        for unit in units:
            g = books.games[unit["game"]]
            side = books.team_side(unit["game"], unit["team_key"])
            if side is None:
                stage["team_side_unresolved"] += 1
                continue
            t0, s = unit["t0"], unit["s"]
            tl = book_timelines(books.h2h[unit["game"]], side)
            b0 = sorted(b for b in tl if value_at(tl[b], t0) is not None)
            if len(b0) < MIN_BOOKS or not books.alive_before(t0):
                stage["books_ineligible"] += 1
                continue
            stage["books_ok"] += 1
            stop = t0 + unit["W"]
            bm = book_first_move(tl, b0, t0, stop, s, books.prev_snapshot)
            p0 = t0 - PLACEBO_OFFSET
            bm_pl = book_first_move(tl, b0, p0, p0 + PLACEBO_WINDOW, s, books.prev_snapshot)

            def truth_side(t: datetime, _tl=tl, _b0=b0, _s=s) -> float | None:
                q = consensus_at(_tl, _b0, t)
                return None if q is None else (q if _s > 0 else 1 - q)

            impact_book = any(ts <= t0 for pk in unit["player_keys"] for ts, *_ in books.props.get((unit["game"], pk), []))
            kprops = [m for pk in unit["player_keys"] for m in kalshi_prop_markets(root, sport, g["commence"], pk)]
            impact = impact_book or any(m["opened_at"] and m["opened_at"] <= t0 for m in kprops)
            official_ok = None
            if sport == "nba" and unit["kind"] == "to_out":
                gday = g["commence"].astimezone(ET).date().isoformat()
                official_ok = any((gday, pk) in official for pk in unit["player_keys"])
            base = {"unit_id": unit["unit_id"], "sport": sport, "game": unit["game"], "kind": unit["kind"], "t0": t0.isoformat(),
                    "players": unit["players"], "sources": unit["sources"], "impact": impact, "official_out": official_ok,
                    "minutes_to_start": round(minutes(g["commence"] - t0), 1), "n_books": len(b0),
                    "book_move_min": None if not bm else round(minutes(bm["mid"] - t0), 2),
                    "book_bracket_min": None if not bm else round(minutes(bm["late"] - bm["early"]), 2),
                    "book_drift": None}
            bc1, bce = consensus_at(tl, b0, t0 + timedelta(minutes=1)), consensus_at(tl, b0, unit["t_end"])
            if bc1 is not None and bce is not None:
                base["book_drift"] = round(s * (bce - bc1), 4)
            # DIAGNOSTIC (post hoc): the team-side book consensus at t0-60 / t0 / t0+1 / t_end, and the sign.
            base.update(s=s, b_pre60=consensus_at(tl, b0, t0 - timedelta(minutes=60)), b_t0=consensus_at(tl, b0, t0),
                        b_1=bc1, b_end=bce)
            # ---- Kalshi
            kev = kalshi_ml_markets(root, sport, g["commence"])
            hit = match_kalshi_event(kev, g["home"], g["away"])
            if not hit:
                stage["kalshi_identity_refused"] += 1
            else:
                event_ticker, tickers = hit
                ticker = tickers[side]
                cs = kalshi.candles(ticker, t0 - timedelta(hours=6), t0 + unit["W"])
                if not any(c[0] <= t0 and kalshi_mid(c) is not None for c in cs):
                    cs = kalshi.candles(ticker, t0 - KALSHI_LOOKBACK, t0 - timedelta(hours=6)) + cs
                if kalshi_mid(candle_at(cs, t0)) is None:
                    stage["kalshi_no_quote_at_t0"] += 1
                else:
                    stage["kalshi_ok"] += 1
                    series = [(c[0], kalshi_mid(c)) for c in cs]

                    def k_exec(t: datetime, _cs=cs, _s=s) -> float | None:
                        c = candle_at(_cs, t)
                        if not c or c[1] is None or c[2] is None:
                            return None
                        return c[2] if _s > 0 else 1 - c[1]

                    row = dict(base, venue="kalshi", ticker=ticker, **measure_venue(series, k_exec, truth_side, unit, bm, bm_pl, "kalshi", ticker))
                    res = kalshi.result(ticker)
                    if res in ("yes", "no") and row.get("ev_1") is not None:
                        won = (res == "yes") if s > 0 else (res == "no")
                        price = k_exec(t0 + timedelta(minutes=1))
                        if price:
                            row["realised_1"] = (1.0 if won else 0.0) / (price + taker_fee_per_contract("kalshi", price, venue_ref=ticker)[0]) - 1
                    # own-prop arm (descriptive)
                    moved = moved_pl = withdrawn = 0
                    nprops = 0
                    for m in kprops:
                        if not (m["opened_at"] and m["opened_at"] <= t0):
                            continue
                        pc = kalshi.candles(m["ticker"], t0 - timedelta(minutes=90), t0 + PLACEBO_WINDOW)
                        ps = [(c[0], kalshi_mid(c)) for c in pc]
                        m0, mp = value_at(ps, t0), value_at(ps, p0)
                        if m0 is None:
                            continue
                        nprops += 1
                        moved += any_move(ps, m0, t0, t0 + PLACEBO_WINDOW, VENUE_MOVE)
                        withdrawn += any(v is None for ts, v in ps if t0 < ts <= t0 + PLACEBO_WINDOW)
                        moved_pl += any_move(ps, mp, p0, p0 + PLACEBO_WINDOW, VENUE_MOVE) if mp is not None else 0
                    row.update(own_props_kalshi=nprops, own_props_moved=moved, own_props_withdrawn=withdrawn,
                               own_props_moved_pl=moved_pl)
                    keys_pre = {(b, mk, sel, ln) for pk in unit["player_keys"]
                                for ts, b, mk, sel, ln, _p in books.props.get((unit["game"], pk), []) if ts <= t0}
                    keys_new = {(b, mk, sel, ln) for pk in unit["player_keys"]
                                for ts, b, mk, sel, ln, _p in books.props.get((unit["game"], pk), [])
                                if t0 < ts <= t0 + PLACEBO_WINDOW}
                    keys_new_pl = {(b, mk, sel, ln) for pk in unit["player_keys"]
                                   for ts, b, mk, sel, ln, _p in books.props.get((unit["game"], pk), [])
                                   if p0 < ts <= p0 + PLACEBO_WINDOW}
                    row.update(own_props_books=len(keys_pre), own_props_books_moved=len(keys_pre & keys_new),
                               own_props_books_moved_pl=len(keys_pre & keys_new_pl))
                    report["rows"].append(row)
                # ---- Polymarket (lag + INDICATIVE; identity via the Kalshi event, amendment A1.3)
                pm = pm_ml_market(root, sport, event_ticker)
                if not pm:
                    stage["pm_identity_refused"] += 1
                else:
                    slug, m = pm
                    pts = [(parse_ts(p.get("ts")), p.get("yes"), p.get("no")) for p in m.get("points") or []]
                    pts = [p for p in pts if p[0] and p[1] is not None and p[2] is not None]
                    first = pts[0][0] if pts else None
                    last_seen = parse_ts(m.get("last_seen"))
                    if not pts or first > t0 - PM_ORIENT_LEAD or not last_seen or last_seen < t0 + PM_TAIL:
                        stage["pm_ineligible"] += 1
                    else:
                        anchor = value_at([(p[0], p) for p in pts], t0 - PM_ORIENT_LEAD)
                        bq = consensus_at(tl, b0, t0 - PM_ORIENT_LEAD)
                        if anchor is None or bq is None or abs(bq - 0.5) < PM_AMBIGUOUS:
                            stage["pm_orientation_ambiguous"] += 1
                        else:
                            team_is_yes = abs(anchor[1] - bq) <= abs(anchor[2] - bq)
                            series = [(p[0], p[1] if team_is_yes else p[2]) for p in pts]
                            other = [(p[0], p[2] if team_is_yes else p[1]) for p in pts]

                            def pm_exec(t: datetime, _series=series, _other=other, _s=s) -> float | None:
                                return value_at(_series if _s > 0 else _other, t)

                            stage["pm_ok"] += 1
                            report["rows"].append(dict(base, venue="polymarket", ticker=slug,
                                                       **measure_venue(series, pm_exec, truth_side, unit, bm, bm_pl, "polymarket", None)))
        counts["stages"] = dict(stage)
        report["counts"][sport] = counts
        log(f"E5_STAGES sport={sport} {json.dumps(dict(stage), sort_keys=True)} kalshi_calls={kalshi.calls} cache_hits={kalshi.cache_hits}")
    summarize(report, log)
    return report


def summarize(report: dict[str, Any], log: Callable[[str], None] = print) -> None:
    rows = report["rows"]
    out: dict[str, Any] = {}
    for venue in ("kalshi", "polymarket"):
        vr = [r for r in rows if r["venue"] == venue]
        prim = [r for r in vr if r["impact"]]
        block: dict[str, Any] = {"primary": verdict(prim), "all": verdict(vr)}
        dates = sorted({r["t0"][:10] for r in prim})
        block["primary_dates"] = dates
        for kind in ("to_out", "to_in"):
            kr = [r for r in prim if r["kind"] == kind]
            block[f"primary_{kind}"] = {"units": len(kr), "drift": cluster_boot(kr, "drift"),
                                        "lag_mid": cluster_boot([r for r in kr if r.get("lag_mid") is not None], "lag_mid", "median"),
                                        "ev_1": cluster_boot(kr, "ev_1"), "ev_inc_1": cluster_boot(kr, "ev_inc_1")}
        for sport in SPORTS:
            sr = [r for r in prim if r["sport"] == sport]
            if sr:
                block[f"sport_{sport}"] = {"units": len(sr), "games": len({r["game"] for r in sr}),
                                           "lag_mid": cluster_boot([r for r in sr if r.get("lag_mid") is not None], "lag_mid", "median"),
                                           "drift": cluster_boot(sr, "drift"), "ev_1": cluster_boot(sr, "ev_1"),
                                           "ev_inc_1": cluster_boot(sr, "ev_inc_1")}
        def share(field: str, rr: list[dict[str, Any]]) -> float | None:
            v = [bool(r.get(field)) for r in rr if field in r]
            return round(sum(v) / len(v), 3) if v else None
        block["move_rates"] = {"venue_15": share("moved_15", prim), "venue_15_placebo": share("moved_15_pl", prim),
                               "book_15": share("book_moved_15", prim), "book_15_placebo": share("book_moved_15_pl", prim)}
        tv = sorted(r["tau_v_min"] for r in prim if r.get("tau_v_min") is not None)
        bt = sorted(r["book_move_min"] for r in prim if r.get("book_move_min") is not None)
        block["tau_v_min_median"] = statistics.median(tv) if tv else None
        block["book_move_min_median"] = statistics.median(bt) if bt else None
        block["book_bracket_min_median"] = statistics.median([r["book_bracket_min"] for r in prim if r.get("book_bracket_min") is not None] or [0]) if prim else None
        ps = [r["pre_share"] for r in prim if r.get("pre_share") is not None]
        block["pre_share_median"] = statistics.median(ps) if ps else None
        block["pre_share_n"] = len(ps)
        block["book_drift"] = cluster_boot(prim, "book_drift")
        block["realised_1"] = cluster_boot(prim, "realised_1")
        block["lag_censored_share"] = share("lag_censored", [r for r in prim if "lag_censored" in r])
        if venue == "kalshi":
            block["own_props"] = {k: sum(r.get(k, 0) for r in vr) for k in ("own_props_kalshi", "own_props_moved", "own_props_withdrawn",
                                                                             "own_props_moved_pl", "own_props_books", "own_props_books_moved",
                                                                             "own_props_books_moved_pl")}
            nba_out = [r for r in vr if r["sport"] == "nba" and r["kind"] == "to_out" and r.get("official_out") is not None]
            block["nba_official_out_share"] = share("official_out", nba_out)
            block["nba_official_out_n"] = len(nba_out)
        out[venue] = block
        log(f"E5_VERDICT venue={venue} primary={json.dumps({k: block['primary'].get(k) for k in ('units', 'games', 'verdict')})} "
            f"lag_mid={block['primary']['lag'].get('mid')} drift={block['primary']['drift']} ev_1={block['primary']['ev'].get(1)}")
    report["summary"] = out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-root", default=os.environ.get("SYNDICATE_DATA_ROOT") or "")
    ap.add_argument("--sports", default=",".join(SPORTS))
    ap.add_argument("--out", required=True)
    ap.add_argument("--cache", default="")
    ap.add_argument("--offline", action="store_true", help="read the Kalshi cache only")
    ap.add_argument("--collector-log", default="", help="default: <data-root>/../logs/news_collector.log")
    args = ap.parse_args(argv)
    if not args.data_root:
        print("REFUSING: no --data-root", flush=True)
        return 2
    root = Path(os.path.expanduser(args.data_root))
    collector_log = Path(args.collector_log) if args.collector_log else root.parent / "logs" / "news_collector.log"
    kalshi = Kalshi(Path(args.cache) if args.cache else None, offline=args.offline)
    report = analyze(root, kalshi, args.sports.split(","), log=lambda line: print(line, flush=True),
                     collector_log=collector_log)
    Path(args.out).write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    print(f"E5_DONE rows={len(report['rows'])} kalshi_calls={kalshi.calls} cache_hits={kalshi.cache_hits} out={args.out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
