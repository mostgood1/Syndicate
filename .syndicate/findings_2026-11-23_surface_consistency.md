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

## Reading 3 -- the code paths behind it `[code read, main at e86a2083e; nothing run]`

Every surface starts from the Layer 2 shortlist rows (`read_layer2_shortlist`, `pipeline/intelligence_state.py:3612`)
or the quote grid under them. Each then recomputes something of its own. The ones that move a shown or placed bet:

| # | what | one side | other side |
|---|---|---|---|
| D1 | in-play row source | the board and the rail read the in-play overlay (`book_grid_artifact.py:973`, merged `intelligence_state.py:1877`), which is not venue re-priced | the plan, Ask and the cheat sheets read the older shortlist row for the same market (`portfolio_commit.py:2279`, `ask_the_syndicate_adapter.py:1270`, `build_cheat_sheets.py:179`) |
| D2 | Suggested vs staked | Suggested is judged at the best bettable book (`layer2_board.py:3712`) | the live and paper2 books re-price at the venue and admit on venue net EV > 0. With `SYNDICATE_LIVE_EV_FLOOR=0`, non-Suggested rows reach the live book (`venue_scope.py:183-217`, `pipeline/portfolio_commit.py:527-553`) |
| D3 | fee | the board's score passes no phase (`layer2_board.py:4687-4700`) | venue scope passes phase and ticker (`venue_scope.py:206-216`); the cheat sheet passes neither and treats a failed lookup as 0 (`cheat_sheets.py:63-76`); the in-play bot fixes Kalshi at 1.0 (`inplay_entries_paper.py:133-136`) |
| D4 | EV gross vs net | the board EV column is gross (`layer2_board.py:5436`) | the Suggested gate, the sheet's "value" and the play cards are net (`cheat_sheets.py:207`, `play_cards.py:69-78`) |
| D5 | model probability | board Win% is the raw projection (`layer2_board.py:5454-5487`) | the stake probability is the L2 fair + `model_edge_pct` (`portfolio_commit.py:765,805`), and that edge was measured against the projection's own fair (`prop_projections.py:1415-1442`) |
| D6 | fair | Layer 2: per-book de-vig, then the median (`layer2_board.py:1681`) | the projection fair de-vigs the mean vigged price (`prop_projections.py:1179-1219`); Layer 1 recomputes fair in JS (`layer1_board.html:734-753`); the live lens uses one quote (`app_slice.py:10482`); the in-play bot polls OddsAPI itself (`inplay_entries_paper.py:148-183`) |
| D7 | "top" | shortlist score (`layer2_board.py:3600`) | Ask sorts by model edge first and never reads Suggested (`ask_the_syndicate_data.py:3657-3664`, `ask_the_syndicate_adapter.py:1208-1229`); the hub sorts by `edge` (`hub_summary.py:24-30`); sheet picks, play cards and NHL picks each use their own rule (`cheat_sheets.py:1190`, `play_cards.py:69-78`, `nhl/picks.py:34-41`) |
| D8 | meaning of `edge` | Layer 2 cards: the market EV fraction (`layer2_board.py:4285`) | legacy cards: model minus fair (`recommendation_engine.py:499`). Both feed the board's `edgeValue` and the hub sort |
| D9 | stake | paper: 1/4 Kelly x credibility (`portfolio_commit.py:1244`) | live: a $5-10 band on full Kelly (`live_stake_band.py:170-183`); in-play: 1 contract; MLB card: `stake_u` |
| D10-D13 | live and freshness | board live edge = live p - projection fair | rail flag = live p - L2 fair (`intelligence.html:3416-3436`); a live row can show a pregame Win% beside a live edge (`live_gameline_join.py:3092-3113`); chip age is trusted 120 s on one path and 600 s on another (`intelligence.py:3618` vs `intelligence_state.py:2207`) |
| D14 | per-sport win probability | board: NBA histogram + book blend (`nba_game_projections.py:347-363`) | NBA cards: logistic on margin (`nba/cards.py:1686-1691`); NBA/MLB chips: raw sim (`game_chip_intervals.py:588-603,1058`) |
| D15 | identity | the plan's `position_key` includes the book (`portfolio_commit.py:1013`) | `pick_id` is book-free (`layer2_ledger.py:52-64`); board dedupe uses matchup text (`intelligence_board.py:394-400`); the overlay ignores line and side (`book_grid_artifact.py:1321`) |

