# hockeysim strength-state (PP/PK) faceoff effect — the first mechanism outside EV

Closes the last item this session's faceoff-zone work flagged as genuinely different from more
zone-slicing: does winning a faceoff DURING a power play or penalty kill have its own measurable
effect, distinct from the zone-specific (EV/OZ/DZ/NZ) mechanisms — all of which are gated
`faceoff_ev_only=True` and have never applied outside even-strength segments at all.

## The population EV-only extraction always excluded

`faceoff_segment_effect.py`'s default extraction path (`_extract_timed_events`) explicitly filters
to `away_skaters == home_skaters` — every zone-specific check this session ran, by construction,
never touched a single PP/PK-strength draw. `compute_post_faceoff_shots_by_strength_role` (new)
extends the same module with `include_non_ev=True`, tagging each non-EV faceoff's `role` as the
WINNER's own skater-count status: `"PP"` (already had the advantage) or `"PK"` (was shorthanded).

## Method

Same winner/other post-draw shot-counting methodology as every zone-specific check, restricted to
PP-role and PK-role draws separately, at the same 4 window sizes.

## Result — real, large, and directionally sensible

| role | window | winner share | ratio |
|---|---|---|---|
| PP | 10s | 0.9329 | 13.90x |
| PP | 15s | 0.9103 | 10.15x |
| PP | 20s | 0.9003 | 9.03x |
| PP | 30s | 0.8790 | 7.27x |
| PK | 10s | 0.4313 | 0.76x |
| PK | 15s | 0.3755 | 0.60x |
| PK | 20s | 0.3189 | 0.47x |
| PK | 30s | 0.2749 | 0.38x |

**PP-role**: the already-advantaged team ALSO winning the draw compounds its existing edge — a
huge, expected effect (most PP draws happen in the attacking zone, and now that team has both the
man advantage and the puck).

**PK-role**: even when the shorthanded team wins the draw, it still gets out-shot, and increasingly
so as the window widens — the opponent's man-advantage reasserts itself regardless of who won the
specific draw. Directionally the opposite of PP-role but for a coherent reason: the underlying
manpower asymmetry dominates over a longer window.

**Isolating the draw-specific increment from the baseline PP/PK asymmetry**: from the PP TEAM's own
perspective (not the "winner"), their share of shots is ~0.93 when they win the draw themselves vs.
~0.57 (`1 - 0.4313`) when the PK team wins it, at 10s — a large, genuinely incremental effect from
who won the specific draw, not merely a restatement of the calibrated `pp_shots_mult`/`pk_shots_mult`
baseline.

## The marginal decay curves

`scripts/build_nhl_faceoff_decay_curve.py --winner-role PP` / `--winner-role PK`, same 1,312-game
cache, 8,033 PP-role and 6,701 PK-role draws:

| bucket | PP winner_mult | PP other_mult | PK winner_mult | PK other_mult |
|---|---|---|---|---|
| (0,5] | 1.9167 | 0.0833 | 1.1331 | 0.8669 |
| (5,10] | 1.8361 | 0.1639 | 0.6327 | 1.3673 |
| (10,15] | 1.7395 | 0.2605 | 0.5298 | 1.4702 |
| (15,20] | 1.7346 | 0.2654 | 0.3435 | 1.6565 |
| (20,30] | 1.6421 | 0.3579 | 0.4097 | 1.5903 |
| (30,45] | 1.6395 | 0.3605 | 0.3886 | 1.6114 |
| (45,60] | 1.6048 | 0.3952 | 0.3919 | 1.6081 |
| (60,90] | 1.5492 | 0.4508 | 0.4332 | 1.5668 |

**A real, interesting property of the PK-role curve**: its direction FLIPS as the window widens — a
brief clear-driven bump favors the shorthanded winner in the first 5-10s (`winner_mult` above 1.0),
then reverses as the opponent's advantage reasserts. No other curve built this session does this;
every other one is monotonic in one direction throughout.

**Neither curve reconverges within the measured window**, unlike the general/OZ/NZ curves — a real
power play often runs close to or beyond 90s, so the underlying man-advantage situation is typically
still active regardless of who won the draw. Both held flat at their own (60,90] values beyond that,
matching DZ's convention, not the general/OZ/NZ assumption of eventual parity.

## The model and wiring

`historical_truth/faceoff_decay_model.py::segment_average_multipliers_pp_role`/`_pk_role` — same
normalization and integration discipline as every curve this session built.

`engine.py`'s new `faceoff_strength_state_model` flag (default ON): fires precisely when the
general/OZ/DZ/NZ block is gated OFF (`faceoff_ev_only=True` and the segment IS a PP/PK segment) —
resolves each side's faceoff percentage via the SAME OZ→EV→blend chain the general mechanism uses,
simulates who wins the segment's assumed draw, determines the WINNER's own role (did they have the
skater advantage or not), and applies the matching curve.

