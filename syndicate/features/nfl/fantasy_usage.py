"""Per-player and per-team season USAGE, aggregated from real nflverse
play-by-play.

This is the bottom of the fantasy projection stack: it turns ~46,000 raw plays
per season into two small dataclasses per subject, and nothing above it ever
reads a play again. It is deliberately a separate module from
``syndicate/features/nfl/player_stats.py`` -- that one answers "what is this
player's rolling rate for one prop market, this season, before week N" for a
live prop card, and its ``player_rate`` is same-season-only with a two-game
floor by design. A season projection needs the opposite shape: whole-season
totals across MULTIPLE seasons, including opportunity denominators
(``targets``, ``rz_carries``) that no prop market prices and that
``player_stats`` therefore never extracts.

The two read the same source file and neither wraps the other, so the numbers
here are re-derived rather than inherited. That is a real duplication cost,
taken knowingly: sharing the extractor would have meant widening a
production prop path (`#471`, backtested over 152,919 rows) to carry fields it
does not use.

**Substrate discipline** (``model_engine_standard.md`` s3b): every value here
is read from ``tracking/nflverse/pbp/pbp_{season}.csv`` resolved through
``syndicate.features.nfl.sources.nfl_pbp_path`` -- which searches candidates
PER FILE, the `#441` fix. ``tracking/`` is gitignored, so on Render this file
exists only on the mounted disk. A caller that gets zero plays back is being
told something about its own checkout, not about production, and
``usage_substrate`` says which path was actually read.
"""

from __future__ import annotations

import csv
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from dataclasses import fields as dataclass_fields
from functools import lru_cache
import json
from pathlib import Path
from typing import Any
from typing import Iterator

from syndicate.features.nfl.sources import nfl_pbp_path


# Red zone / goal line, in nflverse's ``yardline_100`` units (distance to the
# opponent's goal line). These are the standard analytics cuts, not tuned
# constants -- they define WHERE an opportunity happened, and the tuning
# happens downstream in how much a red-zone touch is worth.
RED_ZONE_YARDLINE = 20.0
GOAL_LINE_YARDLINE = 5.0


@dataclass
class PlayerSeasonUsage:
    """One player's whole-season offensive usage.

    Every field is a RAW COUNT or SUM, never a rate. Rates are computed
    downstream where the denominator choice is a modelling decision that has to
    be visible; baking them in here would hide it.
    """

    player_id: str = ""
    player_name: str = ""
    team: str = ""
    season: int = 0
    #: Only meaningful on a per-GAME line; 0 on a summed season record.
    week: int = 0
    games: int = 0

    # passing
    pass_attempts: float = 0.0
    pass_completions: float = 0.0
    pass_yards: float = 0.0
    pass_tds: float = 0.0
    interceptions: float = 0.0
    sacks_taken: float = 0.0
    pass_2pt: float = 0.0

    # rushing
    carries: float = 0.0
    rush_yards: float = 0.0
    rush_tds: float = 0.0
    rush_2pt: float = 0.0

    # receiving
    targets: float = 0.0
    receptions: float = 0.0
    rec_yards: float = 0.0
    rec_tds: float = 0.0
    rec_air_yards: float = 0.0
    rec_2pt: float = 0.0

    # high-leverage opportunity (the TD-share denominators)
    rz_carries: float = 0.0
    rz_targets: float = 0.0
    gl_carries: float = 0.0
    gl_targets: float = 0.0

    # negative
    fumbles_lost: float = 0.0

    # kicking. `fg_att` is the summed total, kept as its own field so field
    # goals can be an opportunity POOL on the same footing as targets and
    # carries -- the projection ranks kickers by it.
    fg_att: float = 0.0
    fg_att_0_39: float = 0.0
    fg_made_0_39: float = 0.0
    fg_att_40_49: float = 0.0
    fg_made_40_49: float = 0.0
    fg_att_50_plus: float = 0.0
    fg_made_50_plus: float = 0.0
    pat_att: float = 0.0
    pat_made: float = 0.0

    # bookkeeping, not modelled
    game_ids: set[str] = field(default_factory=set, repr=False, compare=False)


