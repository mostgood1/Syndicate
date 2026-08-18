# Syndicate — Verified System State

> **Overwrite lines here as facts change. Do not stack contradictions.**
> Every line carries an evidence tag and a date. Untagged lines are invalid.
>
> **COLLAPSED 2026-08-18, 219 KB / 59 sections → this.** The file had drifted
> back into stacking: **six** sections on refresh-worker memory, **eight** on the
> MLB sim, and **six** on UI probes — each a dated snapshot of a story whose
> ending was elsewhere in the same file. A reader had to reconstruct the current
> truth from a chronology instead of reading it. That is the exact failure the
> 2026-08-15 collapse fixed, recurring in ten days.
>
> **Nothing was deleted.** The complete pre-collapse file is
> `.syndicate/state_archive_2026-08-18_full.md`, and the 2026-08-15 one is
> `state_archive_2026-08-15.md`. Grep them before concluding a fact was never
> measured; never cite either as current.
>
> **What was dropped from the LIVE file** (all present in the archive): dated
> one-off measurement snapshots, superseded memory and sim narratives, and the
> coordinator's own process records — sweeps, adjudications and corrections,
> whose home is `deploys.md` and `lanes.md`, not here.
>
> **The rule that keeps this file useful:** when you learn something here is
> wrong, EDIT THE LINE. Do not append a newer section that contradicts it. The
> reasoning trail belongs in `deploys.md` (append-only measurement log).

## [how-to-use] HOW TO USE THIS FILE

Facts only, grouped by subject. If a subject has an owning lane, it is named.
`lanes.md` says who holds what; `learnings.md` carries the rules;
`deploys.md` carries every measurement with its working.

**EVERY SECTION CARRIES A SUBJECT KEY** `[added 2026-08-18]`:

    ## [subject-slug] TITLE — whatever else

One subject, one section. The slug is the identity, mirroring `lanes.md`'s
`### slug — STATUS`, so there is one convention here and not two. To record
something new about a subject that already has a section, **edit that section**
— do not add a second one. Adding a section that shares a slug is the stacking
failure this file has now been collapsed for twice, and it is what
`scripts/state_key_check.py` reports.

The key exists because "no duplicate titles" looked like health and was the
opposite: it is trivially true when sections are titled by their DATE. Two
subjects are deliberately left stacked so the checker fails on a real thing —
`sim-scheduling-deploy-lineage` (x2) and `wnba-sweep-ownership-gate` (x3).
Collapsing those is owed work, not a bug in the tool.


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
- **`memory.current` counts PAGE CACHE.** Split anon from `inactive_file` before
  calling anything a leak: on live-odds-worker 2026-08-18 the aggregate read
  96.8% while anon was 41%, and a rollback was fired on that misreading.


## [user-decisions] USER DECISIONS `[2026-08-14 ~21:5x CDT]`

- **2026-08-16 — DO NOT BUMP THE refresh-worker PLAN. Reduce instead.** Asked
  directly, with the numbers: peak 3,518MB = 85.9% of the 4,096MB `pro` ceiling,
  578MB headroom, zero OOM kills in 7h15m post-`#435`. Options put were Pro Plus
  (8GB), Pro Max (16GB), or keep 4GB and reduce. **Chosen: keep `pro` and work
  the two remaining levers** — child processes (0.4-504MB, bursty,
  uncharacterised) and pymalloc's 350MB arena retention.
  Consequence to hold onto: the crash is FIXED, so this is optimisation, not
  repair — it does not carry outage urgency and must not be used to justify one.
  No `render.yaml` change was made and none is owed; the file still says
  `plan: pro` at line 272 and that is CORRECT.

Product decisions, not engineering ones. Do not re-take them.

1. **The LLM is NOT meant to be on.** `ANTHROPIC_API_KEY` stays absent. The
   deterministic snapshot path IS the product, not a degrade. Ask Lane N is VOID.
2. **CLV opening capture → (a):** record a compact opening snapshot going
   forward. **(b) REJECTED** — do not raise the 256 MB
   `SKIP_OVERSIZED_LEDGER_CHUNK` ceiling. **First real CLV number is ~24h out.**
3. **Soccer → BUILD THE MODEL.** Not "hide the EV", not "accept ~0 rows". A3's
   uninformative-EV rule stays as it is; the ~0-row state is the accepted
   INTERIM, not the destination.
4. **Layer 1 stays** — it is the known universe and the user's research surface.
   Layer 2 is the curation and the product core.
5. **BUILD THE LIVE GAME-LINE PROJECTION** `[2026-08-14 ~22:2x CDT]`. Program
   Tier 5 is ANSWERED: the product is not pregame-first. The stated premise
   ("pregame and live board experience") becomes something to make true rather
   than something to walk back. **This is the current focus.**
6. **The sharp reference price is Pinnacle, and we already have it** — see the
   section below. Model Lane C needs NO sourcing work.
7. **SOCCER: ship the three correctness fixes, HOLD the 3-way de-vig.**
   `[2026-08-15 ~11:5x CDT]` **This SUPERSEDES decision 3's "build the model".**
   The model was then unmeasured; it is now measured and it **LOSES to the
   market** — multiclass Brier **0.5875 vs 0.5737**, worse in **8 of 9 leagues**
   (sign test p = 0.039), under-dispersed (stdev 0.1575 vs 0.1811), on the first
   leak-free backtest this repo has had (1,112 matches, ratings recomputed per
   match day, benchmarked against de-vigged closing odds on identical matches).
   - **SHIP:** seed bootstrap (unblocks 107 of 123 board rows), accent join
     (9 clubs / 5 leagues), as-of date parsing (fixes leakage + two live
     production-ratings bugs). The as-of half is landed: `0b0d44d9` + `f05a21c4`.
   - **HOLD:** the 3-way de-vig. It is a correct removal, but it makes an
     untrustworthy number visible.
   - **The reason the hold matters, and the part most likely to be lost in
     summary: the model's errors sit on the FAVOURITES, so published
     `model_edge_pct` would systematically point edges at underdogs.**
   - So soccer stays at ~0 published EV rows **because the model is not good
     enough**, not because the data is missing. That is a different and more
     honest reason than the one decision 3 was taken under.

**Nothing is currently owed by the user.**


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
- **Deployed SHAs move constantly** — five times in one evening, twice inside 25
  minutes. Re-read per service inside the step that uses one; never carry one
  across turns. A stale read nearly shipped a rollback. `[measured 08-14]`
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


## [session-harness] SESSION HARNESS — what the hooks actually enforce

- **THE LEDGERS ARE KEYED AND CHECKED** `[verified 2026-08-18]`. One checker per
  ledger, all three ENFORCED in CI and reported at session start as
  `LEDGER INCOHERENT`: `scripts/lane_identity_check.py` (slug, one OPEN block,
  one home), `scripts/todo_id_reconcile.py` (numeric id in exactly one of
  `todo.md`/`todo_closed.md`), `scripts/state_key_check.py` (every `## [slug]`
  unique). All three verified to EXIT 1 on deliberately corrupted copies before
  being wired in — the gate is not vacuous. Green at checkpoint: lanes 54 blocks
  coherent, state 35 sections/35 subjects, todo 166 ids.
- **`state.md` sections carry a subject key** `## [subject-slug] TITLE`. One
  subject, one section; a shared slug IS the stacking failure. Added because "no
  duplicate titles" was trivially true while sections were titled by date.
- **`lane-guard.py` reads BOTH Files forms and wrapped continuation lines**
  `[verified 2026-08-18: file-like claims 52 -> 80]`. It previously matched only
  `- Files:`, so 5 lanes using `- **Files (...):**` declared paths NO HOOK COULD
  SEE. A disclaimer now governs only what FOLLOWS it, not the whole line.
  Claim matching is exact-or-suffix (`rel == f or rel.endswith("/"+f) or
  f.endswith("/"+rel)`), never a directory prefix — so a non-path token claimed
  out of prose is INERT.
- **`lane-guard.py` (PreToolUse) enforces.** Blocks `Edit`/`Write` against a file
  claimed by another OPEN lane (exit 2); allows it when `.syndicate/.current-lane`
  names the claiming lane. **With the marker empty it blocks your OWN lane's
  files**, reporting `Current lane: 'none'` — so a session that hand-edits
  `lanes.md` instead of running `/lane` locks itself out.
- **`Bash` bypasses it entirely** — the matcher is
  `Edit|Write|MultiEdit|NotebookEdit`. The guard bounds the file tools, not the
  session.
- **`lane-guard` is blind to `.claude/**` AND `.syndicate/**` by design**
  (`lane-guard.py:244`, one `rel.startswith` test covering both), so the
  enforcement layer cannot protect the directory it lives in — and every real
  collision has happened there. **The `.syndicate/**` half matters just as much
  and was missing from this line until 2026-08-18:** no lane claim can ever
  guard `lanes.md`, `state.md`, `deploys.md` or `learnings.md`, so concurrent
  ledger writes are unprotected by design and a phantom claim on a ledger file
  is inert rather than a lock. Measured during the 2026-08-18 orphan sweep:
  `basketball-model-owner`'s Files block claims bare `lanes.md` (a prose
  collision-check sentence the parser reads as a claim) and it blocks nobody —
  while an unrelated session's write to `lanes.md` landed **between** two of
  that sweep's own edits, reported by the Edit tool as "modified on disk since
  you last read it". Anchor ledger edits on unique strings, never on line
  numbers, and re-read before any edit that depends on surrounding content.
- **`commit-guard.py` (PreToolUse) reads the index the COMMIT will use, fixed
  `a52a2b64` 2026-08-16.** It previously evaluated both predicates against
  `CLAUDE_PROJECT_DIR` — the MAIN worktree — while the commit runs wherever the
  shell is, which for this repo's own contended-tree recipe is a LINKED worktree
  with its own index and its own HEAD. **It blocked three clean commits in one
  session**, and, the half that matters, **would have passed a stale index in the
  worktree actually being committed from without a word.** Now resolves
  `cd` → `-C` → payload `cwd` → project dir, then `rev-parse --show-toplevel`.
  `git -C <dir> commit` is CHECKED (it was skipped for "has its own index";
  having your own index is not having a fresh one). **`--git-dir` /
  `--work-tree` remain a KNOWN GAP** — index and tree decouple, so "is it still
  on disk" has no single correct base. 13 tests on real repos
  (`tests/test_commit_guard_worktree_index.py`); pre-fix 7 fail, post-fix 13 pass.
- **`commit-guard.py` reads the COMMAND, not a proxy for it, fixed `5fb52342`
  2026-08-17.** Two exemptions, both measured:
  (a) **all THREE documented overrides were unreachable.** They were
  `os.environ.get(...)` — the HOOK's env — but a PreToolUse hook runs BEFORE the
  shell, so the `export GIT_INDEX_FILE=…` in the recipe the guard PRINTS, and
  the `SYNDICATE_ALLOW_STAGED_*=1 git commit` prefix it prints as the override,
  were both invisible to it. A session that followed the refusal message was
  refused again. Assignments are now parsed out of the command string,
  last-write-wins against `unset`.
  (b) **a pathspec-limited commit is exempt whole.** MEASURED 2026-08-17 against
  an index holding a revert of `A.txt` plus a `D` of on-disk `C.txt`:
  `git commit -m x -- C.txt` produced a tree keeping BOTH, `--stat` 1 file;
  `--pathspec-from-file=` and `--amend -- <paths>` likewise. A partial commit
  builds from HEAD plus the WORKING TREE content of the named paths and never
  consults the index — not even for the named paths — so there is no path left
  to evaluate. **`-i`/`--include` NOT exempt** (the revert landed).
  **`-a` NOT exempt** (it kept the line but COMMITTED the deletion, so predicate
  1 is live under it); `-a` remains a known false positive for predicate 2,
  left alone because `-a` does not refresh `skip-worktree`/`assume-unchanged`
  and that case is unmeasured. Unrecognised options fall through to "keep
  guarding" — false positive, never false negative. Verified by running 19 cases
  through the pre-fix and post-fix guards together: 10 flip 2→0, 8 hold at 2.
  **62 tests in `tests/test_commit_guard_worktree_index.py`** (69 for the
  two-file run that also covers `test_checkpoint_guard_hook.py` — cite the 62 if
  you mean this guard); exemption path 81 ms, short-circuiting before any git
  call.
- **A PATHSPEC COMMIT NEEDS NO REPAIR STEP; THE ISOLATED-INDEX RECIPE DOES.**
  Measured on `5fb52342`: the partial commit UPDATED the shared index for the
  three paths it committed (`git diff --cached` for them empty afterwards) and
  left another session's staged work untouched. The isolated-index route, by
  contrast, is recorded in `learnings.md` 2026-08-15 as arming a revert of the
  file you just committed, every time, requiring a follow-up
  `git restore --staged`. The guard's refusal message now leads with the
  pathspec form for this reason.
- **`commit-guard` matches the COMMAND STRING**, so bundling a file write or a
  `git reset` into the same command as `git commit` blocks the whole thing.
  Separate them. `[recorded by another lane 2026-08-16]`
- **THE ARCHIVE PASS ITSELF CREATES ORPHANS, and that is a second mechanism, not
  a repeat of the one below.** Moving a CLOSED lane to `lanes_closed.md` takes
  the header and whatever body existed AT THAT MOMENT; any bullet the owning
  session appends afterwards lands in `lanes.md` with no header above it and is
  silently adopted by whichever lane precedes it. Measured 2026-08-15: two
  blocks of `model-audit-devig-and-hygiene` ended up under
  `nfl-live-edge-suppression` and `live-game-line-projection`, and **a later
  collision check therefore reported a FALSE claim on
  `scripts/backtest_mlb_props.py`** — the guard reading a real file claim that
  belonged to nobody. Reconciled 2026-08-15; line arithmetic verified exact.
  **When archiving, re-check the source lane for appends made after the move,
  and when a collision check names a file, read the matched text before trusting
  the slug it is attributed to.**
- **A lane's guard state hangs on ONE header line in a hand-edited shared file,
  and its deletion is silent.** A header once vanished while its body stayed, and
  all 4 of that lane's claimed files went to exit 0. Nothing detected it; it was
  found by reading a diff. Both hooks now take the field between the 1st and 2nd
  em-dash and match the WORD `OPEN` in it.
