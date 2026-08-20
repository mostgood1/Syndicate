"""Build `home_court_advantage.json` for a basketball league (WNBA/NBA).

`#474`. THE GAP THIS CLOSES: the smart-sim engine had NO home/away split of
any kind. `_team_adj_from_advanced_stats_local`
(`basketball_props_smart_sim.py`) builds `home_adj`/`away_adj` purely from
each team's own season-long efficiency/pace/four-factor stats -- those
names describe WHICH TEAM, not WHERE THE GAME IS. Two evenly-matched teams
produced an identical simulated margin regardless of venue, which is wrong
for a real, well-established basketball effect.

MEASURED, not assumed (WNBA 2026, 136 regular-season games with a clean
schedule<->boxscore join): mean home margin **+2.07 points, t=+1.75**
(all-games including preseason: +2.31, t=+2.01; preseason alone runs hotter
at +4.11 on n=18, which is why preseason is EXCLUDED by default -- it is
not representative and it inflates the estimate).

HOW IT IS APPLIED, and why symmetric: the sim consumes `eff_mult` on each
side, which scales shot-make probability and therefore points roughly
linearly (`events.py:688,782,1528,1646`). Splitting the margin symmetrically
(+half to home, -half to away) shifts MARGIN by the measured amount while
leaving the TOTAL unchanged -- which is the correct shape: home-court
advantage is a margin effect, not a scoring-environment effect. Verified
arithmetically against the WNBA sample: home 87.78 / away 85.71 / total
173.49 all reproduce exactly.

DEFENSIVE BY DESIGN. Writes nothing and exits non-zero if the join is too
thin to trust (`--min-games`, default 40), so a bad season-start sample can
never quietly ship a garbage constant. The sim treats a missing file as
"no adjustment" (same optional-artifact convention as the four existing
calibration JSONs), so absence degrades to today's behaviour rather than
breaking anything.

Usage:
    py -3 scripts/build_basketball_home_court_advantage.py --league wnba
    py -3 scripts/build_basketball_home_court_advantage.py --league wnba --season 2026 --json
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _processed_root(league_code: str) -> Path:
    """Resolve the SAME processed root the sim actually reads.

    Deliberately mirrors the env var production sets (`render.yaml`:
    `WNBA_BETTING_DATA_ROOT=/opt/render/project/data/wnba_source/data`), NOT
    the nested `source_artifacts/` tree -- those hold different content and
    the FLAT one is what `_load_team_advanced_stats_asof_local` reads.
    Getting this wrong is a documented trap in this repo (`#468`).
    """
    code = str(league_code or "").strip().lower()
    env_key = "WNBA_BETTING_DATA_ROOT" if code == "wnba" else "NBA_BETTING_DATA_ROOT"
    raw = str(os.environ.get(env_key) or "").strip()
    if raw:
        return Path(raw) / "processed"
    return REPO_ROOT / "data" / f"{code}_source" / "data" / "processed"


def _schedule_path(league_code: str, season: int) -> Path:
    code = str(league_code or "").strip().lower()
    return REPO_ROOT / "vendor" / f"{code}_betting_repo" / "data" / "processed" / f"schedule_{int(season)}.csv"


def compute_home_court_advantage(
    *,
    league_code: str,
    season: int,
    include_preseason: bool = False,
    min_games: int = 40,
    min_t_stat: float = 1.0,
) -> dict:
    """Return the measured HCA payload, or a payload with `ok: False` and a
    reason when the sample cannot support one."""
    import pandas as pd

    processed_root = _processed_root(league_code)
    history_path = processed_root / "boxscores_history.csv"
    schedule_path = _schedule_path(league_code, season)

    diag: dict = {
        "league": str(league_code).lower(),
        "season": int(season),
        "boxscores_history": str(history_path),
        "schedule": str(schedule_path),
        "include_preseason": bool(include_preseason),
        "min_games": int(min_games),
        "min_t_stat": float(min_t_stat),
    }

    if not history_path.is_file():
        return {"ok": False, "reason": "boxscores_history_missing", **diag}
    if not schedule_path.is_file():
        return {"ok": False, "reason": "schedule_missing", **diag}

    box = pd.read_csv(history_path, dtype={"game_id": str})
    sched = pd.read_csv(schedule_path, dtype=str)

    needed_sched = {"game_id", "home_tricode", "away_tricode"}
    if not needed_sched.issubset(set(sched.columns)):
        return {"ok": False, "reason": "schedule_missing_columns", **diag}
    if not {"game_id", "TEAM_ABBREVIATION", "PTS"}.issubset(set(box.columns)):
        return {"ok": False, "reason": "boxscores_missing_columns", **diag}

    # Player rows -> team totals. `boxscores_history.csv` is PLAYER-level and
    # carries no home/away flag of its own -- the venue identity only exists
    # in the schedule, which is why this join is required at all.
    team_pts = box.groupby(["game_id", "TEAM_ABBREVIATION"], as_index=False)["PTS"].sum()

    keep_cols = ["game_id", "home_tricode", "away_tricode"]
    if "season_type_slug" in sched.columns:
        keep_cols.append("season_type_slug")
    merged = team_pts.merge(sched[keep_cols].dropna(subset=["game_id"]), on="game_id", how="inner")

    margins: list[float] = []
    home_points: list[float] = []
    away_points: list[float] = []
    skipped = 0
    for _gid, group in merged.groupby("game_id"):
        if len(group) != 2:
            skipped += 1
            continue
        season_type = str(group["season_type_slug"].iloc[0]).strip().lower() if "season_type_slug" in group.columns else ""
        if (not include_preseason) and season_type == "preseason":
            continue
        home_tri = str(group["home_tricode"].iloc[0]).strip().upper()
        away_tri = str(group["away_tricode"].iloc[0]).strip().upper()
        home_rows = group[group["TEAM_ABBREVIATION"].astype(str).str.upper() == home_tri]
        away_rows = group[group["TEAM_ABBREVIATION"].astype(str).str.upper() == away_tri]
        if len(home_rows) != 1 or len(away_rows) != 1:
            skipped += 1
            continue
        hp = float(home_rows["PTS"].iloc[0])
        ap = float(away_rows["PTS"].iloc[0])
        home_points.append(hp)
        away_points.append(ap)
        margins.append(hp - ap)

    diag["games_used"] = len(margins)
    diag["games_skipped_unjoinable"] = int(skipped)

    if len(margins) < max(2, int(min_games)):
        return {"ok": False, "reason": "insufficient_games", **diag}

    n = len(margins)
    mean_margin = sum(margins) / n
    mean_home = sum(home_points) / n
    mean_away = sum(away_points) / n
    mean_team_points = (mean_home + mean_away) / 2.0
    variance = sum((m - mean_margin) ** 2 for m in margins) / (n - 1)
    stdev = math.sqrt(max(0.0, variance))
    stderr = stdev / math.sqrt(n) if n > 0 else float("nan")
    t_stat = (mean_margin / stderr) if stderr and math.isfinite(stderr) and stderr > 0 else float("nan")
    home_win_rate = sum(1 for m in margins if m > 0) / n

    if mean_team_points <= 0:
        return {"ok": False, "reason": "degenerate_mean_points", **diag}

    diag["mean_margin"] = mean_margin
    diag["t_stat"] = t_stat
    diag["home_win_rate"] = home_win_rate

    # `#483`. THE INCIDENT: a production run on 2026-08-20T14:33Z emitted
    # `eff_mult_delta = -0.0116` from 46 games -- a NEGATIVE home-court
    # advantage, published for the sim to consume. Two hours earlier the same
    # service on the same disk produced +0.0151 from 138 games. The existing
    # `min_games=40` floor passed it, because a game COUNT says nothing about
    # whether the estimate is distinguishable from noise.
    #
    # Home-court advantage is one of the most robust priors in team sports.
    # A negative point estimate is not a discovery, it is a thin sample, and
    # shipping it actively inverts a real effect the sim would otherwise get
    # roughly right by doing nothing. Two gates, both cheap:
    #
    #   SIGN  -- refuse a negative advantage outright. This is a genuine
    #            prior, not curve-fitting: the measured full-season value is
    #            +2.31 pts (t=+2.01), regular-season-only +2.07 (t=+1.75).
    #   POWER -- refuse when the estimate is not distinguishable from zero.
    #            t=1.0 is deliberately permissive (roughly the 84th
    #            percentile one-sided); the aim is to exclude noise, not to
    #            demand significance a 40-game WNBA sample cannot supply.
    #
    # Refusal is FAIL-SAFE: no file is written, `_load_home_court_advantage_local`
    # finds nothing, and the sim runs with no home-court term -- exactly the
    # behaviour that predates `#474`, and strictly better than a sign-flipped one.
    if mean_margin <= 0.0:
        return {"ok": False, "reason": "non_positive_home_advantage", **diag}
    if not (math.isfinite(t_stat) and t_stat >= float(min_t_stat)):
        return {"ok": False, "reason": "estimate_indistinguishable_from_zero", "min_t_stat": float(min_t_stat), **diag}

    # Symmetric split: half the margin to each side, so TOTAL is unchanged.
    eff_mult_delta = (mean_margin / 2.0) / mean_team_points

    # Bounded for the same reason every other multiplier here is bounded: a
    # thin or anomalous sample must not be able to swing the sim hard. 3% per
    # side (~5.2 points of margin at WNBA scoring levels) is far outside any
    # plausible real HCA, so this clamp only ever catches genuine outliers.
    clamped = max(-0.03, min(0.03, eff_mult_delta))

    return {
        "ok": True,
        "home_eff_mult": 1.0 + clamped,
        "away_eff_mult": 1.0 - clamped,
        "eff_mult_delta": clamped,
        "eff_mult_delta_raw": eff_mult_delta,
        "clamped": bool(abs(clamped - eff_mult_delta) > 1e-12),
        "measured": {
            "mean_home_margin": mean_margin,
            "mean_home_points": mean_home,
            "mean_away_points": mean_away,
            "mean_team_points": mean_team_points,
            "margin_stdev": stdev,
            "margin_stderr": stderr,
            "t_stat": t_stat,
            "home_win_rate": home_win_rate,
            "games": n,
        },
        **diag,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--league", default="wnba", choices=("wnba", "nba"))
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--include-preseason", action="store_true", help="include preseason games (default: regular season only)")
    parser.add_argument("--min-games", type=int, default=40, help="refuse to write below this many joined games")
    parser.add_argument("--min-t-stat", type=float, default=1.0, help="refuse when the home-advantage estimate is not distinguishable from zero")
    parser.add_argument("--dry-run", action="store_true", help="compute and print, write nothing")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    payload = compute_home_court_advantage(
        league_code=args.league,
        season=args.season,
        include_preseason=bool(args.include_preseason),
        min_games=int(args.min_games),
        min_t_stat=float(args.min_t_stat),
    )

    if args.json:
        print(json.dumps(payload, indent=2, default=str))
    else:
        if payload.get("ok"):
            m = payload["measured"]
            print(f"{args.league.upper()} {args.season} home-court advantage")
            print(f"  games used           : {m['games']} (skipped unjoinable: {payload['games_skipped_unjoinable']})")
            print(f"  mean home margin     : {m['mean_home_margin']:+.3f} pts")
            print(f"  t-stat vs 0          : {m['t_stat']:+.2f}")
            print(f"  home win rate        : {m['home_win_rate']:.3f}")
            print(f"  mean home / away pts : {m['mean_home_points']:.2f} / {m['mean_away_points']:.2f}")
            print(f"  -> home_eff_mult     : {payload['home_eff_mult']:.5f}")
            print(f"  -> away_eff_mult     : {payload['away_eff_mult']:.5f}")
            if payload.get("clamped"):
                print(f"  NOTE: clamped from raw {payload['eff_mult_delta_raw']:+.5f}")
        else:
            print(f"REFUSING TO WRITE: {payload.get('reason')}")
            print(f"  games_used={payload.get('games_used')} min_games={payload.get('min_games')}")

    if not payload.get("ok"):
        return 2

    if args.dry_run:
        print("\n--dry-run: nothing written")
        return 0

    out_path = _processed_root(args.league) / "home_court_advantage.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(f"\nwrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
