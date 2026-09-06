# Segment orders on Kalshi FULL-GAME series — is it live? NO. `[lane segment-execution-ticker-audit, 2026-09-05]`

**VERDICT: not a live-money execution defect. Every mis-filled segment order in
production predates the 2026-08-28 join fix, and this audit discharges the
money-level re-check that `state_kalshi.md`'s `[kalshi-segment-on-full-game]`
entry explicitly deferred to "the next slate that actually places".**

Substrate: `render`. All order-level numbers read from
`https://syndicate-an21.onrender.com` on 2026-09-05; code checked by CONTENT
against the SHA each service is actually running; the guard's counter read from
the Render logs API on the running refresh-worker.

## 1. Where a ticker actually lives — the reporting agent's null was a key-name miss

The field is **`venue_ticker`**, not `ticker`. It is on `orders[]` and
`unreconciled[]` of `/api/portfolio/live?on=all&show=all` (596 live rows) and on
`/api/portfolio/paper?date=<D>` (2,257 rows over 15 dates). A walk for `ticker`
matches nothing anywhere in either payload.

This is a known trap with a standing rule already on file:
`learnings.md` 2026-08-30 — *"FORBIDDEN: keying a predicate to a field name you
have not confirmed the record STORES. My log printed `ticker=None` for every
order because `ticker` is not a key on it."* — and
`execution_ledger.py:1966` carries the same incident in a comment.

`/api/ops/execution/ledger-summary` will never answer this: `_LEDGER_SUMMARY_FIELDS`
is a declared allowlist and the docstring states the response is built by
incrementing counters so that no ticker exists to leak. Its `by_segment`
dimension gives control TOTALS only. (It is deployed; it is not in the primary
checkout, which is behind.)

## 2. The rate, with denominators

Boot of the fix (`420dddaa`): **2026-08-28T21:55:15Z**. Era split on `submitted_at`.

| population | n | got a `venue_ticker` | on a FULL-GAME series |
|---|---|---|---|
| LIVE kalshi, `segment != full` | 37 | 5 | **5 / 5 = 100%** (`KXMLBTOTAL`) |
| — of those, PRE-boot | 14 | 5 | 5 |
| — of those, POST-boot | 23 | **0** | 0 |
| PAPER kalshi, `segment != full` | 70 | 5 | 5 (`KXMLBTOTAL`) |
| — POST-boot | 45 | **0** | 0 |
| LIVE polymarket, `segment != full` | 6 | 6 | 6 (`aec-` segment-less slug) |
| — POST-boot | **0** | 0 | 0 |

The 5 live Kalshi fills were submitted **2026-08-28T05:17:26Z .. T05:49:17Z**,
~16 hours BEFORE the fix booted. They are the same five already named in
`state_kalshi.md`: `LADDET-3`, `PHILAA-3`, `MIAWSH-3`, `TEXMIL-3`, `LADDET-4`.
The 5 paper rows are their paper twins.

All **10** `settled_by="venue"` rows in `reports/segment_regrade/manifest_2026-09-05.json`
fall on 2026-08-26 and 2026-08-28. **Zero on any later date.** The re-grade
agent's "venue outcome equals our FULL-GAME grade on 9 of 10" is a correct
reading of a real defect — the venue matched full-game because a FULL-GAME
contract is what we held. It is evidence about 2026-08-28, not about today.

## 3. The join reads `segment`, at the one choke point every caller shares

`syndicate/features/shared/kalshi_board_join.py`. `kalshi_ticker_resolver()`
reads nothing but the `matches` list, and `matches` has exactly **two**
`matches.append` sites — the game-line branch and the prop branch. On the
deployed SHA both are immediately preceded by:

    if not _segments_agree(row, verdict):
        _refuse(REASON_SEGMENT_MISMATCH)
        continue

`_segments_agree` compares `segment_for_board_row(row)` against
`segment_for_series(verdict["series"])`, refusing outright when the series
carries an unmappable segment marker. `_match_key`/`_row_key` carry `segment` too.

Present by CONTENT on all three live services:

