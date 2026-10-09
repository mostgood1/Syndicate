"""Syndicate-owned basketball play-by-play: ESPN fetch, event normalisation, on-floor reconstruction.

Phase P2 of `docs/ai_context/basketball_live_native_plan.md` (lane `basketball-native-live-state`).
User decision 2026-10-09: the basketball live lens must not rely on the vendored app in any way. This
module replaces what the vendored tick parsed out of play-by-play (`vendor/nba_betting_repo/app.py`
~3222-3773 and `_live_pbp_rotation_state` :4108) and what the vendored CLI's
`rotations_espn.build_team_stints` built for `rotation_stints_history`. It imports neither.

SOURCE: ESPN's site API summary (`plays` + `boxscore` + `header`) for all three leagues. The NBA CDN is
NOT used: ESPN carries every field this module needs for NBA, WNBA and NCAAB (substitutions with both
players, fouls with the fouler's team, timeouts with the calling team, running score on every play), and
one source keeps the three leagues on one parser. Host order and browser User-Agent follow
`scripts/build_ncaab_team_ratings.py` / state `[espn-egress-and-wnba-boxscores]` (vary the headers before
blaming the host).

WHAT ESPN LOOKS LIKE (measured 2026-10-09 on NBA 401859967, WNBA 401857158, NCAAB 401827679):
  * NBA/WNBA substitutions are ONE play, "X enters the game for Y", participants [in, out].
  * NCAAB substitutions are TWO plays, "X subbing in for <school>" / "Y subbing out ...", one participant
    each, in either order at the same clock.
  * A foul play's `team` is the FOULING team and participants[0] the fouler. NBA/WNBA log an offensive
    foul twice ("Offensive Foul" + "Offensive Foul Turnover"); only the first is a foul.
  * NCAAB types are CamelCase without separators ("PersonalFoul", "MadeFreeThrow" -- also for a MISSED
    free throw, with scoringPlay false), and steals/blocks are separate plays.
  * Period-start lineups are never logged: a substitution made between periods appears nowhere. They are
    INFERRED here from who acts first in each period (see `period_start_lineups`).

TIME: `elapsed` is seconds of game time since tip, regulation periods then 5-minute overtimes, so it is
comparable across games of one league. Clocks under a minute arrive as "45.2" and are kept fractional.
"""

from __future__ import annotations

import dataclasses
import json
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

ESPN_HOSTS = ("site.api.espn.com", "site.web.api.espn.com")
ESPN_SPORT_PATH = {
    "nba": "basketball/nba",
    "wnba": "basketball/wnba",
    "ncaab": "basketball/mens-college-basketball",
}
# ESPN abbreviation -> Syndicate tricode (same table as scripts/build_basketball_player_game_log.py).
# NCAAB keeps ESPN's abbreviation; its stable key is the ESPN team id, carried beside it.
TEAM_ALIASES = {
    "wnba": {"GS": "GSV", "LV": "LVA", "LA": "LAS", "NY": "NYL", "CONN": "CON", "WAS": "WSH", "PHO": "PHX"},
    "nba": {"GS": "GSW", "NY": "NYK", "SA": "SAS", "NO": "NOP", "UTAH": "UTA", "WSH": "WAS", "PHO": "PHX"},
    "ncaab": {},
}
# ESPN `season.type`. Phases are separate populations and are never pooled by anything here.
SEASON_TYPES = {1: "preseason", 2: "regular", 3: "playoffs", 5: "play-in"}


