# Portfolio monitor findings, 2026-11-27 (lane `portfolio-monitor`)

Public repo: counts and percentages only. No dollars, balances, order ids or row-level live trades.

## The 11-24 close-beat study, run 2026-11-27 -- RULE RESTATED BEFORE COMPUTING (written 12:32 PM CST)

User 11-27 ~12:30 PM CST: "Yes, run it" (answering "Should I run the 11-24 closing-line study now?").

The study is the one pre-registered by the daily learning review in `findings_2026-11-24_portfolio_monitor.md`,
"One optimization lead". Its hypothesis, buckets and decision rule are copied here unchanged, and they are frozen:

- *Hypothesis:* the 7 d close-beat decline (beat-close 61.1% to 53.9%) comes from bets submitted long before
  commence, where our fair is stale against a moving market, not from bets near the start.
- *Data:* 30 d and 7 d graded bets with a priced close in `live_all.json`, split by submit-to-commence hours (< 1,
  1-6, > 6). Fee-net CLV per bucket with event-clustered 95% ranges. A forward copy follows on bets submitted from
  11-25, once the > 6 h bucket reaches 100 games.
- *Decision rule:* GO (name a fair-refresh-before-submit or a submit-closer-to-start challenger for a later window)
  iff ALL three hold: (1) the > 6 h bucket's fee-net CLV has a 95% upper bound < 0 on the 30 d set; (2) the < 1 h
  bucket's range includes or exceeds 0; (3) the forward set keeps the same order. Otherwise KILL.

How it is computed (fixed before the numbers are read):
- Orders come from the newest Portfolio Watch reading's `live_all.json` (20261127T180404Z).
- Each bet and its CLV come from `scripts/live_book_edge_readout.py`'s own `bets_from_orders` and the same-book
  scope, the same code that produces the review's CLV figures. That covers fee-net CLV, the close scope and the
  event-clustered SE (`_clustered_mean`); range = mean +- 1.96 SE.
- Windows are by `selected_date`: 30 d = 10-28..11-26 and 7 d = 11-20..11-26, the review's last complete day.
- Hours = `commence_time` minus `submitted_at`. Read literally, the frozen "< 1" bucket also holds in-play bets
  (hours < 0). The rule uses the literal bucket. A pregame-only 0-1 h row and an in-play row are shown beside it
  as a sensitivity, and they do not change the verdict. Bets with no readable `commence_time` or `submitted_at`
  are counted and left out.
- If (1) or (2) fails on the 30 d set, the verdict is KILL now and no forward copy is owed. If both pass, the
  verdict is "30 d half PASS, forward copy owed", not GO.

### RESULT, 2026-11-27 12:35 PM CST: rule conditions 1-2 PASS on 30 d, but the HYPOTHESIS IS NOT SUPPORTED

Script: `scratchpad/clvlead/lead_buckets.py` (session 69d80317), run at Idle priority. It read 2,713 orders and
2,397 graded bets. Every 30 d and 7 d bet has a readable submit and commence time (the 450 without a
`commence_time` are older).

**Check:** the all-bucket totals equal the review's own figures exactly. 30 d: 622 bets / 422 games, gross +1.11,
beat close 60.6%, net -0.63 (se 0.22). 7 d: 99 / 73, gross -0.41, beat close 43.4%, net -2.17 (se 0.31). So the
split uses the review's own definition.

Same-book fee-net CLV by submit-to-commence hours. Each cell gives priced bets / games, then pp with its 95% range:

| bucket | 30 d (10-28..11-26) | 30 d beat close | 7 d (11-20..11-26) | 7 d beat close |
|---|---|---|---|---|
| < 1 h (literal) | 55 / 46: -0.74 [-1.73, +0.26] | 50.9% | 17 / 16: -2.03 [-2.52, -1.54] | 29.4% |
| 1-6 h | 159 / 127: -0.59 [-1.23, +0.04] | 59.7% | 23 / 19: -1.29 [-2.28, -0.30] | 60.9% |
| > 6 h | 408 / 312: -0.63 [-1.14, -0.11] | 62.3% | 59 / 45: -2.55 [-3.45, -1.65] | 40.7% |
| all | 622 / 422: -0.63 [-1.06, -0.20] | 60.6% | 99 / 73: -2.17 [-2.79, -1.55] | 43.4% |

