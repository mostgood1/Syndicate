# FINDINGS — Layer 2 board, weekend of Sat 2026-10-10 / Sun 2026-10-11: what it surfaced, how it graded, and whether the right projections were on each row

Session `9e18a0e7`, 2026-10-13. **No lane**: read-only, answering the user's request to "assess every sport, games vs props,
live vs pregame, by bet type, and check that pregame stats and live projections/actuals map to the correct opportunity."
Substrate: the **fleet** (`http://127.0.0.1:10000`, production since 2026-09-30) plus a code read of `origin/main` `d4fceef4`.
Nothing under `data/` was used.

## What every number rests on

| dataset | what | how |
|---|---|---|
| P. published | `clv_openings`: every row the board PUBLISHED, first sighting per identity per phase, graded with the production grader and settlers. 36,247 graded rows on 177 games with a Central kickoff date of 10-10 or 10-11 | `score_ranking_backtest.py pull --start 2026-10-10 --end 2026-10-11 --sports mlb,nfl,ncaaf,soccer,wnba,nhl,nba --source openings` |
| R. population | `opportunity_population`: every row the board PRICED, published or not, with its score `sc`. 168,291 records, 107,912 graded | same command, `--source recorder` |
| S. served | `/api/board/layer2-shortlist?date=…&limit=2000` for both dates | fetched 2026-10-13 14:55Z |

**What these datasets cannot tell you:**
- **S is not "Saturday's board".** A past date's shortlist artifact is overwritten by every later build: the 10-10 artifact was written
  at 10-11 09:09Z and the 10-11 artifact at 10-12 04:59Z, after the games. Every MLB, NHL and NBA row on it is therefore `dead`
  (game_final), and its rows belong to the following days. S is used here only to check how projections attach to rows; it says
  nothing about what was shown on Saturday. P and R are the record.
- **The sample is small.** It is 13 NFL games, 46 NCAAF, about 88 soccer, 17 NHL, 11 NBA (preseason) and 2 MLB (postseason).
  Bets on the same game are correlated, so a bucket's real sample is closer to its game count than its row count. Intervals
  are 95% bootstraps over games.
- **ROI is flat 1 unit at the published price.** Longshot buckets swing hard on single results.
- The openings record carries no `sc`, so score tiers come from R. That is the priced population ranked by score within
  sport × date × phase, which stands in for the top of the board.

## 1. Headline

- **Published, everything (P): ROI −10.0% [−12.2, −8.0] on 36,247 rows and 177 games.** Hit rate 45.5% against a 48.5% breakeven.
- **92% of published rows had negative market EV.** Game rows: 12,600 of 15,163 at EV < 0. Props: 20,693 of 21,084. The value
  floors allow this: `min_value_pct −2`, and the per-family floors are hold × 1.25, which comes to −5% to −9.3%. For soccer moneylines
  on 10-11 the floor reached −23.6%, because the measured median hold was −18.9% (see §5).
- **The EV signal does point the right way, and the floor lets the losing rows in.** Population, opportunity lane, graded:

  | EV band | live ROI | pregame ROI |
  |---|---|---|
  | < −5% | −10.9% (30,636 rows) | −23.6% (26,411) |
  | −5..0 | −2.2% | −5.8% |
  | 0..2 | −8.4% | −6.2% |
  | 2..5 | +0.9% | +1.7% |
  | 5..10 | +3.3% | −4.1% |
  | 10..50 | +10.2% | +7.1% |

  Every positive band's interval spans zero. Every band below zero is reliably negative.

## 2. By sport × games/props × phase (P, published)

