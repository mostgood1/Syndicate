"""Who is OUT for NHL and NFL props, from the fleet's news collector -- the board's out-player flag for two more sports.

Lane `news-availability-gate` (user 2026-10-14: "do both, start with #1"). `board_enrichment._flag_out_player_props`
flags basketball prop rows whose player is OUT on that league's injury file, and Layer 2 does not seat them (the bet
voids). NHL and NFL had no such check, so a prop on a scratched or injured-reserve player could rank on a stale quote
until the book pulled it -- measured 2026-10-13: Cale Makar was scratched 29 min before puck drop. The news collector
(`scripts/collect_news_snapshots.py`, every 10 min, verified 2026-10-14 to match ESPN exactly in four sports) already
holds both facts on the fleet disk:

  <data root>/news/_state/<sport>_injuries.json   ESPN injuries, last-seen state per athlete (status, team, ...)
  <data root>/news/nhl/gameinfo/<UTC date>.jsonl  NHL officials + each team's SCRATCHES, logged whenever they change

THE RULE, the same one the basketball path uses: confirmed out only. ESPN `Out`, `Injured Reserve` (and the NFL reserve
lists, `Suspension`) flag the line; `Questionable`, `Doubtful`, `Day-To-Day` and `Active` stay priced. An NHL scratch
is INACTIVE for that one game. The status written to `player_availability` is one of OUT / SUSPENDED / INACTIVE --
exactly the set `layer2_board` refuses to seat.

MATCHED ON TEAM + NAME, NOT NAME ALONE. The basketball path keys on the name only; with 800 NFL athletes on ESPN's
list that would flag the Bills' Josh Allen for the Jaguars' Josh Allen. Teams are compared as NHL abbreviations
(`nhl.sources.team_abbreviation`, accent-insensitive) and as normalised NFL full names. A scratch matches only a row
of the same game: same Central game day and the scratch's own team.

FLAGGED, NOT REMOVED (the `[2026-10-05]` rule the basketball path documents): Layer 1 keeps the quote, marked, with no
edge; Layer 2 does not seat it. Reported even when zero, and the state's age is reported, so a silent or stale feed is
visible. A state older than STATE_MAX_AGE is treated as a dead feed: reported `stale`, nothing flagged.

Switch: `SYNDICATE_NEWS_OUT_GATE=off` disables it (default on).

MLB (user 2026-10-14: "collect MLB injuries now, flag in 2027"): ESPN's injured-list statuses (7/10/15/60-Day IL) count
as OUT, Day-To-Day stays priced -- but an MLB row is flagged ONLY when its game day falls inside a regular season listed
in REGULAR_SEASONS (dates from statsapi `/api/v1/seasons/<year>`). No postseason, no spring training, and a season not
listed flags nothing and says so (`season_gate`). Add each season's window when its schedule is published.
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

SPORTS = ("nhl", "nfl", "mlb")
STATE_MAX_AGE = timedelta(hours=24)
# Sports flagged only inside a listed regular season (game day, Central, inclusive). statsapi /seasons/2027 (read
# 2026-10-14): regular season 2027-03-25..2027-09-26, postseason from 2027-09-27.
REGULAR_SEASONS: dict[str, dict[int, tuple[str, str]]] = {
    "mlb": {2027: ("2027-03-25", "2027-09-26")},
}
_IL_STATUS = re.compile(r"\d+-DAY[- ]IL")
SWITCH_ENV = "SYNDICATE_NEWS_OUT_GATE"
CENTRAL = ZoneInfo("America/Chicago")

# ESPN injury status (upper-cased) -> the board's availability status. Anything else stays priced.
OUT_STATUS: dict[str, str] = {
    "OUT": "OUT",
    "INJURED RESERVE": "OUT",
    "LONG TERM INJURED RESERVE": "OUT",
    "RESERVE-RET": "OUT",
    "PHYSICALLY UNABLE TO PERFORM": "OUT",
    "NON-FOOTBALL INJURY": "OUT",
    "SUSPENSION": "SUSPENDED",
    "SUSPENDED": "SUSPENDED",
    # MLB's other unavailable lists (seen on ESPN 2026-10-14 as lower-case "paternity" / "suspension").
    "PATERNITY": "OUT",
    "PATERNITY LIST": "OUT",
    "BEREAVEMENT": "OUT",
    "BEREAVEMENT LIST": "OUT",
    "RESTRICTED": "OUT",
    "RESTRICTED LIST": "OUT",
}
SCRATCH_STATUS = "INACTIVE"


def availability_status(status: object) -> str | None:
    """ESPN status -> OUT / SUSPENDED, or None (still priced). MLB injured lists (`10-Day-IL`, `7-Day IL`) are OUT."""
    text = str(status or "").strip().upper()
    return OUT_STATUS.get(text) or ("OUT" if _IL_STATUS.fullmatch(text) else None)


def season_window(sport: str, game_day: str | None) -> str:
    """'open' (flag), 'outside' (a listed season, but not inside it), 'unknown' (season not listed), 'ungated'."""
    seasons = REGULAR_SEASONS.get(sport)
    if seasons is None:
        return "ungated"
    if not game_day:
        return "unknown"
    window = seasons.get(int(game_day[:4]))
    if window is None:
        return "unknown"
    return "open" if window[0] <= game_day <= window[1] else "outside"


def enabled() -> bool:
    return str(os.environ.get(SWITCH_ENV) or "on").strip().lower() not in {"0", "off", "false", "no"}


def news_root() -> Path | None:
    from syndicate.features.shared.refresh_state_store import data_root

    try:
        root = data_root() / "news"
    except RuntimeError:
        return None
    return root if root.is_dir() else None


def _nfl_team_key(name: object) -> str:
    text = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", re.sub(r"[^A-Za-z0-9 ]", " ", text)).strip().upper()


def team_key(sport: str, name: object) -> str:
    if sport == "nhl":
        from syndicate.features.nhl.sources import team_abbreviation

        return team_abbreviation(name)
    return _nfl_team_key(name)


def _game_day(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(CENTRAL).date().isoformat()


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    try:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    yield json.loads(line)
                except ValueError:
                    continue
    except OSError:
        return


def _scratches(root: Path, sport: str, now: datetime) -> dict[tuple[str, str, str], dict[str, Any]]:
    """(Central game day, team abbr, player key) -> entry, from each NHL game's LATEST gameinfo record."""
    from syndicate.features.shared.basketball_props_availability import player_key

    if sport != "nhl":
        return {}
    latest: dict[str, dict[str, Any]] = {}
    for offset in (-1, 0, 1):
        day = (now + timedelta(days=offset)).strftime("%Y-%m-%d")
        for rec in _read_jsonl(root / "nhl" / "gameinfo" / f"{day}.jsonl"):
            game_id = str(rec.get("game_id") or "")
            if game_id and str(rec.get("captured_at") or "") >= str((latest.get(game_id) or {}).get("captured_at") or ""):
                latest[game_id] = rec
    out: dict[tuple[str, str, str], dict[str, Any]] = {}
    for game_id, rec in latest.items():
        game_day = _game_day(rec.get("start_utc"))
        if not game_day:
            continue
        for side in ("away", "home"):
            team = team_key("nhl", rec.get(side))
            for item in rec.get(f"{side}_scratches") or []:
                name = item.get("name") if isinstance(item, Mapping) else None
                if team and name:
                    out[(game_day, team, player_key(name))] = {
                        "status": SCRATCH_STATUS, "feed_status_text": "scratched", "team": rec.get(side),
                        "source": "nhl_gameinfo", "captured_at": rec.get("captured_at"), "game_id": game_id,
                    }
    return out


