# NHL live re-sim: the live TOTAL fitted (todo #773, lane nhl-live-total-calibration)

2026-11-13, replays 14:18-15:49Z (8:18-9:49 AM CST). Session 87074b1f. READ-ONLY on production. User: "Yes, fit the
total" (the lead from `findings_2026-11-11_nhl_live_endgame_calibration.md`: the live total ran +0.81 goals high at
puck drop).

**Result: the early bias is gone, and nothing priced moves.** The board's live NHL total (the "Live proj." total)
ran +0.87 goals high at puck drop and +0.43 at P2 10:00 (full sample, 301 games). With the fit, every cutoff from
puck drop to P3 01:30 is within +-0.08 goals, and the total's CRPS improves 0.6950 -> 0.6692. Out of sample (202
games, 29 dates, each fit only on earlier dates): puck drop +0.795 -> -0.170 [-0.454, +0.131], P2 10:00 +0.334 ->
-0.080, pooled CRPS -0.0172 [-0.0366, +0.0014].

**Recommendation: LOAD for the display** (live-odds-worker, the producer). It is display-only end to end, and the
margin, the puck line and the moneyline are byte-identical to today (pinned by tests). **Pricing is untouched**:
NHL live totals are refused at the join for want of a total distribution (161 of 161 rows 11-09..11-11), and this
publishes none.

## What ships (`syndicate/features/nhl/live_resim.py`)

`NHL_LIVE_SCORING_CALIBRATION = {goal_scale 1.0, total_keep 0.85, total_keep_late_seconds 240, count_endgame_in_total True}`.

- **Total-only thinning.** After each sim, its REGULAR-PLAY goals (regulation goals after the live state with more
  than 240 s of regulation left) count in the total with probability 0.85 (`thin_total`, its own RNG). Goals in the
  last 4 minutes, OT goals and the shootout credit always count. The engine's draws are untouched, so the margin
  histogram, `modelHomeWinProb`, the end-game and `raw_total_dist` are today's exactly.
- **The end-game's empty-net goals count in the total**, added after the thinning (they are not the engine's
  goals). The 11-11 end-game left them out only because the total's level was wrong; this is that re-fit
  (model_engine_standard 4.4).
- **Published:** `liveScoring {goal_scale, total_keep, total_keep_late_seconds, endgame_in_total, calibration}` at lane
  level, so a production reading can tell on from off. No pricer reads it.
- **Off switch:** `SYNDICATE_NHL_LIVE_SCORING_CALIBRATION=off` -> legacy (raw total, end-game out): today's numbers
  seed for seed (tests; and on production inputs, the final code's raw draws equal the first replay's on all 2,408
  states).
- **Not published, harness only:** `total_dist`, `raw_total_dist`, `regulation_one_goal_totals`, and with
  `record_sims=True` per-sim `[raw total, end-game seconds, [goal seconds-left]]`.

## Why not lower the engine's own scoring rate

The cause is the one the pregame path's `regulation_scale` (0.9398) corrects: the engine's per-shot goal chance is
`goals_per_60 / shots_per_60` (`engine.py:1844`), and `goals_per_60` is the projection's FULL-GAME rate (OT goals and
shootout credits included) used as a regulation rate. So the first thing measured was `goal_scale` on both teams'
`goals_per_60`: five replays at 1.00 / 0.95 / 0.90 / 0.85 / 0.80, same seeds, same states.

| out of sample, same 1,616 states | today | engine scale (walk-forward 0.85-0.90) | total-only (shipped) |
|---|---|---|---|
| total CRPS - today | | -0.0140 [-0.0330, +0.0044] | **-0.0172 [-0.0366, +0.0014]** |
| puck drop bias | +0.795 | -0.094 | -0.170 |
| +-1.5 Brier - today | | +0.00047 [-0.00021, +0.00119] | **0 (identical)** |
| moneyline Brier - today | | +0.00095 [-0.00022, +0.00227] | **0 (identical)** |

The engine scale fixed the total equally, and made the puck line and the moneyline slightly WORSE (within noise,
but the moneyline is a number the join can price). The margin was already too narrow (realised/model width >1 in
the 11-11 grade), and fewer goals narrow it further. So the engine is over-scoring AND under-spreading: the margin's
width is being propped up by the excess goals, plausibly against score effects that are too strong (the 11-11 grade
found the trailer's mid-game comeback over-predicted). Fixing the rate in the engine needs that second mechanism
re-fit with it. Until then the total is corrected on its own, and `goal_scale` stays 1.0 as the replay's knob.

Full-sample shape (end-game in the total), bias by cutoff: scale 1.00 +0.98 / +0.56 / +0.54 / +0.34 / +0.14 / -0.05
/ -0.04 / +0.00; scale 0.85 -0.07 / -0.15 / -0.01 / -0.02 / -0.05 / -0.15 / -0.12 / -0.04 (P1 20:00 ... P3 01:30).
End-game re-fit by scale: p 0.39 / 0.39 / 0.40 / 0.43, ramp 90-120 s; the shipped 0.38 / 90 s needs no change.

## Why a late window

One keep for the whole game (uniform) fixed the early bias but over-thinned the end: the keep that zeroes the bias,
cutoff by cutoff, was ~0.87 with 20+ minutes left and ~1.0 inside the last five. The engine's late play (6-on-5,
desperation) is not high; it is slightly LOW. Sparing goals in the last W seconds:

