# Syndicate — Work Lanes

> Lanes are exclusive by file path. Two lanes may not claim the same file.
> Max concurrent OPEN lanes: 3 (see `state.md`).
> Managed by `/lane`. Do not hand-edit while a session is running.

## OPEN

### memory-guard-reclaimable — OPEN — opened 2026-08-13 — session: memory-guard
- Goal: `memory_headroom_snapshot` decides on unreclaimable memory
  (`anon + shmem + slab_unreclaimable`), so that total memory in use FALLING
  can never tighten the guard. Unblocks `#417` and `#387` in one change.
- Files (exclusive to this lane):
  - `syndicate/features/shared/memory_observability.py` — the fix. Two sites
    share the same wrong formula:
    - `memory_headroom_snapshot()` L238–242 — `reclaimable_bytes =
      inactive_file + slab_reclaimable`. This is the guard.
    - `log_container_memory()` L599–609 — recomputes the SAME expression to
      derive `memory_unreclaimable_mb`. Diagnostic only, but it is the line
      humans read, so it must move with the guard or the log will contradict
      the decision.
  - `tests/test_memory_observability.py` — see hazard below.
  - `pipeline/intelligence_state.py` — L3189 constant only
    (`_MIN_SAFE_MEMORY_HEADROOM_BYTES = 1900MB`). No call-site change.
  - `syndicate/features/intelligence.py` — L2563 constant only
    (`_OVERVIEW_MIN_SAFE_HEADROOM_BYTES = 3000MB` vs a stage measured at
    ~1479MB). No call-site change.
- Not touched, deliberately: the five calling modules
  (`live_refresh_loop.py` ×2 wrappers, `live_lens_loop.py` ×2 wrappers, and
  both `intelligence_state.py` call sites) all funnel through the one shared
  function. Per the `#334` lesson, the fix goes INSIDE it and touches zero
  call sites — that is what makes it unmissable.
  `scripts/check_worker_memory_gate.py` L338 records that it never inherited
  this formula and works on an RSS basis; adjacent, not the same defect,
  and out of scope.
- Hypothesis: the guard's verdict moves on kernel LRU bookkeeping, not on
  memory pressure. `#417`'s 300 consecutive aborts were caused by ~243MB
  being promoted `inactive_file` → `active_file`, which the formula counts
  as unavailable, while `anon` drifted +18.9MB across all 300 samples.
- Falsification test: replay the `#417` sample series — effective headroom
  fell 1877 → 1643MB while total memory in use fell 3120 → 2705MB. Under the
  new metric the guard must NOT tighten across that series. If it still
  tightens, the LRU-promotion hypothesis is wrong and something else moved it.
- Verification (all three required):
  1. Unit: the replayed `#417` series does not tighten.
  2. Liveness — the guard must still be able to REFUSE. Construct a case with
     genuinely high unreclaimable memory and assert `sufficient` is False.
     Without this, "zero aborts in production" is indistinguishable from a
     permanently-inert guard, and inert is how `#75` (the 4GiB OOM) happened.
  3. Production, after deploy: `MEMORY_GUARD_ABORT
     stage=pre_source_state_fingerprint` over a full day drops to ~0 with
     `anon` flat, and `#387`'s overview build stops aborting at
     `sports_done=0 sports_total=8`.
- HAZARD — an existing test asserts the bug is intentional.
  `test_active_file_and_shmem_are_not_treated_as_reclaimable`
  (`tests/test_memory_observability.py:173`) and the code comment at
  `memory_observability.py:234–237` both call the current formula
  "deliberately the conservative reading". That premise was overturned by
  `#417`: excluding `active_file` is not conservative, it is unstable — it
  makes the verdict swing on a quantity the kernel moves for free. This test
  must be rewritten with a comment recording WHY the premise changed, never
  deleted or quietly made green.
