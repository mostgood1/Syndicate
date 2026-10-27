# FINDINGS -- Kalshi combo capture: what it costs to capture Kalshi's same-game combos forward, and how (lane `kalshi-combo-capture`, 2026-10-27)

Todo **`#742`** (Decision Engine `#736`, E4 Stage 2 = `#740` (d)). A capture, not a test: E4's registered Stage 2 is
the test, and this produces its price data. Read-only: Kalshi PUBLIC unauthenticated GETs only, from a dev machine
at Idle priority into a scratch data root. No deploy, restart, env edit or fleet process.

| | |
|---|---|
| **Code** | On main: `b994e9cf` (v1), `ce5c467c` (v2 after the dry run), `da6dbdc3` (streaming tally), `af6e4c14` (adaptive slices) and `883edd96` (remainder slices). `scripts/kalshi_combo_capture.py`, `tests/test_kalshi_combo_capture.py` (51 hermetic tests), and an INERT hourly job `kalshi-combo-capture` in `scripts/local_production.py` `SCHEDULED_JOBS`. |
| **Gate** | `SYNDICATE_KALSHI_COMBO_CAPTURE=on`. Absent = OFF: no request and no file (tested `off != on`). |
| **Store** | `<data root>/reports/intelligence/kalshi_combo_capture/`: `combos_<settled date>.jsonl.gz` (TRADED kept combos only, v2), `runs.jsonl` (counts every kept combo), `collections_<date>.json`, `state.json`. No retention rule in `artifact_retention.RULES` matches it. |
| **Reuses** | `kalshi_maker_shadow.public_get_json` (transport) and `read_trade_prints` (trades); `kalshi_catalogue.sport_for_ticker` / `game_date_from_ticker` / `event_blob_from_ticker` / `SERIES_OUT_OF_SCOPE`; `kalshi_board_join.soccer_competition_for_series` / `series_competition_verdict`; `kalshi_client.series_from_ticker`. No second client. |
| **Running?** | **No.** Where and how often is the user's decision (below). |

## What the probes measured (2026-10-27 13:13Z-14:43Z, public GETs, read from the clock)

| Quantity | Reading |
|---|---|
| Combos **created** (open, newest first) | 1,000 per ~11 s (14:22:33 -> 14:23:07Z, 3 pages): **~330k/hour**. 2,922 of 3,000 `is_provisional`; 95 had a `yes_ask` < 1, 78 had volume. |
| Combos **settled** on `KXMVECROSSCATEGORY` | **22,147** with close in 13:13-13:23Z (23 pages, 107.5 MB decoded); 914 with volume. |
| ... of which a same-game pair in a sport we model | **677** (3.1%): NBA 343, Serie A 148, NFL 123, MLB 106, NHL 84, NCAAF 49, EPL 16, Ligue 1 10, La Liga 4. **9** had volume. |
| Global `/markets/trades` | **65,191** prints in 13:16-13:26Z (66 pages, 2.54 MB wire / 19.95 MB decoded); 7,495 combo prints (11.5%), 5,326 distinct combo tickers. |
| `min_settled_ts` / `max_settled_ts` | Filter exactly: 414 rows in a 2-min window, **0 outside it**, every one `finalized`. Ordered newest settlement first. Close-to-settlement 6-55 s. |
| A finalized untraded combo's quote | **Zeroed**: `yes_bid_dollars` = `yes_ask_dollars` = `last_price_dollars` = 0.0000. |
| `/markets?tickers=` | Batches of 100 work; 250 returns HTTP 414. |
| gzip | Kalshi serves it: a 1,000-market page is 0.44 MB on the wire vs 4.53 MB decoded (10.4x). The platform's `http_compression` opener asks for it on every `urllib` fetch. |
| Combo series | `/multivariate_event_collections`: 1,406 collections. `KXMVENBASINGLEGAME` 1,113, `KXMVENFLSINGLEGAME` 223, `KXMVEMENTIONSSINGLE` 13, `KXMVENFLMULTIGAMEEXTENDED` 8 ... Markets settled 10-20..10-27: `KXMVECROSSCATEGORY` and its shard `KXMVECROSSCATEGORY0` only; the per-sport collections settled 0. |
| How far back settled combos list | `/historical/cutoff` `market_settled_ts` = 2026-08-28. A 2-min settled window returned rows at 3, 7, 14 and **30 days back (09-27)**, and none at 45 or 60 days. |

