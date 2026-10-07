"""Attribute the game sim's plays to players, so props inherit game script.

Lane `football-sim-player-attribution` (design pre-registered in
`.syndicate/findings_2026-10-07_football_player_attribution.md`).

READ-ONLY OVER THE ENGINE. `AttributionAccumulator.add(output)` duck-types the
`segment_accumulator` seam `build_projection` already calls once per seed, reads
that seed's `possession_log`, and draws with its OWN rng (seeded from the game
seed). The engine's rng stream, its scores and every game-line number are
untouched; switching attribution on cannot move a line.

Per offensive play: incomplete / sack -> pass; turnover -> interception or a
lost fumble at measured rates; a play that gained yards -> pass or run by the
measured P(pass | down, to-go, score diff, time, yards). Passes go to the team's
primary QB; receptions to a receiver drawn by reception share weighted by how
well that receiver's yards-per-catch explains the play's yards; runs to a rusher
by carry share weighted the same way by yards-per-carry.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from random import Random
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

STATS = ("pass_att", "completions", "pass_yds", "pass_td", "interceptions",
         "rush_att", "rush_yds", "receptions", "rec_yds", "anytime_td")

LEAGUE_YPR = 11.0
LEAGUE_YPC = 4.3


# ---------------------------------------------------------------------------
# buckets (pre-registered)
# ---------------------------------------------------------------------------

def togo_bucket(distance: int) -> str:
    return "1-3" if distance <= 3 else ("4-7" if distance <= 7 else "8+")


def diff_bucket(score_diff: int) -> str:
    return "trail9" if score_diff <= -9 else ("lead9" if score_diff >= 9 else "close")


def time_bucket(quarter: int, clock: int) -> str:
    if quarter < 4:
        return "q1-3"
    return "q4late" if clock <= 300 else "q4"


def yards_bucket(yards: int) -> str:
    return "neg" if yards < 0 else ("0-5" if yards <= 5 else ("6-15" if yards <= 15 else "16+"))


def pass_rate_key(*, down: int, distance: int, score_diff: int, quarter: int, clock: int, yards: int) -> Tuple:
    return (int(down), togo_bucket(distance), diff_bucket(score_diff), time_bucket(quarter, clock), yards_bucket(yards))


# ---------------------------------------------------------------------------
# inputs
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AttributionTables:
    pass_rate: Mapping[str, float]
    pass_rate_pooled: Mapping[str, float]
    p_int_given_turnover: float
    p_pass_given_fumble: float
    # Amendment A2: real yards per (comp|run, down, to-go bucket, neg|nonneg) as 101 quantiles
    yards_quantiles: Mapping[str, Sequence[int]] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> "AttributionTables":
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(pass_rate={k: float(v["p"]) for k, v in d["pass_rate"].items()},
                   pass_rate_pooled={k: float(v["p"]) for k, v in d["pass_rate_pooled"].items()},
                   p_int_given_turnover=float(d["p_int_given_turnover"]),
                   p_pass_given_fumble=float(d["p_pass_given_fumble"]),
                   yards_quantiles={k: list(v["q"]) for k, v in (d.get("yards_quantiles") or {}).items()})

    def draw_yards(self, rng: Random, kind: str, down: int, distance: int, sim_yards: int, cap: int) -> int:
        """A2: real yards for this play type and situation, keeping the sim's sign; capped short of the goal."""
        sign = "neg" if sim_yards < 0 else "nonneg"
        q = self.yards_quantiles.get(f"{kind}|{int(down)}|{togo_bucket(distance)}|{sign}")
        if not q:
            return sim_yards
        y = int(q[min(100, int(rng.random() * 101))])
        return min(y, cap) if y >= 0 else y

    def p_pass(self, key: Tuple) -> float:
        k = "|".join(map(str, key))
        if k in self.pass_rate:
            return self.pass_rate[k]
        return self.pass_rate_pooled.get("|".join(map(str, key[:2])), 0.55)