- HAZARD — the direction of failure. Relaxing this guard is what the
  `memory_observability.py:166–168` comment warns walks back into `#75`, the
  4GiB OOM. Note `shmem` was 0.0 in the `#79` measurement, so it has never
  actually been exercised as a pinned-cache term; do not assume it is zero on
  refresh-worker today.
- Deploy: refresh-worker `.py` only. No `render.yaml`, so no `blueprint_sync`
  exposure. Standing sim-check gate applies before any deploy is triggered.
- Blocked by: none.
- **STATUS 2026-08-13 — falsification test written and RUN. Hypothesis
  SURVIVED; the lane is cleared to proceed to the fix.**
  `tests/test_memory_observability.py`, 11 passed / 2 failed, the two failures
  being the new falsification tests, failing for exactly the predicted reason:
  - `test_417_page_cache_promotion_must_not_move_the_guard` — moving 243MB
    between LRU buckets, with `current`, `anon` and total file cache all held
    constant, swings the guard **1895.3 -> 1652.3 (243.0MB)**. The observable
    moves the full size of the reclassification with nothing real changing.
  - `test_417_series_never_tightens_while_memory_in_use_falls` — the recorded
    4-sample series is refused at sample 1 (`09:29:27 refused a build that
    fits`), i.e. all 300 aborted cycles had room under the unreclaimable
    reading.
  - Fixture provenance: `slab_reclaimable` is absent from the recorded table
    and was back-solved per row (34.2 / 35.3 / 34.8 / 39.3MB). All four rows
    then reproduce the recorded `headroom` to **±0.00MB**, so the fixture is
    derived from the real formula rather than fitted to the conclusion. If a
    future edit breaks that reproduction, the fixture is wrong, not the code.
  - `test_unreadable_anon_must_not_produce_a_rosy_headroom` **passes today and
    is still required.** It is inert against the current formula, which never
    reads `anon`; it becomes load-bearing the moment the fix does. Do not read
    its green as evidence of anything about the fix — it is a regression guard
    placed ahead of the change, and its own predicate is not yet exercised.
  - Not committed. The file is RED on a shared tree by design.
