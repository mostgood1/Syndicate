# College live quotes read stale because the grid compares timestamps as TEXT (todo #844)

`[2026-11-18, lane ncaab-total-overprojection; user "count books per game on the stale NCAAB quotes"; read-only, fleet]`

## Question

The rail monitor's 11-18 2:27 PM CST reading: the one live NCAAB game, Rutgers @ Notre Dame, had 0 of 9
rows priced within 2 minutes, with quotes about 150 s old at pricing. Is that thin book coverage?

## Answer: no. The books were fresh; the grid's row age reads the wrong book

### 1. Book coverage per game (quote log, minute by minute)

Script `C:\tmp\ncal816\stale_books.py`, output `C:\tmp\ncal816\stale_books_ncaab_2026-11-17_2026-11-18.json`.

- **Source:** the fleet's quote log, `ncaab_source/tracking/book_quotes/<date>.jsonl`, a change log stamped by each book's own clock.
- **Freshness:** a book is fresh at minute t if its newest captured price move was within 120 s of t.
- **Window:** commence + 5 min to the earlier of commence + 130 min and the last live quote.
- **Population:** 57 NCAAB games quoted live, 55 on 11-17 and 2 on 11-18. Only games whose Central kickoff date matches the file are kept. Without that filter, 14 games from 11-16 and 11-17 had landed in the 11-18 file.

| full-game market | stale share of live minutes, median per game | games stale for at least 50% of minutes | fresh books, median | newest book's age, median |
|---|---|---|---|---|
| moneyline | 18.3% | 12 of 57 | 3.5 | 55 s |
| spreads | 10.6% | 0 of 57 | 4.5 | 50 s |
| totals | 8.3% | 0 of 57 | 4.5 | 47 s |

- **Books quoting live:** median 9 per game (range 7–12). Books fresh at some point: median 9 (range 7–10).
  - Present in almost every game: Bovada, DraftKings, BetMGM, BetRivers, Fanatics, Caesars, FanDuel, Polymarket, Kalshi.
  - BetOnline, LowVig, Circa and BetUS quote few games and are almost never fresh.
- **The 12 moneylines stale at least half the time are blowouts**, e.g. Rider @ Miami 96.8% and Jackson St @ Baylor 99.1%. Books stop moving a lopsided moneyline. The same games' spreads and totals were stale only 2–19% of minutes.
- **Rutgers @ Notre Dame on 11-18:**
  - moneyline 6 fresh books (median) and stale 2.7% of minutes;
  - spreads 5 fresh books, totals 5;
  - newest book's age, median about 40 s.

### 2. Why the rail saw ~150 s: the row age takes the max over timestamp STRINGS

- **The code:** `syndicate/features/shared/book_grid.py:1158-1159` (since `e707242165`, 2026-08-07) builds `stamps = [c[s]["observed_at"] ...]` and takes `newest = max(stamps)`. The row's `age_seconds` = `memo.age(newest)`.
- **The two formats in the college grid:**
  - sportsbooks: `'2026-11-18 20:58:05+00:00'` (space);
  - Kalshi `'2026-11-18T20:55:57Z'` and Polymarket `'2026-11-18T20:41:51.488325+00:00'` (`T`).
- **Why that matters:** `T` (0x54) sorts above a space (0x20), so a venue stamp wins the `max()` whatever its time.
- **Who reads it:** the live gate, `live_gameline_join.py:2735`, `quote_age_verdict(row.get("age_seconds"), ...)`, with a 120 s ceiling for NCAAB/WNCAAB. It refuses the row as stale.
- **Seen on the fleet's grid, `book_grid_2026-11-18.json` generated 20:58:22Z, Rutgers @ Notre Dame:**
  - moneyline row age 143.6 s = Kalshi's 143.6, while FanDuel was 14.6 s, BetMGM and Fanatics 15.6 s, DraftKings 32.6 s;
  - spreads 6.5 row age 2004.6 s, while FanDuel was 15 s and Caesars 17 s;
  - spreads 4.5 row age 143.6 s, while BetMGM was 115 s.
