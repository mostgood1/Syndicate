# NBA live: in-game checkpoint backtest + game-situation targets — lane `nba-native-live-resim`

Session 6c348b8f, 2026-10-09. P3 of `docs/ai_context/basketball_live_native_plan.md`.

**Scope this session:**
- At lane open, P1 (`basketball-native-engine`) and P2 (`basketball-native-live-state`) had not landed.
- P2 landed later the same day (verified on origin/main: d3e4e9ad, 2bf917ce).
- P1 has NOT landed (no `syndicate/features/basketball_engine/`; plan row "not started"), so the resumed
  native sim cannot exist yet.
- This file holds only the prerequisite-free part: the harness, the baseline readings, and the targets.

**Tools** (both new, hermetic tests in `tests/test_basketball_live_checkpoint_backtest.py`):
- `scripts/basketball_live_checkpoint_backtest.py`
  - `fetch` / `corpus`: ESPN summaries cached gzipped; season types 1/2/3/5, never pooled.
  - `grade`: projectors at end Q1/Q2/Q3/5:00 Q4, graded vs the final, with paired game-bootstrap CIs vs a
    baseline.
  - `live-close`: OddsAPI historical in-play lines, at-or-before the checkpoint, cached by snapshot
    validity interval. 30 credits/snapshot, measured.
- `scripts/basketball_live_situation_targets.py`: the targets below.

## Data (say which, per CLAUDE.md)

Nothing here comes from `data/` or Render artifacts. Every source is an external fetch cached under
`C:/tmp`, which is reproducible.

- **ESPN summaries:**
  - 2025-11-01..2026-02-28 from the calibration lane's cache (`C:/tmp/bball_sc/cache/nba`, 824);
  - the rest of 2025-26 plus 2026 preseason fetched here (`C:/tmp/nba_live_bt/cache`, 600, 0 failures).
- **Pregame lines:** OddsAPI pre-tip snapshots (`C:/tmp/nba_bt/out/cache/oddsapi_hist/games`, 213 dates,
  2025-10-21..2026-06-13), with ESPN `pickcenter` as the fallback (preseason).
- **Vendored baseline input:** as-of production SmartSim per-draw quarter points, 200 draws/game
  (`C:/tmp/bball_sc/sim_nba`, 809 games, 2025-11-01..2026-02-28, from `basketball-scenario-calibration`).
  - **The vendored replay therefore exists ONLY in that window.** The production NBA processed root holds
    22 SmartSim files (2026 preseason). There is no historical pregame SmartSim to replay elsewhere.
- **FIT window corpus:** 816 regular-season games parsed, 8 skipped (no linescore).
  - Checkpoint states whose pbp running score disagrees with ESPN's official linescore are EXCLUDED, not
    graded: end Q1 5, end Q2 12, end Q3 14, 5:00 Q4 14.

## 1. Baseline: vendored replay vs pregame_rate vs ESPN (regular season, FIT window)

**Projectors:**
- `vendored_replay`: the vendored tick's closed-form formulas (app.py 2164 / 44167 / ~44968 / ~45091).
  - Fidelity: exact at quarter ends.
  - At 5:00 Q4 the 3-min ladder becomes a quarter ladder.
  - No ML pace rescale.
- `pregame_rate`: current score + the pregame line's pro-rata share of the remaining regulation.
  - ML uses margin SD 13.5·√f (a stated constant, NOT fitted).
- `espn_wp`: ESPN's published live win probability (reference only).

Paired diffs (row minus vendored) are per game, 2,000 game resamples, 95% CI. n ≈ 778-811 per cell.

| checkpoint | total MAE: vendored / pregame_rate (diff, CI) | margin MAE: vendored / pregame_rate (diff, CI) | ML Brier: vendored / pregame_rate / espn |
|---|---|---|---|
| end Q1 | 13.00 / 12.60 (−0.44, −0.73..−0.16) | 11.12 / 10.29 (−0.86, −1.30..−0.40) | 0.212 / 0.210 / 0.208 (n.s.) |
| end Q2 | 11.08 / 10.95 (−0.17, n.s.) | 9.19 / 8.60 (−0.58, −0.98..−0.19) | 0.189 / 0.172 / 0.171 (pregame_rate −0.015, −0.027..−0.003) |
| end Q3 | 8.07 / 8.11 (n.s.) | 6.58 / 6.64 (n.s.) | 0.148 / 0.139 / 0.136 (espn −0.011, −0.019..−0.003) |
| 5:00 Q4 | 5.71 / 5.75 (n.s.) | **4.38** / 4.50 (+0.11, +0.004..+0.217: vendored better) | 0.105 / 0.091 / 0.090 (pregame_rate −0.014, −0.021..−0.006) |

Next-quarter total MAE: pregame_rate is better than vendored after Q1 (−0.14, CI −0.26..−0.02) and after Q2
(−0.15, CI −0.28..−0.01). After Q3 the two are not separable.

**Reading:**
- The vendored live tick does not beat "score + pregame line pro rata" anywhere except margin at 5:00 Q4,
  and that edge is barely outside zero.
- It is significantly WORSE early on margin and total, and on ML at end Q2 and 5:00 Q4.
  - Consistent with the calibration lane's "sim margin over-extrapolates (slope 1.59 on −spread)".
    `margin_mean` feeds the ATS blend with weight 1 − elapsed/48.
- **Consequence for the P3 gate:**
  - Beating `vendored_replay` is a LOW bar.
  - The refusal design's §5 keeps `pregame_rate` beside the gate, and I recommend making it part of the
    gate: a native sim that loses to `pregame_rate` should not price live.
  - Note that `pregame_rate` uses no reversion at all, while §2 shows real reversion is large. The native
    sim should beat it once it has the reversion mechanism.

## 2. Targets (regular season, FIT window, n = 816 games; game-resampled 95% CI)

### 2a. Score-effect reversion (line-adjusted: each segment minus its pro-rata share of −spread)

| slope | real |
|---|---|
| H2 margin on H1 margin | **−0.164** [−0.233, −0.096] (the prior lane measured −0.174 on 791 games; the sim's within-game slope is −0.001) |
| Q4 margin on margin entering Q4 | **−0.135** [−0.178, −0.096] |
| rest-of-regulation margin on margin now @ end Q1 | **−0.258** [−0.370, −0.150] |
| ... @ end Q2 | **−0.167** [−0.236, −0.100] |
| ... @ end Q3 | **−0.134** [−0.181, −0.093] |
| ... @ 5:00 Q4 | **−0.082** [−0.107, −0.056] |
| rest-of-regulation TOTAL on total now (pace persistence) @ end Q1 | +0.103 [−0.030, +0.220] |
| ... @ end Q2 / end Q3 / 5:00 Q4 | −0.020 / −0.007 / −0.011, every CI spans 0 |

**Mechanism targets:**
- **Margin:** reversion at every checkpoint, strongest early. A live projection should regress the
  excess margin by ~26% after Q1, ~17% at half, ~13% after Q3 and ~8% at 5:00 Q4.
- **Total:** NO measurable pace persistence beyond the pregame total. A high-scoring first half does not
  predict a high-scoring second half once the line is removed.
  - Do not add total momentum.
  - Use `_recent_total_flow_context`-style pace only with its own target.

### 2b. Asymmetric garbage time (Q4, by |margin| at the start of each interval, seconds-weighted)

Starters on floor are out of 5. Pts/48 and poss/48 are per team.

| window · margin | games | leader starters | trailer starters | gap trail − lead [CI] | pts/48 leader / trailer | poss/48 leader / trailer |
|---|---|---|---|---|---|---|
| Q4 12:00-6:00 · 0-5 | 409 | 2.59 | 2.68 | +0.09 [−0.00, +0.18] | 100 / 102 | 85 / 87 |
| Q4 12:00-6:00 · 11-15 | 381 | 2.58 | 2.81 | +0.23 [+0.09, +0.36] | 103 / 108 | 88 / 92 |
| Q4 12:00-6:00 · 21+ | 233 | 1.85 | 2.06 | +0.22 [+0.04, +0.42] | 101 / **114** | 85 / **96** |
| Q4 6:00-2:00 · 0-5 | 375 | 3.67 | 3.65 | −0.02 (n.s.) | 99 / 108 | 84 / 87 |
| Q4 6:00-2:00 · 11-15 | 313 | 3.58 | 3.31 | **−0.27** [−0.45, −0.09] | 103 / 119 | 87 / 94 |
| Q4 6:00-2:00 · 16-20 | 230 | 2.79 | 2.19 | **−0.60** [−0.81, −0.37] | 109 / 113 | 90 / 93 |
| Q4 6:00-2:00 · 21+ | 229 | 0.98 | 1.00 | +0.03 (n.s.) | 98 / **121** | 87 / **99** |
| Q4 last 2:00 · 6-10 | 319 | 3.85 | 3.48 | **−0.37** [−0.53, −0.20] | 155 / 152 | 113 / 128 |
| Q4 last 2:00 · 11-15 | 265 | 2.66 | 2.10 | **−0.56** [−0.75, −0.37] | 109 / 123 | 100 / 103 |
| Q4 last 2:00 · 21+ | 198 | 0.29 | 0.62 | **+0.33** [+0.20, +0.46] | 105 / **136** | 102 / **111** |

**Reading:**
- **The hypothesis is PARTLY REFUTED.**
  - "The leader benches first" holds only in the early-Q4 blowout window (gap +0.22) and in the final
    2:00 of a 21+ game (+0.33).
  - In the 11-20 band from 6:00 onward, the TRAILER pulls its starters first (−0.27 to −0.60). The
    trailing team concedes; the leader keeps its starters on until the game is safe.
  - A mechanism that only benches the leader would get the 11-20 band wrong-signed.
- **The trailing team's pace and scoring rise with the margin** (poss/48 96-111 vs the leader's 85-102 at
  21+). This half of the hypothesis holds.
  - CAVEAT: the attribution conditions on the state, and scoring moves the state. The trailer's scoring
    advantage in close buckets (102 vs 100 at 0-5) is partly that mechanical selection. Use the leader vs
    trailer POSSESSION gap as the target, not points.

### 2c. End-of-game fouling (Q4 last 2:00 vs Q4 6:00-2:00, by the trailing team's deficit)

