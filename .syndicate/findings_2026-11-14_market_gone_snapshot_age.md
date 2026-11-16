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
## 5. Loaded 11-14 19:55Z; first reading

Fleet `2c230f318`, refresh-worker pid 958200 (deploys.md 2026-11-14 19:54:59Z). The first build with a fresh NFL pull
on the new code (20:16:22Z drop step, references 64-73 s): 0 NFL rows dropped, 332 kept by the new branch, board 1,246
-> 1,189. The same shape on the old code at 18:49:53Z (reference 27 s): 418 dropped, 1,105 -> 752.

The 2,000-row NFL builds (19:00:56Z, 20:20:12Z) carry no 11-14 reference and ~2,500 openings against ~7,750: most likely
the 11-15 board date's build, with two dates in rotation, and so the 70 "spike returns" in section 4. Seen on these
builds, not traced. Owed: the 11-15 Sunday tally with `builds_window2.py` (which skips the process-list log lines;
they quote every running command line, this script's own patterns included).

## 6. The Sunday tally (11-15)

Rule registered 2026-11-14 (lanes.md). Verdict: **FALSIFIED -- one clear signature build on the fixed code: 7:34 AM CST 11-15 (pregame), 164 NFL rows dropped on a fresh pull (reference 54 s), `kept=1`, board 1,383 -> 1,221 -> 1,390 next build.**

- **Window** 11-15 12:00 AM .. 11:00 PM CST (06:00Z 11-15 .. 05:00Z 11-16), refresh-worker.log.1 + refresh-worker.log. Read-only, nice 19.
- **Command:** `wsl -d Ubuntu-24.04 -- nice -n 19 /home/amyn/.venvs/syndicate/bin/python /mnt/c/tmp/edge-analyses/nfl-shortlist-drop/sunday/sunday_tally.py 2026-11-15T06:00 2026-11-16T05:00 --builds > C:\tmp\edge-analyses\nfl-shortlist-drop\sunday\sun1115.txt` (rc 0, 300 builds).
- **Code check:** fleet checkout `10094eae0`; `git merge-base --is-ancestor 1f54452c6 HEAD` YES; `MARKET_GONE_RELOOKED_KEPT` in `pipeline/layer2_shortlist.py` 1; refresh-worker pid 2053259 (since 01:28:28Z 11-15, 7:28 PM CST 11-14). The kept line is missing on 0 of 300 builds, so every build ran the fix.
- **Builds by board date:** 11-14 15, 11-15 268, 11-16 11, no NFL reference 6.
- **Fresh builds** (largest NFL file reference < 150 s): 42 of 300, 22 of them in-play (live_rows > 0; the first NFL game went live ~8:37 AM CST).
- **Gone on fresh:** median 9, max 276; > 65: 9; > 150: 7. **Kept on fresh:** median 0 (it was in the hundreds on the old-row fresh builds: 390 at 12:36 AM, 362 at 5:48 AM; 102 at 9:39 AM, 87 at 9:08 AM).
- **Fresh builds with gone > 65** (time CST, board, rows prev -> this -> next, gone, kept, live_rows, ref):
  - 7:34 AM, 11-15, 1,383 -> 1,221 -> 1,390, gone 164, kept 1, live 0, ref 54 s. **SIGNATURE.** Pregame. The build before (7:31 AM) judged a 1,460 s reference; a pull landed between them -- the #802 shape. Next build gone 0.
  - 8:08 AM, 11-15, 1,234 -> 1,286 -> 1,250, gone 116, kept 14, live 0, ref 50 s. Inside an 8:01-8:35 AM run of 114-165 dropped on every build (pre-drop 1,419 at 7:58 AM), ending at the first live game's kickoff. Stayed down; listed.
  - 8:54 AM, 11-15, 1,367 -> 1,196 -> 1,186, gone 146, kept 0, live 54, ref 95 s. In-play; 146-154 dropped for 4 builds, back at 9:08 AM (1,373, kept 87). Listed.
  - 9:28 AM, 11-15, 1,107 -> 1,148 -> 1,147, gone 187, kept 1, live 45, ref 83 s. In-play run 9:25-9:35 AM (pre-drop 1,351 at 9:22 AM). Stayed down.
  - 9:31 AM, 11-15, 1,148 -> 1,147 -> 1,143, gone 187, kept 1, live 41, ref 25 s. Same run. Stayed down.
  - 9:35 AM, 11-15, 1,147 -> 1,143 -> 1,331, gone 187, kept 1, live 39, ref 25 s. Last build of the run; next build back to 98.5% of 1,351. Counts as a signature by the registered rule, but it is the 4th straight build of an in-play drop, which looks more like a suspension lifting than #802. Not decided.
  - 9:56 AM, 11-15, 1,280 -> 1,119 -> 1,022, gone 276, kept 1, live 31, ref 101 s. In-play run 9:56-10:07 AM. Stayed down.
  - 9:59 AM, 11-15, 1,119 -> 1,022 -> 1,014, gone 264, kept 2, live 50, ref 67 s. Same run. Stayed down.
  - 10:04 AM, 11-15, 1,022 -> 1,014 -> 1,012, gone 260, kept 2, live 44, ref 58 s. Same run. Stayed down (back at 10:11 AM, 1,261, after a non-fresh build).
- **Falls > 25% vs the same board date's previous build:** 6, all on board 11-15 and all with gone 0 (so none is this filter); gone > 150: 0. 3:40 PM 1,080 -> 761 -> 1,070; 4:05 PM 1,018 -> 753 -> 960; 4:15 PM 960 -> 331 -> 946; 5:11 PM 839 -> 401 -> 679; 8:04 PM 411 -> 195 -> 366; 8:24 PM 366 -> 211 -> 370. Each a non-fresh in-play build (references 8,329-22,797 s) with live_rows swinging (441, 410, 19, 59, 4, 20). Not traced.
- **The script overcounts.** It prints 6 signature builds. Its recovery test compares the next build with the build just before, which inside a run of drops is itself a dropped build. Against the last build before each run, 2 meet the rule: 7:34 AM and 9:35 AM. 9:28, 9:31, 9:59 and 10:04 AM stayed down. The verdict does not change: 7:34 AM alone falsifies.
- **Old code, Sunday 11-08** (the instrument check, same script): FALSIFIED by 3 signature builds, 4:09 AM (373 dropped, 1,490 -> 1,120 -> 1,502), 5:07 AM (384) and 7:10 AM CST (324), each back next build; one in-play build at 10:05 AM CST dropped 227 and stayed down.
- **Reading:** the fix cut the pregame signature from 3 builds of 324-384 rows (11-08) to 1 build of 164 (11-15), but did not remove it. The 7:34 AM build's 164 rows were judged on a fresh pull and only 1 was saved by the own-look branch.
- **Owed (lane stays OPEN):** trace which 164 rows the 7:34 AM build (drop step 13:34:06Z) dropped, and why their own book-and-line look in the 11-15 NFL state file (32,582 keys, newest 19 s) did not keep them. Decide whether 9:35 AM is #802 or an in-play suspension lifting. Fix the tally's recovery test to compare against the last pre-drop build.
- **No change made:** no code, env, restart or deploy.
