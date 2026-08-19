# state.md — sections archived 2026-08-19

Moved VERBATIM from `state.md` by lane `ledger-coherence-sweep`, under an
explicit instruction, when the file passed its 180,000-byte cap for the second
time in one evening. Nothing was summarised, rewritten or deleted; each subject
keeps a one-line keyed stub in `state.md` pointing here, so `state_key_check.py`
still sees one subject per section and no subject became unfindable.

SELECTED ON THIS FILE'S OWN STATED CRITERIA for what a collapse drops: dated
one-off measurement and deploy snapshots, records of lanes that are now closed
or released, and sections that already declared themselves archived or stale.
NO live subject's prose was compressed -- that is the subject owner's call and
was deliberately not taken here.

Subjects: board-intelligence-engine, fleet, football-board-defects, lane-guard-disclaimer-and-worktree-exemption-bugs, lane-state-carried, mlb-sim-artifacts-live, nfl-archived, oom-kills-census, refresh-worker-deploy-hold, sim-scheduling-blocker, sim-scheduling-deploy-lineage, wnba-fixture-identity, wnba-game-state, wnba-sweep-ownership-gate.

---

## [oom-kills-census] KILLS ARE EVENTS — there is now a tool, and a census `[measured 08-16 17:5xZ]`

`scripts/render_events.py` (`#442`, `f4627832` on `origin/main`, local tooling,
nothing deployed). **`d72a3f66` — the `_deploy_trigger` fix — was ORPHANED by a
stale-copy commit and re-committed 18:3xZ; verify with
`git show HEAD:scripts/render_events.py | grep -c build_started` (0 = the
reverted version is back).** Reads `/v1/services/<id>/events`. The 2026-08-15 FORBIDDEN
rule said a negative result about process death must come from the events API and
named `render_logs.py` as unable to give one; this is that tool.

    py -3 scripts/render_events.py --service <svc> --failures-only --since <ISO>

- **Paging is not optional.** 2026-08-14 CT returns **29 `oomKilled`** paged and
  **20** unpaged — a 31% undercount that reads as an answer. It prints the window
  it ACTUALLY covered, and an empty window triggers a positive control so
  "quiet" (exit 0) and "reader broken" (exit 2) cannot be confused.
- **refresh-worker `server_failed` 08-09..08-16 = 42 events, ALL 42 `oomKilled`**,
  zero evicted. 08-08:5, 08-13:4, **08-14:29**, 08-15:4, 08-16:0. Clusters
  **15:00–00:00 CT**.
- **live-odds-worker is a DIFFERENT failure: 20 `earlyExit`, ZERO OOM**, ~2.6/day,
  steady across 8 days, latest 08-16 11:38:05 CT. Cause and impact both
  **unmeasured** — `#444`, unowned. Do not merge with the refresh-worker work;
  they share only the word "failure".
- **A cap-touch is not a kill.** 08-16 05:09–10:09 CT read `container_memory_mb`
  **4096.0 MB = 100.0% of the 4 GiB cap** with **zero events** in the window
  (newest refresh-worker event was 01:01:34 CT). `memory.current` includes page
  cache; the ceiling was reached and nothing died.

## [board-intelligence-engine] BOARD / INTELLIGENCE ENGINE — structural facts, archived

Moved to `state_archive.md` 2026-08-15. Every figure in it is also in
`audit_2026-08-14_board_engine_SYNTHESIS.md` (verified by spot-checking
238,071 lines / 24 import cycles / 164 of 390 / 42 sites) — that audit is
the place to read it, and it carries the guard on its two shortlists.

## [nfl-archived] NFL — earlier closed work, archived

Moved to `state_archive.md` 2026-08-15. Closed work; the rules it records
generalise but are not current state. `#377`, `#425`, `#429`.

## [fleet] FLEET `[2026-08-18 02:1xZ — goes stale in minutes; re-read before deploying]`

    web               e5107913
    refresh-worker    00e9a49f
    live-odds-worker  cdaeaa58

## [lane-state-carried] LANE STATE RECORDS CARRIED THROUGH THE 2026-08-18 COLLAPSE

Sections that arrived from other lanes AFTER the collapse was written, so
they are neither in the collapsed file nor in the archive. Carried verbatim
rather than dropped. Several are dated snapshots and belong in `deploys.md`;
they stay here until their lane moves them.