| deficit | last 2:00: trailer fouls/min [CI] | FTA/min | pts/min | 6:00-2:00 baseline: trailer fouls/min · FTA/min · pts/min |
|---|---|---|---|---|
| tied | 0.74 [0.53, 1.01] (either team) | 0.84 | 4.15 | 0.63 · 0.85 · 4.14 |
| 1-3 | **1.10** [0.98, 1.24] | 2.66 | 6.01 | 0.37 · 0.96 · 4.15 |
| 4-6 | **1.33** [1.18, 1.48] | **3.48** | **7.47** | 0.31 · 1.04 · 4.44 |
| 7-10 | **0.94** [0.82, 1.06] | 2.48 | 6.02 | 0.37 · 1.05 · 4.37 |
| 11+ | 0.32 [0.28, 0.36] | 1.24 | 4.91 | 0.34 · 1.04 · 4.61 |

**Reading:**
- A 3-4x foul spike by the trailer, 1-10 down, inside 2:00. FTA/min rises 2.5-3.3x and points per minute
  ~1.5x.
- The spike peaks at 4-6 down and is gone by 11+.
- The vendored engine has no intentional-foul free throws at all (calibration lane, S6). This is the
  largest single late-game mechanism by effect size.

### 2d. Foul trouble (starters; on-floor share of the rest of the period after reaching the count, vs other starters of the same game, same clock)

| state | events | on-floor share after | control | gap [CI] |
|---|---|---|---|---|
| 2 PF in Q1 (≥3:00 left) | 493 | 0.19 | 0.45 | **−0.27** [−0.29, −0.24] |
| 3 PF in Q2 (≥3:00 left) | 302 | 0.21 | 0.74 | **−0.53** [−0.57, −0.49] |
| 4 PF in Q3 (≥3:00 left) | 437 | 0.21 | 0.49 | **−0.27** [−0.31, −0.25] |
| 5 PF in Q4 (≥4:00 left) | 239 | 0.46 | 0.60 | **−0.15** [−0.19, −0.11] |

### 2e. Bench-rotation interval shape (starters on floor by game minute, both teams; 411 close finals ≤ 10, 164 blowout finals ≥ 20)

- **Close games:**
  - Minutes 0-3: 5.0 starters.
  - The bench enters through minutes 5-10; the trough is 1.40 at minute 11.
  - Starters climb back to 3.7 by minute 22.
  - The pattern repeats in the second half, with a trough of 1.61 at minute 35 and 3.81 at minute 46.
- **Blowouts:** identical until minute ~39, then fall to 2.13 at minute 41, 1.10 at minute 45 and
  **0.48 at minute 48**.
- Full 48-value curves are in `targets.json` (`rotation_starters_on_floor_by_minute`).
- This is the shape P2's `rotation_stints_history` must let the engine reproduce.

### Floor-inference quality (the input to 2b, 2d and 2e)

Fives are inferred from pbp:
- Period starters are the players who act before they are subbed in.
- Gaps are topped up from the previous period's closing five.
- Q1 uses the box-score starters.

Validated against official box minutes over 816 games:
- per-game minutes MAE: median **0.25 min**;
- **99.4%** of games have MAE ≤ 0.5 min;
- intervals without exactly 5 on floor: 0.08%.

## 3. Full 2025-26 season, all populations (read 2026-10-09)

**Corpus:**
- 2025-26: 1,393 games (regular 1,231 · postseason 91, which includes play-in · preseason 71); 8 skipped.
- 2026 preseason through 10-08: 23 games, a separate file (a different season, never pooled with 2025).
- Pbp/linescore mismatches excluded per checkpoint: 9 / 21 / 26 / 26 (≤ 2.1%).
- Floor-inference minutes MAE median: 0.25 (regular), 0.25 (post), 0.24 (pre 2025), 0.23 (pre 2026).

**Pregame lines:**
- regular and post: OddsAPI 1,231 / 91;
- 2025 preseason: **none** (no OddsAPI pre-tip snapshot, and ESPN keeps no pickcenter on those 71
  summaries), so every line-adjusted slope is unmeasurable there;
- 2026 preseason: ESPN pickcenter 20 of 23.
  - The pickcenter spread is home-signed. Verified against OddsAPI on 128 regular-season games: 128 same
    sign, 0 opposite, mean |total diff| 2.7.

### 3a. Baselines on the full regular season (pregame_rate on all 1,222-1,209; vendored only in the FIT window)

| checkpoint | pregame_rate total / margin MAE · Brier | espn_wp Brier (diff vs pregame_rate) |
|---|---|---|
| end Q1 | 12.72 / 10.07 · 0.190 | 0.190 (−0.000, −0.003..+0.003) |
| end Q2 | 10.99 / 8.60 · 0.158 | 0.157 (−0.001, n.s.) |
| end Q3 | 8.12 / 6.54 · 0.123 | 0.121 (−0.002, −0.004..+0.000) |
| 5:00 Q4 | 5.66 / 4.49 · 0.083 | 0.082 (−0.001, n.s.) |

`pregame_rate` with an unfitted SD of 13.5 matches ESPN's published live win probability on ML.

**Postseason** (n = 89-91), pregame_rate total / margin MAE · Brier · espn Brier:

| checkpoint | pregame_rate | espn Brier |
|---|---|---|
| end Q1 | 11.72 / 10.61 · 0.212 | 0.200 |
| end Q2 | 9.95 / 8.81 · 0.178 | 0.176 |
| end Q3 | 7.54 / 6.23 · 0.125 | 0.123 |
| 5:00 Q4 | 5.78 / 4.75 · 0.116 | 0.115 |

- ESPN vs pregame_rate is n.s. at every checkpoint.
- No vendored replay exists for the postseason (no as-of SmartSim draws).

### 3b. Targets by population (game-resampled 95% CI)

| target | regular (1,231) | postseason (91) | preseason 2025 (71) | preseason 2026 (23) |
|---|---|---|---|---|
| H2-on-H1 margin slope | **−0.172** [−0.228, −0.118] | −0.041 [−0.306, +0.194] | n/a (no lines) | −0.41 [−0.85, +0.03] (n=20) |
| rest margin on now @ end Q1 / Q2 / Q3 / 5:00 Q4 | **−0.239 / −0.174 / −0.132 / −0.089** (all CIs < 0) | +0.144 / −0.033 / −0.041 / −0.059 (all CIs span 0) | n/a | noisy (n ≤ 20) |
| rest TOTAL on now (pace persistence) | +0.089 [−0.011, +0.192] at Q1, then ~0 | ~0, all CIs span 0 | n/a | n ≤ 20 |
| trailer fouls/min, last 2:00, down 1-3 / 4-6 / 7-10 / 11+ | **1.15 / 1.34 / 0.86 / 0.32** | 0.96 / 1.40 / 1.29 / 0.42 | 0.68 / 0.97 / 0.58 / 0.37 | 1.37 / 1.49 / 0.64 / 0.44 |
| FTA/min, last 2:00, down 4-6 (6:00-2:00 baseline) | 3.54 (1.05) | 2.92 (0.92) | 2.54 (1.36) | 2.57 (1.29) |
| starters gap trail − lead, Q4 6:00-2:00, 16-20 | **−0.51** [−0.69, −0.32] | −0.54 [−1.23, +0.01] | +0.17 (n.s.) | n=4 |
| starters gap, last 2:00, 11-15 | **−0.47** [−0.65, −0.29] | **−1.08** [−1.68, −0.54] | +0.30 (n.s.) | n=8 |
| starters gap, last 2:00, 21+ | **+0.50** [+0.38, +0.62] | +0.16 (n.s.) | +0.23 [+0.00, +0.47] | n=5 |
| starters gap, Q4 12:00-6:00, 21+ | **+0.26** [+0.11, +0.42] | +0.28 (n.s.) | **+1.34** [+0.53, +2.03] | n=5 |
| foul trouble gap: 2 PF Q1 / 3 PF Q2 / 4 PF Q3 / 5 PF Q4 | **−0.27 / −0.51 / −0.28 / −0.14** | **−0.43 / −0.62 / −0.40 / −0.10** | −0.10 / −0.18 / +0.02 / +0.23 | −0.06 / −0.07 / +0.07 / — |

**What this changes for the mechanisms:**
1. **Score-effect reversion is a REGULAR-SEASON phenomenon.** It is strong and tight there and not
   detectable in the playoffs (n=91; the CI admits up to −0.31, so "absent" is not proven).
   - A single league-wide reversion rate would be wrong in one population or the other.
   - Make it a per-population parameter. The postseason value stays 0 until it is measured as non-zero.
     Do not borrow the regular-season value.
2. **End-game fouling holds in every population.** Its shape (peak at 4-6 down) holds too. Intensity is
   lower in preseason (~0.7x). One mechanism, with population-level intensity.
3. **Garbage-time benching is sign-dependent on the band, not on "leader vs trailer":**
   - in the 11-20 band from 6:00, the trailer concedes first (regular, and stronger in the postseason);
   - in 21+, the leader benches first;
   - in preseason, everyone benches early (+1.34 at 21+, early Q4).
4. **Foul trouble is strongest in the playoffs, absent in the preseason.** Coaches stop protecting players
   from fouls in preseason (4 PF in Q3: +0.02; 5 PF in Q4: +0.23).
5. **Total pace persistence ≈ 0 everywhere.** No total-momentum mechanism is justified by any population.
   Live totals should move with the score and the clock, not extrapolate a hot start.

## 4. Live close — OWED (fetch in flight at session end)

**What was approved and measured:**
- User-approved 2026-10-09 in chat: FIT window only, about 2,521 snapshots, about 75.6k credits.
- A one-call probe showed that historical snapshots DO carry in-play NBA lines. Example: CHI-UTA tipped
  01:11Z and showed a 261.5 live total at 01:55Z. `x-requests-last` = 30, and `x-requests-used` was
  1,128,321 at the probe.

**Request timing.** Requests resolve at-or-before the checkpoint state, so a line never knows more than the
model:
- quarter ends: 5 s before the next period's first play;
- 5:00 Q4: the last play at 5:00.

**Grading** keeps only rows whose snapshot was priced on the SAME score as the checkpoint state
(`score_at_snapshot_matches`). In a 5-call test, 3 of 5 matched: the short Q1/Q3 breaks against 5-minute
snapshots lose some rows. n is reported per cell.

**State at session end:**
- 137 snapshots cached (`C:/tmp/nba_live_bt/live_hist`), at roughly 4/min.
- It runs at Idle priority on a host at 100% CPU (13 s of CPU in 40 min), so the expected finish is many
  hours out. The rows file is written at the END of the run.
- Re-running the same command resumes from the cache and spends nothing on cached intervals:
  `ODDS_API_KEY= py -3 scripts/basketball_live_checkpoint_backtest.py live-close --games C:/tmp/nba_live_bt/games_fit.jsonl --cache C:/tmp/nba_live_bt/live_hist --out C:/tmp/nba_live_bt/live_close_fit.jsonl --env-file <primary>/.env --max-calls 2700`

