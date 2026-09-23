"""Does an NFL rating differential predict margin out-of-sample, and at what scale?

THE QUESTION THIS ANSWERS is the one `_points_per_game_ratings_enabled`'s
docstring deferred: "A scale belongs to a lane that can validate it
out-of-sample, not to the lane that noticed the units were wrong."

DESIGN, and the two traps it avoids:
  * WALK-FORWARD. A game in week w rates both teams from plays STRICTLY BEFORE
    week w in its own season, falling back to the prior season entire when that
    is empty (weeks 1-2). No game contributes to its own rating.
  * THE SCALE IS FITTED ON TRAIN SEASONS AND REPORTED ON A HELD-OUT ONE. Fitting
    a coefficient so output SD matches the market's SD is the fit the ledger's
    soccer precedent warns about -- it looked better on the metric it was fitted
    to and still lost. OLS against ACTUAL MARGIN, scored on a season the fit
    never saw, cannot flatter itself that way.

CENTRING CANCELS in a differential -- (off_h - mu) - (off_a - mu) -- so this
works in raw per-game EPA and never needs the league mean.
"""
from __future__ import annotations

import argparse
import csv
import io
import statistics
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
from scripts.generate_smartsim2_nfl_projections import (  # noqa: E402
    _epa_per_game, _mean_epa, load_pbp_plays,
)

NFLVERSE_GAMES_URL = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"


def load_games_csv(cache: Path | None = None) -> str:
    """nflverse `games.csv`: outcomes AND closing lines for every season.

    `spread_line` here is HOME-MARGIN-POSITIVE, not bet notation. That is not a
    detail -- assuming otherwise inverts the market and was a live defect in
    `backfill_nfl_performance.py` until 2026-09-07.
    """
    if cache and cache.exists():
        return cache.read_text(encoding="utf-8")
    req = urllib.request.Request(NFLVERSE_GAMES_URL,
                                 headers={"User-Agent": "syndicate-nfl-rating-units/1.0"})
    with urllib.request.urlopen(req, timeout=60) as response:
        text = response.read().decode("utf-8-sig")
    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(text, encoding="utf-8")
    return text


_GAMES_TEXT: str | None = None

# nflverse pbp and the schedule spell some clubs differently; the generator
# already owns this map, but only for the names it needed. These are the pairs
# that actually differ across the seasons used here.
ALIAS = {"LA": "LAR", "OAK": "LV", "SD": "LAC", "STL": "LAR"}
def norm(t): return ALIAS.get((t or "").strip(), (t or "").strip())


def season_games(season):
    global _GAMES_TEXT
    if _GAMES_TEXT is None:
        _GAMES_TEXT = load_games_csv(REPO / "data" / "nfl_source" / "nflverse_games.csv")
    rows = list(csv.DictReader(io.StringIO(_GAMES_TEXT)))
    out = []
    for r in rows:
        if r.get("season") != str(season) or r.get("game_type") != "REG":
            continue
        if not (r.get("home_score") and r.get("away_score") and r.get("spread_line")):
            continue
        try:
            out.append({
                "week": int(r["week"]),
                "home": norm(r["home_team"]), "away": norm(r["away_team"]),
                "margin": float(r["home_score"]) - float(r["away_score"]),
                "market": float(r["spread_line"]),      # nflverse spread_line is ALREADY
                # home-margin-positive (VERIFIED 2026-09-07: as-is gives market
                # SU 65.3% / MAE 9.72; negated gives 34.7% / 14.49, i.e. worse
                # than a coin flip, which is how the sign error announced itself).
                "total": float(r["home_score"]) + float(r["away_score"]),
                "market_total": float(r["total_line"]) if r.get("total_line") else None,
            })
        except (TypeError, ValueError):
            continue
    return out


def rating_rows(season, *, per_game=True):
    """One row per game: rating differential (home minus away) + outcome."""
    cur = load_pbp_plays(season)
    prior = load_pbp_plays(season - 1)
    if not cur and not prior:
        return []
    fn = _epa_per_game if per_game else (
        lambda plays, *, team, side, before_week: _mean_epa(
            plays, team=team, side=side, before_week=before_week))

    cache = {}
    def rate(team, week):
        key = (team, week)
        if key in cache:
            return cache[key]
        off = fn(cur, team=team, side="offense", before_week=week)
        dfn = fn(cur, team=team, side="defense", before_week=week)
        src = "current"
        if off is None or dfn is None:
            off = fn(prior, team=team, side="offense", before_week=None)
            dfn = fn(prior, team=team, side="defense", before_week=None)
            src = "prior"
        cache[key] = None if (off is None or dfn is None) else (off, dfn, src)
        return cache[key]

    rows = []
    for g in season_games(season):
        h, a = rate(g["home"], g["week"]), rate(g["away"], g["week"])
        if h is None or a is None:
            continue
        # (offence_h - offence_a) - (defence_allowed_h - defence_allowed_a)
        diff = (h[0] - a[0]) - (h[1] - a[1])
        rows.append({**g, "diff": diff, "src": f"{h[2]}/{a[2]}"})
    return rows


