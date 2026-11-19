# NCAAF live re-sim totals: anchored to the close and widened (todo #835, 2026-11-19)

Lane `ncaaf-live-total-dispersion`. The task came from the decision-engine session (local_898e5510) for #835, the open
item of the engine read against Kalshi (`findings_2026-11-17_engine_read_kalshi.md`). Kit (scratch, reproducible):
`C:\tmp\t835`. The original kit `C:\tmp\elp\engine_read` was copied, never edited.

**M2 discipline.** Nothing from slates 11-15..11-22 was read. `C:\tmp\elp\m2gate_kit\test`, `...\out` and
`C:\tmp\elp\m3_kit\live` were never opened. Every script refuses those dates until `m2_verdict.txt` exists. One
exception, deliberate and bounded: the 11-14 slate's late games were logged after midnight UTC into the fleet's
`live_evidence/ncaaf/2026-11-15.jsonl`. That file was read only through a hard cut at 10:00Z 11-15 (4 AM CST); later
rows were discarded on their `t` and never kept or printed. The engine read's own 11-14 opinions already pointed at
those rows (latest `evidence_t` 06:00Z).

## Verdict

**FIX BUILT, DEFAULT OFF. Every done-criterion is met on 11-14.** The multi-Saturday outcome test, run on the shipped
schedule, holds on the three Saturdays not used to choose it.