## [sim-scheduling-deploy-lineage] STALE-TREE DEPLOY LINEAGE — the MECHANISM is real, the SEVERITY I first reported was wrong `[collapsed 2026-08-18 from two 2026-08-17 sections]`

**Largely superseded by the deploy-from-main rule** (see `[deploy-ownership]`):
`deploy_preflight.py` now returns `OFF_MAIN` for any target not contained in
`origin/main`, which is the class this incident belongs to. Kept because the
mechanism and the assertion generalise.

**THE MECHANISM, and it is real.** `7c2b1a17` (refresh-worker, live 00:24:01Z
2026-08-17) was built with its tree computed against `origin/main=7eb5fb28`
while its `-p` parent re-resolved to `40c3c44b` in a later git call. New parent,
old tree — a valid fast-forward, so `git push` accepted it with **no force and
no warning**. `origin/main` was never damaged; the divergence existed only on
the deployed service.

**THE SEVERITY WAS WRONG, and this is the part worth keeping.** I reported that
it "reverted the smaps-vs-cgroup reconciliation guard from the one service that
was OOM crash-looping, while `#449` was open" — in this file, in commits
`d9088741`/`7623a233`, and to the user. Measured:

    git diff --numstat 7c2b1a17 40c3c44b -- syndicate/features/shared/memory_observability.py
    -> +10  -49

A **refactor, not a deletion**. `7c2b1a17` carried the older
`_process_rss_anon_bytes()` implementation; main had replaced it with
cgroup-based accounting. `grep -c reconciles_within_pct` returns **1 on BOTH
trees — the guard was never absent.** The service was LAGGING main's improved
instrumentation, which `7623a233` fixed. Of the 239 deleted lines, 229 were
ledger and the 10 code lines were one side of a refactor.

**The tell I nearly walked past:** a `SMAPS_ANON` line emitting
`reconciles_within_pct` at 00:48:32Z — five minutes BEFORE my ship landed, so
emitted by `7c2b1a17` itself. A SHA lacking the field could not have printed it.
Found only because a follow-up query for the field's VALUES came back empty and
I chased the discrepancy instead of banking the watcher's "1 line" count.

**THE ASSERTION STILL STANDS** — ancestry checks, conflict-marker scans and the
`render.yaml` guard ALL PASSED on the broken commit:

    DEL=$(git diff --numstat "$MAIN" "$SHA" | awk '{d+=$2} END {print d+0}')
    [ "$DEL" -eq 0 ] || refuse

And resolve `origin/main` EXACTLY ONCE per build — never re-read a symbolic ref
in a later call. A plain re-merge does NOT fix a tree already poisoned this way:
the bad merge records the removals as intentional edits, so `merge-tree` sees
"live changed, main did not" and preserves them (`deletions=239` twice). Paths
must be restored from `main` explicitly, which is what `d9088741` did.

**THE LESSON, which is not the one I thought I was recording:** a `numstat`
deletion count tells you SIZE, never MEANING. I read "-10 code lines" and
supplied "a safety guard was removed" without opening the diff.

## [sim-scheduling-blocker] 2026-08-17 02:1xZ — VERIFIED (sim-scheduling): the primary goal has ONE blocker

**`#440`'s goal is "live sims for every sport". Every route to it ends at
refresh-worker/live-odds-worker CAPACITY, which is `#449`.** Not at engine work,
and not at wiring. Stated because three separate attempts tonight each arrived
here from a different direction.

**SOCCER'S LIVE SIM ALREADY EXISTS AND PUBLISHES.**
`soccer/features/live_lens.py` (`build_resume_state`, `apply_red_card_penalty`,
shipped `df96c3fb`) resumes a match from score/clock/red-cards every 60s and
writes home/away/draw win probabilities, over 2.5, BTTS, projected goals and
corners into `data/live/soccer_live_lens.json`. The board never reads it: three
named gates exclude soccer —
`attach_live_projections_for_sport` (`sport != "mlb"`),
`_LIVE_GAMELINE_SPORTS` (`{"mlb","wnba"}`),
`LIVE_LENS_SOURCES_BY_SPORT` (no soccer key).

**WHY WIRING IT TODAY WOULD NOT HELP.** The join releases an edge only above
`PRICEABLE_SIGMA=2.0` standard errors of `sqrt(p(1-p)/n)`:

    80 sims (soccer live tick)  -> 10.91 pp at p=.50, ~10.3 pp for its 3-WAY market
    120 (MLB live)              ->  8.98 pp
    300                         ->  5.74 pp

