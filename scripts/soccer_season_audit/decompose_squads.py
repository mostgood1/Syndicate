# -*- coding: utf-8 -*-
"""Lane soccer-player-substrate, measurement BEFORE code.

Why do real shots come from players the model does not list, and who are the
phantoms it lists instead? Substrates:
  - model lists: production recommendations_*.json (prod/recs)
  - outcomes: ESPN box scores (outcomes.json, 584 completed matches)
  - player files: PRODUCTION players_*.csv (prod/players, pulled 2026-09-15)
  - roster seed: git-tracked rosters_2026.csv (checkout, committed 2026-07-20) --
    labelled as a checkout read, used only to say whether a rescue COULD fire.

Unattributed shot classes (ESPN appeared player with shots, not bound to a predicted row):
  cur_same    in the CURRENT-season file under THIS club   -> builder/name defect
  cur_other   in the current file under ANOTHER club        -> team representation
  prior_same  only in a prior-season file, THIS club        -> name/union defect
  prior_other only in a prior-season file, ANOTHER club     -> intra-league transfer kept at old club
  absent      in no production file for this league         -> needs a current-season source
Phantom classes (predicted row, player not in the ESPN matchday squad at all):
  prior_only  not in the current-season file (departed-filter candidate)
  current     in the current-season file (injured / not selected / name miss)
"""
import collections
import glob
import io
import json
import os
import re
import sys

import pandas as pd

from common import LEAGUES, PRIMARY, S, canonical_team_name, load_outcomes, load_recs, match_team_name
from namejoin_diag import score, strict_match

CURRENT = {lg: 2026 for lg in LEAGUES}


def appeared(p):
    return bool(p["starter"] or p["subbed_in"] or (p.get("appearances") or 0) > 0)


def load_player_files():
    out = collections.defaultdict(dict)   # league -> season -> DataFrame
    for f in glob.glob(os.path.join(S, "prod", "players", "soccer_source_*_players_players_*.csv")):
        m = re.search(r"soccer_source_(.+)_players_players_(\d{4})\.csv$", os.path.basename(f))
        if not m:
            continue
        out[m.group(1)][int(m.group(2))] = pd.read_csv(f)
    return out


def load_roster_seeds():
    out = {}
    for f in glob.glob(os.path.join(PRIMARY, "data", "soccer_source", "*", "api", "rosters", "rosters_2026.csv")):
        lg = f.split(os.sep)[-4]
        try:
            out[lg] = pd.read_csv(f)
        except Exception:
            pass
    return out


def best_name_hits(name, frame, thr=0.84):
    """Rows of `frame` whose player_name scores >= thr against `name` (best score first)."""
    if frame is None or frame.empty:
        return []
    hits = []
    for rec in frame.to_dict("records"):
        s = score(name, rec.get("player_name"))
        if s >= thr:
            hits.append((s, rec))
    hits.sort(key=lambda x: -x[0])
    top = hits[0][0] if hits else None
    return [r for s, r in hits if s == top]


def same_club(team_value, club):
    parts = [p.strip() for p in str(team_value or "").split(",") if p.strip()]
    return any(canonical_team_name(p) == canonical_team_name(club) or match_team_name(p, [club]) is not None for p in parts)


