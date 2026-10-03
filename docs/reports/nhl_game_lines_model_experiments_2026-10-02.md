# NHL game-line model: ranked accuracy plan — 2026-10-02 (lane `nhl-game-lines-model`)

**Framing (user decision, 2026-10-02 ~7:05 PM CT):** "every line is its own decision. we should have a model
that is accurate that then helps inform each decision." Nothing here proposes removing a market from the
board. This is the plan to make the model accurate, ranked by measured impact. Per-line decisions stay with
per-line scoring.

Diagnosis: `docs/reports/nhl_game_lines_backtest_2026-10-02.md`. Harnesses:
`scripts/nhl_game_lines_experiments.py` (variants) and `scripts/fetch_nhl_confirmed_goalies.py`
(confirmed starters). Raw tables are at the end of this file.

## How it was measured

- **Model.** Production `predict_game` lambdas from the as-of re-sim (`backtest_nhl_game_lines.py sim`,
  props lane roots `bt_after`, lineups on `4247a6ea`, which is identical for game lines: 0/1,288 differ).
  Each fix is layered multiplicatively on those lambdas, the same shape a production change would take.
- **Walk-forward fits.** Machinery parameters (regulation scale `s`, OT/SO home share `q`, tie mass `δ`,
  empty-net rate `e`) are fit **only on games strictly before each date**.
- **Frozen information parameters.** Goalie shrink and prior weight, and the rest multipliers, were tuned on
  games **before 2026-01-01 only** and then frozen.
- **Windows.**
  - Out-of-sample headline: **2026-01-01..04-16, n=681** (64 dates).
  - Full regular season: 11-01..04-16, n=1,132.
  - Playoffs: n=82, holdout, below n=100 so indicative only.
- **Two baselines.**
  - **B0:** the naive as-of team GF/GA average.
  - **B4:** the same GF/GA lambdas given the same machinery (V1..V4).

  Beating B0 means more accurate. Beating B4 means real *information* beyond team averages.