def out_index(sport: str, *, root: Path | None = None, now: datetime | None = None) -> dict[str, Any]:
    """The OUT list for one sport: {feed_status, state_age_minutes, out: {(team, player): entry}, scratches: {...}}."""
    from syndicate.features.shared.basketball_props_availability import player_key

    now = now or datetime.now(timezone.utc)
    root = root if root is not None else news_root()
    if root is None:
        return {"feed_status": "absent", "out": {}, "scratches": {}}
    # Scratches come from the gameinfo feed, not the injury state, so they never wait on it (2026-10-25: an absent,
    # stale or unreadable `_state/<sport>_injuries.json` used to drop every NHL scratch with it, silently).
    scratches = _scratches(root, sport, now)
    state_path = root / "_state" / f"{sport}_injuries.json"
    if not state_path.is_file():
        return {"feed_status": "absent", "out": {}, "scratches": scratches}
    age = now - datetime.fromtimestamp(state_path.stat().st_mtime, timezone.utc)
    age_minutes = round(age.total_seconds() / 60, 1)
    if age > STATE_MAX_AGE:
        return {"feed_status": "stale", "state_age_minutes": age_minutes, "out": {}, "scratches": scratches}
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"feed_status": "unreadable", "state_age_minutes": age_minutes, "out": {}, "scratches": scratches}
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for item in (state.values() if isinstance(state, Mapping) else []):
        if not isinstance(item, Mapping):
            continue
        status = availability_status(item.get("status"))
        team = team_key(sport, item.get("team"))
        if status and team and item.get("athlete"):
            out[(team, player_key(item.get("athlete")))] = {
                "status": status, "feed_status_text": item.get("status"), "team": item.get("team"),
                "source": "espn_injuries", "source_updated_at": item.get("source_updated_at"),
            }
    return {"feed_status": "ok", "state_age_minutes": age_minutes, "out": out, "scratches": scratches}


def _entry_for(row: Mapping[str, Any], sport: str, out: Mapping, scratches: Mapping) -> dict[str, Any] | None:
    """The OUT / scratch entry for a prop row (team + name, a scratch only for its own game day), or None. The season
    gate applies: a row outside its sport's window is never matched."""
    from syndicate.features.shared.basketball_props_availability import player_key

    name = player_key(row.get("player_name"))
    if not name:
        return None
    game_day = _game_day(row.get("commence_time"))
    if season_window(sport, game_day) not in ("open", "ungated"):
        return None
    for team in (team_key(sport, row.get(side)) for side in ("home_team", "away_team")):
        if team:
            entry = (scratches.get((game_day, team, name)) if game_day else None) or out.get((team, name))
            if entry:
                return entry
    return None


