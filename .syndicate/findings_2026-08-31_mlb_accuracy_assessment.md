# FINDINGS — MLB accuracy and profitability, full assessment

**Session** `3bb44ef2-a199-430e-afce-c3034bf48d9d`, lane `mlb-accuracy-assessment`.
**Date** 2026-08-31. **Every number below is read off production**
(`https://syndicate-an21.onrender.com`), not off the local checkout, and each
carries its n and window. Where a conclusion is an inference it says so.

Builds on `layer2-accuracy-audit` (2026-08-31, UNOWNED) rather than repeating
it. That lane's named gap — *"whether the board's own `ev_pct` /
`model_edge_pct` / `score` PREDICT the outcome"* — is **CLOSED here**, section 4.

---

## 0. The headline, in one paragraph

The MLB sim is **well calibrated and weakly informative**. The market is
**more** informative. `model_edge_pct` is defined as sim minus market, so it
isolates the sim's *error* rather than its *information* — and it is measurably
anti-predictive: `corr(claimed edge, win) = -0.1379` on 360 moneyline sides.
Every surface that stakes money on that edge loses; every surface that stakes
money on price dispersion wins. The player-prop engine is worse than that: its
side selection is **inverted** — the batters it takes OVER *under*-produce the
batters it takes UNDER, in 5 of 6 (market, line) cells, significant at
z = -4.12 on home runs (n=1,690).

---

## 1. Instrument state — what is and is not measurable (read this first)

| instrument | verdict |
|---|---|
| `/mlb/api/market-accuracy` | **USABLE, but it is not a slate instrument.** 8,918 graded rows 2026-04-10..08-31. Supply collapsed: 5,292 rows in June, 2,781 in July, **285 in August**. The published headline is the `official` tier only: 66 bets in 30 days, ~1 game-line/day. Confirms `todo #610` / `#611`. |
| `/mlb/api/live-lens-accuracy` | **PROVABLY BROKEN — GRADER FIXED 2026-08-31, see section 7e; still UNMEASURABLE because the feed it needs is not published to web.** Over 2026-07-01..08-31 the pooled `by_klass` is `over: 0 wins / 1,578` and `under: 206 wins / 206`. A model cannot go 0-for-1578 and 206-for-206. The grader is comparing the projection against an **in-progress** stat line, so the side that is behind at snapshot time always "loses". The published 6.5% hitter-prop hit rate is an artefact, not a measurement. Separately the input artifact exists on only **11 of 61 days**. |
| `markets.ml` / `markets.totals` on a finished card | **CONTAMINATED on 13 of 193 (6.7%) priced games** — settled/dead prices (`-100000` / `+99900`, overround 1.0000). A naive backtest over this field returned **+101% to +331% ROI**; after filtering (`abs(odds)>1000`, or overround outside 1.010-1.12) the same backtest returns **-2.80%**. Anyone reading this field must filter. |
| `/api/portfolio/live?date=` | **The `date` param is IGNORED.** `?date=2026-08-29` and `?date=2026-08-26` both return the 2026-08-31 payload byte-for-byte. Real-money history is not retrievable from the web service. |
| Polymarket real-money ROI | **ACCOUNTING DEFECT.** `polymarket/game_line` reports `roi_pct: -159.38` on `staked_dollars: 16.37`, `pnl_dollars: -26.09` — a loss larger than the stake on binary contracts. Fees or contract cost sit outside the stake denominator. |

---

## 2. Pregame sim, GAME markets — calibrated, weakly informative, dominated

`n = 482` finals over **39 dates, 2026-06-17..2026-08-30**, from
`/mlb/api/cards?date=`. Sim probabilities are pregame (range 0.119-0.799,
mean 0.5070 vs a 0.5104 base rate; zero values pinned at 0 or 1, so not
live-contaminated).

**Moneyline**
- mean sim home prob 0.5070 vs actual home-win 0.5104 — **bias -0.34pp**: calibrated.
- Brier **0.24307** vs climatology 0.24989 — **skill score +2.73%**.
- AUC **0.5904**. Straight-up favourite accuracy 56.43%.

**vs the market**, on the 180 games with clean two-sided prices:

| | Brier | LogLoss | AUC | skill |
|---|---|---|---|---|
| SIM | 0.23719 | 0.66683 | 0.6155 | +0.70% |
| MARKET (de-vig) | **0.22663** | **0.64701** | **0.6746** | **+5.12%** |
| 50/50 blend | 0.22827 | 0.64863 | 0.6682 | +4.43% |
| climatology | 0.23886 | 0.67069 | 0.5000 | 0.00% |

On the **69 games where sim and market disagree on the favourite, the market is
right 59.4% and the sim 40.6%.** A 50/50 blend does not beat the market alone.

**Run totals** — the shape is genuinely good and the signal is not:
- sim mean total 8.708 vs actual 8.861 — bias **-0.153 runs/game**
- sim distribution sd 4.821 vs the sd actually needed 4.717 — dispersion is right
- PIT deciles `[42 50 37 45 57 44 57 48 54 48]` against 48.2 expected — **uniform**; mean PIT 0.5162
- **`corr(sim mean total, actual total) = 0.169`** — near-zero discrimination
- vs the posted line: sim projects over 51.2% of the time, actual went over 43.9%

---

## 3. Pregame sim, PLAYER PROPS — the side selection is INVERTED

`n = 8,918` graded rows, 2026-04-10..2026-08-31, both tiers.

Pooled: `official` **-7.43% ROI** (n=2,066, hit 52.37% vs 55.53% implied);
`candidate` **-11.60%** (n=6,852, 42.79% vs 45.72%).

**The loss is concentrated entirely on the OVER side.** Restricting to
near-symmetric prices (market-implied 40-60%), where the vig splits evenly and
the comparison is clean:

| side | n | realized | market implied | gap | ROI |
|---|---|---|---|---|---|
| **over** | 1,332 | 44.67% | 50.37% | **-5.70pp** | **-12.24%** |
| under | 1,554 | 53.15% | 53.19% | -0.04pp | -0.08% |

Unders are exactly market-neutral. Overs are 5.7pp worse than the price.

**The discrimination test — controlled on (market, line), asking whether the
batters taken OVER actually out-produce the batters taken UNDER:**

