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

---

# `#603` NCAAF — resolved WITHOUT touching the reverted alias map `[2026-08-30 ~01:0xZ]`

**LANDED, NOT DEPLOYED.**

## What was asked, and why it could not be done as asked

"Populate the ncaaf alias map." That exact change was **built, measured and
REVERTED earlier the same day** (`handoff_2026-08-29_ncaaf_umass_alias_gap.md`):
it does not resolve the names anyway, and it makes `teams_match`
MAP-AUTHORITATIVE, turning `canonical_team("ncaaf","MAS")` -> `UMass Dartmouth`
from a harmless miss into a confident wrong answer. Not re-landed.

## The root, and it is more central than "the map is empty"

`_side_for_team` — the nickname/token-subset resolver every venue join leans on
— **short-circuits before its own fallback**:

    away = canonical_team(sport, resolution.get("away_team"))
    home = canonical_team(sport, resolution.get("home_team"))
    if not away or not home:
        return None

With `_alias_map("ncaaf")` at **0 entries**, both are None, so it returns before
reaching the token-subset logic that exists precisely for bare nicknames. One
empty map disables `game_token`, `teams_match`'s heuristics AND
`_side_for_team`'s fallback simultaneously.

## Why the slug tokens cannot simply be looked up

Real slugs, read from `/api/ops/polymarket/slate?league=ncaaf` (14,900 markets;
`ncaaf|totals 620`, `spreads 867`, `h2h 168`):

    aec-cfb-nmxst-flst-2026-08-29                  moneyline
    tsc-cfb-jaxst-ndkst-2026-08-29-total-26pt5     total

Against `unambiguous_team_index` (2,214 entries): `jaxst`, `ndkst`, `nmxst`,
`flst`, `sacst`, `emich` **all miss**; `hawaii` and `stan` happen to hit. And no
derivation rescues them — **`jaxst` is not even a SUBSEQUENCE of "jacksonville
state"**, because Polymarket's "jax" contributes an `x` the real name lacks.
Subsequence pair-matching against the schedule scored 2 of 4. Inventing a rule
from six examples is the trap `kalshi_board_join`'s header records costing a day.

## The route that works, and it uses only data already present

**The moneyline names its teams; the totals do not; and a game's slug token
pair is CONSTANT across its markets.** So resolve the pair ONCE from the
moneyline and let the other families reuse it:

    aec-cfb-nmxst-flst   outcomes ["Seminoles","Aggies"]  -> which board game?
    -> token-subset against each board game's two names, PAIR must match
    -> exactly one game, or refuse
    -> learn (nmxst, flst) -> event_id
    -> every tsc-cfb-nmxst-flst-* total inherits it

Matched by direct token subset, NOT through `_side_for_team` (which cannot help
here, per the short-circuit above). Measured against the live 08-29 board: **3
of 4 observed pairs resolved to exactly one game**, the fourth being a game not
on the board at all — a correct no-match.

## The identity is our own `event_id`, not a club pair

`game_token` needs `canonical_team`, so it is unbuildable for NCAAF.
`event_game_token(event_id)` -> `evt:<id>` is the one identity both halves can
agree on without a club vocabulary. It is prefixed so it cannot be confused
with a club-pair token, and it is a **FALLBACK ONLY** — club-pair is tried
first, so mlb/nfl/wnba/soccer keep exactly the keys they have today.

## KNOWN BOUNDS, pinned by tests rather than left to be discovered

- **A game with no MONEYLINE in the slate cannot be resolved.** Its totals keep
  a bare key and stay exposed. That is the pre-`#603` behaviour, not a new
  failure, but it is a hole worth counting.
- **An ambiguous pair refuses.** Two fixtures sharing both nicknames
  ("Aggies"/"Bulldogs") yield no mapping rather than a guess.

## Verification

`429 passed` across nine venue/join/catalogue suites, `119` downstream. 4 new
tests including the off!=on pair: without a schedule both games' totals collapse
onto the same keys; with one they separate into `|@evt:evt-nmxst-flst` and
`|@evt:evt-jaxst-ndkst`.

## AND THE THING THIS DOES NOT FIX, WHICH IS WHAT WAS ACTUALLY OBSERVED

