# PRE-REGISTRATION -- E3: are Kalshi / Polymarket DERIVED contracts mispriced against a surface built on the sharp main line? (lane `e3-derived-surface`, 2026-10-26)

Decision Engine plan (`docs/ai_context/plan_syndicate_decision_engine.md`) §3 L1 (price surface), §4 **E3**, §2 P7
("sims do shape and correlation, not the mean"). OFFLINE and read-only on production (fleet `~/syndicate-prod/data`,
nice 19 / ionice idle; Kalshi PUBLIC unauthenticated GETs only). No deploy, restart or env edit. Code:
`scripts/e3_derived_surface.py`, tests `tests/test_e3_derived_surface.py`.

**Committed before any surface x venue x outcome join.** What was looked at before this commit, and only this:

- `venue_odds` file census: market counts per venue x sport x family x date and the 48-point cap counts. While reading
  record SHAPES, the first retained point of ~20 Kalshi markets and the first/last point of ~18 Polymarket markets
  were printed. No venue price was compared with any surface, anchor or outcome.
- `book_quotes` census (rows / events / dates per tier x market x segment) and the anchor extraction itself: every
  book's latest MAIN-market quote at T-60 / T-15 per game (book prices are this test's INPUT, not its outcome), and
  the per-tier anchor coverage counts in §2.
- Kalshi public API SHAPE on one event (`KXNBASPREAD-26OCT22DENOKC`): the market listing's field names and the set
  of `result` values ({yes, no}), and the event-candlestick endpoint's keys and candle counts. Rules text of 7 events
  (OT treatment, below). No per-market result was read or joined.
- Two read-only surveys (sub-agents) of the sim artifacts and of historical score / line files: paths, coverage,
  field names, a few example records (prior-season games, and sim records). No surface was computed on any game.

## 0. The question and the two arms

A **derived contract** is a binary "X > L" on a quantity X that the sharp book does not price at L: an alternate
rung of the full-game margin or total ladder, a quarter / half / period / first-5 segment margin or total, or a team
total. Each arm prices it from the **sharp main line** plus a **shape**. The arms differ ONLY in shape:

- **(a) PARAMETRIC.** Basketball and football: margin ~ Normal, total ~ Normal, per quantity, sigma from history.
  NHL and soccer: independent Poisson team goals. MLB: independent negative-binomial team runs, size from history.
- **(b) SIM-SHAPED.** The sport's own stored sim distribution of X, moved on its integer lattice until it prices the
  sharp main line exactly. The sim supplies SHAPE only; its mean is discarded (measured useless on main lines).

**Location (both arms, same rule):** where the tier's anchor (§2) quotes a main line for the SAME quantity (e.g. the
1H spread), the arm's location is solved so that the arm prices that line at the anchor's de-vigged probability.
Otherwise the quantity's mean is `share_q x mu_full`, with `mu_full` the arm's own full-game location (solved from the
full-game anchor) and `share_q` the parametric arm's history-fitted share (§3).

## 1. Decision time, contracts, identity

- **Window:** games with commence in [2026-09-30T00:00Z, 2026-10-26T08:00Z). Sports: ncaaf, nfl, nba, wnba, nhl,
  mlb, soccer. Season phase from `season_phase.season_phase(sport, ET date)`; every result is split by phase and no
  fit pools phases (NBA preseason 10-02..10-19 is its own cell; MLB and WNBA are postseason).
- **Decision time:** `t_d = commence - 60 min` (**PRIMARY**). `commence - 15 min` is a reported secondary.
- **Kalshi contracts:** every market of every Kalshi DERIVED event (series matching
  `KX<league>[1-4Q|1-2H|1-3P|F5](SPREAD|TOTAL|TEAMTOTAL)`) that appears in our `venue_odds/kalshi__*` logs, listed
  from the public API (`/markets?event_ticker=`). The listing is a superset of the tickers we captured; the captured
  subset is reported beside every number.
  - "X wins [segment] by over L": yes iff X's margin in that segment > L. "Over L": yes iff the segment total > L.
    "Will X score over L": yes iff X's runs > L. OT, from the rules text: full game and 2nd half INCLUDE overtime;
    quarters and NHL periods exclude it; MLB full game includes extra innings, F5 is innings 1-5.
  - **Outcome = the market's own `result`** (yes / no); any other value is excluded and counted.
- **Venue price at t_d:** the last 1-minute event candle at or before t_d (`/series/{s}/events/{e}/candlesticks`,
  fetched over [commence - 7 d, commence]); bid = yes_bid close, ask = yes_ask close; valid only if
  0 < bid <= ask < 1. Mid = (bid + ask) / 2. Executable: YES at ask, NO at 1 - bid. No candle at or before t_d ->
  `no_quote` (counted).
