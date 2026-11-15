"""Which players have LEFT a live game mid-game, read from the live game feed.

Lane ``live-player-exit-gate`` (2026-11-15). A pure function from one ESPN
``summary?event=`` payload (the same payload the live loops already fetch for
NFL, NCAAF, NBA, WNBA, NCAAB, WNCAAB, NHL and soccer) to the set of players who
are out of that game RIGHT NOW, plus whether any of them is a KEY player.

Policy (the lane goal): while a key player is out, the game's live GAMELINES are
refused; while ANY player is out, that player's live PROPS are refused. Both
carry the reason ``key_player_out`` / ``player_out``. This module only DETECTS;
call sites decide what to refuse (see ``gameline_refusal`` / ``prop_refusal``).

Signals, per sport (measured on real ESPN payloads, findings
``.syndicate/findings_2026-11-15_live_player_exit_survey.md``):

football (nfl, ncaaf)
  - play-by-play ``"NE-D.Maye was injured during the play."`` -> out, until a later
    play names him (as an actor, or a tackler in parentheses: he is back on) or
    ``"NE-D.Maye has returned to the game."``. On 2026-11-15 this fired at
    14:41:43Z; ESPN's injuries list only said ``Out`` at 15:43Z.
  - the summary ``injuries`` list stamped AFTER kickoff with status Out /
    Questionable / Doubtful -> out (an in-game ruling, e.g. questionable to return).
  - play text ``ejected`` -> out.
  KEY = a quarterback (anyone in the team's boxscore ``passing`` list).

basketball (nba, wnba, ncaab, wncaab)
  - a play of type ``ejection`` (the dependable signal: the boxscore ``ejected`` flag stayed
    false for a real WNBA ejection) or boxscore ``ejected: true`` -> out (ejection).
  - personal fouls >= the league limit (6 NBA/WNBA, 5 college) -> out (foul_out).
  - ``injuries`` stamped after tip with status ``Out`` -> out (injury).
  KEY = a starter (boxscore ``starter: true``).

hockey (nhl)
  - the live path reads NHL api-web, not ESPN: ``exits_from_nhl_boxscore`` -- the STARTER is
    out once a non-starter goalie has time on ice (goalie_change), KEY.
  - on an ESPN payload: a team with TWO goalies holding time on ice -> the goaltender changed; every
    goalie of that team with TOI is marked out (goalie_change), KEY. (An empty-net
    pull does not add a second goalie to the box.)
  - ``injuries`` stamped after puck drop, status ``Out`` -> out; key if a goalie.

soccer
  - keyEvent type EXACTLY ``Red Card`` -> out (red_card), KEY (a man down).
    Never a substring test: ``"Penalty - Scored"`` contains "red".
  - the starting keeper (position ``G``) ``subbedOut`` -> out (keeper_change), KEY.

mlb is not ESPN-fed here (statsapi ``feed/live``) and is out of season until
2027; see the findings file.

Nothing here does I/O. ``exits_from_espn_summary`` returns an empty status for a
game that is not in progress, so a stale or pregame payload never refuses.
"""

from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

REASON_KEY_PLAYER_OUT = "key_player_out"
REASON_PLAYER_OUT = "player_out"

FOOTBALL = frozenset({"nfl", "ncaaf"})
BASKETBALL = frozenset({"nba", "wnba", "ncaab", "wncaab"})
HOCKEY = frozenset({"nhl"})
SOCCER = frozenset({"soccer"})
SUPPORTED_SPORTS = FOOTBALL | BASKETBALL | HOCKEY | SOCCER

FOUL_LIMIT = {"nba": 6, "wnba": 6, "ncaab": 5, "wncaab": 5}

# ESPN in-game injury statuses that mean "not on the field now".
_INGAME_OUT_STATUSES_FOOTBALL = frozenset({"out", "questionable", "doubtful"})
_INGAME_OUT_STATUSES_OTHER = frozenset({"out"})

