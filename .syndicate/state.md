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
the second time holding a revert of ledger work committed ~20 minutes earlier
(staged `lanes.md`/`state.md` missing lines that were present in BOTH `HEAD` and
the worktree). Each was disarmed with a path-scoped `git reset`, which touches
no file. **Run `git diff --cached --numstat` before EVERY commit and read the
DELETION column** — a stale index shows up as deletions-only against a HEAD that
moved past it. `[measured 08-15, 2 occurrences]`

---

## USER DECISIONS `[2026-08-14 ~21:5x CDT]`

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

**Repo state `[measured 08-15 02:3xZ]`:** `origin/main` is `be5efcbf`; the shared
tree has **ZERO commits not upstream** and is **128 BEHIND**. Being behind is a
read-your-own-staleness problem; being ahead is a lost-work problem. Anyone
reading local `git log` for lineage is reading a stale tree — `git fetch` and
read `origin/main`.

---

## MEMORY — refresh-worker `#435` / `#423`, OPEN

**Owner: session "Ship refresh-worker branch". Nobody else touches
refresh-worker memory, `pipeline/intelligence_state.py`, or the board-build loop.**

- **`#387` FIXED BOARD COVERAGE. IT DID NOT FIX THE OOM.** refresh-worker was
  OOM-killed **16 times on 2026-08-14**, the last 26 minutes after both halves
  were live. Source: `/v1/services/<id>/events`, **NOT the logs** — a killed
  process cannot log its own death, so a log grep for `oomKilled` is worthless
  for this question and produced a retracted "0 kills" claim. `[measured 08-15]`