| market | line | over n / mean | under n / mean | diff | t | verdict |
|---|---|---|---|---|---|---|
| hitter_home_runs | 0.5 | 1,497 / 0.119 | 193 / 0.238 | **-0.119** | **-3.32** | INVERTED |
| hitter_hits | 0.5 | 1,222 / 0.797 | 401 / 0.803 | -0.006 | -0.12 | INVERTED |
| hitter_total_bases | 1.5 | 660 / 1.474 | 752 / 1.605 | -0.131 | -1.31 | INVERTED |
| hitter_rbis | 0.5 | 637 / 0.399 | 671 / 0.475 | -0.077 | -1.63 | INVERTED |
| hitter_runs | 0.5 | 356 / 0.458 | 516 / 0.483 | -0.025 | -0.51 | INVERTED |
| hitter_hits | 1.5 | 51 / 1.275 | 108 / 1.028 | +0.247 | +1.47 | correct |

**Home runs, the load-bearing cell.** P(>=1 HR): model says OVER gives
**10.96%** (n=1,497); model says UNDER gives **21.24%** (n=193); population base
rate across all graded HR rows **12.13%**. Two-proportion **z = -4.12**. The
model's over picks homer *below* the base rate of the very population it is
choosing from, and its under picks homer at nearly twice it. Home runs alone
are **-233u of the -489u total** across all 8,918 rows.

**Two alternatives considered and both weakened:**
- *DNP graded as 0 rather than voided.* Would depress overs and **lift** unders
  by roughly z(1-m), about +4pp. Unders sit at -0.04pp, so this cannot be the
  mechanism. It also cannot touch the over-vs-under *difference*, which is
  where the inversion lives.
- *Partial box scores (the live-lens bug leaking into pregame grading).* Tested
  by first-pitch time: zero-rate 51.8% / 59.9% / 54.4% / 57.3% across
  `<15:00 / 15-18 / 18-20 / 20:00+` — **no gradient**, so no late-game
  contamination. The elevated absolute zero rate (43.1% on hits vs a ~33%
  qualified-starter reference) is explained by coverage: **median 49 graded prop
  rows per game**, about 24 per side, which reaches well past the starting nine.

---

## 4. Does the claimed edge predict the outcome? NO. This closes `layer2-accuracy-audit`'s open item.

MLB moneyline, clean prices, **360 candidate sides**:

| claimed edge | n | sim p | market p | ACTUAL | ROI at the quoted price |
|---|---|---|---|---|---|
| -1.00..-0.10 | 75 | 0.455 | 0.610 | **0.627** | +1.04% |
| -0.10..-0.05 | 64 | 0.475 | 0.535 | 0.547 | -4.71% |
| -0.05..0.00 | 55 | 0.483 | 0.496 | 0.455 | -12.21% |
| 0.00..+0.05 | 65 | 0.524 | 0.485 | 0.508 | -5.62% |
| +0.05..+0.10 | 55 | 0.525 | 0.438 | **0.382** | -16.71% |
| +0.10..+0.20 | 33 | 0.558 | 0.415 | 0.424 | -5.50% |

- **`corr(claimed edge, win) = -0.1379`**
- `corr(sim prob, win) = +0.2344`
- `corr(market de-vig prob, win) = +0.3184`

Game totals, 392 sides: `corr(claimed edge, win) = -0.0202`,
`corr(sim prob, win) = +0.0331`, `corr(market, win) = +0.1224`.

**The mechanism, stated plainly.** The sim carries real information (+0.234 on
moneyline) but strictly less than the market (+0.318). `model_edge = sim -
market` therefore subtracts a *better* estimator from a *worse* one, and what
survives is the sim's error term. Staking on it is staking on the error. This
is not a plumbing defect, and no amount of joining `model_edge_pct` onto more
rows will fix it.

---

## 5. Layer 1 and Layer 2 boards, MLB

**Layer 1 (model edge) is absent from MLB Layer 2 today.** On the served
`/api/board/layer2-shortlist` (2026-08-31, 200 MLB rows of 10,804 considered):
`model_edge_pct` numeric on **0 / 200**; `model_ev_pct` **0 / 200**; `ev_pct`
200/200 with `ev_basis = market_fair` on every row. 140 of 200 rows are LIVE.

The paper exchange books refuse everything for the same reason:
`kalshi rows_in=143 refusals={"no_model_edge_pct": 143}`,
`novig 249/249`, `prophetx 192/192`. **100% refusal.**

Given section 4, that is currently protecting the bankroll, not costing it.

**What IS on the board is price dispersion, and MLB's is healthy.**
`book_age_seconds` median **202s**, p90 1,308s, only 0.5% beyond an hour —
far better than the platform-wide median of 4,498s the prior lane measured.
On the 137 shortlist rows quoting 3 or more books, best price vs the *median*
book is **+9.45% median payout** (mean +11.59%, p25 +7.23%). Median books
quoting per row is only **5** (p10 = 3), so the dispersion is real but thinly
sampled. Best price is held by draftkings 35, **kalshi 25**, betmgm 14,
prophetx 9, pinnacle 8. Exchange presence: kalshi on 69 of 200 rows,
prophetx 41, novig 31, **polymarket 25**.

---

## 6. Realized profitability, 2026-08-22..2026-08-31

From `/api/portfolio/paper?date=` over 16 fetched dates (10 carry settlement).
MLB is 470 of 511 settled rows (92%).

**Pooled: 511 settled, 46.38% win, staked $2,354.28, pnl +$88.45, ROI +3.76%.**
By sport: mlb +4.90% (470), wnba -2.17% (34), soccer -33.27% (7).

**By market family — the same decomposition as sections 2 and 3, in dollars:**

| family | settled | win | staked | pnl | ROI |
|---|---|---|---|---|---|
| game_line | 178 | 52.8% | $868.43 | +$135.06 | **+15.55%** |
| game_total | 188 | 47.3% | $924.62 | +$61.53 | +6.65% |
| **player_prop** | 145 | 37.2% | $561.23 | **-$108.16** | **-19.27%** |

**By paper venue book** (these are NOT additive — each venue prices the same
slate in its own book, so one opportunity can appear in several):

| book | settled | win | ROI |
|---|---|---|---|
| paper:polymarket/game_line | 85 | 44.7% | **+40.89%** |
| paper:kalshi/game_line | 80 | 48.8% | **+30.82%** |
| paper:polymarket/game_total | 99 | 54.5% | +25.63% |
| paper:novig/game_line | 33 | 51.5% | +16.64% |
| paper:prophetx/game_total | 49 | 51.0% | +12.71% |
| paper:novig/game_total | 31 | 48.4% | +9.13% |
| paper:kalshi/game_total | 110 | 40.9% | +2.12% |
| paper:prophetx/game_line | 62 | 50.0% | -4.64% |
| **paper:kalshi/player_prop** | 207 | 38.2% | **-11.96%** |