- **The size of it** (script `C:\tmp\ncal816\rowage_bug_h2h.py`): full-game moneyline, where the grid row is the whole market and the quote log rebuilds it exactly, per live minute.

| sport, slate | games / live minutes | fresh by TIME | fresh by the grid's TEXT max | wrongly stale, as a share of the fresh minutes |
|---|---|---|---|---|
| NCAAB 11-17 + 11-18 | 57 / 6,112 | 81.2% | 25.5% | **68.6%** (3,407 min) |
| WNCAAB 11-17 | 29 / 2,150 | 58.4% | 21.8% | **62.7%** (787 min) |
| NBA 11-17 | 5 / 618 | 95.5% | 95.5% | 0% |
| NHL 11-17 | 11 / 1,360 | 32.1% | 32.1% | 0% |

- **NBA and NHL are clean** because their sportsbook stamps use the same `T` format as the venues' (a venue stamp wins the max 100% of minutes there, but comparing the text then matches comparing the time). The college sportsbook stamps use the space format.
- **Spreads and totals are hit too** wherever a venue quotes the row's line: Kalshi quoted 10 of the 24 in-play rows in the snapshot. Not measured: the grid row is per line, and the quote log does not rebuild it exactly.

### What it costs (believed, not measured)

- **The direction:** the bug can only make a row look OLDER, never fresher. So it refuses college live rows that a fresh sportsbook was pricing, and it never lets a stale row through.
  - Fewer college live game-line flags and fewer priced rows: on moneylines, about two thirds of the fresh minutes are lost.
  - The flags that do fire are on rows where no venue quotes, or where the venue is the newest.
- **What has not been measured:** the money effect. That needs the flags and bets the gate refused, priced against their outcomes.

## The fix as first proposed (superseded by the BUILT section below)

- **Read side:** take the newest stamp by parsed time, e.g. `max(stamps, key=_parse_ts)`, falling back to the text when parsing fails. This fixes today's mixed shards too.
- **Optionally also the write side:** normalise `book_updated_at` to one format in `odds_book_quotes._normalize`.
- **Tests:** a cell set with a space-format sportsbook stamp newer than a `T`-format venue stamp. The row age must equal the sportsbook's, and the current code fails this.
- **It is a BETTING CHANGE** (it changes which college live rows the gate prices), so it loads in a betting-change window (`.syndicate/betting_change_windows.md`, next Tue 11-24 2:00-7:00 AM CST) unless the user calls it a broken money path.
- **The #816 grade** (window 11-17..11-23) is unaffected by a load in the 11-24 window, since that load comes after the window's data ends.

## BUILT, on main `25a5e480d`, DEFAULT OFF `[2026-11-19 00:49Z, 6:49 PM CST 11-18]`

- **User decisions:** "Yes, build it" in this session, then "get 844 landed default off for 11-24", relayed verbatim from session `product-optimization-program`. Window rule 2 (`.syndicate/betting_change_windows.md`) requires the same.
- **The code:** `book_grid._newest_stamp` picks the stamp that is latest in TIME, using a cached `_stamp_instant` parse. Equal instants keep the text max. Unparseable stamps are skipped when another stamp parses, and the text max stands when none do.
- **The switch:** `SYNDICATE_BOOK_GRID_NEWEST_BY_TIME=on` (also 1 / true / yes). Absent, or anything else, keeps the text max exactly.
- **Ownership:** the line was borrowed from lane `ncaaf-grid-build-speed` under a LOAN recorded in both blocks, and is now returned.
- **Tests:** `tests/test_book_grid_newest_stamp.py`, 22 cases. They cover off != on, absent = the old behaviour, offsets, ties, unparseable stamps, and the live gate pricing the fixed row. 5 fail on the old text max. 402 grid, gate and venue tests pass.
- **A/B on the fleet's real shards** (worktree code, key absent vs `on`, one fixed `now`; `C:\tmp\ncal816\grid844_ab.py`):

