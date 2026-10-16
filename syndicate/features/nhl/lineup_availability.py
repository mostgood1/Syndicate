"""Who an NHL lineup must not dress: the news collector's STATE, as of the lineup's build time.

Lane `nhl-lineup-status` (user 2026-10-16: "proceed with recommendations on 3" -- NHL lineup building reads player
status before it builds lines; REMOVAL ONLY, no TOI redistribution beyond the slot re-sort `infer_lines` already
does; measured first). Survey: `.syndicate/findings_2026-10-16_absence_handling_survey.md`. Measurement, decision
and pipeline trace: `.syndicate/findings_2026-10-16_nhl_lineup_status.md`.

THE INPUT is the news collector (`scripts/collect_news_snapshots.py`, every 10 min, no keys) on the data root:

  news/_state/nhl_injuries.json        ESPN injuries, LAST-SEEN STATE keyed by ESPN id (rewritten every run)
  news/nhl/injuries/<UTC date>.jsonl   the change log that state is diffed into: new | changed | cleared
  news/nhl/gameinfo/<UTC date>.jsonl   each game's officials + SCRATCHES (NHL player ids), ~1 h before puck drop

STATE, NEVER EVENTS. The collector re-keys ESPN ids, so one player can appear as a same-run `new` + `cleared` pair
(10-16: Jason Dickinson EDM, 596043 `new` Out + 596013 `cleared`). Read as a stream of news that pair double-counts
him; replayed BY ID into a state it nets to one record. Records are then deduped by team + normalized name.

AS OF. A lineup is a pre-game object, so a team's exclusions use the state as of min(now, that team's puck drop):
the state file while the game is still ahead (the production path), the change log replayed up to puck drop once it
has started (a post-game rebuild must not remove a player hurt IN the game), and nothing for a moment before the
collector's first capture -- reported `before_collection`, never as a clean zero.

THE RULE is the board flag's own (`news_availability.availability_status`): ESPN `Out`, `Injured Reserve`, LTIR and
`Suspension` remove; `Day-To-Day` (and anything else) stays dressed. A posted NHL scratch removes for that one game,
matched by NHL player id. A state older than `news_availability.STATE_MAX_AGE` is a dead feed: nothing is removed
and the line says `stale`.

Switch: SYNDICATE_NHL_LINEUP_STATUS=off disables it. ABSENT = ON.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from syndicate.local_nhl_odds import _alias_team_abbr, _team_abbr

from syndicate.features.nhl.sim_engine.hockeysim.features.props_lines import initial_surname_key, normalize_name

SWITCH_ENV = "SYNDICATE_NHL_LINEUP_STATUS"
#: `news_availability.availability_status` values that take a player out of the lineup.
REMOVE_STATUSES = frozenset({"OUT", "SUSPENDED"})
SCRATCH_STATUS = "INACTIVE"
#: The collector's first NHL capture (2026-10-13T19:29:58Z). Informational: the code reads the log, not this.
COLLECTION_STARTED = "2026-10-13T19:29:58Z"

TeamNameKey = Tuple[str, str]


def enabled() -> bool:
    return str(os.environ.get(SWITCH_ENV) or "on").strip().lower() not in {"0", "off", "false", "no"}


def _utc(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _iso(moment: Optional[datetime]) -> Optional[str]:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if moment else None


def team_code(name: Any) -> str:
    """The api-web team code collect.py builds a lineup under (`_alias_team_abbr(_team_abbr(name))`)."""
    return _alias_team_abbr(_team_abbr(name) or "") or ""


def removal_status(status_text: Any) -> Optional[str]:
    """ESPN status -> OUT / SUSPENDED (remove) or None (stays dressed): the board flag's rule, not a copy of it."""
    from syndicate.features.shared.news_availability import availability_status

    return availability_status(status_text)


