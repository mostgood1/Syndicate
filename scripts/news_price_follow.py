"""How fast do books move after injury news? (lane `news-price-follow`, user 2026-10-14: "do both, start with #1").

The news collector (`scripts/collect_news_snapshots.py`, every 10 min) records WHEN each injury status / NHL scratch
became visible. The quote logs (`<sport>_source/tracking/book_quotes/*.jsonl[.gz]`, append-on-change per book) record
WHEN each book changed each price. Joined, they answer the question the collector was built for: after a material status
change, which books move the player's props and his team's game lines, how many minutes later, and is the price a slow
book leaves up still worth betting against what the fast books now say.

EVENTS (material only):
  to_out   a listed status crosses from playable (Active / Questionable / Doubtful / Day-To-Day / not listed) to
           unplayable (`news_availability.availability_status`: Out, Injured Reserve, Suspension, MLB injured lists),
           or an NHL scratch.
  to_in    unplayable -> playable, or an unplayable player cleared from the list.
  The collector's FIRST run per sport wrote every current injury as `new` -- a baseline, not news -- and is skipped.
  t0 = the collector's `captured_at` (within 10 min of the source; `source_updated_at` is reported beside it).

QUOTES: the player's own props and his team's game lines (h2h / spreads / totals) in his NEXT game (commence after t0,
within 8 days). A quote key is (book, market, selection, player); a record after t0 for that key is a MOVE (the log only
writes changes). A book pulling a line is NOT visible in an append-on-change log -- moves only.

MEASURES
  latency      minutes from t0 to each book's first move on the event's keys (censored at commence).
  placebo      the same keys and books in [t0 - 24 h, t0 - 24 h + W]: the share of books that moved within W with no
               news. lift = news share / placebo share.
  stale EV     at t1 = the first book's first move: for every OTHER book whose last pre-t0 quote is still its latest at
               t1, that price's EV against the median Shin fair of the books that HAVE moved (two-sided pairs at the
               same line). Positive = a slow book left value up.

    python3 scripts/news_price_follow.py --data-root ~/syndicate-prod/data --start 2026-10-13 --end 2026-11-04 --out pf.json
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.basketball_props_availability import player_key  # noqa: E402
from syndicate.features.shared.news_availability import availability_status, team_key  # noqa: E402
from syndicate.features.shared.opportunity_signals import devig  # noqa: E402

SPORTS = ("nfl", "nhl", "nba", "wnba", "mlb")
GAME_MARKETS = {"h2h", "spreads", "totals"}
NEXT_GAME_WINDOW = timedelta(days=8)
PLACEBO_OFFSET = timedelta(hours=24)
WINDOWS_MIN = (15, 60)


def parse_ts(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    opener = gzip.open if path.suffix == ".gz" else open
    try:
        with opener(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                try:
                    yield json.loads(line)
                except ValueError:
                    continue
    except (OSError, EOFError):
        return


def unplayable(status: object) -> bool:
    return availability_status(status) is not None  # incl. MLB injured lists (10-Day-IL ...)


# ----------------------------------------------------------------------------- events


def injury_events(root: Path, sport: str, start: str, end: str) -> list[dict[str, Any]]:
    files = sorted((root / "news" / sport / "injuries").glob("*.jsonl"))
    records = [rec for f in files for rec in _read_jsonl(f)]
    if not records:
        return []
    baseline = min(str(r.get("captured_at") or "") for r in records)  # the collector's first run per sport
    events = []
    for rec in records:
        captured = str(rec.get("captured_at") or "")
        if captured == baseline or not (start <= captured[:10] <= end):
            continue
        kind = None
        if rec.get("event") == "new" and unplayable(rec.get("status")):
            kind = "to_out"
        elif rec.get("event") == "changed":
            before, after = unplayable(rec.get("previous_status")), unplayable(rec.get("status"))
            kind = "to_out" if after and not before else "to_in" if before and not after else None
        elif rec.get("event") == "cleared" and unplayable(rec.get("previous_status")):
            kind = "to_in"
        if kind and rec.get("athlete") and rec.get("team"):
            events.append({"sport": sport, "kind": kind, "source": "espn_injuries", "player": rec["athlete"],
                           "team": rec["team"], "t0": captured, "source_updated_at": rec.get("source_updated_at"),
                           "status": rec.get("status"), "previous_status": rec.get("previous_status")})
    return events


def scratch_events(root: Path, start: str, end: str) -> list[dict[str, Any]]:
    """An NHL player first listed as scratched for a game -> to_out at that capture, for that game only."""
    first_seen: dict[tuple[str, str], dict[str, Any]] = {}
    for f in sorted((root / "news" / "nhl" / "gameinfo").glob("*.jsonl")):
        for rec in _read_jsonl(f):
            captured = str(rec.get("captured_at") or "")
            if not (start <= captured[:10] <= end):
                continue
            for side in ("away", "home"):
                for item in rec.get(f"{side}_scratches") or []:
                    name = item.get("name") if isinstance(item, dict) else None
                    key = (str(rec.get("game_id")), player_key(name))
                    if name and (key not in first_seen or captured < first_seen[key]["t0"]):
                        first_seen[key] = {"sport": "nhl", "kind": "to_out", "source": "nhl_scratch", "player": name,
                                           "team": rec.get(side), "t0": captured, "game_start": rec.get("start_utc")}
    return list(first_seen.values())


# ----------------------------------------------------------------------------- quotes


def load_quotes(root: Path, sport: str, start: str, end: str) -> list[dict[str, Any]]:
    """Quote records from daily files dated start-2 .. end+9 and every weekly file (NFL / NCAAF)."""
    directory = root / f"{sport}_source" / "tracking" / "book_quotes"
    lo = (datetime.fromisoformat(start) - timedelta(days=2)).date().isoformat()
    hi = (datetime.fromisoformat(end) + timedelta(days=9)).date().isoformat()
    candidates: dict[str, list[Path]] = defaultdict(list)
    for path in sorted(directory.glob("*.jsonl*")):
        name = path.name.split(".jsonl")[0]
        if "_wk" in name or lo <= name <= hi:
            candidates[name].append(path)
    out = []
    for paths in candidates.values():
        # The fuller of plain and .gz by LINE count (a .gz is smaller on disk whatever it holds).
        records = max(([r for r in _read_jsonl(p)] for p in paths), key=len)
        out.extend(r for r in records if r.get("kind") in ("prop", "game") and r.get("price") is not None)
    return out


class QuoteIndex:
    def __init__(self, quotes: list[dict[str, Any]], sport: str) -> None:
        self.sport = sport
        self.by_event: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.games: dict[str, dict[str, Any]] = {}
        for q in quotes:
            ts = parse_ts(q.get("captured_at"))
            if ts is None:
                continue
            q = dict(q, _ts=ts, _player=player_key(q.get("player_name")) if q.get("player_name") else "")
            self.by_event[str(q.get("event_id"))].append(q)
            self.games.setdefault(str(q.get("event_id")), {"home": q.get("home_team"), "away": q.get("away_team"),
                                                           "commence": parse_ts(q.get("commence_time"))})
        for rows in self.by_event.values():
            rows.sort(key=lambda r: r["_ts"])

    def next_game(self, team: object, t0: datetime) -> str | None:
        want = team_key(self.sport, team)
        best = None
        for event_id, g in self.games.items():
            if not g["commence"] or not (t0 < g["commence"] <= t0 + NEXT_GAME_WINDOW):
                continue
            if want and want in (team_key(self.sport, g["home"]), team_key(self.sport, g["away"])):
                if best is None or g["commence"] < self.games[best]["commence"]:
                    best = event_id
        return best


def _key(q: dict[str, Any]) -> tuple:
    return (q.get("bookmaker"), q.get("market"), q.get("selection"), q.get("_player"))


def event_quotes(index: QuoteIndex, event: dict[str, Any]) -> tuple[str | None, dict[str, list[dict[str, Any]]]]:
    """The event's next game and its two quote sets: the player's OWN props, and the game lines (h2h/spreads/totals).
    Kept apart: game lines move for many reasons near a game, so only the own-prop set isolates the news."""
    t0 = parse_ts(event["t0"])
    game = index.next_game(event["team"], t0) if t0 else None
    if game is None:
        return None, {}
    pkey = player_key(event["player"])
    rows = index.by_event[game]
    return game, {"own_props": [q for q in rows if q.get("kind") == "prop" and q["_player"] == pkey],
                  "game_lines": [q for q in rows if q.get("kind") == "game" and q.get("market") in GAME_MARKETS]}


def poll_gap_minutes(rows: list[dict[str, Any]], t0: datetime) -> float | None:
    """Median gap between OUR distinct capture times for this game within +-60 min of t0: the timing resolution."""
    stamps = sorted({q["_ts"] for q in rows if abs((q["_ts"] - t0).total_seconds()) <= 3600})
    gaps = [(b - a).total_seconds() / 60 for a, b in zip(stamps, stamps[1:])]
    return round(statistics.median(gaps), 1) if gaps else None


def first_moves(rows: list[dict[str, Any]], start: datetime, stop: datetime) -> dict[str, datetime | None]:
    """book -> its first move in (start, stop] on any key it quoted at or before `start` (None = no move)."""
    quoted_before = {_key(q) for q in rows if q["_ts"] <= start}
    books = {k[0] for k in quoted_before}
    moves: dict[str, datetime | None] = {b: None for b in books}
    for q in rows:
        if start < q["_ts"] <= stop and _key(q) in quoted_before and moves.get(q.get("bookmaker")) is None:
            moves[q.get("bookmaker")] = q["_ts"]
    return moves


def _fair_from_movers(rows: list[dict[str, Any]], t1: datetime, movers: set[str]) -> dict[tuple, float]:
    """(market, player, line, selection) -> median Shin fair over movers' latest two-sided quotes at t1."""
    latest: dict[tuple, dict[str, Any]] = {}
    for q in rows:
        if q.get("bookmaker") in movers and q["_ts"] <= t1:
            latest[(q.get("bookmaker"), q.get("market"), q["_player"], q.get("line"), q.get("selection"))] = q
    pairs: dict[tuple, dict[str, dict[str, float]]] = defaultdict(lambda: defaultdict(dict))
    for (book, market, player, line, selection), q in latest.items():
        pairs[(market, player, line)][book][selection] = float(q["price"])
    fair: dict[tuple, list[float]] = defaultdict(list)
    for (market, player, line), books in pairs.items():
        for book, sides in books.items():
            if len(sides) != 2:
                continue
            names = sorted(sides)
            probs = devig([sides[n] for n in names], method="shin")
            if probs:
                for n, p in zip(names, probs):
                    fair[(market, player, line, n)].append(p)
    return {k: statistics.median(v) for k, v in fair.items()}


