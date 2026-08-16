from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

from .forward_tuning import (
    FORWARD_MANAGER_PITCHING_OVERRIDES_PATH,
    FORWARD_PITCH_MODEL_OVERRIDES_PATH,
    should_use_forward_tuning,
)
from .models import BaseState, GameConfig, InningHalfState, TeamRoster
from .state import GameState, PlateAppearanceState
from .simulate import simulate_game


@dataclass
class LiveSituation:
    inning: int
    top: bool
    outs: int
    bases: BaseState
    away_score: int
    home_score: int
    runner_on_1b: int = 0
    runner_on_2b: int = 0
    runner_on_3b: int = 0
    away_next_batter_index: int = 0
    home_next_batter_index: int = 0
    away_pitcher_id: Optional[int] = None
    home_pitcher_id: Optional[int] = None
    current_batter_id: Optional[int] = None
    balls: int = 0
    strikes: int = 0
    current_pa_pitch_count: int = 0
    pitcher_pitch_count: Dict[int, int] = field(default_factory=dict)
    pitcher_batters_faced: Dict[int, int] = field(default_factory=dict)
    pitcher_pitch_count_inning: Dict[int, int] = field(default_factory=dict)
    pitcher_batters_faced_inning: Dict[int, int] = field(default_factory=dict)
    pitcher_entered_mid_inning: Dict[int, bool] = field(default_factory=dict)


@dataclass
class LiveMcResult:
    home_win_prob: float
    away_win_prob: float
    avg_total_runs: float
    avg_away_runs: float
    avg_home_runs: float
    total_runs_dist: Dict[int, int]
    # PER-PLAYER REMAINING-STAT DISTRIBUTIONS. Every sim below already produces a
    # full box score (`GameResult.batter_stats`/`pitcher_stats`) and this used to
    # discard all of it, keeping only the final score -- so the live prop rows
    # downstream had a live MEAN and no live PROBABILITY, and their P(over) fell
    # back to the PREGAME distribution. Measured on the board 2026-08-13: on 24
    # of 28 live rows the "live" probability was bit-identical to the pregame
    # one, and three props whose over was already WON still read 0.65-0.75,
    # producing edges of +36.5%/+32.3%/+15.8% that sorted above every honest
    # number on the board.
    #
    # Shape: {player_id: {stat: {remaining_value: sim_count}}}. These are
    # REMAINING values, not final ones -- `simulate_game` starts each sim with a
    # fresh `StatsTracker` from the live state, so what it counts is what is
    # still to come. The final value is `actual_so_far + remaining`, which is
    # what makes an already-decided prop resolve to exactly 1.0 instead of 0.66.
    batter_stat_dist: Dict[int, Dict[str, Dict[int, int]]] = field(default_factory=dict)
    pitcher_stat_dist: Dict[int, Dict[str, Dict[int, int]]] = field(default_factory=dict)
    # HOME MARGIN HISTOGRAM: {home_final - away_final: sim_count}.
    #
    # The same argument as `total_runs_dist` above, for the market that had no
    # distribution at all. A live SPREAD needs P(home covers X), and the only
    # live number reaching the board was `avg_home_runs - avg_away_runs` -- a
    # mean, which cannot price a line. Measured on the served board 2026-08-16
    # 19:13Z across 8 live MLB games: `spreads|full` 36 rows and
    # `spreads_alt|first5` 79 rows, every one of them 0 live_aware and 0 edge,
    # rendering a PREGAME projection against a live market.
    #
    # Free, in the sense that matters: the loop below already computes both
    # finals to decide the winner, so this counts something it has in hand. It
    # is one small int-keyed dict per game -- next to `batter_stat_dist`'s
    # measured ~72 KB/game it does not register.
    #
    # SIGNED HOME-POSITIVE, matching `avg_home_runs - avg_away_runs` so the two
    # never disagree about direction. The board's `line` arrives in the
    # away/over frame (`book_grid._canonical_line`), and reconciling that is the
    # CONSUMER's job -- doing it here would bake a presentation convention into
    # the sim.
    margin_dist: Dict[int, int] = field(default_factory=dict)
    # The denominator. Every histogram above sums to exactly this, including the
    # zeros -- see `_record_player_stats`.
    sims_run: int = 0