**Then grade:**
`py -3 scripts/basketball_live_checkpoint_backtest.py grade --games C:/tmp/nba_live_bt/games_fit.jsonl --sim-draws C:/tmp/bball_sc/sim_nba --lines-cache C:/tmp/nba_bt/out/cache/oddsapi_hist/games --live-close C:/tmp/nba_live_bt/live_close_fit.jsonl --baseline vendored_replay --out C:/tmp/nba_live_bt/report_fit_lc`

## 5. Status, and what P3 still needs

- **P1 is NOT on origin/main.** There is no `syndicate/features/basketball_engine/`, and the plan row says
  "not started". Without a resumable engine there is no native projector to grade. Mechanisms, the re-fit,
  `live_resim` publishing, `_LIVE_GAMELINE_SPORTS` and the vendored-import deletion are all NOT started.
- **P2 IS on origin/main** (d3e4e9ad, 2bf917ce):
  - `build_live_game_state` (LiveGameState);
  - historical `pbp_events/<season>/<event>.jsonl.gz` (NBA 2025-26, 1,424 games);
  - native `rotation_stints_history`.
- **When P1 lands:**
  - Add a `native_resim` projector to the harness that maps `CheckpointState` / P2 `LiveGameState` onto
    P1's resume API.
  - Run it on the same games and the same cells.
  - Gate per `docs/ai_context/nba_live_resim_refusal_design.md` §5. Recommended: native must beat BOTH
    `vendored_replay` AND `pregame_rate`, because the vendored tick loses to `pregame_rate` in most cells.
- **Plan Status row P3 was NOT edited.** `lane-guard` blocks the plan doc: it is claimed file-level by the
  P1, P2, P4 and P5 lanes, and the guard cannot scope by table row. Text for whoever next holds the doc:
  > `nba-native-live-resim` | waiting on P1 (P2 landed). Prerequisite-free part done 2026-10-09:
  > checkpoint backtest harness, vendored baseline readings, measured situation targets
  > (`.syndicate/findings_2026-10-09_nba_live_situation_targets.md`), refusal design
  > (`docs/ai_context/nba_live_resim_refusal_design.md`). Resumed sim, mechanisms and cut-over NOT started.
- **Overlap to know about:** the `wnba-native-live-cutover` lane (P5) builds its own WNBA checkpoint corpus
  (`scripts/build_wnba_live_checkpoint_corpus.py`). This harness is league-parametric (`LEAGUES` has
  wnba/ncaab clock rules), so P5/P4 can reuse its grading rather than fork it.

## 6. P3 build after P1 landed (2026-10-09 evening, session 6c348b8f)

**Prerequisites.** Both verified on origin/main before resuming:
- P1 `c2b99d4f` (`syndicate/features/basketball_engine/`, `GameState` resume);
- P2 `d3e4e9ad` / `2bf917ce`.

**Split agreed with basketball-scenario-calibration** (via the plan coordinator d48f3a34):
- That lane owns `score_effect_k`, its mechanism and its re-fit.
- P3 consumes the chosen k unchanged and re-fits only the live mechanisms.

**User decisions relayed in chat** (by d48f3a34; not seen directly by this session):
1. Three section loans from basketball-native-engine:
   - the engine column memo;
   - the default-off live mechanisms;
   - the pregame input persist.
2. **ALL NBA mechanism RE-FITS ARE ON HOLD until #473** (NBA team_adj unfed 0/30, starter flags 0/517).

### 6a. Engine cost and the column memo (loan a)

ms/draw on P1's recorded production inputs (3 NBA games, 20 draws, Idle on a loaded host):

| state | before | after the per-call column memo |
|---|---|---|
| pregame | 570-690 | 305-337 |
| end Q1 | 415-505 | 216-258 |
| end Q2 | 310-380 | 118-196 |
| end Q3 | 145-215 | 62-111 |
| 5:00 Q4 | 76-107 | 39-71 |

- **Before the memo**, cProfile put ~60% of a draw in `_player_usage_weights -> _safe_series`: pandas
  to_numeric/fillna on the same constant frames, every possession.
- **The memo** is scoped to one `simulate_pbp_game_boxscore` call, keyed on (frame id, column), with read-only
  arrays.
- **Evidence it changed nothing:**
  - same-seed mean totals are unchanged;
  - P1's suites pass, 48 tests.
- **Production-corpus gate:** the 5,400-case parity replay plus a same-seed e2e A/B, in flight at writing (see
  deploys.md / the lane).

### 6b. Native resumed sim on 2026 preseason (FIRST READING; team_adj UNFED, so neutral team quality)

**Population:**
- 15 games with recorded production inputs (P1's corpus, 10-05..10-08);
- n = 14-15 per checkpoint.

**Native vs `pregame_rate`, paired:**

| market | native vs pregame_rate |
|---|---|
| total MAE, end Q1 | **+2.43** [+0.39, +4.54] (native worse) |
| total MAE, end Q2 | **+1.76** [+0.57, +2.93] (native worse) |
| total MAE, end Q3 | **+1.26** [+0.75, +1.77] (native worse) |
| total MAE, 5:00 Q4 | +0.06 n.s. |
| margin MAE | n.s. at every checkpoint |
| ML Brier | n.s. at every checkpoint except 5:00 Q4: +0.018 [+0.005, +0.034] (native worse) |

**Bias:** both over-project preseason totals.
- `pregame_rate`: +1.7 / +6.1 / +4.2 / −1.2 at end Q1 / Q2 / Q3 / 5:00 Q4.
- Native: a further ~2.5-3 points.

**Lead, not a finding** (n = 14): preseason second halves score below their lines (starters sit), and the
native engine has no mechanism for that.

**Not shippable, and not graded for shipping:**
- n is tiny;
- team_adj is unfed;
- the preseason is its own population.

### 6c. End-game fouling: the sim vs real, and the mechanism's reach (loan b)

**The native engine, OFF.** Resumed at 2:00 Q4 with home trailing by d, 4-5 recorded games × 30-40 draws:
FTA/min ~1.0 and pts/min ~5.0 at EVERY deficit.

**Real (§2c, 1,231 games):**

| down | FTA/min | pts/min |
|---|---|---|
| 1-3 | 2.75 | 6.0 |
| 4-6 | 3.54 | 7.5 |
| 7-10 | 2.36 | 6.0 |
| 11+ | 1.25 | 4.9 |

**The mechanism** (`EventSimConfig.endgame_foul_*`, default-off, getattr-read, so production's
EventSimConfigLocal is off):
- the trailing defense fouls at possession start with probability p;
- two FTs with the same FT% formula;
- ~5 s of clock;
- possessions are clock-governed past the pace pre-count while the window holds.

**EXPLORATORY sweep, NOT A FIT.** Last-2:00 FTA/min / pts/min at down 2 / 5 / 8 / 14:

| p | down 2 | down 5 | down 8 | down 14 |
|---|---|---|---|---|
| 0.0 | 1.05 / 5.28 | 1.00 / 4.94 | 1.02 / 4.79 | 0.99 / 4.89 |
| 0.3 | 2.10 / 6.08 | 2.30 / 5.83 | 2.02 / 6.01 | 1.14 / 5.08 |
| 0.5 | 2.84 / 6.62 | 2.99 / 6.83 | 2.82 / 6.06 | 1.24 / 5.36 |
| 0.7 | 3.78 / 7.11 | 4.14 / 6.95 | 3.81 / 6.57 | 1.52 / 5.36 |

**Reading:**
- The mechanism REACHES the real range: p ≈ 0.5 gives FTA 2.8-3.0 and pts 6.1-6.8.
- The real curve peaks at 4-6 down and the sim's is flat, so the re-fit should be per deficit bucket.
- 14-down drifts up because the margin re-enters the band.
- No value is chosen until #473 is fixed.

### 6d. Production wiring, and what is deliberately NOT enabled

**What exists:**
- `nba/live_resim.py`:
  - P2 state → P1 `GameState` resume, refusing by name;
  - persisted pregame inputs;
  - a seeded N-sim under a deadline;
  - full-game, quarter and half histograms;
  - live props (actual + remainder, lines = mode across books from the props CSV);
  - a dedicated loop writing `live/nba_live_resim.json` within a 6 MB budget.
- The NBA page lens merges the re-sim's lanes and props by event_id.
- `_call_native_engine_local` persists each newly simulated game's engine inputs (write-only).

**What is NOT enabled:**
- `SYNDICATE_NBA_LIVE_RESIM` (the loop): absent = off.
- `SYNDICATE_NBA_LIVE_MECHANISMS`: absent = off.
- nba is NOT in `_LIVE_GAMELINE_SPORTS`.
- The vendored tick is NOT deleted.

**Reason:** the design's §7 cut-over order. The only native reading so far (6b) does not beat `pregame_rate`, and
re-fits are on hold.

**Preseason props cannot be priced:** today's NBA props CSV carries h2h/spreads/totals only, no player markets.
Priced live props start with the regular season.

### 6e. Native preseason RE-READ with #473 inputs (2026-10-10 ~16:3xZ)

**Inputs.**
- 20 games, 10-03..10-09, re-recorded on a copy of the live NBA root at code ≥ a31ba2bf.
- team_adj non-neutral, starter flags fed, skip_def file present.
- Persisted by the production hook: **20/20, 0 failures**.
- 200 sims. n = 16-18 per checkpoint (pbp/linescore mismatches excluded).

**Native vs `pregame_rate`, paired:**

| market | end Q1 | end Q2 | end Q3 | 5:00 Q4 |
|---|---|---|---|---|
| total MAE | **+2.63** [+0.39, +4.88] | **+2.53** [+1.41, +3.60] | **+1.74** [+1.19, +2.35] | n.s. |
| total bias, native / pregame_rate | **+8.0 / +1.7** | **+10.0 / +6.1** | **+6.8 / +4.2** | +1.8 / -1.2 |
| margin MAE | n.s. (-0.55) | n.s. (-0.39) | n.s. | n.s. |
| ML Brier | n.s. (-0.050) | n.s. (-0.043) | n.s. | **+0.021** [+0.005, +0.042] |

- Interval coverage 80%: 0.69-0.94 (n too small to judge).

**Reading:** #473 did NOT change the preseason picture.
- The native sim over-projects rest-of-game scoring in the preseason by ~3-4 points more than the market already does.
- The candidate is a preseason population effect: second halves played by benches, which neither the market line nor the engine models.
- At n ≈ 16 it is indistinguishable from a general level bias. The 2025-26 regular-season gate decides.

## 7. PRE-REGISTERED 2026-10-12 (before any measurement): end-game fouling re-fit (mechanism M-EG)

**Mechanism:** `EventSimConfig.endgame_foul_*` (c9971e75), extended to a per-deficit-bucket probability
(`endgame_foul_p_by_deficit`, buckets 1-3 / 4-6 / 7-10).
- Window 120 s.
- Clock-governed extension on.
- Foul possession ~5 s.
- All other rates fixed; `score_effect_k` as the calibration lane ships it (k = 0 until stated).

**Population:**
- 2025-26 REGULAR season games whose state at exactly 2:00 Q4 (every play at 2:00 included, the `state_at` rule)
  has |margin| in 1..10.
- pbp/linescore-consistent.
- With v3 as-of engine inputs (#473 + 2024-25 prior).
- Postseason and preseason excluded (separate populations; the postseason gets its own reading only if n >= 30
  per bucket).

**Split:**
- FIT 2025-11-01..2026-02-28;
- VALIDATION 2026-03-01..2026-04-12, read ONCE.

**Game-matched measurement:**
- Resume the native sim from each game's own 2:00 state via `live_resim.resume_from_summary` on the summary cut at
  2:00, with that game's own inputs, 40 draws per (game, p).
- Per game: REAL = regulation points scored after 2:00 (Q4 linescore total minus Q4 points at 2:00); SIM = the
  mean of the same.
- Also trailer FTA after 2:00 (real from pbp, sim from recorded FTA events).

**Grid:** p ∈ {0, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7} per bucket.

**Selection (FIT):** per bucket, the p minimising |mean(SIM - REAL)| on last-2:00 points.

**Ship rule (VALIDATION, read once):** per bucket,
- (a) |mean(SIM - REAL)| at the chosen p is inside REAL's game-resampled 95% CI half-width, AND
- (b) it is smaller than at p = 0.

**A bucket that fails keeps p = 0.** The mechanism's live effect is then judged by the checkpoint gate (5:00 Q4
total / margin / ML vs `pregame_rate`) with M-EG on vs off on the same games.

### 7a. Mechanism targets handed over by basketball-scenario-calibration (full-FIT confirmation, 2026-10-12)

**Run:** 791 games, 2025-11..2026-02, with lineup pools, #473 inputs, `score_effect_k = 0.002` (CONFIRMED; still a
proposal, production pregame k = 0).