- **`checkpoint-guard.py`'s witness is this session's OWN transcript;
  `.last-checkpoint`'s mtime is never read.** The marker is repo-global, so its
  mtime answers "did somebody checkpoint", not "did I" — reading it let session
  A's checkpoint silence session B's warning, losing B's work silently.
  `.syndicate/**` is excluded from work-at-risk: it is the persistence, not the
  thing persisted. **Exit 1 on Stop is advisory**, not a gate.
- **The 3-lane cap in policy has no enforcement** — `/lane open` checks file
  collisions only and never counts. Eight lanes are open today.

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


## [board-freshness] BOARD FRESHNESS AND STALENESS

**THE BOARD HAS TWO INDEPENDENT CAUSES, and fixing one is not enough.**

- **Cause 1 — refusal rate.** 96.7% of board cycles were refused before any work:
  146 `MEMORY_GUARD_ABORT stage=pre_source_state_fingerprint` against 5 completed
  builds. **The guard doing the refusing protects a stage Layer 2 never runs**
  (`_MIN_SAFE_MEMORY_HEADROOM_BYTES`, sized for `build_intelligence_overview`).
  Production's own proof they are independent: on 3 of 5 builds
  `CANDIDATE_POOL_READY count=0` while `LAYER2_SHORTLIST` returned `rows=256` on
  the SAME cycle. `[measured 08-14 14:39Z]`
- **`#387`'s Layer 2 fix is CLOSED-VERIFIED on a full 3h clean window** —
  37 refreshes = 11.9/hour vs 1.7 baseline, longest gap 11.8 min vs 104.7,
  96 `MEMORY_GUARD_ABORT` (so not a boot-confounded quiet period),
  `LAYER2_GUARD_SKIP` 0, zero OOM. All five criteria met. Residual confound
  stated: abort rate 30.8/h vs 48.7/h baseline. `[measured 08-14 19:24Z]`
- **Cause 2 — THE QUOTE INPUT IS NOT MOVING *IN THE PREGAME REGIME ONLY*.** A
  shortlist rebuilt every 5 minutes off a 2-hour-old quote shard is a board that
  LOOKS fresh and is not — **strictly worse than one that is visibly stale,
  because nothing on it says so.** `[measured 08-14 15:1xZ]` **SCOPED 08-15
  02:5xZ: this holds for the empty-slate pregame regime. During a live slate the
  quote input moves every ~1 min and the BOARD REBUILD becomes the binding
  constraint instead — the arrow reverses.** See ODDS CADENCE.
- **QUOTE CHANGE → SERVED UI, END TO END, MEASURED. `[measured 08-15
  02:38–02:58Z, live MLB slate]`** Method:
  `end_to_end = row age_seconds + (server_time − generated_at)`, validated
  against an absolute book timestamp to a 22 s residual — which is what proves
  `age_seconds` is stamped at BUILD time, not at serve time.
  - **Layer 1** (`/api/board/book-grid?sport=mlb`), 15 samples at 60 s over 4
    builds: **min 143 s / p50 451 s / max 698 s** = **2.4 / 7.5 / 11.6 min**.
    Build gaps 10.8 / 5.1 / 4.2 min. Network is not a term (client−server −0.3
    to −0.7 s). **The floor is the board rebuild interval, not the 60 s fetch —
    capture is 6–10× faster than the board can consume it.**
  - **Layer 2** (`/api/board/layer2-shortlist`, which carries its own
    `written_at`): `written_at` **01:53:44Z unchanged for 64+ min**; end-to-end
    3660 → 4022 s (**61 → 67 min**), monotonic, **no rebuild observed**, so this
    is a LOWER BOUND, not a sawtooth. **CONFOUNDED — do not use as a baseline:**
    refresh-worker took three deploys in the preceding 31 min (`ae7318a2`,
    `934b3b81`, `548ded38`, all `#435`). `LAYER2_FAST_REFRESH` since 01:30Z =
    **0** and `MEMORY_GUARD_ABORT` = **0**, so it is NOT the known guard
    refusal — it simply was not running; worker alive and healthy at 02:51Z.
  - **Still unmeasured: a pregame-window end-to-end, and a deploy-free Layer 2
    window.** Both numbers above are live-slate, one sport.
    Full read: `.syndicate/tier5_quote_to_ui_2026-08-14.md`.
- **Layer 1 is NOT dark. `[re-measured 2026-08-16 16:26–16:37Z, lane
  `layer1-board-coverage`]`** The earlier "`count=0` on ~3 of 5 builds" reading
  did NOT reproduce: **4 distinct consecutive MLB builds, all non-zero**, and
  WNBA and soccer non-zero on every one. Same-instant sweep at 16:19:52Z —
  mlb 2,843 rows / 1,941 projected (68.3%), soccer 6,453 / 1,704 (26.4%),
  wnba 872 / 305 (35.0%); nba/nhl/ncaab correctly `no_precomputed_grid_artifact`.
  **Projection coverage does move build to build** (mlb 2,107 → 1,935 projected
  across 16:33:49 → 16:35:06 with `rows` flat at 3,006), so an availability
  claim needs the build stamp, not one read. Program Tier 4.
- **The candidate-pool path serves NEITHER board** and is the real deletion
  candidate. Layer 1 and Layer 2 are **siblings off the shared grid**, not
  sequential — which is the mechanism by which L1 can fail without L2 noticing.

---


## [odds-cadence] ODDS CADENCE AND CAPTURE

- **MLB quote capture has THREE regimes, not one beat. `[measured 08-15 02:5xZ,
  supersedes the single-cadence reading of 08-14 16:3xZ]`** All 371,567 rows of
  `mlb_source/tracking/book_quotes/2026-08-14.jsonl`, streamed from web and
  bucketed by distinct `captured_at`:
  | window (UTC) | slate | gap |
  |---|---|---|
  | 07:03→15:10 | pregame, nothing live | **121 / 121 / 123 / 121 min** |
  | 16:20→18:25 | first games start | 70 / 61 / 64 min |
  | 18:36→20:54 | ramping | 11–12 min |
  | 21:48→02:53 | full live slate | **~1 min, continuous** |
  **121.6 is exact and it is the EMPTY-SLATE PREGAME number only.** The same
  pipeline samples 122× faster once games are live. Never quote it unqualified.
- **SUPERSEDED IN PART — there is a THIRD regime, and it dominates.
  `[measured 08-15 16:38-17:00Z, deploy-free window, 22 samples]`**
  On 08-15 the pregame beat was **~60 min, not 121.6**, and then MLB capture
  starved for **5.8 h**. Cause is neither the tick nor the cooldown: a chain of
  back-to-back refresh **run-locks** (`ops_refresh.py:669`, per-lane, NOT the
  separate `JOB_CAP_THROTTLED` job cap -- an earlier version of this line
  conflated them; raising the job cap would not have helped), each
  held ~25 min with ~2 min free — **~92% occupancy, traced 11:39→17:00Z**.
  17 consecutive ticks refused by `pid=4047`; the ONE tick that got through at
  16:56:26 took end-to-end from **20,880 s to 32 s**, then `pid=5681` retook it.
  **End-to-end is BIMODAL: ~32 s or hours, never in between.** In the starved
  regime the number rises exactly 1 s/s — it is a clock, not a latency.
  **`PREGAME_RELAUNCH_COOLDOWN_SKIPPED` fired ONCE in 5.75 h** (counted on
  live-odds-worker, the correct emitter, with a liveness control), so **Tier 0's
  `0.1` would NOT have prevented this** and is not the Tier 5 prerequisite the
  program plan calls it. Full working:
  `.syndicate/tier5_quote_to_ui_WINDOW2_2026-08-15.md`.
- **WHY 60s BECOMES ~7,300s, two multipliers, both measured `[08-14 17:0xZ]`:**
  1. `SYNDICATE_LIVE_ODDS_REFRESH_INTERVAL_SECONDS=60` is the TICK interval,
     never the launch interval.
  2. **The pregame relaunch cooldown is 1800s and GLOBAL** —
     `_pregame_relaunch_blocked` reads ONE marker keyed by **date only, not by
     sport and not by service**, so a launch for ANY sport starts the clock for
     EVERY sport. 30×.
  3. **Sports rotate across launches**, so MLB rides roughly 1 in 4. ~4×.
  **The leverage is a design fact, not a tuning value: because the cooldown is
  global, every sport added dilutes every other sport's cadence.** A per-sport
  cooldown decouples them; that is the change worth considering, not lowering 1800.
  4. **BUT THE COOLDOWN IS GATED ON PREGAME PHASE AND IS BYPASSED WHENEVER ANY
     GAME IS LIVE. `[measured 08-15 02:5xZ]`** On the deployed tree:
     `effective_phase = ("live" if any_live else "pregame")`, then
     `if ... effective_phase == "pregame" and _pregame_relaunch_blocked(...)`.
     `latest_tick` carried `adaptive:true, anyLive:true, phase:"live"`. So both
     multipliers above apply **only to the empty-slate pregame regime**.
- **The per-sport cooldown fix (`ea8fad58`) is NOT deployed on ANY service.
  `[measured 08-15 02:4xZ]`** Checked by reading the deployed trees, not
  ancestry: `git show <sha>:syndicate/features/shared/live_refresh_loop.py`
  gives `def _pregame_relaunch_blocked(*, now_epoch, date_str)` — no `sports`
  kwarg — on both `548ded38` (refresh-worker) and `ccd10349` (live-odds-worker).
  **`ea8fad58` IS an ancestor of `origin/main`, so an ancestry-only check says
  "shipped" and is wrong.** `autoDeploy` is off; being on `main` ships nothing.
- **WHICH SERVICE DRIVES CAPTURE IS AN OPEN DISCREPANCY — re-check the env
  before relying on either answer. `[measured 08-15 02:5xZ]`** The env API now
  reads the OPPOSITE of this file's 08-14 line: live-odds-worker
  `SYNDICATE_ENABLE_LIVE_ODDS_REFRESH_LOOP=true` and
  `SYNDICATE_MLB_REFRESH_TICK_OWNER=true`; refresh-worker `false` on both; and
  the 02:35:20Z tick wrote `refresh_status_latest__live-odds-worker.json`.
  **But** `ODDS_SWEEP_OUTCOME` since 02:00Z is refresh-worker **16**,
  live-odds-worker **0**, which matches the old line. The emitter
  (`live_refresh_loop.py:4100/4117`) is reachable from the board-build sweep as
  well as the loop tick, so both emitting is not itself a contradiction.
  Unresolved; resolving it needs the board-build loop. Loop ownership is an env
  flag that moves with no diff — that rule is why this line is now a question.
- **This is the real cause of "candidates that are no longer bettable"** — the
  board's MLB prices are up to ~2 hours old by construction.
- **Consequence for the whole movement family — REAL CONSTRAINT IS THE BUFFER
  DEPTH, NOT THE FETCH RATE. `[measured 08-15 02:4xZ, supersedes "sampled
  roughly every two hours"]`** From
  `/api/ops/odds-history/inspect?sport=mlb&date=2026-08-14`, 3,582 markets:
  sampling interval within the retained history is **p50 1.0 min** (live 0.9,
  pregame 1.0) — not 2 hours. But `history_points` is **capped at 20**
  (`_ODDS_HISTORY_LIMIT`, `shared/odds_refresh_tracking.py:40`, env-tunable via
  `SYNDICATE_ODDS_HISTORY_LIMIT` which is **unset on all three services**), and
  3,130 of 3,582 markets sit exactly at the cap. Retained span is therefore
  **p50 17.8 min**. The code's own comment concedes it is *"narrower than the
  steam detector's stated 45-min window for hot markets."*
  **So a movement calculation sees ~18 minutes and is structurally blind to
  whether the previous sweep was 1 minute or 2 hours earlier — the
  pregame→live transition, the biggest move of the day, falls out of the buffer
  within 20 minutes of first pitch.** Re-examine `movement_velocity` and the
  steam detector against `_ODDS_HISTORY_LIMIT`, not against fetch cadence.
  Raising it trades against the 8 MB keyvalue ceiling that forced it to 20.
- **A `too_large` line does NOT mean the artifact failed to publish.** The
  ceiling lives in `_publish_skip_reason`, which is **sweep-only**; the direct
  path streams and never consults it. Verified byte-identical on web. Four
  sessions have now misread this. `[measured 08-14 16:2xZ]`

### OddsAPI budget `[measured 08-14 17:2xZ]`

- **Projected 30-day burn 4,640,809 credits = 92.8% of the 5M cap.** Headroom
  ~360k/month. MLB is **93.7%** of spend (8.72 cr/call); soccer 4.2% (1.46
  cr/call, 6× cheaper); nfl 1.4%; wnba 0.7%. Live hours dominate (83–228k/hr)
  against pregame's 10–18k/hr.
- MLB pregame sweep interval is 3600s with an effective gap of **~1h10m**
  (7,289s → 4,215s). The loop wakes every 900s and sweeps whatever is past its
  interval, so the setting is a FLOOR the tick quantises.
- **Any cadence increase spends against the cap — it is a product decision, not
  a tuning tweak.**

---


## [probability-statistic-ownership] PROBABILITY-STATISTIC OWNERSHIP `[measured 08-15, shipped `2ac3c6bc`]`

- **THE AUDIT'S "TWO DE-VIG ORDERINGS" IS FALSIFIED. In the BOARD/ODDS path
  there is ONE, and `book_grid` is not a second.** `book_grid` never de-vigs — its whole import
  surface from the odds layer is `_implied_probability`, `_line_value`,
  `market_sides_for_quote`. The canonical ordering (`devig` →
  `fair_probability_by_book` → `consensus_fair_probability` median) already had
  both consumers (`layer2_board._fair_by_side`,
  `odds_book_quotes._fair_value_fields`). **Ranked #5's exit criterion was
  already satisfied. Do not re-open it as a de-vig collapse.**
- **What was duplicated is a VIGGED statistic**, hand-rolled in `book_grid` and
  `odds_book_quotes`: mean implied probability across books → a price. It is a
  PRICE-SHOPPING reference, margin-inclusive, and **not** a fair value; it is
  bounded below by zero against the best price by construction. Now owned by
  `opportunity_signals.consensus_vigged_price`. Removes 2 of Tier 3a's 31 copies.