@dataclass(frozen=True)
class LeagueRules:
    """Clock and foul geometry per league.

    `penalty_after` is the number of team fouls in a foul period after which the NEXT foul sends the
    opponent to the line (NBA/WNBA: the 5th foul of a quarter -> 4; NCAAB men: 1-and-1 on the 7th foul of
    a half -> 6, double bonus on the 10th -> 9). `last_two_minute_rule`: in the last 2:00 of a period the
    second foul in that window is a penalty foul even below `penalty_after` (NBA/WNBA).
    """

    code: str
    regulation_periods: int
    period_sec: int
    ot_sec: int
    foul_out: int
    penalty_after: int
    ot_penalty_after: int
    double_bonus_after: int | None
    last_two_minute_rule: bool
    foul_period: str  # "period" (fouls reset each quarter/OT) or "half" (NCAAB: reset at half; OT continues the 2nd half)
    possession_fta_coef: float

    def period_length(self, period: int) -> int:
        return self.period_sec if int(period) <= self.regulation_periods else self.ot_sec

    def period_start_elapsed(self, period: int) -> int:
        p = int(period)
        if p <= self.regulation_periods:
            return (p - 1) * self.period_sec
        return self.regulation_periods * self.period_sec + (p - 1 - self.regulation_periods) * self.ot_sec

    def elapsed(self, period: int, clock_left: float) -> float:
        length = self.period_length(period)
        left = max(0.0, min(float(length), float(clock_left)))
        return float(self.period_start_elapsed(period)) + (float(length) - left)

    def regulation_seconds(self) -> int:
        return self.regulation_periods * self.period_sec

    def foul_bucket(self, period: int) -> int:
        """Which foul-count bucket a period belongs to."""
        p = int(period)
        if self.foul_period == "half":
            return 1 if p <= 1 else 2  # NCAAB: OT fouls carry over from the 2nd half
        return p


# Possessions = FGA + TOV + c*FTA - OREB. `c` is an ESTIMATOR, not a rule, so it lives here.
POSSESSION_FTA_COEF = {"nba": 0.44, "wnba": 0.44, "ncaab": 0.475}


def _from_rulebook(code: str) -> LeagueRules:
    """This module's view of the ONE rulebook, `basketball_league_rules` (agreed P1/P2/P4 2026-10-09).

    The rulebook states thresholds as "the award starts FROM the Nth team foul, counting this one";
    `penalty_after` here is the count of fouls already committed, i.e. N - 1.
    """
    from syndicate.features.shared import basketball_league_rules as rulebook

    r = rulebook.rules_for(code)
    first_award = r.one_and_one_from or r.two_shots_from
    ot_first = r.overtime_two_shots_from or first_award  # NCAAB: overtime continues the 2nd half's count
    return LeagueRules(
        code=r.league, regulation_periods=r.periods, period_sec=r.period_seconds, ot_sec=r.overtime_seconds,
        foul_out=r.foul_out, penalty_after=first_award - 1, ot_penalty_after=ot_first - 1,
        double_bonus_after=(r.two_shots_from - 1) if r.one_and_one_from else None,
        last_two_minute_rule=r.late_period_seconds is not None, foul_period=r.bonus_scope,
        possession_fta_coef=POSSESSION_FTA_COEF[code],
    )


RULES: dict[str, LeagueRules] = {code: _from_rulebook(code) for code in ("nba", "wnba", "ncaab")}


def rules_for(league: str) -> LeagueRules:
    try:
        return RULES[str(league or "").strip().lower()]
    except KeyError:
        raise ValueError(f"unknown basketball league {league!r}; expected one of {sorted(RULES)}") from None


# --------------------------------------------------------------------------------------------- fetch

def espn_get(league: str, path: str, *, timeout: float = 30.0, attempts: int = 3) -> Any:
    """GET an ESPN site-API JSON document for `league`, both hosts, retried with backoff."""
    sport = ESPN_SPORT_PATH[str(league).lower()]
    last: Exception | None = None
    for attempt in range(attempts):
        for host in ESPN_HOSTS:
            url = f"https://{host}/apis/site/v2/sports/{sport}/{path}"
            request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            except Exception as exc:  # noqa: BLE001 -- try the other host, then back off
                last = exc
        if attempt < attempts - 1:
            time.sleep(3.0 * (attempt + 1))
    raise RuntimeError(f"ESPN unreachable for {league} {path}: {type(last).__name__}: {last}")


def fetch_scoreboard(league: str, date_yyyymmdd: str) -> dict[str, Any]:
    extra = "&groups=50&limit=500" if str(league).lower() == "ncaab" else "&limit=100"
    return espn_get(league, f"scoreboard?dates={date_yyyymmdd}{extra}")


def fetch_summary(league: str, event_id: str) -> dict[str, Any]:
    return espn_get(league, f"summary?event={event_id}")


