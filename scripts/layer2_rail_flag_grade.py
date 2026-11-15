"""Read-only: grade the Layer 2 rail's MODEL != LINE flags against finals (lane layer2-rail-monitor).

Usage: py -3 scripts/layer2_rail_flag_grade.py <flags.jsonl> <chips.json> [--json out.json]
Each flag is graded ONCE, at its first sighting, keyed (chip game_key, market, segment, side incl. line):
the first time the rail showed it is the price a viewer could have acted on. Settles against the final
chip's linescore. Halves include OT in 2H; quarters q1-q4; NCAAB plays halves (labels 1, 2, OT...).
Reports hit rate with its denominator, beside the sim's probability and the book's no-vig fair, and Brier
for both (lower is better). A flag is information, not a bet; this is the #780 check, not a P&L.
"""
import json
import sys
from collections import defaultdict


def num(v):
    try:
        return float(str(v).replace("−", "-"))
    except (TypeError, ValueError):
        return None


def periods(chip):
    ls = chip.get("linescore") or {}
    a, h = ls.get("away") or [], ls.get("home") or []
    return [num(x) or 0.0 for x in a], [num(x) or 0.0 for x in h]


def segment_score(chip, sport, seg):
    a, h = periods(chip)
    if seg == "full":
        sa, sh = num((chip.get("away") or {}).get("score")), num((chip.get("home") or {}).get("score"))
        return (sa, sh) if sa is not None and sh is not None else None
    if not a or not h:
        return None
    halves = sport == "ncaab"  # men's college plays two halves; the rest here play quarters
    if halves:
        idx = {"h1": [0], "h2": list(range(1, len(a)))}.get(seg)
    else:
        idx = {"q1": [0], "q2": [1], "q3": [2], "q4": [3], "h1": [0, 1], "h2": list(range(2, len(a)))}.get(seg)
    if not idx or max(idx) >= len(a) or max(idx) >= len(h):
        return None
    return sum(a[i] for i in idx), sum(h[i] for i in idx)


def grade(flag, chip):
    sc = segment_score(chip, flag["sport"], flag["segment"])
    if sc is None:
        return None, "no_score"
    away, home = sc
    side = str(flag["side"]).replace("−", "-").strip()
    if flag["market"] == "totals":
        line = num(side[1:])
        if line is None:
            return None, "bad_side"
        total = away + home
        if total == line:
            return "push", None
        return ("win" if (total > line) == (side[0] == "o") else "loss"), None
    abbr_a = str((chip.get("away") or {}).get("abbr") or "")
    abbr_h = str((chip.get("home") or {}).get("abbr") or "")
    parts = side.split()
    team = parts[0] if parts else ""
    if team == abbr_a:
        mine, theirs = away, home
    elif team == abbr_h:
        mine, theirs = home, away
    else:
        return None, "team_unmatched"
    if flag["market"] == "h2h":
        if mine == theirs:
            return "push", None
        return ("win" if mine > theirs else "loss"), None
    line = num(parts[1]) if len(parts) > 1 else None
    if line is None:
        line = 0.0 if len(parts) > 1 and parts[1] == "PK" else None
    if line is None:
        return None, "bad_side"
    margin = mine + line - theirs
    if margin == 0:
        return "push", None
    return ("win" if margin > 0 else "loss"), None


def main():
    flags_path, chips_path = sys.argv[1], sys.argv[2]
    chips = {str(c.get("game_key")): c for c in json.load(open(chips_path, encoding="utf-8")).get("chips") or []}
    first = {}
    for line in open(flags_path, encoding="utf-8"):
        f = json.loads(line)
        k = (f.get("chip"), f["market"], f["segment"], f["side"])
        if k not in first or f["read_at"] < first[k]["read_at"]:
            first[k] = f
    res = defaultdict(lambda: {"n": 0, "win": 0, "loss": 0, "push": 0, "model": [], "fair": [], "y": []})
    skipped = defaultdict(int)
    for k, f in first.items():
        chip = chips.get(str(f.get("chip")))
        if not chip or chip.get("state") != "final":
            skipped["not_final" if chip else "no_chip"] += 1
            continue
        g, why = grade(f, chip)
        if g is None:
            skipped[why] += 1
            continue
        for bucket in ("ALL", f"{f['sport']}", f"{f['market']}:{'full' if f['segment'] == 'full' else 'segment'}"):
            r = res[bucket]
            r["n"] += 1
            r[g] += 1
            if g != "push" and f.get("model") is not None and f.get("fair") is not None:
                r["model"].append(float(f["model"]))
                r["fair"].append(float(f["fair"]))
                r["y"].append(1.0 if g == "win" else 0.0)
    out = {"unique_flags": len(first), "skipped": dict(skipped), "buckets": {}}
    for b, r in sorted(res.items()):
        dec = r["win"] + r["loss"]
        m, fr, y = r["model"], r["fair"], r["y"]
        brier = (lambda p: round(sum((pi - yi) ** 2 for pi, yi in zip(p, y)) / len(y), 4)) if y else (lambda p: None)
        out["buckets"][b] = {
            "graded": r["n"], "win": r["win"], "loss": r["loss"], "push": r["push"],
            "hit_rate": round(r["win"] / dec, 3) if dec else None,
            "mean_model_p": round(sum(m) / len(m), 3) if m else None,
            "mean_fair_p": round(sum(fr) / len(fr), 3) if fr else None,
            "brier_model": brier(m), "brier_fair": brier(fr), "n_brier": len(y),
        }
    print(json.dumps(out, indent=1))
    if "--json" in sys.argv:
        json.dump(out, open(sys.argv[sys.argv.index("--json") + 1], "w"), indent=1)


if __name__ == "__main__":
    main()