- **Both copies diverged from the owner at the boundary:** p=0.5 → owner
  **+100**, copies **−100**; p∈{0,1} → owner refuses, copies raise
  **ZeroDivisionError**. Reachable, because
  `odds_book_quotes._implied_probability(0)` returns **0.0** rather than
  refusing. **The ±100 flip moves no derived number** — `implied(+100) ==
  implied(−100) == 0.5`, so `edge_vs_consensus_pct` is unchanged.
- **SCOPE, because the line above is easy to over-read:** "one ordering" is
  about the board/odds path only. Sport-local SIM market-anchoring has its own
  de-vig implementations and they were deliberately NOT touched —
  `soccer/features/market_anchoring.py::devig_decimal_odds`,
  `nhl/sim_engine/hockeysim/market_anchoring.py::devig_two_way_home_prob`, plus
  `scripts/backtest_soccer_h2h_calibration.py` and
  `scripts/validate_soccer_vs_market.py`. **The soccer ones are claimed by
  `soccer-model-coverage`.** These are the same engines `state.md` already flags
  as market-anchored and therefore partly circular; unifying them is a modelling
  decision, not a converter cleanup. `[verified 08-15 by repo-wide search with
  `.claude/worktrees/` excluded — those hold full repo copies and triple-count]`
- **Both production copies of the vigged mean are GONE, verified by search:** the
  only `mean_implied` left outside worktree copies is in
  `tests/test_devig_unification.py`, which reproduces the legacy arithmetic on
  purpose to prove valid prices did not move.
- **`edge_vs_consensus_pct` is now ABSENT rather than `0.0` when the consensus
  refuses, and that is verified no-break** across 6 consumer suites (92 green),
  including `tests/test_quote_ref.py`, which asserts the field directly.
  **The only real `book_grid` consumer is `nfl/preseason_cards.py`, reached
  through `read_book_grid_artifact` — an ARTIFACT HOP, so it does not import
  `book_grid` and an importer search cannot find it.** It already tolerated a
  `None` side, because `consensus[side] = None` was reachable before this change
  via the empty-prices branch. `prop_projections`' `consensus` key is a
  different producer's. `[measured 08-15]`
- **`/preflight` now prints the deployed commit of ALL THREE services** (D5),
  degrading a per-service read failure to that row rather than to the gate.
- **MLB prop skill numbers are now OUT-OF-SAMPLE. `D4` CLOSED `[measured 08-15]`.**
  Fitted on 2026-08-01..08-06 (n=1,246), scored on 08-07..08-13 (n=1,241), from
  production artifacts via `/api/ops/artifacts/stream` — **the checkout cannot
  do this** (864 `daily_summary` files, all 05-28..07-12, zero in August).
  Harness validated first: every in-sample figure reproduces the published table
  exactly, so the split reads the same data the module was built from.
  - **6 of 7 in-sample becomes 5 of 7 out of sample, and EXACTLY ONE verdict
    flips — `batter_hits`, the market the module quotes first.** In-sample
    margin **+0.0007**, which is smaller than the 4-dp rounding of its own
    published table; out of sample it LOSES by 0.0081. It never was a result.
  - **The leakage was NOT inflating everything** — four markets IMPROVE out of
    sample (`tb` +0.0256→+0.0313, `rbi` +0.0210→+0.0285, `r` +0.0243→+0.0289,
    `2b` +0.0009→+0.0044). It manufactured a win only where the margin was
    already indistinguishable from zero. **Do not assume the same shape of every
    other backtest here; measure it.**
  - **The BIASED-NOT-BLIND headline SURVIVES.** Correlations fall consistently
    and stay positive (hits .1607→.1487, tb .1523→.1262, rbi .1316→.1156, r
    .1620→.1520, sb .1605→.1322).
  - Each market carries `oos_debiased_beats_baseline` / `oos_margin` /
    `oos_correlation`; the served row's `debias_validation` is `out_of_sample`.
  - `hrr` is still a degenerate constant 0.0 in this window, so its absence from
    `_MARKET_SKILL` remains correct and `unmeasured` remains the truth.

---


### The ±4900 fair-price clamp — web + refresh-worker FIXED. live-odds-worker STILL CARRIES IT. **STILL NOT VERIFIED.**

- **THE WEB-ONLY DEPLOY WAS FALSIFIED IN PRODUCTION** `[measured 08-15 23:10:13Z
  and 23:15:46Z]`. Two triggers, two unrelated slates, both `PRE_FIX_MISPRICE`
  while a fix-carrying web SHA was live: nfl `h2h_3_way` 0.014698 → **+4900**
  (correct +6704); mlb `spreads` 0.009911/0.990089 → **±4900** (correct ±9990).
  `reports/clamp_watch/trigger_20260815T231013+0000.json`, `..._231546+0000.json`.
- **WEB IS NOT THE PRODUCER AND ITS FIX IS STRUCTURALLY INERT.** The block is a
  **backfill** — `if fair_probability is not None and card.get("fair_price") is
  None:` — so a value clamped upstream passes through untouched. Web can only
  act when the field arrives ABSENT. The producer is the intelligence-state
  loop: `SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP` is `true` **only
  on refresh-worker** (`render.yaml:499`).
- **refresh-worker FIXED: `57a437d5`, live 2026-08-16 00:23:04Z** — 0
  occurrences of `max(0.02, min(0.98` across all three files at the live SHA.
  Cut on live `2c14d9ae` (off-main deploy branch).
- **live-odds-worker STILL CARRIES THE CLAMP** on `c4116ab6`. Deferred by user
  decision — it does not run the intelligence-state loop, so it is not the
  producer. `079cc42b` is cut/tested/pushed on `deploy/clamp-workers-on-live`;
  **re-cut on the live SHA first**, that service moved 4× in 100 minutes.
- **STILL NOT VERIFIED** `[reads 08-16 00:24:04Z and 01:30:50Z]`: both
  `no_trigger` (12 then 68 rows, extremes 0.0687/0.8904). Same reading a quiet
  slate gives with the bug fully present. `out_of_clamp=0` is never evidence.
  Both of the real triggers came from **in-play** markets late in games.
- **A CLAIM'S TARGET IS AN INTENTION, NOT A DEPLOYMENT** `[measured 08-15/16]`.
  live-odds-worker's claim advertised clean target `49797f4b` for 45 min; it
  never landed. `c422f79a` then `c4116ab6` landed instead, both clamping.
  Verify by CONTENT at the live SHA.
- Superseded detail: web `e831263e`
  (`dep-da0d8vnlk1mc73fn8ta0`). **Survived two later deploys** — checked by
  CONTENT on each new live SHA (`bb23c8f9`, `8b010dac`): **0/0** occurrences of
  `max(0.02`. `render_deploy.py`'s descendant rule is what protects it.
- **THE FIX IS NOT VERIFIED IN PRODUCTION AND MUST NOT BE RECORDED AS SUCH.**
  The triggering row left the slate during the ~7 min build; the post-deploy
  read was `no_trigger`, which is the SAME reading a quiet slate gave before the
  deploy. **`out_of_clamp=0` is not evidence the fix worked** — that count comes
  from the WORKER's artifact and is independent of this web-side change.
  The watcher is running; **its next trigger is the verification**, and a
  `PRE_FIX_MISPRICE` against a fix-carrying SHA would be a real falsification.
- **BEFORE, measured:** nfl `h2h_3_way` away, JAX @ NO live,
  `fair_probability` **0.007934** published **+4900** vs correct **+12503**
  (off by 7603 pts). **That was ONE row echoed 14x in the payload, not 14 rows.**
- **`check_deploy_safety.py` IS REFRESH-WORKER SCOPED** `[measured 08-15]`. It
  has **no `--service` flag**; its blockers (MLB sim, odds refresh, board build)
  and its `--drain` are all refresh-worker work. **A `NOT CLEAR` from it does
  not, by itself, block a WEB deploy** — web runs **no background loops**
  (`MLB_ENABLE_LIVE_LENS_LOOP`, `SYNDICATE_ENABLE_LIVE_ODDS_REFRESH_LOOP`,
  `SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP` all `false` on the live
  service). Read it, then decide per service.
- **`check_deploy_safety.py` ALSO REPORTS `CLEAR` WHILE JOBS RUN ON THE SERVICE**
  `[measured 08-16 00:13Z refresh-worker, reproduced 00:29Z live-odds-worker]`.
  It returned `CLEAR`, exit 0, "Odds refresh: idle" while that same service ran
  `run_refresh_odds_job.py` → `refresh_odds_sources.py` →
  `build_soccer_artifacts.py --league <X>`. **Gate a worker deploy on
  `safety_rc == 0` AND zero `[JOB]` lines in `deploy_preflight --service <svc>`**,
  re-verified in the same shell command as the POST.
- **Web deploy contention is REAL: 6 deploys in ~50 minutes** from concurrent
  sessions. Landing one took THREE cuts — `render_deploy.py` refused the first
  as a 189-line rollback, Render canceled the second 0.4s after a competing
  deploy started. Budget for re-cutting; never reach for `--allow-rollback`.

### (superseded header, kept for the file/line map) — FIXED IN CODE, ONE THIRD LIVE

- **All three `max(0.02, min(0.98, p))` sites are gone from `main`** (`de0c367f`
  WNBA, `7bb74c95` `layer2_board` + the INLINE copy in
  `pipeline/intelligence_state.py`). All now delegate to
  `opportunity_signals.american_price`. Harness scores each **5/5**;
  `probability_to_american` collapsed **4 behaviour clusters -> 3**.
- **ONLY the WNBA third is LIVE** `[measured 08-15 18:1xZ by CONTENT on
  `1e44e1da`, not by ancestry]`. `7bb74c95` is **committed, not deployed**.
- **The clamp published wrong prices** `[measured 08-15 ~03Z]`:
  `/api/intelligence/query` served 1346 `fair_price` with **24 exactly on ±4900,
  none beyond**; mlb totals under `p=0.992056` published **−4900** vs correct
  **−12488**.
- **`/preflight` on `7bb74c95` = FAIL, and the change is not the problem.** The
  defect is only observable when a slate carries `fair_probability` outside
  [0.02, 0.98], and it does not today (108 rows, p=[0.058, 0.638]). A deploy
  would move 0 → 0. **Do not deploy it as a standalone "verified" fix.**
- **`fair_price` is stamped at SERVE time, not in the artifact** — 0 of 108
  shortlist rows carry it against 1800 served. So this is a **web-only** deploy:
  no refresh-worker restart, no in-flight sim at risk.
- **THE INSTRUMENT EXISTS. Do not re-derive it:**
  `python scripts/watch_clamp_trigger.py --once` (add `--interval 900` to poll).
  Exits **10** on a triggering slate and classifies production from PUBLISHED
  CONTENT — `PRE_FIX_MISPRICE` / `POST_FIX_OK` / `no_trigger`. **`no_trigger` is
  stamped NOT-evidence** in every record. Log: `reports/clamp_watch/`.
  **Its discriminator is the PROBABILITY being outside the band, not the price
  being at ±4900** — `american_price(0.98)` is legitimately −4900, so the naive
  check reports a misprice against correct post-fix output.
- **NEXT:** on a `PRE_FIX_MISPRICE` record, that IS the before-measurement.
  **The user has standing-authorised the deploy on trigger (2026-08-15), and the
  full procedure is `.syndicate/runbook_clamp_deploy.md` — execute that, do not
  improvise it.** `/preflight` is NOT waived; it can fail at trigger time for
  reasons that do not exist now. **The likely outcome is INCONCLUSIVE, not
  success:** the board rebuilds ~every 25 min, so if the triggering row leaves
  the slate before the post-deploy read, `no_trigger` proves nothing — it is the
  same reading the pre-deploy slate gave. Only a match on the recorded ROW
  IDENTITY counts. Until then the fix is correct-and-unproven, which is not the
  same as working.


## [published-shortlist] THE PUBLISHED SHORTLIST — edges, EV, CLV

**Owner: `recommendation-lane-correctness` (model-audit session).**

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

- **`edge_vs_modelled_fair_pct` EXISTS AND IS COMMITTED, NOT DEPLOYED**
  `[user decision 2026-08-17; moved here 2026-08-18 from a WNBA state snapshot]`.
  Measured on the real payload: 228 of 258 both-terms MLB rows priced. It never
  writes `edge_vs_market_pct`.

## [mlb-sim-engine] MLB SIM — INPUTS FULLY FED, STILL NO MARKET EDGE `[measured 2026-08-18, lane convergence-phase7-crps; supersedes seven earlier sim sections]`

- **`sim_input_checklist.py --simulate-rebuild` PASSES, exit 0** — every field the
  engine reads is fed (26 unfed → 0). **A plain run still reports 26**: it audits
  SERIALISED artifacts, i.e. pre-wiring history. Always use `--simulate-rebuild`.
- **Arsenal leaderboards are the source of record**, superseding the per-pitcher
  pitch-splits pipeline: **2 API calls vs 309**, 551 pitchers vs 305, 450 batters
  vs none. `player_id` IS mlbam_id. Multipliers normalise per-player
  (level-neutral), NOT vs the league — league normalisation double-counts
  `k_rate`/`hr_rate`.
- **`statcast_quality_mult` is a UNION bag, PARTIAL BY DESIGN.** Feed RAW metrics
  only (`xwoba`, `ev_mean`, `ev_max`); **never** k/bb/hr/inplay, which
  `simulate.py:163` derives. Seven keys deliberately absent.
- **Fully fed vs market: 4 of 4 better, mean gap 0.01071 → 0.00732 (32% closed)
  — and the market STILL WINS ALL FOUR by 0.0048–0.0105. NO EDGE.**
- **`hr` and `inplay` refit corrections are shippable; `k_rate` and `bb_rate` are
  NOT** — a 1.368x `k_rate` correction moved the residual 0.6pp, because K is
  produced by the pitch-level model, not the per-PA target.
