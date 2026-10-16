"""Are production's soccer team ratings too COMPRESSED for domestic 1X2? (lane soccer-team-strength).

RESEARCH ONLY. Reads production's rating inputs (pulled by lane uefa-offsets-recency-prod with
production's own fetcher) and raw football-data.co.uk season CSVs (for the closing odds that
production's `normalize_match_history` drops); writes JSON into the research root. Nothing in
production reads it. The registration this runs is
`.syndicate/findings_2026-10-16_soccer_rating_compression.md` section 1.

    # raw football-data CSVs (E0 SP1 D1 I1 F1 N1 P1 B1, 1415..2627) into <root>/fd_raw/<CODE>_<yyyy>.csv
    # 1. coverage + football-data -> rating-key name audit (no fit):
    python scripts/soccer_team_strength_experiments.py audit --root C:/tmp/team-strength
    # 2. walk-forward arms A/B/C/D, clamp census, parameters:
    python scripts/soccer_team_strength_experiments.py run --root C:/tmp/team-strength

Arms (link identical in all: per-league Poisson, log λ_h = μ_L + η_L + k(A_h − D_a)):
  A shipped clamp(0.55x, ±0.35), k=1 | B 0.55x, k=1 | C shipped, k refit | D 0.55x, k refit.

Runs itself at Idle priority: the fleet shares the machine.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
from scipy.optimize import minimize  # noqa: E402
from scipy.stats import poisson  # noqa: E402

import syndicate.features.soccer.features.loaders as loaders  # noqa: E402
from syndicate.features.soccer.features.loaders import _as_iso_day  # noqa: E402
from syndicate.features.soccer.features.loaders import compute_team_ratings  # noqa: E402
from syndicate.features.soccer.features.loaders import team_rows_from_match_history  # noqa: E402
from syndicate.features.soccer.features.team_names import match_team_name  # noqa: E402

BIG5 = ("epl", "la_liga", "bundesliga", "serie_a", "ligue_1")
GOALS = ("eredivisie", "primeira_liga", "belgian_pro_league")
LEAGUES = BIG5 + GOALS
FD_CODE = {"epl": "E0", "la_liga": "SP1", "bundesliga": "D1", "serie_a": "I1", "ligue_1": "F1",
           "eredivisie": "N1", "primeira_liga": "P1", "belgian_pro_league": "B1"}
# Registered: production's call shape (build_soccer_artifacts._load_team_ratings) and the
# fleet's disk depth (Understat 3 seasons, football-data 4) -- as in fit_uefa_offsets_prod_ratings.
WINDOW = {**{lg: 45 for lg in BIG5}, **{lg: 90 for lg in GOALS}}
SEASONS_BACK = {**{lg: 2 for lg in BIG5}, **{lg: 3 for lg in GOALS}}
FIRST_SEASON, LAST_SEASON = 2014, 2026
TEST_SEASONS = range(2016, 2027)
MIN_MATCHES = 5
SCALE, CAP = 0.55, 0.35
CLOSE_SOURCES = (("pinnacle_close", "PSCH", "PSCD", "PSCA"), ("avg_close", "AvgCH", "AvgCD", "AvgCA"),
                 ("b365_close", "B365CH", "B365CD", "B365CA"))
ARMS = {"A": ("clamped", 1.0), "B": ("raw", 1.0), "C": ("clamped", None), "D": ("raw", None)}
MAX_GOALS = 10
SEED = 699
# Pre-fit audit aliases: {(league, football-data name): rating key}. Each entry is a section-5 deviation.
# Deviation 1 (pre-fit audit, 2026-10-16): six MISSING pairings, where production's
# `match_team_name` finds nothing and `_rating_for` would hand back a silent 0.0.
ALIASES: dict[tuple[str, str], str] = {
    ("bundesliga", "FC Koln"): "FC Cologne",
    ("bundesliga", "M'gladbach"): "Borussia M.Gladbach",
    ("la_liga", "Ath Bilbao"): "Athletic Club",
    ("la_liga", "La Coruna"): "Deportivo La Coruna",
    ("epl", "QPR"): "Queens Park Rangers",
    ("ligue_1", "Ajaccio GFCO"): "GFC Ajaccio",
}
# Deviation 1: WRONG big-5 pairings the audit found. Each fires only on a day when the right club is
# absent from the as-of table, so the fuzzy match falls through to another club. Excluded, never scored.
WRONG_PAIRINGS = {("epl", "Man City", "Manchester United"), ("epl", "Newcastle", "Manchester United"),
                  ("ligue_1", "Paris FC", "Paris Saint Germain")}


def _set_idle_priority() -> str:
    try:
        import psutil
        proc = psutil.Process()
        proc.nice(psutil.IDLE_PRIORITY_CLASS if os.name == "nt" else 19)
        return str(proc.nice())
    except Exception as exc:  # pragma: no cover - research harness
        return f"unset ({exc})"


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8")
    os.replace(tmp, path)


def _read_csvs(paths) -> list[dict]:
    rows = []
    for path in paths:
        with path.open(encoding="utf-8-sig", newline="", errors="replace") as fh:
            rows.extend(csv.DictReader(fh))
    return rows


def _f(value) -> float | None:
    try:
        out = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


# --------------------------------------------------------------------------- ratings

class RatingIndex:
    """Production's `compute_team_ratings` per (league, kickoff day), shipped AND raw deviation."""

    def __init__(self, prod_root: Path):
        self.by_season: dict[str, dict[int, list[tuple[str, dict]]]] = {}
        for lg in LEAGUES:
            if lg in BIG5:
                raw = _read_csvs(sorted((prod_root / lg / "team_history").glob("teams_*.csv")))
            else:
                raw = team_rows_from_match_history(_read_csvs(sorted((prod_root / lg / "history").glob("matches_*.csv"))))
            buckets: dict[int, list[tuple[str, dict]]] = defaultdict(list)
            for r in raw:
                day = _as_iso_day(r.get("date"))
                if day:
                    buckets[int(float(r["season"]))].append((day, r))
            self.by_season[lg] = buckets
        self._cache: dict[tuple[str, str, bool], dict] = {}
        self.identity_checked = 0
        self.identity_max_err = 0.0

    def _subset(self, league: str, season: int, cutoff: str) -> list[dict]:
        out = []
        for s in range(season - SEASONS_BACK[league], season + 1):
            out.extend(r for d, r in self.by_season[league].get(s, ()) if d < cutoff)
        assert all(_as_iso_day(r.get("date")) < cutoff for r in out), "rating input on/after kickoff"
        return out

    def table(self, league: str, season: int, cutoff: str, *, raw: bool) -> dict:
        key = (league, cutoff, raw)
        if key not in self._cache:
            subset = self._subset(league, season, cutoff)
            if not subset:
                self._cache[key] = {}
            elif raw:
                saved = (loaders._RATING_SCALE, loaders._RATING_CAP)
                loaders._RATING_SCALE, loaders._RATING_CAP = 1.0, float("inf")
                try:
                    self._cache[key] = compute_team_ratings(subset, as_of=cutoff, window=WINDOW[league])
                finally:
                    loaders._RATING_SCALE, loaders._RATING_CAP = saved
            else:
                self._cache[key] = compute_team_ratings(subset, as_of=cutoff, window=WINDOW[league])
        return self._cache[key]

    def check_identity(self, league: str, season: int, cutoff: str) -> None:
        """Registered reachability check: clamp(0.55 x) must equal production's unpatched output."""
        shipped = self.table(league, season, cutoff, raw=False)
        raw = self.table(league, season, cutoff, raw=True)
        assert shipped.keys() == raw.keys()
        for team, entry in shipped.items():
            for field in ("attack_rating", "defense_rating"):
                derived = max(-CAP, min(CAP, SCALE * raw[team][field]))
                err = abs(derived - entry[field])
                self.identity_max_err = max(self.identity_max_err, err)
                if err > 2e-4:
                    raise SystemExit(f"IDENTITY CHECK FAILED {league} {cutoff} {team} {field}: "
                                     f"derived {derived} vs production {entry[field]}")
        self.identity_checked += 1