The user's report was "nothing NCAAF live hits the boards". NCAAF **is** on the
board — 74 rows on 08-29, 7 live — but **0 of 74 carry `model_edge_pct`**, so
all are refused `no_model_edge_pct` before Kelly and none can ever be sized.
That is `football/pick_gate.py::_SERVING_REGISTRY`: ncaaf spread, moneyline and
total are all `servable=False`, measured 2026-08-19 clean out-of-sample — the
margin model **loses to the closing line by 3.563 points of MAE over 2,233
games (t=17.2)** and totals are 1.67x over-dispersed and were never scored
against the close. **This keying work does not move that by one row.** Lifting
that gate needs a model that beats the close, or an explicit decision to trade
one that does not.

---

# `#603` THE GRID PATH — I HAD FIXED THE WRONG FUNCTION `[2026-08-30 ~01:1xZ]`

## The finding, and it supersedes the alias-map explanation

`GRID_REPRICE` fires every board cycle. **`VENUE_REPRICE` did not appear once in
45 minutes of production logs.** They come from two different functions and I
had been reasoning about the wrong one all night.

The path that runs is `apply_venue_quotes_to_grid`, and it was doing:

    payload = collected if collected is not None else collect_quotes(sport, date, now=now)
    ...
    quote = quotes.get(str(quote_key(sport_slug, market, side_key, line)))

**No `games`. Bare `quote_key`. No `_candidate_keys`. No rejection.** And it is
this function that calls `_reprice_live_benchmark`, which writes
`cells[book][side]` -> `book_prices` — the exact write that produced the
corrupted prices.

**Every part of `#603` up to now landed on `apply_venue_quotes`, which the live
board build does not call.** The fix was inert on the only path that produces
the defect.

That, not the empty alias maps, is why the post-deploy reading was flat at
kalshi 2 -> 2. The alias gaps are real and secondary; this is primary.

**One piece of luck worth naming:** the adapters only emit qualified keys when
handed `games`, and the grid path passed none — so the deployed `af535a3d8`
could not have caused a coverage regression either. It did nothing at all.

## The rule this broke

`presence_is_not_reachability`, which I have on file in these exact words:
*"trace the route to the code, and fix the choke point all callers share, not
the one you can see."* I traced `book_prices` -> `cells` ->
`_reprice_live_benchmark` -> `venue_quote_fanin` and stopped one frame early, at
the wrong caller, because that caller's name matched what I was looking for.

## The fix

- **The schedule comes from the GRID ITSELF.** Grid rows carry
  `event_id`/`home_team`/`away_team` (`book_grid.py:573, 581-582`), so
  `_distinct_games(grid, sport)` gives the fixture list with no change to
  `layer2_shortlist.py` — another lane's file.
- **Bare key first, qualified second, rejection always** — the same order and
  the same two helpers as `_candidate_keys`, now extracted so ONE definition
  serves both callers (`_row_game_token`, `_quote_is_for_another_game`). Two
  paths disagreeing about a row's identity is a join that works on whichever
  one you happen to read.
- **`CROSS_GAME_REJECTED_GRID` is emitted** when non-zero, and
  `cross_game_rejected` is on the return. The first version of this counter
  existed only in a return value nothing printed.

## Verification

`434 passed` across nine venue/join/catalogue suites, `131` downstream. 3 new
grid-path tests.

**A fixture bug caught in the writing, and it matters.** The first grid fixture
had `best: {}`, so `sides_seen` never incremented and `repriced == 0` passed
trivially — it would have agreed with an implementation that did nothing. `best`
now carries a dict per side with a deliberately STALE `age_seconds` (9,999s), so
a legitimate quote genuinely WOULD win the freshness check and reprice. Only
then is "0 repriced" evidence of the refusal rather than evidence of an inert
test. Same species as the inert Kalshi guard, one layer down.

## STILL UNPROVEN IN PRODUCTION, AND TONIGHT'S READING IS GONE

`Jacksonville State @ North Dakota State` went **Final 7-33** — one of the two
games in the control pair. So the shared `over 47.5` group disappears on the
next rebuild whether or not anything works, and a post-deploy "0 shared" would
be unattributable. I stopped the deploy rather than spend a restart producing a
third "unproven" on a population that had already changed.

**The reading that will settle it is tomorrow's MLB slate** — both alias maps
are good there, and it is where the original 26-of-28 was measured. Two
instruments now, not one: the behavioural shared-count AND
`CROSS_GAME_REJECTED_GRID`.

---

