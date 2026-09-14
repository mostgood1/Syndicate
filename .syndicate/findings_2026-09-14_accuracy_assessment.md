# Findings — accuracy-assessment-0914 (2026-09-14)

Lane `accuracy-assessment-0914`. The question: pregame AND live accuracy of every
sport x bet type active 2026-08-31..09-13, then optimize on what was learned and
backtest what was never measured.

Numbers are from production (Render web disk, the ops API, ESPN/StatsAPI finals)
unless a line says otherwise. Nothing here was taken from a local `data/` mirror.
Each slice was measured by a read-only agent; the scripts and cached responses sit
in this session's scratchpad under `agents/<slice>/`, and the decisive numbers are
copied here.

Conventions: `diff` = model minus market (Brier: positive means the model is WORSE;
MAE: positive means the model is further from the result). CIs are 95% bootstraps
over GAMES, never rows.

---

## Activity census, 2026-08-31..09-13

| sport | games in window | Layer 2 board rows (09-06 / 09-10 / 09-13) | projections measured / unmeasured (same dates) | orders (14 d) |
|---|---|---|---|---|
| mlb | active | 3,048 / 1,018 / 2,950 | 925/1,348 · 316/443 · 960/1,245 | 274 |
| ncaaf | active | 690 / 1,878 / 633 | 65/0 · 6/0 · 72/0 | 1,587 |
| nfl | active from 09-10 | 1,247 / 2,914 / 2,953 | 0/1,247 · 0/1,967 · 0/1,433 | 87 |
| soccer | active | 17,345 / 24,251 / 17,740 | 0 measured on every date | 149 |
| wnba | **0** (FIBA break, returns 09-17) | 0 (last grid 08-30) | none | 0 |
| nba | **0** (preseason 10-03) | not ingested in 2026 | none | 0 |
| nhl | **0** (preseason 09-19) | not ingested in 2026 | none | 0 |
| ncaab | **0** (none before 11-01) | not ingested | none | 0 |

- The WNBA zero is real: the pregame job wrote empty slates and header-only props
  files every day, and the Layer 2 sweep reported 0 scheduled games.
- Served shortlist 2026-09-14 (`limit=2000`), before any change: 605 of 1,394 rows
  read "model never backtested" (mlb 268, soccer 268, nfl 69).

## WNBA and the out-of-season sports

**Window verdict: unmeasurable, 0 games** — every WNBA market, pregame and live.
There is no WNBA live ledger and no live WNBA line has ever been captured.

**Context from August (outside the window), 62 production game cards joined to ESPN finals:**

| market | n games | model | market | diff | 95% CI | verdict |
|---|---|---|---|---|---|---|
| moneyline (Brier) | 34 | 0.2558 | 0.1302 | +0.126 | [+0.044, +0.216] | loses to market |
| — sim's own probability only | 12 | | | +0.015 | [-0.064, +0.093] | parity (thin) |
| — board's fallback probability | 22 | | | +0.186 | [+0.069, +0.316] | loses; its scale (3.4) is ~2x too confident |
| margin vs line (MAE, pts) | 40 | 9.45 | 6.03 | +3.42 | [+1.48, +5.62] | loses to line |
| total vs line (MAE, pts) | 40 | 14.03 | 7.67 | +6.36 | [+3.78, +8.98] | loses to line |

- Encompassing regression gives the sim a negative weight (-0.49): it adds nothing
  to the market.
- The sim is partly market-anchored (blend 0.95 margin / 0.7 total). It tracks its
  own input line at corr 0.89 but the card's line at only 0.68 (gap SD 9.2 pts):
  on 13 of 15 games it priced a different line than the card carries. Stale lines
  plus 100-sim noise make it worse, not independent.

**NBA / NHL / NCAAB before their seasons:**
- `_attach_projections_by_sport` has no NBA, NHL or NCAAB branch, so their rows will
  carry no projection and no `model_skill` block at all — not even "unmeasured".
- NHL's latest production input report (09-14, covering June dates) shows 21 failing
  inputs: Elo, xG, shots, faceoff and player weights 0% populated. This contradicts
  the 08-20 local pass and needs fixing before 09-19.
- The two WNBA bugs `[sim-edge-analysis-2026-09-01]` says NBA still carries are
  fixed in current code (`refresh_nba_oddsapi_props.py:1250`, `:2256-2264`); the
  deployed version was not checked.

