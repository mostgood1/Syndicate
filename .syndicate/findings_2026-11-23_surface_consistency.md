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

## Step 1b -- "Our sim has X at Y%" quotes the sim `[built 2026-11-23, user "Yes, do the Our sim wording next"; LOADS in the 11-24 window batch, user "Ride tonight's window"]`

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

**Load decision `[2026-11-23 ~7:10 PM CST]`.** The user was asked 'Load the "Our sim" fix in tonight's 2:15 AM
window restart, or fast-forward the fleet now?' and answered "Ride tonight's window". Main carries it as `2010b06ca`;
the fleet checkout is at `d845fe345`, so the 11-24 batch's ff carries it and its drained down/up loads it.

- **The batch would have STOPPED on it.** STEP 4 of the batch prompt (`nfl-level-refit-load-1120`) makes any
  `syndicate/features/` commit class (c) unless the prompt names it, and the `80dbb08f3` line covers no later commit
  of this lane. Added a line naming `2010b06ca` as a DISPLAY-ONLY ride-along, quoting the user's answer. It was
  added right after the `80dbb08f3` line, additions only. Script
  `C:\Users\TEMPAD~1\AppData\Local\Temp\claude\00d03ca7053346b9\d5aa3287-9736-4080-bbac-59f9767838aa\scratchpad\add_1b_ridealong.py`.
  It was sha-guarded, `b2b92c6ad5836a08` -> `ea470e747d7ef969` (113,662 -> 115,082 B). The dry run on a copy was
  byte-identical to the real result. The pre-edit copy is `SKILL.before_1b.md` in the same scratchpad. The
  schedule is unchanged: fireAt 2026-11-24T08:15Z, enabled.