**AND 300 DOES NOT FIT.** live-odds-worker measured **1855.2 MB of 2048 (90.6%),
headroom 257-415 MB across 127 samples — at 80 sims**. Soccer runs FOUR Monte
Carlo passes per live match, 60s cadence, up to ~18 concurrent fixtures. Same
service where WNBA's builder once took **+1,062 MB in one step** and crash-looped
the container. **Do not set `SYNDICATE_SOCCER_LIVE_LENS_TICK_SIMULATIONS=300`.**

**Part 4 Phase 5 is SHIPPED** (`964c89a4`): `load_versioned_profile` is reached
from football, soccer and hockey. Calibration is now a file swap and rollback a
file revert. No-op until an artifact exists.

**`#449` is ONGOING** — kills at 01:07:16, 01:21:07, 01:46:59Z, cadence unbroken
by two full container replacements. Owned by `Worker memory watchdog logs`.

## [wnba-game-state] WNBA GAME-STATE AND FIXTURE COVERAGE — 2026-08-17 (lane `wnba-live-tier`)

- **The worker's WNBA `game_cards_<date>.csv` holds ONE fixture on a three-game
  slate.** Measured 2026-08-17 via `/api/ops/artifacts/export`:
  `game_cards_2026-08-16.csv` = 1 row (`game_id='1'`, POR@PHX);
  `cards_props_snapshot_2026-08-16.json` = 1 game. `IND@ATL` and `CHI@SEA` are
  absent. **`game_id` is a SEQUENTIAL INDEX, not an ESPN event id** — the two
  missing games carry numeric ESPN ids and come from a different source.
- **Chip builder, `is_active_today` and provider code are all EXONERATED by
  measurement.** The defect is the artifact, not any consumer of it.
- **The 207 unjoined WNBA grid rows are NOT a join failure** — two thirds of the
  slate has no `game_cards` row to join against. Supersedes the earlier reading.
