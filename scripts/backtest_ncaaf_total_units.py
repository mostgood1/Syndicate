"""What do ACTUAL NCAAF totals support, as a function of team ratings?

THE NCAAF HALF OF `#686`. `backtest_nfl_rating_units.py --total-level` answers
this for the NFL and nothing answered it for NCAAF, which is why the shared
`smartsim2` repair could not be attempted for both sports: arming
`drive_success_sensitivity` for NCAAF without this would be changing that
sport's totals with no evidence behind them.

  * IT MAKES NO CFBD CALLS. Everything comes from the committed
    `data/ncaaf_source/historical_truth/` tree (games + per-week plays carrying
    CFBD's own `ppa`). That is deliberate and not merely convenient: the CFBD
    quota is MONTHLY and shared by ten snapshot builders on one key, and
    exhausting it already caused a real incident (`cfbd_quota_latch.py` --
    14 generator attempts in a day against a 4.25-day-stale artifact). A
    backtest is exactly the kind of caller that should never spend it.
  * WALK-FORWARD. A week-w rating uses only plays from weeks STRICTLY BEFORE w,
    blended with the prior season the same way the NFL path blends.
  * FITTED ON ACTUAL TOTALS, NEVER ON THE MARKET. The market is not even loaded
    here; `#684`'s whole defence is that the NFL shrink was fitted against
    outcomes, and this has to meet the same bar.
  * COVERAGE IS PRINTED BEFORE ANY FIT. A missing season loads as an EMPTY
    table rather than raising, and that silently turned a "train 2023-24,
    n=544" into 2024 alone earlier in this work. Never again without the count
    in front of it.

TWO BASES, AND THE DIFFERENCE BETWEEN THEM IS THE WHOLE POINT:

  default      per-play PPA summed to a game, walk-forward in-season. The BEST
               available rating, but NOT the engine's units, so its coefficients
               cannot be turned into a keep ratio.
  --sp-units   centred SP+ / SP_RATING_SCALE with DEFENCE NEGATED, i.e. exactly
               what `sp_offense_defense_rating` hands the engine. Comparable to
               the engine's measured response -- but built from the PRIOR
               season's SP+, because every `sp_ratings_*.json` cache was fetched
               in Sept 2026, so a within-season fit would predict games from
               ratings computed OUT OF those games. A prior-season rating is
               strictly weaker than the in-season blend the engine actually
               uses mid-season, so the keep ratios it implies are a LOWER BOUND.

THE TEAM-NAME JOIN USES THE GENERATOR'S OWN `norm()`, NOT `.lower()`. That is
not a detail: `norm` maps "state" -> "st" and strips punctuation, and without it
22.5% / 23.4% of team-slots failed to match ("Florida State" never finds
"florida st"). With it, 0.7% / 1.4% -- and the residue is not a name bug at all,
it is Kennesaw State (2024), Missouri State and Delaware (2025) MOVING UP TO
FBS, so they genuinely have no prior-season SP+ and dropping them is correct.
Fixing the join moved the keep ratios barely at all (0.068 -> 0.062 offence,
0.222 -> 0.253 defence), which is worth knowing: the coverage hole cost
credibility, not accuracy.

Usage:
  py -3 scripts/backtest_ncaaf_total_units.py
  py -3 scripts/backtest_ncaaf_total_units.py --sp-units
"""
from __future__ import annotations

import gzip
import json
import math
import statistics
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# The committed mirror. `data/` is excluded from session worktrees, so fall back
# to the primary checkout rather than silently fitting on nothing.
_CANDIDATES = (
    REPO / "data" / "ncaaf_source" / "historical_truth",
    Path(r"C:\Users\tempadmin\OneDrive\Coding\Syndicate\data\ncaaf_source\historical_truth"),
)
PRIOR_GAMES = 4.0  # mirrors NFL_TOTAL / NFL_RATING_PRIOR_GAMES


def truth_root() -> Path:
    for path in _CANDIDATES:
        if path.exists():
            return path
    raise SystemExit(f"no historical_truth tree found; looked in {[str(p) for p in _CANDIDATES]}")


