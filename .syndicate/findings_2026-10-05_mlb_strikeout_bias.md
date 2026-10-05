# MLB engine calibration chain, and the combined-calibration design `[2026-10-05/06, lanes mlb-strikeout-bias, mlb-starter-length, mlb-hr-rate, mlb-pa-length, mlb-hr-prop-calibration, mlb-non-pa-outs]`

All numbers come from the as-of replay. The engine is TODAY's code, run over the stored `roster_objs` each date's sim consumed, against StatsAPI box scores, on 26 dates (2026-06-15..07-12; tune < 07-04, holdout >= 07-04).

The replay is validated against production's stored sims:
- 10-03: +0.09 outs over 8 starters;
- 10-03..10-05: production matches the replay of the shipped value.

## What shipped (each by a rule pre-registered before its result was read)

| change | holdout effect | live |
|---|---|---|
| `starter_short_start_prob` 0.06 -> 0.10 | outs CRPS 2.344 -> 2.321, outs bias +0.88 -> +0.73 | eedfde5e, verified 10-05 |
| first-pitch sim freeze | 6/6 started games kept a pregame copy | 20b3dbc4, verified 10-05 |
| 10 of 18 hitter-prop calibrations re-fit | e.g. hits_1plus log-loss 0.6911 -> 0.6796, served mean 0.524 -> 0.620 vs 0.589 actual | 5fdd5139, verification owed |
| caught-stealing outs credited to the pitcher | BF balance +0.05 -> -0.05 (actual -0.47); play byte-identical | b6fd6189, verification owed |

## What failed, and why it matters

| attempt | passed | failed |
|---|---|---|
| shelled-starter hook (outs-based pulls) | starter outs: bias ~0, <=9-out share 7-10% vs 8.2% | ER 0.11-0.19 too low, or the totals gap grew |
| `base_hbp` alone (HBP 7.6x too high) | HBP to actual | K/BF rose to +12%, totals 9.0 -> 7.3 |
| joint HBP + foul + HR | K/BF, HR/PA, H/PA, BB/PA all to actual | starters go DEEPER: outs +0.95, H +0.79, BB +0.29, ER +0.32, total 9.60 vs 9.06 |

**The engine's defects cancel in pairs.**
- **HBP vs K.** Seven times too many HBPs end plate appearances before strike three, so K/BF looks right until HBP is fixed.
- **HBP vs runs.** The same free baserunners prop up scoring, so the run environment looks right until HBP is fixed.
- **Per-PA rates vs starter length.** Fixing the per-PA rates makes innings cheaper in pitches, so starters go longer.
- **Opposing starter-length levers.** The shelled hook pulls too early on runs; the joint re-fit keeps starters in too long.

Every single-lever fix moves one side of a pair and breaks the other. **One fit of all the coupled levers together is the only remaining move.**

Also found:
- **The 09-04 HR refit (`hr_rate_mult` 1.856) never reached production.** The forward pitch-model overrides file pins 1.1.

## Combined-calibration design

### Levers (coupled; fitted together)

| lever | target moment (real, TUNE) | evidence |
|---|---|---|
| `base_hbp` | HBP per PA (~1.0%) | 0.0015 -> 0.26/start vs 0.22 |
| `early_count_foul_boost` + `base_in_play`/`base_foul` mix | K/BF (0.228) and pitches/BF (3.85) | foul 1.5 -> K/BF 0.2295; P/BF still 3.46 |
| `hr_rate_mult` | HR per PA (0.0345) | 1.856 -> 0.0367 |
| starter hook: `starter_short_start_prob`, `starter_shell_runs_start/_weight`, `starter_hook_add_pitches` | starter outs mean, <=9-out share, 15-out mass | outs-side only so far |

Held unless a residual demands them: `bb_rate_mult`, `inplay_hit_rate_mult`. The latter was rejected out of sample on 09-04.

**Out-of-fit checks** (never fitted, only guarded): starter H/BB/ER per start, runs per game, team K per game.

### Procedure

1. **Per-PA rates first, in causal order:** HBP, then mix + foul (K/BF and P/BF jointly; the mix is never moved alone), then HR.
2. **Then the starter hook**, against the new per-pitch economy.
3. **Two coordinate-descent passes**, because the hook feeds back into the rates via the order the lineup is cycled.
4. **Grids** are 3 values per lever: 100 sims for the grids, 200 for the final.
5. **The whole procedure, every target and every guard are written down BEFORE the first run**, as before. The validation set below is read ONCE.

Cost: ~6 levers x 3 values x 2 passes, ~36 configs at ~20 min each beside production. **About 12 h of replay**, plus the validation build.

### The blocker: fresh validation data

The 07-04..07-12 holdout has been read twice (starter sweep, joint re-fit). Selecting on it again would make it a tuning set.

A read-only audit of the roster builder found:
- **A leak-free rebuild of `roster_objs` for 05-28..06-14 is NOT possible as the code stands.** Season hitting/pitching (`statsapi.py:795,806`), splits (`:832,889`), arsenal (`:923`), game-log recency (`recency.py:21-63`) and every statcast artifact (`*_2026.json`) are season-to-date at REQUEST time. Only the active roster, BvP and bullpen availability are date-bounded.
- **The cheapest leak-free approximation:**
  - season stats via `byDateRange endDate=D-1`;
  - game logs filtered to `< D`;
  - statcast layers OFF;
  - BvP `end_date = D-1`;
  - the STORED pregame `lineups.json` / `probables.json` (on disk for 05-30..06-14);
  - a fresh cache.
- **Missing pieces:** bullpen availability is empty before 06-14 (no feed_live), and 05-28 / 05-29 are unusable.

| option | data | cost | caveat |
|---|---|---|---|
| **A. As-of rebuild** (recommended) | ~15 dates / ~200 games (05-30..06-14) | build a Syndicate-owned replay-input builder with date-bounded shims; production code is untouched | approximate inputs (statcast off) |
| B. Render export | 07-13..09-29 roster_objs, if Render's disk survives (~75 dates) | unsuspend web (billing) + the stream allowlist excludes roster_objs (code change) | billing decision; may be gone |
| C. Forward frozen sims | postseason from 10-03 (2-4 games/day) | free | far too small; postseason differs |

**Fidelity check before trusting A.** Rebuild with the leak-free builder for dates where REAL `roster_objs` exist (06-15..06-20), then compare:
- (i) profile fields, rebuilt vs stored;
- (ii) replayed starter/batting moments from rebuilt vs stored rosters.

Option A is admissible as validation only if (ii) agrees within MC noise on the moments the combined fit targets. Otherwise its levels differ, and a calibration validated on it says nothing about production.

### Ship rule (to be pre-registered with the targets)

SHIP the combined configuration only if every check holds on the fresh validation set:
- every fitted moment's |bias| is lower than production's;
- every out-of-fit check is within its guard:
  - per-start terms worsen by <= 0.10;
  - runs/game |gap| <= max(0.30, production's);
- the hitter-prop and HR calibrations are re-checked in the same pass, since the HR level changes.

Then a fleet ff, verified on the next sim. Otherwise nothing ships.