The intended single sources already exist, and each one is bypassed:
- **`decision_record.py`** ("ONE decision record per board line") is shadow only: written from `intelligence_state.py:8209`, and
  nothing reads it for placement, sizing or display.
- **`cell_calibration.py`** (#847): one model probability, all four switches off.
- **`_stamp_suggested`** (`layer2_board.py:3636`): one pick definition.
- **`venue_fees.taker_fee_per_contract`**: one fee lookup, called with different arguments per surface.
- **`opportunity_signals`**: the de-vig and EV maths, re-implemented in Layer 1 JS, the live lens, the in-play bot, the
  cheat sheet and NBA cards.

`.syndicate/findings_2026-10-20_one_engine_audit.md` (forks F1-F5) measured D2, D5, D7 and the NHL-picks fork a month
ago, and the code paths are still there. **What it lacked was an instrument that fails while they stay.**

Not verified here: the fleet values of the flags these depend on (`SYNDICATE_PRICING_CALIBRATION`,
`SYNDICATE_CELL_CALIBRATION_*`, `SYNDICATE_FAIR_DEVIG_METHOD`, `SYNDICATE_LIVE_EV_FLOOR`, `SYNDICATE_LIVE_STAKE_BAND`,
`SYNDICATE_SCORE_FEE_NET`).

## Step 1a -- Ask's headline is the board's picks, for the asked sport `[built 2026-11-23, user "Yes, start with Ask"; NOT DEPLOYED]`

Display only: Ask places and sizes nothing, so this is not a betting change.

There were two causes, and both are fixed in code:

1. **Ranking.**
   - `_board_top_opportunities` used to rank `model_edge_pct` first and vet rows on "every edge term positive". It
     now takes the board's own pick:
     - `_is_board_pick`: `suggested is True` (from `_stamp_suggested`) and `ev_pct > 0`;
     - `_board_pick_rank_key`: picks first, then the shortlist's own `score.score`, then EV.
   - The board-ranking table (`_board_candidates_evidence`) shares the same key. It gains a `Board pick` column, and
     its chart now draws the board's picks by EV, not model edges.
   - A Suggested row with a negative model edge is published. The board bets the price, and the prose states the
     sim's view and skill.
2. **Routing.**
   - The view passed only the client's `context` into `build_syndicate_query_response`. The router's inferred sport
     reached the response only after the headline had been built. It now goes in as `routed_sport`.
   - A sport with no board lines now gets "The board has no MLB lines today.", not the cross-sport snapshot.
   - The "No board opportunity matches ..." note is suppressed when the headline is already sport-scoped.
   - The snapshot's own summary is no longer shown over a board answer.

**Contract changed with it.**
- `scripts/ask_syndicate_regression.py`: `top_edge_matches_board` (chat max edge == board max `model_edge_pct`, which
  is the defect, encoded as the test) becomes `top_pick_matches_board`. The headline's first row must be the board's
  top pick by EV, and must be a pick. It uses the same two predicates, imported.
- New check: a sport-specific ranking question must not headline another sport.
- `prop_evidence_checklist.py`'s exempt title "Top edges" becomes "Board picks".
- That checklist FAILS on two other titles ("... by game ...", "... last ..."). They fail identically on unchanged
  `main`, so this change did not cause them.

**Replay on the fleet's 19:32:46Z shortlist**, through the new code:

| question | headline |
|---|---|
| best bets today | 5 board picks: soccer corners x3, NCAAB h2h x2; "Best EV +5.2% at the posted price" |
| best NBA bets | none. "Of its 1,128 NBA lines, 1,100 have a stale quote, 1,039 are below the board's minimum EV and 230 have a fair price from one book only" |
| best NHL bets | 5 NHL picks, EV +2.4 to +4.7 |
| best MLB bets | "The board has no MLB lines today." |

Before the change, the first two were the same 5 cross-sport rows, from losing models.

**Tests.** 365 passed, 6 skipped across the 14 Ask test files. That includes 7 new end-to-end tests through
`POST /api/syndicate/query` (`tests/test_ask_headline_board_pick.py`, routed sport off != on). The old tests that
asserted "headline = max model edge" were rewritten to the board-pick contract.

**Lead it exposed, not followed.** 1,100 of 1,128 NBA lines carry `suspect_stale_quote` at 1:30 PM CT on game day, so
the board can pick no NBA bet at all. Whether that is quote cadence or a capture gap is unmeasured.

**DEPLOYED to web at 20:30:02Z** (`d845fe345`, user "Deploy to web now"; `deploys.md` entry of the same instant).
Measured on the served payload:
- **20:30:12Z:** the NBA headline went from 5 off-sport rows to 0, explained in the board's reasons. The best-bets
  headline went from 0 Suggested rows to 5, with "5 in-play board picks left out".
- **20:32:02Z,** with the revised instrument: `ask_headline:all` 0 of 5 bad and `ask_headline:nba` 0 of 0.
  - The check now fails on non-picks and off-sport rows. It reports the sim's skill verdict and no longer judges
    it: board picks are chosen on price, and the verdict rides beside them.
  - Of today's 5 headline picks, 3 carry a "loses" sim verdict and 2 are unmeasured. That is information about the
    sim, not about the price edge the pick rests on.

## Step 1b -- "Our sim has X at Y%" quotes the sim `[built 2026-11-23, user "Yes, do the Our sim wording next"; NOT DEPLOYED]`

`layer2_row_context.row_explainer` wrote "Our sim has {subject} at {model}", where `model` is the SERVED probability
(`_model_prob_for_side`). Where the board does not trust the sim yet, that number is the market's.

**The fix.** It now reads the sim's own `p_model_raw` (stamped by every blend and calibration step). It maps the
number to the row's side through `_model_prob_for_side` itself, and says which number is which:
- book blend weight 0: "Our sim has X at 59.2%, but it carries no weight in this market yet, so the board uses the
  market's number; the no-vig market across 7 books says 38.7%."
- partial blend: "... at 60.6%, weighted 10% against the market for a board probability of 48.7%; ..."
- calibrated: "... at 62.5%, calibrated to 49.3% for this market; ..."
- unchanged when the served number is the sim's (within 0.05 pp), or on a live row (the live re-sim's number).

