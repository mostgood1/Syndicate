"""UEFA ratings anchored to past closes: re-run the #699 gate (lane uefa-market-anchored-ratings).

RESEARCH ONLY. Reads `<closes>/features.json` (from `backtest_uefa_vs_close.py run --dump-features`)
and `<closes>/report_close_step3.json` (the published step-3 report, for the self-check); writes
`<closes>/report_anchored.json`. Registration: `.syndicate/findings_2026-10-19_uefa_market_anchored.md` s1.

    python scripts/backtest_uefa_anchored.py --closes C:/tmp/uefa-closes

`--favourite-temper T0,T1 --gap-k K --home-term H` (lane uefa-favourite-temper, registration
`.syndicate/findings_2026-10-19_uefa_favourite_temper.md` s1) replaces `p_model` and `p_anchored` with the
domestic (a2) temperature `temper(p, |g_hat|, T0, T1)`, `g_hat = (log(lam_h/lam_a) - H)/K`, adds the
H-TEMPER gate (tempered-model/close blend) and writes `<closes>/report_favourite_temper.json` instead.
`--print-home-term` prints the registered H (mean log(lam_h/lam_a) over seasons 2020-2022) and exits.

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
from scripts import soccer_team_strength_experiments as tse  # noqa: E402

FIRST_CLOSE_SEASON = 2020
ANCHOR_SEASONS = range(2022, 2027)
GATE_FIRST = 2023
COMPETITIONS = ("ucl", "uel", "uecl")
HOME_TERM_SEASONS = (2020, 2021, 2022)  # registered: the seasons before the first gate season


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


def home_term(rows, seasons=HOME_TERM_SEASONS) -> float:
    """Registered H: unweighted mean of log(lam_h/lam_a) over the rows of `seasons` (rates only)."""
    vals = [np.log(r["lam"][0] / r["lam"][1]) for r in rows if r["season"] in seasons]
    if not vals:
        raise ValueError(f"no rows in seasons {seasons}")
    return float(np.mean(vals))


def tempered(rows, key, t0, t1, k, h):
    """temper(row[key], |g_hat|, t0, t1) per row, g_hat = (log(lam_h/lam_a) - h)/k from the step-3 rates."""
    p = np.array([r[key] for r in rows], dtype=float)
    absg = np.abs((np.log([r["lam"][0] / r["lam"][1] for r in rows]) - h) / k)
    return tse.temper(p, absg, t0, t1)


def _kl(close, p):
    c = np.clip(np.asarray(close, dtype=float), 1e-12, 1.0)
    return float(np.sum(c * (np.log(c) - np.log(np.clip(np.asarray(p, dtype=float), 1e-12, 1.0)))))


def _decile_table(rows, order_key, cols):
    """Favourite deciles: sorted by max(row[order_key]); the favourite is argmax(row[order_key])."""
    fav = sorted(rows, key=lambda r: max(r[order_key]))
    out = []
    for i, chunk in enumerate(np.array_split(np.arange(len(fav)), 10)):
        sub = [fav[k] for k in chunk]
        idx = [int(np.argmax(r[order_key])) for r in sub]
        out.append({"decile": i + 1, "n": len(sub),
                    **{name: float(np.mean([r[key][k] for r, k in zip(sub, idx)])) for name, key in cols},
                    "actual": float(np.mean([1.0 if r["y"] == k else 0.0 for r, k in zip(sub, idx)]))})
    return out


def apply_temper(rows, t0, t1, k, h):
    """Registered H-TEMPER (s1): temper p_model / p_anchored / p_live in place (raw kept as `<key>_raw`),
    then gate the tempered-model/close blend, with the controls and secondary arms beside it."""
    for key in ("p_model", "p_anchored", "p_live"):
        sub = [r for r in rows if key in r]
        if not sub:
            continue
        for r, q in zip(sub, tempered(sub, key, t0, t1, k, h)):
            r[key + "_raw"] = r[key]
            r[key] = [float(x) for x in q]
    for r, q in zip(rows, tempered(rows, "p_model_raw", t0, t1, k, 0.0)):
        r["p_model_h0"] = [float(x) for x in q]

    def gate_arm(model_key):
        w = _blend_weights(rows, model_key, GATE_FIRST)  # history = every earlier season that carries model_key
        bkey = "p_blend__" + model_key
        for r in rows:
            if r["season"] in w and model_key in r:
                r[bkey] = list(ucb.blend(r[model_key], r["p_close"], w[r["season"]]))
        g = [r for r in rows if bkey in r and r["season"] >= GATE_FIRST]
        return {"w": w, **{c: _gate([r for r in g if r["competition"] == c], bkey) for c in COMPETITIONS},
                "pooled": _gate(g, bkey)}

    def ll(r, key):
        return ucb.log_loss(r[key], r["y"])

    def diffs(sub, a, b):
        return ulo.paired_bootstrap_ci([ll(r, a) - (r["ll_close"] if b == "close" else ll(r, b)) for r in sub])

    gate_rows = [r for r in rows if r["season"] >= GATE_FIRST]
    out = {"params": {"t0": t0, "t1": t1, "k": k, "h": h},
           "H_TEMPER": gate_arm("p_model"),
           "control_model_blend": gate_arm("p_model_raw"),
           "sensitivity_h0": gate_arm("p_model_h0")}
    if any("p_anchored" in r for r in rows):
        out["secondary_anchored_tempered"] = gate_arm("p_anchored")
        out["control_anchored_raw"] = gate_arm("p_anchored_raw")
    for label, sub in (("all", rows), ("gate", gate_rows)):
        out[f"tempered_minus_model_{label}"] = diffs(sub, "p_model", "p_model_raw")
        out[f"tempered_minus_close_{label}"] = diffs(sub, "p_model", "close")
        out[f"model_minus_close_{label}"] = diffs(sub, "p_model_raw", "close")
        out[f"kl_close_model_{label}"] = float(np.mean([_kl(r["p_close"], r["p_model_raw"]) for r in sub]))
        out[f"kl_close_tempered_{label}"] = float(np.mean([_kl(r["p_close"], r["p_model"]) for r in sub]))
    out["tempered_minus_model_gate_by_comp"] = {
        c: diffs([r for r in gate_rows if r["competition"] == c], "p_model", "p_model_raw") for c in COMPETITIONS}
    cols = (("close", "p_close"), ("model", "p_model_raw"), ("tempered", "p_model"))
    out["calibration_by_close"] = _decile_table(rows, "p_close", cols)
    out["calibration_by_model"] = _decile_table(rows, "p_model_raw", cols)
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--closes", required=True)
    p.add_argument("--skip-live", action="store_true")
    p.add_argument("--favourite-temper", default=None, help="T0,T1 of the domestic (a2) temperature")
    p.add_argument("--gap-k", type=float, default=None)
    p.add_argument("--home-term", type=float, default=None)
    p.add_argument("--print-home-term", action="store_true")
    argv = list(sys.argv[1:] if argv is None else argv)
    for i, a in enumerate(argv[:-1]):  # "-0.066,0.271" is not a negative number to argparse: bind it
        if a == "--favourite-temper":
            argv[i:i + 2] = [f"{a}={argv[i + 1]}"]
            break
    args = p.parse_args(argv)
    temper_args = None
    if args.favourite_temper is not None:
        if args.gap_k is None or args.home_term is None:
            p.error("--favourite-temper needs --gap-k and --home-term")
        temper_args = (*(float(x) for x in args.favourite_temper.split(",")), args.gap_k, args.home_term)
    closes = Path(args.closes)
    rows = json.loads((closes / "features.json").read_text(encoding="utf-8"))
    if args.print_home_term:
        n = sum(1 for r in rows if r["season"] in HOME_TERM_SEASONS)
        print(f"H_RULE seasons={list(HOME_TERM_SEASONS)} n={n} H={home_term(rows)!r}", flush=True)
        return 0
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

    temper_report = apply_temper(rows, *temper_args) if temper_args else {}
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
    if temper_args:
        report["registration"] = ".syndicate/findings_2026-10-19_uefa_favourite_temper.md s1"
        report["favourite_temper"] = temper_report
        _write_json(closes / "report_favourite_temper.json", report)
        print("TEMPER", json.dumps({k: v for k, v in temper_report.items() if not k.startswith("calibration")}), flush=True)
        for name in ("calibration_by_close", "calibration_by_model"):
            for c in temper_report[name]:
                print(name.upper(), c, flush=True)
    else:
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
