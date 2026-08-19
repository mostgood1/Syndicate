"""Per-player `shot_weight`/`goal_weight`/`block_weight` -- the last 3 genuinely-absent
`HockeyPlayerFeatures` inputs `docs/ai_context/hockeysim_engine_reference.md` §5 tracked.

UNLIKE the team-rates dead gate (§2j), these three are ALREADY reachable: `engine.py`'s
`_weighted_choice` reads them directly to decide WHICH on-ice player gets credited for a shot,
goal, or block, and `_build_game_state` already has a documented fallback when they're absent -- a
POSITION-based heuristic scaled by projected TOI (forwards get more shot-weight, defensemen more
block-weight), not a flat uniform value. That heuristic is reasonable but cannot differentiate a
team's top scorer from its 4th-line grinder at the same position/TOI -- this module replaces it
with real, individually differentiated data where available.

WHY PER-GAME TOTALS, NOT PER-60. `engine.py`'s own comment on the fallback heuristic is explicit:
"weights are interpreted as per-game totals and later divided by proj_toi to produce per-minute
propensities." A player's own average shots/goals/blocks PER GAME is exactly that quantity --
computed here directly, with no unit conversion needed to match what the engine already expects.

WHY BOXSCORE, NOT PLAY-BY-PLAY. The `boxscore` cache's `playerByGameStats.{home,away}Team.
{forwards,defense}[]` already carries `sog`/`goals`/`blockedShots` per skater per game -- the exact
season totals needed, with no shot-location parsing required. Same cache §2e/§2g/§2j already
bulk-fetched; no new fetch.

PER-PLAYER `faceoff_weight` (§2zz), added in a later pass -- the first PLAYER-level dimension the
faceoff mechanism has ever had; every faceoff signal built earlier this session (EV/OZ/DZ/NZ,
strength-state role, the joint role-zone refinement) operates on TEAM-level rates, never on WHICH
SPECIFIC PLAYER is on the ice. `engine.py`'s faceoff mechanism reads `TeamRates.faceoff_win_pct` as
its final fallback tier -- a SEASON-LONG team average, blind to who's actually dressed tonight
(injuries, scratches, line changes). This closes that gap: a genuinely LINEUP-AWARE team percentage,
built from real individual centers' own faceoff win rates.

UNLIKE `shot_weight`/`goal_weight`/`block_weight`, THIS ONE NEEDS PLAY-BY-PLAY, NOT THE BOXSCORE --
a real trap caught before building on it. The boxscore's own `faceoffWinningPctg` field IS present
per skater per game, but it is a PER-GAME RATE with no draws-taken denominator exposed -- a direct
spot-check of 480 real center-games found 22% show an EXACT `0.0` or `1.0`, almost always a game
where that player took only 1-3 draws. Averaging those per-game rates EQUALLY with a 25-draw game
(as a naive `mean(faceoffWinningPctg per game)` would) swamps the real signal with small-sample
noise -- a season "average" built that way put SEVERAL real, active centers at a literal 0.0000
across 68-82 games, which is not plausible for an NHL center (`docs/reports/
hockeysim_player_faceoff_rate_report.md` has the full comparison). Fixed by going to `playbyplay`'s
`details.winningPlayerId`/`losingPlayerId` on every faceoff event instead -- TRUE win/total COUNTS
summed across every game a player appears in, the same "a rate, not a count" discipline this
session's own standing rules require. Player names/positions come from the SAME playbyplay
payload's `rosterSpots` array (no boxscore cross-reference needed) -- display/sanity-check only,
not consumed by the engine (which reads `HockeyPlayerFeatures.position` from the roster/lineup row
directly).

NO EXPLICIT "CENTERS ONLY" FILTER -- THE FLOOR ALREADY DOES THAT WORK. Real hockey: faceoffs are
taken almost exclusively by centers, but the LINEUP data this package's own roster/lineup CSVs
carry only tracks the broad F/D/G class, not the finer C/L/R split (`_canonical_position`,
`features/loaders.py`) -- a real, checked data-availability gap, not an oversight. `MIN_DRAWS_
FOR_PLAYER_FACEOFF_WEIGHT` (100 real draws/season) does this filtering IMPLICITLY: a winger who
takes an occasional emergency draw will not clear 100 real draws across a season, so `faceoff_
weight` is naturally populated almost exclusively for players who actually take draws regularly --
verified directly against real data (measured population is 234-238 players at this floor, matching
the roughly-one-center-per-team-per-line-count order of magnitude, not hundreds of wingers/D).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class PlayerGameRecord:
    """One skater's counting stats from one finished game."""

    player_id: int
    full_name: str
    position: str  # "F" or "D" (goalies excluded -- see parse_boxscore_player_rates)
    shots: int
    goals: int
    blocks: int


