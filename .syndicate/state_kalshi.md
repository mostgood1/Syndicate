# state — kalshi

Split out of `state.md` by `scripts/split_state.py`. Bodies are verbatim.
The INDEX of every subject, across every part, is in `state.md`; the
one-subject-one-section rule is global and spans these files.
Same rules as state.md: when a fact changes, EDIT THE LINE.

## [kalshi-in-play-and-real-fees] KALSHI TRADES IN-PLAY AND PUBLISHES ITS OWN FEE PARAMETERS; THE ARB THRESHOLD WAS ABOVE BREAK-EVEN EVERYWHERE ON MLB `[verified 2026-08-29, lane live-venue-order-placement]`

**Kalshi keeps game markets tradeable through the game.** `status=active`,
`close_time` ~3 days out, and `occurrence_datetime` is expected game **END**,
not start — so the in-play test is `occurrence_datetime` future AND
`occurrence_datetime - 3h` past. 14 of 76 open `KXMLBGAME` in play at 22:02Z,
every observed spread **1 cent**, `KXMLBGAME-26AUG291507SEATOR-TOR` at vol24
**904,281** / OI **558,549**. Prices moved between reads 4 minutes apart, which
is what distinguishes a repricing in-play book from a stale pregame one.

**`GET /trade-api/v2/series/<ticker>` carries `fee_type` and `fee_multiplier`.**
Four distinct combinations across the thirteen series this platform trades.
**Every MLB game/total/spread/K series is `fee_multiplier: 0.5` — half rate.**
NFL/WNBA/NBA/NCAAF game series are 1.0. A hardcoded rate is wrong on MLB by 2x.

**Base rate 0.07, MEASURED off 27 of our own fills** (21 at multiplier 0.5 imply
0.0350; 4 at 1.0 imply 0.0700 — a discriminating 2:1). Not circular:
`fees_dollars` comes from Kalshi's own `taker_fees_dollars` via
`kalshi_orders._FEE_FIELDS`, and nothing in this repo computes a fee from a rate.

**Rounding is ceil to a HUNDREDTH of a cent (4dp), not to a cent** — ceil-4dp
matches **18/18** real fills, round-4dp **9/18**. Third-party sources all say
"next cent"; that overstates an order by up to 0.9c.

**CONSEQUENCE: `kalshi_polymarket_arb.DEFAULT_FEE_BUFFER = 0.04` demanded a flat
4.00c raw gap at every price, while MLB break-even runs 3.38c at even money down
to 0.39c at 0.97 — above break-even at EVERY price on the board.** The detector
was not conservative on MLB; it could not report a profitable pair at all.
Replaced by `venue_fees.py` + `kalshi_polymarket_arb.net_edge_per_contract`.

**In-play is where arb is viable, and the mechanism is FEE GEOMETRY, not model
edge.** 5 of 7 in-play games had a side >= 0.90, where break-even is 0.52-1.11c
against a 1c venue spread; pregame moneylines sit at 0.40-0.60 where break-even
is ~3.3c. This says nothing about model edge — `live-game-line-projection`
(CLOSED 2026-08-29) measured the live model TRAILING the market on 8 of 9 dates.

