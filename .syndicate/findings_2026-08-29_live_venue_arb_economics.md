# Live-venue arb economics — 2026-08-29, lane `live-venue-order-placement`

> Everything below was READ FROM THE VENUE or from our own production ledger,
> from a LOCAL session with full egress. Nothing is inferred from a cloud
> sandbox, and nothing is taken from a fee explainer. No order was placed.

## Headline

**In-play is where cross-venue arb is structurally viable, and the old detector
could never have found it.** Two independent measurements:

1. Kalshi's real fee is quadratic and MLB runs at HALF rate, so the break-even
   raw gap on a two-leg pair is **0.52c–1.11c at the tails** and 3.38c at even
   money — against a detector threshold of a flat **4.00c at every price**.
2. In-play MLB moneylines **live at the tails**. 5 of 7 games in progress at
   22:02Z had a side at >= 0.90; pregame lines cluster at 0.40–0.60.

So the flat threshold sat above MLB break-even at EVERY price, and the market
regime where arb is cheapest is exactly the one nobody was scanning.

## 1. Kalshi trades in-play, with real liquidity `[22:02Z]`

`status=active` right through the game. `close_time` sits ~3 days out;
`occurrence_datetime` is expected game END, not start — a market whose
`occurrence_datetime` is future but whose start (end − 3h) has passed is
in-play. 14 of 76 open `KXMLBGAME` markets qualified.

    KXMLBGAME-26AUG291507SEATOR-TOR   0.74/0.75   vol24 904,281   OI 558,549
    KXMLBGAME-26AUG291605MIAWSH-WSH   0.94/0.95   vol24 804,405   OI 524,743
    KXMLBGAME-26AUG291605AZSFG1-AZ    0.63/0.68   vol24 418,031   OI 414,921

Near-$1M notional turnover on a single MLB moneyline. Prices moved between two
reads four minutes apart (TOR 0.73/0.74 -> 0.74/0.75; AZ 0.69/0.70 -> 0.63/0.68),
which is the direct evidence that these reprice in-play rather than being stale
pregame books left open.

**Every in-play spread observed was 1 cent.**

## 2. Kalshi publishes its own fee parameters. We were not reading them.

`GET /trade-api/v2/series/<ticker>` carries `fee_type` and `fee_multiplier`.
Read live across the thirteen series this platform trades — **four distinct
combinations**, not one:

    KXMLBGAME     quadratic_with_maker_fees  0.5    KXNFLGAME    ..._maker_fees  1
    KXMLBTOTAL    quadratic                  0.5    KXWNBAGAME   ..._maker_fees  1
    KXMLBSPREAD   quadratic                  0.5    KXWNBATOTAL  quadratic       1
    KXMLBKS       quadratic                  0.5    KXNBAGAME    ..._maker_fees  1
    KXMLBERA      quadratic                  1      KXNCAAFGAME  ..._maker_fees  1

**Every MLB game/total/spread/K series is HALF RATE.**

### The rate is measured off our own fills, and the reading is not circular

`fees_dollars` on 27 real Kalshi fills (`/api/portfolio/live?show=all`),
contracts recovered as `fill_stake_dollars / fill_price`, implied rate
`fees / (C*P*(1-P))`:

    21 fills, fee_multiplier 0.5  ->  0.0350   (= 0.07 * 0.5)
     4 fills, fee_multiplier 1.0  ->  0.0700   (= 0.07 * 1.0)
     2 fills                      ->  0.0000   (both `quadratic` series; maker)

It DISCRIMINATES — two multipliers, two rates, the expected 2:1 ratio. Checked
for circularity before being trusted: `fees_dollars` is populated in
`kalshi_orders._FEE_FIELDS` from the venue's own `taker_fees_dollars` /
`maker_fees_dollars`, and nothing in this repo computes a fee from a rate.

### The rounding is to a HUNDREDTH of a cent, not to a cent — 18/18

Every third-party source says "rounds up to the next cent". Tested as a
discriminating comparison rather than assumed:

    ceil to 4 decimal places   18 / 18 exact
    round to 4 decimal places   9 / 18 exact

e.g. 19 contracts at 0.53, multiplier 1.0: raw 0.331303, observed **0.3314**.
Whole-cent rounding overstates an order's cost by up to 0.9c, which on a 1-2c
arb margin is the entire decision.

