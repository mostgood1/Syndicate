# 2026-11-20: Layer 2 rail monitor findings (lane `layer2-rail-monitor`)

Slate day 11-20 (the slate day rolls at 5 AM CST). Lean mode since 11-20: the Claude-free Windows task `SyndicateRailWatch` takes the readings into `C:\tmp\railmon\dash\rows_2026-11-20.jsonl` and the Rail Watch page. This file holds the owned readings and the nightly close's summary.

## R-D #851 P6 baseline, night 1 (OddsAPI credits; 00-05Z on 2026-11-21 = 11-20, 6-11 PM CST)

Read-only, by the runbook's method. P6 was registered 11-20 by local_73a5d2dd; the user typed "Keep it in" to "Keep #851 in the 11-24 batch with that OddsAPI cost?". #851 is NOT loaded (default off; it is CHANGE E of the 11-24 batch), so this is a baseline night.

| | 00Z read | 05Z read |
|---|---|---|
| read_at | 2026-11-20T23:59:48Z (5:59 PM CST) | 2026-11-21T05:00:13Z (11:00 PM CST) |
| `quota.latest.used` | 2,568,438 | 2,632,771 |
| remaining | 2,431,562 | 2,367,229 |
| fleet `credits_per_hour` | 5,491.3 | 5,738.3 |
| fleet `projected_30d_credits` | 3,953,745 | 4,131,609 |

- **Credits per hour, 00-05Z: 12,849.** That is 64,333 credits over 5.007 h, from the two reads in `C:\tmp\railmon\p851_quota.jsonl` (labels `base1120_00Z`, `base1120_05Z`).
  - The fleet's own `credits_per_hour` (5,491 and 5,738) averages over a longer window that includes quiet hours. It is not this evening rate.
- **Lane sweeps in the same window: 126 `ODDS_SWEEP_LAUNCHED` lines** (live-odds-worker, all `date=2026-11-20`, ALL_PROCESS_MEMORY lines excluded). They carry **535 sport sweeps**: nba 121, ncaab 126, ncaaf 126, wncaab 126, nhl 14, nfl 11, soccer 11.
  - Counted on the exact read window by `C:\tmp\railmon\p851_sweepcount.py 2026-11-20T23:59:48 2026-11-21T05:00:13`.
  - `p851_loopstages.py 2026-11-21` counts on its own 00-05Z iteration window: 122 launches in tick spans plus 1 outside. Its `#851 P2` gap counts are nba 119, ncaab 124, ncaaf 124, wncaab 124, nhl 13, nfl 10, soccer 9 (ALL 523; n = gaps, so one fewer than launches per sport). The gaps are p50 82 s and p90 330 s, NCAAB p90 301 s.
  - Context, same window: 122 main-loop iterations, p50 82 s, p90 304 s, 36 over 180 s; 33 slow iterations (post > 120 s), all of them with a slate write inside.
- **Credits per sweep: 511 per launch, 120 per sport sweep.** Both are upper bounds: the quota delta counts every OddsAPI caller in the window, not only the lane sweeps.
- **Inference, one night only:** at 120 credits per sport sweep, the lane's +24% evening sweeps would cost up to ~15k credits an evening, about +0.46M over 30 days. That is above the lane's +0.24-0.4M estimate. On the 4.13M projection it would put the month at ~4.6M of the 5M cap. Re-check with night 2.
- **Next:** night 2 is the 11-21 evening (6 PM and 11 PM CST reads). The 11-24 reading compares its 00-05Z credits per hour, and per sweep, against the mean of the two baseline nights. P6 holds at no more than +30%.

## DAILY SUMMARY — Fri 11-20 (day 6, the first lean day), closed 1:10 AM CST 11-21

46 readings by the Windows task, 10:00 AM to 12:43 AM CST, every 20 min with no failed tick (`railwatch\tick.log`). POP_START 16:00Z. Flags are graded on their first sighting against the finals by date (`C:\tmp\railmon\grade_2026-11-20_out.json`).

### The grade

| bucket | flags | games | W-L-P | hit | fair | hit − fair, 90% CI (game-clustered) |
|---|---|---|---|---|---|---|
| **ALL** | 525 | 73 | 249-274-2 | **0.476** | 0.475 | [−0.040, +0.045] |
| P3 first reading: yes | 74 | 40 | 39-35 | 0.527 | 0.476 | [−0.033, +0.152] |
| **P4 fair < 0.40** | 65 | 14 | 8-57 | **0.123** | 0.216 | **[−0.144, −0.026]** |
| P5 NCAAB full totals | 125 | 45 | 68-57 | 0.544 | 0.500 | [−0.043, +0.131] |
| NCAAB full spreads | 77 | 38 | 44-32-1 | 0.579 | 0.503 | [−0.043, +0.193] |
| **sport: NBA** | 176 | 9 | 61-114-1 | **0.349** | 0.413 | **[−0.112, −0.015]** |
| NBA calibrated totals | 98 | 9 | 34-63-1 | 0.351 | 0.431 | [−0.180, +0.025] |
| segment totals (all sports) | 105 | 42 | 42-62-1 | 0.404 | 0.494 | [−0.171, +0.004] |
| segment spreads (all sports) | 40 | 16 | 13-27 | 0.325 | 0.414 | [−0.191, +0.013] |
| NCAAB raw (uncalibrated) totals | 49 | 31 | 20-29 | 0.408 | 0.497 | [−0.209, +0.033] |

