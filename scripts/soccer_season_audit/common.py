# -*- coding: utf-8 -*-
"""Shared loaders, joins and scoring helpers for the soccer season audit.

Lane `soccer-season-market-audit`, 2026-09-15. Evidence:
`.syndicate/findings_2026-09-15_soccer_season_market_audit.md`.

RUNNING IT. Every module reads and writes a CACHE directory, never the repo:
`SOCCER_AUDIT_CACHE` (default: this directory) holds `prod/` (pulled by
`pullchain.py`), `fd/` (football-data season CSVs), `outcomes.json`,
`fotmob_season*.json` and `recs_snapshot_0902/`. `SYNDICATE_REPO_ROOT` must be a
checkout WITH `data/` -- `audit_games.py` reads last season's corners history
from `data/soccer_source/*/history/matches_2025.csv`, which a session worktree
omits by default. Order: pullchain -> outcomes -> shape -> audit_games ->
audit_props -> shape_join (namejoin_diag and leak are diagnostics).
"""
import collections
import datetime as dt
import glob
import io
import json
import math
import os
import random
import sys
import unicodedata

S = os.environ.get("SOCCER_AUDIT_CACHE") or os.path.dirname(os.path.abspath(__file__))
PRIMARY = os.environ.get("SYNDICATE_REPO_ROOT") or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PRIMARY)
from syndicate.features.soccer.features.team_names import canonical_team_name, match_team_name  # noqa: E402

VERSION_SPLIT = dt.datetime(2026, 9, 7, 20, 12, tzinfo=dt.timezone.utc)   # ESPN match-stats inputs reached the worker
LEAGUES = ["epl", "championship", "la_liga", "bundesliga", "serie_a", "ligue_1",
           "eredivisie", "primeira_liga", "belgian_pro_league", "mls"]


def ts(value):
    if value is None:
        return None
    try:
        t = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def fold(name):
    return "".join(c for c in unicodedata.normalize("NFKD", str(name or ""))
                   if not unicodedata.combining(c)).lower().replace(".", " ").replace("-", " ").strip()