## 2026-08-30 — CORRECTION to the entry above: my "VENUE_REPRICE never fires" was LOG TRUNCATION, not absence. The rule I wrote from it was right; the evidence I wrote it from was not.

**RETRACTED:** *"`GRID_REPRICE` fires every cycle; `VENUE_REPRICE` appeared ZERO
times in 45 minutes of production logs"* and the conclusion drawn from it, that
`apply_venue_quotes` is never called.

**What actually happened.** I queried the Render logs API with `limit=200` and
no text filter. On a service emitting thousands of lines that returns the newest
200 — so my window never contained the line I was looking for, and I read the
empty result as proof the code path does not run.

Re-queried with `text=` filtering, same window:

    VENUE_REPRICE   8 matches  00:15-01:25Z   (00:18:39, 00:30:57, ...)
    GRID_REPRICE   20 matches

**BOTH PATHS RUN.** A peer lane (`exchange-join-refusals`) cited
`VENUE_REPRICE_KEYS unmatched 2255` off the 00:53:27Z build in an unrelated
message. That number could not exist if my finding were true, so I re-measured.
Credit theirs; I would not have looked again.

**WHAT SURVIVES, stated so this is not over-retracted.** The grid path genuinely
did lack the game term, and it is the one that calls `_reprice_live_benchmark`
-> `cells[book][side]` -> `book_prices`, which is where the corrupted prices come
from. `apply_venue_quotes` stamps freshness on opportunity rows and does not
write `cells`. **So the FIX was necessary and correct; the REASON I gave for it
was false.** `0c5243b4` stands.

**THE IRONY IS THE LESSON.** The entry above states *"an absent log line is a
fact about the path, not about the clock."* Mine was a fact about my QUERY. The
rule generalises one step further than I wrote it:

**An absent observation is a fact about the INSTRUMENT until you have shown the
instrument could have seen it.** Clock, path, and query limit are three ways to
be blind, and I had already written the rule for two of them while standing in
the third.

**Practical form:** before concluding a log line never appears, either use a
`text=` filter or prove the window was not truncated — a `limit` that equals the
number of rows returned is a truncation signal, and mine returned exactly 200.

**Cost:** a wrong causal claim committed to `learnings.md`, `findings_...md` and
a commit message, live for roughly 40 minutes. No wrong code: the change it
justified was independently correct.

---

# POLYMARKET'S FEE — MEASURED, AND IT IS ZERO `[2026-08-30 ~02:2xZ]`

The measurement I had called "the single highest-value one left". It did not
need the order module fixed after all.

## Why the obvious route was blocked, and the route that worked

`fees_dollars` is null on every filled Polymarket order — `venue_order_view`
hardcodes it, and the venue's `commissionNotionalTotalCollected` never reaches
the ledger. The production log confirms the field EXISTS
(`[polymarket_us_orders] ORDERS_READ ... keys=[... 'commissionNotionalTotal
Collected', 'commissionsBasisPoints', 'makerCommissionsBasisPoints' ...]`) but
prints only the KEY NAMES, never the values.

So the fee was recovered from the **venue's own realized P&L** instead.
`venue_settlement` grades a Polymarket order from
`delta = after_realized - before_realized`, read off the venue's position row,
stored as `pnl_dollars` with `settled_by="venue"`. If a commission had been
taken, realized P&L would fall short of the no-fee expectation by exactly that.

**Circularity checked before trusting it**, the same check Kalshi's rate got:
`delta` is the venue's own realized figure, not a formula of ours.

## The result

Ten venue-settled orders, `$75.98` notional:

    implied fee (expected_no_fee - venue_pnl)   -0.0037 .. +0.0000
    total                                        -$0.0180
    effective rate                               -2.37 bps of notional

**Every value negative or zero.** A real commission is strictly positive; a
negative implied fee is contract-count reconstruction rounding. **Polymarket
took no commission on these fills.**

ONE ROW EXCLUDED, and not for being inconvenient:
`tsc-mlb-tex-mil-2026-08-29-8pt5` implied `+$0.42` and carries
`held_side: POSITION_RESOLUTION_SIDE_SHORT` on an order placed as `under` — the
`#595` wrong-side signature. Its P&L does not describe the position we think we
held, so it cannot price a fee.

## What it changes

