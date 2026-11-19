"""Read-only: grade the 11-17 Layer 2 rail flags (T1-T4 pre-registered 11-17 10:25 AM CST) with the PRE-REGISTERED splits (lane layer2-rail-monitor).

Usage: py -3 grade1116.py <chips.json> [--json out.json]
- Population: flags whose FIRST sighting (read_at) is on 11-16 Central (>= 2026-11-16T06:00Z), keyed as the
  grader keys them (chip, market, segment, side incl. line), graded with scripts/layer2_rail_flag_grade.grade().
- Splits registered in findings_2026-11-16_layer2_rail_monitor.md BEFORE any 11-16 final was read:
  1. fade vs follow (5:41 PM): totals flags, by whether the flag opposes the book's main-line move for that game
     and segment since the game's previous reading.
  2. NCAAB pre / post 00:04:38Z (the #816 calibration load, 6:04 PM).
  3. raw vs calibrated (6:27 PM): model an exact k/102, k/204 or k/51 -> raw.
  4. NBA tail vs body (8:36 PM): book fair < 0.20 or > 0.80 -> tail.
- Each bucket: graded, W-L-P, hit rate, mean model p vs mean fair, Brier model vs fair, and a game-clustered
  bootstrap 90% interval on (hit rate - mean fair) (2,000 resamples of games, seed 7).
"""
import glob
import json
import os
import random
import sys
from collections import defaultdict

sys.path.insert(0, r"C:\Users\tempadmin\Coding\Syndicate\.claude\worktrees\brave-swanson-6e6c6a\scripts")
from layer2_rail_flag_grade import grade  # noqa: E402

READINGS = r"C:\tmp\railmon\readings"
import argparse as _ap
_a = _ap.ArgumentParser()
_a.add_argument("chips")
_a.add_argument("--day", required=True, help="slate date YYYY-MM-DD (CT)")
_a.add_argument("--pop-start", required=True, help="pre-registration instant, UTC YYYY-MM-DDTHH:MM; games commencing earlier are reported separately")
_a.add_argument("--json")
_ARGS = _a.parse_args()
DAY_START = _ARGS.day + "T06:00"
POP_START = _ARGS.pop_start
CAL_LOAD = "2026-11-17T00:04:38"


def raw_model(p):
    try:
        p = float(p)
    except (TypeError, ValueError):
        return False
    return any(abs(p * n - round(p * n)) < n * 5.1e-7 for n in (102, 204, 51))


def chip_first_seen():
    """{chip: earliest reading read_at in which the game appears as a live card on the rail}."""
    seen = {}
    for d in sorted(glob.glob(os.path.join(READINGS, "2026*"))):
        rp, rd = os.path.join(d, "rail.json"), os.path.join(d, "reading.json")
        if not (os.path.exists(rp) and os.path.exists(rd)):
            continue
        try:
            read_at = json.load(open(rd, encoding="utf-8")).get("read_at")
            rail = json.load(open(rp, encoding="utf-8"))
        except Exception:
            continue
        if not read_at or read_at < DAY_START:
            continue
        for c in rail.get("cards") or []:
            if c.get("live"):
                chip = str((c.get("chip") or {}).get("game_key") or "")
                if chip and (chip not in seen or read_at < seen[chip]):
                    seen[chip] = read_at
    return seen


def main_lines():
    """{reading read_at: {(chip, segment): main total line}} -- the line whose fair is closest to 0.5."""
    out = {}
    for d in sorted(glob.glob(os.path.join(READINGS, "2026*"))):
        rp, rd = os.path.join(d, "rail.json"), os.path.join(d, "reading.json")
        if not (os.path.exists(rp) and os.path.exists(rd)):
            continue
        try:
            read_at = json.load(open(rd, encoding="utf-8")).get("read_at")
            rail = json.load(open(rp, encoding="utf-8"))
        except Exception:
            continue
        if not read_at or read_at < DAY_START:
            continue
        best = {}
        for c in rail.get("cards") or []:
            if not c.get("live"):
                continue
            chip = str((c.get("chip") or {}).get("game_key") or "")
            for row in c.get("rows") or []:
                if row.get("market") != "totals":
                    continue
                fair, line = row.get("fair"), row.get("line")
                if fair is None or line is None:
                    continue
                key = (chip, str(row.get("segment") or "full"))
                score = abs(float(fair) - 0.5)
                if key not in best or score < best[key][0]:
                    best[key] = (score, float(line))
        out[read_at] = {k: v[1] for k, v in best.items()}
    return out


