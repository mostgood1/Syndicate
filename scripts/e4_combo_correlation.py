"""E4: does the sims' JOINT distribution predict same-game co-occurrence better than independence? (lane `e4-combo-correlation`).

Decision Engine plan §4 E4 / §2 P7. PRE-REGISTERED in `.syndicate/findings_2026-10-26_e4_combo_correlation_preregistration.md`
(`9f8d759e`, amendment A1 `83f2e460`, A2) before any sim x market x outcome join. Every constant below is the registered one;
change one only through a dated amendment in that file.

READ-ONLY. Reads the fleet data root and sends only unauthenticated GETs to public outcome endpoints (StatsAPI boxscore,
ESPN summaries), cached under --cache. Imports no order, execution or credential code.

    nice -n 19 /home/amyn/.venvs/syndicate/bin/python scripts/e4_combo_correlation.py \
        --data-root ~/syndicate-prod/data --out /mnt/c/tmp/e4/report.json --cache /mnt/c/tmp/e4/cache

Three arms on IDENTICAL market marginals and one functional form (Gaussian copula), differing only in rho:
(a) independence rho=0; (b) the sim's persisted joint re-anchored to the market marginals; (c) the SGP builders' measured
copula cells. Score: 4-cell log loss per pair, game-clustered SE (CR1), Holm across the 7 primary cells.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import os
import re
import statistics
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.nfl.sgp import joint_over, rho_for  # noqa: E402
from syndicate.features.shared.nba_prop_calibration import combo_scale  # noqa: E402

UTC = timezone.utc

# ----------------------------------------------------------------------------- registered constants
WINDOW_START = date(2026, 9, 30)          # market close dated 09-30 .. 10-25 (§2)
WINDOW_END = date(2026, 10, 25)
NBA_REGULAR_FROM = date(2026, 10, 20)     # SP cells are regular season; 10-03..10-16 is the secondary preseason cell
P_MIN, P_MAX = 0.02, 0.98
MIN_GAMES, MIN_PAIRS = 20, 200
RHO_CLIP = 0.95
NBA_PRA_TOL = 0.25
CELL_CLIP = 1e-6
BOOT = 500
SEED = 20261026
ALPHA = 0.05
GAME_MATCH_HOURS = 6.0
VENUES = ("kalshi", "polymarket", "novig", "prophetx", "betfair_ex", "matchbook", "sporttrade")

MLB_STAT = {"batter_hits": "hits", "batter_total_bases": "total_bases", "batter_home_runs": "home_runs",
            "batter_rbis": "rbi", "batter_strikeouts": "strikeouts"}
MLB_BOX = {"hits": "hits", "total_bases": "totalBases", "home_runs": "homeRuns", "rbi": "rbi", "strikeouts": "strikeOuts"}
MLB_NESTED = {frozenset(x) for x in (("hits", "total_bases"), ("home_runs", "hits"), ("home_runs", "total_bases"),
                                      ("home_runs", "rbi"))}
NBA_VEC = {"player_points": (1, 0, 0), "player_rebounds": (0, 1, 0), "player_assists": (0, 0, 1),
           "player_points_rebounds": (1, 1, 0), "player_points_assists": (1, 0, 1),
           "player_rebounds_assists": (0, 1, 1), "player_points_rebounds_assists": (1, 1, 1)}
NBA_SGP = {"player_points": "PTS", "player_rebounds": "REB", "player_assists": "AST", "player_points_rebounds": "PR",
           "player_points_assists": "PA", "player_rebounds_assists": "RA", "player_points_rebounds_assists": "PRA"}
SOCCER_LEAGUES = {"epl": "eng.1", "la_liga": "esp.1", "bundesliga": "ger.1", "serie_a": "ita.1", "ligue_1": "fra.1",
                  "eredivisie": "ned.1", "primeira_liga": "por.1", "belgian_pro_league": "bel.1",
                  "championship": "eng.2", "mls": "usa.1"}
PRIMARY = (("mlb", "SP-nested"), ("mlb", "SP-other"), ("mlb", "TM"), ("mlb", "OP"),
           ("nba", "SP-disjoint"), ("nba", "SP-nested"), ("soccer", "GL"))
TWO_SIDED = {"over": ("over", "under"), "yes": ("yes", "no"), "home": ("home", "away")}


# ----------------------------------------------------------------------------- small pure helpers
def norm_name(v: Any) -> str:
    s = unicodedata.normalize("NFKD", str(v or ""))
    s = "".join(c for c in s if not unicodedata.combining(c)).lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]+", " ", s.replace(".", " ").replace("'", ""))
    toks = [t for t in s.split() if t not in {"jr", "sr", "ii", "iii", "iv", "v"}]
    return " ".join(toks)


def initial_last(v: Any) -> str:
    toks = norm_name(v).split()
    return f"{toks[0][0]} {toks[-1]}" if len(toks) >= 2 else norm_name(v)


_TEAM_DROP = {"fc", "afc", "cf", "sc", "ac", "the", "club", "de", "cd", "sd", "ud", "rc", "sv", "fk", "bk", "vfb", "vfl",
              "tsg", "ssc", "as", "us", "rcd", "ca", "1", "04", "1899", "05", "and", "hove", "albion", "calcio"}


def team_tokens(v: Any) -> set[str]:
    return {t for t in norm_name(v).split() if t not in _TEAM_DROP and len(t) > 1}


def name_lookup(table: Mapping[str, Any], name: str) -> Any:
    """Exact normalised name, else a UNIQUE first-initial + last-name match; never a guess between two."""
    if name in table:
        return table[name]
    il = initial_last(name)
    hits = [k for k in table if initial_last(k) == il]
    return table[hits[0]] if len(hits) == 1 else None


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def parse_ts(v: Any) -> datetime | None:
    if v in (None, ""):
        return None
    try:
        s = str(v).replace("Z", "+00:00")
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}\+00:00", s):
            s = s.replace("+00:00", ":00+00:00")
        d = datetime.fromisoformat(s)
        return d if d.tzinfo else d.replace(tzinfo=UTC)
    except ValueError:
        return None


def american_prob(price: Any) -> float | None:
    """Implied probability INCLUDING vig; American odds only (|price| >= 100), else None."""
    try:
        p = float(price)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(p) or abs(p) < 100:
        return None
    return 100.0 / (p + 100.0) if p > 0 else -p / (-p + 100.0)


def is_venue(book: Any) -> bool:
    b = str(book or "").lower()
    return any(b.startswith(v) for v in VENUES)


def norm_line(v: Any) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return round(x, 2) if math.isfinite(x) else None


def devig_book(prices: Mapping[str, Any], sides: tuple[str, ...]) -> dict[str, float] | None:
    """Multiplicative de-vig of ONE book's full outcome set; None unless every side is quoted."""
    imp = {s: american_prob(prices.get(s)) for s in sides}
    if any(v is None for v in imp.values()):
        return None
    tot = sum(imp.values())
    return {s: v / tot for s, v in imp.items()} if tot > 0 else None


def main_line_leg(by_line: Mapping[Any, Mapping[str, Mapping[str, Any]]], sides: tuple[str, ...],
                  event_side: str) -> dict[str, Any] | None:
    """§3: per line, per book de-vig -> median; keep the line with the most two-sided books (tie: p nearest 0.5)."""
    best = None
    for line, books in by_line.items():
        ps = [d[event_side] for d in (devig_book(pr, sides) for pr in books.values()) if d]
        if not ps:
            continue
        p = float(statistics.median(ps))
        key = (len(ps), -abs(p - 0.5))
        if best is None or key > best[0]:
            best = (key, {"line": line, "p": p, "n_books": len(ps)})
    return best[1] if best else None


