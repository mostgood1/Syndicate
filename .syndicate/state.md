# Syndicate — Verified System State

> Overwrite lines here as facts change. Do not stack contradictions.
> Every line carries an evidence tag and a date. Untagged lines are invalid.
> **Seeded 2026-08-13 from prior session notes. Lines marked `[unverified]`
> must be confirmed against the dashboard before anyone relies on them.**

## Config

- Max concurrent open lanes: **3** `[policy]`
- Repo tip: local `main` `c506eb2a`, **25 ahead / 8 behind `origin/main`**
  (`461c0df0`). The two have diverged and both ends move every few minutes —
  re-read, do not reuse these. `[from-git 08-13 15:1x]`
- **CORRECTION: a push from this checkout does NOT carry a `render.yaml`
  change, and the previous warning here that it fires `blueprint_sync` was
  wrong.** The three commits it named (`d16950b9`, `1e09fa9b`, `7c60d0f8`)
  are **patch-equivalent to commits already on `origin`** — another session
  re-landed them as `d16950b9`/`1e09fa9b`/`7c60d0f8`. `git cherry origin/main
  main` marks all three `-`, and `git diff origin/main..main -- render.yaml`
  is **empty** (web block 52 keys on both sides). Verified immediately before
  pushing `461c0df0`. `[measured 08-13 15:1x]`
- Still true, and the reason the warning existed: **`git push` from this
  checkout is not scoped to your own commits.** Read
  `git log origin/main..HEAD` before pushing. When it carries other lanes'
  work, cherry-pick onto `origin/main` in a throwaway worktree instead —
  used three times on 08-13 (`f6fec4f1`, `03073270`, `461c0df0`), twice
  because another session had uncommitted files the merge would have
  clobbered. `[from-git 08-13]`
- Repo tip: local `main` `5cdf45b6`, **20 ahead / 6 behind `origin/main`**
  (`571f774b`). The two have diverged. **The `session-start.sh` clause here is
  now stale** — that file was committed in `0634e7bb` and the worktree is clean
  of it; it blocks nothing. What a push DOES carry is 3 unpushed `render.yaml`
  commits (`d16950b9`, `1e09fa9b`, `7c60d0f8`), which fire `blueprint_sync`.
  `git push` from this checkout is not scoped to your own commits — read
  `git log origin/main..HEAD` first. Hook work was landed by cherry-picking
  onto `origin/main` in a throwaway worktree to avoid carrying them
  (`f6fec4f1`). Supersedes the `478edd78` line. `[from-git 08-13 14:5x]`
- Deployed SHA: **three different commits, none of them the repo tip.**
  refresh-worker re-read at 08-13 **13:05** CDT; the other two at **11:56**.
  All `status=live`, `trigger=api`. `[measured 08-13]`
  - `syndicate` (web) — `936e2b47`, live since **08-12 21:44 CDT**.
  - `refresh-worker` — **`03073270`**, live since **08-13 13:05 CDT**
    (deploy `dep-d9v0b8bncjis73an78hg`). Carries the `#417`/`#387` memory
    guard fix. Supersedes `448e1816`.
  - `live-odds-worker` — `95effcfa`, live since **08-13 11:36 CDT**.
- Deployed SHA: **re-read 2026-08-13 23:28Z, and they are NOT all equal.**
  `[measured 08-13 23:28Z]`
  - `syndicate` (web) — **`d4bb29b5`**, live since **23:03:32Z**. Supersedes
    `936e2b47`; web is no longer the stale service.
  - `refresh-worker` — **`d4bb29b5`**, live since **22:59:14Z**. Supersedes
    `03073270`.
  - `live-odds-worker` — **still `95effcfa`.** Its `d4bb29b5` deploy has been
    `build_in_progress` since 22:55:27Z — 33+ minutes against a normal 4. The
    old instance keeps serving (Render does not swap until a build succeeds)
    and is healthy. **It does NOT have the `#417` memory fix.** Low impact: the
    guard has never fired on that service (all refusal tokens zero over ~6
    days).
  - **A fired deploy is not a landed deploy.** All three were reported deployed
    tonight on the strength of the POST responses; one was false for 33+
    minutes. Check `status=live` AND the commit, never the 201.

- These go stale in minutes, not days. live-odds-worker moved
  `2caa8eac` → `95effcfa` inside one 40-minute session. Re-read before use.
  `[measured 08-13]`