- **Common random numbers** across variants, and a date-clustered bootstrap (2,000 reps) for every CI.
- **Book leg (added 2026-10-03).** OddsAPI historical closing snapshots ~3 minutes before each start (874
  slots, 11 books typical, 26,220 credits, fleet key read with the user's direct approval). Per-book
  proportional de-vig, consensus over books quoting both sides at the modal line.

## The ranked plan

| # | defect (evidence) | fix | measured impact | where |
|---|---|---|---|---|
| **1** | **Totals line is the median of every captured point.** On production's own 2026-09-30..10-04 files, the priced `totals_line_used` ≠ the modal pregame book line on **24 of 31 games (77%)**, and **8 of 31** are off the half-goal grid. Examples: LAK@COL priced **9.0** when 8/11 books hung 6.5; PHI@NJD priced **5.0** when all 11 hung 5.5. The captures mix alternates and in-play quotes with no timestamp. | Take the **modal line among PREGAME quotes**: the per-book quote log has `captured_at`; keep `captured_at ≤ commence`, latest per book. De-vig over/under at that line only. | Every totals probability is then priced at a line a book actually hangs, instead of refused (6 rows on the 10-02 read) or priced at a phantom number. Deterministic. Largest single accuracy gain for the totals that reach a decision. | `hockeysim/features/market_lines.py::load_market_lines` (unclaimed) |
| **2** | **Regulation pace is a full-game rate.** `projection.py: league_baseline_goals_per_60 = 3.1269` comes from 6.2538 goals/game *including OT goals and SO credits*. The model over-projects regulation goals by **+0.358 [+0.217, +0.498]**. | Rescale to the as-of league **regulation** goal rate (V2: `s` fit walk-forward). | Ships with #3–#5; alone it under-shoots, because the tie goal is then missing. | `projection.py` profile constants (unclaimed) |
| **3** | **No OT/SO in `game_market_sim`.** Totals settle on regulation goals; ML splits regulation ties 50/50. Once settlement is made honest (V1), the true settled bias shows: **+0.272 [+0.131, +0.407]**. | Regulation tie → OT/SO: home wins with as-of `q`, and the settled total gets +1 (OT goal or SO credit). | **#2+#3+#4+#5 together (V4): settled total bias +0.272 → −0.016 [−0.159, +0.121]** (full window); OOS −0.075 [−0.229, +0.090]. OVER 6.5 mean p 0.498 (V1) → 0.449 vs frequency 0.463. | `game_market_sim.py` + `adapters.py` |
| **4** | **Too few regulation ties.** Model 0.160 vs actual **0.2465 [0.221, 0.272]**, in every arm. Independent per-period Poisson cannot produce hockey's tie mass (score effects). | Tie re-weighting, `δ` fit as-of (V3). Next: a per-game correlation term (Dixon-Coles-style ρ) instead of a uniform `δ`. V3 overshoots slightly: 0.272 vs 0.246 full window, 0.264 vs 0.235 OOS. | Tie Brier vs B0 **−0.0062 [−0.0112, −0.0012]** (full); OOS −0.0044 [−0.0108, +0.0017]. This is the precondition for a regulation 3-way price and for an honest ML tie split. | `game_market_sim.py` |
| **5** | **No empty-net goals.** One-goal margins are over-predicted relative to two-goal margins, and tie re-weighting alone drags puck-line covers down (home −1.5 mean p 0.284 → 0.250 OOS). | A one-goal regulation lead becomes two w.p. `e`, fit as-of (V4). The engine already has an `empty_net_p` knob, unused. | Puck-line calibration restored: home −1.5 mean p 0.288 vs frequency 0.317, away 0.257 vs 0.273 (OOS). The residual under-prediction of covers is the next refinement. Brier ties both baselines. | `game_market_sim.py` (`SimConfig.empty_net_p`) |
| **6** | **Playoff scoring is over-projected.** Settled total bias **+0.50 [+0.05, +0.91]** under every variant (n=82): regular-season rates in tighter playoff hockey. | An as-of playoff pace factor (prior playoff rounds; prior-season playoff/regular ratio for round 1). | Expected to remove a ~0.5-goal bias in playoff totals. Measurable next spring; n=82 now. | `projection.py` |
| **7** | **Wrong starting goalie.** Production's `hockeysim_toi` projection named the actual starter in only **1,254/2,264 team-games (55.4%)**. | **Daily Faceoff confirmed starters** (`fetch_nhl_confirmed_goalies.py`): public per-date pages, robots `Allow`, with the post time per starter. Pregame-provable (posted < puck drop), Confirmed and as-of-verifiable: **1,624/1,625 correct (99.9%)**, 72% coverage. Blended with an as-of rotation rule (63.4% alone): **87.0%**. | **Goalie identity is now right.** Goalie *quality* by save% (2024-25 prior, shrink tuned pre-January) carries **no detectable signal**: ML Brier is unchanged for confirmed starters and for the oracle actual starter (V5c, V5o). Over 6.5 V5c vs B0 −0.0046 [−0.0092, −0.0002], borderline. The feed matters for the SAVES prop and for any better goalie metric (#8). | feed: `ingestion/collect.py` (**claimed by lane `nhl-player-props-projection`**, coordinate); the fetcher is this lane's |
| **8** | **The moneyline has no information beyond team averages.** No tested change moves ML Brier: machinery, goalie save%, rest (B2B gf 0.960, n=144), and the oracle starter. **GSAx tested 2026-10-03**: production xG estimator fit on pre-2026-01-01 shots and frozen (111,896 shots; OOS xG 0.0701 vs goal rate 0.0711), as-of per goalie, k tuned pre-January (grid edge, 80 xG). ML OOS vs B4 −0.0000 [−0.0040, +0.0040] → **H6 falsified for ML**. ML is at book parity, so this is a hard ceiling for team-strength inputs. | **Prior-season GSAx prior tested 2026-10-03** (2024-25 play-by-play, 1,312 games, the same frozen xG model, (k, w) tuned pre-January = (160, 0.25)): ML OOS vs B4 −0.0002 [−0.0042, +0.0038], no better than in-season GSAx → **H7 falsified for ML**. Goalie quality in any form adds no ML information at this n. Next for ML: recency-weighted xG; score-adjusted xG. **GSAx helps TOTALS:** OOS OVER 6.5 vs B0 −0.0060 [−0.0110, −0.0012] (save% was no difference); OVER@close vs book +0.0028 (V4) → +0.0014 (V7, confirmed starter + GSAx) → +0.0007 (V7o, actual starter), all CIs including 0. With the prior, OVER@close vs book narrows further to +0.0012 (V8); OOS OVER 6.5 vs B0 −0.0062 [−0.0115, −0.0012]. **Ship GSAx + prior-season prior, heavily shrunk, with the confirmed-starter feed (#7) as a totals input.** | `projection.py` (goalie term) + feed (#7) |
| **9** | **Where the model stands against the book: MEASURED (2026-10-03).** | — | Full window n=1,131 vs the close: ML raw +0.0005 [−0.0030, +0.0039], ML anchored −0.0004 [−0.0026, +0.0018], PL at the book line +0.0010 [−0.0032, +0.0050], OVER at the close +0.0029 [−0.0007, +0.0064] → **book parity on every market**. The plain team average is WORSE than the book on totals (+0.0050 [+0.0012, +0.0085]), so the model's totals carry real information the average lacks. Fixes #2–#5 plus confirmed starters move OVER from +0.0029 to +0.0019, within noise. OOS (n=680) reads the same. | — |
| **10** | **No P1 or 3-way odds are captured.** Production fetches explicit `h2h,spreads,totals`. The historical probe (80 credits, 5 events) found `h2h_3_way` on 4/5 events (4–5 books each), while P1 markets appeared on opening night only. A 3-way backfill is ~14k credits: user decision owed. | Add the period and 3-way markets to the NHL fetch (per-event; cost to be estimated against the 5M/month cap first). | Lets P1 and 3-way lines be scored and decided per line. | `refresh_nhl_oddsapi.py` / `local_nhl_odds.py` |

### What ships together

#2–#5 are one change to the game-market sim: settlement, pace, tie mass and empty net. Shipped alone, each
moves the bias in a different direction (V1 +0.27, V2 −0.12, V3 −0.08, V4 −0.02), so they go together.
Under `model_engine_standard` §4.4 these are mechanisms added to a calibrated engine, and the absorbing rates
(`s`, `δ`, `e`, `q`) are re-fit as-of, which is what this harness already does. #1 is independent and can go
first. #7's feed needs the props lane's collector.

### Not claimed

- No market beats the book, and none loses to it: every model variant is at book parity (#9). The
  binding work is #8, information beyond what the book already prices.
- No change here moves the moneyline. The improvements are calibration (totals bias, tie rate, puck-line
  shape), not discrimination.
- The Daily Faceoff archive names undressed goalies on some past dates, which looks like after-the-fact
  overwrites. 460 team-games were therefore treated as unverifiable. Live use reads the page pregame and is
  not exposed to that.

## Raw tables (regenerated 2026-10-03 with GSAx V7/V7o and GSAx + prior V8/V8o)

# NHL game-line model experiments (generated)

goalie shrink k (tuned before 2026-01-01): (10000.0, 0.5); rest multipliers: {'gf': 0.9596973193680101, 'ga': 0.9967268773300196, 'n': 144}
goalie join misses: `{'V8': {}, 'V8o': {'gsax_unmatched_oracle': 138}, 'V7': {}, 'V7o': {'gsax_unmatched_oracle': 138}, 'V5': {'goalie_unmatched_proj': 29}, 'V5r': {}, 'V5c': {}, 'V6': {}, 'V5o': {'goalie_unmatched_oracle': 138}}`
machinery fits (as-of samples): `{'2025-11-15': {'q_ot': 0.45, 's': 0.927409623209949, 'delta': 1.1058363430962297, 'e': 0.1986300194574574, 'n': 282, 'tie': 0.28368794326241137, 'reg': 5.99290780141844}, '2026-01-01': {'q_ot': 0.4879518072289157, 's': 0.9305409417898483, 'delta': 0.8758954422053264, 'e': 0.24874377006900095, 'n': 631, 'tie': 0.2630744849445325, 'reg': 5.884310618066561}, '2026-03-01': {'q_ot': 0.47717842323651455, 's': 0.9433408514502407, 'delta': 0.798595303051608, 'e': 0.27615074667009987, 'n': 945, 'tie': 0.25502645502645505, 'reg': 5.976719576719577}}`

## EVAL 2026-01-01..04-16 (out of sample) (n=681)

```
ML home (freq 0.527; B0 Brier 0.2433 meanP 0.518; B4 0.2435 meanP 0.511)
   V0   Brier 0.2426 meanP 0.520 | vs B0 -0.0007 [-0.0058,+0.0043] NO DIFFERENCE  | vs B4 -0.0009 [-0.0055,+0.0036] NO DIFFERENCE
   V1   Brier 0.2427 meanP 0.517 | vs B0 -0.0006 [-0.0058,+0.0044] NO DIFFERENCE  | vs B4 -0.0008 [-0.0054,+0.0035] NO DIFFERENCE
   V2   Brier 0.2428 meanP 0.517 | vs B0 -0.0005 [-0.0057,+0.0045] NO DIFFERENCE  | vs B4 -0.0008 [-0.0054,+0.0036] NO DIFFERENCE
   V3   Brier 0.2433 meanP 0.512 | vs B0 -0.0000 [-0.0053,+0.0052] NO DIFFERENCE  | vs B4 -0.0003 [-0.0048,+0.0041] NO DIFFERENCE
   V4   Brier 0.2433 meanP 0.512 | vs B0 -0.0000 [-0.0053,+0.0052] NO DIFFERENCE  | vs B4 -0.0003 [-0.0048,+0.0041] NO DIFFERENCE
   V5   Brier 0.2435 meanP 0.512 | vs B0 +0.0002 [-0.0050,+0.0052] NO DIFFERENCE  | vs B4 -0.0001 [-0.0045,+0.0042] NO DIFFERENCE
   V5r  Brier 0.2434 meanP 0.513 | vs B0 +0.0001 [-0.0049,+0.0051] NO DIFFERENCE  | vs B4 -0.0001 [-0.0044,+0.0041] NO DIFFERENCE
   V5c  Brier 0.2433 meanP 0.513 | vs B0 -0.0000 [-0.0051,+0.0050] NO DIFFERENCE  | vs B4 -0.0003 [-0.0047,+0.0040] NO DIFFERENCE
   V6   Brier 0.2432 meanP 0.514 | vs B0 -0.0001 [-0.0052,+0.0051] NO DIFFERENCE  | vs B4 -0.0003 [-0.0048,+0.0042] NO DIFFERENCE
   V5o  Brier 0.2433 meanP 0.513 | vs B0 -0.0000 [-0.0052,+0.0051] NO DIFFERENCE  | vs B4 -0.0003 [-0.0048,+0.0041] NO DIFFERENCE
   V7   Brier 0.2435 meanP 0.514 | vs B0 +0.0002 [-0.0043,+0.0049] NO DIFFERENCE  | vs B4 -0.0000 [-0.0040,+0.0040] NO DIFFERENCE
   V7o  Brier 0.2434 meanP 0.514 | vs B0 +0.0001 [-0.0046,+0.0050] NO DIFFERENCE  | vs B4 -0.0001 [-0.0042,+0.0040] NO DIFFERENCE
   V8   Brier 0.2434 meanP 0.514 | vs B0 +0.0001 [-0.0047,+0.0048] NO DIFFERENCE  | vs B4 -0.0002 [-0.0042,+0.0038] NO DIFFERENCE
   V8o  Brier 0.2432 meanP 0.514 | vs B0 -0.0001 [-0.0049,+0.0047] NO DIFFERENCE  | vs B4 -0.0004 [-0.0045,+0.0038] NO DIFFERENCE
REG tie (freq 0.235; B0 Brier 0.1847 meanP 0.161; B4 0.1795 meanP 0.259)
   V0   Brier 0.1853 meanP 0.159 | vs B0 +0.0005 [-0.0001,+0.0011] NO DIFFERENCE  | vs B4 +0.0058 [-0.0000,+0.0120] NO DIFFERENCE
   V1   Brier 0.1853 meanP 0.159 | vs B0 +0.0005 [-0.0001,+0.0011] NO DIFFERENCE  | vs B4 +0.0058 [-0.0000,+0.0120] NO DIFFERENCE
   V2   Brier 0.1845 meanP 0.164 | vs B0 -0.0002 [-0.0009,+0.0004] NO DIFFERENCE  | vs B4 +0.0050 [-0.0005,+0.0110] NO DIFFERENCE
   V3   Brier 0.1804 meanP 0.264 | vs B0 -0.0044 [-0.0108,+0.0017] NO DIFFERENCE  | vs B4 +0.0009 [+0.0000,+0.0017] MODEL WORSE
   V4   Brier 0.1804 meanP 0.264 | vs B0 -0.0044 [-0.0108,+0.0017] NO DIFFERENCE  | vs B4 +0.0009 [+0.0000,+0.0017] MODEL WORSE
   V5   Brier 0.1804 meanP 0.265 | vs B0 -0.0043 [-0.0107,+0.0019] NO DIFFERENCE  | vs B4 +0.0009 [+0.0001,+0.0017] MODEL WORSE
   V5r  Brier 0.1805 meanP 0.265 | vs B0 -0.0043 [-0.0106,+0.0019] NO DIFFERENCE  | vs B4 +0.0010 [+0.0001,+0.0018] MODEL WORSE
   V5c  Brier 0.1807 meanP 0.265 | vs B0 -0.0040 [-0.0104,+0.0021] NO DIFFERENCE  | vs B4 +0.0012 [+0.0003,+0.0021] MODEL WORSE
   V6   Brier 0.1806 meanP 0.266 | vs B0 -0.0042 [-0.0107,+0.0020] NO DIFFERENCE  | vs B4 +0.0011 [+0.0001,+0.0020] MODEL WORSE
   V5o  Brier 0.1807 meanP 0.265 | vs B0 -0.0041 [-0.0106,+0.0021] NO DIFFERENCE  | vs B4 +0.0012 [+0.0003,+0.0020] MODEL WORSE
   V7   Brier 0.1804 meanP 0.265 | vs B0 -0.0043 [-0.0110,+0.0020] NO DIFFERENCE  | vs B4 +0.0009 [-0.0000,+0.0018] NO DIFFERENCE
   V7o  Brier 0.1803 meanP 0.265 | vs B0 -0.0045 [-0.0111,+0.0019] NO DIFFERENCE  | vs B4 +0.0008 [-0.0001,+0.0016] NO DIFFERENCE
   V8   Brier 0.1807 meanP 0.265 | vs B0 -0.0041 [-0.0107,+0.0021] NO DIFFERENCE  | vs B4 +0.0012 [+0.0003,+0.0020] MODEL WORSE
   V8o  Brier 0.1805 meanP 0.264 | vs B0 -0.0042 [-0.0108,+0.0020] NO DIFFERENCE  | vs B4 +0.0010 [+0.0002,+0.0018] MODEL WORSE
REG home (freq 0.411; B0 Brier 0.2366 meanP 0.437; B4 0.2364 meanP 0.386)
   V0   Brier 0.2383 meanP 0.441 | vs B0 +0.0017 [-0.0031,+0.0062] NO DIFFERENCE  | vs B4 +0.0018 [-0.0039,+0.0073] NO DIFFERENCE
   V1   Brier 0.2383 meanP 0.441 | vs B0 +0.0017 [-0.0031,+0.0062] NO DIFFERENCE  | vs B4 +0.0018 [-0.0039,+0.0073] NO DIFFERENCE
   V2   Brier 0.2380 meanP 0.438 | vs B0 +0.0014 [-0.0032,+0.0059] NO DIFFERENCE  | vs B4 +0.0016 [-0.0039,+0.0068] NO DIFFERENCE
   V3   Brier 0.2382 meanP 0.386 | vs B0 +0.0016 [-0.0055,+0.0090] NO DIFFERENCE  | vs B4 +0.0018 [-0.0024,+0.0059] NO DIFFERENCE
   V4   Brier 0.2382 meanP 0.386 | vs B0 +0.0016 [-0.0055,+0.0090] NO DIFFERENCE  | vs B4 +0.0018 [-0.0024,+0.0059] NO DIFFERENCE
   V5   Brier 0.2382 meanP 0.385 | vs B0 +0.0016 [-0.0053,+0.0090] NO DIFFERENCE  | vs B4 +0.0018 [-0.0022,+0.0057] NO DIFFERENCE
   V5r  Brier 0.2383 meanP 0.385 | vs B0 +0.0017 [-0.0053,+0.0092] NO DIFFERENCE  | vs B4 +0.0019 [-0.0022,+0.0058] NO DIFFERENCE
   V5c  Brier 0.2385 meanP 0.385 | vs B0 +0.0019 [-0.0050,+0.0093] NO DIFFERENCE  | vs B4 +0.0021 [-0.0020,+0.0060] NO DIFFERENCE
   V6   Brier 0.2385 meanP 0.386 | vs B0 +0.0019 [-0.0050,+0.0094] NO DIFFERENCE  | vs B4 +0.0021 [-0.0022,+0.0061] NO DIFFERENCE
   V5o  Brier 0.2385 meanP 0.385 | vs B0 +0.0019 [-0.0050,+0.0092] NO DIFFERENCE  | vs B4 +0.0021 [-0.0020,+0.0060] NO DIFFERENCE
   V7   Brier 0.2391 meanP 0.387 | vs B0 +0.0025 [-0.0039,+0.0094] NO DIFFERENCE  | vs B4 +0.0026 [-0.0009,+0.0062] NO DIFFERENCE
   V7o  Brier 0.2392 meanP 0.387 | vs B0 +0.0026 [-0.0038,+0.0096] NO DIFFERENCE  | vs B4 +0.0028 [-0.0007,+0.0064] NO DIFFERENCE
   V8   Brier 0.2387 meanP 0.387 | vs B0 +0.0022 [-0.0043,+0.0092] NO DIFFERENCE  | vs B4 +0.0023 [-0.0012,+0.0059] NO DIFFERENCE
   V8o  Brier 0.2388 meanP 0.387 | vs B0 +0.0023 [-0.0043,+0.0093] NO DIFFERENCE  | vs B4 +0.0024 [-0.0011,+0.0060] NO DIFFERENCE
PL home -1.5 (freq 0.317; B0 Brier 0.2100 meanP 0.287; B4 0.2101 meanP 0.291)
   V0   Brier 0.2114 meanP 0.291 | vs B0 +0.0014 [-0.0026,+0.0055] NO DIFFERENCE  | vs B4 +0.0013 [-0.0024,+0.0050] NO DIFFERENCE
   V1   Brier 0.2114 meanP 0.291 | vs B0 +0.0014 [-0.0026,+0.0055] NO DIFFERENCE  | vs B4 +0.0013 [-0.0024,+0.0050] NO DIFFERENCE
   V2   Brier 0.2119 meanP 0.284 | vs B0 +0.0019 [-0.0021,+0.0061] NO DIFFERENCE  | vs B4 +0.0018 [-0.0020,+0.0058] NO DIFFERENCE
   V3   Brier 0.2157 meanP 0.250 | vs B0 +0.0057 [-0.0002,+0.0118] NO DIFFERENCE  | vs B4 +0.0056 [-0.0001,+0.0115] NO DIFFERENCE
   V4   Brier 0.2120 meanP 0.288 | vs B0 +0.0019 [-0.0021,+0.0061] NO DIFFERENCE  | vs B4 +0.0019 [-0.0019,+0.0058] NO DIFFERENCE
   V5   Brier 0.2118 meanP 0.287 | vs B0 +0.0017 [-0.0022,+0.0058] NO DIFFERENCE  | vs B4 +0.0017 [-0.0019,+0.0055] NO DIFFERENCE
   V5r  Brier 0.2120 meanP 0.288 | vs B0 +0.0019 [-0.0020,+0.0060] NO DIFFERENCE  | vs B4 +0.0019 [-0.0017,+0.0057] NO DIFFERENCE
   V5c  Brier 0.2120 meanP 0.288 | vs B0 +0.0019 [-0.0020,+0.0060] NO DIFFERENCE  | vs B4 +0.0019 [-0.0018,+0.0057] NO DIFFERENCE
   V6   Brier 0.2119 meanP 0.288 | vs B0 +0.0019 [-0.0021,+0.0061] NO DIFFERENCE  | vs B4 +0.0019 [-0.0019,+0.0058] NO DIFFERENCE
   V5o  Brier 0.2120 meanP 0.288 | vs B0 +0.0020 [-0.0020,+0.0061] NO DIFFERENCE  | vs B4 +0.0020 [-0.0017,+0.0057] NO DIFFERENCE
   V7   Brier 0.2130 meanP 0.289 | vs B0 +0.0029 [-0.0006,+0.0066] NO DIFFERENCE  | vs B4 +0.0029 [-0.0004,+0.0062] NO DIFFERENCE
   V7o  Brier 0.2131 meanP 0.289 | vs B0 +0.0031 [-0.0004,+0.0065] NO DIFFERENCE  | vs B4 +0.0031 [-0.0001,+0.0062] NO DIFFERENCE
   V8   Brier 0.2124 meanP 0.289 | vs B0 +0.0024 [-0.0013,+0.0062] NO DIFFERENCE  | vs B4 +0.0023 [-0.0011,+0.0059] NO DIFFERENCE
   V8o  Brier 0.2125 meanP 0.289 | vs B0 +0.0025 [-0.0011,+0.0061] NO DIFFERENCE  | vs B4 +0.0024 [-0.0009,+0.0058] NO DIFFERENCE
PL away -1.5 (freq 0.273; B0 Brier 0.1942 meanP 0.257; B4 0.1942 meanP 0.263)
   V0   Brier 0.1923 meanP 0.256 | vs B0 -0.0020 [-0.0056,+0.0016] NO DIFFERENCE  | vs B4 -0.0019 [-0.0052,+0.0013] NO DIFFERENCE
   V1   Brier 0.1923 meanP 0.256 | vs B0 -0.0020 [-0.0056,+0.0016] NO DIFFERENCE  | vs B4 -0.0019 [-0.0052,+0.0013] NO DIFFERENCE
   V2   Brier 0.1929 meanP 0.251 | vs B0 -0.0013 [-0.0051,+0.0023] NO DIFFERENCE  | vs B4 -0.0013 [-0.0047,+0.0020] NO DIFFERENCE
   V3   Brier 0.1956 meanP 0.221 | vs B0 +0.0013 [-0.0033,+0.0056] NO DIFFERENCE  | vs B4 +0.0014 [-0.0031,+0.0056] NO DIFFERENCE
   V4   Brier 0.1929 meanP 0.257 | vs B0 -0.0014 [-0.0051,+0.0023] NO DIFFERENCE  | vs B4 -0.0013 [-0.0047,+0.0019] NO DIFFERENCE
   V5   Brier 0.1931 meanP 0.256 | vs B0 -0.0012 [-0.0048,+0.0023] NO DIFFERENCE  | vs B4 -0.0011 [-0.0045,+0.0020] NO DIFFERENCE
   V5r  Brier 0.1931 meanP 0.256 | vs B0 -0.0011 [-0.0047,+0.0024] NO DIFFERENCE  | vs B4 -0.0011 [-0.0044,+0.0020] NO DIFFERENCE
   V5c  Brier 0.1929 meanP 0.256 | vs B0 -0.0013 [-0.0050,+0.0022] NO DIFFERENCE  | vs B4 -0.0013 [-0.0046,+0.0019] NO DIFFERENCE
   V6   Brier 0.1928 meanP 0.254 | vs B0 -0.0014 [-0.0052,+0.0021] NO DIFFERENCE  | vs B4 -0.0014 [-0.0049,+0.0019] NO DIFFERENCE
   V5o  Brier 0.1928 meanP 0.256 | vs B0 -0.0014 [-0.0051,+0.0020] NO DIFFERENCE  | vs B4 -0.0014 [-0.0047,+0.0018] NO DIFFERENCE
   V7   Brier 0.1928 meanP 0.255 | vs B0 -0.0015 [-0.0051,+0.0022] NO DIFFERENCE  | vs B4 -0.0014 [-0.0048,+0.0019] NO DIFFERENCE
   V7o  Brier 0.1926 meanP 0.255 | vs B0 -0.0016 [-0.0049,+0.0017] NO DIFFERENCE  | vs B4 -0.0016 [-0.0046,+0.0014] NO DIFFERENCE
   V8   Brier 0.1928 meanP 0.255 | vs B0 -0.0014 [-0.0050,+0.0020] NO DIFFERENCE  | vs B4 -0.0014 [-0.0047,+0.0017] NO DIFFERENCE
   V8o  Brier 0.1926 meanP 0.256 | vs B0 -0.0016 [-0.0050,+0.0016] NO DIFFERENCE  | vs B4 -0.0016 [-0.0046,+0.0014] NO DIFFERENCE
OVER 5.5 (freq 0.593; B0 Brier 0.2426 meanP 0.573; B4 0.2427 meanP 0.575)
   V0   Brier 0.2407 meanP 0.611 | vs B0 -0.0019 [-0.0070,+0.0033] NO DIFFERENCE  | vs B4 -0.0020 [-0.0071,+0.0031] NO DIFFERENCE
   V1   Brier 0.2407 meanP 0.611 | vs B0 -0.0019 [-0.0070,+0.0033] NO DIFFERENCE  | vs B4 -0.0020 [-0.0071,+0.0031] NO DIFFERENCE
   V2   Brier 0.2423 meanP 0.554 | vs B0 -0.0003 [-0.0052,+0.0044] NO DIFFERENCE  | vs B4 -0.0004 [-0.0053,+0.0041] NO DIFFERENCE
   V3   Brier 0.2423 meanP 0.553 | vs B0 -0.0002 [-0.0052,+0.0044] NO DIFFERENCE  | vs B4 -0.0004 [-0.0053,+0.0041] NO DIFFERENCE
   V4   Brier 0.2411 meanP 0.578 | vs B0 -0.0015 [-0.0062,+0.0029] NO DIFFERENCE  | vs B4 -0.0017 [-0.0062,+0.0027] NO DIFFERENCE
   V5   Brier 0.2411 meanP 0.571 | vs B0 -0.0015 [-0.0060,+0.0026] NO DIFFERENCE  | vs B4 -0.0017 [-0.0060,+0.0024] NO DIFFERENCE
   V5r  Brier 0.2408 meanP 0.572 | vs B0 -0.0018 [-0.0064,+0.0025] NO DIFFERENCE  | vs B4 -0.0020 [-0.0064,+0.0022] NO DIFFERENCE
   V5c  Brier 0.2409 meanP 0.572 | vs B0 -0.0016 [-0.0060,+0.0025] NO DIFFERENCE  | vs B4 -0.0018 [-0.0061,+0.0023] NO DIFFERENCE
   V6   Brier 0.2409 meanP 0.565 | vs B0 -0.0016 [-0.0063,+0.0027] NO DIFFERENCE  | vs B4 -0.0018 [-0.0064,+0.0024] NO DIFFERENCE
   V5o  Brier 0.2409 meanP 0.573 | vs B0 -0.0017 [-0.0061,+0.0025] NO DIFFERENCE  | vs B4 -0.0019 [-0.0062,+0.0022] NO DIFFERENCE
   V7   Brier 0.2408 meanP 0.565 | vs B0 -0.0017 [-0.0057,+0.0022] NO DIFFERENCE  | vs B4 -0.0019 [-0.0058,+0.0019] NO DIFFERENCE
   V7o  Brier 0.2399 meanP 0.568 | vs B0 -0.0027 [-0.0067,+0.0013] NO DIFFERENCE  | vs B4 -0.0029 [-0.0070,+0.0011] NO DIFFERENCE
   V8   Brier 0.2402 meanP 0.570 | vs B0 -0.0024 [-0.0064,+0.0014] NO DIFFERENCE  | vs B4 -0.0025 [-0.0065,+0.0012] NO DIFFERENCE
   V8o  Brier 0.2398 meanP 0.572 | vs B0 -0.0027 [-0.0068,+0.0012] NO DIFFERENCE  | vs B4 -0.0029 [-0.0069,+0.0010] NO DIFFERENCE
OVER 6.5 (freq 0.479; B0 Brier 0.2543 meanP 0.415; B4 0.2510 meanP 0.453)
   V0   Brier 0.2491 meanP 0.453 | vs B0 -0.0052 [-0.0114,+0.0010] NO DIFFERENCE  | vs B4 -0.0019 [-0.0078,+0.0037] NO DIFFERENCE
   V1   Brier 0.2488 meanP 0.502 | vs B0 -0.0055 [-0.0128,+0.0022] NO DIFFERENCE  | vs B4 -0.0022 [-0.0087,+0.0044] NO DIFFERENCE
   V2   Brier 0.2499 meanP 0.444 | vs B0 -0.0044 [-0.0105,+0.0015] NO DIFFERENCE  | vs B4 -0.0011 [-0.0070,+0.0045] NO DIFFERENCE
   V3   Brier 0.2492 meanP 0.456 | vs B0 -0.0052 [-0.0113,+0.0010] NO DIFFERENCE  | vs B4 -0.0018 [-0.0077,+0.0036] NO DIFFERENCE
   V4   Brier 0.2492 meanP 0.456 | vs B0 -0.0052 [-0.0113,+0.0010] NO DIFFERENCE  | vs B4 -0.0018 [-0.0077,+0.0036] NO DIFFERENCE
   V5   Brier 0.2492 meanP 0.450 | vs B0 -0.0051 [-0.0114,+0.0008] NO DIFFERENCE  | vs B4 -0.0018 [-0.0077,+0.0035] NO DIFFERENCE
   V5r  Brier 0.2488 meanP 0.451 | vs B0 -0.0055 [-0.0117,+0.0005] NO DIFFERENCE  | vs B4 -0.0022 [-0.0082,+0.0033] NO DIFFERENCE
   V5c  Brier 0.2489 meanP 0.450 | vs B0 -0.0054 [-0.0115,+0.0003] NO DIFFERENCE  | vs B4 -0.0021 [-0.0079,+0.0031] NO DIFFERENCE
   V6   Brier 0.2495 meanP 0.443 | vs B0 -0.0048 [-0.0108,+0.0009] NO DIFFERENCE  | vs B4 -0.0015 [-0.0073,+0.0037] NO DIFFERENCE
   V5o  Brier 0.2490 meanP 0.451 | vs B0 -0.0053 [-0.0113,+0.0005] NO DIFFERENCE  | vs B4 -0.0020 [-0.0077,+0.0033] NO DIFFERENCE
   V7   Brier 0.2483 meanP 0.444 | vs B0 -0.0060 [-0.0110,-0.0012] MODEL BETTER   | vs B4 -0.0027 [-0.0076,+0.0021] NO DIFFERENCE
   V7o  Brier 0.2482 meanP 0.446 | vs B0 -0.0061 [-0.0110,-0.0014] MODEL BETTER   | vs B4 -0.0028 [-0.0076,+0.0018] NO DIFFERENCE
   V8   Brier 0.2481 meanP 0.448 | vs B0 -0.0062 [-0.0115,-0.0012] MODEL BETTER   | vs B4 -0.0029 [-0.0079,+0.0019] NO DIFFERENCE
   V8o  Brier 0.2484 meanP 0.450 | vs B0 -0.0060 [-0.0112,-0.0008] MODEL BETTER   | vs B4 -0.0026 [-0.0076,+0.0021] NO DIFFERENCE
ML vs BOOK (n=680; book Brier 0.2430)
   V0   dBrier vs book -0.0003 [-0.0053,+0.0044] dLL -0.0005 [-0.0112,+0.0093] NO DIFFERENCE
   V1   dBrier vs book -0.0002 [-0.0053,+0.0046] dLL -0.0004 [-0.0112,+0.0095] NO DIFFERENCE
   V2   dBrier vs book -0.0001 [-0.0054,+0.0047] dLL -0.0003 [-0.0111,+0.0098] NO DIFFERENCE
   V3   dBrier vs book +0.0003 [-0.0051,+0.0055] dLL +0.0007 [-0.0107,+0.0115] NO DIFFERENCE
   V4   dBrier vs book +0.0003 [-0.0051,+0.0055] dLL +0.0007 [-0.0107,+0.0115] NO DIFFERENCE
   V5   dBrier vs book +0.0005 [-0.0049,+0.0056] dLL +0.0012 [-0.0103,+0.0118] NO DIFFERENCE
   V5r  dBrier vs book +0.0005 [-0.0049,+0.0055] dLL +0.0011 [-0.0102,+0.0115] NO DIFFERENCE
   V5c  dBrier vs book +0.0003 [-0.0050,+0.0054] dLL +0.0007 [-0.0104,+0.0112] NO DIFFERENCE
   V6   dBrier vs book +0.0003 [-0.0047,+0.0049] dLL +0.0006 [-0.0099,+0.0103] NO DIFFERENCE
   V5o  dBrier vs book +0.0003 [-0.0049,+0.0054] dLL +0.0007 [-0.0104,+0.0115] NO DIFFERENCE
   V7   dBrier vs book +0.0006 [-0.0042,+0.0053] dLL +0.0012 [-0.0089,+0.0113] NO DIFFERENCE
   V7o  dBrier vs book +0.0005 [-0.0044,+0.0054] dLL +0.0010 [-0.0092,+0.0111] NO DIFFERENCE
   V8   dBrier vs book +0.0004 [-0.0045,+0.0050] dLL +0.0009 [-0.0095,+0.0107] NO DIFFERENCE
   V8o  dBrier vs book +0.0002 [-0.0046,+0.0049] dLL +0.0006 [-0.0097,+0.0103] NO DIFFERENCE
   B0   dBrier vs book +0.0005 [-0.0045,+0.0053] dLL +0.0016 [-0.0090,+0.0115] NO DIFFERENCE
   B4   dBrier vs book +0.0007 [-0.0043,+0.0055] dLL +0.0018 [-0.0087,+0.0119] NO DIFFERENCE
PL home @book line vs BOOK (n=680; book Brier 0.2229)
   V0   dBrier vs book +0.0023 [-0.0033,+0.0078] dLL +0.0047 [-0.0078,+0.0165] NO DIFFERENCE
   V1   dBrier vs book +0.0023 [-0.0033,+0.0078] dLL +0.0047 [-0.0078,+0.0165] NO DIFFERENCE
   V2   dBrier vs book +0.0032 [-0.0030,+0.0093] dLL +0.0066 [-0.0070,+0.0198] NO DIFFERENCE
   V3   dBrier vs book +0.0084 [-0.0005,+0.0173] dLL +0.0189 [-0.0013,+0.0391] NO DIFFERENCE
   V4   dBrier vs book +0.0032 [-0.0028,+0.0090] dLL +0.0065 [-0.0067,+0.0192] NO DIFFERENCE
   V5   dBrier vs book +0.0030 [-0.0030,+0.0088] dLL +0.0061 [-0.0069,+0.0190] NO DIFFERENCE
   V5r  dBrier vs book +0.0033 [-0.0028,+0.0092] dLL +0.0068 [-0.0063,+0.0199] NO DIFFERENCE
   V5c  dBrier vs book +0.0032 [-0.0029,+0.0091] dLL +0.0067 [-0.0065,+0.0196] NO DIFFERENCE
   V6   dBrier vs book +0.0031 [-0.0026,+0.0089] dLL +0.0065 [-0.0061,+0.0190] NO DIFFERENCE
   V5o  dBrier vs book +0.0032 [-0.0028,+0.0091] dLL +0.0066 [-0.0065,+0.0196] NO DIFFERENCE
   V7   dBrier vs book +0.0037 [-0.0021,+0.0094] dLL +0.0080 [-0.0050,+0.0210] NO DIFFERENCE
   V7o  dBrier vs book +0.0036 [-0.0021,+0.0092] dLL +0.0077 [-0.0048,+0.0201] NO DIFFERENCE
   V8   dBrier vs book +0.0035 [-0.0024,+0.0092] dLL +0.0074 [-0.0055,+0.0199] NO DIFFERENCE
   V8o  dBrier vs book +0.0033 [-0.0025,+0.0090] dLL +0.0069 [-0.0057,+0.0193] NO DIFFERENCE
   B0   dBrier vs book +0.0019 [-0.0035,+0.0073] dLL +0.0043 [-0.0079,+0.0167] NO DIFFERENCE
   B4   dBrier vs book +0.0020 [-0.0033,+0.0071] dLL +0.0044 [-0.0074,+0.0161] NO DIFFERENCE
OVER @close vs BOOK (n=647; book Brier 0.2475)
   V0   dBrier vs book +0.0025 [-0.0019,+0.0067] dLL +0.0051 [-0.0040,+0.0137] NO DIFFERENCE
   V1   dBrier vs book +0.0031 [-0.0012,+0.0073] dLL +0.0062 [-0.0026,+0.0148] NO DIFFERENCE
   V2   dBrier vs book +0.0037 [-0.0002,+0.0076] dLL +0.0075 [-0.0006,+0.0153] NO DIFFERENCE
   V3   dBrier vs book +0.0033 [-0.0004,+0.0068] dLL +0.0066 [-0.0008,+0.0138] NO DIFFERENCE
   V4   dBrier vs book +0.0028 [-0.0010,+0.0065] dLL +0.0057 [-0.0021,+0.0131] NO DIFFERENCE
   V5   dBrier vs book +0.0029 [-0.0009,+0.0064] dLL +0.0057 [-0.0019,+0.0130] NO DIFFERENCE
   V5r  dBrier vs book +0.0024 [-0.0015,+0.0060] dLL +0.0047 [-0.0031,+0.0121] NO DIFFERENCE
   V5c  dBrier vs book +0.0025 [-0.0013,+0.0061] dLL +0.0051 [-0.0026,+0.0122] NO DIFFERENCE
   V6   dBrier vs book +0.0029 [-0.0010,+0.0065] dLL +0.0057 [-0.0021,+0.0132] NO DIFFERENCE
   V5o  dBrier vs book +0.0026 [-0.0011,+0.0061] dLL +0.0052 [-0.0022,+0.0122] NO DIFFERENCE
   V7   dBrier vs book +0.0014 [-0.0025,+0.0051] dLL +0.0027 [-0.0050,+0.0103] NO DIFFERENCE
   V7o  dBrier vs book +0.0007 [-0.0028,+0.0043] dLL +0.0015 [-0.0057,+0.0086] NO DIFFERENCE
   V8   dBrier vs book +0.0012 [-0.0020,+0.0046] dLL +0.0025 [-0.0040,+0.0093] NO DIFFERENCE
   V8o  dBrier vs book +0.0011 [-0.0020,+0.0042] dLL +0.0023 [-0.0040,+0.0085] NO DIFFERENCE
   B0   dBrier vs book +0.0053 [+0.0012,+0.0092] dLL +0.0108 [+0.0023,+0.0186] MODEL WORSE
   B4   dBrier vs book +0.0045 [+0.0011,+0.0077] dLL +0.0091 [+0.0021,+0.0156] MODEL WORSE
TOTAL settled (MAE / bias)
   V0   MAE 1.847 bias +0.021 [-0.132,+0.184] | dMAE vs B4 -0.0099 [-0.0435,+0.0236]
   V1   MAE 1.855 bias +0.180 [+0.027,+0.344] | dMAE vs B4 -0.0021 [-0.0386,+0.0342]
   V2   MAE 1.847 bias -0.184 [-0.339,-0.020] | dMAE vs B4 -0.0096 [-0.0431,+0.0221]
   V3   MAE 1.846 bias -0.149 [-0.303,+0.015] | dMAE vs B4 -0.0104 [-0.0433,+0.0207]
   V4   MAE 1.847 bias -0.075 [-0.229,+0.090] | dMAE vs B4 -0.0101 [-0.0422,+0.0215]
   V5   MAE 1.846 bias -0.112 [-0.266,+0.052] | dMAE vs B4 -0.0108 [-0.0427,+0.0195]
   V5r  MAE 1.843 bias -0.106 [-0.261,+0.058] | dMAE vs B4 -0.0136 [-0.0459,+0.0171]
   V5c  MAE 1.844 bias -0.108 [-0.262,+0.056] | dMAE vs B4 -0.0127 [-0.0440,+0.0170]
   V6   MAE 1.845 bias -0.152 [-0.307,+0.013] | dMAE vs B4 -0.0121 [-0.0449,+0.0171]
   V5o  MAE 1.845 bias -0.103 [-0.257,+0.062] | dMAE vs B4 -0.0119 [-0.0431,+0.0181]
   V7   MAE 1.839 bias -0.149 [-0.301,+0.011] | dMAE vs B4 -0.0179 [-0.0468,+0.0095]
   V7o  MAE 1.837 bias -0.135 [-0.290,+0.026] | dMAE vs B4 -0.0201 [-0.0469,+0.0062]
   V8   MAE 1.839 bias -0.125 [-0.278,+0.036] | dMAE vs B4 -0.0182 [-0.0476,+0.0090]
   V8o  MAE 1.839 bias -0.112 [-0.267,+0.050] | dMAE vs B4 -0.0176 [-0.0452,+0.0093]
   B0   MAE 1.857 bias -0.218 [-0.372,-0.057]
   B4   MAE 1.857 bias -0.084 [-0.240,+0.080]
```

## FULL regular 11-01..04-16 (n=1132)

```
ML home (freq 0.521; B0 Brier 0.2481 meanP 0.517; B4 0.2477 meanP 0.510)
   V0   Brier 0.2447 meanP 0.521 | vs B0 -0.0034 [-0.0075,+0.0007] NO DIFFERENCE  | vs B4 -0.0030 [-0.0068,+0.0007] NO DIFFERENCE
   V1   Brier 0.2448 meanP 0.518 | vs B0 -0.0033 [-0.0074,+0.0008] NO DIFFERENCE  | vs B4 -0.0029 [-0.0066,+0.0007] NO DIFFERENCE
   V2   Brier 0.2448 meanP 0.517 | vs B0 -0.0033 [-0.0074,+0.0007] NO DIFFERENCE  | vs B4 -0.0029 [-0.0066,+0.0007] NO DIFFERENCE
   V3   Brier 0.2450 meanP 0.513 | vs B0 -0.0031 [-0.0071,+0.0008] NO DIFFERENCE  | vs B4 -0.0027 [-0.0062,+0.0008] NO DIFFERENCE
   V4   Brier 0.2450 meanP 0.513 | vs B0 -0.0031 [-0.0071,+0.0008] NO DIFFERENCE  | vs B4 -0.0027 [-0.0062,+0.0008] NO DIFFERENCE
   V5   Brier 0.2451 meanP 0.513 | vs B0 -0.0030 [-0.0068,+0.0008] NO DIFFERENCE  | vs B4 -0.0026 [-0.0060,+0.0007] NO DIFFERENCE
   V5r  Brier 0.2450 meanP 0.513 | vs B0 -0.0031 [-0.0069,+0.0007] NO DIFFERENCE  | vs B4 -0.0026 [-0.0060,+0.0007] NO DIFFERENCE
   V5c  Brier 0.2450 meanP 0.513 | vs B0 -0.0031 [-0.0070,+0.0007] NO DIFFERENCE  | vs B4 -0.0026 [-0.0060,+0.0007] NO DIFFERENCE
   V6   Brier 0.2447 meanP 0.514 | vs B0 -0.0034 [-0.0073,+0.0005] NO DIFFERENCE  | vs B4 -0.0029 [-0.0066,+0.0005] NO DIFFERENCE
   V5o  Brier 0.2449 meanP 0.513 | vs B0 -0.0032 [-0.0071,+0.0006] NO DIFFERENCE  | vs B4 -0.0028 [-0.0062,+0.0006] NO DIFFERENCE
   V7   Brier 0.2459 meanP 0.514 | vs B0 -0.0022 [-0.0058,+0.0012] NO DIFFERENCE  | vs B4 -0.0017 [-0.0049,+0.0012] NO DIFFERENCE
   V7o  Brier 0.2455 meanP 0.514 | vs B0 -0.0026 [-0.0064,+0.0009] NO DIFFERENCE  | vs B4 -0.0022 [-0.0054,+0.0008] NO DIFFERENCE
   V8   Brier 0.2455 meanP 0.514 | vs B0 -0.0026 [-0.0063,+0.0009] NO DIFFERENCE  | vs B4 -0.0022 [-0.0054,+0.0008] NO DIFFERENCE
   V8o  Brier 0.2450 meanP 0.514 | vs B0 -0.0031 [-0.0068,+0.0006] NO DIFFERENCE  | vs B4 -0.0027 [-0.0059,+0.0005] NO DIFFERENCE
REG tie (freq 0.246; B0 Brier 0.1927 meanP 0.161; B4 0.1856 meanP 0.267)
   V0   Brier 0.1933 meanP 0.160 | vs B0 +0.0007 [+0.0001,+0.0012] MODEL WORSE    | vs B4 +0.0077 [+0.0029,+0.0127] MODEL WORSE
   V1   Brier 0.1933 meanP 0.160 | vs B0 +0.0007 [+0.0001,+0.0012] MODEL WORSE    | vs B4 +0.0077 [+0.0029,+0.0127] MODEL WORSE
   V2   Brier 0.1923 meanP 0.165 | vs B0 -0.0004 [-0.0009,+0.0002] NO DIFFERENCE  | vs B4 +0.0067 [+0.0020,+0.0115] MODEL WORSE
   V3   Brier 0.1864 meanP 0.272 | vs B0 -0.0062 [-0.0112,-0.0012] MODEL BETTER   | vs B4 +0.0008 [+0.0000,+0.0015] MODEL WORSE
   V4   Brier 0.1864 meanP 0.272 | vs B0 -0.0062 [-0.0112,-0.0012] MODEL BETTER   | vs B4 +0.0008 [+0.0000,+0.0015] MODEL WORSE
   V5   Brier 0.1866 meanP 0.272 | vs B0 -0.0061 [-0.0110,-0.0010] MODEL BETTER   | vs B4 +0.0010 [+0.0002,+0.0017] MODEL WORSE
   V5r  Brier 0.1866 meanP 0.272 | vs B0 -0.0060 [-0.0110,-0.0010] MODEL BETTER   | vs B4 +0.0010 [+0.0002,+0.0018] MODEL WORSE
   V5c  Brier 0.1867 meanP 0.272 | vs B0 -0.0059 [-0.0108,-0.0008] MODEL BETTER   | vs B4 +0.0011 [+0.0004,+0.0019] MODEL WORSE
   V6   Brier 0.1867 meanP 0.273 | vs B0 -0.0060 [-0.0109,-0.0009] MODEL BETTER   | vs B4 +0.0011 [+0.0003,+0.0018] MODEL WORSE
   V5o  Brier 0.1867 meanP 0.272 | vs B0 -0.0059 [-0.0109,-0.0009] MODEL BETTER   | vs B4 +0.0011 [+0.0003,+0.0019] MODEL WORSE
   V7   Brier 0.1865 meanP 0.272 | vs B0 -0.0062 [-0.0112,-0.0010] MODEL BETTER   | vs B4 +0.0009 [+0.0001,+0.0016] MODEL WORSE
   V7o  Brier 0.1864 meanP 0.272 | vs B0 -0.0062 [-0.0112,-0.0011] MODEL BETTER   | vs B4 +0.0008 [+0.0001,+0.0015] MODEL WORSE
   V8   Brier 0.1867 meanP 0.272 | vs B0 -0.0060 [-0.0109,-0.0009] MODEL BETTER   | vs B4 +0.0011 [+0.0003,+0.0018] MODEL WORSE
   V8o  Brier 0.1865 meanP 0.272 | vs B0 -0.0062 [-0.0111,-0.0011] MODEL BETTER   | vs B4 +0.0009 [+0.0002,+0.0016] MODEL WORSE
REG home (freq 0.400; B0 Brier 0.2376 meanP 0.436; B4 0.2361 meanP 0.381)
   V0   Brier 0.2366 meanP 0.441 | vs B0 -0.0009 [-0.0048,+0.0029] NO DIFFERENCE  | vs B4 +0.0006 [-0.0043,+0.0052] NO DIFFERENCE
   V1   Brier 0.2366 meanP 0.441 | vs B0 -0.0009 [-0.0048,+0.0029] NO DIFFERENCE  | vs B4 +0.0006 [-0.0043,+0.0052] NO DIFFERENCE
   V2   Brier 0.2363 meanP 0.437 | vs B0 -0.0013 [-0.0052,+0.0025] NO DIFFERENCE  | vs B4 +0.0002 [-0.0046,+0.0047] NO DIFFERENCE
   V3   Brier 0.2353 meanP 0.382 | vs B0 -0.0023 [-0.0075,+0.0028] NO DIFFERENCE  | vs B4 -0.0008 [-0.0042,+0.0026] NO DIFFERENCE
   V4   Brier 0.2353 meanP 0.382 | vs B0 -0.0023 [-0.0075,+0.0028] NO DIFFERENCE  | vs B4 -0.0008 [-0.0042,+0.0026] NO DIFFERENCE
   V5   Brier 0.2354 meanP 0.381 | vs B0 -0.0021 [-0.0074,+0.0028] NO DIFFERENCE  | vs B4 -0.0006 [-0.0039,+0.0026] NO DIFFERENCE
   V5r  Brier 0.2354 meanP 0.382 | vs B0 -0.0021 [-0.0075,+0.0029] NO DIFFERENCE  | vs B4 -0.0006 [-0.0040,+0.0026] NO DIFFERENCE
   V5c  Brier 0.2356 meanP 0.382 | vs B0 -0.0019 [-0.0072,+0.0030] NO DIFFERENCE  | vs B4 -0.0004 [-0.0037,+0.0028] NO DIFFERENCE
   V6   Brier 0.2354 meanP 0.382 | vs B0 -0.0022 [-0.0075,+0.0028] NO DIFFERENCE  | vs B4 -0.0007 [-0.0040,+0.0027] NO DIFFERENCE
   V5o  Brier 0.2355 meanP 0.382 | vs B0 -0.0021 [-0.0073,+0.0029] NO DIFFERENCE  | vs B4 -0.0006 [-0.0039,+0.0026] NO DIFFERENCE
   V7   Brier 0.2366 meanP 0.382 | vs B0 -0.0010 [-0.0059,+0.0036] NO DIFFERENCE  | vs B4 +0.0005 [-0.0024,+0.0034] NO DIFFERENCE
   V7o  Brier 0.2361 meanP 0.383 | vs B0 -0.0014 [-0.0063,+0.0032] NO DIFFERENCE  | vs B4 +0.0001 [-0.0029,+0.0030] NO DIFFERENCE
   V8   Brier 0.2361 meanP 0.383 | vs B0 -0.0014 [-0.0064,+0.0032] NO DIFFERENCE  | vs B4 +0.0001 [-0.0030,+0.0030] NO DIFFERENCE
   V8o  Brier 0.2356 meanP 0.383 | vs B0 -0.0019 [-0.0069,+0.0028] NO DIFFERENCE  | vs B4 -0.0004 [-0.0035,+0.0026] NO DIFFERENCE
PL home -1.5 (freq 0.303; B0 Brier 0.2069 meanP 0.286; B4 0.2067 meanP 0.283)
   V0   Brier 0.2064 meanP 0.291 | vs B0 -0.0004 [-0.0040,+0.0031] NO DIFFERENCE  | vs B4 -0.0003 [-0.0036,+0.0031] NO DIFFERENCE
   V1   Brier 0.2064 meanP 0.291 | vs B0 -0.0004 [-0.0040,+0.0031] NO DIFFERENCE  | vs B4 -0.0003 [-0.0036,+0.0031] NO DIFFERENCE
   V2   Brier 0.2066 meanP 0.283 | vs B0 -0.0002 [-0.0039,+0.0032] NO DIFFERENCE  | vs B4 -0.0000 [-0.0034,+0.0032] NO DIFFERENCE
   V3   Brier 0.2095 meanP 0.247 | vs B0 +0.0027 [-0.0018,+0.0070] NO DIFFERENCE  | vs B4 +0.0028 [-0.0013,+0.0068] NO DIFFERENCE
   V4   Brier 0.2068 meanP 0.282 | vs B0 -0.0001 [-0.0037,+0.0034] NO DIFFERENCE  | vs B4 +0.0001 [-0.0032,+0.0033] NO DIFFERENCE
   V5   Brier 0.2068 meanP 0.282 | vs B0 -0.0001 [-0.0036,+0.0033] NO DIFFERENCE  | vs B4 +0.0001 [-0.0031,+0.0032] NO DIFFERENCE
   V5r  Brier 0.2068 meanP 0.282 | vs B0 -0.0000 [-0.0035,+0.0033] NO DIFFERENCE  | vs B4 +0.0002 [-0.0030,+0.0033] NO DIFFERENCE
   V5c  Brier 0.2068 meanP 0.282 | vs B0 -0.0001 [-0.0035,+0.0033] NO DIFFERENCE  | vs B4 +0.0001 [-0.0030,+0.0032] NO DIFFERENCE
   V6   Brier 0.2065 meanP 0.282 | vs B0 -0.0003 [-0.0038,+0.0031] NO DIFFERENCE  | vs B4 -0.0001 [-0.0034,+0.0030] NO DIFFERENCE
   V5o  Brier 0.2067 meanP 0.282 | vs B0 -0.0001 [-0.0035,+0.0033] NO DIFFERENCE  | vs B4 +0.0001 [-0.0031,+0.0032] NO DIFFERENCE
   V7   Brier 0.2074 meanP 0.283 | vs B0 +0.0006 [-0.0025,+0.0035] NO DIFFERENCE  | vs B4 +0.0007 [-0.0019,+0.0034] NO DIFFERENCE
   V7o  Brier 0.2071 meanP 0.283 | vs B0 +0.0002 [-0.0028,+0.0032] NO DIFFERENCE  | vs B4 +0.0004 [-0.0023,+0.0031] NO DIFFERENCE
   V8   Brier 0.2070 meanP 0.283 | vs B0 +0.0001 [-0.0030,+0.0033] NO DIFFERENCE  | vs B4 +0.0003 [-0.0026,+0.0032] NO DIFFERENCE
   V8o  Brier 0.2067 meanP 0.283 | vs B0 -0.0001 [-0.0032,+0.0030] NO DIFFERENCE  | vs B4 +0.0000 [-0.0028,+0.0029] NO DIFFERENCE
PL away -1.5 (freq 0.270; B0 Brier 0.1956 meanP 0.257; B4 0.1956 meanP 0.257)
   V0   Brier 0.1937 meanP 0.256 | vs B0 -0.0019 [-0.0047,+0.0009] NO DIFFERENCE  | vs B4 -0.0018 [-0.0044,+0.0007] NO DIFFERENCE
   V1   Brier 0.1937 meanP 0.256 | vs B0 -0.0019 [-0.0047,+0.0009] NO DIFFERENCE  | vs B4 -0.0018 [-0.0044,+0.0007] NO DIFFERENCE
   V2   Brier 0.1942 meanP 0.249 | vs B0 -0.0014 [-0.0044,+0.0014] NO DIFFERENCE  | vs B4 -0.0014 [-0.0040,+0.0012] NO DIFFERENCE
   V3   Brier 0.1966 meanP 0.218 | vs B0 +0.0010 [-0.0026,+0.0045] NO DIFFERENCE  | vs B4 +0.0011 [-0.0023,+0.0043] NO DIFFERENCE
   V4   Brier 0.1943 meanP 0.251 | vs B0 -0.0013 [-0.0043,+0.0016] NO DIFFERENCE  | vs B4 -0.0013 [-0.0039,+0.0013] NO DIFFERENCE
   V5   Brier 0.1943 meanP 0.250 | vs B0 -0.0013 [-0.0042,+0.0014] NO DIFFERENCE  | vs B4 -0.0013 [-0.0038,+0.0012] NO DIFFERENCE
   V5r  Brier 0.1944 meanP 0.250 | vs B0 -0.0012 [-0.0040,+0.0016] NO DIFFERENCE  | vs B4 -0.0011 [-0.0037,+0.0014] NO DIFFERENCE
   V5c  Brier 0.1943 meanP 0.250 | vs B0 -0.0013 [-0.0042,+0.0015] NO DIFFERENCE  | vs B4 -0.0013 [-0.0038,+0.0013] NO DIFFERENCE
   V6   Brier 0.1942 meanP 0.248 | vs B0 -0.0014 [-0.0044,+0.0015] NO DIFFERENCE  | vs B4 -0.0014 [-0.0041,+0.0012] NO DIFFERENCE
   V5o  Brier 0.1942 meanP 0.250 | vs B0 -0.0014 [-0.0042,+0.0015] NO DIFFERENCE  | vs B4 -0.0013 [-0.0040,+0.0012] NO DIFFERENCE
   V7   Brier 0.1943 meanP 0.250 | vs B0 -0.0013 [-0.0041,+0.0013] NO DIFFERENCE  | vs B4 -0.0013 [-0.0037,+0.0011] NO DIFFERENCE
   V7o  Brier 0.1941 meanP 0.250 | vs B0 -0.0016 [-0.0042,+0.0010] NO DIFFERENCE  | vs B4 -0.0015 [-0.0039,+0.0008] NO DIFFERENCE
   V8   Brier 0.1942 meanP 0.250 | vs B0 -0.0014 [-0.0043,+0.0013] NO DIFFERENCE  | vs B4 -0.0014 [-0.0039,+0.0010] NO DIFFERENCE
   V8o  Brier 0.1940 meanP 0.250 | vs B0 -0.0016 [-0.0044,+0.0010] NO DIFFERENCE  | vs B4 -0.0016 [-0.0040,+0.0008] NO DIFFERENCE
OVER 5.5 (freq 0.569; B0 Brier 0.2474 meanP 0.570; B4 0.2474 meanP 0.564)
   V0   Brier 0.2460 meanP 0.608 | vs B0 -0.0014 [-0.0058,+0.0032] NO DIFFERENCE  | vs B4 -0.0014 [-0.0061,+0.0035] NO DIFFERENCE
   V1   Brier 0.2460 meanP 0.608 | vs B0 -0.0014 [-0.0058,+0.0032] NO DIFFERENCE  | vs B4 -0.0014 [-0.0061,+0.0035] NO DIFFERENCE
   V2   Brier 0.2453 meanP 0.545 | vs B0 -0.0021 [-0.0067,+0.0024] NO DIFFERENCE  | vs B4 -0.0021 [-0.0062,+0.0020] NO DIFFERENCE
   V3   Brier 0.2453 meanP 0.545 | vs B0 -0.0021 [-0.0067,+0.0024] NO DIFFERENCE  | vs B4 -0.0021 [-0.0063,+0.0020] NO DIFFERENCE
   V4   Brier 0.2447 meanP 0.567 | vs B0 -0.0027 [-0.0067,+0.0014] NO DIFFERENCE  | vs B4 -0.0027 [-0.0067,+0.0013] NO DIFFERENCE
   V5   Brier 0.2447 meanP 0.561 | vs B0 -0.0027 [-0.0067,+0.0014] NO DIFFERENCE  | vs B4 -0.0026 [-0.0064,+0.0013] NO DIFFERENCE
   V5r  Brier 0.2445 meanP 0.562 | vs B0 -0.0029 [-0.0069,+0.0012] NO DIFFERENCE  | vs B4 -0.0028 [-0.0066,+0.0011] NO DIFFERENCE
   V5c  Brier 0.2445 meanP 0.562 | vs B0 -0.0028 [-0.0069,+0.0012] NO DIFFERENCE  | vs B4 -0.0028 [-0.0066,+0.0011] NO DIFFERENCE
   V6   Brier 0.2441 meanP 0.555 | vs B0 -0.0033 [-0.0074,+0.0009] NO DIFFERENCE  | vs B4 -0.0033 [-0.0072,+0.0008] NO DIFFERENCE
   V5o  Brier 0.2444 meanP 0.563 | vs B0 -0.0030 [-0.0070,+0.0011] NO DIFFERENCE  | vs B4 -0.0029 [-0.0068,+0.0009] NO DIFFERENCE
   V7   Brier 0.2449 meanP 0.557 | vs B0 -0.0025 [-0.0064,+0.0013] NO DIFFERENCE  | vs B4 -0.0025 [-0.0061,+0.0011] NO DIFFERENCE
   V7o  Brier 0.2442 meanP 0.559 | vs B0 -0.0032 [-0.0070,+0.0006] NO DIFFERENCE  | vs B4 -0.0032 [-0.0068,+0.0005] NO DIFFERENCE
   V8   Brier 0.2442 meanP 0.560 | vs B0 -0.0032 [-0.0070,+0.0006] NO DIFFERENCE  | vs B4 -0.0032 [-0.0068,+0.0004] NO DIFFERENCE
   V8o  Brier 0.2439 meanP 0.562 | vs B0 -0.0035 [-0.0073,+0.0004] NO DIFFERENCE  | vs B4 -0.0035 [-0.0072,+0.0002] NO DIFFERENCE
OVER 6.5 (freq 0.463; B0 Brier 0.2521 meanP 0.412; B4 0.2500 meanP 0.444)
   V0   Brier 0.2478 meanP 0.450 | vs B0 -0.0043 [-0.0090,+0.0004] NO DIFFERENCE  | vs B4 -0.0022 [-0.0066,+0.0023] NO DIFFERENCE
   V1   Brier 0.2487 meanP 0.498 | vs B0 -0.0033 [-0.0096,+0.0028] NO DIFFERENCE  | vs B4 -0.0013 [-0.0066,+0.0039] NO DIFFERENCE
   V2   Brier 0.2483 meanP 0.435 | vs B0 -0.0037 [-0.0082,+0.0008] NO DIFFERENCE  | vs B4 -0.0017 [-0.0061,+0.0028] NO DIFFERENCE
   V3   Brier 0.2478 meanP 0.449 | vs B0 -0.0043 [-0.0091,+0.0003] NO DIFFERENCE  | vs B4 -0.0023 [-0.0066,+0.0023] NO DIFFERENCE
   V4   Brier 0.2478 meanP 0.449 | vs B0 -0.0043 [-0.0091,+0.0003] NO DIFFERENCE  | vs B4 -0.0023 [-0.0066,+0.0023] NO DIFFERENCE
   V5   Brier 0.2478 meanP 0.443 | vs B0 -0.0042 [-0.0088,+0.0003] NO DIFFERENCE  | vs B4 -0.0022 [-0.0064,+0.0022] NO DIFFERENCE
   V5r  Brier 0.2475 meanP 0.444 | vs B0 -0.0045 [-0.0091,-0.0000] MODEL BETTER   | vs B4 -0.0025 [-0.0068,+0.0020] NO DIFFERENCE
   V5c  Brier 0.2475 meanP 0.444 | vs B0 -0.0046 [-0.0092,-0.0002] MODEL BETTER   | vs B4 -0.0026 [-0.0068,+0.0019] NO DIFFERENCE
   V6   Brier 0.2477 meanP 0.437 | vs B0 -0.0044 [-0.0088,+0.0000] NO DIFFERENCE  | vs B4 -0.0024 [-0.0066,+0.0022] NO DIFFERENCE
   V5o  Brier 0.2475 meanP 0.445 | vs B0 -0.0045 [-0.0091,-0.0001] MODEL BETTER   | vs B4 -0.0025 [-0.0067,+0.0018] NO DIFFERENCE
   V7   Brier 0.2478 meanP 0.438 | vs B0 -0.0043 [-0.0082,-0.0003] MODEL BETTER   | vs B4 -0.0023 [-0.0061,+0.0016] NO DIFFERENCE
   V7o  Brier 0.2471 meanP 0.440 | vs B0 -0.0049 [-0.0090,-0.0010] MODEL BETTER   | vs B4 -0.0029 [-0.0066,+0.0009] NO DIFFERENCE
   V8   Brier 0.2472 meanP 0.441 | vs B0 -0.0048 [-0.0090,-0.0008] MODEL BETTER   | vs B4 -0.0028 [-0.0068,+0.0011] NO DIFFERENCE
   V8o  Brier 0.2470 meanP 0.444 | vs B0 -0.0051 [-0.0092,-0.0009] MODEL BETTER   | vs B4 -0.0031 [-0.0069,+0.0009] NO DIFFERENCE
ML vs BOOK (n=1131; book Brier 0.2442)
   V0   dBrier vs book +0.0005 [-0.0030,+0.0039] dLL +0.0012 [-0.0061,+0.0083] NO DIFFERENCE
   V1   dBrier vs book +0.0006 [-0.0029,+0.0040] dLL +0.0014 [-0.0060,+0.0086] NO DIFFERENCE
   V2   dBrier vs book +0.0006 [-0.0030,+0.0041] dLL +0.0013 [-0.0063,+0.0085] NO DIFFERENCE
   V3   dBrier vs book +0.0008 [-0.0029,+0.0044] dLL +0.0018 [-0.0060,+0.0092] NO DIFFERENCE
   V4   dBrier vs book +0.0008 [-0.0029,+0.0044] dLL +0.0018 [-0.0060,+0.0092] NO DIFFERENCE
   V5   dBrier vs book +0.0009 [-0.0028,+0.0044] dLL +0.0020 [-0.0059,+0.0094] NO DIFFERENCE
   V5r  dBrier vs book +0.0008 [-0.0028,+0.0044] dLL +0.0019 [-0.0058,+0.0093] NO DIFFERENCE
   V5c  dBrier vs book +0.0008 [-0.0028,+0.0044] dLL +0.0019 [-0.0058,+0.0093] NO DIFFERENCE
   V6   dBrier vs book +0.0005 [-0.0028,+0.0038] dLL +0.0012 [-0.0059,+0.0081] NO DIFFERENCE
   V5o  dBrier vs book +0.0007 [-0.0030,+0.0042] dLL +0.0016 [-0.0061,+0.0090] NO DIFFERENCE
   V7   dBrier vs book +0.0017 [-0.0018,+0.0051] dLL +0.0037 [-0.0037,+0.0108] NO DIFFERENCE
   V7o  dBrier vs book +0.0013 [-0.0023,+0.0046] dLL +0.0027 [-0.0045,+0.0097] NO DIFFERENCE
   V8   dBrier vs book +0.0013 [-0.0021,+0.0046] dLL +0.0028 [-0.0044,+0.0097] NO DIFFERENCE
   V8o  dBrier vs book +0.0008 [-0.0026,+0.0041] dLL +0.0018 [-0.0052,+0.0086] NO DIFFERENCE
   B0   dBrier vs book +0.0040 [-0.0003,+0.0082] dLL +0.0084 [-0.0004,+0.0169] NO DIFFERENCE
   B4   dBrier vs book +0.0035 [-0.0006,+0.0077] dLL +0.0074 [-0.0011,+0.0159] NO DIFFERENCE
PL home @book line vs BOOK (n=1131; book Brier 0.2168)
   V0   dBrier vs book +0.0010 [-0.0032,+0.0050] dLL +0.0017 [-0.0074,+0.0107] NO DIFFERENCE
   V1   dBrier vs book +0.0010 [-0.0032,+0.0050] dLL +0.0017 [-0.0074,+0.0107] NO DIFFERENCE
   V2   dBrier vs book +0.0014 [-0.0032,+0.0058] dLL +0.0026 [-0.0075,+0.0124] NO DIFFERENCE
   V3   dBrier vs book +0.0048 [-0.0018,+0.0112] dLL +0.0108 [-0.0042,+0.0260] NO DIFFERENCE
   V4   dBrier vs book +0.0014 [-0.0032,+0.0059] dLL +0.0027 [-0.0075,+0.0129] NO DIFFERENCE
   V5   dBrier vs book +0.0013 [-0.0032,+0.0059] dLL +0.0025 [-0.0075,+0.0126] NO DIFFERENCE
   V5r  dBrier vs book +0.0015 [-0.0030,+0.0061] dLL +0.0030 [-0.0071,+0.0131] NO DIFFERENCE
   V5c  dBrier vs book +0.0014 [-0.0031,+0.0060] dLL +0.0028 [-0.0072,+0.0130] NO DIFFERENCE
   V6   dBrier vs book +0.0011 [-0.0033,+0.0055] dLL +0.0020 [-0.0076,+0.0119] NO DIFFERENCE
   V5o  dBrier vs book +0.0014 [-0.0031,+0.0058] dLL +0.0026 [-0.0074,+0.0125] NO DIFFERENCE
   V7   dBrier vs book +0.0018 [-0.0027,+0.0064] dLL +0.0037 [-0.0064,+0.0141] NO DIFFERENCE
   V7o  dBrier vs book +0.0012 [-0.0031,+0.0056] dLL +0.0025 [-0.0073,+0.0124] NO DIFFERENCE
   V8   dBrier vs book +0.0016 [-0.0029,+0.0061] dLL +0.0032 [-0.0066,+0.0133] NO DIFFERENCE
   V8o  dBrier vs book +0.0011 [-0.0031,+0.0053] dLL +0.0021 [-0.0073,+0.0116] NO DIFFERENCE
   B0   dBrier vs book +0.0017 [-0.0028,+0.0061] dLL +0.0046 [-0.0057,+0.0148] NO DIFFERENCE
   B4   dBrier vs book +0.0016 [-0.0030,+0.0061] dLL +0.0042 [-0.0065,+0.0147] NO DIFFERENCE
OVER @close vs BOOK (n=1083; book Brier 0.2481)
   V0   dBrier vs book +0.0029 [-0.0007,+0.0064] dLL +0.0059 [-0.0014,+0.0132] NO DIFFERENCE
   V1   dBrier vs book +0.0039 [+0.0000,+0.0078] dLL +0.0081 [+0.0001,+0.0160] MODEL WORSE
   V2   dBrier vs book +0.0027 [-0.0006,+0.0060] dLL +0.0055 [-0.0014,+0.0121] NO DIFFERENCE
   V3   dBrier vs book +0.0024 [-0.0008,+0.0055] dLL +0.0049 [-0.0017,+0.0111] NO DIFFERENCE
   V4   dBrier vs book +0.0022 [-0.0010,+0.0051] dLL +0.0044 [-0.0021,+0.0103] NO DIFFERENCE
   V5   dBrier vs book +0.0022 [-0.0010,+0.0051] dLL +0.0044 [-0.0020,+0.0103] NO DIFFERENCE
   V5r  dBrier vs book +0.0019 [-0.0013,+0.0048] dLL +0.0037 [-0.0026,+0.0096] NO DIFFERENCE
   V5c  dBrier vs book +0.0019 [-0.0013,+0.0048] dLL +0.0038 [-0.0026,+0.0096] NO DIFFERENCE
   V6   dBrier vs book +0.0018 [-0.0014,+0.0047] dLL +0.0035 [-0.0028,+0.0095] NO DIFFERENCE
   V5o  dBrier vs book +0.0018 [-0.0013,+0.0047] dLL +0.0037 [-0.0026,+0.0095] NO DIFFERENCE
   V7   dBrier vs book +0.0016 [-0.0015,+0.0046] dLL +0.0033 [-0.0030,+0.0092] NO DIFFERENCE
   V7o  dBrier vs book +0.0009 [-0.0020,+0.0037] dLL +0.0018 [-0.0041,+0.0075] NO DIFFERENCE
   V8   dBrier vs book +0.0012 [-0.0015,+0.0039] dLL +0.0024 [-0.0031,+0.0078] NO DIFFERENCE
   V8o  dBrier vs book +0.0009 [-0.0016,+0.0035] dLL +0.0018 [-0.0034,+0.0070] NO DIFFERENCE
   B0   dBrier vs book +0.0050 [+0.0012,+0.0085] dLL +0.0102 [+0.0024,+0.0174] MODEL WORSE
   B4   dBrier vs book +0.0048 [+0.0014,+0.0079] dLL +0.0096 [+0.0028,+0.0159] MODEL WORSE
TOTAL settled (MAE / bias)
   V0   MAE 1.837 bias +0.112 [-0.028,+0.248] | dMAE vs B4 -0.0063 [-0.0325,+0.0210]
   V1   MAE 1.850 bias +0.272 [+0.131,+0.407] | dMAE vs B4 +0.0065 [-0.0236,+0.0366]
   V2   MAE 1.830 bias -0.121 [-0.264,+0.017] | dMAE vs B4 -0.0142 [-0.0400,+0.0123]
   V3   MAE 1.830 bias -0.084 [-0.227,+0.054] | dMAE vs B4 -0.0141 [-0.0390,+0.0121]
   V4   MAE 1.832 bias -0.016 [-0.159,+0.121] | dMAE vs B4 -0.0121 [-0.0371,+0.0144]
   V5   MAE 1.830 bias -0.051 [-0.193,+0.086] | dMAE vs B4 -0.0134 [-0.0375,+0.0123]
   V5r  MAE 1.829 bias -0.044 [-0.187,+0.092] | dMAE vs B4 -0.0150 [-0.0396,+0.0110]
   V5c  MAE 1.829 bias -0.045 [-0.188,+0.092] | dMAE vs B4 -0.0146 [-0.0388,+0.0109]
   V6   MAE 1.826 bias -0.088 [-0.229,+0.047] | dMAE vs B4 -0.0177 [-0.0424,+0.0082]
   V5o  MAE 1.829 bias -0.040 [-0.182,+0.098] | dMAE vs B4 -0.0143 [-0.0383,+0.0112]
   V7   MAE 1.829 bias -0.080 [-0.222,+0.059] | dMAE vs B4 -0.0146 [-0.0380,+0.0083]
   V7o  MAE 1.826 bias -0.065 [-0.205,+0.073] | dMAE vs B4 -0.0175 [-0.0397,+0.0054]
   V8   MAE 1.827 bias -0.062 [-0.203,+0.075] | dMAE vs B4 -0.0168 [-0.0394,+0.0072]
   V8o  MAE 1.826 bias -0.047 [-0.186,+0.091] | dMAE vs B4 -0.0174 [-0.0400,+0.0067]
   B0   MAE 1.843 bias -0.122 [-0.260,+0.012]
   B4   MAE 1.844 bias -0.036 [-0.176,+0.101]
```

## PLAYOFFS (holdout) (n=82)

```
ML home (freq 0.476; B0 Brier 0.2422 meanP 0.524; B4 0.2418 meanP 0.521)
   V0   Brier 0.2378 meanP 0.524 | vs B0 -0.0044 [-0.0130,+0.0033] NO VERDICT (n=82 < 100) | vs B4 -0.0040 [-0.0117,+0.0028] NO VERDICT (n=82 < 100)
   V1   Brier 0.2378 meanP 0.524 | vs B0 -0.0045 [-0.0129,+0.0033] NO VERDICT (n=82 < 100) | vs B4 -0.0040 [-0.0117,+0.0027] NO VERDICT (n=82 < 100)
   V2   Brier 0.2377 meanP 0.523 | vs B0 -0.0046 [-0.0133,+0.0031] NO VERDICT (n=82 < 100) | vs B4 -0.0042 [-0.0119,+0.0027] NO VERDICT (n=82 < 100)
   V3   Brier 0.2387 meanP 0.520 | vs B0 -0.0036 [-0.0122,+0.0043] NO VERDICT (n=82 < 100) | vs B4 -0.0031 [-0.0109,+0.0037] NO VERDICT (n=82 < 100)
   V4   Brier 0.2387 meanP 0.520 | vs B0 -0.0036 [-0.0122,+0.0043] NO VERDICT (n=82 < 100) | vs B4 -0.0031 [-0.0109,+0.0037] NO VERDICT (n=82 < 100)
   V5   Brier 0.2396 meanP 0.520 | vs B0 -0.0026 [-0.0109,+0.0053] NO VERDICT (n=82 < 100) | vs B4 -0.0022 [-0.0095,+0.0045] NO VERDICT (n=82 < 100)
   V5r  Brier 0.2402 meanP 0.520 | vs B0 -0.0021 [-0.0102,+0.0057] NO VERDICT (n=82 < 100) | vs B4 -0.0016 [-0.0089,+0.0051] NO VERDICT (n=82 < 100)
   V5c  Brier 0.2396 meanP 0.520 | vs B0 -0.0027 [-0.0109,+0.0051] NO VERDICT (n=82 < 100) | vs B4 -0.0022 [-0.0095,+0.0044] NO VERDICT (n=82 < 100)
   V6   Brier 0.2396 meanP 0.520 | vs B0 -0.0027 [-0.0109,+0.0051] NO VERDICT (n=82 < 100) | vs B4 -0.0022 [-0.0095,+0.0044] NO VERDICT (n=82 < 100)
   V5o  Brier 0.2396 meanP 0.520 | vs B0 -0.0026 [-0.0108,+0.0052] NO VERDICT (n=82 < 100) | vs B4 -0.0022 [-0.0094,+0.0045] NO VERDICT (n=82 < 100)
   V7   Brier 0.2431 meanP 0.521 | vs B0 +0.0008 [-0.0071,+0.0088] NO VERDICT (n=82 < 100) | vs B4 +0.0013 [-0.0056,+0.0081] NO VERDICT (n=82 < 100)
   V7o  Brier 0.2432 meanP 0.521 | vs B0 +0.0010 [-0.0069,+0.0089] NO VERDICT (n=82 < 100) | vs B4 +0.0014 [-0.0055,+0.0082] NO VERDICT (n=82 < 100)
   V8   Brier 0.2408 meanP 0.520 | vs B0 -0.0014 [-0.0090,+0.0059] NO VERDICT (n=82 < 100) | vs B4 -0.0010 [-0.0076,+0.0052] NO VERDICT (n=82 < 100)
   V8o  Brier 0.2409 meanP 0.520 | vs B0 -0.0013 [-0.0089,+0.0060] NO VERDICT (n=82 < 100) | vs B4 -0.0009 [-0.0074,+0.0052] NO VERDICT (n=82 < 100)
REG tie (freq 0.268; B0 Brier 0.2085 meanP 0.159; B4 0.1970 meanP 0.250)
   V0   Brier 0.2087 meanP 0.157 | vs B0 +0.0002 [-0.0009,+0.0017] NO VERDICT (n=82 < 100) | vs B4 +0.0117 [-0.0027,+0.0270] NO VERDICT (n=82 < 100)
   V1   Brier 0.2087 meanP 0.157 | vs B0 +0.0002 [-0.0009,+0.0017] NO VERDICT (n=82 < 100) | vs B4 +0.0117 [-0.0027,+0.0270] NO VERDICT (n=82 < 100)
   V2   Brier 0.2076 meanP 0.162 | vs B0 -0.0008 [-0.0019,+0.0004] NO VERDICT (n=82 < 100) | vs B4 +0.0106 [-0.0030,+0.0250] NO VERDICT (n=82 < 100)
   V3   Brier 0.1968 meanP 0.253 | vs B0 -0.0116 [-0.0264,+0.0027] NO VERDICT (n=82 < 100) | vs B4 -0.0002 [-0.0020,+0.0016] NO VERDICT (n=82 < 100)
   V4   Brier 0.1968 meanP 0.253 | vs B0 -0.0116 [-0.0264,+0.0027] NO VERDICT (n=82 < 100) | vs B4 -0.0002 [-0.0020,+0.0016] NO VERDICT (n=82 < 100)
   V5   Brier 0.1975 meanP 0.254 | vs B0 -0.0110 [-0.0258,+0.0035] NO VERDICT (n=82 < 100) | vs B4 +0.0005 [-0.0018,+0.0026] NO VERDICT (n=82 < 100)
   V5r  Brier 0.1974 meanP 0.254 | vs B0 -0.0111 [-0.0260,+0.0031] NO VERDICT (n=82 < 100) | vs B4 +0.0003 [-0.0019,+0.0023] NO VERDICT (n=82 < 100)
   V5c  Brier 0.1976 meanP 0.254 | vs B0 -0.0108 [-0.0259,+0.0035] NO VERDICT (n=82 < 100) | vs B4 +0.0006 [-0.0017,+0.0026] NO VERDICT (n=82 < 100)
   V6   Brier 0.1976 meanP 0.254 | vs B0 -0.0108 [-0.0259,+0.0035] NO VERDICT (n=82 < 100) | vs B4 +0.0006 [-0.0017,+0.0026] NO VERDICT (n=82 < 100)
   V5o  Brier 0.1972 meanP 0.254 | vs B0 -0.0113 [-0.0261,+0.0033] NO VERDICT (n=82 < 100) | vs B4 +0.0002 [-0.0022,+0.0023] NO VERDICT (n=82 < 100)
   V7   Brier 0.1972 meanP 0.256 | vs B0 -0.0113 [-0.0264,+0.0033] NO VERDICT (n=82 < 100) | vs B4 +0.0001 [-0.0023,+0.0022] NO VERDICT (n=82 < 100)
   V7o  Brier 0.1973 meanP 0.256 | vs B0 -0.0112 [-0.0264,+0.0034] NO VERDICT (n=82 < 100) | vs B4 +0.0002 [-0.0023,+0.0023] NO VERDICT (n=82 < 100)
   V8   Brier 0.1976 meanP 0.255 | vs B0 -0.0109 [-0.0257,+0.0035] NO VERDICT (n=82 < 100) | vs B4 +0.0006 [-0.0012,+0.0022] NO VERDICT (n=82 < 100)
   V8o  Brier 0.1977 meanP 0.255 | vs B0 -0.0108 [-0.0257,+0.0035] NO VERDICT (n=82 < 100) | vs B4 +0.0006 [-0.0012,+0.0023] NO VERDICT (n=82 < 100)
REG home (freq 0.305; B0 Brier 0.2319 meanP 0.444; B4 0.2195 meanP 0.397)
   V0   Brier 0.2275 meanP 0.446 | vs B0 -0.0044 [-0.0127,+0.0032] NO VERDICT (n=82 < 100) | vs B4 +0.0080 [-0.0060,+0.0218] NO VERDICT (n=82 < 100)
   V1   Brier 0.2275 meanP 0.446 | vs B0 -0.0044 [-0.0127,+0.0032] NO VERDICT (n=82 < 100) | vs B4 +0.0080 [-0.0060,+0.0218] NO VERDICT (n=82 < 100)
   V2   Brier 0.2262 meanP 0.443 | vs B0 -0.0057 [-0.0139,+0.0018] NO VERDICT (n=82 < 100) | vs B4 +0.0067 [-0.0069,+0.0200] NO VERDICT (n=82 < 100)
   V3   Brier 0.2157 meanP 0.395 | vs B0 -0.0162 [-0.0283,-0.0039] NO VERDICT (n=82 < 100) | vs B4 -0.0039 [-0.0111,+0.0025] NO VERDICT (n=82 < 100)
   V4   Brier 0.2157 meanP 0.395 | vs B0 -0.0162 [-0.0283,-0.0039] NO VERDICT (n=82 < 100) | vs B4 -0.0039 [-0.0111,+0.0025] NO VERDICT (n=82 < 100)
   V5   Brier 0.2166 meanP 0.394 | vs B0 -0.0153 [-0.0275,-0.0027] NO VERDICT (n=82 < 100) | vs B4 -0.0029 [-0.0099,+0.0034] NO VERDICT (n=82 < 100)
   V5r  Brier 0.2171 meanP 0.394 | vs B0 -0.0148 [-0.0270,-0.0020] NO VERDICT (n=82 < 100) | vs B4 -0.0024 [-0.0095,+0.0041] NO VERDICT (n=82 < 100)
   V5c  Brier 0.2167 meanP 0.394 | vs B0 -0.0152 [-0.0276,-0.0025] NO VERDICT (n=82 < 100) | vs B4 -0.0029 [-0.0102,+0.0037] NO VERDICT (n=82 < 100)
   V6   Brier 0.2167 meanP 0.394 | vs B0 -0.0152 [-0.0276,-0.0025] NO VERDICT (n=82 < 100) | vs B4 -0.0029 [-0.0102,+0.0037] NO VERDICT (n=82 < 100)
   V5o  Brier 0.2165 meanP 0.394 | vs B0 -0.0154 [-0.0278,-0.0026] NO VERDICT (n=82 < 100) | vs B4 -0.0030 [-0.0103,+0.0035] NO VERDICT (n=82 < 100)
   V7   Brier 0.2197 meanP 0.394 | vs B0 -0.0123 [-0.0249,+0.0013] NO VERDICT (n=82 < 100) | vs B4 +0.0001 [-0.0074,+0.0077] NO VERDICT (n=82 < 100)
   V7o  Brier 0.2196 meanP 0.394 | vs B0 -0.0123 [-0.0250,+0.0012] NO VERDICT (n=82 < 100) | vs B4 +0.0000 [-0.0074,+0.0076] NO VERDICT (n=82 < 100)
   V8   Brier 0.2180 meanP 0.394 | vs B0 -0.0139 [-0.0262,-0.0010] NO VERDICT (n=82 < 100) | vs B4 -0.0016 [-0.0087,+0.0051] NO VERDICT (n=82 < 100)
   V8o  Brier 0.2179 meanP 0.394 | vs B0 -0.0140 [-0.0263,-0.0010] NO VERDICT (n=82 < 100) | vs B4 -0.0016 [-0.0088,+0.0051] NO VERDICT (n=82 < 100)
PL home -1.5 (freq 0.232; B0 Brier 0.1838 meanP 0.295; B4 0.1846 meanP 0.303)
   V0   Brier 0.1788 meanP 0.297 | vs B0 -0.0050 [-0.0120,+0.0014] NO VERDICT (n=82 < 100) | vs B4 -0.0058 [-0.0120,-0.0001] NO VERDICT (n=82 < 100)
   V1   Brier 0.1788 meanP 0.297 | vs B0 -0.0050 [-0.0120,+0.0014] NO VERDICT (n=82 < 100) | vs B4 -0.0058 [-0.0120,-0.0001] NO VERDICT (n=82 < 100)
   V2   Brier 0.1777 meanP 0.290 | vs B0 -0.0060 [-0.0129,+0.0003] NO VERDICT (n=82 < 100) | vs B4 -0.0068 [-0.0133,-0.0006] NO VERDICT (n=82 < 100)
   V3   Brier 0.1753 meanP 0.259 | vs B0 -0.0085 [-0.0170,+0.0007] NO VERDICT (n=82 < 100) | vs B4 -0.0092 [-0.0181,+0.0006] NO VERDICT (n=82 < 100)
   V4   Brier 0.1791 meanP 0.299 | vs B0 -0.0047 [-0.0121,+0.0020] NO VERDICT (n=82 < 100) | vs B4 -0.0055 [-0.0119,+0.0003] NO VERDICT (n=82 < 100)
   V5   Brier 0.1800 meanP 0.299 | vs B0 -0.0038 [-0.0108,+0.0025] NO VERDICT (n=82 < 100) | vs B4 -0.0046 [-0.0106,+0.0013] NO VERDICT (n=82 < 100)
   V5r  Brier 0.1803 meanP 0.299 | vs B0 -0.0034 [-0.0103,+0.0031] NO VERDICT (n=82 < 100) | vs B4 -0.0042 [-0.0102,+0.0016] NO VERDICT (n=82 < 100)
   V5c  Brier 0.1803 meanP 0.298 | vs B0 -0.0035 [-0.0104,+0.0031] NO VERDICT (n=82 < 100) | vs B4 -0.0043 [-0.0104,+0.0017] NO VERDICT (n=82 < 100)
   V6   Brier 0.1803 meanP 0.298 | vs B0 -0.0035 [-0.0104,+0.0031] NO VERDICT (n=82 < 100) | vs B4 -0.0043 [-0.0104,+0.0017] NO VERDICT (n=82 < 100)
   V5o  Brier 0.1802 meanP 0.298 | vs B0 -0.0036 [-0.0105,+0.0029] NO VERDICT (n=82 < 100) | vs B4 -0.0044 [-0.0105,+0.0015] NO VERDICT (n=82 < 100)
   V7   Brier 0.1803 meanP 0.297 | vs B0 -0.0035 [-0.0092,+0.0026] NO VERDICT (n=82 < 100) | vs B4 -0.0043 [-0.0093,+0.0012] NO VERDICT (n=82 < 100)
   V7o  Brier 0.1803 meanP 0.297 | vs B0 -0.0035 [-0.0092,+0.0026] NO VERDICT (n=82 < 100) | vs B4 -0.0043 [-0.0094,+0.0012] NO VERDICT (n=82 < 100)
   V8   Brier 0.1795 meanP 0.298 | vs B0 -0.0043 [-0.0103,+0.0016] NO VERDICT (n=82 < 100) | vs B4 -0.0050 [-0.0103,+0.0004] NO VERDICT (n=82 < 100)
   V8o  Brier 0.1795 meanP 0.298 | vs B0 -0.0043 [-0.0104,+0.0016] NO VERDICT (n=82 < 100) | vs B4 -0.0051 [-0.0104,+0.0004] NO VERDICT (n=82 < 100)
PL away -1.5 (freq 0.329; B0 Brier 0.2186 meanP 0.253; B4 0.2177 meanP 0.264)
   V0   Brier 0.2164 meanP 0.256 | vs B0 -0.0022 [-0.0094,+0.0050] NO VERDICT (n=82 < 100) | vs B4 -0.0013 [-0.0084,+0.0059] NO VERDICT (n=82 < 100)
   V1   Brier 0.2164 meanP 0.256 | vs B0 -0.0022 [-0.0094,+0.0050] NO VERDICT (n=82 < 100) | vs B4 -0.0013 [-0.0084,+0.0059] NO VERDICT (n=82 < 100)
   V2   Brier 0.2180 meanP 0.250 | vs B0 -0.0006 [-0.0079,+0.0070] NO VERDICT (n=82 < 100) | vs B4 +0.0003 [-0.0069,+0.0079] NO VERDICT (n=82 < 100)
   V3   Brier 0.2239 meanP 0.223 | vs B0 +0.0053 [-0.0047,+0.0160] NO VERDICT (n=82 < 100) | vs B4 +0.0062 [-0.0050,+0.0178] NO VERDICT (n=82 < 100)
   V4   Brier 0.2167 meanP 0.261 | vs B0 -0.0019 [-0.0091,+0.0052] NO VERDICT (n=82 < 100) | vs B4 -0.0010 [-0.0078,+0.0059] NO VERDICT (n=82 < 100)
   V5   Brier 0.2175 meanP 0.261 | vs B0 -0.0011 [-0.0080,+0.0057] NO VERDICT (n=82 < 100) | vs B4 -0.0002 [-0.0065,+0.0064] NO VERDICT (n=82 < 100)
   V5r  Brier 0.2176 meanP 0.261 | vs B0 -0.0009 [-0.0077,+0.0061] NO VERDICT (n=82 < 100) | vs B4 -0.0000 [-0.0063,+0.0068] NO VERDICT (n=82 < 100)
   V5c  Brier 0.2174 meanP 0.261 | vs B0 -0.0011 [-0.0080,+0.0059] NO VERDICT (n=82 < 100) | vs B4 -0.0003 [-0.0066,+0.0066] NO VERDICT (n=82 < 100)
   V6   Brier 0.2174 meanP 0.261 | vs B0 -0.0011 [-0.0080,+0.0059] NO VERDICT (n=82 < 100) | vs B4 -0.0003 [-0.0066,+0.0066] NO VERDICT (n=82 < 100)
   V5o  Brier 0.2174 meanP 0.261 | vs B0 -0.0011 [-0.0080,+0.0058] NO VERDICT (n=82 < 100) | vs B4 -0.0003 [-0.0066,+0.0066] NO VERDICT (n=82 < 100)
   V7   Brier 0.2209 meanP 0.258 | vs B0 +0.0024 [-0.0046,+0.0096] NO VERDICT (n=82 < 100) | vs B4 +0.0032 [-0.0039,+0.0106] NO VERDICT (n=82 < 100)
   V7o  Brier 0.2210 meanP 0.258 | vs B0 +0.0024 [-0.0045,+0.0096] NO VERDICT (n=82 < 100) | vs B4 +0.0033 [-0.0038,+0.0106] NO VERDICT (n=82 < 100)
   V8   Brier 0.2186 meanP 0.259 | vs B0 +0.0001 [-0.0065,+0.0067] NO VERDICT (n=82 < 100) | vs B4 +0.0009 [-0.0054,+0.0076] NO VERDICT (n=82 < 100)
   V8o  Brier 0.2187 meanP 0.260 | vs B0 +0.0001 [-0.0064,+0.0067] NO VERDICT (n=82 < 100) | vs B4 +0.0010 [-0.0053,+0.0076] NO VERDICT (n=82 < 100)
OVER 5.5 (freq 0.561; B0 Brier 0.2501 meanP 0.605; B4 0.2510 meanP 0.608)
   V0   Brier 0.2561 meanP 0.640 | vs B0 +0.0060 [-0.0051,+0.0170] NO VERDICT (n=82 < 100) | vs B4 +0.0051 [-0.0061,+0.0162] NO VERDICT (n=82 < 100)
   V1   Brier 0.2561 meanP 0.640 | vs B0 +0.0060 [-0.0051,+0.0170] NO VERDICT (n=82 < 100) | vs B4 +0.0051 [-0.0061,+0.0162] NO VERDICT (n=82 < 100)
   V2   Brier 0.2503 meanP 0.584 | vs B0 +0.0002 [-0.0104,+0.0103] NO VERDICT (n=82 < 100) | vs B4 -0.0007 [-0.0118,+0.0104] NO VERDICT (n=82 < 100)
   V3   Brier 0.2502 meanP 0.583 | vs B0 +0.0001 [-0.0106,+0.0103] NO VERDICT (n=82 < 100) | vs B4 -0.0007 [-0.0121,+0.0102] NO VERDICT (n=82 < 100)
   V4   Brier 0.2519 meanP 0.608 | vs B0 +0.0018 [-0.0073,+0.0106] NO VERDICT (n=82 < 100) | vs B4 +0.0009 [-0.0085,+0.0102] NO VERDICT (n=82 < 100)
   V5   Brier 0.2532 meanP 0.603 | vs B0 +0.0031 [-0.0051,+0.0113] NO VERDICT (n=82 < 100) | vs B4 +0.0022 [-0.0065,+0.0108] NO VERDICT (n=82 < 100)
   V5r  Brier 0.2522 meanP 0.601 | vs B0 +0.0021 [-0.0058,+0.0102] NO VERDICT (n=82 < 100) | vs B4 +0.0012 [-0.0071,+0.0098] NO VERDICT (n=82 < 100)
   V5c  Brier 0.2522 meanP 0.601 | vs B0 +0.0021 [-0.0058,+0.0101] NO VERDICT (n=82 < 100) | vs B4 +0.0012 [-0.0072,+0.0097] NO VERDICT (n=82 < 100)
   V6   Brier 0.2522 meanP 0.601 | vs B0 +0.0021 [-0.0058,+0.0101] NO VERDICT (n=82 < 100) | vs B4 +0.0012 [-0.0072,+0.0097] NO VERDICT (n=82 < 100)
   V5o  Brier 0.2522 meanP 0.601 | vs B0 +0.0021 [-0.0057,+0.0101] NO VERDICT (n=82 < 100) | vs B4 +0.0012 [-0.0071,+0.0097] NO VERDICT (n=82 < 100)
   V7   Brier 0.2477 meanP 0.584 | vs B0 -0.0024 [-0.0121,+0.0073] NO VERDICT (n=82 < 100) | vs B4 -0.0032 [-0.0132,+0.0069] NO VERDICT (n=82 < 100)
   V7o  Brier 0.2480 meanP 0.585 | vs B0 -0.0021 [-0.0118,+0.0076] NO VERDICT (n=82 < 100) | vs B4 -0.0030 [-0.0130,+0.0071] NO VERDICT (n=82 < 100)
   V8   Brier 0.2483 meanP 0.592 | vs B0 -0.0018 [-0.0105,+0.0067] NO VERDICT (n=82 < 100) | vs B4 -0.0027 [-0.0118,+0.0063] NO VERDICT (n=82 < 100)
   V8o  Brier 0.2484 meanP 0.592 | vs B0 -0.0017 [-0.0104,+0.0067] NO VERDICT (n=82 < 100) | vs B4 -0.0026 [-0.0117,+0.0063] NO VERDICT (n=82 < 100)
OVER 6.5 (freq 0.366; B0 Brier 0.2306 meanP 0.447; B4 0.2386 meanP 0.484)
   V0   Brier 0.2411 meanP 0.485 | vs B0 +0.0106 [-0.0016,+0.0225] NO VERDICT (n=82 < 100) | vs B4 +0.0025 [-0.0062,+0.0116] NO VERDICT (n=82 < 100)
   V1   Brier 0.2546 meanP 0.533 | vs B0 +0.0240 [+0.0016,+0.0438] NO VERDICT (n=82 < 100) | vs B4 +0.0160 [+0.0019,+0.0298] NO VERDICT (n=82 < 100)
   V2   Brier 0.2392 meanP 0.474 | vs B0 +0.0087 [-0.0015,+0.0187] NO VERDICT (n=82 < 100) | vs B4 +0.0006 [-0.0081,+0.0097] NO VERDICT (n=82 < 100)
   V3   Brier 0.2417 meanP 0.485 | vs B0 +0.0111 [-0.0009,+0.0227] NO VERDICT (n=82 < 100) | vs B4 +0.0031 [-0.0053,+0.0118] NO VERDICT (n=82 < 100)
   V4   Brier 0.2417 meanP 0.485 | vs B0 +0.0111 [-0.0009,+0.0227] NO VERDICT (n=82 < 100) | vs B4 +0.0031 [-0.0053,+0.0118] NO VERDICT (n=82 < 100)
   V5   Brier 0.2407 meanP 0.479 | vs B0 +0.0102 [-0.0003,+0.0203] NO VERDICT (n=82 < 100) | vs B4 +0.0021 [-0.0057,+0.0102] NO VERDICT (n=82 < 100)
   V5r  Brier 0.2397 meanP 0.477 | vs B0 +0.0092 [-0.0010,+0.0189] NO VERDICT (n=82 < 100) | vs B4 +0.0011 [-0.0065,+0.0092] NO VERDICT (n=82 < 100)
   V5c  Brier 0.2394 meanP 0.478 | vs B0 +0.0088 [-0.0013,+0.0185] NO VERDICT (n=82 < 100) | vs B4 +0.0008 [-0.0069,+0.0091] NO VERDICT (n=82 < 100)
   V6   Brier 0.2394 meanP 0.478 | vs B0 +0.0088 [-0.0013,+0.0185] NO VERDICT (n=82 < 100) | vs B4 +0.0008 [-0.0069,+0.0091] NO VERDICT (n=82 < 100)
   V5o  Brier 0.2395 meanP 0.478 | vs B0 +0.0089 [-0.0012,+0.0186] NO VERDICT (n=82 < 100) | vs B4 +0.0009 [-0.0068,+0.0092] NO VERDICT (n=82 < 100)
   V7   Brier 0.2346 meanP 0.460 | vs B0 +0.0041 [-0.0051,+0.0133] NO VERDICT (n=82 < 100) | vs B4 -0.0040 [-0.0148,+0.0070] NO VERDICT (n=82 < 100)
   V7o  Brier 0.2348 meanP 0.460 | vs B0 +0.0042 [-0.0050,+0.0134] NO VERDICT (n=82 < 100) | vs B4 -0.0038 [-0.0145,+0.0070] NO VERDICT (n=82 < 100)
   V8   Brier 0.2364 meanP 0.468 | vs B0 +0.0058 [-0.0031,+0.0144] NO VERDICT (n=82 < 100) | vs B4 -0.0022 [-0.0110,+0.0065] NO VERDICT (n=82 < 100)
   V8o  Brier 0.2364 meanP 0.468 | vs B0 +0.0059 [-0.0030,+0.0145] NO VERDICT (n=82 < 100) | vs B4 -0.0022 [-0.0110,+0.0065] NO VERDICT (n=82 < 100)
ML vs BOOK (n=82; book Brier 0.2367)
   V0   dBrier vs book +0.0011 [-0.0079,+0.0100] dLL +0.0030 [-0.0154,+0.0214] NO VERDICT (n=82 < 100)
   V1   dBrier vs book +0.0010 [-0.0079,+0.0100] dLL +0.0030 [-0.0155,+0.0215] NO VERDICT (n=82 < 100)
   V2   dBrier vs book +0.0009 [-0.0082,+0.0101] dLL +0.0028 [-0.0158,+0.0216] NO VERDICT (n=82 < 100)
   V3   dBrier vs book +0.0019 [-0.0071,+0.0113] dLL +0.0048 [-0.0141,+0.0240] NO VERDICT (n=82 < 100)
   V4   dBrier vs book +0.0019 [-0.0071,+0.0113] dLL +0.0048 [-0.0141,+0.0240] NO VERDICT (n=82 < 100)
   V5   dBrier vs book +0.0029 [-0.0065,+0.0126] dLL +0.0068 [-0.0127,+0.0267] NO VERDICT (n=82 < 100)
   V5r  dBrier vs book +0.0034 [-0.0061,+0.0134] dLL +0.0079 [-0.0115,+0.0284] NO VERDICT (n=82 < 100)
   V5c  dBrier vs book +0.0028 [-0.0067,+0.0129] dLL +0.0067 [-0.0130,+0.0274] NO VERDICT (n=82 < 100)
   V6   dBrier vs book +0.0028 [-0.0067,+0.0129] dLL +0.0067 [-0.0130,+0.0274] NO VERDICT (n=82 < 100)
   V5o  dBrier vs book +0.0029 [-0.0066,+0.0130] dLL +0.0068 [-0.0128,+0.0276] NO VERDICT (n=82 < 100)
   V7   dBrier vs book +0.0064 [-0.0046,+0.0180] dLL +0.0138 [-0.0088,+0.0380] NO VERDICT (n=82 < 100)
   V7o  dBrier vs book +0.0065 [-0.0045,+0.0182] dLL +0.0140 [-0.0086,+0.0380] NO VERDICT (n=82 < 100)
   V8   dBrier vs book +0.0041 [-0.0064,+0.0151] dLL +0.0092 [-0.0123,+0.0318] NO VERDICT (n=82 < 100)
   V8o  dBrier vs book +0.0042 [-0.0063,+0.0152] dLL +0.0094 [-0.0122,+0.0319] NO VERDICT (n=82 < 100)
   B0   dBrier vs book +0.0055 [-0.0044,+0.0159] dLL +0.0115 [-0.0087,+0.0328] NO VERDICT (n=82 < 100)
   B4   dBrier vs book +0.0051 [-0.0047,+0.0155] dLL +0.0108 [-0.0092,+0.0322] NO VERDICT (n=82 < 100)
PL home @book line vs BOOK (n=82; book Brier 0.2182)
   V0   dBrier vs book -0.0076 [-0.0173,+0.0023] dLL -0.0170 [-0.0377,+0.0045] NO VERDICT (n=82 < 100)
   V1   dBrier vs book -0.0076 [-0.0173,+0.0023] dLL -0.0170 [-0.0377,+0.0045] NO VERDICT (n=82 < 100)
   V2   dBrier vs book -0.0079 [-0.0187,+0.0034] dLL -0.0175 [-0.0411,+0.0072] NO VERDICT (n=82 < 100)
   V3   dBrier vs book -0.0067 [-0.0228,+0.0101] dLL -0.0148 [-0.0501,+0.0234] NO VERDICT (n=82 < 100)
   V4   dBrier vs book -0.0076 [-0.0173,+0.0026] dLL -0.0169 [-0.0382,+0.0050] NO VERDICT (n=82 < 100)
   V5   dBrier vs book -0.0071 [-0.0175,+0.0038] dLL -0.0155 [-0.0378,+0.0080] NO VERDICT (n=82 < 100)
   V5r  dBrier vs book -0.0062 [-0.0166,+0.0047] dLL -0.0135 [-0.0360,+0.0100] NO VERDICT (n=82 < 100)
   V5c  dBrier vs book -0.0063 [-0.0166,+0.0046] dLL -0.0139 [-0.0361,+0.0097] NO VERDICT (n=82 < 100)
   V6   dBrier vs book -0.0063 [-0.0166,+0.0046] dLL -0.0139 [-0.0361,+0.0097] NO VERDICT (n=82 < 100)
   V5o  dBrier vs book -0.0064 [-0.0168,+0.0045] dLL -0.0141 [-0.0364,+0.0095] NO VERDICT (n=82 < 100)
   V7   dBrier vs book -0.0065 [-0.0177,+0.0062] dLL -0.0142 [-0.0387,+0.0135] NO VERDICT (n=82 < 100)
   V7o  dBrier vs book -0.0065 [-0.0177,+0.0062] dLL -0.0143 [-0.0388,+0.0135] NO VERDICT (n=82 < 100)
   V8   dBrier vs book -0.0074 [-0.0181,+0.0040] dLL -0.0164 [-0.0393,+0.0086] NO VERDICT (n=82 < 100)
   V8o  dBrier vs book -0.0075 [-0.0181,+0.0040] dLL -0.0165 [-0.0394,+0.0085] NO VERDICT (n=82 < 100)
   B0   dBrier vs book -0.0061 [-0.0158,+0.0046] dLL -0.0135 [-0.0350,+0.0103] NO VERDICT (n=82 < 100)
   B4   dBrier vs book -0.0057 [-0.0145,+0.0039] dLL -0.0125 [-0.0318,+0.0089] NO VERDICT (n=82 < 100)
OVER @close vs BOOK (n=72; book Brier 0.2467)
   V0   dBrier vs book +0.0261 [+0.0034,+0.0510] dLL +0.0553 [+0.0080,+0.1085] NO VERDICT (n=72 < 100)
   V1   dBrier vs book +0.0285 [+0.0028,+0.0543] dLL +0.0611 [+0.0072,+0.1170] NO VERDICT (n=72 < 100)
   V2   dBrier vs book +0.0169 [+0.0016,+0.0339] dLL +0.0354 [+0.0033,+0.0711] NO VERDICT (n=72 < 100)
   V3   dBrier vs book +0.0170 [+0.0014,+0.0339] dLL +0.0358 [+0.0032,+0.0715] NO VERDICT (n=72 < 100)
   V4   dBrier vs book +0.0207 [+0.0026,+0.0410] dLL +0.0437 [+0.0052,+0.0862] NO VERDICT (n=72 < 100)
   V5   dBrier vs book +0.0213 [+0.0038,+0.0408] dLL +0.0447 [+0.0083,+0.0861] NO VERDICT (n=72 < 100)
   V5r  dBrier vs book +0.0199 [+0.0028,+0.0384] dLL +0.0415 [+0.0060,+0.0811] NO VERDICT (n=72 < 100)
   V5c  dBrier vs book +0.0199 [+0.0030,+0.0384] dLL +0.0416 [+0.0062,+0.0808] NO VERDICT (n=72 < 100)
   V6   dBrier vs book +0.0199 [+0.0030,+0.0384] dLL +0.0416 [+0.0062,+0.0808] NO VERDICT (n=72 < 100)
   V5o  dBrier vs book +0.0199 [+0.0030,+0.0384] dLL +0.0416 [+0.0062,+0.0810] NO VERDICT (n=72 < 100)
   V7   dBrier vs book +0.0146 [+0.0012,+0.0299] dLL +0.0299 [+0.0025,+0.0619] NO VERDICT (n=72 < 100)
   V7o  dBrier vs book +0.0149 [+0.0013,+0.0304] dLL +0.0305 [+0.0027,+0.0626] NO VERDICT (n=72 < 100)
   V8   dBrier vs book +0.0157 [+0.0016,+0.0315] dLL +0.0324 [+0.0034,+0.0652] NO VERDICT (n=72 < 100)
   V8o  dBrier vs book +0.0158 [+0.0017,+0.0316] dLL +0.0326 [+0.0035,+0.0653] NO VERDICT (n=72 < 100)
   B0   dBrier vs book +0.0187 [+0.0037,+0.0354] dLL +0.0385 [+0.0077,+0.0724] NO VERDICT (n=72 < 100)
   B4   dBrier vs book +0.0213 [+0.0039,+0.0389] dLL +0.0440 [+0.0081,+0.0804] NO VERDICT (n=72 < 100)
TOTAL settled (MAE / bias)
   V0   MAE 1.748 bias +0.649 [+0.204,+1.068] | dMAE vs B4 +0.0123 [-0.0472,+0.0716]
   V1   MAE 1.799 bias +0.806 [+0.362,+1.225] | dMAE vs B4 +0.0634 [-0.0175,+0.1399]
   V2   MAE 1.697 bias +0.429 [-0.016,+0.851] | dMAE vs B4 -0.0391 [-0.0966,+0.0173]
   V3   MAE 1.703 bias +0.461 [+0.015,+0.882] | dMAE vs B4 -0.0331 [-0.0872,+0.0210]
   V4   MAE 1.721 bias +0.539 [+0.094,+0.961] | dMAE vs B4 -0.0150 [-0.0661,+0.0357]
   V5   MAE 1.714 bias +0.504 [+0.058,+0.923] | dMAE vs B4 -0.0221 [-0.0697,+0.0269]
   V5r  MAE 1.708 bias +0.495 [+0.048,+0.914] | dMAE vs B4 -0.0284 [-0.0763,+0.0201]
   V5c  MAE 1.705 bias +0.495 [+0.048,+0.913] | dMAE vs B4 -0.0306 [-0.0786,+0.0184]
   V6   MAE 1.705 bias +0.495 [+0.048,+0.913] | dMAE vs B4 -0.0306 [-0.0786,+0.0184]
   V5o  MAE 1.706 bias +0.495 [+0.049,+0.913] | dMAE vs B4 -0.0301 [-0.0783,+0.0187]
   V7   MAE 1.671 bias +0.385 [-0.053,+0.791] | dMAE vs B4 -0.0651 [-0.1312,+0.0046]
   V7o  MAE 1.672 bias +0.386 [-0.052,+0.791] | dMAE vs B4 -0.0640 [-0.1293,+0.0052]
   V8   MAE 1.683 bias +0.432 [-0.013,+0.844] | dMAE vs B4 -0.0534 [-0.1076,+0.0040]
   V8o  MAE 1.683 bias +0.433 [-0.012,+0.844] | dMAE vs B4 -0.0527 [-0.1063,+0.0040]
   B0   MAE 1.697 bias +0.410 [-0.042,+0.820]
   B4   MAE 1.736 bias +0.542 [+0.087,+0.953]
```