**CAVEAT, and it is a large one: all 511 are `settled_by = inferred` — our own
grading, no venue confirmation.** Real money on 2026-08-31: 14 settled,
21.43% win, -$47.96 on $61.05, **-78.56% ROI**; kalshi -39.29% (10),
polymarket -141.40% (4, and see the accounting defect in section 1). The
`layer2-accuracy-audit` lane measured the 2026-08-24..08-30 real-money book at
**239 settled, 42.3% win, -5.5% ROI** against paper's +9.4% over the same days.
Paper is optimistic against real money in every reading either lane has taken.

---

## 7. What is unmeasured, and why

- **Live sim accuracy, games and props.** The only instrument is broken
  (section 1) and its input artifact is missing on 50 of 61 days. 140 of the 200
  served MLB Layer 2 rows are live and none carries a model number, so there is
  nothing to grade even if the grader worked. **Unmeasurable today.**
- **Segment markets (F1/NRFI, F3, F5).** The card publishes a full
  `total_runs_dist` for each segment but carries **no segment ACTUAL**, and the
  scoreboard block holds only a label. Not gradeable from any served surface.
- **Real-money history beyond today**, because of the ignored `date` param.
- **Layer 2 board rows joined to outcomes.** Shortlist artifacts are retained
  about 4 days (prior lane, confirmed), so an edge-bucket curve on the *board's*
  own score cannot be built retrospectively. Section 4 answers the same question
  through the sim, which is the input to that score.

---

## 7b. WHAT WOULD MAKE PROPS VIABLE — measured 2026-08-31, after the first pass

**This section REPLACES the first pass's "stop staking MLB props" recommendation.**
A narrow subset already is viable, and closing the gap is a PRICE problem, not a
model problem. The plan in section 8 is reordered accordingly.

**The identity that governs it.** `ROI = p_realized / q_quoted - 1`, exactly.
Two levers only: raise what the picks realize, or lower the price paid.

**The under book already realizes what it is priced at.** 1,554 symmetric-priced
unders: realized **53.15%** against quoted-implied **53.19%**, gap **-0.04pp**.
The quote INCLUDES the hold, so a book landing on its own quoted implied is
beating the FAIR line by exactly the hold it pays. It does not need a better
model.

**Lever 1 — delete the over side.** No price filter rescues it; this is a
uniform over-side defect, not longshot bias:

| band | n | gap vs implied | ROI |
|---|---|---|---|
| <= -150 | 1,024 | -7.80pp | -11.14% |
| -150..-100 | 694 | -6.95pp | -13.09% |
| +100..+150 | 608 | -4.06pp | -11.67% |
| +150..+300 | 1,164 | -3.29pp | -10.33% |
| > +300 | 1,528 | -4.21pp | -31.56% |

**Lever 2 — delete home runs and hits+runs+RBIs:**

| under book | n | gap | ROI |
|---|---|---|---|
| all unders | 3,764 | -0.27pp | -0.64% |
| minus home runs | 3,571 | +0.13pp | -0.19% |
| **minus HR and HRR** | **2,571** | **+0.68pp** | **+0.65%** (SE 0.96pp) |

Survivors: **hits, total bases, runs, RBIs — unders only.** 2,571 bets over five
months, marginally positive.

**Lever 3 — buy a better price. This is where viability comes from.** Holding
realized fixed at the measured 0.5315:

| target ROI | drop in implied | payout gain needed |
|---|---|---|
| +2% | 1.08pp | +2.08% |
| +5% | 2.57pp | +5.08% |
| +10% | 4.87pp | +10.08% |

Measured dispersion on MLB **prop** rows on the served board: **+10.61% median
payout** (best vs median book, p25 +7.83%, p75 +14.95%). **The requirement sits
inside the dispersion that exists.**

**THE BINDING CONSTRAINT, and it lands on the exchange thesis.** Of 103 MLB prop
rows on the served shortlist, only **51 carry >= 3 books**; median **3 books**,
max **7**; best price is draftkings on 31 of 51. **ZERO of the 103 rows are
quoted by kalshi, polymarket, novig or prophetx** *(count correct; see the
retraction below)*.
~~The venues where the hold would collapse do not quote MLB player props on this
board at all.~~
**RETRACTED 2026-09-01 — SEE SECTION 7f. The count is right and the conclusion
drawn from it is wrong.** It was read off `quote.book_prices`, which is the
OddsAPI AGGREGATOR view, and OddsAPI carries **game lines only for exchanges**.
Kalshi demonstrably quotes MLB props: **23 filled orders with real Kalshi
tickers** (`KXMLBHR-`, `KXMLBHIT-`, `KXMLBTB-`, `KXMLBHA-`). The
CONTRADICTION with `paper:kalshi/player_prop`'s 207 settled rows is RESOLVED —
both readings were true of different things. **The real finding is that the
board cannot SEE exchange prop prices, so its price shopping never considers
them**, which is a visibility defect in the board rather than an absence in the
market. The +10.61% dispersion below was therefore computed across sportsbooks
ALONE.

**Lever 4 — market admission by cost of entry, which varies 13x.** Points of
real skill required to break even against a random pick from the same pool,
measured on the OVER side where the model takes 75-92% of the pool so selection
barely distorts the comparison:

| market | line | n | pool rate | quoted | BAR | delivered |
|---|---|---|---|---|---|---|
| pitcher_strikeouts | 4.5 | 79 | 38.75% | 52.85% | **+14.10pp** | -0.78pp |
| hitter_total_bases | 0.5 | 260 | 49.65% | 57.59% | +7.95pp | +0.35pp |
| hitter_hits | 0.5 | 1,222 | 55.58% | 63.20% | +7.63pp | -0.50pp |
| hitter_total_bases | 1.5 | 660 | 36.90% | 39.87% | +2.97pp | -2.05pp |
| hitter_home_runs | 0.5 | 1,497 | 12.13% | 14.95% | +2.82pp | -1.17pp |
| hitter_rbis | 0.5 | 637 | 28.13% | 29.99% | +1.85pp | -0.98pp |
| **hitter_runs** | 0.5 | 356 | 37.61% | 38.68% | **+1.07pp** | +0.03pp |

Nothing wins pitcher strikeouts at a 14-point bar. **CAVEAT: this decomposition
is CONFOUNDED on the UNDER side** by which players get selected into it — the
ROI figures elsewhere in this section are not. Directional only.

**TWO THINGS THIS RULES OUT.**
- **Inverting home runs is NOT the play.** The inversion is real (z = -4.12) but
  flipping does not pay: entry costs +2.82pp there and the flipped signal is
  worth roughly +1.2pp.
