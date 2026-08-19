"""Per-team blocked-shot rate from the `boxscore` endpoint — the last remaining special-teams gap
after PP/PK goal conversion (`special_teams_builder.py`) and PP/PK shot volume
(`boxscore_shot_strength.py`): `block_rate_ev`/`block_rate_pk`/`block_rate_pp_def`
(`engine.py`'s `p_block_ev`/`p_block_pk`/`p_block_pp_def`) had no per-team signal at all, and
had never been calibrated to real data either -- the vendor's shipped defaults (0.45/0.55/0.35)
were never checked against a measured block rate.

WHY THIS MODULE, NOT `boxscore_shot_strength.py`. Blocks come from a DIFFERENT part of the same
`boxscore` payload (`playerByGameStats.{home,away}Team.{forwards,defense}[].blockedShots`, a
per-player season-game TOTAL) than the strength-state shot splits that module reads (per-goalie
`evenStrengthShotsAgainst`/etc). Blocks here are NOT split by strength state at all -- the source
data has no such breakdown -- so this produces ONE combined per-team index, applied uniformly to
all three of the engine's strength-state block-rate constants (their STRUCTURAL difference --
higher on the penalty kill, lower while short-handed -- stays intact; only the per-team scale on
top of that structure is new).

WHY A RATIO, NOT AN ABSOLUTE RATE. `engine.py`'s own comment on `block_rate_ev` notes its own
basis mismatch: "a blocked shot is recorded on a shot attempt, not a shot on goal. Our sim's
'shot' event is closer to SOG... so a higher default block probability is needed." Any block rate
computed here uses SOG + blocks as its denominator (shot ATTEMPTS aren't available from this
endpoint), which is NOT the same basis the engine's own probabilities are tuned against. Rather
than overwrite the engine's constants with a wrong-basis absolute number, this module produces a
per-team INDEX relative to the SAME wrong-basis league average -- the basis mismatch cancels out
in the ratio, exactly the same reasoning `boxscore_shot_strength.compute_team_shot_rate_index`
already uses for PP/PK shot volume.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Sequence


@dataclass(frozen=True)
class GameBlockRecord:
    """One finished game's blocked-shot counts, parsed from a `boxscore` payload."""

    game_id: str
    home_abbr: str
    away_abbr: str
    home_blocks: int          # shots HOME blocked (of AWAY's attempts)
    away_blocks: int          # shots AWAY blocked (of HOME's attempts)
    home_shots_faced: int     # AWAY's sog + HOME's blocks -- shots directed at HOME's net
    away_shots_faced: int     # HOME's sog + AWAY's blocks -- shots directed at AWAY's net

    @property
    def total_blocks(self) -> int:
        return self.home_blocks + self.away_blocks

    @property
    def total_shots_faced(self) -> int:
        return self.home_shots_faced + self.away_shots_faced


def _abbr(team: Dict) -> str:
    return str((team or {}).get("abbrev") or "").upper()


def _sum_blocks(skaters_by_group: Dict) -> int:
    total = 0
    for group in ("forwards", "defense"):
        for p in skaters_by_group.get(group, []) or []:
            try:
                total += int(p.get("blockedShots") or 0)
            except (TypeError, ValueError):
                continue
    return total


def parse_boxscore_block_rate(boxscore: Dict) -> Optional[GameBlockRecord]:
    """Parse one `boxscore` payload into a :class:`GameBlockRecord` (pure). Returns `None` if the
    payload is missing team abbrevs, SOG, or the `playerByGameStats` skater blocks -- never raises.
    """
    if not isinstance(boxscore, dict):
        return None
    home_team = boxscore.get("homeTeam") or {}
    away_team = boxscore.get("awayTeam") or {}
    home_abbr = _abbr(home_team)
    away_abbr = _abbr(away_team)
    if not home_abbr or not away_abbr:
        return None
    home_sog = home_team.get("sog")
    away_sog = away_team.get("sog")
    if home_sog is None or away_sog is None:
        return None

    pbg = boxscore.get("playerByGameStats") or {}
    home_skaters = pbg.get("homeTeam") or {}
    away_skaters = pbg.get("awayTeam") or {}
    if not home_skaters or not away_skaters:
        return None

    home_blocks = _sum_blocks(home_skaters)
    away_blocks = _sum_blocks(away_skaters)

    return GameBlockRecord(
        game_id=str(boxscore.get("id") or ""),
        home_abbr=home_abbr, away_abbr=away_abbr,
        home_blocks=home_blocks, away_blocks=away_blocks,
        home_shots_faced=int(away_sog) + home_blocks,
        away_shots_faced=int(home_sog) + away_blocks,
    )


