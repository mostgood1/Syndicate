# In-game (live) trading: measurement + staged plan — 2026-10-20

Lane `in-game-trading` (session 15ceeb14). This was started by session 332cb014 on the user directive *"we need the PRIORITY of the whole operation to be LIVE betting/trading"*. The goal was then sharpened at ~23:15Z: *"we should be actively buying AND selling when games are live based on smart profitable positioning"*.

**Status: DRAFT 23:45Z.** The measurement runs until the last game ends. The numbers below are from **23:09-23:38Z** and are replaced by the final read in §6.

## 0. What was measured, and how

**Recorder:** `scripts/inplay_recorder.py`, read-only, on this Windows host at Idle priority. Data is in `C:/tmp/inplay_2026-10-20/`.

| source | what | cadence |
|---|---|---|
| Kalshi public `GET /markets?tickers=` | the 258 full-game NBA/NHL tickers (GAME / SPREAD / TOTAL ladders) in the fleet's venue_odds files, plus held tickets (`held*/`) | 10 s |
| OddsAPI `/v4/sports/{nba,nhl}/odds` | in-play h2h/spreads/totals. Regions us,eu; uk added at 23:16Z for Betfair Exchange | 60 s |
| ESPN scoreboard | state, period, clock, score | 60 s |
| the fleet's `venue_odds/polymarket__*` | the newest point per full-game market, i.e. what the FLEET sees | 60 s |

**Cost:** 918 OddsAPI credits over the first 65 min (84 polls x 6 + 46 x 9). That is about 850 credits/h, or 0.017%/h of the 5M monthly cap. NHL full-game totals are not recorded: the fleet's Kalshi NHL store carries period totals only.

**Fair:** per-book multiplicative no-vig on the SAME line. The consensus is the median over books with at least 3 quotes. A book market whose own `last_update` is more than 120 s old at the poll is dropped, because in play that means suspended or still showing its pregame price. 3-way (draw) hockey markets are skipped. Kalshi rungs with no exact book line are counted as unpriceable, never interpolated.

**Edge at Kalshi's price:** `fair - ask - taker_fee/contract`. The fee is computed for 10 contracts with each series' read `fee_multiplier` (1.0 for all five families).

**Episode:** consecutive positive samples on one (ticker, side). Each episode is tagged by:
- who moved when it ended (the venue or the book);
- seconds since the game's last ESPN score change;
- markout: our leg's Kalshi mid +60 s / +300 s later, minus ask and fee.

Markout is the in-play stand-in for CLV. There is no valid in-play close (learnings 2026-10-02).

**Analysis:** `scripts/inplay_edge_report.py` (edge, episodes, lead/lag, per-book gap, markout) and `scripts/inplay_exit_replay.py` (take-profit at fast vs slow cadence).

## 1. Findings (window 23:09-23:38Z; 5 games mapped: 4 NHL + PHI@NYK)

**F1. Kalshi leads the sportsbooks in play; book consensus is not a usable in-play fair against Kalshi.**
- Lead/lag of per-poll changes, pooled (n=334-378): corr(dKalshi_i, dFair_{i+k}) is +0.69 at k=+2 and +0.20 at k=+1. At k=0 it is +0.03, and at k<0 it is -0.02 / +0.04. The books follow Kalshi by 1-2 polls (60-120 s).
- Example: CBJ's goal (ESPN shows it between 23:11:44 and 23:12:45Z) was in Kalshi's ask at 23:12:11Z. The books still showed 0.41 for TOR at the next poll, which reads as a +13.9% "edge" for 84 s. It ended when the books moved to Kalshi.
- Even Betfair Exchange, via OddsAPI, sits 1.0c from Kalshi's mid at the median. Matchbook, betsson and nordicbet sit 0.8c. OddsAPI's own fetch cadence is the bottleneck.

