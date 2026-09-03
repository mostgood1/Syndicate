# state — board

Split out of `state.md` by `scripts/split_state.py`. Bodies are verbatim.
The INDEX of every subject, across every part, is in `state.md`; the
one-subject-one-section rule is global and spans these files.
Same rules as state.md: when a fact changes, EDIT THE LINE.

## [live-lens-snapshot] THE LIVE-LENS SNAPSHOT CANNOT BE DATED — it is a 4 MB KEYVALUE key, not a file, and archiving it would cost ~5.76 GB/day against a 256 MB store `[measured 2026-09-03, lane mlens-snapshot-dating]`

`data_root()/live/<sport>_live_lens.json` is ONE undated, MUTABLE object. It is
why `#625`(5) had to declare five blocks of the board artifact UNREPLAYABLE, and
the obvious fix — date it — **must not be built.** Measured at one instant:

- **IT IS NOT A FILE.** `_KEYVALUE_EXCLUDED_PATH_MARKERS` is only
  `migration_runs/`, so `live/` routes to the KEYVALUE store. That is also why
  `/api/ops/artifacts/export` reports **0 files under `live/*`** while the
  pattern IS allowlisted — the inventory globs a disk the object never touches.
- **SIZE: `live/mlb_live_lens.json` OCCUPIES ~4 MiB, ONE key — and that is an
  ALLOCATED size, not a payload size `[corrected 2026-09-03]`.**
  `/api/ops/keyvalue/usage` reports allocator-rounded memory: the two
  single-key buckets sit exactly **+96 bytes above a power of two**
  (4,194,400 = 4 MiB+96; `prediction_ledger.json` 2,097,248 = 2 MiB+96) while
  multi-key buckets have arbitrary gaps, which is jemalloc rounding large
  values to powers of two. **The true payload is in (2 MiB, 4 MiB].** The
  decision below is unchanged — even at the 2 MiB lower bound, 1,440 ticks/day
  is ~2.9 GB/day against a 256 MB store, ~11x capacity — but the figure first
  published was overstated by up to 2x.
- **STORE: 222.28 MB of 256 MB (86.8%), policy `volatile-lru`, 12,203 keys
  already evicted.** `reports/intelligence` alone is 189.51 MB of it.
- **COST OF DATING: 4 MB x 1,440 ticks/day = ~5.76 GB/day for MLB ALONE**, about
  22x the whole store's capacity, and five sports write on the same 60s tick.
- **AND IT WOULD BE UNRELIABLE AS WELL AS RUINOUS.** A path containing a date
  token automatically takes a TTL (`_default_keyvalue_ttl_seconds`), and under
  `volatile-lru` ONLY keys with a TTL are evicted — so dated snapshots would be
  the FIRST thing dropped. The archive would be partial with no way to know
  what was missing.

**WHAT WAS DONE INSTEAD:** the board artifact's `live_game_state` block now
carries a `lens_fingerprint` — a sha256 of the NORMALISED games plus counts and
the snapshot age, **98 bytes** on an artifact that IS dated, disk-backed and
mirrorable. It does NOT make the correction reproducible. It makes a divergence
**ATTRIBUTABLE**: two boards can be compared, and a replay can say "I had a
different lens input" instead of diverging for unstated reasons. The hash is
over the normalised games, not the raw payload, because the raw payload churns
on timestamps that change nothing.

## [layer2-board-keyvalue-ceiling] THE BOARD'S CEILING IS THE COMBINED KEY, NOT THE SHARDS — and `per_sport=3000` corrupted production for ~29 min `[verified 2026-08-31 18:25-20:0xZ, lane layer2-cap-raise]`

**Rows are sharded per sport and the merge SERVES the board.** `combined_keeps_rows=False`
on the writer while web served 1,634 rows — an empty combined key cannot otherwise
yield rows. Board 932 → 1,634 at `per_sport=1000`.

**`per_sport=3000` BROKE IT.** The combined key carries card/metadata that scales at
~2,200 B/row **even with `rows: []`** (3,754,595 B at 1,634 rows; 9,648,192 B at
4,552). The write refused at `9,648,192 > 8,388,608` **after the shards had already
landed**, freezing `shard_row_total=1635`; the merge then dropped
`unplaceable=2917` rows and **all of NCAAF**, for ≥3 cycles. It does not self-heal.
So the ceiling is **~3,600 TOTAL rows**, not per-sport, and shard headroom says
nothing about it.

**Live config (refresh-worker only):** `SYNDICATE_LAYER2_ROWS_PER_SPORT=1000`,
`SYNDICATE_LAYER2_ROWS_TOTAL=3000`, `SYNDICATE_LAYER2_COMBINED_ROWS=0`. Web and
live-odds-worker carry NO `LAYER2` keys. **`ROWS_TOTAL=3000` is UNEXERCISED** —
today's board is ~1,600 rows, so it has never bound.

**Fixed and live** (`865c89be` 19:46:59Z, still in live `132559e1`): the merge sizes
from `max(index_total, highest_position+1)`, so a refused write leaves the board
STALE not WRONG, and `written_at` comes from the shards when stamps disagree —
without that the corrupted board reported `18:02:05Z` while serving 18:25 rows and
was **unfalsifiable** to any watcher keyed on `written_at`.

**THE FLIP IS VERIFIED IN PRODUCTION `[2026-08-31 22:50:26Z]`.** `cards` split into
per-sport keys makes the combined key FLAT in row count (451 → **0 B/row**,
measured on the real writer). `SYNDICATE_LAYER2_CARDS_INLINE=0` is live on
refresh-worker `7e678674`; web `7e678674` was deployed FIRST and its deployed SHA
confirmed to contain `_hydrate_layer2_cards` (it had ZERO an hour earlier — that
gate prevented a silent `cards_present=0`). Two clean pre-flip cycles passed
(1468==rows, 1498==rows, three sports each).

**EXERCISED AND PASSED** on the first rebuild under the flip: `combined_keeps_cards=False`
with `cards_present=2216 == rows`, all three sports — the writer stopped filling the
combined key AND web served every card back from the shards. The combined key is now
FLAT in row count, so the ~3,600-row ceiling that made `per_sport=3000` corrupt the
board is GONE. **A cap raise is now defensible but UNATTEMPTED, and must be measured
against the COMBINED key, not the shards** — that mistake caused the 18:25Z incident.
The 1534 → 2216 row change is SLATE (soccer 187 → 834), not headroom. **REVERT:** set
`SYNDICATE_LAYER2_CARDS_INLINE=1` and redeploy.

