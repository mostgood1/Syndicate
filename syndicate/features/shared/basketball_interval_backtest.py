"""Score basketball INTERVAL projections on replayed games: the bar every Phase 2 engine change must beat.

WHAT IS ASKED (user 2026-11-07, Phase 2 step 1 of the interval-projection plan). Projected full-game, first-half,
second-half and (quarter leagues) Q1-Q4 total and home margin, from inside a game, were what the old standalone
apps showed. Before any game-shape input (observed pace, shooting %, shot mix, end-game scenarios) goes into the
native engine, there has to be a number it must beat on the same games. This module is that number's machinery.

WHAT IT DOES, per completed game:
  1. steps through the game every `STEP_SECONDS` (30 s) of REGULATION clock;
  2. at each step rebuilds the state the live path would have built from the log so far -- score per period,
     period, clock, team fouls in the current foul bucket, possession after the last informative play, box counts
     (FGA / 3PA / FTA / TOV / OREB, made shots), and, for the sims, the on-floor fives and player fouls -- with the
     production builders (`basketball_live_state._possession_after` / `_team_fouls` / `_team_counts`,
     `basketball_pbp.reconstruct_from_events` on the PREFIX, so a period-start five is inferred only from plays
     already logged, exactly as live);
  3. asks every registered projector for {segment: (total, home margin)} for the segments still being played;
  4. scores against the actual segment results (`segment_actuals`, the book convention the live re-sims use:
     the full game and the second half include overtime, a quarter and the first half do not).

NOTHING HERE FETCHES, WRITES OR PRICES. It reads the `ReplayGame` it is handed. The script
`scripts/backtest_basketball_intervals.py` loads games read-only from a data root and writes its own report.
College segment PRICING stays off (`SYNDICATE_COLLEGE_LIVE_SEGMENT_PRICING`, todo #763): this measures, it ships nothing.

PROJECTORS (each a named variant behind one interface, `Projector`):
  naive_pace           the old NCAAB app's `proj_pace` (`mostgood1/NCAAB src/ncaab_model/eval/live_lens_interval_backtest.py`):
                       points so far / elapsed x regulation, extended to a segment as segment-so-far + the game's
                       own scoring rate x the segment's seconds left. The bar's own definition, reproduced.
  interval_projection  `basketball_interval_projection.project_interval` (the shipped naive module): this game's pace
                       x this game's points per possession for the rest of the current period, the same pace x ppp
                       for later periods; margin carried (the module projects no margin).
  league_rate          a walk-forward league scoring rate (games before this one's date) for the time left; margin
                       carried. #535's finding: league constants beat game-to-date pace.
  pregame_rate         the pregame line's share of the regulation left (`ncaab_corpus_baseline`'s naive bar).
  pooled_rate          PHASE 2 HOOK: the scoring rate pooled between the pregame line and this game's rate,
                       k = prior seconds of weight (#535: raw game pace HURT, so it must pool toward the prior).
  pooled_pace          PHASE 2 HOOK: possessions pooled toward the prior pace, points per possession from the line.
  pooled_efficiency    PHASE 2 HOOK: points per possession pooled toward the line's, possessions from the prior pace.
  resim / resim_anchored   today's live re-sim (`ncaab/live_resim.resim_live_game`, `league="ncaab"|"wncaab"`, or
                       `nba/live_resim.resim_live_game` for nba/wnba) resumed from the replay state. College margins
                       are market-anchored in production (`anchor_result`); `resim_anchored` is that, `resim` raw.
                       `mechanisms=` sets the default-off end-game mechanisms (SYNDICATE_*_LIVE_MECHANISMS) on the cfg.
  nba_tick             the ported NBA live tick's scope projection (`nba/live_tick/tick.py` `_scope_projection` over
                       `_live_interp_cum_p50`) on the pregame smart sim's 3-minute ladder: totals only, base scope
                       projection only (the tick's recent-window pace / efficiency adjustments are NOT replayed).

SHOT MIX is a declared extension point, not a shipped variant: `ReplayState.counts` carries FGA / 3PA / FTA and
makes per side, so a shot-mix projector is one more `Projector`. None is registered until one is written and tested.
"""

from __future__ import annotations

import bisect
import dataclasses
import math
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence

from syndicate.features.shared import basketball_pbp as pbp

STEP_SECONDS = 30
# The four snapshot points the old NCAAB app's bar is quoted at: minute 10 / 20 / 30 / 38 of a 40-minute game.
# NBA (48 min) and WNBA / WNCAAB (40 min) use the same FRACTIONS of regulation. `checkpoint_times` adds the tip
# ('0m'): the pregame number, where the old NBA app's quarter bar (MAE 8.53) is quoted.
CHECKPOINT_FRACTIONS = (0.25, 0.50, 0.75, 0.95)
# The old app's 2-minute elapsed bins are 5% of a 40-minute game; every league is binned at 5% of regulation.
BUCKET_FRACTION = 0.05
SEGMENT_PERIODS: dict[int, dict[str, tuple[int, ...]]] = {
    2: {"h1": (1,), "h2": (2,)},
    4: {"q1": (1,), "q2": (2,), "q3": (3,), "q4": (4,), "h1": (1, 2), "h2": (3, 4)},
}
# Segments that settle WITH overtime (`ncaab/live_resim.OVERTIME_SEGMENTS`, `nba/live_resim._segments`).
OVERTIME_SEGMENTS = frozenset({"full", "h2"})
LEAGUES = ("ncaab", "wncaab", "nba", "wnba")

Projection = Mapping[str, tuple[Optional[float], Optional[float]]]  # segment -> (total, home margin)


