"""Per-team PP/PK SHOT volume from the `boxscore` endpoint — the truth counterpart the special-teams
GOAL calibration (`docs/reports/hockeysim_special_teams_goal_cal_report.md`) could not reach.

The `landing` feed the rest of `historical_truth/` reads has no shot-by-strength-state breakdown —
only goals. The SEPARATE `boxscore` endpoint (`ingestion/nhl_web.py`'s `NhlWebIngestClient.boxscore`,
cached at `data/nhl_source/data/ingestion_cache/boxscore_{game_id}.json`, bulk-fetched this session
by `scripts/fetch_nhl_boxscore_cache.py`) carries per-goalie strength-state SHOTS-AGAINST splits
(`playerByGameStats.{home,away}Team.goalies[].evenStrengthShotsAgainst`/`powerPlayShotsAgainst`/
`shorthandedShotsAgainst`, each a `"saves/shots"` string).

THE DIRECTION, verified against a 20-game random sample (every game: the three splits sum exactly
to `shotsAgainst`):

    a goalie's own powerPlayShotsAgainst  = the OPPONENT's PP shot volume this game
                                           = this goalie's own team's PK shots-against
    a goalie's own shorthandedShotsAgainst = the OPPONENT's shots while THEY were shorthanded
                                            = this goalie's own team's PP shots-against-while-PK'd
                                              (the rare "opponent scores shorthanded" case)

So: HOME's PP shots this game = AWAY goalie's `powerPlayShotsAgainst` denominator (the away goalie
faces shots FROM home; "while [shooter] was on PP" = while home had the man advantage).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Sequence


@dataclass(frozen=True)
class GameShotStrengthRecord:
    """One finished game's PP/PK shot volume, parsed from a `boxscore` payload."""

    game_id: str
    home_abbr: str
    away_abbr: str
    home_pp_shots: int    # shots HOME took while HOME was on the power play
    away_pp_shots: int    # shots AWAY took while AWAY was on the power play
    home_ev_shots: int
    away_ev_shots: int
    home_sh_shots: int    # shots HOME took while HOME was shorthanded (rare)
    away_sh_shots: int

    @property
    def total_shots(self) -> int:
        return (self.home_pp_shots + self.away_pp_shots + self.home_ev_shots
                + self.away_ev_shots + self.home_sh_shots + self.away_sh_shots)


def _split(value: object) -> Optional[int]:
    """Parse a `"saves/shots"` string; returns the SHOTS (denominator), or None if unparseable."""
    if not value or "/" not in str(value):
        return None
    try:
        _saves, shots = str(value).split("/", 1)
        return int(shots)
    except (ValueError, TypeError):
        return None


def _abbr(team: Dict) -> str:
    return str((team or {}).get("abbrev") or "").upper()


def parse_boxscore_shot_strength(boxscore: Dict) -> Optional[GameShotStrengthRecord]:
    """Parse one `boxscore` payload into a :class:`GameShotStrengthRecord` (pure).

    Returns ``None`` if the payload is missing the `playerByGameStats` block or either side's
    goalie entries are absent/unparseable (an in-progress or malformed payload) -- never raises.
    """
    if not isinstance(boxscore, dict):
        return None
    home_team = boxscore.get("homeTeam") or {}
    away_team = boxscore.get("awayTeam") or {}
    home_abbr = _abbr(home_team)
    away_abbr = _abbr(away_team)
    if not home_abbr or not away_abbr:
        return None

    pbg = boxscore.get("playerByGameStats") or {}
    home_goalies = (pbg.get("homeTeam") or {}).get("goalies") or []
    away_goalies = (pbg.get("awayTeam") or {}).get("goalies") or []
    if not home_goalies or not away_goalies:
        return None

    def _sum(goalies: list, key: str) -> Optional[int]:
        total = 0
        found = False
        for g in goalies:
            v = _split(g.get(key))
            if v is not None:
                total += v
                found = True
        return total if found else None

    home_pp_against = _sum(home_goalies, "powerPlayShotsAgainst")   # = AWAY's PP shots
    away_pp_against = _sum(away_goalies, "powerPlayShotsAgainst")   # = HOME's PP shots
    home_sh_against = _sum(home_goalies, "shorthandedShotsAgainst")  # = AWAY's shots while AWAY shorthanded
    away_sh_against = _sum(away_goalies, "shorthandedShotsAgainst")  # = HOME's shots while HOME shorthanded
    home_ev = _sum(home_goalies, "evenStrengthShotsAgainst")         # = AWAY's EV shots
    away_ev = _sum(away_goalies, "evenStrengthShotsAgainst")         # = HOME's EV shots

    if None in (home_pp_against, away_pp_against, home_sh_against, away_sh_against, home_ev, away_ev):
        return None

    return GameShotStrengthRecord(
        game_id=str(boxscore.get("id") or ""),
        home_abbr=home_abbr,
        away_abbr=away_abbr,
        home_pp_shots=away_pp_against,
        away_pp_shots=home_pp_against,
        home_ev_shots=away_ev,
        away_ev_shots=home_ev,
        home_sh_shots=away_sh_against,
        away_sh_shots=home_sh_against,
    )


