# NBA SmartSim minutes, part 2: the rotation-HISTORY path and a priced-starters variant (lane `nba-sim-minutes-history-path`, todo `#723`)

Side session of `local_c0ccc55a`. Continues `findings_2026-10-22_nba_sim_minutes_allocation.md` (lane
`nba-sim-minutes-allocation`, CLOSED). That lane measured the no-history DERIVE path on 10-21 and built
`SYNDICATE_NBA_SIM_MINUTES_PRICED_FIRST` (default off). Three things are owed on the slates after 10-21, and this file
holds two of them:

1. **The #723 CONFIRMATORY minutes reading.** Its rule is pre-registered in the other file (§5, `8301efcd`) and is read
   here UNCHANGED. Its verdict goes into that file's Results section and into todo `#723`.
2. **The history path** (this file, §1-§3). From a team's second regular-season game, its minutes come from
   `_rotation_sim_minutes_from_history_local`, which the switch does not touch.
3. **A priced-starters-only variant** of the switch (this file, §4). It is a NEW design and is pre-registered here before
   any post-10-21 box exists.

Times are US Central unless marked Z. Substrate: **fleet production files**, read-only
(`/home/amyn/syndicate-prod/data/nba_source/data/processed`). The fleet code is `6954cb0e`. The trace below is on
`origin/main` `3b2aec3c`. `git diff 6954cb0e 3b2aec3c` touches none of the traced functions.

**Written 2026-10-22 ~10:35-11:15 AM CT. No post-10-21 NBA box existed then.** The newest
`rotation_stints/player_checks_<D>.csv` on the fleet was 10-21, and 10-22's box lands ~6:45 AM CT 10-23.

## 1. Trace: how the history path sets a side's minutes

`B` = `syndicate/features/shared/basketball_props_smart_sim.py`,
`O` = `syndicate/features/basketball_engine/orchestrator/smart_sim.py`, `E` = `syndicate/features/basketball_engine/engine.py`.

```
orchestrator simulate_smart_game
  rot_date_str = the AS-OF date (D-1) in pregame mode                                         O:1523
  _rotation_sim_minutes_for_team(home_raw, ...)  (home_raw = props pool minus exclusions)      O:1525 -> B:2526
    pregame: no game id -> _rotation_sim_minutes_from_history_local                            B:2550 -> B:2279
      stints = rotation_stints_history, this team, 28 days, date < cutoff (D-1)                B:2310-2339
      NBA same-phase filter; nothing left -> "no_recent_history" (-> DERIVE path)              B:2345-2362
      ESPN id map: player_checks_<d>.csv, d <= cutoff, 120 days                                B:2364 -> B:_espn_name_to_id_map_for_game_local
      pool player -> ESPN id by _norm_player_key                                               B:2375-2378
      per-id stint minutes, scaled so the team's whole history sums to 240                    B:2390-2403
      MAPPED:   each pool player with stint minutes gets that share                            B:2412-2427
      LEFTOVER: 240 - mapped (minutes of history players NOT in today's pool: excluded today,
                traded, unmapped), spread over EVERY pool player by roll-minutes weights         B:2429-2436
      rescale to 240                                                                            B:2438-2440
      BLEND:    (1 - b) x minutes + b x roll minutes scaled to 240                             B:2443 -> O:750-783
                b = 0.10 + 0.18 x exp_cov + 0.10 x max(0, 0.75 - mapped_frac) / 0.75, clipped [0.08, 0.35]
                (NBA: exp_min_mean is absent, so exp_cov = 0 and b = 0.10 when mapped_frac >= 0.75)
      CAPS:     per-player cap, excess redistributed                                           B:2451-2452 -> O:664, O:1067
      SIGNAL GUARD: a core player (scaled roll >= 24, or starter >= 0.75 and >= 20) below 45% of
                his roll -> REFUSED -> DERIVE path                                              B:2454-2464 -> O:803-842
      SPARSE GUARD: < 5 mapped ids, mapped_frac < 0.50 or < 5 pool lineups -> REFUSED           B:2504-2518
      LINEUP POOL: history 5-man units whose 5 players ALL map into the pool                   B:2466-2492
  _apply_player_priors(sim_minutes = rot_min) -> the engine frame's _sim_min                    O:1544
  served players[].min_mean = the same rot_min                                                  O:2205-2227, O:2003
  engine: ordinary possessions draw a unit from the lineup pool (weights = stint seconds);
          context windows (opening/bench stints, closing, crunch, blowout) sample by weights
          built from _sim_min                                                                    E:957, E:1661-1738
  calibration: served mean = min_mean x shrunk per-minute rate (+ own-average blend)            nba_prop_calibration.py:88-90, :409
```

**What the trace says about DNP minutes on this path.** A pool player who did not play today can carry sim minutes
from three places:
- **MAPPED:** he played in the 28-day window but not today (a garbage-time cameo, or injured since).
- **LEFTOVER:** history minutes of players missing from today's pool, spread by last-season/roll weights over everyone,
  zero-stint players included.