- **The inversion cannot be priced from the GRADED LEDGER.** **0 of 8,778**
  player-date-market-line keys carry both sides; only the chosen side's price is
  ever recorded.
  **[CORRECTED 2026-08-31, later the same session.]** I wrote that recording both
  prices going forward "makes the sign-error question answerable RETROACTIVELY
  across the 8,918 existing rows". **That was wrong** — a forward-looking write
  cannot populate rows already graded. The conclusion survives by a different
  route, and a better one: **the opposite side is ALREADY in the odds history.**
  Measured on `data/mlb_source/tracking/odds_mlb_hitter_props_history_2026-07-11.csv`
  (622 rows, schema `player_name,market,selection,line,price,snapshot_ts`):
  **185 of 227 player/market/line groups carry BOTH sides — 81.5%.** So the
  inversion is priceable TODAY by joining the graded ledger against odds history,
  with no code change and no waiting.
  Production route: those per-market CSVs are **NOT** in `HOT_ARTIFACT_PATTERNS`
  (`/api/ops/artifacts/export?pattern=*hitter_props_history*` returns `count: 0`,
  and absence there is not absence on disk). `*_source/tracking/book_quotes/*.jsonl`
  IS allowlisted and carries the bookmaker dimension, so that is the route for a
  full-season join.
  Recording both sides at selection time is still worth doing — 81.5% is not
  100%, and the mirror is lossy — but it is **no longer the unblocker** and it
  drops down the list accordingly.

**DISCIPLINE:** ~20 cells were tested. `hitter_hits @ 1.5` looks excellent on
both sides and is n=51 / n=108. Do not trade it.

---

## 7c. ITEM 02 EXECUTED — the inversion does NOT pay, and there is NO sign error

**Done 2026-08-31. n = 7,015 joined rows over 23 dates, 2026-04-10..08-30.**
The join is INSIDE ONE ARTIFACT, not against odds history: the graded
`season_betting_day_*.json` carries `all_settled_rows` (outcome, odds, side) AND
`markets.{hitter,extraHitter,pitcher,extraPitcher}Props` (`model_prob_over`,
`market_prob_over`, `market_prob_under`, `market_no_vig_prob_over`) in the same
file. Joined on `(player, prop, market_line)`. **Join rate 7,015 / 8,782 =
79.9%**; 1,765 lost to null probability fields, 2 to an unmatched key.

**A THIRD CORRECTION to my own item 02 framing.** I said first "record both sides
forward, it answers this retroactively" (wrong — a forward write cannot fill
graded rows), then "join against odds history" (workable but unnecessary). The
answer was in the same artifact the graded rows already come from;
`market_accuracy._normalized_rows` projects 14 keys and drops the rest. That is
the third time this session the discriminating field was already inside a
payload I had fetched.

**Note on the source path.** `/mlb/api/season/<yr>/betting-card/day/<date>` serves
a DIFFERENT artifact (`season_day_*_retuned.json`, `source_kind:
canonical_daily_fallback`) whose `all_settled_rows` is **0** on the high-volume
dates while its `all_unresolved_rows` is populated. Use
`/api/ops/artifacts/export?path=...betting_day_payloads_retuned/season_betting_day_*.json`.
One endpoint, two code paths — again.

### (a) THERE IS NO COMPARATOR SIGN ERROR. The leading hypothesis is DEAD.

**7,014 of 7,015 rows (100.0%) pick OVER exactly when `model_prob_over >
market_prob_over`.** Cross-tab: `(under, model<=mkt) 3,762`, `(over, model>mkt)
3,252`, `(over, model<=mkt) 1`. The selection rule does precisely what it says.
**Plan item 09's "check the comparator sign first" is WITHDRAWN** — it would
have been an afternoon spent on a function that is correct.

### (b) INVERTING DOES NOT PAY, at any plausible price

The graded ledger records only the side taken, so the opposite QUOTED price is
reconstructed as `no_vig(opposite) + measured vig share`. The vig share is
measured, not assumed: `quoted_implied(selected) - no_vig(selected)` has median
**+0.0379** (p25 +0.0290, p75 +0.0429) across all 7,015 rows. A symmetric split
is still an assumption, so this is an ESTIMATE of the flip. It does not matter,
because it never turns positive:

| vig share on the opposite side | flipped ROI |
|---|---|
| +0.0000 (impossible — a free price) | **-2.55%** |
| +0.0200 | -6.77% |
| **+0.0379 (measured median)** | **-10.22%** |
| +0.0500 | -12.39% |
| +0.0800 | -17.31% |

As-bet the book is **-5.83%**; flipped it is **-10.22%**. Per cell the flip beats
the original in only 3 of 8 and is positive in none. **The inverted
discrimination measured in section 3 is real as a statistic and does not convert
into money** — the two-sided vig is larger than the signal.

### (c) THE REAL DEFECT IS CALIBRATION, AND ITS EXTREME IS A BUG

Model against market on `P(over)`, all 7,015 rows:

| | Brier | LogLoss | AUC | skill vs climatology |
|---|---|---|---|---|
| MODEL `prob_over` | 0.26913 | **1.92046** | 0.5835 | **-10.80%** |
| MARKET (de-vig) | 0.22932 | 0.64989 | 0.6416 | +5.59% |
| climatology | 0.24289 | 0.67886 | 0.5000 | 0.00% |

A LogLoss of 1.92 against a Brier of 0.269 is the signature of confident, wrong
extremes. The calibration curve confirms it, and the error is monotone at BOTH
tails:

| model bucket | n | predicted | actual | error |
|---|---|---|---|---|
| 0.00-0.00 | 701 | **0.000** | **0.458** | **-0.458** |
| 0.00-0.25 | 702 | 0.089 | 0.316 | -0.228 |
| 0.25-0.30 | 701 | 0.283 | 0.274 | +0.009 |
| 0.30-0.34 | 702 | 0.324 | 0.288 | +0.036 |
| 0.34-0.38 | 701 | 0.359 | 0.389 | -0.031 |
| 0.38-0.43 | 702 | 0.400 | 0.389 | +0.011 |
| 0.43-0.53 | 701 | 0.470 | 0.432 | +0.037 |
| 0.53-0.63 | 702 | 0.589 | 0.513 | +0.076 |
| 0.63-0.68 | 701 | 0.656 | 0.541 | +0.115 |
| 0.68-1.00 | 702 | 0.753 | 0.557 | **+0.196** |