- **In-play bets have no priced close at all**: 0 of 337 in 30 d and 0 of 29 in 7 d. So the literal "< 1" bucket
  is the same as the pregame 0-1 h row, and the sensitivity changes nothing.
- **Frozen rule, as restated above:**
  - (1) PASS: the > 6 h 30 d upper bound is -0.11 < 0.
  - (2) PASS: the < 1 h 30 d range [-1.73, +0.26] includes 0.
  - (3) the forward copy is owed.
  - By the pre-stated reading, the verdict is "30 d half PASS, forward copy owed", NOT GO.
- **The hypothesis is not supported, and the pass does not come from it:**
  - The 30 d buckets do not differ: net -0.59 to -0.74. The bets nearest the start are the worst by point estimate,
    and they beat the close least often (50.9% against 62.3% for > 6 h). That is the reverse of the hypothesis.
  - (1) passes because the whole book loses to the close after fees (all -0.63 [-1.06, -0.20]), and > 6 h is 312 of
    the 422 priced games. Any bucket that large would clear "upper bound < 0".
  - (2) passes because the < 1 h bucket is small (46 games), so its range is wide.
  - The rule tests each bucket against 0, never the buckets against each other. That is a design gap in the 11-24
    rule; note it for the next pre-registration.
  - The 7 d decline is in BOTH the earliest and the latest bucket: beat close 62.3% to 40.7% for > 6 h, and 50.9% to
    29.4% for < 1 h. The 1-6 h bucket did not decline (59.7% to 60.9%). The decline is not a lead-time effect.
- **The forward copy cannot fill.** Since 11-25 00:00 CST, 15 bets were graded and 3 of them had a priced same-book
  close; the > 6 h bucket holds 1 priced game. At that rate 100 games take months.
- **Also seen:** only 99 of the 213 graded 7 d bets (46%) carry a priced same-book close. Since 11-25 it is 3 of 15.
  CLV readings now rest on a thin, non-random share of the book.
- **Still open:** where the 7 d gross decline (+1.11 to -0.41 pp) comes from. It is not lead time; sport, venue and
  market are the next splits. This is not yet a hypothesis, so nothing is pre-registered here.

## Where the 7 d closing-line decline comes from -- HYPOTHESES (written 12:37 PM CST, before the split)