- **The flags hit their fair again, no better** (third day running: 11-18, 11-19, 11-20). The model's own mean p on them was 0.579 against a 0.476 hit, so it is about 10 pp over-confident on the side it flags. That is the per-line calibration case (#847, 11-26 grade).
- **Long shots lost more than their price said.** Model mean 0.371, fair 0.216, hit 0.123, with the CI clear of 0. Of the 65, 31 were NBA tails (4-27). P4 is met as written (at most fair + 2 pp), but the direction is the finding. Evidence for #847.
- **NBA under fair for a third day:** 11-18 0.313 vs 0.392; 11-19 0.385 vs 0.503; 11-20 0.349 vs 0.413, CI below 0. There were 176 flags, but in only 9 games. Evidence for #847, not a gate.
- **Calibrated NCAAB totals were above fair** (0.540 vs 0.500) and raw ones below (0.408 vs 0.497). Both CIs cross 0.

### Pre-registered verdicts (standing P1-P6, P8)

| # | prediction | result | verdict |
|---|---|---|---|
| P1 | 0 rail-card contradictions | 1 at R32 (8:03 PM), 1 at R34 (8:43 PM); 0 at the other 44 | **NOT MET as written; neither is a model fault.** R32 is the card's OURS lagging the flagged row by one re-sim (LEAD 2). R34 is a 2OT tie whose extra-period branch pulled the mean above an under the model favoured (the under won, 204) |
| P2 | board publication gap median ≤ 600 s, none > 1,800 s, 5:30-10:30 PM | 47 publications, median 338 s, max 1,062 s (7:26-7:44 PM), 5 over 600 s (`C:\tmp\railmon\p2_boardpub.py`, refresh-worker log) | **MET** |
| P3 | first-reading flags at or below fair | 0.527 vs 0.476, CI [−0.033, +0.152] | **within noise** (above, not significant, as on 11-19) |
| P4 | long shots (fair < 0.40) at most fair + 2 pp | 0.123 vs 0.216, n 65 / 14 games | **MET** (far below fair; see above) |
| P5 | report NCAAB calibrated live full totals | 125 flags / 45 games, 0.544 vs 0.500; under 101 / over 24; the flagged lines went over 63 of 125 | report (11-19: 0.525 vs 0.502) |
| P6 | 0 pregame NCAAB / WNCAAB totals flags | 0 at all 46 readings | **MET** |
| P8 | score floor: 0 college calibrated full totals below the score | 14 rows at R32, 7 at R33; 0 at the other 44 (up to ~170 rows a reading) | **NOT MET as written; the readings are timing, not the floor.** All 21 rows came from 4 games in the last 4-39 s of regulation (Niagara @ Delaware St H2 0:17, Georgia St @ Jacksonville St 0:12, Oakland @ Purdue 0:04, Iowa @ Xavier 0:39). Their re-sim was 1.5-3.5 min older than the chip's score. In 3 of the 4, the re-sim's own final total is below the chip's score (162.9 vs 165, 143.1 vs 144; Georgia St's away 76.1 vs 77), which a re-sim cannot produce at its own score. Iowa @ Xavier (141.0-141.8 vs 142) cannot be decided from the reading |

- **P2's daytime run:** the whole day's longest board gap was 1,526 s at 9:55 AM (p7count), outside the window.
- **An instrument fault in P2's runbook source:** `d4metrics.py <start> <D> <end>` reads only the tail of each log, so a run long after the window under-covers it. At 1 AM it showed 9 builds and 0 sweeps for 5:30-10:30 PM, and still reported `log_window_covered: true`. P2 is graded from the log itself by `p2_boardpub.py`.

### What the day found

- **I-29, neutral-site joins:** 4 of 4 reoriented NCAAB games had no live model all game: GW @ UAB, W. Illinois @ Albany, VT @ Northwestern, Richmond @ WKU. All 47 games that joined directly were modelled (`extra_2026-11-20.jsonl` orient lists). Since 11-02 that is 28 of 28. The fix is change G of the 11-24 load (lane `college-neutral-site-live-join`); no decision is owed.
- **Games with no live model, other than I-29** (21 readings had at least 1):
  - one-reading misses at tip-off (`not_in_resim`, 12 games);
  - NBA at tip-off: Pacers @ Cavs and Magic @ Nets at R28, before the re-sim picked them up at 6:44-6:47 PM; Suns @ Jazz at R34 (`no_plays` at 8:42 PM);
  - NBA by design: Magic @ Nets at R34-R35, the #814 `key_player_out` refusal for BKN Nolan Traore, 8:32-9:05 PM (deploys.md 02:37Z reading);
  - WNCAAB `no_margin_anchor` and end-of-game refusals (up to 16 of 18 live WNCAAB games refused);
  - one NCAAF reading (Oregon @ Michigan St).
  - Since 3:50 PM the list counts only totals and spreads rows. Before that, soccer flickered onto it because of corners / BTTS / h2h rows (`dash_update.py`, `e69d8b4b3`).
