# state — worker

Split out of `state.md` by `scripts/split_state.py`. Bodies are verbatim.
The INDEX of every subject, across every part, is in `state.md`; the
one-subject-one-section rule is global and spans these files.
Same rules as state.md: when a fact changes, EDIT THE LINE.

## [refresh-worker-headroom-2026-09-02] THE ~1.4GB HEADROOM FIGURE IS STALE, AND THE METRIC EVERYONE READS IS THE WRONG ONE `[2026-09-02, lane m625-env-snapshots, measured off 200 MEMORY_WATCHDOG samples 15:30-16:10Z]`

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

## [render-egress-cause] THE BANDWIDTH BILL IS `web` POLLING EXTERNAL FEEDS ITSELF, AND IT IS 100% BILLED `[verified 2026-09-06, lane render-egress-transport, web `67fd8c9d`]`

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

**Live-projection registries, for reference** (`board_enrichment.py:176,1128,1130`):

    _LIVE_GAME_STATE_SPORTS = {mlb, soccer}
    _LIVE_PROP_SPORTS       = {mlb, wnba, soccer}
    _LIVE_GAMELINE_SPORTS   = {mlb, wnba, soccer}

nfl/nba/nhl/ncaaf/ncaab are in none of them.

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
