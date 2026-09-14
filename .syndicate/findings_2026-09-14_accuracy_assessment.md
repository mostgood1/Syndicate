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

## THE TABLE — every active sport x bet type, pregame and live

**Headline: no model beats the market on any active market, pregame or live.** Every
cell is either a measured loss or parity (CI spans zero). The single cell leaning toward
the model is NCAAF live moneyline, still inside its CI. "Parity" is not "useful": on
MLB moneyline and run line, adding the sim to the market made out-of-sample Brier WORSE.

**Two caveats cap every pregame "parity":** MLB `daily_summary` (game markets AND props)
and soccer projections are REBUILT after the games, so the pregame number that was
published is gone. A leak can only flatter the model — "loses" is robust, "parity" is an
upper bound.

| sport | market | PREGAME verdict | n | LIVE verdict | n |
|---|---|---|---|---|---|
| MLB | moneyline (full) | parity, point worse; sim hurts a blend | 188 g | **LOSES** Brier +0.010 [+0.001, +0.020] | 176 g |
| MLB | run line (full) | parity, point worse; sim hurts a blend | 188 g | parity | 159 g |
| MLB | **totals (full)** | parity only because scoring ran high; sim ~2.1 runs over the line since the 09-05 refit | 177 g | parity; runs high early | 159 g |
| MLB | first 5 moneyline / run line / totals | parity / parity (sim hurts) / parity | 148-168 g | moneyline parity | 67 g |
| MLB | first 3 moneyline / run line / totals | parity (totals possible signal, unconfirmed) | 124-168 g | — | — |
| MLB | first inning total / run line | parity | 168 g | — | — |
| MLB | pitcher `outs` | **LOSES** Brier +0.036 [+0.006, +0.068] | 196 starts | — | — |
| MLB | pitcher `earned_runs` | **LOSES** Brier +0.017 [+0.001, +0.033] | 200 starts | — | — |
| MLB | pitcher `strikeouts` / `hits_allowed` / `walks_allowed` | parity (all biased high except walks) | 186-193 starts | — | — |
| MLB | batter hits+runs+RBIs | parity; beats the trailing mean | 1,266 pg | — | — |
| MLB | batter hits / total bases / RBIs / runs | measured before (`mlb_prop_calibration`), not re-measured; also post-game re-sims | — | — | — |
| MLB | team totals | unmeasurable: no quotes captured | — | — | — |
| NCAAF | spread / margin | **LOSES** MAE +1.75 [+0.45, +3.06] | 100 g | parity | 75 g |
| NCAAF | **totals** | **LOSES** MAE +2.86 [+1.12, +4.59] — first score vs the close | 100 g | **LOSES** MAE +1.88 [+0.79, +3.04] | 75 g |
| NCAAF | moneyline | parity; 22% of probabilities pinned at 0/1 | 58 g | parity, leans model: Brier -0.014 [-0.031, +0.002] | 76 g |
| NFL | spread / margin | **LOSES** MAE +1.79 [+0.09, +3.49] (week 1) | 15 g | unmeasurable: no NFL live ledger | — |
| NFL | totals | **LOSES** MAE +2.57 [+0.35, +4.67] (week 1) | 15 g | unmeasurable | — |
| NFL | moneyline | parity (week 1) | 15 g | unmeasurable | — |
| NFL | player props (two-sided) / anytime TD | **LOSES** Brier +0.021 / +0.017 | 15 g (708 / 184 props) | — | — |
| Soccer | 1X2 | **LOSES** Brier +0.045 [+0.015, +0.074] (current version) | 121 m | parity | 118 m |
| Soccer | totals (main line) / O-U 2.5 | parity | 194 / 145 m | parity | 44 m |
| Soccer | Asian handicap | **LOSES**, borderline, +0.027 [+0.000, +0.054] | 100 m | — | — |
| Soccer | BTTS | parity (no BTTS close; market ~14 h old) | 236 m | — | — |
| Soccer | corners | unmeasurable: no corners distribution or results | — | — | — |
| WNBA | all markets | unmeasurable: 0 games in window (August: moneyline loses +0.126, 34 g) | — | unmeasurable | — |
| NBA / NHL / NCAAB | all markets | no games in window | — | — | — |

(g = games, m = matches, pg = player-games.) Hypotheses: **H1 not falsified** (the label
was a wiring gap), **H2 not falsified** (no prior "loses/ties" overturned), **H3 FALSIFIED**
(MLB live moneyline still loses on the window), **H4 not falsified** (NCAAF totals lose to
the close).

