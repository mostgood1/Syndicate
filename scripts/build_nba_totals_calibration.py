"""Write `calibration_totals_<anchor>.json` for the NBA smart sim's game-total model.

WHY THIS EXISTS (lane `basketball-scenario-calibration`, Phase 2 #1e). `basketball_props_smart_sim.
_apply_totals_calibration_local` reads `calibration_totals_*.json` from the NBA processed root (a global game-total
bias, clamped +/-15, and per-team terms, clamped +/-4) and NOTHING wrote one for NBA -- 0 files on the fleet
2026-10-09. The NBA raw game total (ratings x pace in `_simulate_quarters_local`) ran 15.3 below the market on 87
2025-26 FIT games (215.40 vs 230.70; the market itself unbiased vs real, -0.07), so the market-anchored target
(total weight 0.7) sat ~4.5 low. The engine's old +5.7 overshoot of its own target hid that; with
EXACT_TARGET_CALIBRATION the sim lands on the low target.

WHAT IT COMPUTES. The WNBA recipe (`build_wnba_totals_calibration.calibration_terms`, unchanged): winsorized
mean(actual - raw total) over the last 14 days (season-to-date under 8 games), clipped +/-15; team terms =
residual sum / (n + 20), clipped +/-4. Unlike WNBA, the raw total is not re-predicted here: it is read from NBA's
own per-game `smart_sim_<date>_<HOME>_<AWAY>.json` (`market_anchor.model_total_raw`), with the terms of whatever
calibration file was in effect that day backed out so the fit always sees the UNcalibrated model. Actuals come
from `recon_games_<date>.csv` (final scores, written by the NBA refresh). Regular-season dates only
(nba_season_phase): preseason sims never feed it. With fewer than 8 regular-season games it writes the SEED terms
(a global bias only), labelled `window: seed`.

The anchor is `--date` minus one day: the reader takes the newest file dated on or before the day before the
slate, so a missed run falls back to the previous file.

Usage: python scripts/build_nba_totals_calibration.py --date 2026-10-21 --processed-root <nba_source>/data/processed [--force]
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
GLOBAL_CLIP = 15.0
TEAM_CLIP = 4.0
# Opening-night seed: global bias only (team terms do not carry across seasons). Set from the 2025-26 FIT-window
# fit (final 14 days) once measured -- None means "no seed": write nothing until 8 regular-season games exist.
SEED_GAME_TOTAL_BIAS: Optional[float] = None
SEED_SOURCE = "unset"


def _clamp(v: Any, lo: float, hi: float) -> float:
    try:
        return float(max(lo, min(hi, float(v))))
    except (TypeError, ValueError):
        return 0.0


def calibration_terms(games, *, slate_date) -> dict:
    """The WNBA recipe, unchanged (one source)."""
    if str(REPO_ROOT / "scripts") not in sys.path:
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from build_wnba_totals_calibration import calibration_terms as _terms

    out = _terms(games, slate_date=slate_date)
    if out:
        out["meta"]["source"] = "scripts/build_nba_totals_calibration.py (recipe: build_wnba_totals_calibration)"
    return out


def applied_shift(cal: Optional[dict], home: str, away: str) -> tuple:
    """(total shift, margin shift) the reader applied for these teams under calibration file `cal`."""
    if not isinstance(cal, dict):
        return 0.0, 0.0
    team = cal.get("team") if isinstance(cal.get("team"), dict) else {}
    th = _clamp(team.get(home, 0.0), -TEAM_CLIP, TEAM_CLIP) if home in team else 0.0
    ta = _clamp(team.get(away, 0.0), -TEAM_CLIP, TEAM_CLIP) if away in team else 0.0
    g = cal.get("global") if isinstance(cal.get("global"), dict) else {}
    gb = _clamp(_clamp(g.get("game_total_bias", 0.0), -GLOBAL_CLIP, GLOBAL_CLIP)
                + _clamp(g.get("sim_game_total_bias", 0.0), -GLOBAL_CLIP, GLOBAL_CLIP), -GLOBAL_CLIP, GLOBAL_CLIP)
    return th + ta + gb, th - ta


def games_frame(records: Iterable[Dict[str, Any]], actuals: Dict[tuple, tuple], cal_for_date) -> "Any":
    """records: {date, home, away, model_total_raw, model_margin_raw}; actuals: {(date, home, away): (home_pts, away_pts)};
    cal_for_date(date) -> the calibration dict that was in effect that day (or None). Pure apart from cal_for_date."""
    import pandas as pd

    rows = []
    for r in records:
        k = (str(r["date"])[:10], str(r["home"]).upper(), str(r["away"]).upper())
        if k not in actuals or r.get("model_total_raw") is None:
            continue
        tshift, mshift = applied_shift(cal_for_date(k[0]), k[1], k[2])
        hp, ap = actuals[k]
        rows.append({"date": k[0], "home_team": k[1], "visitor_team": k[2], "home_pts": float(hp), "visitor_pts": float(ap),
                     "pred_total": float(r["model_total_raw"]) - tshift,
                     "pred_margin": float(r.get("model_margin_raw") or 0.0) - mshift})
    return pd.DataFrame(rows, columns=["date", "home_team", "visitor_team", "home_pts", "visitor_pts", "pred_total", "pred_margin"])


def _calibration_index(processed_root: Path) -> List[tuple]:
    out = []
    for f in processed_root.glob("calibration_totals_*.json"):
        ds = f.name[len("calibration_totals_"):-len(".json")]
        if len(ds) == 10 and ds[4] == "-" and ds[7] == "-":
            out.append((ds, f))
    return sorted(out)


def cal_lookup(processed_root: Path):
    """The reader's rule: newest file dated <= day - 1."""
    import pandas as pd

    idx = _calibration_index(processed_root)
    cache: Dict[str, Optional[dict]] = {}

    def get(day: str) -> Optional[dict]:
        if day in cache:
            return cache[day]
        cutoff = (pd.Timestamp(day) - pd.Timedelta(days=1)).date().isoformat()
        best = None
        for ds, f in idx:
            if ds <= cutoff:
                best = f
            else:
                break
        try:
            cache[day] = json.loads(best.read_text(encoding="utf-8")) if best else None
        except Exception:  # noqa: BLE001
            cache[day] = None
        return cache[day]

    return get


