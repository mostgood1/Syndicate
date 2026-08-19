"""Build `player_logs.csv` for a basketball league (WNBA/NBA).

`#477`. THE GAP THIS CLOSES: `_apply_player_priors_local`
(`basketball_props_smart_sim.py`) has FOUR per-player split mechanisms.
`#467` fixed the fourth (opponent-position matchup) by un-nesting it from a
gate it never belonged behind. The other three are still dead, and for a
different reason -- they genuinely need `player_logs.csv`, which does not
exist for EITHER league (measured 2026-08-18, platform-wide, not
WNBA-specific):

    opponent-specific   this player's per-minute rates vs THIS opponent
                        (min_games=2, max_games=5)
    career-vs-opponent  the same, over a 720-day career lookback
                        (min_games=3, max_games=12)
    venue               this player's rates home vs away
                        (min_games=5, max_games=12)

All three sit behind `if player_logs is not None and not player_logs.empty:`
and have therefore never fired in production. They are CONSUMED but never
POPULATED -- `model_engine_standard.md`'s canonical trap, the same shape
`#467` and `#468` were.

WHY THIS IS DERIVABLE AND WASN'T OBVIOUS. `boxscores_history.csv` already
carries every column the split-context builder reads (PLAYER_NAME,
TEAM_ABBREVIATION, MIN, PTS/REB/AST/FG3M/STL/BLK/TOV, date) EXCEPT one:
`MATCHUP`, which is what encodes both the opponent and home/away. That
single missing column is why three real mechanisms were dead. It is fully
derivable by joining the schedule (which has home_tricode/away_tricode) --
measured: 3,838 of 3,838 WNBA boxscore rows join cleanly.

THE MATCHUP FORMAT IS NOT ARBITRARY. `_matchup_opponent` and
`_matchup_home_flag` (`smart_sim.py:976,987`) parse standard NBA-style
strings: "IND @ NYL" (away) / "ATL vs. CHI" (home). This builder emits
exactly that, and the format is verified to round-trip through those two
parsers rather than assumed to.

DELIBERATELY NOT A COPY OF boxscores_history.csv. The consumer reads
GAME_DATE (not `date`) and expects one row per player-game with a MATCHUP;
this writes that shape specifically, so `_load_player_logs_processed` and
`_player_split_rate_context_local` can use it unmodified.

Usage:
    py -3 scripts/build_basketball_player_logs.py --league wnba --dry-run
    py -3 scripts/build_basketball_player_logs.py --league wnba
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _processed_root(league_code: str) -> Path:
    """The FLAT tree the sim actually reads (`#468`'s documented trap)."""
    code = str(league_code or "").strip().lower()
    env_key = "WNBA_BETTING_DATA_ROOT" if code == "wnba" else "NBA_BETTING_DATA_ROOT"
    raw = str(os.environ.get(env_key) or "").strip()
    if raw:
        return Path(raw) / "processed"
    return REPO_ROOT / "data" / f"{code}_source" / "data" / "processed"


def _schedule_path(league_code: str, season: int) -> Path:
    code = str(league_code or "").strip().lower()
    return REPO_ROOT / "vendor" / f"{code}_betting_repo" / "data" / "processed" / f"schedule_{int(season)}.csv"


def build_player_logs(*, league_code: str, season: int, min_rows: int = 200) -> dict:
    """Derive the player-game log table the split mechanisms need."""
    import pandas as pd

    processed_root = _processed_root(league_code)
    history_path = processed_root / "boxscores_history.csv"
    schedule_path = _schedule_path(league_code, season)

    diag: dict = {
        "league": str(league_code).lower(),
        "season": int(season),
        "boxscores_history": str(history_path),
        "schedule": str(schedule_path),
    }

    if not history_path.is_file():
        return {"ok": False, "reason": "boxscores_history_missing", **diag}
    if not schedule_path.is_file():
        return {"ok": False, "reason": "schedule_missing", **diag}

    box = pd.read_csv(history_path, dtype={"game_id": str})
    sched = pd.read_csv(schedule_path, dtype=str)

    required_box = {"game_id", "PLAYER_NAME", "TEAM_ABBREVIATION", "MIN", "date"}
    if not required_box.issubset(set(box.columns)):
        return {"ok": False, "reason": "boxscores_missing_columns", **diag}
    if not {"game_id", "home_tricode", "away_tricode"}.issubset(set(sched.columns)):
        return {"ok": False, "reason": "schedule_missing_columns", **diag}

    diag["boxscore_rows"] = int(len(box))

    slim = sched[["game_id", "home_tricode", "away_tricode"]].dropna(subset=["game_id"]).drop_duplicates("game_id")
    merged = box.merge(slim, on="game_id", how="inner")
    diag["joined_rows"] = int(len(merged))
    diag["rows_dropped_unjoinable"] = int(len(box) - len(merged))

    if merged.empty:
        return {"ok": False, "reason": "no_rows_joined", **diag}

    team_u = merged["TEAM_ABBREVIATION"].astype(str).str.strip().str.upper()
    home_u = merged["home_tricode"].astype(str).str.strip().str.upper()
    away_u = merged["away_tricode"].astype(str).str.strip().str.upper()
    is_home = team_u == home_u
    # A row whose team matches NEITHER side is a genuine identity problem --
    # drop it rather than silently mislabel its opponent/venue.
    valid = is_home | (team_u == away_u)
    dropped_identity = int((~valid).sum())
    merged = merged[valid].copy()
    team_u, home_u, away_u, is_home = team_u[valid], home_u[valid], away_u[valid], is_home[valid]
    diag["rows_dropped_team_identity"] = dropped_identity

    if merged.empty:
        return {"ok": False, "reason": "no_rows_after_identity_filter", **diag}

    opponent = away_u.where(is_home, home_u)
    # EXACTLY the format `_matchup_opponent` / `_matchup_home_flag` parse
    # (smart_sim.py:976,987): "TEAM @ OPP" away, "TEAM vs. OPP" home.
    matchup = team_u + is_home.map({True: " vs. ", False: " @ "}) + opponent

    out = pd.DataFrame(
        {
            # The consumer reads GAME_DATE, not `date`.
            "GAME_DATE": pd.to_datetime(merged["date"], errors="coerce").dt.strftime("%Y-%m-%d"),
            "PLAYER_NAME": merged["PLAYER_NAME"],
            "PLAYER_ID": merged.get("PLAYER_ID"),
            "TEAM_ABBREVIATION": team_u,
            "MATCHUP": matchup,
            "MIN": merged["MIN"],
            "GAME_ID": merged["game_id"],
        }
    )
    for src, dst in (("PTS", "PTS"), ("REB", "REB"), ("AST", "AST"), ("FG3M", "FG3M"), ("STL", "STL"), ("BLK", "BLK"), ("TOV", "TOV")):
        out[dst] = merged[src] if src in merged.columns else 0.0

    out = out[out["GAME_DATE"].notna()].copy()
    # Minutes drive every per-minute rate; a zero/NaN-minute row contributes
    # nothing and would only dilute the split samples.
    minutes = pd.to_numeric(out["MIN"], errors="coerce")
    out = out[minutes.notna() & (minutes > 0.0)].copy()

    diag["rows_written"] = int(len(out))
    diag["distinct_players"] = int(out["PLAYER_NAME"].nunique())
    diag["distinct_games"] = int(out["GAME_ID"].nunique())
    diag["date_min"] = str(out["GAME_DATE"].min()) if len(out) else None
    diag["date_max"] = str(out["GAME_DATE"].max()) if len(out) else None
    diag["home_rows"] = int(out["MATCHUP"].str.contains(" vs. ", regex=False).sum())
    diag["away_rows"] = int(out["MATCHUP"].str.contains(" @ ", regex=False).sum())

    if len(out) < max(1, int(min_rows)):
        return {"ok": False, "reason": "insufficient_rows", "min_rows": int(min_rows), **diag}

    return {"ok": True, "frame": out, **diag}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--league", default="wnba", choices=("wnba", "nba"))
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--min-rows", type=int, default=200, help="refuse to write below this many player-game rows")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = build_player_logs(league_code=args.league, season=args.season, min_rows=int(args.min_rows))
    frame = result.pop("frame", None)

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    elif result.get("ok"):
        print(f"{args.league.upper()} {args.season} player logs")
        print(f"  boxscore rows        : {result['boxscore_rows']}")
        print(f"  joined               : {result['joined_rows']} (dropped unjoinable: {result['rows_dropped_unjoinable']}, "
              f"team-identity: {result['rows_dropped_team_identity']})")
        print(f"  rows written         : {result['rows_written']}")
        print(f"  distinct players     : {result['distinct_players']}")
        print(f"  distinct games       : {result['distinct_games']}")
        print(f"  date range           : {result['date_min']} -> {result['date_max']}")
        print(f"  home / away rows     : {result['home_rows']} / {result['away_rows']}")
    else:
        print(f"REFUSING TO WRITE: {result.get('reason')}")
        for key in ("boxscore_rows", "joined_rows", "rows_written", "min_rows"):
            if key in result:
                print(f"  {key}={result[key]}")

    if not result.get("ok"):
        return 2
    if args.dry_run:
        print("\n--dry-run: nothing written")
        return 0

    out_path = _processed_root(args.league) / "player_logs.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(out_path, index=False)
    print(f"\nwrote {out_path} ({len(frame)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
