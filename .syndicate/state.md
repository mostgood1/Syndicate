# Syndicate — Verified System State

> **Overwrite lines here as facts change. Do not stack contradictions.**
> Every line carries an evidence tag and a date. Untagged lines are invalid.
>
> **COLLAPSED 2026-08-15 (2026-08-14 ~22:0x CDT), 120.8 KB → this.** The file
> had 51 sections and was stacking rather than overwriting — `#387` appeared in
> six with contradictory statuses. **Nothing was deleted:** the complete
> pre-collapse file is `.syndicate/state_archive_2026-08-15.md`. Grep it before
> concluding a fact was never measured; never cite it as current.
>
> **The rule that keeps this file useful:** when you learn something here is
> wrong, EDIT THE LINE. Do not append a newer section that contradicts it. The
> reasoning trail belongs in `deploys.md` (append-only measurement log), not here.

## HOW TO USE THIS FILE

Facts only, grouped by subject. If a subject has an owning lane, it is named.
`lanes.md` says who holds what; `learnings.md` carries the rules; `deploys.md`
carries every measurement with its working. Program sequencing is
`.syndicate/plan_2026-08-14_program.md`.

---

## LIVE SESSIONS AND LANES `[re-measured 2026-08-15 03:0xZ / 22:0x CDT]`

**Six work sessions are live in one shared worktree.** Census taken with
`list_sessions include_archived: true` — the default call HIDES archived
sessions, so "ended" and "never existed" look identical. **A session's own
liveness moves mid-census**; re-read before relying on a row.

| session | plan / lane |
|---|---|
| Ship refresh-worker branch | program Tier 0/4 — `#435` OOM, `memory-watchdog-435`, `mlb-hydration-oom-435`, `mlb-oom-outlier-2003z` |
| Orphaned lanes cleanup | ledger hygiene (`lanes_closed.md`) + `ask-headline-from-board` |
| UI plan Lane G | UI plan G (soccer card) + H (probe harness) |
| Ask deterministic coverage | ask plan K2/K3/K4/K5/K6/K9/K11 |
| Tier 3a probability substrate | program Tier 3a differential test |
| Tier 5 pre-work | program Tier 5 — the `live`-named modules (**30, not 16** — see below) |
| Build the soccer model | `soccer-model-coverage` |

**THE MODEL PLAN HAS LOST ITS OWNER TWICE.** "Audit 2026-08-14 models (fork)"
archived **02:52Z** still holding `recommendation-lane-correctness` (7 file
claims, enforced) and `clv-without-settlement`. **It never consumed the two
user decisions queued to it** — it ended first — so anything in those lane
bodies predates them. The decisions themselves are safe in
`plan_2026-08-14_models.md` (`6cb7a136`). A replacement session is being stood
up; whoever takes it must `/lane open` both and RE-TAKE the files rather than
assume the claims hold. `[measured 08-15 03:0xZ]`

**`.current-lane` CANNOT REPRESENT PARALLEL SESSIONS — this is the root cause of
lane thrash.** One single-valued file, N sessions. `lane-guard` compares a slug
against it, so whichever session wrote last is the only one whose own edits are
permitted; every other session is blocked from ITS OWN lane. `[measured 08-13]`

**Commit through an ISOLATED index (`GIT_INDEX_FILE`), never `git add -A`, and
always `git diff --cached --stat` first.** A parallel session cleared the shared
index between one lane's `git add` and its `git diff --cached`. A complete revert
of shipped work once sat staged in the shared index with the working tree clean —
a bare `git commit` would have un-shipped it without touching a file.
**THE MECHANISM IS NOT RARE — it fired TWICE in one session on 2026-08-15**,
and a THIRD time within a minute of the commit it would have reverted, holding
a revert of ledger work committed ~20 minutes earlier on the second occasion
(staged `lanes.md`/`state.md` missing lines that were present in BOTH `HEAD` and
the worktree). Each was disarmed with a path-scoped `git reset`, which touches
no file. **Run `git diff --cached --numstat` before EVERY commit and read the
DELETION column** — a stale index shows up as deletions-only against a HEAD that
moved past it. `[measured 08-15, **4 occurrences in one session**; the third re-appeared SECONDS after a clean commit, so a single disarm is not a fix — re-check immediately before each commit. **The FOURTH held a revert of a MEASURED result** — `DEBIAS_VALIDATION` back to `in_sample`, restoring a `batter_hits` verdict the backtest had just retired, plus 201 lines of the ledger reconcile. A bare `git commit` by any session would have un-shipped a measurement with the worktree clean]`
- **`git diff` without `--cached` compares the worktree to the INDEX, not to `HEAD`.** Against a stale shared index that reads as "my committed work is missing from the worktree", which is alarming and wrong. **Ask `git diff HEAD` when the question is "did my commit land".** `[08-15, cost one false alarm]`

---

## USER DECISIONS `[2026-08-14 ~21:5x CDT]`

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

## SHARP REFERENCE PRICE — WE HAVE ONE. The audit's caveat is STALE.

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

## DEPLOY DISCIPLINE — read before any deploy

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

## KILLS ARE EVENTS — there is now a tool, and a census `[measured 08-16 17:5xZ]`

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

## MEMORY — refresh-worker: THE 2GB IS A TRANSIENT, AND ITS ALLOCATOR IS STILL UNNAMED `[measured 08-16 15:1xZ]`

**Three fixes are live and exercised; NONE has been shown to move the
transient.** Verified by counting the branch, not the outcome. **Their SHAs were
REBASED 08-16 — the originals are NOT ancestors of live and a SHA-equality check
reads them as reverted** (patch-id verified 08-16 16:3xZ): odds-shard duplicate
parse `51ae7218`→`164f6e80`; ledger streaming + `LEDGER_CHUNKS_ACCEPTED`
`21f8a165`→`1409e96f`; rank_recommendations 3 loads→1 `aa190d58`→`d72d670c`.
They are linear (`164f6e80`→`1409e96f`→`d72d670c`), so
`git merge-base --is-ancestor d72d670c <live>` covers all three. refresh-worker
live `97491161` = `d72d670c` + one unrelated NFL pbp fix (`#441`), finished
08-16 15:45:50Z; no deploy 15:45:50Z–16:29Z.

**Kills are MOSTLY evening, and at-cap is not a kill `[events API, re-censused
08-16 17:26Z, covering 08-09 00:04Z..08-16 17:26Z]`:** **44 `oomKilled`**, every
failure event in the window — **41 of 44 between 15:00 and 23:59 local**
(08-14 alone: 29). The **3 outside** the band are `08-15 00:02:59`,
`08-16 11:34:32` and `08-16 12:19:42` local. And a 5h window (08-16 05:37–10:37
CDT, 2714 samples) read `container_memory_mb` **4096.0 MB = 100.0% of cap** with
**ZERO kills in it** — reclaim succeeding at the cap is what page cache looks
like. Do not report an at-cap reading as a kill.

**The two 08-16 daytime kills are the reason "evening" is now "mostly evening."**
Both landed on an afternoon carrying four deploy cycles (16:43, 16:46, 16:53 and
17:20Z, all user-triggered). Every deploy reboots the worker and re-runs
hydration cold, which is its own route to the transient — so deploy-provoked and
slate-provoked kills are plausibly **different populations, and only the second
is confined to the band.** Not yet a claim that the slate-driven distribution
moved: that needs re-measuring over churn-free days. **Consequence for
instruments:** anything sampling only 15:00–23:59 local — including
`branch-overlap-baseline-watch` since 08-16 — is structurally blind to
deploy-provoked kills and cannot be cited as evidence they did not happen.

**What IS established:** the failure is a ~2GB TRANSIENT, not a leak (22
excursions, 5 deploy-free windows, trough returns every cycle); it is IN-PROCESS
in the parent, pid 39 at 3,138 -> 3,545.8 MB while every child stayed under
54 MB; the kill is decided by evictable page cache (`inactive_file` 26.3/42.2 MB
at the two kills vs 164-240 MB surviving); the climb runs **51s with no stage
marker**, so `last_stage` structurally cannot name it; and **833,550,415 bytes**
of ledger chunks are ACCEPTED per load against a **per-FILE** 256MB ceiling that
never bounded the sum.

**EXONERATED by measurement — do not re-open:** `copy.deepcopy` of the cards page
context (context 0.81MB, copy peak 0.54MB, three orders short, and load-bearing
because `home.py:5381` mutates the returned games).

**A QUIET DAYTIME IS WORTHLESS AS EVIDENCE — but daytime is not always quiet.**
Same clock window one day apart: peak anon 2,816.7 MB pre-fix vs 2,898.5 MB
post-fix, **zero excursions on both**. The pre-fix code once ran **17h51m clean**
in daylight. Judge a FIX only on the live-slate band ~22:00Z-05:00Z;
`scripts/oom_band_report.py` measures it.

**Amended 08-16 17:2xZ (session `branch-overlap-baseline-watch`; the paragraph
above is the `refresh-worker-oom-recurrence` lane's and its measurements stand
unchanged).** The heading previously read "THE DAYTIME LULL IS WORTHLESS AS
EVIDENCE", which is true of a warm deploy-free daytime and false as a blanket
statement: refresh-worker was **`oomKilled` twice in daylight on 08-16**,
16:34:32Z (11:34 local) and 17:19:42Z (12:19 local), amid four deploy cycles.
So "nothing happens in daylight" must not be assumed — **absence of a daytime
kill is only evidence when the window was also deploy-free, and the window's
deploy count must be stated for the claim to mean anything.**

## MEMORY — refresh-worker `#435` — FIX HOLDS; KILLS RECURRED 08-16 02:11Z/02:37Z FROM A SECOND CONDITION `[re-measured 08-16 02:5xZ]`

**THE KILL IS A ~2 GB TRANSIENT, NOT A LEAK, AND NOT A `#435` REGRESSION.**
`c67f7373` IS an ancestor of live `f8ca54e1`, so the streaming reader is in
production by content. The ledger's `#435` figure `2,869 -> 1,071 MB` is the
**book_quotes READ**; `3,857 MB` is **CONTAINER anon** — different quantities,
never in contradiction. 22 excursions over 5 **deploy-free** windows: anon
climbs ~2 GB in 15-25 s (100-330 MB/s), collapses ~2 GB in ~2 s, trough returns
to 971-1,900 MB every time. **Amplitude and peak are FLAT across the night,
before and after tonight's 12 deploys.** Every cycle reaches headroom 0.0-0.2.
**What decides life or death is evictable page cache:** the two kill windows
bottomed at `inactive_file` 26.3 / 42.2 MB; surviving windows kept 164-240 MB.
Kill list from the EVENTS API: 21 kills 08-14 22:17Z..08-15 05:02Z, then **0 for
21h 08m**, then 2. live-odds-worker 0 in window. **The 3000 MB floor does not
guard this pass** — `_OVERVIEW_MIN_SAFE_HEADROOM_BYTES` is consumed only by
`_overview_headroom_exhausted(next_sport=…)` inside the overview sport loop.
**STILL UNNAMED: which allocation inside the pass is the 2 GB.** `last_stage`
cannot say — `seconds_since_stage` is 14-34 s and `apply_game_board_contract`
only does `setdefault`s after `games_normalized`, so the cost is BETWEEN markers.
Working in `deploys.md` (2026-08-16 ~02:5xZ).
**THE CLEAN HOUR HAPPENED AND IT PROVED THE PREMISE WRONG.** `[measured 08-16
04:3xZ]` refresh-worker ran **1h 41m** with no kill and no deploy —
02:37:06Z -> 04:18:17Z (events API), ended by deploy `5c419007` (live 04:24:33Z).
The `win_prob` counter emitted **nothing**, and that is CORRECT, not a failure.
**`WIN_PROB_NULL_NO_PRICE` cannot ever come from refresh-worker: the producer
`refresh_wnba_oddsapi_props.py` runs ONLY on live-odds-worker** — exact-name log
search, 26 matches there, **zero on refresh-worker all day**, positive control
2,346 `MEMORY_WATCHDOG` lines over the identical window. `refresh_nba_oddsapi_props.py`
never ran at all (NBA out of season, as predicted).
**So holding deploys on refresh-worker could never have produced this reading.**
The real gate: the WNBA producer last ran **01:31:25Z**; `PREGAME_CADENCE_SKIPPED
sports=wnba` starts **02:11:58Z** and repeats 115x through 04:30; the counter code
went live on live-odds-worker at **02:24:12Z** (`44bc02f3`) — i.e. AFTER the last
producer run. **The counter has had ZERO opportunity to fire.** It will read on
the next WNBA slate, not on any refresh-worker window.

### Prior `#435` record, unchanged and still true `[measured 08-16 01:07Z]`

**`#435` IS FIXED AND PROVEN.** Root cause: `book_quotes/<date>.jsonl` is
APPEND-ONLY and was read whole. It grows all day (MLB 89.9 -> 184.5MB, resets at
rollover), costs **6.3x file bytes** resident, and **92.4% of it is superseded**
(478,782 rows -> 36,424 keys). `read_book_quotes_latest` reduces AS IT STREAMS.

    same window, same slate      08-14 (no fix)      08-15 (fix live)
    OOM kills                          5                   0
    peak anon                    4,018.5 MB          3,572.4 MB
    longest clean run               53 min              90 min

Grid equality on the DEPLOYED tree: 15/15 events byte-identical.

**THE WORKER IS NOT SAFE.** 3,572MB is 87.2% of the 4,096MB ceiling. The fix
bought ~446MB; a larger slate still crosses.

**ANON COMPOSITION, per-process, clean reading `[01:07:38Z]`:**
`anon_mmap` **1,540.3MB (92%)** vs `heap` 128.3MB. smaps and `RssAnon` agree to
**0.0%**. pymalloc at rest `[21:58Z]`: 934 arenas / 583.7MB live / **350.3MB
retention** — not reclaimable by a trim, and the expected aftermath of freeing
millions of small objects.

**EVERY MEMORY NUMBER CARRIES A SCOPE.** `memory.current`/`anon` and `oomKilled`
are CONTAINER. `smaps`, `PYMALLOC_STATS`, `HEAP_CENSUS`, `RssAnon` are PROCESS.
The worker spawns 8-10 children whose anon swings from 0.4MB to ~504MB, so the
two differ by an amount that is not constant. Subtracting across scopes produced
a retracted "673MB outside pymalloc".

**Instruments live and condition-triggered** (all capped per process, all off the
sampler thread): `MEMORY_WATCHDOG`, `HEAP_CENSUS`, `UNTRACKED_BYTES_CENSUS`,
`PYMALLOC_STATS`, `SMAPS_ANON`. `scripts/render_logs.py` pages BACKWARD and
prints the window it actually covered.

**RULED OUT:** `tracemalloc` at any frame count — it starved the sampler and drove
kill cadence to 3-10 min, and never returned an answer in production.
**EXONERATED:** `board_contract_games_normalized` (0.0MB median, 5,958 builds);
glibc arena fragmentation (`#423`); the per-sport board caches.

**RETRACTED:** "oomKilled 0" (log grep — kills are EVENTS); "85% of anon is not
Python data" (one-level census); "673MB outside pymalloc" (scope error).

**NEXT LEVER, SUPERSEDED 08-16 02:5xZ by the transient measurement above:** the
children (~504MB) and pymalloc's 350MB retention are real but are NOT what
crosses the ceiling. The binding lever is the **amplitude of the single ~2 GB
pass**, or a headroom gate in front of THAT pass rather than in front of the
overview sport loop. Raising the ceiling is excluded by user decision
(keep `pro`, reduce instead). NOT another instrument — but naming the allocator
needs a bounded in-pass measurement, which needs a deploy, which needs a clean
window first. **Deploys must stay OFF refresh-worker until then.**

---

**THE REAL MARGIN IS 124MB, NOT 578MB — the ceiling is a CONTAINER limit and the
worker runs 8-12 processes.** `[measured 08-16 01:4xZ, 6,199 samples]` Worst
combined **3,972.0MB = 97.0%** of 4,096MB: parent 3,302.4 + children 669.6 across
11 kids, at 22:00:31Z. Children peak WITH the parent, not between its peaks —
median 450.2MB while pid 39 held 2-3GB. Any headroom figure that counts one
process is not headroom.

**CHILD TREE IS NESTED, NOT CONCURRENT** (`ppid` chain, same sample):
`run_mlb_daily_sim_job` -> `daily_update`(ui-daily, 180.6) ->
`daily_update_multi_profile`(47.9) -> `daily_update`(76.8) -> 2 spawns(107.4).
~305MB of that is parents IDLING with memory held while children work.
Separately, off its own child of pid 39: `run_refresh_odds_job` ->
`refresh_odds_sources` -> `build_soccer_artifacts` = **202.6MB genuinely
concurrent** with the MLB chain.

**SOCCER'S OVERLAP IS CADENCE, NOT FIXTURES** `[measured 08-16 02:1xZ]`. 43 of 71
soccer refreshes during 18-22Z (**61%**) fetch kickoffs 2+ DAYS away; 19Z, the
worst overlap hour, was 100% future-dated. **Exception: MLS** (20 of 111
invocations) genuinely kicks off in the US evening — a league-blind or clock-blind
rule would break it. The gate must be TIME-TO-KICKOFF.