**Polymarket's fee is NOW READ FROM THE VENUE** `[2026-08-29 22:50Z, VERIFIED
on production]`. It was never absent: `venue_order_view` hardcoded
`fees_dollars: None` while `commissionNotionalTotalCollected` sat in every
`ORDERS_READ`. Mapped in `98e103e1`, live on live-odds-worker as `219d79ca`.
Five reconciled fills, `commission / fill_cost`:

    tsc-mls-nyr-phi-3pt5  0.06/1.8377  3.26%   tsc-mlb-mia-wsh-7pt5  0.05/1.5980  3.12%
    tsc-mls-min-orl-3pt5  0.07/2.1199  3.30%   tsc-mlb-sd-tb-7pt5    0.28/8.7890  3.19%
    tsc-sea-juv-par-2pt5  0.04/1.0500  3.81%

`C60JWBG0WKDK`'s $0.06 independently reproduces the figure derived that
afternoon from a balance delta ($1.8977 debit vs $1.8377 fill) -- two routes,
one number.

**THE RATE IS NOW FITTED AND IT IS NOT A PERCENTAGE.** `[2026-08-30]` The fee is
FLAT: **$0.015 per contract, independent of price** (= 150 bps of the $1
notional). My earlier "3.12-3.81% of fill cost" was the ARTIFACT of dividing a
flat per-contract charge by a VARYING cost — the spread was the symptom, not
the finding. `commissionsBasisPoints` being uniformly `'0'` is consistent with
a flat fee rather than evidence against one; see the resolved note above.
Sample bounds stand: 5 of 73 filled Polymarket rows carry a fee (reconciliation
re-reads open candidates; the 68 settled earlier are NOT backfilled), all
`totals`, $1-$9, one evening.

**A PATH RESOLVER WRITES AND CAN SUPPRESS THE ARTIFACT REPAIR — REAL, BUT NOT
LIVE ON THE DAILY PATH** `[2026-08-29 found, 2026-08-30 NARROWED, both MEASURED]`.
`artifact_publisher._required_daily_artifact_paths` — which only asks WHICH
artifacts are required — reaches `mlb.sources.daily_artifact_path` →
`_resolve_data_path_with_reconcile` → `shutil.copy2` (`mlb/sources.py:116`).
The copy then looks present, so `_missing_required_artifact_relative_paths`
does not request it. **The trigger is `if target_stat is None: should_copy =
True` — a MISSING target copies unconditionally**, which is exactly the case
the repair exists for. (An earlier note here called this an "mtime/size guard";
that was wrong and is corrected.)

**IT DOES NOT FIRE ON THE DAILY PATH.** Render's checkout is a full clone (no
`.slugignore`, no `buildFilter`) but carries GIT-TRACKED files only: 283
`daily_summary_*`, window **2026-05-28 → 2026-07-12**. The daily pull asks for
TODAY, which has no tracked candidate. Measured 2026-08-30:
`daily_summary_2026_08_28` / `_2026_08_29` are git-tracked=NO and both served
200 from production (2,480,712 B / 2,806,937 B). The original 2.46MB tempdir
result was driven by `daily_summary_2026_07_26.json`, which is UNTRACKED and
so cannot exist in a Render checkout.

**WHAT REMAINS:** a BACKFILL or EVALUATION over 2026-05-28 → 2026-07-12 gets
the git mirror's copy instead of production's — the exact window this file's
"lossy mirror" rule already warns backtests run on. Lane
`mlb-resolver-write-side-effect` (LOW priority, not a live incident). Nothing
on the data path has been changed.


**AND THE BANNER NOW SAYS SO** `[2026-08-29 23:24Z, web `3371ad96`]`. The
unknown-submit block on `/portfolio` used to state that only a person opening
the venue's own screen could settle one of these; that sentence and "nothing
here can confirm or deny that a position exists" are DELETED, and a test fails
if either returns. Each row now renders the account's own answer, or states why
it could not (`confounded` / `no_bracketing_reading` / `unreadable`). The page
calls the SAME `_balance_evidence` the worker probe uses, through
`venue_settlement.balance_evidence_for_unknown_submits` — one implementation, a
test asserts the two agree, and it makes NO venue call (arithmetic over the
stamped balance trail plus ledger rows web already holds).
**NOT YET SEEN RENDERING: zero unknown submits exist, so the block is absent
entirely. Verified by tests and by the deployed tree object, not by a live read.**

**AN UNKNOWN SUBMIT CAN BE SETTLED BY THE ACCOUNT, NOT ONLY BY A HUMAN**
`[2026-08-29, VERIFIED]`. `venue_settlement` and `execution_ledger` both said
nothing this system can call settles a submit lost to a 5xx -- true of the ORDER
routes, never true of the account. MEASURED on the $1.84 case: `buyingPower`
96.05 at 21:05:56 / 21:12:47 / 21:18:46 / 21:25:09, then 94.15 only after the
retry filled -- flat across the failed submit, so it never reached the venue.
`venue_balances` now keeps a bounded trail and the probe does that arithmetic.
**Its output (`balance_evidence`/`balance_settled`) has NOT been observed in
production -- the probe only fires when an unknown submit exists, and there are
none. Next genuine 503 is the test.**

**A RETRY USED TO DELETE THE PROVENANCE THAT MADE IT RISKY** `[2026-08-29,
FIXED + VERIFIED]`. `not_placed` is the only thing that sets `rejected`, and
`rejected` is the only thing that makes `record_order` pop the row -- so the pop
deleted `operator_resolution`/`pre_resolution_*`, the exact fields
`resolve_unknown_submit` promises to preserve. Now carried as `prior_attempts`;
read on two real retry rows at 22:50:4x.

**THE CROSS-VENUE NUMBER IS MEASURED, AND IT IS ZERO — BUT NOT FOR A FEE
REASON** `[2026-08-29 ~22:1xZ]`. `/api/board/layer2-shortlist` carries BOTH
venues' prices on the same row in `quote.book_prices`, so this needs one web
call and no credentials. Board `written_at 21:56:11Z`, 1,195 rows: **12
complementary cross-venue pairs, 0 with positive net edge.** Best raw edge
**+0.00c** — and **-0.87c even with a FREE Polymarket**, so the venues simply
agree and Kalshi's own MLB fee exceeds the disagreement. All 12 pairs are
PREGAME and at EVEN MONEY (fee ~3.35c, the parabola's peak); the tail regime
contributed zero pairs.

**THE BINDING CONSTRAINT IS COVERAGE OVERLAP AT THE TAILS**, not fees, not the
YES-leg binding, not the missing executor. 28 live Polymarket rows exist and
**all 28 have `other_side_has_kalshi=False`** — Polymarket quotes one side,
Kalshi does not quote the opposite side of the same market, so no pair can
form. All 28 are totals and **16 sit at the tails** (>=0.90 or <=0.10), exactly
where a 1c gap would clear. Next step is whether that is a LINE MISMATCH
(Kalshi's `KXMLBTOTAL` strike ladder vs Polymarket's `line`) or a join gap.
Building a two-leg executor now would build a consumer for an empty set.

**RETRACTED, and it was my error:** "the Polymarket slate is not published to
web (`export?pattern=*polymarket*` -> `count: 0`)". **FALSE.** `count: 0` on
the artifacts export is a fact about the EXPORT, which scans disk, while
`persist_game_slate` writes to the KEYVALUE store — documented at `ops.py:450`
since 2026-08-27 and reachable the whole time. `/api/ops/polymarket/slate`
returns `count: 17241`. This is the `keyvalue_artifact_split_blinds_guards`
trap, walked into with the rule already on file. No worker-side probe is
needed and nothing needs "publishing".

CAVEAT: `book_prices` is a quote snapshot (`book_age_seconds` ~294s), not a
firm ask, and n=12. Read as "no arb on tonight's 12 observable pairs", NOT as
"no arb between these venues".

STILL BLOCKING EXECUTION `[updated 2026-08-30, session 5611932c]`: the
BLANKET moneyline refusal is GONE — `_resolve_outcome_side` now reads the
venue's own `yesLegIndex` off the stored row and a Polymarket h2h BUILDS
(`ORDER_PATH h2h {'would_build': 1}` at 19:54:08, after five consecutive
`market_unresolved`; live-odds-worker `bf1dd290`). **It still refuses where the
venue states no leg, and where `yesLegIndex` disagrees with our own away-team
position** — a corroboration gate, because `#595`'s stated gate ("score against
all 8 venue-settled moneylines") is UNSATISFIABLE: `marketSides` is never
persisted, so the rule cannot be re-run on a settled market.
**THE LEG CHOICE IS NOT VALIDATED.** All observed reads are `yes_leg_index=0`,
which IS `outcomes[0]`, so the old positional rule agrees and they discriminate
nothing; a `yes_leg_index=1` market is required. `agree=False` has never fired.
NO moneyline has ever been SUBMITTED — `would_build` is not a bet. Also still
true: `#600` (ledger read-modify-write race) landed and NOT deployed, and no
two-leg executor exists — a one-sided fill is a naked position.

