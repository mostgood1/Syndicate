# Findings 2026-11-14 -- the board's market-gone filter and the mid-build pull (`#802`)

Lane `board-market-gone-snapshot-age`, session 35bdf3a7. User: "Do this task here: Stop the board dropping NFL props as
market gone". Follows `findings_2026-11-13_cheat_sheet_section_assessment.md` section 7, which left one question open:
were the dropped rows skipped by the fresh pull, or re-looked and judged on an old age?

## 1. Answer: re-looked, judged on an old age

`_drop_market_gone_rows` judges each row's `quote_seen_age_seconds` against a reference (`_sweep_reference_age`) read
from the state file AT THE DROP STEP. The row's age was computed when the shortlist built that sport's grid
(`pipeline/layer2_shortlist.py`, the `build_book_grid(quote_rows, ..., last_seen=last_seen)` call), earlier in the
same board build. A pull landing between the two re-stamps the row's own key; the reference then says a pull looked
seconds ago, the row still says ~1,500 s, and every single-line prop group (no other line to count as a sibling)
classifies `market_gone`.

The 11-14 6:38 AM CST drop, per NFL board build (`builds_window.py`, refresh-worker log, UTC):

| build | NFL rows | `MARKET_GONE_DROPPED nfl=` | 11-15 file at the drop step |
|---|---|---|---|
| 12:35:26 | 1,216 | 65 | newest 490 s, reference 943 s |
| 12:38:36 | **883** | **454** | newest 17 s, reference 17 s (drop step 12:38:20) |
| 12:42:21 | 1,276 | 6 | newest 213 s, reference 213 s -- the SAME pull |

`ODDS_SWEEP_LAUNCHED sports=nfl,...` at 12:37:55Z (live-odds-worker). `fetch_nfl_oddsapi_props_local.py:620-641`
takes one `captured_at` after fetching and writes the week shard and every kickoff-date shard immediately, so the pull
was whole when the 12:38:20Z drop step read it, and the 12:42Z build recovered with no new pull. Skipped rows would
have stayed dropped until the next pull 25 min later; these came back one build later.

## 2. Second cause found on the way: night games judged by the wrong file

The drop asked the row's UTC commence date and the board's date. The NFL/NCAAF prop writers file by the CENTRAL
kickoff date (`odds_book_quotes.kickoff_shard_date`). For a kickoff after 6 PM CST the UTC date is the next day:
replayed on the live 11-14 board, 133 of 1,224 served NFL rows (SNF 01:20Z, MNF 01:15Z) were judged by a file that
did not hold their group, which reads as "no sibling seen" and so `market_gone` once stale. The same UTC-vs-Central
class as `#801` (another session's NCAAF night-game join, `40d5d6a4a`).

## 3. The fix (branch `session/board-market-gone-snapshot-age`, local: not pushed, not loaded)

- `_index_own_looks` / `_row_own_look_age`: when the judging file last looked at the row's own book and line (selection
  left out: the board's side and the log's `selection` are different vocabularies). Re-looked under 900 s: kept.
  Older: classified on that age. No book or no entry: the old rule, unchanged.
- The Central kickoff-date file is added to the files asked. Only added: a file judges only if it holds the group.
- `MARKET_GONE_RELOOKED_KEPT <sport>=N total=N of M`, its own line, always printed: the rows the grid age alone would
  have dropped. `STALE_ROW_CAUSE` uses the same read, so it does not call a kept row `market_gone`.

Tests (`tests/test_layer2_market_gone_snapshot_age.py`, 8): the mid-build case drops 72 of 72 on the old code and 0 on
this; the night-game case fails with the Central date removed and passes with it; a row the pull did not re-look at,
another book's look, and an old re-look still drop. 87 market-gone / stale-row tests and 211 tests driving
`build_layer2_shortlist` pass.

Replay on the live board (read-only, `own_key_replay.py`, 15:39Z 11-14): 1,224 of 1,224 served NFL rows and 1,259 of
1,259 NCAAF rows find their own key in the judging file (1,091 of 1,224 NFL before the Central date was added).

## 4. The rest of the week's "drops"

Of 176 NFL builds 11-06..11-14 that fell below 75% of the build before (`spike_check.py`): 46 are this filter; **70
are the return from a ONE-BUILD SPIKE** -- the build before was itself > 1.33x the one before it, mostly to 1,800-2,000
rows (2,000 looks like a cap), so no row was lost from the normal level; 60 are other and not traced. What builds
~2,000 NFL rows about hourly is not traced.

Scripts, read-only over the fleet's logs, state files and served board: `C:\tmp\edge-analyses\nfl-shortlist-drop\`
(`builds_window.py`, `own_key_replay.py`, `own_key_replay_ncaaf.py`, `key_peek.py`, `spike_check.py`,
`gone_vs_drop.py`).