def scoreboard_events(scoreboard: Mapping[str, Any]) -> list[dict[str, Any]]:
    """[{event_id, state, completed, status_name, season, season_type, home, away}] for one scoreboard."""
    out: list[dict[str, Any]] = []
    for event in (scoreboard or {}).get("events") or []:
        comp = (event.get("competitions") or [{}])[0]
        status = (comp.get("status") or event.get("status") or {}).get("type") or {}
        season = event.get("season") or {}
        sides = {str(c.get("homeAway")): c for c in comp.get("competitors") or []}
        out.append(
            {
                "event_id": str(event.get("id") or ""),
                "state": str(status.get("state") or ""),  # pre / in / post
                "completed": bool(status.get("completed")),
                "status_name": str(status.get("name") or ""),
                "season": _to_int(season.get("year")),
                "season_type": SEASON_TYPES.get(_to_int(season.get("type")) or 0, f"type{season.get('type')}"),
                "home_id": str(((sides.get("home") or {}).get("team") or {}).get("id") or ""),
                "away_id": str(((sides.get("away") or {}).get("team") or {}).get("id") or ""),
            }
        )
    return out


# ------------------------------------------------------------------------------------------ helpers

def _to_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def parse_clock(display: Any) -> float | None:
    """'7:49' -> 469.0, '45.2' -> 45.2, '0.0' -> 0.0; None when unparseable."""
    text = str(display if display is not None else "").strip()
    if not text:
        return None
    try:
        if ":" in text:
            minutes, _, seconds = text.partition(":")
            return float(minutes or 0) * 60.0 + float(seconds or 0)
        return float(text)
    except ValueError:
        return None


def team_code(league: str, abbreviation: Any) -> str:
    abbr = str(abbreviation or "").strip().upper()
    return TEAM_ALIASES.get(str(league).lower(), {}).get(abbr, abbr)


# ---------------------------------------------------------------------------------------- the game

@dataclass(frozen=True)
class TeamInfo:
    side: str  # home / away
    team_id: str
    code: str
    score: int | None  # ESPN's official score at fetch time


@dataclass(frozen=True)
class BoxPlayer:
    player_id: str
    name: str
    side: str
    starter: bool
    did_not_play: bool
    minutes: float | None  # ESPN reports whole minutes
    pf: int | None
    pts: int | None


@dataclass(frozen=True)
class PbpEvent:
    seq: int  # position in ESPN's play order (ESPN's order is authoritative; clock ties are common)
    play_id: str
    period: int
    clock_left: float
    elapsed: float
    side: str  # home / away / "" (no team: official timeout, end of period)
    kind: str
    type_text: str
    text: str
    points: int  # points this play scored for `side` (0 when not a scoring play)
    home_score: int | None
    away_score: int | None
    players: tuple[str, ...]
    sub_in: tuple[str, ...] = ()
    sub_out: tuple[str, ...] = ()
    made: bool | None = None  # shots / free throws only
    last_free_throw: bool | None = None
    wallclock: str = ""
    points_attempted: int | None = None
    shooting_play: bool = False


@dataclass
class GameMeta:
    league: str
    event_id: str
    date: str  # the ESPN scoreboard day asked for (local schedule date), when known
    season: int | None
    season_type: str
    status_state: str  # pre / in / post
    completed: bool
    home: TeamInfo
    away: TeamInfo
    box: dict[str, BoxPlayer] = field(default_factory=dict)

    def side_of_team_id(self, team_id: Any) -> str:
        tid = str(team_id or "")
        if tid and tid == self.home.team_id:
            return "home"
        if tid and tid == self.away.team_id:
            return "away"
        return ""

    def team(self, side: str) -> TeamInfo:
        return self.home if side == "home" else self.away

    def roster(self, side: str) -> list[str]:
        return [pid for pid, p in self.box.items() if p.side == side]

    def starters(self, side: str) -> list[str]:
        return [pid for pid, p in self.box.items() if p.side == side and p.starter]


