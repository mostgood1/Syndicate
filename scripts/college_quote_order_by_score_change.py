"""College quote-order check (`live_gameline_join.quote_behind_score_verdict`), re-measured against the LAST SCORE CHANGE (lane ncaab-live-resim-capacity, 2026-11-08).

READ-ONLY. Inputs: fleet live-gameline ledgers copied to ./ledgers/<sport>/, ESPN scoreboards + summaries (cached to
./espn/). Population: priceable FULL-GAME spreads / totals (and h2h) records recorded before the quote-order gate
loaded (2026-11-07T16:29:14Z), graded against ESPN finals. Brier diff = (model - y)^2 - (market - y)^2; negative =
model beat the de-vigged market.

Cut 1 (reproduces the gate's table): quote_updated_at - live_state_as_of: < -30 s / within 30 s / > +30 s.
Cut 2 (the question): inside "< -30 s", did a scoring play's ESPN wallclock fall in (quote, as_of]?
  A = no score change between the quote and the state the model saw; B = at least one.
Usage: cd <work dir>; py -3 -I scripts/college_quote_order_by_score_change.py ncaab,wncaab [2026-11-03,...]
Findings: .syndicate/findings_2026-11-08_college_quote_order_by_score_change.md
Sensitivity: the state can only contain plays ESPN had published by as_of, so B is also computed with plays
counted only up to as_of - LAG (LAG = 0, 20, 45 s).
"""
from __future__ import annotations

import json
import math
import random
import re
import sys
import time
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

# Work dir = the CURRENT directory: it must hold ledgers/<sport>/live_gameline_ledger_*.jsonl (copied read-only
# from the fleet's <data>/<sport>_source/data/live_gameline_ledger/); ESPN responses are cached under espn/.
HERE = Path.cwd()
GATE_LOADED = datetime(2026, 11, 7, 16, 29, 14, tzinfo=timezone.utc)
ESPN = {"ncaab": "basketball/mens-college-basketball", "wncaab": "basketball/womens-college-basketball"}
FULL = {"full", "full_game", "game"}
UA = {"User-Agent": "Mozilla/5.0 (research script)"}
DATES = set(sys.argv[2].split(",")) if len(sys.argv) > 2 else set()


def ts(v):
    t = str(v or "").strip()
    if not t:
        return None
    try:
        d = datetime.fromisoformat(t.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name or "").lower())


def fetch_json(url: str, cache: Path):
    if cache.exists():
        try:
            return json.loads(cache.read_text(encoding="utf-8"))
        except Exception:
            pass
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(data), encoding="utf-8")
            time.sleep(0.6)
            return data
        except Exception as exc:  # noqa: BLE001
            print(f"  fetch failed ({attempt + 1}/3) {url}: {type(exc).__name__}", flush=True)
            time.sleep(3)
    return None


def scoreboard(sport: str, date: str):
    compact = date.replace("-", "")
    url = (f"https://site.api.espn.com/apis/site/v2/sports/{ESPN[sport]}/scoreboard"
           f"?dates={compact}&groups=50&limit=500")
    data = fetch_json(url, HERE / "espn" / sport / f"scoreboard_{compact}.json") or {}
    out = {}
    for ev in data.get("events") or []:
        comp = (ev.get("competitions") or [{}])[0]
        teams = {c.get("homeAway"): c for c in comp.get("competitors") or []}
        if "home" not in teams or "away" not in teams:
            continue
        names = []
        for side in ("home", "away"):
            t = teams[side].get("team") or {}
            names.append({norm(t.get(k)) for k in ("displayName", "shortDisplayName", "name", "location") if t.get(k)})
        out[str(ev.get("id"))] = names
    return out


def game_timeline(sport: str, event_id: str):
    url = f"https://site.api.espn.com/apis/site/v2/sports/{ESPN[sport]}/summary?event={event_id}"
    data = fetch_json(url, HERE / "espn" / sport / f"summary_{event_id}.json")
    if not data:
        return None
    comp = ((data.get("header") or {}).get("competitions") or [{}])[0]
    if not ((comp.get("status") or {}).get("type") or {}).get("completed"):
        return None
    sc = {c.get("homeAway"): c.get("score") for c in comp.get("competitors") or []}
    try:
        final_home, final_away = int(sc["home"]), int(sc["away"])
    except Exception:
        return None
    changes, last = [], (0, 0)
    for p in data.get("plays") or []:
        try:
            h, a = int(p.get("homeScore")), int(p.get("awayScore"))
        except Exception:
            continue
        w = ts(p.get("wallclock"))
        if (h, a) != last:
            if w is not None:
                changes.append(w)
            last = (h, a)
    changes.sort()
    return {"final_home": final_home, "final_away": final_away, "changes": changes,
            "n_plays": len(data.get("plays") or [])}


def match(index, home: str, away: str):
    h, a = norm(home), norm(away)
    hits = [eid for eid, (hn, an) in index.items()
            if (h in hn or any(x and (h.startswith(x) or x.startswith(h)) for x in hn if len(x) >= 6))
            and (a in an or any(x and (a.startswith(x) or x.startswith(a)) for x in an if len(x) >= 6))]
    return hits[0] if len(hits) == 1 else None


def outcome(rec, g):
    line = rec.get("line")
    m = rec.get("market")
    if m != "h2h" and not isinstance(line, (int, float)):
        return None
    if m == "totals":
        tot = g["final_home"] + g["final_away"]
        return None if tot == line else (1.0 if tot > line else 0.0)
    if m == "spreads":
        # The ledger's spread `line` is a threshold on the HOME margin (P(home margin > line)); measured: the
        # model's own margin agrees with that reading in 8,971 of 8,986 priced ncaab records (11-03..11-05).
        v = g["final_home"] - g["final_away"] - float(line)
        return None if v == 0 else (1.0 if v > 0 else 0.0)
    if m == "h2h":
        return 1.0 if g["final_home"] > g["final_away"] else 0.0
    return None


