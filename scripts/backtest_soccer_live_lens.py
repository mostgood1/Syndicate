"""Real, non-heuristic validation of the live lens.

No match is live right now, so this validates the forward-projection
mechanism the way the rest of this project validates things: take real
*completed* matches, cut them off at a point in time (build a live state
from real data truncated there -- exactly what a live poll would have
returned at that moment, since ``build_live_state``'s cutoff semantics are
symmetric between "genuinely live" and "replayed at a cutoff"), project
forward, and compare the projection against the REAL final outcome the
match actually had. Non-circular: the model never sees anything past the
cutoff, and "ground truth" is real data withheld from it, not a market
consensus it could be indirectly fit to.

Usage:
    python scripts/backtest_soccer_live_lens.py --league epl --matches 60 --cutoff-minute 60
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from statistics import mean

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.soccer.features.live_lens import project_live_match
from syndicate.features.soccer.features.loaders import compute_team_ratings
from syndicate.features.soccer.features.team_names import match_team_name
from syndicate.features.soccer.ingestion.espn_lineups import fetch_completed_events
from syndicate.features.soccer.ingestion.espn_lineups import fetch_match_summary
from syndicate.features.soccer.ingestion.espn_live_state import build_live_state
from syndicate.features.soccer.ingestion.player_history import fetch_asa_mls_team_history
from syndicate.features.soccer.sim_engine.soccersim.league_profiles import get_league_profile

_LEAGUE_SEASON_WINDOWS = [
    "20250801-20250831", "20250901-20250930", "20251001-20251031", "20251101-20251130",
    "20251201-20251231", "20260101-20260131", "20260201-20260228", "20260301-20260331",
    "20260401-20260430", "20260501-20260531",
]
_NEUTRAL_RATING = {"attack_rating": 0.0, "defense_rating": 0.0}


def _load_team_ratings(league: str) -> dict[str, dict[str, float]]:
    if league == "mls":
        return compute_team_ratings(fetch_asa_mls_team_history(2026))
    history_dir = REPO_ROOT / "data" / "soccer_source" / league / "team_history"
    frames = [pd.read_csv(path) for path in sorted(history_dir.glob("teams_*.csv"))]
    if frames:
        rows = pd.concat(frames, ignore_index=True).to_dict("records")
        return compute_team_ratings(rows, window=45)
    return {}


def run_backtest(league: str, *, max_matches: int, cutoff_minute: int, simulations: int, out_path: Path | None) -> int:
    completed = fetch_completed_events(league, date_windows=_LEAGUE_SEASON_WINDOWS)
    print(f"{len(completed)} completed {league} matches available")
    completed = sorted(completed, key=lambda row: row["date"])
    if len(completed) > max_matches:
        step = len(completed) / max_matches
        completed = [completed[int(i * step)] for i in range(max_matches)]
    print(f"backtesting {len(completed)} matches, cutoff at minute {cutoff_minute}")

    ratings = _load_team_ratings(league)
    profile = get_league_profile(league)
    cutoff_seconds = cutoff_minute * 60.0

    rows: list[dict] = []
    for event in completed:
        try:
            summary = fetch_match_summary(league, event["event_id"])
        except Exception as exc:
            print(f"skip {event['event_id']}: {exc}")
            continue
        full_state = build_live_state(summary, event_id=event["event_id"])
        if not full_state["home_team"] or not full_state["away_team"]:
            continue
        # Skip matches that hadn't reached the cutoff yet (shouldn't happen
        # for completed matches, but stay defensive) or that ended early.
        cutoff_state = build_live_state(summary, event_id=event["event_id"], as_of_seconds=cutoff_seconds)

        home_key = match_team_name(cutoff_state["home_team"], list(ratings))
        away_key = match_team_name(cutoff_state["away_team"], list(ratings))
        home_rating = ratings.get(home_key, _NEUTRAL_RATING) if home_key else _NEUTRAL_RATING
        away_rating = ratings.get(away_key, _NEUTRAL_RATING) if away_key else _NEUTRAL_RATING

        projection = project_live_match(
            cutoff_state, home_rating=home_rating, away_rating=away_rating, profile=profile, simulations=simulations
        )

        actual_home = full_state["score_home"]
        actual_away = full_state["score_away"]
        actual_total = actual_home + actual_away
        actual_btts = actual_home > 0 and actual_away > 0
        actual_over_2_5 = actual_total >= 3
        actual_result = "home" if actual_home > actual_away else ("away" if actual_away > actual_home else "draw")
        result_probability_key = {"home": "home_win_probability", "away": "away_win_probability", "draw": "draw_probability"}[
            actual_result
        ]
        actual_home_corners = full_state["home_corners_so_far"]
        actual_away_corners = full_state["away_corners_so_far"]

        rows.append(
            {
                "match": f"{cutoff_state['home_team']} v {cutoff_state['away_team']}",
                "score_at_cutoff": f"{cutoff_state['score_home']}-{cutoff_state['score_away']}",
                "actual_final_score": f"{actual_home}-{actual_away}",
                "actual_result": actual_result,
                "model_result_probability": projection.to_dict()[result_probability_key],
                "predicted_home_win": projection.home_win_probability,
                "predicted_draw": projection.draw_probability,
                "predicted_away_win": projection.away_win_probability,
                "predicted_total": projection.projected_final_total,
                "actual_total": actual_total,
                "total_error": abs(projection.projected_final_total - actual_total),
                "predicted_btts": projection.both_teams_scored_probability,
                "actual_btts": actual_btts,
                "predicted_over_2_5": projection.over_2_5_probability,
                "actual_over_2_5": actual_over_2_5,
                "predicted_home_corners": projection.projected_home_corners,
                "actual_home_corners": actual_home_corners,
                "predicted_away_corners": projection.projected_away_corners,
                "actual_away_corners": actual_away_corners,
                "corner_error": abs(
                    (projection.projected_home_corners + projection.projected_away_corners)
                    - (actual_home_corners + actual_away_corners)
                ),
            }
        )

    frame = pd.DataFrame(rows)
    if frame.empty:
        print("no usable matches")
        return 1

    # "model_result_probability" is the probability the model assigned to
    # whatever actually happened -- a well-calibrated model should average
    # noticeably above the base rate for that outcome (~43% home / 25% draw
    # / 32% away long-run), since it's conditioning on real match state.
    print(frame[["match", "score_at_cutoff", "actual_final_score", "actual_result", "model_result_probability"]].to_string(index=False))
    print()
    print(f"matches: {len(frame)}")
    print(f"mean probability assigned to the actual result: {frame['model_result_probability'].mean():.4f}")
    print(f"mean total-goals error (predicted vs actual): {frame['total_error'].mean():.4f}")
    print(f"mean corners error (predicted vs actual):     {frame['corner_error'].mean():.4f}")
    btts_brier = ((frame["predicted_btts"] - frame["actual_btts"].astype(float)) ** 2).mean()
    over_brier = ((frame["predicted_over_2_5"] - frame["actual_over_2_5"].astype(float)) ** 2).mean()
    print(f"BTTS Brier score (lower is better, 0.25 = uninformative coinflip): {btts_brier:.4f}")
    print(f"Over 2.5 Brier score (lower is better):                           {over_brier:.4f}")

    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(frame.to_csv(index=False), encoding="utf-8")
        print(f"wrote {out_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--league", type=str, default="epl")
    parser.add_argument("--matches", type=int, default=60)
    parser.add_argument("--cutoff-minute", type=int, default=60)
    parser.add_argument("--simulations", type=int, default=150)
    parser.add_argument("--out", type=str, default=None)
    args = parser.parse_args()
    return run_backtest(
        args.league,
        max_matches=args.matches,
        cutoff_minute=args.cutoff_minute,
        simulations=args.simulations,
        out_path=Path(args.out) if args.out else None,
    )


if __name__ == "__main__":
    raise SystemExit(main())
