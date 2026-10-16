"""UEFA club -> domestic league placement and cross-league strength offsets (todo #699, Stage 1 step 2).

WHY THIS EXISTS. Production soccer ratings are fit per domestic league and centred on that
league's own mean (`features/loaders.compute_team_ratings`), so an EPL +0.2 and a Belgian
+0.2 are different strengths. A UEFA fixture between two of our leagues needs a per-league
offset on top of those ratings, and the offset must be MEASURED from cross-league results,
never assumed. This module is the measurement's library; it is research code and nothing in
the sim, the board or a worker imports it (Stage 0 deliberately serves no UEFA projection).

THREE PIECES:

1. PLACEMENT, per season, by ESPN team id. A club's league in season S is the domestic league
   in whose completed matches it appears inside S's July..June window. Membership moves with
   promotion and relegation, so a season-free map would silently mis-place clubs. A club seen
   in two leagues in one window takes the one with more matches; those are returned as
   conflicts so the caller can report them.

2. DOMESTIC RATINGS AS OF A DATE (the club component). Poisson attack/defence per league on the
   365 days strictly before the kickoff DAY, L2-penalised (kappa) so ratings sit near the league
   mean -- the same league-centred shape production uses. `DomesticRatingIndex` caches one fit
   per (league, day) and asserts no input is dated on or after the kickoff day.

3. THE CROSS-LEAGUE GOALS MODEL. Independent Poisson:
       log lam_home = mu + eta*(1-neutral) + beta*(a_i - d_j) [+ o_L(i) - o_L(j)]
       log lam_away = mu                 + beta*(a_j - d_i) [+ o_L(j) - o_L(i)]
   `fit_cross_league(..., with_offset=False)` is the NO-OFFSET arm. Offsets enter only as
   differences, so they are centred (mean 0 over the leagues seen in training) after the fit.

The registration that fixes every choice above (kappa=10, the window, eligibility, the
walk-forward split and the verdict rule) is `.syndicate/findings_2026-10-16_uefa_league_offsets.md`
section 1, committed before the first fit.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
from scipy.optimize import minimize
from scipy.stats import poisson

from syndicate.features.soccer.ingestion.espn_lineups import LEAGUE_ESPN_SLUGS
from syndicate.features.soccer.ingestion.uefa_history import season_of
from syndicate.features.soccer.sources import UEFA_COMPETITIONS

DOMESTIC_LEAGUES: tuple[str, ...] = tuple(k for k in LEAGUE_ESPN_SLUGS if k not in UEFA_COMPETITIONS)
DOMESTIC_KAPPA = 10.0
DOMESTIC_WINDOW_DAYS = 365
MIN_DOMESTIC_MATCHES = 5
MIN_OFFSET_MATCHES = 30
MAX_GOALS = 10


def _day(iso: str) -> date:
    return date.fromisoformat(str(iso)[:10])


# --------------------------------------------------------------------------- placement


@dataclass
class Membership:
    """{(season, team_id): league} plus the clubs seen in more than one league in one season."""

    league_of: dict[tuple[int, str], str]
    conflicts: list[dict[str, Any]] = field(default_factory=list)

    def league(self, season: int, team_id: str) -> str:
        return self.league_of.get((int(season), str(team_id)), "")


def build_membership(domestic_rows: Mapping[str, Iterable[Mapping[str, Any]]]) -> Membership:
    """`domestic_rows`: {league: completed-match rows with date, home_team_id, away_team_id}."""
    counts: dict[tuple[int, str], Counter] = defaultdict(Counter)
    for league, rows in domestic_rows.items():
        for row in rows:
            season = season_of(row["date"])
            for side in ("home_team_id", "away_team_id"):
                team_id = str(row.get(side) or "")
                if team_id:
                    counts[(season, team_id)][league] += 1
    league_of: dict[tuple[int, str], str] = {}
    conflicts: list[dict[str, Any]] = []
    for key, by_league in counts.items():
        # Ties break on league name so the map is deterministic.
        ranked = sorted(by_league.items(), key=lambda kv: (-kv[1], kv[0]))
        league_of[key] = ranked[0][0]
        if len(ranked) > 1:
            conflicts.append({"season": key[0], "team_id": key[1], "leagues": dict(by_league)})
    return Membership(league_of=league_of, conflicts=conflicts)


def place_matches(uefa_rows: Iterable[Mapping[str, Any]], membership: Membership) -> list[dict[str, Any]]:
    """Copies of the UEFA rows with `home_league` / `away_league` ('' = not one of our leagues)."""
    out = []
    for row in uefa_rows:
        season = int(row["season"])
        placed = dict(row)
        placed["home_league"] = membership.league(season, row["home_team_id"])
        placed["away_league"] = membership.league(season, row["away_team_id"])
        out.append(placed)
    return out


def is_cross_league(row: Mapping[str, Any]) -> bool:
    home, away = row.get("home_league") or "", row.get("away_league") or ""
    return bool(home and away and home != away)


def coverage(placed_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Share of UEFA matches with both / one / neither club placed, and the unplaced clubs."""
    both = one = neither = cross = same = 0
    clubs: dict[str, str] = {}
    placed_clubs: set[str] = set()
    pair_counts: Counter = Counter()
    for row in placed_rows:
        homes = (row.get("home_league") or "", row.get("away_league") or "")
        n = sum(1 for x in homes if x)
        both += n == 2
        one += n == 1
        neither += n == 0
        if is_cross_league(row):
            cross += 1
            pair_counts[tuple(sorted(homes))] += 1
        elif n == 2:
            same += 1
        for side in ("home", "away"):
            team_id = str(row[f"{side}_team_id"])
            clubs.setdefault(team_id, row.get(f"{side}_team") or "")
            if row.get(f"{side}_league"):
                placed_clubs.add(team_id)
    total = len(placed_rows)
    return {
        "matches": total,
        "both_placed": both, "one_placed": one, "neither_placed": neither,
        "both_placed_share": (both / total) if total else 0.0,
        "cross_league": cross, "same_league": same,
        "clubs": len(clubs), "clubs_ever_placed": len(placed_clubs),
        "clubs_never_placed": len(set(clubs) - placed_clubs),
        "pairs": {f"{a}|{b}": n for (a, b), n in sorted(pair_counts.items())},
    }


