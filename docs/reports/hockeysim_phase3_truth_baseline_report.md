# hockeysim Phase 3 — NHL truth baseline

**What this is:** the first real-data truth baseline for the Syndicate-owned NHL engine, built from
actual NHL StatsWeb (`api-web.nhle.com/v1`) finished-game feeds. It replaces guesswork with measured
targets that the calibration lane scores the engine + projection profile against.

## Method

- Source: `/v1/gamecenter/{id}/landing` per finished game (score, SOG, per-period goals with
  strength / empty-net flags, OT/SO markers); game list from `/v1/score/{date}`.
- Loader: `historical_truth/nhl_statsweb_loader.py` — fetches + **caches every landing payload** to
  `data/nhl_source/data/truth/raw/` (gitignored, ~1.7 MB) so the baseline is reproducible offline.
- Aggregation: `historical_truth/snapshot_builder.py`.
- Rebuild (offline, from cache): `py -3 scripts/build_hockeysim_truth_baseline.py`
  Refresh (network): `... --refresh --from 2026-01-05 --to 2026-01-18`
- Derived snapshot (committed): `reports/hockeysim/truth_baseline_20252026.json`.

## Baseline (2025-26 regular season, 108 games, 2026-01-05 … 2026-01-18)

| metric | truth | note |
|---|---|---|
| goals / game | **6.45** | total, both teams |
| home goals / game | **3.54** | |
| away goals / game | **2.92** | home scores 54.8% of goals |
| shots / game | **56.1** | ~28 / team |
| shooting % | **11.5%** | goals / SOG (all situations) |
| period goal share | **P1 0.274 / P2 0.382 / P3 0.344** | regulation goals only |
| power-play goal share | **19.9%** | |
| empty-net goal share | **5.7%** | |
| home win % | **57.4%** | reg + OT + SO |
| OT rate | **24.1%** | |
| shootout rate | **5.6%** | |

## Calibration findings (truth vs. current defaults)

These are the deltas the Phase-3b evaluator + profile overrides will close. **No constants have been
changed yet** — this report records the gap; calibration is applied as audited
`NHL_PROJECTION_PROFILE` / `SimConfig` field overrides in the next step.

1. **Baseline goals slightly low.** Projection baseline `3.05 g/60/team` → 6.10 total vs **6.45**
   truth (−0.35). Bump the projection baseline (or the engine shot→goal conversion) ~+5.7%.
2. **Period shares miscalibrated.** Defaults `(0.31, 0.34, 0.35)` vs truth **(0.274, 0.382, 0.344)**
   — P1 is materially *lower* and P2 *higher* than assumed (the classic long-change second-period
   effect). Update `ProjectionProfile.period_shares`.
3. **Home-ice edge understated.** Truth home share **54.8%** of goals (3.54 / 2.92) vs the projection's
   `1.05 / 0.95` → 52.5%. Widen the home/away multiplier toward ~`1.06 / 0.92`, or validate against a
   larger sample first.
4. **Sane as-is:** PP share (~20%), empty-net (~5.7%), OT (~24%), shootout (~5.6%) all match NHL norms
   and the engine's special-teams / OT knobs — no change indicated.

## Caveats

- 108 games is a two-week window — good for pace/shape, thinner for tail rates (shootout 5.6%). Widen
  to a full season before freezing the profile.
- Shooting % and home/away goal counts include OT + shootout-decider goals (from the final score);
  period shares are regulation-only. This is intentional (period λ model regulation).
- Playoffs excluded (`game_type == 2` only) — playoff hockey is systematically tighter.

## Next (Phase 3b)

`calibration/` package: `benchmark_contracts` (targets + tolerances from
`to_calibration_snapshot()`), `evaluation_metrics` (extract the same metrics from a batch of engine
sim outputs), `simulator_evaluator` (0–1 accept score = `max(0, 1 − mean(norm abs error))`),
`calibration_report_generator`. Then apply the four findings above as profile overrides and re-score.