The break-even bar for a two-leg pair, Polymarket at the old unmeasured 0.10
bound vs measured:

    kalshi p   MLB old   MLB measured
      0.50      3.38c        0.88c
      0.70      2.84c        0.74c
      0.90      1.21c        0.32c
      0.97      0.39c        0.10c

**At even money on MLB the bar falls 3.38c -> 0.88c, a 3.8x reduction.** The old
detector demanded a flat 4.00c.

**AND IT INVERTS THE PRIORITY I RECORDED.** I wrote that Polymarket was "two
thirds of the modelled pair cost at even money" and the highest-value thing to
measure. Measured, it is ZERO and **Kalshi is now the entire bar**. The test
that asserted Polymarket dominant has been inverted to assert Kalshi dominant,
so the finding is pinned rather than merely written down.

## What it does NOT change

The arb verdict on the observed sample. Best raw edge was **+0.00c** and the
best pair was **-0.87c even with a free Polymarket** — Kalshi's own fee already
exceeded the venues' disagreement. Cheaper fees make future opportunities far
likelier to clear; they do not manufacture one that was not there.

## Bounds on the claim

Ten orders, all `totals`, `$1-$9`. `commissionsBasisPoints` and
`makerCommissionsBasisPoints` are on the venue payload and are AUTHORITATIVE
where this inference is not — a different market type or a much larger order
should read the field. The population is carried in code as
`POLYMARKET_MEASURED_SAMPLE` so a caller can see how far it generalises without
reading this. `POLYMARKET_ASSUMED_WORST_CASE_RATE` is kept for callers wanting a
bound and tightened 0.10 -> 0.01.

## A bug the tests caught in my own code

`net_edge_per_contract(polymarket_fee_bound=False)` returned a net edge
IDENTICAL to the bounded one — the flag only affected the rounded
single-contract figure while the rate was always the worst case. A flag whose
name says "measured" and whose behaviour says "bound" is worse than no flag.
Fixed; the flag now selects the rate.

---

# RETRACTION: "POLYMARKET'S FEE IS ZERO" WAS WRONG. MY METHOD WAS FEE-BLIND. `[2026-08-30 ~03:0xZ]`

**RETRACTED IN FULL:** the finding above that Polymarket charges no commission,
`POLYMARKET_MEASURED_TAKER_RATE = 0.0`, the claim that Kalshi is the dominant
leg cost, and the break-even table that followed from them.

## What was wrong

I inferred the fee from the venue's realized P&L at SETTLEMENT
(`delta = after_realized - before_realized`). **Realized P&L is `(exit - entry)`
on the position, so a commission taken at FILL is invisible to it by
construction.** My ten values came out ~zero whether or not a fee was charged.

**A method that cannot return a non-zero answer has not measured zero.** I ran
the circularity check and skipped the reachability one — on the exact night I
recorded four other instances of that same class.

## Disproven on the same orders

`C60JWBG0WKDK` is IN my ten. I reported an implied fee of **-0.0023**; the venue
charged **$0.06**. Two more of the ten were also commissioned and reported ~0:
`C5Y08RVP8KDK` ($0.28) and `C5SM8P8S4KDC` ($0.05).

Credit: peer lane `unknown-submit-retry-provenance`. Their `98e103e1` removed the
hardcoded `None` and `fb749d97` printed the values, live as `219d79ca` — so
`commissionNotionalTotalCollected` became readable AFTER my measurement, which
is why my premise ("unreadable") was true when written and stale within hours.
They also had an INDEPENDENT second route: `buyingPower` 96.04765 -> 94.14995,
**-$1.8977 of real cash for a $1.8377 fill**. Two routes, same $0.06.

## The real fee

Five fills carrying `commissionNotionalTotalCollected`:

    order          contracts  price   fee    modelled@150bps
    C5Y08RVP8KDK       18.70   0.47   0.28        0.2805
    C60RZVXYJKDG        4.93   0.43   0.07        0.0740
    C60JWBG0WKDK        3.91   0.47   0.06        0.0587
    C5SM8P8S4KDC        3.40   0.47   0.05        0.0510
    C5Y0GHE4MKDE        2.38   0.44   0.04        0.0357

**150 bps of NOTIONAL (contracts x $1), flat, independent of price.**

A cost basis (3.247% of contracts x price) fits nearly as well and I first
modelled BOTH, charging the dearer. **A test rejected it**: on the 18.70-contract
fill — the one where cent-rounding matters least — notional errs $0.0005 and
cost $0.0054. Rejected on the best-resolved point, not on an average.

