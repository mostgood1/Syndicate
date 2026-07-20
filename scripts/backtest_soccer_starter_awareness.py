"""Real, non-heuristic validation of starter-aware props allocation.

The earlier validation (``validate_soccer_vs_market.py props --starter-mode
top_minutes``) tested a *heuristic* stand-in for a real lineup (top-11 by
season minutes) because the live props fixtures were too far out for any
real lineup to exist yet, and found the heuristic hurt accuracy. This
script instead uses ESPN's confirmed starter flag for *already-completed*
matches -- genuine ground truth, not a proxy -- and checks a narrower,
cleaner question than the props-vs-market test: given the team's *actual*
observed shot volume in a match, does knowing the real starting XI predict
*which players* got that volume better than season-long usage rates alone?

Using the actual team shot total (not a simulated one) isolates the
allocation question from the separate "how many shots will this team get"
question, which the truth-calibration passes already cover.

Usage:
    python scripts/backtest_soccer_starter_awareness.py --league mls --matches 60
"""

from __future__ import annotations

import argparse
import sys
import unicodedata
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.soccer.features.team_names import match_team_name
from syndicate.features.soccer.ingestion.espn_lineups import extract_match_player_rows
from syndicate.features.soccer.ingestion.espn_lineups import fetch_completed_events
from syndicate.features.soccer.ingestion.espn_lineups import fetch_match_summary
from syndicate.features.soccer.sim_engine.soccersim.player_props import build_usage_profiles

# ESPN scoreboard date-range queries silently cap around ~100 events, so
# each league's season is paged in monthly windows. MLS runs Feb-Nov; the
# big-five European leagues ran Aug 2025-May 2026 for the season this
# session's Understat/football-data pulls cover (2025 season-start-year).
_LEAGUE_SEASON_WINDOWS = {
    "mls": [
        "20260201-20260228",
        "20260301-20260331",
        "20260401-20260430",
        "20260501-20260531",
        "20260601-20260630",
        "20260701-20260731",
    ],
    "epl": [
        "20250801-20250831",
        "20250901-20250930",
        "20251001-20251031",
        "20251101-20251130",
        "20251201-20251231",
        "20260101-20260131",
        "20260201-20260228",
        "20260301-20260331",
        "20260401-20260430",
        "20260501-20260531",
    ],
    "la_liga": [
        "20250801-20250831",
        "20250901-20250930",
        "20251001-20251031",
        "20251101-20251130",
        "20251201-20251231",
        "20260101-20260131",
        "20260201-20260228",
        "20260301-20260331",
        "20260401-20260430",
        "20260501-20260531",
    ],
    "bundesliga": [
        "20250801-20250831",
        "20250901-20250930",
        "20251001-20251031",
        "20251101-20251130",
        "20251201-20251231",
        "20260101-20260131",
        "20260201-20260228",
        "20260301-20260331",
        "20260401-20260430",
        "20260501-20260531",
    ],
    "serie_a": [
        "20250801-20250831",
        "20250901-20250930",
        "20251001-20251031",
        "20251101-20251130",
        "20251201-20251231",
        "20260101-20260131",
        "20260201-20260228",
        "20260301-20260331",
        "20260401-20260430",
        "20260501-20260531",
    ],
    "ligue_1": [
        "20250801-20250831",
        "20250901-20250930",
        "20251001-20251031",
        "20251101-20251130",
        "20251201-20251231",
        "20260101-20260131",
        "20260201-20260228",
        "20260301-20260331",
        "20260401-20260430",
        "20260501-20260531",
    ],
    "eredivisie": [
        "20250801-20250831",
        "20250901-20250930",
        "20251001-20251031",
        "20251101-20251130",
        "20251201-20251231",
        "20260101-20260131",
        "20260201-20260228",
        "20260301-20260331",
        "20260401-20260430",
        "20260501-20260531",
    ],
    "primeira_liga": [
        "20250801-20250831",
        "20250901-20250930",
        "20251001-20251031",
        "20251101-20251130",
        "20251201-20251231",
        "20260101-20260131",
        "20260201-20260228",
        "20260301-20260331",
        "20260401-20260430",
        "20260501-20260531",
    ],
    "championship": [
        "20250801-20250831",
        "20250901-20250930",
        "20251001-20251031",
        "20251101-20251130",
        "20251201-20251231",
        "20260101-20260131",
        "20260201-20260228",
        "20260301-20260331",
        "20260401-20260430",
        "20260501-20260531",
    ],
    "belgian_pro_league": [
        "20250801-20250831",
        "20250901-20250930",
        "20251001-20251031",
        "20251101-20251130",
        "20251201-20251231",
        "20260101-20260131",
        "20260201-20260228",
        "20260301-20260331",
        "20260401-20260430",
        "20260501-20260531",
    ],
}