- **THE K DEFICIT IS TWO OPPOSING ERRORS.** `IN_PLAY` 23.3% vs ~17% and
  pitches/PA 2.97 vs 3.9 truncate PAs (K 27% LOW); correcting the mix alone gives
  K/PA 0.284 vs 0.226 (26% HIGH). **Fixing either alone is a wash — the mix-only
  fix is FORBIDDEN on its own.** Needs joint calibration.
- **Pitch model, shipped to tree and MARKET-NEUTRAL:** `first_pitch_swing_damp =
  0.42`, `first_pitch_called_boost = 1.60`, applied at 0-0 only. **Set both to
  1.0 for an exact no-op.** 0-0 called strikes 13.7% → 29.6% against a real
  29.6%; K/PA 0.161 → 0.185. Kept as a PRECONDITION for calibration, not as an
  improvement (2 better / 2 worse, mean −0.00013).
- **The count matrix is MEASURABLE, not fittable** — 895,320 real statcast
  pitches via `scripts/measure_count_progression.py`. Do not grid-search it.
  `count_delta` is a single scalar and structurally cannot express
  take-early / attack-middle / protect-late; three calibration attempts failed on
  exactly that.
- **Still wrong:** `base_in_play` 0.23 vs ~0.17, the 0-2 waste cell, the 3-2
  protect cell. K/PA 18% low, pitches/PA 17% short.
- **In-sim substitution: BUILT, MEASURED, OFF.** Pitch-type effectiveness: BUILT
  and UNFED. Modelling of neither is present in the served path.


## [model-skill] MODEL SKILL (`#428`) — measured vs not

- **`#428` IS FOUR MODELS, NOT SIX.** `live_projection_join` is a JOIN and
  `game_board_contract` is a passthrough; neither is backtestable. Real targets:
  `soccer_projections`, `wnba_game_projections`, `wnba_projections`,
  `prop_projections`. `[from-code 08-14]`
- **MLB hitter props are MEASURED: BIASED, NOT BLIND.** 2,487 player-games,
  joined on `batter_id` (an exact join). Every counting market carries real
  signal AND loses to a constant baseline by sitting too high; de-biasing flips
  5 of 7 to beating it. `hits` r=0.16 +28.6%, `tb` r=0.15 +17.7%, `rbi` r=0.13
  +30.5%, `runs` r=0.16 +25.9%. `[measured 08-14]`
- **TWO stacked causes; a playing-time fix ALONE will not fix it.** `pa_mean`
  +18.4%, `ab_mean` +17.2%; per-PA rates still +12.2% after normalising.
  Opportunity explains **55%** of the count bias. Fix opportunity first, then
  RE-MEASURE. `[measured 08-14]`
- **"No measured skill" would have been the WRONG conclusion** and would have
  suppressed a model that needs calibrating rather than retiring. **Always
  decompose bias before publishing a skill verdict.**
- **SHIPPED:** refresh-worker `9972977f` / `098877e1` serves 24 MLB prop rows
  carrying `model_skill` with correlation and verdict. `batter_hits_runs_rbis`
  correctly stays `unmeasured` — it must not inherit a neighbour's number.
  Label-only: no projection, mean or edge changed. `[measured 08-15 00:35Z]`
- **`#425` skill declaration is LIVE on both services** — every projection
  carries `model_skill`, `unmeasured` is first-class: `nfl 20 measured`, **mlb
  1631 / wnba 209 / soccer 12 unmeasured**. Counts surface in the `projections`
  coverage block, **not** in `counts`. `[measured 08-14]`
- **`#425` degeneracy detection is LIVE and VERIFIED** — reports any
  `(kind, market, segment)` collapsed to one value across ≥4 distinct GAMES, all
  sports. It found a real defect unprompted on its first live board.
- **WNBA game lines: NOT MEASURABLE YET, nothing broken.** `pred_margin` starts
  2026-08-02; 9 of 361 completed games carry one; n=30 due ~2026-08-26.
- **PRODUCTION HAS FAR MORE HISTORY THAN THE CHECKOUT** — 81 WNBA dates vs "4
  files" locally, and the local files are 7-column stubs with no projection
  column. **Never scope a backtest from the checkout.** `[measured 08-14]`
- **Freeze breadth:** 69 sport × market pairs ship predictions; 2 have a
  backtest. No new pair ships without archive-replay coverage. `[policy]`

---


## [live-surface-tier5] THE LIVE SURFACE — Tier 5 `[measured 08-15 02:3x–03:0xZ]`

Full read with per-module evidence: `.syndicate/tier5_live_modules_2026-08-14.md`.

- **There are 30 `live`-named modules under `syndicate/**`, not 16.** No
  definition yields 16. All 30 were read. **Importer counts must be
  AST-resolved** — a basename grep for `live_lens` collides across eight sports
  and reports `live_lens_loop` as having 0 app importers when it has 2.
- **Nothing here is "an abandoned approach still costing compute."** Breakdown:
  **1 dead** (`features/live_ui_audit.py`, zero importers anywhere incl. tests —
  an argparse CLI parked in `features/`; the only clean deletion), **2 unwired**
  (soccer's projector, below), **11 request-only** (every `live_*_accuracy` /
  `live_prop_audit`, reachable solely from a route — zero background cost), and
  the rest running on purpose.
- **The core MLB path is SEVERED, not scaffolding** — a complete pipeline cut at
  one merge line. See THE PUBLISHED SHORTLIST above.
- **CORRECTED 2026-08-15: "no live GAME-LINE projection exists" is true of what
  is PUBLISHED and FALSE of what is COMPUTED.** *(Restored 2026-08-15 — these
  lines were committed as `fd23c6bc`, then dropped by the 74KB→64KB collapse at
  `7f7d8d88`, which left this section asserting the refuted claim. Do not
  re-collapse without re-reading.)* `estimate_live(LiveSituation(...))` runs in
  production on every live-lens tick, **120 sims per live game**, off the current
  inning/half/outs/bases/score/batter/pitcher, returning `homeWinProb`,
  `awayWinProb`, projected `total` and `homeMargin`
  (`vendor/.../flask_frontend.py:16573`, wired into `_build_game_lens`:16806).
  **Proof it runs:** `LIVE_MC_BAIL` instruments every failure exit;
  live-odds-worker logged exactly **9 bails/tick across 11 consecutive ticks, all
  `status_not_live`**, against a slate of **9 Final / 5 Live** — the live games
  never bail. One exit (`away_score is None`) is uninstrumented, so this is proof
  by exhaustion with one named hole. `[measured 08-15 03:0x–03:2xZ]`
- **It dies in THREE places, and the middle one was re-scoped after measurement:**
  1. `mlb/live_lens.py:1094` — the merge rejected the MC lens for exactly the live
     games (the card's text-derived lens already satisfies
     `_lens_rows_have_projection_signal`); same shape as the prop sever at :1109,
     fifteen lines earlier. **FIXED as `0e0b0aa1`. BOTH DROPS DEPLOYED AND
     WORKING — `live_mc` 0 → 6, CONFIRMED END TO END.** `[measured 08-15 21:49Z]`
     The worker's own per-tick tally reads
     `liveMcSources = {live_mc: 6, segment_projection: 52, unknown: 8}` and web
     SERVES `rows=66 live_mc=6`. **Six and six — the producer's count and the
     served count match**, which is what makes it end-to-end.
     **RETRACTED: my earlier "both drops live and `live_mc` still 0, a clean
     negative" was PREMATURE.** Those passes ran 3 and 8 minutes after the worker
     restarted at 20:56:07Z, inside the live-lens loop's warm-up. **Two reads
     inside one warm-up window are ONE read** — the slate moving between them
     made them independent of each other, not independent of the transient.
  2. **`/mlb/api/live-lens` serves a report WEB WRITES ITSELF.** It reads the
     worker's keyvalue snapshot and, when it judges it stale, DISCARDS it and
     rebuilds locally with the MC hard-refused by
     `refuse_if_compute_in_request_path`. Max age **60 s** vs a **60 s** worker
     tick. **There are THREE live-lens artifacts, not two**, and the published
     disk copy is not the one the surface reads. **FIXED as `4bd7dbb3`, DEPLOYED
     ON WEB** (`9b88d05b` live 19:54:18Z; superseded by `f475c775`, which
     content-checks as carrying both drops and descends from it, so not a
     revert). Carry-forward is bounded 300 s, refused on unreadable age, refused
     on a settled game, stamped with a non-resettable `liveStateAsOf`.
- **INSTRUMENT, corrected twice — read this before verifying anything here.**
  `[measured 08-15 20:0xZ]`
  - **`mlb_source/data/live_lens/…` CANNOT show the lens, ever.** It is the SLIM
    shape from `scripts/refresh_mlb_oddsapi.py`; a game row's keys are exactly
    `{gamePk, startTime, status}` and **`gameLens` is not a key at all**. Earlier
    guidance in this file naming it as the instrument was wrong.
  - **`/mlb/api/live-lens` WAS blind and is now the CORRECT instrument** — it was
    blind because web's rebuild destroyed the lens, and `4bd7dbb3` removed
    exactly that. The rule inverted when the fix landed.
  - **`modelHomeWinProb` is NOT a valid signal: 60 of 60 rows carry one at
    baseline**, stamped on the `first1/3/5` lanes by `_live_margin_win_prob`.
    **`source == "live_mc"` is the only discriminator.**
  - **BASELINE for the pending worker deploy** (`/mlb/api/live-lens`, 15 games /
    4 live): `gameLens rows 60`, **`live_mc` 0**, `liveStateCarriedForward` 0.
  3. ~~`live_projection_join` is entirely prop-shaped; there is no game-line
     join at all.~~ **BUILT AND WIRED as `758a89fa` (Drop 3), DEPLOYED NOWHERE.**
     `shared/live_gameline_join.py` + one call site in `build_book_grid_artifact`
     emitting a `live_gamelines` coverage block, kept separate from
     `live_projections` so one family's zero cannot look like the other's.
     Joined on FULL TEAM NAMES, which match exactly (`matchup.home.name` ==
     `home_team`, verified in production) — **no alias table, deliberately**,
     since the prop join's 91% miss is a market-NAME aliasing failure.
     **SHIPPED: Drop 3 is live on refresh-worker** (`f8ca54e1`, and still
     present on the current live `d72d670c` — verified by content, not ancestry).
     **Expect `rows_live_gameline_edged: 0` at first and do not call it a
     defect:** at 120 sims the 2-sigma bar is ~9.1 pp at p=0.5, so a balanced
     slate refuses by design (recorded decision, spec §8.1).
- **THE LIVE GAME-LINE POPULATION IS 8 ROWS PER BUILD, and the counters are now
  reachable from an API.** `[measured 08-16 03:00Z, 2 games live / 13 Final;
  artifact `generated_at 03:00:00.538Z` streamed off web]`

      live_gamelines       considered 8  projected 2  priceable 0  edged 0
                           withheld 8 = {segment_is_not_full_game: 6,
                                         prob_interval_swamps_edge: 2}
      live_gameline_ledger candidates 0  written 0  enabled true

  - **`index_size` COUNTS SNAPSHOT GAMES CARRYING A `live_mc` LENS, NOT LIVE
    GAMES — the "3 → 8 → 10 is unexplained" handoff line is RESOLVED and nothing
    is broken.** Census at 03:0xZ: 10 of 15 = **8 Final + 2 Live**. A Final keeps
    its last lens, so the number is monotone across a slate. The join filters on
    `game.state == live` on the GRID side, so the Final entries are never used.
  - **The ledger recorded nothing because its population was empty by
    construction, not because of a defect.** v1 recorded `priceable` rows only.
    **FIXED as v2 and SHIPPED** — `5c419007`, live on refresh-worker
    **04:24:33Z**; `LEDGER_VERSION = 2` content-verified on the currently live
    `d72d670c`, which a later deploy carried forward. Records every PROJECTED
    row, keeps `priceable`/`withheld_reason`/`sigma` as fields.
    `LEDGER_VERSION` 1 → 2 because the POPULATION changed: **filter any reader on
    `v` before aggregating**, or the rate spans two denominators.
  - **`/api/board/book-grid` dropped `live_gamelines` and `live_gameline_ledger`**
    though the artifact carries both — second instance of that bug in that
    function. **FIXED AND SHIPPED — web `ebd5f677`, live 03:38:07Z.** Both keys
    read `null` before and serve objects after, measured across two different
    artifacts (03:37:13Z and 03:39:36Z). The ~10 MB
    `/api/ops/artifacts/stream` workaround is no longer needed.
  - **BOTH HALVES ARE DEPLOYED, AND v2 HAS NEVER BEEN EXERCISED.** web
    `ebd5f677` 03:38:07Z, refresh-worker `5c419007` 04:24:33Z, each parented on
    its own service's LIVE SHA — **`main` is an ancestor of NEITHER service's
    live tree** (13 commits live-only on refresh-worker, 33 on web at the time).
    The slate ended between the last pre-deploy build and the first post-deploy
    one, so v2 went live with **zero live rows to act on**; as of 15:17Z on 08-16
    the board reads `index_size 0, considered 0` because nothing is live yet.
    **The test is the scheduled `live-gameline-ledger-check`, 08-16 20:30
    Central.** The discriminator for v2 is `written` rising on rows that are
    **not** priceable — `skipped_unchanged > 0` is NOT it, having already been
    observed under v1.
  - **CORRECTION — "the recorder has never recorded a row" is FALSE.** The
    04:22:51Z pre-deploy build read `priceable 1, candidates 1,
    skipped_unchanged 1`, and `skipped_unchanged` cannot be non-zero unless a
    matching record is already on disk (`_moved(None, rec)` is True, so an empty
    file always writes). **v1 wrote at least one row on 08-15**, between 02:4xZ
    and 04:22Z. The 03:00Z reading above is real; generalising it to a whole
    night was the error.