def game_meta(summary: Mapping[str, Any], league: str, *, date: str = "") -> GameMeta:
    header = summary.get("header") or {}
    comp = (header.get("competitions") or [{}])[0]
    status = (comp.get("status") or {}).get("type") or {}
    season = header.get("season") or {}
    teams: dict[str, TeamInfo] = {}
    for c in comp.get("competitors") or []:
        side = str(c.get("homeAway") or "")
        team = c.get("team") or {}
        teams[side] = TeamInfo(side=side, team_id=str(team.get("id") or ""), code=team_code(league, team.get("abbreviation")), score=_to_int(c.get("score")))
    if not date:
        date = str(comp.get("date") or "")[:10]
    meta = GameMeta(
        league=str(league).lower(),
        event_id=str(header.get("id") or comp.get("id") or ""),
        date=date,
        season=_to_int(season.get("year")),
        season_type=SEASON_TYPES.get(_to_int(season.get("type")) or 0, f"type{season.get('type')}"),
        status_state=str(status.get("state") or ""),
        completed=bool(status.get("completed")),
        home=teams.get("home") or TeamInfo("home", "", "", None),
        away=teams.get("away") or TeamInfo("away", "", "", None),
    )
    for block in (summary.get("boxscore") or {}).get("players") or []:
        side = meta.side_of_team_id((block.get("team") or {}).get("id"))
        if not side:
            continue
        for stat_block in block.get("statistics") or []:
            names = [str(n).upper() for n in (stat_block.get("names") or stat_block.get("labels") or [])]
            for athlete in stat_block.get("athletes") or []:
                pid = str((athlete.get("athlete") or {}).get("id") or "")
                if not pid:
                    continue
                stats = athlete.get("stats") or []
                cell = dict(zip(names, stats)) if len(stats) == len(names) else {}
                meta.box[pid] = BoxPlayer(
                    player_id=pid,
                    name=str((athlete.get("athlete") or {}).get("displayName") or ""),
                    side=side,
                    starter=bool(athlete.get("starter")),
                    did_not_play=bool(athlete.get("didNotPlay")),
                    minutes=_minutes_or_none(cell.get("MIN")),
                    pf=_to_int(cell.get("PF")),
                    pts=_to_int(cell.get("PTS")),
                )
    return meta


def _minutes_or_none(raw: Any) -> float | None:
    text = str(raw if raw is not None else "").strip()
    if not text or text in {"--", "-"}:
        return None
    if ":" in text:
        m, _, s = text.partition(":")
        try:
            return float(m or 0) + float(s or 0) / 60.0
        except ValueError:
            return None
    try:
        return float(text)
    except ValueError:
        return None


# ---------------------------------------------------------------------------------- classification

def classify(type_text: str, text: str, *, shooting_play: bool) -> str:
    """One kind per play. Order matters: a 'Free Throw - Technical' is a free throw, an
    'Offensive Foul Turnover' a turnover, a 'Technical Foul' never a personal foul."""
    t = str(type_text or "").lower().replace("\n", " ")
    flat = t.replace(" ", "").replace("-", "")
    body = str(text or "").lower()
    if "substitution" in flat:
        return "substitution"
    if "freethrow" in flat:
        return "free_throw"
    if "endgame" in flat:
        return "end_game"
    if "endperiod" in flat or "endofperiod" in flat:
        return "end_period"
    if "timeout" in flat:
        return "timeout_official" if ("official" in flat or "tv" in flat) else "timeout"
    if "turnover" in flat:
        return "turnover"
    if "rebound" in flat:
        if "offensive" in flat:
            return "rebound_off"
        if "defensive" in flat:
            return "rebound_def"
        return "rebound_dead"
    if "foul" in flat:
        if "technical" in flat or "3seconds" in flat:
            return "foul_technical"
        if "offensive" in flat or "charge" in flat:
            return "foul_offensive"
        return "foul"
    if "charge" in flat:  # NBA/WNBA "Offensive Charge" carries no "foul" in its type text
        return "foul_offensive"
    if "technical" in flat or "delayofgame" in flat:
        return "foul_technical"
    if "jumpball" in flat or "jump ball" in t:
        return "jumpball"
    if "ejection" in flat:
        return "ejection"
    if "steal" in flat:
        return "steal"
    if "block" in flat:
        return "block"
    if shooting_play or any(k in flat for k in ("shot", "layup", "dunk", "jumper", "tip", "hook", "fadeaway")):
        return "shot"
    if "violation" in flat or "goaltending" in flat:
        return "violation"
    if "challenge" in flat or "review" in flat:
        return "review"
    if "enters the game" in body:
        return "substitution"
    return "other"


