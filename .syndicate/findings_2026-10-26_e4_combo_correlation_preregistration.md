# PRE-REGISTRATION -- E4: does the sims' JOINT distribution predict same-game co-occurrence better than independence? (lane `e4-combo-correlation`, 2026-10-26)

Decision Engine plan §4 **E4** and §2 **P7** (the sims supply shape and correlation, never the mean). OFFLINE and
read-only on production: fleet `~/syndicate-prod/data` at nice 19, plus unauthenticated public GETs for outcomes
(and for Stage 2, Kalshi's public API). No deploy, no restart, no env edit, no LLM.

**Written 2026-10-26 ~22:40Z, BEFORE any sim x market x outcome join.** What was read before writing this
(structure and coverage only; no pair was formed or scored):
- file listings and date coverage per source, listed in §2;
- one file of each artifact type, read for its keys only;
- the prior MLB study `.syndicate/findings_2026-09-09_joint_pricer_scored.md`. It used June-July backfilled joints,
  the sim's own marginals and an edge-selected population. Same-player: the joint beat independence by
  -0.042 nats. Cross-player: null. Team dimensions: never scored.

Every constant below is the registered one. A change goes in a dated amendment in this file, committed before
the result it affects is read.

## 1. The question and the arms

**Unit.** A *pair*: two binary legs on priced markets in the SAME game, both graded, never the same
(player, market). Each leg's marginal is anchored to the market (§3). The pair's outcome is the 4-cell cell
(A&B, A&notB, notA&B, notA&notB). That partition does not depend on how the legs are oriented, so over/under
orientation is irrelevant to the score.

**Arms.** All three arms use the SAME marginals `p_A, p_B` and the SAME functional form, a Gaussian copula:
`p11 = Phi2(Phi^-1(p_A), Phi^-1(p_B); rho)`, with each leg written as its over/yes event. The arms differ ONLY in
`rho`. So a log-loss difference between arms is purely a difference in correlation.

| Arm | rho |
|---|---|
| **(a) independence** | 0 |
| **(b) sim** | The sport's persisted sim joint, re-anchored: the sim supplies the dependence and the market supplies the marginals (§4) |
| **(c) SGP measured copula** | `nfl.sgp.rho_for(cells, mkt_a, mkt_b, relation)` on the CURRENT fleet file `<sport>_source/sgp/<sport>_sgp_correlations.json`, market cells; `type` cells are used where the file has them. It exists for player-prop pairs in MLB and NBA only. |

**(c-ledger), descriptive only.** This arm reads the SGP builders' consistency posterior as recorded. On the graded
`cheatsheets/<sport>/sgp_graded.jsonl` tickets, it gives the log loss and Brier of the binary "every leg won"
outcome under three probabilities:
1. the ledger's `p_joint` (the consistency-posterior marginals times the copula);
2. the ledger's `p_independent`;
3. the product of the legs' `p_market`.

The output is per sport, with n, games and a game-clustered SE. It is not a dependence-only comparison, because the
marginals differ between rows 1-2 and row 3. It is reported, not gated.

## 2. Sources and window (coverage is printed first, with the intersection and the n each result rests on)

| Source | Path (fleet data root) | Coverage seen 2026-10-26 |
|---|---|---|
| MLB sim joint, frozen pregame | `mlb_source/source_artifacts/data/daily/sims_pregame/<date>/sim_pk<gamePk>_g<n>.json` -> `sim.joint` (Spearman, 1,000 sims) | 10-03 .. 10-26, 20 dates (postseason) |
| NBA sim | `nba_source/data/processed/smart_sim_<date>_<HOME>_<AWAY>.json` (`prop_ladders`, `<stat>_sd`, `nba_prop_calibration`; `n_sims` 100 on the file read) | 10-03 .. 10-26, 109 files; regular season from 10-20 |
| Soccer sim, frozen pre-kickoff | `soccer_source/<league>/api/recommendations/recommendations_prekickoff_<date>.*.json` -> `matches[*].scoreline_probabilities` | 10 leagues; MLS 09-30.., others 10-09/10 .. |
| Market close | `settlement_inputs/closing_lines_<date>.csv` (per book: `closing_line`, `closing_price`, `selection`) | mlb 09-30..10-24 (20 dates), nba 10-03..10-25 (20), soccer 09-30..10-25 (26) |
| SGP cells (c) | `<sport>_source/sgp/<sport>_sgp_correlations.json` | mlb, nba (and nfl / nhl / wnba, not used: no (b)) |
| SGP ledger (c-ledger) | `cheatsheets/<sport>/sgp_graded.jsonl` | nhl 740, nba 233, nfl 192, wnba 32, mlb 25 rows |
| Outcomes | MLB: StatsAPI `feed_live` on the fleet, else the public `statsapi.mlb.com/api/v1/game/<pk>/boxscore`. NBA: public ESPN summary box. Soccer: the public ESPN scoreboard, full-time (90 min) score. | GET only, cached to `C:\tmp\e4\` |

**Window:** games with a market close dated 2026-09-30 .. 2026-10-25 and a pregame sim of the type above. The
intersection rule is fixed: a pair exists only where sim, market and outcome all exist for the game.

**Pregame-ness (leakage gate):**
- **MLB:** `_freeze` must exist; a game whose freeze record is after first pitch is excluded.
- **NBA:** the file must be written before `commence_time`. Before the 10-21 tip freeze, a file's mtime at or after
  `commence_time` excludes the game.
- **Soccer:** the pre-kickoff record's own `updated_at` / last build must be before kickoff.
- Exclusions are counted and reported.

## 3. Legs and marginals (identical in every arm)

- **Close:** per book, the two-sided pair at the same `closing_line` (both selections). Multiplicative de-vig, then
  the median across books. Soccer 1X2 (`h2h`, 3 outcomes): per-book normalisation of the three, then the median.
- **Main line:** per (game, player, market) or (game, market), keep ONE line: the line with the most books quoting
  both sides; ties go to the line with the median `p` closest to 0.5. A leg needs >= 1 two-sided book.
  Legs with `p` outside (0.02, 0.98) are dropped.
- **Grading:**
  - Pushes and voids are dropped: integer lines that land exactly, a batter with 0 PA, a basketball player with
    0 minutes, a match not completed in 90 min.
  - Soccer totals use only x.5 lines.
- **Markets:**
  - **MLB:** `batter_hits`, `batter_total_bases`, `batter_home_runs`, `batter_rbis`, `batter_strikeouts`, which are
    the joint's `hits / total_bases / home_runs / rbi / strikeouts`. For the secondary composed types: game
    `h2h` and `totals`.
  - **NBA:** `player_points`, `player_rebounds`, `player_assists`, `player_points_rebounds`,
    `player_points_assists`, `player_rebounds_assists`, `player_points_rebounds_assists`.
  - **Soccer:** `h2h` (home / draw / away), `totals` (main x.5 line), `btts`.
- **Identity:**
  - Players match by accent-stripped, suffix-stripped name within the game's two teams. MLB uses the joint's
    `players{pid:{name,team}}`.
  - Games match on (date, home, away) after team normalisation.
  - Unmatched rows are counted, never guessed.

## 4. Arm (b): what each sim supplies, and how it is re-anchored

- **MLB:**
  - `rho_S` comes from `sim.joint.corr_lower`. `undefined` (-32768) pairs are dropped and counted.
  - Converted with the platform's own map, `rho = 2*sin(pi*rho_S/6)` (`mlb/threshold_correlation.py`), into the
    Gaussian copula at the market marginals. That is exactly SEC2 for n = 2.
  - **Secondary, composed types.** These use latent equal-variance composition from the joint's
    `team|full|{home,away}` labels:
    - batter x game total over: `rho = (r_XH + r_XA)/sqrt(2(1 + r_HA))`;
    - batter x own-team moneyline: `rho = (r_X,own - r_X,opp)/sqrt(2(1 - r_HA))`, each `r` converted as above.
- **NBA:**
  - The three within-player covariances are backed out of the ladders built from the same draws:
    `cov(P,R) = (Var_raw(PR) - Var_raw(P) - Var_raw(R))/2`, and likewise for PA and RA.
  - `Var_raw(P) = (pts_sd / sd_scale.pts)^2`. `Var_raw(PR)` is the variance of the `prop_ladders.pr.distribution`
    over `combo_scale(("pts","reb"), orig_sd, k)^2`. That undoes the calibration's widening
    (`nba_prop_calibration.py:425-449`); `k` and `sd_scale` are read from the file's stamps, and an unstamped row
    uses scale 1.
  - Any within-player pair among the seven markets gets `rho = cov(X,Y)/(sd_X sd_Y)` from that 3x3 matrix, and
    `rho` is clipped to [-0.95, 0.95].
  - **Consistency gate:** a player-game is excluded from (b) if the reconstructed `Var(P+R+A)` differs from
    `(pra_sd / sd_scale.pra)^2` by more than 25%, or if any variance is <= 0. Exclusions are counted.
- **Soccer:**
  - From the sim's scoreline table, compute the sim's own 2x2 table for the two events at the market's line.
  - Solve for the tetrachoric `rho`, the Gaussian-copula `rho` that reproduces the sim's `p11` at the SIM's
    marginals, by bisection on [-0.999, 0.999].
  - Apply it at the MARKET marginals.
  - Secondary: the odds-ratio-preserving re-anchor, which rakes the sim's 2x2 to the market marginals.
- **Not testable, stated now:**
  - NHL, NFL, NCAAF: no persisted joint for any marketed pair. NHL saves none; smartsim2 saves only
    `margin_stdev` and `total_stdev`.
  - WNBA: 13 playoff files with different transforms.
  - Side x total in any sport: no persisted (margin, total) joint, and MLB keeps only 50 score samples.
  - NBA cross-player pairs and NBA player x team: none persisted.
  - The engine read names these as gaps for the sim owners. They are not results.

## 5. Pair types (cells)

| Sport | Cell | Pairs |
|---|---|---|
| MLB | **SP-nested** | same batter; one event implies the other at any line: hits x TB, HR x hits, HR x TB, HR x RBI |
| MLB | **SP-other** | same batter, the rest: hits x RBI, TB x RBI, strikeouts x any |
| MLB | **TM** | teammate batters |
| MLB | **OP** | opposing batters |
| NBA (regular season, 10-20 on) | **SP-disjoint** | same player, no shared component: P x R, P x A, R x A, P x RA, R x PA, A x PR |
| NBA (regular season) | **SP-nested** | same player, sharing a component (e.g. P x PR, PR x PRA) |
| Soccer | **GL** | result x total, result x BTTS, BTTS x total (home/draw/away each paired; never result x result) |

These 7 are the **PRIMARY** cells.

**SECONDARY cells (reported, not gated):**
- MLB composed: batter x game total, batter x own-team moneyline.
- NBA preseason, 10-03..10-16, a different population.
- Soccer by kind, and the odds-ratio variant.
- Each sport x stat pair.
- (b-pooled): (b) with `rho` replaced by the cell's leave-one-date-out mean sim `rho`. It separates the sim's
  STRUCTURAL correlation from per-game variation.
- Game-weighted means: per-game mean first, then the mean over games.

## 6. Metric, inference and the gate

- **Score.** Per pair, the 4-cell log loss of the realised cell; cell probabilities are clipped at 1e-6.
  Differences: `D_ba = LL_b - LL_a`, `D_ca = LL_c - LL_a`, `D_bc = LL_b - LL_c`. Negative means the first arm is
  better. 4-cell (multi-class) Brier differences are reported beside them.
- **Common support.** Within a cell, every arm is scored on the SAME pairs. Pairs where (b) is undefined are
  dropped and counted. `D_ca` and `D_bc` are reported on the subset where (c) exists.
- **Inference.** The mean over pairs, with a game-clustered SE: CR1, the SGP studies' `clustered_se` formula. The
  95% CI is mean ± 1.96 SE.
- **Minimum n.** A cell needs >= 20 games and >= 200 pairs for a verdict. Otherwise it reads **INSUFFICIENT**,
  which is never a kill.
- **Stage 2 gate (the brief's rule).** A primary cell PASSES when the upper bound of the 95% CI on `D_ba` is
  below 0, **Holm-adjusted across the 7 primary cells**. A cell that passes only unadjusted is a LEAD, not a pass.
- **Kill rule (plan §4).**
  - Per primary cell: if the CI on `D_ba` does not exclude 0 on the better side (upper bound >= 0), the sim's
    correlation is not shown better than independence in that cell at this n. E4 is KILLED there.
  - **E4 overall** is **KILLED** when no primary cell passes Holm.
- **What a pass does NOT mean, stated now.**
  - In a NESTED cell, beating independence is close to guaranteed, because independence ignores logical
    implication. Books and venues price nested legs from the same identity.
  - So for nested cells, the decision-relevant read is `D_bc` (sim vs the measured copula) and Stage 2's price
    test, not `D_ba`.
  - The recommendation will weigh `D_bc`. Where `D_bc`'s CI is above 0, the measured copula beats the sim, and the
    sim adds nothing a combo price needs.
- **Engine read (reported, not gated).** Per cell and per stat pair:
  - the mean sim `rho`;
  - the realised `rho`, by MLE: the 4-cell likelihood at the market marginals, a single `rho` per cell, with a
    game-cluster bootstrap CI of 500 resamples;
  - the SGP `rho`.

  For NBA, it also gives the spread of per-game sim `rho` against its expected sampling noise at the file's
  `n_sims`.

## 7. Stage 2 (runs ONLY for cells that pass §6 under Holm)

- **Price source.** Kalshi single-game combo (multivariate) markets for the passing sport, found through the
  PUBLIC API: multivariate event collections, then their markets and trade prints.
  - A combo counts only if its legs map onto the passing cell's pair type and its game settled in the window.
  - The executable evidence is the public trade print, at its price and taker side.
  - Polymarket: no combo capture exists, so it reads NOT RUNNABLE.
- **EV.** `EV = p_b / (q + fee(q)) - 1`.
  - `q` is the print price.
  - `fee` is `venue_fees.taker_fee_per_contract`, i.e. Kalshi 0.07·q(1-q) with any series multiplier. The maker
    fee is reported beside it.
  - Bands of `p_b - p_a` (pp): < 1, 1-3, 3-5, >= 5, per sign.
  - Game-clustered CI. Realised return at the print is reported beside it.
- **If no combo prints with leg composition are publicly retrievable for the window, Stage 2 reads NOT RUNNABLE.**
  The recommendation is then a capture, not a strategy.

## 8. What will be reported regardless of outcome

- Per-source coverage, the intersection, and every exclusion count.
- Every primary and secondary cell, with n pairs / n games.
- The engine read.
- The c-ledger table.
- A recommendation.
- Every line remains its own decision. Nothing here proposes switching a market, family or sport on or off. A
  pass means "the sim-shape expert may earn weight on that pair type in the skill registry". A kill means "its
  weight there stays 0".

## Amendment A1 -- 2026-10-26 ~22:45Z, before any join (market source)

**Found while writing the reader, before any pair was formed.** `settlement_inputs/closing_lines_<date>.csv` holds
one row per SELECTION, priced at one book. That book is often a different one for each side: on 10-18 Yandy Diaz's
hits over 0.5 was DraftKings -222 and the under was ESPN Bet +190. So it is a best-price-per-side ledger. §3's
"per-book two-sided pair, de-vig, median" cannot be computed from it.

**Replacement, same estimator:**

- **Source.** `<sport>_source/tracking/book_quotes/<date>.jsonl[.gz]`, the L0 per-book change log. It carries
  `bookmaker`, `market`, `selection`, `line`, `player_name`, `price`, `captured_at` and `commence_time`. Every file
  in the window is read and indexed by `event_id`. A game's quotes can sit in the previous date's file.
- **Close per book.** For each (book, market, player, line, selection), take the LAST record with
  `captured_at < commence_time`. The log has in-play rows: e.g. an MLB record captured 23:15Z for a 21:11Z start.
  Both sides of a pair must come from the same book at the same line.
- **Then as registered:** multiplicative de-vig per book, the median across books, the §3 main-line rule, and
  (0.02, 0.98).
- **Exchanges and venues are excluded from the market marginal:** kalshi, polymarket*, novig*, prophetx*,
  betfair_ex*, matchbook, sporttrade. Stage 2 prices against the venue, so the venue must not set the fair it is
  tested against.
- The median quote age at commence (`commence_time - captured_at`) is reported per sport. No staleness cut is
  applied, because the log records changes and an unchanged quote has no new row.
- **The pregame reference time** for the NBA and soccer leakage gate (§2) is the game's `commence_time` in
  `book_quotes`.

`closing_lines` is not used. Window, cells, arms, metric and gates are unchanged.

## Amendment A2 -- 2026-10-26, before any join (implementation choices the text left open; committed with the code)

1. **(b-pooled) is computed per (cell, stat pair)**, not per whole cell. It is the leave-one-date-out mean sim
   `rho` over the same stat pair in the same cell. A mixed cell such as MLB SP-other holds pairs of opposite sign:
   hits x RBI is positive, strikeouts x hits is negative. Pooling across those would test a meaningless average,
   not the sim's structural correlation.
2. **Holm always runs over all 7 primary cells (m = 7).** A cell that is INSUFFICIENT, or whose mean `D_ba` is
   >= 0, enters with p = 1. The p-value is two-sided normal on `D_ba / SE`. A cell PASSES when its CI upper
   bound is < 0 AND Holm rejects at 0.05. A cell whose CI upper bound is < 0 but which Holm does not reject is a
   LEAD.
3. **Identity rules:**
   - **Players:** an exact normalised name, else a UNIQUE first-initial + last-name match within the game. Two
     candidates means unmatched, never a guess.
   - **MLB games:** full team names, within ±6 h of the StatsAPI `game_date`.
   - **NBA games:** the sim's ESPN `game_id` gives the ESPN teams and start time, then the `book_quotes` event is
     matched on team nicknames within ±6 h.
   - **Soccer:** the sim's ESPN event id gives ESPN's team names. The `book_quotes` event must be within ±3 h of
     kickoff with token Jaccard >= 0.34 on BOTH home and away; the unique best match wins, and a tie is dropped
     as ambiguous.
   - ESPN `AET` / `PEN` / not completed -> void.
4. **NBA by draw count** (`n_sims` 100 vs 500) is reported as a secondary split of the NBA cells.
5. **c-ledger's market product** uses only tickets whose every leg is an `over` with a recorded `p_market`. The
   count is reported.
6. Stat-pair sub-cells are reported when they have >= 30 pairs.
7. **Code:** `scripts/e4_combo_correlation.py`. Tests: `tests/test_e4_combo_correlation.py`, 23 hermetic tests,
   including a reachability test (`off != on`) and recovery of a known NBA covariance through the real calibration
   widening.

## Amendment A3 -- 2026-10-28, before any price x probability x outcome join (Stage 2 implementation; committed with the code)

**Why.** Stage 1 passed 4 cells under Holm, so §7 applies to MLB SP-nested, MLB SP-other, NBA SP-nested and soccer
GL. §7 was written before a price source existed. The source is now the forward capture `#742` (lane
`kalshi-combo-capture`), which backfilled about 30 days of settled combos. This amendment fixes how §7 is computed
from it. Lane `e4-stage2-combo-prices`.

