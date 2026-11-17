# Layer 2 Games Rail — standing monitor AND improvement hunt, 2026-11-17 (lane `layer2-rail-monitor`)

Day 3 of the monitor.
- **User 11-17 ~10:04 AM CST: "Yes, from noon"**, answering "Monitor Tuesday 11-17 with the same
  method?".
- Then, ~10:10 AM CST: **"ensure not only are we monitoring but we should ALSO be looking for any and
  all optimizations or improvements that we can make"**.

So from today every reading also hunts for improvements:
- Each candidate gets evidence with a denominator and an owner.
- An unowned candidate gets its own lane (hypothesis first, an off != on test, landed on main).
- Any fleet load stays the user's call.

Method as on 11-15 / 11-16:
- Probe `scripts/layer2_rail_monitor_probe.py`; runner `scripts/layer2_rail_monitor_run.mjs`; grader
  `scripts/layer2_rail_flag_grade.py`.
- Wrappers `C:\tmp\railmon\grade1116.py` (pre-registered splits) and `C:\tmp\railmon\grade_window.py`
  (bands).
- Times are Central (CST) unless marked Z.

## Two-day evidence base (11-15 + 11-16), read before any 11-17 game

Source: `C:\tmp\railmon\grade_window.py` (read-only).
- Flags graded at first sighting against final chips; game-clustered bootstrap, 90% interval on
  (hit − book fair).
- 11-15: 491 flags / 63 games, using chips from the 11-15 10:24 PM reading (17 flags not final).
  11-16: 256 flags / 35 games.
- Output `C:\tmp\railmon\gw_1115.json` and `gw_1116.json`.

| bucket | 11-15 W-L (hit vs fair) | 11-16 W-L (hit vs fair) | two days |
|---|---|---|---|
| ALL | 256-233 (52.4% vs 47.5%), CI [+0.4, +9.1] | 128-128 (50.0% vs 47.6%) | 384-361 |
| book fair < 0.20 | 3-17 (15.0% vs 11.9%), Brier model 0.137 / book 0.115 | **0-9** (0% vs 11.2%), Brier 0.079 / 0.014 | **3-26** |
| book fair 0.20-0.40 | 11-25 (30.6% vs 29.9%) | 7-17 (29.2% vs 28.8%) | 18-42: hit ≈ fair, no edge |
| book fair 0.40-0.60 | **233-188 (55.3% vs 50.0%), CI [+0.6, +10.4]** | 108-100 (51.9% vs 49.9%) | 341-288 |
| book fair 0.60-0.80 | 6-2 | **12-2** (85.7% vs 65.7%) | 18-4 |
| NBA full-game spreads | **3-19** (13.6% vs 30.3%), CI [−28.1, −0.1] | 10-17 (37.0% vs 40.2%) | **13-36** |
| NBA segment spreads | 22-17 | 17-8 | 39-25 |
| NBA segment totals | 31-27 | 16-8 | 47-35 |
| NCAAB full-game spreads | 30-19 (61.2% vs 49.8%) | 20-9 (69.0% vs 49.7%), CI [+3.5, +34.0] | **50-28** |
| NCAAB full-game totals | 54-59 | 26-42 | 80-101 |
| NCAAB totals UNDER side | 59-40 | **24-53** | 83-93 |
| NCAAB totals OVER side | **35-56** | 12-4 | 47-60 |

**Reading:**
1. **A favourite-longshot pattern in the flags.** Where the book prices the flagged side under 40%,
   the flags hit at or below the book's own number (21-68 combined). The model claims far more (e.g.
   27% vs the book's 3.8% on POR @ MIN u199.5), and its Brier is worse than the book's on both days.
   The flags' value sits in fair 0.40-0.80.
2. ~~NCAAB totals direction flips by night.~~ **WITHDRAWN ~11:00 AM.** The 11-15 rows were mostly
   pre-#816 raw-model flags, so they do not measure the level. The owner's night-clustered re-grade
   has five straight under nights 11-11..11-15, then the over night 11-16 (see I-7). The level stays
   under test (T4).
3. **NBA full-game spread flags lose** (13-36), most on alternate spreads, while NBA segment flags win.
4. **NCAAB full-game spreads** are the steadiest family (50-28).

**In-sample caveat:** these are the same two days that suggested the cuts. Every cut below is
**pre-registered for 11-17 out of sample** and changes nothing until it holds.

## PRE-REGISTERED for 11-17 (written ~10:25 AM CST, before any 11-17 game)

Graded tonight at first sighting, game-clustered, same method:

- **T1 (fair band):**
  - Flags with book fair < 0.40 hit at most their mean fair + 2 pp, and their Brier is worse than the
    book's.
  - Flags with fair >= 0.40 hit above their mean fair.
  - A "flag only when book fair >= 0.40" rule raises the day's hit-minus-fair.
  - Falsified if the < 0.40 flags beat their fair by more than 2 pp on >= 10 games.
- **T2:** NBA full-game spread flags hit below their mean fair. Falsified if they hit >= fair on
  >= 5 games.
- **T3:** NCAAB full-game spread flags hit above their mean fair. Falsified if they hit <= fair on
  >= 8 games.
- **T4:** NCAAB full-game total flags (calibrated) have no edge: |hit − fair| < 5 pp, OR their sign
  matches the night's scoring (all-totals over share). Reported, not a gate.

**CORRECTION ~10:50 AM CST, before any 11-17 game (raised by peer 0f519972 / local_208683f1):**
- T1's clause "a 'flag only when book fair >= 0.40' rule raises the day's hit-minus-fair" is
  **WITHDRAWN as a candidate.**
  - It is a band exclusion: it withholds every line in a fair band.
  - The user's standing rule forbids that: every line is its own decision; fix the model, then score
    each line. It is on record 5 times, 09-22 to 10-03
    (memory `feedback-every-line-its-own-decision`).
