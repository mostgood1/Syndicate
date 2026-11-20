# NCAAF live re-sim: #808's end-of-half clock for one-score games (todo #858, lane `ncaaf-endgame-clock`, 2026-11-20)

The user said "start the end-game clock follow-up". This is #852's last follow-up
(`findings_2026-11-19_ncaaf_live_endgame_surplus.md`). After #852's leader damping and #855's college overtime,
one-score games still run under in the last two minutes: from 2024 Q4 15:00 resumes the engine gives 2.31 points
against a real 3.58, on 4.7 snaps against 7.3. #808 built an end-of-half clock with an NCAAF table, all switches
default off. It is ON in NFL's profile only. Kit: `C:\tmp\t852` (the #852 harness) and `C:\tmp\t858`.

**What is known going in (#852's `eoh` arm, without the damping):** the seven switches add +1.1 to +1.3 rest-of-game
points at every margin. One-score last-2:00 points go 2.33 -> 3.56 (real 3.67), and blowouts get worse (+4.3 -> +5.4).
The NCAAF live re-sim feeds no timeouts, so with the clock on the engine would assume 3 each.

**Timeouts at the harness states** (CFBD `offenseTimeouts` / `defenseTimeouts` at the snap, both teams): mean 4.98 at
Q4 15:00, falling to 4.06 at Q4 3:00, consistent with timeouts LEFT in the half. Caveat: "(0, 3)" appears in 14% of
Q4 15:00 states, which is high. So the default-3 arm is the sensitivity check, not a strawman.

## PRE-REGISTRATION — written 2026-11-20 before any arm of this lane was run

**Population.** The #852 harness (`C:\tmp\t852\resume.py`, `T852_CPS=late`): the first 150 games of the 2024
every-2nd task list, the same games as #852's fit. Q4 15:00 / 10:00 / 6:00 / 3:00 real CFBD states. 60 sims a state on
the state's own seed block, paired across arms. Production's NCAAF profile, season SP+ with the live shrink.

**Arms.**
- **`base`:** `blowout_damping_strength` 1.0 / threshold 17 / span 14 (#852's pick) + `college_overtime` (#855). This
  is the live candidate before the clock.
- **`clk_to`:** `base` + #808's seven switches (`halftime_kickoff`, `q2_urgency_ignores_score`, `end_of_half_clock`,
  `end_of_half_kneel_out`, `end_of_half_clock_by_need`, `q4_kick_waits`, `kneel_out_q4_only`), fed the REAL CFBD
  timeouts left at the state.
- **`clk_3`:** the same as `clk_to`, with the timeouts left unfed (the engine's default 3 each), which is what the
  live re-sim would do today.

**Readings, by |margin| at the state (0-8 / 9-16 / 17+):**
- rest-of-game points against the real;
- last-2:00 points and snaps against the real;
- common-line log loss against the real final (lines = `base`'s own 25 / 50 / 75% rest quantiles + 0.5), paired SE
  against `base`. These are read at Q4 15:00-6:00 and at Q4 3:00.

**Gates (all three for a build).**
- **G1 (H-CLOCK):** with `clk_to`, one-score (0-8) last-2:00 points fall inside the real 95% CI (bootstrap over the
  same games), and snaps within 10%. One-score log loss at Q4 3:00 is below `base`'s.
- **G2 (H-BLOWOUT):** `clk_to`'s 17+ log loss (Q4 15:00-6:00) is not worse than `base`'s by more than 1 paired SE.
  - If it fails: re-fit the damping with the clock on. Grid: threshold {14, 17, 21} x span {7, 14} at strength 1.0.
  - Same rule as #852: move off 1.0 / 17 / 14 only past 1 paired SE of overall log loss. Then re-read G2 / G3.
- **G3:** `clk_to`'s overall log loss (Q4 15:00-6:00) is not above `base`'s.
- **H-TIMEOUTS** is read as `clk_3` minus `clk_to` at Q4 3:00, one-score. It is "matters" if that exceeds 1 paired SE.
  It decides whether a live build MUST feed ESPN's timeouts first. It does not gate.

**Predictions** (from #852's `eoh` arm).
- `clk_to` one-score:
  - rest +1.0 to +1.6 at Q4 15:00;
  - last-2:00 points 3.3-3.9 (real about 3.6);
  - snaps 6.6-8.0 (real about 7.3).
- `clk_to` 17+: worse than `base` by +0.5 to +1.2 rest points. **G2 is predicted to FAIL** before any re-fit (leaders
  get extra snaps).
- `clk_3` over `clk_to` at Q4 3:00 one-score: +0.2 to +0.6 points.

**Scope.**
- Measurement and, if the gates pass, a build plan.
- Building the live wiring needs:
  - ESPN `situation.homeTimeouts` / `awayTimeouts` read into `ncaaf/live_resim.py`, the NFL pattern of
    `findings_2026-11-16_nfl_live_timeouts.md`;
  - a live switch for these profile fields;
  - loans from `live-player-exit-gate`, the user's yes, and a betting-change window.
- No code here without the user's yes.

## RESULTS, STAGE 1: the gates before any re-fit (written after the runs; nothing above was changed)

`C:\tmp\t858\c858_read.py`, `c858_read_stage1.txt`. 150 paired games; one-score = |margin| <= 8 at the state.

| gate | reading | |
|---|---|---|
| G1 points: one-score last-2:00 points in the real CI | `clk_to` **3.23**; real 3.58 [2.55, 4.71] (n 66); `base` 2.31 | PASS |
| G1 snaps: one-score last-2:00 snaps within 10% | `clk_to` 7.69 against a real 9.09 (**-15%**); `base` 4.91 (-46%) | **FAIL** |
| G1 log loss: one-score at Q4 3:00 below `base` | -0.0132 (se 0.0462) | PASS (point) |
| G2: 17+ log loss (Q4 15:00-6:00) vs `base` | **+0.0307 (se 0.0123)**, 2.5 SE worse | **FAIL** (predicted) |
| G3: overall log loss (Q4 15:00-6:00) vs `base` | +0.0141 (se 0.0098) | **FAIL** |
| H-TIMEOUTS: `clk_3` - `clk_to` rest, Q4 3:00 one-score | **+0.46 (se 0.19)** | matters |

**Rest-of-game, `clk_to` minus `base`, by margin (Q4 15:00 / 10:00 / 6:00 / 3:00):**
- 0-8: +0.87 / +0.97 / +1.22 / +1.02.
- 9-16: +0.89 / +0.87 / +0.76 / +0.15.
- 17-24: +0.66 / +0.54 / +0.01 / -0.22.
- 25+: +0.77 / +0.68 / +0.79 / +0.62.

The leader takes +0.46 at Q4 15:00 at every margin.

**One-score engine minus actual:** `base` -1.04 / -0.91 / -2.13 / -1.49; `clk_to` **-0.17 / +0.06 / -0.91 / -0.47**. The
clock closes most of the one-score gap.

**25+ engine minus actual:** `base` +1.64 / +2.43 / +2.27 / +0.69; `clk_to` +2.41 / +3.11 / +3.06 / +1.30. It reopens
the blowout surplus that #852's damping had cut.

**`clk_3` (default 3 timeouts):**
- every margin +1.1 to +1.5 over `base`;
- 17+ log loss +0.0550 (se 0.0161);
- overall +0.0229 (se 0.0118).

Feeding the real timeouts is necessary but not sufficient.

**Predictions:**
- `clk_to` one-score rest +0.87 at Q4 15:00: MISS, under the predicted +1.0 to +1.6.
- Last-2:00 points 3.23: MISS, just under 3.3-3.9.
- Snaps 7.69: inside the predicted 6.6-8.0. But the one-score REAL is 9.09, not the all-margin 7.3 the prediction
  assumed.
- 17+ worse by +0.5 to +1.2: HELD (+0.54 to +0.79 before 3:00).
- G2 FAIL: HELD.
- H-TIMEOUTS +0.2 to +0.6: HELD (+0.46).

**Next, as registered:** G2 failed, so the damping is re-fit with the clock on. Grid: threshold {14, 17, 21} x span
{7, 14} at strength 1.0. Arms `ckt14s7`, `ckt14s14`, `ckt17s7`, `ckt21s7`, `ckt21s14`; the incumbent `ckt17s14` =
`clk_to`. Then G2 / G3 are re-read (`c858_refit.py`).

## RESULTS, STAGE 2: the damping re-fit with the clock on, and the VERDICT

`C:\tmp\t858\c858_refit.py`, `c858_refit.txt`. The same 150 games, paired.

**Grid, overall log loss (Q4 15:00-6:00) against the incumbent `ckt17s14`, se:**

| threshold / span | vs incumbent | 17+ vs incumbent |
|---|---|---|
| 14 / 7 | +0.0018 (0.0041) | +0.0004 |
| 14 / 14 | +0.0016 (0.0024) | +0.0016 |
| 17 / 7 | -0.0013 (0.0025) | -0.0022 |
| **21 / 7 (PICK, 1.8 SE)** | **-0.0022 (0.0012)** | -0.0037 |
| 21 / 14 | +0.0014 (0.0024) | +0.0034 |

The whole grid spans about +-0.004. The damping's shape is not the lever.

**The pick against `base`:**
- G2: 17+ **+0.0276 (se 0.0127)**. FAIL.
- G3: overall **+0.0121 (se 0.0099)**. FAIL.
- G1: one-score at Q4 3:00 -0.0132 (se 0.0462), unchanged, since the damping does not act there.

### VERDICT: NOT BUILT, the registered "stated reason not to". G2 and G3 fail, and the registered re-fit cannot absorb it.

**Why.**
1. **The clock adds late points at EVERY margin, not just one-score.** Rest-of-game, pick minus `base`, at Q4
   15:00: +0.90 at 0-8, +0.93 at 9-16, +0.74 at 17-24, +0.73 at 25+.
   - In blowouts the extra comes from both sides: leader +0.43, trailer +0.31.
   - The trailer's share is hurry-up and clock stops at a deficit no real team chases. Leader-only damping cannot touch
     it.
2. **The one-score gain is real in the MEAN but not shown in log loss.**
   - One-score engine minus actual: -1.04 -> -0.15 (Q4 15:00) and -1.49 -> -0.47 (Q4 3:00).
   - Last-2:00 points 3.23, inside the real CI.
   - But one-score log loss is +0.0054 (se 0.0168) at Q4 15:00-6:00 and -0.0132 (se 0.0462) at Q4 3:00, with the
     slope 0.64 -> 0.53.
   - Closing the mean gap with a clock that also adds spread did not price one-score games better on these 51-73
     games.
3. **Snaps still miss:** 7.69 against a real 9.09 in one-score games (G1 snaps FAIL).
4. **Timeouts matter** (+0.46, se 0.19). So any live use must feed ESPN's timeouts first: the NFL pattern,
   `findings_2026-11-16_nfl_live_timeouts.md`.

**What a v4 would be (not pre-registered; the user's call).** A MARGIN-AWARE end-game, NCAAF-specific, two new
mechanisms in `situation_model` / `drive_simulator` (a loan):
- (a) the trailing hurry-up and the two-minute drill fire only when the deficit is within reach of the possessions
  left: today `classify_urgency` fires at ANY deficit;
- (b) a leader up beyond reach runs the clock earlier than the 150 s end-game preservation.

Measured target: real Q4 points and seconds per snap by role and margin (`C:\tmp\t852\real_blowout.py`: trailer
pass share 0.66 at 9-24 and 0.52 at 25+; Q4 trailer points 4.80 at 25+). Then the clock is re-read on top.

**The live candidate stays as it is:** #852's damping (1.0 / 17) + #855's college overtime (on main, default off),
#835's anchor. The one-score last-2:00 gap stays open (2.31 vs 3.58 points), and is this lane's documented residual.

**Predictions after the re-fit:** none were registered for the grid beyond the rule. The stage-1 prediction "G2
FAILS before the re-fit" held, and the re-fit did not rescue it.