## The shape matters as much as the level

Kalshi's fee is a PARABOLA and vanishes at the tails; Polymarket's is FLAT and
does not. At P=0.94 Kalshi's MLB fee is 0.0020/contract and Polymarket's 0.0150
— **seven times larger**. My first correction still modelled Polymarket
quadratically, which understated the tails by an order of magnitude, and the
tails are exactly where in-play pairs live.

## Corrected break-even, MLB two-leg

    kalshi p   with 0.10 bound   RETRACTED zero   MEASURED
      0.50          3.38c            0.88c         2.50c
      0.90          1.21c            0.32c         1.81c
      0.94          0.76c            0.20c         1.70c

**My zero made the bar 2.8x too permissive at even money.** A threshold below
true break-even manufactures arbs that lose on every fill — the exact direction
this module's docstring says to round against.

## Two further defects the correction exposed

1. **The "bound" was cheaper than the measurement.** It was a quadratic while
   the fee was thought quadratic; after the shape fix it sat BELOW the real fee
   at every price (0.50 vs 1.50 per hundred contracts at even money). A worst
   case under the true cost is a trap. Now flat at 200 bps, with a test
   asserting `bound > measured` at five prices — the relationship nothing had
   asserted, which is how it survived.
2. **`POLYMARKET_MEASURED_SAMPLE` said `orders: 10`** — the fee-blind ten. Now
   the five real commissions, with the rejected basis recorded.

## What still stands

The arb VERDICT on the observed sample: best raw edge +0.00c. It fails by more
now, not less. `commissionsBasisPoints` reading `'0'` on all eight order reads
while `collected` reads `0.0600` on the SAME payload remains an open
contradiction — at least one field does not mean its name, and the peer flagged
it themselves rather than leaning on the one that suited them.

---

## The Kalshi/Polymarket IN-PLAY comparison — `venue_basis_edge` (2026-08-30)

**What it is.** A live board row's in-play exchange price against the book
consensus, net of the venue's own commission. `syndicate/features/shared/
venue_basis_edge.py`, attached per side in `apply_venue_quotes_to_grid`.

**Why it is allowed live when `market_basis_edge` is not.** `market_basis_edge`
refuses every live market and is right to: its anchor is *other books*, and once
a game starts the cross-book spread is mostly staleness (its header records ten
quotes on one line, +1200 against +175, none stale by the lag rule). This
anchors on an EXCHANGE that demonstrably trades in-play — measured 2026-08-29
22:02Z on `KXMLBGAME`, games in progress: SEA@TOR 0.74/0.75 vol24 904,281;
MIA@WSH 0.94/0.95 vol24 804,405; AZ@SF 0.63/0.68 vol24 418,031. Every observed
in-play spread was ONE CENT and prices moved between reads four minutes apart.

**That is an argument, not a measurement.** `servable` is False on every row and
there is a test pinning it. Nobody has scored venue-vs-book disagreement against
realised results, and the last unmeasured live edge that reached a picks surface
priced three props whose over had ALREADY WON at +36.5%/+32.3%/+15.8%.

### The guard this was first written WITHOUT, and it was the dangerous one

The book side can be a PREGAME capture while the venue price is live. The
difference is then two clocks, not an edge — `_reprice_live_benchmark` has the
measurement: a team three runs up in the 7th is ~0.90 live and ~0.55 to the
pregame consensus, a **35-point number shaped exactly like the finding this
module exists to surface**. The staleness FLAGS do not catch it: when every book
stopped updating at first pitch, none is stale relative to its peers.

Caught while wiring, not while writing — the attach point made the question
"which age is this?" unavoidable. Guard 5 now bounds the anchor by
`opportunity_gate.LIVE_MARKET_MAX_AGE_SECONDS`, read from there so the staleness
the board ENFORCES and the staleness it ANCHORS AGAINST cannot drift apart. 900s
is loose for baseball; it reliably excludes the pregame capture, which is the
defect that produces the 35-point number. **It should be tightened from data.**

### Ordering is the correctness, not a style choice

Both writes below the attach destroy an input the comparison needs:

1. the price reprice overwrites `side_best["age_seconds"]` with the VENUE's age —
   read after it, guard 5 gets the venue's 10s for a two-hour-old book consensus
   and passes exactly what it was written to catch;
2. `_reprice_live_benchmark` sets superseded pregame books ASIDE in
   `cells`/`consensus` — after it, on the rows where it succeeds, there is no
   independent book consensus left and the comparison is the venue against
   itself (0.00, reading as agreement).

`tests/test_venue_basis_wiring.py` pins both by asserting the refusal on a row
that reads fresh AFTER the call, and the book-side anchor on a row where the
benchmark rewrite demonstrably ran.

### Two judgement calls, both recorded

**Kalshi's series `fee_multiplier` is ASSUMED, not required.** Nothing writes it
into `kalshi_markets.json`, so refusing would have made this inert on the one
venue whose in-play depth is measured — inert-but-principled being the worse
failure, since it reads as "Kalshi has no live edges". The full 0.07 rate is
assumed; every MLB game/total/spread series is HALF rate, so the assumption can
only make an edge look SMALLER, never invent one. Rows carry
`fee_is_upper_bound: true`. Consistent with `kalshi_polymarket_arb`'s existing
`float(m.get("kalshi_fee_multiplier") or 1.0)`.

**A negative edge is displayed, not suppressed.** At an identical nominal price
the books are genuinely cheaper — the venue side costs its commission on top —
and the reason string says which side is cheaper rather than leaving it to a sign.

### Fixed in passing: a crash that predates this work

`_distinct_games` (added with `#603`, mine) did not guard against a non-mapping
grid row, while the loop it runs BEFORE does. One `None` in the grid raised
`AttributeError` and took the entire venue reprice down with it.
`test_a_malformed_grid_row_does_not_raise` was already asserting this and was
already red — reproduced with this session's work stashed, so it is not a
regression from the basis work.