- **Identity:** a Kalshi event joins a book game only through production's `kalshi_catalogue.match_event_blob`
  (sport-scoped, with `code_names` from that game's `KX<league>GAME` markets where listed, and the ticker's start as
  `commence_hint`); anything but `ok` is excluded and counted. **Validation:** where window scores exist (§3),
  the share of Kalshi results that agree with the joined game's score is reported; a game whose results disagree is
  excluded from every measure and counted.
- **Main-line rungs are EXCLUDED:** a rung equal to the tier anchor's own main line for that quantity (either side)
  is E1's contract, not E3's. Reported separately as a diagnostic only.

## 2. Anchors and tiers

From `book_quotes` (append-on-change, so a quote's latest record at or before t_d is its state at t_d). Venue and
exchange bookmakers (E5's set) are never anchors. The sport's capture must be alive: some game-market snapshot of the
sport within the 90 min before t_d.

- A book's **main pair** for (market, segment): both sides at the book's most recently written line, de-vigged
  two-way with Shin (`opportunity_signals.devig`). Spreads are expressed on the home-margin axis (L0 = -home line,
  p0 = P(home margin > L0)); totals as (L0 = line, p0 = P(over)). Whole lines are kept with p0 conditional on no
  push; quarter lines (x.25 / x.75) are skipped. Soccer's margin constraint is the 1X2 (home, draw, away), Shin.
- **Tier S (SHARP, PRIMARY):** Pinnacle's main full-game spread AND total pair at t_d (soccer: Pinnacle 1X2 + total).
  The anchor book set is {Pinnacle} for every quantity: a segment has a same-quantity anchor only where Pinnacle
  quotes that segment (MLB F5 / F1, NBA H1 / Q1 / Q2 from 10-25).
- **Tier C (CONSENSUS, SECONDARY verdict):** games without Tier S, where >= 2 books quote the full-game spread and
  total. Per (market, segment): the modal main line across books (ties: nearest the median line, then lower) and the
  median de-vigged p0 among books at it, >= 2 books.
- Coverage at t60 measured before this commit (book data only): Tier S full-game anchors on ncaaf 235 games,
  mlb 32 (and F5 28), nba 7, nfl 4, soccer 6-7; Tier C on nba 109, nhl 177, soccer ~360, nfl 58, wnba 14, plus the
  Tier S sports' remaining games. So **Tier S rests on NCAAF and MLB**, and NHL / WNBA can only be read in Tier C.

## 3. Surface parameters ("variance from history") and the sim arm

**Parametric parameters**, fitted ONCE before scoring, from PRIOR-SEASON games with closing lines where they exist;
otherwise cross-fitted leave-one-date-out (LODO) inside the window (the parameters for a game's date never see that
date's games). Location of a history game: mu_M = -(closing home spread), mu_T = closing total.

| sport | source | fitted |
|---|---|---|
| nfl | nflverse `schedules_games.csv` 2022-2025 (closing `spread_line`, `total_line`) + quarter scores from `pbp_{2022..2025}.csv` | sigma_M, sigma_T per quantity; segment shares |
| nba | 2025-26 regular season: ESPN scoreboards `backfill/nba_props_2025_26/cache/espn` + `asof/game_odds` consensus spread / total (near-close) | same |
| ncaaf | 2025 FBS: CFBD `historical_truth/games_2025.json.gz` line scores + CFBD 2025 lines (`spread`, `overUnder`, primary tree `data/ncaaf_source/data/cfbd_lines_wk*.json`) | same |
| wnba | window LODO (`interval_history/wnba`) -- no prior lines exist | same |
| nhl | `backfill/nhl_lines_2025_26/actuals.json` regular season | period goal shares (Poisson has no free variance) |
| mlb | window LODO (`interval_history/mlb`) -- no prior inning scores on the fleet | NB size r (full) and r5 (F5) on a grid {2,3,4,6,8,12,20,Poisson} by likelihood of team runs at the located means; F5 run share |
| soccer | `soccer_source/<league>/history/matches_{2023,2024,2025}.csv` | first-half goal share |

- Normal family: sigma_q = RMS(X_q - mu_q) about the location (bias counted as variance). Segment shares through the
  origin: f_q = sum(M_q mu_M) / sum(mu_M^2), g_q = sum(T_q mu_T) / sum(mu_T^2); sigma_q = RMS(X_q - share x mu).
  h1 = q1 + q2; h2 = q3 + q4 + OT; full includes OT.
- Count family: NHL regulation goals Poisson, a tied regulation becomes a one-goal win (home with probability
  E[H] / (E[H] + E[A])) and adds one goal to the total; periods ~ Poisson(share_p x regulation mean). MLB the same
  with NB runs and extra innings. Soccer 90 minutes, no tie rule; 1H ~ Poisson(share x mean). (lambda_H, lambda_A)
  are solved jointly from the margin constraint and the total (`solve_count_means`).
- **Sim arm sources** (pregame copies only; the artifact must be written before commence, and its time relative to
  t_d is reported as a split):

| sport | artifact | shape used |
|---|---|---|
| nba, wnba | `smart_sim_<D>_<H>_<A>.json` `score.dist` (100-500 draws) | margin / total per full, h1, h2, q1-q4 |
| nfl, ncaaf | `smartsim2_segment_distributions_<season>_wk*.json` (300 seeds) | same. Written after kickoff for most games; inputs are leak-free by construction (prior-week ratings, no market anchor, fixed seeds). Reported split by write time. |
| mlb | `sims_pregame/<D>/sim_pk*.json` (1,000 sims) | full and first5 margin / total pmfs as stored (full margin is the production ×1.048-widened pmf). Team totals: 50 samples only -> **not available** |
| soccer | `recommendations_prekickoff_<D>.*.json` joint scoreline pmf | full-game margin / total. 1H: means only -> **not available** |
| nhl | -- | **not available**: only per-period means and one probability are stored |

  - Basketball / football histograms become a pmf by a **variance-preserving discrete Gaussian kernel**: draws are
    shrunk toward their mean by sqrt(1 - h^2 / s^2), smoothed with bandwidth h = 0.9 x min(s, IQR / 1.34) x n^(-1/5)
    (s, IQR, n of the draws), and evaluated on the integers. MLB and soccer pmfs are used as stored.
  - **Lattice shift:** a real shift u = k + w is the mixture (1 - w)(X + k) + w(X + k + 1), so the pmf's integer
    structure moves intact and the anchor price is a continuous non-decreasing function of u.
  - **Diagnostic only (not gated):** (b0) the unsmoothed sim pmf, and (b2) a Normal with the sim's per-game sd.

## 4. Measures

Per contract with a valid quote, an outcome and an arm price p:

1. **Log loss vs the venue mid** (probabilities clipped to [0.001, 0.999]): Delta_LL = LL(p) - LL(mid). The log-loss
   population additionally requires ask - bid <= 0.10 (a wide book's mid is not a forecast; this is conservative
   toward the surface). Brier reported beside.
2. **Fee-net EV at the venue's executable price.** Side = the one with the larger predicted EV
   `p_side / (ask_side + fee(ask_side)) - 1`, fee = `venue_fees.taker_fee_per_contract(venue, ask, venue_ref=ticker)`;
   a contract enters the EV test only if that predicted EV >= 0. **Bands by predicted EV:** [0, 2%), [2, 5%),
   [5, 10%), >= 10%. Realised fee-net return per contract `(win - ask - fee) / (ask + fee)`; mean per band.
   Also reported: bands by |p - mid| in pp ([0,2), [2,4), [4,7), >= 7), and a one-bet-per-axis variant (the
   max-predicted-EV contract per game x quantity; "ladders count once", `#711` R1).
3. **Splits** (reported, never a verdict): sport x phase x market type {full spread rung, full total rung, segment
   spread, segment total, team total}; rung distance from the anchor in sigma units (< 0.5, 0.5-1.5, > 1.5); tier;
   decision time t15; sim write time.
4. **Engine read:** arm (b) vs arm (a) paired Delta_LL on the SAME contracts (game-clustered), by sport x quantity and
   rung distance (body vs tails); the sim's per-game sd / the historical sigma; each arm's reliability by decile.
   Where Pinnacle quotes the same alt rung (NBA from 10-25, MLB F5), arm vs Pinnacle's own de-vigged alt price.

**CIs:** game-clustered bootstrap, 2,000 draws, seed 20261026, 95% percentile. n contracts / n games / n dates on
every line.

## 5. Kill rule and verdict (plan §4, made operational)

Per (venue, tier, arm), pooled over sports and market types at t60:

- **Clause LL:** Delta_LL's 95% CI upper bound < 0 (the surface beats the venue mid on held-out outcomes).
- **Clause EV:** at least one predicted-EV band with >= 30 contracts over >= 15 games whose realised fee-net return
  has a **Bonferroni (4 bands, 98.75%)** game-clustered CI lower bound > 0.
- **KILL** if either clause fails. **SURVIVES** only if both pass. **UNDERPOWERED** below 300 log-loss contracts
  over 30 games (no verdict).
- Tier S is the PRIMARY verdict (the hypothesis is "priced off the SHARP main line"); Tier C is a separate,
  secondary verdict labelled consensus-anchored.
- **Cells** (sport x phase x market type) get the same two clauses as a READ, with >= 100 contracts / 15 games, and
  a Bonferroni CI across the cells of that (venue, tier, arm) reported beside. A cell that passes is a **lead for a
  forward pre-registered test**, never a promotion. Every line stays its own decision: no market, family or sport
  is switched on or off by this test.

## 6. Polymarket (INDICATIVE, reported apart)

Polymarket US publishes no price history, so its clock is our own `venue_odds/polymarket__*` points (48-point cap,
board-loop cadence, no depth). A contract is priced at t_d only if a retained point at or before t_d exists (with
oldest-out retention, that point is then the state at t_d) and `last_seen >= t_d`. Mid = (yes + 1 - no) / 2 when
both are present; executable YES at `yes`, NO at `no`; fee `polymarket` filed quadratic. Orientation from the slug
(`polymarket_board_join`): spreads put YES on the slug's FIRST club at the signed line (non-soccer slugs are
away-home), totals YES = over; segment from the slug modifier (1h, q1-q4, p1-p3). Identity only through a Kalshi
event that passed §1 (E5 amendment A1.3). Outcomes from window scores (`interval_history/<sport>` for nba, wnba,
nhl, mlb; CFBD `games_2026` for ncaaf; nflverse schedules + `pbp_2026` for nfl). Soccer Polymarket is not covered
(no reliable window scores). Same measures; its verdict is labelled INDICATIVE and never overrides Kalshi's.

## 7. Coverage rule (CLAUDE.md)

Before any result the run prints per-source date coverage (anchors per tier, Kalshi events / markets / quotes,
sim artifacts, history games, window scores, Polymarket points) and the intersection, and the findings state the
contracts / games / dates every number rests on.

## 8. Deviations

Any change after this commit is a dated AMENDMENT below, with its reason, written before the result it affects is
read. Script bugs that change no definition above are listed in the findings.

### AMENDMENT A1 (2026-10-26 ~23:05Z, before any surface x venue x outcome join; no result read)

Interpretations forced by the data while building the pipeline. None changes an arm, a measure, a threshold or the
verdict rule.

1. **More derived series than the board captures.** Kalshi's listing of the captured events includes team totals
   (NBA, WNBA, NFL 1H, NHL, MLB), NBA / NFL / NCAAF 1H-2H spreads and NHL period spreads. They are in the registered
   population (the §1 series pattern already admits them). Basketball / football team totals: home points =
   (total + margin) / 2, located at (mu_T + mu_M) / 2 of the same segment, sigma_team = RMS of team points about that
   location in the same history (`fit_normal_params`). Sim arm: no team-total histogram is stored -> **not
   available**. Count sports: team totals and period margins come from the solved team pair (§3).
2. **Overtime follows each SERIES' own rules text.** WNBA's 2nd half EXCLUDES overtime while NBA's includes it.
   A 2nd-half series whose rules say "not including / excluding overtime" is priced on q3 + q4 (`h2reg`); the sim
   stores h2 with OT, so the sim arm is not available for those series. Any other contract whose rules exclude
   overtime from a quantity the model counts with it is excluded and counted (`ot_definition_mismatch`). Every
   series' rules text is stored in the fetch output and quoted in the findings.
3. **Candle resolution.** Kalshi pages event candlesticks by market x period, so "1-minute candles over
   [commence - 7 d, commence]" cost ~60 pages per event. Replaced by HOURLY candles over [commence - 4 d, commence]
   plus 1-minute candles over [commence - 180 min, commence - 10 min]. The book at t_d is the last 1-minute candle at
   or before t_d, else the last hourly candle ending at or before t_d; any change after that hour and before t_d
   would have produced a later candle, so the state at t_d is the same. A market unchanged for > 4 days before t_d
   becomes `no_quote`.
4. **Identity candidates** are the book games on the ticker's own ET date (a +/-1 day window made postseason repeat
   match-ups ambiguous: MLB 16 of 34, WNBA 2 of 15).
5. **History choices made by the loaders** (reported in the findings with n):
   - NCAAF 2025 has no consensus provider in CFBD: DraftKings closing spread / total where quoted, else the median
     of the other providers.
   - NBA 2025-26 lines are `asof/game_odds` `oddsapi_consensus`: the last capture before the slate's first tip.
   - NFL uses all 2022-2025 games, regular season and postseason.
   - Soccer's first-half share pools 9 leagues, 2023-2025.
   - WNBA and MLB LODO use the tier anchor's t60 full-game lines in place of closing lines.
6. **Result validation** (§1) is run wherever a window score exists. Soccer and 26 NBA preseason games have none:
   their contracts are kept unvalidated, and the findings say so.
7. **Loader code.** The fleet loaders for sims, history and window scores are committed beside the script:
   `scripts/e3_sim_loaders.py`, `scripts/e3_history_loaders.py` and `scripts/e3_window_loaders.py` (NEW).
