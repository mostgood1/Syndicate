# state — portfolio

Split out of `state.md` by `scripts/split_state.py`. Bodies are verbatim.
The INDEX of every subject, across every part, is in `state.md`; the
one-subject-one-section rule is global and spans these files.
Same rules as state.md: when a fact changes, EDIT THE LINE.

## [portfolio-live-surface] `/portfolio` IS THE LIVE BUYING ENGINE, the venue caps BIND, and the VENUE now settles our bets `[verified 2026-08-27T00:0xZ, lanes portfolio-live-primary / portfolio-venue-caps-editable / venue-balances-on-portfolio / venue-settlement / venue-first-refusal / open-bet-live-status]`

**`/portfolio/live` NO LONGER EXISTS as a page** — it is a 302 to
`/portfolio#live` carrying the query string; `portfolio_live.html` is deleted.
`/portfolio` renders the execution ledger's real orders AND the prediction
ledger's user-logged bets, labelled, never summed. `/portfolio/paper` untouched.

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
