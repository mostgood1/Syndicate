"""Do situational factors explain where the CLOSING LINE is wrong?

THIS RUNS BEFORE ANY FEATURE IS BUILT, and that ordering is the point.

The NCAAF model is STRICTLY DOMINATED: r=+0.421 with realised margin (17.8% of
variance, real signal) but its deviation from the market carries w=-0.028, a CI
ruling out even 10% weight. So a new input only helps if it lands in the
**missing 23.8%** of R^2 that the market has and the model does not. An input the
market ALREADY PRICES lands in the shared 17.8% and changes nothing -- which is
exactly how the returning-production feature failed after a 5.8-sigma prior.

So the question is not "do rest and travel affect football games" (obviously yes)
but "does the MARKET MISPRICE them". Those are completely different claims, and
only the second is worth building.

    market_residual = realised_margin - market_margin      (home perspective)
    regress it on each situational variable

A market that prices these correctly leaves a residual uncorrelated with them.
A significant coefficient is a genuine edge; a null means the bookmakers already
have it and building the feature would be re-deriving priced information.

VARIABLES, all derived from the schedule and venue table -- no new data source:

    rest_diff        home rest days - away rest days (bye weeks, short weeks)
    travel_km        away team's distance from its own home venue
    elev_gain_m      game elevation - away team's home elevation (altitude)
    tz_shift_h       timezone hours the away team crosses (body-clock effect)
    neutral_site     both teams travel; home advantage should not apply
    is_dome / grass  surface and roof
    kick_hour_local  night games
    conference_game

NOTE ON SIGN: the residual is from the HOME side, so a POSITIVE coefficient on
`travel_km` means the home team beats the line by more when the away team
travels further -- i.e. the market UNDER-prices travel. Getting this backwards
would invert every conclusion while still producing plausible numbers.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from syndicate.features.football.pick_ledger import load_ledger  # noqa: E402

CFBD = "https://api.collegefootballdata.com"


def _token() -> str:
    tok = os.environ.get("CFBD_API_KEY", "").strip()
    if tok:
        return tok
    env = REPO / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.strip().startswith("CFBD_API_KEY"):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("no CFBD_API_KEY")


def get(url: str, token: str):
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + token,
                                               "User-Agent": "syndicate/1.0"})
    return json.loads(urllib.request.urlopen(req, timeout=90).read().decode())


def haversine(a_lat, a_lon, b_lat, b_lon) -> float:
    R = 6371.0
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp = math.radians(b_lat - a_lat)
    dl = math.radians(b_lon - a_lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(min(1.0, math.sqrt(h)))


TZ_OFFSET = {"America/New_York": -5, "America/Detroit": -5, "America/Indiana/Indianapolis": -5,
             "America/Kentucky/Louisville": -5, "America/Toronto": -5,
             "America/Chicago": -6, "America/Winnipeg": -6, "America/Denver": -7,
             "America/Boise": -7, "America/Phoenix": -7, "America/Los_Angeles": -8,
             "Pacific/Honolulu": -10, "America/Anchorage": -9, "Europe/Dublin": 0, "Europe/London": 0}


def _parse(dt: str):
    try:
        return datetime.fromisoformat(str(dt).replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def ols(y: list[float], x: list[float]) -> tuple[float, float, float]:
    """slope, SE, t for y ~ a + b*x."""
    n = len(y)
    if n < 20:
        return (0.0, 0.0, 0.0)
    mx, my = statistics.fmean(x), statistics.fmean(y)
    sxx = sum((v - mx) ** 2 for v in x)
    if sxx <= 0:
        return (0.0, 0.0, 0.0)
    b = sum((v - mx) * (c - my) for v, c in zip(x, y)) / sxx
    a = my - b * mx
    resid = [c - (a + b * v) for v, c in zip(x, y)]
    s2 = sum(r * r for r in resid) / (n - 2)
    se = (s2 / sxx) ** 0.5
    return (b, se, b / se if se else 0.0)


def build(seasons, token):
    venues = {v["id"]: v for v in get(f"{CFBD}/venues", token) if v.get("id")}
    rows = []
    for season in seasons:
        games = get(f"{CFBD}/games?year={season}&seasonType=regular&classification=fbs", token)
        # each team's own home venue = its modal non-neutral home venue
        home_ct = defaultdict(Counter)
        for g in games:
            if not g.get("neutralSite") and g.get("venueId"):
                home_ct[g.get("homeTeam")][g["venueId"]] += 1
        home_venue = {t: c.most_common(1)[0][0] for t, c in home_ct.items() if c}

        # last game date per team, for rest days
        by_team = defaultdict(list)
        for g in games:
            d = _parse(g.get("startDate"))
            if d:
                by_team[g.get("homeTeam")].append((d, g))
                by_team[g.get("awayTeam")].append((d, g))
        prev = {}
        for t, lst in by_team.items():
            lst.sort(key=lambda x: x[0])
            for i, (d, g) in enumerate(lst):
                prev[(t, g.get("id"))] = lst[i - 1][0] if i > 0 else None

        for g in games:
            gid, d = g.get("id"), _parse(g.get("startDate"))
            if d is None:
                continue
            ven = venues.get(g.get("venueId")) or {}
            away_home = venues.get(home_venue.get(g.get("awayTeam"))) or {}
            hp = prev.get((g.get("homeTeam"), gid))
            ap = prev.get((g.get("awayTeam"), gid))
            rest_h = (d - hp).days if hp else None
            rest_a = (d - ap).days if ap else None

            travel = None
            if ven.get("latitude") and away_home.get("latitude"):
                travel = haversine(away_home["latitude"], away_home["longitude"],
                                   ven["latitude"], ven["longitude"])
            elev_gain = None
            if ven.get("elevation") is not None and away_home.get("elevation") is not None:
                try:
                    elev_gain = float(ven["elevation"]) - float(away_home["elevation"])
                except (TypeError, ValueError):
                    elev_gain = None
            tz = None
            if ven.get("timezone") in TZ_OFFSET and away_home.get("timezone") in TZ_OFFSET:
                tz = TZ_OFFSET[ven["timezone"]] - TZ_OFFSET[away_home["timezone"]]

            rows.append({
                "season": season, "game_id": str(gid),
                "home": g.get("homeTeam"), "away": g.get("awayTeam"),
                "rest_diff": (rest_h - rest_a) if (rest_h is not None and rest_a is not None) else None,
                "travel_km": travel,
                "elev_gain_m": elev_gain,
                "tz_shift_h": tz,
                "neutral_site": 1.0 if g.get("neutralSite") else 0.0,
                "is_dome": 1.0 if ven.get("dome") else 0.0,
                "conference_game": 1.0 if g.get("conferenceGame") else 0.0,
                "kick_hour_utc": float(d.hour),
            })
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seasons", default="2024,2025")
    args = ap.parse_args()
    seasons = [int(s) for s in args.seasons.split(",") if s.strip()]

    # market + realised from the ledger (model column unused, so 2025's leaked
    # model rows are harmless here)
    market = {}
    for s in seasons:
        for r in load_ledger("ncaaf", s):
            if r.spread_close is None or r.realised_margin is None:
                continue
            g = market.setdefault((s, str(r.game_id)), {"a": r.realised_margin, "l": []})
            g["l"].append(r.spread_close)

    situational = build(seasons, _token())
    joined = []
    for row in situational:
        m = market.get((row["season"], row["game_id"]))
        if not m:
            continue
        mk = -statistics.median(m["l"])
        row["residual"] = m["a"] - mk          # + => home beat the line
        joined.append(row)

    print("=" * 78)
    print("DO SITUATIONAL FACTORS EXPLAIN THE CLOSING LINE'S ERROR?")
    print("=" * 78)
    print("  games with market + result: %d" % len(joined))
    if not joined:
        print("  NOTHING JOINED -- check the ledger is built for these seasons.")
        return 1
    res = [r["residual"] for r in joined]
    print("  market residual: mean %+.3f  SD %.2f" % (statistics.fmean(res), statistics.pstdev(res)))
    print()
    print("  %-16s %6s %10s %9s %8s  %s" % ("variable", "n", "slope", "SE", "t", "verdict"))
    print("  " + "-" * 72)
    hits = []
    for var in ("rest_diff", "travel_km", "elev_gain_m", "tz_shift_h",
                "neutral_site", "is_dome", "conference_game", "kick_hour_utc"):
        pairs = [(r[var], r["residual"]) for r in joined if r.get(var) is not None]
        if len(pairs) < 30:
            print("  %-16s %6d   (too few)" % (var, len(pairs)))
            continue
        x = [p[0] for p in pairs]
        y = [p[1] for p in pairs]
        b, se, t = ols(y, x)
        sig = abs(t) >= 2.0
        if sig:
            hits.append(var)
        print("  %-16s %6d %10.4f %9.4f %+8.2f  %s"
              % (var, len(pairs), b, se, t, "SIGNIFICANT" if sig else "priced (null)"))
    print()
    print("  8 variables tested at 95%%: expect ~0.4 false positives by chance.")
    if hits:
        print("  CANDIDATES: %s" % ", ".join(hits))
        print("  NOT a green light -- must replicate out-of-sample on a season not")
        print("  used here, and survive as an ATS edge, before anything is built.")
    else:
        print("  NO CANDIDATES. The market prices every situational factor tested.")
        print("  Building these into the model would re-derive information already")
        print("  in the line -- it lands in the shared 17.8%, not the missing 23.8%.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
