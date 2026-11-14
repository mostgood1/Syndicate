# NHL live puck line re-graded on the fixed engine (todo #773, lane nhl-live-puckline-regrade)

2026-11-14, run 20:55-21:24Z (2:55-3:24 PM CST). Session 87074b1f. READ-ONLY on production; nothing priced or published. User: "Yes, re-grade it". Pass/fail pre-registered on main before any replay (`23a6abc89`), and a caveat added before any outcome was read (`5af52c6e8`).

**Verdict: PASS on all four pre-registered criteria, as an UPPER BOUND, on both the 11-11 population and the full sample.** Today's engine closes the failure that made 11-11 say DO NOT PRICE. The 11-11 engine, run on the same inputs and seeds, reproduces that failure exactly. Per the pre-registration, this pass licenses a same-instant MARKET grade from the v6 recorder. It does NOT license pricing: the season rate files are leaky, so a replay pass cannot be decisive.

## What was run

- **Harness:** `scripts/backtest_nhl_live_puckline.py` (blob `35dc8724d366`, unchanged since 11-13). Same rules as 11-11: the worst powered bucket against `#499`'s 0.150, game-bootstrapped intervals, and the skill-free Skellam baseline.
- **Code:** the fleet checkout. Its NHL blobs are `41e94507a`'s: `live_resim.py` `d1af1f2cc03d`, `engine.py` `e254762415b9`. It ran under live-odds-worker's own environ, at nice 19, with PYTHONHASHSEED=0, production's 200 sims, and seeds fixed per game x cutoff.
- **Two arms**, with switches checked by resolving them under each arm's environ:
  - **on** = production today: `--endgame production`, so end-game 0.38 / 90 s, overtime as sudden death, rest of period as regulation, scoring keep 0.85 / 240.
  - **off** = the 11-11 engine: all four switches legacy, `--endgame off`.
- **Sample:** 303 completed regular-season games on 44 dates (10-01..11-13), 8 cutoffs (P1 20:00 .. P3 01:30), so 2,424 states per arm. 0 refused, 0 dropped, 0 without features.
  - W1 = the 11-11 population: 284 games, 41 dates (10-01..11-10).
  - W3 = the fresh games: 19 games, 3 dates (11-11..11-13).
- **PROVENANCE: LEAKY**, as on 11-11. The season rate files contain every graded game. They were also REWRITTEN MID-RUN, at 21:12:35Z.
  - So 11-07..11-13 were re-run in both arms on that one version, and the grade splices those rows in.
  - Against the first run, 5 of those 7 dates were byte-identical. 11-07 moved in 14 / 13 of 96 states and 11-12 in 8 / 7 of 88 (on / off), by at most 0.06 home win. That is consistent with the rewrite adding 11-13's two games, which changes four teams' rates.
  - Dates up to 11-06 finished before the rewrite in both arms.
- **Reproduction check:** on W1 the off arm reproduces 11-11's numbers. At P3 05:00 with a one-goal lead, P(leader by 2+) is 0.181 vs 0.433 (11-11: 0.180 vs 0.433). At P3 10:00 it is 0.261 vs 0.495 (11-11: 0.260 vs 0.495). The late width ratios are 1.105 / 1.167 (11-11: 1.105 / 1.167). So today's inputs grade the old engine exactly as 11-11 did, and the difference below is the engine's.

## The pre-registered test

| criterion | W1 on | W1 off | W2 on | W2 off |
|---|---|---|---|---|
| (1) +-1.5 worst powered bucket \|gap\| <= 0.150 | 0.7-0.8 n=301 +0.057 **PASS** | 0.1-0.2 n=438 +0.090 PASS | 0.1-0.2 n=358 -0.050 **PASS** | 0.1-0.2 n=469 +0.076 PASS |
| (2) one-goal lead, P(leader by 2+), \|gap\| <= 0.10 | P3 10:00 0.409 vs 0.495 (+0.085, n=93); P3 05:00 0.404 vs 0.433 (+0.030, n=90): **PASS** | +0.233 / +0.252: **FAIL** | +0.091 (n=98) / +0.034 (n=96): **PASS** | +0.238 / +0.257: **FAIL** |
| (3) Brier model - baseline, 95% upper < 0 | 0.1114 vs 0.1224, [-0.0164, -0.0053] **PASS** | 0.1180, [-0.0076, -0.0014] PASS | 0.1108 vs 0.1219, [-0.0164, -0.0058] **PASS** | 0.1175, [-0.0071, -0.0017] PASS |
| (4) late width ratio in [0.90, 1.10] | 1.048 / 1.084 **PASS** | 1.105 / 1.167 FAIL | 1.045 / 1.093 **PASS** | 1.102 / 1.173 FAIL |
| **all four** | **PASS (upper bound)** | FAIL | **PASS (upper bound)** | FAIL |