# ----------------------------------------------------------------------------- dependence: the three arms' rho
def spearman_to_gauss(rs: float) -> float:
    return 2.0 * math.sin(math.pi * rs / 6.0)


def packed_index(i: int, j: int) -> int:
    """`sim.joint.corr_lower` packs the strict lower triangle row-major: (i, j), i > j -> i*(i-1)/2 + j."""
    if i == j:
        raise ValueError("diagonal")
    if i < j:
        i, j = j, i
    return i * (i - 1) // 2 + j


def joint_rho_s(joint: Mapping[str, Any], index: Mapping[str, int], a: str, b: str) -> float | None:
    if a not in index or b not in index or a == b:
        return None
    v = joint["corr_lower"][packed_index(index[a], index[b])]
    if v is None or v == joint.get("undefined", -32768):
        return None
    return float(v) / float(joint.get("scale") or 1000)


def composed_rho(r_xh: float, r_xa: float, r_ha: float, kind: str) -> float | None:
    """Secondary MLB types, latent equal-variance composition (§4). kind 'total': X with H+A; 'own_win': X with own-opp
    where r_xh is X with its OWN team and r_xa with the opponent."""
    if kind == "total":
        den = math.sqrt(max(2.0 * (1.0 + r_ha), 1e-9))
        return (r_xh + r_xa) / den
    den = math.sqrt(max(2.0 * (1.0 - r_ha), 1e-9))
    return (r_xh - r_xa) / den


def ladder_var(payload: Mapping[str, Any] | None) -> float | None:
    dist = (payload or {}).get("distribution")
    if not isinstance(dist, Mapping) or not dist:
        return None
    vals, cnts = [], []
    for k, c in dist.items():
        try:
            vals.append(float(k))
            cnts.append(float(c))
        except (TypeError, ValueError):
            return None
    n = sum(cnts)
    if n <= 1:
        return None
    m = sum(v * c for v, c in zip(vals, cnts)) / n
    return sum(c * (v - m) ** 2 for v, c in zip(vals, cnts)) / n


def nba_cov(row: Mapping[str, Any], file_k: Mapping[str, float] | None, applied: bool) -> tuple[np.ndarray | None, str]:
    """§4: the raw 3x3 covariance of (PTS, REB, AST) backed out of the ladders built from the same draws, undoing the
    calibration's widening. Returns (Sigma, reason)."""
    stamp = row.get("nba_prop_calibration") if isinstance(row.get("nba_prop_calibration"), Mapping) else {}
    sd_scale = stamp.get("sd_scale") if isinstance(stamp.get("sd_scale"), Mapping) else {}
    orig = {}
    for s in ("pts", "reb", "ast", "pra"):
        try:
            sd = float(row.get(f"{s}_sd"))
        except (TypeError, ValueError):
            return None, "no_sd"
        sc = float(sd_scale.get(s) or 1.0)
        orig[s] = sd / sc
    if min(orig["pts"], orig["reb"], orig["ast"]) <= 0:
        return None, "nonpositive_var"
    lad = row.get("prop_ladders") if isinstance(row.get("prop_ladders"), Mapping) else {}
    var = {s: orig[s] ** 2 for s in ("pts", "reb", "ast")}
    cov = {}
    for key, (x, y) in (("pr", ("pts", "reb")), ("pa", ("pts", "ast")), ("ra", ("reb", "ast"))):
        v = ladder_var(lad.get(key))
        if v is None:
            return None, "no_combo_ladder"
        kk = 1.0
        if applied and file_k:
            kk = combo_scale((x, y), orig, file_k) or 1.0
        cov[key] = (v / (kk * kk) - var[x] - var[y]) / 2.0
    sig = np.array([[var["pts"], cov["pr"], cov["pa"]],
                    [cov["pr"], var["reb"], cov["ra"]],
                    [cov["pa"], cov["ra"], var["ast"]]])
    recon = float(sig.sum())
    raw_pra = orig["pra"] ** 2
    if raw_pra <= 0 or abs(recon - raw_pra) / raw_pra > NBA_PRA_TOL:
        return None, "pra_identity"
    return sig, "ok"


def nba_rho(sig: np.ndarray, ma: str, mb: str) -> float | None:
    wa, wb = np.array(NBA_VEC[ma], float), np.array(NBA_VEC[mb], float)
    va, vb = float(wa @ sig @ wa), float(wb @ sig @ wb)
    if va <= 0 or vb <= 0:
        return None
    return float(np.clip((wa @ sig @ wb) / math.sqrt(va * vb), -RHO_CLIP, RHO_CLIP))


def nba_kind(ma: str, mb: str) -> str:
    return "SP-disjoint" if float(np.dot(NBA_VEC[ma], NBA_VEC[mb])) == 0.0 else "SP-nested"


def soccer_events(scorelines: Mapping[str, float], total_line: float | None) -> dict[str, np.ndarray] | None:
    """Per-scoreline indicators and weights for the five soccer events (§3)."""
    hs, as_, ws = [], [], []
    for k, p in scorelines.items():
        try:
            h, a = (int(x) for x in str(k).split("-"))
            ws.append(float(p))
        except (TypeError, ValueError):
            continue
        hs.append(h)
        as_.append(a)
    if not ws:
        return None
    h, a, w = np.array(hs), np.array(as_), np.array(ws, float)
    w = w / w.sum()
    ev = {"h2h_home": h > a, "h2h_draw": h == a, "h2h_away": h < a, "btts": (h > 0) & (a > 0)}
    if total_line is not None:
        ev["totals"] = (h + a) > total_line
    return {"w": w, **{k: v.astype(float) for k, v in ev.items()}}


def tetrachoric(p1: float, p2: float, p11: float) -> float | None:
    """The Gaussian-copula rho reproducing p11 at marginals (p1, p2), by bisection on [-0.999, 0.999]."""
    if not (1e-4 < p1 < 1 - 1e-4 and 1e-4 < p2 < 1 - 1e-4):
        return None
    lo, hi = -0.999, 0.999
    f_lo = float(joint_over(p1, p2, lo)) - p11
    f_hi = float(joint_over(p1, p2, hi)) - p11
    if f_lo >= 0:
        return lo
    if f_hi <= 0:
        return hi
    for _ in range(60):
        mid = (lo + hi) / 2
        if float(joint_over(p1, p2, mid)) - p11 > 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def plackett_p11(pa: float, pb: float, theta: float) -> float:
    """p11 of the 2x2 with marginals (pa, pb) and odds ratio theta (the odds-ratio-preserving re-anchor)."""
    if abs(theta - 1.0) < 1e-12:
        return pa * pb
    s = 1.0 + (theta - 1.0) * (pa + pb)
    return (s - math.sqrt(s * s - 4.0 * theta * (theta - 1.0) * pa * pb)) / (2.0 * (theta - 1.0))