**Residuals that are P3's to close:**
- **Q4 reversion:** sim -0.093 [-0.097, -0.090] vs real -0.141. The end-game mechanism (§7) is the planned
  closer; it is fitted ON TOP of k = 0.002.
- **Blowout rest:** top-5 starter minutes are FLAT at 31.7 whatever the score, vs real 26.9 when the final
  margin is >= 20.
  - It is the garbage-time mechanism's target.
  - The band-dependent benching in §2b applies: the trailer concedes first at 11-20, the leader benches at 21+.
- **Foul-outs:** 0.47 per game in the sim vs real 0.19.
  - It is the foul-trouble mechanism's target. Real starters sit after 2 PF in Q1 / 3 in Q2 / 4 in Q3 / 5 in Q4
    (§2d: on-floor share gaps -0.27 / -0.51 / -0.28 / -0.14 regular season); the engine has no in-sim
    foul-trouble benching (resume.py: player fouls below the limit are CARRIED, not consumed).
- **The gate states its config:** each arm is labelled "score_effect_k = 0 (production pregame)" or
  "score_effect_k = 0.002 (proposed)". The live re-sim must run the same k as production pregame, so a resume at
  the tip reproduces the pregame number; the user picks one config for both at switch-on.

## 8. PRE-REGISTERED 2026-10-12 (before any measurement): foul-out + foul-trouble benching (mechanism M-FT)

**Mechanisms** (engine, default-off):
- `foul_out_in_sim` (disqualification at the league limit);
- `foul_trouble_bench_mult`, with thresholds 2/3/4/5 PF in Q1-Q4 and no benching inside the final 240 s of
  regulation.

**Measured first, before this pre-registration, on 40 FIT games × 20 pregame draws (v4 inputs,
score_effect_k = 0.002):**
- players reaching 6 PF/game: OFF 0.745, disqualification-only 0.765;
- players EXCEEDING 6 PF: OFF 0.438, disqualification-only 0.014.
- So disqualification fixes "fouling past the limit" but not the foul-out RATE.
- Real 0.193/game (basketball-scenario-calibration full FIT).

**Population:** 2025-26 regular season, v4 as-of inputs, k = 0.002, `foul_out_in_sim` ON in every arm.
- FIT: 60 games sampled from 2025-11..2026-02.
- VALIDATION: 60 games from 2026-03-01..04-12, read once.
- 20 pregame draws/game, common random numbers.

**Grid:** `foul_trouble_bench_mult` ∈ {1.0, 0.5, 0.3, 0.15, 0.05}.

**Selection (FIT):** the mult minimising |sim foul-outs/game − 0.193|.

**Ship rule (VALIDATION):**
- |sim − 0.193| ≤ 0.05 at the chosen mult, AND
- total PF/game within ±5% of the mult = 1.0 arm. Benching may move who fouls, not how much a team fouls; if it
  moves the total, it is absorbing a foul-rate re-fit and that has to be done jointly.

**Secondary (reported, not gated):** the live-resume check. From real states where a starter has just reached
the threshold (§2d), the sim's share of the rest of the period with that player on the floor vs real
0.19 / 0.21 / 0.21 / 0.46. Needs per-possession lineup recording; deferred if the engine cannot report it.

### 8a. RESULT — foul-out + foul-trouble benching (read 2026-10-12 ~22:3xZ, pre-registered §8)

**Setup:** 60 FIT + 60 VALIDATION games, 20 pregame draws each, v4 inputs, k = 0.002, `foul_out_in_sim` ON in
every arm, common random numbers.

| bench mult | FIT foul-outs/g | VALID foul-outs/g | VALID team PF/g |
|---|---|---|---|
| 1.0 (off) | 0.548 | 0.536 | 29.64 |
| 0.5 | 0.338 | 0.349 | 29.65 |
| 0.3 | 0.268 | 0.308 | 29.74 |
| 0.15 | 0.241 | 0.248 | 29.56 |
| **0.05 (chosen)** | **0.240** | **0.213** | **29.68** |

Real foul-outs: 0.193/game.

**SHIP under the rule:**
- VALID |0.213 − 0.193| = 0.020 ≤ 0.05;
- team PF/game +0.1% vs mult 1.0 (≤ 5%).

**Caveats:**
- FIT floors at ~0.24 even at near-total benching, so some excess comes from foul ALLOCATION inside a stint, not
  from who plays. The fit does not close it.
- A 0.05 lineup-weight multiplier is stronger than the real on-floor ratios (§2d: 0.19 / 0.45, 0.21 / 0.74, ...).
  Weight ≠ on-floor share, but the minutes side MUST be read with basketball-scenario-calibration's
  `--track-oncourt` (47216656) before enabling.

**Enabling** stays off. Pregame enablement is the user's decision. Live enablement goes with the switch-on.

**Engine-edit gate:** P1's production-corpus replay on the code with both fields (default-off), in flight.
- **Engine-edit gate:** P1's corpus replay on the code with `foul_out_in_sim` + `foul_trouble_*` (default-off):
  **5,400/5,400**, mismatched_cases 0 (NBA 3,000 / WNBA 2,400), PASS, 3,010 s.

### 7b. RESULT — end-game fouling re-fit (read 2026-10-12 ~23:5xZ, pre-registered §7; VALIDATION read once)