- **WHERE THE HUNT STANDS AFTER BOTH DROPS `[measured 08-15 21:1xZ]`. Two
  hypotheses are DEAD — do not re-run them:**
  - **"Drop 1 is bypassed; `_persist_live_lens_report` never runs on a tick" —
    FALSIFIED.** `_live_projection_enhancement_payload` has **exactly one
    caller**, `mlb/live_lens.py:1384`, inside that function, and it is the only
    in-process import of the vendored `_live_lens_payload` in the MLB path. The
    `LIVE_MC_BAIL` lines prove it executes.
  - **"the MC bails on live games" — FALSIFIED.** 100 log samples,
    time-contiguous 21:05:27–21:11:04 across multiple whole ticks, **100%
    `status_not_live`** (90 Preview, 10 Final). A live game cannot emit that
    reason and none of the other six appears. **NB: my first evidence for this
    was a saturated 40-of-40 sample and was worthless — re-query
    time-contiguous, and check `hits == limit`.**
  - **REMAINING HYPOTHESIS, NOT A FINDING:** the MC takes the ONE uninstrumented
    exit, `if away_score is None or home_score is None: return None`
    (`flask_frontend.py:16611`), which emits nothing. It is the only silent path
    left. **Nothing has observed it.**
- **THE MEASUREMENT THAT SETTLES IT IS COMPUTED EVERY TICK AND WAS DISCARDED.**
  `_tally_mlb_live_mc_sources` (`live_lens_loop.py:473`) counts
  `live_mc / live_projection / segment_projection` per lane into
  `meta["liveMcSources"]`. `live_lens_loop_status_payload()` had **zero
  callers**. A route now exists — `GET /api/ops/live-lens/status` (`09b345ee`),
  **committed, NOT deployed, and its broader ops regression was interrupted and
  never ran.** Read `enabled`/`threadAlive` from it as the CALLING service's,
  not the worker's.
- **Allowlisting `reports/live_lens_loop/latest_live_lens_tick.json` is INERT —
  do not try it.** `_KEYVALUE_EXCLUDED_PATH_MARKERS` is only
  `("migration_runs/",)`, so the path is keyvalue-backed on every service and
  `write_json_file` returns before any disk write, while
  `/api/ops/artifacts/stream` gates on `target.is_file()`. It would turn a 403
  into a 404.
- **live-odds-worker `earlyExit`s roughly every 6.5 h** — `server_failed`,
  `evicted: False`, at 01:37 / 08:05 / 14:34 / 20:03 on 08-15 (**events API**,
  not logs). A refresh run launches on boot, so **this service's deploy gate is
  closed almost continuously**: 76 min of polling yielded one sub-minute CLEAR.
  **`predictions.full` IS pregame at source** — the vendored payload sets
  `"predictions": card.get("predictions")` verbatim, so no merge line downstream
  can make it live. Served surface confirmed the effect before the fix: 56
  `gameLens` rows, lanes `first1/first3/first5` only, `source: None`, **0 with
  `modelHomeWinProb`**.
- **The compute cost of a live game-line projection is ALREADY BEING PAID** — the
  MC runs on both workers today regardless. Publishing it is not new periodic
  work, which is what makes this cheap against the `#435` memory constraint.
  **The open question is precision, not existence:** 120 sims puts the standard
  error on a win probability near **4.6 pp** at p=0.5, which is display-grade and
  not edge-grade. `MLB_LIVE_GAME_MC_SIMS` is env-tunable (min 20).
  Full spec: `.syndicate/spec_live_game_line_projection.md`.
- **`live/nfl_live_lens.json` and `live/soccer_live_lens.json` are built every
  tick and NEVER published to web.** `live_lens_loop.py:150` builds five sports
  (`mlb, nba, wnba, soccer, nfl`); `artifact_publisher.py:433-435` allowlists
  three (`mlb, nba, wnba`). **The two omitted sports are in season; the
  allowlisted NBA is not.** That same publisher block already carries a written
  post-mortem of this exact bug for the three that ARE listed
  (`SKIP_NOT_ALLOWLISTED`, "just a plain missing entry") and records the cost:
  refresh-worker's fallback recompute had `prop_row_counts=[0]*9` across nine
  live games. **Two lines; needs no product decision.**
- **A working live game-line projector already exists — in soccer, unwired.**
  `soccer/features/live_lens.py` exports `project_live_match`,
  `goal_in_window_probability`, `project_live_player_props`, built on
  `match_simulator.simulate_match`'s `initial_state` hook. Reachable only from
  `scripts/backtest_soccer_live_lens.py` and `scripts/poll_soccer_live_state.py`,
  **neither scheduled** (no cron, no `render.yaml`, no worker import; the
  soccersim phase-1 report records the poller as never run). Costs zero compute.
  **"Build the live game-line projection" is therefore not green-field
  everywhere — name this asset in the decision rather than discovering it after.**

---


## [ask-the-syndicate] ASK THE SYNDICATE

**The LLM is off by decision. The deterministic snapshot path is the product.**

- **CURRENT BASELINE: 37/52** (advice 4/5, entity 9/10, explain 4/6, history 2/5,
  lookup 8/8, ranking 7/10, refusal 3/8), measured 2026-08-16 18:0xZ and again
  post-deploy with **zero pass/fail flips**, in
  `reports/ask_regression/{control_pre,post}_answer_substance_2026_08_16.json`.
  `answer_source: snapshot` is the EXPECTED source, not a finding.
  **This REPLACES the 38/52 recorded on 2026-08-15 — that figure was a different
  day's slate and had expired.** Re-measure a same-slate control before judging
  any change; a handed-down baseline is not a baseline.
  **The harness cannot see most of what the panel does.** `_score` checks
  refusal/routing/hallucination/certainty/50-50 and is blind to selection shape,
  units, price, sim terms, quote age and the rendered panel. Four deploys on
  2026-08-16 changed all of those and could not move it. **A flat score is
  therefore not evidence of no effect, and a large jump would be suspicious.**
- **Ask baseline RE-CONFIRMED after all six deploys, 22:2xZ on live `d8985df8`:
  37/52, ZERO pass/fail flips vs the same-slate control, every class identical.**
  `reports/ask_regression/post_all_deploys_2026_08_16.json`. One warning moved —
  `edge_without_market_probability` 0 → 25 — and it is BOARD DATA, not the Ask
  code: the board path's `edge`/`market_probability` are unchanged across all six
  deploys (`git diff ebd5f677 d8985df8`), while **4 of 10 edge-bearing rows now
  carry a `model_edge_pct` not derivable from
  `projection.{model_prob_over, market_fair_prob_over}` by either the direct
  difference or the complement** — including two rows where `row_side ==
  proj_side` so no complement applies and the direct figure is off by 64 and 19
  points. All `full/*_dist` bases. Owned by `layer2-board-quality`, notified.
- **ASK ANSWER SUBSTANCE — LIVE web `9bae928c` (2026-08-16 22:52:31Z).** The
  deterministic panel now: names the bet a human can place (market, line, side,
  price, book — not "Ryan Johnson"); generates its own reason sentences from
  `projection.projected` and `model_skill` (the MLB game lens is the model);
  publishes only rows where EVERY edge term it carries is positive; and reports
  a quote age that advances. `_bet_label` mirrors `layer2_board._pick_label` and
  is pinned by test — the two must not drift.
- **`quote_seen_age_seconds` IS STAMPED AT ARTIFACT BUILD TIME AND DOES NOT
  TICK.** Three reads of the live shortlist 45s apart returned byte-identical
  ages (`mlb=[12.9, 39.8] wnba=[47.1]`) while `written_at` sat at 20:15:41Z.
  **Every consumer of that field understates quote age by the artifact's own
  age** — real age is `stamped + (now - written_at)`. Ask corrects for it; other
  surfaces have not been checked. Its sibling `book_age_seconds` answers a
  DIFFERENT question ("has the price moved") and the board gates on the seen
  clock deliberately — see `layer2_board._row_quote_age_seconds`.
- **WITHDRAWN 2026-08-16 22:5xZ — "the board publishes sides that contradict
  its own projection" was MY error, not a board defect.** Chasing it to a root
  cause showed only **2 of 10** failing rows are explained by live-join
  staleness; the rest are a category error in the Ask reason generator.
  `projection.projected` is a **MEAN**, and what picks a side is
  **`P(X > line)`** — on a low-line count prop those diverge legitimately (a
  mean of 0.214 runs implies `P(>=1) ~ 19%`, which beats a market implying
  15%). **Do not re-open this against the board.** Ask now claims a direction
  only on GAME totals/margins, where the mean is the right statistic; on props
  it states the relationship as a fact. Fixed in web `9bae928c`.
- **STANDS, AND ITS ROOT CAUSE IS CONFIRMED — `model_edge_pct` is not
  comparable with `projection.{model_prob_over, market_fair_prob_over}` after a
  live join.** `live_gameline_join.py:643` overwrites `edge_vs_market_pct` with
  the LIVE edge while deliberately leaving `model_prob_over` at its PREGAME
  value (the live probability goes to a new `live_model_prob_over` key). The
  edge therefore refers to a different probability than the one beside it, with
  nothing in the field name to signal it. **7/7 separation on `live_aware`**;
  arithmetic exact — stated `-39.93` = `(0.1917 - 0.591) x 100`, where the
  pregame pairing gives `+27.46`. Every number is correct; only the PAIRING is
  wrong, which is why it is `full/*` only (segment bases are not live-joined
  and agree 3/3). Owned by `layer2-board-quality`, notified with the fix
  options. Consumers pairing those two fields must prefer `live_model_prob_over`
  when `live_aware` is true.
- **K1 SHIPPED AND VERIFIED** (`bef782cb`, live 20:01:18Z): 20/52 → 23/52,
  `refusal` 3/8 → 6/8, every other class byte-identical, declined-question
  latency 10.9s → 0.19s. **A refusal gate must be tested on what it must NOT
  refuse** — two regressions were caught only by testing the answer direction.
- **CURRENT PRODUCTION SCORE IS 38/52 `[measured 08-15 17:5xZ, live 1e44e1da]`.**
  **K6 IS NOT PART OF THAT NUMBER AND IS NOT LIVE.** Its fix `3ba1c2cf`
  ("source the as-of from `state_meta` too, because production has no
  `freshness` key") was cancelled mid-build at 19:20Z by a peer's deploy and is
  **still absent from live `7abd8e12` at 20:22Z, confirmed by patch-id**. It is
  built, tested and pushed as `deploy/ask-k6-2026-08-15` (`3d68dfe4`), never
  fired. So the ask lane's own `K6 RETRACTED AS INERT ON PROD` still stands:
  **no as-of predicate has been measured on production.**
  Pre-deploy control **25/52** (`reports/ask_regression/prebaseline_c774fe1a_2026_08_15.json`).
  entity **2/10 → 9/10**, lookup **4/8 → 8/8**, ranking **5/10 → 7/10**;
  advice 4/5, explain 4/6, history 2/5, refusal 4/8 all flat. **Zero classes
  regressed.**
  - **ATTRIBUTION: the gain is the `ask-sport-coverage` deploy**
    (`b6f1a2e6`/`0bf866c3`), NOT the web train that followed it. The train
    reproduced 38/52 and added the WNBA clamp and MLB live lens on top. Do not
    credit the train with 13 points.
  - **THE "23/52" BASELINE IS DEAD.** `post_m1_fixed_2026_08_14.json` is a
    ranking-only run with `total: 10`; that number existed only in prose and was
    propagated into three briefs. Use 25/52 as the pre-deploy control, or a run
    you took yourself.
  - Slate caveat, so a flat class is not misread as a failed fix: production was
    **nfl 60 / mlb 39 / wnba 6, zero soccer / ncaab / nhl**, so the soccer
    classes could not move on this measurement whatever the code does.
- **THE TWO-POOL DIVERGENCE IS CLOSED** — web `c774fe1a` (live 2026-08-15
  03:29:56Z), lane `ask-headline-from-board` CLOSED-VERIFIED. `M1`
  (`b16eb1f7`) only SUPPLEMENTED (`visuals.tables`) and left the headline on
  the snapshot, so chat and the board still read 23.81 vs 14.09.
  `_market_summary_schema` now sources `top_opportunities` from
  `read_layer2_shortlist` — the same artifact `/api/board/layer2-shortlist`
  serves. **Measured same-instant: chat 6.35 vs board 6.35, |delta| 0.000**,
  fingerprinted 5/5 rows carrying `source="layer2_shortlist"`.
  Two guards were bought with a rollback and must not be removed:
  the board REPLACES a non-empty `recommendations` pool and never CREATES one
  (an empty pool is the engine DECLINING — sourcing unconditionally answered an
  Ohtani stats question with NFL totals, refusal 4/8 → 3/8), and board rows
  carry explicit `edge_pct` because `edge` is a FRACTION on snapshot rows and a
  PERCENT on board rows (`Best edge 635.0%` served for 14 min).
- **SPORT COVERAGE FIXED AND MEASURED** (`0bf866c3`, live 16:49:28Z) — the
  08-14 finding above (soccer/ncaab had no branch, NFL required the FULL team
  name, wnba was a keyword inside nba) is CLOSED on the routing axis:
  **25/52 → 38/52, zero regressions, `no_sport_resolved_expected_*` 15 → 0.**
  entity 2/10 → 9/10, lookup 4/8 → 8/8, ranking 5/10 → 7/10. Board composition
  identical at both instants (150 rows, wnba 18 / nfl 42 / mlb 90), which is
  what makes the diff attributable. `[measured 08-15 16:52Z]`
- **BUT soccer / ncaab / nhl coverage is UNPROVEN ON DATA.** The board carried
  **zero rows** for all three at both measurement instants, so those cases pass
  on ROUTING only. Whether the new fetcher branches return anything useful on a
  real slate is NOT established — re-measure when soccer is on the board.
- **NFL nickname matching must NOT be copied to NCAAF.**
  `_ncaaf_teams_in_question` excludes mascots deliberately (~680 schools share
  "Wildcats"/"Tigers"). NFL is safe only because its 32 nicknames are unique
  (verified). `[from-code + measured 08-15]`
- **K6 CAUSE CONFIRMED AND FIXED IN `origin/main`, BUT NOT DEPLOYED.**
  `routed_sport` shipped and works; the as-of did not. `as_of` is populated
  **28/52** and `warn:no_as_of_stated` is **24** on the live tree — unmeasured
  and unmoved until `0050d1c4` reaches production. **Do not mark K6 closed.**
  **Cause (measured, not suspected):** production web runs
  `SYNDICATE_INTELLIGENCE_CANONICAL_BOARD_STATE = true` AND
  `SYNDICATE_INTELLIGENCE_COMBINED_BOARD_DEFAULT = true`, **while the comment at
  that call site still says the flag is "default off, so this is a no-op
  today".** That path (`read_combined_intelligence_response`) returns
  `state_meta` and **no `freshness` key at all** (`state_meta.computed_at` was a
  valid `2026-08-15T18:36:33Z`). `read_latest_intelligence_state` has FOUR return
  paths with DIFFERENT payload shapes, so anything reading `freshness` off the
  snapshot works on a dev box and is inert in production. The fix scans
  `("state_meta", "freshness", "state_freshness")`, matching
  `pipeline/intelligence_state.py`'s own order. `[measured 08-15 18:3xZ]`
- **K3's `build_evidence_pack` sport-filter item is DEAD CODE** — reachable only
  from the LLM engine, which never executes by standing decision. `[from-code]`
- **Chat reads the shortlist ARTIFACT directly**, so chat staleness IS artifact
  age. `[from-code]`
- **The system prompt's rules 5–8 (surface uncertainty, distinguish fact from
  projection, never fabricate, flag staleness) are now PERMANENTLY UNENFORCED.**
  They were the only place those rules existed; the deterministic path needs its
  own. That is a consequence of the decision, not a pre-existing defect.