| sport | kind | phase | rows | games | hit / breakeven | ROI [95%] |
|---|---|---|---|---|---|---|
| NFL | game | pregame | 797 | 13 | 50.1 / 52.0 | −5.1 [−7.1, −2.9] |
| NFL | game | live | 1,380 | 9 | 50.0 / 51.9 | −5.0 [−6.6, −3.1] |
| NFL | prop | pregame | 4,979 | 13 | 49.3 / 52.7 | −6.7 [−9.9, −3.6] |
| NFL | prop | live | 6,744 | 9 | 50.0 / 53.1 | −5.6 [−6.4, −4.9] |
| NCAAF | game | pregame | 2,929 | 46 | 50.1 / 51.9 | −2.7 [−5.3, −0.1] |
| NCAAF | game | live | 4,382 | 40 | 50.4 / 52.8 | −3.4 [−5.6, −1.2] |
| NCAAF | prop | pregame | 2,271 | 26 | 50.6 / 53.2 | −4.7 [−6.0, −3.2] |
| Soccer | game | pregame | 1,644 | 88 | 43.9 / 45.6 | −6.8 [−14.4, +2.6] |
| Soccer | game | live | 1,577 | 86 | 47.0 / 48.0 | −6.2 [−11.9, +0.4] |
| **Soccer** | **prop** | **pregame** | **4,251** | 63 | 17.6 / 23.9 | **−38.5 [−45.5, −31.1]** |
| Soccer | prop | live | 94 | 20 | 6.4 / 14.0 | −72.0 |
| NHL | game | pregame | 133 | 17 | 49.6 / 51.3 | −0.8 [−6.1, +5.8] |
| NHL | game | live | 83 | 11 | 51.8 / 50.3 | +4.5 [−12.2, +19.6] |
| NHL | prop | pregame | 2,274 | 17 | 47.8 / 51.0 | −10.0 [−15.1, −3.5] |
| NBA (pre) | game | pregame | 2,000 | 11 | 50.0 / 52.6 | −10.4 [−23.6, +4.8] |
| MLB (post) | game+prop | pregame | 624 | 2 | — | −20% (2 games, no interval) |

The only cells near or above zero were NHL game lines, NCAAF pregame full-game totals (+0.7%), NCAAF pregame full-game h2h (+21.3% [−0.4, +50.1]),
NFL pregame q1 totals (+2.8%) and NFL pregame rushing yards (−0.1%). None is significant.

## 3. Does the score put winners on top? (R, opportunity lane, ranked by `sc` within sport × date × phase)

**CORRECTED the same session.** The first pass ranked the PRE-FILTER population and reported the live top 25 at +246.9%,
driven by venue asks of a few cents (Polymarket/Kalshi +1900..+9900, EV +900%..+4,800%). **None of those rows was ever
published**: the board's existing implausible-book rule (`select_shortlist`, implied book total < 95%) refuses any row
above +5.26% EV, and the published maximum over both days was exactly 5.26%. They were never on the board. The tiers
below apply that same cut (EV <= 5.2632) before ranking:

| tier (per sport × date × phase) | live ROI [95%] | pregame ROI [95%] |
|---|---|---|
| top 25 | −15.2% [−35.0, +6.3] | −26.7% [−45.0, −0.5] |
| 26–100 | −4.7% | −9.0% |
| 101–500 | −5.1% | −12.0% |
| rest | −9.7% | −21.1% |

- **The score's top tiers are no better than the rows below them.** Same shape as the 09-21 finding (non-monotone deciles).
- A top-N per sport cannot select profit by construction: when a sport has few positive-EV lines, top N fills with
  negative ones. Ranking only by market EV (no model rows) did not fix it either (top 100: pregame −8.8%, live −1.4%).
- The pregame top 25 is crowded with markets that have no working model: NBA preseason `spreads_alt`, NHL `goals`, soccer
  corners, MLB home runs.
- **NBA lists both sides of every alt line** at identical market EV. Of the published NBA game rows, 898 had the model
  AGAINST the pick (−18.6% [−31.1, −4.5]) and 1,160 had none (−3.9%); none had it FOR.
- **Model-against already ranks low where the model is the ranking term.** On the served boards, one-sided rows ranked on
  the model's edge (`ev_basis = model_edge`) with the model against: 0 of 858 (10-10) and 0 of 358 (10-11) had a
  positive score, median rank ~1,000–1,200. On two-sided rows the model enters only as the capped sim term
  (`_SCORE_SIM_WEIGHT`, which `[sim-weight-clv-decomposition]` measured and said to leave alone), so a market-EV row the
  model disagrees with can still rank #1 (10-11: soccer BTTS No, EV +3.7, model −1.45).

