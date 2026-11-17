# Findings — WNBA box-score polling of fleet web, decided per date `[2026-11-17, lane wnba-boxscore-polling-per-date, todo #829]`

Started from the Layer 2 rail monitor's I-14 (reading 5, 3:28 PM CST,
`findings_2026-11-17_layer2_rail_monitor.md`). User, in words: "start the WNBA
box-score polling session". Substrate: the fleet's `~/syndicate-prod/logs/web.log`,
its Redis and its data root, read-only. All times US Central unless marked Z.

## What is true

**WNBA box-score calls were 29.4% of all fleet web requests over 18 days, and 67.0% on 11-17.**

- 10-31 03:14Z to 11-17 21:39Z: 29,449 of 100,005 access-log requests.
  - `GET /wnba/api/live_player_boxscore`: 17,756.
  - `GET /wnba/api/final_player_boxscore`: 11,693.
- 11-17, midnight to 3:39 PM: 1,614 of 2,408. The morning had few other requests.
- No WNBA game falls on any of those dates.
- The share varies by day, from 9.8% (11-07, a 10,600-request day) to 51.7% (11-12).
  The WNBA count itself is steady:

| day | all | live box | final box | WNBA share |
|---|---|---|---|---|
| 11-09 | 5,129 | 1,094 | 844 | 37.8% |
| 11-12 | 4,125 | 1,164 | 970 | 51.7% |
| 11-14 | 8,339 | 1,100 | 639 | 20.9% |
| 11-16 | 5,479 | 1,074 | 790 | 34.0% |
| 11-17 (to 3:39 PM) | 2,408 | 714 | 900 | 67.0% |

- **The live box costs a web worker:** p50 731 ms, p90 1,062 ms, n=17,756. Each answer
  is an empty 199 bytes.
- **The post-restart baseline**, 19:52-21:52Z on 11-17 (2.01 h, `C:\tmp\wnba_boxpoll\measure.py`).
  It ends at another session's drained `down`/`up` at 21:52:41Z, so no restart
  falls inside it.
  - 224 of 386 requests (58.0%) were WNBA box calls, 112 an hour.
  - There were 21 web memory recycles (18 hard): 10.46 an hour, one per 18.4 requests.
  - 92 of those 224 were test-leak calls for June/September dates (see caller 3).
    Without them: 132 of 294 (44.9%).

### The three callers (file:line on the pre-change code `a374b19f3`)

**1. Live capture, on live-odds-worker.**

- `syndicate/features/shared/live_lens_loop.py:737`, in `_run_live_lens_tick_for_sport("wnba", <today>)`.
- It calls `scripts/capture_wnba_live_player_box.py:74` `fetch`, which sends
  `GET /wnba/api/live_player_boxscore?date=<today>` (`syndicate/blueprints/wnba.py:726`).
- It runs every ~1.5 min, ~1,000-1,160 a day, user agent `Python-urllib/3.11`.
- The role log shows 148 `WNBA_LIVE_BOX_EMPTY ... games=0` lines and 0 `CAPTURED`
  in the current `live-odds-worker.log`.

**2. Settlement count, on refresh-worker.**

- `pipeline/intelligence_state.py:8083`, inside
  `IntelligenceStateService._build_candidate_pool`, runs for today and yesterday on
  every pass. The board's tomorrow-dated build adds ~1 an hour for 11-18.
- The chain is `_refresh_wnba_boxscores` (`:5495`), then
  `scripts/build_wnba_boxscores.py:363` `fetch_via_web(count_only=True)`, then
  `GET /wnba/api/final_player_boxscore?date=D&count_only=1` (`syndicate/blueprints/wnba.py:654`).
- About 550-770 a day, user agent `Mozilla/5.0` (`build_wnba_boxscores._get`).
- On 11-17: 2026-11-16 297, 2026-11-17 259, 2026-11-15 52.

**3. The June dates are tests, not a stuck backfill.**

The rail monitor read the `final_player_boxscore` requests for 06-03 / 06-04 / 06-05
(and 06-09 / 06-10 / 09-09 / 09-10) as refresh-worker's postgame backfill stuck on
dates that never publish. **They are test runs reaching the live fleet.** There were
2,002 of them since 10-31.

