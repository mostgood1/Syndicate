# NHL live puck line: the re-sim's margin histogram graded against finals (todo #773, lane nhl-live-puckline-grade)

2026-11-11, run 17:48-18:08Z (11:48 AM-12:08 PM CST). Session 87074b1f. READ-ONLY on production. User: "Do this task here" (the grade), then "yes, build the recorder too".

**Verdict: DO NOT PRICE.** The pooled ±1.5 grade passes the `#499` bar (worst powered bucket 0.056 vs 0.150), but only as an upper bound. Inside it, a decisive failure hides in the state live puck lines are bet in: a ONE-GOAL LEAD LATE IN THE THIRD. There the model gives the leader 0.18-0.26 to win by 2+, and it happened 0.43-0.50 of the time (n=90/93, ~5 sd). The cause is in the engine: the live resume path never applies the calibrated empty-net mechanism that the pregame game-market path uses.

## Population and provenance

- **Harness:** `scripts/backtest_nhl_live_puckline.py`. Tests: `tests/test_backtest_nhl_live_puckline.py` (10, with reachability on the shipped producer; 2 mutations caught).
- **Run:** on the fleet host at nice 19, 3 processes, using the fleet checkout's own code: HEAD `4793d823c`, `live_resim.py` blob `7045d8e13d14`, the same blob as `efccead01`.
  - Inputs: `build_slate_features(date, root=~/syndicate-prod/data/nhl_source)`, production's 200 sims, no profile override.
  - Seeds are a fixed function of (game, cutoff). Production's `abs(hash(pk))` is per-process.
  - Outputs: `C:\Users\TEMPAD~1\AppData\Local\Temp\claude\d4b01ba8b898a2f7\87074b1f-3325-4c92-871d-b22851478134\scratchpad\nhlgrade\out\` (`rows.jsonl`, `report.json`, `report.txt`).
- **Sample:** 284 completed REGULAR-season games (`gameType` 2) on 41 dates, 2026-10-01..11-10. Every game had slate features; 0 games were dropped and 0 rows refused.
  - 6 cutoffs per game: P1 20:00 (= the pregame sim), P2 20:00, P2 10:00, P3 20:00, P3 10:00 and P3 05:00. That is 1,704 scored states.
  - Each state is rebuilt exactly from `/v1/score/<date>`'s goal list, and the goal list must reproduce the official final.
- **Outcome:** the official final margin. A shootout winner is credited +1 (2-2 -> 3-2 SO), the way books settle and the way the engine's histogram does too.
- **Probability graded:** the one the board shows, Agresti-Coull P(home margin > away-frame line).
- **PROVENANCE: LEAKY.** `team_rates`, `player_rates`, `team_xg`, `team_elo` and `team_special_teams` `_2026-2027.csv` are rewritten daily (last 2026-11-11 18:04Z) and kept dated nowhere: not on the fleet disk, not in git.
  - So every graded game ran on rates that already contain it, and every later game.
  - **A PASS is an upper bound; only a FAIL is decisive.** Both failures below survive that, because better-informed inputs can only flatter the model.
  - Lineups and goalies are per-date files, but they are last written ~00:00 after the slate, so they are probably the actual lineups. That is also a flattering leak.
- **Baseline:** skill-free and width-correct. Rest-of-regulation goals are Poisson at the sample's own regulation rates (home 3.165, away 2.965 per 60), and a regulation tie resolves ±1 at the sample's home OT/SO share (0.651). It knows the score and the clock and nothing about the teams.

## Result 1: pooled, it passes as an upper bound

| family | cells | worst powered bucket | game-bootstrap 95% of \|gap\| | Brier model / baseline | model - baseline 95% |
|---|---|---|---|---|---|
| puck line ±1.5 | 3,408 | 0.1-0.2, n=333, **+0.056** | [0.048, 0.147] | 0.1340 / 0.1382 | [-0.0082, -0.0005] |
| alt ±2.5 | 3,408 | 0.6-0.7, n=81, **-0.139** | [0.110, 0.281] | 0.1093 / 0.1101 | [-0.0034, +0.0018] |

- **±1.5 shape:** the model is mildly over-confident. Buckets 0.1-0.4 come in +0.04..+0.06 above the prediction; buckets 0.7-0.9 come in -0.03..-0.04 below it.
- **±2.5:** the bootstrap interval straddles the bar, and the model does not beat the skill-free baseline.
- **Width** (realised RMSE about the model mean vs model sd; central-80% coverage):
  - P1/P2 1.05 / 1.06 / 1.00, coverage 0.81-0.87;
  - P3 20:00: 1.00;
  - **P3 10:00: 1.105;**
  - **P3 05:00: 1.167.**

  Too narrow, late.

## Result 2: by state, a decisive failure where live puck lines are bet

P(the LEADER wins by 2+), oriented to the leader:

| cutoff | lead | n | model | observed | gap |
|---|---|---|---|---|---|
| P3 05:00 | 1 | 90 | 0.180 | **0.433** | **+0.254** |
| P3 10:00 | 1 | 93 | 0.260 | **0.495** | **+0.234** |
| P3 20:00 | 1 | 87 | 0.317 | 0.414 | +0.097 |
| P2 10:00 | 1 | 115 | 0.334 | 0.435 | +0.101 |
| P2 10:00 | 2 | 63 | 0.532 | 0.683 | +0.150 |
| P3 05:00 | 2 | 54 | 0.757 | 0.796 | +0.039 |

- **The trailer side is about right late:** P(trailer ties or wins) with a one-goal lead is 0.131 vs 0.100 at P3 05:00 and 0.207 vs 0.183 at P3 10:00. So the late miss is specifically the leader's lead going from one goal to two.
- **The goals that do that are empty-netters.** 98 of the 229 goals scored in the last 5 minutes of P3 across the sample (42.8%) carry `goalModifier` `empty-net` or `awarded-empty-net`.
- **Mid-game (P2 10:00):** the leader's extension is also under-predicted (+0.10 / +0.15), and the trailer's comeback over-predicted (-0.065 / -0.096). That is consistent with score effects that pull too hard toward a tie. The leaky inputs would flatter this, so it is real; the sample is smaller.

## Engine read: the cause

- **Pregame game-market path (calibrated):** `hockeysim/adapters.py NHL_GAME_MARKET_CALIBRATION`, from lane `nhl-game-lines-model` (user decision 2026-10-03).
  - Mechanisms: `regulation_scale 0.9398`, `tie_weight 0.7539` ("regulation ties 0.160 modelled vs 0.2465 actual"), and **`empty_net_p 0.3006`** ("a one-goal regulation lead becomes two").
  - Fit walk-forward on 2025-26 and measured out of sample (n=681), applied post-sim in `game_market_sim.py`. This is what the pregame puck line is priced from.
- **Live resume path:** `live_resim.resim_live_game` -> `runtime.run_hockeysim_game_from_state` -> the engine.
  - It applies NONE of that calibration.
  - Its only empty-net logic is `engine.py:1580`, an ad-hoc heuristic: in the last 3 minutes only, the trailer's shots ×1.20 and the leader's conversion ×1.18.
  - So the live histogram is a different, uncalibrated estimator, and it fails exactly on the mechanism the pregame path was fitted for.
- **Leakage cannot explain it.** Better-informed rates would make the leader stronger in the model, which lowers the gap. The gap is there anyway.

## What this means for the board today

- **Pricing:** no. Opening it (`displayMarginDist` -> `marginDist`) would turn the late miss into edges. With a one-goal lead late, the model would call the trailer's +1.5 a ~0.74-0.82 proposition that really is ~0.50-0.57. Those are large fake edges on exactly the rows a bettor watches.
- **The display number is wrong in the same states.** Late in P3 with a one-goal lead, the Live proj. on the leader's -1.5 row reads ~0.18-0.26 against ~0.43-0.50 realised.
  - The NFL precedent (`#771`: "NFL spreads stay blank" after closed lane `nfl-live-distribution-grade` graded FAIL) withheld even the display.
  - Whether to suppress the NHL puck-line display in that state until the engine is fixed is a decision for the user. Not done.
