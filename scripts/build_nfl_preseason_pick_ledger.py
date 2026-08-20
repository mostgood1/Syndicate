"""Grade the NFL PRESEASON model against the closing line.

The NFL preseason board serves picks from a model measured live at
**4.3x under-dispersed** (margin SD 0.97 against a market 4.21). Dispersion is a
PROXY though, and this session already has a scar from trusting one: a 5.8-sigma
proxy result for NCAAF returning production failed completely against realised
margins. So this grades against OUTCOMES.

    projections  smartsim2_preseason_projections_<season>_wk*.csv
                 rating_source `nflverse_pbp_epa_PRIOR_SEASON_shrunk`, so
                 LEAK-FREE BY CONSTRUCTION -- better than NCAAF's starting
                 point, which needed a --ratings-season override to get a
                 clean arm.
    market       historical_odds/closing_lines_preseason_<season>.json
                 96 games over 2023-24, up to 14 books, captured per kickoff
                 window with post-kickoff snapshots rejected.
    outcome      schedule_preseason_<season>.csv (home_score/away_score)

THE JOIN IS THE RISK, not the arithmetic. Projections and schedule share
`game_id` exactly. OddsAPI uses full names ("Houston Texans") while both local
sources use abbreviations ("HOU"), so a bare string match yields ZERO rows and
looks exactly like "no data" -- the team-name/id trap already recorded in
`ncaaf_data_pipeline.md`. All 32 NFL nicknames are unique, so the mapping keys
on the nickname and every unmatched team is REPORTED rather than dropped
silently.

n IS SMALL -- 96 games against NCAAF's 2,233. A null here is INCONCLUSIVE, not
exoneration, and the output says so rather than printing "not significant" as
though it settled something.
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from syndicate.features.football.pick_ledger import (  # noqa: E402
    PickLedgerRow,
    coverage,
    evaluate,
    ledger_path,
    load_ledger,
    upsert,
)

NFL = REPO / "data" / "nfl_source"

#: nickname -> abbreviation. Every NFL nickname is unique, which is what makes
#: this safe; city prefixes are not (two New York teams, two Los Angeles).
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
#: Abbreviations the local sources spell differently across seasons.
ABBR_ALIAS = {"LAR": "LA", "WSH": "WAS", "JAC": "JAX", "OAK": "LV", "SD": "LAC", "STL": "LA"}


def abbr(name: str) -> str | None:
    """Full team name -> abbreviation. None (never a guess) when unmatched."""
    nick = str(name or "").strip().lower().split()
    return NICK_TO_ABBR.get(nick[-1]) if nick else None


def norm_abbr(a: str) -> str:
    a = str(a or "").strip().upper()
    return ABBR_ALIAS.get(a, a)


def load_projections(season: int) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for path in sorted(NFL.glob(f"smartsim2_preseason_projections_{season}_wk*.csv")):
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                gid = str(row.get("game_id") or "").strip()
                if gid:
                    out[gid] = row
    return out


def load_schedule(season: int) -> dict[tuple[str, str], dict]:
    out: dict[tuple[str, str], dict] = {}
    path = NFL / f"schedule_preseason_{season}.csv"
    if not path.is_file():
        return out
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            key = (norm_abbr(row.get("home_team")), norm_abbr(row.get("away_team")))
            out[key] = row
    return out


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def build(season: int) -> tuple[list[PickLedgerRow], dict]:
    odds_path = NFL / "historical_odds" / f"closing_lines_preseason_{season}.json"
    if not odds_path.is_file():
        return [], {"error": f"missing {odds_path.name}"}
    payload = json.loads(odds_path.read_text(encoding="utf-8"))
    events = payload.get("events") or {}
    projections = load_projections(season)
    schedule = load_schedule(season)

    rows: list[PickLedgerRow] = []
    diag = {"events": len(events), "unmatched_team": 0, "no_schedule": 0,
            "no_projection": 0, "no_result": 0, "joined": 0}
    unmatched: set[str] = set()

    for ev in events.values():
        h, a = abbr(ev.get("home_team")), abbr(ev.get("away_team"))
        if not h or not a:
            diag["unmatched_team"] += 1
            for nm in (ev.get("home_team"), ev.get("away_team")):
                if not abbr(nm):
                    unmatched.add(str(nm))
            continue
        sched = schedule.get((h, a))
        if sched is None:
            diag["no_schedule"] += 1
            continue
        gid = str(sched.get("game_id") or "").strip()
        proj = projections.get(gid)
        if proj is None:
            diag["no_projection"] += 1
        hs, as_ = _f(sched.get("home_score")), _f(sched.get("away_score"))
        if hs is None or as_ is None:
            diag["no_result"] += 1
        diag["joined"] += 1

        for bk in (ev.get("bookmakers") or []):
            spread = total = hml = aml = None
            for mkt in (bk.get("markets") or []):
                k = mkt.get("key")
                for oc in (mkt.get("outcomes") or []):
                    nm = abbr(oc.get("name"))
                    if k == "spreads" and nm == h:
                        spread = _f(oc.get("point"))
                    elif k == "totals" and str(oc.get("name","")).lower() == "over":
                        total = _f(oc.get("point"))
                    elif k == "h2h":
                        if nm == h: hml = _f(oc.get("price"))
                        elif nm == a: aml = _f(oc.get("price"))
            rows.append(PickLedgerRow(
                sport="nfl", season=season,
                week=int(_f(sched.get("week")) or 0),
                game_id=gid, home_team=h, away_team=a,
                start_date=str(sched.get("gameday") or ""),
                provider=str(bk.get("key") or ""),
                spread_close=spread, total_close=total,
                home_moneyline=hml, away_moneyline=aml,
                model_margin=_f((proj or {}).get("margin_mean")),
                model_total=_f((proj or {}).get("total_mean")),
                model_home_win_prob=_f((proj or {}).get("home_win_rate")),
                model_margin_stdev=_f((proj or {}).get("margin_stdev")),
                rating_source=str((proj or {}).get("rating_source") or ""),
                model_generated_at=str((proj or {}).get("generated_at") or ""),
                home_score=hs, away_score=as_,
                realised_margin=(hs - as_) if hs is not None and as_ is not None else None,
                realised_total=(hs + as_) if hs is not None and as_ is not None else None,
                captured_at=str(payload.get("season") or season),
            ))
    diag["unmatched_names"] = sorted(unmatched)
    return rows, diag


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seasons", default="2023,2024")
    ap.add_argument("--root", default=None)
    args = ap.parse_args()

    all_rows: list[PickLedgerRow] = []
    for season in [int(s) for s in args.seasons.split(",") if s.strip()]:
        rows, diag = build(season)
        print(f"\n[{season}] events={diag.get('events')} joined={diag.get('joined')} "
              f"unmatched_team={diag.get('unmatched_team')} no_schedule={diag.get('no_schedule')} "
              f"no_projection={diag.get('no_projection')} no_result={diag.get('no_result')}")
        if diag.get("unmatched_names"):
            print("  UNMATCHED NAMES (fix the map, do not ignore):", diag["unmatched_names"])
        if not rows:
            continue
        counts = upsert("nfl", season, rows, root=args.root)
        print(f"  ledger {ledger_path('nfl', season, root=args.root)}")
        print(f"  added {counts['added']} updated {counts['updated']} total {counts['total']}")
        all_rows += load_ledger("nfl", season, root=args.root)

    if not all_rows:
        print("\nNO ROWS -- nothing to grade.")
        return 1

    print("\n" + "=" * 74)
    print("NFL PRESEASON -- MODEL vs CLOSING LINE (pooled)")
    print("=" * 74)
    cov = coverage(all_rows)
    for k in ("rows", "games", "with_model", "with_spread_close", "with_result", "gradable_vs_close"):
        print(f"  {k:22s} {cov.get(k)}")
    print(f"  providers              {len(cov.get('providers') or [])}")
    print(f"  graded_leak_status     {cov.get('graded_leak_status')}")

    ev = evaluate(all_rows)
    warn = ev.get("leak_warning")
    if warn:
        print("\n  !! " + warn["message"])
    r = ev["vs_close"]
    print()
    if r.get("verdict") == "INSUFFICIENT":
        print(f"  n={r['n']} -- INSUFFICIENT")
        return 0
    print(f"  n={r['n']}  model MAE {r['model_mae']:.3f}  market MAE {r['market_mae']:.3f}")
    print(f"  paired dMAE {r['delta_mae']:+.3f}  SE {r['se']:.3f}  t {r['t']:+.2f}  -> {r['verdict']}")
    games = cov.get("games") or 0
    print()
    print(f"  READ WITH CARE: {games} distinct games (NCAAF's verdict rested on 2,233 rows).")
    print("  Rows are per-BOOK and not independent -- the same game repeats across")
    print("  books, so the SE above is OPTIMISTIC and the true n is the game count.")
    print("  A null here is INCONCLUSIVE, not exoneration.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
