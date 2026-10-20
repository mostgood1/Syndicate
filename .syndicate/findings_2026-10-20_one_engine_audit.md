# One-engine alignment audit — 2026-10-20

Lane `one-engine-alignment-audit` (session e13a70a0). **Audit only, no code.** User,
2026-10-20: *"we def need connectivity across all of Syndicate so everything is
aligned. Right now seems like areas of the site are operating in silos instead of one
cohesive betting engine."*

**Substrate.**
- `[render]`-class reads come from the fleet, which is LIVE money, at 127.0.0.1:10000 (fleet HEAD `72407b6c`). They are read-only public GETs:
  - `/api/board/layer2-shortlist?date=2026-10-20&limit=2000`, read 18:10:01Z. Index written 17:46:44Z, build age 1,400 s, 2,000 of 19,011 considered rows returned.
  - `/nhl/api/picks?date=2026-10-20`.
  - `/nba/api/picks`, which was empty: "no stored NBA picks".
- Env flag VALUES were read from `/proc/<pid>/environ` on the three fleet processes, using an allowlist of `SYNDICATE_*` names only.
- `[code]` reads are from origin/main `8edd23ee`.
- **NOT READ:**
  - The live and paper plans and the execution ledger. `/api/portfolio/plan` needs a portfolio login. Reading the keyvalue store directly would have meant loading the worker's full secret-bearing environment, and that was refused.
  - Because of that, the dollar figures below are bounded by the caps and band. They are not ledger sums.

---

## 0. URGENT, found in passing: venue tickers are joined to the WRONG GAME on the board

Some board rows carry a `venue_ref` (a Kalshi ticker) that belongs to a different game. The date and usually the opponent differ. The rows were measured on the 18:10Z shortlist.

| sport | rows with a `KX…` ticker | ticker date ≠ row's game date |
|---|---|---|
| NCAAF | 29 | **24** |
| soccer | 17 | **9** |
| NHL | 2 | **2** |
| NBA | 39 | 0 |
| **all** | **87** | **35 (40%)** |

Examples:
- `UM @ TRO`, 10-24, carries `KXNCAAFGAME-26OCT29TROYJMU-TROY`. That is Troy vs JMU on 10-29. The row is **`suggested=True`**.
- `MS @ DEL`, 10-20, carries `…26OCT27DELWKU-DEL`.
- `DET @ SEA`, 10-20, carries `KXNHLGAME-26OCT26DETEDM-DET`.

**What it contaminates `[code + measured]`:**
- The wrong game's Kalshi price lands in `quote.book_prices["kalshi"]` and `quote.best_any_book`. For DET@SEA, `best_any_book = kalshi +144` against a sportsbook consensus of about -110.
- That cell can enter the consensus fair, because `_consensus_fair` takes the median over books (layer2_board.py:1480).
- It also fills the "venue price" column that every venue-EV count in this file reads. 8 of the 20 "+EV at Kalshi" sides below are wrong-game prices.
- Shape: these are team-keyed joins, and the board's fan-in has NO date check at all. **Corrected 2026-10-20 ~19:2xZ:** this line first cited `_date_verdict` as venue_quote_fanin.py:1622-1645, but that function is in `kalshi_board_join.py`, the ORDER join, which does date-check. In the fan-in, NCAAF/NHL quotes name no game (`game_token` returns None), an h2h club key is never "contested" (`_key_claimants` maps role keys only), and `kalshi_outcome` ignores `selected_date`, so the club's next listed game answers the same key. Fixed by lane `venue-fanin-game-identity` (`_quote_is_for_another_date`).

**Does it reach an order? UNDETERMINED, and it needs checking first.**
- The executor takes its ticker from a SEPARATE join, `kalshi_board_join._match_key`/`_row_key`, keyed by board `event_id` (kalshi_board_join.py:1012-1104). It does NOT take it from `venue_ref`. So the board's join and the order's join can disagree. **That is itself a fork.**
- To answer it, read the 10-20…10-24 live Kalshi plan (or the ledger) for `UM @ TRO` and for any `venue_ticker` whose date differs from the position's `commence_time`.
- I could not read either.

---

## 1. The surface map