@dataclass(frozen=True)
class Refusal:
    reason: str
    detail: str = ""


# ------------------------------------------------------------------------------------------------ the game

@dataclass(frozen=True)
class ReplayGame:
    """One completed game, everything a projector may read. Built read-only by the script's loaders.

    `pregame_total` / `pregame_home_margin` are the PREGAME line (a close when the source has one) and
    `pregame_source` says which; None means the source has none and every line-based projector refuses by name.
    `extra` carries league-specific inputs: the re-sim's walk-forward priors, the tick's ladder, the league rate."""

    league: str
    game_id: str
    date: str
    phase: str
    meta: pbp.GameMeta
    events: tuple[pbp.PbpEvent, ...]
    pregame_total: Optional[float] = None
    pregame_home_margin: Optional[float] = None
    pregame_source: str = ""
    extra: Mapping[str, Any] = field(default_factory=dict)

    @property
    def rules(self) -> pbp.LeagueRules:
        return pbp.rules_for(self.league)

    @property
    def regulation_seconds(self) -> int:
        return int(self.rules.regulation_seconds())


def segments_for(league: str) -> dict[str, tuple[int, ...]]:
    """Every scored segment of a league, `full` first: name -> regulation periods (1-based)."""
    rules = pbp.rules_for(league)
    periods = int(rules.regulation_periods)
    return {"full": tuple(range(1, periods + 1)), **SEGMENT_PERIODS[periods]}


def points_by_period(events: Iterable[pbp.PbpEvent]) -> dict[str, dict[int, int]]:
    out: dict[str, dict[int, int]] = {"home": defaultdict(int), "away": defaultdict(int)}
    for ev in events:
        if ev.points and ev.side in out:
            out[ev.side][int(ev.period)] += int(ev.points)
    return out


def segment_actuals(game: ReplayGame) -> dict[str, tuple[int, int]] | Refusal:
    """{segment: (total, home margin)} as the books settle them, or a refusal when the log's points do not add up
    to the official final (the live path's `pbp_score_mismatch`: a log that misses plays cannot grade a segment)."""
    pts = points_by_period(game.events)
    reg = int(game.rules.regulation_periods)
    final_h = sum(pts["home"].values())
    final_a = sum(pts["away"].values())
    official = (game.meta.home.score, game.meta.away.score)
    if None in official or (final_h, final_a) != (int(official[0]), int(official[1])):
        return Refusal("pbp_final_mismatch", f"pbp {final_h}-{final_a} official {official[0]}-{official[1]}")
    ot_h = sum(v for p, v in pts["home"].items() if p > reg)
    ot_a = sum(v for p, v in pts["away"].items() if p > reg)
    out: dict[str, tuple[int, int]] = {}
    for name, periods in segments_for(game.league).items():
        h = sum(pts["home"].get(p, 0) for p in periods)
        a = sum(pts["away"].get(p, 0) for p in periods)
        if name in OVERTIME_SEGMENTS:
            h, a = h + ot_h, a + ot_a
        out[name] = (h + a, h - a)
    return out


# ------------------------------------------------------------------------------------------------ the state

@dataclass(frozen=True)
class ReplayState:
    elapsed: float  # regulation seconds elapsed at the snapshot
    period: int  # the period being played (a period boundary is the START of the next one)
    clock_left: float  # seconds left in `period`
    home_period_pts: tuple[int, ...]  # per period 1..period, the current one partial
    away_period_pts: tuple[int, ...]
    n_events: int  # game.events[:n_events] are known at the snapshot
    counts: Mapping[str, Mapping[str, int]]  # side -> fga, fg3a, fgm, fg3m, fta, ftm, tov, oreb
    team_fouls: Mapping[str, int]  # fouls in the current foul bucket (production `_team_fouls`)
    possession: Optional[str]  # production `_possession_after`; None at a period boundary or when the log is silent
    possession_basis: str = ""

    @property
    def home_score(self) -> int:
        return int(sum(self.home_period_pts))

    @property
    def away_score(self) -> int:
        return int(sum(self.away_period_pts))

    @property
    def total(self) -> int:
        return self.home_score + self.away_score

    @property
    def margin(self) -> int:
        return self.home_score - self.away_score


def snapshot_times(league: str, step: int = STEP_SECONDS) -> list[float]:
    """Every `step` seconds strictly inside regulation (tip and the final horn have nothing to project)."""
    reg = int(pbp.rules_for(league).regulation_seconds())
    return [float(t) for t in range(int(step), reg, int(step))]


def checkpoint_times(league: str) -> dict[str, float]:
    """{label: regulation seconds}: the TIP ('0m', the pregame number -- the old NBA app's pregame quarter bar is
    quoted there) and the bar's four in-game points. Labels are elapsed minutes ('10m', '45.6m')."""
    reg = float(pbp.rules_for(league).regulation_seconds())
    out: dict[str, float] = {"0m": 0.0}
    for f in CHECKPOINT_FRACTIONS:
        sec = round(f * reg, 1)
        out[f"{sec / 60.0:g}m"] = sec
    return out


def bucket_of(league: str, elapsed: float) -> float:
    """The 5%-of-regulation bin an elapsed time falls in (the old app's 2-minute bins on a 40-minute game)."""
    reg = float(pbp.rules_for(league).regulation_seconds())
    return round(math.floor((float(elapsed) / reg) / BUCKET_FRACTION + 1e-9) * BUCKET_FRACTION, 4)