# --------------------------------------------------------------------------- matches

def _fd_day(value: str) -> str | None:
    value = str(value or "").strip()
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def load_fd_matches(fd_root: Path) -> tuple[list[dict], dict]:
    rows, coverage = [], Counter()
    for lg in LEAGUES:
        for season in range(FIRST_SEASON, LAST_SEASON + 1):
            path = fd_root / f"{FD_CODE[lg]}_{season % 100:02d}{(season + 1) % 100:02d}.csv"
            if not path.exists() or path.stat().st_size == 0:
                coverage[f"{lg}|{season}|file_missing"] += 1
                continue
            for raw in _read_csvs([path]):
                home, away = str(raw.get("HomeTeam") or "").strip(), str(raw.get("AwayTeam") or "").strip()
                hg, ag, day = _f(raw.get("FTHG")), _f(raw.get("FTAG")), _fd_day(raw.get("Date"))
                if not home or not away or hg is None or ag is None or not day:
                    continue
                close = None
                for name, ch, cd, ca in CLOSE_SOURCES:
                    o = [_f(raw.get(c)) for c in (ch, cd, ca)]
                    if all(x is not None and x > 1.0 for x in o):
                        inv = [1.0 / x for x in o]
                        close = {"source": name, "p": [x / sum(inv) for x in inv], "overround": sum(inv)}
                        break
                rows.append({"league": lg, "season": season, "day": day, "home": home, "away": away,
                             "hg": int(hg), "ag": int(ag), "close": close})
                coverage[f"{lg}|{season}|rows"] += 1
                coverage[f"{lg}|{season}|close_{close['source'] if close else 'none'}"] += 1
    return rows, coverage


def build(root: Path, *, identity_every: int = 25):
    index = RatingIndex(root.parent / "uefa-offsets" / "prod_history" if not (root / "prod_history").exists()
                        else root / "prod_history")
    rows, coverage = load_fd_matches(root / "fd_raw")
    names: dict[str, dict] = {}
    skipped = Counter()
    eligible = []
    seen_tables = 0
    for row in sorted(rows, key=lambda r: (r["league"], r["day"])):
        lg, season, cutoff = row["league"], row["season"], row["day"]
        shipped = index.table(lg, season, cutoff, raw=False)
        if shipped and (lg, cutoff, "id") not in index._cache:
            index._cache[(lg, cutoff, "id")] = True
            seen_tables += 1
            if seen_tables % identity_every == 1:
                index.check_identity(lg, season, cutoff)
        raw = index.table(lg, season, cutoff, raw=True)
        sides = {}
        for side in ("home", "away"):
            fd_name = row[side]
            alias = ALIASES.get((lg, fd_name))
            key = alias if alias in shipped else match_team_name(fd_name, list(shipped))
            entry = names.setdefault(f"{lg}|{fd_name}", {"league": lg, "fd": fd_name, "keys": Counter(), "unmatched": 0})
            if key:
                entry["keys"][key] += 1
            else:
                entry["unmatched"] += 1
            # Goals leagues share one source: any key that is not the name itself is a WRONG pairing.
            if key and ((lg in GOALS and key != fd_name) or (lg, fd_name, key) in WRONG_PAIRINGS):
                key = None
                entry["wrong_same_source"] = entry.get("wrong_same_source", 0) + 1
            sides[side] = (key, shipped.get(key) if key else None, raw.get(key) if key else None)
        (hk, hs, hr), (ak, as_, ar) = sides["home"], sides["away"]
        if hs is None or as_ is None:
            skipped["no_rating"] += 1
            continue
        if hs["matches"] < MIN_MATCHES or as_["matches"] < MIN_MATCHES:
            skipped["under_5_rated_matches"] += 1
            continue
        if row["close"] is None:
            skipped["no_close"] += 1
            continue
        eligible.append({**row, "home_key": hk, "away_key": ak,
                         "ship": [hs["attack_rating"], hs["defense_rating"], as_["attack_rating"], as_["defense_rating"]],
                         "raw": [hr["attack_rating"], hr["defense_rating"], ar["attack_rating"], ar["defense_rating"]]})
    name_map = [{"league": e["league"], "fd": e["fd"], "keys": dict(e["keys"]), "unmatched": e["unmatched"],
                 "wrong_same_source": e.get("wrong_same_source", 0)}
                for e in sorted(names.values(), key=lambda e: (e["league"], e["fd"]))]
    return eligible, rows, coverage, skipped, name_map, index


# --------------------------------------------------------------------------- model

class Design:
    """Arrays for the per-league Poisson link; each match contributes a home and an away goal count."""

    def __init__(self, matches: list[dict], kind: str):
        lg_idx = {lg: i for i, lg in enumerate(LEAGUES)}
        self.n = len(matches)
        self.league = np.array([lg_idx[m["league"]] for m in matches], dtype=int)
        r = np.array([[SCALE * v for v in m["raw"]] if kind == "raw" else m["ship"] for m in matches], dtype=float)
        if r.size == 0:
            r = np.zeros((0, 4))
        self.gap_h = r[:, 0] - r[:, 3]   # home attack - away defence
        self.gap_a = r[:, 2] - r[:, 1]   # away attack - home defence
        self.hg = np.array([m["hg"] for m in matches], dtype=float)
        self.ag = np.array([m["ag"] for m in matches], dtype=float)


