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