`.syndicate/findings_2026-08-29_live_venue_arb_economics.md` carries the tables.

## [kalshi-segment-on-full-game] KALSHI PLACED SEGMENT BETS ON FULL-GAME CONTRACTS: the join key had no `segment` `[verified 2026-08-28, lane portfolio-venue-and-side-integrity]`

**Five orders, $7.08, real money.** `_match_key`/`_row_key` were five-tuples —
game, market, player, line, side — with no `segment`, so a board row for "under
2.5, first 3 innings" matched full-game `KXMLBTOTAL` on every field the key
carried.

    first3  under 2.5  KXMLBTOTAL-26AUG281940TEXMIL-3  +1900,  5c
    first3  under 2.5  KXMLBTOTAL-26AUG282138PHILAA-3  +1900,  5c
    first3  under 2.5  KXMLBTOTAL-26AUG281845MIAWSH-3  +1900,  5c
    first3  under 2.5  KXMLBTOTAL-26AUG281840LADDET-3  +1567,  6c
    first5  under 3.5  KXMLBTOTAL-26AUG281840LADDET-4  +567,  15c

The +1900 is not an edge: the model priced three innings against the venue's
nine-inning price, correctly ~5c. **A mis-keyed join presents as the best line
on the board**, so edge-ranking selects for it. All five will lose. Kalshi has
`KXMLBF5TOTAL` and we already fetch it — a mis-SELECTION, not an impossibility.

