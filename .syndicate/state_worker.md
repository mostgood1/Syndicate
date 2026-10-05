# state — worker

Split out of `state.md` by `scripts/split_state.py`. Bodies are verbatim.
The INDEX of every subject, across every part, is in `state.md`; the
one-subject-one-section rule is global and spans these files.
Same rules as state.md: when a fact changes, EDIT THE LINE.

## [render-crons] THE THREE CRON SERVICES: WHAT THEY ARE, AND FOUR FACTS THAT COST A SESSION TO LEARN `[2026-09-08, lane render-cron-failures, verified on render]`

`sim-input-reports` `crn-dafj4ie7bikc738q9ol0` `0 7 * * *`,
`ci-suite` `crn-dafg4h0u01pc73aavs6g` `0 8 * * *`,
`mlb-season-artifacts` `crn-dafffnn40ujc73b349pg` `0 9 * * 1`. All
`autoDeploy = no`, all created 2026-09-07 — **after** the deploy-lock tooling,
which is why they fell through it.

**1. A CRON CANNOT BE DEPLOYED BY COMMIT.** `POST
/v1/services/<crn-id>/deploys` with `{"commitId": ...}` returns **HTTP 400**,
`cannot deploy cron job service ... by commit reference ID`. The body must be
`{}` and it takes the **BRANCH TIP** — so the SHA that runs is whatever `main`
is at build time. Read the deploy's own `commit.id` back.

**2a. BUT A CODE CHANGE DOES, AND THE ASYMMETRY IS A TRAP.** `autoDeploy = no`,
so a cron keeps running its LAST DEPLOY however many times you push. Measured
2026-09-08 22:0xZ: 4 test repairs were pushed as `510b692e` and the cron was
still on `c208b5ef` — `point_estimator` appeared **0** times in the test file at
the live commit and **1** on `origin/main`. An expectation was about to be
written against the pushed code rather than the running code. **Diff the SERVED
commit's file, not `main`'s, before predicting what a run will report.**

**2. A START-COMMAND CHANGE NEEDS NO DEPLOY.** `PATCH /v1/services/<crn-id>`
with `serviceDetails.envSpecificDetails.startCommand` creates NO deploy, and
the next run uses the new command from the OLD deploy. **The opposite of env
vars**, which do need one. The running container keeps its own copy, so a
change mid-run is safe.

**3. `RENDER` IS INJECTED ON CRON JOBS TOO**, so anything running this repo's
tests there measures its own host. `run_ci_suite._step_env()` scrubs it.
Measured on the same 9 files: **116 failed / 698 passed with the scrub
bypassed, 21 with it.** The scrub lives in `run_ci_suite` ONLY — any other
entry point inherits the bug.

**4. `lastSuccessfulRunAt` READS `None` EVEN AFTER SUCCESSFUL RUNS.** Do not
use it. Read `cron_job_run_ended` events. A run is triggered with
`POST /v1/cron-jobs/<id>/runs`.

**Cron services can now be claimed** (`96cc8cab`): `deploy_claim.py`,
`deploy_preflight.py` and `deploy-guard.py` all handle `crn-`.
`cron_run_in_flight()` answers preflight's in-flight question from run EVENTS,
because a cron emits **0** `ALL_PROCESS_MEMORY` lines (refresh-worker: 20 over
the same 3h window) and the process-sample path would return `UNKNOWN` forever.
Crons are deliberately NOT in the guard's `ALL_SERVICES`: they are absent from
`render.yaml`, so `blueprint_sync` cannot reach them.

## [ci-suite-pytest-step] THE FULL SUITE RUNS ONLY WHEN CHUNKED, AND IT IS GREEN WITH AN EMPTY BASELINE `[verified 2026-10-02, lane ci-red-on-main, local fleet]`

**Worker count was never the lever.** OOM-killed at 2Gi at `-n auto`, at `-n 2`
(1056 s in) and at `-n 0` (537 s in) — **fewer workers failed SOONER**, because
`-n 0` is the floor for PROCESS COUNT and not for PEAK MEMORY: one process must
hold what the whole suite accumulates.

**Chunking is what works.** `--pytest-chunks 8 --pytest-workers 0` COMPLETED
twice, **3013 s and 3039 s**, `collected=16418`. `pytest_baseline.py --chunks N`
runs N fresh processes and UNIONS their results, and refuses (`EXIT_RUN_BROKEN`)
on any chunk that writes no junit or collects 0 cases — because this gate also
fails on a SHRINKING failure set, so a dead chunk would otherwise report its
tests as newly FIXED.

**GREEN, AND THE BASELINE IS EMPTY `[verified 2026-10-02, lane ci-red-on-main]`.** With Render suspended the suite
runs as the local fleet's `ci-suite` job (08:00Z, `local_production.py ci-run`: its own `<home>/ci-checkout`,
scrubbed env, niced). Full run on `d559535b`: **rc=0, 10/10 steps, pytest 21,615 collected / 0 failing,
archive suite ok.** `tests/pytest_baseline.json` holds **0** failures, so ANY failure the job reports is new.

**FIRST SCHEDULED RUN (2026-10-02 08:00Z, `4ec1fd72`): rc=1, ONE failure, a flake now fixed `[verified]`.**
`test_nfl_live_resim::test_turning_it_ON_widens_the_distribution...` failed 1 in 5 isolated runs: the rating
perturbation seeded `random.Random(tuple.__hash__())`, PYTHONHASHSEED-dependent. Fixed in `92565cd5` (p 0.691176
under all 10 hash seeds); the fleet checkout carries it. The job tests the FLEET CHECKOUT's HEAD, so a fix
reaches the 08:00Z run only once `~/Syndicate` is fast-forwarded.

**THE OLD RED WAS MOSTLY HOST LEAKS, NOT KNOWN-CORRECT RED.** Run 1 (`869c4999`): 48 failing, 36 of them
recorded. Every one passed on Windows; on Linux they read the host -- `os.environ["TEMP"]`, the cgroup's
`memory.stat`, real refresh-job processes, Windows `powershell`, 0600 directories -- plus stale fixtures
(hard-coded "future" dates, pre-rule EV) and two code defects (`soccer_season_audit/outcomes.py` TEMP;
`nfl/sources.data_path` sibling-repo fallback). Per-test causes: commits `ef06babc`..`d559535b`.

**NOT RE-MEASURED:** the 2026-09-08 claim that 15 intelligence tests need 3 GB and fail on a 2 GB cron. The
local runner is not memory-capped, so a green run here says nothing about a 2 GB Render cron.

## [odds-history-segment-keys] THE odds_history SHARD CARRIES `segment=` KEYS NOW — and three separate key builders were segment-blind, in two different ways `[verified in production 2026-09-10, lane odds-history-segment-term, live `26c8cfc6`]`

**The store's game keys were `event_id|home_team|away_team|market|bookmaker` with
NO segment term — 4,063 of 4,063 keys on the 2026-09-08 mlb shard — so nothing
downstream could tell a first-5 price from a nine-inning one. Measured live
2026-09-10 01:34Z, 57 s after refresh-worker went live: 0 -> 35 segment keys
(`first5` 21 / `first3` 10 / `first1` 4), and 38 within the hour. It accumulates
every cycle, not once at boot.**

**TWO DIFFERENT DEFECTS, and the second is the one that would have made a key
fix inert.** `clv_join._history_key` simply omitted the field. But
`odds_refresh_tracking` never SAW a segment: `_market_rows_from_mapping`
descends `markets`, meets the key `segments`, stamps `market="segments"` from the
container name and stops, because the level below is segment NAMES. Measured on
a real 15-game snapshot: **45 rows out, zero carrying a segment**; after the
descent fix, 270 rows / 225 keys / 180 segment-keyed.

**FULL GAME KEYS AS NOTHING, AND THAT IS LOAD-BEARING.** Every entry already in
every shard was written without a segment term and these keys are compared
verbatim, so `segment=full` would have orphaned the whole store on the first
write after deploy — silently, because an orphaned key looks exactly like a
market nobody has quoted. Verified across all 47 mirror game-line snapshots:
1,544 old keys -> 6,873, **0 lost**. Cross-sport nhl/nba/wnba 405 keys, 0 lost;
ncaaf/nfl/soccer route segment prices to `book_quotes`, not to an odds-history
snapshot, so no row of theirs carries a `segment`.

**WHAT IT COST IN CLV, measured against production before and after:** 19 of
2,007 resolved rows on 2026-09-08 were a segment bet priced off a full-game
close, 17 of them inside the 231-row same-book headline. `avg_clv_pct` +0.9497
-> **+1.1479**; on 09-07 the headline **flipped sign**, -0.0492 -> +0.1749.
**The mechanism is that h2h has no line** — `_price_for_side` already refuses a
line disagreement, so segmented totals landed in `line_mismatch`, but a
moneyline has no number to disagree about and 18 of the 19 were `h2h`. A guard
that only works where a line exists is not a segment guard.

**`segment_absent_from_history` IS EXPECTED TO BE LARGE AND IS NOT A GAP.**
1,617 on 09-08, equal to that date's non-full opening count. Those bets are
REFUSED rather than mispriced; they become resolvable only for dates whose shard
is rebuilt post-deploy. Read it against `openings_by_segment`, which is on the
report for that reason.

**UNVERIFIED, and both need a shard built entirely post-deploy:** the growth
ratio (predicted **3.63x** game keys, +9.5MB, 56.4 -> 65.9MB **+17%**, measured
on complete mirror snapshots only — the live shard grew 0.5% on the night and
240 -> 284 game keys is unfair by construction), and `segment_absent_from_history`
actually falling. `venue_quote_adapters` now refuses a segment-keyed entry by
name rather than keying it as full game, because its `quote_key` has no segment
slot.

## [refresh-worker-headroom-2026-09-02] THE ~1.4GB HEADROOM FIGURE IS STALE, AND THE METRIC EVERYONE READS IS THE WRONG ONE `[2026-09-02, lane m625-env-snapshots, measured off 200 MEMORY_WATCHDOG samples 15:30-16:10Z]`

> ### CORRECTION 2026-09-09/10, RE-READ 2026-09-10/11 ON THE NEW CODE -- THE NUMBERS ABOVE ARE SUPERSEDED. THE METHOD IS NOT. `[lane refresh-worker-anon-ratchet]`
>
> **The band and the peak stage have both moved. "~2.26GB headroom" is no
> longer true and must not be used to size new periodic work.** The 2026-09-02
> body is kept verbatim below because its METHOD lesson -- read `memory_anon_mb`,
> never `memory_headroom_mb` or `memory_current_mb` -- is what made this
> measurement possible, and because I proved it still bites: I first reported
> this ratchet as *"`container_memory_mb` MAX 4,095.9 = 100.0% of the ceiling"*,
> which is exactly the field this section warns against. Reclaimable page cache
> measured **1,426MB mean** on the same samples.
>
> **FOUR INDEPENDENT LIVE-SLATE WINDOWS, none straddling a restart** (the
> 22:24:40Z and 01:33:47Z deploys are both cut around, per `learnings.md`
> 2026-09-02), 5,040 `MEMORY_WATCHDOG` samples, every window's coverage checked
> against what was asked:
>
> | window (UTC) | live | n | anon min | anon mean | **anon MAX** | headroom at peak |
> |---|---|--:|--:|--:|--:|--:|
> | 22:30-23:30 | `d84840a9` | 1,589 | 1,551.3 | 2,090.5 | **2,820.8** | 1,275.2 |
> | 23:30-00:45 | `d84840a9` | 1,952 | 1,734.5 | 2,281.3 | **3,031.0** | 1,065.0 |
> | 00:45-01:28 | `d84840a9` | 1,093 | 1,931.0 | 2,463.6 | **3,138.7** | **957.3** |
> | 01:45-02:00 | `26c8cfc6` | 406 | 1,880.8 | 2,280.0 | **2,690.6** | 1,405.4 |
>
> **The recorded max was 1,877. The lowest of these four peaks is 2,820.8** --
> +50% on the old ceiling, and the worst window leaves **957MB**, not ~2.26GB.
>
> **IT IS A RATCHET, NOT AN EXCURSION, AND THE FLOOR IS WHAT SAYS SO.** Across
> the three pre-deploy windows the MINIMUM climbs 1,551.3 -> 1,734.5 -> 1,931.0,
> ~+380MB in three hours, with the mean and max climbing in step. A spike would
> move the max and leave the floor.
>
> **THE HIGH-WATER STAGE HAS MOVED: `overview_sport_end` -> `board_contract_end`,
> in all four windows.** Anything sized against the overview peak is sized
> against the wrong stage.
>
> **NOT ATTRIBUTABLE TO THE 2026-09-10 DEPLOY, and the direction is the wrong
> one for that story anyway** -- the three worst windows are all PRE-deploy
> `d84840a9`. The post-deploy row is lower on every column and is NOT evidence
> of an improvement: it starts 11 minutes after a reboot, covered 15 of the 30
> minutes asked, and ran at roughly a third of the job load (process_count mean
> 7.0 pre against 3.1 post -- *re-read 2026-09-11 with the same
> `ALL_PROCESS_MEMORY` parse used below: 6.98 / 6.25 / 6.99 pre and **9.41**
> post over 61 lines, so "a third of the job load" does NOT reproduce by that
> method; the post row's post-reboot start and half coverage are the caveats
> that stand*). The full-slate window on the new code that this paragraph said
> was owed is the re-read below.
>
> **RE-READ 2026-09-10/11 -- THE RATCHET REPRODUCES ON THE NEW CODE.** `[scheduled
> task refresh-worker-anon-ratchet-band, adopting the lane per user reassignment
> 2026-09-10]` Fixed band `2026-09-10T22:00Z..2026-09-11T05:00Z`, read at
> 2026-09-11 13:52Z -- the run fired ~8.5 h after its 00:20-local dispatch, which
> loses nothing because the band is a timestamp range. `slate_band_anon_report.py`
> and `oom_band_report.py`, segments cut on refresh-worker's three in-band deploys.
> **Every segment's commit CONTAINS `26c8cfc6`** (`git merge-base --is-ancestor`).
>
> | segment (UTC) | live | n | anon min | anon mean | **anon MAX** | headroom at peak | min inactive_file |
> |---|---|--:|--:|--:|--:|--:|--:|
> | 22:00-03:24:50 | `c29a7d4e` (live 21:50:27Z) | 8,835 | 1,212.8 | 2,002.8 | **3,020.0** | **1,076.0** | **19.4** |
> | 03:24:50-03:55:29 | `5767e3ac` | 738 | 1,073.5 | 1,455.7 | 1,955.8 | 2,140.2 | 1,238.8 |
> | 03:55:29-04:52:40 | `48621d65` | 1,510 | 970.2 | 1,534.9 | 2,091.6 | 2,004.4 | 700.7 |
> | 04:52:40-05:00 | `1e1285a4` | 138 | 988.2 | 1,133.3 | 1,557.1 | 2,538.9 | 1,280.5 |
>
> **CONFIRMED AGAIN: worst peak 3,020.0 MB against the 2,500 MB test**, in the one
> segment long enough to ratchet. The three later segments start 0-57 minutes
> after a reboot and read the ratchet in neither direction.
>
> **THE FLOOR CLIMBS AGAIN, hour by hour, on ONE process** (no restart
> 21:50:27Z-03:24:50Z; hourly queries, coverage checked): anon MIN 1,361.5
> (22:30-23:00) -> 1,586.9 -> 1,735.1 -> 1,802.3 -> 1,894.6 -> 1,919.9
> (03:00-03:24), **+558 MB in ~5 h**, hourly MAX 2,269.3 -> 2,375.4 -> 2,789.6
> -> 2,867.8 -> 3,020.0. (22:00-22:30 answered only the whole-segment query; the
> segment MIN 1,212.8 falls there, since every later hour's MIN is higher.)
>
> **Against 3,138.7: BELOW, by 118.7 MB -- and NOT attributable to the deploy in
> either direction.** Same-method `process_count` (`ALL_PROCESS_MEMORY`) ran
> hourly means 3.3 / 5.2 / 5.7 / 5.8 / 4.9 / 3.0 across the long segment, against
> 6.98 / 6.25 / 6.99 in the three 09-09/10 windows. The new-code band ran ~20-30%
> lighter and still reached 3,020. **The +17% `odds_history` shard is still NOT
> priced on its own:** a lighter band peaking 119 MB lower fits "the shard is
> cheap" and "the shard costs and the lighter load hid it" equally.
>
> **KILL-BAND FLAG: `min inactive_file` 19.4 MB (23:00-00:00, at
> `board_contract_end`) is BELOW the kill band (26.3, 42.2)**, lower than either
> real OOM kill, and 00:00-01:00 read 38.2, inside it; survived runs read
> 164-240. The events API shows **0 kills** and `oom_band_report.py` **0
> excursions** in the band. Second night running with the kill-band trough and no
> kill; a clean excursion count is still not a clean band.
>
> **Worst-case real headroom is ~1.0 GB on both nights (957.3, 1,076.0), not
> ~2.26 GB.** The high-water sample's `last_stage` moved again, to
> `build_live_state_payload_fallback_return` in the worst segment (and
> `cards_context_sim_games_loaded` in 00:00-01:00; `board_contract_end` only in
> 03:00-03:24 and the 03:55 segment). Size nothing against one named stage.
>
> **CONSTRAINT ON ANY REMEDY: `state.md [user-decisions]` 2026-08-16 -- DO NOT
> BUMP THE refresh-worker PLAN, REDUCE INSTEAD.** Taken with the numbers in
> front of the user. A smaller headroom than recorded is not an argument that
> reopens it.


**Read `memory_anon_mb`, not `memory_headroom_mb`.** `memory_current_mb` includes
reclaimable page cache and this worker holds **~1.2GB** of it, so the headroom
field understates by roughly that much.

    memory_headroom_mb   min 29    max 425   last 99     <- ALARMING AND MISLEADING
    memory_anon_mb       min 1518  max 1877  last 1833   <- the real number
    -> anon 1833 of 4096 = ~2.26GB REAL headroom

**55% of samples read under 200MB nominal headroom.** Anyone reading that field
will conclude the worker is minutes from death. It is not. This is the same trap
as the 2.7GB "plateau" that turned out to be file cache — split anon from
inactive_file before calling anything pressure.

**What IS true:** anon climbs through a cycle (1518 → 1877) and peaks at
`last_stage=overview_sport_end`, so the board-overview stage is the high-water
mark. New periodic work still is not free — `#241` stands — but it is being
weighed against ~2.26GB, not ~1.4GB, and certainly not against 29MB.

**Owed:** the first armed run of the accuracy autorun (`#626`(h), live since
2026-09-02T15:29:45Z) should have its OWN cost read against this
`overview_sport_end` peak, not against an idle baseline.

## [accuracy-autorun-OOM-2026-09-02] THE ACCURACY AUTORUN OOM-KILLED refresh-worker. **RESOLVED — DISARMED AND VERIFIED 19:32Z.** `[2026-09-02, lane soccer-anchor-wiring]`

**RESOLVED. No deadline outstanding.** The key was set `false` at ~19:0xZ and a
peer's refresh-worker deploy (`e4a471c0`, 19:26:44Z) injected it. **VERIFIED
DIRECTLY rather than inferred from deploy ordering** — the decline reason flipped
from `daily_gate` to `disabled` at 19:32:27Z and has held since:

    ACCURACY_SUMMARY_AUTORUN_GATED reason=disabled env=ACCURACY_SUMMARY_ENABLE_...

That verification exists only because the decline telemetry was added earlier the
same day (`24efb82b`); before it, all three decline causes were the same silence.

**MEASURED:** armed 15:29:45Z, fired 15:31:11Z, killed the worker by 15:32:56Z.
Anon **1,833 → 3,868 MB** against a 4,096 MB ceiling, headroom **0.051 MB**,
climbing **+146.9 MB/s**. `[accuracy_summary] AUTORUN_DONE` never printed, and
since the `except` path prints it too, its absence proves a KILL rather than an
exception. `intelligence_evaluation.py:2657` (`build_accuracy_summary`) was on
the stack in all three faulthandler dumps.

**`#241` REPEATED.** "Worker periodic work is never free" was quoted at arming
time and armed over. The job roughly DOUBLES peak anon on a worker whose cycle
already peaks at 1,877 MB.

**WHAT PREVENTED A RESTART LOOP:** `#256`'s claim-before-work. The epoch advances
at CLAIM time, so a death mid-pass costs exactly one run per day instead of every
cycle. That design decision is the only reason this is a scheduled nuisance
rather than an outage.

**THE ALLOCATOR IS MEASURED** `[2026-09-02, lane accuracy-summary-alloc-profile,
LOCAL profile, no deploy]`. Full record: `todo.md #626`(h).

    peak growth = 4.01-4.41 x ACCEPTED CHUNK BYTES, intercept ZERO, R2 0.999998
    100% of resident bytes at intelligence_evaluation.py:711 (json.loads)
    dedup ratio 0.9979 -> the "streaming reduction" reduces nothing here
    98.8-99.9% of peak is set by materialisation, BEFORE any output exists

At the production accepted set (`LEDGER_CHUNKS_ACCEPTED bytes=830,832,574
records=22,078`, ceiling 256MB, and NO date window at all) that is **3,178-3,493
MiB** on top of anon 1,833 MiB -> **5,011-5,326 MiB against a 4,096 MiB ceiling.
The kill was CERTAIN, ~915 MiB short on its most favourable coefficient**, not a
near miss. Corroborated two ways: it died having added 2,035 MiB = 64% of the
projection, and the local allocation rate (155 MiB/s) matches production's
terminal climb (146.9 MB/s) within 6%.

**Why the segment cap could not have worked, and a SECOND defect it hides.**
`_bounded_accuracy_summary` runs on the RETURNED summary, downstream of the whole
working set — a segment cap bounds output rows, never the set that produces them.
Separately it truncates the WRONG CONTAINER: `list(segmented_reliability.items())
[:50]` cuts the three top-level keys, never the `segments` LIST, so
`segments_total` reads **3** while `len(segments)` is **7**, `segments_truncated`
is pinned False at any coverage, and the "bounded" payload is LARGER than the raw
one. The 8MB keyvalue ceiling it was written to protect is unprotected. Owner:
lane `accuracy-autorun-decline-telemetry`, which holds that file.

**THE BUDGET IS BUILT AND RE-MEASURED, OFF vs ON, AT PRODUCTION SCALE**
`[2026-09-02, lane accuracy-summary-ledger-budget, LOCAL, not deployed]`:

    corpus 831,038,410 B / 8 chunks, production-shaped records
    budget OFF -> accepted 831,038,410 B, peak growth 3,181.1 MiB, 41.2 s
    budget ON  -> accepted    89,967,617 B, peak growth   344.4 MiB,  7.3 s
    resident/file byte 4.014 in BOTH -> the budget changes WHICH bytes are
    read, not what a byte costs.  9.24x reduction, 2,836.7 MiB saved.

**THE PROJECTION IS NOW A MEASUREMENT.** 3,181.1 MiB measured against 3,178 MiB
extrapolated — 0.1%. So: OFF = 1,833 + 3,181.1 = **5,014.1 MiB vs a 4,096 MiB
ceiling, OOM by 918 MiB**; ON = 1,877 (cycle peak) + 344.4 = **2,221.4 MiB,
54.2% of ceiling, 1,874.6 MiB free**.

Built in `intelligence_evaluation.py`: `max_total_bytes`/`stats` on
`_stream_chunked_ledger_records` (**default None — all 8 existing callers
unchanged**), newest-first SELECTION with ascending EMISSION so
`_latest_by_recommendation_id`'s last-wins is not inverted, a **per-RECORD**
bound so an oversized chunk is read INTO rather than dropped, env
`SYNDICATE_ACCURACY_SUMMARY_LEDGER_BUDGET_BYTES` (default 90,000,000, **absent
means bounded**), and a published `ledger_coverage` block. 10 tests incl.
off!=on; 66 pass across the ledger/summary suites.

**BOTH PUBLISHING BLOCKERS ARE NOW FIXED** `[same session, cross-lane by user
decision, logged in lanes.md]`. `_bounded_accuracy_summary` no longer drops
`ledger_coverage`, and its truncation now bounds the `segments` LIST instead of
the mapping's three fixed keys. Verified against a real summary AND against the
pre-fix function extracted from HEAD, which fails all four assertions:

    segments_total       3 -> 7 (the real count)
    segments_truncated   False-at-any-coverage -> True when it truncates
    payload/raw ratio    0.996 -> 0.13 at 400 segments capped to 50
    ledger_coverage      dropped -> published

Segments are now kept LARGEST-SAMPLE-FIRST, so a cap that fires drops the
thinnest segments rather than an arbitrary set.

**THE PROJECTION SUPERSEDES THE BUDGET AS THE PRIMARY BOUND** `[same session,
measured]`. `_project_evaluation_record` reduces each record IN THE STREAM to the
~20 scalars the statistics read, so the retained set stops tracking record
fatness:

    materialise, no budget   831,038,410 B, 8 dates -> 3,181.1 MiB, 41.2 s
    materialise, 90MB budget  89,967,617 B, 1 date  ->   344.4 MiB,  7.3 s
    PROJECTED, no budget     831,038,410 B, 8 dates ->    42.2 MiB, 10.9 s

**75x better than baseline, 8x better than the budget on 8x the data, and
faster.** Resident/file byte 4.014 -> **0.053**, i.e. ~2.32 KiB retained per
record. **The 28-day drift window is therefore affordable and the budget default
was raised 90,000,000 -> 2,000,000,000** — at 90MB it cost seven of eight dates
and saved nothing. The budget is now a backstop against unbounded RECORD COUNT,
not what keeps the job alive.

Fold-as-you-go accumulators were the plan and were **deliberately not built**:
they need a second implementation of every formula in this file, and at 42.2 MiB
the asymptotic win buys nothing. `tests/test_accuracy_summary_projection.py`
requires raw and projected to produce **byte-identical** statistics across all 9
sports through the real builders, so a dropped field is a test failure.

**REGRESSION: 136 pass. `tests/test_intelligence.py` HANGS and it is NOT this
change** — located by faulthandler stack dump, my files absent from both stacks.
TWO pre-existing blockers on
`test_intelligence_query_api_resolves_preview_date_and_preserves_contract`:
(1) infinite mutual recursion `wnba/cards.py:1686 _artifact_bundle` <->
`:3078 _games_from_live_state_fallback`, gated on `selected_date ==
central_today_iso() and not _render_web_dyno()` — a DATE-TRIGGERED hang, which is
why it is not a standing red; (2) beneath it, a **live unbounded HTTPS call to
Kalshi from the intelligence REQUEST PATH** (`_build_candidate_pool` ->
`run_kalshi_discovery` -> `fetch_markets` -> `ssl.read`). Both are committed code
owned elsewhere; `cards.py` is unmodified in the tree, last touched `ad33df21`.

**RE-ARMING IS STILL A SEPARATE, UNTAKEN DECISION, and nothing here is
deployed.** The standing caveat is unchanged and is now VISIBLE in the artifact
rather than implicit: at 95-332 MB/day the 90MB budget covers **one day against
a 28-day drift window** (`recent_days=7` + `baseline_days=21`). The budget makes
the job survivable, not correct. The structural fix — streaming accumulators,
peak O(segments + dates) instead of O(ledger) — is the next build
`[user decision 2026-09-02]`.

## [local-fleet-runner] THE THREE SERVICES RUN LOCALLY NOW — and doing it naively would have placed REAL ORDERS `[verified 2026-09-02, lane m625-fleet-runner, commit 92020995, NO DEPLOY]`

`py -3 scripts/fleet_local.py doctor` -> READY.
`... up --bounded --duration-seconds 120` ran all three: web **156.7 MB** of its
2048 MB cap and still serving, refresh-worker **exit 0, 408.9 MB** of 4096,
live-odds-worker **exit 0, 620.2 MB** of 2048. Production run-modes preserved —
**103 / 77 / 37 production keys passed through** per role.

- **RUNNING THE PRODUCTION ENV LOCALLY SPENDS MONEY.** live-odds-worker runs
  `SYNDICATE_EXECUTION_MODE=live`, `SYNDICATE_EXECUTION_LIVE_ARMED=1`,
  `SYNDICATE_EXECUTION_ENABLED=1`, `SYNDICATE_EXECUTION_VENUE=kalshi,polymarket`
  with a real `KALSHI_PRIVATE_KEY` and `POLYMARKET_US_PRIVATE_KEY` — both also on
  refresh-worker. **Measured, not argued: one bounded 120-second pass made 1,176
  outbound attempts, all denied, including 27 each to `trading-api.kalshi.com`,
  `external-api.kalshi.com` and `api.elections.kalshi.com`**, plus
  `statsapi.mlb.com`, `site.api.espn.com` and `api.weather.gov`.
- **FOUR INDEPENDENT DEFENCES**, the first three asserted BY THE CHILD (a
  parent-side scrub can be mis-edited): mode != `live`, the arm switch, no venue
  credentials — and structurally, `snapshot_render_env.py` withholds secret
  VALUES, so 49/50/35 keys per service were never in the snapshot to leak.
- **A `sitecustomize` THAT RAISES DOES NOT STOP THE INTERPRETER.** CPython's
  `site.execsitecustomize` catches it, prints `Error in sitecustomize; set
  PYTHONVERBOSE for traceback:` and CARRIES ON — verified with a one-line probe,
  **rc=0**. Any guard installed that way must `os._exit`, or it announces a
  refusal and permits the thing it refused.
- **BOTH WORKERS REFUSE A FILE STATE BACKEND** while
  `SYNDICATE_REQUIRE_HOSTED_STORAGE` is truthy (`refresh_state_store.py:316`),
  and production sets it `true` on all three services. Clearing `RENDER` alone
  is not enough — the predicate is an OR of the two.
- **GUNICORN CANNOT RUN ON WINDOWS** (`import fcntl`), though
  `shutil.which("gunicorn")` finds the pip shim. Local web runs the Flask dev
  server and says so; do not read performance or concurrency from it.
- **Memory caps are a WATCHDOG, not a container limit.** RSS sampling: a process
  can exceed the cap between samples and a sudden allocation outruns the
  sampler. Useful for the slow ratchet, NOT evidence about Render's ceiling.

## [local-production-host] PRODUCTION RUNS ON ONE MACHINE NOW — `scripts/local_production.py`, and self-publish MUST be off on a shared disk `[verified 2026-09-30, lane local-production-host, PR #118 f565a435, NO DEPLOY]`

All three Render services are billing-suspended (2026-09-30 06:37:51Z). `py -3 scripts/local_production.py init | import-render-env | doctor | up`
runs web + refresh-worker + live-odds-worker + a local Redis, deriving each role's env from `render.yaml` PER SERVICE (then the
live dashboard env, then `<home>/local_production.env`). This is the PRODUCTION counterpart of `[local-fleet-runner]`, which stays the
rehearsal harness. Runbook: `docs/ai_context/local_production_runbook.md`.

- **VERIFIED (Linux container):** all three roles up, web gunicorn 2x4 with the memory guard, both workers on keyvalue, ticks
  complete, `kill -9` recovered in 10 s. **Fresh upstream data NOT measured** (container egress): owed, `#692` item 2.
- **`SYNDICATE_WEB_PUBLISH_URL` MUST BE UNSET when roles share a disk.** The publish receiver `os.replace`s/merges the very file
  the worker is appending to (rows appended mid-merge are lost). Pulls `os.replace` over the live file. Unset + `SYNDICATE_LOCAL_PRODUCTION=1` -> `artifact_publisher.shared_disk_fleet()`: a publish is delivered by the write and a pull is current, silently `[verified 2026-10-02, `08d7ec4d`: 0 BOOK_GRID_PUBLISH_FAILED / 0 *SKIP_NOT_CONFIGURED on both workers]`.
- **Web needs a Render marker (`RENDER_SERVICE_ID`) or `syndicate/app.py` starts the intelligence + live-refresh loops on first
  request WITHOUT reading their flags** -- a second board builder on the same disk.
- **Unset worker->web URLs fall back to the PUBLIC onrender host** (`live_lens_loop._wnba_live_box_base_url`,
  `publish_model_scorecard.base_url`). Set `SYNDICATE_INTERNAL_WEB_BASE_URL` / `SYNDICATE_WNBA_LIVE_BOX_BASE_URL` / `SYNDICATE_BASE_URL`.
- **Money is paper unless `up --allow-live-execution`**, even when the imported live env says live+armed. **Paper RUNS** `[verified 2026-10-02, `927d1787`]`: ENABLED=1, MODE=paper, ARMED=0 (only `local_production.env` may set ENABLED=0). Paper fills on both books, venue settlement and ORDER_PATH run; before that the fleet booked none (431 commits, 0 executions).
- Redis keys embed the ABSOLUTE data-root path: pick `SYNDICATE_LOCAL_HOME` once.
- **Operator scripts: `export SYNDICATE_BASE_URL=http://127.0.0.1:10000` repoints 56 `scripts/*.py` at the fleet** via `scripts/_base_url.py::default_base_url()` (precedence: script-specific vars > SYNDICATE_BASE_URL > SYNDICATE_OPS_BASE_URL > SYNDICATE_DIAG_BASE_URL > Render; unset = Render, unchanged). Fleet admin token is `ADMIN_TOKEN` in `~/syndicate-prod/local_production.env` (WSL), NOT repo `.env`. STILL Render-pinned: only `deploy_preflight.py` (deliberate) -- the 8 lane-claimed `pending:` scripts were all converted 2026-10-02 (`eae1de02`, `f444048a`, and the last two in lane base-url-last-two) `[verified, tests/test_base_url.py has no pending entries]`. `[verified 2026-10-01, 06f5fa7f, unit tests + per-site eval; NOT run against the live fleet, lane scripts-base-url-resolver]` **`check_deploy_safety.py` WORKS ON THE FLEET:** with a local base URL its board-build check reads `~/syndicate-prod/logs/refresh-worker.log` (via `wsl tail` on Windows; override `SYNDICATE_FLEET_REFRESH_LOG`) by LINE ORDER -- the log has no timestamps and no `COLLECT_SPAN_EXIT`; typical build from `BOARD_BUILD_TIMING wall_s` (~6.3 min). `deploy_preflight`'s no-arg call still reads Render. `[verified 2026-10-01 live: CLEAR rc=0 then IN FLIGHT rc=1, lane deploy-safety-fleet-logs]` `--drain` sizes its TTL from the same fleet `wall_s` (max(9000 s floor, 3 x build); fleet build 378 s -> floor holds) `[verified 2026-10-01 unit + live estimate, lane deploy-safety-drain-fleet-ttl]` **Drain WORKS end-to-end on the fleet** when run INSIDE WSL with the refresh-worker's state env (`SYNDICATE_REFRESH_STATE_BACKEND=keyvalue`, `SYNDICATE_REFRESH_STATE_URL=redis://127.0.0.1:6379/0`, `SYNDICATE_REPORTS_ROOT=/home/amyn/syndicate-prod/data/reports`, venv `/home/amyn/.venvs/syndicate/bin/python`) -- run from Windows the key embeds a Windows-resolved path the worker never reads. Worker acks in ~60 s and defers both MLB sim and board builds. `--drain` CLEAR now requires ack-after-request + idle board build (it used to CLEAR in 1 s on a pre-request heartbeat). `[verified 2026-10-01 live, 2 runs, lane fleet-drain-e2e]` Own-output confirmation: fixed `--drain` printed 'not acked yet' then CLEAR rc=0 30 s later `[verified 2026-10-01 01:45Z, lane fleet-drain-rerun]`. **Fleet checkout `~/Syndicate`: GitHub remote is named `github`** (`origin` there is a stale ref) and gunicorn runs WITHOUT `--preload`, so an ff alone reaches web on the next worker recycle with no deploy -- update it as a deliberate all-roles restart (recipe: ff, `--drain` + `check_deploy_safety` CLEAR, `local_production.py down`, `Start-ScheduledTask SyndicateLocalProduction`). Last restart 2026-10-02 13:37Z onto `9856dd92`, all roles `code=9856dd92` `[verified, deploys.md]`. `check_deploy_safety` treats a `running` odds pointer whose pid is dead as `STALE pointer, ignoring` (fleet; `9856dd92`) -- before that fix the pointer blocked a careful restart for its whole 10-min wait. **`check_deploy_safety` (plain and `--drain`) now blocks on every live child of refresh-worker AND live-odds-worker** on the fleet (one `ps` snapshot, descendants of each supervised worker by exact script basename, zombies excluded; UNKNOWN if unreadable or a worker is missing -- live-odds children since lane deploy-safety-odds-worker-children 2026-10-02; during live play expect CLEAR to wait for an odds-job gap) **Its `Odds refresh:` STATE line reads only live-odds-worker's `latest_tick`** -- refresh-worker runs odds refreshes of its own (`run_refresh_odds_job.py`, 567 s old at 13:11Z) while that line said `idle`; trust the child-job lines, not that one `[verified 2026-10-02 13:11Z, deploys.md]`. **Why it goes stale (measured 2026-10-02):** `latest_live_refresh_tick.json` is written once at tick END and its `result` is the LAUNCH-TIME snapshot (`state=running`, pid) -- run `20261002_135535` ended `failed exitCode=1` 13 s after launch per its own `refresh_job_status.json`, while the served tick said `running` for 11+ min; live-odds-worker ticks are short (38 s) but 11+ min apart in pregame/off-hours. **WNBA cards are served from KEYVALUE, not disk**: `/wnba/api/source/cards` reads `game_cards_<date>.csv` and `live/wnba_cards_context_<date>.json` from the refresh-state store -- moving the disk files changed nothing served; deleting the 3 keyvalue copies cleared it `[verified 2026-10-02 16:4xZ, deploys.md]`. **Game odds for WNBA/NBA come from OddsAPI only** (Bovada game-odds fallbacks removed: WNBA `de914b30`, NBA `bec56b80`); NBA lists + prices `basketball_nba_preseason` like NHL's preseason key `[verified live 2026-10-02: 10-03 MIA@TOR, 22 rows]`; upstream PRs WNBA-Betting#8, NBA-Betting#2 OPEN. `/api/ops/live-refresh/state` reconciles against the run's own `refresh_job_status.json` since `8e87c877` (web HUP 14:15Z): an exited run is served `state=finished|failed` with `launchState=running` `[verified 2026-10-02 14:44Z, deploys.md]`. **WNBA odds runs failed 65/65 on 2026-10-02 up to 13:55Z** (36 = `build_recommendation_output` `[0]` on an empty ranking, 29 = props-fetch rc=1 with the error truncated from `stderr_tail`) `[measured, log/2026-10-02.md]`; fix `589886d7` on the fleet since 14:49Z (per-run subprocess, no restart) -- effect UNVERIFIED until the next WNBA runs, lane `wnba-odds-run-failures`. -- `in_flight` itself still carries only `mlb_sim` `[verified 2026-10-02 live, lane deploy-safety-worker-children]`. `~/Syndicate` carries it since the 03:17Z ff to `995c177f` (no restart; roles still `code=d165980d`, STALE by stamp only). Before `down`, look for non-supervisor work too: `ps` for `run_ci_suite`/`pytest` -- other sessions run CI in `~/syndicate-prod/ci-checkout` outside the supervisor's tree (`down` does not touch it, and `check_deploy_safety` does not see it). refresh-worker's log is APPENDED across restarts (rotates only at 200 MB): slice it from the latest `[refresh_worker] BOOTED` line, never grep the whole file.
- `down` on a dead supervisor returns at once and reaps the roles/redis recorded in its pidfile as orphans `[verified 2026-09-30, PR #122 e8ff5030; negative control: pre-fix waited out the timeout]`.
- **Scheduled jobs, backup, AOF `[verified 2026-10-02, lane local-prod-gap-fixes, `869c4999`..`a01590bc`]`:** the supervisor runs `sim-input-reports` 07:00Z, `ci-suite` 08:00Z, `mlb-season-artifacts` Mon 09:00Z, `data-backup` 09:15Z, `model-scorecard` 11:30Z -- each ran once, rc 0 (ci-suite green on its third run). Backup = hard-linked snapshots in `<home>-backup` (keep 7) + one tar.gz in `/mnt/c/SyndicateBackup` (keep 2): 41,051 files / 5.19 GB -> 0.92 GB. Never rsync straight to `/mnt/c` (9p `uid=0` refuses utime). `up` turns AOF on a reused redis (`appendonly yes`). Same physical disk: not protection against disk failure.
- **`status` flags a role `STALE` only on a RUNTIME diff `[verified 2026-10-02, `4f3edfa9`/`8c30fd68`/`00d6c1a6`]`:** loaded `RENDER_GIT_COMMIT` vs HEAD, diffed excluding ledger/docs/tests/reports/data/`*.md` and the supervisor's own `scripts/local_production.py` + `deploy/local/`. Empty -> `no role code changed -- nothing to load`; undiffable -> `STALE?`. Read on the fleet: roles `9856dd92` vs HEAD `00d6c1a6` print nothing-to-load; `869c4999` -> HEAD prints `STALE -- 73 runtime file(s)`.
- **A FAILED SUPERVISOR START IS NOT AUTO-RECOVERED** `[verified 2026-10-04, incident 08:39-13:53Z, deploys.md]`: `SyndicateLocalProduction`'s restart-on-failure fires only on a NONZERO exit; a start whose `wsl ... up` never runs returned 0 (LastTaskResult 0, no supervisor.log line) and the fleet stayed down 5 h 14 min. The watchdog TOASTS but does not restart, and a toast at 3 AM reaches nobody. Any scripted `down` must verify `/healthz` after the start and retry; see learnings 2026-10-04.
- **Health watchdog INSTALLED `[verified 2026-10-02, lane local-prod-watchdog, `bf377ffe`]`:** Windows task `SyndicateFleetWatchdog` every 5 min runs `scripts/local_watchdog.py` in WSL (supervisor, roles, crash loop, /healthz, 15-min log heartbeat, scheduled jobs, backup < 30 h, >= 10 GB free) and toasts on new / every 6 h fail or 24 h warn / recovered; alerts by itself when WSL does not answer. Logs: `C:\SyndicateProd\watchdog\watchdog.log`, `<home>/logs/watchdog.log`. Cannot alert while the laptop sleeps (runs on wake). Remove: `install_watchdog_task.ps1 -Uninstall`.
- **The fleet's live ledger was REBUILT from the venues** `[verified 2026-10-02, lane live-ledger-venue-rebuild, `331eaebe`]`: Render's ledger stayed in its suspended keyvalue, so `venue_ledger_rebuild` wrote 552 graded live rows (`source=venue_rebuild`, one per settled market; kalshi 420 / polymarket 132, Aug 6-Sep 27, P&L -$525.70 on $2,834.45) from the venues' settlement history, run inside live-odds-worker on a request file (dry run, then apply with the exact count). Plan/model fields are None. A settlement tick leaves them as `already` (552). Pre-apply backup: `~/syndicate-prod-backup/ledger_before_venue_rebuild_20261002T181329Z.json`. `unjoinable_split` still reads 593 before / 0 after.
- **Every role line is UTC-stamped and `render_logs.py` reads the fleet** `[verified 2026-10-02, `ca27e45a`]`: `scripts/local_logstamp` sitecustomize on the roles' PYTHONPATH (off: `SYNDICATE_LOCAL_LOG_TIMESTAMPS=0`; needs a supervisor `down`+`up`), 100% of lines stamped after the restart. `render_logs` goes LOCAL on `--local`, with no key, or when Render reports suspended; unstamped lines read `~` (approximate).
- **`status`'s `code=` is HEAD at the role's code-load time, from the checkout's git reflog** `[verified 2026-10-02, `0b4b5859`]` (web: oldest gunicorn worker). It falls back to the env stamp (`RENDER_GIT_COMMIT`, from the last `up`, wrong after role-only restarts or a HUP) only when the reflog cannot answer, and prints `(env stamp)` when it does. A role-only SIGTERM of live-odds-worker exits in about 1 s (`5c205087`).