| 11-14, the engine read's own instruments | production | fix (anchor + k 1.2 -> 1.6) |
|---|---|---|
| sd ratio vs Kalshi's ladder, median, 0-25 / 25-50 / 50-75 / 75-95% | 0.85 / 0.81 / 0.84 / 0.75 | **1.02 / 0.97 / 1.05 / 0.96** |
| same, like-for-like (the re-sim's own ladder probit-fitted) | 0.85 / 0.82 / 0.86 / 0.84 | 1.01 / 0.99 / 1.10 / 1.20 |
| median abs(centre - Kalshi's), pts | 4.0 / 3.0 / 2.9 / 2.5 | **1.5 / 1.5 / 1.5 / 2.0** |
| mean centre - Kalshi's, pts (game-clustered se) | +0.2 (1.7) / +0.4 / +0.9 / +2.2 (0.6) | -0.5 / +0.0 / +0.3 / +2.0 |
| slow games (pace < -5%): rest-of-game pace over the pregame rate | +9.7% (Kalshi +2.0%) | +6.0% |
| calibration slope vs outcomes, ncaaf\|totals (1,944 line-instants, 55 games) | 0.41 | **0.95** |
| by clock bucket | 0.41 / 0.23 / 0.51 / 0.58 | 1.55 / 1.33 / 0.94 / 0.65 |
| log loss, re-sim minus Kalshi (se) | +0.077 (0.054) | **+0.014 (0.016)** |

The 1,944 line-instants are the engine read's own: same examples, same opinions, same evidence rows, re-priced through
the expert's own rule (`two_way_share`, then Agresti-Coull). The identity transform reproduces every one of them, all
1,944 k and p, and slope 0.41, d_ll +0.077 (0.054) and Kalshi's 1.35. The 630 ladder rows are the engine read's 630,
identical in every field. In the fix column, the re-sim beats Kalshi at 0-25% (-0.034, se 0.013) and still loses at
50-75% (+0.074, se 0.020).

## Diagnosis (hypotheses written into the lane before any test)

- **H-WIDTH: TRUE.** Widening alone by 1.2x puts the sd ratio at 1.02 / 0.97 / 1.00 / 0.84, but the slope moves only
  from 0.41 to 0.50. Even 2.0x reaches only 0.78, at an sd far wider than Kalshi's. The spread was not the main cost.
- **H-CENTRE: TRUE.** The live engine's own kickoff total (E0) sits a mean |5.7| points from the closing consensus total,
  with sd 7.95 and correlation 0.43 over 55 games. The live level shrink (`total_level.py`, 0.3) compresses each game
  toward the league; the market knows the game. Kalshi's kickoff centre sits 0.4 pts from the close (13 games).
  Anchoring is what moves the slope (0.41 to 0.95).
- **H-CATCHUP: PARTLY TRUE.** The anchor removes about 40% of the slow-game catch-up (+9.7% to +6.0%; pace weight -0.136
  to -0.082, Kalshi -0.023). The rest is not level. It is the engine's own game-state dynamics.
- **H-ESTIMATOR: TRUE late.** At 75-95% the moment sd of a lumpy late histogram reads below its probit width: production
  0.75 vs 0.84, k 1.2 0.84 vs 0.99. The two instruments disagree most where the histogram is lumpiest.
- **H-ENDGAME: SUPPORTED, NOT FIXED HERE.** At 75-95% the re-sim expects the rest of the game at 1.29x the close's even
  pace (mean; median 1.15). Kalshi expects 0.82x (median 0.91). The late mean gap (+2.0 to +2.2) survives the anchor,
  because the anchor's offset is small by then. The likely seat is smartsim2's end-game: for NCAAF it has no kneel-out
  or clock management (#808's mechanisms stay off there). That is an engine mechanism plus a re-fit, owned by the
  smartsim2 lanes. Lead below.

## The fix

`syndicate/features/ncaaf/live_total_dispersion.py`, switch `SYNDICATE_NCAAF_LIVE_TOTAL_CALIBRATION`. **Absent is off.**
`on` / `1` / `true` / `yes` turn it on. It is two estimator steps on the 120 draws the engine already made. There is no new
mechanism and no engine input changes (`model_engine_standard.md` 4.4):

1. **Anchor** (#834's NBA rule): every draw moves by (C - E0) x rho.
   - C is the closing consensus total, read by #834's own reader (`prior_calibration.closing_totals`: each book's last
     OVER line before the commence, median across books).
   - E0 is `resim_live_game` at Q1 15:00, 0-0, possession unknown, with the same ratings and sims (the
     resume-at-kickoff identity).
   - rho is the share of regulation left.
2. **Widen**: every draw's distance from the moved mean is scaled by k, then floored at the score already on the board.
   - k is 1.2 through half-time and ramps linearly to 1.6 at 95% of regulation, then holds.
   - The floor is mean-preserving: the excess it adds is taken back from the draws above it. A plain floor raised the
     75-95% mean by 0.3 and would have been a centre change made by a spread step.

**Where it runs:** a post-pass on the built snapshot inside `run_refresh_worker._run_ncaaf_live_resim_tick`, before the
snapshot is validated and written. The tick's own ratings are used, so E0 is the same engine on the same inputs.
- `ncaaf/live_resim.py` is not edited: lane `live-player-exit-gate` holds it. The tick call sits in a section of
  `run_refresh_worker.py` disjoint from lane `nfl-live-possession-map`'s.
- Off: the transform never runs (test-pinned with a function that fails if called). The snapshot and the tick's status
  are byte-identical (test-pinned through the tick).

**Inputs, and what is counted:**
- C is looked up in the tick's UTC-date quote-log shard, then the day before, so a game still running after midnight
  UTC finds its close.
- E0 is computed once per game per process: about 2 s at 120 sims on the fleet's data, 1.8-2.3 s measured over 58
  games. A tick computes at most 8.
- A game without C or E0 is still widened and named: `anchorRefusal` is `no_closing_total`, `no_kickoff_total` or
  `kickoff_total_pending`.
- Each lane carries `projection.totalCalibration` (marketTotal, kickoffTotal, offset, appliedOffset, books, k,
  remainingShare, rawTotal). The snapshot and the tick's status carry a tally (anchored / widened only, by reason), so
  the fleet can count fed vs absent.

**Left alone:** the margin, the win probability, `marginDist` and the segment blocks. The segments are display only;
under the switch h1 + h2 no longer sums to the full-game draw.

**Knobs:** `SYNDICATE_NCAAF_LIVE_TOTAL_CALIBRATION_K` (default 1.2) and `..._K_LATE` (default 1.6). A typo or a
non-positive value falls back to the default, never to "no widening".

**Tests:** `tests/test_ncaaf_live_total_dispersion.py`, 42 passed.
- Reachability first, through the worker's tick: absent never runs the transform; off is byte-identical to absent; on
  changes the published `totalRunsDist` and nothing else on the lane; the published `total` is the histogram's mean;
  the calibrated histogram is the one the real join indexes.
- Then E0 = the kickoff re-sim, computed once; the per-tick cap; a missing close widens and names why; refused lanes
  are untouched; the previous-shard fallback; the transform's mean, spread, floor and centre; the k schedule; typo
  fallbacks.
- The neighbouring suites pass: 123 tests across the NCAAF re-sim, wiring, blend, shrink, player-exit and segments
  files.

**Reproduction gate:** the 11-14 kickoff replay (production's ratings path for week 11, the worktree's `resim_live_game`)
reproduces the published kickoff histogram **bit for bit in 7 of the 8 games** that have a kickoff row. The 8th, Miami-Duke,
most likely had possession known at kickoff, which the evidence row does not record.

## Beyond one Saturday: the finals of 159 games (live gameline ledger, four Saturdays)

The evidence log starts 11-09, so 11-14 is the only Saturday with both evidence and a Kalshi ladder. 11-11 and 11-13 have
NCAAF evidence but no placeable Kalshi totals: these midweek games were not listed.
- **Population:** the fleet's live gameline ledger. It keeps the re-sim's mean and P(over) at every priced state since
  10-01. Its clock comes from the in-play recorder's ESPN polls (10-24, 10-31, 11-07, 11-14). Checked against the
  evidence log's exact clocks on 11-14: median difference 0, p90 27 s of game clock.
- **Inputs and finals:** C and E0 as production builds them, per week. Finals are from ESPN.
- **Pricing:** a normal approximation with the engine's own sd by time left, fitted on 3,848 11-14 histograms
  (sd = 0.61 + 12.82 sqrt(rem), residual 0.77). Its production twin reproduces the raw P (slope 0.44 vs 0.45; log loss
  within 0.004).
- **Weighting:** each (game, line) counts once; SEs are clustered by game.
- 10-03 / 10-10 / 10-17 have no recorder clocks and are not scored.

| finals, log loss / calibration slope | 4 Saturdays, 159 games | hold-out: 10-24, 10-31, 11-07 (109 games) |
|---|---|---|
| production raw P | 0.692 / 0.45 | 0.706 / 0.41 |
| widen only, k 1.2 | 0.676 / 0.54 | - |
| anchor + k 1.2 flat | 0.637 / 0.86 (75-95%: 0.55) | 0.639 / 0.84 (0.56) |
| **anchor + k 1.2 -> 1.6 (shipped)** | **0.634 / 0.94-0.96** | **0.636 / 0.94** (75-95%: 0.73) |
| revert to the close's even pace (S + C rho) + k 1.2 | 0.634 / 0.90 | - |

- **What the board PRICES today**: raw P tempered by #780's k 2.48 (`live_gameline_join._TOTALS_PROB_SCALE_BY_SPORT`).
  The fix at join k 1 beats it by **-0.0230 nats (se 0.0081)** over the four Saturdays, and **-0.0262 (se 0.0093)** on
  the hold-out alone. On the fixed totals the best join k is 1.05: flat over 1.0-1.1 at 0.6335-0.6339.
- **Revert vs anchor.** "Revert" pins the rest of the game to the close's even pace. It scores the same on log loss, but
  it sits 1.4-1.7 pts under Kalshi early on 11-14 (finals +1.9 above it early, vs +1.6 for the anchor). Football does
  not score evenly in time: Kalshi's own rest-of-game pace runs 1.03-1.05x the even pace in the first half. The anchor
  keeps the engine's game-state information and its time shape. Chosen.
- **The late k**: 1.5 / 1.6 / 1.8 give a hold-out 75-95% slope of 0.69 / 0.73 / 0.81 and an 11-14 late sd ratio of
  0.93 / 0.96 / 1.02. 1.6 is inside the brief's band and nearer Kalshi's like-for-like late width (1.20 vs 1.28).
- **Books are no comparator here**: the ledger's fair at a book's own main line sits near 0.5 by construction (log loss
  0.688).

## Loading it: the user's yes, in a betting-change window

- **Code:** branch commit in the lane's worktree, NOT on main. The push is the user's call.
  - An ff that carries it changes nothing: absent = off, betting change: no.
- **Switch-on:** a betting change (it changes NCAAF live totals probabilities, so it changes which bets are placed).
  - Only in a window (`.syndicate/betting_change_windows.md`). The next after 11-24 is **Tue 12-08, 2-7 AM CST**.
  - Only on the user's own yes in that session.
  - It needs a claimed, drained full `down`/`up`, preflight `--betting-change yes`, `betting_change.py add`, and
    deploys.md.
- **Two keys, together**, in `~/syndicate-prod/local_production.env` (global, so every role that builds or joins sees
  them):
  - `SYNDICATE_NCAAF_LIVE_TOTAL_CALIBRATION=on`
  - `SYNDICATE_LIVE_TOTALS_PROB_SCALE_NCAAF=1`, the re-fitted join k. **Do not load the switch without it.** k 2.48 was
    fitted on the un-calibrated totals' over-confidence and would correct it twice.
- **M3:** its morning capture records the switch as a new NCAAF live version on its own. The earliest load is the 12-08
  window.
- **Verify after the load**, both readings named in advance:
  - `last.total_calibration` in the NCAAF tick's status: `anchored` > 0 on the first Saturday ticks, `kickoff_sims` <= 8
    per tick.
  - On the evidence log, rows carry the calibrated `totalRunsDist`, the ladder sd ratio sits at 0.95-1.05, and
    `scripts/betting_change.py` registers it.

## PRE-REGISTERED: what 11-21 should show (written 2026-11-19, before any 11-21 data was read)

Run: `bash /c/tmp/t835/check_slate.sh 2026-11-21 12`, only after `C:\tmp\elp\m2gate_kit\out\m2_verdict.txt` exists (it
refuses before). Then 11-28 with week 13 once that slate is played. For the engine read's outcome instrument on those
dates, set `T835_EXAMPLES` / `T835_OPINIONS_DIR` to the learner's re-run outputs (scheduled 11-24 6 PM CST). Without
them the ledger's finals instrument still runs.

**Expected under the fix:**
1. Ladder sd ratio (moment, the engine read's instrument) inside [0.95, 1.05] in at least 3 of the 4 buckets, and all
   4 inside [0.90, 1.10].
2. Calibration slope >= 0.8 on the ledger's finals (and on the engine read's line-instants if available). Expected
   0.85-1.05.
3. Median |centre - Kalshi's| lower than production's in every bucket 0-95%. Expected about 1.5-2.0 vs production's
   2.5-4.
4. Priced log loss (fix at join k 1 minus production at k 2.48) <= 0. Expected -0.02 +- 0.01.
5. Production itself should read again as it did: sd ratio 0.75-0.90, slope 0.35-0.6.

**If 1 or 2 fails on 11-21 (or 11-28), the switch does not go on at 12-08**, and the miss is diagnosed first. 3 or 4
alone failing is reported and weighed. One Saturday is about 50 games: a single-bucket miss is noise until 11-28
agrees.

## Leads and follow-ups (not done here)

- **H-ENDGAME:** smartsim2's NCAAF end-game scores too much late. The rest-of-game pace at 75-95% is 1.29x the close's
  even pace vs Kalshi's 0.82x, and the mean gap stays +2 late. #808's kneel-out / clock mechanisms are off for NCAAF.
  An engine mechanism and re-fit belong to the smartsim2 lanes (`football-scenario-calibration` holds the files).
- **The cutoff-replay harness** (`scripts/backtest_ncaaf_live_totals.py`) grades `resim_live_game` and does not see a
  post-pass made in the tick. If the switch goes on, it should apply `calibrate_total_draws` too, or it will grade the
  raw draws.
- **NCAAF spreads:** the same per-game level noise likely affects the margin. There is no NCAAF margin anchor
  (`marginAnchored` False). Not measured here.
