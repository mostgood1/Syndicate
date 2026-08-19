# hockeysim faceoff mechanism — calibrating `faceoff_alpha`/`faceoff_diff_clip`, the last open item

An exhaustive re-check of every faceoff-track addendum this session produced — `hockeysim_engine_
reference.md` §2j through §2zz, `nhl_model_inventory.md`'s parallel bullets, and every numbered
addendum under `#463` in `todo.md` — found exactly one item stated as open and never subsequently
closed: `faceoff_alpha`/`faceoff_diff_clip`/`faceoff_mult_clip_low`/`faceoff_mult_clip_high`, the
sensitivity constants controlling `_faceoff_multipliers`, still the vendor's original,
never-validated defaults (`alpha=0.35`, `diff_clip=0.12`, `mult_clip=[0.90, 1.10]`).

## Why this is now consequential, not just historical debt

For most of this session, `_faceoff_multipliers` was almost entirely a rollback/fallback path —
the discrete-event curves (EV/OZ/DZ/NZ) replaced it as the live default years ago in engine-time.
But it is NOT a fallback for the two newest mechanisms this session built:
`faceoff_lineup_model`/`faceoff_lineup_model_strength_state` call `_faceoff_multipliers` directly
and unconditionally — there is no discrete-event alternative for a persistent per-game
roster-quality signal, because there is no discrete "event" to build a decay curve from. Every
game those two layers touch in production, right now, is scaled by these never-validated
constants.

## Methodology — game-level, not season-aggregate

`calibrate_nhl_faceoff_nz_index.py` (§2p) already checked whether SEASON-AGGREGATE faceoff
performance predicts SEASON-AGGREGATE shot volume — found every |correlation| under 0.02,
indistinguishable from noise. That result does not settle THIS question: a season aggregate blurs
together everyone who ever dressed for a team, while the lineup-aware signal this calibration
targets is explicitly about tonight's specific roster.

`scripts/calibrate_nhl_faceoff_alpha.py` instead reconstructs, for each of **1,312 real games**,
what `compute_lineup_faceoff_pct` would have computed from that game's own **CONFIRMED** dressed
roster — real players who actually played, real TOI, straight from the `boxscore` cache — combined
with each player's season-long `faceoff_weight`, then regresses the game's real shot SHARE against
the lineup-pct DIFFERENTIAL. Real statistical power: up to 1,312 games, not 32 team-seasons.

`_faceoff_multipliers` is symmetric by construction (`m_home + m_away == 2` always), so the shot
share it implies is `m_home / (m_home + m_away) == 0.5 + (alpha/2) * diff`. Fitting
`shot_share = 0.5 + k*diff` via OLS gives `alpha = 2*k` directly — no unit-conversion guesswork.

## Result — real, weak, and honestly borderline

All 1,312 games resolved a real lineup percentage on both sides (0 skipped):

```
shot_share = 0.5091 + 0.1086 * lineup_pct_diff        R^2 = 0.0028
implied alpha = 2 * slope = 0.2171                     (vendor default: 0.35)
slope standard error = 0.0566                          t = 1.917, p ~= 0.055
95% CI for slope: [-0.002, 0.220]  ->  95% CI for alpha: [-0.005, 0.439]
```

**Neither a clean null nor a confident signal.** R²=0.0028 means the lineup-quality differential
explains essentially none of a single game's shot-share variance — but at N=1,312 the slope sits
right at the conventional significance boundary (p≈0.055), a genuinely different result from the
NZ season-aggregate check's clear |r|<0.02 null. There is a real, if weak, positive relationship;
the game-to-game noise floor is simply much larger than it.

**The decisive fact for the calibration decision**: the vendor's original `alpha=0.35` sits
**comfortably inside** the measured 95% confidence interval `[~0, 0.44]`. Real data does not
contradict the current default. It also does not precisely pin down a better number — the interval
is wide enough to contain almost anything from "no effect" to "somewhat stronger than the vendor's
own guess."

## Decision: left unchanged, backed by a real measurement

**`faceoff_alpha` stays at 0.35.** Overwriting a genuine (if imprecise) measurement with a
differently-uncertain point estimate (0.2171, whose own confidence interval nearly reaches zero at
one end) would not be an improvement — it would trade one unvalidated number for another,
dressed up as a calibration. This is the same discipline the NZ item (§2p) and the block-rate
EV:PK:PP-def ratio (§2h) already established: a real check that concludes "leave it as-is" closes
an open item exactly as legitimately as one that finds a number to change.

`faceoff_diff_clip=0.12` was separately checked against the real observed `|lineup_pct_diff|`
distribution (p95=0.0851, max=0.1582) — it clips only the most extreme ~5% of real cases, a
sensible bound, not an arbitrary one that happens to have never been re-examined.

## What this does NOT do

- Does not touch `faceoff_mult_clip_low`/`faceoff_mult_clip_high` — no real evidence surfaced
  suggesting the output bounds `[0.90, 1.10]` are binding or miscalibrated at the fitted (or even
  the vendor's own) alpha value.
- A mild in-sample note, disclosed rather than hidden: each player's `faceoff_weight` is a
  SEASON-long average that includes the very game being predicted (not a leave-one-out fit).
  Given a single game is a small fraction of a player's 20-80+ game season sample, this dilutes
  rather than dominates the fit — a real, small limitation, not a confound large enough to explain
  away the already-weak result.
- Does not attempt a leave-one-out or held-out-season refit -- the result is weak enough that this
  additional rigor would not change the "leave as-is" conclusion, and the added complexity was not
  judged worth it for a decision that already has a clear answer.

## Verified

- `_ols_slope_and_r2`'s own arithmetic checked against two synthetic cases (a perfect line and a
  flat line) — recovers `intercept`/`slope`/`R²` exactly in both.
- Full 1,312-game run, 0 games skipped for missing data — the calibration ran end to end against
  the complete real local mirror, not a sample.
- `calibration_profile.py`'s `faceoff_alpha`/`faceoff_diff_clip`/`faceoff_mult_clip_*` now carry
  an explicit comment documenting this check and its conclusion, so a future session does not
  re-discover the same open item and re-run an identical check from scratch.
