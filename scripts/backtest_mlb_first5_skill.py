"""Does the sim's FIRST-FIVE number have skill? Measured against real outcomes.

WHY THIS MEASUREMENT AND NOT ANOTHER. The live first-five readout landed in
`70622e0b` and is not deployed, so there is no served history to score. What IS
scoreable is the PREGAME first-five block the daily sim has been writing all
season -- `outputs[].first5.{home_win_prob, away_win_prob, tie_prob,
total_runs_dist}` -- and it comes out of the SAME `simulate_game` engine, from an
initial state instead of a mid-game one. The live readout counts the same event
(home runs > away runs through five innings) over the same trials.

So this answers a NECESSARY condition, and says so plainly rather than
overclaiming: if the engine's five-inning modelling has no skill from a pregame
state, the live version built on it is very unlikely to acquire any. If it does
have skill, that is evidence for -- not proof of -- the live one.

THE TIE IS THE PART THAT MATTERS MOST FOR THE CODE ALREADY SHIPPED. `first5`
carries `tie_prob` around 0.15 where `full` carries 0.0, and
`live_gameline_join.segment_home_win_prob` divides by `(1 - tie)` to match a
two-way book's leg frame. That conditioning is only sound if `tie_prob` is
calibrated, so it is measured here directly rather than assumed.

COVERAGE IS REPORTED, NOT ASSUMED. `CLAUDE.md` is explicit: print the per-family
date coverage and the intersection, and say how many dates the result rests on.
Outcomes come from MLB StatsAPI rather than the local mirror precisely because
the mirror's families do not line up -- production carries no `feed_live` and no
`roster_objs` at all.

Run:
    python scripts/backtest_mlb_first5_skill.py
    python scripts/backtest_mlb_first5_skill.py --json reports/first5_skill.json
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import os
import pathlib
import re
import sys
import time
import urllib.request
from collections import defaultdict

REPO = pathlib.Path(__file__).resolve().parents[1]
DAILY_GLOB = str(REPO / "data" / "mlb_source" / "source_artifacts" / "data" / "daily"
                 / "daily_summary_*.json")
CACHE = pathlib.Path(os.environ.get("TEMP", "/tmp")) / "mlb_linescore_cache"
DATE_RE = re.compile(r"(\d{4})_(\d{2})_(\d{2})")
SEGMENTS = ("first1", "first3", "first5", "full")
SEGMENT_INNINGS = {"first1": 1, "first3": 3, "first5": 5, "full": None}


# --------------------------------------------------------------------------
# model side
# --------------------------------------------------------------------------
def load_predictions() -> tuple[dict, dict]:
    """(date, game_pk) -> {segment: block}. Deduplicated across the day's files.

    A date has ~5 `daily_summary_*` variants (`_locked_policy`, `_hr_targets`,
    ...). They are unioned per game and the FIRST non-empty block for a segment
    wins; a later file disagreeing is counted and reported rather than silently
    overwritten, because two different predictions for one game would make the
    sample's provenance unreadable.
    """
    preds: dict = {}
    conflicts = defaultdict(int)
    files = sorted(glob.glob(DAILY_GLOB))
    for path in files:
        m = DATE_RE.search(pathlib.Path(path).name)
        if not m:
            continue
        date = "-".join(m.groups())
        try:
            with open(path, encoding="utf-8") as fh:
                doc = json.load(fh)
        except Exception:
            continue
        for out in doc.get("outputs") or []:
            if not isinstance(out, dict):
                continue
            pk = out.get("game_pk")
            if pk is None:
                continue
            slot = preds.setdefault((date, int(pk)), {})
            for seg in SEGMENTS:
                block = out.get(seg)
                if not isinstance(block, dict):
                    continue
                if block.get("home_win_prob") is None:
                    continue
                prior = slot.get(seg)
                if prior is None:
                    slot[seg] = block
                elif abs(float(prior["home_win_prob"]) - float(block["home_win_prob"])) > 1e-9:
                    conflicts[seg] += 1
    return preds, {"files": len(files), "conflicts": dict(conflicts)}


# --------------------------------------------------------------------------
# outcome side
# --------------------------------------------------------------------------
def linescores_for_date(date: str) -> dict:
    """game_pk -> per-inning runs, from StatsAPI. Cached on disk."""
    CACHE.mkdir(parents=True, exist_ok=True)
    cached = CACHE / f"{date}.json"
    if cached.is_file():
        try:
            return json.loads(cached.read_text(encoding="utf-8"))
        except Exception:
            pass
    url = (f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={date}"
           f"&hydrate=linescore")
    out: dict = {}
    try:
        with urllib.request.urlopen(url, timeout=60) as resp:
            doc = json.load(resp)
    except Exception as exc:
        print(f"  statsapi {date}: {type(exc).__name__}: {exc}", flush=True)
        return out
    for day in doc.get("dates") or []:
        for game in day.get("games") or []:
            state = str(((game.get("status") or {}).get("abstractGameState") or "")).lower()
            innings = (game.get("linescore") or {}).get("innings") or []
            out[str(game.get("gamePk"))] = {
                "state": state,
                "innings": [
                    {"away": ((i.get("away") or {}).get("runs")),
                     "home": ((i.get("home") or {}).get("runs"))}
                    for i in innings
                ],
            }
    cached.write_text(json.dumps(out), encoding="utf-8")
    time.sleep(0.2)
    return out


def segment_actual(innings: list, through: int | None) -> tuple[int, int] | None:
    """Runs through `through` innings, or the whole game when None.

    REFUSES a game that did not reach the segment. A rain-shortened five-inning
    game has a first5 result; a four-inning one does NOT, and treating its
    partial score as the segment outcome would score the model against an event
    that never resolved.
    """
    if through is None:
        away = sum(int(i["away"] or 0) for i in innings if i["away"] is not None)
        home = sum(int(i["home"] or 0) for i in innings if i["home"] is not None)
        return (away, home) if innings else None
    if len(innings) < through:
        return None
    window = innings[:through]
    # A missing HOME half in the final window inning is legitimate (the home
    # team does not bat when it is already ahead and the game ends), and its
    # runs are 0. A missing AWAY half is not something that happens.
    if any(i["away"] is None for i in window):
        return None
    away = sum(int(i["away"] or 0) for i in window)
    home = sum(int(i["home"] or 0) for i in window)
    return away, home


# --------------------------------------------------------------------------
# metrics
# --------------------------------------------------------------------------
def brier3(p_home: float, p_tie: float, p_away: float, outcome: str) -> float:
    return ((p_home - (outcome == "home")) ** 2
            + (p_tie - (outcome == "tie")) ** 2
            + (p_away - (outcome == "away")) ** 2)


def calibration(pairs: list[tuple[float, int]], bins: int = 5) -> list[dict]:
    """Predicted probability against realised rate, in equal-width bins."""
    buckets: dict[int, list] = defaultdict(list)
    for prob, hit in pairs:
        idx = min(bins - 1, max(0, int(prob * bins)))
        buckets[idx].append((prob, hit))
    rows = []
    for idx in sorted(buckets):
        vals = buckets[idx]
        rows.append({
            "bin": f"{idx / bins:.2f}-{(idx + 1) / bins:.2f}",
            "n": len(vals),
            "pred": sum(p for p, _ in vals) / len(vals),
            "actual": sum(h for _, h in vals) / len(vals),
        })
    return rows


def evaluate(rows: list[dict], label: str) -> dict:
    """Every metric for one segment, with its denominator attached."""
    n = len(rows)
    if n == 0:
        return {"segment": label, "n": 0, "verdict": "UNMEASURED"}

    base_home = sum(1 for r in rows if r["outcome"] == "home") / n
    base_tie = sum(1 for r in rows if r["outcome"] == "tie") / n
    base_away = sum(1 for r in rows if r["outcome"] == "away") / n

    model_b = sum(brier3(r["p_home"], r["p_tie"], r["p_away"], r["outcome"]) for r in rows) / n
    # CLIMATOLOGY, fitted on this very sample. That makes the baseline slightly
    # too GOOD, so the skill score below is conservative -- the honest direction
    # for a number that is being used to decide whether to bet.
    base_b = sum(brier3(base_home, base_tie, base_away, r["outcome"]) for r in rows) / n
    skill = 1.0 - (model_b / base_b) if base_b > 0 else None

    decisive = [r for r in rows if r["outcome"] != "tie"]
    two_way = None
    if decisive:
        pairs = []
        for r in decisive:
            denom = r["p_home"] + r["p_away"]
            if denom <= 0:
                continue
            pairs.append((r["p_home"] / denom, 1 if r["outcome"] == "home" else 0))
        if pairs:
            mb = sum((p - h) ** 2 for p, h in pairs) / len(pairs)
            rate = sum(h for _, h in pairs) / len(pairs)
            bb = sum((rate - h) ** 2 for _, h in pairs) / len(pairs)
            two_way = {
                "n": len(pairs),
                "brier": round(mb, 5),
                "baseline_brier": round(bb, 5),
                "skill_score": round(1.0 - mb / bb, 4) if bb > 0 else None,
                "calibration": calibration(pairs),
            }

    tie = None
    if label != "full":
        tie_pairs = [(r["p_tie"], 1 if r["outcome"] == "tie" else 0) for r in rows]
        tie = {
            "predicted_mean": round(sum(p for p, _ in tie_pairs) / n, 4),
            "actual_rate": round(base_tie, 4),
            "brier": round(sum((p - h) ** 2 for p, h in tie_pairs) / n, 5),
            "calibration": calibration(tie_pairs, bins=4),
        }

    mae = None
    totals = [r for r in rows if r.get("total_mean") is not None]
    if totals:
        mae = round(sum(abs(r["total_mean"] - r["actual_total"]) for r in totals) / len(totals), 3)

    return {
        "segment": label,
        "n": n,
        "base_rates": {"home": round(base_home, 4), "tie": round(base_tie, 4),
                       "away": round(base_away, 4)},
        "brier_3way": round(model_b, 5),
        "baseline_brier_3way": round(base_b, 5),
        "skill_score_3way": round(skill, 4) if skill is not None else None,
        "two_way_conditional": two_way,
        "tie": tie,
        "total_mean_mae": mae,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", type=pathlib.Path)
    ap.add_argument("--max-dates", type=int, default=0)
    args = ap.parse_args()

    preds, meta = load_predictions()
    pred_dates = sorted({d for d, _ in preds})
    print(f"MODEL SIDE   files={meta['files']}  games={len(preds)}  "
          f"dates={len(pred_dates)}  {pred_dates[0]}..{pred_dates[-1]}")
    if meta["conflicts"]:
        print(f"  conflicting duplicate predictions (first kept): {meta['conflicts']}")

    if args.max_dates:
        pred_dates = pred_dates[: args.max_dates]

    scored: dict = {seg: [] for seg in SEGMENTS}
    outcome_dates = set()
    skipped = defaultdict(int)
    for date in pred_dates:
        lines = linescores_for_date(date)
        if not lines:
            skipped["no_linescore_for_date"] += 1
            continue
        outcome_dates.add(date)
        for (d, pk), blocks in preds.items():
            if d != date:
                continue
            game = lines.get(str(pk))
            if game is None:
                skipped["game_not_in_statsapi"] += 1
                continue
            if game["state"] != "final":
                skipped["not_final"] += 1
                continue
            for seg, block in blocks.items():
                actual = segment_actual(game["innings"], SEGMENT_INNINGS[seg])
                if actual is None:
                    skipped[f"{seg}_never_resolved"] += 1
                    continue
                away, home = actual
                outcome = "home" if home > away else "away" if away > home else "tie"
                scored[seg].append({
                    "date": date, "game_pk": pk, "outcome": outcome,
                    "p_home": float(block.get("home_win_prob") or 0.0),
                    "p_away": float(block.get("away_win_prob") or 0.0),
                    "p_tie": float(block.get("tie_prob") or 0.0),
                    "total_mean": (
                        (float(block["away_runs_mean"]) + float(block["home_runs_mean"]))
                        if block.get("away_runs_mean") is not None
                        and block.get("home_runs_mean") is not None else None),
                    "actual_total": away + home,
                })

    print(f"OUTCOME SIDE dates fetched={len(outcome_dates)}")
    print(f"INTERSECTION games scored per segment: "
          f"{ {s: len(v) for s, v in scored.items()} }")
    print(f"  skipped: {dict(skipped)}")
    print()

    results = [evaluate(scored[seg], seg) for seg in SEGMENTS]
    for res in results:
        print(f"=== {res['segment']}  n={res['n']} ===")
        if res["n"] == 0:
            print("  UNMEASURED\n")
            continue
        print(f"  base rates       home {res['base_rates']['home']:.3f}  "
              f"tie {res['base_rates']['tie']:.3f}  away {res['base_rates']['away']:.3f}")
        print(f"  3-way Brier      {res['brier_3way']:.5f}  vs climatology "
              f"{res['baseline_brier_3way']:.5f}   SKILL {res['skill_score_3way']:+.4f}")
        tw = res["two_way_conditional"]
        if tw:
            print(f"  2-way (decisive) n={tw['n']}  Brier {tw['brier']:.5f}  vs "
                  f"{tw['baseline_brier']:.5f}   SKILL {tw['skill_score']:+.4f}")
            for row in tw["calibration"]:
                print(f"      {row['bin']}  n={row['n']:5d}  pred {row['pred']:.3f}  "
                      f"actual {row['actual']:.3f}")
        if res["tie"]:
            t = res["tie"]
            print(f"  TIE              predicted {t['predicted_mean']:.4f}  "
                  f"actual {t['actual_rate']:.4f}  Brier {t['brier']:.5f}")
        if res["total_mean_mae"] is not None:
            print(f"  total mean MAE   {res['total_mean_mae']:.3f} runs")
        print()

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(
            {"dates": sorted(outcome_dates), "skipped": dict(skipped),
             "results": results}, indent=2), encoding="utf-8")
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
