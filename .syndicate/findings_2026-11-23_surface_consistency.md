# Surface consistency oversight -- 2026-11-23 (lane surface-consistency-oversight)

Counts and percentages only (public repo). Substrate: **fleet** (`http://127.0.0.1:10000`), read-only GETs plus
two Ask queries. Nothing on the fleet, the ledger or a venue was changed.

## Why this lane exists

The user asked (2026-11-23, about 1:20 PM CST) for one session with oversight of the whole app. Its job is to make
every surface use the same data: the Layer 2 board, the live rail, the Layer 1 board, the portfolio, Ask the
Syndicate, the cheat sheets and every per-sport endpoint. That data should come from one source of truth, tuned to
place correct bets with positive ROI. The user chose to run it here ("Do it here").

## Reading 1 -- the same line, read on every surface `[19:25:50Z-19:32:48Z]`

**Method.**
- Two waves of GETs:
  - 19:25:50Z: `/api/board/layer2-shortlist?limit=2000`, `/api/board/live-rail`, `/api/board/game-chips`,
    `/api/portfolio/plan`, `/api/portfolio/live` and `/api/portfolio/summary`;
  - 19:28:59Z: `/api/board/layer1?sport=` for 6 sports, `/api/cheatsheets/<sport>/2026-11-23` for 6 sports, and
    two `POST /api/syndicate/query`.
- At 19:32Z, the per-sport endpoints, re-read beside a fresh Layer 2 read: `/<sport>/api/picks|cards|market-board|props`
  for NBA, NHL, NFL, NCAAF, NCAAB and soccer.
- Line identity: event_id, market (lowercased, `player_` stripped), player, side, line (to 0.5), segment.
- Pregame rows only, unless a row says otherwise.
- The cheat sheets were BUILT at 17:30-17:37Z (picks refreshed 17:52-19:22Z). Part of every cheat-sheet difference
  below is therefore age. The test that separates age from method is a same-book, same-price pair, and it is named
  where it was used.

**Instrument cautions.**
- 12 parallel GETs got 7 `ConnectionResetError`s from web. Keep it to 3 in flight.
- `/intelligence/api/opportunity-board` did not answer within 120 s.

### What agrees

| pair | joined lines | fair > 1 pp apart | EV > 1 pt apart | same book / same price |
|---|---|---|---|---|
| Ask board cards vs Layer 2 | 18 of 25 (`best bets`), 15 of 25 (`best NBA bets`) | 0 | 0 | price 33 of 33 |
| Stage A plan vs Layer 2 | 15 of 15 | 0 | 0 | 15 of 15 / 15 of 15 |

Ask's board cards are copies of Layer 2 rows, and so is the Stage A plan.

### What does not agree

1. **Ask's headline ranks a model the same card says loses.**
   - `structured_response.top_opportunities` is the same 5 rows for "What are the best bets today?" and "Best NBA bets
     tonight?". Asked about NBA, the answer is NFL, NCAAF, NHL, soccer and NCAAF.
   - Each row is ranked by the model's edge over the market: 28.15, 25.48, 24.50, 23.07 and 22.48 points.
   - 4 of the 5 carry `model_skill_status=measured` with a verdict that the model LOSES to the de-vigged market or
     the close (e.g. NFL receptions, Brier +0.0242 [+0.0189, +0.0336] over 2,542 obs). The 5th is unmeasured.
   - The same answer's 25 board cards contain 0 Suggested rows.
2. **Two fair probabilities at the same book and price: Layer 2 vs the cheat sheet.**
   - Joined lines: 302 of the cheat sheet's 752 rows.
   - Fair > 1 pp apart on 25 of 302, up to 10.3 pp. EV > 1 pt apart on 62 of 302. Same book 282 of 302, same price
     243 of 302.
   - Same book and same price, different EV (this rules out age, because the input price is identical):
     - receiving yards under, bovada +115: board +4.01, sheet +2.83;
     - NHL assists over, betmgm +240: board +1.33, sheet +4.64;
     - NHL assists over, betmgm +100: board +1.06, sheet +2.16;
     - NHL points over, betmgm -110: board +1.03, sheet +2.56;
     - NHL points over, betmgm -140: board +0.87, sheet +2.30.
   - The cheat sheet carries its own `fair_method` per row (`consensus`, `sharp_anchor`), its own `check.verdict`
     (`value` at EV >= 2.0) and its own `p_posterior`. None of these is on the board.
3. **Two "suggested" flags.**
   - The cheat sheet flags 62 rows `suggested`. 44 of those are on Layer 2, and only 4 of the 44 are Layer 2
     Suggested.
   - Over all 302 joined lines, the two flags disagree on 41.
   - Cheat-sheet picks vs Layer 2: 36 picks, 5 still on Layer 2, 1 Suggested. The picks are frozen at publish time
     by design.
