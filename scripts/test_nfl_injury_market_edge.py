"""Does the NFL market MISPRICE injuries? Now on SEVENTEEN seasons.

HISTORY OF THIS QUESTION, because the answer moved twice and the movement is
the lesson:

    272 games  (2025 only)      all measures null      -> I wrote "the lever is DEAD"
  1,083 games  (2022-2025)      two measures |t|>2     -> corrected to "UNRESOLVED"
  ~4,400 games (2009-2025)      this run

Calling it dead on one season was an overclaim: the caveat in that section said
n=272 could not detect a small effect, and the headline ignored it. **A null has
a sample size too.**

THE SPEND THAT WAS NOT NEEDED. The plan was an OddsAPI historical backfill of
2018-2021, ~10k credits. Two probes killed that: OddsAPI historical NFL returns
**ZERO events for 2018 and 2019** (coverage starts in 2020), and -- far more
usefully -- **nflverse's `schedules/games.csv` already carries `spread_line` and
`total_line`** for every season back to 1999, in a 2.2 MB file. The odds were
free and local all along. Cost of finding out: 3 credits of probing.

    spread_line SIGN, verified empirically on 6,967 games rather than assumed:
        r(spread_line, home margin) = +0.431
        MAE as-is 10.264   vs   MAE negated 14.645
    It IS the home-margin prediction (positive = home favoured), NOT the
    bookmaker-convention negated spread. Getting this backwards inverts every
    conclusion while still producing plausible numbers.

WHAT IS TESTED. If the line already prices injuries, no estimator -- however
causal -- produces an edge, and the lever is dead for NFL and a fortiori for
NCAAF (which has no injury feed at all).

    market_residual = realised_margin - spread_line     (home side)
    regress on the home-away injury burden differential

AND THREE GUARDS THIS FILE EXISTS TO ENFORCE:

  1. **Per-season replication beside the pooled row.** Pooled significance
     without replication is ONE finding, not seventeen -- on 2022-25 the slope
     ran -0.09 / +0.11 / -0.78 / -0.51, significance carried by two seasons with
     one running the WRONG SIGN. That is the shape that killed returning
     production.
  2. **The direct ATS test**, always printed. A slope IMPLIES an edge; only the
     bets DEMONSTRATE one, and they have disagreed here before.
  3. **A positive control** -- burden must actually vary, or a null is vacuous.

2020 is flagged: COVID altered practice, reporting and crowds. It is included
but reported separately so its influence is visible rather than silent.
"""
from __future__ import annotations

import argparse
import csv
import io
import statistics
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

NFLVERSE = "https://github.com/nflverse/nflverse-data/releases/download"
SKILL = {"QB", "RB", "WR", "TE"}
ALIAS = {"LAR": "LA", "WSH": "WAS", "JAC": "JAX", "OAK": "LV", "SD": "LAC", "STL": "LA"}


def norm(team: str) -> str:
    t = str(team or "").strip().upper()
    return ALIAS.get(t, t)


def _fetch_csv(url: str, cache: Path) -> list[dict]:
    if cache.is_file():
        raw = cache.read_bytes()
    else:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (syndicate)"})
        raw = urllib.request.urlopen(req, timeout=180).read()
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(raw)
    return list(csv.DictReader(io.StringIO(raw.decode("utf-8", errors="ignore"))))


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def load_schedule_games() -> list[dict]:
    """Every REG game with a closing spread AND a final score, all seasons.

    `games.csv` supplies results and the closing line together, so there is no
    join between two sources to get wrong and no odds purchase to make.
    """
    rows = _fetch_csv(f"{NFLVERSE}/schedules/games.csv",
                      REPO / "data" / "nfl_source" / "tracking" / "nflverse" / "schedules_games.csv")
    out = []
    for r in rows:
        if (r.get("game_type") or "") != "REG":
            continue
        hs, as_, sp = _f(r.get("home_score")), _f(r.get("away_score")), _f(r.get("spread_line"))
        if hs is None or as_ is None or sp is None:
            continue
        try:
            season, week = int(r["season"]), int(float(r.get("week") or 0))
        except (TypeError, ValueError, KeyError):
            continue
        out.append({"season": season, "week": week,
                    "home": norm(r.get("home_team")), "away": norm(r.get("away_team")),
                    "residual": (hs - as_) - sp})   # spread_line IS the home margin
    return out


def load_injuries(season: int) -> dict:
    """(team, week) -> burden measures. Empty dict when the season has no file."""
    burden: dict[tuple[str, int], dict[str, float]] = defaultdict(
        lambda: {"out": 0.0, "qb_out": 0.0, "weighted": 0.0, "skill_out": 0.0})
    try:
        rows = _fetch_csv(f"{NFLVERSE}/injuries/injuries_{season}.csv",
                          REPO / "data" / "nfl_source" / "tracking" / "nflverse" / "injuries" / f"injuries_{season}.csv")
    except Exception:
        return {}
    for r in rows:
        if (r.get("season_type") or "REG") != "REG":
            continue
        try:
            wk = int(float(r.get("week") or 0))
        except (TypeError, ValueError):
            continue
        b = burden[(norm(r.get("team")), wk)]
        status = (r.get("report_status") or "").strip().lower()
        pos = (r.get("position") or "").strip().upper()
        if status == "out":
            b["out"] += 1
            b["weighted"] += 1.0
            if pos == "QB":
                b["qb_out"] += 1
            if pos in SKILL:
                b["skill_out"] += 1
        elif status == "doubtful":
            b["weighted"] += 0.6
        elif status == "questionable":
            b["weighted"] += 0.25
    return burden