def _decimal(american: float) -> float:
    return 1 + (american / 100 if american > 0 else 100 / -american)


def stale_ev(rows: list[dict[str, Any]], t0: datetime, moves: dict[str, datetime | None]) -> list[dict[str, Any]]:
    moved = {b: t for b, t in moves.items() if t is not None}
    if not moved:
        return []
    t1 = min(moved.values())
    movers = {b for b, t in moved.items() if t <= t1}
    fair = _fair_from_movers(rows, t1, movers)
    out = []
    latest_pre: dict[tuple, dict[str, Any]] = {}
    for q in rows:
        if q["_ts"] <= t0:
            latest_pre[_key(q) + (q.get("line"),)] = q
    for key, q in latest_pre.items():
        book = q.get("bookmaker")
        if book in movers or (moves.get(book) is not None and moves[book] <= t1):
            continue
        p = fair.get((q.get("market"), q["_player"], q.get("line"), q.get("selection")))
        if p:
            out.append({"book": book, "market": q.get("market"), "selection": q.get("selection"), "line": q.get("line"),
                        "price": q["price"], "fair": round(p, 4), "ev_pct": round(100 * (p * _decimal(float(q["price"])) - 1), 2)})
    return out


# ----------------------------------------------------------------------------- driver


def measure(rows: list[dict[str, Any]], t0: datetime, commence: datetime | None) -> dict[str, Any] | None:
    """One quote set around one event: per-book latency, the no-news placebo, and the stale quotes' EV."""
    if not rows or not any(q["_ts"] <= t0 for q in rows):
        return None
    news = first_moves(rows, t0, commence or t0 + NEXT_GAME_WINDOW)
    p0 = t0 - PLACEBO_OFFSET
    placebo = first_moves(rows, p0, min(p0 + timedelta(minutes=max(WINDOWS_MIN)), t0))
    lat = {b: (round((t - t0).total_seconds() / 60, 1) if t else None) for b, t in news.items()}
    return {"books": len(news), "latency_min": lat,
            "moved_within": {w: sum(1 for v in lat.values() if v is not None and v <= w) for w in WINDOWS_MIN},
            "placebo_books": len(placebo),
            "placebo_moved_within": {w: sum(1 for t in placebo.values() if t is not None and (t - p0) <= timedelta(minutes=w))
                                     for w in WINDOWS_MIN},
            "stale": stale_ev(rows, t0, news)}