The "N% of its simulations finish over it" sentence now takes the sim's number too. The sentence keeps its opening
and its "; the no-vig market ... says Z%." close, so `intelligence_state`'s live-strip regex and the cheat sheet's
`_ASK_MODEL_LEADS` still match. Both are tested.

**Replay** over the fleet's 21:00:24Z shortlist, through the new code. Pregame rows with a model and a fair: 1,765.
- 757: the sim had no weight, and the old text called the market's number the sim's (NBA 729, NCAAB 24, WNCAAB 4).
- 318: a partial blend; the old text gave the blended number (all NBA).
- 13: a calibration (NCAAB 12, WNCAAB 1).
- 677: unchanged.

**So 1,088 of 1,765 (62%) pregame explainers said something other than the sim's number under the sim's name.**

**Where it runs.** `layer2_board.py:4360`, in the board build on refresh-worker. The text reaches the board cards, Ask
cards and cheat-sheet picks, all from that one `detail`. It is display only: no score, floor, plan or stake reads
`detail`. Tests: `tests/test_layer2_explainer_sim_attribution.py`, 9 new; 43 pass with the explainer suites.

### Reading 4 -- the peer's report on Suggested vs the purchaser, re-measured `[20:15:43Z-20:19:41Z, fleet, read-only]`

`portfolio-monitor` (session 69d80317) messaged at 19:46Z. It said explicitly that it was not asking for a change.
Re-derived here, same instant per read:

- **Best book.** 47 Suggested rows at 20:15Z. The best price is a sportsbook on all 47: FanDuel 14, BetMGM 13,
  ProphetX 6, BetRivers 4, DraftKings 4, Novig 3, Bovada 2, Fanatics 1. 30 also carry a Kalshi or Polymarket price,
  and 3 of those clear +2% GROSS at the board's fair; fees would cut that further. The peer read 0 of 34 at +2% NET.
  That agrees in direction. **The purchaser can buy almost none of the board's picks, by construction.**
- **Stale in-play picks.** 7 of 47 Suggested rows were in play at 20:15Z, all on a market price alone.
  - NCAAB Long Beach St @ FIU, under 159.5 at BetMGM -102 on a 0.52 fair (quote age 113 s), at 75-75 with 0:57 left.
    That is a price the market has left, and `suspect_stale_quote` did not catch it.
  - At 20:19Z the count was 11 in play, 10 of them market-only.