@dataclass
class TeamSeasonUsage:
    """One team's whole-season offensive volume and defensive production.

    ``points_for``/``points_against`` are filled from the SCHEDULE, not from
    summing pbp scoring plays -- the schedule's final scores are the settled
    truth and cannot drift from a missed two-point or safety attribution.
    """

    team: str = ""
    season: int = 0
    #: Only meaningful on a per-GAME line; 0 on a summed season record.
    week: int = 0
    games: int = 0

    # offensive volume
    off_plays: float = 0.0
    dropbacks: float = 0.0
    pass_attempts: float = 0.0
    carries: float = 0.0
    targets: float = 0.0
    sacks_taken: float = 0.0

    pass_yards: float = 0.0
    rush_yards: float = 0.0
    pass_tds: float = 0.0
    rush_tds: float = 0.0
    interceptions_thrown: float = 0.0
    fumbles_lost: float = 0.0

    rz_carries: float = 0.0
    rz_targets: float = 0.0
    gl_carries: float = 0.0
    gl_targets: float = 0.0

    # scoring, from the schedule
    points_for: float = 0.0
    points_against: float = 0.0

    # kicking
    fg_att: float = 0.0
    fg_made: float = 0.0
    pat_att: float = 0.0
    pat_made: float = 0.0

    # defense / special teams (the D/ST scoring inputs)
    def_sacks: float = 0.0
    def_interceptions: float = 0.0
    def_fumble_recoveries: float = 0.0
    def_safeties: float = 0.0
    def_touchdowns: float = 0.0
    def_blocked_kicks: float = 0.0

    game_ids: set[str] = field(default_factory=set, repr=False, compare=False)


# Columns actually read out of the pbp. Named explicitly so a schema change
# upstream fails loudly at load rather than silently zeroing a field -- the
# exact ``.get(key, 1.0)`` failure shape ``model_engine_standard.md`` s4.2
# describes.
_PBP_COLUMNS: tuple[str, ...] = (
    "game_id",
    "season_type",
    "week",
    "posteam",
    "defteam",
    "yardline_100",
    "play_type",
    "passer_player_id",
    "passer_player_name",
    "rusher_player_id",
    "rusher_player_name",
    "receiver_player_id",
    "receiver_player_name",
    "kicker_player_id",
    "kicker_player_name",
    "passing_yards",
    "rushing_yards",
    "receiving_yards",
    "air_yards",
    "pass_attempt",
    "rush_attempt",
    "complete_pass",
    "pass_touchdown",
    "rush_touchdown",
    "touchdown",
    "td_team",
    "td_player_id",
    "interception",
    "sack",
    "safety",
    "fumble_lost",
    "fumbled_1_player_id",
    "fumbled_1_team",
    "fumble_recovery_1_team",
    "two_point_attempt",
    "two_point_conv_result",
    "field_goal_attempt",
    "field_goal_result",
    "kick_distance",
    "extra_point_attempt",
    "extra_point_result",
    "return_touchdown",
    "return_team",
)


def _number(raw: str | None) -> float:
    if not raw or raw == "NA":
        return 0.0
    try:
        return float(raw)
    except ValueError:
        return 0.0


def _text(raw: str | None) -> str:
    if not raw or raw == "NA":
        return ""
    return raw