- **The web service is the stale one.** It has not been redeployed since
  last night, so any web-path `.py` fix committed today is on `main` and is
  **not running**. Do not read a web-route symptom as evidence about
  today's code without checking `936e2b47` first. `[measured 08-13]`
- **Web is 47 commits behind — do not quote that number.** Only **14** touch
  production `.py`; the rest are ledger, docs and tests. Real delta: **7 files,
  785 insertions**, of which `intelligence.py`, `home.py`,
  `live_projection_join.py` and `flask_frontend.py` are web-path. See `#422`.
  `[measured 08-13 14:44]`
- **"On origin" is not "in production."** Web's LIVE service carries **73**
  env vars; `render.yaml` on origin declares **52**. The web env-block audit
  is pushed and **not reflected on the live service**. Read
  `/v1/services/<id>/env-vars` before recording any config change as shipped.
  `[measured 08-13 14:44]`
- **SELF-CORRECTION to the line above, same session.** It originally read
  "a future sync carries a queued, unannounced 21-key reduction". **That is
  wrong** and contradicted the measured sync semantics recorded further down
  this file: a sync **upserts declared keys and leaves live-only keys alone**
  (2026-08-08, refresh-worker went 92 → 93 while the blueprint declared 84;
  a full replace would have driven it to 84). Removing a declaration
  therefore **never removes the live value** — it only reclassifies the key
  as undeclared. So the 21-key gap is not queued work; it is 21 live-only
  keys that no sync will ever clear. **The web env-block audit cannot take
  effect on a live service at all** unless someone deletes those keys through
  the env API. Anyone wanting the audit to mean something in production has
  to do that deliberately. `[measured 08-13 15:1x — see
  scripts/audit_blueprint_drift.py header]`
- **Web does not run the loops that call `memory_headroom_snapshot`.** Live env:
  `SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP=false`,
  `SYNDICATE_ENABLE_LIVE_ODDS_REFRESH_LOOP=false`,
  `MLB_ENABLE_LIVE_LENS_LOOP=false`. So the `#417` guard change is inert there —
  which matters because web is a **2GB** container with an OOM history and the
  new formula is more permissive. Re-raise that concern if any flag flips.
  `[measured 08-13 14:44]`
- **`live-odds-worker` does NOT carry the `#417` fix and DOES run the guard**
  (odds-refresh and soccer/WNBA live-lens gates). The unstable `active_file`
  arithmetic is still live on that service. Its own deploy, its own
  measurement. `[measured 08-13 14:44]`
- Because `autoDeploy = no`, the repo tip is an upper bound on every
  service and never a reading of any of them. Re-read per service; do not
  reuse the SHAs above once a deploy fires. `[policy]`

## Ledger SHA references

- **69 references across four ledger files were rewritten 08-13 from local
  SHAs to their `origin/main` equivalents.** They named commits that existed
  only in one clone, because this repo's standard push path (cherry-pick onto
  `origin/main` in a throwaway worktree) mints a new SHA. After the pass: 168
  refs resolve on origin, 0 fabricated. `[measured 08-13]`
- **Local-only SHAs, in two kinds — the distinction matters.** `[measured 08-13]`
  - *Will never land, do not wait for them:* `3042c5bc` (checkpoint-guard
    log-witness — SUPERSEDED by the adopted transcript-witness design, and
    replaying it would regress `checkpoint-guard.py`); `a3f9ed97` (a merge
    whose content is already upstream — no patch to cherry-pick).
  - *Pending, blocked on a conflict needing their author's judgment:*
    `a0c5e7af` (collides in `docs/ai_context/todo.md`); `bd227fa3` (collides
    in `.syndicate/lanes.md`, and the change is an `OPEN`→`CLOSED` status
    flip — union-resolving it would stack contradictory headers and invent a
    phantom lane).
  - *Landed, and rewritten throughout this ledger to their origin SHAs:*
    bf8833e9→`8a0d49d8`, 841228d9→`d4bb29b5` (old SHAs deliberately
    unbackticked so this entry does not inflate the check). **Pushing does not make the
    old SHA resolve** — the cherry-pick mints a new one, so the reference has
    to be rewritten too. That step was missed the first time and is the whole
    reason this list exists.
