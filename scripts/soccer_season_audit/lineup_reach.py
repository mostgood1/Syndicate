# -*- coding: utf-8 -*-
"""How often was a soccer match priced from a build that HAD the confirmed starting XI?

Lane `soccer-lineup-reach` (2026-10-09). Read-only. The open item from
`findings_2026-10-08_soccer_last_scorer_lineup.md`: the lineup race helps only if the board's
last pre-kickoff build actually carried the confirmed XI, and that was unmeasurable (the
odds job blanked `SOCCER_CONFIRMED_LINEUPS`, fixed by 93b235a0; past freezes pruned).

TWO SOURCES, both on the fleet's data root:

1. The PRE-KICKOFF FREEZE (`<league>/api/recommendations/recommendations_prekickoff_<date>.<service>.json`):
   one entry per match, the LAST build generated before its kickoff (`build_soccer_artifacts.freeze_prekickoff`).
   Services are merged, keeping each match's latest `frozen_at` before kickoff.
   A side counts as CONFIRMED when NO player sits in the middle band (0.16, 0.75) of
   `expected_minutes_share`. With a confirmed XI, `player_props.build_usage_profiles` writes
   starters max(season, 0.75) and bench 0.15x season, which empties that band. Measured
   2026-10-09 on every freeze on the fleet: all 4 sides frozen <=1 min before kickoff had 0 in
   the band; all 36 sides frozen hours or days out had 3-19. One match (10-07 Chicago v
   Vancouver) shows both states (210 min out: 12 / 10 in the band; 0.1 min out: 0 / 0).
   The count at >=0.75 is NOT the test: deep EPL squads reach 12-16 on season shares alone,
   and confirmed sides showed only 7-10 (`starters_recognised`). That shortfall is starters
   the squad data does not hold or names that do not match, which then get bench minutes.
2. `STEP_MARKER ... SOCCER_CONFIRMED_LINEUPS ... sides_confirmed=X/Y` lines in
   `reports/migration_runs/<date>/odds_refresh_*/odds_refresh.stderr.txt` (when lineups
   first appear, per league-date). Per league-date, not per match.

    python lineup_reach.py --dates 2026-10-09,2026-10-10,2026-10-11,2026-10-12 [--data-root DIR] [--json OUT]
"""
import argparse
import collections
import datetime as dt
import glob
import json
import os
import re

STARTER_SHARE = 0.75
BENCH_CEILING = 0.16  # 0.15 x a full season share, plus rounding
MIN_SIDE_ROWS = 14
BUCKETS = ((0, 60, "<=60 min"), (60, 120, "60-120 min"), (120, 360, "2-6 h"), (360, 10 ** 9, ">6 h"))
_MARKER = re.compile(r"SOCCER_CONFIRMED_LINEUPS league=(?P<league>\S+) date=(?P<date>\S+) "
                     r"sides_confirmed=(?P<c>\d+)/(?P<t>\d+)")


def _ts(value):
    if not value:
        return None
    try:
        t = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def side_confirmed(rows):
    """(confirmed, n_at_starter_share, n_in_middle_band, n_rows) for one side's player props."""
    shares = []
    for r in rows:
        try:
            shares.append(float(r.get("expected_minutes_share")))
        except (TypeError, ValueError):
            continue
    hi = sum(1 for s in shares if s >= STARTER_SHARE)
    mid = sum(1 for s in shares if BENCH_CEILING < s < STARTER_SHARE)
    return (mid == 0 and 1 <= hi <= 11 and len(shares) >= MIN_SIDE_ROWS), hi, mid, len(shares)


