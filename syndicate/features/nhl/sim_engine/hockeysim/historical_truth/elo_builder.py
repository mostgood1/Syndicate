"""Team Elo ratings from real finished-game results (the truth layer's second consumer).

`elo_rating` on :class:`hockeysim.contracts.HockeyTeamFeatures` was, until this module, a
CONSUMED field (`projection.py:188`, ``_elo_win_prob``) with **no producer anywhere in the
codebase** — exactly the alarm `docs/ai_context/model_engine_standard.md` §0 describes. This is
the producer: a standard sequential Elo update over :class:`HistoricalGameRecord` results, using
the SAME truth cache (``data/nhl_source/data/truth/raw/landing_*.json``, 1312 games) the Phase-3
baseline already reads, and the SAME logistic scale (400) and home-ice bump (50 points) already
declared in :class:`hockeysim.projection.ProjectionProfile` so a rating computed here is directly
comparable to the win-prob curve that would consume it.

Pure function, no I/O — mirrors `historical_truth/snapshot_builder.py`'s shape. The producer script
(`scripts/build_nhl_elo_artifact.py`) does the file I/O; this module only computes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from .contracts import HistoricalGameRecord

DEFAULT_INITIAL_RATING = 1500.0
DEFAULT_K = 20.0
# Matches ProjectionProfile.elo_scale / elo_home_adv (projection.py) so a rating produced here
# plugs directly into the existing `_elo_win_prob` curve without a unit mismatch.
DEFAULT_ELO_SCALE = 400.0
DEFAULT_HOME_ADVANTAGE = 50.0


@dataclass(frozen=True)
class EloPregameEntry:
    """One game's Elo state *before* it was played — the backtest-safe view (no lookahead)."""

    game_id: str
    date: str
    home_abbr: str
    away_abbr: str
    home_elo: float
    away_elo: float
    home_win: bool


def _expected_home_win_prob(
    home_elo: float, away_elo: float, *, scale: float, home_advantage: float
) -> float:
    return 1.0 / (1.0 + 10.0 ** (((away_elo) - (home_elo + home_advantage)) / scale))


def compute_elo_progression(
    games: Sequence[HistoricalGameRecord],
    *,
    k: float = DEFAULT_K,
    scale: float = DEFAULT_ELO_SCALE,
    home_advantage: float = DEFAULT_HOME_ADVANTAGE,
    initial: float = DEFAULT_INITIAL_RATING,
) -> Tuple[Dict[str, float], List[EloPregameEntry]]:
    """Run a chronological Elo update over settled games.

    Returns ``(final_ratings, pregame_entries)``. ``final_ratings`` is what a producer publishes
    (the artifact — "team strength as of right now"). ``pregame_entries`` carries each team's
    rating *before* that game was played, in play order — the only view a backtest may score
    against, since scoring a game with its own outcome already folded into the rating is lookahead
    bias, not a measurement.

    Games are ordered by ``(date, game_id)``; games missing a parseable date sort last (stable,
    but their ordering relative to each other is not meaningful — flag rather than silently drop,
    per the standard's "unclassified is logged, not dropped" convention).
    """
    ratings: Dict[str, float] = {}
    pregame: List[EloPregameEntry] = []
    for g in sorted(games, key=lambda r: (r.date or "9999-99-99", str(r.game_id))):
        ra = ratings.get(g.home_abbr, initial)
        rb = ratings.get(g.away_abbr, initial)
        pregame.append(
            EloPregameEntry(
                game_id=g.game_id, date=g.date, home_abbr=g.home_abbr, away_abbr=g.away_abbr,
                home_elo=ra, away_elo=rb, home_win=g.home_win,
            )
        )
        expected_home = _expected_home_win_prob(ra, rb, scale=scale, home_advantage=home_advantage)
        actual_home = 1.0 if g.home_win else 0.0
        delta = k * (actual_home - expected_home)
        ratings[g.home_abbr] = ra + delta
        ratings[g.away_abbr] = rb - delta
    return ratings, pregame


def compute_elo_ratings(games: Sequence[HistoricalGameRecord], **kwargs: object) -> Dict[str, float]:
    """Convenience wrapper: just the final ratings (what the artifact publishes)."""
    final, _pregame = compute_elo_progression(games, **kwargs)  # type: ignore[arg-type]
    return final


def brier_score(pregame: Sequence[EloPregameEntry], *, scale: float, home_advantage: float) -> Optional[float]:
    """Brier score of the Elo-implied home win prob against real outcomes, no-lookahead.

    Lower is better; 0.25 is what a coin flip scores, and a constant-probability baseline (predict
    the league home-win rate every game) is the floor any real signal must beat. Returns ``None``
    for an empty input rather than raising — a backtest over zero games is not a measurement.
    """
    if not pregame:
        return None
    total = 0.0
    for e in pregame:
        p = _expected_home_win_prob(e.home_elo, e.away_elo, scale=scale, home_advantage=home_advantage)
        actual = 1.0 if e.home_win else 0.0
        total += (p - actual) ** 2
    return total / len(pregame)
