# NCAAF live re-sim: a margin-aware end-game, #858's v4 (todo #859, lane `ncaaf-margin-aware-endgame`, 2026-11-20)

The user said "Start v4 here" after #858's verdict (`findings_2026-11-20_ncaaf_endgame_clock.md`). #808's clock fixes
one-score last-2:00 scoring, but adds +0.7 to +0.9 late points at every margin, so it fails the blowout and overall
gates. This lane tests, in the research harness only, whether margin-aware urgency rules let the clock pass. The
harness patches `situation_model.classify_urgency` and `drive_simulator.classify_urgency` inside its own worker
processes; nothing in the repo changes. An engine build needs a loan, asked only on a pass. Kit: `C:\tmp\t859` + the
#852 harness.

## Measured first (CFBD 2023-24 FBS-vs-FBS; `real_late_roles.py`, `real_late_roles.txt`)

**Q4 possession length (6,840 drives starting 15:00-2:00): T = 159 s.**
- Leaders: 162 / 165 / 184 / 196 s at 1-8 / 9-16 / 17-24 / 25+.
- Trailers: 147 / 137 / 137 / 167 s.

**From each game's Q4 6:00 state:**

| \|margin\| | games | leader pts | trailer pts | leader s/snap 6:00-2:00 | trailer s/snap | leader pass share | trailer pass share |
|---|---|---|---|---|---|---|---|
| 1-8 | 465 | 2.93 | 3.57 | 22.2 | 15.7 | 0.32 | 0.64 |
| 9-16 | 373 | 3.11 | 3.62 | 20.2 | 13.2 | 0.15 | 0.75 |
| 17-24 | 257 | 2.81 | 2.81 | 24.1 | 13.6 | 0.11 | 0.67 |
| 25+ | 335 | 1.77 | 2.24 | 23.4 | **19.0** | 0.14 | **0.47** |

**Real trailers "beyond reach" STILL hurry.** Reach here means deficit > 8 x (1 + floor(seconds / 2T)): pass share 0.67
and 13.9 s a snap, against 0.67 and 12.6 s within reach. They ease only at **25+**. So the rule as first framed
("concede beyond reach") would contradict real teams at 9-24. The rules below use what the data shows.

**Engine against real on the harness's own Q4 6:00 states** (150 games, small cells), leader / trailer rest points as
`base` | `clk_to` | real:
- 1-8: leader 3.71 | 4.37 | 4.17; **trailer 3.86 | 4.31 | 5.79**.
- 17-24: leader 4.37 | 4.14 | 3.76; trailer 2.36 | 2.59 | 1.71.
- 25+: **leader 3.54 | 4.07 | 2.32; trailer 1.91 | 2.17 | 0.86**.

## PRE-REGISTRATION — written 2026-11-20 before any v4 arm was run

**The rules (harness patch, regulation Q4 only, never overtime):**
- **(a) CONCEDE:** a trailer down **25 or more** is not in `trailing_urgency` or the two-minute drill. It plays
  `neutral_offense`.
- **(b) RUN-OUT:** a leader up **17 or more** in `neutral_offense` plays `four_minute_offense` (clock_base 0.26, gain
  +0.08, fewer incompletions and sacks) at any Q4 clock. Today that mode starts only at 4:00. The 150 s end-game
  preservation and the #808 kneel-out still come first.
- **Thresholds:** 25 is where real trailers change (pass 0.47 and 19 s a snap at 25+, against 0.67-0.75 and 13-16 s
  below). 17 matches the damping's threshold and the leaders' pass share (0.11-0.15 from 9+).

**Arms**, the #852 / #858 harness: the first 150 games of the 2024 every-2nd list, Q4 15:00 / 10:00 / 6:00 / 3:00, 60
sims, paired. Each arm is on top of `clk_to` (damping 1.0 / 17 / 14 + college OT + #808's seven switches + real CFBD
timeouts):
- `v4a` = `clk_to` + (a);
- `v4ab` = `clk_to` + (a) + (b).

**Gates, #858's against `base`** (damping + OT, no clock):
- **G1:** one-score last-2:00 points inside the real CI [2.55, 4.71]; one-score log loss at Q4 3:00 not above
  `base`'s. (#858's snaps clause is reported, not gating here. These rules do not act on one-score games, so it cannot
  change.)
- **G2:** 17+ log loss (Q4 15:00-6:00) not worse than `base`'s by more than 1 paired SE.
- **G3:** overall log loss (Q4 15:00-6:00) not above `base`'s.

**The H-REACH falsification:** (a) + (b) must move the 17+ rest by at least half of the clock's +0.7 there, i.e.
-0.35 or more against `clk_to`.

**Predictions.**
- `v4ab` vs `clk_to` at 17+: rest -0.3 to -0.8 at Q4 15:00 (mostly the 25+ trailer under (a), and the leader under
  (b)).
- One-score unchanged within 0.05.
- **G2 borderline:** the 25+ leader's over-scoring is a per-play rate the modes do not reach (H-RATE).
- `v4a` alone moves only the trailer.

**Scope.** Harness only. On a pass, the build is two default-off `CalibrationProfile` fields in `situation_model` /
`drive_simulator` on a loan from `football-scenario-calibration`, plus the live timeouts feed (the NFL pattern). Both
need the user's yes. On a fail, the stated reason not to.

## RESULTS (written after the runs; nothing above was changed)

### Verdict: H-REACH TRUE. Both arms pass G1-G3. The simpler `v4a` (concede only) scores at least as well as `v4ab`.

`C:\tmp\t859\c859_read.py`, `c859_read_saved.txt`. 150 paired games, against `base` (damping + college OT, no clock):