## WHAT SHIPPED (branch `session/accuracy-assessment-0914`; NOT deployed)

1. **"Model never backtested" now carries the measurement where one exists.**
   `syndicate/features/shared/measured_market_skill.py` is a table keyed (sport,
   market, segment, phase), consulted by `projection_skill.attach_projection_skill`
   only where the producer attached no note. 31 entries from the table above: MLB
   pregame game markets (10), MLB pitcher props + HRR (6), MLB live (4), soccer
   pregame (3) and live (2), NCAAF live (3), NFL week-1 pregame (3). Every entry
   cites its source, window and n; `sample_games` and verdict are what the row shows.
2. **Live rows state the LIVE model's record.** `live_gameline_join._apply_verdict` and
   `live_projection_join.attach_live_projections` copied the PREGAME `model_skill`
   onto every live-joined row. Both now carry `projection_skill.live_skill_note` (the
   live measurement, else "unmeasured"). A pregame note is never kept on a live row.
3. **The first5 live observation pairs like with like.** 43,269 first5 totals/spreads
   ledger rows (~85% of volume since 09-08) paired a home-WIN probability with
   P(over)/P(cover); the observation is now computed on h2h only.
4. **NCAAF's own note is current.** `NCAAF_MEASURED_SKILL.margins` keeps the 2024 backtest
   and adds the 2026 season (+1.75 MAE over 100 games; the tooltip quotes it, since the
   2024 +3.56 lies outside the 2026 CI). `.totals` replaces "never scored against the
   close" with the measured loss (+2.86 MAE, 2.48x over-dispersed). `pick_gate`'s NCAAF
   totals verdict text says the same; `servable` stays False.
5. **A measured loss cannot re-admit what an unmeasured model could not.**
   `layer2_board._row_rests_on_unmeasured_model` also withholds a ONE-SIDED row whose
   note is measured with `verdict_class: loses_to_market`. On the 2026-09-14 board every
   relabelled market was two-sided, so nothing moves today; this keeps it that way.

**Verification so far (offline):** new test files `test_measured_market_skill.py`,
`test_live_gameline_skill_note.py`, `test_live_projection_skill_note.py`; extended
`test_projection_skill.py`, `test_ncaaf_game_projections.py`,
`test_layer2_unmeasured_model_only.py`. Each change was mutation-checked: its new tests
FAIL against HEAD's version of the file (registry 2, live game-line 7, live prop 2,
Layer 2 withhold 2). Pre-existing failures, identical on HEAD source:
`test_football_pick_gate::test_off_is_not_on`, and 7 NCAAF projection tests that need the
team registry under `data/` (they pass with `SYNDICATE_NCAAF_SOURCE_ROOT` pointed at a
checkout that carries it).

**Owed, production:** the served-board census of `model_skill.status` AFTER a deploy.
The before-reading is 605 of 1,394 shortlist rows "never backtested". The code runs on
BOTH refresh-worker (book grid + Layer 2 builds) and web (the book-grid route's inline
build, `intelligence.py:3186`), so the deploy is both services.

**Not run:** the 14-day CLV sweep across sports (one date sampled: MLB 09-13 same-book
pregame CLV +0.04%, beat-close 29%, n=267) and the in-play vs pregame scorecard over
published openings (`scripts/layer2_live_scorecard.py`).

**USER DIRECTION `[2026-09-14, in chat]`:** "from a model/overall standpoint totally get the
'this category loses' idea HOWEVER at an actual game/prop level there is success. We should
not globally throw something out - we should find where the success is once we have
updated the modeling."

What that means for everything in this file:
- **A category verdict is an AVERAGE over a population, not a ban.** "Loses to the market"
  says the model is not generally better than the price; it says nothing about whether a
  subset of games or props is. The table is the baseline a pocket must beat, not a list of
  things to switch off.
- **Order of work: fix the modelling first, then search for success, then gate at the
  level where success is found.** Pockets found on today's models would be pockets of
  today's defects (the MLB total level, starter length, frozen NCAAF ratings, soccer
  favourite dispersion) and would move when those are fixed.
