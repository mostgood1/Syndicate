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
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence


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
