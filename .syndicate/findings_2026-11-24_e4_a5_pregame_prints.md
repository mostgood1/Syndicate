# E4 Amendment A5 READ -- 2026-11-24: NO_EDGE_SHOWN at the last pregame print. YES side NO EDGE in both sufficient cells (soccer GL, NBA SP-nested); NO side INSUFFICIENT everywhere; no extension owed (lane `e4-pregame-prints`, todo `#740` (e), umbrella `#736`)

Run by the scheduled task `e4-a5-pregame-print-read-1124`, armed on 2026-10-30 by session 8e021fe8 (user: "Yes, arm it").
It ran read-only on the fleet, with no OddsAPI call and no authenticated Kalshi call. All times are US Central (CST).

## Verdict

- **Overall, by A3 §9 / A5 §7: NO_EDGE_SHOWN.** No test is EDGE or LEAD. Holm (m = 8) rejects nothing, and all 8
  tests enter at p = 1.
- **R2, the registered decision read** (realised return per combo at the side's last pregame print, net of the
  upper-bound fee, game-clustered CR1 95% CI):

| Cell | YES (sim favours YES, at `q_YES`) | NO (sim favours NO, at `q_NO`) |
|---|---|---|
| MLB SP-nested | INSUFFICIENT (0 combos / 0 games) | INSUFFICIENT (0 / 0) |
| MLB SP-other | INSUFFICIENT (0 / 0) | INSUFFICIENT (0 / 0) |
| NBA SP-nested | **NO EDGE**: -6.1% [-21.2, +9.0], 246 combos / 106 games, p 0.43 (Holm-adj. 1.00); mean EV_b -3.6% | INSUFFICIENT (1 / 1) |
| Soccer GL | **NO EDGE**: -14.7% [-25.0, -4.5], 805 combos / 169 games, p 0.0047 (mean < 0, so Holm input 1, adj. 1.00); mean EV_b -4.2% | INSUFFICIENT (111 / 67): +1.3% [-7.1, +9.8] |

- **What it decides (A5 §9, registered):**
  - **No cell is EDGE**, so no PAPER combo track is recommended under Phase 5.
  - **"Combo pricing from the sim is closed" needs NO EDGE on BOTH sides of a sufficient cell. By the letter, no cell
    meets that.** Both sufficient cells read NO EDGE on YES and INSUFFICIENT on NO.
  - **The one registered extension does NOT apply.** It runs only if EVERY R2 test is INSUFFICIENT, and two are NO
    EDGE. So this reading stands, nothing is owed on 12-22, and no task is to be armed.
  - **So the YES side is answered: buying the combo the sim's correlation favours, at the price people actually
    paid pregame, loses in both sufficient cells.** The NO side stays unmeasured at the registered price, and nothing
    registered reads it further. Any further read is a new pre-registration and needs the user's decision.
- **Against A5 §10's expectation, stated before any data:**
  - MLB holds no forward combos: **matched**. The store has 0 shaped MLB rows in the window, because the season ended
    about 11-01.
  - NBA SP-nested would likely read INSUFFICIENT: **missed on YES**, matched on NO. Regular-season volume gave 1,311
    shaped combos and 272 priced (Stage 2 priced 12). YES reached 246 / 106 games.
  - Soccer GL is the only cell likely to reach minimum n: **missed in two ways.**
    - Its YES side reached minimum n, but so did NBA's.
    - Its NO side did not (111 of 200 combos). Pregame NO-taker prints are rare: 201 of 1,749 priced soccer combos
      have a `q_NO`, against 1,715 with a `q_YES`. NBA has 27 against 272.

## D0 and coverage (A5 §1)

- **D0 = 2026-10-31**, read from `runs.jsonl` (764 rows; 595 with `trades_shapes == "e4"`). 10-30 is partial: e4 runs
  start at 10-30 17:57:55Z, so the 00:00..17:57Z settlements of every series were not swept by e4. D0 matches the
  expectation.
- **Settlement dates in the window, 10-31..11-22 (23 dates).** Every second of every series was swept by e4 runs,
  except for two short gaps. Rows that settled inside them were never stored, so the script cannot count them as
  MISSING:
  - **11-08:** `KXMVECROSSCATEGORY` 18:36:58-19:04:11Z (12:36-1:04 PM CST, 27 min).
  - **11-09:** `KXMVECROSSCATEGORY0` 04:02:36-05:02:39Z (11-08 10:02-11:02 PM CST, 1 h).
  - No run without `e4` and no rollback touches any date after 10-30.
