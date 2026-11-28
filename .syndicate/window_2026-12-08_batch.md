# 2026-12-08 betting-change window batch: the item list, each item's conditions, and the user's load yeses

Built 2026-11-27 by session 91b0c989 (lane `window-1208-batch`), started by session 898e5510.
The window is Tue 2026-12-08, 2:00-7:00 AM CST (08:00-13:00Z), per `.syndicate/betting_change_windows.md`.

- **Batch task:** `window-batch-load-1208`, firing 2026-12-08 2:15 AM CST (08:15Z).
- **Backup task:** `window-batch-load-1208-backup`, firing 3:45 AM CST (09:45Z). It runs the batch only if the batch
  never started, and it runs the same prompt, checked by sha256.
- **Shape:** one claimed ff to an exact `origin/main` SHA and ONE drained full down/up, modelled on the 11-24 batch
  (`nfl-level-refit-load-1120`, deploys.md 2026-11-24 08:30:10Z). Every item is lettered and droppable on its own.

**Nothing in this file is an instruction to the batch.** The batch's instructions are its prompt, which the user
reviewed; the prompt's sha256 is recorded in lane `window-1208-batch`. The batch reads this file only for the
`LOAD YES` / `LOAD NO` lines below.

## How the user's load yes is recorded

The batch loads an item ONLY if this file, on `origin/main` when the batch runs, holds a valid `LOAD YES` line under
that item's heading.

- **Line form.** Add ONE line under the item's `#### <letter>` heading in the "LOAD yes lines" section at the end of
  this file, in exactly this form:
  `- LOAD YES <YYYY-MM-DD> <h:mm AM|PM> CST, session <first 8 hex of the session where the user answered>, to "<the question, verbatim>": "<the user's words, verbatim>"`
- **Recorded by another session.** If a session other than the one where the user answered writes the line, append
  `, relayed word for word by session <8 hex> from the user's own message`.
- **When it counts.** It counts only if ALL of these hold:
  - it is dated 2026-12-07 00:00 CST or later, and before the batch starts;
  - it quotes the user's own words in the named session. A relayed claim, or a button label the recording session
    offered that the user did not choose, never counts (learnings 2026-10-20 FORBIDDEN);
  - the question it answers names THIS item (its letter or todo number) and its load in the 12-08 window;
  - for an item with a gating record (H: the 11-28 hold-out; I: the timeouts reading; F: the `FIT FIX ON MAIN` line;
    L: the 12-07 grade), it is dated after that record.
- **Cancelling.** A later `- LOAD NO ...` or `- HOLD ...` line in the same form cancels a yes.
- **Two exceptions** (STANDING load instructions; they need no 12-07 line):
  - D: it loads exactly when C loads.
  - M: it rides the batch's down/up whenever at least one betting item loads.
  - ANSWERED at install: the user answered "Yes, install it" (2026-11-27 ~4:29 PM CST, session 91b0c989) to "Install
    it as listed, or install with D and M also needing a 12-07 yes?". So D and M count on their standing words:
    D "load (b) in the next window" (11-26 ~10:12 PM CST); M "Next scheduled restart" (11-25 ~10:10 AM CST).
    A `- LOAD NO` or `- HOLD` line under `#### D` or `#### M`, dated after that answer, cancels either one.
- **Additions only.** Never edit or remove another session's line. Commit through a temp index on a freshly fetched
  `origin/main`.

## The items (load order A..M; each droppable alone unless its block says otherwise)

Every key below reads ABSENT on all three roles today, except J's and L's shadow lines. Every kit's dummy-file
self-test PASSED 2026-11-27 21:01-21:09Z, the real env file stayed byte-identical (sha16 `290f86bd5493eb45`). The
whole-batch rehearsal also PASSED: all 13 applies in this order on one dummy file, with no key twice, and the
earliest backup restored it byte for byte (`C:\tmp\w1208_batch\batch_dummy_rehearsal.sh`, output
`C:\tmp\w1208_batch\selftests_1127.out`).