- **The search must be one this repo's history says survives.** Pre-register the pocket
  definition before looking; score per GAME, never per row; validate leave-one-date-out;
  compare against the market's own lean, not 0.50; state the window. Two MLB live
  "profitable buckets" collapsed that way (`spreads q4_late` +14pp was stale quotes and a
  wrong baseline; +21σ by row was +2.9σ by game), and a subpopulation gate that looked
  real in-sample failed leave-one-date-out. That is a reason to do the search carefully,
  not a reason not to.
- **Nothing shipped here removes a category.** The registry changes labels. The Layer 2
  clause keeps rows that were ALREADY withheld (as "unmeasured") withheld; a pocket that
  proves out can carry its own measured note and `verdict_class`, and pass that gate.
- The "withhold", "weight 0" and "drop the gate" items below are therefore INTERIM
  positions until the pocket search runs on the updated models, not end states.

**Recommended, NOT implemented — each needs a model change, a data-retention change or a
user decision (details and falsifiers in the sections below):**
- MLB: re-fit the game-total level (sim ~2.1 runs over the line since 09-05) with a deploy
  gate against the line; sim weight 0 on moneyline / run line / first5 run line; drop
  "sim agrees" as a staking gate; fix starter length (outs +7%, missing early exits)
  upstream; keep a pregame copy of `daily_summary`; keep MLB live publication OFF.
- NCAAF: totals have no skill (corr 0.14) — re-fit the scoring mechanism; ratings are
  frozen at preseason — add in-season ratings; pre-register the `contradicts` veto.
- NFL: props lost -7.6% on edges in week 1, matching the 2023-25 backtest — keep them
  non-stakeable or anchor them to the market (**user decision**; left stakeable 09-09).
- Soccer: widen the rating spread for favourites and re-fit in the leak-free 1,112-match
  harness; keep 1X2 model edges unpublished; snapshot projections before kickoff.
- Data: close cutoff at min(OddsAPI commence, ESPN kickoff); `closing_lines` refuses
  quotes >60 min old; stop in-play captures evicting soccer closes; the paper payload's
  order drop; the live totals/spreads de-vig with inverted line pairs.

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

## MLB — PREGAME game markets (the user's named example: totals)

Source: production `daily_summary` game probabilities, the single-book pregame odds
freeze (de-vigged), StatsAPI finals. 79 production requests. Coverage: 14 of 14 dates on
every family, 188 games — the full slate; intersection 14 dates / 188 games.

**Three things that change how the numbers read:**
1. **The served `daily_summary` is a re-sim run after first pitch.** All 326 scored games
   (08-21..09-13) are `started_game_repairs`, written ~23:30 CT with pregame lineups but
   whatever code was live then. It is not the file the board showed pregame.
2. **The sim changed three times inside the window**, so it was not pooled with
   06-17..08-30: substitution `e3bdbc8b` (live 09-01 23:41Z), rate refit `ead7c6c5`
   (~09-05 01:47Z), home field `72499c2a` (09-08 ~19:50Z).
3. **`closing_lines_*.csv` (best price across books) is stale on full-game lines**: 49% of
   full-game total rows were >2h old at first pitch, almost all exchange quotes. The
   single-book pregame freeze was used instead; on 09-05 (15 games) it sat within
   0.53pp (h2h) to 0.74pp (spreads) of a ~13-book consensus close.

| market | games | model Brier | market Brier | diff [95% CI] | verdict |
|---|---|---|---|---|---|
| full moneyline | 188 | 0.24715 | 0.23805 | +0.0091 [-0.0046, +0.0236] | parity, point worse; no skill vs base rate |
| full run line | 188 | 0.24526 | 0.23752 | +0.0077 [-0.0055, +0.0207] | parity, point worse |
| **full totals** | 177 | 0.25424 | 0.25033 | +0.0039 [-0.0166, +0.0246] | **parity, but level-confounded** (below) |
| first5 moneyline | 148 | 0.24983 | 0.24094 | +0.0089 [-0.0094, +0.0272] | parity, point worse |
| first5 run line | 168 | 0.25688 | 0.24992 | +0.0070 [-0.0084, +0.0227] | parity |
| first5 totals | 168 | 0.24937 | 0.25120 | -0.0018 [-0.0190, +0.0157] | parity |
| first3 moneyline | 124 | 0.23951 | 0.24617 | -0.0067 [-0.0244, +0.0120] | parity |
| first3 run line | 168 | 0.24341 | 0.24360 | -0.0002 [-0.0123, +0.0122] | parity |
| first3 totals | 163 | 0.23789 | 0.25052 | -0.0126 [-0.0267, +0.0022] | parity (possible signal, not confirmed out of sample) |
| first1 total (o/u 0.5) | 168 | 0.25228 | 0.25331 | -0.0010 [-0.0116, +0.0098] | parity |
| first1 run line / 3-way | 168 | 0.18665 / 0.59327 | 0.19047 / 0.60115 | -0.0038 / -0.0079 | parity |
| team totals | — | — | — | — | unmeasurable: no team-total quotes captured |
| alternate lines | — | — | — | — | unmeasured: main line only |