- **STATUS 2026-08-13 — FIX WRITTEN. Both falsification tests now pass;
  `tests/test_memory_observability.py` 13/13 green. Not committed, not
  deployed, production effect UNVERIFIED.**
  - The guard now decides on `max_bytes - unreclaimable`, where unreclaimable
    is `max(anon + shmem + slab_unreclaimable, current - reclaimable_file)`
    and `reclaimable_file` now includes `active_file`.
  - **The max() is the part worth reviewing.** The formula `learnings.md`
    prescribed (`anon + shmem + slab_unreclaimable`) is a LOWER bound on
    unreclaimable memory — it credits everything `memory.stat` fails to
    attribute as available, which is the permissive-on-unknown shape. Taking
    the larger of it and the residual basis (`current - reclaimable_file`,
    which is what `#318`'s log line already used) makes unaccounted memory
    count against the guard. On the `#417` samples the two bases differ by
    ~5.1-5.6MB, so this does not change the verdict there — it changes what
    happens if `#327`'s unattributed allocator ever shows up in this reading.
  - Both helpers are shared by the guard and by `log_container_memory`, which
    had an independent second copy of the reclaimable expression. Fixing only
    the guard would have left the abort line contradicting the decision it is
    read to explain. Grepped after the change: no third copy exists.
  - Degrade path unchanged in the safe direction: `anon` absent -> return None
    -> fall back to the previous arithmetic, never to a rosier number.
  - `#417`'s second defect fixed in the same pass:
    `headroom_including_file_cache_mb` -> `headroom_excluding_file_cache_mb`.
    The name stated the opposite of its value and produced a 792MB apparent
    deficit against a real one of 278MB during the incident. Renamed rather
    than aliased; nothing outside this module's tests reads it.
  - Two pre-existing tests changed deliberately, neither made green by
    weakening it:
    - `test_reclaimable_page_cache_does_not_count_against_headroom` (`#79`)
      moved +34.3MB, exactly its fixture's `active_file`. Conclusion it
      protects is intact (868 vs 3428, was 868 vs 3393).
    - `test_active_file_and_shmem_are_not_treated_as_reclaimable` split into
      `test_shmem_is_not_treated_as_reclaimable` (still true, different
      reason) plus the new `#417` invariance test that owns the overturned
      active_file half.
  - Consumer blast radius, partially checked: 7/7
    `test_intelligence_overview_memory_guard.py`, and 25 memory/headroom/guard
    tests across `test_intelligence_state.py`, `test_deploy_preflight.py`,
    `test_live_lens_loop.py`. **Full 6-file consumer sweep still running at
    time of writing — not yet a result.**
  - REMAINING before this can close: the production half of Verification
    (items 2 and 3 above) is untouched. Nothing here proves the deployed
    behaviour changes; per `learnings.md` a deployed fix can be inert.
- Discrepancy noted, does not affect the verdict: the `#417` narrative in
  `.syndicate/log/2026-08-13.md` and `todo.md` says `current_mb` fell
  "3120 -> 2705", but the 4-row table it sits beside records 2988.6 -> 2705.3.
  The 3120 figure is not in the table; it is presumably an intermediate peak.
  Both readings agree in DIRECTION (usage fell, guard tightened), so the
  falsification test holds either way — but the table is the authoritative
  per-sample record and is what the fixture uses.

## CLOSED THIS SESSION

### render-yaml-web-block-hygiene — DONE 2026-08-13 — **NO LANE WAS EVER OPENED**
- Recorded after the fact. The originating task carried an explicit "do not open
  or close any lane" instruction and the work grew past it; five commits landed
  outside lane discipline. Flagged rather than tidied away.
- No collision occurred: the only OPEN lane (`memory-guard-reclaimable`) scopes
  itself to "refresh-worker `.py` only. No `render.yaml`." That was a read, not
  a claim — a second session editing `render.yaml` would not have been detected.
- Files touched: `render.yaml` (web `envVars` only), plus the ops-kit install
  (`.claude/**`, `.syndicate/**`, `CLAUDE.md`).
- Done: web block 62 → 52 entries; nine worker-only keys removed; three
  duplicate declarations (one per service) deduped. Every removed key remains
  declared on both workers.
- Verified: `audit_blueprint_drift.py` exit 0 / zero reverts after each commit;
  `tests/test_render_yaml_envs.py` + `tests/test_refresh_worker.py` pass;
  no duplicate keys on any service.
- **Unverified: nothing was deployed.** Reachability is static analysis only —
  no process has been observed booting without these keys.
- **Open obligation:** three commits unpushed (`054b2306`, `cc2e1803`,
  `e8611888`), `origin/main` at `bf06710c`. Two `render.yaml` commits are
  already on origin with no `blueprint_sync` seen in a ~23-minute window —
  that is a window, not an all-clear.

### board-transport — CLOSED 2026-08-13 (work measured 08-10/11)
- Goal: the board computes correctly every cycle and cannot cross the transport.
- Files (exclusive to this lane while open):
  - `pipeline/intelligence_state.py`
  - `syndicate/features/shared/refresh_state_store.py`
  - `syndicate/features/shared/memory_observability.py`
  - `syndicate/blueprints/ops.py` (trace blocks only)
  - `scripts/deploy_preflight.py`, `tests/test_state_freshness.py`,
    `tests/test_candidate_trace_reads.py`, `tests/test_deploy_preflight.py`
- CLOSED: `#317` transport, `#322` state cache, `#324` keyvalue residency,
  `#327` memory instrument, `#334` freshness reporting, `#337` write-path count.
- **OPEN and handed back:** `#338` (serve reads `query_state_cache` at 150 while
  `board_snapshot` stores 220 — cause not localised), `#332` (NFL autorun guard,
  filed not fixed).
- **Blocked on another lane:** `#336`/`#338` are downstream of `#285`'s memory
  ratchet. The overview guard needs **~725MB** it does not have
  (3000MB floor vs 2275.5MB measured headroom), so it aborts at
  `sports_done=0 sports_total=8` and the candidate pool is empty by construction.
- All commits are ancestors of `478edd78`. No uncommitted work from this lane.

### sim-execution-observability — CLOSED-PENDING-MEASUREMENT 2026-08-13
- Goal: measure sim execution per sport (when/how long/how often/what triggers
  a re-sim), then fix what the measurement exposed.
- Files (exclusive to this lane):
  - `syndicate/features/shared/live_refresh_loop.py`
  - `syndicate/features/shared/sim_run_ledger.py`
  - `syndicate/features/shared/odds_book_quotes.py`
  - `syndicate/features/nfl/sources.py`
  - `scripts/run_refresh_worker.py`
  - `scripts/refresh_odds_sources.py`
  - `syndicate/blueprints/ops.py`
  - `syndicate/blueprints/home.py` (segment profiler only)
  - `syndicate/features/intelligence.py` (SLOW_GAME_CANDIDATE only)
- SHIPPED AND VERIFIED: `#388` (orphan cause recorded, observed twice in prod),
  `#389` + artifact-root fix (guard and writer share one resolver),
  `#390` (sim run ledger + `/api/ops/sims/ledger`), `#393` closed as
  root-caused-no-code-change.
- **OPEN AND UNMEASURED: where the board-build cost lives.** `448e1816` is live
  (`15:27:25Z`) carrying `SLOW_SEGMENT_PROFILE` (named segments, rows vs tail)
  and `_QUOTE_JOIN_STATS` (identity resolution by reason + `rows_walked`).
  Neither has emitted: the line is gated per-GAME at 5s and daytime games are
  ~0.4s each.
- Verification still required: one EVENING build (historically 20:49-00:45Z),
  then read one line:
  - `tail_s` >> `rows_s` -> cost is post-loop; `enrich_block` names it
  - `rows_s` >> `tail_s` -> the row loop is implicated after all
  - `by_teams_fallthrough` ~= `calls` with large `rows_walked` -> the cheap
    `event_id` key never matches, as predicted
- Blocked by: nothing. Needs an evening slate only.
- CAUTION: the previous instrument in this lane produced a confident wrong
  answer (see `learnings.md`). Read the segment NAMES, not the totals.

### soccer-sim-grouping — CLOSED 2026-08-10 — shipped and verified, one thread handed on
- Goal: `#282` break the soccer sim into per-league groups. Grew into `#311`,
  `#312`, `#327` as each surfaced from the one before.
- Files (exclusive to this lane):
  - `scripts/refresh_odds_sources.py`
  - `scripts/run_refresh_worker.py`
  - `scripts/audit_blueprint_drift.py` (new)
  - `syndicate/features/shared/ops_refresh.py`
  - `syndicate/features/shared/live_lens_loop.py`
  - `syndicate/features/shared/memory_observability.py`
  - `tests/test_live_lens_loop_publish_instrumentation.py` (new)
- **SHIPPED AND VERIFIED:** `#282` (8 launches, full rotation), `#311` (cap
  fired 16:06:31Z, first time ever, on the autorun path that was broken),
  `#327` instrument work (ring + high-water + in-sweep sampler all confirmed).
- **SHIPPED, MECHANISM UNTESTED:** `#312` — `f1bba90c` on `main`, live on
  nothing (its only deploy was cancelled). `render.yaml` change parked on
  branch **`hold/312-sync-false`**, deliberately off `main`.
- **OPEN, HANDED ON:** `#327 RESIDUAL` — the allocator is unattributed after
  five eliminations. Next action is one small change: record **bytes** on the
  pull and sweep paths beside the existing counts.
- No production change from this lane; all deploys were the oversight lane's.


### layer1-live-tier — CLOSED-PENDING-MEASUREMENT 2026-08-13
- Goal: Layer 1 board carries live projection, sim projection and actual-so-far
  on live rows, with correct live game state; retire `book_grid`.
- Files (exclusive to this lane):
  - `syndicate/features/shared/live_projection_join.py`
  - `syndicate/features/shared/board_enrichment.py`
  - `syndicate/features/shared/book_grid.py`
  - `syndicate/templates/shared/layer1_board.html`
  - `syndicate/templates/book_grid.html` (deleted)
  - `vendor/mlb_bettingv2/sim_engine/live_mc.py`
  - `vendor/mlb_bettingv2/tools/web/flask_frontend.py`
- SHIPPED AND VERIFIED: `#412` (prop join 0 -> 41), `#413` (live state,
  210 rows corrected), `#415` (Betting Board), `#411` (superseded lines).
- **OPEN AND UNVERIFIED: `#416`.** Writer emits live probabilities
  (`priced: 71`/`74`); `rows_live_edged` is still 0 on every build. The
  measurement is not yet READABLE — `e054e19f` splits the counter by game
  state so the `live` bucket can be read without final-game zeros diluting it.
- Verification still required: one build against a slate with live games, then
  read `snapshot_by_game_state["live"]`.
  - `{rows>0, with_live_prob>0}` -> working, edge should follow
  - `{rows>0, with_live_prob=0, with_live_projection>0}` -> writer half failing
  - `{rows: 0}` -> still no live slate, no verdict
- Blocked by: nothing. Needs a live slate only.

### internal-hostname-cutover — CLOSED 2026-08-13 — verified in production
- Verification met: every `PUBLISH_OK` line on refresh-worker at `14:54:11Z`
  carries `url=http://syndicate-an21:10000/api/ops/artifact...`, publishes
  succeeding (`published_hot_artifacts count=14 failed=0`), and
  `PUBLISH_BUDGET uploads=915 used_mb=302.4 ceiling_mb=20480.0`.
- Durability: `render.yaml` carries the internal hostname for both workers, so
  a `blueprint_sync` reinforces the fix instead of reverting it — the one thing
  that could silently have undone it.
- Report committed at `eaf7965d`; tickets now point at it (`3447f983`).

### (superseded lane detail, kept for the file/line map)

### internal-hostname-cutover — CLOSED — opened 2026-08-13 — session: <name>
- Goal: `SYNDICATE_WEB_PUBLISH_URL` points at the internal private-network
  hostname; worker→web traffic no longer leaves the Render network.
- Files:
  - `render.yaml` — env definition. Two blocks, one per worker:
    L418 (`refresh-worker`), L778 (`live-odds-worker`). Both already read
    `http://syndicate-an21:10000` (internal) in the repo. Hostname is
    `syndicate-an21`, NOT `syndicate`.
  - `syndicate/features/shared/artifact_publisher.py` — the only runtime
    reader. Five sites: `_publish_url()` L567, `_export_url()` L1077,
    the pull configuration gate L1230–1231, `_stream_url()` L1614, and
    the single-artifact stream gate L1664.
  - `tests/test_artifact_publisher.py` — asserts full URLs built from the
    var (e.g. L342, L470–480, L522); fixture value is a public
    `https://syndicate.onrender.com`, so a cutover touches it.
  - **No hardcoded fallback exists for this var.** Every read goes through
    `_env("SYNDICATE_WEB_PUBLISH_URL")` and returns `""` / skips when
    unset — absent means "publishing off", not "publish to the public URL".
    `[from-code 08-13]`
- Hypothesis: n/a (root cause confirmed from code)
- Falsification test: n/a
- Verification: service-initiated egress on `live-odds-worker` drops to
  near zero within one full sweep cycle; artifacts still publish
  successfully (non-zero publish count, no 5xx in worker logs).
- Blocked by: none

## CLOSED

_(none yet — seeded ledger)_