# ----------------------------------------------------------------------------- scoring
def four_cell(pa: np.ndarray, pb: np.ndarray, rho: np.ndarray | float) -> np.ndarray:
    """Columns: A&B, A&notB, notA&B, notA&notB, under the Gaussian copula with each leg's own marginal."""
    pa, pb = np.asarray(pa, float), np.asarray(pb, float)
    rho = np.broadcast_to(np.asarray(rho, float), pa.shape)
    p11 = np.where(np.abs(rho) < 1e-12, pa * pb, joint_over(pa, pb, rho))
    p11 = np.clip(p11, np.maximum(0.0, pa + pb - 1.0), np.minimum(pa, pb))
    probs = np.stack([p11, pa - p11, pb - p11, 1.0 - pa - pb + p11], axis=1)
    return np.clip(probs, CELL_CLIP, 1.0)


def four_cell_from_p11(pa: np.ndarray, pb: np.ndarray, p11: np.ndarray) -> np.ndarray:
    p11 = np.clip(p11, np.maximum(0.0, pa + pb - 1.0), np.minimum(pa, pb))
    return np.clip(np.stack([p11, pa - p11, pb - p11, 1.0 - pa - pb + p11], axis=1), CELL_CLIP, 1.0)


def cell_index(ya: np.ndarray, yb: np.ndarray) -> np.ndarray:
    return ((1 - np.asarray(ya, int)) * 2 + (1 - np.asarray(yb, int))).astype(int)


def logloss(probs: np.ndarray, obs: np.ndarray) -> np.ndarray:
    return -np.log(probs[np.arange(len(obs)), obs])


def brier4(probs: np.ndarray, obs: np.ndarray) -> np.ndarray:
    onehot = np.zeros_like(probs)
    onehot[np.arange(len(obs)), obs] = 1.0
    return ((probs - onehot) ** 2).sum(axis=1)


def clustered_se(values: np.ndarray, groups: Iterable[Any]) -> float:
    """CR1 SE of the mean, clustered by game -- the SGP studies' formula (`build_nfl_sgp_correlations.clustered_se`)."""
    values = np.asarray(values, float)
    n = len(values)
    if n == 0:
        return float("nan")
    sums: dict[Any, float] = defaultdict(float)
    for g, v in zip(groups, values - values.mean()):
        sums[g] += float(v)
    per = np.array(list(sums.values()))
    g = len(per)
    return float(math.sqrt((per ** 2).sum() * g / max(g - 1, 1)) / n)


def summarize_diff(d: np.ndarray, games: np.ndarray) -> dict[str, Any]:
    if len(d) == 0:
        return {"n": 0}
    m = float(d.mean())
    se = clustered_se(d, games)
    z = m / se if se and se > 0 else float("nan")
    p = math.erfc(abs(z) / math.sqrt(2.0)) if math.isfinite(z) else float("nan")
    return {"n": int(len(d)), "games": int(len(set(games.tolist()))), "mean": m, "se": se,
            "ci": [m - 1.96 * se, m + 1.96 * se], "z": z, "p_two_sided": p}


def game_weighted(d: np.ndarray, games: np.ndarray) -> float | None:
    if len(d) == 0:
        return None
    per: dict[Any, list[float]] = defaultdict(list)
    for g, v in zip(games, d):
        per[g].append(float(v))
    return float(np.mean([np.mean(v) for v in per.values()]))


def holm(pvals: Mapping[Any, float], alpha: float = ALPHA) -> dict[Any, bool]:
    items = sorted(((p, k) for k, p in pvals.items() if p is not None and math.isfinite(p)), key=lambda x: x[0])
    m = len(items)
    out = {k: False for k in pvals}
    for i, (p, k) in enumerate(items):
        if p <= alpha / (m - i):
            out[k] = True
        else:
            break
    return out


def mle_rho(pa: np.ndarray, pb: np.ndarray, obs: np.ndarray, games: np.ndarray, boot: int = BOOT,
            seed: int = SEED) -> dict[str, Any]:
    """Realised rho: one rho per cell maximising the 4-cell likelihood at the market marginals; game-bootstrap CI."""
    grid = np.round(np.arange(-0.95, 0.9501, 0.01), 4)
    gid = {g: i for i, g in enumerate(dict.fromkeys(games.tolist()))}
    gi = np.array([gid[g] for g in games.tolist()])
    per = np.zeros((len(gid), len(grid)))
    for j, r in enumerate(grid):
        ll = np.log(four_cell(pa, pb, float(r))[np.arange(len(obs)), obs])
        per[:, j] = np.bincount(gi, weights=ll, minlength=len(gid))
    best = float(grid[int(np.argmax(per.sum(axis=0)))])
    rng = np.random.default_rng(seed)
    bs = [float(grid[int(np.argmax(per[rng.integers(0, len(gid), len(gid))].sum(axis=0)))]) for _ in range(boot)]
    return {"rho": best, "ci": [float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))], "games": len(gid)}


# ----------------------------------------------------------------------------- I/O: market legs (A1)
def daterange(a: date, b: date) -> list[date]:
    return [a + timedelta(days=i) for i in range((b - a).days + 1)]


def bq_files(root: Path, sport: str) -> list[Path]:
    base = root / f"{sport}_source" / "tracking" / "book_quotes"
    out = []
    for d in daterange(WINDOW_START - timedelta(days=1), WINDOW_END + timedelta(days=1)):
        for name in (f"{d.isoformat()}.jsonl.gz", f"{d.isoformat()}.jsonl"):
            if (base / name).exists():
                out.append(base / name)
    return out


def _open(p: Path):
    return gzip.open(p, "rt", encoding="utf-8") if p.suffix == ".gz" else open(p, encoding="utf-8")


def load_quotes(root: Path, sport: str, markets: set[str]) -> tuple[dict, dict, Counter]:
    """A1: per (event, book, market, player, line, selection) the LAST record captured before commence_time."""
    latest: dict[tuple, tuple[datetime, Any]] = {}
    events: dict[str, dict[str, Any]] = {}
    cnt: Counter = Counter()
    for f in bq_files(root, sport):
        with _open(f) as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except ValueError:
                    cnt["bad_json"] += 1
                    continue
                if r.get("market") not in markets or str(r.get("segment") or "full") != "full":
                    continue
                if is_venue(r.get("bookmaker")):
                    cnt["venue_excluded"] += 1
                    continue
                cap, com = parse_ts(r.get("captured_at")), parse_ts(r.get("commence_time"))
                if cap is None or com is None:
                    cnt["no_ts"] += 1
                    continue
                if cap >= com:
                    cnt["inplay_excluded"] += 1
                    continue
                ev = str(r.get("event_id"))
                events.setdefault(ev, {"commence": com, "home": r.get("home_team"), "away": r.get("away_team"),
                                       "league": r.get("league")})
                key = (ev, r.get("bookmaker"), r.get("market"), norm_name(r.get("player_name")),
                       norm_line(r.get("line")), str(r.get("selection") or "").lower())
                old = latest.get(key)
                if old is None or cap >= old[0]:
                    latest[key] = (cap, r.get("price"))
                cnt["kept"] += 1
    return latest, events, cnt