## BOARD FRESHNESS AND STALENESS

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

## ODDS CADENCE AND CAPTURE

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

## PROBABILITY-STATISTIC OWNERSHIP `[measured 08-15, shipped `2ac3c6bc`]`

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

## THE PUBLISHED SHORTLIST — edges, EV, CLV

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

## MODEL SKILL (`#428`) — measured vs not

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

## SOCCER

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
- **SOCCER GAME ODDS HAVE NOT BEEN CAPTURED FOR ANY LEAGUE SINCE 08-10/08-11.**
  Eredivisie looked healthy solely because `prop` rows from a different producer
  masked it. **The vendor is NOT the cause** — all ten soccer keys
  `listed=True, active=True`. `[measured 08-14 18:4xZ]`
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

## NFL — CLOSED, archived

Moved to `state_archive.md` 2026-08-15. Closed work; the rules it records
generalise but are not current state. `#377`, `#425`, `#429`.

## UI / BOARD CARDS

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

## ASK THE SYNDICATE

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

## THE LIVE SURFACE — Tier 5 `[measured 08-15 02:3x–03:0xZ]`

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

## BOARD / INTELLIGENCE ENGINE — structural facts, archived

Moved to `state_archive.md` 2026-08-15. Every figure in it is also in
`audit_2026-08-14_board_engine_SYNTHESIS.md` (verified by spot-checking
238,071 lines / 24 import cycles / 164 of 390 / 42 sites) — that audit is
the place to read it, and it carries the guard on its two shortlists.

## SERVICES, CONFIG, PLATFORM

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

## SESSION HARNESS — what the hooks actually enforce

- **`lane-guard.py` (PreToolUse) enforces.** Blocks `Edit`/`Write` against a file
  claimed by another OPEN lane (exit 2); allows it when `.syndicate/.current-lane`
  names the claiming lane. **With the marker empty it blocks your OWN lane's
  files**, reporting `Current lane: 'none'` — so a session that hand-edits
  `lanes.md` instead of running `/lane` locks itself out.
- **`Bash` bypasses it entirely** — the matcher is
  `Edit|Write|MultiEdit|NotebookEdit`. The guard bounds the file tools, not the
  session.
- **`lane-guard` is blind to `.claude/**` by design**, so the enforcement layer
  cannot protect the directory it lives in — and every real collision has
  happened there.
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

## TEST BASELINES

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

## OPEN PROBLEMS

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

## Web card surfaces — soccer, 2026-08-15 03:1xZ `[measured]`

- **Live web SHA is `1e44e1da`** `[measured 08-15 18:1xZ via the deploys API]`
  (`dep-da0a5rlg1s2s73cm43kg`, finished 17:40:30Z). **Supersedes `7e334509`,
  which was 14h stale and is what a session reading this line would have stacked
  on.** Live refresh-worker is `c67f7373` (18:11:41Z); live-odds-worker
  `ccd10349`. Deploys are still PINNED, so **stack on the target service's own
  live SHA** and re-read it — it moved 3 times today.
- **`SYNDICATE_BOARD_L2A_ENABLED` = `"true"` on the live web service**
  `[measured 08-15 18:1xZ]`, although it defaults **False** in code and is
  **absent from `render.yaml`**. The serve-time L2-A fallback path
  (`_layer2_fallback_recommendations` -> `_backfill_layer2_board_columns`) is
  therefore LIVE. Absent =/= off, and here the code default is the misleading one.
- **`fair_price` is stamped at SERVE time, not in the artifact**
  `[measured 08-15 18:1xZ]`: the shortlist artifact carries it on **0 of 108**
  rows while `/api/intelligence/query` serves 1800. So board-column fixes of
  this kind are a **web-only** deploy — no refresh-worker restart, no sim at
  risk.
- **`origin/main` is NOT deployable to web as-is.** It was 131 commits ahead of
  live and contains `ad4b0a3a`, which was deployed successfully at 02:46:23Z
  and then **deliberately reverted** by redeploying `a86eb4ed` at 03:00:19Z
  (another session, `ask-headline-from-board`). Deploying the tip undoes that
  rollback. Check the deploys API for `trigger` and the live `commit.id` before
  any web deploy, and stack rather than replace.
- **A 502 sweep across every route at ~02:5xZ was that deploy's restart
  window, not an outage.** Web routes 502 for ~2 minutes on every deploy. Do
  not open an incident on a 502 without first reading
  `/v1/services/<id>/deploys` for an overlapping `deploy_started`.
- **Soccer publishes no `sim.periods` and no `prop_recommendations`.**
  `[measured 2026-08-15 on /soccer/epl/cards]` The board contract therefore
  synthesizes a single stand-in "Full Game" period row, and its props rows are
  scraped off display panels. Both are now tagged `is_synthesized` and gated:
  `shared_lens_rows` and `shared_prop_status_rows` are the subsets that have
  something of their own to show. The gates are on CONTENT, not on sport — the
  panels return by themselves when the model starts publishing per-half output.
  **`shared_period_rows` is unchanged**, which is what keeps Lane F's three-way
  draw bar alive.
- **Soccer's team names are TWO surfaces sharing one class.** The scoreboard
  strip renders 13px with ellipsis (`.cards-strip-card--soccer`) and that is a
  deliberate fix, not a defect. The card head renders 16px and always did. Any
  claim of the form "class X is N px on sport Y" from before 2026-08-15 was
  measured with a first-match `querySelector` and needs re-reading per surface.

## Soccer model — VERIFIED 2026-08-15 02:4x-03:0xZ (lane `soccer-model-coverage`)

**SUPERSEDES the "8,456 rows / 2,504 projected = 29.6%" figure wherever it
appears, and the framing that layer1 and layer2 run different joins.**

- **There is ONE soccer projection join**, `board_enrichment.py:595`. The 250x
  disagreement was two different GRIDS. `[measured]`
  `layer1?sport=soccer` = **123 rows / 4 games / 12 projected**, date-scoped;
  `layer2-shortlist` `per_sport_ingest.soccer` = **8,515 rows over SIX dates
  (08-14..08-20) / 434 scheduled games / 109 projected**. The layer1 figure of
  8,456 rows is **not reproducible** and should not be quoted again.
- **`matches_in_source: 4` is CORRECT, not an empty source.** There were 4
  soccer fixtures on 2026-08-14, one per league, and the sim produced all four.
  `unmatched_match_rows: 8,396` is dominated by later-date fixtures, because
  `load_soccer_projections(roots, selected_date)` loads ONE date by design.
  Future-date recommendation files DO exist on prod (08-15: 6 leagues,
  08-16: 6, 08-17: 4).
- **~~THE SOCCER SIM PUBLISHES ZERO PLAYER PROJECTIONS.~~ NO LONGER TRUE —
  superseded 2026-08-16 16:20Z by lane `layer1-board-coverage`.** Production
  `/api/board/layer1?sport=soccer&window=slate` serves **1,525 projected player
  props**: `player_goal_scorer_anytime` 519/1,539, `player_first_goal_scorer`
  506/1,516, `player_shots_on_target` 394/1,278, `player_last_goal_scorer`
  106/588. Whoever closed this should record which fix did it. **Still zero:**
  `player_shots` 0/960, `player_assists` 0/171, `player_to_receive_card` /
  `_red_card` 0/162 — and `player_shots` is the notable one, since the sim
  demonstrably models shots-on-target. The 2026-08-15 reading below is kept for
  its root-cause trail only; do not cite its counts as current.
  All four production
  artifacts read `matches=1, player_props=0`. **107 of the 123 soccer board
  rows are player props and every one is unprojected**; all 12 projections are
  game rows. Root cause: **live-odds-worker builds the soccer artifacts** (its
  own `ALL_PROCESS_MEMORY` carries `scripts/build_soccer_artifacts.py` at
  02:25:48Z, matching the four `generated_at` stamps) and its entrypoint
  `run_live_odds_refresh_worker.py` ran **no seed bootstrap**, so its disk never
  received the committed `players_*.csv`. refresh-worker HAS them
  (`SOCCER_SEED_CENSUS ... already_present=[all 10 leagues]`, 02:11:05Z) and is
  not doing the work. `#145` recurring on a fourth service.
- **`compute_team_ratings`'s as-of filter is INERT for 9 of 10 leagues**, and
  this contradicts `soccer-backtest-leakage` being closed as fixing the leak.
  It compares dates as raw TEXT; `history/*.csv` is **DD/MM/YYYY** for all 9
  non-MLS leagues (only Understat `team_history/*.csv` is ISO), and
  `'17/05/2026' >= '2026-08-14'` is **False**. eredivisie returns an identical
  **923 match-rows** at every as-of from 2023 to 2026. The four leagues in
  season (eredivisie, primeira_liga, championship, belgian_pro_league) are
  `history`-only and had NO protection. Two further bugs, same cause, live in
  PRODUCTION ratings: matches on the 30th/31st dropped as "future", and the
  text sort behind `rows[-window:]` making "most recent 45" mean "the 45 latest
  in the MONTH". Fixed locally in `loaders._as_iso_day`; **not deployed.**
- **The 3-way h2h edge refusal is STALE, not a safety property.**
  `_no_vig_over_probability` has handled the draw leg since `95305cab`
  (08-07 13:13 CDT); `#263` wrote the refusal at 23:43 the SAME DAY. Verified
  by running the real function on the live board's 4 h2h rows (Telstar
  133/255/183 -> fair 0.4033 on a 6.4% hold).
- **Soccer's model is well calibrated in AGGREGATE and under-dispersed.**
  Across all 166 probabilities in the 54 production recommendation files: mean
  P(home) **0.4525** / draw **0.2382** / away **0.3093**, against real base
  rates of ~44-46 / ~25-27 / ~28-30. **stdev of P(home) is only 0.1364**
  (max 0.80). It is NOT biased toward the away side — it shrinks toward the base
  rate, so it disagrees with the market by 28-50 points on heavy favourites.
  Contributing: `adapters._DEFAULT_SIMULATIONS = 300` = **±2.9pp of Monte Carlo
  noise** on every published probability (0.0025 quantisation is visible in the
  artifacts).
- **Soccer's binding constraint on PUBLISHED EV is still the odds, not the
  model.** `[measured]` soccer `margin_model`: `one_sided_rows` **8,189**,
  `pct_modelled` **100.0** — one book quoting, so every row is
  `book_margin_model` and the uninformative-EV filter drops all of them.
  A perfect model publishes zero rows until two-sided quotes return.
- **SOCCER BACKTEST ACCURACY IS NOW MEASURED, AND THE MODEL LOSES TO THE
  CLOSING LINE.** `[measured 2026-08-15, first leak-free number this repo has
  ever had]` `scripts/backtest_soccer_h2h_calibration.py`, **1,112 matches
  across 9 leagues**, ratings recomputed per match day with `as_of` set to that
  day (only meaningful at all because `_as_iso_day` fixed the inert filter):

        MODEL  multiclass Brier  0.5875
        MARKET multiclass Brier  0.5737   (proportionally de-vigged closing odds, same matches)
        gap                     +0.0139   lower is better, so the MODEL LOSES

  **Worse than the closing line in 8 of 9 leagues** (two-sided sign test
  p = 0.039). The only exception is belgian_pro_league at -0.0011, which is
  noise at n=120. Per league (n / model / market / gap): eredivisie
  126/.5211/.5064/+.0147, primeira_liga 125/.5722/.5405/+.0317, championship
  126/.6158/.6061/+.0097, belgian_pro_league 120/.6045/.6056/-.0011, epl
  120/.5794/.5572/+.0222, la_liga 123/.5947/.5846/+.0101, bundesliga
  126/.5840/.5653/+.0187, serie_a 120/.5970/.5869/+.0101, ligue_1
  126/.6201/.6117/+.0084.
- **The under-dispersion diagnosis is independently confirmed by the backtest.**
  Mean model stdev(P home) **0.1575** vs market **0.1811**, and the model is
  narrower in **8 of 9** leagues. eredivisie's reliability curve shows the
  model is too TIMID at both extremes: predicted 0.144 -> actual 0.000, and
  predicted 0.823 -> actual 1.000.
- **CONSEQUENCE, and it is the load-bearing one for the board: soccer's model
  must NOT be used to publish `model_edge_pct` yet.** A model that loses to the
  closing line on 1,112 matches produces edges that are noise against a
  better-informed price. The 3-way de-vig fix removes a stale BLOCK; it does
  not make the resulting number publishable. Sharpening the distribution and
  raising `adapters._DEFAULT_SIMULATIONS` from 300 (±2.9pp of Monte Carlo
  noise) are the two named, cheap levers — neither is done.
- Coverage, per the `data/**` rule: eredivisie 918 history rows spanning
  2023-08-11..2026-05-17, with result 918, with complete closing odds 918,
  **intersection 918** — this result does not rest on a narrow join. Matches
  are skipped where either side has fewer than 20 prior as-of matches, so
  early-season rows are not scored as if the model had an opinion.
- The retired `data/soccer_source/*/validation/*_backtest_*.csv` remain **not
  citable**. `SoccerSimulationOutput` still ships
  `calibration.win_probability.brier = None` — the harness exists but is not
  wired into the sim's own evaluation slot.


## UI / card surface — verified 2026-08-15 (session `ui-plan-lane-gh`)

**Lane G (soccer card) is LIVE and has survived three web deploys.** Shipped as
`7e334509` (live 03:21:35Z); superseded by `c774fe1a` then `1e44e1da`, both of
which carry it as an ancestor. Verified by ancestry AND by re-measuring the live
service, not by either alone. Production, `httpStatus` 200: soccer unstyled
links 2 -> 0, empty slots 3 -> 0, projected-score sentence 5 -> 1 on the default
tab, 0px overflow. NCAAF control unmoved. `[measured]`

**`scripts/ui_layout_probe.py` is the harness for this surface and it now fails
closed.** A selector matching nothing used to be dropped from the report
entirely — NCAAF serves 16 cards and matches ZERO `.cards-market-main`, and that
read as a pass. It now reports `count: 0` and FAILS. It also carries
`numericSweep`, which finds digit-rendering elements by what they render rather
than by class name. `[measured]` `33e7d7a8`

**Tabular figures: the 2026-08-14 fix is correct and incomplete.** The three
named classes are right on MLB in production (495 / 60 / 30, all
`tabular-nums`). The digits it does NOT reach: **mlb 1388, nfl 468, ncaaf 432,
soccer 60** leaf elements at `font-variant-numeric: normal`. `[measured]`
The container-rule fix is built and pushed (`1bb8cf9f`) but **NOT DEPLOYED**, so
those four numbers are still true of production.

**MLB renders through `cards_source.js` and is the only sport whose DOM is not
stable at load.** A fixed short delay returns a confident zero. Any probe of
`/mlb/cards` must wait on content, not on a timer. `[measured — this rule cost
me a false claim that a shipped fix had never run]`

**A `deactivated` pinned deploy means SUPERSEDED, not reverted.** Whether your
work survived is a separate question answered only by ancestry or a measurement.
Held twice on 2026-08-15; enforced by nothing but the person deploying.


## Card surface - tabular figures CLOSED `[measured 08-15 20:0xZ]`

**All four generic-board sports render tabular digits. Verified in production
after two pinned deploys.** `numericSweep` (leaf elements rendering a digit at
`font-variant-numeric: normal`): mlb **1388 -> 0**, nfl **468 -> 0**, ncaaf
**432 -> 0**, soccer **60 -> 0**. MLB confirmed on desktop at 15 cards with 146
filter pills all `tabular-nums`. Live: `f475c775` (20:00:58Z), preserved by
content in the next deploy `7abd8e12`.

**`font-variant-numeric` inherits everywhere EXCEPT into form controls.** The UA
stylesheet's `font:` shorthand on `<button>`/`<input>`/`<select>` resets it -
measured live: card `tabular-nums`, `button.cards-filter-pill` `normal`,
`fontFamily` `Arial`. Both rules are now in all four stylesheets. MLB was the
only sport affected because it is the only one with in-card filter pills
carrying counts. `[measured]`

**A pinned deploy is NOT on main's lineage, so ancestry is the WRONG test for
"did my work survive".** `454af741` and `1bb8cf9f` both read as non-ancestors of
the very deploy that carries them; the four CSS blobs are byte-identical. Test
deployment by CONTENT. `[measured 08-15 - this exact check]`

**`scripts/ui_layout_probe.py` still waits on a fixed delay and WILL report
`mlb: 0 cards` spuriously.** It did so mid-verification today. Any MLB reading
must wait on `.cards-game-card`, not a timer. Fixing that wait is the next
change to the probe. `[measured]`


## Card surface - soccer shows its market line and edge `[measured 08-15 21:2xZ]`

**Live `bb23c8f9` (21:18:38Z).** Soccer's card carries `.cards-data-pair` 3
(was 0), `market` `ATS ARS -1.5 | Total 2.5` and `best_edge`
`ATS +0.2 | Total +0.7`, read off the served card. `[measured]`

**A sport with no `sim.periods` gets a stand-in Full Game row, and that row now
reads `betting` + `sim.score` before falling back to a metric-label lookup.**
The lookup asks for "Spread"/"Total"/"Edge"; soccer publishes "Total goals" and
friends, so it matched nothing and the card showed its market line NOWHERE
while `betting.home_spread` and `betting.total` sat on the game. **A
label-matched lookup is not a substitute for the field.** `[measured]`

