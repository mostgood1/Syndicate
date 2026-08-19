"""Per-team EVEN-STRENGTH faceoff win-rate index from the `playbyplay` endpoint.

WHY THIS EXISTS. `engine.py`'s faceoff-driven shot-share adjustment
(`_faceoff_multipliers`) is gated `faceoff_ev_only=True` -- it is ONLY applied
during even-strength segments. But the input feeding it, `TeamRates.faceoff_win_pct`
(`historical_truth/team_game_rates.py`), is an ALL-SITUATIONS blend (every faceoff
the team took, PP/PK/EV together) -- a real mismatch between what the mechanism
claims to model and what the data it reads actually measures. This module closes
that gap: a genuinely EV-SPECIFIC per-team signal, parsed from the SAME
`playbyplay` cache the block/shot-index work already bulk-fetched (no new fetch).

WHY AN INDEX (ratio to league average), NOT A RAW PERCENTAGE. Consistent with
every other per-team signal this session built (`block_rate_index`,
`pp_shot_index`/`pk_shot_index_allowed`) -- a ratio centered at 1.0 is easy to
sanity-check (mean should land near 1.0) and easy to reason about when layering a
new signal on top of an existing mechanism. `engine.py` converts the index back to
an effective win percentage (`0.5 * index`, clamped) at the point of use, since
`_faceoff_multipliers` itself operates on percentages, not indices.

STRENGTH STATE FROM `situationCode`, NOT GUESSED. Each `playbyplay` faceoff event
carries a 4-digit `situationCode`: `[awayGoalieInNet][awaySkaters][homeSkaters]
[homeGoalieInNet]` (e.g. `"1551"` = 5v5 EV, `"1451"` = home team on the power play,
`"1541"` = away team on the power play -- confirmed against a real cached game,
not assumed from documentation). EVEN STRENGTH is defined as `away_skaters ==
home_skaters` (covers 5v5/4v4/3v3 alike, the standard hockey definition), matching
the same "not a power play for either side" condition `engine.py`'s own
`seg_is_home_pp`/`seg_is_away_pp` flags represent -- this module's ground truth and
the engine's own segment classification are conceptually the same split, just
computed from real historical data here instead of simulated on the fly there.

OFFENSIVE-ZONE WIN INDEX (`compute_team_faceoff_oz_index`), added in a second pass.
Not every faceoff win is equally valuable: winning a draw in your OWN offensive zone
sets up an immediate shot chance, winning it in your own defensive zone mostly just
PREVENTS one against you, and a neutral-zone win is somewhere in between. The flat
EV index above blends all three together. `_faceoff_multipliers` specifically boosts
the WINNING team's OWN shot generation, so the offensive-zone-specific win rate is
the more theoretically correct input for that mechanism -- this is a refinement of
what feeds the SAME consumption point, not a second, separately-wired signal.

`zoneCode` IS RELATIVE TO THE WINNER, CONFIRMED EMPIRICALLY, NOT ASSUMED. Two
faceoff events at the IDENTICAL `(xCoord, yCoord)` in a real cached game showed
`zoneCode="O"` when the home team won and `zoneCode="D"` when the away team won at
that same physical dot -- proof the label describes the WINNING team's own zone, not
a fixed rink-absolute frame. This means the LOSING team's own zone at that same draw
is the mirror image: `O` and `D` swap, `N` stays `N` (there are only two ends of the
ice and two teams; one team's offensive zone is the other's defensive zone). Losses
are attributed via that flip (`_ZONE_FLIP`), not left unattributed -- every EV
faceoff a team participates in, won or lost, contributes to their own zone-relative
win/total counts.

DEFENSIVE-ZONE WIN INDEX (`compute_team_faceoff_dz_index`), added in a third pass.
NOT the mirror image of the OZ index (a team's OZ and DZ win rates are computed
from DIFFERENT, non-overlapping sets of draws -- a team can be elite at OZ draws and
mediocre at DZ draws, or vice versa -- so this carries genuinely independent
information, not `1 - oz_index`). A team that wins its own DZ draws well typically
clears the puck and starts a breakout, which does TWO things at once: suppresses the
OPPONENT's sustained shot generation from that zone-time (the immediate defensive
value) AND can spring the winning team's own transition/rush chance (real hockey,
not a stretch -- a DZ win is often the first pass of a rush the other way). Because
of that dual effect, this index is applied as an ADDITIONAL multiplicative layer in
`engine.py`, composed with (not replacing) the OZ/EV-driven multiplier above: the
SAME `_faceoff_multipliers` function, fed DZ-specific percentages, with `m_fo_h`
applied to `lam_h` (winning team's own transition-offense bump) and `m_fo_a` applied
to `lam_a` (suppression of the opponent it was won against) -- exactly the existing
function's own semantics, just a second, independent zone-context input rather than
a fourth tier of the OZ/EV/blend fallback chain (which represents one measurement
getting more precise, not a second, additive game mechanism).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Sequence


def _skaters_from_situation_code(code: object) -> Optional[tuple]:
    """`(away_skaters, home_skaters)` from a 4-digit `situationCode` string, or
    `None` if the code is missing/malformed (never raises)."""
    text = str(code or "").strip()
    if len(text) != 4 or not text.isdigit():
        return None
    return int(text[1]), int(text[2])


@dataclass(frozen=True)
class GameFaceoffEvRecord:
    """One finished game's EVEN-STRENGTH faceoff counts, parsed from a
    `playbyplay` payload."""

    game_id: str
    home_abbr: str
    away_abbr: str
    home_ev_wins: int
    away_ev_wins: int

    @property
    def ev_total(self) -> int:
        return self.home_ev_wins + self.away_ev_wins


def parse_playbyplay_faceoffs_ev(payload: Dict) -> Optional[GameFaceoffEvRecord]:
    """Parse one `playbyplay` payload into a :class:`GameFaceoffEvRecord`, EVEN-
    STRENGTH faceoffs only. Returns `None` if the payload is missing team info or
    carries no `plays` list -- never raises. A game with zero EV faceoffs (should
    not happen in practice, but data is data) returns a record with `ev_total==0`
    rather than `None`, so the caller's own floor decides whether to trust it."""
    if not isinstance(payload, dict):
        return None
    home_team = payload.get("homeTeam") or {}
    away_team = payload.get("awayTeam") or {}
    home_id = home_team.get("id")
    away_id = away_team.get("id")
    home_abbr = str(home_team.get("abbrev") or "").upper()
    away_abbr = str(away_team.get("abbrev") or "").upper()
    if home_id is None or away_id is None or not home_abbr or not away_abbr:
        return None
    plays = payload.get("plays")
    if not isinstance(plays, list):
        return None

    home_wins = away_wins = 0
    for play in plays:
        if not isinstance(play, dict) or play.get("typeDescKey") != "faceoff":
            continue
        skaters = _skaters_from_situation_code(play.get("situationCode"))
        if skaters is None or skaters[0] != skaters[1]:
            continue  # not even strength (or malformed code) -- skip, don't guess
        details = play.get("details") or {}
        owner = details.get("eventOwnerTeamId")
        if owner == home_id:
            home_wins += 1
        elif owner == away_id:
            away_wins += 1
        # else: owner unresolved -- skip rather than misattribute

    return GameFaceoffEvRecord(
        game_id=str(payload.get("id") or ""),
        home_abbr=home_abbr, away_abbr=away_abbr,
        home_ev_wins=home_wins, away_ev_wins=away_wins,
    )