def market_legs(latest: Mapping[tuple, tuple], events: Mapping[str, Mapping[str, Any]], sport: str) -> dict:
    """event -> list of legs {market, player, line, p (P(event side)), n_books, age_min}."""
    grouped: dict[tuple, dict] = defaultdict(lambda: defaultdict(lambda: defaultdict(dict)))
    ages: dict[tuple, list[float]] = defaultdict(list)
    for (ev, book, mkt, player, line, sel), (cap, price) in latest.items():
        grouped[(ev, mkt, player)][line][book][sel] = price
        ages[(ev, mkt, player)].append((events[ev]["commence"] - cap).total_seconds() / 60.0)
    out: dict[str, list[dict]] = defaultdict(list)
    for (ev, mkt, player), by_line in grouped.items():
        legs: list[tuple[str, dict]] = []
        if mkt == "h2h" and sport == "soccer":
            sides = ("home", "draw", "away")
            for side in sides:
                leg = main_line_leg(by_line, sides, side)
                if leg:
                    legs.append((f"h2h_{side}", leg))
        elif mkt == "h2h":
            leg = main_line_leg(by_line, ("home", "away"), "home")
            if leg:
                legs.append(("h2h_home", leg))
        elif mkt == "btts":
            leg = main_line_leg(by_line, ("yes", "no"), "yes")
            if leg:
                legs.append(("btts", leg))
        else:
            lines = {ln: b for ln, b in by_line.items() if ln is not None}
            if sport == "soccer":
                lines = {ln: b for ln, b in lines.items() if abs((ln % 1) - 0.5) < 1e-9}
            leg = main_line_leg(lines, ("over", "under"), "over")
            if leg:
                legs.append((mkt, leg))
        for name, leg in legs:
            if P_MIN < leg["p"] < P_MAX:
                out[ev].append({"market": name, "player": player, "line": leg["line"], "p": leg["p"],
                                "n_books": leg["n_books"], "age_min": statistics.median(ages[(ev, mkt, player)])})
    return out


# ----------------------------------------------------------------------------- I/O: public outcome GETs (cached)
class Fetcher:
    def __init__(self, cache: Path):
        self.cache = cache
        self.cache.mkdir(parents=True, exist_ok=True)
        self.gets = 0
        self.fail = 0

    def get(self, url: str, name: str) -> Any:
        p = self.cache / name
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except ValueError:
                pass
        req = urllib.request.Request(url, headers={"User-Agent": "syndicate-e4-research/1.0"})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    data = json.loads(r.read().decode("utf-8"))
                self.gets += 1
                p.write_text(json.dumps(data), encoding="utf-8")
                time.sleep(0.2)
                return data
            except (urllib.error.URLError, TimeoutError, ValueError):
                time.sleep(1.5 * (attempt + 1))
        self.fail += 1
        return None


# ----------------------------------------------------------------------------- MLB
def match_event(events: Mapping[str, Mapping[str, Any]], t: datetime | None, home: Any, away: Any,
                key=norm_name) -> tuple[str | None, str]:
    cands = []
    for ev, meta in events.items():
        if t is not None and abs((meta["commence"] - t).total_seconds()) > GAME_MATCH_HOURS * 3600:
            continue
        if key(meta["home"]) == key(home) and key(meta["away"]) == key(away):
            cands.append(ev)
    if len(cands) == 1:
        return cands[0], "ok"
    return None, "ambiguous" if cands else "unmatched"


def mlb_box(root: Path, fetch: Fetcher, day: str, pk: int) -> dict | None:
    """{'batters': {pid: {stat: value, 'pa': n}}, 'runs': {'home': r, 'away': r}} for a FINAL game."""
    f = root / "mlb_source" / "source_artifacts" / "data" / "raw" / "statsapi" / "feed_live" / "2026" / day / f"{pk}.json.gz"
    box = None
    if f.exists():
        try:
            g = json.load(gzip.open(f, "rt", encoding="utf-8"))
            if ((g.get("gameData") or {}).get("status") or {}).get("abstractGameState") == "Final":
                box = (g.get("liveData") or {}).get("boxscore")
        except (OSError, ValueError):
            box = None
    if box is None:
        box = fetch.get(f"https://statsapi.mlb.com/api/v1/game/{pk}/boxscore", f"mlb_box_{pk}.json")
        if box is None:
            return None
    out: dict[str, Any] = {"batters": {}, "runs": {}}
    for side in ("home", "away"):
        t = (box.get("teams") or {}).get(side) or {}
        runs = ((t.get("teamStats") or {}).get("batting") or {}).get("runs")
        if runs is None:
            return None
        out["runs"][side] = int(runs)
        for pkey, pl in (t.get("players") or {}).items():
            bat = (pl.get("stats") or {}).get("batting") or {}
            if not bat:
                continue
            pid = str((pl.get("person") or {}).get("id") or pkey.replace("ID", ""))
            out["batters"][pid] = {"pa": int(bat.get("plateAppearances") or 0), "side": side,
                                   **{s: float(bat.get(k) or 0) for s, k in MLB_BOX.items()}}
    return out


def mlb_games(root: Path, fetch: Fetcher, legs_by_ev: Mapping, events: Mapping, funnel: Counter) -> list[dict]:
    base = root / "mlb_source" / "source_artifacts" / "data" / "daily" / "sims_pregame"
    games = []
    for d in daterange(WINDOW_START, WINDOW_END):
        dd = base / d.isoformat()
        if not dd.is_dir():
            continue
        for f in sorted(dd.glob("sim_pk*.json")):
            funnel["sim_files"] += 1
            try:
                s = json.loads(f.read_text(encoding="utf-8"))
            except ValueError:
                funnel["sim_bad"] += 1
                continue
            start = parse_ts((s.get("schedule") or {}).get("game_date"))
            frz = parse_ts((s.get("_freeze") or {}).get("frozen_at"))
            if frz is None or start is None or frz >= start:
                funnel["not_pregame"] += 1
                continue
            joint = (s.get("sim") or {}).get("joint") or {}
            if not joint.get("labels"):
                funnel["no_joint"] += 1
                continue
            ev, why = match_event(events, start, (s.get("home") or {}).get("name"), (s.get("away") or {}).get("name"))
            if ev is None:
                funnel[f"event_{why}"] += 1
                continue
            box = mlb_box(root, fetch, d.isoformat(), int(s["game_pk"]))
            if box is None:
                funnel["no_outcome"] += 1
                continue
            funnel["games"] += 1
            games.append({"sport": "mlb", "game": f"mlb:{s['game_pk']}", "date": d.isoformat(), "event": ev,
                          "sim": s, "box": box, "legs": legs_by_ev.get(ev, [])})
    return games


