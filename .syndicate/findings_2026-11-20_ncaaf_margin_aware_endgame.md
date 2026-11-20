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
