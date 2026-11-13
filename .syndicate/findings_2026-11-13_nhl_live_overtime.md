# NHL live re-sim: overtime played as it is played (todo #773, lane nhl-live-overtime)

**Result: every simulated game that reaches overtime now ends exactly one goal past the tie.** Before, the engine
played OT as one whole 5:00 segment and summed its goals, and a state resumed IN overtime got a fresh 5:00 whatever
the clock showed. On production's inputs (NYR @ VAN, 2026-11-13 slate features, 400 sims) 21 of 400 sims resumed at
P4 05:00 2-2 ended 2-3 goals past the tie, the published total was 5.24 for a game that can only finish with 5,
and the home -1.5 puck line showed 1.25% where the only possible answer is 0. With the fix: 0 of 400, 5.000 and 0.

Not a fit: sudden death has no parameter. Sims that end in regulation are untouched seed for seed.

## The defect (`syndicate/features/nhl/sim_engine/hockeysim/engine.py`, `simulate_with_lineups`)

1. **Not sudden death.** The OT block runs `simulate_period_with_lines(..., period_seconds=overtime_seconds)` and adds
   the whole segment's goals. A 3-on-3 segment with two or three goals ends 2-3 past the tie, and when it ends
   level (1-1) the shootout decides a game a real OT would already have ended.
2. **The clock was ignored on a resume in OT.** `live_resim` resumes an OT state at `period_idx = 3` with the
   scoreboard's clock, but the period loop (`range(start_idx, periods)`) is empty there and the OT block always
   played `overtime_seconds` (300). A shootout in progress (OT clock 0:00) was re-simulated as 5:00 of OT first.

The pregame path shares the OT block. It is NOT changed here (see "What remains").

## What ships

- `engine.simulate_with_lineups(ot_sudden_death=False)`: new keyword, default off, so the pregame entry point
  (`runtime.run_hockeysim_game`, which does not pass it) is unchanged. On:
  - the OT segment is drawn exactly as before and cut at its FIRST goal (`_cut_at_first_goal`): the engine is
    causal, so the events up to that goal are a sudden-death game's; the cut draws nothing;
  - resumed IN OT, the segment is the clock shown (`min(overtime_seconds, resume_seconds_remaining)`; 0 goes
    straight to the shootout).
- `runtime.run_hockeysim_game_from_state(ot_sudden_death=...)`: pass-through.
- `live_resim.resim_live_game(overtime_sudden_death=None)`: defaults to `live_overtime_sudden_death()`, on unless
  `SYNDICATE_NHL_LIVE_OVERTIME=off`. The result carries `overtime {rule, calibration, sims_past_regulation,
  resumed_ot_clock_seconds}` and the lane publishes it as `liveOvertime`, so a production reading can tell on
  from off. No pricer reads it.

What it moves: the live total, the display-only puck-line histogram (`displayMarginDist`), and the live
moneyline in OT and tied-late states (the winner of an OT is now its first scorer, and a short OT clock sends
more sims to the shootout). The moneyline is a number the join can price.

## Reachability (`off != on`) on production's code path and inputs

Run from the worktree under live-odds-worker's environ (pid 445457), today's real slate features, 400 sims,
seed 7 (`C:\tmp\nhlrec\ot_reach.py`). The resolved switch: on. Regulation margin histogram identical off/on in
every state.

| state | sims reaching OT | OT sims > 1 past the tie | home win | total | P(home -1.5) |
|---|---|---|---|---|---|
| P4 05:00 2-2 | 400 | 21 -> **0** | 0.4450 -> 0.4600 | 5.240 -> **5.000** | 0.0125 -> **0** |
| P4 02:00 2-2 | 400 | 21 -> **0** | 0.4450 -> 0.4750 | 5.240 -> **5.000** | 0.0125 -> **0** |
| P4 00:00 2-2 (shootout) | 400 | 21 -> **0** | 0.4450 -> 0.4675 | 5.240 -> **5.000** | 0.0125 -> **0** |
| P3 01:00 2-2 | 364 | 22 -> 0 | 0.4175 -> 0.4175 | 5.242 -> 5.035 | 0.0225 -> 0.0075 |
| P3 05:00 2-2 | 240 | 23 -> 0 | 0.4175 -> 0.4250 | 5.478 -> 5.340 | 0.0625 -> 0.0450 |
| P2 10:00 1-1 | 80 | 5 -> 0 | 0.3225 -> 0.3275 | 5.397 -> 5.362 | 0.1525 -> 0.1500 |
| P3 05:00 2-1 | 86 | 6 -> 0 | 0.8325 -> 0.8350 | 4.135 -> 4.070 | 0.3625 -> 0.3575 |

