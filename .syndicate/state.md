# Syndicate — Verified System State

> Overwrite lines here as facts change. Do not stack contradictions.
> Every line carries an evidence tag and a date. Untagged lines are invalid.
> **Seeded 2026-08-13 from prior session notes. Lines marked `[unverified]`
> must be confirmed against the dashboard before anyone relies on them.**

## Config

- Max concurrent open lanes: **3** `[policy]`
- Repo tip: `478edd78`, `origin/main` at the same commit. Supersedes the
  `93fc7cae` line. `[from-git 08-13]`
- Deployed SHA: **three different commits, none of them the repo tip.**
  Read from `/v1/services/<id>/deploys` at 08-13 **11:56** CDT; all three
  `status=live`, `trigger=api`, nothing in flight. `[measured 08-13]`
  - `syndicate` (web) — `936e2b47`, live since **08-12 21:44 CDT**.
  - `refresh-worker` — `448e1816`, live since **08-13 10:27 CDT**.
  - `live-odds-worker` — `95effcfa`, live since **08-13 11:36 CDT**.
- These go stale in minutes, not days. live-odds-worker moved
  `2caa8eac` → `95effcfa` inside one 40-minute session. Re-read before use.
  `[measured 08-13]`
- **The web service is the stale one.** It has not been redeployed since
  last night, so any web-path `.py` fix committed today is on `main` and is
  **not running**. Do not read a web-route symptom as evidence about
  today's code without checking `936e2b47` first. `[measured 08-13]`
- Because `autoDeploy = no`, the repo tip is an upper bound on every
  service and never a reading of any of them. Re-read per service; do not
  reuse the SHAs above once a deploy fires. `[policy]`

## `render.yaml` env hygiene (`#96` family)

- The web `envVars:` list is anchored `&shared_render_env_vars` but the alias
  **is never referenced anywhere in the file** — nothing was ever shared, so
  worker-only keys accumulated on web for months. `[from-code 08-13]`
- Web block audited and cut **62 → 52 entries** (`606a2f28`, `054b2306`,
  `cc2e1803`, `e8611888`). Every removed key was already declared on both
  workers and is unchanged there. `[from-code 08-13]`
- **Three duplicate declarations existed, one per service** (web and
  live-odds-worker: `SYNDICATE_WNBA_SOURCE_APP_FALLBACK`; refresh-worker:
  `SYNDICATE_BOOTSTRAP_ON_START`). All same-value, all deduped. Zero
  duplicates on any service now. `[measured 08-13]`
- A `blueprint_sync` **upserts declared keys and leaves live-only keys
  alone** — it does NOT replace the whole env block. So removing a
  declaration does not remove the live value; it reclassifies it as
  undeclared. This is narrower than CLAUDE.md's warning implies.
  `[measured — see scripts/audit_blueprint_drift.py header]`
- Blueprint drift: **0 values a sync would revert**, all three services.
  Snapshot only — one env-API change makes it non-zero. `[measured 08-13 11:52]`

## Both workers publish over the internal hostname

- `SYNDICATE_WEB_PUBLISH_URL='http://syndicate-an21:10000'` on refresh-worker
  and live-odds-worker; **not set on web**, correctly. Confirmed in config and
  in the running process — 20 `PUBLISH_OK` lines on live-odds-worker at
  11:17:11 CDT all carry the internal URL. This extends the closed cutover
  lane, which had evidence from refresh-worker only. `[measured 08-13]`

## Keyvalue store (`#324`)

- Instance is **256MB, `allkeys-lru`**, shared by web + both workers. Cannot be
  upgraded. `[measured 08-10]`
- `reports/migration_runs/**` no longer reaches the store: `_keyvalue_backed()`
  in `refresh_state_store.py` excludes it from all seven path-scoped IO
  functions. `refresh_status/` and `live_refresh_loop/` are DELIBERATELY still
  stored — `refresh_status/latest/` is read cross-service and both together were
  only 4.4MB. `[code 08-10]`
- Usage went **246MB / 96.1% → 39.87MB / 15.9%**, with `evicted_keys` frozen at
  38,865 across a 36-minute window. **Re-measure before relying on this: it is
  2–3 days old.** `[measured 08-10]`