def news_root_for(root: Optional[Path] = None) -> Optional[Path]:
    """`news/` beside the NHL artifact root (`<data root>/nhl_source` on the fleet), else `<data root>/news`
    resolved exactly as the board flag resolves it (`refresh_state_store.data_root`: SYNDICATE_DATA_ROOT)."""
    candidates: List[Path] = []
    if root is not None:
        candidates.append(Path(root).parent / "news")
    try:
        from syndicate.features.shared.refresh_state_store import data_root

        candidates.append(data_root() / "news")
    except RuntimeError:  # strict hosted storage without SYNDICATE_DATA_ROOT: reported as feed=absent
        pass
    for path in candidates:
        if path.is_dir():
            return path
    return None


# ----------------------------------------------------------------------------- state


def _read_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    try:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    yield json.loads(line)
                except ValueError:
                    continue
    except OSError:
        return


def replay_injury_events(events: Iterable[Mapping[str, Any]], as_of: datetime) -> Dict[str, Dict[str, Any]]:
    """The collector's per-id state as of ``as_of``: new/changed set the id's record, cleared drops it."""
    cutoff = _iso(as_of) or ""
    ordered = sorted((e for e in events if str(e.get("captured_at") or "") <= cutoff),
                     key=lambda e: str(e.get("captured_at") or ""))
    state: Dict[str, Dict[str, Any]] = {}
    for ev in ordered:
        athlete_id = str(ev.get("athlete_id") or "")
        if not athlete_id:
            continue
        kind = ev.get("event")
        if kind in ("new", "changed"):
            state[athlete_id] = {k: v for k, v in ev.items() if k not in ("event", "previous_status", "sport", "source")}
        elif kind == "cleared":
            state.pop(athlete_id, None)
    return state


def dedupe_state(state: Mapping[str, Mapping[str, Any]]) -> Dict[TeamNameKey, Dict[str, Any]]:
    """(team code, normalized name) -> one record. Two ids for one player keep the most recently updated."""
    out: Dict[TeamNameKey, Dict[str, Any]] = {}
    for athlete_id, rec in state.items():
        if not isinstance(rec, Mapping):
            continue
        team, name = team_code(rec.get("team")), normalize_name(rec.get("athlete"))
        if not (team and name):
            continue
        cand = {**rec, "athlete_id": str(rec.get("athlete_id") or athlete_id), "team_code": team, "name_key": name}
        prev = out.get((team, name))
        rank = (str(cand.get("source_updated_at") or ""), str(cand.get("captured_at") or ""))
        if prev is None or rank >= (str(prev.get("source_updated_at") or ""), str(prev.get("captured_at") or "")):
            out[(team, name)] = cand
    return out