def _unpack(theta, k_fixed):
    L = len(LEAGUES)
    mu, eta = theta[:L], theta[L:2 * L]
    k = theta[2 * L] if k_fixed is None else k_fixed
    return mu, eta, k


def fit(d: Design, k_fixed: float | None, weights: np.ndarray | None = None) -> dict:
    L = len(LEAGUES)
    w = np.ones(d.n) if weights is None else weights
    present = np.bincount(d.league, minlength=L) > 0

    def nll(theta):
        mu, eta, k = _unpack(theta, k_fixed)
        lh = mu[d.league] + eta[d.league] + k * d.gap_h
        la = mu[d.league] + k * d.gap_a
        eh, ea = np.exp(lh), np.exp(la)
        val = np.sum(w * (eh - d.hg * lh + ea - d.ag * la))
        rh, ra = w * (eh - d.hg), w * (ea - d.ag)
        g_mu = np.bincount(d.league, rh + ra, minlength=L)
        g_eta = np.bincount(d.league, rh, minlength=L)
        grad = [g_mu, g_eta]
        if k_fixed is None:
            grad.append(np.array([np.sum(rh * d.gap_h + ra * d.gap_a)]))
        return val, np.concatenate(grad)

    x0 = np.concatenate([np.full(L, 0.25), np.full(L, 0.25)] + ([np.array([1.0])] if k_fixed is None else []))
    res = minimize(nll, x0, jac=True, method="L-BFGS-B")
    mu, eta, k = _unpack(res.x, k_fixed)
    return {"mu": np.where(present, mu, np.nan), "eta": np.where(present, eta, np.nan), "k": float(k),
            "converged": bool(res.success)}


def predict_1x2(d: Design, params: dict) -> np.ndarray:
    mu, eta, k = params["mu"], params["eta"], params["k"]
    lh = np.exp(mu[d.league] + eta[d.league] + k * d.gap_h)
    la = np.exp(mu[d.league] + k * d.gap_a)
    goals = np.arange(MAX_GOALS + 1)
    ph = poisson.pmf(goals[None, :], lh[:, None])
    pa = poisson.pmf(goals[None, :], la[:, None])
    grid = ph[:, :, None] * pa[:, None, :]
    grid /= grid.sum(axis=(1, 2), keepdims=True)
    home = np.tril(np.ones((MAX_GOALS + 1, MAX_GOALS + 1)), -1)
    draw = np.eye(MAX_GOALS + 1)
    p_home = (grid * home[None]).sum(axis=(1, 2))
    p_draw = (grid * draw[None]).sum(axis=(1, 2))
    return np.stack([p_home, p_draw, 1.0 - p_home - p_draw], axis=1)


def outcome_index(matches: list[dict]) -> np.ndarray:
    return np.array([0 if m["hg"] > m["ag"] else (1 if m["hg"] == m["ag"] else 2) for m in matches], dtype=int)


def scores(p: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    p = np.clip(p, 1e-12, 1.0)
    ll = -np.log(p[np.arange(len(y)), y])
    onehot = np.eye(3)[y]
    brier = np.sum((p - onehot) ** 2, axis=1)
    return ll, brier


def boot_mean_ci(diff: np.ndarray, n_boot: int = 2000, seed: int = SEED) -> dict:
    rng = np.random.default_rng(seed)
    n = len(diff)
    if n == 0:
        return {"n": 0}
    means = np.array([diff[rng.integers(0, n, n)].mean() for _ in range(n_boot)])
    return {"n": int(n), "mean": float(diff.mean()),
            "ci": [float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))]}


def verdict(stat: dict) -> str:
    if stat["mean"] >= 0:
        return "FALSIFIED"
    return "SUPPORTED" if stat["ci"][1] < 0 else "NOT DEMONSTRATED"


# --------------------------------------------------------------------------- commands

def cmd_audit(args) -> int:
    print(f"[team_strength] priority={_set_idle_priority()}", flush=True)
    root = Path(args.root)
    eligible, rows, coverage, skipped, name_map, index = build(root)
    by_ls = Counter((m["league"], m["season"]) for m in eligible)
    close_src = Counter(m["close"]["source"] for m in eligible)
    suspicious = [e for e in name_map if e["unmatched"] or e["wrong_same_source"] or len(e["keys"]) != 1
                  or (e["league"] in BIG5 and list(e["keys"])[:1] != [e["fd"]])]
    out = {"fd_rows": len(rows), "eligible": len(eligible), "skipped": dict(skipped),
           "close_sources_eligible": dict(close_src), "identity_tables_checked": index.identity_checked,
           "identity_max_err": index.identity_max_err,
           "eligible_by_league_season": {f"{lg}|{s}": n for (lg, s), n in sorted(by_ls.items())},
           "coverage": dict(sorted(coverage.items())), "clubs": len(name_map), "suspicious": suspicious,
           "map": name_map}
    _write_json(root / "audit.json", out)
    print(json.dumps({k: v for k, v in out.items() if k not in ("map", "coverage")}, indent=1, default=str), flush=True)
    return 0


def _clamp_census(eligible: list[dict]) -> dict:
    cells: dict[str, dict] = {}
    by_ls: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for m in eligible:
        by_ls[(m["league"], m["season"])].append(m)
    for (lg, season), ms in sorted(by_ls.items()):
        vals = np.array([m["ship"] for m in ms])
        raw = np.array([[SCALE * v for v in m["raw"]] for m in ms])
        on_hi = np.isclose(vals, CAP, atol=5e-5)
        on_lo = np.isclose(vals, -CAP, atol=5e-5)
        clubs_any = set()
        for m, hi, lo in zip(ms, on_hi, on_lo):
            if hi[0] or lo[0] or hi[1] or lo[1]:
                clubs_any.add(m["home_key"])
            if hi[2] or lo[2] or hi[3] or lo[3]:
                clubs_any.add(m["away_key"])
        # season-end table: every club's latest appearance in the season
        latest: dict[str, tuple[str, list[float]]] = {}
        for m in ms:
            for key, pair in ((m["home_key"], m["ship"][0:2]), (m["away_key"], m["ship"][2:4])):
                if key not in latest or m["day"] >= latest[key][0]:
                    latest[key] = (m["day"], pair)
        clubs_last = {k for k, (_, pair) in latest.items() if any(abs(abs(v) - CAP) < 5e-5 for v in pair)}
        att = vals[:, [0, 2]]
        cells[f"{lg}|{season}"] = {
            "matches": len(ms), "values": int(vals.size),
            "on_plus_cap": int(on_hi.sum()), "on_minus_cap": int(on_lo.sum()),
            "share_on_clamp": float((on_hi | on_lo).mean()),
            "attack_on_plus_cap": int(np.isclose(att, CAP, atol=5e-5).sum()), "attack_values": int(att.size),
            "clubs": len(latest), "clubs_any_clamped": len(clubs_any), "clubs_clamped_season_end": len(clubs_last),
            "clubs_clamped_season_end_names": sorted(clubs_last),
            "max_abs_unclamped": float(np.abs(raw).max()),
        }
    return cells