---


## [ui-board-cards] UI / BOARD CARDS

- **Lane E is CLOSED-VERIFIED in production** (web `aadcde77`, live 21:42:56Z):
  horizontal overflow 28px desktop / 20–40px mobile → **0 at both widths** on
  nfl, ncaaf, soccer, ncaab; NCAAF default tab 0 panels/187px → 1 panel/556px;
  orphan tabs and unreachable panels → 0; mobile tab targets under 44px 64/48/4
  → 0; numeric classes `normal` → `tabular-nums`. `[measured 08-14 21:4xZ]`
- **Lane F is CLOSED-VERIFIED and live** (web `932a1f71`, then `a86eb4ed`):
  seven fabrication sites in `game_board_contract.py` are gone — an absent
  probability renders as an explicit empty state, a genuine 0.0 survives instead
  of becoming 50/50, and a projected scoreline is never recast as a win split.
  Soccer three-way markets carry a draw segment. One null placeholder (`—`)
  platform-wide: NCAAF hyphen cells 48 → 0, em dashes 0 → 144. `[measured 08-15 01:41Z]`
- **A 50/50 on the board now MEANS 50/50.** The one still served (NFL, DEN@KC)
  sits on a 0.4-point projected margin — the producer's own `home_win_rate`.
- **NCAAF kickoffs file on their CENTRAL day** — 28 of 157 real 2026 kickoffs
  were previously filed under their UTC day. **The platform's display timezone is
  Central everywhere**; `central_today_iso()` is the slate clock. An MLB slate
  spans two UTC dates; it does not span two Central ones.
- **`scripts/ui_layout_probe.py` is the durable instrument.** It reproduced the
  audit's before-numbers against the unchanged service, which is what makes its
  after-numbers a reading rather than a belief. **Synthetic `el.click()` is not
  used anywhere in it — the audit had to retract a finding produced that way.**
- **NBA / NHL / NCAAB serve 0 cards** in production and locally. Their rows in
  the divergence matrix are code-only. **Re-measure in October.**
- **Carried, not fixed:** the desktop strip still breaks long names mid-word in a
  ~52px box — a design decision that CONTRADICTS Lane G1's "raise soccer's 13px
  names to 16px", since 13px + ellipsis is the documented fix for that problem.
- **The prop-producer 0.5 fix is COMMITTED AND NOT ON ANY WORKER** — **SUPERSEDED
  08-15 22:2xZ: it is LIVE on both workers, by content. See the deploy section
  above; this paragraph is kept only for its local sizing numbers.**
  (`bd40056c` / origin `536dfcd0`). Local sizing: 6 of 4,240 probability rows
  were price-missing and every one carried a fabricated 0.5; **67 further exact-
  0.5 rows have real ±100 prices and are legitimate** — a blanket "no 0.5
  anywhere" rule would have destroyed real data. Production rate UNMEASURED.
  **Until a worker deploy carries it, production still fabricates.**

---


## [soccer] SOCCER

**Owner: `soccer-model-coverage` (new) for the model; UI Lane G for the card.**

- **Soccer serves ZERO shortlist rows and that is the INTENDED interim state,
  not an outage.** Its whole presence was one-book longshot props whose `ev_pct`
  was arithmetically `-assumed_hold_pct`. **Read `rows_uninformative_ev` before
  diagnosing soccer as broken** — soccer is ABSENT from `per_sport` rather than
  present at 0.
- **The A3 filter SELF-HEALS.** It keys on `fair_method`, so if soccer ever gets
  two-sided quotes the fair becomes `consensus` and the rows return with a real
  EV — no code change. `[from-code 08-14]`
- **Two endpoints disagree about projection coverage by 250×, same sport, same
  date, 45 seconds apart `[measured 08-14 19:1xZ]`:**
  `/api/board/layer1?sport=soccer` → 8,456 rows, 2,504 projected = **29.6%**;
  `/api/board/layer2-shortlist` → 8,512 rows, 12 projected = **0.1%**, with
  `rows_with_model_edge: 0`, `matches_in_source: 4`, `unmatched_match_rows:
  8,393`. **These are two different joins and at most one describes the board a
  user sees.** Settle this before raising coverage.
- ~~**SOCCER GAME ODDS HAVE NOT BEEN CAPTURED FOR ANY LEAGUE SINCE 08-10/08-11.**~~
  **SUPERSEDED 2026-08-17 21:3xZ — capture is WORKING.** `per_sport_ingest.soccer`
  on the served `/api/board/layer2-shortlist`: `quote_rows 16,044`,
  `candidates 8,355`, `dates_with_rows` spanning **08-17..08-23**. Whatever the
  08-14 outage was, it is over; do not re-diagnose it. The 08-14 note is kept
  struck-through rather than deleted because its *reasoning* (a healthy-looking
  league masked by `prop` rows from another producer) is still the right way to
  read that counter. **The vendor was never the cause** — all ten soccer keys
  `listed=True, active=True`.
- **THERE IS EXACTLY ONE PRODUCER and it is not refresh-worker.** `phase=pregame`
  builds 50 steps including 10 odds steps; `phase=live` builds 20 steps and **0
  odds steps** — and refresh-worker's soccer autorun runs `phase="live"`, so it
  never fetches soccer odds at all, by design since `#148`. Everything depends on
  `_launch_autorun_soccer_pregame_refresh` on live-odds-worker, 4h cadence.
  **Single point of failure.** `[measured 08-14 18:5xZ]`
- **WHY the step fails is STILL UNKNOWN.** No error has been observed anywhere.
  **Two hypotheses are DEAD — do not re-run them:** step truncation at #27 of 50
  (falsified by a ~6-step scoped run that captured nothing), and
  three-specific-leagues (all ten are affected). The `#433` step reorder is
  retained on its own merits but **must not be credited with fixing capture**.
- **The run's own logs are UNREADABLE FROM WEB** — `launch_refresh_run` spawns
  the child `stdout=DEVNULL, stderr=DEVNULL` onto the WORKER's disk, and Render's
  collector captures only a service's own stdout. That is the disk split, not an
  absence of logs, and it is how four days of failure produced no visible error.
- **The sim reports its own input is missing:** `SOCCER_PLAYER_ROWS_MISSING` on
  eredivisie, primeira_liga, championship. Observed once while looking at
  something else — **a lead, not a finding.** `[observed 08-14 19:25Z]`
- **Some markets can never carry an edge however good the model gets.**
  `player_shots` / `player_shots_on_target` map to a MEAN and `soccer_projections`
  refuses by design to derive a probability from a mean; the rows are one-sided
  so `_no_vig_over_probability` returns None. `player_to_receive_red_card` and
  `player_assists` are not in the market map at all.
- **MLS cannot be backtested from its current source at all.**
  `fetch_asa_mls_team_history` returns undated **season aggregates**, so a season
  average already contains the whole season and no `as_of` filter can repair it.
  The backtest returns `{}` for MLS with `AS_OF_DROPPED_UNDATED`. `[measured 08-14]`
- **`data/soccer_source/*/validation/*_backtest_*.csv` is NOT CITABLE** (leakage).
  Report soccer backtest accuracy as **unmeasured**. Production is unaffected —
  `build_soccer_artifacts` predicts forward.
- Soccer sims are ENABLED and running; one sim job = one league-date (`#282`).

---

- **The soccer projection read was ONE DATE against a SEVEN-DATE quote window**
  `[moved here 2026-08-18 from a WNBA state snapshot]`. `#379`'s widening shipped
  inert — its only caller never passed `window_dates`. Fixed (`b4d82364`), **NOT
  deployed**. `window="slate"` is required; the resolver defaults to `"day"`.
- **Soccer's `recommendations_<date>.json` is NOT in `HOT_ARTIFACT_PATTERNS`** —
  it lives under `soccer_source/<league>/api/recommendations/` while the allowlist
  covers `source_artifacts/data/processed/`. `/api/ops/artifacts/export` returns
  `count=0` for it. **`/soccer/<league>/api/cards` is the readable substitute.**

## [sharp-reference-price] SHARP REFERENCE PRICE — WE HAVE ONE. The audit's caveat is STALE.

**The models audit's "no Pinnacle, Circa or exchange in the feed" was true when
measured and is FALSE now.** The feed widened between 08-05 and 08-09 and nobody
re-read it. `[measured 08-15 from data/mlb_source/tracking/book_quotes/]`

| dates | distinct books | pinnacle rows | shard size |
|---|---|---|---|
| 07-28 .. 08-05 | **11** | **0** | ~13 MB/day |
| 08-09 | **37** | **2,604** | **217 MB/day** |

- **Sharp coverage on MLB GAME LINES is 102 of 102 markets = 100%** on 08-09.
  Sharp set present: `pinnacle`, `betfair_ex_eu`, `matchbook`, `novig`,
  `prophetx` (plus `kalshi` / `polymarket` as prediction markets).
- **Sharp coverage on PROPS is 0%.** Prop CLV therefore stays a soft-consensus
  measurement and **must be labelled as such**; game-line CLV can be taken
  against a genuine sharp close.
- **THERE IS ALREADY A PER-SPORT LEVER FOR THE PROP GAP, and NHL uses it.**
  `syndicate/local_nhl_odds.py:542` defaults
  `PROPS_ODDSAPI_BOOKMAKERS = "fanduel,draftkings,pinnacle"` — Pinnacle is
  explicitly requested for NHL props. `vendor/nhl_betting_repo/.../odds_api.py`
  carries it in a book list too. So closing the 0% on other sports' props is a
  **config change on an existing knob**, not a build. `[from-code 08-15]`
  **Cost it before flipping it:** every added book spends OddsAPI credits
  against a cap already at **92.8% projected burn**, and props are the highest-
  volume market family. Measure the per-call delta on one sport first.
- **This removes the standing caveat on the whole CLV program** — "beating a
  closing consensus of eleven soft books can read positive where no exploitable
  edge exists" no longer applies to game lines.
- **The widening is almost certainly the lost-books capture fix**, which also
  explains the 13 MB → 217 MB/day jump. That cost is real and it is what the
  storage-format work (delta/columnar) exists to absorb — **do not "fix" it by
  narrowing the book set again; price shopping was measured at +2.79 ROI pts.**
- **Caveats, stated:** read from the git-tracked mirror, which is lossy, and
  only ONE post-widening date exists locally (08-09). **Confirm against
  production before publishing a sharp-referenced CLV number**, and re-read
  whether the 37-book set is still current.

---


## [layer1-layer2-boards] LAYER 1 / LAYER 2 BOARDS — session briefs exist; three facts worth not re-deriving `[code read 08-16 11:2x CDT, NOT a production measurement]`

Full briefs: `.syndicate/brief_2026-08-16_layer1_board.md`,
`.syndicate/brief_2026-08-16_layer2_board.md` (commit `01c53f56`). Lane names
`layer1-board-coverage` / `layer2-board-quality` are RESERVED BY BRIEF and
deliberately NOT opened in `lanes.md` — no session holds them yet.

- **L2 movement/steam is DISABLED IN CODE, not decayed by data.**
  `layer2_board.py:1152` is `return {}` with an unreachable body. `#372` turned
  it off because the in-builder ~20MB odds-history load **stalled the shortlist
  build for 70 minutes with no exception**. Naive re-enable re-stalls the board.
  Only `h2h`/`totals`/`spreads` have history at all (`:1244`); served overlap was
  event+market 11 of 73.
- **The L2 scoring model EXISTS** — `blended_score()`,
  `opportunity_signals.py:497-575`, `min(value, value*reliability)`. Auditing it
  is the work; rebuilding it is not. The `min()` is load-bearing (it corrects a
  sign inversion on negative-value rows, `corr -0.8312` vs `+0.8560` control).
- **Layer 1 already publishes its own projection-coverage instrument** — the
  header's `N markets / M with a projection`, via `_classify_enrichment`
  (`layer1_board.py:328`) / `_row_is_enriched` (`:176`). Do not build a second.

**NOT established, and stated here so it is not cited as if it were:** "Layer 2
has no book allowlist" is a **negative from a grep over one file**. Layer 1's
list IS confirmed (`DEFAULT_BOOKS`, `templates/shared/layer1_board.html:267`,
client-side JS). Trace the served `book` field to its writer before acting.


## [board-intelligence-engine] BOARD / INTELLIGENCE ENGINE — structural facts, archived

Moved to `state_archive.md` 2026-08-15. Every figure in it is also in
`audit_2026-08-14_board_engine_SYNTHESIS.md` (verified by spot-checking
238,071 lines / 24 import cycles / 164 of 390 / 42 sites) — that audit is
the place to read it, and it carries the guard on its two shortlists.


## [football-smartsim2] FOOTBALL (NFL + NCAAF) — smartsim2 runs on FOUR SCALARS `[measured 2026-08-18, lane football-model-owner]`

**Owner: `football-model-owner`.** Full reference:
`docs/ai_context/football_sim_engine_reference.md`. Gate:
`py -3 scripts/football_sim_input_checklist.py --season 2025 --week 1` (exits 1).

