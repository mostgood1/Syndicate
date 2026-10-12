"""Fetch one NBA season's regular-season player game logs from stats.nba (Syndicate-owned).

Lane nba-live-tick-native (2026-10-12, user request "move nba history refresh off vendor"). Verbatim copy of
`_configure_stats_headers` and `_fetch_season_player_logs` from vendor/nba_betting_repo/src/nba_betting/player_logs.py
(sha256 0c95b59753b899d2...). `syndicate/features/shared/nba_history_refresh.py` used to import the vendored package (and put
vendor/nba_betting_repo/src on sys.path) to reach them. Dependencies are nba_api and pandas only.

tests/test_nba_player_logs_fetch.py pins the two functions to the vendored source (AST-equal) and runs both on the
same mocked LeagueGameLog.
"""
from __future__ import annotations

import time

import pandas as pd
from nba_api.stats.endpoints import leaguegamelog
from nba_api.stats.library import http as nba_http


def _configure_stats_headers() -> None:
    try:
        nba_http.STATS_HEADERS.update(
            {
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.9",
                "Origin": "https://www.nba.com",
                "Referer": "https://www.nba.com/stats/",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                "Connection": "keep-alive",
            }
        )
    except Exception:
        pass


def _fetch_season_player_logs(season: str, max_attempts: int = 3) -> pd.DataFrame:
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            _configure_stats_headers()
            res = leaguegamelog.LeagueGameLog(
                season=season,
                season_type_all_star="Regular Season",
                player_or_team_abbreviation="P",
                counter=0,
                timeout=45,
            )

            df = pd.DataFrame()
            try:
                nd = res.get_normalized_dict() or {}
                df = pd.DataFrame(nd.get("LeagueGameLog", []))
            except Exception:
                df = pd.DataFrame()

            if df.empty:
                try:
                    frames = res.get_data_frames() or []
                    if frames:
                        df = frames[0]
                except Exception:
                    df = pd.DataFrame()

            if df is not None and not df.empty:
                out = df.copy()
                out["SEASON"] = season
                return out

            last_error = RuntimeError(f"LeagueGameLog returned no rows for {season}")
        except Exception as exc:
            last_error = exc

        if attempt < max_attempts:
            time.sleep(min(2.0 * attempt, 6.0))

    if last_error is None:
        raise RuntimeError(f"LeagueGameLog failed for {season}")
    raise RuntimeError(f"LeagueGameLog failed for {season}: {last_error}") from last_error
