# -*- coding: utf-8 -*-
"""ESPN outcomes for every completed fixture in the production prediction archive.

Keyed by ESPN match id -- the same id space the predictions carry, so the join
is direct. Extracts the final score, team corners/shots/SOT, and per-player
shots/SOT/goals/assists from `rosters[].roster[].stats` (the box score, not the
commentary: commentary shot capture was 0.13 in belgian_pro_league on
2026-08-31). A summary that is not FULL TIME is never used and is re-fetched.
"""
import collections
import datetime as dt
import glob
import io
import json
import os
import sys
import time

S = os.environ.get("SOCCER_AUDIT_CACHE") or os.path.dirname(os.path.abspath(__file__))
PRIMARY = os.environ.get("SYNDICATE_REPO_ROOT") or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PRIMARY)
from syndicate.features.soccer.ingestion.espn_lineups import fetch_match_summary  # noqa: E402

CACHE = os.path.join(os.environ["TEMP"], "espn_shots_cache")
os.makedirs(CACHE, exist_ok=True)
NOW = dt.datetime.now(dt.timezone.utc)


def _num(v):
    try:
        return float(str(v).replace("%", ""))
    except (TypeError, ValueError):
        return None


def _kickoff(value, date):
    try:
        k = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return k if k.tzinfo else k.replace(tzinfo=dt.timezone.utc)
    except (TypeError, ValueError):
        return dt.datetime.fromisoformat(str(date) + "T23:00:00+00:00")


def fixtures():
    out = {}
    for f in sorted(glob.glob(os.path.join(S, "prod", "recs", "*recommendations_*.json"))):
        if os.path.basename(f).startswith("_"):
            continue
        j = json.load(io.open(f, encoding="utf-8"))
        if not isinstance(j, dict):
            continue
        lg = j.get("league")
        for m in j.get("matches") or []:
            mid = str(m.get("match_id") or m.get("event_id") or "")
            if not mid:
                continue
            if _kickoff(m.get("kickoff"), j.get("date")) > NOW - dt.timedelta(hours=3):
                continue
            mu = m.get("matchup") or {}
            out[(lg, mid)] = {"league": lg, "match_id": mid, "date": j.get("date"),
                              "kickoff": m.get("kickoff"), "home": mu.get("home_team"),
                              "away": mu.get("away_team")}
    return out


def extract(s):
    comp = ((s.get("header") or {}).get("competitions") or [{}])[0]
    st = (comp.get("status") or {}).get("type") or {}
    res = {"status": st.get("name"), "completed": bool(st.get("completed")), "teams": {}, "players": []}
    side_by_id = {}
    for c in comp.get("competitors") or []:
        side = c.get("homeAway")
        team = c.get("team") or {}
        side_by_id[str(team.get("id"))] = side
        res["teams"][side] = {"name": team.get("displayName"), "score": _num(c.get("score"))}
    for tm in (s.get("boxscore") or {}).get("teams") or []:
        side = side_by_id.get(str((tm.get("team") or {}).get("id")))
        if side not in res["teams"]:
            continue
        stats = {x.get("name"): x.get("displayValue") for x in tm.get("statistics") or []}
        for k in ("wonCorners", "totalShots", "shotsOnTarget", "possessionPct", "redCards"):
            res["teams"][side][k] = _num(stats.get(k))
    for r in s.get("rosters") or []:
        side = r.get("homeAway")
        for p in r.get("roster") or []:
            st2 = {x.get("name"): x.get("value") for x in p.get("stats") or []}
            sub = p.get("subbedIn")
            if isinstance(sub, dict):
                sub = sub.get("didSub")
            res["players"].append({
                "side": side, "name": (p.get("athlete") or {}).get("displayName"),
                "starter": bool(p.get("starter")), "subbed_in": bool(sub),
                "appearances": _num(st2.get("appearances")), "shots": _num(st2.get("totalShots")),
                "sot": _num(st2.get("shotsOnTarget")), "goals": _num(st2.get("totalGoals")),
                # `#673` H33 scores the assists ladder. Additive: every reader of
                # the fields above is unchanged.
                "assists": _num(st2.get("goalAssists")),
            })
    return res


def main():
    fx = fixtures()
    print(f"completed fixtures in archive: {len(fx)}", flush=True)
    out, tally = {}, collections.Counter()
    for i, ((lg, mid), meta) in enumerate(sorted(fx.items()), 1):
        cf = os.path.join(CACHE, f"{lg}_{mid}.json")
        summary = None
        if os.path.exists(cf):
            try:
                summary = json.load(io.open(cf, encoding="utf-8"))
                if not extract(summary)["completed"]:
                    summary = None
            except Exception:
                summary = None
        if summary is None:
            try:
                summary = fetch_match_summary(lg, mid)
                json.dump(summary, io.open(cf, "w", encoding="utf-8"))
                tally["fetched"] += 1
                time.sleep(0.35)
            except Exception as exc:
                tally[f"fail_{type(exc).__name__}"] += 1
                continue
        rec = extract(summary)
        tally["completed" if rec["completed"] else f"status_{rec['status']}"] += 1
        if rec["completed"]:
            out[f"{lg}|{mid}"] = {**meta, **rec}
        if i % 50 == 0:
            print(f"  {i}/{len(fx)} {dict(tally)}", flush=True)
    json.dump(out, io.open(os.path.join(S, "outcomes.json"), "w", encoding="utf-8"))
    print("DONE", dict(tally), flush=True)

    # capture validation: player shots summed vs the team box score, per league
    agg = collections.defaultdict(lambda: [0.0, 0.0, 0.0, 0.0, 0])
    for rec in out.values():
        for side in ("home", "away"):
            t = rec["teams"].get(side) or {}
            ps = [p for p in rec["players"] if p["side"] == side]
            a = agg[rec["league"]]
            a[0] += sum(p["shots"] or 0 for p in ps); a[1] += t.get("totalShots") or 0
            a[2] += sum(p["sot"] or 0 for p in ps); a[3] += t.get("shotsOnTarget") or 0
        agg[rec["league"]][4] += 1
    print("\nleague               matches  player/team shots  player/team SOT  team shots/match  corners present")
    for lg, a in sorted(agg.items()):
        corners = sum(1 for r in out.values() if r["league"] == lg and (r["teams"].get("home") or {}).get("wonCorners") is not None)
        print(f"  {lg:20s} {a[4]:6d}   {a[0]/max(a[1],1):8.2f}          {a[2]/max(a[3],1):8.2f}        {a[1]/max(a[4],1):8.1f}        {corners}")


if __name__ == "__main__":
    main()
