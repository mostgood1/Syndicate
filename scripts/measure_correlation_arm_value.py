"""Does `#621`'s MEASURED same-game correlation price better than the heuristic?

THE QUESTION. `#621` Phase 4 replaced a hand-authored constant table -- one
value for every player in every game -- with a correlation the MLB sim actually
computes (`record["sim"]["joint"]`). That number reaches parlay pricing, the
board correlation badges, and `bankroll_manager.build_portfolio` BET SIZING, so
"is it better" is a money question, not a curiosity.

--------------------------------------------------------------------------
WHY THIS DOES NOT WAIT FOR SETTLED PARLAYS
--------------------------------------------------------------------------

**No multi-leg parlay has ever been placed or settled by this system.**
`execution_ledger.py` says it outright -- "the board does not bet parlays" --
and the one parlay in the prediction ledger is a 4-leg cross-sport bet sitting
at `pending` (`ledger_bridge.py`, module docstring). A prior measurement in this
repo died waiting for exactly that kind of fill: the order-side arm had
`sim_view` on 13 of 667 settled orders, all one arm, needing ~3,796 attributed
orders (~108 days) to reach power, and the treatment arm could never fill
because stake gates censored it.

So this scores REALISED CO-OCCURRENCE of SINGLE legs instead. For any two prop
legs on the same game whose outcomes are both known, `both_won` is a realised
joint outcome, and it needs no parlay to have been placed. That is the whole
trick: the estimator under test prices `P(A and B)`, and `both_won` is a draw
from exactly that distribution whether or not anyone bet it.

--------------------------------------------------------------------------
THREE ARMS ON IDENTICAL MARGINALS
--------------------------------------------------------------------------

This is the discipline that makes it a test of the CORRELATION term and nothing
else. For every pair, `p_A` and `p_B` are held FIXED and only the dependence
varies:

    1. INDEPENDENCE  rho = 0                  -> exactly p_A * p_B
    2. HEURISTIC     `compute_correlation` with NO resolver installed
    3. MEASURED      `compute_correlation` WITH the joint resolver installed

All three are pushed through
`intelligence_parlay_runtime._correlation_adjusted_probability`, the ACTUAL
production estimator, rather than a reimplementation of it. If that function
changes shape, this harness changes with it for free -- which is the point.

Scored with log-loss AND Brier against the realised `both_won` indicator, plus a
calibration table per arm, because an arm can rank well and still be miscalibrated
and it is the calibration that sizes bets.

--------------------------------------------------------------------------
OVER LEGS ONLY BY DEFAULT, AND THE REASON IS A DEFECT IN THE MEASURED PATH
--------------------------------------------------------------------------

The joint stores `spearman_rank` correlation between the underlying STAT
columns. For two OVER legs the stat correlation and the win-indicator
correlation share a sign, so the number transfers. For an OVER against an UNDER
the indicator correlation is NEGATED, and `JointCorrelationIndex.measured()`
does not negate it -- `_resolve_candidate` builds a label
`batter|<pid>|<market>` that carries NO direction, so the resolver returns the
same positive number for `Over x Over` and `Over x Under`.

The heuristic path DOES handle direction (`_same_direction_bonus`: +0.08 same,
-0.14 opposed; `same_subject` opposed takes a further -0.30). So mixing sides
would not compare two estimates of one quantity, it would compare a
direction-aware estimator against a direction-blind one, and the measured arm
would be charged for a defect that has nothing to do with whether measuring the
correlation is a good idea.

`--sides over,under` runs it anyway and the report counts the opposed pairs.
The default stays `over` so the headline answers the question actually asked.

--------------------------------------------------------------------------
THE STATISTICS THAT ARE OTHERWISE WRONG
--------------------------------------------------------------------------

**PAIRS WITHIN ONE GAME ARE NOT INDEPENDENT OBSERVATIONS.** A game with 20
settled legs yields 190 pairs that all share the same nine innings. Treating
them as 190 observations is the single most likely way to produce a confident
wrong answer here, so every interval in this report is a CLUSTER BOOTSTRAP OVER
GAMES -- games are resampled with replacement, never pairs. The arms are compared
PAIRED on each resample, so the CI is on the DIFFERENCE and the common
game-difficulty term cancels.

**THE CLUSTER COUNT IS THE SAMPLE SIZE, NOT THE PAIR COUNT.** Manufacturing more
legs inside one game buys precision that does not exist. With one cluster the
between-game variance is not merely large, it is UNDEFINED, and this script says
so rather than printing a zero-width interval.

**AN UNDERPOWERED NULL IS NOT EVIDENCE OF NO EFFECT.** When the clusters cannot
separate the arms, the verdict is `UNDERPOWERED` and the report states how many
clusters would be needed. It never reads as "no difference".

--------------------------------------------------------------------------
SUBSTRATE (`model_engine_standard` Sec 3b)
--------------------------------------------------------------------------

`render` by default: every input is pulled from `/api/ops/artifacts/export` on
the live web service and the report stamps `substrate=render`. `--offline-dir`
replays a previously pulled cache and stamps `substrate=cache:<dir>`, which is
NOT a claim about production and is labelled that way in the output.

Reads are deliberately gentle -- `names_only` first, then ONE body at a time --
because web is a 2GB box with a confirmed retention problem (`#632`) and
`export` reads each artifact whole into that process.

Usage:
  py -3 scripts/measure_correlation_arm_value.py --date 2026-09-04
  py -3 scripts/measure_correlation_arm_value.py --date 2026-09-04 --json out.json
  py -3 scripts/measure_correlation_arm_value.py --date 2026-09-04 --offline-dir .cache/x
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
import os
import random
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_BASE = "https://syndicate-an21.onrender.com"

SIM_GLOB = "mlb_source/source_artifacts/data/daily/sims/{date}/sim_*.json"
GAME_LOG = "mlb_source/source_artifacts/data/processed/mlb_batter_game_log.csv"

#: joint dimension -> (canonical market key, game-log outcome column).
#: The canonical key is what `sim_joint_correlation.CANONICAL_MARKET_TO_JOINT`
#: keys on; the column is the CSV's own spelling.
#:
#: THE COLUMN NAMES ARE THE CSV'S, NOT THE STATSAPI BOX-SCORE'S. An earlier
#: grader in this repo used `hits`/`totalBases`/`homeRuns` against a CSV whose
#: headers are `h`/`tb`/`hr`, every lookup missed, `float(row.get(k) or 0)` turned
#: each miss into 0.0, and the run "succeeded" while reporting a base rate of
#: 0.000. `_outcome_value` raises on a missing column instead.
MARKETS: dict[str, tuple[str, str]] = {
    "hits": ("batter_hits", "h"),
    "home_runs": ("batter_home_runs", "hr"),
    "total_bases": ("batter_total_bases", "tb"),
    "rbi": ("batter_rbis", "rbi"),
}

#: The lines books actually quote for these markets. All half-lines, so a leg
#: can never push and `both_won` is always defined.
STANDARD_LINES: dict[str, tuple[float, ...]] = {
    "hits": (0.5, 1.5, 2.5),
    "home_runs": (0.5,),
    "total_bases": (0.5, 1.5, 2.5),
    "rbi": (0.5, 1.5),
}

MARKET_LABEL = {
    "hits": "Hits",
    "home_runs": "Home Runs",
    "total_bases": "Total Bases",
    "rbi": "RBIs",
}

#: A leg this extreme carries almost no information about the dependence term and
#: destabilises log-loss. Both arms see the identical filter, so it cannot favour
#: one of them.
MIN_LEG_PROB = 0.02
MAX_LEG_PROB = 0.98

ARMS = ("independence", "heuristic", "measured")


# ---------------------------------------------------------------------------
# production access
# ---------------------------------------------------------------------------


def admin_token() -> str:
    """The gitignored `.env` beside the repo, never argv, so the secret cannot
    reach a log or a prompt."""
    token = str(os.environ.get("ADMIN_TOKEN") or "").strip()
    if token:
        return token
    env = REPO_ROOT / ".env"
    if env.is_file():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("ADMIN_TOKEN="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("no ADMIN_TOKEN in the environment or .env")


def export(base: str, params: dict, timeout: int = 300) -> dict:
    url = f"{base}/api/ops/artifacts/export?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"X-Admin-Token": admin_token()})
    with urllib.request.urlopen(request, timeout=timeout) as handle:
        return json.loads(handle.read().decode("utf-8"))


def fetch_inputs(date_str: str, cache_dir: Path, base: str, pause: float = 0.5) -> Path:
    """Pull one date's sims + the batter game log into `cache_dir`.

    `names_only` FIRST, then one body at a time. `export` reads each artifact
    whole into the web process, so a glob-everything request is a memory event on
    a service someone is usually debugging.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    inventory = export(base, {"pattern": SIM_GLOB.format(date=date_str), "names_only": "1"})
    names = sorted((inventory.get("artifacts") or {}))
    print(f"[fetch] {len(names)} sim artifact(s) for {date_str}", flush=True)
    for name in names:
        dest = cache_dir / re.sub(r"[^A-Za-z0-9._-]", "_", name.split("/")[-1])
        if dest.exists() and dest.stat().st_size > 0:
            continue
        artifacts = export(base, {"pattern": name}).get("artifacts") or {}
        if not artifacts:
            continue
        raw = list(artifacts.values())[0]
        dest.write_text(raw if isinstance(raw, str) else json.dumps(raw), encoding="utf-8")
        time.sleep(pause)
    log_dest = cache_dir / "mlb_batter_game_log.csv"
    if not log_dest.exists():
        artifacts = export(base, {"pattern": GAME_LOG}).get("artifacts") or {}
        if artifacts:
            log_dest.write_text(list(artifacts.values())[0], encoding="utf-8")
    print(f"[fetch] cached into {cache_dir}", flush=True)
    return cache_dir