## 3. Break-even table — what a pair actually has to clear

Kalshi leg at price p, Polymarket leg at ~(1-p), Polymarket priced at its
PESSIMISTIC bound (see §4):

    kalshi p    MLB (mult 0.5)    full rate (1.0)
      0.50          3.38c              4.25c
      0.60          3.24c              4.08c
      0.70          2.84c              3.57c
      0.80          2.16c              2.72c
      0.90          1.21c              1.53c
      0.94          0.76c              0.96c
      0.97          0.39c              0.49c

`DEFAULT_FEE_BUFFER = 0.04` demanded 4.00c at every price. **Above MLB
break-even everywhere on the board.** The detector was not conservative on MLB;
it was structurally incapable of reporting a profitable pair.

## 4. The Polymarket leg is a BOUND, and it dominates the cost

`fees_dollars` is null on **13 of 13** filled Polymarket orders. The per-market
`feeCoefficient` exists on the payload but its units have never been observed
against a real trade. So `venue_fees.polymarket_fee_dollars` REFUSES, and
`polymarket_worst_case_fee_dollars` supplies a deliberately expensive stand-in
(0.10 vs Kalshi's measured 0.07).

**At even money, two thirds of the modelled cost is the number we cannot read.**
Measuring Polymarket's real fee is worth more than any further precision on
Kalshi's — it is the single highest-value next measurement in this lane.

## 5. In-play census — the tails are where the games go `[22:02Z]`

14 in-play `KXMLBGAME` markets, all 1c spreads:

    AZ  0.95/0.96  be 0.52c      COL 0.59/0.60  be 3.24c
    KC  0.93/0.94  be 0.76c      ATL 0.41/0.42  be 3.29c
    WSH 0.93/0.94  be 0.76c      SEA 0.14/0.15  be 1.72c
    NYM 0.92/0.93  be 0.88c      TB  0.08/0.09  be 1.11c
    SD  0.90/0.91  be 1.11c      HOU 0.07/0.08  be 0.99c
    TOR 0.85/0.86  be 1.63c      CLE 0.06/0.07  be 0.88c
                                 MIA 0.06/0.07  be 0.88c
                                 SF  0.04/0.05  be 0.64c

**5 of 7 games had a side at >= 0.90.** A pregame moneyline sits at 0.40–0.60
where break-even is ~3.3c; a game two hours in has resolved toward a tail where
break-even is under 1c and Kalshi's own spread is 1c. The user's instinct that
live markets are the opportunity is correct — but the mechanism is FEE
GEOMETRY, not model edge.

## 6. What is still blocking execution

- **Polymarket refuses every moneyline** (`team_side_needs_verified_yes_leg`,
  live since 2026-08-28T15:06:23Z; wrong on 3 of 8 settled). An arb is a
  moneyline trade, so the Polymarket leg cannot be placed today. Evidence half
  now shipped — see the handoff.
- **The Polymarket slate is not published to web** (`/api/ops/artifacts/export
  ?pattern=*polymarket*` -> `count: 0`, unchanged since 08-26), so the
  Polymarket side of any arb measurement can only run on the worker.
- **`#600`** (execution ledger read-modify-written by two services with no
  lock) is landed and NOT deployed. A fast in-play placement cadence hammers
  exactly that race.
- **No two-leg executor exists.** A one-sided fill is a naked position, not an
  arb, and neither venue's order module is wired to the detector.

## 7. What this does NOT say

It says nothing about model edge. `live-game-line-projection` (CLOSED
2026-08-29) measured the live model TRAILING the market on 8 of 9 scored dates,
and a prior live-edge attempt produced fabricated edges twice the size of real
ones. **Arb viability is model-independent and does not license live
model-driven placement.** Those remain separate questions.

---

# CORRECTION + THE MEASUREMENT, 2026-08-29 ~22:1xZ

## I WAS WRONG: the Polymarket slate IS reachable from web, and I repeated a documented trap

**RETRACTED from §6 and from `state.md`:** *"The Polymarket slate is not
published to web (`export?pattern=*polymarket*` -> `count: 0`)."*

`count: 0` on the artifacts export does **not** mean the artifact is
unreachable. `ops.py:450`'s own docstring records exactly this, measured
2026-08-27: both services run `SYNDICATE_REFRESH_STATE_BACKEND=keyvalue`, so
`persist_game_slate` writes to the KEYVALUE STORE and never to disk, while the
export scans DISK. *"The artifact was already reachable from web the whole time;
what was missing was a reader."* `/api/ops/polymarket/slate` returns
`count: 17241` right now.

This is the `keyvalue_artifact_split_blinds_guards` trap, which I had on file
and walked into anyway. **A zero from a reader is a fact about the READER until
you have checked what it reads.** I then built a recommendation on top of it
(a worker-side probe, or "publish the slate") — both unnecessary.

Credit: peer lane `venue-join-refusal-visibility` flagged that
`/api/ops/polymarket/slate` had answered venue questions all session without
credentials. I verified it rather than taking it, and they are right.

## THE MEASUREMENT THE LANE OWED — RAN FROM WEB, NO CREDENTIALS, NO PROBE

`/api/board/layer2-shortlist` carries **both venues' prices on the same row**
in `quote.book_prices`, so a same-instant cross-venue read needs one HTTP call.
Board `written_at: 2026-08-29T21:56:11Z`, 1,195 rows.

    per-row venue coverage   both 19 | kalshi_only 17 | poly_only 28 | neither 1,124
    complementary cross-venue pairs formed                              12
    pairs with POSITIVE net edge after real fees                         0

### The zero is NOT a fee problem. The venues agree.

    best raw edge across all 12 pairs          +0.00c
    ...with a FREE Polymarket (fee = 0)        -0.87c   still negative

So even setting the Polymarket cost to zero, nothing clears. The two venues
price these markets to within a cent of each other, and Kalshi's own MLB fee
alone exceeds the disagreement. **Measuring Polymarket's real fee would not
change this verdict on this sample** — it remains the right fix for other
reasons, but it is no longer the thing standing between us and an executed arb.

### ALL 12 PAIRS ARE PREGAME AND AT EVEN MONEY — the worst possible regime

Fee on every pair clustered at ~3.35c, the even-money peak of the parabola.
The tail regime, where break-even is 0.52-1.11c, contributed **zero pairs**.

### WHY: the coverage overlap fails exactly where the economics work

28 live Polymarket rows exist. **All 28 have `sides=2` on the board and
`other_side_has_kalshi=False`** — Polymarket quotes one side, Kalshi does not
quote the opposite side of that same market, so the pair can never form. All 28
are `totals`, and **16 of them sit at the tails** (>=0.90 or <=0.10), which is
precisely the regime where a 1c gap would be profitable.

## WHAT THIS CHANGES

**The binding constraint is venue COVERAGE OVERLAP at the tails — not fees, not
the YES-leg binding, and not the missing two-leg executor.** Building an
executor now would be building a consumer for an empty set.

Revised order of work:

1. **Find out why Kalshi's opposite side is absent on live totals.** Line
   mismatch (Kalshi's ladder vs Polymarket's) is the leading candidate and is
   cheap to check — `KXMLBTOTAL` strikes are integers/halves and Polymarket's
   `line` may not land on them. If Kalshi simply does not list that strike, the
   pair is structurally impossible and cross-venue totals arb is dead at the
   tails; if it is a JOIN gap, it is recoverable and it is the whole
   opportunity.
2. Only then revisit the executor.

**UNCHANGED AND STILL TRUE:** the fee work stands on its own (18/18 real fills;
`DEFAULT_FEE_BUFFER` was above MLB break-even at every price). It is what made
this measurement interpretable — a flat 4c buffer would have reported the same
zero and taught us nothing about why.

## CAVEAT ON THE INSTRUMENT

`quote.book_prices` is a board QUOTE SNAPSHOT (`book_age_seconds` ~294s on the
sampled row), not a firm ask. Any positive result would have been a CANDIDATE
requiring a live ask re-read before execution — which `_kalshi_price_for`
already does at submit. A zero on a snapshot is weaker evidence than a zero on
live asks, and n=12 is small: **this is "no arb on tonight's 12 observable
pairs", not "no arb between these venues".**

---

# THE MISSING KALSHI SIDE — ANSWERED, AND IT UNCOVERED A LIVE WRONG-PRICE `[2026-08-29 ~22:3xZ]`

## Direct answer: it is BOTH, 6 join gap / 7 venue gap — and the question turned out to be moot

For the 13 live `(game, line)` totals combos Polymarket quoted, asked directly
of the venue (`KXMLBTOTAL`, open markets, unauthenticated):

    COLATL  7.5   Kalshi lists it (-8,  0.06/0.16)   JOIN GAP, recoverable
    HOUNYM 10.5   Kalshi lists it (-11, 0.07/0.09)   JOIN GAP, recoverable
    HOUNYM  7.5   Kalshi lists it (-8,  0.47/0.48)   JOIN GAP, recoverable
    AZSFG1  7.5   Kalshi lists it (-8,  0.48/0.49)   JOIN GAP, recoverable
    AZSFG1  8.5   Kalshi lists it (-9,  0.31/0.32)   JOIN GAP, recoverable
    KCCLE  11.5   Kalshi lists it (-12, 0.12/0.13)   JOIN GAP, recoverable
    KCCLE   9.5   NOT listed — ladder floor 10.5     VENUE GAP (settled)
    SDTB   7.5/8.5/9.5/10.5  NOT listed — floor 13.5 VENUE GAP (settled)
    SEATOR  8.5/9.5           no open markets        VENUE GAP (game FINAL)

**Kalshi prunes in-play total strikes as runs accumulate.** SD@TB has 13 runs
and its ladder floor is 13.5; KC@CLE has 10 and floors at 10.5; MIA@WSH has 8
and floors at 8.5. Not an exact rule — HOU@NYM (6 runs) still lists 5.5 and
AZ@SF (6) lists 4.5, so pruning lags — but the direction is clear and it is
correct behaviour: a decided strike has nothing to trade.

So **~46% of the live pairs are recoverable by fixing the join**, and the rest
are structurally impossible.

## BUT: the Polymarket side of those live rows is CORRUPT, so no pair was ever real

Computing the net edge on the 6 recoverable combos returned **+10.93c to
+84.75c per contract**. An 85% risk-free return on a market with ~$900k daily
turnover does not exist. That was the tell, and it was checked instead of
reported.

**26 of 28 live Polymarket totals quotes on the board are SHARED ACROSS GAMES,
keyed on the LINE and carrying no game identity:**

    over  7.5 @ -400   on 4 games: AZ@SF, COL@ATL, HOU@NYM, SD@TB
    under 7.5 @ +344   on the same 4
    over  8.5 @ +1233  on 3 games   over 9.5 @ +1900  on 3 games
    over 10.5 @ -6567  on 2 games

**IMPOSSIBILITY CHECK (the falsification test):** COL@ATL is 1 run in the 7th,
so over 7.5 is worth ~2% (Kalshi: 0.08). SD@TB is 13 runs, so over 7.5 has
ALREADY WON — 100%. Both carry `-400` (=80%). One price cannot be both. This is
a join defect, not a market.

**PREGAME rows are unaffected** — BAL@ATH 9.5, PHI@LAA 7.5/8.5, TEX@MIL 8.5 all
carry prices unique to their game. The collapse is on the LIVE path only, which
is exactly the path this lane exists to build on.

This is the defect `venue-quote-line-join` recorded as UNFIXED — *"a TOTALS key
names no GAME"* — previously seen on 672 soccer quotes collapsing to six keys.
Same class, now measured on MLB, live, with a signature that identifies it in
one read.

## BLAST RADIUS — it is the price the board presents as best

**`best_any_book` is `polymarket` on 28 of 28 live totals rows**, i.e. the
fabricated cross-game quote is the one the board holds up as the best available
price. `model_edge_pct` reaches 14.92 on rows priced off it.

MITIGATING, and it is why this is a hazard rather than an incident: `ev_pct` on
these rows sits at -0.99 to -1.40, so they are not surfacing as +EV bets; and
the ORDER path does not read `book_prices` — `execute_portfolio.
_polymarket_resolve_market` prices from the SLATE row, which is per-market and
not affected. **No order has been priced off these numbers.** But any price
shopping, any "best book" display, and any future consumer of `book_prices` on
a live row is reading another game's price.

## WHAT THIS CHANGES FOR THE LANE

The ordering from the previous entry is superseded:

1. **`venue-quote-line-join`'s totals key must name the game.** Until it does,
   every live Polymarket totals number on the board is untrustworthy and no
   cross-venue measurement on live totals means anything. This is now the top
   item, and it is a correctness defect independent of arb.
2. Then the Kalshi live-totals join gap (6 of 13 combos), which is real and
   separately worth fixing.
3. Only then re-run the arb measurement on live totals.
4. **Live MONEYLINE remains genuinely unexplored** — Kalshi quotes tail
   moneylines in play (verified: 14 markets, 0.04-0.96, all `active`), and the
   board's 5 Polymarket h2h rows are all pregame. That path is blocked by the
   YES-leg refusal, not by this defect.

## METHOD NOTE

The +84c figure was produced, recognised as impossible, and traced to its cause
before being reported. The recognition came from a sanity bound (an 85%
risk-free return cannot coexist with $900k of daily volume), not from the
arithmetic — the arithmetic was correct and the INPUT was wrong. Recorded
because this is the same shape as the backed-out live-edge attempt: fabricated
numbers, larger than real ones, sorting to the top.

---

# `#603` FIXED — the totals key names the game `[2026-08-29, USER OVERRIDE to take the files]`

**LANDED ON `main`, NOT DEPLOYED** (user instruction). So production still
carries the defect; this is code on the branch, not a production reading.

## The change, in three parts

1. **`quote_key(sport, market, side, line, game=None)`** — optional trailing
   `|@<game>` term. Absent `game` produces byte-identical output to before.
2. **`game_token(sport, home, away)`** — both clubs through `canonical_team`,
   **sorted** so home/away confusion cannot break the join, `None` if either is
   unresolvable (no raw-string fallback — that is how the two halves of a join
   end up on different vocabularies).
3. **A match-time rejection in the fan-in.** A quote whose `game` names a
   DIFFERENT fixture is refused and counted (`cross_game_rejected`), even when
   its key matched.

## Three design decisions, each forced by evidence rather than taste

**ROLE-KEYED MARKETS ONLY (`totals`, `spreads`, and their `_alt` variants).**
h2h is deliberately left alone: `mlb|h2h|chicago cubs` names a CLUB, and a club
plays one game a day, so it cannot collide across fixtures. That is exactly what
production showed — all 26 shared quotes were TOTALS, while every Polymarket
h2h row carried a price unique to its game. Qualifying h2h would have added a
redundant key to every moneyline row and fixed nothing. **This scoping took the
regression from 11 failing tests to 3.**

**THE ROLE KEY STAYS FIRST; the qualified key is APPENDED LAST.** Written the
other way first, and it broke eleven tests — two of which assert `keys[1]` /
`keys[2]` by POSITION, and several of which exist to assert "the role key is
tried FIRST and unchanged, so every match that worked before still works".
Ordering buys nothing: the match loop rejects a wrong-fixture quote and falls
through, so a bare hit lands on the qualified key on the next iteration. Same
behaviour, one fewer invariant broken.

**ONE QUOTE PER SIDE, keyed qualified — not two.** The first version emitted
both a qualified and a bare quote so a teamless board row would still match.
The tests were right to reject it: it doubled every count in the adapter's
contract, and the coverage it bought is coverage we should not want. If the
BOARD cannot name the fixture, nothing can verify the price.

## The coverage trade, stated rather than discovered later

**A totals row with no `home_team`/`away_team` is no longer priced by
Polymarket.** It goes unmatched instead of taking whichever fixture's quote was
in the pool. Pinned by
`test_a_totals_row_that_cannot_name_its_game_is_not_priced`. Real board rows
carry both teams, so the production population should be small — but it is a
loss and `stamped` may fall.

## What is NOT fixed

- **Only Polymarket names its game.** Kalshi, OddsAPI and Novig still emit bare
  keys, so their quotes can still cross games on a live row. The rejection
  check cannot help — it only fires when a quote NAMES a different fixture, and
  theirs name none. Converting them is the remaining work: Kalshi needs
  `match_event_blob` against the schedule (its `classified` carries no teams for
  a total), which is a bigger change than this one.
- **Doubleheaders.** Two games between the same clubs on one date share a token
  and the pool is only date-scoped. Narrowed from "any game sharing a line"
  (four at once, measured) to "the two halves of a doubleheader" — not closed.
  Neither venue can distinguish them either: Polymarket's slug carries the date
  and no game number. AZ@SF and BOS@NYY both played doubleheaders that day.

## Verification

`247 passed` across the seven venue/join suites, against a **measured baseline
of 235 passed / 0 failed** taken with the change stashed — so every failure
along the way was mine and none was pre-existing. 12 new tests.

**No production reading exists and cannot until this deploys.** The number that
would prove it: `cross_game_rejected` > 0 on a live slate, and the board's live
Polymarket totals no longer sharing a price across games.

---

# `#603`, KALSHI HALF — its quotes name the game too `[2026-08-29 ~23:5xZ]`

**LANDED ON `main`, NOT DEPLOYED.**

## The problem Kalshi posed that Polymarket did not

Polymarket's slug carries both clubs (`aec-mlb-chc-ari-...`), so its adapter
could name the fixture from data it already held. **Kalshi cannot.**
`classify_market` returns market/side/subject/line and NO teams for a total.
The only game identity is in the TICKER, as a run-together blob:
`KXMLBTOTAL-26AUG251840BOSMIA-7` -> `BOSMIA`.

`event_blob_from_ticker`'s docstring refuses to split that blob, and is right
to: club codes run 2-4 characters, nothing in the string says where the
boundary falls, and "a wrong split pairs a bet with the wrong game, which is
the one failure this whole module is built to prevent". `match_event_blob`
inverts it — every legal split, each CHECKED against our own schedule.

So naming a Kalshi quote's game needs the schedule, and the adapter did not
have one.

## How the schedule gets there without breaking the adapter contract

Adapters are called `adapter(sport, date)` and the registry is INJECTABLE —
several suites substitute it. Widening the call signature would break every
adapter and every injection site. So `games` is **bound into** the one adapter
that needs it, via `functools.partial` in `_default_adapters(games)`. An
adapter that takes no `games` is registered unchanged; a caller that passes
none gets exactly today's behaviour.

`apply_venue_quotes` derives the list from its own rows (`_distinct_games`,
one entry per event_id — the same de-duplication `kalshi_board_join.
_resolve_event` documents, because one row per market per game would make an
ordinary slate look ambiguous).

**`games` is passed ONLY when non-empty.** Several suites monkeypatch
`collect_quotes` with a three-argument stub, and an unconditional keyword turns
those into a `TypeError` that the surrounding except-clause swallows into an
EMPTY QUOTE POOL — a silent zero, which is precisely what rule 3 of that module
exists to prevent. Two tests caught it.

## THE CONVERSION SHIPPED INERT AND ONE TEST CAUGHT IT

`_kalshi_game_token` gated on `result["status"] == "matched"`. **That string
does not exist.** `match_event_blob`'s vocabulary is `ok` / `no_match` /
`ambiguous`. Every Kalshi quote fell through to a bare key and the entire
conversion did nothing.

Every other part worked — blob extracted, split resolved, teams returned,
token built. Only the guard was wrong, and an inert conversion is
indistinguishable from a correct one from the outside: the suite was GREEN,
the code was present, and it changed nothing.

What caught it was `test_a_kalshi_totals_quote_names_its_game_OFF_vs_ON`,
which asserts `on_keys != off` — the conversion must CHANGE something. An
ON-only assertion would have passed if the qualifier were unconditional; an
OFF-only one would have passed while inert. This is the standing
`presence_is_not_reachability` rule, and it earned its place again.

`ambiguous` stays a refusal: a blob that splits more than one way against the
schedule is exactly the wrong-game pairing this prevents.

## Scope, matching the Polymarket half

Role-keyed markets only (`totals`, `spreads`, `_alt`). Props are untouched —
`prop_quote_key` already names the PLAYER, a stronger identity than the game.
h2h is excluded because its side IS the club. The mirror leg (`no`) takes the
SAME game token as the primary: it is the other side of one contract on one
fixture.

Unresolvable falls back to a BARE key — never a guess, never a dropped quote.

## Verification

`322 passed` across eight venue/join/catalogue suites; `188 passed` across the
downstream consumers (`layer2_board`, `book_grid`, `clv_join`,
`position_marks`, `execution_multi_venue`, `kalshi_leg_pricing`,
`kalshi_odds_cadence`). 4 new tests.

**Still no production reading, and there cannot be one until this deploys.**

## What remains after this

- **OddsAPI and Novig still emit bare keys.** OddsAPI is the larger remaining
  exposure by volume. Its rows are per-event so the identity is available; it
  has simply not been converted.
- **Doubleheaders**, unchanged and NOT closed: `BOSMIA` appears in both halves'
  tickers and `game_token` collapses to one string either way.

---

# `#603`, ODDSAPI HALF — and it needed no schedule at all `[2026-08-30 ~00:0xZ]`

**LANDED ON `main`, NOT DEPLOYED.** All three quote sources now name the game.

## The identity was already in hand and simply unused

Where Kalshi hid its fixture in a run-together ticker blob and needed
`match_event_blob` against a schedule, the OddsAPI shard's own key names both
clubs outright:

    event_id=..|home_team=..|away_team=..|market=totals|side=over|line=7.5|book=..

`_parse_odds_history_key` is a generic `k=v` splitter, so `home_team` and
`away_team` were already sitting in `parsed_key` on every iteration. The
conversion is one call to `game_token`. **No schedule, no resolver, no
threading** — the hardest source turned out to be the easiest.

## Scope, and why h2h is excluded for a DIFFERENT reason here

Role-keyed markets only, same as the other two. But the reasoning differs and
that is worth stating, because "same scope" hides it:

- **Kalshi/Polymarket h2h** is excluded because its side IS the club, so the
  key already names the fixture implicitly.
- **OddsAPI h2h** keys by ROLE (`home`/`away`/`Draw`), so it has no implicit
  game. It is still excluded — because the BOARD's h2h rows offer a role key
  plus club and token keys that this source cannot produce, and qualifying only
  one half of that pair would break the match rather than sharpen it.

Same decision, two different justifications. Totals and spreads are the only
family where both halves key by role and the collision is real.

## Verification

`325 passed` across eight venue/join/catalogue suites, `138 passed` downstream.
3 new tests, including the discriminating pair the Kalshi half taught me to
write:

- two totals on the SAME line for DIFFERENT games now produce two distinct
  keys and two quotes (before: one key, one surviving pool entry, one price
  answering both);
- an unresolvable club falls back to a BARE key, never a raw-string token only
  one half of the join would recognise.

A note on the test itself: the patch target is `odds_control_plane`, NOT the
adapter module. `oddsapi_outcome` imports the loader INSIDE the function, so it
resolves through the source module at call time and a name bound on `adapters`
would never be consulted — a stub that silently never fires is the same
species of defect as the inert Kalshi guard.

## STATE OF `#603` AFTER THIS

| source | names its game | how |
|---|---|---|
| Polymarket | YES | slug carries both clubs |
| Kalshi | YES | ticker blob via `match_event_blob` + schedule |
| OddsAPI | YES | shard key carries both clubs |
| Novig | no | DISABLED by default (`NOVIG_PUBLIC_TIER_REFUSAL`) — its public tier is anonymised and cannot price a named bet at all, so there is nothing to qualify |

**Every source that can actually price a named bet now names its fixture.**

## STILL NOT CLOSED

- **Doubleheaders.** Unchanged. Two games between the same clubs on one date
  produce one token on every source. Narrowed from "any game sharing a line"
  to "the two halves of a doubleheader" and no further. AZ@SF and BOS@NYY both
  played one on 2026-08-29.
- **No production reading exists**, and cannot until this deploys. The number
  that proves it: `cross_game_rejected` on a live slate, and live Polymarket
  totals no longer sharing a price across games.

---

# THE PRODUCTION READING — `#603` IS DEPLOYED AND **UNPROVEN**. NOT PROVEN WORKING, NOT PROVEN BROKEN. `[2026-08-30 00:31Z]`

## Deploy

Shipped on ANOTHER lane's deploy, not mine: `venue-first-market-universe` held
the refresh-worker claim (00:16:35Z) and deployed `af535a3d8`, which is
origin/main's head and CONTAINS my work — verified by CONTENT, not ancestry
(`game_token`/`_kalshi_game_token` x9, `cross_game_rejected` x3). Live
**00:19:36.947Z**. I took no claim and triggered nothing; a second deploy would
have been a competing restart of the same service.

Service chosen by READING THE LIVE ENV, not inferring:
`SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP` is `true` on
refresh-worker, `false` on live-odds-worker and web. refresh-worker is the only
service that runs the fan-in.

## Gate

Board `written_at` **00:30:59Z** > deploy **00:19:36Z**. The pool read below was
built by the new code. The control (`00:18:41Z`) predates the deploy by 55
seconds — reading it as "after" would have been the exact false verdict the
build-stamp rule exists to prevent.

## THE READING — the collision is STILL THERE

    source       totals  live   live rows sharing a price ACROSS GAMES
    kalshi           25    19   2   over 2.5 @ -270 -> Charlotte FC@Atlanta Utd
                                                       Philadelphia Union@NY RB
    polymarket       13     7   4   over 47.5 @ +108  -> Jacksonville St, New Mexico St
                                    under 47.5 @ -113 -> the same two
    draftkings      138     0   0
    fanduel         139     0   0

CONTROL for comparison: kalshi 2 shared of 20 live; polymarket live=0.
**Kalshi 2 -> 2. No improvement.**

## WHY, measured rather than assumed — and it is TWO different causes

**1. NCAAF has no club map at all.** `_alias_map` entry counts, read live:

    mlb 38 | nfl 38 | wnba 50 | soccer 474 | ncaaf 0 | ncaab 0 | nhl 0

`canonical_team("ncaaf", "Jacksonville State Gamecocks")` -> **None**, so
`game_token` -> None, so the key stays bare and the collision survives. This
was DOCUMENTED before I started — `test_a_sport_with_NO_club_map_offers_no_
token_keys` says `_alias_map` returns `{}` for ncaaf/ncaab/nhl — and I did not
connect it to my own precondition.

**2. Soccer resolves on the BOARD side and only PARTIALLY on Kalshi's.**
`game_token("soccer", "Philadelphia Union", "New York Red Bulls")` ->
`philadelphia union+red bull new york`, fine. But Kalshi's side must resolve a
ticker BLOB, and that is where it splits:

    match_event_blob('CLTATL')  -> ok, Atlanta United FC
    match_event_blob('PHINYRB') -> no_match
    match_event_blob('PHINY')   -> no_match

So one fixture resolves and the other does not.

**3. The bare-key fallback then does exactly what I designed it to do, and
that is the hole.** A quote whose game cannot be named keys BARE and carries
`game=None`, and the rejection check passes `None` through by design — "a quote
that names none is allowed through exactly as it is today". So an unresolvable
fixture keeps the OLD behaviour, INCLUDING THE OLD BUG.

## WHAT THIS DOES AND DOES NOT SAY

**It does NOT say the fix is broken.** Every unit test passes, including the
off!=on pairs, and MLB resolves cleanly on both sides
(`atlanta braves+colorado rockies`).

**It does NOT say the fix works.** The population that would exercise it —
MLB, where the original 26-of-28 was measured and where both maps are good —
**finished for the night before the deploy landed.** Polymarket live MLB totals
went 28 (21:56Z) -> 0 (00:24Z).

**The honest state is UNPROVEN**, and the fix is INERT on every sport that was
live when it shipped. That is not a coincidence of timing I should wave away:
NCAAF and NHL and NCAAB have NO club map, so the fix can never work there until
one exists.

## THE NEXT STEP IS A DECISION, NOT A FIX

The bare-key fallback preserves coverage and preserves the bug. The two ways
out are in tension and this is the user's call:

- **Tighten:** for role-keyed markets, no game token -> NO match. Closes the
  collision everywhere immediately, and drops venue pricing on ncaaf/ncaab/nhl
  entirely plus the soccer fixtures Kalshi cannot resolve.
- **Populate:** build the ncaaf/ncaab/nhl alias maps and widen Kalshi's soccer
  codes. Keeps coverage, and the collision stays live until each map lands.

**VERIFICATION STILL OWED:** an MLB slate. The first MLB game after ~17:00Z
2026-08-30 will exercise the path the original defect was measured on. Until
then `#603` must NOT be reported as fixed in production.
