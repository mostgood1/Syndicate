# NHL live re-sim: the rest of the current period is regulation, not overtime (todo #773, lane nhl-live-period-remainder)

**Result: every live NHL re-sim was playing the rest of the CURRENT period as overtime, and now plays it as
regulation.** On today's real slate (NYR @ VAN) the moneyline moves up to 7 points in mid-period states (P1 15:00
0-0: home 0.280 -> 0.350). On the season replay (301 games, 14 cutoffs, graded against real finals) the priced
moneyline is better in expectation (Brier -0.00057 [-0.00160, +0.00045]), the puck line unchanged, the
display-only total slightly worse within noise (+0.0014 [-0.0015, +0.0044]); the shipped total and end-game
calibrations still fit and are not changed.

## The defect (`syndicate/features/nhl/sim_engine/hockeysim/engine.py`, `simulate_period_with_lines`)

The period sim decided "is this overtime?" from the period's LENGTH: `T != seconds_per_period`. That is right for
a whole regulation period (1200 s) and for OT (300 s). A live resume's first period is the time left on the clock,
so it is almost always short, and four things switched to their overtime form for the rest of that period:

1. **3-on-3 skaters** (`is_ot`, 2 forwards + 1 defenceman from each line, line-quality adjustment skipped) instead
   of the 5-on-5 rotation.
2. **The score effects' clock** counted only the time left in THIS period, so a P1 10:00 state got end-of-game
   urgency (0.8 of full) where the real game had 50 minutes left (0). P3 was already right.
3. **The power-play share**: the legacy PP-time model (the one production runs: `pp_time_model` is unset, so
   `minors_2min`) divided the game's expected PP seconds by the period's REMAINING seconds, capped at 0.45. On the
   stub game the rest of P1 from 10:00 spent ~0.45 of its segments on a power play against ~0.2 in a whole period.
4. **Segment length** 40 s instead of 45 s.

Whole periods after the resumed one, and every pregame period, were always right.

## What ships

- `simulate_period_with_lines(is_overtime=None)`: None keeps the length inference exactly (pregame passes nothing).
  True / False states the period's kind, and the four checks read it. The score clock is now
  `_score_effect_clock(...)`, the same expression lifted out so it can be pinned by a test.
- `simulate_with_lineups(explicit_period_kind=False)`: True passes `is_overtime=False` for every regulation
  period and True for OT. `runtime.run_hockeysim_game_from_state` passes it through.
- `live_resim`: `SYNDICATE_NHL_LIVE_PERIOD_REMAINDER` (default on; `off` is the old play). The result carries
  `period_remainder {play, calibration, resumed_period_seconds}`, published on the lane as `livePeriodRemainder`.
  No pricer reads it.

What it moves: the live moneyline (priced), the display-only puck line, and the live total, in every state that is
not at a period start.

## Reachability (`off != on`) on production's code path and inputs

Run from the worktree under live-odds-worker's environ (pid 482349), today's real slate features, NYR @ VAN, 400
sims, seed 7, OT sudden death on, the shipped keep and end-game (`C:\tmp\nhlrec\period_reach.py`):

| state | home win | total | P(home -1.5) |
|---|---|---|---|
| P1 20:00 0-0 | 0.3175 = 0.3175 | 6.205 = 6.205 | 0.1925 = |
| P1 15:00 0-0 | 0.2800 -> **0.3500** | 5.978 -> 5.745 | 0.1300 -> 0.1825 |
| P1 10:00 1-0 | 0.4350 -> 0.4700 | 6.360 -> 6.320 | 0.2350 -> 0.2475 |
| P2 20:00 1-1 | 0.3550 = 0.3550 | 6.433 = | 0.1725 = |
| P2 10:00 1-1 | 0.3275 -> 0.3500 | 5.362 -> 5.465 | 0.1500 = |
| P2 05:00 2-1 | 0.5825 -> 0.5625 | 6.110 -> 5.952 | 0.2950 -> 0.2550 |
| P3 10:00 2-1 | 0.7000 -> 0.6925 | 4.655 -> 4.588 | 0.3450 -> 0.3300 |
| P3 05:00 2-1 | 0.8350 -> **0.7850** | 4.070 -> 4.152 | 0.3575 -> 0.3425 |
| P3 01:00 2-2 | 0.4175 -> 0.3925 | 5.035 -> 5.015 | 0.0075 -> 0.0050 |

Period starts are identical seed for seed; every mid-period state moves.

## Tests (`tests/test_nhl_live_period_remainder.py`, 11)