def load_freezes(soccer_root, dates):
    """{(league, match_id): entry} keeping the latest pre-kickoff frozen_at across services."""
    best = {}
    for date in dates:
        for path in glob.glob(os.path.join(soccer_root, "*", "api", "recommendations",
                                           f"recommendations_prekickoff_{date}.*.json")):
            league = path.split(os.sep)[-4]
            try:
                body = json.load(open(path, encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for mid, entry in (body.get("matches") or {}).items():
                frozen, kick = _ts(entry.get("frozen_at")), _ts(entry.get("kickoff"))
                if frozen is None or kick is None or frozen >= kick:
                    continue
                key = (league, str(mid))
                if key not in best or frozen > best[key]["_frozen"]:
                    best[key] = dict(entry, _frozen=frozen, _kick=kick, _date=date)
    return best


def classify(freezes, now):
    """One row per match side, final matches only (kickoff in the past)."""
    out = []
    for (league, mid), entry in freezes.items():
        if entry["_kick"] > now:
            continue  # not kicked off yet: its freeze can still change
        # SIDES FROM THE PROPS' OWN `team` FIELD. The frozen `match` record carries no
        # home_team/away_team keys (read 2026-10-09 on the 10-06 MLS freeze), so keying
        # sides off it gave every side 0 rows and a "not confirmed" that measured nothing.
        by_team = collections.defaultdict(list)
        for r in entry.get("player_props") or []:
            by_team[str(r.get("team") or "")].append(r)
        lead = (entry["_kick"] - entry["_frozen"]).total_seconds() / 60.0
        for team, rows in sorted(by_team.items()):
            conf, hi, band, n = side_confirmed(rows)
            out.append({"league": league, "match_id": mid, "date": entry["_date"], "team": team,
                        "lead_minutes": round(lead, 1), "confirmed": conf, "starters_recognised": hi,
                        "middle_band": band, "rows": n})
    return out


def scan_markers(reports_root, dates):
    """{(league, date): [(run_utc, confirmed, total)]} from STEP_MARKER lines."""
    out = collections.defaultdict(list)
    run_dates = sorted({d for d in dates} | {(dt.date.fromisoformat(d) - dt.timedelta(days=1)).isoformat() for d in dates})
    for rd in run_dates:
        for path in glob.glob(os.path.join(reports_root, "migration_runs", rd, "odds_refresh_*", "odds_refresh.stderr.txt")):
            stamp = os.path.basename(os.path.dirname(path))[len("odds_refresh_"):]
            try:
                run = dt.datetime.strptime(stamp, "%Y%m%d_%H%M%S").replace(tzinfo=dt.timezone.utc)
            except ValueError:
                run = None
            try:
                text = open(path, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            for line in text.splitlines():
                if not line.startswith("STEP_MARKER"):
                    continue
                m = _MARKER.search(line)
                if m and m.group("date") in dates:
                    out[(m.group("league"), m.group("date"))].append(
                        (run.isoformat() if run else None, int(m.group("c")), int(m.group("t"))))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dates", required=True, help="comma-separated ISO dates")
    ap.add_argument("--data-root", default=os.environ.get("SYNDICATE_DATA_ROOT") or os.path.expanduser("~/syndicate-prod/data"))
    ap.add_argument("--json")
    args = ap.parse_args()
    dates = [d.strip() for d in args.dates.split(",") if d.strip()]
    now = dt.datetime.now(dt.timezone.utc)

    sides = classify(load_freezes(os.path.join(args.data_root, "soccer_source"), dates), now)
    by_bucket = collections.OrderedDict((label, [0, 0]) for _, _, label in BUCKETS)
    for s in sides:
        for lo, hi, label in BUCKETS:
            if lo <= s["lead_minutes"] < hi:
                by_bucket[label][0] += int(s["confirmed"])
                by_bucket[label][1] += 1
    markers = scan_markers(os.path.join(args.data_root, "reports"), dates)
    first_confirmed = {f"{lg}|{d}": next((r for r, c, _t in sorted(v, key=lambda x: x[0] or "") if c > 0), None)
                       for (lg, d), v in markers.items()}
    positive_controls = [s for s in sides if s["confirmed"]][:3]
    recognised = collections.Counter(s["starters_recognised"] for s in sides if s["confirmed"])
    report = {
        "dates": dates, "now": now.isoformat(), "final_match_sides": len(sides),
        "matches": len({(s["league"], s["match_id"]) for s in sides}),
        "confirmed_sides": sum(1 for s in sides if s["confirmed"]),
        "confirmed_by_lead_bucket": {k: {"confirmed": v[0], "sides": v[1]} for k, v in by_bucket.items()},
        "marker_league_dates": len(markers),
        "marker_first_confirmed_run": first_confirmed,
        "positive_controls": positive_controls,
        "confirmed_sides_by_starters_recognised_of_11": dict(sorted(recognised.items())),
    }
    print(json.dumps(report, indent=1))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"report": report, "sides": sides}, fh, indent=1)


if __name__ == "__main__":
    main()