def _free_throw_of(type_text: str, text: str) -> tuple[int, int] | None:
    """('Free Throw - 2 of 3' | 'makes free throw 1 of 2') -> (2, 3)."""
    for source in (str(type_text or ""), str(text or "")):
        lower = source.lower()
        idx = lower.rfind(" of ")
        if idx <= 0:
            continue
        left = lower[:idx].split()
        right = lower[idx + 4 :].split()
        if left and right:
            try:
                return int(left[-1]), int(right[0])
            except ValueError:
                continue
    return None


def normalize_plays(summary: Mapping[str, Any], meta: GameMeta) -> list[PbpEvent]:
    """ESPN `plays` -> typed events in ESPN's order. Plays without a period or a parseable clock are dropped."""
    rules = rules_for(meta.league)
    events: list[PbpEvent] = []
    for raw in summary.get("plays") or []:
        period = _to_int((raw.get("period") or {}).get("number"))
        clock = parse_clock((raw.get("clock") or {}).get("displayValue"))
        if period is None or period < 1 or clock is None:
            continue
        type_text = str((raw.get("type") or {}).get("text") or "")
        text = str(raw.get("text") or "")
        kind = classify(type_text, text, shooting_play=bool(raw.get("shootingPlay")))
        side = meta.side_of_team_id((raw.get("team") or {}).get("id"))
        players = tuple(str((p.get("athlete") or {}).get("id") or "") for p in raw.get("participants") or [])
        players = tuple(p for p in players if p)
        scoring = bool(raw.get("scoringPlay"))
        points = int(raw.get("scoreValue") or 0) if scoring else 0
        sub_in: tuple[str, ...] = ()
        sub_out: tuple[str, ...] = ()
        if kind == "substitution":
            lower = text.lower()
            if " enters the game for " in lower and len(players) >= 2:
                sub_in, sub_out = (players[0],), (players[1],)
            elif "subbing out" in lower and players:
                sub_out = (players[0],)
            elif ("subbing in" in lower or "enters the game" in lower) and players:
                sub_in = (players[0],)
        made: bool | None = None
        last_ft: bool | None = None
        if kind in {"shot", "free_throw"}:
            lower = text.lower()
            made = scoring or (" makes " in f" {lower} " and " misses " not in f" {lower} ")
            if kind == "free_throw":
                n_of = _free_throw_of(type_text, text)
                last_ft = (n_of[0] == n_of[1]) if n_of else None
        events.append(
            PbpEvent(
                seq=len(events),
                play_id=str(raw.get("id") or ""),
                period=int(period),
                clock_left=float(clock),
                elapsed=rules.elapsed(int(period), float(clock)),
                side=side,
                kind=kind,
                type_text=type_text,
                text=text,
                points=points,
                home_score=_to_int(raw.get("homeScore")),
                away_score=_to_int(raw.get("awayScore")),
                players=players,
                sub_in=sub_in,
                sub_out=sub_out,
                made=made,
                last_free_throw=last_ft,
                wallclock=str(raw.get("wallclock") or ""),
                points_attempted=_to_int(raw.get("pointsAttempted")),
                shooting_play=bool(raw.get("shootingPlay")),
            )
        )
    return events


# Plays whose participants say nothing about who is on the floor: a technical can be called on the bench,
# an ejection follows one, and a substitution is handled on its own.
_NO_FLOOR_EVIDENCE = {"foul_technical", "ejection", "substitution", "timeout", "timeout_official", "end_period", "end_game", "review"}


def _floor_evidence(event: PbpEvent, meta: GameMeta, side: str) -> list[str]:
    if event.kind in _NO_FLOOR_EVIDENCE:
        return []
    return [pid for pid in event.players if pid in meta.box and meta.box[pid].side == side]