def boot(rows, seed=7, n=2000):
    """Game-clustered bootstrap 90% interval on hit rate - mean fair, over decided flags."""
    games = defaultdict(list)
    for r in rows:
        games[r["chip"]].append(r)
    keys = list(games)
    if len(keys) < 2:
        return None
    rng = random.Random(seed)
    stats = []
    for _ in range(n):
        pick = [games[rng.choice(keys)] for _ in keys]
        flat = [r for g in pick for r in g]
        if not flat:
            continue
        stats.append(sum(r["y"] for r in flat) / len(flat) - sum(r["fair"] for r in flat) / len(flat))
    stats.sort()
    return [round(stats[int(0.05 * len(stats))], 3), round(stats[int(0.95 * len(stats)) - 1], 3)]


def summarise(rows):
    dec = [r for r in rows if r["g"] in ("win", "loss")]
    w = sum(1 for r in dec if r["g"] == "win")
    p = sum(1 for r in rows if r["g"] == "push")
    out = {"graded": len(rows), "win": w, "loss": len(dec) - w, "push": p, "games": len({r["chip"] for r in rows})}
    if dec:
        out["hit_rate"] = round(w / len(dec), 3)
        out["mean_model_p"] = round(sum(r["model"] for r in dec) / len(dec), 3)
        out["mean_fair_p"] = round(sum(r["fair"] for r in dec) / len(dec), 3)
        out["brier_model"] = round(sum((r["model"] - r["y"]) ** 2 for r in dec) / len(dec), 4)
        out["brier_fair"] = round(sum((r["fair"] - r["y"]) ** 2 for r in dec) / len(dec), 4)
        out["hit_minus_fair_ci90"] = boot(dec)
    return out


