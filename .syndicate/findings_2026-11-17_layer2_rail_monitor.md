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
