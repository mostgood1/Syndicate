"""NCAAF player-prop projections: a season-to-date baseline, shrunk, with a
distribution -- built on the WORKER, read by the board and by Ask.

--------------------------------------------------------------------------
WHAT THIS IS, AND WHY IT IS NOT `prop_model.py`
--------------------------------------------------------------------------

`prop_model.py` is anytime-TD only on purpose: its own backtest (2025, weeks
5-16, rates fitted on weeks < w) found the player's prior-weeks MEAN beat its
model on every yardage/count market (passing yards MAE 56.8 vs 67.4). So the
projection here IS that baseline -- the player's own season-to-date per-game
mean -- made usable early in a season by shrinking it toward a prior, and given
a spread so a line can be priced:

    n    = the player's games in season S with week < N        (never week N)
    xbar = his per-game mean over those games (a game he logged ANY line in,
           so a zero in this market counts as a zero)
    r    = ROLE PRIOR: the pooled per-game mean of this market among reference
           players in the same volume bucket (`ROLE_BUCKETS`, bucketed by the
           player's own per-game opportunity: pass attempts / carries /
           receptions)
    x0   = PRIOR-SEASON mean (season S-1, same CFBD player_id -- ids persist
           across transfers: 3,019 roster ids changed school 2025 -> 2026 with
           the id unchanged, checked on the roster snapshot), used ONLY when his
           S-1 role bucket equals his current one. A backup who became the
           starter is the common CFB case, and his backup line is not a prior
           for his starter line.
    mu0  = (n0 * x0 + K_PRIOR_ROLE * r) / (n0 + K_PRIOR_ROLE)   if x0 is used
         = r                                                    otherwise
    K    = K_SEASON if x0 is used else K_ROLE
    MEAN = (n * xbar + K * mu0) / (n + K)

The constants were CHOSEN, not fitted: `K_ROLE` = 2 games, `K_SEASON` = 3
games, `K_PRIOR_ROLE` = 2 games, `K_SPREAD` = 4 degrees of freedom. A player
with one game is ~1/3 his own line and ~2/3 prior; with six games ~3/4 his own.
`scripts/build_ncaaf_prop_projections.py --backtest` scores this against real
OUTCOMES; nothing here has been scored against a PRICE.

THE DISTRIBUTION, so P(over line) exists:

    yards  gamma (support >= 0, right-skewed), falling back to a normal only
           when the projected mean is <= 0 (CFB charges sacks to rushing, so a
           QB's rushing mean can be). Rushing was a NORMAL in the first draft;
           on the 2025 checkout backtest its P(over) at a line near the
           player's own mean was badly overstated (0.56 predicted, 0.38
           observed in the busiest bin) and the gamma moved the proxy-line
           Brier 0.244 -> 0.222 (weeks 2-8) and 0.255 -> 0.214 (weeks 9-16,
           held out) with the mean unchanged.
           sd: the player's own game-to-game sd shrunk toward a reference sd
           that grows with the mean (`sd0 = a + b * MEAN`, least squares over
           the reference players), weight (n - 1) vs `K_SPREAD`.
    counts passing TDs / receptions -> negative binomial, or Poisson when the
           shrunk variance/mean ratio is <= 1; the ratio is shrunk the same way
           toward the reference players' median ratio.

    Both spreads are widened by the uncertainty in the mean itself:
    var_pred = var * (1 + 1 / (n + K)).

NEVER A LEAGUE DEFAULT. A player with no season-S game before week N gets NO
entry -- not a role prior dressed up as a projection. A player with games but
no opportunity in a market (a receiver with zero receptions) gets no entry for
that market, and a player whose role is `spot` in EVERY family (a backup with a
carry or two) gets none at all -- when such a player is quoted it is because
his role just changed, and a projection pulled toward the spot prior would be
confidently absurd. All three are counted in the artifact's `refusals`.
ROLE CHANGE IS THIS MODEL'S BLIND SPOT: a baseline built from the games a
player has had cannot know he was promoted this week.

ANYTIME TD IS NOT HERE. `prop_model.anytime_td_probability` rates a player on
his WHOLE season, which on a mid-week build includes week N's Thursday games --
the lookahead this module exists to refuse. The served board carries no NCAAF
anytime-TD rows (Passing Yards, Passing TDs, Rushing Yards, Receiving Yards,
Receptions on 2026-09-18), so nothing served is lost by leaving it out.

KNOWN BIAS, stated rather than hidden: CFBD's `/games/players` lists a player
only in a game where he logged a line in some category, so a receiver held
without a catch AND without a carry has no row for that game and his mean is
computed over the games he appeared in. That biases low-volume players upward.

--------------------------------------------------------------------------
WHERE IT RUNS
--------------------------------------------------------------------------

`build_prop_projections` runs on refresh-worker at the END of the player-stats
refresh (`player_stats_refresh.refresh_player_game_stats`) and writes
`ncaaf_source/data/ncaaf_prop_projections_{season}_wk{week}.json`, published to
web through `HOT_ARTIFACT_PATTERNS`. Web only READS it. The one piece of
arithmetic a reader does is `prob_over` -- evaluating the published
distribution at the row's line, one closed-form CDF, the same order of work as
the de-vig beside it -- because lines move after the build and a line-keyed
artifact (NFL's shape) cannot price a line quoted later.
"""

from __future__ import annotations

import csv
import json
import logging
import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping

_LOGGER = logging.getLogger(__name__)

SCHEMA = "ncaaf_prop_projections_v1"
PROJECTION_SOURCE = "ncaaf_prop_model"