def _norm_position(raw: object) -> str:
    token = str(raw or "").strip().upper()
    if token in ("D", "LD", "RD", "DEFENSE", "DEFENCE"):
        return "D"
    return "F"


def _parse_skater_group(group: List[Dict], position: str) -> List[PlayerGameRecord]:
    out: List[PlayerGameRecord] = []
    for p in group or []:
        pid = p.get("playerId")
        if pid is None:
            continue
        try:
            pid_int = int(pid)
            shots = int(p.get("sog") or 0)
            goals = int(p.get("goals") or 0)
            blocks = int(p.get("blockedShots") or 0)
        except (TypeError, ValueError):
            continue
        name = ((p.get("name") or {}).get("default") if isinstance(p.get("name"), dict)
                else p.get("name")) or ""
        out.append(PlayerGameRecord(
            player_id=pid_int, full_name=str(name).strip(), position=position,
            shots=shots, goals=goals, blocks=blocks,
        ))
    return out


def parse_boxscore_player_rates(boxscore: Dict) -> List[PlayerGameRecord]:
    """Parse one `boxscore` payload into per-SKATER game records (pure; never raises). Goalies are
    excluded -- `shot_weight`/`goal_weight`/`block_weight` only feed skater on-ice attribution
    (`_weighted_choice`'s "shot"/"goal"/"block" pools are forwards+defense, never goalies)."""
    if not isinstance(boxscore, dict):
        return []
    pbg = boxscore.get("playerByGameStats") or {}
    out: List[PlayerGameRecord] = []
    for side in ("homeTeam", "awayTeam"):
        skaters = pbg.get(side) or {}
        out.extend(_parse_skater_group(skaters.get("forwards") or [], "F"))
        out.extend(_parse_skater_group(skaters.get("defense") or [], "D"))
    return out


def build_player_game_dataset(payloads: Sequence[Dict]) -> List[PlayerGameRecord]:
    """Parse many `boxscore` payloads into one flat per-player-game dataset (pure)."""
    out: List[PlayerGameRecord] = []
    for payload in payloads:
        out.extend(parse_boxscore_player_rates(payload))
    return out


# A player with few tracked games produces a noisy per-game rate -- same discipline as every other
# small-sample floor in this package (§2g's MIN_GAMES_FOR_BLOCK_INDEX, §2e's opportunity floor).
# Below this, the player is OMITTED from the output entirely, so `build_player_features` falls
# back to engine.py's own position/TOI heuristic for them -- never a guess dressed up as data.
MIN_GAMES_FOR_PLAYER_WEIGHT = 5


@dataclass(frozen=True)
class PlayerRateAggregate:
    player_id: int
    full_name: str
    position: str
    games: int
    shot_weight: float   # shots/game -- the exact quantity engine.py's fallback heuristic computes
    goal_weight: float   # goals/game
    block_weight: float  # blocks/game


def compute_player_rate_aggregates(
    records: Sequence[PlayerGameRecord],
) -> Dict[int, PlayerRateAggregate]:
    """Season aggregate per player. A player who changed position (rare -- e.g. emergency
    defenseman) is tagged with whichever position they most often played that season."""
    acc: Dict[int, Dict[str, object]] = {}

    def _touch(pid: int) -> Dict[str, object]:
        return acc.setdefault(pid, {
            "games": 0, "shots": 0, "goals": 0, "blocks": 0,
            "full_name": "", "positions": {},
        })

    for r in records:
        row = _touch(r.player_id)
        row["games"] += 1
        row["shots"] += r.shots
        row["goals"] += r.goals
        row["blocks"] += r.blocks
        if r.full_name:
            row["full_name"] = r.full_name
        row["positions"][r.position] = row["positions"].get(r.position, 0) + 1

    out: Dict[int, PlayerRateAggregate] = {}
    for pid, row in acc.items():
        games = row["games"]
        if games < MIN_GAMES_FOR_PLAYER_WEIGHT:
            continue
        position = max(row["positions"].items(), key=lambda kv: kv[1])[0]
        out[pid] = PlayerRateAggregate(
            player_id=pid, full_name=str(row["full_name"]), position=position, games=games,
            shot_weight=round(row["shots"] / games, 4),
            goal_weight=round(row["goals"] / games, 4),
            block_weight=round(row["blocks"] / games, 4),
        )
    return out


# ---------------------------------------------------------------------------
# Per-player faceoff win rate (§2zz) -- see the module docstring's own section for why this needs
# `playbyplay`, not the `boxscore` `shot_weight`/`goal_weight`/`block_weight` above use.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GamePlayerFaceoffRecord:
    """One player's real faceoff win/total COUNT from ONE game (never a per-game RATE -- the
    aggregate below sums these across games, it never averages per-game ratios)."""

    player_id: int
    wins: int
    total: int


