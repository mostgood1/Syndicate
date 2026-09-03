# state — venues

Split out of `state.md` by `scripts/split_state.py`. Bodies are verbatim.
The INDEX of every subject, across every part, is in `state.md`; the
one-subject-one-section rule is global and spans these files.
Same rules as state.md: when a fact changes, EDIT THE LINE.

## [603-cross-game-quote-keys] VENUE QUOTES NAMED NO GAME; FIXED ON EVERY PATH, DEPLOYED, AND STILL UNPROVEN AFTER THREE READINGS `[2026-08-30, lane live-venue-order-placement]`

`quote_key` was `sport|market|side|line` and the fan-in resolves it against a
SPORT-WIDE pool, so one quote answered every fixture sharing a `(side, line)`.
Measured 2026-08-29: **26 of 28 live Polymarket totals quotes shared across
games** — `over 7.5 @ -400` on AZ@SF, COL@ATL, HOU@NYM and SD@TB at once, where
COL@ATL was worth ~2% and SD@TB had ALREADY WON. `best_any_book` was
`polymarket` on 28 of 28 of those rows.

**FIXED on all five surfaces** (`0c5243b4` live on refresh-worker
2026-08-30T01:21:03Z, content-verified): board `_candidate_keys`, the Kalshi
adapter (ticker blob via `match_event_blob` + schedule), Polymarket (slug clubs,
and for NCAAF the moneyline's nicknames), OddsAPI (its shard key already named
both clubs), and the GRID path. Role-keyed markets only — h2h keys by CLUB and
cannot collide. Bare key first, qualified second, plus a match-time rejection
(`CROSS_GAME_REJECTED` / `_GRID`) so an unqualified match on the wrong fixture is
refused rather than used.

**IT IS NOT VERIFIED. Three production readings, none of them evidence:**

    polymarket ncaaf   live=5  keys=5  collidable=0   UNMEASURABLE
    kalshi     mlb     live=7  keys=7  collidable=0   UNMEASURABLE
    kalshi     soccer  live=8  keys=6  collidable=2   FAIL

**A zero is only evidence if it could have been a one.** In the first two, no
two live games shared a `(side, line)`, so the count would read 0 with the
module deleted. Soccer is the only real reading and it still shares.
`scripts/verify_603_cross_game.py` now computes COLLIDABILITY FIRST and returns
`UNMEASURABLE` (exit 3) rather than a soft pass.

**Soccer residual, diagnosed:** four MLS codes (`NYRB`, `POR`, `LAG`, `STL`)
absent from the soccer alias map, so `match_event_blob` cannot complete a split
and the key stays bare. Patch verified by monkeypatch (4/4 `no_match` → `ok`,
no cross-league leakage — `STL`/`POR` collide with other sports so it must stay
sport-scoped). HANDED OFF: `handoff_2026-08-30_kalshi_soccer_mls_codes.md`;
`team_aliases.py` has multiple claimants.

**DO NOT fix NCAAF by populating `_alias_map("ncaaf")`** — built, measured and
REVERTED 2026-08-29; it makes `teams_match` map-authoritative and turns
`canonical_team("ncaaf","MAS")` → `UMass Dartmouth` into a confident wrong
answer.

Scheduled task `verify-603-cross-game-mlb` fires 2026-08-30 20:15 CT.

## [venue-fee-economics] FEES ARE READ FROM THE VENUE AND VERIFIED AGAINST 18/18 REAL FILLS; THE ARB THRESHOLD WAS ABOVE BREAK-EVEN EVERYWHERE ON MLB `[2026-08-30, lane live-venue-order-placement]`

Kalshi publishes `fee_type`/`fee_multiplier` per series — four distinct
combinations, and **every MLB game/total/spread/K series is HALF RATE**. Base
rate 0.07 measured off 27 of our own fills (21 at multiplier 0.5 → 0.0350, 4 at
1.0 → 0.0700 — discriminating), checked for circularity first. **Rounding is
ceil to a HUNDREDTH of a cent: 18/18 exact, vs 9/18 for round-to-4dp and wrong
for the whole-cent rule every third-party source states.**

`kalshi_polymarket_arb.DEFAULT_FEE_BUFFER = 0.04` demanded a flat 4.00c gap at
every price while MLB break-even runs **3.38c at even money down to 0.39c at
0.97** — above break-even everywhere, so that detector was structurally
incapable of reporting a profitable MLB pair.

**CROSS-VENUE ARB MEASURED: 12 complementary pairs, 0 positive.** Best raw edge
**+0.00c**, and **−0.87c even with a FREE Polymarket** — the venues agree and
Kalshi's own MLB fee exceeds the disagreement. All 12 were pregame and at even
money; the tail regime (break-even 0.52-1.11c against a 1c spread) contributed
none. **Kalshi trades in-play and is liquid** (14 markets, `vol24 904,281`, 1c
spreads, prices moving between reads) — so the live opportunity is FEE
GEOMETRY, not model edge.

**POLYMARKET'S FEE IS 150 bps OF NOTIONAL** `[2026-08-30, CORRECTED]`.
`0.015` per contract, FLAT, independent of price. Reproduces all five real
`commissionNotionalTotalCollected` values within a cent (18.70 contracts ->
$0.28 modelled $0.2805). A cost basis (3.247% of cost) was REJECTED on the
largest fill, where cent-rounding matters least.

**RETRACTED: the entry that stood here said the fee was ZERO.** That was
inferred from the venue's realized P&L at settlement, and realized P&L is
`(exit - entry)` on the position, so **a commission taken at FILL is invisible
to it by construction** — the method returns zero whether or not a fee was
charged. Disproven on its own sample: `C60JWBG0WKDK` implied -0.0023 there while
the venue charged $0.06; two more of the ten were also commissioned. Caught by
peer lane `unknown-submit-retry-provenance`, whose `98e103e1`/`fb749d97` made
the field readable AFTER my reading, and who had an independent cash-movement
route agreeing to the cent.

**POLYMARKET IS THE DOMINANT LEG COST, and the earlier inversion of that was
wrong.** Kalshi's fee is a parabola that vanishes at the tails; Polymarket's is
flat and does not. At P=0.94 Kalshi MLB is 0.0020/contract, Polymarket 0.0150 —
seven times larger. MLB two-leg break-even: **2.50c at even money, 1.70c at
0.94** (the retracted zero said 0.88c / 0.20c, i.e. **2.8x too permissive** — a
threshold below true break-even manufactures arbs that lose on every fill).

The arb VERDICT is unchanged and fails by MORE: best raw edge +0.00c.
**RESOLVED 2026-08-30 — IT WAS NEVER A CONTRADICTION.** `commissionsBasisPoints`
reads `'0'` beside a real `collected` because **the fee is FLAT PER CONTRACT
($0.015) and therefore has no ad-valorem component for a rate field to
express.** 18.70 contracts -> $0.28, 3.91 -> $0.06, 2.38 -> $0.04. Against the
$1 notional that equals 150 bps, but the venue does not report it that way.
**`bps == 0` is evidence of the fee's SHAPE, never of its ABSENCE** — reading it
as absence is exactly what produced the retracted zero above. Guarded in code:
`COMMISSION_RATE_APPEARED` fires if a non-zero rate ever shows up (`c0989cfe`).

## [polymarket-live-totals-quote-names-no-game] 26 OF 28 LIVE POLYMARKET TOTALS QUOTES ON THE BOARD ARE SHARED ACROSS GAMES — one price per LINE, no game identity `[verified 2026-08-29 ~22:3xZ, lane live-venue-order-placement]`

Live Polymarket totals quotes in `quote.book_prices` are keyed on the LINE and
fanned out across every live game carrying that line:

    over  7.5 @ -400   AZ@SF, COL@ATL, HOU@NYM, SD@TB      (4 games)
    under 7.5 @ +344   the same 4
    over  8.5 @ +1233  3 games      over 9.5 @ +1900  3 games
    over 10.5 @ -6567  2 games

**IMPOSSIBILITY CHECK, which is what proves it a defect rather than a market:**
COL@ATL was 1 run in the 7th, so over 7.5 is worth ~2% (Kalshi quoted 0.08);
SD@TB was 13 runs, so over 7.5 had ALREADY WON at 100%. Both carry `-400`
(=80%). One price cannot be both.

**PREGAME rows are UNAFFECTED** — BAL@ATH, PHI@LAA, TEX@MIL totals all carry
prices unique to their game. The collapse is on the LIVE path only.

**`best_any_book` is `polymarket` on 28 of 28 live totals rows**, so the
fabricated cross-game quote is what the board presents as the best available
price; `model_edge_pct` reaches 14.92 on rows priced off it.

**NOT AN INCIDENT, A HAZARD — and the reason is specific.** `ev_pct` on these
rows is -0.99 to -1.40 so none is surfacing as a +EV bet, and the ORDER path
does not read `book_prices`: `execute_portfolio._polymarket_resolve_market`
prices from the per-market SLATE row. **No order has been priced off these
numbers.** Price shopping, best-book display, and any future `book_prices`
consumer on a live row ARE affected.

This is the defect OPEN lane `venue-quote-line-join` recorded as UNFIXED — "a
TOTALS key names no GAME", previously 672 soccer quotes collapsing to six keys.
Same class, now measured on MLB live with a one-read signature (identical price
on two games whose scores make it impossible).

**CONSEQUENCE FOR CROSS-VENUE WORK: no measurement on live Polymarket totals
means anything until the key names the game.** A net-edge computation over
these rows returned +10.93c to +84.75c per contract — recognised as impossible
(an 85% risk-free return against ~$900k daily turnover) and traced rather than
reported. The arithmetic was right; the input was another game's price.

SEPARATELY ANSWERED, the Kalshi side of the same question: of the 13 live
(game, line) totals combos, **6 ARE listed on Kalshi right now (join gap,
recoverable) and 7 are genuinely absent at the venue** — 5 because Kalshi
prunes settled in-play strikes as runs accumulate (SD@TB at 13 runs floors its
ladder at 13.5; KC@CLE at 10 floors at 10.5) and 2 because the game was final.
Pruning lags rather than tracking exactly: HOU@NYM at 6 runs still listed 5.5.

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

## [venue-join-refusal-visibility] WHY THE EXCHANGES DO NOT EXECUTE SOCCER OR PROPS, and the two instruments that were lying about it `[verified 2026-08-28T16:13Z, lane venue-join-refusal-visibility]`

- **Kalshi's join refusal breakdown was discarded on EVERY build in that log
  line's history.** `portfolio_commit` printed `joined.get('refusals')`;
  `join_kalshi_to_board` returns it under `reasons`. Fixed in `26a5be42`. First
  populated reading, 16:13:11Z: `matched=198/1308 reasons={'no_matching_board_row':
  4500, 'market_is_for_another_date': 3203, 'unreadable_title': 2260,
  'series_out_of_scope': 1334, 'stat_not_in_market_vocabulary': 255,
  'event_not_on_our_board': 239, 'spread_line_orientation_mismatch': 24,
  'team_side_unresolved': 13}`.
- **THE ABOVE IS SUPERSEDED — CORRECTED 2026-09-01 ~20:0xZ, read from production.
  THE SOCCER TITLE PARSER IS FIXED AND HAS BEEN SINCE 2026-08-28/30.**
  `[kalshi_odds] BOARD_JOIN` at 19:51:47Z: `unreadable_title` is **18 of 6,000
  markets**, and every sampled `unreadable_title` GAP family today is NCAAF
  SEASON AWARDS (`KXNCAAFACCAWARD` 99, `KXNCAAFBIG12AWARD` 98,
  `KXNCAAFBIGTENAWARD` 98, `KXNCAAFSECAWARD` 100 — futures with no board market,
  correctly refused). **ZERO soccer series appear in the gap list.**
  `kalshi_catalogue` carries `_SOCCER_DRAW` ("Tie is the result"), `_SOCCER_BTTS`,
  `_SOCCER_TOTAL` ("Will over 5.5 goals be scored?") and the
  `more than`/`less than` spread wording, all read from production titles.
  **Anyone told "fix the Kalshi soccer title parser" would ship an inert change.**
- **THE REAL REASON KALSHI SOCCER NEVER REACHES THE BOARD IS THE DATE, AND IT IS
  THE SAME DEFECT THE POLYMARKET JOIN ALREADY FIXED.** `kalshi_board_join`
  compares each market's `game_date_from_ticker` against a SINGLE scalar
  `wanted_date = selected_date` (lines 599/722/950) and refuses anything else as
  `market_is_for_another_date` — **3,495 of 6,000, the largest refusal bucket.**
  Measured from `[kalshi_odds] BY_GAME_DATE` 19:51:44Z: Kalshi's working set
  holds **~900 full-game soccer markets spanning 2026-09-02..09-15 and NOT ONE
  dated today** (KXMLSTOTAL, KXLALIGA/LIGUE1/SERIEA/BUNDESLIGA/EREDIVISIE
  GAME+SPREAD+TOTAL, KXBELGIANPLGAME). Soccer is never same-day, so an
  exact-date join can only ever match zero of it. The sibling
  `polymarket_board_join` solved exactly this with a SOCCER-ONLY, FORWARD-ONLY
  widening at `_FORWARD_HORIZON_DAYS = 14` — the same span Kalshi's soccer set
  occupies.
- **NOT FIXED HERE, and it is a USER DECISION because it is the MONEY PATH.**
  `kalshi_board_join` feeds order pricing, and widening soccer date matching
  would make soccer markets priceable and orderable for the first time — on a
  sport whose model is recorded as NOT beating the market (`soccer-model-dispersion`:
  worse than market in 8 of 9 leagues). Coverage and profitability are different
  questions and this change couples them.
- **KALSHI DOES LIST SOCCER; OUR CATALOGUE CANNOT READ ITS TITLES.** ~665
  markets refuse `unreadable_title`: `KXMLSTOTAL` 90, `KXLALIGATOTAL` 66,
  `KXLIGUE1TOTAL` 60, `KXSERIEATOTAL` 60, `KXBUNDESLIGATOTAL` 54,
  `KXEREDIVISIETOTAL` 54, `KXSERIEAGAME` 40, `KXLALIGAGAME` 39,
  `KXBUNDESLIGAGAME` 36, `KXLIGUE1GAME` 34, `KXBELGIANPLGAME` 12,
  `KXEREDIVISIEGAME` 9, + segment/award series. This is a PARSER gap, not a
  coverage gap, and it was unreadable for as long as the line printed `None`.
- **THE POLYMARKET SPREAD SIGN TEST CANNOT ANSWER ITS QUESTION AT ANY SAMPLE
  SIZE.** Polymarket publishes BOTH legs at every line — 12 of 12 sampled MLB
  fixture/magnitude pairs carry `pos` AND `neg` — so the slug's sign names a
  LEG, not a TEAM. Verdict now `NON-IDENTIFYING`, `rate=None`,
  `both_signs=17` (16:06:53Z). **Its old ladder mapped ~0.5 to `FALSIFIED: do
  not ship a mapping on this` and was at n=17 of 30** — it would have recorded
  a property of the instrument as a measurement about the venue. Answering it
  needs PRICE or SETTLEMENT. Spreads stay refused, unchanged.
