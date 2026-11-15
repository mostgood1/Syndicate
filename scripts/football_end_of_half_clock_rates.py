"""Measure the END-OF-HALF CLOCK table for smartsim2 (todo #808, lane `football-end-of-half-fix`).

Pre-registered in `.syndicate/findings_2026-11-15_football_end_of_half_fix.md` before it was run. Reads FIT-season
play-by-play only:

  nfl    nflverse pbp 2024-25 REG   (`data/nfl_source/tracking/nflverse/pbp/pbp_<s>.csv`)
  ncaaf  CFBD plays 2024-25 FBS-vs-FBS REG   (`data/ncaaf_source/historical_truth/plays_<s>_wk<w>.json.gz`)

WINDOW: a snap with <= 120 s left in Q2 or Q4. For each window snap, DELTA = the clock at this snap minus the clock
at the next snap of the same quarter, classified by what the snap did:

  incomplete   the pass fell incomplete (the clock stops)
  oob          a run / completion that went out of bounds (not a TD or a turnover)
  first_down   NCAAF only: an in-bounds first down (the 2023 rule stops the clock in the last 2 minutes)
  to_off       an in-bounds play followed by the OFFENSE's timeout before the next snap
  to_def       ... followed by the DEFENSE's timeout
  run_<mode>   an in-bounds play with the clock running, by the offense's urgency mode
  penalty      a no-play penalty
  td / fg_good / fg_miss / punt / turnover / tod / safety   drive-ending: delta runs to the NEXT team's first snap,
               so it carries the kickoff or the return

URGENCY MODE is the engine's own `classify_urgency` on the real situation, with the candidate's Q2 rule (score-blind
two-minute drill), so the table is keyed on the same function the sim uses:
  hurry = two_minute_drill / trailing_urgency, preserve = halftime / end_game preservation, neutral = anything else.

CENSORING: a snap with no next snap in the quarter (the clock ran out) has no delta. Amendment 2 (pre-registered
before any FIT read): the running-clock and timeout cells (`run_*`, `to_off`, `to_def`) and every probability are
keyed on a 30 s CLOCK BUCKET (0-30 / 30-60 / 60-90 / 90-120 s left), and a bucket whose censored share exceeds 0.15
takes the (mean, sd) of the nearest bucket with more time left that is within it. The censored share is printed
beside each cell.

PROBABILITIES:
  p_incomplete[mode]           P(incomplete | an offensive play in the window) -- run / pass rows, sacks, kneels and
                               turnovers included; spikes, kicks, no-play penalties excluded (Amendment 1)
  p_oob[mode]                  P(out of bounds | run or completion, not a TD / turnover / kneel / spike)
  p_to_off[q][mode]            P(offense timeout right after a clock-running play | offense has one left)
  p_to_def[q][trail|lead]      P(defense timeout right after a clock-running play | no offense timeout, defense has one)
                               trail = the DEFENSE is behind or tied

Also prints the league's per-game window snaps with a game-bootstrap 95% CI (2000 reps, seed 3) -- the G3 target.

Read-only. Writes `C:/tmp/football_eoh_fix/clock_table_<sport>.json` and prints the Python literal for
`situation_model.END_OF_HALF_CLOCK_TABLES`.

    py -3 scripts/football_end_of_half_clock_rates.py nfl
    py -3 scripts/football_end_of_half_clock_rates.py ncaaf
"""
from __future__ import annotations

import collections
import csv
import gzip
import json
import random
import statistics
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from scripts._primary_tree import primary_tree  # noqa: E402
from syndicate.features.football.sim_engine.smartsim2.situation_model import (  # noqa: E402
    URGENCY_END_GAME_PRESERVATION,
    URGENCY_HALFTIME_PRESERVATION,
    URGENCY_TRAILING,
    URGENCY_TWO_MINUTE,
    classify_urgency,
)

WINDOW = 120
# Amendment 2: the running-clock and timeout cells are keyed on a 30 s clock bucket, and a bucket censored above
# CENSOR_LIMIT takes the nearest bucket with more time left (the >= 45 s floor this replaced measured only the slow
# part of the window and applied it everywhere).
CENSOR_LIMIT = 0.15
BUCKETED_DELTA = ("run_hurry", "run_preserve", "to_off", "to_def")


def bucket_of(secs: int) -> int:
    """0: <= 30 s left, 1: <= 60, 2: <= 90, 3: <= 120 -- the engine's `end_of_half_bucket`."""
    return 3 if secs > 90 else 2 if secs > 60 else 1 if secs > 30 else 0