- Short session ids are indistinguishable from short SHAs. Every one in the
  ledger is prefixed `session` — keep it that way. `[policy]`

## refresh-worker memory — `#417` CLOSED, `#423` OPEN

- **`#417`'s guard fix is VERIFIED and STAYS.** The live abort line carries
  `'basis': 'unreclaimable'` (proving the new path executes) with
  `active_file`/`inactive_file` credited as reclaimable. Do not revert it.
  `[measured 08-13 22:48Z]`
- **RETRACTED 23:33Z: the "~300MB/hour anon leak" is NOT established.** It came
  from two point samples (`anon` 1163 → 2603 over 18:05–22:48Z), and `anon` is
  now measured to swing **~1650 ↔ 3200MB within minutes**. Two points cannot
  distinguish a ratchet from two phases of that swing — the same error retracted
  the same evening for the v2 sampler. **Do not cite 300MB/hour.**
  `[retracted 08-13 23:33Z]`
- **What IS measured: `anon` oscillates hugely, and the guard samples one point
  of it.** Floor series post-restart: 980.6 → ~1650 in 20 min (warm-up) → 1670 /
  1652 / 1763 over the next 10 min, roughly flat. p50 1715 → 2176 → 2518, max to
  **3203.7**. The guard needs `anon < 2196`, so a cycle builds or aborts
  depending on where in the swing it reads. `[measured 08-13 23:19–23:29Z]`
- **Regime is INTERMITTENT, not frozen.** Post-restart: 8 `LAYER2_SHORTLIST`
  builds, 4 aborts. The 20:39–22:59 event was different in kind — 300
  consecutive aborts, zero builds. `[measured 08-13 23:33Z]`
- **Prediction falsified:** re-freeze was predicted at ~4–5h; aborts resumed at
  **34 minutes**. The linear-growth model is wrong. `[measured 08-13 23:33Z]`
- Open question, and the likely real defect: **`#417` fixed WHICH quantity the
  guard reads; it did not make ONE READING of that quantity sufficient.** A
  point-sampled guard against a 1550MB-swinging value gives an unstable
  verdict. Trough/median sampling or hysteresis is the shape of the fix — not
  another allocator hunt. `[from-measurement 08-13]`
- **Restarts clear it and prove nothing.** 14:56, 18:05, 22:59 — each dropped
  `anon` (2603 → 980.6MB at 22:59) and each destroyed the evidence window.
  **A recovered board is not a fixed system.** `[measured 08-13]`
- **Both allocator flushes are ALREADY deployed and already measured (`#285`).**
  `malloc_trim` returned 1109.6MB across 24 calls/46min (gc: −104.3MB);
  `configure_malloc_arenas(2)` runs at `run_refresh_worker.py:3156` before
  threads spawn. The trim **halved** the ratchet (~24 → ~11 MB/min) and did not
  stop it; at guard time it returns 0.0–2.9MB. **So the residual is NOT
  free-but-unreturned memory** — it is live objects or fragmentation.
  Do not propose "add a flush". `[measured 08-10, re-read 08-13]`
- **`_BOOK_QUOTES_RSS_PER_FILE_BYTE = 6.3` is CORRECT — EXONERATED.** Measured
  5.89–6.33× on four real shards, conservative at scale. The 500MB budget is
  not blind. `[measured 08-13 23:1xZ]`

## `#414` board-build cost — cause found, fix shipped, effect UNVERIFIED

- **The MLB board-build cost was the quote-join identity scan.** Eight
  production samples fit `19.86s per million rows walked` (R²=0.918) with
  ~83k rows walked per call, constant. `tail_s` 21–54s, `rows_s` 0.00 — the
  row loop is EXONERATED. `[measured 08-13]`
- Index shipped in `d4bb29b5`: **85.43 → 0.66 ms/call (130×)** locally at
  production shard size, equivalence proven over 30+ query shapes.
  **Production effect UNVERIFIED.** `[measured local 08-13]`
- **If the index works, `SLOW_SEGMENT_PROFILE` goes SILENT** (gated at 5s).
  Read its absence only against `LAYER2_SHORTLIST` still recurring and the
  pre-fix baseline of 8 lines in ~4 minutes. `[policy]`

## `render.yaml` env hygiene (`#96` family)

- The web `envVars:` list is anchored `&shared_render_env_vars` but the alias
  **is never referenced anywhere in the file** — nothing was ever shared, so
  worker-only keys accumulated on web for months. `[from-code 08-13]`