- **`#387` shipped in TWO halves** — `cfee9c6e` (streaming cutover) +
  `705eeefc` (the guard's floor becomes two floors). Without the second, the
  first truncated the board to ONE sport for 80 minutes. Verified on
  `098877e1`: `BOARD_OVERVIEW_READY sports=8` on 1 build against **5 consecutive
  `sports=1`** before; `OVERVIEW_STOPPED_FOR_MEMORY` 0; peak anon 1404.5 MB =
  34.3% of ceiling. **One post-fix build is a result, not yet a rate.** `[measured 08-15 00:28Z]`
- **THE KILL IS MLB GAME HYDRATION, NOT THE OVERVIEW.** At 00:41:16 the main
  worker went 1612 MB → 3079 MB in 28s with children small and payloads tagged
  `game_count: 15`. At the canonical 20:03:11 kill the container was at 28.8%
  twelve seconds prior, `stage=post_build_overview` — the overview had already
  finished. The real work is `build_cards_page_context` running HYDRATED on the
  worker. `[measured 08-15]`
- **Leave the 3000 MB floor in front of MLB alone.** It guards the wrong stage,
  but lowering it only admits more work to a process dying elsewhere.
- **THE 20:03:11Z KILL IS UNEXPLAINED** and the diagnosis that explained it is
  FALSIFIED: "eight hydrated sports cannot fit in 4 GiB" — the same 8-sport pass
  ran twice that evening at 613 MB and 804 MB. Streaming caps the transient; it
  did not explain the outlier. `[learnings.md 08-15 EXONERATED]`
- **GOAL #1 HAS TWO QUANTITIES; do not trade them off.** **PEAK** (acute) is what
  crosses the 4 GiB ceiling — a ~1873 MB excursion, cause named and now
  streamed. **FLOOR** (chronic, ~1400–2000 MB `anon`) is UNNAMED; reducing it
  buys headroom but is not what kills the process.
- **`#423` — the leak is NOT glibc arena fragmentation.** Ten readings at `anon`
  ~2031 MB: arena coverage 11.0–24.4%, `system_current` **plateaus at ~393 MB
  while `anon` climbs**. **Stop tuning the allocator.** Both flushes are already
  deployed and measured; `malloc_trim` returns 0.0–2.9 MB at guard time, so the
  residual is live objects, not free-but-unreturned. **Do not propose "add a
  flush".** `[measured 08-14 02:18Z]`
- **It is not in GC-tracked Python objects either** — `HEAP_CENSUS` at
  `container_mb 2150` counts 325,653 gc-tracked objects; millions would be
  needed. Remaining hypothesis, NOT a finding: large allocations neither
  gc-tracked nor in glibc arenas (NumPy/Monte Carlo buffers). `[measured 08-14]`
- **`tracemalloc` made production MEASURABLY WORSE and is OFF
  (`SYNDICATE_TRACEMALLOC_DIAG=0`).** With tracing on, the sampler emitted
  **zero** samples and kill cadence went 16–22 min → 3–10 min:
  `take_snapshot()` walks every live traced allocation holding the GIL and
  blocked the sampler thread. Production was also tracing at **nframe=1**, which
  names `decoder.py` — the allocator, not the caller — so even a successful dump
  would have produced a known-worthless answer. `[measured 08-15 02:1xZ]`
- **`#253`'s worker cache bound was applied to MLB ONLY.** NBA/WNBA/soccer have
  no worker variant (`= 32` unconditional) and the 32-entry limit is never
  reached, so **every context built is retained for the life of the process**.
  Magnitude NOT established — those sports are out of season or small. Do not
  quote it as MB until somebody sizes a context. `[measured 08-14 18:5xZ]`
- **The MLB cards-context cache EARNS its retention — 22.9% hit rate. Do not
  zero it.** The "mathematically zero hit rate, safe to zero" claim is retracted
  at source. `[measured 08-14]`
- **Instrument gap:** `_log_cards_context_memory` exists ONLY in MLB's cards
  module. Zero `[wnba_cards]` lines is a fact about the emitter, not the cache.

---

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
- **MLB prop skill numbers are IN-SAMPLE and now say so** (`debias_validation`).
  The bias was fit and scored on the same 2,487 player-games. The out-of-sample
  split is written into `scripts/backtest_mlb_props.py` but **HAS NEVER RUN** —
  the 08-01..08-14 window is absent from the checkout (864 `daily_summary`
  files, all 05-28..07-12). **Until it runs, the published improvement is a fit,
  not a prediction.**

---

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
- **FIXED IN CODE, NOT DEPLOYED — `1d15686b`, lane `nfl-live-edge-suppression`.**
  Guard applied at the single stamp point in `attach_nfl_game_projections`, so it
  covers h2h/totals/spreads and any future branch; ordered AFTER the projection
  is stamped so `live_aware` still ADMITS a genuinely live model (which matters
  now that user decision 5 is to build one). `pytest -k nfl` **556 passed**; new
  suite mutation-pinned 5-red/5-green exactly as predicted.
  **PRODUCTION RE-MEASURE OWED:** baseline **5** live NFL rows with
  `model_edge_pct` at 02:37Z → expect **0**. Do not call this fixed in
  production until that number is read.
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
  Second, independent blocker: the alias table misses 91% of live rows.
  Full read: `.syndicate/tier5_live_modules_2026-08-14.md`.

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
- **CLV: the opening half is recorded; THERE IS STILL NO VALID CLV NUMBER.**
  Recorder live (`2b14fbeb`), 584 bytes/record vs the evaluation chunk ledger's
  40,555; `book_prices` on 150/150 served rows. **`avg_clv_pct` is None and that
  is the honest answer.** An early `-5.215` was RETRACTED — the line was never
  checked (`home -5.0` vs a `home -1.5` close) and **25 of 25 closes PRECEDED
  their openings**. All three now refused by name (`line_mismatch`,
  `line_unverifiable`, `close_precedes_open`). `close_precedes_open` is a
  PRODUCTION condition. The joiner is library-only, no call site, NOT deployed.
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

## NFL (`#377`, `#425`, `#429`) — closed, kept because the rules generalise

- **NFL game state is REAL on every surface.** `by_state` went
  `{pregame:6, live:0}` → `{live:5, pregame:1, final:0}` with real scores and
  clocks. **The cause was ONE missing field, not five broken surfaces** —
  `_NFLDataProvider.games()` fed `build_game_chips` cards with no game state, so
  `_game_flags` returned `(False, False)` for every NFL game forever.
- **The board's live/final counts LAG by up to one artifact rebuild (~15 min).**
  Not a defect; a reading that disagrees with ESPN inside that window is expected.
- **`#377`'s constant was a DATA OUTAGE, never a model failure.**
  `load_nfl_game_projections` deduped candidates by NAME across source roots and
  read a copy generated where the nflverse pbp was absent. Now dedupes on
  resolved PATH. `projected` distinct **1 → 6**. **A constant that reproduces
  EXACTLY from an empty input is a data outage, not a weak model — use that test
  before touching any model.**
- **`#429` HRR fixed at BOTH ends.** Read-time derivation (distinct 1 → 85,
  corr 0.9267 against the sim's own probabilities vs a 0.1156 control) and the
  producer (`_inc_sum(pid, "H+R+RBI", hrr)`, both copies). Confirmed in
  production: `derived == 0` with 1008/1008 topn rows carrying a nonzero
  `hrr_mean`. **Discriminator needing no artifact access:**
  `projected_derived_from` is stamped only when the read-time path had to
  reconstruct.
- **An unscoped full-slate MLB sim is a known OOM cause** — the loop batches
  through `--only-game-pks` for that reason. Do not trigger one to force an
  artifact rebuild; read through `/api/ops/artifacts/stream`.
- **`PBP_LOADED` cannot answer "does the worker see the pbp"** — it is emitted
  through a `log()` that writes only to `--progress-log` and never reaches
  Render's collector. A 0 there is a fact about the emitter. Use `artifact_path=`.
- **`PRESEASON_WEEK_LABELS` mapping internal week 2 → "Preseason Week 1" is
  CORRECT.** Internal week 1 is the Hall of Fame game; a session nearly "fixed" it.
- **The MLB sim ledger never records completion** — 34/34 runs read
  `state=running, finished_at=null` while soccer and wnba record `ok`. "Did the
  MLB sim finish" is unanswerable from the ledger. MLB-specific, uninvestigated.
- **The NFL season-projection autorun fires at 21:00Z = 16:00 CDT.** Seven ledger
  lines once carried a UTC timestamp reported as local — a five-hour error.
  **Render logs are UTC; this ledger is CDT.**

---

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
- **The prop-producer 0.5 fix is COMMITTED AND NOT ON ANY WORKER**
  (`bd40056c` / origin `536dfcd0`). Local sizing: 6 of 4,240 probability rows
  were price-missing and every one carried a fabricated 0.5; **67 further exact-
  0.5 rows have real ±100 prices and are legitimate** — a blanket "no 0.5
  anywhere" rule would have destroyed real data. Production rate UNMEASURED.
  **Until a worker deploy carries it, production still fabricates.**

---

## ASK THE SYNDICATE

**The LLM is off by decision. The deterministic snapshot path is the product.**

- **Baseline: 23/52** (advice 4/5, entity 2/10, explain 4/6, history 1/5,
  lookup 2/8, ranking 4/10, refusal 6/8), measured 20:45Z, in
  `reports/ask_regression/post_m1_fixed_2026_08_14.json`. `answer_source:
  snapshot` 52/52 is now the EXPECTED source, not a finding.
- **K1 SHIPPED AND VERIFIED** (`bef782cb`, live 20:01:18Z): 20/52 → 23/52,
  `refusal` 3/8 → 6/8, every other class byte-identical, declined-question
  latency 10.9s → 0.19s. **A refusal gate must be tested on what it must NOT
  refuse** — two regressions were caught only by testing the answer direction.
- **M1 SHIPPED** (`b16eb1f7`) but **SUPPLEMENTS rather than REPLACES**: it adds
  `visuals.tables` while `structured_response` survives, so both pools disagree
  (23.81 vs 14.09). Successor lane `ask-headline-from-board`.
- **MLB proves the deterministic path can be genuinely good and seven sports get
  almost none of it** — mlb 4/4 questions producing evidence (14 tables, 4
  charts), ncaaf 2/2, nba 1/1, and **nfl / wnba / soccer / nhl / ncaab 0/9**,
  including with an explicit sport context. Three distinct causes: soccer and
  ncaab have **no branch at all**; NFL's matcher requires the **full** team name
  (`"Patriots vs Seahawks"` → `[]`); wnba/nhl/nba have **entity-only fetchers**
  and a ranking question names no entity. `[measured 08-14]`
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

## BOARD / INTELLIGENCE ENGINE — structural facts `[measured 08-14 21:xxZ]`

Read `.syndicate/audit_2026-08-14_board_engine_SYNTHESIS.md` first.

- Board path: **506 files / 238,071 lines**, 43 over 1,000 lines.
- **24 import cycles; 24 hub modules >10 importers** — `rank_board` (29) and
  `game_board_contract` (28). Seven of the cycles are the same shape once per
  sport and one dependency inversion fixes all seven.
- **164 of 390 modules statically unreachable** — **A SHORTLIST, NOT A DELETION
  LIST.** Thread targets and registries are not followed. The env-key twin of
  this list contains `MLB_LIVE_LENS_DIR`, whose only reader is a vendored module
  called at import scope; deleting it would have broken MLB live-lens.
- **42 sites define or convert a probability** (18 prob↔odds, 9
  `implied_probability`, 11 `confidence`, 4 `fair_probability`).
  **TIER 3a IS DONE `[measured 08-15 02:5xZ, harness d448a100]`.** 31 pure
  converters run over one grid → **10 / 5 / 4 behaviour clusters** across
  american→prob / american→decimal / prob→american. Re-run any time:
  `python scripts/probability_differential.py` (I/O-free, no deploy).
  - **On VALID prices (±100, ±150, ±10000) all 26 american→prob impls agree to
    ten decimals.** The odds maths is not wrong anywhere. **All divergence is at
    the boundary** — `0`, `None`, `""`, string price, float price.
  - **ONE LIVE MISPRICE, CONFIRMED IN PRODUCTION:** `/api/intelligence/query`
    served **1346 `fair_price` values, 24 exactly on ±4900 and none beyond**.
    Joined to their probabilities: mlb totals under `p=0.992056` published
    **−4900** (correct **−12488**), over `p=0.007944` published **+4900**
    (correct **+12488**). Cause is a `max(0.02, min(0.98, p))` clamp in
    `layer2_board`, `wnba/cards`, **and a fourth INLINE copy at
    `pipeline/intelligence_state.py:1816` that has no `def` and was never in the
    42.** A clamp is not a guard — it returns a confident wrong number where a
    refusal belongs.
  - **OWNERS, by a 5-requirement scorecard rather than cluster size:**
    `implied_probability` and `american_price`, both in
    `shared/opportunity_signals.py`, plus `live_lens_local::_american_to_decimal`
    (`opportunity_signals` has no decimal converter — why five modules grew one).
    `american_price` is the **unique** survivor of its concept.
  - **NOT a live defect:** five converters return `0.0` for price `0` (the worst
    substitution — it manufactures the largest edge on the board), but **no zero
    price was found in production** (105 rows: 0 zeros/floats/strings).
    A landmine, not a fire. One 105-row window is not proof of absence.
  - **CLAMP FIX: 1 of 3 sites done `[de0c367f, 2026-08-15]`.**
    `wnba/cards.py::_american_from_prob` now delegates to `american_price` —
    harness scores it **5/5**, was 2/5. `-k wnba`: 561 passed / 3 failed, and
    those 3 reproduce on a **control worktree without the change**, so they are
    pre-existing (live-lens worker + refresh runner).
    **The other two sites were NOT taken and that is a collision result:**
    `pipeline/intelligence_state.py:1816` is held by `memory-cutover-ship`;
    `shared/layer2_board.py` was released by `recommendation-lane-correctness`
    (now CLOSED) but immediately claimed by the new OPEN
    `model-audit-devig-and-hygiene`. Handoffs sent to both. **Not deployed.**
  - **Stale comment, live in the tree:** `layer2_board.py:1280` says it mirrors
    `wnba/cards.py::_american_from_prob` "including its 2%-98% clamp". The WNBA
    copy no longer clamps.
  - Table: `.syndicate/audit_2026-08-15_probability_differential.md`.
- **The "40 sites substituting 0.5" figure is OVER-COUNTED.**
  `(success_rate or 0.5) - 0.5` is a centered prior; `faceoff_win_pct = 0.5` is a
  legitimate sim-contract default; `0.5 * (1.0 + math.erf(...))` is the normal
  CDF. **Triage before enforcing** — indiscriminate enforcement breaks sim engines.
- The **240 bare `except: pass`** are a hygiene backlog, not a board correctness
  finding. Keep them out of the probability invariant.
- **`model_skill` and `min_value_pct` have ZERO defining functions.**
- **19 freshness / 23 market-movement / 18 prob↔odds implementations.**
- **91 of 390 modules branch on liveness; there is no single pregame/live
  boundary** — it is a cross-cutting conditional, not a seam. 16 modules are
  named `live` against **zero live edges ever published**.
- **CORRECTED 2026-08-15: "no live GAME-LINE projection exists" is true of what
  is PUBLISHED and FALSE of what is COMPUTED.** `estimate_live(LiveSituation(...))`
  runs in production on every live-lens tick, **120 sims per live game**, off the
  current inning/half/outs/bases/score/batter/pitcher, and returns `homeWinProb`,
  `awayWinProb`, projected `total` and `homeMargin`
  (`vendor/.../flask_frontend.py:16573`, wired into `_build_game_lens`:16806).
  **Proof it runs:** `LIVE_MC_BAIL` instruments every failure exit;
  live-odds-worker logged exactly **9 bails/tick across 11 consecutive ticks, all
  `status_not_live`**, against a slate of **9 Final / 5 Live** — the live games
  never bail. One exit (`away_score is None`) is uninstrumented, so this is proof
  by exhaustion with one named hole. `[measured 08-15 03:0x–03:2xZ]`
  **It dies in three places:** (1) `mlb/live_lens.py:1094` — the merge rejects the
  MC lens for exactly the live games, because the card's text-derived lens already
  satisfies `_lens_rows_have_projection_signal`; same shape as the prop sever at
  :1109, fifteen lines earlier. (2) the PUBLISHED report is the **slim** HTTP shape
  from `scripts/refresh_mlb_oddsapi.py`, which carries no `gameLens` field at all —
  so fixing (1) alone changes nothing that crosses to web. (3) `live_projection_join`
  is **entirely prop-shaped**; there is no game-line join. Served surface confirms
  the effect: 56 `gameLens` rows, lanes `first1/first3/first5` only, `source: None`,
  **0 with `modelHomeWinProb`**. **`predictions.full` IS pregame at source** —
  the vendored payload sets `"predictions": card.get("predictions")` verbatim, so
  nothing is discarding a live value there.
  **Therefore Tier 5 is publication + plumbing + a precision decision, NOT a
  modelling build.** The precision decision: 120 sims → **±4.56 pp SE** at p=0.5
  (~20× too coarse to price against Pinnacle; 2,500 sims needed for 1 pp), and with
  `seed=gamePk` fixed the error is a **state-correlated bias, not jitter that
  averages out.** Spec: `.syndicate/spec_live_game_line_projection.md` (`9067b606`).
- **`rows_live_edged` is a PROP counter and the game-line work does NOT move it.**
  Its zero is the :1109 sever + a 91% alias miss. Game lines need their own
  `rows_live_gameline_*` counters. Do not conflate them.
- **`0.1` (per-sport cooldown) is NOT a prerequisite for the LIVE product.**
  Re-derived: on deployed `ccd10349`, `live_refresh_loop.py:4587` reaches the 1800s
  cooldown only when `effective_phase == "pregame"` (:4429), and production reads
  `adaptive: true, anyLive: true, phase: "live"` on a live slate, tick 60 s. The
  121.6-min beat is the empty-slate pregame regime. `0.1` remains the right fix for
  the PREGAME board on its own merits. `[measured 08-15 03:3xZ]`
- **Web's `/mlb/api/live-lens` cannot observe the live Monte Carlo**
  (`simContextAvailable: False` on all games). Do not verify live-sim work
  through it.
- **Three of the audit brief's own "known" inputs were wrong** — `static/mlb/board.js`
  does not exist (cited twice), the devig count is not settled at 5, and
  `.claude/worktrees/` holds full repo copies that triple-count any unscoped grep.
  **Spend the first ten minutes of any audit re-verifying the inputs it tells you
  not to re-derive.**

---

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

- **Lane markers are per-session as of 2026-08-15.** `lane-guard.py` reads
  `.syndicate/.current-lane.<session_id>` first and falls back to the shared
  `.syndicate/.current-lane`. Write your slug to YOUR file; the global one is
  contended by every live session and will block edits to your own lane's
  files. Verified: global-only still blocks, per-session allows own lane,
  per-session naming a different lane still blocks.

## Web card surfaces — soccer, 2026-08-15 03:1xZ `[measured]`

- **Live web SHA is `7e334509`** (`dep-d9vtjklg1s2s73bs6ib0`, triggered
  03:15:30Z) = the previously live `a86eb4ed` **+ one commit**. It is a PINNED
  deploy, so **the next web deploy must stack on `7e334509`** or it silently
  drops the soccer card work. Same commit is on `origin/main` as `9b6a48e7`.
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
