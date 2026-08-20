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


def load_games() -> dict:
    """One row per 2025 game from the pbp mirror: teams, week, final score."""
    out: dict[str, dict] = {}
    path = NFL / "tracking" / "nflverse" / "pbp" / "pbp_2025.csv"
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


def load_closing_spreads() -> dict:
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


def load_injuries() -> dict:
    """(team, week) -> burden measures."""
    burden: dict[tuple[str, int], dict[str, float]] = defaultdict(
        lambda: {"out": 0.0, "qb_out": 0.0, "weighted": 0.0, "skill_out": 0.0})
    path = NFL / "tracking" / "nflverse" / "injuries" / "injuries_2025.csv"
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
    ap.parse_args()

    games = load_games()
    spreads = load_closing_spreads()
    burden = load_injuries()

    print("=" * 78)
    print("DOES THE NFL MARKET MISPRICE INJURIES?  (2025 regular season)")
    print("=" * 78)
    print(f"  games (pbp)        {len(games)}")
    print(f"  matchups w/ spread {len(spreads)}")
    print(f"  team-weeks w/ inj  {len(burden)}")

    rows = []
    for g in games.values():
        sp = spreads.get((g["home"], g["away"]))
        if sp is None:
            continue
        market_margin = -float(sp)
        residual = (g["hs"] - g["as"]) - market_margin
        hb = burden.get((g["home"], g["week"]), {})
        ab = burden.get((g["away"], g["week"]), {})
        rows.append({
            "residual": residual,
            "out_diff": hb.get("out", 0.0) - ab.get("out", 0.0),
            "qb_out_diff": hb.get("qb_out", 0.0) - ab.get("qb_out", 0.0),
            "weighted_diff": hb.get("weighted", 0.0) - ab.get("weighted", 0.0),
            "skill_out_diff": hb.get("skill_out", 0.0) - ab.get("skill_out", 0.0),
        })

    print(f"  JOINED             {len(rows)}")
    if len(rows) < 50:
        print("\n  TOO FEW JOINED -- check the team-name mapping before concluding.")
        return 1

    res = [r["residual"] for r in rows]
    mean, sd = statistics.fmean(res), statistics.pstdev(res)
    se = statistics.stdev(res) / len(res) ** 0.5
    print(f"  market residual    mean {mean:+.3f}  SD {sd:.2f}  (t {mean/se:+.2f})")
    print()
    print("  %-16s %6s %10s %9s %8s  %s" % ("burden measure", "n", "slope", "SE", "t", "verdict"))
    print("  " + "-" * 72)
    hits = []
    for var in ("out_diff", "qb_out_diff", "weighted_diff", "skill_out_diff"):
        x = [r[var] for r in rows]
        if statistics.pstdev(x) == 0:
            print("  %-16s %6d   (no variation)" % (var, len(x)))
            continue
        b, s, t = ols(res, x)
        sig = abs(t) >= 2.0
        if sig:
            hits.append(var)
        print("  %-16s %6d %10.4f %9.4f %+8.2f  %s"
              % (var, len(x), b, s, t, "SIGNIFICANT" if sig else "priced (null)"))

    print()
    print("  POSITIVE CONTROL: injury burden must actually VARY, or a null is vacuous.")
    for var in ("out_diff", "weighted_diff"):
        x = [r[var] for r in rows]
        print("    %-16s range %+.1f..%+.1f  SD %.2f" % (var, min(x), max(x), statistics.pstdev(x)))
    print()
    # THE DIRECT ATS TEST, always printed alongside the regression.
    #
    # A regression slope implies an edge; it does not demonstrate one, and the
    # two can disagree. Measured 2026-08-20: weighted_diff read t=-1.81 with the
    # intuitive sign, implying ~1.34 points and ~53.5% ATS -- while the direct
    # test at a bettable threshold came back at EXACTLY 50.0% on 118 bets. The
    # implication was an artefact of extrapolating a non-significant slope.
    # LIFT_CONDITION requires the ATS number, so it is not optional here.
    print()
    print("  DIRECT ATS TEST -- bet the LESS injured side (what you would actually do):")
    for thr in (1.0, 2.0, 4.0):
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
        print("    |weighted_diff| >= %.0f : %3d bets  %5.1f%% ATS  CI [%.1f, %.1f]%s"
              % (thr, n, 100 * p_hat, 100 * (c - m_), 100 * (c + m_), flag))

    print()
    if hits:
        print("  REGRESSION CANDIDATES: %s" % ", ".join(hits))
        print("  Build an estimator ONLY if the DIRECT ATS test above also clears")
        print("  52.4%% on its CI lower bound. A significant slope with a flat ATS")
        print("  record is not an edge -- it is an extrapolation.")
    else:
        print("  NO MISPRICING DETECTED. The NFL market prices injuries.")
        print("  A better estimator cannot beat a line that already has the information.")
        print("  That kills the injury lever for NFL -- and a fortiori for NCAAF, whose")
        print("  data is worse and whose market would price whatever leaks out.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