User 11-27 ~12:36 PM CST: "Yes, split it" (answering "Should I split the 7-day closing-line decline by sport, venue
and market next?").

Read-only: the same `live_all.json` (reading 20261127T180404Z) and the review's own `bets_from_orders`, same-book
scope. The windows are DISJOINT, so a change has a clean range: PRIOR = 10-28..11-19 (23 d) and RECENT = 11-20..11-26
(7 d), both by `selected_date`. The review compares 7 d with 30 d, which overlap, so its 1.5 pp drop understates
the change.

Measures, per cell, for each window:
- gross CLV (pp), the headline that went negative;
- beat-close %;
- fee-net CLV;
- the share of graded bets that carry a priced same-book close.

Change = RECENT minus PRIOR, with SE = sqrt(se_recent^2 + se_prior^2), event-clustered per window. A game falls in
one window only. Dimensions:
- sport;
- venue;
- market, raw and coarse, set before reading: `totals` if the name has "total"; `spreads` if it has "spread" or
  "handicap"; `moneyline` for h2h / moneyline / ml / winner names; `props` if it has "player"; else `other`;
- path: `model_edge` / `maker_pilot` (by `execution_style`) / `market_fair` / other.

Hypotheses:
- **H1 venue:** the drop sits in one venue. Kalshi is the persistent 30 d loser, -6.8% on 591 games.
- **H2 sport:** the drop sits in one sport. NBA is about 73% of Suggested rows. Todo #863 (11-27) found NBA pregame
  quotes go stale 2 h after each scheduled pull, so an NBA fair could lag a moving market.
- **H3 market:** the drop sits in totals, persistent at -13.6% on 278 games.
- **H4 mix:** the drop is a MIX shift. RECENT bought a different sport/venue/market mix, and within each cell CLV did
  not change.
  - Test: the within-cell change is the actual RECENT mean minus the mix-expected mean. The mix-expected mean weights
    each cell's PRIOR mean by RECENT's bet count (cells with no PRIOR bets take the PRIOR overall mean).
- **H5 selection:** the drop comes from WHICH bets get a priced close. The priced share fell to 46% in 7 d. If the
  priced share fell unevenly (one venue's closes stopped pricing), RECENT's CLV describes a different population.

Falsification tests, fixed now:
- H1/H2/H3: a level "carries the drop" iff its gross change has a 95% range below 0, AND the rest of the book's
  gross change (all other levels pooled) has a range that includes 0. If several levels or none meet that, the
  hypothesis for that dimension is REJECTED (the drop is spread out, or there is too little data to place it).
- H4 survives iff the within-cell change's 95% range includes 0 on the dimension the mix test runs on. That is
  sport x venue x coarse market, collapsed to the coarser dimension when a cell has < 3 PRIOR games.
- H5 survives iff the priced share fell by >= 20 points in one venue while another venue's priced share moved
  < 10 points.

RECENT holds 73 priced games, so a range can be wide. A REJECTED for lack of data is reported as that, not as
innocence.

### RESULT, 2026-11-27 12:41 PM CST: Kalshi player props carry the drop, and over half of it is a change in what was bought

Scripts: `scratchpad/clvlead/split.py`, `split2.py`, `split3.py` and `nhlprops.py` (session 69d80317), run at Idle
priority on reading 20261127T180404Z. The floor log copy is `scratchpad/pf3/floor_log.json` (read 11-27 10:24 AM,
entries 10-20..11-25).

**The change is real.** Same-book gross CLV went from +1.40 pp to -0.41 pp, a change of **-1.81 [-2.59, -1.03]**.
PRIOR is 523 priced bets / 353 games; RECENT is 99 / 73. Beat close fell 63.9% to 43.4%. Fee-net CLV went -0.33 to
-2.17, a change of -1.83 [-2.62, -1.05].

| hypothesis | test reading | verdict |
|---|---|---|
| H1 venue | Kalshi -2.11 [-3.03, -1.19] (279 to 56 games); rest = Polymarket -0.90 [-2.06, +0.26] | **SURVIVES: Kalshi** |
| H2 sport | NCAAF -1.60 [-2.63, -0.57], NFL -1.81 [-3.39, -0.22], NHL -2.79 [-4.29, -1.28], each with the rest also below 0; NCAAB +0.16, soccer -0.61 (ranges include 0) | **REJECTED: spread over three sports** |
| H3 totals | totals +0.04 [-1.08, +1.17]: no decline | **REJECTED for totals** |
| H3, market dimension | coarse `other` -3.06 [-4.32, -1.79], rest -0.72 [-1.55, +0.12] | **the drop sits in `other`** |
| H4 mix | mix part -1.03 of -1.81 (57%); within-cell -0.78, see below | **narrowly SURVIVES** |
| H5 selection | priced share ROSE in both venues: Kalshi 41.7% to 51.8%, Polymarket 30.0% to 35.7% | **REJECTED** |

- **`other` is the player props.** The coarse rule set before reading needed "player" in the market name. The live
  names are ASSISTS, Receptions, GOALS, POINTS, Passing TDs and btts, so `other` is player props plus btts.
  - ASSISTS: -3.99 [-6.02, -1.97].
  - Receptions: -1.99 [-3.67, -0.31].
  - Venue x market (exploratory, not a pre-registered test): Kalshi props -3.40 [-4.75, -2.05] (125 to 20 games);
    Polymarket props -0.27 [-1.96, +1.42].
- **H4 depends on which range is used.** Within-cell is -0.78.
  - Counting only RECENT's error, the range is [-1.42, -0.13] (excludes 0).
  - Adding the PRIOR cell means' own error (se 0.24, so total se 0.41) gives [-1.58, +0.02] (includes 0).
  - The frozen test named no SE, and the fuller range is the correct one, so H4 narrowly survives.
  - Reading: at least half of the drop is mix. A within-cell decline is possible, not established.
- **What the mix shift is:**
  - In PRIOR, NHL Kalshi props were 95 of 353 priced games, at +3.18 pp gross.
  - In RECENT they are 11 priced bets. NFL Kalshi props (+0.30 pp in PRIOR) are now RECENT's largest cell, at 26
    bets.
  - Graded NHL Kalshi props by `selected_date`: about 2-17 a day from 11-06 to 11-21. There are none on 11-20,
    11-22 or 11-23 (cause not checked), and **0 on every day since the 11-24 08:30Z floor-off load**.
  - **142 of the 192 graded NHL Kalshi props selected 10-28..11-23 (74%) are in the EV floor log.** So the floor-off
    removed most of the book's best-closing cell.
- **That cell beat the close but did not make money.** Floor era 10-20..11-23, NHL Kalshi props admitted by the
  floor (142 bets / 87 games):
  - fee-net CLV +1.43 pp (se 0.55), gross +2.97, beat close 77.4%;
  - ROI **-9.92% [-24.4, +4.6]**, excess wins -3.4, fees 3.14% of stake.
  - The Suggested NHL Kalshi props (50 / 42) read the same way: CLV +1.65 net, ROI -26.2% [-54.1, +1.7].
  - So the close and the results disagree on this cell. That fits the 30 d "wins minus close" of -4.4 pp (z -2.14):
    the book wins LESS often than its closing prices imply.
  - Re-admitting the cell is NOT supported by this study. It would be a betting change, so it needs its own
    pre-registration and a window.
- **NBA has no same-book close, so the review's closing-line figures never included it.**
  - NBA is 584 of 1,375 graded PRIOR bets and 78 of 213 RECENT. 0 of them carry a same-book close.
  - In the 30 d window, 463 of 662 NBA closes resolved against a DIFFERENT book (`different_book_close`); 199 read
    `no_close_for_market`.
  - On that scope NBA did not decline: +1.35 to +2.17 pp, a change of +0.82 [-0.34, +1.98]; beat close 69.9% to
    77.0% (139 to 28 games).
  - A different-book level is not comparable with a same-book level; only its change is read here.
  - With 0 of the in-play bets priced either, the review's "losing to the close" describes the non-NBA pregame book:
    about 46% of graded bets in 7 d.

**Net answer:**
- The 7 d decline is real.
- It sits in Kalshi, mostly in player props.
- More than half of it is that the book stopped buying NHL Kalshi props, most of which came through the EV floor
  that went off on 11-24. Those props had beaten the close by about 3 pp gross yet lost money.
- It is not lead time (the 11-24 study above), not totals, not a single sport, and not a priced-close selection
  artefact.
- The open question it leaves is why bets that beat the close keep losing: wins minus close is -4.4 pp over 30 d.

## Why bets that beat the close still lose -- HYPOTHESES (written 12:57 PM CST, before the test)

User 11-27 ~12:45 PM CST: "Yes, look into it" (answering "Should I look into why bets that beat the closing price
still lose?").

**The gap.** Over 30 d the book wins 4.4 pp less often than its same-book closing prices imply (z -2.14). It beats
those closes by +1.11 pp gross, so it wins about 3.3 pp less often than its OWN fill prices imply.

**Facts read before writing these:**
- The same-book close is the venue's last pregame row in the quote log (`clv_join._resolve_from_quotes`,
  `close_source=book_quotes_last_pregame`).
- Kalshi's quoted price is the ASK: `kalshi_odds_refresh.py:2457` `yes_probability = dollars_to_probability(yes_ask)`.
  `kalshi_board_join.py:37` says the yes and no asks "do not sum to 1".
- So the close's implied probability for our side includes the spread, and so does every wins-minus-close figure.

Test data:
- The 30 d priced same-book bets (10-28..11-26, 622 bets).
- For each bet, the OTHER selection(s) of the same (event, market, segment, player, line) at the same book: their
  last quote before `commence_time`, from the fleet's own quote-log shards (`<sport>_source/tracking/book_quotes/`),
  read-only at nice 19.
- Overround o = sum of the selections' closing implied probabilities - 1.
- Fair close f = p_close / (1 + o).
- calib_ask = won - p_close (the review's figure); calib_fair = won - f; fair CLV = f - p_fill.
- Pushes are out of calib, as in the review.
- Bets where the other side cannot be found are counted. calib_ask is reported on the covered subset too, so a
  coverage bias shows.

Hypotheses, each with its falsification fixed now:
- **H-ASK (the spread):** the gap is the bid-ask spread inside an ask-priced close.
  - Survives iff, on the covered 30 d set, the mean overround has a 95% range above 0 AND calib_fair's 95% range
    includes 0.
  - Rejected iff calib_fair's range is entirely below 0.
  - It also predicts a venue contrast: Polymarket's slate prices are outcome prices that sum near 1, so its overround
    and its gap should both be near 0, and the gap should sit in Kalshi.
- **H-SEL (adverse selection / self-impact):** we buy the sides the fair close still overprices. That could be
  informed flow, or our own orders moving thin prop markets.
  - Survives iff calib_fair's range is entirely below 0 (the gap outlives de-vigging).
  - Then split descriptively by props vs game lines and by venue.
- **H-LUCK (noise):** survives iff calib_ask's 95% range includes 0 in BOTH disjoint windows, PRIOR 10-28..11-19
  and RECENT 11-20..11-26.

**CLV consequence, reported whichever hypothesis survives:** fair CLV, gross and net of fee. If fair CLV is <= 0, then
"beating the close" mostly measured the spread, not edge.

### RESULT, 2026-11-27 1:02 PM CST: H-ASK SURVIVES; "beating the close" was the spread; against the fair close the book pays too much

Scripts (session 69d80317, kept at `C:\tmp\pfmon\clvcal\`):
- `build_keys.py`: the 622 priced same-book bets, mapped to `clv_join._quote_match_key`.
- `fleet_quotes.py`: on the fleet at nice 19 / ionice idle; read-only. It loads the fleet checkout's `clv_join` by
  file path. 104 shards in 84.6 s, 5,412,579 lines kept by the event filter, 12,652 pregame kalshi/polymarket rows
  matched. 9 candidate shards were absent, all second-choice dates.
- `calib.py`: the de-vig and the ranges.

**Sanity:**
- Gross CLV rebuilt from fill and close matches the recorded figure on 622 of 622 bets.
- Our own side's last pregame quote equals the recorded close on 622 of 622.

**Coverage: 398 of 622 bets (286 of 422 games) have the other side's closing quote.**
- Kalshi 275 of 467; Polymarket 123 of 155. 14 were 3-way h2h, normalised over all three outcomes.
- The 224 uncovered are one-sided in the quote log (192 of them Kalshi).
- **Coverage is not random.** The covered subset's raw gap is -2.33 pp against -4.40 pp on all 621. That puts the
  uncovered bets at about -8.1 pp. That figure is derived from the two means, not separately tested.

Results, 30 d, covered set. Each cell is pp with its 95% range:

| measure | all covered (286 games) | Kalshi (210) | Polymarket (112) | game lines (200) | props (88) |
|---|---|---|---|---|---|
| overround at close | **+2.69 [+1.90, +3.48]** | +2.59 | +2.91 [+1.17, +4.66] | +2.60 | +2.84 |
| wins minus close (as the review computes it) | -2.33 [-7.49, +2.82] | -2.32 | -2.37 | -1.93 | -3.02 |
| wins minus FAIR close | **-1.03 [-6.19, +4.13]** | -0.91 | -1.29 | -0.91 | -1.24 |
| CLV vs the close as quoted, gross | +0.56 [+0.07, +1.06] | +0.73 | +0.20 | +0.08 | +1.38 |
| **CLV vs the FAIR close, gross** | **-0.74 [-1.17, -0.31]** | -0.68 [-1.17, -0.19] | -0.88 [-1.66, -0.09] | -0.94 [-1.50, -0.37] | -0.41 [-1.05, +0.23] |
| CLV vs the FAIR close, net of fee | **-2.53 [-2.96, -2.09]** | -2.26 | -3.13 | -2.83 | -2.01 |

**Verdicts, by the tests fixed above:**
- **H-ASK SURVIVES.** The overround's range is above 0 (+2.69 [+1.90, +3.48]), and wins minus the fair close
  includes 0 (-1.03 [-6.19, +4.13]).
  - Its venue sub-prediction is FALSIFIED. Polymarket's closing quotes carry the same spread (+2.91), so the
    belief that its slate prices "sum near 1" was wrong.
- **H-SEL REJECTED (not established).** Wins minus the fair close includes 0. With outcome noise of about +-5 pp at
  this sample, a 1 pp adverse-selection effect cannot be seen or ruled out.
- **H-LUCK SURVIVES.** Wins minus close as quoted includes 0 in both disjoint windows: PRIOR -4.28 [-8.68, +0.12]
  (353 games) and RECENT -5.06 [-15.0, +4.88] (73). The 30 d -4.40 [-8.44, -0.36] (z -2.14) clears 0 only on the
  pooled set.

**What this answers:**
- **The bets do not beat the close.** The closing price is quoted with a spread of about 2.7 pp across both
  outcomes, so the close's implied probability for our side sits about 1.3 pp above the fair one.
- Measured against that FAIR close, the book pays **0.74 pp more than the fair closing probability** before fees,
  and 2.53 pp more after fees. That holds on both venues and on game lines; on props the range reaches 0.
- So the reported "+1.11 pp, beats the close 60.6% of the time" is the spread, not edge.
- The realised result agrees. Wins minus fill price is -3.29 [-7.38, +0.80] over 621 bets, within noise of the
  -0.74 the fair close predicts.
- The -4.4 pp "wins below the close" splits into about 1.3 pp of spread plus noise. It needs no extra
  explanation at this sample.

**Consequences for the instruments, all measurement and none a betting change:**
1. Every same-book CLV figure the review, the gate (condition 3) and Portfolio Watch report is computed against an
   ask-priced close, so each overstates edge by about half the overround.
   - Fair CLV needs the other side's closing quote. `clv_join._resolve_from_quotes` reads only our selection.
   - Stamping the other side's close, or the overround, on the closing mark is a code change in `clv_join.py` /
     `order_clv.py`, which no open lane claims. It needs its own lane.
2. 192 Kalshi bets are one-sided in the quote log, so they cannot be de-vigged at all. The venue quotes BOTH asks
   (`yes_ask` / `no_ask`, `venue_quote_at_submit` on 149 recent Kalshi orders), so the quote log could carry both.
3. NBA (different-book closes) and in-play bets remain outside this measure.

### Lane `clv-fair-close` opened, 2:32 PM CST (user: "Yes, open it")
- It claims `clv_join.py`, `order_clv.py`, `paper_settlement.py` and a new `tests/test_clv_fair_close.py`. No open lane
  held any of them (checked against origin/main's claims, including directory and glob claims).
- Scope: stamp the close's overround and a fair CLV beside the quoted one on NEW same-book marks. `close_price`,
  `close_book_scope` and `clv_pct` stay unchanged, because `min_ev_tuner._gross_clv` reads them. Old marks are not
  rewritten; for them the 30 d study above is the reading.
- The readout half stays in this lane (`portfolio-monitor` holds `live_book_edge_readout.py`).
- Building it, and any load, wait for the user's yes. A load restarts the role that settles, so the restart rules apply.
