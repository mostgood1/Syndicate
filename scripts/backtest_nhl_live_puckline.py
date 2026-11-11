"""Cutoff-replay grade of the NHL LIVE margin histogram, for puck-line pricing (lane nhl-live-puckline-grade).

WHY THIS EXISTS. `nhl/live_resim.resim_live_game` returns a 200-sim margin histogram that `build_game_lens`
publishes as `projection.displayMarginDist` -- DISPLAY ONLY (`#773`). `live_gameline_join` would PRICE live puck
lines the moment it were published as `marginDist`, and no NHL live margin estimator has ever been graded. This
harness is the ruler that decision would be made on. Nothing here opens it.

MODELLED ON `scripts/backtest_nfl_live_totals.py` (closed lane `nfl-live-distribution-grade`, which graded NFL's
live margins a measured FAIL at worst powered bucket 0.4290 against `#499`'s 0.150), and on that harness's rules:

  - THE HEADLINE IS THE WORST POWERED PREDICTED-PROBABILITY BUCKET, not an aggregate. A bucket below
    `MIN_BUCKET_N` is reported and excluded from the headline.
  - EVERY INTERVAL IS BOOTSTRAPPED OVER GAMES, NOT ROWS: six cutoffs of one game share its final.
  - PROVENANCE LEADS THE OUTPUT. The NHL engine's team and player rates are SEASON files
    (`processed/team_rates_<season>.csv` and siblings), rewritten every day and kept nowhere dated -- not on the
    fleet's disk, not in git. A replay of a past game therefore runs on rates that already contain that game and
    every game after it: better-informed inputs than production had that night. So a PASS here is an UPPER BOUND
    and licenses nothing; only a FAIL is decisive (the inputs can only flatter the model). The run prints the
    rate files' mtimes and the date range they postdate.

WHAT IT DOES. For every completed REGULAR-SEASON game on the dates asked, rebuilds the exact score at each cutoff
from `/v1/score/<date>`'s goal list (period + elapsed time of every goal, the shootout goal included), runs the
SHIPPED `resim_live_game` -- the same `HockeyGameFeatures` production builds (`build_slate_features` on the
producer's root), the same `sims`, no profile override -- and scores its histogram against the official final.

THE OUTCOME IS THE OFFICIAL FINAL MARGIN. NHL credits a shootout winner one goal (2-2 -> 3-2 SO), which is how
books settle a puck line, and the engine's histogram does the same (`resim_live_game`: "a final margin is never
0"). Both sides of the comparison therefore live on the same support.

THE PROBABILITY GRADED IS THE ONE THE BOARD SHOWS: P(home margin > line), Agresti-Coull smoothed
((c+2)/(n+4)), exactly `live_display_block`'s number. `line` is the AWAY-frame point the join reads, so -1.5 is
"home +1.5 covers" and +1.5 is "home -1.5 covers".

THE BASELINE IS A WIDTH-CORRECT, SKILL-FREE MODEL: rest-of-regulation goals as independent Poissons at the
sample's own home/away regulation scoring rates (Skellam), a regulation tie resolved +-1 at the sample's home
OT/SO win share. It knows the score and the clock and nothing about the teams. An engine that cannot beat it on
Brier is adding team knowledge that does not survive.

Usage (on the fleet host, nice 19, from the fleet checkout so the code graded is production's):
    cd ~/Syndicate && nice -n 19 ~/.venvs/syndicate/bin/python /path/to/backtest_nhl_live_puckline.py \\
        --start 2026-10-01 --end 2026-11-10 --source-root ~/syndicate-prod/data/nhl_source \\
        --out-dir /mnt/c/.../nhlgrade --workers 3
    ... --grade-only --out-dir <same>      # re-grade the saved rows without re-simulating
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import math
import os
import random
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SCORE_URL = "https://api-web.nhle.com/v1/score/{date}"
# `live_resim.fetch_score_rows`' own header: api-web.nhle.com 403s urllib's default User-Agent.
SCORE_HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

PERIOD_SECONDS = 20 * 60
REGULATION_PERIODS = 3
REGULAR_SEASON_GAME_TYPE = 2   # 1 = preseason, 3 = playoffs; a different population (season-phase rule)

# (period, seconds remaining, label). End of a period is read as the NEXT period at 20:00: production refuses
# during an intermission (`in_intermission`) and resumes the moment the next period starts, at this state.
CUTOFFS: tuple[tuple[int, int, str], ...] = (
    (1, 1200, "P1 20:00"),   # puck drop: bit-identical to the pregame sim (module docstring)
    (2, 1200, "P2 20:00"),
    (2, 600, "P2 10:00"),
    (3, 1200, "P3 20:00"),
    (3, 600, "P3 10:00"),
    (3, 300, "P3 05:00"),
)

PRIMARY_LINES = (-1.5, 1.5)      # the puck line: home +1.5, home -1.5
ALT_LINES = (-2.5, 2.5)
BUCKETS = tuple((i / 10.0, (i + 1) / 10.0) for i in range(10))
MIN_BUCKET_N = 30                # the NCAAF / NFL harnesses' floor
PASS_BAR = 0.150                 # `#499`'s worst-bucket bar
DEFAULT_SIMS = 200               # `live_resim._DEFAULT_SIMS`, production's count
BOOTSTRAP = 1000


# ---------------------------------------------------------------------------
# inputs
# ---------------------------------------------------------------------------

def fetch_score_day(date: str, cache_dir: Path | None) -> list[dict[str, Any]]:
    """`/v1/score/<date>` games, cached as JSON so a re-grade never re-fetches."""
    if cache_dir is not None:
        path = cache_dir / f"score_{date}.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    req = urllib.request.Request(SCORE_URL.format(date=date), headers=dict(SCORE_HEADERS))
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.load(resp)
    games = [g for g in (payload.get("games") or []) if isinstance(g, Mapping)]
    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / f"score_{date}.json").write_text(json.dumps(games), encoding="utf-8")
    return games


def _clock_to_seconds(text: Any) -> int | None:
    mm, _, ss = str(text or "").partition(":")
    try:
        return int(mm) * 60 + int(ss)
    except ValueError:
        return None


def completed_game(row: Mapping[str, Any]) -> dict[str, Any] | None:
    """A finished regular-season game as `{pk, home, away, final_home, final_away, last_period_type, goals}`,
    or None. `goals` is `[(period, elapsed_seconds, home_score_after, away_score_after, period_type)]`."""
    if str(row.get("gameState") or "").upper() not in {"OFF", "FINAL"}:
        return None
    if int(row.get("gameType") or 0) != REGULAR_SEASON_GAME_TYPE:
        return None
    home, away = row.get("homeTeam") or {}, row.get("awayTeam") or {}
    try:
        fh, fa = int(home.get("score")), int(away.get("score"))
    except (TypeError, ValueError):
        return None
    goals = []
    for g in row.get("goals") or []:
        period = int(g.get("period") or (g.get("periodDescriptor") or {}).get("number") or 0)
        elapsed = _clock_to_seconds(g.get("timeInPeriod"))
        if period < 1 or elapsed is None:
            return None   # an unreadable goal makes every later state unknowable: drop the game, counted
        goals.append((period, elapsed, int(g.get("homeScore")), int(g.get("awayScore")),
                      str((g.get("periodDescriptor") or {}).get("periodType") or "")))
    # The goal list must reproduce the official final, or the states built from it are wrong.
    last = goals[-1] if goals else (0, 0, 0, 0, "")
    if (last[2], last[3]) != (fh, fa) and not (fh == 0 and fa == 0):
        return None
    name = lambda b: str(((b.get("name") or {}).get("default")) or b.get("abbrev") or "")
    return {
        "pk": str(row.get("id")),
        "home": name(home),
        "away": name(away),
        "final_home": fh,
        "final_away": fa,
        "last_period_type": str((row.get("gameOutcome") or {}).get("lastPeriodType") or ""),
        "start_utc": str(row.get("startTimeUTC") or ""),
        "goals": goals,
    }


def score_at(goals: Sequence[Sequence[Any]], period: int, seconds_remaining: int) -> tuple[int, int]:
    """(home, away) on the board at `period` with `seconds_remaining` on its clock.

    A goal counts if it was scored in an earlier period, or in this period strictly before the cutoff's elapsed
    time. A goal AT the cutoff second is not on the board yet (ambiguous to the second; counted as after)."""
    elapsed = PERIOD_SECONDS - int(seconds_remaining)
    home = away = 0
    for g_period, g_elapsed, h_after, a_after, _ptype in goals:
        if g_period < period or (g_period == period and g_elapsed < elapsed):
            home, away = int(h_after), int(a_after)
    return home, away


def stable_seed(pk: str, cutoff_index: int) -> int:
    """Production seeds from `abs(hash(pk))`, which PYTHONHASHSEED makes per-process. A grade must be
    reproducible, so this is a fixed function of the game and the cutoff (the distribution is the same)."""
    return (int(pk) * 7 + cutoff_index * 100_003) % 1_000_003


# ---------------------------------------------------------------------------
# replay (runs the SHIPPED producer)
# ---------------------------------------------------------------------------

def replay_game(features: Any, game: Mapping[str, Any], *, sims: int = DEFAULT_SIMS,
                resim: Any = None) -> list[dict[str, Any]]:
    """One row per cutoff: the producer's histogram at the rebuilt state, beside the official final."""
    from syndicate.features.nhl import live_resim as LR

    resim = resim or LR.resim_live_game
    rows = []
    for idx, (period, remaining, label) in enumerate(CUTOFFS):
        h, a = score_at(game["goals"], period, remaining)
        state = LR.NhlLiveGameState(
            game_pk=str(game["pk"]), home_name=str(game["home"]), away_name=str(game["away"]),
            home_score=h, away_score=a, period=period, clock_seconds=remaining, as_of="replay")
        result = resim(features, state, sims=sims, base_seed=stable_seed(str(game["pk"]), idx))
        if isinstance(result, LR.NhlResimRefusal):
            rows.append({"pk": game["pk"], "cutoff": label, "refused": result.reason})
            continue
        rows.append({
            "pk": game["pk"], "cutoff": label, "period": period, "remaining": remaining,
            "home_score": h, "away_score": a,
            "final_margin": int(game["final_home"]) - int(game["final_away"]),
            "last_period_type": game["last_period_type"],
            "sims_run": result["sims_run"],
            "home_win_prob": result["home_win_prob"],
            "margin_mean": result["home_margin_mean"],
            "hist": result["margin_dist"],
        })
    return rows


