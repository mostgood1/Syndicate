"""Does the NFL market MISPRICE injuries? Test before building an estimator.

THE RECOMMENDATION THIS EXECUTES. NCAAF has no usable injury feed (§12), and
NFL's own injury adjustment was backtested and HURT — 60.98% → 56.44% win
accuracy over 264 games — because its impact estimates were historical averages
confounded by opponent strength and game script. The proposed next step was to
build a CAUSAL estimator on NFL, where the data exists.

**But that is the second question.** The first is whether there is anything to
win at all. The NFL market is the most efficient in sport and injury reports are
MANDATORY and PUBLIC — every book sees the same report at the same time. If the
line already prices injuries, then no estimator, however causal, produces an
edge, and the entire injury lever is dead for BOTH sports rather than just NCAAF.

That question costs minutes; the estimator costs days. This is the same ordering
that killed the situational-factor build in two minutes after returning
production consumed hours for the same kind of answer.

    market_residual = realised_margin − market_margin        (home side)
    regress it on the home−away injury burden differential

A market that prices injuries leaves a residual uncorrelated with them.

BURDEN MEASURES, several because the right weighting is not obvious and picking
one after seeing results would be data mining:

    out_diff        count of players ruled OUT (home − away)
    qb_out_diff     starting-QB-position OUT (home − away) — the single
                    largest known injury effect in football
    weighted_diff   OUT 1.0, DOUBTFUL 0.6, QUESTIONABLE 0.25
    skill_out_diff  OUT at QB/RB/WR/TE only

SIGN: residual is from the HOME side and burden is home−away, so a NEGATIVE
coefficient is the intuitive direction — more home injuries, home underperforms
the line. A positive coefficient would mean the market OVER-prices home injuries.
Getting this backwards would invert the conclusion while looking plausible.
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

NFL = REPO / "data" / "nfl_source"

NICK_TO_ABBR = {
    "cardinals": "ARI", "falcons": "ATL", "ravens": "BAL", "bills": "BUF",
    "panthers": "CAR", "bears": "CHI", "bengals": "CIN", "browns": "CLE",
    "cowboys": "DAL", "broncos": "DEN", "lions": "DET", "packers": "GB",
    "texans": "HOU", "colts": "IND", "jaguars": "JAX", "chiefs": "KC",
    "raiders": "LV", "chargers": "LAC", "rams": "LA", "dolphins": "MIA",
    "vikings": "MIN", "patriots": "NE", "saints": "NO", "giants": "NYG",
    "jets": "NYJ", "eagles": "PHI", "steelers": "PIT", "49ers": "SF",
    "seahawks": "SEA", "buccaneers": "TB", "titans": "TEN", "commanders": "WAS",
}
ALIAS = {"LAR": "LA", "WSH": "WAS", "JAC": "JAX", "OAK": "LV", "SD": "LAC", "STL": "LA"}
SKILL = {"QB", "RB", "WR", "TE"}


def abbr(name: str) -> str | None:
    parts = str(name or "").strip().lower().split()
    return NICK_TO_ABBR.get(parts[-1]) if parts else None


def norm(a: str) -> str:
    a = str(a or "").strip().upper()
    return ALIAS.get(a, a)


def load_games(season: int) -> dict:
    """One row per game from the pbp mirror: teams, week, final score."""
    out: dict[str, dict] = {}
    path = NFL / "tracking" / "nflverse" / "pbp" / f"pbp_{season}.csv"
    if not path.is_file():
        return out
    with path.open("r", encoding="utf-8", errors="ignore", newline="") as fh:
        for row in csv.DictReader(fh):
            gid = row.get("game_id")
            if not gid or gid in out:
                continue
            try:
                out[gid] = {
                    "week": int(float(row.get("week") or 0)),
                    "home": norm(row.get("home_team")),
                    "away": norm(row.get("away_team")),
                    "hs": float(row["home_score"]), "as": float(row["away_score"]),
                    "season_type": row.get("season_type") or "REG",
                }
            except (TypeError, ValueError, KeyError):
                continue
    return {k: v for k, v in out.items() if v["season_type"] == "REG"}


def load_closing_spreads(season: int) -> dict:
    """Closing home spread per matchup.

    TWO SOURCES, because the archive changes shape by season and silently
    returning {} for one of them would drop a whole season while looking like
    a clean run:
      2022-2024  historical_odds/closing_lines_<season>.json -- one captured
                 snapshot per kickoff window, post-kickoff rows already rejected
      2025       real_betting_lines_<date>.json daily files
    """
    archive = NFL / "historical_odds" / f"closing_lines_{season}.json"
    if archive.is_file():
        out: dict[tuple[str, str], float] = {}
        payload = json.loads(archive.read_text(encoding="utf-8"))
        for ev in (payload.get("events") or {}).values():
            h, a = abbr(ev.get("home_team")), abbr(ev.get("away_team"))
            if not h or not a:
                continue
            for bk in (ev.get("bookmakers") or []):
                for mkt in (bk.get("markets") or []):
                    if mkt.get("key") != "spreads":
                        continue
                    for oc in (mkt.get("outcomes") or []):
                        if abbr(oc.get("name")) == h and oc.get("point") is not None:
                            out.setdefault((h, a), float(oc["point"]))
        return out
    return _load_daily_snapshot_spreads()


def _load_daily_snapshot_spreads() -> dict:
    """(home,away) -> home spread, from the LAST daily snapshot that carries it.

    Files are daily, so the last one before kickoff is the closing line. Taking
    the last file that mentions a matchup is the closest available proxy.
    """
    out: dict[tuple[str, str], float] = {}
    for path in sorted(glob.glob(str(NFL / "real_betting_lines_*.json"))):
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception:
            continue
        for matchup, data in (payload.get("lines") or {}).items():
            if "@" not in matchup:
                continue
            away_name, home_name = [s.strip() for s in matchup.split("@", 1)]
            h, a = abbr(home_name), abbr(away_name)
            if not h or not a:
                continue
            spread = ((data or {}).get("run_line") or {}).get("home")
            if spread is None:
                continue
            try:
                out[(h, a)] = float(spread)      # later files overwrite earlier
            except (TypeError, ValueError):
                continue
    return out


def load_injuries(season: int) -> dict:
    """(team, week) -> burden measures."""
    burden: dict[tuple[str, int], dict[str, float]] = defaultdict(
        lambda: {"out": 0.0, "qb_out": 0.0, "weighted": 0.0, "skill_out": 0.0})
    path = NFL / "tracking" / "nflverse" / "injuries" / f"injuries_{season}.csv"
    if not path.is_file():
        return burden
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            if (row.get("season_type") or "REG") != "REG":
                continue
            try:
                wk = int(float(row.get("week") or 0))
            except (TypeError, ValueError):
                continue
            team = norm(row.get("team"))
            status = (row.get("report_status") or "").strip().lower()
            pos = (row.get("position") or "").strip().upper()
            b = burden[(team, wk)]
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seasons", default="2022,2023,2024,2025")
    args = ap.parse_args()
    seasons = [int(x) for x in str(args.seasons).split(",") if x.strip()]

    print("=" * 78)
    print("DOES THE NFL MARKET MISPRICE INJURIES?  seasons %s" % ",".join(map(str, seasons)))
    print("=" * 78)

    rows = []
    per_season = {}
    for season in seasons:
        games = load_games(season)
        spreads = load_closing_spreads(season)
        burden = load_injuries(season)
        n0 = len(rows)
        for g in games.values():
            sp = spreads.get((g["home"], g["away"]))
            if sp is None:
                continue
            market_margin = -float(sp)
            hb = burden.get((g["home"], g["week"]), {})
            ab = burden.get((g["away"], g["week"]), {})
            rows.append({
                "season": season,
                "residual": (g["hs"] - g["as"]) - market_margin,
                "out_diff": hb.get("out", 0.0) - ab.get("out", 0.0),
                "qb_out_diff": hb.get("qb_out", 0.0) - ab.get("qb_out", 0.0),
                "weighted_diff": hb.get("weighted", 0.0) - ab.get("weighted", 0.0),
                "skill_out_diff": hb.get("skill_out", 0.0) - ab.get("skill_out", 0.0),
            })
        per_season[season] = len(rows) - n0
        print("  %d: games=%-4d spreads=%-4d injury team-weeks=%-4d -> JOINED %d"
              % (season, len(games), len(spreads), len(burden), per_season[season]))

    print("  " + "-" * 60)
    print("  POOLED JOINED: %d games" % len(rows))
    if len(rows) < 100:
        print("  TOO FEW -- check the per-season join counts above; a zero means")
        print("  that season's odds or injury source did not load.")
        return 1
    for season, n in per_season.items():
        if n == 0:
            print("  !! season %d contributed ZERO games -- its source did not load." % season)

    res = [r["residual"] for r in rows]
    se = statistics.stdev(res) / len(res) ** 0.5
    print("  market residual   mean %+.3f  SD %.2f  (t %+.2f)"
          % (statistics.fmean(res), statistics.pstdev(res), statistics.fmean(res) / se))
    print()
    print("  %-16s %6s %10s %9s %8s  %s" % ("burden measure", "n", "slope", "SE", "t", "verdict"))
    print("  " + "-" * 72)
    hits = []
    for var in ("out_diff", "qb_out_diff", "weighted_diff", "skill_out_diff"):
        x = [r[var] for r in rows]
        if statistics.pstdev(x) == 0:
            print("  %-16s %6d   (no variation)" % (var, len(x)))
            continue
        b, s_, t = ols(res, x)
        sig = abs(t) >= 2.0
        if sig:
            hits.append(var)
        print("  %-16s %6d %10.4f %9.4f %+8.2f  %s"
              % (var, len(x), b, s_, t, "SIGNIFICANT" if sig else "priced (null)"))

    print()
    print("  PER-SEASON, weighted_diff -- replication is what one season cannot show:")
    for season in seasons:
        sub = [r for r in rows if r["season"] == season]
        if len(sub) < 50:
            continue
        b, s_, t = ols([r["residual"] for r in sub], [r["weighted_diff"] for r in sub])
        print("    %d  n=%-4d slope %+7.4f  t %+6.2f" % (season, len(sub), b, t))

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
            print("    |weighted_diff| >= %.0f : %d bets (too few to judge)" % (thr, n))
            continue
        wins = sum(1 for r in sel if (r["residual"] > 0) == (r["weighted_diff"] < 0))
        p_hat = wins / n
        z = 1.96
        d = 1 + z * z / n
        c = (p_hat + z * z / (2 * n)) / d
        m_ = z * ((p_hat * (1 - p_hat) / n + z * z / (4 * n * n)) ** 0.5) / d
        flag = "  <-- clears 52.4%" if (c - m_) > 0.524 else ""
        print("    |weighted_diff| >= %.0f : %4d bets  %5.1f%% ATS  CI [%.1f, %.1f]%s"
              % (thr, n, 100 * p_hat, 100 * (c - m_), 100 * (c + m_), flag))

    print()
    if hits:
        print("  REGRESSION CANDIDATES: %s" % ", ".join(hits))
        print("  Build ONLY if the DIRECT ATS test also clears 52.4%% on its CI lower")
        print("  bound AND the per-season table shows the sign REPLICATING. A single")
        print("  significant pooled slope with a flat ATS record is an extrapolation.")
    else:
        print("  NO MISPRICING DETECTED across %d seasons. The NFL market prices injuries." % len(seasons))
        print("  A better estimator cannot beat a line that already has the information.")
        print("  That kills the injury lever for NFL -- and a fortiori for NCAAF, whose")
        print("  data is worse (no feed at all) and whose market would price what leaks.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