#: Shrinkage weights, in GAMES (see the module docstring). Chosen a priori.
K_ROLE = 2.0
K_SEASON = 3.0
K_PRIOR_ROLE = 2.0
#: Weight of the reference spread against the player's own, in degrees of freedom.
K_SPREAD = 4.0

#: Reference players need this many games to contribute a spread estimate.
REFERENCE_MIN_GAMES = 3
#: A role bucket with fewer reference players than this falls back to the
#: market's pooled reference over every bucket.
MIN_REFERENCE_PLAYERS = 8

MARKETS: dict[str, dict[str, str]] = {
    "passing_yards": {"family": "passing", "dist": "gamma", "label": "Passing Yards"},
    "passing_tds": {"family": "passing", "dist": "count", "label": "Passing TDs"},
    "rushing_yards": {"family": "rushing", "dist": "gamma", "label": "Rushing Yards"},
    "receiving_yards": {"family": "receiving", "dist": "gamma", "label": "Receiving Yards"},
    "receptions": {"family": "receiving", "dist": "count", "label": "Receptions"},
}

#: The opportunity column per family, and its per-game (lead, rotation)
#: thresholds; below `rotation` is `spot`. CFBD box lines carry no targets or
#: snaps, so receptions stand in for receiving opportunity.
FAMILY_OPPORTUNITY: dict[str, str] = {
    "passing": "passing_attempts",
    "rushing": "rushing_attempts",
    "receiving": "receptions",
}
ROLE_BUCKETS: dict[str, tuple[float, float]] = {
    "passing": (20.0, 8.0),
    "rushing": (12.0, 5.0),
    "receiving": (4.0, 2.0),
}

#: Used only when the reference population is too thin to fit its own (the
#: artifact then says `fallback: true`). sd0 = a + b * mean for yards;
#: variance/mean for counts.
FALLBACK_SD_LINE: dict[str, tuple[float, float]] = {
    "passing_yards": (25.0, 0.30),
    "rushing_yards": (15.0, 0.45),
    "receiving_yards": (10.0, 0.55),
}
FALLBACK_DISPERSION: dict[str, float] = {"passing_tds": 1.0, "receptions": 1.0}

#: An UNDER-dispersed count (variance/mean < 1; receptions' 2025 reference
#: median is 0.70) is priced as a POISSON. Tried and REVERTED 2026-09-18: a
#: normal on the half-integer grid with the shrunk ratio made the 2025 checkout
#: backtest's proxy-line Brier WORSE (receptions 0.2292 -> 0.2309, passing TDs
#: 0.1870 -> 0.1875), so the Poisson's extra width is kept.
COUNT_DISTRIBUTIONS = frozenset({"poisson", "negbin"})

#: Board market label (casefolded) -> stat. Display labels are what
#: `fetch_ncaaf_oddsapi_props_local.MARKET_STD_MAP` writes; the raw OddsAPI keys
#: are accepted because a producer has served them before on NFL.
MARKET_LABEL_TO_STAT: dict[str, str] = {
    "passing yards": "passing_yards",
    "passing tds": "passing_tds",
    "rushing yards": "rushing_yards",
    "receiving yards": "receiving_yards",
    "receptions": "receptions",
    "player_pass_yds": "passing_yards",
    "player_pass_tds": "passing_tds",
    "player_rush_yds": "rushing_yards",
    "player_reception_yds": "receiving_yards",
    "player_receptions": "receptions",
}

_NUMERIC = ("passing_attempts", "passing_yards", "passing_tds", "rushing_attempts", "rushing_yards",
            "receptions", "receiving_yards")

_Z80 = 1.2815515655446004


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


def artifact_name(season: int, week: int) -> str:
    return f"ncaaf_prop_projections_{int(season)}_wk{int(week)}.json"


def artifact_path(season: int, week: int) -> Path:
    from syndicate.features.ncaaf.sources import data_path

    return data_path(artifact_name(season, week))


def artifact_weeks_on_disk(season: int) -> list[int]:
    """Weeks with a projection artifact for `season`, ascending."""
    from syndicate.features.ncaaf.sources import data_path

    weeks: set[int] = set()
    try:
        for path in data_path().glob(f"ncaaf_prop_projections_{int(season)}_wk*.json"):
            tail = path.stem.rsplit("_wk", 1)[-1]
            if tail.isdigit():
                weeks.add(int(tail))
    except OSError:
        return []
    return sorted(weeks)


# ---------------------------------------------------------------------------
# Distribution arithmetic (pure; the only thing a reader computes)
# ---------------------------------------------------------------------------


def _gamma_p(a: float, x: float) -> float:
    """Regularized lower incomplete gamma P(a, x): series below a+1, else a
    continued fraction for Q (Numerical Recipes 6.2)."""
    if x <= 0.0:
        return 0.0
    log_prefix = -x + a * math.log(x) - math.lgamma(a)
    if x < a + 1.0:
        term = 1.0 / a
        total = term
        ap = a
        for _ in range(1000):
            ap += 1.0
            term *= x / ap
            total += term
            if abs(term) < abs(total) * 1e-14:
                break
        return min(1.0, max(0.0, total * math.exp(log_prefix)))
    tiny = 1e-300
    b = x + 1.0 - a
    c = 1.0 / tiny
    d = 1.0 / b
    h = d
    for i in range(1, 1000):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        d = tiny if abs(d) < tiny else d
        c = b + an / c
        c = tiny if abs(c) < tiny else c
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-14:
            break
    return min(1.0, max(0.0, 1.0 - math.exp(log_prefix) * h))


