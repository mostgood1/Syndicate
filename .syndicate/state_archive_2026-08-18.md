# state.md archive — 2026-08-18 (coordinator)

Sections moved out of `state.md` because a LATER section in that same file
supersedes them, or their stated fact is verifiably no longer true. Nothing
was deleted; grep here before concluding a fact was never measured, and never
cite this file as current.

**A date was NOT the test.** `USER DECISIONS` is dated 2026-08-14 and is
standing policy -- archiving by age would have buried it. Each section below
carries the specific evidence that it is superseded.

- `## LIVE SESSIONS AND LANES `[re-measured 2026-08-15 03:0xZ / 22:0x CDT]`` — a session census from 08-15; superseded by the LEDGER SWEEP 2026-08-17 census in this same file
- `## refresh-worker OOM — verified 2026-08-16 evening CDT (session `refresh-wo` — superseded by 'VERIFIED FIX -- the refresh-worker OOM, 2026-08-17' below it
- `## refresh-worker OOM — part 2, verified 2026-08-16 late evening CDT (`refre` — superseded by the same 2026-08-17 VERIFIED FIX section
- `## WEB IS `60cdf8eb` — `#455` + `#456` DEPLOYED, ONE MEASURED `[2026-08-16 2` — web is e5107913 as of 2026-08-18; the SHA in the heading is stale
- `## Web card surfaces — soccer, 2026-08-15 03:1xZ `[measured]`` — a dated surface snapshot, superseded by the soccer work of 08-17/18
- `## UI / card surface — verified 2026-08-15 (session `ui-plan-lane-gh`)` — a dated surface snapshot; the UI probe sections below carry the current state

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