def _safe_div(num: float, den: float) -> float:
    return float(num) / float(den) if den else 0.0


# Same small-sample discipline as `boxscore_block_rate`/`boxscore_shot_strength`.
MIN_GAMES_FOR_FACEOFF_INDEX = 10
DEFAULT_FACEOFF_EV_INDEX = 1.0


@dataclass(frozen=True)
class TeamFaceoffEvIndex:
    """Per-team EVEN-STRENGTH faceoff win-rate tendency, normalized against the
    league-wide EV win rate -- 1.0 = league average; >1.0 = wins EV draws more
    than average; <1.0 = less. `engine.py` converts this back to an effective win
    percentage (`0.5 * index`) at the point of use."""

    team: str
    index: float
    games: int
    ev_wins: int
    ev_total: int


def compute_team_faceoff_ev_index(records: Sequence[GameFaceoffEvRecord]) -> Dict[str, TeamFaceoffEvIndex]:
    acc: Dict[str, Dict[str, int]] = {}

    def _touch(team: str) -> Dict[str, int]:
        return acc.setdefault(team, {"games": 0, "ev_wins": 0, "ev_total": 0})

    for r in records:
        h = _touch(r.home_abbr)
        a = _touch(r.away_abbr)
        h["games"] += 1
        a["games"] += 1
        h["ev_wins"] += r.home_ev_wins
        a["ev_wins"] += r.away_ev_wins
        h["ev_total"] += r.ev_total
        a["ev_total"] += r.ev_total

    league_wins = sum(v["ev_wins"] for v in acc.values() if v["games"] >= MIN_GAMES_FOR_FACEOFF_INDEX)
    league_total = sum(v["ev_total"] for v in acc.values() if v["games"] >= MIN_GAMES_FOR_FACEOFF_INDEX)
    league_rate = _safe_div(league_wins, league_total)

    out: Dict[str, TeamFaceoffEvIndex] = {}
    for team, row in acc.items():
        games = row["games"]
        index = DEFAULT_FACEOFF_EV_INDEX
        if games >= MIN_GAMES_FOR_FACEOFF_INDEX and league_rate > 0:
            team_rate = _safe_div(row["ev_wins"], row["ev_total"])
            index = round(team_rate / league_rate, 4)
        out[team] = TeamFaceoffEvIndex(
            team=team, index=index, games=games,
            ev_wins=row["ev_wins"], ev_total=row["ev_total"],
        )
    return out


