# Why 404 of 427 live sides found no venue quote: a COVERAGE CEILING, and it is ~8.6% of the live board

`[2026-10-15 02:4x–03:0xZ, session 4ab694ed, lane venue-no-quote-attribution, taking the lead filed on closing ncaaf-live-segment-history]`

## The question

Closing the previous lane re-sized the MLB venue finding: from that lane's own
numbers — **427 live MLB sides, 23 matched a venue quote, 17 of those 23 refused
`SEGMENT_MISMATCH_GRID`** — segment mismatch explains **4.0%** of the failure and
the **404 (94.6%) that matched no venue quote at all** is the dominant loss.
Nobody had measured why. Three candidates: no contract exists (coverage), a guard
discards it, or the fan-in never saw the quotes (ingestion).

**No new instrument was needed.** `venue_quote_fanin` already prints
`VENUE_KEY_SHAPE` unconditionally, per sport and per key shape, as
`offered → present → taken → repriced` with `live_*` variants, and its own
comment says how to read it:

> *present==0 means the shape matches nothing; taken==0 with present>0 means a
> guard discards it; repriced==0 with taken>0 means the book was still fresher*

That is the lesson from the `edge_unavailable_reason` lane applied in the other
direction: there I guessed a reason was recorded and it was not; here I looked
first, and it was.

## The funnel, latest tick per sport, from the fleet logs (02:49–02:50Z)

**The dominant gap is `offered → present` in every sport, overall and live-only.**

| sport | live offered | live present | live taken | live repriced | **coverage loss** |
|---|---|---|---|---|---|
| nhl | 182 | 6 | 6 | 2 | **176 (96.7%)** |
| soccer | 2,280 | 99 | 22 | 8 | **2,181 (95.7%)** |
| mlb | 464 | 33 | 6 | 6 | **431 (92.9%)** |
| nba | 281 | 47 | 17 | 17 | **234 (83.3%)** |
| ncaaf | 651 | 144 | 38 | 33 | **507 (77.9%)** |
| nfl | 0 | — | — | — | no live sides this tick |

`offered` counts shape-attempts, so a side tried by several shapes is counted
more than once. For a **per-side** denominator the `role` shape is the one
attempted on every side — `role.offered == sides_seen` exactly in all six sports
— and it finds a contract for:

| sport | `role` offered | `role` present | share |
|---|---|---|---|
| nfl | 2,201 | **0** | **0.0%** |
| soccer | 21,685 | 414 | 1.9% |
| nhl | 358 | 8 | 2.2% |
| mlb | 354 | 14 | 4.0% |
| nba | 484 | 38 | 7.9% |
| ncaaf | 3,752 | 336 | 9.0% |

**So the 404 were a coverage ceiling: no listed contract for the market, segment
and line the board priced.** Not a join fault, not a guard, not ingestion.
`role` matching nothing at all for NFL (0 of 2,201) while NFL still reprices 80
sides through `club`/`role_game`/`token` shows the shapes are per-sport live and
not uniformly broken.

## Cross-validation: the MLB proportions reproduce on a different slate

| | original lane, regular season | this lane, 02:45Z postseason |
|---|---|---|
| sides | 427 | 354 (`role`), 464 shape-attempts |
| matched / present | 23 (5.4%) | 33 (7.1% of attempts) |
| segment-refused | 17 | **27** (`refused_segment`, all shapes) |
| **repriced** | 6 (1.4%) | **6 (1.7%)** |
| **coverage loss** | **404 (94.6%)** | **431 (92.9%)** |

Two instruments, two slates, two months apart in the season: the same shape.
And **27 of MLB's 33 present-but-not-taken are `refused_segment`** — the
segment guard is the whole of the second-order loss, exactly as the original
lane found (17 of 23), which is the sense in which that finding was right.

## The part that re-sizes the whole venue chain

The fan-in's `matched` dict names every reprice that actually landed. **Across
all six sports, every single one is `full|<venue>|<SERIES>`, and SERIES is always
a `*GAME` (winner) or `*TOTAL` series, or Polymarket:**

