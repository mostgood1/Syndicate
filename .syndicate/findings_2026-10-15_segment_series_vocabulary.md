# The segment-demand lead was my own bad ask: the refusal is deliberate, tested, and already cost $7.08 to learn

`[2026-10-15 14:1x–14:4xZ, session 4ab694ed, lane segment-series-vocabulary, taking the segment-demand lead filed on closing venue-prop-series-request-side]`

## What I filed, and why it was wrong

Closing the previous lane I filed three ordered asks, cheapest first:

> **(1)** make the board's demand plumbing ask for segment rungs it already
> prices (45.9% of NCAAF live sides are segment markets and demand is 0)

**Do not do (1) as written.** It would remove a protection that is deliberate,
pinned by a test, and installed after a real-money loss. This lane exists to say
so with the evidence, because the ask reads obvious and is not.

## 1. The demand filter is deliberate, and it says why

`kalshi_odds_refresh.board_line_entries` line 471:

```python
if segment_for_board_row(row) != "full":
    continue
```

Its own docstring:

> **FULL GAME ONLY.** A segment row's rung lives in its own series, and
> `segment_for_board_row` and `segment_for_series` speak different vocabularies.
> Matching across them is the join's job (`_segments_agree`), not the cap's.

So `demand_rungs = 0` for every segment series is the stated design, not an
oversight: the cap chooses *which rungs to keep*, and segment matching belongs
to the join.

## 2. The vocabularies mostly AGREE — my hypothesis is falsified

I predicted the two sides could not agree by construction. Evaluated with the
**deployed** functions over the real series names the fleet fetches and the real
segment values the board serves:

| row segment | series | `segment_for_board_row` | `segment_for_series` | agree? |
|---|---|---|---|---|
| first5 | `KXMLBF5` | `'first5'` | **`'first5'`** | **yes** |
| first5 | `KXMLBF5TOTAL` | `'first5'` | **`'first5'`** | **yes** |
| first5 | `KXMLBF5SPREAD` | `'first5'` | **`'first5'`** | **yes** |
| h1 | `KXNCAAF1HTOTAL` | `'h1'` | **`'h1'`** | **yes** |
| h1 | `KXNCAAF1H` | `'h1'` | `None` | no |
| h1 | `KXNCAAF1HSPREAD` | `'h1'` | `None` | no |
| h2 | `KXNCAAF2HSPREAD` | `'h2'` | `None` | no |
| h2 | `KXNCAAF2HTOTAL` | `'h2'` | `None` | no |
| h1 | `KXNFL1HTEAMTOTAL` | `'h1'` | `None` | no |

12 of 17 pairs agree; **of the 9 segment pairs, 4 agree and 5 do not.** The
board's side is clean for every value it serves (`full`, `first5`, `first3`,
`first1`, `h1`, `h2`, `q1`–`q4` all map to themselves). So "different
vocabularies" overstates it: the two sides agree wherever the series is *in the
table*, and the five `None`s are a table omission, not a dialect clash.

## 3. The omission is the mechanism, and it is load-bearing

`_SERIES_SEGMENT`'s own comment, on the NCAAF first-half entries:

> NCAAF first half — **THE TOTAL ONLY, and the omission of the other two is the
> load-bearing part.** `segment_for_series` returning **None** IS the refusal: an
> unmapped series carrying a segment marker is declined, which is what keeps a
> first-half contract from key-matching a whole-game board row. **Listing a
> series HERE is an affirmative statement that we trade it, and it REMOVES that
> protection.** … So `KXNCAAF1H` (winner) and `KXNCAAF1HSPREAD` are deliberately
> ABSENT and keep returning None. The spread is additionally the
> margin-vs-handicap risk class `KXMLBF5SPREAD` is excluded from trading for.

`tests/test_kalshi_segment_marker_shape.py` pins it with a 13-name refuse-list:
`KXNCAAF1QSPREAD`, `KXNFL2QTOTAL`, `KXNBA3QSPREAD`, `KXNFL4QTOTAL`,
`KXNBAQ1TOTAL`, `KXNCAAF1HSPREAD`, `KXNFL2HTOTAL`, `KXWNBA1HWINNER`, `KXMLBF3`,
`KXMLBF7`, `KXMLBF3TOTAL`, `KXMLBF7TOTAL`, `KXMLBINNINGTOTAL`. Note `KXMLBF3` is
refused **even though the board has `first3` rows to land on** — the test says so
in as many words. These are trading-scope decisions, not gaps.

## 4. What it cost to learn, recorded in the module

`_SERIES_SEGMENT`'s comment carries the incident:

