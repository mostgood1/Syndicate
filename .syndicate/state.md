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
as-of pair** (`allow_undated` in 5 places). **The ARTIFACT effect is still
UNMEASURED** — content is verified, the rate of price-missing rows is not.

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
  denominator, not evidence.** A `rows>0` reading is still owed.** A live-odds-worker WNBA producer run was observed at 01:31:36Z, before
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

## MEMORY — refresh-worker: THE 2GB IS A TRANSIENT, AND ITS ALLOCATOR IS STILL UNNAMED `[measured 08-16 15:1xZ]`

**Three fixes are live in `d72d670c` and exercised; NONE has been shown to move
the transient.** `51ae7218` (odds-shard duplicate parse), `21f8a165` (ledger
streaming + `LEDGER_CHUNKS_ACCEPTED`), `aa190d58` (rank_recommendations: 3 full
ledger loads per call -> 1). Verified by counting the branch, not the outcome.

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

**THE DAYTIME LULL IS WORTHLESS AS EVIDENCE.** Same clock window one day apart:
peak anon 2,816.7 MB pre-fix vs 2,898.5 MB post-fix, **zero excursions on both**.
The pre-fix code once ran **17h51m clean** in daylight. Judge only on the
live-slate band ~22:00Z-05:00Z; `scripts/oom_band_report.py` measures it.

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
- **Layer 1 is dark on ~3 of 5 builds** (`count=0`). On the stated hierarchy that
  is an outage on the research surface, not a deletion argument. Program Tier 4.
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

- **CURRENT BASELINE: 38/52** (advice 4/5, entity 9/10, explain 4/6, history 2/5,
  lookup 8/8, ranking 7/10, refusal 4/8), measured 16:52Z on live `0bf866c3`, in
  `reports/ask_regression/post_ask_sport_coverage_2026_08_15.json`.
  `answer_source: snapshot` is the EXPECTED source, not a finding.
  **Judge every future change against 38/52, and RE-MEASURE the baseline before
  trusting it** — the previous recorded figure (23/52) was two deploys stale by
  the time it was used, and had it been trusted a `refusal` regression from a
  different lane would have been inherited as the new lane's own.
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
- **THE SOCCER SIM PUBLISHES ZERO PLAYER PROJECTIONS.** All four production
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


## UI probe - the height model and the settle rule `[measured 08-15 23:xxZ]`

**`scripts/ui_layout_probe.py` now reports a LAYOUT signal for MLB**, not a
content one: it fits `height = chrome + k * content_units` per game state and
reports the residual. Baseline, settled: mlb mobile Live 6px / Preview 54px,
mlb desktop Live 18px. Budget `LAYOUT_RESIDUAL_BUDGET_PX = 150` (~3x worst
clean reading). Desktop Preview is declared UNRELIABLE — its grid wraps into
columns, so height is linear in ROWS not pairs. `[measured]`

**MLB RENDERS PROGRESSIVELY FOR ~4 SECONDS AND `wait_for_selector` DOES NOT
COVER IT.** Total `.cards-data-pair` across 15 cards at 390px: 482 at +0ms,
530 at +600ms, 590 at +1200, 683 at +2000, **719 at +3000 and stable**. Any
probe of `/mlb/cards` must wait for the DOM to stop changing, not for the first
card to attach. The probe does this now (`_settle`), records `settledMs`, and
FAILS if the render never settles. MLB 3.6-4.0s; every other sport 0.8s.
**Every MLB figure produced before this was taken at ~74% of final content.**
`[measured]`


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
