"""NHL confirmed starting goalies: overlay Daily Faceoff's CONFIRMED starters onto `starting_goalies_<date>.csv`.
Lane `nhl-confirmed-goalies` (user: "wire confirmed starting goalies into the lineups").

WHY. The collector (`ingestion/collect.py`, source `hockeysim_toi`) PROJECTS each team's starter from usage. Daily
Faceoff publishes the starter with a status (Confirmed / Likely / Unconfirmed ...) and the time it was posted, and a
Confirmed starter posted before puck drop was right 1,624 / 1,625 times on 2025-26 (lane `nhl-game-lines-model`).
The starter drives the SAVES prop and the opposing skaters' scoring environment in the props sim.

WHAT. After the collector writes `lineups_<date>.csv` and `starting_goalies_<date>.csv`, `overlay` replaces a team's
starter row ONLY when ALL hold:
  * Daily Faceoff's status for that side is Confirmed;
  * it was posted before the game's scheduled start (and is not in the future);
  * the name maps to exactly ONE goalie the collector dressed for that team in `lineups_<date>.csv`.
The row then reads `goalie=<the lineup's own full_name>`, `status=confirmed`, `confidence=0.95`,
`source=dailyfaceoff`. Every other team keeps the collector's projection, unchanged. The loader matches the starter
by the lineup's own name (`loaders.load_starting_goalies` -> `is_starting_goalie`), so nothing else changes.

SOURCE. `https://www.dailyfaceoff.com/starting-goalies/<YYYY-MM-DD>`: robots.txt `Allow: /` (only `/api/` and
`/cms/` disallowed); the server-rendered `__NEXT_DATA__` JSON; one request per date per generation, browser UA.
Off switch: SYNDICATE_NHL_CONFIRMED_GOALIES=off. NEVER RAISES: on any failure the collector's file stands.
"""
from __future__ import annotations

import csv
import json
import os
import re
import tempfile
import unicodedata
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

URL = "https://www.dailyfaceoff.com/starting-goalies/{date}"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
ENV = "SYNDICATE_NHL_CONFIRMED_GOALIES"
_NEXT = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_GOALIE_COLUMNS = ["team", "goalie", "status", "confidence", "source"]

FetchHtml = Callable[[str], Optional[str]]


def enabled(env: Optional[Dict[str, str]] = None) -> bool:
    raw = str((env if env is not None else os.environ).get(ENV) or "").strip().lower()
    return raw not in {"0", "off", "false", "no"}


def parse_page(html: str) -> Optional[List[Dict[str, Any]]]:
    """Per-game starter records from the page's `__NEXT_DATA__`; None when the data block is missing (a layout
    change must read as an error, never as 'no games')."""
    m = _NEXT.search(html or "")
    if not m:
        return None
    try:
        data = ((json.loads(m.group(1)).get("props") or {}).get("pageProps") or {}).get("data")
    except ValueError:
        return None
    if not isinstance(data, list):
        return None
    return [{
        "home_team": g.get("homeTeamName"), "away_team": g.get("awayTeamName"),
        "home_goalie": g.get("homeGoalieName"), "away_goalie": g.get("awayGoalieName"),
        "home_status": g.get("homeNewsStrengthName"), "away_status": g.get("awayNewsStrengthName"),
        "home_news_at": g.get("homeNewsCreatedAt"), "away_news_at": g.get("awayNewsCreatedAt"),
        "game_time": g.get("dateGmt") or g.get("date") or g.get("gameTime"),
    } for g in data]


def _fetch_html(url: str) -> Optional[str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 (public page, robots Allow)
        return r.read().decode("utf-8", "replace")


def _ts(value: Any) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def name_key(name: Any) -> Tuple[str, str]:
    """(first initial, last word), accent-, case- and punctuation-free: 'Andrei Vasilevskiy' and 'A. Vasilevskiy'
    agree, and so do 'Ukko-Pekka Luukkonen' and 'U. Luukkonen'."""
    s = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode().lower()
    toks = [t for t in re.split(r"[^a-z]+", s) if t]
    if len(toks) < 2:
        return ("", toks[0] if toks else "")
    return toks[0][0], toks[-1]


def _abbr(team: Any) -> Optional[str]:
    from syndicate.features.nhl.sim_engine.hockeysim.features.loaders import _abbr as loader_abbr
    ab = loader_abbr(team)
    return str(ab).upper() if ab else None


def _read(path: Path) -> Tuple[List[str], List[Dict[str, str]]]:
    try:
        with path.open(encoding="utf-8", newline="") as fh:
            r = csv.DictReader(fh)
            rows = list(r)
            return list(r.fieldnames or []), rows
    except OSError:
        return [], []


def _write_atomic(path: Path, header: List[str], rows: List[Dict[str, Any]]) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=header, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)
    os.replace(tmp, path)


