# Layer 2 edge deep dive -- where the edge is, why the board has not found it, and what to build -- 2026-10-13

Lane `layer2-edge-deep-dive` (session 9e18a0e7). Hypotheses H1-H5 committed to the lane (`ffde78ff`) before outcomes were
read. User request: "an extremely deep dive into how we make the layer 2 board a truly game changing betting product ...
an external analysis in addition to the internal audit". Read-only; substrate = the fleet (production since 09-30), plus
code on origin/main. Four parallel research tracks (external practice; odds coverage; prop/matchup inputs; model-vs-market
ledger) are summarised in §4-§6.

## 0. The answer in five lines

1. **The board's "+EV" is mostly a devig artifact.** The fair is the median of MULTIPLICATIVE de-vigs, which carries a
   favourite-longshot bias; 94% of the pregame Suggested bets were plus-money. Against a power-devigged closing consensus
   those bets were worth **-4.0%**; against the multiplicative close they "looked" +1.9%. Realized: -9.0%.
2. **Pregame, line-shopping our ~5-17 US books against their own consensus is roughly break-even at best.** No selection
   rule beat the power-devigged close with a CI above zero. A sharp reference is almost absent: Pinnacle priced 356 of
   21,426 weekend pregame lines (NHL props 180, NCAAF game lines 168, MLB 8); no Circa, BookMaker or pick'em site at all.
3. **Live is where the measured return is.** Suggested live +3.1% [-5.6, +11.8] (live props +7.3%), pregame -11.6%
   [-20.6, -1.0] -- the one significant cell, and it is negative.
4. **The models do not beat the market in any measured cell** (see §5), and advanced data has added nothing measurable
   (season metrics, xG, GSAx, EPA, SP+ all null). Model agreement inside +EV rows adds nothing on game lines.
5. **So the edge has to come from information the closing market does not yet have when we bet** -- speed (news, live
   state), better reference prices (sharp books), and narrow prop niches where we can prove a model beats the close --
   not from more modelling of what the market already prices.

## 1. Data and definitions

| dataset | what | size |
|---|---|---|
| Suggested study | recorder 09-21..10-12 (graded window 09-30..10-12), Suggested rule applied, first qualifying sighting | 2,030 bets / 282 games (1,257 live, 773 pregame) |
| Weekend population | recorder 10-10/11 pregame, every priced line | 40,578 lines; 21,426 with a sighting-time fair; 18,814 with a closing fair |
| Published CLV | `/api/ops/clv/report?rows=1` 09-21..10-12, same-book pregame closes | 182,679 rows / 408 events |
| Quote logs | `<sport>_source/tracking/book_quotes/<date>.jsonl(.gz)` on the fleet disk: every price CHANGE per book | ~780 MB gz, 7 sports |

- **Closing fair** = for each line, every book's LAST quote change before commence (dropped if > 6 h stale), de-vigged
  per book (two- or three-way, both sides required, hold 0.9-1.35), median across books. Computed both MULTIPLICATIVE
  (what the board uses) and POWER (`fair_i = imp_i^k`, sum 1). **EV@close** = fair_close x decimal price - 1: the
  industry's standard "did this bet have positive expected value" measurement.
