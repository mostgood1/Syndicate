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