def _load(path: Path):
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def season_games(season: int) -> list[dict]:
    """FBS-vs-FBS completed games with both scores, which is the projection scope."""
    path = truth_root() / f"games_{season}.json.gz"
    if not path.exists():
        return []
    out = []
    for row in _load(path):
        if row.get("homeClassification") != "fbs" or row.get("awayClassification") != "fbs":
            continue
        hp, ap = row.get("homePoints"), row.get("awayPoints")
        if hp is None or ap is None:
            continue
        week = row.get("week")
        if week is None:
            continue
        out.append({
            "season": season, "week": int(week),
            "home": row.get("homeTeam"), "away": row.get("awayTeam"),
            "total": float(hp) + float(ap), "margin": float(hp) - float(ap),
        })
    return out


def per_week_ppa(season: int) -> dict[str, dict[str, dict[int, float]]]:
    """team -> 'o'/'d' -> {week: PPA summed over that week's plays}.

    CFBD's `ppa` is per PLAY, so summing to the week and dividing by weeks
    played gives a per-GAME figure -- the same shape `_epa_per_game` builds for
    the NFL, and the units the level fit wants.
    """
    table: dict[str, dict[str, dict[int, float]]] = {}
    root = truth_root()
    for week in range(0, 17):
        path = root / f"plays_{season}_wk{week:02d}.json.gz"
        if not path.exists():
            continue
        for play in _load(path):
            ppa = play.get("ppa")
            if ppa is None:
                continue
            try:
                value = float(ppa)
            except (TypeError, ValueError):
                continue
            wk = play.get("week")
            if wk is None:
                continue
            wk = int(wk)
            for team, side in ((play.get("offense"), "o"), (play.get("defense"), "d")):
                if not team:
                    continue
                bucket = table.setdefault(team, {}).setdefault(side, {})
                bucket[wk] = bucket.get(wk, 0.0) + value
    return table


def centred_per_game(table, team, side, before_week):
    """(per-game PPA minus the league per-TEAM mean, games played)."""
    def per_game(name):
        weeks = [v for w, v in table.get(name, {}).get(side, {}).items()
                 if before_week is None or w < before_week]
        return (sum(weeks) / len(weeks), len(weeks)) if weeks else (None, 0)

    value, games = per_game(team)
    if value is None:
        return None, 0
    means = [v for v, _ in (per_game(t) for t in table) if v is not None]
    if not means:
        return None, 0
    return value - sum(means) / len(means), games


def rows(season: int, tables: dict[int, dict]) -> list[dict]:
    cur, pri = tables.get(season, {}), tables.get(season - 1, {})
    cache: dict = {}

    def rate(team, week, side):
        key = (team, week, side)
        if key not in cache:
            c, n = centred_per_game(cur, team, side, week)
            p, _ = centred_per_game(pri, team, side, None)
            if c is None:
                cache[key] = p
            elif p is None or PRIOR_GAMES <= 0:
                cache[key] = c
            else:
                cache[key] = (n * c + PRIOR_GAMES * p) / (n + PRIOR_GAMES)
        return cache[key]

    out = []
    for game in season_games(season):
        parts = [rate(t, game["week"], s) for t in (game["home"], game["away"]) for s in ("o", "d")]
        if any(p is None for p in parts):
            continue
        ho, hd, ao, ad = parts
        out.append({**game, "osum": ho + ao, "dsum": hd + ad, "odif": ho - ao, "ddif": hd - ad})
    return out


def fit(X, y):
    n, k = len(y), len(X[0])
    m = [statistics.fmean(c) for c in zip(*X)]
    my = statistics.fmean(y)
    Xc = [[v - mi for v, mi in zip(r, m)] for r in X]
    yc = [v - my for v in y]
    A = [[sum(Xc[i][a] * Xc[i][b] for i in range(n)) for b in range(k)] for a in range(k)]
    B = [sum(Xc[i][a] * yc[i] for i in range(n)) for a in range(k)]
    M = [A[i][:] + [B[i]] for i in range(k)]
    for c in range(k):
        piv = max(range(c, k), key=lambda r: abs(M[r][c]))
        M[c], M[piv] = M[piv], M[c]
        for r in range(k):
            if r != c:
                f = M[r][c] / M[c][c]
                for j in range(c, k + 1):
                    M[r][j] -= f * M[c][j]
    beta = [M[i][k] / M[i][i] for i in range(k)]
    pred = [my + sum(b * v for b, v in zip(beta, r)) for r in Xc]
    ss = sum((a - b) ** 2 for a, b in zip(y, pred))
    tot = sum(v * v for v in yc)
    return my - sum(b * mi for b, mi in zip(beta, m)), beta, 1 - ss / tot


