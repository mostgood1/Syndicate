# NCAAF has the shared-seed mechanism but NOT the NFL's level problem: production's served level is on target

Lane `ncaaf-engine-level-seeds`, session 8062940b, 2026-11-18 (user: "Check NCAAF seeds"). Follows
`findings_2026-11-17_nfl_engine_level_2026.md` (the NFL engine ran 2.3 points a game low; seeds 1..100 read +1.9).
Diagnosis only: no engine, profile or fleet change. The fleet was only read: a read-only copy of the served NCAAF
projections and the truth files at 10:22 AM CST. Harness: `C:\tmp\ncaaf813\` (`ncaaf_p3.py`, `read_blocks.py`, `gate.json`,
`blocks_1_400.jsonl`, `fleet\`).

## Setup

- **Code:** the NCAAF generator seeds every game `range(1, 301)` (`generate_smartsim2_ncaaf_projections.py:1457`), the
  same pattern as the NFL's.
- **Inputs:** production's own per-week in-season blend index, from the fleet's `sp_ratings_inseason_blend_2026.json`.
  Each week's entry is written by the same run as that week's served CSV (generated_at within seconds), rounded to 4
  decimals.
- **Profile:** the promoted `ncaaf-goal-line-refit-1` (the repo's `data/calibration/ncaaf_profile.json`, the version
  every served row names).
- **Wrapper:** `simulate_game` is wrapped in the research process to record each seed's total. Nothing else changes.
- The harness #808 used for NCAAF (`C:\tmp\football_scenarios\ncaaf_work`, with its CFBD PPA cache) was deleted in the
  C:\tmp cleanup. This route needs no CFBD call.

## Reproduction gate

- 24 served games across weeks 4-11, seeds 1..300: 17 exact.
- **Weeks 4-5 reproduce 0 of 6.** They were served on 09-30 and 10-04, before the NCAAF total-level shrink went live:
  their `rating_source` has no `+level_shrink_0.5`, and the shrink landed 10-03 (`b4cda8272` / `77b35dff1`).
- **Weeks 6-11 reproduce 17 of 18;** the 18th differs by 0.01 (the artifact's 4-decimal rounding).
- So everything below uses weeks 6-11: **358 games**. On the full run, seeds 1..300 reproduce the served total on 343
  of 358; the rest differ by the rounding.

## Data coverage

- Served CSVs weeks 4-12. Weeks 4-11: 472 rows, all with a final in `games_2026.json.gz` (fleet, 11-18 00:32). Week 12
  is not played yet.
- Real FBS-vs-FBS 2026 regular-season mean total: 52.00 (632 games); the 358 games used: 51.65.

## Results

**Served level (production, seeds 1..300) minus the real total:**
- weeks 4-11: -0.70 [-2.35, +0.84] (n 472);
- weeks 6-11: -0.75 [-2.76, +1.26] (n 358).

**Level by 100-seed block, the same 358 games:**

| 1-100 | 101-200 | 201-300 | 301-400 | 1-300 (production) | 1-400 |
|---|---|---|---|---|---|
| 51.42 | 50.86 | 50.43 | 51.13 | 50.90 | 50.96 |

- **The mechanism is there:** the all-games mean moves with an SD of 6.27 points across seeds, against 0.70 if
  seeds were independent. About 23% of a seed's luck is shared by every game (NFL: 34%).
- **The offset is not:** the blocks agree within 1 SE (a 100-seed block's level SE is ~0.63; block SD 0.37).
  Production's seeds 1..300 sit 0.06 below the 400-seed level. Seeds 1..100 are +0.46 here, not the NFL's +1.9: the
  NCAAF profile consumes the random stream differently, so the same seed numbers carry different luck.

**Sim minus real, game bootstrap plus the shared-seed SE in quadrature:**

| seeds | sim - real | 95% CI |
|---|---|---|
| 1..300 (production) | -0.75 | [-2.76, +1.26] |
| 301..400 (disjoint) | -0.52 | [-2.67, +1.62] |
| 1..400 | -0.69 | [-2.65, +1.26] |

## Verdicts

- **H-SEED-NCAAF: the mechanism is TRUE, the effect is NEGLIGIBLE for production.** The across-seed SD is 9x the
  independent value (the falsifier's first condition fails), but the block levels agree within noise, and production's
  1..300 offset is -0.06.
- **H-LEVEL-NCAAF: FALSE.** Long-run minus real is -0.69 [-2.65, +1.26], so the CI contains 0.
- **H-NULL: half right.** The luck IS shared, but the level is on target.

## What it means

- No NCAAF fix is indicated. The promoted profile's level holds on 2026 games.
- The general rule from the NFL lane still applies to NCAAF research: a level read on 100 shared seeds carries about
  +-1.3 points of common noise (2 x 0.63) here. Paired arm-vs-arm differences are much less exposed.
- Other sports' engines (NBA, NHL, the basketball and hockey sims) were not checked; the lead stays open for them.