# ---------------------------------------------------------------------------
# marginals, outcomes, legs
# ---------------------------------------------------------------------------


def prob_over(distribution: dict[str, Any], line: float) -> float | None:
    """`P(stat > line)` from the sim's own count histogram.

    The histogram is the SAME 1,000 simulations the joint was computed over, so
    the marginals and the correlation are consistent by construction -- there is
    no join between them to get wrong.
    """
    total = 0
    above = 0
    for raw_value, raw_count in (distribution or {}).items():
        try:
            value = float(raw_value)
            count = int(raw_count)
        except (TypeError, ValueError):
            continue
        if count < 0:
            continue
        total += count
        if value > line:
            above += count
    if total <= 0:
        return None
    return above / float(total)


@dataclass(frozen=True)
class Leg:
    game_pk: int
    player_id: int
    player_name: str
    team: str
    market: str          # joint dimension: hits / home_runs / total_bases / rbi
    line: float
    side: str            # "over" | "under"
    probability: float   # model P(this leg wins)
    won: int             # realised 0/1

    @property
    def canonical_market(self) -> str:
        return MARKETS[self.market][0]

    def candidate(self) -> dict[str, Any]:
        """The dict shape BOTH consumers read.

        `correlation_engine` keys the game off `matchup`/`game_id`/`event_id`
        (NOT `game_pk`), while `sim_joint_correlation` keys it off
        `game_pk`/`game_id`. Supplying both is what makes the heuristic arm and
        the measured arm see the SAME pair rather than two different ones -- and
        a mismatch here would silently score two different questions.
        """
        label = f"{self.side.title()} {self.line:g} {MARKET_LABEL[self.market]}"
        return {
            "sport_slug": "mlb",
            "sport": "mlb",
            "game_id": str(self.game_pk),
            "game_pk": self.game_pk,
            "event_id": str(self.game_pk),
            "team": self.team,
            "team_key": self.team,
            "player_id": self.player_id,
            "player_name": self.player_name,
            "subject_key": self.player_name,
            "market_key": self.canonical_market,
            "market": self.canonical_market,
            "stat": self.market,
            "line": self.line,
            "pick": label,
            "name": f"{self.player_name} {label}",
            "model_probability": self.probability,
        }


