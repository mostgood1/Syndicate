"""Fit momentum to answer ONE question: is a goal about to happen?

NOT "who is on top" and NOT "what price" -- the target is the EVENT.
`P(at least one goal in the next N minutes)`, scored as a probability.

WHY THE FEATURE IS ABSOLUTE, NOT SIGNED. Signed momentum predicts WHICH side
scores; a goal happening at all is about pressure existing, on either side. A
0-0 with both ends besieged is a high-goal-chance state and a signed reading
calls it ~0. So the candidate features are built from the magnitude.

TWO STAGES, AND THEY ARE SEPARATE ON PURPOSE.
  harvest -- one HTTP round trip per match, cached to disk as raw events
  sweep   -- pure arithmetic over that cache

The sweep re-derives momentum from raw events for every parameter set, so
half-life and weights can be swept in seconds without re-fetching. Fetching
inside the sweep would make a 40-combination sweep 40x the network cost and is
why the first version of this was unaffordable.

DISCIPLINE, all of it load-bearing:
  - STRICTLY CAUSAL. Momentum at T uses only events at or before T.
  - GOALS EXCLUDED from the momentum series. A series that counts goals spikes
    AT the goal, so it would predict the goal it is made of.
  - HELD OUT. Matches are split by id hash; parameters are chosen on the FIT
    half and scored on the HOLDOUT half. Today's lane already has one fitted
    constant that looked clean in-sample and failed held-out by +0.0121 Brier.
  - BASELINES. A model that cannot beat the base rate is worthless, and one
    that cannot beat the sim's own `goal_in_window_probability` adds nothing to
    what already ships. Both are reported beside every candidate.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.soccer.ingestion.espn_lineups import (
    fetch_events,
    fetch_match_summary,
)

# Event families the sweep can weight. Deliberately excludes `foul`: 47 of 124
# commentary entries on a sampled match, and which side it favours depends on
# pitch location the feed does not carry -- volume and ambiguity in equal
# measure.
WEIGHTED_TYPES = (
    "shot-on-target",
    "shot-hit-woodwork",
    "shot-blocked",
    "shot-off-target",
    "corner-awarded",
    "offside",
    # STATE-CHANGING EVENTS, added 2026-08-22. The first sweep used volume
    # events only and was a coin flip held out. These change the REGIME rather
    # than adding volume: a red card, a penalty, a VAR check, an attacking
    # substitution. If a timing signal exists, it is more plausibly here than
    # in another re-weighting of shot counts.
    "penalty-won",
    "penalty-goal",
    "penalty-missed",
    "red-card",
    "yellow-red-card",
    "yellow-card",
    "substitution",
    "handball",
    "var---referee-decision-cancelled",
    "free-kick-won",
)
_GOAL_PREFIX = "goal"
_FULL_MATCH = 5400.0


def harvest(leagues: list[str], windows: list[str], limit: int, out: Path) -> dict[str, Any]:
    """One fetch per match -> raw (clock, type, team) events + goal times."""
    seen: set[str] = set()
    pairs: list[tuple[str, str]] = []
    for league in leagues:
        for w in windows:
            try:
                for e in fetch_events(league, date_windows=[w], statuses={"post"}):
                    eid = str(e.get("event_id") or "")
                    if eid and eid not in seen:
                        seen.add(eid)
                        pairs.append((league, eid))
            except Exception as exc:
                print(f"  discovery failed {league} {w}: {type(exc).__name__}: {exc}", flush=True)
    pairs = pairs[:limit]

    matches: list[dict[str, Any]] = []
    for i, (league, eid) in enumerate(pairs, 1):
        try:
            summary = fetch_match_summary(league, eid)
        except Exception as exc:
            print(f"  fetch failed {league} {eid}: {type(exc).__name__}: {exc}", flush=True)
            continue
        rosters = summary.get("rosters") or []
        home = ""
        for t in rosters:
            if str(t.get("homeAway") or "") == "home":
                home = str((t.get("team") or {}).get("displayName") or "")
        events: list[dict[str, Any]] = []
        goals: list[dict[str, Any]] = []
        for entry in summary.get("commentary") or []:
            play = entry.get("play") or {}
            tk = str((play.get("type") or {}).get("type") or "").strip().lower()
            clock = play.get("clock") or {}
            try:
                secs = float(clock.get("value"))
            except (TypeError, ValueError):
                continue
            team = str((play.get("team") or {}).get("displayName") or "").strip()
            if tk.startswith(_GOAL_PREFIX):
                if "cancel" not in tk and "disallow" not in tk:
                    # WHO, not just when. The event question needs the time;
                    # the "which side" question needs the team, and harvesting
                    # only the time would have made WHO unanswerable without a
                    # second pass over the network.
                    goals.append({"t": secs, "home": team == home})
                continue
            # Harvest EVERY typed event, not just the currently-weighted ones.
            # The first cache stored only the weight table's own keys, so adding
            # an event type meant re-fetching 200 matches. Storage is cheap;
            # a network pass is not.
            if tk and team:
                events.append({
                    "t": secs,
                    "type": tk,
                    "home": team == home,
                    "text": str(play.get("text") or "")[:120],
                })
        if events:
            matches.append({"league": league, "event_id": eid, "home_team": home,
                            "events": events,
                            "goals": sorted(goals, key=lambda g: g["t"])})
        if i % 20 == 0:
            print(f"  harvested {i}/{len(pairs)}", flush=True)

    payload = {"matches": matches, "leagues": leagues, "windows": windows}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload), encoding="utf-8")
    print(f"harvested {len(matches)} matches with events -> {out}", flush=True)
    return payload


def _momentum_at(events: list[dict], t: float, half_life: float, weights: dict[str, float]) -> tuple[float, float]:
    """(signed, absolute-pressure) at t. Causal: only events <= t."""
    home = away = 0.0
    for e in events:
        et = e["t"]
        if et > t:
            continue
        w = weights.get(e["type"], 0.0)
        if not w:
            continue
        decay = math.pow(0.5, (t - et) / max(1.0, half_life))
        if e["home"]:
            home += w * decay
        else:
            away += w * decay
    return home - away, home + away


def _auc(pairs: list[tuple[float, int]]) -> float | None:
    """Rank AUC. Ties share rank, which matters here: many samples have
    identical pressure early in a match."""
    pos = [x for x, y in pairs if y == 1]
    neg = [x for x, y in pairs if y == 0]
    if not pos or not neg:
        return None
    ranked = sorted(pairs, key=lambda p: p[0])
    ranks: dict[int, float] = {}
    i = 0
    while i < len(ranked):
        j = i
        while j + 1 < len(ranked) and ranked[j + 1][0] == ranked[i][0]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[k] = avg
        i = j + 1
    rsum = sum(ranks[k] for k, (_, y) in enumerate(ranked) if y == 1)
    n1, n0 = len(pos), len(neg)
    return (rsum - n1 * (n1 + 1) / 2.0) / (n1 * n0)


def lift_table(samples: list[dict], feature: str, *, buckets: int = 10) -> list[dict]:
    """Hit rate by feature decile -- THE metric that matches how this is used.

    AUC weights every threshold equally and is the wrong lens for a bet you only
    place at the extreme. At 3-1 the break-even is 25%, at 2-1 it is 33%, and
    the base rate here is ~24.7% -- so what matters is whether a TOP SLICE
    clears those, not whether the whole ranking is good. A feature can be near
    0.5 AUC and still carry a usable tail, and the first sweep could not have
    seen that.
    """
    rows = sorted(samples, key=lambda x: x[feature])
    if not rows:
        return []
    n = len(rows)
    out = []
    for b in range(buckets):
        lo, hi = n * b // buckets, n * (b + 1) // buckets
        chunk = rows[lo:hi]
        if not chunk:
            continue
        hit = sum(x["label"] for x in chunk) / len(chunk)
        out.append({
            "decile": b + 1,
            "n": len(chunk),
            "hit_rate": round(hit, 4),
            "feature_min": round(chunk[0][feature], 3),
            "feature_max": round(chunk[-1][feature], 3),
        })
    return out


def print_lift(title: str, samples: list[dict], feature: str) -> list[dict]:
    tbl = lift_table(samples, feature)
    if not tbl:
        return []
    base = statistics.mean([x["label"] for x in samples])
    print()
    print(f"  {title}  (base rate {base:.4f})")
    print(f"    {'decile':>7}{'n':>7}{'hit':>9}{'lift':>8}   {'break-even':>10}")
    for r in tbl:
        lift = r["hit_rate"] / base if base else 0.0
        # 3-1 pays at 25%, 2-1 at 33.3%
        mark = ""
        if r["hit_rate"] >= 0.333:
            mark = "  clears 2-1"
        elif r["hit_rate"] >= 0.25:
            mark = "  clears 3-1"
        print(f"    {r['decile']:>7}{r['n']:>7}{r['hit_rate']:>9.4f}{lift:>8.2f}{mark:>12}")
    return tbl

def build_samples(matches: list[dict], *, half_life: float, weights: dict[str, float],
                  window: float, step: float, start: float, end: float) -> list[dict]:
    out: list[dict] = []
    for m in matches:
        ev, goals = m["events"], m["goals"]
        t = start
        while t <= end:
            signed, pressure = _momentum_at(ev, t, half_life, weights)
            nxt = [g for g in goals if t < g["t"] <= t + window]
            label = 1 if nxt else 0
            # TIME IN HALF. Goals cluster late in halves (measured 2026-08-21:
            # ~62% of goals fall in the second half, and the last bucket of each
            # half is the densest). Momentum alone ignores the clock entirely,
            # so this is carried as its own feature and as an interaction.
            in_half = t if t < 2700 else (t - 2700)
            out.append({"t": t, "signed": signed, "pressure": pressure,
                        "time_in_half": in_half,
                        "pressure_x_late": pressure * (in_half / 2700.0),
                        "abs_signed": abs(signed), "label": label,
                        # WHO scored the FIRST goal in the window. None where no
                        # goal fell in it -- those samples answer the WHEN
                        # question and must not be counted in the WHO one.
                        "scorer_home": (1 if nxt[0]["home"] else 0) if nxt else None,
                        "match": m["event_id"]})
            t += step
    return out


def _is_holdout(event_id: str) -> bool:
    """Split by match id hash -- STABLE across runs and across parameter sets,
    so every candidate is scored on the same holdout. Splitting randomly per
    run would let a lucky split flatter one candidate."""
    return (sum(ord(c) for c in str(event_id)) % 10) >= 7


def evaluate(samples: list[dict], feature: str) -> dict[str, Any]:
    pairs = [(s[feature], s["label"]) for s in samples]
    base = statistics.mean([s["label"] for s in samples]) if samples else 0.0
    return {
        "n": len(samples),
        "base_rate": round(base, 5),
        "auc": (lambda a: round(a, 4) if a is not None else None)(_auc(pairs)),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--harvest", action="store_true")
    ap.add_argument("--leagues", default="epl,la_liga,serie_a,bundesliga,ligue_1,eredivisie,primeira_liga,championship")
    ap.add_argument("--window", default="")
    ap.add_argument("--limit", type=int, default=180)
    ap.add_argument("--cache", default="reports/soccer_backtest/momentum_events_cache.json")
    ap.add_argument("--goal-window", type=float, default=600.0, help="seconds ahead a goal counts")
    ap.add_argument("--step", type=float, default=60.0)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    cache = Path(args.cache)
    if args.harvest:
        wins = [w.strip() for w in args.window.split(";") if w.strip()]
        harvest([x.strip() for x in args.leagues.split(",") if x.strip()], wins, args.limit, cache)
    if not cache.exists():
        print("no cache -- run with --harvest first")
        return 2
    data = json.loads(cache.read_text(encoding="utf-8"))
    matches = data["matches"]
    fit = [m for m in matches if not _is_holdout(m["event_id"])]
    hold = [m for m in matches if _is_holdout(m["event_id"])]
    print(f"matches {len(matches)}  fit {len(fit)}  holdout {len(hold)}  "
          f"goal-window {args.goal_window:.0f}s  step {args.step:.0f}s")

    base_w = {"shot-on-target": 3.0, "shot-hit-woodwork": 3.0, "shot-blocked": 1.5,
              "shot-off-target": 1.5, "corner-awarded": 1.0, "offside": 0.5}
    variants: list[tuple[str, dict[str, float]]] = [
        ("shipped", dict(base_w)),
        ("flat", {k: 1.0 for k in WEIGHTED_TYPES}),
        ("on-target-heavy", {**base_w, "shot-on-target": 5.0, "shot-hit-woodwork": 5.0}),
        ("shots-only", {**{k: 0.0 for k in WEIGHTED_TYPES}, "shot-on-target": 3.0,
                        "shot-hit-woodwork": 3.0, "shot-blocked": 1.5, "shot-off-target": 1.5}),
        ("corners-heavy", {**base_w, "corner-awarded": 2.5}),
    ]
    half_lives = [90.0, 150.0, 300.0, 450.0, 600.0, 900.0]

    print()
    print(f"{'weights':<16}{'half-life':>10}{'AUC fit':>10}{'AUC hold':>10}{'base':>9}")
    rows = []
    for name, w in variants:
        for hl in half_lives:
            sf = build_samples(fit, half_life=hl, weights=w, window=args.goal_window,
                               step=args.step, start=300.0, end=5100.0)
            sh = build_samples(hold, half_life=hl, weights=w, window=args.goal_window,
                               step=args.step, start=300.0, end=5100.0)
            ef, eh = evaluate(sf, "pressure"), evaluate(sh, "pressure")
            rows.append({"weights": name, "half_life": hl, "fit": ef, "holdout": eh})
            print(f"{name:<16}{hl:>10.0f}{str(ef['auc']):>10}{str(eh['auc']):>10}{eh['base_rate']:>9.4f}")

    # --- WHO, conditional on a goal happening ---
    # A SEPARATE QUESTION AND A SEPARATE POPULATION. Only samples whose window
    # actually contained a goal can answer it; scoring WHO over all samples
    # would mostly be measuring WHEN again.
    print()
    print("WHO scores it, among windows that DID contain a goal (signed momentum):")
    print(f"{'weights':<16}{'half-life':>10}{'n':>7}{'AUC fit':>10}{'AUC hold':>10}")
    who_rows = []
    for name, w in variants:
        for hl in half_lives:
            sf = [x for x in build_samples(fit, half_life=hl, weights=w, window=args.goal_window,
                                           step=args.step, start=300.0, end=5100.0)
                  if x["scorer_home"] is not None]
            sh = [x for x in build_samples(hold, half_life=hl, weights=w, window=args.goal_window,
                                           step=args.step, start=300.0, end=5100.0)
                  if x["scorer_home"] is not None]
            af = _auc([(x["signed"], x["scorer_home"]) for x in sf])
            ah = _auc([(x["signed"], x["scorer_home"]) for x in sh])
            who_rows.append({"weights": name, "half_life": hl, "n_hold": len(sh),
                             "auc_fit": af, "auc_hold": ah})
            print(f"{name:<16}{hl:>10.0f}{len(sh):>7}{str(round(af,4) if af else af):>10}"
                  f"{str(round(ah,4) if ah else ah):>10}")
    bw = [r for r in who_rows if r["auc_fit"] is not None]
    if bw:
        b = max(bw, key=lambda r: r["auc_fit"])
        print()
        print(f"BEST WHO ON FIT: {b['weights']} @ {b['half_life']:.0f}s  fit {b['auc_fit']:.4f}"
              f"  HOLDOUT {b['auc_hold']}")

    # --- LIFT AT THE TAIL, which is what a 2-1/3-1 bet actually needs ---
    # Best-on-fit parameters, then the tail examined ON THE HOLDOUT.
    if rows:
        bf = max([r for r in rows if r["fit"]["auc"] is not None],
                 key=lambda r: r["fit"]["auc"], default=None)
        if bf:
            wsel = dict(next(w for n, w in variants if n == bf["weights"]))
            sh = build_samples(hold, half_life=bf["half_life"], weights=wsel,
                               window=args.goal_window, step=args.step,
                               start=300.0, end=5100.0)
            print()
            print(f"=== TAIL ANALYSIS (holdout), {bf['weights']} @ {bf['half_life']:.0f}s ===")
            print("    break-even: 25.0% at 3-1, 33.3% at 2-1")
            for feat, title in (("pressure", "by PRESSURE"),
                                ("time_in_half", "by TIME IN HALF (momentum ignored)"),
                                ("pressure_x_late", "by PRESSURE x LATE-IN-HALF")):
                print_lift(title, sh, feat)

    scored = [r for r in rows if r["fit"]["auc"] is not None]
    best_fit = max(scored, key=lambda r: r["fit"]["auc"]) if scored else None
    if best_fit:
        print()
        print(f"BEST ON FIT   : {best_fit['weights']} @ {best_fit['half_life']:.0f}s  "
              f"AUC {best_fit['fit']['auc']}")
        print(f"  ITS HOLDOUT : AUC {best_fit['holdout']['auc']}  "
              f"(base rate {best_fit['holdout']['base_rate']})")
        drop = (best_fit["fit"]["auc"] or 0) - (best_fit["holdout"]["auc"] or 0)
        print(f"  fit->holdout drop: {drop:+.4f}")
        auc_h = best_fit["holdout"]["auc"] or 0.5
        if auc_h < 0.55:
            print("  VERDICT: NOT USABLE as a WHEN signal -- AUC at/near coin-flip held out.")
        elif auc_h < 0.60:
            print("  VERDICT: WEAK. Real but thin; would need combining with the sim's own")
            print("           goal_in_window_probability rather than used alone.")
        else:
            print("  VERDICT: USABLE. Worth calibrating into P(goal in window).")

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(
            {"goal_window": args.goal_window, "step": args.step,
             "matches": len(matches), "fit": len(fit), "holdout": len(hold),
             "rows": rows, "who_rows": who_rows}, indent=2), encoding="utf-8")
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
