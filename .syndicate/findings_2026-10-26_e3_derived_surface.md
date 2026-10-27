# FINDINGS -- E3: are Kalshi / Polymarket DERIVED contracts mispriced against a surface built on the sharp main line? (lane `e3-derived-surface`, 2026-10-26)

Decision Engine plan §4 **E3**, §3 L1 (price surface), §2 P7. OFFLINE, read-only on production (fleet
`~/syndicate-prod/data` at nice 19 / ionice idle; Kalshi PUBLIC unauthenticated GETs only). No deploy, restart or env
edit. No OddsAPI call.

| | |
|---|---|
| **Pre-registration** | `.syndicate/findings_2026-10-26_e3_derived_surface_preregistration.md`, committed **`f9ee12af` (22:28:14Z)** before any surface x venue x outcome join. Amendment **A1 `ba4f9d79` (22:55:53Z)**, before any join, covers team totals, per-series overtime rules, two-resolution candles, same-date identity and the loaders' history choices. `8975bfe2` corrects A1's timestamp to the read clock. |
| **Code** | `50ec3f30` on main: `scripts/e3_derived_surface.py` (math, fleet extraction, Kalshi fetch, surfaces, scoring, report); fleet loaders `scripts/e3_sim_loaders.py`, `scripts/e3_history_loaders.py`, `scripts/e3_window_loaders.py`; `tests/test_e3_derived_surface.py` (23 hermetic tests). |
| **Window** | Games with commence 2026-09-30T00:00Z .. 2026-10-26T08:00Z. Decision time t60 = commence - 60 min (PRIMARY), t15 beside it. |
| **Run** | Fleet extraction 22:20-22:31Z; Kalshi pull 22:49Z-00:20Z (31,247 public GETs by the main pull plus two side pulls, throttled to ~3-4/s); final scoring 00:21Z (10-27). |
| **Wired anywhere?** | **No.** Nothing imports the module. |

## Verdict

**E3 is KILLED by the registered rule, on every registered population.** That covers Kalshi on both tiers, both
arms and both decision times, and Polymarket (indicative).
- **Kalshi, Tier S (Pinnacle-anchored, PRIMARY):** priced off Pinnacle's main line, both surfaces lose to Kalshi's own mid on held-out outcomes:
  - parametric: **+0.0051 nats [+0.0026, +0.0075]**;
  - sim-shaped: **+0.0069 [+0.0036, +0.0102]**;
  - rests on 26,708 rungs / 243 games / 26 dates.
- **Kalshi, Tier C (consensus-anchored):** the parametric surface **ties** the mid (+0.0006 [-0.0013, +0.0026], 29,199 / 611 games); the sim shape loses (+0.0032 [+0.0003, +0.0060]).
- **EV:** no predicted-EV band makes money at the venue's ask after fees. Every Kalshi band's realised return is between -15% and +2%. Not one Bonferroni lower bound is above 0.

**Why there is nothing to take:**
- The surfaces sit a median **0.9-2.1pp** from the Kalshi mid.
- Crossing costs a median **1.9-2.7c** (half the spread plus the fee).
- Where the two disagree, the venue is at least as right as the surface.
- Even **Pinnacle's own alt-ladder price** for the same rung does not beat Kalshi's mid: +0.011 [-0.003, +0.033], 166 rungs / 30 games.

| Venue, tier, arm (t60) | Verdict | Log-loss n / games / dates | dLL vs venue mid (nats) [95%] | Best predicted-EV band: realised fee-net return [95%] (Bonferroni lower bound) |
|---|---|---|---|---|
| Kalshi S, (a) parametric | **KILL** (LL fails, EV fails) | 26,708 / 243 / 26 | +0.0051 [+0.0026, +0.0075] | [0, 2%): -6.7% [-11.1, -2.0] (-12.2), n 3,553 |
| Kalshi S, (b) sim shape | **KILL** (LL fails, EV fails) | 25,751 / 237 / 25 | +0.0069 [+0.0036, +0.0102] | [0, 2%): -4.2% [-7.0, -1.5] (-7.8), n 5,224 |
| Kalshi C, (a) parametric | **KILL** (LL fails, EV fails) | 29,199 / 611 / 26 | +0.0006 [-0.0013, +0.0026] | [5, 10%): +0.7% [-14.4, +17.7] (-17.9), n 1,487 |
| Kalshi C, (b) sim shape | **KILL** (LL fails, EV fails) | 19,146 / 330 / 24 | +0.0032 [+0.0003, +0.0060] | [0, 2%): -2.7% [-7.1, +1.5] (-8.1), n 2,873 |
| Polymarket S, (a) *indicative* | KILL | 2,212 / 52 / 21 | +0.0031 [-0.0086, +0.0126] | [0, 2%): +5.1% [-5.8, +16.5] (-9.6), n 411 |
| Polymarket S, (b) *indicative* | KILL | 2,162 / 49 / 19 | +0.0033 [-0.0109, +0.0149] | [0, 2%): -8.3% [-16.1, +1.1] (-17.9) |
| Polymarket C, (a) *indicative* | KILL | 15,282 / 233 / 26 | -0.0011 [-0.0034, +0.0012] | [10%+): +9.4% [-10.6, +30.6] (-14.9), n 2,152 |
| Polymarket C, (b) *indicative* | KILL | 10,755 / 93 / 19 | -0.0014 [-0.0048, +0.0024] | [10%+): +4.8% [-20.8, +33.0] (-25.6) |