def _final_params(eligible: list[dict], n_boot: int) -> dict:
    out = {}
    rng = np.random.default_rng(SEED)
    for arm in ("A", "B", "C", "D"):
        kind, k_fixed = ARMS[arm]
        d = Design(eligible, kind)
        point = fit(d, k_fixed)
        entry = {"k": point["k"], "mu": dict(zip(LEAGUES, map(float, point["mu"]))),
                 "eta": dict(zip(LEAGUES, map(float, point["eta"]))), "converged": point["converged"]}
        if k_fixed is None:
            ks = []
            for _ in range(n_boot):
                w = np.bincount(rng.integers(0, d.n, d.n), minlength=d.n).astype(float)
                ks.append(fit(d, None, weights=w)["k"])
            entry["k_ci"] = [float(np.quantile(ks, 0.025)), float(np.quantile(ks, 0.975))]
        out[arm] = entry
        print(f"[team_strength] full-period {arm}: k={entry['k']:.3f} {entry.get('k_ci', '')}", flush=True)
    return out


def cmd_run(args) -> int:
    print(f"[team_strength] priority={_set_idle_priority()}", flush=True)
    root = Path(args.root)
    eligible, rows, coverage, skipped, name_map, index = build(root)
    print(f"[team_strength] eligible={len(eligible)} skipped={dict(skipped)} identity={index.identity_checked} "
          f"max_err={index.identity_max_err:.2e}", flush=True)

    # Walk-forward.
    test_rows, probs, per_season_k = [], {arm: [] for arm in ARMS}, {}
    for S in TEST_SEASONS:
        train = [m for m in eligible if m["season"] < S]
        test = [m for m in eligible if m["season"] == S]
        if not test:
            continue
        per_season_k[S] = {}
        for arm, (kind, k_fixed) in ARMS.items():
            params = fit(Design(train, kind), k_fixed)
            probs[arm].append(predict_1x2(Design(test, kind), params))
            per_season_k[S][arm] = params["k"]
        test_rows.extend(test)
        print(f"[team_strength] test {S}: n={len(test)} train={len(train)} k_C={per_season_k[S]['C']:.3f} "
              f"k_D={per_season_k[S]['D']:.3f}", flush=True)
    probs = {arm: np.concatenate(v) for arm, v in probs.items()}
    close = np.array([m["close"]["p"] for m in test_rows])
    y = outcome_index(test_rows)
    ll = {arm: scores(p, y)[0] for arm, p in probs.items()}
    br = {arm: scores(p, y)[1] for arm, p in probs.items()}
    ll["close"], br["close"] = scores(close, y)

    contrasts = {"H-SCALE C-A": ("C", "A"), "H-CLAMP D-C": ("D", "C"), "literal b B-A": ("B", "A"),
                 "D-A": ("D", "A")}
    result = {"n_test": len(test_rows), "mean_logloss": {k: float(v.mean()) for k, v in ll.items()},
              "mean_brier": {k: float(v.mean()) for k, v in br.items()}, "contrasts": {}, "vs_close": {},
              "per_season_k": per_season_k}
    for name, (a, b) in contrasts.items():
        stat = boot_mean_ci(ll[a] - ll[b])
        result["contrasts"][name] = {"logloss": stat, "brier": boot_mean_ci(br[a] - br[b]), "rule_verdict": verdict(stat)}
    for arm in ARMS:
        result["vs_close"][arm] = {"logloss": boot_mean_ci(ll[arm] - ll["close"]),
                                   "brier": boot_mean_ci(br[arm] - br["close"])}

    # Subsets (secondary).
    def subset(mask, label):
        mask = np.asarray(mask)
        out = {"n": int(mask.sum())}
        if mask.sum() == 0:
            return out
        for name, (a, b) in contrasts.items():
            out[name] = boot_mean_ci((ll[a] - ll[b])[mask])
        for arm in ARMS:
            out[f"{arm}-close"] = boot_mean_ci((ll[arm] - ll["close"])[mask])
        out["mean_logloss"] = {k: float(v[mask].mean()) for k, v in ll.items()}
        return out

    lg_arr = np.array([m["league"] for m in test_rows])
    s_arr = np.array([m["season"] for m in test_rows])
    result["by_league"] = {lg: subset(lg_arr == lg, lg) for lg in LEAGUES}
    result["by_season"] = {int(S): subset(s_arr == S, S) for S in TEST_SEASONS}
    result["big5"] = subset(np.isin(lg_arr, BIG5), "big5")
    result["goals_leagues"] = subset(np.isin(lg_arr, GOALS), "goals")

    # Favourite calibration: the side (home/away) with the highest de-vigged close probability.
    fav_side = np.where(close[:, 0] >= close[:, 2], 0, 2)
    rows_idx = np.arange(len(y))
    fav_won = (y == fav_side).astype(float)
    p_close_fav = close[rows_idx, fav_side]
    fav = {"all": {"n": int(len(y)), "actual": float(fav_won.mean()), "close": float(p_close_fav.mean())}}
    top = p_close_fav >= np.quantile(p_close_fav, 0.9)
    fav["top_decile"] = {"n": int(top.sum()), "actual": float(fav_won[top].mean()), "close": float(p_close_fav[top].mean())}
    for arm in ARMS:
        pf = probs[arm][rows_idx, fav_side]
        fav["all"][arm] = float(pf.mean())
        fav["top_decile"][arm] = float(pf[top].mean())
    for S in (2026,):
        m = s_arr == S
        if m.any():
            fav[f"season_{S}"] = {"n": int(m.sum()), "actual": float(fav_won[m].mean()), "close": float(p_close_fav[m].mean()),
                                  **{arm: float(probs[arm][rows_idx, fav_side][m].mean()) for arm in ARMS}}
    result["favourites"] = fav

    # Spread of the model's 1X2 (descriptive): sd of p(home) - p(away).
    result["spread_sd_home_minus_away"] = {arm: float(np.std(p[:, 0] - p[:, 2])) for arm, p in probs.items()}
    result["spread_sd_home_minus_away"]["close"] = float(np.std(close[:, 0] - close[:, 2]))

    result["clamp_census"] = _clamp_census(eligible)
    result["full_period"] = _final_params(eligible, args.n_boot)
    result["eligible"] = len(eligible)
    result["skipped"] = dict(skipped)
    result["identity"] = {"tables": index.identity_checked, "max_err": index.identity_max_err}
    _write_json(root / "report.json", result)
    printable = {k: v for k, v in result.items() if k not in ("clamp_census", "by_league", "by_season")}
    print(json.dumps(printable, indent=1, default=str), flush=True)
    return 0