# What the NCAAF engine itself applies, measured 2026-09-23 on 5x5 grids with
# one direction pinned at zero, using the PROMOTED profile
# (`ncaaf-goal-line-refit-1`, 24 overrides) -- which is what production runs and
# which responds MORE strongly than the shipped default (+17.00/-11.04 level,
# +7.46/-4.93 difference). R2 0.984-0.991.
ENGINE_LEVEL = (23.1717, -14.2067)
ENGINE_DIFFERENCE = (9.5921, -5.2508)


def sp_rows(season: int, rating_season: int):
    """Games rated by the PRIOR season's SP+, in the engine's own units.

    Joined with the generator's `norm()`. Returns (rows, dropped)."""
    from scripts.generate_smartsim2_ncaaf_projections import SP_RATING_SCALE, norm

    raw = json.loads((truth_root() / f"sp_ratings_{rating_season}.json").read_text(encoding="utf-8"))["teams"]
    index = {norm(k): (float(v[0]), float(v[1])) for k, v in raw.items()}
    off_mean = statistics.fmean(v[0] for v in index.values())
    def_mean = statistics.fmean(v[1] for v in index.values())
    out, dropped = [], 0
    for game in season_games(season):
        home, away = index.get(norm(game["home"])), index.get(norm(game["away"]))
        if home is None or away is None:
            dropped += 1  # a team that moved up to FBS has no prior-season SP+
            continue
        ho, hd = (home[0] - off_mean) / SP_RATING_SCALE, -(home[1] - def_mean) / SP_RATING_SCALE
        ao, ad = (away[0] - off_mean) / SP_RATING_SCALE, -(away[1] - def_mean) / SP_RATING_SCALE
        out.append({**game, "osum": ho + ao, "dsum": hd + ad, "odif": ho - ao, "ddif": hd - ad})
    return out, dropped


def run_sp_units() -> None:
    train, dropped_tr = sp_rows(2024, 2023)
    test, dropped_te = sp_rows(2025, 2024)
    print("ENGINE UNITS (centred SP+/10, defence negated), PRIOR-season ratings\n")
    print(f"COVERAGE: train 2024 n={len(train)} (dropped {dropped_tr})   "
          f"test 2025 n={len(test)} (dropped {dropped_te})")
    print("  dropped = teams with no prior-season SP+ because they moved up to FBS\n")
    if not train or not test:
        raise SystemExit("insufficient coverage to fit -- refusing rather than reporting a number")
    specs = {
        "level only        ": lambda r: [r["osum"], r["dsum"]],
        "level + difference": lambda r: [r["osum"], r["dsum"], r["odif"], r["ddif"]],
    }
    for name, f in specs.items():
        a, b, r2 = fit([f(r) for r in train], [r["total"] for r in train])
        err = [abs(a + sum(bi * xi for bi, xi in zip(b, f(r))) - r["total"]) for r in test]
        print(f"  {name}  train R2 {r2:.4f}  held-out MAE {statistics.fmean(err):6.3f}  "
              f"coeffs {[round(x, 3) for x in b]}")
    flat = statistics.fmean([r["total"] for r in train])
    print(f"  {'flat league mean  ':18}  {'':15}  held-out MAE "
          f"{statistics.fmean(abs(flat - r['total']) for r in test):6.3f}")
    _, b, _ = fit([[r["osum"], r["dsum"]] for r in train], [r["total"] for r in train])
    print(f"\n  ACTUALS support level ({b[0]:+.3f}, {b[1]:+.3f})")
    print(f"  ENGINE applies        ({ENGINE_LEVEL[0]:+.3f}, {ENGINE_LEVEL[1]:+.3f})")
    print(f"  implied keep ratios:  offence {b[0]/ENGINE_LEVEL[0]:.3f}   defence {b[1]/ENGINE_LEVEL[1]:.3f}")
    print("\n  THESE ARE A LOWER BOUND, NOT A SETTING. The prior-season SP+ used here is")
    print("  strictly weaker than the in-season blend the engine consumes mid-season, and a")
    print("  weaker predictor earns smaller coefficients. Reconstruct an as-of-week rating")
    print("  before turning any of this into drive_success_sensitivity.")