- **No market comparison was possible.** No live NHL puck-line prices were recorded beside a model number.
  - The ledger (`nhl_source/data/live_gameline_ledger/`) holds 11-09 and 11-10 only.
  - Its display-only puck-line records carry `model_home_win_prob: None, market_fair_prob: None` and are written once per key per day.

## The recorder (built, NOT pushed, NOT loaded)

- **`live_gameline_ledger.py` v6:**
  - Every live gameline record now carries `display_prob` (the board's display-only number), `display_basis` and `market_fair_prob_over` (the market's de-vig for the same event; None on h2h, where `market_fair_prob` already has it).
  - `_moved` re-records a `live_margin_published_for_display_only` row when either value moves at 2 dp. It is scoped to that one refusal so no other row's write rate changes; that is ~1 row per live NHL game per build.
- **Event check on production's grid, 11-11:** on TBL @ BUF, line -1.5, consensus away +186 / home -227, `market_fair_prob_over` is 0.665. That is exactly the home de-vig, P(home +1.5 covers), the event `display_prob` describes.
- **Tests:** `tests/test_live_gameline_ledger_display_rows.py` (7: reachability through the real producer and join, movement, scope, append, refusal rows); 3 mutations caught. Neighbouring ledger, score, accuracy and NHL tests: 181 + 81 passed.
- **Loading it needs** a push and a claimed refresh-worker TERM. The ledger is written by `book_grid_artifact.record_live_gamelines` on refresh-worker, after `attach_live_gamelines_for_sport`.

## Candidate next steps (none done)

1. **Engine:** give the live histogram the calibrated end-game, then re-grade with this harness.
   - Apply `NHL_GAME_MARKET_CALIBRATION`'s empty-net (and tie re-weighting) to the live resume, or fit a live-specific empty-net rate on this replay walk-forward.
   - It is a mechanism on a calibrated engine, so `model_engine_standard` 4.4 applies: re-fit what absorbs it.
2. **Interim display rule (user decision):** suppress the puck-line Live proj. in P3 one-goal states, or leave it as it is (display-only, no edge).
3. **After the recorder runs for a few slates:** grade production's own displayed number against the market at the same instant. That is clean of the season-rate leakage this replay cannot avoid.

## Reproduce

```
cd ~/Syndicate && PYTHONPATH=$HOME/Syndicate nice -n 19 ~/.venvs/syndicate/bin/python <harness> \
  --start 2026-10-01 --end 2026-11-10 --source-root ~/syndicate-prod/data/nhl_source --out-dir <dir> --workers 3
<harness> --grade-only --out-dir <dir> --end 2026-11-10      # re-grade saved rows
py -3 <scratchpad>\nhlgrade\late_game.py <dir>               # the lead-state table + empty-net count
```
