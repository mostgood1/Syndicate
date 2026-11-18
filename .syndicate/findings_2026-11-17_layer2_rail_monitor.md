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

## Reading 7 — Tue 11-17 4:37 PM CST (22:37Z), full page

**Fleet:** unchanged since reading 6. Web on `25fc2e4f0`; refresh-worker 28948 and live-odds-worker 28949 on
the 3:52 PM `up` (`91d865fd5`). Host load 2.2.

**On main since reading 6, NOT loaded.** Each load is the owner's or the user's call.
- `64daca46f` serialise-once (lane board-query-serialize-once, todo #828). On the fleet's page response,
  measured by the owner: bytes and version identical; median server time 2,259 → 950 ms; peak 109.9 → 79.4 MB.
  This is the lead (a) that came out of my I-13.
- `920c19e70` WNBA box-score polls decided per date (#829, lane wnba-boxscore-polling-per-date). This is
  I-14's fix. The owner's checkpoint says the load is the user's call.
- `f1a278ed8` render-config step 3b: no code reads a `RENDER*` marker any more.

**Slate:** 2 live chips. NCAAB Notre Dame @ Florida H1 2:25; WNCAAB Army @ UMass Q2 2:52.

**Flags: 1 shown, 0 false, 0 missed, 0 dark.**
- NCAAB Notre Dame @ Florida u150.5, 9.8 pp (0.601 vs fair 0.503), ours 149.7. Ours is on the flag's side
  (I-17 check: agrees).
- 4 flagged rows lie behind the 1 shown flag.

**Live rows: 21, all NCAAB.** 10 priced <= 120 s; priced age p50 145 s, max 860 s; 6 over 300 s now.
0 markets without a price of ours.

**Overlay (29 min).** 0 gaps over 360 s.

| sport | builds | gap p50 / max | build s p50 / max | zero-card with rows |
|---|---|---|---|---|
| NCAAB | 33 | 38 s / **246 s** | 3.4 / **46.8** | 0 |
| WNCAAB | 36 | 45 s / 79 s | 1.1 / 12.9 | 36 of 36, all the value floor |

- **The 246 s NCAAB gap (22:09:45 → 22:13:51Z) is one slow build followed by a deferral.**
  - **22:10:14:** NCAAB built in 46.8 s, against p50 3.4 s. The same tick built 4 background dates in 26.3 s
    (ncaaf 11-19 / 11-20 / 11-21, soccer 11-20).
  - **22:11:30:** the next tick deferred NCAAB as slow (`deferred_slow ['ncaab']`).
  - **22:14:07:** the next NCAAB build took 4.7 s.
  - Host load was 5.0 at 22:10. A Serie A soccer artifact build was running at 108% CPU next to the
    refresh-worker's 113%.
  - One event. Watching whether it repeats under the evening load before calling it a defect.
- **Book-grid ticks:** 71, gap p50 22 s, max 57 s.

**Web merges:** fresh 23 / 23 for NCAAB and WNCAAB; 0 stale.

**Load (full page):**
- `/intelligence` 6.0 s / 4.38 MB wire / 23.0 MB raw.
- **Query 2.3 s / 4.05 MB wire / 22.0 MB raw** (warm; #827 form).
- Shortlist 1.5 s; chips 0.34 s; live-rail 0.02 s.
- Board built 94 s ago; query snapshot 1,735 s.
- Gunicorn workers 99 s and 29 s old: still recycling every few minutes (the I-2 recycle read is owed at the
  summary).

**#824:** 0 of 12 college `LIVE_GAMELINE_JOIN` lines since 22:08Z carry the reason. 0 college totals flags
below the points scored (0 of 1).

**Teams:** 0 chip-less, det1 / det2 / det3 0 / 0 / 0, 0 flipped, 0 truncated, 0 live chips without a live card.

**Restarts:** none.

### Improvement hunt, reading 7

- **Lead, not yet an item: a slow background build shares the tick with the live NCAAB build.** At 22:10:14
  one tick did both, and the NCAAB build ran 14× its median.
  - Not shown: that the background work, rather than host contention, caused the slow build.
  - The next readings check every NCAAB build over 20 s: what the same tick built in the background, and the
    host load.
  - If it repeats, the lead is to run background dates only on ticks with no live sport due, or after the
    live builds. Owner: whoever holds the book-grid tick (to name if it repeats).

## Reading 8 — Tue 11-17 5:01 PM CST (23:01Z)

**Fleet:** unchanged (web `25fc2e4f0`; workers 28948 / 28949, up 3,783 s). Host load 3.2.

**Slate:** 2 live chips. NCAAB Notre Dame @ Florida H2 18:42; WNCAAB Army @ UMass Q3 9:18. The 6 PM CST
wave has not tipped yet.

**Flags: 0 shown, 0 false, 0 missed, 0 dark.**

**Live rows: 7.** NCAAB 5 (1 priced <= 120 s); WNCAAB 2 (2). Priced age p50 225 s, max 535 s. 1 of 5
markets carries no price of ours.

**Live strip (`/api/board/live-rail`): 1 row.**
- Notre Dame @ Florida under 157.5 +104 at Polymarket (7 books quoting), P 0.561 vs fair 0.500.
- Book age 535 s, seen 178 s ago.
- **`live_total` 158.99 sits above the line of the under it carries: I-17's contradiction again.**

**Overlay (24 min).** 0 gaps over 360 s; 0 `deferred_slow`.

| sport | builds | gap p50 / max | build s p50 / max | zero-card with rows |
|---|---|---|---|---|
| NCAAB | 33 | 40 s / 91 s | 2.4 / 9.2 | 2 |
| WNCAAB | 34 | 36 s / 69 s | 0.5 / 3.5 | 34 of 34 |

- The 2 NCAAB zero-card builds (22:50:01, 22:50:39Z) refused every opportunity: value floor 28 / 30 and an
  implausible book 2. That is the decided floor (the user's "Keep the floor"). The WNCAAB ones are the floor
  too.
- **No NCAAB build over 20 s, so the reading-7 lead did not repeat.**
- **Book-grid ticks:** 72, gap p50 18 s, max 62 s.

**Web merges:** fresh 19 / 19 for NCAAB and WNCAAB.

**Load:**
- **Query 5.7 s / 4.24 MB wire / 23.1 MB raw.**
- Shortlist 0.66 s; chips 0.39 s; live-rail 0.02 s.
- Board built 60 s ago; query snapshot 3,169 s.
- Gunicorn workers 1,383 s and 466 s old: longer-lived than at 4:08-4:38 PM, when they recycled every
  few minutes.

**#824:** 0 of 16 college `LIVE_GAMELINE_JOIN` lines since 22:37Z carry the reason; 0 college totals flags.

**Teams:** 0 chip-less, det1 / det2 / det3 0 / 0 / 0, 0 flipped, 0 truncated, 0 live chips without a live card.

**Restarts:** none.

### Improvement hunt, reading 8

**I-17 is wider than the rail card.** The sim's number is shown on two surfaces:
- the rail card's "ours" (`syndicate/templates/intelligence.html:3557`, `final.total ?? row.live_total`);
- the board table's **Live** column, live rows only (`intelligence.html:4908`,
  `live_projection ?? live_total`).

Both sit next to a calibrated college total probability. The owner's fix should cover both. Hand-off to
lane ncaab-total-overprojection at the summary.

- **I-17 HANDED OFF 5:10 PM CST (23:10Z)** (user: "hand I-17 to the #816 lane now").
  - **Sent to:** lane ncaab-total-overprojection, session b1d2088f. Its transcript's custom title is
    "Layer 2 Game Rail monitoring", so it is local_1f10ce63.
  - **Delivery:** SendMessage queued (message 874cd0ab); read not confirmed.
  - **What was sent:**
    - the 23-of-74 count and the examples;
    - the two surfaces (`intelligence.html:3557` rail card "ours", `:4908` board table Live column);
    - two per-line, display-only fixes: a "cal" line where served P crosses 0.5, or a "sim" label when a
      calibration is in force;
    - that neither changes served P, so #816's 7-day grade is not split.
  - **The file:** the only open lane naming `intelligence.html` is dh-state-aware-pairing, scoped to the
    doubleheader functions.
  - Until the owner answers, the monitor keeps counting I-17 at each reading.

## Reading 9 — Tue 11-17 5:27 PM CST (23:27Z) — the wave starts, and a deploy drain freezes the board

**Fleet changes since reading 8 (other lanes, each in deploys.md):**
- **23:15:44Z:** ff `25fc2e4f0` → `64daca46f` + `reload-web`. Board query serialise-once, #828 (lane
  board-query-serialize-once-load); MET.
- **23:22:26Z:** live-odds-worker TERM at `64daca46f`, loading #829's live-capture half (lane
  wnba-boxscore-polling-per-date, user "Load it"). New pid 52087. `WNBA_LIVE_BOX_SKIPPED` on its first tick.
- The refresh-worker 28948 still runs `91d865fd5`.
- **The I-2 recycle reading now has two windows:**
  - 21:56:26Z → 23:15:44Z, #827 only (the de-dup owner gave the start; its deploys entry counts 19 recycles in
    78 min);
  - after 23:15:44Z, #827 + #828.

  Each window's baseline is taken inside that window.