- **The rest of the range `d845fe345..cabd9284d`, at 7:15 PM CST.** Five runtime commits. Apart from
  `2010b06ca`, all four are `scripts/` that no role imports (`git grep` on the basenames over
  `local_production.py`, `fleet_role_spec.json`, `pipeline` and `syndicate` finds substrings only, e.g.
  `web_base_url`):
  - `5a7d0217d` (this lane's check);
  - `a37defa97` (`portfolio_watch/panel_shot.py`);
  - `1eaa09bac` and `46e0deed8` (`_base_url.py` and the portfolio probe, "Tooling only, not a betting change").
- **What reads `detail`** (re-checked by `git grep` on origin/main): the board, Ask and cheat-sheet text
  (`cheat_sheets.ask_points`), and `intelligence_state`'s live-strip regex. Nothing in `portfolio_commit`, no
  score, no Suggested flag, floor, plan, stake or exit. `row_explainer` has no try/except at `layer2_board.py:4360`,
  so an exception there would fail the build. The replay ran the new code over all 1,765 pregame rows with none.

**Reader and BEFORE reading.** `C:\tmp\scc_oversight_d5aa\read_1b_explainers.py` is read-only. It takes the
board query's cards (`response.ranked_all`, which carry `detail`). On each pregame over/under card whose
`sim_ladder_raw_over` (= `p_model_raw`, stamped on blended rows) differs from `quote.fair_probability` by more than
5 pp, it classes the "Our sim has ... at X%" number. Exit codes: 0 OK, 1 OLD > 0, 2 blind.
- **OLD:** X is the market fair (within 0.5 pp).
- **SIM:** X is the sim's (within 0.5 pp).
- **other:** neither, e.g. a partial blend.
- It also counts cards carrying the new clauses.

BEFORE, 2026-11-24 01:18:36Z (7:18 PM CST 11-23), snapshot 23:50:44Z:
- 6,405 cards, of them 3,552 pregame "Our sim" cards.
- 144 over/under cards with a sim-market gap, all NBA: OLD 34, SIM 0, other 110.
- New wording: 0 cards.
- Example: De'Aaron Fox threes quoted 39.8% = fair 39.8%, sim 21.8%.
- Saved: `C:\tmp\scc_oversight_d5aa\read_1b_before_1123.json`.

**Prediction, registered before the load:** after the batch's down/up and the first board build after it,
- OLD = 0;
- SIM = (nearly) all of the gap population; "other" only where the card's fair moved after the build;
- new-wording cards > 0.

Falsified if OLD > 0, or new wording is 0, on a build stamped after the up. The slate will differ, so judge the
shares, not the counts.

**LOADED.** The 11-24 window batch loaded it at 08:30:10Z (2:30 AM CST), in one claimed ff `d845fe345..672a18e87`
and one drained full down/up. Its deploys.md entry names `2010b06ca` as a ride-along. The fleet HEAD was
`2b191302f` at 15:53Z and contains it (`merge-base --is-ancestor`).

**AFTER reading `[2026-11-24 15:53:48Z, 9:53 AM CST; snapshot 15:46:35Z, after the up]` -- PREDICTION MET.**
- 5,624 cards, of them 3,814 pregame "Our sim" cards.
- 655 NBA over/under cards with a sim-market gap: OLD 0, SIM 655, other 0 (before: 34 / 0 / 110 of 144).
- New wording on 1,999 cards: 'no weight' NBA 802, NCAAB 437, WNCAAB 5; 'weighted' NBA 576; 'calibrated' NCAAB 164,
  WNCAAB 15.
- Saved: `C:\tmp\scc_oversight_d5aa\read_1b_after_1124.json`. Exit 0.
- `surface_consistency_check.py` at 15:54Z: `sim_attribution:ask_cards` 0 of 17 OK; both `ask_headline` OK.

Served examples (15:5xZ):
- "Our sim has Alex Sarr over 7.5 rebounds assists at 56.2%, weighted 5% against the market for a board probability
  of 53.1%; the no-vig market across 2 books says 54.6%."
- "Our sim has the under 133.5 at 31.5%, calibrated to 58.4% for this market; ..." This is Hampton @ Old Dominion,
  re-derived from the row:
  - `p_model_raw` 0.685 is P(over), so the sim's under is 31.5%; the sim projects 141.3 points.
  - `book_blend` is `total_calibration` (#816): served P(over) 0.4159, so under is 58.4%.
  - The market's under is 54.8%. The side mapping is right; the calibration pulls under the close by design.

### Step 1b follow-up -- the "board probability" it names is not the board's final number `[2026-11-24 ~10:00 AM CST, fleet, read-only]`

The partial-blend clause ("weighted W% against the market for a board probability of X") and the calibration clause
("calibrated to X") state X = the projection's served probability for the side. The board then applies its own
per-sport pricing calibration: `layer2_board.py` ~2797-2840, `probability_calibration.calibrate`. That stamps
`model_probability_cal`, and `model_edge_pct` is differenced from it. Measured on the 15:5xZ shortlist, of the
sentences that state a board number, X differs from the row's `model_probability_cal` by more than 0.5 pp in:
- NBA 'weighted': 219 of 305 (max 3.7 pp);
- NCAAB 'calibrated': 61 of 105 (max 5.3 pp);
- WNCAAB: 0 of 1.

So 280 of 411 name an intermediate number as the board's. Example: Desmond Bane over 2.5 assists. The sim is 48.6%,
blended to 53.8%, and the board's `model_probability_cal` is 54.9% (= the market fair).

Also measured: the board's `ev_pct` is reproduced best by the market fair on 1,402 of 1,710 pregame rows, and by
`model_probability_cal` on 308. EV is price-shopping EV, as found under step 1a. The fix candidate is display
only, in `_pregame_model_sentence`: name `model_probability_cal` as the board's number when the row carries it.
The user's call. Probe: `C:\tmp\scc_oversight_d5aa\probe_clause.py`.

**HELD `[2026-11-24 ~10:30 AM CST]`: the premise was incomplete -- the BOARD shows two model numbers.** The user
answered "Yes, fix it" to 'Fix the "board probability" number so it quotes the board's final model probability?'.
Before editing, I read which number each consumer uses:
- **Win% cell and stake sizing use the served number:** card `model_probability` = `confidence` =
  `_model_prob_for_side` (`layer2_board._layer2_board_columns`). `bankroll_manager.compute_bet_size` reads card
  `model_probability` (`bankroll_manager.py:193`, called via `intelligence_state.py:6944` `compute_board_stake`).
- **The model edge uses the pricing calibration:** `model_edge_pct` = `model_probability_cal` - fair
  (`layer2_board.py` ~2797-2840).

Measured on the served cards at ~16:25Z: 3,567 pregame cards carry Win%, a model edge and a fair.
- On 1,594, Win% - fair differs from the model edge by more than 0.5 pp: NBA 980, NCAAB 204, NFL 150, NCAAF 117,
  soccer 103, NHL 35, WNCAAB 5.
- On 39, the two point to OPPOSITE sides of the market (each > 0.5 pp; NBA 33). None is Suggested.
- Example: Alex Sarr over 7.5 rebounds+assists shows Win% 53.1% against a fair of 54.6%, beside a model edge of
  +0.16.

So the sentence's "board probability" already matches the Win% cell beside it. Naming `model_probability_cal` would
make it disagree with Win% on those cards instead. The root fix is ONE model number per card for Win%, model edge
and stake. It changes stake sizing's input, so it is a betting change: window only, the user's call. No code was
changed; put back to the user. Probes: `C:\tmp\scc_oversight_d5aa\probe_win.py`, `probe_contra.py`.

### One model number per card -- BUILT, DEFAULT OFF, pre-registered `[2026-11-24 ~11:45 AM CST; user "Build one number, off"]`

The user was asked "Which fix for the board's two model numbers?" and answered "Build one number, off".

**Correction to the paragraphs above.** `model_probability_cal` is NOT a calibration curve on any pregame row today.
`calibration_method` is `identity` on every one (1,730 rows, 15:5xZ). On all 1,002 rows where it differs from Win%
by more than 0.5 pp, it equals the quote fair plus `model_edge_pct_raw`/100, i.e. the model's edge against the
market reading its projection was built on, re-based onto the current fair. Win% shows that older reading. For a
row whose sim has no weight, that is a stale market number presented as the model's. Desmond Bane: Win% 53.8%,
current fair 54.9%. Probe: `C:\tmp\scc_oversight_d5aa\probe_anchor.py`.

**Who reads which number.**
- **The live purchaser** sizes on `fair + model_edge_pct/100` (`portfolio_commit.sizing_inputs_with_provenance`,
  ~line 806) from the SHORTLIST row. It never reads the card's `model_probability` / `confidence`
  (`sizing_candidate` builds its own mapping).
- **The card's number** feeds Win%, the sim tags (`intelligence.html`), Ask, the explainer, the Layer 1
  `_attach_board_stakes` display stake, and the evaluation ledger's `model_probability` for `layer2_shortlist`
  records.

**Which number grades better** (a read-only subagent, verified here against its `out_900.txt`).
- Data: 53,474 graded pregame Layer 2 rows, 448 games, 14 dates (2026-11-10..11-23), from the fleet's
  `reports/intelligence/evaluation_ledger_chunks/` (W, result) joined to `decision_records/*.pregame_lines.jsonl.gz`
  (F, E). Same build, within 900 s.
- Brier W 0.2135 / E 0.2135 / F 0.2101. W-E +0.00001 [-0.00016, +0.00018], game-clustered bootstrap, 2,000
  resamples. Log loss W-E -0.0002 [-0.0010, +0.0005].
- **No accuracy difference; the choice is consistency.** E is what the model edge and the live sizer use.
- Both lose to the market fair: W-F +0.0033 [+0.0020, +0.0048] overall; NCAAF +0.0115, NHL +0.0047; NBA +0.0002
  [-0.0002, +0.0006].
- Scratch: `C:\tmp\scc_oversight_d5aa\grade\`.

**The build.**
- **Switch:** `SYNDICATE_LAYER2_ONE_MODEL_NUMBER`. Absent, or any value outside 1/true/yes/on, is OFF = today byte
  for byte (tested).
- **ON, the card:** `layer2_row_context.board_model_probability` returns `model_probability_cal` on a pregame row
  carrying it with a numeric `model_edge_pct`, strictly inside (0, 1). `layer2_board._layer2_board_columns` uses it
  for `model_probability` and `confidence` (Win%). The replaced served number rides beside it as
  `model_probability_projection`, with `model_probability_basis: "model_edge"`.
- **ON, the sentence** names the same number: "... weighted 5% against the market and re-based on the current
  market for a board probability of 54.7%; ...". Unblended sims read "... re-based on the current market for a
  board probability of X".
- **Unchanged under ON:** live rows, and rows without the pair, keep the served number. Lane
  `cell-calibration-847`'s (b) display stamp takes the new number as its input (its own switch, untouched).
- **Tests:** `tests/test_layer2_one_model_number.py`, 24, covering off == absent and on != off (reachability).
  Existing suites touching the card or sentence: 360 pass. The 8 failures in
  `test_nba_prop_side_face_current_roster.py` fail identically on the unchanged code (roster data absent in the
  worktree).

**Replay** through the new code over the fleet's 1,725 pregame shortlist rows (11-24 ~17:20Z), 0 exceptions:

| reading | OFF | ON |
|---|---|---|
| Win% - fair misses the model edge by > 0.5 pp | 1,004 | 2 |
| Win% and edge on opposite sides of the market | 9 | 0 |
| sentence's board number != Win% | 0 of 295 | 0 of 855 |

- The 2 left are NCAAF moneylines with `model_probability_cal` = 1.0, refused as a certainty, so they keep the
  served number.
- A first ON pass printed the served number on 3 sentences where the two were < 0.05 pp apart. Fixed and tested.
- Replay script: `C:\tmp\scc_oversight_d5aa\replay_one_number.py`.

**Prediction for a load** (on the served board, first build after the load):
- **P1:** Win% - fair misses `model_edge_pct` by > 0.5 pp on 0 pregame cards, apart from rows whose
  `model_probability_cal` is 0 or 1.
- **P2:** 0 cards with Win% and the edge on opposite sides.
- **P3:** 0 sentences stating a board number different from Win%.
- **P4:** the live purchaser's inputs are unchanged (it does not read the card).
- **P5:** no measurable accuracy change (W-E above).
- Falsified by any P1-P3 count above 0 on rows with a cal strictly inside (0, 1).

**Classed a BETTING change for the load, conservatively.** The live sizer does not read the card, but the
evaluation ledger's `layer2_shortlist` `model_probability` switches from W to E at the load. Scorecard and
optimizer readings of that field see E from then on: a break in the series, expected near zero because W and E
grade the same. So it loads only in a window. It is NOT in any window's queue: queuing it (12-08 at the
earliest) is the user's call.

**QUEUED FOR THE 12-08 WINDOW `[2026-11-24 ~11:25 AM CST]`.** The user was asked "Queue the one-number switch for
the 12-08 window?" and answered "Queue for 12-08". Nothing loads it automatically; it goes into the 12-08 window's
batch (Tue 12-08 2-7 AM CST, one ff + one drained full down/up).
- **Line:** ONE GLOBAL line, `SYNDICATE_LAYER2_ONE_MODEL_NUMBER=on`, in `~/syndicate-prod/local_production.env`.
  Global so that whichever role builds cards uses one number. The code `d25f49964` is on main, absent = off.
- **Kit:** `C:\tmp\w1208_onenum\kit_env_onenum.sh check|apply|restore <backup>`. It prints only this key and is
  idempotent; `apply` backs the file up first.
  - Self-test `kit_selftest_onenum.sh` PASSED 11-24 11:2x AM CST on a dummy file: apply appends, a repeat is
    idempotent, mode 600 kept, restore exact, real file untouched.
  - A read-only `check` on the real file: key ABSENT in the file and in all three role envs.
- **Droppable:** a failed step restores its own backup and drops this change only, never the batch.
- **Betting change: yes** (classed conservatively; see above). Register it at the load with
  `betting_change.py add --kind yes --loaded-at <role pickup UTC>`.
- **Reader:** `C:\tmp\w1208_onenum\read_after_load.py`, read-only. Exit codes: 0 = MET, 1 = violated, 2 = blind,
  3 = NOT LOADED (no card stamped `model_probability_basis=model_edge`).
  - BEFORE reading, 2026-11-24 17:29:22Z on the 16:53:59Z build: 3,906 pregame cards; Win%-vs-edge misses 1,678;
    opposite sides 46; stated board numbers != Win% 0 of 583; stamped 0, so NOT LOADED (rc 3).
    Saved: `C:\tmp\w1208_onenum\reading_before_1124.json`.
  - Predicted after the load: stamped > 0; P1 (stamped) = P2 = P3 = 0. Unstamped misses only on rows railed at 0/1.
- **Reading owner:** lane `surface-consistency-oversight`, or whoever runs the batch, on the first board build after
  the up.

**#863 QUEUED FOR THE 12-08 WINDOW `[2026-11-27 ~1:00 PM CST]`.** The user was asked "Which NBA fix should I build
for the 12-08 window: the age limit (switched off until then), or the two pre-tip pulls?" and answered "Age limit,
off". Code `f69f7b6c8` + `cc516f4b0` on main, absent = off. Nothing loads it automatically.
- **Line:** ONE GLOBAL `SYNDICATE_NBA_PREGAME_REUSE_MAX_AGE_SECONDS=4500` in `~/syndicate-prod/local_production.env`.
  Both workers' odds sweeps run `refresh_nba_oddsapi_props.py` (NBA launches appear in both role logs); only that
  script reads the key.
  Env is built only at `up`, so it rides the window's drained full down/up.
- **What it does:** both reuse checks refuse a snapshot older than 75 min while a game is to start within 12 h, so
  the sweep refetches every ~90 min before the first tip (worst case ~105 min old, under the grid's 2 h rule). In
  play the in-play lane already keeps the snapshot fresh (11-25: late games captured 1-32 min before their tips).
- **Dry run on the fleet's real snapshot** (18:26Z 11-27, read-only, switch set in-process only): off reuses; on
  4500 declines (age 6,351 s, first tip in 5.7 h).
- **Kit:** `C:\tmp\w1208_nba863\kit_env_nba863.sh check|apply|restore <backup>`, prints only this key, idempotent,
  backs up first. Self-test `kit_selftest_nba863.sh` PASSED 11-27 on a dummy file; `check` on the real file: key
  ABSENT in the file and in all three role envs.
- **Droppable:** a failed step restores its own backup and drops this change only.
- **Betting change: yes** (it changes which NBA rows the board can pick). Register it at the load with
  `betting_change.py add --kind yes --loaded-at <the later of the two workers' pickup UTC>`.
- **Reader:** `C:\tmp\w1208_nba863\read_after_load.py <day>`, read-only, on an NBA game day before the first tip and
  >= 110 min after a scheduled pull. Exit 0 = MET, 1 = violated, 2 = blind / too soon, 3 = NOT LOADED (no
  `PREGAME_REUSE_DECLINED` in the day's job log).
  - BEFORE (switch absent), read 19:00:18Z 11-27, 140 min after the 10:40 AM CST pull: reader rc 3 NOT LOADED (0 decline lines in the job log); snapshot 516 s old, because an injury-change re-sim refetched at 18:51Z (1 off-schedule capture); board (written 18:59:06Z) NBA pregame 4 stale of 1012, 165 Suggested.
  - Predicted after the load: decline lines > 0; snapshot <= 6,600 s old at every discriminating read; NBA pregame
    stale share < 20%. Falsified by a discriminating read with the snapshot > 6,600 s old and a game to start
    within 12 h.
- **Cost (estimate):** ~6 more full NBA runs a game day, ~+75k OddsAPI credits a month against ~288k headroom.
- **Reading owner:** lane `surface-consistency-oversight`, or whoever runs the batch, on the first NBA game day
  after the up.

**Post-window `plan_vs_orders`** (15:54Z, for lane `live-ev-floor-off`; not judged here):
- 11 live orders today, none of their position keys in the current 19-position plan.
- 9 join a board row, and 1 of the 9 is Suggested NOW. Today's orders include ones placed before the 08:30Z up,
  under the floor.
- `side_picked_by` is `price_shopping` on all 11.
- `venue_price_hidden`: 5 of 9.
- This crude join cannot say whether each order was Suggested when placed. That reading is CHANGE P's, with
  `kit_after_up_floor.sh`.

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

## Step 1c -- the cheat sheet takes its pick, fee and model number from the board `[built 2026-11-24, user "Yes, do 1c"; display only; NOT LOADED]`

**Measured first** (fleet, read-only, same instant). Rows: the 20:10:58Z all-sport board read (1,081 pregame rows a
sheet builds from) and a 20:26:41-20:27:02Z per-sport read made the way the builder reads (2,761). Each row was run
through the sheet's own `price_check` / `game_line_check`. Probes: `C:\tmp\scc_oversight_d5aa\probe_1c_sheet_vs_board.py`,
`probe_1c_b.py`.
- **Fair:** the board's own `quote.fair_probability` on every row.
- **Net EV:** the sheet's equals the board's `score_v2.ev_net_pct` on 1,081 of 1,081. The board's EV COLUMN is gross
  (`ev_pct`), so 359 exchange rows (Kalshi 181, Novig 83, Polymarket 53, ProphetX 42) show two EVs under one label.
  That is the board's display, not the sheet's maths (D4; left for step 1e).
- **So Reading 1's "same book, same price, different EV" was age plus the fee, not a second fair.** The sheets read at
  20:11Z were built at 17:30-17:35Z.
- **The pick label differed.** The sheet's own "value" (net EV >= 2, not one-sided, not above 10) fell on rows the board
  refused to suggest:
  - 20:11Z: 12 (6 `suspect_stale_quote`, 6 `single_book_fair`);
  - 20:27Z: 14 (5 stale, 9 one-book).
  Every Suggested row read "value". The sheet's `suggested` field is already a copy of the board's at build time.
- **Model number:** props showed the card's Win% except on blank cards. Game lines showed `model_probability_cal`, which
  differed from the card's Win% by > 0.5 pp on 305 of 614 lines (20:11Z).

**The change** (`syndicate/features/shared/cheat_sheets.py`, rules v4; loans from lanes `cheat-sheets` and
`cheat-sheet-section-optimization`, both owners gone):
- `price_check` / `game_line_check`:
  - "value" is the board's Suggested pick wherever the board judged the row (`board_judgement`).
  - A refused row that clears the price says why: "... but the board does not suggest it: its fair price comes from one
    book only". A stale quote reads "Check price" (`suspect_price`): "... the board flags the quote as stale".
  - One-sided and above-10% still win over the board.
- Rows the board never judged keep the price rule. These are the builder's `rebuilt` rows for games that started first.
- **Fee:** the board's `score_v2.fee_per_contract`; the sheet's own lookup only without it.
- **Model number:** the card's (`layer2_row_context.board_model_probability`), so the sheet follows the 12-08
  one-number switch with the card.
  - Where the card is blank, the sheet keeps its own number. Measured 20:27Z: the card is blank on 104 one-sided "yes"
    props (NFL anytime TD 73, soccer scorers 31), because `_model_prob_for_side` cannot place "yes" against a projection
    framed "over".
- `SECTION_RULES` 3 -> 4 marks the series. Verdicts are stored per row, so past sheets keep theirs. The load day is mixed:
  rows kept from earlier builds carry v3 verdicts under a v4 stamp, as on 11-13.
- The page's Value and game-line Value blurbs say what v4 means (`cheat_sheets.html`).
- Play cards and SGP legs that read "value" inherit it. Nothing that places or sizes money reads a sheet (checked by
  `git grep`).

**Pre-registered hypothesis** (lanes.md, before building): value-not-Suggested 0, Suggested-not-value 0, every EV
unchanged on a judged row. **FALSIFIED AS WRITTEN on one clause**, replay `C:\tmp\scc_oversight_d5aa\replay_1c.py`
(old = origin/main's module):

| read | rows | value-not-Suggested old -> new | Suggested-not-value | EV changed | fair changed |
|---|---|---|---|---|---|
| 20:11Z | 1,081 | 12 -> 0 | 0 -> 0 | 1 | 0 |
| 20:27Z | 2,761 | 14 -> 0 | 0 -> 0 | 1 | 0 |

- The one EV is an NFL receptions line at Kalshi -144: old -0.46, new -0.47. The board's own net EV is -0.465, so both
  are roundings of it. The board publishes its fee to 6 decimals, and that tips the second decimal. No verdict moves.
- Model number at 20:27Z:
  - props: 1,569 of 1,586 within 0.5 pp, 17 none either way, 0 lost;
  - game lines: 379 moved > 0.5 pp to the card's Win%, 22 gained a number, 128 none either way.

**Tests.** `tests/test_cheat_sheet_board_judgement.py`, 17 new, including reachability: the model number moves with the
one-number switch, off != on. 249 pass across the 21 cheat-sheet, play-card, one-number and instrument suites. One old
assert updated: `test_cheat_sheet_section_rules_v2.py`, `SECTION_RULES == 4`. The page script passes `node --check`.

**Lead (not followed):** the board card shows no Win% on one-sided "yes" props (104 at 20:27Z), though
`model_prob_over` is P(yes) there. That is `layer2_board._model_prob_for_side`, the board owner's file.

**How it loads.** The builder is a script: a fleet ff loads it at the next scheduled sheet build, and the blurbs reach web
at a `reload-web` or a recycle. An ff ships ALL of main. When to load it is the user's call.
- On main at `6ca19e36c`. The fleet is at `76a006f45`, 45 commits behind. An ff now would also ship other lanes' work:
  `gunicorn.conf.py`; the ops dashboards blueprint, whose lane `ops-dashboards-hub` recorded the user's "wait for that
  lane"; and `ncaaf/live_margin_anchor.py`. So this step does not ff the fleet itself.
- **Ride-along class for whoever runs the next ff:** display only, betting change NO. Nothing that places or sizes money
  reads a cheat sheet.
- **Reader:** `C:\tmp\scc_oversight_d5aa\read_1c_after_load.py <day>`, read-only, the served sheets. It counts rows whose
  verdict is "value" while their own `suggested` (stamped by the same build) is False, so it has no age confound.
  Exit codes: 0 MET, 1 violated, 2 blind, 3 not loaded (no v4 sheet).
  - BEFORE, 2026-11-24 20:34:13Z, sheets built 17:30-17:35Z, all rules 3: value-not-suggested 4 of 723 rows (NBA 2,
    NCAAB 2; NHL, NCAAF and soccer 0; no NFL sheet on a Tuesday); suggested-not-value 0. rc 3.
    Saved: `C:\tmp\scc_oversight_d5aa\reading_1c_before_1124.txt`.
  - Predicted: on the first full day of v4 sheets, every sheet `section_rules` 4 and value-not-suggested 0. The load
    day itself is mixed, because rows kept from earlier builds keep their v3 verdicts.

## Step 1e -- the board shows the EV it judges, and the Kalshi / Polymarket prices `[built 2026-11-26, user "Start"; display only; LOADED 2026-11-27 04:18:28Z, MET]`

**Measured first** (the fleet's 00:23:40Z 11-27 shortlist, read 00:29:02Z; `C:\tmp\scc_oversight_d5aa\probe_1e_*.py`). D4 and
the "venue price beside the sportsbook best" half of the target:
- **EV column.** 1,929 pregame rows; the page showed the GROSS `ev_pct` (`ev_vs_fair_pct`) on all of them. On 305 the best
  book charges a fee: Novig 104, Kalshi 101, ProphetX 59, Polymarket 41. `_suggested_reasons` judges those on
  `score_v2.ev_net_pct` (`layer2_board.py:3709-3716`). The card carried no `score_v2` and no net number, so the page could
  not show the number the flag judges.
- **Venue prices.** The live book buys only at Kalshi and Polymarket. 355 pregame rows carry a Kalshi price in their own
  quote grid (the best book on 101) and 241 a Polymarket price (best on 41). The page showed none of them: `book_prices`
  is stripped from the wire (`blueprints/intelligence.py` `_UNCONSUMED_QUOTE_FIELDS`), and the Best price cell names only
  the best book.
- Priced by the purchaser's own `venue_scope.scope_rows_to_venue` (aggregator path): Kalshi 354 scoped + 1
  `venue_ev_implausible`, net > 0 on 13, net >= +2 on 0; Polymarket 241 scoped, net > 0 on 8, >= +2 on 0.
  11 of 46 Suggested pregame rows carry a venue price; 4 of those clear 0 net there and 0 clear +2.
- On 18 Kalshi rows and 4 Polymarket rows the venue's raw price beats the board's best, and the board still names a
  sportsbook. All 22 were refused (`ev_below_min` 15, both reasons 6, `ev_net_of_fee_below_min` alone 1), so none is a
  hidden pick. Why the board names the sportsbook on them is NOT traced here.
- The live book today (`/api/portfolio/live?date=2026-11-26`, 00:31Z): 4 live orders, all Kalshi. Too few to join.

**The change** (`ad05b4ab0`):
- `layer2_board._layer2_fee_and_venue_columns`, spread into each card by `layer2_rows_to_board_cards`:
  - `ev_net_pct`, `fee_basis`, `fee_per_contract`, `fee_is_upper_bound`: COPIED from `score_v2`, never recomputed.
  - `venue_prices`: for Kalshi and Polymarket, where the row's quote grid prices them and neither is the best book, the
    output of `scope_rows_to_venue([row], venue)`: price, gross EV, net EV, fee, fee basis, `price_source`
    ("aggregator"). A refused price keeps its reason (`refused`).
  - The venue that IS the best book is left out: its price is the Best price and its net EV is the EV column's. The two
    can differ, so a second number for one price would be a new inconsistency. The board's score reads the side's own
    Kalshi ticker; the purchaser's function has none here, and the board passes no phase for Novig (D3).
  - The row is never written, and `_layer2_board_columns` (which `portfolio_commit` calls) is unchanged. Nothing that
    places, sizes, ranks or flags a bet reads the new fields: **betting change NO**.
- `templates/intelligence.html`:
  - The EV column shows and sorts on `evShownValue`: the net number where a fee is charged, else the gross.
  - The EV cell says "net of fee · +x% gross", with the fee in the tooltip. A card on an exchange without the net
    number (built before the load, or an in-play overlay card) says "gross, before fee".
  - The Best price cell lists "KALSHI +105 · -2.6% net" per venue, or "· not bought" with the reason.
  - The top rail shows "+x% net", and the agree tab filters on the same number.
  - The calibrated-sim tooltip of lane `cell-calibration-847` in `renderBlotterEv` is byte-identical.
- What it does NOT say: the live plan's resolver reads the venue's own feed through its own join
  (`portfolio_commit._venue_price_resolver`) and may hold a fresher or differently matched quote. Each venue line's tooltip
  says so. Showing that number needs the plan's priced rows persisted for every line, not only its positions.

**Replay** (`C:\tmp\scc_oversight_d5aa\replay_1e.py`, rc 0, HELD): the saved 2,000 rows -> the new card builder -> the
page's own `renderBlotterEv` / `renderBlotterBook` / helpers extracted from the edited template and run in node.
- Shown EV == the gate's number on 319 of 319 fee rows (305 pregame + 14 live) and == gross on 1,681 of 1,681 others.
- Venue entries == `scope_rows_to_venue`'s on 480 of 480 (Kalshi 273, Polymarket 207; 6 refused), and that is every row
  that prices a non-best venue.
- 0 render errors; "net of fee" on 319; 474 venue lines + 6 "not bought"; rows unchanged.
- One instrument artifact on the way: Python's `round(-0.25, 1)` is -0.2 and JS `toFixed(1)` is -0.3. The compare now
  uses the unrounded value.
- Reachability: the served payload carries card-level fields through (`book_confidence`, set only by the card builder,
  on 5,982 of 5,982 served items, 00:43:01Z). Cost: +123 bytes per card, about 0.7 MB per list on the 97 MB unslimmed
  response.
- Tests: 12 new (`tests/test_layer2_venue_prices.py`); 1,355 pass across the card builder, query payload and board UI
  suites. The board JS tests give main's results on both line endings (the CRLF checkout breaks one test's LF-only regex
  on main too).

**Reader** `C:\tmp\scc_oversight_d5aa\read_1e_after_load.py` (served payload). BEFORE, 00:48:11Z: rc 3, 5,954 cards, 353
pregame exchange-priced cards without a net number, 0 venue lines. Predicted after both loads:
`exchange_card_without_net` 353 -> 0 (once each date's shortlist is rebuilt), `cards_with_venue_line` 0 -> > 0,
`venue_entry_is_best_book` 0, `venue_net_above_gross` 0.

**Loaded and MET** (user "Load both now"; deploys.md 2026-11-27 04:18:28Z).
- **How it loaded:**
  - Fleet ff to `30b2be76e` 03:56:22Z, then reload-web 03:56:28Z.
  - The board builds ran back to back (3-11 s between a save and the next build), so the after-a-save window
    never opened. A drain (~04:04Z) let the in-flight build save at 04:15:13Z.
  - Preflight refresh-worker CLEAR 04:18:22Z. Then a TERM of the board child only (pid 535 -> 256375, ready
    04:18:34Z) and the undrain at 04:18:47Z. The parent's sims and jobs were not touched.
- **Reader 04:31:00Z, rc 0:**
  - Exchange cards without a net number: 314 -> 0.
  - The net field is on 5,323 of 5,433 cards.
  - Cards with a venue line: 0 -> 375 (Kalshi 273, Polymarket 233 entries).
  - 0 entries name the best book, 0 have net above gross, 0 are unpriced.
  - 10 of 60 Suggested pregame cards carry a venue line, and 0 of them clear +2% net at the venue: the same
    shape as the 00:23Z measurement (11 of 46, 0).
- **Live page** (tomorrow's blotter): 60 "net of fee" cells, 127 venue lines with a net EV, 1 "not bought".
  Example: Florida State +6.5 shows NOVIG +100 with "+0.4% net of fee · +1.9% gross", then "KALSHI +100 · -1.5% net"
  and "POLYMARKET -104 · -3.4% net".
- **Build cost:** the shortlist stage took 137 s and then 94 s on the new child, against 214 s and 395 s on the old
  child the same evening. 0 `VENUE_PRICE_FAILED` lines.

## Step 1d -- the NHL and soccer pages lead with the board's pick; the sim is a labelled view `[built 2026-11-25, user "Yes, do 1d"; display only; DEPLOYED to web 2026-11-26 17:28:02Z, MET]`

**Loaded and measured** (deploys.md 2026-11-26 17:28:02Z): rc 0 at 17:28:18Z. Board pick tile not first: NHL 15 -> 0, soccer
36 -> 0. Props without a verdict 12 -> 0. Live pages showed 0 unlabelled non-board EV, 0 console errors, and 0 web-log
errors. A picks headline made of board picks was first exercised live on 11-27. Read 15:32:05Z (board written 15:25:13Z),
rc 0: the headline is the board's 6 Suggested NHL pregame picks, 0 not the board's; 12 sim cards, 0 unlabelled, 0 without a
verdict; 12 props cards, 0 without a verdict; 4 of 15 NHL games carry a Board pick tile, first on all 4; soccer 11 games, 0
unlabelled sim tiles. Saved `C:\tmp\scc_oversight_d5aa\reading_1d_after_1127.txt`. Nothing owed for 1d.

**Measured first** (fleet, read-only, 16:10:55-16:15:21Z, back to back; `C:\tmp\scc_oversight_d5aa\probe_1d_fetch.py`,
saved `probe_1d\`). Board build 16:06:33Z.
- Board: NHL pregame 645 rows, 39 Suggested, all props (assists 15, points 12, SOG 12), over 13 games; 0 game lines.
  Soccer pregame 190 rows, 6 Suggested (corners totals 5, h2h 1) over 5 games.
- `/nhl/picks`: 12 raw-sim game lines from `recommendations_sim_2026-11-25.csv` at 3.1-10.9% "EV"; 0 Suggested.
- `/nhl/cards` "Player props pulse / Top moving edges": 12 props at EV +85% to +328% (goals over 1.5 at +3000..+9000,
  one book); 0 Suggested; the 7 the board carries read EV -4.86 to +1.99 there (`single_book_fair`, `one_sided_fair`).
  Each game card also led with the sim's "Top pick" and "Official card: Top game edge" (e.g. "ML PIT | EV -12.1%").
- `/nhl/api/cards` "Best playable angles" and `/soccer/cards` "Best 1X2 edge": the sim's; no tile named the board.

**The change** (display only; web routes, so the worker's chip contexts are untouched):
- `syndicate/features/shared/board_game_picks.py` (NEW): the board's pregame rows for one sport and Central day, read with
  `read_layer2_shortlist` (the plain read Ask and the board API make). Only a compact copy is kept, 60 s per process.
  - Picks are the board's `suggested` rows, ordered by the board's own score, then EV: Ask's `_board_pick_rank_key`.
  - A page's game is found by its exact pair, else by ONE side when exactly one board game that day fits. 3 of 13
    soccer games missed on the pair ("Slavia Prague" / "Slavia Praha", "Sporting CP" / "Sporting Lisbon",
    "Internazionale" / "Inter Milan"); with the fallback, 13 of 13 resolve.
  - One verdict sentence per line, in the cheat sheet's refusal words (`cheat_sheets.board_refusal_text`). The EV is
    net of fee where the board has it, and says so. An absent line names the shortlist's floor ("lists lines at EV -2%
    or better at the best price").
- `/nhl/picks` and `/nhl/api/picks`:
  - `rank_cards` (the headline, which the home page's NHL betting card also reads) are the board's picks;
  - `card_sections` add the sim's snapshot, each card badged "Sim EV", with the board's verdict on the same line.
- `/nhl/cards`:
  - a "The board's NHL picks" strip;
  - a Board pick tile and callout on every game;
  - the props pulse is now "Raw sim: not the board's picks", with "Sim EV" and the board's verdict on each card;
  - "Official"/"Top pick"/"Top game edge" now read "Sim card"/"Sim's top pick"/"Sim's top game edge";
  - `_prop_reason_summary` now reads "Sim's case ... Sim win rate ... Sim EV".
- `/nhl/api/cards`, `/nhl/cards?client=board` and the four soccer cards routes: a "Board pick" tile first
  (`attach_board_picks`). Soccer's own tiles say "Sim ·"; the NHL panel is "Sim angles: not the board's picks".

**Pre-registered hypothesis** (lanes.md, before building): every headlined pick is a board Suggested row or carries a
"sim" label; unlabelled non-board picks 0. **HELD** on the replay of the 16:10Z reads (`C:\tmp\scc_oversight_d5aa\replay_1d.py`):

| surface | result |
|---|---|
| `/nhl/picks` | headline 12 of 12 Suggested (of 39); sim 12 of 12 labelled, each with a verdict (absent 11, refused 1) |
| props pulse | 12 of 12 carry the board's verdict; 0 Suggested (7 refused, 5 absent) |
| NHL bundle | 14 of 14 page games resolved; 13 carry a board pick |
| `/nhl/api/cards` | Board pick tile first on 14 of 14; all 39 picks shown across games |
| `/soccer/api/cards` | Board pick tile first on 13 of 13; all 3 picks for the day shown |

Rendered in a local harness (the worktree's code serving the saved fleet reads; `C:\tmp\scc_oversight_d5aa\harness_1d.py`):
- `/nhl/cards`: 103 EV figures, 51 inside a board element, 52 labelled "sim EV", 0 neither. 0 console errors.
- `/nhl/picks`: 12 board cards first, then 12 sim cards, all "Sim EV" with a verdict.
- Soccer was not rendered (no local soccer data): covered by the replay and the tests.

**Tests.** `tests/test_board_game_picks.py`, 21 new. They include reachability: the same sim rows with and without a board
pick give a different headline. 112 pass across the touched suites; `test_archives -k "nhl or soccer"` 55 pass. One assert
updated: `test_soccer_board_mlb_parity.py`, prop tile label "Sim · Best prop edge". `test_soccer_cards.py::test_directory_hit...`
fails in this worktree only: its branding CSV is under `data/`, which the worktree leaves out. The page script passes `node --check`.

**Seen, not changed (leads):**
- Board picks can carry a Board win% below the fair, e.g. Nichushkin over 0.5 assists: fair 28.4%, win% 27.3%,
  Suggested at +5.0% EV. The board bets the price. That is the open "model loses to the market fair" decision, not a
  display defect.
- `/nhl/cards` on the fleet shows "PUCK DROP 11/24, 6:00 PM CST" on 11-25 games. It looks like a bare date read as UTC
  midnight; not traced.

**How it loads.** Web only: an ff of `~/Syndicate`, then `reload-web` (or a recycle). The soccer tile labels and
`_prop_reason_summary` also run on refresh-worker, inside chip and home builds, as labels only. Betting change NO: nothing
that places or sizes money reads these pages.
- **Reader:** `C:\tmp\scc_oversight_d5aa\read_1d_after_load.py <day>`, read-only. rc 0 MET, 1 violated, 2 blind, 3 not loaded.
  - BEFORE, 2026-11-25 16:36:54Z: rc 3. None of the 1d fields are served; soccer sim tiles unlabelled 20.
    Saved: `C:\tmp\scc_oversight_d5aa\reading_1d_before_1125.txt`.
  - Predicted after the load: rc 0. The NHL picks headline is all board; sim cards are labelled with verdicts; every props
    card has a verdict; the bundle board is ok; the Board pick tile is first on every NHL and soccer game; soccer sim tiles
    are unlabelled 0.

## Reading 5 -- the instrument after steps 1a-1e `[2026-11-27 15:29:22Z-15:33Z, fleet, read-only]`

`scripts/surface_consistency_check.py` (exit 1), then a split of what is left
(scratchpad `probe_resid.py`, read 15:30:58Z). The board was written 15:25:13Z; the six cheat sheets were generated
13:30:23-13:35:36Z, about 2 h earlier.

| check | 11-23 (Reading 2) | 11-27 |
|---|---|---|
| `same_price_ev:cheat` | 35 of 235 | 25 of 253 |
| `pick_flag:layer2_vs_cheat` | 42 of 296 (both flag 4 of 44) | 6 of 321 (both flag 36 of 37) |
| `ask_headline:all` | 5 of 5 | 0 of 5 |
| `ask_headline:nba` | 5 of 5 | 0 of 5 |
| `sim_attribution:ask_cards` | 2 of 15 | 0 of 13 |
| `plan_vs_orders` | 33 of 33 | 1 of 2 |
| `venue_price_hidden` | 12 of 16 | 0 of 2 |
| `sport_card_bias:nhl_away_ml` | 1 of 7 (mean +4.11 pp) | 0 of 15 (mean +0.94 pp) |

**What is left on the cheat sheet is the instrument and the sheet's age, not a rule difference.**
- `same_price_ev`, 25 over:
  - 10 are the fee basis. The check reads the board's GROSS `ev_pct` against the sheet's NET `ev_market`. On all 10
    the board's own `ev_net_pct` is within 0.5 pt of the sheet (e.g. Polymarket total over 57.5 at +104: gross +1.43,
    net -2.04, sheet -2.04). This is a defect in the check.
  - 13 are a fair that moved after the sheet was published (more than 0.5 pp; up to 3.2 pp, e.g. Bo Nix rushing attempts
    under 4.5 at draftkings -149: fair 0.568 at 13:30Z, 0.600 at 15:25Z).
  - 2 looked like a rule difference but are fair moves too: below 0.5 pp absolute, at prices where that is about 1 pt
    of EV (Kalshi +9900, fair 0.0096 -> 0.0097; Kalshi +113, fair 0.4750 -> 0.4797).
  - So the 11-23 note "age cannot do that: the input price is identical" was wrong. The fair is a consensus over
    every book, so it moves when other books move, at an unchanged price.
- `pick_flag`, 6 over: 3 fair moved, 2 the best book or price changed since the sheet, 1 the same price and EV within
  0.3 pt (betrivers +112, board Suggested now, sheet not). The last is probably the flag's own age (Suggested also
  depends on rank and caps); not proven without the 13:30Z board.
- **Owed in the instrument:** compare the board's `ev_net_pct` where it carries one, and report a pair whose fair or
  best price moved since the sheet's `generated_at` as age, not as a disagreement. DONE 11-27, Reading 6.

**`plan_vs_orders` is too small to read.** 11-27 to 15:29Z: 2 live orders (both Kalshi, both board Suggested), 1 not in
the 11-position plan. 11-26 (read the same morning): 2 live orders, both not in the 10-position plan, 1 on the board, 0
Suggested. 11-23 had 33. Volume belongs to `portfolio-monitor`; this lane only says the plan and the book still differ
on the few orders there are.

**Not covered by the instrument:** the per-sport pages other than NHL (NBA, NCAAF, NFL, NCAAB; Reading 1 item 6), the
rail (age-confounded, Reading 1 item 7), and Layer 1 beyond the NHL moneyline.

## Reading 6 -- the instrument fixed `[2026-11-27 16:22:49Z-16:23:48Z, fleet, read-only; user "Fix the check"]`

**The change** (`scripts/surface_consistency_check.py`, tooling only: no role runs it, nothing to deploy):
- `same_price_ev` compares the EV the board's Suggested flag judges: `score_v2.ev_net_pct` where the row carries it,
  else `ev_pct`. The sheet's EV is moved to the board's CURRENT fair with the sheet's own formula
  (`cheat_sheets.ev_pct`, the board's `fee_per_contract`). A pair still more than 0.5 pt apart differs on the rule and
  is counted; a pair inside 0.5 only after that move is `fair_moved`, reported and not counted.
- `pick_flag` (renamed `pick_flag:cheat_vs_board`) checks inside the sheet. The builder copies the board's flag at
  publish (`build_cheat_sheets`, `"suggested": bool(r.get("suggested"))`), and the v4 verdict is that pick. So the
  sheet's `suggested` must equal verdict == "value", on every row of a game the board judged (rebuilt games keep the
  price rule and are skipped). A board flag that changed since the sheet is `changed_since_sheet`, reported and not
  counted: without the board build the sheet read, a change cannot be told from an error.
- Measured before the change, 15:30Z: 41 + 1 of 42 sheet picks carry verdict "value", and 0 rows disagree.
- Tests: 16 pass (`tests/test_surface_consistency_check.py`, 7 new: net vs gross, a moved fair read as age and a
  rule gap as bad, the fee formula at Kalshi +9900, the sheet refusing the board's pick, a board change since the
  sheet, a rebuilt game). Each has a case that must pass and one that must fail.

**The reading, 16:22:49Z** (board written 16:21:51Z; sheets generated 13:30:23-13:35:36Z), exit 1:

| check | result | note |
|---|---|---|
| `same_price_ev:cheat` | 0 of 225 | 14 fair moves; after the move all 14 agree within 0.01 pt |
| `pick_flag:cheat_vs_board` | 0 of 873 | 42 picks; 292 rows on the board now, 37 changed since the sheet |
| `ask_headline:all` | 0 of 5 | 1 losing model, 4 unmeasured (reported, not judged) |
| `ask_headline:nba` | 0 of 0 | the board has 0 NBA Suggested rows now (below), so Ask's NBA headline is empty |
| `sim_attribution:ask_cards` | 0 of 13 | |
| `plan_vs_orders` | 2 of 3 | 13 plan positions; 3 live orders, all Kalshi, 2 on the board and Suggested |
| `venue_price_hidden` | 1 of 2 | Kalshi +117 bought; the board's best is prophetx +114, and its grid has Kalshi at +108 |
| `sport_card_bias:nhl_away_ml` | 0 of 15 | mean +0.85 pp |

**What the 37 changes are** (16:23:48Z, the board's `suggested_reasons` on each): 31 NBA rows the board dropped since
7:30 AM CST, plus 2 NHL dropped and 4 added (NCAAB 1, NFL 2, NCAAF 1). Reasons on the dropped rows:
`suspect_stale_quote` 19, `single_book_fair` 12, `ev_below_min` 4. The board's NBA pregame board now has **0 Suggested
of 627**, and 582 carry `suspect_stale_quote`. The NBA cheat sheet still shows its 7:30 AM picks: by design the
sheet's picks are frozen, so a reader of the sheet sees NBA picks the board no longer makes. Whether the stale flag is
right is the 11-23 lead (1,100 of 1,128 NBA lines stale at 1:30 PM CT on game day), not followed here.

**The one order priced better than the board** is the 1e "not verified" item, now seen once. The live book paid
Kalshi +117 where the board's grid holds Kalshi at +108 and its best is prophetx +114 (order EV +5.15, board +4.18).
The live book quotes the venue's own feed, the board the grid. One order cannot say how often or how stale; the
order's placement time was not read.

## Reading 7 -- why the NBA board flags nearly every line stale `[2026-11-27 16:23Z-16:49Z, fleet, read-only; user "NBA stale quotes"]`

**Answer: the quotes really are old. The flag is right; the capture is the defect.** Every NBA sportsbook quote on the
fleet came from ONE capture, the scheduled 6:40 AM CST NBA pull (12:40:07Z). Only Kalshi was fresh (polled every 30 s).
Hypotheses (lane line `b1407a54c`, written before the read): H1 EXONERATED as the cause (its branch fired on 1,256 of
22,958 stale cells), H2 is the branch that fires, H3 is the cause.

**The chain, earliest stage first:**
1. **Capture (the defect).** The regular odds sweep launched NBA 34 times on 11-27 by 16:32Z, about every 30 min, and
   fetched sportsbook quotes 0 times. `refresh_nba_oddsapi_props.py` `_existing_refresh_state` (:3373) and
   `_existing_artifact_bundle_state` (:3431) accept `input_hash`, never read it, and carry no age bound, so once the
   day's snapshot files exist every sweep reuses them. This is the defect `#345` (hash) and `#383` (age bound) fixed for
   WNBA only (`refresh_wnba_oddsapi_props.py` :5156, :5328). The NBA copy got neither.
   - `odds_nba_player_props_2026-11-27.csv` last written 12:40:07Z; the day's props job log last written 12:40:43Z (the
     reuse path logs nothing). Newest `captured_at` in the NBA quote log: 12:40:07Z for all 10 sportsbooks, Kalshi
     16:23:03Z.
   - The only refetches are the forced pulls (`nba_gameday_props_pull.py`; Windows task SyndicateNbaGamedayProps at
     6:40 AM, 10:40 AM and 2:40 PM CST on a game day, SyndicateNbaPreviewProps at 12:40 PM for the next day). They were
     built 10-19 for the cheat-sheet builds, and the script's docstring names this same reuse defect.
   - Instrument caveat (lead, not followed): `ODDS_SWEEP_OUTCOME wrote=True` read 3 times (06:02, 12:40, 16:10Z), but
     the sidecar it watches (`book_quotes/<day>.state.json`) is also written by Kalshi's appends (mtime 16:23:03Z with no
     sweep). So `wrote=True` cannot tell a sportsbook capture from a Kalshi append. Only 12:40Z was a sportsbook capture.
2. **Grid** (`book_grid.py`, the 10-16 own-capture rule). A quote is stale when its book's whole feed is more than 2 h
   (`_FEED_DEAD_PREGAME_SECONDS`) behind the latest look at the game. Kalshi looks every 30 s, so the sportsbooks' feed
   lag was 13,375 s (3 h 43 m). Served grid 16:28Z (first 2,000 of 5,667 rows): 21,702 stale cells by the dead-feed
   branch and 1,256 by own-capture lag; every sportsbook cell stale; best side `suspect_stale` on 2,481 of 2,557 prop
   sides and 1,400 of 1,400 game sides. NHL at the same time: sportsbooks seen 1,630 s ago, feed lag 970-1,349 s, best
   side stale on 62 of 3,407.
3. **Board.** `layer2_board._suggested_reasons` refuses `suspect_stale_quote`: NBA pregame 0 Suggested of 627 (16:23Z).
   The Kalshi-only sides that stay fresh are `single_book_fair`.
4. **Surfaces.** Ask's NBA headline was empty, the NBA cheat sheet kept its 7:30 AM picks (31 of which the board had
   dropped), and the plan held no NBA.

**Tested on the 10:40 AM CST pull (a same-day natural experiment).** Predicted: once the board reads the new snapshot,
NBA stale goes to near 0 and Suggested goes above 0. Snapshot rewritten 16:40:09Z (67 s, 11 of 11 games).
- The board written 16:40:14Z was built from a grid generated 16:39:57Z, before the pull: still 0 Suggested of 654, 613
  stale.
- First board built after it (written 16:45:52Z, read 16:49:01Z): **NBA pregame 881 rows, 113 Suggested, 3 stale.** HELD.
- The served `/api/board/book-grid` artifact was still the 16:39:57Z one at 16:49Z; the board builds its own grid.

**When it bites.** Fresh for 2 h after each pull, then all-stale until the next. On 11-27 that is 8:40-10:40 AM,
12:40-2:40 PM, and 4:40 PM CST to tip (11 games, tips in the 6, 7 and 8 PM CST hours). So the board can never pick an
NBA pregame bet in the last hours before tip. 11-23's lead (1,100 of 1,128 stale at 1:30 PM CT) is the 12:40-2:40
window. Pre-registered for today: all-stale again from about 18:40Z (12:40 PM CST) to the 20:40Z pull, and from about
22:40Z (4:40 PM CST) to tip.

**Cost of a fix.** The 10:40 pull cost 605 credits (24 calls) for 11 games, about 55 a game: NBA credits 659,353 at
16:37:00Z, 659,958 at 16:44:31Z, unchanged at 16:49:02Z. OddsAPI's 30-day projection read 4,712,207 against the 5M cap
(16:37Z), so the headroom is about 288k a month; NBA is 659,353 of 6,729,420 credits since 10-01 (9.8%). Estimates
below take about 225 NBA games a month.
- **Age bound** (WNBA's `#383` applied to NBA), set under the board's 2 h rule with room for the 30-min sweep step (about
  75 min): about 7-8 pulls a game day instead of 3, so roughly +60k credits a month. No all-stale window.
- **Two more scheduled pulls before tip** (4:40 and 5:40 PM CST): roughly +25k a month. The two midday windows stay
  stale.
- Either is a **betting change**: it changes which NBA rows can be Suggested, so the plan and the live book. It lands
  default-off and loads in a betting-change window (12-08), or the user decides otherwise.
- Whether NBA picks earn anything is not measured here (the 11-27 NBA lean forward read MISSED; nothing has cleared the
  #738 bar). Some of the 113 are long-price alt spreads (fanatics +310, +430).

### Reading 7 addendum `[2026-11-27 19:00Z-19:10Z, fleet, read-only]`

**CORRECTION `[2026-11-27 ~1:10 PM CST]`: a SECOND refetch path exists.** A lineup/injury-change re-sim (`LINEUP_INJURY_CHANGE_RESIM_TRIGGERED`, live-odds-worker's `live_refresh_loop`) forces an NBA live-phase run whose in-play-only fetch takes every not-started game as due (`upcoming_events_due`, IN_PLAY_PROPS pass=full) and then runs the full pipeline. It matched 5 of 5 off-schedule NBA captures: 11-25 18:20, 20:22, 21:24, 22:02Z and 11-27 18:51:34Z (job log). So the stale windows are the gaps between pulls with NO injury trigger, irregular by day: 11-27 8:40-10:40 AM CST was one (0 Suggested of 627 at 16:23Z); 11-25 had triggers all afternoon. Reading 7's "only the forced pulls refetch" was wrong for afternoons. The pre-registered 12:40 PM CST window lasted 11 min (18:40-18:51Z; no board built inside it was read): at 19:00Z the snapshot was 516 s old and the board (18:59:06Z) had 4 stale of 1,012 NBA pregame rows, 165 Suggested. The age limit still bounds every gap; on trigger-heavy days it fires less, so the cost estimate is an upper bound.

## Reading 8 -- the per-sport pages other than NHL and soccer `[2026-11-27 20:28:43Z-20:31:32Z, fleet, read-only; user "What's next"]`

The board was written 20:28:25Z. Probes: `C:\tmp\scc_oversight_d5aa\sport_pages_peek*.py`, `nfl_props_vs_board.py` +
`nfl_props_join.py` (join on folded player + side + line + stat), `picks_vs_board.py`.

- **NFL props (`/nfl/api/props`, week 12): the largest gap left.**
  - 2,189 cards ranked by "edge": the season-to-date rate model minus the price's single-sided implied probability,
    so the vig is left in (`syndicate/features/nfl/props.py` `build_nfl_props_page_context`). Top 12 at +43.4% to +50.9%.
  - Against the board: top 12, 8 on the board, 0 Suggested; top 50, 27 on the board, 0 Suggested; all 2,189, 789 on
    the board, 7 Suggested.
  - The board's EV on the top-12 cards it carries is -6.5 to +0.5. Example: Simi Fehoko receptions under 1.5 at +140,
    page +50.9% edge, board -1.47 (`ev_below_min`, `ev_net_of_fee_below_min`).
  - The board's 7 Suggested NFL pregame props (+2.2 to +5.2 EV) sit at page ranks 205, 562, 577, 621, 1037, 1073 and
    1664. No card names the board's verdict.
- **NFL picks (`/nfl/api/picks`):** 12 SmartSim win-probability cards, one a game ("82.7% win prob"), with no price or
  EV. The board's 7 NFL picks are all props, so none appears. Not a conflicting claim: the page does not show the
  board's picks.
- **NCAAF picks (`/ncaaf/api/picks`):** 24 cards. 12 are anytime-TD "yes" ranked by points better than the vigged
  consensus (labelled "price shopping, not model, not EV"); 12 are model win probabilities. The board's 12 NCAAF
  Suggested (4 spreads, 4 totals, 2 receptions, 1 passing TDs, 1 h2h; +3.7 to +5.2 EV) are not on the page.
- **NBA picks and props (`/nba/api/picks`, `/nba/api/props`): empty.** They render only a saved
  `recommendations_slate_<day>.json` / `props_recommendations_top_by_game_<day>.json`, absent for 11-27. The NBA cards
  (11 games) carry no recommendations (`game_market_recommendations` 0 and every `*_ev` 0.0): a market snapshot and the
  sim's leaders. The board's NBA Suggested set (165 at 19:00Z, Reading 7 addendum) reaches none of these pages.
- **NCAAB:** `/ncaab/api/cards` only (49 games, market tiles, no picks). Nothing to disagree with.

**What follows:** a step 1f on 1d's pattern. The NFL props page leads with the board's Suggested NFL props, and every
rate card carries the board's verdict and says its edge is against the vigged price. The NFL, NCAAF and NBA picks
pages lead with the board's picks for the sport. Display only, web routes only; loads with an ff + `reload-web`;
betting change no. The user's call.

## Step 1f -- the NFL props page and the NFL / NCAAF / NBA picks pages lead with the board's picks `[built 2026-11-27, user "Yes, build 1f"; display only; NOT LOADED]`

**What changed** (web routes only; nothing is recomputed, every number is the board's row):
- `board_game_picks.py`:
  - `upcoming_view(sport)`: every pregame line of the sport in today's shortlist, whatever day. The NFL and NCAAF
    pages are weekly; the NFL board's rows were Sunday 11-29 and Monday 11-30.
  - `find_prop(..., away=, home=)`: an index instead of a scan per card, market names folded, the card's own game only.
  - `only_games(pairs, kind=)`.
  - `board_pick_cards` (NHL's 1d card, now shared; a weekly view names the kickoff).
  - `lead_with_board_picks(context, board, ..., off_slate=)`:
    - the board's picks become `rank_cards` and the first section;
    - the page's own cards follow under a label. Its own sections are kept as built, under a `page_label` divider;
    - "Board picks" leads `header_stats`;
    - a page whose week the board does not judge (a past week or season) shows no board picks and says why.
  - Labels: `spreads_alt` / `totals_alt` read as spreads and totals (the replay showed "Home -14.5" with no team);
    `player_rebounds` reads "Rebounds". Matching is unchanged.
- `nfl/props.py`:
  - each rate card is "Rate view · NFL Props" with a "Rate edge" badge, `source` "rate" and a `line_key`
    (game, player, market, side; anytime TD "over" -> the board's "yes");
  - `attach_board_verdicts` puts the board's verdict first on every card (`board_verdict`, `board_pick`);
  - the page leads with the board's Suggested PROPS for the page's own games.
- Routes:
  - `/nfl/props`, `/nfl/api/props`, `/nfl/picks`, `/nfl/api/picks` (off-slate unless latest season and
    `default_week`);
  - `/ncaaf/picks`, `/ncaaf/api/picks` (off-slate for an explicit week other than `default_week()`);
  - `/nba/picks`, `/nba/api/picks` (the day's view).

  `nba/picks.html` renders `card_sections`, as `nhl/picks.html` does since 1d. NHL's `build_board_cards` delegates to
  the shared card (its 21 tests pass unchanged).

**Replay** (read-only on the fleet host: the worktree's code over the fleet's data roots, and the board saved from the
fleet API at 21:12:59Z, built 21:11:02Z; `C:\tmp\scc_oversight_d5aa\replay_1f\`, rc 0 HELD):

| page | served now | after |
|---|---|---|
| NFL props (2026 week 12) | 2,237 rate cards, top "+55.6% edge" | 10 board prop picks (+2.2 to +5.2 EV), then 2,237 rate cards labelled |
| NFL picks | 12 SmartSim win-probability cards | 11 board picks, then the 12 under "SmartSim view: not the board's picks" |
| NCAAF picks | 24 cards (12 price-shopping) | 8 board picks, then the 24 labelled |
| NBA picks (11-27) | 0 cards (no saved slate) | 12 of the board's 167, then the empty slate's reason |

- NFL rate verdicts: 10 board pick, 827 not a pick, 1,273 line not on the board, 127 game not on the board; 0 without a
  verdict, 0 that disagree with the board row, 2,237 of 2,237 badges relabelled. Top 50: 0 board picks, 19 on the
  board.
- Cost: the NFL props build took 5.8 s; the board attach added 0.11 s.

**Tests:**
- `tests/test_board_picks_weekly_pages.py` (NEW, 19). Reachability: the headline changes with the board's picks, and
  every route calls the helper.
- 3 NFL picks tests in `tests/test_archives.py` were updated to the new layout:
  - the page's sections are found after the board section and the divider;
  - the card count is found by its label;
  - a 2025 week has no board picks.
- Against the primary tree's NFL data, 24 of the archive tests these pages touch pass, plus 153 in the other files.
- The worktree has no `data/`, so the data-backed archive tests fail there without it. One WNBA hub-link test fails
  for the same reason; it is unrelated.

**Reader** `C:\tmp\scc_oversight_d5aa\read_1f_after_load.py`. It reads the board before and after the pages, so a
build in between cannot count against them. It must:
- MET (rc 0) on the replay's pages;
- VIOLATED (rc 1) on a copy with one non-board headline card and one card without a verdict.

The BEFORE reading on the served pages was at 21:21:52Z (3:21 PM CST): rc 3 NOT LOADED (NFL props headline 2,190,
NFL picks 12, NCAAF picks 24, NBA picks 0). **Prediction after the load:** rc 0 on all four pages, and 0 NFL rate cards
without a verdict.

**Loads with:** an ff + `reload-web` (web only); betting change NO. The user's call.

**Not covered:** `/nba/props` (empty today: it renders only a saved top-by-game artifact), the NBA and NCAAF game
cards, and the NFL betting-card route (a historical view of the stored snapshot).

**LOADED on web 2026-11-27 22:32:52Z (4:32 PM CST), user "Deploy to web now"; reader rc 0 MET at 22:33:00Z** (deploys.md entry of that time):
- All 4 pages lead with the board section, and no headline card is a non-board pick. The headlines were NFL props 7, NFL picks 8, NCAAF 10 and NBA 12 of 167.
- All 2,211 NFL rate cards carry a verdict and a "Rate edge" badge.
- The `/ncaaf/picks` page takes 4 to 12 s, but the page's own build is 4.0 to 7.0 s of that. The board view adds 0.1 s.

## Evidence on what earns ROI (from the ledger, not re-measured here)

Nothing has cleared the bar yet:
- the Suggested set promised +3.41% and returned -3.02% [-5.56, -0.51] (11,748 bets, 28 days);
- the live book since 11-03 is -4.94% [-12.15, +2.26] (914 bets), with fees 78% of the loss;
- #738 P1 CLV is -0.18% [-0.91, +0.53] (188 bets);
- `cell-calibration` (#847) shows a held-out Brier gain of -0.0062 per row [-0.0102, -0.0021] on the scorecard, and
  is default-off.

So the single source cannot be declared "the profitable one" today. It can be made **one**, measured, and pointed at
whichever probability and selection policy clears the #738 gate.