- Web block audited and cut **62 → 52 entries** (`606a2f28`, `d16950b9`,
  `1e09fa9b`, `7c60d0f8`). Every removed key was already declared on both
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
- **`checkpoint-guard.py` (Stop) can now pass — fixed in `5cdf45b6`.**
  Two independent causes, both measured. (1) `.syndicate/.last-checkpoint` did
  not exist until 08-13, so the pass branch was unreachable: **28 Stop
  deliveries, 5 sessions, exit 1 on all 28, zero exit 0** — while checkpoints
  were demonstrably being written. (2) After the marker appeared it STILL
  returned exit 1, because the denominator was the whole worktree: marker
  13:28:57 vs newest dirty file 13:30:17. It now counts only files this
  session edited, read from `transcript_path` on the hook payload. On the live
  repo: **exit 0 with 62 dirty files present**; before commit it named exactly
  the 2 that were this session's. Replaces `checkpoint-guard.sh`, deleted.
  `[measured 08-13]`
- **Its witness is now session-scoped too (uncommitted, working tree).** The
  marker's mtime is no longer read at all: `.last-checkpoint` is repo-global,
  so session A's checkpoint silenced session B's warning — a false PASS, the
  direction that loses work. The baseline is this session's own `/checkpoint`
  invocation or ledger write, taken from transcript timestamps. `.syndicate/**`
  no longer counts as work. 5/5 cases against the live file, including the
  falsification: no own signal + fresh foreign marker still warns.
  `[measured 08-13]`
- **RETRACTED — `lane-guard` DOES guard `memory-guard-reclaimable`.** A line
  here claimed its four files were unprotected because the status reads
  "DEPLOYED, MEASUREMENT OPEN". That was false and never held: `559d353d`
  ("match OPEN as a WORD in the status field, in both guards") had already
  replaced the one-word status match, and its comment names this very lane.
  The claim came from running an old copy of the regex, not the live file.
  Measured against the hook `settings.json` dispatches to, 5/5 cases:
  `memory_observability.py` and `pipeline/intelligence_state.py` both
  **exit 2 BLOCKED**, `mlb-props-regen`'s file blocked, a CLOSED lane's file
  and an unclaimed file both allowed. The digest and the enforcement AGREE.
  `[measured 08-13]`
- The digest's "1 lane header has no parseable status" is
  `### (superseded lane detail, kept for the file/line map)` — not a lane, and
  correctly unguarded. `559d353d` also stopped such a header inheriting the
  previous lane's open state. `[measured 08-13]`
- **Exit 1 on Stop is advisory.** Delivered stderr carries "Failed with
  non-blocking status code". `/checkpoint` is documented as an obligation and
  is enforced by a log line. A gate would need exit 2; the always-fires defect
  that made that unsafe is fixed (`5cdf45b6`), but raising it is a deliberate
  decision, not a follow-up cleanup. `[measured 08-13]`
- Its denominator is now **the files this session edited**, not the worktree.
  Known gap, deliberate: only `Edit|Write|MultiEdit|NotebookEdit` are counted,
  so a session writing purely through `Bash` redirection reads as clean — the
  same blind spot `lane-guard` has. `[measured 08-13]`
- **A lane's status is free text, and both guards treat it as a predicate — so
  a lane can sit under `## OPEN` and be enforced by nothing.** Live right now:
  `memory-guard-reclaimable` was relabelled
  `— DEPLOYED, MEASUREMENT OPEN —` by its own session. `lane-guard.py` reads
  the status as the first word (`DEPLOYED`) and returns **exit 0 for
  `memory_observability.py`** — its 4 claimed files are unprotected; and
  `session-start.sh` v3 requires literal `— OPEN`, so the digest reports **1
  open lane when the file lists 2**. v1's substring test had the opposite
  failure (it counted `NO LANE WAS EVER OPENED` as open). Neither strictness
  is right: the fix is `OPEN` against the status field only, which
  accepts `DEPLOYED, MEASUREMENT OPEN` and rejects `OPENED`/`REOPENED`.
  **FIXED in `559d353d`** — both hooks now take the field between the 1st
  and 2nd em-dash and match the WORD `OPEN` in it. Both agree on the same
  set, which they did not before. `[measured 08-13]`
