#!/usr/bin/env python3
"""Producer: real play-by-play shot data -> a truth-fit logistic xG model -> `team_xg_{season}.csv`.

Closes the gap `docs/ai_context/hockeysim_engine_reference.md` §5 flagged as genuinely absent, not
merely unfed: `xgf_per_60`/`xga_per_60` have a reader (`loaders.load_team_xg_map`, already wired
into `build_team_features`) but NO PRODUCER anywhere. This is that producer.

WHY TEAM IDENTITY IS NOT A FEATURE (and why that matters for the aggregation step below). The
model is fit on shot-level features ONLY (distance, angle, shot type, strength state, rebound,
empty net) -- never which TEAM took the shot. That means the fitted model cannot overfit to a
specific team's shooting/goaltending quality, so scoring every shot with the SAME model fit on the
FULL dataset (rather than needing held-out/cross-validated scores for the aggregation step) does
not leak team identity back into that team's own xG total. The train/test split below exists only
to validate the model's CALIBRATION, not to protect the aggregation from leakage.

Usage:
  py -3 scripts/build_nhl_xg_artifact.py
  py -3 scripts/build_nhl_xg_artifact.py --season 2025-2026
"""
from __future__ import annotations

import argparse
import glob
import json
import random
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from syndicate.features.nhl.sim_engine.hockeysim.features.loaders import season_code_for_date  # noqa: E402
from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.nhl_statsweb_loader import (  # noqa: E402
    NhlStatsWebTruthLoader,
)
from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.shot_xg_model import (  # noqa: E402
    FEATURE_NAMES, ShotEvent, featurize, parse_play_by_play_shots,
)


def _nhl_source_root() -> Path:
    import os
    env = str(os.environ.get("SYNDICATE_ARTIFACT_ROOT_NHL") or "").strip()
    if env:
        p = Path(env)
        if p.exists():
            return p
    return REPO / "data" / "nhl_source"


def _load_playbyplay_payloads(root: Path, game_ids: List[str]) -> List[Dict]:
    cache_dir = root / "data" / "ingestion_cache"
    out: List[Dict] = []
    for gid in game_ids:
        p = cache_dir / f"playbyplay_{gid}.json"
        if not p.exists():
            continue
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    return out


def _game_team_map(payloads: List[Dict]) -> Dict[str, Dict[str, object]]:
    """`{game_id: {home_id, home_abbr, away_id, away_abbr}}` -- needed to attribute each shot's
    xG to BOTH the shooting team (xGF) and the defending team (xGA)."""
    out: Dict[str, Dict[str, object]] = {}
    for payload in payloads:
        gid = str(payload.get("id") or "")
        home = payload.get("homeTeam") or {}
        away = payload.get("awayTeam") or {}
        if not gid or home.get("id") is None or away.get("id") is None:
            continue
        out[gid] = {
            "home_id": int(home["id"]), "home_abbr": str(home.get("abbrev") or "").upper(),
            "away_id": int(away["id"]), "away_abbr": str(away.get("abbrev") or "").upper(),
        }
    return out


def _fit_logistic(X: List[List[float]], y: List[int]):
    from sklearn.linear_model import LogisticRegression
    model = LogisticRegression(max_iter=2000)
    model.fit(X, y)
    return model


def _evaluate(model, X: List[List[float]], y: List[int]) -> Dict[str, float]:
    from sklearn.metrics import brier_score_loss, roc_auc_score
    proba = model.predict_proba(X)[:, 1]
    auc = float(roc_auc_score(y, proba))
    brier = float(brier_score_loss(y, proba))
    return {"auc": auc, "brier": brier}