### Status

Unit + wiring tests: 25 pass. Surrounding suites (fanin, grid reprice, live
benchmark, key-names-game, line join, fees, arb): 147 pass. **No production
reading yet, and no deploy.** The two numbers most likely to be wrong are
`MAX_VENUE_QUOTE_AGE_SECONDS = 45` and the 900s anchor ceiling; both are
starting positions, neither is a measurement.

---

## CLOSED: the `commissionsBasisPoints` "open contradiction" (2026-08-30)

Recorded above as *"remains an open contradiction — at least one field does not
mean its name."* **It was never a contradiction, and my own flat model is the
explanation.** Raised by session `local_c1fb3f4e`; verified here before adopting.

`commissionsBasisPoints: '0'` sits beside a real `collected` total because **a
flat per-contract fee has no ad-valorem component for a rate field to express.**
Both fields mean exactly what they say. The venue has no way to write "$0.015 a
contract" in a bps field, so it writes `0`.

`bps == 0` is evidence about the fee's **SHAPE**, never about its **ABSENCE**.

**The line that had to change was mine, in code, and it was worse than the one
flagged.** `venue_fees.py`'s module docstring still carried the RETRACTED
zero-fee finding in full — "Polymarket took **no commission**", "`polymarket_
fee_dollars` returns the measured 0.0" — while the function has returned
`0.015 * contracts` since the retraction. A reader of the module was told the
opposite of what runs, and told it in the same authoritative voice as the parts
that are true. It also called the bps fields "authoritative where this inference
is not", which at face value hands a reader a zero fee and lands them precisely
where the retracted measurement did.

Rewritten to state the fee, the shape, the retraction and WHY the old method was
wrong (realized P&L is `exit − entry`; the commission is charged at fill and is
not a term in that difference — fee-blind by construction, not merely weak).

Re-verified here rather than accepted, all four numbers:

| claim | checked |
|---|---|
| Kalshi MLB @P=0.94 | `0.0020`/contract |
| Polymarket @P=0.94 | `0.0150`/contract — 7.5x, and the tails are where in-play lives |
| bound above measurement | `0.02 > 0.015`, pinned by `test_venue_fees.py:272` |
| cost-basis rejection | 3.247% predicts `$0.1579` on the 18.70-contract fill; flat predicts `$0.2805` |

62 tests green across fees / arb / venue basis.

**Attribution, as the peer recorded it and as I confirm it:** their side
contributed the fee's EXISTENCE and an independent cash-movement route
(`buyingPower` delta); the SHAPE is from this lane's five
`commissionNotionalTotalCollected` values. Their "3.12–3.81% of fill cost" was
the artifact of dividing a flat charge by a varying cost — the spread was the
symptom, not the finding. Two independent routes, one answer.

**Standing rule this leaves behind:** a retraction must reach the DOCSTRING of
the module whose behaviour changed, not only the ledger. The constant was fixed
the same hour; the prose that explains it survived four commits saying the
opposite, and nothing was red.

---

## THE READING, 2026-08-30 03:42Z — the instrument works and it found `#603` STILL LIVE

