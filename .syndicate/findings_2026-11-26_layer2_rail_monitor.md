# 2026-11-26: Layer 2 rail monitor findings (lane `layer2-rail-monitor`)

The user said, 11-19 ~1:00 AM CST: "this should just be an always on monitor moving forward". Lean mode since 11-20: the Windows task `SyndicateRailWatch` takes every reading, and Claude runs the nightly close.

## Fleet-watcher flag: soccer FC Copenhagen @ Inter Club d'Escaldes "not_in_resim" at R13 and R14 (to 2:23 PM CST); read-only

- **Verdict: the monitor's own name miss, fixed. No fleet defect, cost 0.** The lens held the match: ESPN 401915738, uecl, spelled "F.C. København" @ "Inter D'Escaldes", `projection` null and `momentum.reason` `competition_not_modelled` (the #699 gate). Read from redis `soccer_live_lens.json` (generated 2:26:38 PM CST) with `C:\tmp\railmon\diag_1126_escaldes.py` (read-only, nice 19).
- **The cause was Copenhagen / København, not the apostrophe or the prefixes** (the watcher's guess). The home side already matched by the word-subset rule ("inter d'escaldes" inside "inter club d'escaldes"). The away side folded to "fc kobenhavn" against the rail's "fc copenhagen", and `team_aliases.chip_join_key` does not join them either.
- **Fixed in the monitor (`C:\tmp\railmon\p29_orient.py`, from 2:27 PM CST; repo copy `scripts/rail_monitor/p29_orient.py`).** `norm` maps native city names to the English ones word by word, on both sides, so it cannot split a pair that already matched: København, München, Köln, Praha, Beograd, București, Warszawa, Kiev, Athina, Wien, Moskva, Lisboa, Genève, Sevilla, Milano, Torino, Napoli, Roma, Firenze, Genova. It also folds curly apostrophes to straight ones.
- **Re-run at 20:27:50Z (2:27 PM CST):** the game reads `direct`, `competition_not_modelled` (uecl), like the other 17 live UEL/UECL games. 18 of 18 live soccer games matched the lens, 0 `not_in_resim`.
- The repo copy of `p29_orient.py` had not been refreshed since 11-22, so it also gains the 11-24 fixes (the ø fold, the UEFA `competition_not_modelled` reason, the `chip_join_key` fallback).

## Rail card OURS fix loaded (10:40 PM CST; user "Yes, fix it here", "Yes, lend it")

- **What:** a flagged full-game total's OURS on the rail card is now the flagged row's own live total, not the chip's PROJ box, which can be one re-sim tick apart (11-25 R20). The tooltip names the box's number when they differ. `fe46fb249`, display only, not a betting change.
- **Load:** ff + reload-web at 04:39:59Z 11-27, after lane `web-silent-worker-kills` loaded `b709934b2` to its exact SHA. Served page carries the branch; web log 0 errors; live page 0 console errors. deploys.md 2026-11-27 04:39:59Z.
- **Owed at the closes:** `ours_resim_tick` reads 0 on every reading after the load. No flagged total was a tick apart from its row at load time, so only the unit test exercised the new answer.

## DAILY SUMMARY -- Thu 11-26 (Thanksgiving, day 12), closed 1:45 AM CST 11-27

The Windows task took **46 readings**, every 20 min from 10:03 AM to 1:03 AM CST, with no failed tick (1 `p29` timeout recovered on its retry). Readings covered the last 90 min of the slate. Fleet heads: `e37a9697f` (R1-R5), `82bfc6bbd` (R6-R36), `30b2be76e` (R37-R38), `fe46fb249` (R39-R46). POP_START is 16:00Z. Flags are graded on their first sighting against the finals by date (`C:\tmp\railmon\grade_2026-11-26_out.json`). Every game was final at the grade; 0 flags skipped. A small slate: no NBA and no NHL; 4 NFL, 1 NCAAF.

### The grade

| bucket | flags | games | W-L-P | hit | fair | hit - fair, 90% CI (game-clustered) |
|---|---|---|---|---|---|---|
| **ALL** | 191 | 29 | 106-84-1 | **0.558** | 0.517 | [-0.032, +0.123] |
| P3 first reading: yes | 41 | 21 | 25-16 | 0.610 | 0.506 | [-0.042, +0.240] |
| P4 fair < 0.40 | 3 | 3 | 2-1 | 0.667 | 0.306 | (3 games) |
| P5 NCAAB full totals | 61 | 20 | 31-30 | 0.508 | 0.500 | [-0.146, +0.181] |
| sport: NCAAB | 167 | 21 | 91-75-1 | 0.548 | 0.518 | [-0.055, +0.123] |
| sport: WNCAAB | 12 | 6 | 9-3 | 0.750 | 0.495 | [+0.060, +0.393] |
| sport: NCAAF | 11 | 1 | 6-5 | 0.545 | 0.498 | (1 game) |
| sport: NFL | 1 | 1 | 0-1 | 0.000 | 0.857 | (1 game) |

- **The flags beat their fair price on the point for the 9th day in a row (11-18 to 11-26); the CI does not clear 0** (191 flags in 29 games). The model's mean p was 0.609 against a 0.558 hit, ~5 pp over-confident on its own side (#847); 11-25 was ~7 pp.
- **By market:** full-game totals 0.562 vs 0.503 (73 flags); full-game spreads 0.475 vs 0.500 (40, below fair again); segment spreads 0.600 vs 0.500 (15); segment totals 0.535 vs 0.499 (44); moneyline 0.737 vs 0.663 (19).
- **Totals leaned under, and the overs won.** 84 of 117 totals flags were unders, at 0.482 vs 0.502; the 33 overs went 24-9 (0.727, CI [+0.101, +0.339]). NCAAB full totals: unders 23-29 (0.442, 52 flags), overs 8-1 (9); the flagged lines went over 37 of 61 (11-25: unders 0.620, over 59 of 136). One day, and the under CI spans 0 ([-0.237, +0.131]).
- **Soccer had 0 flags:** the 13 live matches were Europa / Conference League, `competition_not_modelled`, by design. NFL's Thanksgiving games yielded 1 flag (Bears @ Lions had `uninformative_probability` at 1 reading).

### Pre-registered verdicts (standing P1-P6, P8)

| # | prediction | result | verdict |
|---|---|---|---|
| P1 | 0 rail-card contradictions | 0 at all 46 readings; 0 skew-consistent; 0 `ours_resim_tick` | **MET** |
| P2 | board publication gap median <= 600 s, none > 1,800 s, 5:30-10:30 PM | 56 publications, median **285 s**, max 860 s (04:13:32Z), 2 over 600 s (`p2_boardpub.py`) | **MET** (11-25: median 361 s, max 628 s) |
| P3 | first-reading flags at or below fair | 0.610 vs 0.506, +10.4 pp, CI [-0.042, +0.240] | **within noise** (above, not significant, as on 11-19 to 11-22) |
| P4 | long shots (fair < 0.40) at most fair + 2 pp | 0.667 vs 0.306, **3 flags in 3 games** | **NOT MET on the point; too few to read** |
| P5 | report NCAAB calibrated live full totals | 61 flags / 20 games, 0.508 vs 0.500; under 52 (0.442) / over 9 (0.889); the flagged lines went over 37 of 61 | report |
| P6 | 0 pregame NCAAB / WNCAAB totals flags | 0 at all 46 readings | **MET** |
| P8 | score floor: 0 college calibrated full totals below the score | **0 of 1,100** rows | **MET** |

- **P2's two gaps over 600 s** (802 s from 04:00:10Z, 860 s from 04:13:32Z) bracket the 10:18 PM step-1e board-child TERM (deploys.md 2026-11-27 04:18:28Z), which waited for a drained save: `POST_BUILD_CHECK` held `drain_requested` once (`p7count.py` 23:00-05:00Z). They are the deploy's gaps. Outside them the longest was 444 s.
- `ours_below_points` (#824) was 1, at R19 (4:03 PM).

### Owned readings and carry-overs (runbook R-L)

- **The rail card OURS fix (`fe46fb249`, loaded 10:39:59 PM): nothing to read yet.** `ours_resim_tick` was 0 at all 9 readings after the load (R39-R47), and `read_ours_fix.py` over R39-R42 found **0** flagged uncalibrated full-game totals: every flagged total after the load was calibrated (1-2 a reading), and the rail emptied after midnight. The branch's different answer has still only met the unit test. The owed reading stays open at the next closes.
- **#850 CHANGE J note:** the 11:10 AM reboot gave refresh-worker a FRESH parent (pid 469). It stayed at 1.1-1.3 GB through the evening (`ps` at each reading), not the ~2.2 GB of the note, and logged **0** `BOARD_PROCESS_RECYCLE` and 0 rc 75 exits in 5 PM-11 PM CST. 2 `MEMORY_GUARD_ABORT` (pre_source_state_fingerprint, both 6-7 PM). The board child (pid 535, 4.0-4.5 GB) ran from the boot to the 10:18 PM TERM; its successor is pid 256375. So the evening had no post-build recycles to read.
- **The NCAAB after-midnight cost (R46's lead from 11-25): REAL, on the rail card and on pricing; 0 on money so far.**
  - Two NCAAB games were live across the midnight roll: Baylor @ Gonzaga (tip 04:53Z) and Texas Tech @ Oregon (04:57Z). At 05:43Z each had a rail card with 15 rows (16-17 live rows). **From 06:03Z (12:03 AM CST) the rail rolled to 11-27 and neither game had a card** at R43-R45, though refresh-worker still had both in its live snapshot (`index=2` until 06:50Z). The page's Today filter drops a chip whose Central date is not the rail's date (`intelligence.html` ~4347), and the 11-27 chip list does not carry them.
  - **The same happened on 11-25:** 5 cards were live at 05:43Z 11-26 (Spurs @ Trail Blazers, 125 rows; 4 NCAAB) and 0 from 06:03Z. So it is every night with late West Coast games, and every sport, not only NCAAB.
  - **Pricing thinned on the D+1 shard.** The 11-26 shard built every ~40 s before midnight (15 builds per 10 min, ~80 considered rows per build, 128-281 rows written per 10 min). The 11-27 shard built every ~80 s (6-8 per 10 min, ~30 considered, **0-32 written per 10 min**). Overlay gaps on the 11-27 file were 144-153 s, none over 360 s; the 11-26 file's were 66-89 s before midnight (`overlay_offdate_inplay` `ncaab@2026-11-27` 19-24 rows). Reader: `C:\tmp\railmon\rl2_ncaab_midnight.sh`.
  - **Money:** 0 live bets on either game, before or after midnight (`live_bets_for.py`).
  - **Whose call:** two separate fixes, both the user's. (a) Keep a still-live game of the previous Central day on the Today rail after midnight: a web change plus reload-web, display only, not a betting change. (b) An NCAAB version of change O (quotes filed by the Central tip day): change O was a betting change (BC-070), so (b) is one too and could only load in the 12-08 window, default-off on main until then. No lane owns either (`evening-utc-date-split` closed 11-25).
- R-L (1) done: the 17:28:02Z web load is in `loads.json`, with the day's other 5 loads. R-L (3): the p844 sampler stopped by itself after 11-26.

### What the day found

- **The host was offline for the first hour of the slate.** Its Wi-Fi was down from 12:14 AM to 11:11 AM CST (deploys.md 2026-11-26 17:10:07Z, lane `portfolio-monitor`); Windows was restarted by hand at 11:10 AM. R1-R4 (10:03-11:03 AM) read **0 live games** (the chips could not update), and the day's 3 overlay gaps over 360 s (NCAAB 583 / 775 / 412 s) and tick gaps up to 489 s are all in those windows. After the boot, the longest overlay gap was 172 s.
- **Change G (#854, the I-29 orientation join) held for a 3rd evening.** 11 of the 12 college games whose lane was REVERSED carried a live model, at 61 of 62 game-readings (11-25: 12 of 15). The one miss: Robert Morris @ Clemson (WNCAAB), `no_margin_anchor` at 1 reading.
- **Games with no live model, as unique games: 22** (60 on 11-25, a bigger slate). `competition_not_modelled` 13 (soccer, UEFA), `key_player_out` 3, `not_in_resim` 2 (1 reading each), and 4 single games at 1-2 readings each (`no_margin_anchor`, `uninformative_probability`, `sport_absent_from_helper_read`, the reversed miss above).
- **Sweeps refused fell to 57 of 521 (11%)** (11-25: 28%; 11-24: 41%), on a slate with no NBA or NHL.
- Dark rows 2 at 1 reading, both `board_cadence`. 0 false flags, 0 missed flags. Web stale merges 1,128 of 1,231, in line with 11-23..11-25 (1,147 / 1,340 / 1,215).

### Loads (11-26 slate)

- **11:10 AM:** unplanned restart after the network outage; refresh-worker picked up `e37a9697f` (ride-alongs only). Not a betting change.
- **11:28 AM:** web: the NHL and soccer pages lead with the board's pick (`75624d138`, #861 step 1d; display only).
- **11:40 AM:** live-odds-worker: the exits record archives watch rows unseen for 24 h (`82bfc6bbd`, lane `exit-watch-unseen-prune`; not a betting change).
- **10:18 PM:** web + board child: the board shows the EV it judges, net of fee, and the Kalshi / Polymarket prices (`30b2be76e`, #861 step 1e; display only).
- **10:35 PM:** web: a recycled worker with a request still running leaves at once (`b709934b2`, lane `web-silent-worker-kills`; not a betting change).
- **10:39 PM:** web: the rail card's OURS for a flagged full-game total is the row's own live total (`fe46fb249`, this lane; display only).
- No betting change loaded.

### Open user decisions

- **Late games vanish from the Today rail at midnight** (new, measured above): (a) keep a still-live game of the previous Central day on the rail (display only), and separately (b) file NCAAB quotes by the Central tip day (a betting change, 12-08 window at the earliest).
- **Close lane `nhl-live-join-stl-alias` and todo #860** (asked 11-25 7:15 PM CST after R-H MET, unanswered).
- The next betting-change window is 12-08.

## Fix (a) design check: the page has nothing to show after midnight (9:40 AM CST 11-27; user "Yes fix it here")

- **Correction to the close.** I called (a) "a web change plus reload-web" on the belief that the Today rail's date filter dropped data the page already held. It does not hold it. The saved 12:43 AM reading (`C:\tmp\railmon\readings\20261127T064300Z`, both games still live, refresh-worker `index=2` until 06:50Z):
  - `/api/board/game-chips` (date = 11-27): 494 chips, 0 live, **0 NCAAB chips dated 11-26** (NFL keeps 11-25/11-26 finals, soccer keeps 5 earlier days).
  - `/api/intelligence/query` (combined board, 46.8 MB): **0 rows** naming Gonzaga; the 108 "Texas Tech" hits are football opponent histories.
  - `/api/board/live-rail`: 0 rows. The fast poll can only refresh rows for games the board already shows.
- **Why the board drops them:** `select_shortlist`'s lower date bound (todo `#779`, user 2026-11-10) drops a row whose game starts before midnight Central of the board's own date, because the `portfolio_commit` plan is built from the shortlist. Putting 11-26's games on the 11-27 board would be a betting change. Not proposed.
- **Where the data is:** the prior-date carryover (`[layer2-prior-date-carryover]`) kept 11-26 alive until both games ended. `LAYER2_CARRYOVER date=2026-11-26 decision=built` 06:09:14Z..07:06:12Z, every 6-7 min, `live_rows` 17-31, `chips_live` 2 (1 from 06:58Z, 0 at 07:06Z), then `skip reason=nothing_live_at_last_build` 07:11:31Z. `GAME_CHIPS_PUBLISHED date=2026-11-26 chips=377` every ~6.5 min to 07:03:25Z, alternating with 11-27.
- **So (a) is still web-only and display-only, but bigger than a page filter.** The Today rail has to read 11-26's own artifacts while its carryover runs:
  - (a1) scoreboard card: `/api/board/game-chips` for today also returns the prior date's LIVE chips from the worker's published 11-26 artifact (an artifact read, no inline build), and the page keeps a live prior-day chip on Today. The card comes back with its score and clock, count 0, no flags. Files: `syndicate/blueprints/intelligence.py` (unclaimed) and `syndicate/templates/intelligence.html` (claimed by `surface-consistency-oversight` and `ncaab-total-overprojection`).
  - (a2) card with rows and flags: also put the prior date's live L2-A rows on web's combined board read (`read_combined_intelligence_response`, `pipeline/intelligence_state.py`, claimed by `paper-alongside-live`, `web-silent-worker-kills`, `board-read-cold-share`). That read costs 5-18 s cold and is single-flighted; adding a date adds a shortlist read while the carryover runs.
- **Nothing built.** Both need files other lanes hold; put to the user 9:40 AM CST.
- Reader: `C:\tmp\railmon\carry_1127.sh` (copied to `scripts/rail_monitor/`).

## After-midnight rail fix loaded (10:30 AM CST 11-27; user "Yes fix it here", "Yes, lend it")

- **What:** a game from the evening before that is still live after midnight CT keeps a SCOREBOARD card on the Today rail. `/api/board/game-chips?carry_prior_live=1` lends the prior date's live chips from its published artifact (within 6 h of midnight, artifact <= 900 s old), and the rail keeps a live chip whose `carried_onto` is its date. `8455f25c0`, display only, not a betting change. No rows: the board's lower date bound (#779) still keeps them off today's board, on purpose.
- **Load:** ff + reload-web 16:29:54Z 11-27. All 3 predictions MET (commit, served rule, endpoint report `outside_window` 10.5 h); web log 0 errors; live page 173 cards, 0 console errors. deploys.md 2026-11-27 16:29:54Z.
- **Owed at the 11-27 close (R-M):** the first live reading, if a game is still live after midnight tonight. The probe asks with the same parameter now.

## Santander @ Levante not_in_resim (R17/R18 11-27): the soccer live lens was frozen, not a name miss

- **Flag:** the fleet-watcher, R17 (3:23 PM) and R18 (3:43 PM): `soccer Real Racing Club de Santander @ Levante` reason `not_in_resim`; its guesses were a cup match (`competition_not_modelled`) or a name-fold miss like Bodo / Kobenhavn. Neither.
- **Measured:** every reading R15-R18 (2:43-3:43 PM) read the soccer snapshot as `generated 2026-11-27T14:01:59-06:00`; R15-R17 listed Chelsea @ Nottingham Forest and Nacional @ CS Maritimo the same way (all three kicked off 20:00Z). live-odds-worker: `TICK_COMPLETE` soccer True at 20:02:15Z, then not again until 21:47:56Z; `LIVE_LENS_TICK_DIAG sport=soccer ok=False reason=low_headroom` 31 in 20Z, 32 in 21Z (5-22 an hour 15-19Z), headroom 210-230 MB against the 300 MB floor (`_soccer_live_lens_min_headroom_bytes`, live_lens_loop.py:534); container memory 80-143% of its 3,072 MB max in every 10 minutes 19:50-22:00Z. The autorun kept launching (58 in 19:55-22:05Z, 17 `RefreshLaneBusy`). The 22:05Z lens (generated 15:57:19 CST) held 1 game, Nacional @ Maritimo 83'.
- **The helper is right:** `find()` matches the rail's "Real Racing Club de Santander @ Levante" to "Racing Santander", "Racing de Santander" ("Levante UD") and "Real Racing Club", and still rejects a Real Sociedad @ Levante decoy (C:\tmp\railmon\fold_test_1127.py).
- **Helper change (monitor only):** `p29_orient.py` labels a miss against a snapshot over 900 s old `snapshot_stale` (detail: its age, "not a name miss") and puts `resim_age_s` on each sport's summary line; `dash_update.py` passes the reason through and adds `stale_snapshots` {sport: age_s, generated, games_in_snapshot} to every row; both page builders say "the live snapshot is stale". R18 replayed through it: Santander @ Levante -> `snapshot_stale` (101 min), `stale_snapshots` soccer 6,063 s / 6 games; ncaab, ncaaf, nhl, wncaab 0 s, nfl 241 s. A live run at 22:14Z: rc 0, every sport 30-100 s old.
- **Fleet findings (not fixed here; for the user):**
  - Soccer has NO lane-age ceiling in the live join (`_MAX_LANE_AGE_SECONDS_BY_SPORT`, live_gameline_join.py:792: basketball and football only). The 6 games already in the 20:01:59Z lens kept being priced: `LIVE_GAMELINE_JOIN sport=soccer` priceable 14-38 per build 20:08-21:35Z, `LIVE_PROJECTION_JOIN` edged_modelled 325-555, from a model up to ~95 min old.
  - Orders on it: 32 soccer orders submitted 20:02-21:48Z, all PAPER; 2 in play, both Bologna @ Venezia totals 1.5 at 20:22Z (kalshi and polymarket ladders, edge 32.14 pp, the lens 21 min old). 0 live-money soccer orders (ledger archive shard + keyvalue document).
  - The memory gate itself: the live-odds-worker ran over its cap for most of the afternoon. MLB 112 and WNBA 118 low-headroom skips on 11-27 too.
- **Readers:** `scripts/rail_monitor/soccer_stale_1127/` (gate counts, priced rows, orders, the R18 replay).

## Soccer lane-age ceiling built (#865, 11-27; user "Yes, build it here")

- **What:** `SYNDICATE_LIVE_GAMELINE_SOCCER_LANE_AGE` (absent = off = today; shadow; on) gives soccer live pricing a 600 s lane-age ceiling, and the soccer source stamps the lens time onto each match while the switch is not off (lane `soccer-live-lane-age-ceiling`, todo `#865`). Default off on main; queued for the 12-08 window.
- **Why soccer lanes had no time:** the poller writes `generated_at` at the top of the lens only; `soccer_live_gameline_index` read `game.get("generated_at")`, so `as_of` was None and `lane_age_max=None` on all 287 soccer LIVE_GAMELINE_JOIN lines 11-27. A ceiling alone would have refused every soccer row as untimed.
- **The ceiling, measured** (`soccer_lane_age_1127.sh`, fleet logs 11-23 12:05Z..11-27 22:34Z, 146 soccer builds with a match in play, age = build time minus the last soccer lens write): no gate skip since the write n 102, p50 45 s, p95 101 s, p99 137 s, max 195 s; a gate skip since it n 44, p50 488 s, p95 5,333 s, max 6,032 s. At 600 s: 20 builds refused (493 of 1,903 priceable rows), every one a stall, 0 fresh. The probe readings sample 11-21 (Saturday) held two readings at 501-581 s with 11 matches in the lens, and that day's logs have rotated, so a heavy Saturday's normal cadence is NOT measured: R-N.
- **Proof:** tests 34 / 34; 780 regression; A/B with the switch absent 8 of 8 byte-identical to the pre-change modules (aggregate and per-league lens, h2h / totals / spreads, 60 / 700 / 6,063 s); control `on`: 700 s and 6,063 s price 0 of 12, 60 s 12 of 12; control `shadow`: 12 of 12 at every age.
- **Owed:** R-N (Saturday re-measure after 11-28); the load-day yes; the after-load reading (`kit_after_up_soccer_lane_age.sh`).

## SOCCER_RUN_FAILED exit 1 (fleet-watcher, 11-27): the known Understat outage, #841

- **Ask:** refresh-worker logs `SOCCER_RUN_FAILED exit_code=1` for ~95 run stamps since 01:18Z 11-27, stderr with no Traceback; what exits 1, and which units are stale? (the fleet-watcher, on the user's "yes, send the soccer failures to the rail monitor").
- **What exits 1:** the run's `odds_refresh.json` `failureSummary` names it (the stderr file holds only the debug snapshots). In 20261127_200057: `soccer_bundesliga_history_current` and `soccer_bundesliga_players` rc 1, `UNDERSTAT_UNAVAILABLE ... status=200 content_type='text/html' ... 'Understat.com We will come back soon' (nothing written; the previous file is KEPT and is now stale)`. Every big-5 league (EPL, La Liga, Serie A, Ligue 1, Bundesliga) fails these two steps on every run.
- **Rate:** 1,157 of 1,157 soccer runs 11-20 06:23Z..11-27 22:46Z exited 1 (per day 142 / 155 / 169 / 152 / 138 / 150 / 144 / 107); 1,129 carry an Understat failure (reasons: non_json maintenance page 3,988, unreachable 166). The other 28 failed on the 11-26 DNS outage (artifacts / schedule / odds / props / history / live_state, 06:21-17:09Z) or single OddsAPI 502 / 429s on 11-20..11-24. 11-27: 107 of 107 failed, all through Understat.
- **Known and owned:** `#841` (Understat down since 11-03 2:54 PM CST). The fleet's `soccer_source/_understat_status.json`: state down, down_since 2026-11-18T19:22:04Z (the record's start), last_ok_at null, 9,926 probes, last 22:47Z 11-27. The naming guard is loaded (that is the named stderr_tail); the cooldown stays off by the user's decision; the alternative-source splice is queued for 12-08 (`#845`).
- **What is actually stale** (mtimes on the fleet, 22:5xZ 11-27): only the big-5 Understat files, `team_history/teams_2026.csv` ~645 h (10-31) and `players/players_2026.csv` ~637-639 h (11-01). Fresh: every league's recommendations (<= 0.3 h), odds / props (< 1 h), live state, and the non-Understat leagues' `history/matches_2026.csv` (5.6 h) and `players_2026.csv` (1.7-5.5 h). So the big-5 pregame sims price on team history frozen at 10-31, as `#841` says.
- **The Bundesliga 12-04 unit is not stale by a defect:** its runs at 06:25, 11:36 and 16:49Z ran `soccer_bundesliga_artifacts` rc 0 (16:49Z wrote `recommendations_2026-12-04.json`); the 20:56Z run had no artifacts step because a Bundesliga match was in play, which drops the step from the live phase by design (`#520`, `scripts/refresh_odds_sources.py:2696`). `wrote_since_launch=False` is that run's shape.
- **Not the lens freeze's cause:** the freeze was the live-odds-worker memory gate; this failing run's own snapshot read container memory 72.4% (2,193 MB headroom), and Understat fails at any memory level.
- **Lead (not chased):** MLS `history/matches_2026.csv` was last written 10-07, and the live sweep carries no MLS history step (only `soccer_mls_live_state` and `soccer_mls_artifacts`), so MLS playoff matches since 10-07 are not in its history.
- **Readers:** `scripts/rail_monitor/soccer_runs_1127/`.

## MLS history gap (user "check the MLS history gap", 11-27): no gap reaches the models

- **Corrects** the lead in "SOCCER_RUN_FAILED exit 1" above: `mls/history/matches_2026.csv` does stop in September, but nothing that prices MLS depends on it for recent matches. Hypotheses H1-H3 were written into the lane before the read (5:51 PM CST).
- **The file:** 402 rows, 2026-02-21..2026-09-27, every row with corners (written 10-07; a one-off backfill, `scripts/soccer_season_audit/backfill_mls_corner_history.py`). The sweep has no MLS history step on purpose: "MLS ratings are a live ASA fetch and need no step" (`scripts/refresh_odds_sources.py:2268`).
- **H1 CONFIRMED, ratings:** `build_soccer_artifacts._load_team_ratings` calls `fetch_asa_mls_team_history(today's year)` on every build (`/mls/teams/xgoals`, season aggregates) and never reads `history/` for MLS. ASA's 2026 game list, read 11-27: 520 games, all scored, the latest dated 11-25 UTC.
- **H3 FALSIFIED, playoffs are in the ratings:** the call passes `season_name` only, and ASA's default spans every stage: 30 teams, 34-36 games (16 at 35, 2 at 36); `stage_name=Regular Season` gives exactly 34 each; `stage_name=Playoffs` 18 teams with 1-2 (10 matches, 11-19..11-25 UTC).
- **H2 CONFIRMED, corners:** `corners_estimator.league_corner_rows` on the fleet's code: 402 history rows (last 09-27) + 118 `live_state` match-box rows (09-30..11-24) = 520 rows, 0 sharing (day, home, away). 520 is ASA's game count, so no match between the backfill's end and the live boxes' start is missing. (My own corner check over the boxes read 0 with corners: wrong key path; the estimator's count is the measurement.)
- **Not a gap, noted only:** the ratings fetch takes `date.today().year`; from 2027-01-01 it reads the 2027 season, which has no games until late February. MLS 2026 ends in December, so nothing priced is affected this year.
- **Readers:** `scripts/rail_monitor/soccer_runs_1127/mls_hist_gap_1127.py`, `mls_asa_lag_1127.py`.

## MLS ratings season rollover fixed (#866; user "Fix the ratings year rollover before January")

- **Defect:** `fetch_asa_mls_team_history(date.today().year)`. ASA season 2027 read 11-27: 0 teams, so a February 2027 build rates nobody and `_fill_promoted` puts every MLS team on PROMOTED_TEAM_RATING.
- **Fix:** the build date's season, and last season fills each team's first 34 games (games-weighted). Identical while every team has 34+ (all of 2026); last season is not fetched then.
- **Study** (`scripts/rail_monitor/mls_rollover/mls_rollover_study.py`; rules A season-to-date, B last season, C5/C10/C17 switch, D17/D34 window), pooled 2025+2026, log-lik vs A: 0 games -0.029 +- 0.120 (n 30, all carries equal); 1-4 D34 +0.304 +- 0.220 (n 122); 5-9 +0.030 (n 153); 10-16 +0.029 (n 214); 17-33 +0.011 +- 0.009 (n 501); all D34 +0.050 +- 0.030, D17 +0.045 +- 0.027, C10 +0.034 +- 0.031, B +0.020 +- 0.037; Brier A 0.6365, D34 0.6235. D34 is best in both seasons.
- **Proof:** 10 / 10 new tests; soccer artifact / rating / live-lens regression 76 passed (its one SyntaxWarning is from an unchanged file: the changed script and test compile clean with it as an error); real-pull A/B 3 of 3 2026 dates identical; 2027-02-27 old 0 teams, new 30.
