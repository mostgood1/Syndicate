# findings 2026-11-16 — the pregame smart-sim's `h2` histogram leaves out overtime (todo #820, lane nba-pregame-h2-ot)

Session e8ebbfe5, started from local_a619d7e1 (the #818 grade found this). Written 7:48 PM CST.
**Built default OFF and pushed to main. NOT loaded on the fleet: loading is the user's call.**

## 1. The mismatch, in code

- Producer: `syndicate/features/shared/basketball_props_smart_sim.py` `_SIM_DIST_SEGMENTS_LOCAL`
  has `"h2": (2, 3)` (0-based quarters 3 and 4). `_attach_sim_distributions_local` builds every
  segment from quarters only, and only `full` adds the recorded `hot` / `aot` (overtime points).
- Settlement: every rule the platform has puts all overtime in the second half:
  - `segment_actuals._NBA_SEGMENTS["h2"] = (3, 4, None)` (the board's live actual);
  - `bet_status_nba._OVERTIME_RULES`: all four books (DraftKings, FanDuel, BetMGM, Pinnacle)
    include OT in h2 (learnings 2026-10-29);
  - `bet_status_wnba._segment_points`: `h2` appends periods 5+;
  - the NBA live re-sim, `nba/live_resim._segments`, already adds OT to h2 (`#762`);
  - the #818 grader scores h2 with `segment_score_pair("nba", ...)`, which includes OT.
- So on a draw that goes to overtime, the pregame h2 total is short by that draw's OT points,
  and its h2 margin is off by the OT margin.

## 2. The mismatch, on real sim files

Substrate: the read-only copy of the fleet's NBA processed root that #818 graded,
`C:\tmp\nba_seg\nba_source\data\processed\`. It holds 197 `smart_sim_*.json` files (slates
2026-10-20 .. 11-15; 100 or 500 draws each, 20,100 draws in all). All 197 carry `score.dist`.
Means add exactly over draws, so the marginal histograms are enough:

| check | result over 197 files |
|---|---|
| max \|mean(h2) − mean(q3) − mean(q4)\| | 1.4e-14 (h2 is q3 + q4, nothing else) |
| max \|mean(h1) + mean(h2) − mean(regulation)\| | 2.8e-14 (h1 + h2 = regulation, not the game) |
| files where mean(full) > mean(h1) + mean(h2) | 176 of 197 (the sim drew OT, and h2 dropped it) |
| mean OT points per draw, full − regulation | min 0.00, median 0.46, max 1.40 |

Method, to re-run: for each file, take the mean of every segment's `total` histogram, then compare as in the
table. The script was session scratch (not kept); it is ~30 lines of `json.load` plus those sums.

**Side finding (a LEAD, not fixed or claimed here): the sim draws overtime about a third as often
as real games go to it.** A regulation tie is exactly a draw whose `regulation` margin is 0, so the
mass at 0 is the sim's P(OT):

- 411 of 20,100 draws: **pooled P(OT) = 2.04%**. Per-file median 2.0%, max 6.0%.
- Real: 11 of 192 graded games went to OT (5.7%, #818). The long-run NBA rate is around 6%.
- Median OT points per OT draw: 24.0, both teams, all OT periods.

So even with this fix ON, the pregame h2 gains only ~0.46 points on average, because the sim
rarely reaches OT. The #818 totals/h2 loss (+0.0273 Brier [+0.0110, +0.0444]) is consistent with
the missing OT. It is not shown to be caused by it, and this fix alone is unlikely to close it.
The regulation-tie rate is the bigger lever. That needs its own measurement on real games,
before any mechanism.

## 3. The WNBA shares the path

- `_attach_sim_distributions_local` is in the shared bridge and runs for both leagues
  (`_call_source_simulate_smart_game_local(league_code=...)`). The WNBA's `h2` is q3 + q4 too.
- The WNBA settles h2 with OT (`bet_status_wnba._segment_points`), so it has the same mismatch.
- **Consumers differ, and that matters for loading:**
  - NBA: `nba_game_projections._project_row` prices an h2 row from this histogram, then
    `served_game_probability` blends it. The fleet's `nba_game_book_blend.json` gives every period
    weight 0 (#818). So the SERVED h2 probability is the market's either way. A flip moves only
    `p_model_raw` and the raw `sim_ladder` the page draws (`layer2_board` `sim_ladder_raw_over`).
  - WNBA: `wnba_game_projections` has no book blend. It serves the raw histogram's probability,
    and the edge, on h2 rows. A WNBA flip changes served WNBA h2 probabilities and edges, so it is
    a betting change (`betting_change.py`). The WNBA is out of season (November).
- NBA/WNBA game chips show q1..q4 only (`game_chip_intervals.PERIODS`), so the display does not change.

## 4. The fix (main, default OFF)

- Switch, per league: `SYNDICATE_NBA_SIM_H2_INCLUDES_OT` / `SYNDICATE_WNBA_SIM_H2_INCLUDES_OT`.
  Only `1/true/yes/on` turns it on. Absent, empty or any other value is OFF.
  `_sim_h2_includes_ot_local(league_code)`. NCAAB has no switch, and its sim is not this one.
- `_attach_sim_distributions_local(..., h2_includes_ot=...)`, read at its one production call in
  `_call_source_simulate_smart_game_local`.
  - ON: each draw's h2 total and margin add that draw's `sum(hot)` / `sum(aot)`. Then
    h1 + h2 = full, and `score.dist` gains `h2_includes_ot: true`.
  - OFF: byte-identical to before. No stamp, h2 = q3 + q4.
- **A file without `h2_includes_ot` has the old quarters-only h2.** That holds for every
  production file today. Per learnings 2026-11-11, a grade or study over a window that includes a
  load must split on this stamp, not on the date alone.
- Tests: `tests/test_basketball_pregame_h2_ot.py` (18).
  - Switch parsing, per league.
  - OFF byte-identical.
  - ON: per-draw h2 = q3 + q4 + OT for total and margin; nothing else moves; no-OT draws are unchanged.
  - **Reachability through the real `_call_source_simulate_smart_game_local`, env unset != env set**,
    and the NBA switch does not reach a WNBA sim.
  - The served NBA h2 row's `p_model_raw` moves, 0.25 -> 0.50 on the fixture.
- Neighbouring suites were re-run green: `test_wnba_sim_distributions`,
  `test_basketball_orchestrator_reachability`, `test_basketball_sim_market_anchor_flag` (74 passed with the new file).

## 5. Does a flip need a re-sim to reach production? YES, for any sim that already exists

- The switch is read when a sim is BUILT. `_smart_sim_run_date_local` reuses an existing
  `smart_sim_<D>_<H>_<A>.json`, unchanged, when it:
  - has players;
  - has a current props pool (`props_pool_verdict`);
  - has a current prop-calibration stamp (`nba_prop_calibration.sim_is_stale`);
  - has the current exclusion set (`reuse_verdict`);
  - has a current anchor line (`smart_sim_anchor_refresh.anchor_current`).

  None of those checks reads `score.dist` or the code that built it. Tipped games are also frozen
  (`smart_sim_tip_freeze`).
- So after a flip (an env change: edit `local_production.env`, then a drained full `down`/`up`;
  env is built only at `up`):
  - Sims for slates not yet simulated carry the new h2.
  - Sims that already exist for today and tomorrow keep the old h2. They change only when one of
    the five checks above rebuilds them.
  - A game that has tipped never changes.
- There is no NBA command that forces a re-sim. The WNBA refresh has `--smart-sim-overwrite` /
  `--only-matchups`. The NBA production path (`basketball_props_predictions` ->
  `smart_sim_overwrite=False`) does not expose one. Options, all the user's call:
  1. Flip and wait about two slates. New sims carry it.
  2. Flip, then move the untipped `smart_sim_<D>_*.json` for today/tomorrow aside before the next
     NBA props run. That is a fleet data edit, and it costs one slate of sims on refresh-worker.
  3. A reuse rule: when the switch is on, a file without the stamp is stale. NOT BUILT. It would
     rebuild every untipped sim on the first run after the flip.
- **The Dec 7 re-grade (`nba-segment-regrade-818`, frozen grader) reads h2 from whatever files
  exist.** A flip before Dec 7 puts both rules in its window. That grader does not read the stamp.
  Either flip after Dec 7, or split that re-grade's h2 rows on `h2_includes_ot` by hand.

## 6. What is NOT done

- Not loaded anywhere. No fleet env edit, no deploy.
- The sim's low P(OT) (2.0% vs ~6%): a lead, not investigated.
- No reuse/staleness rule (option 3 above).
