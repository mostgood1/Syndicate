# SCOPE — a board row at Kalshi's 1.5/2.5 so `KXMLBF5SPREAD` can execute

`[2026-09-06, lane mlb-first5-kalshi-execution (closed), scoping only — nothing built]`
Substrate: `render`. Board figures are production `/api/board/layer2-shortlist`
for 2026-09-05 (553 MLB rows); contract figures are 60 real settled
`KXMLBF5SPREAD` and 84 `KXMLBF5TOTAL` markets read from Kalshi's public API.

## THE HEADLINE: DO NOT BUILD CAPTURE. THE ROWS ALREADY EXIST.

The task was scoped as "get a board row at 1.5/2.5". **The board already has
them.** They are filed under `spreads_alt` / `totals_alt` rather than
`spreads` / `totals`, and the join refuses an `_alt` row against a main-line
contract:

| first5 market | rows | at a Kalshi strike |
|---|---|---|
| `spreads` | 3 | **0** — they sit at 0.5, 0.5, 1.0 |
| `spreads_alt` | 8 | **6 at \|1.5\| or \|2.5\|** — Kalshi's only two F5 spread strikes |
| `totals` | 14 | matched 8 in replay |
| `totals_alt` | 16 | **11 on a Kalshi F5 total strike** |

So the gap is a **VOCABULARY** gap, not a data gap. Capturing more OddsAPI
segment markets would spend credits re-acquiring rows we already hold.

## THE CHANGE

One rule, in the helper that already exists: `_row_market()` in
`kalshi_board_join.py` currently strips the SEGMENT suffix
(`totals_1st_5_innings` -> `totals`). Extend it to also collapse the ALTERNATE
suffix (`totals_alt` -> `totals`, `spreads_alt` -> `spreads`) **for join keying
only**. The row keeps its own `market` everywhere else.

`_MARKET_BASES` in `market_segments.py` already encodes the pair
(`"alternate_totals": "totals_alt"`), so the inverse belongs there beside
`split_segment_market_key` — not as a second table in the join.

## IS THIS SAFE? YES, AND I OWE A CORRECTION HERE

**I previously told the user that matching `_alt` rows was "the class of change
that produced the $7.08 segment defect and the 11 faded-club orders". That was
an over-generalisation and it is wrong.** Those two defects paired bets that are
GENUINELY DIFFERENT wagers:

- **segment**: a first-3-innings bet against a nine-inning contract — different
  portion of the game, different outcome.
- **spread sign**: a MARGIN against a HANDICAP — the opposite club.

`totals_alt` at line 4.5 over, vs `totals` at line 4.5 over, same event, same
segment, is **the same wager**. `alternate_totals` is OddsAPI's market for the
same bet at non-main lines; the suffix describes WHICH FEED priced it, not what
was bet. Collapsing them is a correction, not a widening.

The three guards that protect the real distinctions are untouched and must stay:
`_segments_agree` (segment), the spread sign/orientation logic (club), and
`_key_line` (magnitude).

## THE ONE REAL RISK, MEASURED

Collapsing creates a **duplicate key** where a main and an alt row describe the
same bet. Measured over all 553 MLB rows:

    collapsed keys = 78     colliding = 1     main+alt collisions = 1  (1.3%)

The single collision is instructive and is why this needs a stated rule rather
than a `dict[key] = row`:

    first5  totals  line=3.5  over
      totals_alt  ev_pct = +3.48
      totals      ev_pct = -0.37

**Same bet, two prices, and a 3.85-point EV gap** — because two books priced it.
Whichever row the index happens to keep decides the EV the board reports, and
edge-ranking will prefer the higher one. That is not a mis-keyed join (both rows
really are that bet) but it IS arbitrary, and "the better-looking of two prices
wins by insertion order" is how a phantom edge gets manufactured.

**Required: a deterministic tie-break, declared and tested.** Recommend keeping
the row with the best available price FOR THAT SIDE — that is real price
shopping, already worth `+0.74`/`+2.43` ROI points on this platform — and
emitting a counter (`alt_main_collision`) so the rate stays visible. Do NOT
break the tie on freshness alone: an alt feed updating less often would then
silently win or lose on a property unrelated to the bet.

## WHAT IT BUYS, AND THE BLAST RADIUS IS SMALLER THAN I EXPECTED

    segment  market    main   alt   joinable after
    first3   spreads      0     1        1
    first3   totals       3     2        5
    first5   spreads      3     8       11
    first5   totals      14    16       30
    full     spreads      9     0        9
    full     totals      23     0       23
    TOTAL                52    27       79   (1.52x)

**Full-game carries ZERO `_alt` rows on this slate — every one of the 27 is a
segment row.** So despite touching a shared helper, the practical effect is
confined to segment markets, and full-game behaviour is unchanged. That is one
slate; confirm it holds on another before relying on it.

For `KXMLBF5SPREAD` specifically: joinable first5 spread rows go **3 -> 11**, and
6 of the 8 added rows sit exactly on Kalshi's 1.5/2.5. This is the difference
between a series that structurally cannot match and one that can.

## VERIFICATION REQUIRED BEFORE IT SHIPS

1. **Reachability first (`off != on`)** on the same real data used here: 60
   settled `KXMLBF5SPREAD` x 553 production rows, expecting `matched` 0 -> >0.
2. **The orientation guard must still fire.** It counted 4 refusals in the
   current state; a change that drops it to 0 while matches appear is the
   faded-club defect returning and must fail the change.
3. **`_segments_agree` unchanged** — a full-game contract must still refuse a
   first5 row (the 2026-08-28 case), asserted by NAMED reason, not by
   `matched == 0`.
4. **Collision rule tested directly**, both orders of insertion, asserting the
   same row wins either way.
5. **Full-game regression**: `KXMLBTOTAL`/`KXMLBSPREAD` match counts must not
   move on a replayed slate. The table above predicts no change; measure it
   rather than assuming.
6. 283 tests in the kalshi/segment surface stay green.

## COST

Small — one helper, one inverse map entry, a tie-break with a counter, ~6 tests.
No new capture, **no OddsAPI credits**, no new artifact, no `render.yaml`. The
expensive part is the verification above, not the code.

## WHAT THIS SCOPE DELIBERATELY DOES NOT DO

- **No line interpolation.** A contract at 2.5 must never pair with a row at 2.0.
- **No capture widening.** The rows exist; spending credits would be waste.
- **No change to `KXMLBF5` (five-inning tie)** — it correctly refuses as
  `recognised_but_no_board_market`.
- **Does not discharge the outstanding `verify: OWED`** on `1f032074`. That is a
  separate reading and stays owed regardless of what happens here.