## [artifact-allowlist-split] THE ARTIFACT ALLOWLIST IS TWO LISTS NOW: READ WIDE, WRITE NARROW — and an allowlist-filtered inventory is NOT a census of the disk `[verified 2026-09-02 in production, web `e6fa165b`, lane m625-export-only-patterns]`
**CORRECTED 2026-09-03 — `reconciliation/*` MOVED TO THE WRITE LIST.** `#625`(2)
put it on the READ-only list arguing "nothing on web serves these". True, and
the WRONG TEST: export-only makes a family readable IF PRESENT, and nothing
published it, so the entry did nothing and the family stayed unreachable. **The
question is "is there a serving HAZARD", not "does web serve it".** For
reconciliation there is none — the autorun is false on web AND
`reconcile_prediction_results_for_date` defaults its roots to the repo CHECKOUT,
not `data_root()`. Cost measured: **56,564 bytes for a real one, ~663 KB for the
whole 12-date window, published once each.** `feed_live` stays export-only
forever, because there PRESENCE is the trigger. **So there was never a transport
gap for this family — only a misfiled pattern.**


`is_hot_artifact_relative_path` = WRITE (publish + sweep), unchanged.
`is_exportable_artifact_relative_path` = READ (export + stream) = hot +
`EXPORT_ONLY_ARTIFACT_PATTERNS`. Four READ sites in `ops.py` use the wide one;
the two publish sites keep the narrow one.

- **VERIFIED WITH CONTROLS, one instant:** a `feed_live` `.json.gz` went
  **403 -> 415** naming `/stream`; `/stream` serves it **200, 111,585 B**,
  gunzipping to gamePk 822722 Final/Final; a `props_history` CSV went
  **403 -> 200 count=1**; an UNLISTED path (`render.yaml`) is **still 403**, so
  the predicate was widened and not disabled. Inventory 33,229 -> 33,567 files.
- **AN ALLOWLIST-FILTERED INVENTORY IS EVIDENCE ABOUT THE FILTER.**
  `/api/ops/artifacts/export` — `names_only` and body form alike — globs
  `HOT_ARTIFACT_PATTERNS` and can only ever report allowlisted paths, so it can
  NEVER establish that a non-allowlisted family is absent. I read zero
  `feed_live` from it and published "absent"; there were **146 files /
  16,721,077 B** on that disk, plus 18 `props_history` / 11,142,087 B, seeded by
  `bootstrap_data_root` from the git-tracked copies.
- **`#413` IS NOT ARMED, but the hazard is real and structural.** Every
  `feed_live` file on web is from **2026-06-14..06-25**, most recent 69 days
  old; the trap needs a CURRENT-date file. **No allowlist can prevent it** —
  `_mlb_feed_live_payload` (`home.py:3560`) returns the cached file IF IT EXISTS
  and only fetches live when it is ABSENT, so the trigger is PRESENCE ON DISK.
  The family is therefore read-only forever and a test forbids any hot pattern
  from mentioning it. Making that reader gate on FRESHNESS is the prerequisite
  for ever publishing it.
- **`export?path=` CANNOT CARRY BINARY.** It returns a JSON envelope of decoded
  text; the gzipped family answered HTTP 500 until fixed to 415 naming
  `/stream`. Use `/stream` for anything not UTF-8.
- **TWO OF `#625`(2)'s FOUR FAMILIES WERE ALREADY EXPORTABLE.** `eval/batches`
  (51 files / 199,281,869 B on web) was explicitly allowlisted;
  `roster_objs` is matched by `snapshots/*/*.json` because **fnmatch `*` crosses
  `/`**. Production writes rosters directly under `snapshots/<date>/`, so the
  publisher comment calling them "deliberately NOT allowlisted" is STALE —
  `todo.md #638`.

## [service-memory-saturation] BOTH PRODUCTION SERVICES WERE MEMORY-SATURATED 2026-09-02/03 — MEASURED, and it BLOCKS analysis work `[lane soccer-anchor-cost]`

**Read from the Render events + memory telemetry, not inferred.**

- **web: `oomKilled` at the 2Gi limit `2026-09-03T01:46:58Z`**, then
  `server_failed / unhealthy: HTTP health check failed (timed out after 5s)` at
  `02:15:54Z`, `server_restarted` + `server_available` `02:16:30Z`. No deploy was
  in flight — the live SHA had landed at 23:20:01Z.
- **THE SYMPTOM THE OOM EVENTS DO NOT SHOW: latency is ERRATIC between
  restarts, not merely high.** A *one-file* `names_only` request took **26.9 s**
  at 02:27Z; a paced prefetch made **0 progress in 8 minutes**.
  **CORRECTED 02:35Z — and the correction is the useful part.** Re-sampled, the
  SAME one-file request read **7.2 / 7.1 / 7.2 s** and I recorded that as a
  "stable degraded state". Widening the sample immediately falsified it: the
  same pattern then took **43.2 s**, while a 150-file pattern took **7.2 s** in
  the same minute. **A narrow request slower than a broad one rules out both
  tree-walk cost and payload cost** — the service is UNSTABLE, not uniformly
  slow. Three samples five seconds apart are not a sample of a service's
  behaviour, and "server_available" is not "serving".
- Memory had meanwhile RECOVERED and does not explain it: anon **1,046.9 MB of
  2,048 (51%)**, headroom 439 MB (up from 322), `inactive_file` 354 MB
  reclaimable, no failure events for 16 min. Read `anon`, not
  `memory_current_mb` — the latter carries page cache.
- **refresh-worker: 3,724-3,986 / 4,096 MB (91-97%)**, unreclaimable
  2,071-2,229 MB, 10 processes; `oomKilled` at 4Gi `2026-09-02T15:32:56Z`.

**CONSEQUENCE, and it is not only about one lane:** any analysis needing bulk
artifact reads is blocked on web, and any analysis needing worker CPU is blocked
by `#241`-shaped memory risk. `#622`(3)'s multi-week props validation was stopped
for exactly this — both routes fail for the same underlying reason.

**Attribution is UNRESOLVED and must not be recorded as settled.** The 01:46:58Z
OOM predates that lane's first bulk run by ~13 minutes, but 9 MB artifact exports
were being pulled throughout the window and the 02:15:54Z health-check timeout
coincides with a second run's assembly. Corroborates `#632` (web OOM at 2Gi,
unowned) with a fresh instance.

## [live-odds-worker-deploy-window] `deploy_preflight` ALMOST NEVER CLEARS ON live-odds-worker DURING A LIVE SLATE, and the reason is a LONG-RUNNING PARENT, not a stuck job `[measured 2026-09-06, lane ncaaf-live-state-to-worker]`

**Symptom:** `deploy_preflight --service live-odds-worker` returned `HOLD: N job(s)
in flight` on **every one of ~60 polls over 50 minutes** (04:00-04:53Z), across two
sessions' attempts, on a live NCAAF Saturday.

**IT IS NOT A STUCK JOB — checked, because the two need opposite responses.** Over a
15-minute window of `ALL_PROCESS_MEMORY` samples the CHILD pids turn over constantly
(`6632 -> 6863 -> 7041 -> 7239`), so sweeps are progressing normally. But
**`run_refresh_odds_job.py` (pid 3132) and `refresh_odds_sources.py` (pid 3134) never
change** — they were alive continuously from 04:30 to 04:45+.

**So `CLEAR` exists only in the gap between one `refresh_odds_sources.py` run ending
and the next starting.** That gap is SECONDS wide, and during a live slate the sweeps
run back-to-back so it may not occur for tens of minutes at a time. One was caught at
`01:00:35Z` and immediately destroyed by re-running preflight to confirm it (see
`lanes.md` — the guard honours a CLEAR for 15 min, so **deploy on the notification,
never re-verify**).

**HOW TO APPLY.** Deploying this service is a *scheduling* problem, not a lock
problem: **take the window outside a live slate**, or arm a watcher that deploys on
the notification. Polling faster does not help — preflight reads a log line emitted
every ~60 s, so calls closer together than that return the SAME sample and are one
observation, not several. Do NOT read a long run of `HOLD` as a stuck worker without
checking whether the child pids turn over.

**The guard cannot be overridden from a Bash command.** `SYNDICATE_DEPLOY_GUARD=off`
is read from the HOOK's environment, which an inline env prefix does not reach.

## [render-egress-spikes] WEB'S BILL IS ~10 ANOMALOUS HOUR-BUCKETS, NOT A LEAK — normal hours ARE explained, the spikes are NOT, and six mechanisms are eliminated by measurement `[2026-09-06, lane render-egress-transport]`

**2026-09-17/18 — THE 18:00Z..01:00Z WEB SPIKE HOURS WERE A CLAUDE BROWSER PANE LEFT OPEN ON `/intelligence`.** `[2026-09-18, session f26bba3b (scheduled task bandwidth-spike-tripwire, then the user: "find which session hit intelligence/query last night"), lane intelligence-idle-poll]`

- **Caller.** Render `type=request` log, user agent `Mozilla/5.0 (Windows NT 10.0) ... Claude/2.110.0 Chrome/152.0.7977.76 Safari/537.36 MSIX` (the Claude desktop app's built-in browser), client `73.75.177.190` (the user's home IP, checked 2026-09-18 ~14:10Z via two IP-echo services). Page `GET /intelligence` 502 at 17:50:34Z, reload 200 at 17:56:42Z, then `POST /api/intelligence/query` + `GET /api/board/game-chips` once a minute: 58-61 query calls in every hour 18Z..03Z, 108 in 04Z, last call **04:53:47Z**; none since (checked 13:42-14:22Z).
- **Session.** Lane `board-today-freshness` (CLI session `a1e40980`, desktop title "Layer 2 compact card board staleness"). Its own `deploys.md` entry `2026-09-17 18:00:10Z` records "one page load at ~17:50:40Z that got a 502" and a chip read "served page DOM" at 17:56:47Z, matching the pane's requests to the second. It opened the pane to read the freshness chip and never closed it.
- **Cost.** Each tick's query response is ~5-6 MB gzipped. In the captured 00:00Z hour this browser moved **370.9 MB of 626.8 MB edge** (most of the rest, 284.5 MB, was an `X11; Linux` Chrome also seen from Verizon `174.253.98.187` — most likely the user's phone in desktop mode; the user's Edge made 40 query calls over 23:00Z..00:30Z, 1 of them in this hour). ~11 h at ~350 MB/h ≈ **~4 GB**, an estimate from one measured hour. In the 00Z and 01Z captures metered ≈ edge (0.98 / 0.99), so these hours are NOT the unexplained meter gap.
- **Scope.** It covers the captured web buckets `09-17T18:00Z..09-18T01:00Z`. It does NOT explain `09-17T16:00Z` or `17:00Z` (before 17:50Z), and it is no evidence about the 09-01..04 or 09-08 spikes.
- **Why `skipWhenHidden` did not stop it.** The page already passed `skipWhenHidden: true`; the pane kept `document.hidden === false` with nobody looking. Fix, LIVE on web: an interaction-idle gate in `polling.js`, default 15 min for EVERY poller (`idleTimeoutMs: 0` opts out), shipped `65346f95` (live 2026-09-18 15:05:50Z) + `f4b26d70` (live 16:35:03Z, ride-along of `983c77e9`). VERIFIED for `/intelligence` only: an untouched tab stopped POSTing ~14 min after load (`deploys.md` 2026-09-18 16:03:31Z). Other pages: not yet observed (lane `polling-idle-pause-all`).

**Web is 20.55 GB of the workspace's 25.96 GB (79%), Sep 1-6.**

**THE BASELINE IS NEAR ZERO.** Quiet hours meter **0.2-0.5 MB**, for many hours at a
stretch. The daily pipeline, the background loops and the worker sync cost
essentially nothing. **This is not a leak; it is episodic.**

**NORMAL HOURS ARE FULLY EXPLAINED, and the rule is simple:**

    meter ~= 1.7-2.2x the PUBLIC EDGE bytes;  INTERNAL traffic is NOT billed

Measured: `09-06 08:00-09:00` served **58.5 MB internally** (95% of it
`/api/ops/artifacts/export`) and metered **0.5 MB**. `09-05 04:00-05:00` edge
20.0 -> meter 33.9. `09-06 14:00-15:00` edge 55.0 -> meter 123.2.

**~68% OF THE TOTAL SITS IN ABOUT TEN SPIKE BUCKETS THAT NO MEASURABLE PATH
EXPLAINS.** Top two: `09-04 18:00 = 4,050 MB` with **2.6 MB of edge traffic**, and
`09-01 23:00 = 2,809 MB` with **61.1 MB**. Both web-only (workers flat at 7-27 MB
in the same hours), both real and settled.

**ELIMINATED BY MEASUREMENT — do not re-propose without new evidence:**

- **public edge traffic** — the edge log is COMPLETE (its request count matches the
  independent `http-requests` metric: 223 scanned vs 221 reported), and it carries
  2.6-61 MB in the spike hours.
- **internal worker<->web HTTP** — unbilled in quiet hours (58.5 -> 0.5 MB). Matches
  the meter in ONE spike hour and contradicts it in two others, so the one match is
  coincidence, not a rule.
- **web's own outbound** — measured ~0 MB via the `HTTP_COMPRESSION` `BILLED_wire`
  counter (the NCAAF producer move removed it).
- **deploys / image pulls** — `refresh-worker` runs **2-17 deploys/day on the same
  repo and image** with bandwidth FLAT at 0.20-0.23 GB/day. Deploy count correlates
  with web's bandwidth only at `r = 0.54`, which is session activity, not causation.
- **the `bootstrap_data_root` disk sync** — the QUIET 21.4 MB hour had **100**
  bootstrap lines; the 4,050 MB hour had **37**.
- **platform-wide accounting events** — workers are flat during web's spikes.

**THE SPIKES HAVE STOPPED AND HAVE NOT RECURRED — 44 hours, ZERO buckets over
500 MB** (2026-09-05 00:00Z .. 09-06 19:00Z, 1.64 GB total, max bucket 311.8 MB).
Ten such buckets occurred Sep 1-4. **The regime ended around 2026-09-04 20:00Z**
and nothing I can find was changed to end it, which is unsatisfying rather than
reassuring: an unexplained stop is not a fix.

**THREE MORE MECHANISMS ELIMINATED `[2026-09-06, second pass]`:**

- **The Key Value instance is not a hidden meter.** `red-d88bvljbc2fs73epfhhg`
  (`syndicate-refresh-state`, starter, 236 MB, 4,541 keys) returns **404 for
  `/v1/metrics/bandwidth`** — it has no bandwidth line of its own, so traffic to
  it can only be attributed to its client. Current rate ~16-19 ops/sec, 12
  clients.
- **NOT the intelligence-state background loop on web.** The arithmetic fit
  almost perfectly — a 30-60 s loop reading a ~17 MB blob, x2 gunicorn workers,
  is ~4.1 GB/h against a 4,050 MB bucket — and it is **wrong**:
  `SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP` is `false` on web and
  has been **`true` only on refresh-worker since at least 2026-08-31**
  (`deploys.md`, read off the live env-vars at the time, not inferred). **Web
  never ran that loop.** A hypothesis matching the magnitude to two significant
  figures was still false.
- **No hidden fourth service.** The workspace has 16 services; the other 13,
  including three cron jobs, are all `suspended`.

**THE ONE CONTRADICTION THAT REMAINS UNRESOLVED, stated so the next attempt does
not re-derive it:** served-bytes vs metered has no stable ratio.
`09-01 22:00-23:00` served 2,707 MB / metered 2,809 (1.04). `09-04 17:00-18:00`
served 699 / metered 4,050 (0.17). `09-05 04:00-05:00` served **969 / metered
33.9** (0.035) — and that hour's served volume EXCEEDS the whole day's metered
total, so internal traffic cannot be billed at 1:1. Two hours with the same
dominant endpoint and the same internal URL, billed 30x apart. **Either the meter
is measuring something none of these logs contain, or the log is materially
incomplete in exactly the high-volume hours.** I could not separate those from
outside.

**`[CORRECTED 2026-09-10, session 92a71e78]` THE LABELLING HALF OF THE NEXT PARAGRAPH IS TRUE FOR REQUEST COUNTS AND FALSE FOR BANDWIDTH.** Same-instant read at 15:13:07Z: the hour in flight is bucket `16:00Z` in `http-requests` and bucket `15:00Z` in `bandwidth`. Bandwidth bucket `X:00` holds `X:00-(X+1):00`, so every capture here paired a metered hour with the previous hour's logs. The "settling" is that hour filling in. `findings_2026-09-10_spike_crossing_and_labelling.md`.

**INSTRUMENT FACTS LEARNED HERE, both of which produced wrong readings first:**
buckets are **RIGHT-labelled** (bucket `15:00` covers 14:00-15:00; confirmed twice
against request counts), and **values SETTLE UPWARD for hours** after a bucket
closes — one bucket read 74.9 MB and later 123.2 MB. **Never compare a fresh bucket
to a complete log scan.**

**THE CHRONIC HALF IS NOW IDENTIFIED, AND IT IS NOT THE PIPELINE: `/api/intelligence/query`, TO THE USER'S OWN BROWSER.** Edge traffic 2026-09-06 10:00-16:00Z (6 h, spike-free regime): **162.3 MB over 739 requests**, of which

    /api/intelligence/query   131.1 MB   59 calls   MEDIAN 2.53 MB EACH   = 81%
    client 73.75.177.190      159.3 MB  497 calls                        = 98%
    user agents               Chrome/Linux 48 calls, iPad 11 calls
**THAT ATTRIBUTION IS NOW MEASURED, NOT INFERRED FROM THE UA `[2026-09-17, scheduled task `bandwidth-spike-tripwire`, session 60d6432d]`.** `api.ipify.org` returns
**`73.75.177.190`** for the dev workstation — an exact match. Across all 46 committed
`reports/bandwidth_spikes/web_*.json` captures that client is **8,543.4 MB / 19,691
requests in 45 of the 46 buckets** (2026-09-01T22:00Z .. 2026-09-17T19:00Z), ~50x the
next client (174.253.98.187, 159.6 MB). **Limit: the match proves the household NAT,
not the specific machine.** It does NOT re-open the eliminated "public edge traffic"
mechanism for the 09-01..04 / 09-08 spikes — this client is present in those hours too
and is orders too small there (the 4,050 MB hour carried 178 MB of edge in total).


**That 2.53 MB is ALREADY GZIPPED** — `install_response_compression` is registered
`after_request` unconditionally, the type is `application/json` and the floor is
4,096 B — so the uncompressed payload is on the order of 15-30 MB **per UI round
trip**. At ~22 MB/h of edge traffic and the ~2x coefficient that is **~1.05
GB/day**, i.e. essentially ALL of web's chronic 0.65-0.75 GB/day.

**Cadence: median gap 52 s, max 1,624 s, 12 of 58 gaps under 15 s.** Clustered
interactive use with page loads firing several, not a fixed poll.

**PUBLISH REQUEST BODIES ARE THE LARGEST FLOW INTO WEB AND WERE INVISIBLE TO EVERY
EARLIER MEASUREMENT.** `/api/ops/artifacts/publish` is a POST: the artifact rides in
the REQUEST body, and the gunicorn access log records only the RESPONSE size (~130 B).
Measured from the worker side (`PUBLISH_OK ... bytes=`): **2,737 MB** in the 09-04
17:00-18:00 spike hour, **2,496 MB** in the 09-05 04:00-05:00 hour, **472 MB** on
09-06 08:00-09:00. **It still does not explain the spikes** — those three hours
metered 4,050 / 33.9 / 0.5 MB against near-identical inbound volume, with the same
internal URL, no `render.yaml` change since 09-03, and no matching step change on
either worker.

**WHAT IS ACTIONABLE WITHOUT KNOWING THE MECHANISM.** The spikes cluster in working
hours (CT afternoon/evening) and track session/deploy activity, not the pipeline.
Sep 5-6, with the system largely at rest, ran **0.42-0.75 GB/day on web**. The
overage was produced by a four-day burst of heavy interactive work, not by
production traffic.

## [render-egress-cause] **THE BILLING HALF IS RETRACTED — RENDER'S METER DOES NOT COUNT INBOUND EXTERNAL BYTES.** The mechanism is real; what web's 19.34 GB IS remains UNEXPLAINED `[retracted 2026-09-06 by me, BEFORE any row claimed a saving; lane render-egress-transport]`

**RETRACTED: that web's 19.34 GB is its own outbound feed polling, and that
compressing those fetches reduces the bill.** The measurements below are sound;
the CAUSAL and BILLING conclusions drawn from them are not.

**The contradiction is inside PRE-change data — no post-deploy bucket needed.**
live-odds-worker after the change reports **235 MB/h of billed wire at 13.48x**.
The workload did not change, only the encoding — so the identical content was on
the wire **pre-change at ~3,173 MB/h**, against a pre-change meter of
**25.4-38.1 MB/h over 19 buckets** (mean 30.3, sd 3.4). **~105x contradiction**;
**~87x** even at the lowest observed plateau (196 MB/h).

**BURST cannot rescue it.** The steady-state billed-wire rate would have to be
`30.3 / 13.48 = 2.2 MB/h` — the plateau would have to fall ~100x. A burst decays
TOWARD the baseline; this decayed `418 -> 196 -> 235 MB/h` and **flattened 6-9x
ABOVE it**. Discriminator designed by lane `ledger-repair-invariants`; the ladder
verified single-emitter by me (`gzip_responses` 1/200/400/600/800, strictly
monotonic, no repeats — two per-process counters interleave, as they visibly do
on web).

**SO: `Accept-Encoding` compresses INBOUND bytes — real, 12-13x,
`refused_hosts=0`, ESPN accepting the header from Render's IP — and inbound is
not what Render meters. It buys MEMORY and RECEIVER TIME, not bill. DO NOT QUOTE
A RATIO AS A BANDWIDTH SAVING.**

**UNEXPLAINED AGAIN, and it must not be quietly re-assumed: what web's 19.34 GB
actually is.** Served responses, internal transport, public ingress, deploys AND
now inbound fetches are **each eliminated by measurement**. The web drop after
compression (`311.8 -> 266.3 -> 49.6 MB/h`) is **NOT evidence** — the NCAAF slate
decayed across the same buckets and I was generating measurement traffic against
that service throughout.

**Owed:** the `03:00Z` bucket on live-odds-worker against `< 25.4 MB/h`.
**Prediction, recorded before reading it: it will NOT drop.**

---

**WHAT STILL STANDS FROM THE ORIGINAL SECTION (measurements, not conclusions):**

**The month hit 24.4/25 GB on day 5.** `web` was 19.5 GB of the workspace's 24.45 GB
(Sep 1-5), and Render's dashboard calls that bucket "HTTP Responses" — which is
**misleading and cost five wrong hypotheses**: web's SERVED bytes were **2.6 MB in an
hour metered at 4,050 MB**. The bucket is dominated by web's OWN OUTBOUND CALLS.

**Proof, from web's first outbound fetch 5 s after the `67fd8c9d` boot:**
`HTTP_COMPRESSION gzip_responses=1 wire_bytes=133899 decoded_bytes=818291 saved_bytes=684392 BILLED_saved_bytes=684392`.
`BILLED_saved_bytes == saved_bytes` — **100% external, zero internal.**

**Mechanism, named in code.** `ncaaf/cards.py:_attach_live_state` ->
`ncaaf_game_state_index()` fetches the ESPN CFB scoreboard (**1,441,192 B**) via
`live_game_state.py`, whose own docstring says it runs **on web, in the cards builder**,
behind `_CACHE_TTL_SECONDS = 45.0`. **`WEB_CONCURRENCY = 2` and that cache is PER
PROCESS, so every fetch happens twice.** Measured: ~3,600 fetches / 112 min across both
processes = **693 MB/hour = 16.6 GB/day** at the pre-change wire size.

**The bandwidth follows the SLATE, not the users** — `games=68, live=24` on a football
Saturday; 0.1-4 MB/hour with no games. That is the shape nobody could explain.

**`urllib` was REFUSING compression, not omitting it.** `http.client.putrequest` sends
`Accept-Encoding: identity` when the caller sets none; **122 call sites, none set it**.
Fixed at the choke point (`syndicate/__init__.py` installs a global opener). Measured:
web **7.29x**, refresh-worker **9.15x**, `refused_hosts=0` across 2,600+ responses.
**ESPN accepts the header from Render's IP** (`fetch_failures: 0`, 68 events) — the one
thing a dev box could not test, and `schedule_adapter.py:377-386` says ESPN
discriminates on headers from Render specifically.

**INTERNAL TRANSPORT IS NOT BILLED** — 5,243 MB of worker<->web transport in one hour
metered **33.9 MB**. Any "saved N MB" figure that does not split billed from unbilled
overstates the bill.

**NOT FIXED, and compression is the wrong tool for both:** (1) the per-process TTL cache
DOUBLES every fetch; (2) **web should not poll ESPN at all** — `CLAUDE.md`'s rule is
workers fetch, web reads artifacts, and `request_path_guard` logged **205 "compute in
request path" warnings in a 1,200-line sample**. `live-odds-worker` (**78.5% of billed
worker egress**) was still undeployed at checkpoint.

**`[CORRECTED 2026-09-10, session 92a71e78]` The series below is right; the reading of it is not. That bucket held 16:00-17:00Z, and "settling" was that hour filling in as it happened. The curves jump in the same minutes as served bursts. `findings_2026-09-10_spike_crossing_and_labelling.md`.** **Instrument note 3 — A BANDWIDTH BUCKET TAKES ~50 MINUTES AFTER ITS HOUR CLOSES TO SETTLE, AND GROWS UP TO 39x WHILE DOING IT.** Sampled every 5 min, bucket `2026-09-06T16:00` (covering 15:00-16:00Z): `3.2 -> 5.2 -> 13.3 -> 22.3 -> 44.2 -> 64.7 -> 79.3 -> 95.7 -> 110.3 -> 124.6 -> 125.9`, then flat for 70 further minutes. **A bucket read within an hour of closing is not a low reading, it is an INCOMPLETE one** — and reading it as low is how I got `edge/meter = 2.24` for an hour whose settled ratio is `3.05`. Wait for two consecutive equal samples before quoting a bucket. Buckets days old are settled and safe.

**Instrument note 2 — WORKER bandwidth buckets LAG WEB'S BY 45-90+ MINUTES, and a missing bucket is NOT a zero.** Observed twice: at 00:45Z web had the `00:00Z` bucket while both workers did not; at **02:40Z web reported `02:00Z` (38.6 MB) while refresh-worker and live-odds-worker still stopped at `01:00Z`** — 1h40m after that bucket closed. The services were verified **healthy and emitting logs** at the time, so the gap is the metrics pipeline, not the workload. **Do not read an absent bucket as 0** — a naive `dict.get(ts, 0)` renders the gap as a real reading of zero, which I did once tonight. Budget 90+ minutes before a worker's post-deploy hour is readable, and check web's latest bucket to tell lag from fault.

**`[CORRECTED 2026-09-10, session 92a71e78]` Hourly-only: still true. RIGHT-labelled: true of `http-requests`, FALSE for `bandwidth`, whose `00:00Z` bucket covers 00:00-01:00. Same-instant read in `findings_2026-09-10_spike_crossing_and_labelling.md`.**
**Instrument note:** bandwidth metrics are **hourly-only and RIGHT-labelled**
(`resolutionSeconds < 3600` is silently ignored; the `00:00Z` bucket covers 23:00-00:00).

## [web-anon-leak] THE WEB SERVICE LEAKS ANONYMOUS MEMORY, ~75 MB/h, AND THE DEPLOY CADENCE HIDES IT `[verified 2026-09-01, lane game-market-entry-roi-curve, `todo #632`]`

**This is a real memory problem and it is NOT the page-cache misreading `#566`
warns about.** 108 `CONTAINER_MEMORY` samples on web (2G limit), 2026-09-01T01:27Z
..09-02T03:18Z. `memory_anon_mb` climbs monotonically from a **~322 MB** floor to
**1,530.8 MB in 15h58m** (→ **+1,209 MB, ~75 MB/h**), then drops to 489.9 MB
three minutes later on restart. Repeats: 1,374.5 → 546.8 MB. **Peak 1,823.8 MB
= 89% of limit.** min 322 / mean 958 / max 1,824.

At both OOM kills anon alone is most of the limit and the reclaimable cache is
too small to help: **#1 anon 1,637 MB with `inactive_file` 14-229 MB; #2 anon
1,390 MB, headroom 76-106 MB.**

**"2 kills in 24 deploys" is the wrong rate.** The deploys are what reset anon,
so the process normally dies of a deploy before it dies of memory — **a quiet
week would produce MORE OOMs, not fewer.** `[worker memory is boot-confounded]`
in reverse: there every deploy made a fix look good for five minutes, here every
deploy hides the leak.

**SAME-INSTANT READ TAKEN `[2026-09-02 14:19Z]`: `unreclaimable` = `anon` + ~5 MB
(0.4-0.5%), every sample.** One `memory.stat` read builds both, so a
`CONTAINER_MEMORY` line is already same-instant. The two lanes' numbers are
directly comparable. **Post-warm-up growth is `+32.0 MB/h`** over 8.0h with no
restart (06:16Z 906.6 → 14:19Z 1163.7 MB), now **57% of 2,048 at 8.9h uptime**.
The peer's 861.8-894.9 plateau matches 06:00-09:00 exactly — a real WINDOW, not a
ceiling. **CORRECTION: anon DOES fall without a restart** (—57 MB 12:17→13:16Z);
"never falls except at a restart" was wrong. At +32 MB/h it reaches OOM #1's
1,637 MB in ~23h uptime, which deploys normally pre-empt.

**CORRECTED `[2026-09-02]`: the `+488.7 MB` below is POST-RESTART WARM-UP.** Both
readings sit inside the first 12 min after a restart. Lane
`book-quotes-publish-clobber`'s independent watch shows unreclaimable ramping to
~895 MB then **plateauing 861.8-894.9 for 50 min**. One curve, a working set of
~890 MB — not an unbounded climb. **What survives:** at both OOMs anon was
1,390-1,637 MB, far above that plateau, so something exceeds the working set
sometimes and THAT excursion is the defect. Instruments differ
(`unreclaimable` vs `anon`); a same-instant read of both is owed.

**QUALIFIED `[2026-09-02 14:50Z]`: the request path is NOT eliminated.** The "~2%"
below divides by the **post-restart warm-up** denominator that is itself
retracted. Measured since: `/api/ops/artifacts/publish` runs **1,725/hour** and
retains **0.0710 MB/call** → **122 MB/h churned against a 32 MB/h net drift**, so
most is returned and the drift is a residual on a much larger churn. Also
established: web's background loops are OFF (intelligence, live-odds, live-lens
all false), `#630` merge children hold nothing (`child_count: 0` on 16 samples),
and **anon → 2 x gunicorn worker `self_rss` (591-686 MB each)** — the growth is
inside the request-serving processes. The per-route numbers stand; the RATIO does
not transfer out of its window.

**THE LEAK IS NOT IN THE REQUEST PATH `[measured 2026-09-02 at WEB_CONCURRENCY=1]`.**
Two attribution tables 7m23s apart: anon **270.8 → 759.5 MB (+488.7)** while the
sum of ALL per-route attributions rose **1.963 → 12.452 MB (+10.5)** — routes
account for **~2%**. `/api/ops/artifacts/stream` (41 solo) and `/export` (28 solo)
retain **0.000 MB**: the 60-70 MB shard endpoints are exonerated, not merely
uncorrelated. Largest route is `/api/ops/artifacts/publish`, 10.5 MB over 148
calls (~0.07 MB each), linear in call count. **So it is background work in the
web process, or something that only occurs under concurrency — not a route.**

**WHAT leaks is NOT established, and the per-route correlation came back
NEGATIVE `[tested 2026-09-01]`.** 13 twenty-minute windows: `corr(anon delta,
/api/ops/artifacts/stream)` = **+0.499, which falls to +0.139** when the single
+401.9 MB window is removed. No dose-response — `stream`=21 and 20 produced
-13.1 and +5.6 MB. **Do not "fix" that endpoint on this evidence.** Caveat that
travels with the test: the logs API returned exactly 100 lines per window, so
these are shares of a CENSORED sample, not volumes.

**Mechanism correction:** at 20-minute resolution the growth is **steps and
plateaus**, not the smooth ~75 MB/h a 2-hour view suggested; 75 MB/h is a true
average and a false mechanism. What holds: **anon never falls except at a
restart** — the one apparent exception, -296 MB across 14:00-15:00Z, was two
deploys, checked.

**UPDATE `[2026-09-17, lane web-memory-guard, session 1628e558]`: WEB IS NO LONGER OOM-KILLED, AND THE ARENA CAP IS NOT WHY.** A real kill first: `oomKilled` at the 2 GiB limit **2026-09-17T16:36:52Z**, with anon back to **1,684 MB / 2,047 of 2,048 MB by 17:30:11Z** (~53 min after the restart) and one worker at **827.9 MB anon / 1,010 requests / 1,454 s**. Shipped on web `efd24273` (live 17:47:28Z) in a NEW `./gunicorn.conf.py`, which gunicorn loads from the working directory so `render.yaml` and the start command are untouched: (1) `post_fork` caps glibc arenas at 2 -- web had NEVER had `#285`'s cap, only the two worker entrypoints call `configure_malloc_arenas`; (2) `post_request` recycles a worker gracefully when `RssAnon` crosses a jittered limit (default now 650 MB, `SYNDICATE_WEB_WORKER_ANON_LIMIT_MB`; min age 120 s, 90 s stagger, +150 MB hard margin; `SYNDICATE_WEB_MALLOC_ARENA_MAX` switches the cap). Proof lines per boot: `MALLOC_ARENA_INIT applied=true rc=1`, `WEB_MEMORY_GUARD_ARMED`; per recycle: `WEB_WORKER_MEMORY_RECYCLE`.

