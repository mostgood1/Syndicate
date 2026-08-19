# hockeysim DZ discrete-event model — the proper redesign, not just the sign fix

Closes the item `hockeysim_faceoff_dz_direction_fix_report.md` explicitly deferred: "a genuinely
faithful DZ-specific model (its own decay curve, fit to the §2s segment data) remains open." This
is that model — the SAME treatment §2r gave the general EV/OZ case, applied to DZ.

## Why the sign fix wasn't enough

§2t fixed the DIRECTION of the DZ adjustment (a team that wins its own DZ draw was having its own
shots boosted; real data showed the opposite) but left the mechanism's SHAPE unchanged — still one
flat constant applied across an entire ~40-45s segment, exactly the category error §2r already
diagnosed and fixed for the general case. This redesign replaces that constant with the DZ
mechanism's own real, measured decay curve.

## The DZ-specific curve

`scripts/build_nhl_faceoff_decay_curve.py --winner-zone D` extends the same marginal-bucket
technique §2r used, restricted to the 19,458 real EV faceoffs the winner took in their own
defensive zone:

| bucket (s since draw) | winner shots/100s | other shots/100s | ratio |
|---|---|---|---|
| (0, 5] | 0.0960 | 0.3976 | 0.242x |
| (5, 10] | 0.6002 | 0.6298 | 0.953x |
| (10, 15] | 0.8666 | 0.7488 | 1.157x |
| (15, 20] | 0.8174 | 0.8353 | 0.979x |
| (20, 30] | 0.7390 | 0.8712 | 0.848x |
| (30, 45] | 0.7230 | 0.7605 | 0.951x |
| (45, 60] | 0.6702 | 0.6871 | 0.975x |
| (60, 90] | 0.6257 | 0.6610 | 0.947x |

**Reported as measured, not smoothed.** Unlike the general curve's clean monotonic decay, this
curve is noisier (roughly a third the sample per bucket) and briefly crosses back above 1.0x at
(10,15]s — used exactly as measured rather than smoothed into a cleaner-looking shape, matching
this session's standing discipline. The curve also never fully reconverges to parity within the
measured range (staying at ~0.95x through 60-90s) — tail buckets beyond 90s are held flat at the
last measured bucket's own values, not assumed to reach 1.0/1.0 the way the general curve does.

## The model

`historical_truth/faceoff_decay_model.py::segment_average_multipliers_dz(seg_len)` — same
normalization discipline as every curve this session built (each bucket's `winner_mult`/
`other_mult` average to 1.0 by construction), same integration logic (refactored into a shared
`_integrate_curve` helper both the general and DZ curves now call, rather than duplicating the
integration code).

`engine.py`'s DZ layer now has a 3-tier fallback, preserving every prior rollback point:

1. **`faceoff_dz_discrete_event_model=True` (default)** — simulate a discrete Bernoulli draw for
   who wins the segment's assumed DZ draw (from the same resolved percentages), apply the real DZ
   decay curve's time-weighted average. The curve's own sign already encodes the correct
   direction — no separate direction flag needed on this path.
2. **`False`, `faceoff_dz_direction_fixed=True`** — the §2t sign-flip fix (still-flat constant,
   correct direction).
3. **`False`, `faceoff_dz_direction_fixed=False`** — the original, now-known-incorrect wiring, for
   full historical rollback.

## Verified

- **34 unit tests** on the decay-model module (17 pre-existing for the general curve, unchanged
  after refactor + 17 new for the DZ curve): exact bucket reproduction, direction reversed from the
  general curve at short segments, the mean-1.0 invariant across 9 segment lengths, tail-hold
  behavior (not assumed parity), invalid-input handling.
- **2 new reachability tests**: `faceoff_dz_discrete_event_model=True` vs `False` produce
  measurably different output; under the new default mechanism specifically, a high `faceoff_dz_index`
  still produces fewer own shots than a low one (confirms the redesign preserved the measured
  direction, not just changed the mechanism's shape).
- **The existing `faceoff_dz_direction_fixed` reachability test needed updating**, not because it
  broke silently but because its premise changed: with discrete-event now the default, that flag
  no longer affects output unless the legacy fallback is also selected — the test now explicitly
  targets `faceoff_dz_discrete_event_model=False` to exercise the path it actually tests.
- **416 hockeysim/nhl tests pass overall** (up from 397 — 17 new decay-model unit tests + 2 new
  engine reachability tests).
- **Checklist re-confirmed full PASS** — no new consumed field, this changes HOW an already-consumed
  signal is applied.
- **League-wide aggregate barely moved**: 992-pairing round-robin, legacy diff-based
  (direction-fixed) 62.082 avg total shots/game vs discrete-event 62.196 — a +0.185% delta, small
  and expected (the new curve's shape differs from a flat constant, but both average to the same
  mean-1.0 design invariant).

## What this does NOT do

- **No segment-level validation was run for OZ or EV specifically re-applying THIS session's
  refactored integration code** — the general curve's own numbers are unchanged (confirmed via a
  byte-for-byte re-run of the unfiltered decay-curve builder, matching the previously-committed
  values exactly), only the code structure was refactored to share logic with the new DZ path.
- **The noisy DZ curve's brief positive excursion at (10,15]s** is used as measured, not
  investigated further — a larger sample (as more seasons of `playbyplay` data accumulate) would
  narrow the uncertainty on that bucket specifically.
- **PP/PK-strength DZ draws** remain entirely unstudied — this redesign, like everything upstream
  of it, is gated to even-strength segments only (`faceoff_ev_only`).
