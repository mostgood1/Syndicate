# Findings 2026-10-06 — NFL Kalshi forward CLV, week 4 (lane `nfl-kalshi-forward-clv`)

Unattended scheduled run (`nfl-kalshi-forward-clv-week4`). Measurement only: no deploy, no board or scoring change.

## Data (production = local WSL fleet, copied read-only to scratch 2026-10-06 ~16:45Z)

Copied from `~/syndicate-prod/data/nfl_source/` with sha256:

| family | file(s) | sha256 (first 16) | latest coverage |
|---|---|---|---|
| book_quotes | 2026-09-30..10-04 `.jsonl.gz`, 10-05/06/08/11/12 `.jsonl`, `2026_wk4.jsonl`, `2026_wk5.jsonl` (188 MB, 726,832 NFL prop quotes loaded) | wk4 `09f684234939f0a6`, wk5 `b127cdfd3ace8e22` (full list in the run transcript) | Kalshi asks for kickoffs through 2026-10-11 (week 5 pregame) |
| pbp | `tracking/nflverse/pbp/pbp_2026.csv` (fleet mtime 10-05 22:27 local) | `0c2e4494acf5278125e1` | weeks 1-4, **15 of 16 week-4 games**; max game_date 2026-10-04. **MNF 2026_04_ATL_NO (10-05) absent** |
| schedules_games | `tracking/nflverse/schedules_games.csv` (fleet mtime 10-05 22:30) | `b3d8288ab6dc8a80` | 2026 week 4: 15 of 16 with a result; ATL@NO unscored |
| schedule_2026 | `schedule_2026.csv` (fleet mtime 10-06 11:30) | `c2d94963cd49ab1f` | full season |

So: CLV is measurable for every week-4 game (closes exist, incl. MNF); realized ROI is gradable for 15 of 16 week-4 games (not MNF).

## Run

`py -3 scripts/measure_nfl_kalshi_forward_clv.py --quotes-dir C:\tmp\nflbt\kalshi_quotes --root C:\tmp\nflbt\root\nfl_source --out C:\tmp\nflbt\kalshi_clv_week4 --grade` (worktree on origin/main d1aaad1b). Output: `C:\tmp\nflbt\kalshi_clv_week4\nfl_kalshi_forward_clv.json` + `bets.jsonl` (scratch).

Drops: 5,375 Kalshi quotes considered; no entry consensus (< 3 two-sided books in 6 h) 1,737; not pregame 1,956; illiquid pair (sum > 1.15) 47; illiquid price (> 0.95 / < 0.05) 24. Grading: 5 unresolved player, 5 no pbp line, 5 game not completed (MNF + week 5).

## Numbers

| cohort | n | games | n_with_close | mean entry EV (fee-net) | mean fee-net CLV [game-clustered 95% CI] | share CLV > 0 | slope CLV~EV | n_graded | realized ROI [95% CI] |
|---|---|---|---|---|---|---|---|---|---|
| **bets (first +EV ask)** | 58 | 16 | 44 | +1.47% | **-1.87% [-3.22, -0.67]** | 19/44 = 43% | +0.80 | 43 | +3.2% [-24.4, +30.2] |
| control (first sighting) | 380 | 18 | 263 | -5.57% | -5.29% [-5.74, -4.86] | 12% | +0.42 | 292 | -6.0% [-8.7, -3.7] |
| bets, entry consensus <= 90 min old | 22 | 9 | 18 | +1.52% | -0.30% [-3.93, +2.44] | 44% | — | 16 | +2.6% [-51, +47] |
| bets, entry consensus older | 36 | 15 | 26 | +1.44% | -2.95% [-6.54, -0.17] | 42% | — | 27 | +3.6% [-34, +43] |

Composition: 52 of 58 bets are Receptions (Passing TDs 6); 49 of 58 are OVERS — a one-sided pile, so this is mostly one market and one side. 45 of 58 bets kick off 2026-10-04 (Sunday); 1 bet is week 5 (no close yet). Median lead to kickoff ~44 h.

Decomposition (44 bets with a close): fee charged mean 1.70 pp on mean price 0.442 (NFL prop series are unmapped in `venue_fees`, so the FULL taker rate is charged — an upper bound). **Gross-of-fee CLV is +1.97% (29/44 = 66% positive); fee-net it is -1.87%.** Between entry and close the consensus fair moved AGAINST the bet by a mean -1.65 pp: the +EV entries partly reverted rather than being early.

## Verdict

Pre-registered (2026-10-03): positive-entry-EV bets' mean fee-net CLV +0.3 to +1.5 pp; slope > 0; falsified if the CLV CI is wholly <= 0 with n >= 100.

- **Mean fee-net CLV: prediction FAILED at this n.** -1.87% with CI [-3.22, -0.67]: the CI excludes the whole predicted band and sits wholly below 0. The formal falsification bar (n >= 100) is **not reached** (n_with_close = 44, 16 games), so the timing hypothesis is not formally falsified — but nothing here supports it.
- **Slope > 0: held** (+0.80; +0.42 in the control), point estimate only, no CI computed. Selecting on entry EV does buy ~+3.4 pp of CLV over the control (-1.87 vs -5.29); it does not buy enough to clear Kalshi's fee.
- Fresh vs older consensus: fresher entry consensus is less bad (-0.30, CI spans 0, n=18) than older (-2.95, CI wholly < 0, n=26) — consistent with stale consensus manufacturing part of the apparent entry edge. Underpowered; descriptive only.
- **Realized ROI: not informative** — +3.2% with CI [-24, +30] on 43 graded bets (19 wins). No claim.
- Biggest live caveat: the fee is an upper bound and decides the sign (gross +1.97% vs net -1.87%). If NFL prop series actually carry a lower fee, the answer could change; the true fee schedule is the cheapest thing to settle.

## Recommendation

No board, scoring or Kalshi-routing change on this reading. Keep accumulating: re-run the same script after each week (weeks 4+ pooled, game-clustered) until n_with_close >= 100 (~2-3 more weeks at this rate), and read the falsification then. Before that pooled reading, establish the real Kalshi fee for the NFL prop series (receptions / passing TDs) so the fee-net number is not an upper bound. Also add the MNF game to the realized grade once pbp_2026 carries it.