def mlb_pairs(games: list[dict], cells_c: Mapping[str, Any], funnel: Counter) -> list[dict]:
    pairs = []
    for g in games:
        joint = g["sim"]["sim"]["joint"]
        index = {lab: i for i, lab in enumerate(joint["labels"])}
        players = joint.get("players") or {}
        by_name: dict[str, list[str]] = defaultdict(list)
        by_il: dict[str, list[str]] = defaultdict(list)
        for pid, meta in players.items():
            by_name[norm_name(meta.get("name"))].append(pid)
            by_il[initial_last(meta.get("name"))].append(pid)
        box, legs = g["box"], []
        r_ha_s = joint_rho_s(joint, index, "team|full|home", "team|full|away")
        for leg in g["legs"]:
            if leg["market"] in MLB_STAT:
                cand = by_name.get(leg["player"]) or by_il.get(initial_last(leg["player"])) or []
                if len(cand) != 1:
                    funnel["leg_player_unmatched"] += 1
                    continue
                pid = cand[0]
                b = box["batters"].get(pid)
                if not b or b["pa"] <= 0:
                    funnel["leg_void_no_pa"] += 1
                    continue
                stat = MLB_STAT[leg["market"]]
                v = b[stat]
                if v == leg["line"]:
                    funnel["leg_push"] += 1
                    continue
                legs.append({**leg, "kind": "bat", "pid": pid, "side": players[pid].get("side"), "stat": stat,
                             "label": f"batter|{pid}|{stat}", "y": int(v > leg["line"])})
            elif leg["market"] in ("totals", "h2h_home"):
                tot = box["runs"]["home"] + box["runs"]["away"]
                if leg["market"] == "totals":
                    if tot == leg["line"]:
                        funnel["leg_push"] += 1
                        continue
                    legs.append({**leg, "kind": "total", "y": int(tot > leg["line"])})
                else:
                    legs.append({**leg, "kind": "home_win", "y": int(box["runs"]["home"] > box["runs"]["away"])})
        funnel["legs"] += len(legs)
        for i in range(len(legs)):
            for j in range(i + 1, len(legs)):
                a, b = legs[i], legs[j]
                if a["kind"] == "bat" and b["kind"] == "bat":
                    if a["pid"] == b["pid"] and a["stat"] == b["stat"]:
                        continue
                    if a["pid"] == b["pid"]:
                        cell = "SP-nested" if frozenset((a["stat"], b["stat"])) in MLB_NESTED else "SP-other"
                        rel = "same_player"
                    else:
                        cell, rel = ("TM", "teammate") if a["side"] == b["side"] else ("OP", "opponent")
                    rs = joint_rho_s(joint, index, a["label"], b["label"])
                    if rs is None:
                        funnel["pair_rho_undefined"] += 1
                        continue
                    rb = spearman_to_gauss(rs)
                    rc, lvl = rho_for(cells_c, f"{a['market']}|X", f"{b['market']}|X", rel)
                    stat_pair = "~".join(sorted((a["stat"], b["stat"]))) + f"~{rel}"
                    pairs.append(_pair(g, cell, stat_pair, a, b, rb, rc if lvl != "none" else None))
                elif "bat" in (a["kind"], b["kind"]) and r_ha_s is not None:
                    x, o = (a, b) if a["kind"] == "bat" else (b, a)
                    own, opp = ("home", "away") if x["side"] == "home" else ("away", "home")
                    r_own = joint_rho_s(joint, index, x["label"], f"team|full|{own}")
                    r_opp = joint_rho_s(joint, index, x["label"], f"team|full|{opp}")
                    if r_own is None or r_opp is None:
                        funnel["pair_rho_undefined"] += 1
                        continue
                    r_own, r_opp, r_ha = spearman_to_gauss(r_own), spearman_to_gauss(r_opp), spearman_to_gauss(r_ha_s)
                    if o["kind"] == "total":
                        rb = composed_rho(r_own, r_opp, r_ha, "total")
                        pairs.append(_pair(g, "PG-composed", f"{x['stat']}~game_total", x, o, rb, None))
                    elif o["kind"] == "home_win":
                        # the leg is HOME wins; X's own-team-win correlation, signed to the home side
                        rb = composed_rho(r_own, r_opp, r_ha, "own_win")
                        rb = rb if x["side"] == "home" else -rb
                        pairs.append(_pair(g, "PW-composed", f"{x['stat']}~home_win", x, o, rb, None))
    return pairs


def _pair(g: Mapping[str, Any], cell: str, stat_pair: str, a: Mapping, b: Mapping, rb: float | None,
          rc: float | None, **extra: Any) -> dict:
    return {"sport": g["sport"], "cell": cell, "stat_pair": stat_pair, "game": g["game"], "date": g["date"],
            "pa": a["p"], "pb": b["p"], "ya": a["y"], "yb": b["y"],
            "rho_b": None if rb is None else float(np.clip(rb, -RHO_CLIP, RHO_CLIP)),
            "rho_c": None if rc is None else float(rc), **extra}


# ----------------------------------------------------------------------------- NBA
def nickname(v: Any) -> str:
    toks = norm_name(v).split()
    if not toks:
        return ""
    return "blazers" if toks[-1] == "blazers" else toks[-1]