def _count_cdf(k: int, mean: float, dispersion: float) -> float:
    """P(X <= k): Poisson when dispersion <= 1, else NB with var = dispersion * mean."""
    if k < 0:
        return 0.0
    if mean <= 0.0:
        return 1.0
    if dispersion <= 1.0 + 1e-9:
        pmf = math.exp(-mean)
        total = pmf
        for i in range(1, k + 1):
            pmf *= mean / i
            total += pmf
        return min(1.0, total)
    r = mean / (dispersion - 1.0)
    p = r / (r + mean)
    pmf = math.exp(r * math.log(p))
    total = pmf
    for i in range(k):
        pmf *= (i + r) / (i + 1.0) * (1.0 - p)
        total += pmf
    return min(1.0, total)


def prob_over(entry: Mapping[str, Any], line: Any) -> float | None:
    """P(stat > line) from one published market entry, or None if unpriceable."""
    try:
        line_value = float(line)
        mean = float(entry["mean"])
    except (KeyError, TypeError, ValueError):
        return None
    if line_value != line_value:
        return None
    dist = str(entry.get("dist") or "")
    if dist in COUNT_DISTRIBUTIONS:
        try:
            dispersion = float(entry.get("dispersion") or 1.0)
        except (TypeError, ValueError):
            return None
        return max(0.0, 1.0 - _count_cdf(int(math.floor(line_value)), mean, dispersion))
    try:
        sd = float(entry.get("sd"))
    except (TypeError, ValueError):
        return None
    if not sd > 0.0:
        return None
    if dist == "gamma" and mean > 0.0:
        if line_value <= 0.0:
            return 1.0
        shape = (mean / sd) ** 2
        scale = sd * sd / mean
        return 1.0 - _gamma_p(shape, line_value / scale)
    if dist in ("normal", "gamma"):
        return 0.5 * math.erfc((line_value - mean) / (sd * math.sqrt(2.0)))
    return None


def central_range(entry: Mapping[str, Any]) -> tuple[float, float] | None:
    """An approximate 80% interval for DISPLAY (normal approximation on the
    published mean and spread; counts use sqrt(dispersion * mean))."""
    try:
        mean = float(entry["mean"])
        if str(entry.get("dist") or "") in COUNT_DISTRIBUTIONS:
            sd = math.sqrt(max(0.0, float(entry.get("dispersion") or 1.0) * mean))
        else:
            sd = float(entry.get("sd"))
    except (KeyError, TypeError, ValueError):
        return None
    low = mean - _Z80 * sd
    if str(entry.get("dist") or "") != "normal":
        low = max(0.0, low)
    return low, mean + _Z80 * sd


# ---------------------------------------------------------------------------
# The build (worker only)
# ---------------------------------------------------------------------------


@dataclass
class _Game:
    week: int
    game_id: str
    team: str
    stats: dict[str, float]


@dataclass
class _Player:
    player_id: str
    name: str = ""
    games: list[_Game] = field(default_factory=list)


def _read_snapshot(path: Path, seasons: Iterable[int]) -> dict[int, dict[str, _Player]]:
    """season -> player_id -> games, streamed (only the columns the model reads)."""
    wanted = {str(int(s)) for s in seasons}
    out: dict[int, dict[str, _Player]] = {int(s): {} for s in wanted}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            season = str(row.get("season") or "").strip()
            if season not in wanted:
                continue
            player_id = str(row.get("player_id") or "").strip()
            name = str(row.get("player_name") or "").strip()
            try:
                week = int(row.get("week") or 0)
            except (TypeError, ValueError):
                continue
            # CFBD's "Team" pseudo-player (negative id) carries team sack
            # yardage and kneel-downs; it is not a person and is never projected.
            if not player_id or player_id.startswith("-") or not name or week <= 0:
                continue
            stats: dict[str, float] = {}
            for col in _NUMERIC:
                try:
                    stats[col] = float(row.get(col) or 0.0)
                except (TypeError, ValueError):
                    stats[col] = 0.0
            player = out[int(season)].setdefault(player_id, _Player(player_id=player_id))
            player.games.append(_Game(week=week, game_id=str(row.get("game_id") or ""),
                                      team=str(row.get("team") or ""), stats=stats))
            player.name = name
    for players in out.values():
        for player in players.values():
            player.games.sort(key=lambda g: (g.week, g.game_id))
    return out


def _bucket(family: str, per_game_opportunity: float) -> str:
    lead, rotation = ROLE_BUCKETS[family]
    if per_game_opportunity >= lead:
        return "lead"
    if per_game_opportunity >= rotation:
        return "rotation"
    return "spot"


def _opportunity_per_game(games: list[_Game], family: str) -> float:
    column = FAMILY_OPPORTUNITY[family]
    return sum(g.stats[column] for g in games) / len(games) if games else 0.0