**FIXED, DEPLOYED AND MEASURED** — `632f3473` + `#602` `d2ab7e86` + `#604`
`361d8940`, live in `420dddaa`, BOOTED 21:55:15Z. **BOTH GUARDS FIRE:**
`board_row_is_a_segment_bet` 52 then 39 (Polymarket),
`segment_has_no_matching_series: 2` (Kalshi). **THE DEFECT SPANNED BOTH VENUES
— 9 bad orders, not 5** (Kalshi 5 ~$7.30, Polymarket 4 ~$9.38); the second was
found by repeating the audit, not by a report.

**PROVEN TO FIRE, NOT PROVEN TO HAVE CHANGED AN ORDER.** Zero orders were
placed after either boot, so the money-level check is vacuous. Re-run on the
next slate that actually places.

**THAT RE-RUN IS DONE — THE DEFECT IS NOT LIVE, AND NOTHING HAS MIS-FILLED SINCE**
`[verified on production 2026-09-05, lane segment-execution-ticker-audit;
working in .syndicate/findings_2026-09-05_segment_execution_ticker_audit.md]`.
Prompted by a re-grade agent reporting 10 venue-settled segment orders whose
venue outcome matched our FULL-GAME grade on 9 of 10 and our SEGMENT grade on
0 of 10. That reading is CORRECT and it is about **this** defect, on
**2026-08-26 and 2026-08-28 only** — every one of the 10, zero later.

Rates, both modes, denominators named. Era split on `submitted_at` against the
21:55:15Z boot:

| population | n | got a `venue_ticker` | on a FULL-GAME series |
|---|---|---|---|
| LIVE kalshi, `segment != full` | 37 | 5 | **5/5**, all `KXMLBTOTAL` |
| — POST-boot | 23 | **0** | 0 |
| PAPER kalshi, `segment != full` | 70 | 5 | 5, all `KXMLBTOTAL` |
| — POST-boot | 45 | **0** | 0 |
| LIVE polymarket, `segment != full` | 6 | 6 (`aec-` slug) | all PRE-boot |
| — POST-boot | **0** | 0 | 0 |

The 5 live Kalshi fills are 2026-08-28T05:17:26Z..T05:49:17Z — ~16h BEFORE the
boot — and are the same five tickers listed above.

**THE FIELD IS `venue_ticker`, NOT `ticker`,** on `orders[]`/`unreconciled[]` of
`/api/portfolio/live?on=all&show=all` and on `/api/portfolio/paper?date=<D>`.
A walk for `ticker` returns 0 rows from either. `ledger-summary` emits no ticker
BY CONSTRUCTION (`_LEDGER_SUMMARY_FIELDS`), so it can never answer this.

**THE GUARD IS FIRING, WHICH IS THE ONLY THING THAT MAKES THE NULL MEAN ANYTHING.**
`segment_has_no_matching_series` = **257 refusals over 38 join ticks in 30h** on
the running refresh-worker (`933e9bebf154`), on both `[kalshi_odds] BOARD_JOIN`
and `[portfolio_commit] KALSHI_BOARD_JOIN`. Needed because the post-boot null
is otherwise vacuous: all 23 post-boot refusals are `OrderBuildError:
no_venue_ticker` on `totals_alt`/`spreads_alt`/`h2h_3_way`, and those same three
markets **also refused `no_venue_ticker` PRE-boot, 9 of 9**. The reason does not
discriminate, and the shape that DID mis-fill (plain `market=totals`) has not
been attempted by a segment row once since. Post-boot live kalshi on plain
`totals`: 46 orders, 0 segment, 46 full, 40 tickered — the join is alive.

Guard present by CONTENT on all three live SHAs: refresh-worker `933e9bebf154`,
live-odds-worker `7f197639cc97`, web `3cb5b4ba6750`. Choke point confirmed:
`kalshi_ticker_resolver` reads only `matches`, and both — the only two —
`matches.append` sites are immediately preceded by `_segments_agree`.

**THE MECHANISM IS CONFIRMED AS HISTORY:** `KXMLBTOTAL` was hand-registered
2026-08-25 (the title gate missed it; before that a `totals` row had nothing to
join to and refused `no_live_price`). The mis-fills are three days later.