## 4. The model's direction vs the pick (P, published)

| sport / kind | model FOR the pick | model AGAINST the pick | no model |
|---|---|---|---|
| **Soccer props** | −6.1% (591 rows) | **−44.4% (3,754 rows)** | — |
| **Soccer games** | +1.6% (590) | **−23.7% [−38.6, −9.7] (289)** | −6.4% (2,342) |
| NFL games | −10.1% (401) | +1.1% (323) | −5.1% |
| NFL props | −9.2% (2,191) | −2.1% (1,071) | −5.7% (8,461) |
| NCAAF games | −5.6% | −1.1% | −2.7% |
| NHL props | −9.4% | −10.6% | −7.5% |
| NBA games (preseason) | — (0 rows) | −18.6% [−31.1, −4.5] (898) | −3.9% (1,160) |

- **Soccer is where the model clearly beats the board, and the board ignores it.** On the served board 82–94% of soccer prop rows
  have the model AGAINST the pick (10-10: 857 of 1,048; 10-11: 870 of 924). The cause is that soccer shots, SOT and assists are
  one-sided "over" markets. The model says under at every line: for SOT over 0.5 the median model probability is 0.214 against 0.25
  implied, and for shots over 2.5 it is 0.021 against 0.071. The rows still pass the −9.27% `player_prop` floor, and v1 `score` ranks
  some of them in the top 15 on the strength of a +14% edge against the modelled fair. **Withdrawn as a removal rule (PRIME DIRECTIVE, see §7):** these rows already rank at the bottom (§3); they are on the
  board only because the 2,000-row cap exceeds the count of positive-score rows.
- NFL and NCAAF show the opposite (model-for loses more). That is 13 and 46 games and every interval spans zero, so it is not
  evidence the NFL model is inverted. It is evidence the NFL/NCAAF models are not yet adding measurable edge over the market on this
  sample. It needs the weekly backtest, not a weekend.

## 5. Mapping: are the right stats on each row?

Code read on `origin/main` by a subagent. The soccer finding was re-verified by grep, and the per-row behaviour on served payload S.

| sport | segment markets | pregame projection | live projection | live ACTUAL on the row |
|---|---|---|---|---|
| NFL | h1/h2/q1–q4 | **segment-specific** `smartsim2_<seg>_empirical` (`nfl_segment_projections.py:125`; full-game join skips them at `nfl_game_projections.py:410`) — verified on S (e.g. PHI@JAX q1 total proj 9.18, h1 21.66, full 44.26) | refused (`live_gameline_join.py:1517-1548`) | none |
| NCAAF | h1/h2/q1–q4 | segment-specific (`ncaaf/segment_projections.py`, skip at `ncaaf/game_projections.py:706`) | refused | none |
| MLB | first1/3/5 | segment-specific (`prop_projections.py:952`) | first5 only, behind `first5_pricing_enabled()` | none |
| NBA / WNBA | q / h | segment-specific histograms | NBA not in `_LIVE_GAMELINE_SPORTS`; WNBA refused | none |
| NHL | p1–p3 | none, by design (`nhl/game_projections.py:399`) | refused | none |
| **Soccer** | **h1/h2** | **FULL-GAME numbers reused — BUG** | refused, but the full-game pregame edge stays on the row | none |