- **This is the SAME FILE as the WNBA means-only distribution gap** (outstanding
  #3): `pred_margin`/`pred_total` are written there as means. One writer owns
  both defects.
- **A completed overtime game was published as in progress** until `cc0f7605`
  (live-odds-worker, 14:43:08Z): `_normalized_game_status` had no precedence
  between its live and terminal text checks, and `"Final/OT"` trips both.
  **Deployed, verified by content, behavioural test PENDING a finished OT game.**

## [wnba-fixture-identity] WNBA fixture identity + the sweep ownership gap - VERIFIED 2026-08-17

- **The stable WNBA fixture identity is the ESPN event id, already present in
  `schedule_2026.csv`** - verified same-instant against ESPN scoreboard; all
  three 2026-08-16 ids match. Pregame artifacts and the live lens share one key.
  `syndicate/features/shared/wnba_fixture_identity.py`, 40 tests.
- **`game_cards` coverage was 82/113 fixtures = 72.6%** over 41 dates. Fixed and
  proven on the real production artifact (1 row -> 3). **EFFECT IN PRODUCTION
  UNMEASURED** - deployed to both workers by CONTENT only.
- **Nothing on a cadence calls `refresh_wnba_oddsapi_props.main()`.**
  `MAIN_ENTRY` 0 hits over 8h. The GHA cron reads `RUN_FULL_PIPELINE` from
  `github.event.inputs`, which is empty on the `schedule` trigger, so full
  regeneration is manual-dispatch only; and `render.yaml:611` Phase-1 migration
  covered only NFL/NCAAF/NCAAB. **The WNBA full refresh was never re-homed.**
- **Both workers share ONE unnamespaced cadence marker** (identical
  `SYNDICATE_REFRESH_STATE_URL`, `KEY_PREFIX` absent on both). refresh-worker
  stamps it and sweeps four sports; **live-odds-worker swept ZERO across 30h**
  despite being the designated owner per `#129`. Fix committed (`20025cc4`),
  **NOT deployed**.
- **`SYNDICATE_ACTIVE_SPORTS` does not describe what a service does.** Both
  workers behave as the inverse of their env.
- ~~**`.syndicate/coordinator.id` is CORRECT, not stale** - two-id design.~~
  **SUPERSEDED 2026-08-18: the file is DELETED and the role is retired.** See
  "DEPLOY OWNERSHIP" above. The two-id design was a real fix to a real bug and
  still could not save the role — an id that survives a resume does not survive
  the session being archived.

## [wnba-sweep-ownership-gate] WNBA SWEEP OWNERSHIP GATE + PHASE 2 AUTORUN `[collapsed 2026-08-18 from three 2026-08-17/18 snapshots; newest reading wins]`

- **THE SWEEP GATE `20025cc4` IS DEPLOYED AND WORKING.** Partition live on
  live-odds-worker every tick; refresh-worker stopped sweeping mlb/soccer/wnba;
  **marker ownership transferred 23:55:40Z**. Confirmed by CONTENT on all four
  deploy branches — another lane's deploy carried it forward rather than
  reverting it.
- **`ODDS_SWEEP_OUTCOME` on live-odds-worker is STILL ZERO** against a hard-zero
  30h baseline. Grading lag vs dead launch is **UNDETERMINED** — do not report
  the gate as proven end-to-end on the partition line alone.
- **PHASE 2 AUTORUN HAS NEVER SHIPPED.** It EXISTS (`e65a5531`) and is TESTED
  (`c7494c6c`), but `wnba_autorun=0` on all four deploy branches, so its env keys
  on live-odds-worker (`=true`, `=7200`) are **INERT**. **When it ships it goes
  HOT IMMEDIATELY** — the flag is already on and `last_epoch=0` means the
  interval gate does not hold on the first run.
- **`phase="pregame"` is the memory-safety property**, pinned by test:
  live-odds-worker is 2GB, the WNBA refresh leg measures ~1.3–1.5GB RSS, and
  pregame excludes the sim leg.
- **live-odds-worker reports `psutil_unavailable:ImportError`**, so its memory
  instrumentation is DEGRADED — the very signal one would use to abort a Phase 2
  rollout. 293MB RSS / 1237MB headroom at 21:38Z is a reading from a degraded
  instrument.
- **`SYNDICATE_ACTIVE_SPORTS` does not describe what a service does.**
- **Pregame cadence: WNBA and MLB are ALREADY identical at 2h.** Only soccer
  differs (8h). The live path differs by a deliberate memory carve-out, not
  cadence. **`wnba_forced_through` fired 0 times in 24h on both services** — that
  carve-out is INERT and is not what gates WNBA.
- **`game_cards` coverage fix is DEPLOYED, EFFECT UNMEASURED**, and cannot be
  measured until Phase 2 is enabled.
- ~~`.syndicate/coordinator.id` is CORRECT, not stale.~~ **SUPERSEDED 2026-08-18:
  the file is DELETED and the role retired.** See `[deploy-ownership]`.
- ~~`lane-guard` cannot see the coordinator's sweep releases; a released lane
  still blocks every session.~~ **PARTLY SUPERSEDED 2026-08-18:** the disclaimer
  handling was reworked and `lane_identity_check.py` reports the ledger coherent.
  The released-lane case is **UNVERIFIED** — re-test before relying on it.
- ~~THE LOCAL `lanes.md` IS 123 KB / 27 HEADERS BEHIND THE COMMITTED ONE.~~
  **STALE 2026-08-18** — the coordinator it was handed to no longer exists, and
  the local ledger now reads coherent. Re-measure before re-raising.

**Three facts carried in these snapshots were NOT this subject** and have been
moved: `edge_vs_modelled_fair_pct` to `[published-shortlist]`, both soccer
findings to `[soccer]`. A dated "STATE" snapshot that sweeps up whatever was true
that hour is how this subject came to have three sections.

## [mlb-sim-artifacts-live] WEB `055dfc67` — THE FIVE MLB SIM ARTIFACTS ARE IN PRODUCTION `[2026-08-18 22:54:51Z]`

- **`POST /api/ops/artifacts/publish` 403 -> 200.** All five published and read
  back BY CONTENT: `arsenal` 0.57MB, `quality` 0.08MB, `batted_ball` 0.23MB,
  `pitch_splits` 0.23MB, `conditional_mix` 0.48MB.
- **THE SIM STILL CANNOT SEE THEM.** They are on WEB's disk; the sim reads
  WORKER disk. Live refresh-worker `00e9a49f` is **420 commits behind main** and
  **lacks `conditional_mix.py` and `pitch_codes.py` entirely.** A PARTIAL graft
  is worse than none: main's `build_roster.py` imports `conditional_mix`, so the
  call site without the module is an **ImportError in the roster build.**
- **`pattern=` MATCHES THE FULL RELATIVE PATH.** `pattern=conditional_mix_2026.json`
  returns `count: 0` **for a file that is present.** Use `*conditional_mix*` or
  the full path. **Every `count: 0` I reported on 2026-08-18 came from this
  malformed query and proved NOTHING** — the 403 carried the whole argument.
- **`scripts/render_deploy.py --service <s> --commit <sha>`** is the deploy
  entrypoint. Raw `curl` POSTs to `/v1/services/.../deploys` are refused.
- **WEB PREFLIGHT CAN NEVER CLEAR: `psutil` is NOT INSTALLED on web**, so the
  `ALL_PROCESS_MEMORY` emitter cannot run there. The sampler is HEALTHY on
  refresh-worker (age 17s, CLEAR). **This is web-only and a missing dependency —
  I earlier claimed it was global and architectural, and that was wrong.**
  Install `psutil` on web and the break-glass stops being needed.
- **Residual:** `055dfc67` is off main, so a future off-main web deploy drops
  these six lines. They are on main in `c2030c72`.

## [refresh-worker-deploy-hold] refresh-worker: THE OOM DEPLOY HOLD IS ORPHANED. Branch READY, NOT DEPLOYED. `[2026-08-18]`

**The hold is VOID — its owner is dead, and the roster lies about it.**

    "Oom band full report"  3a27ad02
      isRunning:      true          <- the flag
      lastActivityAt: 2026-08-17T05:15:58Z   <- 43 HOURS earlier

`lanes.md:51` already flagged it "flagged running (stale 40h)". **The orphan
sweep skipped it precisely BECAUSE it claims to be running** — the sweep releases
lanes whose session is ARCHIVED, and this one is neither archived nor alive.
**A stale-but-"running" session is invisible to both checks.** `lanes.md:235`
still shows the lane OPEN and `:611` still cites its deploy hold; both are stale.
`[user decision 2026-08-18: the lane is dead, treat the hold as void]`

**READY, PUSHED, NOT DEPLOYED:** `deploy/worker-sim-engine-20260818` = `a1235755`
- parent **`00e9a49f`** — the LIVE worker, not main.
- **14 files, +1,478 / -22.** Whole `sim_engine` tree + `artifact_publisher.py`
  + `run_mlb_daily_sim_job.py`.
- **Import-checked in isolation**: `simulate`, `build_roster`, `conditional_mix`,
  `pitch_codes`, `pull_season_artifacts` all import; `ST -> PitchType.SL`.
- **Verified no overlap**: the worker's **63 commits main lacks** (soccer polls,
  ownership gates, WNBA) touch `syndicate/features` + tests, **NOT** `sim_engine`
  / `artifact_publisher` / the sim job. The graft overwrites nothing unique to
  the worker — and **deploying main instead would REVERT all 63.**

