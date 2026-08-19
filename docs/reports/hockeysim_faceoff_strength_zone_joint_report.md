# hockeysim strength-state faceoff mechanism — a joint role-and-zone refinement

Closes the item the strength-state report's own "What this does NOT do" section named directly:
NZ/DZ/OZ draws that happen to occur DURING a power play or penalty kill were not separately
modeled — only the WINNER's role (§2x), and their per-team role-specific win rate (§2y). This
checks whether the ZONE a PP/PK draw is won in has its own measurable effect, distinct from the
role-only average, and — where the data supports it — builds it.

## Measured first, decided second — matching the NZ precedent

`scripts/calibrate_nhl_faceoff_strength_zone_joint.py` measured winner share by (role, zone) at
three window sizes, and — critically, before committing to build anything — the PER-TEAM draw
count in each cell, since a joint split divides an already-modest non-EV population six ways.

**Population counts, from 1,312 real games**: a PP-role draw is 82.8% offensive-zone (6,653), 13.4%
neutral (1,080), 3.7% defensive (300). A PK-role draw is 83.6% defensive-zone (5,600), 13.5% neutral
(904), 2.9% offensive (197) — almost the mirror image, as real hockey sense predicts (a power play
sets up in the attacking zone; a penalty kill defends in its own).

**Winner share by (role, zone), vs the role-only average, at 15s:**

| role+zone | n | winner_share | role-only | delta |
|---|---|---|---|---|
| PP+O | 6,653 | 0.9159 | 0.9103 | +0.0055 |
| PP+N | 1,080 | 0.8515 | 0.9103 | −0.0589 |
| PP+D | 300 | 0.6667 | 0.9103 | **−0.2437** |
| PK+O | 197 | 0.7059 | 0.3755 | **+0.3304** |
| PK+N | 904 | 0.5059 | 0.3755 | +0.1304 |
| PK+D | 5,600 | 0.3484 | 0.3755 | −0.0272 |

Real, large, and coherent: the majority-zone cells (PP+O, PK+D) sit close to the role-only average
by construction (they ARE most of the population), while the minority-zone cells diverge sharply —
a power-play team winning a draw in its OWN defensive zone (rare) is dramatically LESS favorable
than typical; a shorthanded team winning a draw in the OFFENSIVE zone (rarer still) is dramatically
MORE favorable. Both effects point the same direction as the general OZ>NZ>DZ ordering the
even-strength zone curves already established — a real, hockey-sensible, EXTERNALLY consistent
finding, not an artifact of this specific split.

**Per-team feasibility, the check a curve builder cannot skip:**

| role+zone | teams | min/team | median/team | max/team |
|---|---|---|---|---|
| PP+O | 32 | 164 | 210 | 258 |
| PP+N | 32 | 23 | 33 | 48 |
| PP+D | 32 | 5 | 8 | 16 |
| PK+O | 32 | 1 | 6 | 11 |
| PK+N | 32 | 14 | 29 | 41 |
| PK+D | 32 | 140 | 170 | 244 |

A per-team joint index (mirroring `faceoff_pp_role_index`/`faceoff_oz_index`) is infeasible for 4 of
6 cells — PP+D and PK+O sit at single-digit-to-teens draws PER TEAM across an ENTIRE SEASON, and one
team has exactly 1 PK+O draw all year. **This is why §2z is population-level only, not a per-team
signal** — a real, stated, data-driven limitation, not an oversight.

## What was built: a leaguewide joint decay curve, not a per-team index

Five of the six (role, zone) cells have enough LEAGUEWIDE data (300–6,653 draws) to support their
own discrete-event decay curve, built the same way as every other curve this session
(`scripts/build_nhl_faceoff_decay_curve.py`, extended to accept `--winner-role` and `--winner-zone`
together). **PK+O (197 draws) is the one cell too thin even at the population level** —
`segment_average_multipliers_strength_zone` intentionally routes it to the flat PK-role curve
instead of a dedicated (and unreliable) PK+O curve, a real floor stated in the code, not silently
dropped.

