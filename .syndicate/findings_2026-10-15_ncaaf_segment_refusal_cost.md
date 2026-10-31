# The 2026-09-06 measurement that keeps the segment refusal on is no longer runnable — its two fields are gone from the board

`[2026-10-15 14:3x–14:4xZ, session 4ab694ed, lane ncaaf-segment-refusal-cost, taking the residual lead filed on closing segment-series-vocabulary]`

## The question

`_SEGMENT_REFUSAL_ENABLED = True` rests on a measurement recorded in
`venue_quote_fanin`'s header under a user decision — *"measure the coverage cost
and flip the flag"* (2026-09-06). Served payload, two samples 60s apart:

| sport | rows | segment rows | would be refused |
|---|---|---|---|
| mlb | 734 | 18 | 17 |
| ncaaf | 270 | 8 | 0 |
| soccer | 119 | 0 | 0 |
| **total** | **1,124** | **26** | **17** |

…and **of the 17: DISPLAYABLE 0, SERVABLE 0** — the refusal removed no coverage
anyone could see or act on. Only **8** of those 26 segment rows were NCAAF, and
NCAAF live has since been measured at **45.9% segment — 22,416 of 48,873 live
priced sides**. So the decision rests on a population three orders of magnitude
smaller than the one that exists. This lane re-measures it.

## Finding 1: the predicate cannot be evaluated any more

The 09-06 predicate is stated verbatim in the module header:

> A row counts as refusable when `venue_basis.venue` is set AND that venue also
> appears in `book_prices` — it is actually WEARING a native venue price — and
> its segment is not a `_FULL_GAME_TOKENS` spelling.

Measured 14:36:59Z over 4,535 served rows across eight sports: **neither
`venue_basis` nor `book_prices` appears as a key on a single row.** Not null on
some rows — **absent from the schema entirely.**

I ran the predicate before checking that, and it returned a clean
`0 refusable / 0 displayable / 0 servable` for every sport — a result that looks
exactly like a confirmation of the 09-06 finding and was instead my instrument
reading two fields that no longer exist. The script's own
`NO row wears a venue price -- EMPTY FRAME, not a confirmation` note is what
stopped it being reported as one.

**What carries the venue today:** `venue_ref` (a ticker) and `price_source`, with
the book prices moved inside `quote` (`quote.best_any_book`).

**This matters beyond this lane.** A live flag is held on by a measurement whose
method no longer runs. Anyone re-checking that decision with the documented
predicate gets zeros and reads them as agreement.

## Finding 2: the modern equivalent reads zero, and the zero is attributable

Re-measured at 14:38:11Z with the equivalent predicate — **`venue_ref` non-null
AND `_fold_full(segment) != "full"`**, with `_FULL_GAME_TOKENS` and `_fold_full`
imported from the deployed module rather than restated. Row cap defeated;
`rows == total_rows` for every sport reported.

| sport | rows | segment rows | with `venue_ref` | **refusable** | of those live |
|---|---|---|---|---|---|
| mlb | 227 | **93** | 49 | **0** | 0 |
| nba | 106 | 0 | 1 | 0 | 0 |
| nhl | 926 | 0 | 30 | 0 | 0 |
| nfl | 1,288 | 0 | 48 | 0 | 0 |
| ncaaf | 423 | **0** | 98 | 0 | 0 |
| soccer | 1,433 | 0 | 1,039 | 0 | 0 |
| ncaab / wnba | 0 | — | — | — | out of season |
| **total** | **4,403** | **93** | **1,265** | **0** | **0** |

**Both sides of the predicate are populated and the intersection is empty.**
1,265 rows (28.7%) wear a venue ticker — venue pricing is very much reaching the
board — and 93 rows are segment. No row that wears a venue ticker is a segment
row on this slate. That is a real reading, not an empty frame, and it is
consistent with the 09-06 result.

## Finding 3: but NCAAF is unanswerable right now, by construction

**NCAAF: 423 rows, 0 segment rows.** It was 09:38 CDT on a Thursday — the NCAAF
board is entirely pregame, and pregame NCAAF is ~100% full-game (99.3% pooled
pregame, measured earlier this session). NCAAF's 45.9% segment share exists
**only while games are in play.**

So this reading cannot speak to the question the lead actually asked. The 93
segment rows are all MLB (`first3`/`first5`, postseason), which is the same sport
the 09-06 reading was already dominated by.

## Armed, not guessed

NCAAF kickoffs on the board: **Thu 18:30 and 19:00 CDT**, **Fri 18:30/19:00**,
then **Sat 2026-10-17 from 11:00 CDT** across 21 distinct kickoff times.

