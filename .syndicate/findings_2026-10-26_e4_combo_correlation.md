# FINDINGS -- E4: does the sims' JOINT distribution predict same-game co-occurrence better than independence? (lane `e4-combo-correlation`, 2026-10-26)

Decision Engine plan §4 **E4** and §2 **P7**. OFFLINE and read-only on production: fleet `~/syndicate-prod/data`
at nice 19, public outcome GETs (StatsAPI, ESPN), and Kalshi's PUBLIC market API. No deploy, restart or env edit.
No LLM.

- **Pre-registration:** `.syndicate/findings_2026-10-26_e4_combo_correlation_preregistration.md`, committed
  **`9f8d759e` (22:34Z)** before any sim x market x outcome join.
- **Amendments:** A1 **`83f2e460`** (22:36Z): market marginals from `book_quotes`. `closing_lines` turned out to be a
  best-price-per-side ledger, not per-book pairs. A2 **`f5a503c6`** (22:43Z): implementation choices, committed
  with the code. Both were committed before any join.
- **Code:** `scripts/e4_combo_correlation.py`. Tests: `tests/test_e4_combo_correlation.py`, 23 hermetic tests,
  including the reachability test and recovery of a known covariance through the real NBA calibration widening.
- **Run:** 2026-10-26 22:44:06Z -> 22:49:31Z (the report's `run_at` and the file's mtime). 383 public outcome GETs,
  11 failed.
- **Raw output (scratch, not in git):**
  - `C:\tmp\e4\report.json`, `C:\tmp\e4\report.pairs.csv` (55,203 pairs), `C:\tmp\e4\run1.log`;
  - the Kalshi probes: `kalshi_collections.json`, `kalshi_mve_markets.jsonl` / `kalshi_mve_markets2.jsonl`,
    `kprobe*.py`, `kenum*.py`, `ktr.py`;
  - the NBA independence check `nbachk.py`.

## Verdict

**Registered verdict: PASS_TO_STAGE_2, Holm across 7 primary cells, for 4 cells.** Those are MLB same-batter
nested, MLB same-batter other, NBA same-player nested and soccer result/total/BTTS. **Stage 2 was NOT RUN.**

- Kalshi's combo prints are public, and same-game legs do occur inside them.
- But the window holds millions of public trades, more than 30,000 in one 10-minute Sunday slice. Reconstructing
  them after the fact is not feasible by paging.
- In the slices that were enumerated, no 2-leg combo maps onto a passing cell. See the Stage 2 section.
- The E4 kill rule is not met for those 4 cells, so E4 is **not killed there. Its edge question is open, and it is
  owed to a forward capture.**

**What that means, read as the registration said it must be read:**

- **The sims' correlation beats independence only where the dependence is structural:**
  - same-player legs that imply or share each other (hits/TB/RBI; PTS with PR/PRA);
  - soccer BTTS with the total.