def replay_date(args_tuple: tuple) -> dict[str, Any]:
    """Pool worker: every completed game on one date. Returns rows + per-date accounting."""
    date, source_root, cache_dir, sims = args_tuple
    from syndicate.features.nhl.sim_engine.hockeysim.features.loaders import build_slate_features

    out: dict[str, Any] = {"date": date, "rows": [], "games_completed": 0, "games_no_features": [],
                           "games_dropped": 0, "preseason": 0, "elapsed_s": 0.0}
    started = time.monotonic()
    raw = fetch_score_day(date, Path(cache_dir) if cache_dir else None)
    games = []
    for row in raw:
        if str(row.get("gameState") or "").upper() in {"OFF", "FINAL"} and int(row.get("gameType") or 0) == 1:
            out["preseason"] += 1
        g = completed_game(row)
        if g is None:
            if (str(row.get("gameState") or "").upper() in {"OFF", "FINAL"}
                    and int(row.get("gameType") or 0) == REGULAR_SEASON_GAME_TYPE):
                out["games_dropped"] += 1
            continue
        games.append(g)
    out["games_completed"] = len(games)
    if not games:
        return out
    feats = build_slate_features(date, root=Path(source_root) if source_root else None)
    by_pk = {str(getattr(f, "game_pk", "")).strip(): f for f in feats}
    for g in games:
        f = by_pk.get(str(g["pk"]))
        if f is None:
            out["games_no_features"].append(g["pk"])
            continue
        for r in replay_game(f, g, sims=sims):
            r["date"] = date
            out["rows"].append(r)
    out["elapsed_s"] = round(time.monotonic() - started, 1)
    return out