- walk-forward picked a window of 120-240 s on every one of the 29 out-of-sample dates (never 0);
- out of sample, late window minus uniform, each at its own walk-forward fit: **CRPS -0.0025 [-0.0045, -0.0007]**
  (202 games, bootstrapped over games): decisive;
- full sample: P3 05:00 bias -0.131 (uniform) -> -0.066, P3 03:00 -0.097 -> -0.043.

## Population and provenance

- **Harness:** `scripts/backtest_nhl_live_puckline.py`, extended: `--goal-scale` (replay at an engine scale),
  `--scale-runs` (fit and grade the engine scale across replays), `--fit-total-keep` (the total-only fit), per-sim
  records on every replayed row, `total_hist` (any keep / window / end-game, exact), `crps_discrete`.
- **Run:** fleet host, nice 19, 3-4 workers, the WORKTREE's producer, production's inputs read-only
  (`build_slate_features(date, root=~/syndicate-prod/data/nhl_source)`), 200 sims. Code blobs in
  `C:\tmp\nhlrec\total_code_hashes.txt` (grid replays `live_resim.py` 686ff12942ae; record replay 1573f929b4a1).
- **Sample:** 301 completed REGULAR-season games on 43 dates (2026-10-01..11-12), 0 dropped, 0 refused; 8 cutoffs;
  2,408 states per replay. Walk-forward: 14 warm-up dates, 29 out of sample (202 games, 1,616 states).
- **PROVENANCE: LEAKY**, as in every NHL replay: the season rate files are rewritten daily and kept nowhere dated,
  so each game ran on rates that contain it. The keep measures what this engine over-scores given its
  best-informed inputs; the walk-forward range (0.82-0.85) is the honest spread. The rate files were rewritten at
  15:35Z during the record replay; the two 1.00 replays (14:19-14:54Z and 15:30-15:49Z) are identical on all 2,408
  states, so no replay straddles two vintages.
- **Objective:** mean CRPS of the total's distribution against the official final (shootout winner +1, as books
  settle and as the engine credits). Proper: a level error and a spread error both cost.

## Out of sample: today vs shipped (walk-forward), 202 games

| cutoff | today bias | end-game only | uniform | **shipped** | today CRPS | **shipped CRPS** | shipped bias 95% |
|---|---|---|---|---|---|---|---|
| P1 20:00 | +0.795 | +0.903 | -0.104 | **-0.170** | 1.2982 | **1.2430** | [-0.454, +0.131] |
| P2 20:00 | +0.428 | +0.538 | -0.147 | **-0.172** | 1.0300 | **1.0124** | [-0.419, +0.070] |
| P2 10:00 | +0.334 | +0.443 | -0.079 | **-0.080** | 0.8962 | **0.8781** | [-0.296, +0.136] |
| P3 20:00 | +0.123 | +0.228 | -0.115 | **-0.095** | 0.6867 | **0.6922** | [-0.263, +0.068] |
| P3 10:00 | -0.053 | +0.053 | -0.128 | **-0.083** | 0.5231 | **0.5277** | [-0.221, +0.058] |
| P3 05:00 | -0.194 | -0.088 | -0.182 | **-0.127** | 0.4533 | **0.4436** | [-0.256, -0.013] |
| P3 03:00 | -0.159 | -0.053 | -0.115 | **-0.065** | 0.3825 | **0.3641** | [-0.170, +0.034] |
| P3 01:30 | -0.109 | -0.007 | -0.043 | **-0.007** | 0.2849 | **0.2566** | [-0.096, +0.077] |

Pooled CRPS minus today: end-game only +0.0012 [-0.0084, +0.0114]; uniform -0.0147 [-0.0338, +0.0038]; **shipped
-0.0172 [-0.0366, +0.0014]**. Today's puck-drop bias interval was [+0.513, +1.100].

Full sample at the shipped fit (window 240 s, keep 0.85), bias / CRPS: P1 20:00 +0.003 / 1.2214, P2 20:00 -0.079 /
1.0184, P2 10:00 +0.080 / 0.8780, P3 20:00 +0.062 / 0.6850, P3 10:00 +0.034 / 0.5221, P3 05:00 -0.066 / 0.4288, P3
03:00 -0.043 / 0.3540, P3 01:30 +0.003 / 0.2459; pooled 0.66921 (today 0.69501).

## Falsification test (as registered in the lane)