The middle five buckets are well calibrated (errors +0.009 to +0.036). **The
engine is only wrong where it is confident** — and "model > market" fires
hardest exactly there, which is how a well-behaved middle still produces a
losing book.

**THE BUG AT THE BOTTOM. 993 rows — 14.2% of the joined book — carry a
`model_prob_over` of exactly `0.000`.** A literal assertion of impossibility.
**992 of the 993 are `batter_hits_runs_rbis`.** The market priced those at a
median **48.0%** (p10 0.417, p90 0.554). They actually went over **45.5%** of the
time. Two rows carry an exact `1.000`; both lost.

That is not a modelling shortfall, it is the unfed-field failure mode
`docs/ai_context/model_engine_standard.md` exists to prevent — a neutral default
standing in for a computation that never ran, indistinguishable from a working
feature at every level except the data. **14.2% of the prop book is staked off a
null.**

**And the irony that must be stated, because it inverts the obvious fix:**
removing the zero-probability rows makes the book **WORSE**, -5.83% to -6.35%.
`prob=0` always forces UNDER, unders are roughly market-neutral, and those rows
run **-2.17%** against the rest of the book at -6.35%. **The broken market is
outperforming the working ones.** Fixing the null will not by itself make money —
it moves 993 bets off an accidental under-bias and onto a model whose extremes
are measurably worse than that accident. Fix the calibration FIRST, or this
regresses.

### (d) Within-cell discrimination — the honest version

Pooled AUC is confounded: `P(over)` runs from 12% on HR 0.5 to 55% on hits 0.5,
so a probability that merely knows which market it is scores well. Within
`(market, line)`:

| market | line | n | P(over) | MODEL auc | MARKET auc |
|---|---|---|---|---|---|
| batter_hits | 0.5 | 1,618 | 0.555 | 0.5254 | 0.5647 |
| batter_rbis | 0.5 | 1,307 | 0.281 | 0.5554 | 0.5836 |
| batter_total_bases | 1.5 | 1,145 | 0.388 | 0.5261 | 0.5651 |
| batter_hits_runs_rbis | 1.5 | 956 | 0.449 | 0.4934 | 0.5617 |
| batter_runs_scored | 0.5 | 872 | 0.376 | 0.5664 | 0.5964 |
| batter_total_bases | 0.5 | 284 | 0.496 | 0.5239 | 0.5828 |
| batter_home_runs | 0.5 | 199 | 0.211 | 0.5237 | 0.6034 |
| batter_hits | 1.5 | 158 | 0.310 | **0.5902** | 0.5344 |

**n-weighted within-cell AUC: MODEL 0.5338, MARKET 0.5736.** The model has a
little real discrimination and the market has more, in 7 of 8 cells. The single
cell the model wins is n=158 — the same cell section 7b already flagged as
not-tradeable.

### (e) The Tier-0 rule re-derived on this independent join

| book | n | hit | ROI |
|---|---|---|---|
| all overs | 3,253 | 44.05% | **-11.32%** |
| all unders | 3,762 | 60.58% | -0.63% |
| **unders, minus HR and HRR** | **2,569** | 61.58% | **+0.67%** |
| unders, minus HR only | 3,569 | 59.60% | -0.18% |

**+0.67% here against +0.65% measured on the full 50-date ledger** — the rule
survives re-derivation on an overlapping but not identical population. Unders
positive on their own: `batter_hits` +4.29% (n=515), `strikeouts` +13.95%
(n=51, do not trade), `batter_runs_scored` +0.19% (n=525).

### What this does to the plan

- **Item 09 "check the comparator sign first" is WITHDRAWN.** No sign error exists.
- **Replaced by a calibration item**: isotonic or Platt on `model_prob_over`,
  fitted per `(market, line)`, plus a hard refusal on `prob in {0.0, 1.0}` — a
  certainty a Monte Carlo sim should never emit for a batter event.
- **The `batter_hits_runs_rbis` null is its own defect** and belongs in the
  engine-standard checklist (`scripts/sim_input_checklist.py`), not in the
  betting plan. It must be fixed AFTER the calibration, per the irony above.
- **Section 7b's conclusion STRENGTHENS.** The model's own probability is not
  where the value is; the price is. Nothing here argues for staking more on the
  model.

---

## 7d. ITEM 01 EXECUTED — and the rule I wrote was aimed at the wrong book

**Done 2026-08-31.** Item 01 shipped, but not as specified. The specification
said *cut prop OVERS, home runs and HRR, keep the under book*. **That rule was
derived from a book that does not risk any money, and applied to the staking
path it would have been inert.** What shipped is a sport-scoped market-FAMILY
exclusion, justified on the staked book's own evidence.

### THERE ARE TWO PROP BOOKS AND I HAD BEEN CONFLATING THEM

**Book A — the vendor season betting card.** 8,918 graded rows; everything in
sections 3, 7b and 7c is measured on this. `grep` across `pipeline/`,
`portfolio_commit.py` and `layer2_board.py` returns **zero** references to
`season_betting_card`, `betting_day_payloads` or `locked_cards`. **It is not a
staking input anywhere.** It is a paper surface, and its measured -5.70pp
over-side defect risks nothing.

**Book B — the portfolio, which does risk money.** It commits off
`read_layer2_shortlist`. Measured across 16 dates, 2026-08-22..08-31:

| | n decided | win% |
|---|---|---|
| MLB game markets | 359 | 47.9% |
| **MLB player props** | **257** | **42.0%** |

and from the settlement totals, `player_prop` **-19.27% ROI on $561.23**
(145 settled) against `game_line` +15.55% and `game_total` +6.65%.
`paper:kalshi/player_prop` is -11.96% over 207 settled.

### THE SIDE RULE DOES NOT TRANSFER, AND THAT IS MEASURED, NOT ASSUMED

In Book B the sides are indistinguishable:

| side | n | win% |
|---|---|---|
| over | 99 | 41.4% |
| under | 158 | 42.4% |

Against Book A's over 44.05% / under 60.58%. **The over-side defect simply is
not present in the staked book**, and the reason is visible on the served
board: `model_edge_pct` is numeric on **0 of 103** MLB prop rows and `ev_basis`
is `market_fair` on all 103. **Side selection on the staking path is price, not
projection.** A side rule there would have refused nothing that deserved it.

The two books do not even trade the same markets. Book B stakes `strikeouts`
(98), `totals_alt` (64), `outs` (38), `hits_allowed` (28), `earned_runs` (20),
`h2h_3_way` (22) and `walks_allowed` -- `earned_runs` and `hits_allowed` appear
nowhere in the graded ledger at all.

### WHAT SHIPPED