| | `clk_to` (#858) | **`v4a`** | `v4ab` |
|---|---|---|---|
| G1: one-score last-2:00 points (real 3.58 [2.55, 4.71]) | 3.23 | **3.19** in | 3.21 in |
| G1: one-score log loss, Q4 3:00 | -0.0132 (0.0462) | -0.0132 (0.0462) | -0.0132 (0.0462) |
| G2: 17+ log loss, Q4 15:00-6:00 | +0.0307 (0.0123) FAIL | **-0.0279 (0.0189)** PASS | -0.0153 (0.0268) PASS |
| G3: overall log loss, Q4 15:00-6:00 | +0.0141 (0.0098) FAIL | **-0.0099 (0.0114)** PASS | -0.0037 (0.0136) PASS |
| H-REACH: 17+ rest vs `clk_to`, Q4 15:00 (needs <= -0.35) | | -1.66 (0.13) | -2.74 (0.15) |
| overall slope / rest engine-over-actual | 0.66 / 1.065 | **0.70 / 0.994** | 0.66 / 0.969 |

**`v4a` minus `base` rest, Q4 15:00 / 10:00 / 6:00 / 3:00 by margin, and [`v4a` engine minus actual]:**
- 0-8: +0.83 [-0.22] / +0.97 [+0.06] / +1.22 [-0.91] / +1.02 [-0.47].
- 9-16: +0.55 [-0.77] / +0.68 [-1.19] / +0.73 [+0.78] / +0.16 [-1.44].
- 17-24: -0.56 [-1.34] / -0.23 [-0.49] / -0.72 [+0.53] / -0.35 [+0.54].
- 25+: -1.23 [+0.42] / -1.45 [+0.98] / -1.31 [+0.96] / -0.36 [+0.33].
- For comparison, `base` 25+ was +1.64 / +2.43 / +2.27 / +0.69.

**Reading.**
- The clock still delivers the one-score last two minutes, and the concede rule takes back the blowout cost. A
  trailer down 25+ no longer hurries, so both sides of a rout score less.
- `v4ab`'s run-out over-corrects 17-24: engine minus actual -2.53 at Q4 15:00, against -0.78 for `base`.
- **Prediction misses, reported:**
  - the 17+ move -0.3 to -0.8 was far too small (-1.66 / -2.74);
  - "G2 borderline" was wrong (clear passes);
  - H-RATE is weaker than feared.
- **Prediction held:** one-score unchanged within 0.05 (`v4ab` vs `clk_to` -0.05 at Q4 15:00).
- **Not shown:** that `v4a` beats `base` beyond noise anywhere. Every passing reading is "not worse" with a
  better-signed point estimate.

### What a build would be (the user's call; it needs two loans)

1. **Engine (loan from `football-scenario-calibration`).** A `CalibrationProfile` field, `trailing_concede_deficit`
   (default None = off, byte-identical). In regulation Q4, a trailer down that much leaves `trailing_urgency` / the
   two-minute drill for `neutral_offense` (`situation_model.classify_urgency`, with its call sites taking the profile
   value). Plus its `to_dict` entry and tests: off byte-identical to pinned digests, on reachable.
2. **Live (loan from `live-player-exit-gate`).**
   - ESPN `situation.homeTimeouts` / `awayTimeouts` into `NcaafLiveGameState` and the re-sim's
     `initial_timeouts_*` (the NFL pattern). It is needed because the timeouts matter: +0.46, se 0.19.
   - One live switch that arms the end-game set for the NCAAF live re-sim: #808's seven switches + the concede rule +
     #855's college overtime, on top of #852's damping.
3. **Re-fit and hold-out.**
   - #852's damping (1.0 / 17) was fitted without the clock and v4. A joint re-read of its shape is owed.
   - The 2026 ledger cannot carry timeouts. So the out-of-sample test is live shadow readings after the wiring, or an
     ESPN-timeouts backfill of 11-21 / 11-28.
4. **Loading:** a betting change, a window only, after #852 / #835's own 12-08 decision.

## BUILD — 2026-11-21, on the user's "Build both"; PUSHED on the user's "Push it"

Code: main `b2ff241ae` (pushed 2026-11-21 11:04 AM CST; the same tree as the tested `c8cc6c1dd`, rebased over two ledger-only
commits). Default OFF everywhere. It reaches the fleet at its next fast-forward, still off: that load is not a
betting change. Setting the switch is.

1. **Engine** (loan from `football-scenario-calibration`; `play_state.py` is this lane's own claim).
   - `CalibrationProfile.trailing_concede_deficit: int | None = None`, and its `to_dict` entry.
   - `situation_model.classify_urgency(..., concede_deficit=None)`. In regulation Q4, a trailer down that much or
     more returns `neutral_offense` before every other rule. That means no `trailing_urgency` and no two-minute drill.
     The first half, overtime and the leader are untouched. `classify_situation` reads the value off the play state.
   - `PlayState.trailing_concede_deficit` is a rule switch, not game state, so it is not in `to_dict`. It is passed
     through `build_play_state_from_possession_state(..., trailing_concede_deficit=)`.
   - `drive_simulator` takes the profile value at three places:
     - the five play-state builds;
     - the drive's urgency call;
     - the end-of-half clock's mode call.
2. **Live** (loan from `live-player-exit-gate` for `ncaaf/live_resim.py`).
   - `NcaafLiveGameState.home_timeouts` / `away_timeouts` come from ESPN `situation.homeTimeouts` / `awayTimeouts`.
     The rule is NFL's: 0..3, otherwise None, never clamped. They feed `initial_timeouts_*` only when the feed said.
   - `syndicate/features/ncaaf/live_endgame.py` adds `SYNDICATE_NCAAF_LIVE_ENDGAME`, which only an explicit on value
     arms. It sets:
     - #808's seven clock switches;
     - `trailing_concede_deficit`, from `..._CONCEDE_DEFICIT`. The default is 25, and a bad value falls back to 25,
       never to "no concession";
     - `college_overtime`.

     `resim_live_game` applies it after #852's damping, on the no-profile path. The tick, #835's E0 and the
     cutoff-replay harness all take that path.
   - The result carries `endgame`: {on, concede_deficit, end_of_half_clock, college_overtime, timeouts_fed}.
     `NCAAF_LIVE_ENDGAME on ...` is printed once per process.
   - **With both switches on and the timeouts fed, the live re-sim runs exactly `v4a`.**

### Checks (all `py -3.11`)
- **OFF is byte-identical.** sha256 over 20 seeds of `simulate_game(...).to_dict()` was pinned on the pre-change
  code. It is identical afterwards for 5 inputs:
  - NCAAF pregame;
  - NCAAF tied at Q4 0:20;
  - NCAAF 7-35 at Q4 5:00, with and without the seven clock switches;
  - NFL 7-35 at Q4 5:00 with them.
- **ON is reachable.** The 7-35 state changes, with and without the clock. A 21-24 state at Q4 1:00 does not.
- **The built rule equals the harness patch `v4a`.** On 12 of 12 real 2024 Q4 states with a 17+ margin the draws are
  identical (`C:\tmp\t859\verify_engine.py`). So the RESULTS above are readings of this code.
- **Live, switch absent, off or unrecognised:** byte-identical through `resim_live_game` and the worker's tick,
  whether or not ESPN's timeouts are fed.
- **Live, switch on:**
  - it changes the published lane;
  - the tick carries ESPN's (1, 3) to the engine input;
  - with #852 also on, the profile is `v4a`'s;
  - the kickoff path (#835 E0) sees the same engine;
  - an explicit `profile=` is honoured as given;
  - on the same seeds and clock (200 sims), conceding at 25 gives a lower total than conceding at 60.
- **Tests:** `test_smartsim2_trailing_concede.py` 17 pass, `test_ncaaf_live_endgame.py` 48 pass. Neighbouring
  suites: 721 pass in 50 files (smartsim2, football engine, NCAAF live, NFL live re-sim).
- **`football_sim_input_checklist.py`:** 4 alarms. All are payload population read from this worktree, which has no
  `data/`. They are unchanged by this build, and the checklist does not enumerate profile fields.

### Still owed before any load
- **A joint re-read of #852's damping shape with the end game on.** 1.0 / 17 was fitted without it.
- **A hold-out with real timeouts.** What is verified so far:
  - ESPN's core API carries `situation.homeTimeouts` for a completed 11-14 game (401856859 -> 1 / 0).
  - **Not yet verified:** that the scoreboard row the poller keeps carries them on a LIVE college game. The fleet's
    `live_state_<date>.json` keeps only the day's last snapshot, so it cannot answer this.
  - If the keys are absent, the engine falls back to 3 each. The block shows `timeouts_fed: false`, which is the
    `clk_3` arm, not `v4a`.
- **It is a betting change.** Load it in a window only, on the user's yes, after #852 / #835's 12-08 decision.

## JOINT RE-READ OF #852's DAMPING WITH THE END GAME ON — PRE-REGISTRATION, written 2026-11-21 12:07 PM CST before any arm was run

User "Yes, run it" (2026-11-21), answering "Run the joint damping re-read on 2024 here next?". This is the re-fit the
standard requires (`model_engine_standard.md`: adding a mechanism to a calibrated engine requires re-fitting the rates
that were absorbing it). #852's damping, 1.0 / 17 / 14, was fitted without the clock or the concession.

**Population.** The same as #858 / #859. That is the first 150 games of `C:\tmp\t852\tasks_2024.json` (the 2024
every-2nd list): Q4 15:00 / 10:00 / 6:00 / 3:00 real CFBD states, 60 sims a state on its own seed block, paired across
arms, with the real CFBD timeouts fed. The engine is the SHIPPED code (main `b2ff241ae`, this worktree): the concession
is the profile field `trailing_concede_deficit = 25`, not the harness patch. The runner, `C:\tmp\t859\joint_run.py`,
imports `C:\tmp\t852\resume.py` unchanged (the pinned slate runner imports it too) and adds these arms at import.

**Arms.** All are `v4a` = #808's seven switches + `college_overtime` + concede at 25 + real timeouts, varying only #852's
damping (strength / lead threshold / lead span):
- **incumbent `jd1.0_t17_s14`** (1.0 / 17 / 14), which is `v4a` itself;
- **shape grid** (#858's grid, at strength 1.0): `jd1.0_t14_s7`, `jd1.0_t14_s14`, `jd1.0_t17_s7`, `jd1.0_t21_s7`,
  `jd1.0_t21_s14`;
- **no damping** `jd0.0_t17_s14` (strength 0, an exact no-op): is the damping still needed with the end game on?

**A reproduction check first (not a gate on the science, a gate on the instrument).** The incumbent under the built rule
must equal the harness arm `out_2024L_v4a_60.jsonl` on every one of the 600 states (150 games x 4). If any differ, the
read stops and the difference is reported.

**Selection (the same rule as #852 and #858).** The incumbent is compared with each of the 6 alternatives on overall
common-line log loss at Q4 15:00-6:00, against the real final. Lines come from `calib_arms.py`, with the incumbent's
file first, and the SE is the paired, game-clustered SE. Move off the incumbent only if an alternative improves by more
than 1 paired SE; among those, take the best. Then re-read the pick against `base` (`snap_L_c858_base.jsonl`) on:
- G1: one-score last-2:00 points inside the real [2.55, 4.71]; one-score log loss at Q4 3:00 not above `base`'s;
- G2: 17+ log loss at Q4 15:00-6:00 not worse than `base`'s by more than 1 paired SE;
- G3: overall log loss not above `base`'s.

**Predictions.**
- Reproduction: 600 of 600 identical.
- The shape grid spans within +-0.006 of the incumbent overall (#858's spanned +-0.004), and no shape cell clears 1
  paired SE. **Keep 1.0 / 17 / 14.**
- No damping is worse than the incumbent overall, by more than 1 paired SE. At 17+, its rest engine/actual rises from
  v4a's 1.046 to 1.10-1.20 (the concession slows the trailer; the leader's surplus is the damping's job).

**What follows.**
- If the incumbent is kept: the damping needs no change for the end game, and this item of "Still owed" is closed.
- If a cell is picked: the live default would change. That is a separate betting change, put to the user with the
  re-read G1-G3. Nothing in the repo changes in this read.
- The real-timeouts hold-out stays owed either way.

### AMENDMENT 1 — written 2026-11-21 12:24 PM CST, after the runs and BEFORE any science number was read

**The registered instrument check failed as written.** Of 600 states, 215 were identical and 385 differed, so the scorer
stopped as registered (`C:\tmp\t859\joint\joint_read.txt`). The diagnosis (`C:\tmp\t859\joint_diag.py`):
- **What differs:** ONLY the `sd` key. On all 600 states, `dist` (the draws), `rest` and every other key are identical.
  `max |sd diff|` = 5.3e-15.
- **Why:** `sd` is a float `sum()` (`resume.py` line 236). `v4a` ran on 11-20 under the bare Python 3.12 that `py -3`
  had become (its log's traceback paths are `Python312`), and this run used 3.11. Python 3.12's `sum()` of floats is
  compensated, so the last bits differ. No scorer reads `sd` (`calib_arms.py`, `paired_margin.py`, `joint_read.py`).
- **Amended check:** every sim key except `sd` identical, and `sd` within 1e-9. The rest of the registration is
  unchanged.

### JOINT RE-READ RESULTS — written 2026-11-21 12:26 PM CST, after the runs (nothing above was changed)

`C:\tmp\t859\joint_read.py` produced `C:\tmp\t859\joint\joint_read.txt`. Runs are `C:\tmp\t859\joint\out_2024L_<arm>_60.jsonl`,
each arm about 2 minutes on 2 Idle workers. Population: the same 150 paired 2024 games, Q4 states, 60 sims.

**Instrument (amendment 1):** the built rule matches the harness `v4a` on **600 of 600** states.

**Selection.** Overall log loss at Q4 15:00-6:00, against the incumbent `jd1.0_t17_s14` (= `v4a`), with se:

| strength / threshold / span | overall | one-score (73) | 17+ (69) | 17+ rest engine/actual |
|---|---|---|---|---|
| 1.0 / 17 / 14 (incumbent) | 0 | 0 | 0 | 1.046 |
| 1.0 / 14 / 7 | +0.0062 (0.0038) | +0.0050 | +0.0125 | 0.997 |
| 1.0 / 14 / 14 | +0.0052 (0.0026) | +0.0022 | +0.0104 | 1.024 |
| 1.0 / 17 / 7 | +0.0039 (0.0023) | +0.0005 | +0.0096 | 1.018 |
| **1.0 / 21 / 7 (PICK, 1.6 SE)** | **-0.0021 (0.0013)** | -0.0018 (0.0008) | -0.0029 (0.0028) | 1.047 |
| 1.0 / 21 / 14 | -0.0013 (0.0024) | -0.0018 | -0.0025 | 1.080 |
| 0.0 (no damping) | +0.0156 (0.0092) | -0.0021 | +0.0379 (0.0219) | 1.197 |

**The pick is 1.0 / 21 / 7, the same cell #858 picked with the clock alone** (-0.0022, se 0.0012 there). Two reads
on different engines land on the same shape. But the margin over the incumbent is small, 1.6 paired SE, with 6
alternatives tried.

**The pick against `base`** (G1-G3 as registered):
- **G1:**
  - one-score last-2:00 points are **3.20, inside** [2.55, 4.71] (`base` 2.31, outside);
  - one-score log loss at Q4 3:00 is -0.0132 (se 0.0462), not above `base`. **PASS**
- **G2:** 17+ at Q4 15:00-6:00 is **-0.0333 (se 0.0191)**. **PASS**
- **G3:** overall at Q4 15:00-6:00 is **-0.0127 (se 0.0114)**, slope 0.71 vs 0.71, rest ratio 0.995. **PASS**
- **Not gated, for the record:**
  - one-score at Q4 15:00-6:00 is +0.0067 (se 0.0169);
  - 17+ at Q4 3:00 is +0.0333 (se 0.0473).

  Both are inside noise.

**Damping is still needed with the end game on.** Without it, against the incumbent at Q4 15:00:
- the rest-of-game total moves +2.29 (se 0.23) at 25+ and +0.65 (0.17) at 17-24;
- the shift is all the leader's (+2.30 / -0.01 at 25+).

So the concession fixes the trailer and the damping fixes the leader.

**Predictions:**
- Reproduction 600 of 600: **held**, after amendment 1 (as written, it failed on `sd` only).
- Grid within +-0.006 overall: **missed narrowly** (14 / 7 is +0.0062).
- Keep 1.0 / 17 / 14: **FAILED.** 21 / 7 clears the registered 1-SE bar.
- No damping worse overall by > 1 SE: **held** (+0.0156, 1.7 SE).
- No damping's 17+ rest ratio in 1.10-1.20: **held** (1.197).

**What this means for a load (the user's call; nothing in the repo changed).**
- With the end game on, the registered rule says #852's damping should run at **threshold 21 / span 7**, not 17 / 14.
- That needs NO code. The knobs already exist: `SYNDICATE_NCAAF_LIVE_BLOWOUT_DAMPING_THRESHOLD=21` and `..._SPAN=7`.
  So the end-game load set would be:
  - `SYNDICATE_NCAAF_LIVE_BLOWOUT_DAMPING=on`, `..._THRESHOLD=21`, `..._SPAN=7`;
  - `SYNDICATE_NCAAF_LIVE_ENDGAME=on`.
- #852 alone (without the end game) keeps 1.0 / 17 / 14. Its 11-21 hold-out and 12-08 decision are unchanged.
- **Still owed:** the real-timeouts hold-out, and a window.

### QUEUED FOR THE 12-08 WINDOW — written 2026-11-21 6:15 PM CST

**User 2026-11-21 ~6:10 PM CST, this session:** "queue the end-game load set for the 12-08 window". Queued
CONDITIONALLY on the shared 12-08 queue (the fleet-watcher's, under the NCAAF live totals pair). Nothing changed on
the fleet: none of the six keys is set on any role (read 00:14Z 11-22, key names only).

**The load set.** It rides ONLY on top of #835 + #852's pair, and all six lines are GLOBAL in `local_production.env`:
- the pair, 3 lines (its own 12-08 entry and conditions, unchanged):
  - `SYNDICATE_NCAAF_LIVE_TOTAL_CALIBRATION=on`
  - `SYNDICATE_LIVE_TOTALS_PROB_SCALE_NCAAF=1`
  - `SYNDICATE_NCAAF_LIVE_BLOWOUT_DAMPING=on`
- the end game, 3 more lines:
  - `SYNDICATE_NCAAF_LIVE_BLOWOUT_DAMPING_THRESHOLD=21`
  - `SYNDICATE_NCAAF_LIVE_BLOWOUT_DAMPING_SPAN=7`
  - `SYNDICATE_NCAAF_LIVE_ENDGAME=on`

The end game never loads without the pair, and the damping never stays at 17 / 14 once the end game is on. The joint
re-read above measured 17 / 14 with the end game, and the rule moved it to 21 / 7. If the end game's conditions
fail, the pair loads alone at 17 / 14.

**Conditions:** all must hold, or the end game waits for a later window.
1. **The pair loads in the same window.** Its own conditions are its 11-21 hold-out and the user's yes.
2. **A real-timeouts hold-out passes.** It is pre-registered before any of its data is read.
   - **What it scores:** the CALIBRATED totals (#835's anchor and widening on top), which are what bets are priced
     from, not the raw draws.
     - #835's spread schedule was fitted on the engine without the end game.
     - E0 (the kickoff re-sim that anchors to the close) is the same function, so it moves with the end game.
     - So the hold-out must show the stack still calibrates. Prediction: the calibrated stack is not worse than the
       pair's.
   - **Data:**
     - Slates 11-15..11-22 stay blinded until `C:\tmp\elp\m2gate_kit\out\m2_verdict.txt` exists.
     - Slates 11-28 .. 12-05 are outside that blind window: rivalry week and the conference championships.
3. **A live college scoreboard row shows `situation.homeTimeouts` / `awayTimeouts`.** Without them, the clock runs
   on the engine's default timeouts, and `profile_keys.endgame.timeouts_fed` says `false`.
4. **The user's final yes in this session's chat in the window.** A betting change, `--betting-change yes`.

**Kit:** `C:\tmp\w1208_ncaaf\kit_env_ncaaf.sh`, sha256 `4f31d0ac2b4888b5ca72fa32fa33a6e66482dd7264b5354d00ed360c1a3e4174`.
- Modes: `check` | `apply pair` | `apply endgame` | `restore <backup>`.
- It prints only these switches' lines; no other env value.
- `apply` backs the file up first (mode kept) and never edits a line. It refuses if any of its keys is already
  present under any role prefix.
- `apply endgame` refuses unless each of the pair's three lines is there exactly once.
- The self-test `kit_selftest_ncaaf.sh` passed on a dummy file, and the real file was unchanged (`selftest.out`).

**Verify after the drained down/up:**
- refresh-worker prints `NCAAF_LIVE_BLOWOUT_DAMPING on strength=1.0 lead_threshold=21.0 lead_span=7.0 ...` and
  `NCAAF_LIVE_ENDGAME on concede_deficit=25 end_of_half_clock=7/7 college_overtime=True blowout_damping_strength=1.0 ...`;
- live NCAAF re-sim lanes carry `endgame.on=true`, `concede_deficit=25` and `timeouts_fed=true`;
- the pair's own read: `total_calibration.anchored > 0`.

**Kill rule:** restore the kit's EARLIEST backup and run a drained down/up (a revert, exception (a)) in any of these
cases:
- the end-game line is absent at the first live NCAAF tick;
- `timeouts_fed` is false on every live lane through a full Saturday;
- or the pair's own kill rule fires.

**Noted, not a defect on the fleet:** `live_total_dispersion._live_profile_key()` (the E0 cache key) carries #852's
damping settings but not the end game.
- The cache is per process (`_E0_CACHE`), and env is built only at `up`, so a cached E0 cannot outlive an end-game
  change on the fleet.
- In a process whose env flips, it could. Add `("endgame", deficit)` to the key if the code is next touched.

## REAL-TIMEOUTS HOLD-OUT — PRE-REGISTRATION, written 2026-11-21 8:22 PM CST before any arm was run on its states

The user said "Yes, pre-register it" (2026-11-21), answering "Pre-register the real-timeouts hold-out now, while its
data is still unread?". This is condition 2 of the 12-08 queue entry above.

**Why 2026, and why it need not wait for the M2 verdict.**
- No earlier CFBD season is clean:
  - 2023-24 chose the concession at 25;
  - 2024 chose #852's damping and ran #858's and #859's re-reads;
  - #808's clock rates were fitted on 2024-25 (`scripts/football_end_of_half_clock_rates.py`, `SEASONS = (2024, 2025)`).
- 2026 is out of sample for every choice inside the end game.
- Weeks 1-10 lie wholly before M2's blind window:
  - week 11 is left out ENTIRELY, because one of its regular-season games starts after the cut;
  - weeks 12+ are never pulled.

  So none of slates 11-15..11-22 is read.

**Data.** Pulled before this was written; only counts were read (`C:\tmp\t859h\pull.txt`, `build.txt`).
- **Pull:** CFBD 2026 weeks 1-10, plays and `/lines`, via the repo's own loaders (`ensure_plays_cached`,
  `fetch_ncaaf_market_lines.fetch_lines`), into a PRIVATE dir, `C:\tmp\t859h\truth` (never the shared mirror).
  - The fleet's `games_2026` (refreshed 11-21) was filtered to games starting before 2026-11-15T10:00Z before anything
    else read it: 751 kept; 137 at or after the cut, not read.
  - Real timeouts are present on 99.4-100% of plays in each week.
- **Ratings:** SP+ 2026, the fleet's 11-21 copy. This is the 2024 instrument's source: a season table, in hindsight.
- **States:** the harness's own builder (`resume.build_tasks`; `resume.py` imported unchanged, TRUTH pointed at the
  private dir), at Q4 15:00 / 10:00 / 6:00 / 3:00.
  - **548 FBS-vs-FBS games and 2,191 states. Every state has a possession owner and both teams' real CFBD timeouts.**
  - Dropped: 123 not FBS-vs-FBS, 66 with too few plays (including week 11's, never pulled), 14 regulation mismatches.
  - Each week has 46-61 games.
- **Closes:** each game's median CFBD provider `overUnder`, joined by game id (`h_close.py`).

**Engine and arms.** The engine is a pinned export of main `f6b63e181` (`C:\tmp\t859h\code\COMMIT`). The arms are in
`h_arms.py`, injected into `resume.ARMS` at import:
- **`h_pair`:** #852 alone, which is what loads if the end game fails: damping 1.0 / 17 / 14.
- **`h_eg`:** the QUEUED set: #808's seven switches + college OT + concede at 25 + damping 1.0 / 21 / 7, with real
  timeouts fed.
- **`off`:** production today, for context only.

Each state gets 60 sims on its own seed block, paired across arms, at Idle with 2 workers.

**Instrument check.** Run BEFORE this was written; it reads no outcome (`h_verify.py`, `verify.txt`).
- **What it compares:** on 48 real 2026 states (12 games), each harness arm against the BUILT live path:
  `resim_live_game` with `NcaafLiveGameState.home_timeouts` / `away_timeouts`, under the env lines read from the queued
  kit file itself, at production's 120 seeds.
- **What must match:** the mean, at the payload's 3 decimals, and the full draw distribution.
- **Result:** `h_eg` 48 of 48 (timeouts fed on all 48), `h_pair` 48 of 48.

So the arms ARE the queued load set, run through the code that would run on the fleet.

**#835 on top: what bets are priced from.**
- Each arm's draws pass through production's own `live_total_dispersion.apply`, with the switch on and the default K
  schedule.
- Each arm uses its OWN E0. That is `h_e0.py`: the built `resim_live_game` at kickoff, 120 sims, `total_mean`, under
  the arm's kit env, which is production's E0 call.
- The close is CFBD's.

**Blind smoke test:** before this was written, the whole pipeline ran on the first 4 games into
`C:\tmp\t859h\smoke`. Only return codes and section presence were checked; no number was read.

**Gates.** All four must pass for condition 2 to be MET. The scorer is `h_read.py`. It runs `calib_arms.py`
unchanged: common lines from `h_pair`'s (or `cal_h_pair`'s) own quartiles, and a game-clustered paired SE.
- **C1:** calibrated overall log loss at Q4 15:00-6:00: `h_eg - h_pair` <= +1 paired SE.
- **C2:** calibrated 17+ at Q4 15:00-6:00: <= +1 paired SE.
- **C3:** calibrated one-score (|m| <= 8) at Q4 3:00: <= +1 paired SE.
- **R1:** `h_eg`'s one-score last-2:00 engine points fall inside the real 2026 95% interval. The interval is a
  bootstrap over those games' real points (2000 resamples, seed 859).

**Reported, not gated:**
- the raw-draw reads of all three arms, with slopes and rest ratios;
- the rest of game by margin (`paired_margin.py`);
- the calibrated overall by half-season, weeks 1-5 vs 6-10. #835's K was fitted on the fleet's 10-03..11-14 ledger
  (weeks 6-11).

**Predictions.** For scale: in the 2024 joint re-read, the pick beat `base` by -0.0127 overall, -0.0333 at 17+, and
-0.0132 one-score at Q4 3:00.
- **Raw `h_eg - h_pair`:**
  - overall in [-0.020, 0.000];
  - 17+ in [-0.050, -0.005];
  - one-score Q4 3:00 in [-0.030, +0.010].
- **Calibrated:** smaller in size:
  - overall in [-0.015, +0.002];
  - 17+ in [-0.040, 0.000].
  - C1-C3 all PASS.
- **R1:** `h_eg` inside the interval; `h_pair` and `off` below its centre. In 2024, `base` was 2.31, outside and below.
- **Rest of game by margin:**
  - at 17-24, `h_eg` >= `h_pair`, because 21 / 7 damps a 17-20 lead less;
  - at 25+, `h_eg` < `h_pair`, from the concession.
- **Half-seasons:** weeks 1-5 and 6-10 agree in sign.

**What follows.**
- **MET:** condition 2 holds. Conditions 1, 3 and 4 remain: the pair's own load; a live ESPN scoreboard row carrying
  college timeouts, which can be read on any slate from 11-24 (MACtion) on, outside the blind window; and the user's
  yes in the window.
- **NOT MET:** the end game leaves the 12-08 queue, the pair loads alone at 17 / 14, and the failing gate is reported.
- **Either way:** nothing changes on the fleet. The 11-21 / 11-28 / 12-05 slates are not part of this read. 11-28 and
  12-05 may be added later as a confirmation, reported but not gating.

**Pins (sha256):**

| file | sha256 |
|---|---|
| `h_arms.py` | `aa41e98e905c307cf8d2b2581b6e60ab04796b08171ef2133357a682bcddd976` |
| `h_verify.py` | `7ace0a174b7ab2a4119a0dbfba0d5030a6ff0fbdc9007fc7dedb22a353172ad7` |
| `h_run.py` | `638a16416b20b725b9f18a8d915071ebc2006290be2f3a40db97921d1745be4c` |
| `h_e0.py` | `e717b7a084e0b3168f24785695d6ea5443e5875bd97d4672c5737dbb079907bb` |
| `h_close.py` | `0da41ced76251fb555692bbda12e6da9ec45237dcce6ec66ba450620cb587993` |
| `h_read.py` | `4d424406cdad1df817b93f1aa363deb3a4f994ed44255d336b6e26a99d2cf59d` |
| `pull.py` | `7d94e9e82896fcc0d0a72236fba8a450f60e9c7970be7794377b9042ebb44adc` |
| `h_build.py` | `db915a65b910233fa614aecf5b93f5bb14b4b5a1d9e2092913b377b227955456` |
| `tasks_2026.json` | `44c539d5e90e5db217520f104fb3a0e26e9a6f59df5a371bcd87cfe5d3e7191c` |
| `verify.txt` | `e7a299af22a17d1c06b579b9d8b609e4f090ee3c536fe4dab3a1ce69e0102daa` |
| `C:\tmp\t852\resume.py` (unchanged) | `ef89b077310a777c6f6a33ec43f4905eb855b687f82cd39d8ee38178aedaf2b8` |
| `C:\tmp\t852\calib_arms.py` | `9c8c852b7e876d4d80487ab9bcb71862cbd2a07d656d9e87bdb0e3a532e4ccd3` |
| `C:\tmp\t852\paired_margin.py` | `10a991f4cb3a83b581f1b45a11f09be70abc3f71a5dbe6e6c5090e70df984acc` |
| the kit `kit_env_ncaaf.sh` | `4f31d0ac2b4888b5ca72fa32fa33a6e66482dd7264b5354d00ed360c1a3e4174` |

### REAL-TIMEOUTS HOLD-OUT RESULTS — written 2026-11-21 9:37 PM CST, after the runs (nothing above was changed)

**Verdict: condition 2 is MET.** All four pre-registered gates pass.
- **Where it helps:** on 2026 states the pair alone puts one-score late scoring a third short, and the end game puts
  it on the real number.
- **Where it costs:** big leads late. This is not gated, but it has the same sign in 2024 and in both 2026 reads (see
  "Where it costs").

**Run.** `C:\tmp\t859h\run_all.sh`, log `run.log`.
- Every pin was checked OK at 02:23:55Z 11-22.
- The three arms ran 548 of 548 games each: `h_pair` 4.8 min, `h_eg` 5.9 min, `off` 4.8 min (2 Idle workers, 60
  sims a state).
- E0 ran 548 of 548 for each test arm, 0 refused. Closes were found for 548 of 548 games.
- The pinned `h_read.py` wrote `C:\tmp\t859h\read.txt`. Its instrument re-check: `h_eg` 48 of 48 identical (timeouts
  fed on 48), `h_pair` 48 of 48.
- #835 anchored all 2,191 states in both arms.

**Gates** (calibrated, `h_eg - h_pair`, game-clustered paired SE):

| gate | reading | rule | verdict |
|---|---|---|---|
| C1 overall, Q4 15:00-6:00 (548 games) | -0.0015 (se 0.0045) | <= +1 SE | PASS |
| C2 17+, Q4 15:00-6:00 (249) | +0.0089 (se 0.0092) | <= +1 SE | PASS, by 0.03 SE |
| C3 one-score, Q4 3:00 (203) | **-0.0858 (se 0.0257)** | <= +1 SE | PASS, better by 3.3 SE |
| R1 one-score last-2:00 points (236 games one-score at Q4 15:00) | `h_eg` **3.23**; real 3.16 [2.66, 3.67] | inside | PASS |

On R1, `h_pair` (2.35) and `off` (2.36) are both outside, below. 2024's `base` was 2.31.

**Where it helps.** One-score games at Q4 3:00:
- The pair's rest of game is 0.673 of the real points (engine minus actual -1.83, se 0.43). The end game's is 1.004
  (+0.14, se 0.44).
- Raw log loss there: -0.0419 (se 0.0309).
- That is #808's clock with real timeouts doing what it was built for, now out of sample.

**Where it costs** (NOT gated; stated because the sign holds across reads). At 17+ the end game is behind the pair
after calibration:
- **Q4 15:00-6:00:** +0.0089 (se 0.0092), the C2 reading. Raw, it was ahead: -0.0045 (se 0.0122).
- **Q4 3:00:** **+0.0443 (se 0.0293)** calibrated, +0.0246 (se 0.0198) raw. 2024's joint re-read had +0.0333
  (se 0.0473) raw at the same cell. Three reads, one sign, 0.7-1.5 SE.
- **The shape is over-confidence, not a wrong centre.** At 17+ at Q4 3:00 (calibrated read, same lines for both arms):

  | arm | rest ratio | slope |
  |---|---|---|
  | end game | 0.940 | 0.62 |
  | pair | 1.110 | 0.92 |

  - The end game's centre is closer to the truth, but its spread is too tight.
  - #835's widening was fitted on production's `off` draws (fleet ledger 10-03..11-14).
  - The likely reason, not measured here: the end game's late blowout draws are narrower, because the trailer
    concedes at 25+ and #808's clock slows the end of the game.
- This is `model_engine_standard.md`'s mechanism-vs-estimator case: the estimator on top was fitted without the
  mechanism.

**Not gated, for the record:**
- **Raw draws** (lines from `h_pair`'s quartiles), against the pair:

  | Q4 15:00-6:00 | `h_eg` | `off` |
  |---|---|---|
  | overall | -0.0019 (se 0.0065) | +0.0164 (se 0.0047) |
  | 17+ | -0.0045 (se 0.0122) | +0.0442 (se 0.0124) |

  So on 2026 the pair alone beats production today by 3.5 SE at 17+, the pair's own claim, out of sample.
- **Rest of game by margin:** `h_eg` minus `h_pair`, with engine minus actual for pair -> end game.

  | checkpoint | margin | `h_eg` minus `h_pair` | engine minus actual |
  |---|---|---|---|
  | Q4 15:00 | 0-8 | +1.33 | -1.06 -> +0.27 |
  | Q4 15:00 | 9-16 | +0.62 | -0.51 -> +0.11 |
  | Q4 15:00 | 17-24 | -0.22 | +0.35 -> +0.13 |
  | Q4 15:00 | 25+ | -1.43 | +0.57 -> -0.86 (se 0.75) |
  | Q4 15:00 | all | | -0.42 -> +0.03 |
  | Q4 3:00 | 0-8 | +1.97 | -1.83 -> +0.14 |
  | Q4 3:00 | 25+ | -0.50 | +0.43 -> -0.08 |

- **Calibrated overall by half-season:** weeks 1-5 -0.0041 (se 0.0063); weeks 6-10 +0.0009 (se 0.0064).
- **Calibrated Q4 3:00, all margins:** -0.0110 (se 0.0166).

**Predictions** (6 of 11 held):
- Raw overall in [-0.020, 0.000]: -0.0019, **held**.
- Raw 17+ in [-0.050, -0.005]: -0.0045, **missed narrowly** (a smaller gain).
- Raw one-score Q4 3:00 in [-0.030, +0.010]: -0.0419, **missed** (a bigger gain).
- Calibrated overall in [-0.015, +0.002]: -0.0015, **held**.
- Calibrated 17+ in [-0.040, 0.000]: +0.0089, **FAILED, wrong sign** (see "Where it costs").
- C1-C3 all PASS: **held**.
- R1, `h_eg` inside: **held**.
- R1, `h_pair` and `off` below its centre: **held**.
- 17-24, `h_eg` >= `h_pair`: **FAILED** at all four checkpoints (-0.22, -0.22, -0.10, -0.21; se 0.10-0.14).
  - The shift is mostly the trailer's (-0.20 of -0.22 at Q4 15:00).
  - At every checkpoint the end game sits closer to the real points: engine minus actual +0.35 -> +0.13,
    +0.30 -> +0.08, +0.92 -> +0.82, +0.24 -> +0.03.
- 25+, `h_eg` < `h_pair`: **held** at all four (-1.43, -1.44, -1.56, -0.50).
- Half-seasons agree in sign: **FAILED** (-0.0041 vs +0.0009). Both are inside 1 SE of zero.

**What follows (the pre-registered rule).**
- Condition 2 holds.
- Still owed:
  1. the pair's own load: its 11-21 hold-out after the M2 verdict, and its window;
  2. a live ESPN college scoreboard row with `homeTimeouts` / `awayTimeouts` (any slate from 11-24 MACtion on);
  3. the user's yes in the window.
- Nothing changed on the fleet.

**Open, for the user before 12-08: the 17+ late over-confidence.** The registered gates did not cover 17+ at Q4
3:00, and the rule is the rule, so the end game stays queued.
- The standard asks for a re-fit of #835's widening on top of the end-game draws. It can be done without reusing this
  hold-out: fit on 2024 states, confirm on the 11-28 and 12-05 slates. Those are CFBD plays, outside the blind window.
- A different K would be one more thing to load. So the choice is the user's:
  - re-fit before 12-08;
  - or load the end game on the current K and watch 17+ late.
