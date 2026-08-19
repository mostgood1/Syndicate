# hockeysim OZ-specific discrete-event curve

Closes a real precision mismatch the discrete-event redesign left in place: `_resolve_faceoff_pct`
already prefers the OZ-specific per-team index over the coarser EV-blend index when available (§2n)
— but until this pass, that more-precise WIN-RATE signal still fed into the general
(EV+OZ+DZ-blended) decay curve, discounting the very precision the percentage resolution already
prioritized.

## The OZ-specific curve — a much stronger, cleaner version of the general effect

`scripts/build_nhl_faceoff_decay_curve.py --winner-zone O` — the same population (18,662 real
draws) `hockeysim_faceoff_dz_segment_validation_report.md` already used as its confirming OZ
control, now built at MARGINAL bucket resolution:

| bucket (s since draw) | winner shots/100s | other shots/100s | ratio |
|---|---|---|---|
| (0, 5] | 3.3813 | 0.0282 | 119.7x |
| (5, 10] | 1.7285 | 0.3536 | 4.89x |
| (10, 15] | 1.1453 | 0.5953 | 1.92x |
| (15, 20] | 1.0022 | 0.6533 | 1.53x |
| (20, 30] | 0.9432 | 0.6844 | 1.38x |
| (30, 45] | 0.7529 | 0.7241 | 1.04x |
| (45, 60] | 0.6770 | 0.6259 | 1.08x |
| (60, 90] | 0.6522 | 0.6433 | 1.01x |

**The raw first-bucket ratio (119.7x) reflects a near-zero denominator, not an unstable
measurement**: the team that just lost a draw deep in the opponent's attacking zone genuinely has
almost no shots of its own in the first five seconds — it does not yet have the puck. Real hockey
sense, and the winner's own rate (3.38 shots/100s) is large and robust regardless of how the
ratio is expressed. Mean-normalization tames this into a bounded, sensible pair (winner_mult≈1.98,
other_mult≈0.017) — the same design property that already handled the DZ curve's own extremes.

**Decays smoothly and monotonically, and — unlike DZ — fully reconverges**: winner/other rates are
within 1.4% of each other by (60,90]s, the same clean convergence pattern the general curve showed,
just a stronger version of it. This makes sense: OZ draws are the purest case of the phenomenon the
general (blended) curve represents; the general curve is diluted by NZ draws (mild) and DZ draws
(reversed).

## The model and wiring

`segment_average_multipliers_oz`, sharing the same `_integrate_curve` helper as the general and DZ
curves. Since it fully reconverges, its tail-hold behavior matches the general curve (1.0/1.0
beyond 90s), not DZ's own last-bucket hold.

`engine.py`'s EV/OZ discrete-event block now chooses between the OZ-specific and general curve
**as a single segment-level decision**, gated on BOTH sides carrying real `faceoff_oz_index` data
— the same bilateral discipline the DZ layer already uses, since the curve describes one assumed
draw's consequence, not two independent per-side effects. `faceoff_oz_specific_curve` (default
`True`) controls this; `False` uses the general curve even when real OZ data is available, for
rollback/A-B.

## Verified

- **51 unit tests** on the decay-model module (34 pre-existing unchanged + 17 new for the OZ
  curve): exact bucket reproduction, stronger-than-general at every matched length, the mean-1.0
  invariant (loosened to `abs=1e-3` for OZ specifically, given more rounding accumulation from the
  extreme first-bucket constants than the milder general/DZ curves carry), full reconvergence at
  long segment lengths, invalid-input handling.
- **2 new reachability tests**: the flag changes output when both sides carry real OZ data; the
  curve choice is confirmed a near no-op when only ONE side does (the bilateral gate actually
  gates, not just exists).
- **433 hockeysim/nhl tests pass before these 2 new tests were even added** (the wiring change
  itself broke nothing) — climbing further with the new tests included.
- **League-wide aggregate barely moved**: 992-pairing round-robin, general curve (forced for all
  OZ-preferred segments) 62.127 avg total shots/game vs OZ-specific 62.284 — a +0.253% delta,
  small and expected.
- Checklist re-confirmed full PASS — no new consumed field, this changes HOW an already-consumed
  signal is applied.

## What this does NOT do

- **No NZ-specific curve was built** — `faceoff_nz_index` was already deliberately left unwired
  (§2p) after finding no season-aggregate correlation; this pass doesn't revisit that decision.
- **No re-derivation of the general curve's own OZ-heavy composition** — the general curve still
  blends OZ/NZ/DZ draws together for segments that fall back to it; only segments where BOTH sides
  have real OZ-specific data get the more precise curve.
- **EV-tier segments (real EV index but no OZ index) still use the general curve** — a genuinely
  EV-specific curve (isolating segments where the winner's zone was NOT their own OZ, i.e. NZ+DZ
  combined) was not built; the general curve remains the fallback for that population, matching
  the same precedence order the percentage resolution itself already uses.