`resolve_excluded_families()` in `portfolio_commit.py`, env
`SYNDICATE_PORTFOLIO_EXCLUDED_FAMILIES`, default **`mlb:player_prop`**.
Refusal name `market_family_excluded`, applied FIRST in the commit loop -- the
same ordering `layer2_board`'s `excluded_markets` uses, so an excluded row
cannot be re-seated and the surviving refusal counters describe only in-scope
rows.

- **Sport-scoped on purpose.** The finding is MLB-only; NFL and NBA prop books
  have never been measured this way and must not inherit an MLB verdict
  silently. A test asserts an NFL prop is not swept up.
- **Family classifier is the SHARED one.** `market_family_of` delegates to
  `paper_settlement._market_family` rather than re-deriving. That module's own
  docstring records what a second definition costs. A test asserts the two
  agree.
- **Counted, not vanished.** `refusals_by_market` attributes each refusal to
  its market, and a test asserts the reasons still sum to `rows_in`.
- **Reversible with one env var**, and it is a POLICY DEFAULT, not a defect fix.

Tests: 9 new, plus two pre-existing tests in `test_portfolio_commit.py` pinned
policy-independent -- they used MLB prop rows as fixtures for the ATTRIBUTION
machinery and so silently depended on which families are excluded.
**Off-is-not-on verified: 4 of the 9 fail with the exclusion disabled**, and the
5 that assert the rule does NOT fire pass in both states, which is correct.

### WHAT THIS DOES *NOT* CLAIM

- It does not fix Book A. The calibration defect and the 993 zero-probability
  rows in section 7c are untouched and still real.
- It does not assert props are unprofitable in principle. Section 7b's
  arithmetic stands: the under book clears its hold and needs roughly a **+5.1%
  payout improvement** to reach +5% ROI, against a measured +10.61% dispersion
  on a panel that is **3 books deep with no exchange in it**. If the panel
  widens, this default should be re-measured, not assumed permanent.
- **It is UNDEPLOYED.** `commit_portfolio` runs on the worker; nothing changes
  in production until a deploy.

**Gate:** after deploy, `market_family_excluded` appears in the commit
refusals with a non-zero count and `player_prop` disappears from
`by_market_family` on new dates; then pooled ROI over the following ten days
measured against the +3.76% baseline that included props.

---

## 7e. ITEM 03 EXECUTED — the live grader settled from a running tally, and a green test held it in place

**Done 2026-08-31.** The mechanism is confirmed on production, not inferred,
and it is arithmetic rather than modelling.

### The confirmation

`/mlb/api/live-lens-accuracy` builds from `live_lens_daily_accuracy._registry_rows`.
For each entry it tries the raw statsapi feed first and **falls back to
`lastSeenSnapshot.actual` / `firstSeenSnapshot.actual`** — the stat SO FAR.

For a line of 0.5, an early tally of 0 grades every `over` a LOSS and every
`under` a WIN regardless of what happened afterwards. That is exactly the
production signature: **over 0 wins / 1,578, under 206 / 206** pooled over
2026-07-01..08-31.

**And the fallback was not an edge case. It was the only path that ever ran:**

| date | n | W | L | feedResolved | registryFallback |
|---|---|---|---|---|---|
| 2026-07-17 | 16 | 6 | 10 | **0** | 16 |
| 2026-07-18 | 89 | 13 | 76 | **0** | 89 |
| 2026-07-22 | 403 | 35 | 368 | **0** | 403 |
| 2026-07-28 | 359 | 25 | 334 | **0** | 359 |
| 2026-08-06 | 339 | 42 | 297 | **0** | 339 |
| 2026-08-09 | 261 | 26 | 235 | **0** | 261 |

**`feedResolved` is 0 on all 11 days that produced rows**, against
`feed_live_miss: 1,802`. **100% of everything this instrument ever graded came
from the in-progress branch.**

### Why it cannot be repaired by reading the snapshot more carefully

A snapshot is written by `cards._registry_live_prop_rows` and carries `actual`,
`actualSoFar`, `modelMean`, `liveProjection`, `liveEdge`, `odds` — and **no
game state**. In-progress and final are indistinguishable there. So the only
honest choice is to refuse both, which is what shipped.

### What shipped

The fallback no longer settles. It counts, under two new named signals:
`snapshotActualNotFinal` and the warning `snapshot_actual_not_final:N`.
`pending_actuals` still means something different and is kept separate — *"the
registry never carried a value"* and *"we have a tally and refuse to trust it"*
are opposite problems, and collapsing them would hide which one a day has.

The consequence is that **on production this instrument will now read EMPTY
rather than wrong**, which is the true state. An empty instrument is a visible
gap; a confident wrong one is not.

### THE STRUCTURAL BLOCKER, NAMED AND DELIBERATELY NOT FIXED

`_actual_from_feed` reads `raw_feed_live_path`, under
`data/raw/statsapi/feed_live/`. **That tree is not in
`HOT_ARTIFACT_PATTERNS`**, so it is never published to the web service that
serves this endpoint — which is why `feedResolved` is 0 and always has been.

Publishing per-game raw feeds has a real disk cost (the repo already carries a
207MB `book_quotes` shard as the cautionary case) and belongs to whoever owns
that budget. It is a separate decision and is left as one. **Until it is taken,
MLB live accuracy remains unmeasurable — which section 7 already said, and this
change makes the endpoint agree with it instead of contradicting it.**

Second, smaller reachability note, unfixed: `raw_feed_live_path` resolves
against `_artifact_roots()[0]` — the FIRST root only. Even with the tree
published, a bundle under a later root would not be found.

### A GREEN TEST WAS HOLDING THE BUG IN PLACE

`tests/test_live_lens_local.py::test_mlb_daily_accuracy_uses_local_registry_artifacts`
writes a registry with **no feed artifact** and asserted **`wins == 1,
losses == 1`** — outcomes reachable only by settling from a snapshot. It was
passing, and it encoded the defect as the expected contract.

Corrected to assert the true behaviour. Its stated subject — that the LOCAL
registry artifact is the one being read — is unchanged and still asserted by
`lines == 3`; what changed is that reading three entries no longer implies
grading them. Its sibling
`test_mlb_daily_accuracy_prefers_feed_live_actuals_over_registry_snapshots`
already guarantees the with-feed path and is untouched.

Tests: 8 new. **Off-is-not-on verified: 4 of the 8 fail when the old settling
branch is restored**, and the 4 that assert the with-feed path and the
pending/miss counters pass in both states, which is correct. A prior sweep of
the whole `live_lens` area returned 410 passed / 1 failed, that one failure
being the test above.

