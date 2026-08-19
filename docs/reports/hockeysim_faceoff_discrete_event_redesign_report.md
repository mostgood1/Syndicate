# hockeysim discrete-event faceoff redesign

Closes the item `hockeysim_faceoff_segment_validation_report.md` explicitly flagged as the
properly-faithful fix, not a calibration pass: "directly recalibrating `faceoff_alpha` to match a
~2-4x per-draw shot-rate ratio would be a category error... a more faithful model would need to
represent faceoffs as discrete, time-limited events with their own decay profile."

## The problem, restated precisely

`_faceoff_multipliers` (`engine.py`) applies ONE constant multiplier pair across an entire
engine segment (~40-45s, `target_seg`), derived from a DIFFERENCE in season-long (or per-team
zone-index) win rate. The segment-validation report measured the REAL effect: a sharp shot-rate
spike in the first ~10-15 seconds after a specific draw, decaying smoothly toward baseline by
60-90s. A single constant cannot represent a spike-then-decay shape — recalibrating the constant's
SIZE would still leave its SHAPE wrong.

## Extending the measurement to the engine's actual segment length

The validation report measured cumulative windows up to 30s. `scripts/build_nhl_faceoff_decay_curve.py`
extends this to real MARGINAL (non-overlapping) buckets covering the engine's full ~40-45s segment
length and beyond, in one pass over the same 1,312-game `playbyplay` cache (58,762 real EV
faceoffs):

| bucket (s since draw) | winner shots/100s | other shots/100s | ratio |
|---|---|---|---|
| (0, 5] | 1.1641 | 0.1628 | 7.15x |
| (5, 10] | 0.9305 | 0.3999 | 2.33x |
| (10, 15] | 0.9778 | 0.5994 | 1.63x |
| (15, 20] | 0.9053 | 0.7391 | 1.23x |
| (20, 30] | 0.8289 | 0.7582 | 1.09x |
| (30, 45] | 0.7228 | 0.7414 | 0.98x |
| (45, 60] | 0.6735 | 0.6636 | 1.01x |
| (60, 90] | 0.6569 | 0.6557 | 1.00x |

The effect is fully decayed by 60-90s (winner and other rates within 0.2% of each other) — the
curve is treated as flat (no effect) beyond that, backed by data rather than extrapolated.

## The model

`historical_truth/faceoff_decay_model.py::segment_average_multipliers(seg_len)` — normalizes each
bucket to `winner_mult`/`other_mult` where `(winner_mult + other_mult) / 2 == 1.0` by construction
(the same design invariant every per-team index this session built already uses), then
time-weight-averages the curve over `[0, seg_len]`. A 5s segment reproduces the first bucket
exactly (1.75x/0.25x); a full-period-length segment converges to ~1.0/1.0.

`engine.py` (§2r, `faceoff_discrete_event_model`, default `True`): for each EV segment, resolves
each side's effective faceoff percentage using the EXISTING OZ→EV→blend fallback chain (unchanged
from §2m/§2n), normalizes to a win PROBABILITY (`p_home = fo_h / (fo_h + fo_a)`, clamped to
`[0.05, 0.95]`), simulates a discrete Bernoulli draw for who wins that segment's (assumed single)
faceoff, then applies the decay curve's segment-length-averaged multipliers to the winner and
loser. `False` restores the exact pre-redesign diff-based mechanism, for rollback/A-B comparison.
The separately-composed DZ layer (§2o) is unchanged — its own segment-level validation is a
distinct, not-yet-done follow-up.

## What this does NOT model, stated plainly

Not every ~40-45s engine segment corresponds to a real faceoff at its exact start — some real
shifts begin on the fly, off a line change, with no stoppage. This treats every EV segment as if
one occurs. Real per-game EV faceoff counts (58,762 / 1,312 ≈ 44.8/game) are the same order of
magnitude as this engine's own EV segment count per game, so the approximation is directionally
reasonable, not wildly off — but it is an approximation, not a literal reconstruction of a real
game clock.

## Verified

- **17 unit tests** on the pure decay-curve function: exact bucket reproduction at short segment
  lengths, monotonic decay, convergence at long lengths, the mean-1.0 invariant across 9 segment
  lengths, and invalid-input handling.
- **2 new reachability tests**: `faceoff_discrete_event_model=True` vs `False` produce measurably
  different output holding everything else identical (proves the flag gates something); a team
  with a real `faceoff_oz_index` edge still out-shoots a weaker one on average UNDER the new
  default mechanism specifically (proves the redesign preserved the underlying per-team signal,
  not just changed the functional form arbitrarily).
- **League-wide aggregate barely moved**: 992-pairing round-robin, legacy mechanism 61.938 avg
  total shots/game vs discrete-event 61.864 — a −0.12% delta, well within noise, despite the
  functional form being fundamentally different.
- **390 hockeysim/nhl tests pass** with the new mechanism as the default — no existing test
  (including exact-seed determinism tests) broke, despite the new mechanism consuming an additional
  RNG draw per EV segment and shifting the downstream random stream.

## What remains genuinely open

- **DZ's own segment-level effect** was never separately measured — its mechanism (§2o) still uses
  the legacy diff-based math, composed on top of whichever EV/OZ mechanism (legacy or discrete) is
  active. A DZ-specific post-faceoff shot study (winner's shots vs. the team that took the DZ draw)
  would be the natural next measurement.
- **The "one faceoff per segment" approximation** is not a literal game-clock reconstruction — a
  genuinely faithful model would need real per-second time-stepping with actual faceoff timing,
  substantially larger than this pass.
- **PP/PK segments** are still untouched by any decay-curve logic (`faceoff_ev_only` continues to
  gate this entire mechanism to even-strength segments only) — no post-faceoff shot study was run
  for special-teams draws.