- Current model version (V3, since 09-08) alone: all parity, 60-80 games, 6 dates.
- Baseline 08-21..08-31 (pre-substitution, 140 games): totals LOST to the close,
  +0.0190 [-0.0004, +0.0394]; the date-level CI excludes 0.

**Totals — why "parity" is not "fine".**
- Level (sim mean / line / actual): 7.99 / 8.18 / 8.76 before 09-01; **10.34 / 8.24 / 9.55
  after the rate refit** (127 games) — +2.1 runs over the line, +0.9 over actual.
- After the refit the mean PIT is 0.465 (p=0.023): the sim runs high.
- Window MAE: sim 3.945 vs line 3.881, +0.063 [-0.245, +0.382].
- The sim-vs-line gap does NOT predict the side: side hit 55.9% [48.6, 63.3], mostly the 59%
  over rate; no gradient by gap size; refitting the gap out of sample adds nothing
  (-0.071 [-0.271, +0.135]).
- Resolution 0.0048 (sim) vs 0.0136 (market): recalibration cannot close it.
- The ead7c6c5 and 72499c2a commits never checked game totals against the market, which
  moved ~2.3 runs.

**Conditional information (leave-one-date-out, recalibrated market vs market + sim):** the
sim makes it WORSE on moneyline +0.0022 [+0.0001, +0.0044], run line +0.0031
[+0.0010, +0.0053] and first5 run line +0.0041 [+0.0012, +0.0072]; null elsewhere. Only
first3/first5 totals show in-sample coefficients excluding 0 (pooled first3 0.88
[0.29, 1.58]), unconfirmed out of sample and absent before 09-01. **A fitted blend will not
beat the market.**

**The ledger is consistent.** 37% win rates at -5.3% / -7.2% ROI imply average odds near
+150 (alt-line and exchange contracts). On main lines at the freeze price, betting the sim's
side returns -1.6% [-16, +13] on moneyline vs -4.9% for betting every side — what the hold
predicts if the sim adds nothing; the ±11-point SE can't separate them.

**Proposed (not implemented):**
1. Re-fit the game-total LEVEL: add per-game totals vs the closing line as a target in the
   rate refit, and a deploy gate of ±0.3 runs vs the 7-day line. Until then keep MLB totals
   model probabilities out of ranking and "agrees" gates.
2. Model weight 0 on full moneyline, run line and first5 run line.
3. Drop "sim agrees" as a staking gate for MLB game lines and totals.
4. Shadow-test only a first3/first5 totals blend.
5. `closing_lines` refuses quotes older than 60 min and adds a consensus close.
6. Keep a pregame copy of `daily_summary` instead of overwriting it with post-start re-sims.
7. Withhold the first-inning projected MEAN (MAE 1.029 vs 0.969 for a constant,
   [+0.021, +0.098]).
8. Keep first-5 pricing off: first-5 moneyline skill vs base rate fell from +4.15% (AUC
   0.662) to -0.6% (AUC 0.575).

**Contradicts the ledger:** `state_mlb.md` "run totals calibrated" was true before 09-01 only;
the 08-31 findings call the sim probabilities "pregame" (the inputs are, the code version is
not); "first5 discriminates 3.82σ" no longer holds after the substitution.

**Thin:** no verdict cell is under 30 games (smallest: 38 fresh-close first1 moneyline, 55
fresh-close full moneyline); V3 slices are 60-80 games on 6 dates; the freeze-vs-consensus
check is one date / 15 games.

## MLB — PREGAME PROPS the board called "never backtested"

Markets: pitcher `strikeouts`, `outs`, `hits_allowed`, `earned_runs`, `walks_allowed`,
and batter `batter_hits_runs_rbis` (HRR). 53 production requests.

**What the numbers rest on, and why it bounds them.**
- **Every projection is a POST-GAME re-sim.** Each window `daily_summary` (and 08-12,
  sampled before the window) was rebuilt ~23:30-00:00 CT with every game marked
  `missing_artifact` and 11-15 already Final. The pregame sim the board priced from is
  overwritten nightly and preserved nowhere.