def _prefix_len(events: Sequence[pbp.PbpEvent], elapsed: float) -> int:
    """Events known at `elapsed`: the log in ESPN's order up to the first play logged after that clock."""
    for i, ev in enumerate(events):
        if float(ev.elapsed) > float(elapsed) + 1e-9:
            return i
    return len(events)


def _counts(events: Sequence[pbp.PbpEvent]) -> dict[str, dict[str, int]]:
    out = {side: {"fga": 0, "fg3a": 0, "fgm": 0, "fg3m": 0, "fta": 0, "ftm": 0, "tov": 0, "oreb": 0}
           for side in ("home", "away")}
    for ev in events:
        c = out.get(ev.side)
        if c is None:
            continue
        if ev.kind == "shot":
            c["fga"] += 1
            three = int(ev.points_attempted or 0) == 3
            c["fg3a"] += int(three)
            if ev.made:
                c["fgm"] += 1
                c["fg3m"] += int(three)
        elif ev.kind == "free_throw":
            c["fta"] += 1
            c["ftm"] += int(bool(ev.made))
        elif ev.kind == "turnover":
            c["tov"] += 1
        elif ev.kind == "rebound_off":
            c["oreb"] += 1
    return out


def possessions(counts: Mapping[str, int], league: str) -> float:
    """Team possessions, the live state's estimator: FGA + TOV + c*FTA - OREB (`basketball_live_state._possessions`)."""
    coef = float(pbp.rules_for(league).possession_fta_coef)
    return float(counts["fga"] + counts["tov"]) + coef * float(counts["fta"]) - float(counts["oreb"])