def restamp_out_players(rows: list, *, now: datetime | None = None, root: Path | None = None) -> dict[str, int]:
    """Re-read the feeds and stamp `player_availability` on prop rows that do not carry it yet -- run on the shortlist's
    candidates right before `select_shortlist` (2026-10-25). The board reads news once per build in its NHL slot, 3-6
    min before the shortlist is written; on 10-23 a 7:41 PM scratch missed the 7:46 PM shortlist (read at 7:40:25) and
    its portfolio_commit, and landed on the 7:56 PM one. Only the stamp: no projection edits, no log line. Returns
    {sport: rows stamped}."""
    from syndicate.features.shared.basketball_props_availability import REFUSAL_REASON

    if not enabled():
        return {}
    by_sport: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        sport = str(row.get("sport") or "").strip().lower() if isinstance(row, dict) else ""
        if sport in SPORTS and str(row.get("kind") or "") == "prop" and not row.get("player_availability"):
            by_sport.setdefault(sport, []).append(row)
    stamped: dict[str, int] = {}
    for sport, group in by_sport.items():
        index = out_index(sport, root=root, now=now)
        out, scratches = index.get("out") or {}, index.get("scratches") or {}
        if not out and not scratches:
            continue
        for row in group:
            entry = _entry_for(row, sport, out, scratches)
            if entry:
                row["player_availability"] = {
                    "status": entry["status"], "reason": REFUSAL_REASON,
                    "feed_date": entry.get("captured_at") or entry.get("source_updated_at"),
                    "feed_team": entry.get("team"), "feed_status_text": entry.get("feed_status_text"),
                    "source": entry.get("source"), "stamped_at": "select",
                }
                stamped[sport] = stamped.get(sport, 0) + 1
    return stamped


def flag_out_player_props(grid: list, *, sport: str, now: datetime | None = None,
                          root: Path | None = None) -> dict[str, Any]:
    """Mark this sport's prop rows whose player is OUT / SCRATCHED and clear their edges. Returns the coverage entry."""
    from syndicate.features.shared.basketball_props_availability import REFUSAL_REASON, player_key

    if not enabled():
        return {"out_player_props": {"source": "news", "feed_status": "disabled", "rows_flagged": 0}}
    index = out_index(sport, root=root, now=now)
    out, scratches = index.get("out") or {}, index.get("scratches") or {}
    flagged, by_source = 0, {"espn_injuries": 0, "nhl_gameinfo": 0}
    season_counts: dict[str, int] = {}
    players: set[str] = set()
    for row in grid:
        if not isinstance(row, dict) or str(row.get("kind") or "") != "prop":
            continue
        name = player_key(row.get("player_name"))
        if not name:
            continue
        teams = [team_key(sport, row.get(side)) for side in ("home_team", "away_team")]
        game_day = _game_day(row.get("commence_time"))
        gate = season_window(sport, game_day)
        season_counts[gate] = season_counts.get(gate, 0) + 1
        if gate not in ("open", "ungated"):
            continue  # e.g. MLB before 2027-03-25 or in any postseason: the row is left exactly as it was
        entry = None
        for team in teams:
            if not team:
                continue
            entry = (scratches.get((game_day, team, name)) if game_day else None) or out.get((team, name))
            if entry:
                break
        if not entry:
            continue
        row["player_availability"] = {
            "status": entry["status"],
            "reason": REFUSAL_REASON,
            "feed_date": entry.get("captured_at") or entry.get("source_updated_at"),
            "feed_team": entry.get("team"),
            "feed_status_text": entry.get("feed_status_text"),
            "source": entry.get("source"),
        }
        projection = row.get("projection")
        if isinstance(projection, dict):
            projection["edge_vs_market_pct"] = None
            projection["edge_vs_line"] = None
            projection["edge_unavailable_reason"] = REFUSAL_REASON
        flagged += 1
        by_source[entry.get("source") or "espn_injuries"] = by_source.get(entry.get("source") or "espn_injuries", 0) + 1
        players.add(str(row.get("player_name") or ""))
    summary = {
        "source": "news",
        "feed_status": index.get("feed_status"),
        "state_age_minutes": index.get("state_age_minutes"),
        "out_players_on_feed": len(out),
        "scratches_on_feed": len(scratches),
        "rows_flagged": flagged,
        "rows_flagged_by_source": by_source,
        "players": sorted(players),
    }
    if sport in REGULAR_SEASONS:
        summary["season_gate"] = {"windows": {str(y): list(w) for y, w in REGULAR_SEASONS[sport].items()},
                                  "prop_rows_by_gate": dict(sorted(season_counts.items()))}
    print(
        f"[board_enrichment] OUT_PLAYER_PROPS_FLAGGED sport={sport} source=news feed={summary['feed_status']} "
        f"age_min={summary['state_age_minutes']} out_on_feed={len(out)} scratches={len(scratches)} rows={flagged} "
        f"players={','.join(sorted(players)) or '<none>'}",
        flush=True,
    )
    return {"out_player_props": summary}
