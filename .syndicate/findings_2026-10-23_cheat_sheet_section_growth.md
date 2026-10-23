# Findings 2026-10-23 -- why an exported cheat-sheet section keeps gaining rows (NHL consistency first)

Lane `cheat-sheet-section-growth` (session 474f66e0, a sub-session of `cheat-sheets` / 9e18a0e7). READ-ONLY on the
fleet: files under `/home/amyn/syndicate-prod/data/cheatsheets`, the build log
`~/syndicate-prod/logs/cheat_sheets.log`, `nhl_source/tracking/book_quotes/<date>.jsonl[.gz]`, and GETs of the served
page `http://127.0.0.1:10000/cheatsheets?date=...`. No build, no picks refresh, no odds fetch, no deploy. Fleet
checkout `4eafd1d51` (cheat_sheets.py last changed by `bdde29d32`, 10-22 10:30 AM CT). All times US Central.
Window 10-16 .. 10-23. Scripts: session scratchpad `growth.py`, `firstquote.py`, `served.py`.

## Answer in one paragraph

**Within a day, rows are appended to the posted section in the PREGAME view. The pregame view is the page's default
on every day, reconciled days included.** That view re-derives every section on every request, from the rows of the
**latest full build**. It puts the posted rows first and lists every other row that now qualifies below them:
`pin_posted(..., only=False)` in `page_payload`. Each full build re-picks the sheet's rows, and for NHL that means the
**top 30 player+stat groups out of 63-953 on the board**, ranked by (Suggested, best EV, books quoting). EV moves with
every price, so the top 30 reshuffle at every build. A posted row that falls out is carried back as `posted_kept`, and
the newcomers that pass the consistency rule are appended. So the section grows after the 12:30 PM and 4:30 PM builds
(`SyndicateCheatSheets`). It can also shrink at a later build, because the appended part is whatever that build's
30 groups produce. The 15-minute picks task never touches rows. The RECONCILED view is exact: since `bdde29d3` its
shared section equals the posted rows on all 6 posted days. It is not the default view, though, and the reconcile
only exists from 7:45 AM the next day.

## Writers, measured

| writer | when (CT) | touches rows? |
|---|---|---|
| `SyndicateCheatSheetsTomorrow` (`--date tomorrow`) | D-1 2:00 PM, D-1 9:00 PM | yes: a full build of day D |
| `SyndicateCheatSheets` | D 8:30 AM, 12:30 PM, 4:30 PM | **yes: full build, re-picks the top `cap` groups** (NHL 30, NFL 150, NBA 150, MLB 100, NCAAF 80, soccer 120) |
| `SyndicateCheatSheetPicks` (`--picks-only`) | every 15 min | **no.** `refresh_picks` merges picks, ladders and SGP, then rewrites the file with the same rows. That is why the sheet's mtime reads 6:52 PM (10-21) or 9:22 PM (10-22): those are picks / ladder / SGP writes, not row changes. EXONERATED. |
| `SyndicateCheatSheetsReconcile` | 11:50 PM, 7:45 AM | no: it writes `<date>.reconciled.json` beside the sheet |
| the blueprint, `POST /api/cheatsheets/posted` | on each export | it appends a post to `<date>.posted.json` |

`merge_with_record` keeps a prior row only for a game this build no longer prices. Every priced game's rows are
REPLACED, so the row set reshuffles; it does not only grow. `with_posted` then adds back any posted row that was lost.

## Per build: NHL consistency size, from the build log (counts only, no membership)

The log line is `cs.sections(rows)` after the posted rows were added back, with no pinning. The run order matches
the schedule. Each post's `sheet_generated_at` anchors the 8:30 AM build.