**Which sports reach that branch** (`sim.periods` empty), measured 08-15:
soccer 1/1, **mlb 15/15**, **ncaaf 16/16**, nfl 0/16. MLB and NCAAF are inert
through it today only because their games carry no `betting` spread/total in
that shape - that is a data fact, not a structural guarantee, and it can change
without anyone touching this code. `[measured]`

**`scripts/ui_layout_probe.py` waits on CONTENT, not a timer.** Five
consecutive production runs returned 15 MLB cards on all 10 readings; the old
fixed 400ms delay returned 0 on at least one of three. A render that never
attaches a card is reported as `cardWaitTimedOut`, which is NOT a 0-card slate
and fails even out of season. `[measured]`

**NCAAF has no market tile row and that is by design** - `_game_card_ncaaf.html`
contains zero `cards-market` markup. Declared in `NUMERIC_CLASS_EXEMPT` rather
than failing the run, and the declaration is checked in both directions.
`[measured]`

**UNEXPLAINED, do not inherit as a regression:** MLB card-height spread
56 -> 197px desktop / 112 -> 1887px mobile across the 19:0x-21:2x window, and
empty slots 8 -> 1. Not the contract (rows byte-identical, 0/15). Presumed the
slate moving; **nobody has actually looked.** `[unverified]`


## MLB card-height spread - it measures CONTENT, not layout `[measured 08-15 22:xxZ]`

**Do not read MLB's card-height spread as a layout signal.** Height tracks
`.cards-data-pair` count at ~62px per pair, and MLB serves **20-57 pairs per
card**, so the figure reports how much data each game has. It moved 796 ->
1716 -> 1583px across three readings with no code change. Grouping by game
state does not fix it - Preview alone measured 80px and 797px twenty minutes
apart. `[measured]`

`scripts/ui_layout_probe.py` now prints `content varies N-M pairs/card`
alongside the spread whenever cards differ, so the two can be told apart.
**NCAAF (45/53px) and soccer (0px) carry no content line** - their cards are
uniform and their spreads ARE layout signals. MLB's is not. `[measured]`

**EXONERATED:** the MLB height movement flagged at the 21:2xZ checkpoint is not
`6e9e6107` and not any layout change - the contract rows were byte-identical
across it (0/15 games). `[measured]`


## UI probe - the settle rule and what JUDGES a card's height `[measured 08-16, supersedes the 08-15 entry]`

**The height model no longer judges anything. Deviation from same-content PEERS
does.** A card is anomalous when it differs from cards carrying the SAME
`.cards-data-pair` count — model-free, per state, and it runs on slates where no
line can be fitted. Budget is **`PEER_DEVIATION_BUDGET_PCT = 15.0`**, a share of
the tied group's own median card height, calibrated on 16 healthy readings whose
worst was 9.9%, **and a verdict needs `PEER_MIN_GROUP_N = 3` cards** — an n=2
group read 30.9% (2 cards at 41 pairs, 312px apart) while the n=6 group on the
same board sat at 82px, and minutes later only one card remained at that pair
count. Thin groups are printed as NOT JUDGED, never dropped. `tieFloor` returns
the FULL per-group list so a thin group cannot mask a fat one. `LAYOUT_RESIDUAL_BUDGET_PX = 150` survives only for the
content-independent branch's legacy path; the residual is now CONTEXT. `[measured]`

**Three false alarms on 2026-08-16 shared one root cause: the fitted line was
treated as ground truth.** Raw group spread failed mlb desktop at 313px while
peers differed by 70px; a residual AT its own noise floor (164px) failed while
the same row called it text wrap; and a CURVED fit passed `reliable` at ratio
0.20 then failed on a structured residual. All three are gone. `[measured]`

**`fitRatio` cannot see misspecification** — it is residual/explained, so a wide
explained range certifies a bent line. `fitGroup` now tests SHAPE: slopes between
consecutive pair-count group means, monotone-drift over >=3 steps, drift > 0.5.
Measured: mlb mobile Live 0.88 (curved) vs Preview 0.008 (straight). A curved fit
reports MISSPECIFIED and is not `reliable`. `[measured]`

**MLB desktop is UNFITTABLE, and the mechanism is TEXT WRAP.** Cards with
identical pair counts differ 97-116px because the pair grid is a wrapping
row-max flow — 10 visible columns at 1440, 2 at 390. Agreeing on both visible
pair count AND visible row count still leaves 74px. Preview is linear
(62.4/62.1 px/pair); Live is convex (41.3/61.8/76.6), all of it inside
`section.cards-panel.is-active > div.cards-overview-grid`. `[measured]`

**The settle rule: 2400ms of CONTINUOUS stillness, and a verdict resting on
absence says so.** Two equal polls (800ms) was the floor and fit inside a
pre-enrichment plateau — it shipped a bad row (`rerun_2026-08-16.json`, mlb
desktop, 15 cards at a uniform 33 pairs, `renderSettled: true`, while mobile read
33-49 on the same slate). `_settle` now returns `sawChange`; MLB settles
4.4-10.0s, the seven server-side sports at the 2400ms floor with
`sawChange: false`, named in a footer. The tab click-through check now
reports WHY it failed (error type, or `active=[…] h=…px`) and waits on the
outcome — the board replaces `cardsGrid.innerHTML` on a 30s timer underneath it. The 08-15 growth curve still stands and
is why a short window is not enough — total `.cards-data-pair` across 15 cards at
390px: **482 at +0ms, 530 at +600, 590 at +1200, 683 at +2000, 719 at +3000 and
stable**; every MLB figure produced before `_settle` existed was taken at ~74% of
final content. `[measured 08-15]`

**`identicalContentSpread` is baselined for nfl and ncaaf ONLY**
(`TIE_SPREAD_BASELINED`), where it read bit-identical 14/50/45/53 across 7+ runs.
MLB read 81/109/123/164/193px the same day — **the cause is the SLATE, not the
metric**: nfl/ncaaf slates were static, MLB enriches while games are live.
Baseline file `reports/ui_layout/baseline_2026-08-16.json` (`ok: true`). Drift
FAILS; a state change reports NOT COMPARABLE, which is what stops first pitch
reading as a regression. `[measured]`

**Proportional does NOT tighten the spread** — raw px max/median 3.3, percentages
3.0. It was kept because it fixes the WIDTH bias (150px is 2.8% of a 4800px mlb
mobile card and 27% of a 541px ncaaf desktop one), not for the reason it was
proposed. Drift-against-baseline is the sharper check and caught nothing false
all day. `[measured]`

## UI probe height model - MLB DESKTOP HAS NO LAYOUT SIGNAL, and grid-rows will not give it one `[measured 08-15]`

**CLOSED AS WRONG:** the carried-forward idea that the desktop unit should be
grid ROWS. Rows are proportional to pairs within a group, so the fit is an
affine reparametrization — measured both ways on the same cards, residuals
identical to the pixel (11/11, 139/139, 52/52 px). Do not pick this up again.
`[measured]`

**MLB desktop height is neither driven by the summary-pair unit nor
independent of it** (105-197px explained at 16-26px/pair), so neither the
residual branch nor the content-independent branch produces a signal there. Any
future attempt needs a unit that captures panel COUNT and callout/table rows,
or per-card height bounds instead of a model. `[measured]`

**The model is only stable where a group is large enough.** n=3 groups gave fit
ratios 0.59 and 1.29 while an n=9 group on the same page gave 0.09; the fit now
requires **n >= 5**. Across one evening the same metric read reliable/54px,
unreliable, unreliable, then unfittable as the slate churned — **one reading of
it is not a baseline.** `[measured]`

## SOCCER QUOTE FEED — OUTAGE DIAGNOSED, CAUSE IS LOCK CONTENTION `[measured 2026-08-15 21:2xZ]`

- **Nothing happened at 13:47Z.** Soccer's pregame capture is a **4-hourly
  autorun** on live-odds-worker:

      02:14:40 LAUNCHED | 06:17:45 LAUNCHED | 10:21:54 LAUNCHED
      14:22:29 FAILED (A refresh run is already active, pid=7114)
      18:22:34 FAILED (pid=8200)

  **13:47:17 is the TAIL of the 10:21 run**, which walked leagues ~3.5 h and
  finished. The outage begins at **14:22:29**, the first REFUSED autorun.
- **Mechanism:** a 4-hourly point sample fired at a refresh-run lock held
  **~92%** of the time ⇒ ~1-in-12 success per attempt. Two consecutive misses is
  expected, not anomalous. Soccer is starved by scheduling, not broken.
- **TWO DIFFERENT CLOCKS — corrects the standing `earlyExit` lead.** `earlyExit`
  is ~6.5 h (01:37/08:05/14:34/20:03); the autorun is ~4 h. The 14:22 failure
  PRECEDES the 14:34 exit by 12 min, so the exit did not cause it. `earlyExit`
  remains a real problem for long in-flight runs; it is not this outage.
- **REFUTED on evidence, so nobody re-runs them:** fixtures aging out (08-16 and
  08-17 shards stop at the SAME instant; zero soccer rows anywhere after
  13:48:00Z), a restart at 13:47, the run erroring (zero tracebacks), and
  OddsAPI quota (zero quota lines; mlb/nfl capturing normally).
- **RESOLVED 22:24:29Z, UNAIDED, AND THE DIAGNOSIS IS CONFIRMED.** The 22:23:16
  autorun LAUNCHED (pid=924) and the first new capture landed **73 seconds
  later**; soccer went 516.6 min -> 0.1 min, `stale` -> `ok`.
  **Total outage 14:22:29 -> 22:24:29 = 8h 02m**, two refused attempts.
- **Cheapest fix, unowned, and now QUANTIFIED:** the autorun gives up for 4 h on
  a TRANSIENT lock. Given first-capture-in-73s, a bounded retry (every 5 min for
  30 min) at the 14:22 refusal would have found one of the ~2-min free windows
  that occur every ~25 min — **turning an 8-hour outage into minutes.**
  `live_refresh_loop.py` is claimed by OPEN `live-game-line-projection`.


## Soccer card - the producer now publishes half-by-half periods `[measured 08-15 22:0xZ]`

Served `/soccer/epl/api/cards` carries `sim.periods` = `h1`, `h2`. The card
renders `1st Half` / `2nd Half` / `Full Game` (3 lens rows, 3 total rows), with
the Full Game row carrying `ATS ARS -1.5 | Total 2.5` and
`ATS +0.0 | Total +0.8`. The `-` on the two half rows is deliberate contract
design - only a full-game row is compared against the full-game line.

**Therefore the stand-in-row fix (`6e9e6107`) is NOT currently exercised on
production soccer**, and production soccer is no longer evidence for it. It
remains correct and tested and fires for any sport publishing no periods.
`[measured]`

## Candidate field absence — **THE BASELINE BELOW WAS MEASURED ON THE WRONG PATH** `[corrected 08-16 00:1xZ]`

**CORRECTION, READ THIS FIRST.** These numbers are real but they do NOT measure
the `UniversalCandidate` fixes. The served rows come from the **Layer 2 board**
(`source: layer2_shortlist`), whose `line` is stamped at
`syndicate/features/shared/layer2_board.py:1104` as a bare `row.get("line")`
float. `UniversalCandidate.to_dict` is not on that path. Verified after a
confirmed rebuild on `2c14d9ae` (`computed_at 2026-08-16T00:12:39Z`): `line as a
string` is still **0**, so the deployed fix is **INERT on the served path**.
Fixing whole-numbered lines means changing `layer2_board.py:1104`, where `line`
is also an `_IDENTITY_FIELD` feeding the dedupe key at `:450` — not cosmetic.

Baseline taken from live `/api/intelligence/query`, 101 recommendations, BEFORE
any of this session's three fixes are deployed. **Whoever deploys them re-reads
these four numbers; that is the measurement.**

    market_key blank      0 / 101
    player_name blank     0 / 101
    line as a number     84 / 101   <- of which 7 whole-numbered
    line as a string      0 / 101

- **The `market_key` and `player_name` fixes change NOTHING on production today.**
  They are correctness work: real defects, zero current incidence. Do not claim
  a production effect for them.
- **The only live defect is `line`.** `displayLine()` does a bare `String(line)`,
  so a JSON `2.0` renders as `2` — 7 rows are missing their decimal right now.
- **It is a refresh-worker fix, NOT a web one.** `UniversalCandidate.to_dict`
  runs inside `collect_candidates` (worker-owned) and the served rows come from
  cached worker state. The serve-time half
  (`_attach_intelligence_response_aliases`, 5 call sites in the web blueprint)
  is the `market_key` fix — the one measuring 0 rows. **A web-only deploy of
  this work is inert.**
- **ALL THREE FIXES ARE ON `origin/main` AS OF `89c3d947`** `[pushed 08-15 ~22:4xZ,
  verified BY CONTENT in origin's tree, not by ancestry]`. `1322d0a8` (line),
  `d348e040` (market_key) and `4ae71c4a` (player_name). **Not deployed to any
  service.** A deploy attempt at ~22:5xZ did not fire: the refresh-worker
  deploy claim is HELD by `live-game-line-projection` and the worker had 7 JOB
  processes in flight (MLB sim + MLS artifact build). The claim holder has been
  asked to CARRY `89c3d947` rather than release it.
- `/api/board/layer2-shortlist` is the WRONG surface for this check — its rows
  carry no `market_key` at all (84/84 absent) and its `line` is the shortlist's
  own field, not the recommendation's display value.

## MIA @ CIN's ZERO LIVE COVERAGE — DIAGNOSED, AND IT IS NOT A LIVE-LENS DEFECT `[measured 08-15 22:3x–22:4xZ]`

**`game_chip_scoreboard._game_flags` reintroduces the abstract-only live check
that `features/mlb/game_state.py` exists to prevent, and that module's own
docstring forbids by name.** It builds `status_texts` from
`status.abstract` (among others) and sets `is_live` on
`status_texts.startswith("live") or " live" in status_texts`. MLB StatsAPI
reports `abstractGameState: "Live"` during **warmup**, which is exactly the
`#98`/`#100` trap — `game_state.py` says *"Do not reintroduce an abstract-only
check at a new call site."* AST importers of the canonical module are
`home.py`, `intelligence.py`, `mlb/cards.py`, `fetch_mlb_oddsapi_local.py`,
`refresh_mlb_oddsapi.py`. **`game_chip_scoreboard.py` is not one of them.**
Same shape as the NFL `live_edge_policy` miss: a rule centralised so every
consumer could depend on it, with one consumer never wired to it.

**The effect is a FALSE DENOMINATOR, not a missing projection.** The chip marks
a warming-up game `live`, the board stamps `state: live` on its rows, the live
join therefore counts them as live-and-unmatched — while `cards.py` correctly
emits nothing, because `_actual_payload_is_live` delegates to the canonical
predicate and a game that has not started has no live state to project from.
**Zero was the right answer to the wrong question.**

**PROVEN BY FIRST PITCH, same code, same game, same slate:**

| board artifact | MIA @ CIN first pitch 22:40Z | overlaid |
|---|---|---|
| `22:38:36Z` | **not yet thrown** | **0 of 114 (0%)** |
| `22:41:43Z` | thrown | **74 of 117 (63.2%)** |

**THE BASELINE WAS NOT CONTAMINATED — checked, not assumed.** Rows marked live
whose first pitch had not happened: **0** at the 20:12:48Z baseline, 114 at
22:36:24Z, **0** at 22:41:43Z. So the honest coverage progression on live PROP
rows is **11.6% -> 50.3%**, and the 25.5% mid-read was depressed by this bug
(39.3% excluding the not-yet-started game).

**Per-game, once warm: BAL @ TB 69.7%, MIA @ CIN 63.2%.** The remaining laggard
is **WSH @ NYM at BOT 8 = 13.0%**, consistent with substituted players having no
sim row — **UNVERIFIED, and not claimed.**

**NOT FIXED. Blast radius is every sport's board chips**, not just MLB, and the
predicate change would move what counts as `live` board-wide. Owner needed.

## Board build cadence vs deploy cadence `[measured 2026-08-15/16, lane board-publish-stall]`

- A real board build takes **178-358 s** (3.0-6.0 min), end-to-end
  `BOARD_OVERVIEW_READY -> BOARD_PUBLICATION_RESPONSE_READY` about **10.6 min**
  on the 00:02 build (567 candidates). **`BUILD_SPAN_EXIT elapsed_s=0.0` is the
  empty-pool short-circuit, not a build** — counting those inflates the rate.
- **Closely-spaced worker deploys starve the board.** 13 refresh-worker deploys
  on 08-15 after 21:30Z. Builds completed only inside gaps of **15-33 min**
  (21:53 / 22:32 / 22:52 / 23:10). Six deploys in 46 min at **6-9 min** spacing
  produced **zero** completed builds, and the board went **77 min stale** on a
  worker that was busy the whole time. **Before deploying refresh-worker, ask
  whether the last deploy was under ~15 min ago; if so you are likely killing a
  build nobody will see fail.**