def load_recs(directory=os.path.join(S, "prod", "recs")):
    matches = {}
    for f in glob.glob(os.path.join(directory, "*.json")):
        if os.path.basename(f).startswith("_"):
            continue
        try:
            j = json.load(io.open(f, encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(j, dict) or not j.get("matches"):
            continue
        gen = ts(j.get("generated_at"))
        props_by_match = collections.defaultdict(list)
        for p in j.get("player_props") or []:
            props_by_match[str(p.get("match_id"))].append(p)
        for m in j["matches"]:
            mid = str(m.get("match_id") or "")
            wp = m.get("win_probability") or {}
            if not mid or wp.get("home") is None:
                continue
            sp = {}
            for k, v in (m.get("scoreline_probabilities") or {}).items():
                try:
                    h, a = k.split("-")
                    sp[(int(h), int(a))] = float(v)
                except ValueError:
                    continue
            td = m.get("total_distribution") or {}
            tp = m.get("team_projection") or {}
            vp = m.get("volume_projection") or {}
            mu = m.get("matchup") or {}
            rec = {
                "league": j.get("league"), "date": str(j.get("date")), "match_id": mid,
                "kickoff": ts(m.get("kickoff")), "home": mu.get("home_team"), "away": mu.get("away_team"),
                "generated_at": gen, "version": "post0907" if gen and gen >= VERSION_SPLIT else "pre0907",
                "sims": m.get("simulations") or j.get("simulations"),
                "p_home": float(wp["home"]), "p_draw": float(wp.get("draw") or 0.0), "p_away": float(wp.get("away") or 0.0),
                "scores": sp, "total_mean": td.get("mean"), "p_over25": td.get("over_2_5_probability"),
                "p_btts": td.get("both_teams_scored_probability"),
                "home_mean": tp.get("home_mean"), "away_mean": tp.get("away_mean"),
                "corners_h": vp.get("home_corners"), "corners_a": vp.get("away_corners"),
                "shots_h": vp.get("home_shots"), "shots_a": vp.get("away_shots"),
                "sot_h": vp.get("home_shots_on_target"), "sot_a": vp.get("away_shots_on_target"),
                "players": props_by_match.get(mid, []),
            }
            key = (rec["league"], mid)
            if key not in matches or (gen and matches[key]["generated_at"] and gen > matches[key]["generated_at"]):
                matches[key] = rec
    return matches


def load_outcomes(path=os.path.join(S, "outcomes.json")):
    raw = json.load(io.open(path, encoding="utf-8"))
    return {tuple(k.split("|", 1)): v for k, v in raw.items()}


def same_fixture(home, away, cand_home, cand_away):
    if canonical_team_name(home) == canonical_team_name(cand_home) and canonical_team_name(away) == canonical_team_name(cand_away):
        return True
    return (match_team_name(home, [cand_home]) is not None) and (match_team_name(away, [cand_away]) is not None)


def find_fixture(home, away, candidates):
    """candidates: list of (cand_home, cand_away, payload). Exact canonical first, then a fuzzy
    match that must bind BOTH sides to the SAME candidate and be unique."""
    exact = [c for c in candidates if canonical_team_name(home) == canonical_team_name(c[0])
             and canonical_team_name(away) == canonical_team_name(c[1])]
    if len(exact) == 1:
        return exact[0][2]
    homes = [c[0] for c in candidates]
    aways = [c[1] for c in candidates]
    mh = match_team_name(home, homes)
    ma = match_team_name(away, aways)
    if mh is None or ma is None:
        return None
    hits = [c for c in candidates if c[0] == mh and c[1] == ma]
    return hits[0][2] if len(hits) == 1 else None


# ---------- pricing helpers ----------

def dec_from_american(price):
    price = float(price)
    return 1.0 + (price / 100.0 if price > 0 else 100.0 / abs(price))


def devig(decimals):
    inv = [1.0 / d for d in decimals]
    s = sum(inv)
    return [x / s for x in inv]


def norm_scores(scores):
    tot = sum(scores.values())
    return {k: v / tot for k, v in scores.items()} if tot > 0 else {}


def p_total_over(scores, line):
    """Settlement-weighted P(over) for a half or whole line: returns (p_win, p_push)."""
    win = push = 0.0
    for (h, a), p in scores.items():
        t = h + a
        if t > line:
            win += p
        elif t == line:
            push += p
    return win, push


def ah_home_value(scores, line):
    """Expected settlement of a 1u HOME Asian-handicap bet at `line` (home handicap),
    as (p_full_win, p_half_win, p_push, p_half_loss, p_full_loss). Quarter lines split."""
    parts = [line - 0.25, line + 0.25] if abs((line * 4) % 2 - 1) < 1e-9 else [line]
    out = [0.0] * 5
    for part in parts:
        w = 1.0 / len(parts)
        for (h, a), p in scores.items():
            r = h - a + part
            if r > 0:
                out[0] += w * p
            elif r == 0:
                out[2] += w * p
            else:
                out[4] += w * p
    return out


def settle_ah_home(hg, ag, line, dec):
    """Profit of 1u on HOME at an Asian line with decimal odds `dec`."""
    parts = [line - 0.25, line + 0.25] if abs((line * 4) % 2 - 1) < 1e-9 else [line]
    profit = 0.0
    for part in parts:
        w = 1.0 / len(parts)
        r = hg - ag + part
        profit += w * ((dec - 1.0) if r > 0 else (0.0 if r == 0 else -1.0))
    return profit


def poisson_pmf(k, lam):
    return math.exp(-lam) * lam ** k / math.factorial(k)


def poisson_sf(k, lam):
    """P(X >= k)."""
    return 1.0 - sum(poisson_pmf(i, lam) for i in range(int(k)))


def nb_sf(k, mean, disp):
    """P(X >= k) under a negative binomial with variance = disp * mean (disp > 1); Poisson otherwise."""
    if disp <= 1.0001:
        return poisson_sf(k, mean)
    p = 1.0 / disp
    r = mean * p / (1.0 - p)
    cdf = 0.0
    for i in range(int(k)):
        cdf += math.exp(math.lgamma(i + r) - math.lgamma(r) - math.lgamma(i + 1) + r * math.log(p) + i * math.log(1 - p))
    return 1.0 - cdf


def implied_poisson_goals(p_home, p_away, p_over25):
    """Market-implied (lam_home, lam_away) from de-vigged 1X2 + O/U 2.5 under independent Poisson.
    Grid search; used only as a BENCHMARK for team goals / BTTS where no price exists."""
    best, best_err = None, 1e9
    for i in range(2, 91):
        tot = i * 0.05
        # P(total > 2.5)
        pov = 1.0 - sum(poisson_pmf(k, tot) for k in range(3))
        e1 = (pov - p_over25) ** 2
        if e1 > 0.01:
            continue
        for j in range(1, 100):
            share = j / 100.0
            lh, la = tot * share, tot * (1 - share)
            ph = pa = 0.0
            for h in range(11):
                for a in range(11):
                    pr = poisson_pmf(h, lh) * poisson_pmf(a, la)
                    if h > a:
                        ph += pr
                    elif a > h:
                        pa += pr
            err = e1 + (ph - p_home) ** 2 + (pa - p_away) ** 2
            if err < best_err:
                best, best_err = (lh, la), err
    return best


# ---------- statistics ----------

def boot_ci(units, stat, reps=2000, seed=11):
    """Percentile CI, resampling UNITS (a match, or a match's list of rows)."""
    rng = random.Random(seed)
    k = len(units)
    if k < 5:
        return (float("nan"), float("nan"))
    vals = sorted(stat([units[rng.randrange(k)] for _ in range(k)]) for _ in range(reps))
    return vals[int(0.025 * reps)], vals[int(0.975 * reps) - 1]


def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else float("nan")