# ---------------------------------------------------------------------------
# Zone-specific (offensive-zone) win index -- see the module docstring's second
# section for why this exists and why `zoneCode` can be trusted as winner-relative.
# ---------------------------------------------------------------------------

_ZONES = ("O", "N", "D")
_ZONE_FLIP = {"O": "D", "D": "O", "N": "N"}


def _empty_zone_counts() -> Dict[str, int]:
    return {z: 0 for z in _ZONES}


@dataclass(frozen=True)
class GameFaceoffZoneRecord:
    """One finished game's EVEN-STRENGTH faceoff counts, split by zone, from EACH
    team's OWN perspective (`home_zone_*`/`away_zone_*` are not mirror images of a
    single shared frame -- they are independently team-relative, per the module
    docstring's zone-flip note)."""

    game_id: str
    home_abbr: str
    away_abbr: str
    home_zone_wins: Dict[str, int] = field(default_factory=_empty_zone_counts)
    home_zone_total: Dict[str, int] = field(default_factory=_empty_zone_counts)
    away_zone_wins: Dict[str, int] = field(default_factory=_empty_zone_counts)
    away_zone_total: Dict[str, int] = field(default_factory=_empty_zone_counts)


def parse_playbyplay_faceoffs_by_zone(payload: Dict) -> Optional[GameFaceoffZoneRecord]:
    """Parse one `playbyplay` payload into a :class:`GameFaceoffZoneRecord`, EVEN-
    STRENGTH faceoffs only, split by each team's OWN zone. Returns `None` under the
    same conditions as :func:`parse_playbyplay_faceoffs_ev` -- never raises. A
    faceoff with a `zoneCode` outside `{"O","D","N"}` (missing/malformed) is
    skipped entirely (both win and total counts), matching this module's existing
    "skip rather than guess" discipline for an unresolved `eventOwnerTeamId`."""
    if not isinstance(payload, dict):
        return None
    home_team = payload.get("homeTeam") or {}
    away_team = payload.get("awayTeam") or {}
    home_id = home_team.get("id")
    away_id = away_team.get("id")
    home_abbr = str(home_team.get("abbrev") or "").upper()
    away_abbr = str(away_team.get("abbrev") or "").upper()
    if home_id is None or away_id is None or not home_abbr or not away_abbr:
        return None
    plays = payload.get("plays")
    if not isinstance(plays, list):
        return None

    home_wins, home_total = _empty_zone_counts(), _empty_zone_counts()
    away_wins, away_total = _empty_zone_counts(), _empty_zone_counts()

    for play in plays:
        if not isinstance(play, dict) or play.get("typeDescKey") != "faceoff":
            continue
        skaters = _skaters_from_situation_code(play.get("situationCode"))
        if skaters is None or skaters[0] != skaters[1]:
            continue  # not even strength (or malformed code) -- skip, don't guess
        details = play.get("details") or {}
        owner = details.get("eventOwnerTeamId")
        zone = details.get("zoneCode")
        if zone not in _ZONES:
            continue  # missing/malformed zone -- skip rather than guess
        if owner == home_id:
            home_wins[zone] += 1
            home_total[zone] += 1
            away_total[_ZONE_FLIP[zone]] += 1  # away lost it; zone flips to their own frame
        elif owner == away_id:
            away_wins[zone] += 1
            away_total[zone] += 1
            home_total[_ZONE_FLIP[zone]] += 1
        # else: owner unresolved -- skip rather than misattribute (neither side's counts move)

    return GameFaceoffZoneRecord(
        game_id=str(payload.get("id") or ""),
        home_abbr=home_abbr, away_abbr=away_abbr,
        home_zone_wins=home_wins, home_zone_total=home_total,
        away_zone_wins=away_wins, away_zone_total=away_total,
    )


MIN_GAMES_FOR_FACEOFF_OZ_INDEX = 10
DEFAULT_FACEOFF_OZ_INDEX = 1.0


