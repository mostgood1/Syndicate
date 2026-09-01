# FINDINGS — WNBA accuracy and profitability, full assessment

**Session** `e542848e-6451-41a1-9e60-fd5a5675665d`, lane `wnba-accuracy-assessment`.
**Date** 2026-08-31.

Every number is measured, and carries its n and window. Production numbers are
read off `https://syndicate-an21.onrender.com`. Because **every WNBA accuracy
instrument on production reads zero** (section 1), the accuracy numbers here are
graded against ground truth I built myself from ESPN — 306 completed WNBA games
and 4,652 player-game stat lines — not off any Syndicate grader. Where a
conclusion is an inference it says so.

Requested window was 14 days. The 14-day sample is 39 games, so the assessment
runs the **full 2026 season** and reports the 14-day window as a sub-slice.

---

## 0. The headline, in one paragraph

The WNBA **moneyline sim is the best pregame asset this platform has** — AUC
**0.7631** over 106 games, Brier skill **+16.5%**, and **+34.5% / AUC 0.8413**
over the last 14 days. Almost nothing downstream uses it. The board issued
**2 moneyline recommendations all season out of 466**, spending its volume
instead on spreads and totals, which lose (**-9.68% ROI**, n=105). Every
confidence field in the system is not merely miscalibrated but **anti-informative**:
`corr(claimed prop edge, win) = +0.0002` (n=656), and the board's `p_win` is
overstated by **25.58pp**. The live engine's apparent **+41% ROI is fictional** —
39.4% of its signals are priced against **its own model's line**, no live market
line has ever been captured (`line_live_age_sec` null on 1,777/1,777), and its
hit rate climbs 55.9% → 88.0% from Q1 to Q4 against a stale pregame line. And a
**third of the season's graded history is served from a vendor artifact root
whose market lines correlate -0.04 with the games they are attached to** — any
backtest that reads the archive without splitting on that root will conclude the
sim is broken. Mine did, on the first pass.

**The season is on the FIBA World Cup break. There are no games until
2026-09-17, then 30 games in 9 days, then playoffs.** That is a 17-day runway
in which nothing can be lost by fixing this.

---

## 1. Instrument state — every WNBA accuracy instrument reads zero

| instrument | verdict |
|---|---|
| `/wnba/api/market-accuracy` | **EMPTY.** `available: false` on all 30 days sampled. `/api/ops/wnba/artifact-counts` reports `games.gradeable: false` and `props.gradeable: false` on **30 of 30 days**. |
| `/wnba/api/live-lens-accuracy` | **EMPTY.** `signals.exists: false`, `n: 0`. |
| `/wnba/api/live-game-lens-accuracy` | **EMPTY.** `exists: false` on every day 08-18..08-30. |
| `/wnba/api/live-player-props-lens-accuracy` | **EMPTY.** "No settled BET player-prop rows". |
| `/wnba/api/live-player-props-audit` | **EMPTY.** `raw_rows: 0, settled_rows: 0`. |
| `/api/ops/clv/report?sport=wnba` | **EMPTY.** `resolved: 0`, `openings: 0`, `avg_clv_pct: null`. WNBA CLV has never been measured. |
| `/wnba/api/cards?date=` (past dates) | **NEVER MARKS A GAME FINAL.** All 213 cards across 93 dates read `status: "Scheduled"`, `final: false` — including May. MLB's equivalent endpoint does carry finals. A WNBA result can therefore never be reconciled on the card surface. |

### 1a. Three root causes, all located

**(i) The live-lens readers look in the wrong directory.** The endpoints report
reading `…/wnba_source/source_artifacts/data/`**`processed`**`/live_lens_signals_<date>.jsonl`.
The files exist and are substantial, in `…/data/`**`live_lens`**`/`:

| | |
|---|---|
| dates with >10KB of live signals | **34 consecutive**, 2026-07-28..2026-08-30 |
| size range | 106KB – 1.23MB per day |
| what the reader sees | `exists: false`, every day |

The live sim has been running and emitting a quarter-megabyte of signal a day
for five weeks. Nothing reads it. This is a directory-name mismatch, not a
missing producer.

**(ii) `recon_games_*.csv` is written pregame and never rewritten.** Only **4
exist in all of production** (05-27, 05-28, 06-21, 06-23), and in every one the
outcome columns — `home_pts`, `visitor_pts`, `actual_margin`, `total_actual`,
`margin_error`, `total_error` — are **empty strings**. The file carries
`pred_margin` and nothing to compare it against. `recon_props_*.csv` covers
33 dates, all 05-20..06-26; dead since June.

