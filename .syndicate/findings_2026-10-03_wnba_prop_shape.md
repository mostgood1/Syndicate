# FINDINGS — a count SHAPE for WNBA rebounds / assists / threes ladders

**Lane** `wnba-prop-shape`, session `39b666bb`. **Date** 2026-10-03. **No deploy; flag default OFF.**
Built on the fix #2 + #3 stack (availability + rate shrink; ladders = fix #3's engine module applied post-sim to the
availability-on re-run of all 116 dates). Train May–July regular season, test Aug–Sep + playoffs. 5,891 rows/stat.

## 0. Headline

1. **"Per-player" is REFUTED.** Shrinking each player's own variance-to-mean ratio toward the league's, the fitted
   shrink runs to *league only* for rebounds and threes and to k = 64 (near league-only) for assists. A player's own
   game-to-game dispersion carries no usable signal at these sample sizes.
2. **The SHAPE is what helps:** a negative binomial at the stack mean with the league dispersion (D = 1.189 rebounds,
   1.089 assists, 1.131 threes -- near-Poisson) beats the sim's own ladder.
   - whole-ladder RPS, held out: **rebounds −0.021 [−0.029, −0.013], assists −0.016 [−0.023, −0.008], threes −0.020
     [−0.025, −0.015]**;
   - Brier at the book line, held out, pooled over the three markets: **−0.0042 [−0.0065, −0.0018]** (n 2,420); per
     market the CIs each just touch 0 (rebounds −0.0033 [−0.0063, +0.0001], assists −0.0047 [−0.0096, +0.0001],
     threes −0.0048 [−0.0102, +0.0009]);
   - playoffs (257): −0.0059 [−0.0127, +0.0010] pooled; assists −0.026 [−0.038, −0.015] alone; rebounds +0.007 (ns).
3. **Closest to the book of any prop work so far.** Pooled, still behind the book by **+0.0043 [+0.0002, +0.0083]**;
   per market the gap is no longer distinguishable from 0 (rebounds +0.0049 [−0.0013, +0.0109]; assists +0.0031;
   threes +0.0046). Ties the player's own-average normal (rebounds +0.0003 [−0.0066, +0.0073]).

## 1. The estimator and the change

Engine module NEW `syndicate/features/shared/wnba_prop_shape.py` (one call in `basketball_props_smart_sim.py` after the
rate-shrink call and before the dispersion hook): for each player row, for reb/ast/threes, rebuild the ladder as a
negative binomial with mean `<stat>_mean` and variance `D * mean`, `D = (n D_own + k D_league)/(n + k)` (k, D_league
from `wnba_prop_shape.json`; D_own from `boxscores_history.csv`, games before the slate), materialised as `simCount`
values by largest-remainder rounding, so every reader sees an ordinary ladder. Combo ladders and `<stat>_mean`/`_sd`
untouched. Missing/broken factor file → untouched + named reason. WNBA only; OFF unless `SYNDICATE_WNBA_PROP_SHAPE`.

Factor file (`fit_wnba_prop_shape.py --write-artifact`): `{"reb": {"k": 1e9, "d_league": 1.189}, "ast": {"k": 64,
"d_league": 1.089}, "threes": {"k": 1e9, "d_league": 1.131}}`. D_league is pooled over the TRAINING period (fixed --
as-of for the test; mildly in-sample for train), stated.

**Reachability through the real engine** (one-date re-run 2026-07-20, availability + rate shrink + shape on):
`PROP_SHAPE applied` on all 4 games (57–63 ladders each); **243 of 243** shaped ladders exactly equal the NB at the
row's rate-shrunk mean and stamped D. Tests: `tests/test_wnba_prop_shape.py` (9) + 79 related, 88 pass.

## 2. How this composes with fix #1

Fix #1's stack re-fit found widening does ~nothing on rebounds/assists/threes and slightly hurts rebounds in the
playoffs; its recommendation was to widen only points and the combos. This lane's shape replaces exactly the three
ladders fix #1 should leave alone, and it runs BEFORE fix #1's hook -- so if both are enabled, fix #1's factor file
must NOT include reb/ast/threes (the engine would otherwise dilate the NB). Stated as a requirement for enablement.

## 3. NOT done

Enable (user decision): `SYNDICATE_WNBA_PROP_SHAPE=1` together with #2 and #3 (the shape was fit on their mean), the
factor file on the fleet disk (allowlist line in `artifact_publisher.py`, claimed by lane `nhl-live-resim` →
cross-lane approval), fleet ff.
