# NCAAF in-season blend — forward grade on 2026 weeks 3-4, margins AND totals (todo #677, 2026-09-28)

Lane `ncaaf-blend-forward-grade`, session e4b479b7 (scheduled task `ncaaf-677-grade-blend-vs-close`). Measurement only: no deploy, no env change, no model code touched. Read 2026-09-28 ~10:00 CT.

## Bottom line
- **Margins:** the blend (B) is **not distinguishable from SP+-only (S)**: B-S **+0.63 [-0.85, +2.07]**, n=113, point estimate on S's side. It is **behind the close** by +1.95 [+0.88, +3.04]. The backtest's -3.50 gain was against *prior-season* SP+; against production's *refreshed 2026* SP+ this sample rules out any gain larger than ~0.85 pts MAE.
- **Totals (never measured before):** the blend is **better than S**: B-S **-1.24 [-2.44, -0.04]**, n=113 (CI barely excludes 0). It is behind the close by +1.42 [+0.01, +2.79].
- The pre-stated trigger ("blend worse on totals, or on margins against S, with the CI excluding 0") is **NOT met**. No change is indicated by this data.

## Inputs (all pregame, saved from production)
| week | CSV (sha256 checked) | CSV generated_at (UTC) | rows / on blend | SP+ snapshot fetched_at | blend entry generated_at |
|---|---|---|---|---|---|
| 3 | `smartsim2_projections_2026_wk3.csv` `4d908da7…` | 09-18 23:16:21 – 23:24:28 | 57 / 57 | 09-18 23:16:11 (138 teams) | 09-18 23:16:15 |
| 4 | `smartsim2_projections_2026_wk4.csv` `37a98d94…` | 09-25 16:05:05 – 16:11:47 | 58 / 58 | 09-25 16:04:52 (138 teams) | 09-25 16:04:56 |

