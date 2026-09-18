# -*- coding: utf-8 -*-
"""H24 (`#665`), forward: does scaling the model's goal means by a trailing-year xG environment improve O/U 2.5?

Lane `soccer-h24-grader`. The rules are the registration, not this file:
  `.syndicate/log/2026-09-15.md` ~16:30 CT   predictor, arms, falsification rule, data list
  `.syndicate/log/2026-09-16.md` ~20:50 CT   amendment: the qualifying artifact is the pre-kickoff freeze
  `.syndicate/log/2026-09-17.md` ~20:10 CT   the unstated details fixed before any computation, and the
                                             FotMob base-season gap this grader's pull step fills

    factor_L(d) = clamp(xg_env_L(d) / xg_base_L, 0.85, 1.20), or 1.0 when [d - 365, d) holds < 60 matches
      xg_env_L(d)  mean per-match TOTAL FotMob shot xG over L's matches in [d - 365 days, d)
      xg_base_L    the same over L's two seasons before 2026-27 (Europe 2024-25 + 2025-26; MLS 2024 + 2025)

    P0  independent Poisson(home_mean, away_mean) from the frozen entry -> over 2.5 = 1 - P(T <= 2)
    XE  the same with both means x factor_L(d)

    H24 MET only if BOTH: pooled over-2.5 log loss XE < P0, AND |mean(actual - XE total)| < |mean(actual - P0 total)|.
    Graded at >= 150 matches, or on 2026-10-15 (CT) with whatever n exists. Before either: WATCHING.

The population is the pregame forward grader's own (`forward_grade.py`): freeze entries merged across services by
latest `frozen_at` before the ESPN kickoff, so this grade and H27/W1r/W2/W3 read identical matches.

    py -3 scripts/soccer_season_audit/h24_forward_grade.py pull  --cache <forward-grade cache> --h24-cache <dir> --env-root <checkout>
    py -3 scripts/soccer_season_audit/h24_forward_grade.py grade --cache <forward-grade cache> --h24-cache <dir>
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import io
import json
import math
import subprocess
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHECKOUT = HERE.parents[1]
for p in (str(HERE), str(CHECKOUT)):
    if p not in sys.path:
        sys.path.insert(0, p)

FACTOR_LO, FACTOR_HI = 0.85, 1.20
MIN_WINDOW_MATCHES = 60
WINDOW_DAYS = 365
GRADE_MATCHES = 150
GRADE_DATE = dt.date(2026, 10, 15)
GRADE_FROM = dt.datetime(2026, 9, 16, tzinfo=dt.timezone.utc)
BASE_EUROPE = (dt.date(2024, 7, 1), dt.date(2026, 6, 30))
BASE_MLS = (dt.date(2024, 1, 1), dt.date(2025, 12, 31))
EPS = 1e-9

# football-data.co.uk 2026-27 season files; MLS's "new leagues" file carries 1X2 only, so no O/U 2.5 close there.
FD_CODES = {"epl": "E0", "championship": "E1", "la_liga": "SP1", "bundesliga": "D1", "serie_a": "I1",
            "ligue_1": "F1", "eredivisie": "N1", "primeira_liga": "P1", "belgian_pro_league": "B1"}
FD_SEASON = "2627"


# ---------------------------------------------------------------------------- predictor (pure)

def base_range(league: str) -> tuple[dt.date, dt.date]:
    return BASE_MLS if league == "mls" else BASE_EUROPE


def fotmob_totals(payload: dict) -> dict[str, list[tuple[dt.date, float]]]:
    """league -> [(match date, total shot xG)], one entry per FotMob match id."""
    seen: set[str] = set()
    out: dict[str, list[tuple[dt.date, float]]] = collections.defaultdict(list)
    for m in payload.get("matches") or []:
        mid = str(m.get("match_id"))
        if mid in seen or not m.get("shots"):
            continue
        seen.add(mid)
        try:
            day = dt.date.fromisoformat(str(m.get("date"))[:10])
        except ValueError:
            continue
        out[str(m.get("league"))].append((day, sum(float(s.get("xg") or 0.0) for s in m["shots"])))
    return dict(out)


def xg_base(rows: list[tuple[dt.date, float]], league: str) -> tuple[float | None, int]:
    lo, hi = base_range(league)
    vals = [x for d, x in rows if lo <= d <= hi]
    return (sum(vals) / len(vals), len(vals)) if vals else (None, 0)


def factor(rows: list[tuple[dt.date, float]], base: float, match_day: dt.date) -> tuple[float, int, bool]:
    """(factor, matches in the window, thin) -- thin means the registered < 60 rule set it to 1.0."""
    start = match_day - dt.timedelta(days=WINDOW_DAYS)
    window = [x for d, x in rows if start <= d < match_day]
    if len(window) < MIN_WINDOW_MATCHES:
        return 1.0, len(window), True
    env = sum(window) / len(window)
    return min(FACTOR_HI, max(FACTOR_LO, env / base)), len(window), False


def over25(lam: float) -> float:
    """P(T >= 3) for T ~ Poisson(lam): the sum of two independent Poissons is Poisson with the summed mean."""
    return 1.0 - math.exp(-lam) * (1.0 + lam + lam * lam / 2.0)


def log_loss(p: float, y: float) -> float:
    p = min(max(p, EPS), 1.0 - EPS)
    return -(y * math.log(p) + (1.0 - y) * math.log(1.0 - p))


def verdict(n: int, ll_p0: float, ll_xe: float, bias_p0: float, bias_xe: float, today: dt.date) -> str:
    if n < GRADE_MATCHES and today < GRADE_DATE:
        return "WATCHING"
    if n == 0:
        return "NO MATCHES"
    return "MET" if (ll_xe < ll_p0 and abs(bias_xe) < abs(bias_p0)) else "FALSIFIED"


# ---------------------------------------------------------------------------- closing O/U 2.5 (reported only)

def load_closing(fd_dir: Path) -> dict[str, list[dict]]:
    """league -> [{date, home, away, fair_over}] from the football-data closing averages."""
    from common import devig  # noqa: E402
    out: dict[str, list[dict]] = collections.defaultdict(list)
    for league, code in FD_CODES.items():
        path = Path(fd_dir) / f"{code}.csv"
        if not path.exists():
            continue
        text = path.read_bytes().decode("latin-1").lstrip("﻿").lstrip("ï»¿")
        for r in csv.DictReader(io.StringIO(text)):
            try:
                day = dt.datetime.strptime(str(r.get("Date") or "").strip(), "%d/%m/%Y").date()
                over, under = float(r["AvgC>2.5"]), float(r["AvgC<2.5"])
            except (KeyError, TypeError, ValueError):
                continue
            out[league].append({"date": day, "home": r.get("HomeTeam"), "away": r.get("AwayTeam"),
                                "fair_over": devig([over, under])[0]})
    return dict(out)


def closing_for(closing: dict, league: str, home: str, away: str, day: dt.date) -> float | None:
    from common import find_fixture  # noqa: E402
    cands = [(r["home"], r["away"], r) for r in closing.get(league, []) if abs((r["date"] - day).days) <= 1]
    hit = find_fixture(home, away, cands) if cands else None
    return hit["fair_over"] if hit else None


# ---------------------------------------------------------------------------- grade

def grade(cache: Path, h24_cache: Path, today: dt.date | None = None) -> dict:
    import forward_grade as fg  # noqa: E402 -- the same population the pregame grades read

    today = today or fg.today_ct()
    outcomes = {}
    for path in Path(cache, "espn").glob("*.json"):
        lg, _, mid = path.stem.partition("__")
        try:
            outcomes[(lg, mid)] = fg.outcome_from_summary(json.loads(path.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            continue
    files = fg.load_freeze_files(Path(cache) / "freeze")
    merged = fg.merge_frozen(files, {k: v["kickoff"] for k, v in outcomes.items() if v.get("kickoff")})
    recs = fg.recs_from_merged(merged, Path(h24_cache) / "_recs")

    fotmob_path = Path(h24_cache) / "fotmob_all.json"
    totals = fotmob_totals(json.loads(fotmob_path.read_text(encoding="utf-8"))) if fotmob_path.exists() else {}
    bases = {lg: xg_base(rows, lg) for lg, rows in totals.items()}
    closing = load_closing(Path(h24_cache) / "fd")

    funnel = collections.Counter()
    rows = []
    for (lg, mid), rec in recs.items():
        funnel["frozen_merged"] += 1
        o = outcomes.get((lg, mid)) or {}
        ko = o.get("kickoff")
        if ko is None or ko < GRADE_FROM:
            continue
        funnel["kickoff_in_window"] += 1
        home, away = (o.get("teams") or {}).get("home") or {}, (o.get("teams") or {}).get("away") or {}
        if not o.get("completed") or home.get("score") is None or away.get("score") is None:
            continue
        funnel["finished"] += 1
        if rec.get("home_mean") is None or rec.get("away_mean") is None:
            funnel["no_frozen_means"] += 1
            continue
        base, n_base = bases.get(lg, (None, 0))
        if base is None:
            funnel["no_fotmob_base"] += 1
            continue
        funnel["covered"] += 1
        f, n_window, thin = factor(totals.get(lg, []), base, ko.date())
        lam0 = float(rec["home_mean"]) + float(rec["away_mean"])
        actual = float(home["score"]) + float(away["score"])
        y = 1.0 if actual >= 3 else 0.0
        p0, pxe = over25(lam0), over25(lam0 * f)
        close = closing_for(closing, lg, rec.get("home"), rec.get("away"), ko.date())
        rows.append({"lg": lg, "mid": mid, "factor": f, "thin": thin, "n_window": n_window, "actual": actual, "y": y,
                     "lam_p0": lam0, "lam_xe": lam0 * f, "p_p0": p0, "p_xe": pxe,
                     "p_published": rec.get("p_over25"), "p_close": close})

    def pooled(rs):
        if not rs:
            return {"n": 0}
        return {"n": len(rs),
                "ll_p0": sum(log_loss(r["p_p0"], r["y"]) for r in rs) / len(rs),
                "ll_xe": sum(log_loss(r["p_xe"], r["y"]) for r in rs) / len(rs),
                "bias_p0": sum(r["actual"] - r["lam_p0"] for r in rs) / len(rs),
                "bias_xe": sum(r["actual"] - r["lam_xe"] for r in rs) / len(rs)}

    total = pooled(rows)
    per_league = {lg: pooled([r for r in rows if r["lg"] == lg]) for lg in sorted({r["lg"] for r in rows})}
    for lg, v in per_league.items():
        priced = [r for r in rows if r["lg"] == lg and r["p_close"] is not None]
        v["closing_n"] = len(priced)
        if priced:
            v["brier_gap_xe_vs_close"] = sum((r["p_xe"] - r["y"]) ** 2 - (r["p_close"] - r["y"]) ** 2 for r in priced) / len(priced)
    sign = sum(1 for v in per_league.values() if v["n"] and v["ll_xe"] < v["ll_p0"])
    published = [r for r in rows if r["p_published"] is not None]
    report = {
        "today": today.isoformat(),
        "funnel": dict(funnel),
        "coverage": {
            "freeze_entries": sum(len(f["matches"]) for f in files),
            "espn_outcomes": len(outcomes),
            "fotmob": {lg: {"matches": len(rs), "base_matches": bases[lg][1],
                            "first": min(d for d, _ in rs).isoformat(), "last": max(d for d, _ in rs).isoformat()}
                       for lg, rs in sorted(totals.items())},
            "closing_rows": {lg: len(v) for lg, v in sorted(closing.items())},
            "intersection_graded": len(rows),
        },
        "pooled": total,
        "per_league": per_league,
        "sign_test": {"leagues_xe_better": sign, "leagues": len(per_league)},
        "factor_one_by_thin_window": sum(1 for r in rows if r["thin"]),
        "published_over25_ll": (sum(log_loss(float(r["p_published"]), r["y"]) for r in published) / len(published)) if published else None,
    }
    report["verdict"] = verdict(total.get("n", 0), total.get("ll_p0", float("nan")), total.get("ll_xe", float("nan")),
                                total.get("bias_p0", float("nan")), total.get("bias_xe", float("nan")), today)
    return report


# ---------------------------------------------------------------------------- pull (network)

def pull(cache: Path, h24_cache: Path, env_root: Path | None) -> dict:
    """Freeze + ESPN via the pregame grader's own pull; football-data closes; a resumable FotMob walk to yesterday."""
    import forward_grade as fg  # noqa: E402
    tally: dict = {"forward_grade_pull": fg.pull(Path(cache), with_book_quotes=False, env_root=env_root)}
    fd_dir = Path(h24_cache) / "fd"
    fd_dir.mkdir(parents=True, exist_ok=True)
    for league, code in FD_CODES.items():
        url = f"https://www.football-data.co.uk/mmz4281/{FD_SEASON}/{code}.csv"
        try:
            with urllib.request.urlopen(url, timeout=60) as handle:
                (fd_dir / f"{code}.csv").write_bytes(handle.read())
            tally[f"fd_{league}"] = "ok"
        except Exception as exc:  # noqa: BLE001 -- the close is reported only; a miss is counted, not fatal
            tally[f"fd_{league}"] = type(exc).__name__
    yesterday = (dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=1)).isoformat()
    walk = subprocess.run([sys.executable, str(CHECKOUT / "scripts" / "soccer_fotmob_harvest_2y.py"),
                           "--start", "2024-02-01", "--end", yesterday,
                           "--out", str(Path(h24_cache) / "fotmob_all.json"), "--workers", "6"],
                          cwd=str(CHECKOUT), capture_output=True, text=True, timeout=6 * 3600)
    tally["fotmob_walk_exit"] = walk.returncode
    tally["fotmob_walk_tail"] = (walk.stdout or walk.stderr).strip().splitlines()[-3:]
    return tally


