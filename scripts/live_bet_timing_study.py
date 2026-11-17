"""When is live betting better? Phase / margin / pace / momentum cuts of the fleet's live game-line ledgers -- READ-ONLY.

Lane live-bet-timing-by-game-shape (user 2026-11-17: "determine if there are ideal times in game shape of each sport to
live bet totals/spreads/mls - based on momentum, timing, game shape etc"). Hypotheses and falsification are in the lane
block (written before this ran); results in `.syndicate/findings_2026-11-17_live_bet_timing.md`.

Run on the fleet (it streams the ledgers in place) with network access to ESPN's public API:

    python3 scripts/live_bet_timing_study.py --sport nba --from 2026-10-20 --to 2026-11-16 \
        --cache /mnt/c/tmp/livetiming/tl --json /mnt/c/tmp/livetiming/nba.json

POPULATION: priced (`priceable`) FULL-GAME records of h2h / spreads / totals (and the alternates, reported apart), joined
to ESPN by slate date + team names; graded on ESPN finals (pushes dropped). Each record is placed in GAME time from the
ESPN play feed at `recorded_at - 20 s` (the feed's publication lag): period, clock, score.

CUTS (each record lands in one bucket per cut):
  phase    share of regulation elapsed: 0-25 / 25-50 / 50-75 / 75-90 / 90-100 % / OT
  margin   |home - away| now: close (<= CLOSE) / mid / lopsided (>= LOPSIDED)
  pace     totals only: points so far vs the record's own line x share elapsed: behind (< 0.9) / on / ahead (> 1.1)
  run      the net score change over the last RUN_WINDOW s of game clock: |net| >= RUN_NET is a run (home or away),
           else none; for totals, the window's points vs the line's pace: hot (> 1.3) / cold (< 0.7) / normal
  vs_run   flags only: does the flag lean WITH the run (the side that just scored / over after a hot window) or AGAINST it

METRICS (every mean is per GAME first -- a game's records in a bucket average to one vote -- then across games; the SE
is across games; 90% CI = mean +- 1.645 SE):
  (A) flags, |edge_pp| >= 3: hit - fair, where fair is the de-vigged price of the side the flag leans to.
  (B) market: y - p_market for the HOME / OVER side (positive = the market under-priced home / over). For runs it is
      signed to the RUN side (positive = the side that just ran was under-priced, i.e. the market under-reacted).
CAVEAT: the price is the ledger's quote at pricing time; whether a bettor could still get it is not measured.
"""
from __future__ import annotations

import argparse
import bisect
import datetime as dt
import glob
import json
import math
import os
import re
import sys
import time
import urllib.request
from collections import defaultdict
from typing import Any

SPORTS: dict[str, dict[str, Any]] = {
    "nba":    {"espn": "basketball/nba", "groups": None, "periods": 4, "plen": 720, "close": 5, "lopsided": 15, "run_window": 240, "run_net": 8},
    "ncaab":  {"espn": "basketball/mens-college-basketball", "groups": "50", "periods": 2, "plen": 1200, "close": 5, "lopsided": 15, "run_window": 240, "run_net": 8},
    "wncaab": {"espn": "basketball/womens-college-basketball", "groups": "50", "periods": 4, "plen": 600, "close": 5, "lopsided": 15, "run_window": 240, "run_net": 8},
    "wnba":   {"espn": "basketball/wnba", "groups": None, "periods": 4, "plen": 600, "close": 5, "lopsided": 15, "run_window": 240, "run_net": 8},
    "nfl":    {"espn": "football/nfl", "groups": None, "periods": 4, "plen": 900, "close": 7, "lopsided": 17, "run_window": 600, "run_net": 7},
    "ncaaf":  {"espn": "football/college-football", "groups": "80", "periods": 4, "plen": 900, "close": 7, "lopsided": 17, "run_window": 600, "run_net": 7},
    "nhl":    {"espn": "hockey/nhl", "groups": None, "periods": 3, "plen": 1200, "close": 1, "lopsided": 3, "run_window": 600, "run_net": 1},
}
MARKETS = ("h2h", "spreads", "totals", "spreads_alt", "totals_alt")
FULL = {"full", "full_game", "game"}
LAG_S = 20.0
UA = {"User-Agent": "Mozilla/5.0 (research script)"}