- **BLEND:** 10% of his roll base scaled to 240. That is the only source for a zero-stint player when leftover is 0.

Caps then move a little more. A zero-stint pool player is in NO pool lineup (B:2479-2489), so the engine only plays
him in context windows. The calibration reads `min_mean` either way.

**The opposite failure lives here too.** A player returning from injury, or one who was not in the window, has zero
stint minutes. If he plays today, the history path gives him only the blend share.

### Mechanics seen before any box (truth-free, 10-22 / 10-23 production sims)

| sim | side | path | mapped ids | mapped_frac | leftover | blend b | pool lineups |
|---|---|---|---|---|---|---|---|
| 10-22 OKC_DEN (built 7:40 AM CT 10-22) | OKC | HISTORY | 13 | 1.00 | 0.0 | 0.10 | 31 |
| | DEN | derive (`no_recent_history`) | | | | | |
| 10-22 PHI_CLE | PHI | derive (signal guard) | | | | | |
| | CLE | derive (`no_recent_history`) | | | | | |
| 10-23 BOS_NYK (D-1 build, 12:01 AM CT 10-22) | BOS | HISTORY | 11 of 14 pool | 1.00 | 0.0 | 0.10 | 26 |
| | NYK | HISTORY | 10 | 1.00 | 0.0 | 0.10 | 23 |
| 10-23 SAS_HOU | SAS | HISTORY | 14 | 1.00 | 0.0 | 0.10 | 29 |
| 10-23 MIA_DET | DET | derive (signal guard) | | | | | |

- **The leftover is 0 on all 4 history sides seen.** Every player who played in the window is in today's pool.
- The OKC frame's `_sim_min` is close to game 1's minutes. Stirtz and Barnhizer (1 min each in game 1) hold 0.80.
- BOS's 3 zero-stint pool players hold only the blend: Conley 1.80, Harper Jr. 1.42, A. Williams 0.51.
- The 10-23 builds are D-1 builds. The game-day rebuild replaces them before the tip freeze.

## 2. PRE-REGISTERED (H): the history-path reading, before any post-10-21 box

**Population.**
- Production sides built before their tip, on every final slate from 10-22 to the last slate whose box has landed when
  the reading runs (target 10-27).
- Split by `rotation_minutes.<side>.applied`. **HISTORY** = applied. **DERIVE** = not applied, with the refusal reason
  reported (`no_recent_history` / signal guard / sparse / other).
- Sides with no box, or built after the tip, are dropped and listed.