### A — #850 J's narrowed checkout-HEAD hold (head rule)
- Line: `REFRESH_WORKER__SYNDICATE_BOARD_PROCESS_PARENT_RECYCLE_HEAD_RULE=loaded`.
  - Code is `8e2149f0f`, and the fleet carries it. Absent means `any`, today's rule (`pipeline/board_build_process.py:674-678`).
  - BETTING CHANGE.
- Lane `board-split-memory-guard` (session 644b05ff); findings_2026-11-18_board_split_memory_guard.md s22-s25.
- Queue yes: "Queue it for 12-08", typed ~10 AM CST 11-27 in session 644b05ff. LOAD yes OWED.
- Condition: CHANGE J (`..._PARENT_RECYCLE_MB=1500`) still reads 1500 in refresh-worker's environ at the baseline.
  Without it, the line is inert.
- Kit: `C:\tmp\w1208_headrule\kit_env_headrule.sh` (`check | apply | restore <b> | after_up <utc>`). The load check is
  `after_up` printing `ARMED_HEAD_RULE=loaded`. Then P-HR1..P-HR4 run on the first two qualifying mornings.
- UPDATE 2026-11-28 ~10:30 AM CST (session 91b0c989): a default-off follow-up is on main as `0cc34ecd0` (records
  `254d9f74e`, lane `board-split-memory-guard`, the user's "Yes, build it" in session 644b05ff). The `loaded` rule now
  exempts `scripts/rail_monitor/`, tooling no role reads; a loaded `.py` there still holds. On 11-28 those files were
  19 of the 22 the rule would have held on (findings s26-s27).
  - Checked here: `head_change_holds` runs only when the rule reads `loaded` (`pipeline/board_build_process.py:904`),
    and A's key is absent today, so the batch's step 3 classes it (a). A's line, kit (sha16 `08f90d8cf1bc5d24`), load
    check and REQUIRED `8e2149f0f` are unchanged; the prompt needs no edit.
  - If TARGET carries `0cc34ecd0`, A loads WITH the exemption; if TARGET stops before it, A loads with the stricter
    rule. A's tests now include a guard that fails if role code names `scripts/rail_monitor` as a path; a failure
    drops A in step 2.

### B — #850 host-headroom switch
- Line: `REFRESH_WORKER__SYNDICATE_BOARD_PROCESS_HOST_OVERDRAFT_MB=1024`; the reserve stays at its default 2048.
  - Code is `9a9a0b207`, absent = off. BETTING CHANGE.
- Same lane and session as A; findings s18, s21, s25.
- Queue yes: "Queue it too", typed ~12:15 PM CST 11-27 in session 644b05ff. LOAD yes OWED.
- A and B load in the same down/up by plan, and either loads alone.
- Kit: `C:\tmp\w1208_hosthead\kit_env_hosthead.sh` (`check | apply [n] | restore <b>`).
- Load check: refresh-worker.log since the up shows the board child's
  `BOARD_PROCESS_HOST_HEADROOM installed ... overdraft_mb=1024 reserve_mb=2048` and `host_overdraft_mb=1024
  host_reserve_mb=2048` on the switches line.
- P-H1..P-H5 follow (P-H4 / P-H5 = an OOM kill or a board child rc -9 means revert).

### C — #861 one model number per Layer 2 card
- Line: GLOBAL `SYNDICATE_LAYER2_ONE_MODEL_NUMBER=on`.
  - Code is `d25f49964`, absent = off.
  - BETTING CHANGE, classed conservatively: the evaluation ledger's `model_probability` switches basis.
- Lane `surface-consistency-oversight` (session d5aa3287); findings_2026-11-23_surface_consistency.md "QUEUED FOR THE
  12-08 WINDOW".
- Queue yes: "Queue for 12-08", ~11:25 AM CST 11-24 in session d5aa3287. LOAD yes OWED.
- Kit: `C:\tmp\w1208_onenum\kit_env_onenum.sh`.
- Reader: `py -3 C:\tmp\w1208_onenum\read_after_load.py`, run on the first board build after the up (0 MET / 1
  violated / 2 blind / 3 not loaded).

### D — #847 (b) calibrated Sim / model EV display (rides with C)
- Line: GLOBAL `SYNDICATE_CELL_CALIBRATION_DISPLAY=on`.
  - Code is `75a787964`, absent = off. NOT a betting change.
- Lane `cell-calibration-847-b-load`; findings_2026-11-18_cell_calibration.md s6.
- Standing yes: "load (b) in the next window", typed ~10:12 PM CST 11-26 in session 77184c63.
- Coupled: "Hold (b) with it", ~10:19 AM CST 11-27. D loads ONLY if C loads, and drops if C drops.
- Kit: `C:\tmp\w1208_cellcal_b\kit_env_b.sh`.
- Reader: `py -3 C:\tmp\w1208_cellcal_b\read_after_load_b.py`, on the first board build.
- Needs a non-expired `reports/model_scorecard/model_cell_calibration.json` (72 h expiry; the kit prints `table_mtime`).

### E — #847 (c) rank/stake below the 0.5 floor
- Line: GLOBAL `SYNDICATE_CELL_CALIBRATION_RANK_STAKE=on`. BETTING CHANGE.
  - Code `75a787964`, plus the fixes `a15d94bbc` + `d381a806a` (on main, NOT yet on the fleet). The batch's ff must
    reach `d381a806a`.
- Queue yes: "Queue both", ~10:19 AM CST 11-27 in session e32fef1a. LOAD yes OWED.
- Kit: `C:\tmp\w1208_cellcal_cd\kit_env_cd.sh apply c`.
- Reader, on the first board build: `py -3 C:\tmp\w1208_cellcal_cd\read_after_load_cd.py --use c --fixes yes
  --ncaaf-835 <on if H loaded else off> --d-loaded <yes if F loaded else no>`.

### F — #847 (d) per-cell live probability
- Line: GLOBAL `SYNDICATE_CELL_CALIBRATION_LIVE_PROB=on`. BETTING CHANGE.
  - Code is `8acee817d` + `a15d94bbc` + `d381a806a`.
- Same queue yes as E. The user then said "Yes, both" (~2:25 PM CST 11-27, relayed by session e32fef1a), so (d) loads
  12-08 ONLY IF the FIT FIX (findings s8.3 option (i), lane `cell-calibration-847d-fit-fix`) is on main and tested by
  then. Otherwise it waits for 12-22.
- **Mechanical condition.** Lane `cell-calibration-847d-fit-fix` on `origin/main` carries a dated line beginning
  `FIT FIX ON MAIN <sha>` that names its test files. The batch checks that `<sha>` is an ancestor of `origin/main`, and
  runs those test files at Idle priority in its worktree, all passing. Today the fit fix is uncommitted.
- OPEN, the user's call at the load yes: the #835 skip covers NCAAF live TOTALS only. (d) still moves
  `ncaaf|spreads|full|live` on top of H's damping and I's end game, if they load too.
- Kit: `kit_env_cd.sh apply d`.
- Reader, DURING the first live slate (it reads the book grids):
  `read_after_load_cd.py --use d --fixes yes --ncaaf-835 <on|off>`.
- Live money: in-play live orders come from the Kalshi in-game module and do not size through `portfolio_commit`. So
  today (d) reaches rank, paper and decision records, not live in-play money.
- UPDATE 2026-11-27 ~4:50 PM CST (session 91b0c989): the fit fix is ON MAIN.
  - Commits `86fd3e943` + `d3ec5b72e`, pushed 4:37 PM CST on the user's "Yes, push it" (relayed by session 898e5510).
    Both read as ancestors of `origin/main` `071dbf20a`. New test file: `tests/test_cell_calibration_847d_fit.py`.
  - The batch's F condition is still NOT met: lane `cell-calibration-847d-fit-fix` has no `FIT FIX ON MAIN <sha>` line
    yet. Its owner, session 77184c63, was sent the line's form ~4:40 PM CST.
  - The ff must reach `d3ec5b72e` or later; any TIP from now on does.
  - The reader now requires `--fit-fix yes` (sha16 `e2c5f370e16d1d27`). The installed prompt passes it.
  - Read-only fact (session 898e5510): `SYNDICATE_PRICING_CALIBRATION` is on in all three roles, but the only pricing
    profile is mlb_source's (2026-10-12). So the pricing seam recalibrates no in-season (d) cell.
- UPDATE 2026-11-27 ~5:00 PM CST (session 91b0c989): F's mechanical condition is now MET on `origin/main`.
  - Lane `cell-calibration-847d-fit-fix` has a line beginning `FIT FIX ON MAIN d3ec5b72ed4fb6bbe5c17983fce2a7f06685d2c1`
    (dated 4:45 PM CST, session 77184c63, ledger `eb40bb5f9`). `d3ec5b72e` reads as an ancestor of `origin/main`.
  - Its seven test files are all on main, and the batch reruns them at Idle: `test_cell_calibration_847d_fit`,
    `test_daily_optimizer`, `test_model_scorecard`, `test_opportunity_population_ledger`,
    `test_live_totals_width_fit_source`, `test_layer2_board`, `test_live_gameline_join`. There are no reader_args.
  - F still needs the user's own LOAD YES under `#### F`, dated 12-07 or later.

### G — #863 NBA pregame reuse age limit
- Line: GLOBAL `SYNDICATE_NBA_PREGAME_REUSE_MAX_AGE_SECONDS=4500`. BETTING CHANGE.
  - Code is `f69f7b6c8` + `cc516f4b0`, absent = off. Both workers' odds sweeps run the NBA step.
- Lane `surface-consistency-oversight` (session d5aa3287).
- Queue yes: "Age limit, off", 11-27 in session d5aa3287. The ledger has ~11 AM and ~1 PM CST. LOAD yes OWED.
- Kit: `C:\tmp\w1208_nba863\kit_env_nba863.sh`.
- Reader: `py -3 C:\tmp\w1208_nba863\read_after_load.py <day>`, on an NBA game day before the first tip and >= 110 min
  after a scheduled pull. It is OWED after the load, not read at it. Cost: about +75k OddsAPI credits a month, an
  upper bound.

### H — NCAAF live totals pair, #835 + #852 (three lines, always together)
- Lines, GLOBAL:
  - `SYNDICATE_NCAAF_LIVE_TOTAL_CALIBRATION=on` and `SYNDICATE_LIVE_TOTALS_PROB_SCALE_NCAAF=1` (#835, `f29c53e91`,
    `56e132d40`);
  - `SYNDICATE_NCAAF_LIVE_BLOWOUT_DAMPING=on` (#852, `44184da1e`).
  - BETTING CHANGE.
- Keep #835's key GLOBAL: (c)/(d)'s NCAAF-totals skip (`cell_calibration.py` `ncaaf_live_total_owned_by_835`) reads
  it in whichever role runs them.
- Lanes `ncaaf-live-total-dispersion` and `ncaaf-live-endgame-surplus` (session 617b553b).
- Queue yes: "Queue for 12-08 (Recommended)", ~9:40 AM CST 11-20 in session 617b553b. LOAD yes OWED in session
  617b553b's chat.
- **Condition:** the 11-28 hold-out read by task `engine-ncaaf-checks-1130` (Mon 11-30) must be recorded. That means:
  - a `## Hold-out check, 2026-11-28 slate` section in both `.syndicate/findings_2026-11-19_ncaaf_live_total_dispersion.md`
    and `.syndicate/findings_2026-11-19_ncaaf_live_endgame_surplus.md`;
  - #835 items 1 AND 2 read PASS there. Its own no-go rule: items 1 or 2 FAIL on 11-21 or 11-28 means #835 does not go;
  - #852's section reads `CHECK VALID`.
- On 11-21 it was mixed: #835 items 1-4 PASS and item 5 FAIL on one bucket; #852 failed its 17+ mean F-c. The user
  weighs that at the yes.
- Kit: `C:\tmp\w1208_ncaaf\kit_env_ncaaf.sh apply pair`.
- No NCAAF game falls between 12-08 and Army-Navy 12-12. So at the load only the env is read. The refresh-worker line
  `NCAAF_LIVE_BLOWOUT_DAMPING on strength=1.0 lead_threshold=17.0 lead_span=14.0` (21.0 / 7.0 with I) and the tick's
  `total_calibration.anchored > 0` are OWED at the next live NCAAF game.

### I — #859 margin-aware end game (only on top of H)
- Lines, GLOBAL: `SYNDICATE_NCAAF_LIVE_BLOWOUT_DAMPING_THRESHOLD=21`, `SYNDICATE_NCAAF_LIVE_BLOWOUT_DAMPING_SPAN=7`,
  `SYNDICATE_NCAAF_LIVE_ENDGAME=on`.
  - Code is `b2ff241ae`. BETTING CHANGE.
- Lane `ncaaf-margin-aware-endgame` (session 617b553b).
- Queue yes: "queue the end-game load set for the 12-08 window", ~6:10 PM CST 11-21. LOAD yes OWED, separately from H.
- **Conditions:**
  - H loads in this batch. The kit refuses the end game without the pair.
  - The real-timeouts hold-out is MET 11-21.
  - A dated ledger reading in lane `ncaaf-margin-aware-endgame` or todo #859 shows a live NCAAF scoreboard row carrying
    `homeTimeouts`/`awayTimeouts`. It is NOT recorded today.
- Kit: `kit_env_ncaaf.sh apply endgame`.
- OWED at the next live game: `NCAAF_LIVE_ENDGAME on concede_deficit=25 ...` and live lanes with
  `endgame.timeouts_fed=true`.
- UPDATE 2026-11-28 (session 91b0c989): the timeouts reading is RECORDED, so I's third condition is met as written.
  - Todo #859 carries `TIMEOUTS READING 2026-11-27 10:08 PM CST: 1227 of 1227 live NCAAF reads carry
    homeTimeouts/awayTimeouts as ints 0..3` (7 games), ledger `bbcb51d21`, by session 309b272a. Details:
    `.syndicate/findings_2026-11-27_ncaaf_live_timeouts_reading.md`. The fleet's own 296 live `/ncaaf/api/cards` rows
    carry both keys too.
  - **DEFECT, read before the yes.** ESPN's college scoreboard does NOT reset timeouts at halftime. It shows 3 minus
    every timeout used in the game, floored at 0; college rules give each team a fresh 3 for the second half.
    - At the break, in 3 of 3 games watched, the halftime value carried into the second half.
    - Against ESPN play-by-play (6 games, 1164 reads): the carry-over reading has 0 mismatches, the per-half reading
      has 403.
    - In Q4, 541 of 606 team counts read low; in 170 a team showed 0 while it still had timeouts.
  - Why it bites: `ncaaf/live_resim.py:1004-1007` passes the feed's values in every period, with no halftime check.
    smartsim2 reads them only under `end_of_half_clock` (`smartsim2/game_simulator.py:175`), which
    `SYNDICATE_NCAAF_LIVE_ENDGAME=on` turns on. So loaded as built, I runs the second half on too few timeouts. The
    11-21 hold-out never tested this input; whether its CFBD timeouts also carry over is unchecked.
  - A fix to the second-half value changes nothing while the end-game key is absent, so it can land on main before
    12-08 without being a betting change. The installed prompt requires only `b2ff241ae` for I, NOT a fix: a 12-07
    yes would load I as built unless the prompt is edited. Load as built, wait for a fix, or move to 12-22 is the
    user's call.
- **ANSWERED 2026-11-28 ~9:58 AM CST:** the user answered "Fix it first" (session 91b0c989) to "Item I's
  second-half timeouts read low. Fix it before 12-08, or move I to 12-22?".
  - The task prompt now DROPS I unless todo `#859` on `origin/main` carries a dated `TIMEOUTS FIX ON MAIN <sha>` line
    that names its tests, with `<sha>` an ancestor of `origin/main` and those tests passing in the batch's step 2.
  - A 12-07 LOAD YES for I must be dated after that line. Without the fix, I waits for 12-22, and H still loads at
    17 / 14.
  - The fix is being built by session 309b272a, the session that took the timeouts reading, briefed ~10:00 AM CST
    11-28. `live_resim.py` is held by lane `live-player-exit-gate`, so its loan goes to the user with the push question.
  - The new prompt hashes are in lane `window-1208-batch`.
- NOT in the batch: `SYNDICATE_NCAAF_LIVE_MARGIN_ANCHOR` (`cf12ae61f`). The user has made no load decision and it has
  no kit line.

### J — Polymarket stale cancel, shadow -> on
- Line: `LIVE_ODDS_WORKER__SYNDICATE_POLYMARKET_STALE_CANCEL=on`, promoted IN PLACE from the 11-24 shadow line.
  - Code is `7bc613347`. BETTING CHANGE (a live venue write).
- Lane `polymarket-stale-cancel` (session 69d80317); findings_2026-11-21_polymarket_stale_cancel.md.
- Queue yes: "yes, add the Polymarket stale cancel to the 12-08 queue" (11-21, relayed by the fleet-watcher). LOAD yes
  OWED, typed in session 69d80317's chat.
- **Read before the yes:**
  - The +3 d shadow reading (11-27) was quiet: 0 WOULD_CANCEL, and 0 of 26 orders untouched >= 15 min.
  - So S2 (the client id and slug we send match the venue's) and S3 (no would-cancel order later fills) are UNTESTED,
    with 0 samples.
  - The first live cancel is the probe.
- Kill rules after the load: P1-P5 (the first `CANCEL_STALE` must return `CANCEL_SENT`, and the order must read
  cancelled within 2 passes; any exception to taker / >= 900 s / drift >= 0.01 means kill).
- Kit: `C:\tmp\w1208_pmstale\kit_env_pmstale.sh apply on`. Revert: remove that one line (absent = off), then a
  drained down/up.

### K — #845 soccer Understat-outage splice
- Line: GLOBAL `SYNDICATE_SOCCER_UNDERSTAT_SPLICE=1`.
  - Code is `1ef73b910`, absent = off. BETTING CHANGE (every big-5 rating).
- Owner: todo #845; lane `understat-fetch-failures` CLOSED 11-18.
- Queue yes: "queue the splice for the 12-08 window", 11-18 4:57 PM CST. LOAD yes OWED. Show the user the real-gap
  result first: on 69 outage matches at one round the splice is WORSE than frozen, +0.0084 [+0.0015, +0.0185]; the
  1,818-match backtest favours it at 4+ rounds.
- The SA-arm re-read through the 12-05/06 weekend is owed, and no task holds it.
- **Condition:** `bash /mnt/c/tmp/w1208_batch/understat_status.sh` reads `understat_state=down` when the batch runs.
  2026-11-27 21:07Z: `down` since 2026-11-18T19:22:04Z, `last_ok_at=None`.
- Kit: `C:\tmp\w1208_batch\kit_env_845.sh`, built 11-27 by this lane; self-test 13/13 PASS.
- Load check: `SOCCER_UNDERSTAT_SPLICE league=<big5> ... spliced_matches=N` with N > 0 in a worker log, at the next
  soccer artifact build. OWED if no build runs in the window.

### L — #856 hold-value exits, shadow -> on
- Line: `LIVE_ODDS_WORKER__SYNDICATE_EXIT_HOLD_VALUE=on`, promoted IN PLACE from the 11-24 shadow line.
  - Code is `ace2020d3`. BETTING CHANGE.
- Lane `hold-value-exits` (owner session ffd41dea, archived); findings_2026-11-20_hold_value_exits.md.
- No queue yes for `on` exists. It is a candidate that loads only on BOTH of:
  - a SUPPORT verdict from the pre-registered 12-07 grade (task `hold-value-shadow-grade-1207`, 12:30 PM CST; backup
    4:30 PM). The batch requires lane `hold-value-exits` to carry a `12-07 GRADE [...]: SUPPORT (STRONG)` or
    `SUPPORT (WEAK: CI spans 0)` line;
  - a LOAD YES here.
- Kit: `C:\tmp\w1208_batch\kit_env_856on.sh`, built 11-27 by this lane. It promotes in place, never appends, and
  refuses anything else (rc 5). Self-test 15/15 PASS.
- Load check: the first `EXIT_TICK status=ok` after the up carries `hold_value={'mode': 'on'`, and 0 `EXIT_TICK_FAILED`.
- P1-P6 (findings s5) are read over 12-08..12-21.
- Revert: edit that one line back to `=shadow`, then a drained down/up. Never restore L's own backup after later
  kits applied: it lacks M's line.

### M — #857 web recycle limit (NOT a betting change)
- Line: `WEB__SYNDICATE_WEB_WORKER_ANON_LIMIT_MB=1500` (absent = 650, `gunicorn.conf.py:114`).
- Lane `web-recycle-anon-limit`.
- Standing yes: "Yes, after #853" (11-20), then "Next scheduled restart" (~10:10 AM CST 11-25, rail monitor's chat).
  It rides the first drained full down/up, and none has happened since 11-25. The 11-26 17:10Z reboot was not drained
  and carried no key.
- Kit: `C:\tmp\w857\kit_env_857.sh`. Load check: `kit_after_up_857.sh <up utc>`. P1-P9 are read the first evening,
  5-11 PM CST.

### N — #865 soccer live lane-age ceiling, SHADOW only (NOT a betting change)
- **Added 2026-11-27 ~6:50 PM CST, after install.** The load order is now A..N. The task prompt was edited; its new
  hash is in lane `window-1208-batch`.
- Line: GLOBAL `SYNDICATE_LIVE_GAMELINE_SOCCER_LANE_AGE=shadow`.
  - Code is `fabdd54f7`, absent = off = today. Shadow stamps the soccer lens time on each live lane and counts what a
    600 s ceiling would refuse (`lane_age_would_refuse` on `LIVE_GAMELINE_JOIN`). It refuses nothing.
  - `on` refuses stale soccer lanes, is a BETTING CHANGE, and is NOT approved. The code reads any other set value as
    `on`, so the batch runs the kit exactly as `apply shadow`.
- Lane `soccer-live-lane-age-ceiling` (rail monitor, session d58574cb); todo #865.
- Add yes: the user answered "yes, add #865 to the batch as shadow" (~6:10 PM CST 11-27, session 86352bc9, the
  fleet-watcher) to "#865 soccer age limit: add it to the 12-08 batch as 'on' or 'shadow', or leave it out?". Session
  91b0c989 read those words in that session's transcript as the user's own message. It adds N; it is NOT a load yes.
- LOAD yes OWED: a 12-07 LOAD YES under `#### N`, as for the betting items. Whether N should instead ride on standing
  words, as D and M do, was put to the user 11-27 in session 91b0c989. Until a recorded answer changes the task, N
  needs the 12-07 line.
- **ANSWERED 2026-11-27 ~8:35 PM CST:** the user answered "Ride like M" (session 91b0c989) to "How should item N
  (#865, shadow) get its load yes?". So N is STANDING, like M, and the 12-07 line above is NOT needed. A `- LOAD NO` or
  `- HOLD` line under `#### N`, dated after 2026-11-27 8:35 PM CST, cancels it. N still rides only on a betting item's
  down/up, in shadow only.
- Not a betting change, checked by session 91b0c989 in the code on `origin/main`:
  - in the join's row loop, the soccer lane verdict refuses a row only when the mode is `on`;
  - otherwise the stamped time is read only by the shadow tally, the display-only block, `quote_behind_score_verdict`
    (ncaab/wncaab only), the ledger record (not one of `_moved`'s dedupe fields) and `engine_experts` (paper-only);
  - so it gets no register row.
- Rides only on a betting item's down/up, like M, and never causes one.
- Kit: `C:\tmp\w1208_soccer_lane_age\kit_env_soccer_lane_age.sh` (sha16 `eb2a77214f756828`), built by the rail
  monitor. Self-test PASS 11-27: the real env was untouched, and the key reads ABSENT on all three roles. The
  whole-batch rehearsal A..N also PASSED (`C:\tmp\w1208_batch\batch_dummy_rehearsal_a_to_n.sh`, output
  `rehearsal_a_to_n_1127.out`).
- Load check: `kit_after_up_soccer_lane_age.sh <up utc>` (sha16 `21189172f32096cd`). Soccer join lines with a match in
  play carry a numeric `lane_age_max`, and shadow refuses none. With no soccer in play in the window, it is OWED at
  the first match.
- Revert: remove the one line (absent = off), then a drained down/up.

## Overlaps: what loading together confounds, and which readers still tell the changes apart

- **One count restart.** Every betting item restarts the scale-up gate's count once, together.
- **(d) and the NCAAF pair (F vs H/I).** They touch the same NCAAF live rows.
  - TOTALS: with #835 on, (c) and (d) skip `ncaaf|totals*|full|live` in code. That needs the key GLOBAL.
  - SPREADS: not skipped. (d) moves them on top of #852/#859.
  - The cd reader cannot separate the two unless `--ncaaf-835` is stated correctly. The pair's own instrument is
    `total_calibration.anchored` and `prob_scale`.
- **C, D, E, F on cards.** Each changes a different field, so each reader stays clean:
  - #861: `model_probability_basis=model_edge`;
  - (b): `cal_cell`/`cal_k`, with Win% left raw;
  - (c): `optimizer_factor` in `ranked_all`;
  - (d): `live_cell_calibration` on the grids' `live_gameline` rows.
  - With (c) and (d) both on, fix 1 stops (c)'s k on (d)-stamped rows, and the cards cannot show which rows were
    stamped. Only the rails are judged there.
- **G vs E.** #863 changes which NBA rows exist and are Suggested, so an NBA slice of (c)'s rank/stake reading is
  confounded. #863's own reader (snapshot age, stale share) is separable.
- **A vs B.** Same role. The head rule acts 3-6 AM CST and the host headroom 5-10 PM CST. A morning parent recycle
  frees host memory, so read P-H1..P-H5 with that day's recycle (yes/no) beside them. P-H1 is attributable to B
  only on no-recycle days.
- **M vs A/B/G.** #857's P4 (sum of fleet RSS) overlaps the #850 memory readings and #863's extra NBA runs. P3 (web
  workers only) stays separable.
- **J vs L vs F/G (live-odds-worker).**
  - J's P5 (re-place after a cancel) is confounded by any change in entries from F or G.
  - L's P1/P5 (take-profit sales, entries) are confounded likewise. Read them per cell, or with F/G's days excluded.
  - J's cancel counts (P1-P4) and L's `hold_value` rows are separable.
- **K.** Soccer ratings only; no row collision found.
- **N vs K.** Both are soccer. K changes the big-5 ratings. N in shadow prices nothing, and its counters (`lane_age_max`,
  `lane_age_would_refuse`) are their own fields on the soccer join line.

## Not in the batch (no load yes, no kit line, or already loaded)

- `SYNDICATE_NCAAF_LIVE_MARGIN_ANCHOR` (#859 anchor, `cf12ae61f`): no load decision. The anchored spreads k
  `d8d0af0b7` is HELD by the user ("Yes, hold it").
- #816 spread-only: verdict flip T3 11-24, "NOT loaded, user decision owed". It has no switch (a code constant).
- #836 end-of-game freshness `on`: no queue yes, and no outcome grade.
- The staked-probability guard `..._STAKED_PROBABILITY_UNFITTED=market`: no queue yes.
- #842, #844, #834, the Central soccer shard, #861 step 1c: already loaded (11-24 / 11-25).
- The NCAAB Central-day quote shard (rail monitor 11-26): a candidate, with no lane and no decision.

## LOAD yes lines

(Additions only, under each item's letter, in the form above. The batch reads them from `origin/main`.)

#### A
#### B
#### C
#### D
#### E
#### F
#### G
#### H
#### I
#### J
#### K
#### L
#### M
#### N
