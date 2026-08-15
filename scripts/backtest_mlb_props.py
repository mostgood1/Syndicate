"""Backtest: do the MLB player-prop projections predict anything? (`#428`)

Second target after WNBA game lines. `prop_projections` is the model behind the
board's hitter props, and `#425` gap 1 has it reporting `unmeasured`.

WHAT IT MEASURES. `daily_summary_<date>.json` carries, per player per date, a
mean for each hitter market:

    h_mean -> hits          tb_mean  -> totalBases    rbi_mean -> rbi
    r_mean -> runs          2b_mean  -> doubles       3b_mean  -> triples
    sb_mean -> stolenBases  hrr_mean -> hits+runs+rbi

Each is compared against the real box score and reported **against a constant
baseline** -- the sample's own mean for that stat. The baseline is the finding,
not decoration: a prop model that cannot beat "always predict this player pool's
average" has no value however well it correlates. `#367` measured NFL's totals
at r=0.269 beating the mean by only 0.22 MAE, which a bare correlation would
have dressed up as skill.

THE JOIN IS EXACT AND THAT IS WHY THIS IS WORTH DOING. `batter_id` in the
artifact IS the MLB StatsAPI person id -- verified before this file was written
(54 of 66 box-score batters matched from three games). So the whole class of
name-matching failure that `#218` records for teams does not apply here.

TWO HONESTY RULES THIS FILE EXISTS TO ENFORCE, both learned the hard way today:

  1. PER-MARKET DENOMINATORS. A player-date row is not a data point for a market
     whose mean was never written. `hrr_mean` was 0.0 for every player until
     2026-08-14 (`#429`), and `sb_mean` looks similar. The WNBA harness gated on
     the JOIN count and reported statistics over a tenth as many rows; this
     gates and reports per market.
  2. EXCLUDE PLAYERS WHO DID NOT BAT. A projection for someone who never
     appeared is not a wrong prediction, it is an unplayed one. Including DNPs
     drags every actual toward zero and makes any model look terrible. Rows with
     0 plate appearances are dropped AND COUNTED.

Outcomes come from MLB StatsAPI's boxscore endpoint (small, per game) rather
than `feed/live` (megabytes per game).

Usage:
  py -3 scripts/backtest_mlb_props.py --limit 10
  py -3 scripts/backtest_mlb_props.py --limit 40 --min-games 200
"""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import date as date_cls, datetime, timedelta, timezone
from pathlib import Path
from statistics import fmean
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
BASE = "https://syndicate-an21.onrender.com"
STATSAPI = "https://statsapi.mlb.com/api/v1"

# artifact mean field -> box-score stat key. `hrr` is computed, not a stat.
MARKETS: dict[str, str] = {
    "h_mean": "hits",
    "tb_mean": "totalBases",
    "rbi_mean": "rbi",
    "r_mean": "runs",
    "2b_mean": "doubles",
    "3b_mean": "triples",
    "sb_mean": "stolenBases",
    "hrr_mean": "__hrr__",
}


