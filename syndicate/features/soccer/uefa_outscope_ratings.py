"""Ratings for UEFA clubs outside our domestic leagues (todo #699, Stage 1 item (ii)).

WHY THIS EXISTS. About 525 clubs that play UCL / UEL / UECL matches (Galatasaray, Celtic,
Salzburg, Olympiacos, Shakhtar, ...) are never in the ten leagues production rates, so
`features/loaders._rating_for` would hand them a silent 0.0 and `build_soccer_artifacts
._fill_promoted` a PROMOTED_TEAM_RATING. This module fits them from their UEFA results instead,
ON PRODUCTION'S SCALE: an in-scope club's effective strength is `A = beta*a + o_L`,
`D = beta*d + o_L` (production's `compute_team_ratings` plus the measured CONST league offsets
of `uefa_league_offsets.fit_cross_league`), and an out-of-scope (OOS) club gets an `(A, D)` in
the same units. Research code: nothing in the sim, the board or a worker imports it.

THE MODEL (penalised Poisson MAP). For an OOS club c of association k:
    A_c = g_A + m_A[k] + u_A[c]        D_c = g_D + m_D[k] + u_D[c]
    log lam_home = mu + eta*(1-neutral) + A_home - D_away
    log lam_away = mu                   + A_away - D_home
`g` is one out-of-scope mean, `m` an association effect (penalty tau_k), `u` a club deviation
(penalty tau_c). Arms: MODE_FIXED (every OOS club the same constant -- PROMOTED_TEAM_RATING or
0.0, i.e. what production would do), MODE_PRIOR (u = 0) and MODE_FITTED (the whole model).

The registration that fixes every choice (half-life, tau grid, eligibility, the split, the
verdict rule) is `.syndicate/findings_2026-10-16_uefa_outscope_ratings.md` section 1,
committed before the first fit.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
from scipy.optimize import minimize

from syndicate.features.soccer import uefa_league_offsets as ulo

MODE_FIXED = "fixed"
MODE_PRIOR = "prior"
MODE_FITTED = "fitted"
# Registered 2026-10-16 (findings s1).
HALF_LIFE_DAYS = 365
TAU_GRID: tuple[float, ...] = (2.0, 5.0, 10.0, 20.0, 50.0)
THIN_MATCHES = 6
THIN_SEASONS_BACK = 3
COUNTRY_AUDIT_SHARE = 0.8
# production's default for an unmatched fixture team (scripts/build_soccer_artifacts.py)
PROMOTED_RATING = -0.18


# --------------------------------------------------------------------------- associations


def venue_countries(payload: Mapping[str, Any]) -> dict[str, str]:
    """{event_id: venue country} from a raw ESPN scoreboard payload ('' when absent)."""
    out = {}
    for event in payload.get("events") or []:
        comp = (event.get("competitions") or [{}])[0]
        country = (((comp.get("venue") or {}).get("address") or {}).get("country") or "").strip()
        out[str(event.get("id") or "")] = country
    out.pop("", None)
    return out


@dataclass
class Associations:
    country_of: dict[str, str]  # team_id -> country ('' = unknown)
    audit: list[dict[str, Any]] = field(default_factory=list)

    def get(self, team_id: str) -> str:
        return self.country_of.get(str(team_id), "")


def club_associations(rows: Iterable[Mapping[str, Any]], venue_by_event: Mapping[str, str],
                      neutral_by_event: Mapping[str, bool], *,
                      overrides: Mapping[str, str] | None = None) -> Associations:
    """A club's association = the mode venue country of its NON-neutral home matches.

    A tie or no country gives '' (unknown). `audit` lists every club whose mode holds less than
    COUNTRY_AUDIT_SHARE of its home matches, or that tied, so a human can check geography
    before any fit. `overrides` ({team_id: country}) wins and is reported in the audit.
    """
    counts: dict[str, Counter] = defaultdict(Counter)
    names: dict[str, str] = {}
    for row in rows:
        names.setdefault(str(row["home_team_id"]), str(row.get("home_team") or ""))
        names.setdefault(str(row["away_team_id"]), str(row.get("away_team") or ""))
        event = str(row["event_id"])
        if neutral_by_event.get(event):
            continue
        country = venue_by_event.get(event) or ""
        if country:
            counts[str(row["home_team_id"])][country] += 1
    overrides = {str(k): v for k, v in (overrides or {}).items()}
    country_of: dict[str, str] = {}
    audit: list[dict[str, Any]] = []
    for team_id in sorted(names):
        ranked = sorted(counts.get(team_id, Counter()).items(), key=lambda kv: (-kv[1], kv[0]))
        total = sum(n for _, n in ranked)
        tie = len(ranked) > 1 and ranked[0][1] == ranked[1][1]
        mode = "" if (not ranked or tie) else ranked[0][0]
        country_of[team_id] = overrides.get(team_id, mode)
        if team_id in overrides or tie or (ranked and ranked[0][1] < COUNTRY_AUDIT_SHARE * total):
            audit.append({"team_id": team_id, "team": names[team_id], "venues": dict(ranked),
                          "mode": mode, "tie": tie, "override": overrides.get(team_id)})
    return Associations(country_of=country_of, audit=audit)


# --------------------------------------------------------------------------- matches


@dataclass
class OOSMatch:
    """A UEFA match with at least one out-of-scope club.

    For an in-scope side, `*_A` / `*_D` are its EFFECTIVE strengths (beta*a + o_L, beta*d + o_L);
    for an OOS side they are ignored and the model supplies them.
    """

    event_id: str
    season: int
    day: date
    competition: str
    stage: str
    home_id: str
    away_id: str
    home_oos: bool
    away_oos: bool
    home_A: float
    home_D: float
    away_A: float
    away_D: float
    neutral: bool
    home_goals: int
    away_goals: int
    extra_time: bool


def effective_in_scope(attack: float, defence: float, league: str, const_fit: ulo.CrossFit) -> tuple[float, float]:
    """(A, D) of an in-scope club on the effective scale of a CONST cross-league fit."""
    off = const_fit.offsets.get(league, 0.0)
    return const_fit.beta * attack + off, const_fit.beta * defence + off


def recency_weights(days: Sequence[date], anchor: date, half_life_days: float | None) -> np.ndarray:
    if half_life_days is None:
        return np.ones(len(days))
    return np.array([0.5 ** ((anchor - d).days / half_life_days) for d in days], dtype=float)


def thin_clubs(matches: Iterable[OOSMatch], seasons: Iterable[int], *, threshold: int = THIN_MATCHES
               ) -> tuple[Counter, set[str]]:
    """(OOS matches per club in `seasons`, the clubs below `threshold`) -- the registered THIN rule."""
    keep = set(seasons)
    n: Counter = Counter()
    for m in matches:
        if m.season in keep:
            if m.home_oos:
                n[m.home_id] += 1
            if m.away_oos:
                n[m.away_id] += 1
    return n, {c for c, k in n.items() if k < threshold}


# --------------------------------------------------------------------------- fit


@dataclass
class OutscopeFit:
    mode: str
    mu: float
    eta: float
    g_A: float = 0.0
    g_D: float = 0.0
    assoc: dict[str, tuple[float, float]] = field(default_factory=dict)
    club: dict[str, tuple[float, float]] = field(default_factory=dict)
    club_se: dict[str, tuple[float, float]] = field(default_factory=dict)
    club_weight: dict[str, float] = field(default_factory=dict)
    countries: Associations | None = None
    fixed: tuple[float, float] = (0.0, 0.0)
    tau_club: float | None = None
    tau_assoc: float | None = None
    n_matches: int = 0

    def oos_rating(self, team_id: str) -> tuple[float, float]:
        """(A, D) for an OOS club. An unseen club gets its prior; an unknown association, g."""
        if self.mode == MODE_FIXED:
            return self.fixed
        k = self.countries.get(team_id) if self.countries else ""
        ma, md = self.assoc.get(k, (0.0, 0.0))
        ua, ud = self.club.get(str(team_id), (0.0, 0.0)) if self.mode == MODE_FITTED else (0.0, 0.0)
        return self.g_A + ma + ua, self.g_D + md + ud

    def side(self, m: OOSMatch, home: bool) -> tuple[float, float]:
        if home:
            return self.oos_rating(m.home_id) if m.home_oos else (m.home_A, m.home_D)
        return self.oos_rating(m.away_id) if m.away_oos else (m.away_A, m.away_D)

    def rates(self, m: OOSMatch) -> tuple[float, float]:
        ha, hd = self.side(m, True)
        aa, ad = self.side(m, False)
        lh = math.exp(self.mu + self.eta * (0.0 if m.neutral else 1.0) + ha - ad)
        la = math.exp(self.mu + aa - hd)
        return lh, la


def fit_outscope(matches: Sequence[OOSMatch], countries: Associations, *, mode: str,
                 weights: Sequence[float] | None = None, tau_club: float = 10.0,
                 tau_assoc: float = 10.0, fixed: tuple[float, float] = (0.0, 0.0)) -> OutscopeFit:
    """MAP fit on training matches. Extra-time matches are excluded (the score includes ET)."""
    if mode not in (MODE_FIXED, MODE_PRIOR, MODE_FITTED):
        raise ValueError(f"unknown mode {mode!r}")
    if weights is not None and len(weights) != len(matches):
        raise ValueError("weights must have one entry per match")
    w_all = np.ones(len(matches)) if weights is None else np.asarray(weights, dtype=float)
    keep = [i for i, m in enumerate(matches) if not m.extra_time]
    train = [matches[i] for i in keep]
    w = w_all[keep]
    hg = np.array([m.home_goals for m in train], dtype=float)
    ag = np.array([m.away_goals for m in train], dtype=float)
    home = np.array([0.0 if m.neutral else 1.0 for m in train])
    h_oos = np.array([m.home_oos for m in train], dtype=bool)
    a_oos = np.array([m.away_oos for m in train], dtype=bool)
    # fixed parts: in-scope effective ratings, or the constant for MODE_FIXED
    fa, fd = fixed
    hA0 = np.array([fa if m.home_oos and mode == MODE_FIXED else (0.0 if m.home_oos else m.home_A) for m in train])
    hD0 = np.array([fd if m.home_oos and mode == MODE_FIXED else (0.0 if m.home_oos else m.home_D) for m in train])
    aA0 = np.array([fa if m.away_oos and mode == MODE_FIXED else (0.0 if m.away_oos else m.away_A) for m in train])
    aD0 = np.array([fd if m.away_oos and mode == MODE_FIXED else (0.0 if m.away_oos else m.away_D) for m in train])

    learn = mode != MODE_FIXED
    assoc_keys = sorted({countries.get(c) for m in train for c, o in ((m.home_id, m.home_oos), (m.away_id, m.away_oos))
                         if o and countries.get(c)}) if learn else []
    club_keys = sorted({c for m in train for c, o in ((m.home_id, m.home_oos), (m.away_id, m.away_oos)) if o}) \
        if mode == MODE_FITTED else []
    ki = {k: i for i, k in enumerate(assoc_keys)}
    ci = {c: i for i, c in enumerate(club_keys)}
    K, C = len(assoc_keys), len(club_keys)
    hk = np.array([ki.get(countries.get(m.home_id), -1) if m.home_oos else -1 for m in train], dtype=int)
    ak = np.array([ki.get(countries.get(m.away_id), -1) if m.away_oos else -1 for m in train], dtype=int)
    hc = np.array([ci.get(m.home_id, -1) if m.home_oos else -1 for m in train], dtype=int)
    ac = np.array([ci.get(m.away_id, -1) if m.away_oos else -1 for m in train], dtype=int)
    G = 2 if learn else 0
    n_par = 2 + G + 2 * K + 2 * C

    def unpack(theta):
        mu, eta = theta[0], theta[1]
        gA, gD = (theta[2], theta[3]) if learn else (0.0, 0.0)
        o = 2 + G
        mA, mD = theta[o:o + K], theta[o + K:o + 2 * K]
        o += 2 * K
        uA, uD = theta[o:o + C], theta[o + C:o + 2 * C]
        return mu, eta, gA, gD, mA, mD, uA, uD

    def pick(arr, idx):
        out = np.zeros(len(idx))
        ok = idx >= 0
        if arr.size:
            out[ok] = arr[idx[ok]]
        return out

    def objective(theta):
        mu, eta, gA, gD, mA, mD, uA, uD = unpack(theta)
        hA = hA0 + h_oos * (gA + pick(mA, hk) + pick(uA, hc)) if learn else hA0
        hD = hD0 + h_oos * (gD + pick(mD, hk) + pick(uD, hc)) if learn else hD0
        aA = aA0 + a_oos * (gA + pick(mA, ak) + pick(uA, ac)) if learn else aA0
        aD = aD0 + a_oos * (gD + pick(mD, ak) + pick(uD, ac)) if learn else aD0
        eh = mu + eta * home + hA - aD
        ea = mu + aA - hD
        lh, la = np.exp(eh), np.exp(ea)
        nll = float(np.sum(w * (lh - hg * eh)) + np.sum(w * (la - ag * ea)))
        nll += 0.5 * tau_assoc * float(mA @ mA + mD @ mD) + 0.5 * tau_club * float(uA @ uA + uD @ uD)
        rh, ra = w * (lh - hg), w * (la - ag)
        grad = np.zeros(n_par)
        grad[0] = rh.sum() + ra.sum()
        grad[1] = (rh * home).sum()
        if learn:
            # dA_home: +rh, dD_away: -rh, dA_away: +ra, dD_home: -ra
            gA_h, gD_a, gA_a, gD_h = rh * h_oos, -rh * a_oos, ra * a_oos, -ra * h_oos
            grad[2] = gA_h.sum() + gA_a.sum()
            grad[3] = gD_a.sum() + gD_h.sum()
            o = 2 + G
            gmA, gmD = tau_assoc * mA.copy(), tau_assoc * mD.copy()
            for vals, idx, tgt in ((gA_h, hk, gmA), (gA_a, ak, gmA), (gD_h, hk, gmD), (gD_a, ak, gmD)):
                ok = idx >= 0
                np.add.at(tgt, idx[ok], vals[ok])
            grad[o:o + K], grad[o + K:o + 2 * K] = gmA, gmD
            o += 2 * K
            guA, guD = tau_club * uA.copy(), tau_club * uD.copy()
            for vals, idx, tgt in ((gA_h, hc, guA), (gA_a, ac, guA), (gD_h, hc, guD), (gD_a, ac, guD)):
                ok = idx >= 0
                np.add.at(tgt, idx[ok], vals[ok])
            grad[o:o + C], grad[o + C:o + 2 * C] = guA, guD
        return nll, grad

    start = np.zeros(n_par)
    start[0] = math.log(max(1e-6, float((w @ hg + w @ ag) / max(1e-9, 2 * w.sum()))))
    theta = minimize(objective, start, jac=True, method="L-BFGS-B", options={"maxiter": 5000}).x
    mu, eta, gA, gD, mA, mD, uA, uD = unpack(theta)
    fit = OutscopeFit(mode=mode, mu=float(mu), eta=float(eta), g_A=float(gA), g_D=float(gD),
                      assoc={k: (float(mA[i]), float(mD[i])) for k, i in ki.items()},
                      club={c: (float(uA[i]), float(uD[i])) for c, i in ci.items()},
                      countries=countries, fixed=fixed,
                      tau_club=tau_club if mode == MODE_FITTED else None,
                      tau_assoc=tau_assoc if learn else None, n_matches=len(train))
    if mode == MODE_FITTED and C:
        # Diagonal Laplace: the attack of c is informed by the rate of goals it scores, the
        # defence by the rate it concedes. Registered as approximate.
        info_A, info_D, wsum = np.zeros(C), np.zeros(C), np.zeros(C)
        for m, wi in zip(train, w):
            lh, la = fit.rates(m)
            if m.home_oos:
                i = ci[m.home_id]
                info_A[i] += wi * lh
                info_D[i] += wi * la
                wsum[i] += wi
            if m.away_oos:
                i = ci[m.away_id]
                info_A[i] += wi * la
                info_D[i] += wi * lh
                wsum[i] += wi
        fit.club_se = {c: (float(1 / math.sqrt(info_A[i] + tau_club)), float(1 / math.sqrt(info_D[i] + tau_club)))
                       for c, i in ci.items()}
        fit.club_weight = {c: float(wsum[i]) for c, i in ci.items()}
    return fit


def score_match(fit: OutscopeFit, m: OOSMatch) -> dict[str, float]:
    """Per-match 1X2 log loss and Brier (the registered primary and secondary metrics)."""
    probs = ulo.outcome_probs(*fit.rates(m))
    y = ulo.result_index(m)  # duck-typed: extra_time / home_goals / away_goals
    return {"log_loss": -math.log(max(probs[y], 1e-15)),
            "brier": float(sum((p - (1.0 if i == y else 0.0)) ** 2 for i, p in enumerate(probs)))}


def mean_log_loss(fit: OutscopeFit, matches: Sequence[OOSMatch]) -> float:
    return float(np.mean([score_match(fit, m)["log_loss"] for m in matches])) if matches else float("nan")


def select_taus(train: Sequence[OOSMatch], weights: Sequence[float], val: Sequence[OOSMatch],
                countries: Associations, *, mode: str, grid: Sequence[float] = TAU_GRID
                ) -> tuple[float, float, dict[str, float]]:
    """The registered inner rule: the (tau_club, tau_assoc) with the lowest validation log loss.

    MODE_PRIOR searches tau_assoc only (tau_club is unused). Ties go to the larger tau.
    """
    scores: dict[str, float] = {}
    best: tuple[float, float, float] | None = None
    clubs = list(grid) if mode == MODE_FITTED else [max(grid)]
    for tc in sorted(clubs, reverse=True):
        for ta in sorted(grid, reverse=True):
            fit = fit_outscope(train, countries, mode=mode, weights=weights, tau_club=tc, tau_assoc=ta)
            ll = mean_log_loss(fit, val)
            scores[f"{tc:g}|{ta:g}"] = ll
            if best is None or ll < best[0] - 1e-12:
                best = (ll, tc, ta)
    assert best is not None
    return best[1], best[2], scores


def rating_table(fit: OutscopeFit, beta: float, names: Mapping[str, str] | None = None,
                 counts: Mapping[str, int] | None = None, thin: set[str] | None = None) -> list[dict[str, Any]]:
    """Per-club (A, D), production-unit (A/beta, D/beta) at offset 0, SE, association, counts."""
    rows = []
    for c in sorted(fit.club, key=lambda c: -(fit.oos_rating(c)[0] + fit.oos_rating(c)[1])):
        A, D = fit.oos_rating(c)
        se = fit.club_se.get(c, (float("nan"), float("nan")))
        rows.append({"team_id": c, "team": (names or {}).get(c, ""),
                     "association": fit.countries.get(c) if fit.countries else "",
                     "A": A, "D": D, "A_se": se[0], "D_se": se[1],
                     "attack_rating": A / beta, "defense_rating": D / beta,
                     "weighted_matches": fit.club_weight.get(c, 0.0),
                     "recent_matches": int((counts or {}).get(c, 0)),
                     "thin": bool(thin is not None and c in thin)})
    return rows