def cmd_engine(args) -> int:
    """Deviation 2 (descriptive, no verdict): the ENGINE's gain on the shipped rating.

    The H37 harness (`scripts/backtest_soccer_h2h_calibration.py`, lane soccer-1x2-ratings-xg-source,
    no market anchoring) dumped the served sim's per-match home/away goal means for 2025-26. Regress
    log(home_mean / away_mean) on (A_h - D_a) - (A_a - D_h) at the shipped rating, joined to this
    run's as-of ratings: the slope is the engine's k, comparable to arm C's refit k.
    """
    print(f"[team_strength] priority={_set_idle_priority()}", flush=True)
    root = Path(args.root)
    eligible, *_ = build(root)
    by_key = {}
    for m in eligible:
        by_key.setdefault((m["league"], m["day"]), []).append(m)
    joined, unjoined = [], Counter()
    for path in sorted(Path(args.dumps).glob("h2h_armA_*.jsonl")):
        if path.stem.endswith("_goals"):
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            cands = by_key.get((r.get("league"), r.get("date")), [])
            hit = [m for m in cands if match_team_name(r["home_team"], [m["home"]]) and match_team_name(r["away_team"], [m["away"]])]
            if len(hit) != 1 or not r.get("model_home_mean") or not r.get("model_away_mean"):
                unjoined[r.get("league")] += 1
                continue
            joined.append((hit[0], r))
    out = {"joined": len(joined), "unjoined": dict(unjoined), "by_arm_kind": {}}
    for kind in ("clamped", "raw"):
        d = Design([m for m, _ in joined], kind)
        x = d.gap_h - d.gap_a
        yv = np.log(np.array([r["model_home_mean"] / r["model_away_mean"] for _, r in joined]))
        X = np.column_stack([np.ones_like(x), x])
        beta = np.linalg.lstsq(X, yv, rcond=None)[0]
        rng = np.random.default_rng(SEED)
        bs = []
        for _ in range(1000):
            i = rng.integers(0, len(x), len(x))
            bs.append(np.linalg.lstsq(X[i], yv[i], rcond=None)[0][1])
        resid = yv - X @ beta
        out["by_arm_kind"][kind] = {"slope_k_engine": float(beta[1]), "ci": [float(np.quantile(bs, 0.025)), float(np.quantile(bs, 0.975))],
                                    "intercept": float(beta[0]), "r2": float(1 - resid.var() / yv.var())}
    # The engine's own 1X2 on the joined matches, against the close (descriptive).
    p_eng = np.array([[r["model_home"], r["model_draw"], r["model_away"]] for _, r in joined])
    p_eng = p_eng / p_eng.sum(axis=1, keepdims=True)
    close = np.array([m["close"]["p"] for m, _ in joined])
    yy = outcome_index([m for m, _ in joined])
    out["engine_minus_close_logloss"] = boot_mean_ci(scores(p_eng, yy)[0] - scores(close, yy)[0])
    out["engine_logloss"] = float(scores(p_eng, yy)[0].mean())
    _write_json(root / "engine_gain.json", out)
    print(json.dumps(out, indent=1), flush=True)
    return 0


# --------------------------------------------------------------------------- stage 1: rating-INPUT variants
# Registration: `.syndicate/findings_2026-10-16_soccer_rating_inputs.md` section 1 (734d604e).

GATE_N = 10                      # build_soccer_artifacts._FEW_MATCH_GATE (ON in production since 2026-10-07)
P0 = -0.18 / SCALE               # PROMOTED_TEAM_RATING in raw-deviation space
SHIPPED = (("wf", 1.0), ("h", math.inf), ("c", math.inf), ("s", "gate"), ("p", "p0"))
GRIDS = {"W": ("wf", (1.0, 1 / 3, 2 / 3, 4 / 3, 2.0)), "R": ("h", (math.inf, 40, 20, 10)),
         "B": ("c", (math.inf, 40, 20, 10, 5)), "S": ("s", ("gate", 5, 10, 20, 40)), "P": ("p", ("p0", "fitted"))}
ORDER = ("W", "R", "B", "S", "P")


def _cfg(**over) -> tuple:
    base = dict(SHIPPED)
    base.update(over)
    return tuple((k, base[k]) for k, _ in SHIPPED)


def _cfg_label(cfg: tuple) -> str:
    d, ship = dict(cfg), dict(SHIPPED)
    parts = [f"{k}={round(v, 3) if isinstance(v, float) else v}" for k, v in d.items() if v != ship[k]]
    return ",".join(parts) or "shipped"


def build_full(root: Path):
    """Every football-data match with a close: keys plus production's RAW rating and row count per side.

    Unlike `build`, a side with no rating (0 rows in the depth: a promoted club) is kept -- production gives it
    PROMOTED_TEAM_RATING -- and so is a side with 1..9 rows (production's few-match gate). Wrong pairings are
    excluded as in `build` (deviation 1 of the compression study).
    """
    index = RatingIndex(root.parent / "uefa-offsets" / "prod_history" if not (root / "prod_history").exists()
                        else root / "prod_history")
    rows, _coverage = load_fd_matches(root / "fd_raw")
    out, skipped = [], Counter()
    for row in sorted(rows, key=lambda r: (r["league"], r["day"])):
        lg, season, cutoff = row["league"], row["season"], row["day"]
        raw = index.table(lg, season, cutoff, raw=True)
        keys, vals, ns, wrong = [], [], [], False
        for side in ("home", "away"):
            fd_name = row[side]
            alias = ALIASES.get((lg, fd_name))
            key = alias if alias in raw else match_team_name(fd_name, list(raw))
            if key and ((lg in GOALS and key != fd_name) or (lg, fd_name, key) in WRONG_PAIRINGS):
                wrong = True
            e = raw.get(key) if key else None
            keys.append(key if e else None)
            vals.append([e["attack_rating"], e["defense_rating"]] if e else None)
            ns.append(int(e["matches"]) if e else 0)
        if wrong:
            skipped["wrong_pairing"] += 1
            continue
        if row["close"] is None:
            skipped["no_close"] += 1
            continue
        out.append({**row, "home_key": keys[0], "away_key": keys[1], "prod_raw": vals, "prod_n": ns})
    return out, skipped, index


