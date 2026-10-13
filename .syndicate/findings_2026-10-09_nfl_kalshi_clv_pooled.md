# NFL Kalshi prop CLV, pooled -- lane `nfl-kalshi-clv-pooled` (pre-registered c-lanes 2026-10-09)

Measurement only. Script unchanged: `scripts/measure_nfl_kalshi_forward_clv.py` (rules of lane `nfl-kalshi-forward-clv`).
The read is taken ONCE, at the first completed week where bets with a close reach n >= 100. Scheduled:
`nfl-kalshi-clv-pooled-read` (2026-10-13 11:00 CT, after week 5's MNF; re-schedules itself for week 6 if n < 100).

## INTERIM 2026-10-09 ~18:45Z -- NO VERDICT (n_with_close 50 < 100)

Data: fleet `~/syndicate-prod/data/nfl_source` copied read-only 2026-10-09 via `\\wsl.localhost` (19 files, sha256 in
`C:\tmp\nflbt\kalshi_pooled\PROVENANCE.txt`); covers week 4 (complete) + week 5 Thursday (2026-10-08). Output
`C:\tmp\nflbt\kalshi_pooled\interim_2026-10-09\`.

| cohort | n | n with close | mean fee-net CLV [game-clustered 95% CI] |
|---|---|---|---|
| bets (first fee-net +EV ask per line+side) | 76 | 50 | -2.07% [-3.32, -0.76] |
| control (first sighting) | 575 | 291 | -5.19% [-5.63, -4.78] |
| bets, entry consensus <= 90 min old | 27 | 21 | -1.10% [-4.61, +2.01] |
| bets, entry consensus older | 49 | 29 | -2.77% [-6.08, -0.36] |

Bets mean entry EV +1.56%, share CLV > 0 0.42, slope CLV~EV +0.60; realized ROI -1.1% [-32.6, +26.6] on 43 graded.
Consistent with week 4 alone (-1.87% [-3.22, -0.67], n=44). The fee is still charged at the full Kalshi taker rate
(NFL prop series unmapped: an upper bound). Not a verdict: the pre-registered read needs n_with_close >= 100.

Operational note: copying large files from WSL to `/mnt/c` failed twice with `Cannot allocate memory` (drvfs write
path; WSL had 9.8 GB available, no lingering process). Copying from the Windows side through `\\wsl.localhost`
worked; the scheduled read uses that path.

## INTERIM 2026-10-13 ~16:10Z -- NO VERDICT (n_with_close 90 < 100; weeks 4 + 5 complete incl. MNF)

Data: fleet `~/syndicate-prod/data/nfl_source` copied read-only 2026-10-13T16:04:36Z via `\wsl.localhost` (25 files,
sha256 in `C:	mp
flbt\kalshi_pooled\PROVENANCE.txt`; the 10-09 copy kept as `quotes_interim_2026-10-09\`). Output
`C:	mp
flbt\kalshi_pooledead_2026-10-13\`. 1,390,891 quotes loaded; script unchanged.

| cohort | n | games | n with close | mean entry EV | mean fee-net CLV [game-clustered 95% CI] | share CLV>0 | slope CLV~EV | realized ROI [95% CI] (n graded) |
|---|---|---|---|---|---|---|---|---|
| bets (first fee-net +EV ask per line+side) | 116 | 30 | 90 | +1.70% | -1.91% [-3.28, -0.74] | 0.44 | +1.26 | -2.8% [-24.2, +15.6] (87) |
| control (first sighting) | 736 | 35 | 547 | -6.83% | -6.71% [-7.76, -5.62] | 0.13 | +0.94 | -8.3% [-11.0, -6.0] (570) |
| bets, entry consensus fresh | 44 | 18 | 36 | +1.96% | -0.85% [-3.59, +1.28] | 0.50 | +1.66 | -11.2% [-55.9, +25.8] (33) |
| bets, entry consensus older | 72 | 28 | 54 | +1.55% | -2.62% [-4.53, -0.94] | 0.41 | +0.45 | +2.4% [-19.8, +24.2] (54) |

Per week (bets; week by kickoff, boundaries Thu 10-08 / 10-15; gross = fair close vs ask before fee; CIs here are
analytic game-clustered from bets.jsonl, not the script's):

| week | n | games | n with close | fee-net CLV [95% CI] | gross-of-fee CLV [95% CI] |
|---|---|---|---|---|---|
| wk4 | 57 | 15 | 44 | -1.87% [-3.17, -0.56] | +1.97% [+0.58, +3.37] |
| wk5 | 56 | 14 | 46 | -1.95% [-4.10, +0.20] | +1.75% [-0.55, +4.05] |
| wk6 (Thu 10-16, not played) | 3 | 1 | 0 | -- | -- |
| pooled | 116 | 30 | 90 | -1.91% (script CI above) | +1.86% [+0.53, +3.19] |

Reading, not a verdict: the asks beat the close BEFORE the fee (+1.9%) and lose AFTER it (-1.9%); the fee is still the
full Kalshi taker rate (fee_upper_bound_share 1.0, NFL prop series unmapped), so fee-net CLV is a lower bound. Markets:
Receptions 105 of 116. Week 5 alone fell 10 short of what the lane needed; n_with_close 90 < 100 -> **no verdict**. The
read moves to task `nfl-kalshi-clv-pooled-read-wk6` (fires 2026-10-20 11:00 CDT), which takes it at n >= 100 or writes
the inconclusive read with its n and closes the lane.