- **CONFIRMED BUG: soccer segment rows are priced with full-match outputs.** `attach_soccer_projections`
  (`syndicate/features/shared/soccer_projections.py:1237`; the loop starts around `:1400`) never reads `row["segment"]`. The word does
  not appear in the file. On S: NFO@CRY h1 spread home 0.0 carries the full-game `projected 0.33 / p 0.596`, and
  `_price_against_market` (`:1683`) stamps `model_edge_pct = +11.68` on it. EVE@HUL h1 over 1.0 shows p(over) 0.934 and h1 over 0.5 shows 0.945.
  Those are full-match goal probabilities; a first half is roughly 0.70–0.75 for over 0.5. MON@LAZ h1 h2h shows the full-match 0.6275.
  The published result was soccer live h2h h1 −26.5% (76 rows / 41 games). **Fix:** at the top of the loop, skip any row whose
  `normalize_segment(segment) != "full"` and count it, as NFL, NCAAF and NHL already do. Price h1 again only once the match sim
  publishes per-half scorelines. It is event-timed, so it can.
- **Interval totals do not show interval ACTUALS anywhere.** The board's Actual column reads only `projection.actual_so_far`
  (`layer2_board.py:3567-3578`), and only the live PROP join writes it (`live_projection_join.py:683`). A live q2 or h1 total renders a
  dash, and the only score on the card is the full-game chip score (`intelligence.html:2919`). `segment_actuals.py` already computes
  per-segment actuals for grading and the pollers, but the board never calls it. Nothing shows a wrong number; the period number is
  simply absent. Wiring `segment_actuals` into the live gameline enrichment (`actual_so_far` = the segment score so far) would make
  an interval total readable live.
- Pregame prop stat mapping looks right. Projected ÷ line medians: NFL receptions 0.99, receiving yards 1.09, rushing yards 0.98,
  passing yards 1.08, passing attempts 0.92. NCAAF and NFL totals 0.97. No market is mapped to the wrong stat scale.
- Lead, not verified: the live prop join's key has no segment, so a segmented prop market would pick up the full-game live
  projection. No such market was seen on the board.

## 6. Other defects found along the way

1. ~~Venue cent-ask artifacts are top of the live board~~ **RETRACTED (same session): never published.** The implausible-book
   rule already refuses them; they exist only in the pre-filter population recorder. A recorder-based analysis must apply
   the shortlist's own filters before ranking, or it grades rows the board never showed.
2. **The soccer moneyline floor went to −23.6% on 10-11** because `measured_hold` came out at −18.9% median. A negative hold means
   the sides were mis-paired (3-way h2h devigged as 2-way, or a draw missing). The floor should clamp the derived hold to ≥ 0.
3. **NBA lists both sides of the same line** at negative EV. NBA pregame game rows filled the whole 2,000-row per-sport cap and
   none of them had the model FOR the pick.
4. **The past-date shortlist is overwritten after the slate** (§ datasets). Anyone reading "Saturday's board" off
   `/api/board/layer2-shortlist?date=2026-10-10` gets Sunday morning's build. This is not a defect for serving. It is a trap for any review.
5. In the population, 92 rows had EV `none` and a breakeven around 95% (prices near −2000) and lost −48%. Small, unexplained, and worth a look.

## 7. What was done, and what the board should do to make profit

**Standing rule checked AFTER the first draft of this section (it should have been checked before):** `learnings.md`
2026-10-05 PRIME DIRECTIVE, "no market is withheld; accuracy ranks, it never hides". The first draft's items 1 and 2
(drop soccer model-against rows; floor EV at 0 where no model is validated) were market-level withholds and are
withdrawn. The user chose "rank, don't hide"; §3 shows ranking already demotes model-against rows wherever the model is
the ranking term, so no score change was made.

Shipped to `main` (NOT loaded on the fleet yet):
- `995d5b47` lane `soccer-segment-projection-guard`: soccer h1/h2 rows no longer carry full-match projections (§5).
- `d6a5ffc5` lane `layer2-live-segment-actuals`: live interval totals show their own interval's score in Actual (§5).

### Where profit is on this weekend's data (P, published)