- "No single scale brings BOTH the P1 20:00 and the P2 10:00 bias inside +-0.15": **not met by the hypothesis's
  failure.** The engine scale did (-0.094 / -0.093 out of sample); the level error is real. The SHIPPED total-only
  fit sits at -0.170 / -0.080 out of sample (puck drop just outside +-0.15 on the point, interval [-0.454, +0.131])
  and at +0.003 / +0.080 on the full sample.
- "Worsens the +-1.5 or the moneyline Brier beyond noise": the shipped fit cannot (identical by construction); the
  engine scale was within noise and in the wrong direction, which is why it is not shipped.

## Pipeline trace (what the change reaches)

1. `live_resim.resim_live_game` -> `total_mean` / `total_dist` (thinned + end-game), `liveScoring`.
2. `live_resim.build_game_lens` -> `projection.total` (= `total_mean`), lane `liveScoring`.
3. `live_gameline_join.py:1089` -> `total_mean`; `:1428` `live_display_block` (the Live column); `:2518` the board
   block. Totals price only from `totalRunsDist`, which NHL does not publish: refused
   `live_resim_published_no_distribution_for_this_market`.
4. The v6 ledger records `model_total_mean` on those rows (read-only; the grade's join is by `event_id`).

## What remains, not fixed here

1. **The last minutes are still slightly low** (-0.07 full / -0.13 out of sample at P3 05:00): the engine
   under-produces the trailer's 6-on-5 goals, the same miss as the 11-11 two-goal-lead finding. A trailer
   goalie-pull mechanism is its own fit; when it lands, the keep and window are re-fit with it.
2. **The engine over-scores and under-spreads at once.** A proper engine-level fix is the scoring rate AND score
   effects re-fit together; until then the total is corrected on its own.
3. **NEW defect (lead): a resumed OVERTIME state ends 2-3 goals past the tie in ~10% of sims** (stub game, 31 of 300
   from P4 at 2-2). Regular-season OT is sudden death, so a real game ends exactly one past the tie. The resumed-OT
   path seems to play OT as a full segment, then add a shootout. It affects live OT states' total and margin; the
   shipped thinning never touches OT goals, so it neither fixes nor worsens it.
4. **Pricing live NHL totals** would need a published total distribution and a grade of it (worst powered bucket,
   as `#499`); out of scope.

## Load (the user's decision)

- Producer on live-odds-worker: push to main; ff the fleet to that exact SHA; live-odds-worker claim, drain,
  preflight from an origin/main worktree; a claimed TERM. Nothing on web or refresh-worker changes.
- **Verify** on a live NHL game: the served snapshot's lanes carry `liveScoring.calibration = "on"`, `total_keep
  0.85`, `total_keep_late_seconds 240`, `endgame_in_total true`; the published total at puck drop sits ~0.9 below
  the raw engine total for the same state (~6.6 regular-play goals x 0.15 thinned, ~0.1 end-game goals added); the
  `displayMarginDist` and `modelHomeWinProb` are unchanged in kind.
- **Revert:** env `SYNDICATE_NHL_LIVE_SCORING_CALIBRATION=off` (`LIVE_ODDS_WORKER__` scope, a drained down/up), or
  revert the commit, ff, and a claimed live-odds-worker TERM.

## Reproduce

```
wsl -- bash /mnt/c/tmp/nhlrec/replay_total.sh 1.0 0.95 0.9 0.85 0.8         # engine-scale replays
wsl -- bash /mnt/c/tmp/nhlrec/replay_total_rec.sh 1.0                       # per-sim record replay
py -3 scripts/backtest_nhl_live_puckline.py --end 2026-11-12 --out-dir C:\tmp\nhlrec\total_fit5 --scale-runs "1.0=C:\tmp\nhlrec\total_1.0,0.95=...,0.8=C:\tmp\nhlrec\total_0.8"
py -3 scripts/backtest_nhl_live_puckline.py --end 2026-11-12 --out-dir C:\tmp\nhlrec\total_rec_1.0 --fit-total-keep
py -3 C:\tmp\nhlrec\keep_extra.py                                           # full-sample shape, late vs uniform CI
```

Tests: `tests/test_nhl_live_total_calibration.py` (23), reachability first (the total moves on vs off and the margin
and moneyline do not, through `build_live_lens_snapshot`). `tests/test_nhl_live_endgame_calibration.py`'s lane helper
now pins LEGACY scoring for its "end-game moves the margin only" contract. NHL live suites 98 passed; the 20
NHL-touching join / ledger / board suites 894 passed, 2 skipped.

Mutations (`C:\tmp\nhlrec\mutate_total.py`): **18 of 18 caught.** The first pass let 3 survive, each a weak test,
now strengthened: un-scaling ONE team's rate still lowered the total (the test now reads the rates the engine
receives); records with no goal times passed vacuous checks (a sim that ends in regulation must now account for its
total exactly); the scale walk-forward's test data could not tell its own date in or out (its out-of-sample date now
outweighs the training date).
