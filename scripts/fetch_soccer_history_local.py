"""Fetch soccer team/league match history and player per-90 history locally.

Match history: football-data.co.uk season CSVs (big five + Eredivisie,
Primeira Liga, Championship, Belgian Pro League). Player history: Understat
league tables (big five), American Soccer Analysis (MLS), or ESPN
match-summary aggregation (any other league with a LEAGUE_ESPN_SLUGS
entry).

All three emit TRUE per-90 rates over real minutes. The "ESPN gives
season-aggregated appearance rates" caveat this docstring used to carry
describes a version of `espn_player_stats.py` that predates
`compute_minutes_played`; its rows have been tagged `espn_true_per90`
since, and that module's docstring now states the comparison to
Understat/ASA in full.

For an ESPN league, `--espn-date-windows` is OPTIONAL: omitted, the windows
covering the already-played part of the season are derived from the season
calendar. Pass it only to backfill a season other than the current one.

Usage:
    python scripts/fetch_soccer_history_local.py --league epl --kind matches --seasons 2023,2024,2025
    python scripts/fetch_soccer_history_local.py --league epl --kind players --seasons 2025
    python scripts/fetch_soccer_history_local.py --league mls --kind players --seasons 2026
    python scripts/fetch_soccer_history_local.py --league eredivisie --kind players --seasons 2026
    python scripts/fetch_soccer_history_local.py --league eredivisie --kind players --seasons 2025 --espn-date-windows 20250801-20250815,...
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.soccer.ingestion.espn_lineups import LEAGUE_ESPN_SLUGS
from syndicate.features.soccer.ingestion.espn_player_stats import aggregate_season_player_stats
from syndicate.features.soccer.ingestion.espn_player_stats import season_date_windows
from syndicate.features.soccer.ingestion.match_history import LEAGUE_HISTORY_CODES
from syndicate.features.soccer.ingestion.match_history import fetch_match_history_csv
from syndicate.features.soccer.ingestion.match_history import normalize_match_history
from syndicate.features.soccer.ingestion.player_history import UNDERSTAT_LEAGUES
from syndicate.features.soccer.ingestion.player_history import fetch_asa_mls_players
from syndicate.features.soccer.ingestion.player_history import fetch_understat_league_data
from syndicate.features.soccer.ingestion.player_history import fetch_understat_players
from syndicate.features.soccer.ingestion.player_history import normalize_asa_players
from syndicate.features.soccer.ingestion.player_history import normalize_understat_players
from syndicate.features.soccer.ingestion.player_history import normalize_understat_team_history


def _write_csv(rows: list[dict], out_path: Path) -> None:
    """Write `rows` to `out_path`, REFUSING to publish an empty result.

    `pd.DataFrame([]).to_csv(index=False)` is a bare newline -- 3 bytes, no
    header, no columns -- so an empty fetch used to leave a file behind that
    LOOKS written and parses as nothing. Every reader of these CSVs goes through
    `pd.read_csv`, which raises `EmptyDataError: No columns to parse from file`
    on it (measured), so one rate-limited or shape-changed upstream response
    took out the whole league's artifact build, every cycle, until a human
    noticed.

    This was harmless while nothing ever called `--kind players`: the roster
    CSVs were hand-run committed seeds. The producer step in
    `refresh_odds_sources.py` makes it a WEEKLY opportunity, and the failure
    would land on a file that already had good data in it.

    So: fail loudly and leave the previous file alone. The caller is a refresh
    step, which records STEP_FAIL and moves on -- a visible failed step with
    last week's roster still in place, rather than a silent zero-byte file that
    breaks the reader.
    """
    frame = pd.DataFrame(rows)
    if frame.empty:
        existing = ""
        try:
            if out_path.exists():
                existing = f" ({out_path.stat().st_size} bytes already there, KEPT)"
        except OSError:
            pass
        raise SystemExit(
            f"REFUSING to write 0 rows to {out_path}{existing}. An empty frame "
            "serialises to a bare newline with no header, which every reader of "
            "these CSVs hits as pandas EmptyDataError. Treat this as an upstream "
            "fetch failure, not as a season with no players."
        )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp.write_text(frame.to_csv(index=False), encoding="utf-8")
    tmp.replace(out_path)
    print(f"Wrote {len(frame)} rows to {out_path}")


def fetch_matches(league: str, seasons: list[int], out_dir: Path) -> None:
    if league not in LEAGUE_HISTORY_CODES:
        raise SystemExit(f"match history not available for league '{league}' (supported: {sorted(LEAGUE_HISTORY_CODES)})")
    for season in seasons:
        csv_text = fetch_match_history_csv(league, season)
        rows = normalize_match_history(csv_text, league=league, season=season)
        _write_csv(rows, out_dir / f"matches_{season}.csv")


def fetch_players(league: str, seasons: list[int], out_dir: Path, *, espn_date_windows: list[str] | None = None) -> None:
    """Write `players_{season}.csv` for each season, from whichever source
    covers this league.

    THE ESPN BRANCH USED TO BE UNREACHABLE FROM A PRODUCER. It required
    `--espn-date-windows` and raised `SystemExit` without it, so the weekly
    `--kind players` step in `refresh_odds_sources.py` had to exclude
    eredivisie, primeira_liga, championship and belgian_pro_league outright --
    including them would have made every refresh tick a FAILING step. Those
    four leagues therefore ran the sim against a hand-committed
    `players_2025.csv` seed, i.e. the COMPLETED 2025-26 season, with every
    summer-2026 signing and both promoted clubs absent.

    The windows are now DERIVED (`season_date_windows`) when the caller does
    not supply them. They could never have been hard-coded into the step: it
    runs weekly and forever, and a stale literal window list would keep
    producing a correct-looking roster built from the wrong season. An
    explicit `--espn-date-windows` still overrides, for backfilling a season
    that is not the current one.
    """
    for season in seasons:
        if league == "mls":
            raw = fetch_asa_mls_players(season)
            rows = normalize_asa_players(raw, season=season)
        elif league in UNDERSTAT_LEAGUES:
            raw = fetch_understat_players(league, season)
            rows = normalize_understat_players(raw, league=league, season=season)
        elif espn_date_windows:
            rows = aggregate_season_player_stats(league, date_windows=espn_date_windows)
        elif league in LEAGUE_ESPN_SLUGS:
            windows = season_date_windows(league, season)
            if not windows:
                # A real answer, not a failure to compute one: nothing has been
                # played. Still an exit, because a caller that asked for this
                # season's players by name asked for something that cannot
                # exist yet -- the weekly step declines EARLIER, so it never
                # reaches here (`_soccer_players_step`'s season-elapsed gate).
                raise SystemExit(
                    f"season {season} has not started for league '{league}' "
                    "(no completed matches to aggregate); refusing to write an "
                    "empty roster over the previous season's"
                )
            print(
                f"ESPN_PLAYER_WINDOWS league={league} season={season} "
                f"windows={len(windows)} span={windows[0]}..{windows[-1]}",
                flush=True,
            )
            rows = aggregate_season_player_stats(league, date_windows=windows)
        else:
            raise SystemExit(
                f"player history not available for league '{league}': no Understat/ASA "
                f"coverage and no ESPN slug (supported ESPN leagues: {sorted(LEAGUE_ESPN_SLUGS)})"
            )
        _write_csv(rows, out_dir / f"players_{season}.csv")


def fetch_teams(league: str, seasons: list[int], out_dir: Path) -> None:
    if league not in UNDERSTAT_LEAGUES:
        raise SystemExit(f"team xG history not available for league '{league}' (supported: {sorted(UNDERSTAT_LEAGUES)})")
    for season in seasons:
        league_data = fetch_understat_league_data(league, season)
        rows = normalize_understat_team_history(league_data, league=league, season=season)
        _write_csv(rows, out_dir / f"teams_{season}.csv")


_KIND_DIRS = {"matches": "history", "players": "players", "teams": "team_history"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--league", type=str, required=True)
    parser.add_argument("--kind", type=str, choices=("matches", "players", "teams"), required=True)
    parser.add_argument("--seasons", type=str, required=True, help="Comma-separated season start years (e.g. 2024,2025)")
    parser.add_argument("--out-dir", type=str, default=None)
    parser.add_argument(
        "--espn-date-windows",
        type=str,
        default=None,
        help=(
            "Comma-separated YYYYMMDD-YYYYMMDD windows for --kind players on leagues "
            "without Understat/ASA coverage. OPTIONAL: omitted, the windows covering "
            "the already-played part of --seasons are derived from the season calendar. "
            "Pass it to backfill a season other than the current one."
        ),
    )
    args = parser.parse_args()

    league = args.league.strip().lower()
    seasons = [int(season.strip()) for season in args.seasons.split(",") if season.strip()]
    out_dir = Path(args.out_dir) if args.out_dir else REPO_ROOT / "data" / "soccer_source" / league / _KIND_DIRS[args.kind]
    espn_date_windows = [w.strip() for w in args.espn_date_windows.split(",") if w.strip()] if args.espn_date_windows else None

    if args.kind == "matches":
        fetch_matches(league, seasons, out_dir)
    elif args.kind == "teams":
        fetch_teams(league, seasons, out_dir)
    else:
        fetch_players(league, seasons, out_dir, espn_date_windows=espn_date_windows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