def parse_playbyplay_player_faceoffs(payload: Dict) -> List[GamePlayerFaceoffRecord]:
    """One game's per-player faceoff win/total counts, from `details.winningPlayerId`/
    `losingPlayerId` on every faceoff event. Returns `[]` for a payload with no `plays` list --
    never raises. Every draw contributes to exactly two players' totals (the winner's and the
    loser's), and one win to the winner's own count."""
    if not isinstance(payload, dict) or not isinstance(payload.get("plays"), list):
        return []
    acc: Dict[int, List[int]] = {}
    for play in payload["plays"]:
        if not isinstance(play, dict) or play.get("typeDescKey") != "faceoff":
            continue
        details = play.get("details") or {}
        w, l = details.get("winningPlayerId"), details.get("losingPlayerId")
        if w is None or l is None:
            continue
        try:
            w_int, l_int = int(w), int(l)
        except (TypeError, ValueError):
            continue
        wa = acc.setdefault(w_int, [0, 0])
        wa[0] += 1
        wa[1] += 1
        la = acc.setdefault(l_int, [0, 0])
        la[1] += 1
    return [GamePlayerFaceoffRecord(player_id=pid, wins=v[0], total=v[1]) for pid, v in acc.items()]


def parse_playbyplay_roster_names(payload: Dict) -> Dict[int, Tuple[str, str]]:
    """`{player_id: (full_name, position_code)}` from `rosterSpots` in the SAME `playbyplay`
    payload -- no boxscore cross-reference needed. Display/sanity-check only; the engine reads
    `HockeyPlayerFeatures.position` from the roster/lineup row directly, never from this lookup."""
    if not isinstance(payload, dict):
        return {}
    out: Dict[int, Tuple[str, str]] = {}
    for spot in payload.get("rosterSpots") or []:
        pid = spot.get("playerId")
        if pid is None:
            continue
        try:
            pid_int = int(pid)
        except (TypeError, ValueError):
            continue
        first = (spot.get("firstName") or {}).get("default", "")
        last = (spot.get("lastName") or {}).get("default", "")
        pos = str(spot.get("positionCode") or "").strip().upper()
        name = f"{first} {last}".strip()
        if name or pos:
            out[pid_int] = (name, pos)
    return out


# A player below this real DRAW-COUNT floor (not a game-count floor -- some players take many
# draws in few games, others few in many) produces a rate too noisy to trust -- see the module
# docstring for the measured 0.0/1.0-per-game-rate artifact this floor exists to avoid. Below it,
# the player is OMITTED entirely, so `build_player_features`/`compute_lineup_faceoff_pct` fall back
# to the team's own season aggregate for them -- never a guess dressed up as data.
MIN_DRAWS_FOR_PLAYER_FACEOFF_WEIGHT = 100


@dataclass(frozen=True)
class PlayerFaceoffRateAggregate:
    player_id: int
    full_name: str
    position: str
    games: int
    draws: int
    faceoff_weight: float  # TRUE wins/total across ALL games -- never an average of per-game rates


def compute_player_faceoff_aggregates(
    per_game_records: Sequence[Sequence[GamePlayerFaceoffRecord]],
    per_game_names: Sequence[Dict[int, Tuple[str, str]]],
) -> Dict[int, PlayerFaceoffRateAggregate]:
    """Season aggregate per player -- summed win/total COUNTS across every game (see the module
    docstring for why this must never be an average of per-game rates). `per_game_records` and
    `per_game_names` must be the SAME length, in the SAME game order (typically one entry per
    parsed `playbyplay` payload)."""
    wins: Dict[int, int] = {}
    total: Dict[int, int] = {}
    games: Dict[int, int] = {}
    names: Dict[int, str] = {}
    positions: Dict[int, Dict[str, int]] = {}

    for recs, name_lookup in zip(per_game_records, per_game_names):
        for r in recs:
            if r.total <= 0:
                continue
            wins[r.player_id] = wins.get(r.player_id, 0) + r.wins
            total[r.player_id] = total.get(r.player_id, 0) + r.total
            games[r.player_id] = games.get(r.player_id, 0) + 1
            nm, pos = name_lookup.get(r.player_id, ("", ""))
            if nm:
                names[r.player_id] = nm
            if pos:
                pos_counts = positions.setdefault(r.player_id, {})
                pos_counts[pos] = pos_counts.get(pos, 0) + 1

    out: Dict[int, PlayerFaceoffRateAggregate] = {}
    for pid, t in total.items():
        if t < MIN_DRAWS_FOR_PLAYER_FACEOFF_WEIGHT:
            continue
        pos_counts = positions.get(pid) or {}
        position = max(pos_counts.items(), key=lambda kv: kv[1])[0] if pos_counts else ""
        out[pid] = PlayerFaceoffRateAggregate(
            player_id=pid, full_name=names.get(pid, ""), position=position,
            games=games.get(pid, 0), draws=t,
            faceoff_weight=round(wins.get(pid, 0) / t, 4),
        )
    return out