class TeamStore:
    """Per-league, per-club chronological rating rows, as production's subset+sort sees them."""

    def __init__(self, prod_root: Path):
        self.teams: dict[str, dict[str, dict]] = {}
        self.season_rows: dict[str, dict[int, dict]] = {}
        self._tables: dict[tuple, list] = {}
        for lg in LEAGUES:
            if lg in BIG5:
                raw = _read_csvs(sorted((prod_root / lg / "team_history").glob("teams_*.csv")))
            else:
                raw = team_rows_from_match_history(_read_csvs(sorted((prod_root / lg / "history").glob("matches_*.csv"))))
            per: dict[str, list] = defaultdict(list)
            for r in raw:
                day = _as_iso_day(r.get("date"))
                team = str(r.get("team") or "").strip()
                xf, xa = loaders._safe_float(r.get("xg_for")), loaders._safe_float(r.get("xg_against"))
                if not day or not team or xf is None or xa is None:
                    continue
                per[team].append((date.fromisoformat(day).toordinal(), int(float(r["season"])), xf, xa))
            teams = {}
            for team, items in per.items():
                items.sort(key=lambda t: t[0])  # stable: same tie order as production's sort of the subset
                arr = np.array(items, dtype=float)
                season = arr[:, 1].astype(int)
                assert np.all(np.diff(season) >= 0), f"{lg} {team}: season labels not monotone in day"
                teams[team] = {"day": arr[:, 0], "season": season, "xf": arr[:, 2], "xa": arr[:, 3],
                               "cf": np.concatenate([[0.0], np.cumsum(arr[:, 2])]),
                               "ca": np.concatenate([[0.0], np.cumsum(arr[:, 3])])}
            self.teams[lg] = teams
            # Per league-season pooled rows, for the promoted-club prior.
            seas: dict[int, dict] = {}
            for team, t in teams.items():
                for s in np.unique(t["season"]):
                    m = t["season"] == s
                    e = seas.setdefault(int(s), {"sum_f": 0.0, "n": 0, "teams": {}})
                    e["sum_f"] += float(t["xf"][m].sum())
                    e["n"] += int(m.sum())
                    e["teams"][team] = (float(t["xf"][m].sum()), float(t["xa"][m].sum()), int(m.sum()))
            self.season_rows[lg] = seas

    def table(self, lg: str, season: int, cutoff: str) -> list:
        key = (lg, season, cutoff)
        if key not in self._tables:
            c = date.fromisoformat(cutoff).toordinal()
            rows = []
            for team, t in self.teams[lg].items():
                lo = int(np.searchsorted(t["season"], season - SEASONS_BACK[lg], "left"))
                hi = int(np.searchsorted(t["day"], c, "left"))
                if hi > lo:
                    cur = int(np.searchsorted(t["season"], season, "left"))
                    rows.append((team, lo, hi, max(cur, lo)))
            self._tables[key] = rows
        return self._tables[key]

    def promoted_prior(self, lg: str, before_season: int) -> tuple[float, float]:
        """Mean raw (x_att, x_def) of PROMOTED clubs over their promotion-season rows, seasons < before_season."""
        seas = self.season_rows[lg]
        num_f = num_a = 0.0
        n = 0
        for s, e in seas.items():
            if s >= before_season or (s - 1) not in seas:
                continue
            mu = e["sum_f"] / e["n"]
            earlier = set()
            for b in range(s - SEASONS_BACK[lg], s):
                earlier |= set(seas.get(b, {"teams": {}})["teams"])
            for team, (sf, sa, k) in e["teams"].items():
                if team not in earlier:
                    num_f += sf / mu
                    num_a += sa / mu
                    n += k
        if n == 0:
            return (P0, P0)
        return (num_f / n - 1.0, 1.0 - num_a / n)


def variant_features(store: TeamStore, matches: list[dict], cfg: tuple, priors: dict | None) -> dict:
    """Shipped-space ratings [A_h, D_h, A_a, D_a] under one input config, plus raw x and row counts."""
    c = dict(cfg)
    r = np.zeros((len(matches), 4))
    raw = np.full((len(matches), 4), np.nan)
    n_out = np.zeros((len(matches), 2), dtype=int)
    mu_cache: dict[tuple, float] = {}
    for i, m in enumerate(matches):
        lg, season, cutoff = m["league"], m["season"], m["day"]
        W = int(round(WINDOW[lg] * c["wf"]))
        tab = store.table(lg, season, cutoff)
        mk = (lg, season, cutoff, W)
        if mk not in mu_cache:
            tot = cnt = 0.0
            for team, lo, hi, _cur in tab:
                a = max(lo, hi - W)
                t = store.teams[lg][team]
                tot += t["cf"][hi] - t["cf"][a]
                cnt += hi - a
            mu = tot / cnt if cnt else 1.35
            mu_cache[mk] = mu if mu > 0 else 1.35
        mu = mu_cache[mk]
        by_team = {team: (lo, hi, cur) for team, lo, hi, cur in tab}
        prior = (priors or {}).get(lg, (P0, P0)) if c["p"] == "fitted" else (P0, P0)
        for j, key in enumerate((m["home_key"], m["away_key"])):
            n, est, x = 0, False, None
            if key is not None and key in by_team:
                lo, hi, cur = by_team[key]
                t = store.teams[lg][key]
                a = max(lo, hi - W)
                n = hi - a
                est = cur > lo
                if c["h"] == math.inf:
                    mf, ma = (t["cf"][hi] - t["cf"][a]) / n, (t["ca"][hi] - t["ca"][a]) / n
                else:
                    w = 0.5 ** (np.arange(n)[::-1] / c["h"])
                    mf, ma = float(w @ t["xf"][a:hi] / w.sum()), float(w @ t["xa"][a:hi] / w.sum())
                x = [mf / mu - 1.0, 1.0 - ma / mu]
                raw[i, 2 * j:2 * j + 2] = x
                if c["c"] != math.inf and hi > cur:
                    ncur = hi - cur
                    b = ncur / (ncur + c["c"])
                    xc = [(t["cf"][hi] - t["cf"][cur]) / ncur / mu - 1.0, 1.0 - (t["ca"][hi] - t["ca"][cur]) / ncur / mu]
                    x = [(1 - b) * x[0] + b * xc[0], (1 - b) * x[1] + b * xc[1]]
            n_out[i, j] = n
            if c["s"] == "gate":
                if n < GATE_N:
                    x = list(prior)
            elif c["s"] == "none":          # production before 2026-10-07: only _fill_promoted
                if n == 0:
                    x = list(prior)
            else:
                n0 = float(c["s"])
                target = (0.0, 0.0) if est else prior
                x = [((n * x[k]) if n else 0.0) / (n + n0) + n0 * target[k] / (n + n0) for k in range(2)]
            r[i, 2 * j] = round(_clamp_ship(x[0]), 4)
            r[i, 2 * j + 1] = round(_clamp_ship(x[1]), 4)
    return {"r": r, "raw": raw, "n": n_out}


