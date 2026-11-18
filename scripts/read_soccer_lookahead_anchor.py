"""READ-ONLY P1-P5 reading for lane soccer-pregame-odds-lane (fix 640c6d4fd, fleet ff 2026-11-18 17:58:30Z).

Run on the fleet (Git Bash):  MSYS_NO_PATHCONV=1 wsl -- nice -n 19 python3 <path to this file under /mnt/c/...> [--until ISO_UTC] [--out PATH]
Reads ~/syndicate-prod/data/reports/migration_runs/*/odds_refresh_*/ and ~/syndicate-prod/logs/refresh-worker.log*.
Writes nothing to the fleet. Prints a report; with --out, also writes the full result as JSON to PATH.
Findings: .syndicate/findings_2026-11-18_soccer_pregame_odds_lane.md (todo #840).

Pre-registered (lane block, commit af0d41f05, 2026-11-18 10:16:54 AM CST):
  P1 every refresh-worker look-ahead run after the ff carries --horizon-days 0 --date <run date> on every soccer
     _artifacts/_picks step; weekly units (live phase, pinned --date) unchanged.
  P2 per run: soccer artifact seconds <= 16 x fixtures(run date, from its markers) + 30 for launches 00:00-07:59 CST,
     <= 2.5x that bound in daytime.
  P3 first 48 h of look-ahead runs: run hold p50 <= 600 s and 0 runs > 1,800 s.
  P4 weekly autorun SOCCER_UNIT_LAUNCHED last_success_age_s p90 <= 18,900 s.
  P5 look-ahead soccer artifact hours <= 1.0 per CST day.
  FALSIFIED IF P1 fails, or P3/P5 miss by > 25%, or P4 shows a loss.
"""
import json, os, re, sys
from datetime import datetime, timezone, timedelta

FF = datetime(2026, 11, 18, 17, 58, 30, tzinfo=timezone.utc)
UNTIL = FF + timedelta(hours=48)
if "--until" in sys.argv:
    UNTIL = datetime.fromisoformat(sys.argv[sys.argv.index("--until") + 1].replace("Z", "+00:00"))
CST = timedelta(hours=-6)
ROOT = os.path.expanduser("~/syndicate-prod/data/reports/migration_runs")
LOGS = os.path.expanduser("~/syndicate-prod/logs")


def ts(v):
    v = str(v or "")
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        d = datetime.fromisoformat(v)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def q(vals, p):
    v = sorted(vals)
    return v[min(len(v) - 1, int(round(p * (len(v) - 1))))] if v else None


lookahead, weekly_units, other_soccer = [], [], []
for day in sorted(os.listdir(ROOT)):
    if day < "2026-11-18":
        continue
    dp = os.path.join(ROOT, day)
    for run in sorted(os.listdir(dp)):
        if not run.startswith("odds_refresh_"):
            continue
        rp = os.path.join(dp, run)
        try:
            st = json.load(open(os.path.join(rp, "refresh_job_status.json")))
            gate = json.load(open(os.path.join(rp, "refresh_and_gate_run.json")))
        except Exception:
            continue
        started = ts(st.get("startedAt"))
        if not started or started < FF or started > UNTIL:
            continue
        if "soccer" not in str(gate.get("oddsSports") or ""):
            continue
        m = re.search(r"refresh_status_latest__(.+)\.json", str(st.get("latestPath") or ""))
        lane = m.group(1) if m else "?"
        try:
            d = json.load(open(os.path.join(rp, "odds_refresh.json")))
        except Exception:
            continue  # still running or unreadable: not counted
        summ = d.get("result") if "result" in d else d
        run_date = str(gate.get("date") or summ.get("date") or "")
        cst_day = (started + CST).date().isoformat()
        hold = None
        a, b = ts(d.get("finishedAt") or summ.get("finished_at")), ts(d.get("startedAt") or summ.get("started_at"))
        if a and b:
            hold = (a - b).total_seconds()
        art_s, matches_on_date, scopes, p1_ok = 0.0, 0, [], True
        for sr in summ.get("results") or []:
            if not isinstance(sr, dict) or sr.get("sport") != "soccer":
                continue
            for s in sr.get("refresh_steps") or []:
                if not isinstance(s, dict):
                    continue
                name = str(s.get("name") or "")
                cmd = list(s.get("command") or [])
                if name.endswith(("_artifacts", "_picks")):
                    scope = cmd[cmd.index("--league") + 2: cmd.index("--source-root")] if "--league" in cmd and "--source-root" in cmd else []
                    scopes.append(" ".join(scope))
                    anchored = "--horizon-days" in scope and scope[scope.index("--horizon-days") + 1] == "0" and "--date" in scope and scope[scope.index("--date") + 1] == run_date
                    single_date_fallback = scope == ["--date", run_date]
                    if not (anchored or single_date_fallback):
                        p1_ok = False
                if name.endswith("_artifacts"):
                    x, y = ts(s.get("started_at")), ts(s.get("finished_at"))
                    art_s += (y - x).total_seconds() if x and y else 0
                    for mk in s.get("stdout_markers") or []:
                        mm = re.search(r"SOCCER_CONFIRMED_LINEUPS league=\S+ date=(\S+) sides_confirmed=\d+/(\d+)", mk)
                        if mm and mm.group(1) == run_date:
                            matches_on_date += int(mm.group(2)) // 2
        row = {"run": run, "lane": lane, "phase": gate.get("oddsPhase"), "date": run_date, "cst_day": cst_day,
               "started": started.isoformat(), "launch_hour_cst": (started + CST).hour, "hold_s": hold,
               "soccer_artifact_s": round(art_s), "matches_on_date": matches_on_date, "p1_ok": p1_ok,
               "scopes": sorted(set(scopes))}
        is_future = run_date > cst_day
        if lane == "refresh-worker" and gate.get("oddsPhase") == "pregame" and is_future:
            bound = 16 * matches_on_date + 30
            row["p2_bound_s"] = bound if row["launch_hour_cst"] < 8 else bound * 2.5
            row["p2_ok"] = art_s <= row["p2_bound_s"]
            lookahead.append(row)
        else:
            other_soccer.append(row)