def iter_pbp_rows(season: int) -> Iterator[dict[str, str]]:
    """Stream the regular-season plays for *season*, trimmed to the columns
    this module reads.

    Uses ``csv.reader`` plus a column-index map rather than ``DictReader``:
    the pbp is 372 columns wide and ~50,000 rows, so ``DictReader`` builds
    ~18 million throwaway dict entries per season. Yields nothing at all when
    the file is absent -- see the module docstring on what a zero means.
    """
    path = nfl_pbp_path(season)
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration:
            return
        index = {name: position for position, name in enumerate(header)}
        missing = [name for name in _PBP_COLUMNS if name not in index]
        if missing:
            raise ValueError(
                f"nflverse pbp schema changed: {path} is missing {missing}. "
                "Fix the column list in fantasy_usage._PBP_COLUMNS rather than "
                "letting these fields silently read as zero."
            )
        wanted = [(name, index[name]) for name in _PBP_COLUMNS]
        season_type_at = index["season_type"]
        for row in reader:
            if len(row) <= season_type_at or row[season_type_at] != "REG":
                continue
            yield {name: row[position] for name, position in wanted}


def _fg_bucket(distance: float) -> str:
    if distance >= 50.0:
        return "50_plus"
    if distance >= 40.0:
        return "40_49"
    return "0_39"


def _schedule_scores(season: int) -> dict[str, tuple[str, str, float, float]]:
    """``game_id -> (away_team, home_team, away_score, home_score)`` from the
    nflverse schedule. The settled final score, not a pbp reconstruction."""
    from syndicate.features.nfl.fantasy_schedule import load_schedule_rows

    scores: dict[str, tuple[str, str, float, float]] = {}
    for row in load_schedule_rows(season):
        away = _text(row.get("away_score"))
        home = _text(row.get("home_score"))
        if not away or not home:
            continue
        scores[row["game_id"]] = (row["away_team"], row["home_team"], float(away), float(home))
    return scores


#: Fields summed from per-game lines into a season total. Everything on
#: ``PlayerSeasonUsage`` except identity, ``games`` (a count of lines, not a
#: sum) and the bookkeeping set.
_PLAYER_SUM_FIELDS: tuple[str, ...] = tuple(
    spec.name
    for spec in dataclass_fields(PlayerSeasonUsage)
    if spec.name not in {"player_id", "player_name", "team", "season", "week", "games", "game_ids"}
)

_TEAM_SUM_FIELDS: tuple[str, ...] = tuple(
    spec.name
    for spec in dataclass_fields(TeamSeasonUsage)
    if spec.name
    not in {"team", "season", "week", "games", "game_ids", "points_for", "points_against"}
)


