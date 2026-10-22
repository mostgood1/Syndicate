# state — portfolio

Split out of `state.md` by `scripts/split_state.py`. Bodies are verbatim.
The INDEX of every subject, across every part, is in `state.md`; the
one-subject-one-section rule is global and spans these files.
Same rules as state.md: when a fact changes, EDIT THE LINE.

## [portfolio-sign-in-and-books] EVERY PORTFOLIO PAGE IS BEHIND A SIGN-IN, AND THERE IS MORE THAN ONE PORTFOLIO `[verified on production 2026-09-10T16:05Z, web df60b3e3, lane portfolio-login-multibook]`

**THE GATE** (`portfolio_auth.py`, installed app-wide in `create_app`) covers
every `/portfolio*` page and `/api/portfolio/*` endpoint. Credentials are
`SYNDICATE_PORTFOLIO_USERNAME` + `SYNDICATE_PORTFOLIO_PASSWORD` (plain) on web,
DASHBOARD-ONLY — `SYNDICATE_PORTFOLIO_PASSWORD_HASH` was deleted 2026-09-10
after it held a plaintext value and refused every sign-in. Measured live:
signed-out pages → 302 `/portfolio/login?next=…`; signed-out JSON → 401
`portfolio_login_required`; boot line `PORTFOLIO_AUTH_MODE mode=required
credentials_configured=True hash=no on_render=True` (16:26:59Z); **a real
sign-in, `LOGIN_OK` 16:43:56Z.** Since `2224dec0` (live 16:55:19Z) a HASH value
that is not a werkzeug hash locks with a named `problem=password_hash_not_a_hash`
(503, value never echoed) instead of refusing every sign-in; the boot line now
carries `problem=none` when the setup is sound.

**TOOLING READS WITH THE OPS TOKEN.** `X-Admin-Token` (or `?admin_token=`)
passes — measured 200 on `/api/portfolio/live` and `/api/portfolio/books`. **A
bare curl of `/api/portfolio/*` returns 401 from 2026-09-10 on**, which breaks
every recipe in this ledger that reads `/api/portfolio/live` or
`/api/portfolio/paper` without the header.

**ABSENT IS NOT OFF.** On Render, missing credentials answer 503 on every gated
path (tested, not observed live). `SYNDICATE_PORTFOLIO_AUTH=off` is the only
way to open it.

**DURABILITY HAZARD — `render.yaml`.** The credential keys are dashboard-only,
and a `blueprint_sync` deletes dashboard-only keys (`todo.md #650`). When `#650`
reconciles the blueprint they must enter it as `sync: false`, or the next sync
locks the portfolio. That fails closed, but it reads as an outage.

**THE PORTFOLIOS.** A dropdown on every portfolio page: Kalshi + Polymarket
(`/portfolio`), Paper (`/portfolio/paper`), and MANUAL portfolios
(`/portfolio/books/<id>`; default `manual` = "Other books"). Hand-entered bets
live in `data_root()/portfolio_books.json` on WEB'S disk only — deliberately
not the prediction ledger, because `prediction_reconciliation._match_result_row`
accepts the first result row sharing ANY key with a bet (sport alone) and would
grade a typed bet off another game. Slip-logged bets stay in
`prediction_ledger.json` with a new `portfolio_id` (None → the default book).
Live reading 16:05Z: `/api/portfolio/books` → `['manual']`, no user-created
portfolio yet.

## [portfolio-live-surface] `/portfolio` IS THE LIVE BUYING ENGINE, the venue caps BIND, and the VENUE now settles our bets `[verified 2026-08-27T00:0xZ, lanes portfolio-live-primary / portfolio-venue-caps-editable / venue-balances-on-portfolio / venue-settlement / venue-first-refusal / open-bet-live-status]`