> MEASURED, real money: five orders carrying `segment=first3`/`first5` were
> placed on full-game `KXMLBTOTAL` tickets, **$7.08 staked** … THE PRICES ARE
> THE TELL AND THEY LOOK LIKE FREE MONEY. The model priced "under 2.5 runs
> through three innings" and compared it against the venue's price for "under
> 2.5 runs in nine", which is correctly ~5c because it almost never happens.
> **The entire apparent edge is the two numbers describing different events. All
> five will lose.**

My ask (1) would have re-opened exactly that: demanding segment rungs without an
affirmative per-series trading decision is how a first3 board row finds a
full-game ticket again.

## 5. The one real gap I found is FEE-ONLY, and fixing it would be inert

`venue_fees._KALSHI_SERIES_BY_MARKET` maps `("mlb","totals","first5") →
KXMLBF5TOTAL` and `("mlb","spreads","first5") → KXMLBF5SPREAD`, and **has no
entry for `("mlb","h2h","first5")`** — which is precisely the shape the
originating lane reported refused (`mlb|first5|h2h`).

Two reachability checks stopped that becoming a claim:

- **It is not a selection table.** `kalshi_series_for_market` has exactly two
  callers and both are fee paths (`venue_fees.taker_fee_per_contract:772` and a
  `layer2_board:4298` wrapper that delegates to it). A missing entry therefore
  cannot mis-pair anything — it makes a tickerless Kalshi row fall back to
  `kalshi_assumed_full_rate` with `is_upper_bound=True`: an **overstated** fee,
  flagged as a bound. Conservative by design, and the module's own rule is
  "never invent a cheaper fee".
- **And the fix would be a no-op anyway.** `KALSHI_SERIES_FEE_MULTIPLIERS` has
  `KXMLBF5TOTAL: 0.5` and `KXMLBF5SPREAD: 0.5` but **no entry for bare
  `KXMLBF5`**, so adding the mapping resolves to a series with no measured rate
  and falls back to the same assumed bound. Supplying a rate from inference is
  the one thing the table forbids.

**So no code changed.** The table's own standard is that every pair was read off
a served row's ticker; I have not observed a `KXMLBF5-…` ticker on a served row,
so adding one on inference would violate the standard it is maintained to.

## 6. And the coverage cost was already measured, with a user decision on it

`venue_quote_fanin`'s header carries it — `[user decision, 2026-09-06: "measure
the coverage cost and flip the flag"]`, served payload, two samples 60s apart:

| sport | rows | segment rows | would be refused |
|---|---|---|---|
| mlb | 734 | 18 | 17 |
| ncaaf | 270 | 8 | 0 |
| soccer | 119 | 0 | 0 |
| **total** | **1,124** | **26** | **17** |

1.51% of all rows, 65.4% of segment rows — and **of the 17: DISPLAYABLE 0,
SERVABLE 0.** The refusal removed no coverage a user could see or act on, which
is why `_SEGMENT_REFUSAL_ENABLED = True`.

## The residual lead, which is real and is NOT what I filed

**That decision was measured on 26 segment rows. I have since measured 22,416.**

The 2026-09-06 reading saw 8 NCAAF segment rows on a 270-row NCAAF board. The
lane two before this one measured NCAAF live at **45.9% segment — 22,416 of
48,873 live priced sides**, and NCAAF live at 54.1% full-game against NHL's
100%. The population the "0 displayable, 0 servable" conclusion rests on is
three orders of magnitude smaller than the one that exists now, and it was
almost entirely MLB.

**So the question to re-ask is not "wire the demand" but "re-measure the refusal's
coverage cost on a current NCAAF slate."** If 0 displayable / 0 servable still
holds, the refusal is free and the whole venue-segment thread is closed for good.
If it does not, the next step is a per-series affirmative trading decision —
someone deciding we trade `KXNCAAF1HTOTAL`-style contracts, with the
margin-vs-handicap exclusion respected — and not a blanket demand change.

The header also flags the caveat that makes re-measuring worthwhile: the 17 read
unservable because of a **45s staleness ceiling**, not because of segment logic.
A fresher quote makes them servable, so the zero is a timing property of that
slate rather than a structural one.

## Method note

Both vocabularies were evaluated by importing the deployed functions and calling
them on the real inputs — no reimplementation, and the board-side values are the
ones measured on the served board earlier in this session. The fee-table gap was
checked for reachability (callers) and then for effect (is there a rate?) before
being written down, which is what kept it from being reported as a mis-pairing
cause. No code was changed and no deploy was made.