def ols(y, x):
    n = len(y)
    if n < 25:
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


def wilson(k: int, n: int):
    p = k / n
    z = 1.96
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    m = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return p, max(0.0, c - m), min(1.0, c + m)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from-season", type=int, default=2009)
    ap.add_argument("--to-season", type=int, default=2025)
    args = ap.parse_args()

    print("=" * 78)
    print("DOES THE NFL MARKET MISPRICE INJURIES?  seasons %d-%d" % (args.from_season, args.to_season))
    print("=" * 78)

    games = load_schedule_games()
    rows = []
    per_season_n = {}
    for season in range(args.from_season, args.to_season + 1):
        burden = load_injuries(season)
        if not burden:
            print("  %d: no injury file -- SKIPPED" % season)
            continue
        n0 = len(rows)
        for g in games:
            if g["season"] != season:
                continue
            hb = burden.get((g["home"], g["week"]), {})
            ab = burden.get((g["away"], g["week"]), {})
            rows.append({
                "season": season, "residual": g["residual"],
                "out_diff": hb.get("out", 0.0) - ab.get("out", 0.0),
                "qb_out_diff": hb.get("qb_out", 0.0) - ab.get("qb_out", 0.0),
                "weighted_diff": hb.get("weighted", 0.0) - ab.get("weighted", 0.0),
                "skill_out_diff": hb.get("skill_out", 0.0) - ab.get("skill_out", 0.0),
            })
        per_season_n[season] = len(rows) - n0
        print("  %d: %d games" % (season, per_season_n[season]))

    print("  " + "-" * 60)
    print("  POOLED: %d games across %d seasons" % (len(rows), len(per_season_n)))
    if len(rows) < 200:
        print("  TOO FEW -- a season showing 0 above means its injury file did not load.")
        return 1

    res = [r["residual"] for r in rows]
    se0 = statistics.stdev(res) / len(res) ** 0.5
    print("  market residual  mean %+.3f  SD %.2f  (t %+.2f)"
          % (statistics.fmean(res), statistics.pstdev(res), statistics.fmean(res) / se0))
    print()
    print("  %-16s %6s %10s %9s %8s  %s" % ("burden measure", "n", "slope", "SE", "t", "verdict"))
    print("  " + "-" * 72)
    hits = []
    for var in ("out_diff", "qb_out_diff", "weighted_diff", "skill_out_diff"):
        x = [r[var] for r in rows]
        b, s_, t = ols(res, x)
        sig = abs(t) >= 2.0
        if sig:
            hits.append(var)
        print("  %-16s %6d %10.4f %9.4f %+8.2f  %s"
              % (var, len(x), b, s_, t, "SIGNIFICANT" if sig else "priced (null)"))

    print()
    print("  PER-SEASON, weighted_diff -- REPLICATION is what a pooled row hides:")
    signs = []
    for season in sorted(per_season_n):
        sub = [r for r in rows if r["season"] == season]
        if len(sub) < 50:
            continue
        b, s_, t = ols([r["residual"] for r in sub], [r["weighted_diff"] for r in sub])
        signs.append(b)
        tag = "  <- COVID season" if season == 2020 else ""
        print("    %d  n=%-4d slope %+7.4f  t %+6.2f%s" % (season, len(sub), b, t, tag))
    neg = sum(1 for b in signs if b < 0)
    print("    ---- %d of %d seasons carry the intuitive (negative) sign" % (neg, len(signs)))

    print()
    print("  POSITIVE CONTROL: burden must VARY, or a null is vacuous.")
    for var in ("out_diff", "weighted_diff"):
        x = [r[var] for r in rows]
        print("    %-16s range %+.1f..%+.1f  SD %.2f" % (var, min(x), max(x), statistics.pstdev(x)))

    print()
    print("  DIRECT ATS TEST -- bet the LESS injured side (what you would actually do):")
    for thr in (1.0, 2.0, 4.0, 6.0):
        sel = [r for r in rows if abs(r["weighted_diff"]) >= thr]
        n = len(sel)
        if n < 30:
            print("    |weighted_diff| >= %.0f : %d bets (too few)" % (thr, n))
            continue
        wins = sum(1 for r in sel if (r["residual"] > 0) == (r["weighted_diff"] < 0))
        p, lo, hi = wilson(wins, n)
        flag = "  <-- CLEARS 52.4%" if lo > 0.524 else ""
        print("    |weighted_diff| >= %.0f : %5d bets  %5.1f%% ATS  CI [%.1f, %.1f]%s"
              % (thr, n, 100 * p, 100 * lo, 100 * hi, flag))

    print()
    if hits:
        print("  REGRESSION CANDIDATES: %s" % ", ".join(hits))
        print("  Ship ONLY if the ATS CI lower bound clears 52.4%% AND the per-season")
        print("  signs replicate. Pooled significance with a split sign is one finding.")
    else:
        print("  NO MISPRICING DETECTED across %d seasons." % len(per_season_n))
        print("  At this n the test can detect a slope of ~%.2f pts; anything smaller"
              % (2 * ols(res, [r["weighted_diff"] for r in rows])[1]))
        print("  is beyond reach and is also too small to bet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
