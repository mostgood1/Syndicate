# FINDINGS — the Kalshi execution-path join: my 1.2% was one tick, and the real gate is the alias map

`[2026-09-09, lane kalshi-join-match-rate (landed `167b2841`), commissioned from lane segments-joint-v1]`

## 1. RETRACTION — "matched=7 of 600" is not the match rate, and I quoted it as one

I opened this work on a single `[kalshi_odds] BOARD_JOIN` line, `matched=7 board_rows=600`,
and presented **1.2%** as the execution-path match rate. It is the 04:43:54Z tick,
**the worst of 48 measured across 00:05–15:00Z.** Re-measured on the execution
emitter `[portfolio_commit] KALSHI_BOARD_JOIN`, split by the date each tick was
building:

| build date | ticks | board rows | matched | rate |
|---|---|---|---|---|
| **2026-09-09 (today)** | 26 | 65,736 | 14,047 | **21.4%** |
| 2026-09-08 | 10 | 15,078 | 2,905 | 19.3% |
| 2026-09-10 (tomorrow) | 11 | 20,031 | 192 | 1.0% |

**Two errors, both mine, both on the ledger's standing list:**
- **A rate from one observation.** `learnings.md` already forbids this and it is
  the second-most repeated error in this repo. One tick is not a rate.
- **Two populations conflated.** The miss REASONS are counted per MARKET
  (~12,500/tick); `matched` is counted per (market, row) PAIRING. Dividing one by
  the other produces a number that describes nothing. I built a six-bucket case on
  that division.

The commissioned session was still worth running — it found the real gates — but
**anything downstream of "1.2%" must be re-derived, not inherited.**

## 2. Kalshi already prices four rows in five that the portfolio considers

`[portfolio_commit] PAPER2_PLAN_WRITTEN venue=kalshi`, 14:46:45Z: **781 of 983
rows priced, 79.4%.** So "the join is the bottleneck" is FALSE as a statement
about pricing coverage on the execution path today.

The gap is one step later: **`placeable_committed = 0 of 11`.**

## 3. The choke point is `team_aliases`, and it is NCAAF-wide

All 11 sized positions pulled from `/api/portfolio/paper?date=2026-09-09` are
NCAAF, every one `price_source='aggregator'` with `venue_ticker=null`.
Polymarket took 5 of 5 as `venue_feed` on the same build.

Two chained gates:

1. `kalshi_board_join.py:1225-1238` (`_date_ok`) — forward-date widening reads
   `sport != "soccer" -> return False`, so every forward NCAAF market dies as
   `market_is_for_another_date`. Kalshi does list them: `BY_GAME_DATE` 2026-09-12
   carries `KXNCAAFGAME 182, KXNCAAFSPREAD 400, KXNCAAFTOTAL 400`.
2. **The real one:** `team_aliases.canonical_team("ncaaf", …)` returns `None` for
   **every NCAAF club** — verified with `data/` present in the primary tree, where
   nfl, mlb and soccer all resolve. `match_event_blob`'s resolver branch therefore
   skips every NCAAF game, so an NCAAF game line can never resolve an event.

**The honest shrink, verified end to end rather than assumed: fixing gate 1 alone
gains ZERO of the 11 positions.** Only 5 are `KXNCAAFTOTAL` at all
(`KXNCAAFGAME`/`KXNCAAFSPREAD` are unmapped in `sport_for_series`), and all of
them still die at the alias map.

**No club alias was guessed**, and a test named
`test_the_ALIAS_MAP_is_the_real_gate_and_this_lane_did_not_open_it` pins that
result so a later session cannot mistake the shipped flag for the fix.

## 4. What shipped (landed `167b2841`, NOT deployed, flag OFF)

`_date_ok` becomes `_date_verdict` with per-sport horizons (soccer 14 unchanged,
ncaaf/nfl 7) behind `SYNDICATE_KALSHI_FORWARD_DATE_SPORTS`, **absent = `soccer` =
byte-identical to today.**

The valuable part is the instrument, not the flag: a new named refusal
`forward_date_sport_not_enabled` counts only markets **inside the horizon their
sport would get**, so the size of the prize is readable in production *with the
flag still off*. `market_is_for_another_date` could never answer that — it also
holds 4,237 stale and futures markets on a quiet build.

19 tests including an `off != on` on identical input, a `#603` control proving a
widened market still refuses an unrelated fixture at the same line, and a
half-point check on a literal production title: `KXNCAAFTOTAL :: 'Over 77.5
points scored'`, ticker `…-78`. **A game total's title already carries the
half-point, so no prop-style N−0.5 shift applies** — worth knowing before anyone
"fixes" the conversion for game lines.

## 5. The ladder-violation hypothesis is REFUTED in production

`findings_2026-09-09_venue_routing_scope.md` recorded 720 of 4,172 ladders (17.3%)
violating monotonicity at 0.02 on **untracked mirror snapshots**, explicitly as a
hypothesis pending a production read. The production read is in, over 23
today-slate ticks:

    rungs_seen 10,991   ladders_checked 381   monotonic 381
    violating 0   refused 0   worst_violation 0.0 pts   mode=report (all 34 ticks)

**381 of 381 clean.** The earlier "0 ladders checked / 7 matched rows" reading was
the same anomalous 04:44 tick. The gate has a real population and finds nothing
wrong with it. Do not carry the 17.3% figure forward; if it is real it lives in
rungs the board never matches, which is a different claim about a different set.

## 6. Two findings worth their own work

- **A deliberate policy is reading as a fault.** Every near-zero tick is a
  TOMORROW-date build whose matches are 100% soccer, withheld on purpose by
  `SYNDICATE_KALSHI_SOCCER_RESOLVERS`. With `matches` empty the resolver returns
  `(None, None)` and the plan stamps
  `READER_FAILED:has_a_feed_but_resolver_returned_none` — a string whose own
  docstring says it means **a defect, not a gap**. So a policy working as designed
  is being recorded as a failure, in the exact field someone would triage from.
- **`PRECAP_CUT_BY_DATE` truncates ladders DATE-BLIND.** `MAX_MARKETS_PER_SERIES
  = 400` keeps an arbitrary `markets[:400]`; `KXNCAAFTOTAL` fetched **1,967 and
  cut 1,567**. Any single board line has roughly a **22%** chance its rung
  survives the cut. That is a coverage ceiling nobody set deliberately, and it
  sits upstream of every join number in this file.
