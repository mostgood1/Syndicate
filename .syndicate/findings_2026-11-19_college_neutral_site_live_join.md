# Findings 2026-11-19 — neutral-site college games go dark on the live rail when the odds feed orients them opposite to ESPN

Lane `college-neutral-site-live-join` (session 86eb6e0f, started from the rail monitor's session local_62433e58;
rail monitor I-29). Todo `#854`. All fleet reads were read-only at nice 19 against `~/syndicate-prod` /
`http://127.0.0.1:10000`. Times are CST unless marked Z.

## 1. The cause, file:line

The board's live rows and the live re-sim's lanes name the two teams in **different orders** on some neutral-site
games, and the join keys the **ordered** pair.

- **The rows carry the odds feed's away/home.** Every live NCAAB row is an odds-feed row (`book_grid`), so a
  neutral-site game whose home the odds feed assigns to the other team arrives as `away @ home` in that order.
  The slate follows the odds feed too: `syndicate/features/ncaab/slate.py:202` `orient_neutral_site_games` swaps a
  neutral-site game to the feed's orientation when the feed has only the reversed pair (`:251`, since 11-02,
  `92d9e9193`).
- **The live re-sim keys each game on ESPN's `homeAway`.** `syndicate/features/ncaab/live_resim.py:1447`
  `espn = _espn_names(summary)` reads each competitor's `homeAway` (`:1211-1221`), and `:1448` `board_name` (`:726`)
  only RESPELLS each name to the odds feed's spelling. It never reorders them. So `nameSource: odds` means the
  names are the board's, and the orientation is still ESPN's.
  - Cross-check: over 11-09..11-19, the lanes the re-sim actually wrote (`live_evidence/ncaab/*.jsonl`) match ESPN's
    scoreboard orientation for **459 of 459** NCAAB games and 467 of 468 WNCAAB games.
    - The WNCAAB exception: 11-18 Oregon State @ UC Riverside (401928312), not neutral.
    - Its lane was a refusal (`no_margin_anchor`, no number), and ESPN's scoreboard now reads the reverse.
    - Not chased: it published nothing a row could join.
- **The join keys the ordered pair.**
  - `syndicate/features/shared/live_gameline_join.py:2472` indexes each lane under `(away, home)`.
  - `:2757` looks each row up under its own `(away, home)`.
  - `:2319` `resolve_live_gameline` reads `candidates` for that exact pair.
  - A reversed game misses. Its full-game rows are withheld `no_live_gameline_projection`, and its segment rows get no
    Live number.
  - #791's alias fallback is NCAAF-only (`_TEAM_ALIAS_JOIN_SPORTS`) and keys an ordered canonical pair, so it does not
    help.
- **The odds feed's orientation is not stable within a game.** It flips both ways. Ledger first and last row times:

  | game (11-19) | rows in ESPN's order | rows reversed |
  |---|---|---|
  | Murray St / NC State (401918959) | 5:20-6:47 PM, 286 of 342 full-game rows modelled | 5:06-5:19 PM (the tip), 24 rows, 0 full-game rows modelled |
  | WVU / Florida (401920517) | 1:33-1:43 PM, 66 of 66 modelled | 1:47-3:20 PM (to the final), 65 rows, 0 modelled |
  | Auburn / Notre Dame (401920519) | none | 4:08-5:55 PM (tip to final), 71 rows, 0 modelled |

  So a fix that re-orients the producer from the slate would lag every flip by a re-sim tick and a slate refresh. A
  join that maps sides by team on every board build does not lag.

## 2. The re-sim's own numbers were right (no home edge, anchor on the right side)

`/mnt/c/tmp/cnsl/hca.py`, 11-19's three neutral-site games that had a lane. For each game: the published
`inputs.pregameHomeMargin`, today's fleet code's prior computed both ways, and the closing market in the lane's frame
next to the lane's first (tip) projection:

| game, lane frame | published | neutral prior / swapped | home-site prior | close (lane frame) | tip proj. |
|---|---|---|---|---|---|
| Murray St @ NC State | 8.68 | 8.68 / -8.68 | 13.14 | +3.5 | +4.76 |
| Florida @ WVU | -5.61 | -5.61 / +5.61 | -1.15 | -7.5 | -5.77 |
| Notre Dame @ Auburn | 6.63 | 6.63 / -6.63 | 11.09 | +4.0 | +4.14 |

