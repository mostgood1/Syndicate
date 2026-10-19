# The 73 NCAAF `skipped_no_fair` rows: Polymarket alone, pricing BOTH sides of a ±0.5 spread at ~98%. No fair exists, the board is right to refuse one, and nothing on the row says so

`[2026-10-19 22:08Z / 5:08 PM CDT]` lane `ncaaf-skipped-no-fair`
`[no outcomes used anywhere in this document]`
`[served board, cap defeated, single same-instant fetch per sport, `written_at` 2026-10-19T21:53:32Z, 3,944 rows]`

## The lead, answered

The lead (filed 2026-10-19, from the strikeouts check) read:

> **59 NCAAF rows carry `calibration_method: skipped_no_fair` with a MEDIAN RAW
> EDGE of 25.20 points** — the largest unshrunk magnitudes on the served board.
> The first question is why these rows have no fair at all.

**Answer: because there is no market to be fair to.** The count is **73** on the
current slate (the earlier 59 was a smaller slate; the median edge is unchanged
at 25.2, which is why the rate was the comparable figure and the count was not).

All 73 are a single family — **`ncaaf spreads`, `segment=full`, `kind=game`** —
and every one of them is quoted by **Polymarket and nothing else**:

```
quote.book_prices     {"polymarket": -4900}
quote.books_quoting   1
quote.price           -4900
quote.other_sides     {"home": {"bookmaker": "polymarket", "price": -4900.0}}
```

- prices across the 73: **−9900, −4900, −3233, −2400** → implied **0.96 to 0.99**
- **70 of 73 carry the SAME price on the opposing side, from the SAME book**
- implied(this side) + implied(other side): **median 1.9600**, min 1.9200, max
  1.9800 — **all 73 above 1.5**, i.e. a **96% hold**
- control, the 344 sibling `ncaaf spreads|full` rows that DO have a fair:
  **median 1.0238** (a normal ~2.4% hold)
- **0 of those 344 are Polymarket-only.** Polymarket-only is the whole story.

A binary market whose two sides both imply 98% is not a market. No honest
de-vig exists, so `_consensus_fair` returns `{}` (it needs
`_two_sided_prices_by_book`), the anchor tiers do not anchor, the same-book
fallback cannot help because the degenerate pair IS the same book, and
`_resolve_fair` yields nothing. **The board is behaving correctly.**

**68 of the 73 sit at a point of ±0.5** (34 at −0.5, 34 at +0.5; the remaining 5
at −20.5, −8.5, +8.5). A ±0.5 spread is a moneyline. So what is reaching the
NCAAF spreads board is a Polymarket "who wins" market wearing a spread's
clothes, at a price that is not tradeable.

## Not live, not flagged stale

Both explanations that would have made this benign are ruled out from fields
already on the row:

| | the 73 | the 27 (below) |
|---|---|---|
| `is_live` | False ×73 | False ×27 |
| `game_state` | pregame ×73 | pregame ×27 |
| `market_state` | pregame ×73 | pregame ×27 |
| `suspect_stale` | False ×73 | False ×27 |

A late-game live quote at −9900 would be honest. These are **pregame**, and
nothing flags them.

## The lead's own framing was technically true and materially misleading

My hypothesis predicted this and it held: `ev` is guarded on the same `fair`
(`layer2_board.py:3329`, `ev = expected_value_pct(price, fair) if fair is not
None else None`), and `portfolio_commit` back-derives its fair FROM `ev_pct`. So:

- `fair_probability`: **None on all 73** (control: present on 3,871)
- `ev_pct`: **None on all 73** (control: present on 3,871)

**These rows cannot be sized. They are not an exposure.** Calling them "the
largest unshrunk magnitudes on the board" was true of the number and wrong
about the risk — the exact failure mode CLAUDE.md names. What they do cost is
measurement integrity: 73 ranked rows in `board_lane: opportunity` carrying a
`model_edge_pct` up to ±33 points, inflating every coverage and model-edge
census. That is precisely what made them look like the worst rows on the board
in my 10-16 bug list.