Deploy `dep-da9q7bpf2nfc7389ug30`, commit `77e61607`, refresh-worker live
03:32:26Z (fired by `stale-row-cause-blind-spot` under their claim; one
cumulative deploy carrying three lanes). Board pool `written_at
2026-08-30T03:42:11Z`, which crosses the deploy — the build-stamp gate refused
two earlier attempts against the 03:20:09Z pool.

### The wiring: confirmed, all three hops

    rows                       809
    carrying the venue_basis KEY   809   <- the board fan-out ran on every row
    with a VERDICT (non-null)      148   <- the venue quoted this side
      pregame, routed to market_basis_edge  123
      guard4 books<3                         13
      DISPLAYABLE                             7
      guard5 pregame anchor                   4
      guard3 venue quote stale                1
      noise floor (venue and books AGREE)     0

### The finding is NOT the seven edges. It is that all seven are FICTION

**Zero rows landed in the noise floor.** Seven reached the arithmetic and seven
disagreed, six of them by more than 11 points. A live exchange and live books
tracking the same game should agree most of the time. Zero agreements out of
seven is not an edge distribution, it is a broken join — and that inference is
NOT selection-biased, because an agreeing row would have been counted as a
noise-floor refusal and none was.

`venue_ref` says what happened:

| board row | venue ticker | the fixture it actually prices |
|---|---|---|
| Phillies@Angels over 4.5 | `KXMLBTOTAL-26AUG301410CWSMIN-5` | White Sox@Twins |
| Orioles@Athletics over 6.5 | `KXMLBTOTAL-...CWSMIN-7` | White Sox@Twins |
| Tempo@Mercury under 175.5 | `KXWNBATOTAL-26AUG30LASEA-176` | LA@Seattle |
| LA Galaxy@San Diego draw | `KXBELGIANPLGAME-26SEP06BEVOHL-TIE` | Belgian Pro League, Sep 6 |
| Memphis@UNLV under 49.5 | `tsc-cfb-toledo-mst-2026-09-04-...` | Toledo@Miss State, Sep 4 |

The soccer row is the cleanest proof and needs no alias map: a DRAW at halftime
on a 1-0 scoreline priced at 0.8099, whose complement 0.1901 equals the book
consensus 0.190476 to four decimals.

### The alias-free measurement — collidability on the REF

Team-name matching is unreliable (my first pass reported 100% mismatch and was
WRONG: `Toronto`→`toro` misses `TORPHX`, a ref that is in fact correct). The
test that needs no name resolution is how many refs answer more than one
fixture, because at most one of them can be right:

    distinct venue_refs in use      35
    refs answering >1 FIXTURE       11
    rows served by such a ref      108 / 148   (73%)

      KXBELGIANPLGAME-26SEP06BEVOHL-TIE   claimed by 33 fixtures
      KXBUNDESLIGATOTAL-26SEP05SCHBMU-3   claimed by 25 fixtures
      KXBUNDESLIGATOTAL-26SEP05SCHBMU-4   claimed by 10 fixtures

One Belgian tie ticker is answering 33 fixtures across Spain, the Netherlands,
Italy, England and Germany.

### WHY MY `#603` FIX DID NOT CATCH THIS, stated plainly