def period_start_lineups(events: Sequence[PbpEvent], meta: GameMeta, period: int, side: str, previous_end: Sequence[str]) -> tuple[list[str], list[str]]:
    """Who was on the floor for `side` when `period` began, and the notes that explain any guess.

    A player whose FIRST appearance in the period is anything but entering the game was on the floor at
    the start (he acted, or was subbed OUT, before anyone sent him in). A player whose first appearance is
    entering was not. For period 1 ESPN's box `starter` flags decide when they name five players.
    Short of five (someone played the whole period without touching the ball in the log): fill from the
    previous period's closing five, skipping anyone first seen ENTERING this period, then by box minutes.
    More than five (a missed substitution in the log): keep the earliest five to appear, noted.
    """
    notes: list[str] = []
    if period == 1:
        starters = meta.starters(side)
        if len(starters) == 5:
            return list(starters), notes
        notes.append(f"p1_box_starters={len(starters)}")
    first_role: dict[str, str] = {}
    order: list[str] = []
    for ev in events:
        if ev.period != period:
            continue
        if ev.kind == "substitution" and ev.side == side:
            for pid in ev.sub_out:
                if pid not in first_role:
                    first_role[pid] = "on"
                    order.append(pid)
            for pid in ev.sub_in:
                if pid not in first_role:
                    first_role[pid] = "in"
                    order.append(pid)
            continue
        for pid in _floor_evidence(ev, meta, side):
            if pid not in first_role:
                first_role[pid] = "on"
                order.append(pid)
    lineup = [pid for pid in order if first_role[pid] == "on"]
    if len(lineup) > 5:
        notes.append(f"p{period}_inferred_{len(lineup)}_on")
        lineup = lineup[:5]
    if len(lineup) < 5:
        for pid in previous_end:
            if len(lineup) >= 5:
                break
            if pid not in lineup and first_role.get(pid) != "in":
                lineup.append(pid)
                notes.append(f"p{period}_carried_{pid}")
    if len(lineup) < 5:
        by_minutes = sorted(
            (p for p in meta.box.values() if p.side == side and not p.did_not_play and p.player_id not in lineup and first_role.get(p.player_id) != "in"),
            key=lambda p: -(p.minutes or 0.0),
        )
        for p in by_minutes:
            if len(lineup) >= 5:
                break
            lineup.append(p.player_id)
            notes.append(f"p{period}_filled_by_minutes_{p.player_id}")
    return lineup, notes


@dataclass(frozen=True)
class LineupStint:
    side: str
    team: str
    period: int
    start_elapsed: float
    end_elapsed: float
    lineup: tuple[str, ...]  # sorted ESPN athlete ids
    pts_for: int
    pts_against: int
    open: bool = False  # still on the floor (live state only)

    @property
    def duration_sec(self) -> float:
        return max(0.0, self.end_elapsed - self.start_elapsed)


@dataclass
class Reconstruction:
    meta: GameMeta
    events: list[PbpEvent]
    stints: list[LineupStint]
    on_floor: dict[str, list[str]]  # side -> current five (at the last event)
    period: int
    clock_left: float
    elapsed: float
    notes: list[str]
    anomalies: int  # substitutions that did not match the reconstructed floor
    lineups_at: list[tuple[tuple[str, ...], tuple[str, ...]]] = field(default_factory=list)  # (home five, away five) after each event


def reconstruct(summary: Mapping[str, Any], league: str, *, date: str = "") -> Reconstruction:
    meta = game_meta(summary, league, date=date)
    events = normalize_plays(summary, meta)
    return reconstruct_from_events(meta, events)