**Optimizations proposed (not implemented), each with its falsifier:**
1. Drop the WNBA fallback moneyline probability, or refit its scale out of sample.
   Falsified if a refit reaches parity on 30+ games from 09-17.
2. Stop deriving WNBA spread/total edges from sim means. Falsified if, over the
   first 50 games, the error-gap CI includes 0 on both markets.
3. Refuse or re-run the WNBA sim probability when the card's line moved away from
   the sim's input line. Falsified if 80%+ of 09-17..09-19 rows already share it.
4. Fix NHL's 21 failing inputs before 09-19. Falsified if the first preseason
   report shows 0 failures with no change. (Recorded as a lead, not worked here.)

## MLB — LIVE game lines

Source: per-record live game-line ledgers (web copy, 14/14 dates) joined to 188
StatsAPI finals. Headline cut: fresh quotes (<=120 s), paired, h2h `segment=full`.

**Coverage.** Fresh h2h: 14 dates / 176 games (09-12 only 8 rows / 5 games).
Totals/spreads: 13 dates / 159 games (09-09 has none — the f5c2468a crash window).
Rows carrying the model's total/margin MEANS: 7 dates / 64 games. first5: 6 dates /
67 games, and those rows carry no quote age.

| market / cut | window | dates | games | rows | model | market | diff [95% CI over games] | calibration | verdict |
|---|---|---|---|---|---|---|---|---|---|
| h2h full, fresh (headline) | 08-31..09-13 | 14 | 176 | 2,374 | 0.16949 | 0.15931 | **+0.01019 [+0.00089, +0.02045]** | reliability gap -0.00048 (spans 0); resolution gap +0.01007 [+0.00033, +0.02013] | **loses to market** |
| h2h, before 09-08 | 08-31..09-07 | 8 | 107 | 1,748 | 0.17818 | 0.16561 | +0.01256 [+0.00054, +0.02591] | | loses to market |
| h2h, since 09-08 | 09-08..09-13 | 6 | 69 | 626 | 0.14525 | 0.14169 | +0.00356 [-0.00966, +0.01610] | both gaps span 0 | parity — underpowered |
| first5 h2h | 09-08..09-13 | 6 | 67 | 1,302 | 0.16821 | 0.15916 | +0.00905 [-0.00869, +0.02806] | model more spread (sd 0.30 vs 0.26) | parity |
| totals, P(over) | 13 dates | 13 | 159 | 4,780 | 0.24824 | 0.24342 | +0.00482 [-0.00847, +0.01889] | 16.5% of market line pairs inverted | parity |
| totals, model mean vs line (MAE runs) | 09-06..09-13 | 7 | 64 | 1,342 | 2.416 | 2.268 | +0.148 [-0.188, +0.512] | model runs HIGH by +0.89 | parity |
| spreads, P(home covers) | 13 dates | 13 | 159 | 4,518 | 0.22852 | 0.22849 | +0.00002 [-0.0139, +0.0147] | model over-dispersed | parity |

- **H3 is FALSIFIED on the window.** The deficit is still RESOLUTION, not
  calibration. Error is monotone in the model's disagreement: +0.02677 at 10-20pp,
  +0.09815 above 20pp.
- Held-out-date blending is worse than the market (+0.00637 [+0.0011, +0.0124]),
  and recalibration is worse than the raw model (+0.00607 [+0.0023, +0.0103]).
- Totals/spreads are measured for the first time (the ~60-game gate is met at 64).
  Their 62-64% hit rates against 0.50 are STRUCTURE, not edge: on spreads the
  market's own lean hits 62.3% vs the model's 63.0%; "always over" hits 55.9%.
- Early in games the totals model projects 8.87 remaining runs, against 6.83 for the
  line and 7.15 actual.

**Publication: stays OFF on all four markets.** To turn one back ON would need a
paired, fresh-cut Brier diff whose CI upper bound is below 0, on the rows the board
would publish, within one model era, on held-out dates. For a true -0.005 that is
~500-700 h2h games or ~1,300 spreads games.

**Where live rows get `model_skill`: nowhere live-specific.** `attach_projections`
(`book_grid_artifact.py:431`) stamps the PREGAME note; the live join
(`live_gameline_join.py:1694`, `:1788`) copies that projection, so live rows inherit
it. `REASON_ANALYTIC_UNCALIBRATED` (`:1087`) is a WNBA-style refusal reason, not a
skill note, and never fires on MLB.