def confirmed_by_team(games: List[Dict[str, Any]], now: datetime) -> Tuple[Dict[str, str], Dict[str, int]]:
    """{abbr: goalie name} for every side Confirmed and posted before both the scheduled start and `now`, plus
    reason counts for the rest."""
    out: Dict[str, str] = {}
    why = {"confirmed": 0, "not_confirmed": 0, "posted_after_start": 0, "no_time": 0, "unmapped_team": 0}
    for g in games:
        start = _ts(g.get("game_time"))
        for side in ("home", "away"):
            if str(g.get(f"{side}_status") or "").strip().lower() != "confirmed":
                why["not_confirmed"] += 1
                continue
            posted = _ts(g.get(f"{side}_news_at"))
            if posted is None or start is None:
                why["no_time"] += 1
                continue
            if not (posted < start and posted <= now):
                why["posted_after_start"] += 1
                continue
            ab = _abbr(g.get(f"{side}_team"))
            if not ab or not g.get(f"{side}_goalie"):
                why["unmapped_team"] += 1
                continue
            out[ab] = str(g[f"{side}_goalie"])
            why["confirmed"] += 1
    return out, why


def overlay(processed: Path, day: str, games: List[Dict[str, Any]], *, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Rewrite `starting_goalies_<day>.csv` for confirmed starters that map to a dressed goalie. Returns counts."""
    now = now or datetime.now(timezone.utc)
    lp, gp = Path(processed) / f"lineups_{day}.csv", Path(processed) / f"starting_goalies_{day}.csv"
    _lh, lineup = _read(lp)
    gh, goalie_rows = _read(gp)
    status: Dict[str, Any] = {"day": day, "applied": 0, "changed_starter": 0, "no_dressed_match": 0}
    if not lineup:
        status["reason"] = "no lineups file"
        return status
    conf, why = confirmed_by_team(games, now)
    status.update(why)
    dressed: Dict[str, List[Dict[str, str]]] = {}
    team_name: Dict[str, str] = {}
    for r in lineup:
        ab = _abbr(r.get("team"))
        if not ab:
            continue
        team_name.setdefault(ab, str(r.get("team")))
        if str(r.get("position") or "").upper() == "G":
            dressed.setdefault(ab, []).append(r)
    by_team = {}
    for r in goalie_rows:
        ab = _abbr(r.get("team"))
        if ab:
            by_team[ab] = r
    changed = False
    for ab, name in conf.items():
        if ab not in team_name:
            continue  # this team does not play on the slate we collected
        hits = [r for r in dressed.get(ab, []) if name_key(r.get("full_name")) == name_key(name)]
        if len(hits) != 1:
            status["no_dressed_match"] += 1
            continue
        new = {"team": team_name[ab], "goalie": hits[0]["full_name"], "status": "confirmed",
               "confidence": 0.95, "source": "dailyfaceoff"}
        old = by_team.get(ab)
        if old is not None and str(old.get("goalie") or "").strip().lower() != new["goalie"].strip().lower():
            status["changed_starter"] += 1
        by_team[ab] = new
        status["applied"] += 1
        changed = True
    if changed:
        _write_atomic(gp, gh or _GOALIE_COLUMNS, list(by_team.values()))
    status["wrote"] = changed
    return status


def refresh_confirmed_goalies(artifact_root: Path, day: str, *, fetch_html: Optional[FetchHtml] = None,
                              now: Optional[datetime] = None) -> Dict[str, Any]:
    """Fetch the day's Daily Faceoff page and overlay it. Never raises; prints one status line."""
    status: Dict[str, Any] = {"day": day}
    try:
        processed = Path(artifact_root) / "data" / "processed"
        if not enabled():
            status["reason"] = f"{ENV}=off"
        elif not ((processed / f"lineups_{day}.csv").exists() and (processed / f"starting_goalies_{day}.csv").exists()):
            status["reason"] = "no collector lineups/starting_goalies for the day; nothing fetched"
        else:
            html = (fetch_html or _fetch_html)(URL.format(date=day))
            games = parse_page(html or "")
            if games is None:
                status["reason"] = "error=no __NEXT_DATA__ data block (fetch failed or layout change)"
            else:
                status.update(overlay(processed, day, games, now=now))
                status["dfo_games"] = len(games)
    except Exception as exc:  # noqa: BLE001 -- generation must still run on the collector's own projection
        status["reason"] = f"error={type(exc).__name__}: {exc}"
    print(f"[nhl_confirmed_goalies] NHL_CONFIRMED_GOALIES {json.dumps(status, sort_keys=True, default=str)}", flush=True)
    return status