def _role(family: str, games: list[_Game]) -> str:
    """The volume bucket, split by the player's OTHER job where it changes the
    market's economics. CFBD publishes no positions on these lines, so the job
    is read off the volume:

      receiving + >= `rotation` carries/game  -> "+rusher"  (a running back's
          catches are screens and checkdowns: measured on the 2025 checkout,
          the receivers the plain bucket priced worst ran 3.5 yards a catch
          against a wide receiver's ~12)
      rushing + >= `rotation` pass attempts/game -> "+passer" (a QB's carries
          include sacks and scrambles, not designed runs)
    """
    bucket = _bucket(family, _opportunity_per_game(games, family))
    if family == "receiving" and _opportunity_per_game(games, "rushing") >= ROLE_BUCKETS["rushing"][1]:
        return bucket + "+rusher"
    if family == "rushing" and _opportunity_per_game(games, "passing") >= ROLE_BUCKETS["passing"][1]:
        return bucket + "+passer"
    return bucket


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _sample_sd(values: list[float]) -> float | None:
    """Sample sd (n - 1). Plain floats: `statistics.stdev` is exact-rational
    and was most of a 35k-row build's 8.6 s."""
    n = len(values)
    if n < 2:
        return None
    mean = sum(values) / n
    return math.sqrt(max(0.0, sum((v - mean) ** 2 for v in values) / (n - 1)))


def _fit_line(points: list[tuple[float, float]]) -> tuple[float, float] | None:
    """Least squares sd = a + b * mean, clamped to a >= 0, b >= 0."""
    if len(points) < MIN_REFERENCE_PLAYERS:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 0:
        return None
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    return max(0.0, my - b * mx), max(0.0, b)


def build_reference(players: Iterable[_Player], *, before_week: int | None) -> dict[str, Any]:
    """Per-market role priors and spread references over a player population.

    `before_week` restricts to games strictly before it (a current-season
    reference); None takes every game (a completed prior season).
    """
    sums: dict[tuple[str, str], list[float]] = {}
    spread_points: dict[str, list[tuple[float, float]]] = {m: [] for m in MARKETS}
    ratios: dict[str, list[float]] = {m: [] for m in MARKETS}
    for player in players:
        games = [g for g in player.games if before_week is None or g.week < before_week]
        if not games:
            continue
        for market, spec in MARKETS.items():
            opportunity = _opportunity_per_game(games, spec["family"])
            if opportunity <= 0.0:
                continue
            values = [g.stats[market] for g in games]
            for key in ((market, _role(spec["family"], games)), (market, "all")):
                cell = sums.setdefault(key, [0.0, 0.0, 0.0])
                cell[0] += sum(values)
                cell[1] += len(values)
                cell[2] += 1
            if len(values) >= REFERENCE_MIN_GAMES:
                mean = statistics.fmean(values)
                sd = _sample_sd(values)
                if spec["dist"] == "count":
                    if mean > 0 and sd is not None:
                        ratios[market].append(sd * sd / mean)
                elif sd is not None:
                    spread_points[market].append((mean, sd))
    priors: dict[str, dict[str, dict[str, float]]] = {}
    for (market, bucket), (total, games_n, players_n) in sums.items():
        priors.setdefault(market, {})[bucket] = {
            "mean": round(total / games_n, 4) if games_n else 0.0,
            "games": int(games_n),
            "players": int(players_n),
        }
    spread: dict[str, dict[str, Any]] = {}
    for market, spec in MARKETS.items():
        if spec["dist"] == "count":
            values = ratios[market]
            if len(values) >= MIN_REFERENCE_PLAYERS:
                spread[market] = {"dispersion": round(statistics.median(values), 4), "players": len(values),
                                  "fallback": False}
            else:
                spread[market] = {"dispersion": FALLBACK_DISPERSION[market], "players": len(values), "fallback": True}
        else:
            fit = _fit_line(spread_points[market])
            if fit is None:
                a, b = FALLBACK_SD_LINE[market]
                spread[market] = {"sd_a": a, "sd_b": b, "players": len(spread_points[market]), "fallback": True}
            else:
                spread[market] = {"sd_a": round(fit[0], 4), "sd_b": round(fit[1], 4),
                                  "players": len(spread_points[market]), "fallback": False}
    return {"priors": priors, "spread": spread}


def _role_prior(reference: Mapping[str, Any], market: str, bucket: str) -> tuple[float, str] | None:
    table = reference["priors"].get(market) or {}
    cell = table.get(bucket)
    if cell and cell.get("players", 0) >= MIN_REFERENCE_PLAYERS:
        return float(cell["mean"]), f"role:{bucket}"
    pooled = table.get("all")
    if pooled and pooled.get("players", 0) > 0:
        return float(pooled["mean"]), "role:all"
    return None


