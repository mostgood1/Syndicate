# -*- coding: utf-8 -*-
"""Lane soccer-player-substrate, second measurement: WHY is a player who IS in the
current-season production file, under THIS club, missing from the predicted list?

  1. EMPTY SIDES: fixture sides the builder published with ZERO players.
  2. ALIAS GAPS: ESPN fixture clubs with no EXACT canonical match among the player-file
     team names (the builder binds exactly, `loaders._bind_player_team`).
  3. cur_same shooters split by LISTING HISTORY: was that player ever listed for that
     club on ANY date in the archive? And his first ESPN appearance vs this match.
  4. Coverage on each club's LATEST archived match only (the state now, after the
     weekly producer caught up), vs all dates.
"""
import collections
import datetime as dt
import glob
import os
import re

import pandas as pd

from common import LEAGUES, S, canonical_team_name, load_outcomes, load_recs
from decompose_squads import appeared, best_name_hits, load_player_files, same_club
from namejoin_diag import fold, strict_match


def main():
    recs, outc = load_recs(), load_outcomes()
    files = load_player_files()

    # ---- 2. alias gaps (exact canonical, as the builder binds)
    print("=== ALIAS GAPS: fixture clubs with no EXACT canonical team in any production player file ===")
    alias = {}
    for lg in LEAGUES:
        teams = set()
        for fr in files.get(lg, {}).values():
            for t in fr["team"].dropna().astype(str):
                for part in t.split(","):
                    if part.strip():
                        teams.add(canonical_team_name(part.strip()))
        clubs = {m[side] for (l, _), m in recs.items() if l == lg for side in ("home", "away")}
        miss = sorted(c for c in clubs if canonical_team_name(c) not in teams)
        alias[lg] = miss
        print(f"  {lg:20s} clubs={len(clubs):3d} unbound={len(miss):2d} {miss}")

    # ---- per-club listing history and ESPN appearance history
    listed = collections.defaultdict(set)          # (lg, club) -> folded names ever listed
    for (lg, mid), m in recs.items():
        for p in m["players"]:
            club = m["home"] if p.get("side") == "home" else m["away"]
            listed[(lg, club)].add(fold(p.get("player_name")))
    first_app = {}                                   # (lg, club, folded name) -> earliest match date
    for (lg, mid), o in outc.items():
        m = recs.get((lg, mid))
        if not m:
            continue
        for q in o["players"]:
            if not appeared(q):
                continue
            club = m["home"] if q["side"] == "home" else m["away"]
            key = (lg, club, fold(q["name"]))
            first_app[key] = min(first_app.get(key, "9999"), m["date"])

    empty = collections.Counter()
    empty_names = collections.defaultdict(collections.Counter)
    cls = collections.defaultdict(collections.Counter)
    latest_date = {}
    for (lg, mid), m in recs.items():
        if (lg, mid) in outc:
            for club in (m["home"], m["away"]):
                latest_date[(lg, club)] = max(latest_date.get((lg, club), ""), m["date"])
    cov_all = collections.defaultdict(lambda: [0.0, 0.0])
    cov_latest = collections.defaultdict(lambda: [0.0, 0.0])

    for (lg, mid), m in recs.items():
        o = outc.get((lg, mid))
        if not o:
            continue
        cur = files.get(lg, {}).get(2026)
        for side, club in (("home", m["home"]), ("away", m["away"])):
            preds = [p for p in m["players"] if p.get("side") == side]
            roster = [q for q in o["players"] if q["side"] == side]
            side_shots = sum((q["shots"] or 0) for q in roster if appeared(q))
            if not preds:
                empty[lg] += 1
                empty_names[lg][club] += 1
            mp = strict_match(preds, roster)
            bound = set(mp.values())
            covered = sum((q["shots"] or 0) for j, q in enumerate(roster) if appeared(q) and j in bound)
            cov_all[lg][0] += covered
            cov_all[lg][1] += side_shots
            if m["date"] == latest_date.get((lg, club)):
                cov_latest[lg][0] += covered
                cov_latest[lg][1] += side_shots
            for j, q in enumerate(roster):
                shots = q["shots"] or 0
                if not appeared(q) or shots <= 0 or j in bound:
                    continue
                if not preds:
                    cls[lg]["empty_side"] += shots
                    continue
                hits = best_name_hits(q["name"], cur)
                if not (hits and any(same_club(r.get("team"), club) for r in hits)):
                    continue
                name = fold(q["name"])
                ever = any(fold(n) == name or (n.split() and name.split() and n.split()[-1] == name.split()[-1] and n[:1] == name[:1])
                           for n in listed[(lg, club)])
                fa = first_app.get((lg, club, name), m["date"])
                days_since_first = (dt.date.fromisoformat(m["date"]) - dt.date.fromisoformat(fa)).days
                if ever:
                    cls[lg]["cur_same_listed_on_another_date"] += shots
                elif days_since_first >= 8:
                    cls[lg]["cur_same_NEVER_listed_established"] += shots
                else:
                    cls[lg]["cur_same_NEVER_listed_new"] += shots

    print("\n=== EMPTY SIDES (published with zero players) ===")
    for lg in LEAGUES:
        print(f"  {lg:20s} {empty[lg]:3d} sides  {dict(empty_names[lg])}")

    print("\n=== cur_same and empty-side shots, share of ALL real shots ===")
    print(f"{'league':20s} {'empty_side':>10s} {'listed_elsewhere':>16s} {'never_established':>17s} {'never_new':>9s}")
    for lg in LEAGUES:
        t = max(cov_all[lg][1], 1)
        c = cls[lg]
        print(f"{lg:20s} {100 * c['empty_side'] / t:9.1f}% {100 * c['cur_same_listed_on_another_date'] / t:15.1f}% "
              f"{100 * c['cur_same_NEVER_listed_established'] / t:16.1f}% {100 * c['cur_same_NEVER_listed_new'] / t:8.1f}%")

    print("\n=== COVERAGE: all archived matches vs each club's LATEST archived match ===")
    for lg in LEAGUES:
        a, l = cov_all[lg], cov_latest[lg]
        print(f"  {lg:20s} all {100 * a[0] / max(a[1], 1):5.1f}% ({int(a[1])} shots) | latest {100 * l[0] / max(l[1], 1):5.1f}% ({int(l[1])} shots)")


if __name__ == "__main__":
    main()
