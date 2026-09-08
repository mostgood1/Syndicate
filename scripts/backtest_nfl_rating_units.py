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


if __name__ == "__main__":
    have = [s for s in (2022, 2023, 2024, 2025)
            if (REPO / f"data/nfl_source/tracking/nflverse/pbp/pbp_{s}.csv").exists()]
    print("pbp seasons available:", have)
    seasons = [s for s in have if (s - 1) in have]
    print("usable (need prior season for wk1 fallback):", seasons)
    if len(seasons) >= 2:
        train, test = seasons[:-1], seasons[-1]
        run(train, test, per_game=True, label="POINTS-PER-GAME rating (the fix)")
        run(train, test, per_game=False, label="PER-PLAY rating (production today)")
