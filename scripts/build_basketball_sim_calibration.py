"""Build the smart-sim calibration artifacts from paired sim-vs-actual history.

`#476`. THE GAP THIS CLOSES: the smart-sim engine reads four optional
calibration artifacts, every one of which has been ABSENT since the engine
shipped -- so four real correction mechanisms have been permanently inert:

    smart_sim_total_calibration.json   {"points_mult": float}
    player_stat_calibration.json       {"players": {"<pid>": {"pts": bias, ...}}}
    intervals_band_calibration.json    {"per_segment": {...}, "global": {"seg","cum"}}
    intervals_time_profile.json        {"segment_multipliers": [...], "clip": [lo,hi]}

Each degrades silently to "no adjustment" when missing, which is exactly why
nobody noticed: a missing calibration file and a perfectly-calibrated model
are indistinguishable at every level except the data.

THE SUBSTRATE TRAP, and it is the whole reason this script reads production
rather than the local mirror. Every `smart_sim_*.json` in the local
git-tracked mirror is FALLBACK-STUB output, not real-engine output --
measured 2026-08-19: 56 local files, 0 with a `score` block, 53 carrying
`home_team_total_pts_mean` (the stub's fingerprint key, present ONLY in
`_simulate_smart_game_local`'s return dict). Production is the opposite:
`smart_sim_2026-08-19_WSH_TOR.json` has `score.total_mean = 174.78`,
`n_sims = 100`, no stub key. Calibrating off the local mirror would fit
corrections to a model that never runs -- worse than no calibration at all.
So `--source production` is the DEFAULT here, deliberately, inverting this
repo's usual local-first convention.

WHAT IT CAN AND CANNOT BUILD, stated honestly:
  * `smart_sim_total_calibration` -- fully derivable. Needs only predicted
    vs actual game totals, both available.
  * `player_stat_calibration` -- fully derivable. Needs per-player predicted
    means (in each sim file's `players` block) vs actual box lines.
  * `intervals_band_calibration` / `intervals_time_profile` -- NOT built
    here, and not by oversight. Both need per-3-minute-segment ACTUALS
    (interval scoring within each quarter). Syndicate captures final box
    lines and quarter totals, not 3-minute segment scoring, so the actuals
    side does not exist in any artifact this repo currently produces.
    Building them would mean first building segment-level capture (a
    play-by-play derivation), which is genuinely separate work. This script
    reports that explicitly rather than emitting a plausible-looking file
    fitted to data that cannot support it.

Usage:
    py -3 scripts/build_basketball_sim_calibration.py --league wnba --dry-run
    py -3 scripts/build_basketball_sim_calibration.py --league wnba --write
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_SIM_NAME_RE = re.compile(r"smart_sim_(\d{4}-\d{2}-\d{2})_([A-Z0-9]+)_([A-Z0-9]+)\.json$")

# Same base URL the other ops-reading scripts use.
_DEFAULT_BASE_URL = "https://syndicate-an21.onrender.com"


def _admin_token() -> str:
    token = str(os.environ.get("ADMIN_TOKEN") or "").strip()
    if token:
        return token
    env_path = REPO_ROOT / ".env"
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("ADMIN_TOKEN"):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("ADMIN_TOKEN not found (env or .env)")


def _ops_export(base_url: str, token: str, *, path: str | None = None, pattern: str | None = None, names_only: bool = False) -> dict:
    params = {"admin_token": token}
    if path:
        params["path"] = path
    if pattern:
        params["pattern"] = pattern
    if names_only:
        params["names_only"] = "1"
    url = base_url.rstrip("/") + "/api/ops/artifacts/export?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=90) as response:
        return json.loads(response.read().decode("utf-8"))


def _processed_root(league_code: str) -> Path:
    code = str(league_code or "").strip().lower()
    env_key = "WNBA_BETTING_DATA_ROOT" if code == "wnba" else "NBA_BETTING_DATA_ROOT"
    raw = str(os.environ.get(env_key) or "").strip()
    if raw:
        return Path(raw) / "processed"
    return REPO_ROOT / "data" / f"{code}_source" / "data" / "processed"


def _load_pairs(league_code: str, base_url: str, token: str, *, verbose: bool = True) -> tuple[list[dict], list[dict], dict]:
    """Return (game_pairs, player_pairs, diag) from PRODUCTION artifacts."""
    import pandas as pd

    diag: dict = {"source": "production", "base_url": base_url}

    listing = _ops_export(base_url, token, pattern=f"{league_code}_source/data/processed/smart_sim_*.json", names_only=True)
    sim_paths = sorted(listing.get("artifacts", {}).keys())
    diag["sim_files_listed"] = len(sim_paths)
    if verbose:
        print(f"  production smart_sim files: {len(sim_paths)}")

    box_payload = _ops_export(base_url, token, path=f"{league_code}_source/data/processed/boxscores_history.csv")
    if not box_payload.get("count"):
        raise SystemExit("boxscores_history.csv not retrievable from production")
    import io

    box = pd.read_csv(io.StringIO(list(box_payload["artifacts"].values())[0]), dtype={"game_id": str})
    diag["boxscore_rows"] = int(len(box))
    actual_dates = set(box["date"].astype(str))
    if verbose:
        print(f"  boxscore rows: {len(box)}  dates: {len(actual_dates)}")

    schedule_path = REPO_ROOT / "vendor" / f"{league_code}_betting_repo" / "data" / "processed" / "schedule_2026.csv"
    sched = pd.read_csv(schedule_path, dtype=str) if schedule_path.is_file() else None

    team_pts = box.groupby(["game_id", "TEAM_ABBREVIATION"], as_index=False)["PTS"].sum()

    game_pairs: list[dict] = []
    player_pairs: list[dict] = []
    fetched = 0
    for rel in sim_paths:
        match = _SIM_NAME_RE.search(rel.replace("\\", "/"))
        if not match:
            continue
        date_str, home_tri, away_tri = match.group(1), match.group(2), match.group(3)
        if date_str not in actual_dates:
            continue  # no actuals for that date; nothing to calibrate against

        gid = None
        if sched is not None:
            cand = sched[(sched["home_tricode"] == home_tri) & (sched["away_tricode"] == away_tri)]
            for col in ("date_utc", "date_est"):
                if col in cand.columns:
                    hit = cand[cand[col] == date_str]
                    if not hit.empty:
                        gid = str(hit["game_id"].iloc[0])
                        break
            if gid is None and not cand.empty:
                gid = str(cand["game_id"].iloc[0])
        if gid is None:
            continue

        team_rows = team_pts[team_pts["game_id"] == gid]
        if len(team_rows) != 2:
            continue
        home_actual = team_rows[team_rows["TEAM_ABBREVIATION"].astype(str).str.upper() == home_tri]["PTS"]
        away_actual = team_rows[team_rows["TEAM_ABBREVIATION"].astype(str).str.upper() == away_tri]["PTS"]
        if len(home_actual) != 1 or len(away_actual) != 1:
            continue

        try:
            payload_json = _ops_export(base_url, token, path=rel)
        except Exception:
            continue
        if not payload_json.get("count"):
            continue
        fetched += 1
        try:
            sim = json.loads(list(payload_json["artifacts"].values())[0])
        except Exception:
            continue

        score = sim.get("score") if isinstance(sim.get("score"), dict) else {}
        pred_total = score.get("total_mean")
        if pred_total is None:
            # Stub output -- explicitly excluded, see module docstring.
            continue

        actual_total = float(home_actual.iloc[0]) + float(away_actual.iloc[0])
        game_pairs.append(
            {
                "date": date_str,
                "game_id": gid,
                "pred_total": float(pred_total),
                "actual_total": actual_total,
                "pred_margin": float(score.get("margin_mean") or 0.0),
                "actual_margin": float(home_actual.iloc[0]) - float(away_actual.iloc[0]),
            }
        )

        # Per-player predicted means vs actual box lines.
        game_box = box[box["game_id"] == gid]
        actual_by_pid: dict[str, dict] = {}
        for _, brow in game_box.iterrows():
            pid = str(brow.get("PLAYER_ID") or "").strip()
            if not pid:
                continue
            actual_by_pid[pid] = {
                "pts": float(brow.get("PTS") or 0.0),
                "reb": float(brow.get("REB") or 0.0),
                "ast": float(brow.get("AST") or 0.0),
                "threes": float(brow.get("FG3M") or 0.0),
                "stl": float(brow.get("STL") or 0.0),
                "blk": float(brow.get("BLK") or 0.0),
                "tov": float(brow.get("TOV") or 0.0),
            }

        players_block = sim.get("players")
        rows_iter: list[dict] = []
        if isinstance(players_block, dict):
            for side in ("home", "away"):
                side_rows = players_block.get(side)
                if isinstance(side_rows, list):
                    rows_iter.extend([r for r in side_rows if isinstance(r, dict)])
        elif isinstance(players_block, list):
            rows_iter = [r for r in players_block if isinstance(r, dict)]

        for prow in rows_iter:
            pid = str(prow.get("player_id") or prow.get("PLAYER_ID") or "").strip()
            if not pid or pid not in actual_by_pid:
                continue
            actual = actual_by_pid[pid]
            for stat in ("pts", "reb", "ast", "threes", "stl", "blk", "tov"):
                pred = prow.get(f"{stat}_mean")
                if pred is None:
                    continue
                try:
                    pred_f = float(pred)
                except Exception:
                    continue
                if not math.isfinite(pred_f):
                    continue
                player_pairs.append({"player_id": pid, "stat": stat, "pred": pred_f, "actual": actual[stat]})

    diag["sim_files_fetched"] = fetched
    diag["game_pairs"] = len(game_pairs)
    diag["player_pairs"] = len(player_pairs)
    return game_pairs, player_pairs, diag


def build_total_calibration(game_pairs: list[dict], *, min_games: int) -> dict:
    if len(game_pairs) < min_games:
        return {"ok": False, "reason": "insufficient_games", "games": len(game_pairs), "min_games": min_games}
    pred = [g["pred_total"] for g in game_pairs]
    actual = [g["actual_total"] for g in game_pairs]
    n = len(pred)
    mean_pred = sum(pred) / n
    mean_actual = sum(actual) / n
    if mean_pred <= 0:
        return {"ok": False, "reason": "degenerate_predictions"}
    raw_mult = mean_actual / mean_pred
    # The consumer clamps to [0.97, 1.03]; clamp here too so the artifact
    # never claims a correction the engine will silently refuse to apply.
    points_mult = max(0.97, min(1.03, raw_mult))
    errs = [a - p for a, p in zip(actual, pred)]
    mean_err = sum(errs) / n
    sd = math.sqrt(sum((e - mean_err) ** 2 for e in errs) / (n - 1)) if n > 1 else float("nan")
    se = sd / math.sqrt(n) if n > 1 and math.isfinite(sd) else float("nan")
    return {
        "ok": True,
        "points_mult": points_mult,
        "points_mult_raw": raw_mult,
        "clamped": bool(abs(points_mult - raw_mult) > 1e-12),
        "measured": {
            "games": n,
            "mean_predicted_total": mean_pred,
            "mean_actual_total": mean_actual,
            "mean_error": mean_err,
            "mae": sum(abs(e) for e in errs) / n,
            "error_sd": sd,
            "error_se": se,
            "t_stat": (mean_err / se) if se and math.isfinite(se) and se > 0 else float("nan"),
        },
    }


def build_player_stat_calibration(player_pairs: list[dict], *, min_obs_per_player_stat: int) -> dict:
    if not player_pairs:
        return {"ok": False, "reason": "no_player_pairs"}
    grouped: dict[str, dict[str, list[float]]] = {}
    for row in player_pairs:
        grouped.setdefault(row["player_id"], {}).setdefault(row["stat"], []).append(row["actual"] - row["pred"])

    players: dict[str, dict[str, float]] = {}
    kept = 0
    skipped_thin = 0
    for pid, stats in grouped.items():
        entry: dict[str, float] = {}
        for stat, errs in stats.items():
            if len(errs) < min_obs_per_player_stat:
                skipped_thin += 1
                continue
            bias = sum(errs) / len(errs)
            # Bounded: a per-player additive bias is a nudge, not a rewrite.
            # 3.0 points/rebounds/assists is already a very large systematic
            # miss; anything beyond that is far likelier to be a sample
            # artifact than a real, stable player-level bias.
            bias = max(-3.0, min(3.0, bias))
            if abs(bias) < 1e-9:
                continue
            entry[stat] = bias
            kept += 1
        if entry:
            players[pid] = entry

    if not players:
        return {"ok": False, "reason": "no_player_stat_met_threshold", "min_obs_per_player_stat": min_obs_per_player_stat}
    return {
        "ok": True,
        "players": players,
        "measured": {
            "players_with_bias": len(players),
            "player_stat_biases_kept": kept,
            "player_stat_combos_skipped_thin": skipped_thin,
            "min_obs_per_player_stat": min_obs_per_player_stat,
            "total_observations": len(player_pairs),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--league", default="wnba", choices=("wnba", "nba"))
    parser.add_argument("--base-url", default=_DEFAULT_BASE_URL)
    parser.add_argument("--min-games", type=int, default=30, help="minimum paired games for the total calibration")
    parser.add_argument("--min-obs", type=int, default=4, help="minimum observations per (player, stat) for a bias")
    parser.add_argument("--write", action="store_true", help="write artifacts (default is dry-run)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    token = _admin_token()
    print(f"Pairing production sim outputs with actuals ({args.league.upper()})...")
    game_pairs, player_pairs, diag = _load_pairs(args.league, args.base_url, token)
    print(f"  paired games: {diag['game_pairs']}  player-stat observations: {diag['player_pairs']}")

    total_cal = build_total_calibration(game_pairs, min_games=args.min_games)
    player_cal = build_player_stat_calibration(player_pairs, min_obs_per_player_stat=args.min_obs)

    results = {
        "smart_sim_total_calibration.json": total_cal,
        "player_stat_calibration.json": player_cal,
        "intervals_band_calibration.json": {
            "ok": False,
            "reason": "actuals_unavailable",
            "detail": (
                "Needs per-3-minute-segment actual scoring to compare against the sim's "
                "own interval quantiles. Syndicate captures final box lines and quarter "
                "totals, not intra-quarter segment scoring, so the actuals side does not "
                "exist in any artifact this repo currently produces. Building this "
                "requires segment-level capture (a play-by-play derivation) first."
            ),
        },
        "intervals_time_profile.json": {
            "ok": False,
            "reason": "actuals_unavailable",
            "detail": (
                "Same blocker as intervals_band_calibration: the segment_multipliers it "
                "expects describe the SHAPE of scoring across 16 regulation 3-minute "
                "segments, which cannot be fitted without segment-level actuals."
            ),
        },
    }

    if args.json:
        print(json.dumps({"diag": diag, "results": results}, indent=2, default=str))
    else:
        print()
        for name, payload in results.items():
            if payload.get("ok"):
                print(f"  BUILDABLE  {name}")
                if name.startswith("smart_sim_total"):
                    m = payload["measured"]
                    print(f"               points_mult={payload['points_mult']:.5f} (raw {payload['points_mult_raw']:.5f}"
                          f"{', CLAMPED' if payload['clamped'] else ''})")
                    print(f"               games={m['games']}  pred={m['mean_predicted_total']:.2f}  actual={m['mean_actual_total']:.2f}")
                    print(f"               mean_err={m['mean_error']:+.2f}  MAE={m['mae']:.2f}  t={m['t_stat']:+.2f}")
                else:
                    m = payload["measured"]
                    print(f"               players_with_bias={m['players_with_bias']}  biases={m['player_stat_biases_kept']}")
                    print(f"               observations={m['total_observations']}  skipped_thin={m['player_stat_combos_skipped_thin']}")
            else:
                print(f"  NOT BUILT  {name}  ({payload.get('reason')})")

    if not args.write:
        print("\n(dry run -- pass --write to emit artifacts)")
        return 0

    processed_root = _processed_root(args.league)
    processed_root.mkdir(parents=True, exist_ok=True)
    written = 0
    for name, payload in results.items():
        if not payload.get("ok"):
            continue
        (processed_root / name).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        print(f"wrote {processed_root / name}")
        written += 1
    if written == 0:
        print("nothing written (no artifact met its threshold)")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