# ---------------------------------------------------------------------------
# grading (pure)
# ---------------------------------------------------------------------------

def hist_ints(hist: Mapping[Any, Any]) -> dict[int, int]:
    return {int(k): int(v) for k, v in hist.items()}


def p_cover(hist: Mapping[int, int], line: float, *, smoothed: bool = True) -> float:
    """P(home margin > line). Smoothed = Agresti-Coull, `live_display_block`'s number."""
    n = sum(hist.values())
    c = sum(v for k, v in hist.items() if k > line)
    return (c + 2) / (n + 4) if smoothed else c / n


def bucket_of(p: float) -> int:
    return min(int(p * 10), 9)


def calibration(cells: Sequence[tuple[str, float, int]]) -> list[dict[str, Any]]:
    """cells = (game, predicted, outcome 0/1). Per bucket: n, games, mean predicted, observed, gap."""
    out = []
    for i, (lo, hi) in enumerate(BUCKETS):
        sub = [c for c in cells if bucket_of(c[1]) == i]
        if not sub:
            out.append({"bucket": f"{lo:.1f}-{hi:.1f}", "n": 0})
            continue
        pred = sum(c[1] for c in sub) / len(sub)
        obs = sum(c[2] for c in sub) / len(sub)
        out.append({"bucket": f"{lo:.1f}-{hi:.1f}", "n": len(sub), "games": len({c[0] for c in sub}),
                    "pred": round(pred, 4), "obs": round(obs, 4), "gap": round(obs - pred, 4),
                    "powered": len(sub) >= MIN_BUCKET_N})
    return out