**(iii) The boxscore producer died on 2026-08-26.** `boxscores_*.csv` runs
2023-05-05..**2026-08-25** and stops. `boxscores_present` is `true` on 25 of the
last 30 days and **false on 08-26..08-30** — the five most recent playing days.

### 1b. The card payload's prices are arithmetically impossible

Of 128 priced fields carried in card `betting` blocks, **55 (43.0%) are strictly
between -100 and +100** — not a valid American price: `-89.125`, `-94.375`,
`-62.25`, `-59.14`. This is the signature of **averaging American odds
arithmetically across books**, which is invalid across the ±100 discontinuity;
implied probabilities must be averaged instead. Any EV computed off this field
is wrong.

---

## 2. Slate coverage — 69.3% for the season, but 100% for the last 14 days

Completed WNBA games (Central-dated) 2026-05-17..2026-08-30, against cards:

| window | carded / played | |
|---|---|---|
| full window | **192 / 277** | 69.3% |
| last 60 days | 114 / 156 | 73.1% |
| last 30 days | 62 / 85 | 72.9% |
| **last 14 days** | **39 / 39** | **100%** |

85 games were never carded: **31 on 11 days with zero coverage** (05-20, 05-23,
06-08, 06-19, 06-20, 06-23, 06-24, 06-25, 06-28, 06-30, 07-02) and **54 on 32
partially-covered days**. The gap is historical and concentrated in June/July.
**Coverage is currently healthy** — do not fix a problem that has already closed;
do treat the June/July archive as holed when backtesting.

---

## 3. The vendor artifact root is unusable, and it is 43% of the graded history

`/wnba/api/cards` serves from two roots depending on which file happens to exist
(`#309` resolves per requested file):

- `wnba_source/data/processed/` — **Syndicate-owned**
- `wnba_source/source_artifacts/…` — **vendor bundle**

Split the same measurement on that one variable:

| | n | Brier skill | AUC | favourite acc | residual SD | total bias | corr(**market** line, actual) |
|---|---|---|---|---|---|---|---|
| **Syndicate root** | 106 | **+16.53%** | **0.7631** | 67.0% | 12.8 | +2.24 | **+0.6785** |
| **vendor root** | 79 | **-72.36%** | **0.4018** | 41.8% | 24.6 | +21.46 | **-0.0396** |

**Controlled on the month.** July carries both roots: Syndicate July AUC
**0.905** (n=26), vendor July AUC **0.292** (n=23). Same league, same month, same
join method — the only variable is the root.

**It is not a side flip and not a bad join.** Flipping `p_home → 1-p_home` on the
vendor root only reaches AUC 0.598 and Brier skill -30.6%, so it is not
inverted; and the join is sound (every fallback match is the same team pair on
the same day, differing only in scheduled-vs-actual tip time by a few minutes).
The decisive number is the last column: **on the vendor root the market line
itself carries no information about the game it is attached to** (r = -0.0396,
versus +0.6785 on the clean root). Those rows are mis-joined at source.

Corroborating: impossible lines are concentrated there — **|spread| > 20.5 on
9.2%** of rows (max **55.0**), **totals outside 145–200 on 11.9%** (max **253.0**).
WNBA spreads do not reach 55 and totals do not reach 253.

> **This is the single most expensive trap in the WNBA data.** Read the archive
> without splitting on `source_path` and the sim measures at Brier skill
> **-21.5%**, AUC 0.595 — "worse than climatology". Split it and the same sim is
> **+16.5%**, AUC 0.763. The first pass of this assessment reported the former.

Everything below uses the **Syndicate root only**.

---

## 4. Pregame sim, GAME markets — the moneyline is genuinely good

n = **106** finals, 2026-05-17..2026-08-30.

### Moneyline — the asset

| | value |
|---|---|
| mean sim `p_home` | 0.5245 vs actual 0.5566 — bias **-3.22pp** |
| Brier | **0.20599** vs climatology 0.24680 — skill **+16.53%** |
| LogLoss | 0.61126 vs 0.68673 |
| **AUC** | **0.7631** |
| favourite accuracy | **66.98%** |

**By window** (all clean-root):

| window | n | Brier skill | AUC | accuracy |
|---|---|---|---|---|
| **last 14 days** | **39** | **+34.50%** | **0.8413** | **76.92%** |
| last 21 days | 50 | +34.02% | 0.8374 | 76.00% |
| last 30 days | 62 | +24.14% | 0.7937 | 69.35% |
| last 45 days | 87 | +28.45% | 0.8222 | 71.26% |