The reading is armed for **Saturday 2026-10-17 14:00 CDT** (task
`ncaaf-segment-refusal-cost-1017`, verified stored with `fireAt` and its guards),
not for tonight: previous Saturdays carried **39,591 live NCAAF sides** against
~800 on a midweek slate, so Saturday is where the population the lead is about
actually lives. The task's prompt:

- re-confirms that `venue_basis` / `book_prices` are still absent rather than
  reporting a zero from them;
- uses the equivalent predicate and **labels it an equivalent**;
- proves the frame is live from `game-chips` first, and **re-arms for 2026-10-24
  rather than reporting any share if no NCAAF game is in play**;
- attributes any zero to which side of the predicate is empty;
- reads the fan-in's `SEGMENT_MISMATCH_GRID` counter as a second instrument, in
  **whole log lines** — the 220-character cut that turned `kept_in_window=5149`
  into `53` earlier today is named in it;
- and is told **not to change any code or flag** if a cost does appear: the next
  step is a per-series affirmative trading decision for a human, with the
  margin-vs-handicap exclusion respected, because `_SERIES_SEGMENT`'s refusal was
  installed after five orders staked $7.08 against the wrong portion of a game.

## Status

**Lane stays OPEN with the obligation dated.** The pregame half is measured and
consistent with 09-06; the NCAAF half — the only half the lead was about — is
armed for Saturday. Finding 1 stands on its own regardless of how that reads.

## Method note

The equivalent predicate imports the deployed `_FULL_GAME_TOKENS` / `_fold_full`
instead of restating the token set. No share is reported over a sport with zero
rows, and the two out-of-season sports are listed with a dash rather than
omitted. The first run of this measurement was wrong in a way that produced a
*plausible* answer — the lesson is in the findings rather than only in the
learning: **a predicate whose fields have been renamed returns a clean zero, and
a clean zero that agrees with your prior is the hardest kind to catch.**

## 2026-10-26 16:09Z: scheduled Saturday reading NOT MEASURED (run started 45h late)

- Slot: `2026-10-24T19:00:00Z`. Dispatch: `2026-10-26T16:08:40Z` (from `list_task_runs`, read 16:09Z). Late by **45h09m**, more than the 6h guard allows, so the run stopped. **No numbers were taken.** It did not read the board as it stood: Monday's board is not the Saturday in-play population this lane needs, the same reason it rejects a midweek MACtion frame.
- Not checked by this run, so no claim either way: whether `venue_basis.venue`/`book_prices` are still absent, and the `SEGMENT_MISMATCH_GRID sport=ncaaf` counter.
- Re-arm to `2026-10-31T14:00:00-05:00` was **refused**: the scheduler needs a person's approval for an unattended run. The prompt's guard date (10-24) also needs changing. Direct SKILL.md writes are blocked in auto mode; the working route is `update_scheduled_task` with a full `prompt`.
- **Pattern:** two armed Saturday slots in a row (10-17 and 10-24) were lost to late dispatch on this host. A one-time `fireAt` fires only while the app is up and the host awake. Before arming a third, a human should confirm the host will be awake at that time, or take the reading by hand.

## 2026-10-31 19:00-19:04Z (14:00-14:04 CDT): THE LIVE SATURDAY READING. Refusal is FREE on the real NCAAF population

Scheduled task `ncaaf-segment-refusal-cost-1017`, dispatched on time (clock read 19:00:46Z, 0 min past the slot, so the frame guard passed).

**Frame proven live.** `GET /api/board/game-chips` read 19:01:08Z (artifact published 19:00:14Z, age 55s): NCAAF **14 live / 33 pregame / 47 chips**. Live games included BC@DUK Q4, WIS@IOW Q4, ND@NAV Q4, MIC@RUT Q4, AUB@OM Q3, MAR@OD HALF, KS@COL Q2, CC@GS Q2. This is a Saturday afternoon in-play frame, not a midweek one.

**The 09-06 predicate is still unrunnable.** `venue_basis.venue` is set on **0** rows and the `book_prices` key is present on **0** rows, across all 5,544 served rows in 8 sports. That is the same as 10-15. No zero is reported from those fields.

**EQUIVALENT predicate (an equivalent, not the 09-06 measurement):** a row is REFUSABLE when `venue_ref` is non-null AND its segment is not a `_FULL_GAME_TOKENS` spelling. `_FULL_GAME_TOKENS`, `_fold_full` and `_row_segment` were imported from `venue_quote_fanin` at `origin/main` `0b9307586`; the token set is `{'', 'full', 'full_game', 'game'}`. Two segment classifiers were run: the plain `segment` field, and the module's own `_row_segment` (which also catches a market-name suffix). **They agree on every sport.** `GET /api/board/layer2-shortlist?sport=<s>&limit=5000`. The cap is defeated on every sport: `rows == total_rows`, and `rows_truncated` is null on all of them. Shortlist `written_at` 18:47:16Z, `build_age_seconds` 932.6 at the NCAAF read.