def main():
    recs, outc = load_recs(), load_outcomes()
    files = load_player_files()
    seeds = load_roster_seeds()
    print("production player files:", {lg: sorted(v) for lg, v in files.items()})
    for lg in LEAGUES:
        for season, fr in sorted(files.get(lg, {}).items()):
            mins = [c for c in ("minutes", "minutes_played") if c in fr.columns]
            print(f"  {lg:20s} {season} rows={len(fr):4d} busiest_minutes={pd.to_numeric(fr[mins[0]], errors='coerce').max() if mins else 'n/a'} cols={list(fr.columns)[:14]}")
    shot_cls = collections.defaultdict(collections.Counter)
    phantom_cls = collections.defaultdict(collections.Counter)
    seed_rescuable = collections.Counter()
    examples = collections.defaultdict(list)
    for (lg, mid), m in recs.items():
        o = outc.get((lg, mid))
        if not o or not m["players"]:
            continue
        fl = files.get(lg, {})
        cur = fl.get(CURRENT[lg])
        prior = pd.concat([fr for s, fr in fl.items() if s != CURRENT[lg]], ignore_index=True) if any(s != CURRENT[lg] for s in fl) else None
        for side, club in (("home", m["home"]), ("away", m["away"])):
            preds = [p for p in m["players"] if p.get("side") == side]
            roster = [q for q in o["players"] if q["side"] == side]
            mp = strict_match(preds, roster)
            bound_j = set(mp.values())
            for j, q in enumerate(roster):
                shots = q["shots"] or 0
                if not appeared(q) or shots <= 0:
                    continue
                shot_cls[lg]["total"] += shots
                if j in bound_j:
                    shot_cls[lg]["covered"] += shots
                    continue
                ch = best_name_hits(q["name"], cur)
                if ch:
                    cls = "cur_same" if any(same_club(r.get("team"), club) for r in ch) else "cur_other"
                else:
                    ph = best_name_hits(q["name"], prior)
                    if ph:
                        cls = "prior_same" if any(same_club(r.get("team"), club) for r in ph) else "prior_other"
                    else:
                        cls = "absent"
                shot_cls[lg][cls] += shots
                if len(examples[(lg, cls)]) < 4:
                    examples[(lg, cls)].append(f"{q['name']} ({club})")
            matched_i = set(mp.keys())
            squad_names = [q["name"] for q in roster]
            for i, p in enumerate(preds):
                phantom_cls[lg]["predicted"] += 1
                if i in matched_i:
                    continue
                phantom_cls[lg]["unbound"] += 1
                in_cur = bool(best_name_hits(p.get("player_name"), cur))
                phantom_cls[lg]["current" if in_cur else "prior_only"] += 1
                phantom_cls[lg]["phantom_expected_shots_" + ("current" if in_cur else "prior_only")] += float(p.get("expected_shots") or 0.0)
                if not in_cur and len(examples[(lg, "phantom_prior_only")]) < 4:
                    examples[(lg, "phantom_prior_only")].append(f"{p.get('player_name')} ({club})")
            if lg in seeds:
                sd = seeds[lg]
                club_rows = sd[[same_club(t, club) for t in sd["team"]]] if "team" in sd.columns else sd.iloc[0:0]
                for j, q in enumerate(roster):
                    if appeared(q) and (q["shots"] or 0) > 0 and j not in bound_j and best_name_hits(q["name"], club_rows):
                        seed_rescuable[lg] += q["shots"]
    print("\nUNATTRIBUTED SHOTS, share of all real shots by appeared players")
    print(f"{'league':20s} {'shots':>6s} {'covered':>8s} {'cur_same':>8s} {'cur_oth':>8s} {'pri_same':>8s} {'pri_oth':>8s} {'absent':>7s} | {'in 07-20 seed':>13s}")
    res = {}
    for lg in LEAGUES:
        c = shot_cls[lg]
        t = max(c["total"], 1)
        row = {k: c[k] / t for k in ("covered", "cur_same", "cur_other", "prior_same", "prior_other", "absent")}
        row["shots"] = c["total"]
        row["seed_rescuable"] = seed_rescuable[lg] / t
        res[lg] = row
        print(f"{lg:20s} {int(c['total']):6d} {100 * row['covered']:7.1f}% {100 * row['cur_same']:7.1f}% {100 * row['cur_other']:7.1f}% {100 * row['prior_same']:7.1f}% {100 * row['prior_other']:7.1f}% {100 * row['absent']:6.1f}% | {100 * row['seed_rescuable']:12.1f}%")
    print("\nPHANTOMS: predicted rows NOT in the ESPN matchday squad")
    print(f"{'league':20s} {'predicted':>9s} {'unbound':>8s} {'prior_only':>10s} {'current':>8s} {'exp.shots prior_only':>21s} {'exp.shots current':>18s}")
    for lg in LEAGUES:
        c = phantom_cls[lg]
        print(f"{lg:20s} {c['predicted']:9d} {c['unbound']:8d} {c['prior_only']:10d} {c['current']:8d} {c['phantom_expected_shots_prior_only']:21.1f} {c['phantom_expected_shots_current']:18.1f}")
        res[lg]["phantoms"] = dict(c)
    print("\nEXAMPLES")
    for (lg, cls), ex in sorted(examples.items()):
        print(f"  {lg:18s} {cls:20s} {ex}")
    json.dump(res, open(os.path.join(S, "decompose_squads.json"), "w", encoding="utf-8"), indent=1)


if __name__ == "__main__":
    main()