- **LEAD 1, soccer h2h has no live number:** 0 of 16 soccer h2h rail rows (home 10, away 4, draw 2) carried a live model. NBA, NCAAB and NHL h2h do get one (`display.prob_over`, side-mapped by `layer2_board._live_prob_for_side`). The soccer live lens produces win probabilities, so the lane is not handing them to h2h rows. Not traced; it belongs to the soccer lane's owner.
- **LEAD 2, the card's OURS can be one re-sim behind its own row:** on an uncalibrated total, the rail card's OURS is the chip's `intervals.final.total` (`intelligence.html` ~3578: it beats the row's own `live_total`). At R32, Wisconsin @ Murray St showed OURS 131.0, from the chip's 7:59:46 PM re-sim, beside UNDER 128.5 p=0.725. That row projected 126.7 itself (8:03:28 PM build). A display-only fix would prefer the flagged row's own `live_total`. It belongs to the I-17/#803 owner.
- **LEAD 3, P8 compares the row's total with a newer score.** In the last minute of a close game the re-sim trails the score by a possession or two. A clean test needs the score the re-sim ran at, carried on the row; the row does not carry it today. Instrument only.
- **R-D #851 P6 baseline, night 1:** 12,849 credits/h 6-11 PM; at most 120 credits per sport sweep (block above).
- **R-F #850 repeat evening** (sent to local_d0f83044):
  - Qualifier, borderline: 26 core live games at the 7:03 PM reading (threshold 33), 37 at 7:23 PM; no refresh-worker restart (parent pid 1011283 all day).
  - P1: **13 refusals, FALSIFIED** (3/3/3/1/3 an hour; 11-19: 4). CORRECTION 1:25 AM: this file first said 15. The monitor's `p7count.py` counted every `MEMORY_GUARD_ABORT` stage, while §5's P1 counts `stage=pre_source_state_fingerprint` only. The other two were one `build_candidate_pool_start` and one `post_pull_hot_artifacts`. The owner's reading on main, `9d3644bfd`, is the record; `p7count.py` now prints the split.
  - P2: 3 child exits, all rc 75, 0 fatal (NEITHER).
  - P3: longest build gap 1,062 s (NEITHER).
  - Parent RSS ~9 PM p50 2,255 MB. It was ~1.7 GB all afternoon, rose from 6 PM, peaked at 2,396 MB at 10:03 PM and did not fall back.
  - Whole slate day: 38 aborts, 6 child exits (all rc 75), 21 of 21 post-build checks held by `transient_jobs`.
  - The owner decides whether the evening counts and what the next lever is. Any lever is a betting change.
- **Fleet-watcher flags (local_379fd729):** every one was diagnosed and answered in a line. They were the I-29 games above, the soccer no-model flicker (instrument, fixed), NBA tip-off timing, the WNCAAB end-of-game refusals and the two P1 contradictions. Nothing needed routing.
- **Team cards:** 226 chips, 0 defects at every reading. 0 false and 0 missed flags at every reading; dark rows at most 4 (R28, 6:43 PM, the NBA tips).

### Loads (11-20)

All three were web-only, all `betting change: no`. The workers did not restart (refresh-worker parent pid 1011283 all day).
- **11:03 AM:** web stall instruments `3c8ba5b14`, ff + reload-web (52 s, a 73 s board query in flight).
- **11:38 AM:** the combined board read leaves the 40 MB Layer 2 shortlist encoded, `eeeb62a63`.
- **2:13 PM:** the `WEB_GC_PAUSE` line is written by the heartbeat, not the GC callback, `0d20a6919` (BC-056). It fixed the 2:01 PM worker kill.

### Owned readings (R-A..R-G)

- **R-A** score floor: see P8 (timing, 2 readings).
- **R-B** #844: verdict on 11-24 if change D loads.
- **R-D** #851: night 1 done; night 2 on 11-21 (6 PM and 11 PM reads); measurement on 11-24.
- **R-F** #850: read tonight (above). The parent floor is read at 9:04 AM 11-21.
- **R-G** #853: 11-24, 11:20 PM.

### Open user decisions

- None new tonight.
- #850's next lever comes to you through local_d0f83044, if its owner proposes one after tonight's 13 refusals. Any lever is a betting change.
- #851's cost: night 1 reads above the lane's estimate (~+0.46M vs +0.24-0.4M a month). It is not a decision until night 2 confirms it.