Off, the three P4 rows are identical: the clock was ignored. On, they differ only in the moneyline (a shorter
OT clock sends more sims to the shootout, whose winner is drawn from the goal-rate share).

## Tests (`tests/test_nhl_live_overtime.py`, 12)

Each on-test has an off twin on the same seeds that shows the defect. Engine: OT sims end one past the tie
(off: some end 2+); on IS off cut at its first goal (same team, same `t`); OT clock 0:00 goes straight to the
shootout (off played OT goals); fewer OT goals at 1:00 than at 5:00 (off: identical); a tied P3 0:30 state's
regulation events and regulation endings identical seed for seed; pregame never turns it on (signature default
False; the opening-faceoff resume with it off equals `run_hockeysim_game` on 60 seeds); the cut's no-event
fallback. live_resim: reachability off != on; regulation histogram identical mid-game; the env switch; the
published lane carries `liveOvertime` and a one-goal OT.

Mutations, each caught: the cut removed (6 fail), the clock ignored (2 fail), cutting at the LAST goal (2 fail).
Neighbouring suites: 247 passed (NHL live + hockeysim engine / pp-time / calibration / adapter / projection).

## Replay (the total fit and the grade, OT on vs off, same inputs)

`C:\tmp\nhlrec\replay_ot.sh`, 2026-11-13 20:04-20:39Z: the worktree's producer, production's inputs read-only,
both arms in parallel on the same inputs and window as the total fit (301 games / 43 dates, 2026-10-01..11-12,
2,408 cutoff states, 200 sims, seeds per state), end-game off in the stored rows (applied in expectation below).
**The off arm reproduces the total fit exactly** (keep 0.85 / 240 s, CRPS 0.669213, the same out-of-sample
table), so the inputs are the fit's and the on arm differs by the OT rule alone. Regulation histograms are
identical in all 2,408 states. Of the 2,408 states, 544 come from real games that went to OT or a shootout; 0
of those finals ended more than one past the tie.

**Paired, game-clustered bootstrap (2,000 resamples over 301 games), on - off** (`C:\tmp\nhlrec\ot_paired.py`):

| | raw (end-game off) | with production's end-game (0.38, 90 s) |
|---|---|---|
| +-1.5 Brier | +0.00050 [+0.00024, +0.00077] | **-0.00012 [-0.00039, +0.00016]** |
| moneyline Brier | +0.00016 [-0.00004, +0.00037] | same (the end-game never changes a winner) |
| total absolute error | -0.0143 goals [-0.0181, -0.0108] | same |

- **The total gets better**, outside the noise. **The puck line as shipped is neutral.** Raw, it is worse: the
  engine's margin is already too narrow (realised/model width 1.05-1.25 by cutoff), and the impossible OT goals
  were widening it by accident. The end-game, which exists to restore the late width, takes that back.
- **The moneyline is within noise** (+0.00016, interval spans 0). It changes only in sims that reach OT: the
  winner is now the first scorer, and an OT that would have ended level after 5:00 is now decided by its first
  goal rather than the shootout.

**The shipped calibrations still fit; neither is changed:**
- Total keep, refit on the on arm: keep 0.85, window 300 s (shipped 240 s), CRPS 0.665652; walk-forward keep
  [0.82, 0.86], window [120, 300]. Best keep at the shipped 240 s window: 0.86. Out of sample the shipped ON bias
  is within -0.17..-0.05 by cutoff (off arm -0.17..-0.01), pooled CRPS on - today -0.0168 [-0.0351, +0.0015]
  (off arm -0.0172).
- End-game (the harness's own +-1.5 Brier): on arm at the shipped 0.38 / 90 s **0.111094**, at its refit
  0.43 / 120 s 0.111062 (0.00003 apart); off arm at 0.38 / 90 s 0.111266. Walk-forward p [0.37, 0.57], ramp
  [90, 120] (off arm [0.35, 0.55], [90, 120]).

## What remains, not fixed here

1. **The pregame path keeps the old OT** (`run_hockeysim_game` never passes the flag). It feeds the pregame
   totals, puck line and OT player stats. Changing it is a pregame mechanism change with its own grade.
2. **The rest of the CURRENT regulation period is played as overtime on every live resume** (lead in
   `leads.md`, 2026-11-13): the engine infers OT from `T != seconds_per_period`, and a resume's first period is
   always short. Found while reading this OT block; not touched here because it changes regulation play and the
   priced moneyline, and the total keep and the end-game were fitted on top of it.
3. **The shootout winner** is drawn from the two teams' goal-rate share, clipped to [0.25, 0.75], not a measured
   shootout rate.
4. **Playoff OT** (20-minute 5-on-5 periods, no shootout) is not modelled; regular season only.