def clustered(rows):
    """mean Brier diff, and a game-clustered standard error (per-game means, equal weight to records)."""
    if not rows:
        return None
    by = defaultdict(list)
    for gid, d in rows:
        by[gid].append(d)
    n = len(rows)
    mean = sum(d for _, d in rows) / n
    g = len(by)
    if g < 2:
        return mean, float("nan"), n, g
    # cluster-robust SE of a mean: sqrt(sum_g (sum_i (d_i - mean))^2) / n
    s = sum((sum(d - mean for d in ds)) ** 2 for ds in by.values())
    return mean, math.sqrt(s * g / (g - 1)) / n, n, g


def main():
    sports = sys.argv[1].split(",") if len(sys.argv) > 1 else ["ncaab", "wncaab"]
    lags = (0, 20, 45)
    for sport in sports:
        recs = []
        for f in sorted((HERE / "ledgers" / sport).glob("live_gameline_ledger_*.jsonl")):
            with f.open(encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if '"priceable": true' not in line and '"priceable":true' not in line:
                        continue
                    try:
                        r = json.loads(line)
                    except Exception:
                        continue
                    if str(r.get("segment") or "").lower() not in FULL:
                        continue
                    rec_at = ts(r.get("recorded_at"))
                    if rec_at is None or rec_at >= GATE_LOADED:
                        continue
                    if DATES and str(r.get("date")) not in DATES:
                        continue
                    recs.append(r)
        games = {}
        for date in sorted({r["date"] for r in recs}):
            games[date] = scoreboard(sport, date)
        keyed, unmatched = defaultdict(list), set()
        for r in recs:
            eid = match(games.get(r["date"], {}), r.get("home_team"), r.get("away_team"))
            if eid is None:
                unmatched.add((r["date"], r.get("home_team"), r.get("away_team")))
                continue
            keyed[eid].append(r)
        print(f"=== {sport}: {len(recs)} priceable full-game records pre-gate, {len(keyed)} ESPN games matched, "
              f"{len(unmatched)} game keys unmatched", flush=True)
        timelines = {}
        for i, eid in enumerate(sorted(keyed)):
            timelines[eid] = game_timeline(sport, eid)
            if i % 50 == 0:
                print(f"  timelines {i}/{len(keyed)}", flush=True)
        acc = defaultdict(list)  # key -> [(game, diff)]
        skipped = defaultdict(int)
        dates_used = set()
        for eid, rs in keyed.items():
            g = timelines.get(eid)
            if not g:
                skipped["no_final_or_summary"] += len(rs)
                continue
            if not g["changes"]:
                skipped["no_wallclocks"] += len(rs)
                continue
            for r in rs:
                q, a = ts(r.get("quote_updated_at")), ts(r.get("live_state_as_of"))
                pm, pk = r.get("model_home_win_prob"), r.get("market_fair_prob")
                y = outcome(r, g)
                if q is None or a is None or not isinstance(pm, (int, float)) or not isinstance(pk, (int, float)):
                    skipped["missing_field"] += 1
                    continue
                if y is None:
                    skipped["push_or_no_line"] += 1
                    continue
                dates_used.add(r["date"])
                diff = (pm - y) ** 2 - (pk - y) ** 2
                m = r["market"]
                d = (q - a).total_seconds()
                b1 = "older30" if d < -30 else ("within30" if d <= 30 else "newer30")
                acc[(m, b1)].append((eid, diff))
                if m == "totals" and isinstance(r.get("model_total_mean"), (int, float)):
                    fin = g["final_home"] + g["final_away"]
                    acc[("totals_bias", b1 + "|model_minus_final")].append((eid, float(r["model_total_mean"]) - fin))
                    acc[("totals_bias", b1 + "|line_minus_final")].append((eid, float(r["line"]) - fin))
                if b1 == "older30":
                    for lag in lags:
                        hi = a.timestamp() - lag
                        n_ch = sum(1 for w in g["changes"] if q.timestamp() < w.timestamp() <= hi)
                        part = "A_no_change" if n_ch == 0 else "B_changed"
                        acc[(m, f"older30|lag{lag}|{part}")].append((eid, diff))
                        if lag == 20 and part == "A_no_change":
                            gap = -d
                            gb = "30-90s" if gap < 90 else ("90-180s" if gap < 180 else ("180-300s" if gap < 300 else "300s+"))
                            acc[(m, f"older30|lag20|A_no_change|gap {gb}")].append((eid, diff))
                if b1 == "newer30":
                    n_ch = sum(1 for w in g["changes"] if a.timestamp() < w.timestamp() <= q.timestamp())
                    acc[(m, "newer30|" + ("quote_saw_no_new_score" if n_ch == 0 else "quote_saw_a_newer_score"))].append((eid, diff))
        print(f"  dates graded: {sorted(dates_used)}; skipped {dict(skipped)}")
        for m in ("spreads", "totals", "h2h", "totals_bias"):
            keys = sorted(k for k in acc if k[0] == m)
            for k in keys:
                res = clustered(acc[k])
                if res is None:
                    continue
                mean, se, n, ng = res
                print(f"  {m:7s} {k[1]:42s} n={n:6d} games={ng:4d}  brier(model-market)={mean:+.4f}  se={se:.4f}")
        if unmatched:
            print("  unmatched sample:", sorted(unmatched)[:8])


if __name__ == "__main__":
    main()