def _safe_div(num: float, den: float) -> float:
    return float(num) / float(den) if den else 0.0


@dataclass(frozen=True)
class LeagueBlockRateSnapshot:
    n_games: int
    league_block_rate: float   # total blocks / total shots faced, league-wide
    blocks_per_game: float     # per TEAM per game


def build_league_block_rate_snapshot(records: Sequence[GameBlockRecord]) -> LeagueBlockRateSnapshot:
    n = len(records)
    if n == 0:
        raise ValueError("build_league_block_rate_snapshot: no eligible games (need >=1)")
    total_blocks = sum(r.total_blocks for r in records)
    total_faced = sum(r.total_shots_faced for r in records)
    return LeagueBlockRateSnapshot(
        n_games=n,
        league_block_rate=round(_safe_div(total_blocks, total_faced), 4),
        blocks_per_game=round(_safe_div(total_blocks, 2 * n), 4),  # 2 teams per game
    )


# A team with few tracked games produces a noisy block rate -- same discipline as the other
# per-team indices in this package.
MIN_GAMES_FOR_BLOCK_INDEX = 10
DEFAULT_BLOCK_INDEX = 1.0


@dataclass(frozen=True)
class TeamBlockRateIndex:
    """Per-team blocked-shot tendency, normalized against the SAME league-wide (SOG+blocks-basis)
    ratio every team is measured against -- 1.0 = league average; >1.0 = blocks more than average;
    <1.0 = blocks less. Applied UNIFORMLY to all three of the engine's strength-state block
    probabilities (`block_rate_ev`/`block_rate_pk`/`block_rate_pp_def`) -- there is no
    strength-state split in the source data to differentiate further."""

    team: str
    block_index: float
    games: int
    blocks: int
    shots_faced: int


def compute_team_block_rate_index(records: Sequence[GameBlockRecord]) -> Dict[str, TeamBlockRateIndex]:
    acc: Dict[str, Dict[str, int]] = {}

    def _touch(team: str) -> Dict[str, int]:
        return acc.setdefault(team, {"games": 0, "blocks": 0, "shots_faced": 0})

    for r in records:
        h = _touch(r.home_abbr)
        a = _touch(r.away_abbr)
        h["games"] += 1
        a["games"] += 1
        h["blocks"] += r.home_blocks
        a["blocks"] += r.away_blocks
        h["shots_faced"] += r.home_shots_faced
        a["shots_faced"] += r.away_shots_faced

    league_blocks = sum(v["blocks"] for v in acc.values() if v["games"] >= MIN_GAMES_FOR_BLOCK_INDEX)
    league_shots_faced = sum(v["shots_faced"] for v in acc.values() if v["games"] >= MIN_GAMES_FOR_BLOCK_INDEX)
    league_rate = _safe_div(league_blocks, league_shots_faced)

    out: Dict[str, TeamBlockRateIndex] = {}
    for team, row in acc.items():
        games = row["games"]
        index = DEFAULT_BLOCK_INDEX
        if games >= MIN_GAMES_FOR_BLOCK_INDEX and league_rate > 0:
            team_rate = _safe_div(row["blocks"], row["shots_faced"])
            index = round(team_rate / league_rate, 4)
        out[team] = TeamBlockRateIndex(
            team=team, block_index=index, games=games,
            blocks=row["blocks"], shots_faced=row["shots_faced"],
        )
    return out