def match_flags(payload: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """{event_id: {status, neutral, extra_time}} from a raw ESPN scoreboard payload.

    `extra_time` is True for after-extra-time or penalties: the stored score then includes
    extra-time goals, while the 90-minute result was a draw by construction. (Measured
    2026-10-16 over 9,998 events: STATUS_FINAL_AET 224, STATUS_FINAL_PEN 202.)
    """
    out = {}
    for event in payload.get("events") or []:
        comp = (event.get("competitions") or [{}])[0]
        name = str(((comp.get("status") or {}).get("type") or {}).get("name") or "")
        out[str(event.get("id") or "")] = {
            "status": name,
            # ESPN's soccer scoreboard carries no `neutralSite` (0 of 9,998 UEFA events,
            # read 2026-10-16); the final is the neutral match and is tagged by season slug.
            "neutral": bool(comp.get("neutralSite")) or (event.get("season") or {}).get("slug") == "final",
            "extra_time": ("AET" in name.upper()) or ("PEN" in name.upper()),
        }
    out.pop("", None)
    return out


# --------------------------------------------------------------------------- domestic ratings


def fit_poisson_ratings(home_idx: np.ndarray, away_idx: np.ndarray, home_goals: np.ndarray,
                        away_goals: np.ndarray, n_teams: int, *, kappa: float = DOMESTIC_KAPPA
                        ) -> tuple[float, float, np.ndarray, np.ndarray]:
    """(mu, eta, attack[n], defence[n]) maximising the L2-penalised Poisson likelihood."""
    hg, ag = home_goals.astype(float), away_goals.astype(float)

    def objective(theta: np.ndarray) -> tuple[float, np.ndarray]:
        mu, eta = theta[0], theta[1]
        att, dfn = theta[2:2 + n_teams], theta[2 + n_teams:]
        lh = np.exp(mu + eta + att[home_idx] - dfn[away_idx])
        la = np.exp(mu + att[away_idx] - dfn[home_idx])
        nll = float(np.sum(lh - hg * np.log(lh)) + np.sum(la - ag * np.log(la)))
        nll += 0.5 * kappa * float(att @ att + dfn @ dfn)
        rh, ra = lh - hg, la - ag
        g_att, g_dfn = kappa * att, kappa * dfn
        np.add.at(g_att, home_idx, rh)
        np.add.at(g_att, away_idx, ra)
        np.add.at(g_dfn, away_idx, -rh)
        np.add.at(g_dfn, home_idx, -ra)
        grad = np.concatenate([[rh.sum() + ra.sum(), rh.sum()], g_att, g_dfn])
        return nll, grad

    start = np.zeros(2 + 2 * n_teams)
    start[0] = math.log(max(1e-6, float((hg.sum() + ag.sum()) / max(1, 2 * len(hg)))))
    result = minimize(objective, start, jac=True, method="L-BFGS-B")
    theta = result.x
    return float(theta[0]), float(theta[1]), theta[2:2 + n_teams], theta[2 + n_teams:]


class DomesticRatingIndex:
    """As-of domestic ratings: one penalised Poisson fit per (league, kickoff day), cached."""

    def __init__(self, domestic_rows: Mapping[str, Iterable[Mapping[str, Any]]], *,
                 kappa: float = DOMESTIC_KAPPA, window_days: int = DOMESTIC_WINDOW_DAYS):
        self.kappa, self.window_days = kappa, window_days
        self._by_league: dict[str, list[tuple[date, str, str, int, int]]] = {}
        for league, rows in domestic_rows.items():
            parsed = [(_day(r["date"]), str(r["home_team_id"]), str(r["away_team_id"]),
                       int(r["home_score"]), int(r["away_score"])) for r in rows]
            parsed.sort(key=lambda x: x[0])
            self._by_league[league] = parsed
        self._cache: dict[tuple[str, date], dict[str, tuple[float, float, int]]] = {}

    def ratings_as_of(self, league: str, kickoff_day: date) -> dict[str, tuple[float, float, int]]:
        """{team_id: (attack, defence, matches_in_window)} from matches strictly before the day."""
        key = (league, kickoff_day)
        if key in self._cache:
            return self._cache[key]
        lo = kickoff_day - timedelta(days=self.window_days)
        window = [m for m in self._by_league.get(league, ()) if lo <= m[0] < kickoff_day]
        assert all(m[0] < kickoff_day for m in window), "domestic input dated on/after kickoff"
        out: dict[str, tuple[float, float, int]] = {}
        if window:
            teams = sorted({m[1] for m in window} | {m[2] for m in window})
            index = {t: i for i, t in enumerate(teams)}
            hi = np.array([index[m[1]] for m in window])
            ai = np.array([index[m[2]] for m in window])
            hg = np.array([m[3] for m in window])
            ag = np.array([m[4] for m in window])
            _, _, att, dfn = fit_poisson_ratings(hi, ai, hg, ag, len(teams), kappa=self.kappa)
            played = Counter([m[1] for m in window] + [m[2] for m in window])
            out = {t: (float(att[i]), float(dfn[i]), int(played[t])) for t, i in index.items()}
        self._cache[key] = out
        return out

    def rating(self, league: str, team_id: str, kickoff_day: date) -> tuple[float, float, int] | None:
        return self.ratings_as_of(league, kickoff_day).get(str(team_id))


# --------------------------------------------------------------------------- cross-league model


@dataclass
class CrossMatch:
    """One eligible cross-league match, ready for the goals model."""

    event_id: str
    season: int
    home_league: str
    away_league: str
    home_att: float
    home_def: float
    away_att: float
    away_def: float
    neutral: bool
    home_goals: int
    away_goals: int
    extra_time: bool


@dataclass
class CrossFit:
    mu: float
    eta: float
    beta: float
    offsets: dict[str, float]  # centred over `leagues`; empty for the NO-OFFSET arm
    leagues: tuple[str, ...]
    n_matches: int

    def rates(self, m: CrossMatch) -> tuple[float, float]:
        oh = self.offsets.get(m.home_league, 0.0)
        oa = self.offsets.get(m.away_league, 0.0)
        lh = math.exp(self.mu + self.eta * (0.0 if m.neutral else 1.0)
                      + self.beta * (m.home_att - m.away_def) + oh - oa)
        la = math.exp(self.mu + self.beta * (m.away_att - m.home_def) + oa - oh)
        return lh, la


def fit_cross_league(matches: Sequence[CrossMatch], *, with_offset: bool,
                     weights: Sequence[float] | None = None) -> CrossFit:
    """Poisson MLE on training matches. Extra-time matches are excluded (score includes ET).

    `weights` (one per entry of `matches`, default all 1) scales each match's log-likelihood:
    the recency-weighted arm of the 2026-10-16 production-ratings registration
    (`.syndicate/findings_2026-10-16_uefa_offsets_recency_prod.md`) weights the WHOLE
    likelihood, so mu, eta, beta and the offsets all move with it.
    """
    if weights is not None and len(weights) != len(matches):
        raise ValueError("weights must have one entry per match")
    w_all = [1.0] * len(matches) if weights is None else [float(x) for x in weights]
    kept = [(m, w) for m, w in zip(matches, w_all) if not m.extra_time]
    train = [m for m, _ in kept]
    wt = np.array([w for _, w in kept], dtype=float)
    leagues = tuple(sorted({m.home_league for m in train} | {m.away_league for m in train}))
    li = {lg: i for i, lg in enumerate(leagues)}
    hg = np.array([m.home_goals for m in train], dtype=float)
    ag = np.array([m.away_goals for m in train], dtype=float)
    home = np.array([0.0 if m.neutral else 1.0 for m in train])
    xh = np.array([m.home_att - m.away_def for m in train])
    xa = np.array([m.away_att - m.home_def for m in train])
    hl = np.array([li[m.home_league] for m in train], dtype=int)
    al = np.array([li[m.away_league] for m in train], dtype=int)
    k = len(leagues) if with_offset else 0
    tiny = 1e-6  # identifies the offsets' common level; they are centred afterwards anyway

    def objective(theta: np.ndarray) -> tuple[float, np.ndarray]:
        mu, eta, beta = theta[:3]
        off = theta[3:]
        d = (off[hl] - off[al]) if k else 0.0
        lh = np.exp(mu + eta * home + beta * xh + d)
        la = np.exp(mu + beta * xa - d)
        nll = float(np.sum(wt * (lh - hg * np.log(lh))) + np.sum(wt * (la - ag * np.log(la)))) + 0.5 * tiny * float(off @ off)
        rh, ra = wt * (lh - hg), wt * (la - ag)
        grad = [rh.sum() + ra.sum(), (rh * home).sum(), (rh * xh).sum() + (ra * xa).sum()]
        g_off = tiny * off.copy()
        if k:
            np.add.at(g_off, hl, rh - ra)
            np.add.at(g_off, al, ra - rh)
        return nll, np.concatenate([grad, g_off])

    start = np.zeros(3 + k)
    start[0] = math.log(max(1e-6, float((wt @ hg + wt @ ag) / max(1e-9, 2 * wt.sum()))))
    start[2] = 1.0
    theta = minimize(objective, start, jac=True, method="L-BFGS-B").x
    offsets: dict[str, float] = {}
    if k:
        centred = theta[3:] - theta[3:].mean()
        offsets = {lg: float(centred[i]) for lg, i in li.items()}
    return CrossFit(mu=float(theta[0]), eta=float(theta[1]), beta=float(theta[2]),
                    offsets=offsets, leagues=leagues, n_matches=len(train))


def outcome_probs(lam_home: float, lam_away: float, *, max_goals: int = MAX_GOALS) -> tuple[float, float, float]:
    """(home, draw, away) from independent Poisson rates, goals truncated at `max_goals`, renormalised."""
    goals = np.arange(max_goals + 1)
    grid = np.outer(poisson.pmf(goals, lam_home), poisson.pmf(goals, lam_away))
    total = grid.sum()
    return (float(np.tril(grid, -1).sum() / total), float(np.trace(grid) / total),
            float(np.triu(grid, 1).sum() / total))


def result_index(m: CrossMatch) -> int:
    """0 home / 1 draw / 2 away at 90 minutes. Extra time means the 90-minute score was level."""
    if m.extra_time or m.home_goals == m.away_goals:
        return 1
    return 0 if m.home_goals > m.away_goals else 2


def score_match(fit: CrossFit, m: CrossMatch) -> dict[str, float]:
    """Per-match 1X2 log loss and Brier (the registered primary and secondary metrics)."""
    probs = outcome_probs(*fit.rates(m))
    y = result_index(m)
    onehot = [1.0 if i == y else 0.0 for i in range(3)]
    return {
        "log_loss": -math.log(max(probs[y], 1e-15)),
        "brier": float(sum((p - o) ** 2 for p, o in zip(probs, onehot))),
    }


def paired_bootstrap_ci(diffs: Sequence[float], *, resamples: int = 2000, seed: int = 699,
                        level: float = 0.95) -> tuple[float, float, float]:
    """(mean, lo, hi) of a paired per-match difference, bootstrapping matches."""
    arr = np.asarray(diffs, dtype=float)
    if arr.size == 0:
        return float("nan"), float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    means = arr[rng.integers(0, arr.size, size=(resamples, arr.size))].mean(axis=1)
    tail = (1.0 - level) / 2.0
    return float(arr.mean()), float(np.quantile(means, tail)), float(np.quantile(means, 1 - tail))


def verdict(mean: float, lo: float, hi: float) -> str:
    """The registered rule for H-OFFSET on Δ log loss = OFFSET − NO-OFFSET."""
    if mean >= 0:
        return "FALSIFIED"
    return "SUPPORTED" if hi < 0 else "NOT DEMONSTRATED"