def main():
    chips = {str(c.get("game_key")): c for c in json.load(open(_ARGS.chips, encoding="utf-8")).get("chips") or []}
    first = {}
    for line in open(os.path.join(READINGS, "flags.jsonl"), encoding="utf-8"):
        f = json.loads(line)
        k = (f.get("chip"), f["market"], f["segment"], f["side"])
        if k not in first or f["read_at"] < first[k]["read_at"]:
            first[k] = f
    first = {k: f for k, f in first.items() if f["read_at"] >= DAY_START}
    lines = main_lines()
    first_seen = chip_first_seen()
    stamps = sorted(lines)
    graded, skipped = [], defaultdict(int)
    for f in first.values():
        chip = chips.get(str(f.get("chip")))
        if not chip or chip.get("state") != "final":
            skipped["not_final" if chip else "no_chip"] += 1
            continue
        g, why = grade(f, chip)
        if g is None:
            skipped[why] += 1
            continue
        try:
            model, fair = float(f["model"]), float(f["fair"])
        except (TypeError, ValueError, KeyError):
            skipped["no_prob"] += 1
            continue
        start = str(chip.get("start_time_utc") or "")
        r = {"g": g, "y": 1.0 if g == "win" else 0.0, "model": model, "fair": fair, "chip": str(f.get("chip")), "start": start,
             "sport": f["sport"], "market": f["market"], "segment": f["segment"], "side": f["side"], "read_at": f["read_at"]}
        # 1. fade vs follow (totals only)
        r["move"] = None
        if f["market"] == "totals":
            # the reading that produced this flag is the latest stamp <= read_at; the previous one before it
            cur = [s for s in stamps if s <= f["read_at"]]
            if len(cur) >= 2:
                key = (str(f.get("chip")), f["segment"])
                now_line = lines[cur[-1]].get(key)
                prev = next((lines[s][key] for s in reversed(cur[:-1]) if key in lines[s]), None)
                if now_line is not None and prev is not None:
                    mv = now_line - prev
                    under = str(f["side"]).startswith("u")
                    r["move"] = "flat" if mv == 0 else ("fade" if (mv > 0) == under else "follow")
                else:
                    r["move"] = "no_prior_line"
            else:
                r["move"] = "no_prior_reading"
        graded.append(r)
    buckets = defaultdict(list)
    early = [r for r in graded if r["start"] and r["start"][:16].replace(" ", "T") < POP_START]
    for r in early:
        buckets["EARLY_before_preregistration:ALL"].append(r)
    graded = [r for r in graded if not (r["start"] and r["start"][:16].replace(" ", "T") < POP_START)]
    for r in graded:
        buckets["ALL"].append(r)
        # P3: flags sighted on the game's first rail reading
        fs = first_seen.get(r["chip"])
        import datetime as _dt
        _p = lambda x: _dt.datetime.fromisoformat(str(x)[:19])
        first_rd = fs is None or (_p(r['read_at']) - _p(fs)).total_seconds() < 600  # same reading: flags are stamped up to ~60 s after the reading start
        buckets[f"P3_first_reading:{'yes' if first_rd else 'no'}"].append(r)
        # P4: book fair band
        buckets[f"P4_fair:{'lt_0.40' if r['fair'] < 0.40 else 'ge_0.40'}"].append(r)
        # P5: NCAAB calibrated full-game live totals
        if r["sport"] == "ncaab" and r["market"] == "totals" and r["segment"] == "full":
            buckets["P5_ncaab_full_totals:ALL"].append(r)
            buckets[f"P5_ncaab_full_totals:{'under' if str(r['side']).startswith('u') else 'over'}"].append(r)
        buckets[f"sport:{r['sport']}"].append(r)
        buckets[f"market:{r['market']}:{'full' if r['segment'] == 'full' else 'segment'}"].append(r)
        if r["market"] == "totals":
            buckets[f"totals_side:{'under' if str(r['side']).startswith('u') else 'over'}"].append(r)
            buckets[f"S1_fade_follow:{r['move']}"].append(r)
        if r["sport"] == "ncaab":
            buckets[f"S2_ncaab:{'post_cal' if r['read_at'] >= CAL_LOAD else 'pre_cal'}"].append(r)
            if r["market"] == "totals" and r["segment"] == "full":
                buckets[f"S2_ncaab_full_totals:{'post_cal' if r['read_at'] >= CAL_LOAD else 'pre_cal'}"].append(r)
        if r["market"] == "totals":
            buckets[f"S3_{r['sport']}_totals:{'raw' if raw_model(r['model']) else 'calibrated_or_scaled'}"].append(r)
        # T1: book fair band (all flags)
        buckets[f"T1_fair:{'lt_0.40' if r['fair'] < 0.40 else 'ge_0.40'}"].append(r)
        # T2 / T3: full-game spreads (main + alternate)
        if r["segment"] == "full" and r["market"] in ("spreads", "spreads_alt"):
            if r["sport"] == "nba":
                buckets[f"T2_nba_full_spreads:{r['market']}"].append(r)
                buckets["T2_nba_full_spreads:ALL"].append(r)
            if r["sport"] == "ncaab":
                buckets["T3_ncaab_full_spreads:ALL"].append(r)
        # T4: NCAAB full-game totals (all post-#816 load on 11-17)
        if r["sport"] == "ncaab" and r["market"] == "totals" and r["segment"] == "full":
            buckets[f"T4_ncaab_full_totals:{'under' if str(r['side']).startswith('u') else 'over'}"].append(r)
            buckets["T4_ncaab_full_totals:ALL"].append(r)
        if r["sport"] == "nba":
            buckets[f"S4_nba:{'tail' if (r['fair'] < 0.20 or r['fair'] > 0.80) else 'body'}"].append(r)
    p5 = buckets.get("P5_ncaab_full_totals:ALL") or []
    went_over = sum(1 for r in p5 if (r["y"] == 1.0) == (not str(r["side"]).startswith("u")))
    out = {"population": f"first sighting on {_ARGS.day} CT (read_at >= {DAY_START}Z), games commencing >= {POP_START}Z; earlier games in EARLY_*",
           "p5_flagged_lines_went_over": f"{went_over} of {len(p5)}", "unique_flags": len(first),
           "graded": len(graded), "skipped": dict(skipped), "readings_with_lines": len(stamps),
           "buckets": {b: summarise(rs) for b, rs in sorted(buckets.items())}}
    print(json.dumps(out, indent=1))
    if _ARGS.json:
        json.dump(out, open(_ARGS.json, "w", encoding="utf-8"), indent=1)


if __name__ == "__main__":
    main()
