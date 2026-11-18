# In-play recorder: Kalshi poll gaps, before and after (lane `inplay-recorder-discovery`)

Side session of `local_898e5510` (decision engine, todo #736). M3 (`.syndicate/findings_2026-11-17_m3_paper_book.md`)
replays paper bets against this recorder's Kalshi quotes, and a look with more than 10% of its bets unmarked is
`NOT_A_VERDICT`. On the 11-14 dev rehearsal, 8.7% of A1's bets were unmarked, and 72 of the 101 unmarked bets had their
next quote 13 to 80 minutes later. The brief blamed the fleet capture file's 8,000-market cap. The measurement below
finds a second cause, and it is the larger one.

All times CST unless marked Z. Tool: `scripts/inplay_poll_gaps.py <night dir>` (new, read-only).

## 1. Before: NCAAF Saturday 2026-11-14 (`C:/tmp/inplay_2026-11-14`, recorder at origin/main 5d13d68ab)

| metric | value |
|---|---|
| markets polled at least once | 5,014 (NCAAF 4,545, NBA 327, NHL 142) |
| quotes (rows) | 3,462,426 over 10:30 AM - 1:57 AM |
| per-market gap p50 / p90 / p99 / max | 24.4 s / 56.3 s / 322.0 s / 7,137.9 s |
| each market's largest gap, p50 / p90 | 560.1 s / 2,028.3 s |
| markets with any gap > 120 s | 4,129 of 5,014 = **82.4%** (NCAAF 87.9%, NHL 93.0%, NBA 0%) |
| decision instants with no quote in a 60 s window (M3's [t_d+10, t_d+70]) | **26.7%** (time-weighted over each market's quoted span; 11-16 weeknight: 2.0%) |
| Kalshi 429s | 1,552 |
| whole-loop stalls > 60 s | 0 |

**Cause of each gap > 120 s.** The tool rebuilds the poll loop's cycles. A cycle walks the sorted ticker list in
50-ticker batches; a new cycle starts when a batch's first ticker sorts before the previous batch's last. A gap is `list`
when some complete cycle inside it got past the ticker's place without returning it (the capture file had dropped it).
It is `starve` when no cycle reached that far. `list` is a floor: a dropped ticker in a region no cycle reached reads
`starve`.

| cause | gaps > 120 s | of which > 20 min | seconds |
|---|---|---|---|
| list (the 8,000-market cap) | 387 | 320 | 615,291 |
| starve (429 ends the cycle before the tail) | 90,485 | 3,750 | 33,530,685 |

**Why the tail starves.** The loop meant to average ~2.5 req/s. It started a cycle every `0.4 s x batches`, but then fired
that cycle's batches back to back, at ~5 req/s (one 10-minute window, 1:01-1:11 PM CST: 55 requests in 11 s). A 429
ended the cycle, and the next cycle started again at the top of the sorted list. In that window, no cycle
completed: the 20 cycles reached 6 to 55 of 72 batches, so the last ~800 tickers (late NCAAF totals, then NHL) were
never polled. Sorted order puts `KXNCAAFTOTAL` and `KXNHL*` last, which is why NHL (93%) and NCAAF totals carry the
long gaps.

**A weeknight, for contrast: 2026-11-16** (596 markets, NBA/NFL/NHL): gap p50 10.4 s, p90 12.9 s, max 188.4 s; 96.0% of
markets have a gap > 120 s. Every one of those comes from two whole-loop stalls (70 s and 136 s, about 7:25 and 7:31 PM CST;
the second ended at a ticker refresh). That is a different cause (likely the Idle-priority process or the capture-file
read over `\\wsl.localhost`). It is not addressed here (follow-up).

## 2. The change (scripts/inplay_recorder.py, LOAN from lane `in-game-trading`)

The loan was approved by the user ("Approve the recorder loan", typed in `local_898e5510` at ~7:25 PM CST and
forwarded verbatim; I checked that session's transcript). It is recorded in both lane blocks (`f854831fb`). The code is
three commits on branch `claude/stoic-stonebraker-a6c9aa`: the list and loop, the gap tool's 60 s share, and the
200 x 1.25 defaults. It has 8 tests in `tests/test_inplay_recorder_discovery.py` and 4 for the gap tool; with
`tests/test_inplay_repo_paths.py`, 17 pass. It is not on main: the nightly re-syncs from `origin/main`, so landing it
changes the next night's recording, and that needs the user's yes. The SHA on main gets recorded here when it lands.

- **List:** every `--tickers-seconds` (600), union of Kalshi's public listing (`GET /markets?series_ticker=<s>&status=open`,
  kept to the event tickers carrying the slate's date code, e.g. `26NOV14`) and the capture file. A ticker stays polled
  until its result is recorded. Series: `KX{NBA,NFL,NCAAF}{GAME,SPREAD,TOTAL}`, `KXNHL{GAME,SPREAD}`.
  - `KXNHLTOTAL` is left out on purpose. The capture file has never fed it (checked 11-07, 11-13..11-16), and
    `inplay_fair_score` scores any `*TOTAL` family, so adding it would add an NHL-totals population to the stage-2
    scoreboard. That is lane `in-game-trading`'s decision.
  - Measured 2026-11-17: one discovery sweep of all twelve series is 15 requests and ~11 MB.
- **Loop:** every Kalshi request (poll or discovery) waits its turn at `--kalshi-rate`, evenly spaced. Each poll asks
  for `--kalshi-batch` tickers. Kalshi returned all of them for 50, 100, 150 and 200 tickers per request, at 0.22-0.28 s
  each. A 429 still ends the cycle and waits 5 s, but the next cycle starts at the batch that failed, so no part of the
  list is starved. Defaults: **200 tickers at 1.25 req/s** (§3; first written as 100 at 2.5, which drew ~3x the 429s).
- **Cost (measured in §3; the 11-17 estimate of "~2 GB" was low):**
  - Download: ~0.5 MB/s (a 200-ticker response is ~420 KB).
  - Disk: on a 4,663-market list the new loop writes ~210-230 MB an hour (~290 bytes a row). 11-14 wrote ~65 MB an
    hour (1.01 GB over 15.5 h). A Saturday `kalshi.jsonl` grows about 3-3.5x, to at most ~3.6 GB if the whole list
    stayed open all day. It will be less, since settled markets drop out.
  - Weeknights (~600 markets, 3 requests a cycle at the 10 s floor) poll at the same cadence as today.
  - C: had 153 GB free on 11-18.
  - `--kalshi-rate 0.625` would halve the rows at a ~38 s cycle. That is not measured, and it sits closer to M3's
    60 s window.
- `--no-discover` restores the capture-file-only source (the reachability test's "off").
- Unchanged: the `kalshi.jsonl` row shape, the settled-ticker drop, books/ESPN/Polymarket polling, `inplay_nightly.py`,
  the stage-2 scoreboard, M3.

## 3. After: dry A/B on a Saturday-sized universe (2026-11-18, 1:33-4:55 AM, 13 segments of 15 minutes)

**Setup.** This ran after the 11-17 nightly logged `stopped`, so it never overlapped it. One discovery sweep listed Saturday 11-21's
full-game markets (NCAAF 4,103, NBA 12, NHL 28) plus Sunday 11-22's NFL (520): **4,663 tickers**, the same scale as
11-14's 5,014. All 4,663 went into one synthetic capture file that **both** arms read (`--fleet-root`), so the old arm's
list was complete. That isolates the poll-loop change. The list change is measured by §1's `list` row and pinned by the
tests. Four 15-minute segments alternated: old (origin/main 5d13d68ab's recorder), new, old, new. "New" here is the
first commit at its first defaults (100 tickers at 2.5 req/s; the final defaults come below). They used the same
flags and ran at Idle priority. The markets were pregame (no game in play, so no OddsAPI call).
Tool: `scripts/inplay_poll_gaps.py`. Outputs: the session scratchpad's `ab/`.

| metric (15 min each) | old1 | new1 | old2 | new2 |
|---|---|---|---|---|
| markets quoted at least once, of 4,663 | 2,700 | **4,663** | 2,800 | **4,663** |
| never quoted in 15 minutes | 1,963 (42.1%) | 0 | 1,863 (40.0%) | 0 |
| gap p50 / p90 / max | 38.2 / 76.6 / 646.8 s | 20.6 / 35.4 / 58.8 s | 38.3 / 76.3 / 424.0 s | 20.4 / 28.6 / 47.7 s |
| each market's largest gap, p90 | 646.8 s | 58.7 s | 424.0 s | 46.9 s |
| any gap > 120 s, or never quoted | 2,713 = 58.2% | **0** | 3,313 = 71.0% | **0** |
| no quote in a 60 s window (quoted markets only) | 26.3% | **0.0%** | 33.6% | **0.0%** |
| Kalshi 429s | 24 | 9 | 24 | 6 |
| whole-loop stalls > 60 s | 0 | 0 | 2 (74 s, 72 s) | 0 |
| rows / `kalshi.jsonl` | 41,850 / 12.4 MB | 180,305 / 52.2 MB | 26,600 / 7.8 MB | 189,694 / 54.9 MB |

- **The old loop reproduced 11-14's starvation on a complete list.** It never quoted 1,315-1,415 of the 1,622
  `KXNCAAFTOTAL` markets, and it quoted no NFL and no NHL market at all in either segment. Its "no quote in 60 s" share
  (26-34%) is close to 11-14's 26.7%, and it counts only the markets it quoted at least once.
- **The new loop quoted every market, every segment.** It had no gap over 60 s and no gap over 120 s. Every sport
  had p50 20-21 s.
- **old2's two whole-loop stalls are 429s on a cycle's first request.** At 2:11:06 and 2:11:42 AM (again at 2:16:50 and
  2:17:24) the first batch was refused. The old loop then waited its full ~38 s cycle slot each time: 74 s with no quote
  for any market. The 11-16 weeknight stalls (§1) are **not** this: that log has no `kalshi_error` between 7:24 and
  7:33 PM CST. They stay a follow-up.
- **A failed discovery request costs nothing.** At new2's second refresh (2:28 AM), `KXNCAAFGAME` and `KXNHLGAME` got
  429s, so the sweep found 3,883 tickers instead of 4,143. The polled list stayed at 4,663, because a ticker leaves only
  when its result is recorded.

**Tried and REJECTED: retrying sooner after a 429 (`cycle_due`, 2026-11-18, never committed).** new1's 58.8 s
maximum sat 1.2 s under M3's 60 s window. After each 429 the loop idled 6.6-21.6 s: it backed off 5 s and then waited
out the cut cycle's full 18.8 s slot. A patch let a cut cycle go again straight after the 5 s back-off (the pacer still
held 2.5 req/s). Three more patched segments ran alternating with two more unpatched ones (same setup; 2:37-3:53 AM):

| 15 min each | unpatched: new1 / new2 / unp4 / unp5 | patched: new3 / pat4 / pat5 |
|---|---|---|
| Kalshi 429s | 9 / 6 / 14 / 15 | **24 / 52 / 25** |
| gap max | 58.8 / 47.7 / 52.7 / 69.8 s | 50.5 / **94.4** / 46.5 s |
| each market's largest gap, p90 | 58.7 / 46.9 / 51.8 / 69.6 s | 44.9 / 93.9 / 46.4 s |
| no quote in a 60 s window | 0 / 0 / 0 / 0.9% | 0 / **2.6%** / 0 |
| successful requests | 1,816 / 1,911 / 1,661 / 1,644 | 1,707 / 1,324 / 1,756 |

Retrying sooner drew about 3x the refusals, and its worst segment (pat4) was the worst of all seven. The idle time
was not wasted: it let Kalshi's limiter drain. The patch is kept at `rejected_cycle_due.patch` in the session
scratchpad and is not on any branch. Do not re-propose it without a different back-off.

**The unpatched loop is not airtight either:** unp5 reached 69.8 s (0.9% of the time without a quote in 60 s), so a
second variable was tested: the request size.

**Request size: 200 tickers at 1.25 req/s replaces 100 at 2.5 (2026-11-18, 3:54-4:55 AM).** Both settings poll the
same tickers per second and have the same cycle length (~19 s on 4,663 markets); 200 uses half the requests. Every
pause longer than 25 s in any segment was two 429s in a row (5 s back-off plus the rest of the slot, twice). So the
worst gap tracks how often Kalshi refuses, and fewer requests should mean fewer refusals. Two alternating pairs of
the committed loop, same setup:

| 15 min each | 100 x 2.5: d100_6 / d100_7 | 200 x 1.25: b200_6 / b200_7 |
|---|---|---|
| Kalshi 429s | 15 / 16 | **6 / 3** |
| gap p50 / p90 | 20.5 / 37.2 s, 25.0 / 37.5 s | 20.1 / 31.4 s, 19.7 / 21.1 s |
| gap max | 68.7 / 56.6 s | 59.9 / 51.6 s |
| no quote in a 60 s window | 0.9% / 0 | 0 / 0 |
| markets quoted, of 4,663 / gaps > 120 s | 4,663 / 0, both | 4,663 / 0, both |
| rows / `kalshi.jsonl` | 167,890 / 48.6 MB, 164,264 / 47.6 MB | 188,257 / 54.5 MB, 201,246 / 58.2 MB |

Over all eight segments of the committed loop, 100 x 2.5 drew 6-16 refusals per segment (six segments, mean 12.5) and
200 x 1.25 drew 3 and 6. Fewer refusals also meant more quotes (rows +12-23%). **200 x 1.25 is now the default**
(`--kalshi-batch 200 --kalshi-rate 1.25`; commit on the branch after the two above). `inplay_nightly.py` passes no Kalshi
flags, so the default is what Saturday records. The evidence is two segments against six, at night, on pregame
markets. The 11-21 nightly is the real reading.

**Where the new loop stands, for M3:** every market is quoted, nothing passes 120 s, the largest gap in a segment
was 47.7-69.8 s, and the share of time without a quote in a 60 s window was 0-0.9% (old loop: 26-34%; 11-14: 26.7%).
A single gap over 60 s needs two or three 429s in a row on one market's batch.

**Caveats.**
- These are 15-minute segments at 1:30-2:30 AM on pregame markets, not a live Saturday. Kalshi's 429 rate during live
  play may differ; 11-14's old loop drew ~100 an hour against old1/old2's ~96. Prices moved less, which does not change
  the timing.
- `inplay_poll_gaps.py`'s cause split (`list`/`starve`) is not valid for the new loop, whose cycles start mid-list.
  Only the pooled and per-market numbers are compared.
- The real after-reading is the first Saturday nightly on the new code. The tool reads it as is:
  `py -3 scripts/inplay_poll_gaps.py C:/tmp/inplay_2026-11-21`.