**t15 (secondary)** reads the same:
- Kalshi S: (a) +0.0061 [+0.0027, +0.0097]; (b) +0.0083 [+0.0043, +0.0127].
- Kalshi C: (a) -0.0001 [-0.0023, +0.0021]; (b) +0.0028 [-0.0004, +0.0059].
- All eight t15 verdicts are KILL.

**Ladders counted once** (the best-EV rung per game x quantity, `#711` R1):
- Kalshi S: (a) -10.7% [-20.7, +1.0], 1,770 bets; (b) -11.0% [-18.8, -2.8].
- Kalshi C: (a) -0.5% [-10.5, +10.5]; (b) -5.4% [-18.1, +8.4].

## What it rests on (CLAUDE.md coverage rule)

| Source | Coverage |
|---|---|
| Book anchors at t60 (`book_quotes`: latest main pair at or before t_d; capture alive within 90 min) | **Tier S (Pinnacle):** ncaaf 235 games / 18 dates (10-01..10-24); mlb 32 / 20; nba 6 and nfl 4 (10-25 only); soccer 6. **Tier C:** nhl 177 / 26; soccer 367 / 17; nba 94 / 18; nfl 53 / 11; wnba 14 / 10. |
| Kalshi derived events (our venue logs, listed from the public API) | 6,485 in the window. 5,809 joined a book game through `match_event_blob`. 71,823 contracts; 100% of rungs were in our logs. |
| Kalshi book at t_d | Hourly (4 d) plus 1-minute (commence -180..-10 min) event candles. t60 `no_quote`: ncaaf 1,232; nhl 2,029 (period markets are thin); nfl 634; nba 664; soccer 618; wnba 113; mlb 57. |
| Polymarket | 49,120 spread / total rungs in the window. Identity only through a Kalshi-verified game: ncaaf refused 20,814 (CFB slug codes differ from Kalshi's), nba 2,482, nhl 1,634. |
| Sims (pregame copies) | ncaaf 229, nfl 58, nba 92, wnba 11, mlb 29, soccer 316. **nhl: none stored.** |
| History for the parametric arm | nfl 1,139 (2022-25, closing lines); nba 1,170 (2025-26 regular season, near-close consensus); ncaaf 792 (2025; DraftKings, else provider median); nhl 1,312 (period shares); soccer 9,681 (first-half share). wnba and mlb by window LODO. |
| Result validation (Kalshi `result` vs the joined game's score) | 66,838 checked, **66,815 agree**. Three games disagree and are excluded: an NCAAF CFBD line score (RUTG @ MD 10-17, Q4); a Kalshi MLB postponement re-mapping (TB @ CLE "originally 10-17"); one NHL game. Soccer and 26 NBA preseason games have no window score and are unvalidated. |

**What the primary verdict actually rests on:**
- The Tier S verdict is NCAAF: 27,746 of its rows, 204 games, 18 dates.
- MLB adds 28 postseason games.
- NBA / NFL / soccer add one date each (10-25).

## Results by sport x market type (Kalshi, t60)

Log-loss deltas are surface minus Kalshi mid, in 10⁻³ nats; **bold** = 95% CI below 0 (the surface beat the venue).
The EV column is arm (a)'s best band with >= 30 contracts. Cells with fewer than 100 log-loss contracts are omitted.

| tier | sport | phase | market type | LL n / games | arm a | arm b | best EV band, arm a |
|---|---|---|---|---|---|---|---|
| S | ncaaf | regular | full spreads | 5,789 / 202 | +3.2 [-1.9, +7.9] | +1.6 [-3.8, +7.0] | -10.0% [-28.7, +9.4] (644) |
| S | ncaaf | regular | segment spreads | 8,093 / 189 | +1.5 [-2.1, +5.3] | +1.9 [-2.7, +7.1] | -1.0% [-8.8, +7.3] (877) |
| S | ncaaf | regular | full totals | 3,727 / 202 | +8.4 [+3.2, +13.7] | +13.0 [+5.5, +20.6] | -13.4% [-24.9, -1.5] (520) |
| S | ncaaf | regular | segment totals | 6,302 / 190 | +8.2 [+4.4, +12.3] | +13.1 [+6.3, +20.9] | -4.1% [-9.2, +1.1] (1,113) |
| S | mlb | postseason | full spreads | 135 / 27 | +16.4 [-25.6, +62.0] | -1.4 [-31.8, +25.0] | +4.0% [-15.2, +19.4] (30) |
| S | mlb | postseason | F5 spreads | 112 / 28 | +0.9 [-35.7, +42.6] | +23.0 [+4.9, +40.5] | **+19.0% [+11.4, +25.2] (33)** |
| S | mlb | postseason | team totals | 378 / 27 | +0.9 [-16.6, +19.7] | n/a | +3.3% [-6.4, +11.6] (124) |
| S | mlb | postseason | full totals | 276 / 27 | +9.7 [-18.5, +43.9] | +18.2 [-0.9, +35.7] | +7.4% [-5.9, +18.5] (93) |
| S | mlb | postseason | F5 totals | 184 / 28 | +3.4 [-30.6, +44.1] | +17.6 [+5.4, +29.2] | +7.1% [-5.4, +18.5] (54) |
| C | nfl | regular | full spreads | 1,321 / 53 | +3.3 [-3.7, +9.9] | +4.6 [-3.2, +11.3] | -3.8% [-19.4, +13.3] (216) |
| C | nfl | regular | segment spreads | 3,747 / 53 | +1.8 [-3.3, +7.3] | +0.6 [-4.7, +5.9] | -1.1% [-13.9, +12.7] (430) |
| C | nfl | regular | full totals | 975 / 53 | +0.2 [-3.4, +3.6] | +2.1 [-4.3, +9.7] | -1.7% [-18.5, +20.4] (143) |
| C | nfl | regular | segment totals | 2,660 / 53 | -0.4 [-5.6, +5.1] | -0.2 [-5.8, +5.4] | -3.8% [-8.3, +1.0] (590) |
| C | nfl | regular | 1H team totals | 1,146 / 53 | +1.2 [-8.2, +12.9] | n/a | -2.1% [-7.9, +3.8] (395) |
| C | nba | regular | full spreads | 1,120 / 35 | +1.8 [-7.1, +9.2] | +7.6 [-17.0, +31.5] | -18.0% [-48.1, +13.7] (167) |
| C | nba | regular | segment spreads | 2,232 / 35 | -1.5 [-4.1, +1.0] | +5.5 [-2.2, +12.9] | +4.0% [-42.6, +68.3] (55) |
| C | nba | regular | team totals | 1,330 / 35 | -3.1 [-6.4, +0.1] | n/a | -1.4% [-22.7, +18.8] (89) |
| C | nba | regular | full totals | 995 / 35 | -2.2 [-7.9, +2.6] | +4.5 [-4.0, +13.4] | +31.9% [-76.1, +171.5] (56) |
| C | nba | regular | segment totals | 2,162 / 35 | -2.6 [-8.7, +3.4] | +2.0 [-5.7, +10.1] | +64.0% [-18.7, +150.4] (105) |
| C | nba | preseason | full spreads | 1,391 / 59 | -0.2 [-11.3, +12.1] | +4.5 [-9.6, +19.2] | +16.7% [-0.9, +32.7] (179) |
| C | nba | preseason | full totals | 1,199 / 59 | +3.2 [-3.6, +9.8] | +5.1 [-4.9, +14.5] | -27.6% [-64.2, +14.6] (82) |
| C | nhl | regular | full spreads (puck-line ladder) | 420 / 140 | +6.7 [-5.1, +19.3] | n/a | +1.0% [-6.2, +7.9] (152) |
| C | nhl | regular | period spreads | 840 / 140 | -3.7 [-7.7, +0.1] | n/a | +74.2% [+2.0, +149.2] (58) |
| C | nhl | preseason | period spreads | 216 / 36 | **-8.8 [-18.6, -0.4]** | n/a | no band >= 30 |
| C | nhl | regular | team totals | 1,400 / 140 | -0.3 [-3.3, +2.8] | n/a | +12.2% [-7.7, +31.2] (198) |
| C | nhl | regular | period totals | 1,260 / 140 | -0.8 [-3.2, +1.7] | n/a | -4.3% [-27.2, +17.8] (114) |
| C | soccer | all | full spreads | 902 / 246 | +1.1 [-1.9, +4.1] | +3.6 [-2.2, +9.6] | -20.6% [-59.5, +26.5] (102) |
| C | soccer | all | full totals | 1,218 / 228 | -0.2 [-1.9, +1.7] | +0.7 [-3.1, +4.9] | +1.8% [-52.7, +78.4] (38) |
| C | wnba | postseason | full / segment spreads, team totals | 109-234 / 11-12 | +19.6..+35.3, CIs above 0 | +10.5..+19.4 | no band >= 30 |

**Cell reads:**
- 82 cells are readable (>= 100 log-loss contracts / 15 games). **None passes both clauses.**
- Three pass one clause only. None of them survives the Bonferroni correction across cells on its other clause.
  1. **NHL preseason period spreads, arm (a):** the log-loss clause passes; it fails at the Bonferroni across 25 cells [-0.026, +0.004]. No EV band has >= 30 contracts.
  2. **MLB F5 spreads, arm (a), the [2, 5%) band:** +19.0%, Bonferroni lower bound across cells +7.5%, but only **33 contracts / 20 games**. Log loss fails (+0.9 [-35.7, +42.6]).
  3. **Polymarket NFL full-game totals, arm (b)** (indicative): the log-loss clause passes, -9.0 [-14.9, -2.8], Bonferroni [-17.0, -0.2]. Its EV clause fails.

  These are leads at most (§ Recommendation).
- **The NCAAF totals loss is the largest effect in the test, and it sits in the BODY of the ladder, not the tails.**
  - Full totals lose +8.4 / +13.0 and segment totals +8.2 / +13.1.
  - Split by rung distance (arm a): within 0.5 sd of the located mean +10.7 [+2.5, +20.4] (full) and +11.4 [+4.4, +18.7] (segments); 0.5-1.5 sd +6.7 / +8.4; beyond 1.5 sd +1.5 / +3.1 (not significant).
  - The main-line rung itself is excluded, so these are the rungs just around Pinnacle's t60 total.
  - So this is not a tail-shape failure. Near the line, **Kalshi's NCAAF total ladder carries information that Pinnacle's t60 total does not** (a later move, or a Pinnacle quote that our capture holds stale). That is an E1 question (whose price is sharper on NCAAF totals), not an E3 one.

## Engine read -- where the sim's SHAPE beats or loses to the parametric shape (for the sim owners)

Paired on the SAME Kalshi contracts at t60 (log-loss population), arm (b) minus arm (a), in nats; negative = the sim's
shape is better. The ratio column is the sim's per-game sd over the history sigma (median, from the stored
distributions).

| sport (sim draws, games) | spreads, full | spreads, segments | totals, full | totals, segments | sim sd / history sigma |
|---|---|---|---|---|---|
| ncaaf (300 seeds, 229) | -0.0015 [-0.0047, +0.0021] | +0.0005 [-0.0026, +0.0037] | +0.0044 [-0.0012, +0.0100] | +0.0047 [-0.0004, +0.0106] | **totals 0.84-0.87** (full, h1, q1, q2): too narrow; margins 0.90-1.01 |
| nfl (300, 58) | +0.0018 [-0.0016, +0.0052] | -0.0006 [-0.0035, +0.0021] | +0.0028 [-0.0038, +0.0100] | +0.0002 [-0.0037, +0.0041] | totals 0.88-0.93 except q1 / q3; margins 0.94-1.09 |
| nba (100-500, 92) | +0.0018 [-0.0105, +0.0132] | **+0.0073 [+0.0014, +0.0128]** | +0.0024 [-0.0019, +0.0067] | **+0.0047 [+0.0008, +0.0088]** | **margins 1.08-1.27**: too wide (full 1.27; halves 1.15-1.17); quarter totals 1.06-1.14 |
| wnba (100-500, 11) | -0.0141 [-0.060, +0.029] | -0.0280 [-0.065, +0.008] | -0.0055 [-0.027, +0.018] | **-0.0219 [-0.058, -0.001]** | (the parametric sigma rests on 12 LODO games) |
| mlb (1,000, 29) | -0.0148 [-0.086, +0.048] | +0.0339 [-0.014, +0.076] | +0.0042 [-0.050, +0.051] | +0.0083 [-0.036, +0.052] | F5 alt rungs: sim 1.5pp from Pinnacle's own alt price, the NB surface 4.5pp (52 rungs / 24 games) |
| soccer (400-sim pmf, 190) | +0.0013 [-0.0049, +0.0081] | n/a (1H: means only) | +0.0005 [-0.0034, +0.0044] | n/a | |
| nhl | **not available**: only period means and one probability are stored | | | | |

**Reading it:**
1. **Where history exists, the sim's shape beats a plain Normal / count surface nowhere.**
   - NCAAF, NFL and soccer are ties.
   - NBA loses significantly on segments, because its margins are 8-27% too wide.
   - Football totals lose (b - a not significant). That is consistent with the sims' totals being 7-16% too narrow: the sim's extra loss on NCAAF totals sits at 0.5-1.5 sd from the mean (+15.0 vs +6.7 x10⁻³ nats for arm a, full totals; +15.9 vs +8.4, segments), where a too-narrow distribution misprices most.
2. **Where history is thin, the sim helps.** WNBA's parametric sigma rests on 12 postseason games. It is the only sport where the sim's shape wins: segment totals, -0.0219 [-0.058, -0.001], on 11 games. That supports the plan's L1 claim ("where history is thin, the sim supplies the shape"), on a tiny sample.
3. **The MLB sim's F5 shape matches Pinnacle's own alt ladder** far better than the fitted NB: 1.5pp vs 4.5pp mean gap. Pooled over every rung Pinnacle quotes as an alt, the sim sits 1.3pp from Pinnacle and the parametric surface 2.0pp. Neither beats Kalshi's mid.
4. **Smoothing is not the problem.** The unsmoothed sim pmf (b0) is never better, and it is worse on NFL segment totals (+0.0099 [+0.0039, +0.0165]) and NCAAF segment totals (+0.0075 [+0.0017, +0.0141]). The stored 300-seed and 100-draw histograms are noisy.
5. **Leakage check (football sims written after kickoff, kept by registration):** post-kickoff files do no better.
   - NCAAF: post-kickoff files score +0.0037 vs the mid; files written before t_d score +0.0153.
   - NFL: +0.0019 and +0.0006.
6. **Reliability.** Both surfaces are calibrated within ~1-2pp per decile, and Kalshi's mid slightly better. The parametric arm's 0.436 decile realised 0.413.

**Work list for the sim owners** (each one its own item; none is promoted by E3):
- NCAAF / NFL: totals variance is too low in every segment. Check the scoring-rate dispersion; a fixed-seed 300-draw run also understates tails.
- NBA: margins are too wide, full game 1.27x the residual sigma about a near-close line. The sim is anchored to the market mean (weight 0.95), so the excess variance is in the possession / efficiency noise.
- NHL: store per-game draws (or period pmfs). Without them the sim cannot be graded on shape at all.
- NBA: store more than 100 draws. 67 of 92 games have n = 100, which is too coarse to price a ladder.
- MLB team totals: only 50 joint samples are stored, so the sim cannot price them.
- Basketball / football: no team-total histogram is stored.

## Recommendation (every line is its own decision; nothing here switches a market off or on)

1. **Do not build a derived-market TAKER on a sharp-anchored surface.** E3 is killed by the registered rule on Kalshi in every tier x arm x decision time. On Kalshi's derived rungs, the venue's own two-sided mid is at least as good a probability as Pinnacle's main line plus a shape. It also beats Pinnacle's own alt price where one exists. No band of predicted edge survives the ask plus the fee.
2. **For the Decision Engine's L1 fair on a derived Kalshi rung, use the venue's own two-sided mid** (the plan's fallback 3, after the identity check this test validated on 66,815 of 66,838 results) rather than a surface. The surface is not more accurate, and it costs a model. A Suggested line that bets a derived rung at the ask is then -EV by the half spread plus the fee (median 1.9-2.7c) unless another, separately earned signal moves it.
3. **The only structural way to earn on derived rungs is the spread** (E2: maker), not the price.
   - The median derived-rung book is 1c wide on full-game ladders and 3c on segments. Segment books are wide enough that a maker quoting near the mid is the testable idea.
   - That belongs to the maker shadow (`kalshi-maker-shadow-paper`, `#735`), with this surface or the mid as its reference. E3 adds no taker strategy.
4. **Leads, not promotions** (each needs a forward pre-registered read before any money; recorded in the todo):
   - (a) **NHL period spreads:** the Poisson surface beats Kalshi's mid on log loss in preseason (Bonferroni fails) and leans that way in the regular season (-3.7 [-7.7, +0.1], 140 games). No EV yet; Kalshi period books are often unquoted at t60.
   - (b) **MLB F5 spreads, arm (a)** [2, 5%) band: +19% on 33 contracts / 20 games, but the cell's log loss fails. The MLB postseason is over, so the next read is the 2027 season.
   - (c) **For E1 / Syndicate Fair (not E3):** on NCAAF totals, Kalshi's ladder just around the line beats a price anchored on Pinnacle's t60 total (+10.7 [+2.5, +20.4] x10⁻³ nats within 0.5 sd). Whether Pinnacle's NCAAF total is stale in our capture, or Kalshi simply moves later, is a question for `fair-price-v2` / the Pinnacle forward test. Pinnacle is not automatically the sharper price on every market.
   - The script is reusable: re-running `score` on a later window with the same constants is the forward read.
5. **Read with E4 (`#740`, closed the same evening).** E4 found the sims' JOINT distribution beats independence only on structural pairs, and a measured copula ties or beats it. E3 finds the sims' MARGINAL shapes do not beat a Normal or count surface either. Together:
   - the sims' distributional output is not a venue-pricing edge today;
   - its value is the engine work list above, and the thin-history case (WNBA here).

## Found along the way

- **CFBD line scores can be wrong:** RUTG @ MD on 10-17 has a 7-7 fourth quarter that Kalshi's settled Q4 markets contradict. Validation caught it, and it matters to any segment backtest that grades on CFBD line scores.
- **A Kalshi "originally scheduled" event can settle on a different game** after a postponement (MLB TB @ CLE, 10-16 / 10-17). Validation caught it; the production join keys on the ticker date.
- **WNBA's 2nd-half series EXCLUDE overtime; NBA's include it.** A segment join that assumes one rule per family mis-grades one of the two.
- **Kalshi throttles unauthenticated public GETs to ~3-4/s.** It also pages event candlesticks by market x period, so a 7-day 1-minute window costs ~60 pages per event. Hourly plus a short 1-minute window costs ~3.
- **The fleet's Polymarket venue logs** in one JSON dump hit `Cannot allocate memory` (no harm; the dump was streamed per sport instead).

## Caveats

- **The Tier S verdict is NCAAF's.** NCAAF supplies 204 of 243 games. MLB adds 28; NBA / NFL / soccer add one Pinnacle date each (10-25). The NBA regular season and NFL stage-2 read with Pinnacle anchors is not here.
- **NBA's history lines are near-close, not closes** (`asof/game_odds`). That inflates the NBA sigma (14.0 vs the ~12 typical about a close) and penalises arm (a) on NBA, mildly.
- **WNBA and MLB fit their parameters by window LODO** (12 / ~28 games); their parametric arm is weak by construction.
- **Polymarket prices are our own recorded points** (48-point cap, board-loop cadence, no depth). Its verdict is INDICATIVE and never overrides Kalshi's.
- **The EV test buys every qualifying rung.** Rungs of one ladder are one bet several times over; the CIs are game-clustered, and the one-per-axis variant is reported.
- **Fees:** Kalshi segment series without a declared multiplier are charged the full 0.07 rate (`fee_is_upper_bound`). If a segment multiplier were 0.5, fee-net returns there would improve by roughly 0.5-0.9c. No band is close enough for that to flip a verdict.

## Bugs fixed before the final run (no registered definition changed)

1. Cell reads first used the POOLED thresholds (300 / 30). They now use the registered cell thresholds (100 / 15). The registered Bonferroni-across-cells CI was added to every readable cell.
2. The registered Pinnacle-alt diagnostic (§4) was added after the first shakedown.

Raw output (scratch, not in git):
- `C:\tmp\e3\out\rows.jsonl` and `report.json`, and the formatted `report.md`;
- the Kalshi cache `C:\tmp\e3\kcache\`;
- the extracts `C:\tmp\e3\extract\`.

## Owed

- **Todo `#741`** carries the leads and the engine work list.
- **Forward re-reads, when they become possible:**
  - NHL period spreads after 30 more regular-season days;
  - MLB F5 spreads next season;
  - a Tier S re-run once Pinnacle has covered NBA / NFL / soccer for a month (same script, same constants).