| sport, shard, now | grid rows | rows changed | rows crossing the 120 s gate, stale to fresh |
|---|---|---|---|
| NBA 11-17, 03:30Z | 3,885 | 0 (BYTE-IDENTICAL) | 0 |
| NHL 11-17, 02:30Z | 1,470 | 0 (BYTE-IDENTICAL) | 0 |
| NCAAB 11-17, 02:00Z | 2,139 | 190 | 58 |
| NCAAB 11-18, 20:58Z | 1,298 | 140 | 13 |
| WNCAAB 11-17, 01:30Z | 270 | 21 | 3 |

- **What changed:** only `updated_at` and `age_seconds`, and only on rows with a Kalshi/Polymarket cell. The age always got younger: 0 rows got older and 0 crossed fresh to stale.
- **Caveat:** the A/B's capture filter compares `captured_at` as text, the same flaw, so a "now" snapshot may include some later space-format rows. Both arms read identical inputs, so the A/B holds.
- **Roles that must carry the key:**
  - refresh-worker: the book_grid artifact build in `run_refresh_worker.py`, and `build_layer2_shortlist` in the board child, which inherits refresh-worker's env;
  - web: the inline builds in `/api/board/book-grid` and `/api/board/cross-book`;
  - live-odds-worker builds no grid.
  - A global key in `local_production.env` covers all of them, at a drained `down`/`up`.
- **Betting change:** yes, conservatively. It changes which college live rows the live gate prices. Live orders are not traced. The window package's money trace may support `no`, and that is the user's call at the window.
- **PRE-REGISTERED PREDICTION, before any load:**
  - **P1 reachability:** refresh-worker's first NCAAB grid after load has at least one row with a venue cell and a sportsbook-spelled `updated_at`. Before load there are 0, because a venue cell always wins.
  - **P2:** NCAAB full-game moneyline rows with `age_seconds` <= 120 rise from about 25% (25.5% of live minutes on 11-17/18) to >= 70% on the first full evening slate. Fresh by time was 81.2%.
  - **P3:** the NBA and NHL grids are unchanged.
  - **P4:** NCAAB/WNCAAB `stale_quote` refusals per build fall, and priceable rows per build rise.
- **Load:** proposed for the Tue 11-24 betting-change window (2:00-7:00 AM CST) through the window package. Loading needs the user's yes.

## READING 2026-11-25 ~1:10 AM CST: the first evening after the 11-24 load (CHANGE D), rail monitor R-B; INTERIM, P2/P3 owed

CHANGE D loaded in the 11-24 window batch: `BOOK_GRID_NEWEST_BY_TIME=on` on refresh-worker, live-odds-worker, the web master and both web workers (deploys.md `2026-11-24 08:30:10Z`). Read-only, nice 19.

**Why only one sample.** The runbook planned the #844 grid sampler at every reading of the first evening. In lean mode the Windows task takes the readings, and it never ran the sampler, so the 11-24 evening has no samples. I took one at 06:58:57Z, with 2 NCAAB games still live. The grid it read was built at 06:02:44Z: after midnight the slate rolled, and the 11-24 grid stopped rebuilding. From 11-25 the tick runs the sampler at every reading, for the 11-25 and 11-26 slates (`C:\tmp\railmon\railwatch\tick.py`, appending to `C:\tmp\railmon\p844_<day>.jsonl`).

| # | prediction | 11-19 baseline (22 NCAAB samples with h2h rows, 19:36Z-06:19Z) | 11-24 | verdict |
|---|---|---|---|---|
| P1 | venue rows with a sportsbook-spelled `updated_at` > 0 | 22 of 1,213 venue rows (1.8%) | **7 of 9** (1 sample) | **PREDICTED** (one sample) |
| P2 | h2h rows fresh by row age >= 70% over the evening, near fresh-by-cell | 44 of 141 (31.2%) vs 113 of 141 by cell (80.1%); 304 mismatch rows | 3 of 3, cell 3 of 3, mismatch 0 of 34 rows (1 sample) | **OWED** (11-25 evening) |
| P3 | NBA / NHL grids unchanged | NBA mismatch 0 (306 rows) | NBA 0 in-play rows at the sample | **OWED** (11-25 evening) |
| P4 | NCAAB / WNCAAB stale-quote withholds per build fall; priceable per build rises | see below | see below | **NEITHER** |