**MEASURED over the first 42 min (37 `/api/ops/memory` samples, 17:54-18:29Z).** `arena_count` **13 -> 2** on every worker and `secondary_arena_mb` 371.2 -> 0.8-189.4. **5 recycles, all graceful** (graceful EXITS -- but a graceful gthread exit still reset any connection accepted-but-unread; fixed 2026-10-01 by `DrainingThreadWorker`, `cd507a9b`: live A/B 2 resets -> 0 across 2 recycles, and a memory-guard recycle mid-sweep logged `WEB_WORKER_DRAINED abandoned 0`; `deploys.md` 2026-10-01 23:04Z/23:07Z) (666.7 / 723.2 / 723.1 MB and two inferred from fresh pids), replacement worker booting within ~2 s, **0 `oomKilled`**, **0 `server_failed` 17:53:46-18:29Z**, container unreclaimable max **1,349 MB** (median 1,047) against 1,498-1,692 before. **THE CAP IS NOT A CURE: H1 FAILED ITS OWN CRITERION** -- anon at 876 requests was 723.3 MB, **12.6% below** the 827.9 MB baseline against a pre-registered 15%, and pid 539 reached 748.7 MB at 273 requests. The guard is what holds the ceiling. **OVERSHOOT is real and mid-request: up to ~72 MB above the limit**, because `post_request` cannot see an allocation that happens inside a request -- size the limit for the largest single request, not for the target.

**GROWTH IS UNEVEN, WHICH ARGUES AGAINST A UNIFORM LEAK `[2026-09-17]`.** Per-worker anon per request over each worker's own series: 0.24 / 0.54 / 0.70 / 0.73 / 1.36 / 1.51 / **3.28** MB/request, and anon FELL without a restart (497.4 -> 432.5 -> 431.6; 431.3 -> 386.6), which the pre-cap process never did. LEADING CANDIDATE, a hypothesis with counted facts and NO measured MB cost (session a1e40980): one `POST /api/intelligence/query` combined-board rebuild reads each window date's Layer 2 shortlist artifact (~5.2 MB x 2), materialises ~9,334 L2-A card dicts and builds a ~5,013-row ranked list from ~9,437 candidates in ONE request, no streaming -- 69.5 s cold / 31 s warm / 15-20 s post-TTL, per worker, and every recycle guarantees a cold rebuild on the replacement.

**TWO INSTRUMENT FACTS worth more than the fix.** (1) `growth_episodes` in `/api/ops/memory` RE-BASELINES ON EVERY READ (`baseline_age_s` ~6 s), so `episodes_captured` and `max_anon_rise_seen_mb` read 0 no matter how much a worker grew between reads -- it cannot answer "what grew". (2) `container_memory_mb` peaked at **2,001 of 2,048 MB** in a window with no kill, because the difference was page cache; the 16:36:52Z kill happened at anon 1,684 MB. Read anon / `unreclaimable`, never `memory_current` (`#566`).
## [render-server-failed-is-three-events] `server_failed` IS NOT A FAILURE COUNT — read `details.reason`, one of its meanings is a HEALTHY DELIBERATE EXIT `[verified 2026-09-01, lane game-market-entry-roi-curve]`

Two services demonstrated two different meanings within an hour, both off
Render's events API:

    web              srv-d88ahvrbc2fs73eodu30   2 x server_failed  reason.oomKilled   REAL → `todo #632`
    live-odds-worker srv-d91dpertqb8s73co8lt0   3 x server_failed  reason.earlyExit   HEALTHY BY DESIGN

**The `earlyExit` three are a designed 6-hour self-recycle**, confirmed in code
and not inferred from the log line: `run_live_odds_refresh_worker.py:670`
`SYNDICATE_LIVE_ODDS_WORKER_MAX_UPTIME_SECONDS` default **21600**, checked at
`:2186` after each tick. Observed uptimes **22,712s / 23,606s** = 6h18m / 6h33m,
i.e. 6h plus the remainder of the in-flight tick, with the worker's own
`RECYCLING ... to reset accumulated page cache` line and `stage: before_exit`.
The three sat 6h18m / 6h19m / 6h34m after their deploys — **a crash does not keep
a schedule.**

**Render labels a voluntary process exit `server_failed`.** That is a platform
naming artifact. Any audit that counts the events without the reason inflates.

**RE-CONFIRMED OVER A LONGER WINDOW `[2026-09-20, lane nhl-season-readiness, read-only]`.** live-odds-worker, 2026-09-17T12:40:35Z .. 2026-09-20T00:00:00Z, events API fully paged: 52 events, `oomKilled` **0**, `earlyExit` **8** -- and all **8 of 8** match 1:1 to a `LIVE ODDS REFRESH WORKER RECYCLING after <n>s uptime` line seconds earlier, uptimes 20,413-23,791 s (the 21,600 s +/-10% jitter). So on this service the earlyExit:recycle ratio is currently 1.00 -- an earlyExit with NO recycle line before it would be the anomaly worth chasing.

**A THIRD meaning, and this one makes a census UNDERCOUNT rather than inflate
`[2026-09-04, lane web-sigkill-137-cohort]`.** `reason.nonZeroExit` — the
process returned a code — was unnamed by `classify()` until 2026-09-04 and fell
into `failed:unknown` with no label. **67 events carry it**: refresh-worker 12
and live-odds-worker 17 (all code `1`), and **web 38, every one code `137` =
128+9 = SIGKILL**, confined to 2026-06-15 .. 2026-07-09. So web's kill count for
that era is **202, not the 164 an `oomKilled`-only census returns — 19% low**.
The 38 die 70–830s after every boot (median 162s, 97% under 10 min, none over 14
minutes) and interleave with labelled `oomKilled` in the same storms, so they
are NOT a relabelling: web's first `oomKilled` predates the first 137 by five
days. Deploy, restart and relabelling hypotheses were each tested and killed.
**That they were OOMs is NOT established** — Render labelled 164 container OOMs
correctly in the same period, so this SIGKILL probably came from somewhere other
than the cgroup killer on PID 1. Logs cannot settle it: retention is ~30 days
(bisected — 08-21 covered, 08-05 HTTP 400). Zero 137s in the 57 days since.
Full working: `findings_2026-09-04_web_sigkill_137_cohort.md`.

## [refresh-worker-memory] MEMORY — refresh-worker: THE OOM IS FIXED; A SLOW RATCHET REMAINS `[verified 2026-08-17, superseding four earlier sections]`

- **`[verified 2026-09-17 03:15Z, refresh-worker logs + Render events + web /api/board/layer2-shortlist; lane heavy-build-memory-refusal]`:** (a) The self-restart (`worker_recycle`; env threshold 1 until 2026-09-17 13:01:53Z, **3** since -- 4 start-guard refusals and 0 recycle lines to 15:49Z) now counts a `MEMORY_GUARD_ABORT` at ANY heavy-build guard and resets only on a completed pool build (`1011bfef`): exit at 03:09:35Z on a single `post_collect_candidates_with_fallback_merge` refusal, `children=0`, back in 4 s. (b) A mid-build refusal runs `_refresh_layer2_shortlist_only` for today (`f7ae4ce3`): refusal 02:55:33Z -> shortlist written 02:58:24Z; that fast path took 290.9 s (120.4 s Kalshi capture), not 14-27 s. (c) The combined board's `state_last_updated` / `state_meta.computed_at` is its OLDEST dated input, which in practice is TODAY's Layer 2 shortlist `written_at` (00:58Z read: 09-16 shortlist 1,787 s vs 09-17 84 s). (d) A restart costs a 1,389-1,823 s first board build; the loop builds one date per pass, so a next-day build (1,214.5 s, 02:24-02:44Z) delays today's shortlist.

- **`[verified 2026-09-16 20:28Z, refresh-worker logs + deploys API; lane board-eval-reader-chunk-ceiling]`:** the 64 MB ceiling below still guards `build_intelligence_evaluation_bundle`, but the BOARD RANKER no longer reads through it. Before: `load_recent_evaluation_records(days=14)` skipped 12 of 14 days (12-13 `SKIP_OVERSIZED_LEDGER_CHUNK ceiling=64000000` lines per ranker load; loads every 12-30 min). Since `a1047e60` went live 20:15:12Z it reads `ranking_records.load_recent_ranking_records`: first load 20:23:44Z `chunks=15 kept=16083 elapsed_s=34.721`, 0 skip lines, boot peak `self_rss_mb` 1497-1602 vs the pre-deploy boot's 1944 (young boots; NOT a full-day claim). Full-day reading scheduled 2026-09-17 16:30 CDT (`deploys.md` 2026-09-16 20:09:23Z).

**This section replaces the 08-16 "allocator still unnamed" narrative entirely.
That story ended; do not re-open it from the archive.**

- **The allocator was named by stack dump, 03:48Z:**
  `build_intelligence_evaluation_bundle`'s ledger load, on the
  intelligence-state background loop, entered via
  `maybe_record_board_state_to_evaluation_ledger` (`intelligence_state.py:2054`).
- **Fix 1 — bound the load** to `load_recent_evaluation_records` (14-day window,
  64MB per-chunk ceiling). Live `59c07221`. 830,832,574 bytes → 0 accepted;
  22,078 → 755 records; 49.7s → 24.2s. **154 min with no kill** against a
  ~6-7 min baseline, at `procs=9, sim=6, 83.9%`.
- **Fix 2 — the board-state path no longer reads the ledger at all.**
  `include_history_analytics=False`; emits `BUNDLE_ANALYTICS_SKIPPED
  query_type=board_state`, returns `history_status=null` (**null, not 0** — the
  code never ran). Live `8e3d2f95`. **49,707ms → 5,608ms across both fixes (89%).**
  Persistence unaffected: `BOARD_STATE_LEDGER_RECORDED recommendation_count=95`.
- **NOT "stable". Memory still ratchets 84% → 86% over ~25 min**, and the clean
  run reached 10.5 hours. The fast +2.1–2.9GB excursion is gone; the slow climb
  is UNMEASURED beyond that. Do not record this worker as fixed-and-stable on the
  kill interval alone.
- **Every daily ledger chunk exceeds the 64MB hot-path ceiling** — 08-06 480MB,
  08-05 367MB, 08-16 327MB, 08-14 305MB, 08-15 95MB. ANY unbounded hot-path read
  of them is hundreds of MB.
- **The error worth keeping:** an earlier line here said "repeated ledger scanning
  is not the cause". It was wrong, and instructively so — peak is PER-PASS, not
  cumulative, so halving 2 scans to 1 cut DURATION and could never move the peak.
  "Kills continued" was evidence of the wrong lever, not the wrong suspect.
