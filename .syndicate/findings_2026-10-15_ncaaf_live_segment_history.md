# Live segment markets are a PLATFORM-WIDE property, not MLB's — and MLB is never the worst sport

`[2026-10-15 01:3x–02:0xZ, session 4ab694ed, lane ncaaf-live-segment-history, taking the NCAAF follow-up filed on closing venue-segment-addressable]`

## What this was supposed to be, and what it turned into

The venue lane closed 90 minutes earlier with a flag: NCAAF was the one live
exception at **7 of 12 rows full-game (58.3%)**, n=12, on a Wednesday MACtion
slate. The follow-up asked for a second reading on a real college slate.

**The lane's hypothesis was that Saturdays would look like the other sports
(90%+ full) and the n=12 reading was a thin-slate artifact. That is FALSIFIED.**
And checking it the same way for every sport refutes the venue lane's verdict
too — which was mine, from 90 minutes earlier.

## The source, and why it beats waiting for Saturday

`opportunity_population_ledger` records the first sighting of each priced side
per (date, sport) **before the shortlist cuts anything**, and since 2026-09-17 it
records a side **once per phase** (`seen_key` appends `#live`). So live sightings
exist for sides also seen pregame — exactly what a served-board snapshot cannot
give. `segment` sits inside the key (`KEY_FIELDS` position 4) and `gs` carries
`game_state`. Phase is decided by the **deployed `_phase`**, not a local guess;
it returned `unknown` for **0** rows.

On the fleet disk: 16 board dates (2026-09-30 → 10-15), **0 unparsable lines**.

## NCAAF, per date — the Wednesday reading was RIGHT, not an artifact

| date | dow | pregame | **LIVE** | `segment=full` on live |
|---|---|---|---|---|
| 2026-10-01 | Thu | 3,525 | 898 | 380 (42.3%) |
| 2026-10-02 | Fri | 6,513 | 1,398 | 712 (50.9%) |
| **2026-10-03** | **Sat** | 10,616 | **20,912** | **11,064 (52.9%)** |
| 2026-10-06 | Tue | 4,685 | 455 | 285 (62.6%) |
| 2026-10-07 | Wed | 5,816 | 799 | 461 (57.7%) |
| 2026-10-08 | Thu | 7,158 | 1,801 | 1,059 (58.8%) |
| 2026-10-09 | Fri | 7,466 | 2,386 | 1,408 (59.0%) |
| **2026-10-10** | **Sat** | 9,543 | **18,679** | **10,173 (54.5%)** |
| 2026-10-13 | Tue | 5,420 | 836 | 486 (58.1%) |
| 2026-10-14 | Wed | 5,941 | 709 | 429 (60.5%) |
| 09-30, 10-04, 10-05, 10-11, 10-12, 10-15 | | | **0** | no live sightings — reported, not omitted |
| **ALL** | | 87,428 | **48,873** | **26,457 (54.1%)** |
| **SATURDAYS ONLY** | | | **39,591** | **21,237 (53.6%)** |

The n=12 Wednesday reading said 58.3%. The 10-14 full-day figure is **60.5%**,
and the Saturdays are **53.6% over 39,591 sides**. The small reading was accurate
and slightly *generous*. **45.9% of NCAAF live sides (22,416) are segment
markets** — `h1/spreads` 2,866, `h1/totals` 2,724, `h2/totals` 1,816,
`h2/spreads` 1,770, `q2/spreads` 1,742, and so on through q1–q4.

## Every sport, one instrument, one denominator basis

This is the part that refutes the venue verdict. 212,665 live priced sides:

| sport | live sides | `full` | share | the segments a full-game quote cannot price |
|---|---|---|---|---|
| **ncaaf** | 48,873 | 26,457 | **54.1%** | 22,416 (45.9%) — h1, h2, q1–q4 |
| **nba** | 17,682 | 11,560 | **65.4%** | 6,122 (34.6%) — h1, h2, q1–q4 |
| **mlb** | 14,173 | 10,571 | **74.6%** | 3,602 (25.4%) — first5, first3, first1 |
| wnba | 18,964 | 14,455 | 76.2% | 4,509 (23.8%) |
| nfl | 52,610 | 45,346 | 86.2% | 7,264 (13.8%) |
| soccer | 43,001 | 41,763 | 97.1% | 1,238 (2.9%) |
| **nhl** | 17,362 | 17,362 | **100.0%** | **0 — genuinely clean** |
| ncaab | — | — | — | no population parts on disk (out of season) |