def _outcome_value(row: dict[str, str], column: str) -> float:
    if column not in row:
        raise KeyError(
            f"game-log column {column!r} absent; columns are {sorted(row)}. "
            "Refusing to coerce a missing column to 0.0 -- that is how a grader "
            "in this repo silently reported a 0.000 base rate."
        )
    text = str(row.get(column) or "").strip()
    return float(text) if text else 0.0


def load_outcomes(game_log_text: str, date_str: str) -> dict[tuple[int, int], dict[str, str]]:
    rows = list(csv.DictReader(io.StringIO(game_log_text)))
    out: dict[tuple[int, int], dict[str, str]] = {}
    for row in rows:
        if str(row.get("date") or "") != date_str:
            continue
        try:
            out[(int(row["game_pk"]), int(row["player_id"]))] = row
        except (TypeError, ValueError, KeyError):
            continue
    return out


def build_legs(
    sim_records: dict[int, dict[str, Any]],
    outcomes: dict[tuple[int, int], dict[str, str]],
    *,
    sides: Sequence[str] = ("over",),
    lineup_only: bool = True,
) -> tuple[list[Leg], Counter]:
    """One leg per (batter, market, line, side) that is BOTH priced and graded."""
    legs: list[Leg] = []
    skipped: Counter = Counter()
    for game_pk, record in sorted(sim_records.items()):
        hitter_props = ((record or {}).get("sim") or {}).get("hitter_props") or {}
        for raw_pid, profile in hitter_props.items():
            try:
                player_id = int(raw_pid)
            except (TypeError, ValueError):
                skipped["bad_player_id"] += 1
                continue
            if lineup_only and not profile.get("is_lineup_batter"):
                skipped["not_in_lineup"] += 1
                continue
            outcome_row = outcomes.get((game_pk, player_id))
            if outcome_row is None:
                skipped["no_realised_outcome"] += 1
                continue
            for market, (_canonical, column) in MARKETS.items():
                distribution = profile.get(f"{market}_dist")
                if not distribution:
                    skipped["no_marginal_distribution"] += 1
                    continue
                actual = _outcome_value(outcome_row, column)
                for line in STANDARD_LINES[market]:
                    p_over = prob_over(distribution, line)
                    if p_over is None:
                        skipped["degenerate_distribution"] += 1
                        continue
                    for side in sides:
                        probability = p_over if side == "over" else 1.0 - p_over
                        if not (MIN_LEG_PROB <= probability <= MAX_LEG_PROB):
                            skipped["leg_probability_out_of_band"] += 1
                            continue
                        won = int(actual > line) if side == "over" else int(actual < line)
                        legs.append(
                            Leg(
                                game_pk=game_pk,
                                player_id=player_id,
                                player_name=str(profile.get("name") or ""),
                                team=str(profile.get("team") or ""),
                                market=market,
                                line=float(line),
                                side=side,
                                probability=float(probability),
                                won=won,
                            )
                        )
    return legs, skipped