- The re-sim knows more than the pregame sim: its player stats carry no date cutoff.
  Against the pregame `k_targets` projection (146 starts), the post-game version moves
  toward the actual result (corr 0.19, p=0.03, CI [0.014, 0.363]). Leakage and
  legitimate late information (confirmed lineups) cannot be separated. **"Loses" holds;
  "parity" may flatter the model.**
- Model vs market: 8 dates (09-06..09-13), 101-106 games; earlier dates have no pregame
  odds seal and 605 MB of book_quotes shards were not pulled. Model vs trailing mean:
  14 dates, 188 games, 376 starts, 3,199 HRR player-games. All market-paired rows are
  after the 09-04 rate refit (sim changes on 09-01 and 09-04).

| board key | player-games | Brier model | Brier market | Brier trailing mean | model - market [95% CI, games] | bias | degenerate p | verdict |
|---|---|---|---|---|---|---|---|---|
| `strikeouts` | 193 | 0.2621 | 0.2452 | 0.2704 | +0.017 [-0.009, +0.042] | +12.6% | 0 | parity (point estimate worse) |
| `outs` | 196 | 0.2801 | 0.2437 | 0.2698 | **+0.036 [+0.006, +0.068]** | +7.1% | 2 rows at exactly 0/1 | **loses to market** (and to the trailing mean) |
| `hits_allowed` | 192 | 0.2599 | 0.2496 | 0.2715 | +0.010 [-0.014, +0.035] | +11.4% | 0 | parity |
| `earned_runs` | 200 | 0.2597 | 0.2430 | 0.2729 | **+0.017 [+0.001, +0.033]** | +13.5% | 0 | **loses to market** (lower bound barely above 0) |
| `walks_allowed` | 186 | 0.2358 | 0.2390 | 0.2398 | -0.003 [-0.015, +0.010] | +0.5% | 0 | parity |
| `batter_hits_runs_rbis` | 1,266 | 0.2456 | 0.2487 | 0.2550 | -0.003 [-0.009, +0.003] | HRR mean +15%, PA +15% | 0 of 12,796 | parity; beats the trailing mean -0.009 [-0.017, -0.002] |

- Power de-vig and a second bootstrap change nothing.
- Calibration: `strikeouts` bins at p 0.6-0.8 come true 36-48% while the model takes the
  over 75% of the time; `outs` rows at p >= 0.9 come true 59% (n=17); `walks` P(over 1.5)
  is understated (0.49 vs 0.55).
- **One upstream bias explains most of the pitcher markets: starter length.** Outs are
  over-projected in every version (+8% over the window, +7.1% current), explaining
  ~58% of the strikeouts bias, 64% of hits allowed and 54% of earned runs — close to the
  55% share recorded for hitter PA. Total pitches are about right (+2.4%) but the sim
  spends 4.4% too few pitches per out, and it misses early exits: 14% of real starts end
  at <=9 outs, the model gives 1.7%.
- The sim's batters-faced exceeds outs+H+BB by 1.67 per start (actual -0.24); one
  candidate is the counter incrementing at PA start (`simulate.py:2657`), unverified.
- HRR: no exact-zero probabilities in the window (so with/without scores are identical);
  its calibrated probability equals the raw one on every row, i.e. it is uncalibrated.

**Contradicts the ledger:**
- `state_mlb.md` still describes 993 exact-zero HRR rows as a live defect: 0 in the window
  (consistent with `3ee0f382`).
- `mlb_prop_calibration.py` / `prop_projections.py` say `hrr_mean` is 0.0 for every hitter:
  it is live (corr 0.24, +15% bias).
- The hitter "biased, not blind" numbers in `mlb_prop_calibration.py` (08-01..08-14) rest on
  the same post-game re-sims (08-12: 15 of 15) — they are upper bounds too.
- `e3bdbc8b` put residual opportunity bias at +6.1%; production PA bias is +14.6% after
  `ead7c6c5`, whose "residuals under 9%" is per-PA (prop-level counts +11% to +14%).
- `outs` did have a betting-only grade before (95 bets, -10.15%); the direction agrees.