def _clamp_ship(x: float) -> float:
    return max(-CAP, min(CAP, SCALE * x))


class RDesign(Design):
    def __init__(self, matches: list[dict], r: np.ndarray):  # noqa: D107 - shares Design's arrays
        lg_idx = {lg: i for i, lg in enumerate(LEAGUES)}
        self.n = len(matches)
        self.league = np.array([lg_idx[m["league"]] for m in matches], dtype=int)
        self.gap_h = r[:, 0] - r[:, 3]
        self.gap_a = r[:, 2] - r[:, 1]
        self.hg = np.array([m["hg"] for m in matches], dtype=float)
        self.ag = np.array([m["ag"] for m in matches], dtype=float)


class Stage1:
    def __init__(self, store: TeamStore, matches: list[dict]):
        self.store, self.matches = store, matches
        self.season = np.array([m["season"] for m in matches])
        self.y = outcome_index(matches)
        self._feat: dict[tuple, dict] = {}
        self._fit: dict[tuple, tuple] = {}

    def priors(self, S: int) -> dict:
        return {lg: self.store.promoted_prior(lg, S) for lg in LEAGUES}

    def feats(self, cfg: tuple, S: int | None) -> dict:
        key = (cfg, S if dict(cfg)["p"] == "fitted" else None)
        if key not in self._feat:
            self._feat[key] = variant_features(self.store, self.matches, cfg,
                                               self.priors(S) if dict(cfg)["p"] == "fitted" else None)
        return self._feat[key]

    def season_fit(self, cfg: tuple, S: int, k_fixed: float | None = None) -> tuple[float, np.ndarray]:
        """(in-sample train log loss, held-out probs for season S)."""
        key = (cfg, S, k_fixed)
        if key not in self._fit:
            r = self.feats(cfg, S)["r"]
            tr, te = self.season < S, self.season == S
            mtr = [m for m, f in zip(self.matches, tr) if f]
            mte = [m for m, f in zip(self.matches, te) if f]
            params = fit(RDesign(mtr, r[tr]), k_fixed)
            ll_tr = float(scores(predict_1x2(RDesign(mtr, r[tr]), params), self.y[tr])[0].mean())
            self._fit[key] = (ll_tr, predict_1x2(RDesign(mte, r[te]), params), params["k"])
        return self._fit[key][:2]


def _metrics(probs: dict, y: np.ndarray, close: np.ndarray, masks: dict) -> dict:
    ll = {a: scores(p, y)[0] for a, p in probs.items()}
    br = {a: scores(p, y)[1] for a, p in probs.items()}
    ll["close"], br["close"] = scores(close, y)
    out = {"mean_logloss": {a: float(v.mean()) for a, v in ll.items()},
           "mean_brier": {a: float(v.mean()) for a, v in br.items()}, "vs_Cstar": {}, "vs_close": {}}
    gap_c = float((ll["C*"] - ll["close"]).mean())
    for a in probs:
        if a != "C*":
            st = boot_mean_ci(ll[a] - ll["C*"])
            out["vs_Cstar"][a] = {"logloss": st, "brier": boot_mean_ci(br[a] - br["C*"]),
                                  "rule_verdict": verdict(st)}
        vc = boot_mean_ci(ll[a] - ll["close"])
        out["vs_close"][a] = {"logloss": vc, "share_of_Cstar_gap_closed": 1.0 - vc["mean"] / gap_c}
    fav_side = np.where(close[:, 0] >= close[:, 2], 0, 2)
    idx = np.arange(len(y))
    won = (y == fav_side).astype(float)
    pc = close[idx, fav_side]
    top = pc >= np.quantile(pc, 0.9)
    fav = {"all": {"n": int(len(y)), "actual": float(won.mean()), "close": float(pc.mean())},
           "top_decile": {"n": int(top.sum()), "actual": float(won[top].mean()), "close": float(pc[top].mean())}}
    for a, p in probs.items():
        fav["all"][a] = float(p[idx, fav_side].mean())
        fav["top_decile"][a] = float(p[idx, fav_side][top].mean())
    out["favourites"] = fav
    out["spread_sd_home_minus_away"] = {a: float(np.std(p[:, 0] - p[:, 2])) for a, p in probs.items()}
    out["spread_sd_home_minus_away"]["close"] = float(np.std(close[:, 0] - close[:, 2]))
    out["subsets"] = {}
    for name, mk in masks.items():
        if mk.sum() == 0:
            continue
        sub = {"n": int(mk.sum()), "mean_logloss": {a: float(v[mk].mean()) for a, v in ll.items()}}
        for a in probs:
            if a != "C*":
                sub[f"{a}-C*"] = boot_mean_ci((ll[a] - ll["C*"])[mk], n_boot=500)
        sub["C*-close"] = boot_mean_ci((ll["C*"] - ll["close"])[mk], n_boot=500)
        out["subsets"][name] = sub
    return out


