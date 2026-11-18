# Why the NBA live re-sim's total starts high, and the fix (todo #834, lane nba-live-resim-total-anchor)

2026-11-18, 11:45 AM CST. Asked by the engine-learner lane's brief (`brief_2026-11-17_engine_read_kalshi.md`): the NBA
live re-sim's total starts ~2 points above Kalshi's and loses to it. **Read-only on the fleet; nothing deployed,
restarted or written there.** Substrate: `fleet` (the fleet's own artifacts under `~/syndicate-prod/data`, read in
WSL at nice 19). Scripts in `C:\tmp\t834\` (`decomp.py`, `offset_by_week.py`, `totals_ladder_fixed.py`,
`ladder_analysis_path.py`) and `scripts/replay_nba_live_total_anchor.py` (branch `nba-live-total-anchor`).

**The hypothesis stated in the lane before any artifact was read is FALSIFIED.** It said the pre-sim market blend
(total weight 0.7) leaves the target above the market. It leaves the target 3.1 points BELOW the market. The excess
comes after that, from the engine.

## 1. The trace (file:line, the same chain the margin trace #780 walked)

```
basketball_props_smart_sim._simulate_quarters_local            shared/basketball_props_smart_sim.py:1150
  raw team means from ratings x pace (+ adjustments, totals calibration)            :1190-1205
  -> _apply_market_anchor_local: total blended toward market_total at total_w 0.7  :95-130, :1211-1220
     (total_w from processed_root/quarters_blend_weights.json, default 0.7          :918-935)
     records market_anchor {market_total, model_total_raw, anchored_total}        :1226-1238
  -> quarter means -> orchestrator sums them into target_home/away_points
                                       basketball_engine/orchestrator/smart_sim.py:1568
  -> engine kwargs persisted once per game: _persist_engine_inputs_once_local
     -> nba/live_resim.persist_engine_inputs (keys _INPUT_KEYS incl. targets)   nba/live_resim.py:109-114, :315
  -> pregame engine run: simulate_pbp_game_boxscore steers efficiency toward
     target points per possession; NBA uses the LOOSE solver
     (league.py:108 exact_target_calibration=False; clip 0.85-1.15)            basketball_engine/engine.py:1114-1131
     writes smart_sim_<date>_<H>_<A>.json score.total_mean (REGULATION only:
     home_scores = sum of quarters)                    orchestrator/smart_sim.py:1739, :2485-2488
