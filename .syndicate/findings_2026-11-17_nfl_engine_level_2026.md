# The NFL engine runs about 2.3 points a game low in BOTH eras; the "2026-only" gap was a seed artifact

Lane `nfl-engine-level-2026`, session 8062940b, 2026-11-17 (user: "diagnose 813 part 3"). Todo `#813` part 3.
Diagnosis only: no engine, ratings or profile edit, nothing on the fleet changed (the only fleet action was a read-only
copy of `pbp_2025.csv`, `pbp_2026.csv` and `schedules_games.csv` at 8:56 PM CST). Harness and outputs:
`C:\tmp\nfl813p3\` (`p3.py`, `season_sd.py`, `analyze.py`, `blocks_read.py`, each with its `.log` / `.jsonl`).

## The question, as the ledger stated it

`#813` (2026-11-16): the pregame projector ran -2.24 [-4.58, -0.09] against 149 final 2026 games, while the #808 FIT
read on 2024-25 had the engine on target (regulation 45.84 vs the league's 45.62). So the miss was read as "the engine's
response to 2026's ratings". The same harness gave 45.95 on the 136 FIT games (seeds 1..100) and 44.12 on the 121
2026 wk1-8 games (seeds 1..1000), with the same code and profile.

## Data coverage (what every number below rests on)

- **FIT:** the same 136 games as #808 (every 4th completed 2024-25 REG game), ratings from the primary mirror's
  `pbp_2023/2024/2025.csv`, the files #808 read.
- **2026:** the same 121 games as #808's held-out (2026 wk1-8), ratings from the FLEET's `pbp_2025.csv` and `pbp_2026.csv`
  (copied 11-17 8:56 PM CST; 2026 has weeks 1-10, 18,447 offensive plays). #808's private 11-03 pull is deleted.
- **Outcomes:** the fleet's `schedules_games.csv` (11-16): 544 2024-25 games, 149 2026 games.
- **Seeds:** 1..100 (the #808 FIT and my first arms), 101..400 (disjoint), and for one neutral matchup 1..2000.

## The reproduction gate (run before any attribution)

- **FIT, 20 games at 100 seeds: exact.** Today's `build_projection` equals the 11-15 stored `total_mean` on 20 of 20.
  My seed loop on the rebuilt ratings equals `build_projection` on 20 of 20. So the code, the data and the rebuilt
  ratings are what that run used.
- **2026, 6 games at 1000 seeds:** my loop equals `build_projection` on 6 of 6, so the rebuilt ratings are exactly what
  the engine receives today. But `build_projection` equals the stored 11-15 value on only 1 of 6 (week 1, prior-only
  ratings). The other 5 differ by -0.49 to +0.53, because the fleet's `pbp_2026.csv` has changed since the 11-03 pull.
  Every 2026 arm below therefore runs on today's data, paired with its own baseline.

## Hypotheses (written in the lane before each test) and verdicts

- **H-DISP: FALSE.** 2026's ratings ARE narrower (offence SD 0.240 vs 0.301 across the games' rating slots; mean |sim
  margin| 4.19 vs 5.89). But re-simulated on the same seeds 1..100, the 2026 games read **45.86** against FIT's 45.95,
  a gap of -0.09 [-1.01, +0.84]. Rescaling 2026's per-component dispersion to FIT's moves the total -0.07 [-0.32,
  +0.18]. The level part moves +0.00 [-0.13, +0.15] and the difference part -0.10 [-0.34, +0.13]; the reverse is
  +0.07 [-0.17, +0.31].
- **H-RATE-FEATURE: FALSE.** Every rating set is centred (mean level components within +-0.03), and no swap moves the
  total.
- **H-PBP: FALSE.** Full-season offence SD by season: 2022 0.247, 2023 0.298, 2024 0.308, 2025 0.273, 2026 (wk1-10)
  0.263. Defence: 0.166 / 0.192 / 0.195 / 0.253 / 0.193. 2026 is inside 2022-25's range: offences really are more
  alike this year.
- **H-NONRATING: not needed.** With identical seeds, the two sets agree.
- **H-SEED (added after H-DISP failed, before its test): TRUE.**

## H-SEED: the measurement

`game_simulator.py:91` builds `Random(simulation_input.seed)` from the seed alone. So seed k draws the same stream in
every game, and part of its luck is common to every game in a run. The production generator runs seeds 1..300 for
every game (`SEEDS_PER_GAME = 300`); the #808 FIT ran seeds 1..100.

Level (mean projected total, default profile) by 100-seed block, same games:

| set | 1-100 | 101-200 | 201-300 | 301-400 | 101-400 |
|---|---|---|---|---|---|
| 2024-25 FIT, 136 games | **45.95** | 43.03 | 44.08 | 45.20 | **44.10** |
| 2026 wk1-8, 121 games | **45.86** | 42.50 | 43.85 | 45.17 | **43.84** |
| neutral (all ratings 0), 1 matchup | **46.15** | | | | 2,000-seed mean **44.02** |

- Seeds 1..100 are a lucky block, about +1.9 over the long run, in all three.
- The all-games mean moves with an SD of **6.86 points across seeds** (FIT; 2026 7.10), against 1.01 if seeds were
  independent. About 34% of a seed's luck is shared by every game (6.86^2 / 11.80^2).
- So a level read on N shared seeds has the noise of N draws, not of games x seeds: about +-1.4 points (2 SE) at
  N = 100, which is exactly the size of the "gap" that was being diagnosed.
- The neutral matchup's 100-seed blocks behave like independent draws (block SD 1.34 vs 1.25 iid).

## The real miss: the engine runs low in both eras

Sim on seeds 101..400 minus the real final total, per game, with the game bootstrap and the shared-seed SE in
quadrature:

| profile, games | n | sim - real | 95% CI |
|---|---|---|---|
| default, 2024-25 FIT | 136 | -2.35 | [-4.66, -0.04] |
| default, 2026 wk1-8 | 121 | -2.27 | [-5.05, +0.52] |
| **default, both** | **257** | **-2.31** | **[-4.21, -0.40]** |
| **v3 (loaded on the fleet 11-17), 2024-25 FIT** | 136 | **-2.83** | **[-5.11, -0.56]** |

- League targets: 2024-25 averaged 45.92 [44.82, 47.12] points with OT (544 games); 2026 46.17 [43.93, 48.64] (149).
- 2022-23 averaged 43.65, which is roughly where the engine sits now.
- Production's served level on seeds 1..300: FIT games 44.35, 2026 games 44.07, neutral 44.38. That is near the long
  run and agrees with the served 2026 wk1-10 file's 43.93.

## What this overturns

- **"The engine was on target on 2024-25 (45.84 vs 45.62)"** (#808 FIT read, cited in #813): a seeds-1..100 reading,
  +1.9 high.
- **"An engine-level miss on 2026 ratings"** (#813): it is the same miss on 2024-25. 2026's ratings are exonerated.
- **#808's level-sensitive FIT gates and its touchdown multiplier.** v3 (`h0.03`, `t0.825`) read 45.92 on FIT's
  seeds 1..100, against the league's 45.92. It reads **43.61** on seeds 101..400 (blocks 43.23 / 43.54 / 44.07), 0.49
  below the old default on the same seeds and games. The multiplier was chosen to bring an inflated reading down to
  the league, so the loaded profile runs about 2.8 points a game low.
  - Quarter SHARES and paired arm-vs-arm differences on the same seeds are much less exposed: the common luck cancels
    in a paired difference. Absolute quarter levels against the league's CIs are exposed.

## What it affects now

- **The NFL live re-sim** runs the same engine and profile: about -2.3 to -2.8 points a game of level. #813's replay
  measured the engine at -1.93 in Q4 alone on 65 games (independent seeds), which is part of this. Live totals and
  spreads stay off. The live moneyline is priced; how much a level miss moves a win probability was not measured here.
- **NFL pregame totals** (display; the generator's own comments say the model must not price) sit ~2.3-2.8 low against
  the league and the close.
- **The #780 width fit's k** absorbs part of this; re-fit after a level change.

## Fixes this points to (none made; each is the user's call)

1. **Re-fit #808's level on honest seeds:** disjoint seeds per game, or seeds per game keyed on the game id as the
   live re-sim now does (`ee47c930a`), or at least many seeds with the across-seed SD reported. The touchdown multiplier
   (or another level lever) re-chosen there would likely move back toward 1.0. Needs a fresh held-out: 2026 wk1-8 is
   spent; wk9 onward is clean.
2. **Seed the pregame generator per game** (`build_projection`'s `range(1, seeds + 1)`), as part (2) did for live. On
   300 seeds the served level's shared offset is small (+0.1 to +0.4 today), but every game in a slate shares its
   errors.
3. **Harness rule:** any level read from a shared seed list states the across-seed SD of the all-games mean, or uses
   disjoint seeds per game. Other sims seeded the same way (NCAAF smartsim2, the #808 NCAAF arms, other sports'
   harnesses) were not surveyed.

## Not measured

- The live re-sim's level on disjoint seeds (part 2's per-game seeds start after a sha256 offset, so production's live
  draws are now disjoint per game, but the level miss is in the engine).
- Why the engine sits at ~44: which rates (drive success, TD vs FG, pace) carry the 2.3 points. Out of this lane's scope.
- NCAAF.