**WHY IT DID NOT SHIP — a live blocker, not a policy one:** `HOLD: 9 jobs in
flight`, including `run_mlb_daily_sim_job.py` mid-run with `daily_update.py` and
multiprocessing children. **A deploy kills a running MLB sim.** Unlike web's
vacuous preflight, refresh-worker's gate WORKS and this is it working.

**BEFORE DEPLOYING `a1235755`, READ THIS:**
1. **It does NOT carry the `edge_basis` fix** another lane left on main marked
   "whoever next deploys refresh-worker carries it" (`lanes.md:613`). Shipping
   mine as-is silently skips theirs and pushes the worker FURTHER from main.
2. **Its parent is the CURRENT live SHA.** If the worker moves first, RE-CUT —
   the same staleness that invalidated my first web branch tonight.
3. **Better end-state: get the worker onto main.** That carries `edge_basis`, my
   engine set, and the other 420 commits at once, and stops the divergence
   instead of deepening it. Bigger change, needs its own preflight.

**verify once deployed:** a sim run logs `season_artifacts_pulled=N`, then
`sim_input_checklist.py --publish` shows `conditional_arsenal` > 0% with source
`statcast_conditional_mix`. **Needs a ROSTER REBUILD** — `--use-roster-artifacts`
defaults on and reuses profiles serialised before these fields existed.

### MERGE ASSESSMENT — getting refresh-worker onto main is a REAL TWO-WAY MERGE `[2026-08-18]`