**Setup:**
- v4 inputs (pools + #473 + the 2024-25 prior), `score_effect_k = 0.002` in every arm.
- Game-matched at 2:00 Q4, 40 draws, common random numbers.
- 518 regular-season games graded.
- Named refusals: `pbp_score_mismatch` 8, `on_floor_incomplete` 11; 26 without inputs/summary.

**Per trailing-deficit bucket at 2:00.** REAL = regulation points after 2:00; error = mean(SIM − REAL).

| bucket | FIT n | FIT err @p=0 / @chosen | chosen p | VALID n | VALID err @p=0 / @chosen | REAL VALID 95% CI | ship |
|---|---|---|---|---|---|---|---|
| 1-3 | 157 | −1.01 / +0.57 | **0.2** | 41 | −1.19 / **+0.45** | [10.15, 12.98] (half-width 1.41) | **yes** |
| 4-6 | 108 | −0.76 / −0.76 | **0.0** | 45 | −1.84 / −1.84 | [11.33, 13.62] (half-width 1.14) | **no → p = 0** |
| 7-10 | 123 | −1.19 / −0.04 | **0.2** | 44 | −1.38 / **−0.12** | [10.41, 13.50] (half-width 1.55) | **yes** |

**Shipping values:** `endgame_foul_p_by_deficit = (0.2, 0.0, 0.2)`; window 120 s; extension on.
- Off by default.
- Live enablement is with the switch-on, through `SYNDICATE_NBA_LIVE_MECHANISMS`.

**Reading:**
1. With p = 0 the sim UNDER-scores the last 2:00 in every bucket (−0.8 to −1.8 points), consistent with §2c.
2. In 1-3 and 7-10, p = 0.2 removes it on held-out games.
3. **4-6 is a SHAPE miss.** On FIT, p = 0.2 already over-shoots points (+0.79) while sim FTA stays far below real
   (3.48 vs real 5.25 FTA after 2:00). So the sim's foul trips convert to points differently from real ones.
   - Candidate causes: real fouls are concentrated and immediate; the sim has 5-s trips but fewer of them; the
     extension adds shot possessions as well as FT trips.
   - A per-bucket p cannot fix a shape miss. The pre-registered rule leaves 4-6 at p = 0.
   - Follow-up (not done): fit on FTA and points JOINTLY, or make the foul trip replace the shot possession rather
     than extend.
4. **Q4 reversion:** calibration's full FIT left Q4 at −0.093 vs real −0.141 with k = 0.002. The effect of M-EG on that
   slope is to be measured in the gate's 5:00 Q4 cells, not assumed.
- **Engine-edit gate on the MERGED file** (P3 foul mechanisms + P4 bonus free throws, 3dcc513e): corpus replay **5,400/5,400**, mismatched_cases 0, PASS, 2,669 s (2026-10-13 00:06Z).

## 9. THE GATE — native resumed sim vs `pregame_rate` and the vendored tick (2025-26, read 2026-10-13 ~04:2xZ)

**Setup.**
- Inputs: v4 as-of engine inputs (#473 team quality + starter flags, 2024-25 prior in player_logs, lineup pools
  from stints history copied as-of), 1,294 games.
- `native_resim`, 100 sims per checkpoint, through the live code path on summaries cut at the checkpoint.
- **NO live mechanisms enabled** (end-game, foul-out and foul-trouble all OFF).
- Two arms: `score_effect_k = 0.002` (proposed) and `k = 0` (production pregame today).
- Paired game-resampled 95% CIs vs `pregame_rate`.
- `vendored_replay` only in the FIT window (n ≈ 780).
- Refusals named: `no_pregame_inputs` 25-26/checkpoint, `pbp_score_mismatch` ≤ 6, `on_floor_incomplete` 2.

**REGULAR SEASON (n = 1,176-1,196 per checkpoint).** native − pregame_rate (MAE; Brier for ML):

| checkpoint | total, k=.002 | total, k=0 | margin, k=.002 | margin, k=0 | ML, k=.002 | ML, k=0 |
|---|---|---|---|---|---|---|
| end Q1 | **+0.69** [+0.44, +0.94] | **+0.63** [+0.39, +0.86] | +0.13 n.s. | **+0.28** [+0.15, +0.42] | −0.001 n.s. | +0.004 n.s. |
| end Q2 | **+0.26** [+0.09, +0.43] | **+0.31** [+0.14, +0.47] | −0.09 n.s. | **+0.14** [+0.03, +0.25] | −0.003 n.s. | **+0.004** [+0.000, +0.008] |
| end Q3 | **+0.21** [+0.12, +0.31] | **+0.25** [+0.15, +0.35] | **−0.10** [−0.20, −0.01] | **+0.08** [+0.02, +0.15] | −0.002 n.s. | −0.000 n.s. |
| 5:00 Q4 | +0.04 n.s. | +0.06 n.s. | **−0.11** [−0.17, −0.05] | −0.03 n.s. | −0.002 n.s. | −0.000 n.s. |

**Context:**
- **Total bias** (k = .002, native / pregame_rate): Q1 +3.2 / +0.3, Q2 +2.0 / +0.3, Q3 +2.0 / +1.2, Q4 −0.1 / −1.0. The
  native sim over-projects rest-of-game scoring early: a LEVEL problem, not variance.
- **Distributions:** 80% interval coverage is 0.79-0.80 on totals and 0.85 on margins (slightly wide); 50% coverage
  is 0.50-0.57.
- **Next-quarter total:** worse after Q1 (+0.19) and Q3 (+0.31) in both arms.
- **vs the vendored tick** (vendored − pregame_rate, FIT window): margin end Q1 **+0.86**, end Q2 **+0.58**. Native
  is far better on early margins. On totals vendored is +0.44 at Q1 and native +0.69 (not paired head-to-head).
  ML: vendored +0.015/+0.014 worse at Q2/Q4, native ties.

**POSTSEASON (n = 83-85):**
- Totals and ML n.s. throughout.
- MARGIN with k = .002 is WORSE at end Q2 (+0.78 [+0.26, +1.30]) and end Q3 (+0.44 [+0.11, +0.75]). With k = 0,
  n.s.
- This matches §3b: no measurable reversion in the playoffs, so imposing the regular-season reversion hurts there.
  `score_effect_k` should be population-specific (0 in the postseason) if it ships at all.

**VERDICT against the pre-registered gate (design §5):**
- **NOT PASSED.**
- Totals lose to `pregame_rate` at end Q1/Q2/Q3 in both arms.
- ML ties `pregame_rate` (and ESPN) everywhere.
- Margin with k = .002 ties or beats `pregame_rate`, and beats the vendored tick early.
- Coverage is acceptable.
- What is missing for a priced switch-on is a source of information BEYOND the naive baseline on ML and totals.
- The live-close comparison (did the native number beat the live MARKET line?) is the bar for edges. It is being
  completed: 2,500 of ~2,521 snapshots cached, rows being written.

## 10. PRE-REGISTERED 2026-10-13 13:37Z (before any result): skip_def_subtraction ON vs OFF in the PRODUCTION config (#695)

- **Asked by:** d48f3a34 relaying the user, spec superseded by lane `basketball-scenario-calibration` (owner of #695 and `nba_sim_total_inputs.json`).
- **Hypothesis (theirs, written before the result):** production overshoots its own target by ~+5.7 (EXACT_TARGET_CALIBRATION off, no NBA calibration file); skip_def adds ~+1.5 to the target, so published totals sit ~+2.7 over actual with it versus ~+1.2 without. The native re-sim's early rest-of-game overshoot (§9, bias +2 to +3 at end Q1-Q3) is the same level problem.
- **Arms:** ON = `inputs_v4` (recorded 2026-10-12 with the live file `{"skip_def_subtraction": true}`). OFF = `inputs_v5nosd`, same recorder/pristine/as-of/props snapshots, `--no-total-inputs` (file absent). Production engine object, SYNDICATE_NBA_TEAM_INPUTS absent (= on), EXACT off, no calibration file, live mechanisms OFF (k=0). Same seed per game in both arms.
- **Readings:** (1) pregame from the tip (`scripts/nba_pregame_total_bias.py`, 100 sims): total bias vs actual, MAE, minus pre-tip market total, paired ON-OFF with game bootstrap; (2) in-game: k=0 grade of OFF at the four checkpoints vs pregame_rate, paired with the existing `gate_v4_k0` (ON). Regular and postseason separate; n stated.
- **Decision rule (calibration lane's):** if ON is >= ~+2 worse on pregame total bias/MAE than OFF in this config, it proposes the revert to the user. If the in-game overshoot does NOT shrink with OFF, the level problem lies elsewhere (per-quarter targets or remaining-possession count) and #695 keeps waiting.
- **Caveat recorded up front:** the OFF inputs are recorded on today's worktree code; ON on 10-12's. A sample of pickles will be diffed field by field and any difference outside team-rating/target fields reported before the result is read.

### §8 follow-up (2026-10-13 13:44Z, reported by basketball-scenario-calibration, NOT re-derived here)
- On its #4b sample (12 FIT dates, 87 games; Phase 2 config), foul_out_in_sim + foul_trouble_bench_mult 0.05 ON reads foul-outs ~0.15/game in every arm, against real 0.193 and §8a's VALID 0.213. A different config and sample from §8a; it is not a contradiction until re-measured on the same games. OWED: P3 re-measures foul-outs/game for M-FT on those 12 dates in both configs before M-FT is proposed for production.
- The engine.py loan to that lane is returned (blowout_bench_rest, 1e85bbc5): corpus parity 5,400/5,400 by that lane.
- **Resolved (2026-10-13, reported by basketball-scenario-calibration, full FIT 791 games, combined Phase 2 config incl. M-FT):** foul-outs 0.206/game vs real 0.193 [0.162, 0.226] -- inside the real CI and consistent with §8a's 0.213. The 0.15 reading came from the 12-date subsample and did not reproduce. Top-5 starter minutes by final margin (≤6/7-19/≥20): sim 30.89/30.08/27.63 vs real 31.32/29.98/26.87. The owed P3 re-measure is withdrawn; M-FT remains a production PROPOSAL, default off.

### §10a RESULT, part 1: pregame total, skip_def ON vs OFF, production config (read 2026-10-13 22:00Z)

`scripts/nba_pregame_total_bias.py`, 100 sims from the tip, same seed per game in both arms, pre-tip OddsAPI consensus total. `/home/amyn/nba_live_bt/pgb_695/`.

| population | n | arm | total bias vs actual | total MAE | minus market | margin MAE |
|---|---|---|---|---|---|---|
| regular | 1,205 | ON (live file) | **+3.14** | 15.49 | +3.89 | 11.29 |
| regular | 1,205 | OFF | **+1.93** | 15.48 | +2.68 | 11.24 |
| regular | 1,205 | market | -0.75 | 14.60 | -- | -- |
| postseason | 85 | ON | +8.70 | 14.42 | +9.15 | 13.57 |
| postseason | 85 | OFF | +8.33 | 14.20 | +8.77 | 13.61 |
| postseason | 85 | market | -0.45 | 13.40 | -- | -- |

Paired OFF minus ON, game bootstrap:
- **Regular:** total level -1.21 [-1.35, -1.08]; |total err| -0.01 [-0.16, +0.14] (n.s.); |margin err| -0.04 [-0.17, +0.08] (n.s.).
- **Postseason:** total level -0.37 [-0.82, +0.08]; |err| -0.22 [-0.64, +0.22] (n.s.).

Reading:
- **The level moved as predicted.** The calibration lane predicted ON ~+2.7, OFF ~+1.2. Measured: ON +3.14, OFF +1.93, a gap of 1.2 against its predicted +1.5. Both arms run ~0.5-0.7 pt above its estimate.
- **Accuracy did not move.** MAE is identical. skip_def is a level shift of ~1.2 pt that the MAE is blind to; the remaining +1.9 is the engine's own overshoot with EXACT off.
- **The pre-registered revert rule ("ON ≥ ~+2 worse") is NOT met.** On bias the gap is 1.2 pt; on MAE it is 0.0.
- **Postseason:** both arms are ~+8.5 over actual, and skip_def is not the cause there (-0.37, n.s.).
- **Market:** the market beats both arms on total MAE by ~0.9 pt, regular season.

Pickle-integrity check (pre-registered caveat), 40 random games, field by field:
- 40/40 differ only in `target_home_points`, `target_away_points` and `quarters`, as expected.
- 1/40 (2026-01-15 HOU_OKC) also differs in the home side's `_prior_*_pm` columns (max |Δ| 0.8 pts/min). This is code drift between the 10-12 and 10-13 recordings, not skip_def.
- At ~2.5% of games it cannot move a paired mean of -1.21 with a CI of ±0.14 by more than noise.

Part 2 (in-game k=0 grade of OFF, paired against gate_v4_k0) is running; ETA ~02:00Z.

### §10b RESULT, part 2: in-game rest-of-game total, skip_def ON vs OFF, k=0 production config (read 2026-10-14 00:15Z)

Paired on the same 5,078 (game, checkpoint) projections. ON = `gate_v4_k0`, OFF = `gate_v5nosd_k0`; 100 sims, same seeds. Truth is the final total.

| pop | checkpoint | n | bias ON | bias OFF | level OFF-ON | total MAE ON / OFF | d|total err| | d|margin err| |
|---|---|---|---|---|---|---|---|---|
| regular | end Q1 | 1,196 | +2.94 | +2.02 | -0.92 [-1.04,-0.81] | 13.33 / 13.27 | -0.06 [-0.18,+0.07] n.s. | -0.03 n.s. |
| regular | end Q2 | 1,188 | +1.82 | +1.17 | -0.64 [-0.73,-0.56] | 11.27 / 11.15 | **-0.12 [-0.21,-0.03]** | -0.07 n.s. |
| regular | end Q3 | 1,183 | +1.99 | +1.70 | -0.29 [-0.35,-0.24] | 8.33 / 8.25 | **-0.07 [-0.13,-0.02]** | +0.01 n.s. |
| regular | 5:00 Q4 | 1,176 | -0.14 | -0.26 | -0.11 [-0.14,-0.09] | 5.71 / 5.69 | -0.02 n.s. | +0.00 n.s. |
| postseason | Q1/Q2/Q3/Q4-5 | 83-85 | +6.45/+4.67/+2.00/-0.05 | +6.42/+4.54/+1.97/-0.02 | all n.s. | -- | all n.s. | Q1 -0.31 [-0.61,-0.01], rest n.s. |

OFF against `pregame_rate` (regular, native-minus-pr total MAE):

| | end Q1 | end Q2 | end Q3 | 5:00 Q4 |
|---|---|---|---|---|
| ON | +0.63 | +0.31 | +0.25 | +0.06 n.s. |
| OFF | **+0.57 [+0.34,+0.80]** | **+0.19 [+0.03,+0.34]** | **+0.17 [+0.08,+0.27]** | +0.03 n.s. |

OFF is still WORSE than pregame_rate at Q1-Q3.

Reading:
- **skip_def is about a third of the in-game overshoot.** The level shift scales with the remaining game (−0.9 / −0.6 / −0.3 / −0.1). It buys a small, significant accuracy gain at end Q2 and end Q3, and nothing at end Q1.
- **The rest of the overshoot is not skip_def.** Bias of +2.0 / +1.2 / +1.7 remains with skip_def OFF. That is the engine-overshoot term (EXACT off), as the pregame part found.
- **The in-game gate does not pass either way.** P3's totals level fix is NOT "turn skip_def off". It needs the target/calibration stack, which is the calibration lane's Phase 2 config: total bias −0.22 on its full FIT. Next P3 step: re-gate on Phase 2-config inputs once that config is accepted.
- **Postseason:** skip_def does not explain its +6.5 early overshoot.
- **Decision (2026-10-14 ~00:3xZ, relayed by basketball-scenario-calibration, user choice "validate first"):** #695 = KEEP the skip_def file. The Phase 2 totals stack (EXACT + NBA calibration builder) goes to production only after Phase 2 finishes (#3 FT bonus, #5 volume) and its held-out VALIDATION window is read once. Until then the production config stays EXACT-off. P3 treats the ~+2 regular / +6.5 early-postseason in-game overshoot as a known production term and re-gates on Phase 2 inputs after that decision. **OPEN on both sides:** the postseason pregame +8.7 total bias, which is not skip_def.

## 11. On-floor match RATES -- the live resume cannot place players the PREGAME frame never admitted (read 2026-10-14 ~13:4xZ; lead from P5's WNBA reading)

Production sequence (`resume_from_summary` -> `map_state_names`) on the pickled pregame engine frames. A side with ANY unmatched on-floor player resumes with a SAMPLED five (by design).

**(a) 2025-26 as-of replay (inputs_v4, 5:00 Q4):**
- REGULAR, 2,392 sides: player match **0.910**; sides resumed with the real five **0.689** (745 sampled).
- POSTSEASON, 168 sides: 1.000 / 1.000.
- Misses: 1,038 / 1,081 (96%) are ABSENT from the frame, not name normalisation (43 near-name). Missed players' final-box minutes: median 25; 758 of 1,081 played >= 20.
- By month (real-five share / mean frame size):

| Oct | Nov | Dec | Jan | Feb | Mar | Apr |
|---|---|---|---|---|---|---|
| 0.45 / 12.5 | 0.57 / 13.4 | 0.53 / 13.6 | 0.62 / 13.9 | 0.80 / 15.3 | 0.92 / 16.8 | 0.89 / 17.3 |

- At end Q1/Q2/Q3 the on-floor list is empty (period break), so the engine samples the next period's five by design. Match 0/0 there is not a defect.

**(b) PRODUCTION persisted frames** (`engine_inputs/2026-10-11..13`, 13 final preseason games, 26 frames of 14-18 players):
- **165 of 375 players who logged minutes (44%) are absent from their team's pregame frame**; 43 of them played >= 20 min.
- Frame/box overlap is ~half per team (e.g. OKC 1 of 9, SAC 4 of 14). Team mapping was checked per frame (frame_team = box_team on 26/26).
- Examples: MIL Herro 23, Ware 24, Jaquez 20; CHA Naz Reid 20.

**Reading:**
- The pregame frame is built from players with HISTORY for that team. Offseason arrivals and early-season roster changes are missing, and the frame fills in as games accrue. Matches P5's WNBA finding (92.3% / 30% sampled).
- This is a **PREGAME** defect first: the pregame sim itself runs without those players, and the live resume inherits it. Live props for them cannot exist.
- Preseason is extreme (camp invitees). The regular-season ramp in (a) predicts ~45% real fives in the first weeks after 10-20.
- **Owner: not P3.** The pregame frame / roster mode belongs to the smart-sim roster path (lanes nba-pregame-lineup-pools / basketball props). Filed as a lead. P3's resume can only report it. A partial-five resume (place the matched 4, sample 1) would hide a missing starter, not fix it.

## 12. PRE-REGISTERED 2026-10-14 (before any measurement): live re-gate on the Phase 2 config, FIT window only

**Why:** the §9 gate failed on totals level in the PRODUCTION config (EXACT off, overshoot +2..+3 early). The calibration lane's Phase 2 config fixes the pregame level (PK2 bias +0.08). This gate asks whether the live resume, run in THAT config, beats `pregame_rate`.

**Config:** `fit_f3_config.json` (calibration lane, findings_2026-10-06 "FULL-FIT ENGINE CONFIG, machine-readable"), applied verbatim by `--phase2-config` (5a9c9f69) at BOTH stages:
- as-of inputs re-recorded with its env, flags, total-input keys, availability/prop-calibration copies and all 105 walk-forward calibration files;
- the resume runs with its engine flags and EventSimConfig fields.

**Population:** 2025-26 REGULAR season, **FIT window 2025-11-01..2026-02-28 only**. The VALIDATION window (03-01..04-12) and the postseason are graded ONCE, in the same pass as the calibration lane's single VALID read (agreed with that lane). Pbp/linescore-consistent games only, as §9. n stated per checkpoint.

**Checkpoints:** end Q1, end Q2, end Q3, 5:00 Q4. 100 sims, seeds as §9.

**PASS (all required, per checkpoint):**
- Total MAE: native − pregame_rate paired game-bootstrap CI upper bound < 0 at end Q1, Q2 and Q3 (better). At 5:00 Q4, not worse (CI lower bound ≥ −0.05 … upper ≤ +0.05 counts as a tie).
- Margin MAE: not worse than pregame_rate at any checkpoint (CI upper ≤ +0.05).
- ML (p_home log-loss): not worse than pregame_rate at any checkpoint.
- Total bias |·| < 1.0 at every checkpoint.

**Also read (not gated):**
- Paired native Phase 2 vs native production config (gate_v4_k0) on the same games, total and margin.
- 80% coverage.
- Refusal tally.
- The on-floor real-five share (§11).

**If PASS:** report to the user. Shadow -> priced remains the user's decision, and production must also run the Phase 2 pregame config.
**If FAIL:** name the failing market/checkpoint and stop. No re-fit inside this gate.

## 7c. PRE-REGISTERED 2026-10-14 (before any measurement): §7 game-matched end-game check in the Phase 2 #3 config (FIT only)

- **Why:** P3's end-game p by deficit (0.2, 0.0, 0.2) was fitted (§7b) in the production config, without bonus, foul fixes or EXACT. The calibration lane's full FIT passed with it held fixed. This checks it still fits at the game-matched 2:00 state in the config that will ship.
- **Method:** identical to §7 (`scripts/fit_nba_endgame_fouling.py`, 40 draws, grid {0, .2, .3, .4, .5, .6, .7}, same seeds). Base config = `fit_f3_config.json` via `--phase2-config`; the grid overrides endgame_*, and p=0 turns end-game OFF. Inputs = `inputs_p2` (Phase 2 as-of recording).
- **Population:** REGULAR, **FIT 2025-11-01..2026-02-28 only**, |margin| 1..10 at 2:00 Q4. VALID is untouched.
- **Rule (the §7 selection rule):** per bucket, the p minimising |mean(SIM − REAL)| on last-2:00 points over FIT.
  - Where it equals the shipped p, the bucket holds.
  - Where it differs, that bucket is re-fitted to it, and the solver's Δ (solver_endgame_pts_per_team) must then be re-measured by the calibration lane before the VALID read.
  - Trailer FTA (sim vs real) is READ, not gated. The 4-6 shape miss from §7b is expected to persist.

### §7c RESULT (read 2026-10-15 01:3xZ): Phase 2 #3 config, FIT only -- 2 of 3 buckets RE-FIT

Inputs `inputs_p2` (795 FIT games; the same 2 REC_FAIL dates as v4). 388 graded (40 draws per p, same seeds). Refusals: `pbp_score_mismatch` 6, `on_floor_incomplete` 10; 387 outside |1..10| at 2:00; 360 without inputs (VALID window, by design).

| bucket | FIT n | err @p=0 | err @shipped | FIT-optimal p (err) | verdict | real FTA after 2:00 | sim FTA @optimal |
|---|---|---|---|---|---|---|---|
| 1-3 | 157 | −1.26 | +0.17 (0.2) | **0.2** (+0.17) | holds | 4.76 | 3.59 |
| 4-6 | 108 | −1.10 | −1.10 (0.0) | **0.2** (+0.40) | **re-fit 0.0 -> 0.2** | 5.25 | 3.74 |
| 7-10 | 123 | −1.47 | −0.27 (0.2) | **0.3** (+0.09) | **re-fit 0.2 -> 0.3** | 4.52 | 4.03 |

**New end-game p by deficit (Phase 2): (0.2, 0.2, 0.3).**

Reading:
- In the Phase 2 config, p = 0 under-scores the last 2:00 in every bucket by 1.1-1.5 pts.
- **4-6 no longer over-shoots at 0.2** (+0.40 here vs +0.79 in §7b). The bonus, EXACT and foul fixes changed its shape enough for the rule to pick 0.2.
- 7-10's move (0.2 -> 0.3) is small: |−0.27| vs |+0.09|.
- **Shape caveat (READ, not gated):** at the chosen p, sim FTA after 2:00 is still 0.5-1.5 BELOW real in every bucket, while points match. The sim reaches the right points with too few FTs, so intentional-foul trips are too rare and too much scoring comes from shots. A per-possession foul p cannot fix both; a two-parameter version (fouling probability AND the trailer's quick-shot share) is the follow-up, if anyone needs late-game FTA props.
- **Consequences:**
  - (1) `solver_endgame_pts_per_team` (Δ′ = 0.138) was measured at (0.2, 0.0, 0.2) and must be re-measured at (0.2, 0.2, 0.3) on the calibration lane's disjoint dates, as pre-registered.
  - (2) The Phase 2 live re-gate (§12) must run on the config that carries the new p and Δ (and #5 if adopted). Its projection cache from the #3 config is stale for every checkpoint, since every resume plays through the last 2:00.
  - (3) VALID untouched.

### §7c on the FINAL config (fit_f5_config.json, sha 7fe3d0b70d0d; read 2026-10-15 16:04Z): HOLDS
FIT-optimal p = **(0.2, 0.2, 0.3)**, unchanged. Last-2:00 points error at it: −0.00 / +0.31 / −0.01 (n 157 / 108 / 123); at p=0: −1.30 / −1.20 / −1.49. Trailer FTA still low (sim 3.55 / 3.71 / 4.04 vs real 4.76 / 5.25 / 4.52), read-only. Δ″ = 0.262 stands.

### §12 RESULT (read 2026-10-15 18:35Z): live re-gate on the FINAL Phase 2 config, REGULAR FIT window -- **NOT PASSED** by the pre-registered rule, but the totals LEVEL is fixed

Run: fit_f5_config.json via `--phase2-config`, inputs_p2, 100 sims; n = 786 / 780 / 777 / 772. Refused: `no_pregame_inputs` 24-25 (the 2 REC_FAIL dates), `pbp_score_mismatch` ≤ 4, `on_floor_incomplete` 2.

| checkpoint | total: native − pregame_rate | total bias native (pr) | margin: nat − pr | ML log-loss: nat − pr | 80% cov total |
|---|---|---|---|---|---|
| end Q1 | **+0.23 [+0.02, +0.44] worse** | **+0.19** (+0.95) | −0.07 [−0.25, +0.11] | **−0.006 [−0.011, −0.001] better** | 0.78 |
| end Q2 | +0.18 [−0.01, +0.36] n.s. | +0.11 (+0.74) | −0.00 [−0.17, +0.16] | **−0.005 better** | 0.77 |
| end Q3 | +0.08 [−0.04, +0.21] n.s. | **+1.14** (+1.31) | −0.11 [−0.23, +0.01] | **−0.005 better** | 0.75 |
| 5:00 Q4 | +0.06 [−0.06, +0.18] n.s. | +0.06 (−1.08) | **−0.09 [−0.17, −0.00] better** | +0.002 n.s. | 0.77 |

**Pre-registered rule, line by line:**
- Total better at Q1-Q3: FAIL (Q1 worse; Q2/Q3 not separable).
- Margin not worse (CI upper ≤ +0.05): Q1 and Q2 FAIL by the letter (ties with upper +0.11 / +0.16). Q3 and Q4 pass.
- ML not worse: PASS everywhere, and BETTER at Q1-Q3.
- |total bias| < 1.0: FAIL at end Q3 (+1.14). pregame_rate's +1.31 there points to the remaining-period truth at that checkpoint, not to native alone. Still a fail as written.

**Native Phase 2 vs native PRODUCTION config, paired on the same games (read, not gated):**

| checkpoint | total |err| P2 − prod | margin |err| P2 − prod | total bias prod -> P2 |
|---|---|---|---|---|
| end Q1 | **−0.52 [−0.83, −0.21]** | **−0.38 [−0.59, −0.16]** | +3.98 -> +0.19 |
| end Q2 | −0.12 [−0.36, +0.12] | −0.14 [−0.34, +0.05] | +2.57 -> +0.11 |
| end Q3 | **−0.16 [−0.31, −0.03]** | **−0.18 [−0.30, −0.04]** | +2.23 -> +1.14 |
| 5:00 Q4 | −0.00 n.s. | −0.02 n.s. | −0.10 -> +0.06 |

**Reading:**
- Phase 2 removes the overshoot that failed §9: early bias goes from +4 / +2.6 to +0.2 / +0.1. It improves native on both total and margin, significantly at Q1 and Q3.
- It now **beats pregame_rate on win probability at Q1-Q3** and on margin at 5:00 Q4.
- It does NOT yet beat the naive "score + pregame line pro rata" on TOTAL; it ties from Q2 on.
- The remaining total gap is accuracy, not level. Plausible contributors, unmeasured:
  - REB −1.4/team (fewer OREB continuations);
  - the trailer-FTA shape;
  - the §11 frame gap (31% of sides resume with a sampled five at 5:00 Q4).
- **Verdict:** shadow -> priced is NOT supported on totals by this gate. On ML (and margin late) the native lens is now measurably better than pregame_rate. Whether to price ML only is a user decision; the gate as written says no.
- VALID and postseason are untouched, and are graded once with the calibration lane's single VALID read.

## 13. PRE-REGISTERED 2026-10-15 (before any VALID measurement): G3, P3's live part of THE VALID READ

Co-signed into findings_2026-10-06 "THE VALID READ — PRE-REGISTRATION". It runs ONCE, in the same pass as the calibration lane's read.

- **Population:** REGULAR VALID 2026-03-01..04-12, pbp/linescore-consistent. Game-clustered paired bootstrap.
- **Arms (FINAL − PROD), same seeds, 100 sims:**
  - FINAL = fit_f5_config.json on `inputs_p2` re-recorded for VALID dates with the walk-forward VALID calibration files.
  - PROD = gate_v4_k0 projections (production recipe; v4 inputs with #473 + skip_def; native defaults, EXACT off, k=0). **Disclosed:** PROD's VALID values were seen once in §9; FINAL on VALID is unseen.
- **PASS needs both:**
  - (a) pooled over end Q1/Q2/Q3: total |err|, margin |err| and ML log-loss each with 95% CI upper < 0;
  - (b) at 5:00 Q4: each not worse (CI upper ≤ +0.05).
- **Reported once, not gated by G3:**
  - §12 rule on VALID (FINAL native vs pregame_rate per checkpoint) and total bias;
  - postseason as a separate stratum on the calibration lane's terms.
- **No re-tuning after the read.**
- **§13 amendment, 2026-10-15 (before any VALID read; matches the calibration lane's amendment):** G3 pairs by GAME. FINAL and PROD are different configs, so their draws are independent anyway. The per-game `stable_seed` is NOT assumed to reproduce across processes (PYTHONHASHSEED etc.). Simulation noise is part of the game-clustered CI. Thresholds unchanged.
- **§13 grader smoke on the FIT window (2026-10-15 ~19:5xZ; NOT VALID; G3 deliberately NOT amended):** the G3 grader (`g3_grade.py`), run on FIT regular (816 games), FINAL − PROD:
  - pooled Q1-Q3: total −0.26 [−0.44, −0.08] ✓; margin −0.23 [−0.37, −0.10] ✓; ML log-loss −0.008 [−0.020, +0.006] ✗ n.s.;
  - 5:00 Q4: total −0.004 [−0.08, +0.08] ✗ (bar +0.05, noise-limited); margin −0.02 [−0.10, +0.06] ✗; **ML +0.010 [+0.000, +0.021] ✗, worse**.
  - => G3 as registered FAILS on FIT. It is left as written: changing it after seeing the FIT shape would fit the gate to the data.
  - Expect G3 to fail on VALID unless VALID differs materially.
  - The late-game ML regression is a real FIT finding (end-game/bonus fouling in the final config moves late win probability the wrong way), reported to the calibration lane.

### §13 RESULT -- G3, THE VALID READ (read 2026-10-16 00:0xZ, same pass as the calibration lane's read): **FAIL**

REGULAR VALID 2026-03-01..04-12; 335 games, 329-331 per checkpoint. FINAL (fit_f5) − PROD (gate_v4_k0), paired by game, game-clustered bootstrap.

| | total |err| | margin |err| | ML log-loss |
|---|---|---|---|
| end Q1 | −0.03 [−0.43, +0.38] | −0.16 [−0.48, +0.18] | −0.022 [−0.045, +0.001] |
| end Q2 | −0.06 [−0.38, +0.25] | −0.22 [−0.53, +0.08] | **−0.022 [−0.043, −0.001]** |
| end Q3 | −0.19 [−0.38, +0.00] | **−0.22 [−0.42, −0.02]** | −0.008 [−0.023, +0.008] |
| 5:00 Q4 | −0.06 [−0.19, +0.07] | **−0.14 [−0.27, −0.02]** | **−0.021 [−0.035, −0.008]** |
| **pooled Q1-Q3** | **−0.10 [−0.32, +0.13] ✗** | **−0.20 [−0.39, −0.01] ✓** | **−0.017 [−0.032, −0.003] ✓** |

- (a) Pooled all-better: **FAIL on total only.** (b) 5:00 Q4 not worse (≤ +0.05): **FAIL on total** (upper +0.07); margin and ML better.
- **G3 FAIL.** Combined with the calibration lane's G1 / G2 FAIL, THE VALID READ fails. Per the user's rule, nothing is enabled and there is no joint deploy.

**Reported once, not gated (§12 rule on VALID; FINAL native vs pregame_rate):**
- Total is WORSE at end Q1 (+0.47 [+0.13, +0.84]) and end Q2 (+0.28 [+0.01, +0.57]), with ties at Q3 / Q4.
- Margin and ML tie everywhere. The FIT-window ML advantage over pregame_rate did not hold on VALID.
- Native total bias is −1.67 / −1.42 / +1.08 / +0.10 (pregame_rate −0.77 / −0.50 / +1.47 / −0.67).

**Correction to the FIT-smoke note above:** the late-Q4 ML regression seen on FIT (+0.010) did NOT replicate on VALID (−0.021 [−0.035, −0.008], FINAL better). It is not a robust finding; withdrawn as a lead.

**Reading:**
- Phase 2 makes the live re-sim better than its production self on margin and win probability out of sample.
- It does not move totals accuracy, and it still does not beat "score + pregame line pro rata" on totals.
- The live totals problem is ACCURACY, not level. Candidate drivers remain unmeasured: REB −1.4, trailer-FTA shape, the §11 frame gap.
- Postseason: graded with the calibration lane's stratum; not run here yet (the inputs chain is still recording postseason dates).
- **§13 postseason stratum (reported, NOT gated; read 2026-10-16 ~00:2xZ), FINAL − PROD, 2026 play-in/playoffs, 83-85 games/checkpoint:**
  - pooled Q1-Q3: total **−0.63 [−1.16, −0.12]** better, margin +0.20 [−0.16, +0.59] n.s., ML −0.016 [−0.037, +0.004] n.s.
  - Early totals improve most: end Q1 −1.10, end Q2 −0.67 (both CI < 0). This matches the calibration lane's postseason G2: |total| −2.43, bias +10.45 -> +3.89.
  - 5:00 Q4 total +0.22 [−0.03, +0.49]: n.s., leaning worse.
  - So Phase 2's clearest live win is the postseason TOTAL level. Not gated, not enabling anything.

## 14. PRE-REGISTERED 2026-10-16 (before any 2026-27 data): the FORWARD shadow gate

**Why:** THE VALID READ (§13) failed, and 2025-26 has no untouched window left. The 2026-27 regular season is the only clean holdout. The shadow loop already re-sims every live NBA game. Its per-tick lanes are now kept (`live_resim_history/<date>.jsonl`, a6c3d388; loads at the next live-odds-worker restart).

**Population:**
- 2026-27 REGULAR season, first slate 2026-10-20, through 2026-12-15 or the first 300 graded games, whichever comes later.
- Preseason, NBA Cup knockout and postseason are separate and not gated.
- Games are graded per `resumeEngine` label. **If the label (engine config, `:lp=` / `:cfg=`) changes inside the window, each config is graded on its own games. Configs are never pooled.**

**Checkpoint rows:**
- For each game, the FIRST history row at or after each state: end Q1 / end Q2 / end Q3 (`period` = q, `clock_s` = 0, or period q+1 with clock > 11:00), and 5:00 Q4 (period 4, clock ≤ 300, the first row with clock ≥ 240).
- Rows with `source` ≠ live_resim are refusals, tallied by reason. A game with no row in a checkpoint's window is a MISSING row, counted and not imputed.

**Comparators:**
- `pregame_rate` built offline from the same row's score and time and the pre-tip consensus line (OddsAPI snapshot, as §9). Same metrics as §12: total |err|, margin |err|, ML log-loss vs the final; 80% coverage of total_dist.
- **If** a live market line within ±2 min of the row exists in the fleet's book-grid history: native vs live market, reported, not gated.

**PASS (all required):** the §12 rule, unchanged:
- total: native − pregame_rate CI upper < 0 at end Q1, Q2 and Q3; not worse at 5:00 Q4 (upper ≤ +0.05);
- margin and ML: not worse at any checkpoint;
- |total bias| < 1.0 everywhere.
- Game-clustered bootstrap, n stated per cell.

**Read ONCE** at the window's end. No interim peeks at the pass metrics; only row counts and refusal tallies are monitored.

## 15. FIT-only diagnosis (2026-10-16): why native live TOTALS do not beat pregame_rate

FIT regular, Phase 2 final config (gate_f5 cache), n ≈ 780 per checkpoint. VALID was NOT used (already read once).

**(a) Is native's deviation from pregame_rate informative?** w = OLS slope of (final − pr) on (nat − pr), split-half:

| checkpoint | w (all) | split-half w | sd(nat − pr) |
|---|---|---|---|
| end Q1 | **+0.02** | +0.24 / −0.17 | 3.16 |
| end Q2 | **+0.05** | −0.14 / +0.24 | 2.70 |
| end Q3 | +0.27 | +0.28 / +0.26 | 1.85 |
| 5:00 Q4 | +0.85 | +1.26 / +0.45 | 1.37 |

Early (Q1/Q2) the deviation carries ~NO information about the final total; it is noise around the pro-rata line. It becomes informative only late (Q3 partially, 5:00 Q4 mostly).

**(b) Is it the pregame target vs the market?** Removing (model target − market total) × remaining fraction (mean |gap| 2.2 pts):

| checkpoint | native − pr | anchored − pr |
|---|---|---|
| end Q1 | +0.23 | +0.14 [−0.01, +0.29] |
| end Q2 | +0.18 | +0.18 [+0.02, +0.33] |
| end Q3 | +0.09 | +0.07 |
| 5:00 Q4 | +0.06 | +0.06 |

**Reading:**
- The target gap is about 40% of the end-Q1 deficit and none of end-Q2's. The rest is the live-state response itself: the engine's early reaction to fouls, pace and score adds variance, not information.
- Monte Carlo noise at 100 sims (SE of the mean ≈ 1.3 pts) explains only ~0.05 of it.
- Implication: as specified, the §12/§14 total rule ("beat pregame_rate at Q1-Q3") is unlikely to be met by ANY state-driven re-sim of this model. Early on, the information is in the line, not in our state features.
- Options for the user, none applied:
  - (1) a state-dependent shrink: total = pr + w(f)·(nat − pr), with w fitted on FIT. It ties pr early and gains late, but needs its own pre-registered forward gate.
  - (2) price live margin/ML only, where native is better than PROD out of sample (§13).
  - (3) find what live state is informative early (in-game pace vs pregame pace, foul rate, the 3PA rate) before touching the engine.

### §15b (2026-10-16, user chose "Shrink totals"): shrink fitted on FIT in the PRODUCTION config -- it collapses to the line

The PROD config runs in production, since the VALID read failed. Data: gate_v4_k0 + inputs_v4, FIT regular, n ≈ 780. The shrink is total = B + w·(nat − B), with B = current score + the pregame TARGET total pro-rata (available live from the persisted inputs; production targets are market-anchored). w is the OLS slope clipped to [0, 1]; split-half scoring. Comparator: market pregame_rate (the gate's).

| checkpoint | w (all) | native − mkt pr | B − mkt pr | split-half shrink − mkt pr |
|---|---|---|---|---|
| end Q1 | **0.00** | +0.74 | +0.04 | +0.16 / −0.01 |
| end Q2 | **0.00** | +0.30 | −0.02 | +0.03 / −0.00 |
| end Q3 | **0.00** | +0.25 | −0.03 | +0.04 / −0.02 |
| 5:00 Q4 | 1.00 | +0.07 | +0.00 | +0.12 / −0.02 (w 1.00 / 0.64: unstable) |

**Reading:**
- In the production config the native early-game total deviation has NO usable signal (w = 0 at Q1-Q3), and the shrink reduces to "B", which ties market pregame_rate.
- It removes native's loss (+0.74 at end Q1) but cannot BEAT the line. §14's total rule ("beat pregame_rate at Q1-Q3") is therefore unreachable by a shrink.
- A live total that equals the pro-rata line has, by construction, no edge against a live book.
- **Not built**: the user's "shrink totals" choice is re-presented with this result (see the user report), since building it buys protection, not edge.

## 16. FIT-only research (user: "Find early signal", 2026-10-16): no early in-game state predicts remaining points beyond the line

FIT regular, 802-811 games per checkpoint. y = remaining regulation points − pre-tip market total × remaining fraction. Eight features from pbp-so-far: score vs line, possession rate, points/possession, FTA rate, 3PA share, foul rate, |margin|, OREB rate. OLS split-half by game, out-of-sample.

| checkpoint | resid sd | 8-feature model: OOS |err| vs line | OOS R² | intercept-only: OOS |err| vs line | mean resid (halves) |
|---|---|---|---|---|---|
| end Q1 | 14.9 | −0.11 [−0.33, +0.09] | −0.006 | −0.13 [−0.28, +0.01] | −2.11 (−2.16 / −2.07) |
| end Q2 | 12.5 | −0.10 [−0.26, +0.07] | −0.019 | −0.12 [−0.26, +0.02] | −1.92 (−2.43 / −1.40) |
| end Q3 | 8.7 | −0.34 [−0.51, −0.17] | −0.018 | **−0.37 [−0.54, −0.20]** | −2.49 (−2.95 / −2.03) |
| 5:00 Q4 | -- | -- | -- | +0.00 | −0.10 |

- Every univariate correlation is within |0.07|. Every coefficient flips sign or halves between the two halves. OOS R² ≤ 0 everywhere.
- **The only stable effect is a constant per checkpoint:** the pro-rata line over-projects remaining REGULATION points by ~2-2.5 pts at the period breaks. Part of that is OT, since the market total includes it and this y does not; the rest is the scoring shape across quarters. It is not a live-state signal.
- **Conclusion:** none of these early in-game states (pace, efficiency, FT/3PA/foul rates, score vs line, margin) predicts remaining NBA points beyond the market line in 2025-26. Together with §15/§15b, the totals edge is not in our state features. A live book sees the same box score and moves its line at least as well.
- Recommendation recorded for the user: stop live-totals modelling work; the forward gate (§14) still records totals for completeness.
- **§14 AMENDMENT (2026-10-16 ~14:4xZ, BEFORE any 2026-27 regular-season data; user decision "Re-point gate + watch"):** the forward gate is re-pointed from TOTALS to MARGIN + WIN PROBABILITY. §15 / §15b / §16 showed the totals rule cannot be met by this model: no early signal beyond the line.
  - **Comparator:** `pregame_rate` (the shadow lens runs the PROD config, since Phase 2 is not enabled, so there is no PROD-vs-FINAL arm).
  - **PASS (all required), game-clustered bootstrap, n stated:**
    - (a) pooled end Q1/Q2/Q3: margin |err| native − pr CI upper < 0, AND ML log-loss native − pr CI upper < 0;
    - (b) 5:00 Q4: margin and ML NOT significantly worse (CI lower ≤ 0). This is a noise-proof not-worse bar, the G3 lesson.
  - **Reported only, not gated:** total |err| and bias vs pr; 80% coverage; native vs live market when a ±2-min live line exists; refusals; the real-five share.
  - Everything else unchanged: population, window, config-label stratification, read ONCE at the end, no interim peeks at pass metrics.


## USER OVERRIDE 2026-10-20 20:47Z (3:47 PM CT) -- NBA live pricing ON before the §14 forward gate (lane `nba-live-board`)

- **Override, in chat (session 9e18a0e7):** "Display + money on everything", then "yes push and deploy it before 6 PM".
- **What the user was told first:**
  - THE VALID READ (§13) failed;
  - the re-sim beats production on margin and ML, but not on totals or against score + pregame line;
  - it was never measured against the live market;
  - §14's forward gate started today.
- **Change:** f0dd04bb.
  - `board_enrichment._nba_live_priced()` is ON unless `SYNDICATE_NBA_LIVE_PRICED` is 0/off/false.
  - An NBA in-play capture lane runs in the live-odds worker.
- **Live props stay unpriced:** the re-sim snapshot carries no `liveProps`, so there is no player-level live projection.
- **§14 forward read:** still runs on `live_resim_history/`, still owed, and is now read AFTER live money started on these games.