@dataclass(frozen=True)
class PlayerUsage:
    player_id: str
    name: str
    carry_share: float = 0.0
    reception_share: float = 0.0
    incompletion_share: float = 0.0     # targets that were not caught
    ypr: float = LEAGUE_YPR
    ypc: float = LEAGUE_YPC


@dataclass(frozen=True)
class TeamUsage:
    team: str
    qb_id: Optional[str]
    qb_name: str
    players: Tuple[PlayerUsage, ...]


def _exp_weight(yards: int, mean: float) -> float:
    m = max(1.0, float(mean))
    return math.exp(-max(0, yards) / m) / m


def _draw(rng: Random, items: Sequence[Tuple[Any, float]]) -> Any:
    total = sum(w for _, w in items)
    if total <= 0:
        return None
    r = rng.random() * total
    acc = 0.0
    for item, w in items:
        acc += w
        if r <= acc:
            return item
    return items[-1][0]


# ---------------------------------------------------------------------------
# the accumulator
# ---------------------------------------------------------------------------

_ATTRIBUTED = {"gain", "explosive_gain", "touchdown", "incomplete_pass", "sack", "turnover", "turnover_on_downs"}


@dataclass
class AttributionAccumulator:
    """Per-seed player stat lines for one game. `results[pid][stat]` is a list, one value per seed."""

    home: TeamUsage
    away: TeamUsage
    tables: AttributionTables
    # NCAAF box scores count a sack as a QB rush (attempt + its negative yards); the NFL does not.
    sacks_are_rushing: bool = False
    # Amendment 2 (measured run-share correction). The engine yields too few yard-gaining plays, so
    # runs are starved: `pass_odds_multiplier` c scales the pass ODDS on gaining plays, and
    # `incomplete_as_run` r credits that share of 0-yard incompletions as stuffed 0-yard runs. Fitted per
    # sport to real team rush / pass attempts; the defaults (1.0, 0.0) consume no extra rng.
    pass_odds_multiplier: float = 1.0
    incomplete_as_run: float = 0.0
    results: Dict[str, Dict[str, List[float]]] = field(default_factory=dict)
    seeds: int = 0
    team_totals: Dict[str, Dict[str, List[float]]] = field(default_factory=dict)

    def add(self, output: Any) -> None:
        rng = Random(f"attribution|{output.seed}")
        line: Dict[str, Dict[str, float]] = {}
        team_line = {"home": {s: 0.0 for s in STATS}, "away": {s: 0.0 for s in STATS}}
        for step in output.possession_log:
            outcome = str(getattr(step["outcome"], "value", step["outcome"]))
            if outcome not in _ATTRIBUTED:
                continue
            st = step["start_state"]
            side = st["possession_owner"]
            usage = self.home if side == "home" else self.away
            yards = int(step.get("yards_gained") or 0)
            diff = (st["score_home"] - st["score_away"]) * (1 if side == "home" else -1)
            key = pass_rate_key(down=int(st["down"]), distance=int(st["distance"]), score_diff=diff,
                                quarter=int(st["quarter"]), clock=int(st["clock_remaining"]), yards=yards)
            touchdown = outcome == "touchdown"
            if outcome in ("incomplete_pass", "sack"):
                kind = "incomplete" if outcome == "incomplete_pass" else "sack"
                if kind == "incomplete" and self.incomplete_as_run > 0 and rng.random() < self.incomplete_as_run:
                    kind, yards = "run", 0                # a stuffed run, not an incompletion
            elif outcome == "turnover":
                if rng.random() < self.tables.p_int_given_turnover:
                    kind = "interception"
                else:
                    kind = "fumble_pass" if rng.random() < self.tables.p_pass_given_fumble else "fumble_run"
            else:
                p = self.tables.p_pass(key)
                if self.pass_odds_multiplier != 1.0 and 0.0 < p < 1.0:
                    odds = self.pass_odds_multiplier * p / (1.0 - p)
                    p = odds / (1.0 + odds)
                is_pass = rng.random() < p
                if outcome == "turnover_on_downs":
                    kind = "incomplete" if is_pass else "run"
                    yards = 0
                else:
                    kind = "completion" if is_pass else "run"
            if kind in ("completion", "run") and not touchdown and self.tables.yards_quantiles:
                yards = self.tables.draw_yards(rng, "comp" if kind == "completion" else "run", int(st["down"]),
                                               int(st["distance"]), yards, cap=max(0, 99 - int(st["field_position"])))
            self._credit(rng, line, team_line[side], usage, kind, yards, touchdown)
        for pid, stats in line.items():
            slot = self.results.setdefault(pid, {s: [0.0] * self.seeds for s in STATS})
            for s in STATS:
                slot[s].append(stats.get(s, 0.0))
        for pid, slot in self.results.items():       # players with no touch this seed record zeros
            if pid not in line:
                for s in STATS:
                    slot[s].append(0.0)
        for side in ("home", "away"):
            tt = self.team_totals.setdefault(side, {s: [] for s in STATS})
            for s in STATS:
                tt[s].append(team_line[side][s])
        self.seeds += 1

    def _credit(self, rng: Random, line: Dict[str, Dict[str, float]], team: Dict[str, float],
                usage: TeamUsage, kind: str, yards: int, touchdown: bool) -> None:
        def add(pid: Optional[str], stat: str, value: float = 1.0) -> None:
            team[stat] += value
            if pid:
                line.setdefault(pid, {})
                line[pid][stat] = line[pid].get(stat, 0.0) + value

        qb = usage.qb_id
        if kind == "sack":
            if self.sacks_are_rushing:               # NCAAF stat rule
                add(qb, "rush_att")
                add(qb, "rush_yds", yards)
            return                                   # NFL: a sack is neither passing nor rushing
        if kind in ("completion", "incomplete", "interception", "fumble_pass"):
            add(qb, "pass_att")
            if kind == "completion" or kind == "fumble_pass":
                rec = _draw(rng, [(p.player_id, p.reception_share * _exp_weight(yards, p.ypr))
                                  for p in usage.players if p.reception_share > 0])
                add(qb, "completions")
                add(qb, "pass_yds", yards)
                add(rec, "receptions")
                add(rec, "rec_yds", yards)
                if touchdown:
                    add(qb, "pass_td")
                    if rec:
                        line[rec]["anytime_td"] = 1.0       # anytime TD is a yes/no per game
            else:
                _ = _draw(rng, [(p.player_id, p.incompletion_share) for p in usage.players if p.incompletion_share > 0])
                if kind == "interception":
                    add(qb, "interceptions")
            return
        # runs (and fumbles on runs)
        rusher = _draw(rng, [(p.player_id, p.carry_share * _exp_weight(yards, p.ypc))
                             for p in usage.players if p.carry_share > 0])
        add(rusher, "rush_att")
        add(rusher, "rush_yds", yards)
        if touchdown and rusher:
            line[rusher]["anytime_td"] = 1.0