- **Same-book CLV** (the CLV report's `clv_pct`) is the change in the SAME book's implied probability from our price to
  its close. It still contains that book's vig, so it overstates value -- it measures "the outlier price moved", not
  "the bet was +EV".
- Intervals: 95% bootstraps over games. One weekend / three weeks: every cell is noisy; direction is reported only where
  the interval says so.

## 2. Findings from the quote logs

### 2a. Calibration: power devig is better calibrated than multiplicative (18,814 pregame lines, 177 games)

| fair bucket | mult: fair -> hit | power: fair -> hit |
|---|---|---|
| 0.0-0.1 | 0.069 -> 0.032 | 0.065 -> 0.047 |
| 0.1-0.2 | 0.155 -> 0.110 | 0.152 -> 0.141 |
| 0.3-0.4 | 0.358 -> 0.320 | 0.356 -> 0.328 |
| 0.6-0.7 | 0.642 -> 0.682 | 0.643 -> 0.672 |
| 0.8-0.9 | 0.845 -> 0.891 | 0.849 -> 0.851 |
| Brier | 0.22431 | **0.22391** |

Multiplicative over-rates underdogs and under-rates favourites (the favourite-longshot bias); power removes most of it.

### 2b. The Suggested pregame bets against the close (635 bets with a closing fair)

| close fair | expected hits | EV@close |
|---|---|---|
| multiplicative | 246.6 | +1.86% [+1.21, +2.59] |
| power | 240.2 | **-3.63%** |
| actual | **223** | realized ROI -10.3% |

Plus-money 599 of 635: mult +1.89% / power -3.98% / realized -9.0%. By book (mult close): BetMGM +4.95, BetRivers +3.80,
FanDuel +3.26, ProphetX +1.61, Bovada -5.29. By books at the close: 1 book -2.51, 7+ books +4.15 (mult).

### 2c. Selection rules on the weekend population, outcome = EV at the POWER close

| rule (game lines) | n | plus-money | EV@close (pow) | ROI |
|---|---|---|---|---|
| board EV >= 2 (today) | 168 | 98% | -0.90 [-2.08, +0.29] | +4.8 |
| power EV at sighting >= 2 | 79 | 66% | +0.79 [-1.55, +2.57] | +1.0 |
| power EV, own book excluded, >= 2 | 162 | 60% | -0.30 [-1.28, +0.56] | +3.4 |

| rule (props) | n | EV@close (pow) | ROI |
|---|---|---|---|
| board EV >= 2 (today) | 36 | **-4.35 [-6.46, -1.48]** | -34.5 |
| power EV at sighting >= 0 | 59 | +0.27 [-1.17, +1.77] | +6.0 |

A power-devig fair removes the underdog skew and moves selection from clearly negative to about zero. It does not by
itself create an edge.

### 2d. Live vs pregame (Suggested, 09-30..10-12, realized)

| phase | sportsbook | exchange | all |
|---|---|---|---|
| live | +2.4% (1,029) | +6.2% (228) | **+3.1% [-5.6, +11.8]**; props +7.3% [-3.2, +17.6] |
| pregame | **-18.6% [-34.7, -3.8]** (406) | -3.9% (367) | **-11.6% [-20.6, -1.0]** |

### 2e. Pre-registered hypotheses

- **H1 prop unders > overs: NOT SUPPORTED.** Same-book CLV over +0.31 vs under +0.26 pooled; unders ahead only in the
  EV 2-5.3 band (+3.30 vs +2.14, overlapping CIs).
- **H2 sharp anchor > consensus: NOT SUPPORTED, AND BARELY TESTABLE** (EV >= 2 same-book CLV: sharp_anchor +1.05 vs
  consensus +1.39). Pinnacle-power EV >= 1 at sighting: +1.76 [-0.65, +4.10] at the power close, n = 18 / 13 games --
  too few to read. (A first-pass grep claimed Pinnacle was absent from the quote logs; it was wrong and is corrected here.)
- **H3 edge concentrates in thin markets: MIXED.** Same-book CLV is similar for main / alt / segment game lines
  (+0.91 / +1.00 / +1.00). Props carry more same-book CLV but NEGATIVE EV at the close (§2c): their prices move, but not
  enough to overcome the hold.
- **H4 earlier sightings carry more value: WEAK SUPPORT** for game lines (+0.68 inside 1 h -> +1.06 at 3 d+); props peak
  6-24 h out (+3.01).
- **H5 model agreement adds value: NOT SUPPORTED on game lines** (power-EV >= 0: agree +0.39 vs against +0.60 at the
  close). Props agree +1.67 vs against -1.53 (n = 24/25): a lead, nothing more.

## 3. The model-vs-market ledger (internal audit track; sources: `/api/model-scorecard` 28d 09-15..10-12, `findings_2026-10-02_*_lines_props_backtest.md`, `measured_market_skill.py`, `findings_2026-10-09_mlb_oos_market_backtest.md`, live-gameline pool)

- **No cell where the model measurably beats the market and holds up.** Scorecard: 73 readable cells, 47 worse / 26 better by point estimate; CI wholly worse in 10, wholly better in 2; no cell has model-side ROI CI above 0, 11 have it wholly below. Game-line cells: 35 of 44 worse.
- The two "beats" (soccer SOT -0.0045 [-0.0072, -0.0016], assists -0.0040) are one-sided overs graded against the `book_margin_model` fair measured 8.5 pp overstated: artifacts, not skill.
- MLB out-of-sample 07-16..09-27: 0 of 18 markets beat the de-vigged book, 15 worse. NFL 2022-25 (1,087 games): ML / spread / total all worse with CIs above 0; NFL props worse by Brier +0.012..+0.053; the model probability adds nothing beyond the line. NCAAF 2025: margin and total MAE worse. Soccer 1X2 +0.029 worse (671 matches). NBA/WNBA props never beat the book. NHL saves worse; skater props never compared to the book.
- **Pattern:** the models are "the market plus noise" -- mostly an over-spread probability (MLB total reliability .0126 vs the book's .0002; model p spread 1.4-3x the book's on props, slope ~0.1 on K and outs). Recalibration can reach parity, not edge.
- Every ranker tested (sc, score_v2, model edge) is null on ROI and CLV (`findings_2026-10-13_score_study_suggested.md`).
- Housekeeping found: the weekly backtests' Layer 2 runs read "zero opportunities" 56 of 56 with JSONDecodeError headlines; the skill registry is stale (still labels several MLB markets "parity" that backtests measured as losses) and has no entry for NBA, WNBA, NHL skater props, NCAAF props or MLB hitter props -- served NHL/NCAAF rows read "never backtested" although backtests exist.

## 4. Props and matchup data (internal audit track)

| sport | how the prop probability is made | matchup inputs CONSUMED | missing / neutral in practice | news -> probability |
|---|---|---|---|---|
| MLB | full pitch sim -> calibrated ladders | platoon both sides, 14-game recency, BvP, arsenal + Statcast quality, park geometry, weather, umpire field, home/road | umpire mult 1.0 in 160/160 sims; park HR override 0/160; temperature 160/554, wind 17/104; NWS weather has no reader; no catcher framing/defense; lineups projected (Rotowire default) [Render-era readings] | posted-lineup / probable-pitcher fingerprint, re-sim debounced to 1/h, ~15 min each: worst case ~75 min |
| NBA/WNBA | possession engine via smart-sim | 21-day per-minute priors, pace/off/def rating, defense-vs-position, OUT exclusion with minutes re-capped + usage renormalised, rest | opponent splits (need player logs: 0 rows); no home-court constant; teammate on/off retired 10-13 (A/B favoured off) | ESPN injuries polled every 30 min -> re-sim; board OUT flag (only these two sports) |
| **NFL/NCAAF** | **NOT the sim**: rolling per-game rate x game-context multiplier (implied total, spread) -> lognormal/Poisson; NCAAF a shrunk season mean | season-to-date rate/sd, prior-season fallback, QB-starts-only for passing | **opponent defense, snap/route/target share, injuries/inactives, weather, home/away, rest: none read** | news never reaches the prop probability; it only forces an odds sweep (2 h baseline; the starting-soon cadence was merged DARK 09-27) |
| NHL | hockeysim box score -> Poisson (saves NB) | line slot/TOI, PP/PK minutes, team xGF/xGA, assist shares, confirmed goalie | injuries fetched, never read; rates frozen at 2025-26 until 11-01; sim PP minutes 6.84 vs 4.66 real | goalie overlay once per generation |
| Soccer | match-sim volumes x player shares x minutes mixture | opponent via team means, per-90 rates, position, set-piece/penalty flags, confirmed XI | no injury/suspension code; no referee/formation; XI only known at the last minute | 8 h sweeps, every tick inside 3 h |

Measured prop skill vs the book: MLB 0 of 18 (K +0.0305, outs +0.0493 Brier worse); NBA pooled +0.0234 [+0.0204, +0.0268]
over 249,884 lines; NFL +0.012..+0.053; soccer shots ROI -22.4% [-40.6, -1.7], last scorer -66.8%. Exonerated (do not
re-run): NFL QB-prop wind / practice status / pbp usage / injury redistribution (no information beyond the line), NBA/WNBA
teammate on/off, WNBA full minutes redistribution, MLB starter-workload features.

Highest-value prop inputs not yet built or tested: NFL/NCAAF snap / route / target share + inactives ~90 min pre-kickoff
and opponent defense-vs-position (the only untested NFL families); NBA/WNBA ROLE MINUTES (minutes bias -3.67, MAE 6.64 vs
5.27 for last-5; actual minutes cut WNBA points bias -1.51 -> -0.27 -- the gap is role, not availability); MLB lineup /
probable-pitcher latency (remove the 1 h debounce) and reliability calibration; NHL in-season rates before 11-01, PP-time
bias, a real scratch feed; soccer injury / suspension / expected XI earlier than the last minute.

### 2f. Inside live (Suggested, 09-30..10-12, 1,257 bets)

| cut | n / games | ROI [95%] |
|---|---|---|
| quote seen <= 60 s | 161 / 101 | -7.3 [-23.5, +9.6] |
| 60-180 s | 531 / 178 | **+9.2 [+0.3, +19.7]** |
| 180-300 s | 379 / 134 | +0.4 |
| > 300 s | 186 / 102 | -0.1 |
| NFL live props | 365 / 31 | **+11.3 [+1.0, +21.4]** |
| live totals | 276 / 158 | +9.6 [-3.9, +22.8] |
| live spreads | 270 / 145 | **-12.5 [-25.7, -0.4]** |
| live h2h | 76 / 61 | -12.8 |

No sign the live return comes from stale quotes (the oldest quotes return ~0). The positive cells are leads after
multiple comparisons, not findings; live spreads lose.

## 5. Odds coverage, cadence and execution (internal audit track; fleet read 2026-10-13 17:40-17:56Z, 4,828 shortlist rows, all pregame)

| sport / family | rows quoted by 1-2 books | sharp / exchange presence |
|---|---|---|
| MLB game | 28% | Pinnacle 38%, ProphetX 37%, Novig 12%, Kalshi 35% |
| NCAAF game | 30% | Pinnacle 56%, ProphetX 89%, Novig 61%, BetOnline 66%, LowVig 63% |
| NFL game / NHL game | 19% / 4% | 11 US books, no Pinnacle, no exchanges |
| Soccer game | 54% | 13 books incl. Kalshi, no Pinnacle |
| NBA game | 98% | alt lines DraftKings-only |
| NHL prop | 83% | DraftKings, FanDuel, Pinnacle (82% of rows) |
| NFL prop / NCAAF prop | 60% / 99% | BetOnline, FanDuel; no Pinnacle |
| MLB prop | 67% | Kalshi 43%, Polymarket 41% |
| Soccer prop | 100% | 95% single book (FanDuel) |

- **Why the sharp/exchange coverage is lopsided:** `SYNDICATE_LIVE_ODDS_GAME_LINE_REGIONS=eu,us_ex` is read only by the
  MLB and NCAAF game-line fetchers; every other game-line and prop fetch is `regions=us`. Not captured anywhere: Circa,
  BookMaker (not in the vendor feed), every DFS pick'em site.
- **Fair method in use:** consensus 74%, `book_margin_model` 22% (soccer + NFL props), `sharp_anchor` 3.5% (Pinnacle,
  MLB/NCAAF game lines). Pinnacle sits on ~1,000 NHL prop rows but anchors none: the 5% hold gate (tuned on 2-3% game
  lines) refuses its 6-8% prop holds.
- **Cadence:** pregame sweeps 25-60 min by sport; live tick configured 60 s, observed ~153 s between launches. Median
  quote seen-age on served rows: NFL/NCAAF 70-83 s, soccer 130-156 s, NHL props ~18 min, MLB ~20 min.
- **Credits:** 1.82M of the 5M cap used by 10-13; burn 143-168K/day projects to 4.3-4.7M by 10-31 (0.3-0.7M headroom).
  Soccer uses 33% of credits for props that are 95% single-book and returned -38.5%.
- **Execution:** paper only (`EXECUTION_MODE=paper`, `LIVE_ARMED=0`); last live orders 09-27. 81% of served best prices
  are US sportsbooks with no adapter; of 98 rows at EV 2-5.27%, 70% are exchange rows.
- **"Lost the books" is partly stale:** the capture collapse was fixed 08-06; what persists is prop breadth (regions=us,
  a 3-book NHL filter, a vendor limit on soccer).

## 6. External practice: how profitable bettors and products find edge (research track; sources tagged S strong / M moderate / W weak)

- **Public information is close to fully priced.** NBA openers are wrong when a player is absent but the close corrects
  them (Dare, Dennis & Paul 2015, S); simple published edges decay (NFL high-total unders 59.7% 2001-09, gone 2010-18, S).
  Our nulls on season metrics / xG / EPA / GSAx are the expected result, not a bug.
- **Durable edge comes from four places:** PRICE (shopping against a fair line built per market), TIME (news, openers),
  COVERAGE (long-tail props, alt ladders, pick'em sites, exchanges, niche sports), DISTRIBUTION modelling (medians,
  ladders, correlation) -- not better point estimates of public information.
- **Multiplicative ("proportional") devig over-states longshots; Shin / power devig beat it** (Data Golf; Strumbelj, S) --
  the same bias measured in §2a-2b.
- **Sharp references:** sides/totals -- Pinnacle, Circa, BookMaker, Betcris. Props -- no agreed sharp book; FanDuel and
  Caesars are called the most efficient US prop books; DraftKings / Caesars / MGM share an origination source (do not
  count them as independent); Pinnacle props are outsourced (Swish) and capped ~$250 pre-gameday (M).
- **Evidence the market-based approach works:** Kaunitz et al. (soccer outliers vs consensus) profitable in backtest,
  paper and 5 months of real money until restricted (S); Data Golf, ~106k golf matchups: 1.8-3.8% ROI at Pinnacle's close,
  but realized ROI at OPENERS landed only about halfway between blind and expected (M).
- **Prop practice:** lines sit at the MEDIAN of right-skewed stats (mean projections over-bet overs); model + market
  beats model alone (Data Golf's best weight ~45-55% model, profit concentrated in thin 3-balls); NBA: minutes first,
  then injury-driven usage redistribution (M).
- **Matchup tables are mostly priced and noisy:** raw DvP tracks pace more than defense; platoon splits need ~1,000-2,200
  PA to be half-reliable; no evidence umpire effects are mispriced; WEATHER has the best academic support (NFL totals
  under-priced heat / wind / rain 1984-2004, S).
- **Market structure:** pick'em per-leg break-evens 54.9-57.7%, DraftKings Pick6 lines do not move after posting (M);
  same-game parlays carry ~18.5% margin (avoid); Kalshi (300k+ contracts): sub-10-cent contracts lose >60%, >50-cent
  earn a small positive return, average pre-fee about -20% (S).
- **KPI:** beating the de-vigged CLOSE is the accepted skill signal; ~65 bets by price movement vs thousands by outcome
  (Buchdahl, M); prop closes are thin, so CLV must be against a sharp de-vigged close, never the same book (M).
- **Limits cap edge:** UK 2024, 4.31% of active accounts restricted, 46.8% of restricted customers in profit vs 25.4% of
  all (S). A product must report bettable size, not just EV.
- **What the winning products deliver:** a per-market sharp-weighted fair line (Unabated), breadth (OddsJam / Betstamp,
  90-200+ books), auto-synced CLV tracking (Pikkit), transparent realized-vs-expected (Data Golf). Hit-rate / L10 trend
  tools, raw DvP tables, umpire and "Wrigley wind" systems are folklore (W).

## 7. The plan -- ranked by expected value and evidence

**Thesis.** The sims and the advanced data are not where the money is: measured against the market they are "the market
plus noise", and the outside evidence says public information is priced. The raw material that IS valuable, and that we
already own, is (a) a per-book price-CHANGE log for 7 sports, (b) live game state, and (c) the sims as distribution
engines. Today they are pointed at the wrong target: the board finds underdogs that a biased devig flatters. Re-point it
at three things: a calibrated fair price, speed, and coverage.

### Phase 0 -- measure truthfully (days; prerequisite for everything)
1. **Fair price v2.** Replace the median-of-multiplicative devig with power (or Shin) devig, de-duplicate books that share
   a feed (DraftKings / Caesars / MGM), and fit per-sport x market book weights on out-of-sample closing log-loss from the
   quote logs. Evidence: §2a (power better calibrated), §2b (multiplicative turns -4% bets into "+2%").
2. **EV at the close as THE KPI.** A daily reading per sport x market x book x phase: EV against the calibrated closing
   fair, beside realized ROI and n / games. Same-book CLV is retired as a headline (it carries the book's vig).
3. **Fix the measurement plumbing:** weekly Layer 2 backtests read "zero opportunities" 56/56; the skill registry is stale
   and missing NBA / WNBA / NHL skater / NCAAF / MLB hitter props.

### Phase 1 -- market edge done right (1-3 weeks)
4. **Coverage where it is cheap:** wire `eu,us_ex` (Pinnacle, Novig, ProphetX) into NFL, NHL, NBA and soccer game lines
   (~+30K credits/month per region); a prop-specific Pinnacle hold gate (908 NHL prop pairs refused today); a one-event
   probe of Pinnacle NFL/MLB props; fund it by cutting soccer props (33% of credits, 95% single-book, -38.5% ROI).
5. **Slow-book detector.** From the change log, measure per book how long it lags a move at the sharp/exchange reference;
   rank stale-line alerts by that lag. This is the Kaunitz / Data Golf edge, built on data we already have.
6. **Suggested v2** = EV >= threshold against fair price v2, with per-cell EV shrink fitted on realized results, a
   bettable-size field, and live / exchange rows first (the only cells with positive returns: live +3.1%, live props
   +7.3%, exchange-priced live +6.2%).

### Phase 2 -- the prop / matchup product, done the way the winners do it (3-6 weeks)
7. **News-to-reprice engine.** Timestamped injury / lineup / goalie / inactive / XI feeds -> minutes, usage and role
   models -> reprice every affected prop within minutes -> alert the books that have not moved. Today: MLB lineups wait
   up to ~75 min (1 h debounce), NFL news never reaches the prop probability, NHL and soccer have no injury feed.
8. **Distribution-first props** (medians and full ladders, not means), blended with the market-implied mean at a fitted
   weight. Rebuild NFL / NCAAF props, which are not sim-based and read no opponent defense, snap / route / target share,
   injuries or weather. Priority inputs: NFL snap / route / target share + inactives ~90 min pre-kickoff; NBA / WNBA role
   minutes (minutes bias -3.67); NHL in-season rates and scratches; soccer expected XI and injuries.
9. **Matchup features earn their place by incremental EV at the close**, pre-registered per sport x stat: pace-adjusted
   DvP, regressed platoon splits, weather first (best prior), umpire last.

### Phase 3 -- live (ongoing; the strongest lead)
10. Live latency (observed ~153 s between launches vs 60 s configured), live prop re-pricing from game state, interval
    actuals (shipped today), and a live KPI (realized vs predicted, and next-quote movement) since live has no close.

### Product layer
11. **Matchup research cards** -- the Twitter-style evidence (usage trend, DvP, pace, weather, lineup/role) on each
    suggested prop -- as PRESENTATION, labelled with whether that input moved the price. Research sells; it must never be
    mistaken for edge.
12. **Public, timestamped CLV / realized-vs-expected ledger** (the Data Golf / Pikkit credibility standard), limit-aware
    fractional Kelly with correlation caps, and a prediction-market module that buys favourites and avoids sub-10-cent
    contracts, net of fees.

### What is missing and needs to be injected

| input | today | why it matters |
|---|---|---|
| Sharp / exchange books beyond MLB + NCAAF game lines | `regions=us` elsewhere | fair price and slow-book detection need a reference |
| Prop sharp reference (FanDuel / Caesars weighting, Pinnacle props) | none; Pinnacle on NHL props refused by the hold gate | prop EV is -1.6..-4.4% at the close today |
| DFS pick'em lines (PrizePicks / Underdog / Pick6) | not captured | stale-by-design lines; a known soft venue |
| True openers (first posted) | first sighting only | openers are where prices are most wrong |
| Timestamped news: NFL inactives, MLB lineups / probables, NHL goalies / scratches, soccer XI / injuries, NBA injury report | partial, slow, or absent | the speed edge |
| NFL snap / route / target share (nflverse) | not cached | the only untested NFL prop family |
| NBA / WNBA player game logs for role minutes | 0 rows | minutes is the base layer of every basketball prop |
| Weather join (NWS) / umpire producer | no reader / neutral | weather has the best academic prior |
| Execution: sportsbook adapters, limits | paper only, US books manual | edge is capped by limits; size must be shown |