def load_records(processed_root: Path, before: str) -> List[Dict[str, Any]]:
    """Regular-season per-game smart sim outputs dated before `before`."""
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from syndicate.features.shared.nba_season_phase import phase_for_date

    recs, phase_cache = [], {}
    for f in sorted(processed_root.glob("smart_sim_20??-??-??_*.json")):
        day = f.name[len("smart_sim_"):len("smart_sim_") + 10]
        if day >= before:
            continue
        if day not in phase_cache:
            phase_cache[day] = phase_for_date(day, processed_root=processed_root, allow_fetch=False)
        if phase_cache[day] != "regular":
            continue
        try:
            j = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        a = j.get("market_anchor") or {}
        recs.append({"date": day, "home": j.get("home"), "away": j.get("away"),
                     "model_total_raw": a.get("model_total_raw"), "model_margin_raw": a.get("model_margin_raw")})
    return recs


def load_actuals(processed_root: Path, before: str) -> Dict[tuple, tuple]:
    out = {}
    for f in sorted(processed_root.glob("recon_games_20??-??-??.csv")):
        day = f.name[len("recon_games_"):len("recon_games_") + 10]
        if day >= before:
            continue
        with f.open(encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                try:
                    out[(str(r["date"])[:10], str(r["home_tri"]).upper(), str(r["away_tri"]).upper())] = (float(r["home_pts"]), float(r["visitor_pts"]))
                except (KeyError, TypeError, ValueError):
                    continue
    return out


def build(processed_root: Path, slate_date: str) -> dict:
    games = games_frame(load_records(processed_root, slate_date), load_actuals(processed_root, slate_date), cal_lookup(processed_root))
    terms = calibration_terms(games, slate_date=slate_date) if len(games) else {}
    if not terms and SEED_GAME_TOTAL_BIAS is not None:
        terms = {"global": {"game_total_bias": round(float(SEED_GAME_TOTAL_BIAS), 3)}, "team": {},
                 "meta": {"source": "scripts/build_nba_totals_calibration.py", "window": "seed", "seed_source": SEED_SOURCE,
                          "n_season": int(len(games)), "slate_date": slate_date}}
    return terms


def main(argv: Optional[List[str]] = None) -> int:
    import pandas as pd

    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--date", required=True, help="Slate date YYYY-MM-DD; the file is anchored on the day before")
    ap.add_argument("--processed-root", required=True, help="<nba_source>/data/processed")
    ap.add_argument("--force", action="store_true", help="Rebuild even if the anchor file already exists")
    args = ap.parse_args(argv)
    root = Path(args.processed_root)
    anchor = (pd.Timestamp(args.date) - pd.Timedelta(days=1)).date().isoformat()
    out = root / f"calibration_totals_{anchor}.json"
    if out.is_file() and out.stat().st_size > 0 and not args.force:
        print(json.dumps({"status": "exists", "path": str(out)}), flush=True)
        return 0
    terms = build(root, args.date)
    if not terms:
        print(json.dumps({"status": "skipped", "reason": "fewer than 8 regular-season games and no seed"}), flush=True)
        return 0
    terms["meta"]["anchor"] = anchor
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(terms, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, out)
    print(json.dumps({"status": "wrote", "path": str(out), "game_total_bias": terms["global"]["game_total_bias"],
                      "window": terms["meta"].get("window"), "n_season": terms["meta"].get("n_season")}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