Off reproduces the defect (the rest of P1 is 3-on-3; whole periods 5-on-5); on is 5-on-5 in the remainder; the
remainder's PP share is the game's (off > on + 0.10; on within 0.05 of a whole period's); the score clock counts
the periods still to come (pure function); a resume at a period start is identical seed for seed; pregame never
turns it on (signature default; opening-faceoff resume with it ON equals `run_hockeysim_game`); OT is still
3-on-3; live_resim reachability, period-start identity, the env switch, and the published lane.

Mutations, each caught: 3-on-3 by length (1 fails), PP denominator by length (1), score clock always regulation
(1), the flag not passed to regulation periods (3). Neighbouring suites: 114 + 156 passed.

## Replay, the standard eight cutoffs (on vs off, same inputs; OT on in both)

`C:\tmp\nhlrec\replay_period.sh`, 2026-11-13 22:15-22:59Z: 301 games / 43 dates, 2,408 states. The off arm
reproduces the overtime lane's run exactly (total-keep fit CRPS 0.665652, same table), so the inputs are the same.
**Three of the eight cutoffs are period starts (P1 / P2 / P3 20:00), where the fix changes nothing (graded
identical to the last digit); the rest are P2 10:00 and four P3 states.**

Paired, game-clustered bootstrap (2,000 resamples), on - off, as production publishes (shipped end-game and keep;
`C:\tmp\nhlrec\period_paired.py`):

| | pooled (2,408) | P2 10:00 | P3 10:00 | P3 05:00 | P3 03:00 | P3 01:30 |
|---|---|---|---|---|---|---|
| moneyline Brier | **-0.00030** [-0.00127, +0.00061] | -0.00087 | -0.00189 | -0.00161 | +0.00172 | +0.00026 |
| +-1.5 Brier | -0.00014 [-0.00064, +0.00034] | +0.00077 | -0.00137 | -0.00102 | +0.00004 | +0.00046 |
| total CRPS | +0.0001 [-0.0022, +0.0024] | +0.0008 | -0.0017 | -0.0003 | -0.0000 | +0.0019 |

Every per-cutoff interval spans 0.

**The calibrations still fit; neither is changed:**
- Total keep on the on arm: keep 0.86 at a 300 s window (CRPS 0.665602) vs the off arm's 0.85 / 300 s
  (0.665652); walk-forward keep [0.82, 0.86] in both. The shipped 0.85 / 240 s stays.
- End-game (the harness's +-1.5 Brier): on arm at the shipped 0.38 / 90 s 0.110952, best on the grid 0.40 / 90 s
  0.110935 (0.00002 apart); off arm 0.111094 at the shipped values.

## Replay, six MID-PERIOD cutoffs

`C:\tmp\nhlrec\replay_period_mid.sh`, 23:01-23:18Z: P1 15:00 / 10:00 / 05:00, P2 15:00 / 05:00, P3 15:00 (the
states the standard grade does not have, and where the fix moves the moneyline most), same 301 games, inputs and
seeds-per-state rule. The harness's own `CUTOFFS` were swapped by a driver (`C:\tmp\nhlrec\replay_mid.py`); no repo
file changed. 1,806 paired states.

| on - off | pooled (1,806) | P1 15:00 | P1 10:00 | P1 05:00 | P2 15:00 | P2 05:00 | P3 15:00 |
|---|---|---|---|---|---|---|---|
| moneyline Brier | **-0.00094** [-0.00284, +0.00111] | +0.00229 | -0.00209 | -0.00116 | -0.00112 | -0.00210 | -0.00147 |
| +-1.5 Brier | +0.00014 [-0.00100, +0.00136] | -0.00021 | +0.00073 | -0.00200 | +0.00080 | +0.00177 | -0.00028 |
| total CRPS | +0.0032 [-0.0022, +0.0086] | +0.0046 | +0.0123 | -0.0061 | +0.0086 | -0.0067 | +0.0066 |

Every per-cutoff interval spans 0 (P1 10:00's total is the nearest: [-0.0011, +0.0256]).

**All 14 cutoffs together (4,214 paired states, 301 games):** moneyline Brier **-0.00057 [-0.00160, +0.00045]**
(better in 8 of the 11 mid-period cutoffs), +-1.5 -0.00002 [-0.00063, +0.00062], total CRPS +0.0014 [-0.0015,
+0.0044].

**The total, read closer** (`C:\tmp\nhlrec\mid_bias.py`): the fix LOWERS the engine's raw total mid-period by
0.02-0.06 goals (raw bias P1 15:00 +0.701 -> +0.654, P2 15:00 +0.440 -> +0.378), the right direction for an
engine that over-scores. The shipped keep was fit on the old, higher total, so the published total now sits a
little lower than the finals (P1 10:00 -0.085 -> -0.122). Re-fitting the keep over all 14 cutoffs
(`C:\tmp\nhlrec\keep_check.py`): on arm best 0.86 / 300 s, CRPS 0.789098, vs the shipped 0.85 / 240 s 0.789630
(0.0005, 0.07%); walk-forward keep [0.84, 0.87], window [120, 300] on both arms. **The shipped keep is kept**: the
re-fit's gain is below anything this sample resolves, and the shipped values sit inside its walk-forward range. The
end-game likewise (mid arms: on at 0.38 / 90 s 0.154013, best 0.34 / 90 s 0.153982).

## Verdict

A correctness fix (the engine was simulating 3-on-3 with up to 45% power play for the rest of every live period),
neutral to slightly better on everything graded against real finals: the priced moneyline better in expectation
(-0.00057 pooled, not significant), the puck line unchanged, the display-only total slightly worse within noise.
No calibration constant changes. Its moneyline moves are large in single states (up to 7 points at P1 15:00
tonight), so it is a load for the user to decide.

## What remains, not fixed here

1. **The engine's early over-scoring and narrow margin** (findings_2026-11-13_nhl_live_total_calibration.md) are
   still there: the P1 20:00 bias is a period start and does not move. That is the scoring-rate / score-effects
   re-fit.
2. **OT's power-play share** still uses OT's own clock (the legacy denominator, capped at 0.45); unchanged here.
3. **Pregame**: unaffected by this defect (its periods are whole), and untouched.