- Every published margin equals the NEUTRAL prior exactly. Swapping the sides negates the margin and leaves the total
  unchanged. A home-site prior would have read 4.46 points different (13.14, -1.15, 11.09).
- Why, in the code:
  - `live_team_model.py:257` `edge = 0.0 if neutral`;
  - the prior calibration's `gamma` applies only when `home_site` (`prior_calibration.py:88`);
  - the possession engine has no home-only term;
  - the margin anchor maps the closing market and the pregame sim onto the live home side by team id
    (`live_resim.py:860-881`; it tries both orientations, `:875`).
- So the lanes were correct in ESPN's frame. Only their LABELS disagreed with the rows, and a side-mapped join is
  sufficient. No re-sim change is needed.

## 3. Frequency since 11-02, with denominators

`scripts/college_neutral_site_history.py` (on main with the fix). Sources per Central date:

- ESPN's own orientation: the public scoreboard, the GET the slate makes every minute, parsed before the slate
  reorients.
- The slate artifact.
- The live gameline ledger, which holds the rows' own orientation. A full-game row the join misses is never written,
  but the game's segment rows are, so a dark game still appears, with no modelled full-game row.

Raw output: `C:\tmp\cnsl\history_{ncaab,wncaab}.{txt,json}`.

**NCAAB, 11-02..11-19 (18 dates):**

| | count | of |
|---|---|---|
| D1 games on the slates | 807 | |
| games with live rows | 782 | 807 |
| neutral-site games | 67 | 807 |
| neutral-site games with live rows | 61 | 67 |
| **games whose rows were reversed against the lane at some point** | **24** | 61 neutral live (39%); 0 of 721 non-neutral |
| **of those, dark while reversed** (0 modelled full-game rows in the reversed order) | **24** | 24 |
| reversed the whole game (no row ever in ESPN's order) | 17 | 24 |
| reversed for part of the game (the feed flipped) | 7 | 24 |
| baseline: games whose rows were never reversed and still had 0 modelled full-game rows | 22 | 758 (2.9%; 14 on 11-02, other causes) |

- **About 1.3 dark games a day.** By date: 11-02 6; 11-06 2; 11-07, 11-08, 11-09 1 each; 11-11 2; 11-12, 11-14 1
  each; 11-15 2; 11-17 3; 11-18 1; 11-19 3. 0 on the 6 other dates.
- **The slate's `reoriented_neutral_site` is a proxy, not the count.**
  - Its total over the 18 final files is 23. 20 of the 24 reversed games are among them.
  - The rest flipped back before the slate's last write (SDSU / Colorado 11-07, Rutgers / Houston and Liberty / SIU
    11-17, Murray St / NC State 11-19).
- The 24 games: 11-02 Miami/Florida, Arizona/UCLA, Murray St/Tennessee St, UTEP/NKU, Furman/Bethune-Cookman,
  FSU/FAMU; 11-06 Saint Louis/Missouri, UT Arlington/Portland; 11-07 SDSU/Colorado; 11-08 Cal/Houston; 11-09 Seton
  Hall/Charlotte; 11-11 KC/FAMU, USF/St Joseph's; 11-12 Bradley/Coppin St; 11-14 George Mason/Bradley; 11-15
  Baylor/Texas, Marquette/Missouri; 11-17 Rutgers/Houston, Arkansas/Indiana, Liberty/SIU; 11-18 Washington
  St/Hawai'i; 11-19 Murray St/NC State, WVU/Florida, Auburn/Notre Dame.
- **WNCAAB:**
  - 822 games, 27 neutral-site, 11 neutral with live rows, 4 reoriented on the slates;
  - **0 reversed live games, 0 dark.** The same code path is exposed; it has not fired yet, because few women's
    neutral games are quoted live.
- **LIVE_GAMELINE_BUILD** (rotated refresh-worker logs, about 11-12 onward) is per build, not per game, so it cannot
  attribute a miss to a game. It corroborates 11-19: the rail monitor's `lgb.py` read projected 0 / full_games 0 on
  every build while WVU / Florida and Auburn / Notre Dame were the only live NCAAB games (readings 6-10).
- **Coming up:** Feast Week (11-25..11-29) is the season's densest neutral-site week, and it falls after the 11-24
  window.

## 4. The fix (on main, absent = SHADOW)

