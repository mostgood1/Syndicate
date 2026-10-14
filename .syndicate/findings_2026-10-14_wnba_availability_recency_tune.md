# FINDINGS — tuning the WNBA recency availability rule (lane `wnba-availability-recency-tune`)

User decision 2026-10-14 ("tune the rule"), after P5 (`wnba-native-live-cutover`) measured that at 5:00 Q4 of the 2026
season 217 of the 261 on-court players absent from the pregame engine frame had sat out their team's previous game
(the K=1 rule's trigger; median 19 min that night). Then, offered the offline result below: "Engine re-run, 2
candidates".

## 1. The rule today (`syndicate/features/shared/wnba_sim_availability.py`)

K=1: a player who did not appear (MIN > 0) in the team's last game is dropped from that team's SmartSim pool.
Enabled 2026-10-05 (file switch, user decision) from lane `wnba-sim-availability`
(`findings_2026-10-03_wnba_sim_availability.md`). That lane selected K=1 on **net non-player sim minutes removed per
team-game** -- the criterion reused here unchanged, so the bar does not move.

## 2. Offline candidates (`scripts/fit_wnba_sim_availability.py`, pre-rule as-of archive `~/wnba_bt/archive`, 2026-10-14)

Selection on train (regular season before 2026-08-01, 414 team-games); confirmation on test (Aug-Sep, 230) and
playoffs (18). "Regular" is as-of from the team's earlier box scores only.

| rule | train net removed | test net removed | test real players wrongly dropped | of whom >= 20 actual min | playoffs net |
|---|---|---|---|---|---|
| **k1 (today)** | **27.02** | **32.87** | 79 | 40 | 26.18 |
| k2 | 25.17 | 31.13 | 40 | 22 | 27.61 |
| k3 | 23.11 | 28.55 | 27 | 15 | 30.15 |
| k1, regular (mean MIN >= 20 over last 5 apps) needs k2 = `regular_k2_min20` | 26.85 | 31.57 | 58 | 24 | 27.77 |
| k1, regular needs k3 (min20) | 26.55 | 29.38 | 52 | 19 | 29.40 |
| k1, exempt if >= 3 of last 5 team games = `exempt_apps3of5` | 25.70 | 29.70 | 35 | 17 | 31.01 |
| k1, exempt if >= 2 of last 5 | 25.00 | 27.76 | 24 | 11 | 29.62 |
| k1, exempt if mean MIN >= 10 / 15 / 20 | 17.02 / 18.30 / 22.79 | 12.49 / 13.32 / 19.89 | 4 / 23 / 35 | 1 / 3 / 6 | 12.45 / 13.32 / 21.17 |

**Pre-registered verdict on this criterion: NO candidate beats k1** (train or test). The candidates do what the
user asked -- they cut the big-minute wrong drops (test >= 20 min: 40 -> 17-24) -- at 1.3-5.1 net minutes per
team-game handed back to non-players. Net sim-minutes is a PROXY, so the held-out engine re-run decides (§3).

## 3. Engine re-run (running)

Three arms on today's code (`1c353e05`, frozen at `~/wnba_avail_tune/code_1c353e05`), production configuration
(the four WNBA file switches and P2 rotation inputs copied in as of D), 500 sims, Aug-1 .. playoffs, 2 workers each,
nice 19, PYTHONHASHSEED=0: `k`, `regular_k2_min20` (smallest net loss), `exempt_apps3of5` (fewest >= 20-min wrong
drops among the k1-based rules). Runner: `scripts/run_wnba_availability_arms.py`. Launched 2026-10-14 20:13Z.

Reachability through the real path (smoke, 2026-08-12, 20 sims): `SIM_AVAILABILITY applied ... rule=k added=191`,
`rule=regular_k2_min20 added=187`, `rule=exempt_apps3of5 added=181`.

Not equivalent to production, stated: no injury feed in the scratch (production's starts 2026-10-01, so only the last
held-out date could differ); the lineup-effect tables are absent (season-fit); the inputs are today's code as-of, not
what production ran per date.

**PRE-REGISTERED DECISION (written before any engine result):** a variant is recommended over `k` only if, on the
held-out regular season (paired, game-clustered CI via `fit_wnba_sim_availability.py --compare`):
1. played-player minutes MAE is not worse (CI upper bound <= 0 is "better"; a CI straddling 0 is "not worse"), AND
2. no priced market's book-line Brier is worse with a CI excluding 0, AND
3. at least one of {minutes MAE, points/PRA book-line Brier} is better with a CI excluding 0.
If both variants qualify, the one with the larger minutes-MAE gain. Otherwise `k` stays. Playoffs (9 games) are
reported, not decisive. Enabling in production is a separate user decision either way.

## 4. RESULT (2026-10-14 22:1xZ): `k` STAYS -- no variant meets the pre-registered rule

Arms finished 22:14Z: 42 held-out dates x 124 game sims per arm, identical sets, 0 errors (3 of the 45 archive dates
lack the phase-1 game predictions and were skipped by every arm). Scored with `fit_wnba_sim_availability.py --compare
--n-boot 2000` (k = baseline) and `scripts/evaluate_wnba_availability_arms.py` (the §3 rule, applied mechanically).

Held-out REGULAR season (115 games), variant - k (negative = variant better), 95% game-clustered CI:

| | `regular_k2_min20` | `exempt_apps3of5` |
|---|---|---|
| played-player minutes MAE | -0.014 [-0.089, +0.058] (n 2,038) | +0.031 [-0.081, +0.137] (n 2,016) |
| minutes bias (k -> variant) | +0.152 -> -0.425 | +0.189 -> -0.941 |
| points book-line Brier | +0.0002 [-0.0024, +0.0030] | +0.0027 [-0.0015, +0.0072] |
| PRA book-line Brier | -0.0004 [-0.0042, +0.0038] | +0.0049 [-0.0006, +0.0104] |
| any market Brier worse (CI > 0) | none | none |
| player-games projected (k 2,266) | 2,306 (+40 net; k-projected games it lost: 15 played, 4 did not) | 2,412 (+146 net; lost: 37 played, 18 did not) |
| clause 1 / 2 / 3 | yes / yes / **no** | yes / yes / **no** |

**Neither variant shows a measurable gain** (clause 3): both are statistically indistinguishable from `k` on pregame
minutes and on every priced market. `exempt_apps3of5` widens coverage most but spreads minutes thinner (bias -0.94).
Playoffs (9 games) point the same way and are not decisive. **Pre-registered outcome: `k` stays.** Nothing in
production changed: the rule selector's default IS `k`, and no switch was set.

NOT measured by the pre-registered criteria: the LIVE lens. More rotation players in the pregame frame means more
on-court fives the native re-sim can resume (P5: 30% of 5:00-Q4 sides sampled under `k`). That benefit is real but
unquantified here; it can be measured inside P5's backtest (re-record inputs under a variant, compare real-five rate
and the paired live metrics) once P3's re-fits land.