def worst_powered(cal: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    powered = [b for b in cal if b.get("powered")]
    return max(powered, key=lambda b: abs(b["gap"])) if powered else None


def brier(cells: Sequence[tuple[str, float, int]]) -> float:
    return sum((p - y) ** 2 for _g, p, y in cells) / len(cells)


def _pois(k: int, lam: float) -> float:
    return math.exp(-lam) * lam ** k / math.factorial(k) if k >= 0 else 0.0


def skellam_cover(cur_margin: int, seconds_left_reg: int, lam_home: float, lam_away: float,
                  home_ot_share: float, line: float, kmax: int = 20) -> float:
    """Skill-free baseline: P(final margin > line) with rest-of-regulation goals ~ Poisson at per-second rates."""
    a, b = lam_home * seconds_left_reg, lam_away * seconds_left_reg
    ph = [_pois(k, a) for k in range(kmax)]
    pa = [_pois(k, b) for k in range(kmax)]
    p = 0.0
    for x in range(kmax):
        for y in range(kmax):
            w = ph[x] * pa[y]
            m = cur_margin + x - y
            if m == 0:   # regulation tie: OT/SO, winner credited one goal
                p += w * (home_ot_share * (1 > line) + (1 - home_ot_share) * (-1 > line))
            else:
                p += w * (m > line)
    return p


def regulation_rates(games: Iterable[Mapping[str, Any]]) -> tuple[float, float, float]:
    """(home goals/sec, away goals/sec, home share of OT/SO wins) over the games' REGULATION."""
    hg = ag = n = ot = ot_home = 0
    for g in games:
        n += 1
        reg = [x for x in g["goals"] if x[0] <= REGULATION_PERIODS]
        h, a = (reg[-1][2], reg[-1][3]) if reg else (0, 0)
        hg += h
        ag += a
        if g["last_period_type"] in ("OT", "SO"):
            ot += 1
            ot_home += int(g["final_home"] > g["final_away"])
    secs = n * REGULATION_PERIODS * PERIOD_SECONDS
    return hg / secs, ag / secs, (ot_home / ot if ot else 0.5)


def width_stats(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Model spread vs realised: RMS(final - model mean) / sqrt(mean model variance); central-80% coverage."""
    if not rows:
        return {"n": 0}
    resid2 = var = inside = 0.0
    for r in rows:
        h = hist_ints(r["hist"])
        n = sum(h.values())
        mean = sum(k * v for k, v in h.items()) / n
        var += sum(v * (k - mean) ** 2 for k, v in h.items()) / n
        resid2 += (r["final_margin"] - mean) ** 2
        # central 80%: the smallest set of margins from the 10th to the 90th percentile of the histogram
        cum, lo, hi = 0, None, None
        for k in sorted(h):
            cum += h[k]
            if lo is None and cum / n > 0.10:
                lo = k
            if hi is None and cum / n >= 0.90:
                hi = k
        inside += int(lo <= r["final_margin"] <= hi)
    model_sd = math.sqrt(var / len(rows))
    actual = math.sqrt(resid2 / len(rows))
    return {"n": len(rows), "model_sd": round(model_sd, 3), "actual_rmse": round(actual, 3),
            "ratio_actual_over_model": round(actual / model_sd, 3) if model_sd else None,
            "central80_coverage": round(inside / len(rows), 3)}


def game_bootstrap(games: Sequence[str], stat, *, reps: int = BOOTSTRAP, seed: int = 7) -> tuple[float, float]:
    """95% interval of `stat(sample_of_games)` resampling GAMES with replacement."""
    rng = random.Random(seed)
    vals = []
    for _ in range(reps):
        sample = [games[rng.randrange(len(games))] for _ in games]
        v = stat(sample)
        if v is not None:
            vals.append(v)
    vals.sort()
    if not vals:
        return (float("nan"), float("nan"))
    return (vals[int(0.025 * len(vals))], vals[min(len(vals) - 1, int(0.975 * len(vals)))])


def grade(rows: Sequence[Mapping[str, Any]], games_meta: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    scored = [r for r in rows if "hist" in r]
    lam_h, lam_a, ot_home = regulation_rates(games_meta)
    report: dict[str, Any] = {
        "rows_scored": len(scored),
        "rows_refused": sum(1 for r in rows if "refused" in r),
        "refusals": _count(r.get("refused") for r in rows if "refused" in r),
        "games": len({r["pk"] for r in scored}),
        "dates": len({r.get("date") for r in scored}),
        "baseline_rates": {"home_goals_per_60": round(lam_h * 3600, 3), "away_goals_per_60": round(lam_a * 3600, 3),
                           "home_ot_so_share": round(ot_home, 3)},
        "families": {},
        "width_by_cutoff": {},
    }
    by_pk: dict[str, list] = {}
    for r in scored:
        by_pk.setdefault(r["pk"], []).append(r)
    for fam, lines in (("puck_line_1_5", PRIMARY_LINES), ("alt_2_5", ALT_LINES)):
        cells, base_cells = [], []
        for r in scored:
            h = hist_ints(r["hist"])
            left = (REGULATION_PERIODS - r["period"]) * PERIOD_SECONDS + r["remaining"]
            cur = r["home_score"] - r["away_score"]
            for line in lines:
                y = int(r["final_margin"] > line)
                cells.append((r["pk"], p_cover(h, line), y))
                base_cells.append((r["pk"], skellam_cover(cur, left, lam_h, lam_a, ot_home, line), y))
        cal = calibration(cells)
        worst = worst_powered(cal)
        games = sorted({c[0] for c in cells})
        cells_by_game: dict[str, list] = {}
        base_by_game: dict[str, list] = {}
        for c, b in zip(cells, base_cells):
            cells_by_game.setdefault(c[0], []).append(c)
            base_by_game.setdefault(b[0], []).append(b)

        def _brier_diff(sample):
            m = [c for g in sample for c in cells_by_game[g]]
            bb = [c for g in sample for c in base_by_game[g]]
            return brier(m) - brier(bb)

        def _worst_gap(sample):
            w = worst_powered(calibration([c for g in sample for c in cells_by_game[g]]))
            return abs(w["gap"]) if w else None

        report["families"][fam] = {
            "cells": len(cells),
            "calibration": cal,
            "worst_powered": worst,
            "worst_powered_abs_gap_ci95": [round(x, 4) for x in game_bootstrap(games, _worst_gap)],
            "verdict": ("NO_POWERED_BUCKET" if worst is None else
                        ("PASS_UPPER_BOUND" if abs(worst["gap"]) <= PASS_BAR else "FAIL")),
            "brier_model": round(brier(cells), 5),
            "brier_skellam_baseline": round(brier(base_cells), 5),
            "brier_model_minus_baseline_ci95": [round(x, 5) for x in game_bootstrap(games, _brier_diff)],
            "by_cutoff": {},
        }
        for _p, _r, label in CUTOFFS:
            sub_rows = [r for r in scored if r["cutoff"] == label]
            sub = [c for r in sub_rows for c in [(r["pk"], p_cover(hist_ints(r["hist"]), ln),
                                                   int(r["final_margin"] > ln)) for ln in lines]]
            sub_b = [(r["pk"], skellam_cover(r["home_score"] - r["away_score"],
                                             (REGULATION_PERIODS - r["period"]) * PERIOD_SECONDS + r["remaining"],
                                             lam_h, lam_a, ot_home, ln), int(r["final_margin"] > ln))
                     for r in sub_rows for ln in lines]
            if not sub:
                continue
            w = worst_powered(calibration(sub))
            report["families"][fam]["by_cutoff"][label] = {
                "cells": len(sub), "brier_model": round(brier(sub), 5), "brier_baseline": round(brier(sub_b), 5),
                "worst_powered": w,
            }
    for _p, _r, label in CUTOFFS:
        report["width_by_cutoff"][label] = width_stats([r for r in scored if r["cutoff"] == label])
    pk_list = sorted(by_pk)

    def _ratio(sample):
        rs = [r for g in sample for r in by_pk[g] if r["cutoff"] != "P3 05:00"]
        w = width_stats(rs)
        return w.get("ratio_actual_over_model")

    report["width_ratio_all_but_last_cutoff_ci95"] = [round(x, 3) for x in game_bootstrap(pk_list, _ratio, reps=300)]
    return report


def _count(values: Iterable[Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for v in values:
        out[str(v)] = out.get(str(v), 0) + 1
    return out


# ---------------------------------------------------------------------------
# provenance
# ---------------------------------------------------------------------------

SEASON_FILES = ("team_rates", "player_rates", "team_xg", "team_elo", "team_special_teams")


def provenance(source_root: Path | None, season: str, first_date: str, last_date: str) -> dict[str, Any]:
    out: dict[str, Any] = {"season_files": {}, "verdict": "UNKNOWN"}
    if source_root is None:
        return out
    proc = source_root / "data" / "processed"
    stamps = []
    for name in SEASON_FILES:
        p = proc / f"{name}_{season}.csv"
        if p.exists():
            mt = _dt.datetime.fromtimestamp(p.stat().st_mtime, _dt.timezone.utc)
            out["season_files"][p.name] = mt.strftime("%Y-%m-%dT%H:%MZ")
            stamps.append(mt.date().isoformat())
        else:
            out["season_files"][p.name] = None
    if stamps and min(stamps) > last_date:
        out["verdict"] = (f"LEAKY: every season rate file was last written {min(stamps)}..{max(stamps)}, after the "
                          f"last graded date {last_date}; graded games {first_date}..{last_date} ran on rates that "
                          "contain them. A PASS is an upper bound; only a FAIL is decisive.")
    elif stamps:
        out["verdict"] = "MIXED: some season rate files predate the last graded date; still not point-in-time."
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _dates(start: str, end: str) -> list[str]:
    d0, d1 = _dt.date.fromisoformat(start), _dt.date.fromisoformat(end)
    return [(d0 + _dt.timedelta(days=i)).isoformat() for i in range((d1 - d0).days + 1)]


def _text(report: Mapping[str, Any]) -> str:
    lines = []
    p = report.get("provenance") or {}
    lines.append(f"PROVENANCE: {p.get('verdict')}")
    for k, v in (p.get("season_files") or {}).items():
        lines.append(f"  {k}: {v}")
    g = report["grade"]
    lines.append(f"sample: {g['games']} games on {g['dates']} dates, {g['rows_scored']} cutoff rows scored, "
                 f"{g['rows_refused']} refused {g['refusals']}")
    lines.append(f"baseline rates: {g['baseline_rates']}")
    for fam, f in g["families"].items():
        w = f["worst_powered"]
        lines.append(f"\n[{fam}] verdict={f['verdict']} cells={f['cells']} worst powered bucket="
                     f"{(w or {}).get('bucket')} n={(w or {}).get('n')} gap={(w or {}).get('gap')} "
                     f"|gap| ci95={f['worst_powered_abs_gap_ci95']} (bar {PASS_BAR})")
        lines.append(f"  Brier model {f['brier_model']} vs skill-free baseline {f['brier_skellam_baseline']}; "
                     f"model - baseline ci95 {f['brier_model_minus_baseline_ci95']}")
        for b in f["calibration"]:
            if b["n"]:
                lines.append(f"    {b['bucket']} n={b['n']:5d} games={b['games']:4d} pred={b['pred']:.3f} "
                             f"obs={b['obs']:.3f} gap={b['gap']:+.3f}{'' if b['powered'] else '  (unpowered)'}")
        for label, c in f["by_cutoff"].items():
            w = c["worst_powered"] or {}
            lines.append(f"    {label}: cells={c['cells']} Brier {c['brier_model']} vs base {c['brier_baseline']}; "
                         f"worst powered {w.get('bucket')} n={w.get('n')} gap={w.get('gap')}")
    lines.append("\nWIDTH (final margin): model sd vs realised RMSE about the model mean; central-80% coverage")
    for label, w in g["width_by_cutoff"].items():
        lines.append(f"  {label}: {w}")
    lines.append(f"  realised/model ratio (all but P3 05:00) ci95: {g['width_ratio_all_but_last_cutoff_ci95']}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--start", default="2026-10-01")
    ap.add_argument("--end", required=True)
    ap.add_argument("--source-root", default=None, help="the producer's nhl_source root (fleet: "
                    "~/syndicate-prod/data/nhl_source)")
    ap.add_argument("--season", default="2026-2027")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--sims", type=int, default=DEFAULT_SIMS)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--grade-only", action="store_true")
    args = ap.parse_args(argv)

    out_dir = Path(os.path.expanduser(args.out_dir))
    out_dir.mkdir(parents=True, exist_ok=True)
    cache = out_dir / "score_cache"
    rows_path = out_dir / "rows.jsonl"
    root = Path(os.path.expanduser(args.source_root)) if args.source_root else None
    dates = _dates(args.start, args.end)

    if not args.grade_only:
        done = set()
        if rows_path.exists():
            for line in rows_path.read_text(encoding="utf-8").splitlines():
                done.add(json.loads(line).get("date"))
        todo = [d for d in dates if d not in done]
        accounting = []
        tasks = [(d, str(root) if root else None, str(cache), args.sims) for d in todo]
        if args.workers > 1:
            import multiprocessing as mp
            with mp.get_context("fork" if hasattr(os, "fork") else "spawn").Pool(args.workers) as pool:
                results = pool.imap_unordered(replay_date, tasks)
                for res in results:
                    _append(rows_path, res, accounting)
        else:
            for t in tasks:
                _append(rows_path, replay_date(t), accounting)
        (out_dir / "accounting.json").write_text(json.dumps(accounting, indent=1), encoding="utf-8")

    rows = [json.loads(l) for l in rows_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    rows = [r for r in rows if args.start <= str(r.get("date")) <= args.end and "pk" in r]
    meta = []
    for d in sorted({r["date"] for r in rows}):
        for raw in fetch_score_day(d, cache):
            g = completed_game(raw)
            if g is not None:
                meta.append(g)
    graded_dates = sorted({r["date"] for r in rows})
    report = {
        "provenance": provenance(root, args.season, graded_dates[0] if graded_dates else args.start,
                                 graded_dates[-1] if graded_dates else args.end),
        "grade": grade(rows, meta),
        "sims": args.sims,
        "range": [args.start, args.end],
    }
    (out_dir / "report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    text = _text(report)
    (out_dir / "report.txt").write_text(text, encoding="utf-8")
    print(text, flush=True)
    return 0


def _append(rows_path: Path, res: Mapping[str, Any], accounting: list) -> None:
    with rows_path.open("a", encoding="utf-8") as fh:
        for r in res["rows"]:
            fh.write(json.dumps(r) + "\n")
        if not res["rows"]:
            fh.write(json.dumps({"date": res["date"], "empty": True}) + "\n")
    acc = {k: v for k, v in res.items() if k != "rows"}
    accounting.append(acc)
    print(f"[nhl_puckline_grade] {res['date']} completed={res['games_completed']} rows={len(res['rows'])} "
          f"no_features={len(res['games_no_features'])} dropped={res['games_dropped']} "
          f"preseason={res['preseason']} elapsed={res['elapsed_s']}s", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
