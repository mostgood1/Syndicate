# 2026-11-23: Layer 2 rail monitor findings (lane `layer2-rail-monitor`)

The user said, 11-19 ~1:00 AM CST: "this should just be an always on monitor moving forward". Lean mode since 11-20: the Windows task `SyndicateRailWatch` takes every reading, and Claude runs the nightly close.

## The monitor ran an old page copy for four days, fixed 11-23 ~2:30 PM CST (main `bbbbb4b3f`)

- **What was wrong:** until `bbbbb4b3f`, the probe's `--no-page` reused `readings\served.html` forever. Every tick from 11-20 to 11-23 2:03 PM CST therefore ran the rail code of the 11-19 11:00 PM page.
  - **Read every rail verdict from 11-20 to 11-22 with that in mind** (chip-less cards, det1-det3, flipped and team defects). The grade and the API fields (board cadence, overlay, floor, sweeps) do not depend on the page copy.
- **The fix:** the probe now refetches the page once its copy is 60 minutes old (`--page-max-age-min`, default 60). The runner also keeps a list per canonical and exact chip key and picks on start, like the page since `3983309ce` (asked by session local_15f2d5e2).
- **The one failed tick:** 2:23 PM CST (rc 1, no `rail.json`). The primary tree's auto-ff landed `bbbbb4b3f` mid-run: the old probe was in memory, the runner was new, and the page was from 11-19.
  - The user said "fast-forward the primary tree now" (`a5637a517` -> `d845fe345`, 2:28 PM).
  - From the 2:43 PM tick on, every reading was clean.
- **R-I check, measured at this close:** MET on all three parts.
  - (1) The primary tree holds `bbbbb4b3f`.
  - (2) Readings 14-44 have `page_age_min` at most 59.9 and no `page_fetch_error`.
  - (3) LAFC @ St. Louis City SC (401933728) was chip-less at readings 1-13 (59 rows at r13) and at none from r14 on.

## Fleet-watcher flag: soccer overlay gaps R30 869 s, R32 750 s, R34 711 s (x2), 8:03-9:03 PM CST; read-only

- **Verdict:** this is the evening-MLS UTC/CT date split, NOT the low-headroom refusals.
  - All 42 refusals from 00:00 to 03:30Z were live-odds-worker `LIVE_LENS_TICK_DIAG` lines (19 of them soccer). Refresh-worker, which builds the overlay, logged 0.
  - LAFC @ St. Louis City (01:15Z kickoff) had its in-play rows in the soccer **2026-11-24** file. That file was rebuilt every 711-877 s (02:03..03:21Z, rows 63 -> 31), while the 11-23 file was rebuilt every 2-3 min.
  - R34's second gap was the 11-23 file (449 s, 03:03:55 -> 03:11:24Z).
  - Read with `C:\tmp\railmon\diag_1123_soccer_gap.sh` and `diag_1123_soccer_gap2.sh` (read-only, nice 19).
- **Cost:** at 9:23 PM the rail's LAFC card (live, 90'+10') showed 2 live rows and 1 market.
- **Window aliasing:** windows that read 0 gaps had the same cadence. A 20-min window holds about one build of the 11-24 file, so it can read no gap at all.
- **Routed** to lane `evening-utc-date-split` (session local_15f2d5e2).
  - Its answer: change O (the soccer Central quote shard, `e5a0ecd29`, default off, in the 11-24 batch) moves the overlay too, because the overlay date is the grid date, which is the quote-shard date (`book_grid_artifact.py:563-564`, `:862`; checked on main).
  - Their P-E3: Rail Watch's `overlay_offdate_inplay` stays empty. Graded at the 11-24 close on HOU @ SJ (runbook R-K).

## DAILY SUMMARY — Mon 11-23 (day 9), closed 1:05 AM CST 11-24