`historical_truth/faceoff_decay_model.py` gained `segment_average_multipliers_pp_role_oz`/`_nz`/`_dz`
and `_pk_role_nz`/`_dz` (five new curves), `_STRENGTH_ZONE_PROBS` (the real measured zone
distribution per role), `draw_strength_zone` (maps a uniform draw to a zone using those real
proportions), `segment_average_multipliers_strength_zone` (the dispatcher, including the PK+O
floor), and `expected_multipliers_strength_zone` (the zone-marginalized expectation the exact
normalization below needs).

## The exact-normalization proof, generalized without re-deriving it from scratch

The naive-combination bug §2x found and fixed taught this session a hard lesson: combining two
independently mean-1 curves does NOT automatically preserve the aggregate. Adding a THIRD random
dimension (which zone) risked repeating that mistake in a harder-to-spot form.

`engine.py`'s new `_strength_state_zone_multipliers` avoids re-deriving the proof: it reuses
`_strength_state_multipliers`'s exact structure, with one change — the denominator
(`e_pp_side`/`e_pk_side`) is computed from the ZONE-MARGINALIZED expectation
(`expected_multipliers_strength_zone`, a real weighted sum over the three zone curves using the
REAL measured population proportions), not the flat role-only curve. The numerator still uses the
SPECIFIC zone actually drawn for that segment. Because the zone is drawn AFTER the win/loss outcome
from that SAME fixed distribution the expectation was computed against, `E[applied_mult] = 1.0`
follows by the same algebra as §2x's own proof — not an assumption that a role-only curve
"happens to" equal a zone-weighted average of the joint curves (a decomposition that would only
hold approximately for a rate, not exactly, since a rate is not linear the way a share is).
**If the realized zone's values equal the zone-expected values (no differentiation), the function
provably reduces to exactly `_strength_state_multipliers`'s own output** — a direct backward-
compatibility test confirms this.

**Verified two ways**: analytically (`E[m_pp_side] == E[m_pk_side] == 1.0` to 4 decimal places at 5
win probabilities, using the REAL joint curve values and REAL zone probabilities) and empirically
(992-pairing round-robin, zone model ON vs OFF — see Verified below for the measured delta).

## What was found, stated plainly

- The joint effect is real, large, and directionally consistent with the already-shipped
  even-strength zone curves (OZ > NZ > DZ, for both roles) — external validation, not a novel or
  surprising pattern invented for this pass.
- One of six cells (PK+O) is too data-thin for its own curve at ANY level, population or per-team,
  and falls back to the flat role-only curve, a real floor stated in the code.
- A per-team joint index is infeasible for 4 of 6 cells — this is population-level only, and that
  limitation is real, not a shortcut.
- The zone is drawn from a FIXED population distribution, not conditioned on which specific teams
  are in the segment — the mechanism captures "the zone effect exists and matters," not "this team
  is more likely to win its OWN-zone draws than that team," which no data supports building.

## Verified

- 27 new unit tests on the five joint curves plus the dispatcher/expectation/zone-draw helpers (182
  total in the decay-model file).
- 4 new engine tests: the analytical `E[]=1.0` proof at 5 win probabilities; a reduces-to-flat
  backward-compatibility check; reachability (the flag changes the per-seed event stream); plus the
  existing `_strength_state_multipliers` tests unaffected.
- `nhl_sim_input_checklist.py` re-confirmed full PASS (no new consumed `HockeyTeamFeatures` field —
  this mechanism uses population-level constants, not a new per-team CSV column).
- 605 hockeysim/nhl tests pass overall.
- **League-wide aggregate**: **−0.055%** (992-pairing round-robin, zone model ON vs OFF, real
  production `special_teams` data) — noise-level, matching the mean-invariance property this
  mechanism's own exact-normalization design guarantees (a per-game DISTRIBUTIONAL refinement, not
  a mean shift), the same result §2y's own round-robin found for the same underlying reason.