def run_asof() -> None:
    """The fit that can actually set a keep ratio: AS-OF-WEEK ratings.

    Uses the construction the generator really runs mid-season -- `blend_ppa`
    at k=2, prior-season SP+ blended with a ridge SRS on in-season PPA at
    weight n/(n+k) -- via `backtest_ncaaf_inseason_blend`'s own loaders and
    `ratings_asof`, so this is the code that was already graded rather than a
    reimplementation. Leak-free by construction (week N uses weeks < N), and
    offline: `ppa_source="plays"` reads the committed plays, never CFBD.

    That blend was graded on MARGIN (12.830 vs 16.334 for the static prior).
    TOTALS were never graded on it, which is the gap this fills.
    """
    from pathlib import Path as _P

    import scripts.backtest_ncaaf_inseason_blend as B
    from scripts.generate_smartsim2_ncaaf_projections import (
        INSEASON_BLEND_K, INSEASON_BLEND_MIN_WEEK, SP_RATING_SCALE, norm,
    )

    data_root = None
    for cand in (REPO / "data" / "ncaaf_source",
                 _P(r"C:\Users\tempadmin\OneDrive\Coding\Syndicate\data\ncaaf_source")):
        if (cand / "historical_truth").exists():
            data_root = cand
            break
    if data_root is None:
        raise SystemExit("no ncaaf_source tree found")

    s_train = B.load_season(data_root, None, 2024, None, ppa_source="plays")
    s_test = B.load_season(data_root, None, 2025, s_train, ppa_source="plays")
    setting = B.Setting("blend_ppa", INSEASON_BLEND_K)

    def build(sd):
        out, dropped, by_week = [], 0, {}
        for g in sd.games:
            if not (g.home_fbs and g.away_fbs) or g.week < INSEASON_BLEND_MIN_WEEK:
                continue
            if g.week not in by_week:
                by_week[g.week] = B.ratings_asof(setting, sd.prior, sd.games, sd.ppa,
                                                 g.week, sd.beta, sd.index_cache)
            idx = by_week[g.week]
            home = idx.get(norm(g.home)) or idx.get(g.home)
            away = idx.get(norm(g.away)) or idx.get(g.away)
            if home is None or away is None:
                dropped += 1
                continue
            om = statistics.fmean(v[0] for v in idx.values())
            dm = statistics.fmean(v[1] for v in idx.values())
            ho, hd = (home[0] - om) / SP_RATING_SCALE, -(home[1] - dm) / SP_RATING_SCALE
            ao, ad = (away[0] - om) / SP_RATING_SCALE, -(away[1] - dm) / SP_RATING_SCALE
            out.append({"total": g.home_points + g.away_points, "week": g.week,
                        "osum": ho + ao, "dsum": hd + ad, "odif": ho - ao, "ddif": hd - ad})
        return out, dropped

    train, dt = build(s_train)
    test, ds = build(s_test)
    print(f"AS-OF-WEEK ratings (blend_ppa k={INSEASON_BLEND_K}, weeks >= {INSEASON_BLEND_MIN_WEEK}), ENGINE units")
    print(f"  beta: train {s_train.beta_source}   test {s_test.beta_source}")
    print(f"  COVERAGE: train 2024 n={len(train)} (dropped {dt})   test 2025 n={len(test)} (dropped {ds})\n")
    specs = {
        "level only        ": lambda r: [r["osum"], r["dsum"]],
        "level + difference": lambda r: [r["osum"], r["dsum"], r["odif"], r["ddif"]],
    }
    for name, f in specs.items():
        a, b, r2 = fit([f(r) for r in train], [r["total"] for r in train])
        err = [abs(a + sum(bi * xi for bi, xi in zip(b, f(r))) - r["total"]) for r in test]
        print(f"  {name}  train R2 {r2:.4f}  held-out MAE {statistics.fmean(err):6.3f}  "
              f"coeffs {[round(x, 3) for x in b]}")
    flat = statistics.fmean([r["total"] for r in train])
    print(f"  {'flat league mean  ':18}  {'':15}  held-out MAE "
          f"{statistics.fmean(abs(flat - r['total']) for r in test):6.3f}")
    _, b, _ = fit([[r["osum"], r["dsum"]] for r in train], [r["total"] for r in train])
    print(f"\n  ACTUALS support level ({b[0]:+.3f}, {b[1]:+.3f})")
    print(f"  ENGINE applies        ({ENGINE_LEVEL[0]:+.3f}, {ENGINE_LEVEL[1]:+.3f})")
    print(f"  keep ratios: offence {b[0]/ENGINE_LEVEL[0]:.3f}   defence {b[1]/ENGINE_LEVEL[1]:.3f}")
    print("  (--sp-units, on the DEGRADED prior-season basis, gave 0.062 / 0.253 --")
    print("   about half, exactly as a lower bound should behave)")