All six manifest sha256s re-computed and matched. Snapshots at `C:\tmp\ncaaf_677_snapshots\wk3|wk4\`; everything this run produced (scripts, arm outputs, raw CFBD responses, per-game table) at `C:\tmp\ncaaf_677_snapshots\grade\`.

## Method
- **B** = the snapshot CSV's `margin_mean` / `total_mean` (home minus away; home+away).
- **S** = the same games rebuilt through the generator's own `build_projection` (300 seeds, seeds 1..300), with `sp_index` = the SNAPSHOTTED `sp_ratings_2026.json` held pregame that week, `SYNDICATE_NCAAF_INSEASON_BLEND=off`, scratch `SYNDICATE_DATA_ROOT`/`SYNDICATE_NCAAF_SOURCE_ROOT`, calibration profile `ncaaf-goal-line-refit-1` (origin/main `data/calibration/ncaaf_profile.json`, via `SYNDICATE_CALIBRATION_PROFILE_DIR`), drive priors off. `main()` was NOT run (it refreshes caches and calls `publish_hot_artifact`, which with `.env` loaded could overwrite web's CSV). Today's SP+ was never read.
- **Proof the rebuild is the production path, off != on:** the same driver with `sp_index` = the snapshotted blend entry reproduces the production CSV **exactly on 113/115 rows** (margin and total to 3 dp) and within 0.03 pts on the other 2 (Illinois @ Ohio State, Liberty @ Coastal Carolina — the blend artifact rounds ratings to 4 dp). Swapping in the SP+ snapshot moves margins by 7.94 and totals by 6.55 on average, so S is a different arm; all 115 team pairs rated in both indexes (no PPA fallback in either arm). S rows carry `cfbd_sp_plus_2026_snapshot_wk<W>[scale=10]`; the generator's `inseason_blend_enabled()` returned False in the S processes.
- **C** = CFBD `/lines` provider **DraftKings** for every game (DK covers 119/119 wk3 line rows; Bovada only 78). The field is CFBD's latest recorded `spread`/`overUnder` (separate from `spreadOpen`), taken as the close. **Sign checked on a known game:** Miami @ Wake Forest, `formattedSpread "Miami -20.5"`, `spread -20.5` → implied home margin = -spread = -20.5.
- **Results** from CFBD `/games` (`homePoints`/`awayPoints`, `completed`), joined on CFBD game id = CSV `game_id`, team orientation checked.
- **CIs:** `backtest_ncaaf_inseason_blend.paired_delta_ci` (paired |err| difference, bootstrap over games, 10,000 reps, seed 677).

## Coverage
115 rows → **113 graded** (wk3 56, wk4 57; 2 neutral-site). Dropped, with reason:
- wk3 Syracuse @ Pittsburgh (401858225) — kickoff 09-17 23:30Z is BEFORE the row's generated_at 09-18 23:16Z (Thursday game; the daily re-write stamped a post-kickoff row). Not pregame.
- wk4 Liberty @ Coastal Carolina (401869941) — kickoff 09-24 23:30Z before generated_at 09-25 16:05Z. Same cause.
No row was dropped for FCS/unrated, missing result, or missing close. The CSV is FBS-vs-FBS by construction, so the week's FCS games are outside this grade entirely.

## Numbers (MAE vs actual; paired deltas negative = first arm better)
| cell | n | metric | B | S | C | B-S [95% CI] | B-C [95% CI] | S-C [95% CI] |
|---|---|---|---|---|---|---|---|---|
| wk3 | 56 | margin | 10.82 | 10.52 | 8.80 | +0.29 [-1.90, +2.54] | +2.02 [+0.37, +3.71] | +1.72 [+0.37, +3.08] |
| wk3 | 56 | total | 16.43 | 17.28 | 14.02 | -0.85 [-2.63, +0.93] | +2.41 [+0.61, +4.26] | +3.27 [+1.31, +5.15] |
| wk4 | 57 | margin | 13.19 | 12.22 | 11.30 | +0.97 [-0.86, +2.81] | +1.89 [+0.54, +3.31] | +0.93 [-0.88, +2.69] |
| wk4 | 57 | total | 11.21 | 12.84 | 10.76 | -1.63 [-3.29, -0.09] | +0.45 [-1.62, +2.49] | +2.07 [+0.15, +4.12] |
| **pooled** | **113** | **margin** | **12.01** | **11.38** | **10.06** | **+0.63 [-0.85, +2.07]** | **+1.95 [+0.88, +3.04]** | +1.32 [+0.17, +2.43] |
| **pooled** | **113** | **total** | **13.80** | **15.04** | **12.38** | **-1.24 [-2.44, -0.04]** | **+1.42 [+0.01, +2.79]** | +2.66 [+1.24, +4.05] |

Mean error (bias, model minus actual), pooled: margin B -0.79, S +0.08, C +0.85; total B -1.53, S -0.27, C -1.27.

Largest B-vs-S total disagreements (all wk4 unless noted): Texas A&M @ LSU B 30.8 / S 57.6 / close 52.5 / actual 41; Tulsa @ Arkansas 50.9 / 75.0 / 51.5 / 40; UConn @ Miami (OH) 61.2 / 38.0 / 52.5 / 45; wk3 Miami @ Wake Forest 66.3 / 45.4 / 55.5 / 53.

## What this can and cannot rule out
- **Can:** the blend is not materially WORSE on totals than refreshed SP+ (CI upper bound -0.04). Neither arm matches the close on either market (all four pooled B-C and S-C CIs lie above 0), so picks staying suppressed remains right.
- **Cannot:** whether the blend helps or hurts MARGINS against refreshed SP+ — the CI spans -0.85 to +2.07. The point estimate (+0.63) leans toward S, which is the opposite of what the backtest suggested; it is two weeks of 56-57 games. 2026 SP+ is itself an in-season rating that absorbs results (the wk4 snapshot was fetched 09-25, after week 3), so it is a much stronger baseline than the backtest's prior-season stand-in, and the backtest's -3.50 does not transfer.
- The totals win is marginal (upper bound -0.04) and is one of four cells examined; treat as suggestive, not settled. Week 3 alone did not exclude 0.
- Two weeks, two slates: slate composition (week 3 is still non-conference-heavy) and weather are not controlled.
- "The close" is CFBD's last recorded DraftKings number; its capture time is not in the payload.

## Decision (the user's)
None forced: the pre-registered harm trigger was not met on either market. Options, NOT acted on:
1. Keep the blend as is and keep grading forward. Weeks 5-6 would double n to ≈ 230, enough to resolve a margin effect of ~1 pt either way; a 0.6-pt effect needs ~5x this n (most of the season).
2. If the margin lean toward S persists: blend TOTALS only and price margins off refreshed SP+ (new code in the generator and the live re-sim — a mechanism change, owes its own measurement).
3. Full off switch: `SYNDICATE_NCAAF_INSEASON_BLEND=off` + a refresh-worker deploy (reverts pregame and live). This data does not support it: it would give back the measured totals improvement.