**Overconfidence is REAL POOLED and ALREADY GONE IN THE CURRENT DATA — do not
blanket-rescale.** The win probability is generated analytically from the
projected margin. Comparing the dispersion it assumes against the dispersion it
actually needs, by period (clean root):

| window | n | implied margin SD | actual residual SD | ratio |
|---|---|---|---|---|
| May–Jun | 18 | 10.61 | 17.04 | **1.61** |
| Jul | 26 | 11.12 | 12.82 | 1.15 |
| Aug | 62 | 10.88 | 11.25 | 1.03 |
| **last 14 days** | **39** | **11.39** | **11.57** | **1.02** |
| pooled | 106 | 10.87 | 12.81 | 1.18 |

The pooled 1.18× overconfidence is **entirely a legacy of the early season**. On
current data the mapping is essentially exact.

I tested the obvious fix and it fails. Fitting a single sigma on the first
two-thirds by date (n=70, → sigma 24.00) and testing on the last third (n=36)
gives **test Brier skill +35.43% against the shipped +39.56%** — the refit is
*worse* out of sample, because a sigma fit on stale, badly-calibrated games
over-widens for a period that no longer needs it. In-sample the same refit looks
like a +5pp win. **It is not one; do not ship it.**

What the table does justify is an **adaptive** sigma — a trailing-window
residual SD rather than a constant — because the failure mode it protects
against is exactly the one that recurs on **2026-09-17**: a restart after a
three-week break, with stale priors and roster churn, which is the same
condition that produced ratio 1.61 in May.

**High-confidence moneyline picks are the real product.** Straight-up accuracy
by the sim's own confidence, clean root:

| confidence band | n | straight-up accuracy |
|---|---|---|
| 0.5–0.6 | 18 | 44.4% |
| 0.6–0.7 | 17 | 52.9% |
| 0.7–0.8 | 16 | 68.8% |
| 0.8–0.9 | 26 | 65.4% |
| **0.9–1.0** | **29** | **89.7%** |

### Spread — weakly informative, not proven

n = 101 (implausible lines excluded). `p_cover` bias **-6.55pp**, Brier skill
**-15.67%**, **AUC 0.5431**. Side selection at flat -110 goes **55-46 = +3.96%**,
which is **+0.42 SE above breakeven — not significant**.

### Totals — the sim loses here

n = 102. Sim bias +1.77 pts (fine); **MAE 14.23 vs the market's 11.87**;
**corr 0.419 vs the market's 0.581**. The sim is a strictly worse total estimator
than the line it is betting into. Side selection at flat -110: **47-54,
ROI -11.16%**; the OVER subset is **-15.50%**. `p_over` leans over by **+8.08pp**.

### Margin

corr(sim projected margin, actual) **+0.5222** vs the market's **+0.6785**.
MAE 14.42 vs 12.00.

---

## 5. Layer 1 board — it bets the two markets that lose and skips the one that wins

466 recommendations across the season; 105 game-line rows on the clean root are
gradeable with a valid price.

| slice | n | record | hit | implied | ROI | claimed EV |
|---|---|---|---|---|---|---|
| **all game lines** | **105** | 50-55 | **47.62%** | 52.65% | **-9.68%** | +22.7% |
| ATS | 51 | 24-27 | 47.06% | 52.56% | -10.61% | +26.1% |
| TOTAL | 54 | 26-28 | 48.15% | 52.73% | -8.80% | +19.4% |
| ML | **0** | — | — | — | — | — |

**`p_win` is overstated by 25.58pp** — the board claims **73.20%** and delivers
**47.62%**.

**Its own EV does not rank its own bets.** `corr(claimed EV%, win) = +0.0466`;
`corr(claimed p_win, win) = +0.0147`. By EV quartile:

| quartile | EV range | n | hit | ROI |
|---|---|---|---|---|
| Q1 lowest | -4.9 .. +5.3 | 26 | 57.7% | **+9.47%** |
| Q2 | +5.5 .. +16.8 | 26 | 42.3% | -19.97% |
| Q3 | +16.8 .. +31.2 | 26 | 38.5% | -27.07% |
| Q4 highest | +32.6 .. +72.7 | 27 | 51.9% | -1.46% |

Non-monotone. The cheapest quartile is the best one.