def print_report(r: dict) -> None:
    print(f"H24 {r['today']}: funnel {r['funnel']}")
    cov = r["coverage"]
    print(f"  coverage: freeze entries {cov['freeze_entries']}, ESPN outcomes {cov['espn_outcomes']}, graded (intersection) {cov['intersection_graded']}")
    for lg, v in cov["fotmob"].items():
        print(f"    fotmob {lg:20s} {v['matches']:5d} matches {v['first']}..{v['last']}  base {v['base_matches']}")
    print(f"    closing O/U 2.5 rows: {cov['closing_rows']}")
    p = r["pooled"]
    if p.get("n"):
        print(f"  pooled n {p['n']}: log loss P0 {p['ll_p0']:.4f} vs XE {p['ll_xe']:.4f} | bias P0 {p['bias_p0']:+.3f} vs XE {p['bias_xe']:+.3f}"
              f" | published {r['published_over25_ll'] if r['published_over25_ll'] is None else round(r['published_over25_ll'], 4)}")
    for lg, v in r["per_league"].items():
        gap = v.get("brier_gap_xe_vs_close")
        print(f"    {lg:20s} n {v['n']:3d}  LL P0 {v['ll_p0']:.4f} XE {v['ll_xe']:.4f}  bias P0 {v['bias_p0']:+.2f} XE {v['bias_xe']:+.2f}"
              f"  close n {v['closing_n']}{'' if gap is None else f'  XE-close Brier {gap:+.4f}'}")
    print(f"  sign test: XE better in {r['sign_test']['leagues_xe_better']} of {r['sign_test']['leagues']} leagues; factor = 1.0 by the thin-window rule: {r['factor_one_by_thin_window']}")
    print("H24:", r["verdict"])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("pull", "grade"):
        p = sub.add_parser(name)
        p.add_argument("--cache", required=True, help="the pregame forward grader's cache (freeze + ESPN)")
        p.add_argument("--h24-cache", required=True, help="FotMob harvest, football-data closes, working files")
        if name == "pull":
            p.add_argument("--env-root", default=None, help="checkout holding the gitignored .env")
        else:
            p.add_argument("--today", help="YYYY-MM-DD (CT); default today")
    args = ap.parse_args(argv)
    if args.cmd == "pull":
        print(json.dumps(pull(Path(args.cache), Path(args.h24_cache), Path(args.env_root) if args.env_root else None), indent=1, default=str))
        return 0
    report = grade(Path(args.cache), Path(args.h24_cache), dt.date.fromisoformat(args.today) if args.today else None)
    Path(args.h24_cache).mkdir(parents=True, exist_ok=True)
    Path(args.h24_cache, "h24_forward_grade.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    print_report(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
