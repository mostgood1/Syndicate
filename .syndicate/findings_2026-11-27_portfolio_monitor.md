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
