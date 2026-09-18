"""Leak-free AS-OF backtest: does a season-to-date rating blend beat the NCAAF
generator's static prior-season SP+ on game margin?

Lane `ncaaf-sim-inseason-ratings` (2026-09-18). PRE-REGISTERED DECISION RULE:
the blend ships only if margin dMAE (candidate - baseline) on HELD-OUT data has
a 95% bootstrap-over-games CI entirely below 0.

WHAT IS COMPARED, per game in week N (regular season, FBS vs FBS, both teams
rated by the prior-season SP+):

  BASELINE   prior-season FINAL SP+ (season S-1) -- the established leak-free
             stand-in for the generator's rating (`[ncaaf-ratings-leak]`:
             CFBD's SP+ for a completed season is END-of-season, so the
             same-season number would contain the game).
  CANDIDATE  that prior blended with season-S information from weeks < N ONLY:
             opponent-adjusted scoring (a ridge SRS on `games_<S>` actuals)
             and/or opponent-adjusted per-play PPA (from `plays_<S>_wkNN`,
             garbage time removed), put on the SP+ points scale. Two shapes:
               ridge_*  prior-centred ridge: each team's offense/defense is
                        shrunk toward its prior with strength lambda (in games),
                        so the current-season weight is ~n/(n+lambda);
               blend_*  explicit: (k*prior + n*current)/(n+k), `current` a
                        lightly-regularised season-to-date SRS/PPA rating.
             `ridge_pts_window` uses only the last L weeks (the last-N variant).

Both are turned into a margin by the GENERATOR ITSELF: the rating index goes
through `sp_league_means` + `sp_offense_defense_rating` (the generator's own
centring and `SP_RATING_SCALE`) and then the SmartSim2 engine. Two engines:

  mc         `build_projection` -- the generator's Monte Carlo, `--seeds` seeds
             per game (300 = production), common random numbers across
             baseline and candidate. The DECISION is taken on this.
  surrogate  the engine's expected score as a smooth function of
             (offense rating, opposing defense rating), fitted to a grid of
             engine runs and validated against `mc` on real games. Used for
             TUNING only (a grid of ~140 settings x 2 seasons of full Monte
             Carlo is ~20 CPU-hours); every tuned number is labelled with it.

Tuning (lambda/k, alpha, L) happens on `--tune-seasons` only; `--eval-season`
is touched once, by the selected setting. The market comparison uses the
closing spread (median of books, CFBD `/lines`), `market margin = -spread`.

Usage:
  python scripts/backtest_ncaaf_inseason_blend.py \
      --data-root <repo>/data/ncaaf_source --cache-dir <dir with the fetched
      sp_ratings_2022.json / cfbd_lines_2023.json / cfbd_lines_2024.json> \
      --calibration-dir <repo>/data/calibration --out result.json
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
import os
import statistics
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# ONE BLAS thread. The linear algebra here is thousands of ~280x280 solves; a
# threaded BLAS spreads each across every core for no gain and, measured
# 2026-09-18, burned ~5 cores for a single-process tuning pass on a shared box.
for _var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

import numpy as np

DEFAULT_DATA_ROOT = REPO_ROOT / "data" / "ncaaf_source"
EVAL_WEEKS = tuple(range(3, 16))
WEEK_BUCKETS = (("3-5", 3, 5), ("6-9", 6, 9), ("10-15", 10, 15))
# CFBD's garbage-time rule (score margin at the snap, by quarter). Overtime is
# never garbage time.
GARBAGE_MARGIN_BY_PERIOD = {1: 43, 2: 37, 3: 27, 4: 21}
OTHER = "__other__"  # every team without a prior SP+ rating (FCS, FBS newcomers)
GRID = tuple(round(-2.6 + 0.2 * i, 3) for i in range(27))
LAMBDAS = (1.0, 2.0, 3.0, 4.0, 6.0, 8.0, 12.0, 16.0, 24.0, 32.0, 48.0)
ALPHAS = (0.25, 0.5, 1.0, 2.0, 4.0)
WINDOWS = (3, 4, 5, 6)
CURRENT_LAMBDA = 1.0  # the light ridge behind blend_* "current" ratings
OTHER_LAMBDA = 0.01

_GEN = None


def gen():
    """The generator module, imported lazily so `--calibration-dir` can set
    SYNDICATE_CALIBRATION_PROFILE_DIR before the engine's profile loads."""
    global _GEN
    if _GEN is None:
        import scripts.generate_smartsim2_ncaaf_projections as module

        _GEN = module
    return _GEN


def norm(name: str) -> str:
    return gen().norm(name)


# ---------------------------------------------------------------------------
# DATA
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Game:
    game_id: int
    season: int
    week: int
    home: str
    away: str
    home_points: float
    away_points: float
    neutral: bool
    home_fbs: bool
    away_fbs: bool

    @property
    def margin(self) -> float:
        return self.home_points - self.away_points


def _read_json_gz(path: Path):
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def load_games(ht_dir: Path, season: int) -> list[Game]:
    """Completed regular-season games with a final score, from `games_<S>`."""
    out: list[Game] = []
    for row in _read_json_gz(ht_dir / f"games_{season}.json.gz"):
        if str(row.get("seasonType") or "regular") != "regular":
            continue
        if row.get("homePoints") is None or row.get("awayPoints") is None:
            continue
        out.append(Game(
            game_id=int(row["id"]), season=int(season), week=int(row.get("week") or 0),
            home=norm(row.get("homeTeam") or ""), away=norm(row.get("awayTeam") or ""),
            home_points=float(row["homePoints"]), away_points=float(row["awayPoints"]),
            neutral=bool(row.get("neutralSite")),
            home_fbs=row.get("homeClassification") == "fbs",
            away_fbs=row.get("awayClassification") == "fbs",
        ))
    return out