- **Not re-derived:** the peer's -7.06% [-13.60, -0.46] over 1,249 bets for the 0% floor population. It is cited as
  theirs.
- **The purchaser's in-play rule reads a role-scoped key. That is harmless for the purchaser and matters only to a
  caller elsewhere.**
  - `portfolio_commit._refuses_in_play_market_fair` first checks `SYNDICATE_PORTFOLIO_MARKET_FAIR_SPORTS`. Read from
    the running roles at about 20:25Z, it is `mlb,nba,wnba,nhl,nfl,ncaaf,ncaab,soccer` on refresh-worker and ABSENT
    on live-odds-worker. On a role without it the function returns False for every row.
  - **CORRECTED 2026-11-23 ~20:40Z.** This section first called the key's source "unlocated". It is
    `~/syndicate-prod/fleet_env/refresh-worker.json`, under `values`: the frozen 10-01 snapshot layer. My reader
    looked for an `env` block and missed that shape. Re-read with a shape-blind search: present in refresh-worker,
    ABSENT in web and live-odds-worker. `portfolio-monitor` found it first.
  - **No unguarded path, so the "risk" framing is withdrawn.** Code checked here: the only callers are
    `portfolio_commit.py:1197` (the plan commit) and `paper_ladder.py:159`. `portfolio-monitor` reports, and I have
    not re-derived:
    - the plan commit runs only on refresh-worker (38 PLAN_WRITTEN and 152 LIVE_PLAN_WRITTEN there in 3 h, 0 on
      live-odds-worker);
    - live-odds-worker only executes written plans;
    - absent is STRICTER, because with the allowlist empty every row with no model edge is refused
      `no_model_edge_pct` before the in-play check.
  - What stands is narrower: **a caller on another role**, such as Ask on web, cannot call the function and get the
    purchaser's answer. That is why Ask builds the rule from its parts.

**Step 1a amended by this.** Ask's headline leaves out a Suggested row that is in play on a market price alone. That
is the purchaser's rule, and the system would not buy that row. Ask builds the rule from `portfolio_commit`'s own
role-independent pieces (`_in_play_market_fair_allowed`, `_in_play_market_fair_cells`, `_market_fair_family`), because
calling the function from web would be a silent no-op. The headline then says how many it left out:
"10 in-play board picks left out: on a market price alone, the purchaser does not buy them" (replay, 20:19Z read).
The board still flags these rows Suggested. That is a **board defect owed to the board's owner and the user**:
- changing `_stamp_suggested` changes the Suggested series that the daily grader and the paper book read;
- the live plans also read Suggested, so changing it may be a betting change.

**The canonical-pick decision is partly made, by the user, elsewhere.** The batch kit
(`C:\tmp\w1124_floor\dry_SKILL.md`, CHANGE P, lane `live-ev-floor-off`) records the user's answer in session 69d80317,
about 2:15 PM CST 11-23: "Yes, add it tonight". That turns the 0% live EV floor OFF in tonight's 11-24 window batch.
After it loads, the live plans buy Suggested rows only, re-priced at the venue. Pregame, Ask's headline, the board's
picks and the purchaser's pool will then be one set.

What is still split is the **price**. Suggested is judged at the best sportsbook. The purchaser re-prices at the
venue, where 3 of 30 venue-listed picks cleared +2% gross at 20:15Z (`portfolio-monitor`: 0 of 34 net). So the
purchaser should be expected to buy very few rows after the load. That is a decision about what a pick is priced
against, and it is the user's.

## Evidence on what earns ROI (from the ledger, not re-measured here)

Nothing has cleared the bar yet:
- the Suggested set promised +3.41% and returned -3.02% [-5.56, -0.51] (11,748 bets, 28 days);
- the live book since 11-03 is -4.94% [-12.15, +2.26] (914 bets), with fees 78% of the loss;
- #738 P1 CLV is -0.18% [-0.91, +0.53] (188 bets);
- `cell-calibration` (#847) shows a held-out Brier gain of -0.0062 per row [-0.0102, -0.0021] on the scorecard, and
  is default-off.

So the single source cannot be declared "the profitable one" today. It can be made **one**, measured, and pointed at
whichever probability and selection policy clears the #738 gate.