# Only the stats that back a real prop market, because the histograms are
# retained per player per sim and there is no reason to carry the rest.
_BATTER_TRACKED_STATS = ("H", "HR", "TB", "HRR", "RBI", "R", "BB", "SO", "SB")
_PITCHER_TRACKED_STATS = ("OUTS", "SO", "ER", "H", "BB")


def _batter_total_bases(row: Dict[str, int]) -> int:
    """`TB` is not tracked by the sim, but its components are."""
    singles = int(row.get("1B") or 0)
    doubles = int(row.get("2B") or 0)
    triples = int(row.get("3B") or 0)
    homers = int(row.get("HR") or 0)
    return singles + 2 * doubles + 3 * triples + 4 * homers


def _batter_hits_runs_rbis(row: Dict[str, int]) -> int:
    """H+R+RBI, DERIVED PER SIM rather than from the three marginals.

    The distribution of a sum is not recoverable from the distributions of its
    parts -- they are correlated (the same swing that produces a hit often
    produces an RBI, and a home run produces all three at once), so combining
    marginals would understate the joint upside badly. Summing inside each sim
    keeps the correlation the simulation already generated.
    """
    return int(row.get("H") or 0) + int(row.get("R") or 0) + int(row.get("RBI") or 0)


def _record_player_stats(
    accumulator: Dict[int, Dict[str, Dict[int, int]]],
    stats: Dict[int, Dict[str, object]],
    tracked: tuple,
    *,
    derive_total_bases: bool = False,
) -> None:
    for player_id, row in (stats or {}).items():
        if not isinstance(row, dict):
            continue
        try:
            key = int(player_id)
        except (TypeError, ValueError):
            continue
        player = accumulator.setdefault(key, {})
        for stat in tracked:
            if stat == "TB" and derive_total_bases:
                value = _batter_total_bases(row)
            elif stat == "HRR" and derive_total_bases:
                value = _batter_hits_runs_rbis(row)
            else:
                raw = row.get(stat)
                if raw is None:
                    continue
                try:
                    value = int(round(float(raw)))
                except (TypeError, ValueError):
                    continue
            bucket = player.setdefault(stat, {})
            bucket[value] = bucket.get(value, 0) + 1


def _backfill_absent_sims(
    accumulator: Dict[int, Dict[str, Dict[int, int]]], sims: int
) -> None:
    """A player absent from a sim recorded NOTHING, which is not the same as no data.

    A batter who never comes to the plate again, or a reliever who never enters,
    simply has no row in that sim's box score. Left alone, his histogram sums to
    fewer than `sims` and every probability computed from it is divided by the
    wrong denominator -- inflating P(over) by exactly the fraction of sims in
    which he had no further chance to reach the line. That is the wrong
    direction: the player least likely to bat again would look most likely to go
    over. Absence is a real observation of zero, so it is recorded as one.
    """
    for player in accumulator.values():
        for bucket in player.values():
            observed = sum(bucket.values())
            missing = int(sims) - int(observed)
            if missing > 0:
                bucket[0] = bucket.get(0, 0) + missing


def prob_over_line_from_remaining(
    remaining_dist: Optional[Dict[int, int]],
    actual_so_far: Optional[float],
    line: Optional[float],
) -> Optional[float]:
    """P(final > line), where final = what already happened + what is still to come.

    Empirical, not fitted: the fraction of simulated rest-of-games in which this
    player finishes above the line. No distributional assumption is made, which
    is the whole point -- deriving a probability from the live MEAN would be
    inventing a shape, and this repo already refuses that elsewhere ("inventing
    P(over) from a mean would put a fabricated number into EV").

    An already-decided prop falls out for free: with 1 hit banked against a 0.5
    line, every sim satisfies `1 + remaining > 0.5` and this returns exactly 1.0.
    """
    if not isinstance(remaining_dist, dict) or not remaining_dist or line is None:
        return None
    try:
        line_value = float(line)
        banked = float(actual_so_far or 0.0)
    except (TypeError, ValueError):
        return None
    total = 0
    over = 0
    for value, count in remaining_dist.items():
        try:
            final_value = banked + float(value)
            weight = int(count)
        except (TypeError, ValueError):
            continue
        total += weight
        if final_value > line_value:
            over += weight
    if total <= 0:
        return None
    return float(over) / float(total)