**Read before writing this (structure and coverage only).** No print price was compared with any probability, and
no combo or leg was graded.
- The capture's design and findings (`findings_2026-10-27_kalshi_combo_capture.md`).
- The fleet store's file listing.
- Two coverage probes, from tickers alone (`C:\tmp\e4\s2_coverage.py`, `s2_cells.py`; neither reads
  `last_price`, `result` or any outcome).
  - **Probe 1:** 13,608,138 stored rows, of which 685,789 are traded two-leg one-game combos.
  - **Probe 2, games dated in the Stage 1 window, by ticker shape:**
    - MLB same-batter: SP-nested 374 combos (33 games), SP-other 234 (33).
    - NBA same-player: SP-nested 110 (33), SP-disjoint 2,502 (43).
    - Soccer result/total/BTTS: about 7,600 in Stage 1's leagues, plus UCL, which has no Stage 1 sim.
- 19 leg markets' public metadata, in 3 GETs (title, `floor_strike`, `strike_type`, rules; no leg result was read), to write the leg parser.

**The run waits for a condition.** Stage 2 runs only after the capture's first-full-forward-day reading
(`READING: Kalshi combo capture first full forward day`) is on origin/main. The user approved Stage 2 on that
condition on 2026-10-28 ("Yes, after the reading"), relayed by the decision-engine session. A `--funnel-only` run
before then may count joins, but writes or prints no price, probability, outcome or reading.