def load_prior_sp(ht_dir: Path, cache_dir: Path | None, season: int) -> dict[str, tuple[float, float]]:
    """Season S-1 FINAL SP+ -- the leak-free preseason rating for season S."""
    name = f"sp_ratings_{season - 1}.json"
    for base in (ht_dir, cache_dir):
        if base is not None and (base / name).exists():
            return gen()._read_sp_cache(base / name)
    return {}


def is_garbage_time(play: dict) -> bool:
    try:
        period = int(play.get("period") or 0)
        margin = abs(float(play.get("offenseScore") or 0) - float(play.get("defenseScore") or 0))
    except (TypeError, ValueError):
        return False
    threshold = GARBAGE_MARGIN_BY_PERIOD.get(period)
    return threshold is not None and margin > threshold


def load_game_ppa(ht_dir: Path, season: int) -> dict[tuple[int, str], tuple[float, int]]:
    """`(game_id, offense) -> (mean PPA per play, plays)`, garbage time removed."""
    sums: dict[tuple[int, str], list[float]] = defaultdict(lambda: [0.0, 0])
    for week in range(0, 17):
        path = ht_dir / f"plays_{season}_wk{week:02d}.json.gz"
        if not path.exists():
            continue
        for play in _read_json_gz(path):
            ppa = play.get("ppa")
            if ppa is None or is_garbage_time(play):
                continue
            key = (int(play.get("gameId")), norm(play.get("offense") or ""))
            acc = sums[key]
            acc[0] += float(ppa)
            acc[1] += 1
    return {key: (acc[0] / acc[1], int(acc[1])) for key, acc in sums.items() if acc[1] > 0}


def game_ppa_from_cfbd_rows(rows: list) -> dict[tuple[int, str], tuple[float, int]]:
    """`/ppa/games` rows -> `(game_id, team) -> (offense.overall, 0)`.

    THIS IS THE PRODUCTION INPUT, so it is the default. The generator already
    fetches exactly these rows (`load_ppa_games_week`, `excludeGarbageTime=true`,
    `seasonType=regular`). The plays-derived alternative above is NOT the same
    number -- measured 2026-09-18 on 2025 week 5, 104 of 104 rows matched with
    r = 0.935 and a difference SD of 0.090 against a spread of 0.246 -- so a
    backtest on plays would measure an input production never sees. CFBD
    returns FBS teams' rows only; an FCS offense simply has no observation.
    """
    out: dict[tuple[int, str], tuple[float, int]] = {}
    for row in rows or []:
        if str(row.get("seasonType") or "regular") != "regular":
            continue
        value = (row.get("offense") or {}).get("overall")
        if value is None or row.get("gameId") is None:
            continue
        out[(int(row["gameId"]), norm(row.get("team") or ""))] = (float(value), 0)
    return out


def closing_margins_from_rows(rows: list) -> dict[int, float]:
    """`game_id -> market margin (home - away)` = -(median closing spread).

    CFBD `spread` is from the HOME side (negative = home favoured) and is the
    latest line each book reported, i.e. the close for a completed game.
    """
    out: dict[int, float] = {}
    for row in rows or []:
        spreads = [float(line["spread"]) for line in (row.get("lines") or [])
                   if isinstance(line, dict) and line.get("spread") is not None]
        if spreads and row.get("id") is not None:
            out[int(row["id"])] = -statistics.median(spreads)
    return out