def _calibration_table(model, X: List[List[float]], y: List[int], *, n_buckets: int = 10) -> List[Tuple[float, float, int]]:
    """`[(mean_predicted, actual_goal_rate, n)]` per decile of predicted probability -- a
    well-calibrated model has mean_predicted ≈ actual_goal_rate in every bucket."""
    proba = model.predict_proba(X)[:, 1]
    order = sorted(range(len(y)), key=lambda i: proba[i])
    n = len(order)
    bucket_size = max(1, n // n_buckets)
    rows = []
    for b in range(n_buckets):
        idx = order[b * bucket_size: (b + 1) * bucket_size] if b < n_buckets - 1 else order[b * bucket_size:]
        if not idx:
            continue
        mean_pred = sum(proba[i] for i in idx) / len(idx)
        actual = sum(y[i] for i in idx) / len(idx)
        rows.append((round(mean_pred, 4), round(actual, 4), len(idx)))
    return rows


def _write_csv(path: Path, xgf60: Dict[str, float], xga60: Dict[str, float], games: Dict[str, int]) -> int:
    import csv
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(xgf60)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["abbr", "xgf60", "xga60", "games"])
        for abbr in rows:
            w.writerow([abbr, round(xgf60[abbr], 4), round(xga60.get(abbr, 0.0), 4), games.get(abbr, 0)])
    return len(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--season", default=None)
    ap.add_argument("--root", type=Path, default=None)
    ap.add_argument("--holdout-frac", type=float, default=0.2)
    ap.add_argument("--seed", type=int, default=20260818)
    args = ap.parse_args()

    root = args.root or _nhl_source_root()
    truth_loader = NhlStatsWebTruthLoader(offline=True)
    truth_games = truth_loader.load_from_cache()
    regular = [g for g in truth_games if int(g.game_type) == 2]
    if not regular:
        print("REFUSED: no cached regular-season truth games", file=sys.stderr)
        return 1
    game_ids = sorted({g.game_id for g in regular})
    dates = sorted({g.date[:10] for g in regular if g.date})
    season = args.season or (season_code_for_date(dates[-1]) if dates else "")

    payloads = _load_playbyplay_payloads(root, game_ids)
    if not payloads:
        print(f"REFUSED: no play-by-play cache under {root}/data/ingestion_cache -- run "
              f"scripts/fetch_nhl_playbyplay_cache.py first", file=sys.stderr)
        return 1
    print(f"loaded {len(payloads)}/{len(game_ids)} play-by-play payloads")

    game_team = _game_team_map(payloads)
    shots: List[ShotEvent] = []
    for payload in payloads:
        shots.extend(parse_play_by_play_shots(payload))
    print(f"parsed {len(shots)} Fenwick shot attempts ({sum(1 for s in shots if s.is_goal)} goals, "
          f"{sum(1 for s in shots if s.is_goal) / len(shots):.4f} shooting%)")

    # Split by GAME (not shot) for the calibration check -- conservative, though team identity
    # isn't a feature so shot-level leakage isn't really possible; games are a natural, clean unit.
    rng = random.Random(args.seed)
    game_ids_with_shots = sorted({s.game_id for s in shots})
    rng.shuffle(game_ids_with_shots)
    n_holdout = max(1, int(len(game_ids_with_shots) * args.holdout_frac))
    holdout_games = set(game_ids_with_shots[:n_holdout])

    train_shots = [s for s in shots if s.game_id not in holdout_games]
    test_shots = [s for s in shots if s.game_id in holdout_games]
    X_train, y_train = featurize(train_shots), [1 if s.is_goal else 0 for s in train_shots]
    X_test, y_test = featurize(test_shots), [1 if s.is_goal else 0 for s in test_shots]
    print(f"train: {len(train_shots)} shots ({len(game_ids_with_shots) - n_holdout} games)  "
          f"holdout: {len(test_shots)} shots ({n_holdout} games)")

    model_cv = _fit_logistic(X_train, y_train)
    metrics = _evaluate(model_cv, X_test, y_test)
    print(f"\nholdout validation: AUC={metrics['auc']:.4f}  Brier={metrics['brier']:.4f}")
    print("calibration table (mean_predicted, actual_goal_rate, n) by decile of predicted prob:")
    for mean_pred, actual, n in _calibration_table(model_cv, X_test, y_test):
        print(f"  predicted={mean_pred:.4f}  actual={actual:.4f}  n={n}")

    # Refit on the FULL dataset for the production model (team identity isn't a feature -- see
    # module docstring -- so this doesn't leak team-level information back into a team's own xG).
    X_full = featurize(shots)
    y_full = [1 if s.is_goal else 0 for s in shots]
    model = _fit_logistic(X_full, y_full)
    coefs = dict(zip(FEATURE_NAMES, model.coef_[0].tolist()))
    print(f"\nfull-data model intercept={model.intercept_[0]:.4f}")
    for name, coef in coefs.items():
        print(f"  {name:20s} {coef:+.4f}")

    proba_full = model.predict_proba(X_full)[:, 1]

    xgf: Dict[str, float] = defaultdict(float)
    xga: Dict[str, float] = defaultdict(float)
    games_played: Dict[str, set] = defaultdict(set)
    skipped = 0
    for shot, xg in zip(shots, proba_full):
        meta = game_team.get(shot.game_id)
        if not meta:
            skipped += 1
            continue
        if shot.team_id == meta["home_id"]:
            shooter, defender = meta["home_abbr"], meta["away_abbr"]
        elif shot.team_id == meta["away_id"]:
            shooter, defender = meta["away_abbr"], meta["home_abbr"]
        else:
            skipped += 1
            continue
        xgf[shooter] += float(xg)
        xga[defender] += float(xg)

    for gid, meta in game_team.items():
        games_played[meta["home_abbr"]].add(gid)
        games_played[meta["away_abbr"]].add(gid)

    xgf60 = {abbr: xgf[abbr] / max(1, len(games_played[abbr])) for abbr in games_played}
    xga60 = {abbr: xga[abbr] / max(1, len(games_played[abbr])) for abbr in games_played}
    games = {abbr: len(g) for abbr, g in games_played.items()}

    league_xgf = sum(xgf60.values()) / max(1, len(xgf60))
    league_xga = sum(xga60.values()) / max(1, len(xga60))
    print(f"\n{skipped} shots skipped (game not in team map)")
    print(f"teams rated: {len(xgf60)}  league avg xGF/60={league_xgf:.4f}  league avg xGA/60={league_xga:.4f}")
    print("(sanity check: a well-calibrated model's league-average xG/60 should sit close to the "
          "real, truth-calibrated league_baseline_goals_per_60=3.1269 this codebase already uses)")

    out_dir = root / "data" / "processed"
    written = []
    if season:
        p = out_dir / f"team_xg_{season}.csv"
        written.append((p, _write_csv(p, xgf60, xga60, games)))
    p_latest = out_dir / "team_xg_latest.csv"
    written.append((p_latest, _write_csv(p_latest, xgf60, xga60, games)))
    for path, n in written:
        print(f"wrote {path} ({n} teams)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