@dataclass
class Pair:
    game_pk: int
    leg_a: Leg
    leg_b: Leg
    both_won: int
    same_batter: bool
    same_team: bool
    predictions: dict[str, float] = field(default_factory=dict)
    correlations: dict[str, float] = field(default_factory=dict)

    @property
    def opposed_sides(self) -> bool:
        return self.leg_a.side != self.leg_b.side


def build_pairs(legs: Iterable[Leg]) -> list[Pair]:
    """Every same-game pair of legs on DIFFERENT joint dimensions.

    A pair of two legs on the same (batter, market) at different lines is
    excluded: it is one dimension against itself, the joint has no off-diagonal
    entry for it, and the two legs are nested rather than merely dependent.
    """
    by_game: dict[int, list[Leg]] = defaultdict(list)
    for leg in legs:
        by_game[leg.game_pk].append(leg)
    pairs: list[Pair] = []
    for game_pk, game_legs in sorted(by_game.items()):
        for leg_a, leg_b in combinations(game_legs, 2):
            if leg_a.player_id == leg_b.player_id and leg_a.market == leg_b.market:
                continue
            pairs.append(
                Pair(
                    game_pk=game_pk,
                    leg_a=leg_a,
                    leg_b=leg_b,
                    both_won=int(leg_a.won and leg_b.won),
                    same_batter=leg_a.player_id == leg_b.player_id,
                    same_team=leg_a.team == leg_b.team,
                )
            )
    return pairs


# ---------------------------------------------------------------------------
# the three arms
# ---------------------------------------------------------------------------


def build_joint_index(sim_records: dict[int, dict[str, Any]], date_str: str):
    """The REAL resolver, fed in memory.

    `JointCorrelationIndex.for_date` reads through `syndicate.features.mlb.sources`,
    which needs a data root on disk. `add_game` is the same class's own public
    construction path, so this exercises the production resolver -- its label
    indexing, its packed-triangle reader, its `undefined` sentinel handling and
    its name/id keying -- without requiring the artifact tree to be mounted.
    """
    from syndicate.features.mlb.sim_joint_correlation import JointCorrelationIndex

    index = JointCorrelationIndex()
    index.date = str(date_str)
    for game_pk, record in sorted(sim_records.items()):
        joint = ((record or {}).get("sim") or {}).get("joint")
        if joint:
            index.add_game(int(game_pk), joint)
    return index