def _norm_name(name: str) -> str:
    text = unicodedata.normalize("NFKD", str(name or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.lower().replace(".", " ").replace("-", " ").split())


def _predicted_shares(rows: list[dict[str, Any]], *, side: str, team: str, starters: set[str] | None) -> dict[str, float]:
    profiles = build_usage_profiles(rows, side=side, team=team, starters=starters)
    return {_norm_name(profile.player_name): profile.shot_share for profile in profiles}


def run_backtest(league: str, *, max_matches: int, min_team_shots: int, out_path: Path | None) -> int:
    if league not in _LEAGUE_SEASON_WINDOWS:
        raise SystemExit(f"no season window configured for league '{league}' (have: {sorted(_LEAGUE_SEASON_WINDOWS)})")

    completed = fetch_completed_events(league, date_windows=_LEAGUE_SEASON_WINDOWS[league])
    print(f"{len(completed)} completed {league} matches available")
    completed = sorted(completed, key=lambda row: row["date"])
    # Evenly sample across the season rather than just the earliest matches,
    # so squad/form drift over the year doesn't bias the sample.
    if len(completed) > max_matches:
        step = len(completed) / max_matches
        completed = [completed[int(i * step)] for i in range(max_matches)]
    print(f"backtesting {len(completed)} matches")

    players_dir = REPO_ROOT / "data" / "soccer_source" / league / "players"
    player_frames = [pd.read_csv(path) for path in sorted(players_dir.glob("players_*.csv"))]
    if not player_frames:
        raise SystemExit(f"no player history under {players_dir}; run fetch_soccer_history_local.py --kind players first")
    all_player_rows = pd.concat(player_frames, ignore_index=True).to_dict("records")
    rows_by_team: dict[str, list[dict[str, Any]]] = {}
    for row in all_player_rows:
        rows_by_team.setdefault(str(row.get("team") or ""), []).append(row)
    team_names = list(rows_by_team)

    per_player_rows: list[dict[str, Any]] = []
    matches_used = 0
    for event in completed:
        try:
            summary = fetch_match_summary(league, event["event_id"])
        except Exception as exc:
            print(f"skip {event['event_id']}: fetch failed ({exc})")
            continue
        match_rows = extract_match_player_rows(summary, event_id=event["event_id"])
        if not match_rows:
            continue

        used_this_match = False
        for side in ("home", "away"):
            side_rows = [row for row in match_rows if row["side"] == side]
            outfield_rows = [row for row in side_rows if not row["is_goalkeeper"]]
            team_total_shots = sum(row["total_shots"] for row in outfield_rows)
            if team_total_shots < min_team_shots:
                continue
            espn_team = str(side_rows[0]["team"]) if side_rows else ""
            asa_team = match_team_name(espn_team, team_names)
            if asa_team is None:
                continue
            season_rows = rows_by_team[asa_team]
            starter_names = {_norm_name(row["player_name"]) for row in side_rows if row["starter"]}
            # build_usage_profiles/player_row_key key by player_id when a row
            # has one (ASA rows always do), falling back to a name-based key
            # only when it's absent -- so the starters set must use each
            # season row's own player_id, matched to ESPN's real starter
            # flag by normalized name (ESPN and ASA use different id spaces).
            starters_by_key = {
                str(row.get("player_id"))
                for row in season_rows
                if _norm_name(row.get("player_name")) in starter_names
            }
            if len(starters_by_key) < 7:
                continue  # too few season-data matches to trust this side

            baseline_shares = _predicted_shares(season_rows, side=side, team=asa_team, starters=None)
            lineup_shares = _predicted_shares(season_rows, side=side, team=asa_team, starters=starters_by_key)

            for row in outfield_rows:
                key = _norm_name(row["player_name"])
                if key not in baseline_shares:
                    continue
                actual_share = row["total_shots"] / team_total_shots if team_total_shots else 0.0
                per_player_rows.append(
                    {
                        "event_id": event["event_id"],
                        "team": asa_team,
                        "player": row["player_name"],
                        "was_starter": row["starter"],
                        "actual_shots": row["total_shots"],
                        "actual_share": actual_share,
                        "baseline_predicted_share": baseline_shares.get(key, 0.0),
                        "lineup_predicted_share": lineup_shares.get(key, 0.0),
                    }
                )
            used_this_match = True
        if used_this_match:
            matches_used += 1

    frame = pd.DataFrame(per_player_rows)
    if frame.empty:
        print("no matches produced comparable rows (name matching or data coverage issue)")
        return 1

    frame["baseline_error"] = (frame["baseline_predicted_share"] - frame["actual_share"]).abs()
    frame["lineup_error"] = (frame["lineup_predicted_share"] - frame["actual_share"]).abs()

    baseline_mae = frame["baseline_error"].mean()
    lineup_mae = frame["lineup_error"].mean()
    baseline_corr = frame["baseline_predicted_share"].corr(frame["actual_share"])
    lineup_corr = frame["lineup_predicted_share"].corr(frame["actual_share"])
    baseline_spearman = frame["baseline_predicted_share"].corr(frame["actual_share"], method="spearman")
    lineup_spearman = frame["lineup_predicted_share"].corr(frame["actual_share"], method="spearman")
    improved_rows = (frame["lineup_error"] < frame["baseline_error"]).sum()

    print(f"\nmatches with usable data: {matches_used}  player-rows compared: {len(frame)}")
    print(f"MAE (predicted shot share vs actual)  -- baseline (season-only): {baseline_mae:.4f}")
    print(f"MAE (predicted shot share vs actual)  -- lineup-aware (real):    {lineup_mae:.4f}")
    print(f"Pearson  -- baseline: {baseline_corr:.4f}   lineup-aware: {lineup_corr:.4f}")
    print(f"Spearman -- baseline: {baseline_spearman:.4f}   lineup-aware: {lineup_spearman:.4f}")
    print(f"lineup-aware improved {improved_rows}/{len(frame)} player-rows ({improved_rows / len(frame) * 100:.1f}%)")

    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(frame.to_csv(index=False), encoding="utf-8")
        print(f"wrote {out_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--league", type=str, default="mls")
    parser.add_argument("--matches", type=int, default=60)
    parser.add_argument("--min-team-shots", type=int, default=6)
    parser.add_argument("--out", type=str, default=None)
    args = parser.parse_args()
    return run_backtest(args.league, max_matches=args.matches, min_team_shots=args.min_team_shots, out_path=Path(args.out) if args.out else None)


if __name__ == "__main__":
    raise SystemExit(main())