- T1's measurements stand unchanged: hit vs fair and Brier by book-fair band. Their result is
  evidence for a per-line TAIL CALIBRATION (shrink the model's probability toward the book's where the
  book's fair is far from 0.5), never a gate.
- The same applies to T2 (NBA full-game spreads): evidence for fixing the NBA alternate-spread
  distribution, not for withholding a market.

## Improvement backlog (ranked by expected value × confidence)

Evidence from 11-15 / 11-16 unless noted.

| # | improvement | evidence | owner | next step |
|---|---|---|---|---|
| I-1 | **Tail calibration, per line:** shrink the model's probability toward the book's where the book's fair is far from 0.5 (the longshot overconfidence). A per-line fix, never a band gate (corrected 10:50 AM, see T1). | 21-68 at hit ≈ fair below 0.40; Brier worse than the book both days; tail lines 3-26 | **No open lane.** The flag rule `liveRowFreshEdge` came from #781 (`3c38ef4c4`); lane `rail-callouts-sim-vs-book` closed 11-14. The calibration likely belongs to the engines' live probability. | New lane + user decision; T1 tonight is the out-of-sample evidence |
| I-2 | **De-duplicate the board query.** `ranked_all` (6,295 rows) is sent again as `board_contract.cards` (the same 6,295), and `top_opportunities` (4,500) and `top_live_opportunities` (2,176) are subsets. ~26 MB unique in an 80 MB response. | 7:48 PM 11-16 `query.json`: 23.9 + 23.1 + 21.4 + 11.9 MB. Query 3-78 s, 45-83 MB; web workers recycled every 5-15 requests | unowned: `blueprints/intelligence.py` is claimed by `nba-live-props-midnight`, the page by `dh-state-aware-pairing` (09-25) | **User 11-17 ~11:0x AM CST: "start the board query de-dup session".** Started as "De-duplicate the 80 MB board query response" (local_bc8d3e61). **ON MAIN `5db26434e`** (opt-in `row_refs`; lane `board-query-row-refs` closed; todo #826). The session measured, on the recorded 7:48 PM fleet response: 80.3 → 33.1 MB raw, 14.4 → 5.7 MB gzipped, same rendered board on and off. **Not on the fleet** (fleet `92ae7490a`, checked ~12:0x PM). Loading (ff + web reload) is the user's call. |
| I-3 | **NBA slow-sport cadence** | 70 dark NBA rows at 7:48 PM 11-16; NBA builds p50 58 s; 4 `deferred_slow` | No open lane (local_208683f1 raised the decision) | Decision owed by the user |
| I-4 | **NBA alternate lines stale between alt pulls.** DOWNGRADED ~11:00 AM: staleness is not what costs the flags. | NBA `_alt` priced <= 120 s in 2 of 23 readings 11-16. **But NBA full-spread flags, 2 days, split:** alt line (>= 1 pt off the main) **7-32** (17.9% vs fair 32.1%, model 45.5%); main line 6-4 (60.0% vs 49.9%). Alt priced < 60 s 3-14; alt priced 60-120 s 4-18. Fresher alt quotes would not fix it: the model overrates alt spreads (a tail-calibration problem, I-1). | local_1f10ce63 (#811): a faster alt pull is a new build with a credit cost and the user's call | Not justified by this evidence. The fix lives in I-1 (NBA alt-spread distribution / tail calibration). |
| I-5 | **NFL quarter/half lines go stale.** Fetched every 10 min; the overlay keeps lines <= 5 min | 52% of MNF with no fresh NFL segment line | local_78b841a1 (diagnosis on main `6ff29d9c4`) | **FIX ON MAIN `c70674e3b`**: in-play quarter/half lines refresh on every lines run, 76 tests. **On the fleet since another session's 11:25 AM CST ff** (fleet `92ae7490a` contains it; live-odds-worker kept its process). It acts only once an NFL game is live: first reading at TNF 11-19, 7:15 PM CST, owed by local_78b841a1. |
| I-6 | **NFL live totals/spreads never price** (the #780 width gate); the uninformative band refuses whole games | MNF: 0 priced lines until Q3; first flag at 9:46 PM | NFL live-engine lanes (#780) | Known; the backlog records the cost |
| I-7 | **#816 level.** My "flips nightly" WITHDRAWN as the base case, ~11:00 AM (owner's re-grade). | Owner (`findings_2026-11-16_ncaab_total_overprojection.md` "2026-11-17", `6d63250fb`), finals minus live price on priced NCAAB full totals: 11-11 −8.5, 11-12 −12.7, 11-13 −7.5, 11-14 −11.8, 11-15 −10.2, 11-16 post-load +9.1 pp. Five straight under nights, then 11-16. Night-clustered over 9 pre-load nights: −4.7 ± 2.5 pp. Not quote staleness. Walk-forward, 188 games: spread+level Brier 0.2240, spread-only 0.2281, market 0.2296. The daily refit moved a from −0.358 to −0.288. **My 11-15 under/over table mixes pre-load raw-model rows, so it is not a level measurement.** | local_1f10ce63 | Spread-only is built behind `FIT_LEVEL` on its branch, not recommended on current evidence. T4 tonight goes to the owner. |
| I-12 | **Refuse a live college full-game total whose projected final is below the points already scored** (Iona @ UMBC type) | Owner graded those unders: 0.430 hit vs 0.520 price (47 games). The broader "model behind the score late" rule was falsified (+11.5 ± 1.8 pp over price, 285 games), so end-of-half flags are not refused. | local_1f10ce63 (todo #824) | BUILT, not loaded; waiting on the user |
| I-8 | **Under flag beside an "ours" above the line** | 8 of 13 at 7:21 PM 11-16 | local_1f10ce63 | Told; its call |
| I-9 | **A priced live line missing from the rail:** the MNF moneyline | Per local_208683f1 from `refresh-worker.log`: `LIVE_GAMELINE_BUILD nfl` priceable 1 only from 03:19:44Z to 03:27:20Z (0 before and after), so at the 03:23:01Z read the line was priceable but the rail had no NFL moneyline. The overlay's `refused=` counts are aggregates and cannot name it. | **No open lane** | A one-build `select_shortlist` replay at ~03:23Z (grid snapshot likely gone). Going forward, each reading compares join-priceable lines with rail rows carrying a model probability, per sport. |
| I-10 | **WNCAAB in-play coverage is thin** | 10 in-play grid rows for 7 live games at 5:41 PM 11-16. Owner: the WNCAAB live pull already runs on the 60 s default (live-odds-worker pid 3777750, no override); halves and quarters on 240 s. So it is more likely book coverage than cadence. | local_1f10ce63 (#810) | Count books per live WNCAAB game today |
| I-11 | **The monitor's own footprint** | A full page plus query = 117 MB a reading | this lane | Full page only every 4th reading (done 11-16) |

## Carried in (noon CST 11-17)

- **Fleet head `92ae7490a`.** Overnight and morning updates, from the fleet reflog and deploys.md:
  - `d7c183d8d` 6:55 PM 11-16 (the #816 display fix);
  - `17ff69398` 9:25 AM;
  - `c4d35b515` 10:24 AM (portfolio `key_player_out` refusal, #814);
  - `8aea4fe7e` 10:26 AM (#821 F0, NBA game-model-fed audit);
  - `0a60d9e0a` 11:01 AM (#807 NCAAF sim-history dedupe);
  - `3d3c0a426` 11:25 AM, plus a drained, claimed refresh-worker TERM (#790 lever (i); it also carried
    #823 option A, the NFL segment lines, I-5);
  - `92ae7490a` 11:34 AM, plus a switch flip at 11:35 AM (**#821 F1 ON, NBA outs penalties OFF**: the
    NBA game sim changed this morning).
- **refresh-worker pid 4049350** (since the 11:25 AM TERM). **live-odds-worker pid 3777750.**
- **#816:** the overnight refit wrote `total_prob_calibration_2027_asof_20261116.json` at 5:09 AM
  11-17. Per its owner, a went from −0.358 to −0.288. Tonight's NCAAB totals run on the softer level.
- **Not on the fleet:** the board-query de-dup `5db26434e` (I-2, the user's call).
- **Owed by the user:** the NFL/NBA slow-sport decision; the I-2 load; #824 (I-12).

## Reading 1 — Tue 11-17 12:01 PM CST (18:01Z), full page

**Slate (chips):**
- NCAAB 55 (1 live), WNCAAB 37 (3 live, 3 final), NHL 11, NBA 5, NCAAF 3 (Tuesday MACtion).
- 282 soccer chips, all pregame.

**Flags: 4 shown on 2 cards. 0 false, 0 missed, 0 dark.**
- NCAAB Hofstra @ Murray State: MUR −16.5 (8.8 pp); u153.5 (8.3 pp, calibrated, ours 152.8); 1H u73.5
  (6.5 pp).
- WNCAAB Alabama State @ Mississippi State u125.5 (17.5 pp, raw, ours 121.5).

**Live rows:** 23. NCAAB 19 (4 priced <= 120 s); WNCAAB 4 (3 priced <= 120 s). 2 of 8 markets carry
no price of ours.

**Overlay (60 min), 0 gaps over 360 s:**
| sport | builds | gap p50 / max | build p50 | zero-card with rows |
|---|---|---|---|---|
| NCAAB | 24 | 34 s / 68 s | 2.9 s | 0 |
| WNCAAB | 22 | 38 s / 72 s | 0.9 s | 5 |

- 0 `deferred_slow`. Tick gap p50 20 s, max 63 s.

**Web merges:** ncaab and wncaab fresh 79 / 79.

**Load:**
- `/intelligence` 7.6 s / 22.1 MB. **Query 8.1 s / 61.1 MB.** Shortlist 1.3 s; chips 0.4 s; live-rail
  0.03 s.
- Gunicorn workers were 1,276 s and 412 s old. Host load 2.1.
- **Board:** built 187 s ago; shortlist written 231 s ago.

**Teams:** 111 chips today, 0 chip-less, det1 / det2 / det3 0 / 0 / 0, 0 flipped, 0 truncated.

**Restarts:** none since the 11:25 AM refresh-worker TERM.

### Improvement hunt, reading 1

- **I-10 measured (books per live game, the in-play grid at 18:02Z; read-only, refresh-worker environ,
  nice 19; `C:\tmp\railmon\books1117.py`):**
  - NCAAB Hofstra @ Murray State: **25 in-play rows from 12 books** (BetMGM, BetOnline, BetRivers,
    BetUS, Bovada, Caesars, Circa, DraftKings, Fanatics, FanDuel, LowVig, Polymarket).
  - The 3 live WNCAAB games: **2, 3 and 5 in-play rows from 2-4 books each.** BetMGM and Kalshi in all
    three; FanDuel, Bovada or Polymarket in one each.
  - So thin WNCAAB in-play coverage is the books, not our cadence (60 s per its owner).
  - Odds requests use `--regions us` (`scripts/refresh_odds_sources.py:4230`, default "us"). Adding a
    second region (e.g. `us2`) for WNCAAB in-play might add books, at a credit cost per call.
  - Candidate for local_1f10ce63 (#810), and the user's call. Not measured: which books `us2` would add
    for WNCAAB.

### #824 LOADED (12:03:56 PM CST) — new watch items from its owner

- **What loaded:** the owner local_1f10ce63 restarted refresh-worker (claimed TERM) at **18:03:56Z**, fleet
  `92ae7490a`; **new pid 4060729** (deploys.md 2026-11-17 18:03:56Z).
- **What it does:** a live NCAAB/WNCAAB full-game total whose projected final is below the points
  already scored is refused (no edge, no Live number), reason `model_projected_final_below_points_scored`.
- **Size:** ~0.5% of priced totals 11-08..11-16, so a handful at most on a full slate.
- Backlog I-12 status: LOADED.
- **Each college reading from now on (the owner's request):**
  1. The count of that reason in `LIVE_GAMELINE_JOIN` `why=` (`C:\tmp\railmon\why824.sh <since>`).
  2. Any rail totals flag whose "ours" is below the segment's points already scored
     (`C:\tmp\railmon\c824.py <reading dir>`).
     - For full-game totals that would be a miss of the guard.
     - Segment totals are not covered by it; reported separately.
- **Baselines:**
  - Since 18:03:56Z: 0 of 14 college `LIVE_GAMELINE_JOIN` lines with the reason.
  - Reading 1 (12:01 PM, 2 minutes before the load): 0 of 3 college totals flags below the score.
- College ledger rows now carry `state_home_score` / `state_away_score` / `state_period` /
  `state_clock_seconds` (the score and clock the re-sim started from), usable to grade the model's lag.

### I-2 load — user 11-17 ~12:40 PM CST: "Load it tonight" (answering "Load the board-query de-dup onto the fleet?")

**What turns it on:**
- The page template sends `row_refs: true`; the server honours it. The off switch is
  `SYNDICATE_QUERY_ROW_REFS=off`.
- It works in both directions: an old cached page gets the full response, and a new page on an old
  server gets the full response.
- So it takes effect with an ff plus `reload-web`.

**The plan:** an exact-SHA ff `92ae7490a -> 5db26434e`, then `reload-web` (a rolling HUP), at or after
~5 PM CST, behind a web claim and preflight. Measure the page's query bytes and seconds before and
after.

**Ride-along check** (`92ae7490a..5db26434e`, 21 commits; runtime files):
- **`ac2cbc2fc`, render-config-retirement step 1** (`scripts/local_production.py` reads
  `fleet_role_spec.json` + `fleet_env/`):
  - The lane closed; the owner verified 0 env keys differ.
  - But **the user said "Steps 1+2, load later"**.
  - The ff would put it on the fleet's disk, live at the next `up`. **User decision asked**;
    "Remove Render's config and markers from the fleet" (local_c787e775) also asked.
- **`2148f99cb`, paper-endpoint-request-path** (`/portfolio/paper` reads a worker-written all-dates
  record):
  - The lane is open and not loaded.
  - After `reload-web` the new web code would run before refresh-worker writes that record.
  - **The owner was asked** (local_d7643dac) whether it is safe as a ride-along.
- `.claude/hooks`, `check_lane_invariants.py`, `fleet_secrets_backup.py`, `fleet_env_snapshot.py`:
  tooling, not imported by any running role.
- **No load until both answers are in.**

- **Ride-along answer, `2148f99cb` (paper-endpoint-request-path, owner session 69d80317 =
  local_d7643dac, ~12:50 PM CST): "(a) Safe as a ride-along".**
  - Before the worker's first write, `read_paper_all_time()` returns None and the template prints no
    all-dates line: no error and no zero.
  - On the fleet's data (web worker environ, nice 19, read-only), the old and new builders gave
    identical paper orders, idempotency keys, ledger summary and date settlement for 11-17, 11-16 and
    10-20. New: 0.5-0.7 s warm, 105-137 MB peak. Old: 5-13 s, 769-1,052 MB.
  - Worker side, at the next refresh-worker restart: `settle_orders()` writes
    `reports/intelligence/paper_settlement_all_time.json` (try/except, `PAPER_ALL_TIME_WRITTEN` /
    `_FAILED`). No restart is needed for this load.
  - Display only. **The owner asks that the deploy record note that `2148f99cb` reached web**; it
    will time one `/portfolio/paper` GET afterwards.
- **Still waiting:** the user's decision on `ac2cbc2fc` (read at `up`, not at `reload-web`, per both
  owners), and local_c787e775's answer.
- **Ride-along answer, `ac2cbc2fc` (local_c787e775, 18:39Z):** it is not loading render-config steps 1+2
  and has no user go either. Don't wait for it. Facts it checked:
  - **What the ff carries:** `5db26434e` contains step 1 (`ac2cbc2fc`) but not step 2 (`cc90fb653`). An
    exact-SHA ff cannot leave step 1 out.
  - **What step 1 changes:** only `scripts/local_production.py`, `scripts/fleet_role_spec.json`,
    `scripts/fleet_env_snapshot.py`, `scripts/fleet_secrets_backup.py`, and tests. No web worker
    imports any of them.
  - **`reload-web` does not run the new env path:** `cmd_reload_web` (`local_production.py:2486-2550`)
    only HUPs the gunicorn master.
  - **What would run step-1 code after the ff:**
    - any `local_production.py` CLI (`status`, `env` incl. preflight's env reads, `doctor`);
    - the nightly 09:15Z data-backup (its secrets step reads `fleet_env/`);
    - `ci-run`;
    - the next `up` (incl. a reboot or WSL-update restart).
  - **The data is in place:** `fleet_env/` is on the fleet disk, the same as `render_env/` (88 / 182 /
    148 keys, mode 600). The old and new launcher build identical env (0 keys differ, both state modes).
  - **New behaviour:** `up` refuses a role with no `fleet_env/<role>.json`. The files exist, so it has
    no effect today. No betting change.
  - Whether step 1 rides along is the user's call (the user said "Steps 1+2, load later"). Asked in
    the next-step box ~12:45 PM CST.
- **User 11-17 ~12:55 PM CST: "Carry it tonight"**, answering "Carry the launcher change you deferred
  along with tonight's de-dup update?". So the I-2 load carries `ac2cbc2fc` (render-config step 1)
  and `2148f99cb` (paper endpoint).
- **Load plan:** at the first tick at or after 5:00 PM CST:
  1. Run from a worktree at origin/main.
  2. Baseline the page query's bytes and seconds and the fleet head `92ae7490a`.
  3. `deploy_claim.py acquire --service web --holder layer2-rail-monitor` (gate on the exit code).
  4. `deploy_preflight.py --service web --target-commit 5db26434e --expect ... --baseline ...`.
  5. Fleet ff to exactly `5db26434e`.
  6. `local_production.py reload-web`.
  7. Verify the page query is about 5.7 MB on the wire and the response carries `_response_row_refs`.
  8. Record in deploys.md (naming `ac2cbc2fc` and `2148f99cb` as carried), then release the claim.
- If the fleet head has moved past `92ae7490a` by then, re-run the ride-along check on the new range
  first.
- **Also, relayed by local_1f10ce63:** the user typed in that session at ~12:4x PM CST 11-17: **"carry the launcher change along"**, answering the same question. The deploys.md entry quotes both: "Carry it tonight" (this session) and "carry the launcher change along" (local_1f10ce63).
- **Also, from local_c787e775:** asked "When should steps 1+2 load on the fleet?", the user replied at ~12:48 PM CST: **"With next down/up"**. Consistent with tonight's carry: the ff puts step 1 on disk; `reload-web` builds no env; the nightly backup, preflight env reads and the next drained down/up run it (the user was told this before answering "Carry it tonight"). The before/after readings for steps 1+2 are owed by whoever runs the next drained down/up (todo #766, `findings_2026-11-17_render_config_retirement.md` "The load"), not by this load.
- **Post-ff check added (local_c787e775):** run `local_production.py status` once after the ff. Its memory-cap line calls `load_role_spec` + `fleet_env/`, so a clean run proves the new spec and snapshot load; a traceback or "no keys for role" is the failure. Send local_c787e775 the ff time; it will then compare each role's launcher-built env with the live `/proc/<pid>/environ` per key by sha256, read-only. It expects only `RENDER_INSTANCE_ID` and `RENDER_GIT_COMMIT` (plus inherited shell keys) to differ.
- **LOAD OWNERSHIP MOVED (~1:10 PM CST):** lane `board-query-row-refs-load` (session e569a6cd = local_bc8d3e61, the de-dup session) opened on main (`3a24317a4`). The user said "Load it" + "Carry both" in that session. **This monitor stands down from running the load** (no web claim, no ff). It handed over the user's quotes from the other sessions and the asks from local_c787e775 (post-ff `status`, ff time) and local_d7643dac (note `2148f99cb` reached web). After the reload, this monitor reads the rail: query wire size, `_response_row_refs` present, worker ages, 0 detector changes.

## Reading 2 — Tue 11-17 1:07 PM CST (19:07Z), full page — after the I-2 load

### I-2 LOADED by lane `board-query-row-refs-load` (local_bc8d3e61) — measured on the rail

- **Fleet ff `92ae7490a -> 5db26434e` at 12:58:43 PM CST** (fleet reflog). `reload-web` HUP at
  12:58:46 PM (`web.log`: "Handling signal: hup", new workers 4074414 / 4074415).
- **It carried** `ac2cbc2fc` (render-config step 1, on disk, inert until the next down/up per the user's
  "With next down/up") and `2148f99cb` (the paper endpoint).
- **Same-instant A/B of the page's own query body** (`C:\tmp\railmon\refs_ab.py`, three back-to-back
  POSTs, read-only):

  | request | wire | raw | `_response_row_refs` | time |
  |---|---|---|---|---|
  | `row_refs: true` | **4.38 MB** | **24.25 MB** | present | 17.6 s |
  | no `row_refs` | 11.37 MB | 61.86 MB | absent | 16.8 s |
  | `row_refs: true` | 4.39 MB | 24.28 MB | present | 14.9 s |

- **The size cut is −61% on the wire and −61% raw.** Server time did NOT drop: 14.9-17.6 s vs 16.8 s at
  host load ~10-11. `QUERY_STAGE_MS` (refs true, 19:01:40Z) puts the time in:
  - `hydrate_and_mirror` 8.8 s;
  - `version_and_debug` 2.7 s (11.1 s on the 19:07:22Z refs-false request);
  - `drop_row_diagnostics` 2.6 s;
  - `slim` 2.1 s;
  - `row_refs` 1.2 s.

  The win is the client's download and parse, and web memory per response. See I-13 for the server time.
- **The page sends `row_refs`:** `QUERY_STAGE_MS` at 19:01:40Z shows `"refs": true`.
- **This monitor's own probe does NOT send it**, so its 28.4 s / 11.35 MB reading below is the refs-off
  path. The probe will be updated to send `row_refs` and rehydrate through the page's own function
  (this lane's files).
- `/portfolio/paper` answered **302** in 0.08 s (a redirect). The 200 check is the load lane's.
- Teams after the reload: 0 chip-less, det1 / det2 / det3 0 / 0 / 0, 0 flipped, 0 truncated.

### Reading 2

**Slate:** 3 live chips.
- NCAAB: Hofstra @ Murray State H2 5:45; Houston @ Rutgers H1 16:29.
- WNCAAB: Murray State @ Oregon Q1.

**Flags: 2 shown on 1 card. 0 false, 0 missed, 0 dark.**
- Hofstra @ Murray State u152.5 (6.9 pp, calibrated; **ours 154.6, above the line**) and 2H o76.5
  (6.9 pp).

**Live rows:** 42. NCAAB 39 (17 priced <= 120 s); WNCAAB 3 (1 priced <= 120 s). 2 of 11 markets carry
no price of ours.

**Overlay (66 min):**
| sport | builds | gap p50 / max | notes |
|---|---|---|---|
| NCAAB | 66 | 52 s / 287 s | **1 `deferred_slow`** |
| WNCAAB | 65 | 55 s / **373 s** (1 over 360 s) | 7 zero-card builds with rows |

- Tick gap p50 26 s, max 189 s.

**Web merges:** ncaab fresh 71 / 71; wncaab 70 / 71.

**#824:** 0 of 22 college `LIVE_GAMELINE_JOIN` lines since 18:03:56Z carry
`model_projected_final_below_points_scored`. 0 college totals flags below the points scored (0 of 2).

**Load:**
- `/intelligence` 10.1 s. Query (refs off) **28.4 s** / 61.7 MB. Shortlist 1.5 s.
- **Host load 11.1 → 10.6 → 7.5** over the reading. Board built 456 s ago.
- CPU at 13:11 CST, no single cause: a soccer artifact build (championship, 95%), refresh-worker (95%),
  web workers (66% + 26%), live-odds-worker (62%), `kalshi_combo_capture` (39%), a nice-19
  `du -sb syndicate-prod-backup` (42%), a WNBA ESPN live-status fetch (59%) and a WNBA schedule fetch.

**Restarts:**
- live-odds-worker **3777750 → 4062745**: a routine recycle ("exited code=0 after 21751s", after a 200 MB
  log rotation).
- refresh-worker 4060729.

### Improvement hunt, reading 2 — new backlog items

| # | improvement | evidence | owner | next step |
|---|---|---|---|---|
| I-13 | **Cache the built query response per board version** instead of rebuilding it on every request | Each page query spends ~15-17 s server-side at host load ~10: `hydrate_and_mirror` 4-9 s, `version_and_debug` 2.7-11 s, `drop_row_diagnostics` 2.6-3.2 s, `slim` 0.6-2.1 s. The board changes every few minutes, but the same 5,100-row response is rebuilt and re-hashed per request. | Board-query area. The `row_refs` work's session local_bc8d3e61 has the context; no open lane on the cache. | Sent to local_bc8d3e61. A session card if it declines. |
| I-14 | **Offseason WNBA work in November (unverified cost)** | At 13:11 CST a WNBA ESPN live-status fetch (59% CPU) and a WNBA schedule fetch were running; the WNBA season is over. Frequency not measured: the job's lines are not in the role logs. | Unknown | Measure how often these run (job log / supervisor) before calling it waste |
| I-15 | **The monitor's probe should send `row_refs`** like the page, and rehydrate through the page's function | Since 12:58 PM the probe measures the refs-off path (28.4 s / 61.7 MB), not what users get | This lane | Update `scripts/layer2_rail_monitor_probe.py` + `layer2_rail_monitor_run.mjs`, test, land |

- **I-15 DONE (~1:16 PM CST):** `scripts/layer2_rail_monitor_probe.py` now sends `row_refs: true` like the page (`--no-row-refs` reads the old path), and its runner rebuilds the lists through the page's own `rehydrateAliases`. **off != on, back to back at 1:14 PM:** the same rail (111 cards, 4 live, 1 flag, teams identical; live-rail rows 44 / 47, 40 s apart); query 4.73 MB wire / 25.9 MB raw / 11.5 s (refs) vs 12.08 MB / 65.2 MB / 12.4 s (no refs). From reading 3 on, the probe's query load is what the page gets.

- **I-2, the load lane's own record (local_bc8d3e61; deploys.md "2026-11-17 18:58:45Z", main `ea6aab2e2`; lane CLOSED `46a2bcbbc`):**
  - web claim 18:54:47Z; preflight CLEAR 18:58:02Z; ff 18:58:45Z; `reload-web` 18:58:52Z (0 failures); claim released 19:05Z.
  - Baseline: the page's query at 18:56:07Z, 11,214,708 B gz, **136.6 s** (web saturated).
  - After, at 18:59:08Z: 4,320,530 B gz (38.5%), 23.98 MB raw, 200 in 18.1 s. `version_and_debug` 1,968 ms (7.4-7.9 s before).
  - Headless `/intelligence`: 0 page errors, 2,600 card nodes, rail drawn.
  - `2148f99cb` (paper): its owner measured 200 in 31.4 s, no WORKER TIMEOUT. `cc90fb653` and the paper retirement `f7fb3ed4e` are NOT on the fleet.
  - **Owed to this monitor:** `WEB_WORKER_MEMORY_RECYCLE` per query request after the load vs before (28 recycles 16:00-18:59Z). Note that open browser tabs keep the old page JS (no `row_refs`, ~11 MB a poll) until reloaded.
- **I-13 update (~1:25 PM CST):** local_bc8d3e61 declined it (its lanes are closed; it is new work), giving 6 design notes: mirror `_slim_embedded_board_payload`'s once-per-window embed cache; key on the request flags + `sort_keys`, not only the board version; keep `timestamp` / `selected_date` / debug per request; cache gzipped bytes (~4.4 MB) rather than the ~24 MB dict; check `LAST_RESULT` readers; `response_hash` equality as the per-line-neutral test. **Proposed as a session card, "Cache the built board query response per board version" (task_ab023c09).** Also from it: `local_c787e775`'s post-ff reading at 19:06:39Z gave `status` rc 0 with every role's env identical except `RENDER_GIT_COMMIT` (deploys.md 19:06:39Z).

## FLEET EVENT — host restart 1:48:57 PM CST (19:48:57Z)

- **Cause:** Windows event 1074, StartMenuExperienceHost on behalf of the user, "Other (Unplanned)",
  restart. Host up again at 1:50:05 PM.
- **`SyndicateLocalProduction` brought the fleet back** (`supervisor.log`): "LOCAL PRODUCTION UP ...
  state=redis port=10000 commit=5db26434e310", **money LIVE**.
  - web pid 496 (/healthz 200), **refresh-worker pid 560**, **live-odds-worker pid 561**.
  - Redis AOF already on; bootstrap rc 0.
  - One launcher line: "[web] 1 declared key(s) with no value in any layer: ANTHROPIC_API_KEY".
    Believed pre-existing (Ask LLM off by decision); flagged to local_c787e775.
- **This `up` is the first to run render-config step 1 (`ac2cbc2fc`) from disk.** It is the user's "next
  down/up", but NOT drained, so the step-1 readings are owed against it (local_c787e775 told ~1:57 PM).
- Anything in flight on the workers at 1:48 PM was killed by the restart.

## Reading 3 — Tue 11-17 1:58 PM CST (19:58Z), full page — 8 minutes after the restart

**Slate:** 3 live chips.
- NCAAB: Rutgers @ Houston H1 0:30.
- WNCAAB: Pepperdine @ Nevada HALF; Murray State @ Oregon HALF.

**Flags: 1 shown. 0 false, 0 missed, 0 dark.**
- WNCAAB Murray State @ Oregon u178.5 (13.2 pp, raw; ours 174.3).

**Live rows:** 28. NCAAB 18 (5 priced <= 120 s); WNCAAB 10 (3 priced <= 120 s).

**Overlay (48 min), the restart outage included:**
| sport | builds | gap p50 / max | gaps over 360 s |
|---|---|---|---|
| NCAAB | 27 | 48 s / **849 s** | 2 |
| WNCAAB | 26 | 57 s / **829 s** | 2 |

- Worker tick gap max **1,328 s**. All of it spans the 1:48-1:52 PM outage. 0 `deferred_slow`.

**Web merges:** fresh 28 / 28.

**Load, cold after the restart:**
- `/intelligence` **42.7 s** / 22.5 MB. **Query 29.1 s / 4.38 MB wire / 24.25 MB raw** (`row_refs`, I-15
  probe). Shortlist 2.2 s; chips 1.5 s.
- Gunicorn workers 432 s old (all three since the `up`). Host load 9.5 at 7 minutes up.
- **Board:** built 218 s ago. Query snapshot 6,214 s old: watch whether the state loop refreshes it
  after the restart.

**#824:** 0 of 8 college `LIVE_GAMELINE_JOIN` lines since 19:07Z with the reason; 0 college totals
flags below the points scored (0 of 1).

**Teams:** 0 chip-less, det1 / det2 / det3 0 / 0 / 0, 0 flipped, 0 truncated.

### I-2 owed reading — web memory recycles per query (sent to local_bc8d3e61)

| window | recycles | query POSTs (`row_refs`) | all requests | per hour | per query |
|---|---|---|---|---|---|
| before, 16:00-18:58:46Z | 28 | 25 (0) | 550 | 9.4 | 1.12 |
| after, 18:58:46-19:48:50Z | 11 | 13 (5) | 190 | 13.2 | 0.85 |

- **Not measurable yet.** 8 of the 13 post-load query POSTs still asked for the full response: 3 were
  this monitor's own A/B, the rest likely open tabs on the old page JS.
- Recycled workers ran anon 650-980 MB after 5-20 requests.
- From the 19:50Z restart, every worker is fresh and browsers likely load the new page. **Tonight's slate
  is the clean window:** recycles per hour and per `row_refs` query, read at the daily summary.

- **I-2 recycle reading, the load lane's partial (deploys.md 19:56:53Z, main `675fe06fb`): NOT ATTRIBUTABLE yet.**
  - Before (16:00-18:59Z): 25 queries, all full form; 28 recycles (20 hard); 1.12 per query.
  - After (18:59-19:57Z): 14 queries, 5 in the new form; 11 recycles (7 hard); 0.79 per query.
  - The request rate is about the same (~210 per hour).
  - The 9 full-form queries after the load: **8 Python-urllib scripts** (19:01, 19:07, 19:08, 19:10, 19:15, 19:22, 19:38, 19:52Z, each 11.2-12.1 MB; several are this monitor's A/B and pre-I-15 probe), plus 1 browser tab still on the old page JS (19:17:53Z, referer `/?live_edge=any`).
  - This monitor finishes the reading tonight over the clean post-restart window, with `C:\tmp\rowrefs826\recycle.py` (`wsl -- python3`; it splits by response size, < 7 MB = new form).

| # | improvement | evidence | owner | next step |
|---|---|---|---|---|
| I-16 | **Read-only scripts still pull the full ~11.8 MB board query.** Have each send `row_refs` and decode with `response_row_refs.decode_row_refs` (or the page's `rehydrateAliases`), as this monitor's probe does since I-15. | 8 Python-urllib full-form POSTs in the hour after the load. Ad-hoc readers that POST `/api/intelligence/query` sit in `C:\tmp\railload\` (`rail_probe.py`, `rail_census.py`, `callout_tracker.py`, `served_dump.py`, ...), `C:\tmp\nbaname\` (`liveedge_read.py`, `portis_liveedge*.py`), `C:\tmp\lpa\ledger_nfl_sunday.py`. Which run on a schedule is unknown. | Each script's session; scheduled monitors first | Count full-form POSTs per hour from `web.log` tonight (response size > 7 MB), then name the recurring callers |
- **The I-2 recycle reading, as run tonight.** The args are START SPLIT END in UTC; under 7 MB counts as the new form.
  - **After** (the clean window):
    `MSYS_NO_PATHCONV=1 wsl -d Ubuntu-24.04 -- python3 /mnt/c/tmp/rowrefs826/recycle.py 2026-11-17T19:51:31 2026-11-17T19:51:31 <END_UTC>`
  - **Before** (Monday evening, the same kind of slate):
    `... recycle.py 2026-11-16T23:00:00 2026-11-17T05:00:00 2026-11-17T05:00:01`
  - It reads the last 400 MB of `web.log` (env `RECYCLE_TAIL_BYTES`); the Monday window may need a larger tail.
  - The load lane voided its restart-spanning window (deploys.md 20:02:54Z, main `2e43d5bd2`).
  - The 19:51Z `up` is classified BC-033 "no" by the load lane. Do not add a second row.
- **Render-config step 1, verified after the restart's `up`** (local_c787e775, deploys.md "2026-11-17 19:58:28Z", BC-035 no; the load is BC-033): every role's live `/proc` environ (160 / 262 / 235 keys) matches what the old and new launchers build, with **0 keys differing**. `ANTHROPIC_API_KEY` is not new: the old launcher listed the same unset key on web, and the two launchers' unset lists are identical. Steps 2 / 3a are not on the fleet.
- **I-13 MEASURED, NOT BUILT** (session local_004fdc3e; findings on main `661c80a47`).
  - The page's 60 s poll got a new response hash 6 of 6 times during live play. Only back-to-back
    duplicates matched (~4.5% of queries; 2.9 s warm vs 5.7 s).
  - So a cache keyed on the board version would barely hit. The premise holds only for duplicate
    requests. No code changed, nothing loaded.
  - Server time is still the cost; the next lever would be the per-request stages themselves
    (`hydrate_and_mirror`, `version_and_debug`), not a response cache.
- **#827 (strip diagnostics from the `top_live` rows, the de-dup follow-up) is ON MAIN `25fc2e4f0`**, NOT
  loaded.
  - Recorded response 5.7 → 4.6 MB on the wire.
  - The fleet runs `5db26434e`, 83 commits behind main, so loading it needs its own ride-along check and
    the user's decision.

## Reading 4 — Tue 11-17 2:35 PM CST (20:35Z)

**Fleet:** `5db26434e`, stable since the 19:50Z `up` (refresh-worker 560, live-odds-worker 561). Host
load 1.9.

**Slate:** 3 live chips.
- NCAAB: Rutgers @ Houston H2 13:26.
- WNCAAB: Pepperdine @ Nevada Q4; Murray State @ Oregon Q4.

**Flags: 4 shown on 2 cards. 0 false, 0 missed, 0 dark.**
- NCAAB Rutgers @ Houston: HOU −16.5 (6.9 pp); u153.5 (**18.7 pp**, calibrated, ours 149.4); 2H u76.5
  (6.1 pp).
- WNCAAB Murray State @ Oregon u178.5 (16.0 pp, raw, ours 175.7).

**Live rows:** 38. NCAAB 18 (5 priced <= 120 s); WNCAAB 20 (7 priced <= 120 s). 2 of 8 markets carry
no price of ours.

**Overlay (37 min), 0 gaps over 360 s:**
| sport | builds | gap p50 / max | zero-card with rows |
|---|---|---|---|
| NCAAB | 44 | 50 s / 102 s | **18** |
| WNCAAB | 40 | 51 s / 154 s | 1 |

- **All 18 NCAAB zero-card builds are the value floor:** `refused={"rows_below_value_floor":N}` with N
  equal to the opportunities (9-20). This is the decided behaviour (the user: "Keep the floor"). NCAAB
  builds with cards published 15-17 (`refused` floor 22-24, implausible book 1).
- 0 `deferred_slow`. Tick gap p50 33 s, max 138 s.

**Web merges:** fresh 50 / 50.

**Load (warm again):**
- **Query 9.2 s / 4.47 MB wire / 24.7 MB raw** (`row_refs`). Shortlist 0.78 s; chips 0.86 s; live-rail
  0.06 s.
- Gunicorn workers 546 s and 304 s old.
- **Board:** built 80 s ago. **Query snapshot 1,112 s old**: the state loop refreshed it after the
  restart (6,214 s at 1:58 PM).

**#824:** 0 of 16 college `LIVE_GAMELINE_JOIN` lines since 19:58Z with the reason; 0 college totals
flags below the points scored (0 of 3).

**Teams:** 0 chip-less, det1 / det2 / det3 0 / 0 / 0, 0 flipped, 0 truncated.

**Restarts:** none since the 19:50Z `up`.

### Improvement hunt, reading 4

- **I-14 parked (low value).** The WNBA work visible in the role logs is the intelligence overview
  pass (`OVERVIEW_SPORT_BEGIN sport=wnba` → `_END` in ~0.3 s, 0 games): negligible. The ESPN WNBA
  live-status fetch seen at 13:11 is not logged per run, so its frequency stays unmeasured. Not worth
  more time without a cost signal.
- **I-13 measured, not built; #827 on main, not loaded:** recorded above.

## Reading 5 — Tue 11-17 3:28 PM CST (21:28Z), full page — the afternoon lull

**Fleet:** `5db26434e`; refresh-worker 560 (up 5,401 s); live-odds-worker 561. Host load 1.9.

**Slate:** 0 live chips. The early college games are final; the evening wave starts ~5 PM.

**Flags:** 0 shown, 0 false, 0 missed, 0 dark. 0 live rows.

**Overlay (53 min):** NCAAB 69 builds, gap max 134 s; WNCAAB 24 builds, gap max 87 s (9 zero-card with
rows, the floor). 0 over 360 s. 0 `deferred_slow`.

**Load:**
- `/intelligence` 7.0 s / 23.5 MB. **Query 2.8 s / 4.60 MB wire / 25.3 MB raw** (`row_refs`, nothing
  live). Shortlist 0.8 s; chips 0.02 s.
- Board built 186 s ago; query snapshot 1,556 s.

**#824:** 0 of 34 college join lines since 20:35Z with the reason; 0 flags.

**Teams:** 0 defects.

**Restarts:** none.

### I-2 recycle reading, the clean post-restart window so far (19:52-21:27Z, 1.58 h; `recycle.py`)

| requests | queries (`row_refs` / full) | recycles (hard) | per query | per hour | requests per recycle (median) | anon MB at recycle (median) |
|---|---|---|---|---|---|---|
| 273 | 18 (11 / 7) | 19 (18) | 1.06 | 12.0 | **10** | 878 |

- **Reading:** recycles track ALL requests (~1 per 10), not the board query (19 recycles for 18
  queries). So the query's −61% is not the main memory driver, which leads to I-14 below.
- The final number comes at the daily summary, over the evening slate.

### Improvement hunt, reading 5

**I-14 RE-OPENED with a count: ~70% of the web's requests in November are WNBA box-score calls, in the
WNBA offseason.**
- **Measured:** web route mix since 19:51:31Z (273 requests):
  - `GET /wnba/api/final_player_boxscore` 120;
  - `GET /wnba/api/live_player_boxscore` 70;
  - `POST /api/syndicate/query` 22;
  - `POST /api/intelligence/query` 19;
  - `GET /api/board/live-rail` 9.
  - All 190 WNBA calls come from Python-urllib (the fleet's own scripts).
- **Per day:** 1,790 (11-14), 1,626 (11-15), 1,858 (11-16), 1,947 (11-17).
- **`live_player_boxscore?date=2026-11-17`:** every 1-2 min, an empty 199-byte answer, **0.8-5.1 s each**.
  - Caller: `scripts/capture_wnba_live_player_box.py`, via the WNBA live-lens loop
    (`syndicate/features/shared/live_lens_loop.py`, `syndicate/features/wnba/live_lens.py`). It refuses
    to store an empty capture but polls anyway.
- **`final_player_boxscore?...&count_only=1`:** repeatedly for **2026-06-03 (28), 06-04 (37), 06-05 (9)**,
  plus 11-16 (20) and 11-17 (22).
  - Caller: the refresh-worker's WNBA postgame backfill (`scripts/run_refresh_worker.py` ~1600-1640 →
    `build_wnba_boxscores.build_date`).
  - It retries a date whose box was never published (`_WNBA_BOX_REBUILD_MAX_ATTEMPTS`).
  - The three June dates look stuck. The loop never drains to its hourly stamp, so it re-asks them
    every few minutes.

| # | improvement | evidence | owner | next step |
|---|---|---|---|---|
| I-14 | **Stop offseason WNBA polling:** the live box-score capture with no WNBA games on the date, and the postgame backfill stuck on 06-03..06-05. Per line / per date, never a sport switch: skip a date with 0 scheduled games, and stop retrying a date whose box cannot publish. | Above. ~1,900 web requests a day, 70% of web traffic since the restart; live calls 0.8-5.1 s each, for nothing. | No open lane found (WNBA live / postgame code) | Proposed as a session card |
| I-16 | **A scheduled full-form reader** | Python-urllib full-form (11.3-11.6 MB) `/api/intelligence/query` POSTs at a 15-minute cadence: 20:07:30, 20:22:10, 20:37:09, 20:52:12, 21:07:10, 21:22:11Z (:07 / :22 / :37 / :52). | Unknown (likely another session's scheduled monitor) | Name the caller: scheduled-task prompts that POST the query |
- **I-14 picked up (~3:45 PM CST):** the user started "WNBA box-score polling" from local_1f10ce63 ("start the WNBA box-score polling session") as **local_dee5a95c** (`wnba-boxscore-polling`). This monitor's duplicate card task_8d96c2b0 is dismissed. The numbers are in reading 5 (the item is I-14 here). I-16 (the 15-minute 11.5 MB full-form puller) stays with this monitor.
- **I-16 IDENTIFIED** (local_1f10ce63, at the user's request "find the 15-minute board query puller too"): the Windows scheduled task **`SyndicateCheatSheetPicks`**, every PT15M since 2026-10-16 14:37 CST.
  - It runs `scripts/build_cheat_sheets.py --picks-only`; its `fetch_board_cards()` (~line 704) POSTs the query without `row_refs` and reads only `response.board_contract.cards` (~5,300 cards).
  - 83 requests today, median 11.1 MB on the wire.
  - The fix: send `row_refs` and decode with `response_row_refs.decode_row_refs`. The file belongs to the `cheat-sheets` lane. Proposed as session card **"Cheat-sheet picks: request the compact board query" (task_8e1142e4)**. No fleet load is needed beyond the next ff, since the task runs `~/Syndicate`.

## Reading 6 — Tue 11-17 4:08 PM CST (22:08Z) — the evening wave starts

**Fleet changed twice since reading 5. Both changes were other lanes' work; each was recorded in deploys.md by its owner.**
- **3:52 PM:** the render-config session ran a full `up` on `91d865fd5` (supervisor: `LOCAL PRODUCTION UP ...
  commit=91d865fd5251`). New pids: web 28883, refresh-worker 28948 (boot 21:53:02Z), live-odds-worker 28949.
- **3:56:24 PM:** ff to `25fc2e4f0` + `reload-web` (#827, lane board-query-diag-strip-load, deploys.md 21:56:24Z).
  The workers still run `91d865fd5`'s code. #827 is web-only.
- Host load 5.0. Top consumers:
  - refresh-worker 113% CPU, RSS 2.9 GB at 18 min;
  - a Serie A soccer artifact build 108%;
  - live-odds-worker 58%;
  - `kalshi_combo_capture` 55% at nice 19.

**#827 is on the rail.** The probe sends the page's body, `row_refs` included.
- **Query: 4.13 MB wire / 22.5 MB raw**, against 4.60 / 25.3 at reading 5 with nothing live (−10% / −11%).
- `rationale` appears only in `_dropped_row_fields`; 0 `diagnostics` keys in the response.
- **TTFB 15.2 s:** both gunicorn workers were born or recycled within ~30 s of the query (pids 32906 at
  22:08:36Z, 33273 at 22:09:20Z). That is a cold worker, the same 15-18 s server time the de-dup lane measured.
- Other loads: shortlist 1.5 s; chips 0.56 s; live-rail 0.02 s.
- Board built 344 s ago; query snapshot 3,994 s old.

**Slate:** 2 live chips. NCAAB Notre Dame @ Florida H1 11:40; WNCAAB Army @ UMass Q1 5:38.

**Flags: 1 shown, 0 false, 0 missed, 1 dark.**
- **Shown:** NCAAB Notre Dame @ Florida u139.5, 5.0 pp (calibrated 0.555 vs fair 0.504), priced 23.5 s ago.
  The card shows **ours 142.2**, which sits on the other side of the line from the flagged under. See I-17 below.
- **Dark:** the same game's 1H spread FLA −12.5 / ND +12.5, ND +12.5 side, gap 10.1 pp. Priced 100 s, now 444 s old.

**Live rows: 18.**
- NCAAB 17 (3 priced <= 120 s); WNCAAB 1 (1).
- 12 of 18 rows are over 300 s old now; priced age p50 181 s.
- 1 of 6 markets carries no price of ours.

**Overlay (40 min).** 0 gaps over 360 s; 0 `deferred_slow`.

| sport | builds | gap p50 / max | zero-card with rows |
|---|---|---|---|
| NCAAB | 16 | 52 s / 91 s | 0 |
| WNCAAB | 6 | 58 s / 62 s | **6 of 6**, all the value floor (`refused={"rows_below_value_floor":N}`, N = opportunities 6-12; the user's "Keep the floor") |

- **Book-grid ticks:** gap p50 58 s. The 235 s max straddles the 3:52 PM `up` (21:51:34 → 21:55:29Z).
  Before it, during the lull, there were three gaps of 167-173 s.

**Web merges:** NCAAB fresh 31 / 31. WNCAAB: **15 stale** (21:55:42-22:02:30Z, `stale_3795s`..`stale_4203s`),
then 16 fresh.
- **Cause:** the last WNCAAB overlay before the lull was written at 20:52:27Z. The next build came at 22:04:54Z,
  when Army @ UMass had in-play rows.
- So the evening's first live WNCAAB game had a chip by 21:55:42Z and **no fresh overlay for ~9 min**.
- This matches I-10 (WNCAAB coverage is the books' in-play listings). Not checked whether any book listed
  Army @ UMass in play before 22:04Z.

**#824:** 0 of 10 college `LIVE_GAMELINE_JOIN` lines since 21:28Z carry the reason. 0 college totals flags
below the points scored (0 of 1).

**Teams:** 0 chip-less, det1 / det2 / det3 0 / 0 / 0, 0 flipped, 0 truncated, 0 live chips without a live card.

**Restarts:** the 3:52 PM `up` and the 3:56 PM `reload-web` above. No unplanned restart.

### Improvement hunt, reading 6

**I-17: college total cards show the sim's projected final next to a calibrated flag on the other side.**

- **Measured (`flags.jsonl`, every shown college totals flag since the #816 load, 11-17 00:04:20Z):**
  - **NCAAB full game: 23 of 74 flag observations** show "ours" on the opposite side of the line. That is
    24 distinct matchup × side across NCAAB and WNCAAB.
  - **Every one is an under with ours above the line.** Examples:
    - Long Beach St @ UCLA u145.5 at ours 150.8;
    - Columbia @ Northwestern u127 at ours 133.7;
    - Texas Southern @ UC San Diego u184.5 at ours 186.2 (27.0 pp).
  - WNCAAB full game: 1 of 17. NCAAB halves: 0 of 21 (outside #816's scope).
- **Why:** the flag is right by #816's design.
  - The served P is `logit p_mkt + a + c (logit p_raw − logit p_mkt)`, with the level `a` ≈ −0.29 to −0.37 on
    the over: about −9 pp at a 50/50 line.
  - "ours" is `live_total`, the sim's own median. #816 found that pregame this median carried no information
    against the close (slope 0.017 ± 0.129, 621 games).
  - So the card puts the one number we decided not to trust beside the decision that overrules it.
- **Fix (per line, display only, no probability changes):** show the line at which the row's served P
  crosses 0.5, as "fair line" or "cal", in place of or beside the sim's number. Or label the sim's number
  "sim" when a calibration is in force.
  - The rows on the card already hold that crossing. For Notre Dame @ Florida, P(under) is 0.543 at 138.5,
    still above 0.5, so the crossing is below 138.5.
  - Display-only, so it does not split #816's pre-registered 7-day grade (11-17..11-23), which reads served P.
- **Owner:** lane `ncaab-total-overprojection` (#816, OPEN, session b1d2088f). Hand-off at the daily summary.