def _load_json_file(path: Path) -> Dict[str, object]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def _forward_live_cfg_kwargs(date_str: Optional[str]) -> Dict[str, object]:
    if not date_str or not should_use_forward_tuning(str(date_str)):
        return {}
    return {
        "pitch_model_overrides": _load_json_file(FORWARD_PITCH_MODEL_OVERRIDES_PATH),
        "manager_pitching_overrides": _load_json_file(FORWARD_MANAGER_PITCHING_OVERRIDES_PATH),
    }


def _clamp_batter_index(roster: TeamRoster, raw_index: int) -> int:
    lineup = list(getattr(getattr(roster, "lineup", None), "batters", []) or [])
    if not lineup:
        return 0
    try:
        return int(max(0, raw_index)) % len(lineup)
    except Exception:
        return 0


def _default_pitcher_id(roster: TeamRoster) -> int:
    try:
        return int(getattr(getattr(roster.lineup.pitcher, "player", None), "mlbam_id", 0) or 0)
    except Exception:
        return 0


def _build_initial_state(
    away: TeamRoster,
    home: TeamRoster,
    situation: LiveSituation,
    cfg: GameConfig,
) -> GameState:
    top = bool(situation.top)
    batting_roster = away if top else home
    fielding_roster = home if top else away
    next_batter_index_by_team = {
        int(away.team.team_id): _clamp_batter_index(away, int(situation.away_next_batter_index or 0)),
        int(home.team.team_id): _clamp_batter_index(home, int(situation.home_next_batter_index or 0)),
    }
    state = GameState(
        away=away,
        home=home,
        config=cfg,
        inning=max(1, int(situation.inning or 1)),
        top=top,
        away_score=max(0, int(situation.away_score or 0)),
        home_score=max(0, int(situation.home_score or 0)),
        pitcher_pitch_count={
            int(pid): max(0, int(value or 0))
            for pid, value in (situation.pitcher_pitch_count or {}).items()
            if int(pid or 0) > 0
        },
        pitcher_batters_faced={
            int(pid): max(0, int(value or 0))
            for pid, value in (situation.pitcher_batters_faced or {}).items()
            if int(pid or 0) > 0
        },
        pitcher_pitch_count_inning={
            int(pid): max(0, int(value or 0))
            for pid, value in (situation.pitcher_pitch_count_inning or {}).items()
            if int(pid or 0) > 0
        },
        pitcher_batters_faced_inning={
            int(pid): max(0, int(value or 0))
            for pid, value in (situation.pitcher_batters_faced_inning or {}).items()
            if int(pid or 0) > 0
        },
        pitcher_entered_mid_inning={
            int(pid): bool(value)
            for pid, value in (situation.pitcher_entered_mid_inning or {}).items()
            if int(pid or 0) > 0
        },
        next_batter_index_by_team=next_batter_index_by_team,
    )

    away_pitcher_id = int(situation.away_pitcher_id or 0) or _default_pitcher_id(away)
    home_pitcher_id = int(situation.home_pitcher_id or 0) or _default_pitcher_id(home)
    if away_pitcher_id > 0:
        state.current_pitcher_by_team[int(away.team.team_id)] = away_pitcher_id
    if home_pitcher_id > 0:
        state.current_pitcher_by_team[int(home.team.team_id)] = home_pitcher_id

    batting_team_id = int(batting_roster.team.team_id)
    state.half = InningHalfState(
        batting_team=batting_roster.team,
        fielding_team=fielding_roster.team,
        outs=max(0, min(2, int(situation.outs or 0))),
        bases=situation.bases if isinstance(situation.bases, BaseState) else BaseState.EMPTY,
        runner_on_1b=max(0, int(situation.runner_on_1b or 0)),
        runner_on_2b=max(0, int(situation.runner_on_2b or 0)),
        runner_on_3b=max(0, int(situation.runner_on_3b or 0)),
        runs_scored=0,
        next_batter_index=int(next_batter_index_by_team.get(batting_team_id, 0) or 0),
    )
    live_balls = max(0, min(3, int(situation.balls or 0)))
    live_strikes = max(0, min(2, int(situation.strikes or 0)))
    live_batter_id = int(situation.current_batter_id or 0)
    current_fielding_pitcher_id = away_pitcher_id if batting_team_id == int(home.team.team_id) else home_pitcher_id
    if live_batter_id > 0 and current_fielding_pitcher_id > 0 and (live_balls > 0 or live_strikes > 0):
        state.pa = PlateAppearanceState(
            batter_id=live_batter_id,
            pitcher_id=int(current_fielding_pitcher_id),
            count=(int(live_balls), int(live_strikes)),
            pitch_count=max(int(situation.current_pa_pitch_count or 0), int(live_balls + live_strikes)),
            pitches=None,
        )
    return state