def espn_nba(fetch: Fetcher, gid: Any) -> dict | None:
    s = fetch.get(f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={gid}", f"nba_{gid}.json")
    if not s:
        return None
    comp = ((s.get("header") or {}).get("competitions") or [{}])[0]
    if not (((comp.get("status") or {}).get("type") or {}).get("completed")):
        return None
    teams = {c.get("homeAway"): (c.get("team") or {}).get("displayName") for c in comp.get("competitors") or []}
    box: dict[str, dict] = {}
    for team in (s.get("boxscore") or {}).get("players") or []:
        for st in team.get("statistics") or []:
            keys = [str(k).lower() for k in (st.get("keys") or st.get("labels") or [])]
            for ath in st.get("athletes") or []:
                nm = norm_name((ath.get("athlete") or {}).get("displayName"))
                vals = ath.get("stats") or []
                if ath.get("didNotPlay") or not vals:
                    box[nm] = {"dnp": True}
                    continue
                row = dict(zip(keys, vals))

                def num(*names):
                    for n in names:
                        if n in row:
                            try:
                                return float(str(row[n]).split("-")[0])
                            except ValueError:
                                return None
                    return None

                mins = num("minutes", "min")
                box[nm] = {"dnp": not mins, "pts": num("points", "pts"), "reb": num("rebounds", "reb"),
                           "ast": num("assists", "ast")}
    return {"start": parse_ts(comp.get("date")), "home": teams.get("home"), "away": teams.get("away"), "box": box}


def nba_games(root: Path, fetch: Fetcher, legs_by_ev: Mapping, events: Mapping, funnel: Counter) -> list[dict]:
    base = root / "nba_source" / "data" / "processed"
    games = []
    for f in sorted(base.glob("smart_sim_2026-*.json")):
        m = re.match(r"smart_sim_(\d{4}-\d{2}-\d{2})_", f.name)
        if not m or not (WINDOW_START <= date.fromisoformat(m.group(1)) <= WINDOW_END):
            continue
        funnel["sim_files"] += 1
        try:
            s = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            funnel["sim_bad"] += 1
            continue
        if not s.get("players") or not s.get("game_id"):
            funnel["sim_no_players"] += 1
            continue
        e = espn_nba(fetch, s["game_id"])
        if e is None or e["start"] is None:
            funnel["no_outcome"] += 1
            continue
        ev, why = match_event(events, e["start"], e["home"], e["away"], key=nickname)
        if ev is None:
            funnel[f"event_{why}"] += 1
            continue
        mtime = datetime.fromtimestamp(f.stat().st_mtime, UTC)
        if mtime >= events[ev]["commence"]:
            funnel["not_pregame"] += 1
            continue
        funnel["games"] += 1
        games.append({"sport": "nba", "game": f"nba:{s['game_id']}", "date": m.group(1), "event": ev, "sim": s,
                      "espn": e, "legs": legs_by_ev.get(ev, []), "n_sims": s.get("n_sims")})
    return games


def nba_pairs(games: list[dict], cells_c: Mapping[str, Any], funnel: Counter) -> list[dict]:
    pairs = []
    for g in games:
        s = g["sim"]
        cal = s.get("nba_prop_calibration") if isinstance(s.get("nba_prop_calibration"), Mapping) else {}
        applied, file_k = bool(cal.get("applied")), cal.get("k") if isinstance(cal.get("k"), Mapping) else None
        sigma: dict[str, np.ndarray] = {}
        for side in ("home", "away"):
            for row in (s.get("players") or {}).get(side) or []:
                sig, why = nba_cov(row, file_k, applied)
                funnel[f"player_cov_{why}"] += 1
                if sig is not None:
                    sigma[norm_name(row.get("player_name"))] = sig
        by_player: dict[str, list[dict]] = defaultdict(list)
        for leg in g["legs"]:
            if leg["market"] not in NBA_VEC:
                continue
            b = name_lookup(g["espn"]["box"], leg["player"])
            if b is None:
                funnel["leg_no_box"] += 1
                continue
            if b.get("dnp") or any(b.get(k) is None for k in ("pts", "reb", "ast")):
                funnel["leg_void_dnp"] += 1
                continue
            v = float(np.dot(NBA_VEC[leg["market"]], (b["pts"], b["reb"], b["ast"])))
            if v == leg["line"]:
                funnel["leg_push"] += 1
                continue
            by_player[leg["player"]].append({**leg, "y": int(v > leg["line"])})
            funnel["legs"] += 1
        regular = date.fromisoformat(g["date"]) >= NBA_REGULAR_FROM
        for player, legs in by_player.items():
            sig = name_lookup(sigma, player)
            if sig is None:
                funnel["player_no_sim_cov"] += len(legs)
                continue
            for i in range(len(legs)):
                for j in range(i + 1, len(legs)):
                    a, b = legs[i], legs[j]
                    kind = nba_kind(a["market"], b["market"])
                    cell = kind if regular else f"{kind}-preseason"
                    rb = nba_rho(sig, a["market"], b["market"])
                    if rb is None:
                        funnel["pair_rho_undefined"] += 1
                        continue
                    rc, lvl = rho_for(cells_c, f"{NBA_SGP[a['market']]}|X", f"{NBA_SGP[b['market']]}|X", "same_player")
                    sp = "~".join(sorted((NBA_SGP[a["market"]], NBA_SGP[b["market"]])))
                    pairs.append(_pair(g, cell, sp, a, b, rb, rc if lvl != "none" else None, n_sims=g["n_sims"]))
    return pairs


# ----------------------------------------------------------------------------- soccer
def espn_soccer(fetch: Fetcher, slug: str, eid: Any) -> dict | None:
    s = fetch.get(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/summary?event={eid}",
                  f"soc_{slug}_{eid}.json")
    if not s:
        return None
    comp = ((s.get("header") or {}).get("competitions") or [{}])[0]
    st = (comp.get("status") or {}).get("type") or {}
    if not st.get("completed"):
        return {"void": "not_completed"}
    detail = f"{st.get('name')} {st.get('detail')} {st.get('shortDetail')}".upper()
    if "AET" in detail or "PEN" in detail or "EXTRA" in detail:
        return {"void": "extra_time"}
    sc, names = {}, {}
    for c in comp.get("competitors") or []:
        try:
            sc[c.get("homeAway")] = int(c.get("score"))
        except (TypeError, ValueError):
            return {"void": "no_score"}
        names[c.get("homeAway")] = (c.get("team") or {}).get("displayName")
    if set(sc) != {"home", "away"}:
        return {"void": "no_score"}
    return {"home": sc["home"], "away": sc["away"], "home_name": names.get("home"), "away_name": names.get("away")}


def soccer_games(root: Path, fetch: Fetcher, legs_by_ev: Mapping, events: Mapping, funnel: Counter) -> list[dict]:
    frozen: dict[str, dict] = {}
    for league, slug in SOCCER_LEAGUES.items():
        base = root / "soccer_source" / league / "api" / "recommendations"
        for f in sorted(base.glob("recommendations_prekickoff_*.json")):
            m = re.match(r"recommendations_prekickoff_(\d{4}-\d{2}-\d{2})", f.name)
            if not m or not (WINDOW_START <= date.fromisoformat(m.group(1)) <= WINDOW_END):
                continue
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except ValueError:
                continue
            for mid, rec in (d.get("matches") or {}).items():
                fz, ko = parse_ts(rec.get("frozen_at")), parse_ts(rec.get("kickoff"))
                mt = rec.get("match") or {}
                if fz is None or ko is None or fz >= ko or not mt.get("scoreline_probabilities"):
                    funnel["sim_not_pregame_or_empty"] += 1
                    continue
                old = frozen.get(mid)
                if old is None or fz > old["frozen_at"]:
                    frozen[mid] = {"league": league, "slug": slug, "frozen_at": fz, "kickoff": ko, "match": mt,
                                   "date": m.group(1)}
    games = []
    for mid, rec in sorted(frozen.items()):
        funnel["sim_matches"] += 1
        e = espn_soccer(fetch, rec["slug"], mid)
        if e is None:
            funnel["no_outcome"] += 1
            continue
        if e.get("void"):
            funnel[f"void_{e['void']}"] += 1
            continue
        best, second = None, None
        for ev, meta in events.items():
            if abs((meta["commence"] - rec["kickoff"]).total_seconds()) > 3 * 3600:
                continue
            sc = (jaccard(team_tokens(meta["home"]), team_tokens(e["home_name"]))
                  + jaccard(team_tokens(meta["away"]), team_tokens(e["away_name"])))
            ok = (jaccard(team_tokens(meta["home"]), team_tokens(e["home_name"])) >= 0.34
                  and jaccard(team_tokens(meta["away"]), team_tokens(e["away_name"])) >= 0.34)
            if ok and (best is None or sc > best[0]):
                best, second = (sc, ev), best
            elif ok and (second is None or sc > second[0]):
                second = (sc, ev)
        if best is None:
            funnel["event_unmatched"] += 1
            continue
        if second is not None and abs(second[0] - best[0]) < 1e-9:
            funnel["event_ambiguous"] += 1
            continue
        funnel["games"] += 1
        games.append({"sport": "soccer", "game": f"soc:{mid}", "date": rec["date"], "event": best[1], "league": rec["league"],
                      "sim": rec["match"], "score": e, "legs": legs_by_ev.get(best[1], [])})
    return games


def soccer_pairs(games: list[dict], funnel: Counter) -> list[dict]:
    pairs = []
    for g in games:
        h, a = g["score"]["home"], g["score"]["away"]
        legs = []
        for leg in g["legs"]:
            mk = leg["market"]
            if mk == "h2h_home":
                y = h > a
            elif mk == "h2h_draw":
                y = h == a
            elif mk == "h2h_away":
                y = h < a
            elif mk == "btts":
                y = h > 0 and a > 0
            elif mk == "totals":
                y = (h + a) > leg["line"]
            else:
                continue
            legs.append({**leg, "y": int(y)})
        funnel["legs"] += len(legs)
        tline = next((x["line"] for x in legs if x["market"] == "totals"), None)
        ev = soccer_events(g["sim"].get("scoreline_probabilities") or {}, tline)
        if ev is None:
            funnel["sim_no_scorelines"] += 1
            continue
        for i in range(len(legs)):
            for j in range(i + 1, len(legs)):
                x, z = legs[i], legs[j]
                kinds = {x["market"].split("_")[0], z["market"].split("_")[0]}
                if kinds == {"h2h"}:
                    continue
                kind = "~".join(sorted(k if k != "h2h" else "result" for k in kinds))
                w = ev["w"]
                s1, s2 = float((w * ev[x["market"]]).sum()), float((w * ev[z["market"]]).sum())
                s11 = float((w * ev[x["market"]] * ev[z["market"]]).sum())
                rb = tetrachoric(s1, s2, s11)
                if rb is None:
                    funnel["pair_rho_undefined"] += 1
                    continue
                s10, s01 = s1 - s11, s2 - s11
                s00 = 1.0 - s1 - s2 + s11
                theta = ((s11 + 1e-6) * (s00 + 1e-6)) / ((s10 + 1e-6) * (s01 + 1e-6))
                stat_pair = f"{kind}:{'~'.join(sorted((x['market'], z['market'])))}"
                pairs.append(_pair(g, "GL", stat_pair, x, z, rb, None, theta=theta, kind=kind))
    return pairs


# ----------------------------------------------------------------------------- scoring a cell
def score_cell(rows: list[dict], with_b_pooled: bool = True) -> dict[str, Any]:
    rows = [r for r in rows if r["rho_b"] is not None]
    if not rows:
        return {"pairs": 0, "games": 0}
    pa = np.array([r["pa"] for r in rows])
    pb = np.array([r["pb"] for r in rows])
    obs = cell_index([r["ya"] for r in rows], [r["yb"] for r in rows])
    games = np.array([r["game"] for r in rows])
    rb = np.array([r["rho_b"] for r in rows])
    P_a, P_b = four_cell(pa, pb, 0.0), four_cell(pa, pb, rb)
    ll_a, ll_b = logloss(P_a, obs), logloss(P_b, obs)
    br_a, br_b = brier4(P_a, obs), brier4(P_b, obs)
    out: dict[str, Any] = {
        "pairs": len(rows), "games": len(set(games.tolist())), "dates": len({r["date"] for r in rows}),
        "ll_a": float(ll_a.mean()), "ll_b": float(ll_b.mean()),
        "D_ba": summarize_diff(ll_b - ll_a, games), "B_ba": summarize_diff(br_b - br_a, games),
        "D_ba_game_weighted": game_weighted(ll_b - ll_a, games),
        "mean_rho_b": float(rb.mean()), "mean_abs_rho_b": float(np.abs(rb).mean()),
        "realised_both": float((obs == 0).mean()), "pred_both_a": float(P_a[:, 0].mean()),
        "pred_both_b": float(P_b[:, 0].mean()),
    }
    has_c = np.array([r["rho_c"] is not None for r in rows])
    if has_c.any():
        rc = np.array([r["rho_c"] if r["rho_c"] is not None else 0.0 for r in rows])
        P_c = four_cell(pa, pb, rc)
        ll_c, br_c = logloss(P_c, obs), brier4(P_c, obs)
        m = has_c
        out.update({"pairs_c": int(m.sum()), "games_c": int(len(set(games[m].tolist()))),
                    "ll_c": float(ll_c[m].mean()), "mean_rho_c": float(rc[m].mean()),
                    "D_ca": summarize_diff(ll_c[m] - ll_a[m], games[m]),
                    "D_bc": summarize_diff(ll_b[m] - ll_c[m], games[m]),
                    "B_bc": summarize_diff(br_b[m] - br_c[m], games[m]),
                    "D_ba_on_c_subset": summarize_diff(ll_b[m] - ll_a[m], games[m])})
    if with_b_pooled:
        # A2: (b-pooled) per (cell, stat pair), the leave-one-DATE-out mean sim rho
        by_sp: dict[str, list[int]] = defaultdict(list)
        for i, r in enumerate(rows):
            by_sp[r["stat_pair"]].append(i)
        rp = np.full(len(rows), np.nan)
        for idx in by_sp.values():
            for i in idx:
                others = [rows[k]["rho_b"] for k in idx if rows[k]["date"] != rows[i]["date"]]
                if others:
                    rp[i] = float(np.mean(others))
        m = ~np.isnan(rp)
        if m.any():
            ll_p = logloss(four_cell(pa[m], pb[m], rp[m]), obs[m])
            out["D_bpooled_a"] = summarize_diff(ll_p - ll_a[m], games[m])
            out["D_b_bpooled"] = summarize_diff(ll_b[m] - ll_p, games[m])
    if rows[0].get("theta") is not None:
        th = np.array([r["theta"] for r in rows])
        p11 = np.array([plackett_p11(x, y, t) for x, y, t in zip(pa, pb, th)])
        ll_or = logloss(four_cell_from_p11(pa, pb, p11), obs)
        out["D_or_a"] = summarize_diff(ll_or - ll_a, games)
    out["realised_rho"] = mle_rho(pa, pb, obs, games)
    return out


def verdict_cell(res: Mapping[str, Any]) -> str:
    if res.get("pairs", 0) < MIN_PAIRS or res.get("games", 0) < MIN_GAMES:
        return "INSUFFICIENT"
    return "CANDIDATE" if res["D_ba"]["ci"][1] < 0 else "KILLED"


# ----------------------------------------------------------------------------- c-ledger (descriptive)
def c_ledger(root: Path) -> dict[str, Any]:
    out = {}
    for sport in ("nhl", "nba", "nfl", "wnba", "mlb"):
        base = root / "cheatsheets" / sport
        led = {}
        try:
            for line in (base / "sgp_ledger.jsonl").read_text(encoding="utf-8").splitlines():
                try:
                    r = json.loads(line)
                    led[r.get("sgp_id")] = r
                except ValueError:
                    continue
            graded = [json.loads(x) for x in (base / "sgp_graded.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
        except OSError:
            continue
        rows = []
        for g in graded:
            if g.get("status") not in ("won", "lost") or g.get("p_joint") is None:
                continue
            L = led.get(g.get("sgp_id")) or {}
            pm = []
            for leg in L.get("legs") or []:
                p = leg.get("p_market")
                if p is None or str(leg.get("side") or "over").lower() != "over":
                    pm = None
                    break
                pm.append(float(p))
            rows.append({"y": 1.0 if g["status"] == "won" else 0.0, "pj": float(g["p_joint"]),
                         "pi": L.get("p_independent"), "pm": float(np.prod(pm)) if pm else None,
                         "game": g.get("event_id")})

        def ll(p, y):
            p = min(max(p, 1e-6), 1 - 1e-6)
            return -(y * math.log(p) + (1 - y) * math.log(1 - p))

        res: dict[str, Any] = {"settled": len(rows), "games": len({r["game"] for r in rows}),
                               "hit_rate": float(np.mean([r["y"] for r in rows])) if rows else None,
                               "pred_joint": float(np.mean([r["pj"] for r in rows])) if rows else None}
        sub = [r for r in rows if r["pi"] is not None]
        if sub:
            d = np.array([ll(r["pj"], r["y"]) - ll(float(r["pi"]), r["y"]) for r in sub])
            res["D_joint_vs_ledger_indep"] = summarize_diff(d, np.array([r["game"] for r in sub]))
        sub = [r for r in rows if r["pm"] is not None]
        if sub:
            d = np.array([ll(r["pj"], r["y"]) - ll(r["pm"], r["y"]) for r in sub])
            res["D_joint_vs_market_product"] = summarize_diff(d, np.array([r["game"] for r in sub]))
            res["n_market_product"] = len(sub)
            res["pred_market_product"] = float(np.mean([r["pm"] for r in sub]))
            res["hit_rate_market_subset"] = float(np.mean([r["y"] for r in sub]))
        out[sport] = res
    return out


# ----------------------------------------------------------------------------- main
def coverage(root: Path) -> dict[str, Any]:
    def dates_of(paths: Iterable[str], rx: str) -> list[str]:
        ds = sorted({m.group(1) for p in paths for m in [re.search(rx, p)] if m})
        return [x for x in ds if WINDOW_START.isoformat() <= x <= WINDOW_END.isoformat()]

    cov: dict[str, Any] = {}
    mlb = root / "mlb_source" / "source_artifacts" / "data" / "daily" / "sims_pregame"
    cov["mlb_sims_pregame"] = dates_of([p.name for p in mlb.iterdir()] if mlb.is_dir() else [], r"(\d{4}-\d{2}-\d{2})")
    nba = root / "nba_source" / "data" / "processed"
    cov["nba_smart_sim"] = dates_of([p.name for p in nba.glob("smart_sim_2026-*.json")], r"smart_sim_(\d{4}-\d{2}-\d{2})")
    soc = []
    for lg in SOCCER_LEAGUES:
        b = root / "soccer_source" / lg / "api" / "recommendations"
        soc += [p.name for p in b.glob("recommendations_prekickoff_*.json")] if b.is_dir() else []
    cov["soccer_prekickoff"] = dates_of(soc, r"prekickoff_(\d{4}-\d{2}-\d{2})")
    for s in ("mlb", "nba", "soccer"):
        cov[f"{s}_book_quotes"] = dates_of([p.name for p in bq_files(root, s)], r"(\d{4}-\d{2}-\d{2})")
    for s, simk in (("mlb", "mlb_sims_pregame"), ("nba", "nba_smart_sim"), ("soccer", "soccer_prekickoff")):
        cov[f"{s}_intersection_dates"] = sorted(set(cov[simk]) & set(cov[f"{s}_book_quotes"]))
    return {k: (v if not isinstance(v, list) else {"first": v[0] if v else None, "last": v[-1] if v else None,
                                                     "n": len(v)}) for k, v in cov.items()}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-root", default=os.environ.get("SYNDICATE_DATA_ROOT") or "")
    ap.add_argument("--out", required=True)
    ap.add_argument("--cache", required=True)
    ap.add_argument("--sports", default="mlb,nba,soccer")
    ap.add_argument("--coverage-only", action="store_true")
    args = ap.parse_args(argv)
    if not args.data_root:
        print("REFUSING: no --data-root", flush=True)
        return 2
    root = Path(os.path.expanduser(args.data_root))
    fetch = Fetcher(Path(args.cache))
    report: dict[str, Any] = {"prereg": "9f8d759e", "amendments": ["A1 83f2e460", "A2"],
                              "run_at": datetime.now(UTC).isoformat(), "coverage": coverage(root)}
    print("E4_COVERAGE " + json.dumps(report["coverage"]), flush=True)
    if args.coverage_only:
        Path(args.out).write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
        return 0
    all_pairs: list[dict] = []
    report["funnel"], report["market"] = {}, {}
    for sport in [s.strip() for s in args.sports.split(",") if s.strip()]:
        funnel: Counter = Counter()
        if sport == "mlb":
            mk = set(MLB_STAT) | {"h2h", "totals"}
        elif sport == "nba":
            mk = set(NBA_VEC)
        else:
            mk = {"h2h", "totals", "btts"}
        latest, events, qcnt = load_quotes(root, sport, mk)
        legs = market_legs(latest, events, sport)
        report["market"][sport] = {"events": len(events), "events_with_legs": len(legs),
                                   "legs": sum(len(v) for v in legs.values()), "quote_rows": dict(qcnt),
                                   "median_age_min": statistics.median([x["age_min"] for v in legs.values() for x in v])
                                   if legs else None}
        print(f"E4_MARKET {sport} " + json.dumps(report["market"][sport]), flush=True)
        cells_c = {}
        p = root / f"{sport}_source" / "sgp" / f"{sport}_sgp_correlations.json"
        if p.exists():
            cells_c = json.loads(p.read_text(encoding="utf-8"))
        if sport == "mlb":
            pairs = mlb_pairs(mlb_games(root, fetch, legs, events, funnel), cells_c, funnel)
        elif sport == "nba":
            pairs = nba_pairs(nba_games(root, fetch, legs, events, funnel), cells_c, funnel)
        else:
            pairs = soccer_pairs(soccer_games(root, fetch, legs, events, funnel), funnel)
        funnel["pairs"] = len(pairs)
        report["funnel"][sport] = dict(funnel)
        print(f"E4_FUNNEL {sport} " + json.dumps(dict(funnel)), flush=True)
        all_pairs += pairs
    by_cell: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in all_pairs:
        by_cell[(r["sport"], r["cell"])].append(r)
        if r["sport"] == "soccer":
            by_cell[("soccer", f"GL:{r['kind']}")].append(r)
        if r["sport"] == "nba":
            by_cell[(f"nba-n{r.get('n_sims')}", r["cell"])].append(r)
    cells = {}
    for key, rows in sorted(by_cell.items()):
        res = score_cell(rows)
        res["verdict"] = verdict_cell(res) if res.get("pairs") else "INSUFFICIENT"
        sp: dict[str, Any] = {}
        groups: dict[str, list[dict]] = defaultdict(list)
        for r in rows:
            groups[r["stat_pair"]].append(r)
        for k, rr in sorted(groups.items()):
            if len(rr) >= 30:
                sp[k] = score_cell(rr, with_b_pooled=False)
        res["by_stat_pair"] = sp
        cells[f"{key[0]}|{key[1]}"] = res
        print(f"E4_CELL {key[0]}|{key[1]} pairs={res.get('pairs')} games={res.get('games')} "
              f"D_ba={res.get('D_ba', {}).get('mean')} ci={res.get('D_ba', {}).get('ci')} verdict={res['verdict']}",
              flush=True)
    pvals = {}
    for sport, cell in PRIMARY:
        res = cells.get(f"{sport}|{cell}") or {}
        # Holm runs over all 7 registered cells: an INSUFFICIENT or wrong-signed cell enters as p = 1 (A2)
        ok = res.get("verdict") in ("CANDIDATE", "KILLED") and res["D_ba"]["mean"] < 0
        pvals[f"{sport}|{cell}"] = res["D_ba"]["p_two_sided"] if ok else 1.0
    passed = holm(pvals)
    for k in pvals:
        res = cells.get(k) or {}
        if res.get("verdict") == "CANDIDATE":
            res["verdict"] = "PASS" if passed.get(k) else "LEAD"
    report["cells"] = cells
    report["holm"] = {"pvals": pvals, "pass": passed}
    report["e4_overall"] = "PASS_TO_STAGE_2" if any(passed.values()) else "KILLED"
    report["c_ledger"] = c_ledger(root)
    report["fetch"] = {"gets": fetch.gets, "fail": fetch.fail}
    Path(args.out).write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    with open(Path(args.out).with_suffix(".pairs.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["sport", "cell", "stat_pair", "game", "date", "pa", "pb", "ya", "yb",
                                           "rho_b", "rho_c"], extrasaction="ignore")
        w.writeheader()
        w.writerows(all_pairs)
    print(f"E4_OVERALL {report['e4_overall']} holm={json.dumps(passed)} gets={fetch.gets} fail={fetch.fail}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
