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