def main() -> None:
    print(f"truth tree: {truth_root()}\n")
    if "--asof" in sys.argv:
        run_asof()
        return
    if "--sp-units" in sys.argv:
        run_sp_units()
        return
    tables = {s: per_week_ppa(s) for s in (2022, 2023, 2024, 2025)}
    print("COVERAGE, printed before any fit:")
    for s in (2022, 2023, 2024, 2025):
        print(f"   plays {s}: {len(tables[s]):>4} teams   games {s}: {len(season_games(s)):>4}")
    data = {s: rows(s, tables) for s in (2023, 2024, 2025)}
    for s, v in data.items():
        print(f"   rated rows {s}: {len(v)}")
    train = data[2023] + data[2024]
    test = data[2025]
    print(f"   TRAIN {len(train)}   TEST {len(test)}\n")
    if not train or not test:
        raise SystemExit("insufficient coverage to fit -- refusing rather than reporting a number")

    specs = {
        "level only        ": lambda r: [r["osum"], r["dsum"]],
        "level + difference": lambda r: [r["osum"], r["dsum"], r["odif"], r["ddif"]],
    }
    print("WHAT ACTUAL NCAAF TOTALS SUPPORT (fit on 2023-24, scored on a held-out 2025)\n")
    for name, f in specs.items():
        a, b, r2 = fit([f(r) for r in train], [r["total"] for r in train])
        err = [abs(a + sum(bi * xi for bi, xi in zip(b, f(r))) - r["total"]) for r in test]
        print(f"  {name}  train R2 {r2:.4f}   held-out MAE {statistics.fmean(err):6.3f}")
        print(f"                      coeffs {[round(x, 4) for x in b]}")
    flat = statistics.fmean([r["total"] for r in train])
    print(f"  {'flat league mean  ':18}  {'':16}   held-out MAE {statistics.fmean(abs(flat - r['total']) for r in test):6.3f}")

    xs = [abs(r["margin"]) for r in test]
    ys = [r["total"] for r in test]
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sxy = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    sxx = sum((a - mx) ** 2 for a in xs)
    syy = sum((b - my) ** 2 for b in ys)
    # LABELLED, NOT QUIETLY REPORTED. This uses |ACTUAL margin|, which is an
    # OUTCOME and therefore partly mechanically tied to the total (a high-scoring
    # game has more room for a big margin). It is NOT comparable to the NFL's
    # `corr(|market spread|, ACTUAL total) = -0.032`, which uses a PRE-GAME
    # quantity. The clean NCAAF test of "does mismatch predict a total" is the
    # held-out MAE comparison above, and it says NO -- adding the difference
    # terms makes it WORSE out of sample (12.859 vs 12.839).
    print(f"\n  corr(|ACTUAL margin|, ACTUAL total) on 2025: {sxy / math.sqrt(sxx * syy):+.3f}"
          "  <- CONTAMINATED: outcome, not a pre-game line. See the source note.")
    print(f"  SD of actual totals: train {statistics.pstdev([r['total'] for r in train]):.2f}  "
          f"test {statistics.pstdev(ys):.2f}")


if __name__ == "__main__":
    main()
