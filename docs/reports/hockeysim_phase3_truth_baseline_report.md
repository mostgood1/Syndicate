# hockeysim Phase 3 — NHL truth baseline

**What this is:** the real-data truth baseline for the Syndicate-owned NHL engine, built from actual
NHL StatsWeb (`api-web.nhle.com/v1`) finished-game feeds. It replaces guesswork with measured
targets that the calibration lane (Phase 3b) scores the engine + projection profile against.

## Method

- Source: `/v1/gamecenter/{id}/landing` per finished game (score, SOG, per-period goals with
  strength / empty-net flags, OT/SO markers); game list from `/v1/score/{date}`.
- Loader: `historical_truth/nhl_statsweb_loader.py` — fetches + **caches every landing payload** to
  `data/nhl_source/data/truth/raw/` (gitignored, ~15 MB for a full season) so the baseline is
  reproducible offline.
- Aggregation: `historical_truth/snapshot_builder.py` (regular season only, `game_type == 2`).
- Rebuild (offline, from cache): `py -3 scripts/build_hockeysim_truth_baseline.py`
  Refresh (network): `... --refresh --from 2025-10-01 --to 2026-04-30`
- Derived snapshot (committed): `reports/hockeysim/truth_baseline_20252026.json`.

## Baseline — full 2025-26 regular season (1312 games, 2025-10-07 … 2026-04-16)

| metric | truth | note |
|---|---|---|
| goals / game | **6.25** | total, both teams |
| home goals / game | **3.19** | |
| away goals / game | **3.06** | home scores only **51.0%** of goals |
| shots / game | **55.7** | ~28 / team |
| shooting % | **11.2%** | goals / SOG (all situations) |
| period goal share | **P1 0.292 / P2 0.348 / P3 0.360** | regulation goals only; P3 highest |
| power-play goal share | **19.4%** | |
| empty-net goal share | **6.1%** | |
| home win % | **52.2%** | reg + OT + SO |
| OT rate | **24.9%** | |
| shootout rate | **9.1%** | |

## Why a full season mattered (the key lesson)

An initial **108-game** (two-week) sample was misleading on exactly the quantities being calibrated:

| metric | 108-game window | full season (1312) | error if frozen early |
|---|---|---|---|
| home goals/game | 3.54 | **3.19** | home ice overstated ~2.3x |
| away goals/game | 2.92 | **3.06** | |
| home goal share | 54.8% | **51.0%** | |
| home win % | 57.4% | **52.2%** | |
| shootout rate | 5.6% | **9.1%** | thin-tail underestimate |
| period-1 share | 0.274 | **0.292** | |

Calibrating on the two-week window would have set `home_ice ≈ 1.10` — nearly double the real edge.
The full-season sample brings it to `1.021`. **Real home-ice advantage in scoring is small (~51% of
goals);** the noisy short window inflated it. This is why the truth layer + a full-season sample come
*before* freezing any constant.

## Applied calibration (Phase 3b)

Overrides derived from this baseline and applied to `projection.NHL_PROJECTION_PROFILE` (see
`hockeysim_phase3b_calibration_report.md`): baseline `3.05 → 3.1269` g/60, home/away
`1.05/0.95 → 1.0209/0.9791`, period shares `(0.31,0.34,0.35) → (0.2924,0.3478,0.3598)`. Accept score
0.727 → **0.989** (full validation set) / **0.9999** (directly-tuned metrics). PP / empty-net / OT /
shootout are governed by the engine `SimConfig` and already match truth — no change indicated.

## Caveats

- Shooting % and home/away goal counts include OT + shootout-decider goals (from the final score);
  period shares are regulation-only (period λ model regulation).
- Playoffs excluded (`game_type == 2` only) — playoff hockey is systematically tighter.
- `home_win_pct` is emergent (a Poisson consequence of the calibrated goal means), not a directly
  tuned lever; it lands at 0.518 vs 0.522 truth, close but not forced.