live tick (live-odds-worker):
  load_engine_inputs (the same persisted kwargs)                               nba/live_resim.py:383
  -> resim_live_game: same engine, resumed from the live state; full-game
     total INCLUDES overtime (#763)                                            nba/live_resim.py:533-606
  -> apply_margin_anchor (#780: margin only)                                   nba/live_resim.py (tick)
  -> build_game_lens: projection.total = total_mean, totalRunsDist             nba/live_resim.py:1137-1182
  -> live evidence log / board join (totals priced off totalRunsDist,
     tempered by k 2.16)                 shared/live_gameline_join.py:1282-1314, :1510
```

## 2. Where the gap comes from: the 32 dev games of the engine read

The engine read's dev games (11-09..11-14 ex 11-12), each with a first live row at <= 3% elapsed. Every hop is a
per-game difference in points, mean (se) over 32 games (`decomp.py`; per-game table in its output):

| hop | mean (se) |
|---|---|
| live first row - Kalshi's ladder total (the defect) | **+1.95 (0.77)** |
| closing book total - Kalshi | -0.37 (0.50) |
| the sim's `market_total` - the close | +0.00 (0.08) |
| raw model total - `market_total` | -10.39 (1.09) |
| anchored target - `market_total` (the 0.7 blend) | **-3.12 (0.33)** |
| persisted `target_home+away_points` - anchored target | +0.00 (0.00) |
| pregame ENGINE output - its own target | **+4.83 (0.62)** |
| live first row - pregame engine output | +0.61 (0.70) |
| pregame engine output - the close | +1.71 (0.73) |

**Two errors of opposite sign, and the engine's wins.**
- The pre-sim blend leaves the target 3.1 points under the market, because the raw model sits 10.4 under it.
- The engine then overshoots its own target by 4.8 points, about 2.2%.
  - It is roughly a constant: slope -0.18 on (market - target) and -0.09 on the target.
  - It is the total's twin of the margin trace (`findings_2026-11-13_nba_live_anchor_trace.md`): the NBA engine
    follows its target only loosely. NBA runs the loose solver; WNBA runs the exact one.
- The live first row adds +0.6 more, partly overtime: the pregame sum is regulation-only, the live total is not.
- **Not pace and not the spread** (the engine read already showed both).

## 3. It is not a fixed 1%: the pregame level drifts week to week

Every NBA pregame artifact on the fleet, by slate week (`offset_by_week.py`), mean (se):

| week | games | engine - close | anchored target - market | engine - its target | raw model - market |
|---|---|---|---|---|---|
| 10-21..10-25 | 40 | -0.94 (0.84) | -4.55 (0.26) | +3.69 (0.72) | -15.15 (0.87) |
| 10-26..11-01 | 49 | -1.68 (0.65) | -4.07 (0.24) | +2.37 (0.57) | -13.57 (0.81) |
| 11-02..11-08 | 54 | +0.31 (0.49) | -3.86 (0.22) | +4.21 (0.45) | -12.85 (0.75) |
| 11-09..11-14 | 42 | **+1.90 (0.60)** | -3.10 (0.27) | +5.02 (0.52) | -10.34 (0.90) |
| **11-18, after F1** (pregame artifacts only) | 12 | **+6.78 (1.04)** | +0.28 (0.67) | +6.46 (0.62) | +0.94 (2.24) |

- In late October the engine sat UNDER the close; by the dev week it sat 1.9 over. A flat "-1%" scale would have
  pushed the October totals further under.
- **Since F1 (`#821`, switched on 2026-11-17 17:35Z) it is 3.5x worse.**
  - F1 feeds the game model's total, so the raw model now sits at the market (+0.94), and the blend leaves nothing
    to cancel the overshoot.
  - The engine's +6.5 overshoot comes straight through: **today's 12 pregame totals sit +6.8 (se 1.0) above the
    close.**
  - Unless something changes, tonight's live NBA totals start about 7 points high and lean to the over.
  - The read used today's PREGAME artifacts and closes only. No outcome, Kalshi quote or evidence row in M2's
    11-15..11-22 window was read.

## 4. The fix: a per-game total anchor (ON MAIN `88193c0a7`, 2026-11-18 ~12:35 PM CST, user "Yes, push it"; built as `7dfa1f7fa`; default off, not loaded)

The #780 margin anchor's rule, applied to the total, in `syndicate/features/nba/live_resim.py` "total anchor":
- the full-game total histogram moves by (closing consensus total - pregame SmartSim `score.total_mean`) x the
  share of REGULATION still to play, and its mean is re-derived;
- the close is each book's last full-game OVER line before the commence, median across books
  (`college_basketball/prior_calibration.closing_totals`, the same quote log the margin anchor reads).

It is per game, so it removes whatever the engine's level is that week, in either direction.

- **ABSENT IS OFF**: `SYNDICATE_NBA_LIVE_TOTAL_ANCHOR=on` (1 / true / yes). Off = the lane is byte-identical: no new
  keys, and the anchor is never looked up.
- NBA only. The margin, P(home), segments, live props and `overtime_prob` are untouched.
- No anchor is not a refusal: the raw total is served with `totalAnchorRefusal` (`no_pregame_sim_total` /
  `no_closing_total`).
- Provenance:
  - on the lane: `rawModelTotal` and `totalAnchor` {marketTotal, simTotal, offset, books, remainingFraction,
    appliedOffset};
  - in the history: `total_raw` and `total_anchor`;
  - on the tick line: `total_anchored=` and `total_anchor_missing=`, last on `NBA_LIVE_RESIM_TICK`.
- **Known residual:** at the tip the anchored total is the close plus the engine's overtime points (~+0.2, at its ~2%
  overtime rate).
- **Tests:** `tests/test_nba_live_total_anchor.py`, 27, reachability first.
  - `off != on` through `build_live_lens_snapshot`, and through the board join's totals pricer.
  - Plus: the math, the close rule, the refusals, WNBA, the cache, the history and the tally.
  - 93 passed with `test_nba_live_margin_anchor.py` + `test_nba_live_resim.py`. The 67 in the other NBA/WNBA
    live re-sim files also pass.

## 5. Before / after on the engine read's own rows

`totals_ladder_fixed.py` is `C:\tmp\elp\engine_read\totals_ladder.py` (row selection, M3's Kalshi placement, the
probit ladder fit), plus ONE step. Each evidence row's histogram goes through the worktree's `total_anchor_for` +
`anchor_total_result` with `remaining_regulation_fraction(period, clock)`: the tick's own calls.
- **Reproduction is exact:** the same 1,939 rows / 37 games; 0 rows differ from the engine read's file in the raw
  total, Kalshi's total, the sd or the clock. The mean moved by the applied offset to 4e-14.
- 37 of 37 games have an anchor, mean offset -1.64.
- `ladder_analysis.py` is run unchanged except its input path.

| clock | rows | re-sim - Kalshi, BEFORE (se) | AFTER (se) |
|---|---|---|---|
| 0-25% | 355 | +1.78 (0.40) | **+0.30 (0.41)** |
| 25-50% | 443 | +1.24 (0.42) | +0.12 (0.44) |
| 50-75% | 635 | +1.10 (0.43) | +0.39 (0.47) |
| 75-95% | 408 | +0.02 (0.23) | -0.21 (0.23) |
| 95%+ | 98 | +0.32 (0.70) | +0.28 (0.70) |
| first row <= 3% | 32 games | +1.95 (0.77) | **+0.25 (0.70)** |

- **Goal met: the 0-25% gap is inside +/-0.5.** The rule has no fitted parameter, so nothing was tuned on these rows.
- The spread is unchanged (sd ratio 1.05-1.09).
- Rest-of-game rate level a: +0.010 -> +0.002.
- Per game at the first row: sd 4.36 -> 4.01, mean |gap| 3.62 -> 3.17 (`decomp.py`). The pregame artifact's own
  100-draw noise does not cost more than the per-game engine error it removes.

## 6. Against finals, and the totals probability scale (model_engine_standard 4.4)

`scripts/replay_nba_live_total_anchor.py`, fleet history + ledgers 10-21..11-14 (M2's 11-15..11-22 held out):
- 185 of 185 games anchored; mean offset +0.13 (mean |offset| 3.33).
- 26,402 ledger totals states / 173 games, re-priced raw vs anchored with the join's own `price_distribution_market`.

| | result |
|---|---|
| Brier anchored - raw, k = 1 | -0.006 +- 0.008 (tip -0.014 +- 0.015, early -0.017 +- 0.013, mid -0.001, late +0.001) |
| model - books' fair, k = 1 | raw +0.001 +- 0.012 -> anchored -0.005 +- 0.009 |
| k fitted, raw | **2.327** (walk-forward 2.28-2.36) |
| k fitted, anchored | **1.843** (walk-forward 1.80-1.86) |
| model - books' fair at the fitted k | raw -0.006 +- 0.005; anchored -0.008 +- 0.005 |
| model - books' fair at today's k 2.16 | raw -0.006 +- 0.006; anchored -0.008 +- 0.004 |

- As 4.4 predicts, the scale absorbed part of the bias: anchored totals want k 1.84, not 2.16.
- On Brier, 2.16 and 1.84 are equal on anchored totals (-0.008 both), so the anchor can load with k unchanged.
- An anchored-k table entry (the `_SPREADS_PROB_SCALE_ANCHORED_BY_SPORT` pattern, nba 1.84) is the second half,
  for `live_gameline_join.py`. It is not in this lane's files; it is the user's call.
- Against the BOOKS, the anchored total is better on point but inside noise. The engine read's measure is against
  KALSHI's price.

## 7. What it does not fix: leads for the owners

- **The root cause is the engine's overshoot** (`engine.py:1114-1131`, the loose NBA solver).
  - It inflates every live NBA quantity the anchor does not touch: segment totals, and the player remainders the
    live props price.
  - Since F1 it is about +6.5 points a game.
  - Owner: lane `basketball-scenario-calibration`. A solver change is a mechanism in a calibrated engine (4.4),
    with a re-fit.
- **F1's keep/revert grade (`#821`, due ~12-06)** should read the live re-sim's total level as well as the pregame
  served numbers. On the evidence above, F1 roughly tripled the live total's lean.

## 8. To load (the user's decision; betting change: yes)

**Hold LIFTED, 2026-11-18 ~11:55 AM CST.**
- **The decision:** the user's "Yes, lift it", typed in the decision-engine session (local_898e5510) and relayed from
  there. The question was "Lift the 11-22 load hold for the NBA total anchor (#834)?".
- **Why:** F1 (#821, on since 11-17 11:35 AM CST) already moved the NBA re-sim's starting totals inside M2's window.
  So the hold no longer keeps that window on one re-sim, and it would cost ~4 more nights of the over-lean.
- **Scope:** #834 only; #836's hold stands. M3 picks up an anchor load as a new NBA version; the M2/M3/re-run notes
  carry the F1 correction (`89ff009f2`).
- **Still owed:** the push and the load each need the user's own yes in this lane's session. The load is a betting
  change.

The original hold, kept for the record:

**Load hold (superseded):** proposed 2026-11-18 ~12:00 PM CST by the decision-engine session (local_898e5510).
- **The hold:** load nothing before 2026-11-22 ends.
  - M2's test window (11-15..11-22) and the learner re-run window end then.
  - Holding keeps both windows on the re-sims they started with.
  - After 11-22, M3 tags each bet with the live re-sim version (`findings_2026-11-17_m3_paper_book.md` Addendum 5).
- **The cost of the hold** (§3): about 4 more nights of live NBA totals starting ~+6.8 high. The user weighs that.
- **A push to main is not a load:** absent = off, so a fleet ff without the env key changes nothing.

1. The user's yes to push `nba-live-total-anchor` to main.
2. Fleet ff to that SHA.
3. `LIVE_ODDS_WORKER__SYNDICATE_NBA_LIVE_TOTAL_ANCHOR=on` in `local_production.env`, then a drained full `down`/`up`,
   behind the deploy claim and preflight.
   - live-odds-worker is the role that runs the NBA live re-sim: its log carries 196 `NBA_LIVE_RESIM_TICK` lines in
     its last 80 MB, refresh-worker's 0. Read 2026-11-18 ~11:50 AM CST.
4. Verify on the first live NBA ticks after the load:
   - the tick line's `total_anchored=` equals the fresh lanes;
   - the history's `total_anchor.offset` matches close - `score.total_mean` for each game.