**Consequences for the design:**
- **Snapshotting quotes at creation is not affordable:** ~330k combos/hour is ~8k GETs/day and ~37 GB/day decoded, for a quote that is mostly an empty book.
- **The global trade stream is not affordable either:** ~9.5k GETs/day, and it carries no legs.
- **Listing SETTLEMENTS is:** every combo appears once, already `finalized`, with legs, result, `last_price` and `volume`. Only kept combos with volume need a trade read (`/markets/trades?ticker=`, one GET each).
- **The executable prices are the trade prints.** A finalized combo's quote is zeroed, so `quote_at_capture` is stored as listed but is not a price.
- **"Cannot be paged back" holds for TRADES, not for settled combos.** The listing by settlement time reaches back ~30 days, at the same cost per day of data as forward capture. A backfill is possible (decision below).

## Design (what a run does)

1. Daily: snapshot `/multivariate_event_collections` (8 GETs), naming every combo series the job does not sweep.
2. Per combo series, sweep settlement time from a persisted watermark up to now - 300 s, in integer-second slices (`KXMVECROSSCATEGORY` 15 min, the `0` shard 1 h, the per-sport collections 6 h and at most every 6 h).
   - The query asks for hi + 1. A row belongs to the slice holding floor(`settlement_ts`), so a sub-second settlement on a boundary is neither lost nor counted twice.
   - A slice is all or nothing: an unreadable page writes nothing and the watermark stays.
   - A slice needing more than 300 pages is split in half.
   - The run budget (900 pages, 30 min) is checked before a slice starts, so a slice is never cut short.
3. Keep a combo when two or more of its legs share a dated game segment (`26OCT27SACSAS`) in one scope:
   - US sports (MLB, NBA, WNBA, NHL, NFL, NCAAF, NCAAB): the sport;
   - soccer: the competition. Women's and second-tier families (`KXSERIEAWGAME`, `KXLALIGA2`) refuse.
   - Never paired: futures, `SERIES_OUT_OF_SCOPE`, broadcast `MENTION` series, Mobile Legends (`KXMLBB`), college baseball (`KXNCAABB`), tennis, crypto.
4. Tally every kept combo (by sport, league, and traded by leg count). Drop an untraded one: its finalized quote is zeroed, so it carries no price (`--store-untraded` keeps it).
5. Optionally (`--trades-max-legs N`, default 0 = none) read the public trade prints of traded kept combos of at most N legs. Each read is charged to the run budget.
6. Append the traded rows (one gzip member per slice) to `combos_<settled date>.jsonl.gz`. Write one `runs.jsonl` row per run: GETs by kind, pages, wire bytes, windows covered, and the tallies.

## Dry run

Public GETs from this dev machine at Idle priority, into scratch data roots; nothing on the fleet. Two legs over one
contiguous settlement window. The legs differ in what they store (v1 stored every kept row; v2 stores only traded
ones), but both list every settled combo, so the GET and kept counts compare.

### Sunday leg: settlements 2026-10-26 15:03:30Z -> 10-27 03:33:29Z (12.5 h; NFL Sunday, SNF, NBA), v1, no trade reads

Read 15:08-17:08Z on 10-27. The run stopped at its 2-hour limit; the 7,909 market pages covered 12.5 h of settlement time.

| Quantity | Reading |
|---|---|
| GETs | **7,917**: 7,909 market pages + 8 collections. **633 pages per settled hour.** |
| Bytes | **3.68 GB wire**, 35.5 GB decoded (9.6x gzip) |
| CPU | 7,218 s at Idle: **0.91 s per page**, almost all JSON decode |
| Settled cross-category combos | **5,481,380** (the `0` shard and per-sport collections: 0 in this window) |
| Kept (a same-game pair in a modelled sport) | **3,363,027 = 61%**. A long multi-game parlay almost always holds one. Monday 13:13Z kept 3.1%. |
| Kept AND traded | **484,887** (14% of kept). Every one has a non-zero `last_price`. |
| Kept by sport | NBA 1,996,096 · NFL 1,197,326 · soccer 298,653 · MLB 267,293 · WNBA 127,639 · NHL 87,233 · NCAAF 1,963 (a ticket with pairs in two sports counts in each) |
| Traded by sport | NFL 281,658 · NBA 159,645 · MLB 56,183 · soccer 35,766 · WNBA 12,674 · NHL 10,586 · NCAAF 215 |
| Soccer kept by league | Ligue 1 218,242 · La Liga 144,786 · Serie A 24,655 · EPL 9,370 · Bundesliga 7,411 · MLS 2,879 · UCL 1,439 · Championship 28 |
| Traded by leg count | 2: **21,737** · 3: 44,456 · 4: 55,917 · 5: 51,082 · 6: 47,711 · 7: 37,486 · 8: 33,088 · 9: 25,805 · 10: 24,308 · 11-15: 67,663 · 16+: 75,634 |
| Traded two-leg, by sport | NFL 13,411 · NBA 4,422 · MLB 2,772 · soccer 413 · NHL 362 · WNBA 357 |
| Traded PURE same-game tickets (every leg in one game) | **245,556**: NFL 189,699 · MLB 27,694 · NBA 23,053 · WNBA 3,281 · soccer 1,035 · NHL 794 |
| Settlement by hour (kept / traded) | 15-18Z 3-16k / 0.4-1.7k · 19-21Z 36-107k / 7.5-12.5k (NFL early games end) · 22-23Z 40k, 11k · 00Z 120k / 14k · **01Z 567k / 47k · 02Z 1.29M / 148k · 03Z (:00-:33) 1.09M / 241k** |