def prob_over(values: Sequence[float], line: float) -> Optional[float]:
    """Share of seeds strictly above the line; an integer line drops pushes."""
    vals = list(values)
    if not vals:
        return None
    over = sum(1 for v in vals if v > line)
    push = sum(1 for v in vals if v == line)
    denom = len(vals) - push
    return over / denom if denom else None


# ---------------------------------------------------------------------------
# as-of usage from nflverse-shaped play rows
# ---------------------------------------------------------------------------

def build_team_usage(team: str, current: Iterable[Mapping[str, Any]], prior: Iterable[Mapping[str, Any]],
                     *, k_prior_games: float = 4.0, force_active: Iterable[str] = (),
                     qb_override: Optional[str] = None) -> TeamUsage:
    """`current` / `prior`: nflverse pbp rows STRICTLY before the week (the caller filters).

    Counts are the current season plus the prior season scaled to `k_prior_games`
    games; shares are over the players who touched the ball in the team's most
    recent game (the availability proxy -- no as-of inactive list exists)."""
    def tally(rows):
        c: Dict[str, Dict[str, float]] = {}
        names: Dict[str, str] = {}
        games: List[str] = []
        dropbacks: Dict[str, Dict[str, int]] = {}
        for r in rows:
            if r.get("posteam") != team or r.get("play_type") not in ("pass", "run"):
                continue
            gid = r.get("game_id")
            if gid and (not games or games[-1] != gid):
                if gid not in games:
                    games.append(gid)
            if r["play_type"] == "pass":
                qb = r.get("passer_player_id")
                if qb:
                    dropbacks.setdefault(gid, {})
                    dropbacks[gid][qb] = dropbacks[gid].get(qb, 0) + 1
                    names[qb] = r.get("passer_player_name") or qb
                rid = r.get("receiver_player_id")
                if rid and r.get("sack") != "1":
                    names[rid] = r.get("receiver_player_name") or rid
                    d = c.setdefault(rid, {})
                    d["targets"] = d.get("targets", 0) + 1
                    if r.get("complete_pass") == "1":
                        d["rec"] = d.get("rec", 0) + 1
                        d["rec_yds"] = d.get("rec_yds", 0) + float(r.get("yards_gained") or 0)
            else:
                rid = r.get("rusher_player_id")
                if rid:
                    names[rid] = r.get("rusher_player_name") or rid
                    d = c.setdefault(rid, {})
                    d["carries"] = d.get("carries", 0) + 1
                    d["rush_yds"] = d.get("rush_yds", 0) + float(r.get("yards_gained") or 0)
        return c, names, games, dropbacks

    cur, n1, g1, db1 = tally(current)
    pri, n2, g2, db2 = tally(prior)
    names = {**n2, **n1}
    scale = (k_prior_games / len(g2)) if g2 else 0.0
    blended: Dict[str, Dict[str, float]] = {}
    for src, w in ((cur, 1.0), (pri, scale)):
        for pid, d in src.items():
            b = blended.setdefault(pid, {})
            for k, v in d.items():
                b[k] = b.get(k, 0.0) + w * v
    # availability: touched the ball in the most recent game (current season, else prior)
    recent_rows_src, recent_games, recent_db = (current, g1, db1) if g1 else (prior, g2, db2)
    last = recent_games[-1] if recent_games else None
    active = set()
    if last:
        for r in recent_rows_src:
            if r.get("game_id") == last and r.get("posteam") == team:
                for col in ("receiver_player_id", "rusher_player_id", "passer_player_id"):
                    if r.get(col):
                        active.add(r[col])
    # A1: players quoted for this game are playing (pregame information the book publishes)
    active |= set(force_active)
    tot_t = sum(d.get("targets", 0) for p, d in blended.items() if p in active) or 1.0
    tot_r = sum(d.get("rec", 0) for p, d in blended.items() if p in active) or 1.0
    tot_c = sum(d.get("carries", 0) for p, d in blended.items() if p in active) or 1.0
    players = []
    for pid, d in blended.items():
        if pid not in active:
            continue
        rec, tgt = d.get("rec", 0.0), d.get("targets", 0.0)
        players.append(PlayerUsage(
            player_id=pid, name=names.get(pid, pid),
            carry_share=d.get("carries", 0.0) / tot_c,
            reception_share=rec / tot_r,
            incompletion_share=max(0.0, tgt - rec) / max(1.0, tot_t - tot_r),
            ypr=(d["rec_yds"] / rec) if rec >= 3 else LEAGUE_YPR,
            ypc=(d["rush_yds"] / d["carries"]) if d.get("carries", 0) >= 5 else LEAGUE_YPC,
        ))
    # primary QB: most dropbacks over the last 3 games of the season that has games
    qb_counts: Dict[str, int] = {}
    for gid in recent_games[-3:]:
        for qb, n in recent_db.get(gid, {}).items():
            qb_counts[qb] = qb_counts.get(qb, 0) + n
    qb = max(qb_counts, key=qb_counts.get) if qb_counts else None
    if qb_override:
        qb = qb_override                                  # A1: the quoted QB starts
    return TeamUsage(team=team, qb_id=qb, qb_name=names.get(qb, "") if qb else "", players=tuple(players))