def summarize(measured: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {"events": len(measured)}
    for w in WINDOWS_MIN:
        n_books = sum(m["books"] for m in measured)
        p_books = sum(m["placebo_books"] for m in measured)
        share = sum(m["moved_within"][w] for m in measured) / n_books if n_books else None
        pshare = sum(m["placebo_moved_within"][w] for m in measured) / p_books if p_books else None
        out[f"share_moved_{w}m"] = None if share is None else round(share, 3)
        out[f"placebo_share_{w}m"] = None if pshare is None else round(pshare, 3)
        out[f"lift_{w}m"] = round(share / pshare, 2) if share is not None and pshare else None
    by_book: dict[str, list[float]] = defaultdict(list)
    for m in measured:
        for book, v in m["latency_min"].items():
            if v is not None:
                by_book[book].append(v)
    out["median_latency_min_by_book"] = {b: round(statistics.median(v), 1) for b, v in sorted(by_book.items())}
    stale = [s for m in measured for s in m["stale"]]
    out["stale_quotes"] = len(stale)
    out["stale_events"] = sum(1 for m in measured if m["stale"])
    out["stale_ev_mean_pct"] = round(statistics.mean(s["ev_pct"] for s in stale), 2) if stale else None
    out["stale_ev_positive_share"] = round(sum(1 for s in stale if s["ev_pct"] > 0) / len(stale), 3) if stale else None
    return out


def analyze(root: Path, start: str, end: str, sports: Iterable[str] = SPORTS) -> dict[str, Any]:
    report: dict[str, Any] = {"window": [start, end], "sports": {}}
    for sport in sports:
        events = injury_events(root, sport, start, end) + (scratch_events(root, start, end) if sport == "nhl" else [])
        quotes = load_quotes(root, sport, start, end) if events else []
        index = QuoteIndex(quotes, sport)
        rows_out = []
        for ev in sorted(events, key=lambda e: e["t0"]):
            t0 = parse_ts(ev["t0"])
            game, sets = event_quotes(index, ev)
            if not game:
                rows_out.append({**ev, "game": None, "matched": False})
                continue
            commence = index.games[game]["commence"]
            rows_out.append({**ev, "game": game, "matched": True, "commence": commence.isoformat() if commence else None,
                             "poll_gap_min": poll_gap_minutes(sets["own_props"] + sets["game_lines"], t0),
                             **{name: measure(rows, t0, commence) for name, rows in sets.items()}})
        matched = [r for r in rows_out if r.get("matched")]
        gaps = [r["poll_gap_min"] for r in matched if r.get("poll_gap_min") is not None]
        summary: dict[str, Any] = {
            "events": len(rows_out), "matched": len(matched),
            "by_kind": {k: sum(1 for r in rows_out if r["kind"] == k) for k in ("to_out", "to_in")},
            "median_poll_gap_min": round(statistics.median(gaps), 1) if gaps else None,
        }
        for name in ("own_props", "game_lines"):
            for kind in ("to_out", "to_in"):
                summary[f"{name}.{kind}"] = summarize([r[name] for r in matched if r["kind"] == kind and r.get(name)])
        report["sports"][sport] = {"summary": summary, "events": rows_out}
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-root", default=os.environ.get("SYNDICATE_DATA_ROOT") or "")
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--sports", default=",".join(SPORTS))
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    if not args.data_root:
        print("REFUSING: no --data-root", flush=True)
        return 2
    report = analyze(Path(os.path.expanduser(args.data_root)), args.start, args.end, args.sports.split(","))
    Path(args.out).write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    for sport, body in report["sports"].items():
        print(f"NEWS_PRICE_FOLLOW {sport} {json.dumps(body['summary'], sort_keys=True)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
