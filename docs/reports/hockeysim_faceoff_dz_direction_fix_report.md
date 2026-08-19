# hockeysim DZ mechanism wiring-direction fix

Closes the item `hockeysim_faceoff_dz_segment_validation_report.md` explicitly left open: "whether
to change the DZ mechanism's wiring direction — the natural next step, not attempted here." This
is that fix — narrowly scoped, matching the exact recommendation.

## What was wrong, restated precisely

`engine.py`'s DZ layer (§2o) applied `m_dz_h` (elevated when HOME's `faceoff_dz_index` is high) to
`lam_h` — i.e. a team good at winning its own defensive-zone draws got ITS OWN shots boosted. §2s's
real segment-level measurement found the opposite: the team that wins a real DZ draw is OUT-SHOT,
not out-shooting, in the following seconds, at every one of 4 window sizes tested (winner share
0.42–0.47 vs an OZ-specific control's 0.78–0.93, confirming the technique and isolating DZ as a
real reversal, not a method artifact).

## The fix

A minimal, targeted swap — not a mechanism redesign. `m_dz_h`/`m_dz_a` are still computed exactly
the same way (`_faceoff_multipliers` fed DZ-specific percentages); only WHICH team's shot lambda
each one is applied to changed:

```
# before (§2o, now known incorrect):
lam_h *= m_dz_h   # elevated own-DZ-index team's OWN shots boosted
lam_a *= m_dz_a

# after (§2s fix, default):
lam_h *= m_dz_a   # elevated own-DZ-index team's OWN shots pulled DOWN
lam_a *= m_dz_h   # opponent's shots pulled UP
```

Gated by a new `faceoff_dz_direction_fixed` flag (default `True`, backed by the real measurement),
`False` restores the exact original mapping for rollback/A-B comparison — the same pattern
`faceoff_discrete_event_model` (§2r) already established for exactly this kind of change.

## What this does NOT do

This is deliberately NOT a full discrete-event redesign of the DZ mechanism the way §2r rebuilt the
general EV/OZ case — it fixes the DIRECTION of the existing diff-based constant, not its
functional SHAPE. §2s's own report flagged that "an effect this specific may itself need
discrete-event treatment rather than a simple sign flip" — that remains a distinct, larger,
not-yet-attempted follow-up. This fix corrects a clear directional error with the smallest change
that does so, matching the narrow scope of what was actually asked.

## Verified

- **The existing reachability test caught the direction change immediately**, before any new test
  was written: `test_special_teams_faceoff_dz_index_actually_changes_shot_volume` failed on the
  first post-fix run with `strong=31.450 < weak=32.688` — the exact reversal the fix intended,
  confirming the change took effect. Updated to assert the corrected direction (`assertLess`
  instead of `assertGreater`).
- **New reachability test** for the flag itself: `faceoff_dz_direction_fixed=True` vs `False`
  produce measurably different output for the identical strong-DZ team, proving the flag gates the
  swap (not just exists on `SimConfig`).
- **League-wide aggregate barely moved**: 992-pairing round-robin, legacy-direction 62.230 avg
  total shots/game vs fixed-direction 62.106 — a −0.199% delta, as expected for a symmetric swap
  of which side receives a multiplier rather than a magnitude change, confirming nothing else
  regressed.
- **397 hockeysim/nhl tests pass** (up from 396), `nhl_sim_input_checklist.py` re-confirmed full
  PASS after the fix.

## What remains genuinely open

- **A proper DZ-specific discrete-event redesign** (matching §2r's treatment of the general case)
  — this fix fixes the sign, not the shape; a genuinely faithful model would need its own decay
  curve fit to the DZ-specific segment data already gathered in §2s.
- **The magnitude of the corrected effect** — `faceoff_alpha`/`faceoff_diff_clip` are unchanged,
  so the SIZE of the DZ adjustment is still the same conservative default as before; only its
  direction changed. Whether that magnitude is itself correct for the (now correctly-signed)
  effect was not examined.
