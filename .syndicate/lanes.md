# Syndicate — Work Lanes

> Lanes are exclusive by file path. Two lanes may not claim the same file.
> Max concurrent OPEN lanes: 3 (see `state.md`).
> Managed by `/lane`. Do not hand-edit while a session is running.

## OPEN

### checkpoint-guard-scope — OPEN — opened 2026-08-13 — session: hooks-test
- Goal: `checkpoint-guard.sh` fires on **this session's unpersisted work** and
  is silent otherwise — i.e. its pass branch becomes reachable and its
  denominator becomes the session, not the worktree.
- Files (exclusive to this lane):
  - `.claude/hooks/checkpoint-guard.sh` — scope + parsing + witness.
  - `.claude/commands/checkpoint.md` — step 7 wording only.
- CORRECTION to the closed `hooks-enforcement-test` lane: step 7 (`touch
  .syndicate/.last-checkpoint`) was reported missing from `checkpoint.md`.
  **It is present and has been since `0d0b8931`.** The marker was absent
  because that commit landed 08-13; the 27 observed Stop deliveries predate
  it. The defect is not a missing instruction — it is that the pass branch
  depends on a model executing an optional-looking last step.
- Hypothesis: two independent causes of the all-fire distribution.
  (1) `DIRTY` counts the whole worktree (66 files at the last checkpoint,
  4 of them the session's), so the condition is ~always true in a repo whose
  pipeline output is permanently dirty. (2) the pass branch needs BOTH
  `$TODAY_LOG` and `$MARKER`, and the marker had never been written.
- Falsification test: with the marker fresh and only generated output dirty,
  the guard must exit 0. If it still exits 1, scope is not the cause.
- Verification (both required):
  1. PASS branch witnessed — exit 0 at least once. Never observed to date.
  2. FIRE branch still works — touch a source file after the marker and
     confirm exit 1 naming that file, so the fix is not inertness.
- Note on method: running this hook in a terminal is legitimate here. The
  08-13 FORBIDDEN entry is about assuming stdout ARRIVES; delivery for this
  hook is already measured (27 deliveries), so what is unverified is the
  predicate, and the predicate is testable locally.
- Deploy exposure: none. Harness-only, no service code, no `render.yaml`.
- Blocked by: none.

### memory-guard-reclaimable — DEPLOYED, MEASUREMENT OPEN — opened 2026-08-13 — session: memory-guard
- **CHECKPOINT 2026-08-13 13:3x CDT. Code done and shipped; the lane stays
  OPEN because its verification is not complete.**
  - Shipped: `03073270` live on refresh-worker since 13:05 CDT (deploy
    `dep-d9v0b8bncjis73an78hg`). Verification items 1 and 2 (unit +
    liveness-in-test) MET: 13/13 memory_observability, falsification tests
    written before the fix and run red first.
  - Verification item 3 (production) **NOT met.** T+23min shows
    `LAYER2_SHORTLIST` x3 vs 0 in the preceding 4h12m and 0 aborts vs ~300 in
    5.4h — but the container is 23 minutes from boot, and the PRE-FIX code
    also rebuilt after a restart and re-froze ~3h later. Not discriminating
    yet.
  - **SINGLE NEXT ACTION for whoever picks this up: take the 24h read at
    2026-08-14 ~13:00 CDT.** Count `MEMORY_GUARD_ABORT` and
    `LAYER2_SHORTLIST` on `srv-d91dpertqb8s73co8ls0` since
    `2026-08-13T18:05:38Z`, and record `anon` drift. Aborts ~0 with the board
    still building = fix holds. Aborts resumed = it did not.
    Write the result into the OPEN `deploys.md` row. OWNER STILL UNASSIGNED.
  - Known gap, do not mistake for a result: `basis` cannot confirm the code
    path ran — it is emitted only on the abort branch. See `learnings.md`.
  - Push blocked, not by this lane: local `main` is 20 ahead / 6 behind and
    `.claude/hooks/session-start.sh` holds another session's uncommitted work.
    `03073270` is already on `origin/main`, so nothing here depends on it.
- **CHECKPOINT 2026-08-13 ~15:0x CDT — final for this session.**
  - Push blocker **CLEARED**: `session-start.sh` was committed by its own
    session (`0642cdf7`/`f8bace6a`). Local `main` now **22 ahead / 6 behind**,
    so a push needs a merge first and still carries other lanes' commits.
    Nothing in this lane depends on it — `03073270` is already on origin.
  - Filed **`#422`** (`7b480fe4`): web is 47 commits behind, only 14 of them
    production, and `layer1-live-tier`'s "SHIPPED AND VERIFIED" may cover only
    the worker half. Filed as an INFERENCE with the confirming check named.
  - A blanket web deploy **FAILED `/preflight`** — 14 commits across five
    lanes, two files claimed by open lanes, no named reader. The board slice
    alone is the deploy worth making, and it belongs to `layer1-live-tier`.
  - Three entries appended to `learnings.md`, all from this lane's own
    instruments misleading it: a discriminator that only emits on failure; a
    watcher whose label was not entailed by its exit condition; and
    "pushed to origin" != "applied to production".
  - **STILL THE SINGLE NEXT ACTION: the 24h read, 2026-08-14 ~13:00 CDT.**
    Owner still unassigned. Everything else in this lane is done.


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

### mlb-props-regen — OPEN — opened 2026-08-13 — session: mlb-props-regen
- Goal: MLB top-props/ladders rebuild automatically once prop odds land,
  instead of serving an empty artifact written before the odds existed.
  Testable outcome: a slate whose top-props artifact was written pre-odds
  gets a `props_now_available` launch within one cooldown of the odds
  landing, with no human trigger.
- Files (exclusive to this lane):
  - `syndicate/features/shared/live_refresh_loop.py` — all three fixes:
    - `_mlb_oddsapi_props_snapshot_has_entries()` L1554 — the blind read.
    - `_mlb_props_now_available_needs_regen()` L1562 — marker write moves out.
    - the fingerprint block L1938–1957 — marker write moves in (launch path).
    - `_sim_pipeline_deferral_reason()` L1673 /
      `_max_consecutive_pipeline_defers()` L1650 — starvation, SEPARATE
      COMMIT (see scope note).
  - `tests/test_live_refresh_loop.py` — see hazard.
- NOT touched, deliberately: `syndicate/features/shared/refresh_state_store.py`.
  Making `read_json_file` fall back to disk globally would fix this and change
  the semantics of every other caller in the repo at the same time. Out of
  scope; the narrow fix goes in the odds-presence helper.
- Hypothesis (recorded before testing — since CONFIRMED, see evidence):
  the `props_now_available` guard has **never been able to fire in
  production**. Its odds check reads through `read_json_file`
  (`refresh_state_store`, imported at L25), which for any path not containing
  `migration_runs/` goes to Redis with **no filesystem fallback** and returns
  `(None, True)` — "confirmed absent, read succeeded" — on a missing key. The
  snapshots it looks for are written by
  `vendor/mlb_bettingv2/tools/oddsapi/fetch_daily_oddsapi_markets.py:_write_json`
  (L87) as plain `tmp.write_text()` + `replace()`. **Writer is filesystem,
  reader is Redis.** So `has_pitcher_odds`/`has_hitter_odds` are always False
  and the guard returns "odds genuinely aren't posted yet" — silently, with no
  log line — every time.
- Evidence:
  - `SYNDICATE_REFRESH_STATE_BACKEND=keyvalue` confirmed live on
    refresh-worker via the Render env-vars API, so `_keyvalue_backed()` is
    True for these paths. This is the load-bearing precondition.
    `[measured 08-13]`
  - top-props written 00:24:21 CDT with `candidateCount: 0`; prop odds landed
    10:08 CDT (18 pitcher / 171 hitter markets); artifact still empty at
    11:43. `[measured 08-13]`
  - 5 of 100 sim ticks in 15:05–16:20Z reached the decision function at all
    (83 gated `intelligence_pipeline_busy`); all 5 returned `no_change` with
    `candidateCount = 0` and odds present. `[measured 08-13]`
  - The odds ARE on refresh-worker's own disk: the 11:56:56 rebuild ran with
    `--refresh-current-oddsapi off` and still produced 12 cards, so
    `daily_update.py` (plain filesystem IO) read them fine. Same box, same
    instant, same file — only the reader differs. `[measured 08-13]`
  - The 2026-08-13 recovery was NOT the safety net: an unrelated 3-game
    lineup resim (`--only-game-pks 823829,824238,824561`) happened to be in
    flight and its top-props stage rewrites the whole artifact. The
    `force-mlb-resim` trigger bounced off it with `previous_run_still_active`,
    so the fix is not attributable to it either. `[measured 08-13]`
- Falsification test: if the guard's odds check reads the snapshots from disk
  and it STILL returns False on a replayed 08-13 state, the writer/reader
  split is not the cause and the cooldown marker is the remaining candidate.
- Verification (all three required):
  1. Unit: a test that exercises the REAL `read_json_file` against a
     keyvalue-backed path with the file present on disk and the key absent.
     Must fail before the fix and pass after.
  2. Liveness — the guard must still be able to return False. Construct a
     case with genuinely no odds on disk and assert False, so "it fires now"
     is distinguishable from "it fires always". Per `learnings.md` 2026-08-13
     ("confirm an instrument can emit non-zero before believing its zero"),
     inverted here: confirm it can still emit False.
  3. Production, after deploy: on a slate whose top-props was written before
     odds landed, a `MLB_SIM_TICK` carrying
     `mlbDailySim.reason = props_now_available` appears within one cooldown
     of the odds file's `retrieved_at`. This reason string has **never once
     appeared in the logs** — absence is the current baseline, so a single
     occurrence is a clean positive.
- HAZARD — the entire existing test suite for this guard is blind to the bug.
  `test_mlb_props_now_available_needs_regen_true_when_odds_landed_after_empty_write`
  (`tests/test_live_refresh_loop.py:1492`) and its four siblings all
  `patch.object(live_refresh_loop, "read_json_file", side_effect=_fake_read)`
  — they replace the very function whose backend routing is the defect. They
  pass today and would pass against the broken code forever. New tests must
  NOT patch `read_json_file`. Do not delete the existing ones; they still
  cover the decision logic.
- HAZARD — three prior incidents (08-01, 08-02, 08-04) are named in this
  guard's own docstring and were "fixed" each time. Every one of those fixes
  refined code sitting downstream of a read that always returns None. Treat
  any further logic-only fix here as suspect until the read is proven.
- SCOPE NOTE — fix 3 (pipeline-defer starvation) is a SEPARATE COMMIT and
  should be a separate deploy. 83% tick suppression is real and measured, but
  the guard only needs to fire once per slate, and 5 opportunities in 75
  minutes is sufficient for that. Shipping a tuning change alongside the
  root-cause fix would make neither attributable — `learnings.md` 2026-08-12
  ("do not batch changes during a diagnosis").
- Interaction, not conflict: the breakthrough path in
  `_sim_pipeline_deferral_reason` gates on
  `_mlb_sim_memory_headroom_snapshot().sufficient`, whose meaning is being
  changed by the `memory-guard-reclaimable` lane. That lane owns
  `memory_observability.py`; this lane does not touch it. Expect the
  breakthrough rate to move when their fix lands, and do not read that as a
  result of this lane's work.
- Blocked by: none.

### hooks-enforcement-test — CLOSED 2026-08-13 — opened 2026-08-13 — session: hooks-test
- OUTCOME: `lane-guard` (PreToolUse) **enforces**, measured at the destination
  in 4 probes. `session-start` **delivers within budget** (1,243 B arrived,
  no truncation). `checkpoint-guard` (Stop) **fires but cannot pass and does
  not block** — 27/27 deliveries across 5 sessions at `exitCode 1`, and the
  harness labels that "non-blocking". Two defects filed below.

#### RESULTS — measured 2026-08-13, this session

| probe | attempt | result |
|---|---|---|
| A | `Edit` own-lane file, marker set | ALLOWED — correct |
| B | `Edit` foreign-claimed file | **BLOCKED**, exit 2, edit did not land |
| C | `Edit` own-lane file, marker EMPTY | **BLOCKED** — marker is load-bearing |
| D | `Write` foreign-claimed file | **BLOCKED** — matcher covers Write, not just Edit |
| E | `Bash` heredoc to foreign-claimed file | **WROTE THROUGH** — by design; the matcher is file-tools only |

- SessionStart, measured from the ARRIVING `attachment` record in this
  session's transcript (`2e6476cd`, line 3): `hookName=SessionStart:startup`,
  `exitCode=0`, `durationMs=1528`, **stdout 1,243 B**, no "Output too large"
  marker. The v3 rewrite holds against the ~2KB cap that made v1 ~5%
  functional. This is the destination-side check the 08-13 FORBIDDEN entry
  demands, not a terminal run.
- Probe C is the one worth remembering: with `.syndicate/.current-lane` empty
  the guard blocks the session's **own** files, and the message reads
  `Current lane: 'none'` — correct behaviour, confusing symptom. A session
  that opens a lane by hand-editing `lanes.md`, or one resumed after
  `/clear`, will hit this and look like a cross-lane collision.
- **Probe C is not hypothetical — it has already happened.** The marker did
  **not exist at all** before this session created it, so `none` was the repo's
  baseline. Session `ab30bcc8` line 186 carries a real block:
  `BLOCKED: tests/test_intelligence_state.py is claimed by OPEN lane
  'intelligence-state-red-baseline'. Current lane: 'none'.` — a session
  refused access to the file of the lane it was working (`#288`, the lane
  behind the `224 passed` baseline in `state.md`). `[measured 08-13]`
- **Closing a lane restores the failure state.** `/lane close` step 4 empties
  the marker, and an empty marker is the same lockout as a missing one. This
  session left it empty per the doc. Safe only because `/lane open` writes it
  — any session that edits a claimed file before opening a lane is locked out.
- METHOD NOTE — counting these from transcripts inflates badly. A first pass
  matching `BLOCKED:` across all transcripts returned **11**; the hook's own
  source and the counting scripts contain the string. Filtering to records
  with a real `tool_result` / `is_error` payload gives **4** (3 probes here,
  1 prior). Sibling of the substring-containment caveat already in
  `learnings.md`.

#### DEFECT 1 — `checkpoint-guard` can never take its pass branch
- `.syndicate/.last-checkpoint` **does not exist and never has**, so
  `[ -f "$MARKER" ]` at `checkpoint-guard.sh:17` is always false and the
  short-circuit is unreachable. Every Stop with a dirty tree warns.
- Measured across every transcript in this project: **27 Stop-hook deliveries,
  5 sessions, `exitCode 1` on all 27. Zero exit 0.** Meanwhile
  `.syndicate/log/2026-08-13.md` is 32,956 B — checkpoints ARE being written.
  The guard has been reporting "no checkpoint" at sessions that checkpointed.
- Second half of the defect: `DIRTY` counts the whole worktree — **65 files at
  baseline**, mostly pipeline output and other sessions' work. Even once the
  marker exists, a background artifact write after the checkpoint pushes
  `NEWEST` past `MARK` and the warning returns. The predicate is ~always true,
  so the alarm carries no information. Same shape as the `learnings.md`
  instrument-blindness entries.
- Fix: `/checkpoint` step 7 must actually `touch` the marker (it is in the
  command doc and was not happening), and the guard should compare against
  files the SESSION touched rather than the whole dirty tree.

#### DEFECT 2 — the Stop guard is advisory, not a gate
- Delivered stderr is prefixed **"Failed with non-blocking status code"**. Exit
  1 on Stop informs; it does not hold the session. The PreToolUse guard's
  exit 2 genuinely blocked (probe B). `CLAUDE.md` presents `/checkpoint` as an
  obligation — "if the session ends without a checkpoint, the work is
  considered lost" — and the enforcement behind it is a log line.
- Fix if a gate is wanted: exit 2. Decide deliberately; a blocking Stop hook
  that always fires (Defect 1) would wedge every session.

#### DEFECT 3 — nothing enforces the concurrent-lane cap
- `state.md` sets max concurrent OPEN lanes to **3** `[policy]`. This test
  opened lanes 3 and 4 and no check anywhere complained. `/lane open` step 3
  checks file collisions only; the cap is never counted.

- Probe fixtures (`reports/hooks_probe/`) and the temporary
  `hooks-probe-foreign` lane were deleted after the run. Nothing shipped;
  no code changed.

#### ORIGINAL LANE ENTRY (kept for the claim/hypothesis record)
- Goal: prove the three wired hooks ENFORCE at the destination, not just emit
  at the source. Named test, deliberately disposable — this lane exists to be
  the subject of its own experiment.
- Files (exclusive to this lane):
  - `.claude/hooks/lane-guard.py` — subject; not guarded by itself (the guard
    exempts `.claude/**` and `.syndicate/**`).
  - `.claude/hooks/checkpoint-guard.sh` — subject.
  - `.claude/hooks/session-start.sh` — subject.
  - `reports/hooks_probe/mine.txt` — probe file, THIS lane owns it. Expected
    ALLOW.
  - probe file owned by the temporary foreign lane below. Expected BLOCK.
- Hypothesis: `lane-guard.py` blocks a cross-lane edit through the harness
  (exit 2 on a `PreToolUse` match), and permits an edit whose claiming lane
  matches `.syndicate/.current-lane`.
- Falsification test: if the foreign-claimed Edit SUCCEEDS, the guard is inert
  in production regardless of what running it in a terminal shows. If the
  own-lane Edit is BLOCKED, the `.current-lane` marker is not being read and
  the guard is unusable (it would block every session's own work).
- Verification: both probes attempted as real `Edit` tool calls in this
  session, plus the SessionStart digest measured from the ARRIVING
  `attachment` record in this session's transcript — not from a terminal run.
  Per `learnings.md` 2026-08-13 (hook stdout cap): a terminal has no cap, so
  it can only ever confirm the emitter.
- Blocked by: none. No file overlap with `memory-guard-reclaimable` or
  `mlb-props-regen`.

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
- **Obligation CLOSED 13:20 CDT — all three are pushed.** They are on
  `origin/main` as `d16950b9` / `1e09fa9b` / `7c60d0f8`, rebuilt onto
  `d6188ca7` rather than pushed from local `main`: by then local `main` had
  been merged and built on by another session, so a plain push would have
  shipped **15 commits, 11 of them not this lane's** (`#419`/`#420`,
  `#417`/`#387`, a `.claude/settings.json` layer, test fixes). The pushed
  tip differs from `d6188ca7` in `render.yaml` only.
- Sync impact measured BEFORE pushing, not assumed: `would_revert: none`
  **and** `would_create: none` on all three services. A `blueprint_sync`
  would change zero live values and create zero keys.
- **No `blueprint_sync` fired.** Checked 12:55 and 13:14 CDT — all triggers
  `api`, services still live on their prior commits. `render.yaml` has been
  on origin since 11:33 with no sync. **That is a long window, not a
  guarantee**; `#284` documents a sync arriving with no user in it.
- **Still unverified: nothing has booted without these keys.** Web is on
  `936e2b47` from 08-12. The first deploy that picks up this blueprint is
  the real test. `MLB_LIVE_LENS_DIR` is the one that would have broken it
  had the grep-level pass been trusted over the call-graph trace.

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

### hooks-enforcement-wiring — DONE 2026-08-13 — **NO LANE WAS EVER OPENED**

Recorded retroactively for traceability, matching the `render-yaml-web-block-hygiene`
precedent. Harness-only work (`.claude/**`, `.gitignore`, `.gitattributes`);
collisions were checked against the OPEN lanes and were nil, but that was a
read, not a claim. Third session today to work `.claude/**` without a lane —
if that keeps happening, the protocol should say harness work is exempt rather
than have every session quietly decide it is.

- Outcome: three hooks wired and measured end-to-end. `session-start` v3
  delivers 1,243 B inside the ~2KB cap (v1 delivered ~5%); `lane-guard.py`
  rewritten to parse the real lanes.md shape and confirmed blocking through
  the harness; `checkpoint-guard.py` replaces the `.sh` and can now pass.
- Commits: `0d0b8931`, `0642cdf7`, `5b2ca320`. Pushed: `f6fec4f1` only.
- Full detail: `.syndicate/log/2026-08-13.md`, session entry at the tail.