**Structural findings:**
- **2 moneyline recommendations all season, of 466** (`PROPS` 277, `ATS` 85,
  `TOTAL` 85, `PROP` 17, `ML` 2). The board's best-measured market is the one it
  does not bet.
- **All 466 rows carry `card_bucket: "playable"`.** There is no tiering — no
  `official` / `candidate` split as MLB has.
- **`stake_units` is null on all 466.** No sizing exists.
- **36 recommendations claim `p_win = 1.000`**; max claimed EV **2264.8%**.

**Board enrichment coverage.** Over 13 playing days, `/api/board/layer1?sport=wnba`
returns 522–1,276 rows/day, of which `rows_modelled_fair` is **20–56**, i.e.
**~4–6%**. **94–96% of the WNBA Layer 1 board carries no model fair value at
all** — for those rows it is a pure price-shopping board.

**No exchange prices on the board.** Best-price books across a full day's 1,115
rows: draftkings, fanduel, betrivers, fanatics, betmgm, betonlineag,
williamhill_us, bovada, mybookieag, betus. **Kalshi and Polymarket appear zero
times** — while real money is executed on exactly those two venues (section 9).
The surface that chooses the bet never sees the price the bet is filled at.

---

## 6. Layer 2 board — WNBA is excluded upstream

`/api/board/layer2-shortlist` returns **0 WNBA rows on 13 of 14 days**. The one
exception is 2026-08-29: 8 rows, all `game`, **0 `prop`**.

The reason is not a value floor. On 2026-08-30 the shortlist reports
**`active_sports: ['ncaaf', 'soccer']`** — WNBA is not a considered sport at all.
Of 7,724 opportunities considered, ncaaf took 322 and soccer 400 against a
`per_sport_limit` of 400; WNBA has no `per_sport` entry.

So the whole Layer 2 ranking, sizing and settlement path — the one the ledger
notes call the only surface that *can* be settled, because it persists what it
recommended — **has essentially never seen WNBA**.

---

## 7. Pregame player props — break-even, and the confidence signal is noise

1,538 recommendations; **656 graded on the clean root** (1,374 across both roots).
Grading is against final ESPN boxscores; DNPs and pushes are excluded, not
scored as losses.

| | n | record | hit | implied | gap | ROI |
|---|---|---|---|---|---|---|
| **clean root, all** | **656** | 354-302 | **53.96%** | 52.17% | **+1.80pp** | **+3.32%** |
| OVER | 225 | 120-105 | 53.33% | 51.18% | +2.16pp | +4.24% |
| UNDER | 431 | 234-197 | 54.29% | 52.68% | +1.61pp | +2.85% |
| vendor root | 718 | 360-358 | 50.14% | 52.51% | -2.37pp | -4.91% |

**+1.80pp is +0.92 SE. ROI +3.32% ± 3.75pp. Neither is significant.** The honest
verdict is *break-even, possibly slightly positive* — not a proven edge. Unlike
MLB, the side selection is **not** inverted: only one (market, line) cell had
enough volume to test, and it came out correct.

**The confidence fields carry no information — this is the finding.**

| field | corr with win | n |
|---|---|---|
| claimed `p_win` | **-0.0552** | 516 |
| claimed `ev_pct` | **-0.0157** | 656 |
| `edge` | **+0.0002** | 656 |

Calibration of `p_win`:

| claimed band | n | claimed | realized | ROI |
|---|---|---|---|---|
| 0.4–0.6 | 119 | 0.558 | **0.563** | **+12.68%** |
| 0.6–0.8 | 261 | 0.658 | 0.521 | -1.20% |
| 0.8–1.0 | **136** | **0.910** | **0.507** | -3.00% |

The only calibrated band is the least confident one, and it is the only
profitable one. The model's `tier` label reproduces the inversion exactly:

| tier | n | hit | ROI | claimed p_win |
|---|---|---|---|---|
| **High** | **382** | **50.79%** | **-1.61%** | 74.6% |
| Medium | 85 | 61.18% | +15.72% | 59.2% |
| Low | 49 | 53.06% | +1.38% | 54.7% |
| (unlabelled) | 140 | 58.57% | +9.94% | — |

By market (clean root, all underpowered individually — treat as hypotheses):
`ast` +27.09% (n=50), `pr` +12.65% (n=130), `pts` +3.57% (n=109), `ra` +4.06%
(n=64), `threes` +1.28% (n=123), `reb` -0.56% (n=89), **`pa` -17.31% (n=91)**.

---

