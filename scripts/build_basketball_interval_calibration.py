"""Build the two INTERVAL calibration artifacts from ESPN play-by-play.

`#476` part 2. THE EARLIER CONCLUSION THIS OVERTURNS: `#476` shipped the
other two calibration artifacts and reported these two as
`actuals_unavailable` -- "Syndicate captures final box lines and quarter
totals, not intra-quarter segment scoring". **That was wrong.** The actuals
were already on disk the whole time.

`_espn_summary_local` (`basketball_props_smart_sim.py:392`) fetches ESPN's
summary endpoint for every game the boxscore bootstrap touches, and CACHES
it at `<processed_root>/_espn_cache/<league>/summary_<event_id>.json`. Those
payloads carry a `plays` array -- measured: 380 plays for a typical game,
113 of 114 locally-cached summaries usable -- and each play carries
`period.number`, `clock.displayValue`, and the RUNNING `homeScore`/
`awayScore`. Differencing the running score across plays yields exact
per-segment scoring. Verified on a real cached game: the 16 derived segments
sum to 179, and the final score from the last play is 179.

So no new capture pipeline was needed. The data was a cache read away, and
"we don't capture that" was a claim about the artifact NAMES rather than
about the DATA.

WHAT IT BUILDS:

  intervals_time_profile.json   {"segment_multipliers": [m1..m16], "clip": [lo,hi]}
      The SHAPE of scoring across the 16 regulation segments (4 per quarter,
      2.5 min each for WNBA's 10-minute quarters). `_apply_intervals_time_
      profile` multiplies each segment then RESCALES each sim row to keep its
      total unchanged -- so this is purely a redistribution, never a scoring-
      level change. Multipliers are therefore normalised to mean 1.0 by
      construction; anything else would be silently undone by the rescale.

  intervals_band_calibration.json  {"global": {"seg","cum"}, "per_segment": {...}}
      How much the sim's p10/p90 interval bands need widening (>1) or
      tightening (<1) to match observed dispersion. `_apply_band_scale`
      widens symmetrically about p50, and `_interval_scale` reads
      `per_segment[<1-based idx>][seg|cum]` first, falling back to
      `global[seg|cum]`.

HONEST LIMIT ON THE BAND CALIBRATION. A proper band fit compares the sim's
OWN predicted quantiles against actuals game-by-game. The production
`smart_sim_*.json` artifacts do not persist per-segment interval quantiles
(only whole-game `intervals`/`intervals_1m` blocks), so this derives the
scale from the ratio of OBSERVED cross-game dispersion to the dispersion a
Poisson-like scoring process implies -- a distributional argument, not a
paired residual fit. That is weaker evidence than `#476`'s total/player
calibrations, it is labelled as such in the artifact itself, and the default
`--bands` is OFF for exactly that reason.

Usage:
    py -3 scripts/build_basketball_interval_calibration.py --league wnba --dry-run
    py -3 scripts/build_basketball_interval_calibration.py --league wnba
    py -3 scripts/build_basketball_interval_calibration.py --league wnba --bands
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# The consumer's own geometry (`smart_sim.py:4129`): 4 segments per quarter,
# 4 regulation quarters. Segment length follows from the league's quarter.
_N_SEG_PER_QUARTER = 4
_N_REG_SEGMENTS = 4 * _N_SEG_PER_QUARTER
_QUARTER_SECONDS = {"wnba": 600.0, "nba": 720.0}


def _processed_root(league_code: str) -> Path:
    code = str(league_code or "").strip().lower()
    env_key = "WNBA_BETTING_DATA_ROOT" if code == "wnba" else "NBA_BETTING_DATA_ROOT"
    raw = str(os.environ.get(env_key) or "").strip()
    if raw:
        return Path(raw) / "processed"
    return REPO_ROOT / "data" / f"{code}_source" / "data" / "processed"


def _clock_to_seconds(value) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if ":" in text:
            mins, secs = text.split(":", 1)
            return float(int(mins) * 60 + float(secs))
        return float(text)
    except Exception:
        return None


def segment_points_for_game(payload: dict, *, quarter_seconds: float) -> list[float] | None:
    """Return per-segment TOTAL points (both teams) for the 16 regulation
    segments, or None when the payload cannot support it.

    Derived by differencing the RUNNING score across plays -- ESPN gives a
    cumulative homeScore/awayScore on every play, so the delta between
    consecutive plays is the points scored in that interval.
    """
    plays = payload.get("plays")
    if not isinstance(plays, list) or len(plays) < 50:
        return None

    seg_seconds = quarter_seconds / float(_N_SEG_PER_QUARTER)
    seg_points = [0.0] * _N_REG_SEGMENTS
    previous_total = 0
    saw_regulation = False

    for play in plays:
        if not isinstance(play, dict):
            continue
        period = (play.get("period") or {}).get("number")
        try:
            period_int = int(period)
        except Exception:
            continue
        remaining = _clock_to_seconds((play.get("clock") or {}).get("displayValue"))
        if remaining is None:
            continue
        try:
            total = int(play.get("homeScore") or 0) + int(play.get("awayScore") or 0)
        except Exception:
            continue

        delta = total - previous_total
        previous_total = total
        if period_int > 4:
            # Overtime: the profile describes REGULATION shape only. The points
            # are still consumed above (previous_total advances) so a later
            # regulation play can never be handed an inflated delta.
            continue
        saw_regulation = True
        if delta <= 0:
            continue
        elapsed_in_quarter = quarter_seconds - remaining
        seg_index = int(elapsed_in_quarter // seg_seconds)
        seg_index = max(0, min(_N_SEG_PER_QUARTER - 1, seg_index))
        seg_points[(period_int - 1) * _N_SEG_PER_QUARTER + seg_index] += float(delta)

    if not saw_regulation or sum(seg_points) <= 0:
        return None
    return seg_points


def collect_segment_actuals(*, league_code: str, processed_root: Path) -> tuple[list[list[float]], dict]:
    cache_dir = processed_root / "_espn_cache" / str(league_code).strip().lower()
    diag: dict = {"cache_dir": str(cache_dir)}
    if not cache_dir.is_dir():
        diag["reason"] = "espn_cache_missing"
        return [], diag

    summaries = sorted(cache_dir.glob("summary_*.json"))
    diag["summaries_found"] = len(summaries)
    quarter_seconds = _QUARTER_SECONDS.get(str(league_code).strip().lower(), 600.0)
    diag["quarter_seconds"] = quarter_seconds
    diag["segment_seconds"] = quarter_seconds / float(_N_SEG_PER_QUARTER)

    games: list[list[float]] = []
    skipped = 0
    for path in summaries:
        try:
            payload = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            skipped += 1
            continue
        seg = segment_points_for_game(payload, quarter_seconds=quarter_seconds)
        if seg is None:
            skipped += 1
            continue
        games.append(seg)

    diag["games_used"] = len(games)
    diag["games_skipped"] = skipped
    return games, diag


def build_time_profile(games: list[list[float]], *, min_games: int, clip: tuple[float, float]) -> dict:
    if len(games) < min_games:
        return {"ok": False, "reason": "insufficient_games", "games": len(games), "min_games": min_games}

    per_segment_means = []
    for index in range(_N_REG_SEGMENTS):
        values = [g[index] for g in games]
        per_segment_means.append(statistics.mean(values))

    grand_mean = statistics.mean(per_segment_means)
    if grand_mean <= 0:
        return {"ok": False, "reason": "degenerate_mean"}

    # Normalised to mean 1.0 BY CONSTRUCTION: the consumer rescales each sim
    # row back to its original total, so only the relative shape survives.
    # Emitting un-normalised values would imply a scoring-level change this
    # mechanism structurally cannot make.
    raw = [m / grand_mean for m in per_segment_means]
    lo, hi = clip
    multipliers = [max(lo, min(hi, value)) for value in raw]
    clamped = sum(1 for r, m in zip(raw, multipliers) if abs(r - m) > 1e-12)

    return {
        "ok": True,
        "segment_multipliers": multipliers,
        "clip": [lo, hi],
        "measured": {
            "games": len(games),
            "segments": _N_REG_SEGMENTS,
            "mean_points_per_segment": per_segment_means,
            "grand_mean_points_per_segment": grand_mean,
            "raw_multipliers": raw,
            "clamped_segments": clamped,
            "min_multiplier": min(multipliers),
            "max_multiplier": max(multipliers),
        },
    }


def build_band_calibration(games: list[list[float]], *, min_games: int, clip: tuple[float, float]) -> dict:
    """Derive band scales from observed vs Poisson-implied dispersion.

    WEAKER EVIDENCE THAN THE OTHER ARTIFACTS, deliberately labelled. See the
    module docstring: production sim artifacts do not persist per-segment
    interval quantiles, so this cannot be a paired residual fit.
    """
    if len(games) < min_games:
        return {"ok": False, "reason": "insufficient_games", "games": len(games), "min_games": min_games}

    lo, hi = clip
    per_segment: dict[str, dict[str, float]] = {}
    seg_ratios: list[float] = []
    cum_ratios: list[float] = []

    for index in range(_N_REG_SEGMENTS):
        values = [g[index] for g in games]
        mean = statistics.mean(values)
        if mean <= 0:
            continue
        observed_sd = statistics.pstdev(values) if len(values) > 1 else 0.0
        # Points arrive in 1/2/3-point increments; a pure-count Poisson
        # understates that, so the reference sd uses the mean POINTS with a
        # ~2.0 average points-per-scoring-event inflation. This is the
        # assumption doing the work, and it is why the result is labelled
        # weak rather than authoritative.
        implied_sd = math.sqrt(mean * 2.0)
        if implied_sd <= 0:
            continue
        ratio = observed_sd / implied_sd
        seg_ratios.append(ratio)

        cumulative = [sum(g[: index + 1]) for g in games]
        cum_mean = statistics.mean(cumulative)
        cum_observed_sd = statistics.pstdev(cumulative) if len(cumulative) > 1 else 0.0
        cum_implied_sd = math.sqrt(max(1e-9, cum_mean * 2.0))
        cum_ratio = cum_observed_sd / cum_implied_sd if cum_implied_sd > 0 else 1.0
        cum_ratios.append(cum_ratio)

        per_segment[str(index + 1)] = {
            "seg": max(lo, min(hi, ratio)),
            "cum": max(lo, min(hi, cum_ratio)),
        }

    if not per_segment:
        return {"ok": False, "reason": "no_usable_segments"}

    global_seg = max(lo, min(hi, statistics.mean(seg_ratios))) if seg_ratios else 1.0
    global_cum = max(lo, min(hi, statistics.mean(cum_ratios))) if cum_ratios else 1.0

    return {
        "ok": True,
        "global": {"seg": global_seg, "cum": global_cum},
        "per_segment": per_segment,
        "evidence_strength": "weak",
        "evidence_note": (
            "Derived from observed vs Poisson-implied dispersion, NOT a paired "
            "residual fit against the sim's own predicted quantiles -- production "
            "smart_sim artifacts do not persist per-segment interval quantiles. "
            "Treat as a starting point to be replaced once they do."
        ),
        "measured": {
            "games": len(games),
            "segments_fitted": len(per_segment),
            "mean_seg_ratio": statistics.mean(seg_ratios) if seg_ratios else None,
            "mean_cum_ratio": statistics.mean(cum_ratios) if cum_ratios else None,
            "clip": [lo, hi],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--league", default="wnba", choices=("wnba", "nba"))
    parser.add_argument("--min-games", type=int, default=40)
    parser.add_argument("--profile-clip", type=float, nargs=2, default=(0.85, 1.15),
                        help="bounds for segment_multipliers")
    parser.add_argument("--band-clip", type=float, nargs=2, default=(0.80, 1.25),
                        help="bounds for band scales")
    parser.add_argument("--bands", action="store_true",
                        help="ALSO build intervals_band_calibration.json (weaker evidence, off by default)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    processed_root = _processed_root(args.league)
    games, diag = collect_segment_actuals(league_code=args.league, processed_root=processed_root)

    print(f"Segment actuals from ESPN play-by-play cache ({args.league.upper()})")
    print(f"  cache dir      : {diag.get('cache_dir')}")
    print(f"  summaries found: {diag.get('summaries_found', 0)}")
    print(f"  games usable   : {diag.get('games_used', 0)}  (skipped {diag.get('games_skipped', 0)})")
    print(f"  segmentation   : {_N_REG_SEGMENTS} segments, {diag.get('segment_seconds')}s each")

    profile = build_time_profile(games, min_games=int(args.min_games), clip=tuple(args.profile_clip))
    bands = build_band_calibration(games, min_games=int(args.min_games), clip=tuple(args.band_clip)) if args.bands else {
        "ok": False, "reason": "not_requested (pass --bands; weaker evidence, see module docstring)"
    }

    if args.json:
        print(json.dumps({"diag": diag, "time_profile": profile, "band_calibration": bands}, indent=2, default=str))
    else:
        print()
        if profile.get("ok"):
            m = profile["measured"]
            print("  BUILDABLE  intervals_time_profile.json")
            print(f"               games={m['games']}  clamped_segments={m['clamped_segments']}")
            print(f"               multiplier range {m['min_multiplier']:.4f} .. {m['max_multiplier']:.4f}")
            print("               mean points per segment (Q1..Q4, 4 each):")
            means = m["mean_points_per_segment"]
            for q in range(4):
                row = "  ".join(f"{means[q * 4 + s]:5.2f}" for s in range(4))
                print(f"                 Q{q + 1}: {row}")
        else:
            print(f"  NOT BUILT  intervals_time_profile.json  ({profile.get('reason')})")
        if bands.get("ok"):
            m = bands["measured"]
            print("  BUILDABLE  intervals_band_calibration.json  [evidence: WEAK]")
            print(f"               global seg={bands['global']['seg']:.4f}  cum={bands['global']['cum']:.4f}")
            print(f"               segments fitted={m['segments_fitted']}  games={m['games']}")
        else:
            print(f"  NOT BUILT  intervals_band_calibration.json  ({bands.get('reason')})")

    if not profile.get("ok") and not bands.get("ok"):
        return 2
    if args.dry_run:
        print("\n--dry-run: nothing written")
        return 0

    processed_root.mkdir(parents=True, exist_ok=True)
    written = 0
    if profile.get("ok"):
        (processed_root / "intervals_time_profile.json").write_text(json.dumps(profile, indent=2, default=str), encoding="utf-8")
        print(f"\nwrote {processed_root / 'intervals_time_profile.json'}")
        written += 1
    if bands.get("ok"):
        (processed_root / "intervals_band_calibration.json").write_text(json.dumps(bands, indent=2, default=str), encoding="utf-8")
        print(f"wrote {processed_root / 'intervals_band_calibration.json'}")
        written += 1
    return 0 if written else 2


if __name__ == "__main__":
    raise SystemExit(main())