# P4: weekly autorun unit age at launch, from refresh-worker logs
ages = []
for f in sorted(x for x in os.listdir(LOGS) if x.startswith("refresh-worker.log")):
    with open(os.path.join(LOGS, f), "rb") as fh:
        for raw in fh:
            if b"[refresh_worker] SOCCER_UNIT_LAUNCHED" not in raw[:80]:
                continue
            line = raw.decode("utf-8", "replace")
            t = ts(line[:24])
            if not t or t < FF or t > UNTIL:
                continue
            m = re.search(r"last_success_age_s=(\d+)", line)
            if m and int(m.group(1)) < 10 ** 8:
                ages.append(int(m.group(1)))

holds = [r["hold_s"] for r in lookahead if r["hold_s"] is not None]
art_by_day = {}
for r in lookahead:
    art_by_day[r["cst_day"]] = art_by_day.get(r["cst_day"], 0) + r["soccer_artifact_s"]
full_days = [d for d in sorted(art_by_day) if FF + CST < datetime.fromisoformat(d + "T00:00:00+00:00") and datetime.fromisoformat(d + "T23:59:59+00:00") < UNTIL + CST]
res = {
    "window_utc": [FF.isoformat(), UNTIL.isoformat()],
    "P1": {"lookahead_runs": len(lookahead), "anchored": sum(r["p1_ok"] for r in lookahead),
           "other_soccer_runs": len(other_soccer), "other_scopes_sample": sorted({s for r in other_soccer for s in r["scopes"]})[:8]},
    "P2": {"runs": len(lookahead), "within_bound": sum(1 for r in lookahead if r.get("p2_ok")),
           "misses": [{k: r[k] for k in ("run", "date", "launch_hour_cst", "soccer_artifact_s", "matches_on_date", "p2_bound_s")} for r in lookahead if not r.get("p2_ok")]},
    "P3": {"n": len(holds), "p50": q(holds, .5), "p90": q(holds, .9), "max": max(holds) if holds else None,
           "over_1800": sum(1 for h in holds if h > 1800), "met": bool(holds) and q(holds, .5) <= 600 and not any(h > 1800 for h in holds)},
    "P4": {"n": len(ages), "p50": q(ages, .5), "p90": q(ages, .9), "max": max(ages) if ages else None,
           "met": bool(ages) and q(ages, .9) <= 18900},
    "P5": {"hours_by_cst_day": {d: round(s / 3600, 2) for d, s in sorted(art_by_day.items())}, "full_days": full_days,
           "met": bool(full_days) and all(art_by_day[d] / 3600 <= 1.0 for d in full_days)},
    "saturday_target_runs": [r for r in lookahead if r["date"] == "2026-11-21"],
    "lookahead_runs": lookahead,
}
if "--out" in sys.argv:
    json.dump(res, open(sys.argv[sys.argv.index("--out") + 1], "w"), indent=1, default=str)
print(f"window {FF:%m-%d %H:%MZ} .. {UNTIL:%m-%d %H:%MZ}")
print(f"P1 anchored {res['P1']['anchored']} of {res['P1']['lookahead_runs']} look-ahead runs; other soccer runs {res['P1']['other_soccer_runs']} scopes {res['P1']['other_scopes_sample']}")
print(f"P2 within bound {res['P2']['within_bound']} of {res['P2']['runs']}; misses {res['P2']['misses']}")
print(f"P3 run hold n={res['P3']['n']} p50={res['P3']['p50']} p90={res['P3']['p90']} max={res['P3']['max']} over_1800={res['P3']['over_1800']} met={res['P3']['met']}")
print(f"P4 unit age n={res['P4']['n']} p50={res['P4']['p50']} p90={res['P4']['p90']} max={res['P4']['max']} met={res['P4']['met']}")
print(f"P5 soccer sim-hours by CST day {res['P5']['hours_by_cst_day']} full days {full_days} met={res['P5']['met']}")
for r in res["saturday_target_runs"]:
    print(f"  SAT-TARGET {r['run']} launched {r['launch_hour_cst']}h CST hold {r['hold_s']} soccer_art {r['soccer_artifact_s']} matches {r['matches_on_date']} bound {r['p2_bound_s']}")