def score_arms(pairs: list[Pair], index) -> Counter:
    """Fill `pair.predictions` for all three arms, on IDENTICAL marginals."""
    from syndicate.features.correlation_engine import (
        compute_correlation,
        register_measured_correlation_resolver,
    )
    from syndicate.features.intelligence_parlay_runtime import (
        _correlation_adjusted_probability,
    )

    basis: Counter = Counter()

    # --- arm 1 + 2: heuristic, with the registry explicitly EMPTY -----------
    register_measured_correlation_resolver(None)
    for pair in pairs:
        candidate_a = pair.leg_a.candidate()
        candidate_b = pair.leg_b.candidate()
        probabilities = [pair.leg_a.probability, pair.leg_b.probability]
        pair.predictions["independence"] = _correlation_adjusted_probability(probabilities, 0.0)
        result = compute_correlation(candidate_a, candidate_b)
        basis[f"heuristic:{result.get('correlation_basis')}"] += 1
        rho = float(result.get("correlation_score") or 0.0)
        pair.correlations["heuristic"] = rho
        pair.predictions["heuristic"] = _correlation_adjusted_probability(probabilities, rho)

    # --- arm 3: measured, resolver installed process-wide -------------------
    register_measured_correlation_resolver(index.as_lookup())
    try:
        for pair in pairs:
            candidate_a = pair.leg_a.candidate()
            candidate_b = pair.leg_b.candidate()
            probabilities = [pair.leg_a.probability, pair.leg_b.probability]
            result = compute_correlation(candidate_a, candidate_b)
            basis[f"measured:{result.get('correlation_basis')}"] += 1
            rho = float(result.get("correlation_score") or 0.0)
            pair.correlations["measured"] = rho
            pair.predictions["measured"] = _correlation_adjusted_probability(probabilities, rho)
    finally:
        # NEVER leave a resolver installed in the process. It is process-wide
        # state and a later import in the same interpreter would inherit it.
        register_measured_correlation_resolver(None)

    return basis


# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------

_EPSILON = 1e-12


def log_loss(predictions: Sequence[float], outcomes: Sequence[int]) -> float:
    total = 0.0
    for probability, outcome in zip(predictions, outcomes):
        clipped = min(1.0 - _EPSILON, max(_EPSILON, probability))
        total += -(math.log(clipped) if outcome else math.log(1.0 - clipped))
    return total / float(len(predictions)) if predictions else float("nan")


def brier(predictions: Sequence[float], outcomes: Sequence[int]) -> float:
    if not predictions:
        return float("nan")
    return sum((p - o) ** 2 for p, o in zip(predictions, outcomes)) / float(len(predictions))


def metrics_for(pairs: Sequence[Pair], arm: str) -> dict[str, float]:
    predictions = [p.predictions[arm] for p in pairs]
    outcomes = [p.both_won for p in pairs]
    return {
        "log_loss": log_loss(predictions, outcomes),
        "brier": brier(predictions, outcomes),
        "mean_prediction": (sum(predictions) / len(predictions)) if predictions else float("nan"),
        "base_rate": (sum(outcomes) / len(outcomes)) if outcomes else float("nan"),
    }


def calibration_table(pairs: Sequence[Pair], arm: str, bins: int = 5) -> list[dict[str, Any]]:
    """Reliability, because ranking is not what sizes a bet."""
    edges = [i / bins for i in range(bins + 1)]
    table: list[dict[str, Any]] = []
    for low, high in zip(edges[:-1], edges[1:]):
        bucket = [
            p for p in pairs
            if (p.predictions[arm] >= low and (p.predictions[arm] < high or high == 1.0))
        ]
        if not bucket:
            continue
        predicted = sum(p.predictions[arm] for p in bucket) / len(bucket)
        realised = sum(p.both_won for p in bucket) / len(bucket)
        table.append(
            {
                "bin": f"[{low:.1f},{high:.1f})",
                "n": len(bucket),
                "mean_predicted": predicted,
                "realised": realised,
                "gap": predicted - realised,
            }
        )
    return table