def _admin_token() -> str:
    for line in (REPO_ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("ADMIN_TOKEN="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("ADMIN_TOKEN not found in .env")


def _get(url: str, headers: dict | None = None, timeout: int = 120) -> bytes:
    return urllib.request.urlopen(
        urllib.request.Request(url, headers=headers or {}), timeout=timeout).read()


def projections_for(date: str, token: str, cache: Path) -> dict[int, dict]:
    """batter_id -> {mean_key: value}, from PRODUCTION."""
    cached = cache / f"summary_{date}.json"
    if cached.is_file():
        raw = cached.read_bytes()
    else:
        path = f"mlb_source/source_artifacts/data/daily/daily_summary_{date.replace('-', '_')}.json"
        try:
            raw = _get(f"{BASE}/api/ops/artifacts/stream?path={urllib.parse.quote(path)}",
                       headers={"X-Admin-Token": token})
        except Exception:
            return {}
        cache.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(raw)

    try:
        payload = json.loads(raw.decode("utf-8", errors="replace"))
    except Exception:
        return {}

    out: dict[int, dict] = {}
    for game in payload.get("outputs") or []:
        for _bucket, rows in ((game or {}).get("hitter_props_likelihood_topn") or {}).items():
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                pid = row.get("batter_id")
                if pid is None:
                    continue
                slot = out.setdefault(int(pid), {})
                for key, value in row.items():
                    if isinstance(key, str) and key.endswith("_mean") and isinstance(value, (int, float)):
                        slot[key] = float(value)
    return out


def actuals_for(date: str, cache: Path) -> dict[int, dict]:
    """batter_id -> box-score batting line, for every player who batted."""
    cached = cache / f"box_{date}.json"
    if cached.is_file():
        return {int(k): v for k, v in json.loads(cached.read_text(encoding="utf-8")).items()}

    try:
        sched = json.loads(_get(f"{STATSAPI}/schedule?sportId=1&date={date}", timeout=30))
    except Exception:
        return {}
    pks = [g.get("gamePk") for d in sched.get("dates") or [] for g in d.get("games") or []]

    out: dict[int, dict] = {}
    for pk in pks:
        try:
            box = json.loads(_get(f"{STATSAPI}/game/{pk}/boxscore", timeout=30))
        except Exception:
            continue
        for side in ("away", "home"):
            players = ((box.get("teams") or {}).get(side) or {}).get("players") or {}
            for player in players.values():
                batting = (player.get("stats") or {}).get("batting") or {}
                if not batting:
                    continue
                pid = (player.get("person") or {}).get("id")
                if pid is None:
                    continue
                out[int(pid)] = batting
        time.sleep(0.05)

    cache.mkdir(parents=True, exist_ok=True)
    cached.write_text(json.dumps({str(k): v for k, v in out.items()}), encoding="utf-8")
    return out


def corr(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3:
        return None
    mx, my = fmean(xs), fmean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = sum((x - mx) ** 2 for x in xs) ** 0.5
    dy = sum((y - my) ** 2 for y in ys) ** 0.5
    return round(num / (dx * dy), 4) if dx and dy else None


def mae(pred: list[float], actual: list[float]) -> float:
    return round(fmean(abs(p - a) for p, a in zip(pred, actual)), 4)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=14, help="how many recent dates")
    parser.add_argument("--end", default="", help="last date (YYYY-MM-DD), default today")
    parser.add_argument("--min-games", type=int, default=100,
                        help="per-MARKET minimum before a skill number is emitted")
    # D4. The out-of-sample split is ALWAYS attempted -- there is no flag to
    # turn it off, because the in-sample number is the one that gets published
    # by accident and an opt-in check is a check nobody runs. This only sets how
    # many dates each half needs before the split is worth reporting.
    parser.add_argument("--min-holdout-dates", type=int, default=3,
                        help="minimum dates per half before an out-of-sample number is emitted")
    args = parser.parse_args()

    token = _admin_token()
    cache = Path(os.environ.get("TEMP", "/tmp")) / "mlb_props_backtest_cache"
    end = date_cls.fromisoformat(args.end) if args.end else date_cls.today()
    dates = [(end - timedelta(days=i)).isoformat() for i in range(args.limit)]

    pairs: list[tuple[dict, dict, str]] = []
    no_proj, no_box, dnp = [], [], 0
    for i, day in enumerate(dates, 1):
        proj = projections_for(day, token, cache)
        if not proj:
            no_proj.append(day)
            continue
        act = actuals_for(day, cache)
        if not act:
            no_box.append(day)
            continue
        for pid, means in proj.items():
            batting = act.get(pid)
            if batting is None:
                continue
            # A projection for someone who never batted is an UNPLAYED
            # prediction, not a wrong one. Including DNPs drags every actual to
            # zero and makes any model look terrible.
            if int(batting.get("plateAppearances") or 0) <= 0:
                dnp += 1
                continue
            pairs.append((means, batting, day))
        print(f"  ...{i}/{len(dates)} dates, {len(pairs)} player-games")

    print("\nCOVERAGE")
    print(f"  dates sampled                 : {len(dates)}")
    print(f"  dates with no projection      : {len(no_proj)}")
    print(f"  dates with no box score       : {len(no_box)}")
    print(f"  player-games joined           : {len(pairs)}")
    print(f"  excluded, did not bat (0 PA)  : {dnp}")

    if not pairs:
        print("\nNothing joined. Nothing to measure.")
        return 1

    print("\nPER-MARKET (a market whose mean was never written is NOT measurable,")
    print("no matter how many player-games joined -- see #429's hrr_mean)")
    header = (f"  {'market':10s} {'n':>5s} {'corr':>8s} {'MAE model':>10s} {'MAE base':>9s} "
              f"{'MAE debias':>10s} {'bias':>8s} {'infl':>7s} {'verdict'}")
    print(header)
    print("  " + "-" * (len(header) - 2))

    results = {"sport": "mlb", "scope": "hitter props",
               "generated_at": datetime.now(timezone.utc).isoformat(),
               "dates": f"{dates[-1]}..{dates[0]}", "player_games": len(pairs),
               "markets": {}}

    for mean_key, stat_key in MARKETS.items():
        pred, act_vals, pair_dates = [], [], []
        for means, batting, pair_day in pairs:
            value = means.get(mean_key)
            if value is None:
                continue
            if stat_key == "__hrr__":
                actual = (int(batting.get("hits") or 0)
                          + int(batting.get("runs") or 0)
                          + int(batting.get("rbi") or 0))
            else:
                actual = batting.get(stat_key)
                if actual is None:
                    continue
                actual = int(actual)
            pred.append(float(value))
            act_vals.append(float(actual))
            pair_dates.append(pair_day)

        label = mean_key.replace("_mean", "")
        if len(pred) < args.min_games:
            print(f"  {label:10s} {len(pred):5d} {'-':>8s} {'-':>10s} {'-':>9s} "
                  f"below --min-games {args.min_games}, no number emitted")
            results["markets"][label] = {"n": len(pred), "verdict": "not measurable (sample too small)"}
            continue
        if len(set(pred)) == 1:
            print(f"  {label:10s} {len(pred):5d} {'-':>8s} {'-':>10s} {'-':>9s} "
                  f"CONSTANT {pred[0]} -- degenerate, not a projection")
            results["markets"][label] = {"n": len(pred), "constant_value": pred[0],
                                         "verdict": "degenerate constant, not measurable"}
            continue

        baseline = fmean(act_vals)
        m_model = mae(pred, act_vals)
        m_base = mae([baseline] * len(act_vals), act_vals)
        c = corr(pred, act_vals)
        beats = m_model < m_base

        # LEVEL BIAS vs NO SIGNAL -- these are different findings with different
        # fixes, and MAE alone cannot tell them apart. A model can be correctly
        # SHAPED (positive correlation) and still lose to a constant purely by
        # sitting at the wrong level. `#367` found exactly that on NFL totals
        # (+5.6 bias) and the fix was `calibrated_total`, not a new model.
        #
        # So: subtract the mean error and re-score. If the de-biased MAE beats
        # the baseline, the signal is real and the model needs CALIBRATION. If
        # it still loses, there is genuinely nothing there.
        bias = fmean(p - a for p, a in zip(pred, act_vals))
        m_debiased = mae([p - bias for p in pred], act_vals)
        debiased_beats = m_debiased < m_base

        # D4. THE ABOVE IS IN-SAMPLE AND MUST NOT BE PUBLISHED AS A RESULT.
        #
        # `bias` is estimated from the same player-games it is then used to
        # correct, and `baseline` is the mean of the same actuals it is scored
        # against. Both leak, so "de-biased beats the baseline" is a statement
        # about a fit, not a prediction. The soccer lane retired an entire
        # validation set for exactly this shape (`D1`), and the difference here
        # is only one of degree.
        #
        # So: fit the correction on the EARLIER dates and score it on the LATER
        # ones. `dates` is built newest-first, so the fit half is the TAIL.
        # Temporal order matters -- fitting on the later half and scoring the
        # earlier one would be a lookahead, which is the defect being fixed, not
        # a symmetric alternative.
        #
        # BOTH numbers are reported. The in-sample one is not deleted, because a
        # reader comparing them learns how much of the de-biasing was real; a
        # reader shown only one number learns nothing about the gap.
        oos: dict[str, Any] = {"available": False, "reason": None}
        ordered_dates = sorted(set(pair_dates))
        if len(ordered_dates) < 2 * args.min_holdout_dates:
            oos["reason"] = (f"needs >= {2 * args.min_holdout_dates} distinct dates, "
                             f"have {len(ordered_dates)}")
        else:
            cut = len(ordered_dates) // 2
            fit_dates = set(ordered_dates[:cut])       # earlier
            score_dates = set(ordered_dates[cut:])     # later
            fit_idx = [i for i, d in enumerate(pair_dates) if d in fit_dates]
            score_idx = [i for i, d in enumerate(pair_dates) if d in score_dates]
            if len(fit_idx) < args.min_games or len(score_idx) < args.min_games:
                oos["reason"] = (f"split leaves {len(fit_idx)}/{len(score_idx)} player-games, "
                                 f"below --min-games {args.min_games}")
            else:
                # Everything the correction knows comes from the fit half only.
                fit_bias = fmean(pred[i] - act_vals[i] for i in fit_idx)
                fit_baseline = fmean(act_vals[i] for i in fit_idx)
                s_pred = [pred[i] for i in score_idx]
                s_act = [act_vals[i] for i in score_idx]
                oos_model = mae(s_pred, s_act)
                oos_base = mae([fit_baseline] * len(s_act), s_act)
                oos_debiased = mae([p - fit_bias for p in s_pred], s_act)
                oos = {
                    "available": True, "reason": None,
                    "fit_dates": f"{ordered_dates[0]}..{ordered_dates[cut - 1]}",
                    "score_dates": f"{ordered_dates[cut]}..{ordered_dates[-1]}",
                    "n_fit": len(fit_idx), "n_score": len(score_idx),
                    "bias_fit_on_earlier": round(fit_bias, 4),
                    "mae_model": oos_model,
                    "mae_constant_baseline": oos_base,
                    "mae_debiased": oos_debiased,
                    "debiased_beats_baseline": oos_debiased < oos_base,
                    "correlation": corr(s_pred, s_act),
                }

        if beats:
            verdict = f"beats baseline by {round(m_base - m_model, 4)}"
        elif debiased_beats:
            verdict = (f"BIASED, NOT BLIND -- de-biased beats baseline by "
                       f"{round(m_base - m_debiased, 4)} (bias {bias:+.4f})")
        else:
            verdict = "NO measured skill"

        # Is the inflation UNIFORM across markets? If every counting stat is
        # over-predicted by roughly the same PERCENTAGE, that is one upstream
        # cause (over-estimated playing time inflates every counting stat
        # proportionally), not eight independent model faults -- and one fix.
        inflation = round(100.0 * bias / baseline, 1) if baseline else None
        print(f"  {label:10s} {len(pred):5d} {str(c):>8s} {m_model:>10.4f} {m_base:>9.4f} "
              f"{m_debiased:>10.4f} {bias:>+8.4f} {str(inflation) + '%':>7s} {verdict}")
        results["markets"][label] = {
            "n": len(pred), "correlation": c, "mae_model": m_model,
            "mae_constant_baseline": m_base, "mae_debiased": m_debiased,
            "mean_bias": round(bias, 4), "baseline_value": round(baseline, 4),
            "beats_constant_baseline": beats,
            "debiased_beats_baseline": debiased_beats,
            "inflation_pct_of_baseline": inflation, "verdict": verdict,
            # Explicit, so no consumer can mistake the block above for a
            # prediction. Everything outside `out_of_sample` is a FIT.
            "validation": "in_sample",
            "out_of_sample": oos,
        }
        if oos.get("available"):
            print(f"  {'':10s} {oos['n_score']:5d} {str(oos['correlation']):>8s} "
                  f"{oos['mae_model']:>10.4f} {oos['mae_constant_baseline']:>9.4f} "
                  f"{oos['mae_debiased']:>10.4f} {'':>8s} {'':>7s} "
                  f"OUT-OF-SAMPLE (fit {oos['fit_dates']}, scored {oos['score_dates']})"
                  f" -- de-biased {'BEATS' if oos['debiased_beats_baseline'] else 'LOSES TO'} baseline")
        else:
            print(f"  {'':10s} {'':5s} {'':>8s} {'':>10s} {'':>9s} {'':>10s} "
                  f"{'':>8s} {'':>7s} out-of-sample NOT COMPUTED: {oos['reason']}")

    print("\n" + "=" * 72)
    print("MEASURED_SKILL block:")
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