def state_at(game: ReplayGame, elapsed: float) -> ReplayState:
    """The state the live path would have built from the log at regulation clock `elapsed`."""
    from syndicate.features.shared.basketball_live_state import _possession_after, _team_fouls

    rules = game.rules
    reg = int(rules.regulation_seconds())
    plen = float(rules.period_sec)
    elapsed = max(0.0, min(float(elapsed), float(reg)))
    period = min(int(elapsed // plen) + 1, int(rules.regulation_periods))
    clock_left = period * plen - elapsed
    if clock_left < 0:  # elapsed == regulation: the final horn of the last regulation period
        clock_left = 0.0
    k = _prefix_len(game.events, elapsed)
    known = game.events[:k]
    pts = points_by_period(known)
    hp = tuple(int(pts["home"].get(p, 0)) for p in range(1, period + 1))
    ap = tuple(int(pts["away"].get(p, 0)) for p in range(1, period + 1))
    at_start = abs(clock_left - plen) < 1e-9
    if at_start:
        possession, basis = None, "period_start"
    else:
        possession, basis = _possession_after(known, game.meta)
    fouls = {side: int(_team_fouls(known, rules, side, period)[0]) for side in ("home", "away")}
    return ReplayState(elapsed=elapsed, period=period, clock_left=clock_left, home_period_pts=hp, away_period_pts=ap,
                       n_events=k, counts=_counts(known), team_fouls=fouls, possession=possession, possession_basis=basis)


def segment_progress(game: ReplayGame, state: ReplayState, segment: str) -> tuple[int, int, float, bool]:
    """(points so far in `segment`, margin so far, REGULATION seconds left in it, over?). A segment that settles with
    overtime is never over while regulation is being played."""
    periods = segments_for(game.league)[segment]
    plen = float(game.rules.period_sec)
    so_far_h = sum(state.home_period_pts[p - 1] for p in periods if p <= state.period)
    so_far_a = sum(state.away_period_pts[p - 1] for p in periods if p <= state.period)
    left = 0.0
    for p in periods:
        if p > state.period:
            left += plen
        elif p == state.period:
            left += state.clock_left
    over = segment not in OVERTIME_SEGMENTS and left <= 0.0
    return so_far_h + so_far_a, so_far_h - so_far_a, left, over


def live_segments(game: ReplayGame, state: ReplayState) -> list[str]:
    return [s for s in segments_for(game.league) if not segment_progress(game, state, s)[3]]


# ------------------------------------------------------------------------------------------------ projectors

class Projector:
    """One named projection family. `emits` names every variant `project` returns (a re-sim emits a raw and an
    anchored margin from ONE set of draws). `every_step=False` marks an expensive projector run only at the
    checkpoints (`replay_game(sim_times=...)`)."""

    name: str = ""
    every_step: bool = True

    @property
    def emits(self) -> tuple[str, ...]:
        return (self.name,)

    def supports(self, game: ReplayGame) -> Optional[Refusal]:
        return None

    def prepare(self, game: ReplayGame) -> Any:
        return None

    def project(self, game: ReplayGame, state: ReplayState, prepared: Any) -> Mapping[str, Projection] | Refusal:
        raise NotImplementedError


def _rate_projection(game: ReplayGame, state: ReplayState, total_rate: float, margin_rate: float) -> dict[str, tuple[float, float]]:
    """segment -> so far + rate x regulation seconds left in it, for every live segment."""
    out = {}
    for seg in live_segments(game, state):
        tot, mar, left, _over = segment_progress(game, state, seg)
        out[seg] = (tot + total_rate * left, mar + margin_rate * left)
    return out


class NaivePace(Projector):
    """The old NCAAB app's `proj_pace`: this game's points per second so far x the time left."""

    name = "naive_pace"

    def project(self, game, state, prepared):
        if state.elapsed <= 0:
            return Refusal("no_elapsed")
        return {self.name: _rate_projection(game, state, state.total / state.elapsed, state.margin / state.elapsed)}


class IntervalModule(Projector):
    """`basketball_interval_projection.project_interval` (the shipped naive module) for the current period; its
    pace x ppp for the periods after it. Margin is carried: the module projects none."""

    name = "interval_projection"

    def prepare(self, game):
        # The module's two inputs, built once per game from the log: cumulative possessions (both teams) and
        # signed scoring rows, keyed by elapsed game seconds.
        pressure, scoring = [], []
        counts = {"home": {"fga": 0, "fta": 0, "tov": 0, "oreb": 0}, "away": {"fga": 0, "fta": 0, "tov": 0, "oreb": 0}}
        for ev in game.events:
            c = counts.get(ev.side)
            if c is not None:
                key = {"shot": "fga", "free_throw": "fta", "turnover": "tov", "rebound_off": "oreb"}.get(ev.kind)
                if key:
                    c[key] += 1
            poss = possessions(counts["home"], game.league) + possessions(counts["away"], game.league)
            pressure.append({"clock_seconds": float(ev.elapsed), "possession_index": max(0.0, poss)})
            if ev.points and ev.side in ("home", "away"):
                scoring.append({"clock_seconds": float(ev.elapsed), "sign": 1.0 if ev.side == "home" else -1.0,
                                "weight": float(ev.points)})
        return {"pressure": pressure, "scoring": scoring}

    def project(self, game, state, prepared):
        from syndicate.features.shared.basketball_interval_projection import project_interval

        k = state.n_events
        pressure = prepared["pressure"][:k]
        scoring = [r for r in prepared["scoring"] if r["clock_seconds"] <= state.elapsed]
        row = project_interval(pressure, scoring, state.elapsed, league_code=game.league)
        if row is None:
            return Refusal("interval_module_no_projection")
        rate = float(row["state_pace_per_min"]) * float(row["state_points_per_possession"]) / 60.0
        # The module's own number for the rest of the CURRENT period; the same rate after it.
        rest_now = float(row["proj_rest_total"])
        out = {}
        for seg in live_segments(game, state):
            tot, mar, left, _over = segment_progress(game, state, seg)
            periods = segments_for(game.league)[seg]
            in_now = state.period in periods
            later = left - (state.clock_left if in_now else 0.0)
            out[seg] = (tot + (rest_now if in_now else 0.0) + rate * later, float(mar))
        return {self.name: out}


class LeagueRate(Projector):
    """A walk-forward league scoring rate (points per regulation second, games dated before this one) x time left.
    Margin carried. The loader puts the rate in `extra['league_points_per_second']`."""

    name = "league_rate"

    def supports(self, game):
        if not game.extra.get("league_points_per_second"):
            return Refusal("no_league_rate")
        return None

    def project(self, game, state, prepared):
        return {self.name: _rate_projection(game, state, float(game.extra["league_points_per_second"]), 0.0)}


class PregameRate(Projector):
    """The pregame line spread over regulation: segment so far + line x share of regulation left in it."""

    name = "pregame_rate"

    def supports(self, game):
        if game.pregame_total is None or game.pregame_home_margin is None:
            return Refusal("no_pregame_line")
        return None

    def project(self, game, state, prepared):
        reg = float(game.regulation_seconds)
        return {self.name: _rate_projection(game, state, float(game.pregame_total) / reg,
                                            float(game.pregame_home_margin) / reg)}


class PooledRate(Projector):
    """PHASE 2 HOOK -- observed scoring rate POOLED toward the pregame line (#535: raw game pace made projections
    worse, so a game-to-date rate only enters shrunk). rate = (k*line_rate + elapsed*game_rate) / (k + elapsed),
    k in seconds of prior weight. k=0 is `naive_pace`; k -> infinity is `pregame_rate`."""

    def __init__(self, k_seconds: float = 1200.0, *, name: str = ""):
        self.k = float(k_seconds)
        self.name = name or f"pooled_rate_k{int(round(self.k))}"

    def supports(self, game):
        if game.pregame_total is None or game.pregame_home_margin is None:
            return Refusal("no_pregame_line")
        return None

    def project(self, game, state, prepared):
        reg = float(game.regulation_seconds)
        w = self.k + state.elapsed
        if w <= 0:
            return Refusal("no_weight")
        tr = (self.k * float(game.pregame_total) / reg + float(state.total)) / w
        mr = (self.k * float(game.pregame_home_margin) / reg + float(state.margin)) / w
        return {self.name: _rate_projection(game, state, tr, mr)}


class _PossessionPooled(Projector):
    """Shared arithmetic for the pace / efficiency split. Prior pace = `extra['prior_possessions']` (BOTH teams, per
    regulation game); prior points per possession = pregame total / prior possessions. Observed: the live state's
    possession estimator on the log so far. Margin rides on the pregame line's share (`pregame_rate`)."""

    pool_pace = False
    pool_eff = False

    def __init__(self, k_possessions: float = 60.0, *, name: str = ""):
        self.k = float(k_possessions)
        self.name = name or self.default_name()

    def default_name(self) -> str:
        raise NotImplementedError

    def supports(self, game):
        if game.pregame_total is None or game.pregame_home_margin is None:
            return Refusal("no_pregame_line")
        if not game.extra.get("prior_possessions"):
            return Refusal("no_prior_possessions")
        return None

    def project(self, game, state, prepared):
        reg = float(game.regulation_seconds)
        prior_poss = float(game.extra["prior_possessions"])
        prior_pace = prior_poss / reg  # possessions (both teams) per second
        prior_ppp = float(game.pregame_total) / prior_poss
        obs_poss = possessions(state.counts["home"], game.league) + possessions(state.counts["away"], game.league)
        pace = prior_pace
        if self.pool_pace and state.elapsed > 0:
            k_sec = self.k / prior_pace  # k possessions of prior, expressed as seconds at the prior pace
            pace = (k_sec * prior_pace + obs_poss) / (k_sec + state.elapsed)
        ppp = prior_ppp
        if self.pool_eff and obs_poss > 0:
            ppp = (self.k * prior_ppp + float(state.total)) / (self.k + obs_poss)
        return {self.name: _rate_projection(game, state, pace * ppp, float(game.pregame_home_margin) / reg)}


class PooledPace(_PossessionPooled):
    """PHASE 2 HOOK -- observed POSSESSIONS pooled toward the prior pace; points per possession from the line."""

    pool_pace = True

    def default_name(self):
        return f"pooled_pace_k{int(round(self.k))}"


class PooledEfficiency(_PossessionPooled):
    """PHASE 2 HOOK -- observed POINTS PER POSSESSION (shooting) pooled toward the line's; pace from the prior."""

    pool_eff = True

    def default_name(self):
        return f"pooled_efficiency_k{int(round(self.k))}"


# ------------------------------------------------------------------------------------------------ re-sims

def resume_game_state(game: ReplayGame, state: ReplayState, names: Mapping[str, str], *, with_floor: bool = True):
    """The engine `GameState` the live path would resume from, keyed by the engine frames' `player_name`.

    At a period boundary the engine starts the next period from its tip (the live path's rule): no clock, no five,
    no possession. A five that does not map to 5 distinct frame names is left empty, so the engine samples the
    lineup (`nba/live_resim.map_state_names`' rule). Returns (GameState, report)."""
    from syndicate.features.basketball_engine.resume import GameState

    plen = float(game.rules.period_sec)
    report: dict[str, Any] = {}
    at_start = abs(state.clock_left - plen) < 1e-9
    if at_start:
        return GameState(period=state.period, seconds_remaining=None, home_period_pts=state.home_period_pts,
                         away_period_pts=state.away_period_pts), {"boundary": True}
    fives: dict[str, tuple[str, ...]] = {"home": (), "away": ()}
    if with_floor:
        rec = pbp.reconstruct_from_events(game.meta, game.events[: state.n_events])
        for side in ("home", "away"):
            mapped = [names.get(pid) for pid in (rec.on_floor.get(side) or [])]
            ok = len(mapped) == 5 and all(mapped) and len(set(mapped)) == 5
            fives[side] = tuple(mapped) if ok else ()  # type: ignore[arg-type]
            report[f"{side}_on_floor_mapped"] = ok
    pf = pbp.personal_fouls(game.events[: state.n_events], game.league)
    fouls = {"home": {}, "away": {}}
    for pid, n in pf.items():
        box = game.meta.box.get(pid)
        nm = names.get(pid)
        if box is not None and nm:
            fouls[box.side][nm] = int(n)
    gs = GameState(
        period=state.period, seconds_remaining=int(round(state.clock_left)), home_period_pts=state.home_period_pts,
        away_period_pts=state.away_period_pts, possession=state.possession,
        home_on_floor=fives["home"], away_on_floor=fives["away"],
        home_player_fouls=fouls["home"], away_player_fouls=fouls["away"],
        home_team_fouls=int(state.team_fouls["home"]), away_team_fouls=int(state.team_fouls["away"]),
    )
    return gs, report


def _segment_means(result: Mapping[str, Any], game: ReplayGame, state: ReplayState) -> dict[str, tuple[float, float]]:
    """Full game + every live segment from a re-sim result (`total_mean`, mean of `margin_dist`)."""
    out: dict[str, tuple[float, float]] = {}
    live = set(live_segments(game, state))
    if "full" in live:
        out["full"] = (float(result["total_mean"]), float(result["home_margin_mean"]))
    for seg, block in (result.get("segments") or {}).items():
        if seg not in live or not isinstance(block, Mapping):
            continue
        dist = block.get("margin_dist") or {}
        n = sum(int(c) for c in dist.values())
        if n <= 0:
            continue
        mean_margin = sum(int(m) * int(c) for m, c in dist.items()) / n
        out[seg] = (float(block["total_mean"]), float(mean_margin))
    return out


class Resim(Projector):
    """Today's live re-sim resumed from the replay state.

    College (`ncaab`/`wncaab`): `ncaab/live_resim.build_engine_inputs` on the walk-forward priors the loader put in
    `extra['college_resim']` (team prior + player priors, as of the day before), then `resim_live_game`. Emits
    `resim` (raw) and `resim_anchored` (production's market anchor, `anchor_result`, scaled by the share of
    regulation left, against the pregame CLOSE and this game's own tip sim).
    NBA/WNBA: `nba/live_resim.load_engine_inputs` (the inputs production persisted at pregame), names mapped with
    `map_state_names`, then `resim_live_game`. NBA's live margins are not anchored, so it emits `resim` only.

    `mechanisms` (EventSimConfig fields) sets the default-off live mechanisms on the cfg -- the same fields
    SYNDICATE_NCAAB_LIVE_MECHANISMS / SYNDICATE_NBA_LIVE_MECHANISMS set -- and renames the variant. `simulate` is
    the engine call (tests pass a stub); None runs the real engine."""

    every_step = False

    def __init__(self, sims: int = 100, *, mechanisms: Optional[Mapping[str, Any]] = None, name: str = "",
                 simulate: Optional[Callable[..., Any]] = None, with_floor: bool = True):
        self.sims = int(sims)
        self.mechanisms = dict(mechanisms or {})
        self.name = name or ("resim" if not self.mechanisms else "resim_mech")
        self.simulate = simulate
        self.with_floor = with_floor

    @property
    def emits(self):
        return (self.name, f"{self.name}_anchored")

    def supports(self, game):
        if game.league in ("ncaab", "wncaab"):
            return None if game.extra.get("college_resim") else Refusal("no_walk_forward_inputs")
        if game.league in ("nba", "wnba"):
            return None if game.extra.get("engine_inputs_root") else Refusal("no_engine_inputs_root")
        return Refusal("league_not_supported", game.league)

    def _college_inputs(self, game):
        import datetime as dt

        from syndicate.features.ncaab import live_resim as lr
        from syndicate.features.ncaab import live_team_model as tm

        task = game.extra["college_resim"]
        prior_kw = dict(task["prior"])
        prior_kw["ratings_as_of"] = dt.date.fromisoformat(str(prior_kw["ratings_as_of"]))
        prior = tm.NcaabGamePrior(**prior_kw)
        priors = lr.PlayerPriors(season=int(task["season"]), as_of=dt.date.fromisoformat(game.date),
                                 source="walk_forward", by_team=task["player_priors"])
        inputs = lr.build_engine_inputs(game.date, game.meta.home.team_id, game.meta.away.team_id,
                                        neutral=bool(task.get("neutral")), priors=priors, team_prior=prior,
                                        league=game.league)
        if isinstance(inputs, lr.NcaabResimRefusal):
            return Refusal(inputs.reason, inputs.detail)
        if self.mechanisms:
            inputs = {**inputs, "cfg": dataclasses.replace(inputs["cfg"], **_tupled(self.mechanisms))}
        names: dict[str, str] = {}
        for frame in (inputs["home_players"], inputs["away_players"]):
            names.update({str(k): str(v) for k, v in zip(frame["athlete_id"], frame["player_name"])})
        return {"inputs": inputs, "names": names}

    def _nba_inputs(self, game):
        from syndicate.features.nba import live_resim as lr

        inputs = lr.load_engine_inputs(game.date, game.meta.home.code, game.meta.away.code,
                                       root=game.extra["engine_inputs_root"], league=game.league)
        if isinstance(inputs, lr.NbaResimRefusal):
            return Refusal(inputs.reason, inputs.detail)
        if self.mechanisms:
            inputs = lr.with_live_mechanisms(inputs, self.mechanisms)
        return {"inputs": inputs, "names": {pid: p.name for pid, p in game.meta.box.items()}}

    def prepare(self, game):
        prep = self._college_inputs(game) if game.league in ("ncaab", "wncaab") else self._nba_inputs(game)
        if isinstance(prep, Refusal):
            return prep
        if game.league not in ("ncaab", "wncaab") or game.pregame_home_margin is None:
            return prep  # nothing to anchor: no tip sim needed
        # The tip sim: the pregame number the anchor compares the close against (the live path's `pregame_sim`).
        from syndicate.features.basketball_engine.resume import GameState

        tip = self._run(game, prep, GameState(), seed_key=0)
        if isinstance(tip, Refusal):
            return tip
        prep["tip"] = {"total_mean": tip["total_mean"], "home_margin_mean": tip["home_margin_mean"]}
        prep["tip_result"] = tip  # the same seed as a t=0 projection: reused there, not re-run
        return prep

    def _run(self, game, prep, gs, *, seed_key: int):
        if game.league in ("ncaab", "wncaab"):
            from syndicate.features.ncaab import live_resim as lr

            res = lr.resim_live_game(prep["inputs"], gs, sims=self.sims, base_seed=lr.stable_seed(game.game_id, seed_key, game.league),
                                     simulate=self.simulate, league=game.league)
            if isinstance(res, lr.NcaabResimRefusal):
                return Refusal(res.reason, res.detail)
            return res
        from syndicate.features.nba import live_resim as lr

        res = lr.resim_live_game(prep["inputs"], gs, sims=self.sims, base_seed=lr.stable_seed(game.game_id, seed_key),
                                 simulate=self.simulate, league=game.league)
        if isinstance(res, lr.NbaResimRefusal):
            return Refusal(res.reason, res.detail)
        return res

    def project(self, game, state, prepared):
        gs, report = resume_game_state(game, state, prepared["names"], with_floor=self.with_floor)
        if game.league in ("nba", "wnba") and not report.get("boundary"):
            from syndicate.features.nba import live_resim as lr

            gs, rep = lr.map_state_names(gs, prepared["inputs"]["home_players"], prepared["inputs"]["away_players"])
            report.update(rep)
        if state.elapsed <= 0 and "tip_result" in prepared:
            res = prepared["tip_result"]
        else:
            res = self._run(game, prepared, gs, seed_key=int(round(state.elapsed)))
        if isinstance(res, Refusal):
            return res
        out = {self.name: _segment_means(res, game, state)}
        if game.league in ("ncaab", "wncaab") and game.pregame_home_margin is not None:
            from syndicate.features.ncaab import live_resim as lr

            anchor = lr.MarginAnchor(market_home_margin=float(game.pregame_home_margin),
                                     sim_home_margin=float(prepared["tip"]["home_margin_mean"]), books=1)
            remaining = (float(game.regulation_seconds) - state.elapsed) / float(game.regulation_seconds)
            anchored = lr.anchor_result(res, anchor, remaining_fraction=remaining)
            out[f"{self.name}_anchored"] = _segment_means(anchored, game, state)
        return out


def _tupled(values: Mapping[str, Any]) -> dict[str, Any]:
    return {k: tuple(v) if isinstance(v, list) else v for k, v in values.items()}


class NbaTick(Projector):
    """The ported NBA tick's scope projection (`tick._scope_projection`): actual so far + (ladder at the scope's end
    - ladder now), never below the actual, the ladder being the pregame smart sim's 3-minute cumulative p50
    (`smart_sim_<date>_<H>_<A>.json` `intervals`), read through the tick's own `_live_interp_cum_p50`. Totals only;
    the tick's recent-window pace / efficiency adjustments are not replayed (they need its live tuning file)."""

    name = "nba_tick"

    def __init__(self, interp: Optional[Callable[..., Any]] = None):
        self.interp = interp

    def supports(self, game):
        if game.league != "nba":
            return Refusal("league_not_supported", game.league)
        if not game.extra.get("tick_intervals"):
            return Refusal("no_smart_sim_intervals")
        return None

    def prepare(self, game):
        if self.interp is not None:
            return {"interp": self.interp}
        from syndicate.features.nba.live_tick.tick import _live_interp_cum_p50

        return {"interp": _live_interp_cum_p50}

    def project(self, game, state, prepared):
        interp = prepared["interp"]
        ladder = game.extra["tick_intervals"]
        plen_min = float(game.rules.period_sec) / 60.0
        elapsed_min = state.elapsed / 60.0
        out = {}
        for seg in live_segments(game, state):
            periods = segments_for(game.league)[seg]
            start_min, end_min = (periods[0] - 1) * plen_min, periods[-1] * plen_min
            actual, _mar, _left, _over = segment_progress(game, state, seg)
            elapsed_scope = max(0.0, min(end_min - start_min, elapsed_min - start_min))
            total_minutes = int(round(end_min))
            sim_start = interp(ladder, elapsed_min=start_min, total_minutes=total_minutes) or 0.0
            sim_at = interp(ladder, elapsed_min=start_min + elapsed_scope, total_minutes=total_minutes)
            sim_end = interp(ladder, elapsed_min=end_min, total_minutes=total_minutes)
            if sim_at is None or sim_end is None:
                continue
            proj = max(float(actual), float(actual) + (float(sim_end) - float(sim_start)) - (float(sim_at) - float(sim_start)))
            out[seg] = (proj, None)
        if not out:
            return Refusal("ladder_unreadable")
        return {self.name: out}


DEFAULT_PROJECTORS: tuple[Callable[[], Projector], ...] = (
    NaivePace, IntervalModule, LeagueRate, PregameRate, lambda: PooledRate(1200.0), lambda: PooledPace(60.0),
    lambda: PooledEfficiency(60.0),
)


# ------------------------------------------------------------------------------------------------ replay + score

def replay_game(game: ReplayGame, projectors: Sequence[Projector], *, step: int = STEP_SECONDS,
                sim_times: Optional[Iterable[float]] = None) -> dict[str, Any]:
    """Every snapshot x projector for one game -> {'rows': [...], 'refusals': {variant: reason}, ...}.

    Rows carry the projection AND the actual so the scorer needs nothing else. `sim_times` are the snapshots an
    expensive projector (`every_step=False`) runs at; default the four checkpoints."""
    actual = segment_actuals(game)
    out: dict[str, Any] = {"league": game.league, "game_id": game.game_id, "date": game.date, "phase": game.phase,
                           "rows": [], "refusals": {}, "prepare_refusals": {}}
    if isinstance(actual, Refusal):
        out["game_refusal"] = actual.reason
        out["detail"] = actual.detail
        return out
    checkpoints = checkpoint_times(game.league)
    labels = {round(v, 1): k for k, v in checkpoints.items()}
    times = sorted(set(snapshot_times(game.league, step)) | set(checkpoints.values()))
    sim_set = {round(float(t), 1) for t in (sim_times if sim_times is not None else checkpoints.values())}
    active: list[tuple[Projector, Any]] = []
    for proj in projectors:
        refusal = proj.supports(game)
        if refusal is None:
            prepared = proj.prepare(game)
            refusal = prepared if isinstance(prepared, Refusal) else None
        if refusal is not None:
            for name in proj.emits:
                out["prepare_refusals"][name] = refusal.reason
            continue
        active.append((proj, prepared))
    reg = float(game.regulation_seconds)
    refusals: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for t in times:
        runners = [(p, prep) for p, prep in active if p.every_step or round(t, 1) in sim_set]
        if not runners:
            continue
        state = state_at(game, t)
        for proj, prep in runners:
            res = proj.project(game, state, prep)
            if isinstance(res, Refusal):
                for name in proj.emits:
                    refusals[name][res.reason] += 1
                continue
            for variant, projection in res.items():
                for seg, (tot, mar) in projection.items():
                    a_tot, a_mar = actual[seg]
                    out["rows"].append({
                        "projector": variant, "segment": seg, "elapsed": t, "frac": round(t / reg, 4),
                        "bucket": bucket_of(game.league, t), "checkpoint": labels.get(round(t, 1), ""),
                        "total": None if tot is None else round(float(tot), 3),
                        "margin": None if mar is None else round(float(mar), 3),
                        "actual_total": a_tot, "actual_margin": a_mar,
                    })
    out["refusals"] = {k: dict(v) for k, v in refusals.items()}
    return out


def compact(result: Mapping[str, Any]) -> dict[str, Any]:
    """A replay result small enough to keep for thousands of games: the CHECKPOINT rows in full (the ship gate pairs
    on them) and, for every 30 s snapshot, per (projector, segment, 5% bucket) error sums
    `[n_total, sum_err, sum_abs_err, n_margin, sum_err, sum_abs_err]` (the error curve)."""
    out = {k: v for k, v in result.items() if k != "rows"}
    rows = result.get("rows") or ()
    out["cp_rows"] = [r for r in rows if r.get("checkpoint")]
    out["buckets"] = {f"{p}|{s}|{k}": v for (p, s, k), v in _bucket_sums(rows).items()}
    return out


def _bucket_sums(rows: Iterable[Mapping[str, Any]]) -> dict[tuple[str, str, str], list[float]]:
    sums: dict[tuple[str, str, str], list[float]] = {}
    for r in rows:
        cell = sums.setdefault((r["projector"], r["segment"], str(r["bucket"])), [0, 0.0, 0.0, 0, 0.0, 0.0])
        if r["total"] is not None:
            e = float(r["total"]) - float(r["actual_total"])
            cell[0] += 1
            cell[1] += e
            cell[2] += abs(e)
        if r["margin"] is not None:
            e = float(r["margin"]) - float(r["actual_margin"])
            cell[3] += 1
            cell[4] += e
            cell[5] += abs(e)
    return sums


def _game_cells(res: Mapping[str, Any], by: str) -> dict[tuple[str, str, str], list[float]]:
    """One game's error sums per (projector, segment, key): `key` is the checkpoint label or the 5% bucket."""
    if by == "checkpoint":
        rows = res["cp_rows"] if "cp_rows" in res else [r for r in res.get("rows") or () if r.get("checkpoint")]
        return _checkpoint_sums(rows)
    if "buckets" in res:
        out = {}
        for key, v in (res.get("buckets") or {}).items():
            p, s, k = key.split("|")
            out[(p, s, k)] = v
        return out
    return _bucket_sums(res.get("rows") or ())


def _checkpoint_sums(rows: Iterable[Mapping[str, Any]]) -> dict[tuple[str, str, str], list[float]]:
    relabelled = [{**r, "bucket": r["checkpoint"]} for r in rows]
    return _bucket_sums(relabelled)


def _stat(n: float, s: float, a: float) -> dict[str, Any]:
    if not n:
        return {"n": 0}
    return {"n": int(n), "mae": round(a / n, 3), "bias": round(s / n, 3)}


def summarize(results: Iterable[Mapping[str, Any]], *, by: str = "checkpoint") -> dict[str, Any]:
    """league -> phase -> projector -> segment -> key -> {games, total{n,mae,bias}, margin{...}}.

    `by="checkpoint"` keys on the four bar points ('10m'...), `by="bucket"` on the 5%-of-regulation bins over
    every snapshot. A segment already over at a snapshot was never asked for, so it is never scored. Errors are
    projection minus actual: a positive bias is a projection that runs HIGH."""
    acc: dict[tuple, list[float]] = {}
    for res in results:
        for (p, s, k), v in _game_cells(res, by).items():
            cell = acc.setdefault((res["league"], res["phase"], p, s, k), [0, 0, 0.0, 0.0, 0, 0.0, 0.0])
            cell[0] += 1
            for i in range(6):
                cell[1 + i] += v[i]
    out: dict[str, Any] = {}
    for (lg, ph, pj, seg, key), c in sorted(acc.items(), key=lambda kv: tuple(str(x) for x in kv[0])):
        out.setdefault(lg, {}).setdefault(ph, {}).setdefault(pj, {}).setdefault(seg, {})[str(key)] = {
            "games": int(c[0]), "total": _stat(c[1], c[2], c[3]), "margin": _stat(c[4], c[5], c[6])}
    return out


def paired_delta(results: Iterable[Mapping[str, Any]], candidate: str, baseline: str, *, quantity: str = "total",
                 by: str = "checkpoint") -> dict[str, Any]:
    """THE SHIP GATE. Candidate vs baseline on the SAME games and cells only: the mean |error| difference
    (candidate - baseline; NEGATIVE = candidate better) with a GAME-CLUSTERED standard error -- snapshots inside one
    game are not independent, so each game contributes its own mean |error| per projector and the SE is taken over
    games. At a checkpoint each game holds exactly one snapshot, so this is snapshot-paired.
    league -> phase -> segment -> key -> {games, mae_candidate, mae_baseline, delta, se, verdict}; `verdict` is
    'better' / 'worse' only when |delta| > 1.96 se, else 'n.s.'."""
    n_i, a_i = (0, 2) if quantity == "total" else (3, 5)
    per: dict[tuple, list[tuple[float, float]]] = defaultdict(list)
    for res in results:
        cells = _game_cells(res, by)
        keys = {(s, k) for (p, s, k) in cells if p == candidate} & {(s, k) for (p, s, k) in cells if p == baseline}
        for s, k in keys:
            c, b = cells[(candidate, s, k)], cells[(baseline, s, k)]
            if c[n_i] and b[n_i]:
                per[(res["league"], res["phase"], s, k)].append((c[a_i] / c[n_i], b[a_i] / b[n_i]))
    out: dict[str, Any] = {}
    for (lg, ph, seg, key), pairs in sorted(per.items(), key=lambda kv: tuple(str(x) for x in kv[0])):
        diffs = [c - b for c, b in pairs]
        delta = statistics.fmean(diffs)
        se = (statistics.stdev(diffs) / math.sqrt(len(diffs))) if len(diffs) > 1 else float("nan")
        verdict = "n.s."
        if se == se and abs(delta) > 1.96 * se:
            verdict = "better" if delta < 0 else "worse"
        out.setdefault(lg, {}).setdefault(ph, {}).setdefault(seg, {})[str(key)] = {
            "games": len(pairs), "mae_candidate": round(statistics.fmean(c for c, _ in pairs), 3),
            "mae_baseline": round(statistics.fmean(b for _, b in pairs), 3), "delta": round(delta, 3),
            "se": None if se != se else round(se, 3), "verdict": verdict}
    return out