**THE FIX BOUGHT SAFETY, NOT CAPABILITY — SEGMENT EXECUTION ON KALSHI IS
0-FOR-EVERYTHING.** No order in the whole 2,853-order population has ever
carried a `KXMLBF5*` ticker. `first5` is mapped and executable in principle and
never has been (every first5 order attempted is `totals_alt`/`spreads_alt`,
which map to no Kalshi board market). `first3` is **inherently unexecutable**:
no first3 entry in `_SERIES_SEGMENT` and no Kalshi first-3-innings series exists
(`KXMLBINNINGTOTAL` is per inning). Still unproven, unchanged from above: the
guard is proven to REFUSE, never yet proven to have CORRECTED a fill.

**FOR ANY SEGMENT RE-GRADE WRITE-BACK: EXCLUDE THE 10 VENUE-SETTLED ROWS.** Not
only because a venue settlement outranks our inference — for the 5 Kalshi rows
the contract we HELD was a full-game contract, so the venue's grade is the
correct grade of the bet actually owned. `reports/segment_regrade/manifest_2026-09-05.json`
proposes `outcome_changed=True` on `KXMLBTOTAL-26AUG281840LADDET-3`
(`lost` -> `won`); applying it would invent P&L no position earned.
`segment_for_series` + `segment` in both key tuples + `series` stamped at both
match-record sites (neither carried it). Unmapped defaults to `full` because the
protection is on the BOARD side; refusal is reserved for an unmapped series
carrying a segment MARKER (F5/INNING/1H). Refusing ALL unmapped — my first
version — would have unindexed the whole prop book. 9 tests, 127 passing.

**THE SERVICE IS refresh-worker, MEASURED NOT ASSUMED** `[2026-08-28T20:19Z]`:
`[portfolio_commit] KALSHI_BOARD_JOIN` appears on refresh-worker and NEVER on
live-odds-worker over the same 2h window. Execution stamps `ticker_resolver(row)`
verbatim from the plan, so the ticker is decided at commit time.

## [kalshi-venue-execution] KALSHI ORDERS: the blocker was SHARD COLLATERAL, and spreads were inverting the bet `[verified 2026-08-26, lane kalshi-spread-join-sign]`

**Kalshi splits markets across EXCHANGE SHARDS, and balances are PER-SHARD.**
`GET /trade-api/v2/exchange/status`: `0 Default`, `1 Combos`, `2 Crypto`,
**`3 Tennis & Baseball`** — all `trading_active`. `exchange_index` is on the
PUBLIC market payload, so the shard of any ticker is readable WITHOUT
credentials. MLB is shard 3; NFL, NBA and WNBA are shard 0.

**The account had collateral only on shard 0, so every MLB order failed.** Split
perfect at n=12: every fill ever is on a funded shard, every failure was shard 3
before funding. `exchange_index: 0` (pinned) gave `market_not_found`; `-1`
(auto-route) gave `user_not_found: <uuid>`. **Both errors were literally true and
NEITHER was ours.** Discharged 2026-08-26 after the user moved $25 to shard 3 —
three MLB fills, all `executed`, all `exchange_index=3`.

**THIS IS THE ACCOUNT HOLDER'S ACTION, NOT THE VENUE'S.**
docs.kalshi.com/getting_started/exchange_sharding.md: *"Subaccount balances are
local to a specific exchange instance"*, *"Programmatic traders must preallocate
collateral on a given exchange shard before order placement."* Fund at
kalshi.com/account/exchange-indexes or via the intra-account-transfer API;
`set-target-balance-allocation` auto-rebalances. `KALSHI_ORDER_KNOWN_SHARDS`
(live-odds-worker) is `0,3`.

**The order contract is CONFIRMED FROM THE DOCS, not inferred:**
`POST /portfolio/events/orders`; `side` is `bid`/`ask` **quoted from the YES leg
only** (no `action` field, no separate buy/sell); `exchange_index: -1` requires
auto-routing by ticker.

**SPREADS WERE PAIRING WITH THE OPPOSITE BET.** A Kalshi spread states a MARGIN
(`"Texas wins by over 1.5 runs"` = `TEX -1.5`); the board writes a HANDICAP, so
that game's rows are `TEX +1.5` / `CWS -1.5`. The join keyed on Kalshi's bare
MAGNITUDE, so `1.5 == 1.5` paired the market with the `+1.5` row. Measured over
the served board and 90 open KXMLBSPREAD markets: **15 of 30 matches put YES on
`+1.5`**; on the live book all 11 spread orders carried the ticker of the club
they were FADING. Only `_side_to_kalshi` refusing `home`/`away` kept it off the
venue. FIXED both ends — the join names both reachable rows (NAMED club at `-X`
-> YES, OTHER club at `+X` -> NO) and the order builder derives the leg from the
SIGN of the line. AFTER: 0 violations. First spread order ever placed
2026-08-26T17:26:18Z, `KXMLBSPREAD-26AUG261540CHCAZ-AZ2` home `-1.5` -> YES,
filled 3 @ 0.33, venue title *"Arizona wins by over 1.5 runs?"* matching the row.