def load_closing_margins(data_dir: Path, cache_dir: Path | None, season: int) -> dict[int, float]:
    rows: list = []
    if cache_dir is not None and (cache_dir / f"cfbd_lines_{season}.json").exists():
        rows = json.loads((cache_dir / f"cfbd_lines_{season}.json").read_text(encoding="utf-8"))
    else:
        for path in sorted(data_dir.glob("cfbd_lines_*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            rows.extend(r for r in payload if isinstance(r, dict) and r.get("season") == season)
    return closing_margins_from_rows(rows)


# ---------------------------------------------------------------------------
# RATINGS -- every function below sees only games with week < N
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Setting:
    family: str  # baseline | ridge_pts | ridge_ppa | ridge_combo | ridge_pts_window | blend_pts | blend_ppa
    lam: float = 0.0
    alpha: float = 0.0
    window: int = 0

    @property
    def label(self) -> str:
        if self.family == "baseline":
            return "baseline_prior_sp"
        if self.family == "control_scale":
            return f"control_scale[c={self.lam:g}]"
        parts = [self.family, f"k={self.lam:g}"]
        if self.family == "ridge_combo":
            parts.append(f"alpha={self.alpha:g}")
        if self.family == "ridge_pts_window":
            parts.append(f"L={self.window}")
        return "[".join([parts[0], ",".join(parts[1:])]) + "]"


def all_settings() -> list[Setting]:
    out = [Setting("baseline")]
    for lam in LAMBDAS:
        out += [Setting("ridge_pts", lam), Setting("ridge_ppa", lam),
                Setting("blend_pts", lam), Setting("blend_ppa", lam)]
        out += [Setting("ridge_combo", lam, alpha=a) for a in ALPHAS]
        out += [Setting("ridge_pts_window", lam, window=w) for w in WINDOWS]
    return out


# THE DISPERSION CONTROL. Never a candidate, never the primary. The engine
# amplifies a rating gap (measured: +1.0 engine offense -> +16.6 margin, i.e. a
# 10-point SP+ edge priced at ~17 points), so ANY candidate that happens to
# compress the ratings can beat the baseline on dispersion alone, carrying no
# in-season information at all. `control_scale[c]` is the static prior with
# its spread multiplied by c -- exactly `SP_RATING_SCALE = 10 / c` -- tuned on
# the same seasons. A candidate's gain over THIS is the in-season information.
CONTROL_SCALES = (0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0)


def control_settings() -> list[Setting]:
    return [Setting("control_scale", c) for c in CONTROL_SCALES]


@dataclass(frozen=True)
class Obs:
    kind: str  # "pts" | "ppa"
    week: int
    offense: str
    defense: str
    home: float  # 1.0 when the offense is the home side of a non-neutral game
    y: float


def build_observations(games: list[Game], ppa: dict, before_week: int, *, window: int = 0) -> list[Obs]:
    """One pts obs and (when plays exist) one ppa obs per team per game, weeks < N.

    `window` > 0 keeps only weeks >= N - window. THE WEEK FILTER IS THE LEAK
    BOUNDARY: `tests/test_backtest_ncaaf_inseason_blend.py` perturbs week-N
    results and asserts the ratings do not move.
    """
    low = before_week - window if window > 0 else -1
    out: list[Obs] = []
    for g in games:
        if not (low <= g.week < before_week):
            continue
        home_flag = 0.0 if g.neutral else 1.0
        out.append(Obs("pts", g.week, g.home, g.away, home_flag, g.home_points))
        out.append(Obs("pts", g.week, g.away, g.home, 0.0, g.away_points))
        for offense, defense, flag in ((g.home, g.away, home_flag), (g.away, g.home, 0.0)):
            value = ppa.get((g.game_id, offense))
            if value is not None:
                out.append(Obs("ppa", g.week, offense, defense, flag, value[0]))
    return out


def _team_ids(prior: dict) -> dict[str, int]:
    teams = sorted(prior)
    ids = {team: i for i, team in enumerate(teams)}
    ids[OTHER] = len(teams)
    return ids


_KINDS = ("pts", "ppa")


def normal_equations(obs: list[Obs], prior: dict, beta: float) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """Per observation kind, `(X'X, X'y)` over the fixed parameter layout
    `[o_0..o_T, d_0..d_T, mu_pts, h_pts, mu_ppa, h_ppa]` (T includes OTHER).

    Model per observation: y = mu_kind + h_kind*home + o[off] - d[def]. A PPA
    observation enters as `beta * ppa` -- beta converts a per-play PPA rating
    into SP+ points -- so o and d are in POINTS for both kinds, and a PPA row's
    residual is on the same scale as a points row's. (Entering it unscaled
    left it weighted ~1/beta^2 = 0.0003 against the prior, i.e. inert -- the
    first smoke run returned the prior unchanged.)
    """
    ids = _team_ids(prior)
    n_teams = len(ids)
    n_params = 2 * n_teams + 2 * len(_KINDS)
    out: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for k_pos, kind in enumerate(_KINDS):
        rows = [ob for ob in obs if ob.kind == kind]
        x = np.zeros((len(rows), n_params))
        y = np.zeros(len(rows))
        scale = 1.0 if kind == "pts" else float(beta)
        mu = 2 * n_teams + 2 * k_pos
        for r, ob in enumerate(rows):
            x[r, ids.get(ob.offense, ids[OTHER])] += 1.0
            x[r, n_teams + ids.get(ob.defense, ids[OTHER])] -= 1.0
            x[r, mu] = 1.0
            x[r, mu + 1] = ob.home
            y[r] = scale * ob.y
        out[kind] = (x.T @ x, x.T @ y)
    return out


def solve_ridge(
    equations: dict[str, tuple[np.ndarray, np.ndarray]],
    prior: dict[str, tuple[float, float]],
    *,
    lam: float,
    weights: dict[str, float],
    centre_on_prior: bool = True,
) -> dict[str, tuple[float, float]]:
    """Opponent-adjusted `{team: (o, d)}` in POINTS vs league average.

    Penalty lam*((o - o0)^2 + (d - d0)^2) per prior team, (o0, d0) its centred
    prior when `centre_on_prior` (so the current season carries weight ~n/(n+lam)
    against the prior), else 0 (a plain, lightly-ridged SRS). Unrated teams share
    one OTHER pair with a near-zero penalty; mu/h are effectively unpenalised.
    """
    ids = _team_ids(prior)
    n_teams = len(ids)
    n_params = 2 * n_teams + 2 * len(_KINDS)
    ata = np.zeros((n_params, n_params))
    atb = np.zeros(n_params)
    for kind, weight in weights.items():
        if weight > 0:
            ata += weight * equations[kind][0]
            atb += weight * equations[kind][1]
    mean_o = statistics.fmean(v[0] for v in prior.values())
    mean_d = statistics.fmean(v[1] for v in prior.values())
    target = np.zeros(n_params)
    penalty = np.full(n_params, 1e-6)
    for team, i in ids.items():
        if team == OTHER:
            penalty[i] = penalty[n_teams + i] = OTHER_LAMBDA
            continue
        penalty[i] = penalty[n_teams + i] = lam
        if centre_on_prior:
            target[i] = prior[team][0] - mean_o
            target[n_teams + i] = mean_d - prior[team][1]
    solution = np.linalg.solve(ata + np.diag(penalty), atb + penalty * target)
    return {team: (float(solution[i]), float(solution[n_teams + i])) for team, i in ids.items() if team != OTHER}


def fit_ridge(
    obs: list[Obs],
    prior: dict[str, tuple[float, float]],
    *,
    lam: float,
    weights: dict[str, float],
    beta: float = 1.0,
    centre_on_prior: bool = True,
) -> dict[str, tuple[float, float]]:
    """`solve_ridge` over freshly built normal equations."""
    return solve_ridge(normal_equations(obs, prior, beta), prior, lam=lam, weights=weights,
                       centre_on_prior=centre_on_prior)


def games_played(obs: list[Obs], kind: str) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for ob in obs:
        if ob.kind == kind:
            counts[ob.offense] += 1
    return counts


def to_sp_index(prior: dict, adjusted: dict[str, tuple[float, float]]) -> dict[str, tuple[float, float]]:
    """(o, d) points-vs-average -> SP+ shape (offense scored, defense ALLOWED)."""
    mean_o = statistics.fmean(v[0] for v in prior.values())
    mean_d = statistics.fmean(v[1] for v in prior.values())
    return {team: (mean_o + o, mean_d - d) for team, (o, d) in adjusted.items()}


def ratings_asof(
    setting: Setting,
    prior: dict[str, tuple[float, float]],
    games: list[Game],
    ppa: dict,
    week: int,
    beta: float,
    cache: dict | None = None,
) -> dict[str, tuple[float, float]]:
    """The SP+-shaped index this setting would hand the generator for week N.

    `cache` (one dict per season) memoises the observations and normal
    equations per (week, window); they do not depend on lambda/alpha.
    """
    if setting.family == "baseline":
        return dict(prior)
    if setting.family == "control_scale":
        mean_o = statistics.fmean(v[0] for v in prior.values())
        mean_d = statistics.fmean(v[1] for v in prior.values())
        c = setting.lam
        return {t: (mean_o + c * (o - mean_o), mean_d + c * (d - mean_d)) for t, (o, d) in prior.items()}
    key = (week, setting.window)
    if cache is not None and key in cache:
        obs, equations = cache[key]
    else:
        obs = build_observations(games, ppa, week, window=setting.window)
        equations = normal_equations(obs, prior, beta)
        if cache is not None:
            cache[key] = (obs, equations)
    if setting.family.startswith("ridge_"):
        weights = {
            "ridge_pts": {"pts": 1.0},
            "ridge_pts_window": {"pts": 1.0},
            "ridge_ppa": {"ppa": 1.0},
            "ridge_combo": {"pts": 1.0, "ppa": setting.alpha},
        }[setting.family]
        return to_sp_index(prior, solve_ridge(equations, prior, lam=setting.lam, weights=weights))
    kind = "pts" if setting.family == "blend_pts" else "ppa"
    current = solve_ridge(equations, prior, lam=CURRENT_LAMBDA, weights={kind: 1.0}, centre_on_prior=False)
    counts = games_played(obs, kind)
    mean_o = statistics.fmean(v[0] for v in prior.values())
    mean_d = statistics.fmean(v[1] for v in prior.values())
    blended = {}
    for team, (off, dfn) in prior.items():
        n = counts.get(team, 0)
        w = n / (n + setting.lam) if n > 0 else 0.0
        c_o, c_d = current.get(team, (0.0, 0.0))
        p_o, p_d = off - mean_o, mean_d - dfn
        blended[team] = ((1 - w) * p_o + w * c_o, (1 - w) * p_d + w * c_d)
    return to_sp_index(prior, blended)


def fit_ppa_scale(final_sp_of_that_season: dict, games: list[Game], ppa: dict) -> float:
    """PPA-rating -> SP+ points slope, from ONE full season's data.

    Regress that season's FINAL SP+ components (centred; offense and defense
    stacked) on its full-season opponent-adjusted PPA ratings, through the
    origin. Called with season S-1 for target season S, so the evaluation
    season never informs its own scale. One slope, not two: the separate fits
    were 62.8/64.1 (2023) and 60.0/67.6 (2024), and a single scale keeps a PPA
    row's residual on one points scale for both sides.
    """
    # Near-unregularised: a full season identifies every FBS team, and a ridge
    # here would shrink the PPA ratings and inflate the slope by the shrinkage
    # (lam=1 read 66.5 against a true 60 on synthetic data).
    obs = build_observations(games, ppa, 99)
    adjusted = fit_ridge(obs, final_sp_of_that_season, lam=1e-3, weights={"ppa": 1.0},
                         beta=1.0, centre_on_prior=False)
    mean_o = statistics.fmean(v[0] for v in final_sp_of_that_season.values())
    mean_d = statistics.fmean(v[1] for v in final_sp_of_that_season.values())
    num = den = 0.0
    for team, (a_o, a_d) in adjusted.items():
        off, dfn = final_sp_of_that_season[team]
        num += (off - mean_o) * a_o + (mean_d - dfn) * a_d
        den += a_o * a_o + a_d * a_d
    return num / den if den else 1.0


# ---------------------------------------------------------------------------
# ENGINE -- the generator's own centring + SmartSim2
# ---------------------------------------------------------------------------


def engine_inputs(index: dict[str, tuple[float, float]], home: str, away: str) -> tuple[float, float, float, float] | None:
    g = gen()
    means = g.sp_league_means(index)
    h = g.sp_offense_defense_rating(home, index, means)
    a = g.sp_offense_defense_rating(away, index, means)
    if h is None or a is None:
        return None
    return h[0], h[1], a[0], a[1]


def _init_worker(calibration_dir: str | None) -> None:
    if calibration_dir:
        os.environ["SYNDICATE_CALIBRATION_PROFILE_DIR"] = calibration_dir
    gen()


def _grid_task(args: tuple[float, float, int]) -> tuple[float, float, float, float]:
    """Engine scores with offense x facing defense y on BOTH sides."""
    x, y, seeds = args
    from syndicate.features.football.sim_engine.smartsim2.contracts import SmartSim2SimulationInput
    from syndicate.features.football.sim_engine.smartsim2.game_simulator import simulate_game
    from syndicate.features.football.sim_engine.smartsim2.ncaaf_calibration_profile import NCAAF_CALIBRATION_PROFILE

    home = away = 0.0
    for seed in range(1, seeds + 1):
        out = simulate_game(SmartSim2SimulationInput(
            home_team="H", away_team="A", seed=seed,
            home_offense_rating=x, home_defense_rating=y,
            away_offense_rating=x, away_defense_rating=y,
        ), profile=NCAAF_CALIBRATION_PROFILE)
        home += out.final_score["home"]
        away += out.final_score["away"]
    return x, y, home / seeds, away / seeds


def _mc_task(args: tuple) -> float:
    """One game through the generator's `build_projection` (its own seeds 1..S)."""
    home, away, home_sp, away_sp, means, seeds = args
    projection = gen().build_projection(
        season=0, week=0, home_team=home, away_team=away, game_id="backtest",
        ppa_index={}, rating_source="backtest", seeds=seeds,
        sp_index={home: home_sp, away: away_sp}, sp_means=means,
    )
    return float(projection.margin_mean)


def _poly_basis(x: np.ndarray, y: np.ndarray, degree: int = 5) -> np.ndarray:
    return np.column_stack([x ** i * y ** j for i in range(degree + 1) for j in range(degree + 1)])


class Surrogate:
    """Engine margin ~ H(ho, ad) - A(ao, hd): smooth fits over a run grid."""

    def __init__(self, grid_rows: list[tuple[float, float, float, float]]):
        arr = np.array(grid_rows, dtype=float)
        self.lo, self.hi = float(arr[:, 0].min()), float(arr[:, 0].max())
        basis = _poly_basis(arr[:, 0], arr[:, 1])
        self.home_coef, *_ = np.linalg.lstsq(basis, arr[:, 2], rcond=None)
        self.away_coef, *_ = np.linalg.lstsq(basis, arr[:, 3], rcond=None)
        self.fit_rmse = (
            float(np.sqrt(np.mean((basis @ self.home_coef - arr[:, 2]) ** 2))),
            float(np.sqrt(np.mean((basis @ self.away_coef - arr[:, 3]) ** 2))),
        )
        self.clamped = 0

    def _clip(self, value: float) -> float:
        if value < self.lo or value > self.hi:
            self.clamped += 1
        return min(self.hi, max(self.lo, value))

    def margin(self, ho: float, hd: float, ao: float, ad: float) -> float:
        return float(self.margins(np.array([[ho, hd, ao, ad]]))[0])

    def margins(self, inputs: np.ndarray) -> np.ndarray:
        """Vectorised: rows of (home_off, home_def, away_off, away_def)."""
        inputs = np.asarray(inputs, dtype=float)
        self.clamped += int(np.sum((inputs < self.lo) | (inputs > self.hi)))
        x = np.clip(inputs, self.lo, self.hi)
        home = _poly_basis(x[:, 0], x[:, 3]) @ self.home_coef
        away = _poly_basis(x[:, 2], x[:, 1]) @ self.away_coef
        return home - away


def build_surrogate_grid(seeds: int, workers: int, calibration_dir: str | None, cache_path: Path | None, profile_version: str):
    if cache_path is not None and cache_path.exists():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        if cached.get("seeds") == seeds and cached.get("grid") == list(GRID) and cached.get("profile_version") == profile_version:
            return [tuple(r) for r in cached["rows"]]
    tasks = [(x, y, seeds) for x in GRID for y in GRID]
    rows = _run_pool(_grid_task, tasks, workers, calibration_dir)
    if cache_path is not None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps({"seeds": seeds, "grid": list(GRID), "profile_version": profile_version,
                                          "rows": [list(r) for r in rows]}), encoding="utf-8")
    return rows


def _run_pool(func, tasks: list, workers: int, calibration_dir: str | None) -> list:
    if workers <= 1:
        _init_worker(calibration_dir)
        return [func(t) for t in tasks]
    import multiprocessing as mp

    with mp.get_context("spawn").Pool(workers, initializer=_init_worker, initargs=(calibration_dir,)) as pool:
        return pool.map(func, tasks, chunksize=max(1, len(tasks) // (workers * 8)))


# ---------------------------------------------------------------------------
# SCORING
# ---------------------------------------------------------------------------


def paired_delta_ci(cand: np.ndarray, base: np.ndarray, actual: np.ndarray, *, reps: int, seed: int) -> dict:
    """Mean paired |err| difference with a bootstrap-over-games 95% CI."""
    diff = np.abs(cand - actual) - np.abs(base - actual)
    n = len(diff)
    if n == 0:
        return {"n": 0}
    rng = np.random.default_rng(seed)
    means = diff[rng.integers(0, n, size=(reps, n))].mean(axis=1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return {"n": int(n), "delta_mae": float(diff.mean()), "ci95": [float(lo), float(hi)]}


def market_regression(model: np.ndarray, market: np.ndarray, actual: np.ndarray, *, reps: int, seed: int) -> dict:
    """`actual = a + b*market + w*(model - market)`, with bootstrap CIs."""
    n = len(actual)
    if n < 10:
        return {"n": int(n)}
    x = np.column_stack([np.ones(n), market, model - market])
    coef, *_ = np.linalg.lstsq(x, actual, rcond=None)
    rng = np.random.default_rng(seed)
    boots = []
    for _ in range(reps):
        idx = rng.integers(0, n, size=n)
        c, *_ = np.linalg.lstsq(x[idx], actual[idx], rcond=None)
        boots.append(c)
    boots = np.array(boots)
    return {
        "n": int(n),
        "b": float(coef[1]), "b_ci95": [float(v) for v in np.percentile(boots[:, 1], [2.5, 97.5])],
        "w": float(coef[2]), "w_ci95": [float(v) for v in np.percentile(boots[:, 2], [2.5, 97.5])],
        "model_mae": float(np.mean(np.abs(model - actual))),
        "market_mae": float(np.mean(np.abs(market - actual))),
    }


# ---------------------------------------------------------------------------
# DRIVER
# ---------------------------------------------------------------------------


@dataclass
class SeasonData:
    season: int
    games: list[Game]
    ppa: dict
    prior: dict
    market: dict[int, float]
    beta: float
    beta_source: str
    eq_cache: dict = field(default_factory=dict)
    index_cache: dict = field(default_factory=dict)

    def ratings(self, setting: Setting, week: int) -> dict[str, tuple[float, float]]:
        key = (setting, week)
        if key not in self.index_cache:
            self.index_cache[key] = ratings_asof(setting, self.prior, self.games, self.ppa, week, self.beta,
                                                 cache=self.eq_cache)
        return self.index_cache[key]

    def eval_games(self) -> list[Game]:
        return [g for g in self.games
                if g.week in EVAL_WEEKS and g.home_fbs and g.away_fbs
                and g.home in self.prior and g.away in self.prior]


def coverage(data_root: Path, cache_dir: Path | None, seasons: list[int]) -> dict:
    """Per data family: which season/weeks exist, and the game-level intersection."""
    ht, dd = data_root / "historical_truth", data_root / "data"
    report: dict = {}
    for season in seasons:
        games = load_games(ht, season) if (ht / f"games_{season}.json.gz").exists() else []
        fbs = [g for g in games if g.home_fbs and g.away_fbs and g.week in EVAL_WEEKS]
        prior = load_prior_sp(ht, cache_dir, season)
        market = load_closing_margins(dd, cache_dir, season)
        play_weeks = sorted(w for w in range(0, 17) if (ht / f"plays_{season}_wk{w:02d}.json.gz").exists())
        rated = [g for g in fbs if g.home in prior and g.away in prior]
        with_line = [g for g in rated if g.game_id in market]
        report[str(season)] = {
            "games_file": bool(games), "games_completed": len(games),
            "fbs_vs_fbs_wk3_15": len(fbs),
            "play_weeks": play_weeks,
            "prior_sp_season": season - 1, "prior_sp_teams": len(prior),
            "lines_games": len(market),
            "lines_weeks": sorted({g.week for g in games if g.game_id in market}),
            "intersection_rated_wk3_15": len(rated),
            "intersection_rated_with_close_wk3_15": len(with_line),
        }
    return report


def load_season(data_root: Path, cache_dir: Path | None, season: int, prev_for_beta: "SeasonData | None",
                ppa_source: str = "cfbd") -> SeasonData:
    ht, dd = data_root / "historical_truth", data_root / "data"
    games = load_games(ht, season)
    if ppa_source == "cfbd":
        path = (cache_dir / f"cfbd_ppa_games_{season}.json") if cache_dir is not None else None
        if path is None or not path.exists():
            raise SystemExit(f"--ppa-source cfbd needs {path} (CFBD /ppa/games?year={season}&seasonType=regular"
                             "&excludeGarbageTime=true, one call per season)")
        ppa = game_ppa_from_cfbd_rows(json.loads(path.read_text(encoding="utf-8")))
    else:
        ppa = load_game_ppa(ht, season)
    prior = load_prior_sp(ht, cache_dir, season)
    market = load_closing_margins(dd, cache_dir, season)
    # PPA scale from season S-1 (its final SP+ is season S's prior). When S-1's
    # plays are not held, fit on S itself -- only ever for a TUNING season, and
    # reported as such.
    if prev_for_beta is not None:
        beta = fit_ppa_scale(prior, prev_for_beta.games, prev_for_beta.ppa)
        source = f"fit_on_{season - 1}"
    else:
        own_final = load_prior_sp(ht, cache_dir, season + 1)
        beta = fit_ppa_scale(own_final, games, ppa)
        source = f"fit_on_{season}_IN_SAMPLE_tuning_only"
    return SeasonData(season, games, ppa, prior, market, beta, source)


def project_surrogate(sd: SeasonData, setting: Setting, surrogate: Surrogate, games: list[Game] | None = None) -> dict[int, float]:
    by_week: dict[int, list[Game]] = defaultdict(list)
    for g in (sd.eval_games() if games is None else games):
        by_week[g.week].append(g)
    ids, rows = [], []
    for week, week_games in by_week.items():
        index = sd.ratings(setting, week)
        means = gen().sp_league_means(index)  # once per week, not per game
        for g in week_games:
            h = gen().sp_offense_defense_rating(g.home, index, means)
            a = gen().sp_offense_defense_rating(g.away, index, means)
            if h is not None and a is not None:
                ids.append(g.game_id)
                rows.append((h[0], h[1], a[0], a[1]))
    if not rows:
        return {}
    return dict(zip(ids, (float(m) for m in surrogate.margins(np.array(rows)))))


def project_mc(sd: SeasonData, setting: Setting, seeds: int, workers: int, calibration_dir: str | None,
               games: list[Game] | None = None) -> dict[int, float]:
    tasks, ids, means_cache = [], [], {}
    for g in (sd.eval_games() if games is None else games):
        index = sd.ratings(setting, g.week)
        if g.week not in means_cache:
            means_cache[g.week] = gen().sp_league_means(index)
        tasks.append((g.home, g.away, index[g.home], index[g.away], means_cache[g.week], seeds))
        ids.append(g.game_id)
    margins = _run_pool(_mc_task, tasks, workers, calibration_dir)
    return dict(zip(ids, margins))


def score(sd: SeasonData, proj: dict[int, float], base: dict[int, float], *, reps: int, seed: int) -> dict:
    games = [g for g in sd.eval_games() if g.game_id in proj and g.game_id in base]
    actual = np.array([g.margin for g in games])
    cand = np.array([proj[g.game_id] for g in games])
    bl = np.array([base[g.game_id] for g in games])
    result = {
        "n": len(games),
        "mae": float(np.mean(np.abs(cand - actual))) if games else None,
        "vs_baseline": paired_delta_ci(cand, bl, actual, reps=reps, seed=seed),
        "by_bucket": {},
    }
    for name, lo, hi in WEEK_BUCKETS:
        mask = np.array([lo <= g.week <= hi for g in games])
        result["by_bucket"][name] = paired_delta_ci(cand[mask], bl[mask], actual[mask], reps=reps, seed=seed)
        result["by_bucket"][name]["mae"] = float(np.mean(np.abs(cand[mask] - actual[mask]))) if mask.any() else None
    with_line = [i for i, g in enumerate(games) if g.game_id in sd.market]
    if with_line:
        market = np.array([sd.market[games[i].game_id] for i in with_line])
        result["vs_market"] = market_regression(cand[with_line], market, actual[with_line], reps=min(reps, 2000), seed=seed)
        result["vs_market"]["delta_mae_vs_market"] = paired_delta_ci(cand[with_line], market, actual[with_line], reps=reps, seed=seed)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--cache-dir", type=Path, default=None)
    parser.add_argument("--calibration-dir", type=str, default=None)
    parser.add_argument("--tune-seasons", type=str, default="2023,2024")
    parser.add_argument("--eval-season", type=int, default=2025)
    parser.add_argument("--seeds", type=int, default=300, help="Monte Carlo seeds per game (production: 300)")
    parser.add_argument("--grid-seeds", type=int, default=200)
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    parser.add_argument("--mc", choices=("primary", "families", "none"), default="primary")
    parser.add_argument("--validate-games", type=int, default=120)
    parser.add_argument("--bootstrap", type=int, default=10000)
    parser.add_argument("--ppa-source", choices=("cfbd", "plays"), default="cfbd",
                        help="cfbd = the /ppa/games rows production reads (default); plays = derived here")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.calibration_dir:
        os.environ["SYNDICATE_CALIBRATION_PROFILE_DIR"] = args.calibration_dir
    t0 = time.time()
    g = gen()
    from syndicate.features.football.sim_engine.smartsim2.ncaaf_calibration_profile import NCAAF_CALIBRATION_PROFILE_METADATA

    profile_version = str(NCAAF_CALIBRATION_PROFILE_METADATA.get("version") or NCAAF_CALIBRATION_PROFILE_METADATA.get("source"))
    tune = [int(s) for s in args.tune_seasons.split(",") if s.strip()]
    seasons = sorted(set(tune + [args.eval_season]))
    report: dict = {"profile_version": profile_version, "sp_rating_scale": g.SP_RATING_SCALE,
                    "ppa_source": args.ppa_source,
                    "coverage": coverage(args.data_root, args.cache_dir, seasons)}
    print(json.dumps({"coverage": report["coverage"]}, indent=1), flush=True)

    data: dict[int, SeasonData] = {}
    for season in seasons:
        data[season] = load_season(args.data_root, args.cache_dir, season, data.get(season - 1), args.ppa_source)
        print(f"LOADED season={season} games={len(data[season].games)} eval_games={len(data[season].eval_games())} "
              f"ppa_rows={len(data[season].ppa)} beta={data[season].beta:.2f} "
              f"({data[season].beta_source})", flush=True)
    report["ppa_scale"] = {str(s): {"beta": d.beta, "source": d.beta_source} for s, d in data.items()}

    grid_rows = build_surrogate_grid(args.grid_seeds, args.workers, args.calibration_dir,
                                     (args.cache_dir / f"surrogate_grid_{profile_version}_{args.grid_seeds}.json") if args.cache_dir else None,
                                     profile_version)
    surrogate = Surrogate(grid_rows)
    report["surrogate"] = {"grid": [GRID[0], GRID[-1], len(GRID)], "grid_seeds": args.grid_seeds,
                           "fit_rmse_home_away": list(surrogate.fit_rmse)}
    print(f"SURROGATE grid={len(grid_rows)} fit_rmse={surrogate.fit_rmse} ({time.time() - t0:.0f}s)", flush=True)

    # --- tuning (surrogate), tune seasons only -----------------------------
    baseline = Setting("baseline")
    base_proj = {s: project_surrogate(data[s], baseline, surrogate) for s in tune}

    def tune_over(settings: list[Setting]) -> list[tuple[float, Setting]]:
        scored = []
        for setting in settings:
            errs, n = 0.0, 0
            for s in tune:
                proj = project_surrogate(data[s], setting, surrogate)
                for game in data[s].eval_games():
                    if game.game_id in proj:
                        errs += abs(proj[game.game_id] - game.margin)
                        n += 1
            scored.append((errs / n, setting))
        return sorted(scored, key=lambda item: item[0])

    tuning = tune_over(all_settings()[1:])
    controls = tune_over(control_settings())
    print(f"TUNED {len(tuning)} settings + {len(controls)} controls ({time.time() - t0:.0f}s)", flush=True)
    base_err = statistics.fmean(abs(base_proj[s][x.game_id] - x.margin) for s in tune for x in data[s].eval_games()
                                if x.game_id in base_proj[s])
    primary = tuning[0][1]
    control = controls[0][1]
    family_best: dict[str, Setting] = {}
    for _, setting in tuning:
        family_best.setdefault(setting.family, setting)
    report["tuning"] = {
        "seasons": tune, "engine": "surrogate", "baseline_mae": base_err,
        "top10": [{"setting": s.label, "mae": e} for e, s in tuning[:10]],
        "family_best": {f: {"setting": s.label, "mae": next(e for e, t in tuning if t == s)} for f, s in family_best.items()},
        "primary": primary.label,
        "controls": [{"setting": s.label, "mae": e} for e, s in controls],
        "control_best": control.label,
    }
    print(f"TUNING baseline_mae={base_err:.3f} primary={primary.label} mae={tuning[0][0]:.3f} "
          f"control_best={control.label} mae={controls[0][0]:.3f}", flush=True)
    for f, s in family_best.items():
        print(f"  family_best {f}: {s.label} mae={next(e for e, t in tuning if t == s):.3f}", flush=True)
    for s in tune:
        report.setdefault("tune_season_scores_surrogate", {})[str(s)] = {
            "primary": score(data[s], project_surrogate(data[s], primary, surrogate), base_proj[s],
                             reps=2000, seed=s)}

    # --- surrogate validation against the real Monte Carlo ----------------
    # On a TUNING season: the surrogate's job is tuning, so that is where its
    # error matters, and the held-out season stays untouched until evaluation.
    ev = data[args.eval_season]
    if args.validate_games > 0:
        sample = data[tune[-1]]
        pool_games = sample.eval_games()
        games_v = pool_games[:: max(1, len(pool_games) // args.validate_games)][: args.validate_games]
        val = {}
        for label, setting in (("baseline", baseline), ("primary", primary)):
            mc_map = project_mc(sample, setting, args.seeds, args.workers, args.calibration_dir, games_v)
            sur_map = project_surrogate(sample, setting, surrogate, games_v)
            mc = np.array([mc_map[x.game_id] for x in games_v])
            sur = np.array([sur_map[x.game_id] for x in games_v])
            val[label] = {"n": len(games_v), "mean_diff": float(np.mean(sur - mc)), "sd_diff": float(np.std(sur - mc)),
                          "corr": float(np.corrcoef(sur, mc)[0, 1]), "mc_sd": float(np.std(mc))}
        report["surrogate_validation"] = {"season": sample.season, "seeds": args.seeds, **val}
        print(f"SURROGATE_VALIDATION {json.dumps(report['surrogate_validation'])} ({time.time() - t0:.0f}s)", flush=True)

    # --- evaluation: held-out season -----------------------------------------
    eval_settings = [primary] + [s for f, s in sorted(family_best.items()) if s != primary]
    ev_games = ev.eval_games()

    def dispersion(proj: dict[int, float]) -> dict:
        vals = [proj[x.game_id] for x in ev_games if x.game_id in proj]
        mkt = [ev.market[x.game_id] for x in ev_games if x.game_id in proj and x.game_id in ev.market]
        return {"model_sd": float(np.std(vals)) if vals else None, "market_sd": float(np.std(mkt)) if mkt else None,
                "actual_sd": float(np.std([x.margin for x in ev_games]))}

    def evaluate(engine: str, project) -> dict:
        # Baseline, then the candidates, THEN the control: the decision rests on
        # the first two, and the MC cache persists each as it lands.
        base = project(baseline)
        out = {"baseline": {**score(ev, base, base, reps=args.bootstrap, seed=1), "dispersion": dispersion(base)}}
        projections = {}
        for setting in ([primary] if engine == "mc" and args.mc == "primary" else eval_settings):
            projections[setting] = project(setting)
            print(f"{engine.upper()} {setting.label} done ({time.time() - t0:.0f}s)", flush=True)
        ctrl = project(control)
        out[control.label] = {**score(ev, ctrl, base, reps=args.bootstrap, seed=3), "dispersion": dispersion(ctrl)}
        for setting, proj in projections.items():
            out[setting.label] = {**score(ev, proj, base, reps=args.bootstrap, seed=2), "dispersion": dispersion(proj),
                                  # THE INFORMATION TEST: the same candidate against the
                                  # best re-scaled static prior, not the unscaled one.
                                  "vs_control": score(ev, proj, ctrl, reps=args.bootstrap, seed=4)["vs_baseline"]}
        return out

    report["eval_surrogate"] = evaluate("surrogate", lambda s: project_surrogate(ev, s, surrogate))
    report["surrogate"]["clamped_inputs"] = surrogate.clamped
    if args.mc != "none":
        # MC results are cached per (profile, season, seeds, setting), so a
        # re-run with more settings does not repeat the hour already spent.
        cache_path = (args.cache_dir / f"mc_cache_{profile_version}_{args.ppa_source}_{ev.season}_{args.seeds}.json") if args.cache_dir else None
        mc_cache: dict = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path and cache_path.exists() else {}

        def project_mc_cached(setting: Setting) -> dict[int, float]:
            hit = mc_cache.get(setting.label)
            if hit and all(str(x.game_id) in hit for x in ev_games):
                return {int(k): float(v) for k, v in hit.items()}
            proj = project_mc(ev, setting, args.seeds, args.workers, args.calibration_dir)
            mc_cache[setting.label] = {str(k): v for k, v in proj.items()}
            if cache_path:
                cache_path.write_text(json.dumps(mc_cache), encoding="utf-8")
            return proj

        report["eval_mc"] = {"seeds": args.seeds, **evaluate("mc", project_mc_cached)}
        report["eval_rows"] = [
            {"game_id": x.game_id, "week": x.week, "home": x.home, "away": x.away, "actual": x.margin,
             "market": ev.market.get(x.game_id),
             **{label: mc_cache[label][str(x.game_id)] for label in mc_cache if str(x.game_id) in mc_cache[label]}}
            for x in ev_games
        ]
        verdict = report["eval_mc"][primary.label]["vs_baseline"]
        info = report["eval_mc"][primary.label]["vs_control"]
    else:
        verdict = report["eval_surrogate"][primary.label]["vs_baseline"]
        info = report["eval_surrogate"][primary.label]["vs_control"]
    ships = bool(verdict.get("ci95") and verdict["ci95"][1] < 0)
    report["decision"] = {
        "primary": primary.label, "engine": "mc" if args.mc != "none" else "surrogate",
        "delta_mae": verdict.get("delta_mae"), "ci95": verdict.get("ci95"), "n": verdict.get("n"),
        "rule": "ships only if the held-out margin dMAE CI is entirely below 0",
        "ships": ships,
        "control": control.label,
        "vs_control_delta_mae": info.get("delta_mae"), "vs_control_ci95": info.get("ci95"),
    }
    report["elapsed_seconds"] = round(time.time() - t0, 1)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    print(f"DECISION {json.dumps(report['decision'])}", flush=True)
    print(f"wrote {args.out} ({report['elapsed_seconds']}s)", flush=True)


if __name__ == "__main__":
    main()