**Measured, so the next session starts from numbers rather than rediscovering
this.** The correct end-state (one worker deploy from main carries everything and
STOPS the divergence) is confirmed correct — and it is **not a quick action.**

    merge base     aa60d7569
    main side      420 commits
    worker side     63 commits   (live worker 00e9a49f)
    merge-tree     CONFLICTS -- 7 conflict / changed-in-both markers

**BOTH SIDES HAVE MOVED ON THE SAME FILES.** Changed on main AND on the worker
since the base:

    pipeline/intelligence_state.py
    syndicate/features/shared/board_enrichment.py
    syndicate/features/shared/game_shape.py
    syndicate/features/shared/intelligence_evaluation.py
    syndicate/features/shared/live_gameline_join.py    <- ledger already records
                                                          this as a CONTESTED file
    syndicate/features/shared/live_gameline_ledger.py
    syndicate/features/shared/book_grid_artifact.py
    scripts/poll_soccer_live_state.py
    scripts/refresh_wnba_oddsapi_props.py
    scripts/mlb_leverage_index.py

**This needs SEMANTIC resolution, not a merge driver** — deciding whose soccer
poller, whose gameline join, whose board enrichment is right, in files owned by
OTHER lanes. **A wrong resolution does not fail loudly**; it ships a half-merged
board or intelligence path to the service that runs the daily pipeline.

**NOT ATTEMPTED, deliberately.** Doing it would have meant guessing at other
sessions' intent in files I had not read. Recorded instead.

**Sequence when someone takes it:**
1. an owner for the merge; read the lane ledger for `live_gameline_*`,
   `board_enrichment`, `intelligence_state` before resolving anything;
2. land on main, tests green;
3. ONE worker deploy from main then carries **all** of it — the 63 soccer/WNBA
   commits, `edge_basis` (`lanes.md:613`), and the `#440` engine set.

**Until then the worker stays off main and every worker deploy is an off-main
graft that must be re-cut against the live SHA.** That is the cost of deferring,
and it compounds: each graft pushes the worker further from main and makes this
merge larger.

## [lane-guard-disclaimer-and-worktree-exemption-bugs] TWO REAL BUGS FOUND IN `lane-guard.py`, NEITHER FIXED `[found 2026-08-18]`

- **Bug 1:** the `.syndicate`/`.claude` exemption (`rel.startswith(".syndicate")`)
  is computed relative to `CLAUDE_PROJECT_DIR` (the primary tree). Editing the
  same logical file via a `session_worktree.py` worktree produces a
  `../../../tmp/...`-style relative path that never starts with `.syndicate`,
  so the exemption silently fails to apply and the file gets claim-checked
  like ordinary code.
- **Bug 2:** in `_claims()`, the initial `- Files:` line's content goes
  straight to `_paths_in()` without `_claimable_prefix()` first — unlike
  continuation lines, which do get it. A same-line disclaimer clause after the
  path list (e.g. "Collision check: ... grepped `lanes.md`, clean.") is read
  as claims, not prose. **Live instance:** `basketball-model-owner` appears to
  claim `lanes.md` itself, purely from a collision-check aside on its own
  Files line.
- Together these blocked a routine worktree edit to `.syndicate/lanes.md`
  this session (worked around by landing via a different session's sweep,
  not by fixing the guard). **NOT FIXED** — a design was drafted
  (`.claimable_prefix()` applied to the initial Files line too; exemption
  check based on path substring rather than root-relative prefix) but never
  written to a file. Regression tests belong in
  `tests/test_lane_guard_files_forms.py`, which already has fixture coverage
  that happens not to trigger bug 2 (`PLAIN_WRAPPED`'s first line has no
  colon, so it sidesteps the bug by coincidence, not by testing against it).

## [football-board-defects] FOOTBALL BOARDS — THREE DEFECTS SHIPPED AND MEASURED `[2026-08-18/19]`

- **NCAAF served 16 of 51.** Three hardcoded 16-caps; 16 is the NFL's natural
  slate, correct there and wrong for a 50-60 game sport. Now 80. Post-deploy
  51/49/57/56/56/66, week 1 matching CFBD's independent count exactly.
- **Both NFL boards served no spread or total.** `total_mean`/`margin_mean` 0% on
  16/16; `_shared_predictions` never read `sim.periods.full`. Now 100%.
- **Preseason projections were 13.1 days stale**, invisible until
  `projection_provenance` was published.