**Cloud sessions cannot reach the venue or docs hosts** (`connect_rejected`),
which is why several comments in this path recorded guesses. Both hosts answer
from a non-proxied network. Venue facts:
`.syndicate/findings_2026-08-26_venue_api_unblock.md`.

## [kalshi-coverage-vs-oddsapi] KALSHI COVERAGE: capture is healthy, the JOIN is the bottleneck, and two prop vocabularies do not exist `[verified 2026-08-25, lane kalshi-oddsapi-coverage-audit]`

**UPDATED 2026-08-27, lane `venue-quote-line-join`. "THE JOIN IS THE BOTTLENECK" WAS RIGHT AND UNDER-SPECIFIED — FOUR SEPARATE DEFECTS, ALL NOW FIXED AND MEASURED:**
1. **No Kalshi quote carried a PRICE.** The adapter read `yes_bid`/`last_price`; `_LEAN_MARKET_FIELDS` persists neither. 400 nfl / 400 ncaaf / 121 wnba quotes had `probability=None` while `status` read `ok`. Now read from `*_probability` / `*_ask_dollars`; `leg_without_price` counts the residual.
2. **A threshold market offered ONE leg.** Kalshi titles every total as an OVER, so only that side was published. Both legs now, each from its OWN quoted price — never `1-p`, which would erase the spread. nfl/ncaaf quotes 400 -> 800.
3. **Prop keys named no PLAYER**, so every player's row in a market collapsed to one key and the first row took a quote describing someone else. Cross-sport, not soccer-only. Now keyed with `kalshi_board_join.normalize_person`. Cost, stated in advance: kalshi selections 2,533 -> 550, mlb unmatched 530 -> 1,437 — that fall IS the correction.
4. **One sport could evict another** from the 6,000-market working set. `PER_SPORT_FLOOR_MARKETS=300`; measured `TRIM_BY_SPORT kept=6000 trimmed=3262 kept_by_sport={mlb:300, nba:6, ncaaf:300, nfl:300, soccer:300, wnba:300}`.

**AND THE VENUES NOW HAVE THEIR OWN CLOCK.** Both refreshes rode the live worker's ADAPTIVE loop, which returns the ~900s IDLE interval whenever no game is live — so every cadence env var was a lever that did nothing. A dedicated thread (`start_venue_poll_loop`) took kalshi ~1,250s -> ~120s and polymarket 428-828s -> ~120s. `SYNDICATE_VENUE_POLL_INTERVAL_SECONDS` (default 60, floor 30) now set to 120.

**STILL TRUE AND STILL UNFIXED:** kalshi wins ZERO soccer rows despite being the freshest feed — `offered_overlap_by_sport` shipped to tell coverage from freshness and has NOT been read on a build where kalshi has soccer quotes. And a TOTALS key names no GAME: 672 polymarket soccer quotes collapse to SIX, so one fixture's price can stamp another's row — the same class as defect 3, on a different axis.

Full audit: `docs/ai_context/kalshi_oddsapi_coverage_audit.md` (branch
`claude/kalshi-oddsapi-coverage-audit`, `4152111e2`). Evidence is production
log lines with timestamps; regenerate with
`scripts/audit_kalshi_oddsapi_coverage.py`.

**KALSHI LISTS 13,472 SERIES** `[KALSHI_SERIES_CATALOGUE status=ok, 20:21:24.977Z]`.
By ticker token: MLB 174, NBA 351, WNBA 91, NHL 52, NFL 323, NCAAF 126,
NCAAB 20. **NBA's 351 INCLUDES WNBA's 91** -- `series_matching` is a substring
match and `NBA` sits inside `WNBA`. **Soccer has no line at all**, because
`_KALSHI_SPORT_TOKENS` is the 7 sports and soccer is named by competition.
That is "we cannot see it", NOT "Kalshi does not list it".

**`[kalshi_discovery] LISTED` IS NOT THE CATALOGUE AND MUST NOT BE READ AS ONE.**
`truncated=True` on 7 of 7 runs observed, `combinatorial` 39,350-39,976 of
40,000. `singles` swung 24 -> 650 between consecutive runs on pagination luck.
**Every per-series count derived from it is a floor.**