**Correction to this lane's own first sample.** A 4-hour trades-on run (settlements 14:35-18:34Z, 3,778 traded kept) had
**0** two-leg and **0** pure same-game traded tickets, and I read that as "Kalshi's traded combos are all multi-game
parlays". The full window has 21,737 two-leg and 245,556 pure SGP tickets traded. The sample ended before any NFL game
did. Absence in one window was not absence.

**What the trade reads add (the 3,778 read in that sample).**
- 3,053 (81%) printed once, 582 twice, 143 three or more times.
- `last_price` equalled the last print's YES price in 3,774 of 3,778.
- The prints' `count` summed to `volume_fp` in **all 3,778**.
- The first print came after `created_time` by p10 8.8 s, **p50 24 s**, p90 113 s and p99 1.8 h; 80% within 60 s.

So the listing's own `last_price`, `volume_fp` and `created_time` carry the price, the size and (for most) the time to
within a minute, with no trade read. A trade read is one GET per combo: on this window, 122k for tickets of 4 legs or
fewer and 485k for all, against the listing's 7,909 pages.

**Two defects the run exposed, both fixed on main.**
1. `report` collected a whole settlement date in memory. On the 3.36M-row store it reached 9 GB with 207 MB free on
   this host before I stopped it. The fleet shares the host; its supervisor and workers kept running (etime 10.9 h).
   `report` now streams (`ce5c467c`).
2. Trade reads were not charged to the run budget, so a run could exceed MAX_RUN_S and the lock's stale age. They are
   now charged (`ce5c467c`). A sweep also held every untraded kept row to the end of its slice: 1.25 GB working set on a
   peak slice. It now tallies and drops them (`da6dbdc3`).

### Monday leg: settlements 10-27 03:33:30Z -> 17:17:15Z (13.7 h), v2 defaults (store traded only, no trade reads)

Read 17:22-18:20Z on 10-27 (`ce5c467c` code), from the Sunday leg's watermark.

| Quantity | Reading |
|---|---|
| GETs | **5,550** market pages: 3,743 for `KXMVECROSSCATEGORY`, 7 for the `0` shard and the six per-sport collections (1 h each; **0 settled**), and **1,800 thrown away by 6 slice splits** |
| Bytes | **2.15 GB wire**, 22.3 GB decoded |
| CPU | 3,463 s at Idle: **0.62 s per page** |
| Settled / kept / kept and traded | 3,712,613 / 2,249,887 (61%) / **69,903** |
| Kept by sport | NFL 1,562,260 (Sunday-night and prop tickets settling Monday) · NBA 590,773 · MLB 186,951 · soccer 62,567 · NHL 49,478 · WNBA 4,244 · NCAAF 2,791 |
| Traded by sport | NBA 45,626 · NFL 18,382 · soccer 5,198 · NHL 4,286 · MLB 1,373 · WNBA 138 · NCAAF 139 |
| Traded by leg count | 2: **4,744** · 3: 7,978 · 4: 9,767 · 5: 7,761 · 6: 6,745 · 7: 5,002 · 8: 4,234 · 9: 3,351 · 10: 3,001 · 11-15: 8,915 · 16+: 8,405 |
| Stored | 69,903 rows in **8.7 MB** gzip (124 B a row) |

### Catch-up and settle-lag check (`af6e4c14` code)

- **Catch-up run.** Settlements 17:17:16Z -> 18:17:16Z, read 18:22-18:23Z.
  - **137 pages**, 0 splits, 0.51 s a page, **176 MB** peak working set (sampled every 5 s).
  - 15,585 kept and 1,329 traded.
- **Lag check.** The same hour was re-swept at 18:55-18:56Z, 33 minutes after the first read.
  - Kept **15,585 = 15,585**, traded **1,329 = 1,329**.
  - **0 missing, 0 extra, 0 with a changed traded flag** (135 pages, 213 MB peak).
  - Nothing settled into the hour after it was read about 6 minutes past its end, so `SETTLE_LAG_S = 300` lost nothing here.
  - This is one Monday-afternoon hour; a Sunday-night burst was not lag-checked.