`syndicate/features/shared/live_gameline_orientation.py`, called from `board_enrichment.attach_live_gamelines_for_sport`
(`board_enrichment.py:3107` `prepare`, `:3122` `finish`). That function is the one attach behind both the book-grid
tick (`book_grid_artifact.py:676`) and the Layer 2 shortlist (`pipeline/layer2_shortlist.py:1538`).
`live_gameline_join.py` is not edited; it is held by lane `live-player-exit-gate`.

- **How it works:**
  - After the join's index is built, each lane is also filed under the REVERSED pair as a view restated in the row's
    frame, in the full-game index and in every segment index.
  - The join's own resolver reads `candidates` first, so the rows meet a hit already in their frame. Every pricer, gate,
    display block and ledger copy downstream is unchanged.
- **Restated fields:**
  - `home_win_prob`: `1 - p` on the full game, which is exact because a full game cannot end level. A segment
    recomputes `P(margin > 0)` from the restated histogram, so its tie mass stays out of both sides.
  - `margin_dist`, `margin_dist_raw` and `margin_dist_display` keys are negated; `home_margin` is negated.
  - The state scores are swapped, and `pregame_home_win_prob` becomes `1 - p`.
- **Guards:**
  - EXACT FIRST: a view is filed only under a pair with no exact candidate.
  - Every hit field is classified as side-free or restated. An unclassified field, a non-integer histogram key, a
    side-bearing `progress` key or a per-line analytic market refuses the view by name; college lanes publish none of
    these.
  - NCAAB and WNCAAB only.
- **The switch `SYNDICATE_COLLEGE_LIVE_JOIN_ORIENTATION`:**
  - absent = `shadow`: files nothing, serves byte-identical rows, and counts the rows that would join;
  - `on`: files the views;
  - `off`: does nothing.
- **Instruments:**
  - `[live_gameline_orientation] COLLEGE_ORIENTATION_JOIN sport= mode= games= rows= joined= error= pairs= refused=`
    on refresh-worker, printed only when a reversed row, a refusal or an error exists;
  - `orientation_reversed` in the join's coverage on every college build. It goes into `index_diagnostics` (the
    LIVE_GAMELINE_BUILD line's `index_why`) only when the line above prints. That line is capped at 1,000 chars and
    drops its widest dict, so an always-present zero would crowd out `withheld_by_reason`.
- **Tests: `tests/test_live_gameline_orientation.py`, 14 passing.** They cover:
  - the switch;
  - the side mapping by hand on a WVU / Florida-shaped game: h2h 0.70 for the row's home, spread raw 0.70 at WVU +3.5
    where the lane frame reads 0.30, state 32-23, H2 margin +0.9;
  - the segment's tie mass (0.50, not 0.70);
  - lanes written by the NCAAB and WNCAAB producers' own functions, through `board_enrichment`'s own attach, equal an
    independently hand-flipped twin row for row;
  - off != on, shadow == off for every served row, exact first, and an exact join identical in every mode;
  - every real hit field classified, an unclassified field refused by name, and the log line parseable.