**THE BOTTLENECK IS THE JOIN, NOT CAPTURE.** Latest `BOARD_JOIN` 2026-08-26
`01:49:32Z`: `kalshi_markets=6000 board_rows=1291 matched=71`,
`market_is_for_another_date=3282 no_matching_board_row=1838
unreadable_title=493 stat_not_in_market_vocabulary=304`. `unreadable_title`
fell 3703 -> 493 on the title-grammar work (`8efdf0ff7`, `1c6e10281`), and
`no_matching_board_row` is now the largest addressable bucket.
`market_is_for_another_date` is NOT addressable -- it is a DESCRIPTION:
`BY_GAME_DATE` summed is 1958 today / 60 tomorrow / 3982 beyond, so a lookahead
venue plus a date-blind cap must produce it `[verified 2026-08-26]`.
`VENUE_REPRICE_KEYS` on ten consecutive readings 19:35-20:18Z lists Kalshi in
**NO `sources_offered` bucket** for any sport. **So no OddsAPI market may be
cancelled in favour of Kalshi yet** -- that turns a metered market into a
missing one. Order: fix the join, measure `matched` per family, then cancel.

**NO NHL AND NO NCAAB PLAYER PROP COULD EVER AUTO-REGISTER -- FIXED
`b8a958fe6`, NOT YET DEPLOYED, and unobservable until those seasons start.**
`market_keys._BY_SPORT` had no `nhl` and no `ncaab` key, and
`auto_series_from_catalogue` gates registration on `canonical_market_key`
resolving. `_TOTAL_UNIT` *does* carry both, so game totals work and props
cannot -- which is why it reads as coverage. `KXNHLSAVES`, `KXNHLANYGOAL`,
`KXNHLPTS` are already listed. Identical to the defect `market_keys`' own
header records for NFL (`ticker_substring_n=317 classified_n=0`).

**LADDERS: THE RECORD IS WHOLE, THE JOIN'S INPUT IS NOT.**
`MAX_MARKETS_PER_SERIES=400` against `KXNCAAFSPREAD`'s **1994** real markets is
one rung in five; `KXNFLSPREAD` **795** is one in two. Per-tick `trimmed=`
862-2983. Surviving rungs are `markets[:400]` in API order, not the ones near
the line. `_record_daily_book(full_markets)` runs before both bounds
(`e4ae9ebec`, live 18:56Z), so the dated capture files ARE whole.

**SOCCER REGISTERS AS OF `461ee74be` (live 20:20:57Z).** `AUTO_SERIES`
20:32:19Z read `game_series=204` where every prior run read **173**, with
`('KXMLSTOTAL','soccer')` in the sample. **Any reading before 20:20:57Z
describes a system that no longer exists.** What remains is scoped:
(a) only the 10 competitions in `LEAGUE_DISPLAY_NAMES` can register -- UCL,
UEL, UECL and EFL Cup are absent BY DESIGN, a product call, not a defect
(`KXEFLCUPSPREAD` still `unmapped_series` 20:33:06Z); (b) soccer PROP series
still cannot, because Kalshi titles them "La Liga Goal" with no word "Player"
(`KXLALIGAGOAL` 5, `unmapped_series`, 20:33:06Z).

**TWO ONE-LINE FIXES, MEASURED, NOT APPLIED** (20:33:06Z, 180 live markets):
`KXMLBHRR` **136** refuses `stat_not_in_market_vocabulary
detail="hits + runs + RBIs"` -- registered 12 minutes earlier by `461ee74be`
and still refusing, the largest MLB prop family on the venue, one
`market_keys._MLB` line. `KXMLBSB` **44** refuses `unmapped_series`
("1+ stolen bases"), one registry line plus one vocabulary line.

**`KXNBAPTS` IS A REAL, LISTED, AUTO-DISCOVERED SERIES.**
`kalshi_catalogue.py`'s header uses it as its example of an invented ticker;
it appears in `AUTO_SERIES sample` on six reads on 2026-08-25. The principle
is right and should stand -- the EXAMPLE is falsified and misleads anyone who
checks it.

## [kalshi-execution] Kalshi execution — session close 2026-08-26 (lane `kalshi-exchange-index`)

**DONE 2026-08-26: shard 3 is FUNDED — $25 moved to exchange index 3**, and
`KALSHI_ORDER_KNOWN_SHARDS=0,3` is set on live-odds-worker (set by
syndicate-43, readback confirmed). Kalshi balances are PER-SHARD and must be
preallocated; shard 3 is "Tennis & Baseball", which is why only MLB failed.

**VERIFIED 16:19:13Z — MLB IS FILLING. Funding shard 3 was the whole blocker.**