- `/api/ops/keyvalue/usage` reports **allocator bytes** (`MEMORY USAGE`,
  jemalloc size classes), not logical length. Correct unit for "is the instance
  full"; deltas are block-quantised, so do not quote them to more precision than
  ~4KB. `[measured 08-10]`

## Board transport (`#317`, `#322`)

- Board snapshot and `query_state_cache` are **compacted (aliases) then
  zlib+base64 compressed** before the keyvalue write. 31.4MB → 812KB, 17.7× on
  real candidate data. Top-level scalars are left uncompressed on purpose so
  `_read_state_payload`'s freshness comparison still works. `[measured 08-10]`
- **Any reader of these artifacts must call `expand_persisted_state` first.** A
  raw read returns an envelope that still passes `isinstance(dict)`, so it
  degrades silently rather than raising. This has already bitten three ops
  diagnostics (`#320`) and one more (`#338`). `[code 08-11]`

## Services

- `syndicate` — web service. ~333 GB outbound in Aug, almost entirely HTTP
  responses; only 207 MB service-initiated. `[measured 08-12]`
- `live-odds-worker` — background worker, 1 CPU / 2 GB, 50 GB persistent
  disk. Publishes a single date, ~30–60 publishes/min. `[measured 08-12]`
- `refresh-worker` — background worker. Multi-date sweep, ~30–60
  publishes/min. `[measured 08-12]`
- **Soccer sims are ENABLED and running.** `SYNDICATE_ENABLE_SOCCER_WEEKLY_REFRESH_AUTORUN='true'`
  live; all three sim fixes are ancestors of the deployed commit; a 20m13s
  `build_soccer_artifacts` process was observed. Any belief that they are off is
  wrong. `[measured 08-10]`
- **One soccer sim job = one league-date** (`#282`, deployed). Verified by 8
  `SOCCER_UNIT_LAUNCHED` lines completing a full 4-unit rotation, `due`
  counting 4→3→2→1, spacing = `interval // unit_count`. `[measured 08-10]`
- **refresh-worker's active-job cap now actually fires** (`#311`, deployed) —
  `JOB_CAP_THROTTLED active=1 max=1 source=process_and_manifest`, the first time
  in this system's history. `SYNDICATE_REFRESH_WORKER_MAX_ACTIVE_JOBS` is unset
  on both workers, so the cap is **1**; raising it weakens the bound
  proportionally and nothing at the point of change says so. `[measured 08-10]`

## Platform constraints

- Hosted on Render. `[fact]`
- Artifacts stored on **Render persistent disks**, not S3/GCS. This forces
  single-instance services and stop-then-start deploys with downtime.
  `[from-code 08-12]`
- Render April 2026 pricing: included bandwidth cut, $0.15/GB overage.
  `[fact]`
- Included pipeline/build minutes exceeded in Aug: 1,549 of 1,000.
  `[measured 08-12]`

## Session harness — what the hooks actually enforce

- **`lane-guard.py` (PreToolUse) enforces.** Blocks `Edit` and `Write` against
  a file claimed by another OPEN lane (exit 2, edit does not land); allows the
  same file when `.syndicate/.current-lane` names the claiming lane.
  `[measured 08-13, 4 probes through the harness]`
- **With `.current-lane` empty or missing it blocks your OWN lane's files**,
  reporting `Current lane: 'none'`. Correct by design, confusing symptom — a
  session that hand-edits `lanes.md` instead of running `/lane` locks itself
  out. **The marker did not exist at all before 08-13**, so `none` was the
  baseline, and it has already bitten once: session `ab30bcc8` was refused
  `tests/test_intelligence_state.py`, claimed by the very lane it was working
  (`intelligence-state-red-baseline`). `/lane close` empties the marker, which
  restores that state — only `/lane open` clears it. `[measured 08-13]`
- **`Bash` bypasses it entirely** — the matcher is `Edit|Write|MultiEdit|
  NotebookEdit`. The guard bounds the file tools, not the session.
  `[measured 08-13]`
- **`session-start.sh` delivers 1,243 B**, `exitCode=0`, no truncation marker,
  measured from the arriving `attachment` record (session `2e6476cd`, line 3).
  Inside the ~2KB cap that left v1 ~5% functional. `[measured 08-13]`