def ols(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    b = sxy / sxx if sxx else 0.0
    return my - b * mx, b


def score(rows, a, b):
    pred = [a + b * r["diff"] for r in rows]
    act = [r["margin"] for r in rows]
    mkt = [r["market"] for r in rows]
    n = len(rows)
    mae = lambda p: sum(abs(x - y) for x, y in zip(p, act)) / n
    rmse = lambda p: (sum((x - y) ** 2 for x, y in zip(p, act)) / n) ** 0.5
    # Straight-up winner agreement, ties excluded.
    hit = lambda p: sum(1 for x, y in zip(p, act) if y != 0 and (x > 0) == (y > 0))
    played = sum(1 for y in act if y != 0)
    return {
        "n": n, "pred_sd": statistics.pstdev(pred), "mkt_sd": statistics.pstdev(mkt),
        "model_mae": mae(pred), "market_mae": mae(mkt),
        "model_rmse": rmse(pred), "market_rmse": rmse(mkt),
        "model_su": hit(pred) / played, "market_su": hit(mkt) / played,
        "flat_mae": mae([statistics.mean(act)] * n),
    }


def run(train_seasons, test_season, *, per_game, label):
    tr = [r for s in train_seasons for r in rating_rows(s, per_game=per_game)]
    te = rating_rows(test_season, per_game=per_game)
    if not tr or not te:
        print(f"{label}: insufficient data (train {len(tr)}, test {len(te)})")
        return None
    a, b = ols([r["diff"] for r in tr], [r["margin"] for r in tr])
    s = score(te, a, b)
    print(f"\n=== {label} ===")
    print(f"  fit on {train_seasons} (n={len(tr)}), tested on {test_season} (n={s['n']})")
    print(f"  fitted: margin = {a:+.2f} {b:+.3f} * rating_diff   "
          f"[rating_diff SD train {statistics.pstdev([r['diff'] for r in tr]):.3f}]")
    print(f"  predicted margin SD  {s['pred_sd']:6.2f}   (market {s['mkt_sd']:.2f})")
    print(f"  MAE   model {s['model_mae']:6.2f}   market {s['market_mae']:6.2f}   "
          f"flat {s['flat_mae']:6.2f}")
    print(f"  RMSE  model {s['model_rmse']:6.2f}   market {s['market_rmse']:6.2f}")
    print(f"  SU%   model {s['model_su']*100:5.1f}%  market {s['market_su']*100:5.1f}%")
    return {"a": a, "b": b, **s}


def _per_week_table(plays):
    """team -> side ('o'/'d') -> {week: EPA summed over that game}."""
    table = {}
    for week, posteam, defteam, _play_type, epa in plays:
        for team, side in ((posteam, "o"), (defteam, "d")):
            if team:
                bucket = table.setdefault(team, {}).setdefault(side, {})
                bucket[week] = bucket.get(week, 0.0) + epa
    return table


def _centred_per_game(table, team, side, before_week):
    """(per-game EPA minus the league's per-TEAM mean, games) -- `_rating_pair`'s
    centring, without its scale (a linear factor the fitted slope absorbs)."""
    def per_game(t):
        weeks = [v for w, v in table.get(t, {}).get(side, {}).items() if before_week is None or w < before_week]
        return (sum(weeks) / len(weeks), len(weeks)) if weeks else (None, 0)
    value, games = per_game(team)
    if value is None:
        return None, 0
    means = [v for v, _ in (per_game(t) for t in table) if v is not None]
    return value - sum(means) / len(means), games


_TABLES = {}


def _season_table(season):
    # A pbp season is ~100 MB of CSV; the K grid would otherwise re-read it per K.
    if season not in _TABLES:
        _TABLES[season] = _per_week_table(load_pbp_plays(season))
    return _TABLES[season]


def level_rows(season, prior_games=4.0):
    """`blend_rows`, but carrying the two directions SEPARATELY.

    The MARGIN reads the teams' DIFFERENCE, the TOTAL reads their common LEVEL,
    and the engine applies one gain to both. `--total-level` fits the level's
    own gain; `--prior-games` and the scale fit the difference's.

    THE DEFENCE SIGN DIFFERS BETWEEN THE TWO DIRECTIONS AND IT IS EASY TO GET
    BACKWARDS. `_centred_per_game(..., 'd', ...)` is EPA ALLOWED -- higher is a
    WORSE defence -- and is NOT negated here, though `_rating_pair` negates it
    before the engine sees it. So the margin takes `-(hd - ad)` (a better home
    defence RAISES the home margin) while the total takes `+(hd + ad)` (two
    leakier defences RAISE the total). Regressing the total on `(o_h+o_a) -
    (d_h+d_a)` instead measured r = 0.19 against the engine's own output on
    2026 wk3 and read as "the ratings barely drive the total"; on the correct
    basis the same 16 games give R2 = 0.89. Fit the two components separately
    when in doubt -- it is what caught this.
    """
    cur, pri = _season_table(season), _season_table(season - 1)
    cache = {}

    def rate(team, week, side):
        key = (team, week, side)
        if key not in cache:
            c, n = _centred_per_game(cur, team, side, week)
            p, _ = _centred_per_game(pri, team, side, None)
            if c is None:
                cache[key] = p
            elif p is None or prior_games <= 0:
                cache[key] = c
            else:
                cache[key] = (n * c + prior_games * p) / (n + prior_games)
        return cache[key]

    rows = []
    for g in season_games(season):
        home, away = ({"LAR": "LA"}.get(t, t) for t in (g["home"], g["away"]))
        parts = [rate(t, g["week"], s) for t in (home, away) for s in ("o", "d")]
        if None in parts:
            continue
        ho, hd, ao, ad = parts
        rows.append({**g, "osum": ho + ao, "dsum": hd + ad})
    return rows


# WHAT THE ENGINE ITSELF APPLIES TO THE LEVEL, at NFL_RATING_SCALE 20 with the
# K=4 blend. Measured by regressing the GENERATOR's own `total_mean` on the two
# level components over 2025 weeks 5/9/10/13/17 (300 seeds, all flags default),
# pooled -- the same method `ENGINE_SLOPE_AT_SCALE_20` uses for the margin, on a
# larger sample because a single week's n=14 put the pair at 0.631/0.444 while
# production's 2026 wk3 n=16 put it at 0.797/0.764.
ENGINE_TOTAL_LEVEL_COEFFS = (0.797, 0.764)  # (offence_sum, defence_sum)


def run_total_level(train_seasons, test_season, grid=(0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.8, 1.0)):
    """Choose the level SHRINK on TRAIN against ACTUAL totals, report held out.

    lambda = 1.0 is what production does today. The engine's level term is held
    FIXED at what it actually applies, so lambda is the only free parameter and
    it means exactly one thing: the fraction of the level the engine should keep.
    """
    bo, bd = ENGINE_TOTAL_LEVEL_COEFFS
    def level(r):
        return bo * r["osum"] + bd * r["dsum"]

    fits = {}
    train = [r for s in train_seasons for r in level_rows(s)]
    for lam in grid:
        a = statistics.fmean(r["total"] - lam * level(r) for r in train)
        fits[lam] = (a, sum(abs(a + lam * level(r) - r["total"]) for r in train) / len(train))
        print(f"  lambda={lam:<4}  train MAE {fits[lam][1]:.3f}")
    chosen = min(fits, key=lambda k: fits[k][1])
    print(f"\nchosen on {train_seasons}: lambda={chosen}; tested on {test_season}")
    test = level_rows(test_season)
    for name, lo, hi in (("wk1", 1, 1), ("wk2-4", 2, 4), ("wk5-9", 5, 9), ("wk10+", 10, 99), ("ALL", 1, 99)):
        sel = [r for r in test if lo <= r["week"] <= hi]
        if not sel:
            continue
        errs = {k: [abs(fits[k][0] + k * level(r) - r["total"]) for r in sel] for k in (1.0, chosen)}
        delta = [x - y for x, y in zip(errs[chosen], errs[1.0])]
        mk = [r for r in sel if r.get("market_total")]
        market = statistics.fmean(abs(r["market_total"] - r["total"]) for r in mk) if mk else float("nan")
        print(f"  {name:6} n={len(sel):3}  today {statistics.fmean(errs[1.0]):6.2f}  "
              f"lambda={chosen} {statistics.fmean(errs[chosen]):6.2f}  (delta {statistics.fmean(delta):+.2f} +- "
              f"{statistics.pstdev(delta) / len(delta) ** 0.5:.2f})  market {market:6.2f}")
    sd_today = statistics.pstdev([fits[1.0][0] + level(r) for r in test])
    sd_new = statistics.pstdev([fits[chosen][0] + chosen * level(r) for r in test])
    mk = [r for r in test if r.get("market_total")]
    print(f"\n  SD of the model's own totals on {test_season}: today {sd_today:.2f} -> "
          f"lambda={chosen} {sd_new:.2f}   (market {statistics.pstdev([r['market_total'] for r in mk]):.2f})")


def blend_rows(season, prior_games):
    """`team_rating`'s per-game path: this season's games blended with the prior
    season as (n*current + K*prior)/(n+K); K=0 is the pre-2026-09-21 estimator
    (current if any, else prior). Pbp spells the Rams `LA`."""
    cur, pri = _season_table(season), _season_table(season - 1)
    cache = {}

    def rate(team, week, side):
        key = (team, week, side)
        if key not in cache:
            c, n = _centred_per_game(cur, team, side, week)
            p, _ = _centred_per_game(pri, team, side, None)
            if c is None:
                cache[key] = p
            elif p is None or prior_games <= 0:
                cache[key] = c
            else:
                cache[key] = (n * c + prior_games * p) / (n + prior_games)
        return cache[key]

    rows = []
    for g in season_games(season):
        home, away = ({"LAR": "LA"}.get(t, t) for t in (g["home"], g["away"]))
        parts = [rate(t, g["week"], s) for t in (home, away) for s in ("o", "d")]
        if None in parts:
            continue
        ho, hd, ao, ad = parts
        rows.append({**g, "diff": (ho - ao) - (hd - ad)})
    return rows


# The slope the ENGINE applies at NFL_RATING_SCALE 20, measured 2026-09-21 by
# regressing production's own 2026 wk1 `margin_mean` (all 16 on
# prior_season_fallback) on this file's centred 2025 differential: 0.5471,
# intercept +0.59, residual SD 0.884. Not the ~0.42 the scale comment implies.
ENGINE_SLOPE_AT_SCALE_20 = 0.5471


def run_prior_games(train_seasons, test_season, grid=(0, 1, 2, 3, 4, 5, 6, 8, 10, 12)):
    """Choose K on TRAIN with the slope fixed at what production applies, then
    report the held-out season by week bucket against K=0 and the market."""
    b = ENGINE_SLOPE_AT_SCALE_20
    fits = {}
    for k in grid:
        tr = [r for s in train_seasons for r in blend_rows(s, k)]
        a = statistics.fmean(r["margin"] - b * r["diff"] for r in tr)
        fits[k] = (a, sum(abs(a + b * r["diff"] - r["margin"]) for r in tr) / len(tr))
        print(f"  K={k:>2}  train MAE {fits[k][1]:.3f}")
    chosen = min(fits, key=lambda k: fits[k][1])
    print(f"\nchosen on {train_seasons}: K={chosen}; tested on {test_season}, slope {b}")
    buckets = (("wk1", 1, 1), ("wk2-4", 2, 4), ("wk5-9", 5, 9), ("wk10+", 10, 99), ("ALL", 1, 99))
    tests = {k: blend_rows(test_season, k) for k in (0, chosen)}
    for name, lo, hi in buckets:
        sel = {k: [r for r in rows if lo <= r["week"] <= hi] for k, rows in tests.items()}
        errs = {k: [abs(fits[k][0] + b * r["diff"] - r["margin"]) for r in rows] for k, rows in sel.items()}
        delta = [x - y for x, y in zip(errs[chosen], errs[0])]
        market = statistics.fmean(abs(r["market"] - r["margin"]) for r in sel[0])
        print(f"  {name:6} n={len(delta):3}  K=0 {statistics.fmean(errs[0]):6.2f}  K={chosen} "
              f"{statistics.fmean(errs[chosen]):6.2f}  (delta {statistics.fmean(delta):+.2f} +- "
              f"{statistics.pstdev(delta) / len(delta) ** 0.5:.2f})  market {market:6.2f}")


if __name__ == "__main__":
    if "--prior-games" in sys.argv:
        run_prior_games((2023, 2024), 2025)
        raise SystemExit(0)
    if "--total-level" in sys.argv:
        run_total_level((2023, 2024), 2025)
        raise SystemExit(0)
    have = [s for s in (2022, 2023, 2024, 2025)
            if (REPO / f"data/nfl_source/tracking/nflverse/pbp/pbp_{s}.csv").exists()]
    print("pbp seasons available:", have)
    seasons = [s for s in have if (s - 1) in have]
    print("usable (need prior season for wk1 fallback):", seasons)
    if len(seasons) >= 2:
        train, test = seasons[:-1], seasons[-1]
        run(train, test, per_game=True, label="POINTS-PER-GAME rating (the fix)")
        run(train, test, per_game=False, label="PER-PLAY rating (production today)")