- **The served intelligence recommendations are LAYER 2 rows**, not the
  candidate pool: `source: layer2_shortlist`, `surface_key: layer2`,
  `candidate_type: None`. Anything reasoning about "what the board serves" must
  start at `pipeline/layer2_shortlist.py` /
  `syndicate/features/shared/layer2_board.py`, NOT at `collect_candidates` or
  `UniversalCandidate`. `[this cost one pointless worker restart on 08-15]`
  - **Re-measured 2026-08-16: `layer2_is_primary=True`,
    `legacy_candidate_count=0`, and 108 of 108 board cards carry
    `source=layer2_shortlist`.** So the earlier ledger claim *"NO TEMPLATE
    CONSUMES THE SHORTLIST — the board still renders `ranked_all`"* is **STALE
    and must not be cited.** It came from a `grep` over `templates/`/`static/`
    for "layer2" that returns zero **to this day** — the wiring is SERVER-side.
    A template grep cannot answer "does anyone consume this"; read the served
    payload. `[measured 08-16 16:20Z]`
- **THE LAYER 2 BOARD FIXES ARE LIVE AND MEASURED** `[2026-08-16 18:31Z]`.
  refresh-worker `7b544eb4` (live 18:20:40Z), web `ad77e46a` (live 18:27:30Z).
  On the post-deploy artifact (`written_at` 18:31:26Z, 108 rows/cards):
  best book outside the operator's 11 **27 -> 0**; `h2h_lay` served **9 -> 0**;
  prop cards attributed to a team **56 -> 0** (renders the board's `—`);
  cards carrying `sim_view` **0 -> 108/108**; rail cards **108 -> 18**
  (MLB 15, WNBA 3). `book_shortlist.py` is the ONE owner of the bettable-book
  list; Layer 1 does NOT read it yet.
- **`no_bettable_book` / `repriced_to_bettable` ARE COMPUTED AND NEVER
  PUBLISHED** `[2026-08-16]`. `pipeline/layer2_shortlist.py` builds
  `per_sport_stats` from an EXPLICIT KEY LIST that omits them, so the book
  filter works and is invisible — a future slate that shrinks because rows had
  no bettable book is indistinguishable from a thin slate. `#397`'s trap, in
  the module that warns about it. OWED by `layer2-board-quality`.
- **`/api/board/game-chips` IS NOT A "TODAY" FEED, BY DESIGN.**
  `game_chip_scoreboard.py:227` says a chip strip "can span several days at
  once" and disambiguates with a date prefix on the status token rather than by
  filtering. Measured 2026-08-16: a single-date request returned **90 soccer
  chips across 10 Central dates (08-15..08-28), only 21 of them today**, while
  MLB (15/15) and WNBA (3/3) were clean — so the multi-day case is invisible
  until a week-keyed sport reaches the consumer. Any consumer must filter by
  CENTRAL date itself. `[measured 08-16]`
- **MOVEMENT/STEAM COVERAGE IS 96%, UP FROM 31%, AND THE KEY IS WHY** `[measured
  2026-08-16 22:20:31Z]`. `clv_opening_ledger._opening_key` includes `line` and
  `bookmaker`; joining movement on it meant only UNMOVED rows could match their
  own opening. Movement now uses `layer2_board.movement_join_key` (event ·
  market · player · segment · side). `_opening_key` is UNCHANGED and still
  correct for settlement.
- **A LOOSE JOIN KEY MADE ROWS VISIBLE, NOT COMPARABLE** `[measured 22:20:31Z]`.
  19 of 23 tracked rows had a different opening line, and the board briefly
  showed a FALSE STEAM flag (`Rockies spreads -1.5` vs an opening of `+1.0`).
  Price delta is now emitted only when the line is unchanged; when it moved, the
  line move IS the movement. Fix `3662d552`; worker `2ef1165a` LIVE 22:34:09Z and web `acdaaf7e`
  LIVE 22:35:42Z. **THE GATE IS VERIFIED IN PRODUCTION** `[2026-08-16 23:01:01Z]` —
  **9 moved-line rows, 0 leaked a price delta** (pre-fix 19 of 23), and the 2
  same-line rows still priced, so it does not over-suppress. Independently
  re-counted. **STEAM is still UNVERIFIED** — only 2 rows could fire it and both
  openings were outside the 3h window.
- **`_SCORE_SIM_WEIGHT` IS `0.0`, NOT `0.5`.** (`opportunity_signals.py:390`,
  deliberately zeroed and gated on S6.) **The board ranks on market EV and price
  shopping ALONE; the simulation contributes nothing to the ordering.** Measured
  on the served shortlist: 65 of 108 rows carry `model_edge_pct` and
  `sim_component` is non-zero on **0** of them. `layer2_board.py`'s own module
  docstring said `0.5` until 08-16, and **a session brief and an audit both
  inherited that number and built on it** — if you change the constant, change
  every line that quotes it in the same commit. `[measured 08-16 16:20Z]`
- **The workers and web run a DEPLOY BRANCH, so `git merge-base --is-ancestor`
  gives WRONG answers about what is deployed.** Measured 08-16: `edbbee9d` is
  NOT an ancestor of live `97491161` (branch `deploy/nfl-pbp-root`) and the fix
  it carries **is running**. Test deployment by CONTENT — `git show <sha>:<path>`
  — on EVERY service the question touches. `[measured 08-16]`
- **Cutting a deploy branch from an older commit silently un-ships every fix
  landed since the branch point, and nothing in the deploy path reports it.**
  `deploy/nfl-pbp-root` branched at `b0ab37a1` (08-15 17:26 CDT); the `min()`
  score fix landed 19:04 CDT and was therefore absent from all three services
  for ~22h. Restored and verified 08-16 17:13Z. `[measured 08-16]`
- `/api/intelligence/query` returns a **different-sized set on each call**
  (101, 98, 271, 216, 30 observed within one hour on the same body). **Counts
  across calls are not comparable** — compare type distributions or ratios, and
  never quote a bare N/M as a before/after.

## SIM ENGINES — verified 2026-08-15 (`#440`, lane `sim-engine-phase0-census`)

Read from every engine package and from live production, not from registry prose.

- **7 of 8 sports have a real Monte Carlo pregame engine. NCAAB has NONE** — no `sim_engine`,
  no projection module, no generator; its only pipeline step is an odds snapshot.
- **Only 2 of 8 have a live sim** (MLB `estimate_live`, soccer `poll_league`). NBA/WNBA/NFL
  carry non-sim stand-ins; NHL/NCAAF/NCAAB have nothing live.
- **NBA/WNBA run a full possession-level MC game sim** (`simulate_smart_game` -> score
  distributions, `p_home_win`/`p_home_cover`/`p_total_over`), persisted per game. Verified on
  3/3 production artifacts. The no-sampling stub is NOT firing.
- **Production basketball `n_sims` = 100** (engine default 2000). All 9 served probabilities
  across 3 games are exact multiples of 0.01 — quantized because each is a count of 100 draws.
  Binomial SE at p=0.25 is ±4.3 pts.
- **The live-lens loop runs on BOTH workers**, so mlb/wnba/soccer are built TWICE per cycle —
  69 MLB builds/hr across two containers where one owner needs ~35. Measured by log
  (`TICK_COMPLETE`, 02:21-03:13Z), not inferred from config.
- **Kickoffs, America/Chicago** (`reports/kickoff_census/latest.json`): 9 European soccer
  leagues n=200 span hours **5..14 with 0.0% in the 18:00-01:00 band and none after 14:00**;
  MLS n=111 94.6%; mlb n=605 53.6%; wnba n=117 84.6%; nfl_preseason n=49 71.4%.
- **OddsAPI is at 62.7% of the 5M cap** (`projected_30d_credits` 3,134,318; 4,353 credits/hr).
  Spend is **mlb 93.0%, soccer 4.1%** — soccer cadence is not a cost lever.
- **`calibration_profile_store` load/save have NO non-test caller**, and most of
  `model_scoring` (CRPS, pinball, reliability, bias/dispersion) likewise. `sim_run_ledger` IS
  wired at three choke points. The convergence foundation is built and ~1/3 reachable.
- **Fixture-aware pregame cadence is SHIPPED BUT DARK** —
  `SYNDICATE_PREGAME_FIXTURE_AWARE_CADENCE` defaults false and **no service sets it**. Soccer
  is excluded from it by measurement (see learnings 2026-08-15).
- **Baseline watcher `branch-overlap-baseline-watch`** (cron `15 */4 * * *`) is accruing
  `reports/branch_overlap/baseline.jsonl`. First sample: **worst container 4096.0 MB = 100.0%
  of cap in 3 separate hours**, against the previously recorded 3,972 MB / 97.0% / 124 MB
  margin. **That older figure is STALE — do not judge Phase 1 against it.** Whether 4096.0
  indicates a leak is NOT established: `memory.current` includes page cache and anon vs
  inactive_file was never split.
  **Provenance, verified 08-16 19:52Z:** records now carry `run_mode`. Of the 4
  records on `main`, exactly **ONE** (`2026-08-16T19:52:23+00:00`, `samples=1967`)
  is `run_mode="scheduled"`; the other three carry NO field and are UNKNOWN, not
  scheduled. **Count only `scheduled` records toward the Phase 1 distribution** —
  the 10:09Z and 10:37Z pair also double-counts ~4.5 of its 5 hours.

## LAYER 1 / LAYER 2 BOARDS — session briefs exist; three facts worth not re-deriving `[code read 08-16 11:2x CDT, NOT a production measurement]`

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

## NFL PLAY-BY-PLAY — verified 2026-08-16 (`#441`, CLOSED)

- **The nflverse pbp had NO ingestion path in this repo.** Ten scripts read it, zero
  wrote it. It was absent from all four candidate roots including the mounted disk;
  env vars were present and strict storage on, so neither configuration nor root
  selection was the cause.
- **`scripts/fetch_nfl_pbp.py` now provides it**, wired as a refresh-worker autorun at
  dispatch position 2, gated by `NFL_PBP_FETCH_ENABLE_REFRESH_WORKER_AUTORUN` (set
  `true` on refresh-worker only, default OFF).
- **VERIFIED IN PRODUCTION 18:31:15Z:** `pbp_2025.csv` written to the mounted disk,
  97,951,481 bytes, 46,452 REG plays. `NO PLAY-BY-PLAY` stopped; the generator ran
  again 31s later and did not refuse.
- **The season that matters is the PRIOR one.** 2026 legitimately 404s until the season
  starts; week-1 ratings come from `prior_season_fallback`.
- **`#443` and `#445` remain OPEN and unowned** — the stale-PID silent stall, and
  NCAAF's generator crashing on a hard-coded 2025 input 13 days before its season opens.

## NCAAF SEASON PROJECTIONS — verified 2026-08-16 (`#445`, FIXED, NOT DEPLOYED)

- **The generator crashed on every launch** with `FileNotFoundError` on
  `ncaaf_source/data/college_football_schedule_2025_predicted_totals_enhanced.csv`,
  and the staleness gate relaunched it indefinitely
  (`SEASON_PROJECTION_ARTIFACT_MISSING sport=ncaaf ... since_launch_seconds=2866`).
- **The CFBD fallback for this case already existed** and was already called by
  `main()`; it was unreachable because the read raised instead of returning empty.
  Fixed in `483bb9dd` (4 lines + an `ENGINE_SCHEDULE_ABSENT` log line).
- **The predicted-totals CSV family is season-2025-only** — 278 files in the
  checkout, all 2025, none for 2026, and nothing in the repo writes one. CFBD is
  the correct source for any season the legacy engine never covered. **Do not
  re-point the hard-coded filename at a 2026 path**: it would rate 2026 from 2025
  predicted totals, which is silently wrong rather than loudly broken.
- **NOT DEPLOYED.** NCAAF opens 2026-08-29; rides the next worker deploy with
  `b909d008`. Whether it produces rows in production is UNVERIFIED.

**MLB GRADING IS PINNED AT ONE ROW A DAY, AND THE CAUSE IS A PATH `[measured 08-16 ~18:2xZ]`.**
The pregame freeze writer and the grading reader are on two trees one segment apart:
writer `market_dir = source_root/data/market/oddsapi` with `source_root = REPO_ROOT/data/mlb_source`
(`refresh_odds_sources.py:666`), git-tracking **0** files; reader `_odds_paths` ->
`<MLB_BETTING_DATA_ROOT>/market/oddsapi` = `.../mlb_source/source_artifacts/data/market/oddsapi/`,
git-tracking **27** `*_pregame.json`, newest **2026-07-08**. Measured consequence: `ml`
graded rows = **exactly 1 on all 8 dates checked**, 4-14 `Missing game-line match` warnings
each, and `season_betting_day_2026_08_15.json` retains ONE game of a ~15-game slate.
Fix built and tested (419 passing, 3 new tests verified non-vacuous) — **NOT DEPLOYED**;
runbook in `.syndicate/handoff_deploy_freeze_reader_tree.md`.

**THE FREEZE IS NOT MONOTONIC IN PRODUCTION `[measured 08-16]`.** 14 games / 54,995 B at
~17:52Z -> 8 games / 17,832 B at 18:12Z, 7 of the 8 still pregame. `_merge_pregame_game_lines`
cannot shrink a seal it can READ, so the input was empty. Deploy-reset is the leading
explanation but is **n=1 on the transition** — not proven.

**`/api/ops/evaluation-settlement/status` SERVES A STORED FILE. CHECK `epoch` FIRST
`[measured 08-16]`.** It read `2026-08-06T11:03:17Z` — ten days stale, frozen since the
autorun was disabled. `settled 0 / pending 8276 of 8276 / graded_rows_available 1` describes
08-06, not today. Quoting it as current is how this lane opened on a wrong premise.

**`/api/board/book-grid` HARD-CAPS `limit` AT 2000 `[measured 08-16]`** (`intelligence.py:2240`,
`min(2000, ...)`). A `limit=4000` request returns 2000 of 3325 and every count off it is a
floor. The `market=` filter is applied BEFORE the cap, so per-market fetches are exact.

**`/api/ops/artifacts/export` RUNS ON WEB AND READS WEB'S DISK `[measured 08-16]`**, and is
filtered by `HOT_ARTIFACT_PATTERNS` (`ops.py:1342`). It showed 3466 files under
`mlb_source/source_artifacts/data/` and **zero** containing `/market/` — which says nothing
about refresh-worker's disk, where the grading builder actually reads. A zero from it is
not absence.

**ALT-LINE PROJECTIONS `32186e28`/`c422f79a` VERIFIED PASS `[measured 08-16 17:2xZ]`.**
Book grid **359 of 361** alt rows carry a projection (was 238 / 0); shortlist MLB alt rows
with non-null `sim_component` **12 of 17** (was 0 of 9), mean rank 42.6 -> 37.6 pctile, no
crowd-out. Caveat that matters: `sim_component` is non-null but **exactly 0.0 on main
markets too** — `_SCORE_SIM_WEIGHT` is 0.0, so the fix moved alt rows onto the same
degenerate value main rows already had. They are not sim-ranked.

## 2026-08-16 21:2xZ — VERIFIED (sim-scheduling lane)

Deployed SHAs at this instant (they go stale in minutes — re-read before using):

| service | live SHA | finished |
|---|---|---|
| web | `73e59f51` | 21:20:12Z |
| refresh-worker | `a9e5d3d6` | 20:50:14Z |
| live-odds-worker | `46b5ec66` | 19:47:16Z |

**`#441` — VERIFIED IN THE RUNNING PROCESS.** The NFL pbp autorun sits at
dispatch position 2 and every decline path states a reason. Proof is the ORDER
inside one covered tick, 63 ms apart:
`RECONCILIATION_AUTORUN_GATED` -> `NFL_PBP_FETCH_SKIPPED reason=rate_limited
marker_age_s=8162/interval_s=86400`. `rate_limited` is the CORRECT outcome (the
fetch succeeded ~18:31Z; interval is 24h).

**Production had SILENTLY REVERTED `#441` to position 6** before this. Found by
diffing the DEPLOYED tree by content; ancestry would not have shown it. Assume
any fix can be reverted by another lane's deploy and re-check by content.

**Layer 2 counters — VERIFIED ON THE SERVED PAYLOAD**
(`/api/board/layer2-shortlist`, HTTP 200, `rows: 51`):

| sport | grid_rows | no_bettable_book | repriced_to_bettable |
|---|---|---|---|
| mlb | 3296 | 87 | 1667 |
| nfl | 1425 | 76 | 586 |
| soccer | 8591 | 881 | 1586 |
| ncaaf | **0** | — | — |

No sport carries an `error` key, which disproves the caller/callee `TypeError`
described in `learnings.md` for this date.

**`#445` — SHIPPED, NOT VERIFIED, AND NOT VERIFIABLE TODAY.** NCAAF has no slate
on 2026-08-16 (season opens ~08-29); `layer1?sport=ncaaf` returns `games=0
empty_reason=no_precomputed_grid_artifact`. Do not close on the absence of the
old crash line. See `todo.md` `#445` UPDATE for the two unseparated readings.

**THE FREEZE FIX IS ON `main` AND NOT LIVE ON EITHER WORKER `[measured 08-16 22:2xZ, by blob]`.**
`origin/main` carries `scripts/refresh_mlb_oddsapi.py` blob **`426bbd70`**
(`_freeze_market_dirs` = 2). Live SHAs `bdb3dc58` (refresh-worker) and `440f5f29`
(live-odds-worker) both carry **`f471b0d2`** (= 0). Deploy runbook:
`.syndicate/handoff_deploy_freeze_reader_tree.md`. **`autoDeploy` is off, so it ships
nothing until someone deploys.**

**IT REACHED `main` WITHOUT BEING MERGED, AND ANCESTRY SAYS OTHERWISE `[08-16]`.**
`git merge-base --is-ancestor origin/wip/grading-blocker-freeze-fix origin/main` = **NO**,
yet the content is there — commits made on the shared local `main` were pushed by another
session. Judged by ancestry this reads "go merge it"; judged by content it is done.
**Compare by BLOB** (`git ls-tree` + `git cat-file`): `git show <rev>:<path>` returns a
false negative under Git Bash on dot-prefixed paths, and an empty-input `0` that looks
like a real zero.

**`send_message` IS UNAVAILABLE IN UNATTENDED SESSIONS, IN BOTH DIRECTIONS `[08-16]`.**
A scheduled-task run cannot reach its peers and cannot be reached. So the session that
most needs to coordinate before a deploy is structurally the one that cannot — which is
the practical argument for the control `learnings.md` already asks for (a
`deploy_claim.py` that refuses an unattended holder).

## GAME SHAPE — CONTRACT FOR FOUR SPORTS, TWO LIVE EMITS, **n = 0** `[measured 2026-08-16, lane game-shape-capture]`

Supersedes the "GAME SHAPE IS NOT PERSISTED FOR ANY SPORT" section above for the
capture half; that section's MEASUREMENTS stand, its status line does not.

`syndicate/features/shared/game_shape.py` (`origin/main` `8a01fa3d`) is the
extraction contract. **90 tests, 31 of 31 mutations caught.**

| sport | primitive | live emit | why |
|---|---|---|---|
| MLB | yes | **blocked** | producer is `vendor/.../flask_frontend.py:16647`, held by `mlb-live-gameline-distributions` |
| WNBA/NBA | yes | **blocked** | producer is `wnba/cards.py:3679`, held by `wnba-live-tier` |
| NFL | yes | **LANDED** | `nfl/live_game_state.py` was unclaimed |
| soccer | yes | **LANDED** | `soccer/ingestion/espn_live_state.py` was unclaimed |
| NCAAF | contract only | **no producer exists** | no `live_game_state` analog in `ncaaf/`; season opens 08-29 |

**THE NUMBER THAT MATTERS: every bucket is n = 0.** Nothing has run in
production. Both emits are PREPARED, NOT DEPLOYED, and no deploy was requested.
Do not read "contract for four sports" as coverage.

**Per-sport facts worth not re-deriving:**
- **MLB** — `LiveSituation` (`vendor/mlb_bettingv2/sim_engine/live_mc.py:20`) is
  built in full every live tick and discarded at the return. Capture is
  serialisation, not derivation.
- **WNBA/NBA** — **possession pace is UNDERIVABLE**: no FGA/TOV/OREB/FTA in any
  live artifact. The field is `points_per_minute` and records carry
  `possession_pace_available: False`. `wnba/cards.py:891 _wnba_elapsed_minutes`
  is the canonical clock math (10-min quarters, NOT NBA's 12); the shared copy
  is pinned to it by a 143-cell drift test.
- **NFL** — `situation` (down/distance/yardline) was in the fetched ESPN payload
  and never read; now captured, **live games only**. `pace_features.py` is
  SEASON-level and is not a live pace source.
- **NCAAF** — overtime is **UNTIMED** (alternating possessions), so elapsed
  minutes is undefined there and is returned as `None`, never extrapolated.
- **soccer** — `clock_remaining` is remaining **in that half**
  (`_HALF_SECONDS = 2700`): half 2 / 1800s is the **60th minute**. Its
  `live_state` **embeds the model's own `projection`**, which is excluded from
  the shape (circular conditioning). Second-half stoppage is invisible — the
  producer clamps at 0, so 90' and 95' both read 90; flagged `clock_saturated`.
- Margin bands are in **each sport's own unit** — runs / points / scores /
  goals. Buckets cap at 17 (13 for soccer).

## PLAY-BY-PLAY COVERAGE IS 5 SPORTS OF 8 `[measured 2026-08-16, `#454`]`

| have it | form |
|---|---|
| NFL | nflverse CSV, **372 cols incl. `epa`, `wp`, `wpa`** — 2025 = 46,452 REG plays |
| MLB | statsapi `feed_live` — 618 + 105 files |
| NCAAF | CFBD `plays_<season>_wk##.json.gz` — 51 files, 2023+ |
| WNBA / NBA | `live_pbp_stats_<date>.jsonl` — 53 / 11 |

**soccer, NHL and NCAAB have NONE** — the same three modules that are weakest
elsewhere. `vendor/wnba_betting_repo/models/pbp/` is **models trained from pbp**
(`.joblib`/`.onnx`), not pbp; a census by path would miscount it.

**pbp is the OFFLINE substrate; `game_shape` is the prediction-time conditioning
variable. Do not merge them** — that is how leakage gets in. pbp unblocks two
refusals already written into `game_shape.py` by name: the MLB leverage index
(needs a fitted win-expectancy table — `feed_live` is where it comes from) and
football down/distance value (NFL pbp already ships `epa`/`wp`/`wpa`).

## 2026-08-17 00:29Z — VERIFIED (sim-scheduling)

**ALL THREE SERVICES ARE CONVERGED WITH `main`.** Each is a merge commit with two
parents, cut on that service's own live SHA:

| service | commit | landed |
|---|---|---|
| web | `763a2f66` | 00:13:41Z |
| refresh-worker | `7c2b1a17` | 00:24:01Z |
| live-odds-worker | `c348da53` | 23:57:12Z |

**Do not deploy `main`'s tree to these services.** Each lineage held commits main
never received (21 / 52 / 40). See `learnings.md` 2026-08-17 for the per-file
`main-only == 0` test that finds them.

**`#440` Phase 1c VERIFIED IN PRODUCTION 00:11:36Z on live-odds-worker.** Soccer
pregame cadence now resolves PER LEAGUE: `mls due:imminent_handoff_to_t_window:1107s`
while `championship`, `la_liga` and `primeira_liga` all skip at 18-19h out
(`scope=league due=mls of=4`). Corroborated by a live process carrying
`--soccer-leagues mls`. Flag `SYNDICATE_PREGAME_LEAGUE_SCOPED_CADENCE` is set on
**live-odds-worker only** — the code is present but INERT on the other two, and
`FIXTURE_CADENCE sport=soccer` appears in live-odds-worker's logs and nowhere else.

**`refresh-worker` IS OOM CRASH-LOOPING — `#449`.** 23 `oomKilled` (4Gi) events
since 12:00Z, first 16:34:32Z, cadence tightened to ~11-15 min. It is a SPIKE not
a leak: post-restart memory is ~510MB of 4096. Each kill takes the running job
with it, so **any job longer than ~12 minutes may never complete on this service**
— check this before diagnosing unrelated "job never finished" symptoms.
NOT caused by tonight's deploys; the loop predates them by 96 minutes.

**Tooling:** `scripts/pending_deploys.py` re-derives pending work per service from
each service's CURRENT live SHA. Use it instead of `rev-list --count live..main`,
which reports 600-700 and means nothing because services run curated branches.


## LIVE TIER AND EDGE ATTRIBUTION — VERIFIED 2026-08-16/17 (lane `layer1-board-coverage`)

- **The ±4900 clamp is GONE platform-wide.** 0 clamp sites by content at all
  three live SHAs (web `9f617f34`, refresh-worker `fdc72dd0`, live-odds-worker
  `c348da53`), and **7,002 served `fair_price` values across mlb+wnba+soccer
  carry 0 at ±4900**. `[measured 00:0xZ]` The last piece shipped via another
  session's converge deploy, not by the clamp lane.
- **Soccer was serving bettable edges on FINISHED matches, and no longer is.**
  27 rows on `state: final` plus 9 live-from-pregame → **0**, confirmed by the
  enforcement counter `live_edge_enforced_rows: 36` matching the pre-fix count
  exactly. Two causes, both fixed: soccer published no structured liveness
  (every game read `pregame`), and the producer's own refusal was unreachable
  behind an early return. `[measured 18:38–18:56Z]`
- **`live_edge_policy` is now enforced at `attach_projections`**, over the
  finished grid, where no producer's control flow can route around it. Producers
  that already refuse correctly hit 0 rows (MLB reads 0).
- **WNBA has a live GAME-LINE tier**: 218 of 321 game rows `live_aware` on a live
  slate, edges withheld by `sim_count_unusable` because wnba publishes no
  `simsRun` — an `n` was NOT invented. **WNBA PROPS DO NOT**: `actual` /
  `live_projection` / `live_total` are NULL in all 24 rows at the source.
  `[measured 22:2x–23:3xZ]`
- **A finished game retains NO model probability on any served surface**
  (`{final: 14, live: 1}` → model_prob rows `{live: 12}`). Live projections
  exist only in `live_gameline_ledger`, which is on the worker's disk and
  matches **zero** `HOT_ARTIFACT_PATTERNS`. **Scoring live edges is blocked on
  transport, not on method.** `[measured 01:02Z]`
- **NFL slate window is 7 days**, not 5: the preseason week starts at +5 from a
  Sunday anchor, one day past the old edge. Measured — width 7 reaches 15
  preseason games vs 1, and is the widest that does not pull a second
  regular-season week onto a today board. Widens Layer 2's NFL horizon by
  construction (shared `slate_window_days`).

## refresh-worker OOM — verified 2026-08-16 evening CDT (session `refresh-worker-oom-trace`)

> Supersedes nothing above by contradiction; these SHARPEN the existing
> "STILL UNNAMED: which allocation inside the pass is the 2 GB" line. The
> allocator is still unnamed.

- **WHY `last_stage` cannot name the allocator — now specific, not just
  observed.** `_WATCHDOG_STATE` (`memory_observability.py:774`) is a
  module-level dict with **no thread-locals**, and this worker runs concurrent
  daemon threads (`live_lens_loop.py:914` and `:814`,
  `run_refresh_worker.py:3498`). `last_stage` therefore names whichever thread
  most recently emitted a marker, NOT the allocating thread. The existing
  "climbs with no stage marker" line is true; this is the mechanism. **Any
  attribution built on `last_stage` is invalid by construction.**
- **Excursion shape, n=7 distinct excursions (events API + watchdog samples):**
  effective headroom (`max - unreclaimable`) at excursion START **2231–2953MB**;
  magnitude **+2078 to +2860MB**; routine operating headroom **2913–3186MB**.
  Fatal-start and routine ranges **OVERLAP at 2913–2953MB**, so no static
  threshold at the check point separates "about to die" from "working".
- **`OVERVIEW_STOPPED_FOR_MEMORY` is silent because it is PASSING A CHECK IT
  SHOULD PASS**, not because it is broken. Measured at a real check point:
  headroom **3341.6MB**, unreclaimable 754MB — clears both floors.
  `OVERVIEW_MEMORY_CHECK_FAILED` fired 0 times; the permissive-default branch is
  NOT being taken. The seven non-MLB sports take the relaxed **1500MB** floor
  (`intelligence.py:2622`), and all 7 excursion-start headrooms clear 1500 while
  falling below 3000.
- **~87% OF ANON IS INVISIBLE TO THE PYTHON OBJECT CENSUS.**
  `UNTRACKED_BYTES_CENSUS explained_pct_of_anon = 13.7%`; `SMAPS_ANON`:
  `anon_mmap 1848.2MB`, **1293MB in mmap regions >64MB**, largest single region
  **515.0MB**. pymalloc takes 1MB arenas, so these are large contiguous buffers
  (NumPy / bytes / compression scratch), not object churn. **`HEAP_CENSUS`'s
  682k dicts are a red herring — every tracked holder totals 253.8MB of 2146MB.**
  **CAVEAT: these censuses fire at anon 1610–1700MB (elevated BASELINE), not at
  the 3700–4000MB peak. They describe what the process HOLDS, not what the
  excursion ALLOCATES.**
- **`apply_game_board_contract` is CHEAP and exonerated by measurement:** a
  `sport=nfl games=16` triplet ran mid-excursion for anon **2935→2937MB (+2MB)**.
- **Stage-marker density inside an excursion is ZERO** (4 consecutive
  sub-windows, each under the logs-API cap). Only the watchdog's own 2s clock
  samples in there. Any design that polls at existing stage markers cannot work.
- **The artifact-pull path is EXONERATED for the excursion** — presence in
  excursion vs matched control windows is the same rate (`pulled_hot_artifacts`
  1/7 vs 1/6). Stop re-investigating it without new evidence.

### Instruments now live on refresh-worker
- **`board_contract_end`** — emitted by `apply_game_board_contract` for all 8
  sports (the only per-sport hydration signal the seven non-MLB sports have).
  Live since `7c2b1a17`; present in `4ec66498`.
- **Peak SMAPS** — `SMAPS_ANON` at anon ≥2600MB
  (`SYNDICATE_MEMORY_WATCHDOG_PEAK_SMAPS_MB`), up to 3×, off-thread. Deployed
  `4ec66498` at 01:23:37Z. **HAD NOT FIRED at checkpoint time** — it needs an
  excursion, and the post-deploy worker was at anon 328MB.

- **refresh-worker RUNS OFF-MAIN DEPLOY BRANCHES.** Observed this evening:
  `deploy/wnba-live-tier` (`fdc72dd0`) → `deploy/rw-ship` (`7623a233`) →
  `deploy/rw-peak-smaps` (`4ec66498`). `origin/main` was 639 commits ahead at one
  point and 11 at another. **Always parent a deploy branch on the LIVE SHA and
  read that SHA before every deploy** — this is the `web_runs_a_deploy_branch`
  rule holding for refresh-worker too.

## `#454` COMPLETE — RE, WE AND LEVERAGE EXIST AND ARE ON MAIN `[measured 2026-08-16]`

Built from `data/mlb_source/**/feed_live`: 723 files, 714 games, **47 dates**
(2026-05-28..07-14), **53,049 plate appearances**.

- **`scripts/mlb_run_expectancy.py`** — RE24. Reproduces published values under a
  single **+14.6%** run-environment factor, 21 of 23 comparable cells within
  3 SE. **0 score cross-check mismatches over 12,361 half-innings**, monotonic in
  outs in all 8 base states.
- **`scripts/mlb_win_expectancy.py`** — WE by COMPOSITION. The empirical table was
  refused on measurement: 4,039 cells, **median 4 observations**, zero at 1,000+.
  Composed from P(k runs | base-out) at ~2,200 obs/state.
- **`scripts/mlb_leverage_index.py`** + **`shared/mlb_leverage_table.py`**
  (GENERATED, 5,382 cells) — LI matching published values (start 0.93,
  bottom-9-tied 2.36, bases-loaded-tied-2-out 10.61, 6-run 9th 0.00).
- **`game_shape.py` emits `leverage_index` + `leverage_source`.** Its leverage
  REFUSAL is lifted; the module stays pure (generated literals, function-local
  import).

**THE CAVEATS ARE LOAD-BEARING AND RIDE ON THE RECORDS THEMSELVES:**
league-average only — i.i.d. innings, one shared run distribution for both sides,
no team or park term, extras as a constant, and a start-of-game WE of **0.500**
against a published ~0.540 (that gap IS the omitted home-field advantage).
**Wrong for a specific matchup.** The RE reference table is **RECALLED, NOT
SOURCED**; two cells disagree by >3 SE and the attribution is deliberately OPEN.

## `#455` / `#456` — BOTH FIXED, NEITHER DEPLOYED `[measured 2026-08-16]`

- **`#455` WNBA:** `build_live_pbp_stats_payload` never computes pbp — it replays
  a stored snapshot and otherwise emits an all-null skeleton, and a skeleton has a
  NON-EMPTY `games` list, so once persisted it was served over real data all day.
  Reproduced on a slate that was two games FINAL and one LIVE, `generated_at`
  **frozen 3 hours**. Fixed in `ea9a2be8` under a logged claim override on
  `wnba/cards.py`, taken on explicit user instruction.
- **`#456` NBA:** a DIFFERENT defect — one undated snapshot path served for every
  requested date (`?date=2025-12-25` -> payload date `2026-06-13`). NBA never
  persists, so it does NOT share `#455`. Fixed in `0fcdefa4`.
- **Both change what a live endpoint serves and NEITHER IS DEPLOYED.** `#455` is
  verifiable only during a live slate: check that `generated_at` advances.

## WNBA pbp IS NOT A CORPUS `[measured 2026-08-16]`

`live_pbp_stats_*.jsonl` are **cached API responses** (`payload`/`ttl`/`ok` is an
HTTP envelope), not a data store. 53 files -> 120 game records -> 17 with
possessions -> minus 8 placeholder ids and 5 partial snapshots -> **4 usable
games**. The endpoint serves LIVE ONLY (past dates return 0 games), so there is
nothing to accumulate historically. **The mirror refresh cannot help — it copies
local-to-local and never contacts production.** `HOT_ARTIFACT_PATTERNS` excludes
the family, but that is NOT the binding constraint: there is nothing to export.


## LIVE GAME-LINE MODEL — SCORED 2026-08-17 (lane `score-live-gameline-edges`)

- **The live game-line model LOSES TO THE MARKET on every population.** Measured
  on the served `book_grid` artifact at **02:28:13Z, the COMPLETE 15-game MLB
  slate** (`by_state {final: 15, live: 0}`):

  | population | model Brier | market Brier | model − market | n |
  |---|---|---|---|---|
  | `all_records` | 0.27725 | **0.23883** | **+0.03842** | 3,638 |
  | `last_per_game` | 0.25925 | **0.20147** | **+0.05778** | 15 |
  | `priceable_only` | 0.29694 | **0.24070** | **+0.05624** | 2,409 |

  Positive = the market is better calibrated. **It is worst on
  `priceable_only` — the rows the board actually shows.**
- **SUPERSEDES the 14-game figures written at 02:1xZ** (`all_records` +0.02656).
  Those were taken while one game was still live; the gap WIDENED to +0.03842
  once the slate completed. Do not quote the earlier numbers.
- **ONE SLATE. `last_per_game` is n=15.** The direction is consistent across
  three populations and 3,638 records, but the magnitude rests on a single
  night. **Do not act on it without a second slate.**
- **`no_final_outcome_for_game` resolved to ZERO and was never a defect.** It
  read 416 at 02:12Z because one game was still in progress, and cleared itself
  when that game went final — the counter correctly refusing to score a result
  that did not exist yet. The only remaining unscored bucket is
  `record_carries_no_model_probability: 110`, which is the live re-sim
  publishing no probability (the same refusal surfacing as
  `prob_interval_swamps_edge` on the board).
- **The score is readable from the API**: `live_gameline_score` on
  `/api/board/book-grid?sport=<sport>&date=<date>`. The ledger itself stays
  unpublished (zero `HOT_ARTIFACT_PATTERNS`), so this block is the ONLY way the
  measurement leaves the worker.
- Live: refresh-worker `9bff3cc1`, web `685ab3e9`; `origin/main` matches both by
  content.


## refresh-worker OOM — part 2, verified 2026-08-16 late evening CDT (`refresh-worker-oom-trace`)

- **PEAK SMAPS ANSWERED ITS QUESTION.** 01:46:04–09Z, three samples, kill
  01:46:59Z: **one anon VMA 1096.5 → 1306.2 → 1586.4MB (+489.9MB in 5.5s) while
  regions #2/#3/#4 were IDENTICAL across all three samples**
  (268.7/201.8/194.0). Total `anon_mmap` +489.8MB — all growth in that one
  region. Baseline largest region was 515.0MB at anon 1610–1700MB.
- **BUT THE SECOND EXCURSION HAS A DIFFERENT SHAPE, and this is load-bearing.**
  02:26:43–02:27:01Z (kill 02:27:07Z): top5 `[751.1, 648.6, …]` →
  `[759.9, 622.1, …]` → `[774.6, 759.9, …]` — **two comparable regions trading
  places**, individual regions moving both up and down, total +136MB. **Do NOT
  treat "one giant growing region" as the established signature.** The most
  likely reconciliation is that VMA identity is an artifact of where the kernel
  merged adjacent mappings at sample time (`_SMAPS_MAX_PER_PROCESS`'s own comment
  says coalescing makes region counts meaningless), so region topology locates
  bytes but does not identify an allocator.
- **THE PER-FILE LEDGER CEILING IS CORRECT AND IS NOT THE BUG.** Applied BEFORE
  the read (`intelligence_evaluation.py:679`, `stat().st_size` → `continue`), and
  accepted chunks stream line-by-line. **The unbounded quantities are the SUM
  (8 chunks, 830,832,574 bytes accepted per load) and the MATERIALISATION by
  callers** — `_iter_record_payloads`'s own docstring: "holds every record of
  every accepted chunk at once".
- **`recommendation_engine.py`'s duplicate-load defects are ALREADY FIXED**
  (`:1253-1256`, `:1545-1548`, single load threaded via `_owned_records`). Its
  comments describe the pre-fix state — read the code, not the comment.
- **SETTLEMENT AUTORUN IS OFF**, verified three ways: code default for absent is
  False; `EVALUATION_SETTLEMENT_ENABLE_REFRESH_WORKER_AUTORUN='false'`;
  `EVALUATION_SETTLEMENT_REFRESH_INTERVAL_SECONDS` ABSENT. **105 env keys across
  2 pages — page 1 returns exactly 100, the cap; a single-page read is
  truncated.** Statically, the autorun is the ONLY production path to
  `evaluation_settlement._read_chunk_records`; no blueprint reaches it.
- **LANE CLAIMS MUST BE READ WITH THE GUARD'S OWN PARSER, not by eye.** Reading
  `lanes.md` by eye said `recommendation_engine.py` was claimed; running
  `_claims()` from `.claude/hooks/lane-guard.py` says it is NOT (a blank line
  ends the Files block before the path). 51 claimed paths across OPEN lanes.
  `evaluation_settlement.py` IS claimed (`grading-blocker-settled-zero`).
  Recipe: exec the hook source with `sys.exit(main())` neutralised — importing it
  runs and exits.

### Instruments live on refresh-worker (all deployed, none is a fix)
- `board_contract_end` — all 8 sports. Live since `7c2b1a17`.
- **Peak SMAPS** — `SMAPS_ANON` at anon ≥2600MB, ≤3×, off-thread. `4ec66498`.
  **FIRED TWICE, both readings above.**
- **`PAYLOAD_LOAD`** — on `_iter_record_payloads` (the choke point all three
  ledger entry points share), reporting `records` + `elapsed` + anon delta +
  caller. Live `7d8f960d` since 02:39:10Z. **HAD NOT FIRED at checkpoint
  (02:43Z).**
- **Kill cadence intact: 01:46:59Z, 02:27:07Z.** Earlier quiet was
  boot-confounded by four deploys; it was NOT improvement.

## WEB IS `60cdf8eb` — `#455` + `#456` DEPLOYED, ONE MEASURED `[2026-08-16 21:58 CDT / 02:58:34Z]`

**Supersedes any earlier web SHA in this file.** Deploy
`dep-da17ekm7bikc738hcisg`, scoped to two files and parented on the previous
live SHA `685ab3e9`, NOT on `main` (which carried 14 pending commits from six
lanes). Branch `origin/deploy/web-455-456` holds the commit.

- **`#456` MEASURED PASS:** `/nba/api/live_pbp_stats?date=<past>` returns
  `empty_reason=snapshot_date_mismatch` with the stale `snapshot_date` named;
  a request for the MATCHING date is still served unrefused (the control).
  Before: all dates returned payload date `2026-06-13`.
- **`#455` NOT MEASURED.** `generated_at` being current post-deploy is NOT
  evidence — the restart alone produces it. Needs a live WNBA slate:
  `generated_at` must ADVANCE between `ttl=1` fetches and no all-null record may
  persist. Instrument: `scripts/capture_wnba_pbp.py --date <d> --probe`
  (exits 2 when every record is a skeleton). **Unowned.**
- **Rollback:** redeploy `685ab3e9`.

**A FACT ABOUT THIS PLATFORM worth not re-deriving:** web's configured Render
branch is `main`, and its live SHA was nonetheless NOT an ancestor of `main`.
Previously-deployed commits fall out of `main`'s history when sessions rewrite
it. **Never infer the deploy base from the branch setting — read the live SHA
from the service.**

- **The evaluation bundle scanned the chunked ledger TWICE per pass; it now scans
  ONCE.** `build_intelligence_evaluation_bundle` passed `records=None` to both
  `build_evaluation_history_summary` and
  `build_recommendation_performance_analytics` — the branch that re-reads all 8
  chunks (830,832,574 bytes / 22,078 records each). Fixed by reducing once and
  threading the REDUCED set (raw would raise the peak above the double scan).
  **VERIFIED in production 03:10:25–03:10:26Z: exactly one
  `LEDGER_CHUNKS_ACCEPTED` before the bundle completion, against two pre-fix.**
  Live `a3340e32`.
- **THAT CHANGE DID NOT STOP THE OOM.** Kill at 03:10:46Z, 20s after the bundle.
  Series: 02:27:07, 02:51:09, 02:57:53, 03:10:46. **A THIRD ledger pass exists**
  (`SKIP 08-05/06/07`, different date set, therefore a different caller) which
  died mid-flight in the original excursion and is NOT covered by the
  bundle-level sharing.
- **The 830MB chunked loads do NOT go through the materialising wrapper.**
  `PAYLOAD_LOAD` (on `_iter_record_payloads`) fired twice with `records=0` in a
  window where `LEDGER_CHUNKS_ACCEPTED` fired three times — so the heavy loads
  take the six `_latest_by_recommendation_id(_stream_record_payloads(...))`
  reduce routes. **The materialisation hypothesis is DISCONFIRMED**; the cost is
  the transient of streaming/parsing 830MB repeatedly, not a retained list.

- **CORRECTION to the line above: there was no third ledger pass. There were
  exactly TWO scans per bundle, now ONE.** `_stream_chunked_ledger_records`
  (`:644-662`) has NO date scoping — manifest list or a full `*.jsonl` glob — so
  every call sees the same chunks and emits skips in SORTED order.
  `08-05/06/07` is a scan's START, `08-14/08-16` its END. Verified from two
  UNCAPPED windows: scan A ran 02:26:21->02:26:45, scan B 02:26:46->02:27:02.
- **Consequence, and it is the important one: the single-scan fix removes HALF
  the bundle's entire ledger cost, and the OOM continued regardless** (kill
  03:10:46Z, 20s after the post-fix bundle). **Repeated ledger scanning is not
  the cause of the excursion, or not the dominant part of it.** The remaining
  ~2GB is unexplained by anything measured this session.

## THE ALLOCATOR IS NAMED — 2026-08-17 03:48Z, by stack dump

**Supersedes the earlier line in this file saying "repeated ledger scanning is
not the cause of the excursion". That was WRONG and the error is worth keeping:
peak is PER-PASS, not cumulative — halving 2 scans to 1 cut DURATION
(81s/195s -> 46-49s) and could never have moved the peak, so "kills continued"
was evidence of the wrong lever, not of the wrong suspect.**

- **`build_intelligence_evaluation_bundle`, on the INTELLIGENCE-STATE BACKGROUND
  LOOP**, entered via `maybe_record_board_state_to_evaluation_ledger`
  (`pipeline/intelligence_state.py:2054`, loop at `:5411`). Captured in two
  frames of the same chain, in one excursion, while anon climbed 100+ MB/s:
  - `_latest_by_recommendation_id` (`intelligence_evaluation.py:1464`) consuming
    `_stream_chunked_ledger_records` (`:706`) — the reduce over the 830MB stream.
  - `_aggregate_performance_rows` (`:1992`) via
    `build_recommendation_performance_analytics` (`:2095`).
- Region #1 grew **764.7 -> 1041.3 -> 1260.4 MB** across three samples 5s apart
  while region #2 stayed frozen at 631.0MB and all others were static.
- **The pass is near-useless as well as expensive:**
  `performance_publish_count=22078`, `recommendation_count=60`,
  **`sample_size=0`**, `reliability_multiplier=1.0`, `duration_ms=49706`.
  22,078 ledger records reduced and aggregated to serve 60 recommendations,
  deriving zero samples and returning the neutral multiplier. `sample_size=0` is
  PRE-EXISTING (verified in pre-fix windows 23:52, 01:54, 02:34), not caused by
  the single-scan change.
- **A fix must address BOTH sites** — the reduce and the aggregation are separate
  allocations inside the same pass.
- Method note, because it is the transferable part: five instruments and six
  retractions preceded this, and every log-correlation attempt was refuted by its
  own control. The answer came from `faulthandler.dump_traceback(all_threads=True)`
  — the only instrument that does not require the allocating code to volunteer a
  log line.

## VERIFIED FIX — the refresh-worker OOM, 2026-08-17

- **The allocator was `build_intelligence_evaluation_bundle`'s ledger load**, on
  the intelligence-state background loop, entered via
  `maybe_record_board_state_to_evaluation_ledger` (`intelligence_state.py:2054`).
  Named by stack dump 03:48Z, confirmed by fix.
- **Fix: bound the load** to `load_recent_evaluation_records` (14-day window +
  64MB per-chunk ceiling). Live `59c07221` from 04:03:35Z.
- **Result: 154 minutes with no kill** (last kill 03:55:17Z, pre-deploy) against
  a ~6-7 min baseline, sustained at `procs=9, sim=6, 83.9%` — a busier machine
  than the excursions it replaced. Mechanism: 830,832,574 bytes -> 0 accepted;
  22,078 -> 755 records; 49.7s -> 24.2s.
- **NOT "stable": memory still ratchets slowly, 84% -> 86% over ~25 min.** The
  fast +2.1-2.9GB excursion is gone; a slow climb remains and is UNMEASURED
  beyond ~2.5 hours. Do not record this worker as fixed-and-stable on the
  strength of the kill interval alone.
- **Every ledger chunk exceeds the hot-path ceiling** — 08-06 480MB, 08-05
  367MB, 08-16 327MB, 08-14 305MB, down to 08-15 95MB (1.5x over 64MB). The
  daily chunks have grown large enough that ANY unbounded hot-path read of them
  is hundreds of MB.

- **The board-state path no longer reads the evaluation ledger at all.**
  `maybe_record_board_state_to_evaluation_ledger` passes
  `include_history_analytics=False`; the bundle emits
  `BUNDLE_ANALYTICS_SKIPPED query_type=board_state` and returns
  `history_status=null` / `performance_publish_count=null` (**null, not 0** — the
  code never ran). Live `8e3d2f95` from 14:39:32Z, measured 14:47:01Z.
  **49,707ms -> 5,608ms across the session's two fixes (89%).** Persistence is
  unaffected: `BOARD_STATE_LEDGER_RECORDED recommendation_count=95`.


## LEDGER SWEEP 2026-08-17 — ownership was decoupled from reality `[measured 11:5x–12:3x CDT, lane `ledger-sweep-2026-08-17`]`

**The headline fact: of 15 lanes reading OPEN in `lanes.md`, 9 had no live
owner.** Not archived — GONE. `get_session` returns *not found* for every one
of them. This was measured, not inferred: roster census via `list_sessions`
with `include_archived: true`, then a per-id `get_session` on each session named
by a lane or by a `.current-lane.<id>` marker.

Nothing in this sweep changed code, config, or any production surface.

### Owner census `[2026-08-17 12:0x CDT]`

| lane | owner | verdict |
|---|---|---|
| `convergence-phase7-crps` | `model-sim-track` | RUNNING |
| `wnba-live-tier` | `layer1-board-coverage` fork 6 | RUNNING (last claim file belongs to an archived fork) |
| `live-edge-basis` | `ask-answer-substance` fork | EXISTS, idle — the only orphan recoverable by resuming a session |
| `layer2-board-quality` | — | GONE |
| `clv-without-settlement` | `lane-cleanup` | GONE |
| `ask-sport-coverage` | — | GONE |
| `soccer-model-coverage` | `soccer-model` | archived, claims explicitly released |
| `live-game-line-projection` | `live-gameline-eval` | GONE |
| `refresh-worker-oom-recurrence` | — | GONE (but the OOM itself was FIXED 2026-08-17 by other sessions) |
| `odds-cadence-off-the-mlb-peak` | `sim-engine-track` | archived |
| `grading-blocker-settled-zero` | `alt-line-shortlist-watch` | GONE |
| `game-shape-capture` | — | GONE |

Each of the above now carries a `[SWEEP 2026-08-17]` block under its header
naming its owner state and its SINGLE NEXT ACTION. **File claims were left
ENFORCED** — every header still reads `OPEN`, so `lane-guard` behaves exactly as
before. Releasing them is a separate decision and is reversible either way.

`export-force-refresh-escape` was CLOSED by the `wnba-fixture-identity` session
at ~12:1x, mid-sweep. That is why the count reads 15 in one place and 14 in
another; both are correct at their stated time.

### The obligation counter was a high-water mark, not a count

`deploys.md` is append-only by its own convention, so a `Measured:` pending
marker is NEVER cleared — the MEASUREMENT row closing it is appended BELOW it.
**The session-start hook counted the markers, so its number could only ever go
up.** It read **14 owed**. The true number was **0**: 12 were already
discharged (seven by rows literally headed "closes the ... row" a few hundred
lines further down), and the remaining two are the same `#395` row counted
twice, which is a blast-radius cap nobody owes a measurement on.

Fixed at both ends: an `OBLIGATION RECONCILIATION` section in `deploys.md`
adjudicates all 14 with one `- RECONCILED:` line each, and the hook now
subtracts them and prints `$RECONCILED of $PENDING`. It reads
"none owed (14 of 14 markers reconciled)".

**Do not read that as a healthy service.** The refresh-worker's bounded-ledger
fix is VERIFIED against the kill it addressed; the slow ratchet (84% -> 86% over
~25 min) is real and unmeasured beyond ~10.5h.

### Two enforcement gaps found while counting

1. **`game-shape-capture` has no `— OPEN` header anywhere in `lanes.md`.**
   `lane-guard` only enforces claims on a lane whose status field matches
   `\bOPEN\b`, so **every file that lane claims has been unguarded the whole
   time**, while its 16 update blocks read as active work.
2. **One `layer1-board-coverage` block has a single em-dash**, so it has no
   parseable status field and the hook reports it as unguarded. It is a
   byte-identical duplicate of a block already in `lanes_closed.md` and
   disappears when the duplicates are removed.

### Stale claim markers retired

18 `.current-lane.<session-id>` markers pointed at sessions that no longer
exist. **Moved, not deleted**, to `.syndicate/lane_claims_retired/`. Five held
claims on lanes that are still open (`layer2-board-quality`,
`clv-without-settlement`, `ask-sport-coverage`, `grading-blocker-settled-zero`,
`refresh-worker-oom-recurrence`); the rest were empty or named closed lanes.
Markers belonging to ARCHIVED-but-existing sessions were deliberately left
alone — an archived session can be resumed.

### NOT DONE, and it needs a quiet window

**~1,000 lines of `lanes.md` are duplicates** — 13 blocks byte-identical to
copies already in `lanes_closed.md`, one exact 92-line intra-file duplicate
(`clv-without-settlement — SETTLED READING`, appearing twice), and one stray
1-line header. Six closed lanes (`ask-answer-substance`, `layer1-board-coverage`,
`mlb-live-gameline-distributions`, `score-live-gameline-edges`,
`mlb-tie-spread-baseline`, `render-events-reader`) still sit in the OPEN file.

It was not done because **the file moved under the transform, twice, inside ten
minutes** — three sessions append to it continuously, and the first attempt's
hash guard aborted correctly rather than clobbering a live append. Deleting a
thousand lines from a file being appended to is a different risk class from
annotating it. The transform script exists and is idempotent:
`scratchpad/sweep_lanes.py` (re-baseline `EXPECT_SHA` before running).

**`lanes.md` states its own cap: "Max concurrent OPEN lanes: 3". It is at 14.**

### ADDENDUM 2026-08-17 12:3x CDT — a LIVE lane is unguarded, and the cause is one character

Found while verifying the sweep, not while looking for it. `wnba-fixture-identity`
(opened minutes earlier by the running `layer1-board-coverage` fork 6) is written
with **ASCII hyphens instead of em-dashes** in its header:

    ### wnba-fixture-identity - OPEN - **stable fixture identity SHIPPED...

`lane-guard.py`'s `LANE_RE` is `^###\s+(\S+)\s+—\s*([^—]*)` and requires U+2014.
A hyphen header does not parse **at all**, so:

- its three claimed files are **NOT GUARDED**, including
  `scripts/refresh_wnba_oddsapi_props.py` — the same file the just-closed
  `export-force-refresh-escape` lane was editing;
- the session-start digest does not list the lane under OPEN LANES, so a session
  starting now sees no claim on those paths;
- the hook already prints `(1 lane header(s) have no parseable status and are NOT
  guarded)`, which is how it surfaced.

**Not fixed here — it is another session's live lane and cross-lane edits are
forbidden.** Notified via `send_message` to `layer1-board-coverage` fork 6.

**The general rule:** in this ledger the em-dash is not punctuation, it is
SYNTAX. Two hooks parse on it (`lane-guard` for enforcement, `session-start` for
the digest), and both fail silently and permissively — a malformed header does
not warn the lane's owner, it just stops protecting them. That is the third
distinct instance recorded of a guard whose unparseable input maps onto its
permissive branch.

### ADDENDUM 2 2026-08-17 12:4x CDT — a revert-in-waiting was sitting in the shared index, and it was 1,110 lines wide

Found by the mandatory `git diff --cached --numstat` check at the end of the
sweep, not by looking for it. The shared index held a staged `.syndicate/lanes.md`
that was **3,512 lines against a 4,622-line worktree** and contained **zero** of
the sweep annotations. A bare `git commit` by ANY session would have recorded a
`lanes.md` missing today's ledger work — the sweep, the `wnba-fixture-identity`
lane, and the sub-block restructure — **with the worktree clean and nothing
visibly wrong.**

**Disarmed path-scoped and index-only** (`git reset -- .syndicate/lanes.md`),
which changes no file; verified after: worktree still 4,622 lines with all 13
annotations. The two staged `game-shape-capture` blobs
(`syndicate/features/shared/game_shape.py`, `tests/test_game_shape.py`, 906/693
insertions, **0 deletions**) were LEFT ALONE — they are adds, not a revert, and
they belong to a lane's commit.

This is the **fifth** recorded occurrence of the stale-shared-index mechanism.
The count is the finding: it is not rare, and a single disarm is not a fix.
Re-check immediately before every commit.

### ADDENDUM 3 2026-08-17 13:4x CDT — the deploy guard is INSTALLED and proven live

`.claude/hooks/deploy-guard.py`, registered in `settings.json` on
`Bash|PowerShell`. Deploy ownership stops being a convention as of now.

**Proven in the live harness, both directions** — an ALLOW on its own is
worthless here, since an unregistered hook produces the identical result:

- `coordinator.id` pointed elsewhere → a command naming `render_deploy.py` was
  BLOCKED by the real `PreToolUse:Bash` hook, message and all.
- `coordinator.id` restored → the same command ran.

That also settles, by measurement rather than inference, that this session's id
really is the one in `coordinator.id`.

**21 assertions across two suites, both committed next to the hook:**

- `.claude/hooks/test_deploy_guard.py` — 17. Ordered MUST BLOCK first,
  deliberately: a suite that only ever sees green cannot distinguish a working
  guard from one that returns 0 unconditionally. It reads `coordinator.id`
  rather than hardcoding a session id, so the "from the COORDINATOR" case cannot
  silently decay into a second copy of the "another session" case.
- `.claude/hooks/test_deploy_guard_render_yaml.py` — 4, in a throwaway git repo,
  because the main suite only exercised the `render.yaml` branch in its ALLOW
  direction. That branch is the one guarding the 2026-08-08 `blueprint_sync`
  incident, so its positive case is shown, not assumed.

**What is allowed on purpose, and it is most of the surface:**
`render_events.py`, `render_logs.py`, `oom_band_report.py`,
`check_deploy_safety.py`, and any GET of `/deploys` — the Render API is read
constantly and a guard that blocks reads is one people disable. Only POST intent
and `render_deploy.py` are deploys.

**Fail-open is asserted, not assumed:** malformed payload, missing command, and
a missing `coordinator.id` were each tested to return 0. Deleting
`.syndicate/coordinator.id` remains the whole off switch.

**Grants** (`.syndicate/deploy/grants/<session_id>.json`, `expires_epoch`) are
tested in all three states: valid allows, expired does NOT, malformed does NOT.
A grant that cannot be parsed is not a grant.

### ADDENDUM 4 2026-08-17 14:0x CDT — local `main` is 135 BEHIND origin, and 17 commits had never left this machine

Measured while pushing. **This is the divergence `coordination-protocol.md`
predicted** ("origin/main held 144 commits the local checkout lacked while the
local checkout held 16 unpushed... sessions working blind and discovering it at
merge time"). The numbers today: **135 behind, 29 ahead, of which 17 are
genuinely unpushed** and 12 already reached `origin` by patch-id through another
route.

**Pushed to `ledger/coordinator-2026-08-17` (`e8b86d60`)** — a side branch, so
the work is durable and shareable without touching `origin/main` or the
worktree. Nothing can be lost now.

**`origin/main` is NOT updated, and that is a deliberate hold, not an oversight:**

- `git merge-tree` (no worktree, no index) reports **15 conflicted paths**,
  including `deploys.md`, `lanes.md`, `lanes_closed.md`, `learnings.md`,
  `state.md` — every append-only ledger file, conflicting on both sides' appends.
- the worktree has **52 uncommitted modified files** belonging to live sessions.

Integrating means resolving 15 conflicts and rewriting files under three or more
running sessions. That needs a quiet window and a decision, not a convenient
moment. **Do it as its own lane**, with no other lane open against the ledger.

**One false alarm worth recording, because I raised it myself.** The pre-push
blueprint check reported `render.yaml` in the diff. It was not: the pattern
`render.yaml` is a REGEX, `.` matched `_`, and it hit my own new test file
`test_deploy_guard_render_yaml.py`. The real blueprint is byte-identical between
`origin/main` and `HEAD`, confirmed by `git diff origin/main HEAD -- render.yaml`
returning empty and `git log origin/main..HEAD -- render.yaml` returning nothing.
Second unanchored-pattern error of the day (the first was `[—-]` as a bracket
range, which reported 12 open lanes as 1). **A `grep -c` answers "how many"
when the question was "which one" — ask for the name.**


## MERGED FROM origin/main — 2026-08-17, by the coordinator

Block-level union. These blocks existed on `origin/main` and nowhere
on the swept side. Appended verbatim, nothing edited, nothing reordered.

## KILLS ARE EVENTS — there is now a tool, and a census `[measured 08-16 17:5xZ]`

`scripts/render_events.py` (`#442`, shipped `f4627832`/`d72a3f66`, local tooling,
nothing deployed). Reads `/v1/services/<id>/events`. The 2026-08-15 FORBIDDEN
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

## ASK THE SYNDICATE

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
- **ASK ANSWER SUBSTANCE — LIVE web `9f617f34` (2026-08-16 23:30:17Z).** The
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
- **BOARD FINDING 3 IS FIXED, DEPLOYED AND MEASURED.** `edge_basis` is live on
  refresh-worker `b20072cd` and OBSERVED ON SERVED ROWS (build 17:44:30Z, 9
  `live_aware` rows): **the key is set IFF the edge is priceable** — 5 rows with a
  real `edge_vs_market_pct` carry it (`live` on spreads/totals, `pregame` on h2h),
  4 withheld rows carry `edge_unavailable_reason` instead. So a consumer can now
  tell which probability `edge_vs_market_pct` was computed against.
  **A RENAME TO `live_edge_vs_market_pct` REMAINS FORBIDDEN** —
  `layer2_board._model_edge_for` reads `edge_vs_market_pct` directly, so a rename
  prices LIVE rows off a PREGAME edge. Pinned by test.
  **The correct assertion for any future check is "every PRICEABLE `live_aware`
  row carries `edge_basis`"** — a watcher asserting it of EVERY `live_aware` row
  reported a false FAIL on the withheld rows and contradicted the repo's own test.
- **STANDING DECISION, 2026-08-17, FROM THE OWNER: KEEP THE GATE WAIVERS.**
  The three tolerated findings were put to the owner explicitly, together with
  the fact that the gate went FAIL -> PASS by waiving and not fixing, and the
  offer to revert `cda5ffdb` + `411977fd` if a failing gate was preferred.
  **The answer was keep them.** So a future session finding a green gate over
  three waived artifact-coverage findings is looking at a DECISION, not an
  oversight — do not revert either commit without a fresh owner override,
  logged here. What remains correct to do is DELETE the entries when the
  underlying artifacts are generated, and to rebuild the two checks the
  waivers removed (MLB daily mirror data presence; NFL/NCAAF advanced
  surfaces) rather than widening the allowances.
- **THE MIGRATION GATE PASSES, AND IT PASSES BECAUSE IT ASKS LESS.** FAIL ->
  PASS on 2026-08-17 via THREE WAIVERS AND ZERO FIXES: MLB daily manifest
  breadth (`cda5ffdb`), NFL/NCAAF advanced inputs (`411977fd`), plus the
  pre-existing nba/wnba entries. Waived findings still appear in `violations`;
  only `unexpected` drives `ok`, so what is tolerated stays visible.
  **Two checks no longer exist:** nothing verifies the MLB daily mirror has
  DATA (`PROTECTED_LOCAL_RESOLVER_CHECKS` runs against a TemporaryDirectory
  with patched roots and passes on an empty mirror), and NFL/NCAAF advanced
  surfaces are unguarded. Delete the entries when the generators run.
- **THE MLB MIRROR MANIFEST CHECK DOES NOT READ THE FILES.** Pulling 255
  artifacts (186 MiB) took the mirror 161 -> 416 `daily_summary` files matching
  production exactly (79 dates, 2026-05-28..08-17) and the violation did not
  move: it reads `mirror_refresh_latest.json`, CI-written and dated
  2026-07-14. **And that pull is invisible to git** — `.gitignore:36` ignores
  `data/*_source/source_artifacts/` while 1,977 files there are already
  tracked, so the new ones are ignored. It improves THIS CHECKOUT ONLY and
  will not survive a fresh clone.
- **THE FOUR NFL/NCAAF 2026 ADVANCED INPUTS WERE NEVER GENERATED.** Prior
  seasons exist (`upcoming_recs_2025_wk17/19/21`, the 2025 enhanced-totals CSV);
  `recommendations_summary/` exists for no season. **Nothing in this repo
  writes `upcoming_recs_*`** — only readers. None of the four is in
  `HOT_ARTIFACT_PATTERNS`, so **whether production has them is UNKNOWN**; do
  not read their local absence as absence there.
- **MIGRATION GATE ON `origin/main` `ea9340f2` (2026-08-17 01:50Z, `--skip-smoke`):
  FAIL — and the failure is DATA COVERAGE, not code.** All three command steps
  PASS: `audit_migration.py` (6 findings / 4 allowed, inside tolerance),
  `module_tracker_snapshot.py`, and `unittest tests.test_archives` — the one CI
  actually runs. The two failing sections are:
  **runtime dependency** — protected mirror assets missing (`mlb` daily manifest
  breadth `daily/daily_summary_` + `daily/sims/`; `nba` betting-card breadth
  `season_betting_card_manifest_` + `season_betting_card_day_`); and
  **advanced readiness** for 2026-08-16 — `nfl` missing its weekly recommendation
  snapshot (2/3), `ncaaf` missing weekly summary + recommendation index +
  enhanced totals export (0/3).
  **DO NOT QUOTE THIS AS "main is broken".** Both failures are artifacts absent
  from the CHECKOUT, and `data/**` in git is a lossy per-family mirror, not a
  snapshot of production. Whether production has them was NOT checked. The
  browser parity smoke was skipped, so nothing here speaks to client parity.
- **`.syndicate/lanes.md`'s STRUCTURAL INVARIANTS ARE CHECKABLE IN ONE
  COMMAND, and both hold as of 2026-08-17 01:0xZ** (17 headings, 8 OPEN
  lanes, 40 claims):

      py -3 scripts/check_lane_invariants.py

  It asserts (1) every claimed file has exactly ONE open holder and (2) no
  OPEN lane sits under `## Archived lanes` — archiving one moves its body to
  `lanes_closed.md`, which `lane-guard` never reads, so its file protection
  disappears silently. It also HINTS at prose inside a `- Files:` block,
  because `_claims()` reads every indented line there as a claim.
  **It names no lane on purpose** — the roster turns over hourly and a check
  naming a lane goes stale in hours.
  **`lane-guard.py` cannot be imported to reuse its parser**: it runs
  `main()` at import and `sys.exit()`s on EOF stdin, killing the caller with
  exit code 0 and no output. The regexes are copied and pinned to the hook's
  source by `tests/test_check_lane_invariants.py`.
  `lanes.md` is 208KB, down from 310KB on 2026-08-16.
- **The Ask sim-vs-line clause claims a direction ONLY when the mean clears
  the line by 0.5 (`_SIM_DIRECTION_MIN_MARGIN`).** The precondition is that
  the distribution's MEDIAN is on the same side as the mean; for Poisson
  counts the median sits ~1/3 below, so `mean > line` stops implying
  `P(over) > 50%` in a band just above the line. **A 2.6 mean against a 2.5
  goal line reads 48.2% — the most common shape in soccer.** An earlier
  `player_name` prop/game split was wrong for exactly that case (a soccer
  total is a low-count GAME row). NOT verified on served soccer rows —
  soccer had 0 board rows all session; re-check when it returns.
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

## PLAY-BY-PLAY COVERAGE IS 5 SPORTS OF 8 `[measured 2026-08-16, `#454`]`

| have it | form |
|---|---|
| NFL | nflverse CSV, **372 cols incl. `epa`, `wp`, `wpa`** — 2025 = 46,452 REG plays |
| MLB | statsapi `feed_live` — 618 + 105 files |
| NCAAF | CFBD `plays_<season>_wk##.json.gz` — 51 files, 2023+ |
| WNBA / NBA | `live_pbp_stats_<date>.jsonl` — 53 / 11 |

**soccer, NHL and NCAAB have NONE** — the same three modules that are weakest
elsewhere. `vendor/wnba_betting_repo/models/pbp/` is **models trained from pbp**
(`.joblib`/`.onnx`), not pbp; a census by path would miscount it.

**pbp is the OFFLINE substrate; `game_shape` is the prediction-time conditioning
variable. Do not merge them** — that is how leakage gets in. pbp unblocks two
refusals already written into `game_shape.py` by name: the MLB leverage index
(needs a fitted win-expectancy table — `feed_live` is where it comes from) and
football down/distance value (NFL pbp already ships `epa`/`wp`/`wpa`).
## 2026-08-17 00:29Z — VERIFIED (sim-scheduling)

**ALL THREE SERVICES ARE CONVERGED WITH `main`.** Each is a merge commit with two
parents, cut on that service's own live SHA:

| service | commit | landed |
|---|---|---|
| web | `763a2f66` | 00:13:41Z |
| refresh-worker | `7c2b1a17` | 00:24:01Z |
| live-odds-worker | `c348da53` | 23:57:12Z |

**Do not deploy `main`'s tree to these services.** Each lineage held commits main
never received (21 / 52 / 40). See `learnings.md` 2026-08-17 for the per-file
`main-only == 0` test that finds them.

**`#440` Phase 1c VERIFIED IN PRODUCTION 00:11:36Z on live-odds-worker.** Soccer
pregame cadence now resolves PER LEAGUE: `mls due:imminent_handoff_to_t_window:1107s`
while `championship`, `la_liga` and `primeira_liga` all skip at 18-19h out
(`scope=league due=mls of=4`). Corroborated by a live process carrying
`--soccer-leagues mls`. Flag `SYNDICATE_PREGAME_LEAGUE_SCOPED_CADENCE` is set on
**live-odds-worker only** — the code is present but INERT on the other two, and
`FIXTURE_CADENCE sport=soccer` appears in live-odds-worker's logs and nowhere else.

**`refresh-worker` IS OOM CRASH-LOOPING — `#449`.** 23 `oomKilled` (4Gi) events
since 12:00Z, first 16:34:32Z, cadence tightened to ~11-15 min. It is a SPIKE not
a leak: post-restart memory is ~510MB of 4096. Each kill takes the running job
with it, so **any job longer than ~12 minutes may never complete on this service**
— check this before diagnosing unrelated "job never finished" symptoms.
NOT caused by tonight's deploys; the loop predates them by 96 minutes.

**Tooling:** `scripts/pending_deploys.py` re-derives pending work per service from
each service's CURRENT live SHA. Use it instead of `rev-list --count live..main`,
which reports 600-700 and means nothing because services run curated branches.

## 2026-08-17 00:4xZ — LIVE HAZARD (sim-scheduling): refresh-worker's deploy lineage is POISONED until `d9088741` ships

**Do not deploy refresh-worker from `7c2b1a17` + `main`. It will silently
re-revert 10 lines of `memory_observability.py`.**

`7c2b1a17` (live since 00:24:01Z) was built with its tree computed against
`origin/main=7eb5fb28` while its `-p` parent re-resolved to `40c3c44b` in a later
git call. New parent, old tree — a valid fast-forward, so `git push` accepted it
with no force and no warning.

It reverted, on the deployed service only (`origin/main` is intact; `40c3c44b`
and `2aa30b7a` remain ancestors of main):

| path | lines | matters? |
|---|---|---|
| `syndicate/features/shared/memory_observability.py` | **-10** | **YES, code** |
| `.syndicate/{deploys,learnings,log/2026-08-16,state}` | -229 | no, inert on a service |

The code is the smaps-vs-cgroup **reconciliation guard** (`cgroup_anon_mb`,
`reconciles_within_pct`, `reconciles`) — removed from the one service that is
OOM crash-looping (`#449`), while `#449` was open.

**WHY A PLAIN RE-MERGE WILL NOT FIX IT.** The bad merge recorded the removals as
INTENTIONAL EDITS on the live side. A fresh `merge-tree` therefore sees "live
changed, main did not" and preserves the deletion. Re-merging returned
`deletions=239` a second time. The five paths must be restored from `main`
EXPLICITLY, which is what `d9088741` does.

**THE FIX IS BUILT AND PUSHED: `d9088741` on branch `deploy/rw-converge-fix`.**
It descends from live `7c2b1a17`, restores the five paths from main, keeps the
three LIVE-wins resolutions (0 lines lost), and asserts `deletions vs the main
parent == 0`. **It is deliberately NOT deployed — it is to ride the next
refresh-worker ship, not to justify one of its own.** Whoever ships next: base on
`d9088741`, not on `7c2b1a17`.

**THE ASSERTION THAT CATCHES THIS CLASS, and nothing else does:**

    DEL=$(git diff --numstat "$MAIN" "$SHA" | awk '{d+=$2} END {print d+0}')
    [ "$DEL" -eq 0 ] || refuse

Ancestry checks, conflict-marker scans and the `render.yaml` guard ALL PASSED on
the broken commit. Only counting deletions against the main parent sees it.
And resolve `origin/main` EXACTLY ONCE per build — never re-read a symbolic ref
in a later call.

## 2026-08-17 00:5xZ — CORRECTION: the "silent revert" was a LAG, not a removal. I overstated it twice.

**What I claimed** (in `state.md`'s POISONED-lineage block, in commits
`d9088741` / `7623a233`, and to the user): `7c2b1a17` "reverted 10 lines of
`memory_observability.py` — the smaps-vs-cgroup RECONCILIATION guard — on the one
service that is OOM crash-looping, while `#449` was open."

**What is actually true, measured:**

    git diff --numstat 7c2b1a17 40c3c44b -- syndicate/features/shared/memory_observability.py
    -> +10  -49

It is a **refactor**, not a deletion. `7c2b1a17` carried the OLDER implementation
(`_process_rss_anon_bytes()`, reading `RssAnon` from `/proc/self/status`); main
had replaced it with cgroup-based accounting (`cgroup_anon_mb`). **`grep -c
reconciles_within_pct` returns 1 on BOTH trees.** The guard was never absent.

**The tell I nearly walked past:** a `SMAPS_ANON` line emitting
`reconciles_within_pct` at **00:48:32Z** — five minutes BEFORE my ship landed, so
emitted by `7c2b1a17` itself. If that SHA had truly lacked the field it could not
have printed it. I found this only because a follow-up query for the field's
VALUES came back empty and I chased the discrepancy instead of banking the
watcher's "1 line" count.

**Corrected severity.** The deployed service was LAGGING main's improved memory
instrumentation, which is worth fixing and was fixed by `7623a233`. It was not
"instrumentation removed during an incident". The stale-tree MECHANISM is real
and the `deletions vs the main parent == 0` assertion still stands — what was
wrong was my reading of WHAT the 239 lines contained. 229 of them were ledger;
the 10 code lines were one side of a refactor.

**The lesson, which is not the one I thought I was recording:** a `numstat`
deletion count tells you SIZE, never MEANING. I read `-10 code lines` and
supplied "a safety guard was removed" without opening the diff. Read the lines
before naming the damage — the same rule already written for the `wnba/cards.py`
`american_price` scare earlier this session, which I got right and then did not
apply an hour later.

## 2026-08-17 01:3xZ — VERIFIED (sim-scheduling): the real MLB re-sim rules

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
## WNBA pbp IS NOT A CORPUS `[measured 2026-08-16]`

`live_pbp_stats_*.jsonl` are **cached API responses** (`payload`/`ttl`/`ok` is an
HTTP envelope), not a data store. 53 files -> 120 game records -> 17 with
possessions -> minus 8 placeholder ids and 5 partial snapshots -> **4 usable
games**. The endpoint serves LIVE ONLY (past dates return 0 games), so there is
nothing to accumulate historically. **The mirror refresh cannot help — it copies
local-to-local and never contacts production.** `HOT_ARTIFACT_PATTERNS` excludes
the family, but that is NOT the binding constraint: there is nothing to export.

## 2026-08-17 02:1xZ — VERIFIED (sim-scheduling): the primary goal has ONE blocker

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

## LIVE GAME-LINE MODEL — SCORED 2026-08-17 (lane `score-live-gameline-edges`)

- **The live game-line model LOSES TO THE MARKET on every population.** Measured
  on the served `book_grid` artifact at **02:28:13Z, the COMPLETE 15-game MLB
  slate** (`by_state {final: 15, live: 0}`):

  | population | model Brier | market Brier | model − market | n |
  |---|---|---|---|---|
  | `all_records` | 0.27725 | **0.23883** | **+0.03842** | 3,638 |
  | `last_per_game` | 0.25925 | **0.20147** | **+0.05778** | 15 |
  | `priceable_only` | 0.29694 | **0.24070** | **+0.05624** | 2,409 |

  Positive = the market is better calibrated. **It is worst on
  `priceable_only` — the rows the board actually shows.**
- **SUPERSEDES the 14-game figures written at 02:1xZ** (`all_records` +0.02656).
  Those were taken while one game was still live; the gap WIDENED to +0.03842
  once the slate completed. Do not quote the earlier numbers.
- **ONE SLATE. `last_per_game` is n=15.** The direction is consistent across
  three populations and 3,638 records, but the magnitude rests on a single
  night. **Do not act on it without a second slate.**
- **`no_final_outcome_for_game` resolved to ZERO and was never a defect.** It
  read 416 at 02:12Z because one game was still in progress, and cleared itself
  when that game went final — the counter correctly refusing to score a result
  that did not exist yet. The only remaining unscored bucket is
  `record_carries_no_model_probability: 110`, which is the live re-sim
  publishing no probability (the same refusal surfacing as
  `prob_interval_swamps_edge` on the board).
- **The score is readable from the API**: `live_gameline_score` on
  `/api/board/book-grid?sport=<sport>&date=<date>`. The ledger itself stays
  unpublished (zero `HOT_ARTIFACT_PATTERNS`), so this block is the ONLY way the
  measurement leaves the worker.
- Live: refresh-worker `9bff3cc1`, web `685ab3e9`; `origin/main` matches both by
  content.
## WEB IS `60cdf8eb` — `#455` + `#456` DEPLOYED, ONE MEASURED `[2026-08-16 21:58 CDT / 02:58:34Z]`

**Supersedes any earlier web SHA in this file.** Deploy
`dep-da17ekm7bikc738hcisg`, scoped to two files and parented on the previous
live SHA `685ab3e9`, NOT on `main` (which carried 14 pending commits from six
lanes). Branch `origin/deploy/web-455-456` holds the commit.

- **`#456` MEASURED PASS:** `/nba/api/live_pbp_stats?date=<past>` returns
  `empty_reason=snapshot_date_mismatch` with the stale `snapshot_date` named;
  a request for the MATCHING date is still served unrefused (the control).
  Before: all dates returned payload date `2026-06-13`.
- **`#455` NOT MEASURED.** `generated_at` being current post-deploy is NOT
  evidence — the restart alone produces it. Needs a live WNBA slate:
  `generated_at` must ADVANCE between `ttl=1` fetches and no all-null record may
  persist. Instrument: `scripts/capture_wnba_pbp.py --date <d> --probe`
  (exits 2 when every record is a skeleton). **Unowned.**
- **Rollback:** redeploy `685ab3e9`.

**A FACT ABOUT THIS PLATFORM worth not re-deriving:** web's configured Render
branch is `main`, and its live SHA was nonetheless NOT an ancestor of `main`.
Previously-deployed commits fall out of `main`'s history when sessions rewrite
it. **Never infer the deploy base from the branch setting — read the live SHA
from the service.**

## WNBA GAME-STATE AND FIXTURE COVERAGE — 2026-08-17 (lane `wnba-live-tier`)

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

## MLB PITCHER-OUTS MODEL AND ITS INPUTS — verified 2026-08-17 (lane `convergence-phase7-crps`)

- **The `outs` over-projection is the F5 STARTER LEASH.** 267 starts / 13 dates /
  87,500 game-sims replayed from archived roster artifacts. Every metric improves
  monotonically as the leash shortens; dispersion **1.002 → 0.791 against a
  calibrated 0.7979**, short-start gap **−0.1778 → −0.0266**. Replay at the
  current leash reproduces production (P(outs<15) 0.0965 vs 0.104 on 726 starts).
- **`starter_min_innings` is now a `manager_pitching_overrides` key** (v2 hook).
  Absent = the manager profile's value = byte-for-byte no-op. `0` disables the
  leash; the old `max(1, …)` silently promoted 0 to 1.
- **NO LEASH VALUE IS PROMOTED.** The model loses to a CONSTANT baseline at every
  grid point (baseline MAE 3.0912 vs best 3.1852), and residual bias at leash 0
  is still −1.470 — the leash is the largest term, not the only one.
- **THE BETTING GRADE IS CONFOUNDED. Do not re-run it without the side-blind
  baseline.** On 148 starts ALWAYS OVER returned **58.78% / +8.16% with no
  model**; the grid varied only how often it bet the over (106→146 of 148); the
  whole spread was **1.49 SE**. Taken naively it endorses the over-projection
  defect. **Standing rule: print ALWAYS OVER / ALWAYS UNDER beside any prop hit
  rate.**
- **ARCHIVED LINE COVERAGE: only 5 of 29 dates carry >=8 pitchers with an `outs`
  line; 12 of 29 carry ZERO.** The discriminator is `retrieved_at` INSIDE the
  artifact: same-day-afternoon fetches carry 26–30 pitchers, fetches after
  ~02:00Z the next day carry 0, because books pull player-prop markets once games
  end. `mode` is `live` on every file including the `_pregame` ones.
- **`betting_accuracy.py` is ABSENT from this checkout** — the overrides file's
  55.78%/54.65% came from an instrument that is not here. Do not compare to it.
- **Re-simulating the leash grid on PRODUCTION data is impossible** — it needs
  schema-v4 `roster_obj_*.json`; production 404s at every root and the sim's
  loader rejects the raw bundle (`schema_version=None`).


## MERGED FROM origin/main — 2026-08-17, by the coordinator

Block-level union. These blocks existed on `origin/main` and nowhere
on the swept side. Appended verbatim, nothing edited, nothing reordered.

## MLB PITCHER-OUTS MODEL AND ITS INPUTS — verified 2026-08-17 (lane `convergence-phase7-crps`)

- **The `outs` over-projection is the F5 STARTER LEASH.** 267 starts / 13 dates /
  87,500 game-sims replayed from archived roster artifacts. Every metric improves
  monotonically as the leash shortens; dispersion **1.002 → 0.791 against a
  calibrated 0.7979**, short-start gap **−0.1778 → −0.0266**. Replay at the
  current leash reproduces production (P(outs<15) 0.0965 vs 0.104 on 726 starts).
- **`starter_min_innings` is now a `manager_pitching_overrides` key** (v2 hook).
  Absent = the manager profile's value = byte-for-byte no-op. `0` disables the
  leash; the old `max(1, …)` silently promoted 0 to 1.
- **NO LEASH VALUE IS PROMOTED.** The model loses to a CONSTANT baseline at every
  grid point (baseline MAE 3.0912 vs best 3.1852), and residual bias at leash 0
  is still −1.470 — the leash is the largest term, not the only one.
- **THE BETTING GRADE IS CONFOUNDED. Do not re-run it without the side-blind
  baseline.** On 148 starts ALWAYS OVER returned **58.78% / +8.16% with no
  model**; the grid varied only how often it bet the over (106→146 of 148); the
  whole spread was **1.49 SE**. Taken naively it endorses the over-projection
  defect. **Standing rule: print ALWAYS OVER / ALWAYS UNDER beside any prop hit
  rate.**
- **ARCHIVED LINE COVERAGE: only 5 of 29 dates carry >=8 pitchers with an `outs`
  line; 12 of 29 carry ZERO.** The discriminator is `retrieved_at` INSIDE the
  artifact: same-day-afternoon fetches carry 26–30 pitchers, fetches after
  ~02:00Z the next day carry 0, because books pull player-prop markets once games
  end. `mode` is `live` on every file including the `_pregame` ones.
- **`betting_accuracy.py` is ABSENT from this checkout** — the overrides file's
  55.78%/54.65% came from an instrument that is not here. Do not compare to it.
- **Re-simulating the leash grid on PRODUCTION data is impossible** — it needs
  schema-v4 `roster_obj_*.json`; production 404s at every root and the sim's
  loader rejects the raw bundle (`schema_version=None`).

## ODDS-SWEEP OWNERSHIP GATE — ON `main`, RUNNING ON NEITHER WORKER `[measured 2026-08-17 19:2xZ, by content]`

- **`20025cc4` (`_sweep_ownership_exclusion`) is absent from both workers' live
  SHAs** — refresh-worker `8c0bd8e6` and live-odds-worker `abc9987515`, checked
  by CONTENT (`git show <sha>:<path>`), not by ancestry. **The starvation it
  fixes is live in production.**
- The defect: `_live_refresh_loop_effective_sports` fell back to "every
  season-active sport" when `SYNDICATE_LIVE_ODDS_REFRESH_SPORTS` was unset,
  ignoring BOTH `SYNDICATE_ACTIVE_SPORTS` and the ownership flags. refresh-worker
  swept mlb/nfl/soccer/wnba owning only nfl; live-odds-worker swept NOTHING. The
  non-owner wins the shared cadence marker and starves the owner.
- **DO NOT NAMESPACE THE CADENCE MARKER.** Rejected in code by the authoring
  lane: the ownership flags are the intended mutex. With the gate deployed the
  shared marker is a SAFETY NET — namespacing alone lets two services sweep the
  same sport independently and doubles OddsAPI spend (cap ~62.7%, MLB 93% of it).
- **Weekly sports are deliberately NOT gated** by it — gating them broke
  `test_run_tick_claims_weekly_sports_on_game_days` and would reintroduce the 24h
  NFL capture gap measured 2026-08-07.
- Verify after deploy is TWO-SIDED: `SWEEP_OWNERSHIP_EXCLUDED` on refresh-worker
  naming `mlb` in `dropped`, **and** an MLB pregame sweep appearing on
  live-odds-worker. Half one proves the non-owner stopped, not that the owner
  started.


## WNBA fixture identity + the sweep ownership gap - VERIFIED 2026-08-17

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
- **`.syndicate/coordinator.id` is CORRECT, not stale** - two-id design, see
  `coordinator.md:139`. **Do not edit or delete it.**
