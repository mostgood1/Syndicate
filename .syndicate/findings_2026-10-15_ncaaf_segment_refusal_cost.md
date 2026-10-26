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
