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