- **I-17 accepted** by lane ncaab-total-overprojection (`ef4163bb5`; the user chose the calibrated total).

### ANOMALY: a refresh-worker deploy drain has held the Layer 2 board since 23:14Z

- **Who and when:** `deploy_drain.json` (fleet Redis, data root): owner **ncaaf-grid-build-speed**, reason
  `check_deploy_safety --drain`.
  - Requested **23:09:26Z** (5:09 PM CST); **expires 01:39:26Z** (7:39 PM CST), a 2.5 h lifetime.
  - The same lane holds the refresh-worker claim (acquired ~23:08Z).
- **The worker is ready:** `worker_drain_state_refresh-worker.json` shows `acked_drain_at` 23:30:27Z and
  `in_flight {"mlb_sim": false}`. It is idle and waiting for the TERM.
- **What has stopped:**
  - Every board build since 23:14:42Z logs `DEFERRED_BOARD_BUILD reason=deploy_drain_requested` (13 by 23:29Z).
  - `LAYER2_TODAY_CADENCE ran=held age_before_s=1764 limit_s=300` at 23:30:11Z.
  - The last today board was published 23:02:14Z (2,741 candidates). The 23:13:09Z build (522 s wall) was the
    11-18 board.
  - The board-loop `PORTFOLIO_EXECUTED` (mode=paper) last ran 23:12:01Z.
  - `DRAIN_HOLD stage=mlb_sim_tick` every ~35 s.
- **What has NOT stopped:** the in-play overlay. In 26 min: NCAAB 31 builds, WNCAAB 28, NCAAF 20; every gap
  under 145 s; web merges fresh 61 / 61 / 51. The live rows on the cards stay fresh.
- **Handed off at 23:31Z** to the claim holder's session, local_208683f1. Transcript 0f519972's custom title
  is "Layer 2 rail: live edge line, highlight and filter". Message 20522098 is queued; read not confirmed.
  - **Asked:** TERM now, since the worker is idle, or clear the drain until ready.
  - Nothing touched by me.

### The reading

**Slate: 11 live chips.**
- NCAAB 4: Notre Dame @ Florida H2 8:50; St. Peter's @ UMass Lowell; SIU @ Liberty; Marist @ Army.
- NCAAF 1: Eastern Michigan @ Western Michigan, Q1.
- WNCAAB 6.

**Flags: 4 shown, 0 false, 0 missed, 0 dark.**
- NCAAB Notre Dame @ Florida u161.5, 11.9 pp; ours 161.5, on the line itself.
- NCAAB Marist @ Army u132.5, 3.8 pp; **ours 137.7, on the other side (I-17)**.
- NCAAB St. Peter's @ UMass Lowell ML UML, 5.8 pp.
- WNCAAB Tennessee St @ Louisville u149.5, 14.2 pp; ours 144.6, agrees.
- **I-17 this reading: 1 of 3 totals flags contradicts its "ours"**, plus 1 tie.

**Live rows: 97.** 36 priced <= 120 s; 26 over 300 s now; priced age p50 156 s.

**13 of 28 live markets carry no price of ours:**
- **WNCAAB 7, all fresh in-play rows (67-250 s).**
  - h2h 4: heavy favourites −400 to −1,900.
  - Full-game totals 3.
- **6 live markets display a PREGAME shortlist quote as their book** (`source=layer2_shortlist`, no in-play
  row for that market):
  - NCAAF Eastern Michigan @ Western Michigan: spread EM +17.5 (971 s), ML WM −800 (1,287 s), 1H spread
    EM +10.5, and 1H total 23.5 (1,032 s);
  - NCAAB Marist @ Army: spread **ARMY −1 at 26,035 s (7.2 h)** and 1H spread MRST +0.5 (2,367 s).
  - No flag can fire on these, since there is no price of ours. The cards carry the age.

**Team cards: 1 flipped.**
- The NCAAB card is titled **"Liberty Flames @ Southern Illinois Salukis"** (the odds feed: home SIU). Its chip
  (ESPN 401920953) is **"Southern Illinois @ Liberty"** (home Liberty).
- The card carries only totals (full + 1H), which are symmetric in home/away, so no price on it depends on
  the orientation.
- 0 chip-less, det1 / det2 / det3 0 / 0 / 0, 0 truncated, 0 live chips without a live card.

**Overlay (26 min).** 0 gaps over 360 s; 0 `deferred_slow`.

| sport | builds | gap p50 / max | build s p50 / max | zero-card with rows |
|---|---|---|---|---|
| NCAAB | 31 | 51 s / 89 s | 5.4 / **22.4** | 0 |
| WNCAAB | 28 | 64 s / 123 s | 1.6 / 7.5 | 2 |
| NCAAF | 20 | 70 s / 145 s | 1.6 / 11.9 | 0 |

- **Reading 7's lead is weakened.** 3 NCAAB builds took over 20 s (23:06:58 20.8 s, 23:08:28 22.4 s,
  23:09:21 22.2 s), and **2 of the 3 had no background build in the same tick**. The NCAAB slate is now 57
  games. No deferral followed.
- **Book-grid ticks:** 64, gap p50 18 s, max 90 s. Host load 4.2.