- **The window:**
  - A steady ~76 a day arrive in 08:16-08:54Z.
  - The nightly suite runs in that window: `job-ci-suite.log`, pytest shards
    02:14:07-02:58 CST (08:14-08:58Z), from `~/syndicate-prod/ci-checkout`.
  - Daytime bursts on 10-31, 11-02, 11-10, 11-14 and 11-17 (17-20Z) are sessions'
    own test runs.
  - On 11-15, 11-16 and 11-17 every June request falls in one of those windows.
  - Compared with a control hour, the 08:10-09:00Z window adds `final_player_boxscore`
    and nothing else to web (122 against 40).
- **The mechanism:**
  - A test that builds the candidate pool for a fixture date runs the settlement
    pass, which runs `_refresh_wnba_boxscores`.
  - `web_base_url()` falls back to `http://127.0.0.1:10000`, the fleet, when
    `SYNDICATE_WNBA_LIVE_BOX_BASE_URL` is unset.
  - A pytest spy (`C:\tmp\wnba_boxpoll\plugin\leakspy.py`) over
    `tests/test_intelligence_state.py` caught these tests reaching it:
    - `test_build_candidate_pool_does_not_embed_full_odds_history_payload` and
      `test_compute_response_recomputes_when_cached_snapshot_is_stale` (06-09/10);
    - the three `test_background_loop_*_board_date_drain*` tests (today and yesterday).
    So some of the "today/yesterday" volume in test windows is tests too.
- **EXONERATED: refresh-worker's WNBA postgame backfill**
  (`scripts/run_refresh_worker.py:1570`, `_run_wnba_postgame_producer_tick`).
  - It calls `build_wnba_boxscores.build_date(target)` with no `base_url`, so it goes
    to ESPN directly and never to web.
  - Its window is the last 30 days, so June is not in it.
  - Fleet status `wnba_postgame_producer.json`, read 21:5xZ:
    - last run 1,602 s earlier (the hourly gate holds);
    - 75 dates done (23 `ok`, 52 `no_final`);
    - `box_rebuilds` capped at 3 on 9 September dates.

## Hypothesis and result

- **Hypothesis (written in the lane before testing):** two production loops poll web
  for dates with no WNBA games, and the June calls are test runs leaking to
  `127.0.0.1:10000`.
- **Falsification:** June requests outside test-run windows, or no test reaching web.
- **Result:** CONFIRMED on both counts (above).

## The fix (on main `920c19e70`, not loaded)

**`syndicate/features/wnba/slate_schedule.py` (new): `wnba_slate_verdict(date)`.**

- **Source:** `<data root>/wnba_source/data/processed/schedule_<YYYY>.csv`. The WNBA
  refresh's `fetch-schedule` rewrites it on every run. The fleet copy at 3:34 PM CST
  had 374 rows, 2026-04-25..10-31, playoffs included.
- **Skip:** only when that file is readable, has rows, and lists no game on the date.
- **Counting leans towards polling:** a row counts on its `date_est` OR its `date_utc`,
  and every status counts.
- **UNKNOWN (polls, logs the reason):** `schedule_absent`, `schedule_unreadable`,
  `schedule_empty`, `schedule_no_date_columns`, `schedule_undated_rows`, `bad_date`,
  `data_root_unavailable`.
- **The cards context only un-skips.** The published cards context for the date can
  turn a 0-game verdict into a poll (`cards_context_has_games`). It can never cause a
  skip, because on 11-17 that context said `games: []` while its `source_path`
  (`game_cards_2026-11-17.csv`) was absent from disk. Absent is not empty.

**Live capture:** `_run_live_lens_tick_for_sport` asks the verdict before
`_capture_wnba_live_player_box` (the old block, moved to a helper unchanged). It logs one of:

- `WNBA_LIVE_BOX_SKIPPED date=D reason=schedule_has_no_games ... -- no request to web`;
- `WNBA_LIVE_BOX_SLATE_UNKNOWN date=D reason=<name> -- polling`.