- **Runs since 10-30:**
  - `shaped_budget_stopped`: true in 0 runs.
  - Status other than `ok` in 516 runs:
    - **481 `budget_stopped`.** That is the per-run PAGE budget; the shaped-read reservation is separate and never
      stopped.
    - **35 `errors`.** Every error string after the A5 switch-on is `SliceUnreadable` (64 errors in all), which is
      retried by design. They fall on 11-01, 11-03, 11-06 (5 runs, 10:05-14:05Z), 11-13 (2), 11-18 (3), 11-19 (6),
      11-20 (2), 11-21 (3), 11-22 (4), 11-23 (5) and 11-24 (3).
  - 11-02's 24 runs read 0 shaped rows while `KXMVECROSSCATEGORY0` was livelocked (fixed `d8def445`, caught up 11-03
    03:04Z, lane block). Its settlements were swept later by e4 runs.
- **Per-cell coverage (A6 §5; rows whose settlement date and game date are both in the window):**

| Cell | Shaped rows | MISSING | Share | Stamp |
|---|---|---|---|---|
| MLB SP-nested / SP-other | 0 / 0 | 0 | -- | -- |
| NBA SP-nested | 1,311 | 0 | 0.0% | none |
| Soccer GL | 5,821 | 2 (`unreadable`) | 0.03% | none |

  - **No cell is COVERAGE-LIMITED.**
  - The report's `missing_by_settlement_date`, 83-921 a date (sum 11,962), is almost entirely NBA **SP-disjoint**:
    11,960 rows with `trades_status skipped`. SP-disjoint is not a passing cell, and the capture reads only the
    passing shapes, so those rows are unread by design. A passing cell has only the 2 soccer rows.
- **The result rests on:**
  - **NBA:** 272 combos / 109 games over 22 game dates, 10-31..11-22.
  - **Soccer:** 1,749 combos / 174 matches over 12 match dates, 10-31..11-22.
  - All of it was read from the fleet store, `/home/amyn/syndicate-prod/data`. No git-tracked data and no local mirror
    was used.

## Funnel (A5 §3 `--funnel-only`, then the read; the two agree)

| | Stage 2 (26 days, 09-30..10-25) | A5 (23 days, 10-31..11-22) |
|---|---|---|
| **MLB** candidates -> priced | 608 -> 137 | 0 -> 0 |
| **NBA SP-nested** candidates | 110 (plus 2,502 SP-disjoint) | 1,311 (SP-disjoint is not a candidate under A5) |
| NBA: no two-sided book quote at the line | 1,580 (both cells) | 561 |
| NBA: other losses | 390 no game in slot | 255 player has no sim row; 156 no pregame print; 32 DNP void; 23 no box; 11 game not matched; 1 PRA identity |
| **NBA priced** | **12 / 11 games** | **272 / 109 games** |
| **Soccer GL** candidates | 6,371 | 5,819 |
| Soccer: no two-sided book quote at the line | 2,983 | 1,241 |
| Soccer: no Stage 1 game in slot / game not matched | 216 / 687 | 206 / 572 |
| Soccer: no pregame print (A6 §2) | -- | 2,016 |
| Soccer: other | -- | 30 legs unparsed; 5 clubs unresolved |
| **Soccer priced** | **2,467 / 200** | **1,749 / 174** |

- Stage 1 machinery over the window:
  - NBA: 167 sim files -> 164 games (3 with no outcome).
  - Soccer: 293 frozen matches -> 263 (27 unmatched, 2 not completed, 1 extra time).