def _safe_div(num: float, den: float) -> float:
    return float(num) / float(den) if den else 0.0


@dataclass(frozen=True)
class ShotStrengthSnapshot:
    """League-wide shot-by-strength-state truth -- the calibration TARGET for `cal_pp_sh_mult`
    (target: `pp_shot_share`) and `cal_pk_sh_mult` (target: `sh_shot_share`), mirroring
    `TruthMetrics.pp_goal_share`/`sh_goal_share`'s role for the goal multipliers."""

    n_games: int
    shots_per_game: float
    pp_shot_share: float
    sh_shot_share: float
    ev_shot_share: float


def build_shot_strength_snapshot(records: Sequence[GameShotStrengthRecord]) -> ShotStrengthSnapshot:
    n = len(records)
    if n == 0:
        raise ValueError("build_shot_strength_snapshot: no eligible games (need >=1 to form a baseline)")
    total_shots = sum(r.total_shots for r in records)
    total_pp = sum(r.home_pp_shots + r.away_pp_shots for r in records)
    total_sh = sum(r.home_sh_shots + r.away_sh_shots for r in records)
    total_ev = sum(r.home_ev_shots + r.away_ev_shots for r in records)
    return ShotStrengthSnapshot(
        n_games=n,
        shots_per_game=round(_safe_div(total_shots, n), 4),
        pp_shot_share=round(_safe_div(total_pp, total_shots), 4),
        sh_shot_share=round(_safe_div(total_sh, total_shots), 4),
        ev_shot_share=round(_safe_div(total_ev, total_shots), 4),
    )


@dataclass(frozen=True)
class TeamShotStrengthRates:
    """Per-team PP/PK shot volume -- descriptive only (not wired into the engine this pass; see
    `docs/ai_context/hockeysim_engine_reference.md` §2e for why per-team differentiation of shot
    volume needs a NEW engine mechanism, not just a calibration, and was deliberately not built
    in the same pass as the league-wide multiplier calibration)."""

    team: str
    games: int
    pp_shots_per_game: float
    pk_shots_against_per_game: float  # = opponent's pp_shots_per_game vs this team, by definition


def compute_team_shot_strength_rates(
    records: Sequence[GameShotStrengthRecord],
) -> Dict[str, TeamShotStrengthRates]:
    acc: Dict[str, Dict[str, int]] = {}

    def _touch(team: str) -> Dict[str, int]:
        return acc.setdefault(team, {"games": 0, "pp_shots": 0, "pk_shots_against": 0})

    for r in records:
        h = _touch(r.home_abbr)
        a = _touch(r.away_abbr)
        h["games"] += 1
        a["games"] += 1
        h["pp_shots"] += r.home_pp_shots
        a["pp_shots"] += r.away_pp_shots
        # This team's PK shots-against = the OPPONENT's PP shots this game.
        h["pk_shots_against"] += r.away_pp_shots
        a["pk_shots_against"] += r.home_pp_shots

    out: Dict[str, TeamShotStrengthRates] = {}
    for team, row in acc.items():
        games = row["games"]
        out[team] = TeamShotStrengthRates(
            team=team, games=games,
            pp_shots_per_game=round(_safe_div(row["pp_shots"], games), 4),
            pk_shots_against_per_game=round(_safe_div(row["pk_shots_against"], games), 4),
        )
    return out