**F2. "Positive after fee" is common but not real.**
- Of 4,616 priced side-samples:
  - 12.3% are > 0
  - 8.5% are > 1%
  - 6.4% are > 2%
  - 4.6% are > 3%
- The large ones cluster at score changes and end by the BOOK moving:
  - NBA game lines: 14 of 19 near-score episodes ended by the book.
  - NHL game lines: 8 of 8 did.
- **Markout is negative in every cell:**
  - near-score, NHL game lines: +60 s -4.9c (0/8 positive), +300 s -2.8c (0/6)
  - near-score, NHL spreads: +60 s -5.7c (1/8), +300 s -7.5c (0/6)
  - away-from-score, NHL game lines: +60 s -2.1c (1/20), +300 s -1.9c (6/16)
  - away-from-score, NHL spreads: +60 s -1.4c (5/16), +300 s -1.9c (5/13)
  - NBA spreads, near score: +60 s -2.5c (3/22), +300 s -0.6c (8/16)
- Buying what the books call +EV loses about the fee plus half the spread against Kalshi's own later mid. Gross edge is about zero.
- **The hypothesis in the lane is FALSIFIED for book-consensus fairs:** positive sides exist but do not persist in our favour.

**F3. Kalshi's in-play book is tight and fast.**
- Ask change interval, in play: p50 10-11 s (the poll floor) on spreads and totals; 11-21 s on game lines. p90 is 32-95 s.
- |mid - consensus|: p50 1.2c, p90 7.0c. Bid-ask spread: p50 1c, p90 3c.

**F4. The fleet's own eye is 10-30x slower than the venue.** Measured from the venue_poll lines, 22:53-23:10Z:
- Kalshi is polled every ~2-3 min. The env default is 60 s, but the series self-pace and the batch is capped at markets=6000.
- Polymarket is polled every ~3-5 min. The newest Polymarket point per market moved in 3-4 min steps in play.
- The exit check is on the 300 s execution tick; EXIT_TICK lines run 5-15 min apart.
- The fleet's NBA in-play book capture runs every 240 s. NHL in-play books are not captured at all (`_launch_inplay_capture_autoruns`).

**F5. Fast vs slow take-profit, synthetic book (both legs of every recorded game line, entered at the ask at ESPN "in"; NHL so far, 180 positions):**
- At margin 0.08: 10 s marks trigger on 35 positions (19.4%), a 6-min cadence on 12 (6.7%).
- Where both trigger, the slow loop sold +0.1c/contract higher, 285 s later. Speed does not get a better price on the same trigger. It catches moves that the slow tick never sees, because they reverse before the next tick.
- **Whether that is GOOD (locking gains) or BAD (selling winners early) is the settlement read in §6.**

**F6. Live take-profit went live tonight.** Lane kalshi-exit-path, EXIT_TICK at 23:37:00Z, `mode=live`:
- `live_exits={'rule_not_armed': 3, 'placed': 1}`.
- The `placed` exit was the first real in-game sale: `KXNCAAFSPREAD-26OCT20MOSUDEL-DEL3` NO x1, `status=filled`. fill_price and fee were not yet read back.

**F7. Kalshi cancel is broken on both routes** (deploys.md 22:04Z / 23:05Z: 404 on events/orders, 410 on classic). An exit is IOC and needs no cancel. **Any resting in-game order (maker quotes, re-pricing) does.**

## 2. What the measurement means for the program

Two-sided in-game trading has two halves, and tonight separates them.

- **Selling (exits) needs no in-game fair to be SAFE.** Take-profit only compares Kalshi's own bid with our entry cost. Its open question is whether it is PROFITABLE: does taking +8c early beat holding to settlement? The settlement read (§6) and the exit lane's 10-26 counterfactual answer that. Speed is the cheap, measurable part.
- **Buying in play needs a fair that is better than Kalshi's own price.** Tonight that fair is not the sportsbooks: Kalshi leads them (F1) and their "edges" mark out negative (F2). It also cannot be a data-latency play. Kalshi had a goal priced 34 s before ESPN's scoreboard showed it, and we have no faster feed. What is left is a MODEL fair that Kalshi's crowd misprices over minutes: a score-aware win/cover/total model, like the NBA live re-sim (§3, stage 2). It must beat Kalshi's mid on settlement before one dollar is entered on it.

