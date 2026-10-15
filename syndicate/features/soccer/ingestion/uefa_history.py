"""UEFA club-competition RESULTS history from ESPN, for Stage 1 of the UEFA work (todo #699).

WHY THIS EXISTS. Every soccer rating here is fit per domestic league, so a UEFA fixture
mixes two scales and clubs from leagues we do not carry have no rating at all. Stage 1
needs (a) results for those clubs and (b) cross-league matches to measure league offsets.
Neither football-data.co.uk nor anything else this repo ingests carries UEFA competitions.

THE REQUEST SHAPE, measured 2026-10-15 (findings_2026-10-15_uefa_kalshi_join_and_history.md):
`scoreboard?dates=YYYY&limit=1000` returns a whole CALENDAR year of one competition in one
call (UCL 2024: 137 of 137 completed), back to at least 2010. The `YYYYMMDD-YYYYMMDD`
range form is refused with HTTP 400. A calendar year spans two SEASONS, so rows are
regrouped by season start year (July onward = that year's season).

QUALIFIERS live under separate `<slug>_qual` slugs from 2020; before 2020 they sit inside
the main slug. Both are fetched; `stage` records which slug a row came from.

TEAM IDS ARE KEPT. Placing a club in a domestic league (for the league offsets) goes by
ESPN team id, because names differ across feeds. `espn_lineups.fetch_events` drops the ids,
which is why this does not reuse it.

RESULTS ONLY. Team box stats (shots, corners) need one `summary` call per match
(~2,500 for 2021-25); that is a separate, opt-in step, not this one.
"""

from __future__ import annotations

import csv
import io
import os
import time
from datetime import date
from pathlib import Path
from typing import Any, Callable, Iterable

import requests

from syndicate.features.soccer.ingestion.espn_lineups import LEAGUE_ESPN_SLUGS
from syndicate.features.soccer.ingestion.espn_lineups import _ESPN_BASE
from syndicate.features.soccer.ingestion.espn_lineups import unplayed_post_status
from syndicate.features.soccer.sources import UEFA_COMPETITIONS

COLUMNS = (
    "season", "date", "event_id", "competition", "stage", "espn_slug",
    "home_team", "home_team_id", "away_team", "away_team_id", "home_score", "away_score",
)


def season_of(iso_date: str) -> int:
    """European season start year: July onward belongs to that year's season."""
    day = date.fromisoformat(str(iso_date)[:10])
    return day.year if day.month >= 7 else day.year - 1


def slugs_for(competition: str) -> list[tuple[str, str]]:
    """[(stage, espn_slug)] for one competition: the main draw, then its qualifiers."""
    comp = str(competition).strip().lower()
    if comp not in UEFA_COMPETITIONS:
        raise ValueError(f"{competition!r} is not a UEFA competition ({UEFA_COMPETITIONS})")
    main = LEAGUE_ESPN_SLUGS[comp]
    return [("main", main), ("qualifying", f"{main}_qual")]


def fetch_year(espn_slug: str, year: int, *, timeout: int = 30,
               get: Callable[..., Any] = requests.get) -> dict[str, Any]:
    """One calendar year of one ESPN slug. 404 or a refused slug-year is an EMPTY year, not an error."""
    response = get(f"{_ESPN_BASE}/{espn_slug}/scoreboard",
                   params={"dates": str(int(year)), "limit": 1000}, timeout=timeout)
    if response.status_code in (400, 404):
        return {"events": []}
    response.raise_for_status()
    return response.json()


def completed_rows(payload: dict[str, Any], *, competition: str, stage: str, espn_slug: str) -> list[dict[str, Any]]:
    """Completed, actually-played matches only. Postponed/abandoned (`unplayed_post_status`) are dropped."""
    rows = []
    for event in payload.get("events") or []:
        comp = (event.get("competitions") or [{}])[0]
        status = (comp.get("status") or {}).get("type") or {}
        if not status.get("completed") or unplayed_post_status(status):
            continue
        sides = {c.get("homeAway"): c for c in comp.get("competitors") or []}
        home, away = sides.get("home") or {}, sides.get("away") or {}
        event_id, when = str(event.get("id") or ""), str(event.get("date") or "")
        if not event_id or not when or not home or not away:
            continue
        try:
            home_score, away_score = int(home.get("score")), int(away.get("score"))
        except (TypeError, ValueError):
            continue
        rows.append({
            "season": season_of(when), "date": when, "event_id": event_id,
            "competition": competition, "stage": stage, "espn_slug": espn_slug,
            "home_team": (home.get("team") or {}).get("displayName") or "",
            "home_team_id": str((home.get("team") or {}).get("id") or ""),
            "away_team": (away.get("team") or {}).get("displayName") or "",
            "away_team_id": str((away.get("team") or {}).get("id") or ""),
            "home_score": home_score, "away_score": away_score,
        })
    return rows


def collect(competition: str, seasons: Iterable[int], *, pause_seconds: float = 0.3,
            fetch: Callable[[str, int], dict[str, Any]] = fetch_year) -> dict[int, list[dict[str, Any]]]:
    """{season: rows} for the requested seasons, deduplicated by event_id across years and slugs.

    Season S spans calendar years S and S+1, so both are fetched for every season asked for.
    """
    wanted = sorted({int(s) for s in seasons})
    years = sorted({y for s in wanted for y in (s, s + 1)})
    by_event: dict[str, dict[str, Any]] = {}
    for stage, slug in slugs_for(competition):
        for year in years:
            for row in completed_rows(fetch(slug, year), competition=competition, stage=stage, espn_slug=slug):
                by_event.setdefault(row["event_id"], row)
            if pause_seconds:
                time.sleep(pause_seconds)
    out: dict[int, list[dict[str, Any]]] = {s: [] for s in wanted}
    for row in by_event.values():
        if row["season"] in out:
            out[row["season"]].append(row)
    for rows in out.values():
        rows.sort(key=lambda r: (r["date"], r["event_id"]))
    return out


def history_path(out_root: Path, competition: str, season: int) -> Path:
    return Path(out_root) / competition / "history" / f"uefa_results_{int(season)}.csv"


def write_season(out_root: Path, competition: str, season: int, rows: list[dict[str, Any]]) -> Path:
    """Atomic: the CSV is built in memory, written to a temp file, then renamed over the target.

    Never `open(target, "w")` before the content exists -- a raise in between leaves an
    EMPTY file with no error naming it (learnings.md 2026-09-16, repeated 2026-10-15).
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    payload = buffer.getvalue().encode("utf-8")
    target = history_path(out_root, competition, season)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".csv.tmp")
    tmp.write_bytes(payload)
    os.replace(tmp, target)
    return target
