"""Build the two INTERVAL calibration artifacts, as genuine PAIRED fits.

`#476` part 3. THIS SUPERSEDES PART 2, WHICH SHIPPED A REAL BUG.

TWO WRONG CLAIMS, BOTH RETRACTED HERE:

1. Part 1 said the actuals were `actuals_unavailable`. Wrong: ESPN's summary
   payload carries a `plays` array (~380/game) with `period.number`,
   `clock.displayValue` and the RUNNING `homeScore`/`awayScore`, and
   `_espn_summary_local` already CACHES it at
   `<processed_root>/_espn_cache/<league>/summary_<event_id>.json`.

2. Part 2 said the sim's own per-segment quantiles were not persisted, so
   only a weak dispersion argument was possible. **Also wrong.** Production
   `smart_sim_*.json` carries `intervals.segments[]`, each entry holding
   `q.{p10,p50,p90}` AND `cum_q.{p10,p50,p90}` -- exactly the predicted
   quantiles a proper paired fit needs. Part 2 also HARDCODED the segment
   geometry as four equal 150s buckets (600s quarter / 4), which is WRONG:
   production reports `segment_seconds: 180` with labels "Q1 12-9", so the
   real buckets are 180/180/180/60 and segment 4 covers only the final
   MINUTE of a WNBA quarter. Measured on a production artifact -- Q1 segment
   shares 0.277 / 0.274 / 0.287 / 0.162, nowhere near the 0.25 equal-split
   part 2 assumed. Multipliers fitted on equal buckets were therefore
   misaligned with the segments the consumer applies them to.

   (Root cause of the 180s itself: `smart_sim.py:4128` reads
   `LEAGUE.regulation_period_seconds` with a `or (12*60)` NBA fallback. The
   vendored WNBA league sets 600, so a 720 in production means production
   runs a build where that value is absent/zero. Worth its own look; this
   builder does not depend on the answer because it READS the geometry the
   sim actually used rather than assuming one.)

THE DESIGN RULE THAT FOLLOWS: never assume the geometry. Every fit here
buckets actuals using `intervals.segment_seconds` /
`intervals.segments_per_quarter` READ FROM THE SIM ARTIFACT ITSELF, so the
multipliers and band scales are always expressed in the same coordinates the
consumer will apply them in, whatever the engine is configured to use.

WHAT IT BUILDS, both as paired fits against real outcomes:

  intervals_time_profile.json   {"segment_multipliers": [...], "clip": [lo,hi]}
      Ratio of ACTUAL mean points per segment to the SIM's own predicted mean
      (`mu`) per segment, normalised to mean 1.0. `_apply_intervals_time_
      profile` rescales each sim row back to its original total, so only
      relative shape survives -- normalising is required, not cosmetic.

  intervals_band_calibration.json  {"global": {...}, "per_segment": {...}}
      COVERAGE-BASED, which is the honest way to fit an interval band: the
      sim publishes p10/p90, so a well-calibrated band should contain ~80% of
      actual outcomes. This measures realised coverage per segment and solves
      for the symmetric widening factor about p50 that would have produced
      80%. Coverage below target -> bands too narrow -> scale > 1. That is a
      real paired residual fit, not the dispersion proxy part 2 settled for.

Usage:
    py -3 scripts/build_basketball_interval_calibration.py --league wnba --dry-run
    py -3 scripts/build_basketball_interval_calibration.py --league wnba
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_SIM_NAME_RE = re.compile(r"smart_sim_(\d{4}-\d{2}-\d{2})_([A-Z0-9]+)_([A-Z0-9]+)\.json$")
_DEFAULT_BASE_URL = "https://syndicate-an21.onrender.com"
_TARGET_COVERAGE = 0.80  # p10..p90 by construction


def _admin_token() -> str:
    token = str(os.environ.get("ADMIN_TOKEN") or "").strip()
    if token:
        return token
    env_path = REPO_ROOT / ".env"
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("ADMIN_TOKEN"):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("ADMIN_TOKEN not found (env or .env)")


def _ops_export(base_url: str, token: str, *, path: str | None = None, pattern: str | None = None, names_only: bool = False) -> dict:
    params = {"admin_token": token}
    if path:
        params["path"] = path
    if pattern:
        params["pattern"] = pattern
    if names_only:
        params["names_only"] = "1"
    url = base_url.rstrip("/") + "/api/ops/artifacts/export?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=90) as response:
        return json.loads(response.read().decode("utf-8"))


def _processed_root(league_code: str) -> Path:
    code = str(league_code or "").strip().lower()
    env_key = "WNBA_BETTING_DATA_ROOT" if code == "wnba" else "NBA_BETTING_DATA_ROOT"
    raw = str(os.environ.get(env_key) or "").strip()
    if raw:
        return Path(raw) / "processed"
    return REPO_ROOT / "data" / f"{code}_source" / "data" / "processed"


def _fetch_espn_summary(*, event_id: str, league_code: str) -> dict | None:
    """Fetch one ESPN summary. Mirrors `_http_get_json_local`'s
    browser-shaped User-Agent, which `#469` measured as the difference
    between a real payload and a soft-blocked empty body from a datacenter IP.
    """
    sport_path = "sports/basketball/wnba" if str(league_code).lower() == "wnba" else "sports/basketball/nba"
    url = f"https://site.web.api.espn.com/apis/site/v2/{sport_path}/summary?event={event_id}"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            if response.status != 200:
                return None
            payload = json.loads(response.read().decode("utf-8"))
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


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


def segment_points_for_game(payload: dict, *, quarter_seconds: float, segment_seconds: float, segments_per_quarter: int) -> list[float] | None:
    """Per-segment TOTAL points for the regulation segments, bucketed with the
    geometry the SIM used (passed in, never assumed).

    Buckets can be unequal in wall-clock terms -- with 180s segments on a
    600s quarter the last bucket is only 60s -- and that is exactly why the
    geometry must come from the artifact.
    """
    plays = payload.get("plays")
    if not isinstance(plays, list) or len(plays) < 50:
        return None

    n_seg = 4 * int(segments_per_quarter)
    seg_points = [0.0] * n_seg
    previous_total = 0
    saw_regulation = False

    for play in plays:
        if not isinstance(play, dict):
            continue
        try:
            period_int = int((play.get("period") or {}).get("number"))
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
            # OT consumed (so previous_total stays honest) but not bucketed:
            # the profile describes REGULATION shape only.
            continue
        saw_regulation = True
        if delta <= 0:
            continue
        elapsed_in_quarter = quarter_seconds - remaining
        seg_index = int(elapsed_in_quarter // float(segment_seconds))
        seg_index = max(0, min(int(segments_per_quarter) - 1, seg_index))
        seg_points[(period_int - 1) * int(segments_per_quarter) + seg_index] += float(delta)

    if not saw_regulation or sum(seg_points) <= 0:
        return None
    return seg_points


def collect_paired(*, league_code: str, base_url: str, token: str, allow_fetch: bool = True) -> tuple[list[dict], dict]:
    """Pair each production sim's per-segment PREDICTIONS with PBP actuals."""
    import pandas as pd

    diag: dict = {}
    processed_root = _processed_root(league_code)
    cache_dir = processed_root / "_espn_cache" / str(league_code).strip().lower()
    diag["espn_cache_dir"] = str(cache_dir)

    schedule_path = REPO_ROOT / "vendor" / f"{league_code}_betting_repo" / "data" / "processed" / "schedule_2026.csv"
    sched = pd.read_csv(schedule_path, dtype=str) if schedule_path.is_file() else None
    if sched is None:
        diag["reason"] = "schedule_missing"
        return [], diag

    listing = _ops_export(base_url, token, pattern=f"{league_code}_source/data/processed/smart_sim_*.json", names_only=True)
    sim_paths = sorted(listing.get("artifacts", {}).keys())
    diag["sim_files_listed"] = len(sim_paths)

    paired: list[dict] = []
    no_cache = 0
    no_intervals = 0
    geometries: dict[tuple, int] = {}

    for rel in sim_paths:
        match = _SIM_NAME_RE.search(rel.replace("\\", "/"))
        if not match:
            continue
        date_str, home_tri, away_tri = match.group(1), match.group(2), match.group(3)

        cand = sched[(sched["home_tricode"] == home_tri) & (sched["away_tricode"] == away_tri)]
        event_id = None
        # `date_est` FIRST, deliberately: smart_sim filenames carry the SLATE
        # date (local), and `date_utc` is the next calendar day for any
        # evening tip -- measured, 3 of the first 4 files on 2026-06-01/02
        # matched on date_est and missed on date_utc. Matching date_utc first
        # silently produced ZERO pairs while every input was present.
        for col in ("date_est", "date_utc"):
            if col in cand.columns:
                hit = cand[cand[col] == date_str]
                if not hit.empty:
                    event_id = str(hit["game_id"].iloc[0])
                    break
        # No blind fallback to "first row for this matchup": two teams meet
        # several times a season, so that would pair a sim with the WRONG
        # game's actuals -- silently, and the fit would look fine.
        if event_id is None:
            continue
        if event_id is None:
            continue

        cache_path = cache_dir / f"summary_{event_id}.json"
        if not cache_path.is_file():
            # The local cache only holds what the bootstrap happened to fetch.
            # Measured: sim `intervals` blocks exist only from 2026-07-17
            # onward, while the local cache ended 2026-07-16 -- ZERO overlap,
            # so without this fetch the paired fit is structurally impossible
            # despite every input being obtainable. ESPN's summary endpoint is
            # the same one `_espn_summary_local` already uses.
            if not allow_fetch:
                no_cache += 1
                continue
            fetched = _fetch_espn_summary(event_id=event_id, league_code=league_code)
            if fetched is None:
                no_cache += 1
                continue
            try:
                cache_dir.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(json.dumps(fetched), encoding="utf-8")
            except Exception:
                pass
            diag["espn_fetched"] = int(diag.get("espn_fetched", 0)) + 1

        try:
            sim_payload_json = _ops_export(base_url, token, path=rel)
            if not sim_payload_json.get("count"):
                continue
            sim = json.loads(list(sim_payload_json["artifacts"].values())[0])
        except Exception:
            continue

        intervals = sim.get("intervals") if isinstance(sim.get("intervals"), dict) else None
        segments = (intervals or {}).get("segments")
        if not intervals or not isinstance(segments, list) or not segments:
            no_intervals += 1
            continue

        seg_seconds = float(intervals.get("segment_seconds") or 0.0)
        seg_per_q = int(intervals.get("segments_per_quarter") or 0)
        if seg_seconds <= 0 or seg_per_q <= 0:
            no_intervals += 1
            continue
        # Regulation quarter length is implied by the league, but the BUCKETING
        # is whatever the sim used -- record both so the mismatch is visible.
        quarter_seconds = 600.0 if str(league_code).lower() == "wnba" else 720.0
        geometries[(seg_seconds, seg_per_q)] = geometries.get((seg_seconds, seg_per_q), 0) + 1

        try:
            summary = json.loads(cache_path.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            continue
        actuals = segment_points_for_game(
            summary, quarter_seconds=quarter_seconds, segment_seconds=seg_seconds, segments_per_quarter=seg_per_q,
        )
        if actuals is None:
            continue

        n_reg = 4 * seg_per_q
        pred = []
        for entry in segments:
            try:
                idx = int(entry.get("idx"))
            except Exception:
                continue
            if idx < 1 or idx > n_reg:
                continue
            q = entry.get("q") or {}
            cum_q = entry.get("cum_q") or {}
            pred.append(
                {
                    "idx": idx,
                    "mu": float(entry.get("mu") or 0.0),
                    "p10": float(q.get("p10")) if q.get("p10") is not None else None,
                    "p50": float(q.get("p50")) if q.get("p50") is not None else None,
                    "p90": float(q.get("p90")) if q.get("p90") is not None else None,
                    "cum_p10": float(cum_q.get("p10")) if cum_q.get("p10") is not None else None,
                    "cum_p50": float(cum_q.get("p50")) if cum_q.get("p50") is not None else None,
                    "cum_p90": float(cum_q.get("p90")) if cum_q.get("p90") is not None else None,
                }
            )
        if len(pred) < n_reg:
            no_intervals += 1
            continue

        paired.append(
            {
                "date": date_str,
                "event_id": event_id,
                "segment_seconds": seg_seconds,
                "segments_per_quarter": seg_per_q,
                "actual_segments": actuals,
                "pred_segments": sorted(pred, key=lambda r: r["idx"]),
            }
        )

    diag["paired_games"] = len(paired)
    diag["skipped_no_espn_cache"] = no_cache
    diag["skipped_no_intervals"] = no_intervals
    diag["geometries_seen"] = {f"{int(k[0])}s x{k[1]}": v for k, v in geometries.items()}
    return paired, diag


def _coverage_scale(actuals: list[float], lows: list[float], mids: list[float], highs: list[float], *, clip: tuple[float, float]) -> tuple[float, float, float]:
    """Solve for the symmetric widening factor about p50 that would have
    produced ~80% coverage. Returns (scale, coverage_before, coverage_after)."""

    def coverage(scale: float) -> float:
        hits = 0
        for a, lo, mid, hi in zip(actuals, lows, mids, highs):
            low_edge = mid - scale * (mid - lo)
            high_edge = mid + scale * (hi - mid)
            if low_edge <= a <= high_edge:
                hits += 1
        return hits / len(actuals) if actuals else 0.0

    before = coverage(1.0)
    lo_s, hi_s = 0.25, 4.0
    for _ in range(40):
        mid_s = (lo_s + hi_s) / 2.0
        if coverage(mid_s) < _TARGET_COVERAGE:
            lo_s = mid_s
        else:
            hi_s = mid_s
    solved = (lo_s + hi_s) / 2.0
    after = coverage(solved)
    return max(clip[0], min(clip[1], solved)), before, after


def build_from_paired(paired: list[dict], *, min_games: int, profile_clip: tuple[float, float], band_clip: tuple[float, float]) -> tuple[dict, dict]:
    if len(paired) < min_games:
        reason = {"ok": False, "reason": "insufficient_games", "games": len(paired), "min_games": min_games}
        return reason, dict(reason)

    seg_per_q = paired[0]["segments_per_quarter"]
    n_reg = 4 * seg_per_q
    usable = [p for p in paired if p["segments_per_quarter"] == seg_per_q and len(p["actual_segments"]) == n_reg]

    actual_means, pred_means = [], []
    for index in range(n_reg):
        actual_means.append(statistics.mean([p["actual_segments"][index] for p in usable]))
        pred_means.append(statistics.mean([p["pred_segments"][index]["mu"] for p in usable]))

    ratios = [(a / m) if m > 0 else 1.0 for a, m in zip(actual_means, pred_means)]
    grand = statistics.mean(ratios)
    raw = [r / grand for r in ratios] if grand > 0 else [1.0] * n_reg
    lo, hi = profile_clip
    clamped_vals = [max(lo, min(hi, v)) for v in raw]
    # RE-NORMALISE AFTER CLAMPING. Clamping breaks the mean-1.0 property the
    # pre-clamp normalisation established -- measured: 6 of 16 segments hit the
    # bound and dragged the mean to 1.0378. The consumer rescales each sim row
    # back to its own total anyway, so a drifted mean is not a scoring bug, but
    # it makes the artifact misreport its own strength: a reader comparing
    # multipliers against 1.0 would misjudge every segment by ~4%.
    clamp_mean = statistics.mean(clamped_vals) if clamped_vals else 1.0
    multipliers = [v / clamp_mean for v in clamped_vals] if clamp_mean > 0 else clamped_vals

    profile = {
        "ok": True,
        "segment_multipliers": multipliers,
        "clip": [lo, hi],
        # A profile is only valid for the geometry it was FITTED against.
        # Stamped so a future reader (or a guard) can detect the mismatch
        # instead of silently applying multipliers to different-shaped
        # segments -- which is exactly the bug part 2 shipped.
        "fitted_segment_seconds": paired[0]["segment_seconds"],
        "fitted_segments_per_quarter": seg_per_q,
        "geometry_warning": (
            "Fitted against segment_seconds=%d with %d segments/quarter. The WNBA "
            "quarter is 600s, so 180s segments mean segment 4 spans only the final "
            "60s -- the sim over-predicts it ~2x (predicted share 0.183 vs actual "
            "0.120) because its bucketing assumes a 12-minute NBA quarter "
            "(smart_sim.py:4128's `or (12*60)` fallback). THIS PROFILE COMPENSATES "
            "FOR THAT, it does not fix it. If the engine's segment geometry is ever "
            "corrected, REBUILD this artifact -- it will otherwise be actively wrong."
            % (int(paired[0]["segment_seconds"]), seg_per_q)
        ),
        "measured": {
            "games": len(usable),
            "segments": n_reg,
            "segment_seconds": paired[0]["segment_seconds"],
            "segments_per_quarter": seg_per_q,
            "actual_mean_points_per_segment": actual_means,
            "sim_mean_points_per_segment": pred_means,
            "actual_over_sim_ratio": ratios,
            "clamped_segments": sum(1 for r, m in zip(raw, multipliers) if abs(r - m) > 1e-12),
            "fit": "paired: actual mean vs sim mu, per segment, normalised to mean 1.0",
        },
    }

    per_segment: dict[str, dict[str, float]] = {}
    seg_scales, cum_scales, seg_cov_before, cum_cov_before = [], [], [], []
    for index in range(n_reg):
        acts = [p["actual_segments"][index] for p in usable]
        preds = [p["pred_segments"][index] for p in usable]
        if any(x["p10"] is None or x["p50"] is None or x["p90"] is None for x in preds):
            continue
        s_scale, s_before, _ = _coverage_scale(
            acts, [x["p10"] for x in preds], [x["p50"] for x in preds], [x["p90"] for x in preds], clip=band_clip
        )
        cum_acts = [sum(p["actual_segments"][: index + 1]) for p in usable]
        if any(x["cum_p10"] is None or x["cum_p50"] is None or x["cum_p90"] is None for x in preds):
            c_scale, c_before = 1.0, None
        else:
            c_scale, c_before, _ = _coverage_scale(
                cum_acts, [x["cum_p10"] for x in preds], [x["cum_p50"] for x in preds], [x["cum_p90"] for x in preds], clip=band_clip
            )
        per_segment[str(index + 1)] = {"seg": s_scale, "cum": c_scale}
        seg_scales.append(s_scale)
        cum_scales.append(c_scale)
        seg_cov_before.append(s_before)
        if c_before is not None:
            cum_cov_before.append(c_before)

    if not per_segment:
        bands = {"ok": False, "reason": "no_segment_had_complete_quantiles"}
    else:
        bands = {
            "ok": True,
            "global": {
                "seg": max(band_clip[0], min(band_clip[1], statistics.mean(seg_scales))),
                "cum": max(band_clip[0], min(band_clip[1], statistics.mean(cum_scales))),
            },
            "per_segment": per_segment,
            "measured": {
                "games": len(usable),
                "segments_fitted": len(per_segment),
                "target_coverage": _TARGET_COVERAGE,
                "mean_seg_coverage_before": statistics.mean(seg_cov_before) if seg_cov_before else None,
                "mean_cum_coverage_before": statistics.mean(cum_cov_before) if cum_cov_before else None,
                "clip": list(band_clip),
                "fit": (
                    "paired coverage fit: realised fraction of actuals inside the sim's own "
                    "p10..p90, solved for the symmetric widening about p50 that yields 80%"
                ),
            },
        }
    return profile, bands


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--league", default="wnba", choices=("wnba", "nba"))
    parser.add_argument("--base-url", default=_DEFAULT_BASE_URL)
    parser.add_argument("--min-games", type=int, default=30)
    parser.add_argument("--profile-clip", type=float, nargs=2, default=(0.85, 1.15))
    parser.add_argument("--band-clip", type=float, nargs=2, default=(0.80, 1.60))
    parser.add_argument("--no-fetch", action="store_true",
                        help="do not fetch missing ESPN summaries (local cache only)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    token = _admin_token()
    print(f"Pairing production sim per-segment quantiles with ESPN PBP actuals ({args.league.upper()})...")
    paired, diag = collect_paired(league_code=args.league, base_url=args.base_url, token=token, allow_fetch=not args.no_fetch)
    print(f"  sim files listed     : {diag.get('sim_files_listed', 0)}")
    print(f"  paired games         : {diag.get('paired_games', 0)}")
    print(f"  skipped (no PBP cache): {diag.get('skipped_no_espn_cache', 0)}")
    print(f"  skipped (no intervals): {diag.get('skipped_no_intervals', 0)}")
    print(f"  geometries seen      : {diag.get('geometries_seen')}")

    profile, bands = build_from_paired(
        paired, min_games=int(args.min_games), profile_clip=tuple(args.profile_clip), band_clip=tuple(args.band_clip)
    )

    if args.json:
        print(json.dumps({"diag": diag, "time_profile": profile, "band_calibration": bands}, indent=2, default=str))
    else:
        print()
        if profile.get("ok"):
            m = profile["measured"]
            print("  BUILDABLE  intervals_time_profile.json   [paired fit]")
            print(f"               games={m['games']}  geometry={int(m['segment_seconds'])}s x{m['segments_per_quarter']}/quarter")
            print(f"               clamped={m['clamped_segments']}  range {min(profile['segment_multipliers']):.4f}..{max(profile['segment_multipliers']):.4f}")
            print("               actual vs sim mean pts per segment:")
            for q in range(4):
                a = "  ".join(f"{m['actual_mean_points_per_segment'][q * m['segments_per_quarter'] + s]:5.2f}" for s in range(m["segments_per_quarter"]))
                p = "  ".join(f"{m['sim_mean_points_per_segment'][q * m['segments_per_quarter'] + s]:5.2f}" for s in range(m["segments_per_quarter"]))
                print(f"                 Q{q + 1} actual: {a}   sim: {p}")
        else:
            print(f"  NOT BUILT  intervals_time_profile.json  ({profile.get('reason')})")
        if bands.get("ok"):
            m = bands["measured"]
            cov = m.get("mean_seg_coverage_before")
            print("  BUILDABLE  intervals_band_calibration.json  [paired coverage fit]")
            print(f"               realised seg coverage of p10..p90: {cov:.3f} (target {m['target_coverage']:.2f})")
            print(f"               -> global seg scale {bands['global']['seg']:.4f}  cum scale {bands['global']['cum']:.4f}")
            print(f"               segments fitted={m['segments_fitted']}  games={m['games']}")
        else:
            print(f"  NOT BUILT  intervals_band_calibration.json  ({bands.get('reason')})")

    if not profile.get("ok") and not bands.get("ok"):
        return 2
    if args.dry_run:
        print("\n--dry-run: nothing written")
        return 0

    processed_root = _processed_root(args.league)
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