@dataclass(frozen=True)
class TeamFaceoffOzIndex:
    """Per-team OFFENSIVE-ZONE-specific faceoff win-rate tendency (their own zone,
    not a rink-absolute frame), normalized against the league-wide OZ win rate --
    1.0 = league average. The more theoretically correct input for
    `_faceoff_multipliers` than the blended EV index above, since that mechanism
    specifically boosts the WINNING team's own shot generation and an OZ win is
    what most directly causes one."""

    team: str
    index: float
    games: int
    oz_wins: int
    oz_total: int


def compute_team_faceoff_oz_index(records: Sequence[GameFaceoffZoneRecord]) -> Dict[str, TeamFaceoffOzIndex]:
    acc: Dict[str, Dict[str, int]] = {}

    def _touch(team: str) -> Dict[str, int]:
        return acc.setdefault(team, {"games": 0, "oz_wins": 0, "oz_total": 0})

    for r in records:
        h = _touch(r.home_abbr)
        a = _touch(r.away_abbr)
        h["games"] += 1
        a["games"] += 1
        h["oz_wins"] += r.home_zone_wins["O"]
        h["oz_total"] += r.home_zone_total["O"]
        a["oz_wins"] += r.away_zone_wins["O"]
        a["oz_total"] += r.away_zone_total["O"]

    league_wins = sum(v["oz_wins"] for v in acc.values() if v["games"] >= MIN_GAMES_FOR_FACEOFF_OZ_INDEX)
    league_total = sum(v["oz_total"] for v in acc.values() if v["games"] >= MIN_GAMES_FOR_FACEOFF_OZ_INDEX)
    league_rate = _safe_div(league_wins, league_total)

    out: Dict[str, TeamFaceoffOzIndex] = {}
    for team, row in acc.items():
        games = row["games"]
        index = DEFAULT_FACEOFF_OZ_INDEX
        if games >= MIN_GAMES_FOR_FACEOFF_OZ_INDEX and league_rate > 0:
            team_rate = _safe_div(row["oz_wins"], row["oz_total"])
            index = round(team_rate / league_rate, 4)
        out[team] = TeamFaceoffOzIndex(
            team=team, index=index, games=games,
            oz_wins=row["oz_wins"], oz_total=row["oz_total"],
        )
    return out


# ---------------------------------------------------------------------------
# Zone-specific (defensive-zone) win index -- see the module docstring's third
# section for why this is a SEPARATE signal from the OZ index, not its mirror image.
# ---------------------------------------------------------------------------

MIN_GAMES_FOR_FACEOFF_DZ_INDEX = 10
DEFAULT_FACEOFF_DZ_INDEX = 1.0


@dataclass(frozen=True)
class TeamFaceoffDzIndex:
    """Per-team DEFENSIVE-ZONE-specific faceoff win-rate tendency (their own zone, not a
    rink-absolute frame), normalized against the league-wide DZ win rate -- 1.0 = league average.
    Applied in `engine.py` as an ADDITIONAL multiplicative layer alongside the OZ/EV chain, not a
    fourth tier of it -- see the module docstring for why."""

    team: str
    index: float
    games: int
    dz_wins: int
    dz_total: int


def compute_team_faceoff_dz_index(records: Sequence[GameFaceoffZoneRecord]) -> Dict[str, TeamFaceoffDzIndex]:
    acc: Dict[str, Dict[str, int]] = {}

    def _touch(team: str) -> Dict[str, int]:
        return acc.setdefault(team, {"games": 0, "dz_wins": 0, "dz_total": 0})

    for r in records:
        h = _touch(r.home_abbr)
        a = _touch(r.away_abbr)
        h["games"] += 1
        a["games"] += 1
        h["dz_wins"] += r.home_zone_wins["D"]
        h["dz_total"] += r.home_zone_total["D"]
        a["dz_wins"] += r.away_zone_wins["D"]
        a["dz_total"] += r.away_zone_total["D"]

    league_wins = sum(v["dz_wins"] for v in acc.values() if v["games"] >= MIN_GAMES_FOR_FACEOFF_DZ_INDEX)
    league_total = sum(v["dz_total"] for v in acc.values() if v["games"] >= MIN_GAMES_FOR_FACEOFF_DZ_INDEX)
    league_rate = _safe_div(league_wins, league_total)

    out: Dict[str, TeamFaceoffDzIndex] = {}
    for team, row in acc.items():
        games = row["games"]
        index = DEFAULT_FACEOFF_DZ_INDEX
        if games >= MIN_GAMES_FOR_FACEOFF_DZ_INDEX and league_rate > 0:
            team_rate = _safe_div(row["dz_wins"], row["dz_total"])
            index = round(team_rate / league_rate, 4)
        out[team] = TeamFaceoffDzIndex(
            team=team, index=index, games=games,
            dz_wins=row["dz_wins"], dz_total=row["dz_total"],
        )
    return out
