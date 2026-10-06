"""Keep NBA `player_logs.csv` current with THIS season's REGULAR-season games (lane `nba-season-phase`, user
decision 2026-10-06: "History refresh + guards").

WHY. Measured 2026-10-06 on the fleet: `player_logs.csv` ends 2026-04-12 and nothing refreshes it. The props refresh's
gate (`refresh_nba_oddsapi_props._ensure_player_logs_for_props_refresh`) returns True once the file EXISTS, and no
scheduled job fetches NBA logs. From opening night (2026-10-20) every NBA input -- sim minutes priors, props
features, calibration rates, rosters -- would run on frozen 2025-26 history.

WHAT. `refresh_player_logs` fetches stats.nba `LeagueGameLog(season, "Regular Season")` -- the same call the vendor
`fetch-player-logs` makes (`vendor/.../player_logs.py:_fetch_season_player_logs`) -- for the season containing the
slate. It replaces that season's rows in `player_logs.csv` and KEEPS every other season (the calibration's
prior-season rates read the previous season from the same file). Rows whose GAME_ID is not a regular-season id
(`002...`) are dropped, so the file stays phase-pure.

It does NOT use the vendor `fetch_player_logs`, whose fallback rewrites player_logs from the all-phase ESPN
boxscores_history (`player_logs.py:293-298`). An empty fetch -- every day before opening night -- writes nothing.
Throttled by a marker file (default every 6 h). Atomic write. Never raises; returns what it did.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional

FILE = "player_logs.csv"
MARKER = ".nba_history_refresh.json"
REQUIRED = ("SEASON_ID", "PLAYER_ID", "PLAYER_NAME", "TEAM_ABBREVIATION", "GAME_ID", "GAME_DATE", "MIN", "PTS", "REB",
            "AST", "FG3M", "STL", "BLK", "TOV")


def current_season(date_str: str) -> str:
    """stats.nba season string for a slate: 2026-10-20 -> '2026-27', 2027-02-01 -> '2026-27'."""
    y, m = int(str(date_str)[:4]), int(str(date_str)[5:7])
    start = y if m >= 7 else y - 1
    return f"{start}-{str(start + 1)[-2:]}"


def _vendor_fetch() -> Callable[[str], Any]:
    try:
        from nba_betting import player_logs as pl  # type: ignore
    except Exception:  # noqa: BLE001
        src = Path(__file__).resolve().parents[3] / "vendor" / "nba_betting_repo" / "src"
        if str(src) not in sys.path:
            sys.path.insert(0, str(src))
        from nba_betting import player_logs as pl  # type: ignore
    return lambda season: pl._fetch_season_player_logs(season, max_attempts=2)


def _due(marker: Path, now: datetime, min_interval_hours: float) -> bool:
    try:
        last = datetime.fromisoformat(json.loads(marker.read_text(encoding="utf-8"))["attempted_at"])
        return (now - last).total_seconds() >= min_interval_hours * 3600.0
    except Exception:  # noqa: BLE001
        return True


def refresh_player_logs(processed_root: Path, date_str: str, *, min_interval_hours: float = 6.0,
                        fetch: Optional[Callable[[str], Any]] = None, now: Optional[datetime] = None,
                        force: bool = False) -> Dict[str, Any]:
    import pandas as pd

    processed_root = Path(processed_root)
    now = now or datetime.now(timezone.utc)
    season = current_season(date_str)
    out: Dict[str, Any] = {"date": str(date_str)[:10], "season": season, "wrote": False}
    marker = processed_root / MARKER
    path = processed_root / FILE
    try:
        if not force and not _due(marker, now, min_interval_hours):
            out["skipped"] = f"attempted within {min_interval_hours} h"
            return out
        marker.write_text(json.dumps({"attempted_at": now.isoformat(), "season": season}), encoding="utf-8")
        try:
            fetched = (fetch or _vendor_fetch())(season)
        except Exception as exc:  # noqa: BLE001 -- before opening night stats.nba returns no rows: not an error
            out["reason"] = f"fetch returned nothing: {str(exc)[:160]}"
            return out
        if fetched is None or len(fetched) == 0:
            out["reason"] = "fetch returned 0 rows"
            return out
        fetched = fetched.copy()
        missing = [c for c in REQUIRED if c not in fetched.columns]
        if missing:
            out["reason"] = f"fetched frame lacks {missing}; not written"
            return out
        gid = fetched["GAME_ID"].astype(str).str.zfill(10)
        regular = gid.str.startswith("002")
        out["dropped_non_regular"] = int((~regular).sum())
        fetched = fetched[regular]
        fetched["SEASON"] = season
        if path.is_file():
            old = pd.read_csv(path, low_memory=False, dtype={"GAME_ID": str})
            cols = list(old.columns)
            keep = old[old.get("SEASON", pd.Series("", index=old.index)).astype(str) != season]
        else:
            cols, keep = list(fetched.columns), None
        for c in cols:
            if c not in fetched.columns:
                fetched[c] = pd.NA
        merged = pd.concat([keep, fetched[cols]], ignore_index=True) if keep is not None else fetched[cols]
        merged = merged.sort_values(["GAME_DATE", "GAME_ID", "PLAYER_ID"], kind="stable")
        tmp = path.with_suffix(".csv.tmp")
        merged.to_csv(tmp, index=False)
        os.replace(tmp, path)
        parquet = processed_root / "player_logs.parquet"
        if parquet.exists():  # a stale parquet beside a fresh CSV is what parquet-first readers would read
            try:
                merged.to_parquet(parquet, index=False)
            except Exception as exc:  # noqa: BLE001
                parquet.unlink(missing_ok=True)
                out["parquet"] = f"removed (rewrite failed: {type(exc).__name__})"
        out.update(wrote=True, season_rows=int(len(fetched)), rows_total=int(len(merged)),
                   newest_game_date=str(fetched["GAME_DATE"].max())[:10],
                   other_seasons_kept=int(0 if keep is None else len(keep)))
        return out
    except Exception as exc:  # noqa: BLE001 -- a refresh failure must never break the props refresh
        out["reason"] = f"failed: {type(exc).__name__}: {str(exc)[:160]}"
        return out
    finally:
        print("NBA_PLAYER_LOGS_REFRESH " + json.dumps(out, default=str), flush=True)


RECON_MARKER = ".nba_recon_refresh.json"


def refresh_recon(processed_root: Path, date_str: str, *, lookback_days: int = 3, min_interval_hours: float = 6.0,
                  build: Optional[Callable[..., Dict[str, Any]]] = None, now: Optional[datetime] = None,
                  force: bool = False) -> Dict[str, Any]:
    """Write NBA recon (recon_games / recon_quarters / recon_props) for the `lookback_days` dates before the slate,
    from ESPN, via scripts/build_wnba_recon.build_date(league="nba"): outcome-only, completed games only.

    WHY. Nothing wrote NBA recon after 2026-06-13, so the props bias calibration had no outcomes. Called from the NBA
    props refresh (no restart), throttled. Every phase is written (preseason recon is real data); the calibration
    windows already keep same-phase dates only. Never raises."""
    from datetime import date as _date, timedelta as _timedelta

    processed_root = Path(processed_root)
    now = now or datetime.now(timezone.utc)
    out: Dict[str, Any] = {"date": str(date_str)[:10], "dates": {}}
    marker = processed_root / RECON_MARKER
    try:
        if not force and not _due(marker, now, min_interval_hours):
            out["skipped"] = f"attempted within {min_interval_hours} h"
            return out
        marker.write_text(json.dumps({"attempted_at": now.isoformat()}), encoding="utf-8")
        if build is None:
            repo = Path(__file__).resolve().parents[3]
            if str(repo) not in sys.path:
                sys.path.insert(0, str(repo))
            from scripts.build_wnba_recon import build_date as build  # type: ignore
        data_root = processed_root.parent.parent.parent      # <data_root>/nba_source/data/processed
        anchor = _date.fromisoformat(str(date_str)[:10])
        for back in range(1, int(lookback_days) + 1):
            d = (anchor - _timedelta(days=back)).isoformat()
            try:
                res = build(d, data_root=data_root, league="nba")
                out["dates"][d] = {k: res.get(k) for k in ("status", "games", "props")}
            except Exception as exc:  # noqa: BLE001 -- one bad date must not stop the others
                out["dates"][d] = {"status": f"failed: {type(exc).__name__}"}
        return out
    except Exception as exc:  # noqa: BLE001
        out["reason"] = f"failed: {type(exc).__name__}: {str(exc)[:160]}"
        return out
    finally:
        print("NBA_RECON_REFRESH " + json.dumps(out, default=str), flush=True)