| sport | read (Z) | rows (=total_rows) | segment | `venue_ref` | REFUSABLE | live rows | live segment | REFUSABLE live |
|---|---|---|---|---|---|---|---|---|
| mlb | 19:02:30 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| nba | 19:02:32 | 1,092 | 272 | 81 | **0** | 0 | 0 | 0 |
| nhl | 19:02:42 | 911 | 0 | 16 | **0** | 14 | 0 | 0 |
| nfl | 19:02:44 | 1,033 | 0 | 38 | **0** | 0 | 0 | 0 |
| **ncaaf** | 19:02:47 | **1,094** | **609** | **153** | **0** | **116** | **0** | **0** |
| ncaab | 19:02:49 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| wnba | 19:02:51 | 321 | 45 | 69 | **0** | 0 | 0 | 0 |
| soccer | 19:02:52 | 1,093 | 9 | 678 | **0** | 138 | 7 | 0 |
| **all** | | **5,544** | **935** | **1,035** | **0** | 268 | 7 | 0 |

**The zero is the THIRD kind again: both sides are populated and the intersection is empty.** NCAAF has 609 segment rows (55.7% of 1,094; h1 170, q1 147, q2 78, q4 75, q3 74, h2 65) and 153 rows carrying a `venue_ref` (14.0%; polymarket_us 149, kalshi 4). Every one of the 153 is a full-game row: totals 130, h2h 23. Every one of the 609 segment rows has `price_source = None`, so it is book-priced. **Of the refusable rows, 0 are displayable and 0 are servable, out of 0.**

**A second fact this reading exposed, not attributed to the refusal:** all 609 NCAAF segment rows belong to PREGAME games. The 116 live NCAAF rows, covering all 14 in-play games, are 100% `segment=full` (totals 62, spreads 43, h2h 11). So at this read the served shortlist carries **no in-play NCAAF segment row at all**, against the 45.9% live-segment share in priced-side history. The refusal cannot have caused this: it strips a mismatched VENUE price, and segment rows here are book-priced. The cause is upstream in shortlist admission or capture, and is NOT determined. The shortlist's NCAAF drop counters at this build were beyond_quote_age 71, superseded_line 62, withdrawn_line 9 and no_market_price 12; these are not split by segment. This is recorded as a lead, not as part of this lane's goal.

**Second instrument: the fan-in's own counter.** Read 19:03:53Z in WSL over `/home/amyn/syndicate-prod/logs/*.log`. Whole lines were read and parsed by field name, taking the FIRST occurrence, because the trailing prose repeats `refusing=False`. That prose repeat matters: my first parse picked it up and read `refusing=False`. The real field reads `refusing=True` on every line. There are 80 `SEGMENT_MISMATCH_GRID sport=ncaaf` lines today, 08:45:33Z..18:56:23Z. Newest line, **18:56:23Z: `count=62 sides_seen=7644 repriced=328 matched={'full|kalshi|KXNCAAFGAME': 10, 'full|polymarket_us|-': 318} refusing=True`**. The in-play cycles were: 17:40Z count 54 / sides 7212, 18:15Z **278** / 7502, 18:30Z 242 / 7608, 18:40Z 110 / 7636. The maximum `count` today is 278 and the maximum `sides_seen` is 7,644.

**So the fan-in IS refusing in play, up to 278 pairings per cycle, and every refusal is the defect being stopped.** All 12 samples in the last two lines have the same shape: `ncaaf|h1|h2h` or `ncaaf|q1|h2h` ROW <- `kalshi|full|h2h|KXNCAAFGAME-...`, which is a full-game Kalshi moneyline contract offered to a first-half or first-quarter moneyline row. That is the 2026-09 `KXMLBTOTAL`-on-`first5` incident in NCAAF form. Every `matched` landing is `full|...`, so no Kalshi or Polymarket NCAAF segment contract matched any segment row: there was no legitimate segment venue price for the refusal to remove. The bound is that `sample` holds 6 of up to 278 per line. Shape-uniformity across all 278 is inferred from the samples plus the all-`full` `matched`; it was not enumerated.

**VERDICT:** on the real in-play NCAAF Saturday population, the segment refusal removes **no coverage anyone could see or act on**. On the served board: 0 refusable of 1,094 NCAAF rows (5,544 overall), both sides populated. In the fan-in: up to 278 pairings refused per cycle, all sampled ones wrong-portion bindings. `_SEGMENT_REFUSAL_ENABLED = True` now rests on a live-NCAAF measurement rather than on the unrunnable 8-row 09-06 one. **The venue-segment thread is closed.** No code and no flag was changed. Scripts: `measure.py` / `grid.py` in session `2bfb589e` scratchpad; `/c/tmp/grid_ncaaf_1031.py`.