- **`checkpoint-guard.sh` (Stop) has never passed and cannot.**
  `.syndicate/.last-checkpoint` did not exist until this session, so line 17's
  pass branch was unreachable: **27 Stop deliveries, 5 sessions, exit 1 on all
  27, zero exit 0** — while checkpoints were demonstrably being written.
  `[measured 08-13]`
- **Exit 1 on Stop is advisory.** Delivered stderr carries "Failed with
  non-blocking status code". `/checkpoint` is documented as an obligation and
  is enforced by a log line. A gate would need exit 2 — and must not be raised
  to exit 2 until the always-fires defect is fixed, or it wedges every session.
  `[measured 08-13]`
- Its `DIRTY` count is the **whole worktree**, not the session: 64 dirty files
  at this checkpoint, 1 of them this session's. `[measured 08-13]`
- **The 3-lane cap in `## Config` is policy with no enforcement.** Four OPEN
  lanes ran this session unchallenged; `/lane open` checks file collisions
  only and never counts. `[measured 08-13]`

## Test baselines

- `tests/test_intelligence_state.py` is **GREEN: 224 passed, 10 subtests
  passed, 0 failed** on `bd227fa3`. It had carried a standing
  `4 failed, 220 passed` on a clean checkout; `#288` closed 2026-08-13, all
  four repaired in the test with **zero source changes**. **A failure in this
  file is now yours** — it is no longer safe to assume standing noise, which is
  the whole point of having fixed it. `[measured 08-13]`
- It costs **~15 minutes** (891s red, 902s green), so it is not a quick check.
  The four historically-broken tests run alone in ~35s and are the cheap
  smoke: `test_build_candidate_pool_does_not_embed_full_odds_history_payload`,
  `test_query_endpoint_default_unchanged_when_combined_flag_disabled`,
  `test_read_latest_response_syncs_shared_backend_state`,
  `test_background_loop_survives_board_window_watch_exception`.
  `[measured 08-13]`
- Two of those four are pinned against SOURCE by mutation, not just by green:
  re-embedding `odds_history` on the per-sport pool entry, or removing the
  sport-scoped `_latest_key` promotion skip, each turns the right test red.
  `[measured 08-13]`
- **Green here says nothing about `tests/test_intelligence.py`.** `#288`'s
  record notes two query failures and a blotter failure in other files; those
  were never in its scope and were **not re-measured** on 08-13.
  `[unverified 08-13]`

## Board live tier (layer1-live-tier lane)

- **The live prop join was matching 0 of 1385 rows** — keyed on `market`, which
  is a display GROUPING (`hitter_props` covered 4 markets). Fixed `#412`;
  control on one production snapshot + board: 0 -> 41 rows. `[measured 08-13]`
- **Board game state is stamped from the live-lens snapshot, not the cached raw
  feed** (`#413`). `_mlb_feed_live_payload` consults the cached feed for
  PRESENCE only, never freshness, so a game froze at whenever it was first
  captured. Override measured `rows_corrected 210, live->final 210`.
  `[measured 08-13]`
- **No live GAME-LINE projection exists.** `predictions.full` in the live-lens
  snapshot is the PREGAME sim — all 6 final games carried pregame win
  probabilities (0.489 on a completed game). Only PROPS have a live tier.
  `[measured 08-13]`
- **`liveModelProbOver` reaches the published snapshot's keyspace**, value null
  so far. Transport is not the break. `[measured 08-13]`
- **`rows_live_edged` is 0 on every build to date**, and the flat counter cannot
  be read while a slate is mostly final — final props come from a registry path
  that never computes a live probability. `e054e19f` splits by game state; the
  `live` bucket has **never been observed against a live slate**.
  `[unverified 08-13]`
- **Web's `/mlb/api/live-lens` cannot observe the live Monte Carlo**:
  `simContextAvailable: False` on all games, `gameLens source: ABSENT` on all
  lanes. Do not verify live-sim work through it. `[measured 08-13]`

### Sim execution and the board build

- **MLB board build: 688.7 / 719.0 / 852.5 / 1125.2 / 1157.3 s** over five
  builds at 102–206 candidates — **spread 1.68×, no code change**. Judge any
  future delta against this series, not against a single earlier build.
  Morning builds are ~4.4s at 16 candidates: the cost tracks time of day.
  `[measured 08-13]`