| service | live SHA | finished | `_segments_agree` |
|---|---|---|---|
| refresh-worker | `933e9bebf154` | 2026-09-05T23:57:12Z | 3 occurrences, both append sites guarded |
| live-odds-worker | `7f197639cc97` | 2026-09-05T23:13:56Z | same |
| web | `3cb5b4ba6750` | 2026-09-05T23:00:51Z | same |

## 4. The guard is FIRING, not merely deployed — 257 refusals in 30h

`segment_has_no_matching_series` on the running refresh-worker, 2026-09-04T18:54Z
.. 2026-09-06T00:48Z: **38 join ticks carrying the counter, 257 refusals total**,
on both emitters (`[kalshi_odds] BOARD_JOIN` and `[portfolio_commit]
KALSHI_BOARD_JOIN`), every few minutes, right now.

## 5. THE CONFOUND THIS NEARLY DIED ON — stated because the null alone proves nothing

All 23 post-boot live refusals read `OrderBuildError: no_venue_ticker` on
`totals_alt` / `spreads_alt` / `h2h_3_way`. **Those same three markets also
refused `no_venue_ticker` PRE-boot, 9 of 9.** The refusal reason therefore does
not discriminate: it is what an unmapped Kalshi market does regardless of segment.

Worse, the discriminating shape is absent. Every one of the 5 mis-fills was
plain `market=totals`, and there is **not one post-boot segment order on plain
`totals`** — so the post-boot cohort never exercised the vulnerable path.
Post-boot live Kalshi on plain `totals`: 46 orders, 0 segment, 46 full, 40 with
tickers (39 `KXMLBTOTAL`) — the join is alive and matching full-game rows on
exactly that market.

Read alone, "0 of 23" is consistent with the guard working AND with nothing of
the vulnerable shape having been attempted. **Only §4 separates them**: segment
rows do reach the join, continuously, and are being refused there. That is the
load-bearing measurement in this document.

## 6. The hypothesized mechanism is confirmed — as history

`kalshi_catalogue.py` records `KXMLBTOTAL` hand-registered after a user
confirmation on **2026-08-25**, because the title gate missed it and "an MLB
`totals` board row had nothing to join to and every Kalshi order refused
`no_live_price`". The mis-fills are **2026-08-28**. So yes: registering the
full-game total is what gave a segment board row a contract to bind to. The
fix put `segment` in the key three days later.

## 7. Side finding, unasked: the guard bought safety, not capability

**No order in the entire 2,853-order population has ever carried a `KXMLBF5*`
ticker.** Segment execution on Kalshi is 0-for-everything — the fix converted
wrong fills into no fills, not into correct fills.

- `first5` is executable in principle (`KXMLBF5TOTAL`/`KXMLBF5SPREAD`/`KXMLBF5`
  are all mapped in `_SERIES_SEGMENT`) and never has been. Every first5 order
  attempted is `totals_alt`/`spreads_alt`, which map to no Kalshi board market.
- `first3` is **inherently unexecutable on Kalshi**: `_SERIES_SEGMENT` has no
  first3 entry and Kalshi offers no first-3-innings series (it has
  `KXMLBINNINGTOTAL`, per inning). A first3 row can only ever refuse.

## 8. Write-back: the exclusion is right, and the reason is stronger than stated

The 10 `settled_by="venue"` rows must be excluded from any write-back — not
merely because a venue settlement outranks our inference, but because **for the
5 Kalshi rows the contract we HELD was a full-game contract**, so the venue's
grade is the correct grade of the bet actually owned. The manifest currently
proposes `outcome_changed=True` on `KXMLBTOTAL-26AUG281840LADDET-3`
(`lost` -> `won`); applying that would invent P&L that no position earned.

## What is NOT established

- I did not break the 257 refusals down into "board row disagrees with contract"
  vs "series carries an unmappable marker". Both return False from
  `_segments_agree` and the counter does not separate them.
- No post-boot segment order has reached the venue, so the fix remains **proven
  to REFUSE, still never proven to have CORRECTED a fill.** That distinction is
  unchanged from the original entry; what changed is that the refusal is now
  observed continuously in production rather than only at boot.