- **Where the platform already has a MEASURED copula (the SGP builders' box-score cells), the sim never beats it.**
  - MLB nested: the copula is better than the sim. `D_bc` +0.0052 [+0.0009, +0.0095].
  - MLB other: tie. `D_bc` -0.0081 [-0.0223, +0.0062].
  - NBA nested: tie. `D_bc` +0.0101 [-0.0010, +0.0213].
  - NBA same-player, non-nested: the copula is better than the sim. `D_bc` +0.0114 [+0.0028, +0.0200].
- **The sims' correlation is KILLED for every cross-player cell** (MLB teammates and opponents) **and for NBA
  same-player P x R / P x A / R x A.** There, the NBA sim carries ZERO within-player correlation against a realised
  +0.22. That is an engine defect, confirmed independently below.
- **So the SIM is not the correlation source a combo edge would come from.**
  - Where the sim is right, the dependence is structural and a measured copula prices it as well or better.
  - Where the sim would have to add information (cross-player, non-nested same-player), it adds none or is wrong.
- **Whether Kalshi's combo prices embed that structural correlation, or price legs as independent plus a haircut, is
  the open question.** It is unmeasured.
  - If Kalshi prices independence plus a haircut, the edge would come from the measured copula and from the soccer
    scoreline sim, not from the player sims.

| Cell (primary) | Pairs / games / dates | `D_ba` (b - a), nats/pair [95% CI] | Holm | `D_ca` (copula - a) | `D_bc` (sim - copula) | Verdict |
|---|---|---|---|---|---|---|
| MLB SP-nested | 747 / 22 / 18 | **-0.258** [-0.339, -0.177] | pass | -0.263 [-0.346, -0.181] | **+0.0052 [+0.0009, +0.0095]** (copula better) | PASS; the sim loses to the copula |
| MLB SP-other | 843 / 22 / 18 | **-0.077** [-0.106, -0.049] | pass | -0.069 [-0.110, -0.029] | -0.0081 [-0.0223, +0.0062] | PASS; ties the copula |
| MLB TM (teammates) | 18,772 / 22 / 18 | +0.00002 [-0.0016, +0.0016] | -- | +0.0001 [-0.0017, +0.0019] | -0.0001 [-0.0007, +0.0006] | **KILLED** (underpowered: the copula is null too) |
| MLB OP (opponents) | 21,006 / 22 / 18 | +0.0005 [-0.0001, +0.0012] | -- | +0.0000 | +0.0005 [-0.0001, +0.0011] | **KILLED** |
| NBA SP-disjoint | 2,657 / 40 / 5 | +0.0009 [-0.0028, +0.0046] | -- | **-0.0105 [-0.0176, -0.0034]** | **+0.0114 [+0.0028, +0.0200]** | **KILLED, POWERED**: the copula finds the correlation and the sim does not |
| NBA SP-nested | 6,523 / 40 / 5 | **-0.191** [-0.203, -0.178] | pass | -0.148 (1,236 pairs) | +0.0101 [-0.0010, +0.0213] | PASS; ties the copula |
| Soccer GL | 2,007 / 289 / 17 | **-0.031** [-0.039, -0.024] | pass | no copula | -- | PASS |

`D` is the mean 4-cell log-loss difference per pair. Negative means the first arm is better. The game-clustered
(CR1) CIs are 95%, unadjusted. Holm p-values: MLB nested 3.7e-10, MLB other 8.4e-8, NBA nested 2.1e-204, soccer
1.3e-16; the other three enter as p = 1. 4-cell Brier differences agree in sign and significance in every primary
cell (report `B_ba`).

## What it rests on (CLAUDE.md coverage rule)

| Source | Coverage in the window (09-30 .. 10-25) |
|---|---|
| MLB frozen pregame sims (`sims_pregame`, `sim.joint`) | 19 dates, 10-03..10-24 (postseason only; the joint has existed since 09-04 but frozen copies only from 10-03) |
| NBA smart-sim files | 20 dates, 10-03..10-25 (all `n_sims` = 100 among the files that survived) |
| Soccer pre-kickoff frozen sims | 17 dates, 09-30..10-25, 10 leagues |
| `book_quotes` | mlb 20 dates, nba 20, soccer 26 |
| **Intersection (sim and market)** | **MLB 18 dates, NBA 20, soccer 17** |
| Outcomes | MLB `feed_live` (fleet) else StatsAPI; NBA and soccer from ESPN summaries |

**The n each result rests on:**
- **MLB:** 22 games over 18 dates.
- **NBA:** 40 games over 5 dates, 10-21..10-25. Every surviving game is regular season, so the registered preseason
  secondary cell is EMPTY.
- **Soccer:** 289 matches over 17 dates.

**Funnel:**
- **MLB:**
  - 32 sim files → 23 games. Lost: 5 frozen at or after first pitch, 3 unmatched, 1 ambiguous.
  - 1,427 legs; 93 voided (0 PA); 35 players unmatched; 166 pairs with an undefined joint.
- **NBA:**
  - 99 files → 41 games. Lost: 28 files of the old shape with no player rows, 15 unmatched to a book event,
    11 with no ESPN outcome, 4 written at or after tip.
  - 3,399 legs.
  - Player covariance: 993 OK, 89 failed the PRA identity gate, 26 had a non-positive variance.
- **Soccer:** 319 frozen matches → 289. Lost: 28 unmatched, 2 not completed.
- **Market:**
  - De-vigged medians over sportsbooks only.
  - Venues excluded: 64,744 MLB / 15,726 NBA / 78,076 soccer quote rows.
  - In-play rows excluded: 182,196 / 556,159 / 323,942.
  - Median age of the last pregame quote at the start: MLB 119 min, NBA 126 min, soccer 36 min. These are
    change-log records, and an unchanged quote has no newer row.

## Secondary cells (reported, not gated)

| Cell | Pairs / games | `D_ba` [95% CI] | Read |
|---|---|---|---|
| MLB batter x own-team win (composed, equal variance) | 1,380 / 22 | **-0.0120 [-0.0215, -0.0026]** | LEAD. The sim's batter x team-win sign is informative. It is not gated. |
| MLB batter x game total (composed) | 1,268 / 20 | -0.0036 [-0.0151, +0.0078] | null |
| Soccer BTTS x total | 285 / 285 | -0.138 [-0.198, -0.078] | near-structural (BTTS needs >= 2 goals) |
| Soccer BTTS x result | 855 / 285 | -0.017 [-0.032, -0.003] | small, real |
| Soccer result x total | 867 / 289 | -0.010 [-0.023, +0.003] | null at n |
| Soccer, odds-ratio re-anchor instead of tetrachoric | 2,007 / 289 | -0.031 [-0.039, -0.024] | same as the primary |
| (b-pooled), the sim's leave-one-date-out STRUCTURAL rho, vs per-game rho | every cell | `D_b - D_bpooled` within +/-0.008 and its CI spans 0, except MLB SP-other (-0.0076 [-0.0128, -0.0024]) and the MLB own-win composite | Per-game sim variation adds nothing measurable over one pooled rho per stat pair, except a little on MLB same-batter pairs. |
| NBA 500-draw files | 0 | -- | none survived the funnel |

## Stage 2 -- NOT RUN: the prices are public, but reconstructing the window after the fact is infeasible (registered §7)

The probes ran 2026-10-26 between 22:50Z and 23:47Z, read from the clock. All of them were PUBLIC GETs.

- **Combos are public.**
  - Kalshi lists **1,406** combo collections.
  - Each combo market carries its legs (`mve_selected_legs`), its result and `volume_fp`.
  - Trade prints are public through `/markets/trades`.
- **Same-game legs exist inside Kalshi combos.**
  - Within the 210,984 cross-category combo markets enumerated (below), tickets holding at least one same-game pair
    of legs: WTA 6,922, NBA 2,353, NFL 1,939, Liga MX 787, NHL 599, **MLB 557**, La Liga 414, EPL 251,
    **Serie A 202**, NCAAF 58.
  - Almost all of them are multi-leg parlays. Only **20** are 2-leg same-game combos, all WTA tennis.
  - A multi-leg ticket's price embeds its other legs, so it is not a pair-level price (the registered unit).
- **What was enumerated:**
  1. `KXMVENBASINGLEGAME`, complete for closes 09-30..10-26 12:00Z. It holds **569** same-game combos, all NBA
     **preseason** (10-03..10-07):
     - spread x total: 345;
     - winner x total: 204;
     - winner x spread x total: 16;
     - winner x spread: 4.

     These collections had 3 events and no player props. Side x total is registered NOT TESTABLE, because no sim
     persists a (margin, total) joint, and it is not a passing cell.
  2. `KXMVECROSSCATEGORY`: **210,984** markets, newest first. They cover closes **10-26 06:23Z..12:00Z only**, about
     35,000 per hour of close time. My own 50-minute cap stopped the run there. The window's 26 days would be
     millions of markets.
  3. `/markets/trades`: one **10-minute slice (10-18 18:00Z)** held more than 30,000 trades, not exhausted at 30
     pages; 8,502 of them (28%) were combo trades.
- **Why the window cannot be reconstructed by paging.** Rebuilding it from public trades needs tens of thousands of
  GETs against a public API. That is neither proportionate nor polite.
  - A targeted lookup (combo ticker from a set of legs) exists in Kalshi's docs. It was NOT verified here, either for
    being public or for its history.
- **Polymarket:** no combo capture exists.
- **Consequence:**
  - The 4 passing cells have NO price test.
  - The SGP builders' 18.5% "haircut", and Kalshi's real treatment of same-game correlation, both stay unmeasured.
  - **E4's edge question is open, not answered.**
  - The cheapest honest path is a forward capture (Recommendation 3).

## c-ledger -- the SGP builders' consistency posterior, on the tickets as recorded (descriptive)

Binary "every leg won" outcome. `D` is the log-loss difference; negative means the ledger's `p_joint` is better.

| Sport | Settled / games | Hit rate vs `p_joint` | `p_joint` vs ledger `p_independent` | `p_joint` vs product of `p_market` (all-over tickets) |
|---|---|---|---|---|
| NHL | 601 / 63 | 19.5% vs **22.8%** | +0.0042 [-0.0027, +0.0112] | -0.0072 [-0.0231, +0.0086] (409) |
| NBA | 226 / 31 | 42.0% vs 45.0% | +0.0082 [-0.0067, +0.0231] | +0.0053 [-0.0331, +0.0438] (226) |
| NFL | 149 / 23 | 26.2% vs **32.0%** | -0.0076 [-0.0351, +0.0199] | -0.0242 [-0.0755, +0.0271] (70) |
| WNBA | 32 / 4 | 43.8% vs 48.4% | +0.0010 [-0.0067, +0.0086] | +0.0014 [-0.0925, +0.0953] (32) |
| MLB | 22 / 5 | 54.5% vs 46.7% | -0.029 [-0.083, +0.026] | -0.031 [-0.113, +0.051] |

**CORRECTED 2026-10-27** (lane `sgp-pjoint-calibration`, `cbf05bec`, prereg `1e7793e3`): the 3-6 point gap is NOT a `p_joint` miscalibration. It is grader censoring. `grade_sgp_paper` scores a ticket with an unresolved leg as lost when another leg lost, but never as won. Censoring alone adds +2.4 [+1.3, +3.5] points pooled and +4.3 in NHL (488 of 493 pending legs carry no `player_id`). On tickets where every leg resolved (971 / 139 games), `p_joint` is NOT shown miscalibrated: pooled +1.7 points [-3.1, +6.4], and Holm rejects nothing. The table above is as-graded and inherits the censoring. Fixes: `#743`.

**Read:**
- The posterior is not shown better than plain market independence in any sport.
- ~~It over-predicts the joint hit rate by 3-6 points in NHL, NBA and NFL.~~ Grader censoring; see CORRECTED above.
- The copula adds nothing measurable on these tickets, which are mostly cross-player.
- This agrees with E4's primary cells: cross-player correlation is too small to see at these n.

## ENGINE READ -- which correlations the sims get right or wrong (input for the sim owners)

Realised `rho` is the MLE of one rho per cell or stat pair at the market marginals, with a game-bootstrap CI over
500 resamples. The grid is capped at ±0.95, so a value of 0.95 means "at least that".

**NBA (smart-sim): within-player P / R / A are INDEPENDENT in the sim. This is a defect, and it is confirmed two
ways.**
- **Backed out of the ladders**, against the realised and copula `rho`:

  | Stat pair | Sim | Realised [CI] | Copula |
  |---|---|---|---|
  | PTS x REB | +0.014 | +0.27 [+0.16, +0.38] | +0.236 |
  | AST x PTS | -0.043 | +0.08 | +0.150 |
  | AST x REB | +0.024 | +0.15 | +0.184 |
  | PA x REB | +0.021 | +0.33 | +0.256 |
  | PTS x RA | -0.016 | +0.28 | +0.223 |

- **Post hoc, with no back-out at all:** in 846 player-games with >= 15 sim minutes, the sim's
  `Var(PRA) / [Var(P) + Var(R) + Var(A)]` has median **0.997** (p10-p90 0.90-1.11). It reads 1.0 exactly when
  the parts are uncorrelated. Real box scores (`boxscores_history`, 17 players with >= 15 games at >= 15 MIN) read
  **1.196**.
- **The likely mechanism:**
  - The scenario-calibration study found sim minutes are an INPUT held constant across draws (S10,
    `findings_2026-10-06_basketball_scenario_calibration.md`).
  - Minutes variation is the common driver of a player's points, boards and assists. Hold minutes fixed and the
    three come out independent.
- **What to fix:**
  - Draw minutes per draw, or a per-draw usage/pace shock.
  - Then re-run this script: `off != on` on SP-disjoint, then `D_bc`.
- **Consequences:**
  - The NBA same-player nested cell "passes" only because nesting is arithmetic: PTS sits inside PR whatever the
    covariance.
  - The SGP pool's `p_sim` gate for PR/PA/RA already uses a Normal that assumes independent parts. That matches the
    sim and is wrong in the same direction.
- 100 draws per game adds ±0.1 of noise to each per-game `rho`. The (b-pooled) arm shows per-game variation buys
  nothing, so the mean is the issue, not the noise.

**MLB (`sim.joint`): right on same-batter direction, too low for rare events, and a small cross-team sign error.**

- **Same batter.** Sim vs copula vs realised:

  | Stat pair | Sim | Copula | Realised |
  |---|---|---|---|
  | hits x RBI | +0.48 | +0.66 | +0.62 [+0.51, +0.75] |
  | TB x RBI | +0.59 | +0.73 | +0.61 |
  | hits x TB | +0.939 | +0.950 | >= 0.95 |
  | HR x RBI | +0.56 | +0.95 | >= 0.95 (5 games) |
  | HR x TB | +0.48 | +0.95 | +0.80 |
  | HR x hits | +0.31 | +0.64 | +0.63 |

  - The sim is too low on every HR pair, and that is what makes the copula beat it on nested pairs.
  - **Cause:** `2·sin(pi·rho_S/6)` maps a Spearman of COUNTS. For a zero-inflated count like HR, ties attenuate
    `rho_S`, so the latent threshold correlation is understated.
  - **Fix:** publish the per-draw indicator correlation, or the 2x2 at the traded line, for same-batter pairs.
    `threshold_correlation.py` already notes the conversion is an approximation.
- **Teammates.**
  - Sim +0.07, copula +0.078, realised +0.03 [-0.03, +0.10]. All three are consistent.
  - The effect is ~1e-4 nats/pair, far below what 22 games resolve. The SGP studies needed thousands of games.
  - KILLED by the registered rule, but that is "not shown", not "shown zero".
- **Opponents.**
  - Sim +0.014, realised -0.04 [-0.10, +0.03].
  - On hits x hits the sim is WORSE than independence: +0.0012 [+0.0003, +0.0022].
  - The sim's shared run environment (park, weather, umpire) makes opposing batters move together. Once the
    marginals come from the market lines, that environment is already in the price.
  - **Fix:** with market-anchored marginals, the residual cross-team rho should be ~0. The copula has 0.001.
- **Batter x own-team win** (composed; secondary): informative, -0.012 nats. The joint lacks a `team|full|margin`
  and `team|full|total` label, so this needs an equal-variance composition.
  - **Fix:** add those two labels to `sim.joint`. They cost one column each, and they would make player x winner
    and player x total testable without assumptions.
- **Pitchers are not in the joint.** Pitcher Ks x anything is unreachable.

**Soccer (scoreline table): dependence is well calibrated.**

| Pair | Sim | Realised (289 matches) |
|---|---|---|
| BTTS x over | +0.76 | +0.75 [+0.63, +0.85] |
| BTTS x draw | +0.435 | +0.43 |
| BTTS x home | -0.22 | -0.16 |
| BTTS x away | -0.12 | -0.23 |
| draw x over | -0.27 | -0.24 |
| home x over | +0.14 | +0.18 |

- No engine change is indicated.
- The odds-ratio re-anchor gives the same answer as the tetrachoric one.

**Gaps (registered NOT TESTABLE; for the owners, not results):**
- No sport persists a (margin, total) joint. Basketball's `score.dist` and football's smartsim2 keep margin and total
  separately; MLB keeps 50 score samples. So **side x total cannot be priced from any sim artifact.** It is the only
  2-leg same-game combo type found in Kalshi's NBA single-game series in the window (569 preseason combos).
- NHL persists no joint at all: per-sim player samples are discarded (`player_props.py:133-150`), and no
  goals table or SD is saved.
- NBA saves no cross-player and no player x team joint.
- NFL and NCAAF player props do not come from the sim.

## Recommendation

1. **Do not build an E4 combo strategy now.**
   - On realised outcomes, the sims' correlation is never better than the measured copula where one exists.
   - It adds nothing on cross-player pairs.
   - It is wrong on NBA within-player pairs.
   - No venue price test exists yet.
2. **Assign correlation sources per pair type (skill registry, P5). Every line stays its own decision.**
   - **Same-player pairs:** the measured SGP copula (c), not the sim.
   - **Soccer result/total/BTTS:** the sim's scoreline table. It is calibrated, and no measured copula exists for it.
   - **Cross-player:** independence until a measured cell clears its own CI.
   - **The "sim shape" expert's correlation weight:** stays **0** on MLB TM/OP and NBA SP-disjoint. It may earn
     weight on soccer GL and MLB batter x own-team win only after a venue-price test.
   - Nothing here switches a market, family or sport on or off.
3. **Capture Kalshi combos forward. It is public and read-only, and it is the only way Stage 2 becomes runnable.**
   - **What:** poll `/markets?series_ticker=KXMVECROSSCATEGORY` (and its `0` shard and the single-game series)
     by close time.
     - Keep ONLY combos that contain a same-game pair from a sport the platform simulates or prices.
     - Store each one's legs, `last_price`, `volume_fp` and result.
     - Fetch `/markets/trades` only for kept combos with volume > 0.
   - **Scale, from the measured rate of ~35,000 cross-category closes per hour:** about 35 list GETs per hour plus the
     trades GETs. That is roughly 1,000 GETs a day, at nice 19.
   - **Why:**
     - Same-game soccer legs (Serie A, La Liga, EPL, Liga MX), MLB, NBA and NHL legs already appear inside Kalshi
       combos.
     - This is the only way to measure whether Kalshi prices same-game correlation or independence plus a haircut,
       and it would replace the SGP ledger's assumed 18.5%.
   - **Owner:** the L0 evidence-store work (plan §3, "store Kalshi trade prints").
   - This is a user decision.
4. **Engine work goes to the sim owners. Each item comes with this script as the reachability and correctness
   test.**
   - **NBA:** per-draw minutes. This is the largest item.
   - **MLB:** a threshold-correct same-batter correlation for HR, and `team|full|margin` / `team|full|total` joint
     labels.
   - **All sports:** persist a (margin, total) joint, so winner/spread x total combos become testable.
   - **NHL:** persist any player joint.
5. **Re-run** after either a month of Kalshi combo capture or the NBA minutes fix, whichever comes first. Use the same
   script and the same constants. An MLB re-run waits for 2027.

**Decisions owed (routed to "Syndicate AI decision engine"):**
- **(a)** Approve the Kalshi combo capture job (public GETs, fleet, nice 19).
- **(b)** Rescope the plan's Phase 5 "combo correlation (E4)": the platform's correlation source for any combo
  pricing is the measured copula; the sims supply correlation only for soccer scorelines. The plan text is the
  decision-engine lane's file, and this lane does not edit it.

## Caveats

- **MLB is postseason only:** 22 games. The frozen pregame copies start 10-03, and the fleet's `book_quotes` start
  09-30, so the September regular season has no market side on the fleet.
- **NBA is 5 regular-season dates.**
- Cross-player cells are underpowered for effects of ~1e-4 nats. Their kill means "not shown", which is what the
  registered rule tests.
- **Marginals:** the de-vigged median of the LAST pregame record per book, from a change log. That is not a
  synchronized close (median age 36-126 min).
- **NBA SP-nested and MLB SP-nested include arithmetic or logical nesting.** Beating independence there was expected,
  and the registration said so in advance. `D_bc` is the read that matters.
- **The copula arm (c) uses the CURRENT fleet correlation files.** They were fitted on 2023-25 (NFL/NHL) and
  2025-26 (NBA) data, before this window, so (c) is out of sample here.
- **NBA (b) back-out** relies on the calibration stamps (`sd_scale`, file `k`). 89 player-games failed the 25% PRA
  identity gate and were dropped. The independence finding does not depend on the back-out (the post-hoc ratio).

## POST-HOC ADDENDUM 2026-10-27 13:0xZ — how much of the REAL within-player P/R/A covariance is minutes (NOT pre-registered)

Asked in this session after E4 closed: if the NBA sim drew minutes per draw, how far would that move its 0.997?

- **Data:** ESPN summary boxes from the 2025-26 NBA regular season, 824 games. Read-only from `C:/tmp/bball_sc/cache/nba`, the `basketball-player-distribution` cache.
- **Population:** players with >= 20 qualifying games.
- **Ratio:** `Var(PRA) / [Var(P) + Var(R) + Var(A)]`, pooled across players, with a player-bootstrap 95% CI (2,000 resamples, seed 20261027).
- **"vs trailing-10":** each game minus the player's own trailing-10-game mean. This removes role drift that a pregame sim already knows.
- **"minutes removed":** residuals of each stat on that game's minutes (OLS per player).

| Population | Players | Raw | Minutes removed |
|---|---|---|---|
| All games | 398 | 1.358 [1.334, 1.382] | 1.042 [1.024, 1.060] |
| All games, vs trailing-10 | 342 | 1.333 [1.306, 1.359] | 1.043 [1.020, 1.065] |
| >= 15 MIN | 310 | 1.233 [1.211, 1.255] | 1.038 [1.018, 1.057] |
| **>= 15 MIN, vs trailing-10** | **246** | **1.216 [1.189, 1.244]** | **1.039 [1.015, 1.064]** |

Median per-player correlations, >= 15 MIN vs trailing-10:

| | P x R | P x A | R x A |
|---|---|---|---|
| Raw | +0.20 | +0.11 | +0.16 |
| Minutes removed | +0.07 | 0.00 | +0.06 |

**Read:**
- **Minutes carry 82% to 87% of the real excess over 1.0** (82% at >= 15 MIN vs trailing-10; 87% on all games vs trailing-10).
  - A per-player, per-game minutes draw should take most of the sim's 0.997 toward the real value. That draw is `basketball-player-distribution`'s planned Phase 2 (1); its Phase 1 (`0050a741`) found the sim's minutes 1.57x too narrow (bench 2.03x).
  - The remainder, about 0.04, is per-minute co-movement (P x R, R x A). It is second-order.
- **E4's real 1.196 rested on 17 players.** The same filter on 246 players reads 1.216.
- **Acceptance check offered to the owner lane:**
  - At >= 15 sim minutes, the sim's ratio should rise from 0.997 toward 1.216 [1.189, 1.244].
  - A minutes draw alone should land near 1.18. That figure is by subtraction, not simulated.
  - Then re-run E4's NBA SP-disjoint cell (`#740` (d)).
- **Caveat:** OLS on realised minutes credits to minutes any co-movement where minutes RESPOND to performance (foul trouble, a hot night, blowouts). The sim reproduces that share only if its minutes draw is tied to game script; an independent minutes draw gets the rest.
- **No lane opened for the fix.** It belongs to `basketball-player-distribution` (session e0a3e383, OPEN). It was routed there in `.syndicate/brief_2026-10-27_engine_reads.md`, the NBA section.
- **Script and output:** `C:/tmp/e4/pra_minutes_decomp.py` and `C:/tmp/e4/pra_minutes_decomp.out.jsonl` (scratch, not in git).
- **LOCATED 2026-10-27 15:06Z by the owner lane (`a6e470f0`, rule pre-registered `b497373a`): CONFIG.**
  - On the same 12 dates the production engine config reads **1.002** (corr(sim min, pts) 0.18). The candidate
    round-2b + #5b-A config reads **1.138** (0.41). Real is 1.196.
  - So the fix is not a new minutes draw. It is the candidate config, whose playing-time levers (bench boost, blowout
    rest, foul trouble and foul-outs in sim, score effect) are believed, not tested, to carry the co-movement.
  - It reaches production only via `nba_engine_config.json`, after its forward test (`3020b556`, 2026-27 regular
    season from 11-01, read once at >= 250 period-line games) and a user decision. Phase 2's minutes draw is for the
    widths.
  - My 'minutes fixed across draws' attribution was too strong. The production config's playing time does vary by
    draw; it barely co-moves with production.
  - Owed when the config is live: E4's served statistic (predicted 0.997 -> ~1.14), the `k_combo` pr/pa/ra
    (`nba_prop_calibration.py:19-21`) and SGP pool PR/PA/RA Normal re-reads, and `#740` (d)'s NBA cells. Tracked
    weekly by scheduled task `nba-pra-covariance-watch` (user 2026-10-27: "keep it where it is but stay on top of it").
