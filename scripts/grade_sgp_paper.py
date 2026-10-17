#!/usr/bin/env python
"""Grade the NFL same-game-parlay PAPER ledger against outcomes (lane `nfl-sgp-builder`, #621 paper only).

Reads `<data root>/cheatsheets/nfl/sgp_ledger.jsonl` (each parlay as first suggested: legs, our joint probability,
fair / worth-it / estimated odds) and grades every leg from that day's `<date>.reconciled.json` -- the production
grader's own results, keyed by `cheat_sheets.prop_result_key`, so a parlay is graded exactly as the sheet's props.

A parlay WINS when every leg wins, LOSES when any leg loses, is VOID when a leg is void (a player who did not play;
books' SGP void rules vary, so a void is never counted as either), and PENDING otherwise. Writes
`<data root>/cheatsheets/nfl/sgp_graded.jsonl` (one line per parlay, rewritten whole) and prints:
  * calibration -- realized joint hit rate vs the mean predicted `p_joint` (THE claim this ledger can test);
  * paper ROI at the WORTH-IT price (what a user who only bets at that price or better would at least get) and at
    the ESTIMATED book price (an assumption: the leg prices multiplied, less 18.5%).
Neither ROI is an edge claim. PRE-REGISTERED (findings_2026-10-16_nfl_sgp_correlations.md): no edge label until
real SGP prices are captured and a game-clustered test over >= 300 graded parlays clears zero.

  nice -n 19 python scripts/grade_sgp_paper.py --data-root /home/amyn/syndicate-prod/data
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.nfl.sgp import payout  # noqa: E402
from syndicate.features.shared import cheat_sheets as cs  # noqa: E402


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    out = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    except OSError:
        pass
    return out


def grade_one(record: Mapping[str, Any], reconciled: Mapping[str, Any] | None) -> dict[str, Any]:
    """WON / LOST / VOID / PENDING for one parlay, with each leg's result."""
    props = (reconciled or {}).get("props") or {}
    void = (reconciled or {}).get("void") or {}
    # The player's ACTUAL stat from any graded line of the same player x market: an alt-rung leg ("OVER 30.5 saves")
    # is usually not a line the sheet itself graded. Measured 10-16: 11 of 13 NHL parlays sat "pending" for that alone.
    actual: dict[tuple[str, str], float] = {}
    voided: set[tuple[str, str]] = set()
    for key, val in props.items():
        parts = str(key).split("|")
        if len(parts) == 4 and isinstance(val, dict) and val.get("v") is not None:
            actual[(parts[0], parts[1])] = float(val["v"])
    for key in void:
        parts = str(key).split("|")
        if len(parts) == 4:
            voided.add((parts[0], parts[1]))
    legs, results = [], []
    for leg in record.get("legs") or []:
        key = cs.prop_result_key(leg)
        parts = key.split("|")
        pm = (parts[0], parts[1]) if len(parts) == 4 else None
        value = (props.get(key) or {}).get("v")
        if key in void or (pm in voided and pm not in actual):
            res = "void"
        elif key in props and props[key].get("y") is not None:
            res = "won" if float(props[key]["y"]) >= 1 else "lost"
        elif pm in actual:
            value = actual[pm]
            try:
                line = float(leg.get("line"))
            except (TypeError, ValueError):
                line = None
            side = str(leg.get("side") or "").lower()
            if line is None and side == "yes":                 # Anytime TD: a yes leg wins on any TD
                res = "won" if value > 0 else "lost"
            elif line is None or value == line:
                res = "void"                                   # a push is graded like a void: never won or lost
            elif side in ("over", "yes"):
                res = "won" if value > line else "lost"
            else:
                res = "won" if value < line else "lost"
        else:
            res = "pending"
        legs.append({"bet": leg.get("bet"), "key": key, "result": res, "actual": value})
        results.append(res)
    if "lost" in results:
        status = "lost"
    elif "void" in results:
        status = "void"
    elif results and all(r == "won" for r in results):
        status = "won"
    else:
        status = "pending"
    return {"sgp_id": record.get("sgp_id"), "date": record.get("date"), "event_id": record.get("event_id"),
            "relation": record.get("relation"), "same_player": record.get("same_player"),
            "p_joint": record.get("p_joint"), "worth_it_odds": record.get("worth_it_odds"),
            "est_book_odds": record.get("est_book_odds"), "status": status, "legs": legs}


def summarize(graded: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Calibration and paper ROI over the settled parlays, with a game-clustered SE on the hit-rate gap."""
    graded = list(graded)
    settled = [g for g in graded if g["status"] in ("won", "lost") and g.get("p_joint") is not None]
    out: dict[str, Any] = {"settled": len(settled), "void": sum(1 for g in graded if g["status"] == "void"),
                           "pending": sum(1 for g in graded if g["status"] == "pending")}
    if not settled:
        return out
    won = [1.0 if g["status"] == "won" else 0.0 for g in settled]
    pred = [float(g["p_joint"]) for g in settled]
    per_game: dict[str, float] = defaultdict(float)
    for g, w, p in zip(settled, won, pred):
        per_game[str(g.get("event_id"))] += w - p
    n, games = len(settled), len(per_game)
    gap = sum(won) / n - sum(pred) / n
    se = math.sqrt(sum(v * v for v in per_game.values()) * games / max(games - 1, 1)) / n
    out.update({"games": games, "hit_rate": round(sum(won) / n, 4), "predicted": round(sum(pred) / n, 4),
                "gap": round(gap, 4), "gap_se_game_clustered": round(se, 4),
                "brier": round(sum((w - p) ** 2 for w, p in zip(won, pred)) / n, 4)})
    for label, field in (("worth_it", "worth_it_odds"), ("est_book", "est_book_odds")):
        pays = [(payout(g.get(field)) or 0.0) for g in settled]
        if all(pays):
            out[f"roi_at_{label}_price"] = round(sum(w * d for w, d in zip(won, pays)) / n - 1.0, 4)
    for rel in ("same_player", "teammate", "opponent"):
        sub = [(w, p) for g, w, p in zip(settled, won, pred) if g.get("relation") == rel]
        if sub:
            out[rel] = {"n": len(sub), "hit_rate": round(sum(w for w, _ in sub) / len(sub), 4),
                        "predicted": round(sum(p for _, p in sub) / len(sub), 4)}
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-root", default=os.environ.get("SYNDICATE_DATA_ROOT") or "")
    ap.add_argument("--sport", default="nfl", choices=("nfl", "nhl"))
    args = ap.parse_args(argv)
    if not args.data_root:
        print("REFUSING: no --data-root", flush=True)
        return 2
    base = Path(os.path.expanduser(args.data_root)) / "cheatsheets" / args.sport
    ledger = read_jsonl(base / "sgp_ledger.jsonl")
    cache: dict[str, Any] = {}
    graded = []
    for record in ledger:
        day = str(record.get("date") or "")
        if day not in cache:
            try:
                cache[day] = json.loads((base / f"{day}.reconciled.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                cache[day] = None
        graded.append(grade_one(record, cache[day]))
    if graded:
        tmp = base / "sgp_graded.jsonl.tmp"
        tmp.write_text("".join(json.dumps(g) + "\n" for g in graded), encoding="utf-8")
        os.replace(tmp, base / "sgp_graded.jsonl")
    print(f"SGP_PAPER {args.sport} {json.dumps(summarize(graded))} ledger={len(ledger)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