def build_season_game_lines(
    season: int,
) -> tuple[dict[tuple[str, str], PlayerSeasonUsage], dict[tuple[str, str], TeamSeasonUsage]]:
    """Aggregate one season of real plays into PER-GAME lines.

    Keyed by ``(player_id, game_id)`` and ``(team, game_id)``. Season totals
    are derived from these by summing, so there is exactly one accumulation
    path and no way for a season total to drift from the games that compose it
    -- ``tests/test_nfl_fantasy_usage.py`` asserts that identity directly.

    Per-game lines are not a by-product: the weekly projection grades against
    them, the season projection's variance is estimated from them, and the
    backtest needs them to score a week under an arbitrary scoring profile.

    Returns empty dicts when the pbp for *season* is not on this substrate.
    Callers must treat that as UNMEASURED, never as zero usage.
    """
    players: dict[tuple[str, str], PlayerSeasonUsage] = {}
    teams: dict[tuple[str, str], TeamSeasonUsage] = {}
    current_game: dict[str, str] = {"id": "", "week": "0"}

    def player(player_id: str, name: str, team: str) -> PlayerSeasonUsage:
        key = (player_id, current_game["id"])
        entry = players.get(key)
        if entry is None:
            entry = PlayerSeasonUsage(
                player_id=player_id,
                player_name=name,
                season=season,
                week=int(current_game["week"] or 0),
            )
            entry.game_ids.add(current_game["id"])
            players[key] = entry
        if name and not entry.player_name:
            entry.player_name = name
        if team:
            entry.team = team
        return entry

    def team_entry(team: str) -> TeamSeasonUsage:
        key = (team, current_game["id"])
        entry = teams.get(key)
        if entry is None:
            entry = TeamSeasonUsage(
                team=team,
                season=season,
                week=int(current_game["week"] or 0),
            )
            entry.game_ids.add(current_game["id"])
            teams[key] = entry
        return entry

    for row in iter_pbp_rows(season):
        current_game["id"] = row["game_id"]
        current_game["week"] = row["week"]
        game_id = row["game_id"]
        posteam = _text(row["posteam"])
        defteam = _text(row["defteam"])
        yardline = _number(row["yardline_100"])
        in_red_zone = 0.0 < yardline <= RED_ZONE_YARDLINE
        in_goal_line = 0.0 < yardline <= GOAL_LINE_YARDLINE

        if posteam:
            offense = team_entry(posteam)
            offense.game_ids.add(game_id)
        if defteam:
            defense = team_entry(defteam)
            defense.game_ids.add(game_id)

        # ---- two-point conversions: scored, but they are not pass/rush
        # attempts in nflverse and must not inflate any volume denominator.
        if _number(row["two_point_attempt"]) == 1.0:
            if row["two_point_conv_result"] == "success":
                passer_id = _text(row["passer_player_id"])
                rusher_id = _text(row["rusher_player_id"])
                receiver_id = _text(row["receiver_player_id"])
                if passer_id:
                    player(passer_id, _text(row["passer_player_name"]), posteam).pass_2pt += 1.0
                if receiver_id:
                    player(receiver_id, _text(row["receiver_player_name"]), posteam).rec_2pt += 1.0
                if rusher_id and not passer_id:
                    player(rusher_id, _text(row["rusher_player_name"]), posteam).rush_2pt += 1.0
            continue

        # ---- passing / receiving
        if _number(row["pass_attempt"]) == 1.0 and _number(row["sack"]) != 1.0:
            passer_id = _text(row["passer_player_id"])
            receiver_id = _text(row["receiver_player_id"])
            complete = _number(row["complete_pass"]) == 1.0
            pass_yards = _number(row["passing_yards"])
            pass_td = _number(row["pass_touchdown"]) == 1.0
            interception = _number(row["interception"]) == 1.0

            if posteam:
                offense = team_entry(posteam)
                offense.pass_attempts += 1.0
                offense.dropbacks += 1.0
                offense.off_plays += 1.0
                offense.pass_yards += pass_yards
                if pass_td:
                    offense.pass_tds += 1.0
                if interception:
                    offense.interceptions_thrown += 1.0
                if receiver_id:
                    offense.targets += 1.0
                    if in_red_zone:
                        offense.rz_targets += 1.0
                    if in_goal_line:
                        offense.gl_targets += 1.0

            if passer_id:
                entry = player(passer_id, _text(row["passer_player_name"]), posteam)
                entry.game_ids.add(game_id)
                entry.pass_attempts += 1.0
                entry.pass_yards += pass_yards
                if complete:
                    entry.pass_completions += 1.0
                if pass_td:
                    entry.pass_tds += 1.0
                if interception:
                    entry.interceptions += 1.0

            if receiver_id:
                entry = player(receiver_id, _text(row["receiver_player_name"]), posteam)
                entry.game_ids.add(game_id)
                entry.targets += 1.0
                entry.rec_air_yards += _number(row["air_yards"])
                if in_red_zone:
                    entry.rz_targets += 1.0
                if in_goal_line:
                    entry.gl_targets += 1.0
                if complete:
                    entry.receptions += 1.0
                    entry.rec_yards += _number(row["receiving_yards"])
                    if pass_td:
                        entry.rec_tds += 1.0

        # ---- sacks (a dropback, not a pass attempt)
        if _number(row["sack"]) == 1.0:
            if posteam:
                offense = team_entry(posteam)
                offense.sacks_taken += 1.0
                offense.dropbacks += 1.0
                offense.off_plays += 1.0
            if defteam:
                team_entry(defteam).def_sacks += 1.0
            passer_id = _text(row["passer_player_id"])
            if passer_id:
                entry = player(passer_id, _text(row["passer_player_name"]), posteam)
                entry.game_ids.add(game_id)
                entry.sacks_taken += 1.0

        # ---- rushing
        if _number(row["rush_attempt"]) == 1.0:
            rusher_id = _text(row["rusher_player_id"])
            rush_yards = _number(row["rushing_yards"])
            rush_td = _number(row["rush_touchdown"]) == 1.0
            if posteam:
                offense = team_entry(posteam)
                offense.carries += 1.0
                offense.off_plays += 1.0
                offense.rush_yards += rush_yards
                if rush_td:
                    offense.rush_tds += 1.0
                if in_red_zone:
                    offense.rz_carries += 1.0
                if in_goal_line:
                    offense.gl_carries += 1.0
            if rusher_id:
                entry = player(rusher_id, _text(row["rusher_player_name"]), posteam)
                entry.game_ids.add(game_id)
                entry.carries += 1.0
                entry.rush_yards += rush_yards
                if rush_td:
                    entry.rush_tds += 1.0
                if in_red_zone:
                    entry.rz_carries += 1.0
                if in_goal_line:
                    entry.gl_carries += 1.0

        # ---- turnovers charged to the offensive player who lost the ball
        if _number(row["fumble_lost"]) == 1.0:
            fumbler_id = _text(row["fumbled_1_player_id"])
            fumble_team = _text(row["fumbled_1_team"])
            if fumbler_id and fumble_team == posteam:
                player(fumbler_id, "", posteam).fumbles_lost += 1.0
            if posteam:
                team_entry(posteam).fumbles_lost += 1.0
            recovery_team = _text(row["fumble_recovery_1_team"])
            if recovery_team and recovery_team == defteam:
                team_entry(defteam).def_fumble_recoveries += 1.0

        if _number(row["interception"]) == 1.0 and defteam:
            team_entry(defteam).def_interceptions += 1.0

        if _number(row["safety"]) == 1.0 and defteam:
            team_entry(defteam).def_safeties += 1.0

        # ---- defensive / return touchdowns: credited to whichever team
        # scored, which on these plays is NOT the team with possession.
        if _number(row["touchdown"]) == 1.0:
            td_team = _text(row["td_team"])
            if td_team and posteam and td_team != posteam:
                team_entry(td_team).def_touchdowns += 1.0
        elif _number(row["return_touchdown"]) == 1.0:
            return_team = _text(row["return_team"])
            if return_team:
                team_entry(return_team).def_touchdowns += 1.0

        # ---- kicking
        if _number(row["field_goal_attempt"]) == 1.0:
            kicker_id = _text(row["kicker_player_id"])
            result = row["field_goal_result"]
            bucket = _fg_bucket(_number(row["kick_distance"]))
            if posteam:
                offense = team_entry(posteam)
                offense.fg_att += 1.0
                if result == "made":
                    offense.fg_made += 1.0
            if result == "blocked" and defteam:
                team_entry(defteam).def_blocked_kicks += 1.0
            if kicker_id:
                entry = player(kicker_id, _text(row["kicker_player_name"]), posteam)
                entry.game_ids.add(game_id)
                entry.fg_att += 1.0
                setattr(entry, f"fg_att_{bucket}", getattr(entry, f"fg_att_{bucket}") + 1.0)
                if result == "made":
                    setattr(entry, f"fg_made_{bucket}", getattr(entry, f"fg_made_{bucket}") + 1.0)

        if _number(row["extra_point_attempt"]) == 1.0:
            kicker_id = _text(row["kicker_player_id"])
            result = row["extra_point_result"]
            if posteam:
                offense = team_entry(posteam)
                offense.pat_att += 1.0
                if result == "good":
                    offense.pat_made += 1.0
            if result == "blocked" and defteam:
                team_entry(defteam).def_blocked_kicks += 1.0
            if kicker_id:
                entry = player(kicker_id, _text(row["kicker_player_name"]), posteam)
                entry.game_ids.add(game_id)
                entry.pat_att += 1.0
                if result == "good":
                    entry.pat_made += 1.0

    scores = _schedule_scores(season)
    for (team, game_id), entry in teams.items():
        entry.games = 1
        row = scores.get(game_id)
        if row is None:
            continue
        away_team, home_team, away_score, home_score = row
        if team == home_team:
            entry.points_for = home_score
            entry.points_against = away_score
        elif team == away_team:
            entry.points_for = away_score
            entry.points_against = home_score

    for entry in players.values():
        entry.games = 1

    return players, teams