## 8. Live sim — the reported edge is an artefact; one honest cell survives

1,689 gradeable live player-prop signals, 2026-08-17..2026-08-30, graded against
final boxscores.

**Taken at face value the live engine looks extraordinary: 1249-440,
hit 73.95%, ROI +41.18% at -110.** It is not real. Three independent proofs:

**(i) There is no live line.** `line_live_age_sec`, `line_live_span` and
`line_live_n` are **null on 1,777 of 1,777** player-prop signals. The engine has
never seen a live market price.

**(ii) 39.4% of signals are priced against the model's own line.**
`line_source` = `oddsapi` 944, **`model` 701**, `pregame` 132.

| line source | n | hit | ROI@-110 |
|---|---|---|---|
| `oddsapi` (real market) | 920 | 61.63% | +17.66% |
| **`model` (its own line)** | **637** | **91.21%** | +74.13% |
| `pregame` | 132 | 76.52% | +46.07% |

**(iii) The hit rate tracks the clock, which is what leakage looks like.**
Restricted to real `oddsapi` lines:

| period | n | hit | ROI@-110 |
|---|---|---|---|
| Q1 | 537 | **55.87%** | +6.65% |
| Q2 | 205 | 60.00% | +14.55% |
| Q3 | 103 | 75.73% | +44.57% |
| Q4 | 75 | **88.00%** | +68.00% |

On `model` lines the same walk ends at **99.17% in Q4**. A full-game prop line
from before tip is not purchasable in Q4; "beating" it once the player has
already cleared it is bookkeeping, not alpha.

**The one honest cell: Q1 + a real market line — n=537, hit 55.87%, ROI +6.65%.**
Breakeven is 52.38%; that is **+1.62 SE**. Suggestive, **not significant**, and
still measured against a pregame line that may have moved before Q1 ended.

**Other live findings:**
- `win_prob` claims **0.6693**, realizes **0.5684** — overstated **10.09pp**.
- Projections are biased low (→ a structural UNDER lean; sides run 1,058 UNDER
  vs 744 OVER). Q1: `sim_mu` bias **-2.240**, `pace_proj` bias **-1.098**.
- **A better estimator is already in the record and unused for side choice.**
  Pooled, `corr(pace_proj, final) = +0.7493` vs `corr(sim_mu, final) = +0.5611`.
  On the honest cell, side selection by `pace_proj` **56.84%** vs `sim_mu`
  **54.72%** (n=519). In Q1 `sim_mu` is the better *point* estimate
  (MAE 6.636 vs 7.453) while `pace_proj` picks the better *side* — they carry
  different information and neither is being combined.
- **All 1,814 signals are `klass: BET`.** No tiering, no abstention.
- 38% of signals fire in Q1, when the projection is weakest.

---

## 9. Real money — WNBA is the only sport in the black, on a sample too small to bank

All-time, `/api/portfolio/live` → `periods.by_sport`:

| sport | orders | settled | staked | PnL | ROI | win% |
|---|---|---|---|---|---|---|
| **wnba** | 32 | 31 | **$124.96** | **+$4.09** | **+3.31%** | 45.16% |
| mlb | 229 | 205 | $636.97 | -$78.20 | -13.39% | 39.02% |
| nfl | 19 | 18 | $72.32 | -$2.87 | -4.06% | 50.00% |
| soccer | 17 | 10 | $72.58 | -$20.05 | -46.87% | 50.00% |

WNBA by venue: **Kalshi 29 orders, $112.82 staked, -$3.48**; **Polymarket 3
orders, $12.14 staked, +$7.57**. Settlement is no longer wins-only — 14 won and
17 lost are both recorded, so the defect the ledger notes flagged is closed.

**n = 31 settled on $125. This is noise.** A 45.16% win rate with a positive ROI
means the book is on plus-money underdogs, which is consistent with the sim's
one real strength (moneyline discrimination) — but it cannot be claimed as
evidence. Basketball prop markets in the book are smaller still:
`player_rebounds` 7 orders +46.79%, `player_threes` 10 orders -31.33%,
`player_points` 6 orders -31.33%, `player_assists` 3 orders -4.49%.

