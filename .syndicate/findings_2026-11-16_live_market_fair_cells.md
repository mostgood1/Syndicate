# live-market-fair-cells -- pre-registered KILL read, second look (2026-11-16)

Scheduled task `live-market-fair-cells-kill-read-1116`, run 2026-11-16 ~09:00-09:15 AM CST (15:00-15:15Z). Lane `live-market-fair-cells`. Read-only: no code, env, restart or deploy.

## Rule (the lane's Falsification line, unchanged)
KILL read at >= 400 pooled Tier 1 bets with >= 40 NFL-props games and >= 40 NCAAF-totals games: re-refuse (`SYNDICATE_PORTFOLIO_IN_PLAY_MARKET_FAIR_CELLS=none` on refresh-worker) if the pooled flat-unit ROI's game-clustered 95% UPPER bound is below 0. Otherwise CONTINUE to the promote read (>= 1,000 bets and >= 150 games, first possible 2026-11-24).

## Instrument (the 11-03 one, re-run unchanged)
- Source: fleet disk `~/syndicate-prod/data/reports/intelligence/opportunity_population/<date>__{nfl,ncaaf}__part*.jsonl`, 112 files (2026-10-13..2026-11-17 names).
- Live by `measured_bucket_skill._phase`, `t >= 2026-10-13T21:03Z` (16:03 CDT), `sg=True`, first sighting per side per line (line key includes UTC capture day), cells as registered (NFL row with a player; NCAAF `totals*` / non-corner `alternate_totals*`, no player).
- Extractor `C:\tmp\edge-analyses\live-regrade\kill1116\k1_extract.py` = the 11-03 `kill1103/k1_extract.py` with only the output dir changed (diff: one line). Grader `kill1116/k2_grade.py` = `lr_grade.py` with only its input file and import path changed: `score_ranking_backtest.grade_rows` -> `bucket_search.grade_population`, flat 1 unit at the RECORDED price, fleet web `http://127.0.0.1:10000`. Fleet checkout `~/Syndicate` at `10094eae0`. All jobs `nice -n 19`.
- Reproducibility check: W42..W44 in-cell counts equal the 11-03 run's exactly (NFL 47/34/78, NCAAF 56/35/23).

## Instrument is live (live sg rows by ISO week, all live rows / sg)
| week | NCAAF | NFL |
|---|---|---|
| W42 | 25,357 / 136 | 20,104 / 75 |
| W43 | 22,884 / 95 | 23,238 / 92 |
| W44 | 21,645 / 77 | 21,900 / 120 |
| W45 | 24,702 / 119 | 20,408 / 75 |
| W46 | 26,998 / 126 | 24,718 / 134 |
| W47 (to 11-16 SNF UTC) | - | 2,239 / 4 |

## Trigger: MET
In-cell first sightings: NFL props 293 bets / 68 games (W42 47, W43 34, W44 78, W45 41, W46 91, W47 2); NCAAF totals 190 bets / 135 games (W42 56, W43 35, W44 23, W45 35, W46 41). Pooled **483 >= 400**; games 68 >= 40 and 135 >= 40.
Graded 480 of 483 (3 `extra_dnp_void`, NFL props).

## Result (flat unit, recorded price, game-clustered bootstrap 4,000 reps, seed 20261014)
| cell | bets | games | W-L | units | ROI [95% CI] | wins vs consensus-fair expected |
|---|---|---|---|---|---|---|
| **POOLED** | 480 | 203 | 248-232 | +28.77 | **+6.0% [-4.1, +16.0]** | 248 vs 241.7, z = +0.59 |
| NFL props | 290 | 68 | 150-140 | +20.45 | +7.1% [-6.8, +20.6] | z = +0.63 |
| NCAAF totals | 190 | 135 | 98-92 | +8.31 | +4.4% [-10.2, +18.7] | z = +0.16 |

**VERDICT: CONTINUE.** The pooled upper bound is +16.0, not below 0, so the rule does not kill. No env change is due. The cells stay staked on paper until the promote read.

Descriptive only, NOT part of the rule:
- Per week, NCAAF totals went +22.9% / +17.6% / -10.9% / -14.4% / -7.6% (W42..W46); NFL props -2.1 / +25.4 / +1.9 / +6.0 / +9.9%.
- Since the 11-03 read (t >= 11-03 15:00Z): 196 bets, -0.4% [-17.0, +14.5]. So the pooled +6.0% rests mostly on the first three weeks.
- NCAAF totals without a sim edge (`me` null): 153 bets, +8.3% [-7.6, +24.8].
- 28 of 480 rows are exchange prices (prophetx 22, novig 6). The grader's `pnl` is at the recorded price and does not deduct commission. At ~2-3% commission on winners that is under 0.5 unit in total, so the upper bound does not move across 0.
- `central_date` in `lr_common` assumes CDT (UTC-5) after DST ended on 11-01. It is unchanged here to keep the instrument identical. It shifts only the `kc` day label for sightings between 05:00 and 06:00Z.

## Secondary: paper portfolio staked P&L on the cells
Source: the execution-ledger archive shards on the fleet disk (`reports/intelligence/execution_ledger_archive/orders_2026-1{0,1}.jsonl`), 66,974 rows. Deduplicated by idempotency key (last version kept), that is 49,128 orders, 10-02..11-16 04:22Z. The keyvalue live document read back 0 rows from this ad-hoc reader. That reflects the reader's environment, not the ledger. The archive runs to 11-16 04:22Z, so only orders after that are missing. Filter: paper, submitted >= clock, submitted >= commence (in-play), same cell rule. Every matched order is settled.

| cell | basis | orders | games | staked | P&L | ROI |
|---|---|---|---|---|---|---|
| NCAAF totals | market-fair | 577 | 189 | $1,009.65 | -$34.02 | -3.4% |
| NCAAF totals | sim edge | 461 | 157 | $1,101.17 | -$57.68 | -5.2% |
| NFL props | market-fair | 772 | 60 | $1,418.49 | +$33.73 | +2.4% |
| NFL props | sim edge | 7 | 5 | $9.32 | +$3.33 | +35.7% |
| all | | 1,817 | | $3,538.63 | -$54.64 | -1.5% |

The market-fair rows the allowlist admitted come to $2,428 staked, -$0.29, about 0.0%. Paper stakes more lines than the instrument's first-sighting set (ladder rungs, books, repeats), and its P&L is net of fees, so these numbers are not comparable to the instrument's.

## Next
The promote read needs >= 1,000 bets and >= 150 games, and is first possible 2026-11-24. At about 95 in-cell bets per full week (W45 76, W46 132), 1,000 bets lands around mid-to-late December (~5-6 more weeks; NCAAF regular season ends early December, so later). Nothing is scheduled. That is the user's call.

Artifacts: `C:\tmp\edge-analyses\live-regrade\kill1116\` (records.jsonl, graded.jsonl, k3_out.txt, k4_out.txt, scripts).