44 readings by the Windows task, 10:03 AM to 12:43 AM CST, every 20 min. 1 tick failed (2:23 PM, above). POP_START is 16:00Z. Flags are graded on their first sighting, against the finals by date (`C:\tmp\railmon\grade_2026-11-23_out.json`).

The grade ran while Colorado St @ Arizona and San José St @ UC San Diego were still live, so 11 flags are ungraded (`not_final`). From 12:03 AM the rail and the chips had rolled to 11-24, so the monitor did not see those two games after midnight (the midnight family, #792 / #782).

### The grade

| bucket | flags | games | W-L-P | hit | fair | hit − fair, 90% CI (game-clustered) |
|---|---|---|---|---|---|---|
| **ALL** | 382 | 49 | 198-184-0 | **0.518** | 0.454 | [+0.012, +0.119] |
| P3 first reading: yes | 49 | 28 | 20-29 | 0.408 | 0.483 | [−0.211, +0.071] |
| P4 fair < 0.40 | 67 | 16 | 13-54 | 0.194 | 0.191 | [−0.047, +0.073] |
| P5 NCAAB full totals | 73 | 27 | 43-30 | 0.589 | 0.502 | [−0.028, +0.208] |
| sport: NCAAB | 174 | 27 | 93-81 | 0.534 | 0.503 | [−0.037, +0.101] |
| **sport: NBA** | 183 | 10 | 89-94 | **0.486** | 0.402 | [+0.006, +0.171] |
| sport: WNCAAB | 14 | 6 | 8-6 | 0.571 | 0.490 | [−0.119, +0.308] |
| sport: soccer | 8 | 4 | 8-0 | 1.000 | 0.540 | (4 games) |
| sport: NHL | 3 | 2 | 0-3 | 0.000 | 0.416 | (2 games) |

- **The flags beat their fair price for the 6th day in a row (11-18 to 11-23), and for the 2nd day the CI clears 0.** The model's mean p was 0.559 against a 0.518 hit, so it is ~4 pp over-confident on its own side (#847). On 11-22 that gap was ~7 pp.
- **NBA beat fair for the first time in 6 days** (0.486 vs 0.402, CI clear of 0, 10 games).
  - The body carried it: 0.583 vs 0.467.
  - Its long shots went 1-31 (0.031 vs 0.095, CI below 0), as they have all week.
- **NCAAB full-game totals: the unders went 0.650 (60 flags) and the overs 0.308 (13 flags).** The flagged lines went over 25 of 73 times.
- 13 flags were not graded: 11 not final and 2 with no probability.

### Pre-registered verdicts (standing P1-P6, P8)

| # | prediction | result | verdict |
|---|---|---|---|
| P1 | 0 rail-card contradictions | 0 at all 44 readings (0 skew-consistent either) | **MET** |
| P2 | board publication gap median ≤ 600 s, none > 1,800 s, 5:30-10:30 PM | 44 publications, median **384 s**, max 901 s (7:18 PM), 6 over 600 s (`p2_boardpub.py`) | **MET** (11-22: median 317 s, max 724 s) |
| P3 | first-reading flags at or below fair | 0.408 vs 0.483, CI [−0.211, +0.071] | **MET** (below fair, within noise) |
| P4 | long shots (fair < 0.40) at most fair + 2 pp | 0.194 vs 0.191 | **MET** |
| P5 | report NCAAB calibrated live full totals | 73 flags / 27 games, 0.589 vs 0.502; under 60 (0.650) / over 13 (0.308); the flagged lines went over 25 of 73 | report |
| P6 | 0 pregame NCAAB / WNCAAB totals flags | 0 at all 44 readings | **MET** |
| P8 | score floor: 0 college calibrated full totals below the score | 0 of 1,574 rows | **MET** |

### What the day found

- **The monitor had been reading an 11-19 page copy since 11-20.** Fixed (block above). The 11-20 to 11-22 rail verdicts were taken on old rail code.
- **The MLS playoff team-card lead (3 slates old) is closed.** `3983309ce` (web, 2:08 PM) gave LAFC @ St. Louis City its card on 401933728, and the monitor saw 0 chip-less cards from 2:43 PM on.
- **The evening soccer overlay ran on an 11-24 file** (block above). Change O in tonight's batch is meant to fix it, and the 11-24 close grades it (R-K).
- **After midnight:** the 12:03 AM reading counted 12 flipped cards on the new 11-24 slate (all pregame). They were gone at 12:23 AM. On 11-21 and 11-22 the post-midnight team defects lasted all night (5 and 2).
- **I-29 hit 12 college games** (4 NCAAB, 8 WNCAAB, up from 16 on 11-22). **None of the 12 carried a live model.** Examples: Arkansas St @ Southern Utah (7 readings), Nevada @ San Francisco (6), Illinois St @ Santa Clara (6), Michigan @ Miami and MTSU @ Oregon St (WNCAAB, 6 each). Change G (the I-29 fix) is in the 11-24 batch.
- **Other games with no live model, as unique games:**
  - WNCAAB `no_margin_anchor`: 5 (Radford @ Furman, 5 readings);
  - NCAAB / WNCAAB `not_in_resim` at tip-off: 5 / 2;
  - NHL `in_intermission`: 6, and `budget_exhausted`: 3 (Calgary @ Ottawa, Toronto @ Islanders, Utah @ Winnipeg, one reading each; this reason has appeared since 11-21);
  - NCAAB `no_plays`: 1 (NC A&T @ SC State, 3 readings) and `pbp_score_mismatch`: 1;
  - NFL `uninformative_probability`: 1 (Cincinnati @ Washington, 3 readings).
- 0 false and 0 missed flags at every reading; dark rows at most 3 (r14, all `board_cadence`).

### Owned readings

- **R-F #850 did not qualify:** 18 core live games at 7:03 PM and 23 at 7:23 PM (threshold 33). The session local_d0f83044 is archived (the user's ask), so any further numbers go to lane `board-split-memory-guard`. Context on the parent that was reset at 4:17 AM:
  - 21 refusals at the P1 stage, 5 PM to 10 PM CST (5 / 7 / 4 / 1 / 4 an hour);
  - 1 exit (rc 75, `heavy_build_refused`, 7:25 PM);
  - longest build gap 901 s; `held=transient_jobs` 10 of 10;
  - parent RSS 8-10 PM p50 **1,994 MB** (n 6, 1,924-2,020).
  - The parent grew from 1,039 MB at 10 AM to ~2 GB by 9 PM. That is the same evening level as 11-22 (1,974 MB), which also started from a morning reset. The reset sets the morning level, not the evening one.
- **R-I** (the page copy): MET (block above).
- **R-J** (soccer overlay gaps): diagnosed and routed (block above).
- **R-K** (P-E3 for change O) and **R-H** (#860 St. Louis): at the 11-24 close, only if the batch loads them.
- **R-B / R-D / R-G:** 11-24, only if their changes load (one-shot crons exist).

### Loads (11-23 slate)

All four are betting change no.
- **4:17 AM:** refresh-worker parent reset (#850), no code change.
- **8:17 AM:** web: no automatic full garbage collections in web workers (`05a2ce65e`, BC-058).
- **2:08 PM:** web: the rail keeps every chip on its canonical key and picks on start (`3983309ce`).
- **2:30 PM:** web: Ask's headline is the board's own picks (`d845fe345`, #861 step 1a).
- Readings 1-13 ran on fleet head `05a2ce65e`, and readings 14-44 on `d845fe345`.

### Open user decisions

- **The 11-24 window batch** runs at 2:15 AM CST. The fleet-watcher keeps its queue.
- **#857** (web's worker recycle limit to 1,500 MB): recommended after #853's first evening (11-24).
- **#850's next lever** now goes through lane `board-split-memory-guard`.