**Defects found:**
1. **The first5 observation rows are mislabelled.** 43,269 first5 totals/spreads rows
   carry a home-WIN probability — 97.8% identical to the same build's h2h
   probability — while their market price is P(over)/P(cover). They are ~85% of
   ledger volume since 09-08. Site: `live_gameline_join.py` ~1510.
2. **The totals/spreads market baseline is degraded.** 14-16% of line pairs have
   P(over) RISING with the line (median slope -0.047 per run vs the model's -0.092).
3. **The scorer's hit-rate baseline is 0.50** (`live_gameline_score._directional`)
   instead of the market's own lean, inflating directional results by ~+12pp.
   **NOT CHANGED, deliberately.** Three reasons, all read in code:
   - `test_market_fair_prob_is_never_read_on_a_line_priced_row` pins that the
     whole `point_forecast` block must not move with `market_fair_prob`. That
     guard exists so a ~0.50 de-vig cannot creep back into the comparison.
   - The market probability a lean baseline would read is the one defect 2 shows
     is degraded (14-16% inverted line pairs).
   - On spreads, `line` is the away/over-frame line (`#262`). Whether
     `market_fair_prob` is P(home covers) or P(away covers) in that frame is not
     settled by the code, so a lean baseline could carry the wrong sign.

   Fix defect 2 first (same-book, same-line de-vig), then add the lean baseline as
   a SEPARATE block beside `point_forecast`. Until then, read any live
   totals/spreads hit rate against 55.9% ("always over", totals) and 62.3% (the
   market's lean, MLB run lines), never against 50%.
4. Early-game live totals run ~+1.7 remaining runs high at under a third of the game
   (60 games). Unexplained.

**Contradicts the ledger:**
- `pool_live_gameline_trend.py --era each --cut fresh_quotes_only` reads +0.00460 /
  134 games through 09-11. The raw recomputation reads +0.01019 [CI excludes 0] /
  176 games: the tool drops 08-31 (+0.03591 over 12 games) and uses board finals.
- `state_mlb.md [mlb-live-edge-forbidden]` item 4 says spreads price at ~-110, so the
  de-vigged price is ~0.50 whatever the line. FALSE for MLB run lines: market sd
  0.134, and its lean hits 62.3%.
- The worker history counts more fresh h2h rows than the web ledger holds (88 vs 84
  on 09-10, 114 vs 100 on 09-11). Unresolved.

## SOCCER — pregame and live

Source: odds_history closes (per book, proportionally de-vigged: 3-way for 1X2,
two-way at the line, then averaged; median h2h close 69 min before kickoff),
soccer projection artifacts, the live game-line ledger, ESPN finals with draws
counted. 54 production requests, every shard landed. Bootstrap over matches,
4,000 resamples.

**Population.** 246 completed matches in 10 leagues; 229 with a 1X2 close.
- 7 on 08-31: that shard is 0.11 MB and holds no closes.
- 8 are name-join misses on 4 clubs (1. FC Köln / FC Cologne, Sporting Lisbon /
  Sporting CP, Rennes / Stade Rennais, SK Beveren / Waasland-Beveren). Production's
  own `teams_match` fails on them too.
- 2 had no market event.

**Model versions split at 2026-09-07 20:12Z**, when ESPN match-stats inputs reached
the worker. The market prior was off (`armed=False`) on all 127 later builds.

**THE CAVEAT THAT BOUNDS THE PREGAME RESULTS.** All 246 projection files were
REBUILT after their match (median 10.3 h after kickoff). The code path reads no
result, but the number actually published before kickoff is kept nowhere, and
`pregame_home_win_prob` is null on all 8,210 soccer ledger rows. A leak can only
flatter the model, so **"loses" verdicts are robust and "parity" verdicts are an
upper bound on skill.**

| market | phase | dates | matches (rows) | model | market | diff [95% CI] | verdict |
|---|---|---|---|---|---|---|---|
| 1X2 multiclass Brier | pre, built >=09-07 | 7 | 121 | 0.6474 | 0.6028 | **+0.0446 [+0.0148, +0.0742]** | **loses to market** |
| 1X2 multiclass Brier | pre, built <09-07 | 6 | 108 | 0.6481 | 0.6334 | +0.0148 [-0.0187, +0.0497] | parity |
| 1X2, pooled (mixed versions, secondary) | pre | 13 | 229 | 0.6477 | 0.6172 | +0.0305 [+0.0087, +0.0527] | loses |
| Over/Under 2.5 | pre | 13 | 145 | 0.2557 | 0.2488 | +0.0069 [-0.0060, +0.0197] | parity |
| Totals, main half/whole line | pre | 13 | 194 | 0.2603 | 0.2505 | +0.0099 [-0.0037, +0.0237] | parity |
| Asian handicap, main line | pre, <09-07 | 6 | 84 | 0.2527 | 0.2490 | +0.0038 [-0.0216, +0.0304] | parity |
| Asian handicap, main line | pre, >=09-07 | 7 | 100 | 0.2698 | 0.2433 | +0.0265 [+0.0001, +0.0542] | loses (borderline) |
| BTTS | pre | 14 | 236 | 0.2465 | 0.2432 | +0.0033 [-0.0048, +0.0113] | parity (market side ~14 h old, no BTTS close) |
| Live P(home win) | live, <=120 s | 12 | 118 (1,136) | 0.1490 | 0.1340 | +0.0150 [-0.0032, +0.0319] | parity |
| Live totals, model mean vs line | live, <=120 s | — | 44 (258) | hit 52.7% | 50% | [44.2%, 61.3%] | parity (thin) |
| Corners | both | — | — | — | — | — | unmeasurable: no corners distribution or corners results source |

- 1X2 after 09-07: the model scored worse on 78 of 121 matches (p=0.002). The
  version gap itself is NOT proven: post minus pre +0.0298 [-0.0155, +0.0741].
- The deficit is RESOLUTION, not reliability: reliability 0.027 model vs 0.025
  market, resolution 0.047 vs 0.070; home-probability spread 0.153 vs 0.168.
- **The favourite defect persists.** On 46 matches with a market favourite >=0.60,
  the model gives the favourite 0.627, the market 0.728, and 0.717 won. Favourite-leg
  diff +0.042 [+0.005, +0.081].
- The 1,112-match verdict holds in DIRECTION with a bigger gap (+0.030 pooled vs
  +0.014), but "worse in 8 of 9 leagues" does not replicate: 6 of 10 (p=0.75).
  Significant only in Championship (+0.088, n=44) and Primeira Liga (+0.051, n=15).
- Totals: model mean bias -0.095 goals; its lean hits 49%.
- **No blend beats the market out of sample** (leave-one-date-out). 1X2 after 09-07:
  blend minus market +0.021 [-0.005, +0.048], full-sample model weight -0.73 and
  linear-pool weight 0. Over 2.5 blends lose in both periods; BTTS blend loses
  +0.005 [+0.001, +0.010].
- Live: the model is worse in 76 of 118 matches (p=0.002), concentrated where it
  disagrees by 10+ points: +0.037 [+0.004, +0.068] over 95 matches vs -0.0005 under
  2 points. 80 sims explain only 0.0019 of the gap.

**The paper ledger, read against the full population.** Soccer game_line "agrees" at
-44.3% (31 settled) is CONSISTENT: 1X2 loses, and model edges >=4 points hit 24.3%
against 29.3% implied (-16.6% ROI at the fair close, 164 matches, secondary cut).
Game_total "agrees" at +15.3% (33 settled) is NOT supported: totals are parity.

**Data defects found:**
1. Pregame projections are overwritten after the match (246 of 246), so no pregame
   soccer measurement can be taken on the published number.
2. The 20-entry odds_history cap evicts closes: on 09-05, 147 of 2,960 book-side keys
   (5.0%) lost every pre-kickoff quote to in-play captures; 08-31 captured no closes.
3. Four club aliases missing (3.3% of matches unjoinable).

**Contradicts the ledger:**
- The live gap recorded as +0.108 (51 games, priceable rows, 08-21..08-26) is +0.015
  on fresh quotes and +0.022 on priceable rows in this window. Direction holds.
- The live source docstring says 400 sims; every fresh ledger row says 80.
- odds_history now carries IN-PLAY soccer quotes, and they are evicting closes.
- 09-12 priceable is 504 of 1,541 on the final ledger, not 276 of 928 (a mid-day read).

**Proposed, not implemented:** keep 1X2 model edges unpublished; fix favourite
under-dispersion by widening the rating spread and re-fit in the leak-free 1,112-match
harness (not on this window, which fails out of sample); treat totals "agrees" orders
as no signal; test a 10pp-disagreement refusal on live h2h with leave-one-date-out
first (the MLB precedent failed out of sample); snapshot the pregame projection on
first sighting; protect closes from the history cap; add the 4 aliases.
