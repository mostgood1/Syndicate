"""Team-level ALL-SITUATIONS rate stats -- `shots_per_60`, `blocks_per_60`, `faceoff_win_pct` --
the last 3 team-level `HockeyTeamFeatures` fields `docs/ai_context/hockeysim_engine_reference.md`
§5 flagged as genuinely absent (`penalties_per_60` is handled separately -- see
`scripts/build_nhl_team_rates_artifact.py`'s module docstring for why).

These are ALL-SITUATIONS rates (not split by strength state) -- `player_props.py`'s `TeamRates`
construction reads them as flat per-team constants, the same shape `shots_per_60`/`goals_per_60`/
etc. already have in that dataclass. This is DELIBERATELY simpler than the PP/PK-specific work
earlier in this session (`boxscore_shot_strength.py`, `boxscore_block_rate.py`) -- those built
per-STRENGTH-STATE signals layered on top of an existing mechanism; this fills a plain team-rate
gap that has no existing mechanism to layer on top of at all (the dataclass fields sat at a single
hardcoded league-average constant for every team, unconditionally).

WHY BOXSCORE FOR SOG/BLOCKS, PLAY-BY-PLAY FOR FACEOFFS. `boxscore`'s own `sog` field is the
league's own recorded shots-on-goal total -- no need to re-derive it from play-by-play events.
Blocks reuse `boxscore_block_rate.parse_boxscore_block_rate` (already built, §2g) rather than
re-parsing the same payload a second way. Faceoffs have no boxscore equivalent at the team level,
so those come from `play-by-play`'s `faceoff` events, whose `eventOwnerTeamId` is the WINNING
team -- verified directly against `rosterSpots` team assignment (0 mismatches / 70 faceoffs in a
spot-check sample) rather than assumed from documentation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Sequence

from .boxscore_block_rate import parse_boxscore_block_rate

_FACEOFF_TYPE = "faceoff"


@dataclass(frozen=True)
class GameTeamRates:
    """One finished game's ALL-SITUATIONS team rate counts."""

    game_id: str
    home_abbr: str
    away_abbr: str
    home_sog: int
    away_sog: int
    home_blocks: int
    away_blocks: int
    home_faceoff_wins: int
    away_faceoff_wins: int
    faceoff_total: int


def _abbr(team: Dict) -> str:
    return str((team or {}).get("abbrev") or "").upper()


def parse_boxscore_sog_and_blocks(boxscore: Dict) -> Optional[Dict[str, object]]:
    """`{home_abbr, away_abbr, home_sog, away_sog, home_blocks, away_blocks}` from one `boxscore`
    payload (pure; never raises). Reuses the block parser already built for §2g."""
    if not isinstance(boxscore, dict):
        return None
    home_team = boxscore.get("homeTeam") or {}
    away_team = boxscore.get("awayTeam") or {}
    home_abbr = _abbr(home_team)
    away_abbr = _abbr(away_team)
    home_sog = home_team.get("sog")
    away_sog = away_team.get("sog")
    if not home_abbr or not away_abbr or home_sog is None or away_sog is None:
        return None
    block_rec = parse_boxscore_block_rate(boxscore)
    if block_rec is None:
        return None
    return {
        "home_abbr": home_abbr, "away_abbr": away_abbr,
        "home_sog": int(home_sog), "away_sog": int(away_sog),
        "home_blocks": block_rec.home_blocks, "away_blocks": block_rec.away_blocks,
    }


def parse_play_by_play_faceoffs(payload: Dict) -> Optional[Dict[str, object]]:
    """`{home_wins, away_wins, total}` from one `play-by-play` payload's `faceoff` events (pure;
    never raises). `eventOwnerTeamId` on a faceoff event is the WINNING team."""
    if not isinstance(payload, dict):
        return None
    home = payload.get("homeTeam") or {}
    away = payload.get("awayTeam") or {}
    home_id = home.get("id")
    away_id = away.get("id")
    if home_id is None or away_id is None:
        return None
    home_wins = away_wins = 0
    for p in payload.get("plays") or []:
        if p.get("typeDescKey") != _FACEOFF_TYPE:
            continue
        winner = (p.get("details") or {}).get("eventOwnerTeamId")
        if winner == home_id:
            home_wins += 1
        elif winner == away_id:
            away_wins += 1
    total = home_wins + away_wins
    if total == 0:
        return None
    return {"home_wins": home_wins, "away_wins": away_wins, "total": total}


def build_game_team_rates(
    boxscore_payloads: Sequence[Dict], playbyplay_by_id: Dict[str, Dict],
) -> Dict[str, GameTeamRates]:
    """Join a game's `boxscore` (SOG + blocks) with its `play-by-play` (faceoffs) into one
    `GameTeamRates` per game id. A game missing EITHER source is skipped -- never guessed."""
    out: Dict[str, GameTeamRates] = {}
    for boxscore in boxscore_payloads:
        gid = str(boxscore.get("id") or "")
        if not gid:
            continue
        sb = parse_boxscore_sog_and_blocks(boxscore)
        if sb is None:
            continue
        pbp = playbyplay_by_id.get(gid)
        fo = parse_play_by_play_faceoffs(pbp) if pbp else None
        if fo is None:
            continue
        out[gid] = GameTeamRates(
            game_id=gid, home_abbr=sb["home_abbr"], away_abbr=sb["away_abbr"],
            home_sog=sb["home_sog"], away_sog=sb["away_sog"],
            home_blocks=sb["home_blocks"], away_blocks=sb["away_blocks"],
            home_faceoff_wins=fo["home_wins"], away_faceoff_wins=fo["away_wins"],
            faceoff_total=fo["total"],
        )
    return out


@dataclass(frozen=True)
class TeamRateAggregate:
    team: str
    games: int
    shots_per_60: float
    blocks_per_60: float
    faceoff_win_pct: float
    faceoffs: int


def compute_team_rate_aggregates(records: Sequence[GameTeamRates]) -> Dict[str, TeamRateAggregate]:
    """Season aggregate per team -- `shots_per_60`/`blocks_per_60` as season-total/games (the same
    per-game-as-per-60 convention `league_baseline_goals_per_60` already uses elsewhere in this
    codebase); `faceoff_win_pct` as wins/total faceoffs taken."""
    acc: Dict[str, Dict[str, int]] = {}

    def _touch(team: str) -> Dict[str, int]:
        return acc.setdefault(team, {"games": 0, "sog": 0, "blocks": 0, "fo_wins": 0, "fo_total": 0})

    for r in records:
        h = _touch(r.home_abbr)
        a = _touch(r.away_abbr)
        h["games"] += 1
        a["games"] += 1
        h["sog"] += r.home_sog
        a["sog"] += r.away_sog
        h["blocks"] += r.home_blocks
        a["blocks"] += r.away_blocks
        h["fo_wins"] += r.home_faceoff_wins
        a["fo_wins"] += r.away_faceoff_wins
        h["fo_total"] += r.faceoff_total
        a["fo_total"] += r.faceoff_total

    out: Dict[str, TeamRateAggregate] = {}
    for team, row in acc.items():
        games = max(1, row["games"])
        fo_total = row["fo_total"]
        out[team] = TeamRateAggregate(
            team=team, games=row["games"],
            shots_per_60=round(row["sog"] / games, 4),
            blocks_per_60=round(row["blocks"] / games, 4),
            faceoff_win_pct=round(row["fo_wins"] / fo_total, 4) if fo_total else 0.5,
            faceoffs=fo_total,
        )
    return out
