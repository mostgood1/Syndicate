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

## NBA, WNBA, NHL and college basketball: a code survey (2026-11-18 11:16 AM CST, user "Check NBA and NHL")

The NFL / NCAAF offset needs one thing: every game in a run drawing from the same seed list. No production NBA / NHL
path does that, so nothing here needed a measurement. Read on main `434fc7f48`:

| path | how a game is seeded | shared across games? |
|---|---|---|
| NBA / WNBA pregame (`shared/basketball_props_smart_sim.py:6348` -> `basketball_engine/orchestrator/smart_sim.py:1183`) | `seed=None` -> `np.random.default_rng(None)`: fresh OS entropy per game | no |
| NBA live re-sim (`nba/live_resim.py:1622`, `:528`) | `stable_seed(event_id, last_seq)` (crc32) | no |
| college basketball pregame + live (`college_basketball/pregame_sim.py:238`, `ncaab/live_resim.py:624`) | `stable_seed(event_id, ...)` | no |
| NHL pregame (`nhl/sim_engine/hockeysim/projection.project_game`; market sim `adapters.py:148`) | the LEVEL is analytic (Poisson expected goals), no Monte Carlo; the market sim seeds `game_seed(date, game_pk)` | no |
| NHL live re-sim (`nhl/live_resim.py:661`) | `hash(game_pk)` per game (cross-process reproducibility depends on PYTHONHASHSEED for a str pk, a known caveat) | no |

**Level-fitting harnesses:** `scripts/nba_pregame_total_bias.py:64` seeds per game (`stable_seed(event_id, -1)`); the
NHL calibrations (`calibrate_nhl_block_rate.py:126,164`, `calibrate_nhl_special_teams_goal_mult.py:102,132`) give
every simulation its own seed from a `Random(seed)` stream; the WNBA rate fits are data fits, not sims. The one
shared-seed harness is `scripts/ab_basketball_sim_anchor.py` (`--seed 7` -> every game `default_rng(7)`), a PAIRED
anchor on/off A/B, where the common luck cancels; it sets no production level.

**Verdict:** the shared-seed offset is a smartsim2 property (NFL and NCAAF seed `range(1, N + 1)`). NBA / WNBA /
NHL / college basketball production levels cannot carry it. MLB and soccer were not part of this check.

## MLB and soccer (2026-11-18 1:07 PM CST, user "Check MLB and soccer"; lane `soccer-live-shared-seeds`)

| path | how a game is seeded | shared across games? |
|---|---|---|
| MLB pregame (`mlb/native/tools/daily_update.py:8205`, sims `GameConfig(rng_seed=seed + i)` at `:757` / `:4552`) | `args.seed + idx * 100000` per game in the slate, 1,000 sims each; `--seed` is a fixed 1337 for today's date (`default_fixed`), fresh for a future date | not within a slate; slot k reuses its block day to day, far below anything a season's level could show at 1,000 sims a game |
| MLB eval harness (`eval/eval_sim_day_vs_actual.py:2791`) | `seed + game_pk % 100000` | no |
| soccer pregame (`soccer/adapters.py:44`) | `crc32(league:match_id:date) % 1_000_000 + 1`, then `+ offset` per sim | no (two matches' blocks can overlap by chance, partially) |
| soccer market anchoring (`soccer/features/market_anchoring.py:259`) | `seed=1000 + index` per fixture, `+ offset` per sim: fixture blocks overlap almost entirely | YES, but OFF on the fleet: `SYNDICATE_SOCCER_MARKET_ANCHOR_WEIGHT` is absent from `local_production.env`, every `fleet_env/<role>.json` and `fleet_role_spec.json` (key names read only), so the weight is its default 0.0 |
| **soccer live re-sim (`scripts/poll_soccer_live_state.py:434`)** | `simulate_live_paths(...)` with NO seed, so `live_lens.py`'s default `seed=1`; 300 sims (`--simulations` default) | **YES: every live match on seeds 1..300** |

**Sizing the live one** (`C:\tmp\soccer813\soc_seeds.py`, `read_soc.py`): 60 synthetic matches (ratings uniform +-0.25,
cap 0.35), the EPL league profile the poller uses, `simulate_match`'s own per-seed loop, seeds 1..900, from kickoff (the
most play left, so an upper bound for remaining goals):
- all-matches mean SD across seeds **0.948 goals** vs **0.213** independent (4.4x); shared share **~0.33** (NFL 0.34, NCAAF 0.23);
- level by 300-seed block **3.012 / 3.065 / 3.029**; **seeds 1..300 minus the 900-seed mean -0.024 goals (-0.8%)**, SE ~0.045.

**Verdict: the mechanism is real, the offset is not.** The seeds the live poller uses happen to sit at the long-run
level. A different fixed 300-seed list could sit about +-0.11 goals (2 SE, ~3.6%) away, so the live default is safe by
the luck of the draw, not by design. Per-match seeding (as NFL part 2) would make it safe by design and make concurrent
live matches' errors independent. Not a level fix; optional.

**Survey closed: every sport checked.** Only smartsim2 (NFL, NCAAF) and the soccer live default share a seed list in
production. The NFL's is the one that moved a level (the fix loads in the 11-24 window); NCAAF's and soccer live's sit
within noise.
