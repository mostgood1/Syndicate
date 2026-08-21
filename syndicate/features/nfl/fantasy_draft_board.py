"""Turn projections into a DRAFT BOARD.

A projection ranks players by points. A draft board ranks them by what they are
worth to YOU, which is a different question and has a different answer: the
best quarterback may outscore the best running back by eighty points and still
be the worse pick, because the twelfth-best quarterback is nearly as good as
the best one and the twelfth-best running back is not.

So the board is ordered by VALUE OVER REPLACEMENT -- a player's projection
minus what you could get at his position for free after the draft. Replacement
level is not assumed; it is computed by actually filling every starting slot in
the league, flex included, and asking who is left.

Everything here is a pure function of a projection list plus league settings.
No data is read, nothing is cached, and the same projections serve a 10-team
standard league and a 14-team superflex without being recomputed.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from typing import Iterable
from typing import Sequence

from syndicate.features.nfl.fantasy_projection import PlayerProjection


@dataclass(frozen=True)
class LeagueSettings:
    """Roster shape. Drives replacement level and therefore the whole board."""

    teams: int = 12
    qb: int = 1
    rb: int = 2
    wr: int = 2
    te: int = 1
    flex: int = 1
    superflex: int = 0
    k: int = 1
    dst: int = 1
    bench: int = 6

    #: Which positions may fill a FLEX slot.
    flex_positions: tuple[str, ...] = ("RB", "WR", "TE")
    #: Which positions may fill a SUPERFLEX slot.
    superflex_positions: tuple[str, ...] = ("QB", "RB", "WR", "TE")

    @property
    def label(self) -> str:
        shape = "superflex" if self.superflex else f"{self.qb}QB"
        return f"{self.teams}-team {shape}"

    def base_starters(self) -> dict[str, int]:
        return {
            "QB": self.qb,
            "RB": self.rb,
            "WR": self.wr,
            "TE": self.te,
            "K": self.k,
            "DST": self.dst,
        }

    @property
    def draftable_rounds(self) -> int:
        starters = sum(self.base_starters().values()) + self.flex + self.superflex
        return starters + self.bench


DEFAULT_LEAGUE = LeagueSettings()


@dataclass(frozen=True)
class DraftBoardRow:
    """One player, priced for a draft."""

    rank: int
    position_rank: int
    tier: int
    player_id: str
    name: str
    team: str
    position: str
    games: float
    fantasy_points: float
    points_per_game: float
    floor: float
    ceiling: float
    value_over_replacement: float
    replacement_points: float
    #: Rough round in a snake draft of this league's size.
    projected_round: int
    basis: dict


def replacement_levels(
    projections: Sequence[PlayerProjection],
    settings: LeagueSettings = DEFAULT_LEAGUE,
) -> dict[str, float]:
    """The points you can get for free at each position once the league's
    starting slots are full.

    Computed by SIMULATING the fill rather than by a rule of thumb. Fixed slots
    go first, then flex and superflex are awarded to the best remaining
    eligible player in turn -- which is what makes the flex spill correctly
    into whichever position actually has depth this year, instead of assuming
    it is always running backs.

    Replacement is then the NEXT player at that position. When a position runs
    out entirely, it falls back to the worst projected player there, and to
    zero only when nothing at that position exists at all -- a real "there is
    nobody" rather than a silent zero that would make everyone look valuable.
    """
    by_position: dict[str, list[PlayerProjection]] = {}
    for entry in projections:
        by_position.setdefault(entry.position, []).append(entry)
    for pool in by_position.values():
        pool.sort(key=lambda entry: -entry.fantasy_points)

    taken: dict[str, int] = {position: 0 for position in by_position}
    for position, per_team in settings.base_starters().items():
        taken[position] = min(per_team * settings.teams, len(by_position.get(position, [])))

    def best_remaining(positions: Iterable[str]) -> str | None:
        best_position, best_points = None, None
        for position in positions:
            pool = by_position.get(position) or []
            index = taken.get(position, 0)
            if index >= len(pool):
                continue
            points = pool[index].fantasy_points
            if best_points is None or points > best_points:
                best_position, best_points = position, points
        return best_position

    for _ in range(settings.flex * settings.teams):
        position = best_remaining(settings.flex_positions)
        if position is None:
            break
        taken[position] += 1
    for _ in range(settings.superflex * settings.teams):
        position = best_remaining(settings.superflex_positions)
        if position is None:
            break
        taken[position] += 1

    levels: dict[str, float] = {}
    for position, pool in by_position.items():
        if not pool:
            levels[position] = 0.0
            continue
        index = taken.get(position, 0)
        levels[position] = pool[index].fantasy_points if index < len(pool) else pool[-1].fantasy_points
    return levels


def _tiers(values: Sequence[float], max_tiers: int = 12) -> list[int]:
    """Assign tier numbers by finding the largest GAPS in a sorted value list.

    Tiers are what a draft board is actually for: the question at your pick is
    never "who is best" but "is there a real drop after this group". Splitting
    on the biggest gaps answers that directly, and needs no clustering library
    for a one-dimensional sorted sequence -- the optimal 1-D k-segmentation on
    a sorted list IS the top k-1 gaps.
    """
    if not values:
        return []
    gaps = sorted(
        ((values[index] - values[index + 1], index) for index in range(len(values) - 1)),
        reverse=True,
    )
    cuts = sorted(index for _, index in gaps[: max(max_tiers - 1, 0)])
    tiers: list[int] = []
    tier = 1
    cut_set = set(cuts)
    for index in range(len(values)):
        tiers.append(tier)
        if index in cut_set:
            tier += 1
    return tiers


def build_draft_board(
    projections: Sequence[PlayerProjection],
    settings: LeagueSettings = DEFAULT_LEAGUE,
    limit: int | None = None,
) -> list[DraftBoardRow]:
    """Rank every projected player by value over replacement."""
    levels = replacement_levels(projections, settings)

    priced = sorted(
        (
            (entry, entry.fantasy_points - levels.get(entry.position, 0.0))
            for entry in projections
        ),
        key=lambda pair: -pair[1],
    )

    tiers_by_position: dict[str, dict[str, int]] = {}
    for position in {entry.position for entry, _ in priced}:
        pool = [pair for pair in priced if pair[0].position == position]
        assignments = _tiers([value for _, value in pool])
        tiers_by_position[position] = {
            entry.player_id: tier for (entry, _), tier in zip(pool, assignments)
        }

    picks_per_round = max(settings.teams, 1)
    rows: list[DraftBoardRow] = []
    position_counts: dict[str, int] = {}
    for index, (entry, value) in enumerate(priced, start=1):
        position_counts[entry.position] = position_counts.get(entry.position, 0) + 1
        rows.append(
            DraftBoardRow(
                rank=index,
                position_rank=position_counts[entry.position],
                tier=tiers_by_position.get(entry.position, {}).get(entry.player_id, 1),
                player_id=entry.player_id,
                name=entry.name,
                team=entry.team,
                position=entry.position,
                games=round(entry.games, 1),
                fantasy_points=round(entry.fantasy_points, 1),
                points_per_game=round(entry.points_per_game, 2),
                floor=round(entry.floor, 1),
                ceiling=round(entry.ceiling, 1),
                value_over_replacement=round(value, 1),
                replacement_points=round(levels.get(entry.position, 0.0), 1),
                projected_round=(index - 1) // picks_per_round + 1,
                basis=entry.basis,
            )
        )
        if limit and len(rows) >= limit:
            break
    return rows


def board_summary(
    rows: Sequence[DraftBoardRow],
    settings: LeagueSettings = DEFAULT_LEAGUE,
) -> dict:
    """Replacement levels and position counts, for a payload's context block."""
    by_position: dict[str, dict] = {}
    for row in rows:
        entry = by_position.setdefault(
            row.position,
            {"count": 0, "replacement_points": row.replacement_points, "tiers": 0},
        )
        entry["count"] += 1
        entry["tiers"] = max(entry["tiers"], row.tier)
    return {
        "league": settings.label,
        "teams": settings.teams,
        "starters": settings.base_starters()
        | {"FLEX": settings.flex, "SUPERFLEX": settings.superflex},
        "draftable_rounds": settings.draftable_rounds,
        "by_position": by_position,
    }