def _sum_lines(lines: list[Any], kind: type, fields: tuple[str, ...], **identity: Any) -> Any:
    """Sum a list of per-game lines into one season record."""
    total = kind(**identity)
    for line in lines:
        for name in fields:
            setattr(total, name, getattr(total, name) + getattr(line, name))
        total.game_ids |= line.game_ids
    total.games = len(total.game_ids)
    return total


def build_season_usage(season: int) -> tuple[dict[str, PlayerSeasonUsage], dict[str, TeamSeasonUsage]]:
    """Season totals for every player and team, summed from per-game lines.

    A player's ``team`` is the team of his LAST game that season, which is what
    a mid-season trade should leave behind: his usage history is real wherever
    it happened, and where he plays NEXT is a roster question this module does
    not answer (``fantasy_players`` does).
    """
    player_lines, team_lines = build_season_game_lines(season)

    by_player: dict[str, list[PlayerSeasonUsage]] = {}
    for (player_id, _), line in player_lines.items():
        by_player.setdefault(player_id, []).append(line)
    by_team: dict[str, list[TeamSeasonUsage]] = {}
    for (team, _), line in team_lines.items():
        by_team.setdefault(team, []).append(line)

    players: dict[str, PlayerSeasonUsage] = {}
    for player_id, lines in by_player.items():
        lines.sort(key=lambda line: sorted(line.game_ids))
        name = next((line.player_name for line in lines if line.player_name), "")
        last_team = next((line.team for line in reversed(lines) if line.team), "")
        players[player_id] = _sum_lines(
            lines,
            PlayerSeasonUsage,
            _PLAYER_SUM_FIELDS,
            player_id=player_id,
            player_name=name,
            team=last_team,
            season=season,
        )

    teams: dict[str, TeamSeasonUsage] = {}
    for team, lines in by_team.items():
        total = _sum_lines(lines, TeamSeasonUsage, _TEAM_SUM_FIELDS, team=team, season=season)
        total.points_for = sum(line.points_for for line in lines)
        total.points_against = sum(line.points_against for line in lines)
        teams[team] = total

    return players, teams