SEASONS = (2024, 2025)
OUT = Path(r"C:\tmp\football_eoh_fix")
NFL_SNAP = {"pass", "run", "field_goal", "punt", "qb_kneel", "qb_spike"}
DRIVE_END = ("td", "fg_good", "fg_miss", "punt", "turnover", "tod", "safety")


def mode_of(quarter: int, secs: int, diff: int, yardline: int) -> str:
    """The candidate's urgency, bucketed. Q2's two-minute drill ignores the score (part 2 of #808)."""
    u = classify_urgency(quarter=quarter, seconds_remaining=secs, score_differential=diff, yardline=yardline)
    if quarter == 2 and secs <= 120 and u != URGENCY_HALFTIME_PRESERVATION:
        u = URGENCY_TWO_MINUTE
    if u in (URGENCY_TWO_MINUTE, URGENCY_TRAILING):
        return "hurry"
    if u in (URGENCY_HALFTIME_PRESERVATION, URGENCY_END_GAME_PRESERVATION):
        return "preserve"
    return "neutral"


def _f(x: Any, d: Optional[float] = None) -> Optional[float]:
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


class Acc:
    """Snap records -> the table."""

    def __init__(self, delta_bounds: Optional[Tuple[int, int]] = None) -> None:
        # NCAAF ONLY: CFBD's `clock` is the clock at the END of each play, and some rows sit out of order inside a
        # game, which produces negative and multi-minute deltas (SDs of 23-46 s on stopped-clock cells). Deltas
        # outside the bounds are dropped and the dropped share is reported per cell. NFL is unfiltered.
        self.delta_bounds = delta_bounds
        self.recs: List[Dict[str, Any]] = []          # one per window snap
        self.snaps_by_game: Dict[str, List[int]] = {}  # game -> [q2 snaps, q4 snaps]
        self.spikes = collections.Counter()

    def game(self, gid: str) -> None:
        self.snaps_by_game.setdefault(gid, [0, 0])

    def count(self, gid: str, quarter: int) -> None:
        self.snaps_by_game[gid][0 if quarter == 2 else 1] += 1

    def add(self, **rec: Any) -> None:
        self.recs.append(rec)

    def table(self) -> Dict[str, Any]:
        """Pooled cells, plus (Amendment 2) the running-clock / timeout deltas and every probability BY CLOCK BUCKET."""
        pooled = collections.defaultdict(list)
        bucketed = collections.defaultdict(list)
        cens = collections.Counter()
        tot = collections.Counter()
        dropped = collections.Counter()
        for r in self.recs:
            cat = r["cat"]
            if cat == "run":
                cat = f"run_{r['mode']}"
            key = (cat, bucket_of(r["secs"])) if cat in BUCKETED_DELTA else (cat, None)
            tot[key] += 1
            if r["delta"] is None:
                cens[key] += 1
                continue
            if self.delta_bounds and not (self.delta_bounds[0] <= r["delta"] <= self.delta_bounds[1]):
                dropped[key] += 1
                continue
            (bucketed if key[1] is not None else pooled)[key].append(r["delta"])

        def cell(key, xs):
            out = {"mean": round(statistics.fmean(xs), 2) if xs else None,
                   "sd": round(statistics.pstdev(xs), 2) if xs else None,
                   "n": len(xs), "censored": round(cens[key] / max(1, tot[key]), 3)}
            if self.delta_bounds:
                out["dropped"] = round(dropped[key] / max(1, tot[key]), 3)
            return out

        cells = {key[0]: cell(key, xs) for key, xs in sorted(pooled.items())}
        by_bucket: Dict[str, List[Dict[str, Any]]] = {}
        for cat in BUCKETED_DELTA:
            row = [cell((cat, b), bucketed.get((cat, b), [])) for b in range(4)]
            # CENSORING RULE (Amendment 2): a bucket censored above the limit takes the (mean, sd) of the nearest
            # bucket with MORE time left whose censored share is within it.
            for b in range(4):
                row[b]["from_bucket"] = b
                if row[b]["censored"] > CENSOR_LIMIT or row[b]["mean"] is None:
                    for b2 in range(b + 1, 4):
                        if row[b2]["censored"] <= CENSOR_LIMIT and row[b2]["mean"] is not None:
                            row[b]["mean"], row[b]["sd"], row[b]["from_bucket"] = row[b2]["mean"], row[b2]["sd"], b2
                            break
            if any(c["n"] for c in row):
                by_bucket[cat] = row

        def rate(rows, key_fn, hit_fn):
            num = collections.Counter()
            den = collections.Counter()
            for r in rows:
                k = key_fn(r)
                if k is None:
                    continue
                den[(k, bucket_of(r["secs"]))] += 1
                num[(k, bucket_of(r["secs"]))] += bool(hit_fn(r))
            keys = sorted({k for k, _ in den})
            p = {k: [round(num[(k, b)] / den[(k, b)], 4) if den[(k, b)] else 0.0 for b in range(4)] for k in keys}
            n = {k: [den[(k, b)] for b in range(4)] for k in keys}
            return p, n

        # p_oob: runs / completions that could go out of bounds
        p_oob, n_oob = rate(self.recs, lambda r: r["mode"] if r["oob_eligible"] else None, lambda r: r["cat"] == "oob")
        # Amendment 1: the incompletion share of offensive plays (run / pass rows, sacks, kneels and turnovers;
        # not spikes, kicks or no-play penalties)
        p_inc, n_inc = rate(self.recs, lambda r: r["mode"] if r.get("off_play") else None,
                            lambda r: r["cat"] == "incomplete")
        # timeouts right after a clock-running play (run / to_off / to_def / NCAAF first_down)
        running = [r for r in self.recs if r["cat"] in ("run", "to_off", "to_def", "first_down")]
        p_to_off, n_to_off = rate(running, lambda r: f"{r['quarter']}_{r['mode']}" if r["off_to"] >= 1 else None,
                                  lambda r: r["cat"] == "to_off")
        # the defense trails (or is tied) when the OFFENSE's diff is >= 0
        p_to_def, n_to_def = rate(
            [r for r in running if r["cat"] != "to_off"],
            lambda r: f"{r['quarter']}_{'trail' if r['diff'] >= 0 else 'lead'}" if r["def_to"] >= 1 else None,
            lambda r: r["cat"] == "to_def")
        return {"delta": cells, "delta_by_bucket": by_bucket, "p_incomplete": p_inc, "p_oob": p_oob,
                "p_to_off": p_to_off, "p_to_def": p_to_def,
                "n": {"p_incomplete_n": n_inc, "p_oob_n": n_oob, "p_to_off_n": n_to_off, "p_to_def_n": n_to_def}}

    def snaps_ci(self) -> Dict[str, Any]:
        games = sorted(self.snaps_by_game)
        out = {"games": len(games)}
        for i, q in ((0, "q2"), (1, "q4")):
            xs = [self.snaps_by_game[g][i] for g in games]
            rng = random.Random(3)
            boots = sorted(statistics.fmean(rng.choice(xs) for _ in xs) for _ in range(2000))
            out[q] = {"mean": round(statistics.fmean(xs), 3), "ci": [round(boots[49], 3), round(boots[1949], 3)]}
        return out