def project_market(
    *,
    market: str,
    games: list[_Game],
    prior_games: list[_Game],
    reference: Mapping[str, Any],
) -> dict[str, Any] | None:
    """One player's projection for one market, or None (no game, no
    opportunity in this market, or no role prior to shrink toward)."""
    spec = MARKETS[market]
    family = spec["family"]
    n = len(games)
    if n == 0:
        return None
    opportunity = _opportunity_per_game(games, family)
    if opportunity <= 0.0:
        return None
    bucket = _role(family, games)
    role = _role_prior(reference, market, bucket)
    if role is None:
        return None
    role_mean, role_source = role
    values = [g.stats[market] for g in games]
    xbar = statistics.fmean(values)

    n0 = len(prior_games)
    prior_used = bool(n0) and _role(family, prior_games) == bucket
    if prior_used:
        x0 = statistics.fmean(g.stats[market] for g in prior_games)
        mu0 = (n0 * x0 + K_PRIOR_ROLE * role_mean) / (n0 + K_PRIOR_ROLE)
        k = K_SEASON
        prior_source = f"prior_season+{role_source}"
    else:
        mu0 = role_mean
        k = K_ROLE
        prior_source = role_source if not n0 else f"{role_source} (prior season role differed)"
    mean = (n * xbar + k * mu0) / (n + k)
    widen = 1.0 + 1.0 / (n + k)
    df = max(0, n - 1)
    own_sd = _sample_sd(values)
    spread = reference["spread"][market]

    entry: dict[str, Any] = {
        "mean": round(mean, 3),
        "season_mean": round(xbar, 3),
        "season_games": n,
        "role": bucket,
        "prior_mean": round(mu0, 3),
        "prior_source": prior_source,
        "prior_weight_games": k,
        "prior_season_games": n0 if prior_used else 0,
    }
    if spec["dist"] == "count":
        d0 = float(spread["dispersion"])
        own = (own_sd * own_sd / xbar) if (own_sd is not None and xbar > 0) else None
        d = ((df * own + K_SPREAD * d0) / (df + K_SPREAD)) if own is not None else d0
        d_pred = d * widen
        if d_pred > 1.0 + 1e-9:
            entry["dist"], entry["dispersion"] = "negbin", round(d_pred, 4)
        else:
            entry["dist"], entry["dispersion"] = "poisson", 1.0
    else:
        sd0 = float(spread["sd_a"]) + float(spread["sd_b"]) * max(0.0, mean)
        sd = ((df * own_sd + K_SPREAD * sd0) / (df + K_SPREAD)) if own_sd is not None else sd0
        dist = spec["dist"]
        if dist == "gamma" and mean <= 0.0:
            dist = "normal"
        entry["dist"] = dist
        entry["sd"] = round(max(sd * math.sqrt(widen), 1e-6), 3)
    return entry


@dataclass
class BuildResult:
    season: int
    week: int
    path: Path | None
    written: bool
    reason: str = ""
    players: int = 0
    projections: int = 0
    bytes: int = 0
    refusals: dict[str, int] = field(default_factory=dict)
    published: bool | None = None
    payload: dict[str, Any] | None = None

    def summary_line(self) -> str:
        return (
            f"[ncaaf_prop_projections] {'WRITTEN' if self.written else 'NOT_WRITTEN'} "
            f"season={self.season} week={self.week} players={self.players} projections={self.projections} "
            f"bytes={self.bytes} refusals={self.refusals} published={self.published} "
            f"reason={self.reason or '-'} path={self.path}"
        )