`L2` = syndicate/features/shared/layer2_board.py
`SPC` = syndicate/features/shared/portfolio_commit.py
`PC` = pipeline/portfolio_commit.py
`EP` = pipeline/execute_portfolio.py
`VS` = syndicate/features/shared/venue_scope.py
`cs` = syndicate/features/shared/cheat_sheets.py

| surface | fair prob | price | EV + fee | floor / gates | sizing | graded where |
|---|---|---|---|---|---|---|
| **L2 board `suggested`** | market consensus: median of per-book de-vigs (Shin on fleet rows) `_resolve_fair` L2:1681, `_consensus_fair` L2:1480. The sim enters only as `model_edge_pct` and in the score (weight 0.125, cap 1.5) | best **bettable** book, which can be an exchange only if it is the top price (L2:3031-3135, `book_shortlist.DEFAULT_BOOKS`) | `expected_value_pct` gross (L2:3358 → opportunity_signals.py:325). The fee applies ONLY when the price book itself is a fee venue (L2:3690-97, 4617) | `SUGGESTED_MIN_EV_PCT` 2.0 (L2:3634). Implied book total ≥95, i.e. EV ≤5.26% (L2:5239). Two-sided fair, ≥2 books, not stale. Opposite side dedupe (L2:3676-3769). Ignores the sim, movement, and the venue price | none (rank `blended_score`) | `opportunity_population_ledger.py:217` (`sg`) → scorecard |
| **paper main plan** | fair re-derived from `ev_pct` and price (SPC:724); model = fair + `model_edge_pct` or fitted blend (SPC:764-792) | `quote.price` (best bettable) | gross | `suggested` only (PC:1696-1721, applied PC:1756). `min_ev_pct` (fleet env **0**) (SPC:1153). Fair noise 5/√books (SPC:373). Net of fee >0 (SPC:1179) | ¼ Kelly × credibility; game cap 5%, slate 20%, 12 positions (bankroll_manager.py:300-340) | `paper_settlement.py:411` |
| **paper2 `paper:<venue>`** | same, inverted from best-book EV (VS:178) | venue feed, else the aggregator's `book_prices[venue]` (VS:143-149) | venue gross (VS:183, written as `ev_pct` VS:227) plus `ev_pct_net_of_fee` (VS:217) | `suggested` first, THEN venue gross ≥ `min_ev` (0) and net >0. A venue EV >5.26% is refused as implausible (VS:184) | same as main | `paper_settlement.py` |
| **LIVE plan + executor** | same as paper2 | venue feed only + ticker (`placeable_refusal` PC:170). Kalshi sends at the live ask (EP:1020) | venue gross. Polymarket ask check is gross vs **market** fair (`polymarket_us_orders.py:1243-1277`, `PRICE_AT_ASK=1` on fleet) | the paper2 gates, then dedupe across slates (EP:733), trim to the order cap (EP:778), and `check_order` day/order caps (`execution_guard.py:885`). `BALANCE_CAPS=on` | compounding `on`, basis `venue_total`, `floor_one_contract` (PC:392-517); **stake band $5–10 on FULL Kelly** (`live_stake_band.py:109-130`, `on`) | `venue_settlement.py:1464` (venue's own records) |
| **min-ev tuner** | the orders' own venue `ev_pct` | — | venue gross | cells venue\|sport\|market\|phase (`min_ev_tuner.py:176`). **Mode: shadow** (unset on fleet → changes nothing, :121-127) | — | reads settled Kalshi/Polymarket orders, live + paper twins dropped (:478-535) |
| **cheat sheet props/lines** | board `quote.fair_probability` (build_cheat_sheets.py:174); a re-built Shin median for started games (:260-325) | board's best price | `(p·dec−1)` net of fee; **fee lookup returns 0 on exception** (cs:51-76) | VALUE ≥2.0, **SUSPECT >10** (board: 5.26) (cs:35-37) | none (1 unit) | `reconcile_cheat_sheets.py` → `.reconciled.json` |
| **cheat sheet picks** | board row | board | board | board `suggested`, THEN its own re-label: "SYNDICATE PICK" needs the sim ≥ market +1pp, else "PRICE PLAY" (cs:947-954, 1339-1366) | none | same |
| **play cards** (posted to X) | sheet row | sheet | sheet | `suggested` OR (value, EV 2–10, ≥3 books); **a suggested row with EV >10 is dropped** (play_cards.py:74-80) | none, top 3/sport | `grade_play_cards.py` → `playcards/ledger.jsonl` |
| **SGP pools** (mlb/basketball/nhl/nfl) | **own**: alt-rung median implied ÷ margin factor, then `consistency_posterior` (sgp_hit_rate.py:63-128). The sim only vetoes | product of legs at ONE book × (1−0.185 **unmeasured**) (nfl/sgp.py:28, 583-598) | `est_ev_pct`, no fee | market p .75-.95, ≥8/10 hits, sim ≥.75; joint ≥.40/.28 | none | `grade_sgp_paper.py` ← `sgp_ledger.jsonl` |
| **cross-game parlays** | product of legs (independence) | product at one sportsbook (`PARLAY_BOOKS`) | p·dec−1, fee 0 | value legs EV 2–10 per book | none | `cross_game_parlays.grade` :229 |
| **Ask the Syndicate** | board row (`read_layer2_shortlist`) | board's best price | row `ev_pct` | **any positive** `model_edge_pct` and `ev_pct` (adapter.py:1170-1213); never reads `suggested` | none | **none** |
| **per-sport picks/cards** | **own sim / own model**. MLB: sim vs multiplicative no-vig of one pair. NBA/WNBA lines: logistic(margin/7.5). NHL: market-anchored sim. NCAAF/NFL: SmartSim2. Soccer: model | own: one pair / CSV column (−110 fallback) / median / best | own EV vs a **vigged** price (8+ implementations, §5 of the code read) | MLB edge 0.01 to 0.03 prob; NBA lines **none**; NHL higher-prob side; NCAAF/NFL serve every row | NCAAF ¼ Kelly on $100; others none | `evaluation_settlement.py` (intelligence ledger) / per-sport |
| **daily optimizer / scorecard** | grades every L2 priced side + published shortlist rows | — | — | outputs `edge_shrink`, `stake_scale` ∈ [0.5,1] | feeds L2 score (L2:937-1015) and paper sizing (SPC:330-360) **only** | itself |

**Count of independent pieces:**
- Fair: 5 bases.
- Price: 6 bases.
- EV/edge implementations: 21 (listed in the code read: opportunity_signals ×4, bankroll_manager, recommendation_engine, refresh_nba_oddsapi_props, basketball_props_edges, MLB daily_update ×3, prop_projections, hockeysim, build_soccer_picks, build_ncaaf_recommendation_summary, market/venue_basis_edge, soccer/cards, evaluation_settlement).
- Grading ledgers: 7 (population ledger, paper settlement, venue settlement, cheat reconcile, playcards, sgp, evaluation).

---

## 2. Forks, measured on the 18:10Z fleet shortlist (2,000 rows)

| # | fork | count | denominator |
|---|---|---|---|
| F1 | `suggested` at best book, but NEGATIVE net at Kalshi's own price (full-rate fee bound) | **12** | 13 suggested Kalshi-quoted sides |
| F1 | same, Polymarket (1.5% notional fee) | **2** | 3 |
| F1′ | positive net at Kalshi, NOT suggested, so never a live candidate (PC:1756 runs before any venue re-price) | **19** | 20 positive. **But identity-clean: 1**; 8 carry a wrong-game ticker (§0) and 11 have none. Polymarket: 16 of 17 |
| F2 | ticker joined to the wrong game | **35** | 87 rows with a ticker (§0) |
| F3 | board **suggests** a side its own sim OPPOSES (`model_edge_pct` < 0) | **33** | 56 suggested rows that carry a model view (80 suggested in all) |
| F3′ | sim edge ≥5pp, NOT suggested | **370** | 1,398 rows with a model view. NCAAF 172, NHL 124, NFL 40, soccer 34 |
| F4 | NHL picks page shows a pick at +2.6…+11.1% "EV"; the board carries the same line at NEGATIVE EV, not suggested | **8 of 8** matched (4 more are not on the board) | 12 NHL picks |
| F5 | Ask's positive-edge filter admits a row the board does not suggest | **193** | 222 Ask-admissible rows |

**Notes on the forks:**
- **F1 is mostly caught downstream, and that is its own cost.** paper2 and live re-gate at venue net >0 (SPC:1179), so most of the 12 are refused, not placed. The result is that the live venue's candidate set is "suggested at a sportsbook" ∩ "positive at the venue". On today's board, that is **1 identity-clean Kalshi side out of 259**. The live book is being chosen by a gate that is about a different book.
- **F3/F4 are the engine's identity crisis.** Three verdicts sit on one line:
  - The sim says bet (model edge +3…+8pp on every NHL away +1.5 / under on the board).
  - The per-sport picks page says bet (+EV vs a vigged price).
  - The board says don't (market-fair EV −0.7…−2.5).
  - None of them is wrong by its own definition; they answer different questions.
- **Model-engine note, per the standard:** every NHL away/under game row on the board (17 of 17 sides read) has a POSITIVE model edge. That is a one-directional lean (dog +1.5 and under on every game), not an edge. It reads as a bias in the market-anchored hockeysim, and the scorecard's w* should already be shrinking it. Logged as a lead; this is not a measurement of the engine.

---

## 3. Top 5 forks by money at stake

**Fleet money ceilings:**
- The defaults are Kalshi $50/day, Polymarket $100/day, all venues $150/day, and $10/order (execution_guard.py:77). Stored overrides were **not read**.
- `BALANCE_CAPS=on`, which can only tighten them.
- The stake band is $5–10/order.
- The paper main book stakes 20% of a $1,000 bankroll per slate.

| rank | fork | money it governs | why it ranks there |
|---|---|---|---|
| **1** | **F2 wrong-game venue join** | Up to one order cap ($10) per bad ticker, **if** the executor's own join agrees with it. It is already biasing the fair and the price on 35 rows | Ranked first because the failure mode is a real order on the wrong contract, which the 2026-08-28 segment incident ($7.08) already proved this class can cause. Check first (§0) |
| **2** | **F1 candidate gate = best-book `suggested`, then venue re-price** | **The entire live book** ($150/day ceiling) is selected by a gate priced at another book. Measured yield today: 1 clean Kalshi candidate of 259 | Every live dollar passes through it. It also turns the venue +EV population (Kalshi has 1 clean positive side, Polymarket 16 of 17 positive sides unconsidered) into zero |
| **3** | **Sizing chain: ¼-Kelly plan → compounding `floor_one_contract` → band $5–10 on FULL Kelly → order trim → balance caps** | Every live dollar, again. The final stake follows none of the plan's Kelly | The band reads `sizing.kelly_fraction` (FULL) and ignores the 0.25 multiplier and credibility (live_stake_band.py:117-130). Below the small-edge fraction, a stake is one contract regardless of Kelly. Five layers from four lanes, none of which owns the composition |
| **4** | **F3 sim vs market (board suggests what the sim opposes; cards pick what the board rejects)** | Paper main book (≈$200/slate), and the published picks (NHL page, cheat-sheet "SYNDICATE PICK" vs "PRICE PLAY") | 33/56 suggested sides are sim-opposed. Paper sizes on `fair + model_edge` (SPC:764), so the sizer and the selector disagree on the same row |
| **5** | **Public verdict surfaces (play cards on X, cheat sheets, Ask, SGP) each with their own floor** | No execution dollars (verified: no execution reader). The money is reputational and in the graded record: 7 ledgers grade 7 populations | Play cards drop suggested rows above 10% and admit non-suggested ones; the cheat sheet's ceiling is 10 against the board's 5.26; Ask admits 193 rows the board rejects; SGP prices are an unmeasured 18.5% haircut. The optimizer learns only from L2, so these never improve the engine and the engine never governs them |

---

## 4. Proposal: ONE decision record per line

**Computed once, by the worker, in the Layer 2 build** (it already has the fair, the venue fan-in, the fee schedule, and the sim). It is written alongside the shortlist, and every surface reads it instead of recomputing.

```
DecisionRecord  (key = event_id | market | segment | player | line | side)
  identity      event_id, commence_time, sport, market, segment, player, line, side
  fair          p_market (de-vig method + books + anchor), p_model (engine, version,
                calibration), p_decision (the ONE probability we bet on: the staked
                profile blend, with its basis named), model_skill status
  prices[]      per bettable book AND per venue: price, source (feed|aggregator),
                ticker (venue only, from ONE join, identity-checked against
                commence_time), quote age, executable size, fee_per_contract,
                fee_basis, fee_is_bound
  ev[]          per price: net EV = p_decision / (p_price + fee) - 1   (ONE formula)
  gates         {name: pass|fail|unmeasured} - plausibility (one cap), freshness,
                two-sided fair, books, identity, in-play, model-skill, movement
  verdict       per DESTINATION: board_badge / paper / live:kalshi / live:polymarket
                -> {bet|no_bet, reason, best_destination}
  size          per destination: kelly_full, kelly_applied (multiplier, credibility,
                optimizer stake_scale), stake_dollars after compounding/band/caps,
                and WHICH layer bound it
  provenance    build id, fair/price timestamps, overlay version
```

**The single rules it enforces:**
1. **One EV formula, fee-net, per destination price.** "Suggested" becomes `verdict.board_badge` = best net EV over the user's bettable books. "Live" is the verdict at the venue's own price. Selecting live candidates by the venue's own net EV removes F1.
2. **One probability to bet on (`p_decision`), with `p_market` and `p_model` shown beside it.** Whether that is the market, the sim, or a blend is ONE switch per sport×market (the staked-probability profile from `#704` is the natural home). It is not decided separately by the selector, the sizer, the cards and Ask. That removes F3/F4.
3. **One venue join, identity-checked**, used by both the board and the executor. That removes F2.
4. **Sizing is a recorded composition**: every layer writes what it did to the size, so "which layer bound this stake" is a field and not a reconstruction.
5. **Every surface grades against the same record key.** The scorecard then sees cards, Ask, cheat sheets and live on one population, which closes the optimizer feedback loop for all of them.

**Migration order** (each step behind a flag, shadow first, one change per deploy):
1. **Identity check on the venue fan-in (F2).** A ticker's date must equal the row's game date; a mismatch is a refusal. This is small and a safety fix. Do it first, independent of the rest.
2. **Write the DecisionRecord in shadow** beside the shortlist. Nothing reads it yet. Report daily agreement against `suggested`, the paper plan, the live plan, and NHL/NCAAF picks. These fork counts become the gate.
3. **Live and paper2 read the record**: candidate = `verdict[live:<venue>]`, replacing `suggested_rows` → `scope_rows_to_venue` (PC:1756, VS:100). This is the biggest money step and needs a user decision. It overlaps the companion proposal "Pick live bets on the venue's own price".
4. **The sizing chain writes into `size`**: compounding, band and caps keep their logic but record their effect. Then decide (user) whether the band should read applied Kelly rather than full Kelly.
5. **The board badge, the paper main book and the tuner read the record.** The tuner then tunes the same net EV that selects.
6. **Ask, cheat sheets and play cards read `verdict` + `gates`.** Their extra labels (SYNDICATE PICK, value, suspect) become gate names on the record, not private thresholds.
7. **Per-sport picks pages read the record** for any line the board carries, and label their own sim-only picks as "model view", not "EV".
8. **Graders key on the record**, and the scorecard grades all populations.

**What cheat sheets / SGPs need that the record lacks** (record v2, or a sibling artifact keyed the same way):
- **Alt ladders**: per-rung fair and per-book price (`alt_rungs`, sgp_hit_rate.py:78-97). The record above is the main line only.
- **Joint structure**: per-leg latent normals plus the rho cells (nfl/sgp.py:525-560). Ideally the sim's joint draws per game, which no engine publishes today.
- **A real SGP book price.** Today it is an assumed 18.5% haircut, so SGP EV is not a decision-grade number until it is captured.
- **Per-player distribution and form**: sim histogram or mean/spread, `model_skill`, last-10 values (the sheet's prop context).
- **Same-book prices across legs**, because a parlay is priced at one book.

---

## 5. Not done / owed
- §0's executor check (needs a plan or ledger read: a portfolio login or an explicit user OK to read the store).
- Ledger-summed dollars per fork (same blocker).
- The production values of the stored execution limits and `SYNDICATE_FAIR_ANCHOR`/`FAIR_DEVIG_METHOD`. The fleet rows report `fair_devig_method: shin`, `fair_method: consensus`.
- A per-sport side-by-side for MLB, NCAAF and soccer picks against the board. NHL only today, and NBA had no stored picks.