1. **Price source** (replaces §7's "found through the public API ... trade prints").
   - **Store:** `<data root>/reports/intelligence/kalshi_combo_capture/combos_<settled UTC date>.jsonl.gz`, first
     row per ticker, settlement dates 09-29..10-28. It holds TRADED combos only: v2 stores no untraded row, and
     Kalshi purges untraded finalized combos within about 3 days.
   - **The price, `q`:** `quote_at_capture.last_price`, the last print's YES price. It equalled the last trade read
     in 3,774 of 3,778 checked (`#742`).
   - **DEVIATION: the print's taker side is NOT captured** (trade reads are off by default). The primary EV is §7's
     own formula for a YES buyer at `q`; the NO buyer at `1 - q` is reported beside it, with the side chosen by the
     sim (R2 below). A combo that printed several times is represented by its last print; 81% printed once (`#742`).
   - **Unit:** one combo (ticker), unweighted. Volume-weighted means are reported beside.
2. **Population, fixed now:**
   - `n_legs == 2`, `traded`, both legs in ONE same-game group, a `last_price` in (0, 1);
   - the game date, from the leg ticker, in Stage 1's window 09-30..10-25;
   - the legs' shape maps onto a passing cell:
     - **MLB:** same batter (same ticker player segment); `KXMLBHIT` / `KXMLBTB` / `KXMLBHR` / `KXMLBRBI` =
       hits / total_bases / home_runs / rbi; nested per `MLB_NESTED`, else other. `KXMLBHRR` and pitcher series are
       no Stage 1 market.
     - **NBA:** same player; `KXNBAPTS` / `REB` / `AST` / `PRA`; the pair shares a component (SP-nested);
       regular season only (Stage 1's game date >= 10-20).
     - **Soccer:** full-match `KX<league>GAME` x `TOTAL`, `GAME` x `BTTS`, or `BTTS` x `TOTAL`, in Stage 1's 10
       leagues; never 1H/2H/team totals, never result x result.
   - Combos in killed or unregistered shapes are counted, not tested.
   - The combo must join a Stage 1 game, with that game's sim, outcome and pregame gates (Stage 1's own loaders and
     cache), so every arm's input comes from the Stage 1 machinery.
   - No window extension: games after 10-25 have no Stage 1 join and are not used.
3. **Game join:** the production matcher `kalshi_catalogue.match_event_blob`.
   - It takes the leg ticker's team blob and a commence hint from the ticker, and matches against Stage 1 games
     within ±1 day.
   - Each game's `book_quotes` home/away names are used; soccer also needs the same league and a per-league code map
     read from the GAME legs' own "<Club> wins" titles.
   - Only `ok` is used; `no_match` and `ambiguous` are counted.
4. **Legs** (public `GET /markets?tickers=` in batches of 100, cached; metadata only):
   - **Props:** subject = the title before `:`; `strike_type` must be `greater`; line = `floor_strike`; the YES
     event is stat > line.
   - **Soccer:**
     - total: over `floor_strike`, x.5 only;
     - BTTS: title "Both Teams To Score";
     - GAME: "<Club> wins" maps to home/away by `club_key`, else by unique token Jaccard >= 0.34; a `TIE` suffix
       with "Tie is the result" means draw.
   - A leg on side `no` takes the complement event. The combo's YES is both legs' chosen events.
   - **Players:** Stage 1's identity rule (exact normalised name, else a unique first initial + last name). MLB
     requires both legs to be the SAME joint pid.
5. **Marginals** (replaces §3's main-line rule for Stage 2 only). The combo fixes each leg's line, so each leg's
   marginal is A1's estimator AT THAT LINE:
   - per sportsbook, the last pregame two-sided quote at exactly that line;
   - multiplicative de-vig (soccer result: the 3-way de-vig);
   - the median across books, with >= 1 two-sided book and p in (0.02, 0.98).
   - A leg with no such quote is unanchored: the combo is dropped and counted (`leg_no_market_at_line`).
6. **The arms**, on the legs' YES-oriented marginals:
   - `p_a`: rho = 0.
   - `p_b`: Stage 1's §4 sim rho for that pair:
     - MLB: `corr_lower` -> 2 sin(pi rs / 6);
     - NBA: the ladder-backed covariance with the PRA identity gate;
     - soccer: the tetrachoric rho from the frozen scoreline table at the combo's total line.
   - `p_c`: the SGP copula (`rho_for`, MLB/NBA only, where a cell exists).
   - The Gaussian copula of §1 picks the cell matching the two sides.
7. **Fee and EV.**
   - Fee per contract: 0.07 x m x q(1-q), not rounded, since order size is not captured.
   - m is `KXMVECROSSCATEGORY`'s own `fee_multiplier` from one public `/series` read at run time. If it cannot be
     read, m = 1.0, stamped as an upper bound.
   - EV: `EV_x = p_x/(q + fee) - 1` for x in {a, b, c}, and `EV_x^NO = (1 - p_x)/((1 - q) + fee) - 1`.
   - Realised YES return: `R = 1{Kalshi result = yes}/(q + fee) - 1`. The NO return is defined likewise.
   - **Kalshi's `result` decides R**, since it is what pays. Our own grading of both legs (Stage 1's outcome sources)
     must agree. A disagreement is counted and that combo leaves R2/R3; it stays in R1.
8. **Bands of p_b - p_a, in pp** (§7, per sign): <= -5, (-5,-3], (-3,-1], (-1,0), [0,1), [1,3), [3,5), >= 5.
   - Per cell and band: n combos and games; mean q, p_a, p_b and p_c; mean EV_b and mean realised return (YES and
     NO), each with a game-clustered (CR1) 95% CI. The game is the Stage 1 game.
9. **Readings, registered now:**
   - **R1, price tracking (per cell, descriptive):** OLS of (q - p_a) on (p_b - p_a), game-clustered SE.
     - A slope CI that excludes 0 means the prints move with the sim's correlation; a slope near 1 means they carry
       it fully.
     - A slope CI that includes 0 means the prints are consistent with pricing the legs as independent.
     - The intercept is the margin. Mean (q - p_a), (q - p_b) and (q - p_c) are reported beside it.
   - **R2, sim edge at the print (the decision read; gated):**
     - Per cell, on the side the sim's correlation favours: YES among combos with p_b - p_a >= 1 pp, and NO among
       combos with p_a - p_b >= 1 pp.
     - The statistic is the mean realised return, with a game-clustered 95% CI and a two-sided normal p.
     - Holm runs across all 8 tests (4 cells x 2 sides). A test enters with p = 1 when it is below minimum n or its
       mean is <= 0.
     - Minimum n: >= 20 games and >= 200 combos, else **INSUFFICIENT**, which is never a kill.
     - **EDGE:** minimum n, CI lower bound > 0, and Holm rejects at 0.05.
     - **LEAD:** CI lower bound > 0 without Holm.
     - **NO EDGE:** otherwise.
     - Overall: EDGE_FOUND if any test is EDGE; INSUFFICIENT if every test is; otherwise NO_EDGE_SHOWN.
   - **R3 (descriptive):** the binary log loss of Kalshi's YES result under p_b vs p_a, game-clustered.
   - No outcome chooses a band, cell, side or threshold. The full §7 band table is reported regardless.
10. **Polymarket:** NOT RUNNABLE (unchanged; no combo capture).
11. **Code:** `scripts/e4_stage2_combo_prices.py`, reusing Stage 1's loaders, gates and scorer helpers from
    `scripts/e4_combo_correlation.py` unchanged. Tests: `tests/test_e4_stage2_combo_prices.py`, 29 hermetic tests,
    including:
    - an `off != on` reachability test (the sim's rho moves the combo probability);
    - side complements summing to 1;
    - the exact-line marginal (a one-sided book is never priced);
    - the blob join;
    - the R2 verdict rules (INSUFFICIENT is never a kill; EDGE needs Holm).

## Amendment A4 -- 2026-10-28, after a `--funnel-only` run and before any statistic (the game join; the fee reading)

**Found by the funnel-only run of `6034d16a`.** That run writes join counts only: no price, probability, outcome or
reading was written or printed.

- **The defect.** A3 §3's +/-1-day window let a postseason series' next game match the same team blob: MLB
  `game_ambiguous` 328 of 608 candidates.
- **The fix.** Keep only Stage 1 games whose commence is within +/-6 h of the ticker's own start time where the ticker
  carries one (MLB, via `event_start_from_ticker`), else whose US/Eastern date equals the ticker's date (NBA, soccer).
  Then `match_event_blob` as A3 §3. The refusal is renamed `no_stage1_game_in_slot`.
- **Joined combos / games, before -> after:**
  - MLB SP-nested 20 / 3 -> 54 / 6;
  - MLB SP-other 17 / 6 -> 83 / 20;
  - NBA SP-nested 12 / 11 -> 12 / 11;
  - soccer GL 2,471 / 201 -> 2,467 / 200;
  - MLB `game_ambiguous` 328 -> 0.
- **What the counts already say, stated before any statistic.** MLB SP-nested, MLB SP-other and NBA SP-nested are
  below A3's minimum n (200 combos / 20 games), so their R2 tests will read INSUFFICIENT. Soccer GL is the only cell
  that can reach an R2 verdict. R1 and R3 are reported for all four. The main losses are:
  - legs with no two-sided sportsbook quote at the combo's line (MLB 265, NBA 1,580, soccer 2,983);
  - combos in games outside Stage 1's joined set.
- **Fee.** `/series/KXMVECROSSCATEGORY` reports `fee_type` `quadratic_with_combo_maker_fees` and `fee_multiplier` 1.
  - `venue_fees.kalshi_fee_params` refuses an unknown fee type on purpose, so A3 §7's fallback applies: m = 1.0,
    stamped as an upper bound. The raw fields go in the report.
  - The bound and the venue's own multiplier agree on the number. Whether the combo TAKER fee is the plain quadratic
    is unverified.
- **Code:** `same_slot` in `scripts/e4_stage2_combo_prices.py`. 30 tests, adding the next-day rematch and the ET-date
  rule.
