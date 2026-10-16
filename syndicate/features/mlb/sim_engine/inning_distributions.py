"""Per-inning run distributions -- the vector the sim already builds and throws away.

WHAT WAS BEING COLLAPSED. `GameResult.away_inning_runs` / `home_inning_runs` are
nine-plus element vectors (`models.py`, filled in `simulate.py`'s half-inning
apply). `daily_update._sim_many` reduces every one of them through
`seg_score(r, innings)` -- which SUMS a prefix -- into four cumulative scalars
(`full`, `first1`, `first3`, `first5`) and then into counters. `r` is dropped at
the next loop iteration. Nothing downstream can ever ask "what does the sim think
about the 7th inning", or "runs from here to the end", because by the time the
artifact is written the shape is gone.

This module is the counters that keep it. It holds **integers only** -- never a
`GameResult`, never a vector, never a per-sim row. A 1,000-sim game leaves it
holding a few hundred `int -> int` entries regardless of sim count, because the
histogram keys are run values (0..~5 per inning), not simulations.

PACKING CONVENTION, DELIBERATELY THE EXISTING ONE. Each inning publishes a block
shaped exactly like `sim.segments.{full,first1,first3,first5}`: a
`total_runs_dist` and a `run_margin_dist` mapping value -> count, plus means.
`syndicate/features/shared/prop_projections.py:887-942` already walks precisely
those two keys to price segment totals and spreads, so a future consumer prices
an inning-level market with that walk **unchanged** -- it is handed the inning's
block where it is handed a segment's block today. The per-team
`away_runs_dist`/`home_runs_dist` are the additional shape a segment does not
carry, because inning-level team-total markets need the marginal, not the sum.

THE EXTRAS BUCKET IS NOT A ROUNDING. A 10th-inning run is real, it is in the
final score, and dropping it would make the per-inning blocks disagree with
`segments.full` about the same simulation. `extras` holds, per simulation, the
SUM of runs scored in innings 10+, so mass reconciles: summing run mass over
innings 1..9 plus extras equals the run mass in `segments.full.total_runs_dist`
exactly. Games that ended in 9 contribute a 0 to the extras bucket rather than
nothing, so every bucket's counts sum to the sim count.

`not_batted` IS SEPARATE FROM A ZERO. A home team ahead after the top of the 9th
never bats, so its vector is short. Those innings are recorded as 0 runs -- which
is what a totals market wants and what keeps the counts summing to the sim count
-- and the number of times it happened is published beside the histogram so the
two cases stay distinguishable. Conflating them silently is the failure mode the
model-engine standard exists to prevent.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional, Sequence, Tuple

DISTRIBUTION_VERSION = 1

REGULATION_INNINGS = 9
EXTRAS_KEY = "extras"
INNING_KEYS: Tuple[str, ...] = tuple(str(i) for i in range(1, REGULATION_INNINGS + 1))
ALL_KEYS: Tuple[str, ...] = INNING_KEYS + (EXTRAS_KEY,)

ENV_FLAG = "SYNDICATE_MLB_INNING_DISTRIBUTIONS"

_TRUE = {"1", "on", "true", "yes", "y"}


def enabled(env: Optional[Dict[str, str]] = None) -> bool:
    """ABSENT MEANS OFF.

    The whole falsification test for this feature is that with the flag unset the
    published artifact is byte-identical to what it was before the code existed,
    so the default must be the one that writes nothing. Note the contrast with
    `SYNDICATE_MLB_CONDITIONAL_MIX`, which defaults ON and is switched OFF -- the
    same env-var idiom with the opposite default, which is exactly the trap
    CLAUDE.md's "Absent != off" note is about. Read this function, not the name.
    """
    src = os.environ if env is None else env
    return str(src.get(ENV_FLAG, "") or "").strip().lower() in _TRUE


def _new_hist_map() -> Dict[str, Dict[int, int]]:
    return {key: {} for key in ALL_KEYS}


class InningRunAccumulator:
    """Counters only. Never retains a `GameResult` or a run vector.

    One instance per game (per chunk, on the multiprocessing path). `record` is
    called with the two vectors and immediately discards them; the instance's
    size is bounded by the number of DISTINCT run values seen, not by sims.
    """

    __slots__ = (
        "away",
        "home",
        "total",
        "margin",
        "away_not_batted",
        "home_not_batted",
        "sims",
        "extras_games",
        "max_inning",
    )

    def __init__(self) -> None:
        self.away: Dict[str, Dict[int, int]] = _new_hist_map()
        self.home: Dict[str, Dict[int, int]] = _new_hist_map()
        self.total: Dict[str, Dict[int, int]] = _new_hist_map()
        self.margin: Dict[str, Dict[int, int]] = _new_hist_map()
        self.away_not_batted: Dict[str, int] = {key: 0 for key in ALL_KEYS}
        self.home_not_batted: Dict[str, int] = {key: 0 for key in ALL_KEYS}
        self.sims: int = 0
        self.extras_games: int = 0
        self.max_inning: int = 0

    # -- accumulation ------------------------------------------------------

    def _bump(self, key: str, a: int, h: int) -> None:
        away = self.away[key]
        away[a] = away.get(a, 0) + 1
        home = self.home[key]
        home[h] = home.get(h, 0) + 1
        tot = self.total[key]
        t = a + h
        tot[t] = tot.get(t, 0) + 1
        mar = self.margin[key]
        m = h - a
        mar[m] = mar.get(m, 0) + 1

    def record(self, away_inning_runs: Optional[Sequence[int]], home_inning_runs: Optional[Sequence[int]]) -> None:
        av: Sequence[int] = away_inning_runs or ()
        hv: Sequence[int] = home_inning_runs or ()
        n_a = len(av)
        n_h = len(hv)
        for idx in range(REGULATION_INNINGS):
            key = INNING_KEYS[idx]
            if idx < n_a:
                a = int(av[idx])
            else:
                a = 0
                self.away_not_batted[key] += 1
            if idx < n_h:
                h = int(hv[idx])
            else:
                h = 0
                self.home_not_batted[key] += 1
            self._bump(key, a, h)

        extra_a = 0
        for idx in range(REGULATION_INNINGS, n_a):
            extra_a += int(av[idx])
        extra_h = 0
        for idx in range(REGULATION_INNINGS, n_h):
            extra_h += int(hv[idx])
        self._bump(EXTRAS_KEY, extra_a, extra_h)

        depth = n_a if n_a > n_h else n_h
        if depth > REGULATION_INNINGS:
            self.extras_games += 1
        if depth > self.max_inning:
            self.max_inning = depth
        self.sims += 1

    # -- transport across the multiprocessing boundary ---------------------

    def to_transport(self) -> Dict[str, Any]:
        """Plain nested dicts of ints -- picklable, and small.

        `_merge_seg` merges counts only, so a chunk-local accumulator that had no
        transport would be silently discarded on the DEFAULT execution path
        (`--workers` is 4). That is the exact bug `#621` Phase 4 had to fix for
        the joint; it is not repeated here.
        """
        return {
            "away": {k: dict(v) for k, v in self.away.items()},
            "home": {k: dict(v) for k, v in self.home.items()},
            "total": {k: dict(v) for k, v in self.total.items()},
            "margin": {k: dict(v) for k, v in self.margin.items()},
            "away_not_batted": dict(self.away_not_batted),
            "home_not_batted": dict(self.home_not_batted),
            "sims": int(self.sims),
            "extras_games": int(self.extras_games),
            "max_inning": int(self.max_inning),
        }

    def extend(self, transport: Optional[Dict[str, Any]]) -> None:
        if not transport:
            return
        for field in ("away", "home", "total", "margin"):
            src = transport.get(field) or {}
            dst = getattr(self, field)
            for key, hist in src.items():
                if key not in dst:
                    continue
                bucket = dst[key]
                for value, count in (hist or {}).items():
                    iv = int(value)
                    bucket[iv] = bucket.get(iv, 0) + int(count)
        for field in ("away_not_batted", "home_not_batted"):
            src = transport.get(field) or {}
            dst = getattr(self, field)
            for key, count in src.items():
                if key in dst:
                    dst[key] = int(dst[key]) + int(count)
        self.sims += int(transport.get("sims") or 0)
        self.extras_games += int(transport.get("extras_games") or 0)
        incoming_max = int(transport.get("max_inning") or 0)
        if incoming_max > self.max_inning:
            self.max_inning = incoming_max

    # -- publication -------------------------------------------------------

    def to_payload(self) -> Dict[str, Any]:
        denom = float(self.sims) if self.sims else 1.0
        by_inning: Dict[str, Dict[str, Any]] = {}
        for key in ALL_KEYS:
            away_hist = self.away[key]
            home_hist = self.home[key]
            by_inning[key] = {
                "away_runs_dist": dict(away_hist),
                "home_runs_dist": dict(home_hist),
                # The two keys `prop_projections.project_game_market` reads.
                "total_runs_dist": dict(self.total[key]),
                "run_margin_dist": dict(self.margin[key]),
                "away_runs_mean": hist_mass(away_hist) / denom,
                "home_runs_mean": hist_mass(home_hist) / denom,
                "away_not_batted": int(self.away_not_batted[key]),
                "home_not_batted": int(self.home_not_batted[key]),
            }
        return {
            "distribution_version": int(DISTRIBUTION_VERSION),
            "sims": int(self.sims),
            # "was the extras bucket POPULATED" is a different question from
            # "does the extras key exist" -- it always exists, and carries a 0
            # for every game that ended in nine. A consumer that cannot tell
            # those apart would read a slate of nine-inning games as evidence
            # that extras are not modelled.
            "extras_populated": bool(self.extras_games),
            "extras_games": int(self.extras_games),
            "max_inning_seen": int(self.max_inning),
            "regulation_innings": int(REGULATION_INNINGS),
            "by_inning": by_inning,
        }


def hist_mass(hist: Any) -> float:
    """Sum of value*count. The reconciliation primitive the tests assert on.

    A marginal per-inning accumulator cannot reconstruct a joint game total
    distribution -- that would need the per-sim rows this module deliberately
    refuses to keep. What it CAN reconcile, and what must hold exactly, is total
    run MASS: the runs the per-inning blocks account for and the runs
    `segments.full.total_runs_dist` accounts for are the same simulations, so
    they are the same integer.
    """
    total = 0.0
    for value, count in (hist or {}).items():
        total += float(int(value)) * float(int(count))
    return total


def hist_count(hist: Any) -> int:
    """Sum of counts. Must equal the sim count for every bucket."""
    return sum(int(c) for c in (hist or {}).values())


def accumulator_for(sims: int, *, want: bool) -> Optional["InningRunAccumulator"]:
    """None when not wanted, so the caller can omit the key entirely.

    Absent must mean "not measured", never "measured, nothing there" -- the same
    distinction `_joint_accumulator_for` draws directly above this in the caller.
    """
    if not want or int(sims or 0) < 1:
        return None
    try:
        return InningRunAccumulator()
    except Exception:
        # An addition must never be able to fail a sim that would otherwise
        # have produced its marginals.
        return None