**P4, from the `LIVE_GAMELINE_BUILD` lines of `refresh-worker.log*`.** Window 5:30-10:30 PM CST each night. The stale-quote reason is `quote_older_than_live_pricing_ceiling`. Reader: `C:\tmp\railmon\p844_p4.py <lo> <hi>`; output in `C:\tmp\railmon\p844_p4_1124.txt`.

| | NCAAB 11-19 | NCAAB 11-24 | WNCAAB 11-19 | WNCAAB 11-24 |
|---|---|---|---|---|
| builds | 389 | 432 | 383 | 343 |
| rows considered per build | 394 | 861 | 69 | 69 |
| stale-quote withholds per build | 147.7 | 318.2 | 51.5 | 30.7 |
| stale share of rows considered | 37.4% | **37.0%** | 74.2% | **44.6%** |
| priceable per build | 17.5 | 55.8 | 9.2 | 1.6 |
| priceable share of rows considered | 4.4% | **6.5%** | 13.2% | **2.3%** |

- **NCAAB:** the raw count rose because the slate was twice the size (861 rows a build against 394). The stale share is flat (37.4% to 37.0%). The priceable share rose from 4.4% to 6.5%.
- **WNCAAB:** the stale share fell sharply (74% to 45%). But the priceable share fell too (13% to 2%), because `no_live_gameline_projection` went from 1,248 to 9,272. Those games had no live model at all; on the rail that is mostly `no_margin_anchor` (no closing full-game spread in the quote log), which is not #844's doing.
- So P4 reads NEITHER. Its two halves split by sport, and both nights' slates differ in size and in model coverage.
- **What #844 changes, and so what P4 can show.** #844 changes the row's age stamp, picking the newest by time. The join's quote-age ceiling is per quote, so a fall in NCAAB stale withholds was never guaranteed. P1 and P2 are #844's own test.

**Owed:** the 11-25 close grades P2 and P3 from `p844_2026-11-25.jsonl` (every tick while NCAAB is live), then writes the deploys.md READING entry and the todo #844 verdict.

## READING 2026-11-26 11:35 AM CST: the 11-25 evening, rail monitor R-B; FINAL (P2, P3 graded)

Reader: `C:\tmp\railmon\p844_2026-11-25.jsonl`, written by `p844.sh` at every Windows-task tick, 48 NCAAB and 48 NBA samples, 16:04Z 11-25 to 07:44Z 11-26. After midnight the 11-25 NCAAB grid stopped rebuilding at 06:02Z, so the last 6 samples read one grid: the NCAAB sums below count each distinct grid once (43 of 48). Read-only.

| # | prediction | 11-19 baseline | 11-25 | verdict |
|---|---|---|---|---|
| P1 | venue rows with a sportsbook-spelled `updated_at` > 0 | 22 of 1,213 (1.8%) | 1,053 of 2,696 venue rows, > 0 in 42 of 48 samples | **PREDICTED** |
| P2 | h2h rows fresh by row age >= 70% over the evening, near fresh-by-cell | 44 of 141 (31.2%) vs 80.1% by cell; 304 mismatch rows | **274 of 352 (77.8%)**, cell 274 of 352 (77.8%), **0 mismatch** rows over 43 grids | **PREDICTED** |
| P3 | NBA / NHL grids unchanged | NBA mismatch 0 | NBA mismatch 0 over 48 samples (22 with rows, 63 h2h rows) | **PREDICTED** (NBA; NHL is not sampled) |
| P4 | NCAAB / WNCAAB stale-quote withholds per build fall | -- | 11-24 (interim above) | **NEITHER** |

- **#844 does what it was built for.** The row's age now reads the newest stamp by time: fresh by row and fresh by cell agree on every row (0 mismatches), against 304 mismatches on 11-19.
- P4 was never #844's own test (the join's ceiling is per quote), and its two halves split by sport.
- Recorded in deploys.md 2026-11-26 17:35Z (betting change: no) and todo #844.
