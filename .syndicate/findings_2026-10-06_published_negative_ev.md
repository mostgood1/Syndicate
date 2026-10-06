# Why published lines show negative EV, and where the staked portfolio actually loses -- 2026-10-06

Lane `published-negative-ev` (session 5942cf5f). User: "look into why published lines show negative predicted EV - we really need Syndicate to be delivering profitability while maintaining our main goals".

All numbers are read-only from the local fleet (production since 2026-09-30), 2026-10-06 ~15:00-16:00Z.

## 1. The daily optimizer's "published" column is NOT the recommendation set (H1 CONFIRMED)

On 2026-10-05, `clv_openings` (the shortlist's published rows) covered most of each sport's recorded population:

| sport | published / recorded keys |
|---|---|
| nhl | 625 / 728 (86%) |
| mlb | 869 / 1,151 (75%) |
| nfl | 2,300 / 3,377 (68%) |
| nba | 1,356 / 2,356 (58%) |
| ncaaf | 1,652 / 4,151 (40%) |
| soccer | 4,213 / 10,623 (40%) |

**This is a defect in my own lane (`daily-optimizer`).** It labelled the published column "recommendations". The staked set is the paper portfolio, the execution ledger with `ev_pct >= 2`, and that is what "recommendation accuracy" should grade.

## 2. The negative EV is real board EV, not an artifact (H2 FALSIFIED)

The recorder's own `ev` field equals `fair x price - 1` exactly and is negative on published rows in every sport:

| sport | mean `ev` | rows with `ev > 0` |
|---|---|---|
| mlb | -5.3% | 33 / 869 |
| nfl | -5.6% | 50 / 2,300 |
| ncaaf | -4.1% | 70 / 1,494 |
| nhl | -6.1% | 6 / 625 |
| nba | -4.7% | 25 / 1,356 |
| soccer | -7.2% | 90 / 4,213 |

About a full vig: the board ranks and serves lines at an ordinary book price. That is fine for a board, whose job is to show every line (PRIME DIRECTIVE). It is not a bet list.

Model EV `(fair + me/100) x price - 1` on published rows: NFL **+7.4%** (n=215 with a model). Soccer reads **-54%** (n=2,215), which is implausible. LEAD: a `model_edge_pct` scale defect on soccer rows.

## 3. What Syndicate actually stakes is losing, and the loss is concentrated (the profitability answer)

Execution ledger: 3,616 orders. Portfolio book (venue `paper`), settled: **623 orders over 4 dates (2026-10-02..05)**.

| slice | n | ROI | win / break-even | predicted EV at entry |
|---|---|---|---|---|
| ALL | 623 | **-7.7%** ($-152.08 on $1,973.83) | 44.1% / 47.3% | +3.6% |
| market-only (price shopping, no model edge) | 268 | **-13.6%** | 44.0% / 47.6% | +3.7% |
| model edge present | 355 | -3.3% | 44.2% / 47.0% | +3.6% |

- By sport: ncaaf -7.9% (316), nfl -6.9% (158), mlb -10.8% (90), wnba -9.6% (52).
- Every order's side was `side_picked_by=price_shopping`. Nearly all were pregame.
- **Paper fills record `fees_dollars = 0`.** Most fills are at exchanges (prophetx 243, novig 90, kalshi 39), so real-money results would be WORSE.
- Rough significance, ignoring game clustering (which widens intervals): the total gap of -11.3 pts is ~2.8 SE; market-only ~2.8 SE; model ~1.3 SE (not distinguishable from its prediction yet).

### The winner's curse: market-only edges on thin lines (decisive, monotone)

Joined to each order's published opening (`books_quoting`), 623 / 623 joined:

| basis / books quoting | n | ROI |
|---|---|---|
| market-only, 1-2 books | 181 | **-22.6%** ($-133.75 = **88% of the whole portfolio's loss**) |
| market-only, 3-4 | 47 | -11.3% |
| market-only, 5-7 | 19 | +6.5% |
| market-only, 8+ | 21 | +42.6% |
| model, 1-2 | 210 | -1.4% |
| model, 3-4 / 5-7 / 8+ | 59 / 45 / 41 | -14.9% / -11.2% / +8.2% |

With 1-2 books the "consensus fair" is essentially the other book. "Best price beats fair by >= 2%" then selects the side where the two disagree, which is usually the stale one. Selecting on a noisy estimate inflates it. Model-backed bets survive thin lines far better (-1.4%), because their edge does not come from the noisy fair.

**Thin lines are the norm.** Published openings on 10-05 with only 1-2 books quoting: nfl props 89%, nba lines 88%, ncaaf lines 68% / props 100%, mlb props 74% / lines 43%, nhl props 99%, soccer 95-99%. Memory `project_odds_capture_lost_books` says the 1-book capture was fixed 2026-08-06 (#209). On the fleet it is thin again. Cause NOT investigated here (LEAD): fewer regions/books requested for credit budget? Books dropped by freshness? Consensus built from a subset?

## Caveats

- 4 dates, 623 bets. The slicing was exploratory, so the book-count result is a strong, pre-registrable hypothesis, not yet a validated rule.
- CLV is not stored on settled orders (`mark` empty). Today's live marks show avg CLV +0.76% on 274 marked orders (moved toward 148 / against 32), which is not yet consistent with the losses. CLV on SETTLED orders is the faster-converging test.

## Ranked fix list -- per LINE, never a market withhold

1. **Uncertainty-adjusted EV for sizing (a property of the line: how many books form its fair).** Shrink a market-only (price-shopping) edge by the noise of a fair built from N books; Kelly on the adjusted EV. A 1-2-book market-only edge then sizes to ~0 via the existing per-line `Kelly <= 0` guard. Model-backed edges are unaffected. On this sample, removing market-only 1-2-book stakes leaves about $-18 on $1,382 (~-1.3%). That is in-sample, so pre-register and verify forward.
2. **Restore book breadth in odds capture** (root cause; best-price grading was worth +2.79 ROI pts paired, n=1,091). Find why fleet lines show 1-2 books.
3. **Charge exchange fees in paper fills**, so paper P&L is not fee-free.
4. **Store CLV on settled orders**, which converges faster than ROI.
5. **Repoint the daily optimizer's recommendation grade at the execution ledger** (staked orders, their entry price, fees, CLV) instead of `clv_openings`. My lane's defect.
6. LEAD: soccer `model_edge_pct` scale (model EV -54% on published rows).
