# hockeysim faceoff segment-level validation — a real, large, local effect

Closes the item `hockeysim_faceoff_nz_calibration_report.md` explicitly left open: "a
segment-level (not season-aggregate) validation of the EV/OZ/DZ mechanism — the only kind of check
that could actually confirm or refute the local effect `_faceoff_multipliers` claims to model."
This is that check, and it flips the picture the season-aggregate check gave.

## The question the season-aggregate check couldn't answer

Every faceoff-zone index this session built (EV/OZ/DZ/NZ) showed a season-aggregate correlation
with real `shots_per_60` under 0.02 in magnitude — indistinguishable from zero. That result could
not distinguish "faceoffs have no real effect on shot generation" from "a real, local effect exists
and washes out completely across a season's worth of everything else that happens in the other ~58
minutes per game." The season aggregate is simply the wrong timescale to see a segment-level
effect, if one exists.

`_faceoff_multipliers` claims the latter kind of effect: winning a specific draw shifts shot
generation in the seconds immediately following that draw. This report checks that directly.

## Method

`historical_truth/faceoff_segment_effect.py`: for every real EVEN-STRENGTH faceoff in the
`playbyplay` cache (1,312 games), count real `shot-on-goal`/`goal` events by the WINNING team vs
the OTHER team in a window immediately after the draw — truncated at whichever comes first: the
fixed window length, the next EV faceoff in the same period (so a shot is never attributed to more
than one draw), or the period's own end.

## Result — robust across window sizes, with the exact decay pattern a real effect should show

| window | EV faceoffs | winner shots | other shots | winner share | shots/100s winner | shots/100s other | ratio |
|---|---|---|---|---|---|---|---|
| 10s | 58,762 | 5,501 | 1,432 | 0.7935 | 0.9740 | 0.2535 | 3.84x |
| 15s | 58,762 | 7,565 | 2,746 | 0.7337 | 0.9245 | 0.3356 | 2.76x |
| 20s | 58,762 | 9,349 | 4,235 | 0.6882 | 0.8865 | 0.4016 | 2.21x |
| 30s | 58,762 | 12,572 | 7,191 | 0.6361 | 0.8493 | 0.4858 | 1.75x |

**The winner out-shoots the loser by a real, large margin in every window tested**, and the ratio
**decays smoothly and monotonically** as the window widens — exactly the pattern a genuine,
concentrated, local effect should produce (the closer to the draw, the more the window's shots are
dominated by the direct consequence of the draw; the wider the window, the more it's diluted by
broken plays, transitions, and other possession changes unrelated to who won the faceoff). A
methodology artifact or pure noise would not be expected to decay this cleanly across four
independently-run window sizes.

## What this means

**Faceoffs DO have a real, substantial, immediate effect on shot generation** — the season-
aggregate null result was measuring the wrong thing, not disproving the mechanism's premise. This
is the single most important finding from this session's whole faceoff-zone track: the underlying
hockey intuition behind `_faceoff_multipliers` (and behind building OZ/DZ/NZ indices in the first
place) is validated by real, direct, local measurement, even though none of the per-team indices
built on top of it show up in season-long team aggregates.

## The important caveat — this does NOT validate the ENGINE's current mechanism as-is

`_faceoff_multipliers` applies **one uniform multiplier across an entire engine segment**, derived
from a team's **season-long** win percentage (or, after §2m/§2n/§2o, a per-team zone-specific
index) — not a discrete, short-lived boost tied to a specific draw the way this measurement is. The
real effect measured here is a **sharp, brief spike concentrated in the first ~10-15 seconds**, not
a persistent segment-wide shift. This report validates that faceoffs matter and validates the
*direction* of the existing mechanism (the winning team's own shots should go up) — it does **not**
validate that the engine's specific *functional form* (a uniform per-segment multiplier sourced
from season-aggregate win rate) is the right way to model a real effect that is this concentrated
and short-lived.

**Concretely**: directly recalibrating `faceoff_alpha` to match a ~2-4x per-draw shot-rate ratio
would be a category error — `alpha` scales a *segment-long* multiplier, not a *per-draw* spike, and
the two are not the same kind of quantity. A more faithful model would need to represent faceoffs
as discrete, time-limited events with their own decay profile (matching the window-size decay
measured here) rather than folding them into a segment-wide constant — a genuine engine redesign,
not a calibration pass, and a substantially larger undertaking than this report attempts.

## What remains genuinely open

- **A properly-scoped recalibration of the segment-wide mechanism** using this report's findings as
  a directional sanity check (does a stronger team's season win% differential still point the right
  way, even if the magnitude can't be derived directly from the per-draw ratio) — not attempted
  here, since the basis mismatch above means there's no single clean conversion.
- **An engine redesign representing faceoffs as discrete events** with a real decay profile (the
  10s/15s/20s/30s ratios above are a genuine empirical starting point for such a model) — a
  substantially larger project, out of scope for this pass.
- **Whether this local effect explains any of the real per-team OZ/DZ/NZ spread** measured in the
  earlier zone-specific work — not tested here; would need combining per-team zone-index data with
  per-draw segment outcomes, a natural follow-up.