- **An orphaned MLB sim now records a CAUSE**, not just a death:
  `MLB_DAILY_SIM_ORPHANED state=killed_by_restart` observed `00:24:36` and
  `23:00:18`. Only the tick owner writes it. `[measured 08-13]`
- **NFL projections were written to the ephemeral checkout** — the generator
  used `/opt/render/project/src/data/...` while the guard read
  `/opt/render/project/data/...`, so ~90 completed sims/day were discarded.
  Guard and writer now share `nfl_artifact_output_root()`. `[measured 08-13]`
- **The deploy sim-gate refuses in flight, not only in theory**: three polls of
  `HOLD: 3 job(s) in flight`, then `CLEAR`, then deploy. `[measured 08-13]`
- **Where the board-build cost lives is NOT established.** The row loop is
  exonerated only as far as an instrument that could not distinguish rows from
  the tail — see `learnings.md`. Leading candidate is per-candidate scanning in
  the tail; unmeasured. `[unverified 08-13]`

## Open problems

- **Something allocates 493–878MB in-process on refresh-worker and nothing knows
  what (`#327` RESIDUAL).** Released within ~72s, arriving 11–42 min apart, peak
  observed at container **3459.1MB = 84% of a 4096MB cap**.
  `post_mlb_sim_tick` is a **BYSTANDER** — all five sub-features report
  `launched=false` at every peak, so the stage name marks the observer, not the
  allocator. Five causes eliminated. **Strongest lead:** both hot-artifact
  operations allocate 300–717MB while transferring *nothing* (`pub=0`,
  `pulled=0`), so the cost is in the export payload, not the transfer — but
  **only counts have been measured, never bytes.** `[measured 08-10]`
- **`#312`'s `sync: false` protection is on `main` and live on NOTHING**, and
  the `blueprint_sync` mechanism remains **untested** — the only deploy carrying
  it was cancelled, so the mechanism was never offered its input. That is the
  wrong experiment, not a null result. `[measured 08-10]`

- **The L2 board freezes silently and only a restart clears it (`#417`).**
  `MEMORY_GUARD_ABORT stage=pre_source_state_fingerprint` fired 300 consecutive
  cycles `09:29:27Z–14:54:44Z`, aborting before the fingerprint, so no
  shortlist was built or written for **4h12m**. Not a leak: `anon` drifted
  **+18.9 MB** across all 300 samples. The guard
  (`_MIN_SAFE_MEMORY_HEADROOM_BYTES = 1900`) credits only `inactive_file`, so
  when the kernel promoted ~243 MB to `active_file` at ~11:02, effective
  headroom fell 1877 → 1643 **while total memory in use fell 3120 → 2705 MB**.
  Sibling of `#387`, different guard. `[measured 08-13]`
- **Expected to recur** as the worker re-warms — the 14:56 restart is the only
  thing that cleared it. `[unverified 08-13]`
- `live-odds-worker` disk usage climbing steadily, ~20% → ~40% of 50 GB
  over two weeks. Something accumulates and is not cleaned up.
  **Not yet diagnosed.** `[measured 08-12]`
- Chronic instance restarts / failures across the fortnight, instance count
  dropping to 0. Pegged CPU, climbing memory. **Cause unconfirmed — may or
  may not be downstream of the egress issue.** `[from-logs 08-12]`

## Resolved

- Aug egress ~2.1 TB outbound vs 25 GB included; ~1.79 TB service-initiated.
  Root cause: `SYNDICATE_WEB_PUBLISH_URL` pointed at the web service's
  **public** URL, so workers POSTed every artifact out to the public
  internet and back in. `[from-code 08-12]`
- Secondary cause: a checksum was computed and sent but never compared, so
  unchanged artifacts re-uploaded in full every sweep. `[from-code 08-12]`
- **Cutover is live and durable.** Every `PUBLISH_OK` on refresh-worker at
  `14:54:11Z` carries `url=http://syndicate-an21:10000/...`, and `render.yaml`
  holds the internal hostname for both workers, so a `blueprint_sync`
  reinforces it rather than reverting it. `[measured 08-13]`
- `#401`'s maintenance runner is **not** broken: 15.62h elapsed against an
  86400s interval, the env override unset on both workers. Next run expected
  ~`23:38:06Z`. `[measured 08-13]`