**A real, stated limitation, not hidden**: no dedicated per-team PP/PK-specific win-rate index was
built. A team's faceoff performance while already on the power play (with specialist personnel
often deployed) could genuinely differ from their overall/EV win rate, and this mechanism cannot
capture that difference — it reuses the general signal as the best available approximation. Building
a true PP/PK-role-specific per-team index would need its own aggregation pipeline (mirroring
`compute_team_faceoff_oz_index`'s structure but for role instead of zone), not attempted this pass.

## A real bug found by the round-robin check every layer this session was held to — and fixed

The first wiring applied each curve via a naive probabilistic branch: simulate who wins, apply
`pp_curve.winner_mult`/`other_mult` if the PP-side team won, `pk_curve.winner_mult`/`other_mult` if
the PK-side team won. Each curve is individually mean-1.0 (`winner_mult + other_mult` averages to
2 across the two outcomes) — but that guarantees only that the SUM of the two sides' expected
multipliers is 2, not that EACH side's own expectation is 1.0 individually. Since the PP-side's
baseline lambda is already larger than the PK-side's (by design — `pp_shots_mult > pk_shots_mult`),
and PP-role's magnitude is far larger than PK-role's, this asymmetry inflated the league-wide total
by **+4.478%** in a 992-pairing round-robin — silently working against the already truth-calibrated
`pp_shot_cal_mult`/`pk_shot_cal_mult` baseline, exactly the kind of aggregate drift this session's
own discipline exists to catch before shipping.

**Fixed with an exact per-segment normalization**, not an empirically-tuned damping constant (a
damping factor was considered and rejected: since the bias scales linearly with the damping
strength through the origin, any nonzero damping still leaves SOME bias — there is no damping value
that both preserves a real effect AND fully removes the bias). `_strength_state_multipliers`
(`engine.py`, extracted as an independently testable pure function) computes, PER SEGMENT, each
side's own expected multiplier at THAT segment's specific win probability (`E_pp_side = p*w_pp +
(1-p)*o_pk`, `E_pk_side = p*o_pp + (1-p)*w_pk`), then divides the realized multiplier by that
expectation — making `E[applied_mult] = 1.0` EXACTLY for both sides, for any win probability,
while leaving each curve's real, measured, asymmetric SHAPE (the ratio between winning and losing
the draw) completely untouched.

**Verified two ways, not just one**:
- **Analytically**: a dedicated test computes `p*m_when_pp_wins + (1-p)*m_when_pk_wins` directly at
  5 win probabilities (0.05 to 0.95) using the REAL curve values, confirming `E[]=1.0` to 6 decimal
  places — a mathematical proof, not a statistical approximation.
- **Empirically**: the same 992-pairing round-robin, re-run after the fix — league-wide aggregate
  delta dropped from **+4.478% to +0.203%**, in line with every other faceoff layer's near-zero
  deltas this session measured.
- A separate test confirms the fix did NOT flatten the real effect into a no-op: the winner's own
  multiplier still exceeds the loser's on both sides after re-centering.

## Verified

- **31 new unit tests** on the two curves (99 total in the decay-model file): exact bucket
  reproduction, the PK-role direction-flip property, both curves' non-reconvergence at long
  segments, the mean-1.0 invariant across 9 lengths each, invalid-input handling.
- **7 new unit tests** on the strength-role extraction and counting function (24 total in the
  segment-effect file): role classification (PP vs PK, correctly flipping with which side has the
  advantage), EV-draw exclusion, cross-strength-state shot counting within a window, backward
  compatibility of the EV-only extraction path (`include_non_ev` defaults to `False`).
- **3 new engine tests**: reachability (the flag changes total simulated shot output); the
  analytical E[]=1.0 proof at 5 win probabilities; the real-shape-preserved check.
- **League-wide aggregate**: +0.203% after the normalization fix (992-pairing round-robin), down
  from a real +4.478% bug in the first wiring.
- Checklist and full test suite re-confirmed unaffected (no new `HockeyTeamFeatures`/CSV field —
  this mechanism reuses signals already consumed elsewhere).

## What this does NOT do

- No dedicated PP/PK-role-specific per-team index (stated above).
- The curve choice does not distinguish HOME-PP-vs-AWAY-PK from AWAY-PP-vs-HOME-PK beyond what the
  role classification already captures — both are handled correctly by the same PP/PK role logic,
  but no team-level PP-specific-vs-PK-specific SEPARATE index differentiates, say, a team's PP-unit
  faceoff specialist from its PK-unit one.
- Neutral-zone and defensive/offensive-zone draws that happen to occur DURING a power play are not
  separately modeled — this mechanism treats every PP/PK segment's assumed draw uniformly by role
  only, not role-and-zone jointly (the zone-specific curves remain gated EV-only).