## 3. Staged plan (each stage = its own user decision)

### Stage 1: fast held-position loop (mark -> exit). BUILT, PAPER, NOT RUNNING.

- **Code (main `c2191d1b`):**
  - `syndicate/features/shared/execution_exits_fast.py`, NEW: `FastExitLoop.step`, `mark_pass`, `in_play_kalshi_positions`.
  - `scripts/run_fast_exit_loop.py`, NEW: a standalone runner, `--until` self-exit, nice 19.
  - `tests/test_execution_exits_fast.py`: 8 pass.
- It marks every IN-PLAY Kalshi position every 15 s (`SYNDICATE_EXIT_FAST_LOOP_SECONDS`), from the same public batched quote (`execution_exits.fetch_quotes`, :546). It runs the slow tick's own rule (`execution_exits.evaluate_exit`, :760) with the same margin env.
- It books the first trigger per entry as a FAST paper exit in `reports/intelligence/execution_exits_fast.json`. Each row records what the slow tick's watch said at that moment (`slow_last_reason`, `slow_last_seen`).
- Positions are re-read every 60 s (`SYNDICATE_EXIT_FAST_POSITIONS_SECONDS`), net of live sales (`net_of_live_sales`, :1124). It prints `FAST_EXIT_PASS` once a minute with marks and passes, and `FAST_EXIT_PAPER` per trigger.
- **It cannot sell.** It imports no order/cancel/credential code; the test parses the module and fails on `place_exit`, `send_exit_order`, `kalshi_orders`, `cancel_order` or `_persist`. It never writes `execution_exits.json`.
- **Reachability:** `test_reachability_off_books_nothing_on_books_the_trigger` (off != on). `SYNDICATE_EXIT_FAST_LOOP` absent = off; only exactly `paper` = on.
- **NOT wired into live-odds-worker.** Adding `_fast_exit_background_loop` + `start_fast_exit_loop` next to `start_inplay_capture_loop()` (run_live_odds_refresh_worker.py ~:2894 / :3229) was refused by this session's permission classifier as a shared-resource edit. The lane claims that section. The standalone runner exists so that wiring is optional.
- **USER DECISION 1a (paper on the fleet), pick one:**
  - (i) allow the worker-thread edit, then fleet ff + live-odds-worker restart + `SYNDICATE_EXIT_FAST_LOOP=paper`;
  - (ii) run `scripts/run_fast_exit_loop.py --until <next morning>` as its own fleet process under the worker's storage env, with no restart. It needs the same keyvalue read the worker does.
- **Readout:**
  - Marks/min.
  - Fast triggers vs slow triggers on the same entries.
  - Fast paper P&L vs hold vs the slow tick's live/paper exit, at settlement. `scripts/exit_counterfactual_report.py` is the slow tick's version; the fast doc is keyed by the same entry_key.
- **USER DECISION 1b (going live):** the fast loop would call `execution_exits.place_exit` (:918) for in-play positions. Prerequisites:
  - ONE WRITER for `execution_exits.json`. The slow tick must skip in-play Kalshi positions while the fast loop runs, or both take a lock. Otherwise two writers race the same doc and the same daily caps (`_live_exits_today`, :189). That is a change inside kalshi-exit-path's file, so it is coordinated with that lane, not forked.
  - The fill read-back already exists (`reconcile_exit_orders`, :1041).
  - Caps stay those of `live_exit_daily_caps` (5 sales / $25 per day).
  - No cancel needed (IOC).

### Stage 2: an in-game fair price per sport (MEASURE before use)