- **Worst-bucket intervals** (game bootstrap of \|gap\|): on W1 [0.043, 0.133], on W2 [0.047, 0.137]. Both sit wholly under the bar.
- **Criterion (2) is IN-SAMPLE for p.** The end-game 0.38 / 90 s was fit on W1's rows by lane nhl-live-endgame-calibration. Its out-of-sample evidence is that lane's walk-forward: 185 games on 27 dates, with those states within +-0.035. P3 10:00 is the largest gap left here: +0.085..+0.091, 1.6-1.8 binomial sd.
- **Paired on - off**, same states and seeds, bootstrapped over games, on W2:
  - +-1.5 Brier **-0.0067 [-0.0114, -0.0020]**;
  - moneyline Brier -0.00003 [-0.00095, +0.00085], unchanged.
  - W1 is the same: -0.0066 [-0.0115, -0.0016] and +0.0001.

## By state, on W2, oriented to the leader (model vs observed)

- **Late one-goal leads are fixed.** P(leader by 2+): P3 05:00 0.404 vs 0.438, P3 03:00 0.392 vs 0.443, P3 01:30 0.391 vs 0.400. The old engine had 0.181 / 0.142 / 0.091 against the same outcomes.
- **Early leads are fixed too.** The old engine under-predicted the leader's extension by +0.06..+0.13 from P2 20:00 to P3 20:00. Today it reads -0.007..+0.045 at one- and two-goal leads.
- **What is left:**
  - **Mid-game trailer comeback** is still over-predicted. At P2 10:00 the trailer ties or wins: model 0.317 vs 0.256 with a one-goal lead (n=121), and 0.174 vs 0.092 with a two-goal lead (n=65). This is 11-11's "score effects pull too hard toward a tie", and these fixes do not touch it.
  - **Late two-goal leads are over-held.** P(leader by 2+) at P3 01:30 is 0.910 vs 0.818 (n=44), and 0.857 vs 0.821 at P3 03:00.
  - **Very late width:** the P3 03:00 width ratio is 1.135 (1.212 off). It is outside the pre-registered cutoffs.
- **Alt +-2.5 (secondary, not gating):**
  - It passes the bar only as an upper bound: worst 0.6-0.7, n=82, -0.133, with a worst-gap interval of [0.112, 0.272] that straddles 0.15.
  - The model does not beat the skill-free baseline: [-0.0030, +0.0008].
  - It is over-confident in the 0.7-0.9 buckets (-0.10..-0.13). Pricing the alt line would need its own work.
- **W3, the 19 fresh games, is underpowered** and does not gate. The on arm scores Brier 0.1027 vs the baseline's 0.0998, with an interval of [-0.025, +0.027]. The lead cells have n of 2-7.

## What this means

- **The 11-11 DO NOT PRICE reason is gone.** Its decisive failure was a one-goal lead late in P3, and on today's engine those states sit inside +-0.10 on the replay (in-sample for p) and inside +-0.035 out of sample (the end-game lane's walk-forward).
- **This is still not a licence to price.** A replay on leaky rates can only pass as an upper bound. The pre-registered next gate is production's own displayed number against the market's de-vig at the same instant, from the v6 recorder (`live_gameline_ledger.py`: `display_prob` + `market_fair_prob_over` on every display-only puck-line row).
- **Recorder population, read 21:2xZ:** spreads rows carrying both numbers number 249 (6 games) on 11-11, 631 (10) on 11-12, 131 (2) on 11-13, and 99 (2) on 11-14 so far. Only rows after the 11-14 19:42:50Z load come from the fully fixed engine. At about 8 games a night, about 100 games on today's engine is roughly 11-26.
- **Pricing stays the user's decision.** Nothing here changes it: `displayMarginDist` -> `marginDist` stays closed.

## Reproduce

```
wsl -- bash /mnt/c/tmp/nhlrec/run_regrade.sh on      # and: off
wsl -- bash /mnt/c/tmp/nhlrec/run_regrade_late.sh on 2026-11-07 2026-11-13 _late   # and: off
cd ~/Syndicate && nice -n 19 ~/.venvs/syndicate/bin/python /mnt/c/tmp/nhlrec/regrade/compare.py /mnt/c/tmp/nhlrec/regrade
```

Outputs: `C:\tmp\nhlrec\regrade\{on,off,on_late,off_late}\` (`rows.jsonl`, `report.txt`), `C:\tmp\nhlrec\regrade\compare.txt`.