```
RECONCILED KXMLBHRR-26AUG261310TBDET-DETHLEE50-2 submitted->filled
  contracts=11 fill_price=0.4  fees=0.0924
RECONCILED KXMLBTOTAL-26AUG261940TEXCWS-8        submitted->filled
  contracts=5  fill_price=0.47 fees=0.0436
```

Those are the SAME two tickers that returned `market_shard=3` refusals an hour
earlier. First MLB fills since 08-24. ~$6.75 of the $25 committed.

**The next constraint is collateral, not correctness:** $25 on shard 3 against a
$10/order cap is a couple of orders per cycle. Expect insufficient-collateral
errors rather than shard errors from here.

**Verified working today:** Kalshi fills on shard 0 (`KXWNBA3PT` filled
16:03:06Z, 10 contracts @ 0.40 + 0.168 fees, ~1s round trip). Polymarket
reconciling clean (15 orders, `not_found=0`). Bankroll $1000, caps $10/order,
15/book, 25/day.

**Kalshi order body — settled, do not re-litigate:**
- `POST /portfolio/events/orders` on `external-api.kalshi.com` — CONFIRMED from
  the venue's own docs, not inferred.
- `exchange_index: -1` (auto-route by ticker). A literal `0` PINS shard 0 and
  returns `market_not_found` for anything elsewhere.
- `subaccount: 0` — omitting it was deployed, disproven, reverted. Every fill
  the account has ever taken carries `0`.
- `side` is `bid`/`ask` only, quoted from the YES leg. The UI's
  `op_order_side`/`op_side` are UI params, not body fields.

**Still open, none of it blocking:**
- `#573` — refuse by READING `GET /portfolio/balance?exchange_index=N` instead
  of a hardcoded `funded_shards` list. Self-heals the moment the shard is
  funded; turns the last inferred step into a measurement.
- Kalshi spreads/h2h side plumbing — **owned by syndicate-43**
  `[USER DECISION 2026-08-26]`. `unmappable_side` is currently a GUARD, not a
  gap: the join pairs a `+1.5` board row with the same team's `-1.5` market, so
  clearing the refusal without fixing the join inverts ~10 bets a cycle.
- `no_venue_ticker` on h2h — `price_source=aggregator`, so no Kalshi ticker is
  ever stamped. Nobody holds this.
- Polymarket per-order reads cannot detect orphans by construction (no list
  route, `GET /v1/orders` -> `code: 12` UNIMPLEMENTED). `coverage=per_order`
  says so on every RECONCILE line.

## [kalshi-odds-refresh-bound] THE VENUE FAN-OUT IS A COLD-START BURST ON A PERSISTED CLOCK, AND IT IS NOW TIME-BOUNDED `[2026-09-03, lane kalshi-discovery-deadline, LOCAL measurements, NOT deployed]`

`run_kalshi_odds_refresh` — NOT discovery, which is capped at 10 series and paced
0.5s. The loop is `_due_series(state, ...)` -> `cold[:series_per_tick()]` ->
`fetch_series` -> `fetch_markets`, gated by a per-series clock persisted in
`reports/intelligence/kalshi_markets.json` (`markets_artifact_path()`).

    DEFAULT_SERIES_PER_TICK   150    <- exactly the 150 distinct series measured
    DEFAULT_REFRESH_INTERVAL  120s   per series
    DEFAULT_DORMANT_INTERVAL 3600s   for a series that read empty

**REPRODUCE ON DEMAND:** delete the state file -> every series due ->
`fetch_markets` **150 calls / 50.1s**. Do NOT read a quiet tick as "the venue is
quiet": within the dormant hour the correct behaviour is zero calls.

`request_budget(seconds)` now wraps the whole refresh (env
`SYNDICATE_KALSHI_REFRESH_BUDGET_SECONDS`, default 30, `0` disables), so all
three callers inherit it. Measured on the real cold tick: **50.1s -> 10.7s**, and
a cold queue drains 25/31/53 across three ticks with nothing lost.
**The bound covers VENUE REQUESTS, not the function** — wall clock exceeds it
(32-47s vs 30s) because merge and state-write follow the loop.

**THE TRAP IT AVOIDS, and why the wiring is not a one-liner:** `fetch_markets`
returns a PARTIAL result on exhaustion rather than raising, and the refresh reads
an empty successful read as "no open markets" -> dormant for an hour. Stopping
mid-fetch would have marked up to 150 series empty and blanked them off the
board. The loop therefore checks `budget_remaining()` BEFORE spending.