- **Neighbouring suites:** 605 passed, 0 failed.
- **Replay on fleet data** (`C:\tmp\cnsl\replay.py`, this worktree's code over a captured snapshot and grid): on the
  6:47 PM capture (10 live NCAAB games, all in ESPN's order), off, shadow and on gave identical rows. See section 6
  for the reversed-game replay.

## 5. Pre-registered prediction for the first live evening after `on` loads

Registered 2026-11-19, before any load. The load is a betting change: it adds live rows that can carry an edge.

- **P1 (mechanism).** On every board build where a live NCAAB or WNCAAB game's rows are in the reverse of its lane's
  order, `COLLEGE_ORIENTATION_JOIN mode=on` prints with `games >= 1` and `joined >= 1`. The reversed game's full-game
  rows carry a live model: the `lgb.py` / rail `live_games_no_model` count for reversed games is **0** wherever the
  lane itself is priced (not refused).
- **P2 (side mapping, same-instant read).** For each reversed game, one same-instant read of the snapshot and the
  grid:
  - the full-game h2h row's `live_gameline.home_win_prob` equals `1 - lane.modelHomeWinProb` to 1e-9;
  - its `state_home_score` equals the lane's `awayScore`;
  - its `home_margin` equals minus the lane's `homeMargin`.
- **P3 (frequency).** At least one reversed NCAAB game in the first three live evenings after the load. History:
  about 1.3 a day; 12 of the 18 dates had at least one.
- **P4 (no collateral).** On games joined in ESPN's order, `rows_live_gameline_projected` and the rows' verdicts are
  unchanged: the tests pin this, and the shadow-period counts give the before.
- **Not predicted:** whether those games' flags win. They join an existing, measured population (college live
  full-game lines), and the portfolio monitor grades them there.
- **Falsified if:** a reversed game's rows stay dark with `on` while its lane is priced; or P2 fails on any reversed
  game; or a game in ESPN's order changes.

## 6. Tonight's replay, and what the shadow period adds

- **Shadow loads with the next fleet ff that carries the code.** It is not a betting change: rows are byte-identical,
  tested. From then on, every reversed game is counted live before the switch goes on.
- **The reversed-game replay, 11-19 7:35 and 7:38 PM CST** (`C:\tmp\cnsl\replay_ncaab_20261120T013517Z` and
  `..._013818Z`):
  - The game: UNLV / Rutgers (401920520), neutral. ESPN lists Rutgers @ UNLV, so the lane is home UNLV; the rows read
    UNLV @ Rutgers.
  - This worktree's code was run over the fleet's own snapshot and grid, captured at the same instant.

  | capture | fleet (rows with a model) | off = shadow | on |
  |---|---|---|---|
  | 7:35 PM | 0 / 19 | full-game 0 / 13 modelled; 13 `no_live_gameline_projection` | all 19 rows joined; 13 full-game rows reach the quote gates and are refused there (stale quote / quote behind the score, as on any game); 19 Live-column numbers |
  | 7:38 PM | 0 / 29 | full-game 0 / 18; 18 `no_live_gameline_projection` | 29 of 29 joined; full-game 7 / 18 modelled, **5 priceable**; `no_live_gameline_projection` 0 |

  - Side mapping on the 7:38 PM h2h row:
    - row home Rutgers 0.7600 = 1 - lane `modelHomeWinProb` 0.24 (lane home UNLV);
    - row state home 10 / away 2 = lane away 10 / home 2 (Rutgers led 10-2);
    - priceable, edge +8.75 pp: a flag the board could not show.
  - Shadow rows == off rows in both captures. The 10 games in ESPN's order are identical in all three modes.
  - Seton Hall / Wisconsin, also reversed on the slate, had no live rows in either capture.
- **Second replay, Kansas / Houston, 10:34 PM CST** (`/mnt/c/tmp/cnsl/replay_ncaab_20261120T043448Z`; reported by
  the rail monitor at 10:33 PM, readings 17 and 23):
  - The lane is home Kansas (ESPN Houston @ Kansas); the rows read Kansas @ Houston.
  - The slate read Houston @ Kansas, unswapped, at 6:55 PM. Its `reoriented_neutral_site` went 4 -> 5 by 04:33:55Z:
    the odds feed's orientation changed later in the day.
  - Fleet: 0 of 61 rows with a model.
  - Switch `on`:
    - 61 of 61 joined, 53 Live-column numbers;
    - full-game 9 of 31 modelled; `no_live_gameline_projection` 31 -> 0;
    - none priceable: stale quotes, and no two-sided market at the moment.
  - Sides: row home Houston 0.9425 = 1 - lane 0.0575 (lane home Kansas); state 26-10 restated.
  - Shadow == off.
- **Tonight's tally (rail monitor, re-read here for the two games captured):**
  - 5 of 7 NCAAB neutral-site games were reoriented, and all 5 were dark: WVU / Florida, Auburn / Notre Dame,
    Rutgers / UNLV, Seton Hall / Wisconsin, Kansas / Houston.
  - The other 2 joined directly.
  - The history count in section 3 (24, to about 6:50 PM) does not include the 3 evening games.

## 7. NCAAF: measured, not exposed so far (2026-11-20)

- **The shape is the same.** The NCAAF live lens takes its home/away from the CFBD projection artifact
  (`run_refresh_worker.py` `_run_ncaaf_live_resim_tick` builds `games` from `smartsim2_projections_<season>_wk<w>.csv`),
  while the rows carry the odds feed's.
- **The data:** `/mnt/c/tmp/cnsl/ncaaf_rev.py`, read-only on the fleet. It compares the NCAAF live gameline ledger
  10-01..11-19 (37 dates) with the 2026 artifacts wk4..wk12.
- **Result: 0 of 420 live NCAAF games had rows reversed against the lens.**
  - Direct games with no modelled full-game row: 35 of 420, other causes.
  - 7 live FCS games were in no artifact.
  - So CFBD and the odds feed agreed on every regular-season game, including the neutral-site rivalries.
- **Not measurable yet:** conference championships (12-05), Army-Navy (12-12) and the bowls, where "home" is assigned
  per game.
  - The pregame NCAAF join already met one flipped neutral site (state_football: CFBD Arizona State @ Kansas at
    Wembley against the odds feed's reverse).
  - Extending `ORIENTATION_JOIN_SPORTS` to `ncaaf` would need its hit fields classified first. NCAAF hits can carry
    possession-side state.
  - Re-measure after 12-05. The script is now on main as `scripts/ncaaf_live_orientation_check.py` (`8a818a4f9`).
  - It reproduces this section's numbers: 420 live, 0 reversed, 35 dark for other causes.
  - It also names the second NCAAF orientation failure: ESPN's order against CFBD's, which makes the lens refuse
    `no_live_state`. That was 0 of the 35 here; 34 of them predate the evidence log (11-09), and 1 was
    `game_not_in_progress`.
  - Scheduled: task `ncaaf-orientation-recheck-1207`, Mon 12-07 9:00 AM CST, over 11-20..12-06.


## 8. First evenings after the load (11-24..11-26 CST; read 2026-11-27 9:30 AM CST)

Read-only, scheduled task `college-orientation-join-reading-1127`. Load: CHANGE G of the 11-24 window batch,
2026-11-24 08:30:37Z (2:30 AM CST); `SYNDICATE_COLLEGE_LIVE_JOIN_ORIENTATION=on` read from /proc on refresh-worker
(pid 469, the 11-26 17:19Z restart) and live-odds-worker on 11-27, and 1 `=on` line in `local_production.env`.

**P1 log lines** (`refresh-worker.log` + `.1`..`.5`, which cover 11-21 08:13Z .. 11-27 15:31Z; timestamped lines
only, `ALL_PROCESS_MEMORY` excluded, de-duplicated). 4,233 lines since the load, ALL `mode=on`; 0 `shadow`, 0 `off`
(2,921 shadow lines before the load).

| sport | lines | first / last (UTC) | distinct `pairs` | max games | rows sum / max | joined sum / max | lines joined=0 |
|---|---|---|---|---|---|---|---|
| ncaab | 3,249 | 11-24 15:14Z / 11-27 05:13Z | 35 | 4 | 186,376 / 192 | 160,947 / 177 | 112 |
| wncaab | 984 | 11-25 02:10Z / 11-27 01:19Z | 12 | 3 | 23,588 / 64 | 23,215 / 64 | 0 |

- `error=none` on 4,233 of 4,233. `refused={}` on all 4,233: the one non-`{}` value was a log line with a
  `MEMORY_WATCHDOG` line glued on (11-26 02:25:18Z), not a refusal. No `unclassified_field`: no code drift.
- All 112 `joined=0` lines are one pair, Saint Louis @ Stanford (rows' order), 11-26 06:24Z..17:07Z: see the dark
  games below.

**P1/P3/P4 per game** (`scripts/college_neutral_site_history.py` from origin/main, ESPN scoreboard + slates + live
gameline ledger, 11-24..11-26):

| league | ESPN games | live with rows | neutral live | reversed live | dark while reversed | direct live dark / direct live |
|---|---|---|---|---|---|---|
| ncaab | 157 | 157 | 85 | **26** (10 / 7 / 9 by date) | 3 | 1 / 131 (0.8%) |
| wncaab | 114 | 32 | 26 | **9** (1 / 6 / 2) | 0 | 0 / 23 |

- Baseline 11-02..11-19: 24 of 24 reversed NCAAB games dark; direct dark 22 / 758 (2.9%).
- **32 of 35 reversed games carried modelled full-game rows in the reversed order**, e.g. Oklahoma @ Pittsburgh
  981 / 993, UCLA @ Saint Mary's 1,095 / 1,104, LSU @ SMU 1,204 / 1,229; WNCAAB Utah @ Miami 503 / 510.
- Reversed NCAAB (ESPN order): 11-24 Wright St @ St. Bonaventure, Oklahoma @ Pittsburgh, San Francisco @ Oregon St,
  New Haven @ Lindenwood, Kent St @ Wyoming, Robert Morris @ Lamar, Georgia Southern @ Bellarmine, Santa Clara @
  Nevada, Duquesne @ High Point, Saint Louis @ Grand Canyon; 11-25 LSU @ Arizona St, Southern Utah @ Long Beach St,
  Princeton @ Liberty, Texas A&M @ Xavier, Omaha @ UC Davis, Grand Canyon @ Colorado, Stanford @ Saint Louis; 11-26
  UCLA @ Saint Mary's, Louisville @ St. John's, Alabama @ Kansas St, USC @ Utah St, LSU @ SMU, Maryland @ San Diego
  St, Arizona St @ South Carolina, UC Davis @ Jacksonville St, Pacific @ Omaha.
- Reversed WNCAAB: 11-24 Virginia @ UAB; 11-25 Vermont @ Texas Southern, Robert Morris @ Stetson, Arizona @ GW, Utah @
  Miami, Middle Tennessee @ Montana St, SMU @ Memphis; 11-26 Minnesota @ Missouri St, North Dakota St @ Fairfield.
- **The 3 "dark" reversed games are not P1 failures** (evidence `live_evidence/ncaab/<date>.jsonl` by ESPN id):
  - Robert Morris @ Lamar (401925014, 11-24): 5 reversed SEGMENT rows, all at 23:43:15Z, 0 reversed full-game rows;
    the lane's first row is 23:44:08Z (as_of 23:43:35Z). No lane existed to join. 487 of the game's 491 direct
    full rows modelled.
  - Santa Clara @ Nevada (401911458, 11-24): 12 reversed segment rows 00:16:26-00:17:33Z, 0 full; lane first at
    00:20:39Z. Same shape; 552 of 561 direct full rows modelled.
  - Stanford @ Saint Louis (401921672, 11-25; tip 06:08Z = 12:08 AM CST 11-26, Acrisure Arena; final 66-64): the lane
    was refused `no_plays` at 05:11Z and 06:00Z, priced ONCE (as_of 06:12:39Z, 3-4, 1st half 1081 s), and never
    updated again (the same as_of re-observed at 17:12Z). The join served it: `joined=16..23` at 06:13-06:18Z (3
    lines); the ledger wrote no reversed full-game row in that window (10 NCAAB ledger rows in all of 06:05-06:40Z).
    From 06:24Z `joined=0`: the lane was stale. The orientation join worked; the LANE froze after one tick, a
    lane-side defect. Lead (unverified): the tip was after Central midnight on a game dated 11-25. The game's rows
    also stayed on the board 11 h after FINAL (rows=12 to 17:07Z).
- The rail monitor's 11-24 reading agrees: 9 of 10 reversed games modelled; the 10th, WNCAAB Arkansas @ High Point,
  was refused `no_margin_anchor` (lane-side).
- P4 (reported, not gated): direct-order dark 1 / 131 NCAAB, 0 / 23 WNCAAB, against 22 / 758 before.

**P2 side mapping** (reversed full-game h2h ledger rows with `model_home_win_prob_raw`, matched to the evidence lane
row whose `as_of` = the row's `live_state_as_of`):

| game | checked | matched | mismatches |
|---|---|---|---|
| NCAAB Oklahoma @ Pittsburgh 11-24 | 116 | 116 | 0 |
| NCAAB Grand Canyon @ Colorado 11-25 | 152 | 152 | 0 |
| NCAAB UCLA @ Saint Mary's 11-26 | 132 | 132 | 0 |
| NCAAB Louisville @ St. John's 11-26 | 146 | 146 | 0 |
| WNCAAB Utah @ Miami 11-25 | 106 | 106 | 0 |

- 652 of 652 rows: raw = 1 - `modelHomeWinProb` (1e-6), state scores swapped, `model_margin_mean` = -`proj.homeMargin`
  (1e-6). Example: Oklahoma @ Pittsburgh 18:33:33Z, row 0.4575 vs lane 0.5425, row 2-0 = lane away 2 / home 0,
  margin -0.81 vs +0.81. 0 ambiguous as_of, 0 unmatched.

**Verdicts:** P1 **MET** (4,233 `mode=on` lines; every reversed game whose lane was priced joined; 0 errors, 0
refusals). P2 **MET** (652 / 652). P3 **MET** (26 reversed NCAAB in 3 evenings, every evening). P4 **MET** (1 / 131
direct dark, below the 2.9% baseline). Source: scratchpad of scheduled task `college-orientation-join-reading-1127` (raw: `coj.txt`, `hist_{ncaab,wncaab}.{txt,json}`, `p2.py`).
