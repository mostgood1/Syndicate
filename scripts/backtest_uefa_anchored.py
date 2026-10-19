"""UEFA ratings anchored to past closes: re-run the #699 gate (lane uefa-market-anchored-ratings).

RESEARCH ONLY. Reads `<closes>/features.json` (from `backtest_uefa_vs_close.py run --dump-features`)
and `<closes>/report_close_step3.json` (the published step-3 report, for the self-check); writes
`<closes>/report_anchored.json`. Registration: `.syndicate/findings_2026-10-19_uefa_market_anchored.md` s1.

    python scripts/backtest_uefa_anchored.py --closes C:/tmp/uefa-closes

Run at Idle / `nice -n 19`.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from syndicate.features.soccer import uefa_close_backtest as ucb  # noqa: E402
from syndicate.features.soccer import uefa_league_offsets as ulo  # noqa: E402
from syndicate.features.soccer import uefa_market_anchor as uma  # noqa: E402

FIRST_CLOSE_SEASON = 2020
ANCHOR_SEASONS = range(2022, 2027)
GATE_FIRST = 2023
COMPETITIONS = ("ucl", "uel", "uecl")


def _write_json(path: Path, payload) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8")
    os.replace(tmp, path)


def _am(r) -> uma.AnchorMatch:
    return uma.AnchorMatch(r["home_id"], r["away_id"], float(r["lam"][0]), float(r["lam"][1]),
                           tuple(r["p_close"]), int(r["y"]))


def _blend_weights(rows, key, first):
    """{season: w} fit on held-out `key` predictions of earlier seasons (registered rule)."""
    out = {}
    for s in sorted({r["season"] for r in rows}):
        if s < first:
            continue
        hist = [(r[key], r["p_close"], r["y"]) for r in rows if key in r and r["season"] < s]
        out[s] = ucb.choose_weight(hist)
    return out


def _gate(sub, key):
    d = ulo.paired_bootstrap_ci([ucb.log_loss(r[key], r["y"]) - r["ll_close"] for r in sub])
    v = "NO-GO / FALSIFIED" if d[0] >= 0 else ("GO" if d[2] < 0 else "NO-GO / NOT DEMONSTRATED")
    return {"n": len(sub), "d_vs_close": d, "verdict": v}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--closes", required=True)
    p.add_argument("--skip-live", action="store_true")
    args = p.parse_args(argv)
    closes = Path(args.closes)
    rows = json.loads((closes / "features.json").read_text(encoding="utf-8"))
    step3 = {r["event_id"]: r for r in json.loads((closes / "report_close_step3.json").read_text(encoding="utf-8"))["rows"]}
    # Registered self-check: the dump must reproduce step 3's model exactly.
    worst = max(abs(r["ll_model"] - step3[r["event_id"]]["ll_model"]) for r in rows)
    lam_check = max(abs(ucb.log_loss(uma.probs_from_rates(*r["lam"]), r["y"]) - r["ll_model"]) for r in rows)
    print(f"SELF_CHECK rows={len(rows)} step3={len(step3)} max|ll_model diff|={worst:.2e} max|lam->probs diff|={lam_check:.2e}", flush=True)
    if len(rows) != len(step3) or worst > 1e-9 or lam_check > 1e-9:
        print("ABORT: the dump does not reproduce step 3", flush=True)
        return 2
    report = {"registration": ".syndicate/findings_2026-10-19_uefa_market_anchored.md s1", "rows": len(rows),
              "self_check": {"max_ll_model_diff": worst, "max_lam_probs_diff": lam_check}}

    taus, tau_scores = {}, {}
    for s in ANCHOR_SEASONS:
        train = [r for r in rows if FIRST_CLOSE_SEASON <= r["season"] < s]
        inner_train = [r for r in train if r["season"] < s - 1]
        inner_val = [r for r in train if r["season"] == s - 1]
        w_in = uma.recency_weights([r["day"] for r in inner_train], f"{s - 1}-07-01")
        taus[s], tau_scores[s] = uma.select_tau([_am(r) for r in inner_train], w_in, [_am(r) for r in inner_val])
        fit = uma.fit_anchor([_am(r) for r in train], tau=taus[s],
                             weights=uma.recency_weights([r["day"] for r in train], f"{s}-07-01"))
        test = [r for r in rows if r["season"] == s]
        for r in test:
            r["p_anchored"] = list(fit.probs(_am(r)))
        big = sorted(fit.corrections.items(), key=lambda kv: -abs(kv[1][0]) - abs(kv[1][1]))[:5]
        print(f"FROZEN season={s} train={len(train)} test={len(test)} tau={taus[s]:g} largest={[(c, round(a, 3), round(d, 3)) for c, (a, d) in big]}", flush=True)

    if not args.skip_live:
        by_day = defaultdict(list)
        for r in rows:
            if r["season"] in ANCHOR_SEASONS:
                by_day[r["day"]].append(r)
        for i, day in enumerate(sorted(by_day)):
            train = [r for r in rows if r["day"] < day and r["season"] >= FIRST_CLOSE_SEASON]
            s = by_day[day][0]["season"]
            fit = uma.fit_anchor([_am(r) for r in train], tau=taus[s],
                                 weights=uma.recency_weights([r["day"] for r in train], day))
            for r in by_day[day]:
                r["p_live"] = list(fit.probs(_am(r)))
            if i % 25 == 0:
                print(f"LIVE {i + 1}/{len(by_day)} day={day} train={len(train)}", flush=True)

    weights_a = _blend_weights(rows, "p_anchored", GATE_FIRST)
    weights_l = _blend_weights(rows, "p_live", GATE_FIRST) if not args.skip_live else {}
    for r in rows:
        if r["season"] in weights_a:
            r["p_blend_a"] = list(ucb.blend(r["p_anchored"], r["p_close"], weights_a[r["season"]]))
        if r["season"] in weights_l and "p_live" in r:
            r["p_blend_l"] = list(ucb.blend(r["p_live"], r["p_close"], weights_l[r["season"]]))
    gate_rows = [r for r in rows if "p_blend_a" in r]
    verdicts = {c: _gate([r for r in gate_rows if r["competition"] == c], "p_blend_a") for c in COMPETITIONS}
    verdicts["pooled"] = _gate(gate_rows, "p_blend_a")
    live_rows = [r for r in rows if "p_blend_l" in r]
    live_verdicts = ({c: _gate([r for r in live_rows if r["competition"] == c], "p_blend_l") for c in COMPETITIONS}
                     | {"pooled": _gate(live_rows, "p_blend_l")}) if live_rows else {}

    anch = [r for r in rows if "p_anchored" in r]

    def ci(diffs):
        return ulo.paired_bootstrap_ci(diffs)

    def ll(r, k):
        return ucb.log_loss(r[k], r["y"])

    secondary = {
        "n_anchored": len(anch),
        "log_loss": {k: float(np.mean([ll(r, k) for r in anch if k in r])) for k in ("p_model", "p_anchored", "p_close", "p_live") if any(k in r for r in anch)},
        "anchored_minus_model": ci([ll(r, "p_anchored") - ll(r, "p_model") for r in anch]),
        "anchored_minus_close": ci([ll(r, "p_anchored") - r["ll_close"] for r in anch]),
        "live_minus_close": ci([ll(r, "p_live") - r["ll_close"] for r in anch if "p_live" in r]),
        "anchored_minus_model_in_in": ci([ll(r, "p_anchored") - ll(r, "p_model") for r in anch if r["pair"] == "in_in"]),
        "anchored_minus_model_with_oos": ci([ll(r, "p_anchored") - ll(r, "p_model") for r in anch if r["pair"] != "in_in"]),
        "per_season": {s: {"n": sum(1 for r in anch if r["season"] == s), "tau": taus.get(s), "w_a": weights_a.get(s), "w_l": weights_l.get(s),
                           "anchored_minus_close": ci([ll(r, "p_anchored") - r["ll_close"] for r in anch if r["season"] == s])}
                       for s in ANCHOR_SEASONS},
    }
    calib = []
    fav = sorted(anch, key=lambda r: max(r["p_close"]))
    for i, chunk in enumerate(np.array_split(np.arange(len(fav)), 10)):
        sub = [fav[k] for k in chunk]
        idx = [int(np.argmax(r["p_close"])) for r in sub]
        calib.append({"decile": i + 1, "n": len(sub),
                      **{name: float(np.mean([r[key][k] for r, k in zip(sub, idx)])) for name, key in
                         (("close", "p_close"), ("model", "p_model"), ("anchored", "p_anchored"))},
                      "actual": float(np.mean([1.0 if r["y"] == k else 0.0 for r, k in zip(sub, idx)]))})
    report.update({"taus": taus, "tau_scores": tau_scores, "blend_w_anchored": weights_a, "blend_w_live": weights_l,
                   "H_ANCHOR": verdicts, "live_secondary_gate": live_verdicts, "secondary": secondary, "calibration": calib})
    _write_json(closes / "report_anchored.json", report)
    print("H_ANCHOR", json.dumps(verdicts), flush=True)
    print("LIVE_GATE", json.dumps(live_verdicts), flush=True)
    print("SECONDARY", json.dumps({k: v for k, v in secondary.items() if k != "per_season"}), flush=True)
    print("PER_SEASON", json.dumps(secondary["per_season"]), flush=True)
    for c in calib:
        print("CALIB", c, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