def ts(v: Any) -> dt.datetime | None:
    t = str(v or "").strip()
    if not t:
        return None
    try:
        d = dt.datetime.fromisoformat(t.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


def norm(s: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def fetch(url: str) -> Any:
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            time.sleep(0.4)
            return data
        except Exception as exc:  # noqa: BLE001
            print(f"  fetch failed ({attempt + 1}/3) {url}: {type(exc).__name__}", flush=True)
            time.sleep(3)
    return None


def scoreboard(sport: str, day: str, cache: str) -> dict[str, list[set[str]]]:
    path = os.path.join(cache, sport, f"sb_{day}.json")
    if os.path.exists(path):
        return {k: [set(x) for x in v] for k, v in json.load(open(path)).items()}
    cfg = SPORTS[sport]
    url = (f"https://site.api.espn.com/apis/site/v2/sports/{cfg['espn']}/scoreboard?dates={day.replace('-', '')}&limit=500"
           + (f"&groups={cfg['groups']}" if cfg["groups"] else ""))
    data = fetch(url) or {}
    out: dict[str, list[set[str]]] = {}
    for ev in data.get("events") or []:
        comp = (ev.get("competitions") or [{}])[0]
        teams = {c.get("homeAway"): c for c in comp.get("competitors") or []}
        if "home" in teams and "away" in teams:
            out[str(ev.get("id"))] = [{norm((teams[s].get("team") or {}).get(k)) for k in ("displayName", "shortDisplayName", "name", "location") if (teams[s].get("team") or {}).get(k)} for s in ("home", "away")]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump({k: [sorted(x) for x in v] for k, v in out.items()}, open(path, "w"))
    return out


def match(index: dict[str, list[set[str]]], home: str, away: str) -> str | None:
    h, a = norm(home), norm(away)
    hits = [eid for eid, (hn, an) in index.items()
            if (h in hn or any(x and len(x) >= 6 and (h.startswith(x) or x.startswith(h)) for x in hn))
            and (a in an or any(x and len(x) >= 6 and (a.startswith(x) or x.startswith(a)) for x in an))]
    return hits[0] if len(hits) == 1 else None


def clock_s(text: Any) -> float | None:
    try:
        parts = str(text).split(":")
        return int(parts[0]) * 60 + float(parts[1]) if len(parts) == 2 else float(parts[0])
    except Exception:  # noqa: BLE001
        return None


def timeline(sport: str, eid: str, cache: str) -> dict[str, Any] | None:
    """Compact per-game timeline [(wallclock_epoch, period, clock_s, home, away)] + final, cached."""
    path = os.path.join(cache, sport, f"tl_{eid}.json")
    if os.path.exists(path):
        doc = json.load(open(path))
        return doc if doc.get("final_home") is not None else None
    data = fetch(f"https://site.api.espn.com/apis/site/v2/sports/{SPORTS[sport]['espn']}/summary?event={eid}")
    doc: dict[str, Any] = {"final_home": None}
    if data:
        comp = ((data.get("header") or {}).get("competitions") or [{}])[0]
        done = bool(((comp.get("status") or {}).get("type") or {}).get("completed"))
        sc = {c.get("homeAway"): c.get("score") for c in comp.get("competitors") or []}
        plays = data.get("plays") or [p for d in ((data.get("drives") or {}).get("previous") or []) for p in (d.get("plays") or [])]
        rows = []
        for p in plays:
            w = ts(p.get("wallclock"))
            per = (p.get("period") or {}).get("number")
            c = clock_s((p.get("clock") or {}).get("displayValue"))
            try:
                h, a = int(p.get("homeScore")), int(p.get("awayScore"))
            except Exception:  # noqa: BLE001
                continue
            if w is None or per is None:
                continue
            rows.append([w.timestamp(), int(per), c, h, a])
        rows.sort(key=lambda r: r[0])
        if done:
            try:
                doc = {"final_home": int(sc["home"]), "final_away": int(sc["away"]), "plays": rows}
            except Exception:  # noqa: BLE001
                pass
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(doc, open(path, "w"))
    return doc if doc.get("final_home") is not None else None


def elapsed_s(sport: str, period: int, clock: float | None) -> tuple[float | None, bool]:
    cfg = SPORTS[sport]
    if period > cfg["periods"]:
        return float(cfg["periods"] * cfg["plen"]), True
    if clock is None:
        return None, False
    return (period - 1) * cfg["plen"] + max(0.0, cfg["plen"] - clock), False


def outcome(market: str, line: Any, fh: int, fa: int) -> float | None:
    if market.startswith("h2h"):
        return None if fh == fa else (1.0 if fh > fa else 0.0)
    if not isinstance(line, (int, float)):
        return None
    if market.startswith("totals"):
        v = fh + fa - float(line)
    else:   # spreads: the ledger's line is a threshold on the HOME margin, P(home margin > line)
        v = fh - fa - float(line)
    return None if v == 0 else (1.0 if v > 0 else 0.0)


def bucket_phase(f: float, ot: bool) -> str:
    if ot:
        return "OT"
    return "0-25" if f < 0.25 else "25-50" if f < 0.5 else "50-75" if f < 0.75 else "75-90" if f < 0.9 else "90-100"


def grade(sport: str, first: str, last: str, ledger_root: str, cache: str) -> dict[str, Any]:
    cfg = SPORTS[sport]
    reg = cfg["periods"] * cfg["plen"]
    files = sorted(glob.glob(os.path.join(ledger_root, f"{sport}_source", "data", "live_gameline_ledger", "live_gameline_ledger_*.jsonl")))
    files = [f for f in files if first <= os.path.basename(f)[21:31] <= last]
    cells_a: dict[tuple, dict[tuple, list[float]]] = defaultdict(lambda: defaultdict(list))
    cells_b: dict[tuple, dict[tuple, list[float]]] = defaultdict(lambda: defaultdict(list))
    stats = defaultdict(int)
    graded_games: set = set()
    for f in files:
        day = os.path.basename(f)[21:31]
        index = None
        by_game: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for line in open(f, encoding="utf-8", errors="replace"):
            if '"priceable":true' not in line and '"priceable": true' not in line:
                continue
            r = json.loads(line)
            if str(r.get("segment") or "").lower() not in FULL or r.get("market") not in MARKETS:
                continue
            if r.get("market_fair_prob") is None or r.get("edge_pp") is None:
                continue
            stats["records"] += 1
            if index is None:
                index = scoreboard(sport, day, cache)
            eid = match(index, r.get("home_team"), r.get("away_team"))
            if eid is None:
                stats["unmatched"] += 1
                continue
            by_game[eid].append(r)
        for eid, recs in by_game.items():
            tl = timeline(sport, eid, cache)
            if tl is None:
                stats["no_final"] += len(recs)
                continue
            plays = tl["plays"]
            if not plays:
                stats["no_plays"] += len(recs)
                continue
            walls = [p[0] for p in plays]
            # game-time index for the run window: elapsed per play, carried forward through clock-less plays
            el, last_el = [], 0.0
            for p in plays:
                e, _ot = elapsed_s(sport, p[1], p[2])
                last_el = e if e is not None else last_el
                el.append(last_el)
            fh, fa = tl["final_home"], tl["final_away"]
            gid = (day, eid)
            for r in recs:
                at = ts(r.get("recorded_at"))
                if at is None:
                    continue
                i = bisect.bisect_right(walls, at.timestamp() - LAG_S) - 1
                if i < 0:
                    stats["before_first_play"] += 1
                    continue
                _w, per, clk, h, a = plays[i]
                e_now, ot = elapsed_s(sport, per, clk)
                if e_now is None:
                    e_now = el[i]
                market = r["market"]
                y = outcome(market, r.get("line"), fh, fa)
                if y is None:
                    continue
                stats["graded"] += 1
                graded_games.add(gid)
                p_mkt = float(r["market_fair_prob"])
                edge = float(r["edge_pp"])
                frac = min(1.0, e_now / reg)
                phase = bucket_phase(frac, ot)
                margin = abs(h - a)
                mb = "close" if margin <= cfg["close"] else "lopsided" if margin >= cfg["lopsided"] else "mid"
                # the run window, in game time
                j = max(0, bisect.bisect_right(el, e_now - cfg["run_window"]) - 1) if e_now >= cfg["run_window"] else None
                if j is not None:
                    hj, aj = plays[j][3], plays[j][4]
                    net = (h - a) - (hj - aj)
                    win_pts = (h + a) - (hj + aj)
                else:
                    net = win_pts = None
                if net is None:
                    run = "early"
                elif abs(net) >= cfg["run_net"]:
                    run = "home_run" if net > 0 else "away_run"
                else:
                    run = "none"
                pace = heat = None
                if market.startswith("totals") and isinstance(r.get("line"), (int, float)) and frac > 0.05 and not ot:
                    ratio = (h + a) / (float(r["line"]) * frac) if float(r["line"]) > 0 else None
                    pace = None if ratio is None else ("behind" if ratio < 0.9 else "ahead" if ratio > 1.1 else "on")
                    if win_pts is not None and float(r["line"]) > 0:
                        exp = float(r["line"]) * cfg["run_window"] / reg
                        heat = "hot" if win_pts > 1.3 * exp else "cold" if win_pts < 0.7 * exp else "normal"
                fam = "alt" if market.endswith("_alt") else "main"
                mk = market.replace("_alt", "")
                cuts = [("all", "all"), ("phase", phase), ("margin", mb)]
                if mk == "totals":
                    if pace:
                        cuts.append(("pace", pace))
                    if heat:
                        cuts.append(("heat", heat))
                    if pace and phase != "OT":
                        cuts.append(("phase_x_pace", f"{phase}|{pace}"))
                else:
                    cuts.append(("run", "run" if run in ("home_run", "away_run") else run))
                cuts.append(("phase_x_margin", f"{phase}|{mb}"))
                # (B) market residual for home/over
                for cut in cuts:
                    cells_b[(mk, fam, "home_or_over") + cut][gid].append(y - p_mkt)
                # (B) signed to the run side (spreads/h2h) or the hot/cold direction (totals)
                if mk != "totals" and run in ("home_run", "away_run"):
                    s = 1.0 if run == "home_run" else -1.0
                    cells_b[(mk, fam, "run_side", "run", "run")][gid].append(s * (y - p_mkt))
                    cells_b[(mk, fam, "run_side", "phase_x_run", phase)][gid].append(s * (y - p_mkt))
                if abs(edge) >= 3:
                    lean_hi = edge > 0
                    won = y if lean_hi else 1.0 - y
                    fair = p_mkt if lean_hi else 1.0 - p_mkt
                    side = ("over" if lean_hi else "under") if mk == "totals" else ("home" if lean_hi else "away")
                    for cut in cuts:
                        cells_a[(mk, fam, side) + cut][gid].append(won - fair)
                        cells_a[(mk, fam, "any") + cut][gid].append(won - fair)
                    if mk != "totals" and run in ("home_run", "away_run"):
                        rel = "with_run" if (lean_hi == (run == "home_run")) else "against_run"
                        cells_a[(mk, fam, "any", "vs_run", rel)][gid].append(won - fair)
                    if mk == "totals" and heat in ("hot", "cold"):
                        rel = "with_heat" if (lean_hi == (heat == "hot")) else "against_heat"
                        cells_a[(mk, fam, "any", "vs_heat", rel)][gid].append(won - fair)
    def summarize(cells):
        out = []
        for key, games in cells.items():
            per = [sum(v) / len(v) for v in games.values()]
            n = len(per)
            m = sum(per) / n if n else float("nan")
            se = math.sqrt(sum((x - m) ** 2 for x in per) / (n - 1) / n) if n > 1 else float("nan")
            out.append({"key": list(key), "games": n, "records": sum(len(v) for v in games.values()),
                        "mean_pp": round(100 * m, 2), "ci90_pp": [round(100 * (m - 1.645 * se), 2), round(100 * (m + 1.645 * se), 2)] if n > 1 else None})
        return sorted(out, key=lambda d: d["key"])
    return {"sport": sport, "window": [first, last], "ledger_days": [os.path.basename(f)[21:31] for f in files],
            "stats": {**dict(stats), "graded_games": len(graded_games)}, "flags": summarize(cells_a), "market": summarize(cells_b)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--sport", required=True, choices=sorted(SPORTS))
    ap.add_argument("--from", dest="first", required=True)
    ap.add_argument("--to", dest="last", required=True)
    ap.add_argument("--ledger-root", default=os.path.expanduser("~/syndicate-prod/data"))
    ap.add_argument("--cache", required=True)
    ap.add_argument("--json", required=True)
    a = ap.parse_args()
    res = grade(a.sport, a.first, a.last, a.ledger_root, a.cache)
    json.dump(res, open(a.json, "w"), indent=1)
    print(json.dumps({"sport": res["sport"], "days": len(res["ledger_days"]), **res["stats"]}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
