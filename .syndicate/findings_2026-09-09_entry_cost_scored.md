# FINDINGS — the entry-cost edge is REFUTED: a correct GROSS number was quoted as if it were NET

`[2026-09-09, lane segments-joint-v1, commissioned scoring run. VERDICT: REFUTED.]`

## What was claimed, and by whom

The Engine Room Audit calls venue-hold routing the largest measured lever on
file: MLB prop unders excluding HR and HRR, n=2,569, flat 1u — **+8.48% ROI at
zero hold, +6.52% at 2%, +0.98% at the ~8.1% book hold**. Today's hold reading
put Kalshi at **3.55% net of fee** against the book's **6.89%**, and I reported
the attainable prize as **+4.1 ROI points**.

**Every one of those figures is a HOLD calculation. None was ever scored against
an outcome.** This is that scoring.

## The result — realised flat-1u return, book vs exchange

MLB, 2026-09-01..09-04, last **pregame** same-instant pair (±60s), exchange net
of the measured per-series fee, graded against StatsAPI finals. **CI95
bootstrapped over GAMES, not rows** — rows within a game are correlated.

| same-book scope | n | games | ROI book | ROI exch | **diff** | CI95 | excludes +4.1 |
|---|--:|--:|--:|--:|--:|---|---|
| pinnacle | 281 | 53 | −1.29% | −2.95% | **−1.67** | [−1.87, −1.48] | yes |
| draftkings | 601 | 53 | −1.48% | −1.12% | **+0.37** | [−0.27, +1.00] | yes |
| fanduel | 323 | 53 | −2.66% | −2.36% | **+0.29** | [−0.00, +0.59] | yes |
| betmgm | 478 | 53 | +1.75% | +2.73% | **+0.98** | [+0.12, +1.73] | yes |

Best-of-N (`book_agnostic`) **reported apart and never pooled** with same-book,
per the standing rule: −0.02 [−0.85, +0.71], n=1,146.

**NOT UNDERPOWERED, and this is checkable rather than asserted:** the losing leg
returns −1u at BOTH venues and cancels exactly, so the game-level sd of the
*difference* is only 0.78–2.03 pts. Roughly **one game** separates +4.1 from
zero. There are 53.

## Why it fails — the fee is paid twice in the argument and once in the arithmetic

| scope | gross diff | **net diff** | fee cost |
|---|--:|--:|--:|
| pinnacle | +1.53 | **−1.67** | −3.20 |
| draftkings | +3.17 | **+0.37** | −2.80 |
| fanduel | +3.48 | **+0.29** | −3.19 |
| betmgm | +4.09 | **+0.98** | −3.11 |

**Gross, the exchange IS cheaper by +1.5 to +4.1 points — the hold measurement
was never wrong.** The error is category, not arithmetic: **hold subtracts the
fee once, at entry; realised P&L pays it on every trade regardless of outcome.**
A correct gross number was carried through an entire day of work as if it were
net.

**Against a SHARP book the exchange is WORSE by 1.67 points**, with a CI that
excludes zero. Venue routing is worth roughly **±1 point, sign depending on which
book you would otherwise have used.**

## The audit's own gate population

MLB prop unders, −HR −HRR: draftkings −0.39 [−2.69,+1.68] (n=113/32g);
best-of-N +0.33 [−1.36,+2.15] (n=266/40g); betmgm +0.98 [−2.87,**+5.09**]
(n=66/19g); **pinnacle 0 — it quotes no MLB props at all.** ~16–18 games are
needed for +4.1; DK and best-of-N are powered and exclude it. **BetMGM's gate
scope is UNMEASURED — do not quote it in either direction.**

## Attrition, because the denominator is the finding

    823,446 shard rows
    −27,704  novig/prophetx (no fee model exists)
     12,176  exchange keys
       −743  no book quote
     −2,604  in-play only
     −6,065  SAME-INSTANT REJECTIONS at ±60s  (49.8% — half the population)
      2,764  pairs
     −1,543  non-full-game segment
        −74  doubleheader
      1,146  scored / 53 games

Zero player-name failures. **The verdict holds at 5, 30, 60, 300 and 900-second
windows**, so it is not an artefact of the tolerance.

## THREE METHOD DEFECTS — TWO ARE LIVE IN REPO CODE

1. **`measure_exchange_prop_option_value.quote_key:333-345` OMITS `segment`.**
   469 of 5,290 keys (**8.9%**) span more than one segment; `totals_alt` and
   `spreads_alt` are mostly `first5`. Unfixed, it pairs a full-game exchange
   price to a first-5 book price — *"MLB over 1.5 at +245"* — and manufactured a
   fictitious **−21.7 point** headline. `odds_book_quotes._KEY_FIELDS` already
   includes `segment`. **EVERY NUMBER THAT SCRIPT HAS PUBLISHED RESTS ON THIS
   KEY and must be re-derived before being quoted again.**
2. **First-available entry is a median 18 minutes AFTER first pitch** — i.e.
   in-play, with the exchange at its widest. A "pregame" study that enters
   in-play is measuring something else.
3. Best-of-N reads `spreads_alt` book ROI **+51%** — pure selection, not edge.

## Limits of this result

- **Counterfactual on quoted prices, not fills** (`placeable_committed = 0/11`),
  so it is an **UPPER BOUND on the exchange** — real slippage only worsens it,
  which **strengthens** the refutation.
- MLB only; full-game segments only.
- `venue_odds` could not be read from production (not allowlisted) and the local
  mirror was deliberately NOT substituted.

## Consequences

- **Stop quoting +4.1, and stop quoting +8.48 as attainable.** The honest figure
  is ~±1 point, negative against a sharp book.
- **S6b (pregame entry-cost routing) should NOT be built.** The fill probe
  established the book supports it; this establishes it is not worth doing. Both
  answers were needed and only the second is decisive.
- `#624` step 6 (venue-hold routing as the largest lever) stays **NOT MET**, by a
  wider margin than the +2.43% reading suggested.
- Fix `quote_key` before that script informs anything.