**Settlement:** `_refresh_wnba_boxscores(D, holds_ungraded_wnba=...)` logs one of:

- `WNBA_BOXSCORES_COUNT_SKIPPED`, then returns;
- `WNBA_BOXSCORES_SLATE_UNKNOWN`, then asks web.

The call site passes `holds_ungraded_wnba` when the ledger holds an ungraded WNBA order
on D. That is evidence the slate had games, so it always asks, and prints
`WNBA_BOXSCORES_SCHEDULE_DISAGREES` if the schedule says none.

**Tests no longer reach the fleet.** `tests/conftest.py` sets
`SYNDICATE_WNBA_LIVE_BOX_BASE_URL=http://127.0.0.1:9` at import. Port 9 refuses at once.
It is set at import rather than in a fixture because settlement threads outlive tests.

- **No deploy is needed for this part.** The nightly suite's `ci-checkout` follows
  main, so the next run (02:14 CST 11-18) should send 0 June/September requests.

**No sport switch, no season flag, no new env key.** January 2027 will need a check:

- `schedule_2027.csv` does not exist yet, so every 2027 date is UNKNOWN and polls at
  today's rate, logging `reason=schedule_absent`.
- That lasts until `fetch-schedule` writes a 2027 file with rows.
- This is deliberate (unknown never skips) and costs ~1,600 requests a day while it
  lasts.
- Check `WNBA_LIVE_BOX_SLATE_UNKNOWN` counts in the first week of January (todo `#829`).

### Validation against the fleet (read-only, the module loaded by path under the fleet's `python3`)

- **Verdicts:**
  - 11-16, 11-17, 11-18 skip;
  - 06-03 / 06-04 / 06-05 poll (4 / 3 / 4 games), as do 10-08 and 10-31;
  - 2027-01-05 is `schedule_absent` (polls);
  - 0 undated rows.
- **The schedule against an independent record**, the postgame producer's per-date
  ESPN finals: 66 of 75 dates agree.
  - All 9 disagreements are the safe kind: the schedule lists a game where the
    producer saw no final, mostly from counting the UTC date too.
  - 0 dates where ESPN had finals and the schedule lists none.
  - All 132 `boxscores_2026-*.csv` files (04-25..10-31) fall on dates the schedule lists.

### Tests

- **New files:**
  - `tests/test_wnba_slate_schedule.py`, 13 tests;
  - `tests/test_wnba_box_polling_per_date.py`, 11 tests.
- **Reachability first:** the same code on the same date makes the request when the
  schedule lists a game and makes none when it lists none, for both callers. **Both
  reachability tests FAIL on the pre-change files** (checked by swapping in `HEAD`'s
  `live_lens_loop.py` and `intelligence_state.py`) and pass on the new ones.
- **Then:** a no-game date is skipped and logged; a game date is polled; an unknown
  schedule polls and logs its reason; a failing verdict polls; ungraded WNBA orders
  overrule an empty schedule.
- **Guards:** an AST check that every settlement call site passes
  `holds_ungraded_wnba`, and a check that neither box client resolves to `:10000`
  under the suite.

## Expected effect after a load (to be measured, deploys.md)

- **Live box:** ~1,000-1,160 a day to 0 on no-game dates. This needs live-odds-worker
  to load the code (a role TERM after an ff).
- **Settlement count:** ~550-770 a day to 0 on no-game dates. This needs refresh-worker
  to load it (a role TERM after an ff, which kills an in-flight MLB sim; check first).
- **Test leaks:** ~76 a day plus bursts, to 0, from tonight's suite with no deploy.
- **Web worker recycles:** expected to fall with request count (the rail monitor:
  about one per 10 requests in its clean window). The reading owed is recycles per
  hour before and after, over comparable windows.

## Not in scope, named

- `scripts/poll_basketball_momentum.py` also runs every WNBA tick in the offseason
  (`BASKETBALL_MOMENTUM sport=wnba games=0`). It calls ESPN directly, not web, so it
  does not count against web.
- I-16 (a 15-minute full-form query reader) belongs to the rail monitor.