**Measures** (served `min_mean` against `player_checks` box minutes, with the box `starter` flag, exactly as
`audit_side` computes them for #723):
- For each path, per side and pooled: DNP sim minutes per side, box-starter bias, bench bias, outside-pool box minutes
  per side, and played-player MAE. Pooled values get a 95% cluster bootstrap over sides (10,000 resamples, seed 7).
- **Decomposition of the HISTORY sides' DNP sim minutes**, by replaying the REAL `_rotation_sim_minutes_from_history_local`
  on each frozen `engine_inputs` frame with spies on the module view. For each pool player:
  - MAPPED = (1-b) x r x his stint share;
  - LEFTOVER = (1-b) x r x his leftover share;
  - BLEND = b x his scaled roll base;
  - CAPS = final - (the sum of the three).
  - Here r is the rescale at B:2438 (1.0 when mapped + leftover = 240).
  - A side whose replayed final minutes differ from the frame's `_sim_min` by more than 0.05 min is dropped from the
    decomposition and listed. It stays in the descriptive table.
- **Returning players:** zero-stint HISTORY pool players who PLAYED. Report n, their mean bias, and the list.

**Predictions, written before any box:**
- **P1.** History DNP sim mass per side is well below derive's: a point estimate < 10 min/side, against derive >= 25.
- **P2.** The LEFTOVER part is about 0 on most history sides (it is 0 on 4/4 above). What DNP mass there is comes from
  BLEND (zero-stint players) and MAPPED (players who played in the window but not today).
- **P3.** Zero-stint pool players who DO play are badly under-allocated: about 10% of a scaled roll base, 0.5-2 min.

**Gate: what this lane builds from the reading.**
- **G-LEFTOVER.** The LEFTOVER part of history DNP mass is >= 5 min/side with CI lower > 0. Then a DEFAULT-OFF fix
  is built: spread the leftover only over pool players with stint minutes or a posted prop line.
  - It is pre-registered in its own entry before its arm is compared with a box.
  - Development is read on these slates. The confirmatory reading is owed on later slates.
- **G-OTHER.** Total history DNP mass has CI lower >= 10 min/side, but LEFTOVER < 5. The dominant part is named. Its fix
  is designed after this reading as a NEW pre-registered entry, not built blind.
- **G-BIAS.** The history starter or bench bias has a CI that excludes 0 and |mean| >= 2 min. It is named and treated
  like G-OTHER.
- **NO-GO.** History DNP mass has median < 10 min/side and its CI upper < 15, AND starter bias is within +-2 min with a
  CI covering 0. Then there is no history-path minutes fix, and that is recorded.
- **P3 does not gate.** A fix for returning players changes who gets minutes, not where DNP minutes go. It is a separate
  design with its own pre-registration.

## 3. The #723 CONFIRMATORY reading (rule: `findings_2026-10-22_nba_sim_minutes_allocation.md` §5, unchanged)

```
python scripts/nba_sim_minutes_audit.py --replay --processed /home/amyn/syndicate-prod/data/nba_source/data/processed \
    --dates <every final slate after 10-21> --min-rows 150
```

- History-path sides drop out of that replay by its own rule (OFF must be the derive path).
- So the confirmatory population is the derive sides only:
  - opening-week teams;
  - the second team of a back-to-back opener;
  - signal-guard and sparse refusals.
- With 2-6 derive sides per slate after 10-23, reaching 150 played rows may take the whole window. Below 150 the verdict
  is INCONCLUSIVE with its count, as registered.

## 4. PRE-REGISTERED (V-S): priced STARTERS first, a variant of the #723 switch, before any post-10-21 box

**Why a variant.** The 10-21 development scratch arms showed the registered design over-protecting PRICED BENCH players
(bias -0.34 -> +4.71 min). Their last-season base is left whole while the unpriced absorb the excess. Priced starters
gained the most (-6.01 -> -1.05). This variant protects only the priced STARTERS.

- 10-21 is its design source, so **V-S is never read on 10-21**. It is read only on the confirmatory slates (> 10-21),
  beside the registered design.
- The registered design keeps its own rule and verdict. Nothing about V-S changes them.

**Design (no fitted constant).**
- **Protected set:** pool players who are priced (the registered design's set: a posted player-prop line on the team's
  game, matched by `normalize_player_name_key`) AND have `_starter_signal(team_df) >= 0.55`.
  - `_starter_signal` is the engine's own starter signal: the explicit `starter_prob` / `is_starter`, topped up to 5 by the
    minutes-signal ramp when fewer than 5 are explicit (O:570-591).
  - 0.55 is the threshold the engine already uses for "starter" (O:1040, O:712).
- **Fill:** `_priced_first_fill_local(base, priced = protected)`. The excess over 240 comes off the unprotected players
  first, by the same equal subtraction. Only then does it come off the protected ones.
- **Gate:** identical to the registered design. It acts on the NBA derive path only, when the base sums over 240 and
  >= 5 pool players are priced. With no protected player the fill equals the water-fill, so it does not engage.
- **Switch:** `SYNDICATE_NBA_SIM_MINUTES_PRICED_FIRST_SET`.
  - Absent or `priced` = the registered design. `priced_starters` = V-S.
  - It is read only when `SYNDICATE_NBA_SIM_MINUTES_PRICED_FIRST` is `shadow` or `on`.
  - With the main switch absent or off, nothing changes.
- **Classification (standard §4.4):** an ESTIMATOR change, the same as the registered design. The same downstream re-fit
  checks apply before any `on`: the k width, the book-blend weight, and a reuse stamp.

**Arms.**
- **OFF:** production's own frame `_sim_min`, replayed, with #723's drop rules (history path, or max deviation > 0.05).
- **ON:** the registered design.
- **VAR:** the same call with the main switch `on` and the set switch at `priced_starters`. The priced set is rebuilt
  from props snapshots no later than the pkl's `written_at`, as for ON.

**PRIMARY-V (minutes).**
- Population: VAR-engaged sides (VAR differs from OFF); pool players who played.
- Statistic: paired |VAR - actual| - |OFF - actual|, cluster bootstrap over sides (10,000 resamples, seed 7).
- **PASS:** CI upper < 0. **FAIL:** CI lower > 0. Otherwise INCONCLUSIVE, and INCONCLUSIVE below 150 rows.

**HEAD-TO-HEAD** (decides which design is proposed if both pass).
- Statistic: paired |VAR - actual| - |ON - actual|, over pool players who played on sides where both engage. Same
  bootstrap.
- VAR is preferred only if its CI upper < 0. Otherwise the registered design keeps precedence, since it was registered
  first.

**Before V-S is proposed:** the #723 SECONDARY points statistic, read on scratch worker arms (OFF vs VAR) of a
confirmatory slate, must not FAIL.

**Reported, not gating.**
- Bias OFF / ON / VAR for priced starters, priced bench and unpriced players.
- DNP sim minutes per engaged side.

**Prediction, written before any box.**
- VAR keeps most of ON's starter gain.
- It takes priced bench players back to roughly OFF's bias.
- Unpriced players who played lose more than under OFF and less than under ON.
- The head-to-head sign is not predicted.

## Results

(appended below this line, never above it)
