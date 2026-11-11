# NCAAF live SEGMENTS (h1 h2 q1-q4): the cause traced, and the shipped re-sim's segment output graded

`[2026-11-11, lane ncaaf-live-segment-display, todo #785, session d979fc08]`

## 1. Why every live NCAAF segment row showed no Live proj. — TRACED, not inferred

The inference handed to this lane (`live_gameline_join.py:2034`, "the NCAAF live re-sim seems to publish no
h1/quarter segment lanes") is CONFIRMED, and it was one of two gaps, not one.

| hop | file:line (fleet `~/Syndicate`, 11-11 ~18:05Z, `4793d823c`) | what it does to an NCAAF segment row |
|---|---|---|
| producer | `syndicate/features/ncaaf/live_resim.py` `build_game_lens` | lane `projection` = homeMargin/total/totalRunsDist/marginDist/score/period/clock. **0 occurrences of `segments` in the file.** |
| board | `syndicate/features/shared/board_enrichment.py:2989` / `:3007` | `segment_indexes` built for `ncaab`/`wncaab` and `nba` only; for `ncaaf` it stays `None` |
| join | `syndicate/features/shared/live_gameline_join.py:2046` | `own_segment_index = segment_indexes is not None and ...` -> False |
| join | `:2058-2066` | no first5 index, no own index -> `REASON_SEGMENT_NOT_FULL_GAME` |
| join | `:2070` | the display branch needs `own_segment_index` -> never reached |

**The refusal label is itself the proof of the board hop.** Had an NCAAF segment index existed (even empty), the
reason would read `segment_pricing_disabled`, as NCAAB's does. Fleet refresh-worker log, 11-11 00:08:21Z-04:45:10Z,
every non-empty `LIVE_GAMELINE_JOIN sport=ncaaf` line: **43 lines, 4,892 rows considered, 2,825 refused
`segment_is_not_full_game` (25-104 per pass), display 481 (all full-game), 0 lines carrying a segment index or
`segment_pricing_disabled`.** Read with `C:/tmp/ncaafseg/join_sum.py` over `refresh-worker.log.1`.

The inputs existed one level down and were discarded:
- `smartsim2.game_simulator.simulate_game` returns a per-quarter `quarter_log` for every seed (`home_points`,
  `away_points` per quarter, the resumed quarter counted from the carried-in score); overtime is on the scoreboard
  and in no quarter entry (`football_segment_distributions` documents the same).
- The live-state record (`scripts/poll_ncaaf_live_state._game_from_event`) carries `home_linescores` /
  `away_linescores` since 2026-09-08, on both the record and the fetch path the re-sim tick reads.

## 2. The fix (no new engine input, no new mechanism)

Per simulated rest-of-game, each segment = the points already on the board for it + the sim's points in its quarters
from the resume point on + the sim's overtime points for `h2` only, binned exactly as
`segment_actuals.SEGMENT_PERIODS["ncaaf"]` settles (q4 regulation only; h2 = q3 + q4 + every OT period). The score
already on the board is split by linescore only where the score cannot separate it (h1 in Q2 needs none); a hole
or a linescore past the score is a NAMED refusal for that segment. Draw by draw q1 + q2 = h1 and h1 + h2 = full
(both calibrators are identity). `board_enrichment` builds NCAAF per-segment indexes with segment pricing OFF, so a
segment row refuses `segment_pricing_disabled` and carries the number for DISPLAY only. `marginAnchored` is False:
segment moneylines show nothing (a football quarter ties too often for "P(home leads)" to be the bet's two sides).
Off switch `SYNDICATE_NCAAF_LIVE_SEGMENTS=0` restores the old lane byte for byte and the old refusal label.

## 3. The grade — cutoff replay of the SHIPPED `resim_live_game`

`scripts/backtest_ncaaf_live_totals.py --market segment_total|segment_margin` (new), each open segment at each cutoff
against what it really scored. Ladders are centred on the segment's FROZEN value (points already in it), observed,
never modelled. Run on the fleet host at nice 19 from the session worktree, `SYNDICATE_DATA_ROOT` = the fleet's.

**Population:** six Saturdays 2026-10-03 .. 2026-11-07, ESPN completed FBS games with linescores: 294 found, 7
refused unrated (FCS side), **287 games, 861 quarter-end cutoffs**, 0 duplicate rows. 120 sims (production's).
**Ratings:** production's SP+ cache, `fetched_at 2026-11-09T15:39:46Z`, `verified=True` — they POSTDATE every game,
so a PASS is an upper bound and only a FAIL is decisive. **Possession is unknown at every quarter-end cutoff**, so
the draws are the pooled two-plan mixture, WIDER than a production state with possession known; with the sim
already narrower than the residual (sd ratios 0.84-0.94 below), production's live states are if anything more
over-confident than graded. Same limitations the full-game grade shipped on.

`#499`'s bar: worst POWERED bucket gap <= 0.150 (n >= 30 cells).

### Totals

| segment | cutoff rows | worst bucket | gap | bias | MAE | MAE frozen | sim sd / resid sd |
|---|---|---|---|---|---|---|---|
| full (reference) | 861 | 0.1-0.2 | 0.0614 | -0.548 | 8.89 | 27.32 | 9.59 / 11.28 = 0.850 |
| segments pooled | 2,870 | 0.0-0.1 | 0.0804 | -0.187 | 6.70 | 16.22 | 0.879 |
| h1 (= q2 at end Q1) | 287 | 0.3-0.4 | 0.0771 | -1.911 | 6.36 | 15.41 | 0.883 |
| q2 | 287 | 0.3-0.4 | 0.0771 | -1.911 | 6.36 | 15.41 | 0.883 |
| h2 | 861 | 0.0-0.1 | 0.1402 | +0.089 | 8.15 | 22.18 | 0.861 |
| q3 | 574 | 0.6-0.7 | 0.1408 | +1.052 | 5.80 | 11.38 | 0.909 |
| **q4** | 861 | **0.0-0.1** | **0.2398 FAIL** | -0.141 | 6.06 | 14.03 | 0.939 |

q4's failing cell: n=35, predicted P(over) 0.0745, realised 0.3143 — the last quarter's right tail is too thin. Its
next bucket (0.1-0.2, n=272) reads 0.156 vs 0.228. **Decision: the lane withholds q4's totals histogram**
(`live_resim._SEGMENT_TOTALS_WITHHELD`) and keeps its mean (bias -0.14, MAE 6.06 vs 14.03 frozen), so a q4 totals
row shows the live total and no probability, as NHL totals do. h1 and q2 are the same reading at the only cutoff
both are open (end of Q1), ladders centred on each one's own frozen value.

### Margins (spreads)

| segment | cutoff rows | worst bucket | gap | bias | MAE | MAE frozen | sd ratio |
|---|---|---|---|---|---|---|---|
| full (reference) | 861 | 0.2-0.3 | 0.1175 | -1.090 | 8.44 | 9.56 | 0.956 |
| segments pooled | 2,870 | 0.2-0.3 | 0.0965 | -0.630 | 6.82 | 7.21 | 0.955 |
| h1 / q2 | 287 | 0.1-0.2 | 0.1015 | +0.039 | 7.12 | 7.62 | 0.841 |
| h2 | 861 | 0.2-0.3 | 0.1431 | -1.103 | 7.83 | 8.50 | 0.975 |
| q3 | 574 | 0.7-0.8 | 0.0629 | +0.570 | 6.32 | 6.30 | 0.928 |
| q4 | 861 | 0.4-0.5 | 0.1342 | -1.403 | 5.94 | 6.24 | 1.084 |

Every segment passes the bar; h2 (0.143) and q4 (0.134) are close to it. Showing them needs the join's
`_RAW_MARGIN_DISPLAY_SPORTS` to name ncaaf (a separate decision, see the lane).

**Side reading, not this lane's:** the FULL-GAME margin reads worst bucket 0.1175 on this Oct-Nov sample against
0.0411 on the 2026-09-27 Saturday grade, with the home side under-predicted (bias -1.09; buckets 0.1-0.5 realise
7-10 pp above predicted). Still under 0.150; consistent with `#780`'s "spread 10-30% too narrow".

### Kickoff cutoff (`--cutoffs 0`, new) — the only cutoff at which q1 is open

Same 287 games, one row each at Q1 15:00, 0-0 (the resume-at-kickoff state; possession pooled).

| segment | totals worst gap | totals bias | margins worst gap | margins sd ratio |
|---|---|---|---|---|
| full (reference) | 0.1219 | +0.79 | 0.1397 | 0.974 |
| pooled | 0.0767 | +0.34 | 0.0854 | 0.950 |
| h1 | 0.0851 | +0.08 | 0.1435 | 0.930 |
| h2 | 0.1354 | +0.71 | 0.1140 | 0.967 |
| **q1** | **0.1863 FAIL** (0.4-0.5, n=107: 0.448 predicted, 0.262 realised) | **+1.41** | 0.0780 | 1.073 |
| q2 | 0.0489 | -1.33 | 0.1081 | 0.882 |
| q3 | 0.0948 | +0.51 | 0.0599 | 0.931 |
| q4 | 0.1004 | +0.67 | 0.1188 | 1.084 |

q1's failure is LOCATION, not shape: buckets 0.2-0.9 all realise 4-19 pp under predicted, and the mean runs 1.41
points high on an ~11-point quarter -- the sim scores too much in the first quarter (and too little in the second:
q2 -1.33), which cancels in h1 (+0.08). **Decision: the lane withholds BOTH q1 totals numbers** (histogram and mean);
a q1 totals row shows nothing.

## 4. What the lane carries, and therefore what the board can show

| segment | totals (Live column) | spreads | moneyline |
|---|---|---|---|
| h1, h2, q2, q3 | live total + P(over) | histogram carried; shown only if `_RAW_MARGIN_DISPLAY_SPORTS` names ncaaf | blank by design (ties) |
| q4 | live total only | as above | blank |
| q1 | nothing | as above | blank |

Every grade above is an upper bound (ratings postdate the games; pooled possession widens the draws). The bar it
clears is `#499`'s for PRICING; this is DISPLAY only, priced nowhere, with `SYNDICATE_NCAAF_LIVE_SEGMENTS=0` as
the off switch.

Reproduce: `C:/tmp/ncaafseg/grade.sh` (fleet host, nice 19) per Saturday with `--dump-rows`, then
`py -3 C:/tmp/ncaafseg/score_merged.py <repo> <dir>`; rows in `C:/tmp/ncaafseg/rows_*.json` (quarter-end) and
`kick_*.json` (kickoff).