def reconstruct_from_events(meta: GameMeta, events: Sequence[PbpEvent]) -> Reconstruction:
    """Walk the play log in ESPN's order and cut a lineup stint at every change of five and every period end.

    Points are credited to the stint that is open when the scoring play is reached in ESPN's order, so free
    throws around a substitution land on the five the log says was out there.
    """
    rules = rules_for(meta.league)
    notes: list[str] = []
    anomalies = 0
    stints: list[LineupStint] = []
    periods = sorted({ev.period for ev in events})
    if not periods:
        return Reconstruction(meta, list(events), [], {"home": meta.starters("home")[:5], "away": meta.starters("away")[:5]}, 0, float(rules.period_length(1)), 0.0, ["no_plays"], 0, [])
    on: dict[str, list[str]] = {"home": [], "away": []}
    lineups_at: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
    last_active: dict[str, int] = {}  # player -> seq of the last play that proves he was on the floor
    subbed_at = {(ev.period, ev.clock_left, pid) for ev in events if ev.kind == "substitution" for pid in (*ev.sub_in, *ev.sub_out)}
    last_event = events[-1]
    for period in periods:
        p_events = [ev for ev in events if ev.period == period]
        open_at: dict[str, float] = {}
        pts: dict[str, list[int]] = {}
        for side in ("home", "away"):
            lineup, n = period_start_lineups(events, meta, period, side, on[side])
            notes.extend(f"{side}:{x}" for x in n)
            on[side] = lineup
            open_at[side] = float(rules.period_start_elapsed(period))
            pts[side] = [0, 0]

        def close(side: str, t: float, *, still_open: bool = False) -> None:
            if t > open_at[side] or still_open:
                stints.append(
                    LineupStint(
                        side=side,
                        team=meta.team(side).code,
                        period=period,
                        start_elapsed=open_at[side],
                        end_elapsed=t,
                        lineup=tuple(sorted(on[side])),
                        pts_for=pts[side][0],
                        pts_against=pts[side][1],
                        open=still_open,
                    )
                )
                pts[side] = [0, 0]
            elif pts[side] != [0, 0]:
                # zero-length stint that scored (free throws around a sub at one clock): fold into the next five
                pass
            open_at[side] = t

        i = 0
        while i < len(p_events):
            ev = p_events[i]
            if ev.kind == "substitution" and ev.side in ("home", "away"):
                side = ev.side
                group = [ev]
                j = i + 1
                # NCAAB logs in/out as separate plays at one clock: apply the whole group at once.
                while j < len(p_events) and p_events[j].kind == "substitution" and p_events[j].side == side and p_events[j].clock_left == ev.clock_left:
                    group.append(p_events[j])
                    j += 1
                outs = [pid for g in group for pid in g.sub_out]
                ins = [pid for g in group for pid in g.sub_in]
                new = list(on[side])
                for pid in outs:
                    if pid in new:
                        new.remove(pid)
                    else:
                        anomalies += 1
                        notes.append(f"{side}:p{period}_out_not_on_{pid}@{ev.clock_left:g}")
                for pid in ins:
                    if pid not in new:
                        new.append(pid)
                    else:
                        anomalies += 1
                        notes.append(f"{side}:p{period}_in_already_on_{pid}@{ev.clock_left:g}")
                for pid in ins:
                    last_active[pid] = ev.seq
                if len(new) > 5:
                    # An OUT the log never wrote. Drop whoever has been idle longest (never the players just
                    # sent in) -- a guess, so it is counted and noted, never silent.
                    anomalies += 1
                    notes.append(f"{side}:p{period}_six_on@{ev.clock_left:g}")
                    while len(new) > 5:
                        new.remove(min((p for p in new if p not in ins), key=lambda p: last_active.get(p, -1), default=new[0]))
                if sorted(new) != sorted(on[side]):
                    close(side, ev.elapsed)
                    on[side] = new
                for _ in range(i, j):
                    lineups_at.append((tuple(sorted(on["home"])), tuple(sorted(on["away"]))))
                i = j
                continue
            for side in ("home", "away"):
                acting = _floor_evidence(ev, meta, side)
                for pid in acting:
                    last_active[pid] = ev.seq
                # ESPN writes some substitutions AFTER the incoming player's first play at the same clock (and
                # some before an outgoing player's last): a sub of this player at this clock is not a gap.
                missing = [pid for pid in acting if pid not in on[side] and (period, ev.clock_left, pid) not in subbed_at]
                if missing:
                    # A player ACTS while the log has him on the bench: his substitution was never written
                    # (ESPN's college logs drop some). Put him on now -- the earliest moment the log proves --
                    # in place of whoever has been idle longest and is not part of this play. Counted.
                    new = list(on[side])
                    for pid in missing:
                        anomalies += 1
                        notes.append(f"{side}:p{period}_acting_off_floor_{pid}@{ev.clock_left:g}")
                        new.append(pid)
                    while len(new) > 5:
                        candidates = [p for p in new if p not in acting] or new
                        new.remove(min(candidates, key=lambda p: last_active.get(p, -1)))
                    close(side, ev.elapsed)
                    on[side] = new
            if ev.points and ev.side in ("home", "away"):
                other = "away" if ev.side == "home" else "home"
                pts[ev.side][0] += ev.points
                pts[other][1] += ev.points
            lineups_at.append((tuple(sorted(on["home"])), tuple(sorted(on["away"]))))
            i += 1
        is_last = period == periods[-1]
        live = is_last and not meta.completed and last_event.kind not in {"end_period", "end_game"}
        end_t = last_event.elapsed if live else float(rules.period_start_elapsed(period) + rules.period_length(period))
        for side in ("home", "away"):
            close(side, end_t, still_open=live)
    return Reconstruction(
        meta=meta,
        events=list(events),
        stints=stints,
        on_floor={side: sorted(on[side]) for side in ("home", "away")},
        period=last_event.period,
        clock_left=last_event.clock_left,
        elapsed=last_event.elapsed,
        notes=notes,
        anomalies=anomalies,
        lineups_at=lineups_at,
    )