| slice | rows | games | ROI [95%] |
|---|---|---|---|
| all published | 36,247 | 177 | −10.0% [−12.2, −8.0] |
| **published, market EV ≥ +2%** | 1,274 (3.5%) | 144 | **+4.6% [−4.1, +14.0]** |
| … live | 887 | 122 | **+9.9% [+1.7, +18.0]** |
| … pregame | 387 | 109 | −7.5% [−25.9, +9.7] |
| … priced at an exchange | 538 | 83 | **+9.6% [+1.2, +17.8]** |
| … NCAAF | 683 | 46 | **+14.0% [+4.8, +24.0]** |
| … fair = `book_margin_model` (one-sided) | 16 | 11 | −100% |
| … model FOR / AGAINST / none | 150 / 204 / 920 | | −4.8% / +8.2% / +5.3% (all n.s.) |
| staked paper book, 10-10..10-14 (`ledger-summary?days=5`) | 709 settled | | −2.5% ($−226.73 on $9,104); soccer games +17.0%, NCAAF game lines −6.3% on $4,009, NHL −35% |

The board's EV against a robust two-sided fair is the one signal that pays here. Model agreement adds nothing measurable at
this sample. One-sided `book_margin_model` fairs are overstated (−100% here; 8.5 pp in `[layer2-score-outcomes]`).
Caveat that must travel with this: `[layer2-score-outcomes]` (09-01..09-20) found main pregame lines at EV 2–5.27% at
−21.2% [−37, −3]. Pregame EV ≥ 2 is NOT established as profitable; live and exchange-priced are the strongest cells.

### The design this supports (proposed, not built)

1. **Board ≠ bet list.** The board keeps serving every line ranked (prime directive). Profit is a property of a SEPARATE,
   line-level selection, and that is what gets graded.
2. **"Suggested opps" = a line-level flag, computed once at build** in `layer2_board`, stored on each row with its
   reasons, and read by three consumers so they cannot drift: the board's All / Suggested filter, the paper
   portfolio's eligibility, and the nightly grader. Candidate criteria, all properties of the LINE: market EV ≥ +2%
   (fee-net at venues) against a two-sided fair (consensus or sharp anchor; not `book_margin_model`), a quote seen
   within the freshness ceiling, and not a both-sides-of-one-line pair.
3. **Graduate on evidence, per cell:** the daily optimizer grades Suggested by sport × phase × market family on ROI and
   CLV, and the flag's thresholds move only on a validated reading. A threshold is not a withhold; every line stays on
   the board.
4. Re-read after the next two weekends. Every positive cell above rests on one weekend.

## 8. Suggested, backtested over the week 10-06..10-12 (recorder, read-only) `[added same session, 2026-10-13 ~17:4xZ]`

Rule applied to every priced record as `_stamp_suggested` would have: opportunity lane, market EV in [+2, +5.26]
(plausibility cut), two-sided fair, fee-net >= 2 where a fee applies, one side per line per capture day; graded on the
FIRST QUALIFYING sighting (the price the paper book would have taken). Baseline = deterministic 1-in-10 sample of all
opportunity-lane rows under the same plausibility cut. 385,117 records; script `sg_backtest.py` (scratchpad, wraps
`score_ranking_backtest.py pull`).

| set | bets | games | hit / break-even | ROI [95%, by game] |
|---|---|---|---|---|
| **Suggested** | 843 (~120/day) | 162 | 42.6 / 43.2 | **-4.1% [-12.8, +7.5]** (-34.6 units) |
| baseline (board) | 10,317 | 251 | 42.2 / 47.2 | -16.8% [-21.0, -13.4] |

Suggested cells (all intervals span zero): exchange-priced +8.2% (237), props +4.7% (284), game lines -8.6% (559), NFL live
+7.7% (204), NCAAF pregame +6.4% (201), soccer -19.4% (122), WNBA -28.2% (87, 4 games), NHL live -29.7% (20).

- **The flag removes most of the loss (about -17% -> -4%) but is NOT shown profitable over this week.** It is a better bet
  list than the board, not yet a winning one.
- Limits: 111 suggested rows (mostly NCAAF) fell out `extra_team_unresolved` because the worktree has no `data/` team
  registry; flat 1-unit staking; fees are not netted in `pnl` (only 9 fee-venue rows qualified).