- **Polymarket props are structurally out of scope BOTH WAYS**: 8,029
  `market_type_not_a_game_line` (the venue's PROP markets) and 922
  `board_market_not_a_game_line` (70% of our board — `batter_*`,
  `alternate_totals_corners`, `spreads_alt`, `player_*`). Polymarket carries no
  player-prop resolution; Kalshi does and its 7 prop families place fine.
  **SUPERSEDED 2026-09-01 `[lane polymarket-prop-quote-capture]`: MLB player
  props are IN SCOPE for the JOIN + QUOTE CAPTURE as of `9a436fab`**
  (verified 18:10:22Z, capture appended 0→374; both counters above collapsed:
  6,960→3,375 / 935→138). "Carries no player-prop resolution" conflated two
  things: the venue LISTS player props (its largest bucket); what we lacked
  was a measured player-token decode, which now exists (97/99 exact,
  `.syndicate/findings_2026-09-01_polymarket_prop_census.md`). ORDER
  placement on Polymarket props sits behind `SYNDICATE_POLYMARKET_PROP_RESOLVERS`
  — **staged '1' (user-authorized, lane polymarket-prop-resolver-arming) and
  INJECTED by the `bde67379` deploy live 19:06:37Z `[verified present pre-deploy
  by lane prop-unmatched-decomposition; the armed=True/venue_priced log read
  belongs to the arming lane]`** — see `todo #628`.
  **Prop no-match refusals are DECOMPOSABLE as of `bde67379` `[verified
  2026-09-01T19:18:45Z, lane prop-unmatched-decomposition]`:** each prop
  `unmatched_sample` names `player`/`token`/`fixture_tokens` (same
  fixture+family, near-tokens first, bounded 6)/`token_lines`, so one
  `POLYMARKET_UNMATCHED` read separates token-miss (`wilcon2`-class) vs
  rung-miss vs player-not-listed — **and COUNTED COMPLETELY as of `356d65b9`
  (`prop_classes=`, per-family sums == `no_match|mlb|*`, invariant held 532=532
  on first read) `[measured 2026-09-01 ~20:30Z on `839bfa06`, lane
  prop-rung-miss-rate]`: player_not_listed 65.2%, rung_miss 27.4%, near_token
  4.9%, fixture_miss 2.4% (532 rows, one cycle — quote a FRESH line, the
  population moves). Pitcher props are the inverse of the headline: 85.7%
  rung_miss (strikeouts 100%); batter props 71.8% player_not_listed — the venue
  lists ~6–10 batters/game vs our full-lineup board.** The earlier 3-sample
  read (2 of 3 rung-miss) had suggested rung-miss plurality; the complete count
  falsified it. Named follow-up in
  `findings_2026-09-01_prop_rung_miss_rate.md`: board names like `Max Muncy
  (2002)` derive token `max200` (parenthetical survives cleaning) — a
  derivation fix CHANGES MATCHING for deliberately-ambiguous names, own lane
  required.
  rung-miss vs player-not-listed. First read: 2 rung-miss (Soto hits 0.5 vs
  venue 1.5; Gasser K 4.5 vs {1.5,2.5,6.5}), 1 player-not-listed (Rocchio),
  0 token-miss; counts unchanged (224 ≈ 230 baseline — instrumentation only).
  **UPDATED 2026-09-01 19:18Z `[lane polymarket-prop-resolver-arming, USER
  DECISION]`: the resolvers are ARMED** (key set by the user, injected by
  dep-dabi38dcqm1c73dmhdjg live 19:06:37Z). Verified first cycle:
  `armed=True withheld=0`, polymarket `venue_priced` 62 → **462**/485. Props
  are now venue-priced and ticker-stamped, **but prop POSITIONS (and
  therefore prop orders) are still closed by the portfolio commit's own
  `market_family_excluded` policy (402/485 refused, positions unchanged at
  4/$14.71)** — pricing opened, position-taking did not; opening the family
  policy is a separate decision nobody has made.
- **Soccer competition bucketing FIXED, and it bought nothing yet.**
  `soccer_competition_tokens` now unions the flat alias test with the PAIR test
  (`soccer_fixture_clubs`), which `_teams_match` had already trusted since
  08-27. `soccer_tokens_proven=['arg2','bun','eflch','epl','lal','lg1',
  'ligpor','lng','lpa','mlp','mls','sea','swe2']`; ops reader soccer buckets
  **738 -> 1,809**. But `no_match|soccer|h2h` is **93 of 93 board rows** and
  totals **18 of 18** — still 100%. The 104 -> 93 drop was the BOARD SHRINKING
  (1326 -> 1308 rows), not the fix.
- **THE SOCCER BLOCKER IS FIXTURE PAIRING, AND THE REFUSAL NAME SAID SO BEFORE
  THE FIX SHIPPED.** Those rows were already `no_match` (candidates present,
  no fixture paired), never `no_candidates`. Bucketing was a real defect for
  MLS markets and was never the binding constraint for these rows.
- **ORIENTATION: SUPPORTED, NOT ESTABLISHED** `[measured 2026-08-28T17:40:42Z,
  73a7e358, board_rows=1313]`. `POLYMARKET_ORIENTATION`, read denominator-first:

      tried   = {soccer|h2h 106, soccer|totals 27, wnba|totals 6,
                 nfl|h2h 3, wnba|spreads 2, nfl|totals 2}
      flipped = {soccer|h2h 10, soccer|totals 2}

  Soccer flips at **12 of 133 = 9.0%**, a real rate on a real sample. **The
  claim that this is SPORT-SPECIFIC is not established** and must not be
  written as if it were.
- **THE CONTROL CANNOT DISCRIMINATE AT THIS n, and that is arithmetic, not
  caution.** `mlb` is absent from `tried` entirely — 0 of 0, 35 unmatched
  game-line rows and the flip attempted on NONE (spreads/totals only attempt at
  the board's own line). NFL was exercised at 0 of 5. At soccer's 9.02%,
  P(zero rescues in 5) = **0.623** — a zero is the MAJORITY outcome even if NFL
  behaved identically. All non-soccer pooled is 0 of 13, P(zero) = **0.293**.
  Verified independently here and by a second reader. **~30 non-soccer attempts
  would make a zero mean something** (P(>=1) = 0.941); NFL volume should climb
  with the season.
- **A SECOND, NESTED DENOMINATOR PROBLEM — the 9% is a LOWER BOUND, not a
  rate.** The 106 includes rows that could never flip-match for reasons
  unrelated to orientation (a club the alias map cannot resolve fails BOTH
  orientations). So 12/133 is "flipped, out of all unmatched", not "flipped,
  out of fixtures where a flip was even possible". The true inversion rate
  among RESOLVABLE fixtures is unknown and higher. Nobody has that denominator.
- **RESOLVED 2026-08-28, and the earlier downgrade was wrong: THE SOCCER SLUG IS
  HOME-FIRST.** Checked against ESPN scoreboards, independently in two sessions:
  `eng.1 Manchester City @ Crystal Palace` / slug `atc-epl-cry-mnc` (cry = HOME,
  listed first); `fra.1 PSG @ Lille` / `atc-lg1-lil-psg`; `esp.1 Villarreal @
  Alavés` / `atc-lal-ala-vil`. **Our board is CORRECT on all three.** MLB is
  away-first (`aec-mlb-lad-det` = Dodgers @ Tigers) and pairs today, so the slug
  order genuinely DIFFERS BY SPORT.
- **10 of 106 WAS THE WRONG DENOMINATOR AND IT IS WHY I DOWNGRADED IN ERROR.** A
  board row reaches `no_match` only if it did NOT pair normally. So:
  paired normally 0 · paired flipped 10 · never paired either way 96.
  **Among soccer h2h fixtures pairable at all: 10 of 10 inverted, 0 correct.**
  The 96 are a COVERAGE question — the fixture is absent from the slate, or its
  venue tri-code resolves in neither orientation — not a join defect.
- **`no_match` CONFLATES "listed but unpairable" WITH "NOT LISTED"**, because
  `no_candidates` fires only when the whole `(league, date, market)` bucket is
  empty, and for soccer it never is. That conflation is what made 96 look like
  join failures. Splitting it is the next instrument.
- Board-side resolvability MEASURED and exonerated: **all 106** board soccer h2h
  rows have BOTH clubs resolving via `canonical_team`. Zero fail there.
- **STILL DO NOT SHIP A BLANKET FLIP.** MLB pairs correctly away-first today; a
  global flip breaks it. Any fix is per-sport and needs the 96 split first.
- **THE SAMPLES SHOW THE MECHANISM, NOT THE RATE.** All 8 are soccer, across
  five competitions (Ligue 1, MLS, EFL Championship, La Liga, EPL) and both
  slug prefixes, every one board-`away@home` against the reversed slug pair.
  They are capped at 8 AND SELECTED ON THE OUTCOME — drawn only from rows that
  did flip-match — so the "prominent club is away in our data" pattern I read
  off them is conditioned on flipping and cannot support an inference about the
  other ~96. **DO NOT APPLY A FLIP.**
- `/api/ops/polymarket/slate` now passes the join's `soccer_tokens`, so reader
  and decider agree; and it emits `outcome_readability_by_reason_and_recency`
  — `outcomes_count_mismatch` is `past 216 / upcoming 193`, i.e. NOT the stale
  population a six-row sample suggested.
- **NCAAF is invisible to Polymarket for an unrelated token mismatch**: the
  venue files college football under `cfb`, the board says `ncaaf`.
  `no_candidates|ncaaf|totals` 41 of 41, `|h2h` 6 of 6.

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
`segment_for_series` + `segment` in both key tuples + `series` stamped at both
match-record sites (neither carried it). Unmapped defaults to `full` because the
protection is on the BOARD side; refusal is reserved for an unmapped series
carrying a segment MARKER (F5/INNING/1H). Refusing ALL unmapped — my first
version — would have unindexed the whole prop book. 9 tests, 127 passing.

**THE SERVICE IS refresh-worker, MEASURED NOT ASSUMED** `[2026-08-28T20:19Z]`:
`[portfolio_commit] KALSHI_BOARD_JOIN` appears on refresh-worker and NEVER on
live-odds-worker over the same 2h window. Execution stamps `ticker_resolver(row)`
verbatim from the plan, so the ticker is decided at commit time.

## [polymarket-fill-price-is-reported] THE VENUE REPORTS `avgPx`. "This path has no fill price" was FALSE and cost a 12h live halt `[verified 2026-08-30 18:41Z, live-odds-worker `fcadd126`, lane ncaaf-market-basis-picks]`

Three sessions diagnosed the 2026-08-30 execution halt as *"the venue gave no
price"*. **It gave one.** `venue_order_view` already read `avgPx`; TWO bugs in
the same function discarded it, and fixing either alone still left
`fill_price=None` — which is what forced `execution_ledger` onto its contract
bound, refused `13.13 > 10.8953`, and blocked BOTH venues.

Venue payload for `C65VD0R72KDG`, read by a one-shot probe (`a6eeaf17`):

    cumQuantity 13.13   leavesQuantity 0   ORDER_STATE_FILLED
    avgPx 0.2350        price(limit) 0.22
    side ORDER_SIDE_SELL   intent BUY_SHORT   outcomeSide OUTCOME_SIDE_NO
    commissionNotionalTotalCollected 0.1400

1. **The complement was applied on a side LABEL.** `outcomeSide=NO` turned
   `0.2350` into `0.7650`, absurd against a `0.22` limit — so the downstream
   guard correctly refused it. The guard worked; the complement was wrong. The
   reading is now chosen by which of `{avgPx, 1-avgPx}` the SUBMITTED LIMIT
   agrees with — semantics-free, because `order["price"]` is our own limit
   echoed back on the same scale. Reproduces 4/4 of the recorded fills.
2. **The limit check was DIRECTIONAL and read one way.** "A BUY cannot fill
   above its limit" is true; the unencoded inverse — a SELL cannot fill BELOW
   its limit — is equally true. This order is a SELL, so `0.2350 > 0.22` is
   price IMPROVEMENT and was refused as a violation.
3. **A value outside (0,1) is ABSENCE wearing a number.** `avgPx='0.0000'` on an
   unfilled order was treated as a price: on a BUY it survived as
   `recorded=0.0`, and `fill_stake_dollars` is derived as
   `contracts x fill_price`, so a real position would book at **$0**.

**verify:** `FILL_PRICE avgPx='0.2350' recorded=0.235`, `fill_cost=3.08555`
(= `13.13 x 0.235`, now OBSERVED not bounded); four orders across both side
conventions. **And the strongest reading — `FILL_ABOVE_LIMIT` fired 36 times in
one hour on orders with `filled=0.0` and now returns NOTHING.** That line means
"this price was impossible"; it had become noise and is trustworthy again.

**NOT PROVEN:** no BUY has reported `avgPx=0` and THEN filled since the deploy.
`FILL_PRICE_ZERO_WITH_FILL`/`FILL_PRICE_OUT_OF_RANGE` silence is equally what
"the condition never arose" looks like. **The halt's RECOVERY is not attributable
to this** — `9733a01a` + `77ca329a` cleared it; this fixes what is RECORDED.

## [live-odds-worker-deploy-gate] THE DEPLOY GATE IS UNREACHABLE ON live-odds-worker, and the documented override CANNOT WORK AS WRITTEN `[measured 2026-08-30 18:0x-18:35Z]`

`deploy_preflight --service live-odds-worker` returned **`HOLD` on ~76 samples
across ~30 minutes**, sampled as tightly as every 4s, and never once `CLEAR`.
Independently reproduces `live-venue-order-placement`'s 36-poll finding.

**Cause: `refresh_odds_sources.py` (pid 2580) is a PERSISTENT sweep** walking the
soccer league list (`epl -> mls -> eredivisie -> ...`) under a stable parent pid.
It briefly showed 2 jobs and went straight back to 3. The only window is the gap
between sweeps, and **a preflight sample itself takes ~10s** — so a shorter gap
is not observable at all. (A window DID open later at ~18:4xZ and another lane
took the claim, so this is "unreachable in practice", not "impossible".)

**`SYNDICATE_DEPLOY_GUARD=off` AS AN INLINE PREFIX DOES NOTHING.** The hook is a
separate process that reads its own environment BEFORE the command runs, so
prefixing the sanctioned deploy entrypoint is blocked exactly as if unset
(measured). Making it take means putting the var in Claude Code's own
environment — `.claude/settings.json` — which disables the guard **repo-wide, for
every session, permanently**. That is not a per-deploy override.

**The narrow form that works:** the same one-liner run in a HUMAN's own shell,
where hooks do not apply and nothing persists. Used for `fcadd126` at 18:37:12Z.

**A SECOND, UNRELATED HOOK BEHAVIOUR worth knowing:** the guard pattern-matches
the COMMAND STRING, so a `cat >>` writing ledger prose that merely NAMES the
deploy script is blocked as if it were a deploy. Write such prose from a file,
not from a heredoc.

## [polymarket-h2h-buys-the-wrong-side] POLYMARKET MONEYLINES BUY THE WRONG TEAM: `outcomes[0]` is not reliably the YES leg `[verified 2026-08-28, lanes portfolio-venue-and-side-integrity / venue-candidate-key-token-guard]`

`outcome_side_for_index` assumes `OUTCOME_SIDE_YES` buys `outcomes[0]`. It does
not. Measured against ground truth: polymarket h2h **5 agree, 3 MISMATCH**;
polymarket totals 9/0; kalshi totals 4/0. Totals are immune BECAUSE they resolve by
NAME (`over` -> YES); h2h has no name to fall back on, so the index is a positional
guess.

`aec-mlb-az-sf-2026-08-27`: our `side=home` (San Francisco), submitted
`OUTCOME_SIDE_YES outcome_index=0 outcome='San Francisco Giants'` at 0.48. StatsAPI
`Arizona 1 @ San Francisco 6`, Final, `home_win=True`. The venue graded it **lost**,
pnl **-5.871** (our exact cost basis), `held_side=POSITION_RESOLUTION_SIDE_SHORT`.
**We bet the winner and were paid a loss.**

Cleanest evidence, needing no team-name reasoning: four sibling futures in ONE
catalogue response, outcomes literally the strings "Yes"/"No", and
`tec-mlb-nlchamp-2026-09-27-atl` lists them **NO-first** while its three siblings
are YES-first.

**TWO DIFFERENT MAPPINGS — do not conflate them.** `outcomes[i] <-> outcomePrices[i]`
(alignment) is PROVEN correct. `OUTCOME_SIDE_YES <-> outcomes[0]` (the binding) is
the false one. An alignment proof says nothing about the binding.

`home`/`away` on Polymarket now REFUSES by name rather than guessing, and that
refusal is **LIVE on live-odds-worker since 2026-08-28T15:06:23Z** (escape hatch
`SYNDICATE_POLYMARKET_ALLOW_TEAM_SIDE=1`). It has **never fired in production** —
nothing tried to place an h2h in the observed window — so its reachability rests
on tests (`off != on`: 4 fail against it, pass with the hatch, asserted through
`order_body`) and on `verify_order_paths`, not on a production line.

**THE VENUE NAMES ITS OWN YES LEG, AND IT IS NOW MEASURED RATHER THAN INFERRED**
`[2026-08-28T20:08:15Z, live-odds-worker 54da64e1, post-go-live 20:05:22Z]`.
`marketSides[].long` + `.description`/`.team.name`, read on three NFL moneylines
(`bettable=True`): `long_index` = **0, 0, 1** — `was-bal` Commanders,
`atl-mia` Falcons, `hou-car` **Texans = outcomes[1]**. **So the YES leg is NOT
`outcomes[0]`**, confirmed on the venue's own field and corroborating the 3-of-8
wrong-team rate independently. `hou-car` repeats the `az-sf` signature exactly:
outcomes reversed against the slug, long side second.

WEAKER, FLAGGED NOT ASSERTED: on `hou-car` the long side's price (`0.5100`)
matches `outcomePrices[0]` while the long side is `outcomes[1]`, which would mean
the misalignment reaches the PRICE too. It rests on a ONE-CENT separation
(0.51 vs 0.50) — the thin-margin trap this file's own learnings record — and
needs a market where the long side is `outcomes[1]` AND the prices are far apart.
It also scratches `venue-join-refusal-visibility`'s alignment proof, which was
run on totals; flagged to them.

STILL **NOT WIRED**: `todo.md #595` step 3 requires scoring the rule against all
8 venue-settled moneylines INCLUDING the 3 that went wrong before the refusal
comes off.

**THE CLASS IS NOW CAUGHT BY A MACHINE.** `paper_settlement._check_venue_grade`
cross-examines every VENUE-stated outcome against the real game result — the two
authorities are independent because ours applies the order's own `side` while the
venue's reads the realized P&L delta on the position it says we held, so a
disagreement is the signature of a wrong-side fill. Live on refresh-worker;
`/api/portfolio/live` serves `grade_conflicts: 3` / `$10.07`, 62 rows carrying
`grade_check` (58 True / 3 False / 1 None). It hit a PRE-REGISTERED prediction —
the three tickers were named before the reading. It never rewrites `outcome` or
`pnl_dollars`. `learnings.md` had recorded this class as "caught twice by a human
looking at a screen and zero times by a machine"; that is no longer true.

## [venue-candidate-key-ambiguity] BOARD JOIN KEYS: a bare token could name another fixture's team, and the guard's own counter cannot see it fire `[verified PARTIAL 2026-08-28T02:36Z, lane venue-candidate-key-token-guard]`

`_candidate_keys` built city/nickname keys from a board team, bounded only by
subtracting the OPPONENT's words — correct about the ROW and the wrong SCOPE for the
lookup, since `apply_venue_quotes` resolves against the sport's WHOLE quote pool.
Measured over the alias maps: **soccer 21 ambiguous tokens** (`city` names 14 clubs,
`real` 4), **mlb 7**, **nfl 5**, **nba 3**; and `_alias_map` is `{}` for nhl/ncaaf/
ncaab, so those rows had NO guard at all ("Ohio State Buckeyes" offered
`ncaaf|h2h|state`). An unresolvable board team also fell through to raw words
("Not A Real Club" -> `mlb|h2h|club`, `|not`, `|real`).

`unambiguous_club_tokens` now keeps only tokens naming exactly one club, and
`team_name_tokens` resolves through `canonical_team` with no raw fallback.

**PARTIAL, and the limit is the instrument.** Production read (`32b0cfaa`, 02:36Z):
soccer inputs byte-identical across the boundary and output identical — unmatched
rate **30.72% -> 30.72%**, kalshi `wanted_overlap` **83 -> 83**. That shows NO HARM.
It does NOT show the guard fired: `wanted_overlap` counts `offered ∩ wanted`, this
change shrinks *wanted*, and kalshi's soccer keys are full club names the guard
preserves — so the counter reads 83 either way. The nhl/ncaaf/ncaab **wrong**-match
half is a different question and no counter here answers it.

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

## [odds-cadence] ODDS CADENCE AND CAPTURE

- **MLB quote capture has THREE regimes, not one beat. `[measured 08-15 02:5xZ,
  supersedes the single-cadence reading of 08-14 16:3xZ]`** All 371,567 rows of
  `mlb_source/tracking/book_quotes/2026-08-14.jsonl`, streamed from web and
  bucketed by distinct `captured_at`:
  | window (UTC) | slate | gap |
  |---|---|---|
  | 07:03→15:10 | pregame, nothing live | **121 / 121 / 123 / 121 min** |
  | 16:20→18:25 | first games start | 70 / 61 / 64 min |
  | 18:36→20:54 | ramping | 11–12 min |
  | 21:48→02:53 | full live slate | **~1 min, continuous** |
  **121.6 is exact and it is the EMPTY-SLATE PREGAME number only.** The same
  pipeline samples 122× faster once games are live. Never quote it unqualified.
- **SUPERSEDED IN PART — there is a THIRD regime, and it dominates.
  `[measured 08-15 16:38-17:00Z, deploy-free window, 22 samples]`**
  On 08-15 the pregame beat was **~60 min, not 121.6**, and then MLB capture
  starved for **5.8 h**. Cause is neither the tick nor the cooldown: a chain of
  back-to-back refresh **run-locks** (`ops_refresh.py:669`, per-lane, NOT the
  separate `JOB_CAP_THROTTLED` job cap -- an earlier version of this line
  conflated them; raising the job cap would not have helped), each
  held ~25 min with ~2 min free — **~92% occupancy, traced 11:39→17:00Z**.
  17 consecutive ticks refused by `pid=4047`; the ONE tick that got through at
  16:56:26 took end-to-end from **20,880 s to 32 s**, then `pid=5681` retook it.
  **End-to-end is BIMODAL: ~32 s or hours, never in between.** In the starved
  regime the number rises exactly 1 s/s — it is a clock, not a latency.
  **`PREGAME_RELAUNCH_COOLDOWN_SKIPPED` fired ONCE in 5.75 h** (counted on
  live-odds-worker, the correct emitter, with a liveness control), so **Tier 0's
  `0.1` would NOT have prevented this** and is not the Tier 5 prerequisite the
  program plan calls it. Full working:
  `.syndicate/tier5_quote_to_ui_WINDOW2_2026-08-15.md`.
- **WHY 60s BECOMES ~7,300s, two multipliers, both measured `[08-14 17:0xZ]`:**
  1. `SYNDICATE_LIVE_ODDS_REFRESH_INTERVAL_SECONDS=60` is the TICK interval,
     never the launch interval.
  2. **The pregame relaunch cooldown is 1800s and GLOBAL** —
     `_pregame_relaunch_blocked` reads ONE marker keyed by **date only, not by
     sport and not by service**, so a launch for ANY sport starts the clock for
     EVERY sport. 30×.
  3. **Sports rotate across launches**, so MLB rides roughly 1 in 4. ~4×.
  **The leverage is a design fact, not a tuning value: because the cooldown is
  global, every sport added dilutes every other sport's cadence.** A per-sport
  cooldown decouples them; that is the change worth considering, not lowering 1800.
  4. **BUT THE COOLDOWN IS GATED ON PREGAME PHASE AND IS BYPASSED WHENEVER ANY
     GAME IS LIVE. `[measured 08-15 02:5xZ]`** On the deployed tree:
     `effective_phase = ("live" if any_live else "pregame")`, then
     `if ... effective_phase == "pregame" and _pregame_relaunch_blocked(...)`.
     `latest_tick` carried `adaptive:true, anyLive:true, phase:"live"`. So both
     multipliers above apply **only to the empty-slate pregame regime**.
- **The per-sport cooldown fix (`ea8fad58`) is NOT deployed on ANY service.
  `[measured 08-15 02:4xZ]`** Checked by reading the deployed trees, not
  ancestry: `git show <sha>:syndicate/features/shared/live_refresh_loop.py`
  gives `def _pregame_relaunch_blocked(*, now_epoch, date_str)` — no `sports`
  kwarg — on both `548ded38` (refresh-worker) and `ccd10349` (live-odds-worker).
  **`ea8fad58` IS an ancestor of `origin/main`, so an ancestry-only check says
  "shipped" and is wrong.** `autoDeploy` is off; being on `main` ships nothing.
- **WHICH SERVICE DRIVES CAPTURE IS AN OPEN DISCREPANCY — re-check the env
  before relying on either answer. `[measured 08-15 02:5xZ]`** The env API now
  reads the OPPOSITE of this file's 08-14 line: live-odds-worker
  `SYNDICATE_ENABLE_LIVE_ODDS_REFRESH_LOOP=true` and
  `SYNDICATE_MLB_REFRESH_TICK_OWNER=true`; refresh-worker `false` on both; and
  the 02:35:20Z tick wrote `refresh_status_latest__live-odds-worker.json`.
  **But** `ODDS_SWEEP_OUTCOME` since 02:00Z is refresh-worker **16**,
  live-odds-worker **0**, which matches the old line. The emitter
  (`live_refresh_loop.py:4100/4117`) is reachable from the board-build sweep as
  well as the loop tick, so both emitting is not itself a contradiction.
  Unresolved; resolving it needs the board-build loop. Loop ownership is an env
  flag that moves with no diff — that rule is why this line is now a question.
- **This is the real cause of "candidates that are no longer bettable"** — the
  board's MLB prices are up to ~2 hours old by construction.
- **Consequence for the whole movement family — REAL CONSTRAINT IS THE BUFFER
  DEPTH, NOT THE FETCH RATE. `[measured 08-15 02:4xZ, supersedes "sampled
  roughly every two hours"]`** From
  `/api/ops/odds-history/inspect?sport=mlb&date=2026-08-14`, 3,582 markets:
  sampling interval within the retained history is **p50 1.0 min** (live 0.9,
  pregame 1.0) — not 2 hours. But `history_points` is **capped at 20**
  (`_ODDS_HISTORY_LIMIT`, `shared/odds_refresh_tracking.py:40`, env-tunable via
  `SYNDICATE_ODDS_HISTORY_LIMIT` which is **unset on all three services**), and
  3,130 of 3,582 markets sit exactly at the cap. Retained span is therefore
  **p50 17.8 min**. The code's own comment concedes it is *"narrower than the
  steam detector's stated 45-min window for hot markets."*
  **So a movement calculation sees ~18 minutes and is structurally blind to
  whether the previous sweep was 1 minute or 2 hours earlier — the
  pregame→live transition, the biggest move of the day, falls out of the buffer
  within 20 minutes of first pitch.** Re-examine `movement_velocity` and the
  steam detector against `_ODDS_HISTORY_LIMIT`, not against fetch cadence.
  Raising it trades against the 8 MB keyvalue ceiling that forced it to 20.
- **A `too_large` line does NOT mean the artifact failed to publish.** The
  ceiling lives in `_publish_skip_reason`, which is **sweep-only**; the direct
  path streams and never consults it. Verified byte-identical on web. Four
  sessions have now misread this. `[measured 08-14 16:2xZ]`

### OddsAPI budget `[measured 08-14 17:2xZ]`

- **Projected 30-day burn 4,640,809 credits = 92.8% of the 5M cap.** Headroom
  ~360k/month. MLB is **93.7%** of spend (8.72 cr/call); soccer 4.2% (1.46
  cr/call, 6× cheaper); nfl 1.4%; wnba 0.7%. Live hours dominate (83–228k/hr)
  against pregame's 10–18k/hr.
- MLB pregame sweep interval is 3600s with an effective gap of **~1h10m**
  (7,289s → 4,215s). The loop wakes every 900s and sweeps whatever is past its
  interval, so the setting is a FLOOR the tick quantises.
- **Any cadence increase spends against the cap — it is a product decision, not
  a tuning tweak.**

---

## [venue-odds-storage] `venue_odds` LIVES ON DISK, NOT IN THE SHARED KEYVALUE `[measured + deployed 2026-09-02, lane venue-odds-byte-aware-trim]`

`reports/intelligence/venue_odds/` held **41 keys / 114.9 MB of a 224.3 MB
store** — 51% of a 256 MB Redis at 93% with 11,852 keys evicted — and the reader
trace found **nothing reads it**: the only read is `record_daily_odds`'s own
read-modify-write, and both external importers take write paths only. It is a
deliberate capture-first archive whose consumer was never built.

Two changes, both live on BOTH workers and measured:

- **`#638` byte-aware trim** (`21de4a9e`). The count caps could never bind:
  `MAX_POINTS_PER_MARKET=48` / `MAX_MARKETS_PER_FILE=8000` bound COUNTS while the
  guard bounds BYTES. **3,192 refused writes in 40h** (live-odds-worker 2,203,
  refresh-worker 989; web none — it does not run this writer). Trim is REACTIVE:
  it catches `KeyValuePayloadTooLarge` and retries at 90% of the ceiling, so it
  costs nothing on the happy path and is inert on a disk backend.
  **The criterion is a PAIR, not zero rejections** — one rejection per file per
  growth cycle is BY DESIGN; the failure is a rejection with no `TRIMMED_TO_FIT`
  after it.
- **`#637` moved off keyvalue** (`e4a471c0`). `_KEYVALUE_EXCLUDED_PATH_MARKERS`
  gains `/intelligence/venue_odds/`. **50 and 37 files hydrated, distinct ==
  total on both workers.** Disk is PER-SERVICE where Redis was shared — not a
  regression, since two services doing RMW on one key already lost each other's
  updates. `reports_root()` is `/opt/render/project/data/reports`, the MOUNTED
  disk (read off live env), so these survive a deploy.

**MEMORY NOT RECLAIMED, DELIBERATELY.** ~115 MB stays until the 10-day TTL.
Hydration reads the old key on a service's FIRST write of a file, and
refresh-worker has not yet written polymarket — expiring now would make those
start empty, and an accumulator that starts empty **re-dates every `opened_at`
to the expiry moment**. Wrong data, permanently. Gate before any expiry:
`scripts/check_venue_odds_hydration_census.py` (exits 0 only when every censused
key is SAFE and nothing was truncated; first run **27 SAFE / 15 PENDING**).

**NOT OWED — VOID. `#637` MADE `#638`'s TRIM UNREACHABLE, and "wait for it to
fire" was wrong `[corrected 2026-09-03]`.** The trim triggers by catching
`KeyValuePayloadTooLarge`, which ONLY the keyvalue backend raises. `#637` moved
`venue_odds` to disk, and disk has no 8 MB ceiling — so the write cannot be
refused, so the trim cannot be reached. Measured since the disk move
(2026-09-02T19:26:44Z): **zero `TRIMMED_TO_FIT` and zero
`KEYVALUE_WRITE_REJECTED` for `venue_odds` on BOTH workers**, including
live-odds-worker, which had trimmed twice before the move. That is the ceiling
being gone, not a stalled writer.

**UNREACHABLE IS NOT UNVERIFIED, and the two look identical in a log.** An
unverified fix might still be broken; an unreachable one cannot run at all.
Carrying this as "owed" would send a future session hunting a signal that can
never appear.

**The mechanism IS proven** — live-odds-worker emitted two `TRIMMED_TO_FIT`
lines on 2026-09-02 with `markets_dropped=0` and a `status=ok` book. `#638`
remains correct, unit-tested both directions, and is now DORMANT: the safety net
if `venue_odds` ever returns to keyvalue.

## [sharp-reference-price] SHARP REFERENCE PRICE — WE HAVE ONE. The audit's caveat is STALE.

**The models audit's "no Pinnacle, Circa or exchange in the feed" was true when
measured and is FALSE now.** The feed widened between 08-05 and 08-09 and nobody
re-read it. `[measured 08-15 from data/mlb_source/tracking/book_quotes/]`

| dates | distinct books | pinnacle rows | shard size |
|---|---|---|---|
| 07-28 .. 08-05 | **11** | **0** | ~13 MB/day |
| 08-09 | **37** | **2,604** | **217 MB/day** |

- **Sharp coverage on MLB GAME LINES is 102 of 102 markets = 100%** on 08-09.
  Sharp set present: `pinnacle`, `betfair_ex_eu`, `matchbook`, `novig`,
  `prophetx` (plus `kalshi` / `polymarket` as prediction markets).
- **Sharp coverage on PROPS is 0%.** Prop CLV therefore stays a soft-consensus
  measurement and **must be labelled as such**; game-line CLV can be taken
  against a genuine sharp close.
- **THERE IS ALREADY A PER-SPORT LEVER FOR THE PROP GAP, and NHL uses it.**
  `syndicate/local_nhl_odds.py:542` defaults
  `PROPS_ODDSAPI_BOOKMAKERS = "fanduel,draftkings,pinnacle"` — Pinnacle is
  explicitly requested for NHL props. `vendor/nhl_betting_repo/.../odds_api.py`
  carries it in a book list too. So closing the 0% on other sports' props is a
  **config change on an existing knob**, not a build. `[from-code 08-15]`
  **Cost it before flipping it:** every added book spends OddsAPI credits
  against the 5M cap — **STALE→UPDATED 2026-09-01: 4,959,329 of 5,000,000
  remaining (99.2% unused) per `odds_regions.py:63-66` after the #15/#16 cuts;
  quota is no longer the binding constraint** — and props are the highest-
  volume market family. Measure the per-call delta on one sport first.
- **This removes the standing caveat on the whole CLV program** — "beating a
  closing consensus of eleven soft books can read positive where no exploitable
  edge exists" no longer applies to game lines.
- **The widening is almost certainly the lost-books capture fix**, which also
  explains the 13 MB → 217 MB/day jump. That cost is real and it is what the
  storage-format work (delta/columnar) exists to absorb — **do not "fix" it by
  narrowing the book set again; price shopping was measured at +2.79 ROI pts.**
- **Caveats, stated:** read from the git-tracked mirror, which is lossy, and
  only ONE post-widening date exists locally (08-09). **Confirm against
  production before publishing a sharp-referenced CLV number**, and re-read
  whether the 37-book set is still current.

---

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

## [board-quote-staleness] Board freshness vs QUOTE staleness — verified 2026-08-26 (lane `board-staleness-visibility`)

**THE BOARD BUILD IS ~108s IN STEADY STATE.** n=40 unattended builds, median
107.8s, p90 145.5s. **A COLD build (first after restart) is 747.8s — 6.9x — but that is a FLOOR, not a bound: measured again 2026-08-27, boot `00:56:13Z` to first `GAME_CHIPS_PUBLISHED` `01:14:32Z` = **18m19s**, half again the recorded figure, on a 15-game slate. Slow rather than stuck — stages walked forward (`cards_context_end` 01:01, `board_contract_end` 01:07) and memory was flat at ~1.79GB anon. Do not size a wait against 747.8s.**
Every figure in older entries (19m43s, 12m44s, 11m22s) is a COLD build
generalised; they were measured in a window with 15 deploys in 6h15m where the
worker never reached a warm build. **Quote a board-build duration only with
cold/warm attached.**

**Cold-build decomposition:** `build_intelligence_overview` 295.1s,
`candidate_collection_with_fallback` 178.0s, `candidate_building` 0.01s,
`manifest_odds_history_join` 0.32s. **All eight sports' candidate generation is
47s — 6% of the build.** Optimising generation optimises nothing.

**Per-sport odds-history load is CHEAP:** total 0.2s across 5 sports, mlb 0.19s,
**soccer 0.01s**. Do not size work against an assumption that shard reads are
expensive.

**THE BOARD SERVES STALE QUOTES, and publication freshness cannot see it.**
`seen_p50=859s` against a ~60s publish cadence. Every publication-time
instrument (`written_at`, `state_meta`, the stale badge) reads FRESH on a board
carrying 14-minute-old quotes. Use `QUOTE_AGE_SERVED`.

**`last_seen` MUST be read across the same dates as `quote_rows`.** Fixed
2026-08-26: `quote_rows` extends across `window_dates` while `last_seen` read
`selected_date` alone, leaving rows clockless — and **a clockless row is
invisible to `drop_superseded_lines`**, which requires a clock on both sides by
design. Measured before the fix: `no_seen_age=7553` against `kept=15672`, 48% of
a grid exempt from the guard. After: `no_seen_age` max 52, drops 16 -> 824/2271,
artifact 962141 -> 962176 bytes.

**NFL's sweep cadence is FIXTURE-AWARE AND CORRECT, not an outage.**
`FIXTURE_CADENCE sport=nfl interval=28800 reason=mid:26h_out` — 8 hours by
design (`#440` Phase 1b, which predicted nfl_preseason 12.00 -> 3.56 sweeps/day).
ncaaf 86400s, wnba 7200s. **Judge a sport's sidecar against its OWN interval or
against its rows' ages — never a flat threshold.**

**`_pregame_sweep_interval_for_tick` DISAGREES ACROSS SERVICES.** It is
fixture-aware; the decision is made on **live-odds-worker**. Recomputing it on
refresh-worker returns 7200 for nfl against production's 28800, because the
fixture lookup finds nothing there.

**NO MEMORY PROBLEM EXISTS ON refresh-worker.** Peak unreclaimable 29.1% of
4096MB, zero oomKilled over two days. `container_memory_pct_of_max` counts page
cache; `ALL_PROCESS_MEMORY` now carries `container_memory_unreclaimable_*`
beside it. **Quote the unreclaimable figure.**

## [exchange-refresh-cadence] — VERIFIED 2026-08-27, live-odds-worker `34b4d4b4`

- **Kalshi's 120s refresh interval is unreachable.** `run_kalshi_odds_refresh()`
  is called from ONE site — inside the board build — whose period is 3.4-13 min.
  The board loop sets the venue refresh rate, not the venue config.
- **CORRECTED 2026-08-27 18:5xZ — my earlier line here ("`MAX_STORED_MARKETS =
  6000` drops ~42% of the catalogue") WAS WRONG and is replaced.** The cap is
  deliberate and safe: the keyvalue store hard-refuses at 8MB, an unbounded
  version reached 13.3MB and STOPPED WRITING THE ARTIFACT AT ALL, and
  `venue_daily_odds` keeps the complete record. 6000 is a bounded WORKING SET
  the join prices against, not the record. Nothing is lost by the bound.
- **ALLOCATION IS CONFIRMED AS THE BINDING CONSTRAINT, AND TODAY'S RECOVERY WAS
  NOT THE FIX FOR IT `[2026-08-27 ~21:0xZ, corrected]`.**
  `[kalshi_odds] BOARD_JOIN matched` went from 5-24 back to **208 / 218 / 221**
  against a complete-set 235 / 242 — the 6,000 working set now captures ~91% of
  what the full ~10,560-market catalogue matches, up from ~6%. `matched` tracks
  MLB's slot count almost exactly (`mlb_slots` 794 -> matched 27; 1620 -> 208;
  1741 -> 218; 1706 -> 221), which is what establishes allocation as the
  mechanism.
  **I FIRST ATTRIBUTED THIS TO `venue-quote-line-join`'s DEMAND-WEIGHTED TRIM
  (`bd81ba3c`). THAT WAS WRONG AND THEY CORRECTED IT.** The trim's own log line
  at the moment of recovery reads `TRIM_BY_SPORT ... demand=None mlb_slots=1620`
  — `_sport_slot_caps` returns None with no demand signal and the trim falls
  back to the FLAT-FLOOR branch. So the demand code was DEPLOYED AND NOT
  EXECUTED. I checked ancestry (deploy state) and inferred causation
  (predicate); the emitted field disproves it. Standing rule "test the fix's
  predicate, not its deploy state" — I had it available and did not apply it.
  **WHAT ACTUALLY RECOVERED IT: MLB's slate approaching first pitch.** Its
  markets churn, become the freshest in the catalogue, and the staleness-ordered
  remainder pass hands them the slots. Staleness ACCIDENTALLY doing what demand
  weighting does deliberately.
  **SO THE COLLAPSE IS EXPECTED TO RECUR TOMORROW MORNING** — corrected from
  "afternoon", which was wrong. In CENTRAL time today's collapse ran roughly
  09:00-14:00 CT (matched 5-27, spiking 146/210/99) and the recovery landed at
  14:49 CT (208 -> 218 -> 221). The bad window is the MORNING.
  **AND OBSERVING THE RECURRENCE IS NOT A PRECONDITION FOR ANYTHING.** I framed
  it as one. It would only confirm a prediction; the mechanism is understood
  (`matched` tracks mlb slot count) and `f4beb1bc` is landed. Turning "I could
  measure this" into "this must be measured first" is not a reason to carry a
  known-fixed defect through the window. Demand weighting is what stops the
  RECURRENCE; it is not what fixed today. Their `f4beb1bc` (per-sport MAX over a
  6h/12-sample window) additionally fixes `_record_board_demand` overwriting on
  every join — the alternating 442/842-row future-date builds were dropping mlb
  from the vector entirely, last-write-wins reading "not mentioned" as "no
  demand". Landed, undeployed as of this writing.
  HISTORICAL RECORD OF THE DEFECT FOLLOWS:
- ~~THE REAL DEFECT IS THE ALLOCATION, AND IT IS LIVE~~: the BOARD's Kalshi join
  lost ~93% of its matches today.** Same ticks, refresh-worker:
  `[kalshi_odds] BOARD_JOIN set=6000 rows=1329 matched=210` at 16:01:42Z, then
  `matched=5` from 16:13:19Z and 13-24 since — while
  `[portfolio_commit] KALSHI_BOARD_JOIN markets=10650 rows=1335 matched=210..217`
  on those same ticks. A SELECTION problem, not a catalogue one.
  CAUSE: `_trim_to_storage_bounds` orders by series staleness with a flat
  `PER_SPORT_FLOOR_MARKETS = 300` and has NO notion of which sports have games
  on the date being built. NCAAF opening week floods the set —
  `TRIM_BY_SPORT kept_by_sport={'mlb': 648, 'nba': 6, 'ncaaf': 1896,
  'nfl': 2083, 'soccer': 1067, 'wnba': 300}` (MLB hit the bare 300 floor at
  18:45Z) — against board demand of mlb 400 / soccer 400 / wnba 400 rows vs
  nfl 88 / ncaaf 42. ~4,000 of 6,000 slots serve 130 rows.
  **SCOPE, CHECKED NOT ASSUMED: EXECUTION IS UNAFFECTED.** `portfolio_commit`
  reads the STORED artifact via `markets_from_state` (~10,650) and still
  matches 210-217, so orders price off Kalshi's real book. The degradation is
  `join_to_board`'s board ANNOTATION — display and edge detection, not order
  placement. Not a money-at-risk incident.
  The 300/sport floor shipped the same day and DID fix soccer starving to zero;
  this is the adjacent failure a flat floor cannot see. Owned by lane
  `venue-quote-line-join` (claims `pipeline/kalshi_odds_refresh.py`), messaged
  with these measurements 18:5xZ. NOT edited by me — cross-lane file.
- **`run_polymarket_odds_refresh` is boot-only and yields nothing.** Wired only
  into `_polymarket_catalogue_at_boot`, so its 300s interval never applies. All
  10 boots in 17h: `count=100 sporting=0 truncated=False` — one page, zero
  sporting, and it believes the catalogue complete. `portfolio_commit`'s own
  Polymarket path sees `markets=17299 indexed=9106`.
- **Execution fires ~16 min, places almost nothing**: 9 cycles 13:49-15:52Z ->
  4 orders (Kalshi 3, Polymarket 1); otherwise `placed=0 duplicates=3-9`.
- **The live caps come from the SAVED STORE, not the env vars — BY DESIGN, and
  the current numbers are DELIBERATE `[USER CONFIRMED 2026-08-27]`.** Env
  `SYNDICATE_EXECUTION_MAX_DAY_DOLLARS_KALSHI=50` while `LIMITS` logs
  `max_day_dollars: 75.01`, because `_stored_live_limit` reads the `/portfolio`
  form store and that store WINS. `/api/portfolio/limits` reports every field as
  `source: stored`, `store_error: null`, `updated_at 2026-08-27T08:56:10-05:00`.
  In force: order $10.01 · kalshi $75.01/25 orders · polymarket $100.01/50 ·
  all-venues $200.01/75. The order caps exceed the `[USER DECISION 2026-08-25]`
  code defaults (15/15/25); **the user set them personally and they are
  intended.**
  **DO NOT "fix" this by reverting the caps to the env values — that would
  LOWER live money limits the user chose.** The env vars are fallback-only and
  are what is actually stale. Comparisons are strict `>`
  (`used + stake > cap`), so the trailing `.01` is not needed to admit an
  exactly-at-cap order; it only absorbs sub-cent overage such as Kalshi taker
  fees.
  STILL OPEN, not a defect: `update_limits` records only field values plus
  `updated_at` — no actor and no prior value — and `POST /api/portfolio/limits`
  is reachable by any agent session. No audit trail on a money surface.
- **Staleness dominates cadence.** `QUOTE_AGE_SERVED seen_p50=4285s` (71 min),
  p90 7776s, max 37837s; Polymarket join `slate_age_s=579.5`. A faster board
  loop cannot make a 71-minute-old quote fresh.

None of the above is fixed. No lane holds them.

## [polymarket-vs-kalshi-prop-prices] — MEASURED 2026-09-01, MLB, production shard

**First cross-venue PROP price comparison the platform has ever been able to
make** (exchange prop prices were in `book_quotes` nowhere before today). Full
method + bounds: `.syndicate/findings_2026-09-01_polymarket_vs_kalshi_prop_prices.md`.

- **Both venues quote ASKS, not mids** — settled from the data by summing both
  sides of one bet at one venue (kalshi median **101.04%**, polymarket
  **101.93%**, ~0-1% below 100). Without this gate the whole comparison would
  have been an ask-vs-mid artifact.
- **The two books agree to about one 1c tick.** 390 bets quoted by both (61.7%
  of polymarket's 632, 48.2% of kalshi's 809): median difference **+0.00pp**,
  median |diff| **0.95pp**, p10/p90 -1.09/+1.13.
- **Staleness control PASSED:** median capture gap 111.8 min, but the
  within-10-minute subset (n=93) returns the same answer (median +0.00, |diff|
  0.90pp) — the agreement is real, not an artifact of comparing across time.
- **KALSHI IS THE TIGHTER BOOK: median spread 1.04pp vs polymarket 1.93pp**
  (~1.9x, and a much fatter tail: p90 2.07% vs 4.93%). That is where "better
  price: kalshi 37% / polymarket 26% / tie 37%" comes from.
- **POLYMARKET WINS ON PITCHER VOLUME MARKETS, and that is the only
  price-shopping signal here:** `earned_runs` 73% cheaper (median -1.13pp),
  `hits_allowed` 58% (-1.13pp). Kalshi wins `batter_total_bases` (15% poly),
  `outs` (12%), `strikeouts` (21%).
- **CROSS-VENUE ARBITRAGE: EFFECTIVELY NONE.** 502 two-sided cross-venue pairs,
  median 101.92%; **6 distinct** below 100% (1.2%), only **2 surviving a
  10-minute same-instant bound**, both ~99%. The other 4 have legs 49-119 min
  apart — stale legs, not mispricings. ~1pp gross is erased by any plausible
  fee, and **Polymarket's fee remains an OPEN question** (the "measured zero"
  was retracted as an instrument artifact; `DEFAULT_FEE_BUFFER = 0.04` is a
  placeholder). **DO NOT build an arb strategy on this.**
- **A doubled count was caught and is recorded:** the first pass reported 12
  sub-100% pairs; each was counted twice (both leg orderings). 6 is the number.
- **SOCCER: NO COMPARISON EXISTS, and it is not a reader problem.** ZERO
  exchange rows of ANY kind (kalshi or polymarket, prop or game) in **92,795
  soccer quote rows across SIX fixture dates** (08-31..09-05) — soccer shards by
  FIXTURE date, so one date would be the wrong window. Instrument calibrated:
  the same reader found 2,870 MLB exchange prop rows the same day. **TWO
  INDEPENDENT CAUSES, each sufficient:** (1) Kalshi soccer never reaches the
  join — `[kalshi_odds] QUOTE_CAPTURE ... sports=['mlb']`, upstream the known
  `unreadable_title` PARSER gap on ~665 real Kalshi soccer markets; (2)
  Polymarket soccer DOES match (~25 rows/cycle: `soccer|h2h` 4, `soccer|totals`
  21) but every one is GAME/TEAM level with an empty `player_name`, and the
  capture is props-only by its correctness bound — all 25 discarded per cycle.
- **THE PROPS-ONLY BOUND'S PREMISE IS EMPIRICALLY FALSE FOR SOCCER**, and this is
  the actionable half. The bound exists because OddsAPI already writes exchange
  GAME lines under the same dedup key (measured on MLB: 2,350 polymarket game
  rows 08-31). In soccer OddsAPI carries **no exchange rows at all**, so there is
  nothing to collide with. **NOT changed** — the guard also hedges against
  OddsAPI starting to carry them, and its stated release condition (`source` in
  `_KEY_FIELDS`, pinned by `tests/test_direct_feed_provenance.py`) is unmet.
- **CORRECTION, read from production:** `_capture_kalshi_quotes` runs on
  **refresh-worker**, not live-odds-worker (zero hits there). The docstring in
  `portfolio_commit._capture_polymarket_quotes` still says otherwise.
- **INSTRUMENT AMBIGUITY worth carrying:** `POLYMARKET_QUOTE_CAPTURE ...
  sports=['mlb','soccer']` lists sports with MATCHES, not sports with APPENDED
  ROWS. Soccer is in that field every cycle and contributes exactly zero quotes.
- **NOT ESTABLISHED:** anything about MODEL edge. This is venue-vs-venue price
  quality on one sport, one slate. Spread figures rest on the two-sided subset
  only (coverage is heavily one-sided at both venues).

## [polymarket-low-activity] — VERIFIED 2026-08-27, refresh-worker + live-odds-worker

**WHY POLYMARKET PLACES ALMOST NOTHING. Three stacked structural facts, NOT a
broken join.** Day totals $23.25 / 8 orders against a $100.01 / 50 cap — caps
are nowhere near binding.

Full refusals, `POLYMARKET_BOARD_JOIN`, 1,344-row board, matched=52:

```
market_type_not_a_game_line          6960   venue's non-sports catalogue, correct
segment_market_not_full_game         1240   halves/quarters, correct
board_market_not_a_game_line          935   OUR PROPS -- venue does not list them
no_matching_polymarket_market         298   league listed, our GAME not listed
outcomes_count_mismatch               296
no_polymarket_market_for_league_date   42   NCAAF absent entirely
side_not_an_outcome_of_this_market     17
```

1. **THE BOARD IS ~76% PLAYER PROPS AND POLYMARKET LISTS NONE.** Sampled live
   MLB board, 300 rows: `batter_hits` 103, `batter_hits_runs_rbis` 58,
   `batter_total_bases` 45, `strikeouts` 11, `outs` 10 = 227 props vs 73 game
   lines. That is the 935 refusal AND the entire Kalshi-217 vs Polymarket-52
   gap — Kalshi DOES list MLB props (`ORDER_PATH venue=kalshi` shows
   `batter_rbis`/`strikeouts`/`batter_hits_runs_rbis`; Polymarket's shows
   `{'totals': {'would_build': 3}}` and nothing else).
   **CORRECTED 2026-09-01 `[lane polymarket-prop-quote-capture]` — "LISTS
   NONE" was FALSE, and the inference shape is the lesson.** It rested on two
   refusal counters that refuse INDEPENDENTLY (venue-side
   `market_type_not_a_game_line` fires before any prop is compared to our
   board; board-side `board_market_not_a_game_line` fires before any board
   prop is compared to the venue), so neither could measure overlap. Measured
   against the venue's own catalogue (99 slug↔question pairs, 8/8 fixtures):
   PROP|mlb is the venue's LARGEST bucket (2,644/cycle), ~170 player props
   per fixture (hits/tb/hr/hrr/k/outs/er/wa/ha). The join now admits them —
   verified in production 18:10:22Z: `POLYMARKET_QUOTE_CAPTURE matches=436
   appended=374` (was 60/0), `market_type_not_a_game_line` 6,960→3,375,
   `board_market_not_a_game_line` 935→138. Props feed the QUOTE CAPTURE only;
   resolvers withhold them (`POLYMARKET_PROP_RESOLVERS armed=False
   withheld=374`) unless `SYNDICATE_POLYMARKET_PROP_RESOLVERS` is armed.
   Evidence: `.syndicate/findings_2026-09-01_polymarket_prop_census.md`;
   `todo #628`. Point 1's ~76%-props board composition remains TRUE — only
   the "lists none" half is retired.
2. **POLYMARKET LISTS A PARTIAL SLATE** of the remaining game lines.
   `POLYMARKET_UNMATCHED` samples show the venue offering entirely different
   fixtures — board wants `Baltimore Orioles @ St. Louis Cardinals`, venue
   offered `mil-nym`/`col-wsh`. So `no_match` mostly means "this game is not
   listed", not "listed under a name we do not know".
3. What survives is **3 positions, all `totals`, all already held**
   (`duplicates=3 placed=0`). Stable all day (matched 55/55/55/52 at
   15:21/15:25/16:01/18:57) — NOT a regression.

**ONE REAL BUG — FIXED by `open-bet-live-status` (`2589365c`), LANDED NOT LIVE
on refresh-worker `[verified 2026-08-27 ~20:0xZ: live=7dd4ce07, does NOT
contain it]`.** A WNBA team-alias gap: `board: 'Washington Mystics @ Phoenix
Mercury'` refused `no_match` while `offered: [... 'wsh-phx@None']` — that IS
the fixture. Buckets `no_match|wnba|h2h: 7` + `no_match|wnba|totals: 15`.
MY REPORT WAS LESS PRECISE THAN THE FIX: I implied both tokens failed; they
measured `wsh` -> 'washington mystics' fine and `phx` -> None as the whole
failure. I had the sample and inferred from the pair instead of testing each
half. The CAUSE is systematic — `_basketball_alias_to_name` merges NBA and
WNBA and drops any key naming two clubs, so every city fielding both loses its
three-letter code (`phx`, `atl`, `chi`, `dal`, `ind`; `min` was supplemented
earlier for the same reason). Fixed as a class, NBA resolution verified
unaffected. refresh-worker runs the join, so the ~22 rows are NOT recovered
until that service deploys.

**THE DEAD BOOT HOOK IS GONE** — `_polymarket_catalogue_at_boot()` removed
(`fcdc5c57`), live-odds-worker live 19:43:37Z, verified here. Their control is
worth copying: `POLYMARKET_CATALOGUE: 0` read alongside `POLYMARKET_US_AUTH: 1`
and `POLYMARKET_US_SLATE: 2`, because all three at zero would have meant "no
boot observed", not "hook removed". `pipeline/polymarket_odds_refresh.py`
remains in the tree with a test suite and NO production caller — deleting a
tested module is its owner's call.

**DISPROVEN — DO NOT RE-PROPOSE.** I hypothesised the totals-only output came
from Polymarket SIDE RESOLUTION, citing `kalshi-spread-join-sign` item #4
(`over->YES/under->NO` a fixed constant while outcome orientation varies).
**Measured `side_not_an_outcome_of_this_market: 17` — the SMALLEST refusal in
the set.** `_probability_for_side` translates `home`/`away` into the row's own
team, matches literally then via `team_aliases`, and returns None rather than
picking positionally; there is no fixed over/YES constant in the board-join
path. That note is about the ORDER path. I attached a real defect to the wrong
module by topic adjacency instead of reading the function.

**NOT ESTABLISHED:** whether today is lower than previous days. Stability
WITHIN today is measured; day-over-day is not. The execution ledger is
`reports/intelligence/execution_ledger.json` (NOT `reports/execution/
live_ledger.jsonl` — I probed that first and it does not exist; the real path
is blocked too, so the conclusion held by luck off a wrong measurement).
**DO NOT "FIX" THIS BY ADDING IT TO `HOT_ARTIFACT_PATTERNS` — that is INERT.**
`execution_ledger._ledger_path()` writes through `write_json_file`, which
routes every path outside `migration_runs/` to the KEYVALUE store and returns
BEFORE touching disk, so there is no file behind that path.
`/api/ops/artifacts/export` is a DISK read; allowlisting turns
`403 not allowed` into an empty result — the guard passes and the data still
never arrives. Documented already at `ops.py:566`. The working shape is a
keyvalue-aware read, exactly like `api_ops_live_lens_snapshot_index`. Asked
`open-bet-live-status` (owns `ops.py` + `execution_ledger.py`) for a read-only
AGGREGATES endpoint — counts per venue per day, deliberately not rows, because
this is the money record. **THEY DECLINED TO BUILD IT ON A PEER REQUEST AND
WERE RIGHT TO.** It is a new outward-facing surface on the money record, which
is a SCOPE decision for the user, not something a peer can authorise — I named
that risk class and then asked a peer for it anyway. Escalated to the user with
the reasoning attached; still PENDING. So day-over-day Polymarket volume
remains unanswerable, and the structural answer above does not depend on it.

**READING TRUNCATED LOG LINES:** the Render logs API returns the full message
in `logs[].message` (2,331 chars for `POLYMARKET_UNMATCHED`); it is the
per-line DISPLAY that truncates. Fetch and slice the field rather than
concluding the detail is unavailable — the counts and samples that answered
all of the above were in a line that looked cut off.

## [exchange-venues] Crypto.com is NOT a third venue — VERIFIED 2026-08-28, local full-egress session

**The venue is attractive; the ACCESS is the blocker, and that is the whole
finding.** Crypto.com Predictions sports contracts are real, CFTC-regulated via
CDNA, and priced in dollars of probability against a $1 settlement — the SAME
unit convention as Kalshi (`BOS $0.42 / NYY $0.59`, ~1pt vig, one MLB game at
$1.37M cumulative traded). It still cannot be integrated:

- The only JSON sports surface is the consumer app's undocumented internal
  proxy, and it is **Cloudflare-gated: 200 to a challenged browser, 403 to a
  plain client** (curl, with and without full Chrome headers). Workers use
  `urllib.request`. Kalshi and Polymarket both answer a plain server-side GET.
- That JSON **carries no prices** (RSC-rendered; only a 2-point sparkline).
- The documented Exchange REST catalogue holds **957 instruments, 0 event
  contracts** (CCY_PAIR 578 / PERPETUAL_SWAP 367 / FUTURE 12).
- **OddsAPI has no crypto.com row** (`us_ex` = betopenly, kalshi, novig,
  polymarket, prophetx), so the aggregator path Novig/ProphetX use is closed.

Unblock is a **contact form, not code**. Do NOT build a browser-driven scraper.
`cryptocom_client.FINDING` and `probe()` now say all of this; `probe()` returns
`unblocked` (default False, flipped only by a non-crypto `inst_type` in the
SANCTIONED catalogue). Full evidence:
`.syndicate/findings_2026-08-28_cryptocom_venue_evaluation.md`.

**Supersedes the 2026-08-24 record**, which was written from a sandbox that
403s CONNECT to crypto.com and got three things wrong — see `learnings.md`.

## [polymarket-venue-join] VERIFIED 2026-08-29, all three services on `95c4fb12`

**Soccer, corners, BTTS and NCAAF now execute on Polymarket.** Readings are
post-`BOOTED` lines on refresh-worker, not post-`finishedAt`.

```
matched                              85 (15:22Z) -> 167 (19:08Z)
ambiguous_polymarket_match          206 -> 24     (3-way leg selection)
side_not_an_outcome_of_this_market   81 -> 22     (gt<line> polarity map)
no_candidates|ncaaf|*                90 -> 0      (cfb -> ncaaf alias)
no_match|soccer|alternate_totals_corners  37 -> 3 (line restored to _KEEP)
no_match|soccer|h2h              80 of 80 -> 0    (fixture matching)
kalshi unreadable_title            2264 -> 1790   (two soccer title grammars)
```

**Polymarket's soccer market grammar, measured rather than guessed:**
- 3-way h2h is **THREE Yes/No markets**, one per outcome, subject in the slug
  (`-liv`, `-draw`, `-not`). Not one market with three outcomes.
- Corners are `cor-all-gt<line>` PROP rows; `gt` states the direction, so
  **`Yes` = over**. 434 of them — the third-largest soccer PROP family.
- PROP vocabulary: `exact-score` 930, `fh-exact-score` 496, `cor-all` 434,
  `btts` 62, `ftts-<club>`, with `fh-`/`sh-` half variants.
- College football is filed under **`cfb`**, never `ncaaf` (2,194 rows).
- **The venue row's `line` field is the ONLY source for corners** — their slug
  carries no parseable number. `_KEEP` must retain `"line"` or every
  `_SLATE_STORAGE_FIELDS` reader silently gets `None`.

**`_has_segment` must screen `fh`/`sh`.** They are soccer halves and the old
pattern only matched digit-led ones (`1h`/`2h`), so 124 half-BTTS contracts were
admitted as full-game. Segment refusals 465 -> ~1,850 after the fix; that RISE is
the correction.

**STILL FAILING, deliberately:** MLB spreads, 22 rows. Outcomes are signed
numbers (`+1.50`/`-1.50`) against a board asking home/away, and the two observed
samples both carry `pos-1pt5`, so they cannot establish whose perspective the
venue states the spread from. Left refusing — a wrong polarity is a wrong-side
fill on live money.

**UNPROVEN, five readings:** `forward_date_widened` is `{}` on every production
read, night and day. The slate-vs-fixture date fix has never fired.

**ORDERS: there is NO Polymarket cancel path.** `kalshi_orders.py` has
`cancel_order`; `polymarket_us_orders.py` has submit/fetch/view and none.
Resting orders are GTC with no `commence_time` expiry, so a pre-game limit rests
into a live game — one was submitted 13 seconds before kickoff and never filled.
Cancelling requires Polymarket's own UI.

---

## [venue-market-universe] The venues list ~25,000 markets and the board acts on 277 — VERIFIED 2026-08-30

Measured on `refresh-worker 7d5addba`, both joins, same cycle:

```
Polymarket  15,457 captured ->  60 matched   (0.4%)
Kalshi       9,267 captured -> 217 matched   (2.3%)
board_rows   1,179
```

**THE CAPTURE IS NOT THE GAP.** `/api/ops/polymarket/slate` reports
`truncated: False`, `dropped_for_size: 0`, `slug_unparseable: 0`, 15,104 rows,
horizon to 2026-09-27, and **2,508 totals rungs against 1,385 moneylines** — the
alt ladders are already in hand, 4-9 rungs per soccer fixture.

**WE DISCARD AT CONSUMPTION.** The board is built from the ODDS SOURCE, so its
market universe is OddsAPI's. A venue market with no board row has no model
probability, no edge, and cannot be traded however good the quote:

```
market_type_not_a_game_line   6,647   props, exact-score, ftts
segment_market_not_full_game  1,430   intervals — refused BY DESIGN (#563, $7.08)
no_matching_board_row         2,016   kalshi
series_out_of_scope           1,334   kalshi
```

**A MISSING ROW IS NOT A MISSING MODEL.** Kalshi team totals
(`KXWNBATEAMTOTAL`, 36/build) refuse for want of a board row, NOT for want of a
price: `basketball_props_smart_sim` already projects `home_mu`/`away_mu`,
`home_team_total_pts_mean` and `team_total_pts` per simulated box, so
P(team over N) is countable today. The two states call for different work.

**Polymarket soccer market grammar, measured rather than guessed:** 3-way h2h is
THREE Yes/No markets with the subject in the slug; corners are `cor-all-gt<line>`
where `gt` states the direction (`Yes` = over); college football is filed under
`cfb`; the venue row's `line` field is the ONLY source for corners and `_KEEP`
must retain it.

**Kalshi refusals now say WHICH KIND.** `unreadable_title` 1,371 -> 458 with
`recognised_but_no_board_market` 838: a grammar to WRITE is separated from a
market we understand and will never price. Segments remain untradeable.

---

**`#603` REOPENED 2026-08-31 01:11Z — the 06:18Z closure below measured a
NARROWER property than the ticket.** Venue quotes DO still answer the wrong
game: 41 of 97 live MLB Kalshi-priced rows, including **9 of 9 live totals**
(Reds@Cubs priced by `KXMLBTOTAL-26AUG311805SFATL-*`, a San Francisco @ Atlanta
market), on a pool built by `165c448f` which contains both `#603` fixes. Full
reading and cause in `deploys.md`. The closure reading was real but is blind to
a ref imported from a game **not on the priced slate**: it answers exactly one
of our fixtures — the wrong one — so a collision metric scores it clean.
Cause: `_unconfirmed_on_a_contested_key` returns False whenever
`len(claimants[key]) <= 1`, and `_kalshi_game_token` collapses `no_match` into
the same `None` as "named nothing", which is the permissive branch.
`CROSS_GAME_REJECTED_GRID` never fired in ~23.7h (positive control:
`GRID_REPRICE` 544 matches, same window). `verify_603_cross_game.py` shares the
blind spot — it scores UNMEASURABLE without a collidable pair, and this defect
needs no collision.

The superseded closure, kept because its reading was sound for what it covered:
**`#603` closed and measured 2026-08-30 06:18Z.** Board `2026-08-30` pool `06:18:37Z`, after `d7cda903`:
`refs answering >1 fixture 0 of 96`, `rows served by one 0 of 177`,
`wrong-game price as served HEADLINE 0` (was 2). **The zero is discriminating**
— 192 contested keys and 992 rows of opportunity existed, and 166 matched rows
sat on contested keys, all resolving to single-fixture refs. Rule:
`venue_quote_fanin._unconfirmed_on_a_contested_key` — on a key more than one
game claims, a match needs BOTH sides to name the same game.

**The venue basis (`venue_basis_edge.py`) is WIRED and UNMEASURED.** Live in-play
exchange price vs book consensus net of venue fee, attached in the grid path and
carried through `layer2_board`'s `quote` fan-out. Proven to run: 809/809 rows
carried the key, and the same script read `NOT WIRED` against the pre-deploy
pool. **`servable=False` on every row and no reading has yet produced a real
number** — its only measurement was a slate where all 7 displayable rows were
wrong-game artifacts, and the post-fix slate was `live=0`. Its two freshness
constants (45s venue, 900s anchor) are UNFITTED guesses.

**Polymarket's fee is 150 bps of NOTIONAL, flat, price-independent** (five
`commissionNotionalTotalCollected` fills + an independent `buyingPower` route).
The earlier "fee is zero" is RETRACTED: realized P&L is `exit − entry` and the
commission is charged at fill, so that method was fee-blind by construction.
`commissionsBasisPoints: '0'` is evidence of the fee's SHAPE, never its ABSENCE.
Shape matters at the tails: at P=0.94 Kalshi MLB is `0.0020`/contract and
Polymarket `0.0150`.

**LIVE EXECUTION IS RUNNING, 2026-08-30 16:42Z**, after a ~13h halt.
`LIVE_ORDER status=submitted` ×2, then `EXECUTION status=ok
spent={'dollars': 11.37, 'orders': 4}`, both venues stamping, unreconciled 0.
Both blockers were our own guards, each correct under an assumption the other
could not see: `FILL_ABOVE_LIMIT` withheld a real `avgPx 0.2350` assuming a BUY
on an `ORDER_SIDE_SELL` order, and the reconcile then refused the order for the
price's absence. Fixed at both layers.

**A PAPER ORDER CAN NO LONGER HALT LIVE EXECUTION.** `unreconciled_orders()`
blocked on any stale `submitted` row while `reconcile_live_orders` only selects
`mode==LIVE` / `outcome is None` / matching venue — a permanent latch. Measured:
`08e9385059f46852b160eeab`, `venue='paper:polymarket'`, blocked live for hours
and was never once examined. Now excused with `UNRECONCILABLE_ORDER
... blocks_live=False`; a venue with no reader still blocks, by design, and is
named on every pass.

**`venue_quote_fanin.age_seconds` IS THE CAPTURE'S AGE, NOT A PER-QUOTE AGE.**
32 MLB quotes in one build share it to the decimal. So
`venue_basis_edge.MAX_VENUE_QUOTE_AGE_SECONDS = 45` is an ALL-OR-NOTHING gate on
a race between the venue capture cycle and the board build cycle — 0-of-6 at
64s and 32-of-32 at 4.9s are the same mechanism. Do not tune it as per-quote
staleness. `VENUE_QUOTE_AGE` now emits the uncensored series.

**`#603` IS REOPENED (2026-08-31 01:11Z) — see above. The reading below is
DISCRIMINATING FOR COLLISIONS ONLY and cannot see an off-slate ref.**
Board 06:18:37Z: 0 of 96
refs answer more than one fixture, 0 rows served by one, 0 wrong-game headline
prices — against 192 contested keys and 992 rows of opportunity, with 166
matched rows sitting on contested keys.

**`POLYMARKET_MEASURED_NOTIONAL_RATE = 0.015` IS KNOWN WRONG BELOW p≈0.43.**
Probe of `C65VD0R72KDG`: actual commission `$0.1400` against a predicted
`$0.197`; `$0.010663`/contract at a 0.235 fill. The five fitted fills sit at
0.43-0.47, straddling the p=0.4620 point where per-contract and per-cost models
are identical by construction.

**THE VENUE BASIS IS WIRED AND UNMEASURED.** `venue_basis_edge` runs end to end
(809/809 rows carried the key) and `servable=False` on every row. **No reading
has yet produced a single scored comparison** — its one live slate refused all
six eligible rows before the arithmetic. Do not lift `servable` without one.

## [polymarket-orders-are-cancelled] 2026-08-30 — the venue cancels them, we re-place them, and nobody knows why

**THE ORDERS DO NOT REST AND FAIL TO FILL. THEY ARE CANCELLED.** That reframes
the original question: it is not a pricing or sizing problem at all.

**WE ARE NOT DOING IT — fifth cause eliminated.** `cancel_stale_resting_orders`
(15-min age, 1c band, max 3/pass) is a real venue-write loop, but
`run_live_odds_refresh_worker:1676-1699` feeds it ONLY Kalshi rows and says so:
*"Kalshi first and its result kept ... Polymarket's pass runs for its ledger
corrections only."* Polymarket's own `cancel_order` (`3170db13`) exists and is
NEVER CALLED. So the cancellations are venue-initiated.

**THE SUBMIT -> CANCEL -> RESUBMIT LOOP is real, and it is where the duplicate
exposure came from:**

    tsc-sea-lec-rom-2026-08-31   submit 01:02:05 -> CANCELED 01:30:32 -> resubmit 01:30:35
    tsc-mlb-phi-laa-2026-08-30   submit 16:42:25 -> cancelled -> 18:19:10 -> cancelled -> 20:48:00

The resubmit follows the observed cancel by THREE SECONDS — same tick.

**REFUTED: a fixed venue TTL.** `C6R7RS83JKDD` died ~28 min after submit, but its
replacement `C6RNQZ8B2KDE` has been `ORDER_STATE_NEW` for 40+ minutes
(01:30:35 -> 02:10:11) with no cancel. **REFUTED: market close** — sea-lec-rom
was cancelled ~15 HOURS before its 16:30Z kickoff.

**CORRECTION, MINE, CAUGHT BEFORE IT WAS REPORTED AS A FINDING.** I measured a
near-perfect +62s correlation between deploys and cancellations across six
deploys and nearly called it cancel-on-disconnect. It was an artifact: I matched
the raw text `order_state_canceled`, which appears on EVERY pass that re-prints
an already-cancelled row. Filtering to actual `RECONCILED` state TRANSITIONS
leaves **three events in 12h** — 18:18:51 (n=4), 19:59:16 (n=1), 01:30:32 (n=1)
— and only one is deploy-adjacent. **A re-report is not an event.**

**STILL WORTH EXPLAINING: 18:18:51 cancelled FOUR orders at once** (lad-det x2,
phi-laa, lal-cel-ath). A simultaneous batch looks like a session-level event, but
no restart appears in the 18:00-18:30Z logs.

**MEASURED 2026-08-31T02:34:51Z — EXPIRY IS DEAD. `goodTillTime=None` ON ALL
FIVE ORDERS, and `tif='TIME_IN_FORCE_GOOD_TILL_CANCEL'` on all five.**

    C6RNQZ8B2KDE  sea-lec-rom  NEW     created 01:30:36  tif=GTC  goodTillTime=None
    C6RYD4TDWKDH  bun-scp-scf  NEW     created 01:47:57  tif=GTC  goodTillTime=None
    C4N3GPYA4GNQ  nfl lar-lac  FILLED  created 08-27     tif=GTC  goodTillTime=None

Two facts, both new. **The venue imposes NO expiry** — there is no clock on these
orders. And **the venue DID store the good-till-cancel we sent**, which had been
an assumption nothing ever read back.

The `created` timestamps close the TTL question outright: `C6RNQZ8B2KDE` has been
`ORDER_STATE_NEW` for **64 minutes** and counting, while its predecessor
`C6R7RS83JKDD` died at ~28. Cancellation is not a clock. **Sixth cause
eliminated.**

**THE 18:18:51 BATCH, CHASED 2026-08-31. Four more causes eliminated, and my own
framing of it is now suspect.**

Window bounded to **18:13:12 -> 18:18:51**: the prior polymarket reconcile pass
reported `changed=0`, this one `changed=4`. Inside that window:

- **NOT an account-wide sweep.** `candidates=10 venue_orders=10 changed=4` -- ten
  orders read, four cancelled. Selective. But the six survivors were already
  FILLED, i.e. terminal and uncancellable, so the four may still have been ALL
  the OPEN orders. That distinction is unresolved.
- **NOT insufficient collateral.** Balance FLAT at $87.26 across the window
  (18:12:47 / 18:18:36 / 18:26:44), and it did not RISE afterwards either, so
  those orders were not holding reserved funds.
- **NOT a restart or OOM.** The Render EVENTS API is empty from 17:30 to
  18:34:20Z.
- **NOT a deploy.** The nearest one STARTED 18:34:20, after the fact.

**THE VENUE DOES NOT SAY WHY.** Its per-order payload carries 24 fields and no
cancellation-reason field; `state` is the only status-bearing one.

**AND "FOUR AT ONCE" IS MY WORDING, NOT A MEASUREMENT.** We OBSERVED four
transitions in ONE reconcile pass spanning 5.6 minutes. Whether they were
cancelled SIMULTANEOUSLY is a different claim. `lastTransactTime` is returned on
every order and has never been logged: if the four share one timestamp it is a
single sweep; if they differ, they are independent events being treated as one
phenomenon.

**DEPLOYED AND READ 2026-08-31T02:50:52Z (96735d8a). One half works, the other
half was a miss.**

**`lastTransactTime` WORKS, and was validated BEFORE being relied on:**

    resting  sea-lec-rom  created 01:30:36.041  lastTransact 01:30:36.043  (untouched)
    filled   nfl lar-lac  created 08-27 18:33:31  lastTransact 19:40:20    (+67 min)
    filled   sea-juv-par  created 19:45:07        lastTransact 19:48:59    (+4 min)

It equals `created` to the millisecond for an untouched order and is the fill
time for a filled one. So the next cancellation shows whether the orders share
ONE timestamp (a sweep) or differ (independent events wrongly described as one
phenomenon). That question is now answerable; it was not before.

**`marketMetadata` IS A MISS — IT CARRIES NO MARKET STATE.** The full object fits
inside the 240-char bound: `{slug, icon, title, outcome, eventSlug, eventId}`.
Pure display metadata. **The market-state hypothesis cannot be tested from the
order payload at all.** Do not re-add this field expecting state — the state
proxy is `orderable` on the SLATE row, a different read in
`polymarket_us_markets` (held by `live-venue-order-placement`).

The bound did not hide it: the value came back UNCLIPPED, and that was checked
rather than assumed.

**Incidental, and it bears on the time-to-event hypothesis:** resting orders DO
fill, on very different timescales — `nfl lar-lac` at +67 minutes,
`sea-juv-par` at under 4.


**NEXT, CHEAP:** log `lastTransactTime` (exact transition time), `marketMetadata`
(market state -- the leading remaining explanation) and `intent`. Log-only, same
ORDER_STATE line, one deploy.


WHAT REMAINS: cancellations are SPORADIC EVENTS, not a rule. Three transitions in
12h, one of which took FOUR orders at once (18:18:51) with no restart in the
surrounding logs. That batch is now the whole remaining thread — a simultaneous
multi-order cancel is a session- or account-level action, not a per-order one.

Superseded, kept for the record:
**THE DECISIVE FIELD IS `goodTillTime`, AND WE NEITHER SET NOR LOG IT.** We send
`tif=TIME_IN_FORCE_GOOD_TILL_CANCEL` and no expiry, so the venue applies its own
default. It RETURNS `goodTillTime` on every order — `ORDERS_READ` prints the KEY
NAMES only, and `ORDER_STATE` logs cum/leaves/avgPx but not this. One line added
to `ORDER_STATE` would settle it. `polymarket_us_orders.py` is claimed by
`polymarket-yes-leg-binding`, so it needs that lane or an override, plus a deploy.

## [polymarket-resting-orders-do-not-encumber-cash] 2026-08-31T15:45Z — CONFIRMED by a before/after pair, after I doubted it

**The claim under test:** "an unfilled order holds no reserved funds", used as
the argument that placing early costs only CHURN, never capital. It rested on a
balance that was flat at $87.26 across a cancellation — weaker evidence than it
sounded, because a cancellation restoring funds looks identical to funds never
having been taken.

**The doubt:** the user's order screen showed Cash $75.55 against Portfolio
$89.95 with $10.09 of pending orders sitting in the gap.

**THE MEASUREMENT — the same instant either side of two real submits:**

    15:25:23Z  VENUE_BALANCES polymarket=ok:75.56   BEFORE both explores
    15:25:43Z  SUBMIT bal-col  $1.10
    15:25:45Z  SUBMIT ast-ars  $8.99
    15:42:16Z  VENUE_BALANCES polymarket=ok:75.56   AFTER, unchanged

$10.09 of NEW resting orders moved spendable capital by **$0.00**. The gap on
the screen is position value and reconciles exactly: 75.55 + 14.40 = 89.95.

**WHY THIS READING IS THE RIGHT ONE.** `venue_balances.py:372` sets
`spendable = buying_power if buying_power is not None else current`, and
`buyingPower` is the venue's own "unencumbered capital available for trading".
Encumbrance is precisely what that field would express, and it did not move.

**SO CHURN REALLY IS THE ONLY COST OF A RESTING ORDER**, and the pregame hold is
justified by duplicate-exposure risk alone — never by tied-up capital. Anyone
arguing the hold saves money is arguing something this measurement refutes.

## [polymarket-price-gate-leaks-by-crossing] 2026-08-31T16:05Z — FIXED AND DEPLOYED. The ceiling used to be checked against a price the venue never receives

**VERIFIED BY CODE TRACE, not by inference:**

    execute_portfolio.py:498   gate  _polymarket_hold_price(request, venue)
                               reads planned_probability(request.requested_price)
    execute_portfolio.py:1816  submit _polymarket_resolve_market(request)
                               applies crossing (+N ticks) THEN snap direction="up"

The gate runs ~1300 lines EARLIER than price resolution. Both crossing and the
snap round UP by design, so **the submitted price is systematically higher than
the price the ceiling was tested against.** Measured on the two live explores:

    gate saw   0.444 / 0.441      (logged in EXPLORE_PREGAME_BOUNDARY)
    venue got  0.45  / 0.45       (SUBMIT ... price={'value': '0.45'})

**CONSEQUENCE 1 — the ceiling is NOMINAL.** A planned 0.349 against a 0.35
ceiling passes the gate and is submitted at ~0.355+. There is no price at which
the gate actually bounds what is bought; it bounds an intermediate value.

**CONSEQUENCE 2 — every HELD/EXPLORE price in the logs is the WRONG NUMBER to
reason from.** Anyone deriving a boundary from those lines is reading planned
prices and attributing them to orders that rested at a higher price.

**NOT CURRENTLY MOVING A DECISION, and that is luck, not design.** The overshoot
is one tick, and 0.349 -> 0.36 stays inside the unobserved gap 0.335..0.410, so
no hold/place call flips today. The moment the ceiling is tuned NEAR the real
boundary — which is the whole point of the exploration arm — the leak lands
exactly where it does damage.

**FIXED `34d43512`, live 15:50:18Z.** `_polymarket_submit_price` resolves through
the SAME `_polymarket_resolve_market` placement uses, so there is no second copy
of the venue's rounding to go stale. Every `None` path — unresolvable side, stale
artifact, `_SlippageExceeded` — means "cannot tell" and PLACES, because the real
path refuses each by name moments later. The raise is caught deliberately: the
gate's call site does not handle it, so an escape would abort the placement loop
for every remaining position on the tick.

**VERIFIED by branch assertion:** `submit_price=` exists only in the new code and
appeared 4x at 15:53:26Z. HELD/EXPLORE now log `submit_price=` for the same
reason — the old field was a planned price attributed to an order resting higher,
and I reasoned from it wrongly once.

**FIX IS NOT "subtract a tick".** The gate must evaluate the price that will be
submitted, which means resolving tick/cross BEFORE the gate or applying the same
arithmetic in it. Anything else re-derives the venue's rounding by hand and goes
stale the next time tick size changes.

## [polymarket-soccer-h2h-bought-the-OPPOSITE-team] 2026-08-31T21:25Z — FIXED AND DEPLOYED on both services; the positive case is UNVERIFIED

**USER-REPORTED, LIVE MONEY.** Two orders bought the other team.

    atc-lal-osa-get   board "Getafe @ CA Osasuna", bet HOME -> bought GETAFE
                      Osasuna WON, the bet LOST.  -$5.96 realised
    atc-sea-ata-bol   board "Bologna @ Atalanta BC", bet HOME -> bought BOLOGNA
                      STILL OPEN on the wrong side. No deploy unwinds it.

**CAUSE.** `parse_slug` documents `<away>-<home>` and applies it to EVERY sport.
MLB really is away-first (`aec-mlb-bal-col` reports away_index=1 = Baltimore and
`bal` leads); both soccer fixtures are HOME-first. `_subject_is_side` checked
`subject == parsed[wanted]` FIRST and returned True. Its "definitive NO" guard
reads the SAME inverted parse, so it CONFIRMED the wrong answer rather than
contradicting it — two checks, one shared broken input. The alias check that
answers all four legs correctly sat below both and never ran.

**BLAST RADIUS EXACTLY 2**, by enumerating all 69 distinct Polymarket slugs
submitted in log retention: the other 67 are totals or team-named markets that
never route through the subject test.

**FIXED.** `8876b823` — the board's own team names decide, refusing when the
subject names both or neither; the positional parse is gone from this decision.
`d04d9f49` — `execute_portfolio` was handing that test the SLATE row, and
`_SLATE_STORAGE_FIELDS` has no team names, so alone it would have refused EVERY
soccer moneyline: fail-safe and silently dark.

    live-odds-worker  d04d9f49  live 21:02:07Z
    refresh-worker    8876b823  live 21:20:36Z  (ancestry-checked on the RUNNING
                                commit; deployed by `layer2-cap-raise`, not me)

**`parse_slug` IS NOT CHANGED.** Its orientation is still used for FIXTURE
matching, where both teams are present and the roles do not decide which game is
found. Anyone touching it should know the soccer orientation is inverted.

**VERIFIED: only the NEGATIVE.** The wrong-side path cannot execute — first tick
after showed `positions=4 placed=0 skipped=4`, MLB `YES_LEG agree=True`, zero
`POLYMARKET_SIDE_REFUSED`. **NO soccer h2h has resolved since either deploy**, so
a correct leg being selected and placed has NOT been observed. Tomorrow's slate.

**AND IT CONFOUNDS THE FILL EVIDENCE.** Two of the three pregame fills cited all
day as "cheap sides fill" (0.240, 0.250) ARE these wrong-side orders — cheap
BECAUSE they were away underdogs. The `ast-ars` confirmation stands alone; the
sample around it was thinner and dirtier than it was presented.

## [polymarket-two-dimensional-rule-PARTLY-CONFIRMED] 2026-09-01T01:20Z — the PREGAME half is solid on two probes; the LIVE half rests on ONE and is NOT replicating

**THE FIRST DELIBERATE TEST OF THE RULE, AND IT PASSED.** `ast-ars` was placed ON
PURPOSE at a price the rule predicted could not fill, to try to break it.

    created      15:25:45Z   pregame, submit_price 0.45
    kickoff      19:02:22Z   (hours_to_commence=1.5 @ 17:32:22Z)
    lastTransact 19:20:09Z   FILLED, kick+17m47s
    avgPx        0.4500      exactly the limit, no price improvement
    cum          19.97/19.97 leaves=0, complete fill
    ledger       RECONCILED submitted->filled fill_price=0.45

**PREGAME: ~20 book reads over 3h54m, cum=0 throughout, zero partials.
LIVE: filled inside 18 minutes.** `bal-col` is still resting and still pregame
(kickoff ~00:45Z), which is the control and it behaves.

**THE PRICE RULE IS NOT REFUTED.** It did NOT fill pregame at 0.45, well above
the 0.410 top of the observed resting range. The ceiling does not move on this.

**AND THE BIG ONE: THE HELD POPULATION IS DEFERRED, NOT FORFEITED.** The gate's
cost was recorded hours ago as "a bet that ~11.5% mean EV across six positions is
unreachable". That framing is now WRONG in the good direction: a held order
places once `hours <= 0` and fills like this one did. The EV is not thrown away.

**BUT DO NOT READ THIS AS A WIN FOR THE GATE — IT WEAKENS THE CASE FOR IT.**
This order was PLACED EARLY and nothing bad happened: no churn, no cancel, no
duplicate, and it filled at exactly its limit. Meanwhile the price it locked was
0.45 while the same market read 0.460 at 17:32Z, so placing early plausibly beat
placing at kickoff by ~1c on 19.97 shares. One instance, and the earlier drift
measurement was 3 up / 2 down / 2 flat with mean +0.005 — no systematic
direction. The honest position: the gate prevents duplicate exposure (a real,
measured $9.12 incident) and buys nothing else that this fill demonstrates.

**WHAT IS STILL UNMEASURED:** whether the model was RIGHT. `ev_pct=22.68` on this
position is the model's own claim. The bet settles with the match.

**REVISED, and this DOWNGRADES what I recorded at 19:25Z.** I wrote "the rule is
CONFIRMED" on ONE probe. The second probe is not behaving the same way.

    ast-ars  EPL totals   rested 3h54m pregame, FILLED kick+17m47s @ avgPx 0.4500
    bal-col  MLB h2h      rested 9h13m pregame, STILL RESTING at pitch+35m

`bal-col` reads at pitch -15/-10/-5/0/+5/+10/+15/+20/+25/+30/+35, every one
`cum=0 leaves=2.44`. `lastTransact` never moved off its 15:25:43Z submit.

**WHAT IS SOLID: the PREGAME half.** Two deliberately-placed probes at 0.45, ~20
book reads each, zero fills, zero partials, across two sports and two markets.
Near-even pregame orders do not fill. That is now well-supported.

**WHAT IS NOT: the LIVE half.** "Once live, everything fills" rests on ONE
observation (`ast-ars`) plus 8 earlier settled orders that were ALREADY under way
when observed — never a probe placed pregame and watched through the transition.
`bal-col` is exactly that probe and it is not filling.

**A DEADLINE WAS NEVER PART OF THE RULE.** `ast-ars` filling at +18m does not
make +35m late for a different market. This is a divergence in progress, not a
refutation. But the rule cannot be stated as general until it is qualified by
sport or market, or `bal-col` fills.

**CANNOT INDEPENDENTLY CONFIRM LIVENESS.** `gameStartTime` is ABSENT on all 10
`bal-col` slate rows (same class as the documented `line: None` gap), so "live"
here means only the board's `commence_time` — two readings agreeing on ~00:38-40Z
(`7.1h @ 17:32Z`, `5.2h @ 19:28Z`). If that value is wrong, the game is not live
and none of this is a live-window observation at all.

## [polymarket-held-population-is-6-of-6-POSITIVE-EV] 2026-08-31T17:33Z — the gate suppresses positive-EV bets; its whole defence is that they cannot fill

**FIRST MEASUREMENT OF WHAT THE HOLD COSTS.** `9d0fcb11` stamps `ev_pct` on every
gate line (live 17:28:43Z); the first tick after it, 17:32:20-22Z:

    ticker                       submit  ev_pct  edge_pct
    tsc-epl-ast-ars-2pt5          0.460   22.68     6.80
    aec-mlb-nyy-laa               0.465   16.32     2.45
    aec-mlb-det-min               0.470   14.03     2.29
    tsc-mlb-det-min-8pt5          0.460    8.14     8.64
    aec-mlb-mia-wsh               0.495    4.82    11.52
    tsc-mlb-bal-col-10pt5         0.465    3.27     2.51

    EXECUTED positions=8 placed=0 skipped=6 refused={'pregame_price_too_high': 6}
             duplicates=2   (the two resting experiments)

**6 of 6 POSITIVE. Mean +11.5% EV.** Unweighted — the log does not carry stake,
so this is per-position and NOT the dollar-weighted number.

**WHAT THIS DOES AND DOES NOT SAY.** It does NOT say the gate is wrong. EV is
only realisable if the order FILLS, and the gate's entire premise is that these
do not fill pregame — 8 resting observations, zero pregame fills above 0.410. If
that premise holds, suppressing them costs nothing and the +11.5% is unreachable
paper EV.

**BUT THE PREMISE IS NOW LOAD-BEARING IN DOLLARS, NOT JUST IN TIDINESS.** Before
this reading the hold looked free — churn avoidance. It is not free: it is a bet
that ~11.5% mean EV across six positions is unreachable. If the kickoff
experiment shows these fill, the gate is expensive and the ceiling must move.

**DO NOT TREAT `ev_pct` AND `edge_pct` AS THE SAME RANKING.** They disagree
sharply and consistently — `nyy-laa` is 16.32 EV on 2.45 edge, `mia-wsh` is 4.82
EV on 11.52 edge. They measure different things (return per stake vs probability
edge in points). Whichever one a decision uses must be named.

**AND EV HERE IS THE MODEL'S OWN CLAIM.** It is `ev_pct` off the plan position,
not a realised result. Nothing in this section is evidence the model is right —
today's six settle overnight and that is the first honest scoring.

## [polymarket-explore-arm-FIRING] 2026-08-31T16:05Z — the arm fired, STALLED on a float edge, and fires again; the falsifier is live

**`e8392f1b` live 15:21:40Z at rate 0.5. First tick after rollout:**

    EXPLORE  aec-mlb-bal-col-2026-08-31       0.444  +9.3h   rate=0.5
             tsc-epl-ast-ars-2026-08-31-2pt5  0.441  +3.6h   rate=0.5
    HELD     mia-wsh 0.485 │ nyy-laa 0.461    (both ABOVE the 0.45 band edge)
    EXECUTED positions=6 placed=2 filled=0 duplicates=2 skipped=2

`rate=0.5` appears in the log line itself, so the new code RAN — asserted by
branch, not by deploy state. The two held are correctly outside the band; the
two explored are correctly inside it. `ast-ars` drifted 0.450 -> 0.441, which is
what brought it into range.

**THESE TWO ORDERS ARE THE LIVE FALSIFIER.** Both are priced ABOVE 0.410, the
top of the observed resting range, and both were placed ON PURPOSE. The rule
says they will rest.

    EITHER FILLS  -> the rule is refuted, 0.35 is too low, and the ceiling must
                     be re-derived from where the fill landed.
    BOTH REST     -> the ordering survives its first deliberate test and n grows
                     from 3.

**READ THEM AS EXPLORATION, NOT AS ORDINARY FILLS.** They were selected BECAUSE
the rule predicts they fail. Pooling an exploration fill with an ordinary one
would corrupt exactly the measurement the arm exists to produce — that is why
the line is logged distinctly.

**AND STILL: A FILL HERE IS NOT PROFIT.** These are near-even sides chosen to
test a boundary, not because they are good bets. Whatever they do, the EV
question is separate and unanswered.

**CORRECTION, and it is why "the arm is firing" was not enough.** It fired twice
at 15:25Z and then STALLED. `0.35 + 0.10` is `0.44999999999999996`, so a 0.450
order fell outside a band whose configured top is 0.45. LATENT ALL DAY and made
reachable by the submit-price fix: planned prices (0.441, 0.444) are arbitrary
and never land on the edge, while SUBMIT prices are snapped to the tick and land
on round boundaries constantly — 0.45 is exactly where a 0.44 or 0.445 quote
crosses to. The arm's single most probable price was the one it could not place.
Fixed `3db201bc`, live 15:59:13Z; verified 16:03:16Z, `EXPLORE bal-col
submit_price=0.450`, with 0.460/0.465/0.490 correctly held.

**THE EXPERIMENTS, as of 16:20Z:** both rest at 0.45, `cum=0`, full `leaves`,
across FIVE independent book reads. The pregame price rule holds on its first
DELIBERATE test — the evidence moved from 3 passive observations to 5, and from
observed to probed. Kickoff is the decisive reading: `ast-ars` ~18:57Z,
`bal-col` ~00:45Z.

## [polymarket-explore-arm-too-slow] 2026-08-31T15:11Z — the arm is LIVE and CORRECT, and its sample rate is close to zero

**Deployed `b6c02dff`, live 15:07:47Z. First tick: `EXPLORE_PREGAME_BOUNDARY 0`,
and that is arithmetic, not a fault.**

    HELD    0.485  0.465  0.461  0.450        band = 0.35 .. 0.45
    -> only ONE of four is inside the band, and at rate 0.10 one order explores
       10% of the time.

**AND DETERMINISM MEANS IT NEVER RE-ROLLS.** Assignment is
`sha1(position_key)`, deliberately, so the same position gets the same verdict
forever — that is what stops the churn. The consequence is that the arm samples
**new POSITIONS, not ticks**: repeating a held order every 5 minutes gives no
extra chances. With a handful of new boundary positions a day at 10%, this
yields roughly **one exploration order every several days**.

**So the falsifier is alive but nearly static.** Better than the
self-confirming gate it replaced, and far short of what re-deriving a threshold
needs.

**TWO TUNABLE FIXES, neither applied:**
  - **RAISE THE RATE.** 0.10 was picked for a large population; the real
    boundary population is 1-3 positions per tick. 0.25-0.50 would sample
    meaningfully at a still-bounded cost, since the cost is churn and not stake.
  - **WIDEN THE BAND** past 0.45. Weaker: 0.46-0.49 has been observed resting
    repeatedly, so it buys churn for information already held.

**Prefer the rate.** `SYNDICATE_POLYMARKET_EXPLORE_RATE`, and on Render an env
change needs a deploy either way.

**ALSO OBSERVED, unrelated and pre-existing:** `POLYMARKET_US_SLATE
status=skipped reason=sports_routes_404_on_this_host_measured_2026-08-24`. It is
NOT blocking the order path — `ORDER_PATH` and `EXECUTED` both ran this tick —
but if the slate ever stops refreshing, price resolution refuses on staleness and
the symptom looks identical to a dead arm.

## [polymarket-gate-is-self-confirming] 2026-08-31T13:42Z — THE GATE DESTROYED ITS OWN FALSIFIER

**Asked whether `sf-atl` (pregame, ~0.400, the closest observation to the
boundary) ever filled. IT WAS NEVER PLACED — the gate held it.** There is no
order, so there is no answer, and there never will be while the gate runs.

    tracked orders now: 5, ALL FILLED, resting: NONE
      0.210 juv-par(past)  0.240 ata-bol  0.250 osa-get
      0.335 ath-tex        0.490 lar-lac(past)

**Every surviving order fits the rule perfectly, and that is exactly what a
self-confirming filter looks like.** The stated falsifier is "a PREGAME FILL
above 0.410" — but near-even pregame orders are the ONLY population that could
produce one, and the gate suppresses all of them. The evidence base is now
frozen at n=3 pregame fills and cannot grow.

**THIS IS A DESIGN DEFECT, NOT A DATA GAP.** The 0.35 ceiling was chosen as a
risk decision pending more evidence, and the gate as built guarantees that
evidence never arrives. Any threshold in 0.335-0.410 will look correct forever.

**THE FIX IS AN EXPLORATION ARM.** Let a small, bounded fraction of near-even
pregame orders through — a holdout — so the boundary keeps being tested at a
known, capped cost. Without one, the rule cannot be re-derived and the
"re-derive as the gap fills in" note in `_polymarket_max_pregame_price` is
unachievable by construction.

**NOT BUILT. Flagged only.** It is a live-money selection change and this
session has already deployed one gate on a hypothesis that died within the hour.

## [polymarket-cheap-side-selection-risk] 2026-08-31 — HIGHER FILL VOLUME IS NOT SUCCESS. The gate changes the BET MIX.

**Raised by `polymarket-yes-leg-binding` and it is the most important
consequence of the price gate, not a footnote.**

The rule places cheap pregame sides and holds near-even ones. That is not a
neutral execution filter — **it is a SELECTION CHANGE**. It systematically
shifts what we bet toward LONGSHOTS, because those are the sides with a book
pregame.

**Everything established tonight is about whether an order FILLS. Nothing
establishes whether a cheap pregame fill is a GOOD BET.** Those are different
questions and the 11-order sample answers only the first.

**SO DO NOT READ RISING FILL VOLUME AS SUCCESS.** A gate that doubles fills
while shifting the mix toward longshots could easily be EV-negative and would
look like progress on every count we currently print. The EV of the cheap-side
population must be scored SEPARATELY, against the closing line or realised
settlement, before this gate is judged to have helped.

**Concretely: `placed`, `filled` and fill-rate are now MISLEADING as success
metrics for this change.** The honest metric is P&L or CLV on the orders the
gate lets through, versus what the un-gated policy would have produced.

**THE CEILING IS 0.35, AND THAT IS A RISK CHOICE, NOT A MEASUREMENT.** Nothing
has ever been observed between 0.335 and 0.410; every threshold in that gap fits
the data equally. 0.35 places only what has been watched to fill; 0.41 would
place an unmeasured band on the assumption it behaves like the cheap side. Since
churn is the stated harm, it errs toward not placing. **0.37 shipped first and
was the worst available choice — the midpoint of a gap is the one value with no
evidence behind it.**

**FALSIFIER, either ends the rule:** a pregame FILL above 0.410, or a pregame
REST below 0.335. Only the ORDERING is claimed. `sf-atl` at 0.400 is the closest
live observation to the boundary.

## [polymarket-price-gate-LIVE] 2026-08-31T05:58Z — the price gate is live and holding the right population

**`0c3f102f` deployed THROUGH a preflight HOLD `[user: "deploy it through
anything running"]`.** Cost recorded rather than skipped: it killed three
in-flight jobs — `refresh_odds_sources.py`, its parent `run_refresh_odds_job.py`,
and a `build_soccer_artifacts.py --league serie_a` build. All re-run next tick.

**First tick:**

    HELD_PREGAME_NEAR_EVEN x5   mia-wsh 0.485 +16.8h │ det-min 0.455 +17.7h
                                nyy-laa 0.429 +19.7h │ lec-rom 0.481 +10.5h
                                sf-atl  0.400 +16.1h
    EXECUTED positions=8 placed=0 duplicates=3 skipped=5
             refused={'pregame_price_too_high': 5}

Every held order is near-even AND pregame — exactly the population that has
never filled across 12 observations. **Nothing cheap was suppressed**, which is
the failure mode the old time gate had.

**A PRECISION CAVEAT WORTH KEEPING.** The gate reads
`planned_probability(requested_price)`, not the venue quote, and they differ
slightly: `sf-atl` gates at 0.400 while its venue price was 0.410; `mia-wsh`
0.485 vs 0.490. The slippage guard bounds that gap at 3c, so a decision NEAR THE
CEILING could flip on which number is used. Away from 0.37 it makes no
difference; at the boundary it would.

**STILL UNVALIDATED:** the 0.37 ceiling. n=3 pregame fills, and the boundary
lies in the never-observed gap 0.335 -> 0.410. `sf-atl` at 0.400 is now the
closest observation to it — if that price ever fills, the ceiling is too low.

## [polymarket-TIME-IS-NOT-THE-VARIABLE] 2026-08-31T05:29Z — TIME-TO-EVENT IS REFUTED. The gate's premise is false.

**A PREGAME ORDER FILLED, 18.6 HOURS BEFORE KICKOFF, WITHIN ~18 MINUTES.**

    aec-mlb-ath-tex-2026-08-31   mlb h2h   kickoff 09-01T00:05Z  18.6h out  FILLED cum=5.25 @0.335
    tsc-sea-lec-rom-...-2pt5     soccer totals  kickoff 08-31T16:30Z  11.0h out  resting 1.4h
    tsc-epl-ast-ars-...-2pt5     soccer totals  kickoff 08-31T19:00Z  13.5h out  resting 1.4h

**The order that FILLED was FURTHER from kickoff than the two that did not.**
Time-to-event cannot explain that, and it was the hypothesis `f6f45321` was
built on. **The gate's stated premise — "pregame orders do not fill at any
price" — is FALSE.**

**WHAT ACTUALLY SEPARATES THEM IS THE MARKET, NOT THE CLOCK.** Filled: an MLB
MONEYLINE (`aec-`). Resting: SOCCER TOTALS (`tsc-`). Also newly placed and
resting are three more MLB moneylines (det-min, nyy-laa, sf-atl) at 16-20h, so
one h2h fill out of four is not yet a rate either — but one fill is enough to
kill "pregame never fills".

**THE GATE IS LIVE AND SUPPRESSING 13 OF 17 POSITIONS ON A FALSE PREMISE.** It
did not block this fill (18.6h is inside the 24h window), so nothing is known to
have been lost yet. But it is keyed on the WRONG AXIS, and the orders it holds
are mostly far-out SOCCER h2h — a market family we have never seen fill at any
horizon, which is a different reason from the one written into the code.

**RECOMMENDED: disable it** (`SYNDICATE_POLYMARKET_MIN_HOURS_TO_COMMENCE=0`, or
revert `f6f45321`) until the axis is established. On Render an env change needs
a deploy, so a revert is the faster off-switch.

**THE REAL QUESTION IS NOW LIQUIDITY BY MARKET FAMILY:** do soccer `tsc-` totals
EVER fill, at any horizon? Every fill on record is MLB or NFL. If soccer totals
never fill, the fix is not timing at all -- it is not offering them.

## [polymarket-placement-hold] 2026-08-31 — LIVE, and it holds 13 of 17 positions

**Deployed `f6f45321`, live 04:36Z. First tick:**

    EXECUTED positions=17 placed=0 duplicates=2 retried=2 skipped=13
             refused={'too_early_to_place': 13}

    held: 38.1h, 86.4h, 129.4h, 129.4h, 131.4h, 131.9h ... (threshold 24.0h)

**NOTHING BORDERLINE IS CAUGHT.** Every held order is 38h+ out; the 0-24h window
is untouched, which is the design. But **13 of 17 is a large suppression** and it
is the dominant refusal on the venue now — that is a real behavioural change, not
a marginal one.

**AND IT INTERACTS WITH THE YES-LEG FIX.** Almost every held order is an `atc-`
**h2h** market — the moneylines `8b0d27df` unblocked earlier today. Opening h2h
produced a large set of far-future soccer moneyline candidates, and this gate is
now holding them. Neither change is wrong; the combination is what produces
`placed=0`, and reading either one alone would mislead.

**WHY HOLDING THEM IS RIGHT ON THE EVIDENCE:** pregame orders do not fill at any
price we have tried (quote, and a tick above), while 8 of 8 fills came on
live-or-past markets. An order 5 days out cannot fill and only buys the
submit -> cancel -> resubmit churn that produced the $9.12 duplicate.

**WHAT WOULD MAKE THIS WRONG, and how it would show:** if far-out orders DO fill
given enough time, this suppresses real bets. The test is already running for
free — `lec-rom` and `ast-ars` sit live at 0.49 with kickoffs ~12h out, inside
the window and therefore still placed. If they fill near kickoff and nothing
ever fills far out, the gate is justified and 24h can be tuned from evidence
instead of judgement.

## [polymarket-crossing-RESULT] 2026-08-31 — CROSSING DOES NOT HELP. Price is not the constraint pregame.

**THE EXPERIMENT RAN PROPERLY AND ANSWERED.** The user cancelled the three
resting orders on the venue, freeing their position keys; the next tick
re-placed all three ONE TICK ABOVE the quote:

    04:07:01  tsc-sea-lec-rom-2026-08-31-2pt5  0.49  (quote 0.48)  kickoff ~12h
    04:07:06  tsc-bun-scp-scf-2026-09-05-2pt5  0.46  (quote 0.45)  kickoff 5 DAYS
    04:07:08  tsc-epl-ast-ars-2026-08-31-2pt5  0.49  (quote 0.48)  kickoff ~12h

    EXECUTED positions=17 placed=3 filled=0 duplicates=0

**AND THEY STILL DID NOT FILL** — reported by the USER from the venue's own
Orders screen. That is the tenth eliminated cause: **PRICE**.

**WHAT IT MEANS.** We bid the quote: rests. We bid a tick above: rests. On the
same markets, at two prices, pregame. The book is not there at any price we have
tried. Combined with 8 of 8 fills occurring on LIVE-or-PAST markets and 3 of 3
pregame orders resting, **time-to-event is now supported by a direct experiment
rather than by correlation alone.**

**THE FIX IS PLACEMENT TIMING, NOT PRICING.** Nothing in the pricing path is
wrong: the tick snap is a no-op on on-grid quotes, the slippage guard gates the
sent price, the quote is a real ask (sums 1.005-1.030), and crossing it changes
nothing.

**HONEST LIMITS, because this was ~15 minutes:**
- One tick may be too small. The dial reaches 3 (`SYNDICATE_POLYMARKET_CROSS_TICKS`).
- `nfl lar-lac` once took **67 minutes** to fill, so a short no-fill window is
  suggestive, not proof.
- Two fixtures are ~12h out and one is 5 days; none is near kickoff, which is
  exactly the regime the hypothesis says DOES fill.
- The clean confirmation is free and arrives on its own: if these same orders
  fill as their kickoffs approach, time-to-event is settled outright.

**CALIBRATION GAINED FOR FREE.** The user's three cancels produced DISTINCT
`lastTransactTime` values 0.66-0.82s apart, spanning 1.47s. So a real
multi-order cancel action looks like sub-second-spaced DISTINCT timestamps, not
one shared one — the yardstick that was missing when the 18:18:51 "four at once"
claim had to be withdrawn as unverified.

## [polymarket-crossing-experiment] 2026-08-31 — LIVE and CORRECT, but it has no test case yet

**Deployed `0fc174c6`, live 03:48:28Z. It fired on all three pending orders at
03:50:47:**

    tsc-sea-lec-rom-2026-08-31-2pt5  quote=0.48 snapped=0.48 crossed=0.49  tick=0.01
    tsc-bun-scp-scf-2026-09-05-2pt5  quote=0.44 snapped=0.44 crossed=0.45  tick=0.01
    tsc-epl-ast-ars-2026-08-31-2pt5  quote=0.48 snapped=0.48 crossed=0.49  tick=0.01

**AND NOTHING WAS SUBMITTED.** `EXECUTED ... positions=17 placed=0 filled=0
duplicates=3 retried=13`. The three resting orders HOLD THEIR POSITION KEYS, so
each crossed price was computed and then discarded as a duplicate. Predicted
before the deploy, and it is why the run is INCONCLUSIVE rather than negative.

**THE CODE IS PROVEN; THE HYPOTHESIS IS NOT TESTED.** Crossing arithmetic is
confirmed correct on three real orders. Whether a crossed price FILLS is still
unknown, because no crossed order has ever reached the venue.

**TO GET THE READING — cancel the three resting orders.** The venue's own Orders
screen has a Cancel button per row (user screenshot). Cancelling frees the
position keys, and the next tick re-places them at 0.49 / 0.45 / 0.49 instead of
0.48 / 0.44 / 0.48. Then:
    fills   -> size sits one tick above; PRICE was the problem
    rests   -> no book exists pregame; the fix is placement TIMING, not price

A `cancel_order` adapter exists (`3170db13`) and is NEVER CALLED, so this is a
human action tonight, not an automated one.

**DIAGNOSTIC THAT EARNED ITS KEEP:** the watcher logged `price evals since
deploy=0` for the first three checks. Without that counter, three minutes of
silence would have read as "crossed and did not fill" when the order path simply
had not ticked since the reboot.

## [polymarket-pregame-orders-rest] 2026-08-31 — THREE pending orders, ALL pregame, ALL bid AT the quote

**USER SCREENSHOT of Polymarket's own Orders screen, 03:2xZ**, corroborated
against our logs. Three PENDING, every one a SOCCER TOTAL on a fixture that has
not kicked off:

    Buy Over 2.5   Aston Villa v Arsenal   17.37 @ 48c   $8.34   Until Cancelled
    Buy Under 2.5  US Lecce v AS Roma       5.97 @ 52c   $3.10   Until Cancelled
    Buy Over 2.5   SC Paderborn v Freiburg 27.97 @ 44c  $12.31   Until Cancelled

**"Until Cancelled" is the venue's own UI confirming `goodTillTime=None`** —
independent corroboration of the API measurement.

**WE ARE BIDDING EXACTLY THE VENUE'S QUOTE, not under it.** Measured at our last
evaluation of each:

    tsc-sea-lec-rom-2026-08-31-2pt5   quote 0.48  sent 0.48  snapped=False  Under
    tsc-bun-scp-scf-2026-09-05-2pt5   quote 0.44  sent 0.44  snapped=False  Over

The 52c shown for lec-rom is the NO-side display complement of our 0.48, not a
different price. All three orders ARE tracked in our ledger (the third is
`tsc-epl-ast-ars-2026-08-31-2pt5`, order C6SRM9D8MKDN) — no ledger gap.

**THE PATTERN IS NOW CONSISTENT ACROSS EVERY ORDER WE HAVE OBSERVED:**

    PREGAME market   ->  rests, cum=0, never touched   (3 of 3 pending)
    LIVE/PAST market ->  fills                          (8 of 8 settled)

That is the peer's TIME-TO-EVENT hypothesis, and it has survived every test that
killed the others: tick floor, stale ask, bidding a mid, our own cancel loop,
market close, venue expiry, insufficient collateral, restart/OOM, deploy.

**STILL INFERENCE, AND THIS IS THE LIMIT:** we cannot see the order BOOK. The
slate gives ONE price per outcome, not depth. "The quote exists but no size sits
behind it pregame" explains everything observed and remains untested, because
nothing we have reads depth.

**THE EXPERIMENT THAT WOULD SETTLE IT** is a live-money change and needs a
decision: bid ONE TICK ABOVE the quote on pregame markets. If size exists just
above, it fills; if nothing fills at any price pregame, the market genuinely has
no book yet and the fix is placement TIMING, not price.

## [polymarket-fill-time-to-event] 2026-08-30 — the leading hypothesis is TIME TO EVENT, not liquidity at our size

**Raised by `polymarket-yes-leg-binding` off the `ORDER_STATE` instrument, and it
is better than my own.** n=2 resting vs 8 settled, and the separation is on the
market's DATE, not its price:

    RESTING (2, both cum=0 NEVER TOUCHED)   2026-08-31 and 2026-09-05
    SETTLED (8)                             7 past, 1 today

Confirmed against the board: `tsc-sea-lec-rom-2026-08-31-2pt5` is ROM@LEC
starting 2026-08-31T16:30Z, and `tsc-bun-scp-scf-2026-09-05-2pt5` is SCF@SCP
starting 2026-09-05T13:30Z — **both PREGAME**, one five days out. Every fill was
on a live-or-finished market. A Bundesliga total five days away plausibly has no
resting size because nobody is trading it yet.

**This fits my own counter-example better than size does.** `sea-tor` filled
11.17 at 0.435 while `lad-det` rested at 10.66 — near-identical size, opposite
outcome, which "no liquidity at our quantity" cannot explain and time-to-event
can.

**AND I CAN NO LONGER TEST IT ON THAT PAIR.** Both MLB fixtures have aged off the
board, the same way KC@CLE did, so their kickoff times are unavailable. That
check is gone; it needed to be run while they were live.

**MY LIQUIDITY HYPOTHESIS IS NOT DEAD, IT IS CONFOUNDED.** Every untouched order
in this sample is on an unplayed market, so the sample cannot separate the two.
n=2 is not a rate and neither of us is claiming it is.

**THE DISCRIMINATING TEST, needing no new code now `ORDER_STATE` is live:**
bucket `cum==0` resting orders by HOURS TO COMMENCE. If never-touched
concentrates far from kickoff and fills concentrate near it, the fix is WHEN we
place, not what we price. **If untouched orders appear at t-30min too, the
liquidity story survives and time-to-event is dead.** Run it on a full slate, not
on tonight's two.

**IF IT HOLDS, it reframes the original complaint** ("barely placing orders, and
the ones placed aren't processed"): we would be placing into books that do not
exist yet, and the remedy is placement timing rather than pricing, sizing, the
venue join, or the tick logic — all four of which have now been eliminated by
measurement.

## [polymarket-order-fills] 2026-08-30 — four causes REFUTED; fills are mostly fine

**5 of 7 Polymarket orders FILLED today.** The two that did not (`lad-det`,
`phi-laa`) ended `order_state_canceled` with 0 contracts — CANCELLED, not
resting. The premise "we bid the ask and never fill" was overstated.

**Four proposed causes are refuted by measurement, not argument:**
- tick-size floor — 12 of 12 quotes on-grid post-deploy, snap never fired. The
  submit-time quote for `lad-det` was 0.51 and we sent 0.51; the 0.515 was read
  30 minutes later. My claim, retracted. The fix is a NO-OP and stays only
  because the slippage guard now gates the SENT price.
- stale ask — 44s old at submit.
- bidding a mid — `prices[]` sums 1.005–1.030 over 8 binary markets: an ASK.
- "orders rest forever" — they are cancelled, not resting.

**Still unexplained:** why two orders were cancelled. `ORDER_STATE` logging of
`cumQuantity`/`leavesQuantity` shipped (`bf1dd290`) and HAS NOT BEEN READ yet.
That is the next reading.

**Why the board is game-totals only** — four separate limits, only one now lifted:
- h2h: FIXED by `8b0d27df`, verified live 19:54:08 (`yes_leg_index=0 agree=True`).
  Not yet proven to pick the right SIDE — `yes_leg_index=0` equals the old
  positional answer; the discriminating case needs `yes_leg_index=1`.
- props: refused BY DESIGN in `polymarket_board_join.py` — a prop priced by a
  guessed player token is a real order on the wrong person.
- spreads: **THERE IS NO SPREAD DEFECT. The question was malformed and the error
  was mine.** I said "71 board spread rows reach ORDER_PATH zero times" and built
  a day of tracing on it. Those 71/65 come from `SPREAD_SIGN_AUDIT`'s
  `board_spread_rows`, which counts ODDS-BOARD rows (of `board_rows=1230`) across
  all sports. They are NOT portfolio candidates.
  MEASURED 2026-08-30T21:25Z on `/api/portfolio/live?all_dates=1`, unfiltered:
  the ENTIRE portfolio holds **1 spread row** -- mlb, `KC@CLE away 2.5`, venue
  KALSHI, ticker `KXMLBSPREAD-26AUG301340KCCLE-CLE3`, and it PLACED AND FILLED.
  All markets in the portfolio: totals 12, earned_runs 4, spreads 1, and one each
  of four prop types.
  So the portfolio selects almost no spreads, and the one it selected succeeded.
  That is a SELECTION outcome (edge/threshold), not a plumbing failure, and no
  part of the venue join, the tick logic or the order path is implicated.
  A cheap follow-up IF spread volume is wanted: ask why the ranker emits ~1
  spread candidate a day against 65 board rows. That is a modelling question.
- spreads, SUPERSEDED TRACE (the join mechanics below are accurate; both
  conclusions I drew from them were not). Earlier "the join never matches them"
  was WITHDRAWN
  -- it rested on ONE fixture that had already left the slate.
  KC@CLE started 18:40Z. Its TOTALS resolved fine at 19:05/19:10/19:17Z, and the
  spread `no_venue_ticker` drops are all 19:33-20:24Z, i.e. AFTER it aged out.
  Confirmed 21:15Z: `?slug=kc-cle` now returns `matched=0` for spreads AND for
  totals AND for h2h -- the whole fixture is gone, so a zero there says nothing
  about spread coverage. The TOTALS control is what caught this; without it the
  zero reads as "the venue lists no spread".
  A game that has started dropping out of the slate is CORRECT behaviour, so
  there may be no spread defect at all.
  WHAT IS ESTABLISHED: the venue carries orderable, correctly-signed MLB spreads
  for LIVE fixtures -- `asc-mlb-lad-det-2026-08-30-neg-1pt5 line=-1.5
  orderable=true`, plus pos-1pt5/neg-2pt5/pos-2pt5 (`?slug=lad-det` -> matched=4,
  which also proves the filter works).
  TO SETTLE IT: catch a board spread row and a live venue fixture at the SAME
  moment. No Polymarket-scoped spread reached ORDER_PATH in the 90 min to 21:10Z,
  so it could not be tested then. The tooling now exists and is verified.
  (Superseded detail below is kept only for the join mechanics it records.)
- spreads, ORIGINAL TRACE (mechanics still valid, CONCLUSION withdrawn):
  The venue carries 200 `mlb|spreads` (1,900 spreads overall, from
  `/api/ops/polymarket/slate`). Spreads DO reach `ORDER_PATH` -- 9 times in 12h,
  correcting an earlier "zero" that came from a 6-tick window -- and every one is
  dropped `no_venue_ticker`, i.e. the JOIN produced no slug.
  `spread_side_needs_verified_team_mapping` fires ZERO times, so we never even
  build a candidate for the order-time sign gate to refuse: the drop is at the
  join's EXACT signed line match (`abs(candidate.line - board_line) > 1e-9`),
  upstream of it. `POLYMARKET_BOARD_JOIN` (refresh-worker, NOT live-odds-worker)
  matches 48 of 1197 board rows, with `no_matching_polymarket_market: 140`.
  `SPREAD_SIGN_AUDIT` -- the instrument that would settle whether the venue's
  `pos`/`neg` means home or away -- reports `fixtures=0 rate=None
  verdict=NON-IDENTIFYING` and has never identified anything.
  CORRECTION: I reported that endpoint as "aggregates only, rows:0". WRONG --
  the key is `samples`, not `markets`/`rows`, and I read the wrong field. It
  returned rows all along.
  What it could NOT do was aim: `?league=mlb&market=spreads` capped at 25
  samples in slate order, all `hou-nym`/`lad-det`/`tex-mil`, so the fixture
  being diagnosed was neither present nor absent. `?slug=` and `?limit=` now
  exist, with `matched_samples`/`samples_truncated` (`508a7e79`) -- NOT YET
  DEPLOYED, web still runs 165c448f.
  Already shown by the un-aimed sample: `asc-mlb-<fixture>-2026-08-30-neg-1pt5`
  carries `line=-1.5 orderable=true`, so a board row at `home -1.5` is NOT
  missing for want of a market at that line. The open question is now narrow and
  answerable: is the KC@CLE fixture in the venue's spread list at all? One call
  to `?league=mlb&market=spreads&slug=kc-cle` settles it once deployed.
- alt/period totals: the venue carries them (`tsc-...-1q-17pt5`); we never
  attempt them. UNTRACED.

**`not_found` latch:** live execution was halted on BOTH venues from 19:47:34Z
by one order with no venue id. Fixed correctly by `dd33c865` (per-order read;
three refusing paths keep blocking). My `63661af1` auto-reject was UNSAFE and is
reverted (`ef0d2d47`) — absent from the OPEN book is not absent from the venue.

﻿

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