def build_payload(
    *,
    season: int,
    week: int,
    snapshot_path: Path,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """The artifact payload for (season, week) -- pure over the snapshot file.

    Reads seasons S and S-1 only; every season-S game at week >= N is dropped
    before anything is computed, so week N's own game cannot leak in however
    late in the week the build runs.
    """
    season, week = int(season), int(week)
    by_season = _read_snapshot(snapshot_path, (season, season - 1))
    return payload_from_players(
        season=season,
        week=week,
        current=by_season.get(season, {}),
        previous=by_season.get(season - 1, {}),
        snapshot_name=snapshot_path.name,
        generated_at=generated_at,
    )


def read_snapshot_players(snapshot_path: Path, seasons: Iterable[int]) -> dict[int, dict[str, _Player]]:
    """Public for the backtest: read once, build many weeks."""
    return _read_snapshot(snapshot_path, seasons)


def payload_from_players(
    *,
    season: int,
    week: int,
    current: Mapping[str, _Player],
    previous: Mapping[str, _Player],
    snapshot_name: str,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """`build_payload` over already-read players (`read_snapshot_players`)."""
    season, week = int(season), int(week)
    if previous:
        reference = build_reference(previous.values(), before_week=None)
        reference_basis = f"season {season - 1}, all weeks"
    else:
        reference = build_reference(current.values(), before_week=week)
        reference_basis = f"season {season}, weeks < {week}"

    refusals = {"no_game_before_week": 0, "no_opportunity_market": 0, "no_role_prior_market": 0,
                "spot_role_only_player": 0}
    players_out: list[dict[str, Any]] = []
    weeks_used: set[int] = set()
    for player_id, player in sorted(current.items()):
        games = [g for g in player.games if g.week < week]
        if not games:
            refusals["no_game_before_week"] += 1
            continue
        weeks_used.update(g.week for g in games)
        prior = previous.get(player_id)
        prior_games = list(prior.games) if prior is not None else []
        markets: dict[str, Any] = {}
        for market, spec in MARKETS.items():
            if _opportunity_per_game(games, spec["family"]) <= 0.0:
                refusals["no_opportunity_market"] += 1
                continue
            entry = project_market(market=market, games=games, prior_games=prior_games, reference=reference)
            if entry is None:
                refusals["no_role_prior_market"] += 1
                continue
            markets[market] = entry
        if not markets:
            continue
        if all(entry["role"].startswith("spot") for entry in markets.values()):
            # SPOT ROLE IN EVERY FAMILY: a backup with a carry or two. Measured
            # on the 2025 checkout snapshot at week 5, 2,319 of 5,000 players
            # and ~40% of the file. Books do not quote them, and when one IS
            # quoted it is because his role just changed (a backup named the
            # starter) -- where shrinking toward the spot prior (~15 passing
            # yards) would be a confidently absurd number. Refused, counted.
            refusals["spot_role_only_player"] += 1
            continue
        players_out.append({
            "player_id": player_id,
            "name": player.name,
            "team": games[-1].team,
            "games": len(games),
            "last_week": games[-1].week,
            "markets": markets,
        })

    return {
        "schema": SCHEMA,
        "source": PROJECTION_SOURCE,
        "season": season,
        "week": week,
        "generated_at": generated_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "method": {
            "mean": "(n*xbar + K*mu0)/(n+K); mu0 = prior-season mean shrunk to the role prior when the role "
                    "is unchanged, else the role prior",
            "K_ROLE": K_ROLE,
            "K_SEASON": K_SEASON,
            "K_PRIOR_ROLE": K_PRIOR_ROLE,
            "K_SPREAD": K_SPREAD,
            "role_buckets": {k: list(v) for k, v in ROLE_BUCKETS.items()},
            "distributions": {m: s["dist"] for m, s in MARKETS.items()},
            "no_lookahead": f"only season-{season} games with week < {week}",
            "skill": "unmeasured against prices",
        },
        "input": {
            "snapshot": snapshot_name,
            "season_players": len(current),
            "prior_season": season - 1 if previous else None,
            "prior_season_players": len(previous),
            "weeks_used": sorted(weeks_used),
            "reference_basis": reference_basis,
        },
        "reference": reference,
        "refusals": refusals,
        "players": players_out,
    }


def build_prop_projections(
    *,
    season: int,
    week: int,
    snapshot_path: Path | None = None,
    output_path: Path | None = None,
    publish: bool = True,
) -> BuildResult:
    """Build, write and publish one week's artifact. Never writes an empty one."""
    from syndicate.features.ncaaf.sources import player_game_stats_snapshot_path

    season, week = int(season), int(week)
    source = snapshot_path or player_game_stats_snapshot_path()
    target = output_path or artifact_path(season, week)
    if not source.exists():
        return BuildResult(season=season, week=week, path=target, written=False, reason="snapshot_missing")
    payload = build_payload(season=season, week=week, snapshot_path=source)
    players = payload["players"]
    result = BuildResult(season=season, week=week, path=target, written=False, players=len(players),
                         projections=sum(len(p["markets"]) for p in players),
                         refusals=dict(payload["refusals"]), payload=payload)
    if not players:
        # AN EMPTY ARTIFACT IS NEVER WRITTEN, let alone published: a zero-row
        # file on web reads as "the model has no view on anyone" and replaces a
        # good copy. NFL shipped exactly that (`/nfl/api/props` 1,684 -> 0) and
        # `artifact_publisher._NON_EMPTY_REQUIRED_PATTERNS` exists because of it.
        result.reason = "no_player_has_a_game_before_week"
        return result
    text = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".json.part")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(target)
    result.written = True
    result.bytes = len(text.encode("utf-8"))
    if publish:
        try:
            from syndicate.features.shared.artifact_publisher import publish_hot_artifact

            result.published = bool(publish_hot_artifact(target, timeout_seconds=120))
        except Exception as exc:  # noqa: BLE001 - a transfer failure never fails the build
            result.published = False
            result.reason = f"publish_error:{type(exc).__name__}"
    return result


# ---------------------------------------------------------------------------
# Reading (web and worker)
# ---------------------------------------------------------------------------


def name_keys(value: Any) -> set[str]:
    """Every spelling of one name a feed might use -- the shared board rule
    (`prop_evidence.common.name_keys`: accents folded, suffixes dropped,
    "D.J." == "DJ")."""
    from syndicate.features.shared.prop_evidence.common import name_keys as shared_name_keys

    return {key for key in shared_name_keys(value) if key}


@dataclass
class NcaafPropProjectionIndex:
    season: int | None = None
    week: int | None = None
    generated_at: str | None = None
    path: Path | None = None
    players: int = 0
    by_name: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    by_id: dict[str, dict[str, Any]] = field(default_factory=dict)

    def candidates(self, player_name: Any) -> list[dict[str, Any]]:
        seen: dict[str, dict[str, Any]] = {}
        for key in name_keys(player_name):
            for entry in self.by_name.get(key, ()):
                seen[str(entry.get("player_id"))] = entry
        return list(seen.values())


def index_from_payload(payload: Mapping[str, Any], path: Path | None = None) -> NcaafPropProjectionIndex:
    index = NcaafPropProjectionIndex(
        season=int(payload.get("season") or 0) or None,
        week=int(payload.get("week") or 0) or None,
        generated_at=str(payload.get("generated_at") or "") or None,
        path=path,
    )
    for player in payload.get("players") or ():
        if not isinstance(player, Mapping) or not isinstance(player.get("markets"), Mapping):
            continue
        entry = dict(player)
        index.by_id[str(entry.get("player_id"))] = entry
        for key in name_keys(entry.get("name")):
            index.by_name.setdefault(key, []).append(entry)
        index.players += 1
    return index


@lru_cache(maxsize=8)
def _index_cached(path_text: str, mtime_ns: int, size: int) -> NcaafPropProjectionIndex | None:
    try:
        payload = json.loads(Path(path_text).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - unreadable is absent, never a crash
        _LOGGER.exception("NCAAF_PROP_PROJECTION_READ_FAILURE path=%s", path_text)
        return None
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        return None
    return index_from_payload(payload, Path(path_text))


def load_index(season: int, week: int) -> NcaafPropProjectionIndex | None:
    """The published artifact for (season, week) as a join index, or None.
    Cached by file stamp, so a republished week is read on the next call."""
    path = artifact_path(season, week)
    try:
        info = path.stat()
    except OSError:
        return None
    index = _index_cached(str(path), int(info.st_mtime_ns), int(info.st_size))
    if index is None or index.season != int(season) or index.week != int(week):
        return None
    return index


def newest_index_at_or_before(season: int, week: int) -> NcaafPropProjectionIndex | None:
    """The artifact for `week`, else the newest EARLIER one. Never a later one:
    a later week's build includes this week's games, which is lookahead."""
    for candidate in sorted((w for w in artifact_weeks_on_disk(season) if w <= int(week)), reverse=True):
        index = load_index(season, candidate)
        if index is not None and index.players:
            return index
    return None


def _fold_team(value: Any) -> str:
    try:
        from syndicate.features.ncaaf.oddsapi_lines import fold

        return fold(value)
    except Exception:  # noqa: BLE001
        return str(value or "").strip().casefold()


def find_player(
    index: NcaafPropProjectionIndex, player_name: Any, teams: Iterable[str | None]
) -> tuple[dict[str, Any] | None, str]:
    """(player, "") or (None, reason).

    A name joins ONLY through one of `teams` -- the game's two CFBD schools. A
    namesake at another school is never used, and two matches on this game's
    schools are refused rather than guessed.
    """
    wanted = {_fold_team(t) for t in teams if t}
    if not wanted:
        return None, "teams_unresolved"
    candidates = index.candidates(player_name)
    if not candidates:
        return None, "player_not_in_artifact"
    on_team = [c for c in candidates if _fold_team(c.get("team")) in wanted]
    if not on_team:
        return None, "player_not_on_either_team"
    if len(on_team) > 1:
        return None, "ambiguous_player"
    return on_team[0], ""


# ---------------------------------------------------------------------------
# Week placement for a board row
# ---------------------------------------------------------------------------


def _parse_ts(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def season_for_date(value: Any) -> int | None:
    """A football season is named for the year it starts; Jan/Feb belong to the previous one."""
    text = str(value or "").strip()
    try:
        year, month = int(text[:4]), int(text[5:7])
    except (ValueError, IndexError):
        return None
    return year - 1 if month <= 2 else year


def week_for_kickoff(
    season: int, commence_time: Any, *, week_state: Mapping[str, Any] | None = None
) -> tuple[int | None, str]:
    """(week, how) for a kickoff: the lowest week whose LAST unplayed kickoff
    is not before it (`week_state`, the resolver Ask's game-sim layer uses),
    else week_state's target week, else (None, "unresolved").

    READS THE PUBLISHED week_state ONLY. `sources.ncaaf_target_week` falls back
    to the raw CFBD games cache when the artifact is absent, and that fallback
    measured 17.9 s and 41 MB retained on a dev machine -- a price a board join
    or an Ask answer must never pay. Unresolved is counted, not guessed.
    """
    kickoff = _parse_ts(commence_time)
    state = week_state
    if state is None:
        try:
            from syndicate.features.ncaaf.week_state import read_week_state

            state = read_week_state(int(season))
        except Exception:  # noqa: BLE001
            state = None
    unplayed = state.get("unplayed_kickoffs") if isinstance(state, Mapping) else None
    if isinstance(unplayed, Mapping) and kickoff is not None:
        for week in sorted(int(w) for w in unplayed if str(w).isdigit()):
            last = _parse_ts((unplayed.get(str(week)) or {}).get("last"))
            if last is not None and last >= kickoff:
                return week, "week_state"
    target = current_week_from_state(season, week_state=state)
    return (target, "week_state_target") if target else (None, "unresolved")


def current_week_from_state(season: int, *, week_state: Mapping[str, Any] | None = None) -> int | None:
    """The week in progress per the PUBLISHED week_state, never the games cache."""
    try:
        from syndicate.features.ncaaf.week_state import read_week_state, target_week_from_state

        state = week_state if week_state is not None else read_week_state(int(season))
        target = target_week_from_state(state)
    except Exception:  # noqa: BLE001
        return None
    return int(target) if target else None


# ---------------------------------------------------------------------------
# The board join (`board_enrichment._attach_projections_by_sport`, NCAAF)
# ---------------------------------------------------------------------------


def _as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed or parsed in (float("inf"), float("-inf")):
        return None
    return parsed


def _row_date(row: Mapping[str, Any]) -> str:
    """The row's CENTRAL kickoff date -- the key every board reader's per-date
    pass uses (`odds_book_quotes.kickoff_shard_date`), else the UTC prefix."""
    try:
        from syndicate.features.shared.odds_book_quotes import kickoff_shard_date

        central = kickoff_shard_date(row)
    except Exception:  # noqa: BLE001
        central = None
    return str(central or str(row.get("commence_time") or "")[:10])


def attach_ncaaf_prop_projections(grid: Iterable[dict[str, Any]], *, selected_date: str | None = None) -> dict[str, Any]:
    """Stamp `projection` onto NCAAF player-prop rows from the published
    artifact. Returns coverage, every refusal counted under its own name.

    `selected_date` SCOPES THE PASS to rows whose Central kickoff date is that
    date. `layer2_shortlist._attach_projections_over_window` calls the NCAAF
    join once per date of a 7-day window over the SAME grid and SUMS the
    counters; an unscoped pass would count every prop row seven times (the
    exact artefact `ncaaf.game_projections.attach_ncaaf_game_projections`
    documents: 9.3% reported for a join that was really ~47%).

    `model_skill` IS DELIBERATELY NOT SET HERE. `projection_skill.attach_projection_skill`
    (run by the `attach_projections` wrapper for every sport) stamps the
    declared-absence note -- `status: "unmeasured"` -- on any projection that
    has none, and COUNTS it as unmeasured. A producer note, even one that says
    "unmeasured", is counted under `rows_with_measured_skill`, which would put
    430 never-scored rows into the measured column.
    """
    from syndicate.features.shared.probability_refusal import refuse_published_certainty
    from syndicate.features.shared.wnba_game_projections import _attach_sim_probability_edge

    try:
        from syndicate.features.ncaaf.oddsapi_lines import resolve_team
    except Exception:  # noqa: BLE001
        resolve_team = None  # type: ignore[assignment]

    counts = {
        "rows_considered": 0,
        "rows_with_projection": 0,
        "unsupported_market_rows": 0,
        "no_line_rows": 0,
        "no_week_rows": 0,
        "no_artifact_rows": 0,
        "teams_unresolved_rows": 0,
        "player_not_in_artifact_rows": 0,
        "player_not_on_either_team_rows": 0,
        "ambiguous_player_rows": 0,
        "no_market_projection_rows": 0,
        "no_probability_rows": 0,
        "stale_week_rows": 0,
    }
    unsupported: dict[str, int] = {}
    artifact_weeks: dict[str, int] = {}
    week_cache: dict[tuple[int, str], tuple[int | None, str]] = {}
    index_cache: dict[tuple[int, int], NcaafPropProjectionIndex | None] = {}
    team_cache: dict[str, str | None] = {}
    date_key = str(selected_date or "")[:10]

    def _team(name: Any) -> str | None:
        key = str(name or "")
        if key not in team_cache:
            try:
                team_cache[key] = resolve_team(key) if resolve_team else None
            except Exception:  # noqa: BLE001
                team_cache[key] = None
        return team_cache[key]

    for row in grid:
        if not isinstance(row, dict) or str(row.get("kind") or "") != "prop":
            continue
        if date_key:
            row_date = _row_date(row)
            if row_date and row_date != date_key:
                continue
        counts["rows_considered"] += 1
        label = str(row.get("market") or "").strip()
        stat = MARKET_LABEL_TO_STAT.get(label.casefold())
        if stat is None:
            counts["unsupported_market_rows"] += 1
            unsupported[label] = unsupported.get(label, 0) + 1
            continue
        line = _as_float(row.get("line"))
        if line is None:
            counts["no_line_rows"] += 1
            continue
        kickoff = str(row.get("commence_time") or "")
        season = season_for_date(kickoff or date_key)
        if season is None:
            counts["no_week_rows"] += 1
            continue
        if (season, kickoff) not in week_cache:
            week_cache[(season, kickoff)] = week_for_kickoff(season, kickoff)
        game_week, week_basis = week_cache[(season, kickoff)]
        if game_week is None:
            counts["no_week_rows"] += 1
            continue
        if (season, game_week) not in index_cache:
            index_cache[(season, game_week)] = newest_index_at_or_before(season, game_week)
        index = index_cache[(season, game_week)]
        if index is None:
            counts["no_artifact_rows"] += 1
            continue
        home, away = _team(row.get("home_team")), _team(row.get("away_team"))
        if not home or not away:
            # Both, or neither: a player joined through ONE resolved school
            # would accept a namesake on the other that could not be checked.
            counts["teams_unresolved_rows"] += 1
            continue
        player, reason = find_player(index, row.get("player_name"), (home, away))
        if player is None:
            counts[f"{reason}_rows"] = counts.get(f"{reason}_rows", 0) + 1
            continue
        entry = (player.get("markets") or {}).get(stat)
        if not isinstance(entry, Mapping):
            counts["no_market_projection_rows"] += 1
            continue
        model_prob = prob_over(entry, line)
        if model_prob is None:
            counts["no_probability_rows"] += 1
            continue
        stale = index.week != game_week
        projection: dict[str, Any] = {
            # The projected STAT (its mean), for the display column; never
            # interchangeable with the probability below.
            "projected": _as_float(entry.get("mean")),
            "side": "over",
            "basis": "ncaaf_prop_model_probability",
            "source": PROJECTION_SOURCE,
            "distribution": entry.get("dist"),
            "projected_sd": _as_float(entry.get("sd")),
            "dispersion": _as_float(entry.get("dispersion")),
            "season_mean": _as_float(entry.get("season_mean")),
            "sample_games": entry.get("season_games"),
            "prior_source": entry.get("prior_source"),
            "player_team": player.get("team"),
            "artifact_season": index.season,
            "artifact_week": index.week,
            "game_week": game_week,
            "week_basis": week_basis,
            # A projection built before the game's own week (its week's file is
            # not on disk) is still leak-free but misses the weeks in between;
            # said on the row rather than inferred.
            "stale_week": stale,
            "generated_at": index.generated_at,
        }
        # Sets `model_prob_over`, `market_fair_prob_over` and
        # `edge_vs_market_pct` -- or a named `edge_unavailable_reason`, applying
        # the live-row suppression (`live_edge_policy.live_edge_unavailable_reason`)
        # every other sport's join goes through. Reused, not a new de-vig.
        _attach_sim_probability_edge(projection, row=row, model_prob=model_prob)
        row["projection"] = refuse_published_certainty(projection)
        counts["rows_with_projection"] += 1
        if stale:
            counts["stale_week_rows"] += 1
        key = f"{index.season}_wk{index.week}"
        artifact_weeks[key] = artifact_weeks.get(key, 0) + 1

    coverage: dict[str, Any] = {"supported": True, **counts}
    if artifact_weeks:
        coverage["artifact_weeks"] = artifact_weeks
    if unsupported:
        coverage["unsupported_markets"] = dict(sorted(unsupported.items(), key=lambda kv: -kv[1])[:8])
    if counts["rows_considered"]:
        coverage["pct_projected"] = round(counts["rows_with_projection"] / counts["rows_considered"] * 100.0, 1)
    return coverage
