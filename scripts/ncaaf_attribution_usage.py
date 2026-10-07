"""NCAAF data step, part 1 (lane `football-sim-player-attribution`): who touched the ball, from CFBD playText.

Pre-registered in `.syndicate/findings_2026-10-07_football_player_attribution.md` ("NCAAF data step")
-- the parse rules and the acceptance bar were fixed before this file existed.

    py -3 scripts/ncaaf_attribution_usage.py parse    --seasons 2023,2024,2025
    py -3 scripts/ncaaf_attribution_usage.py validate --season 2025

`parse` writes one row per attributed play (nflverse-shaped column names, so the NFL attribution
module's `build_team_usage` reads it unchanged). `validate` joins parsed per-player-game totals to the
CFBD box scores on (game, team, normalised name) and applies the pre-registered bar.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

TRUTH = Path(r"C:\Users\tempadmin\OneDrive\Coding\Syndicate\data\ncaaf_source\historical_truth")
BOX = Path(r"C:\Users\tempadmin\OneDrive\Coding\Syndicate\data\ncaaf_source\source_artifacts\data\processed"
           r"\player_game_stats\ncaaf_player_game_stats_snapshot.csv")
OUT = Path(r"C:\tmp\football_scenarios\ncaaf_attribution")

RUN = re.compile(r"^(?P<a>.+?) run for ")
COMPLETE = re.compile(r"^(?P<a>.+?) pass complete to (?P<b>.+?) for ")
INCOMPLETE = re.compile(r"^(?P<a>.+?) pass incomplete(?: to (?P<b>.+?))?\s*$")
SACK = re.compile(r"^(?P<a>.+?) sacked by ")
INTERCEPT = re.compile(r"^(?P<a>.+?) pass intercepted")
_SUFFIX = re.compile(r"\b(jr|sr|ii|iii|iv|v)\b\.?")
# Gamebook style (CFBD from 2025 week 9): "#47 B.Bachmeier pass complete short left to #11 P.Kingston ..."
# a name runs until the first lower-case word (the verbs are lower case): "#7 C.Del Rio-Wilson pass ..."
_GBN = r"#\d+\s+(?P<%s>[A-Za-z][A-Za-z'.\-]*(?:\s[A-Z][A-Za-z'.\-]*)*)"
# summary touchdown lines: "Landry Lyddy 7 Yd Run (X Kick)", "Elijah Metcalf 76 Yd pass from Landry Lyddy (X Kick)"
SUM_RUN = re.compile(r"^(?P<a>.+?) \d+ Yd Run\b")
SUM_PASS = re.compile(r"^(?P<b>.+?) \d+ Yd pass from (?P<a>[^,(]+?)(?:,| \(|$)")
PASS_TO = re.compile(r"^(?P<a>.+?) pass to (?P<b>.+?) for ")
GB_RUN = re.compile(_GBN % "a" + r"\s+(?:rush|scramble|kneels|takes)")
GB_COMPLETE = re.compile(_GBN % "a" + r"\s+pass complete\b.*?\bto\s+" + _GBN % "b")
GB_INCOMPLETE = re.compile(_GBN % "a" + r"\s+pass incomplete(?:.*?\b(?:intended for|to)\s+" + _GBN % "b" + r")?")
GB_SACK = re.compile(_GBN % "a" + r"\s+sacked")
GB_INTERCEPT = re.compile(_GBN % "a" + r"\s+pass intercepted")
# "B.Davenport steps back to pass. Pass incomplete intended for J.Henderson." (another 2025 style)
STEPBACK_INC = re.compile(r"^(?P<a>\S+) steps back to pass\. Pass incomplete(?: intended for (?P<b>[^.]+(?:\.[^.\s]+)?))?")
CATCHMADE = re.compile(r"^(?P<a>\S+) pass complete\. Catch made by (?P<b>\S+) for ")

RUSH_TYPES = {"Rush", "Rushing Touchdown"}
COMP_TYPES = {"Pass Reception", "Passing Touchdown", "Pass Completion"}
# offensive plays CFBD files under other types (a fumble after the run/catch, a counted penalty, ...)
OTHER_TYPES = {"Fumble Recovery (Own)", "Fumble Recovery (Opponent)", "Fumble", "Fumble Return Touchdown",
               "Penalty", "Uncategorized"}
INC_TYPES = {"Pass Incompletion"}
SACK_TYPES = {"Sack"}
INT_TYPES = {"Interception", "Pass Interception Return", "Interception Return Touchdown"}


def player_key(name: Optional[str]) -> str:
    """First initial + last name: the only identity every CFBD text style carries."""
    n = norm(name)
    if not n:
        return ""
    parts = n.split()
    return parts[0][0] + " " + parts[-1] if len(parts) > 1 else parts[0]


def resolve_key(key: str, roster: List[str]) -> str:
    """Map a parsed player key onto a team-game roster's keys: exact, else the UNIQUE same-last-name
    player, else the UNIQUE same-initial near-spelling (difflib >= 0.85). Unresolved -> unchanged.
    Applied identically wherever parsed players meet a roster (validation now, usage later)."""
    if not key or key in roster:
        return key
    import difflib
    last = key.split()[-1]
    same_last = [k for k in roster if k.split()[-1] == last]
    if len(same_last) == 1:
        return same_last[0]
    near = [k for k in roster if k[:1] == key[:1]
            and difflib.SequenceMatcher(None, k.split()[-1], last).ratio() >= 0.85]
    return near[0] if len(near) == 1 else key


def norm(name: Optional[str]) -> str:
    if not name:
        return ""
    s = name.lower().replace(".", ". ")             # "b.bachmeier" -> "b. bachmeier"
    if "," in s:                                   # "HILL, Jyaire" -> "jyaire hill"
        last, _, first = s.partition(",")
        s = f"{first} {last}"
    s = _SUFFIX.sub("", s)
    s = re.sub(r"[^a-z ]", "", s)
    return re.sub(r"\s+", " ", s).strip()


KNEEL = re.compile(r"^(?P<a>[A-Z][A-Za-z.'\- ]+?) (?:takes a knee|kneels)\b")
_BAD_NAME = re.compile(r"[\d,]|\bto\b|\bfor\b|\bpenalty\b|\bconversion\b", re.I)


def ok_name(name: Optional[str]) -> bool:
    """Reject fragments captured as names (2-pt / penalty text): digits, commas, connective words, > 4 words."""
    if not name:
        return True                      # an absent optional target is fine
    n = name.strip()
    return 0 < len(n) <= 40 and len(n.split()) <= 4 and not _BAD_NAME.search(n)


_YDS = re.compile(r"\bfor (?:(?P<nogain>no gain)|a loss of (?P<lossof>\d+)|loss of (?P<lossof2>\d+)|(?P<n>-?\d+) (?:yds?|yards?)(?P<loss> loss)?)"
                  r"|^.+? (?P<sum>\d+) Yd (?:Run|pass)\b", re.I)


def text_yards(text: str) -> Optional[int]:
    """The play's own gain as the text states it. CFBD's `yardsGained` folds in penalty yardage on
    some plays (amendment 3); None when the text states no yardage."""
    m = _YDS.search(text)
    if not m:
        return None
    if m["nogain"]:
        return 0
    if m["lossof"] or m["lossof2"]:
        return -int(m["lossof"] or m["lossof2"])
    if m["n"] is not None:
        y = int(m["n"])
        return -abs(y) if m["loss"] else y
    return int(m["sum"])


def parse_play(r: dict) -> Optional[dict]:
    t, text = r.get("playType"), (r.get("playText") or "").strip()
    if t in OTHER_TYPES:
        if "no play" in text.lower():
            return None
        # classify by the text's leading action, then parse as that type
        if COMPLETE.match(text) or PASS_TO.match(text) or GB_COMPLETE.search(text) or CATCHMADE.match(text):
            t = "Pass Reception"
        elif INCOMPLETE.match(text) or GB_INCOMPLETE.search(text):
            t = "Pass Incompletion"
        elif SACK.match(text) or GB_SACK.search(text):
            t = "Sack"
        elif RUN.match(text) or GB_RUN.search(text):
            t = "Rush"
        else:
            return None
    ty = text_yards(text)
    base = {"game_id": str(r.get("gameId")), "season": r.get("season"), "week": r.get("week"),
            "posteam": r.get("offense"), "yards_gained": ty if ty is not None else int(r.get("yardsGained") or 0),
            "touchdown": "1" if t in ("Rushing Touchdown", "Passing Touchdown") else "0",
            "passer_player_id": "", "receiver_player_id": "", "rusher_player_id": "", "complete_pass": "0", "sack": "0"}
    if t in RUSH_TYPES:
        m = RUN.match(text) or GB_RUN.search(text) or SUM_RUN.match(text) or KNEEL.match(text)
        if not m or not ok_name(m["a"]):
            return None
        return dict(base, play_type="run", rusher_player_id=player_key(m["a"]), rusher_player_name=m["a"])
    if t in COMP_TYPES:
        m = (COMPLETE.match(text) or GB_COMPLETE.search(text) or CATCHMADE.match(text) or SUM_PASS.match(text)
             or PASS_TO.match(text))
        if not m or not ok_name(m["a"]) or not ok_name(m["b"]):
            return None
        return dict(base, play_type="pass", passer_player_id=player_key(m["a"]), passer_player_name=m["a"],
                    receiver_player_id=player_key(m["b"]), receiver_player_name=m["b"], complete_pass="1")
    if t in INC_TYPES:
        m = INCOMPLETE.match(text) or GB_INCOMPLETE.search(text) or STEPBACK_INC.match(text)
        if not m or not ok_name(m["a"]) or not ok_name(m["b"]):
            return None
        return dict(base, play_type="pass", passer_player_id=player_key(m["a"]), passer_player_name=m["a"],
                    receiver_player_id=player_key(m["b"]) if m["b"] else "", receiver_player_name=m["b"] or "", yards_gained=0)
    if t in SACK_TYPES:
        m = SACK.match(text) or GB_SACK.search(text) or re.match(r"^(?P<a>.+?) sacked for", text)
        if not m or not ok_name(m["a"]):
            return None
        return dict(base, play_type="pass", passer_player_id=player_key(m["a"]), passer_player_name=m["a"], sack="1")
    if t in INT_TYPES:
        m = INTERCEPT.match(text) or GB_INTERCEPT.search(text)
        if not m or not ok_name(m["a"]):
            return None
        return dict(base, play_type="pass", passer_player_id=player_key(m["a"]), passer_player_name=m["a"], yards_gained=0,
                    interception="1")
    return None


COLS = ("game_id", "season", "week", "posteam", "play_type", "passer_player_id", "passer_player_name",
        "receiver_player_id", "receiver_player_name", "rusher_player_id", "rusher_player_name",
        "complete_pass", "sack", "interception", "touchdown", "yards_gained", "season_type")


def cmd_parse(seasons: List[int]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for season in seasons:
        n_type, n_ok = defaultdict(int), defaultdict(int)
        rows = []
        for wk in range(1, 17):
            p = TRUTH / f"plays_{season}_wk{wk:02d}.json.gz"
            if not p.exists():
                continue
            for r in json.load(gzip.open(p, "rt", encoding="utf-8")):
                t = r.get("playType")
                if t not in RUSH_TYPES | COMP_TYPES | INC_TYPES | SACK_TYPES | INT_TYPES | OTHER_TYPES:
                    continue
                n_type[t] += 1
                d = parse_play(r)
                if d is None:
                    continue
                n_ok[t] += 1
                d["season_type"] = "REG"
                rows.append(d)
        path = OUT / f"ncaaf_attributed_plays_{season}.csv"
        with path.open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(COLS), extrasaction="ignore")
            w.writeheader()
            for d in rows:
                w.writerow({c: d.get(c, "") for c in COLS})
        cov = {t: f"{n_ok[t]}/{n_type[t]} ({100 * n_ok[t] / n_type[t]:.1f}%)" for t in sorted(n_type)}
        print(f"{season}: {len(rows)} attributed plays -> {path}")
        print(f"   parse coverage {cov}")


def cmd_validate(season: int) -> None:
    # Box first: its team-game rosters are what `resolve_key` maps parsed players onto.
    box: Dict[Tuple[str, str, str], Dict[str, float]] = {}
    roster: Dict[Tuple[str, str], List[str]] = defaultdict(list)
    with BOX.open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            if int(r["season"]) != season:
                continue
            k = (r["game_id"], norm(r["team"]), player_key(r["player_name"]))
            box[k] = {s: float(r[s] or 0) for s in ("rushing_attempts", "rushing_yards", "receptions",
                                                    "receiving_yards", "passing_attempts", "passing_yards")}
            roster[k[:2]].append(k[2])
    parsed: Dict[Tuple[str, str, str], Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    resolved = changed = 0
    with (OUT / f"ncaaf_attributed_plays_{season}.csv").open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            g, team, y = r["game_id"], norm(r["posteam"]), float(r["yards_gained"] or 0)
            ros = roster.get((g, team), [])

            def pk(col: str) -> str:
                nonlocal resolved, changed
                raw = r[col]
                out = resolve_key(raw, ros) if raw else raw
                resolved += 1 if raw else 0
                changed += 1 if raw and out != raw else 0
                return out
            if r["play_type"] == "run" and r["rusher_player_id"]:
                d = parsed[(g, team, pk("rusher_player_id"))]
                d["rushing_attempts"] += 1
                d["rushing_yards"] += y
            elif r["play_type"] == "pass" and r["sack"] == "1" and r["passer_player_id"]:
                d = parsed[(g, team, pk("passer_player_id"))]      # NCAAF: a sack is QB rushing
                d["rushing_attempts"] += 1
                d["rushing_yards"] += y
            elif r["play_type"] == "pass" and r["sack"] != "1":
                if r["passer_player_id"]:
                    d = parsed[(g, team, pk("passer_player_id"))]
                    d["passing_attempts"] += 1
                    if r["complete_pass"] == "1":
                        d["passing_yards"] += y
                if r["complete_pass"] == "1" and r["receiver_player_id"]:
                    d = parsed[(g, team, pk("receiver_player_id"))]
                    d["receptions"] += 1
                    d["receiving_yards"] += y
    print(f"{season}: identity resolver remapped {changed} of {resolved} player references")
    games = {k[0] for k in parsed} & {k[0] for k in box}
    checks = (("rushing_yards", 5, "rushing_attempts"), ("receiving_yards", 5, "receptions"),
              ("rushing_attempts", 1, "rushing_attempts"), ("receptions", 1, "receptions"),
              ("passing_yards", 10, "passing_attempts"))
    print(f"{season}: games parsed {len({k[0] for k in parsed})}, box {len({k[0] for k in box})}, both {len(games)}")
    verdict = True
    for stat, tol, touch in checks:
        keys = {k for k in set(parsed) | set(box) if k[0] in games
                and ((parsed.get(k, {}).get(touch, 0) > 0) or (box.get(k, {}).get(touch, 0) > 0))}
        ok = sum(1 for k in keys if abs(parsed.get(k, {}).get(stat, 0.0) - box.get(k, {}).get(stat, 0.0)) <= tol)
        only_p = sum(1 for k in keys if k not in box)
        only_b = sum(1 for k in keys if k not in parsed)
        share = ok / len(keys) if keys else 0.0
        bar = 0.90
        verdict &= share >= bar
        print(f"   {stat:17} within +-{tol:<3} {ok}/{len(keys)} = {share:.3f}  {'PASS' if share >= bar else 'FAIL'}"
              f"   (parsed-only {only_p}, box-only {only_b})")
    print(f"   => {'ACCEPTED' if verdict else 'NOT ACCEPTED -- do not use'}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("parse", "validate"))
    ap.add_argument("--seasons", default="")
    ap.add_argument("--season", type=int, default=0)
    a = ap.parse_args()
    if a.cmd == "parse":
        cmd_parse([int(s) for s in a.seasons.split(",")])
    else:
        cmd_validate(a.season)


if __name__ == "__main__":
    main()