**CAPS NOW STAGED AT 2000/6000, NOT DEPLOYED `[2026-09-01 01:3xZ]`.**
`SYNDICATE_LAYER2_ROWS_PER_SPORT=2000` + `ROWS_TOTAL=6000` are SET on
refresh-worker but the live SHA `6d024dc7` predates them; the 75% warn threshold
(`c461693e`) is on main and also undeployed. Both apply on the next
refresh-worker deploy by anyone. **MEASURED SAFE against REAL production rows —
combined key 220 B (0.0%), worst shard 50.6–55.2%** — which is the check that was
skipped before the 18:25Z incident. **UNTESTED AND UNTESTABLE TONIGHT: the board
is MLB-ONLY at ~547 rows** (slates finished; `LAYER2_BOARD_HEALTH` 01:14:48Z mlb
547, ncaaf 0, soccer 0), so nothing approaches even the OLD 1000 cap. Verifiable
only on a full multi-sport slate. **Two caveats:** the shard percentage is
SLATE-DEPENDENT (same config read 55.2% on a three-sport board, 50.6% on tonight's),
and 3000/sport sits at 74.6% — just UNDER the 75% line, so the warning is NOT a
guard against a 3000 raise.

**ALL THREE INCIDENT DEFECTS ARE CLOSED AND VERIFIED `[2026-09-01 00:15Z]`:** (1) the
refused write that left CORRUPTION not staleness — `865c89be`; (2) the shed that could
not shrink the combined key — cards split + flip; (3) the size instrument that measured
a payload nothing writes — `6d024dc7`, live 23:41:30Z on refresh-worker.
`SHORTLIST_PERSIST_LARGE` is GONE; `LAYER2_KEY_LARGE` reports **one number per KEY** and
names the lever that matches whichever key is biggest. Verified over two builds
(23:54:28Z, 00:15:02Z): both counters 0, `cards_present == rows`. Before the fix it fired
on EVERY build at `88.5 → 90.6 → 116.8 → 122.5` pct on a healthy board, advising a cap
that was not the constraint. **Do not act on any surviving reference to
`SHORTLIST_PERSIST_LARGE`; it no longer exists.** `openings` needs no split — `openings_index` never reaches the artifact.

**The board is GROUPED BY SPORT and always was** (FLOOR-THEN-MERIT, `layer2_board.py:2744`,
`4ef894e3`/#524) — NOT a sharding artifact. Reading `rows[:25]` reads the top of the
FIRST SPORT, not the board.

## [layer2-realized-accuracy] THE LAYER 2 BOARD'S REALIZED ACCURACY — the portfolio book is the surface, and the measurement chain is broken in four places `[verified 2026-08-31T17:3x-18:0xZ, lane layer2-accuracy-audit]`

**START HERE FOR ANY BOARD-ACCURACY QUESTION, NOT AT THE EVALUATION LEDGER.**
`pipeline/portfolio_commit.py:357` commits BOTH the paper and live portfolios
straight off `read_layer2_shortlist`, so `/api/portfolio/paper?date=` and
`/api/portfolio/live` are direct measurements of this board. The evaluation
ledger is the learning loop's INPUT, not the accuracy surface, and it currently
settles 0.2% (19,692 settleable, 35 settled).

**7 days, 2026-08-24..08-30, by bet type (paper):** game_line 142 settled 56.7%
**+25.3% ROI [95% CI +7.2..+43.4]** — the only bucket excluding zero;
game_total 141 / 47.5% / +9.8% [-9.3..+29.0]; player_prop 119 / 37.8% /
**-13.5%** [-33.5..+6.5]. **REAL MONEY INVERTS game_line:** h2h+spreads
12W-23L = **34.3% win, -23.9% ROI**. By sport (paper): mlb 375 settled (93% of
all), wnba 22, soccer 5, nfl 0, **ncaaf 0 — never bet, ever**.

**FOUR BROKEN LINKS, each measured, working backward from the board:**
1. **Board retention is ~4 days.** `/api/board/layer2-shortlist?date=` answers
   `no_shortlist_artifact` for 08-25/26/27. No retrospective longer than that
   is possible.
2. **MLB grading joins ~1 game in 14. FIX IS LIVE AND HAS NOT MOVED THE
   NUMBER. DO NOT RECORD THIS AS FIXED.** `[2026-08-31, lane layer2-accuracy-audit]`
   Baseline across the full window, both disks agreeing: `rows.all` =
   1/1/2/1/1/1/7 for 08-24..08-30 with 0/14/14/6/12/12/13 `Missing game-line
   match` warnings — **14 graded rows total, 71 lost joins.** That supply is
   what starves settlement (19,692 settleable, 35 settled).
   **WHAT IS LIVE:** `49c43aeb` (`_odds_paths` best-found-not-first-found +
   `daily/snapshots/` search), `04185203` (multi-date backfill), `a35591dc`
   (publish the rebuilt payload). `132559e1` (re-run a date that built but
   never published) is on main, NOT live.
   **THE BACKLOG REGRADE RAN AND RECOVERED NOTHING.** All seven dates rebuilt
   `ok=True` 19:03:47-19:08:33Z, each in **0.4-0.9 seconds** reporting
   `cards: 1`. A 14-game slate cannot be joined and graded in 0.4s. `ok=True`
   is an exit code, not a result.
   **WHY THE 14/14 PROOF DID NOT TRANSFER — READ THIS BEFORE TRUSTING ANY
   ARTIFACT-BASED PROOF IN THIS REPO.** The fix was proven on the freeze and
   live docs pulled from `/api/ops/artifacts/export`, **which runs on WEB and
   reads WEB's disk**. refresh-worker has its own disk. The proof established
   "the resolver works given these files present" and was used to claim "works
   on the worker", which was never tested. Presence is not reachability, across
   a service boundary this repo documents.
   **RESOLVED, and the resolver fix WORKS `[verified 2026-08-31 20:33Z]`.** The
   freeze IS reachable on refresh-worker at `daily/snapshots/<date>/`:
   2026-08-30 now reads `(pregame-freeze, 14 games)` with `Missing game-line
   match` **13 -> 0**, and raw moneyline candidates went **1-4 -> 12** against
   three pre-fix control dates. **The graded ROW count did not move (7 -> 7)**
   because `caps.ml = 1` absorbs the whole gain — so my claim that the join
   rate was starving settlement is **FALSIFIED by its own fix**. Graded rows
   come from the locked card, i.e. the policy's picks. See `todo #610`.
   **MLB prop supply is a SEPARATE defect (`todo #611`):** the prop pregame
   seal has produced nothing since 2026-08-16, so hitter/pitcher props grade
   against a post-slate remnant (~1 game). Leading cause **cadence** — measured
   2026-08-31, the MLB refresh ran 22:12:30Z against a 22:05:00Z first pitch,
   so `slate_started` was True and props were skipped by design. Not yet proven
   to be the whole cause. MLB odds refresh runs on **live-odds-worker**.
   **THE READING THAT DECIDES IT** is the always-on diagnostic shipped in
   `49c43aeb`: `Game lines read: <path> (pregame-freeze|live, N games)` in the
   payload warnings. `(live, 1 games)` => freeze unreachable worker-side, fix
   inert in production. `(pregame-freeze, 14 games)` => freeze found, failure
   is elsewhere. **It needs `132559e1` deployed** — the seven payloads carrying
   it were built before the publish call existed and nothing exports them.
   **MARKERS CANNOT BE CLEARED FROM OUTSIDE, measured:**
   `keyvalue/expire-run-artifacts` returns `matched_keys: 1` (surgical) and
   `skipped_no_run_stamp: 1` (refuses — run-stamped keys only); `keyvalue/sweep`
   only touches 10-day-stale keys. Hence the self-heal in `132559e1`.
   **THREE INSTRUMENTS WERE BLIND, all chosen for reachability rather than for
   answering the question:** `/mlb/api/market-accuracy` (wrong disk, and the
   backfill had no publisher), `graded_rows_available` (STALE — `epoch`
   unchanged for ~2h; moves only when the settlement autorun fires), and the
   builder's `stdout_tail` (JSON summary only, no warnings).
3. **NCAAF has never produced a graded row.** `_ncaaf_graded_rows_for_date`
   reads `cfbd_lines_*.json`; zero in the hot-artifact set.
4. **Soccer's biggest board market is ungradeable by construction.** Grader
   covers 3-way ML / totals@2.5 / BTTS; the board's #1 market is
   `alternate_totals_corners`, **573 of 2,623 rows (22%)**.

**THE FUNNEL IS THE OPTIMIZATION TARGET.** Refusals 08-24..08-31:
`no_model_edge_pct` **2,506**, `below_min_ev_pct` 1,567, below_min_stake 46,
zero_kelly 37 — ~4,150 against ~458 orders. Board side agrees:
**`model_edge_pct` is numeric on only 902 of 2,623 rows (34.4%)**,
`model_ev_pct` on 201. `ev_basis` = market_fair 1,451 / model_edge 184 /
model_probability 17 / unset 971 — on a `market_fair` basis the board is a
stale-price detector, not a model-vs-market edge.

**BOARD QUALITY, n=2,623 over the 4 dated snapshots:** books_quoting<=1 on
**1,511 (57.6%)**; book_age median 4,498s, **p90 36,816s (10.2h)**, >6h 21.3%,
`suspect_stale` 8.8%; movement not tracked 42.1%; `ev_pct`>0 on only 444
(16.9%), median **-2.35%**; model_skill measured 625 / unmeasured 882 / no
projection block 1,116. **Composition mismatch:** soccer 51% of board / 1.2% of
settled bets; ncaaf 33% / 0%; mlb 16% / 93%.

**NOT MEASURED, and it is the read that decides how to rank:** whether the
board's own `ev_pct`/`model_edge_pct`/`score` PREDICT the outcome. The
portfolio endpoints serve settlement marginals only (`by_sport`,
`by_market_family`, `by_venue_family`), never per-order rows, so no calibration
curve exists. Exposing settled orders with their board fields is the unblock.

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

## [board-freshness] BOARD FRESHNESS AND STALENESS

**THE BOARD HAS TWO INDEPENDENT CAUSES, and fixing one is not enough.**

- **Cause 1 — refusal rate.** 96.7% of board cycles were refused before any work:
  146 `MEMORY_GUARD_ABORT stage=pre_source_state_fingerprint` against 5 completed
  builds. **The guard doing the refusing protects a stage Layer 2 never runs**
  (`_MIN_SAFE_MEMORY_HEADROOM_BYTES`, sized for `build_intelligence_overview`).
  Production's own proof they are independent: on 3 of 5 builds
  `CANDIDATE_POOL_READY count=0` while `LAYER2_SHORTLIST` returned `rows=256` on
  the SAME cycle. `[measured 08-14 14:39Z]`
- **`#387`'s Layer 2 fix is CLOSED-VERIFIED on a full 3h clean window** —
  37 refreshes = 11.9/hour vs 1.7 baseline, longest gap 11.8 min vs 104.7,
  96 `MEMORY_GUARD_ABORT` (so not a boot-confounded quiet period),
  `LAYER2_GUARD_SKIP` 0, zero OOM. All five criteria met. Residual confound
  stated: abort rate 30.8/h vs 48.7/h baseline. `[measured 08-14 19:24Z]`
- **Cause 2 — THE QUOTE INPUT IS NOT MOVING *IN THE PREGAME REGIME ONLY*.** A
  shortlist rebuilt every 5 minutes off a 2-hour-old quote shard is a board that
  LOOKS fresh and is not — **strictly worse than one that is visibly stale,
  because nothing on it says so.** `[measured 08-14 15:1xZ]` **SCOPED 08-15
  02:5xZ: this holds for the empty-slate pregame regime. During a live slate the
  quote input moves every ~1 min and the BOARD REBUILD becomes the binding
  constraint instead — the arrow reverses.** See ODDS CADENCE.
- **QUOTE CHANGE → SERVED UI, END TO END, MEASURED. `[measured 08-15
  02:38–02:58Z, live MLB slate]`** Method:
  `end_to_end = row age_seconds + (server_time − generated_at)`, validated
  against an absolute book timestamp to a 22 s residual — which is what proves
  `age_seconds` is stamped at BUILD time, not at serve time.
  - **Layer 1** (`/api/board/book-grid?sport=mlb`), 15 samples at 60 s over 4
    builds: **min 143 s / p50 451 s / max 698 s** = **2.4 / 7.5 / 11.6 min**.
    Build gaps 10.8 / 5.1 / 4.2 min. Network is not a term (client−server −0.3
    to −0.7 s). **The floor is the board rebuild interval, not the 60 s fetch —
    capture is 6–10× faster than the board can consume it.**
  - **Layer 2** (`/api/board/layer2-shortlist`, which carries its own
    `written_at`): `written_at` **01:53:44Z unchanged for 64+ min**; end-to-end
    3660 → 4022 s (**61 → 67 min**), monotonic, **no rebuild observed**, so this
    is a LOWER BOUND, not a sawtooth. **CONFOUNDED — do not use as a baseline:**
    refresh-worker took three deploys in the preceding 31 min (`ae7318a2`,
    `934b3b81`, `548ded38`, all `#435`). `LAYER2_FAST_REFRESH` since 01:30Z =
    **0** and `MEMORY_GUARD_ABORT` = **0**, so it is NOT the known guard
    refusal — it simply was not running; worker alive and healthy at 02:51Z.
  - **Still unmeasured: a pregame-window end-to-end, and a deploy-free Layer 2
    window.** Both numbers above are live-slate, one sport.
    Full read: `.syndicate/tier5_quote_to_ui_2026-08-14.md`.
- **Layer 1 is NOT dark. `[re-measured 2026-08-16 16:26–16:37Z, lane
  `layer1-board-coverage`]`** The earlier "`count=0` on ~3 of 5 builds" reading
  did NOT reproduce: **4 distinct consecutive MLB builds, all non-zero**, and
  WNBA and soccer non-zero on every one. Same-instant sweep at 16:19:52Z —
  mlb 2,843 rows / 1,941 projected (68.3%), soccer 6,453 / 1,704 (26.4%),
  wnba 872 / 305 (35.0%); nba/nhl/ncaab correctly `no_precomputed_grid_artifact`.
  **Projection coverage does move build to build** (mlb 2,107 → 1,935 projected
  across 16:33:49 → 16:35:06 with `rows` flat at 3,006), so an availability
  claim needs the build stamp, not one read. Program Tier 4.
- **The candidate-pool path serves NEITHER board** and is the real deletion
  candidate. Layer 1 and Layer 2 are **siblings off the shared grid**, not
  sequential — which is the mechanism by which L1 can fail without L2 noticing.

---

## [live-surface-tier5] THE LIVE SURFACE — Tier 5 `[measured 08-15 02:3x–03:0xZ]`

Full read with per-module evidence: `.syndicate/tier5_live_modules_2026-08-14.md`.

- **There are 30 `live`-named modules under `syndicate/**`, not 16.** No
  definition yields 16. All 30 were read. **Importer counts must be
  AST-resolved** — a basename grep for `live_lens` collides across eight sports
  and reports `live_lens_loop` as having 0 app importers when it has 2.
- **Nothing here is "an abandoned approach still costing compute."** Breakdown:
  **1 dead** (`features/live_ui_audit.py`, zero importers anywhere incl. tests —
  an argparse CLI parked in `features/`; the only clean deletion), **2 unwired**
  (soccer's projector, below), **11 request-only** (every `live_*_accuracy` /
  `live_prop_audit`, reachable solely from a route — zero background cost), and
  the rest running on purpose.
- **The core MLB path is SEVERED, not scaffolding** — a complete pipeline cut at
  one merge line. See THE PUBLISHED SHORTLIST above.
- **CORRECTED 2026-08-15: "no live GAME-LINE projection exists" is true of what
  is PUBLISHED and FALSE of what is COMPUTED.** *(Restored 2026-08-15 — these
  lines were committed as `fd23c6bc`, then dropped by the 74KB→64KB collapse at
  `7f7d8d88`, which left this section asserting the refuted claim. Do not
  re-collapse without re-reading.)* `estimate_live(LiveSituation(...))` runs in
  production on every live-lens tick, **120 sims per live game**, off the current
  inning/half/outs/bases/score/batter/pitcher, returning `homeWinProb`,
  `awayWinProb`, projected `total` and `homeMargin`
  (`vendor/.../flask_frontend.py:16573`, wired into `_build_game_lens`:16806).
  **Proof it runs:** `LIVE_MC_BAIL` instruments every failure exit;
  live-odds-worker logged exactly **9 bails/tick across 11 consecutive ticks, all
  `status_not_live`**, against a slate of **9 Final / 5 Live** — the live games
  never bail. One exit (`away_score is None`) is uninstrumented, so this is proof
  by exhaustion with one named hole. `[measured 08-15 03:0x–03:2xZ]`
- **It dies in THREE places, and the middle one was re-scoped after measurement:**
  1. `mlb/live_lens.py:1094` — the merge rejected the MC lens for exactly the live
     games (the card's text-derived lens already satisfies
     `_lens_rows_have_projection_signal`); same shape as the prop sever at :1109,
     fifteen lines earlier. **FIXED as `0e0b0aa1`. BOTH DROPS DEPLOYED AND
     WORKING — `live_mc` 0 → 6, CONFIRMED END TO END.** `[measured 08-15 21:49Z]`
     The worker's own per-tick tally reads
     `liveMcSources = {live_mc: 6, segment_projection: 52, unknown: 8}` and web
     SERVES `rows=66 live_mc=6`. **Six and six — the producer's count and the
     served count match**, which is what makes it end-to-end.
     **RETRACTED: my earlier "both drops live and `live_mc` still 0, a clean
     negative" was PREMATURE.** Those passes ran 3 and 8 minutes after the worker
     restarted at 20:56:07Z, inside the live-lens loop's warm-up. **Two reads
     inside one warm-up window are ONE read** — the slate moving between them
     made them independent of each other, not independent of the transient.
  2. **`/mlb/api/live-lens` serves a report WEB WRITES ITSELF.** It reads the
     worker's keyvalue snapshot and, when it judges it stale, DISCARDS it and
     rebuilds locally with the MC hard-refused by
     `refuse_if_compute_in_request_path`. Max age **60 s** vs a **60 s** worker
     tick. **There are THREE live-lens artifacts, not two**, and the published
     disk copy is not the one the surface reads. **FIXED as `4bd7dbb3`, DEPLOYED
     ON WEB** (`9b88d05b` live 19:54:18Z; superseded by `f475c775`, which
     content-checks as carrying both drops and descends from it, so not a
     revert). Carry-forward is bounded 300 s, refused on unreadable age, refused
     on a settled game, stamped with a non-resettable `liveStateAsOf`.
- **INSTRUMENT, corrected twice — read this before verifying anything here.**
  `[measured 08-15 20:0xZ]`
  - **`mlb_source/data/live_lens/…` CANNOT show the lens, ever.** It is the SLIM
    shape from `scripts/refresh_mlb_oddsapi.py`; a game row's keys are exactly
    `{gamePk, startTime, status}` and **`gameLens` is not a key at all**. Earlier
    guidance in this file naming it as the instrument was wrong.
  - **`/mlb/api/live-lens` WAS blind and is now the CORRECT instrument** — it was
    blind because web's rebuild destroyed the lens, and `4bd7dbb3` removed
    exactly that. The rule inverted when the fix landed.
  - **`modelHomeWinProb` is NOT a valid signal: 60 of 60 rows carry one at
    baseline**, stamped on the `first1/3/5` lanes by `_live_margin_win_prob`.
    **`source == "live_mc"` is the only discriminator.**
  - **BASELINE for the pending worker deploy** (`/mlb/api/live-lens`, 15 games /
    4 live): `gameLens rows 60`, **`live_mc` 0**, `liveStateCarriedForward` 0.
  3. ~~`live_projection_join` is entirely prop-shaped; there is no game-line
     join at all.~~ **BUILT AND WIRED as `758a89fa` (Drop 3), DEPLOYED NOWHERE.**
     `shared/live_gameline_join.py` + one call site in `build_book_grid_artifact`
     emitting a `live_gamelines` coverage block, kept separate from
     `live_projections` so one family's zero cannot look like the other's.
     Joined on FULL TEAM NAMES, which match exactly (`matchup.home.name` ==
     `home_team`, verified in production) — **no alias table, deliberately**,
     since the prop join's 91% miss is a market-NAME aliasing failure.
     **SHIPPED: Drop 3 is live on refresh-worker** (`f8ca54e1`, and still
     present on the current live `d72d670c` — verified by content, not ancestry).
     **Expect `rows_live_gameline_edged: 0` at first and do not call it a
     defect:** at 120 sims the 2-sigma bar is ~9.1 pp at p=0.5, so a balanced
     slate refuses by design (recorded decision, spec §8.1).
- **THE LIVE GAME-LINE POPULATION IS 8 ROWS PER BUILD, and the counters are now
  reachable from an API.** `[measured 08-16 03:00Z, 2 games live / 13 Final;
  artifact `generated_at 03:00:00.538Z` streamed off web]`

      live_gamelines       considered 8  projected 2  priceable 0  edged 0
                           withheld 8 = {segment_is_not_full_game: 6,
                                         prob_interval_swamps_edge: 2}
      live_gameline_ledger candidates 0  written 0  enabled true

  - **`index_size` COUNTS SNAPSHOT GAMES CARRYING A `live_mc` LENS, NOT LIVE
    GAMES — the "3 → 8 → 10 is unexplained" handoff line is RESOLVED and nothing
    is broken.** Census at 03:0xZ: 10 of 15 = **8 Final + 2 Live**. A Final keeps
    its last lens, so the number is monotone across a slate. The join filters on
    `game.state == live` on the GRID side, so the Final entries are never used.
  - **The ledger recorded nothing because its population was empty by
    construction, not because of a defect.** v1 recorded `priceable` rows only.
    **FIXED as v2 and SHIPPED** — `5c419007`, live on refresh-worker
    **04:24:33Z**; `LEDGER_VERSION = 2` content-verified on the currently live
    `d72d670c`, which a later deploy carried forward. Records every PROJECTED
    row, keeps `priceable`/`withheld_reason`/`sigma` as fields.
    `LEDGER_VERSION` 1 → 2 because the POPULATION changed: **filter any reader on
    `v` before aggregating**, or the rate spans two denominators.
  - **`/api/board/book-grid` dropped `live_gamelines` and `live_gameline_ledger`**
    though the artifact carries both — second instance of that bug in that
    function. **FIXED AND SHIPPED — web `ebd5f677`, live 03:38:07Z.** Both keys
    read `null` before and serve objects after, measured across two different
    artifacts (03:37:13Z and 03:39:36Z). The ~10 MB
    `/api/ops/artifacts/stream` workaround is no longer needed.
  - **BOTH HALVES ARE DEPLOYED, AND v2 HAS NEVER BEEN EXERCISED.** web
    `ebd5f677` 03:38:07Z, refresh-worker `5c419007` 04:24:33Z, each parented on
    its own service's LIVE SHA — **`main` is an ancestor of NEITHER service's
    live tree** (13 commits live-only on refresh-worker, 33 on web at the time).
    The slate ended between the last pre-deploy build and the first post-deploy
    one, so v2 went live with **zero live rows to act on**; as of 15:17Z on 08-16
    the board reads `index_size 0, considered 0` because nothing is live yet.
    **The test is the scheduled `live-gameline-ledger-check`, 08-16 20:30
    Central.** The discriminator for v2 is `written` rising on rows that are
    **not** priceable — `skipped_unchanged > 0` is NOT it, having already been
    observed under v1.
  - **CORRECTION — "the recorder has never recorded a row" is FALSE.** The
    04:22:51Z pre-deploy build read `priceable 1, candidates 1,
    skipped_unchanged 1`, and `skipped_unchanged` cannot be non-zero unless a
    matching record is already on disk (`_moved(None, rec)` is True, so an empty
    file always writes). **v1 wrote at least one row on 08-15**, between 02:4xZ
    and 04:22Z. The 03:00Z reading above is real; generalising it to a whole
    night was the error.
- **WHERE THE HUNT STANDS AFTER BOTH DROPS `[measured 08-15 21:1xZ]`. Two
  hypotheses are DEAD — do not re-run them:**
  - **"Drop 1 is bypassed; `_persist_live_lens_report` never runs on a tick" —
    FALSIFIED.** `_live_projection_enhancement_payload` has **exactly one
    caller**, `mlb/live_lens.py:1384`, inside that function, and it is the only
    in-process import of the vendored `_live_lens_payload` in the MLB path. The
    `LIVE_MC_BAIL` lines prove it executes.
  - **"the MC bails on live games" — FALSIFIED.** 100 log samples,
    time-contiguous 21:05:27–21:11:04 across multiple whole ticks, **100%
    `status_not_live`** (90 Preview, 10 Final). A live game cannot emit that
    reason and none of the other six appears. **NB: my first evidence for this
    was a saturated 40-of-40 sample and was worthless — re-query
    time-contiguous, and check `hits == limit`.**
  - **REMAINING HYPOTHESIS, NOT A FINDING:** the MC takes the ONE uninstrumented
    exit, `if away_score is None or home_score is None: return None`
    (`flask_frontend.py:16611`), which emits nothing. It is the only silent path
    left. **Nothing has observed it.**
- **THE MEASUREMENT THAT SETTLES IT IS COMPUTED EVERY TICK AND WAS DISCARDED.**
  `_tally_mlb_live_mc_sources` (`live_lens_loop.py:473`) counts
  `live_mc / live_projection / segment_projection` per lane into
  `meta["liveMcSources"]`. `live_lens_loop_status_payload()` had **zero
  callers**. A route now exists — `GET /api/ops/live-lens/status` (`09b345ee`),
  **committed, NOT deployed, and its broader ops regression was interrupted and
  never ran.** Read `enabled`/`threadAlive` from it as the CALLING service's,
  not the worker's.
- **Allowlisting `reports/live_lens_loop/latest_live_lens_tick.json` is INERT —
  do not try it.** `_KEYVALUE_EXCLUDED_PATH_MARKERS` is only
  `("migration_runs/",)`, so the path is keyvalue-backed on every service and
  `write_json_file` returns before any disk write, while
  `/api/ops/artifacts/stream` gates on `target.is_file()`. It would turn a 403
  into a 404.
- **live-odds-worker `earlyExit`s roughly every 6.5 h** — `server_failed`,
  `evicted: False`, at 01:37 / 08:05 / 14:34 / 20:03 on 08-15 (**events API**,
  not logs). A refresh run launches on boot, so **this service's deploy gate is
  closed almost continuously**: 76 min of polling yielded one sub-minute CLEAR.
  **`predictions.full` IS pregame at source** — the vendored payload sets
  `"predictions": card.get("predictions")` verbatim, so no merge line downstream
  can make it live. Served surface confirmed the effect before the fix: 56
  `gameLens` rows, lanes `first1/first3/first5` only, `source: None`, **0 with
  `modelHomeWinProb`**.
- **The compute cost of a live game-line projection is ALREADY BEING PAID** — the
  MC runs on both workers today regardless. Publishing it is not new periodic
  work, which is what makes this cheap against the `#435` memory constraint.
  **The open question is precision, not existence:** 120 sims puts the standard
  error on a win probability near **4.6 pp** at p=0.5, which is display-grade and
  not edge-grade. `MLB_LIVE_GAME_MC_SIMS` is env-tunable (min 20).
  Full spec: `.syndicate/spec_live_game_line_projection.md`.
- **`live/nfl_live_lens.json` and `live/soccer_live_lens.json` are built every
  tick and NEVER published to web.** `live_lens_loop.py:150` builds five sports
  (`mlb, nba, wnba, soccer, nfl`); `artifact_publisher.py:433-435` allowlists
  three (`mlb, nba, wnba`). **The two omitted sports are in season; the
  allowlisted NBA is not.** That same publisher block already carries a written
  post-mortem of this exact bug for the three that ARE listed
  (`SKIP_NOT_ALLOWLISTED`, "just a plain missing entry") and records the cost:
  refresh-worker's fallback recompute had `prop_row_counts=[0]*9` across nine
  live games. **Two lines; needs no product decision.**
- **A working live game-line projector already exists — in soccer, unwired.**
  `soccer/features/live_lens.py` exports `project_live_match`,
  `goal_in_window_probability`, `project_live_player_props`, built on
  `match_simulator.simulate_match`'s `initial_state` hook. Reachable only from
  `scripts/backtest_soccer_live_lens.py` and `scripts/poll_soccer_live_state.py`,
  **neither scheduled** (no cron, no `render.yaml`, no worker import; the
  soccersim phase-1 report records the poller as never run). Costs zero compute.
  **"Build the live game-line projection" is therefore not green-field
  everywhere — name this asset in the decision rather than discovering it after.**

---

## [ask-the-syndicate] ASK THE SYNDICATE

**The LLM is off by decision. The deterministic snapshot path is the product.**

- **CURRENT BASELINE: 37/52** (advice 4/5, entity 9/10, explain 4/6, history 2/5,
  lookup 8/8, ranking 7/10, refusal 3/8), measured 2026-08-16 18:0xZ and again
  post-deploy with **zero pass/fail flips**, in
  `reports/ask_regression/{control_pre,post}_answer_substance_2026_08_16.json`.
  `answer_source: snapshot` is the EXPECTED source, not a finding.
  **This REPLACES the 38/52 recorded on 2026-08-15 — that figure was a different
  day's slate and had expired.** Re-measure a same-slate control before judging
  any change; a handed-down baseline is not a baseline.
  **The harness cannot see most of what the panel does.** `_score` checks
  refusal/routing/hallucination/certainty/50-50 and is blind to selection shape,
  units, price, sim terms, quote age and the rendered panel. Four deploys on
  2026-08-16 changed all of those and could not move it. **A flat score is
  therefore not evidence of no effect, and a large jump would be suspicious.**
- **Ask baseline RE-CONFIRMED after all six deploys, 22:2xZ on live `d8985df8`:
  37/52, ZERO pass/fail flips vs the same-slate control, every class identical.**
  `reports/ask_regression/post_all_deploys_2026_08_16.json`. One warning moved —
  `edge_without_market_probability` 0 → 25 — and it is BOARD DATA, not the Ask
  code: the board path's `edge`/`market_probability` are unchanged across all six
  deploys (`git diff ebd5f677 d8985df8`), while **4 of 10 edge-bearing rows now
  carry a `model_edge_pct` not derivable from
  `projection.{model_prob_over, market_fair_prob_over}` by either the direct
  difference or the complement** — including two rows where `row_side ==
  proj_side` so no complement applies and the direct figure is off by 64 and 19
  points. All `full/*_dist` bases. Owned by `layer2-board-quality`, notified.
- **ASK ANSWER SUBSTANCE — LIVE web `9bae928c` (2026-08-16 22:52:31Z).** The
  deterministic panel now: names the bet a human can place (market, line, side,
  price, book — not "Ryan Johnson"); generates its own reason sentences from
  `projection.projected` and `model_skill` (the MLB game lens is the model);
  publishes only rows where EVERY edge term it carries is positive; and reports
  a quote age that advances. `_bet_label` mirrors `layer2_board._pick_label` and
  is pinned by test — the two must not drift.
- **`quote_seen_age_seconds` IS STAMPED AT ARTIFACT BUILD TIME AND DOES NOT
  TICK.** Three reads of the live shortlist 45s apart returned byte-identical
  ages (`mlb=[12.9, 39.8] wnba=[47.1]`) while `written_at` sat at 20:15:41Z.
  **Every consumer of that field understates quote age by the artifact's own
  age** — real age is `stamped + (now - written_at)`. Ask corrects for it; other
  surfaces have not been checked. Its sibling `book_age_seconds` answers a
  DIFFERENT question ("has the price moved") and the board gates on the seen
  clock deliberately — see `layer2_board._row_quote_age_seconds`.
- **WITHDRAWN 2026-08-16 22:5xZ — "the board publishes sides that contradict
  its own projection" was MY error, not a board defect.** Chasing it to a root
  cause showed only **2 of 10** failing rows are explained by live-join
  staleness; the rest are a category error in the Ask reason generator.
  `projection.projected` is a **MEAN**, and what picks a side is
  **`P(X > line)`** — on a low-line count prop those diverge legitimately (a
  mean of 0.214 runs implies `P(>=1) ~ 19%`, which beats a market implying
  15%). **Do not re-open this against the board.** Ask now claims a direction
  only on GAME totals/margins, where the mean is the right statistic; on props
  it states the relationship as a fact. Fixed in web `9bae928c`.
- **STANDS, AND ITS ROOT CAUSE IS CONFIRMED — `model_edge_pct` is not
  comparable with `projection.{model_prob_over, market_fair_prob_over}` after a
  live join.** `live_gameline_join.py:643` overwrites `edge_vs_market_pct` with
  the LIVE edge while deliberately leaving `model_prob_over` at its PREGAME
  value (the live probability goes to a new `live_model_prob_over` key). The
  edge therefore refers to a different probability than the one beside it, with
  nothing in the field name to signal it. **7/7 separation on `live_aware`**;
  arithmetic exact — stated `-39.93` = `(0.1917 - 0.591) x 100`, where the
  pregame pairing gives `+27.46`. Every number is correct; only the PAIRING is
  wrong, which is why it is `full/*` only (segment bases are not live-joined
  and agree 3/3). Owned by `layer2-board-quality`, notified with the fix
  options. Consumers pairing those two fields must prefer `live_model_prob_over`
  when `live_aware` is true.
- **K1 SHIPPED AND VERIFIED** (`bef782cb`, live 20:01:18Z): 20/52 → 23/52,
  `refusal` 3/8 → 6/8, every other class byte-identical, declined-question
  latency 10.9s → 0.19s. **A refusal gate must be tested on what it must NOT
  refuse** — two regressions were caught only by testing the answer direction.
- **CURRENT PRODUCTION SCORE IS 38/52 `[measured 08-15 17:5xZ, live 1e44e1da]`.**
  **K6 IS NOT PART OF THAT NUMBER AND IS NOT LIVE.** Its fix `3ba1c2cf`
  ("source the as-of from `state_meta` too, because production has no
  `freshness` key") was cancelled mid-build at 19:20Z by a peer's deploy and is
  **still absent from live `7abd8e12` at 20:22Z, confirmed by patch-id**. It is
  built, tested and pushed as `deploy/ask-k6-2026-08-15` (`3d68dfe4`), never
  fired. So the ask lane's own `K6 RETRACTED AS INERT ON PROD` still stands:
  **no as-of predicate has been measured on production.**
  Pre-deploy control **25/52** (`reports/ask_regression/prebaseline_c774fe1a_2026_08_15.json`).
  entity **2/10 → 9/10**, lookup **4/8 → 8/8**, ranking **5/10 → 7/10**;
  advice 4/5, explain 4/6, history 2/5, refusal 4/8 all flat. **Zero classes
  regressed.**
  - **ATTRIBUTION: the gain is the `ask-sport-coverage` deploy**
    (`b6f1a2e6`/`0bf866c3`), NOT the web train that followed it. The train
    reproduced 38/52 and added the WNBA clamp and MLB live lens on top. Do not
    credit the train with 13 points.
  - **THE "23/52" BASELINE IS DEAD.** `post_m1_fixed_2026_08_14.json` is a
    ranking-only run with `total: 10`; that number existed only in prose and was
    propagated into three briefs. Use 25/52 as the pre-deploy control, or a run
    you took yourself.
  - Slate caveat, so a flat class is not misread as a failed fix: production was
    **nfl 60 / mlb 39 / wnba 6, zero soccer / ncaab / nhl**, so the soccer
    classes could not move on this measurement whatever the code does.
- **THE TWO-POOL DIVERGENCE IS CLOSED** — web `c774fe1a` (live 2026-08-15
  03:29:56Z), lane `ask-headline-from-board` CLOSED-VERIFIED. `M1`
  (`b16eb1f7`) only SUPPLEMENTED (`visuals.tables`) and left the headline on
  the snapshot, so chat and the board still read 23.81 vs 14.09.
  `_market_summary_schema` now sources `top_opportunities` from
  `read_layer2_shortlist` — the same artifact `/api/board/layer2-shortlist`
  serves. **Measured same-instant: chat 6.35 vs board 6.35, |delta| 0.000**,
  fingerprinted 5/5 rows carrying `source="layer2_shortlist"`.
  Two guards were bought with a rollback and must not be removed:
  the board REPLACES a non-empty `recommendations` pool and never CREATES one
  (an empty pool is the engine DECLINING — sourcing unconditionally answered an
  Ohtani stats question with NFL totals, refusal 4/8 → 3/8), and board rows
  carry explicit `edge_pct` because `edge` is a FRACTION on snapshot rows and a
  PERCENT on board rows (`Best edge 635.0%` served for 14 min).
- **SPORT COVERAGE FIXED AND MEASURED** (`0bf866c3`, live 16:49:28Z) — the
  08-14 finding above (soccer/ncaab had no branch, NFL required the FULL team
  name, wnba was a keyword inside nba) is CLOSED on the routing axis:
  **25/52 → 38/52, zero regressions, `no_sport_resolved_expected_*` 15 → 0.**
  entity 2/10 → 9/10, lookup 4/8 → 8/8, ranking 5/10 → 7/10. Board composition
  identical at both instants (150 rows, wnba 18 / nfl 42 / mlb 90), which is
  what makes the diff attributable. `[measured 08-15 16:52Z]`
- **BUT soccer / ncaab / nhl coverage is UNPROVEN ON DATA.** The board carried
  **zero rows** for all three at both measurement instants, so those cases pass
  on ROUTING only. Whether the new fetcher branches return anything useful on a
  real slate is NOT established — re-measure when soccer is on the board.
- **NFL nickname matching must NOT be copied to NCAAF.**
  `_ncaaf_teams_in_question` excludes mascots deliberately (~680 schools share
  "Wildcats"/"Tigers"). NFL is safe only because its 32 nicknames are unique
  (verified). `[from-code + measured 08-15]`
- **K6 CAUSE CONFIRMED AND FIXED IN `origin/main`, BUT NOT DEPLOYED.**
  `routed_sport` shipped and works; the as-of did not. `as_of` is populated
  **28/52** and `warn:no_as_of_stated` is **24** on the live tree — unmeasured
  and unmoved until `0050d1c4` reaches production. **Do not mark K6 closed.**
  **Cause (measured, not suspected):** production web runs
  `SYNDICATE_INTELLIGENCE_CANONICAL_BOARD_STATE = true` AND
  `SYNDICATE_INTELLIGENCE_COMBINED_BOARD_DEFAULT = true`, **while the comment at
  that call site still says the flag is "default off, so this is a no-op
  today".** That path (`read_combined_intelligence_response`) returns
  `state_meta` and **no `freshness` key at all** (`state_meta.computed_at` was a
  valid `2026-08-15T18:36:33Z`). `read_latest_intelligence_state` has FOUR return
  paths with DIFFERENT payload shapes, so anything reading `freshness` off the
  snapshot works on a dev box and is inert in production. The fix scans
  `("state_meta", "freshness", "state_freshness")`, matching
  `pipeline/intelligence_state.py`'s own order. `[measured 08-15 18:3xZ]`
- **K3's `build_evidence_pack` sport-filter item is DEAD CODE** — reachable only
  from the LLM engine, which never executes by standing decision. `[from-code]`
- **Chat reads the shortlist ARTIFACT directly**, so chat staleness IS artifact
  age. `[from-code]`
- **The system prompt's rules 5–8 (surface uncertainty, distinguish fact from
  projection, never fabricate, flag staleness) are now PERMANENTLY UNENFORCED.**
  They were the only place those rules existed; the deterministic path needs its
  own. That is a consequence of the decision, not a pre-existing defect.

---

## [ui-board-cards] UI / BOARD CARDS

- **THE GAMES RAIL AND THE BOARD CARD JOIN ON `sport_slug`, NEVER ON `sport` — and the LABEL comes from the chip's league `[verified in production 2026-08-27, web `78a95c7f` / `0e964af8` / `fb9261b8`, `#589`/`#590`/`#591`]`.** Two fields, and they are not interchangeable: `sport_slug` is the SLUG, `sport` is a DISPLAY string that for soccer's steam, prop and `#162` game-candidate paths is the **LEAGUE** (`"la liga"`). Every chip index in `loadGameChips` is keyed on `chip.sport` == the slug, so keying a lookup on `sport` returns null for a chip that is present — which is how one La Liga game seated two rail cards. `gameKey` had always read `sport_slug || sport`; `chipForGame` and `group.sport` read the same two fields with the OPPOSITE precedence, ten lines apart. **`chip.league_display` is the authoritative label: populated 213/213 on soccer chips across 10 leagues, and NULL on every mlb/nfl/wnba chip** (`game_chip_scoreboard.py:467` says so), so reading it cannot relabel another sport. Measured A/B, control = pre-change served bytes, one payload: 250→248 cards / 2→0 duplicate chips; head labels `SOCCER=213`→ten leagues; subtitles `SOCCER=489 LA LIGA=7`→ten leagues with 496 rows joining a league-carrying chip on both sides.
- **NO OTHER SPORT CAN HAVE THAT LABEL SPLIT `[code, 2026-08-27 — NOT a production reading for nba/nhl/ncaab]`.** The registry sets `name` to exactly `slug.upper()` for mlb/nba/wnba/nfl/ncaaf/ncaab/nhl (`intelligence.py:113-120`) and soccer's `"Soccer"` matches too, so `sport.get("name")` never diverges; the only override reads `league_display`, and every producer of that field imports `league_display_name` from `features/soccer/sources.py`. Measured 0 divergent rows for mlb/nfl/ncaaf/wnba on two payloads. **NBA, NHL and NCAAB had zero games and zero chips that day — covered by the code argument only.**
- **`data-syndicate-sport` IS AN IDENTIFIER ON THE MONEY PATH, NOT A CAPTION `[2026-08-27, `#591`; ledger half verified independently by lane `open-bet-live-status`]`.** `bet_slip.js:174` and `watchlist.js:129` read that attribute and `bet_slip.js:254,271` POST it as a bet's `sport` into `prediction_ledger`; **`settle_orders` and the venue resolvers KEY ON `sport`**, so a bet written as `"LA LIGA"` never joins a settlement source and **sits unresolvable forever rather than failing loudly**. It was being fed `item.sport`. Both sites now write the slug uppercased, matching `market_board.js:463,587`. **HAZARD, NOT CORRUPTION — measured twice, two sessions:** `/portfolio` holds `{mlb: 167, wnba: 17, nfl: 7, soccer: 2}` over 193 rows and no league string anywhere. Second time in one day that a UI-side display value turned out to be load-bearing on the execution ledger.
- **`bet_slip.js`'s POSTed units are CLEAN `[checked 2026-08-27]`:** `odds` is AMERICAN and `/api/portfolio/bets` stores it verbatim via `_coerce_float`; `stake` is dollars; `implied_probability` is a separate ledger field the slip never populates, so there is no odds→probability crossing. **Latent shape, not a live bug, in a file this lane did not own:** `prediction_ledger._coerce_probability` maps `1 < x <= 100` to `x/100`, so a value arriving in the wrong vocabulary INSIDE that band is silently rescaled (American `+50` → `0.50`) while `+150`/`-110` correctly become `None` — loud at the extremes, silent in the middle.
- **Lane E is CLOSED-VERIFIED in production** (web `aadcde77`, live 21:42:56Z):
  horizontal overflow 28px desktop / 20–40px mobile → **0 at both widths** on
  nfl, ncaaf, soccer, ncaab; NCAAF default tab 0 panels/187px → 1 panel/556px;
  orphan tabs and unreachable panels → 0; mobile tab targets under 44px 64/48/4
  → 0; numeric classes `normal` → `tabular-nums`. `[measured 08-14 21:4xZ]`
- **Lane F is CLOSED-VERIFIED and live** (web `932a1f71`, then `a86eb4ed`):
  seven fabrication sites in `game_board_contract.py` are gone — an absent
  probability renders as an explicit empty state, a genuine 0.0 survives instead
  of becoming 50/50, and a projected scoreline is never recast as a win split.
  Soccer three-way markets carry a draw segment. One null placeholder (`—`)
  platform-wide: NCAAF hyphen cells 48 → 0, em dashes 0 → 144. `[measured 08-15 01:41Z]`
- **A 50/50 on the board now MEANS 50/50.** The one still served (NFL, DEN@KC)
  sits on a 0.4-point projected margin — the producer's own `home_win_rate`.
- **NCAAF kickoffs file on their CENTRAL day** — 28 of 157 real 2026 kickoffs
  were previously filed under their UTC day. **The platform's display timezone is
  Central everywhere**; `central_today_iso()` is the slate clock. An MLB slate
  spans two UTC dates; it does not span two Central ones.
- **`scripts/ui_layout_probe.py` is the durable instrument.** It reproduced the
  audit's before-numbers against the unchanged service, which is what makes its
  after-numbers a reading rather than a belief. **Synthetic `el.click()` is not
  used anywhere in it — the audit had to retract a finding produced that way.**
- **NBA / NHL / NCAAB serve 0 cards** in production and locally. Their rows in
  the divergence matrix are code-only. **Re-measure in October.**
- **Carried, not fixed:** the desktop strip still breaks long names mid-word in a
  ~52px box — a design decision that CONTRADICTS Lane G1's "raise soccer's 13px
  names to 16px", since 13px + ellipsis is the documented fix for that problem.
- **The prop-producer 0.5 fix is COMMITTED AND NOT ON ANY WORKER** — **SUPERSEDED
  08-15 22:2xZ: it is LIVE on both workers, by content. See the deploy section
  above; this paragraph is kept only for its local sizing numbers.**
  (`bd40056c` / origin `536dfcd0`). Local sizing: 6 of 4,240 probability rows
  were price-missing and every one carried a fabricated 0.5; **67 further exact-
  0.5 rows have real ±100 prices and are legitimate** — a blanket "no 0.5
  anywhere" rule would have destroyed real data. Production rate UNMEASURED.
  **Until a worker deploy carries it, production still fabricates.**

---

## [layer2_board_display] LAYER 2 BOARD -- USER-VISIBLE DISPLAY BUGS, 2026-08-20 AUDIT

### 2026-08-21 -- FOUR MORE, ALL THE SAME SHAPE: a number computed in one frame, displayed in another `[code + artifact evidence, NOT a served-board read -- see the gap below]`

Found from a user screenshot of the served board (one MLB game, all LIVE rows).
Fixed on `claude/layer2-odds-refresh-kbcxs8`, lane
`layer2-sim-view-and-live-projection`. **NOT deployed** -- `autoDeploy = no`.

- **`Win%` WAS THE BOOKS-QUOTING MULTIPLIER, NOT A PROBABILITY.** `layer2_board.py`
  published `score["book_confidence"]` as `confidence`, and
  `intelligence.html:2180` renders `confidence` as the column labelled **Win%**.
  So **"Win% 100%" meant "5+ books quote this market"**. Confirmed 5/5 against the
  screenshot with nothing left over: 1 book -> 50%, 2 -> 70%, 3 -> 85%, 14 -> 100%,
  21 -> 100%, exactly `_book_confidence`'s `((1,0.5),(2,0.7),(4,0.85))` ladder.
  This is the most severe of the four: a reader takes it as a certainty.
  Now carries the side-correct model probability; blank where there is no model.
- **`model_probability` WAS THE WRONG SIDE'S.** `layer2_board.py` published
  `projection["model_prob_over"]` with no side awareness. That field is always the
  OVER/HOME framing -- the same file proves it at `_model_edge_for`, which maps
  `"home": model_prob_over`. `sim_view` IS side-adjusted, so **away and draw rows
  rendered a coherent badge beside the other side's probability**. Repro:
  home -> `agrees`/0.62 (right); away -> `disagrees`/0.62 (away is 0.38).
  Fixed by `_model_prob_for_side`, mirroring `_model_edge_for`'s three-way/two-way
  logic rather than reimplementing it.
- **THREE HITTER MARKETS COULD NEVER PROJECT.** `_HITTER_BUCKETS` named mean fields
  that do not exist in the artifact, so `projected` was `None` on every row of
  those markets forever -- indistinguishable from thin model coverage.
  Measured at bucket-row level against a real `daily_summary` (2026-07-10):

      batter_runs_scored  wanted runs_mean     artifact writes  r_mean
      batter_doubles      wanted doubles_mean  artifact writes  2b_mean
      batter_triples      wanted triples_mean  artifact writes  3b_mean

  Matches the screenshot exactly: all 8 `batter_runs_scored` rows blank, every
  `batter_hits`/`batter_rbis`/`batter_hits_runs_rbis` row populated.
  **MEASURED BEFORE/AFTER ON THE SAME REAL ARTIFACT** (15 games, 6,210 hitter
  bucket rows), which is the strongest evidence in this whole block because it
  is a coverage number rather than a code reading:

      market               mean key BEFORE   before        after (r_mean/2b_mean/3b_mean)
      batter_runs_scored   runs_mean          0/810   0%     810/810   100%
      batter_doubles       doubles_mean       0/270   0%     270/270   100%
      batter_triples       triples_mean       0/270   0%     270/270   100%

  **0% -> 100% on 1,350 projections.** Values are the right MAGNITUDE, not merely
  non-null: triples projects 0.058 against P(1+) 0.057, and for a rare event the
  mean must approximate the probability -- a wrong-field join would not do that.
  **THE FILE ALREADY KNEW** -- `_HRR_COMPONENT_MEANS` is
  `("h_mean", "r_mean", "rbi_mean")`, so the HRR derivation read runs correctly
  while the runs MARKET did not, twenty lines apart.
- **THE LIVE SIM'S VERDICT WAS UNLABELLED.** `live_projection_join` already
  recomputes `edge_vs_market_pct` from `live_prob_over`, so on a re-priced live row
  `sim_view` WAS the live sim's -- nothing said so. "our pregame model dislikes
  this" and "the re-sim, watching the game, dislikes this" rendered identically.
  Now `sim_view: live_disagrees` + `sim_basis`, gated on
  `projection["basis"] == "live_resim"` and NOT on game state, so a pregame
  projection sitting in a live game is not mislabelled live.
- Also: exactly-zero `model_edge_pct` was bucketed as `agrees` (`>= 0`); now
  `neutral`. And `pipeline/layer2_shortlist.py` now PRINTS the live-join
  telemetry (`LIVE_PROJECTION_JOIN sport=... projected=... lens_indexed=...
  miss_player=...`), which previously existed only inside the artifact payload --
  so "why is the Live column blank" was unanswerable from production logs.

**THE VERIFICATION GAP, STATED SO IT IS NOT CITED AS DONE:** none of this was read
off the served board. This session's egress proxy returns **403 for
`syndicate-an21.onrender.com`**, so the evidence is code + the real artifact files
+ the user's screenshot. Per this section's own 2026-08-20 note, checking the raw
shortlist row shape is NOT sufficient for this class of fix -- the read owed is of
`boardContract.cards`. Tests discriminate (5/5 fail pre-fix, pass post-fix), which
is not the same thing as a production measurement.

**Blank LIVE cells are NOT all a bug.** `attach_live_projections`' own telemetry
records the ceiling: the live lens indexed 81 rows against 1,385 live board rows
(2026-08-13). The join cannot project what the lens never produced, so some blanks
are correct and the fix for them is in the lens, not the board. The new log line is
what separates "lens produced nothing" from "lens had rows, join missed".


**All five items from the 2026-08-20 user-directed board audit are FIXED and
LIVE-VERIFIED.** `syndicate/templates/intelligence.html` unless noted.

- **Over/Under picks now show direction.** `propLine()` dropped the
  selection word (`"Under"`/`"Over"`) whenever it matched the card's
  fallback title, which is EXACTLY when both were the same placeholder
  value. **VERIFIED live: 273/273 (100%)** over/under rows show direction
  post-fix.
- **Projected is no longer blank for most moneyline rows.**
  `displayProjection()` had no fallback for h2h (no natural number to
  project pregame). Added a probability-derived fallback. **VERIFIED
  live: 84 of 94** previously-blank h2h `Projected` cells now populated
  (remaining 10 lack `model_probability` upstream — a real backend
  coverage gap, correctly left blank, not fabricated).
- **Live-game Projected/Live/Actual semantics fixed, backend.** Two
  independent gaps: (1) `live_projection_join.py` preserved the pregame
  number under `sim_projected` (`#412`) but then still overwrote
  `projected` itself with the live re-sim value three lines later,
  contradicting its own comment — measured 34/40 live rows with
  `projected == live_projected` pre-fix. (2) `_live_projection_columns`
  (`layer2_board.py`) never mapped `actual_so_far` to `actual` at all —
  zero hits repo-wide before the fix. **VERIFIED live (on the actual
  served surface, `boardContract.cards` — the raw `/api/board/layer2-
  shortlist` row shape exposes this data differently and checking only
  that is NOT sufficient for this class of fix): 36/48** live MLB prop
  cards now show a populated `Actual` and a distinct `Live` projection.
- **Movement/steam display fixed.** `renderMovement()` only read the
  legacy `line_odds_movement` nested shape; the real data moved to
  top-level `movement_state`/`movement_price_delta`/etc months ago
  (`#372`) and the frontend never followed — every tracked/flat row
  rendered blank regardless of real movement data existing. **VERIFIED
  live: 169/169 (100%)** tracked/flat rows now render real movement text
  (e.g. "Odds +226 · 12h ago"). Steam badge logic confirmed correct by
  code read; no real steam event occurred during the verification window
  to observe directly (`steamRows: 0` at check time — a real, expected
  state given the size-and-clock bar, not a rendering gap).
- **Compact game-card "uniformity" was a render-order race, NOT a
  chip-matching bug.** Original hypothesis REFUTED by measurement: chip-
  matching is 100% correct for today's real games (15/15). The actual
  cause: `loadGameChips()` fired AFTER the synchronous initial render, so
  the mini-card strip's first paint always used the chip-less fallback
  style — even for today's real games — then visibly relaid out once
  chips arrived a moment later. Fixed: fetch chips first, gate the
  strip's first paint on a `gameChipsLoadedOnce` flag with a sized
  skeleton placeholder instead of the wrong-shape fallback.
  **NOT live-verified with a timed capture** — confirmed by code read
  (exact line numbers for both bug and fix) plus the existing
  `deriveGameCards` Node harness (unaffected, still 10/10), not by
  screenshot/network-waterfall. Flag this gap to whoever next touches
  the game-card strip.

---

- **The soccer projection read was ONE DATE against a SEVEN-DATE quote window**
  `[moved here 2026-08-18 from a WNBA state snapshot]`. `#379`'s widening shipped
  inert — its only caller never passed `window_dates`. Fixed (`b4d82364`), **NOT
  deployed**. `window="slate"` is required; the resolver defaults to `"day"`.
- **Soccer's `recommendations_<date>.json` is NOT in `HOT_ARTIFACT_PATTERNS`** —
  it lives under `soccer_source/<league>/api/recommendations/` while the allowlist
  covers `source_artifacts/data/processed/`. `/api/ops/artifacts/export` returns
  `count=0` for it. **`/soccer/<league>/api/cards` is the readable substitute.**

## [layer1-layer2-boards] LAYER 1 / LAYER 2 BOARDS — session briefs exist; three facts worth not re-deriving `[code read 08-16 11:2x CDT, NOT a production measurement]`

Full briefs: `.syndicate/brief_2026-08-16_layer1_board.md`,
`.syndicate/brief_2026-08-16_layer2_board.md` (commit `01c53f56`). Lane names
`layer1-board-coverage` / `layer2-board-quality` are RESERVED BY BRIEF and
deliberately NOT opened in `lanes.md` — no session holds them yet.

- **L2 movement/steam is DISABLED IN CODE, not decayed by data.**
  `layer2_board.py:1152` is `return {}` with an unreachable body. `#372` turned
  it off because the in-builder ~20MB odds-history load **stalled the shortlist
  build for 70 minutes with no exception**. Naive re-enable re-stalls the board.
  Only `h2h`/`totals`/`spreads` have history at all (`:1244`); served overlap was
  event+market 11 of 73.
- **The L2 scoring model EXISTS** — `blended_score()`,
  `opportunity_signals.py:497-575`, `min(value, value*reliability)`. Auditing it
  is the work; rebuilding it is not. The `min()` is load-bearing (it corrects a
  sign inversion on negative-value rows, `corr -0.8312` vs `+0.8560` control).
- **Layer 1 already publishes its own projection-coverage instrument** — the
  header's `N markets / M with a projection`, via `_classify_enrichment`
  (`layer1_board.py:328`) / `_row_is_enriched` (`:176`). Do not build a second.

**NOT established, and stated here so it is not cited as if it were:** "Layer 2
has no book allowlist" is a **negative from a grep over one file**. Layer 1's
list IS confirmed (`DEFAULT_BOOKS`, `templates/shared/layer1_board.html:267`,
client-side JS). Trace the served `book` field to its writer before acting.

## [board-intelligence-engine] BOARD / INTELLIGENCE ENGINE — structural facts, archived — **ARCHIVED 2026-08-19 to `state_archive_2026-08-19.md`, verbatim.**

## [locked-cards-retuned-no-autorun] `locked_cards_retuned` HAS NO AUTOMATIC TRIGGER, ANYWHERE `[measured 2026-08-18]`

- The only builder, `build_season_betting_cards_manifest.py`, is invoked two
  ways and **neither runs on Render**: the routine season-wide path only
  exists inside `daily_update.py` (GHA-only, `scripts/daily_update.ps1`,
  Render never calls it); the single-date backfill inside
  `run_refresh_worker.py` is manually env-var-gated
  (`MLB_BETTING_DAY_BACKFILL_DATE`).
- **The GHA cron itself defaults to backup-only**, not the full pipeline —
  `run_full_pipeline` defaults `false`; its own text calls the full-pipeline
  path a "manual fallback for backfills/recovery."
- Consequence, measured: the pregame odds freeze (`#265`/`#440` Phase 7) is
  fixed and improving (1→11→15 games captured, 08-16→08-18), but
  `season_betting_day_2026_08_17.json` still has exactly 2 games / `ml=1`,
  because nothing ever rebuilds it against the improved freeze. Full trace:
  `docs/ai_context/todo.md` under `#265`.
- **NOT FIXED.** Next step if picked up: decide whether to add a routine,
  feature-flagged autorun (generalizing the existing single-date backfill) or
  fix the GHA default — either is a real, scoped change, neither attempted.

## [layer1-board-date-scoping] THE BOARD WAS DROPPING GAMES TWO WAYS — both FIXED AND VERIFIED `[verified 2026-08-30 05:0x-05:5xZ, web+refresh-worker `d7cda903`]`

1. **A 9pm Central game was invisible.** The grid artifact is keyed by **UTC**
   date; the board scopes by **CENTRAL** game date; the read set was window+today.
   `window=day&date=2026-08-29` served **7 games** while
   `book_grid_2026-08-30.json` held Memphis @ UNLV at `02:19Z` = 9:19pm Central
   on the 29th. **7 -> 8 games, `rows_other_dates=0`.** Same game and cause
   `ncaaf/sources.py` already recorded; that fix corrected ONE consumer and the
   board was the second. Rule now lives in `layer1_board.artifact_read_dates`.
2. **Whole slates had no artifact.** `_SLATE_WINDOW_DAYS["ncaaf"]=7` sized BOTH
   display and BUILD; NCAAF week 1 spans ten days, so the last three days were
   unreachable by date. `?date=2026-09-05` **0 -> 67 games / 353 rows**; 09-06
   and 09-07 also reachable for the first time. Split into
   `artifact_window_days` (never below the display window). **The display width
   is UNCHANGED at 7** and `#565`'s per-sport cost pruning survives — three extra
   shard checks for NCAAF, none for any other sport.

## [board-chip-coverage] Layer 2 compact game cards — FULL chip coverage, verified 2026-08-26

Every compact card on the board resolves a live-scoreboard chip, measured from
refresh-worker logs the same evening:

    mlb 400/400   wnba 400/400   nfl 106/106   soccer 400/400

`CHIP_JOIN_COVERAGE` (`pipeline/layer2_shortlist.py`, per sport, every build) is
the instrument. It reports `chips=`, `chip_dates=`, resolution by index
(`by_id` / `by_matchup` / `by_canonical`), plus `needs_fallback`,
`no_chip_available` and `unknown_no_key` with named samples. Before it existed
this defect class was found ONLY by a person looking at the board — twice.

Three causes were closed, all previously invisible:

* **Phase offset.** The chip build resolved ONE matchday per league from
  `default_week(reference_date=today)`; on a Monday that is the matchday just
  played. 65 of 96 chips described finished fixtures. Soccer
  `no_chip_available` 251 -> 0; NFL was the same defect via an exact-date
  filter, 106 -> 0.
* **Two different names for one club.** Normalisation cannot bridge
  "Athletic Bilbao"/"Athletic Club"; both sides now carry `canonical_team`'s
  answer as a join key.
* **Alias gaps**, named by the telemetry itself: soccer `unknown_no_key`
  7 -> 0.

**The horizon is the CALLER's to ask for** (`include_upcoming`, default False).
`provider.games()` serves the home rail (means "today") and the chip strip
(means "the board's forward horizon"); overloading it silently doubled the
soccer home rail 98 -> 210 while fixing the board.

**The alias map has TWO CONSUMERS WITH DIFFERENT REACH.** `teams_match` falls
through to a shared-suffix heuristic; `canonical_team` is map-only and the chip
join calls it directly. A club can join fixtures fine and still return None for
a chip key. The asymmetry is principled: `teams_match` holds BOTH names and
answers "same club?", so a loose rule is safe; the chip index holds ONE name and
must mint a globally unique KEY, where the same rule mints collisions.

**`DIRECT_FEED_BOOKS` needs no widening.** `near_misses={}` across many builds,
one at 27,070 rows — the aggregator uses no spelling the exact match misses.
Reproduced independently by lane `board-staleness-visibility`.

## [chip-artifact-content-age] A chip artifact's TIMESTAMP and its CONTENT age are different numbers — verified 2026-08-27 (lane `mlb-chip-live-state`)

**`/api/board/game-chips` `published_at` bounds when the artifact was WRITTEN,
not how old the live state inside it is.** Measured 00:09:03Z, refresh-worker on
`f8d8b05f`: `published_at` 79 seconds old, content two innings — roughly fifteen
minutes — behind StatsAPI. `BOS` read `TOP 3` against `Bottom 5`; `MIL` read
`BOT 1 0-0` against `Bottom 3 4-0`.

**`#564`'s 120s freshness threshold and the page's stale badge both key on
`published_at`, so BOTH read healthy through this.** Same shape as
`[board-quote-staleness]`. A board build that takes ~750s cold stamps its
artifact at the END.

**THE DISCRIMINATOR BETWEEN A STALE CHIP AND A BLANKED ONE IS THE TOKEN, NOT
THE SCORE.** A blanked game (`#581`) carries `0-0` AND a bare `LIVE`/`FINAL`
with no inning. A stale game carries a real inning that is merely behind. Both
present as "the score is wrong", and reading the score alone gets it backwards
— this was nearly called a `#581` regression off a watcher line that reported
only score mismatches.

**THE CAUSE IS BOARD-BUILD DURATION, NOT THE LENS BOUND.** A first hypothesis
blaming `_MLB_LIVE_LENS_MAX_AGE_SECONDS = 15 * 60` was FALSIFIED the same hour:
one build later, WARM, the same worker with the same bound served an inning gap
of **max 1, mean 0.25 over 8 live games** (`pub=00:15:18Z`). A bound does not
know which build it is in — if it were admitting the staleness, a warm build
would be just as stale. The content is about ONE BUILD old, and this file
already carries the numbers: **cold 747.8s, warm 107.8s**.

**So the exposure is a ~12-minute window after every worker RESTART, not a
standing lag** — and a restart is what every deploy causes. refresh-worker was
deployed three times on the evening of 2026-08-26. Same family as
`[board-quote-staleness]` and `#563`'s deploy-cadence finding.

**Open as `todo.md #585`, not fixed.**

## [board-overview-skipped-for-memory] — VERIFIED 2026-08-27, refresh-worker `277062cd`

**The 8-sport overview was skipped ENTIRELY on every board build in steady
state.** 13:50-14:52Z: 18 consecutive `BOARD_OVERVIEW_READY sports=0`, both
dates. Each preceded by `OVERVIEW_STOPPED_FOR_MEMORY next_sport=mlb
floor=expensive floor_mb=3000 sports_done=0 sports_total=8`.

**`BUILD_SPAN_EXIT stage=build_intelligence_overview elapsed_s=0.0` DOES NOT
MEAN FAST.** It means the guard refused at sport 0 and the loop `break`ed. Read
it together with the `sports=` count or it inverts the diagnosis — a skipped
build looks like a cheap one.

**The expensive floor is unreachable at rest.** headroom = `max - anon`
(4096 - 1297 = 2799, confirmed against the emitted snapshot). Steady-state anon
is 1300-1550MB, so headroom is 2550-2800MB and never reaches the 3000MB floor.
Only 5 of ~40 iterations over 3h08m produced `sports=8`.

**Board cycle period** (`CALLING_COMPUTE` -> `RETURNED_FROM_COMPUTE`):
**~214s** when the overview is skipped, **674-783s** when it runs. Layer 2 is
NOT the cost — `LAYER2_SHORTLIST` publishes every iteration regardless (rows
1323-1330 today) and its tail runs in ~1s. The 460s is
`build_intelligence_overview` (305-366s) + `candidate_collection_with_fallback`
(155-176s).

FIX `6421bf7f` (`break` -> `continue`, plus today+1 throttle default 300 ->
1800s) IS ON MAIN AND **NOT DEPLOYED** — refresh-worker live on `600a753a`.
Production effect is UNOBSERVED. Lane `board-cycle-overview-throughput`.

## [board-overview-fix-verified] — VERIFIED 2026-08-27, refresh-worker

**A memory refusal now skips MLB alone instead of discarding all eight sports.**
`6421bf7f`, live since `b8163ef0` 17:02:59Z, still in on `fb9261b8`. Four paired
readings 18:01-18:58Z: guard fires `OVERVIEW_STOPPED_FOR_MEMORY next_sport=mlb
sports_done=0` at headroom 2775-3020MB and the build returns `sports=7` with MLB
ABSENT and the other seven present. Pre-fix the identical guard line returned
`sports=0` EIGHTEEN times running. Control: the four non-firing iterations read
`sports=8` with `mlb:g=7` present, so the gate in front of MLB is not relaxed.

Today's board went from rebuilt every ~7 min at `sports=0` — never actually
built — to every ~25 min at `sports=7`/`sports=8`. Slower and real.

**THE THROTTLE HALF DID NOT "BUY NOTHING" — IT COST BOARD FRESHNESS, AND I
MISSED IT FOR NINE HOURS `[CORRECTED 2026-08-28 21:4xZ]`.** Raising the code
default 300 -> 1800s starved the THIRD date in a 3-day window. Measured from
the user's own board screenshot and confirmed per date:
```
date         last build     age     candidates
2026-08-28   21:20:24        19m      278
2026-08-29   21:37:15         3m       68
2026-08-30   17:15:20       264m       42   <- sets computed_at
```
`17:15:20Z` is 12:15 PM Central — EXACTLY the "as of" the board displayed at
4:33 PM. `combined_board_window` reports `computed_at` as the OLDEST
contributor's stamp by design, so one starved date drags the whole board's
shown vintage down by 4h24m while today and tomorrow were 19m and 3m fresh.
**MITIGATED:** `SYNDICATE_INTELLIGENCE_BOARD_WINDOW_SLOW_REFRESH_SECONDS=600`
set on refresh-worker (env overrides the 1800 code default; inert until that
service next deploys). `SYNDICATE_INTELLIGENCE_BOARD_WINDOW_DAYS=2` is the
alternative — it drops 08-30 so the board stops claiming a date it is not
maintaining — but that changes coverage and is a user decision.
**THE ERROR:** I optimised a metric I chose (today's SHARE of cycles) and
never checked the metric the user SEES (`computed_at`). Recording it as
"bought nothing" was incomplete — it bought nothing AND cost this. Same
family as the share-of-the-whole rule: measuring the wrong quantity
confidently. ORIGINAL ENTRY FOLLOWS.
~~THE THROTTLE HALF BOUGHT NOTHING and is recorded as such.~~ Default 300 ->
1800s does throttle (future-date builds ~7min -> ~30min) but today's SHARE of
iterations did not move (5/4/1 over 127 min vs a 9/9 baseline — 50% both ways).
The `>=4:1` bar I wrote was unreachable: the board window is THREE dates, and
the overview fix slowed each build 150s -> 534s, so there are fewer builds to
redistribute. The two changes interact; I did not predict it.

**REMAINING LEVER, no lane:** the 534s overview itself — MLB's
`build_cards_page_context` running hydrated on the worker — not the throttle.
### CFBD IS OUT OF QUOTA UNTIL 1 SEPTEMBER — A MONTH, NOT A WINDOW

Measured 2026-08-27 from the 429 itself: `X-CallLimit-Remaining: 0`,
`{"message":"Monthly call quota exceeded."}`. **Monthly cap, so it resets
2026-09-01 — AFTER the 08-29 openers.** Retrying cannot shorten it; polling
sustains it. NCAAF projections therefore CANNOT be regenerated before the
season starts, and the board will serve the 08-19 artifact through opening
weekend.

Consequence for provenance: `profile_source`/`profile_version` are stamped only
by a SUCCESSFUL run, so the live CSV reads `unknown` until September. Until
then the refresh-worker log line below is the only evidence that exists.

Not blocked by this: OddsAPI props/lines (different provider, own budget), the
team and pace snapshots (already built), and the board itself.

### THE PROMOTED NCAAF CALIBRATION ARTIFACT LOADS IN PRODUCTION — CONFIRMED

Read from the Render logs API on refresh-worker, 2026-08-27 21:21:37Z:

    [calibration] ncaaf profile source=artifact version=ncaaf-goal-line-refit-1
                  goal_line_touchdown=True drive_yardage_multiplier=0.95

`source=artifact`, not `default`, with three discriminating fields agreeing —
`goal_line_touchdown` defaults False, `drive_yardage_multiplier` defaults 1.15.
This discharges the confirmation owed since the promotion.

**Those four runs then CRASHED on the 429 and wrote nothing.** They failed
safely: board intact at 51 cards, 0 missing projection values. A ratings-less
artifact written over the good one would have looked exactly like success.

### `header_stats` NOW RENDERS ON THE SHARED RANK BOARD — 21 of 21 ROUTES

`header_stats` is a REQUIRED argument of `build_rank_page_context` (31 call
sites, 23 files) that `shared/rank_board.html` read NOWHERE; it rendered the
optional `summary_panel.summary_stats` instead. Production sweep 2026-08-27
found **14 routes with a full board of cards rendering no slate stats**, and 1
rendering them. It survived because 11 sport-specific templates DO loop over
`header_stats` — load-bearing there, inert on the shared board.

Fixed at the template (`12928720`, live 22:03:52Z) as an `elif`, so a builder
supplying its own `summary_panel` is untouched. After: **21 of 21 rank_board
routes render slate stats.** Verify by counting `feature-summary-pill`, NOT by
grepping panel prose — "on the board" is body text that only appears on a
populated slate and reads as a false negative on most routes out of season.

## [board-compute-attribution] — VERIFIED 2026-08-28, refresh-worker `4805abe5`

**THE BOARD BUILD'S COST IS NAMED. 84% attributed, and every venue/IO
hypothesis is DEAD.** One complete build, `BOARD_BUILD_TIMING wall_s=678.8
cpu_s=664.1 off_cpu_pct=2.2`:

```
build_intelligence_overview          331.09s   49%
candidate_collection_with_fallback   168.40s   25%
layer2_shortlist_build                51.00s    8%
kalshi_odds_refresh                   12.84s
portfolio_commit                       5.38s
pull_hot_artifacts                     1.15s
kalshi_board_join                      0.91s
manifest_odds_history_join             0.31s
candidate_building                     0.01s
                                    --------
named                                571.1s   84%
unattributed                         107.7s   16%
```

**`off_cpu_pct=2.2` — THIS BUILD DID ESSENTIALLY NO WAITING. There is no I/O
win available.** Confirmed twice, independently: the ratio itself, and
`pull_hot_artifacts=1.15s` measured directly.

### THREE HYPOTHESES RETIRED, ALL MINE, ALL WRONG

1. **"The artifact_publisher HTTP pulls are a large part of it."** They are
   **1.15s, ~0.2%**. I had measured ~37s of pull lines by GAP-BETWEEN-LOG-LINES
   earlier and treated that as cost; the span says otherwise.
2. **"The Polymarket join is a credible largest-single-item."** It is
   **0.25s** (`POLYMARKET_BOARD_JOIN elapsed_s=0.25 markets=15303 indexed=7717
   board_rows=1008`). Wrong by three orders of magnitude. Instrumenting it was
   still correct — it was the largest UNMEASURED block and is now RULED OUT
   rather than suspected.
3. **"Compute doubled; suspect venue-loop contention."** The series is 480.6,
   650.9, 778.8, 593.1, 735.5, 865.2, 1058.9, 855.6, 678.8 — and the 865.2s
   build at 00:24Z PREDATES the venue loop. I read two points as a trend.

### WHAT IS ACTUALLY LEFT, and it is where the first measurement pointed

`build_intelligence_overview` (331s) + `candidate_collection_with_fallback`
(168s) = **499s of 679s (73%)**. The overview is MLB's
`build_cards_page_context` running HYDRATED on the worker — named as "the real
work... untouched" by a code comment since 2026-08-07 and still true. **The
next lever is an OPTIMISATION task, not an instrumentation one.** The
measurement work is finished; do not spend more on spans.

The residual 107.7s (16%) is spread across gaps individually too small to
chase.

## [board-window-staleness] — **CAUSE FOUND AND VERIFIED 2026-08-29. It is neither the queue NOR build cost — see `[week-scoped-board-window]`.**

**SYMPTOM, from the user's own board:** `combined_board_window · as of Aug 28,
12:15 PM · 1746 candidates` displayed at 4:33 PM. `computed_at` is the OLDEST
contributing date's stamp BY DESIGN (`read_combined_intelligence_response`), and
that anchoring is load-bearing: `_apply_freshness_recompute` would otherwise
recompute the age to ~0 and hand back `is_fresh: True`. **The number on the board
is TRUE. There is no display bug and no display fix.**

### SUPERSEDED CAUSE — kept visible because it is actionable and WRONG

Recorded 2026-08-28 in `b1f791fd`: *"`_ensure_default_board_window_watched`
re-queues TODAY every loop iteration, UNTHROTTLED, while future dates are
throttled ... ELIGIBILITY WAS NEVER THE CONSTRAINT; SLOT ALLOCATION IS,"* with
"round-robin the pending queue" named as the real fix.

**REFUTED 2026-08-29.** The starvation mechanism is really in the code; it is not
what was happening. `BUILD_SPAN_ENTER stage=pull_hot_artifacts`, refresh-worker,
00:28-03:55Z, `days=2` + `SLOW_REFRESH=600`:

```
00:28  08-28    01:35  08-28    02:31  08-28    03:54  08-28
00:49  08-28    02:07  08-29    03:16  08-29
01:20  08-29
```

The dates ALTERNATE. Allocation is roughly fair. **Do not build the round-robin.**

### ACTUAL CAUSE — build duration

| stage | range (s) |
|---|---|
| `build_intelligence_overview` | 257 – **1158** |
| `candidate_collection_with_fallback` | 119 – **656** |
| layer2 + kalshi + portfolio | ~100 – 400 |

**900–2000s per build.** Two dates alternating fairly => each date rebuilt every
30–66 min => the older one sets `computed_at`. That is the whole symptom.

**WHY THE THREE CONFIG ATTEMPTS COULD NOT HAVE WORKED.** All three moved slot
ALLOCATION, which was never binding. A knob that redistributes a fixed amount of
work between two dates cannot reduce the age of the older one -- it can only
choose WHICH date is stale. That is why `SLOW_REFRESH=600` made `08-29` worse
(3m -> 84m) and why `days=2` was absorbed by today (36 min post-boot, two builds,
both `08-28`). Three spellings of the same non-fix.

1. `SLOW_REFRESH_SECONDS` code default 300 -> 1800 (mine). Starved the third date
   to 264m. Recorded as "bought nothing" having measured only today's SHARE of
   cycles, never `computed_at`.
2. `SLOW_REFRESH_SECONDS=600` env override. **Made it WORSE.**
3. `BOARD_WINDOW_DAYS=2`. Dropped `08-30` correctly; today absorbed the slot.

### CHECKED AND EXONERATED

The hydrated-overview rate limit (`SYNDICATE_HYDRATED_OVERVIEW_MIN_REBUILD_SEC=900`)
reads `cache_entries=0` on every pass and fired ZERO times in 4 hours -- but
retention is `max(10, 900)` = 900s and the per-date gap is 1220–1307s, so the
cache is CORRECTLY empty. `#336`'s own comment already predicted this. Raising the
interval would make it bind only by serving an overview older than the gap:
trading a measured number for a hidden one. **NOT DONE, deliberately.**

### CURRENT ENV ON refresh-worker (all set by me, all live)

`SYNDICATE_INTELLIGENCE_BOARD_WINDOW_DAYS=2`,
`SYNDICATE_INTELLIGENCE_BOARD_WINDOW_SLOW_REFRESH_SECONDS=600`. Code default for
the latter is 1800 and is ALSO mine — env currently wins. `DAYS=1` remains
available and is NOT set: it makes `computed_at` current by NARROWING WHAT THE
BOARD CLAIMS, which is not what was asked for.

### THE FIX — and BOTH earlier answers in this section are superseded

**MEASURED on the served payload, 2026-08-29 18:13:02Z:**

```
computed_at 2026-08-28T23:03:31Z   age 68,971 s (19.2 h)   newest_age 300 s
by_date  2026-08-29  153 candidates, 12 sports
         2026-08-30   42 candidates, ["serie a"]   <- 19.2h old, REAL ROWS
         2026-08-31    0 candidates                <- ignored (#603)
```

`2026-08-30` has ONLY soccer fixtures (`SCHEDULE_RECONCILE_CHECK
scheduled_games=0`). `_supported_intelligence_dates()` covers FIVE DAILY SPORTS
ONLY, so that date is never eligible to BUILD, while the read side correctly
shows its 42 real rows — whose 19.2h stamp then sets `computed_at`.

**BUILD SPEED CANNOT MOVE THIS**, which is why nothing did: three config changes
AND two verified performance fixes (`lstat` 7,955 -> absent; soccer bracket
363s -> 80.5s, full board build 1005s vs a 900-2000s baseline) all left it at 19.2h.

`#603` (landed `a1d7ad4e`, verified firing) removed EMPTY dates from the age —
08-31 no longer counts. 08-30 is not empty, so it still does, correctly.

**The remaining fix is scoped, not built: `[week-scoped-board-window]` below.**
### KNOWN, NOT ACTIONED — USER DECISION

`#385` records that refilling the legacy pool costs **~580s per build and
contributes 0 rows** when Layer 2 owns the board, gated on
`board_l2a_fallback_enabled()` (`SYNDICATE_BOARD_L2A_ENABLED`, default OFF).
Turning it on is a PRODUCT decision: the board template reads 70 fields per row
and ~40 have no source on an L2-A row, so cards render leaner. Surfaced, not flipped.

### SEPARATELY MEASURED — worth someone's lane

Soccer generates 151 candidates per build and loses ALL of them at
`CANDIDATE_SLATE_FILTER` (`SPORT_LOST_ALL_CANDIDATES sport=soccer no_match=28
chips=351 -- alias gap, NOT a date exclusion`), while Polymarket reports
`no_candidates|soccer|alternate_totals_corners: 222` and `no_match|soccer|h2h: 93`.
Soccer is currently the most expensive sport in the build AND contributes zero
board rows.

## [week-scoped-board-window] SCOPED, NOT BUILT `[2026-08-29]`

**THE REMAINING CAUSE OF BOARD STALENESS, after everything else today was fixed
and did not fix it.**

### Evidence, served payload 18:13:02Z

```
state_meta: computed_at 2026-08-28T23:03:31Z   age 68,971 s (19.2 h)
            newest_age 300 s   artifacts_dated 4   status stale
            source combined_board_window+layer2_fallback
by_date:    2026-08-29  153 candidates, 12 sports
            2026-08-30   42 candidates, ["serie a"]   <- 19.2h old, REAL ROWS
            2026-08-31    0 candidates                <- correctly ignored (#603)
```

### The chain

1. `2026-08-30` has ONLY soccer fixtures. `SCHEDULE_RECONCILE_CHECK date=2026-08-30
   scheduled_games=0` for MLB; `BETTING_PAYLOAD_READ exists=False`.
2. `_supported_intelligence_dates()` unions FIVE DAILY LOADERS ONLY --
   `mlb_available_daily_summary_dates`, `nba_/wnba_/ncaab_/nhl_available_dates`.
   **No soccer, no NFL, no NCAAF.**
3. `_default_board_window_dates()` = today UNION (window INTERSECT supported), so a
   soccer-only date is NEVER ELIGIBLE TO BUILD.
4. The read side deliberately does not filter, so it still shows tomorrow's 42
   Serie A rows -- which are real, so `#603`'s row-gate correctly passes them.
5. Their 19.2h stamp sets `computed_at`. **No build-speed work can ever move this.**

The code already names the gap: *"soccer's available-date probe is per-league --
conflating either into this rolling day-window would be the wrong shape for them.
Tracked as a separate follow-up (`_default_week_scoped_dates`, not yet implemented)."*

### The primitives ALREADY EXIST -- this is not new plumbing

- `soccer.sources.available_dates(league)` -> reads `display_prediction_dates.json`
  under `_api_root(league)`. One JSON per league, 10 leagues in `LEAGUE_DISPLAY_NAMES`.
- `soccer.sources.active_leagues_for_date(date)` -> `league_active_for_date` per league.
- Path resolution for those reads is no longer a cost: the `source_roots` cache
  landed today (`lstat` 7,955 -> absent).

### Proposed change (v1, SOCCER ONLY)

```
_week_scoped_supported_dates()  -> union of available_dates(league) over leagues
_default_board_window_dates()   -> today UNION (window INTERSECT (daily UNION week_scoped))
```

**NFL/NCAAF DELIBERATELY OUT OF v1.** They are week-scoped, not date-scoped; mapping
week -> dates is a different transform and the existing comment is right that
bolting it on here is the wrong shape. Soccer is date-indexed already, so it fits
the rolling window as-is.

### THE PART THAT MUST NOT BE SKIPPED: this makes today WORSE unless throttled

Each eligible date costs a FULL BOARD BUILD. Measured 2026-08-29 17:32-17:49,
post-fix: **1005 s wall** (24.72 pull + 177.34 overview + 282.67 collect + 137.04
layer2 + 106.34 kalshi + 122.62 portfolio). Today is currently the ONLY eligible
date and rebuilds every ~21 min. Add tomorrow and they alternate: **~42 min each.**

So the naive widening trades a 19.2h displayed age for a 42-min one AND HALVES
TODAY'S REFRESH RATE. `SYNDICATE_INTELLIGENCE_BOARD_WINDOW_SLOW_REFRESH_SECONDS`
exists precisely for this and already applies to non-today dates -- **verify it
BINDS before widening**, because this lane has already shipped three tuning changes
to that knob that did nothing (see `[board-window-staleness]`).

> **PARTLY SUPERSEDED 2026-09-03 — "IT BINDS" IS WRONG (see the correction
> below the block). The COST-MODEL half stands and was measured again.**
> `[lane board-window-throttle-binds]` Measured per-date `BUILD_SPAN_ENTER`
> intervals, 744-minute window on refresh-worker:
>
>     2026-09-02  today, unthrottled   39 builds   median gap 15.8 min
>     2026-09-03  tomorrow, throttled   7 builds   median gap 38.8 min
>
> Tomorrow sits ABOVE the 30-min floor; today runs free. **"They alternate at
> ~42 min each" did NOT happen — today is 15.8 min, not 42.** The throttle SHEDS
> the extra date's turns instead of alternating, so **widening does not halve
> today's refresh rate.** The paragraph above is kept because its CAUTION was
> right and produced this measurement; only its arithmetic is superseded.
>
> Method note: a first pass read a 12-line log tail and concluded tomorrow
> out-built today 3:1. Over the full span it is 39 to 7 the other way — a tail
> read as a population, which is the standing "a rate, not a count" rule.

> **CORRECTION 2026-09-03 — THE THROTTLE DOES NOT BIND, AND THE FLOOR IT WAS
> JUDGED AGAINST WAS NEVER IN EFFECT.** `[lane board-throttle-600s-remeasure]`
>
> The block above reasons against a 30-minute floor. The code is
> `max(30, _env_int(SYNDICATE_INTELLIGENCE_BOARD_WINDOW_SLOW_REFRESH_SECONDS, 1800))`
> and the LIVE value on refresh-worker is **`600`**, read from the Render API.
>
> Re-measured from `BUILD_SPAN_ENTER stage=pull_hot_artifacts`, refresh-worker,
> covered window **2026-09-02T12:42:56Z → 2026-09-03T02:16:34Z (13.6 h)**,
> 341 matching lines over 5 pages:
>
>     date        n   min      p25      median    max        (gap seconds)
>     2026-09-02  46  128.1    806.9     940.8    3,484.7    <- today, no floor
>     2026-09-03   5  1,331.2  2,329.3   3,854.1  28,518.5   <- non-today
>
> **THE FLOOR NEVER CLIPS.** Of the non-today gaps: **0 below 600 s, and 0 in
> [600, 750) s** — no pile at the floor. The smallest gap tomorrow ever achieved
> is **1,331.2 s = 2.2x the floor**. A constraint that is never the binding one
> is not "binding"; a gap sitting ABOVE a floor is not evidence the floor caused
> it.
>
> **AND THE 1800 s FLOOR WAS DEMONSTRABLY NOT IN EFFECT**, which removes the
> objection that the env value is only confirmed for the process that booted at
> 01:10Z: a **1,331.2 s (22.2 min) gap CANNOT EXIST under an 1800 s floor**. So
> the effective floor across the whole measured window was <= 1,331 s,
> independently corroborating the API's `600`.
>
> **WHAT ACTUALLY SPACES THE BUILDS IS SERIALISATION.** Today's median gap
> 940.8 s against the ~1005 s measured full-board-build cost is a ratio of
> **0.94** — the worker builds today essentially BACK-TO-BACK, and non-today
> dates get whatever turns are left (median 64 min, worst 7.9 h).
>
> **WHAT STILL STANDS:** the cost model *"add tomorrow and they alternate at
> ~42 min each"* is still wrong. Today measured **15.7 min median here**, against
> 15.8 min in the superseded block — two independent windows agreeing. Widening
> did not halve today's refresh rate.
>
> Sample caveat, stated rather than buried: non-today n=5 gaps. The post-deploy
> window where `600` is directly confirmed holds **n=0** non-today builds (1.1 h),
> so this rests on the full window plus the <=1,331 s inference above, not on the
> post-deploy segment.

### Risks

1. **Today regresses** if the throttle does not bind. Measured earlier today with 2
   eligible dates: per-date period 30-66 min.

   > **STILL LIVE 2026-09-03 — the throttle does NOT bind, so this risk is NOT
   > discharged.** `[lane board-throttle-600s-remeasure]` Today is currently
   > protected only because the window holds TWO dates on a saturated worker, not
   > because anything sheds load. The soccer index offers **8 forward days** (see
   > risk 2), and with the floor at `600` they would compete freely.
   > **The mechanism exists and is simply set too low to fire** — raise
   > `SYNDICATE_INTELLIGENCE_BOARD_WINDOW_SLOW_REFRESH_SECONDS` above the
   > serialisation period as part of any widening, and re-measure that it clips.

   > **RAISED AND INJECTED 2026-09-03.** `[lane board-window-floor-raise]` Env
   > `600` -> `1800` (single-key endpoint; absent from `render.yaml`), injected by
   > a SAME-SHA redeploy of `f84eb21b` (live 03:08:48Z) so no code shipped with
   > it. Then `33b181ee` (live 04:20:45Z) made the floor OBSERVABLE for the first
   > time: `BOARD_WINDOW_QUEUE_GATED` / `BOARD_WINDOW_QUEUED`, both branches, so
   > the gate has a denominator.
   >
   > **The mechanism is demonstrated; the RATE is not measured yet.** A non-today
   > enqueue was GATED at `elapsed_s=725` against `floor_s=1800` — under the old
   > `600` floor that same enqueue would have been ADMITTED. n=2, twelve minutes
   > after a cold start: that is a mechanism, NOT a clip rate.
   >
   > Owed: `py -3 scripts/measure_board_window_clip_rate.py` (committed, carries
   > its own baseline). **A clip rate of 0 is a LEGITIMATE RESULT** meaning the
   > queue coalesces and the floor is the wrong lever — not a failed measurement.
2. **`display_prediction_dates.json` staleness** -- if that artifact lags, the same
   class of bug recurs one level down. WHO WRITES IT AND HOW OFTEN IS UNVERIFIED.

   > **DISCHARGED 2026-09-02 — THE INDEX IS NOT STALE. IT LEADS.**
   > `[lane soccer-date-index-staleness]` Read live off production disk,
   > `/api/ops/artifacts/export?pattern=soccer_source/*/api/display_prediction_dates.json`,
   > `count=10 truncated=False` — all ten leagues, nothing elided.
   >
   > **WHO WRITES IT:** `build_soccer_artifacts.py:696` calls `_update_date_index`
   > at the END of a league+date build, right after the recommendations file.
   > ACCUMULATE-ONLY — read `dates`, add `iso_date`, write sorted + `latest`.
   > Nothing ever removes a date.
   >
   > **HOW OFTEN:** the soccer weekly autorun, live on refresh-worker —
   > `SYNDICATE_ENABLE_SOCCER_WEEKLY_REFRESH_AUTORUN=true`,
   > `SYNDICATE_SOCCER_WEEKLY_REFRESH_INTERVAL_SECONDS=14400` (4 h),
   > `SYNDICATE_SOCCER_SIM_HORIZON_DAYS=7`. So every 4 hours across a SEVEN-DAY
   > forward horizon, which is exactly why the index leads rather than lags.
   >
   > **MY HYPOTHESIS WAS REFUTED.** I predicted the index records dates that were
   > BUILT and so could never hold tomorrow, making the widening INERT. Wrong:
   > 9 of 10 leagues carry a future date, out to **+7 days**, and NO league's max
   > is before today. The builder runs a horizon, not just today.
   >
   > Per-day league counts, measured (central dates):
   >
   >     today +0  2026-09-02   2 leagues    +3  2026-09-05   7 leagues
   >           +1  2026-09-03   3 leagues    +4  2026-09-06   7 leagues
   >           +2  2026-09-04   7 leagues    +5..+7           3,1,3 leagues
   >
   > **The widening has real input:** a 2-day window yields both `2026-09-02` and
   > `2026-09-03`; 8 forward days carry at least one league. Note TODAY IS THE
   > THIN DAY (2 leagues) while +2..+4 carry 7 each — an argument FOR widening,
   > since most soccer activity sits two to four days out.
   >
   > Residual, NOT a blocker: the index is accumulate-only and never pruned
   > (MLS reaches back to 2026-07-22), so anything intersecting it must be
   > window-bounded. `#631`'s formula already intersects the board window.

   > **CAUTION RAISED ON RISK 1 BY THE SAME READ.** The live
   > `SYNDICATE_INTELLIGENCE_BOARD_WINDOW_SLOW_REFRESH_SECONDS` on refresh-worker
   > is **`600`**, not the code default `1800` the throttle analysis above reasons
   > against (`max(30, _env_int(KEY, 1800))`). Read from the Render API
   > 2026-09-03T02:2xZ; the running process booted 01:10:00Z (`f84eb21b`), so
   > `600` is what it holds. **"Tomorrow's 38.8-min median sits above the 30-min
   > floor" is therefore not evidence the throttle binds** — against a 10-minute
   > floor a 38.8-minute gap means the floor is NOT the constraint, and something
   > else is spacing those builds.
   >
   > What SURVIVES that correction, because it was measured directly rather than
   > inferred from the floor: **with two eligible dates, today still built at a
   > 15.8-minute median** — so widening did not halve today's refresh rate. The
   > practical conclusion stands; the MECHANISM story ("the throttle binds") does
   > not, and re-measuring it needs its own pass.
3. Memory: builds are serial, and the OOM history is on `build_intelligence_overview`
   per build, not across concurrent dates -- likely fine, not verified.

### Verification predicate, to be written down BEFORE deploying

- `BUILD_SPAN_ENTER stage=pull_hot_artifacts date=<tomorrow>` appears at all.
- Served `state_meta.computed_at` age drops below the slow-refresh interval.
- Today's own per-date period does not exceed ~30 min.
- REFUTED IF today's period doubles without tomorrow's age improving.

### THE ALTERNATIVE, and why it is worse

Gate `computed_at` on "is this date in the BUILD window" rather than "does it have
rows". Cheap, no extra builds -- but the board would then read FRESH while showing
19.2h-old Serie A rows. That is a display that lies, and `#334`/`#563` exist because
this repo has already been burned by asserted freshness. **Not recommended.**

### Effort

~30 lines plus tests for the eligibility change. The real work is the cost
verification, not the code.

---

## [board-model-edge-coverage] 2026-08-30 — 82% of the board is UNSIZABLE, and every `_alt` market is 0%

**MEASURED on the full board**, `/api/board/layer2-shortlist?date=2026-08-30&limit=2000`,
1198 rows -- the same `rows_in` `PLAN_WRITTEN` reports. My count of rows carrying
`model_edge_pct` is 218/1198 = 18.2%, which reproduces production's own
`no_model_edge_pct=980` exactly, so this is the same population the sizer sees.

`no_model_edge_pct` is not a threshold. Without a model view `model_probability`
== `fair`, so Kelly is exactly ZERO and the row cannot be SIZED at all
(`portfolio_commit.py:259`). Those rows can rank; they can never be bet.

    market              rows   w/ view   coverage
    totals               344        34      9.9%
    h2h                  142        65     45.8%
    spreads_alt          131         0      0.0%
    totals_alt           128         0      0.0%
    spreads               63         2      3.2%
    batter_hits           45        23     51.1%
    batter_hits_runs_rbis 40        21     52.5%
    batter_total_bases    32        19     59.4%
    strikeouts            10         0      0.0%
    TOTAL               1198       218     18.2%

**EVERY `_alt` MARKET IS EXACTLY ZERO** -- `spreads_alt` 0/131, `totals_alt`
0/128, and the other zero rows are small prop families. That is 259 rows, 22% of
the board, that can never produce a bet no matter what the venues quote.

**The whole plan funnel, arithmetic closing exactly:**
1198 rows -> 980 no model view -> 218 -> 213 below min EV -> 5 -> 2 below min
stake -> 3 sized -> 2 zero Kelly -> **1 position**.

**This is why "the ranker only picks one spread".** 63 spread rows existed, TWO
were sizable, and one survived EV and Kelly. The ranker did about as well as its
inputs allowed. The constraint is MODEL COVERAGE, not selection, and not any
part of the venue join / tick logic / order path -- none of which refuse spreads.

**AND NCAAF IS SEPARATELY BROKEN, not only gated.** Of its 373 rows ~193 carry
the gate's named refusals; **~180 carry "no projection object at all"** — no
reason, no projection dict. That is a generator that never ran, and it has a
cause: see `[cfbd-monthly-quota-exhausted]`. Deliberate suppression and a failed
generator were being counted as one thing.

**WHY totals is 9.9%: NCAAF dominates an opener-weekend board and its model is
DELIBERATELY WITHHELD.** 281 of the 344 totals rows are NCAAF, and NCAAF carries
a named, measured refusal:

    totals   "totals are 1.67x over-dispersed against the market and were
              never scored against the close"                        139 rows
    spreads  "margin model loses to the closing line by 3.563 points
    /h2h      of MAE over 2233 [games]"                               54 rows

That is a model that was BACKTESTED, FOUND WORSE THAN THE CLOSE, and suppressed.
Correct behaviour. NCAAF is 373 rows, ZERO covered, across every market.

**EXCLUDING NCAAF, totals coverage is 34/63 = 54%.** The 9.9% is composition.

Coverage by sport, whole board:
    soccer   103 rows   87 covered   84.5%
    mlb      332 rows  117 covered   35.2%
    wnba     390 rows   14 covered    3.6%
    ncaaf    373 rows    0 covered    0.0%

MLB + soccer = 435 rows, 47% covered -- the sports with a working model.
NCAAF + WNBA = 763 rows (64% OF THE BOARD), 1.8% covered.

WNBA's near-zero is a DIFFERENT cause: its board is mostly alternate lines
(`spreads_alt` 126, `totals_alt` 115) and the reason given is
`analytic_probability_is_only_valid_at_its_own_line` -- the analytic model
cannot price away from the line it was computed at. That is also why every
`_alt` market is 0% board-wide.

So "the board outgrew the model" is too vague. Precisely: the board added two
sports, one whose model is gated because it MEASURED WORSE THAN THE CLOSE, and
one whose board is mostly alt lines its model structurally cannot price.

The code's own baseline comment records 65 of 108 rows carrying `model_edge_pct`
on 2026-08-16 (60%). Coverage is now 18%, but the board grew ~11x (108 -> 1198)
while covered rows grew ~3x (65 -> 218). That is the board outgrowing the model,
which is a different problem from the model breaking -- do NOT read it as a
regression without checking per-market coverage against that date.

Venue-scoped coverage is much better than board-wide: the Polymarket line
reports `sim_view_on=14/29` (48%). The unprojected mass is mostly rows the
venues do not quote anyway.