### The reading: one contiguous 26.2-hour window (Sun 10-26 15:03Z -> Mon 10-27 17:17Z = 1.093 days)

It holds NFL Sunday, Sunday night football and the NBA slate. It does not hold Monday night football, and no
quiet weekday was measured. Read it as the HEAVY end of a week, not an average.

| Per day of settlement time | Reading |
|---|---|
| **GETs** | **12,322 spent**, of which 4,200 were split re-reads, so **~8,500 needed** with adaptive slices (`af6e4c14`). E4's "about 1,000" was 8-12x low. |
| Wire / decoded | **~3.7 GB / ~38 GB** a day without the re-reads (5.83 GB / 57.7 GB spent) |
| CPU | ~1.5 h a day of nice-19 CPU at 0.62 s a page |
| Disk (traded only) | ~508k rows, **~63 MB a day** gzip. The fleet disk has 772 GB free. |
| **Same-game combos (kept) per day** | NFL **2.52M** · NBA **2.37M** · MLB 416k · soccer 331k · NHL 125k · WNBA 121k · NCAAF 4.3k |
| **Traded same-game combos per day** | NFL **274.5k** · NBA **187.8k** · MLB 52.7k · soccer 37.5k · NHL 13.6k · WNBA 11.7k · NCAAF 324 |
| Traded two-leg per day | **24.2k**. All tickets of 4 legs or fewer: 132k. |
| Soccer kept by league (window) | Ligue 1 231,130 · La Liga 154,269 · Serie A 67,849 · EPL 11,933 · Bundesliga 8,477 · MLS 4,610 · UCL 1,498 · Championship 28 |
| Combo series other than `KXMVECROSSCATEGORY` | **0 settlements** (the `0` shard and six per-sport collections, read 1 h each) |

**What it means for E4 Stage 2.**
- The capture is not data-starved: about 245k traded pure same-game tickets on one NFL Sunday, and 1,035 in soccer.
- The binding cost is the LISTING, about 8.5k pages on a heavy day. All of it is spent learning about combos that are then dropped: 39% of settled combos have no same-game pair, and 86% of kept combos never traded.
- None of the `/markets` parameters this lane found filters on legs or volume. The ones that exist are series, close, created and settled windows, status and tickers.

## Decisions owed (user)

Nothing runs until the user chooses. Each option is public GETs only, at nice 19, into
`~/syndicate-prod/data/reports/intelligence/kalshi_combo_capture/` on the fleet.

1. **Where and how often.** Hourly in either case. Completeness does not depend on the cadence: settled combos stay
   listable for about 30 days, and the watermark resumes where the last run stopped.
   - **(A) The fleet's hourly supervisor job**, already in `SCHEDULED_JOBS`.
     - Steps: fast-forward the fleet to main at `883edd96` or later; append
       `REFRESH_WORKER__SYNDICATE_KALSHI_COMBO_CAPTURE=on` to `~/syndicate-prod/local_production.env`; supervisor
       `down` and `up`.
     - All of that is under `deploy_claim.py` and `deploy_preflight.py`. It is best done riding along with the next
       fleet fast-forward.
     - A run is capped at 900 pages and 30 min. A Sunday-night peak hour needs about 2,000, so the job falls behind
       on Sunday night and catches up on Monday.
   - **(B) A bridge now.**
     - A draft is at `C:\Users\tempadmin\AppData\Roaming\Claude\side-session-notes\local_668211d5-72d4-4559-97f9-20741e3d858a\kalshi_combo_capture_bridge.sh`. It is modelled on the maker-shadow bridge:
       `setsid`, nice 19, run from a git archive of main.
     - It runs the same command hourly, or 60 s after a budget-stopped run. It exits by itself once the supervisor
       job has run enabled.
     - It is a persistent fleet process, so it needs the user's OK.
2. **Trade reads.**
   - **Recommended: none** (the default). `last_price`, `volume_fp` and `created_time` carry the price, the size and
     the time to within a minute for 80% of combos.
   - The alternative is `--trades-max-legs 2`: about 24k more GETs a day on a heavy day, roughly 3x the listing. It is
     budget-charged, so it would slow the listing rather than overrun.
3. **Backfill.**
   - Settled combos list back about 30 days (to about 09-27 on 10-27), and that edge moves forward one day every day.
   - A **~30-day backfill** would make E4 Stage 2's "a month of capture" available in about two days rather than on
     about 11-27.
   - Estimate: 150k-250k GETs, 60-100 GB wire and 26-43 h of nice-19 CPU, all once. This is extrapolated from one
     heavy day plus a Monday-morning probe; no quiet weekday was measured.
   - It needs (B) or a manual run. Set `LOOKBACK_HOURS=720` on the store's first run; the watermark walks forward from
     the oldest day, so the edge is read first.
