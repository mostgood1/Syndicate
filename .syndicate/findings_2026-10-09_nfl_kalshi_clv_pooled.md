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


## THE READ 2026-10-26 ~15:42Z -- HYPOTHESIS SUPPORTED: fee-net CLV CI wholly <= 0 at n_with_close 196 (>= 100)

Data: fleet `~/syndicate-prod/data/nfl_source` copied read-only 2026-10-26T15:38:21Z from the Windows side via
`\wsl.localhost` (36 files, sha256 + bytes in `C:/tmp/nflbt/kalshi_pooled/PROVENANCE.txt`; the 10-13 quotes moved to
`quotes_prev_2026-10-13/`, its provenance to `PROVENANCE_prev_2026-10-13.txt`). Quotes: daily files 2026-09-30..10-29
plus `2026_wk4/5/6.jsonl`; 2,473,983 quotes loaded. Output `C:/tmp/nflbt/kalshi_pooled/read_2026-10-26/`. Script
unchanged, run at Idle priority. The task was scheduled for 2026-10-20 and ran 2026-10-26, so the copy also holds
week 7 through Sunday (MNF 10-26 not played: no close, ungraded) -- shown separately below and excluded in the
completed-weeks-only row; the verdict is the same either way.

| cohort | n | games | n with close | mean entry EV | mean fee-net CLV [game-clustered 95% CI] | share CLV>0 | slope CLV~EV | realized ROI [95% CI] (n graded) |
|---|---|---|---|---|---|---|---|---|
| bets (first fee-net +EV ask per line+side) | 240 | 56 | 196 | +1.74% | -1.96% [-2.80, -1.14] | 0.45 | +1.25 | +2.2% [-9.9, +14.9] (193) |
| control (first sighting) | 1471 | 62 | 1166 | -6.77% | -6.52% [-7.08, -5.98] | 0.14 | +0.90 | -7.5% [-9.4, -5.7] (1210) |
| bets, entry consensus fresh | 79 | 36 | 65 | +1.86% | -1.54% [-3.15, -0.01] | 0.51 | +1.53 | -7.1% [-36.1, +18.6] (62) |
| bets, entry consensus older | 161 | 54 | 131 | +1.69% | -2.16% [-3.43, -1.08] | 0.43 | +0.96 | +6.7% [-10.9, +25.7] (131) |

Per week (bets; week by kickoff UTC date, boundaries 10-08 / 10-15 / 10-22 / 10-29; gross = fair close vs ask before
fee; CIs here are analytic game-clustered from bets.jsonl, not the script's bootstrap):

| week | n | games | n with close | fee-net CLV [95% CI] | gross-of-fee CLV [95% CI] | realized ROI [95% CI] (n graded) |
|---|---|---|---|---|---|---|
| wk4 | 57 | 15 | 44 | -1.87% [-3.17, -0.56] | +1.97% [+0.58, +3.37] | -1.1% [-31.7, +29.5] (43) |
| wk5 | 56 | 14 | 46 | -1.95% [-4.10, +0.20] | +1.75% [-0.55, +4.05] | -4.5% [-27.9, +18.8] (48) |
| wk6 | 70 | 14 | 60 | -2.43% [-4.29, -0.57] | +1.29% [-0.75, +3.33] | +3.1% [-28.8, +35.0] (56) |
| wk7 (through Sunday; MNF unplayed) | 57 | 13 | 46 | -1.42% [-3.19, +0.35] | +2.19% [+0.24, +4.14] | +11.4% [-8.6, +31.4] (46) |
| wk4-6, completed weeks only | 183 | 43 | 150 | -2.12% [-3.15, -1.09] | +1.63% [+0.51, +2.75] | -0.6% [-17.1, +15.9] (147) |
| pooled | 240 | 56 | 196 | -1.96% (script CI above) | +1.76% [+0.81, +2.72] | +2.2% (script CI above) |

Markets: Receptions 214 of 240 bets, Passing TDs 26. By entry-EV band: 0-2% bets -3.10% [-4.14, -2.09] (n_with_close
137); 2-5% bets -0.16% [-1.46, +1.06] (52).

**Verdict against the Falsification line: fee-net CLV CI wholly <= 0 (-1.96% [-2.80, -1.14], n_with_close 196; wk4-6
alone -2.12% [-3.15, -1.09], n 150) -> the hypothesis is SUPPORTED: Kalshi NFL prop asks that look +EV after the fee
do not hold that value to the close.** Precisely what it says: the asks beat the closing consensus BEFORE the fee
(+1.76% gross, CI > 0) and lose to it AFTER the fee, which is charged at the full Kalshi taker rate
(fee_upper_bound_share 1.0, NFL prop series unmapped) -- so fee-net CLV is a lower bound, and the 2-5% EV band alone
spans 0. Realized ROI spans 0 at n 193 and carries no weight. Not tested here: maker (resting) entry, a mapped
(lower) fee, any market other than Receptions / Passing TDs.