4. **"Our sim has X at 39.0%" quotes the market, not the sim.**
   - Layer 2 has 1,151 pregame rows with a sim ladder.
     - On 733 of them, `model_probability_cal` equals the market fair, because `book_blend_w` gave the sim weight 0.
     - On 643 of them, the sim's raw ladder probability is more than 5 pp from the fair.
   - Example: Cedric Coward over 2.5 threes.
     - Sim ladder `p_model_raw`: 0.592.
     - Calibrated "model": 0.3868 (= the quote's fair, shin consensus).
     - The projection block's own fair: 0.3901, a second fair on the same row.
     - Shadow likelihood: 0.374.
   - The Ask card and the cheat-sheet pick text both say "Our sim has ... at 39.0%". That is the market's number
     under the sim's name.
5. **The portfolio buys a different set from the one the board recommends.**
   - Already measured by `portfolio-monitor` at 19:07Z (`findings_2026-11-23_portfolio_monitor.md`); re-read here.
   - Stage A plan (`/api/portfolio/plan`): 15 positions, all 15 Layer 2 Suggested, all at sportsbook prices (`book`
     fanduel and others).
   - Live orders today: 33 (31 filled), all on Kalshi (20) or Polymarket (13), `side_picked_by=price_shopping` on
     33 of 33.
     - **0 of the 33 share a position_key with the plan.**
     - 13 are still on Layer 2, and 0 of those are Suggested.
     - EV on the same line: board median 4.13 pts below the order. On 10 of 13 the board shows EV <= +0.2 at a
       sportsbook, while the order recorded +2.6 to +5.0 at a better venue price.
     - Example: NBA alt total under 231.5. Board betmgm -250, EV -1.00. Order Kalshi -213, EV +4.03.
     - So the board's "best price" does not show the venue price the book actually pays.
   - The plan's `model_probability` equals the market fair on 13 of 14 positions. Layer 2's `model_probability_cal`
     for the same rows is a median 4.0 pp away. The plan's record of "the model" is not the model.
6. **Per-sport pages run their own raw sim, with their own price and their own EV.**
   - **NHL** (`/nhl/api/cards`, `/nhl/api/picks`). The cards price raw sim probabilities.
     - Against the Layer 1 consensus fair, the sim's away-team win probability is higher on 7 of 7 games, mean
       +4.1 pp (+1.4 to +6.5).
     - So every away moneyline reads +EV (+0.7% to +11.2%) and every home moneyline reads -4.8% to -12.0%.
     - The picks page reads `nhl_source/data/processed/recommendations_sim_2026-11-23.csv`. It headlines "11.5% EV"
       (Under 6.5 ANA@SEA) and 8 more picks at 4.9-9.3% EV: 5 away +1.5 puck lines and 3 unders.
     - Layer 2 Suggested has none of them. The portfolio holds none of them.
     - The card's displayed price is not the board's: UTA ML card -113 against board best Polymarket +104.
   - **Soccer** (`/soccer/api/cards`): Monza ML +255 is shown at **+17.2% EV** from the raw sim.
     - Brentford ML: card +9.4%; Layer 2 +0.56 at fanatics +130.
   - **NBA**: `/nba/api/picks` serves 0 cards and `/nba/api/props` an empty page. Layer 2 has 1,136 NBA pregame
     rows and the NBA cheat sheet has 12 picks.
     - `/nba/api/market-board` serves fractional American prices (-390.0058).
   - **NCAAF** (`/ncaaf/api/picks`): 24 cards ranked by "points better than the vigged consensus", correctly labelled
     price-shopping, not EV. That is a fourth ranking quantity.
   - **NFL** (`/nfl/api/picks`): 12 SmartSim win-probability cards. "No stored NFL weekly recommendation snapshot
     exists for this week yet."
7. **Rail vs Layer 2.**
   - 7 of the rail's 77 rows share a key with Layer 2. Fair > 1 pp apart on 5 of the 7.
   - These are in-play rows, and the two reads were 0-7 min apart, so this one is age-confounded. No claim is made.

### What this says, in one line

There is **one shared universe** (every surface starts from Layer 2 rows or the same quote grid). But there are **at
least four fair probabilities**, **at least five "model" probabilities**, **at least five ranking quantities**, and
**three recommendation sets**. On top of those, **per-sport pages run a parallel raw-sim producer** that none of the
others read.

## Reading 2 -- the instrument, first run `[19:38:51Z-19:38:57Z, scripts/surface_consistency_check.py, exit 1]`

The check turns Reading 1 into a repeatable test (todo `#861`).

| check | over | of | note |
|---|---|---|---|
| `same_price_ev:cheat` | 35 | 235 | same book, same price, EV more than 0.5 pt apart |
| `pick_flag:layer2_vs_cheat` | 42 | 296 | cheat flags 44, both flag 4 |
| `ask_headline:all` | 5 | 5 | 4 losing models, 1 unmeasured |
| `ask_headline:nba` | 5 | 5 | the same 5, all 5 off-sport |
| `sim_attribution:ask_cards` | 2 | 15 | quoted number = market fair, sim ladder more than 5 pp away |
| `plan_vs_orders` | 33 | 33 | plan 14 positions; 16 orders on the board, 0 Suggested; price_shopping 33 |
| `venue_price_hidden` | 12 | 16 | the order paid a better price than the board's best shows |
| `sport_card_bias:nhl_away_ml` | 1 | 7 | mean +4.11 pp, same sign 7 of 7 |

The test suite caught one defect in the check before this run: "beats the close" contains the letters "lose". The
check now matches the whole word.

## Evidence on what earns ROI (from the ledger, not re-measured here)

Nothing has cleared the bar yet:
- the Suggested set promised +3.41% and returned -3.02% [-5.56, -0.51] (11,748 bets, 28 days);
- the live book since 11-03 is -4.94% [-12.15, +2.26] (914 bets), with fees 78% of the loss;
- #738 P1 CLV is -0.18% [-0.91, +0.53] (188 bets);
- `cell-calibration` (#847) shows a held-out Brier gain of -0.0062 per row [-0.0102, -0.0021] on the scorecard, and
  is default-off.

So the single source cannot be declared "the profitable one" today. It can be made **one**, measured, and pointed at
whichever probability and selection policy clears the #738 gate.