def usage_substrate(season: int) -> dict[str, Any]:
    """What was actually read, so a caller can name its substrate.

    ``model_engine_standard.md`` s3b: a claim that does not name its substrate
    is not yet a claim.
    """
    path = nfl_pbp_path(season)
    return {
        "season": season,
        "path": str(path),
        "exists": path.is_file(),
        "bytes": path.stat().st_size if path.is_file() else 0,
    }


# ---------------------------------------------------------------------------
# Cached artifact
# ---------------------------------------------------------------------------

def usage_artifact_path(season: int) -> Path:
    """Where the built usage document lives.

    Under the NFL source root's ``fantasy/`` tree so it publishes and reads
    through the same ``SYNDICATE_NFL_SOURCE_ROOT`` / mounted-disk mechanism as
    every other NFL artifact. ONE DOCUMENT PER SEASON, not per week --
    ``model_engine_standard.md`` s3 asks for bounded artifacts because the
    allowlist drives publishing as well as reading.
    """
    from syndicate.features.nfl.sources import default_nfl_source_root

    return default_nfl_source_root() / "fantasy" / f"nfl_fantasy_usage_{season}.json"


def _strip(entry: Any, game_id: str | None = None) -> dict[str, Any]:
    payload = asdict(entry)
    payload.pop("game_ids", None)
    if game_id is not None:
        payload["game_id"] = game_id
    # Season records carry no meaningful week; drop it rather than serialise a
    # zero that reads like week 0.
    if game_id is None:
        payload.pop("week", None)
    return payload