## THE ACTUAL DEFECT: the refusal is silent

On all 73:

```
fair_method            None
fair_anchor_refusal    null
fair_anchor_refusals   []
```

Nothing says why. The refusal fields are stamped from
`fair_resolution.anchor_refusal(s)`, which record **anchor-tier** refusals
only — and here no tier refused, there was simply nothing two-sided to anchor
on. **There is no reason code for "consensus had no two-sided book".** So the
single most load-bearing number on the row is absent and the row is mute about
it.

This is my own recurring rule from the other direction
(`feedback_gate_on_the_output_not_the_input`,
`feedback_instrument_blindness`): a healthy reading is evidence only once you
know what makes it read unhealthy. Here an absent fair and an absent *reason*
are indistinguishable from a row that was never evaluated.

## WITHDRAWN: my "27 rows got a fair from a degenerate pair" finding

I measured 27 rows platform-wide whose two-sided implied sum exceeds 1.30 while
still carrying a fair and an `ev_pct`, several with small POSITIVE EV
(+0.15 to +2.37), and was about to report a fabricated edge. **It does not hold.**

`other_sides` reports the **best price per side across books**; the fair is
built **per book** (`_two_sided_prices_by_book`, then median). Summing the best
home price from `novig` against the best away price from `kalshi` is exactly the
cross-book combination `_resolve_fair`'s own comment warns about — *"It is the
CROSS-book case that launders"*. My sum is therefore **not the quantity any fair
was built from**, and cannot establish a defect in one.

The 73 survive this objection only because Polymarket is the **only** book on
them (`books_quoting: 1`, `book_prices` of size 1), so there the pair genuinely
is same-book and same-price.

**This is the fourth time in two days I have built a population out of a field
whose semantics I assumed rather than checked** (after `bucket_factor`'s `None`,
`established_loss_rel`'s consumers, and `edge_vs_market_pct` vs
`model_edge_pct`). The pattern is identical each time: the arithmetic is right
and the operand is not mine to combine.

## Handed over, NOT claimed

Scope note: `_resolve_fair` / `_consensus_fair` are claimed by lane
**`fair-price-v2`** (OPEN, session `9e18a0e7`), so this lane made no edit there
and does not propose one. Two things for that lane to judge:

1. **The missing reason code.** A `fair_refusal` of the form
   `no_two_sided_book` (or `consensus_empty`) stamped where `_resolve_fair`
   falls through would make all 73 self-explaining. That is a change in their
   file, not mine.
2. **Best-of-market prices summing 1.30–1.35 on 12 pregame h2h rows**
   (NCAAF and soccer, venues `kalshi` / `novig` / `prophetx` among the best
   quotes). Per the withdrawal above this is **not** evidence the fair is wrong,
   because the fair is not built from that combination — but a 30–35% implied
   hold across best-of-market prices on a pregame h2h is not a plausible market
   state and may indicate a venue price conversion worth checking. Reported as
   an observation with its own refutation attached.

## What is NOT shown here

- **No outcomes were used.** Nothing here tests whether any of these rows would
  have won or lost. The claim is that 73 rows are priced against a quote that
  is not a market, and that the board says nothing about it.
- Whether Polymarket's ±0.5 NCAAF spread should be surfaced **at all** is a
  product decision, not established here. The cheaper framing is that a venue
  quoting both sides at 0.96–0.99 should be excluded from the spreads board, or
  mapped to h2h where ±0.5 actually belongs.
- Point pairing is **unverifiable from the payload** for the spread rows:
  `other_sides` carries a bookmaker and a price but **no `line`**, so I could
  not confirm a mirrored point from the row alone. For the 68 rows at ±0.5 the
  board supplies the confirmation itself (34 at −0.5 and 34 at +0.5, in the
  same 32 games); for the other 5 it is assumed, not shown.
- All 32 games holding a no-fair row **also** hold a with-fair spread row
  (32 of 32), so this is per-row, never a per-game data outage.