**VENUE CAPITAL FIELDS, MEASURED 2026-10-19 18:13Z (lane compounding-bankroll):** Kalshi `portfolio_value` is OPEN POSITIONS ONLY (4.50 beside $485.48 cash with one $4.50 position) -- not cash plus positions. Polymarket `buyingPower` INCLUDES a pending deposit (586.05 = `displayedCash` 36.05 + `depositReservation`/`displayedAvailableSoon` 550). `venue_capital.py` uses Kalshi cash + positions, and Polymarket buyingPower minus the pending deposit, for the dark compounding flags (todo #702).

**LIVE PLACEMENT WAS FROZEN ON BOTH VENUES FROM 2026-09-04T18:27Z TO 2026-09-10T17:21Z, AND WHAT CAUSED IT
IS NOW REFUSED BEFORE IT CAN RECUR** `[verified on production 2026-09-10T18:17:30Z, lane
exchange-execution-unblock]`.

- **The freeze.** One Polymarket order with no slug was written `submitted` (the write-ahead), refused at
  build, and logged `rejected`. The stored row stayed `submitted` anyway.
  - **A LOST UPDATE, MECHANISM PROVEN 2026-09-10** (lane `write-ahead-build-refusal`).
    `execution_ledger._persist` merges on a fresh read and then SETs, with nothing atomic between the two.
  - live-odds-worker SET the rejection at 18:27:25.083. refresh-worker's paper SET at 25.228 was exactly its
    own 24.711 document + 48 B, and it carried the write-ahead copy back.
  - The stored row has `error` and `venue_resolved_at` null, so no rule keyed on a recorded build error could
    ever have seen it.
  - Paper rows stuck at `submitted` are this race's witnesses: 13 across 09-06..09-11, since paper completes
    `filled` in the same call.
  - Any unreconciled live order blocks every venue.
  - Nothing reconciles an order that never got a venue id.
  - It was cleared by the operator path, `/portfolio/live/unknown/<key>/resolve` with `not_placed`.
- **The fix.** Since `332e596d`, a LIVE position with no `venue_ticker` is refused by name before
  `place_order` (`refused['no_venue_ticker']`, a `REFUSED_NO_VENUE_TICKER` line). No write-ahead row is ever
  written for an order that cannot be built.
  - First pass: 11 refused, and 1 placed and filled, the first live Kalshi fill since 09-04.
- **The residual is closed too** `[live-odds-worker 2914b6c7, live 2026-09-10T21:55:18Z, lane write-ahead-build-refusal; carried by e4410f37, live 22:18:17Z, verified by content]`.
  A LIVE order is now BUILT before its write-ahead row.
  - These write NO row, log `REFUSED_AT_BUILD`, and are counted by name in `refused`:
    - a contract that cannot be built (a slug missing from the slate, a side `order_body` refuses, Kalshi `no_live_price`)
    - a disarmed worker
    - a missing adapter
  - Passes at 22:03, 22:09 and 22:14Z all read `duplicates=1 refused={'no_venue_ticker': 17}`, and the `live:kalshi` order count held at 14.
  - **The refusal branch is MEASURED in production** `[2026-09-11T04:10:57Z, live-odds-worker 3bafdd2b, which carries it by content]`.
    - A Polymarket draw side (`unmappable_side`, slug `atc-lal-elc-rma-2026-09-15-draw`) was refused at build and counted in `refused`, and it wrote NO ledger row.
    - No rejected `LIVE_ORDER` has occurred since the deploy.
    - `market_unresolved_for_position` and `no_live_price` share the branch and are tested, not yet seen live.
  - **The same race could revert a SENT order's completion. A CAS now closes it, and it is committing on both workers; the close reading is owed** `[verified on production 2026-09-11T03:36Z, lane execution-ledger-cas]`. `_persist`'s merge-read and SET are one compare-and-swap (`todo.md #656`, `de8a3f2a`).
    - `LEDGER_CAS_ACTIVE` on live-odds-worker at 03:23:41Z and on refresh-worker at 03:36:13Z. web has run it since 23:19:34Z; its line waits on an operator write.
    - **It works in production** `[2026-09-11T13:41Z]`: 7 collisions caught (6 in one 16 s two-writer burst at 05:15Z), and 0 new stuck paper rows across 245 new paper orders while live orders ran. A second reading `[2026-09-12T16:37Z]` held the paper half -- 31 more collisions caught, +340 paper orders, 0 new stuck paper rows, 0 CAS failures -- but found 4 LIVE rows stuck at `submitted` (polymarket, 09-11 and 09-12) against 0 in the first, so `#656` did NOT close. live-odds-worker was `oomKilled` 47 times in that window, one kill 2 min 25 s after the last stranded order: the crash shape, not a lost update.
    - Read stuck rows per date: the 5,000-record cap trims old dates.
- **Kalshi NCAAF/NFL forward-date matching** (`SYNDICATE_KALSHI_FORWARD_DATE_SPORTS=soccer,ncaaf,nfl`) is live
  on live-odds-worker. On refresh-worker, where the join reads it: LIVE since `86c82220` (20:13:21Z). `forward_date_sport_not_enabled` went from 7,617 to absent, and the first NCAAF Kalshi orders were placed and filled at 20:27:54Z.
  - `167b2841`'s "gains zero NCAAF rows" caveat is stale. `04a82c38` gave NCAAF its alias map.

**`/portfolio/live` NO LONGER EXISTS as a page** — it is a 302 to
`/portfolio#live` carrying the query string; `portfolio_live.html` is deleted.
`/portfolio` renders the execution ledger's real orders only — the prediction
ledger's user-logged bets moved to the manual portfolio "Other books" on
2026-09-10 (`[portfolio-sign-in-and-books]`). `/portfolio/paper` untouched.

**FLEET LIVE STATE `[verified 2026-10-19, session 332cb014, lane caps-revamp]`:**
- **Stored caps = dollar CEILINGS** (saved 10-19 23:58:48Z): $100/order, $1,000/day per venue, $2,000/day all venues, 50/50/100 orders. The live caps are the % of capital below them.
- **LIVE STAKE SIZING CHAIN, measured on the 10-20 15:01Z fill** `[verified 2026-10-20 from one build's COMPOUNDING_BANKROLL + STAKE_BAND lines]`:
  - Kelly at fixed $1,000 ($1.15).
  - -> compounding (`basis=venue_total`: Kalshi sized on the whole account, $465.37; `min_stake=floor_one_contract`) ($0.54).
  - -> **stake band** (lane live-stake-band: min $5, max $10, max at 5% Kelly) ($5.46).
  - -> trim to the order cap.
  - The band, not Kelly, sets live stake size today.
  - **The whole chain ran end to end:** Kalshi NCAAF under, 11 @0.47 = $5.17 + $0.19 fee, filled and reconciled 5 s after submit, then refused `duplicates=1` on the next pass.
- **First fleet live order** (16:59:37Z): Kalshi WNBA points under, filled @0.90 for $4.50.
- **KALSHI SHARD 3 = Sports: Tennis, Baseball, Basketball** (docs.kalshi.com exchange_sharding). MLB, NBA and WNBA orders draw ONLY on shard 3 cash. With shard 3 at $0 they refuse `insufficient_shard_balance`. Read 16:34Z: {0: 170.00, 1: 75.01, 3: 245.00}. Shard 1 (Combos) is not traded.
- **LIVE CAPS ARE A SHARE OF VENUE CAPITAL** since the 23:55:55Z full up on `d3878d69` `[verified under live-odds-worker's own environ, 23:58Z]`:
  - `SYNDICATE_EXECUTION_BALANCE_CAPS=on`: 25%/day and 5%/order of each venue's capital, bounded by the stored dollar ceilings ($100/order, $1,000/day per venue, $2,000/day all, 50/50/100 orders; user "Loose backstop").
  - Read: kalshi $24.38/order, $121.91/day; polymarket $29.30/order, $146.51/day; all venues $268.42/day.
  - Polymarket capital = buyingPower INCLUDING the pending deposit (user decision).
  - An over-cap stake is TRIMMED to the order cap (`TRIMMED_TO_ORDER_CAP`), not refused. Before this it was refused `over_max_order_dollars` ($28.57 vs $25, 22:00Z). The trim is loaded (EXECUTED lines carry `trimmed=`) and has not fired yet.
  - **Ceilings: raise them only while balance caps are ON.** With the flag off, a raised ceiling IS the live cap.

**THE VENUE CAPS ARE USER-EDITABLE AND THEY BIND.** Seven fields
(`max_day_dollars_kalshi|_polymarket`, `max_day_orders_kalshi|_polymarket`,
`max_order_dollars`, and both `_all_venues` ceilings) in
`execution_limits_settings.py`; `execution_guard.limits()` reads the store ON
THE WORKER on the same call `check_order` refuses with. Proven end to end by a
real user save 2026-08-26T20:27:26Z. **Orders now resolve PER VENUE** — they
were flat, so a per-venue orders field would have been stored and unenforced.
**Stored caps bind LIVE only**; paper stays uncapped by design.

**BOTH VENUE BALANCES READ, from the documented shapes** (`venue_balances.py`,
stamped by live-odds-worker, read by web — web holds no credential and must not):
kalshi `GET /portfolio/balance` (`balance_dollars` preferred, cents
cross-checked), polymarket **`GET /v1/account/balances`** — PLURAL, a list keyed
by `currency`, and `buyingPower` is the cap-comparable figure, NOT
`currentBalance`. Reading 21:07:32Z: kalshi **$11.55** cash / $40.54 with
positions; polymarket **$65.30** buying power / $123.89 cash. **NEITHER VENUE
CAN REACH ITS OWN DAY CAP** (4.2x and 1.5x over).

**THE VENUE SETTLES LIVE ORDERS** (`venue_settlement.py`, live-odds-worker, runs
BEFORE placing so the day's spend is freed first). Kalshi
`GET /portfolio/settlements`, Polymarket
`activities?types=ACTIVITY_TYPE_POSITION_RESOLUTION`. Won/lost from WHICH SIDE
WE HELD, never from our `side`/`line`. First run 21:36Z: `settled=3` with the
venues' exact P&L; **`settled_count` 12 -> 15**, the first outcomes on this board
scored from a venue record. Idempotent (3 -> `already` next tick).

**INFERENCE IS NOW THE FALLBACK, NOT A RACE.** `paper_settlement.settle_orders`
(refresh-worker) and venue settlement (live-odds-worker) both skip a graded
order, so whichever ticked first OWNED the row. A live order now waits
`SYNDICATE_VENUE_SETTLEMENT_GRACE_HOURS` (default 24) before inference touches
it — a DELAY, not a refusal, so a market the venue never settles still reaches
the ledger. Verified `awaiting_venue: 28`, the exact pre-deploy count of
filled-and-ungraded live orders.

**THE VENUE/INFERRED SPLIT IS NOW MEASURED AT SCALE, AND IT IS NOT SMALL.**
`[re-measured 2026-08-31T17:5xZ, lane layer2-accuracy-audit — supersedes the
n=3 reading that stood here]` Over 2026-08-24..08-30: the PAPER book (all
`settled_by=inferred`, 402/402) returns **+9.4% ROI** (47.9% win, +$156.32 on
$1,656.80); the LIVE book (real fills, venue-settled) returns **-5.5%** (42.3%
win, -$40.31 on $733.31). Per venue: `paper:kalshi` **+1.1%** (364 settled) vs
live kalshi **-7.6%** (159); `paper:polymarket` **+28.5%** (165) vs live
polymarket **-1.3%** (83). Same sign both venues, same direction as the old
n=3 reading. **STILL NOT A CONTROLLED COMPARISON** — the comparison book stakes
every eligible row at a venue price while the live book holds only what passed
the gates and filled, so selection is confounded with grading. Three live
candidates, none eliminated: optimistic inference, an unattainable paper price,
worse venue-available subset. **`settlement_summary` still does not split on
`settled_by` on the surface; the blend is what the page shows.** Zero paper
orders in the window were venue-settled.

## [portfolio-settlement] PORTFOLIO SETTLEMENT — the ledger crossed no service boundary, and the join keyed on a value that drifts `[verified 2026-08-22, lane portfolio-ledger-service-split]`

**SETTLEMENT BY SPORT `[verified 2026-08-26, lane kalshi-spread-join-sign]`:**
MLB settles (157 all-time). **WNBA settled ZERO until 2026-08-26** — the order
carries the OddsAPI board hash while `live_player_box_<date>.json` carries ESPN
ids, two namespaces that cannot meet, so every order refused
`game_not_in_live_box`. FIXED by matchup recovery on the WNBA tri-code pair
(`bet_status_wnba`), the same shape `bet_status_mlb` already used. Reading
16:24:12Z: `game_not_in_live_box` **9 -> ABSENT**, `graded` **0 -> 3**
(`outcomes={'won': 3}`), all-time wnba `0 -> 2`. **SOCCER IS STILL ZERO
ALL-TIME.** Its cause is known and a fix is deployed but UNDEMONSTRATED:
`live/soccer_live_lens.json` is a ROLLING SINGLE-DATE snapshot and both readers
gate on `date == selected_date`, so once it rolls the yesterday pass (which
`settle_orders` runs deliberately) can read nothing on refresh-worker. Dated
finals retention added; it only accumulates FORWARD.

**`/api/portfolio/summary` read `settled_count: 0, avg_clv: null` for weeks, and
settlement was never the cause.** Three defects, stacked; the first two are FIXED
AND LIVE, the third is fixed and live but UNPROVEN against real data.

**1. The ledger never crossed the web/worker boundary (`#502`).** The bet slip
writes `prediction_ledger.json` on WEB; the reconciliation autorun that settles
it runs on REFRESH-WORKER. All three services set
`SYNDICATE_DATA_ROOT=/opt/render/project/data` and **Render gives each its own
disk** (web `dsk-d8bi8prbc2fs73en7dig`, refresh-worker
`dsk-d91f7ggk1i2s73ar37a0`). One path string, two files.
`prediction_ledger.json` matches **none of the 151 `HOT_ARTIFACT_PATTERNS`**
(checked with `fnmatch`, both directions), so the publisher never carried it
either. FIXED: IO routes through the keyvalue store, disk written first as the
durable copy (Redis is a 256MB instance measured at 96% with 34,529 LRU
evictions), promotion upward-only so an empty worker ledger cannot shadow real
bets. Live both services `2aa1df54` 17:04Z.

**2. Settlement was reached once in 45 minutes (`#504`).** It sat 13th of 14 in
an exclusive `elif` chain, behind `mlb_refresh` and a soccer branch draining 44
units at one per 300s. Moved to 2nd, directly behind reconciliation. VERIFIED by
co-occurrence: `RECONCILIATION_AUTORUN_GATED` 18:28:38.192696 and
`LEDGER_INDEX_SIZE` 18:28:38.194012 — **1.3ms, same tick**, against **116s and a
different tick** before. Live `4eeffb5c` 18:18:05Z.

**3. The join keyed on `recommendation_id`, which is a SNAPSHOT HASH (`#505`).**
`record_recommendation` mints it over `prediction_id` + the whole recommendation
payload + `artifact_metadata`; `pipeline/intelligence_state.py:2028` already
says it comes from "a content hash of the full recommendation payload (incl.
live odds/edge/probability)" and drifts "purely from ordinary price drift". The
board re-records 150 recommendations per rebuild, so a bet's click-time id and
settlement's later id never meet. That is the `matched: 0` and
`4,560 no_key_match of 8,276` this repo already recorded. FIXED: a second tier
keyed on a stable identity modelled on `clv_opening_ledger._opening_key`,
bookmaker excluded (outcomes are book-independent) and segment excluded (the bet
slip never captures it), with disagreeing records marked ambiguous and REFUSED.
Live `a1e89ff3` 18:50:02Z, refresh-worker only.

**MEASURED FACTS worth not re-deriving:**
- A settlement pass over 3 dates costs **~40MB / 71s** — NOT the ~1.4GB the
  4.05-4.19x RSS coefficient predicts. That coefficient does not describe this
  path as run. It settled ZERO records though, so the WRITE path
  (`_replace_ledger_line`, a whole-chunk rewrite per settled record) is **still
  unexercised in production**.
- Current evaluation chunks: 95-332MB/day (largest `2026-08-16` at 331,787,011 B).
- Opportunity tracking and CLV BOTH run daily and are healthy:
  `BOARD_STATE_LEDGER_RECORDED recommendation_count=150` and
  `[clv_opening_ledger] OPENINGS ... already=1538 unkeyable=0`.
- **CLV is deliberately NOT wired to the portfolio.** `clv_join.py` states why:
  the ledger holds ~3 user bets against 11,864 opportunities, so
  `avg_clv` over 3 rows "is a metric with no denominator, which is worse than
  the honest `null` it returns today." `avg_clv: null` is a REFUSAL, not a bug.

**A BACKFILL CAN ONLY REACH HALF THE INPUTS** `[verified 2026-08-22 with
`fnmatch` against all 151 patterns]`. `settlement_inputs/closing_lines_*.csv`,
`settlement_inputs/finals_*.json` and `reports/intelligence/clv_openings/*` are
PULLABLE. `evaluation_ledger_chunks/<date>.jsonl` and its `index.json` are
**NOT REACHABLE** — not allowlisted, refresh-worker serves no HTTP. So "pull it
down and backfill locally" settles STRAIGHT bets only; parlays need the bridge,
which needs evaluation records that cannot leave the worker.
`scripts/backfill_portfolio_settlement.py` (preview-by-default) exists for this
and has NOT been run against production.

**NOT VERIFIED — `#505`'s `entity` mapping** (`player_name/player/name/team/
selection`) is reasoned from the bet slip's comments, never measured against
real evaluation records: the ledger is worker-local and not in
`HOT_ARTIFACT_PATTERNS`, so no service with an API can read it. The next
`[ledger_bridge]` line carries the breakdown that falsifies it —
`by_identity` large with `matched_by_identity: 0` means the mapping is wrong.

## [portfolio-sim-sizing-gate] ONLY A MODEL MEASURED TO BEAT THE MARKET SIZES MONEY; TODAY NONE IS, SO STAKES FOLLOW PRICE `[verified on production 2026-09-19 15:17Z and 15:48Z, lane sim-sizing-skill-gate]`

**CORRECTION 2026-10-19 (lane `ev-overstatement-decomp`, substrate: local fleet ledger, read-only): this title is no longer true. From 2026-10-05 (lane `stop-market-withholding`) the sim SIZES paper stakes again: its share of paper dollars by submit date was 0.00 on 10-02..10-04, 0.71-0.83 on 10-06..10-13, 0.52-0.62 on 10-14..10-17 and 0.27 on 10-18. Stakes rest on `portfolio_commit.py:761` (`fair + model_edge_pct/100`, shrunk only by `_sizing_skill_factor` >= 0.25). No staked-probability profile exists on the fleet (`<data root>/calibration/` is absent), so every cell is unfitted and sizes on the raw sim. On 4,876 settled EV>=2 orders the sim's fitted weight is -0.27 [-0.78, +0.18]. Its added dollars returned -12.2 +- 8.4% at EV>=4 against -3.3 +- 4.3% for the EV-only dollars, and pooled over EV>=2 they are no worse (-2.9 vs -3.2): unearned stake, amplifying noise. `findings_2026-10-19_ev_overstatement_decomp.md`; proposal in lane `sim-stake-unfitted-market-only` (todo #704).**

**STAKED-PROBABILITY PROFILE, verified 2026-10-22T16:46Z (lane `sim-stake-earned-profile`, fleet ledger read-only, fleet venv):** still NO profile on the fleet (`/home/amyn/syndicate-prod/data/calibration/` absent), and none can be fitted yet: per venue x sport x market x segment x phase, 0 of 321 cells reach 200 held-out rows (largest 189; 2,959 usable rows / 427 events, 10-02..10-21). Every measurable cell picks beta 0. The candidate profile is empty, so nothing was published. The reader keys `sport|market|segment` only, with no venue or phase (`portfolio_commit.py` ~776). `findings_2026-10-22_sim_stake_earned_profile.md`, todo #727.

USER 2026-09-19: "All sports". `portfolio_commit._sizing_model_edge` returns None
for a sim edge unless the row's `projection.model_skill` is `measured` +
`beats_market`, or the daily scorecard validated its bucket as a skill pocket
(`bucket_factor == 1.0`). Such a row takes the price-basis path: it is sized on
market fair, the sim cannot create, veto or shrink a bet, and the
`max_positions` cut ranks it without the sim term. The edge is still shown,
ranked on the board and recorded on the position (`sizing.sim_sizing`,
`sizing.basis = market_fair`).

- **Measured:** `sim_share_of_staked` was 0.25-0.39 on 09-19 plans before the
  deploy. After it (plans 10:16 and 10:47 CDT) it is **0.0**, with every
  sim-edge position market_fair and labels `gated_parity` / `gated_unmeasured` /
  `price_basis_sport`.
- **Why none is admitted:** all 31 `measured_market_skill` entries are parity (23)
  or loses (8). The `model-scorecard` cron's 146 cells carry 0 beats. WNBA's
  props, totals and spreads lose in the 2026-09-18 backtest
  (`[wnba-model-vs-board-mismatch]`).
- **Consequences:** in-play rows whose stake rested on the sim are refused
  `in_play_market_fair` (the default).
- **The input checklist's canonical row carries a `beats_market` note.** Remove
  it and the hard gate in `pipeline/portfolio_commit.py` stops every commit
  wherever MLB is not market-fair-allowlisted.
- **Off switch:** `SYNDICATE_PORTFOLIO_SIM_SIZING=legacy` (exact word).

## [order-model-attribution] AN ORDER RECORDS THE SIM'S VERDICT — DEPLOYED AND VERIFIED ON PRODUCTION; THE COMMIT GATE MAKES FOUR OF THE NINE VERDICTS UNREACHABLE `[verified on production 2026-09-04 00:03:26Z, lane order-sim-view]`

`sim_view` / `sim_line_gap` / `sim_probability_railed` are stamped onto the
position by `portfolio_commit._sim_view_of`, copied across the `OrderRequest`
boundary by `execute_portfolio`, and persisted by `execution_ledger`
(`_LEAN_FIELDS`), alongside `model_edge_pct`/`ev_pct` from `04187cdf`. The rule
is IMPORTED from the board's own `_layer2_board_columns`, never recopied — the
board attaches the verdict to `shortlist["cards"]` while the commit path prices
`shortlist["rows"]`, so there is nothing to read it off.

**THE LOAD-BEARING FACT, and it is about the ROW rather than the field** `[rewritten 2026-09-16, lane sim-view-reachability-caveat]`.
`contradicts`, `live_contradicts`, `unpriced` and `none` (FOUR of the nine
verdicts) are all computed where `model_edge_pct is None`. So an order carrying
one of them was sized on MARKET FAIR, never on the sim's edge. The row is
refused `no_model_edge_pct` unless its sport is on
`SYNDICATE_PORTFOLIO_MARKET_FAIR_SPORTS`, and refused `in_play_market_fair` in
play:

    ALWAYS REACHABLE (3)      agrees, live_agrees, neutral
    EV-CONDITIONED   (2)      disagrees, live_disagrees  -- placeable only when
                              the EV outruns the disagreement
    MARKET-FAIR ONLY (4)      contradicts, live_contradicts, unpriced, none

**These buckets FILL.** Paper ledger for 2026-09-16..17, read 22:46:11Z:
contradicts 38, none 159, unpriced 131, against agrees 130 and disagrees 4.
`contradicts`-vs-`agrees` settled ROI can therefore be taken, but it compares
SIZING BASIS as well as verdict: one bets price dispersion while the sim points
the other way, the other bets the sim's edge. Each bucket on
`/api/ops/execution/ledger-summary` carries `market_fair_only` (web
`c49ecd3d`). Pinned in BOTH allowlist states by
`test_a_contradicted_row_becomes_an_order_only_on_market_fair` and
`test_the_market_fair_only_set_is_exactly_the_rows_with_no_sim_edge`.

HISTORY, superseded: on 2026-09-03, with no sport allowlisted, all four were
refused at every ev_pct and the payload called the buckets "structurally empty
and stay empty". That became false when the allowlist named `ncaaf`
(2026-09-04) and all eight sports (2026-09-16). The tests pinning it read the
env implicitly and CI leaves it absent, so they stayed green; with production's
value they failed.

**\* `disagrees` IS REACHABLE BUT CENSORED, and the censoring is not random.**
The stake gates admit a disagreement only when the EV outruns it. Measured
through `commit_portfolio` at price -110:

    ev_pct 5.0   admits model_edge_pct -0.5  (-1.0 below_min_stake, -5.0 zero_kelly_stake)
    ev_pct 10.0  admits -2.0               (-5.0 below_min_stake)
    ev_pct 20.0  admits -5.0               (nothing in range refused)

`disagrees` orders are therefore systematically HIGH-EV against `agrees`
orders. **Any ROI comparison must control for `ev_pct`** — which is on the order
since `04187cdf` — or it measures the EV gap and reports it as a sim effect.

**THE READ SIDE IS BUILT** `[2026-09-03, same lane, NOT DEPLOYED]`.
`paper_settlement.sim_view_roi_summary()` cuts settled ROI by sport x market
family x `sim_view`, served as `sim_view_roi` on
`/api/ops/execution/ledger-summary` — the only keyvalue-aware reader of the
ledger, and it is handed the rows the endpoint ALREADY read, so the counts and
the ROI describe one snapshot rather than two reads seconds apart.

Buckets come from `_grouped` — the same function behind `by_market_family`,
`by_sport` and `by_venue_family` — so there is **one** ROI definition, not two;
`test_roi_matches_settlement_summary_on_the_same_rows` pins it. **Portfolio rows
only**, or the unrestricted book pools with its own `paper:<venue>` shadow
copies (proven discriminatingly: adding 5 shadow rows to 10 portfolio rows
changes nothing). Percentages stay `None` rather than `0.0` on an empty
denominator, inherited from `_grouped`.

The endpoint's aggregates-only shape is PRESERVED, not merely respected: the cut
emits counters, money sums and three label strings, and reads only `sport`,
`market`, `venue`, `mode`, `selected_date`, `status`, `outcome`,
`fill_stake_dollars`, `pnl_dollars` and `sim_view`. Verified over the whole
serialised response — no ticker, key, price, position key, event id or player
name survives.

`verdict_reachability` travels IN the payload: four verdicts hold only
market-fair-sized orders (`market_fair_only`, flagged on every bucket since web
`c49ecd3d`), two more are EV-selected, and pre-`cb223b62` orders are
`(unrecorded)`. The market-fair claim is re-derived from the commit gate with
the allowlist env SET in both states. The earlier test that read the env
implicitly is how "empty by construction" outlived its truth by 12 days.

**THE SAMPLE IS DECISIONS, NOT ROWS** `[2026-09-17, lane sim-view-roi-decision-count; web 6b26e0c1]`.
An order's identity includes `selected_date` and venue, so a bet planned on
several slate dates is several rows with one outcome. Every `sim_view_roi`
bucket now carries `decisions` and `settled_decisions`, keyed by
`_decision_key`, the same key `settled_decisions_by_sport` uses. A top-level
`sample` block counts bets that carry different verdicts on different slate
dates. Read 01:11:16Z (paper, 09-15..17): NCAAF 458 rows = 198 decisions; the
sample holds 373 decisions, 2 of them in two verdicts. **Quote
`settled_decisions` as n; ROI stays row-weighted** (each row is its own stake at
its own price).

Size cost, since `_LEAN_FIELDS` bounds a document two services
read-modify-write: +74 B/record, **+361 KB at the 5,000-record ceiling**, where
the whole ledger is ~4.40 MB against an 8 MB refusal — already 220% of its own
2 MB warn line before this change.

**DEPLOYED AND VERIFIED.** web `1d6b2f13` (read side, live 2026-09-03T23:14:37Z,
carried by another lane's deploy); refresh-worker + live-odds-worker `1e5ae2b1`
(write side, live 23:46:43Z / 23:50:56Z, both fired at `jobs_in_flight=0`).
**Ambiguous window 4.2 min — exclude orders written in it.**

**VERIFIED 2026-09-04 00:03:26Z** by the first non-`(unrecorded)` bucket,
`mlb | game_line | agrees`, on the served payload. That proves the write side
RAN (reachability, not presence), that `_LEAN_FIELDS` persists it, that the read
side serves it, and that both agree on the field name.

**WHAT THE ROI ARM IS ACTUALLY WAITING ON, measured 2026-09-04 01:5xZ: A
ONCE-DAILY JOB, NOT THE MATCHES.**
`EVALUATION_SETTLEMENT_ENABLE_REFRESH_WORKER_AUTORUN` is `true` on
refresh-worker, but `EVALUATION_SETTLEMENT_REFRESH_INTERVAL_SECONDS` is an
**EMPTY STRING**. Empty is falsy, so `if str(os.environ.get(...) or "").strip():`
(`run_refresh_worker.py:2039`) skips the interval override and the
**once-per-Central-calendar-day** gate applies, target hour default **06:00 CT**.
So `settled` cannot leave zero before ~06:00 CT / ~11:00Z however the matches
finish, and four identical hand-polls between 00:21Z and 01:27Z are explained by
that rather than by anything being wrong.

Two things follow. **`bet_status` and the ledger disagree ON PURPOSE and both are
right:** three soccer totals read `decided=True, status=lost` in the live view
while the ledger still counted them among 111 pending, because the live view
answers "is this bet winning" and `outcome` is written by settlement. **And the
empty string is a near-miss on a documented hazard** — `CLAUDE.md` records that
setting that key AT ALL overrides the daily gate and once produced 4 runs/day of
a ~1.4GB job. It currently behaves correctly by Python truthiness rather than by
intent, and reads as "set" to anyone scanning env vars.

**IT PROVES NOTHING ABOUT ROI, and the shape of the reading says so:**
`orders=1, settled=0, pending=0, unknown=0` ⇒ `execution_guard.is_non_position`
⇒ that order was REJECTED, never opened a position, and contributes $0 to staked
and pnl permanently. **The ROI arm still needs SETTLED rows carrying a verdict,
and none exist yet.**

**THE ROI ARM NOW HAS A DENOMINATOR** `[read-only measurement 2026-09-20 12:09:02 CT / 17:09:02Z, one fetch of `/api/ops/execution/ledger-summary?days=5&mode=paper`, scheduled task `ncaaf-sim-verdict-roi-read-0920`; full working in `log/2026-09-20.md`]`. NCAAF settled 832 of 899 orders (66 pending). Within `ncaaf | game_total`, all `market_fair_only: true` so the sizing basis is held fixed — `contradicts` n=71 settled_decisions, +$15.35 on $330.02, **+4.65%**; `unpriced` n=76, +$51.79 on $349.11, **+14.83%**; `none` n=78, -$76.39 on $376.02, **-20.32%**. `ncaaf | game_line` has no `contradicts` bucket; there `none` n=144 **-3.74%**, `unpriced` n=52 **+3.39%**. Different sizing basis, stated: `agrees` `game_line` n=34 **+16.90%**, `game_total` n=17 **-37.41%**; `disagrees` n=18 **-71.72%** / n=11 **-39.61%** (also EV-conditioned). Pooled `by_verdict`, all sports: agrees n=325 +12.64%, contradicts n=102 +9.84%, unpriced n=208 +7.63%, none n=259 -8.93%, disagrees n=71 -35.01%. **DESCRIPTIVE ONLY — at n≈70-80 a bucket's ROI standard error is ~12 points and a difference's ~16, so the 10.2-point contradicts/unpriced gap is inside one SE; no staking or sim change follows from this read.** 55 of 1,300 decisions sit in more than one verdict bucket.


## [min-ev-tuner-shadow] THE MIN_EV CUT IS TUNED PER CELL IN SHADOW -- RUNNING ON THE FLEET, ZERO MOVES, NOTHING APPLIED `[verified on production 2026-10-19 19:25:36Z, lane min-ev-tuner-shadow]`

- **What runs.** `syndicate/features/shared/min_ev_tuner.py`, once a day (>= 12:00Z) right after settlement in refresh-worker's
  intelligence-state loop.
  - **Cells:** venue x sport x market x season_phase.
  - **Rule:** propose +/-0.5 on a cell's EV cut only when the marginal band's ROI AND same-book CLV are both significant
    (event-clustered).
  - **Mode:** `SYNDICATE_MIN_EV_TUNER` is unset on the fleet, so `shadow`. Nothing at commit reads it;
    `effective_min_ev_pct` is unwired.
- **Verified 2026-10-19:**
  - refresh-worker `code=94c97011` (TERM 19:06:01Z).
  - First line `19:25:36.467Z MIN_EV_TUNER mode=shadow cells=60 actions={'hold': 60} base=0.0 moves=0`.
  - State `reports/intelligence/min_ev_tuner_state.json` readable via `scripts/min_ev_tuner_readout.py state`, run inside WSL
    with the worker state env.
- **Production's base cut is 0.0**, not 2.0: refresh-worker carries `SYNDICATE_PORTFOLIO_MIN_EV_PCT=0` (user decision
  2026-09-16), and there is no stored settings key. Rows reach the ledger at EV ~2+ because other gates bind first.
- **Loaded (verified 2026-10-22 readout 3/7):**
  - The full code runs on refresh-worker: effective-cut anchor, flat-unit grading, live-twin dedup, ladder skip and net-EV carry.
  - Daily pass: `mode=shadow`, 73 cells, all hold, 0 moves; `ladder_not_pre_registered` skipped 80.
  - Apply wiring is on main and INERT: `SYNDICATE_MIN_EV_TUNER` is unset on the fleet and no cell holds an override.
  - Taken-bet evidence is now mostly LIVE fills (~50/day); the EV-band ladder adds ~200/day below the floor, for the pre-registered LOWER rule.
  - Readouts are started by hand: the app scheduler does not fire on this host.
- **Evidence base:** settled paper venue orders only (paper:kalshi + paper:polymarket, 1,176 over 10-02..10-18). The 552 live rows
  are `venue_rebuild` rows with no `ev_pct`. Same-book CLV on venue MLB props is near zero (kalshi 49/266, polymarket 1/95).
- Detail: `findings_2026-10-19_min_ev_tuner_backtest.md`; deploys.md 2026-10-19 19:06:01Z; todo #701.

## [live-plan-empty-funnel] THE LIVE PLAN IS EMPTY BECAUSE THE VENUE'S OWN PRICE IS <= 0 EV AFTER THE TAKER FEE -- NOT A CAP, NOT A CHOSEN GATE `[verified on the fleet 2026-10-19 22:15Z and 2026-10-20 12:33Z, read-only, session 6200a74b]`

- **Funnel, median per build** (refresh-worker `LIVE_PLAN_WRITTEN` and its sibling lines):
  - 10-19 live window, 31 builds: board 4,096 -> Suggested 21 -> Kalshi scoped 9 / Polymarket 5 -> venue-feed priced 9 / 1.5 -> live positions 0 / 0.
    Kalshi had >0 in 6 of 30 builds; Polymarket in 0 of 30.
  - 10-20, 130 builds 01:21Z..12:33Z: Kalshi and Polymarket live positions 0 in 130 of 130. Polymarket venue-priced 0 in every build.
- **Whole board, re-priced at `quote.book_prices[venue]`**, 10-19:
  - Kalshi 556 sides quoted: 0 at >= +2% net of taker fee, 23 at 0 to +2%. 41 are at >= +2% before the fee.
  - Polymarket 324 quoted: 0 at >= +2% net, 5 at 0 to +2%.
  - 10-20: Kalshi 488 / 1 / 9, Polymarket 230 / 0 / 2.
- **Live settings** (refresh-worker env):
  - commit `min_ev_pct=0`, `max_positions=25`, bankroll $1,000, slate 0.2.
  - The effective floor is the board's Suggested flag (`SUGGESTED_MIN_EV_PCT` 2.0, net of fee, at the BEST book).
- **Caps** (stored, read 2026-10-19 22:15Z): $25 per order, Kalshi $200, Polymarket $100, all venues $150. The combined cap did not
  bind ($4.53 spent). These are superseded by caps-revamp's balance caps on `d3878d69` (deploys.md 23:55Z).
- **Executor on 10-19:** one Kalshi row (NCAAF DEL -3.5, $26.52) was refused `over_max_order_dollars` 14 times.
- **Since d3878d69** (compounding on, trim-to-cap loaded): 196 live passes from 23:50Z to about 12:38Z, all `positions=0`, so
  trim-to-cap has not been exercised. The one row paper2 commits on 10-20 is refused `below_min_stake_compounded` in live.
- **Polymarket balance:** the stamp's `dollars` 586.05 includes a 500.00 pending deposit (read 2026-10-19 22:15Z).
- **Maker entry is NO-GO:** `findings_2026-10-19_kalshi_maker_entry_paper.md`.
- Detail: `findings_2026-10-19_live_execution_empty_plan_funnel.md`.


## [ledger-price-units] THE EXECUTION LEDGER HOLDS TWO PRICE UNITS; EVERY KNOWN READER NOW HANDLES BOTH `[verified 2026-10-22, code + fleet ledger, lane fitter-contract-price-units]`

- **The rule:** a price strictly inside (0, 1) is a venue CONTRACT price; anything else is American odds. One implementation each:
  `paper_settlement.profit_per_dollar` (profit), `execution_ledger._price_as_probability`, `prediction_ledger._implied_from_price` (CLV).
- **Which column is which on a LIVE order:** `requested_price` = the plan's venue price in AMERICAN, and `ev_pct` is stamped against it
  (`venue_scope.py`); `fill_price` = contract price paid. A paper fill copies requested into fill. So back `fair` out of `requested_price`, and
  take profit/return at `fill_price`.
- **Readers fixed:** CLV (`d1a7ffbe`, #719); offline fitters `fit_probability_calibration`, `fit_staked_probability`, `ev_overstatement_decomp`,
  `paper_bet_optimization` (`4c7134a7`, `97dca15b`). Fleet ledger 2026-10-22 (12,111 orders): calibration live rows kept 6 -> 72, decomp 6 -> 73 of 73,
  paper rows byte-identical. Already unit-aware before: P&L, `venue_settlement`, `execution_exits._probability`.
- **A NEW reader of `fill_price` must use one of the three functions above.** Read as American, 0.65 is a 0.65% profit / 99.4% implied, and the row
  either drops silently or skews a fit with no error.

---

## [order-clv-opening-less] AN ORDER WITH NO RECORDED CLV OPENING IS GRADED FROM THE QUOTE LOG ON ITS OWN IDENTITY -- ON MAIN, NOT ON THE FLEET `[verified 2026-10-22, fleet ledger + replay, lane venue-order-opening-gap]`

- **The openings file has a ceiling and hits it.** `clv_opening_ledger._MAX_LEDGER_BYTES` = 32 MiB, ONE file per date for ALL sports. Fleet 09-30..10-23: full on 6 of 24 dates (10-04, 10-10, 10-11, 10-17, 10-18, 10-21; 10-11 stopped at 19:03Z). Every bet first sighted after the cut has no opening -- in the CLV report AND for orders. **FIXED (`22e3a0aa`) AND LIVE ON THE FLEET since 20:35Z 10-22, verified 20:43:10Z `dropped=0`** (lane `clv-openings-ceiling`, todo #732, `.syndicate/findings_2026-10-22_clv_openings_ceiling.md`): per-(date,sport) 64 MiB + per-date 128 MiB, `OPENINGS_CEILING_HIT` when it fires; >= 36,228 openings were lost over the 6 days (10-21 exact 3,939).
- **The departures file has the same shape, one tier lower.** `clv_departure_ledger._MAX_LEDGER_BYTES` was 8 MiB, ONE file per date for ALL sports. Fleet 09-30..10-23 (read 2026-10-22 20:25Z): it has NOT fired (0 of 2,184 refresh-worker DEPARTURES lines for 10-16..10-22 say `truncated=True`); peak 10-17 7,938,374 B (94.6%); NBA wrote 2.35 MiB on Wed 10-21. **FIXED `a77077a2`, ON THE FLEET since 21:15:11Z 10-22 (load read 21:28Z: new DEPARTURES fields, `ledger.bytes` == file size)** (lane `clv-departures-ceiling`, todo #734, `.syndicate/findings_2026-10-22_clv_departures_ceiling.md`): 16 MiB per (date,sport) + 32 MiB per date, `DEPARTURES_CEILING_HIT`, heartbeats kept, a refused sport censored (`censored` in the heartbeat) so the scorecard reads `unobserved`, not `kept`.
- **Venue orders key on the venue's book.** `venue_scope` rewrites `quote.bookmaker`; the board records an opening only for its best book. So a venue order often has no opening of its own key.
- **Before the fix:** 523 of 7,777 settled mlb/ncaaf/nfl paper orders had no opening (330 ceiling, 193 venue-scoped), every one `no_close_for_market`/None.
- **Fix `f5113511` (origin/main, NOT on the fleet):** `order_clv` resolves an order the resolver never saw from the quote log (submitted_at = open, same in-play/not-started/arrow-of-time rules); failures `no_opening:<reason>`; marks carry `opening_source=order`. Replay: 0 -> 149 resolved (75 same-book); residual 374, of which 318 are in-play bets (no pregame close by definition).
- Detail: `.syndicate/findings_2026-10-22_venue_order_opening_gap.md`; todo #729.

---