# ------------------------------------------------------------------------------- derived summaries

def player_seconds(stints: Iterable[LineupStint]) -> dict[str, float]:
    out: dict[str, float] = {}
    for st in stints:
        for pid in st.lineup:
            out[pid] = out.get(pid, 0.0) + st.duration_sec
    return out


def player_intervals(stints: Sequence[LineupStint]) -> list[dict[str, Any]]:
    """Per player, contiguous on-floor intervals (merged across lineup changes that kept him on)."""
    by_side: dict[str, list[LineupStint]] = {"home": [], "away": []}
    for st in stints:
        by_side.setdefault(st.side, []).append(st)
    rows: list[dict[str, Any]] = []
    for side, side_stints in by_side.items():
        side_stints = sorted(side_stints, key=lambda s: (s.start_elapsed, s.end_elapsed))
        current: dict[str, dict[str, Any]] = {}
        for st in side_stints:
            for pid in list(current):
                cur = current[pid]
                if pid not in st.lineup or abs(cur["out_elapsed"] - st.start_elapsed) > 1e-6 or cur["period"] != st.period:
                    rows.append(current.pop(pid))
            for pid in st.lineup:
                if pid in current:
                    current[pid]["out_elapsed"] = st.end_elapsed
                    current[pid]["pts_for"] += st.pts_for
                    current[pid]["pts_against"] += st.pts_against
                else:
                    current[pid] = {"side": side, "team": st.team, "player_id": pid, "period": st.period,
                                    "in_elapsed": st.start_elapsed, "out_elapsed": st.end_elapsed,
                                    "pts_for": st.pts_for, "pts_against": st.pts_against}
        rows.extend(current.values())
    for row in rows:
        row["duration_sec"] = round(row["out_elapsed"] - row["in_elapsed"], 3)
    return sorted(rows, key=lambda r: (r["side"], r["in_elapsed"], r["player_id"]))


def pair_seconds(stints: Iterable[LineupStint]) -> dict[tuple[str, str, str], list[float]]:
    """{(side, player1, player2): [seconds together, stints]} for every teammate pair (ids sorted)."""
    out: dict[tuple[str, str, str], list[float]] = {}
    for st in stints:
        ids = sorted(set(st.lineup))
        if st.duration_sec <= 0:
            continue
        for a in range(len(ids)):
            for b in range(a + 1, len(ids)):
                acc = out.setdefault((st.side, ids[a], ids[b]), [0.0, 0])
                acc[0] += st.duration_sec
                acc[1] += 1
    return out


def reconstructed_score(events: Iterable[PbpEvent]) -> dict[str, int]:
    """Sum of every scoring play's value by side -- independent of ESPN's running score fields."""
    out = {"home": 0, "away": 0}
    for ev in events:
        if ev.points and ev.side in out:
            out[ev.side] += ev.points
    return out


def personal_fouls(events: Iterable[PbpEvent], league: str) -> dict[str, int]:
    """Personal fouls per player as the box score counts them.

    NBA/WNBA: personal, shooting, loose-ball, take, flagrant and offensive fouls; technicals are not
    personal fouls. NCAAB: a player technical also counts toward the five, but ESPN's college log does not
    attribute every technical to a player, so only attributed ones are counted.
    """
    out: dict[str, int] = {}
    count_tech = str(league).lower() == "ncaab"
    for ev in events:
        if ev.kind in {"foul", "foul_offensive"} or (count_tech and ev.kind == "foul_technical" and "foul" in ev.type_text.lower()):
            if ev.players:
                out[ev.players[0]] = out.get(ev.players[0], 0) + 1
    return out


def to_jsonable(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: to_jsonable(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, float):
        return round(obj, 3)
    return obj