### CROSS-SPORT NOTE

The live lane `wnba-accuracy-assessment` (session e542848e) independently found
their live engine's **+41% ROI to be FICTIONAL** — 39.4% of signals priced
against the engine's own model line, `line_live_age_sec` null on 1,777 of
1,777. **Same instrument family, same class of defect, second sport.** Their
files are `syndicate/features/wnba/...` and `shared/live_lens_local.py`
(`_artifact_path` only); nothing here touches those. Worth treating as a
platform-level pattern rather than two coincidences.

---

## 7f. TIER 1 ITEM 06 — RESOLVED, and it RETRACTS section 7b's binding constraint

**Done 2026-09-01.** The contradiction was real and both halves were true; they
measured different things. **The conclusion I drew from one of them was wrong
and is withdrawn.**

### WHAT SECTION 7b SAID, AND WHY IT IS WRONG

> "Zero of the 103 MLB prop rows are quoted by Kalshi, Polymarket, Novig or
> ProphetX. The venues where the hold would actually collapse do not quote MLB
> player props on this board at all."

The number is correct. **The conclusion drawn from it is not.**

That count came from `quote.book_prices`, and `venue_scope.scope_rows_to_venue`
states in its own docstring what that field is:

> "the price is read from `quote.book_prices[venue]`, which is the AGGREGATOR's
> view — and **for these exchanges OddsAPI carries game lines only**, which is
> why every coverage number in this system was about OddsAPI rather than the
> venue."

So `0 of 103` never measured whether Kalshi quotes props. It measured whether
**OddsAPI reports Kalshi prop prices**, which it structurally does not, for any
exchange, ever.

### WHAT IS ACTUALLY TRUE — measured on the live order book

**23 filled Kalshi MLB player-prop orders**, carrying real Kalshi contract
tickers:

    KXMLBHR-26AUG311840SDCIN-SDTFRANCE4-1        batter_home_runs  over  @0.15
    KXMLBHIT-26AUG311940DETMIN-MINKCLEMENS2-1    batter_hits       under @0.37
    KXMLBTB-26AUG312140PHIAZ-AZTTAWA13-2         batter_total_bases over @0.30
    KXMLBHA-26AUG311940MILCHC-MILKHARRISON52-5   hits_allowed      over  @0.53

Distribution: `batter_hits` 8, `strikeouts` 6, `batter_total_bases` 2,
`hits_allowed` 2, `batter_home_runs` 2, `batter_rbis` 1, `earned_runs` 1,
`batter_hits_runs_rbis` 1. Plus `paper:kalshi/player_prop` carrying **207
settled rows** over 16 days (section 6).

**Kalshi quotes MLB player props, and we trade them.**

### THE REAL FINDING, WHICH IS SHARPER THAN THE ONE IT REPLACES

Not *"the exchanges have no prop liquidity"* but:

**THE BOARD CANNOT SEE EXCHANGE PROP PRICES, SO ITS PRICE SHOPPING NEVER
CONSIDERS THEM.**

The venue feeds exist and are already wired — but only into the *venue-scoped*
books, via `scope_rows_to_venue(..., price_resolver=...)`. The main board's
best-price selection reads `quote.book_prices`, which is aggregator-only. So
the +10.61% best-vs-median dispersion measured in section 7b was computed
across **sportsbooks alone**, with the exchange prices sitting one function
call away and never entering the comparison.

That is a visibility defect in the board, not an absence in the market — and it
is a much better target than "go find more books".

### THE PER-VENUE PICTURE, corrected

| venue | price source | can price a named prop? |
|---|---|---|
| **kalshi** | direct feed (`kalshi_markets.json`) | **yes — proven, 23 filled orders** |
| **polymarket** | direct feed (`_polymarket_price_resolver`) | yes |
| **novig** | aggregator only | **NO, structurally** |
| **prophetx** | aggregator only | not through the board |

**Two further corrections found while checking:**

1. `pipeline/portfolio_commit.py:815` comments *"Only Kalshi has a direct feed
   today"*. **Stale** — `_venue_price_resolver` dispatches to
   `_polymarket_price_resolver` as well. Polymarket has one too.
2. **Novig cannot ever price a named bet through its public mirror**, and this
   is documented rather than accidental: the CSV mirror is "anonymized at the
   game/player/team level (measured 2026-08-24), so `reportTicker` names a
   CATEGORY and can never price a named bet." Its credentialed REST tier could.
   So Novig is a hard ceiling, not a coverage gap to close by widening.

### WHAT THIS DOES TO ITEM 05

Section 7b priced the under book as needing **+5.1% payout for +5% ROI**
against a measured **+10.61%** dispersion, and called the panel — 3 books deep,
no exchange — the binding constraint. **The arithmetic stands; the constraint
was mis-identified.**

Item 05 is no longer "integrate more books". It is: **make the board's price
comparison read the venue feeds it already has.** The plumbing exists, it is
proven in production by filled orders, and it is currently confined to the
venue-scoped books.

**NOT YET MEASURED, and it is the next thing:** what the best-vs-median
dispersion becomes once exchange prop prices are in the comparison. Until that
number exists, the prop-viability case remains "arithmetically reachable" and
not "demonstrated" — the same standard section 7b set for itself.

**Also unchanged:** none of this argues for re-enabling prop staking. Item 01's
exclusion rests on the portfolio's own realized -19.27%, which is independent of
where the prices come from.

---

## 8. The plan, ranked by measured dollars per unit of work

Each item names the gate that decides whether it worked. Nothing here is
"believed"; each is a reading someone must take.

### Tier 0 — stop the bleeding (hours, no modelling)

1. **[SUPERSEDED BY SECTION 7d — SHIPPED, but as a FAMILY rule, not a SIDE
   rule. The side rule below describes the VENDOR CARD, which grep confirms is
   not a staking input; in the staked book the sides are indistinguishable
   (over 41.4% n=99, under 42.4% n=158) because the board carries no model view
   on prop rows. What shipped is `mlb:player_prop` excluded from
   `commit_portfolio`. Read 7d before acting on this paragraph.]**
   ~~Cut prop OVERS, home runs and hits+runs+RBIs; KEEP the under book on hits,
   total bases, runs and RBIs.~~ Overs are negative in all five price bands
   (-3.29 to -7.80pp) and in every market cell, so no filter rescues that side.
   The under book minus HR and HRR is **+0.65% ROI on 2,571 bets** over five
   months.
   *Gate:* over stake and HR/HRR stake at zero, then the surviving under book
   measured on its own over the next 500 graded rows against the +0.65% baseline.