# ---------------------------------------------------------------------------- NFL

def _nfl_cat(r: Dict[str, str]) -> str:
    pt = r.get("play_type")
    if pt == "no_play":
        return "penalty"
    if r.get("interception") == "1" or r.get("fumble_lost") == "1":
        return "turnover"
    if r.get("safety") == "1":
        return "safety"
    if r.get("touchdown") == "1":
        return "td" if r.get("td_team") == r.get("posteam") else "turnover"
    if pt == "field_goal":
        return "fg_good" if r.get("field_goal_result") == "made" else "fg_miss"
    if pt == "punt":
        return "punt"
    if r.get("fourth_down_failed") == "1":
        return "tod"
    if pt == "qb_spike":
        return "spike"
    if r.get("incomplete_pass") == "1":
        return "incomplete"
    if r.get("out_of_bounds") == "1":
        return "oob"
    return "run"


def nfl(acc: Acc) -> None:
    root = primary_tree() / "data" / "nfl_source" / "tracking" / "nflverse" / "pbp"
    for season in SEASONS:
        by = collections.defaultdict(list)
        with open(root / f"pbp_{season}.csv", newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if r.get("season_type") == "REG":
                    by[r["game_id"]].append(r)
        for gid, rows in by.items():
            acc.game(gid)
            rows.sort(key=lambda r: _f(r.get("play_id"), 0.0))
            # the snap sequence the sim steps through: scrimmage snaps + no-play penalties (not timeouts)
            seq = []
            for i, r in enumerate(rows):
                q = int(_f(r.get("qtr"), 0) or 0)
                qs = _f(r.get("quarter_seconds_remaining"))
                if qs is None or q not in (1, 2, 3, 4):
                    continue
                pt = r.get("play_type")
                is_pen = pt == "no_play" and r.get("penalty") == "1" and r.get("timeout") != "1"
                if pt in NFL_SNAP or is_pen:
                    seq.append((i, q, int(qs)))
            for k, (i, q, qs) in enumerate(seq):
                r = rows[i]
                if q not in (2, 4) or qs > WINDOW:
                    continue
                cat = _nfl_cat(r)
                if r.get("play_type") in NFL_SNAP:
                    acc.count(gid, q)
                if cat == "spike":
                    acc.spikes[q] += 1
                    continue
                nxt = seq[k + 1] if k + 1 < len(seq) and seq[k + 1][1] == q else None
                j_end = nxt[0] if nxt else len(rows)
                if cat in ("run",):
                    tos = [x for x in rows[i + 1:j_end] if x.get("timeout") == "1" and _f(x.get("qtr")) == q]
                    if tos:
                        cat = "to_off" if tos[0].get("timeout_team") == r.get("posteam") else "to_def"
                diff = int(_f(r.get("score_differential"), 0) or 0)
                yl = 100 - int(_f(r.get("yardline_100"), 75) or 75)
                pt = r.get("play_type")
                acc.add(sport="nfl", game=gid, quarter=q, secs=qs, cat=cat, mode=mode_of(q, qs, diff, yl), diff=diff,
                        delta=(qs - nxt[2]) if nxt else None,
                        off_to=int(_f(r.get("posteam_timeouts_remaining"), 0) or 0),
                        def_to=int(_f(r.get("defteam_timeouts_remaining"), 0) or 0),
                        oob_eligible=(pt in ("run", "pass") and cat in ("run", "oob", "to_off", "to_def")
                                      and r.get("qb_kneel") != "1" and r.get("sack") != "1"),
                        off_play=pt in ("run", "pass", "qb_kneel"))
        print(f"nfl {season}: {len(by)} games", flush=True)


# ---------------------------------------------------------------------------- NCAAF

_CFBD_SNAP = {"Rush", "Pass Reception", "Pass Incompletion", "Sack", "Passing Touchdown", "Rushing Touchdown",
              "Punt", "Field Goal Good", "Field Goal Missed", "Interception", "Pass Interception Return",
              "Interception Return Touchdown", "Fumble Recovery (Own)", "Fumble Recovery (Opponent)",
              "Fumble Return Touchdown", "Safety", "Blocked Punt", "Blocked Field Goal", "Blocked Punt Touchdown",
              "Punt Return Touchdown", "Penalty"}


# Amendment 1's offensive plays: everything snapped from scrimmage except kicks, spikes and penalties.
_CFBD_OFFENSIVE_PLAY = {"Rush", "Pass Reception", "Pass Incompletion", "Sack", "Passing Touchdown", "Rushing Touchdown",
                        "Interception", "Pass Interception Return", "Interception Return Touchdown",
                        "Fumble Recovery (Own)", "Fumble Recovery (Opponent)", "Fumble Return Touchdown", "Safety"}


def _cfbd_cat(r: Dict[str, Any]) -> str:
    pt = r.get("playType")
    txt = str(r.get("playText") or "")
    low = txt.lower()
    if pt == "Penalty":
        return "penalty"
    if pt in ("Interception", "Pass Interception Return", "Interception Return Touchdown", "Fumble Recovery (Opponent)",
              "Fumble Return Touchdown"):
        return "turnover"
    if pt == "Safety":
        return "safety"
    if pt in ("Passing Touchdown", "Rushing Touchdown"):
        return "td"
    if pt == "Field Goal Good":
        return "fg_good"
    if pt in ("Field Goal Missed", "Blocked Field Goal"):
        return "fg_miss"
    if pt in ("Punt", "Blocked Punt", "Blocked Punt Touchdown", "Punt Return Touchdown"):
        return "punt"
    if int(r.get("down") or 0) == 4 and int(r.get("yardsGained") or 0) < int(r.get("distance") or 99) \
            and pt in ("Rush", "Pass Reception", "Pass Incompletion", "Sack"):
        return "tod"
    if "spike" in low:
        return "spike"
    if pt == "Pass Incompletion":
        return "incomplete"
    if "out of bounds" in low:
        return "oob"
    if "1st down" in low and pt in ("Rush", "Pass Reception"):
        return "first_down"
    return "run"


def _clock(r: Dict[str, Any]) -> Optional[int]:
    c = r.get("clock") or {}
    try:
        return int(c.get("minutes") or 0) * 60 + int(c.get("seconds") or 0)
    except (TypeError, ValueError):
        return None


def ncaaf(acc: Acc) -> None:
    root = primary_tree() / "data" / "ncaaf_source" / "historical_truth"
    for season in SEASONS:
        games = json.load(gzip.open(root / f"games_{season}.json.gz", "rt", encoding="utf-8"))
        fbs = {int(g["id"]) for g in games if g.get("seasonType") == "regular"
               and g.get("homeClassification") == "fbs" and g.get("awayClassification") == "fbs"}
        by = collections.defaultdict(list)
        for p in sorted(root.glob(f"plays_{season}_wk*.json.gz")):
            for r in json.load(gzip.open(p, "rt", encoding="utf-8")):
                if int(r.get("gameId") or 0) in fbs:
                    by[int(r["gameId"])].append(r)
        for gid, rows in by.items():
            gk = f"{season}_{gid}"
            acc.game(gk)
            rows.sort(key=lambda r: (int(r.get("driveNumber") or 0), int(r.get("playNumber") or 0), str(r.get("id"))))
            seq = []
            for i, r in enumerate(rows):
                q = int(r.get("period") or 0)
                c = _clock(r)
                if c is None or q not in (1, 2, 3, 4) or r.get("playType") not in _CFBD_SNAP:
                    continue
                seq.append((i, q, c))
            for k, (i, q, c) in enumerate(seq):
                r = rows[i]
                if q not in (2, 4) or c > WINDOW:
                    continue
                cat = _cfbd_cat(r)
                if cat != "penalty":
                    acc.count(gk, q)
                if cat == "spike":
                    acc.spikes[q] += 1
                    continue
                nxt = seq[k + 1] if k + 1 < len(seq) and seq[k + 1][1] == q else None
                j_end = nxt[0] if nxt else len(rows)
                if cat in ("run", "first_down"):
                    tos = [x for x in rows[i + 1:j_end] if x.get("playType") == "Timeout" and int(x.get("period") or 0) == q]
                    if tos:
                        txt = str(tos[0].get("playText") or "").lower()
                        off = str(r.get("offense") or "").lower()
                        cat = "to_off" if off and off in txt else "to_def"
                diff = int(r.get("offenseScore") or 0) - int(r.get("defenseScore") or 0)
                yl = 100 - int(r.get("yardsToGoal") or 75)
                pt = r.get("playType")
                acc.add(sport="ncaaf", game=gk, quarter=q, secs=c, cat=cat, mode=mode_of(q, c, diff, yl), diff=diff,
                        delta=(c - nxt[2]) if nxt else None,
                        off_to=int(r.get("offenseTimeouts") if r.get("offenseTimeouts") is not None else 0),
                        def_to=int(r.get("defenseTimeouts") if r.get("defenseTimeouts") is not None else 0),
                        oob_eligible=(pt in ("Rush", "Pass Reception") and cat in ("run", "oob", "to_off", "to_def",
                                                                                   "first_down")
                                      and "kneel" not in str(r.get("playText") or "").lower()),
                        off_play=pt in _CFBD_OFFENSIVE_PLAY)
        print(f"ncaaf {season}: {len(by)} FBS-vs-FBS games with plays (of {len(fbs)})", flush=True)


def _idle() -> None:
    """Research runs at Idle (the production fleet shares this machine)."""
    try:
        import os
        import psutil
        psutil.Process().nice(psutil.IDLE_PRIORITY_CLASS if os.name == "nt" else 19)
    except Exception:  # noqa: BLE001
        pass


def main(argv: List[str]) -> None:
    _idle()
    sport = argv[0] if argv else "nfl"
    acc = Acc(delta_bounds=(0, 60) if sport == "ncaaf" else None)
    (nfl if sport == "nfl" else ncaaf)(acc)
    table = acc.table()
    snaps = acc.snaps_ci()
    out = {"sport": sport, "seasons": list(SEASONS), "window": WINDOW, "censor_limit": CENSOR_LIMIT,
           "league_window_snaps": snaps, "spikes_per_game": {q: round(n / snaps["games"], 3) for q, n in acc.spikes.items()},
           **table}
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"clock_table_{sport}.json"
    path.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out, indent=1))
    print("wrote", path)


if __name__ == "__main__":
    main(sys.argv[1:])