def estimate_live(
    away: TeamRoster,
    home: TeamRoster,
    situation: LiveSituation,
    sims: int = 300,
    seed: Optional[int] = None,
    cfg_kwargs: Optional[Dict[str, object]] = None,
    track_player_stats: bool = True,
) -> LiveMcResult:
    """Monte Carlo estimate for winner/total from the actual current game state.

    `track_player_stats` retains each sim's per-player box score as remaining-stat
    histograms, which is what gives live PROPS a real live probability rather
    than falling back to the pregame distribution. Kept as a flag so a caller
    that only wants the win/total numbers can opt out, but it defaults on because
    the sims are already paying for the box score.
    """
    rng = random.Random(seed)
    home_wins = 0
    away_wins = 0
    total_sum = 0.0
    away_sum = 0.0
    home_sum = 0.0
    dist: Dict[int, int] = {}
    margin: Dict[int, int] = {}
    batter_dist: Dict[int, Dict[str, Dict[int, int]]] = {}
    pitcher_dist: Dict[int, Dict[str, Dict[int, int]]] = {}
    effective_cfg_kwargs = dict(cfg_kwargs or {})
    sims_run = max(1, int(sims))

    for i in range(sims_run):
        cfg = GameConfig(rng_seed=rng.randint(1, 2**31 - 1), **effective_cfg_kwargs)
        state = _build_initial_state(away, home, situation, cfg)
        res = simulate_game(away, home, cfg, initial_state=state)
        # Retaining the box score this sim already built. MEASURED, not assumed:
        # 120 sims on a real roster ran 1.77s/2.79s with tracking off against
        # 1.89s/3.25s on -- **+7% to +16% CPU**, and ~72 KB of histograms per
        # game (~1.1 MB across a 15-game slate). Not free, and small enough to be
        # worth a real live probability; recorded here at the measured figure
        # rather than as "negligible", which is what the first draft of this
        # comment claimed before it was checked.
        if track_player_stats:
            _record_player_stats(
                batter_dist, getattr(res, "batter_stats", None) or {},
                _BATTER_TRACKED_STATS, derive_total_bases=True,
            )
            _record_player_stats(
                pitcher_dist, getattr(res, "pitcher_stats", None) or {}, _PITCHER_TRACKED_STATS,
            )
        away_final = max(0, int(res.away_score or 0))
        home_final = max(0, int(res.home_score or 0))
        total = int(away_final + home_final)
        total_sum += float(total)
        away_sum += float(away_final)
        home_sum += float(home_final)
        dist[total] = dist.get(total, 0) + 1
        # Home-positive, same frame as `avg_home_runs - avg_away_runs`.
        margin[home_final - away_final] = margin.get(home_final - away_final, 0) + 1

        if home_final > away_final:
            home_wins += 1
        elif away_final > home_final:
            away_wins += 1
        else:
            # tie: count half/half
            home_wins += 0.5
            away_wins += 0.5

    denom = float(max(1, sims))
    if track_player_stats:
        # AFTER the loop, never inside it: a player absent from one sim may
        # appear in the next, so the zeros can only be counted once the total
        # number of sims is final.
        _backfill_absent_sims(batter_dist, sims_run)
        _backfill_absent_sims(pitcher_dist, sims_run)
    return LiveMcResult(
        home_win_prob=float(home_wins) / denom,
        away_win_prob=float(away_wins) / denom,
        avg_total_runs=total_sum / denom,
        avg_away_runs=away_sum / denom,
        avg_home_runs=home_sum / denom,
        total_runs_dist=dist,
        margin_dist=margin,
        batter_stat_dist=batter_dist,
        pitcher_stat_dist=pitcher_dist,
        sims_run=sims_run,
    )
