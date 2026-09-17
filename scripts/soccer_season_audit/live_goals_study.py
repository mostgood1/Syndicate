# -*- coding: utf-8 -*-
"""H30, offline: live REMAINING goals -- the production live re-sim vs a pregame market pace, with and without
an update on the shot QUALITY produced so far.

Lane `soccer-live-model-study`, `#664` item 7. The rules are the registration, not this file:
`.syndicate/log/2026-09-17.md` ~14:00 CT. Nothing here changes the engine.

    G0  production live: `project_live_match(state).projected_final_total - goals_so_far`, ratings computed as
        of the match date, default profile, include_stoppage=True, 300 simulations, seed 1
    G1  pregame pace:    T_pre * Sg(t),  T_pre = Poisson mean implied by the de-vigged pregame P(over 2.5)
    G2  shot quality:    Sg(t) * (a * T_pre + Fx(t) * T_obs) / (a + Fx(t)),  T_obs = k * xG_so_far / Fx(t)

Sg(t), Fx(t) and k are ratio-of-sums on TRAIN (before 2026-08-22); `a` comes from the registered grid on
TRAIN. Reported beside the graded arms: the same G2 with SHOTS ON TARGET in place of xG.

    py -3 scripts/soccer_season_audit/live_goals_study.py --heldout <corners_estimators_heldout.csv>
        --fotmob <dir with fotmob_season*.json> --espn-cache %TEMP%/espn_shots_cache
        --source-root <checkout>/data/soccer_source --out <dir> [--shard i/N]
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import math
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHECKOUT = HERE.parents[1]
for p in (str(CHECKOUT), str(CHECKOUT / "scripts"), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

from live_corners_study import A_GRID, CUTOFFS, SEED, SIMULATIONS, TRAIN_END, paired_boot, verdict  # noqa: E402


# ---------------------------------------------------------------------------- arms (pure)

def ratio_share_after(rows: list[dict], field_after: str, field_total: str) -> dict[int, float]:
    """Ratio of sums, per cutoff: sum(after t) / sum(total). Registered for goals and xG because a third of
    matches end 0-0 or 1-0 and a per-match share is undefined or 0/1 noise there."""
    num = collections.defaultdict(float)
    den = collections.defaultdict(float)
    for r in rows:
        num[r["cutoff"]] += r[field_after]
        den[r["cutoff"]] += r[field_total]
    return {t: (num[t] / den[t]) for t in num if den[t] > 0}


def g1(t_pre: float, sg: float) -> float:
    return t_pre * sg


def g2(t_pre: float, observed_so_far: float, sg: float, f_obs: float, k: float, a: float) -> float:
    """`observed_so_far` is xG (graded) or shots on target (reported); k scales it into goals."""
    if f_obs <= 0:
        return g1(t_pre, sg)
    t_obs = k * observed_so_far / f_obs
    return sg * (a * t_pre + f_obs * t_obs) / (a + f_obs)


def pick_a(train: list[dict], sg: dict[int, float], f_obs: dict[int, float], k: float, field: str) -> tuple[float, dict[float, float]]:
    scores = {}
    for a in A_GRID:
        errs = [abs(g2(r["t_pre"], r[field], sg[r["cutoff"]], f_obs[r["cutoff"]], k, a) - (r["final_goals"] - r["goals_so_far"]))
                for r in train]
        scores[a] = sum(errs) / len(errs) if errs else float("nan")
    return min(A_GRID, key=lambda a: scores[a]), scores


# ---------------------------------------------------------------------------- data

def load_population(heldout: Path, fotmob_dir: Path) -> tuple[list[dict], collections.Counter]:
    """Held-out matches with a pregame de-vigged P(over 2.5) and a FotMob shot timeline."""
    from common import find_fixture  # noqa: E402
    funnel = collections.Counter()
    by_lg_date = collections.defaultdict(list)
    seen = set()
    for path in sorted(Path(fotmob_dir).glob("fotmob_season*.json")):
        body = json.loads(path.read_text(encoding="utf-8"))
        matches = body.get("matches") if isinstance(body, dict) else body
        for m in (matches.values() if isinstance(matches, dict) else matches):
            if str(m.get("match_id")) in seen:
                continue
            seen.add(str(m.get("match_id")))
            by_lg_date[(m.get("league"), str(m.get("date"))[:10])].append((m.get("home_team"), m.get("away_team"), m))
    out = []
    with open(heldout, encoding="utf-8") as handle:
        for r in csv.DictReader(handle):
            funnel["heldout_rows"] += 1
            try:
                p_over = float(r["p_over"])
            except (TypeError, ValueError):
                funnel["no_pregame_over25"] += 1
                continue
            if math.isnan(p_over):
                funnel["no_pregame_over25"] += 1
                continue
            date = str(r["date"])[:10]
            fm = find_fixture(r["home"], r["away"], by_lg_date.get((r["lg"], date), []))
            if fm is None or not fm.get("shots"):
                funnel["no_fotmob_join"] += 1
                continue
            funnel["priced_and_joined"] += 1
            out.append({"lg": r["lg"], "date": date, "match_id": str(r["match_id"]), "p_over": p_over,
                        "shots": [(float(s["t"]), float(s.get("xg") or 0.0), bool(s.get("on_target"))) for s in fm["shots"]]})
    return out, funnel


def engine_rows(matches: list[dict], espn_cache: Path, source_root: Path, cache_path: Path) -> tuple[list[dict], collections.Counter]:
    from outcomes import extract  # noqa: E402
    from audit_games import poisson_mean_from_over25  # noqa: E402
    from backtest_soccer_live_totals import _production_ratings  # noqa: E402
    from syndicate.features.soccer.features.live_lens import project_live_match  # noqa: E402
    from syndicate.features.soccer.ingestion.espn_live_state import build_live_state  # noqa: E402

    cached = {}
    for other in sorted(cache_path.parent.glob("live_goals_c0*.json")):
        cached.update(json.loads(other.read_text(encoding="utf-8")))
    funnel = collections.Counter()
    rows = []
    started, dirty = time.time(), 0
    for i, m in enumerate(matches, 1):
        path = espn_cache / f"{m['lg']}_{m['match_id']}.json"
        if not path.exists():
            continue
        summary = json.loads(path.read_text(encoding="utf-8"))
        box = extract(summary)
        if not box["completed"]:
            continue
        funnel["completed"] += 1
        final_state = build_live_state(summary, event_id=m["match_id"])
        pair = _production_ratings(m["lg"], source_root, m["date"], final_state["home_team"], final_state["away_team"])
        if pair is None:
            funnel["no_ratings_as_of"] += 1
            continue
        funnel["population"] += 1
        home_rating, away_rating = pair
        final_goals = float(int(final_state["score_home"]) + int(final_state["score_away"]))
        t_pre = poisson_mean_from_over25(m["p_over"])
        total_xg = sum(x for _, x, _ in m["shots"])
        total_sot = float(sum(1 for _, _, on in m["shots"] if on))
        for cutoff in CUTOFFS:
            key = f"{m['lg']}|{m['match_id']}|{cutoff}"
            state = build_live_state(summary, event_id=m["match_id"], as_of_seconds=cutoff * 60.0)
            goals_so_far = float(int(state["score_home"]) + int(state["score_away"]))
            if key not in cached:
                proj = project_live_match(state, home_rating=home_rating, away_rating=away_rating,
                                          simulations=SIMULATIONS, seed=SEED, include_stoppage=True)
                cached[key] = {"projected_final_total": proj.projected_final_total}
                dirty += 1
            cut = cutoff * 60.0
            rows.append({
                "key": f"{m['lg']}|{m['match_id']}", "lg": m["lg"], "date": m["date"], "cutoff": cutoff,
                "goals_so_far": goals_so_far, "final_goals": final_goals, "t_pre": t_pre,
                "xg_so_far": sum(x for t, x, _ in m["shots"] if t <= cut),
                "sot_so_far": float(sum(1 for t, _, on in m["shots"] if on and t <= cut)),
                "xg_total": total_xg, "sot_total": total_sot,
                "goals_after": final_goals - goals_so_far,
                "xg_after": total_xg - sum(x for t, x, _ in m["shots"] if t <= cut),
                "sot_after": total_sot - float(sum(1 for t, _, on in m["shots"] if on and t <= cut)),
                "g0_remaining": float(cached[key]["projected_final_total"]) - goals_so_far,
            })
        if dirty >= 40:
            cache_path.write_text(json.dumps(cached), encoding="utf-8")
            dirty = 0
        if i % 50 == 0:
            print(f"  {i}/{len(matches)} matches, {time.time() - started:.0f}s, funnel {dict(funnel)}", flush=True)
    cache_path.write_text(json.dumps(cached), encoding="utf-8")
    return rows, funnel


# ---------------------------------------------------------------------------- study

def study(rows: list[dict]) -> dict:
    train = [r for r in rows if r["date"] < TRAIN_END]
    test = [r for r in rows if r["date"] >= TRAIN_END]
    sg = ratio_share_after(train, "goals_after", "final_goals")
    fx = {t: 1.0 - v for t, v in ratio_share_after(train, "xg_after", "xg_total").items()}
    fs = {t: 1.0 - v for t, v in ratio_share_after(train, "sot_after", "sot_total").items()}
    k_xg = sum(r["final_goals"] for r in train) / max(sum(r["xg_total"] for r in train), 1e-9)
    k_sot = sum(r["final_goals"] for r in train) / max(sum(r["sot_total"] for r in train), 1e-9)
    a_xg, a_scores = pick_a(train, sg, fx, k_xg, "xg_so_far")
    a_sot, _ = pick_a(train, sg, fs, k_sot, "sot_so_far")
    for r in test:
        target = r["final_goals"] - r["goals_so_far"]
        t = r["cutoff"]
        r["err_g0"] = r["g0_remaining"] - target
        r["err_g1"] = g1(r["t_pre"], sg[t]) - target
        r["err_g2"] = g2(r["t_pre"], r["xg_so_far"], sg[t], fx[t], k_xg, a_xg) - target
        r["err_g2sot"] = g2(r["t_pre"], r["sot_so_far"], sg[t], fs[t], k_sot, a_sot) - target

    def mae(rs, f):
        return sum(abs(x[f]) for x in rs) / len(rs) if rs else float("nan")

    def bias(rs, f):
        return sum(x[f] for x in rs) / len(rs) if rs else float("nan")

    fields = ("err_g0", "err_g1", "err_g2", "err_g2sot")
    out = {
        "train_matches": len({r["key"] for r in train}), "test_matches": len({r["key"] for r in test}),
        "Sg": sg, "Fx": fx, "Fs": fs, "k_xg": k_xg, "k_sot": k_sot, "a_xg": a_xg, "a_sot": a_sot, "a_train_mae": a_scores,
        "test_pooled": {f: {"mae": mae(test, f), "bias": bias(test, f)} for f in fields},
        "per_cutoff": {t: {f: mae([r for r in test if r["cutoff"] == t], f) for f in fields} for t in CUTOFFS},
        "per_league": {lg: {"matches": len({r["key"] for r in test if r["lg"] == lg}),
                            **{f: mae([r for r in test if r["lg"] == lg], f) for f in fields}}
                       for lg in sorted({r["lg"] for r in test})},
        "g2_vs_g0": paired_boot(test, "err_g2", "err_g0"),
        "g2_vs_g1": paired_boot(test, "err_g2", "err_g1"),
        "g1_vs_g0": paired_boot(test, "err_g1", "err_g0"),
        "g2sot_vs_g0": paired_boot(test, "err_g2sot", "err_g0"),
    }
    out["verdict"] = verdict(out["g2_vs_g0"], out["g2_vs_g1"][0])
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--heldout", required=True)
    ap.add_argument("--fotmob", required=True)
    ap.add_argument("--espn-cache", required=True)
    ap.add_argument("--source-root", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--shard", default=None, help="i/N: fill the G0 cache for every N-th match only (no verdict)")
    args = ap.parse_args(argv)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    matches, funnel = load_population(Path(args.heldout), Path(args.fotmob))
    matches.sort(key=lambda m: (m["date"], m["lg"], m["match_id"]))
    cache_name = "live_goals_c0.json"
    if args.shard:
        i, n = (int(x) for x in args.shard.split("/"))
        matches = [m for k, m in enumerate(matches) if k % n == i]
        cache_name = f"live_goals_c0.shard{i}of{n}.json"
    rows, engine_funnel = engine_rows(matches, Path(args.espn_cache), Path(args.source_root), out_dir / cache_name)
    print("join funnel", dict(funnel), "| engine funnel", dict(engine_funnel), "rows", len(rows))
    if args.shard:
        print("SHARD RUN: no verdict")
        return 0
    res = study(rows)
    res["funnel"] = {**dict(funnel), **dict(engine_funnel)}
    (out_dir / "live_goals_study.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    print(f"TRAIN {res['train_matches']} matches  TEST {res['test_matches']}  Sg {{{', '.join(f'{t}: {v:.3f}' for t, v in sorted(res['Sg'].items()))}}}  "
          f"k_xg {res['k_xg']:.3f}  a_xg {res['a_xg']}  a_sot {res['a_sot']}")
    print("TEST pooled MAE / bias: " + " | ".join(f"{f[4:].upper()} {v['mae']:.3f} / {v['bias']:+.3f}" for f, v in res["test_pooled"].items()))
    for t, v in res["per_cutoff"].items():
        print(f"  {t:>2}'  G0 {v['err_g0']:.3f}  G1 {v['err_g1']:.3f}  G2 {v['err_g2']:.3f}  G2sot {v['err_g2sot']:.3f}")
    for name in ("g2_vs_g0", "g2_vs_g1", "g1_vs_g0", "g2sot_vs_g0"):
        p, (lo, hi), k = res[name]
        print(f"  {name}: mean |err| diff {p:+.4f} [{lo:+.4f}, {hi:+.4f}] over {k} matches")
    for lg, v in res["per_league"].items():
        print(f"  {lg:16s} n{v['matches']:4d}  G0 {v['err_g0']:.3f}  G1 {v['err_g1']:.3f}  G2 {v['err_g2']:.3f}")
    print("H30:", res["verdict"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