**Proposed (not implemented):** freeze `daily_summary` at first pitch and stop
re-simulating Final games (without this no MLB prop backtest is truly pregame); withhold
`model_prob_over` on `outs`; add an early-exit mixture to the outs distribution (a mean
shift made it WORSE out of sample, 0.272 -> 0.294); fix pitches-per-out upstream rather
than per-market rates (the 09-04 strikeout knob moved strikeout bias +11.1% -> +12.6%);
interim strikeouts-only thinning by 0.909 (Brier 0.2516 -> 0.2411 out of sample, CI
[-0.026, +0.006], 64 games); audit the BF counter; fix HRR PA inflation, don't calibrate.

**Thin:** version breakdowns (v0 1 date / 12 games, v1 3 dates / 39), reliability bins
under n=30, the out-of-sample test (60-65 games), 8 dates for the market comparison.

## FOOTBALL — NCAAF and NFL, pregame and live (2026 season to 09-13)

Source: production NCAAF/NFL projection CSVs, OddsAPI closes from production
captures, the live game-line ledger, ESPN finals (the grader's own source). 59
production requests. Bootstrap over games.

**Coverage and as-of.**
- NCAAF: weeks 1-2 (08-29..09-12), 100 FBS-vs-FBS projections, each with a close and
  a final; 58 with a two-sided moneyline close. The served CSVs were regenerated
  after kickoff, but the inputs are provably pregame: SP+ 2026 is identical on 09-05
  and 09-14 (0 of 138 teams changed), and 80 of 80 `contradicts` orders imply exactly
  the CSV's projected total. All on the refit profile promoted 09-05.
- NFL: week 1, 15 finals (DEN@KC is Monday), all after the rating-units fix.
- 14 of 100 NCAAF "closes" were captured 10-49 min AFTER ESPN kickoff and 5 are over
  an hour stale; a clean-timing cut is reported.

| sport | market | phase | games | model | market | diff [95% CI] | cover / hit | verdict |
|---|---|---|---|---|---|---|---|---|
| NCAAF | margin (MAE pts) | pre | 100 | 13.85 | 12.10 | +1.75 [+0.45, +3.06] | 42.4% [33, 52] | loses (clean cut, 81 games: +1.30 [-0.19, +2.72]) |
| NCAAF | **total (MAE pts)** | pre | 100 | 14.37 | 11.51 | **+2.86 [+1.12, +4.59]** | 51.0% | **loses** — first score vs the close; spread 2.48x the close's, +4.6 pts high |
| NCAAF | moneyline (Brier) | pre | 58 | 0.133 | 0.111 | +0.022 [-0.003, +0.050] | — | parity; 22% of probabilities pinned at 0/1 |
| NCAAF | total (MAE) | live | 75 | 10.28 | 8.40 | +1.88 [+0.79, +3.04] | 49.9% | loses, in every game phase |
| NCAAF | spread (MAE) | live | 75 | 9.44 | 8.93 | +0.51 [-0.40, +1.40] | 54.3% | parity |
| NCAAF | moneyline (Brier) | live | 76 | 0.078 | 0.092 | -0.014 [-0.031, +0.002] | — | parity, leans model (same on fresh quotes) |
| NFL | margin (MAE) | pre | 15 | 12.59 | 10.80 | +1.79 [+0.09, +3.49] | 6/14 | loses (underpowered) |
| NFL | total (MAE) | pre | 15 | 14.94 | 12.37 | +2.57 [+0.35, +4.67] | 6/15 | loses (underpowered) |
| NFL | moneyline (Brier) | pre | 15 | 0.260 | 0.214 | +0.046 [-0.012, +0.101] | — | parity (underpowered) |
| NFL | props, two-sided (Brier) | pre | 15 games / 708 props | 0.270 | 0.249 | +0.021 [+0.002, +0.039] | edges >=5pp ROI -7.6% [-23, +10] | loses |
| NFL | anytime TD (Brier) | pre | 15 / 184 props | 0.179 | 0.162 (vigged) | +0.017 [+0.006, +0.029] | — | loses |
| NFL | any live market | live | — | — | — | — | — | unmeasurable: no NFL live ledger on production |

- **H4 is NOT FALSIFIED.** NCAAF totals lose to the close by 2.86 points of MAE;
  correlation with actual totals is 0.14. The best out-of-sample fix (heavy shrink to
  the mean, MAE -3.7 [-6.7, -0.9]) only reaches parity with the close.
- **The NFL units fix separates teams but did not improve accuracy.** On the same 15
  games: margin SD 0.97 -> 4.38, coin-flip games 100% -> 69%, but error +1.11
  [-0.76, +2.75] points WORSE than before; its favourite won 7/15 vs the market's 11/15.
- **NCAAF ratings are frozen at preseason.** The ratings behind weeks 1-3, including the
  week-3 CSV built 09-13, contain zero 2026 results; SP+ was already this value on
  08-19. Not the CFBD quota (#633's 09-03 correction stands). Week 2's margin gap
  (+2.55) is worse than week 1's (+0.99); CIs overlap.

**What the NCAAF `sim_view` buckets are, and whether the contradiction is informative.**
All three exist only where the row has no model edge; NCAAF reaches them because it
sizes on the market-fair price.
- `contradicts`: the sim's total is on the other side of the line by >=10% of the line.
- `unpriced`: a model number but no contradiction past 10%. It pools sim-agrees
  (+11.2%) with small disagreements (+43.3%), so its +18% is not the sim agreeing.
- `none`: no model number. Its FBS-vs-FCS part lost -25.0% over 48 games.
- On the ORDERS the contradiction looks informative: contradicted totals picks hit 28.8%
  (35 games, ROI -39.7%); the sim's side won 71% [52, 87] of them, 67% [48, 83] against
  the close, and the close moved toward the sim after 82%.
- On ALL GAMES it is not a signal to follow: across the 64 games where the projection
  was >=10% off the close, the sim's side won 51.6% [40, 63].
- As a VETO: dropping `contradicts` orders lifts the NCAAF totals book +6.6 ROI points
  [-1.0, +14.9]; dropping FCS totals lifts it similarly. Not established.

**Contradicts the ledger or code:**
- `paper_settlement`'s `SIM_VIEW_UNREACHABLE` / `verdict_reachability` note and
  `portfolio_commit._sim_view_of`'s docstring say contradicts/unpriced/none can never
  reach an order. FALSE for NCAAF: 1,406 orders sit there.
- `[ncaaf-margin-calibration]` says margins are calibrated (1.06x the market's spread).
  Against 2026 closes margins are 1.28x and totals 2.48x (not 1.67x).
- `NCAAF_MEASURED_SKILL` still says totals were "never scored" against the close, and
  its 2024 margin gap (+3.56) lies outside the 2026 CI, so the tooltip overstates it.
- A code note says NCAAF live probability is "unmeasurable, n=5": now measured on 76.
- `/api/portfolio/paper` holds 1,809 of the ledger's 1,865 orders; its dict keyed on
  `position_key` (`intelligence.py` ~L4352/L4420) can drop orders sharing a key. Read
  from code, not confirmed per order.
- The close cutoff uses OddsAPI's commence time, which is why 14 of 100 NCAAF closes
  are post-kickoff.

**Proposed (not implemented unless marked below):**
1. NCAAF totals have no skill: re-fit the scoring mechanism rather than damping inputs,
   and stop presenting the sim total as a view.
2. NCAAF margins are over-dispersed 1.28x: fit `SP_RATING_SCALE` walk-forward on 2025.
3. Add in-season NCAAF ratings (as-of PPA blend or the market-implied lane).
4. Pre-register the `contradicts` veto for market-fair NCAAF totals; decide at >=80
   games. Do not follow the sim.
5. Cut closes at the earlier of OddsAPI commence and ESPN kickoff; fix the paper
   payload's order drop.
6. NFL props: anchor to the market or keep them non-stakeable — a user decision (left
   stakeable 09-09). Week 1 lost -7.6% on edges, matching the 2023-25 backtest (-7.35%);
   the +25.5% on 15 settled prop orders is noise.
7. NFL game lines stay display-only; re-read at ~60 games.

**Fewer than 30 games:** everything NFL (15), NCAAF follow-the-sim at a 25% gap (19),
NCAAF week-2 moneyline (25), the order sub-buckets (20-26 each), the contradicts x CLV
splits (25/7/7). The contradicts bucket itself is 35 games.

---

**Soccer, proposed, not implemented:** keep 1X2 model edges unpublished; fix favourite
under-dispersion by widening the rating spread and re-fit in the leak-free 1,112-match
harness (not on this window, which fails out of sample); treat totals "agrees" orders
as no signal; test a 10pp-disagreement refusal on live h2h with leave-one-date-out
first (the MLB precedent failed out of sample); snapshot the pregame projection on
first sighting; protect closes from the history cap; add the 4 aliases.
