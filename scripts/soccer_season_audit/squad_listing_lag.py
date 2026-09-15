# -*- coding: utf-8 -*-
"""Lane soccer-player-substrate, third measurement -- the three facts the remedy choice turns on.

  A. "listed on another date": listed AFTER this match (file lag -> cadence / lineup
     source) or only BEFORE it (dropped later -> filter/dedupe behaviour)?
  B. Empty-side clubs: exact spelling in every production player file of EVERY league
     (alias gap vs promoted/relegated club carried by another league's file).
"""
import collections
import glob
import os
import re
from difflib import SequenceMatcher

import pandas as pd

from common import LEAGUES, S, canonical_team_name, load_outcomes, load_recs
from decompose_squads import appeared, best_name_hits, load_player_files, same_club
from namejoin_diag import fold, strict_match


def main():
    recs, outc = load_recs(), load_outcomes()
    files = load_player_files()

    # listing dates per (lg, club, folded name)
    listed_dates = collections.defaultdict(set)
    for (lg, mid), m in recs.items():
        for p in m["players"]:
            club = m["home"] if p.get("side") == "home" else m["away"]
            listed_dates[(lg, club, fold(p.get("player_name")))].add(m["date"])

    def listed_on(lg, club, name):
        name_toks = name.split()
        out = set()
        for (l, c, n), ds in listed_dates.items():
            if l != lg or c != club:
                continue
            nt = n.split()
            if n == name or (nt and name_toks and nt[-1] == name_toks[-1] and nt[0][:1] == name_toks[0][:1]):
                out |= ds
        return out

    lag = collections.defaultdict(collections.Counter)
    for (lg, mid), m in recs.items():
        o = outc.get((lg, mid))
        if not o:
            continue
        cur = files.get(lg, {}).get(2026)
        for side, club in (("home", m["home"]), ("away", m["away"])):
            preds = [p for p in m["players"] if p.get("side") == side]
            if not preds:
                continue
            roster = [q for q in o["players"] if q["side"] == side]
            bound = set(strict_match(preds, roster).values())
            for j, q in enumerate(roster):
                shots = q["shots"] or 0
                if not appeared(q) or shots <= 0 or j in bound:
                    continue
                hits = best_name_hits(q["name"], cur)
                if not (hits and any(same_club(r.get("team"), club) for r in hits)):
                    continue
                ds = listed_on(lg, club, fold(q["name"]))
                if not ds:
                    continue
                after = any(d > m["date"] for d in ds)
                before = any(d < m["date"] for d in ds)
                key = "listed_after_only" if after and not before else ("listed_before_only" if before and not after else "listed_before_and_after")
                lag[lg][key] += shots
    print("=== 'listed on another date' shots, by WHEN ===")
    for lg in LEAGUES:
        if lag[lg]:
            print(f"  {lg:20s} {dict(lag[lg])}")

    # empty-side clubs: where do their names live?
    all_teams = collections.defaultdict(lambda: collections.defaultdict(set))   # league -> season -> raw team names
    for lg, seasons in files.items():
        for season, fr in seasons.items():
            for t in fr["team"].dropna().astype(str):
                for part in t.split(","):
                    if part.strip():
                        all_teams[lg][season].add(part.strip())
    empty_clubs = collections.defaultdict(set)
    for (lg, mid), m in recs.items():
        if (lg, mid) not in outc:
            continue
        for side, club in (("home", m["home"]), ("away", m["away"])):
            if not [p for p in m["players"] if p.get("side") == side]:
                empty_clubs[lg].add(club)
    print("\n=== EMPTY-SIDE CLUBS: nearest spelling in each league's files (same league first, then any league) ===")
    for lg in LEAGUES:
        for club in sorted(empty_clubs[lg]):
            cc = canonical_team_name(club)
            best = []
            for lg2 in LEAGUES:
                for season, names in all_teams[lg2].items():
                    for n in names:
                        r = SequenceMatcher(None, cc, canonical_team_name(n)).ratio()
                        if cc in canonical_team_name(n) or canonical_team_name(n) in cc:
                            r = max(r, 0.9)
                        if r >= 0.6:
                            best.append((round(r, 2), lg2, season, n))
            best.sort(reverse=True)
            exact_same = any(canonical_team_name(n) == cc for s, names in all_teams[lg].items() for n in names)
            print(f"  {lg:18s} {club:28s} canon='{cc}' exact_in_own_league={exact_same} nearest={best[:4]}")


if __name__ == "__main__":
    main()