Guard 2 refuses a quote that **names a different fixture**. These quotes name
NOTHING — the adapter could not resolve the ticker, so `Quote.game is None`, and
the documented asymmetry ("a quote that names none is allowed through exactly as
it is today... it can only ever remove a match that is provably wrong") lets it
match the bare key and answer every row sharing `(sport, market, side, line)`.

That asymmetry was chosen so the fix could not regress coverage. **The
measurement now shows it leaves the defect essentially intact wherever game
resolution FAILS** — which is soccer and NCAAF, i.e. 129 of the 148 verdict
rows. `#603` is NOT fixed; it is fixed only for venues that can name their game.

### Production impact BEYOND the annotation

This is not confined to a display-only field. The same wrongly-joined quote
feeds the price reprice and `_reprice_live_benchmark`:

    HEADLINE price is the venue                     17 rows
      ...and its ref answers >1 fixture              2   <- WRONG-GAME price served
    best_any_book is the venue                     148
      ...and its ref answers >1 fixture            108

Served right now: `Baltimore Orioles@Athletics` totals 4.5 carries **-525 / +488
from a White Sox@Twins ticker** as its headline price.

### Verdict on the venue basis itself

**UNMEASURED, and correctly so.** Not one of the seven numbers is evidence about
in-play venue edge; every one is a join defect wearing an edge's clothes. The
`servable=False` default is vindicated by its first contact with production —
had these been servable they would have sorted straight to the top of an
edge-ranked board at -40.9, -39.7 and -21.5 points.

The honest state: the comparison is WIRED and PROVEN to run end to end, and its
first reading measured the join, not the market. It cannot measure the market
until the game-resolution gap is closed.

---

## CLOSING THE RESOLUTION GAP — `#603` second pass (2026-08-30)

The first pass refused a quote that **names** a different fixture. In production
it rejected nothing, because the quotes doing the damage **name nothing**. This
pass adds the rule the passthrough never had.

### The rule: COLLIDABILITY, applied as a guard rather than a test

An unnamed quote may answer a bare key only if **exactly one game claims it**.

    _key_claimants(rows, sport)   -> {bare_key: {event_id, ...}}
    _quote_names_no_game(quote)
    _unnamed_quote_is_ambiguous(quote, key, claimants)

Claimants are counted by **`event_id`, never by team-name token**. The alias map
is precisely what fails on the sports where this defect lives — soccer and NCAAF
were 129 of the 148 verdict rows — and a claimant count that collapses two games
into one because it cannot name either would re-open the hole it is closing.

Wired into **both** call sites through the same two helpers. Two paths
disagreeing about whether a quote may answer a row is a join that works on
whichever one you happen to read, which is how the first pass came to land on
the function production does not run.

### What it replaces, and why that asymmetry had to go

The first pass documented: *"a quote that names none is allowed through exactly
as it is today... it can only ever remove a match that is provably wrong."* That
was true, and it was the wrong bar — it made the fix structurally unable to touch
the majority case, and the majority case was wrong.

### THE COVERAGE COST, MEASURED ON THE REAL BOARD, NOT ARGUED

Simulated against the served pool `written_at 2026-08-30T03:42:11Z`:

    verdict rows                                    148
      bare key CONTESTED (>1 game claims it)        107
        ...ref answers >1 fixture  -> PROVABLY WRONG 107
        ...ref answers 1 fixture   -> would be LOST    0
      bare key uniquely claimed -> UNAFFECTED        41

**Zero plausibly-correct quotes are lost.** Every row the guard removes is one
whose ticker is already answering more than one fixture, where at most one can
be right. The 41 rows on uniquely-claimed keys keep working unchanged.

Two honest bounds on that number: it is ONE slate and ONE pool, and it is an
UPPER bound on loss because it assumes every contested-key quote is unnamed —
a quote that names its game is untouched by this guard.

### Tests: five, and the coverage half matters as much as the safety half

- two games sharing a key -> **both refused**, the measured CWS@MIN-on-Orioles case
- **one** game claiming the key -> **still matched** (or this trades a wrong-price
  bug for a no-price bug)
- a quote that NAMES its game -> survives a contested key; the first pass's
  by-name refusal still fires for the other game
- 33 fixtures on one ticker -> 0 matches, 66 rejections (the Belgian tie ticker
  at its measured scale)
- `over 7.5` and `over 8.5` do NOT contest each other — over-refusing per market
  instead of per key would silently delete a whole slate's coverage

`AMBIGUOUS_UNNAMED_REJECTED` prints unconditionally with its denominator,
including the zero. A guard whose only evidence is a counter nobody prints is
how the first pass looked like it was working while rejecting nothing.

### What this does NOT do

It does not make the venue name its game. Resolution is still failing for the
Belgian/Bundesliga Kalshi tickers and the `tsc-cfb` Polymarket slugs; this stops
those quotes from answering the wrong row, and the 107 rows now go UNPRICED by
the venue rather than WRONGLY priced. Restoring that coverage is alias/resolver
work — the four missing MLS codes already handed off are the same class of gap.

206 tests green.