**Load (#827 + #828 on web):**
- **Query 3.8 s / 4.25 MB wire / 23.0 MB raw.**
- Shortlist 1.8 s; chips 0.05 s; live-rail 0.03 s (70-92 rows).
- Board built 900 s ago (the drain); query snapshot 1,644 s.
- Gunicorn workers 96 s and 27 s old.

**#824:** 0 of 2 college `LIVE_GAMELINE_JOIN` lines since 23:01Z carry the reason. 0 college totals flags below
the points scored (0 of 3).

### Improvement hunt, reading 9

| # | improvement | evidence | owner | next step |
|---|---|---|---|---|
| I-18 | **A deploy drain can freeze the board for its whole 2.5 h lifetime** once the worker has acked and gone idle. Lead: an idle-acked drain with no TERM should alarm after N minutes, or expire well under 2.5 h. | Above: requested 23:09:26Z, acked idle, board held 16+ min of the evening wave, expiry 01:39:26Z. | `check_deploy_safety.py --drain` (to name the lane at the summary); the holder now | First, the holder's TERM. Then measure how long past drains sat acked-idle. |
| I-19 | **Live cards show a pregame shortlist quote as the market's book** when no in-play row exists for that market (6 of 28 live markets, up to 7.2 h old). | Above. | Rail lane (local_208683f1), or a display decision for the user | Count it every reading tonight; find whether the card marks it as pregame. |
| — | Flipped card (Liberty / SIU): the odds feed and ESPN disagree on home/away. Totals only, no price depends on it. | Above. | Rail team-card matching | Count it every reading; any side market on such a card would matter. |

## Reading 10 — Tue 11-17 5:50 PM CST (23:50Z), full page — the drain is over; the evening board build runs 9 min

**The r9 anomaly is CLOSED.**
- The holder (local_208683f1) **cleared the drain at 23:33:29Z** after a ~24 min hold. It said odds-refresh
  child jobs kept starting under the drained worker, so the idle window never came.
- A today board published 23:39:54Z (`LAYER2_TODAY_CADENCE ran=yes age_before_s=1980`).
- It re-drained at ~23:40:30Z for one 300 s attempt, then **ABORTED the load at 23:46Z; nothing loaded**
  (`5f70b8af3`). The drain key reads `cleared`. refresh-worker is still pid 28948 on `91d865fd5`.
- **Board gap: the today board went 23:02:14Z → 23:39:54Z (37.7 min) without a publication.**
- Next today board: 23:49:40Z (2,768 candidates).
- **I-18 refined:** the drain stops the board but not the odds-refresh child jobs, so a preflight that waits
  for 0 jobs may never clear in the live evening. The holder now caps its wait at 5 min and will message
  the monitor before draining again.

**Fleet:** web `64daca46f`; live-odds-worker 52087 (`64daca46f` code); refresh-worker 28948 (`91d865fd5`).
Host load 2.4-4.4.

**Slate:** 12 live chips. NCAAB 5 (Lipscomb @ Purdue tipped); NCAAF Eastern Michigan @ Western Michigan
Q2; WNCAAB 6. NBA/NHL not yet live.

**Flags: 6 shown, 0 false, 0 missed, 0 dark.**
- NCAAB Notre Dame @ Florida u164.5, 8.1 pp; ours 163.3, agrees.
- NCAAB St. Peter's @ UMass Lowell UML −1.5, 7.7 pp; ours UML −2.5.
- NCAAB Marist @ Army u149.5, 5.6 pp; **ours 151.6, on the other side (I-17)**.
- NCAAF Eastern Michigan +21.5, 6.5 pp; ours EM +19.9.
- NCAAF o55.5, 6.0 pp; ours 60.2.
- **WNCAAB Tennessee St @ Louisville u162.5, 32.4 pp**: model 0.8235 = 14/17, a raw sim-count fraction
  (WNCAAB stays raw under #816's gate), vs fair 0.500; ours 152.7. Priced 84 s. Grade it at the final.
- **I-17 this reading: 1 of 3 college totals flags contradicts its "ours".**

**Live rows: 111.** 37 priced <= 120 s; 32 over 300 s; priced age p50 178 s, max 866 s.
- 10 of 32 markets carry no price of ours.
- **I-19: 6 live markets carry only pregame-shortlist rows**, all checked within 102-155 s of the read (the
  board had just rebuilt):
  - St. Peter's @ UMass Lowell ML SPU −108;
  - SIU @ Liberty spread SIU +4.5 and ML LIB −220;
  - Marist @ Army ML MRST +290;
  - WNCAAB NKU @ EKU ML EKU −9,900 and Fordham @ Campbell ML FOR −1,900.
  - Reading 9's 7.2 h Marist spread is gone.

**Team cards:** 0 flipped this reading (SIU @ Liberty at HALF); det1 / det2 / det3 0 / 0 / 0; 0 chip-less.

**Overlay (23 min).** 0 gaps over 360 s; 0 `deferred_slow`.

| sport | builds | gap p50 / max | build s p50 / max |
|---|---|---|---|
| NCAAB | 21 | 66 s / 88 s | 6.6 / 31.2 |
| WNCAAB | 23 | 57 s / 103 s | 2.4 / 8.8 |
| NCAAF | 16 | 75 s / 165 s | 2.0 / 8.8 |

- **Ticks:** 43, gap p50 30 s, max 96 s. Web merges fresh 52 / 52 / 52.
- **NCAAB builds over 20 s:** 4 (23:35:10 31.2 s, 23:36:02 20.3 s, 23:47:00 30.0 s, 23:47:37 23.5 s). Only 1
  had background work in the tick. **Reading 7's background-sharing lead is CLOSED:** 2 of 3 (r9) and 3 of 4
  (r10) slow builds had none. They fit I-20 below.

**Load:**
- `/intelligence` **11.3 s** / 4.72 MB wire / 24.7 MB raw (6.0 s at r7).
- **Query 3.7 s / 4.31 MB wire / 23.3 MB raw.**
- Shortlist 1.0 s; chips 0.56 s; live-rail 0.02-0.06 s (121-122 rows).
- Board built 85 s ago; query snapshot 2,385 s.

**#824:** 0 of 6 college `LIVE_GAMELINE_JOIN` lines since 23:27Z carry the reason. 0 college totals flags below
the points scored (0 of 3).

### Improvement hunt, reading 10

**I-20: in the live evening the Layer 2 board build runs 5-16 min against its 300 s today cadence.** Every
stage slows together and the process CPU equals the wall time.

**Measured** (`BOARD_BUILD_TIMING` and `BUILD_SPAN_EXIT`, refresh-worker.log):

| build | wall | cpu | intelligence overview | shortlist | portfolio commit | tail |
|---|---|---|---|---|---|---|
| 22:41:56-22:43:18Z (calm) | 82 s | 84 s | 1.4 s | 51 s | 12.6 s | ~15 s |
| 23:04:42-23:13:09Z (the 11-18 board, 253 candidates) | 522 s | 569 s | 51 s | 368 s | 17 s | ~75 s |
| 23:40:47-23:49:39Z | 542 s | 601 s | **42 s (30×)** | **204 s (4×)** | **123 s (10×)** | ~180 s |

- **Monday evening the same:** 100-200 s until 23:50Z, then 345 / 395 / **942** / 592 / 739 / 559 s from
  00:16 to 02:05Z, then 160-335 s.
- **The mechanism is known: the interpreter-lock convoy.** Lane nba-overlay-card-cost, CLOSED 11-16, found
  that the refresh-worker runs at the one-core ceiling all day, so the board-build thread shares one
  interpreter with the live book-grid / overlay tick. `off_cpu_pct` −9 to −11 tonight says the process is
  busy, not waiting. That lane's lever (check once per build, `a39058946`) is loaded; the convoy itself stays.
- **Cost:** in the live evening the pregame board, its shortlist cadence and the board-loop portfolio refresh
  every ~9-16 min, not every ~3 min. The NCAAB grid builds stretch too: 20-31 s, against a 5-7 s p50.
- **Lever (not built):** run the board build and the live tick in separate processes, so they stop sharing one
  interpreter. Architectural, so it is a session of its own.
- **Owner:** none open. The convoy lane is closed, and no todo item proposes the split.

## Reading 11 — Tue 11-17 6:17 PM CST (00:17Z 11-18) — the college peak

**Fleet:** unchanged. Web `64daca46f`; live-odds-worker 52087; refresh-worker 28948 (`91d865fd5`). Host load
3.3-4.1. No drain.

**On main, NOT loaded:**
- `923869cf3` (17:46): college totals show the CALIBRATED total as "ours". This is the I-17 fix, lane
  ncaab-total-overprojection; the user chose "A: calibrated total". A load is a web reload.
- `882a64d5a`: #829's live half MET, measured by its owner (the WNBA share of web requests 40.1% → 0.8%).

**Slate: 50 live chips.** NCAAB 25, NCAAF 3, NHL 5 (P1), WNCAAB 17. NBA not tipped.

**Flags: 36 shown, 0 false, 0 missed, 0 dark.** 24 of 50 live cards carry a flag.
- **I-17 at peak:** 20 NCAAB full-game totals flags, **all unders**. **12 of 20 show "ours" on the other side
  of the line:**
  - Norfolk St @ Georgia Tech u148.5 at 153.0;
  - CSUN @ Troy u155.5 at 159.5;
  - Tennessee St @ USF u169.5 at 171.7;
  - ETSU @ Marshall u137.5 at 142.8;
  - Cleveland St @ Xavier u152.5 at 158.3;
  - Monmouth @ Wake u144.5 at 148.8;
  - Fordham @ Manhattan u141.5 at 146.9;
  - Rider @ Miami u142.5 at 143.2;
  - Lehigh @ Mt. St. Mary's u143.5 at 148.3;
  - Wagner @ St. Joseph's u144.5 at 148.5;
  - Akron @ Bucknell u143.5 at 145.0;
  - Central Michigan @ Dayton u149.5 at 154.2.

  WNCAAB 0 of 3. The fix that ends this is on main, not loaded.
- **Graded at the final:** WNCAAB Tennessee St @ Louisville. Now u154.5, 23.5 pp (model 0.730); at r10
  u162.5, 32.4 pp.

**Live rows: 667.** 234 priced <= 120 s; 181 over 300 s; priced age p50 193 s.
- By sport: NCAAB 520 (201 <= 120 s, 72 flagged); WNCAAB 78 (29, 3); NCAAF 60 (**0** <= 120 s); NHL 9 (4).
- **NCAAF:** 0 of 60 rows priced within 120 s. Book age p50 235 s, min 141 s; seen age p50 130 s. To watch.
- 21 of 151 live markets carry no price of ours.
- **I-19: 22 of 151 live markets carry only pregame-shortlist rows** (r9 6 of 28, r10 6 of 32).

**Team cards:** 0 flipped, det1 / det2 / det3 0 / 0 / 0, 0 chip-less, 0 live chips without a live card.

**Overlay (27 min).** 0 gaps over 360 s; 0 `deferred_slow`.

| sport | builds | gap p50 / max | build s p50 / max | zero-card with rows |
|---|---|---|---|---|
| NCAAB | 33 | 49 s / 77 s | 7.2 / 20.0 | 0 |
| WNCAAB | 28 | 57 s / 91 s | 1.6 / 7.5 | 0 |
| NCAAF | 23 | 59 s / 155 s | 1.4 / 5.9 | 0 |
| NHL | 8 | 96 s / 126 s | 3.8 / 23.1 | 1 |

- **Ticks:** 60, gap p50 22 s, max 81 s.
- **Web merges:** fresh NCAAF / NCAAB / WNCAAB 57 / 57 / 57, NHL 14; 0 stale. No NCAAB build over 20 s.

**Board builds since the drain:**
- 153 s (23:56Z), 124 s, 242 s, 253 s, 250 s (00:17:48Z). All under the 300 s today limit, but 1.5-3× the calm
  82 s.
- **I-20 corrected:** the two 520-540 s builds (23:13Z and 23:49Z) bracket the drain. The second was the first
  build after the 38-min hold. Monday's 345-942 s evening builds (00:16-02:05Z) had no drain. Tonight's peak
  past 7 PM is still to read.

**Load:**
- **Query 8.1 s / 4.53 MB wire / 24.3 MB raw.**
- Chips 1.5 s; shortlist 0.67 s; live-rail 0.09-0.34 s (740 rows, 700 KB raw).
- Board built 117 s ago; query snapshot 3,994 s (as of 23:11:20Z; the state loop refreshes it about hourly,
  as all day).

**#824:** 0 of 12 college `LIVE_GAMELINE_JOIN` lines since 23:50Z carry the reason. 0 of 23 college totals
flags below the points scored.

### Improvement hunt, reading 11

**I-21 (lead): the NHL in-play overlay drops its props for one build. At the same moment the latest-quote
cache is thrashing.**

- **The drop, measured:**
  - The NHL `INPLAY_OVERLAY` `rows_inplay` since puck drop: 20, 20 (pre-props), 770, 770, 770, **20** (00:14:30Z,
    6 cards), 755, 755, 760.
  - The web merged NHL 283 → **6** (00:15:00Z) → 277 (00:15:37Z). So the live NHL props left the board for one
    merge, ~37 s.
- **The cache, measured:** `[odds_book_quotes] LATEST_CACHE_EVICT` (budget 250 MB) evicts 7-15 shard files at
  a time, every ~5 min: 00:08:57, 00:13:58-00:14:42, 00:19:39Z.
  - The files include **the live sports' own today shards**: NCAAB 2026-11-17 at 00:13:58 (19,920 rows) and
    00:19:39 (21,315 rows); NBA 2026-11-17 (29,458); **NHL 2026-11-17 at 00:14:08 (12,542 rows), 22 s before
    the 20-row NHL build**.
- **Not shown:**
  - that the eviction causes the drop. n = 1, and the NHL quote read at 00:14:25 was `mode=incremental` and
    healthy;
  - that the thrash costs the convoy (I-20) measurable CPU.
- **Next:** at each reading, count the NHL 20-row builds and the evictions that precede them. The idea: size
  the budget or the eviction order (oldest dates first) so the live sports' today shards are not evicted. Owner
  to name at the summary.

## Reading 12 — Tue 11-17 6:45 PM CST (00:45Z 11-18), full page — NBA tips

**Fleet:** unchanged. Web `64daca46f`; live-odds-worker 52087; refresh-worker 28948. Host load 5.0. No drain.
I-17 fix `923869cf3` still not loaded.

**Slate: 61 live chips.** NCAAB 30, WNCAAB 20, NHL 7, NCAAF 3, NBA 1 (Knicks @ Raptors).

**Flags: 50 shown, 0 false, 0 missed, 0 dark.** 31 of 61 live cards carry a flag.
- **NCAAB:** spreads 18, h2h 2, full-game totals 20, all unders. **I-17: 10 of 20 contradict "ours"**, for
  example:
  - Jacksonville St @ Louisiana u122.5 at 130.9;
  - Green Bay @ West Florida u149.5 at 153.7;
  - Wagner @ St. Joseph's u144.5 at 148.7.
- **WNCAAB:** totals 5, 0 contradict.
- **NCAAF:** 4 (Ball St @ Ohio spread / total / ML; EMU @ WMU o57.5).
- **NBA:** 1 (Knicks @ Raptors o214.5, 4.9 pp, priced 64 s).
- **To grade at the final:**
  - **Villanova @ Pittsburgh ML PITT, 24.4 pp** (0.694 vs fair).
  - WNCAAB Tennessee St @ Louisville. It is at Q4 4:25; the book line fell 162.5 (r10) → 154.5 (r11) →
    130.5 (now; u130.5, 15.0 pp, ours 129.0).

**Live rows: 1,137.**
- 270 priced <= 120 s; 395 over 300 s; priced age p50 201 s.
- By sport:

| sport | rows | priced <= 120 s | flagged |
|---|---|---|---|
| NCAAB | 687 | 215 | 81 |
| NBA | 317 | **1** | 1 |
| WNCAAB | 77 | 31 | 9 |
| NCAAF | 35 | 9 (r11: 0 of 60) | 4 |
| NHL | 21 | 14 | 0 |

- **NBA in-play rows on the cards are alternates** (totals_alt full / 1H / quarters, spreads_alt). Book age p10
  **200 s**, p50 214 s; seen p50 179 s. So almost no NBA row can carry a fresh-priced flag. Consistent with
  I-4 (NBA alt flags lose regardless of age).
- 28 of 180 live markets carry no price of ours.
- **I-19: 17 of 180 live markets carry only pregame-shortlist rows.**

**Team cards:** 0 flipped, det1 / det2 / det3 0 / 0 / 0, 0 chip-less, 0 live chips without a live card.

**Overlay (28 min).** 0 gaps over 360 s; 0 `deferred_slow`.

| sport | builds | gap p50 / max | build s p50 / max |
|---|---|---|---|
| NCAAB | 33 | 47 s / 90 s | 7.4 / 36.1 |
| WNCAAB | 33 | 49 s / 114 s | 0.9 / 9.2 |
| NHL | 26 | 55 s / 173 s | 3.9 / 16.7 |
| NCAAF | 18 | 83 s / 165 s | 1.5 / 4.8 |
| NBA | 4 | 38 s / 53 s | 7.1 / 16.3 |

- **Ticks:** 80, gap p50 17 s, max 85 s. Web merges fresh: 72 lines for every sport, NBA 7; 0 stale.
- **NBA overlay:** 929-937 rows in play, 805-814 cards, elapsed 0.9-11.4 s.
- **NCAAB builds over 20 s:** 3 (25.8 / 26.6 / 36.1 s), none with background work.

**Board builds since 00:17Z: 250, 155, 185, 191, 173, 256, 208 s.** All under 300 s; `off_cpu_pct` −2.4 to
+1.9.

**Load (full page):**
- `/intelligence` 5.5 s / 5.77 MB wire / 31.0 MB raw.
- **Query 9.2 s / 4.70 MB wire / 25.3 MB raw.**
- **Chips 3.1 s** (0.05-1.5 s earlier). Shortlist 0.94 s.
- Live-rail 0.13-0.25 s (1,251 rows, 1.18 MB raw).
- Board built 77 s ago.
- Both gunicorn workers 42-46 s old.

**#824:** 0 of 12 college `LIVE_GAMELINE_JOIN` lines since 00:17Z carry the reason. 0 of 25 college totals flags
below the points scored.

### Improvement hunt, reading 12

**I-21 re-read: the NHL in-play overlay drops its props for 1-2 builds about every 10 min. The cache-eviction
cause is FALSIFIED as the general explanation.**

- **The drops (`rows_inplay` → cards):**
  - 00:14:30 (20 → 6);
  - **00:21:46 (36 → 1) and 00:22:41 (44 → 7)**: the web merged NHL 272 → **1** → 7 → 180, ~80 s;
  - **00:34:32 (23 → 7).**

  The builds between them carry 464-791 rows.
- **The evictions:** an NHL `LATEST_CACHE_EVICT` came 22 s before the first drop only. None between 00:17 and
  00:37Z, so the eviction preceded **1 of 4** drop builds.
- **Separately:** between 00:24 and 00:35Z the NHL cards fell 180 → 6-21 while rows stayed 464-624.
  Opportunities fell 288 → 36-63, which is the selection (value floor), not a drop.
- **Next lead:** the NHL live-props quote capture cadence, if props rows age out of the in-play window between
  captures. Read the live-odds-worker's NHL props pulls against the drop times at the next reading.
  - **Effect:** the live NHL props leave the board for ~30-80 s at a time. The game lines stay.

## Reading 13 — Tue 11-17 7:11 PM CST (01:11Z 11-18)

**Fleet:** unchanged. Web `64daca46f`; live-odds-worker 52087; refresh-worker 28948. **Host load 7.0-7.6.**
- Top CPU: refresh-worker 89%; an NBA ESPN live-status fetch 80%; live-odds-worker 56%; `kalshi_combo_capture`
  40% (nice 19); two live re-sim servers 38% each (nice 5); an M3 rehearsal `m3_launch.py` 16% (nice 19).
- **Scheduled:** the user moved lane ncaaf-grid-build-speed's refresh-worker load (`3f337b2d9`, #809 memo) to
  **after 1:10 AM CST**. A background script tries from 07:10Z: up to 4 capped attempts, each holding the board
  at most 5 min. No drain before then.

**Slate: 69 live chips.** NCAAB 37, WNCAAB 19, NHL 9, NCAAF 3, NBA 1.

**Flags: 47 shown, 0 false, 0 missed, 1 dark.** The dark one: Charlotte @ Davidson ML away, gap 3.4 pp; priced
28 s, now 531 s old.
- **I-17:** NCAAB full-game totals 15 (all unders), **3 contradict "ours"**. WNCAAB 1 over contradicts "ours"
  (raw model; outside #816's fix).
- **Notable flags:**
  - NBA Knicks @ Raptors o209.5, 13.9 pp; ours 221.1.
  - NCAAB Illinois @ Duke 2H u88.5, 21.0 pp.
  - WNCAAB SMU @ Kansas St o111.5, 17.8 pp.
  - WNCAAB Tennessee @ Belmont u150.5, 16.6 pp.
- **Villanova @ Pittsburgh** (H2 15:52): the 24.4 pp ML PITT flag of r12 is gone. Now PITT −3.5 (8.1 pp) and
  u151.5 (9.4 pp). Grade at the final.

**Live rows: 1,165.** 260 priced <= 120 s; **737 over 300 s now**; priced age p50 246 s.
- By sport:

| sport | rows | priced <= 120 s |
|---|---|---|
| NCAAB | 772 | 203 |
| NBA | 267 | **4** |
| NCAAF | 51 | 16 |
| NHL | 33 | 20 |
| WNCAAB | 42 | 17 |

- 42 of 209 live markets carry no price of ours. Priced age max 39,585 s (a pregame shortlist row, I-19).

**Team cards:** 0 flipped, det1 / det2 / det3 0 / 0 / 0, 0 chip-less, 0 live chips without a live card.

**Overlay (26 min).** 0 gaps over 360 s; 0 `deferred_slow`.

| sport | builds | gap p50 / max | build s p50 / max |
|---|---|---|---|
| NBA | 26 | 58 s / 126 s | 10.0 / 24.8 |
| NCAAB | 24 | 63 s / 97 s | 10.4 / **43.7** |
| WNCAAB | 21 | 70 s / 127 s | 1.4 / 13.4 |
| NHL | 14 | 97 s / **203 s** | 5.9 / 17.8 |
| NCAAF | 17 | 90 s / 158 s | 2.4 / 6.7 |

- **Ticks:** 60, gap p50 23 s, max 75 s. Web merges fresh 53 / 53 for every sport.
- NCAAB builds over 20 s: 3 (23.0 / 43.7 / 37.8 s), none with background work.

**Board builds:**
- 207, 242, 226 s, then **346 s (01:04:00Z, over the 300 s today limit)**.
- The build in progress at 01:07Z had spent **90.7 s in the intelligence overview** (1.4 s calm).
- Board built 503 s ago at the read. **I-20 holds at the 7 PM wave.**

**Load:**
- **Query 15.9 s** / 4.77 MB wire / 25.5 MB raw.
- **Chips 4.0 s; shortlist 2.9 s.** Live-rail 0.16-0.34 s (1,303 rows, 1.2 MB raw).
- Both gunicorn workers 215-292 s old.

**#824:** **1 of 8** college `LIVE_GAMELINE_JOIN` lines since 00:45Z carries
`model_projected_final_below_points_scored`: the day's first NCAAB refusal I have seen. 0 of 23 college totals
flags below the points scored.

### Improvement hunt, reading 13

**I-21 → I-22: the NHL props drops follow the live odds lane's long runs. That lane runs one refresh at a time,
and in the evening half its sweeps are refused.**

- **Measured:** `[live_refresh_loop] ODDS_SWEEP_LAUNCHED` / `ODDS_SWEEP_REFUSED`, live-odds-worker.log, 00:00-01:10Z.
  - **34 sweeps launched, 17 refused** `reason=lane_busy` ("A refresh run is already active").
  - Runs inferred from the busy `run_stamp`s:

| run | lasted (to the next accepted sweep) |
|---|---|
| 00:14:10 | **~8.3 min** (refused through 00:21:15) |
| 00:24:39 | ~2.4 min |
| 00:32:56 | ~3.8 min |
| 00:41:44 | ~2.5 min |
| 00:48:39 | **~10.7 min** (refused through 00:58:00) |
| 00:59:19 | ~6.7 min (no launch between 01:00:31 and 01:06:01) |

- **The NHL props drops sit inside or at the end of those runs:**
  - 00:21:46-00:22:41: end of the 8.3-min run;
  - 00:55:10-00:58:40: inside the 10.7-min run;
  - 01:05:17-01:06:38: inside the 6.7-min gap;
  - 00:14:30: right after a 5.5-min gap;
  - 00:34:32: right after a 4.6-min gap.

  That is **5 of 5 drop episodes**. Two gaps of 4.5-5.0 min had no drop. So a drop needs ~6+ min without a
  completed odds run: the props rows age out of the overlay's in-play window.
- **Wider than NHL:** in those windows every live sport's quotes age together. That fits 737 of 1,165 live rows
  being over 300 s at 01:11Z, and the NBA rows' 200 s+ quote ages.
- **Lead (not built; the OddsAPI call budget applies):** split the live odds lane, or bound a run's length, so
  one slow sport cannot hold every live sport's refresh for 8-11 min.
  - First, find what made the 00:14:10 and 00:48:39 runs long: the run's per-sport job times.
  - Owner: the live-odds-worker `live_refresh_loop` (to name at the summary).

## Reading 14 — Tue 11-17 7:39 PM CST (01:39Z 11-18) — the evening peak overloads the refresh-worker

**Fleet:** unchanged. Web `64daca46f`; live-odds-worker 52087; refresh-worker 28948.

**A second drain, recorded by its owner (deploys.md 01:08Z, `35c366025`):** lane ncaab-total-overprojection
tried to load I-17's `923869cf3` ("Try now anyway").
- It held four capped drains, 01:08-01:28Z (~20 min). Every one was NOT CLEAR (`board_build=in_flight`).
- It ABORTED and loaded nothing. Claims released 01:29:47Z.
- Same lesson as the 23:46Z abort: in the live evening this worker has no idle window.

**Slate: 74 live chips.** NCAAB 40, WNCAAB 19, NHL 9, NBA 3, NCAAF 3.

**Flags: 65 shown, 0 false, 0 missed, 3 dark.** 39 of 74 live cards carry a flag.
- **Dark:**
  - Illinois @ Duke 2H spread ILL +7, 10.9 pp;
  - Seton Hall @ Auburn ML away, 3.7 pp;
  - Edmonton @ Florida spread FLA +2.5, 4.6 pp.

  All priced fresh (23-119 s), now 607-702 s old.
- **I-17:** NCAAB full-game totals 26 (all unders), **10 contradict "ours"**. **WNCAAB 2 of 5 contradict**: FGCU
  @ South Carolina u174.5 at 24.9 pp, ours 175.8, so the raw model contradicts too.
- **Large gaps:**
  - CSUN @ Troy TROY −9.5 **30.7 pp** (0.807; ours TROY −18.6);
  - Lehigh −25.5 24.9 pp;
  - WNCAAB FGCU u174.5 24.9 pp and Mt. St. Mary's @ Nebraska u153.5 23.1 pp.
- **NBA:** 5 flags across Pistons @ Spurs, Blazers @ Wolves, Knicks @ Raptors, priced 75-113 s.
- **Villanova @ Pittsburgh** (H2 6:15): now VILL +10.5 (11.8 pp) and u147 (11.7 pp).

**Live rows: 1,752.** 326 priced <= 120 s; **1,199 over 300 s now (68%)**; priced age p50 304 s. 36 of 230 live
markets carry no price of ours.

| sport | rows | priced <= 120 s |
|---|---|---|
| NBA | 880 | 23 |
| NCAAB | 789 | 267 |
| WNCAAB | 39 | 15 |
| NCAAF | 24 | 5 |
| NHL | 20 | 16 |

**Team cards:** 0 flipped, det1 / det2 / det3 0 / 0 / 0, 0 chip-less, 0 live chips without a live card.

### The degradation (28 min, 01:11-01:40Z)

**Book-grid ticks:** **21** (60-80 in earlier readings' windows). Gap p50 65 s; max 206 s and 212 s.
`deferred_slow`: NBA 3, NHL 1, NCAAB 1.

| sport | build s p50 / max | overlay builds | gap p50 / max | gaps over 360 s |
|---|---|---|---|---|
| NBA | **51.5 / 107.1** | 6 | **342 s / 498 s** | **2** |
| NCAAB | **35.4 / 64.1** | 10 | 147 s / **453 s** | **1** |
| NHL | **34.3 / 87.7** | 4 | 177 s / 316 s | 0 |
| WNCAAB | 7.3 / 20.7 | 12 | 133 s / 215 s | 0 |
| NCAAF | 4.7 / 12.8 | 11 | 144 s / 242 s | 0 |

**Web merges: stale 19 of 36 lines** (NHL 11, NBA 5, NCAAB 3).
- NBA `stale_374s`..`469s` (01:22-01:32Z);
- NCAAB `stale_374s`..`438s` (01:31-01:33Z);
- **NHL `stale_405s`..`666s`** (01:18-01:40Z; the NHL overlay was last written ~01:29Z).

A stale overlay is dropped at merge, so in those minutes the board serves those games' live rows from the
shortlist.

**The board build: 1,510 s (25.2 min), 01:05:38-01:30:47Z.**

| span | this build | calm (22:41Z) |
|---|---|---|
| intelligence overview | 91 s | 1.4 s |
| `layer2_shortlist_build` | **633 s** | 51 s |
| `portfolio_commit` | **226 s** | 12.6 s |
| tail | ~531 s | ~15 s |

- `off_cpu_pct` 0.2: computing, not waiting.
- The previous build: 346 s (01:04:00Z). **The today board went 01:04:00 → 01:30:47Z (26.8 min) without a
  publication.**
- At the read: board 583 s old; **query 16.3 s** / 5.00 MB wire / 26.7 MB raw; chips 3.5 s; shortlist 2.2 s;
  live-rail 0.5-1.3 s (1.72 MB raw).

**The host is NOT saturated. The refresh-worker is.**
- **12 cores, load 8.6-10.1.**
- refresh-worker **90.7% CPU** (its one-interpreter ceiling); live-odds-worker 65%.
- Also on the host, each about one core:
  - a Bundesliga soccer artifact build (99%, nice 0);
  - `momentum_lag_study.py` (94%, nice 19, the new research lane);
  - gunicorn workers 60% + 33%;
  - two live re-sim servers 44% each (nice 5).
- Memory: 254 MB free, 5.4 GB available.

**The live odds lane at the same time (I-22):** 5 sweeps launched in 29 min, 3 refused `lane_busy`. The 01:21:11Z
run lasted ≥12 min (refused through 01:33:25Z).

**#824:** 0 of 2 college `LIVE_GAMELINE_JOIN` lines since 01:11Z carry the reason. 0 of 35 college totals flags
below the points scored.

### Improvement hunt, reading 14

**I-20 is now the evening's main defect, and the measurement says why the split works.** At the NBA + college
peak, the refresh-worker's one interpreter carries both the board build and the live book-grid tick:
- the board build took 25 min, against a 300 s today limit;
- the live overlays crossed web's 360 s staleness cutoff (NBA 2, NCAAB 1; 19 stale merges);
- the host had 2-3 idle cores the whole time.

Running the board build in its own process (card **task_265c4921**, waiting for the user) is the lever this
reading supports. A second, smaller lever: the evening's pregame soccer artifact build runs at nice 0 next to
the live roles.

## Reading 15 — Tue 11-17 8:06 PM CST (02:06Z 11-18), full page — the live odds lane is blocked by a hung NHL odds fetch

**Fleet:**
- **Web reloaded at 01:46:27Z (7:46 PM CST)** onto `3920a2d4d`: lane web-silent-worker-kills' loop-stall black box
  (deploys.md, `c2dd0bd6f`).
- **I-17's web half is now live:** the rail template and the `live_rail_rows` fields from `923869cf3` rode along.
  It falls back to the old number until refresh-worker loads the join. The I-17 lane has scheduled that load for
  1:50 AM CST 11-18 (task i17-calibrated-total-load-1118).
- **BC-041 `yes` is pending at the next refresh-worker restart:** `ee47c930a`, NFL re-sim seeds.
- refresh-worker 28948 (`91d865fd5`); live-odds-worker 52087. Host load 7.2-7.6 on 12 cores; 7 GB available.

**Slate: 58 live chips.** NCAAB 34, NHL 9, WNCAAB 9, NBA 3, NCAAF 3. Villanova @ Pittsburgh and Tennessee St @
Louisville are final (graded at the summary).

**Flags: 47 shown, 0 false, 0 missed, 0 dark.** 25 of 58 live cards carry a flag.

**I-17 metric corrected.** A "contradiction" now requires the flagged side's model P > 0.5 with "ours" on the other
side of the line. An alternate-line value flag at P < 0.5 is consistent with its median. Example: Knicks @ Raptors
u199.5 at P 0.28 vs fair 0.13, ours 217.7.

Recount over every shown totals flag since the #816 load (`flags.jsonl`):

| sport | contradictions (P > 0.5) | of observations |
|---|---|---|
| **NCAAB** (full game) | **64** | **176** |
| WNCAAB | 4 | 41 |
| NBA | 2 (1 full, 1 Q2) | 82 |

Every NCAAB and WNCAAB "other side" observation had P > 0.5, so the earlier readings' college counts stand. This
reading: NCAAB 4 of 16.

**Live rows: 1,256.** 456 priced <= 120 s; 587 over 300 s; priced age p50 154 s. 23 of 189 markets carry no
price of ours.

| sport | rows | priced <= 120 s |
|---|---|---|
| NBA | 671 | 330 |
| NCAAB | 472 | 86 |
| NCAAF | 49 | 14 |
| WNCAAB | 46 | 19 |
| NHL | 18 | 7 |

**Overlay (27 min): 0 gaps over 360 s** (max NHL 292 s, NBA 278 s, NCAAB 259 s).
- Ticks 25; gap p50 54 s, max 144 s. `deferred_slow`: NBA 2, NCAAB 1.
- Build s p50 / max: NBA 31.8 / 74.8; NCAAB 27.9 / 52.5; NHL 9.1 / 20.6.
- **Web merges stale 2 of 48** (NHL 1, NBA `stale_399s` at 01:45:21Z), down from r14's 19 of 36.
- **NHL in-play rows: 99 → 5 → 723 → 0 → 5.** 7 of 11 NHL builds carried zero cards (see below).

**Board build 829 s** (01:51:40-02:05:29Z): overview 166 s, shortlist 430 s, portfolio 49 s. Over 300 s again.

**Load (full page):**
- **`/intelligence` 17.0 s** / 6.07 MB wire / 32.2 MB raw.
- Query 14.5 s / 4.62 MB / 24.7 MB.
- Chips 2.7 s; shortlist 1.5 s; live-rail 0.14-1.42 s.

**#824:** 0 of 5 college join lines since 01:39Z carry the reason. 0 of 21 college totals flags below the
points scored.

### I-22 ROOT CAUSE: `scripts/refresh_nhl_oddsapi.py` hangs for its full 1,800 s timeout inside the live odds lane

- **The run that held the lane 01:21-01:53Z** (manifest
  `data/reports/migration_runs/2026-11-17/odds_refresh_20261118_012111/odds_refresh.json`):
  - `refresh_odds_sources.py --sports nba,nhl,ncaaf,ncaab,wncaab --phase live`, started 01:21:11Z, finished
    01:53:20Z, ok False, rc 1;
  - error `TimeoutExpired: ... scripts/refresh_nhl_oddsapi.py --date 2026-11-17 --days-ahead 1 ... timed out
    after 1800 seconds`.
- **The next run (01:54:26Z) is in the same state now:**
  - `refresh_nhl_oddsapi.py` pid 110202 had run 1,032 s at 02:12Z, at 1.7% CPU;
  - main thread in `poll_schedule_timeout`, 11 threads in `futex_do_wait`;
  - it opens successive HTTPS connections (the local port changed 52538 → 54862) to **104.16.144.251:443 =
    api-web.nhle.com**, the NHL web API (`syndicate/local_nhl_odds.py` `NhlWebClient`: 30 s per request, 3/s).
  - Expected to time out ~02:24:30Z.
- **Cost:**
  - live odds sweeps 01:39-02:06Z: **11 launched, 10 refused `lane_busy`**; 00:00-01:10Z: 17 of 34;
  - every sport this lane refreshes waits behind NHL: NBA, NHL, NFL, NCAAF, NCAAB, WNCAAB. NCAAB / WNCAAB also
    have a fast tick; NBA has its own autorun;
  - NHL in-play rows fell to 0-5 for most of 01:41-02:07Z. NHL is the sport with live in-game entries.
- **First time in three days of manifests:** 11-15..11-17 had three earlier `TimeoutExpired`s, all on
  `refresh_nba_oddsapi_props.py` at ~05:00Z, off-peak. This is the first NHL odds timeout, and the first at peak.
- **The fix (not built; a live-odds-worker restart to load is the user's call):**
  - give each sport's odds job its own lane or deadline, so one stuck sport cannot block the rest;
  - and/or give `NhlWebClient` a total deadline (or move the NHL web schedule call out of the live odds path).
- **Owner:** no lane claims `refresh_nhl_oddsapi.py` or `local_nhl_odds.py`. Proposed as a session card.
- **Immediate mitigation:** none taken. Ending the stuck child early would free the lane ~10 min sooner; that is
  a production action for the user.

- **USER DECISION ~8:25 PM CST (02:25Z): "Load it"**, answering "Let the 1:10 AM restart load the NFL re-sim seeds?".
  - **Context:** lane ncaaf-grid-build-speed's refresh-worker TERM after 1:10 AM CST loads the fleet head
    `3920a2d4d`. That carries #809, I-17 `923869cf3`, and `ee47c930a` NFL re-sim seeds (BC-041 yes). The seeds
    lane had recorded that load as the user's call after TNF 11-19.
  - **Relayed** to the TERM's lane (local_208683f1, delivered) and to the seeds lane's owner (local_997aa897,
    queued). Nothing loaded by me.

## Reading 16 — Tue 11-17 8:37 PM CST (02:37Z 11-18) — the NHL odds hang repeats every run

**Fleet:** unchanged. Web `3920a2d4d`; live-odds-worker 52087; refresh-worker 28948. Host load 7.3 on 12 cores.

**Sessions started on the user's words:**
- I-20 local_9c4bd078: switch on main `09eddabf2`. The user said **"Yes, switch it on"** in that session: env key
  + a drained full down/up after the overnight loads (`d32449953`).
- I-22 local_73a5d2dd: lane odds-lane-sport-deadline, `1f4b262da`.
- I-16 local_1a1d1ce7.
- I-21 local_ce6ce550.

**Slate: 42 live chips.** NCAAB 23, NHL 7, WNCAAB 7, NBA 3, NCAAF 2.

**Flags: 38 shown, 0 false, 0 missed, but 73 dark rows (18 markets).**
- **Dark:** almost all NBA alternates: totals_alt full / Q3 / Q4, spreads_alt full / Q3 / Q4. They were priced
  fresh (<= 120 s) and are now 310-325 s old. The NBA alt quotes are not re-priced within 5 min. Also 8 NCAAB rows
  at ~355 s.
- **I-17 (P > 0.5 rule):** NCAAB full-game totals 7 of 20 contradict "ours". NBA 1 value flag, not counted.
- **Largest:** Kennesaw St @ Alabama ALA −23.5, 25.2 pp.

**Live rows: 881.** 377 priced <= 120 s; 620 over 300 s; priced age p50 160 s. 12 of 141 markets carry no
price of ours.

**I-22, the NHL odds hang, now three runs in a row** (`odds_refresh.json` manifests):
- **01:21:11Z: TimeoutExpired** on `scripts/refresh_nhl_oddsapi.py`, 1,929 s;
- **01:54:27Z: TimeoutExpired** on the same script, 1,817 s;
- **02:25:36Z:** its NHL child (pid 138879) at 688 s and 1.8% CPU at 02:37Z, the same pattern.

**Live odds sweeps 02:06-02:37Z:** 7 launched, **6 refused** `lane_busy`.

**NHL in-play rows:** 5, 0, 4, 4, 4, 16, 6, **600, 598**, 0, 9. They are present only at 02:26-02:29Z, right
after the 02:24Z timeout freed the lane. 5 of 11 NHL builds carried zero cards.

**Overlay (31 min).**
- Gap max: NHL **382 s (1 over 360)**; NCAAF 286 s; WNCAAB 279 s; NCAAB 212 s; NBA 158 s.
- Web merges stale 1 of 63 (NHL `stale_371s` 02:36:02Z).
- Ticks 33, gap max 152 s. `deferred_slow`: NBA 1, NCAAB 1.
- Build s p50 / max: NBA 26.8 / 111.4; NCAAB 19.0 / 79.9.

**Board:** build spans overview 98 s, shortlist 561 s (exit 02:35:52Z). Board built 202 s ago at the read.

**Load:** **query 19.2 s** / 4.64 MB / 24.9 MB; **shortlist 5.9 s; chips 5.2 s**; live-rail 0.36-0.50 s.

**Team cards:** 0 flipped, det1 / det2 / det3 0 / 0 / 0, 0 chip-less, 0 live chips without a live card.

**#824:** **2 of 6** college `LIVE_GAMELINE_JOIN` lines since 02:06Z carry the reason (refusals). 0 of 21 college
totals flags below the points scored.

- **OPS 8:46 PM CST (02:46:25Z):** on the user's "kill the hung nhl odds process", SIGTERM to the hung NHL odds
  child pid 138879 (1,252 s, 1.1% CPU). It exited in 1 s.
  - Its run finished 02:47:17Z (rc 1, the NHL failure; the other sports ran).
  - The next sweep was accepted at 02:48:06Z, but **its NHL child (pid 158782) re-hung on api-web.nhle.com within
    ~2.5 min**, and the 02:49:20Z sweep was refused `lane_busy` again.
  - So a kill frees the lane for one run only. Recorded in deploys.md (betting change: no). The fix is I-22's.
