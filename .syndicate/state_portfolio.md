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

## [order-model-attribution] AN ORDER RECORDS THE SIM'S VERDICT — DEPLOYED AND VERIFIED ON PRODUCTION; THE COMMIT GATE MAKES FOUR OF THE NINE VERDICTS UNREACHABLE `[verified on production 2026-09-04 00:03:26Z, lane order-sim-view]`

`sim_view` / `sim_line_gap` / `sim_probability_railed` are stamped onto the
position by `portfolio_commit._sim_view_of`, copied across the `OrderRequest`
boundary by `execute_portfolio`, and persisted by `execution_ledger`
(`_LEAN_FIELDS`), alongside `model_edge_pct`/`ev_pct` from `04187cdf`. The rule
is IMPORTED from the board's own `_layer2_board_columns`, never recopied — the
board attaches the verdict to `shortlist["cards"]` while the commit path prices
`shortlist["rows"]`, so there is nothing to read it off.

**THE LOAD-BEARING FACT, and it is about the GATE rather than the field.**
`contradicts`, **`live_contradicts`**, `unpriced` and `none` — **FOUR of the
nine verdicts, not three** `[count corrected 2026-09-03 in the same lane; the
first record missed `live_contradicts`, which sits in the same branch]` — are
all computed where `model_edge_pct is None`, and `sizing_inputs_from_row`
refuses that row by name (`no_model_edge_pct`) before anything is sized, **at
every ev_pct**. Measured by running the real `commit_portfolio` over one row per
verdict class:

    agrees     PLACED     contradicts  REFUSED  no_model_edge_pct
    neutral    PLACED     unpriced     REFUSED  no_model_edge_pct
    disagrees  PLACED*    none         REFUSED  no_model_edge_pct

The nine verdicts fall into three classes, and the middle one is the
dangerous one because its buckets FILL UP and look like a fair sample:

    ALWAYS REACHABLE (3)      agrees, live_agrees, neutral
    EV-CONDITIONED   (2)      disagrees, live_disagrees  -- placeable only when
                              the EV outruns the disagreement
    UNREACHABLE      (4)      contradicts, live_contradicts, unpriced, none

**So a STORED order can only ever carry `agrees`, `disagrees`, `neutral` or a
`live_` form — and the `contradicts`-vs-`agrees` ROI split that
`layer2-sim-disagrees` pre-registered has a denominator that is structurally
zero and stays zero however long the ledger runs.** Persisting the field was
NECESSARY AND IS NOT SUFFICIENT. Corroborated on production the same day:
`/api/portfolio/paper` served 41 orders — mlb 29, soccer 12, **no NCAAF**, which
is where the contradictions live. Pinned by
`test_a_contradicted_row_still_cannot_become_an_order`.

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

`verdict_reachability` travels IN the payload, because four buckets are empty by
construction and two more are EV-selected, and a reader without that reads the
gap as a broken join. **That claim is re-derived from the live commit gate at
three EVs by a test**, so it cannot go stale silently.

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