ENV_SWITCH = "SYNDICATE_LIVE_PLAYER_EXIT_GATE"

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def gate_enabled(env: Mapping[str, str] | None = None) -> bool:
    """The switch call sites read. Absent = ON: refusing is the safe failure,
    and an absent key must not map onto the permissive branch."""
    raw = (env if env is not None else os.environ).get(ENV_SWITCH)
    if raw is None:
        return True
    return str(raw).strip().lower() not in {"0", "off", "false", "no"}


@dataclass(frozen=True)
class PlayerOut:
    sport: str
    game_id: str
    team: str  # team abbreviation as the feed spells it
    player: str  # display name
    player_id: str | None
    reason: str  # injury | injured_in_play | ejection | foul_out | goalie_change | red_card | keeper_change
    key: bool
    source: str  # pbp | injuries | boxscore | keyEvents | rosters
    since: str | None = None  # feed wallclock / injury stamp when known


@dataclass(frozen=True)
class GameExitStatus:
    sport: str
    game_id: str
    in_progress: bool
    players_out: tuple[PlayerOut, ...] = field(default_factory=tuple)
    home_team: str = ""  # feed displayName: board rows join on team NAMES, not ids
    away_team: str = ""

    def to_dict(self) -> dict[str, Any]:
        """The shape a producer publishes in its live-lens snapshot."""
        return {
            "sport": self.sport,
            "game_id": self.game_id,
            "home_team": self.home_team,
            "away_team": self.away_team,
            "in_progress": self.in_progress,
            "players_out": [dict(p.__dict__) for p in self.players_out],
        }

    @property
    def key_players_out(self) -> tuple[PlayerOut, ...]:
        return tuple(p for p in self.players_out if p.key)

    def player_is_out(self, name: str) -> PlayerOut | None:
        target = normalize_name(name)
        if not target:
            return None
        for p in self.players_out:
            if normalize_name(p.player) == target:
                return p
        return None


def gameline_refusal(status: GameExitStatus | None) -> dict[str, Any] | None:
    """A refusal record for the game's live gamelines, or None to price."""
    if status is None or not status.in_progress:
        return None
    keys = status.key_players_out
    if not keys:
        return None
    return {
        "reason": REASON_KEY_PLAYER_OUT,
        "sport": status.sport,
        "game_id": status.game_id,
        "players": [f"{p.team}:{p.player}:{p.reason}" for p in keys],
    }


def prop_refusal(status: GameExitStatus | None, player: str) -> dict[str, Any] | None:
    """A refusal record for one player's live props, or None to price."""
    if status is None or not status.in_progress:
        return None
    hit = status.player_is_out(player)
    if hit is None:
        return None
    return {
        "reason": REASON_KEY_PLAYER_OUT if hit.key else REASON_PLAYER_OUT,
        "sport": status.sport,
        "game_id": status.game_id,
        "players": [f"{hit.team}:{hit.player}:{hit.reason}"],
    }


# --------------------------------------------------------------------------- names

_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def normalize_name(name: Any) -> str:
    text = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-z0-9 ]+", " ", text.lower())
    return " ".join(p for p in text.split() if p not in _SUFFIXES)


def _abbrev(first: str, last: str) -> str:
    """ESPN football play text spells a player ``D.Maye`` / ``A.St. Brown``."""
    first = (first or "").strip()
    last = (last or "").strip()
    if not first or not last:
        return ""
    return f"{first[0]}.{last}"


# --------------------------------------------------------------------------- feed helpers


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%MZ", "%Y-%m-%dT%H:%M:%S.%fZ"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _competition(summary: Mapping[str, Any]) -> Mapping[str, Any]:
    comps = ((summary.get("header") or {}).get("competitions")) or []
    return comps[0] if comps else {}


def _in_progress(summary: Mapping[str, Any]) -> bool:
    status = (_competition(summary).get("status") or {}).get("type") or {}
    return str(status.get("state") or "").lower() == "in"


def _home_away_names(summary: Mapping[str, Any]) -> tuple[str, str]:
    home = away = ""
    for comp in _competition(summary).get("competitors") or []:
        name = str(((comp.get("team") or {}).get("displayName")) or "")
        if comp.get("homeAway") == "home":
            home = name
        elif comp.get("homeAway") == "away":
            away = name
    return home, away