class CollectorState:
    """The news collector's NHL state as of any moment, read once per distinct ``as_of``."""

    def __init__(self, news_root: Optional[Path], *, now: Optional[datetime] = None,
                 max_age: Optional[timedelta] = None) -> None:
        from syndicate.features.shared.news_availability import STATE_MAX_AGE

        self.news_root = news_root
        self.now = _utc(now) or datetime.now(timezone.utc)
        self.max_age = max_age or STATE_MAX_AGE
        self._events: Optional[List[Dict[str, Any]]] = None
        self._gameinfo: Dict[str, List[Dict[str, Any]]] = {}
        self._injuries: Dict[str, Tuple[Dict[TeamNameKey, Dict[str, Any]], Dict[str, Any]]] = {}

    @property
    def state_path(self) -> Optional[Path]:
        return self.news_root / "_state" / "nhl_injuries.json" if self.news_root else None

    def events(self) -> List[Dict[str, Any]]:
        if self._events is None:
            folder = self.news_root / "nhl" / "injuries" if self.news_root else None
            files = sorted(folder.glob("*.jsonl")) if folder and folder.is_dir() else []
            self._events = [ev for path in files for ev in _read_jsonl(path)]
        return self._events

    def gameinfo(self, utc_day: str) -> List[Dict[str, Any]]:
        """One UTC day's gameinfo records (the collector files them by capture day)."""
        if utc_day not in self._gameinfo:
            path = self.news_root / "nhl" / "gameinfo" / f"{utc_day}.jsonl" if self.news_root else None
            self._gameinfo[utc_day] = list(_read_jsonl(path)) if path is not None else []
        return self._gameinfo[utc_day]

    def injuries_at(self, as_of: Optional[datetime] = None) -> Tuple[Dict[TeamNameKey, Dict[str, Any]], Dict[str, Any]]:
        """``({(team, name): record}, meta)``. ``meta['feed_status']`` is ok / absent / stale / unreadable /
        before_collection; anything but ok carries NO records, so a dead feed removes nobody and says so."""
        as_of = min(_utc(as_of) or self.now, self.now)
        key = _iso(as_of) or ""
        if key not in self._injuries:
            self._injuries[key] = self._load_injuries(as_of)
        return self._injuries[key]

    def _load_injuries(self, as_of: datetime) -> Tuple[Dict[TeamNameKey, Dict[str, Any]], Dict[str, Any]]:
        meta: Dict[str, Any] = {"as_of": _iso(as_of), "news_root": str(self.news_root) if self.news_root else None}
        path = self.state_path
        if path is None or not path.is_file():
            return {}, {**meta, "source": "state_file", "feed_status": "absent"}
        mtime = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        if mtime <= as_of:
            age = as_of - mtime
            meta.update(source="state_file", state_written_at=_iso(mtime), state_age_minutes=round(age.total_seconds() / 60, 1))
            if age > self.max_age:
                return {}, {**meta, "feed_status": "stale"}
            try:
                state = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return {}, {**meta, "feed_status": "unreadable"}
            if not isinstance(state, Mapping):
                return {}, {**meta, "feed_status": "unreadable"}
            return dedupe_state(state), {**meta, "feed_status": "ok"}
        # The state file is NEWER than as_of: replay the change log up to as_of instead of reading the future.
        events = self.events()
        cutoff = _iso(as_of) or ""
        first = min((str(e.get("captured_at") or "") for e in events), default="")
        meta.update(source="event_replay", first_capture=first or None)
        if not first or first > cutoff:
            return {}, {**meta, "feed_status": "before_collection"}
        last = max((str(e.get("captured_at") or "") for e in events if str(e.get("captured_at") or "") <= cutoff), default="")
        meta["last_change_at"] = last or None
        return dedupe_state(replay_injury_events(events, as_of)), {**meta, "feed_status": "ok"}

    def scratches_at(self, game_id: Any, as_of: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
        """The game's latest gameinfo record captured at or before ``as_of`` (None until scratches are posted)."""
        as_of = min(_utc(as_of) or self.now, self.now)
        cutoff = _iso(as_of) or ""
        gid = str(game_id or "")
        best: Optional[Dict[str, Any]] = None
        # A game is polled from 4 h before puck drop, so its records sit in as_of's UTC day or the day before.
        days = [(as_of - timedelta(days=1)).strftime("%Y-%m-%d"), as_of.strftime("%Y-%m-%d")]
        for rec in (r for day in days for r in self.gameinfo(day)):
            if str(rec.get("game_id") or "") != gid:
                continue
            captured = str(rec.get("captured_at") or "")
            if captured <= cutoff and (best is None or captured >= str(best.get("captured_at") or "")):
                best = rec
        return best


# ----------------------------------------------------------------------------- matching


def _row_pid(row: Mapping[str, Any]) -> Optional[int]:
    try:
        return int(row.get("player_id"))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def match_records(rows: List[Mapping[str, Any]], team: str,
                  records: Mapping[TeamNameKey, Mapping[str, Any]]) -> Dict[int, Tuple[Dict[str, Any], str]]:
    """``{player_id: (record, how)}`` for this team's records that name one of ``rows``.

    Exact normalized name first; then initial + surname ("Mitch Marner" / "Mitchell Marner"), accepted only when
    exactly one row of THIS team carries that key. Every status is matched -- the caller decides who is removed.
    """
    by_name: Dict[str, int] = {}
    by_abbr: Dict[str, List[int]] = {}
    for row in rows:
        pid = _row_pid(row)
        if pid is None:
            continue
        by_name.setdefault(normalize_name(row.get("full_name")), pid)
        abbr = initial_surname_key(row.get("full_name"))
        if abbr:
            by_abbr.setdefault(abbr, []).append(pid)
    out: Dict[int, Tuple[Dict[str, Any], str]] = {}
    for (rec_team, name), rec in records.items():
        if rec_team != team:
            continue
        pid, how = by_name.get(name), "name"
        if pid is None:
            cands = set(by_abbr.get(initial_surname_key(rec.get("athlete")), []))
            pid, how = (next(iter(cands)), "initial_surname") if len(cands) == 1 else (None, "")
        if pid is not None:
            out[pid] = (dict(rec), how)
    return out


def match_scratches(rows: List[Mapping[str, Any]], team: str, gameinfo: Optional[Mapping[str, Any]]) -> Dict[int, Dict[str, Any]]:
    """``{player_id: scratch entry}`` for this team's side of a gameinfo record: NHL id first, then exact name."""
    if not gameinfo:
        return {}
    side = next((s for s in ("home", "away") if team_code(gameinfo.get(s)) == team), None)
    if side is None:
        return {}
    pids = {pid for pid in (_row_pid(r) for r in rows) if pid is not None}
    by_name = {normalize_name(r.get("full_name")): _row_pid(r) for r in rows}
    out: Dict[int, Dict[str, Any]] = {}
    for item in gameinfo.get(f"{side}_scratches") or []:
        if not isinstance(item, Mapping):
            continue
        try:
            pid: Optional[int] = int(item.get("id"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            pid = None
        if pid not in pids:
            pid = by_name.get(normalize_name(item.get("name")))
        if pid is not None:
            out[pid] = {"name": item.get("name"), "captured_at": gameinfo.get("captured_at"),
                        "game_id": gameinfo.get("game_id")}
    return out


# ----------------------------------------------------------------------------- slate


@dataclass
class TeamGame:
    team: str
    game_id: str
    start_utc: Optional[datetime]


def slate_games(date: str, root: Optional[Path] = None) -> Dict[str, TeamGame]:
    """team code -> its game on ``date`` (id + scheduled puck drop), from the scoreboard collect.py dresses from."""
    from syndicate.features.nhl.sim_engine.hockeysim.features.loaders import _odds_games_dir, _read_csv_rows

    out: Dict[str, TeamGame] = {}
    for row in _read_csv_rows(_odds_games_dir(root) / f"date={date}" / "scoreboard.csv"):
        gid = str(row.get("gamePk") or row.get("game_pk") or "").strip()
        start = _utc(row.get("gameDate"))
        for side in ("home", "away"):
            team = team_code(row.get(side) or row.get(f"{side}_team"))
            if team and gid and team not in out:
                out[team] = TeamGame(team=team, game_id=gid, start_utc=start)
    return out


@dataclass
class SlateAvailability:
    """What one `collect_slate_inputs` run removed, per team, and from which state."""

    date: str
    collector: CollectorState
    games: Dict[str, TeamGame] = field(default_factory=dict)
    excluded: List[Dict[str, Any]] = field(default_factory=list)
    feeds: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def load(cls, date: str, *, root: Optional[Path] = None, now: Optional[datetime] = None,
             news_root: Optional[Path] = None) -> "SlateAvailability":
        nroot = news_root if news_root is not None else news_root_for(root)
        return cls(date=date, collector=CollectorState(nroot, now=now), games=slate_games(date, root))

    def as_of_for(self, team: str) -> datetime:
        game = self.games.get(team)
        start = game.start_utc if game else None
        return min(start, self.collector.now) if start else self.collector.now

    def apply(self, team: str, usage: List[Dict[str, Any]], *, team_name: str = "") -> List[Dict[str, Any]]:
        """``usage`` without the players this team must not dress; each removal is recorded and printed.

        Never raises: the lineup must still build, so a failure keeps ``usage`` whole and says NOT APPLIED."""
        try:
            return self._apply(team, usage, team_name=team_name)
        except Exception as exc:  # noqa: BLE001 - an availability bug must not cost the slate its lineups
            self.feeds[team] = {"source": "error", "feed_status": "error", "error": f"{type(exc).__name__}: {exc}"[:200]}
            print(f"[nhl_lineup_status] ERROR date={self.date} team={team} NOT APPLIED: {type(exc).__name__}: {exc}",
                  flush=True)
            return usage

    def _apply(self, team: str, usage: List[Dict[str, Any]], *, team_name: str = "") -> List[Dict[str, Any]]:
        as_of = self.as_of_for(team)
        records, meta = self.collector.injuries_at(as_of)
        self.feeds[team] = meta
        game = self.games.get(team)
        scratches = match_scratches(usage, team, self.collector.scratches_at(game.game_id, as_of) if game else None)
        remove: Dict[int, Dict[str, Any]] = {}
        for pid, (rec, how) in match_records(usage, team, records).items():
            status = removal_status(rec.get("status"))
            if status in REMOVE_STATUSES:
                remove[pid] = {"status": status, "feed_status_text": rec.get("status"), "source": "espn_injuries",
                               "captured_at": rec.get("captured_at"), "source_updated_at": rec.get("source_updated_at"),
                               "espn_id": rec.get("athlete_id"), "espn_name": rec.get("athlete"),
                               "comment": rec.get("comment"), "match": how}
        for pid, entry in scratches.items():
            remove.setdefault(pid, {"status": SCRATCH_STATUS, "feed_status_text": "scratched", "source": "nhl_gameinfo",
                                    "captured_at": entry.get("captured_at"), "game_id": entry.get("game_id"),
                                    "match": "nhl_id_or_name"})
        if not remove:
            return usage
        kept: List[Dict[str, Any]] = []
        for row in usage:
            pid = _row_pid(row)
            if pid in remove:
                self.excluded.append({
                    "team": team_name or team, "team_code": team, "player_id": pid, "full_name": row.get("full_name"),
                    "position": row.get("position"), "toi_avg": row.get("toi_avg"),
                    "played_last_game": row.get("played_last_game"), "as_of": _iso(as_of), **remove[pid],
                })
            else:
                kept.append(row)
        names = [f"{e['full_name']}({e['status']}:{e.get('feed_status_text')})" for e in self.excluded if e["team_code"] == team]
        print(f"[nhl_lineup_status] date={self.date} team={team} as_of={_iso(as_of)} feed={meta.get('feed_status')} "
              f"source={meta.get('source')} excluded={len(names)} players={', '.join(names)}", flush=True)
        return kept

    def summary(self) -> Dict[str, Any]:
        statuses: Dict[str, int] = {}
        for meta in self.feeds.values():
            label = f"{meta.get('source')}:{meta.get('feed_status')}"
            statuses[label] = statuses.get(label, 0) + 1
        return {"enabled": True, "excluded": len(self.excluded), "teams": len(self.feeds), "feeds": statuses,
                "players": sorted(str(e.get("full_name")) for e in self.excluded)}

    def report(self) -> None:
        """One slate line, printed even when nothing was removed; a feed that is not ok says NOT APPLIED."""
        s = self.summary()
        not_ok = sorted({m.get("feed_status") for m in self.feeds.values()} - {"ok"})
        verdict = f" NOT APPLIED for {sum(1 for m in self.feeds.values() if m.get('feed_status') != 'ok')} team(s): feed={','.join(not_ok)}" if not_ok else ""
        print(f"NHL_LINEUP_STATUS date={self.date} teams={s['teams']} excluded={s['excluded']} feeds={s['feeds']} "
              f"news_root={self.collector.news_root}{verdict} players={','.join(s['players']) or '<none>'}", flush=True)

    def write(self, out_dir: Path) -> Path:
        """``lineup_exclusions_<date>.json`` beside the lineups file: who was removed, why, and from which state."""
        path = Path(out_dir) / f"lineup_exclusions_{self.date}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"date": self.date, "built_at": _iso(self.collector.now), "switch": SWITCH_ENV,
                   "summary": self.summary(), "feeds": self.feeds, "excluded": self.excluded}
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=1, sort_keys=True, default=str), encoding="utf-8")
        os.replace(tmp, path)
        return path