| sheet day | 8:30 AM build | export | 12:30 PM build | 4:30 PM build (final) | served now: pregame / reconciled |
|---|---|---|---|---|---|
| 10-18 | 7 (groups 30/175) | 10:00 AM, 7 rows (whole section) | 10 (30/188, 4 posted kept) | 7 (30/197, 3 kept) | 7 / 7 |
| 10-21 | 8 (30/144) | 11:51 AM, 8 rows (whole section) | **17** (30/203, 6 kept) | **12** (30/208, 6 kept) | **12** / 8 |
| 10-22 | 6 (30/950) | 11:41 AM, 6 rows (whole section) | **12** (30/953, 4 kept) | **12** (30/953, 5 kept) | **12** / 6 |
| 10-16 | 2-3 | 12:34 PM, 2 rows (backfilled 10-17; predates `d956cbcc`) | 3 | 5 (the 8:27 PM rebuild; Karlsson's side flipped) | 6 / 2 |

- 10-21: the section reached 17 between 12:30 and 4:30 PM, then fell to 12. It grows AND churns, so a viewer saw a
  different list at each build.
- 10-18: 7 → 10 → 7. Rows were appended after 12:30 PM and gone again by the 4:30 PM build. Today it serves 7 + 0.
- **Posted rows fall out of the build.** Of the posted rows, 6 of 8 (10-21) and 5 of 6 (10-22) were not in the final
  build's 30 groups, though still quoted. They survive only as `posted_kept`.

## Why the appended rows entered: first book quote (`book_quotes`) vs the 8:30 AM build

| day | appended row | first quoted | books by the 8:30 AM build | reason |
|---|---|---|---|---|
| 10-21 | Josh Norris ASSISTS u0.5 | 10-20 8:39 PM | 3 | top-30 reshuffle |
| 10-21 | Jack Quinn ASSISTS u0.5 | 10-20 8:39 PM | 4 | top-30 reshuffle |
| 10-21 | Ridly Greig POINTS u0.5 | 10-21 8:43 AM | 0 | books posted the line after the build |
| 10-21 | Josh Norris SOG u1.5 | 10-21 8:43 AM | 0 | books posted the line after the build |
| 10-22 | Andrew Copp, Sam Bennett, Clayton Keller, Evan Rodrigues, Brady Tkachuk (5) | 10-21 10:57 PM - 10-22 12:31 AM | 4-5 each | top-30 reshuffle |
| 10-22 | Aaron Ekblad ASSISTS u0.5 | 10-22 10:27 AM | 0 | books posted the line after the build |

Of 10 appended NHL rows on 10-21 and 10-22: **7 were cap/priority churn** (quoted with 3-5 books before 8:30 AM but
outside the build's top 30) and **3 were books posting the line later**. Every appended row kicks off that evening
(6:10-9:10 PM), and the L10 of each is 7-9 of 10.

## Candidates from the brief, one by one

- **Books posting new lines:** CONTRIBUTES, 3 of 10.
- **Top-30 group cap reshuffling** (EV rank moves each build): **MAIN DRIVER**, 7 of 10. It also removes posted rows
  from the build (6 of 8, 5 of 6).
- **`form10` crossing 70% as games finish:** NOT a cause intraday. An NHL row's L10 comes from finished games before
  the day, and the day's games are evening games. Across days see H4.
- **The section's `top` cap freeing slots:** NOT for NHL, whose section peaked at 17 against a cap of 25. It does
  bind on NFL 10-18 and every NBA day (25 = cap), where the pregame view shows the posted rows plus up to 25 more.
- **15-minute picks merge:** EXONERATED (it never re-prices rows; see the writers table).
- **Posted rows lead, build rows appended below:** CONFIRMED. This is the display mechanism (`pin_posted` with
  `only=False` in `page_payload`, pregame `sections` and `game_sections`).
- **The full build replacing the sheet:** CONFIRMED as the source of the new rows (`merge_with_record` replaces every
  priced game's rows).

## Hypotheses (written to the lane before testing)

- **H1 CONFIRMED.** Pregame re-derives per request, and posted rows lead with current qualifiers below. Served:
  NHL 10-21 12 rows (8 posted), 10-22 12 (6), NFL 10-18 28 (12), MLB 10-18 15 (12).
- **H2 FALSIFIED as stated.** The row set does not only grow; it is replaced per priced game, and `frozen=0` on
  10-21 and 10-22. What grows is the posted rows plus the current qualifiers.
- **H3 NOT OBSERVED, but latent.** Every posted section in the window has exactly 1 post. The path is real, though: a
  re-export from the pregame view captures the posted rows plus the first appended ones (a `.rowlist` keeps 10 in the
  image, 12 of a table), and `recordPosted` records them all. The posted union, and with it the reconciled "shared"
  view, would then grow. NHL 10-22 re-exported at 5 PM would have posted 10-12 rows instead of 6.
- **H4 FALSIFIED for every sport.** NHL `form10.games` is 10 on nearly every primary row from 10-14 (22-34 rows a
  day; it already spans last season). The size of the consistency section follows the slate, not the season's age: NHL 7, 7, 5, 10, 7, 4, 6,
  12, 12, 4 over 10-14..10-23. Nothing accumulates across days, and each day's sheet is its own file.

## The three views, separated

| view | how its sections are built | after an export |
|---|---|---|
| Live page, PREGAME (the default on every day, `STATE.view` defaults to "pregame") | `pin_posted(sections(rows))`: posted lead, the latest build's qualifiers appended | **grows and churns** at each later full build |
| RECONCILED (`?view=reconciled`, only once `<date>.reconciled.json` exists = 7:45 AM the next day) | `doc.shared`: `pin_posted(..., only=True)`, rows shown as posted | **exact**: equals the posted rows on all 6 posted days |
| An export or re-export | the frame clones what the current view shows (the first 10 of a row list, 12 of a table); pregame only, because a reconciled export is not recorded as a post | a re-export of a grown section ADDS the appended rows to `posted.json` (H3, latent) |

## Other sports (quick)

- Posts in the window: NHL 10-16 / 10-18 / 10-21 / 10-22, NFL 10-18, MLB 10-18. **Every post was the consistency
  section.** No other section, and no NBA / NCAAF / soccer / WNBA post. The other sections run through the same
  `pin_posted` path, so they would behave the same; none was observed.
- NFL 10-18: posted 12 at 10:11 AM (the 8:30 AM build). The pregame view serves 28 = 12 + 16 appended, and the
  section's cap of 25 binds. 3 of the 12 posted rows left the final build's own section; 2 are `posted_kept`.
- MLB 10-18: posted 12 at 9:54 AM. It serves 15 = 12 + 3, and one of the 3 is a **duplicate player+stat** (Victor
  Mesa Jr. H+R+RBI: posted o0.5, appended u1.5), because the later build chose a different main line. `pin_posted`
  does not de-duplicate by player+stat.

## Per-build history: there is none

Each sheet is overwritten in place (`write_atomic`). The build log carries per-section COUNTS per build but not
membership, and has no per-line timestamps (runs are mapped by schedule order and anchored by `sheet_generated_at`).
To measure membership per build, a full build would append one line to `<sport>/<date>.builds.jsonl`:
{generated_at, writer, groups_on_board, sections: {key: [card_id, ...]}}. That is a few KB a day, written by the
generator. It is not needed for this diagnosis.

## Proposed fix (for lane `cheat-sheets` to take to the user)

**A section that has been posted is frozen in every view.** On the live (pregame) page and in the reconciled view,
the section shows exactly its posted rows, as posted, in posted order, all day and afterwards. Rows that qualify
after the graphic are shown below a divider, "Qualified after the graphic -- not on it". That block is never exported
and never recorded as posted, and it leaves out any player+stat already in the posted rows. A section never posted in
a scope keeps its live rows.

- Why the extra block, not plain hiding: hiding drops real later qualifiers from the featured page altogether. The
  divider keeps the posted list identical to the X graphic and still says what changed. Option B, simpler, is to
  freeze and hide the later rows. That is the user's call.
- It also closes H3: a re-export captures only the frozen rows, so the posted union cannot grow.
- It does not touch the builds. Re-picking the top 30 per build is correct for unposted sections and for prices.

**Files** (all claimed by lane `cheat-sheets`):
- `syndicate/features/shared/cheat_sheets.py`, `page_payload`:
  - pass `only=True` to `pin_posted` for `sections`, `game_sections`, `game_line_sections` and
    `game_line_sections_by_game` in every view;
  - add `sections_after_post` (and a per-game twin): `sections(rows)[key]` minus the posted card ids, minus any
    player+stat already posted, only for keys that were posted;
  - apply the posted copy (`posted_items`) in the pregame view too, so a frozen row shows the graphic's price and book.
    Today that happens only when `rec is not None`.
  - `doc["shared"]` becomes identical to the main sections. Keep it as an alias for one release, or drop it with the
    template's `sharedOf`.
- `syndicate/templates/cheat_sheets.html`:
  - render the "Qualified after the graphic" block with class `no-export`, so `buildExport` strips it and
    `recordPosted` never sees its rows;
  - simplify `sharedOf` / `sectionsFor`.
- `tests/test_cheat_sheet_posted.py`:
  - `test_reconciled_shared_view_is_exactly_what_was_posted_as_it_was_posted` asserts the OLD pregame behaviour (the
    newcomer "Late Add" in `doc["sections"]["consistency"]`), and so does
    `test_no_shared_view_before_the_day_is_reconciled_and_rows_show_the_build`. Both change.

**Test that proves it** (new, in `tests/test_cheat_sheet_posted.py`):
`test_a_posted_section_is_frozen_in_every_view_and_later_qualifiers_sit_apart`.
- Build the NHL 10-21 shape: a sheet with 2 posted consistency rows, then a later sheet where one posted row is
  `posted_kept`, one newcomer qualifies, and a second newcomer repeats a posted player+stat at another line.
- With no reconciled file, assert `doc["sections"]["consistency"]` is exactly the 2 posted card ids in posted order;
  `doc["sections_after_post"]["consistency"]` holds only the first newcomer; each posted row shows the posted
  price and book; and a section never posted is unchanged.
- Repeat with a reconciled file and assert the same lists.
- Template assertion: the after-post block carries `no-export`.
- Reachability: the same sheet with no posted file gives the section all 3 qualifiers, so the freeze is what changed
  the result.