def _team_abbrevs(summary: Mapping[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for comp in _competition(summary).get("competitors") or []:
        team = comp.get("team") or {}
        if team.get("id") is not None:
            out[str(team["id"])] = str(team.get("abbreviation") or "")
    return out


def _box_athletes(summary: Mapping[str, Any]) -> Iterable[tuple[str, str, Mapping[str, Any], Mapping[str, Any]]]:
    """Yield (team_abbrev, category_name, category, athlete_entry) over the boxscore."""
    for team_block in (summary.get("boxscore") or {}).get("players") or []:
        abbr = str((team_block.get("team") or {}).get("abbreviation") or "")
        for cat in team_block.get("statistics") or []:
            name = str(cat.get("name") or cat.get("type") or "")
            for entry in cat.get("athletes") or []:
                yield abbr, name, cat, entry


def _stat(cat: Mapping[str, Any], entry: Mapping[str, Any], label: str) -> str | None:
    labels = list(cat.get("labels") or [])
    stats = list(entry.get("stats") or [])
    if label in labels:
        idx = labels.index(label)
        if idx < len(stats):
            return str(stats[idx])
    return None


def _ingame_injuries(summary: Mapping[str, Any], sport: str) -> list[tuple[str, Mapping[str, Any], str, str]]:
    """(team_abbrev, athlete, status, stamp) for injuries stamped after the start."""
    start = _parse_ts(_competition(summary).get("date"))
    if start is None:
        return []
    allowed = _INGAME_OUT_STATUSES_FOOTBALL if sport in FOOTBALL else _INGAME_OUT_STATUSES_OTHER
    out = []
    for team_block in summary.get("injuries") or []:
        abbr = str((team_block.get("team") or {}).get("abbreviation") or "")
        for inj in team_block.get("injuries") or []:
            stamp = _parse_ts(inj.get("date"))
            status = str(inj.get("status") or "").strip().lower()
            if stamp is None or stamp < start or status not in allowed:
                continue
            out.append((abbr, inj.get("athlete") or {}, status, str(inj.get("date"))))
    return out


def _athlete_id(athlete: Mapping[str, Any]) -> str | None:
    aid = athlete.get("id")
    return str(aid) if aid not in (None, "") else None


def _names_on_field(text: str, ab: str) -> bool:
    """Does ``ab`` (``D.Maye``) take part in this play -- as the passer / runner /
    receiver, or as a tackler in parentheses (a defender only ever appears there)
    -- other than as this very play's injured player?"""
    if not re.search(rf"(?<![A-Za-z\.]){re.escape(ab)}(?![A-Za-z])", text):
        return False
    return not re.search(rf"-{re.escape(ab)} (?:was injured|has returned)", text)


# --------------------------------------------------------------------------- sports

_INJURED_RE = re.compile(r"\b([A-Z]{2,4})-([A-Z]\.[A-Za-z'\.\- ]+?) was injured during the play")
_RETURNED_RE = re.compile(r"\b([A-Z]{2,4})-([A-Z]\.[A-Za-z'\.\- ]+?) has returned to the game")
_EJECTED_RE = re.compile(r"\b([A-Z]{2,4})-([A-Z]\.[A-Za-z'\.\- ]+?) (?:was|has been) ejected")


def _football_plays(summary: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    drives = summary.get("drives") or {}
    plays: list[Mapping[str, Any]] = []
    for drive in drives.get("previous") or []:
        plays.extend(drive.get("plays") or [])
    plays.extend(((drives.get("current") or {}).get("plays")) or [])
    seen: set[str] = set()
    unique = []
    for p in plays:
        pid = str(p.get("id") or "")
        if pid and pid in seen:
            continue
        seen.add(pid)
        unique.append(p)
    unique.sort(key=lambda p: (_parse_ts(p.get("wallclock")) or _EPOCH, int(p.get("sequenceNumber") or 0)))
    return unique


def _football(sport: str, game_id: str, summary: Mapping[str, Any]) -> list[PlayerOut]:
    by_abbrev: dict[tuple[str, str], Mapping[str, Any]] = {}
    abbrev_by_name: dict[tuple[str, str], str] = {}  # (team, normalized display) -> D.Maye
    passers: set[tuple[str, str]] = set()  # (team, normalized display name)
    for team, cat_name, _cat, entry in _box_athletes(summary):
        ath = entry.get("athlete") or {}
        ab = _abbrev(ath.get("firstName") or "", ath.get("lastName") or "")
        if ab:
            by_abbrev.setdefault((team, ab), ath)
            abbrev_by_name.setdefault((team, normalize_name(ath.get("displayName"))), ab)
        if cat_name == "passing":
            passers.add((team, normalize_name(ath.get("displayName"))))

    def is_key(team: str, display: str) -> bool:
        return (team, normalize_name(display)) in passers

    plays = _football_plays(summary)
    out_state: dict[tuple[str, str], tuple[str, str | None]] = {}  # (team, abbrev) -> (reason, since)
    for play in plays:
        text = str(play.get("text") or "")
        when = play.get("wallclock")
        for (team, ab), (reason, _since) in list(out_state.items()):
            if reason != "ejection" and _names_on_field(text, ab):
                del out_state[(team, ab)]
        for team, ab in _RETURNED_RE.findall(text):
            out_state.pop((team, ab.strip()), None)
        for team, ab in _INJURED_RE.findall(text):
            out_state[(team, ab.strip())] = ("injured_in_play", when)
        for team, ab in _EJECTED_RE.findall(text):
            out_state[(team, ab.strip())] = ("ejection", when)

    results: dict[tuple[str, str], PlayerOut] = {}
    for (team, ab), (reason, since) in out_state.items():
        ath = by_abbrev.get((team, ab)) or {}
        display = str(ath.get("displayName") or ab)
        results[(team, normalize_name(display))] = PlayerOut(
            sport, game_id, team, display, _athlete_id(ath), reason, is_key(team, display), "pbp", since
        )
    for team, ath, _status, stamp in _ingame_injuries(summary, sport):
        display = str(ath.get("displayName") or "")
        k = (team, normalize_name(display))
        if not display or k in results:
            continue
        # the injuries list carries displayName only: take the boxscore's spelling
        ab = abbrev_by_name.get(k) or _abbrev(ath.get("firstName") or "", ath.get("lastName") or "")
        if not ab and " " in display:
            first, _, last = display.partition(" ")
            ab = _abbrev(first, last)
        if ab and _returned_after(plays, team, ab, stamp):
            continue  # the feed shows him back on the field after the ruling
        results[k] = PlayerOut(sport, game_id, team, display, _athlete_id(ath), "injury", is_key(team, display), "injuries", stamp)
    return list(results.values())


def _returned_after(plays: list[Mapping[str, Any]], team: str, ab: str, stamp: str) -> bool:
    cutoff = _parse_ts(stamp)
    if cutoff is None:
        return False
    for play in plays:
        when = _parse_ts(play.get("wallclock"))
        if when is None or when <= cutoff:
            continue
        text = str(play.get("text") or "")
        if f"{team}-{ab} has returned to the game" in text or _names_on_field(text, ab):
            return True
    return False


def _basketball(sport: str, game_id: str, summary: Mapping[str, Any]) -> list[PlayerOut]:
    limit = FOUL_LIMIT.get(sport, 6)
    results: dict[tuple[str, str], PlayerOut] = {}
    starters: set[tuple[str, str]] = set()
    for team, _name, cat, entry in _box_athletes(summary):
        ath = entry.get("athlete") or {}
        display = str(ath.get("displayName") or "")
        if not display:
            continue
        k = (team, normalize_name(display))
        starter = bool(entry.get("starter"))
        if starter:
            starters.add(k)
        if entry.get("ejected"):
            results[k] = PlayerOut(sport, game_id, team, display, _athlete_id(ath), "ejection", starter, "boxscore")
            continue
        pf = _stat(cat, entry, "PF")
        try:
            fouls = int(float(pf)) if pf not in (None, "", "--") else 0
        except ValueError:
            fouls = 0
        if fouls >= limit:
            results[k] = PlayerOut(sport, game_id, team, display, _athlete_id(ath), "foul_out", starter, "boxscore")
    # THE PLAY, NOT THE FLAG: on a real WNBA final (401856991) "Isabelle Harrison ejected" is a play of
    # type `ejection` while her boxscore entry still says `ejected: false`.
    by_id = {}
    for team, _name, _cat, entry in _box_athletes(summary):
        ath = entry.get("athlete") or {}
        if _athlete_id(ath):
            by_id.setdefault(_athlete_id(ath), (team, ath, bool(entry.get("starter"))))
    for play in summary.get("plays") or []:
        if str(((play.get("type") or {}).get("text")) or "").strip().lower() != "ejection":
            continue
        for part in play.get("participants") or []:
            hit = by_id.get(str(((part.get("athlete") or {}).get("id")) or ""))
            if hit is None:
                continue
            team, ath, starter = hit
            display = str(ath.get("displayName") or "")
            results[(team, normalize_name(display))] = PlayerOut(
                sport, game_id, team, display, _athlete_id(ath), "ejection", starter, "pbp", play.get("wallclock")
            )
    for team, ath, _status, stamp in _ingame_injuries(summary, sport):
        display = str(ath.get("displayName") or "")
        k = (team, normalize_name(display))
        if display and k not in results:
            results[k] = PlayerOut(sport, game_id, team, display, _athlete_id(ath), "injury", k in starters, "injuries", stamp)
    return list(results.values())


def _toi_seconds(value: str | None) -> int:
    if not value or ":" not in str(value):
        return 0
    mins, _, secs = str(value).partition(":")
    try:
        return int(mins) * 60 + int(secs)
    except ValueError:
        return 0


def _hockey(sport: str, game_id: str, summary: Mapping[str, Any]) -> list[PlayerOut]:
    results: dict[tuple[str, str], PlayerOut] = {}
    goalies: dict[str, list[Mapping[str, Any]]] = {}
    goalie_names: set[tuple[str, str]] = set()
    for team, name, cat, entry in _box_athletes(summary):
        if "goal" not in name.lower():
            continue
        ath = entry.get("athlete") or {}
        goalie_names.add((team, normalize_name(ath.get("displayName"))))
        if _toi_seconds(_stat(cat, entry, "TOI")) > 0:
            goalies.setdefault(team, []).append(ath)
    for team, played in goalies.items():
        if len(played) < 2:
            continue
        for ath in played:
            display = str(ath.get("displayName") or "")
            results[(team, normalize_name(display))] = PlayerOut(
                sport, game_id, team, display, _athlete_id(ath), "goalie_change", True, "boxscore"
            )
    for team, ath, _status, stamp in _ingame_injuries(summary, sport):
        display = str(ath.get("displayName") or "")
        k = (team, normalize_name(display))
        if display and k not in results:
            results[k] = PlayerOut(sport, game_id, team, display, _athlete_id(ath), "injury", k in goalie_names, "injuries", stamp)
    return list(results.values())


def _soccer(sport: str, game_id: str, summary: Mapping[str, Any]) -> list[PlayerOut]:
    teams = _team_abbrevs(summary)
    results: dict[tuple[str, str], PlayerOut] = {}
    for event in summary.get("keyEvents") or []:
        etype = str(((event.get("type") or {}).get("text")) or "").strip()
        if etype != "Red Card":
            continue
        team = teams.get(str(((event.get("team") or {}).get("id")) or ""), "")
        for part in event.get("participants") or []:
            ath = part.get("athlete") or {}
            display = str(ath.get("displayName") or "")
            if display:
                results[(team, normalize_name(display))] = PlayerOut(
                    sport, game_id, team, display, _athlete_id(ath), "red_card", True, "keyEvents",
                    str(((event.get("clock") or {}).get("displayValue")) or "") or None,
                )
    for roster in summary.get("rosters") or []:
        team = str(((roster.get("team") or {}).get("abbreviation")) or "")
        for entry in roster.get("roster") or []:
            pos = str(((entry.get("position") or {}).get("abbreviation")) or "")
            if pos == "G" and entry.get("starter") and entry.get("subbedOut"):
                ath = entry.get("athlete") or {}
                display = str(ath.get("displayName") or "")
                k = (team, normalize_name(display))
                if display and k not in results:
                    results[k] = PlayerOut(sport, game_id, team, display, _athlete_id(ath), "keeper_change", True, "rosters")
    return list(results.values())


# --------------------------------------------------------------------------- NHL api-web

_NHL_LIVE_STATES = frozenset({"LIVE", "CRIT"})


def exits_from_nhl_boxscore(boxscore: Mapping[str, Any] | None, *, require_in_progress: bool = True) -> GameExitStatus:
    """The NHL live path reads ``api-web.nhle.com/v1/gamecenter/{id}/boxscore``, not ESPN.

    Each goalie carries ``starter`` and ``toi``. Once a NON-starter goalie has ice time, the starter
    has left (pulled or hurt): he is out, KEY. An empty-net pull adds no goalie to the box, so it
    never fires this. Measured on a real final (2025021309): Vejmelka starter 40:00, Vanecek 18:31.
    """
    box = boxscore or {}
    gid = str(box.get("id") or "")
    live = str(box.get("gameState") or "").upper() in _NHL_LIVE_STATES

    def team_name(side: str) -> str:
        t = box.get(side) or {}
        place = str(((t.get("placeName") or {}).get("default")) or "")
        common = str(((t.get("commonName") or {}).get("default")) or "")
        return " ".join(x for x in (place, common) if x)

    home, away = team_name("homeTeam"), team_name("awayTeam")
    if require_in_progress and not live:
        return GameExitStatus("nhl", gid, live, (), home, away)
    out: list[PlayerOut] = []
    stats = box.get("playerByGameStats") or {}
    for side in ("homeTeam", "awayTeam"):
        abbr = str(((box.get(side) or {}).get("abbrev")) or "")
        goalies = list(((stats.get(side) or {}).get("goalies")) or [])
        relief_played = any(not g.get("starter") and _toi_seconds(g.get("toi")) > 0 for g in goalies)
        if not relief_played:
            continue
        for g in goalies:
            if g.get("starter"):
                name = str(((g.get("name") or {}).get("default")) or "")
                pid = g.get("playerId")
                out.append(PlayerOut("nhl", gid, abbr, name, str(pid) if pid is not None else None,
                                     "goalie_change", True, "boxscore"))
    return GameExitStatus("nhl", gid, True, tuple(sorted(out, key=lambda p: (p.team, p.player))), home, away)


_DISPATCH = {}
_DISPATCH.update({s: _football for s in FOOTBALL})
_DISPATCH.update({s: _basketball for s in BASKETBALL})
_DISPATCH.update({s: _hockey for s in HOCKEY})
_DISPATCH.update({s: _soccer for s in SOCCER})


def exits_from_espn_summary(
    sport: str,
    summary: Mapping[str, Any] | None,
    *,
    game_id: str | None = None,
    require_in_progress: bool = True,
) -> GameExitStatus:
    """Players out of this game right now, from one ESPN summary payload.

    ``require_in_progress=False`` is for replaying a FINAL payload in tests and
    backfills; live call sites leave it True so a pregame or final payload never
    refuses anything.
    """
    sport_key = str(sport or "").strip().lower()
    summary = summary or {}
    gid = str(game_id or (summary.get("header") or {}).get("id") or "")
    live = _in_progress(summary)
    home, away = _home_away_names(summary)
    fn = _DISPATCH.get(sport_key)
    if fn is None or (require_in_progress and not live):
        return GameExitStatus(sport_key, gid, live, (), home, away)
    players = tuple(sorted(fn(sport_key, gid, summary), key=lambda p: (p.team, p.player)))
    return GameExitStatus(sport_key, gid, True, players, home, away)