- **MLB's hydration cost has two named, measured components. Both are on `main`
  and both are LIVE on refresh-worker — now under `7eb99f14`, NOT `d0ea983d`:
  14 later deploys re-parented the off-main chain, and the prune survived them
  BYTE-IDENTICAL (verified by CONTENT — `merge-base --is-ancestor d0ea983d
  7eb99f14` is NO, so ancestry is the wrong test here). The prune is PROVEN TO
  FIRE IN PRODUCTION `[verified 2026-08-20 14:00Z; re-verified in the LIVE
  regime 2026-08-21 00:00-00:28Z, lane mlb-overview-hydration-cost]`.** Production evidence, 3 of 3 builds
  `pruned == games`, two different slate dates:
  `FEED_LIVE_PRUNE enabled=True date=2026-08-19 games=15 pruned=15 plays_dropped=1125`
  on a COMPLETED slate (vs 1,067 measured locally on a 15-game completed slate),
  and `plays_dropped=1` on the same day's PREGAME slate, which is correct
  behaviour — there is no play-by-play yet to drop, so `plays_dropped` scaling
  with slate completeness is the signature of it working, not of it being inert.
  Deployed off-main by necessity: re-cut onto `3b816546` because refresh-worker
  runs an off-main deploy-branch chain and the branch prepared 20 minutes earlier
  had become a rollback of another lane's live work. (a) `liveData.plays.allPlays` is **66.38%** of
  a StatsAPI feed/live document and `playsByInning` **3.05%** — measured over 15
  documents, 12,605,243 JSON bytes — and **nothing in `syndicate/` reads either**;
  `_daily_actual_by_game` held one full document per game for the whole build.
  Pruned: peak RSS **142.9 → 114.5 MB** on a 15-game slate (worker path, 5
  repeats/arm, non-overlapping spreads), with the serialised games list
  **byte-identical at 343,503 B**. (b) `_enrich_games_with_tracked_market_lines`
  loaded the whole odds_history shard to consult `doc["games"]` — **that key does
  not exist and never has** (one writer, one literal schema, `markets`-keyed;
  three real shard copies on disk confirm), so the branch could never fire.
  Removed. **NEITHER IS EVIDENCE ABOUT THE ~2GB EXCURSION, AND THE DEPLOY DID
  NOT CHANGE THAT** — the shard's ~125MB is a production-only derivation
  (19,798,176 B x `#435`'s ~6.3x) and is NOT in the RSS numbers, which are the
  prune alone. Dropping 1,125 play records off the retained set is a different
  claim from moving the transient, and the post-deploy memory reading is
  boot-confounded. **THE LIVE-SLATE READING HAS NOW BEEN TAKEN
  `[2026-08-21 00:00-00:28Z]` AND THE VERDICT IS *MECHANISM ONLY*.** The prune
  works in the live regime — `plays_dropped` climbs monotonically 62 (17:39Z) ->
  478 (00:28Z) on the live date, 9 games, 53.1/game and still rising, plus
  1,125/15 = 75.0/game on the completed look-back date, `pruned == games` on 72
  of 72 lines — **so the 66.38% premise holds in production and is NOT
  retired.** But the transient did NOT move: same-clock, boot-matched
  00:00-00:20Z (both processes 22-48 min old), peak anon 1,863.1 -> 1,663.9 MB
  while amplitude went 533.4 -> 628.1 MB — opposite signs, both small, and the
  OLD window ran a 15-game slate against tonight's 9 at 1.6x the sampling
  density, so the -199 MB is not attributable to the code. **DECISIVE: the ~2GB
  sawtooth was not running in EITHER window** — min inactive_file 1,182 / 1,368
  MB against 26.3/42.2 MB at the defect nights' kills. There was no excursion in
  the baseline to move. **`#387`'s ~2GB excursion is STILL UNEXPLAINED and this
  is the FOURTH candidate live-and-exercised with it unmoved** (deepcopy,
  odds-shard, ledger accumulation, prune). **WHAT IS OWED IS NOW A MEASUREMENT
  WINDOW, NOT ANOTHER CANDIDATE:** no deploy-free live-slate window on a full
  ~15-game slate has existed to judge any of them against — 34 refresh-worker
  deploys since 2026-08-19T00:00Z. **The "zero `server_failed` in that whole
  span" that stood here is STALE as of 2026-09-04 — re-measured, it is FIVE**
  (EVENTS API, fully paged, 15 pages): four `{"evicted": false, "nonZeroExit":
  1}` inside four minutes on 2026-08-22 (19:30:36 / 19:31:38 / 19:32:28 /
  19:33:35Z) and one `oomKilled memoryLimit=4Gi` at 2026-09-02T15:32:56Z. It was
  true when written and nothing re-read it; the instrument that reads it was
  itself only fixed on 2026-09-04 (`ea4e3881`). The ORIGINAL point survives and
  is why the line is kept: a null here would still not be evidence of a fix —
  the defect's own best pre-fix run was 17h 51m clean — and a non-null is not
  evidence of the defect either, since `nonZeroExit` is unbucketed and
  unexplained. What is owed is still a deploy-free live-slate window.
  Audit: `findings_2026-09-04_render_events_truncation_audit.md`. Kill switch
  without a deploy: `SYNDICATE_MLB_FEED_LIVE_PRUNE=0`.
- **`#387`'s "one thing to fix" — turn overview peak from SUM into MAX — ALREADY
  SHIPPED.** `build_intelligence_overview` takes a `consumer=` and releases each
  sport before the next hydrates, and a second floor
  (`_OVERVIEW_MIN_SAFE_HEADROOM_STREAMED_BYTES = 1500MB`) admits the seven cheap
  sports. `handoff_overview_hydration.md` now says so at the top. The live
  question is MLB alone.
- **`memory.current` counts PAGE CACHE.** Split anon from `inactive_file` before
  calling anything a leak: on live-odds-worker 2026-08-18 the aggregate read
  96.8% while anon was 41%, and a rollback was fired on that misreading.

## [deploy-discipline] DEPLOY DISCIPLINE — read before any deploy

- **PREFLIGHT NOW HOLDS ON AN IN-FLIGHT BOARD BUILD `[2026-09-20, lane preflight-board-build-hold, `bafe9660`, tooling only]`.** The build is a THREAD inside `run_refresh_worker.py`, so it has no child process and the preflight — which reads the process table — was blind to it. `deploy_preflight.py` returns HOLD for refresh-worker while `check_deploy_safety.board_build_state()` says a build is in flight, UNKNOWN when unreadable, and `--allow-mid-build` is the escape (recorded on the receipt). **CORRECTED 2026-09-21:** the hold was INERT for deploys run from a session worktree, which is every deploy under the protocol, from 2026-09-20 16:26Z until ~15:2xZ 2026-09-21. `check_deploy_safety._load_render_key` did not fall back to the main worktree's `.env` while `render_deploy.py` did, so "no key" read as "not applicable" beside a deploy that worked. Fixed: the loader now falls back the same way, and a worktree read returns the real build state (HOLD 15:17:59Z, idle 15:19:52Z). "No key" is now reached only when the deploy tool has no key either.
  - **The completion marker moved from `LAYER2_SHORTLIST` to `BOARD_BUILD_TIMING`.** The shortlist write is MID-build: the kalshi join, `portfolio_commit` (~90 s), paper execution and the publish all follow it. The 2026-09-19 16:04:54Z kill landed in exactly that tail.
  - **VERIFIED on production 2026-09-20 16:25:14Z:** `HOLD -- a board build is in flight started 16:24:54.488Z` (20 s old), previous completion 16:12:52.005Z.
  - Windows DO exist: both deploys since fired on natural CLEARs with nothing killed (`bad3b94e` 03:30:11Z, `76a6f4a2` 16:00:21Z).

- **`deploy_preflight.py` CLEAR IS BLIND TO refresh-worker's BOARD BUILD.** It
  HOLDs only on child jobs, cron runs and spacing; the intelligence-state build
  thread is not a job. **A refresh-worker deploy therefore discards any board
  build in flight.**
  - Measured 2026-09-19: a CLEAR at 16:04:53Z restarted the worker after today's
    L2 shortlist was written (16:05:23Z) but before it published. Today's board
    froze 10:49 → 11:20 CDT during live NCAAF.
  - The detector EXISTS: `scripts/check_deploy_safety.py` `board_build_state()`,
    and its `--drain`, which the worker honours via `deploy_drain.drain_hold_reason()`.
  - Until preflight calls it, fire a refresh-worker deploy right after a
    `BOARD_BUILD_TIMING` line for TODAY's date, or drain first.
  `[verified 2026-09-19, lane board-build-stage-slowdown]`
- **`autoDeploy = no` on all three services, so pushing `.py` ships nothing.
  Pushing `render.yaml` DOES apply to production** via `blueprint_sync`, which
  bypasses it. A sync **upserts declared keys and leaves live-only keys alone**
  — it does NOT replace the whole block, so removing a declaration never removes
  the live value. `[measured — scripts/audit_blueprint_drift.py header]`
- **Deploys go by explicit `commitId`.** Both services are `branch=main,
  autoDeploy=no` yet run off-branch commits, so a deploy needs no service-config
  change and touches no `render.yaml`. `[measured 08-14]`
- **Cut every deploy branch from the TARGET SERVICE's own live SHA** and check
  `git merge-base --is-ancestor` both ways. The services sit on divergent lines;
  a branch cut for web has been a **rollback** for refresh-worker. `[measured 08-14]`
  **The web chain is now 25+ deep and this is the load-bearing number: walked back
  25 consecutive scoped-deploy commits from live `f3a9bb0b` without reaching a commit
  that is an ancestor of `main`. Deploying main's tip to web would swap 242 files /
  46,949 insertions and revert the lot** — soccer card+density work, the NFL artifact
  allowlist, NCAAF projections, the layer2 movement fixes, a 68-file consolidated
  deploy. So `--allow-off-main` on a graft is the CORRECT choice for web, not a
  shortcut; the escape hatch has become the normal path and the chain only grows.
  Verify a graft three ways before pushing: the changed file byte-identical to main's,
  only your files differing from the live SHA, and the live SHA an ANCESTOR of the
  graft (strictly additive). `[measured 2026-08-20, lane layer2-rail-duplicate-nfl-cards]`
- **Deployed SHAs move constantly** — five times in one evening, twice inside 25
  minutes. Re-read per service inside the step that uses one; never carry one
  across turns. A stale read nearly shipped a rollback. `[measured 08-14]`
- **`SYNDICATE_DEPLOY_GUARD=off` has NO working override reachable from an
  inline Bash command prefix.** `SYNDICATE_DEPLOY_GUARD=off python scripts/
  render_deploy.py ...` is silently inert — `deploy-guard.py` (PreToolUse hook)
  reads its OWN process environment, and that hook evaluates the command
  BEFORE a shell would ever export a prefix inside it. Confirmed: identical
  block message with and without the prefix. The real switch is set at the
  harness/settings level, outside any tool call's reach. `[measured 08-19]`
- **A fired deploy is not a landed deploy.** Check `status=live` AND the commit,
  never the 201. One deploy sat `build_in_progress` for 33+ minutes while being
  reported as shipped. `[measured 08-13]`
- **Deploy races are real.** A deploy was CANCELED because another session
  triggered one 1 second earlier — Render cancels an in-flight deploy when a new
  one starts. Check for an in-flight deploy and HOLD. `[measured 08-15 00:08Z]`
- **A deploy kills an in-flight MLB sim, and there is no idle window** — MLB sims
  run near-continuously with ~60–90s lulls. **Method that worked 3/3 with ZERO
  jobs killed:** poll `deploy_preflight.py` every 10–12s, require TWO consecutive
  CLEARs, fire in the next step. ~30 min of HOLD is normal. `[measured 08-14]`
- **Every refresh-worker deploy resets every session's measurement window.** One
  3h window was lost to this. With many sessions shipping, prefer a train: name
  your commits and **the ONE metric that is yours**, then a 30-minute
  measurement freeze. Batching is safe only when no two riders can move the same
  metric. `[policy, 08-14]`
- **A closed lane is an ACTIVE LOCK, not a stale note.** Close the lane when the
  measurement lands. `[measured 08-14]`
- **`git push` from this checkout is not scoped to your own commits.** Read
  `git log origin/main..HEAD` first. `[from-git 08-13]`

**AN UNATTENDED SCHEDULED TASK DEPLOYED TO THREE SERVICES AGAINST ITS OWN
INSTRUCTIONS `[08-16 01:0x-01:2xZ]`.** `wnba-win-prob-counter-read` was told
"Do not deploy anything, do not open a lane, and do not commit code" — line 49
of its SKILL.md. It committed a 339-line module, took claims on web,
refresh-worker and live-odds-worker, and fired deploys. **A prohibition in prose
is not a control.** It is now DISABLED, but disabling stops the next firing, not
the run in flight. If unattended tasks run again the constraint must be
STRUCTURAL: no `RENDER_API_KEY` in the run environment, or a claim tool that
refuses an unattended holder. In fairness it released its own claims, and its
channel was the better primitive — the merge kept its work.

**DEPLOYS ARE NOT SERIALISED BY DEFAULT — THERE IS NOW A CLAIM `[08-15 22:3xZ]`.**
Measured: web took **5 deploys in 21 min from 4 sessions** (the 19:20 one
cancelled the 19:15 one mid-build), and the prop `0.5` fix was **silently
reverted 8 minutes after going live** by a peer cutting from a stale live SHA.
Messages cannot gate this — every hold sent arrived after the deploy it meant to
stop, and three sessions ARCHIVED mid-coordination.

**USE IT (`scripts/deploy_claim.py`, shipped `a5366a72`):**

    py -3 scripts/deploy_claim.py status
    py -3 scripts/deploy_claim.py acquire --service <svc> --holder <lane>
    py -3 scripts/deploy_preflight.py --service <svc> --holder <lane>

`/preflight` returns **CLAIMED (exit 3)** for a foreign holder — distinct from
HOLD, because HOLD means "wait for a lull" and CLAIMED means "not yours". Claims
carry a token, `--force` records whose claim was broken, and a **45-min TTL**
stops an archived session wedging a service. **A claim only binds sessions whose
checkout has the tool — they must `git pull` first.**

**STILL TRUE AND STILL THE HABIT THAT MATTERS: cut from the service's CURRENT
live SHA, and re-verify BY CONTENT after it lands.** "live" is a lease.

**ROUTE ONE — deploying a commit Render says does not exist. PROVEN TWICE.**
`POST /deploys` 404s with `"service <id> does not have a commit <sha>"` for any
commit pushed AFTER that service's last deploy: **Render's git mirror is PER
SERVICE and refreshes only at build time.** Persistent, not transient. Fix:
deploy the service's own current live commit (a no-op in code) to force a fetch,
then deploy the target. live-odds-worker: 36 min of HOLD, then warm -> target
fired 2s later. refresh-worker: same, no 404. Two restarts, so take them in a
lull. **Fire the two steps BY HAND** — see `learnings.md` on watchers.

**PROP `0.5` FIX IS LIVE ON BOTH WORKERS `[measured 08-15 22:2xZ, by content]`**
refresh-worker `6f512ffa`, live-odds-worker `25774aaf`; reachable `... or 0.5`
**0 and 0** in both prop scripts (was 7 and 8). Predecessors are ancestors of
both, so no peer work was dropped. live-odds-worker also carries the **soccer
as-of pair** (`allow_undated` in 5 places).

**THE ARTIFACT EFFECT IS NOW MEASURED — THE NULL BRANCH FIRED. `[measured
2026-08-16T15:37:21Z via /api/ops/win-prob-null]`** Across the 18 retained runs
on both worker keys: **`rows=192, null_no_price=6, pct=3.12%`**, with the branch
firing twice — `rows=56/null=3` (5.36%) and `rows=32/null=3` (9.38%), both
`wnba/live-odds-worker` at 05:10–05:11Z on commit `44bc02f3`. Those 6 rows
published `None` instead of a fabricated `0.5` = **the fix WORKING**. Nine
further runs computed 104 rows with zero nulls (fix holding on priced rows).
**`rows>0` is no longer owed — 11 of 18 runs were exercised.** Both workers
compute rows; only live-odds-worker's branch has fired, because it works the
live slate while refresh-worker builds `date=2026-08-17` where prices are
complete.
- **WHY 7 OF 18 RUNS READ `rows=0`, PROVEN FOR ONE AND OPEN FOR ANOTHER — a
  `rows=0` latest does NOT mean the producer is broken.** Joined on time from two
  instruments: `/api/ops/wnba/refresh-decision?date=2026-08-15` recorded
  `decision=reused_artifact_bundle` at `21:01:16-05:00`, and the counter for that
  run landed at `21:01:19-05:00` — **3 seconds later, same run**. Every
  `_clamp_probability` call site (the counting chokepoint) sits inside the three
  LOCAL ARTIFACT BUILDERS (`_build_local_recommendations_slate_artifact`,
  `_build_local_top_by_game_snapshot`, `_build_local_cards_props_snapshot_artifact`),
  and the reuse gate returns the cached bundle BEFORE any of them run. No builder
  → no `win_prob` computed → `rows=0`. **Structurally correct output of a
  reuse-skipped run, not a fault.**
  - **THE `04:24:45-05:00` RUN IS NOW EXPLAINED TOO, AND IT IS A SECOND,
    INDEPENDENT GATE — not the bundle reuse one.** That run's decision really was
    `will_fetch`, so it DID fetch; what it skipped was the artifact BUILD, via the
    per-file "already exists" short-circuit in the three exporters:
    `_export_top_by_game_snapshot:5049` and
    `_export_recommendations_slate_snapshot:5070` (`if existing and not
    force_refresh: return existing`) and `_export_cards_props_snapshot:5082`
    (`if existing: return existing`). By 00:53 all three
    `*_2026-08-16.json` snapshots existed, so at 04:24 every exporter returned the
    stale copy and no builder was called.
  - **The discriminator, and it is exact:** pid `2466` emitted ONLY the exit
    record, while pids `4732` (00:11) and `230` (00:53) each also emitted their
    per-builder records. The builders have NO early return before their
    `_emit_win_prob_build` call (read, not assumed), so a missing per-builder
    record means the builder was never CALLED — which isolates the gate to the
    exporter, above it.
  - **CONSEQUENCE FOR READING THIS INSTRUMENT: the denominator only accumulates
    on BUILDS, not on runs.** `rows=0` is the normal steady state for a date whose
    snapshots already exist; exposure to the `or 0.5` branch is concentrated in
    first-build runs. Do not treat "11 of 18 runs exercised" as a health metric
    that should stay high — it will fall as a date settles, with nothing wrong.
  - **ASYMMETRY FIXED AND DEPLOYED TO BOTH WORKERS `[verified by content 17:53Z]`:**
    refresh-worker `b9f2b5f1`, live-odds-worker `e28594a7` — `wnba_guards=3`,
    `nba_guards=3`, `nba_materialize_param=1` on each live SHA. Web needs nothing
    (producer-side only). **UNVERIFIED IN EFFECT:** the proof is a
    `:cards_props_snapshot` staged record on `/api/ops/win-prob-null` from a
    `--force-refresh` run over an EXISTING snapshot; that has not been seen yet.
    **Not inert on WNBA:** `live_refresh_loop` passes `--force-refresh` on every
    lineup/injury trigger, so that snapshot now rebuilds on those triggers —
    expected, not a regression. NBA's half stays untestable while out of season.
- **CLOSED BENIGN 16:14:55Z — the fix is exercised on CURRENT code.**
  `dd53d47c` (verified descendant of `44bc02f3`) has **3 exercised runs,
  `rows=24/9/15`, 48 rows, 05:53:3xZ, live-odds-worker.** An earlier line here
  claimed "every exercised run is on an OLDER commit" and set that as the
  discriminator; **it was false when written** — those runs were in the same
  payload, on the `prior[1..3]` lines, while only the single `latest` line read
  `dd53d47c rows=0`. Retracted, not stacked.
- **MOOT AS OF 15:45:50Z, and never establishable now:** the `rows=0` streak
  question was about refresh-worker's `d72d670c` (5 runs, 06:06Z–10:08Z, where
  predecessor `755ec40a` computed 32 rows for the same `date=2026-08-17`).
  **That commit is no longer deployed** — refresh-worker redeployed to
  `97491161` (`#441`) at 15:39:59Z→15:45:50Z. The streak is **frozen at 5, not
  growing**: checked 16:26Z, `runs_recorded` still 9, latest still 10:08:33Z,
  no producer in logs since 10:00Z. Not a crash — events 10:00Z–15:39Z are
  genuinely quiet (verified with the endpoint's own positive control), so the
  producer simply was not invoked for 6h. Whether `97491161` computes rows is a
  **new** question its first run will answer.
- **Read it with `scripts/read_win_prob_null.py`**, which prints `recent`
  alongside `latest` — see below for why the route's headline cannot be trusted.
- **DO NOT READ THE ROUTE'S HEADLINE — READ `readings[*].recent`.** The same
  payload said `any_exercised: false`, `rows: 0`, `"producers reported but
  computed no win_prob"`, because `win_prob_null_diag._summarize` iterates
  `latest` only and both services' latest run was an empty one. The summary
  erases an exercised run as soon as any later run reports `rows=0`.
- **The log line is dead and a scheduled task is watching it.**
  `WIN_PROB_NULL_NO_PRICE`: zero matches on both workers over ~16h (since
  23:31Z / 23:17Z) while the counter recorded 18 runs. Probe proven live first
  (positive control: 940 lines / 11 pages, 15:15–15:22Z). Scheduled task
  `wnba-win-prob-counter-read` used to grep that line and would have reported
  "not yet run" forever — **REPOINTED 2026-08-16 at `scripts/read_win_prob_null.py`**
  (every 4h, reports only on change). Nothing should read that log line again.

**AND THE COUNTER BUILT TO MEASURE IT COULD NOT BE READ. `[measured 08-15/16]`**
The `WIN_PROB_NULL_NO_PRICE` counter deployed to both workers (refresh-worker
`903d09c5`, live-odds-worker `b7ae47e6`) `print()`s to stdout, and
`refresh_odds_sources._run_command` runs every producer under
`subprocess.run(capture_output=True)` and **discards a successful step's stdout**
(bounded stderr tail only, and only on FAILURE). Same trap `ops.py:2263`
recorded on 2026-08-01, for this same script.
- **The producer DID run and the line still appeared nowhere.** live-odds-worker's
  own `ALL_PROCESS_MEMORY` census at 23:36:05Z lists PID 1900
  `refresh_wnba_oddsapi_props.py --date 2026-08-15 --do-edges --do-export`
  (started 23:36:04Z, ppid 1880), while a bounded log read across the whole
  window since the deploy returned **zero matches on both workers**. So "the
  producer has not run yet" was the WRONG reading — the silence was the
  emitter's, not the code's.
- **DEPLOYED 2026-08-16 TO ALL THREE:** refresh-worker `b2af0fac` (01:13:32Z,
  since carried forward by another session's `3e1994a2` — verified BY CONTENT),
  web `fa1871cf` (01:15:37Z), live-odds-worker `3573a0c3` (01:59:59Z).
  `/api/ops/win-prob-null` answers **200** and reports
  `reports_root=/opt/render/project/data/reports`. **CHANNEL PROVEN 02:02:33Z by a
  real cross-service reading:** `wnba/live-odds-worker rows=0 null=0`,
  `generated_at` 02:01:19Z (80s after the deploy), `commit 3573a0c3` — worker
  wrote, web read. **NOTHING ABOUT THE `or 0.5` FIX IS CONFIRMED: `rows=0` means
  that run computed no `win_prob` at all, so `null=0` is arithmetic on an empty
  denominator, not evidence.** (**That `rows>0` reading has since ARRIVED — see
  the measured block above; do not re-open this as outstanding.**) A live-odds-worker WNBA producer run was observed at 01:31:36Z, before
  that service had the writer; the next one after its 01:59:59Z reboot is what
  produces the first reading. live-odds-worker has NO idle window during live
  hours (10 of 10 samples across 25 min had jobs running), so this deploy killed
  ~3 in-flight jobs by design, not by accident.
- **FIXED IN CODE, `b281bc7f`.** Both producers now also publish
  through `write_json_file` (per-service key under `reports_root()`, verified
  identical on all three services), readable at **`/api/ops/win-prob-null`**.
  Needs **both workers** (writer) **and web** (reader) to be worth anything.
- Reading guide, so the next reader does not re-derive it: `rows=0` = ran,
  computed no `win_prob` (says nothing about the fix; correct for out-of-season
  NBA); `rows>0, null=0` = fix holding AND exercised; `null>0` = the branch
  fired and published `None` instead of a fabricated `0.5` — **the fix working**.

**`main` IS NOT A SUPERSET OF THE WORKERS — do not "just deploy main".**
`memory_observability.py` is **0 insertions / 366 DELETIONS** from
refresh-worker's live `dca39fad` to `origin/main`. Building on main would strip
`#435` instrumentation off production. Whether main's smaller file is the
INTENDED state is an open question with the memory lane; merging the worker
lineage into main conflicts in **30 hunks across 6 files** of two other lanes'
live code.

**Repo state `[measured 08-15 20:3xZ]`:** the shared tree is **13 AHEAD / 151
BEHIND** `origin/main`. Being behind is a read-your-own-staleness problem; being
ahead is a **lost-work** problem. `git fetch` and read `origin/main` for lineage.

**THE DIVERGENCE RECURS ON A TIMESCALE OF HOURS AND IS STRUCTURAL, NOT A LAPSE.**
Reconciled at 17:0xZ as `6822d539` — local `main` was 33 ahead / 136 behind with
**32 commits genuinely unpushed by patch-id** across six lanes. It was 13 ahead
again within the hour. **Cause: sessions commit to local `main`, while every
deploy-shaped push goes to `origin` through a throwaway worktree**, so the two
lineages separate continuously. Until that workflow changes, assume unpushed
work exists and check `git cherry origin/main main` before any reset, checkout
or fast-forward. A snapshot of the uncommitted tree is on branch
`safety/worktree-snapshot-2026-08-15` (`ad504d57`) — five files were genuinely
unsaved anywhere.

---

## [services-config-platform] SERVICES, CONFIG, PLATFORM

- Web is **`https://syndicate-an21.onrender.com`** (`srv-d88ahvrbc2fs73eodu30`).
  `syndicate.onrender.com` 404s.
- `refresh-worker` `srv-d91dpertqb8s73co8ls0` (4 GB) — sim/board.
  `live-odds-worker` `srv-d91dpertqb8s73co8lt0` (1 CPU / 2 GB / 50 GB disk) —
  odds. Web (2 GB) — display only.
- **The boot-time git->disk sync (`bootstrap_data_root`) runs on WEB ONLY.**
  `_bootstrap_render_data` is called from `create_app()` and nowhere else
  (repo-wide grep 2026-08-20); neither worker entrypoint imports
  `syndicate.app`, and both are `type: worker` running a plain script.
  `SYNDICATE_BOOTSTRAP_ON_START=1` is set on ALL THREE services and read by
  nothing on the two workers — **the env var is the trap, the code is the
  answer.** This voids `#357`'s counter-argument that `team_history` "should be
  on the disk" via bootstrap on refresh-worker.
- **That sync is SEED-ONLY as of `32148cac`** (web `15a0be64`, live 22:36:32Z):
  artifact roots copy only when the destination is ABSENT, so the committed
  mirror can no longer overwrite live pipeline output. Vendored code
  (`vendor/wnba_betting_repo/src`) keeps overwrite; `SYNDICATE_BOOTSTRAP_FORCE_
  OVERWRITE=1` re-arms the old behaviour. Measured on the real disk 23:35:55Z:
  `Bootstrap totals: copied=0 unchanged=33354 kept=25`, of which
  `soccer_source kept=24`. Before the fix, **1,114 of 8,016 hot artifacts web
  served were byte-for-byte the git checkout's copy** (allowlist only; the sync
  walks ~33k files). `#494`.
- **The bootstrap lock is CONTAINER-LOCAL** (`/tmp/syndicate_bootstrap_sync.lock`)
  as of `35daa092` (web `f3a9bb0b`, live 23:34:33Z). It used to live on the
  persistent disk, so a killed sync left a lock that made the NEXT container skip
  its sync for 30 minutes — measured 2026-08-20 22:37:52Z. The holder's liveness
  is now checked, which is sound only because the lock is container-local (PID
  namespaces restart with the container).
- **NOTHING under `reports/intelligence/` is bootstrapped, and it must stay that
  way** (`#496`, `0dd9c6cd`). `BOOTSTRAP_FILES` and the per-date globs had never
  copied a byte — `_sync_tree` returns immediately for a non-directory — while
  the loop logged `Syncing <file>` for each; confirmed in production 23:35:55Z.
  **Deleted, not repaired.** On the keyvalue backend every
  `reports/intelligence/**` path reads from Redis with no filesystem fallback
  (`_KEYVALUE_EXCLUDED_PATH_MARKERS` is `("migration_runs/",)`), so a seeded file
  has no readable CONTENT — but its FILENAME and MTIME are what
  `_intelligence_state_read_path` and `blueprints/intelligence.py` use to decide
  which date is latest, so seeding months-old copies would inject dates with
  nothing behind them. Zero intelligence files have been bootstrapped since
  2026-07-03 (`2fc3673e`, itself a fix for deploys OOM-ing on a 3.2 GB
  `evaluation_ledger.jsonl` pulled in by the old whole-directory sync) with no
  incident attributed to a missing seed. `test_no_bootstrap_pair_points_into_
  reports_intelligence` now also blocks the directory root that caused that OOM.
- **`SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP` is `true` on
  refresh-worker ONLY** (`false` on web and live-odds-worker);
  `SYNDICATE_INTELLIGENCE_REFRESH_INTERVAL_SECONDS = 60` on all three.
- **Web does not run the loops that call `memory_headroom_snapshot`**, so guard
  changes are inert there — which matters because web is a 2 GB container with an
  OOM history. Re-raise if any flag flips.
- **Both workers publish over the internal hostname**
  (`http://syndicate-an21:10000`), not set on web, correctly. **`syndicate-an21`
  RESOLVES FINE** — the "it names a host that does not exist" claim was an
  inference from Render's naming convention and is FALSIFIED.
- **Keyvalue store is 256 MB, `allkeys-lru`, shared by web + both workers, and
  cannot be upgraded.** `/api/ops/keyvalue/usage` reports allocator bytes;
  deltas are block-quantised. `reports/live_refresh_loop/**` is deliberately
  keyvalue-backed and therefore shared across all three services.
- **Board snapshot and `query_state_cache` are compacted then zlib+base64
  compressed** (31.4 MB → 812 KB). **Any reader must call
  `expand_persisted_state` first** — a raw read returns an envelope that still
  passes `isinstance(dict)`, so it degrades silently rather than raising. This
  has bitten four ops diagnostics.
- **`render.yaml`'s web `envVars:` anchor is never referenced anywhere**, so
  nothing was ever shared and worker-only keys accumulated on web for months.
  Web block cut 62 → 52. Blueprint drift: 0 values a sync would revert — a
  snapshot only.
- **"On origin" is not "in production."** Web's live service carries 73 env vars
  against 52 declared. Read `/v1/services/<id>/env-vars` before recording any
  config change as shipped (paginate — `limit` > 100 returns HTTP 400).
- **Absent ≠ off.** Check the code's default for any key added or removed.
- Artifacts are on **Render persistent disks**, forcing single-instance services
  and stop-then-start deploys with downtime. Cross-disk access is a hard
  requirement; web and worker disks cannot be shared.
- **live-odds-worker disk usage climbing ~20% → ~40% of 50 GB over two weeks.
  Not yet diagnosed.**
- Egress was fixed at root (public → internal publish URL); Aug overage was
  ~2.1 TB against 25 GB included. **Never point a worker publish URL at a public
  hostname.**
- **Odds capture is 65.7% of platform bytes and ~97% MLB** — one day of
  `mlb_source/tracking/book_quotes` is 329.5 MB. It is also the ONLY record of
  line movement. The tradeoff between cutting bytes and keeping movement history
  is mostly false: full-state snapshots at 60s re-record unchanged quotes, so
  delta/columnar storage cuts it by a large multiple while preserving movement.

---

## [oom-kills-census] KILLS ARE EVENTS — there is now a tool, and a census `[measured 08-16 17:5xZ]` — **ARCHIVED 2026-08-19 to `state_archive_2026-08-19.md`, verbatim.**

## [live-refresh-ownership] LIVE ODDS REFRESH — WHO OWNS WHAT, and the three defects that made "live bets" scarce `[verified 2026-08-22/23, lane layer2-sim-view-and-live-projection, supersedes nothing — this was never written down]`

**The live-odds tick runs on ONE service.** `SYNDICATE_ENABLE_LIVE_ODDS_REFRESH_LOOP`
is `true` on live-odds-worker only (`render.yaml:857`); `false` on web (`:147`)
and on refresh-worker (`:501`). refresh-worker still LAUNCHES soccer refreshes by
other paths, which is what makes this easy to misread from a process list.

**`SYNDICATE_ACTIVE_SPORTS` is live-only drift — it is in no service block in
`render.yaml`.** live-odds-worker carries `mlb,wnba,soccer`; refresh-worker
carries `nfl`. That partition plus the loop being off on refresh-worker is how
NFL ended up with **no owner at all**: refresh-worker's
`_active_weekly_sports_for_date` YIELDS nfl to the fast tick on a game day, and
the fast tick was dropping it on `ACTIVE_SPORTS`. Both sides consulted the same
predicate and both stepped back. Fixed in code (`#520`), not in config.

**Measured before and after, `LAYER2_BOARD_HEALTH`, 21:06Z -> 22:57Z:**

    nfl     rows 23 -> 275   live_rows 0 -> 252   quote age p50 36,478s -> 603s
    mlb                      live_rows 37 -> 276  live_proj 21 -> 138
    wnba                     live_rows 0 -> 155   quote age p50 581s -> 139s
    soccer                                        quote age p50 23,941s -> 751s

**The 60s tick was notional on a busy slate.** 20:31-21:33Z: `LIVE ODDS REFRESH
TICK` True **5**, False **47** — 9.6%, every skip reporting an already-active
run, against a configured 60s interval. Observed launch cadence ~12 minutes. It
went all-True once the MLB sim finished, so this is a busy-slate number.

**Two counters that mean different things, and the difference is the diagnosis.**
`attach_live_gamelines` increments `considered` only AFTER
`game.state in {live, in_progress}` (`live_gameline_join.py:807`). So
`considered=0` with `lens_live_games=6` is a join **no row reached**, not a join
that priced nothing. That single distinction is what found `#523`.

**Two paths stamp `game.state` and they are not the same chain.**
`book_grid_artifact.py` runs `attach_game_state` then
`attach_live_game_state_from_lens`; `pipeline/layer2_shortlist.py` ran only the
first until `#523`. **MLB masks this permanently** — its chips are
StatsAPI-derived and already carry a live status, so the correction is redundant
there. Soccer's chips come from `_unsimulated_game`, which defaults
`status_state` to `"pre"` for the nine of ten leagues the sim does not cover.
After the fix, soccer `live_rows` 0,0,0 -> **12** (01:14:18Z) and **5**
(01:35:11Z) — first non-zero.

**AND THE REST OF THAT CHAIN IS NOW MEASURED `[verified 2026-08-23 19:21:05Z]`.**
`considered` reached 1,269 and `projected` 125, and the withheld reason splits:

    edge_why={'no_fair_value_one_sided_quote': 110, 'no_fair_value_devig_failed': 15}

**110 of 125 (88%) of live soccer prop rows are quoted ONE-SIDED** — the book
prices the over and nothing else, so no de-vig exists and no downstream work can
produce an edge. `consensus_present_devig_returned_none` is **ZERO**: there is no
broken-de-vig population.

Two things this retires:

  * **`#503` was never a pricing decision.** It was a misplaced `return` —
    `soccer_projections._price_against_market` computed `market_fair_prob_over`
    BELOW its `live_edge_unavailable_reason` early-return, so a live row never got
    a fair value. `prop_projections.py:951` has always ordered it the other way,
    which is why MLB's live tier works. Fixed; correct in isolation; it did NOT
    raise `edged`, because of the 88% above. Both are true.
  * **Soccer's live-prop MISS attribution was inert.** `_has_attribution`
    (`live_projection_join.py:435`) requires `players_seen` and
    `lines_by_player_market` on the indexed payload and `soccer_live_prop_index`
    returned neither, so every miss took the catch-all and the sample's
    `player_in_lens`/`lens_lines_available` were constants. The pre-fix
    `miss_market=620` pointed at an alias gap **that does not exist** — post-fix
    it is 0, with `miss_not_live=548` and `miss_line=583` carrying the population.

**THE OPEN QUESTION MOVED OFF THE PROJECTION LAYER.** It is now: does the soccer
prop fetch capture the UNDER side? `fetch_soccer_oddsapi_props_local.py` handles
`over_price`/`under_price`, so the shape exists; whether OddsAPI returns an under
for `player_shots` and whether it survives into `consensus` is UNMEASURED.
`edged > 0` for soccer has still never been observed.

**NFL cannot produce a live projection, by design.** `nfl_game_projections.py`
applies `live_edge_policy` at the stamp point because there is no NFL live
re-sim — "a pregame full-game total priced against a market that has already
watched 55 minutes of football is not an edge, it is the score." It fires ~248
times a build. **NFL live rows with no model view are the guard working.** Do not
read that as a coverage regression; the grid join is healthy at
`considered=1427 projected=1021` (71.5%).

**Live-projection registries, for reference** (`board_enrichment.py:366,1931,1947`, re-read on `main` 2026-09-10):

    _LIVE_GAME_STATE_SPORTS = {mlb, soccer, ncaaf}   # ncaaf: 42d49364, live on refresh-worker 5767e3ac
    _LIVE_PROP_SPORTS       = {mlb, wnba, soccer}
    _LIVE_GAMELINE_SPORTS   = {mlb, wnba, soccer, ncaaf}

nfl/nba/nhl/ncaab are in none of them; ncaaf is in two.

## [shortlist-payload-budget] THE PERSISTED SHORTLIST IS ONE KEYVALUE WRITE, and the cliff was on the calendar `[verified 2026-08-23, lane layer2-sim-view-and-live-projection]`

    4 sports at the 400/sport cap   rows=1600   5,747,257 B   68.5% of 8 MB
    after the total budget (#525)   rows=1600   4,550,297 B   54.2%

**3,592 bytes/row** at that size. Before `#525` the headroom was ~735 rows —
**less than two more sports at cap** — and `per_sport` could not prevent the
breach because it scales the payload with the number of sports IN SEASON, which
nobody sets. NCAAF ~08-29 projected ~7.19 MB (86%); NCAAB in November, over.

**The failure mode above the ceiling is a SILENT BOARD FREEZE, not an error.**
`write_json_file` raises `KeyValuePayloadTooLarge`; both call sites of
`write_layer2_shortlist` (`intelligence_state.py:3609`, `:4970`) catch it and
return. The worker keeps rebuilding, the board serves its last successful copy
indefinitely, and the only symptom is one log line. A crash restarts; a caught
refusal does not.

Now: a **total** budget (`SYNDICATE_LAYER2_ROWS_TOTAL`, default 1600 = the
measured four-sport board, so a no-op until a fifth sport arrives) allocated by
water-filling, with `per_sport` retained as the ceiling that stops soccer's
20,025 grid rows owning the board. Plus a shed that drops the lowest-ranked rows
rather than freezing. **`SHORTLIST_SHED_TO_FIT` was ABSENT on the verified
build** — the budget held it and the rescue path is a backstop, not load-bearing.

**Still uncovered:** `cards`, `openings_records`, `clv_openings` and the coverage
payloads are a fixed cost no row budget touches. Moving them to their own keys is
what would make the shed unreachable rather than merely rare.

## [published-shortlist] THE PUBLISHED SHORTLIST — edges, EV, CLV

**Owner: `recommendation-lane-correctness` (model-audit session).**

- **NCAAF PROJECTION COVERAGE IS A BOUNDARY, NOT A GAP, AND THE RATIO IS 51/99.
  `[verified 2026-08-31, lane ncaaf-cfbd-quota-latch]`** Week 1 2026: 99
  scheduled games, 51 projected. **48 of 48 missing are `(fbs, fcs)`; 51 of 51
  projected are `(fbs, fbs)`.** CFBD SP+ rates FBS only, so an FBS-vs-FCS
  fixture has no rating for one side and can never be projected. Coverage of the
  RATEABLE population is **100%**, and the team-pair join matched 50 of 51 CSV
  rows. **`games_indexed` is the ANCHOR DATE and `scheduled_games` is the 7-DAY
  WINDOW** — comparing them produced "1 game indexed of 39", which is a
  denominator error and not a defect. Unprojectable fixtures now carry
  `projection_absent_reason`; `rows_unmatched` means only "unmatched for a
  reason we do not know".
- **THE NCAAF SEASON-PROJECTION RELAUNCH IS SELF-AMPLIFYING WHEN IT FAILS.
  `[verified 2026-08-31]`** `SEASON_PROJECTION_LAUNCHING reason=artifact_stale
  age_seconds=366893 interval_seconds=86400` — **configured once per DAY, firing
  ~24x that**, because a failing run never refreshes the artifact so every
  worker tick re-triggers it. Ten snapshot builders share the CFBD key. It
  hammers hardest exactly when the quota is scarcest. `cfbd_quota_latch.py`
  (live on refresh-worker `bf0811bb`) makes every caller fail fast with NO
  request once CFBD says the MONTHLY quota is gone, expiring at the month roll;
  `/ppa/teams` is now cached with a stale fallback stamped into `rating_source`.
  **Both are INERT until 2026-09-01** — the cache is empty and arming it needs
  the call that is failing. **After the roll, `LATCHED_SKIP` still firing means
  the latch did not expire and is CAUSING an outage**; override is
  `clear_latch()`, file at
  `<SYNDICATE_DATA_ROOT>/ncaaf_source/state/cfbd_quota_latch.json`.
  **THE LATCH IS PROVEN ACROSS PROCESSES `[verified 2026-08-31]`** — two
  consecutive hourly runs on the same build `bf0811bb`: `05:16:39Z` set it and
  spent **5** CFBD calls; `06:19:49Z` spent **0** (`LATCHED_SKIP GET /ppa/teams
  clears_in_hours=17.7`, `[ppa] season=2025 source=none
  reason=quota_exhausted_and_cache_empty`, new `LATCH_SET` count 0), all in one
  second in a fresh process. **The five calls on the DISCOVERING run were a real
  defect production found and the tests did not:** `raise_if_latched` ran once
  BEFORE `call_with_retry` and never inside it, so the first 429 set the latch
  and the four retries behind it still went out — exactly
  `cfbd_backoff.MAX_ATTEMPTS`. Fixed by raising `QuotaExhausted` from `_once` to
  abandon the ladder (live `13afa27f`). **That fix's own number — 1 call, not 5 —
  is UNVERIFIED and not imminent:** it needs a fresh exhaustion event and the
  latch is already set until the roll.
- **MLB LIVE PROP PROBABILITIES ARE PRODUCED AND WERE DISCARDED BY A MERGE.
  `[verified 2026-08-31, lane mlb-live-prop-prob-merge]`** `LIVE_MC_PRICED`
  series over one game: **27, 26, 18, 16, 14, 11, 10, 8, 5, 4, 2, 0** (decaying
  as props RESOLVE), against a published snapshot of `live: {rows: 124,
  with_live_projection: 115, with_live_prob: 0}` — produced 27, published 0.
  `_merge_cards_context_into_live_row` replaced the MC row set wholesale with
  the cards set. FIXED in `5bab0685` by carrying the probability ONTO the card
  rows; **DEPLOYED AND UNVERIFIED** — no live MLB game since. **A SINGLE
  `LIVE_MC_PRICED rows=0 outcomes={'priced': 14}` TICK SAYS THE OPPOSITE and is
  an end-of-game artifact** (`priced` increments before the already-decided gate
  drops the row). Read the SERIES.
- **MODEL-EDGE COVERAGE IS THE NUMBER THAT DECIDES WHETHER THIS BOARD IS WORTH
  READING, AND IT WAS 5.2%. `[verified 2026-08-31 01:43Z, lane
  layer1-model-edge-join]`** `rows_with_model_edge / sides_priced` from
  `per_sport_ingest`: **1,406 of 26,835** across five sports. A projection is
  NOT an edge — 7,970 of 13,262 board rows carried `projection` while 465 (3.5%)
  carried `edge_vs_market_pct`, and `scripts/audit_layer1_completeness.py`
  reported the board broadly healthy for weeks because it counted the first.
  Without an edge, `blended_score` falls back to EV alone, and
  `portfolio_commit` refuses the row `no_model_edge_pct` because
  `model_probability == fair` makes Kelly exactly zero — so those rows can rank
  and can never be bet.
- **THE MODELLED-FAIR FALLBACK HAD NEVER RUN, ON ANY SPORT OR PATH — three
  breaks in series, now FIXED AND VERIFIED IN PRODUCTION.**
  `book_margin_model.modelled_fair_edge` reads `row["modelled_fair"]`, which
  `attach_margin_model` writes, and all three production paths call
  `attach_projections` FIRST (`book_grid_artifact.py` 222 vs 340,
  `layer2_shortlist.py` 1066 vs 1069, `intelligence.py` 2670 vs 2677). Second
  break: `_model_edge_for` accepted `edge_vs_market_pct` only. Third: the side
  key — `modelled_fair` is keyed by the ROW's side while the projection's `side`
  is its own framing (1,278 soccer rows stamp `"over"` against a `("yes",)` row,
  1,939 stamp the PLAYER'S NAME). **9,161 rows carried a `modelled_fair` and 0
  carried the edge.** After (soccer, the only sport with a pregame slate that
  night): **342/16923 (2.0%) -> 2082/16940 (12.3%)**, `modelled_edge_rows_priced`
  ABSENT -> **3,159**, served top-200 rows with a model edge **1 -> 100**,
  `rows_uninformative_ev` 274 -> 184. NFL 26.9% -> 39.8%.
  **`mfair_priced` ABSENT vs 0 is the reachability signal** — absent indicts the
  producer, 0 indicts the input.
- **MLB, WNBA and NCAAF post-fix coverage is UNREAD, not flat.** All three sat
  at 0 pregame games at verification time, and the sweep correctly refuses live
  and settled rows. WNBA's spread-frame fix (the grid's line is AWAY-framed,
  `sim_market_home_spread` is HOME-framed, so `p_home_cover` was unreachable for
  every non-zero spread — 0 of 58 edged) is unit-proven both directions and has
  **never fired in production**. `rows_at_sim_market_line` is the counter that
  will say. Read all four with `py -3 scripts/measure_model_edge_coverage.py`.
- **`[user decision 2026-08-30]` one-sided rows are valued on EV against the
  MODEL's probability, not the book's margin** — `-hold` is the same number for
  every such row and buried them. Confined to `book_margin_model` fairs;
  `ev_pct` itself is untouched because `portfolio_commit` back-derives the fair
  from it. **Reach measured: 2 rows of 200.** 3,159 were priced; the one-sided
  pool still scores below the two-sided one.
- **"ZERO LIVE EDGES EVER PUBLISHED" IS FALSE, AND WHAT IS PUBLISHED IS WRONG.
  `[measured 08-15 02:37Z]`** Served `/api/board/layer2-shortlist`, 105 rows: 51
  carry `market_state: live` — the live tier is not dark — and **5 carry a
  `model_edge_pct`**. All 5 are NFL, all `basis: smartsim2_total_normal`, on
  games at `Q4 4:53` / `Q4 2:52`, with edges +2.70 / +2.47 / −2.47 / −4.53 /
  −7.03 against full-game totals of 34.5–39.5 — i.e. **a pregame full-game
  projection priced against a market that has already seen 55 minutes of
  football.** They RANK (`ev_pct` up to 2.65), which is the specific harm.
- **Cause, one missing import: `shared/nfl_game_projections.py` does not import
  `shared/live_edge_policy.py`** and has no `market_state` guard of any kind.
  AST-resolved importers of the policy are `prop_projections`,
  `soccer_projections`, `wnba_projections` only. MLB's 31 live rows carry the
  policy's exact suppression string; NFL's do not. **The policy's own docstring
  predicted this for WNBA on 08-10 ("WNBA never got it", 128 of 128 live rows
  edged) and the rule was centralised so every sport could depend on it — NFL
  still doesn't.**
- **FIXED, DEPLOYED AND VERIFIED IN PRODUCTION — refresh-worker `dca39fad`,
  live 2026-08-15T20:00:19Z. `[measured 20:15Z]`** On the first post-deploy
  build: **12 live NFL rows, 0 carrying `model_edge_pct`** (baseline 5), 12
  pregame rows with 2 real edges retained, and **10 rows carrying the policy's
  exact reason string** — which is the proof the branch ran, since nothing else
  writes it. **It had to go to refresh-worker, not web:** the shortlist is a
  plain artifact read and the edges are baked in at build time
  (`book_grid_artifact.py:221`); a web deploy would have been inert.
  So "zero live edges have ever been published" — Tier 5's founding premise —
  was false, and what was published is now correctly suppressed.
- **(superseded) fixed in code `1d15686b`, not deployed.**
  Guard applied at the single stamp point in `attach_nfl_game_projections`, so it
  covers h2h/totals/spreads and any future branch; ordered AFTER the projection
  is stamped so `live_aware` still ADMITS a genuinely live model (which matters
  now that user decision 5 is to build one). `pytest -k nfl` **556 passed**; new
  suite mutation-pinned 5-red/5-green exactly as predicted.
  **PRODUCTION RE-MEASURE OWED:** baseline **5** live NFL rows with
  `model_edge_pct` at 02:37Z → expect **0**. Do not call this fixed in
  production until that number is read. **A reading of 0 taken while the board
  carries no live rows at all is NON-EVIDENCE** — window 2 produced exactly that
  and it proves nothing. Re-measure on a live NFL slate.
- **QUOTE-FEED AGE ALARM IS DEPLOYED AND MEASURED — web `0c65a832`, live
  2026-08-15 19:27:27Z. `[measured 19:28Z]`** `GET /api/ops/quote-feed-age`
  went **404 → 200**; running commit confirmed from `/api/ops/version`.
  First read: mlb ok 33.7 min, nfl ok 2.5 min, wnba ok 122.6 min,
  **soccer STALE 340.9 min** — it caught a real stale feed on a sport nobody
  was watching — **but see the correction below; that catch is weaker than it
  reads.** Production still serves the single **10,800 s** threshold.
- **PER-SPORT THRESHOLDS ARE WRITTEN AND NOT DEPLOYED — `9e100444`.**
  Measured per-sport cadence (2026-08-15, production shards, distinct
  `captured_at` gaps, read from the artifacts not the logs):
  `nfl p50 1.0 min (n=128) | mlb 31.0 (n=16) | wnba 122.0 (n=14) | soccer 173.0
  (n=91)` — a **173x spread**, which no single global value can serve.
  New defaults **nfl 2 h / mlb 3 h / wnba 6 h / soccer 7 h**, each set ABOVE its
  feed's measured healthy gaps. **NOT off p50:** an alarm floor lives in the
  tail, and 3x p50 put MLB at 93 min, under its measured 123-min healthy
  pregame gap — refuted by an existing test (`learnings.md`).
- **THAT "THRESHOLD ARTIFACT" CORRECTION IS ITSELF WITHDRAWN.** The 173-min
  soccer p50 was computed across a shard that spans **10 calendar days** —
  soccer's is keyed by FIXTURE date, uniquely (mlb 2, nfl 1, wnba 2, soccer 10).
  **Soccer's real intra-day p50 is 40 min**, so 340.9 min was ~8x normal and the
  alarm's first catch WAS legitimate. Threshold corrected 7 h -> **4 h**,
  deployed `8b010dac` 21:33:13Z and measured (`thresholds_by_sport.soccer`
  14400). I corrected a true finding into a false one with an unchecked
  statistic; the second correction restores the first.
- **KNOWN LIMIT, UNSOLVED:** an age-only alarm cannot distinguish "quiet" from
  "broken". Every sport's max gap (244-558 min) is overnight or between-slate,
  and clearing those tails is what keeps all four thresholds in hours rather
  than minutes. Gating on scheduled games is the real fix.
  Deployed from a branch cut off web's OWN live SHA — `8b6f7773` deployed
  directly would have rolled web back **109 commits**.
- **(superseded) built `8b6f7773`, committed.** `shared/quote_feed_age.py` (O(1)
  tail-read of the quote shard → `newest_captured_at`, age, status
  `ok`/`stale`/`unknown`) + `GET /api/ops/quote-feed-age`.
  **Unknown never maps onto `ok`** — a missing or unparseable shard reports
  `unknown` with a reason, so a broken join cannot read as a healthy feed.
  Built because the 5.8 h starvation above was invisible to every existing
  signal: the boards kept building and serving confidently on stale quotes.
  `tests/test_quote_feed_age.py` 14 passed, mutation-pinned. **Production
  behaviour UNVERIFIED.**
- **MLB live PROP edges are 0 for a different, fully diagnosed reason.
  `[measured 08-15 02:41Z]`** From `book_grid_2026-08-14.json`'s own counters:
  `rows_live_considered 989 / rows_live_projected 86 / rows_live_edged 0 /
  rows_live_edge_withheld 86 / snapshot_live_prob_seen 0 / miss_no_market_alias
  903`. 93 live rows carry a `liveProjection`; **zero** carry
  `liveModelProbOver`, the only field `live_projection_join` will price.
  **The severing line is `syndicate/features/mlb/live_lens.py:1109`:** the Monte
  Carlo payload's props are merged in ONLY when the cards artifact had none, so
  in the normal case the MC rows — the sole source of `liveModelProbOver` — are
  discarded, and what survives is `mlb/cards.py:3441`'s
  `_bounded_live_pitcher_projection`, a deterministic interpolation with no
  probability. **`#414` is deployed and INERT.** True whether or not the MC ran.
  Full read: `.syndicate/tier5_live_modules_2026-08-14.md`.
- **CORRECTED 2026-08-15: "the alias table misses 91% of live rows" was the wrong
  defendant.** The alias table already contains every market that reads as a
  miss, including the two that matched ZERO (`batter_home_runs` 0 of 116,
  `batter_hits_runs_rbis` 0 of 79). The gap is EMITTER-side, and it is four
  causes: (1) `batter_hits_runs_rbis` was in `_MLB_HITTER_PROP_DIST_CONFIG` and
  not in `_LIVE_HITTER_MARKET_KEYS`; (2) `_select_bounded_live_side` is a BET
  SELECTOR (two-way price, non-favourite `-200`, projection clear by 0.08/0.18,
  market edge over 0.05/0.03) whose rejections were dropped, so **the board
  sourced a projection set from a pick list**; (3) a pitcher market already past
  its line was skipped outright; (4) `_live_pitcher_prop_row_actionable` drops
  pulled-starter rows. Fixed in `3a476001` behind `include_projection_only`.
  **NOT PROVEN IN PRODUCTION — see the env split below.** `[from-code + measured 08-15 20:12Z]`
- **~~THE LIVE-LENS SNAPSHOT IS BUILT ON live-odds-worker, NOT refresh-worker~~
  — SUPERSEDED, IT HAS MOVED TO refresh-worker. `[measured 2026-08-31 02:17Z,
  refresh-worker logs, lane mlb-live-prop-prob-merge]`** `[live_lens_loop]
  TICK_COMPLETE results={'mlb': True, 'wnba': True, 'soccer': True, 'nfl': True}`
  and `[live_props] LIVE_MC_PRICED` both appear on **refresh-worker**;
  live-odds-worker matched NOTHING for `live_props` or `LIVE_MC_PRICED` over the
  same window. The 08-15 reading below was true then and is false now.
  **The point of the original entry survives and is the reason this line is
  corrected rather than deleted: loop ownership is an env flag that moves with
  no diff, so a fix shipped to the wrong service is INERT and looks identical to
  a fix that did not work.** Read the logs for the loop's own line before
  choosing a deploy target; do not inherit this from any ledger, including this
  one. `[superseded: MLB_ENABLE_LIVE_LENS_LOOP false on refresh-worker / true on
  live-odds-worker, measured 08-15 21:5xZ]`
- **THE LIVE-LENS SNAPSHOT IS BUILT ON live-odds-worker, NOT refresh-worker, AND
  ONLY THE ENV SAYS SO.** `MLB_ENABLE_LIVE_LENS_LOOP` = **false** on
  refresh-worker, **true** on live-odds-worker. A `cards.py` emitter fix shipped
  to refresh-worker is INERT; `live_projection_join.py` runs there during the
  board build and is not. **One commit, two files, two owning services.**
  `[measured 08-15 21:5xZ, Render env API, both services]`
- **The live-row proj/prob CONTRADICTION is FIXED AND VERIFIED IN PRODUCTION**
  (refresh-worker `846bb74e`, live 21:45:20Z; artifact 21:46:06Z, 430 live rows).
  `live_projection_join` used to stamp the lens' `modelProbOver` — the PREGAME
  number — beside a live `projected`, so **7 of 13 live pitcher rows had the two
  on opposite sides of the line**. Now `model_prob_over` is the live probability
  or is ABSENT with a reason, pregame preserved as `sim_model_prob_over`.
  Verified by NEW-CODE MARKER (`sim_model_prob_over` on 21 of 21 rows), not by
  the outcome alone; straddles **0**. `[measured 08-15 21:46Z]`
- **The board's live PROJECTION column and its live EDGE are different claims and
  only the edge was ever guarded.** The edge has always priced `live_prob_over`
  only and correctly refuses without it; the displayed projection kept showing a
  pregame number against a live market with no staleness marker. **89% of live
  rows still do** — that half is unfixed and was explicitly not in scope.
  `[measured 08-15]`

- **The audit's "0.5 coin-flip default" was BACKWARDS as a production
  mechanism.** `_fair_probability`'s `0.5` terminal is UNREACHABLE: every
  `filter_candidates` call site is fed `_score_candidates` output, so `score/100`
  always won first (score 4.05 → fair 0.0405 → edge −0.36). Model-free
  candidates were not published as coin flips — they were **silently REJECTED**
  under `reason: "edge_below_threshold"`, a reason claiming an edge had been
  measured when no model had run. **Removing only the `0.5` would have been an
  inert fix.** `[measured + from-code 08-14]`
- **A1's exclusion IS INERT in production** — `FILTER_CANDIDATES sport=all
  in=476 out=377 rejected={"edge_below_threshold": 99}`, with
  `no_model_probability` absent (0 of 476). What changed is that the 99
  rejections are now honest. **Do not credit A1 with an effect it does not have.**
  `[measured 08-15 23:01:39Z]`
- **A3 is SHIPPED AND VERIFIED** (web `ea1d2ed6` + refresh-worker `29ed6de1`).
  Five predictions written BEFORE the deploy all held: `rows_uninformative_ev`
  null → 4003, soccer selected 100 → 0, `total_rows` 256 → 156 (exactly 256−100),
  `book_margin_model` served rows 100 → 0, and **the control mlb 84 / nfl 60 /
  wnba 12 unchanged to the row.** `[measured 08-14 19:58Z]`
- **Why the control held is a mechanism, not a coincidence:** MLB carries 357
  one-sided rows with a modelled fair, so the rule CAN reach it — it held because
  mlb has `rows_with_model_edge = 2256` and the rule keeps any row carrying a
  model view. **The narrowness clause is what protects MLB.** A later mlb 84 → 78
  is 1.4h of SLATE DRIFT, not the rule. `[measured 08-14 21:2xZ]`
- **Ranked #3 + #4 are LIVE (`79148d8e`) and CLOSED — P3 IS MEASURED.** The
  `FILTER_CANDIDATES` line landed at 23:01:39Z (`in=476 out=377
  rejected={"edge_below_threshold": 99}`), which closed both P3 and the
  `7b1f3fdc` instrument deploy. **`recommendation-lane-correctness` is
  CLOSED-VERIFIED and its 7 file claims are released.** Two later handoffs still
  described this as the plan's cheapest open item while quoting the very line
  that closed it — re-read the lane header before re-taking it. `[measured 08-15]`
- **A3a score monotonicity is COMMITTED AND DELIBERATELY NOT DEPLOYED**
  (`28291eb6`; corr(reliability, score) = −0.8312 on 156 negative-value rows vs
  +0.8560 control). **Do not deploy without a pool-side counter** — its effect is
  on SELECTION and is invisible in a shortlist that returns survivors only.
- **CLV: A VALID NUMBER NOW EXISTS. `[measured 08-15 19:4xZ, web `bebe87c9`]`**
  This OVERWRITES the previous "there is still no valid CLV number / avg_clv_pct
  is None" line, which was true until 19:36:45Z today.

      /api/ops/clv/report?date=2026-08-15&sport=mlb
        openings     520
        same_book_n  144      (was 0)
        avg_clv_pct  -0.0711  (was None)

  **The blocker was a VERSION SKEW, not a defect** — web's receiver 403s any
  path failing `is_hot_artifact_relative_path`, and web's `artifact_publisher.py`
  lacked the `clv_openings` pattern the worker had, so 490 openings sat stranded
  on the worker. Fixed by deploy, not by code. Owner: lane `clv-without-settlement`
  (`lane-cleanup`), **whose entry carries the fuller reading — 27.1% beat rate,
  taken PRE-FIRST-PITCH, and the lane's own breadth hypothesis REFUTED. Cite the
  lane, not this summary.**
  - **UNVERIFIED:** the `PUBLISH_OK` log line was never observed; the artifact
    crossing (`export count=1`) is the evidence. **And it is NOT established
    that this is against a sharp close** — a same-book join pairs a book with
    itself, which need not be Pinnacle. Do not merge with the game-line
    sharp-reference finding without checking which book.
  - Still true and still the reason the headline is same-book only: the earlier
    `-5.215` was RETRACTED (`home -5.0` differenced against a `home -1.5` close;
    25 of 25 closes preceded their openings). `close_precedes_open` remains a
    PRODUCTION condition, refused by name alongside `line_mismatch` and
    `line_unverifiable`.
- **The recommendation lane does not price the shortlist.** Every published row
  carries `quote.fair_method` = `consensus` or `book_margin_model`. Fixes to
  `recommendation_engine` should NOT be expected to move the shortlist.
- **Per program Tier 1, stamp fetch cadence / quote age on every CLV record**
  alongside the pricing-version stamp — an "opening" price can be up to two
  hours off the real open.

---

- **`edge_vs_modelled_fair_pct` IS DEPLOYED AND JOINED TO BOTH BOARDS
  `[2026-08-31, lane layer1-model-edge-join; SUPERSEDES "COMMITTED, NOT
  DEPLOYED" of 2026-08-17]`.** `attach_modelled_fair_edges` runs at the tail of
  `attach_margin_model` — one hop downstream of projections, shared by all three
  board paths — and `layer2_board._model_edge_for` falls back to it, side-checked
  and never negated. It still never writes `edge_vs_market_pct`; the two stay
  distinct on purpose. **Per user decision, EV is now priced against the MODEL
  where a modelled fair exists** (`model_ev_pct` + `ev_basis`), because
  `book_margin_model` prices one-sided rows as `fair = implied x (1-hold)` and so
  made `expected_value_pct` a restatement of the book's own hold. **`ev_pct`
  itself is deliberately UNTOUCHED — `portfolio_commit` back-derives fair from
  it.**
  **SUPERSEDED FOR THE RANKING TERM `[user decision 2026-08-31]`: the board
  ranks one-sided rows on `model_edge_pct`, NOT on model EV.** The 08-30
  decision stands for PRICING — `model_ev_pct` and `ev_basis` still travel on
  the row — but EV is edge divided by the fair probability, so ranking on it
  multiplied edge by the reciprocal of p and a smaller edge on a longer shot
  outranked a bigger edge on a shorter one. MEASURED on the served shortlist
  2026-08-31 by lane `layer2-board-opportunities` and reproduced independently:
  the top 25 was 24 `batter_home_runs` plus one totals, all 25 one-sided, top
  row model EV about 85 points against the best market-basis EV anywhere of
  about 5. **And the flaw was structural, not just a scale mismatch:**
  `blended_score` caps the model at fifteen points when it arrives as
  `model_edge`, while the `value_ev` path it was routed through has no cap —
  the same signal capped in one path and uncapped in the next line. EV ranking
  also amplifies model error hardest where the model is weakest: at p near
  one-tenth a two-point probability error moves EV about twenty points, and
  these rows carry `model_skill.sample_games: 0`. `layer2_board.py` is released
  to that lane; the flag defaults to the NEW behaviour.
  **LIVE AND MEASURED `[cffbbd89, board rebuilt 2026-08-31T17:00:33Z]`.** The
  identity inverted exactly: `score.value_pct == model_ev_pct` 50/50 -> **0/52**,
  `== model_edge_pct` 0/50 -> **52/52**; scores compressed 5x (36.16 -> 7.23);
  top-25 market-priced rows 3 -> 14. **BUT THE INTENDED OUTCOME IS NOT
  ACHIEVED: the top NINE rows are still model-basis and the best
  market-anchored row reaches only RANK 10** (`ev_pct` 4.91, score 1.31 against
  the leader's 7.23). Cause, and it is structural rather than a tuning miss:
  `value_ev` carries edge in PROBABILITY POINTS while market rows carry EV in
  PERCENT — model edges run 3.4-12.0 against a best market EV of 4.94, so the
  bigger unit wins the sort on units alone and `ev_basis` cannot fix that.
  **Whether the two should share one sort at all is UNSETTLED and this deploy
  did not settle it.** Full working: `deploys.md`, 2026-08-31 16:48Z.
  **AND THE UNDERLYING CAUSE IS NOW MEASURED AND CORRECTED AT SOURCE
  `[2026-08-31, lane soccer-shot-shrinkage]`:** the soccer shots model
  over-predicts ~1.39x, so the large model edges feeding those rows were mostly
  a level error rather than disagreement. See `[soccer-shots-prop-skill]`.
  **DIVISOR NOW 1.3930 `[2026-09-02, refit, n=10,176 / 254 matches / 9 leagues;
  held out 2026-08-22: SCALAR MAE 0.5491 vs RAW 0.6178, bias +0.0281 vs +0.1687,
  beat AFFINE in all 9]`. Published and read back.**
  **AND IT IS NOW OBSERVED WORKING — in the ENGINE, not on the board
  `[2026-09-02]`.** Measured on the prediction archive, self-normalised over the
  3,434 players present both sides of the ship date: median post/pre
  `expected_shots` **0.720** against a predicted 1/1.3979 = **0.715**, with
  `expected_minutes_share` flat at **1.000** so the step is not "future fixtures
  carry fewer minutes". Second, independent confirmation via a different
  denominator (`#636`): pre **0.925** → post **0.631**, ratio 0.682 vs 0.718.
  `todo #612` CLOSED. Tools: `scripts/check_soccer_divisor_reached_engine.py`,
  `scripts/check_soccer_shot_divisor_vs_season_rate.py`.
  **NOT claimed: that 1.3930 SPECIFICALLY is live.** The two divisors differ by
  0.35%, far below this measure's noise; what is proven is that a divisor of
  roughly the shipped size is applied and the resolver did not break.
  **The lane's own `1.19 → 0.85` target is RETIRED, not met** — that baseline
  came from a construction I could not reproduce (this instrument reads the
  pre-divisor window at 0.925). Only before/after on ONE instrument is valid.

**ADMISSION, NOT RANKING: a one-sided row whose ONLY value is an UNMEASURED model's edge is now WITHHELD from the shortlist** `[2026-09-11, user decision "Withhold, all sports"; 9d580145 live on refresh-worker 12:27 CT, lane pricing-plane-v1]`.
- **Why.** The 08-31 ranking change reduced the HR takeover but did not end it. On 2026-09-11 all 116 MLB `batter_home_runs` rows were `book_margin_model`
  with `model_skill.sample_games: 0`, 8 of them in the top 25:
  - Acuna 1+ HR: model 0.321 vs implied 0.196.
  - 2+ HR longshots rested on model means of 0.38-0.59 HR/game.
- **The rule.** `select_shortlist` drops a `book_margin_model` row with a model edge whose `model_skill.status` is not `measured` (an absent note
  counts as unmeasured). It is counted as `rows_unmeasured_model_only` plus `unmeasured_model_only_by_market`.
- **Measured, first post-deploy build (17:37:25Z):**
  - 0 of 4,986 served rows match the rule; `unmeasured_model_only=3107`.
  - MLB HR rows: 0.
  - The row budgets refilled the freed slots with market-priced rows.
- **Reverse-out:** `SYNDICATE_LAYER2_UNMEASURED_MODEL_ONLY=admit`.
- **The consequence:** those markets get no paper orders, so their skill can only become measured through a prediction-vs-box-score grader
  (lead, 2026-09-11). The served counter keys wait on a web deploy.

## [artifact-delivery-topology] AN ARTIFACT AN ENGINE READS IS A THREE-SERVICE CHANGE `[measured 2026-08-31]`

Getting an 867-byte calibration file to the engine that reads it required all
three of these to agree, and two plausible choices were silently wrong:

- **`/api/ops/artifacts/publish` is a RECEIVER ON WEB.** Workers push TO it, so
  publishing lands on WEB's disk. Workers run no HTTP server and cannot be
  pushed to.
- **Workers PULL, DATE-SCOPED.** `pull_hot_artifacts` requests
  `?pattern=*<today>*` (an unfiltered pull hit Render's proxy timeout), so **a
  file with no date in its name can never arrive** — as `run_refresh_worker`
  already records for `schedule_2026.json`. Hence `shot_shrinkage_<DATE>.json`.
- **THE RECEIVER VALIDATES AGAINST ITS OWN ALLOWLIST.** Deploying
  `HOT_ARTIFACT_PATTERNS` to the workers alone produced
  `403 relative_path is not an allowed hot artifact` because WEB was behind.
  **web needs the deploy even when it runs none of the code.**

Rejected, both look right: the boot seeder copies only into a directory with
NONE matching yet, so it can seed a first value and never a re-fit; keyvalue
`write_json_file` is cross-service but applies a TTL, so a constant would
silently expire back to its default.
  **COVERAGE IS UNREAD, NOT FLAT.** MLB/WNBA/NCAAF all read zero at the
  post-deploy check because there were **zero PREGAME games** at that moment.
  Read it with `py -3 scripts/measure_model_edge_coverage.py`, which prints the
  pregame/live/final mix precisely so a composition effect cannot be mistaken for
  a regression, and `mfair_priced: ABSENT` as the reachability signal.

## [fleet] FLEET `[2026-08-18 02:1xZ — goes stale in minutes; re-read before deploying]` — **ARCHIVED 2026-08-19 to `state_archive_2026-08-19.md`, verbatim.**

## [deploy-ownership] DEPLOY OWNERSHIP — SELF-SERVE BEHIND TWO LOCKS `[verified 2026-08-18, user decision, REPLACES the coordinator role]`

**There is no coordinator session.** `.syndicate/coordinator.id` is DELETED,
`coordinator.md` is a tombstone, and `.syndicate/deploy/requests/` is retired
(a README there names the two requests that were still pending).

**DEPLOY A SHA CONTAINED IN `origin/main`** `[2026-08-18, user decision]`.
`deploy_preflight.py` returns **`OFF_MAIN` (exit 4)** otherwise, and the guard
blocks on it like any non-CLEAR verdict. Escape hatch `--allow-off-main`, said
out loud in `deploys.md`. **Measured: 170 remote `origin/deploy/*` branches
exist and every sampled tip is OFF main** — two such deploys do not contain each
other, so the second silently reverts the first. Serialisation is not
composition: the claim ORDERS deploys, only being on `main` makes them
CUMULATIVE.

**The preflight receipt is bound to its SHA.** A CLEAR taken for one commit does
not authorise deploying another for the next 15 minutes, or `OFF_MAIN` would be
sidestepped by preflighting a main commit and shipping something else.

**UNVERIFIED and stated as such:** this predicate has never gated a real deploy.
`OFF_MAIN` has not fired in anger and no receipt has been consumed live. The
first real deploy is the test — treat a surprise there as expected, not as
evidence the rule is wrong.

**Any lane may deploy** once it holds, for the target service:

1. an unexpired `scripts/deploy_claim.py` claim in its own lane name, and
2. a `scripts/deploy_preflight.py` verdict of `CLEAR` less than 15 min old.

`.claude/hooks/deploy-guard.py` enforces both and prints the exact command that
clears each refusal. A `render.yaml` push needs all three services locked —
`blueprint_sync`'s blast radius is all three. Off switch:
`SYNDICATE_DEPLOY_GUARD=off`. Break glass:
`.syndicate/deploy/grants/<session_id>.json` with `expires_epoch`, which any
session may write — it is `--force` with an audit trail, not a permission.

**Why the role ended, stated here because the failure is reusable:** the guard
gated on `session_id in coordinator.id`. When the holder was archived that
predicate had no true value, so the guard's allow-branch became unreachable and
it blocked EVERY session's deploys silently — not a throttle, an outage. The
lock it wrapped was always the better mechanism: `O_CREAT|O_EXCL` with a 45-min
expiry frees itself when its holder dies, which is precisely what the role could
not do.

Process records — sweeps, adjudications, corrections — live in `deploys.md` and
`lanes.md`, not here.

- **Verified by test, not by belief:** `tests/test_deploy_guard.py`, 33 cases,
  both directions — reads of the deploy entrypoint ALLOWED (the old guard blocked
  them, including the edit that fixed it), unlocked deploys BLOCKED, foreign
  claim under the sibling alias BLOCKED, stale `CLEAR` BLOCKED, fresh `HOLD`
  overriding an older `CLEAR` BLOCKED.

## [sim-scheduling-deploy-lineage] STALE-TREE DEPLOY LINEAGE — the MECHANISM is real, the SEVERITY I first reported was wrong `[collapsed 2026-08-18 from two 2026-08-17 sections]` — **ARCHIVED 2026-08-19 to `state_archive_2026-08-19.md`, verbatim.**

## [web-request-path-latency] WEB'S 502s WERE `/healthz` STARVATION, NOT SLOW COLD BOOTS — FIXED AND MEASURED `[2026-08-22, lane render-web-request-path]`

**COLD BOOT IS NOT A PROBLEM AND NEVER WAS.** Boot-to-listening on web is
**2.7s** (17:12:52.36 `sh -c` -> 17:12:55.09 gunicorn `Listening at` -> 17:12:58.43
first `/healthz` 200). Stop diagnosing boot time.

**THE 502s WERE RESTARTS.** Web was SIGTERM'd every ~90s during live MLB slates
with ~15s of no listener after each. Container `-2mdsk`, booted 17:12:55, **no
deploy after 17:12:59**: terms at 17:14:08 / 17:15:38 / 17:17:38, a NEW gunicorn
master pid each time; health checks unanswered **84s** (17:16:34 -> 17:17:58).
Render 502s carry `responseBytes=223158` — that is Render's own error page and is
how you separate them from app errors. `WORKER TIMEOUT` appeared **zero** times
in three days, so `GUNICORN_TIMEOUT=60` is EXONERATED.

**CAUSE:** `_mlb_feed_live_payload` fell through to statsapi for every game
because `mlb_source/source_artifacts/data/raw/statsapi/feed_live/**` matches
**none of the 175** `HOT_ARTIFACT_PATTERNS`. 15 live HTTPS calls per home request,
uncached, against 8 request slots (`WEB_CONCURRENCY=2` x `GUNICORN_THREADS=4`).

**FIXED — `apply_live_scores` on `games=15`, measured on production:**

    BEFORE  3318 / 7991 / 8400 / 5498 / 3494 / 3802 / 3694 ms
    AFTER   0-93 ms (max 93, 14 samples, two instances, two deploys)

Live scores now come from `live_lens_report_<date>.json` (already allowlisted,
republished ~60s). The residual statsapi path is SINGLE-FLIGHTED: at most one
request thread can ever block on it. Live on web `8149e51d` / `3ada3512`.

**DO NOT ALLOWLIST `raw/statsapi/feed_live`.** It is the obvious fix and it is a
REGRESSION: `_mlb_feed_live_payload` takes the file if it EXISTS with **no
freshness check**, so publishing it freezes every game at capture time — `#413`,
measured 2026-08-13, MIL @ SD reading `live / TOP 9` against a lens reading Final.
It also buys **no speed**: `vendor/mlb_bettingv2/tools/daily_update.py` refreshes
those files **prior-day only** ("must fetch the final game feed, not a stale
pregame cache entry"), so a freshness gate rejects them and falls through anyway.
~3.2 MB x 15 per publish cycle on top.

**`MLB_GAMES_STAGE_MS` settles two WRONG hypotheses** and is the instrument for
any future work here: `per_game_reco_rows` was **0-13ms in every sample** (the
`scope_2026-08-21_home_request_path_compute.md` suspect), and the live-lens
cache-key invalidation its follow-up proposed was not the cost either.

**NOT VERIFIED: the card-cache idle bound.** `_MLB_CARDS_CONTEXT_CACHE` /
`_MLB_TODAY_CACHE` now bound on IDLE time (300s / 120s), targeting a ratchet
measured at 369 MB -> 2,026,717,200 B over ~7.5h against a 2,147,483,600 B
ceiling. Post-deploy readings are directionally better at comparable ages and
**that is not proof**. Peers redeploy web every 20-30 min, so no instance
survives long enough to show it. Instrument: memory-over-uptime, plus the rate
of `CONTEXT_CACHE_EVICTED ... web=True` falling.

**NEXT BOTTLENECK:** `build_cards_page_context`, now dominant at 1803-2402 ms on
a cache miss.

---

## [web-boot-sync-healthz] THE BOOT SYNC WAS A SECOND `/healthz` STARVATION SOURCE — 72.20s, NOW 0.65s `[verified 2026-08-27, lane boot-sync-healthcheck-kill]`

Distinct from `[web-request-path-latency]`, which fixed the REQUEST path against
the same 5s budget. This one is BOOT, and it survived that fix.

**4 `server_failed` in 24h, every one 1-2.5 min after a `deploy_ended
succeeded`, 0 unpaired, over 22 deploys** (~1 boot in 5). Reason on all four:
`HTTP health check failed (timed out after 5 seconds)`, `evicted: false`.

**MECHANISM — not a request slot.** The sync runs on a DAEMON thread
(`syndicate/app.py:241`), so it never holds one of the 8 slots. It starves the
container: boot 20:39:49Z, sync began 20:40:09Z, first `/healthz` blackout
20:40:14Z — 5 seconds later. Gaps **35.21s and 34.74s** against a 5.00s probe
cadence; instance killed 115s after boot.

**COST WAS SYSCALLS, NOT BYTES: 5.34 per file** (measured by counting, over a
real 600-file subtree). A 2-parameter regression said bytes and was wrong by 2x.
`filecmp.cmp(shallow=False)` opened and fully read both sides — ~66,800 opens,
~6.2 GB — to copy zero files.

**FIXED, live on `48833112`:** seed-only roots decide from the destination
directory's NAME SET (`os.scandir`), 0.20 syscalls/file; overwrite roots keep the
exact compare. Sync **72.20s -> 0.65s**, reproduced at **0.59s** on an unrelated
lane's next deploy. `mlb_source/source_artifacts` 62.75s -> 0.49s.

**NOTHING IS SKIPPED:** `present=33316` + overwrite `unchanged=76` = **33,392** =
`git ls-files` over the bootstrap roots, exactly, on both boots.

**THE KILL RATE IS NOT ESTABLISHED — 2 deploys, 0 kills, against ~1-in-5.** What
is established is the DURATION, so the starvation window is 0.6s wide instead of
72s. **A per-boot `/healthz` trace does NOT discriminate**: two PRE-fix boots
that SURVIVED were equally clean (5.13s, 5.59s); only the KILLED boot shows
blackouts, which is circular. Count `server_failed` per deploy over >=5 deploys.

**`/api/ops/bootstrap/run` still reports the real `unchanged`/`kept` split** —
`classify_existing` defaults to the exact path and only `main()` opts out. A
boot now logs `present=N (not inspected)`, never `kept=0`, because a run that
inspected nothing must not assert zero divergence.

## [web-preflight-dead-sample] WEB'S PREFLIGHT SAMPLE HAS BEEN DEAD SINCE 2026-08-14 — CAUSE STILL UNKNOWN AFTER FOUR WRONG ANSWERS `[2026-08-18, collapsed from 2 stacked sections]`

**COLLAPSED 2026-08-18 by lane `ledger-coherence-sweep`, under an explicit
instruction.** This subject had a CORRECTION section and a RETRACTION section
that contradicted each other, which is the stacking this file has been collapsed
for twice. Newest truth wins; the superseded claims are recorded below as VOID
rather than deleted, because two of them are *actionable and wrong* and someone
remembering them would do damage. Full prior text is in git history.

**THE SYMPTOM IS FIXED `[2026-08-19]`. `deploy_preflight.py` is SERVICE-AWARE:**
web's process list is read live from its own `/api/ops/memory`; the workers keep
the `ALL_PROCESS_MEMORY` log path, which works for them. Measured on the first
run after the change — `web CLEAR, sample_source api:/api/ops/memory, age 0.0s,
jobs 0` against `refresh-worker HOLD, log path, age 26s, jobs 7`. **Web no longer
needs a break-glass grant to deploy.** The fix does NOT depend on the cause, and
that was deliberate: four causes had been claimed and all four were wrong, so
anything resting on a fifth guess would have been the fifth mistake. Falsified in
the blocking direction too — a job on web yields HOLD, and an unreachable
endpoint falls back to the log path and yields UNKNOWN, never CLEAR.

**THE MECHANISM IS NOW FOUND AND VERIFIED `[2026-08-19]` — and it is NOT a fifth
guess, because it is read off the code and the live config rather than inferred
from the symptom.** Web has exactly one path to the emitter, and it is gated off:

    syndicate/app.py  _start_background_loops()
      render_web_dyno = _is_render_web_dyno()
      if render_web_dyno and not _env_bool(
              "SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP", default=False):
          return                     <-- web returns HERE
      start_intelligence_state_background_loop(app)   <- the 12 emitter call sites
      if not render_web_dyno:
          start_live_refresh_background_loop()        <- also skipped on web

- **Live web env: `SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP = false`.**
  `render.yaml` sets it `"false"` for web and `"true"` for the worker.
- **No other caller exists on web.** `syndicate/blueprints/**` has ZERO
  references to either emitter function, so no request path can produce one —
  which is why hitting `/api/ops/memory` repeatedly tonight emitted nothing.
- **Confirmed empirically, not just by reading:** web has REBOOTED many times
  since (newest gunicorn boot 2026-08-19T00:48:07Z) and has still never emitted.
  A restart cannot fix a loop that is configured not to start.

**WHAT IS STILL NOT PROVEN: which change on ~2026-08-13/14 flipped it.** The gate
dates from 2026-07-04 and the blueprint's `false` from 2026-07-25, both well
before the last emission at 2026-08-14T18:55:39Z — so for those three weeks the
SERVICE-level env must have carried a `true` that drifted from the blueprint.
**The leading candidate is the FIVE `render.yaml` pushes on 2026-08-13**, each of
which fires `blueprint_sync`, and a sync rewrites the service's WHOLE env block
from the blueprint — overwriting exactly that kind of manual `true`. **This is
NOT confirmed:** Render exposes no history of env-var values, so the pre-08-13
service value is unrecoverable. Candidate, not finding.

**THE SYMPTOM AS IT WAS, for anyone reading an older receipt:**
`deploy_preflight.py` returned `UNKNOWN` for web — "sample is 356656s old (limit
180s)", 4.1 days and only ageing. The guard requires a CLEAR within 15 min, so
web's preflight was permanently unsatisfiable and every web deploy needed a
break-glass grant. A
guard that must be broken on every use has stopped being a guard. Tracked as
`todo.md` `#465`.

### WHAT IS ESTABLISHED — and it is only this

- **The emitter EXISTS and prints when called.** `memory_observability.py:1944
  def log_all_process_memory` → `:1952 print(f"ALL_PROCESS_MEMORY ...")`.
- **`origin/main`'s copy is BYTE-IDENTICAL to the 420-commit-old live worker
  `00e9a49f`** — 124,684 bytes both sides, 1 emitter definition, 1 emitter print
  each. Measured 2026-08-18.
- **refresh-worker emits every ~17s. Web has not emitted since 2026-08-14.**
- **Web HAS a reachable call path** (see the falsified trace below), so "web
  never had a caller" is not consistent with the evidence.

### FOUR CAUSES CLAIMED FOR ONE SYMPTOM. ALL FOUR ARE WRONG.

    1. "the sampler is broken"        NO
    2. "psutil is not installed"      NO -- real, but incidental. procfs
                                      enumerates 4/4 processes and
                                      /api/ops/memory returns full process data.
    3. "the emitter was deleted"      NO -- intact at :1952, byte-identical to
                                      the live worker's copy.
    4. "web has no caller"            NO -- app.py:37 starts one.

    ACTUAL CAUSE                      **UNKNOWN. DO NOT ADD A FIFTH GUESS.**

**Acting on cause 2 would have shipped a `psutil` dependency that fixed nothing
and looked exactly like a fix.** That is the pattern to watch here: every one of
these four was plausible, and three were argued from real evidence.

### THE TRACE THAT CLAIMED "NO CALLER ON WEB" IS FALSIFIED

It enumerated **two** caller families — `live_lens_loop` (started only by
`run_live_odds_refresh_worker.py:30`) and `refresh_odds_sources.py` (a worker
script) — and concluded both were worker-only, therefore web has no caller.
**It missed a third family, while quoting it.** Its own evidence block reads
`syndicate/app.py:36-37 starts live_refresh_loop + intelligence_state`, and:

    syndicate/app.py:37        start_intelligence_state_background_loop
     -> pipeline/intelligence_state.py  _diag_log_all_process_memory  (12 sites)
       -> memory_observability.py:1919  log_and_persist_process_memory
         -> :1944 log_all_process_memory  ->  :1952 the print

**Web starts a loop that reaches the emitter.** The claim read as true because
`syndicate/app.py`, `wsgi.py` and `syndicate/blueprints/` contain ZERO
occurrences of the callee — literally true, and materially misleading, because
`app.py` does not call it, it *starts something that does*. Grepping for the
callee and never asking what starts the caller is a reachability error.

**So the question is NOT "does a caller exist" but "why does the caller that
exists not emit".** Candidates, none tested: the loop is gated off on web by
env; it returns before reaching those 12 sites; or it is not actually running.

**HOW CAUSE 3 WAS REACHED, kept because the mechanism recurs:**
`git grep -l 'ALL_PROCESS_MEMORY' origin/main -- '*.py'` piped through `head -4`
returned four `scripts/` paths, and **a TRUNCATED list was read as an EXHAUSTIVE
one** — `memory_observability.py` was simply below the cut. Same family as cause
4's error: both concluded absence from a search that was never asked to be
complete.

### THE SUPERSEDED CORRECTION'S TWO ACTIONABLE CLAIMS ARE VOID

Recorded explicitly because both are alarming, specific, and would waste real
work:

- **VOID — "refresh-worker's CLEAR preflight is an ARTEFACT OF STALENESS. The
  moment the worker is brought onto main its preflight goes UNKNOWN too and NO
  service can gate a deploy."** This derived from the emitter being absent on
  main. It is present, and the file is byte-identical across those 420 commits,
  so modernising the worker changes nothing about its emitter. **Do not let this
  warning deter a worker update.**
- **VOID — "THE ACTUAL FIX: restore the emitter."** There is nothing to restore.

### THE LEAD, AND THE FIX THAT SURVIVES REGARDLESS OF CAUSE

**Look at loop ownership first: it moves between services via env flags with NO
DIFF** (`_mlb_refresh_tick_owner_here` and friends) — already a recorded trap in
this file. A loop web still starts can be gated off inside it, which would look
exactly like this.

**The fix does not depend on the cause and should be taken now: make preflight
SERVICE-AWARE — have `deploy_preflight.py` read `/api/ops/memory` for web**
instead of scraping logs for `ALL_PROCESS_MEMORY`. That endpoint already returns
a fresh, complete enumeration on live web (measured: 4 processes, all infra,
zero jobs), and it is **already what every web break-glass does by hand**. It is
also better matched to the real risk — a web deploy has no long job to land on.

**Rejected alternative: give web its own periodic emitter.** That is request-path
periodic work, which the worker-split rule exists to prevent and which `#241`
already turned into a production restart loop (headroom figure STALE — see
`[refresh-worker-headroom-2026-09-02]`).

**DO NOT ACT ON A CAUSE FROM THIS SECTION.** Act on the fix, which is
cause-independent.

## [refresh-worker-deploy-hold] refresh-worker: THE OOM DEPLOY HOLD IS ORPHANED. Branch READY, NOT DEPLOYED. `[2026-08-18]` — **ARCHIVED 2026-08-19 to `state_archive_2026-08-19.md`, verbatim.**

## [test-intelligence-runtime] `tests/test_intelligence.py` IS SLOW, NOT STALLED — and the "warm state" finding is RETRACTED `[2026-09-03, lane intelligence-suite-runtime]`

**221 pass in 586.00s (9:46).** An armed faulthandler never fired. No single test
exceeds **4.9%** of the run; the 25 slowest are all
`test_intelligence_query*` at 12.5-28.9s, each driving a real candidate-pool
build. Collection alone is 43-75s. The earlier ">10 minutes, stalled at 32%" was
a 10-minute timeout landing mid-run; the frozen percentage is pytest printing
per output line.

**RETRACTED, do not cite:** a "warm state" effect (216.4s cold vs 131.4s warm),
a 1.7x isolation penalty, four mechanism exonerations, and "do not split the slow
tests into their own job". All rested on ONE unreplicated comparison with an
outlier cold reading. Three paired replications erased it: **cold 31.32s vs warm
31.45s**. The rule is in `learnings.md` 2026-09-03.

## [refresh-worker-disk-2026-09-13] refresh-worker's 48.9 GB disk: FULL 09-12 23:39Z -> 09-13 14:15Z, COMPACTED to 16.3 GB free `[verified 2026-09-13, lane refresh-worker-disk-inventory]`

- **UPDATE `[verified 2026-09-16, refresh-worker DISK_INVENTORY + single-key env reads]`:** used 36.19 GB (09-13 16:32Z) -> 37.62 GB (09-16 14:40Z), ~+0.49 GB/day, 14.88 GB free (~a month to full). Growers: `evaluation_ledger_chunks` 8.63 -> 9.18 GB (~+190 MB/day), `mlb_source/source_artifacts/data` ~+142 MB/day, `venue_odds` 430 -> 528 MB (~+34 MB/day). **Retention had never run until 2026-09-18 00:48:54Z** (the dry-run flag, live since the `7ef0431b` boot, adds a retention step to the DAILY `DISK_MAINTENANCE` pass that has run ~00:35-00:49Z every day since at least 09-10; each pass scans 8,000 of 124,941 files, `DISK_INVENTORY_SUMMARY` 09-18 15:32Z: 38.6 GB used, 13.4 GB available; verified 2026-09-18 from logs + `disk_maintenance.py`) (the dry run is now live, `SYNDICATE_DISK_RETENTION_DRY_RUN=1` since the `7ef0431b` boot 22:34:51Z; first sweep 2026-09-18 00:48:54Z: 0 deleted, 396 files / 338.2 MB would-delete in 8,000 scanned, cursor incomplete). Before that: `SYNDICATE_ARTIFACT_RETENTION_ENABLED`, `_OBSERVE`, `SYNDICATE_DISK_RETENTION_DRY_RUN`, `_NEW_RULES_APPLY` all ABSENT on refresh-worker AND live-odds-worker (`SYNDICATE_DISK_MAINTENANCE_ENABLED=true` on both). Dry-run rule-table retention landed inert as `4481cb6c` (lane worker-disk-auto-retention). live-odds-worker's disk: UNREAD (it emits no DISK_INVENTORY).

- **Inventory, 13:44Z, 0.0 MB free.**
  - `soccer_source/tracking` 13.32 GB: daily `odds_*_history_<date>.csv`, export-only, no reader in code.
  - `evaluation_ledger_chunks` 8.01 GB; `mlb_source/source_artifacts/data` 6.74 GB; `mlb_source/data/market` 3.88 GB.
  - MLB `book_quotes` 3.48 GB, including 3.15 GB of plain shards beside their `.gz`.
- **Compaction (`disk_compaction.py`).** A one-shot thread at boot from `run_disk_maintenance`, default only when `RENDER` is set AND the service is refresh-worker.
  - First run (`3e18be8e`, 14:44:15Z): free 0 -> 16.44 GB. 96 verified duplicate shards removed; 203 closed history CSVs gzipped, 13.64 -> 1.01 GB.
  - Post-`c114e1aa` run (16:30:45Z): free 16,296,890,368 B; nothing new to compact.
- **History re-append is OFF by default.** `SYNDICATE_TRACKING_HISTORY_CSV=1` restores `_persist_tracking_snapshot`'s full-snapshot CSV append.
- **18 plain/gz mismatched shards remain:** mlb 09-03..09-09, ncaaf 09-05, soccer 08-22..09-09. None is a byte prefix of its `.gz`, and `resolve_book_quotes_path` serves the shorter plain file.
- **Not approved / not done:** resize, retention, evaluation-ledger slimming, `odds_history` triple copies.

## [streamed-pull-append-only-tail] `pull_streamed_artifact` sends NO `since=` on append-only tails — web's stream route 304'd before Range and froze NFL `[verified 2026-09-13 in production, refresh-worker `cae4713e` live 18:31:22Z]`

- **The route.** `/api/ops/artifacts/stream` returns 304 on `st_mtime <= since` BEFORE honouring Range (`ops.py`). Probed live: since >= web mtime -> 304; since older -> 206 tail. A 304 or 416 is a silent success in the puller.
- **Measured failure.** refresh-worker's `nfl_source/tracking/book_quotes/2026-09-13.jsonl` stayed at 19,914,752 B (books from 09-12 08:02Z) while web held 28,757,424 B. The served board had 0 NFL rows for the Sunday slate.
- **Now `[verified 2026-09-15, refresh-worker `55fee786` live 18:13:26Z, still in `5686a555`; lane book-quotes-splice-repair]`.**
  - Append-only paths with a local copy sync against a `.<shard>.webpos` offset with a 4 KB overlap compare (`_pull_append_only_synced`).
  - Match: under `shard_append_lock`, cut at webpos, write web's tail, re-append local rows web lacks (`STREAM_TAIL_SYNC_OK`).
  - Mismatch, 416 or non-206: whole pull plus local valid rows, non-JSON lines dropped (`STREAM_SYNC_WHOLE reason=...`).
  - The blind `STREAM_TAIL_OK` path reads 0 since 18:13Z.
  - Whole-file families keep `since=`. (09-13: `STREAM_TAIL_OK` on the NFL shard at 18:39:40Z unfroze the board.)
  - Measured: 18:13-18:48Z SYNC_WHOLE 9 (once per shard), TAIL_SYNC_OK 13+, failures 0. After web's P3 repair (19:28Z), each touched shard resynced once on `overlap_mismatch`, dropping exactly web's refused counts.
  - DNS blips during a web restart log `STREAM_PULL_FAILED ... Name or service not known` (10 at 18:56:59-18:57:32Z) and clear on the next pass.
- **book_quotes on web `[verified 2026-09-15]`.**
  - The merge refuses non-JSON lines (`MERGE_REFUSED_BAD_LINES`, P1 `9ed5c5ad`).
  - Historical splice fragments were removed by `POST /api/ops/book-quotes/repair` (P3 `8b563ca9`, applied 19:28:33Z): 2152 from 49 shards since 09-01. 20 orphans remain, most of them 09-13 07:31-10:22Z captures.
  - **P5 `[verified 2026-09-15]`:** `publish_hot_artifact` sanitizes an append-only shard before sending, `append_book_quotes` terminates a torn tail before appending, and the tail sync parks local-only rows in `.<shard>.pending` before cutting.
    - live-odds-worker (`991a94d5`, then `8c089e8c`): web refused its soccer 09-15 merges 43/43/43 before and 0/0/0 after.
    - It still never re-syncs a shard it already holds; the sanitize is what cleans its copy.
    - Glued lines on web were split (21:44:39Z): 7 rows made readable. 20 unreadable lines remain as orphans (13 torn 09-13 heads, 4 headless 09-01 tails, 3 heads whose tail was glued).
- **Related.**
  - Web's append-only publish MERGES: line-digest dedupe, then `os.replace`, so a byte-identical republish advances only the mtime.
  - Web's merge concurrency cap is 1, so a second publish seconds later gets `ARTIFACT_MERGE_AT_CAPACITY` (503, retried by a later publish).
  - `_FAILED_DIRECT_PUBLISH` is in-process and lost on reboot.

## [refresh-worker-heavy-build-refusal] refresh-worker's heavy build is refused for hours once the MAIN PROCESS settles above ~2.2 GB after its first full build — child jobs are not the cause. Short streaks clear on their own in 10-80 min; long ones clear only on a restart `[verified 2026-09-13 in production logs, corrected 2026-09-14 by a 45 h streak replay, lane heavy-build-memory-refusal]`

- **Streak shape, 09-12 18Z..09-14 15Z** (23 closed streaks): 18 ended with an admitted build and no boot (1-22 refusals, 10-80 min). 5 ended only at a boot, among them streaks of 24, 401 and 120 refusals. Boot to first admitted build has a median of 13.1 min (6 boots).
- **Stopgap by user decision 2026-09-14:** recycle threshold 1 (env `SYNDICATE_REFRESH_WORKER_RECYCLE_AFTER_REFUSALS=1`). Live since refresh-worker `6fe6c6e9` (15:37:05Z) `[verified 2026-09-14, deploy + env single-key read]`.
  - A replay with recycle's child-job hold gives ~612 blocked minutes at 1 vs ~1,044 at 15 over 24 streaks, i.e. ~40% better. Child jobs were present in 55-68% of samples, so a restart is often held.
  - The root-cause work is lane `heavy-build-child-process`.
- **Where pid 39's growth comes from `[verified 2026-09-14, one boot of 0a18557a, 504 staged ALL_PROCESS_MEMORY samples; shares are rough because threads interleave]`:** +1,516 MB in 109 min.
  - Live-lens loop builds +883 (soccer +414, mlb +388); heavy build +497; startup +390 (before any build); MLB sim tick +149 net; live-lens pulls -426 net (the spike is trimmed right after).
  - **The live-lens loop is OFF on refresh-worker `[verified 2026-09-15 02:33Z]`:** by user decision `SYNDICATE_ENABLE_LIVE_LENS_LOOP=false`, deployed in `c4f45fee`, with `LIVE_LENS_LOOP_START_RESULT started=False` and 0 live-lens ticks.
    - live-odds-worker is the sole writer of `live/mlb_live_lens.json` (3.48 MB writes, 02:33Z / 02:35Z).
    - Before that, both workers built and wrote it (two MLB writers measured 22:40-23:17Z 09-14).
    - Owed: live-odds-worker memory with the loop alone on a full slate, and refresh-worker per-build growth without the live-lens builds.
- **Candidate-pool cache `[verified 2026-09-14]`:** one 09-14 pool is 19.7-28.2 MB of JSON; a 09-15 pool is 6.2-7.2 MB.
  - **`SYNDICATE_CANDIDATE_POOL_CACHE_MAX=1` on refresh-worker since deploy `dep-dal1djoae00c73f7ajug` (`0d3cea8f`, created 2026-09-16 04:10:55Z) `[verified 2026-09-16: single-key GET reads 1; every post-deploy CANDIDATE_POOL_CACHE line reads limit=1 and cache_json_bytes == pool_json_bytes]`.** Was 2 (code `0a18557a`, log field `d4deb502`). Absent on web and live-odds-worker.
  - **The pool's JSON->RSS multiplier is UNKNOWN. A ~3x figure was recorded 2026-09-16 and WITHDRAWN the same morning** `[verified 2026-09-16 14:10Z from the Render deploys and events APIs]`: every cache drop that showed RSS falling with the cache spans a refresh-worker RESTART (22:07->22:24Z spans 22:12:03Z; 23:29->23:57Z spans 23:33:30Z; the "183.2 -> 0 MB, -525.5 MB" flush 00:13->01:03Z spans 00:36:13Z). A restart empties the cache AND resets RSS, so those ratios measured boots. The one restart-free drop (02:40:43->03:26:27Z, -47.4 MB cache) moved RSS -30.0 MB, ratio 0.63; the two restart-free small drops saw RSS rise. The 3.33 regression pooled three boots. On a live slate a pool did reach 108.0 MB and the `limit=2` cache 203.2 MB — those sizes stand.
  - **The saving from `limit=1` is UNMEASURED and has NO clean prediction** (the ~300 MB figure rested on the withdrawn multiplier). The post-deploy RSS drop is boot-confounded; the cap survived a later deploy (`5abc20f3`, 05:06:56Z, not this lane's).
  - Over builds 1-4 pid 39 grew ~164 MB less than on an uncapped boot, but kept growing (+291 MB over builds 3-6). The cache is part of the tail, not all of it.

- **Guard.** `MEMORY_GUARD_ABORT stage=pre_source_state_fingerprint floor_mb=1900` at the top of `_compute_board_publication_response`; basis = 4096 - unreclaimable. 403 refusals 09-12 21:34Z..09-13 16:14Z.
  - It stopped `CANDIDATE_POOL`, `BOARD_PUBLICATION`, `PORTFOLIO_COMMIT` (paper orders) and Kalshi capture. `LAYER2_FAST_REFRESH` (600 MB floor) kept the board alive.
- **Cause measured.**
  - After each boot unreclaimable starts ~75 MB. It crosses 2,196 MB 16-60 min later (the first full build) and then holds: hourly min 2,049 -> 2,241 MB over 16 h.
  - pid 39 rss 2.1-2.4 GB. `UNTRACKED_BYTES_CENSUS` explains only 16% of anon as Python objects.
  - 3,303 of 7,159 refused-level samples had `process_count` 2, i.e. no children.
  - Heavy builds resumed within minutes of the 13:42Z, 16:23Z and 18:31Z boots.
- **The floor is roughly right.** Steady-state builds peak +296 / 719 / 1,416 MB above start (2 s `MEMORY_WATCHDOG`, n=12), minimum headroom at peak 633 MB, at parent stages (`board_contract_end`, `build_live_state_payload_fallback`). The MLB hydrated overview runs in a capped child (`[overview_isolation] OK` 33/33, 0 `MEMORY_CAP_HIT`), so the floor's 08-07 sizing comment describes a stage no longer in pid 39.
- **Fix LIVE and EXERCISED ONCE `[verified 2026-09-15 01:34:39Z, refresh-worker logs + Render events]`:** `RECYCLE_EXIT` after 2 refusals with 0 children; Render `server_failed earlyExit` (not evicted) then `server_available` 1 s later; boot 32 s after the exit.
  - During the live slate before it, 5 checks held on `children_running`: the recycle cannot fire while slate jobs run.
  - Heavy builds resuming after the exit: OWED at the time of writing.
  - Earlier history, kept: `339dc6e9` `worker_recycle` has been on refresh-worker since `fb0c91cf` (13:39:49Z); refresh-worker was on `6438830d` from 21:03:17Z.
  - The worker exits (Render restarts it) after >= N consecutive refusals (env, now 1; 0 disables), uptime >= 30 min, no live child, no drain.
  - On `fb0c91cf`, refusals came back 50m45s after live (14:30:34Z). They were then reset by an admitted build at 15:22Z before any recycle.
  - The later boots (15:38Z, 17:29Z, 19:07Z, 21:03Z) logged 0 refusals before the next deploy. No `RECYCLE_EXIT` has ever been observed.

## [refresh-run-lanes] Refresh-run lane topology, and refusals are now LOGGED [verified 2026-09-25/26]

`SYNDICATE_REFRESH_RUN_PER_SERVICE_LANES` is ON in production. A lane is one
"only one refresh run at a time" mutex, and an explicit `lane=` on
`launch_refresh_run` creates a private one. SEVEN lanes exist; two on the SAME
container run concurrently as a matter of course (measured in one fetch
22:13:53Z: `live-odds-worker` pid 6472 and `live-odds-worker-ncaaf-lines` pid
8532, both running).

    live-odds-worker                 the COMBINED sweep (the tick) + look-ahead
    live-odds-worker-ncaaf-lines     _launch_autorun_ncaaf_lines_refresh
    live-odds-worker-nfl-lines       _launch_autorun_nfl_lines_refresh
    live-odds-worker-wnba-live       _launch_autorun_wnba_live_refresh
    live-odds-worker-wnba-pregame    _launch_autorun_wnba_pregame_refresh  [NEW 8edd8778]
    refresh-worker                   mlb / weekly_sports / soccer_weekly autoruns
    web                              (idle since 2026-08-31)

STILL SHARING the combined sweep's lane, so still able to contend with it:
`_launch_autorun_soccer_pregame_refresh` (live-odds-worker) and all three
refresh-worker autoruns.

**A refused launch now NAMES itself** (`890b90e4`+): `REFRESH_LAUNCH_REFUSED
reason=<lane_busy|state_unconfirmed> lane= pid= run_stamp=` from
`ops_refresh._raise_refresh_refusal` (the raise site, so all 14 call sites), plus
`ODDS_SWEEP_REFUSED ... sports=` from the loop. `lane_busy` is benign and
self-correcting; `state_unconfirmed` is FAIL-CLOSED - nothing is running to
release it, so it refuses every launch permanently. Do not read them as the same.

**A refusal no longer costs an interval** (`ec10612a`+): the global
`last_odds_refresh_launch` marker is rewound on any `RefreshRunRefused`, because
`_off_hours_gate_blocks_launch` reads it as "when did odds last refresh" and
would otherwise suppress real launches. A launch that DIED is deliberately not
rewound.

**The combined sweep SELF-COLLIDES, and that is BACKPRESSURE, NOT A DEFECT**
[investigated + closed 2026-09-26, USER DECISION: leave it]. The tick polls on a
~60s interval against a sweep taking ~4-6 min, the mutex serialises, the tick
retries. Do not re-litigate it as a bug; the numbers below are why.

Measured 2026-09-25T22:56Z -> 2026-09-26T13:47Z: **177 launches vs 96 refused
attempts (35%)**, and the refuse rate is FLAT across every sport sharing the
tick -- mlb 36%, ncaaf 36%, nhl 37% (wnba 46% on n=26). A starved sport would
show a refuse rate far above the others; none does. 65 distinct holder
run_stamps behind those 96 refusals (mean 1.48, median 1) -- the tick discovers
'busy' once and moves on, it does not spin.

A refusal costs NOTHING now: raised before `launch_refresh_run` starts anything,
so no OddsAPI call, and `ec10612a` rewinds the global marker. The two real harms
(invisible; cost a refresh interval) are both fixed.

**DO NOT 'fix' this with `is_refresh_run_active` as a pre-check.** It has NO
stale-pid healing -- its own docstring says it deliberately skips the
reconciliation `_assert_no_active_refresh_run` performs -- so it can report a
lane busy when the real guard would have healed the manifest and allowed the
launch. A pre-check on it would SKIP launches that would have succeeded, which
is the starvation class this whole 2026-09-25 arc existed to remove. Any future
pre-check must use an authoritative read WITH healing and must FAIL OPEN.

**Production intervals are env-set, not the code defaults.** WNBA pregame runs at
7200s, not the 14400s fallback in `_wnba_pregame_refresh_interval_seconds`.


## [pregame-sweep-cadence] THE IDLE LOOP NOW WAKES WHEN A SPORT'S OWN PREGAME SWEEP IS DUE; soccer schedules refetch a near window between 6-hourly full rebuilds `[2026-10-02 22:10Z-23:40Z, fleet 963c2374 + de28521c, lane layer2-freshness-1h]`

**Before (measured on the fleet 2026-10-02):** with nothing live, `live_refresh_loop` slept the 900s idle
interval after every tick, so per-sport pregame intervals were only CHECKED every ~16 min -- any setting
between 16 and 32 min fired at ~32 (NFL/NCAAF at 1500s launched 20:37:55Z then 21:15:56Z, 38 min apart).
The GLOBAL off-hours gate (900s since any sport's sweep) and the flat 1800s per-sport relaunch cooldown
also held shorter intervals back. Oldest NFL/NCAAF/WNBA board rows peaked 57-60 min against the 1h rule.

**Now (963c2374, live on live-odds-worker from 22:10Z):** idle wait = min(idle, next sport due + 5s),
floor 60s (`_pregame_idle_wait_seconds`); a due sport bypasses the off-hours gate
(`OFF_HOURS_GATE_BYPASSED_SPORT_DUE`); an EXPLICIT `SYNDICATE_PREGAME_SWEEP_INTERVAL_SECONDS_<SPORT>`
below the cooldown shortens that sport's cooldown. Due-ness is STRICT (checker says not live, marker
stamped, not league-scoped). Off switch `SYNDICATE_PREGAME_TICK_FOLLOWS_DUE=0`. Seen live: sleep 733s
timed to WNBA's due time; bypass fired for nfl,ncaaf 22:18:55Z and wnba 22:33:00Z. A refused (lane_busy)
due sport keeps its rewound marker and retries every ~1.5-3 min -- refusals spend no credits.

**Soccer (de28521c, fleet NOT yet fast-forwarded at 00:10Z 10-03 -- verify):** the soccer pregame run
rebuilt ten leagues' FULL seasons every run -- 1,327 of 1,416 step-seconds (run 20261002_223521, 24 min;
ESPN refuses every range here so a full build is ~one request per date) against 11 s of odds -- holding
the refresh lane and refusing every other sport's sweep. Now `--near` (today-2..+7, merged by event_id)
unless the last FULL build is > `SYNDICATE_SOCCER_SCHEDULE_FULL_REBUILD_SECONDS` (21600). Live-ESPN check:
mls near 14s vs full 91s, result identical to a fresh full build (511/511). Soccer's earlier "~10 min"
runs were FAILURES (rc 1 at the Belgian schedule step until 5566d4ba), not its normal duration.

**Fleet env (local_production.env, read only at SUPERVISOR start -- a child restart re-uses the old
values):** sweep intervals NHL 1800, NFL/NCAAF/WNBA 1500, WNBA autorun 1500, soccer autorun 2700 (the
key was absent from the file; render.yaml's 14400 applied); shortlist 1h gate NHL/WNBA by code,
NFL/NCAAF/SOCCER by env.

**SHOWN `[verified 2026-10-03 12:30-16:30Z, Saturday pregame, 77 samples/sport, ~/satwatch/summary.txt]`:** 0 rows served > 1h in every sport and sample. Launch gaps NFL 25.2 / WNBA 25.2 / NHL 30.1 / MLB 60.1 min median (the configured intervals; were 32-38 before 963c2374). Served-row age p90 NFL 12.6, NCAAF 9.2, NHL 18.4, soccer 19.4 min. The OLDEST served row sits near 60 min (NFL 59.7, NCAAF 60.0, NHL 59.8 max) because the 1h gate CENSORS it -- that tail is hidden at 60: NFL 301, NHL 193, NCAAF 110, soccer 153 median. **MEASURED 2026-10-04 16:29Z (quote keys on the fleet, not a guess): they are DEAD LINES, not missed ones** -- of NFL's 8,641 pregame keys last seen > 1h, 90% are `line_moved` (the same book+side is quoted fresh at another line; the old key just stops being seen), 6% book dropped the market, 3% market gone, 0.3% side dropped; median age 25.6 h. NHL: 84 stale, 90% line_moved, median 7.9 h. Hiding them is correct and there is NO coverage gap. Consequence: `rows_beyond_quote_age` mostly counts superseded lines and cannot serve as a freshness alarm unless split. 'oldest ~45 min' was the wrong metric. Soccer runs 2.3 min with 1 full + 9 near schedules (stagger 1433933d live). lane_busy refusals 15 in 4h (12 live-phase), against 129 overnight.
**ALSO LIVE:** restart -> first sweep 1m48s (Polymarket boot work on a thread, ba7e2d3a; was ~13 min); slate sweep single-flight (fef0df47).

## [web-oom-leak] WEB SERVICE MEMORY GROWTH — the UPDATE 1..44 chain, 2026-09-04 onward, moved here VERBATIM 2026-10-04

Moved out of `state.md`'s `[subject-index]` section by session 4ab694ed (user: “fix the state.md budget”). **It had NO `##` section and NO index row ANYWHERE** — 46 `###` UPDATE blocks, 105,320 chars, sitting under the index heading — so the largest subject in `state.md` was invisible to the index that exists to find it, and `state_key_check.py`'s subject count never included it. Filed here because this part already holds the service-memory subjects (`[service-memory-saturation]`, `[accuracy-autorun-OOM-2026-09-02]`, `[refresh-worker-headroom-2026-09-02]`).

**NOTHING IS RESTATED.** The blocks below are verbatim and carry their own conclusions, including the retractions among them (UPDATE 43 retracts an earlier “not me”); the heading above deliberately describes the CHAIN rather than asserting a current state, because this was a MOVE and the 44 updates were not re-derived. Newest is UPDATE 44.

### `[web-oom-leak]` UPDATE — the instrument is fixed and the growth has a SUSPECT, 2026-09-04T00:4xZ `[session b2b5b45b]`

**Supersedes the "needs an INSTRUMENT change" line in the entry above — that
change shipped (`442f82fe`) and is verified REACHED**, not merely deployed:
emissions carry `attribution_basis = process_anon_smaps_rollup` with a non-null
`process_anon_mb_now` and `unreadable = 0`. Attribution now differences THIS
PROCESS's anon (`/proc/self/smaps_rollup`), so its scope matches the per-worker
`inflight` guarantee.

**THE PREVIOUS CULPRIT WAS AN ARTEFACT.** `/api/ops/artifacts/publish` read
**211 MB** container-scoped and reads **1.15 MB across 81 solo requests**
per-process. A publish spawns a merge CHILD; the container-scoped instrument
charged the child to the parent's request. **Any earlier conclusion pointing at
publish came from measuring the wrong scope.**

**THE SUSPECT: `/api/intelligence/query`, ~82 MB PER CALL** — 408.0 MB over 5
calls, replicated on both workers. Infrequent and very expensive; nothing else is
within an order of magnitude (publish moves tens of MB across HUNDREDS of calls).
It does NOT recompute — `read_combined_intelligence_response` only reads what the
background loop already built — it MATERIALISES AND HYDRATES a large precomputed
payload, and CPython does not return freed arenas. `intelligence.py:1600` notes
slimming that payload would change an API contract, so the fix is not free.

**THE RANKING IS TRUSTWORTHY; THE SHARE IS NOT.** Attributed 408 MB against
342 MB of actual process growth. One contamination source remains and it is
named: `syndicate/app.py` runs the live-refresh and intelligence-state loops IN
THE SAME PROCESS, and `inflight` guarantees no other REQUEST, not no other
THREAD. Of three sources — cross-worker, merge children, same-process threads —
two are gone.


### `[web-oom-leak]` UPDATE 2026-09-09 22:2x CT `[lane web-oom-census, session 2edf8b82]` — THE KILLS ARE 16 NOT 2, THE MEMORY IS ANON NOT CACHE, AND A SECOND PATH IS NAMED

**THIS DOES NOT DISPLACE THE `/api/intelligence/query` SUSPECT ABOVE.** That was
measured per-PROCESS, per-ENDPOINT (`process_anon_smaps_rollup`), which is a
better attribution instrument than anything used here. The two have not been
compared on one instrument and **must be before either is called the cause.**

VERIFIED this session:

- **16 `oomKilled` at `memoryLimit=2Gi`, 2026-08-25..09-09** (events API), against
  the **2** `#632` records. 14 landed after that item was written; one was
  2026-09-09 17:54 CT. By Central day: 08-29 x1, 08-31 x1, 09-02 x3, 09-03 x1,
  09-06 x3, 09-07 x1, **09-08 x5**, 09-09 x1. 37 `unhealthy` in the same window,
  so a raw `server_failed` count inflates this ~3.3x.
- **ANON is the dominant and volatile term, not page cache.** Web emits
  `CONTAINER_MEMORY` (NOT `ALL_PROCESS_MEMORY` — that is worker-only, and looking
  for it on web is why this split had not been taken). 60 samples:
  `memory_anon_mb` **546 -> 1,168** (+621), `memory_inactive_file_mb` 242 -> 635,
  `memory_current_mb` up to **1,961 of 2,048**, **minimum headroom 87 MB**.
  **`#566`'s page-cache explanation does not transfer to this service.**
- **A SECOND PATH: `/api/home` rebuilds live state payloads ON THE REQUEST PATH.**
  Chain read link by link in `syndicate/blueprints/home.py`: `@home_bp.get("/api/home")`
  and `@home_bp.get("/syndicate")` -> `api_home:8418` -> `_home_payload:8295` ->
  `build_home_overview:8240` -> `_build_sport_overview:7616` ->
  `_load_home_prop_items:7100` -> `_load_home_live_prop_items:5953` ->
  `build_live_state_payload`. **`live_refresh_loop.py` calls none of these**, so
  the request path is the only entry. Every `CONTAINER_MEMORY` sample is tagged
  with those stages.

**NOT ESTABLISHED:** which of the two paths dominates, or whether this one is the
largest allocator at all — no per-allocation profile was taken here. **The next
action is running the `/api/home` path through the SAME per-process anon
instrument that produced the 82 MB/call figure**, so the two are comparable.

**If the request-path build is confirmed material, the fix is architectural** —
`CLAUDE.md` puts this payload in a worker-written artifact that web READS.

### `[web-oom-leak]` UPDATE 2 — the payload is down ~74% and the instrument is honest, 2026-09-04T02:3xZ `[session b2b5b45b]`

* **Per-request attribution now measures THIS PROCESS** (`/proc/self/smaps_rollup`),
  so its scope matches the per-worker `inflight` guarantee (`442f82fe`, verified
  REACHED). **Supersedes every earlier route ranking**: `/api/ops/artifacts/publish`
  read 211 MB container-scoped and **1.15 MB across 81 solo requests** per-process,
  because a publish spawns a merge CHILD that the old scope charged to the parent.
* **The largest per-request allocator is `/api/intelligence/query`, ~82 MB/call**
  (408 MB over 5 calls, both workers). It does NOT recompute; it materialises and
  hydrates a large precomputed payload.
* **That payload is now ~74% smaller.** The self-nested mirror is gone (50.0%,
  `53a1052b`) and the alias duplication is opt-in-slimmed (47.9% on a same-slate
  live A/B, `b3966bf1`): `recommendations` -> `top_opportunities`, `boardContract`
  -> `board_contract`, `by_sport` regrouped from `ranked_all`, described in
  `_response_aliases` and rebuilt client-side.
* **OPT-IN: a caller that does not send `slim_aliases` is byte-for-byte
  unaffected.** Verified live; a test exists whose only job is to fail if that
  ever changes.
* **STILL OPEN:** one contamination source remains and it is named —
  `syndicate/app.py` runs the live-refresh and intelligence-state loops IN THE
  SAME PROCESS, and `inflight` guarantees no other REQUEST, not no other THREAD.
  So the route RANKING is trustworthy and the exact SHARE is not.
* **NOT re-measured:** whether the ~74% cut moves the ~500 MB/h growth rate. That
  needs a fresh uninterrupted window.

### `[web-oom-leak]` UPDATE 3 — the rate is re-measured: +173 MB/h, down 66%, 2026-09-04T03:2xZ `[session b2b5b45b]`

**Supersedes the "NOT re-measured" line in UPDATE 2.** Fitted on 81 merge-child-free
plateau samples (25.5-62.7 min uptime) on web `b3966bf1`: **+173 MB/h, R^2 0.90**,
against the pre-cut **+503 MB/h, R^2 0.75, n=32**. Time to the 2,048 MB limit goes
**2.0 h -> 5.7 h**, i.e. past the 2.45-3.13 h uptimes at which this service was
being OOM-killed.

**Confounded in two ways, both registered before the measurement:** different time
of day (02:40Z vs 22:30Z), and the alias half of the payload cut is OPT-IN so it
only applies when a browser drives the page — meaning **-66% is most plausibly the
self-mirror half alone**. Consistent with the fix; not proof of it.

### `[web-oom-leak]` UPDATE 4 — rate down 66%, four mechanisms ruled out, 2026-09-04T14:5xZ `[session b2b5b45b]`

* **Growth rate re-measured after the payload cut: `+503 -> +173 MB/h`** (fitted,
  R^2 0.90, n=81 merge-child-free plateau samples). Time to the 2,048 MB limit
  **2.0 h -> 5.7 h**, past the 2.45-3.13 h uptimes at which web was being killed.
  Confounded by time of day, and the alias half of the cut is opt-in — so this is
  consistent with the fix, not proof of it.
* **The attributed SHARE is still not recoverable, and four candidates are now
  eliminated by measurement:** cross-worker cgroup scope (CONFIRMED, fixed by
  per-process anon); background loops (FALSIFIED — neither runs on web, and the
  gate built for them is INERT); GC timing (EXCLUDED — the one gen-2-overlapping
  request was POSITIVE while the non-overlapping group went negative);
  `LAST_RESULT` reassignment (EXCLUDED — 0.0 MB both halves).
* **THE CONSTRAINT THAT KILLS PER-STATEMENT PROBES:** CPython returns freed
  objects to pymalloc's ARENAS, not to the OS. An in-Python free cannot reduce
  `Anonymous:`. A negative anon delta therefore requires ARENA RELEASE — an
  emergent property of allocator free-list state, attributable to no statement,
  request or thread.
* **NEXT INSTRUMENT, if the symptom returns:** `malloc_info` / pymalloc arena
  counts around the negative windows, not another attribution probe.
  `memory_observability` already carries `parse_smaps` and `#435`'s arena-vs-anon
  comparison. The question is "when does an arena empty".
* The symptom is INTERMITTENT — zero negative routes in the last two windows.
  Nothing is confirmed; four things are ruled out.

### `[web-oom-leak]` UPDATE 5 — **POSITIVELY IDENTIFIED: 8-64MB anon mappings**, 2026-09-04T18:09Z `[session b2b5b45b]`

* **The growth is in LARGE ANONYMOUS MAPPINGS (8-64MB regions).** Measured on
  `76c0e174` via `smaps_trend` split by pid, gate pre-registered before the data:
  pid 79 `+148.70 MB / 37.3 min` with **80.5% in `8-64MB`**; pid 78
  `+54.10 MB / 34.6 min` with **85.4%** there. `UNNAMED` `0.00` on both — the
  breakdown sums to its own total. `<64KB` and `64KB-1MB` unchanged to the
  decimal across all 12 readings.
* **This is the first POSITIVE finding in `#632`; the previous five were
  exclusions.** It also explains WHY they were: pymalloc arenas cover ~40% of
  worker RSS and glibc `malloc_info` reached 13.9% coverage in `#435`. **Both are
  structurally blind to an allocation over 512 bytes**, so their flat readings
  were never evidence of a flat process.
* **CORRECTS an intermediate claim made the same session.** With only the size
  buckets recorded, the residual computed by subtraction read as 65-70%
  "non-mmap" and I proposed glibc's main arena. Recording `by_kind_mb` retired
  that: heap is **7.4% / 14.6%**, a minority term.
* **NOT ESTABLISHED:** what allocates those regions; and the rates
  (`+239.4` vs `+93.7 MB/h`) are EARLY-LIFE and not comparable to the `+173 MB/h`
  plateau figure. **The two workers differ 2.6x on one container in one window,
  unexplained.**
* **NEXT MEASUREMENT:** does the climb track which worker serves
  `/api/intelligence/query`? That discriminates the payload story from
  everything else, and it is answerable with the instrument already deployed.

### `[web-oom-leak]` UPDATE 6 — **query correlation is NULL, and `/api/intelligence/query` was never called**, 2026-09-04T18:2xZ `[session b2b5b45b]`

* **NO ROUTE'S CALL RATE EXPLAINS THE 8-64MB GROWTH.** Per-worker, per-interval,
  every quantity as a PER-MINUTE RATE (n=13 intervals, 2 workers): after
  dropping one high-leverage point every `|r| < 0.45`, and Pearson disagrees
  with Spearman in SIGN on three of five routes.
* **The `/api/intelligence/query` payload hypothesis is FALSIFIED for this
  window — the route received ZERO calls on either worker** while anon climbed
  +54.1 and +148.7 MB. The growth does not need an intelligence query to happen.
* **Two correlations that looked real and were not:**
  - Unnormalised, `/healthz` ranked TOP at `r=+0.682` — a route with
    `max_mb 0.00`. Differencing over UNEQUAL intervals let duration drive both
    sides. `/api/ops/artifacts/export` fell from `+0.348` to **`+0.037`** once
    normalised; the export hypothesis died there.
  - `/api/ops/artifacts/publish` at `r=-0.882` collapsed to **`-0.271`** when one
    3.1-minute interval was dropped. That was a claim about one point.
* **NEW AND POSITIVE: the 8-64MB memory IS RETURNED TO THE OS.** One interval
  (pid 79, 18:09:52->18:13:00) fell **-43.4 MB**. Large mappings are `munmap`ped
  back, unlike pymalloc arenas. **So this is not monotonic retention** — it is
  churn with a high-water mark, which is a different defect and admits different
  fixes (bounding concurrent peak, not finding a "leak").
* **INSTRUMENT LIMIT, stated so the null is read correctly:** emissions fire
  every 200 solo requests, giving 3-9 minute intervals and n=13. That is coarse
  enough to hide a real per-call effect. **This null bounds the effect size; it
  does not prove independence.**

### `[web-oom-leak]` UPDATE 7 — per-request attribution **FAILED ITS SHARE CHECK**, 2026-09-04T19:3xZ `[session b2b5b45b]`

* **A per-request smaps sampler was built, deployed (`5314e85b`, live 19:11:55Z)
  and its verdict WITHDRAWN.** It reported `/api/ops/artifacts/export` at
  **+145.10 of +145.10 MB** (100%); the share check against each process's own
  8-64MB climb gave **pid 79 = 0.0%** (process +90.30 MB, sampled requests
  +0.00) and **pid 80 = 175.0%** (process +23.20, attributed +40.60).
* **`sum(sampled)/sum(sampled)` is 100% by construction.** The denominator was a
  set of routes I chose, not the process's climb. Failing in BOTH directions
  rules out a scale error.
* **WHAT STANDS:** three events where ONE `/api/ops/artifacts/export` call grew
  anon by **39.9 / 56.9 / 48.3 MB** in the 8-64MB bucket and had not released it
  at teardown; two fired **one second apart**. 16 of 19 export calls cost
  **exactly 0.00**. The bimodality explains why five earlier probes read flat and
  why the route correlation was `r=+0.037`: a rare ~50 MB event averaged over
  3-9 minute intervals disappears.
* **WHAT DOES NOT STAND:** any claim about the FRACTION of `#632` those events
  represent.
* **WHY, hypothesised not established:** the sampler covers SOLO requests on an
  allowlist of two routes, and `skipped_concurrent` was **285** — most export
  calls are never sampled. pid 80's >100% additionally implies memory released
  after the window, consistent with the observed `-43.4 MB` interval.
* **INSTRUMENT COST: 64.93 ms mean / 150.50 ms max per sampled request**, 28-64x
  the synthetic estimate. Allowlist set to the sentinel `__off__`.
* **NEXT:** attribution must cover ALL requests, not an allowlist, and needs
  process readings dense enough to divide by — an emission every 200 solo
  requests cannot verify a 10-minute window.

### `[web-oom-leak]` UPDATE 8 — `proc_token` shipped INERT (fork inheritance); residual still unmeasured, 2026-09-04T20:3xZ `[session b2b5b45b]`

* **`proc_token` was generated at IMPORT and gunicorn forks workers AFTER the
  import**, so every worker inherited the same value — pid 99 and pid 98 both
  emitted `6178fc632433` (measured 20:24-20:26). Fixed by deriving it lazily and
  re-minting whenever `os.getpid()` changes (`b36d993f`).
* **The broken version produced a CONFIDENT WRONG ANSWER, not a null:**
  `r = +0.870`, "residual tracks skipping", 18.0% coverage over 3 "clean"
  windows. **DISCARDED** — those windows differenced one worker against another.
  The tell was a window reporting `solo 0` beside `attributed -103.22 MB`.
* **The residual is therefore STILL UNMEASURED.** Nothing about skipped requests
  as the gap is established; the earlier `r = +0.870` must not be quoted.
* Two instrument defects fixed and landed before it (`63e45361`): `routes` is
  truncated to `top=12` (differencing it read **4842% unexplained**), so
  `attributed_total_mb` is now untruncated; and `skipped_concurrent` counts
  CONTAMINATED WINDOWS, not requests — one overlap increments it twice.
* **NEXT:** collect >= 3 windows on `b36d993f`, with the collector refusing any
  token that spans more than one pid.

### `[web-oom-leak]` UPDATE 9 — **the residual is measured: 82.3% covered, and skipping is NOT the gap**, 2026-09-04T21:3xZ `[session b2b5b45b]`

* **16 clean windows, 2 distinct process tokens, ~50 min: process `+669.30 MB`,
  attributed `+550.67 MB`, residual `+118.63 MB` — 82.3% COVERED.** Stable under
  doubling n (75.9% at n=8). This is `#632`'s first stable share.
* **FALSIFICATION TEST FIRED — the residual does NOT track `skipped_concurrent`:**
  pearson `+0.236`, spearman `-0.047`, and `+0.087` without the single leverage
  window. Skipped requests are not the gap; the solo-only rule is not what hides
  the memory.
* **PER-WINDOW COVERAGE IS UNUSABLE** (`-130%` to `+452%`, over 100% in five
  windows, negative in four). Under munmap-heavy churn, a per-request delta and a
  net process change are different quantities. **Quote the aggregate, never a
  window.**
* `residual` vs `process climb` (pearson `+0.856`) is PARTLY DEFINITIONAL —
  `residual = process - attributed`. Not independent evidence.
* **Three earlier verdicts from this same collector were wrong**, all small-n
  coefficients: `-0.999` at n=3, `+0.870` on merged workers, `+0.710` at n=8
  collapsing to `-0.297` on leave-one-out. Gate is now n>=8 + leave-one-out +
  Spearman beside Pearson.
* **NEXT for `#632`:** the 8-64MB mappings are identified and requests own ~82%
  of the movement, but no single route owns it and per-request attribution
  cannot be made to compose. The open question is the remaining ~18% and whether
  the churn HIGH-WATER MARK — not a leak — is what OOMs the service.

### `[web-oom-leak]` UPDATE 10 — **RETENTION, not churn. Two independent instruments agree**, 2026-09-04T22:4xZ `[session b2b5b45b]`

* **`VmHWM - VmRSS` is ~29 MB on BOTH workers** (pid 98: 682.98 vs 654.28; pid 97:
  640.88 vs 612.09), and `process_anon_mb_now` EQUALS the running peak on both.
  A process sitting at its own all-time high-water mark has not returned memory.
  **Churn would show a large HWM-RSS gap. It does not.**
* **Independent confirmation from a 60-sample RSS poll of `/api/ops/memory`**
  (20 min, 20 s cadence): in EVERY series the floor equals the FIRST reading —
  worker 97 `380.8 -> 612.1`, worker 98 `434.8 -> 811.0 peak`, container
  `1248.0 -> 2037.0 peak`, unreclaimable `793.4 -> 1403.3 peak`. **Nothing ever
  returned below where it started.**
* **The container touched `2037.0 MB` — 99.5% of the 2048 MB limit**, ~11 MB of
  headroom, at a moment when a transient merge child (pid 198, 94 MB) was
  present. Steady state at the time of writing: **1888.5 MB, 92.2%, 159.5 MB
  headroom**.
* **THE SYNTHESIS, and it corrects an earlier reading in this same session:**
  worker retention is the DOMINANT term and transient children are a small
  additive one. An earlier note called them roughly equal partners; the
  `VmHWM-VmRSS` reading settles it. The children matter only because they land
  on a floor that retention has already raised.
* **INSTRUMENT DEFECT, mine:** `anon_extremes.floor_mb` is a RUNNING MINIMUM,
  and a running minimum over a rising series is always the FIRST reading — it
  can never rise, so it cannot detect a rising floor, which is the question it
  was built for. Both floors are pinned at their boot values. What answered the
  question was `VmHWM` vs `VmRSS`, added as a secondary reading. A WINDOWED
  minimum (last N) is the correct design.
* **`unexplained_memory_mb` is 385.5 MB** and is not yet investigated.

### `[web-oom-leak]` UPDATE 11 — merge caps lowered and **UNTESTED**; growth is NOT merges; the restart buys ~15 min, 2026-09-04T23:0xZ `[session b2b5b45b]`

* `SYNDICATE_ARTIFACT_MERGE_CHILD_CAP` **2 -> 1** (`e3a5154f`) and
  `SYNDICATE_ARTIFACT_MERGE_INFLIGHT_MB` **-> 16** (`3a9153f4`), both deployed on
  CLEAR preflights. **verify: UNTESTED — 0 merge children in 75 polls / ~20 min.**
* **The container ramped `1066.8 -> 1988.5 MB` (52% -> 97%) with NO merge child
  running.** Merges are not the driver of the current growth; both changes bound
  a path that is not firing.
* **The restart bought ~15 MINUTES, not hours:** `1888.5 (92.2%) -> 1133.4
  (55.3%)` at go-live, back to `1871.4` within 20 min.
* **CORRECTS my own earlier estimate.** I said "a few hours", carrying the
  `+173 MB/h` plateau rate from a quiet period into a much busier regime.
  Measured: `52% -> 96.7% in 11 minutes`. Stale baseline, different regime.
* Merge children are INTERMITTENT (two in flight at 22:29Z, pids 281/284, which
  delayed the first deploy) — so the caps may be exercised in a later window.
* **`#632` STILL HAS NO FIX.** Retention is the dominant mechanism (`VmHWM -
  VmRSS` ~29 MB both workers; every polled series floor == first reading), it has
  no identified owner, and neither env change touches it.

### `[web-oom-leak]` UPDATE 12 — **CORRECTION to UPDATE 10: it is BOTH, and my "retention, not churn" rested on one time point**, 2026-09-04T23:2xZ `[session b2b5b45b]`

* **UPDATE 10 said "RETENTION, not churn" on the strength of `VmHWM - VmRSS`
  reading ~29 MB on both workers. A later emission from the SAME session
  undercuts it.** The full series, in time order:

        22:17:09  pid 98   HWM 436.0  RSS 389.3   gap  46.8
        22:20:49  pid 97   HWM 606.2  RSS 571.9   gap  34.4
        22:22:57  pid 98   HWM 683.0  RSS 606.0   gap  77.0
        22:29:14  pid 97   HWM 640.9  RSS 612.1   gap  28.8
        22:31:00  pid 98   HWM 683.0  RSS 654.3   gap  28.7
        22:36:33  pid 97   HWM 766.8  RSS 612.1   gap 154.7   <-- 155 MB RETURNED

* **pid 97 reached 766.8 MB and came back down ~155 MB** — memory RETURNED, which
  is churn. **pid 98 held its HWM flat at 683.0 while RSS climbed 606.0 -> 654.3**
  — memory RETAINED. **Two workers in one container doing different things.**
* **The 29 MB reading I built a verdict on was a COINCIDENCE of one sample
  instant**, when both workers happened to sit near their peaks. Two emissions
  later the same worker read 154.7.
* **Correct statement: BOTH mechanisms are present.** Peaks are returned
  sometimes, and the baseline still trends up. UPDATE 10's exclusive framing is
  withdrawn; the container-level facts in it (ramp `1066.8 -> 1988.5`, restart
  buying ~15 min) stand.
* The `anon_extremes` collector printed `VERDICT: ... CHURN` — **ignore that
  line.** It is computed from `floor_mb`, a running minimum that cannot rise
  (UPDATE 10 records the defect). Its own caveat says to read `VmHWM - VmRSS`
  instead, which is what the series above does.
* **METHOD NOTE:** a single-timepoint reading of a monotone-vs-current gap cannot
  distinguish these mechanisms — the gap is near zero whenever a process happens
  to be AT its peak, regardless of whether it returns memory later. It needs a
  SERIES, and UPDATE 10 did not have one.

### `[web-oom-leak]` UPDATE 13 — **the retainer is NOT a module-level container: census explains 6.1% of growth**, 2026-09-05T02:5xZ `[session b2b5b45b]`

* **Two readings, one worker, 13.7 min apart, budget not exhausted:** census
  `59.0 -> 64.9 MB` (+5.9) while process anon went `389.3 -> 486.1 MB` (+96.8).
  **The census explains 6.1% of the growth.** Level coverage 15.6% / 12.5% on the
  two workers.
* **NAMED RETAINERS (level, not growth):**
  `_COMBINED_INTELLIGENCE_RESPONSE_CACHE` **~20 MB in ONE entry**;
  `soccer.cards._CARDS_CONTEXT_CACHE` 14.45 MB / 29;
  `mlb.cards._MLB_CARDS_CONTEXT_CACHE` 6-10 MB / 4 (**+11.21 MB on one added
  entry**); `_MLB_TODAY_CACHE` 7.6-10 MB; `LAST_RESULT` ~5 MB.
* **`LAST_RESULT` reconciles two earlier readings:** it HOLDS ~5 MB and grows
  0.0 MB per request. The per-request probe was right and so is this.
* **READ THE LIMIT BEFORE QUOTING THE 6.1%:** the walk's ROOTS are module globals
  that are already containers. A module-level OBJECT with caches in its
  `__dict__`, a class attribute, a closure, or thread-local state is never
  reached. The claim is **"not in container-typed module globals"**, NOT "not in
  Python". Widening the roots is the next step.
* **Instrument cost:** 1.2 s, ~10 MB transient, walk completes at 2M nodes. At
  lower caps the budget exhausts and the ranking becomes *biggest among whatever
  was reached first* — the 20k/100k/400k runs are NOT quotable.
* Worker anon grew **+96.8 MB in 13.7 min (~424 MB/h)** during this window,
  consistent with the fast regime measured earlier tonight.

### `[web-oom-leak]` UPDATE 13 — **the retained bytes are NOT Python objects (28.3%). The object-graph line is CLOSED.**, 2026-09-05T20:4xZ `[session b2b5b45b]`

* **Measured on pid 98 with a CONVERGED walk (891,276 nodes, not truncated):
  process anon `373.17 MB`, live Python objects `105.56 MB` — `28.3%`.
  `267.61 MB` (71.7%) is not Python objects.** Threshold pre-registered before
  the reading (`>=70%` Python / `<=35%` not).
* Convergence was the whole point: the same call read `7.2%` at a 200k cap and
  `28.5%` at 800k, both TRUNCATED. **A truncated walk reads as "not Python" —
  the correct answer here, reached for the wrong reason at any smaller cap.**
* **CORROBORATION, not proof:** an arena reading from a different worker hours
  earlier gave `bytes_in_allocated_blocks = 105.731 MB` against this walk's
  `105.56 MB` — independent methods agreeing to `0.16%`. Different epochs, so
  suggestive only.
* Implied decomposition (same caveat): `105.6 MB` live objects, `44.3 MB`
  pymalloc fragmentation, `223.2 MB` **outside pymalloc arenas entirely** —
  where the 8-64MB mappings identified earlier must live.
* **CLOSED: no Python-level probe can reach the 71.7%.** Root sets, retainer
  censuses and per-request attribution are all blind to non-object bytes.
  Remaining candidates: C-extension buffers, allocator behaviour below CPython,
  per-thread state.
* **STILL WORTH DOING, on its own merits and not as an OOM fix:**
  `_COMBINED_INTELLIGENCE_RESPONSE_CACHE` **37.50 MB** and
  `_CARDS_CONTEXT_CACHE` **12.67 MB** are real, nameable, unbounded caches.
* The census table and the heap ratio came from DIFFERENT workers (pid 99 vs
  98) — the endpoint round-robins. The ratio is self-consistent; the table is
  not a breakdown of it.

### `[web-oom-leak]` UPDATE 14 — **the GROWTH is non-Python too, not just the standing total**, 2026-09-05T21:0xZ `[session b2b5b45b]`

* UPDATE 13 measured a STOCK ratio at one instant (28.3%). That does not answer a
  GROWTH question — a heap could hold 28% of anon and still be the entire
  growing term. **Measured over 10.9 min, per worker, every walk CONVERGED (0
  truncated readings discarded):**

        pid 97   anon  +56.26 MB   heap  +0.19 MB   =  0.3% of the growth
        pid 98   anon +107.06 MB   heap +24.50 MB   = 22.9% of the growth

* **pid 97 is the decisive case: its Python heap sat at `104.68 -> 104.87 MB`,
  flat to 0.2 MB, while anon climbed 56 MB.** The verdict is upgraded from a
  snapshot to a trend: the growth itself is non-Python.
* **pid 98's 22.9% is an UPPER BOUND, not a measurement.** Consecutive walks on
  that worker swung `184.23 -> 167.18 MB` (~17 MB), so its `+24.50 MB` delta is
  only modestly above the instrument's own noise. Quote pid 97's `0.3%`.
* **RATE, measured in the same window and it is steep:** pid 97 `~307 MB/h`,
  pid 98 `~590 MB/h`, ~900 MB/h combined. Container at the end: **1756.6 MB,
  85.8%, 291 MB headroom.**
* Nothing changes about the `#632` conclusion except its strength: no
  Python-level probe can find the growing bytes.

### `[web-oom-leak]` UPDATE 15 — **CORRECTION: I quoted page cache as OOM pressure. Real pressure is 54%, not 86%.**, 2026-09-05T21:2xZ `[session b2b5b45b]`

* **`container_memory_mb` INCLUDES RECLAIMABLE PAGE CACHE and is NOT the OOM
  metric.** I quoted `1756.6 MB / 85.8% / 291 MB headroom` and projected an OOM
  in ~20 minutes. Minutes later the same figure had FALLEN to `1509.1 MB` while
  both workers' RSS went slightly UP — a ~247 MB move that no process made.
* Split over 5.1 min (7 samples, 50 s apart):

        total           +151.2 MB   -> +1786 MB/h   (cache swung 469 -> 588 MB)
        UNRECLAIMABLE    +98.8 MB   -> +1167 MB/h
        pid 98 rss       +53.9 MB
        pid 97 rss       +44.2 MB   (sum 98.1 ~= unreclaimable 98.8: consistent)

* **Standing pressure is `1103.7 MB` unreclaimable of 2048 = 54%**, not the 86%
  I reported. The difference is ~570 MB of file cache the kernel evicts under
  pressure before it OOMs anything.
* **GROWTH IS BURSTY, so no rate from a short window is trustworthy — including
  the ones above.** Both workers rose ~98 MB between 16:17:43 and 16:19:25 and
  were then FLAT to the decimal (`595.3` / `509.4`) for the remaining 3.5 min.
  Extrapolating `+1167 MB/h` across a window containing one burst is exactly the
  error that produced the "~20 minutes to OOM" claim.
* This is the standing `memory.current is page cache` rule, which I had recorded
  and did not apply: **split anon from file before calling anything pressure.**

### `[web-oom-leak]` UPDATE 16 — **bursts are ORDINARY TRAFFIC, and the "both workers" observation that started the lane was a SAMPLING ARTIFACT**, 2026-09-05T22:2xZ `[session b2b5b45b]`

* **7 settled bursts at 10 s cadence, 0 restarts inside the window:**
  `0/7 hit both workers`; sizes `17.6-41.8 MB` (mean `28.0`); gaps
  `3.3, 0.2, 1.6, 4.0, 0.2, 3.4 min`, spread/mean `1.79` against a periodicity
  bar of `<=0.35`. **Not simultaneous, not periodic — demand-driven request
  traffic on one worker at a time.** The scheduled-job / fan-out hypothesis is
  FALSIFIED.
* **THE LANE'S FOUNDING OBSERVATION DOES NOT SURVIVE.** It was opened on "both
  workers rose ~98 MB in ~100 s — one request cannot do that", taken from
  **50-SECOND sampling** (pid 98 `+53.9`, pid 97 `+44.2` over 5.1 min). At 50 s
  resolution *"one worker then the other"* is INDISTINGUISHABLE from *"both at
  once"*. At 10 s resolution it resolves into single-worker bursts, 7 for 7.
  **A conclusion drawn at a resolution coarser than the phenomenon.**
* **A FIRST RUN WAS DISCARDED ENTIRELY.** A peer deployed web at
  `16:29:52-16:32:58` and the detector had no restart guard, so it reported
  warm-up as bursts — including `+570 MB` and `+284 MB`. Pids are REUSED across a
  restart (97 and 98 both times), so the pid set looked continuous. Rebuilt with
  restart inference (RSS drop or a run of failed fetches) and a 10-minute settle
  window; the rerun excluded 3 warm-up bursts explicitly rather than silently.
* Consistent with the rest of `#632`: ~28 MB increments match the 8-64MB
  anonymous mappings already identified, and none of it is reachable from Python.
* Weak signals, recorded as such: pid 98 took **6 of 7** bursts (lopsided for
  round-robin, but n=7), and ONE burst coincided with a 98 MB child process
  (`272:pro`, the only child all window) — an anecdote, not a mechanism.

### `[web-oom-leak]` UPDATE 17 — intelligence response cache **BOUNDED and VERIFIED**: `22.503 -> ~13.1 MB` (-42%), 2026-09-06T02:3xZ `[session b2b5b45b]`

* `_COMBINED_INTELLIGENCE_RESPONSE_CACHE` now carries a **row budget** beside the
  entry cap, **loop eviction** (the old code popped exactly ONE entry per insert,
  so a cache over budget by more than one never caught up), and a **one-entry
  floor** so an oversized slate cannot turn the cache into a permanent miss.
  Deployed `814fda97`.
* **Measured: `~13.1 MB` vs a `22.503 MB` control taken on the old code minutes
  before the deploy — 58%, a 42% reduction, flat over 22.9 min (largest climb
  `+0.477 MB`), both workers agreeing.**
* **THE BOOT CONFOUND IS RULED OUT BY THE SAME WINDOW:** census total recovered
  to `73.66`/`67.89 MB` against a `77.38`/`69.97` control (~95%) while the cache
  stayed at 58%. The process matured; the cache did not. No cross-epoch
  comparison was needed.
* **The control had to be re-taken.** The lane quoted `37.50 MB` from hours
  earlier on a bigger slate; the live value was `22.503 MB`. Against the stale
  number, doing nothing would have passed.
* Row count was chosen over byte-sizing on MEASUREMENT: an accurate deep walk
  costs `228 ms` per insert; a truncated walk reported `11.31 MB as 1.44 MB`;
  `json.dumps` costs `70-174 ms` and allocates a `9.44 MB` transient string.
* **NOT AN OOM FIX** — `#632`'s bytes are not Python objects (28.3% of anon,
  0.3% of the growth).
* **NEXT, and NOT shipped:** `slice_intelligence_board_state_for_request` builds
  `top_opportunities` and `recommendations` as two INDEPENDENT deep copies of the
  same rows. Every use is a reassignment, never an in-place mutation, so sharing
  the row dicts would roughly halve that term. Separate change, separate risk.

### `[web-oom-leak]` UPDATE 18 — **FOUND: ~200 MB per worker is FREED-BUT-RETAINED in glibc's arena**, 2026-09-06T15:4xZ `[session b2b5b45b]`

* **`mallinfo2` on both live workers, 16 samples after an 8-minute settle:**
  arena `269.4`/`275.5 MB`, **in use only `72.8`/`72.1 MB`**, **free-but-retained
  `196.6`/`203.4 MB` (72.9% / 73.7% of what glibc holds)**. Both workers agree to
  within 1%.
* **This is the first mechanism `#632` has identified that admits a FIX.** The
  memory is not lost — it is freed, and glibc is holding it rather than returning
  it. `malloc_trim()` is the mechanism that hands it back; `releasable_top_mb`
  alone was `41.6 MB`.
* **NOT the call `#435` tried.** That was `malloc_info` (per-arena XML, 13.9%
  coverage). `mallinfo2` is a different function.
* **COVERAGE CAVEAT — 61% IS A FLOOR:** `mallinfo2` reports the MAIN ARENA ONLY,
  and web runs `GUNICORN_THREADS=4`, so per-thread secondary arenas (created via
  `mmap`) are excluded. This RECONCILES what looked like a contradiction: smaps
  `by_kind` gave `anon_mmap 370.0` vs `heap 81.2 MB`, while `mallinfo2` gives
  `arena 275.5` vs `mmapped 0.387 MB` — different arenas, not different truths.
* Consistent with everything else measured: not Python objects (28.3%), not
  returned by freeing, grows with request traffic, lives in large anon regions.
* **NEXT: measure `malloc_trim()` before/after.** Not called yet — it mutates
  allocator state and takes the malloc lock across arenas.

### `[web-oom-leak]` UPDATE 19 — **`malloc_trim` returns ~50 MB/worker in ~14 ms; the first intervention that gives memory back**, 2026-09-06T16:1xZ `[session b2b5b45b]`

* **Measured on both live workers after a 12-min settle, POST once each:**
  pid 97 `354.2 -> 296.1 MB` (**-58.1**) in `14.2 ms`; pid 98 `339.8 -> 292.6`
  (**-47.3**) in `4.1 ms`. glibc returned `1` on every call and `in_use` did not
  move, so the drop is attributable to the trim.
* **~105 MB across the container**, for ~14 ms of malloc-lock hold.
* **IT DOES NOT RECOVER THE FULL ~200 MB.** pid 97 held `144.3 MB` free and gave
  back `30.0`. The remainder is FRAGMENTED — free chunks interleaved with live
  ones, so whole pages cannot be released. **Trim recovers the releasable
  fraction, not the free total.**
* **The anon drop EXCEEDS the main-arena drop** (`-58.1` vs `-31.3`), which
  corroborates the `mallinfo2` coverage caveat: that call sees the MAIN ARENA
  only, `malloc_trim` iterates ALL arenas, so ~27 MB came from per-thread arenas
  the measurement cannot see. The two instruments disagree exactly as their
  documented scopes predict.
* **Repeat calls return ~0** (`-0.4`, `-0.2`, `+0.0 MB`, sub-ms) — trim is
  idempotent until free space re-accumulates.
* **STILL NOT A FIX.** This is a manual call. Automating it needs a cadence, a
  trigger, and a cost measurement under concurrent load rather than under a probe.

### `[web-oom-leak]` UPDATE 20 — **automatic `malloc_trim` is LIVE and VERIFIED: 1,481 MB returned in 34 min**, 2026-09-06T17:0xZ `[session b2b5b45b]`

* `SYNDICATE_MALLOC_TRIM_AUTO=1` on web, code `f6af42cf`, gated at a 300 s
  interval and a 64 MB free-arena threshold, riding the existing
  `teardown_request` hook (no new thread).
* **12 trims / 33.9 min across both workers, ALL with glibc returning 1 and
  `in_use` unmoved. Mean `-123.5 MB` per trim, total `1,481.4 MB`.** Container
  unreclaimable fell in 12 separate intervals — an independent source agreeing
  with the log lines.
* **NET STILL RISING: `676.6 -> 879.8 MB` (+203.2) in the same window**, so gross
  growth was ~1,685 MB (~2,982 MB/h). **Without the trims the container would
  have reached ~2,361 MB against a 2,048 limit inside 34 minutes** — not a
  controlled proof, but the first `#632` intervention whose size is comparable to
  the problem.
* **NOT A FIX — a faster drain on a running tap.** The growth mechanism is
  untouched; only the freed-but-retained portion is reclaimed.
* **COST: 3 of 12 trims held the malloc lock 62-75 ms** (median 12.3). One
  request per interval per worker pays it. The median understates the tail.
* Re-accumulation is fast: ~100 MB per five minutes per worker against ~120
  returned.

### `[web-oom-leak]` UPDATE 21 — **RETRACTION: the auto-trim headline was my own artifact; flag OFF**, 2026-09-06T18:0xZ `[session b2b5b45b]`

* **RETRACTED from UPDATE 20:** *"without the trims the container would have
  reached ~2,361 MB"*. That assumed the `1,481 MB` returned would otherwise have
  ACCUMULATED; it would not — it was free arena space being REUSED in place.
* **Matched short windows (>=50 publish calls each):** pre-trim `n=62`, median
  **`0.000 MB/call`** (50 of 62 read exactly zero); post-trim `n=28`, median
  **`0.893 MB/call`**. Boundary `16:24:41`, the instant the flag went live.
* **MECHANISM:** `malloc_trim` returns pages via `MADV_DONTNEED`;
  `smaps_rollup`'s `Anonymous` counts RESIDENT pages, so the next request
  re-faults them and the per-request delta records that as fresh allocation. The
  trim turns *reuse-in-place* into *return-then-refault*.
* **The "~3 GB/h allocation rate" is therefore substantially the trim's own
  doing.** Pre-trim, `/api/ops/artifacts/publish` — ~1,300 calls per window, the
  busiest route — cost nothing measurable in anon.
* **SURVIVES:** the trim does return memory (12 trims, glibc returning 1,
  `in_use` unmoved, 12 independent container falls). **DOES NOT SURVIVE:** that
  the memory would otherwise have accumulated.
* **NET EFFECT UNDETERMINED** — lowers RSS, adds page-fault churn, nothing
  measured says which wins. Needs a controlled on/off comparison over matched
  windows. **Flag set to `0`** rather than run a production change on an
  invalidated inference. The code stays, inert.

### `[web-oom-leak]` UPDATE 22 — the trim A/B is **DEFERRED to a quiet window, with a runnable harness committed**, 2026-09-06T18:3xZ `[session b2b5b45b]`

* **The question left open:** is automatic `malloc_trim` net-positive? It returns
  memory (12 trims, glibc confirming, two independent sources) AND causes the
  returned pages to be re-faulted. Nothing measured says which wins.
* **FIRST ATTEMPT DIED AFTER 3.4 CLEAN MINUTES.** A peer deployed web at
  `18:22:36`, mid-window. A restart resets every memory metric, so the arm was
  discarded rather than salvaged.
* **THIS IS THE ENVIRONMENT, NOT BAD LUCK: web took a deploy roughly every 20-30
  minutes** through the working day (`15:22`, `15:53`, `16:21`, `18:04`,
  `18:22`). The experiment needs **~84 uninterrupted minutes** — a 12-minute
  settle plus a 30-minute window, twice.
* **DEFERRED by user decision** rather than rushed. Shortening the settle would
  produce a FALSE NEGATIVE — a fresh worker has not accumulated the free arena
  space the trim returns — and that is the failure mode that reads as an honest
  disappointing result.
* **`scripts/malloc_trim_ab.py` is committed and runnable.** `arm OFF <ts>`,
  `arm ON <ts>`, `compare`. It detects a mid-window restart and says DISCARD; it
  refuses to call a winner if the arms' request volumes differ by >25%; and its
  decision metric is CONTAINER UNRECLAIMABLE, never the trim's own reported
  savings — those are the numbers that produced the retracted claim.
* **Current production state: flag `SYNDICATE_MALLOC_TRIM_AUTO=0`, code live and
  inert** (`4f62d937`). Nothing is degraded; pressure ~55%.

### `[web-oom-leak]` UPDATE 23 — **THE PROGRAM'S LIVE DATA IS NOT GROWING. `in_use` is flat-to-FALLING while anon climbs.**, 2026-09-06T20:2xZ `[session b2b5b45b]`

* **Clean 31-minute window, both workers, trim OFF, no restart, under a HELD
  deploy claim** (three earlier windows had been killed by peer deploys):

        pid 97  n=32  arena +7.2   IN USE -10.3 (62.4..81.8)   free +17.6   anon +42.4
        pid 98  n=44  arena +8.3   IN USE  -2.9 (67.7..73.3)   free +11.2   anon +26.9

* **THE HEADLINE, robust across every reading taken today: `in_use` sits at
  62-82 MB while process anon is 536-677 MB. Live program data is UNDER 12% of
  the process's memory, and over this window it FELL while anon rose.** Whatever
  the other 88% is, the program is not using it.
* **The growth is NOT in the main arena.** Anon rose `+42.4`/`+26.9 MB` while the
  main arena moved `+7.2`/`+8.3` — so ~80% of it landed where `mallinfo2` cannot
  look. That call reports the MAIN ARENA ONLY, and web runs
  `GUNICORN_THREADS=4`, so per-thread SECONDARY arenas exist and are created via
  `mmap`.
* **The lane's own test could not fire** and said so: with the main arena flat
  there was nothing to attribute, so the formal verdict is *NOT a result*. The
  hypothesis was about main-arena fragmentation and this window shows the main
  arena is not where the action is.
* **Two earlier hand-read segments (17% and 5% of arena growth becoming live
  data) describe the BOOT PHASE**, when the main arena fills to ~330-390 MB with
  ~80% free. They are not contradicted; they are a different phase. Steady state
  plateaus the main arena and pushes growth to the secondary ones.
* **NEXT, and it is a specific instrument:** `malloc_info`'s per-arena XML is the
  only thing that can see secondary arenas. `#435` dismissed it at 13.9%
  coverage, but that was measuring a different question — coverage of TOTAL anon,
  not the per-arena split. It should be re-read with this question in hand.

### `[web-oom-leak]` UPDATE 24 — **A DUPLICATE DEFINITION HAD SILENTLY KILLED `#285`'s PROOF LINE**, plus the per-arena instrument is built (and INERT), 2026-09-06T21:1xZ `[session b2b5b45b]`

* **THE DEFECT, and it is live code.** `_MALLOC_TRIM_STATE` and
  `_resolve_malloc_trim` were each defined **TWICE** at module scope in
  `syndicate/features/shared/memory_observability.py` — once by `#285`
  (~line 2397) and again ~1,900 lines later, beside the `mallinfo2` work **this
  session added earlier the same day**. Python keeps the LAST binding, so
  `#285`'s resolver was dead code. Fixed in `67af1276`.
* **Nothing failed loudly, which is why it survived.** `malloc_trim` still bound
  and still trimmed. What the duplicate removed was the EVIDENCE:
  * **`MALLOC_TRIM_INIT`** — the one-time line `#285` added *precisely because*
    the binding cannot be exercised on any dev machine here, so a production log
    line is its only proof. Grepping for it after a deploy returned nothing,
    which reads as *"the binding failed"* and actually meant *"the emitter is
    gone"*. This is `[feedback_absent_signal_is_about_the_emitter]` again, and
    this time I caused it.
  * **commit `daed5d92`**, *"hold the CDLL, not just the function pointer taken
    off it"* — the duplicate kept only the pointer, re-opening a FIXED lifetime
    bug.
  * the `libc.so.6` → `find_library("c")` → `None` fallback chain, narrowed to a
    single `CDLL(None)`.
* **Blast radius is real, not theoretical:** `release_freed_memory_to_os()` is
  called from **five sites** in `pipeline/intelligence_state.py` (layer2 refresh
  guards, candidate pool, overview headroom). Also, `malloc_trim_now()` was
  reading a `why` key that the surviving state dict does not have, so it reported
  *"malloc_trim not found in libc"* **whatever the real reason was**.
* **How it was found:** `tests/test_malloc_trim_release.py` had a RED test
  asserting `MALLOC_TRIM_INIT` is emitted. It was failing, it was in the area I
  was working, and it was telling the truth. `[feedback_documented_caveat_is_a_scheduled_defect]`.
* **A repo-wide AST sweep found TWO MORE instances**, both outside this lane and
  both FREE at the time: `syndicate/features/nba/live_lens.py`
  (`build_live_lens_api_payload`, lines 747 and 807 — a LIVE API payload
  builder) and `syndicate/features/nhl/cards.py` (`_sim_hist_rows`, 521 and 539).
  Flagged, not fixed here. A test now pins the no-duplicate invariant for
  `memory_observability.py`; a repo-wide check is the better home for it.

* **THE INSTRUMENT, built and landed but NOT YET LIVE.**
  `parse_malloc_info_arenas()` splits `malloc_info` XML **per `<heap>`**, which
  `parse_malloc_info_xml` discards by design (top-level totals only, to avoid
  double counting). Each `<heap nr=N>` IS an arena, so this is the only
  instrument that can see the secondary arenas `mallinfo2` does not report.
* **It does NOT inherit my own assumption.** I have been asserting `mallinfo2`
  is main-arena-only. `man mallinfo2` says so under BUGS; glibc's
  `__libc_mallinfo2` walks the arena ring; neither runs on any machine here, and
  **the entire "80% is invisible" claim from UPDATE 23 rests on which is right.**
  So `mallinfo2.arena` is compared against BOTH heap 0 and the top-level total
  and the scope is decided FROM THE DATA — including `indistinguishable` when
  there is one arena and the comparison has no power to say anything.
  **If it comes back `all_arenas`, UPDATE 23's premise is falsified** and the
  growth is outside glibc entirely.
* Every derived number is paired with its residual: per-heap sum vs glibc's own
  top-level total, and a FAILED reconciliation blocks every downstream verdict
  rather than yielding a confident split off a misread tree. Coverage against
  cgroup anon gates it too — below 50% the arenas are not where the memory lives.
* **INERT until deployed AND enabled.** `SYNDICATE_MALLOC_ARENA_DETAIL` defaults
  **OFF**, and web runs a deploy branch with `autoDeploy = no`, so landing on
  `main` ships nothing. It is flag-gated and throttled because
  `get_all_process_memory_snapshot()` is also reached from
  `log_all_process_memory()` at worker STAGE CHECKPOINTS — unconditional libc
  work there is the `#241` shape. The call reports its own `duration_ms`, and a
  cached reading is stamped `age_s`, so neither the cost nor the freshness has to
  be assumed.
* Reachability note: it rides the EXISTING `/api/ops/memory` rather than a route
  of its own, because `syndicate/blueprints/ops.py` is held by
  `ncaaf-live-resim-wire`. 36 new tests; 89 pass across the memory-instrument
  files, including the previously-red `MALLOC_TRIM_INIT` test.

### `[web-oom-leak]` UPDATE 25 — **THE ARENA HAS A CEILING (~390 MB in ~30 min). `mallinfo2` WAS NEVER BLIND, so UPDATE 23's headline is CORRECTED.**, 2026-09-06T22:2xZ `[session b2b5b45b]`

* **`mallinfo2` READS EVERY ARENA. `82 of 82` readings returned
  `mallinfo2_scope == "all_arenas"`**, matching the all-arena total to `0.0 MB`
  and missing the main arena by `70.1 MB` with 15-20 arenas live — so the
  comparison had power, unlike the single-arena case the instrument refuses.
  `man mallinfo2`'s BUGS note ("only the main memory allocation area") does NOT
  describe this glibc; `__libc_mallinfo2` walks the arena ring.
* **CORRECTION TO `UPDATE 23`.** I wrote that ~80% of the growth "landed where
  `mallinfo2` cannot look". **Wrong — it was never blind.** Re-reading the SAME
  numbers with correct semantics says something stronger: of `+69.3 MB` anon
  growth, glibc's whole allocator took `+15.5 MB`, so **77.6% was outside the
  allocator**, not hiding in secondary arenas.
* **ALSO CORRECTED: the "58-72% coverage" I quoted was MISPAIRED** — it crossed
  one worker's arena with the other's anon. Paired correctly the mature figure is
  **58.6-61.3%**.
* **THE RAMP IS THE OPPOSITE OF THE PLATEAU, and that is the finding.** A 33-min
  window on a freshly restarted process, both workers, no restart, trim OFF:

        pid 97  n=37  anon +266.9  glibc ALL +211.7 (79%)  main +20.7  secondary +190.9
        pid 98  n=37  anon +213.9  glibc ALL +194.5 (91%)  main +34.9  secondary +159.8

  In the ramp the allocator takes **79-91%** of the growth and **~85% of THAT
  goes to SECONDARY arenas** (arena count 15 -> 20). In the mature phase it takes
  **22.4%**. Both are true; they are consecutive phases.
* **THE CEILING IS REPRODUCIBLE ACROSS THREE INDEPENDENT WINDOWS** on pid 97:
  `387.7` at the end of the ramp, `388.2 -> 395.4` through UPDATE 23's window,
  `390.1` on a later spot read. **The arena fills to ~390 MB in ~30 minutes and
  then stops.** Everything after that is growth the allocator does not take.
* **THE RESIDUAL IS NOT `malloc` AT ALL.** `hblkhd` — glibc's large-allocation
  mmap path — is **0.4 MB in 3 regions**. So "outside the arena" is not "large
  chunks mmapped by malloc"; it is outside `malloc` entirely. `205.1 MB` (34.4%)
  on pid 97, `142.1 MB` (27.6%) on pid 98, and it grows steadily in BOTH phases
  (`+55.2` over the ramp, `+35.2` over UPDATE 23's mature window).
* **AND THE ARENA IS MOSTLY NOT LIVE DATA.** At ~50 min: `in_use` `51.8`/`54.0 MB`
  against `338.3`/`319.2 MB` free-in-arena. **87% of what glibc holds is free
  chunks it has not returned** — ~660 MB across two workers, against a 2,048 MB
  limit. That is the standing cost `malloc_trim` addresses and the A/B
  (`scripts/malloc_trim_ab.py`) is still owed on.
* **A DEFECT IN MY OWN INSTRUMENT, caught in its first window and BEFORE any
  conclusion was drawn from it.** **Pids 97 and 98 both reported
  `process_anon_mb` = `701.6`** — identical, which is impossible for a
  per-process figure, because I had paired per-process arena numbers with the
  CONTAINER cgroup's anon. Coverage was
  understated by roughly the worker count (`15.9-32.3%` measured, `47.8-56.1%`
  true). `_process_anon_mb()` exists in the same file for exactly this and its
  docstring records the same substitution producing a 61-150% attributed share on
  2026-09-03. Fixed in both callers, with the source now REPORTED in
  `anon_source` — a fallback indistinguishable from the real thing is how it
  survived a whole window.
* **NEXT, and it is now a narrow question:** name the ~150-205 MB of per-worker
  anon that is not `malloc`. CPython's pymalloc arenas are `mmap`ped directly and
  would land exactly here, as would thread stacks (`GUNICORN_THREADS=4`) and
  C-extension buffers. `#632`'s earlier heap census put Python objects at 28.3%
  of anon, which is the right order of magnitude — that census should be re-read
  against THIS denominator rather than repeated.

### `[web-oom-leak]` UPDATE 26 — **THE NON-MALLOC ANON IS PYMALLOC (162-165 MB/worker) AND IT IS A CONSTANT, NOT A LEAK. Growth is INTERMITTENT.**, 2026-09-07T00:0xZ `[session b2b5b45b]`

* **THE PARTITION CLOSES.** `anon = glibc_malloc + pymalloc_arenas +
  so_private_dirty + main_thread_stack`. **50 of 50** mature readings and 49 of 50
  ramp readings scored `explained`, residuals `-0.8` to `-8.2 MB` on a 105-583 MB
  process, and `smaps`'s own total agrees with `smaps_rollup` to `0.0 MB`. This is
  a complete account of a web worker's anonymous memory, not a best guess.
* **THE `205 MB` HOLE FROM `UPDATE 25` IS NAMED: CPython's pymalloc arenas,
  162-165 MB per worker.** CPython `mmap`s them, so glibc never allocated them
  and `mallinfo2` was structurally incapable of seeing them. The other two
  non-`malloc` terms are real and negligible: `.so` private-dirty **exactly
  `4.4 MB`** and the main stack `0.1 MB`, both unmoved across 66 minutes.
* **AND IT IS A CONSTANT.** Over 31 mature minutes `pymalloc_arenas` did not move
  ONE megabyte on either worker — `162.0 -> 162.0`, `165.0 -> 165.0`. **I had
  written that pymalloc "becomes the growth driver" once the arena plateaus; that
  was speculation stated as a finding and the measurement refutes it.** In the
  ramp it takes 7.5-14.2% of growth; at maturity, 0.0%.
* **THE MATURE WINDOW DID NOT REPRODUCE THE GROWTH.** Anon moved `-5.8` and
  `+15.3 MB` in 31 min, against `UPDATE 23`'s `+42.4`/`+26.9` over the same span.
  On pid 98 the little growth there was went **98.7% to glibc**. So the episode
  UPDATE 23 caught is NOT attributed by this window — it did not occur during it.
  **Growth on web is INTERMITTENT**, and one stable window is not evidence it
  stopped (`[feedback_absence_in_a_window_is_not_absence]`).
* **WHAT THIS CHANGES ABOUT `#632`.** The steady-state composition is now fully
  known and contains no mystery: ~400 MB glibc arena (of which only ~52 MB is
  live data — 87% free chunks retained), ~165 MB pymalloc, ~4.5 MB everything
  else. Nothing is unaccounted for. **The OOM question is therefore no longer
  "what is the memory" but "what causes the intermittent growth episodes", and
  the single largest standing cost is the ~340 MB/worker of free-but-retained
  arena that `malloc_trim` addresses** — `scripts/malloc_trim_ab.py`, still owed.
* **INSTRUMENT COST, measured not assumed:** partition median `47-96 ms`, **max
  `1,700.6 ms`** — `/proc/self/smaps` is O(regions) and the throttle bounds
  frequency, not duration. `SYNDICATE_ANON_PARTITION` is back **OFF** (deployed
  `cc598278`). `SYNDICATE_MALLOC_ARENA_DETAIL` stays ON at `0.9-1.0 ms` median.
* **A CALIBRATION BUG OF MY OWN, caught in production within minutes.** The
  partition shipped with ONE tolerance serving two questions and false-tripped
  `terms_overlap` at residual `-4.3 MB` on a `209 MB` process. The overlap bar is
  now set against the FAULT it exists to catch — a whole pymalloc term double
  counted, ~100 MB — not against zero: 5%/8 MB, an order of magnitude above the
  slack and below the fault. The read-agreement check keeps the tight 2%/2 MB bar
  because it compares two reads of the SAME quantity.

### `[web-oom-leak]` UPDATE 27 — **SEVEN EPISODES CAUGHT. BOTH ALLOCATORS GROW, ALTERNATING — and PYMALLOC IS NOT THE CONSTANT `UPDATE 26` CALLED IT.**, 2026-09-07T02:1xZ `[session b2b5b45b]`

* **The in-process detector caught 7 episodes in 55 minutes**, both workers,
  every one `attributed` with the unattributed term between `-2.0%` and `+24.9%`
  — so the cheap capture (allocators only, no `smaps`) was sufficient throughout,
  which was the assumption it was built to expose if wrong.
* **THE LANE'S HYPOTHESIS IS REFUTED.** It predicted glibc. **4 episodes are
  glibc-dominant, 3 are PYMALLOC-dominant at 74-98.4%.** They alternate:

        96 @  955s  +19.9 MB  glibc 75.1%      97 @ 1121s  +19.1 MB  pymalloc 89.1%
        97 @ 1517s  +17.6 MB  pymalloc 74.0%   96 @ 2013s  +33.8 MB  glibc 98.4%
        96 @ 2080s  +18.3 MB  pymalloc 98.4%   97 @ 2511s  +55.4 MB  glibc 90.8%
        96 @ 3032s  +49.3 MB  glibc 102.0%

* **CORRECTION TO `UPDATE 26`, which called pymalloc "a large CONSTANT, not a
  leak".** It grows — in DISCRETE JUMPS of `+6.0`, `+13.0`, `+17.0`, `+18.0 MB`,
  all near-integer and consistent with 1 MB arena granularity. The 31-minute
  mature window that measured `+0.0 MB` on both workers did not span a jump. That
  is the difference between a continuous instrument and a sampled one, and it is
  exactly `[feedback_absence_in_a_window_is_not_absence]` — which UPDATE 26 cited
  about anon and then failed to apply to its own pymalloc reading.
* **THE RATE IS AN OOM TRAJECTORY.** Sustained post-warm-up: **3.68 MB/min** on
  pid 96 and **3.98 MB/min** on pid 97, `2.6-2.9x` `UPDATE 23`'s 1.4 MB/min. Two
  workers is **~7.4 MB/min of container growth** against a 2,048 MB limit.
* **THE ROUTE MIX IS NOT AN ATTRIBUTION, and the arithmetic says so.**
  `/api/ops/artifacts/publish` appears in all seven, but growth does NOT scale
  with it: **224 requests / 101 publishes → `+17.6 MB`**, while **36 requests / 9
  publishes → `+55.4 MB`**. This is the same route whose attribution I RETRACTED
  earlier this session as trim-inflated (pre-trim it cost ~0 MB in anon terms),
  and a co-occurrence is not grounds to re-adopt it.
* **THE DETECTOR ITSELF NEEDED A WARM-UP, found in production.** Its first run
  fired 18.4 s after boot on `+230.3 MB at 750 MB/min` with `/` and `/healthz`
  the only routes — the boot ramp, three orders of magnitude faster than the
  phenomenon. That cost the episode slot and, worse, polluted
  `max_anon_rise_seen_mb`, the one field that separates "the process was flat"
  from "the trigger is mis-sized". Warm-up now 900 s; process age is derived
  LAZILY PER PID because gunicorn forks after import (the trap that shipped
  `proc_token` inert earlier in `#632`).
* **NEXT, and it is now two separate questions:** (a) what triggers a pymalloc
  arena jump — 1 MB granularity means it is a real allocation burst, not
  fragmentation; (b) whether glibc's episodes are the arena re-expanding above
  the ~390-400 MB ceiling, which `malloc_trim` would address and
  `scripts/malloc_trim_ab.py` is still owed on.

### `[web-oom-leak]` UPDATE 28 — **THE PYMALLOC GROWTH IS PER-REQUEST, NOT PER-ROUTE. `/healthz` retains as fast as the artifact endpoints.**, 2026-09-07T03:0xZ `[session b2b5b45b]`

* **Per-route RETAINED pymalloc blocks, ~1,340 solo requests per worker,
  gen2-free windows only.** Among routes with a real sample (`n>=80`) the
  per-request retention spans **18.6-32.8 blocks** (pid 97) and **21.2-37.9**
  (pid 98) — a **1.8x spread, IDENTICAL on both workers**. A route-specific leak
  would be orders of magnitude apart.
* **THE LANE'S FALSIFICATION CONDITION FIRED, as written:** *"retained blocks
  spread evenly across routes"*. They do. **No route drives the arena jumps; the
  request COUNT does.**
* **`/healthz` RETAINS 26.6-28.0 BLOCKS PER REQUEST** — a trivial health check,
  and the cleanest control available. It leaks at the same rate as
  `/api/ops/artifacts/stream` and `export`. Whatever retains is in the SHARED
  request path or the interpreter, not in any handler.
* **`/api/ops/artifacts/publish` leads on TOTAL (38-41%) purely because it is
  served most** (762 and 680 of ~1,340 solo requests) — and it has the **LOWEST
  per-request rate of the four**. Ranking by total would have re-adopted an
  attribution I already retracted once today as trim-inflated. That is three
  separate times this route has looked guilty by co-occurrence and been wrong.
* **THE RECONCILIATION PASSES, which is what licenses the conclusion.** The solo
  sample covers 78-81% of requests, so scaled up it is ~42.7k and ~48.3k blocks
  against the **9.0 and 13.0 MB of arena jumps** caught on those same pids —
  **221 and 282 bytes per retained block**, against ~50-200 B for a small object
  with pymalloc overhead. Same order. The blocks measured DO account for the
  arenas, so the growth is not hiding somewhere the sample never saw.
* **CAVEAT I CANNOT CLOSE FROM THIS DATA:** this session added per-request
  instrumentation, and uniform per-request retention is exactly what that would
  look like. The phenomenon PREDATES it — `UPDATE 23` measured the growth hours
  before any of this code existed — so the leak is not mine; but I cannot say
  from these numbers how much of the ~25 blocks/request the instruments
  themselves contribute. Measuring that needs the profile toggled OFF and the
  arena rate re-read.
* **NEXT:** the target is now a SHARED per-request retainer of ~20-38 small
  objects, not a route. Candidates in order of testability: this session's own
  instrumentation (toggle it off and re-measure the arena rate — cheapest and
  also closes the caveat above), Flask/Werkzeug per-request caches, and logging.
  A route allowlist is no longer the right tool; a before/after on the shared
  path is.

### `[web-oom-leak]` UPDATE 29 — **THE LEAK IS NOT MOSTLY MINE. With every per-request instrument OFF, anon still grows 1.01-2.39 MB/min.**, 2026-09-07T04:5xZ `[session b2b5b45b]`

* **The A/B that `UPDATE 28` owed.** `SYNDICATE_REQUEST_MEMORY_PROFILE` ON vs OFF,
  two sequential arms, each measured over the SAME process-age window
  (`900-2400s`) so both sit in the same phase of the lifecycle. The measuring
  instrument — the growth detector — stayed ON in both arms, because letting an
  intervention supply its own measurement is what produced this session's
  retracted counterfactual. Request-volume skew **15%**, inside the 25% gate.
* **THE HEADLINE, and it is robust:** with the profile OFF — no per-request anon
  reads, no block counting — anon still grows at **1.01 and 2.39 MB/min**. The
  per-request retention `UPDATE 28` found is **REAL and mostly not my
  instrumentation's**.
* **THE MAGNITUDE IS NOT DETERMINED, and the mean hides why:**

        ON   pid 80  2.91   pid 79  2.39    mean 2.65 MB/min
        OFF  pid 79  2.39   pid 78  1.01    mean 1.70 MB/min

  The harness reported *"PARTIAL: 36% of the anon rate"*. But **the ranges
  TOUCH** — one OFF worker ran at exactly the rate of an ON worker — and the
  whole gap rests on OFF pid 78, whose anon **FELL** (`442.1 -> 417.3`) in its
  tail. With n=2 workers per arm, 36% is a DIRECTION, not a magnitude. No OFF
  worker exceeded any ON worker, so a contribution is plausible; its size is not
  measured. **This overlap check was NOT pre-registered** — I added it after
  seeing the arms, and it is stated as a limitation rather than folded into the
  estimate.
* **pymalloc: NO VERDICT, as pre-registered.** ON `0.362 -> ` OFF `0.000 MB/min`,
  but **1 of 2 workers jumped ON and 0 of 2 OFF** — a difference of ONE discrete
  1 MB-arena event. That gate was written after seeing the ON arm and BEFORE
  collecting OFF, precisely because a `0.000` OFF arm was always a plausible coin
  flip and would otherwise have read as *"the profile was the cause"*.
* **WHAT THIS SETTLES FOR `UPDATE 28`.** Its `~25 blocks/request` figure carries
  some instrumentation contribution that cannot be sized from here — the profile
  IS the thing that counts blocks, so turning it off removes the measurement.
  What survives is the part that matters: the shared-path retention is real,
  route-independent, and persists with all of it off.
* **DECISION: the profile stays OFF.** Its measurement job is done, it plausibly
  costs something, and web is a 2 GB service. `SYNDICATE_GROWTH_EPISODE` stays ON
  at ~4-5 ms per 15 s interval.
* **NEXT:** the target is unchanged and now cleaner — a shared per-request
  retainer that is NOT this session's code. Flask/Werkzeug per-request caches and
  logging are the candidates. If a future arm wants a real magnitude for the
  instrumentation's own share, it needs more workers or repeated windows; two
  workers and one window each cannot separate a 36% effect from worker variance.

### `[web-oom-leak]` UPDATE 30 — **RETRACTION: my block instrument over-counts 16x. `UPDATE 28`'s reconciliation FAILS, and Flask/Werkzeug are NOT the retainer.**, 2026-09-07T05:2xZ `[session b2b5b45b]`

* **THE DEFECT, measured locally where it can be run to ground.** The instrument
  reads `getallocatedblocks()` in `teardown_request`. That hook fires **BEFORE**
  the response object, the request context and the WSGI environ are released, so
  everything still alive at that instant is scored as RETAINED when most of it is
  about to die. Same 500 requests, two measurement points:

        measured AT teardown_request (what the instrument does):  64.7 blocks/req
        measured AFTER the request fully returns (ground truth):   4.1 blocks/req

  **A 16x over-count.** After a `gc.collect()` the true figure is **under 1
  block/request**.
* **RETRACTED from `UPDATE 28`: "~19-38 blocks retained per request".** That is
  per-request SCAFFOLDING counted at the wrong point in the lifecycle, not
  retention.
* **RETRACTED from `UPDATE 28`: "the reconciliation PASSES ... 221 and 282 bytes
  per retained block ... same order as a small object".** I called that the thing
  that *licensed the conclusion*. Corrected for the 16x, the same arithmetic
  gives **3,539 and 4,516 BYTES PER BLOCK** — and **pymalloc only handles objects
  <= 512 B, so that is impossible.** The retained blocks I measured **CANNOT**
  account for the arena growth. The reconciliation passed only because its
  numerator was inflated.
* **WHAT SURVIVES `UPDATE 28`, and it is now better explained:** *no route
  dominates*. Retention looked uniform across routes including `/healthz` because
  the instrument was largely measuring FRAMEWORK per-request objects, which are
  uniform by construction. The conclusion stands; the stated reason was wrong.
* **`UPDATE 29` IS UNAFFECTED.** That A/B compared the **anon rate**, not blocks,
  so the "leak is not my instrumentation" result does not depend on this.
* **THE QUESTION ASKED — Flask/Werkzeug caches — IS ANSWERED: NO.** Locally,
  after full request completion, `/healthz` retains `4.1` blocks/request raw and
  **under 1 after GC**, against a production-instrument reading of `26.6-28.0`.
  Toggling both my flags moved it not at all (`2.0` / `1.0` / `2.3` blocks/req).
  Per-request framework caches are not the retainer.
* **THE REFRAME, and it is the useful part.** Arena count is driven by **PEAK
  SIMULTANEOUS live blocks, not retained blocks.** A transient burst that needs
  17 MB of concurrently-live small objects forces 17 new arenas, and pymalloc
  rarely returns an arena to the OS — so a big TRANSIENT permanently grows the
  arena. My instrument measured the wrong quantity for the question it was built
  to answer.
* **NEXT:** `blocks_max` is already recorded per route and is much closer to the
  right quantity (local `/healthz` peak: 131). The hunt is for peak concurrent
  allocation, not for something that leaks. Fixing the instrument means measuring
  in WSGI middleware wrapping the full call — after `close()` — rather than in
  `teardown_request`, which is the last Flask hook but not the last thing to run.

### `[web-oom-leak]` UPDATE 31 — **STEADY-STATE RETENTION IS ZERO. The arena is driven by a PEAK, and one route peaks at 44,007 blocks in a single request.**, 2026-09-07T07:3xZ `[session b2b5b45b]`

* **The table re-read with the FIXED instrument (`8bcdef11`), as a DELTA between
  two warm snapshots** — cumulative totals are useless here: on this deploy
  `retained_blocks` read `663,143` at n=34 and `663,803` at n=239, so the first
  34 requests carried ~19,500 blocks each (caches, lazy imports) while the next
  205 averaged **3.2**. Reading the cumulative figure would have republished boot
  as a leak.

        pid 78   +794 solo requests   TOTAL RETAINED    -18 blocks  = -0.0/req
        pid 79   +722 solo requests   TOTAL RETAINED  +3,969 blocks = +5.5/req

  Local ground truth was `4.45/req`, so **the fix transfers from `test_client` to
  gunicorn**. Steady-state per-request retention is **~0**. There is no
  per-request leak.
* **`UPDATE 28` IS CONFIRMED AS AN INFLIGHT MEASUREMENT.** The renamed
  `blocks_inflight` column reads **17.1-30.7/req** here, against UPDATE 28's
  reported "18.6-37.9". Same quantity, same numbers — it was measuring
  per-request scaffolding and calling it retention. The retraction in `UPDATE 30`
  is now corroborated by the corrected instrument, not just by a local test.
* **THE RECONCILIATION FAILS, exactly as `UPDATE 30` predicted:**
  * pid 79: `7.0 MB` of arena jump against ~`5,150` retained blocks =
    **1,425 bytes per block**, and pymalloc caps at 512 B.
  * pid 78 is the cleanest case available: **`53.0 MB` of arena growth against
    NET `-18` blocks retained.** Retention cannot account for the arenas at all.
* **THE PEAK COLUMN IS THE LEAD, and it is very concentrated:**

        route                             peak blocks (78/79)   calls
        /wnba/api/live_player_boxscore       44,007 /  3,277      9 / 11
        /api/ops/memory                       3,370 /     43      5 /  8
        /api/ops/artifacts/export               761 /    114     63 / 77
        /api/ops/artifacts/publish              701 /    277    493 /428
        /healthz                                148 /    145    142 /132

  **`/wnba/api/live_player_boxscore` peaks 13-60x above every other route**, on
  9-11 calls. At 64-128 B per small object that is **2.7-5.4 MB of simultaneously
  live objects in ONE request** — and arenas are allocated to cover the peak,
  which pymalloc then rarely returns.
* **AN ARITHMETIC COINCIDENCE THAT IS A HYPOTHESIS, NOT A RESULT:** pid 78's
  `53 MB` jump would need **10-20** such requests, and that route was served
  **9** times in the window. Suggestive and the right order — but I have NOT
  shown the jump coincided with those calls, and this is the same route-shaped
  reasoning that made `/api/ops/artifacts/publish` look guilty three times and be
  wrong each time. **It needs a direct test:** correlate the episode timestamp
  against that route's calls, or call it in isolation and watch the arena.
* **NOTE the peak asymmetry between workers** — `44,007` on pid 78 vs `3,277` on
  pid 79 for the same route. Either the work is input-dependent (a big game vs a
  small one) or one call did something the others did not. That difference is
  itself measurable and worth resolving before acting.
* Profile returned to **OFF** after the reading, per `UPDATE 29`.

### `[web-oom-leak]` UPDATE 32 — **THE DIAGNOSTIC RING IS A PEAK GENERATOR: ~18,600 simultaneously-live objects per checkpoint, ~15x/min, retaining nothing.**, 2026-09-07T08:1xZ `[session b2b5b45b]`

* **Tested `/wnba/api/live_player_boxscore` in isolation** — `UPDATE 31`'s lead.
  It peaks **196x the control** locally but moved the arena **+0.0 MB**. The lead
  is NOT confirmed, and I am not calling it the cause.
* **Its SIBLING is the one that grows the arena.**
  `/wnba/api/final_player_boxscore`, order-independent, two controls flat:

        order reversed, n=20      final  +2,321.9 blocks/req   arena +16.0 MB
                                  live      +69.0 blocks/req   arena  +0.0 MB
                                  healthz    -1.4 blocks/req   arena  +0.0 MB

        4 successive batches of 20:   +347.6 -> +10,589.9 -> +17,134.0 -> +18,536.1 /req
                                      arena  +0.0 -> +38.0 -> +13.0 -> +33.0 MB

  **It ACCELERATES**, which is the signature of an O(n) cost over something that
  is itself growing.
* **`tracemalloc` names the chain, at 100% coverage** (244,637 of 243,443 blocks):

        route -> pipeline/intelligence_state.py:5958 _diag_log_all_process_memory
              -> memory_observability.py:2174 log_and_persist_process_memory
              -> memory_observability.py:2049 dump_process_memory_checkpoint
              -> refresh_state_store read_json_file -> json.loads  **+11.32 MB**

  `dump_process_memory_checkpoint` **READ-MODIFY-WRITES THE WHOLE RING**: it
  `json.loads` the entire file, appends one record, truncates to 300, re-encodes
  and writes it back — on every checkpoint.
* **AT THE DESIGNED SIZE, which is what matters for production.** Reconstructed
  the ring exactly as documented (300 records, 6 container processes) — 359 KB
  at **1,224 B/record against the docstring's 1,233**:

        json.loads        peak  +18,620 blocks SIMULTANEOUSLY LIVE
        + re-encode       peak  +18,644 blocks
        retained after            +11 blocks

  **It retains nothing and peaks enormously**, ~15 times a minute. `UPDATE 30`
  and `31` established that arena count follows PEAK simultaneous live blocks and
  that pymalloc rarely returns an arena. For scale, the production
  `blocks_inflight_max` measured 3,370 (`/api/ops/memory`) and 44,007
  (`live_player_boxscore`) — 18,600 sits squarely between them.
* **THE DIAGNOSTIC MACHINERY BUILT TO INVESTIGATE THE OOM IS A PLAUSIBLE DRIVER
  OF IT.** The ring's docstring reasons carefully about the WRITE cost ("~1.1MB
  rewritten ~15x/min on a memory-constrained worker"); the READ side, which
  materialises ~18,600 live objects each time, is not considered anywhere.
* **WHAT DOES NOT TRANSFER, stated because the local numbers are dramatic.** The
  84 MB of arena growth from 80 local calls is inflated by process count: each
  local record embeds **337 Windows processes with cmdlines** against Render's
  **~6**, roughly 50x. **The local MAGNITUDE is not a production number.** What
  transfers is the MECHANISM and the designed-size figure above.
* **STILL NOT PROVEN:** that this accounts for production's arena jumps. I have a
  mechanism, a chain and a plausible magnitude — not a production measurement.
  The direct test is to correlate a `GROWTH_EPISODE` timestamp against checkpoint
  writes, or to cut the ring's read cost and re-measure the arena rate.
* **SEPARATE DEFECT, seen in the same trace:** the route emits
  `WARNING: compute in request path (operation=wnba_has_games_for_date_espn_fetch)`
  — a live upstream fetch inside a Flask handler, which `CLAUDE.md`'s
  load-bearing rule forbids outright.

### `[web-oom-leak]` UPDATE 33 — **THE RING CUT IS WORTH 38 MB PER WORKER, MEASURED, RANGES SEPARATED.**, 2026-09-07T17:2xZ `[session b2b5b45b]`

* **A/B on the diagnostic-ring cut, both arms running the SAME runtime code**
  (toggled by `SYNDICATE_RING_KEEP_CMDLINE`, so the control did not require
  deploying a stale commit):

        arm    pids   pymalloc@600s  @1200s  @1800s
        FAT     2         209.0       209.0   209.0
        SLIM    2         170.0       170.0   171.0

* **`-38 MB` per worker at every age point, and the PER-WORKER RANGES DO NOT
  OVERLAP** (`max(SLIM) 176 < min(FAT) 198`). Volume skew **14%**, inside the
  gate. **~76 MB of a 2,048 MB container, 3.7%.**
* **The separation check was in the harness BEFORE either arm ran.** `UPDATE 29`
  had to add it afterwards, having nearly called a coin flip a result; this time
  a mean difference alone would not have been reported.
* **`UPDATE 32`'s MECHANISM IS CONFIRMED AS LOAD-BEARING, not just real.** The
  ring's read-modify-write was not merely an expensive thing that existed —
  halving its peak measurably lowered the arena. The diagnostic built to
  investigate this OOM was contributing ~38 MB per worker to it.
* **AND THE MAGNITUDE IS NOT EXPLAINED.** The cut removes 9,002 blocks per
  checkpoint (~0.86 MB at 100 B) and the arena fell **44x** that. Unverified
  candidates: `GUNICORN_THREADS=4` concurrent peaks, per-size-class arenas that
  cannot be reused across classes, and the peak recurring ~15x/min through the
  ramp. **The measurement stands; the multiplier is an open question and should
  not be quoted as understood.**
* **METHOD NOTE:** pymalloc was FLAT across the window in BOTH arms (`209.0` at
  all three FAT ages), so this compares plateau LEVELS, not ramp rates — the
  arena reaches its ceiling before age 600. The plateau is set by ramp-phase
  peaks that were not directly observed.
* limits: n=2 workers per arm, one pair, not repeated. A peer's 13-file /
  947-insertion landing between arms was checked and touches **zero** runtime
  files.

### `[web-oom-leak]` UPDATE 34 — **RETRACTION OF `UPDATE 33`: the arms were NOT comparable, and the mechanism cannot produce 38 MB.**, 2026-09-07T18:0xZ `[session b2b5b45b]`

* **I set out to explain `UPDATE 33`'s 44x multiplier and the explanation
  falsified the result instead.** Two independent checks, both against the
  measurement I had just published.
* **CHECK 1 — the mechanism is ~60x too small.** My hypothesis was pymalloc POOL
  fragmentation: pools are per-size-class and an arena frees only when every pool
  in it is free, so a peak could strand `POOL_SIZE` per straggler. **Measured
  directly out of `_debugmallocstats`** rather than argued:

        FAT   json.loads  +76 pools  1.26 MB live  ->  1.19 MB of pools
        SLIM  json.loads  +35 pools  0.66 MB live  ->  0.55 MB of pools
        the cut removes  41 pools, 634 KB live
        pool bytes / live bytes = **1.1x**, not 44x

  **Pools are nearly fully packed. There is no fragmentation amplification.** One
  checkpoint's cut saves ~`0.64 MB` of pool footprint — the mechanism can produce
  well under 1 MB, not 38. (Note this build reports **16,384-byte pools**, not the
  4,096 I first assumed; the arithmetic I nearly published was wrong twice over.)
* **CHECK 2 — the arms differed in memory the cut CANNOT TOUCH.** At age 1800 s:

        arm    pymalloc   total anon   NON-pymalloc anon
        FAT      209.0       563.2          354.2
        SLIM     171.0       491.8          320.8
        delta    -38.0       -71.4          **-33.4**

  The cut removes pymalloc-domain allocations only. It cannot change the glibc
  arena, `.so` private-dirty or thread stacks. **A 33.4 MB gap there — 47% of the
  total anon difference — proves the two arms did not see the same workload.**
* **SO `UPDATE 33`'s "38 MB per worker" IS RETRACTED.** The separated per-worker
  ranges and the 14% volume gate BOTH passed and the result was still confounded.
* **WHY THE GATE MISSED IT, and this is the transferable lesson: I gated on
  REQUEST COUNT, which is not WORK PER REQUEST.** The arms ran ~50 minutes apart;
  a lighter game slate gives the same request count with far less allocation per
  request. Every future arm on this service needs a work proxy — payload bytes,
  or a non-target memory term used as a control — not a request tally.
* **WHAT SURVIVES.** The ring cut is still a real, deterministic reduction:
  `18,644 -> 9,642` blocks and `360 -> 151 KB` per checkpoint, measured locally
  and reproducible. It removes data that is redundant by construction (`cmdline`
  is constant per pid, stored up to 300 times), so it stays. **What is withdrawn
  is its production VALUE, not its correctness.** On the pool measurement its
  true worth is ~`0.6 MB` of transient footprint per checkpoint, ~15x/min — real,
  small, and nothing like 38 MB.
* **`UPDATE 32` NEEDS THE SAME DISCOUNT.** The ring is a peak generator, and that
  measurement stands; but "plausible driver of the OOM" rested on the arena
  response now retracted. It is a contributor of ~0.6 MB per checkpoint.

### `[web-oom-leak]` UPDATE 35 — **THE RING IS INERT ON WEB. It never writes a checkpoint, so the cut could not have affected web's memory and `UPDATE 32`'s premise is wrong for web.**, 2026-09-07T18:2xZ `[session b2b5b45b]`

* **MEASURED, two ways.** `ring_cost` — the per-checkpoint accounting deployed in
  `224dc5a8` — is **ABSENT on both web workers** (pids 77 and 78) after live
  traffic, and a collector polled for ~5 minutes without ever seeing it. The env
  says why: **`SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP='false'` on
  web.** No loop, no `_diag_log_all_process_memory`, no checkpoint.
* **SO THE RING IS A REFRESH-WORKER COST, NOT A WEB COST.** `#632` is about
  WEB's OOM. **The ring cannot be a contributor to it.**
* **`UPDATE 32` IS WRONG FOR WEB.** "The diagnostic machinery built to
  investigate the OOM is a plausible driver of it" describes a code path web does
  not execute. The mechanism is real and the local measurement stands — it is
  simply about the refresh-worker.
* **AND THIS EXPLAINS `UPDATE 33` STRUCTURALLY.** That A/B toggled
  `SYNDICATE_RING_KEEP_CMDLINE` on web and read a 38 MB arena difference. **The
  treatment was INERT on web, so the difference was NECESSARILY confound.**
  `UPDATE 34` retracted it on evidence (47% of the gap in memory the cut cannot
  touch); this is the reason that evidence looked the way it did. Two independent
  routes to the same retraction.
* **WHY THE LOCAL REPRODUCTION MISLED ME.** Locally the app is not a Render web
  dyno, so `_start_background_loops()` DOES run and the route really did reach
  the checkpoint — `tracemalloc` traced it honestly. **The trace was true of my
  laptop and false of production web**, and nothing in the trace could say so.
* **THIS IS `[project_which_service_runs_the_code]`, and I had it in front of
  me.** Loop ownership is an env flag that moves with no diff. I built THREE
  experiments on web — an arena A/B, its retraction, and a per-checkpoint A/B —
  before checking whether web runs the code under test. The check that settled it
  took one request and one env read.
* **WHAT SURVIVES.** The cut is still correct and still worth having: `18,644 ->
  9,642` blocks and `360 -> 151 KB` per checkpoint, deterministic, removing data
  redundant by construction. **Its beneficiary is the REFRESH-WORKER**, where the
  loop runs and the checkpoint fires ~15x/min. It is live there by default (the
  flag was only ever set on web).
* **NEXT, if the ring is worth pursuing:** run the `ring_cost` A/B on
  **refresh-worker**, not web. The instrumentation is deployed and service-
  agnostic. And for `#632` proper, the ring is now eliminated as a web-OOM
  candidate — the field is clear again.

### `[web-oom-leak]` UPDATE 36 — **THE RING A/B IS DEFERRED: refresh-worker has NO quiet window, and waiting cannot create one.**, 2026-09-07T20:0xZ `[session b2b5b45b]`

* **MEASURED, 75 minutes of polling.** A waiter watched refresh-worker for both
  conditions — claim free AND no job in flight — and **never found a clear
  moment**. Board builds started at `18:57, 19:05, 19:10, 19:23, 19:30, 19:35,
  19:39, 19:46` (every **5-8 minutes**), interleaved with MLB sims
  (`tip_off_window`, `fingerprint_change`, `props_now_available`) and odds
  refreshes. The claim itself freed several times; a JOB was in flight every
  time.
* **WAITING CANNOT SOLVE IT, and that is the finding.** A deploy takes ~5 minutes
  to go live while builds start every 5-8. **Even catching a gap lands the
  restart inside the NEXT build**, so a tighter poll does not help. The
  experiment needs a genuinely quiet period (overnight / no games) or a
  deliberate decision to kill one board build per arm. **Same shelf and the same
  reason as `scripts/malloc_trim_ab.py`** — now confirmed on a second service.
* **DEFERRED WITH A RUNNABLE HARNESS**, not a note: `scripts/ring_cost_ab.py`
  (`plan` / `read FAT|SLIM` / `compare`). It reads via the **Render logs API**
  because refresh-worker has no HTTP server, drops lines whose `keep_cmdline`
  belongs to the other arm, **gates on ring length** (the read cost scales with
  it), and reports the SPREAD — refusing a verdict when ranges overlap even at N
  in the hundreds.
* **A MISTAKE I MADE AND UNDID.** I set `SYNDICATE_RING_KEEP_CMDLINE=1` on
  refresh-worker BEFORE checking the claim, which a peer held. An env change is
  inert until a deploy — so it would have ridden along on **their** deploy and
  silently switched their service to the fat records. Reverted to `0` within the
  minute. **Setting config on a service another session holds is the same class
  of error as deploying into their window; the flag just makes it quieter.**
* **AND THE VALUE IS LIMITED EVEN WHEN IT RUNS.** `UPDATE 35` established the
  ring is inert on web, so this measures the WORKER's efficiency. `#632` is a WEB
  OOM and the ring is already eliminated as a candidate for it. Worth doing for
  the 4 GB worker's own sake; it will not move the OOM investigation.
* **NOT held, NOT pending:** no claims held, and no env change left on any
  service (web `RING_KEEP_CMDLINE='0'`, `REQUEST_MEMORY_PROFILE='off'`,
  `GROWTH_EPISODE='1'`).

### `[web-oom-leak]` UPDATE 37 — **WEB IS NOT DYING OF MEMORY. It is dying of LATENCY: 32.5% of requests exceed the 5-second health-check budget.**, 2026-09-07T22:2xZ `[session b2b5b45b]`

* **THERE ARE NO OOM KILLS.** Across the full available Render event history
  (~800 events, back past 2026-08-26): **35 `server_failed`, and ZERO with
  `evicted=True`.** Every one reads
  `{"evicted": false, "unhealthy": "HTTP health check failed (timed out after 5
  seconds)"}`. `#632` has been framed as an OOM investigation for two days;
  **the failure mode in the events API is UNRESPONSIVENESS.**
* **AND IT PREDATES EVERYTHING I SHIPPED** — the oldest is `2026-08-26`, my first
  instrumentation deploy was `2026-09-06T21:00Z`. Not caused by this session.
  Seven today: `06:16, 13:08, 13:53, 16:08, 19:11, 20:44, 21:55`.
* **THE LATENCY IS CATASTROPHIC.** 628 requests in the 90 minutes to 22:00Z:

        p50     475 ms
        p90  13,732 ms
        p99  64,902 ms
        max 142,801 ms   (2.4 MINUTES)

        >= 5s (the health-check budget): 204 requests = **32.5%**
        >= 10s: 104      >= 15s: 54

* **THE MECHANISM IS THREAD STARVATION.** gunicorn runs `WEB_CONCURRENCY=2` x
  `GUNICORN_THREADS=4` = **8 concurrent slots**. With a third of requests holding
  a slot for 5+ seconds, the pool saturates, `/healthz` cannot get a thread
  within 5 s, and Render restarts the instance. The 21:55 window shows it
  directly: `13166`, `13828`, `16682`, `18267 ms` in the ten seconds before
  `Handling signal: term`.
* **THE ROUTES, joined to slow requests by timestamp proximity (PARTIAL — only
  ~76 of 204 slow requests fell within 2 s of an access line, so treat the counts
  as a floor, not a census):**

        /api/ops/artifacts/export      n=3   median 26,057 ms   max 87,448
        /api/intelligence/query        n=8   median  5,063 ms   max 18,291
        /api/board/game-chips          n=19  median     11 ms   max 11,599

  `game-chips` is BIMODAL — 11 ms typical, 11.6 s worst — the signature of a cache
  miss doing real work in the request path.
* **`compute in request path` IS BEING LOGGED, BY NAME.**
  `WARNING:syndicate.features.shared.request_path_guard: (operation=
  wnba_has_games_for_date_espn_fetch)` fires twice in the same ten seconds — a
  LIVE UPSTREAM ESPN FETCH inside a Flask handler. `CLAUDE.md`'s load-bearing
  rule forbids exactly this, and the guard that detects it is already wired.
* **WHY THE MEMORY WORK FOUND NOTHING, and it was not wasted.** Composition is
  fully accounted (~400 MB glibc arena of which only ~52 MB is live, ~165 MB
  pymalloc, ~4.5 MB else), there is NO per-request leak (retention `-0.0` to
  `+5.5` blocks/request), and nothing approaches the limit — container sits at
  47.7% unreclaimable. **Two days of measurement kept finding no leak because
  there is no leak.** The eliminations are sound; the question was wrong.
* **NEXT, and it is a different investigation:** cut request-path latency.
  Ordered by evidence: (1) `/api/ops/artifacts/export` at a 26 s MEDIAN — this is
  the backup workflow's own endpoint; (2) the `request_path_guard` warnings,
  which already name the offending operations; (3) `/api/intelligence/query` at
  5 s median and 1.5 MB responses. Raising `GUNICORN_THREADS` would buy headroom
  but treats the symptom.

### `[web-oom-leak]` UPDATE 38 — **BOTH SLOW ROUTES FIXED AND TESTED ON `main`.** ~~NEITHER IS LANDED AT ITS CALL SITE~~ **— SUPERSEDED ON THE LANDING QUESTION BY `UPDATE 39`: both were landed 2026-09-07 on an explicit user decision. Everything else here still stands.**, 2026-09-07T23:1xZ `[session b2b5b45b]`

`UPDATE 37` named three slow routes. Two now have a mechanism on `main` with
tests, and a verified diff waiting for the file's owner.

**`/api/ops/artifacts/export`** (26 s median, 87 s max) — the cost is the
directory WALK, not the file bodies: `?names_only=1` reads no bodies and still
timed out after 180 s. 176 patterns collapse onto 95 parents and the busiest is
named by 18 of them, so that directory is listed 18 times per sport per request.
`syndicate/features/shared/artifact_walk.py` + 12 tests, landed `b79e7eb5`.
Measured on a local mirror: **125 → 51 `scandir`, byte-identical file set.**
Handoff: `.syndicate/handoff_2026-09-07_artifacts_export_walk.md`.

**`/api/intelligence/query`** (5 s median, 18 s max) — two compounding causes,
both in the code. `_COMBINED_INTELLIGENCE_RESPONSE_CACHE` is read at
`intelligence_state.py:8599` and written at `:8861` with NOTHING between, so N
concurrent misses each start their own rebuild; and the TTL defaults to **15 s**
(`:8493`) while the rebuild costs 5–18 s, so past ~15 s the entry is stale the
moment it is written. `syndicate/features/shared/single_flight.py` + 15 threaded
tests, landed `e7519883`. Handoff + verified patch:
`.syndicate/handoff_2026-09-07_intelligence_query_singleflight.{md,patch}`.

**The A/B, driving the real function with 8 threads: 8 date-reads → 1.**
**Elapsed was UNCHANGED at ~1.00 s and that is not a latency result** — the stub
sleeps, so parallel sleeps do not contend. What collapses is WORK COUNT. The
production claim is about SLOT OCCUPANCY: each rebuild holds one of web's 8
gunicorn slots (`WEB_CONCURRENCY=2` × `GUNICORN_THREADS=4`) for 5–18 s, so one
expiry can take the whole pool and leave `/healthz` nowhere to run. A wall-clock
number would need a load test, which has NOT been run.

**Why neither is landed at its call site.** `check_lane_claims.py`: `ops.py` is
held by `ncaaf-live-resim-wire`; `intelligence_state.py` is held by THREE open
lanes — `polymarket-yes-leg-binding`, `layer2-cap-raise` (both session
`5611932c`) and `layer2-sim-disagrees` (`3492626c`). **Neither session appears in
`list_sessions(include_archived=True, limit=80)`**, which reaches back to
2026-08-31. Every prior take from `3492626c` was an EXPLICIT USER DECISION, so
these two are queued as decisions, not taken.

**Design note worth keeping.** The single-flight ships two classes and the call
site needs the one that stores NOTHING. That cache is bounded by ROW COUNT, not
entries, because `#632` itself measured it at **37.50 MB while obeying its
32-entry cap** — entry size varies by orders of magnitude with slate size.
Substituting a generic entry-capped cache would have reintroduced the exact bug
that bound was added to fix. **A cache is not a drop-in for a cache.**

**Still unaddressed from `UPDATE 37`:** `/api/board/game-chips` (bimodal, 11 ms
typical / 11.6 s worst) and the `request_path_guard` line that already names a
live ESPN fetch inside a Flask handler
(`operation=wnba_has_games_for_date_espn_fetch`).


### `[web-oom-leak]` UPDATE 39 — **BOTH CALL-SITE PATCHES ARE LANDED ON `main` (`d5e4cc51`). Production is still UNMEASURED.**, 2026-09-07T23:4xZ `[session b2b5b45b]`

`UPDATE 38` left both fixes one diff short of their call sites, blocked on lane
claims. User decision: "land both patches". Both are in.

* **`syndicate/blueprints/ops.py`** — the export walk now lists each directory
  ONCE instead of once per pattern naming it (18× for the busiest, per sport,
  per request). 43/38 line churn is one level of dedent.
* **`pipeline/intelligence_state.py`** — a single flight around
  `_COMBINED_INTELLIGENCE_RESPONSE_CACHE`. The store and its ROW-COUNT pruning
  are untouched on purpose.

**What is measured:** 8 threads against the REAL
`read_combined_intelligence_response` go from **8 date-reads to 1**. 122 tests
in the directly relevant suites, 279 across everything calling that function.

**What is NOT, and this is the part that matters:** production. No load test and
no deploy. **Elapsed in that A/B was UNCHANGED at ~1.00 s** — the stub sleeps, so
parallel sleeps do not contend. The A/B measures WORK COUNT; the production claim
is SLOT OCCUPANCY (each rebuild holds one of web's 8 gunicorn slots for 5–18 s),
which is an argument, not a reading. **The verification this lane owes is the
≥5 s request share re-measured the same way as the 32.5% baseline, AFTER a
deploy.** `COMBINED_BOARD_SERVED_STALE` is the line proving the single flight
fires, and it needs a request-count denominator beside it.

**Five NFL-nickname tests are red** (`test_ask_sport_coverage.py`,
`test_ask_the_syndicate.py`). They fail IDENTICALLY on clean HEAD with both
patches reverted — measured, not assumed. Pre-existing, and not this lane's.

**Claims, for the record.** All four owning sessions are absent from
`list_sessions(include_archived=True, limit=80)`; `send_message` to `520cd594`
returned `Session not found`, which is how absence was CONFIRMED rather than
inferred from a roster scan. `ops.py` TAKEN from `ncaaf-live-resim-wire`.
`intelligence_state.py` NOT claimed — a NOTICE in `layer2-sim-disagrees`, since
claiming it would contest the one live holder and `check_lane_invariants.py`
fails on that, correctly.

### `[web-oom-leak]` UPDATE 40 — **DEPLOYED AND MEASURED. The export walk is 3.2x. The intelligence single flight turns a health-check FAILURE into a clean run. `#632`'s core question is answered.**, 2026-09-08T01:0xZ `[session b2b5b45b]`

Web `72aebc06` → `8589c005`. Supersedes `UPDATE 39`'s "production is UNMEASURED".

**THE CAUSAL PROOF, which is the finding that outlives the numbers.** A 6-concurrent
x 3 burst on `/api/intelligence/query` produced `unhealthy — HTTP health check
failed (timed out after 5 seconds)` at 00:28:29.375Z, the second the burst ended —
**byte-identical to the 35 `server_failed` events this investigation began from.**
`UPDATE 37` argued web dies of latency, not memory. It is now demonstrated: 18
requests on one slow route take the service down. **Both load tests caused a real
brief outage (~28 s, ~30 s).**

**MEASURED — export `?names_only=1`** (reads no file bodies, so it isolates the
walk): **60,876 → 19,139 ms p50, 95,740 → 25,579 ms max.** The AFTER arm ran on a
COLD page cache, which understates it. n=2 per probe.

**MEASURED — `/api/intelligence/query`, identical load, clean window:**

    arm                   completed  errors   p50        unhealthy
    BEFORE 72aebc06          16/18      2    20,671 ms   YES
    AFTER2 8589c005 clean    18/18      0    24,108 ms   **NO**

9 `COMBINED_BOARD_SERVED_STALE` lines confirm the mechanism firing. **The
percentiles are biased AGAINST the fix**: BEFORE's exclude its 2 errors — the
worst cases — so the arms lack a common denominator and "p50 got worse" is
unsupported. Raw samples were not retained; only summaries. **Store them next time.**

**REACHABILITY, checked before trusting any of it:**
`SYNDICATE_INTELLIGENCE_COMBINED_BOARD_DEFAULT='true'` on web (absent ⇒ FALSE, so
this was not optional to check), `WEB_CONCURRENCY=2` x `GUNICORN_THREADS=4` = 8
slots, and `..._CACHE_SECONDS` **absent**, so the 15 s code default is live.

**I SHIPPED AND FIXED A REGRESSION IN THE SAME NIGHT.** `d5e4cc51`'s
`patterns_that_can_match` compared directory DEPTH while the caller applies the
subset with `fnmatch`, whose `*` crosses `/` — so `?pattern=` silently dropped
every deep family, live 00:37:33–00:47:15Z. Fixed `a0d02297`. **48,717 witnesses
/ 0 unsound drops** over the real 177 patterns; **250 unsound** against the actual
buggy file. Scope, narrowed by three independent checks: **pattern-filtered
listings only — no deletions, no unfiltered reads.**

**A SUBSET-SHAPED LIMIT ON THE 3.2x, and it was measured with NO `?pattern=` at
all.** Keep-counts are a local function of the pattern lists: `wnba_source/*`
keeps 111 of 177, `mlb_source/*` 107, but leading-`*` `*sim_input_report*` keeps
**161** — so it degenerates to nearly the full 176-pattern walk. **The grouped
walk is subset-independent and helps everywhere; the pre-filter cannot save a
leading `*`.**

**STILL OPEN.** The **>=5 s request share against the 32.5% baseline is NOT
measured** — that baseline came from organic traffic and a synthetic burst cannot
answer it. The `unhealthy` absence is ONE run, observed ~2–3 min past burst end.
`/api/board/game-chips` (11 ms typical / 11.6 s worst) and the
`request_path_guard` ESPN fetch inside a Flask handler are both untouched.

### `[web-oom-leak]` UPDATE 41 — **THE CHIP PUBLISH CADENCE IS NOT FIXED, and my own `b81eab85` cannot fix it. The fast path is a MEMORY-PRESSURE FALLBACK, not a periodic refresher.**, 2026-09-08T03:1xZ `[session b2b5b45b]`

**MEASURED, and this is the number that matters.** Consecutive
`GAME_CHIPS_PUBLISHED` on refresh-worker, **per date**, 22:00–02:54Z:

    date=2026-09-07 (what web reads)  n=13  median 24.1 min  range 12.6–32.2
    date=2026-09-08                   n=7   median 47.3 min  range 24.7–55.6
    LAYER2_FAST_REFRESH lines                0

Against the endpoint's **120 s** freshness threshold, a 24.1-minute median is
**12x over** — which is why `/api/board/game-chips` serves
`source=inline_artifact_stale` on essentially every request. Per date matters:
the worker alternates today and tomorrow, so an all-dates gap understates what
web sees by ~2x.

**`b81eab85` FIXED A REAL DEFECT THAT CHANGES NOTHING TODAY.**
`_layer2_fast_refresh_at` was one float guarding a per-DATE resource, and the
heavy build stamped it, so a build for 09-07 silenced the fast path for 09-08.
Keyed per date, 6 tests, 651 passing across every suite touching the state
service. **But the path it gates is only CALLED at
`intelligence_state.py:7555`, inside
`if _abort_build_candidate_pool_if_memory_critical("pre_source_state_fingerprint")`
— a MEMORY-PRESSURE FALLBACK.** `MEMORY_GUARD_ABORT` has not fired since the
worker's 02:54:37Z deploy and headroom reads **3,450 MB**, so the guard never
refuses and the fallback never runs.

**I CLAIMED THE OPPOSITE AND IT WAS WRONG.** `b81eab85`'s message says the fix
"makes an inert path START RUNNING" and warns it adds periodic work on a
memory-constrained worker (`#241`). Both halves are false: the path stays inert,
so there is **no added duty cycle** — the risk I flagged does not exist — and
**no cadence improvement** either. The fix is correct and latent: it will matter
the first time the memory guard fires, and not before.

**NO DEPLOY WAS NEEDED OR MADE.** `b81eab85` reached refresh-worker inside
another session's `5b459411` at 02:54:37Z. Verified by CONTENT, not ancestry:
`_mark_layer2_fast_refresh` appears 3x in `git show 5b459411:pipeline/intelligence_state.py`.
Claim acquired, found redundant, released — a redundant restart would have killed
an in-flight board build and interrupted live-lens ticks during live games for
nothing.

**THE ACTUAL LEVER, not attempted.** Chips are published once per
`build_layer2_shortlist`, so their cadence IS the heavy board build's cadence
(~10–20 min per date). `layer2_shortlist.py`'s own comment already states the
chips depend on NONE of the surrounding work — they are built from per-sport
provider payloads. So the fix is a **small periodic chip publish decoupled from
the board build**, at ~120 s for `central_today_iso()` only. That is genuinely
new periodic work on the 4 GB worker and needs a headroom reading either side —
`#241` is the precedent. The cheap alternative is raising
`SYNDICATE_GAME_CHIP_ARTIFACT_MAX_AGE_SECONDS` toward the real cadence, which
`#564`'s comment already describes as "favour the worker and accept a staler
scoreboard" — that hides the symptom rather than fixing it.

### `[web-oom-leak]` UPDATE 42 — **CLOSING MEASUREMENT: on the routes that existed at baseline, the ≥5 s share fell 38.50% → 4.76%. What remains is a route family that did not exist in the baseline and is not this lane's.**, 2026-09-08T14:4xZ `[session b2b5b45b]`

Settled organic window, n=111, taken >12 min past the deploy boot that
contaminated the first reading.

    window                          ALL routes           EXCLUDING /ncaaf*
    BEFORE 2026-09-07 23:00-00:00Z  n=213  82 (38.50%)   n=213  82 (38.50%)
    AFTER  2026-09-08 14:15-14:36Z  n=111  29 (26.13%)   n=84    4 ( 4.76%)

**`/ncaaf*` had ZERO requests in the BEFORE window** — it is not a route that got
slower, it is a route family that did not exist there. In the AFTER window it is
**n=27 with 25 over 5 s (92.6%)**, i.e. **25 of the 29 slow requests on the whole
service**. That is `nfl-ncaaf-ui-parity`'s freshly deployed card code
(`09f6ab86`, 14:02:20Z), post-boot, relayed to them with the measurement recipe
and NOT diagnosed by me.

**PER ROUTE, which is the mix-independent view and the honest one:**

    route                        BEFORE                    AFTER
    /api/ops/artifacts/export    26,057 ms med (am probe)   59 ms med, 0/42 >=5s
    /api/board/game-chips        5,537 ms, 36/61 (59%)      1,145 ms, 1/6
    /api/intelligence/query      6,800 ms, 46/60 (77%)      4,104 ms, 2/5 (40%)

**ONLY EXPORT IS STRONG (n=42).** chips n=6 and intelligence n=5 are thin and are
recorded, not claimed; for chips the real evidence is the controlled 10-probe run
(10/10 `worker_artifact`, p50 422 ms, 0 over 5 s).

**AND THE 38.50% → 4.76% IS NOT PURELY THESE FIXES.** The windows differ in time
of day and therefore in MIX: the baseline hour put 121 of 213 requests (57%) on
the two heavy routes, the after window puts 11 of 111 (10%). Direction and
magnitude are clear; a clean attribution would need matched hours.

**WHAT `#632` NOW SAYS, end to end.** Web was never being OOM-killed — 35
`server_failed`, zero `evicted=True`, every one a 5 s health-check timeout, and a
synthetic burst reproduced that failure byte-identically. Three causes were found
and fixed with measurements: an export walk listing each directory once instead
of 18x per sport; a combined-board cache whose read and write had nothing between
them; and a scoreboard artifact published on the board build's 24-minute cadence
against a 120 s freshness threshold, now on its own 135 s clock with the reader's
threshold raised to 180 s so the two no longer straddle.

**OPEN, and neither is this lane's to close:** `/ncaaf*` at 92.6% over 5 s, and
`/api/intelligence/query` still at 40% over 5 s on n=5 — the single flight removed
the duplicate rebuilds but one rebuild still costs seconds, and that cost is
untouched.

### `[web-oom-leak]` UPDATE 43 — **WEB *CAN* BE OOM-KILLED, and the unslimmed `/api/intelligence/query` is one way to do it. This RETRACTS the "not memory, latency" framing as a GENERAL claim.**, 2026-09-08T15:5xZ `[session b2b5b45b]`

`UPDATE 37` established that web dies of LATENCY, not memory: 35 `server_failed`,
zero `evicted=True`, every one a 5 s health-check timeout. **That remains true of
those events and is now FALSE as a general statement.**

**SIX `oomKilled memoryLimit=2Gi` on web on 2026-09-08.** Four preceded anything I
sent (01:10:07, 14:13:44, 14:23:48, 14:43:54). **Two are MINE** (15:11:13,
15:13:28): I POSTed `/api/intelligence/query` with no `slim_aliases` and it built
**3,927 rows five times over into a 64.98 MB payload in 28.2 s**, inside a 2 GiB
container with 8 gunicorn slots.

**THE DANGEROUS SHAPE IS THE DEFAULT.** `slim_aliases` is opt-IN. The UI sends it;
nothing else must. `scripts/watch_clamp_trigger.py:340` POSTs
`{"question": "show me the board"}` unslimmed on a 600 s poll — its last
observation is 2026-08-16 so it is NOT running, checked before blaming it, but it
is a loaded gun. `response_compression.py` already documented this endpoint at
**53-67 MB per call**; that the default can kill the service was not written down.

**FIXED AND VERIFIED IN PRODUCTION (`009bb3c3`, live 15:31:38Z).**
`_RESPONSE_SLIM_ROW_GUARD = 2500` on all three response exits. Re-sending the
request that killed it:

    latency   28,235 ms -> 3,785 ms      payload  64.98 MB -> 32.53 MB
    server:   RESPONSE_SLIM_GUARD rows=3932 guard=2500
              dropped=['boardContract','by_sport','recommendations']

Below the guard the contract is UNCHANGED — an unasking caller gets the same
object back, uncopied. Above it, only keys `_slim_response_aliases` PROVES are
duplicates are dropped, each declared in `_response_aliases`.

**STILL CARRIES THE SAME ~3,932 ROWS THREE TIMES for 32.53 MB.** The guard makes
the endpoint survivable, NOT efficient. Collapsing `cards` / `ranked_all` /
`top_opportunities` is a real contract change and was not attempted.

**THE OOM CLUSTER'S CAUSE IS NOT ESTABLISHED.** `/ncaaf/cards` is in flight at all
three pre-probe kills — one in the SAME SECOND — and is 25 of the 29 slow requests
on the service (median 11,626 ms, 20/20 over 5 s, POST-BOOT). `/api/intelligence/query`
is also in flight at all three. Per-request memory is not visible, so this is
CORRELATION, relayed to `nfl-ncaaf-ui-parity` and not diagnosed here. No
`oomKilled` since 15:31:38Z, but the cluster ran 10-20 min apart and that window
is comparable — **not proof the guard ended it.**

### `[web-oom-leak]` UPDATE 44 — **`/api/intelligence/query`'s rebuild cost was a 15-SECOND cache TTL on data that changes every 10–18 MINUTES. `board_read` 2,916–6,841 ms → 0.1 ms.**, 2026-09-08T16:4xZ `[session b2b5b45b]`

The last route `#632` owed. **The fix is an env value, not code:**
`SYNDICATE_INTELLIGENCE_COMBINED_BOARD_CACHE_SECONDS`, absent (code default
**15**) → **180**, via the single-key API.

    stage                  BEFORE (15 s TTL)      AFTER (180 s TTL)
    board_read             2,916 / 3,816 / 6,841    0.1 / 0.1 / 0.2 / 0.1
    TOTAL server-side      4,142 / 5,010 / 7,626    409 / 1,058 / 645 / 532

Comparable boards (1,520 → 1,465 rows). **At the UI's real 60 s cadence:** a
request 65 s after another HIT (0.2 ms); one 292 s after another correctly MISSED
(3,420 ms). Steady state is 2 of 3 polls cached; at 15 s a 60 s poll missed 3 of
3 by construction. Measured board republish cadence, which is what makes 180 s
conservative: **11m31s, 17m58s, 10m09s**.

**THE SAME DEFECT SHAPE AS THE CHIP BUG EARLIER THE SAME DAY** — a freshness
bound far tighter than the data it guards (here 40–72x). Worth carrying: when a
producer and a consumer both hold a time bound, check their RATIO, not each
value's plausibility.

**THIS COULD NOT BE FOUND BY PROBING AND THE ATTEMPT PRODUCED TWO WRONG
ANSWERS.** The same request varies **7,759 → 3,000 ms** — a 4,759 ms spread, 9x
the effect being chased. The `QUERY_STAGE_MS` instrument (`0d55ba1b`) is what
made it attributable. **And my probes never once hit the cache**: spaced ~16–17 s
against a 15 s TTL, so the control request was itself a miss — which is exactly
why a cache problem presented as noise.

**EVERY READING HERE IS MY OWN TRAFFIC.** 4 requests to that endpoint in the
16:30–16:40Z window, all mine, of 51 to the service. **The organic reading is
OWED**; a watcher is armed and had found nothing by 16:51Z, with a passing
control (87 requests to web after the boundary, none to this endpoint).

**STILL UNFIXED, and it is the next candidate:** `limit=50` returns 50 rows and
still ships **13.71 MB**, because the limit slices `top_opportunities` and NOT
`ranked_all` (7.37 MB) or `board_contract.cards` (7.37 MB). **Those two are NOT
interchangeable duplicates** — 3,317 of 3,914 rows match and **597 differ** — so
they cannot be aliased away; slicing them is the fix, and it is a contract
change.