def write_usage_artifact(season: int) -> Path:
    """Build from pbp and write the season's usage document. Returns the path.

    Carries BOTH the season totals and the per-game lines they were summed
    from. One document per season -- ``model_engine_standard.md`` s3 prefers a
    bounded per-season artifact over per-date fan-out, because the allowlist
    drives publishing as well as reading and this repo's egress history is
    expensive (`#322`).
    """
    player_lines, team_lines = build_season_game_lines(season)
    players, teams = build_season_usage(season)
    payload = {
        "season": season,
        "substrate": usage_substrate(season),
        "players": {key: _strip(value) for key, value in players.items()},
        "teams": {key: _strip(value) for key, value in teams.items()},
        "player_game_lines": [
            _strip(value, game_id) for (_, game_id), value in sorted(player_lines.items())
        ],
        "team_game_lines": [
            _strip(value, game_id) for (_, game_id), value in sorted(team_lines.items())
        ],
    }
    path = usage_artifact_path(season)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    return path


def _from_payload(payload: dict[str, Any], kind: type) -> Any:
    names = {spec.name for spec in dataclass_fields(kind)} - {"game_ids"}
    entry = kind(**{key: value for key, value in payload.items() if key in names})
    game_id = payload.get("game_id")
    if game_id:
        entry.game_ids.add(game_id)
        entry.games = 1
    return entry


@lru_cache(maxsize=8)
def _load_usage_payload(season: int) -> dict[str, Any] | None:
    """The raw usage document for *season*, or ``None`` when it is absent.

    The web service must always land here rather than in ``build_season_usage``:
    a full pbp parse inside a request handler is exactly the heavy computation
    the worker-split rule forbids. ``SYNDICATE_NFL_FANTASY_USAGE_STRICT=1``
    turns the pbp fallback off so that violation fails loudly instead of just
    running slowly.
    """
    path = usage_artifact_path(season)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _fallback_allowed() -> bool:
    import os

    return os.environ.get("SYNDICATE_NFL_FANTASY_USAGE_STRICT") != "1"


@lru_cache(maxsize=8)
def load_season_usage(season: int) -> tuple[dict[str, PlayerSeasonUsage], dict[str, TeamSeasonUsage]]:
    """Season totals, from the cached artifact when present."""
    payload = _load_usage_payload(season)
    if payload:
        players = {
            key: _from_payload(value, PlayerSeasonUsage)
            for key, value in (payload.get("players") or {}).items()
        }
        teams = {
            key: _from_payload(value, TeamSeasonUsage)
            for key, value in (payload.get("teams") or {}).items()
        }
        return players, teams
    if not _fallback_allowed():
        raise RuntimeError(
            f"no usage artifact at {usage_artifact_path(season)} and the pbp fallback is "
            "disabled. Run scripts/build_nfl_fantasy_usage.py on the worker."
        )
    return build_season_usage(season)


@lru_cache(maxsize=4)
def load_season_game_lines(
    season: int,
) -> tuple[tuple[PlayerSeasonUsage, ...], tuple[TeamSeasonUsage, ...]]:
    """Per-game player and team lines, from the cached artifact when present.

    These are what the weekly projection grades against and what the season
    projection's per-game variance is estimated from.
    """
    payload = _load_usage_payload(season)
    if payload:
        players = tuple(
            _from_payload(entry, PlayerSeasonUsage) for entry in (payload.get("player_game_lines") or [])
        )
        teams = tuple(
            _from_payload(entry, TeamSeasonUsage) for entry in (payload.get("team_game_lines") or [])
        )
        return players, teams
    if not _fallback_allowed():
        raise RuntimeError(
            f"no usage artifact at {usage_artifact_path(season)} and the pbp fallback is "
            "disabled. Run scripts/build_nfl_fantasy_usage.py on the worker."
        )
    player_lines, team_lines = build_season_game_lines(season)
    return tuple(player_lines.values()), tuple(team_lines.values())