```
mlb     {'full|kalshi|KXMLBTOTAL': 4, 'full|polymarket_us|-': 2}
nba     {'full|kalshi|KXNBAGAME': 9, 'full|kalshi|KXNBATOTAL': 12, 'full|polymarket_us|-': 17}
nfl     {'full|kalshi|KXNFLGAME': 18, 'full|kalshi|KXNFLTOTAL': 34, 'full|polymarket_us|-': 28}
ncaaf   {'full|kalshi|KXNCAAFGAME': 116, 'full|kalshi|KXNCAAFTOTAL': 27, 'full|polymarket_us|-': 223}
nhl     {'full|polymarket_us|-': 8}
soccer  {'full|kalshi|KX<LEAGUE>GAME' / 'KX<LEAGUE>TOTAL' across 5 leagues}
```

Nothing segment. Nothing spread. No prop series — **even though
`KXMLBSPREAD`, `KXMLBKS`, `KXMLBHR`, `KXMLBHIT`, `KXMLBRBI`, `KXMLBOUTS` and
seven more exist as series constants in the code.** MLB does not reprice through
`KXMLBGAME` at all on this tick.

**So the ceiling is not "full-game", which is what I wrote at 00:55Z. It is
full-game h2h plus full-game totals.** Measured over the live priced population
(218,054 live sides, 16 dates):

| sport | live sides | full+h2h | full+totals | **CEILING** | measured actual |
|---|---|---|---|---|---|
| ncaaf | 48,987 | 242 | 9,176 | **19.2%** | 366/3,752 = **9.8%** |
| nba | 18,134 | 106 | 2,226 | **12.9%** | — |
| nhl | 17,366 | 204 | 1,236 | **8.3%** | 8/358 = 2.2% |
| mlb | 14,205 | 50 | 602 | **4.6%** | 6/354 = **1.7%** |
| nfl | 52,610 | 74 | 2,190 | **4.3%** | 80/2,201 = 3.6% |
| soccer | 47,788 | 435 | 1,436 | **3.9%** | 181/21,685 = 0.8% |
| wnba | 18,964 | 55 | 644 | **3.7%** | — |
| **POOLED** | **218,054** | 1,166 | 17,510 | **8.6%** | |

**The venue chain can reach at most ~8.6% of live priced sides, and already
reaches roughly a third to a half of that** — NCAAF 9.8% against a 19.2%
ceiling, MLB 1.7% against 4.6%, NFL 3.6% against 4.3%.

Alt-totals ladders would add a lot for two sports (nba +22.3pp to 35.2%, wnba
+8.5pp to 12.2%) **if** the venues listed them. They never appear in `matched`,
so they are excluded from the ceiling and shown separately rather than quietly
counted as addressable.

## What this means for the venue work, stated as a decision

1. **The 404 are not fixable by us.** They are sides with no counterpart
   contract. More key-matching, better vocabularies and fresher quotes move none
   of them — the original lane's conclusion that "more key-matching buys
   nothing" was right, for a reason it had not yet measured.
2. **The genuinely ours part is the gap between actual and ceiling**, and it is
   small in absolute terms: roughly 4–9 percentage points of live sides,
   concentrated in **NCAAF (9.8% → 19.2%)** and whatever NBA's actual turns out
   to be. For MLB the whole remaining headroom is ~2.9pp of a 14,205-side
   population.
3. **Segment refusal is second-order and correctly placed.** 27 of MLB's 33
   present sides, against 431 lost to coverage. Fixing it recovers at most the
   27, which is why "wire full-game venue pricing" was the right direction and
   the wrong size — I called the gain "broad and partial" at 00:55Z; it is
   **narrow and partial**.
4. **Worth checking next, and NOT measured here:** whether the prop series that
   exist as constants (`KXMLBKS`, `KXMLBHR`, …) are being fetched at all. Zero
   matches through any of them is consistent with "the exchange lists them but
   we never request them" as well as with "they are not listed live", and this
   lane cannot tell those apart.

## Method note

The funnel is read from the DEPLOYED diagnostic rather than recomputed; the
`role`-shape per-side denominator is used wherever a per-side share is quoted,
because `offered` double-counts shape-attempts and that is stated at the point
of use. The ceiling is computed over the population ledger's live sightings
(218,054 sides, 16 dates) while the success rates come from a single fan-in tick
per sport — different frames, which is why they are placed side by side with
both denominators rather than divided into one number. No share is reported for
NFL live, which had no live sides on that tick. Analysis at `nice -n 19`.