def cmd_stage1(args) -> int:
    print(f"[stage1] priority={_set_idle_priority()}", flush=True)
    root = Path(args.root)
    prod_root = root / "prod_history" if (root / "prod_history").exists() else root.parent / "uefa-offsets" / "prod_history"
    matches, skipped, _index = build_full(root)
    store = TeamStore(prod_root)
    st = Stage1(store, matches)
    print(f"[stage1] FULL matches={len(matches)} skipped={dict(skipped)}", flush=True)

    # Registered identity check: shipped config reproduces production's raw x and row count, every rated side.
    ship = _cfg()
    f0 = st.feats(ship, None)
    max_err, checked = 0.0, 0
    for i, m in enumerate(matches):
        for j in range(2):
            if m["prod_raw"][j] is None:
                assert f0["n"][i, j] == 0, f"{m['league']} {m['day']} side {j}: production unrated, variant n={f0['n'][i, j]}"
                continue
            if f0["n"][i, j] != m["prod_n"][j]:
                raise SystemExit(f"IDENTITY FAILED (n) {m['league']} {m['day']} {m['home']}-{m['away']} side {j}: "
                                 f"{f0['n'][i, j]} vs production {m['prod_n'][j]}")
            err = float(np.max(np.abs(f0["raw"][i, 2 * j:2 * j + 2] - np.array(m["prod_raw"][j]))))
            max_err = max(max_err, err)
            checked += 1
            if err > 2e-4:
                raise SystemExit(f"IDENTITY FAILED (x) {m['league']} {m['day']} {m['home']}-{m['away']} side {j}: "
                                 f"{f0['raw'][i, 2 * j:2 * j + 2]} vs production {m['prod_raw'][j]}")
    print(f"[stage1] identity PASSED: {checked} rated sides, max err {max_err:.2e}", flush=True)

    held = np.isin(st.season, list(TEST_SEASONS))
    prod_n = np.array([m["prod_n"] for m in matches])
    core = (prod_n >= GATE_N).all(axis=1)
    coverage = {"full": len(matches), "held_out": int(held.sum()), "core_held_out": int((core & held).sum()),
                "promoted_held_out": int((~core & held).sum()), "skipped": dict(skipped),
                "identity": {"sides": checked, "max_err": max_err},
                "sides_by_n_held_out": {"0": int((prod_n[held] == 0).sum()), "1-9": int(((prod_n[held] > 0) & (prod_n[held] < GATE_N)).sum()),
                                        ">=10": int((prod_n[held] >= GATE_N).sum())},
                "close_source_held_out": dict(Counter(m["close"]["source"] for m, h in zip(matches, held) if h)),
                "by_season": dict(Counter(int(s) for s in st.season))}

    # Registered reachability check: every non-shipped grid value changes >= 1% of FULL matches.
    reach = {}
    for fam, (param, grid) in GRIDS.items():
        for v in grid[1:]:
            cfg = _cfg(**{param: v})
            fv = st.feats(cfg, 2026)
            changed = float((np.abs(fv["r"] - f0["r"]) > 1e-6).any(axis=1).mean())
            reach[f"{fam}:{_cfg_label(cfg)}"] = changed
    coverage["reachability_share_changed"] = reach
    _write_json(root / "stage1_coverage.json", coverage)
    print(json.dumps(coverage, indent=1), flush=True)
    if args.coverage_only:
        return 0

    tests = [S for S in TEST_SEASONS if (st.season == S).any()]
    probs: dict[str, list] = defaultdict(list)
    selections: dict[str, dict] = defaultdict(dict)
    nogate = _cfg(s="none")
    for S in tests:
        probs["C*"].append(st.season_fit(ship, S)[1])
        probs["C_nogate"].append(st.season_fit(nogate, S)[1])
        probs["N"].append(st.season_fit(ship, S, k_fixed=0.0)[1])
        # Every grid point (descriptive) and each family's walk-forward selection (the verdict arm).
        for fam, (param, grid) in GRIDS.items():
            best = None
            for v in grid:
                cfg = _cfg(**{param: v})
                ll_tr, p = st.season_fit(cfg, S)
                if v != grid[0]:
                    probs[f"{fam}:{_cfg_label(cfg)}"].append(p)
                if best is None or ll_tr < best[0] - 1e-12:
                    best = (ll_tr, v, p)
            probs[f"{fam}*"].append(best[2])
            selections[fam][S] = best[1]
        # Cumulative, fixed order W -> R -> B -> S -> P.
        cur = dict(SHIPPED)
        for fam in ORDER:
            param, grid = GRIDS[fam]
            best = None
            for v in grid:
                cand = tuple((k, v if k == param else cur[k]) for k, _ in SHIPPED)
                ll_tr, p = st.season_fit(cand, S)
                if best is None or ll_tr < best[0] - 1e-12:
                    best = (ll_tr, v, p)
            cur[param] = best[1]
        cum = tuple((k, cur[k]) for k, _ in SHIPPED)
        probs["CUM"].append(st.season_fit(cum, S)[1])
        selections["CUM"][S] = _cfg_label(cum)
        print(f"[stage1] test {S}: n={(st.season == S).sum()} " + " ".join(f"{f}={selections[f][S]}" for f in ORDER)
              + f" CUM={selections['CUM'][S]}", flush=True)

    probs = {a: np.concatenate(v) for a, v in probs.items()}
    test_matches = [m for S in tests for m, s in zip(matches, st.season) if s == S]
    order_idx = np.concatenate([np.where(st.season == S)[0] for S in tests])
    y = st.y[order_idx]
    close = np.array([m["close"]["p"] for m in test_matches])
    lg_arr = np.array([m["league"] for m in test_matches])
    s_arr = st.season[order_idx]
    core_t = core[order_idx]
    masks = {"CORE": core_t, "PROMOTED": ~core_t, "big5": np.isin(lg_arr, BIG5), "goals": np.isin(lg_arr, GOALS),
             **{f"league:{lg}": lg_arr == lg for lg in LEAGUES}, **{f"season:{S}": s_arr == S for S in tests}}
    result = {"coverage": coverage, "selections": {f: {int(k): v for k, v in d.items()} for f, d in selections.items()},
              "k_by_season": {f"{_cfg_label(cfg)}|{S}|{kf}": v[2] for (cfg, S, kf), v in st._fit.items()},
              **_metrics(probs, y, close, masks)}
    _write_json(root / "stage1_report.json", result)
    for a in sorted(probs):
        vc = result["vs_close"][a]["logloss"]
        line = f"[stage1] {a:28s} LL {result['mean_logloss'][a]:.4f} vs close {vc['mean']:+.4f}"
        if a in result["vs_Cstar"]:
            s = result["vs_Cstar"][a]["logloss"]
            line += f" vs C* {s['mean']:+.4f} [{s['ci'][0]:+.4f},{s['ci'][1]:+.4f}] {result['vs_Cstar'][a]['rule_verdict']}"
        line += f" top-dec {result['favourites']['top_decile'][a]:.3f} sd {result['spread_sd_home_minus_away'][a]:.3f}"
        print(line, flush=True)
    print(f"[stage1] close LL {result['mean_logloss']['close']:.4f}; top-dec actual "
          f"{result['favourites']['top_decile']['actual']:.3f} close {result['favourites']['top_decile']['close']:.3f}", flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("audit")
    a.add_argument("--root", required=True)
    r = sub.add_parser("run")
    r.add_argument("--root", required=True)
    r.add_argument("--n-boot", type=int, default=1000)
    e = sub.add_parser("engine")
    e.add_argument("--root", required=True)
    e.add_argument("--dumps", default="C:/tmp/soccer-lpb")
    s1 = sub.add_parser("stage1")
    s1.add_argument("--root", required=True)
    s1.add_argument("--coverage-only", action="store_true")
    args = parser.parse_args()
    return {"audit": cmd_audit, "run": cmd_run, "engine": cmd_engine, "stage1": cmd_stage1}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