**WNBA CLV has never been measured** (section 1). Given the season break, the
WNBA quote shard is legitimately absent right now (`status: unknown`, "no quote
shard for this sport and date") — that is the schedule, not a defect.

---

## 10. Schedule — the runway

ESPN shows **no WNBA games 2026-08-31 through 2026-09-16** (FIBA World Cup
break), then:

| dates | games |
|---|---|
| 2026-09-17 .. 2026-09-25 | **30 games in 9 days** |
| after | playoffs (season ends 2026-10-20) |

Everything in the plan can be built, deployed and verified before a single
further bet is placed.

---

## 11. Method and reproducibility

- `scripts/assess_wnba_accuracy.py` — the loaders, join and statistics used here.
  Read-only; touches no production code or `data/`.
- Ground truth: ESPN `scoreboard` (2026-05-01..2026-09-02) and `summary`
  (192 event ids). 306 completed WNBA games; the All-Star exhibition teams
  (`COOP`, `NIGER`, `SPO`) are excluded by name.
- Join: card `startTime` to the minute + team pair, falling back to same UTC day
  + team pair; deduplicated to the card whose own date matches the game's
  Central date. **74 of 266 matches used the fallback and every one is the same
  team pair on the same day** (scheduled-vs-actual tip drift of 2–14 minutes),
  and the fallback rate is the same on both artifact roots (SYND 48/107,
  VENDOR 26/85), so it cannot explain the root split in section 3.
- Prices strictly between -100 and +100 are **rejected, never coerced** (section
  1b), which is why priced-row counts are smaller than graded-row counts.
- Pushes and DNPs are excluded from prop grading rather than scored as losses.

---

# THE PLAN

Ordered by expected value per unit of work, not by area. Every item names the
measurement that closes it. **Nothing here needs a bet placed to be verified** —
the break runs to 2026-09-16.

The organising fact: **this platform has one proven WNBA edge (moneyline
discrimination, AUC 0.7631) and it is the one thing the board never bets and
Layer 2 never sees. Everything else it does bet is measurably negative or
unproven.** The plan is mostly about connecting an asset that already exists to
the surfaces that already execute.

---

## Tier 0 — stop the measured losses (before 2026-09-17)

**T0-1. Route WNBA game-market volume to the moneyline.**
The board issued **2 ML recommendations out of 466** while spending 170 on ATS
and TOTAL, which returned **-10.61%** and **-8.80%**. The sim's ML is
**AUC 0.7631 / 89.7% straight-up in its top confidence band**; its totals
estimator is **strictly worse than the line** (MAE 14.23 vs 11.87, corr 0.419 vs
0.581).
*Verify:* ML recommendations > 0 per slate; over 09-17..09-25 measure ML hit rate
against de-vigged implied, with n stated.

**T0-2. Stop recommending WNBA totals until the estimator beats the line.**
Not a tuning problem — the sim is a worse total predictor than the market on
every metric. Withhold rather than de-weight.
*Verify:* zero TOTAL rows in the WNBA recommendation set; the totals estimator
re-admitted only on a held-out `corr(sim total, actual) > corr(market, actual)`.

**T0-3. Never emit a live BET whose `line_source == "model"`.**
**701 of 1,777** live signals are priced against a line the model itself
produced, and they "hit" **91.21%** (99.17% in Q4). This is self-grading, and it
is the single largest contributor to the fictitious +41% live ROI.
*Verify:* `line_source` distribution on the next live slate contains no `model`
rows in `klass: BET`.

**T0-4. Reject impossible American prices at the boundary, don't average them.**
**43.0% of priced card fields** are strictly between -100 and +100. Average
implied probabilities across books, then convert back once. Add a hard guard
that refuses `-100 < odds < 100`.
*Verify:* zero card price fields inside (-100, +100) on a live slate.

**T0-5. Quarantine the vendor artifact root from every evaluation path.**
`source_artifacts` rows have `corr(market line, actual) = -0.0396`. Any
calibration, backtest or promotion decision that reads them is fitting noise.
Stamp `source_path` onto every row a consumer reads and exclude it; add a
plausibility guard (`|spread| <= 20.5`, `145 <= total <= 200`) as a second net.
*Verify:* re-run section 3 — the fitted sample contains zero `source_artifacts`
rows, and the excluded count is reported rather than silent.

---

## Tier 1 — restore measurement (this is why none of Tier 0 was known)

Everything in Tier 0 was invisible for a season because all six instruments read
zero. These are cheap and they backfill.

**T1-1. Point the live-lens readers at `data/live_lens/`, not `data/processed/`.**
**34 consecutive days** of live signals (106KB–1.23MB/day) already sit on the
Render disk unread. This is a directory-name fix and it makes five weeks of live
history measurable **immediately, retroactively** — no waiting for new games.
*Verify:* `/wnba/api/live-lens-accuracy?date=2026-08-30` returns `n > 0`; its
pooled hit rate reconciles with the 1,689 signals graded in section 8.

**T1-2. Make `recon_games` a post-game writer.**
It writes `pred_margin` pregame and never returns; `home_pts`, `actual_margin`,
`total_actual`, `margin_error` are empty in every one of the 4 files that exist.
*Verify:* `recon_games_<date>.csv` for a played date has non-empty
`actual_margin` on every row; `artifact-counts` flips `games.gradeable` to true.

**T1-3. Restart the boxscore producer.** `boxscores_*.csv` stops at
**2026-08-25**. `scripts/build_wnba_boxscores.py` is the Syndicate-owned
replacement and it exists.
*Verify:* `boxscores_present: true` for 08-26..08-30 after a backfill, and for
each new date within 24h.

**T1-4. Make cards mark finals.** All **213 of 213** past cards read
`status: "Scheduled"`. Nothing downstream can reconcile a WNBA result.
*Verify:* `/wnba/api/cards?date=2026-08-30` shows `final: true` with scores.

**T1-5. Turn on WNBA CLV.** `resolved: 0`, `openings: 0` — it has never been
measured, and CLV is the only profitability signal that gives an answer before
the sample is large enough to trust ROI. Given n=31 lifetime settled WNBA
orders, **CLV is the metric that will actually decide things this season.**
*Verify:* `/api/ops/clv/report?sport=wnba` returns `resolved > 0` and a
`same_book` `avg_clv_pct` after the first slate back.

---

## Tier 2 — make the confidence fields mean something

The recurring defect, in four places at once: **the system's stated confidence is
uncorrelated with being right, and is used to rank and to size.**

| surface | claimed | realized | correlation with outcome |
|---|---|---|---|
| board game lines `p_win` | 73.20% | 47.62% | +0.0147 |
| prop `p_win` | 70.2% | 53.96% | -0.0552 |
| prop `edge` | — | — | **+0.0002** |
| live `win_prob` | 66.93% | 56.84% | — |

**T2-1. Demote `ev_pct` / `p_win` / `edge` from ranking keys until each one
passes a held-out `corr > 0` test.** Rank by something measured. A field with
r = +0.0002 is a random number with a confident name; the ordering it produces
is the reason the *lowest*-EV quartile is the profitable one.
*Verify:* out-of-sample `corr(ranking key, outcome) > 0` at n >= 200 before it
ranks anything.

**T2-2. Fix or invert the prop tier.** `tier: High` (n=382) returns **-1.61%**
and hits 50.79%; `Medium` (n=85) returns **+15.72%**. The single calibrated band
is `p_win` 0.4–0.6 (claimed 0.558, realized 0.563, **+12.68%**, n=119).
Cheapest correct action: **bet only the calibrated band** while the tier model is
re-fitted.
*Verify:* re-measure by tier over the September slate; ship the tier back only
when `High` >= `Medium`.

**T2-3. Cap the arithmetic.** 36 recommendations claim `p_win = 1.000` and one
claims **EV 2264.8%**. A pregame WNBA bet is never certain. Clamp, and treat any
row that would have exceeded the clamp as a defect signal, logged.
*Verify:* zero rows with `p_win >= 0.999` or `ev_pct > 100` on a live slate.

**T2-4. Give WNBA a tier and a size.** All 466 recommendations are
`card_bucket: "playable"` and **`stake_units` is null on all of them**; all 1,814
live signals are `klass: BET`. There is no abstention anywhere in the WNBA path.
MLB's `official` / `candidate` split is the reference.

---

## Tier 3 — Kalshi and Polymarket (the profitability core)

**This is where the asset and the venue actually line up, and nothing connects
them.** The sim's one proven edge is a **winner-market** edge; Kalshi and
Polymarket are **winner-market venues**; and real WNBA money is already
executed on exactly those two.

**T3-1. Get exchange quotes onto the Layer 1 board.**
Across a full day's **1,115 WNBA board rows** the best-price books are
draftkings, fanduel, betrivers, fanatics, betmgm, betonlineag, williamhill_us,
bovada, mybookieag, betus — **Kalshi and Polymarket appear zero times**, while
29 Kalshi and 3 Polymarket WNBA orders have been filled. The surface that picks
the bet cannot see the price the bet is filled at, so no edge it computes is the
edge that gets traded.
*Verify:* WNBA board rows carry a kalshi and/or polymarket quote; count and
median age reported per slate.

**T3-2. Admit WNBA to Layer 2.**
`active_sports: ['ncaaf', 'soccer']` — WNBA is excluded upstream, not filtered on
value. It has produced shortlist rows on **1 of 14 days** (8 rows, 0 props).
Layer 2 is the only surface that persists what it recommended and can therefore
be settled; WNBA has essentially never been in it, which is a second, independent
reason WNBA profitability is unmeasurable.
*Verify:* `per_sport.wnba` present with `selected > 0` on a WNBA slate; those
rows settle.

**T3-3. Confirm the WNBA series join on both venues before the restart.**
The ledger records that `series_matching` is a substring match and **`NBA` sits
inside `WNBA`**, so NBA's ticker count subsumed WNBA's. I did **not** re-verify
that in this pass — the season break leaves no WNBA quote shard to read
(`status: unknown`, correctly). Re-check it on 09-17, because a substring
collision here silently routes WNBA orders against NBA markets.
*Verify:* WNBA-tickered quotes counted independently of NBA on a live slate.

**T3-4. Size on CLV, not on ROI, until n is real.**
WNBA lifetime is **31 settled orders on $124.96** (+3.31%, +$4.09). It is the
only sport in the black — mlb -13.39%, nfl -4.06%, soccer -46.87% — and it is
**noise**. Do not scale stakes on it. T1-5 gives the signal that will be readable
inside one September.

**T3-5. Watch the Polymarket accounting defect.**
The MLB assessment recorded `polymarket/game_line` reporting a loss larger than
its own stake. WNBA's Polymarket slice is 3 orders / $12.14, too small to
confirm or exclude the same defect. Re-check once WNBA Polymarket volume exists.

---

## Tier 4 — the live engine

There is no live WNBA product today. `line_live_age_sec`, `line_live_span` and
`line_live_n` are **null on 1,777 of 1,777** signals: the engine has never seen a
live market price, so every "edge" is against a pregame line that is no longer
purchasable. The apparent 73.95% hit rate is that fact, not skill.

**T4-1. Capture a live line.** This is the precondition for everything else in
the tier; without it the live engine cannot be evaluated or traded, only
admired.
*Verify:* `line_live_n > 0` and a non-null `line_live_age_sec` on live rows.

**T4-2. Until then, restrict live BET emission to Q1–Q2.** The only honest cell
in the data is **Q1 with a real market line: n=537, 55.87%, +6.65%, +1.62 SE** —
suggestive, not significant. Q3/Q4 numbers are leakage and must not be reported
as performance.

**T4-3. Combine `pace_proj` with `sim_mu` for side choice.** Both already sit in
every record. Pooled, `corr(pace_proj, final) = +0.7493` vs `sim_mu` **+0.5611**;
on the honest cell `pace_proj` picks **56.84%** vs `sim_mu` **54.72%**. But in Q1
`sim_mu` is the better *point* estimate (MAE 6.636 vs 7.453) — they carry
different information, and a naive 50/50 blend did **not** beat either
(54.72%). Fit the combination, don't assume it.

**T4-4. Correct the low bias.** Q1 `sim_mu` bias **-2.240**, `pace_proj`
**-1.098**, producing a structural UNDER lean (1,058 UNDER vs 744 OVER).

---

## What to measure over 2026-09-17 .. 2026-09-25

30 games in 9 days is roughly a **75% increase** on the 39-game sample this
assessment's strongest numbers rest on. Pre-register these, so the sprint is a
test and not a story:

| # | quantity | current reading | passes if |
|---|---|---|---|
| 1 | ML sim AUC, clean root | 0.8413 (n=39) | >= 0.70 on the new slate |
| 2 | implied-SD / residual-SD ratio | 1.02 (n=39) | stays in 0.9–1.2 after the break |
| 3 | board game-line ROI | -9.68% (n=105) | >= 0 once T0-1/T0-2 land |
| 4 | prop `corr(edge, win)` | +0.0002 (n=656) | > 0 out of sample |
| 5 | WNBA CLV, same-book | never measured | resolved > 0, and reported |
| 6 | live `line_live_n` | 0 of 1,777 | > 0 |
| 7 | Layer 2 `per_sport.wnba.selected` | 0 on 13 of 14 days | > 0 per slate |
| 8 | exchange quotes on WNBA board rows | 0 of 1,115 | > 0 |

Item 2 is the one to watch hardest: the restart after a three-week break is
precisely the condition that produced overconfidence ratio **1.61** in May.