**MLB is the third-most full-game of the five segment-carrying sports.** NCAAF
and NBA are both worse. So *"the segment constraint is MLB-specific"* — the
verdict I landed at 00:55Z — is **wrong**.

## Why the served-board snapshot misled, and the proof is NBA

The 00:55Z reading was taken off the served shortlist: 189 non-MLB live rows,
**95.8% full**. The served live board is a tiny score-ranked subset of the priced
population (10-14: **709** NCAAF live sides priced, **12** served).

**NBA is the clean demonstration.** It read **19 of 19 = 100% full** on the
served board — the healthiest sport in that snapshot. Over 17,682 priced live
sides it is **65.4%**, the second *worst*. A served snapshot and the priced
population answer different questions, and for a question about whether venue
quotes can price the board, the priced population is the right denominator —
it is the basis the original MLB finding's own 427 was on.

## The unit matters, so here it is three ways

`totals_alt` / `spreads_alt` are separate markets and every alt rung is its own
side, so a side count can be inflated by whichever segment carries more ladders.
Recounted with ladders collapsed:

| sport | sides | (event, segment, market) | (event, segment) |
|---|---|---|---|
| ncaaf | 54.1% of 48,873 | **29.1%** of 3,068 | 14.3% of 847 |
| nba | 65.4% of 17,682 | **17.1%** of 997 | 15.9% of 327 |
| mlb | 74.6% of 14,173 | **55.9%** of 655 | 25.5% of 98 |
| wnba | 76.2% of 18,964 | 37.1% of 415 | 14.3% of 77 |
| nfl | 86.2% of 52,610 | 40.0% of 930 | 14.3% of 217 |
| soccer | 97.1% of 43,001 | 78.7% of 1,490 | 42.8% of 297 |
| nhl | 100% of 17,362 | **100%** of 781 | **100%** of 102 |

- **The ordering is stable in every unit** and MLB is never the worst — in the
  ladder-collapsed unit MLB is the *best* of the five (55.9%).
- **The LEVEL is unit-dependent and must be quoted with its unit.** "54.1% of
  NCAAF live sides are full-game" and "29.1% of its live markets are" are both
  true. The side count is the unit closest to *what the board prices and could
  bet*; the market count is closest to *how many venue contracts you would have
  to source*.
- **The third column is near-degenerate** — 14.3% is exactly 1/7, i.e. almost
  every live game carries full + h1 + h2 + q1–q4. It measures how many segment
  types exist per game, not share of the board, and is shown only so the
  degeneracy is visible rather than mistaken for a finding.
- **NHL is 100% in all three columns**, which is a real result and not a
  coincidence of units.

## The venue lead, restated

**Supersedes the 00:55Z verdict on `venue-segment-addressable`.**

1. **Segment markets are platform-wide.** Only NHL (100%) and soccer (97.1%) have
   live boards a full-game venue quote can price wholesale. NCAAF (54.1%), NBA
   (65.4%), MLB (74.6%), WNBA (76.2%) and NFL (86.2%) all carry a material
   segment population.
2. **Wiring full-game venue pricing is still worth it, for a different reason
   than the one I gave.** It is not "the constraint is MLB-only, so one fix
   clears it" — it is that full-game is a majority of live sides in all seven
   sports, 54.1% at worst. The gain is broad and partial, not narrow and total.
3. **AND THE PREMISE THE WHOLE CHAIN RESTED ON IS FALSE.** The inherited lead
   stated *"The live MLB board is mostly first3/first5."* Measured: MLB live is
   **74.6% full-game, 25.4% segment**. That sentence was never measured, and I
   carried it into two findings files without checking it.
4. **So the MLB arithmetic needs redoing by whoever owns it.** From that lane's
   own numbers — 427 live MLB sides, **23** matched a venue quote, **17 of those
   23** refused `SEGMENT_MISMATCH_GRID` — segment mismatch explains **17 of 427
   = 4.0%** of the failure. The dominant loss is the **404 of 427 (94.6%) that
   matched no venue quote at all**, which segment shape does not explain and this
   lane did not measure. `17/23 = 74%` is a share of *matched sides*, not of the
   board, and reading it as the latter is how "mostly first5" became received.

## Method note

Live/pregame from the deployed `_phase` (0 unknown). No share is reported over a
date with no live sightings — six such dates are listed with a zero. Segment
shares are of the **priced** population, which is the right denominator for a
pricing question and is **not** the served board; the gap between them is stated
above with a measured example rather than left implicit. Every figure is
recounted in three units and the unit is named wherever a level is quoted.
Analysis run at `nice -n 19` — the fleet shares this host.