- **The engine consumes 9 feature blocks / 65 keys out of
  `feature_generation_payload`, and 0 of 3 production entrypoints pass one.**
  Every NFL and NCAAF game served runs on `home/away_offense_rating`,
  `home/away_defense_rating` and a hardcoded `pace_seconds_per_play=24.0`.
  `returning_production_index` 0.5 / `coach_continuity_index` 0.5 /
  `player_usage_index` 0.25 / `market_prior_index` 0.5 are constants carried
  identically by every game.
- **Reachability measured, not inferred:** 21 of 21 drive-prior fields move when
  fed. 400 seeds/arm → margin −1.125, total −1.685, home win% **−6.50 pts**.
- **DO NOT SIMPLY WIRE IT.** Both calibration profiles were fit against a payload
  the engine cannot read, so this is a mechanism added to a calibrated engine and
  owes a **re-fit** (`model_engine_standard.md` §4.4 — negative interaction in
  4 of 4 markets measured elsewhere). Those deltas are the DISTURBANCE, not the
  improvement. `#457`.
- **Three unfed blocks, three DIFFERENT remedies — do not batch them.** Over 272
  real NFL games: `defensive_metrics` **MISROUTED** (all 7 keys sit in
  `team_metrics` at 100%), `pace` **NULL AT SOURCE** (all 4 keys `None`),
  `player_usage` **WRONG GRAIN** (19,400 player rows exist; no game-level block;
  `adapters.py:_team_player_usage` already aggregates correctly and nothing
  consumes it). `offensive_metrics`/`advanced_metrics`/`market_features` are
  **100% fed**.
- **NCAAF SERVES 16 GAMES AND THE MODEL IS NULL ON ALL 16** `[measured against
  PRODUCTION 2026-08-18]`. `predictions.home_mean/away_mean/margin_mean/
  total_mean` and all six probabilities are `null`; `smartsim_reasons` `[]`.
  **Cause: `CFBD_API_KEY` is ABSENT on all three services** (live env-vars, not
  `render.yaml`); `generate_smartsim2_ncaaf_projections.py:57` raises, the
  autorun dies, the artifact is never written. Logs: **21 of 21
  `SEASON_PROJECTION_ARTIFACT_MISSING` are `sport=ncaaf`, 0 `sport=nfl`** —
  positive control. `interval_seconds=86400` → **once-daily, NOT a relaunch
  loop, not burning worker cycles.** Two-arm test: no key → `RuntimeError`;
  with key → 99 games → 51 FBS-vs-FBS → 136 PPA teams → 50/51 rated.
  **Everything downstream of the key works**, incl. `#445`'s guard (verified by
  CONTENT in deployed blob `00e9a49f`). **Season opens 2026-08-29.** Deploy
  request filed: `.syndicate/deploy/requests/20260818T154432Z-football-model-owner.md`.
  `#458`.
- **DO NOT diagnose NCAAF from a local checkout.** `load_features(sport="ncaaf")`
  returns **0 games locally** while production serves 16. I filed that local zero
  as a production defect and retracted it. `data/**` lossy mirror, as CLAUDE.md
  says.
- **FIXED, DEPLOYED AND MEASURED 2026-08-18 18:48Z: the NCAAF board was capping
  the slate at 16.** Live on web as `5fdabc46` (cap) + `4c3b0aa5` (its counter).
  **Served payload, six weeks: 16 -> 51 / 49 / 57 / 56 / 56 / 66, with
  `games == runtime_rows`, `truncated: false`, `dropped: 0` on every one.**
  **Week 1 = 51 = CFBD's independent FBS-vs-FBS count** — cross-source
  agreement, not merely a bigger number. Max slate 66 vs the 80 guard.
  **The alternative is dead:** `runtime_rows` of 49-66 proves the summaries
  always held a full slate, so the 16 was entirely the cap. Had `runtime_rows`
  read 16, the cap would have been exonerated — which is why the counter shipped
  WITH the change, not after it.
- **The cap fix's own INSTRUMENT shipped inert, and it was the SAME defect.**
  `board_row_counts` was absent from the payload while the fix worked, because
  `build_game_board_api_payload` **whitelists** response keys.
  `apply_game_board_contract` does preserve extras (`dict(context)`) — **it is
  not the last hop.** Presence in the context is not reachability to the client,
  exactly as presence in `_collapse_games` was not reachability to the board.
  Twice in one change.
- **`deploy_preflight --service web` can NEVER return CLEAR** — web does not emit
  `ALL_PROCESS_MEMORY` at all (sample 3.9 days old, predating the live deploy).
  Positive control: refresh-worker on the same instrument reads **7s**. A
  break-glass grant was used, user-authorised, with a live `/api/ops/memory`
  process read substituted as better evidence. **OWED: make web emit it** so this
  does not need a grant every time.
- **`/portdetectorv2` is RENDER PLATFORM INFRA, not a job**, and it appears
  *because* you just deployed — so a name-based idle check blocks the second
  deploy of every pair. `deploy_preflight` classes it `[infra]`. Same for pid 1
  `bash /home/render/graceful-shell-command.sh`. **Classify by cmdline.**
- **SUPERSEDED (was: the deploy-ordering hazard).** The board fix is live BEFORE
  the key, which is the order that was required. The SmartSim2-standalone branch
  can no longer truncate ~51 rows to 16 when the artifact starts existing.
- ~~**FIXED (`752a866d`, UNDEPLOYED): the NCAAF board was capping the slate at 16.**~~
  Weeks 1/2/3/5/8/12 all served exactly 16; CFBD lists **51** FBS-vs-FBS for wk1.
  16 = 32 teams / 2 — an **NFL-shaped number**, correct for NFL, wrong for a
  50-60 game sport, which is why it was invisible. **THREE caps on three branches
  of the same page**; the route calls `build_smartsim_cards_page_context`, NOT
  `build_cards_page_context`, so fixing `_collapse_games` alone would have been
  INERT. `_NCAAF_BOARD_GAME_LIMIT = 80` — raised, not removed (~9.8 KB/game, 2GB
  web service). Truncation now self-reports via `board_row_counts` on the payload
  (present whether or not it bit) + `NCAAF_BOARD_TRUNCATED` on web stdout.
- **DEPLOY ORDERING IS LOAD-BEARING: web (`752a866d`) FIRST or together, THEN the
  key.** The SmartSim2-standalone branch is empty today only because the artifact
  is missing; the moment the key lands it returns ~51 rows, and the old `[:16]`
  would cut them back to 16 **with `verify:` passing**. Key-alone is the one
  combination to avoid.
- **RENDER IS THE SOURCE OF TRUTH — now MANDATORY in
  `model_engine_standard.md` §3b** `[user directive 2026-08-18]`. Every claim
  must name its substrate and that substrate must be Render. Also: an input NOT
  in `HOT_ARTIFACT_PATTERNS` is UNAUDITABLE — NCAAF's `recommendations_summary`
  (the artifact its board renders from) is not allowlisted. **Owed.**
- **There are TWO unrelated football models.** `FootballSimulationAdapter`
  (`adapters.py:110`) is a closed-form linear formula that **never calls
  smartsim2**; its callers are all offline analysis. smartsim2 is the only
  user-facing one. `NflAdapter`/`NcaafAdapter` have zero non-self callers.
- **`smartsim2/calibration_profile.py` showing as `M` in `git status` is NOT
  orphaned work** — it is `964c89a4`, already on `origin/main`.

**NOT AUDITED** (so not a clean bill): `SYNDICATE_DATA_ROOT` backing,
`HOT_ARTIFACT_PATTERNS` allowlisting, reuse-flag rebuild procedure, and a
market-relative scoreboard.


## [nfl-archived] NFL — earlier closed work, archived

Moved to `state_archive.md` 2026-08-15. Closed work; the rules it records
generalise but are not current state. `#377`, `#425`, `#429`.


## [test-baselines] TEST BASELINES

- **`tests/test_intelligence_state.py` is NOT "224 green" — that line was wrong
  and is corrected here.** It carries **2 pre-existing failures on BOTH sides of
  the reconcile** (`..._fallback_merge_falls_back_on_empty_pool`,
  `..._recomputes_when_cached_snapshot_is_stale`), verified by swapping each
  side's source + test file into one worktree. On the **deployed lineage** it is
  **218 passed / 6 failed** (measured at `2b14fbeb`). **Gate against the lineage
  you are shipping, not against `main`.** `[measured 08-14/15]`
- It costs **~15 minutes**, so it is not a quick check.
- **`tests/test_intelligence.py` is 218 passed / 0 failed on committed `main`**
  `[measured 08-15 ~21:5xZ, lane red-intelligence-tests]`. It was **216/2** at
  the start of that session and 217/1 mid-way. All three reds were real, and
  **two of the three were product defects, not stale tests** — see
  `todo_closed.md` `#436`/`#438`. **It costs ~37 minutes**, single-threaded;
  `pytest-xdist` is NOT installed, so there is no faster path today.
- **The "526 passed, 0 failed" line below is NOT contradicted by that, but it is
  narrower than it reads.** Three `test_intelligence.py` failures existed on
  committed code at 08-15 21:00Z, so whatever that full-suite run covered, it
  either predates them or did not include this file. Treat it as unverified for
  `test_intelligence.py` specifically; the line above is the direct measurement.
- Full suite: **526 passed, 0 failed** after the soccer `as_of` fix `[08-15]`.
- `tests.test_archives` (what CI runs) — 383 pass.

---


## [open-problems] OPEN PROBLEMS

- **The refresh-worker anon floor is UNNAMED** (`#423`). Allocator, GC-tracked
  objects, the board build and the MLB cards cache are all eliminated.
- **The 20:03:11Z OOM is UNEXPLAINED**, and the 3000 MB floor in front of MLB
  stays until it is.
- **Why the soccer pregame odds step fails is UNKNOWN.** No error observed.
- **Something allocates 493–878 MB in-process on refresh-worker and nothing knows
  what** (`#327` residual). Released within ~72s, arriving 11–42 min apart.
  `post_mlb_sim_tick` is a BYSTANDER. **Only counts have been measured, never
  bytes.**
- **`#312`'s `sync: false` protection is on `main` and live on NOTHING**, and the
  `blueprint_sync` mechanism remains untested — the only deploy carrying it was
  cancelled. That is the wrong experiment, not a null result.
- **Chronic instance restarts across the fortnight**, instance count dropping to
  0, pegged CPU. Cause unconfirmed.
- **MLB sim model-side as-of-ness is UNKNOWN.** The backtest is PIT-safe by
  replay, which says nothing about the model's own inputs.
- **NBA / NHL / NCAAB feature point-in-time status UNKNOWN** — no harness reaches
  them.
- **NHL and soccer market anchoring** make those engines' market-relative
  evaluation partly circular. Quantify before believing any CLV number for them.

- **`/api/ops/clv/report` WORKS AS OF 2026-08-15 19:36:45Z, and it produced this
  system's first unbiased CLV number.** It had been blind: the route runs on
  **web**, `load_openings` is a `path.exists()` on a local file, and web was
  answering refresh-worker's publish with `HTTP 403 FORBIDDEN` because web's
  `HOT_ARTIFACT_PATTERNS` lacked `reports/intelligence/clv_openings/*.jsonl`
  while the worker's had it. Shipping that one allowlist line to web
  (`bebe87c9`; also `baec34a8` on main — it had existed on NO main branch)
  flipped `PUBLISH_FAILED`×8/16h to `PUBLISH_OK` 15s after deploy, zero failures
  since. MLB 2026-08-15: `openings 0→520`, `resolved 0→293`, `same_book_n 0→144`.
- **CLV ON 2026-08-15 IS `-0.2714` (n=151, beat 27.2%), MLB, same-book AND
  pregame.** Web `c8810f45` live 21:58:19Z. Verified by recomputing the mean from
  the served rows at the same instant (`-0.2714` both ways). **PRELIMINARY —
  taken 21:5xZ, before the last first pitch (2026-08-16T01:40Z). NOT the settled
  number; the settled read was never taken (see OWED, below).**
- **THREE JOIN DEFECTS FOUND AND TWO FIXED, in order of severity:**
  1. **FIXED — `observed_transition` was side-blind.** `closing_price` is
     `entity`'s price and **`entity == home_team` on 18/18** stamped markets, so
     every away-side opening was differenced against the HOME close. A stamp is
     now used only when the opening IS the entity's side, else it falls through
     to the side-aware `last_pregame_quote` path. Measured: 20 refusals,
     `observed_transition` 48 -> 22, `same_book_n` 131 -> **151** (rows that were
     being discarded now resolve correctly).
  2. **FIXED — the headline counted in-play prices.** `close_age_seconds` is
     `(commence - stamp)`; negative means post-first-pitch. Now excluded and
     reported as `by_close_timing`. **The in-play bucket flipped sign between
     readings (-ve at 21:1xZ, `+0.7937` at 21:4xZ), so it was NOISE, not a bias**
     — the old code would have published `-0.0124` at 21:4xZ.
  3. **NOT FIXED — the odds-history feed transposes `home_line`/`away_line`.**
     Event `69928d29…` FanDuel spreads carried identical prices (`-205`/`+168`)
     under OPPOSITE labels at 06:02Z and 21:26Z. The line guard checks numeric
     equality, so it matched the wrong bet. **Severe per row, self-cancelling in
     aggregate** (the two extremes are a mirror pair; spreads n=42 mean `+0.515`
     median `0.000`; h2h/totals n=128 have zero |clv|>10). Corrupts
     per-recommendation CLV, variance, CIs and any "worst bets" list.
- **`clv_pct` per recommendation is NOT built** — the lane's original goal. The
  ledger's `PredictionResult.clv_pct` field exists and is never populated, which
  is why `/api/portfolio/summary` returns `avg_clv: null`.

- **Lane markers are per-session as of 2026-08-15.** `lane-guard.py` reads
  `.syndicate/.current-lane.<session_id>` first and falls back to the shared
  `.syndicate/.current-lane`. Write your slug to YOUR file; the global one is
  contended by every live session and will block edits to your own lane's
  files. Verified: global-only still blocks, per-session allows own lane,
  per-session naming a different lane still blocks.