def cluster_bootstrap(
    pairs: Sequence[Pair],
    arm_a: str,
    arm_b: str,
    metric: Callable[[Sequence[Pair], str], float],
    *,
    draws: int = 2000,
    seed: int = 20260904,
) -> dict[str, Any]:
    """CI on `metric(arm_a) - metric(arm_b)`, resampling GAMES not pairs.

    PAIRED on each resample: both arms are scored on the SAME resampled games, so
    the (large) between-game difficulty term cancels and what is left is the
    difference the dependence model makes.

    With fewer than two clusters the between-cluster variance is UNDEFINED, and
    this returns `None` bounds rather than a zero-width interval that would read
    as certainty.
    """
    by_game: dict[int, list[Pair]] = defaultdict(list)
    for pair in pairs:
        by_game[pair.game_pk].append(pair)
    games = sorted(by_game)
    point = metric(pairs, arm_a) - metric(pairs, arm_b)
    if len(games) < 2:
        return {
            "point": point,
            "low": None,
            "high": None,
            "clusters": len(games),
            "undefined_reason": "fewer than two clusters: between-game variance is undefined",
        }
    rng = random.Random(seed)
    deltas: list[float] = []
    for _ in range(draws):
        drawn: list[Pair] = []
        for _ in games:
            drawn.extend(by_game[games[rng.randrange(len(games))]])
        if not drawn:
            continue
        deltas.append(metric(drawn, arm_a) - metric(drawn, arm_b))
    deltas.sort()
    if not deltas:
        return {"point": point, "low": None, "high": None, "clusters": len(games)}
    low = deltas[int(0.025 * (len(deltas) - 1))]
    high = deltas[int(0.975 * (len(deltas) - 1))]
    crosses_zero = low <= 0.0 <= high
    return {
        "point": point,
        "low": low,
        "high": high,
        "clusters": len(games),
        "draws": len(deltas),
        "significant": not crosses_zero,
    }


def required_clusters(pairs: Sequence[Pair], arm_a: str, arm_b: str,
                      metric: Callable[[Sequence[Pair], str], float]) -> dict[str, Any]:
    """How many GAMES would be needed to resolve the observed per-game effect.

    A per-game paired difference has mean `d` and SD `s` across games; a paired
    test needs roughly `n >= (1.96 * s / |d|)^2` clusters. Reported so an
    underpowered result carries its own price rather than being read as a null.
    """
    by_game: dict[int, list[Pair]] = defaultdict(list)
    for pair in pairs:
        by_game[pair.game_pk].append(pair)
    per_game = [metric(v, arm_a) - metric(v, arm_b) for v in by_game.values()]
    n = len(per_game)
    if n < 2:
        return {"clusters_observed": n, "needed": None,
                "reason": "fewer than two clusters: no between-game SD exists"}
    mean = sum(per_game) / n
    variance = sum((d - mean) ** 2 for d in per_game) / (n - 1)
    sd = math.sqrt(variance)
    if abs(mean) < 1e-15:
        return {"clusters_observed": n, "per_game_mean": mean, "per_game_sd": sd,
                "needed": None, "reason": "observed per-game effect is exactly zero"}
    return {
        "clusters_observed": n,
        "per_game_mean": mean,
        "per_game_sd": sd,
        "needed": int(math.ceil((1.96 * sd / abs(mean)) ** 2)),
    }


# ---------------------------------------------------------------------------
# loading
# ---------------------------------------------------------------------------


def load_cached(cache_dir: Path, date_str: str) -> tuple[dict[int, dict[str, Any]], dict]:
    sim_records: dict[int, dict[str, Any]] = {}
    for path in sorted(cache_dir.glob("sim_*.json")):
        match = re.search(r"pk(\d+)", path.name)
        if not match:
            continue
        try:
            sim_records[int(match.group(1))] = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
    log_path = cache_dir / "mlb_batter_game_log.csv"
    outcomes = (
        load_outcomes(log_path.read_text(encoding="utf-8"), date_str) if log_path.is_file() else {}
    )
    return sim_records, outcomes


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------


