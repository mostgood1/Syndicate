"""Is a basketball games history (`raw/games_nba_api.csv`) behind the schedule? (lane nba-source-cli-native, 2026-10-13)

THE GAP. Both props refreshes re-fetched the games history only when its newest game was more than 30 days before
the slate (`_games_history_is_stale`). That rule exists to catch a missing or partial file, and it does; but a file
that is merely a few games behind never trips it, so new results waited up to a month. Measured on the fleet
2026-10-13: the WNBA history stopped at 10-02 (last written 10-04) while the schedule listed six final playoff games
on 10-04/10-07/10-09. The game model's features (`build-features`), `predict-date` and the totals calibration all read
that file, so the whole postseason was predicted without its own results.

THE RULE ADDED. Re-fetch when the league's own schedule (`processed/schedule_*.csv`, rewritten by `fetch-schedule`
at the top of the same bootstrap) lists a FINAL game dated after the history's newest game. Season types the
league's fetch never stores are ignored, or they would look permanently missing: preseason and All-Star games for
both leagues, and NBA post-season (its bulk LeagueGameLog fetch is regular season only; the fleet history ends 04-12).
A schedule with no status values counts a game as final once its date is before today (UTC).

Only the most recently written `schedule_*.csv` is read (the one `fetch-schedule` just rewrote).

COOLDOWN. A final game the fetch cannot capture would otherwise trigger a fetch on every run; `due()` marks each
attempt in `processed/.games_history_behind_schedule_attempt.json` and stays quiet for
`REFRESH_GAMES_HISTORY_BEHIND_SCHEDULE_COOLDOWN_MINUTES` (default 360). The 30-day rule is unchanged and not cooled down.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from typing import Any

MARKER_NAME = ".games_history_behind_schedule_attempt.json"
COOLDOWN_ENV = "REFRESH_GAMES_HISTORY_BEHIND_SCHEDULE_COOLDOWN_MINUTES"
DEFAULT_COOLDOWN_MINUTES = 360.0

#: label/slug fragments (lower case) of games each league's history never holds.
NOT_IN_HISTORY = {
    "wnba": ("preseason", "all-star", "all star"),
    "nba": ("preseason", "all-star", "all star", "playoff", "play-in", "post-season", "postseason", "nba cup final"),
}
_FINAL_STATUS = "3"


def _history_newest(history_path: Path) -> str | None:
    import pandas as pd

    try:
        if not history_path.is_file() or history_path.stat().st_size <= 0:
            return None
        newest = pd.to_datetime(pd.read_csv(history_path, usecols=["date"])["date"], errors="coerce").max()
        return None if pd.isna(newest) else newest.date().isoformat()
    except Exception:
        return None


def final_games_after_history(history_path: Path, processed_root: Path, *, league: str, today: dt.date | None = None) -> dict[str, Any]:
    """Final scheduled games dated after the history's newest game. Pure read; no side effects."""
    import pandas as pd

    today = today or dt.datetime.now(dt.timezone.utc).date()
    newest = _history_newest(history_path)
    info: dict[str, Any] = {"newest": newest, "finals_after": 0, "dates": [], "schedules": []}
    if newest is None:
        return info
    skip = NOT_IN_HISTORY.get(str(league).lower(), NOT_IN_HISTORY["wnba"])
    dates: list[str] = []
    # Only the most recently written schedule: `fetch-schedule` rewrites this league's file at the top of the same
    # bootstrap, while older snapshots under other names linger (the WNBA dir holds schedule_2025_26.csv and
    # schedule_2026_27.csv, both stale 2026 WNBA copies, on 2026-10-13).
    candidates = [path for path in Path(processed_root).glob("schedule_*.csv") if path.is_file()]
    for path in sorted(candidates, key=lambda path: path.stat().st_mtime)[-1:]:
        try:
            sched = pd.read_csv(path, dtype=str)
        except Exception:
            continue
        date_col = next((c for c in ("date_est", "date_utc", "date") if c in sched.columns), None)
        if date_col is None:
            continue
        info["schedules"].append(path.name)
        kind = pd.Series("", index=sched.index)
        for col in ("season_type_slug", "game_label", "game_subtype"):
            if col in sched.columns:
                kind = kind + " " + sched[col].fillna("").astype(str).str.lower()
        keep = ~kind.apply(lambda text: any(token in text for token in skip))
        day = pd.to_datetime(sched[date_col], errors="coerce").dt.date
        status = sched["game_status"].fillna("").astype(str).str.strip() if "game_status" in sched.columns else pd.Series("", index=sched.index)
        if (status != "").any():
            final = status == _FINAL_STATUS
        else:
            final = day.apply(lambda d: d is not None and not pd.isna(d) and d < today)
        newest_day = dt.date.fromisoformat(newest)
        after = day.apply(lambda d: d is not None and not pd.isna(d) and d > newest_day)
        dates += [d.isoformat() for d in day[keep & final & after]]
    info["finals_after"] = len(dates)
    info["dates"] = sorted(set(dates))
    return info


def _cooldown_minutes() -> float:
    try:
        return max(0.0, float(os.environ.get(COOLDOWN_ENV) or DEFAULT_COOLDOWN_MINUTES))
    except Exception:
        return DEFAULT_COOLDOWN_MINUTES


def due(history_path: Path, processed_root: Path, *, league: str, now: dt.datetime | None = None) -> dict[str, Any] | None:
    """The reason to re-fetch now (and records the attempt), or None: not behind, or behind but inside the cooldown."""
    now = now or dt.datetime.now(dt.timezone.utc)
    info = final_games_after_history(history_path, processed_root, league=league, today=now.date())
    if not info["finals_after"]:
        return None
    marker = Path(processed_root) / MARKER_NAME
    try:
        last = dt.datetime.fromisoformat(json.loads(marker.read_text(encoding="utf-8"))["attempted_at"])
        if (now - last).total_seconds() < _cooldown_minutes() * 60.0:
            return None
    except Exception:
        pass
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps({"attempted_at": now.isoformat(), "newest": info["newest"], "dates": info["dates"]}), encoding="utf-8")
    except Exception:
        pass
    return {"newest": info["newest"], "finals_after": info["finals_after"], "dates": info["dates"]}
