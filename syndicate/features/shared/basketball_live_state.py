"""Typed live game state for NBA / WNBA / NCAAB, built from ESPN play-by-play by Syndicate code only.

Phase P2 of `docs/ai_context/basketball_live_native_plan.md` (lane `basketball-native-live-state`). This
is the input P3's resumable re-sim starts from: period, clock, score, possession, team fouls and bonus,
player fouls, the five on the floor per team, the stint log so far, timeouts, and recent-window flow
(pace, runs, droughts) -- the last of which the vendored tick computed and DISCARDED.

It replaces the vendored tick's play-by-play parsing (`vendor/nba_betting_repo/app.py` ~3222-3773:
attempt / possession / score-by-minute / recent-window stats; `_live_pbp_rotation_state` :4108: on/off,
current stint and rest). Nothing here imports `vendor.`.

STORAGE. `capture_live_states` writes plain files under
`<SYNDICATE_DATA_ROOT>/<league>_source/data/processed/live_state/<date>/`:
  * `<event_id>.json`        the newest state, atomically replaced each tick;
  * `<event_id>.ticks.jsonl` one compact line per tick whose state ADVANCED (period, clock, score,
                             possession, fouls, the two fives) -- the tick-by-tick record.
Plain file IO on purpose, never `refresh_state_store.write_json_file`: on a keyvalue backend that call
takes the KEYVALUE branch and returns (learnings 2026-09-16), and the store refuses writes over 8 MB (the
NBA lens was refused for 9 hours on 2026-10-08). A state is bounded by one game's stint log -- measured
~20-40 KB for a full NBA game -- and `MAX_STATE_BYTES` refuses to write anything that is not.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from syndicate.features.shared import basketball_pbp as pbp

MAX_STATE_BYTES = 1_000_000
RECENT_WINDOWS_SEC = (180, 300)
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class PlayerLiveState:
    player_id: str
    name: str
    side: str
    on_floor: bool
    pf: int
    fouled_out: bool
    pts: int
    seconds_played: float
    current_stint_sec: float | None  # on the floor: seconds since he last came on
    current_rest_sec: float | None  # on the bench: seconds since he last went off (None if never played)
    stints_n: int


@dataclass(frozen=True)
class TeamLiveState:
    side: str
    team_id: str
    code: str
    score: int
    possessions: float  # FGA + TOV + c*FTA - OREB (c = 0.44 NBA/WNBA, 0.475 NCAAB)
    fga: int
    fta: int
    tov: int
    oreb: int
    team_fouls_period: int  # in the current foul bucket (quarter / OT for NBA+WNBA, half for NCAAB)
    fouls_last_two_min: int  # NBA/WNBA last-2:00 rule window of the current period
    fouls_to_give: int  # fouls this team can commit before the opponent shoots
    shooting_bonus: str  # "none" / "bonus" / "double_bonus": what THIS team gets when fouled now
    timeouts_used: int
    timeouts_remaining: int | None  # only when ESPN reports it; never derived from a guessed rule
    on_floor: tuple[str, ...]


@dataclass(frozen=True)
class RecentWindow:
    window_sec: int
    from_elapsed: float
    points: dict[str, int]
    possessions: dict[str, float]
    pace_per_game: float | None  # per-team possessions per regulation game (48 / 40 min) at the window's rate
    current_run: dict[str, Any]  # {"side", "points"}: unanswered points by the team that scored last
    seconds_since_score: dict[str, float | None]  # per side: drought length


@dataclass(frozen=True)
class LiveGameState:
    schema_version: int
    league: str
    event_id: str
    date: str
    season: int | None
    season_type: str
    status_state: str  # pre / in / post
    completed: bool
    period: int
    clock_left: float
    elapsed: float
    regulation_seconds: int
    last_seq: int
    last_play_id: str
    possession_side: str | None  # who has the ball after the last play, when the log says
    possession_basis: str
    home: TeamLiveState
    away: TeamLiveState
    players: tuple[PlayerLiveState, ...]
    stints: tuple[pbp.LineupStint, ...]
    recent: tuple[RecentWindow, ...]
    official_score: dict[str, int | None]  # ESPN header score at fetch time
    pbp_score: dict[str, int]  # sum of the log's scoring plays
    score_source: str  # "official" (header) or "pbp" (no header score); see build_live_game_state
    anomalies: int
    notes: tuple[str, ...]
    built_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return pbp.to_jsonable(self)

    def tick_record(self) -> dict[str, Any]:
        return {
            "built_at": self.built_at,
            "status": self.status_state,
            "period": self.period,
            "clock_left": round(self.clock_left, 1),
            "elapsed": round(self.elapsed, 1),
            "last_seq": self.last_seq,
            "score": [self.home.score, self.away.score],
            "possession": self.possession_side,
            "team_fouls": [self.home.team_fouls_period, self.away.team_fouls_period],
            "on_floor": [list(self.home.on_floor), list(self.away.on_floor)],
            "anomalies": self.anomalies,
        }


# --------------------------------------------------------------------------------------------- build

def _team_counts(events: Sequence[pbp.PbpEvent], side: str) -> dict[str, int]:
    fga = sum(1 for e in events if e.side == side and e.kind == "shot")
    fta = sum(1 for e in events if e.side == side and e.kind == "free_throw")
    tov = sum(1 for e in events if e.side == side and e.kind == "turnover")
    oreb = sum(1 for e in events if e.side == side and e.kind == "rebound_off")
    return {"fga": fga, "fta": fta, "tov": tov, "oreb": oreb}


def _possessions(counts: Mapping[str, int], coef: float) -> float:
    return round(float(counts["fga"] + counts["tov"]) + coef * float(counts["fta"]) - float(counts["oreb"]), 2)


def _team_fouls(events: Sequence[pbp.PbpEvent], rules: pbp.LeagueRules, side: str, period: int) -> tuple[int, int]:
    """(fouls in the current foul bucket, fouls in the current period's last two minutes) for `side`.

    NBA/WNBA count defensive personal fouls toward the penalty and NOT offensive fouls; NCAAB counts every
    player personal foul, offensive included. Technicals count for neither.
    """
    bucket = rules.foul_bucket(period)
    countable = {"foul"} if rules.code in {"nba", "wnba"} else {"foul", "foul_offensive"}
    in_bucket = [e for e in events if e.side == side and e.kind in countable and rules.foul_bucket(e.period) == bucket]
    last_two = [e for e in in_bucket if e.period == period and e.clock_left <= 120.0]
    return len(in_bucket), len(last_two)


def _shooting_bonus(rules: pbp.LeagueRules, opp_fouls: int, opp_last_two: int, period: int, clock_left: float) -> tuple[str, int]:
    """(bonus status for the team the opponent is fouling, opponent's fouls to give)."""
    limit = rules.penalty_after if period <= rules.regulation_periods else rules.ot_penalty_after
    if rules.double_bonus_after is not None and opp_fouls >= rules.double_bonus_after:
        return "double_bonus", 0
    if opp_fouls >= limit:
        return "bonus", 0
    to_give = limit - opp_fouls
    if rules.last_two_minute_rule and clock_left <= 120.0:
        if opp_last_two >= 1:
            return "bonus", 0
        to_give = min(to_give, 1)
    return "none", to_give


def _possession_after(events: Sequence[pbp.PbpEvent], meta: pbp.GameMeta) -> tuple[str | None, str]:
    """Who has the ball after the last informative play, and the play kind that says so."""
    other = {"home": "away", "away": "home"}
    for ev in reversed(events):
        if ev.kind in {"end_period", "end_game"}:
            return None, ev.kind
        if ev.side not in other:
            continue
        if ev.kind == "shot" and ev.made:
            return other[ev.side], "made_fg"
        if ev.kind == "free_throw" and ev.last_free_throw:
            return (other[ev.side], "made_last_ft") if ev.made else (None, "missed_last_ft")
        if ev.kind in {"rebound_def", "rebound_off", "steal", "jumpball"}:
            return ev.side, ev.kind
        if ev.kind in {"turnover", "foul_offensive"}:
            return other[ev.side], ev.kind
        if ev.kind == "foul":
            return other[ev.side], "defensive_foul"
    return None, "unknown"


def _recent_window(events: Sequence[pbp.PbpEvent], rules: pbp.LeagueRules, now_elapsed: float, window: int) -> RecentWindow:
    start = max(0.0, now_elapsed - float(window))
    sub = [e for e in events if e.elapsed > start or (e.elapsed == start and start == 0.0)]
    points = {"home": 0, "away": 0}
    for e in sub:
        if e.points and e.side in points:
            points[e.side] += e.points
    poss = {side: _possessions(_team_counts(sub, side), rules.possession_fta_coef) for side in ("home", "away")}
    span = now_elapsed - start
    pace = round(((poss["home"] + poss["away"]) / 2.0) * (float(rules.regulation_seconds()) / span), 1) if span >= 60.0 else None
    run_side: str | None = None
    run_pts = 0
    last_score_at: dict[str, float | None] = {"home": None, "away": None}
    for e in events:  # whole game: a run or drought does not respect the window
        if e.points and e.side in last_score_at:
            last_score_at[e.side] = e.elapsed
            if e.side == run_side:
                run_pts += e.points
            else:
                run_side, run_pts = e.side, e.points
    since = {side: (round(now_elapsed - t, 1) if t is not None else None) for side, t in last_score_at.items()}
    return RecentWindow(window_sec=int(window), from_elapsed=round(start, 1), points=points, possessions=poss,
                        pace_per_game=pace, current_run={"side": run_side, "points": run_pts}, seconds_since_score=since)


def _summary_timeouts(summary: Mapping[str, Any]) -> dict[str, int | None]:
    """ESPN's own timeouts-remaining when the live summary carries it (situation block); else None."""
    out: dict[str, int | None] = {"home": None, "away": None}
    comp = ((summary.get("header") or {}).get("competitions") or [{}])[0]
    situation = comp.get("situation") or summary.get("situation") or {}
    for side in ("home", "away"):
        value = situation.get(f"{side}Timeouts")
        out[side] = pbp._to_int(value)
    return out


def build_live_game_state(summary: Mapping[str, Any], league: str, *, date: str = "", built_at: str | None = None) -> LiveGameState:
    rules = pbp.rules_for(league)
    rec = pbp.reconstruct(summary, league, date=date)
    meta, events = rec.meta, rec.events
    # The team score is ESPN's header score when it has one. Measured over the 2025-26 NBA backfill
    # (1,420 games): the sum of scoring plays matched the official final 1,412 times; in 6 of the 8 misses
    # ESPN's own running score was wrong too (plays missing from the log), and once the play values
    # double-counted (MIN-DEN 2025-11-15, +4 each) while the running score was right. The play sum is kept
    # beside it (`pbp_score`), and the stint points always come from the log.
    pbp_score = pbp.reconstructed_score(events)
    official = {"home": meta.home.score, "away": meta.away.score}
    use_official = official["home"] is not None and official["away"] is not None and (meta.status_state in {"in", "post"} or events)
    score = dict(official) if use_official else dict(pbp_score)
    pf = pbp.personal_fouls(events, league)
    period = rec.period or 1
    clock_left = rec.clock_left if events else float(rules.period_length(1))
    timeouts_left = _summary_timeouts(summary)

    fouls = {side: _team_fouls(events, rules, side, period) for side in ("home", "away")}
    teams: dict[str, TeamLiveState] = {}
    for side in ("home", "away"):
        opp = "away" if side == "home" else "home"
        counts = _team_counts(events, side)
        bonus, _ = _shooting_bonus(rules, fouls[opp][0], fouls[opp][1], period, clock_left)
        _, to_give = _shooting_bonus(rules, fouls[side][0], fouls[side][1], period, clock_left)
        info = meta.team(side)
        teams[side] = TeamLiveState(
            side=side, team_id=info.team_id, code=info.code, score=score[side],
            possessions=_possessions(counts, rules.possession_fta_coef), **counts,
            team_fouls_period=fouls[side][0], fouls_last_two_min=fouls[side][1], fouls_to_give=to_give,
            shooting_bonus=bonus,
            timeouts_used=sum(1 for e in events if e.side == side and e.kind == "timeout"),
            timeouts_remaining=timeouts_left[side],
            on_floor=tuple(rec.on_floor.get(side) or ()),
        )

    seconds = pbp.player_seconds(rec.stints)
    pts: dict[str, int] = {}
    for e in events:
        if e.points and e.players:
            pts[e.players[0]] = pts.get(e.players[0], 0) + e.points
    intervals = pbp.player_intervals(rec.stints)
    players: list[PlayerLiveState] = []
    for pid, box in sorted(meta.box.items(), key=lambda kv: (kv[1].side, kv[1].name)):
        mine = [iv for iv in intervals if iv["player_id"] == pid]
        on = pid in (rec.on_floor.get(box.side) or [])
        cur_stint = cur_rest = None
        if on and mine:
            cur_stint = round(rec.elapsed - mine[-1]["in_elapsed"], 1)
        elif mine:
            cur_rest = round(rec.elapsed - mine[-1]["out_elapsed"], 1)
        players.append(PlayerLiveState(
            player_id=pid, name=box.name, side=box.side, on_floor=on, pf=pf.get(pid, 0),
            fouled_out=pf.get(pid, 0) >= rules.foul_out, pts=pts.get(pid, 0),
            seconds_played=round(seconds.get(pid, 0.0), 1), current_stint_sec=cur_stint, current_rest_sec=cur_rest,
            stints_n=len(mine),
        ))
    possession, basis = _possession_after(events, meta)
    last = events[-1] if events else None
    return LiveGameState(
        schema_version=SCHEMA_VERSION, league=rules.code, event_id=meta.event_id, date=meta.date, season=meta.season,
        season_type=meta.season_type, status_state=meta.status_state, completed=meta.completed,
        period=period, clock_left=clock_left, elapsed=rec.elapsed, regulation_seconds=rules.regulation_seconds(),
        last_seq=last.seq if last else -1, last_play_id=last.play_id if last else "",
        possession_side=possession, possession_basis=basis, home=teams["home"], away=teams["away"],
        players=tuple(players), stints=tuple(rec.stints),
        recent=tuple(_recent_window(events, rules, rec.elapsed, w) for w in RECENT_WINDOWS_SEC),
        official_score=official, pbp_score=pbp_score, score_source="official" if use_official else "pbp",
        anomalies=rec.anomalies, notes=tuple(rec.notes[:50]),
        built_at=built_at or dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    )


# ------------------------------------------------------------------------------------------- storage

def source_root(league: str) -> Path:
    league = str(league).lower()
    override = str(os.environ.get(f"SYNDICATE_{league.upper()}_SOURCE_ROOT") or "").strip()
    if override:
        return Path(override)
    repo = Path(__file__).resolve().parents[3]
    return Path(os.environ.get("SYNDICATE_DATA_ROOT", str(repo / "data"))) / f"{league}_source"


def live_state_dir(league: str, date: str) -> Path:
    return source_root(league) / "data" / "processed" / "live_state" / str(date)


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def write_live_state(state: LiveGameState, *, out_dir: Path | None = None) -> dict[str, Any]:
    """Persist one state; append a tick line only when the game ADVANCED since the previous line."""
    out_dir = out_dir or live_state_dir(state.league, state.date)
    body = json.dumps(state.to_dict(), separators=(",", ":"))
    if len(body.encode("utf-8")) > MAX_STATE_BYTES:
        raise ValueError(f"live state for {state.league} {state.event_id} is {len(body)} B > {MAX_STATE_BYTES}; refusing to write")
    state_path = out_dir / f"{state.event_id}.json"
    ticks_path = out_dir / f"{state.event_id}.ticks.jsonl"
    _atomic_write(state_path, body)
    tick = state.tick_record()
    previous = None
    if ticks_path.is_file():
        try:
            with ticks_path.open("rb") as handle:
                handle.seek(max(0, ticks_path.stat().st_size - 8192))
                tail = handle.read().decode("utf-8", "replace").strip().splitlines()
            previous = json.loads(tail[-1]) if tail else None
        except (OSError, ValueError):
            previous = None
    advanced = previous is None or previous.get("last_seq") != tick["last_seq"] or previous.get("status") != tick["status"]
    if advanced:
        with ticks_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(tick, separators=(",", ":")) + "\n")
    return {"event_id": state.event_id, "bytes": len(body), "advanced": advanced, "path": str(state_path)}


def capture_live_states(league: str, date: str, *, include_final: bool = True, fetch_scoreboard=pbp.fetch_scoreboard,
                        fetch_summary=pbp.fetch_summary, out_dir: Path | None = None) -> list[dict[str, Any]]:
    """One tick for every in-progress (and, by default, just-final) game of `league` on `date` (YYYY-MM-DD)."""
    events = pbp.scoreboard_events(fetch_scoreboard(league, date.replace("-", "")))
    results: list[dict[str, Any]] = []
    for ev in events:
        if ev["state"] != "in" and not (include_final and ev["state"] == "post"):
            continue
        target = out_dir or live_state_dir(league, date)
        if ev["state"] == "post" and (target / f"{ev['event_id']}.json").is_file():
            try:
                prior = json.loads((target / f"{ev['event_id']}.json").read_text(encoding="utf-8"))
                if prior.get("completed"):
                    continue  # final already captured; no refetch every tick
            except (OSError, ValueError):
                pass
        try:
            state = build_live_game_state(fetch_summary(league, ev["event_id"]), league, date=date)
            result = write_live_state(state, out_dir=target)
            result.update({"status": state.status_state, "period": state.period, "clock_left": state.clock_left,
                           "score": [state.home.score, state.away.score], "official": [state.official_score["home"], state.official_score["away"]],
                           "anomalies": state.anomalies})
        except Exception as exc:  # noqa: BLE001 -- one bad game must not stop the others; the error is reported
            result = {"event_id": ev["event_id"], "error": f"{type(exc).__name__}: {exc}"}
        results.append(result)
    return results