## [shipped-verified] SHIPPED / VERIFIED — current status by item `[2026-08-18; replaces a dozen dated snapshot sections]`

One line per item. Where a thing is live, the SHA is the one that carries it, not
`main` — the three services run separate lineages and `main` is on none of them.

| item | status |
|---|---|
| refresh-worker OOM | **FIXED** `59c07221` + `8e3d2f95`; slow ratchet remains |
| odds-sweep ownership gate (`20025cc4`) | **HALF-WORKING** — fires on live-odds-worker (`kept=mlb,wnba,soccer dropped=nfl,ncaaf`), NOT reached on refresh-worker. `#129` reads OPEN again. |
| WNBA phase-2 autorun | **INERT** — launcher fires, `launched=ok runStamp=None artifactsDir=None`, `MAIN_ENTRY` never appears. Reproduced across two boots. |
| soccer live lens (`6bdc50de`) | **FIXED** — 7 leagues → 10; the three that vanished were exactly the three with matches in play |
| soccer projection window (`6aaa11af`+`b4d82364`) | **READ FIXED, JOIN NOT** — 30 artifacts across six dates, `matches_in_source` 3 → 99, but `rows_with_projection` still 4 of 1,142; 1,138 unmatched |
| soccer live-lens observability (`461774cb`+`481de91d`) | live both workers; **emits only on failure**, so no reading yet |
| monotone props seal (`bafb4fb2`) | **ROLLED BACK** at its requester's sequencing objection; 08-19 cadence read is unconfounded |
| MLB live game-line model | **SCORED — the model LOSES to the market** on every population |
| soccer model | **LOSES to the market** — multiclass Brier 0.5875 vs 0.5737, worse in 8 of 9 leagues; errors sit on FAVOURITES |
| `#445` NCAAF season projections | FIXED, **not deployable until the season opens** (~08-29) |
| `#455` / `#456` | both FIXED; deploy state per service, check by content |
| game shape | contract for five sports, **n = 0** — emit still blocked |
| play-by-play coverage | **5 sports of 8** |
| WNBA pbp | **not a corpus** |

## [fleet] FLEET `[2026-08-18 02:1xZ — goes stale in minutes; re-read before deploying]`

    web               e5107913
    refresh-worker    00e9a49f
    live-odds-worker  cdaeaa58

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

## [mlb-resim-rules] 2026-08-17 01:3xZ — VERIFIED (sim-scheduling): the real MLB re-sim rules

`_mlb_daily_sim_decision()` (`live_refresh_loop.py`, 230 lines, every tick).
Blocks first: `disabled` / pipeline deferral / `previous_run_still_active` /
`odds_refresh_active` / `insufficient_memory_headroom`. Then, first match wins:
`no_games_scheduled` -> `first_appearance` (own backoff) -> `tip_off_window`
(default 30 min, **once per game**, deliberately falls through) ->
`within_check_interval` (**default 600s, floor 60s**) -> merged
`fingerprint_change` / `join_mismatch` / `board_missing` / `props_now_available`
-> `evening_next_day_sim` (**default OFF**).

**THE 600s INTERVAL IS A FLOOR, NOT A SCHEDULE.** Past it, any input-hash diff
relaunches. Measured triggers 23:03:50 / 23:17:31 / 23:32:20 / 23:44:11 /
23:56:58, all `fingerprint_change`, ~12-14 min apart. Nothing is clock-anchored.

**A `fingerprint_change` launch is SCOPED to changed games and never reaches the
top-props stage** — the function's own comment records `daily_top_props` holding
zero rows for 11+ hours because of it. The trigger that fires most often
regenerates least.

**THE MEMORY GATE NEVER FIRES.** 12 parsed `MLB_SIM_TICK` decisions from 23:00Z:
`insufficient_memory_headroom` **0**, and no decision carries a `memory` payload
— on a service OOM-killed every ~12 min (`#449`). The dominant suppressor is
`intelligence_pipeline_busy`, checked ABOVE the memory gate, so the gate is
usually unreachable. **Unresolved:** unreachable vs miscalibrated. Do not assume
that guard is doing work.

**Deployed:** web `763a2f66`, live-odds-worker `c348da53`, refresh-worker
`4ec66498` (01:23:37Z, another session) — which DESCENDS from my `7623a233` and
retains Phase 1c and the reconciliation guard. The convergence held.

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

## [mlb-pitch-mix] MLB CONDITIONAL PITCH MIX — MECHANISM VALIDATED, MARKET SILENT `[2026-08-18]`

- **Engine picks pitches by count bucket and batter hand**, not one season vector.
  `simulate.py` both selection sites; artifact
  `data/conditional_mix/conditional_mix_<season>.json`; Dirichlet shrinkage
  toward (own season mix x league cell tilt), **k fitted out-of-sample**, builder
  REFUSES to write if it loses to either baseline.
- **VALIDATED ON REAL GAMES, no RNG anywhere**: out-of-sample (built through
  06-30, scored on games from 07-01), **395/512 pitchers (77.1%)** beat the
  season vector; log-loss **-6.21%**; within-count TVD median 0.3064 -> 0.2542.
  **Reproducible to the digit.**
- **MARKET: NO DETECTABLE EFFECT.** Two seed pairs at 1920 sims: mean -0.00097
  and +0.00001. **Measured** noise floor 0.00064; effect/floor **0.75**.
  Resolving it needs ~112x the original volume for <=0.0005 Brier. **Not worth
  buying.** Both statements are true — the engine pitches like reality, and the
  price does not notice.
- **THE SWEEPER HAD NO HOME.** `ST` (8.20% of pitches) mapped to `OTHER` or was
  DROPPED in all three code->PitchType maps. **34.5% of pitchers lost a pitch
  type carrying ~23.8 usage points** — often their primary breaking ball. One map
  now: `sim_engine/data/pitch_codes.py`. Appliers merge on collision —
  **probabilities SUM, multipliers AVERAGE by usage.**
- **`GameConfig.crn_pa_seeding` IS BROKEN — DO NOT ENABLE.** Inflates run scoring
  8-35%. Default off, marked in place.
- **The market harness cannot resolve <~0.003 Brier at 120 sims.** Never report a
  single-seed delta from it as a result.

### SOCCER RATINGS ARE A DETERMINISTIC TRANSFORM OF xG — VERIFIED ALL NINE LEAGUES 2026-08-18

- **`attack_rating` and `defense_rating` carry no information beyond `xg_for` /
  `xg_against`.** Measured across every league with history: **|corr| >= 0.98 on both
  sides in all nine, four at exactly +/-1.000**. The not-quite-1.000 values are the
  `_RATING_CAP` clamp biting on outlier teams, not independent signal.
- **CONSEQUENCE, and it generalises beyond the term already removed:** any feature
  derived from goals or xG is ALREADY IN the ratings. `build_possession_priors`
  averages its metrics index with `0.5 + attack_rating`, so such a feature enters
  twice. `94578cbc` removed the two explicit xG terms; **check this before wiring any
  further goal-derived metric into `possession_priors`.**
- **`corr(xg_for, shots_per_match)` is +0.83..+0.93 in all nine leagues.** Shots is
  the weakest surviving term in `_attack_strength` (weight 0.016) and is 83-93% the
  same signal as the rating. Not removed — pending evidence it earns nothing.
- **CAVEAT ON ALL OF THE ABOVE:** measured as the pipeline computes ratings TODAY,
  where `xg_for` IS goals on the football-data path
  (`team_rows_from_match_history`). A real xG source whose values diverge from goals
  would weaken these correlations and could earn the dropped terms back. That is why
  the now-unread `xg_for_per_match` / `xg_against_per_match` keys stay populated.
- **The dispersion question is NOT yet answered.** A 16-fixture probe returned
  stdev(P home) 0.1765 against baseline model 0.1575 / market 0.1811, but its 95%
  band (0.1133..0.2397) contains both — the effect is smaller than the instrument's
  noise. **Do not cite 0.1765 as evidence the under-dispersion is fixed.**

## [live-sha-authority] LIVE SHAs — ASK THE SERVICE, NOT THE LEDGER `[2026-08-18 ~21:2xZ]`

**`GET /api/ops/version` on the running service is the ONLY authority.** It
reports what is executing. Everything else in this file is a record of a deploy
that happened, which is a different question.

- **web = `841b6d84`** ("scoped deploy: NFL preseason projection means +
  provenance"), read from `/api/ops/version`. **NOT an ancestor of `origin/main`.**

**THREE DIFFERENT VALUES WERE IN CIRCULATION FOR WEB TODAY**, and two of them
were wrong in a way that survived review:

    fa1871cf   this file, "DEPLOYED 2026-08-16 TO ALL THREE"   <- TRUE HISTORY,
               but I read a dated deploy record as the current SHA. My error,
               not the ledger's. A deploy record is not a state reading.
    0bf866c3   another lane's note                             <- also not live
    841b6d84   /api/ops/version                                <- ACTUALLY LIVE

I cut a deploy branch off `0bf866c3` on the strength of the second one. **It was
built on the wrong parent and was never pushed** — no harm done, but a deploy
from it would have reverted whatever `841b6d84` carries.

**Render reports web as `branch: main` while running a non-main SHA.** A deploy
triggered without an explicit commit id takes main's tip: measured today,
**1,042 commits / 451 files / +190,277 lines** against the live SHA. Always name
the commit.

**The `/deploys` REST read is blocked by `deploy-guard.py`** — it matches the URL
path, so even `GET .../deploys?limit=2` is refused as "a Render deploy". Use
`/api/ops/version` instead; it is a better source anyway.

### Live web ALREADY carries `clv_openings`

`841b6d84`'s `HOT_ARTIFACT_PATTERNS` contains
`reports/intelligence/clv_openings/*.jsonl`. So the CLV lane's 403 was diagnosed
against an OLDER web, and `deploy/clv-openings-allowlist` may now be redundant
for that pattern. **It does NOT carry the five MLB sim patterns**, which are
still genuinely absent — `conditional_mix` etc. return `count: 0` and `POST
/api/ops/artifacts/publish` still 403s.

## WEB `055dfc67` — THE FIVE MLB SIM ARTIFACTS ARE IN PRODUCTION `[2026-08-18 22:54:51Z]`

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

## CORRECTION — THE DEAD PREFLIGHT IS A DELETED EMITTER, NOT MISSING `psutil` `[2026-08-18]`

**Supersedes what I wrote three times today** — in the break-glass grant, in the
web-deploy state entry above, and in the session checkpoint. All three name
`psutil` as the cause. **They are wrong.**

**MEASURED:**

    00e9a49f  (live refresh-worker, 420 commits old)
        memory_observability.py -> 3 hits, INCLUDING print(f"ALL_PROCESS_MEMORY...
    origin/main (what web runs after `055dfc67`)
        memory_observability.py -> EMITTER GONE
        survivors are CONSUMERS ONLY: deploy_preflight, check_worker_memory_gate,
        diagnose_sim_pipeline

**The emitter was DELETED somewhere in those 420 commits.** `psutil_available:
false` on web is real but INCIDENTAL — procfs enumeration works there (4/4
processes, and `/api/ops/memory` returned full process data to me). The signal is
missing because **nothing prints the line any more.**

**INSTALLING `psutil` WOULD HAVE CHANGED NOTHING** while looking exactly like a
fix: a shipped dependency, a plausible story, and a gate still returning UNKNOWN.

**THE TRAP THIS LEAVES.** refresh-worker's CLEAR preflight is an ARTEFACT OF
STALENESS — it emits only because it runs old code. **The moment the worker is
brought onto main (which is the correct thing to do), its preflight goes UNKNOWN
too and NO service can gate a deploy.** Whoever modernises the worker walks into
this.

**THE ACTUAL FIX:** restore the emitter. It exists verbatim at
`00e9a49f:syndicate/features/shared/memory_observability.py`. Contract: a log
line `deploy_preflight.py:parse_processes` can parse into `{pid, ppid, rss, cmd}`.
Re-adding the periodic call must respect the standing rule that **worker periodic
work is never free** (`#241` caused a production restart loop; ~1.4GB headroom).

## RETRACTION — "THE EMITTER WAS DELETED" IS ALSO WRONG. CAUSE IS **UNKNOWN**. `[2026-08-18]`

**Supersedes the CORRECTION section immediately above.** That section says the
`ALL_PROCESS_MEMORY` emitter was deleted from `memory_observability.py`.
**It was not. It is intact on main**, byte-identical to the 420-commit-old worker:

    memory_observability.py:1944  def log_all_process_memory(...)
    memory_observability.py:1952  print(f"ALL_PROCESS_MEMORY {json.dumps(...)}",
                                        file=sys.stderr, flush=True)

**HOW I GOT IT WRONG:** `git grep -l 'ALL_PROCESS_MEMORY' origin/main -- '*.py'`
piped through `head -4` returned four `scripts/` paths. **I read a TRUNCATED list
as an EXHAUSTIVE one** and concluded the file was absent from it.

**FOUR ROOT CAUSES CLAIMED FOR ONE SYMPTOM, THREE OF THEM WRONG:**

    1. "the sampler is broken"        NO
    2. "psutil is not installed"      NO -- real, but incidental; procfs works
    3. "the emitter was deleted"      NO -- it is at :1952, intact
    4. actual cause                   **UNKNOWN. Do not add a fifth guess.**

**WHAT IS ACTUALLY ESTABLISHED**, and it is only this:
- the emitter exists and prints when called;
- `log_all_process_memory()` is called from live-lens loops,
  `scripts/refresh_odds_sources.py`, and elsewhere;
- **refresh-worker emits every ~17s. Web has not emitted since 2026-08-14.**

**THE QUESTION IS WHICH CALLER RUNS ON WEB AND WHY IT STOPPED** — not whether the
code exists. First place to look: **loop ownership moves between services via env
flags with NO DIFF** (`_mlb_refresh_tick_owner_here` and friends), which is
already a recorded trap. A web-side caller may simply have been handed to a
worker.

**DO NOT ACT ON A CAUSE FROM THIS FILE UNTIL SOMEONE TRACES THE CALL SITES.**
Acting on cause 2 would have shipped a `psutil` dependency that fixed nothing and
looked exactly like a fix.