- **Candidates, measured against Kalshi's mid and against settlement, never against the books in play (F1):**
  - **NBA:** the live re-sim already writes a model fair to disk: `nba_source/data/live_gameline_ledger/live_gameline_ledger_<date>.jsonl`. It carries `model_home_win_prob`, `model_margin_mean`, `model_total_mean`, `prob_std_err`, `sims_run`. At 23:37Z it had 27 priceable full-game rows of 606. The rest:
    - 451 `segment_is_not_full_game`
    - 116 `prob_interval_swamps_edge`
    - 9 `live_resim_published_no_distribution_for_this_market`
    - 3 `no_two_sided_market_price`
  - It ran **100 sims, std err ~4.8pp**, and claimed +9.7 to +11.5pp on NYK alt spreads against a book quote 250 s old. That is the shape F2 says to distrust. Tonight's snapshots are kept (`C:/tmp/inplay_2026-10-20/nba_live_gameline/`) for the score-against-Kalshi read.
    - Gate `SYNDICATE_NBA_LIVE_PRICED` (board_enrichment.py:2560-2577).
    - Forward read owed after 12-15 (todo #700).
  - **NHL:** `nhl/live_resim.py` via the live lens. Its disk snapshot `data/live/nhl_live_lens.json` is stale (dated 09-30; the live copy is in keyvalue). NHL in-play books are not captured by the fleet at all (F4).
  - **A cheap baseline for every sport:** a score/time win-prob model anchored on the pregame Kalshi close (logistic in score diff x time remaining). It is cheap, needs only ESPN plus the pregame price, and is the bar a sim-based fair must beat.
- **Measurement design** (`scripts/inplay_edge_report.py` extended; no code on the fleet):
  - For each (fair, sport, market), Brier and log-loss at settlement vs Kalshi mid at the same timestamps.
  - Markout at +60/+300 s of the sides the fair calls positive after fee.
  - Split by near/away from a score change, and by game phase.
  - Per the model engine standard: a gating input checklist for whatever fair is chosen, a pipeline trace, and a reachability test.
- **Pre-registered GO for a (fair, sport, market) cell:**
  - Brier better than Kalshi mid, with the 95% CI excluding 0, over >= 300 settled game-states from >= 20 games;
  - AND positive mean markout +300 s after fee, CI lower bound > 0.
  - Calendar stop 2026-12-31.
- **USER DECISION 2:** approve the measurement design and its kill/promote rule. It is read-only, recorder + report, with no fleet change. Optionally choose the NBA re-sim sims budget (100 -> 1000+) for in-play, which is a refresh-worker memory question.

### Stage 3: in-play ENTRIES (and adds) gated on the measured edge

- Only for a cell that passed stage 2. The entry path:
  - stamps `fair_source="in_game"` on the plan position. This is `pipeline.execute_portfolio.IN_GAME_FAIR_SOURCE` (:213); the exemption check is at :218 and the log at :865. It passes the new REFUSED_AFTER_COMMENCE block (150e1180) and logs `AFTER_COMMENCE_IN_GAME_FAIR`. Nothing removes the block. `portfolio_commit` does not copy the field from board rows today, so the stage-3 row builder must set it on the position.
  - replaces, for that cell only, the `in_play_market_fair` refusal (portfolio_commit.py:530-553, :1143). It does this by being a MODEL-edge row (the refusal applies to market-fair-only rows), never by widening `IN_PLAY_MARKET_FAIR_CELLS` (:500).
  - prices at the venue's live ask at order time (`LIVE_PRICE` drift check, already there) on the stage-1 cadence, not the 5-min plan tick. That needs an in-play plan source the fast loop can read; the design point is that entries and exits share one in-play loop.
- **Grading:** settled ROI from the venue (`venue_settlement`), plus markout +60/+300 s vs Kalshi mid as the in-play CLV analogue. There is no in-play close. Pre-registered stop: markout CI upper bound < 0 after 200 entries, or ROI CI upper bound < 0 after 400.
- **Sizing:** the stake band and caps as today, with a separate in-play daily dollar cap (new stored field, default $25) until 200 graded entries.
- **Resting (maker) in-game orders are OUT until Kalshi cancel works** (F7; fix in progress, session fix-kalshi-order-cancels). Taker IOC/FOK only.
- **USER DECISION 3:** per cell, after stage 2 says GO. The in-play cap value.

### Stage 4: Polymarket in play: keep the pregame-only rule

- The rule (`polymarket_us_orders._refuse_after_commence`, :1037-1057) rests on in-play bets going 3-10 against 5.7 expected (-46.6%), user decision 2026-09-11.
- Tonight adds three reasons it is still right:
  - the fleet sees Polymarket in 3-5 min steps (F4), so any in-play price it would act on is minutes old;
  - Polymarket's flat 150 bp fee does not shrink at the tails the way Kalshi's does (venue_fees.py:654);
  - a Polymarket live SALE is not built (`venue_live_exit_unbuilt`, execution_exits.py:960), so an in-play Polymarket position could not be exited.
- **Revisit only when** stage 2 has a GO cell AND a signed book read happens at order time AND a live Polymarket sale exists.
- **USER DECISION 4:** confirm keep (recommended).

### Stage 5: one engine (#709), not a silo

- The in-play decision is the same DecisionRecord the audit proposes (findings_2026-10-20_one_engine_audit.md §4):
  - `p_market` = Kalshi mid at decision time;
  - `p_model` = the stage-2 in-game fair, with `fair_source=in_game` and its `as_of`;
  - gates named (`in_play_market_fair`, `game_started`, `REFUSED_AFTER_COMMENCE`'s exemption, `near_score_change`);
  - per-destination verdicts.
- What is NEW to #709 is a **position-decision record**: hold / exit / add, for an entry_key, at a mark, with the rule that fired. Both the slow tick and the fast loop write it. One schema makes "the exit lane's counterfactual", "the fast loop's paper exits" and "in-play adds" one table, not three documents (`execution_exits.json`, `execution_exits_fast.json`, the plan).
- Proposal: #709's step list gains "position decisions" after step 3, shadow first.
- **USER DECISION 5:** fold this into #709's pick.

## 4. Touch points summary

| stage | file:line | change |
|---|---|---|
| 1 | `syndicate/features/shared/execution_exits_fast.py` | NEW (on main) |
| 1 | `scripts/run_live_odds_refresh_worker.py` ~:2894 + after :3229 | start the fast thread (needs permission) |
| 1-live | `execution_exits.py` :1195 `run_exit_tick` | skip in-play positions when the fast loop owns them (kalshi-exit-path's file) |
| 1-live | `execution_exits_fast.py` | call `place_exit` (:918) under `live_exit_rules` / caps |
| 2 | `scripts/inplay_edge_report.py` | score fair sources vs Kalshi mid + settlement |
| 2 | `board_enrichment.py` :2553-2577, `nba` live re-sim sims budget | only after GO |
| 3 | `pipeline/execute_portfolio.py` :213/:218/:865 | stamp `fair_source=in_game` (exists) |
| 3 | `portfolio_commit.py` :530-553 | in-game MODEL rows pass as model-edge rows |
| 3 | `execution_limits_settings.py` | in-play daily cap field |
| 4 | `polymarket_us_orders.py` :1037-1057 | unchanged |
| 5 | #709 DecisionRecord | position-decision record |

## 5. Not done / caveats

- The fleet's live exit doc and the execution ledger were not read directly (keyvalue). Held positions were taken from LIVE_LEDGER_ROW, LIVE_PRICE and EXIT_* log lines.
- OddsAPI in-play books are at 60 s; a faster sharp feed was not tested. F1 is a statement about THIS feed.
- The synthetic exit book is a cadence comparison, not a strategy.
- One night, 2 sports. Sample sizes are printed; nothing here is a GO.

## 6. Final read (after the last game)
