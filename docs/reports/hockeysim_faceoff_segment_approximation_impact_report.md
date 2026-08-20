# hockeysim discrete-event faceoff mechanism — measuring the "one faceoff per segment" approximation

The one item every faceoff-track addendum this session left genuinely open, never revisited since
the discrete-event redesign first shipped: `engine.py`'s segment loop applies exactly one
faceoff-driven shot-share multiplier to EVERY simulated segment — EV or PP/PK, no exceptions — as
if a real faceoff occurred at that segment's own start and its decay curve's time-weighted average
describes the whole ~44.4s window. This measures, for the first time, how far that assumption is
from what real games actually look like, and whether it has a measurable effect on simulated
output.

## What the approximation actually is, read from the code

`engine.py:467-469`: for a regulation period (`T == seconds_per_period == 1200`), `target_seg =
45.0`, `segments = round(1200 / 45) = 27`, `seg_len = 1200 / 27 ≈ 44.44s`. The per-segment loop
(`for k in range(segments)`) has no branch for "no real faceoff happened in this window" — every
segment gets either the EV/OZ/DZ/NZ block or the strength-state block, whichever its PP/PK flags
select, and that block always resolves a winner and applies a curve.

## Measurement 1 — how often is "exactly one faceoff" actually true?

`scripts/measure_nhl_faceoff_segment_approximation.py` divides every real game's periods 1-3 into
the SAME 27 segments the engine would generate (reading `seconds_per_period`/the `target_seg`
formula directly from `SimConfig`/`engine.py`, not re-typed by hand) and counts real faceoff
events (any strength state) landing in each segment's window, from the same `playbyplay` cache
this session's other faceoff work already bulk-fetched (1,312 games, 106,272 segments, 72,693 real
faceoffs counted).

| real faceoffs in segment | segments | % |
|---|---|---|
| 0 | 51,687 | 48.64% |
| 1 | 39,416 | 37.09% |
| 2 | 12,544 | 11.80% |
| 3 | 2,339 | 2.20% |
| 4 | 261 | 0.25% |
| 5 | 22 | 0.02% |
| 6 | 3 | 0.00% |

**Mean real faceoffs per segment: 0.684** — the engine always assumes 1.0, a real ~46% over-count
in event-frequency terms. **Only 37.09% of segments match the model's assumption exactly.**
48.64% of segments — very close to half — have ZERO real faceoffs at all: the model applies an
assumed win/loss shot-share tilt with no real event behind it. 14.27% have 2+ real faceoffs, a
case the model under-represents (it can only apply one assumed winner's effect).

**A genuinely unrepresentable case, quantified**: 7.79% of ALL segments (8,278 of 106,272) contain
2+ real faceoffs won by DIFFERENT teams — the model resolves exactly one winner per segment by
construction, so these windows cannot be represented at all, regardless of curve shape or
calibration. This is real, structural, and does not go away with better tuning of any existing
constant.

## Measurement 2 — does the over-assumption show up in simulated output?

Every discrete-event curve this session built is mean-1.0 preserving by construction (verified via
round-robin every single time a new layer was added), so applying the SAME curve to a segment with
no real driver behind it cannot, by itself, shift the AVERAGE simulated shot total — that has
already been repeatedly confirmed. What it CAN do is inject extra shot-share VARIANCE: a real,
non-trivial win/loss-driven tilt applied to roughly twice as many segments as reality has a real
event for.

`scripts/measure_nhl_faceoff_segment_variance_impact.py` runs a controlled A/B — identical rosters,
rates, and real per-team `special_teams` data both sides, seeded identically, the ONLY difference
being every one of the ten `faceoff_*` boolean flags on `SimConfig` (ON = shipped defaults, OFF =
every flag disabled, the complete list read directly from `engine.py` rather than guessed) — and
compares the standard deviation of total (home+away) shots-per-game against each other and against
the real observed standard deviation from 1,312 actual boxscores.

**Result, full scale (992-pairing round-robin, 3 sims/pairing, 2,976 games per condition, real
per-team `special_teams` data, identical seeds both sides):**

| | n | mean | std |
|---|---|---|---|
| REAL (boxscore) | 1,312 | 55.657 | 8.295 |
| SIM ON (shipped default) | 2,976 | 61.783 | 8.023 |
| SIM OFF (all faceoff mechanisms disabled) | 2,976 | 61.837 | 8.199 |

Mean delta ON vs OFF: **-0.086%** — negligible, in line with every individual-layer round-robin
check this session ran (each one, in isolation, moved the league-wide average well under 1%).

**Std delta ON vs OFF: -2.154%** — real, measurable, and the OPPOSITE direction from the
hypothesis this measurement set out to test. The over-assumption does not inflate output variance;
turning every faceoff mechanism ON very slightly REDUCES the standard deviation of total shots per
game relative to having them all off.

**A plausible mechanism, not exhaustively proven here**: every faceoff-driven multiplier this
session built is symmetric and roughly zero-sum between the two teams (`lam_h` scaled up while
`lam_a` scales down, or vice versa, on the SAME segment) — a small NEGATIVE correlation injected
between home and away shot counts on every segment, by construction. Summing two anti-correlated
quantities (home+away total) reduces the variance of the sum relative to summing two independent
ones, which is consistent with the small measured reduction. This is offered as the likely
explanation for the direction of the effect, not verified through a separate covariance
measurement — a real, stated limitation of this pass.

**Neither condition fully explains the real observed variance.** Both ON (ratio 0.9671) and OFF
(ratio 0.9884) sit BELOW the real std of 8.295 — the simulated shot-total distribution is
somewhat too tight relative to reality regardless of the faceoff mechanism's state. **This is the
decisive finding for scoping the open item**: whatever is causing the engine's shot-total
variance to run ~1-3% below real games, the "one faceoff per segment" approximation is NOT its
primary driver — disabling it entirely closes less than half of the ON-vs-real gap (0.9671→0.9884,
still 1.16% short of real), and the direction of its own effect on variance is a REDUCTION, not an
inflation. Whatever explains the larger remaining gap lives elsewhere in the engine's other
stochastic sources (segment-level Poisson shot draws, line-matching noise, or the score-effects/
period-pace multipliers) — a separate, larger question this measurement does not attempt to
answer.

## What this does NOT do

- Does not attempt a literal per-second time-stepping redesign of the engine (the fix the original
  §2r docstring named as the "real" solution) — that is a substantially larger engine-architecture
  project, out of scope for a measurement pass.
- Does not separately measure OT/shootout segments (`target_seg=40`, different geometry) — a small
  fraction of total game time, a distinct question.
- Does not attempt to fix the 7.79% genuinely-unrepresentable multi-winner-conflict case — this
  measurement quantifies it; addressing it is the larger redesign question above, not something a
  parameter change can close.

## Verified

- Segment geometry read directly from the live `SimConfig`/`engine.py` source (`seconds_per_period`,
  the `target_seg` formula), not re-typed by hand — confirmed to match by importing `SimConfig`
  itself in the measurement script rather than hardcoding `45.0`/`27`/`44.4444` as literals.
- Full 1,312-game run for measurement 1, 106,272 segments, all periods 1-3 covered.
- Measurement 2's ON/OFF flag list confirmed complete by reading every `faceoff_.*: bool` field
  declared on `SimConfig` directly (`grep -n "faceoff_.*: bool" engine.py`), not assembled from
  memory — 10 flags, all set False for the OFF condition. Full 992-pairing round-robin at 3
  sims/pairing (2,976 games per condition), identical seeds both sides for a paired comparison.