- **`lane-guard` is blind to `.claude/**` by design** — `rel.startswith(".claude")`
  returns 0 before any lane is consulted, so the enforcement layer cannot
  protect the directory it lives in. Every real collision today happened
  there. **Three sessions worked `.claude/**` with no lane on 08-13** (ops-kit
  11:00, hooks-enforcement 12:18, hooks-test 14:5x), each deciding
  independently that harness work is exempt. The protocol does not say it is.
  `[measured 08-13]`
- **`.syndicate/.current-lane` is ONE file shared by every session.** It named
  `checkpoint-guard-scope` — another session's lane — during this session's
  run. So `lane-guard` identifies whoever opened a lane most recently, not
  you: it can block your own edits AND fail to block a foreign session,
  depending on who ran `/lane open` last. It cannot do its job with more than
  one session live, and 5 were. `[measured 08-13]`
- **A lane's guard state hangs on ONE header line in a hand-edited shared
  file, and its deletion is silent.** At 14:5x the `memory-guard-reclaimable`
  header was removed from `lanes.md` while its body stayed; the body was
  absorbed into the preceding `checkpoint-guard-scope — CLOSED-VOID` block and
  **all 4 of its claimed files went to exit 0** — the same hole `559d353d` had
  just closed, reopened by a different mechanism 40 minutes later. Repaired by
  restoring the header verbatim (committed in `c506eb2a`; pre-repair backup at
  `/tmp/lanes.pre-repair.bak`). Nothing detected this; it was found by reading
  a diff. `[measured 08-13]`
- **`checkpoint-guard.py`'s witness is this session's own transcript, and
  `.last-checkpoint`'s MTIME IS NEVER READ.** The baseline is the newest
  checkpoint signal in the session's transcript: a `/checkpoint` invocation, a
  file-tool write to `.syndicate/**`, or a shell command naming a ledger file
  (step 2 is a `cat >>` heredoc and leaves no file-tool record). The marker is
  repo-global, so its mtime answers "did somebody checkpoint", not "did I" —
  reading it let session A's checkpoint silence session B's warning, losing B's
  work silently. The `touch` still counts, as a signal in the transcript rather
  than a timestamp on disk. No signal of the session's own means no baseline,
  which warns. `.syndicate/**` is excluded from work-at-risk: it is the
  persistence, not the thing persisted. Design and implementation are the
  archived `hooks-test` session's, recovered from its uncommitted file.
  `[measured 08-13, origin `cf6de8f7`]`
- **Verified by `tests/test_checkpoint_guard_hook.py`, 7 two-actor cases**,
  each with a bystander session doing the right thing. It discriminates: 7/7 on
  this implementation, 5/7 on the superseded one, failing the two-actor case.
  **Supersedes an earlier claim here of "8 fixture cases including the
  false-pass one" — that was false.** All 8 were single-actor and none tested
  the false pass, which is why it survived. `[measured 08-13]`
- Known limitation: `touched` is every path the session ever wrote, so a file
  it wrote and another session later modified is still attributed to it. Errs
  toward false warn, never false pass. `[measured 08-13]`
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
- **`#417` FIX IS DEPLOYED, NOT YET PROVEN.** `03073270` live on
  refresh-worker since 13:05 CDT. The guard now decides on
  `max - max(anon + shmem + slab_unreclaimable, current - reclaimable_file)`,
  with `active_file` counted as reclaimable. At T+23min: `LAYER2_SHORTLIST`
  **x3** vs 0 in the preceding 4h12m, `MEMORY_GUARD_ABORT` **0** vs ~300 in
  5.4h. `[measured 08-13 13:28]`
- **That is NOT yet evidence the fix holds.** The pre-fix code also rebuilt
  after the 14:56 restart (built 15:08) and re-froze ~3h later — it was
  aborting again by 18:00Z. The deploy has not survived that re-warm
  interval, so T+23min is consistent with "rebooted" as much as "fixed".
  **The 24h read settles it: due 2026-08-14 ~13:00 CDT, OWNER UNASSIGNED.**
  `[unverified 08-13]`
- **It is also unconfirmed that the new code PATH executed.** `basis`, the
  field meant to prove it, is emitted only inside the abort branch
  (`intelligence_state.py:3215`), so a working fix leaves it silent forever.
  Needs a success-path log — its own change and deploy. `[unverified 08-13]`
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
