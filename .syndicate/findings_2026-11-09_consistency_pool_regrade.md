# FINDINGS: the consistency pool re-graded, 10-23..11-08: the 10-23 edge did not hold; the pool still beats the outside but not clear of noise; the lock helps where it matters

Scheduled read-only run `cheat-sheet-consistency-pool-regrade-1109`, 2026-11-09 10:38-10:55 AM CT. Lane `cheat-sheets`
(opened by session 9e18a0e7). Nothing changed on the fleet, in env or in code. All fleet work ran `nice -n 19`. No odds
fetch, no money. Follows `findings_2026-10-23_nhl_consistency_hit_rate_first.md` (the pool question) and
`findings_2026-10-23_cheat_sheet_section_growth.md` (the posted freeze).

## What the numbers rest on

- **Sheets:** each day's FINAL build, `cheatsheets/<sport>/<date>.json` on the fleet (`/home/amyn/syndicate-prod/data`),
  sheet dates 10-23..11-08. NHL has 17 of 17 days reconciled. The final build is the 4:30 PM CT build (`generated_at`
  21:32-21:37Z every day).
- **Grades:** `<date>.reconciled.json` `props` (`PLAYER|stat|side|line` -> `{y, v}`). Flat 1 u at the sheet's price
  (`check.price`, the build's best book). Pushes count as 0 u.
- **Intervals:** 2,000 bootstrap resamples over games (`event_id`). NHL sheet days have 2-12 games, so no single day's
  interval is read alone.
- **Population:** `suggested_grade.py 2026-10-23 2026-11-08` (read-only, the recorder from disk; ran 10:40-10:50 AM CT).
  It found 1,187,896 records and graded 793,913. NHL pregame priced props: 22,383. Of those, 13,783 resolved to one
  player's game log and sat in the -250..+250 band. 8,291 fell outside the band or market, 211 had no log, and 98 were
  ambiguous. The NHL game logs run through 11-08.
- **Official record:** `/api/cheatsheets/record`, generated 2026-11-09 6:58 AM CT (12:58Z).
- **Code in the window:** 2b897d0d (stable day: sticky groups, the line/side lock and the `pool` field) and 9260ea0b
  (posted freeze) reached the fleet 10-23 1:56 PM CT, so 10-23's 4:30 PM build was the first on them. **176179e7**
  narrowed `sticky` to "a group an earlier same-day build SHOWED IN A FEATURED SECTION". It reached the fleet 10-25
  1:35 PM CT, so 10-23 and 10-24 sticky means "any group built earlier that day", and 10-25 onward means the narrower rule.
- Scripts and outputs: `C:\tmp\edge-analyses\consistency\2026-11-09\`.
  - `consistency_regrade.py` -> `regrade.out` (sheet side, every sport).
  - `nhl_hitrate_first.py` -> `hitrate.out` (population; adapted from 10-23: window, pool split by the sheet's
    own `pool` field).
  - `record.json` (the record snapshot).

## 1. NHL consistency section record, 10-23..11-08

| source | bets / games | W-L | ROI [95% by game] | units |
|---|---|---|---|---|
| served section of the final sheet, at the sheet price | 205 / 83 | 130-75 | **+3.5% [-7.7, +14.7]** | +7.16 |
| official record (`/api/cheatsheets/record`, NHL, same dates) | 216 / - | 138-78 | +4.4% | +9.44 |
| for comparison, 10-14..10-22 (10-23 findings) | 60 / - | 46-14 | +30.9% | +18.51 |

- The two grades agree within 11 bets. The record grades posted rows at the posted price and keeps posted-kept rows.
- Season to date on the record (official, from 10-15): 184-92, +27.95 u on 276 (+10.1%).
- Only 2 of the 17 days were shared (10-23 2-2, 10-26 2-4).
- By day, the section swung from -69.9% (11-08, 2-9 on 5 games) to +44.5% (10-28). 11-08 alone is -7.69 u of the window.
- **The +30.9% did not persist.** The section is still positive over the window, but its interval spans 0, and it
  excludes the earlier +30.9%.

## 2. NHL qualifying sheet rows (form10.games >= 8, rate >= 0.7), every line and side of the final build

All: **368 bets / 102 games, +2.7% [-4.8, +9.8]**, +10.10 u. On 10-14..10-22 this was +20.2% [+9.4, +30.8] on
172 / 47, and the new upper bound sits below that old point estimate. Non-qualifying rows: -6.3% [-16.1, +4.5]
on 824 / 113.

| split (qualifying rows) | bets / games | ROI [95% by game] | section rows only: bets / games, ROI |
|---|---|---|---|
| pool rank <= 10 | 77 / 52 | -9.0% [-26.9, +9.4] | 43 / 34, -15.9% [-41.2, +8.9] |
| pool rank 11..30 | 142 / 73 | +9.2% [-1.3, +20.3] | 65 / 47, +15.6% [-3.9, +35.7] |
| sticky (kept from an earlier build) | 148 / 73 | +2.0% [-10.9, +13.3] | 96 / 58, +2.8% [-11.5, +17.3] |
| `primary_locked` | 200 / 81 | +2.1% [-9.5, +13.4] | 190 / 80, +1.0% [-10.1, +12.5] |
| not locked | 168 / 79 | +3.5% [-6.9, +13.9] | 15 / 13, +34.5% [+4.2, +66.5] |
| row EV > 0 | 148 / 74 | +7.8% [-3.6, +19.7] | 100 / 57, +5.7% [-9.6, +22.5] |
| row EV <= 0 | 220 / 83 | -0.7% [-11.1, +9.9] | 105 / 57, +1.4% [-15.6, +17.4] |
| assists | 172 / 81 | +4.0% [-5.2, +13.6] | 88 / 54, -3.5% |
| points | 107 / 62 | +10.3% [-5.6, +25.2] | 74 / 47, +19.9% [-1.7, +38.5] |
| sog | 72 / 47 | -6.2% [-24.7, +11.5] | 35 / 29, -9.8% |
| goals | 17 / 13 | -20.0% [-59.6, +25.2] | 8 / 7, -13.5% |
| over | 70 / 47 | +11.1% [-10.3, +32.0] | 43 / 35, +22.5% [-2.8, +46.1] |
| under | 298 / 95 | +0.8% [-7.7, +8.5] | 162 / 75, -1.5% [-14.9, +10.9] |

- One row had no `pool` field (1 bet). Every other row carried `cap` 30.
- **Pool rank:** the top 10 is the WORST bucket, ranks 11..30 the best, and sticky sits between them. It is not
  monotone, and every pair of intervals overlaps. Nothing here supports a smaller cap.
- **Lock:** locked and unlocked qualifying rows are indistinguishable. The 15 unlocked section rows are too few to read.
- **EV:** EV > 0 leads EV <= 0 by ~8 pts, with overlapping intervals. On 10-14..10-22 the order was reversed (+18.8 vs
  +20.8), so this is not a stable separator yet.
- **Stat:** the 10-23 SOG lead (+47.9%) reversed (-6.2%). Points is the only stat positive in both windows.
- **L10 band:** flat to falling (70-79% +6.1%, 80-89% +2.3%, 90%+ -5.1%), the same pattern as 10-23. A higher hit rate
  does not pay more.

## 3. Hit-rate-first over every priced NHL prop (population, first sighting): inside vs outside the pool

One row per player + stat + game, at the main line (most books), on the qualifying side. 2,340 bets / 117 games.

| | bets / games | ROI [95% by game] |
|---|---|---|
| all qualifiers | 2,340 / 117 | **-3.3% [-7.6, +0.6]** |
| **inside the final sheet's pool** | **317 / 101** | **+1.8% [-7.0, +10.5]** |
| **outside the pool** | **2,023 / 117** | **-4.1% [-8.3, -0.2]** |
| inside, rank <= 10 | 57 / 43 | +5.1% [-17.0, +25.5] |
| inside, rank 11..30 | 117 / 69 | +10.3% [-4.1, +24.3] |
| inside, sticky | 143 / 73 | -6.5% [-19.5, +6.1] |
| every qualifying line and side, inside / outside | 358 / 103 ; 2,326 / 117 | +2.9% [-5.4, +11.6] ; -3.5% [-7.3, +0.3] |
| non-qualifying (every line and side) | 11,099 / 117 | -8.5% [-10.1, -6.8] |

- The pool is the final sheet's groups for that day. That is 983 group-days: 196 ranked <= 10, 394 ranked 11..30 and 393
  sticky.
- **The pool still separates in direction.** It runs ~6 pts above the outside, and outside the pool hit-rate-first is
  now clearly negative (upper bound -0.2%). Inside, it is no longer clear of 0, and the gap's two intervals overlap.
  The 10-23 reading (+16.1% inside vs -2.7% outside) has shrunk to +1.8% vs -4.1%.
- **What separates in this window is the row's own EV, not pool membership.**
  - Qualifiers with first-sighting EV > 0: +13.5% [+0.8, +25.7] on 198 / 83.
  - EV <= 0: -4.9% [-9.5, -0.7] on 2,142 / 117.
  - Own EV > 0 and the group's best EV >= 2: +21.0% [+3.9, +37.9] on 121 / 60.
  - The group-best-EV bands are close to monotone this time: < 0 -4.8%, 0-2 +2.8%, 2-5 -4.3%, 5-10 +13.3%,
    >= 10 +48.3% on 17.
  - This was NOT pre-registered, and on 10-23 the same cut did not separate. It is a lead for the next window, not a
    rule.

## 4. The line/side lock vs what the final build's price would choose (NHL)

- 791 group-days had a locked row. For 736 of them the lock equals the final-price choice (main line, better-EV side),
  so the lock changed nothing. 55 differed: 54 with both sides graded, all 54 a SIDE flip on the same line.
- Over the 54 graded pairs (36 games) the result is a wash. The locked side went 27-27, +0.9% [-28.4, +28.3]. The
  final-price side also went 27-27, -0.3% [-29.7, +31.3]. Opposite sides of one line mirror each other, so this was
  expected.
- In the 21 pairs (15 games) where either side met the consistency rule, the locked side was +17.9% [-26.6, +60.6]
  (12-9) and the final-price side -20.6% (9-12).
- In 11 of those pairs the locked row was in the served section. Every one is the case the lock exists for (Karlsson
  10-16): the qualifying side kept its place after prices moved toward the other side, whose L10 was 20-30%. The
  locked rows went 6-5 there.
- **The lock does not hurt.** It keeps the posted side stable, and where it bites, the evidence leans its way. At 21
  pairs, that lean is noise-sized.

## 5. Other in-season sports, served consistency section, 10-23..11-08 (sheet price)

| sport | days reconciled | section bets / games | ROI [95% by game] | record (same dates) | qualifying rows, all lines |
|---|---|---|---|---|---|
| NBA | 16 | 354 / 105 | +1.7% [-9.9, +13.3] | 207-187, +0.7% on 394 | +9.0% [-1.1, +18.4] on 688 / 117 |
| NCAAF | 12 | 139 / 72 | +5.6% [-8.3, +18.9] | 90-58, +6.4% on 148 | +4.8% [-6.8, +17.0] on 267 / 96 |
| NFL | 7 | 97 / 31 | -4.3% [-22.6, +16.1] | 59-54, -5.1% on 113 | -5.1% [-14.8, +4.3] on 726 / 41 |
| soccer | 17 | 12 / 11 | +8.0% [-31.9, +48.1] | 9-6, -3.8% on 15 | -4.5% on 59 / 46 |
| NCAAB | 7 (11-01 not reconciled) | 0 | - | - | the section has never had a qualifying row (no form10 rows) |
| MLB (ended 10-28) | 5 | 84 / 5 | +3.5% [-11.2, +18.3] | 54-32, +5.3% on 86 | 5 games: not readable |
| WNBA (ended 10-31) | 4 | 56 / 4 | +0.1% [-20.5, +13.1] | 33-23, +0.1% on 56 | 4 games: not readable |

- No sport's section is clear of 0 in either direction.
- In every sport the non-qualifying sheet rows grade below the qualifying ones. The ones clear of 0 are soccer -46.5%
  (mostly long-priced goal-scorer rows), MLB -19.0% and NCAAF -5.7%.
- So the rule still sorts the sheet, but no section has shown that it beats the price.

## Recommendation

1. **Keep the pool.** Inside the pool, hit-rate-first is +1.8% [-7.0, +10.5]. Outside it is -4.1% [-8.3, -0.2]. Widening
   the section beyond the pool would add rows that grade below 0.
2. **Keep the cap at 30.** The top 10 graded worst (-9.0% qualifying, -15.9% in the section), so a narrower cap has no
   support. A wider cap reaches into the population, which grades -4%.
3. **Keep the line/side lock.** It is a no-op in 736 of 791 groups. Where it bit (54 side flips) it was a wash overall,
   and it led in the 21 pairs where consistency was at stake. It also keeps a posted side stable.
4. **Set expectations: the 10-14..10-22 run (+30.9%) was mostly variance.** Over 205 more bets / 83 games the section is
   +3.5% [-7.7, +14.7]. Public copy should quote the season record with its denominator, not the early run.

**Evidence that would change this, pre-registered for the next read (window 11-09 onward, at >= 100 more NHL games):**

- **Cap:** if qualifying rows ranked <= 10 stay below ranks 11..30 AND below sticky, with the rank <= 10 upper bound
  < 0, re-examine the priority key (Suggested, best EV, books) rather than the cap size. If ranks 11..30 hold
  >= +5% with a lower bound > 0, test cap 40-50 on a replay before any change.
- **Pool:** if inside-minus-outside, bootstrapped by game as one paired statistic, has a lower bound > 0, the pool is
  confirmed. If the inside interval's upper bound falls below 0, the pool is not adding value.
- **An EV gate inside the section (the new lead):** if qualifying section rows with EV > 0 again lead EV <= 0, and the
  EV <= 0 upper bound is < 0, propose showing only EV > 0 rows (or ordering them first). This window's population cut
  (+13.5% vs -4.9%) is the hypothesis. It does NOT yet justify a change, because 10-23's in-pool EV split ran the other
  way.
- **Lock:** at >= 60 flipped pairs where a side qualifies, if the final-price side's ROI exceeds the locked side's with
  a paired interval clear of 0, drop the lock for SIDE (and keep it for the posted rows only).