- Grading disagreements with Kalshi: NBA 1, which left R2/R3 as registered (so R3's n is 271). Soccer 0.
- Leg metadata: 9,602 legs, all cached in `/mnt/c/tmp/e4/cache` (39 new GETs in the first funnel run, 0 after).
  Outcome fetcher: 0 GETs, 3 cached failures.

## Fee (A3 §7, A5 §6)

- One public `/series/KXMVECROSSCATEGORY` read returned `fee_type quadratic_with_combo_maker_fees`,
  `fee_multiplier 1`.
- `venue_fees` does not know that fee type, so **m = 1.0 is stamped as an upper bound**, as in Stage 2.

## Descriptive readings (not gated)

| | NBA SP-nested (272 / 109) | Soccer GL (1,749 / 174) |
|---|---|---|
| R1 slope of (q_any - p_a) on (p_b - p_a) [95% CI] | 0.88 [0.80, 0.96] | 0.92 [0.90, 0.94] |
| R1 intercept | +0.028 | +0.010 |
| Mean q_any - p_a, pp | +12.4 [+10.9, +14.0] | +2.1 [+1.8, +2.4] |
| Mean q_any - p_b, pp | +1.5 [+0.6, +2.5] | +0.9 [+0.8, +1.1] |
| R3 `D_ba`, nats/combo (negative: the sim's joint beats independence) | **-0.062 [-0.107, -0.017]** (271 / 108) | -0.0034 [-0.0112, +0.0044] |
| Any-side R2 YES at `q_any` | -6.1% [-21.2, +9.0] (246 / 106) | -14.7% [-25.0, -4.5] (805 / 169) |
| Any-side R2 NO at `q_any` | +4.2% [-15.6, +24.1] (24 / 16) | -2.8% [-7.3, +1.6] (660 / 163) |
| R2 sensitivity, prints before commence - 15 min: YES | -6.8% [-22.2, +8.6] (233 / 103) | -15.6% [-26.5, -4.8] (736 / 167) |
| R2 sensitivity: NO | 1 / 1 | +1.7% [-7.1, +10.4] (105 / 65) |
| Joined combos with any pregame print | 1,144 of 1,300 | 2,995 of 5,011 |
| LAST print in play | 16.6% of 1,300 | **80.7% of 5,011** |
| FIRST print in play | 12.0% | 40.2% |
| Minutes from last pregame print to commence, median / p90 | 236 / 606 (n 1,144) | 30 / 750 (n 2,995) |

- **Kalshi's pregame prints carry almost all of the sim's correlation.** The R1 slope is about 0.9 in both cells, and
  the prints sit 0.9-1.5 pp ABOVE the sim's own joint. That is the margin, and it is what the YES buyer loses to.
- **Stage 2's soccer measurement problem was real and large.** 81% of soccer combos' last print is in play, against
  "at least 29%" in Stage 2's estimate. The A5 price removes it; the timing table above is the evidence.
- **R3:**
  - On NBA same-player nested combos, Kalshi's result is better predicted by the sim's correlated joint than by
    independence. That is consistent with Stage 1's NBA nested pass.
  - Soccer R3 is null on this population (Stage 2's population read -0.0111 [-0.0156, -0.0065]).
  - R3 still informs the correlation source (A5 §9). It does not show a price edge.
- Volume-weighted realised YES (A3 §1, descriptive only): NBA -21.0%, soccer +11.5%. The soccer sign differs from the
  unweighted mean. What drives it is not examined here, and it enters no test.

### A5 §8 band table at `q_any` (realised return per combo, game-clustered 95% CI)

**Soccer GL**

| Band (p_b - p_a, pp) | Combos / games | Mean q_any | Mean p_a | Mean p_b | Realised YES | Realised NO |
|---|---|---|---|---|---|---|
| <= -5 | 219 / 103 | 0.183 | 0.251 | 0.160 | -10.8% [-44.9, +23.4] | +1.3% [-5.1, +7.7] |
| (-5,-3] | 222 / 120 | 0.243 | 0.269 | 0.230 | -10.5% [-35.8, +14.8] | -1.2% [-8.7, +6.2] |
| (-3,-1] | 219 / 113 | 0.246 | 0.256 | 0.236 | +17.5% [-10.3, +45.3] | -8.6% [-16.5, -0.7] |
| (-1,0) | 143 / 83 | 0.214 | 0.215 | 0.210 | -15.9% [-52.5, +20.7] | +0.8% [-8.0, +9.6] |
| [0,1) | 141 / 84 | 0.261 | 0.250 | 0.255 | -38.6% [-61.3, -15.9] | +6.9% [-2.8, +16.6] |
| [1,3) | 190 / 98 | 0.287 | 0.259 | 0.279 | -18.9% [-38.8, +1.0] | +1.1% [-7.5, +9.7] |
| [3,5) | 234 / 112 | 0.323 | 0.273 | 0.313 | -10.6% [-28.3, +7.2] | +0.3% [-8.3, +8.9] |
| >= 5 | 381 / 165 | 0.406 | 0.298 | 0.403 | -15.2% [-28.9, -1.5] | +7.7% [-2.5, +17.9] |

**NBA SP-nested**

| Band (p_b - p_a, pp) | Combos / games | Mean q_any | Mean p_a | Mean p_b | Realised YES | Realised NO |
|---|---|---|---|---|---|---|
| <= -5 | 24 / 16 | 0.129 | 0.250 | 0.093 | -65.2% [-132.9, +2.6] | +4.2% [-15.6, +24.1] |
| (-5,-3] | 0 | | | | | |
| (-3,-1] | 0 | | | | | |
| (-1,0) | 1 / 1 | 0.303 | 0.323 | 0.323 | -100% | +40.5% |
| [0,1) | 0 | | | | | |
| [1,3) | 10 / 9 | 0.336 | 0.265 | 0.285 | -34.7% [-103.3, +34.0] | +0.5% [-45.7, +46.7] |
| [3,5) | 23 / 23 | 0.373 | 0.287 | 0.329 | -51.9% [-90.5, -13.4] | +17.4% [-11.2, +46.0] |
| >= 5 | 214 / 102 | 0.450 | 0.291 | 0.441 | -0.1% [-16.4, +16.3] | -7.5% [-21.3, +6.3] |

- NBA same-player nested pairs almost always have p_b > p_a, which is structural. That is why the NBA NO side cannot
  reach minimum n.
- No soccer band shows a YES edge; the one positive point estimate, (-3,-1], has a CI that spans 0.

## Run record

- **Code:** worktree `C:\tmp\syndicate-sessions\e4-pregame-prints`, at origin/main `9aa640865`. It holds `39891b5e`
  (the A5/A6 reader). `scripts/e4_stage2_combo_prices.py`, the capture and the Stage 1 script are unmodified.
- **Report fields:** the report carries `amendments` [A1, A2, A3, A4, A5 41cb8aba, A6], `a5_window`
  [2026-10-31, 2026-11-22], `a5_coverage`, `a5_timing`, and `R2_*_at_q_any` / `R2_*_sensitivity_15min` per cell.
- **Runs** (fleet venv, `nice -n 19 ionice -c3`, data root `/home/amyn/syndicate-prod/data`):
  1. **`--funnel-only`, 10:18-10:28 AM CST: INVALID INVOCATION, superseded.** It joined 0 soccer combos
     (`game_no_match` 5,583 of 5,819).
     - **Cause:** `SYNDICATE_DATA_ROOT` was not exported. The soccer club resolver
       (`team_aliases._soccer_alias_to_name` -> `soccer.sources.all_teams` -> the team-branding files) then reads the
       repo `data/`, and a session worktree has no `data/` by design. So every soccer club resolved to None.
     - **Proved structure-only:** Levante v Atletico Madrid, Bologna v Monza and Stoke v Preston returned `no_match`
       without the variable and `ok` with it, under both the current matcher and Stage 2's (`c0201fc5`). No price,
       probability or outcome was read in the diagnosis (`C:\tmp\e4_a5\diag_soccer.py`, `diag_match.py`).
     - **No code was changed.** NBA's join was identical in both runs.
     - Kept as `a5_funnel_nodataroot.{log,json}`.
  2. **`--funnel-only` with `SYNDICATE_DATA_ROOT` set to the fleet root, which is how the fleet roles run, 10:37-10:44
     AM CST:** NBA 272 / 109, soccer 1,749 / 174.
  3. **The registered read, the same invocation without `--funnel-only`, 10:44-10:50 AM CST:** rc 0.
- **Output (scratch, not in git):** `C:\tmp\e4_a5\a5.json`, `a5.combos.csv` (2,021 rows), `a5_run.log`, `a5_funnel.json`
  / `.log`; D0 and coverage in `coverage.py` / `coverage.out`.
- **Lesson:** a script that imports `syndicate.features.soccer` and runs from a session worktree must export
  `SYNDICATE_DATA_ROOT`; `--data-root` alone does not reach the alias maps. The A5 task text pointed the reader at a
  worktree path, and it would have silently dropped soccer.