def run(date_str: str, cache_dir: Path, substrate: str, *, draws: int,
        sides: Sequence[str], json_out: Path | None) -> int:
    sim_records, outcomes = load_cached(cache_dir, date_str)
    joint_games = {
        pk for pk, rec in sim_records.items() if ((rec or {}).get("sim") or {}).get("joint")
    }
    outcome_games = {pk for pk, _ in outcomes}

    print("=" * 78)
    print(f"MEASURED vs HEURISTIC same-game correlation -- {date_str}")
    print(f"substrate={substrate}")
    print("=" * 78)
    print("\n--- FEASIBILITY: the date intersection, with denominators ---")
    print(f"  sim artifacts read            : {len(sim_records)}")
    print(f"  games carrying sim.joint      : {len(joint_games)} / {len(sim_records)}")
    print(f"  games with realised outcomes  : {len(outcome_games)}")
    intersection = joint_games & outcome_games
    print(f"  INTERSECTION (joint AND graded): {len(intersection)}  {sorted(intersection)}")
    if not intersection:
        print("\nVERDICT: INTERSECTION EMPTY -- no game has both a joint and a graded outcome.")
        print("The measurement is not answerable on this date. Re-run when it is.")
        return 2

    usable = {pk: rec for pk, rec in sim_records.items() if pk in intersection}
    legs, skipped = build_legs(usable, outcomes, sides=tuple(sides))
    pairs = build_pairs(legs)
    clusters = len({p.game_pk for p in pairs})
    print("\n--- LEGS AND PAIRS ---")
    print(f"  legs built                    : {len(legs)}  (sides={','.join(sides)})")
    print(f"  legs skipped                  : {dict(skipped)}")
    print(f"  same-game pairs               : {len(pairs)}")
    print(f"  CLUSTERS (games)              : {clusters}")
    if not pairs:
        print("\nVERDICT: no gradeable pairs. Not answerable on this date.")
        return 2
    opposed = sum(1 for p in pairs if p.opposed_sides)
    if opposed:
        print(f"  OPPOSED-SIDE pairs            : {opposed} / {len(pairs)} -- the measured "
              f"resolver does NOT negate for these (see the module docs)")

    index = build_joint_index(usable, date_str)
    basis = score_arms(pairs, index)
    print(f"  resolver games_with_joint     : {index.games_with_joint}")
    print(f"  resolver reasons              : {dict(index.reasons)}")
    print(f"  correlation_basis tally       : {dict(basis)}")

    measured_count = basis.get("measured:measured_joint", 0)
    if measured_count == 0:
        print("\nVERDICT: the MEASURED arm answered on ZERO pairs -- it is identical to")
        print("the heuristic arm here, so this run cannot compare them. Not answerable.")
        return 2

    print("\n--- CORRELATION TERM (this is what differs between arms) ---")
    for arm in ("heuristic", "measured"):
        values = [p.correlations[arm] for p in pairs if arm in p.correlations]
        if not values:
            continue
        values_sorted = sorted(values)
        mid = values_sorted[len(values_sorted) // 2]
        print(f"  {arm:11} n={len(values):6}  min={values_sorted[0]:+.3f}  "
              f"median={mid:+.3f}  max={values_sorted[-1]:+.3f}  "
              f"mean={sum(values)/len(values):+.3f}")

    print(f"\n--- SCORES (n={len(pairs)} pairs over {clusters} games) ---")
    print(f"  {'arm':13} {'log_loss':>10} {'brier':>10} {'mean_pred':>10} {'base_rate':>10}")
    results: dict[str, dict[str, float]] = {}
    for arm in ARMS:
        m = metrics_for(pairs, arm)
        results[arm] = m
        print(f"  {arm:13} {m['log_loss']:>10.5f} {m['brier']:>10.5f} "
              f"{m['mean_prediction']:>10.5f} {m['base_rate']:>10.5f}")

    print("\n--- CALIBRATION (predicted vs realised; ranking is not enough) ---")
    for arm in ARMS:
        print(f"  {arm}:")
        for row in calibration_table(pairs, arm):
            print(f"    {row['bin']:12} n={row['n']:6}  pred={row['mean_predicted']:.4f}  "
                  f"real={row['realised']:.4f}  gap={row['gap']:+.4f}")

    print("\n--- GAME-CLUSTERED BOOTSTRAP on the DIFFERENCE (games resampled, not pairs) ---")
    comparisons = [("measured", "heuristic"), ("measured", "independence"),
                   ("heuristic", "independence")]
    bootstrap: dict[str, Any] = {}
    for arm_a, arm_b in comparisons:
        for metric_name, metric_fn in (
            ("log_loss", lambda ps, a: metrics_for(ps, a)["log_loss"]),
            ("brier", lambda ps, a: metrics_for(ps, a)["brier"]),
        ):
            result = cluster_bootstrap(pairs, arm_a, arm_b, metric_fn, draws=draws)
            key = f"{arm_a}-{arm_b}:{metric_name}"
            bootstrap[key] = result
            if result.get("low") is None:
                print(f"  {key:34} delta={result['point']:+.5f}  CI=UNDEFINED "
                      f"({result.get('undefined_reason')})")
            else:
                verdict = "SEPARATES" if result["significant"] else "cannot separate"
                print(f"  {key:34} delta={result['point']:+.5f}  "
                      f"95% CI [{result['low']:+.5f}, {result['high']:+.5f}]  {verdict}")

    print("\n--- POWER ---")
    power = required_clusters(pairs, "measured", "heuristic",
                              lambda ps, a: metrics_for(ps, a)["log_loss"])
    print(f"  clusters observed : {power['clusters_observed']}")
    if power.get("needed") is None:
        print(f"  clusters needed   : UNDETERMINED -- {power.get('reason')}")
    else:
        print(f"  per-game mean delta (log-loss, measured-heuristic): {power['per_game_mean']:+.5f}")
        print(f"  per-game SD                                       : {power['per_game_sd']:.5f}")
        print(f"  clusters needed for 95% resolution                : ~{power['needed']}")

    separated = any(
        v.get("significant") for k, v in bootstrap.items() if k.startswith("measured-heuristic")
    )
    print(f"\n{'=' * 78}")
    if separated:
        delta = bootstrap["measured-heuristic:log_loss"]["point"]
        print(f"VERDICT: the arms SEPARATE. measured - heuristic log-loss = {delta:+.5f} "
              f"({'measured better' if delta < 0 else 'heuristic better'}).")
    else:
        print("VERDICT: UNDERPOWERED. The clusters available cannot separate the arms.")
        print("THIS IS NOT EVIDENCE OF NO EFFECT. It is an absence of resolution.")
        if power.get("needed"):
            print(f"Resolving the observed per-game effect needs ~{power['needed']} game-clusters; "
                  f"this run has {power['clusters_observed']}.")
    print("=" * 78)

    if json_out:
        json_out.write_text(
            json.dumps(
                {
                    "date": date_str,
                    "substrate": substrate,
                    "games_total": len(sim_records),
                    "games_with_joint": len(joint_games),
                    "games_with_outcomes": len(outcome_games),
                    "intersection": sorted(intersection),
                    "legs": len(legs),
                    "pairs": len(pairs),
                    "clusters": clusters,
                    "opposed_side_pairs": opposed,
                    "correlation_basis": dict(basis),
                    "metrics": results,
                    "bootstrap": bootstrap,
                    "power": power,
                    "calibration": {a: calibration_table(pairs, a) for a in ARMS},
                },
                indent=1,
                default=str,
            ),
            encoding="utf-8",
        )
        print(f"\nwrote {json_out}")
    return 0 if separated else 3


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--date", help="slate date, YYYY-MM-DD")
    parser.add_argument("--base-url", default=DEFAULT_BASE)
    parser.add_argument("--cache-dir", default=None,
                        help="where production artifacts are cached (default .cache/corr_arms/<date>)")
    parser.add_argument("--offline-dir", default=None,
                        help="replay a cache without touching production; NOT a claim about production")
    parser.add_argument("--sides", default="over",
                        help="comma list of over,under. DEFAULT over ONLY -- see the "
                             "direction caveat in the module docs")
    parser.add_argument("--draws", type=int, default=2000)
    parser.add_argument("--json", dest="json_out", default=None)
    args = parser.parse_args()

    if args.offline_dir:
        cache_dir = Path(args.offline_dir)
        date_str = args.date or ""
        if not date_str:
            parser.error("--offline-dir needs --date")
        substrate = f"cache:{cache_dir}"
    else:
        if not args.date:
            parser.error("--date is required")
        date_str = args.date
        cache_dir = Path(args.cache_dir) if args.cache_dir else REPO_ROOT / ".cache" / "corr_arms" / date_str
        fetch_inputs(date_str, cache_dir, args.base_url)
        substrate = "render"

    return run(
        date_str,
        cache_dir,
        substrate,
        draws=args.draws,
        sides=[s.strip() for s in args.sides.split(",") if s.strip()],
        json_out=Path(args.json_out) if args.json_out else None,
    )


if __name__ == "__main__":
    raise SystemExit(main())