1b. **Record BOTH sides' prices at selection time.** 0 of 8,778 keys carry both
   today. This unblocks the inversion test retroactively across 8,918 existing
   rows instead of waiting on 500 fresh ones.
   *Gate:* share of graded keys carrying both sides above 90% within one slate.

**REORDERING NOTE.** Item 9 (widen the book panel) moves from Tier 2 to Tier 1
and is renamed: it is no longer a general improvement, it is the PRECONDITION
for the surviving prop book existing at all. The under book needs a **+5.1%
payout improvement for +5% ROI**; measured prop-row dispersion is +10.61% median
but the panel is **3 books deep with no exchange in it**. Two items are added
alongside it: resolve the Kalshi prop contradiction (0 board rows quoted vs 207
settled), and gate prop markets on a measured entry bar of <= 3pp. Full ordered
list is in the artifact.

2. **Kill `/mlb/api/live-lens-accuracy` as a decision input, and fix its grader.**
   It reports 0-for-1,578 on overs and 206-for-206 on unders. Until the grader
   compares against a FINAL stat line rather than `actualSoFar`, every number it
   emits is an artefact.
   *Gate:* on a re-run over the same 61 days, `by_klass` over-hit and under-hit
   must both land strictly inside (0%, 100%). Anything at a boundary means it is
   still reading in-progress state.

3. **Fix the Polymarket stake/PnL denominator.** `roi_pct` of -141% and -159%
   on binary contracts is arithmetically impossible; fees or contract cost are
   outside `staked_dollars`. Every venue-level ROI comparison is wrong by that
   amount until it is fixed.
   *Gate:* no `by_venue_family` row reports `roi_pct < -100`.

### Tier 1 — the strategic correction (days)

4. **Retire `model_edge_pct` as a staking signal; keep the sim as a
   *feature*, not an *estimator*.** Measured: `corr(claimed edge, win) =
   -0.1379`. The sim probability itself is informative (+0.2344) and the market
   is more so (+0.3184). The correct combination is not a difference, it is a
   **fitted blend** — logistic regression of the outcome on
   `logit(market_devig)` and `logit(sim)`, refit weekly.
   *Gate:* out-of-sample Brier of the fitted blend must beat market-alone
   (0.22663) on a held-out fortnight. If the fitted sim weight is not
   significantly different from zero, the honest answer is to drop the sim from
   pricing entirely and say so.

5. **Invert or gate the prop side selection.** The HR cell is the proof:
   over picks homer 10.96%, under picks 21.24%, base rate 12.13%, z = -4.12.
   That is real signal pointed the wrong way. Two candidate causes, and they are
   distinguishable in one afternoon: (a) a **sign error** in the prop
   over/under comparator, (b) the projection is right and the *selection rule*
   takes the side with the worse price. Check (a) first — it is one comparator
   and it would explain all six cells at once.
   *Gate:* re-run the same controlled (market, line) discrimination table on
   the next 500 graded rows. Every cell must flip to a positive diff.

6. **Fit the moneyline recalibration the calibration table already asks for.**
   The sim is unbiased in aggregate but the buckets are not monotone
   (0.42-0.46 predicts 0.442 and delivers 0.341; 0.58-0.65 predicts 0.608 and
   delivers 0.521). A single Platt scaling on 482 games will not fix
   discrimination (AUC 0.590 is the ceiling) but it removes the bucket errors
   that the edge calculation amplifies.
   *Gate:* bucket errors all within +/-0.05 on a held-out month.

### Tier 2 — where the money actually is: price dispersion, Kalshi and Polymarket (weeks)

7. **Double down on price shopping; it is the only thing measurably winning.**
   game_line +15.55% and game_total +6.65% while props lose; polymarket and
   kalshi game_line paper books at +40.89% and +30.82%. Best-vs-median payout
   dispersion is **+9.45% median** on MLB rows. This edge is mechanical and does
   not depend on the sim being right.
   *Gate:* the profitable half must survive real-money settlement, not
   `settled_by = inferred`. That is item 8.

8. **Close the paper-vs-real-money gap before scaling stake — this is the
   single biggest risk in the whole assessment.** Paper says +3.76%; the only
   real-money readings available are -5.5% (239 settled, prior lane) and -78.6%
   (14 settled, today). The candidate causes are fill quality, fees, and
   selection (paper takes prices real orders never get). None is measured.
   *Gate:* a controlled join — for every real order, the paper book's price for
   the same `position_key` at the same instant. Report the mean slippage in
   basis points. Do not raise stake until that number exists.

9. **Widen the book panel.** Median **5 books quoting per row**, p10 = 3. Price
   shopping is a max over a sample; a 5-book max leaves most of the dispersion
   unseen. The shortlist already sees up to 37 books on some rows, so this is a
   coverage problem, not an integration one.
   *Gate:* median books-per-row above 10, and the best-vs-median payout gap
   re-measured on the wider panel.

10. **Restore the ignored `date` param on `/api/portfolio/live`.** Without it,
    real-money performance cannot be tracked over time by anyone, which is why
    item 8 currently rests on 14 settled orders.
    *Gate:* `?date=2026-08-29` returns 2026-08-29.

### Tier 3 — only after tiers 0-2 have readings

11. **Rebuild game-total discrimination or stop pricing totals.**
    `corr(sim mean, actual) = 0.169` and `corr(sim prob, win) = +0.0331` — the
    run engine has *calibration without information*. The distribution shape is
    already right (PIT uniform, dispersion 4.821 vs 4.717 needed), so the work
    is entirely in the conditional mean: lineups, bullpen state, park, weather.
    *Gate:* correlation above 0.30 on a held-out month, else drop model totals
    and price them on market-fair alone.

12. **Make live measurable at all.** 140 of 200 MLB board rows are live, the
    live grader is broken, and no live row carries a model number. Until a live
    projection is both produced and correctly graded, live MLB is an unmeasured
    surface carrying most of the board's volume.
    *Gate:* a live accuracy table with n, a window, and both hit rates strictly
    inside (0%, 100%).

---

## 9. Reproduction

Scratchpad scripts (read-only, production HTTP only), this session:
`flat.py` (cards to `games_flat.json`), `calib2.py` (sections 2 and 4),
`totals.py` (run-total PIT and totals backtest), plus inline analyses over
`/mlb/api/market-accuracy?since=2026-04-01&until=2026-08-31` (section 3) and 16
`/api/portfolio/paper?date=` payloads (section 6). 75 dates of
`/mlb/api/cards?date=` were pulled, 2026-06-17..2026-08-30.
