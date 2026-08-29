# Syndicate — Work Lanes

> Lanes are exclusive by file path. Two lanes may not claim the same file.
> Max concurrent OPEN lanes: 3 (see `state.md`).
> Managed by `/lane`. Do not hand-edit while a session is running.

> **History lives in `lanes_history.md`.** This file is read at the start of
> every session, so it carries each lane's CURRENT state plus one prior block --
> **plus any block that declares file claims**, which `lane-guard` reads from
> here and nowhere else. 36 superseded blocks (2,667 lines) were moved out
> verbatim on 2026-08-18. Nothing was summarised or deleted: if a lane's earlier
> reasoning matters, it is there under the same slug.

#### ORPHAN SWEEP 2026-08-18 ~21:4xZ — 8 lanes RELEASED, 32 claims dropped, contested-file invariant CLEARED

**Measured with `lane-guard.py`'s OWN `_claims()`**, not the simplified copy in
`check_lane_invariants.py` — the two disagree, and the difference decides
outcomes. The checker lacks the guard's `_is_disclaimer` / `_claimable_prefix`
handling, so it reported 70 claims / 12 OPEN lanes where the guard actually saw
**102 claims / 17 OPEN lanes**. Read the guard when the question is "is this
file guarded"; the checker answers a different, looser question.

    claims         102 -> 70          OPEN lanes holding claims  17 -> 9
    contested       1  -> 0           (live_gameline_join.py)
    OPEN-under-Archived  15 -> 7

**RELEASED (owner session archived or role retired, verified against the full
roster INCLUDING archived — `include_archived: false` hides exactly the
evidence this question needs):**

| lane | owning session | why released |
|---|---|---|
| `syndicate-coordinator` | `syndicate-coordinator` | role RETIRED by user decision; all 3 "Deploy and Document Coordinator" sessions archived |
| `clv-without-settlement` | `lane-cleanup` | = "Orphaned lanes cleanup", archived 08-16 01:14 |
| `layer2-board-quality` | `layer2-board-quality` | all 3 "Layer 2 board audit" sessions archived; the block itself said claims "can be released on request" |
| `wnba-live-tier` | `layer1-board-coverage` | all 6 "Layer 1 board coverage audit" forks archived — **this is what cleared the contested file** |
| `wnba-phase2-migration` | `layer1-board-coverage` | same family, all archived |
| `modelled-fair-edge` | `layer1-board-coverage` | same family, all archived |
| `odds-cadence-off-the-mlb-peak` | `sim-engine-track` | all 5 "Sim engine scheduling assessment" forks archived |
| `convergence-phase5-profile-seam` | `sim-scheduling` | same family, all archived |

**NOT RELEASED, DELIBERATELY — a live or plausibly-live owner exists.** Releasing
these would un-guard files a running session is editing, which is the exact
failure the lane system exists to prevent:

    basketball-model-owner    "Basketball model deep dive"   RUNNING
    nhl-model-owner           "NHL hockey model deep dive"   RUNNING
    soccer-model-dispersion   "Soccer Session (fork)"        RUNNING
    convergence-phase7-crps   "Modeling Session (fork 2)"    active today 21:40Z
    grading-blocker-settled-zero  "Betting settlement data"  RUNNING — plausible owner by SUBJECT, not by name; the header names `alt-line-shortlist-watch`. UNRESOLVED, left guarded.
    refresh-worker-oom-recurrence "Oom band full report"     flagged running (stale 40h)
    live-edge-basis           `ask-answer-substance`         no roster match; left guarded because it now SOLELY owns `live_gameline_join.py`
    repo-coordination         unmapped                       holds the global `.current-lane`; 9 claims
    ask-sport-coverage        `ask-sport-coverage`           owner family archived, but it sits correctly under `## OPEN` and is the digest's lead lane — flagged, not swept

**THE 7 REMAINING `OPEN`-UNDER-`## Archived lanes` ARE NOT MINE TO FIX.** Every
one belongs to a live or uncertain lane above, and the remedy is to MOVE the
block above the `## Archived lanes` marker — which is editing another lane's
block. Left for each owner. The hazard is real but latent: their claims work
today and would be dropped silently by a future archive pass.

**Method note for the next sweep.** `.syndicate/.current-lane.<uuid>` marker
filenames match archived `sessionId`s exactly (6 of 13 did), so a marker whose
id resolves to an ARCHIVED session is hard evidence the lane is orphaned. The
markers for running sessions did NOT match any roster id, so the mapping proves
death, never life — do not invert it.

## OPEN
### open-bet-live-status — OPEN — opened 2026-08-26 — session syndicate-27 (749848)
- Goal: `/portfolio` is the live buying engine — merged book, editable caps,
  venue balances, venue settlement, live status on open bets. `[user 2026-08-26]`
- Files: `blueprints/intelligence.py`,
  RELEASED `[2026-08-28, session 29794bbe]`: `syndicate/templates/portfolio.html`
  `features/shared/execution_limits_settings.py`,
  `execution_guard.py`, `venue_balances.py`,
  `venue_settlement.py`, `paper_settlement.py`,
  ~~`polymarket_board_join.py`~~ **INSTRUMENTATION-ONLY CLAIM TRANSFERRED to
  `venue-refresh-decoupling` `[2026-08-28, session 3e5a9659]`** — an additive
  timing span around `join_polymarket_to_board`, NO behaviour change. Taken
  because this lane's session (`syndicate-27`) is NOT RUNNING (`list_sessions`
  shows every session `isRunning: false`) and the board build cannot attribute
  ~305s of CPU without it. **The SEMANTIC scope of this file stays yours** —
  side resolution, alias matching, the join's correctness. Take it back by
  striking this note.
  `scripts/run_live_odds_refresh_worker.py`, + tests.
  RELEASED `[2026-08-28, session d617eefd]`: `blueprints/ops.py`
  RELEASED `[2026-08-28, session d617eefd]`: `team_aliases.py`
  RELEASED `[2026-08-28, session d617eefd]`: `execution_ledger.py`
  RELEASED `[2026-08-28, session d617eefd]`: `polymarket_board_join.py` (its
  SEMANTIC scope; the instrumentation-only transfer struck above stands).
  A marker governs ONLY ITS OWN LINE -- `_claimable_prefix` cuts at the first
  marker and keeps everything before it, so a path that WRAPS onto an unmarked
  continuation line is claimed in full. That is why each path above repeats the
  word rather than sharing one lead-in. All three are now
  held in full by `venue-join-refusal-visibility`, which is fixing the
  Polymarket soccer league-bucketing gap and the ops slate reader that
  disagrees with the join about it. Taken because this lane's session is
  ARCHIVED and not running -- verified in that session, not assumed:
  `list_sessions(include_archived=true)` shows `local_f08f0df5` "Portfolio
  page consolidation", `isArchived: true`, `isRunning: false`, last activity
  2026-08-27T21:51:49Z. Take them back by striking this note.
- **STATUS 2026-08-27T21:45Z — 11 commits landed, 6 verified in production,
  5 shipped-but-unfired. Narrative and all 7 self-corrections in
  `log/2026-08-27.md`; measurements in `deploys.md`.**
- **OWED, all trigger-gated, none forceable:**
  1. `cle-laa` home row — grace expired 21:44:25Z, predict `lost / -2.76`.
  2. WNBA city codes (`31575179`) + soccer pair (`fde862aa`) need a
     refresh-worker deploy; live there is behind.
  3. paused-retry and balance-gate need an exchange pause / a cash floor.
- **DO NOT re-derive:** NCAAF projections cannot complete before **1 Sept**
  (monthly CFBD quota exhausted, `X-CallLimit-Remaining: 0`); it relaunches
  every ~38s and crashes on `429` until then. `source=artifact` IS confirmed —
  the profile loads; the RUN fails downstream.
- Claims: NONE held (web released 20:44Z, live-odds-worker expired).

### live-game-line-projection — CLOSED 2026-08-29 — **both scorer fixes EXERCISED on real finals and read correctly; closure bar fully met.** VERIFICATION A **PASS**: soccer board `finals_index` = `draws_scored_as_not_a_home_win: true`, `finals_seen: 483`, `finals_level: 458`, `finals_skipped_level: 0` — the first build where `finals_level > 0`, so the draw fix is exercised, not merely deployed. VERIFICATION B **PASS**: all three cuts `populations_matched: true` with `model_paired.n == market.n` (326/326, 1/1, 189/189); `all_records` carried 151 rows without a market prob, exactly the mismatch the pairing fix exists to expose. Pooled `games_with_outcome` = **102 across 10 dates**, clearing the 100 bar. OOM debt discharged 2026-08-27 (`6bfd37a2`). **What closes is the INSTRUMENT, not the model:** `priceable_only` model MINUS market Brier is positive on 8 of 9 scored dates (soccer 08-28 +0.08338; MLB band +0.058..+0.091) — the model TRAILS the market, and that is now measured on a correct denominator rather than hidden by a population mismatch. Nightly task `live-gameline-fixes-first-real-reading` DISABLED on closure; `live-gameline-accuracy-snapshot` left ENABLED (retirement is `#594`). Narrative in `log/2026-08-29.md`. — opened 2026-08-16

**[TAKEN 2026-08-27] THE ACCUMULATION HAS BEEN DEAD SINCE 2026-08-21 — this header's "Accumulating nightly" is FALSE.** Three readings today that agree:
- `reports/live_gameline_accuracy/history.jsonl` — **2 rows, 2 dates, mtime Aug 21 16:22**. Pooled `games_with_outcome` = **3** (08-20 games=3 diff=+0.04006; 08-21 games=0 diff=None). Target ~100. Six days produced nothing.
- Scheduled task `live-gameline-accuracy-snapshot` is **`enabled: false`**, `lastRunAt 2026-08-21T21:22Z`. It was PAUSED 08-21 16:xx CT to avoid double-firing with one-off `live-gameline-recapture-0821`, and that task's own description says it re-enables this one when it finishes — **it did not**.
- `live-gameline-recapture-0821` DID fire (`lastRunAt 2026-08-22T04:45:12Z`) but appended NO row; the history file was not modified after 16:22 on 08-21. Its step-3 snapshot either failed or never ran.

So this lane is not "underpowered and waiting" — it is **stalled at n=3 with its collector switched off**. The model-trails-market reading (+0.04006 Brier) still rests on THREE games and must not be quoted as a result.

- Goal: pooled `games_with_outcome` >= 100 in `history.jsonl`, then re-score model vs market on the `priceable_only` cut.
- Files: none — **all five claims RELEASED 2026-08-27 at session close, and deliberately NOT re-named here: any path written inside a `Files:` block is re-read as a CLAIM, released or not.** The code work is landed on origin/main (`a293bf14`, `0365f802`, both verified ancestors) and the three remaining criteria are READ-ONLY verification, so holding them would block other lanes for nothing. The paths are listed in the 2026-08-27 log if this lane ever needs another code change.
- Hypothesis: the scorer is fine; the collector is simply disabled. Re-enabling resumes accumulation at the real slate rate.
- Falsification test: re-enable and run `scripts/snapshot_live_gameline_score.py --sport mlb` by hand tonight. If it exits 2/3, or appends a row with `games_with_outcome=0` on a COMPLETED slate, the fault is in the scorer or the served payload, not the schedule.
- **RESULT `[2026-08-27]` — HYPOTHESIS HELD, SCORER EXONERATED.** Ran `scripts/snapshot_live_gameline_score.py --sport mlb` by hand (script is byte-IDENTICAL to `origin/main`, `162b3d57`). **Exit 0** — not 2 (fetch failed), not 3 (scorer disabled). It fetched, scored and appended row 3: `date=2026-08-27 games_with_outcome=0 ... ledger written=0 candidates=0 priceable=0`. The zero is the pre-slate hour, not a fault — the same shape the 08-21 16:22 early fire produced. **So the collector chain is healthy end-to-end and the ONLY broken link is the disabled cron.** Do not go looking for a scorer bug.
- **COLLECTOR RE-ENABLED `[2026-08-27, user decision]` — MEASURED, NOT ASSUMED.** `live-gameline-accuracy-snapshot` re-read after the change: `enabled: true`, `cronExpression 25 23 * * *`, `jitterSeconds 520`, **`nextRunAt 2026-08-28T04:33:40Z` = tonight 23:33 CT** — before the midnight Central slate roll, which is the whole point of the 23:25 slot. Its description now carries why it was off and the warning that an unpause delegated to another task must be VERIFIED, not assumed — that delegation is exactly what failed on 08-21. Stale one-off `live-gameline-recapture-0821` left disabled (fired 08-22T04:45Z, appended nothing).
- **`state.md` VERDICT LINE CORRECTED `[2026-08-27]`.** The row read "MLB live game-line model — **SCORED — the model LOSES to the market** on every population". That rested on n=3 games with MAE running the OTHER way, and `all_records` is unsound (model n 1526 vs market 1449 — different row sets, so "every population" was never a like-for-like claim). Now states the numbers, the n=3 bound, and that it is under-powered until pooled ~100.
- **GOAL SUBSTANTIALLY MET BY RECOVERY, NOT BY WAITING `[2026-08-27]` — pooled `games_with_outcome` 3 -> 94.** The six "lost" nights were never lost: the retained ledger holds them. `/api/ops/artifacts/export?pattern=*live_gameline_ledger*` returns **20 files / 47.7 MB** — mlb 08-20..08-26 (7 files, 1.5-8.3 MB each), wnba 7, soccer 6. And `/api/board/book-grid?sport=mlb&date=<past>` **re-scores a past date server-side**: it reads that date's ledger and builds the finals index from that date's grid. 08-21 alone returned `games_with_outcome=15, records_considered=8070`. All 7 nights backfilled into `history.jsonl`, stamped `recovered_from_ledger: true` so a reconstruction is never mistaken for a live capture.
- **THE RESULT, AND IT IS NOW POWERED.** Pooled `priceable_only` (n 25,504 BOTH sides): **model Brier 0.32266 vs market 0.25285, diff +0.06981** — the model TRAILS. 6 of 7 nights negative for the model; sole exception 08-24 (-0.08120), also the thinnest (10 games). **Pooled `last_per_game` is NOT quotable — n 94 model vs 90 market**, the same different-row-sets defect this lane already flagged in `all_records`; only `priceable_only` is population-matched. `state.md` row updated.
- **WNBA AND SOCCER SCORED FOR THE FIRST TIME `[2026-08-27]`, same recovery route.** WNBA: model BEATS market, pooled `priceable_only` 0.11116 vs 0.23620 (**-0.12504**), 18 games — **but only 101 of 12,669 records survive to the scored cut, selected on the model's own confidence, so it is not bankable.** Soccer: **UNSOUND, do not quote** — `build_finals_index` drops every `h == a` final ("baseball does not tie"), which silently excludes 17-38% of soccer matches; `games_with_outcome` == finals MINUS draws EXACTLY on 08-24 (4) and 08-26 (1). **Shared-code defect** in `syndicate/features/shared/live_gameline_score.py`, which this lane does NOT claim and did not edit; fixing it needs a modelling decision on what a draw means for a binary home-win Brier. Full numbers: `log/2026-08-27.md`.
- **DRAW HANDLING FIXED `[2026-08-27]` — commit `a293bf14`, worktree branch `session/live-game-line-projection`. COMMITTED, NOT PUSHED, NOT DEPLOYED** (no claim taken, no preflight). `build_finals_index` is now sport-aware: two EXPLICIT tables (`DRAW_IS_A_REAL_OUTCOME` = soccer/nfl/ncaaf, `LEVEL_FINAL_IS_A_BAD_ROW` = mlb/nba/wnba/ncaab/nhl), unknown sport skipped AND counted rather than given the permissive branch, `finals_index` diagnostics on the payload, and the call site passes `sport` (without which the fix is inert). **off != on proven before any correctness claim:** 6 of 13 tests fail against the pre-fix module; direct A/B over one grid = OLD 2 of 3, NEW soccer 3 of 3 (draw = False), NEW mlb 2 of 3 **identical to OLD**, so MLB/WNBA are provably unregressed. 193 passed across the gameline + book-grid suites.
- **SOCCER'S SCORE IS WITHDRAWN, NOT CORRECTED.** The pre-fix figure (model 0.31927 vs market 0.20126) came from the sport-blind path and is unsound; the fix changes what FUTURE builds compute, so soccer stays UNMEASURED until this is running on the service that serves `/api/board/book-grid`.
- **PAIRED-DIFFERENCE DEFECT ALSO FIXED `[2026-08-27]` — commit `0365f802`, LANDED AND DEPLOYED.** It was in ALL THREE cuts, not just `last_per_game`: the market list is a subset of the model list, so every difference spanned two row sets (MLB `last_per_game` n **94 vs 90**; `all_records` had been recorded as "UNSOUND" at 1526 vs 1449 and never fixed). `priceable_only` only LOOKED immune at 25,504/25,504 — a property of the data, not a guarantee — so it is paired too. Difference now uses `model_paired`; `model` kept unchanged; `rows_without_market_prob` + `populations_matched` emitted per cut. off != on: 2 new tests fail against `a293bf14`, A/B gives pre-fix **-0.095** vs fixed **-0.12**. 195 passed.
- **DEPLOYED AND VERIFIED `[2026-08-27]`.** web + refresh-worker both live on `0365f802` (refresh-worker finished 16:28:59Z, web 16:30:23Z). **Reading that proves it: the soccer board REBUILT at 16:30:58Z — after the deploy, so not a stored artifact — carrying `finals_index {sport: soccer, sport_known: true, draws_scored_as_not_a_home_win: true}`.** Both claims released, nothing forced. **NOT YET PROVEN:** no draw has actually been SCORED (`finals_seen: 0`; no sport had a final at 16:33Z) and the pairing fields are UNEXERCISED (they need a non-empty finals index). Tonight's `live-gameline-accuracy-snapshot` at 23:33 CT discharges both — **if `populations_matched` is absent or false in that row, the pairing fix reopens.** `live-odds-worker` left on `34b4d4b4`: chosen skew, it does not build the board.
- **VERIFICATION ARMED, NIGHTLY UNTIL IT PASSES `[2026-08-27]`.** `live-gameline-fixes-first-real-reading` is now a RECURRING cron `50 23 * * *` (`nextRunAt 2026-08-28T04:56:01Z`), not a one-off — because (a) needs an actual soccer DRAW and tonight's slate has only **2 matches** (measured; mlb has 7). A one-shot check would report "still unexercised" and nothing would look again, which is exactly how 08-21..08-27 was lost. **Closure bar is THREE:** (a) soccer `finals_index` with `draws_scored_as_not_a_home_win` true AND `finals_seen`>0 AND `finals_level`>0 AND `finals_skipped_level`==0; (b) `populations_matched` true and `model_paired.n`==`market.n` in every cut with data; (c) pooled `games_with_outcome` >= 100 (94 now; 7 MLB games should clear it). **"Still unexercised" is NOT a pass** — `finals_level`==0 means the slate had no draws, and the task leaves the lane OPEN naming that criterion. The task DISABLES ITSELF on close, escalates if (a) is outstanding >7 runs, and must never disable `live-gameline-accuracy-snapshot`. **Proportion:** the draw fix is ALREADY proven offline on production data (the 08-21..08-26 backfill recovered **13 real draws**, soccer 38 -> 51 scored games); tonight adds only the DEPLOYED-code reachability proof.
- Verification: `history.jsonl` gains one row per night with non-zero `games_with_outcome`, pooled total rising toward 100. **At 94 of ~100 as of 2026-08-27**; tonight's live fire is now a top-up plus the proof the cron works, not the whole sample.
- Blocked by: none. **THE `artifact_publisher.py` BLOCKER WAS DOUBLY FALSE `[2026-08-27]`** — (a) the allowlist entry it wanted has existed since `d7dbdbd2` (2026-08-20) and is content-verified on all three DEPLOYED SHAs, so there was nothing to write; (b) the claim that would have stopped anyone writing it was held by a session absent from the roster even with `include_archived=true`. Claim released `[user decision]`; file is now unheld and this lane does NOT claim it, because it needs no edit.
- **OOM DEBT DISCHARGED — EXONERATED ON MEASUREMENT `[2026-08-27]`.** Three independent legs, not a retraction. **(1)** The event is real but its date was wrong in my summary: `oomKilled` at **2026-08-16**T04:46:44.460099Z, and it sits inside a storm of **56 oomKilled** whose FIRST is 2026-08-15T00:04:47Z — **28 hours BEFORE the ledger deploy**. The deploy landed mid-incident; attribution was never supported. **(2)** Last `oomKilled` anywhere on refresh-worker is **2026-08-17T03:55:17Z** — **0 kills in the 10d13h since**, census via `render_events.py` (kills are EVENTS; `render_logs.py` cannot answer this), **fully paged, 15 pages, 1,443 events**, window stated. And the ledger DEMONSTRABLY RAN throughout: 20 ledger files / 47.7 MB exist, mlb 08-20..08-26, `MLB_LIVE_GAMELINE_LEDGER_ENABLED` absent = enabled. A clean census over a switched-off feature would prove nothing. **(3)** The mechanism cannot reach 4 GiB: the largest ledger (8,313,889 B, 10,406 records) parses to **36.3 MB peak, 4.6x amplification — 0.9% of the 4,096 MB limit**, transient and bounded per date; all three sports together ~58 MB against ~3,086 MB of headroom (worker RSS 1,010 MB read same-instant). Kill switch retained for the record and NOT needed: `MLB_LIVE_GAMELINE_LEDGER_ENABLED=0`. Full working: `log/2026-08-27.md`.
> **[SWEEP 2026-08-17 12:1x CDT] ORPHANED CONFIRMED** — session
> `live-gameline-eval` no longer exists in the roster, so "UNOWNED" is now a
> measured fact rather than a checkpoint note.
> **SINGLE NEXT ACTION:** read `live_gameline_ledger` off
> `/api/board/book-grid?sport=mlb` across TWO builds. The v2 discriminator is
> **`written` rising on rows that are NOT priceable** — `skipped_unchanged > 0`
> is NOT it and was already seen under v1.
> **[COORDINATOR 2026-08-18] THE HEADER ABOVE WAS STALE AND IS CORRECTED.**
> "v2 STILL UNEXERCISED" is **FALSE** as of 2026-08-17 02:2x–02:3xZ: the
> scheduled `live-gameline-ledger-check` measured **3,748 rows** on the first
> real slate, via `live_gameline_score.records_considered` (the ledger file's
> own row count), not via the per-build counters. Recorded in `deploys.md` and
> now on both request files in `deploy/done/`, which had been closed with no
> outcome carried back.
> **THE NEXT ACTION SURVIVES, NARROWED.** What 3,748 proves is that the recorder
> writes. It does **not** prove the v2 discriminator — `written` rising on rows
> that are **NOT priceable** — because `candidates` was 0 on every build that
> night (Sunday day slate, over before 20:30 Central fired). That still needs
> two builds **inside a live window**, and 20:30 Central is the wrong hour to
> get one on a Sunday.
> **AND IT CANNOT BE READ OFF-WORKER.** `/api/ops/artifacts/stream` returns
> **403 `path is not an allowed hot artifact`** for the ledger `.jsonl`;
> re-verified 2026-08-18 — no entry in `HOT_ARTIFACT_PATTERNS`
> (`artifact_publisher.py:35`) matches
> `*_source/data/live_gameline_ledger/live_gameline_ledger_*.jsonl`. Whoever
> takes this lane needs the artifact route, or the allowlist entry first.
> **^ THAT PARAGRAPH IS OBSOLETE `[corrected 2026-08-27]`. THE ALLOWLIST ENTRY
> EXISTS AND IS DEPLOYED.** `d7dbdbd2` (2026-08-20, "allowlist: make the
> live-gameline ledger readable off-worker (#440)") added BOTH patterns, now at
> `artifact_publisher.py:677-678`. Content-checked on all three DEPLOYED SHAs —
> web `e3568422`, refresh-worker `ad3f116c`, live-odds-worker `34b4d4b4` — 2
> matching lines each. The 2026-08-18 "no entry matches" reading was true when
> taken and went stale two days later; it then deterred work for seven days.

**STATUS AT CHECKPOINT `[15:2xZ]`.** Nothing uncommitted; everything is on
`origin/main` and content-verified there. web `ebd5f677` live 03:38:07Z,
refresh-worker `5c419007` live 04:24:33Z — and `LEDGER_VERSION = 2` is
content-verified on the CURRENTLY live `d72d670c`, which another lane deployed
at 06:01:34Z and carried it forward. Board at 15:17Z reads `index_size 0,
considered 0` — Sunday pregame, nothing live yet.

**THE SINGLE NEXT ACTION:** read `live_gameline_ledger` off
`/api/board/book-grid?sport=mlb&date=2026-08-16` during tonight's slate
(scheduled `live-gameline-ledger-check`, 20:30 Central). **The discriminator
for v2 is `written` rising on rows that are NOT priceable.**
`skipped_unchanged > 0` is NOT it — that was already observed under v1 at
04:22:51Z, which is what refuted this lane's own "never recorded a row".
Read across two builds, never one.

**ONE UNPAID DEBT:** an `oomKilled` fired at 04:46:44Z, 22 min after my
deploy added work to refresh-worker. Recorded by `refresh-worker-oom-recurrence`,
and `44ad2f9d` reports `d72d670c` as 9h clean since — **but I never measured
the ledger's RSS and I am not claiming exoneration.** Kill switch, no deploy
needed: `MLB_LIVE_GAMELINE_LEDGER_ENABLED=0` (currently ABSENT = enabled).

— original re-take header follows —
### convergence-phase7-crps — OPEN, **UNOWNED** `[session abf487e4 ARCHIVED 2026-08-20T21:1xZ]` — **FIVE FINDINGS: FOUR DEFECTS FIXED AND MEASURED, ONE NOT A DEFECT.** Ladder over the 12MB publish ceiling (pitcher strikeouts 0/12 → 18/18 rows with market lines, verified on the served payload); conditional mix never CALLED from the roster build; season-artifact pull matching NOTHING (bare globs vs fnmatch on full paths) — all five inputs now present on the worker. NOT a defect: `vs_pitcher_*` is unfed by `FORWARD_BVP_MATCHUP_MODE=off`, a modelling decision; reclassified as `disabled` so nfail means "wrong". **THE ONE THING OWED: verify on 2026-08-21** — first `sim_input_report_2026-08-21.json` via `/api/ops/artifacts/export?pattern=*sim_input_report*` must show `nfail` **10 → 0**; still 10 on a fresh `generated_at` means the wiring is INERT and this reopens. Claims: NONE held. Still open, deliberately not fixed: ephemeral `vendor/*/data/` statcast caches; BVP left OFF by design. — opened 2026-08-17
- **Goal (single testable outcome):** a proper scoring rule runs over
  CONTINUOUS projections joined to realized outcomes, with **no dependency on
  settlement, grading, or a placed bet**, and emits a non-zero per-sport sample
  with `n` attached to every statistic. This is `#440` Part 4 **Phase 7** — the
  instrument Phases 8 and 9 are read with. Nothing downstream is attributable
  until it exists.
- **Why this phase:** Phase 5 shipped (`964c89a4`) and Phase 6 touches the
  prediction-ledger write path, a seam the plan says needs an owner agreed with
  the betting-engine track. Phase 7 as scoped below touches neither.
- **Files (all NEW — collision-checked 2026-08-17 against all 14 OPEN lane
  blocks on `origin/main`; zero overlap):**
  - `syndicate/features/shared/projection_score.py` (NEW)
  - `tests/test_projection_score.py` (NEW)
  - `scripts/score_projections.py` (NEW)
- **NOT claimed, deliberately:**
  - `syndicate/features/shared/intelligence_evaluation.py` — IS claimed by an
    OPEN lane, and is the **settled-bets** path this work exists to route
    around. `model_scoring.py`'s own docstring says it "does not read the
    ledger, the board, or any artifact itself" and names its intended callers as
    a recalibration job or a backtest script. Phase 7 does not need this file.
    **Raised, not taken** — per the Phase 5 close: *"Raise ownership before
    writing code."* No live session holds the betting-engine track
    (`clv-without-settlement`, `grading-blocker-settled-zero` are OPEN but their
    sessions are stopped).
  - `syndicate/features/shared/model_scoring.py` — READ-ONLY. Pure math, 0
    non-test callers, verified on `origin/main` (not on this stale checkout).
- **Hypothesis (stated before measuring):** the plan's claim that Phase 7
  "works today on all seven sports that produce a mean and a spread" is
  **BELIEVED, NOT VERIFIED**. I predict **fewer than seven** sports publish a
  projection carrying BOTH a usable spread and an outcome join.
- **Falsification test:** if ≥7 sports carry a joinable (mean, sigma, outcome),
  the hypothesis is wrong and Phase 7 is a seven-sport instrument on day one.
  If fewer, Phase 7 **re-scopes to bias/dispersion (signed error + MAE), which
  needs no sigma** — and that re-scope gets recorded, NOT papered over by
  fabricating a sigma from a fixed constant.
- **DESIGN CONSTRAINT from `learnings.md` 2026-08-16 FORBIDDEN (letting a
  FITTED MODEL judge when a model-free measurement is available):**
  `crps_normal` imposes a **Normal** predictive distribution on what are
  actually empirical Monte Carlo draws — and for low-scoring discrete outcomes
  (runs, goals) that approximation is doing real work. Where the sim's own
  distribution is available, the **empirical-CDF CRPS is the evidence and the
  Normal closed form is the hypothesis.** Report both where both are
  computable; never report the Normal one alone as "the" CRPS.
- **Denominator discipline (CLAUDE.md standing trap + rule "a rate, not a
  count"):** print per-family date coverage AND the intersection **first**, and
  state the number of dates the result actually rests on. Do not scope the
  sample from this checkout — production has far more history (81 WNBA dates vs
  4 files locally).
- **Verification:** a scored report with, per sport × market: `n`, the
  bias/dispersion decomposition, CRPS where a spread exists, and — for any
  binary companion — the **market's** number on the identical rows. A cell below
  the sample floor reports `unmeasured`, following `projection_skill`'s existing
  first-class `unmeasured` convention rather than inventing a second one. Result
  written to `deploys.md` with the window and sample size.
- **Blocked by:** none. Deliberately not touching Phase 2/2b files
  (`live_refresh_loop.py`, `run_refresh_worker.py`) held by
  `refresh-worker-oom-recurrence`.

#### convergence-phase7-crps — SUBSTRATE MEASURED 2026-08-17 — **hypothesis CONFIRMED, and the coverage is INVERTED from what the plan assumes**

`[measured from this checkout — a LOSSY MIRROR, so every count is a LOWER BOUND
on production and the absences are NOT all established. Labelled per row.]`

**The plan's claim that Phase 7 "works today on all seven sports that produce a
mean and a spread" is NOT SUPPORTED.** Falsification test did not fire.

| sport | spread in the artifact | status |
|---|---|---|
| **MLB** | **full 1000-draw empirical PMF** | **CONFIRMED** |
| **WNBA / NBA** | `pts_sd`, `reb_sd`, `ast_sd`, `pra_sd`, … + `home_pts_sigma` / `away_pts_sigma` | **CONFIRMED** (56 wnba files, 21 dates) |
| NFL | none, across **165 files / 160 dates** | **CONFIRMED ABSENT** |
| NHL | none in the file sampled — but the sample was a 159-byte `odds_history.json` | **UNMEASURED, not absent** |
| soccer | no pregame picks/projection files in the checkout at all | **UNMEASURED, not absent** |
| NCAAF | 0 files locally; season opens 08-29 | **UNMEASURED** |
| NCAAB | no engine exists (`state.md`) | n/a |

So Phase 7 is a **2-sport instrument on day one**, not a 7-sport one. NHL and
soccer must be re-checked against PRODUCTION before anyone writes "no spread" —
this checkout is exactly the trap CLAUDE.md documents.

**AND THE MLB COVERAGE IS INVERTED — this is the finding that shapes the build:**

| MLB family | spread | markets | existing backtest? |
|---|---|---|---|
| **pitcher props** | **full PMF, 1000 draws** | so, outs, hits, earned_runs, walks, batters_faced, pitches (**7**) | **NONE** |
| **game total / margin** | **full PMF, 1000 draws**, in 4 segments (`full`/`first1`/`first3`/`first5`) | total_runs, run_margin (**2 × 4**) | **NONE** |
| hitter props | **mean only — NO distribution** | h, tb, rbi, r, hrr, 2b, 3b, sb, hr (9) | yes, `backtest_mlb_props.py`, n=2,487 |

**The one MLB family that HAS a backtest is the only one that CANNOT be
distributionally scored, and the two families carrying a full 1000-draw PMF have
never been scored at all.** That is where Phase 7 goes.

- **Denominator, stated:** ~30 pitchers/date × 7 markets over 78 local dates is
  ~16k pitcher-market observations, against "a few dozen settled bets a week".
  The plan's 10–100× claim is now MEASURED for MLB rather than asserted.
- **OUTCOME JOIN ALREADY EXISTS AND IS EXACT.**
  `processed/mlb_batter_game_log.csv` (12,185 rows) and
  `mlb_pitcher_game_log.csv` (5,089 rows), keyed `date, game_pk, player_id`.
  `feed_live` is **absent from this checkout (0 dates)** — the CLAUDE.md
  intersection trap fired exactly as written, and the game logs are the way
  around it.
- **DO NOT BUILD A NEW JOIN.** `scripts/backtest_mlb_props.py` already solves
  archive-replay-from-production, the exact `batter_id` join, per-market
  denominators, DNP exclusion and baseline comparison. It reads **means only**
  and never touches the `*_dist` sitting in the same artifact. Phase 7 is the
  distribution half of a harness that already works, not a second harness.

**CLAIM AMENDED:** this lane now also claims
`syndicate/features/shared/model_scoring.py` — **additive only**, to add
`crps_empirical` beside `crps_normal`. Re-checked 2026-08-17: the file appears
in NO OPEN lane's claim set. Justification: the repo's own
`prop_projections._dist_prob_over` docstring says *"Exact, not a normal
approximation"* for this same PMF, and the 2026-08-16 FORBIDDEN rule says a
model-free measurement outranks a fitted one. Putting the empirical form
anywhere but next to `crps_normal` would be the "fourth copy" this repo punishes.

#### convergence-phase7-crps — **PRODUCTION RUN DONE 2026-08-17. The instrument works; the mirror-only finding is PARTLY WITHDRAWN.**

- **Shipped and pushed:** `origin/main` `91be99e6` — `crps_empirical` +
  `distribution_moments` in `model_scoring`, `projection_score.py`,
  `scripts/score_projections.py`, tests. Verified after the push by blob
  (5/5 match disk, 0 carriage returns). **NO DEPLOY** — local tooling.
- **Lane goal MET:** a proper scoring rule runs over continuous projections
  joined to outcomes, with zero dependency on settlement/grading/a placed bet.
  **12k observations across two windows** where settlement has produced 0.
- **THE FALSIFICATION TEST DID NOT FIRE** on the sport hypothesis: 2 sports
  carry a spread, not 7. NHL/soccer/NCAAF remain **UNMEASURED, not absent.**
- **A SECOND, UNANTICIPATED RESULT — the two sources barely overlap in time.**
  production game logs 2026-07-19..08-16 (29 dates); mirror 05-28..07-12 (46).
  The logs are a ROLLING WINDOW production trims. "Production has more history"
  is FALSE for this family. Recorded in `deploys.md`; the scorer now reports a
  reproducibility table because of it.
- **I OVERSTATED THE FIRST RESULT.** "Every pitcher market is biased high" was
  true of the mirror window only; 3 of 7 markets flip sign on production. What
  reproduces: `outs`, `hits_allowed`, `earned_runs` all biased high, and `outs`
  overconfident, in BOTH windows. The `#428` opportunity thesis is corroborated
  through `outs`; the blanket claim is withdrawn.
- **NEXT, in order:** (1) `--source production` for WNBA/NBA — the other sport
  confirmed to carry a spread; (2) settle whether NHL/soccer carry one, from
  production, before anyone writes "no spread"; (3) trace the `outs`
  over-projection to the sim's starter-depth logic — that is the model fix and
  it is upstream of `hits_allowed` and `earned_runs`; (4) `#440` D4, an
  out-of-sample baseline split.
- **STILL NOT TAKEN:** `shared/intelligence_evaluation.py` and the prediction
  ledger write path. Phase 7 did not need either. Phase 6 still does, and still
  needs an owner agreed with the betting-engine track.

#### convergence-phase7-crps — HYPOTHESIS RECORDED BEFORE TESTING 2026-08-17 — the `outs` over-projection is a FIVE-INNING LEASH

Written before the test is run, per protocol. `[from-code]` unless marked.

**Mechanism proposed.** `ManagerProfile.starter_min_innings = 5`
(`vendor/mlb_bettingv2/sim_engine/models.py:368`), commented *"Keep starters in
longer early (useful for F5 markets) unless they blow up."* Both hook
implementations gate on it identically:

    in_leash_window = state.inning <= max(1, starter_min_innings)      # = 5
    if in_leash_window and (not blowout) and pc < (pull_starter_pitch_count + 15):
        return current      # keep the starter, unconditionally

`pull_starter_pitch_count = 95`, so inside the leash the starter is kept unless
he is at **110+ pitches** or trailing/leading by **6+**. That is a near-hard
floor of **15 outs** on every start.

**And the controls that would break the leash are DEFAULTED INERT** — the same
built-and-unreachable pattern this repo keeps finding. The V2 hook's own
comment says so: *"Defaults preserve the existing behavior (i.e., 'always keep'
within leash unless blowout)"* — `starter_leash_lev_max=1.0`,
`starter_leash_runner_max=1.0`, `starter_leash_tto_max=99.0`. Likewise
`starter_tto_quality_scaling=0.0` and `starter_quality_hook_weight=0.0` both
return a no-op at their defaults, so **starters of different true talent derive
to nearly the same hook** — which is a mechanism for the σ defect specifically.

**THIS DEFECT IS ALREADY KNOWN AND PARTIALLY MITIGATED.** `starter_short_start_prob
= 0.06` / `starter_short_start_hook_delta = -32` carries the comment *"Promoted
default: rare large negative hook shift to prevent pathological overconfidence
in starter outs-at-line."* Someone measured this before and injected a 6% short
start as a patch. **My measurement says it is still there**, so the question is
not "does the leash exist" but "is 6% enough". Do not re-report the mechanism as
a discovery.

**Why this explains BOTH measured symptoms with one cause** — the thing a
bias-only or dispersion-only story cannot do:
- **bias high** (`outs` −5.14 mirror / −2.03 production): a floor raises the mean.
- **σ too narrow** (dispersion 1.54 / 1.10 vs a calibrated 0.798): a floor
  TRUNCATES THE LEFT TAIL. Short starts are the bulk of real outs variance, and
  the sim can barely produce one.

**FALSIFIABLE TEST (decisive, needs no deploy, data already cached):** compare
**P(outs < 15)** in the sim's own `outs_dist` against the empirical rate of
sub-15-out starts in `mlb_pitcher_game_log`, on the same starts.

- **Confirms** if sim P(outs<15) is materially BELOW the actual rate.
- **REFUTES** if the two are close — then the leash is not binding in practice
  (the pitch-count term may be pulling starters before inning 5 anyway) and the
  bias lives somewhere else, most likely the per-batter pitch model. I will
  report a refutation as such rather than hunting for a second story.
- Also report the FULL simulated vs actual outs distribution, not just the tail,
  so a single-number match cannot hide a wrong shape.

#### convergence-phase7-crps — **LEASH HYPOTHESIS CONFIRMED 2026-08-17, AND MY OWN HYPOTHESIS WAS PARTLY WRONG**

**FIRST, TWO CORRECTIONS TO THE HYPOTHESIS I RECORDED AN HOUR AGO.** I called
three terms "defaulted inert". Read from the LIVE overrides file
(`vendor/mlb_bettingv2/data/tuning/manager_pitching_overrides/forward_start_2026_04_14_v1.json`),
that is wrong:
- **`starter_quality_hook_weight` IS PROMOTED TO 1.0**, not 0.0. It is live.
- **`starter_tto_quality_scaling = 0.0` is a DELIBERATE, EVIDENCE-BASED REVERT**,
  not neglect: promoted then reverted the same session because it made the
  betting hit rate on strikeouts WORSE (55.78% -> 54.65%), the very market it
  targeted. Do not "re-enable" it; that decision is documented and correct.

I read code defaults and called them production. **The overrides file is the
configuration.** Same class of error as reading a stale ledger.

**THE TEST RESULT — CONFIRMED, and the shape is the evidence, not the mean.**
`[measured, production cache, 726 starts / 29 dates]`

    sim  P(outs < 15)   0.1036
    ACTUAL rate         0.2961      <- 2.86x more short starts than the sim makes
    mean outs   sim 17.53 (5.84 IP)   actual 15.50 (5.17 IP)   diff +2.03

That +2.03 **independently reproduces the −2.031 bias** measured by the scorer
through a completely different route. Two methods, one number.

**THE SMOKING GUN IS A POINT MASS AT EXACTLY THE PARAMETER BOUNDARY:**

    outs   IP    sim %   actual %
      12  4.0     2.10      7.58     <- sim makes 1/3.6 as many
      13  4.3     1.61      4.13
      15  5.0   *26.78*    16.25     <- 27% OF ALL MASS AT EXACTLY 5.0 IP
      18  6.0    18.79     24.66     <- reality's mode is 6.0 IP; the sim's is 5.0
      23  7.7     3.08      0.14     <- and the long tail is over-produced 22x

The sim is wrong in BOTH tails: too few short starts, too many very long ones,
and a spike at the leash boundary. A bias-only measurement cannot see this.

**THE CAUSAL CHAIN, END TO END** `[from-code]`

1. `build_roster.py:2506` — every team gets `ManagerProfile()`, i.e. DEFAULTS:
   `starter_min_innings = 5`, `pull_starter_pitch_count = 95`.
2. It then tries per-team tendencies from `data/manager/manager_tendencies.json`
   (`build_roster.py:529`). **That file does not exist anywhere in the repo**
   (`Glob **/manager_tendencies*` -> no files). The loader returns `{}`,
   **caches it**, and the call site is wrapped in `try/except: pass`. So all 30
   teams silently share one hardcoded manager.
3. Its generator, `tools/datasets/build_manager_tendencies_from_feed_live.py`,
   **is referenced only from `bootstrap_prior_season_artifacts.py`** — never
   from the daily pipeline. Built, has a generator, never run.
4. `_select_pitcher_v2:1755` — inside innings 1-5 the starter is KEPT unless
   blowout, or `pc >= eff_hook + 20`, or one of three leash-break conditions
   that ARE at inert code defaults (`lev < 1.0`, `runner_pressure < 1.0`,
   `tto < 99.0` — none of these is in the promoted overrides file).

**THE STRUCTURAL POINT, and it is the part worth acting on.** All four promoted
tunings (`starter_hook_add_pitches = -13`, `stamina_excess_weight = 0.75`,
`quality_hook_weight = 1.0`, `tto_quality_scaling = 0.0`) act on **`eff_hook`,
the pitch-count hook**. Inside the leash window the hook is bypassed unless
`pc >= eff_hook + 20`. **So the leash sits ABOVE every knob that has been
tuned, and it is the one parameter nobody has touched** — it is not even
exposed as a `manager_pitching_overrides` key. A −13 pitch hook reduction can
only bite on a starter already past ~102 pitches inside five innings, which is
rare. That is why careful hook tuning has not closed the sub-15-out deficit:
**it structurally cannot.**

**CREDIT WHERE DUE — DO NOT RE-REPORT THIS AS A DISCOVERY.** The team already
measured this bias by market tier and partly fixed it (elite −0.46, mid-high
+0.73, mid +1.78, back-end +2.66 after `quality_hook_weight`; their sign
convention is `sim − actual`, opposite to the scorer's). **The over-projection
is concentrated in mid and back-end starters; elite starters are slightly
UNDER-projected.** My pooled −2.03 averages across a tier structure that flips
sign, so a single global shift would make aces worse.

**WHAT I HAVE NOT ESTABLISHED**
- **That the tendencies file is absent IN PRODUCTION.** It is absent from the
  repo and its path is code-adjacent (resolved from `__file__`), so it almost
  certainly ships absent — but I did not read the Render disk. Confirm before
  acting.
- Whether the 15-out spike survives per-tier. The tier structure is theirs,
  measured; the distribution is mine, pooled. They have not been crossed.
- Nothing was changed. **No code edit, no config edit, no deploy.**

**RECOMMENDED NEXT STEP, and the reason it is not "lower the leash":** the fix
is not a global constant change — the tier data says that would hurt elite
starters. It is (a) expose `starter_min_innings` as a `manager_pitching_overrides`
key so it can be swept like everything else, then (b) sweep it against the SAME
35-tune/11-holdout harness the other four went through, grading on betting hit
rate and not only on bias — that harness's own lesson, recorded in the
overrides file, is that statistical-bias improvements do not reliably translate
to betting-accuracy improvements.

### soccer-model-dispersion — OPEN, UNOWNED (session `soccer-sport-owner` checkpointed and released 2026-08-20 ~13:3xZ) — TESTABLE OUTCOME NOT MET; DISPERSION FALSIFIED; DISCRIMINATION CONFIRMED AS THE REMAINING DEFECT; HOME-ADVANTAGE RE-FIT TRIED AND FAILED HELD-OUT VALIDATION

- Goal (unchanged, still NOT met): `backtest_soccer_h2h_calibration.py`
  reports model Brier **<= market** on at least one non-`belgian_pro_league`
  league. Baseline: `reports/soccer_backtest/h2h_calibration_2026-08-15_limit120_n1112.json`.
- **RESULT, 2026-08-20 ~06:00Z, against the FIXED pipeline (`3ad5c8a4`) and
  every input-quality change this session made:**
  `reports/soccer_backtest/h2h_calibration_2026-08-19_fixed_pipeline_all9_s300_limit120.json`
  (session worktree, not committed) — **worse than market in 8 of 9
  leagues, `belgian_pro_league` the same single exception as 08-15,
  unchanged.** Mean model stdev(P home) rose **0.1575 -> 0.1922**, PAST
  market's own 0.1859 (model no longer under-dispersed). **This is the
  lane's own pre-registered falsification outcome** ("if the Brier gap does
  not close while stdev rises to market's, under-dispersion is NOT the
  binding constraint") — recorded as an OVERTURNED belief in
  `learnings.md`, 2026-08-20. Full numbers + reasoning in the log
  (2026-08-20 entry) and `state.md`.
- **The input-quality avenue is exhausted, not abandoned.** Every field this
  session set out to check — xG double-count, shots-weight shrink,
  clean_sheet_rate, possession_share, set_piece_goal_share,
  starters_available_share, pace_seconds_per_event, ppda, the backtest/
  production pipeline mismatch, market_features.confidence — is sourced (or
  correctly ruled out), tested, and disposed with a stated reason. None of
  it was wasted (the engine is measurably more complete and honest about
  what it doesn't know than at session start), but none of it closed the
  Brier gap either. **Do not re-open this list without new evidence that a
  specific field is systematically BIASED, not just present or absent** —
  that is the falsification test's actual implication: the spread was fixed
  and it didn't help, so the next hypothesis has to be about what the
  ratings get systematically WRONG, not another input or another knob on
  dispersion.
- Files: `scripts/backtest_soccer_h2h_calibration.py`,
  `scripts/build_soccer_artifacts.py`, `scripts/validate_soccer_vs_market.py`,
  `scripts/soccer_sim_input_checklist.py`, `syndicate/features/soccer/` (sim
  engine, adapters, ratings, `ingestion/espn_match_stats.py`),
  `tests/test_soccer_feature_loaders.py`, `tests/test_soccer_projections.py`,
  `tests/test_build_soccer_artifacts.py`, `tests/test_soccer_adapter.py`,
  `tests/test_soccer_advanced_input_reachability.py`,
  `tests/test_backtest_matches_production_rating_source.py`,
  `reports/soccer_backtest/`.
- **NOT IN THIS LANE:** `syndicate/features/shared/soccer_projections.py`,
  `syndicate/features/shared/book_margin_model.py` — board-side adapter,
  owned by lane `modelled-fair-edge`. Re-check before assuming still true.
- **BIAS DECOMPOSITION DONE, 2026-08-20 ~06:3x-13:2xZ (full detail in the
  log's two 08-20 entries):** `fit_soccer_probability_calibration.py
  --per-league` confirms DISCRIMINATION, not dispersion, is the remaining
  defect (global held-out calibration made Brier worse, fitted temperature
  ~1.0). **Per-league AUC gap is the map of where to look next:** eredivisie/
  championship/primeira_liga/belgian_pro_league/epl all rank AS WELL OR
  BETTER than market (AUC gap +0.004 to +0.044) — NOT ranking problems.
  ligue_1/la_liga are near-parity (-0.002/-0.003). **serie_a (-0.055) and
  especially bundesliga (-0.111) have real, unaddressed ranking
  deficiencies** — the most promising untried thread.
  Traced and tried `home_advantage_attack_boost` (a real calibrated
  constant, stale relative to this session's mechanism changes) for the 5
  shift-candidate leagues: bounded grid search then widened. Four
  directional findings (eredivisie: no change needed; epl: discarded,
  ran away to an implausible negative value; belgian_pro_league:
  noisy/inconclusive; primeira_liga: direction plausible, magnitude
  unresolved) plus ONE genuine bracketed optimum (championship,
  0.055 -> 0.115). **Applied championship's change to a worktree and
  HELD-OUT VALIDATED it (old vs new boost, same 151-match set, scored on
  the 125 matches NOT used to find the value) — FAILED: mean Brier delta
  +0.0121 worse, t=+1.19. REVERTED, NOT COMMITTED.** Same pattern as
  `clean_sheet_rate`: the most trustworthy-looking in-sample result still
  failed held-out. **No home-advantage adjustment shipped for any league —
  none of the other 4 should be trusted either, having looked LESS solid
  than the one that failed.**
- Next action: **bundesliga and serie_a's AUC deficiencies, not another
  home-advantage attempt.** Those two leagues' ranking gap vs market
  (-0.111 and -0.055) is real, measured, and untouched by anything this
  session tried — everything tried so far (dispersion, home-advantage
  shift) targeted the 5 leagues where ranking was already fine. Whatever
  makes bundesliga/serie_a rank worse than market is a different, unexamined
  question — likely something about how team strength is differentiated
  for those two specifically, not a global mechanism. Separately: whether
  `belgian_pro_league` being the one Brier-beating league says something
  transferable is still untried. **Any future single-parameter fit MUST
  clear a held-out validation (different matches than the fit) before
  being applied — this session demonstrated why, not just asserted it.**
- Blocked by: none.

**INHERITED, DO NOT RE-DERIVE** (full detail moved to `.syndicate/lanes_history.md`,
archived 2026-08-19 — read there for the falsification-test design and the
Monte-Carlo-noise-floor cheap-falsifier note, both still valid):
- A leak-free backtest ALREADY EXISTS (`backtest_soccer_h2h_calibration.py`,
  `5a94b134`) — the retired-for-leakage `*_backtest_*.csv` artifacts are a
  DIFFERENT, unrelated thing.
- MLS cannot be backtested from its current source (undated season aggregates).
- Do not publish `model_edge_pct` on a partial win — publishing is a separate
  decision from closing the Brier gap.

#### convergence-phase7-crps — BUILT 2026-08-18, **VALIDATION IN FLIGHT** — per-PA common random numbers

`GameConfig.crn_pa_seeding`, **default OFF**. Re-seeds the game RNG at every
plate appearance from `(rng_seed, batting team_id, that team's PA index)`.

**The problem it targets, measured:** the market harness had a seed-to-seed
noise floor of **0.00326 Brier against effects of ~0.00138**. Cause: one RNG
stream per game, so the first pitch whose outcome differs shifts every
subsequent draw and the two arms are running different games from that point on.
**Sharing a seed across arms LOOKS like common random numbers and is not**, when
control flow depends on the RNG.

**The design decision:** a team's Nth plate appearance is the same logical event
in both arms *by definition of a batting order*, so seeding on it re-synchronises
after any divergence. **Inning is deliberately NOT in the key** — it shifts when
scoring differs, which would break the alignment the flag exists to create.

**Seeds pass through a splitmix64 avalanche, not a plain multiply.** Consecutive
PA indices differ by 1 and Mersenne Twister seeds differing in low bits give
correlated early output — the naive version introduces exactly the correlation
it is meant to remove.

**DEFAULT OFF and it must be ON FOR BOTH ARMS of a comparison.** It changes every
simulated result, so it is a measurement instrument, never a silent change to
what production simulates.

**CLAIMED, NOT YET MEASURED.** `scripts/validate_crn_pa_seeding.py` is running
and checks, in order: (1) determinism preserved with the flag off — a variance
fix that broke reproducibility would be worse than the problem; (2) reachability,
on != off; (3) **the only claim that matters — the spread of `(mix ON - mix OFF)`
across seeds, CRN off vs on.** Each ARM's own variance is irrelevant and will not
improve; reporting it would look like a result and mean nothing. **If the ratio
comes back ~1.0 the flag is not worth using and this entry says so.**


### repo-coordination — OPEN — **POSSIBLY ORPHANED, unconfirmed `[flagged 2026-08-19]`: no currently-running session found narrating its own work under `repo-coordination` — every hit is a session reading the shared `lanes.md` digest or its own guard output (one session's transcript shows `your lane: repo-coordination` printed to a session that is clearly NOT this lane — `Modeling Session (fork 2)` / `abf487e4…` — the exact bare-file misattribution bug fixed earlier 2026-08-19, not evidence of real ownership). No `.current-lane.<session_id>` marker exists for it. Not closed and not force-reassigned on this evidence alone — a live session claiming this lane should confirm by opening it fresh (which now also backfills its own per-session marker).** deployment, assignment and documentation. NOT any sport, model or engine. — opened 2026-08-18 — session: repo-coordination

- **Goal (single testable outcome):** the machinery that decides WHO deploys,
  WHO owns which files, and WHERE a fact is written stays coherent and
  self-checking, with every rule enforced by something that cannot be archived
  or forgotten. Testable: `lane_identity_check.py`, `todo_id_reconcile.py` and
  `state_key_check.py` all exit 0, CI enforces all three, and every deploy goes
  through claim + preflight.
- **Scope, stated as a boundary because this session already crossed it twice:**
  hooks, guards, the deploy path, the four ledgers, `CLAUDE.md`, and the
  session/worktree protocol. **NOT** sport features, sim engines, model inputs,
  backtests, or measuring any model's coverage — including "just reading a
  board to see if a model is fed". If a task's outcome is a statement about a
  MODEL, it belongs to that sport's lane.
- **Files:**
  - `.claude/hooks/` (deploy-guard, lane-guard, commit-guard, session-start)
  - `scripts/session_worktree.py`
  - `scripts/lane_identity_check.py`
  - `scripts/todo_id_reconcile.py`
  - `scripts/state_key_check.py`
  - `scripts/deploy_claim.py`
  - `scripts/deploy_preflight.py`
  - `docs/ai_context/session_isolation_protocol.md`
  - RELEASED 2026-08-25 by `exchange-markets-api-integration` (narrowly, the
    `pytest-baseline` job's own step only -- see that lane's block for the
    full note): the CI workflow file
- **NOT claimed, deliberately:** every `syndicate/features/**` path, every
  `scripts/generate_*` and `scripts/backtest_*` entrypoint, and every per-sport
  checklist or engine reference. Those belong to sport lanes.
- **Shipped under this remit today** (all on `origin/main`, all measured):
  deploy-guard gates on claim + SHA-bound CLEAR preflight instead of a session
  id; `OFF_MAIN` (exit 4) so deploys compose; coordinator role retired; three
  ledger checkers built, wired into CI and the session digest; lane-guard's
  claim parsing fixed (52 -> 80 file claims); `state.md` keyed and its two
  stacked subjects collapsed; per-session worktrees adopted.
- **Known open, in remit:**
  - **SHIPPED `58c63b62` on `origin/main` `[2026-08-20]`** — the hook guards
    were resolving paths against `CLAUDE_PROJECT_DIR`, i.e. the wrong
    REPOSITORY once sessions moved to worktrees. `ledger-commit-guard.py`
    blocked a clean worktree over the primary tree's lane duplicates and
    printed `trim_lane_blocks.py --apply`, a remedy that would have
    rewritten two OTHER lanes' blocks; `ledger-append-guard.py` was fully
    INERT in every worktree. Both fixed + measured, shared resolver in
    `commit_context.py`, 33 new tests. `commit-guard.py` refactor proven a
    behavioural no-op. Cross-lane edit taken under explicit user instruction
    while this lane was flagged possibly orphaned.
    Detail: `.syndicate/log/2026-08-20.md`.
  - **CLOSED — all four guards fixed, all four suites ENFORCED in CI**
    `[2026-08-20]`: `f73d163e` fixed `ledger-postwrite-check.py` (blind to
    worktree Bash writes, and it blamed whichever session observed the change);
    `86ec6b42` wired all four suites in, **verified green on the Linux runner**
    (run 32415246596 — 16/16, 17/17, 16/16, 10/10). Enforced rather than
    tolerated because each suite was mutation-tested first. `lane-guard` is
    EXONERATED: same mangled relpath, absorbed by exact-or-suffix matching — do
    NOT "fix" its `root`, the PRIMARY tree is correct for it.
  - `land` reports the ledger checkers rather than gating on them.
  - The new deploy predicate has never gated a real deploy; `OFF_MAIN` has never
    fired in anger; no preflight receipt consumed live. First real deploy tests it.
  - ~100 stale worktrees under `C:/tmp` need a human pass before reaping.
  - `deploys.md` (834 KB) and `lanes_closed.md` (838 KB) have no size discipline
    and no checker.
- **Blocked by:** none.


### wnba-live-odds-capture-gap — OPEN, NARROWED — **THE AUTORUN FIRED FOR REAL `[2026-08-21T00:07:24.782Z / 19:07 CT]`, observed by a third party (scheduled task `verify-wnba-live-scale-481`, session `1f76348c`) on IND@DAL. The "never fired" blocker is DISCHARGED. What replaces it: the autorun launches every ~4.3 min and refreshes the LIVE-LENS path, but `book_quotes/<date>.jsonl` advanced ONCE (00:07:49Z) and was still byte-identical 26 min later. The lane's literal testable outcome PASSES, but passing cannot be attributed to the autorun — see FINDINGS.** **ROOT CAUSE FOUND `[00:45Z]`: the autorun is fine; `refresh_wnba_oddsapi_props.py`'s REUSE GUARD sits upstream of it and returns `reused_artifact_bundle` every tick, so the child that appends `book_quotes` never spawns. The guard's staleness bound is the PREGAME sweep interval (2h) and its reuse key carries no phase term, so a 240s live autorun cannot outrun it. THE FIX BELONGS IN THE GUARD, NOT THE AUTORUN.** — opened 2026-08-20 — session 2bffd747-efb5-45d8-b4f3-ae067b645eb7
- Goal: WNBA's in-game (live-phase) odds capture actually refreshes once a
  game goes live, instead of freezing at its last pregame quote.
  **Testable outcome:** for a WNBA game currently in live state, re-pull
  `wnba_source/tracking/book_quotes/<date>.jsonl` and confirm at least one
  market's `captured_at` is newer than the game's own kickoff time.
- Files:
  - **CLAIM RELEASED 2026-08-20 to `wnba-live-reuse-bound`** (session
    `1f76348c`), narrowly and by this lane's own instruction below. The defect
    location IS now confirmed and it is not in this file — only `_build_wnba_steps`
    needs one line to pass the phase to the child. This lane is UNOWNED (session
    `2bffd747` absent from the roster including archived), so holding a
    read-only reference here would block the fix this lane exists to enable.
    Path deliberately NOT written as a path on this line, because
    `check_lane_invariants.py` parses any backticked path inside a `- Files:`
    block as a live CLAIM and would keep reporting the file as contested.
    Formerly: the WNBA step builder, read-only reference, "do not edit without
    re-claiming narrowly, same convention the soccer lane used for this same
    file" — which is exactly what was done.
  - Not claimed, read-only reference: `scripts/run_live_odds_refresh_worker.py`
    — likely relevant (soccer's autorun equivalent lived here), not yet
    confirmed WNBA has an analogous live-phase launcher at all.
- Hypothesis: WNBA's live-phase odds fetch either (a) does not exist as a
  distinct step from the soccer-style `phase=live` odds capture, or (b)
  exists but is failing/never firing, structurally similar to `#343`
  (soccer's bulk-endpoint 422) but a different mechanism, since WNBA's
  fetch script and market list have never been touched by that fix.
- **Already established, measured 2026-08-20 ~02:18Z (do not re-derive):**
  Minnesota Lynx @ Golden State Valkyries (kickoff 2026-08-20T02:10:00Z):
  every h2h/spreads/totals/prop market for this matchup shares ONE
  `captured_at` (`2026-08-20T00:31:28Z`) — 99 minutes BEFORE kickoff, zero
  refreshes since, 107+ min stale at check time. Distinct from the sim-side
  gap already documented in `per_sport_ingest.wnba.enrichment.
  live_projections` (`reason: "no live re-sim wired for wnba"`) — that is
  about projections, this is about the underlying MARKET QUOTE, which a
  pure book-price EV play does not need a sim for at all.
- Falsification test: find a WNBA-specific `phase=live` odds-fetch step
  that DID run recently for this game (any log evidence of an attempt,
  success or failure) — if one exists and simply failed silently, the
  hypothesis narrows to (b); if none exists at all in the step-builder,
  hypothesis (a) is confirmed and this is a missing feature, not a bug.
  **RESOLVED: hypothesis (b), but not `#343`-shaped — see below.**
- **ROOT CAUSE CONFIRMED 2026-08-20 02:37Z, tested directly, not inferred.**
  1. `_build_wnba_steps` (`scripts/refresh_odds_sources.py:828`) DOES fire
     for `phases=("pregame","live")` — hypothesis (a) is dead.
  2. Replicated the exact discovery + per-event `/odds` call this fetcher
     makes (`fetch_basketball_oddsapi_props_local.py`, event_id
     `09563bab4edf9cf2073ee946ad95d61b`, Lynx@Valkyries) directly against
     production OddsAPI: **HTTP 200, 8 bookmakers, every market present.**
     This is NOT `#343` — the market list is fine (this fetcher already
     uses the safe discover-then-intersect pattern, unlike soccer's old
     naive bulk request; its own code comment even cites `#343` by name as
     the reason it was built this way).
  3. Confirmed genuinely stale via the unambiguous `event_id` join (not a
     team-name mismatch in the diagnostic): 6,981 rows for this event, all
     frozen at `captured_at=2026-08-20T00:31:28Z`, 2+ hours stale.
  4. **The autonomous sweep's own outcome log admits the failure directly:**
     `[live_refresh_loop] ODDS_SWEEP_OUTCOME sport=wnba wrote=False
     exists=True since_launch_s=193 sidecar_age_s=7449` (02:35:49Z) — no
     inference needed, the sweep says it did not write.
  5. **Fired a manually SCOPED trigger** (`POST /api/ops/odds-refresh/run`,
     `phase=live, sports=wnba` ONLY — no mlb, no soccer) and it succeeded
     immediately: `PUBLISH_OK path=wnba_source/tracking/book_quotes/
     2026-08-19.jsonl bytes=6983198` at 02:37:07Z. Re-pulled the shard:
     7,851 rows (up from 6,981), latest `captured_at` **1.7 minutes old**.
     Verification step (below) is DONE for this specific game.
  - **Mechanism:** `live_refresh_loop.py`'s sweep calls
    `launch_refresh_run(sports=launch_sports, ...)` ONCE per tick with ALL
    active sports combined (`sports=mlb,wnba,soccer`) — one subprocess, one
    `refresh_odds_sources.py --sports mlb,wnba,soccer` invocation. Step
    order follows `REGISTRY`'s insertion order: `mlb` (heaviest, most
    complex live-phase work) runs BEFORE `wnba`. Under load, MLB's own
    live-phase cost appears to consume the sweep's effective time/resource
    budget before WNBA's step gets a turn — same general SHAPE as soccer's
    pre-`#433` problem (a heavy sport starving a lighter one sharing one
    combined run), but the mechanism is scheduling/ordering within ONE
    process, not a market-list API error. NOT yet proven which specific
    resource is exhausted (wall-clock step budget vs memory vs something
    else) — that is the next open question, not this session's finding.
- **FIX IMPLEMENTED 2026-08-20 ~03:0xZ, deployed and flag-flipped 13:07-13:31Z.**
  `_launch_autorun_wnba_live_refresh()` (`scripts/run_live_odds_refresh_worker.py`) mirrors the
  existing pregame autorun's shape: its own 240s cadence, its own EXPLICIT refresh lane
  (`live-odds-worker-wnba-live`, so it can never contend with the combined sweep's lane), `mode=
  "fast"` (skips the SmartSim prediction/edges/export pipeline that `test_wnba_pregame_autorun.py`'s
  own comment warns would OOM this 2GB service if run every few minutes), gated on
  `_wnba_has_live_game` specifically — not merely "WNBA active today". Default OFF, same
  convention as every other autorun in this file. 22 new tests
  (`tests/test_wnba_live_refresh_autorun.py`), 73/73 passing across every file touching the module.
- **Deploy history, both scoped off the LIVE SHA (origin/main had drifted 47+ commits ahead by
  deploy time — see `deploys.md` for the full "exactly one substantive change" reasoning):**
  1. `170505ec` landed on `main`; `b5cf8ac2` (scoped, parent `d520d93d`) deployed 13:15:46Z, code
     default-OFF, verified genuinely inert (zero `WNBA_LIVE_AUTORUN` log lines post-deploy).
  2. `SYNDICATE_ENABLE_WNBA_LIVE_REFRESH_AUTORUN=1` set on the service; `cb322dd1` (comment-only,
     produced specifically because `deploy_preflight.py` has no override for an intentional
     same-commit redeploy — a real tooling gap worth fixing separately) deployed 13:31:11Z. Content
     landed on `main` too (`2908373d`), not orphaned on the deploy branch.
- **verify: FIRING CONFIRMED, WRITE-THROUGH NOT.** Measured 2026-08-21 00:07–00:34Z by session
  `1f76348c` (not this lane — findings handed over, lane NOT otherwise touched):
  - `WNBA_LIVE_AUTORUN_LAUNCHED` first at **00:07:24.782Z**, ~7.4 min after IND@DAL's 00:00Z tip,
    then 00:12:15 / 00:16:48 / 00:21:13 / 00:25:35 / 00:30:06 — a clean ~4.3 min cadence matching
    the 240s design. Zero `WNBA_LIVE_AUTORUN_ERROR`, zero `_SKIPPED`. `_wnba_has_live_game` is
    therefore confirmed against a REAL live game, not just a monkeypatched return.
  - **Testable outcome PASSES but does not prove the mechanism.**
    `wnba_source/tracking/book_quotes/2026-08-20.jsonl`: 28,743 rows, latest `captured_at`
    **00:07:49.815Z** (2,437-row batch, all three events) — newer than kickoff, as required.
    BUT prior batches ran 14:33 / 15:57 / 17:58 / 20:40 / 22:40 / 00:07, i.e. 84–162 min apart, so
    a ~1.5–2.5h cadence produces a 00:07-ish batch with no autorun at all. The 25s gap between the
    00:07:24 launch and the 00:07:49 capture is suggestive, NOT probative. **Do not close on this.**
  - **The shard then stopped advancing.** Re-pulled 00:33:46Z: byte-identical, still 28,743 rows,
    still latest 00:07:49Z — 26 min stale across five further launches. Not a publish lag: every
    tick logs `WNBA_LIVE_AUTORUN_PREV … launched=ok runStamp=None artifactsDir=None`, and the state
    sidecar reports `PUBLISH_SKIPPED_UNCHANGED checksum=951d27e5fb28`, so the worker's own state did
    not change either.
  - **What the autorun demonstrably DOES refresh: the live-lens path.**
    `PERIOD_MARKET_DISCOVERY_DIAG matchup=DAL@IND discover_status=200` with live_lens
    projections/signals republishing every cycle. So the fetch works and the credentials/market list
    are fine — it simply is not landing in `book_quotes`.
- **OWNER OF THE APPEND: FOUND, and the combined-sweep suspicion above was WRONG.** Traced
  2026-08-21 00:45Z. `append_book_quotes` (`odds_book_quotes.py:328`) ← `_append_basketball_book_quotes`
  (`fetch_basketball_oddsapi_props_local.py:330`, the CHILD) ← `refresh_wnba_oddsapi_props.py` (the
  PARENT) ← the single step `_build_wnba_steps` builds. The autorun's own chain, not the combined
  sweep's — so MLB starvation is exonerated for THIS symptom.
- **WHY IT NEVER WRITES: the reuse guard, upstream of everything `mode="fast"` controls.**
  `/api/ops/wnba/refresh-decision` names the branch outright — `decision="reused_artifact_bundle"`,
  `recorded_at` advancing every tick (00:45:30Z, 00:46:36Z, same `input_hash`), so the parent runs
  each tick and `_existing_artifact_bundle_state` returns a cached bundle each time; the child that
  fetches never spawns. This is `#344`/`#383`'s documented fixpoint recurring.
- **THE ACTUAL DEFECT, and it is not in the autorun.** Reuse IS bounded by
  `_reuse_max_age_seconds("wnba")` — but that bound is the PREGAME sweep interval (2h default, no
  override in `render.yaml`), and the reuse `step_key` is
  `(artifact_root, date, do_edges, do_export)` with **no phase and no time component**, so a live
  tick is indistinguishable from a pregame one. **A 240s live autorun is therefore gated by a 2h
  pregame-derived staleness bound and cannot move this artifact by design.** Predicts a ~2h quote
  cadence; observed batch spacing 84–162 min. The comment at
  `run_live_odds_refresh_worker.py:343` — the snapshot fetch "runs UNCONDITIONALLY" under
  `mode="fast"` — is true of MODE and false of the REUSE GUARD that sits above it. That gap is the bug.
- **Confirmed NOT "prices were stable".** `append_book_quotes` is a CHANGE log (unmoved price writes
  no row), so a flat `.jsonl` proves nothing on its own — but its state file carries a last-seen slot
  written whenever anything is OBSERVED, precisely to separate stable from stopped-looking. All
  5,489 keys read last-seen `00:07:49.815Z`, 36+ min cold. Nothing was observed.
- Next concrete step: fix shape is a live-phase-aware reuse bound — give the guard a phase/live-game
  term, or a separate max-age when a game is in progress. Do NOT touch the autorun; it works.
  Re-verify with the last-seen slot and `refresh-decision`, not with `.jsonl` row counts.
  UNVERIFIED: the 2h figure is the code default with no `render.yaml` override — live service
  env-vars were NOT read, so a service-level override is still possible.
- **Adjacent risk, NOT this lane's, surfaced because it was measured in the same window:**
  live-odds-worker hit **97.2% of its 2GB cap — 43.6MB headroom** at 00:17:03Z
  (`memory_anon_mb 992`, `container_memory_mb 2004`) with three live games, during
  `WNBA_SCOPED_SMART_SIM_RESIM_TRIGGERED matchups=GSV-MIN`. Unowned as far as this lane knows.
- Blocked by: none.

### soccer-board-mlb-parity — OPEN, UNOWNED (session `f98be73b` checkpointed 2026-08-22 23:2xZ) — **TWO THINGS DEPLOYED TONIGHT. (1) `#518` FOTMOB MOMENTUM — live-odds-worker `94a16efe`, live 22:18:35Z: the event-signal sweep (momentum/xG/shot pressure) was killed by a null control, but a pooled 60-120s model IS real and DIRECTIONAL (which team scores next, dAUC +0.071), driven by FotMob's own momentum series; production's ESPN proxy carries NO signal at any half-life — retired. 5,552-match dataset committed. (2) COMPACT CARD REDESIGN — web `a1dc1e9a`, live 23:08:55Z, VERIFIED ON PRODUCTION HTML: pregame cards show sim-projected totals + BTTS/goals/corners/top-score; final cards RECONCILE those same facts against the real result (19 hit/62 miss on today's slate, spot-checked by hand).** OWED: (a) the FotMob join has never resolved a real fixture — MLS kickoff 2026-08-23T01:30Z is the first test; (b) the live-odds market-pricing pilot sits at 1.46 SE, n=106, needs ~2 more match-days. Full detail: `state.md [soccer-live-momentum]` + `[soccer-compact-cards]`, `log/2026-08-22.md` 22:0x-23:1xZ entries. — opened 2026-08-20 — session f98be73b-b686-42b7-bdf9-248ab97f65b7
- Goal (unchanged): `/soccer` serves a date-scoped board whose cards carry the
  same information classes MLB's do, and whose live tier updates during a match.
- **OWED, and not claimed as done:**
  1. **Verify the FotMob join against a real fixture** — MLS kickoff 2026-08-23T01:30Z.
  2. **gate 3 has never been observed PRICING a live edge** — only withholding
     by name. Needs a live soccer market quoted two-sided.
  3. **The live totals lens is unproven**: harness ran n=1 with NEUTRAL ratings.
     Multi-match aggregation is the next action.
  4. **Two fair bases on one market**: home rows use `soccer_projections`'
     de-vig, away/draw use layer2's `quote.fair_probability`. Residual median
     0.47 / max 1.38 pts.
  5. Inherited and still open: five of six ESPN-join collision pairs (incl.
     Manchester City ↔ Manchester United, 0.812) fixed BY CONSTRUCTION and never
     rebuilt in production; only la_liga was.
  6. The live-odds market-pricing pilot (does the book already price momentum?)
     sits at 1.46 SE, n=106 — needs ~2 more match-days of capture to resolve.
- Files: `syndicate/features/shared/{board_enrichment,soccer_live_gameline_source,soccer_projections,layer2_board,publication_adapter,live_lens_loop}.py`,
  `syndicate/features/soccer/{features/live_lens.py,features/lineups.py,ingestion/fotmob_*.py}`,
  **the soccer cards builder was REMOVED FROM THE BRACE ABOVE
  `[2026-08-28, session 3e5a9659]`** —
  claim transferred to `soccer-overview-cost` for INSTRUMENTATION ONLY (two
  sub-marks inside `_build_cards_page_context_uncached`, no behaviour change,
  nothing near the FotMob/live-lens work this lane owns). Taken because this
  lane is UNOWNED — session `f98be73b` checkpointed 2026-08-22 and does not
  appear in `list_sessions` at all. REMOVED rather than struck through, and
  removed from INSIDE the brace: `check_lane_invariants` parses paths
  positionally and a brace expansion is a claim per member. To reclaim, put
  that filename back inside the brace.
  **AND THE FILENAME ITSELF HAD TO GO, not just its position in the brace**
  `[2026-08-29, session 6dc988f8, lane ncaaf-live-lens-state]` — this note
  said the claim was removed while still spelling the bare filename twice
  inside the `- Files:` block, so `_claims()` kept yielding it. `lane-guard`
  matches on path SUFFIX (`rel.endswith("/" + f)`, line 420), and a bare
  filename has no directory to disambiguate it, so this UNOWNED soccer lane
  was claiming **every sport's cards builder** — mlb, nba, nfl, ncaaf, wnba.
  It blocked an NCAAF edit on 2026-08-29 while the first game of the season
  was in progress. `check_lane_invariants` did NOT catch it: it checks that
  each claim has exactly one holder, and this claim did. Same basename
  collision `state.md` records for `live_lens` across eight sports. **A
  disclaimer next to a path does not unclaim it — only deleting the path
  text does.**
  `syndicate/templates/shared/_scoreboard_strip_soccer.html`, `syndicate/static/shared/dense_cards.css`,
  `scripts/{build_soccer_artifacts,backtest_soccer_live_totals,poll_soccer_live_state,soccer_*}.py`,
  `tests/test_soccer_*`, `tests/test_fotmob_*`.
- **NOT IN THIS LANE:** `syndicate/features/soccer/sim_engine/`, adapters,
  ratings — held by `soccer-model-dispersion`.
- Blocked by: none.

### mlb-native-ladders-producer — OPEN, UNOWNED (session 822e1e5a archived 2026-08-20 ~20:4xZ) — **MAKE `ladders_build.py` THE PRODUCER AND DELETE THE VENDOR LADDERS STAGE. Stage 1 of 20 in the MLB vendor exit (`state.md [mlb-vendor-exit-audit]`; `todo.md #493`). ALL CODE SHIPPED AND LIVE — fix `a54dffa3` (18:27:40Z), force knob + one-shot guard live in `a0396411` (20:28:43Z, verified by CONTENT), `SYNDICATE_MLB_LADDERS_FORCE_DATE=2026-08-20` SET. THE PRODUCTION VERIFICATION IS UNDISCHARGED AND IS A ONE-CURL READ: last status `skipped_fresh` at 20:11:24Z PREDATES the deploy, so nothing had run with the knob yet — pending, NOT failed.** — opened 2026-08-20
- **Goal (single testable outcome):** `daily_ladders_<date>.json` produced by
  `syndicate.features.mlb.ladders_build` on the NORMAL path — `generatedBy`
  stamped on the SERVED artifact — with the vendor ladders stage removed from
  `daily_update.py`, and both consumers (top-props board, compact-card pregame
  chips) rendering unchanged.
- **Files:** `syndicate/features/mlb/ladders_build.py`, `tests/test_mlb_ladders_build.py`, `scripts/run_mlb_daily_sim_job.py`, `tests/test_run_mlb_daily_sim_job.py`.
- **INHERITED OBLIGATION (item 1, from `mlb-pregame-ladder-schema`):** `a54dffa3`
  is live and UNVERIFIED in production. Discharge by arming
  `SYNDICATE_MLB_LADDERS_FORCE_DATE=<central date>` on refresh-worker and reading
  `generatedBy == syndicate.features.mlb.ladders_build` PLUS populated
  `ladder[]`/`gamePk` on 18/18 pitcher rows. **Chips on the board prove NOTHING**
  — the vendor writer renders them either way. Knob shipped (`c99b259c`); env var
  NOT set (Claude's PUT is classifier-blocked; needs a dashboard edit) and the
  deploy is parked on it.
- **Gap to parity, measured 2026-08-20:** 4 presenter fields (`lineupOrder`,
  `paMean`, `matchupReasons`, `matchupSummary`) read by `ladders_common.py`, and
  hitter ladders 0/234 vs vendor 234/234. The other 14 vendor-only fields are NOT
  blockers: `modeProb`/`modeCount`/`overLineCount` have 0 consumers;
  `marketLinesByStat`/`pregameMarketLine` are read only as FALLBACKS behind
  `marketLine`, which native already emits; the rest are cosmetic.
- **Hitter ladders: decide, do not default.** No consumer reads them, and
  `learnings.md` 2026-08-20 records this artifact silently exceeding
  `_PUBLISH_MAX_BYTES`. Native+pitcher ladders is 635,001 B vs the vendor's
  9,518,280 B, so 234 hitter ladders is the biggest size lever here. Do not add
  them without a consumer.
- **Do not delete the vendor stage until native is proven on the normal path.**
  The board currently runs on the vendor artifact; removing its writer first
  converts a degraded path into an outage.


### layer2-rail-duplicate-nfl-cards - **CLOSED 2026-08-27T19:5xZ.** `#583` + `#589` fixed and verified in production (web `b0ef00b8`, `78a95c7f`); the behavioural read owed since 08-20 was OBSERVED LIVE on the La Liga slate, not replayed. No claims, nothing owed. Body moved VERBATIM to `lanes_history.md` 2026-08-27; evidence in `deploys.md` + `log/2026-08-27.md`.
### wnba-halftime-elapsed — **OPEN, UNOWNED** `[session 1f76348c ARCHIVED 2026-08-21 ~16:1xZ]` — **ONE READING OWED** — fix is LIVE on web (`2b9040df`, content-verified) and on the workers (`3b41696d` is an ancestor of refresh-worker's SHA). Unit-verified both directions: 3 break tests FAIL pre-fix, 2 narrowness tests PASS in both states. **THE BREAK BEHAVIOUR ITSELF IS UNOBSERVED IN PRODUCTION** — a 20-minute watcher caught no blank-clock state, and the one suggestive reading (a board row at 'End of 1st' keeping a live lane at model 0.2155 vs its 0.27 pregame baseline) was INDIRECT, via the board. Next WNBA break discharges it. — opened 2026-08-20 — session 1f76348c-062d-4075-a54b-a8b0eadabb2b
- Goal: the live win/cover probability must keep using the live margin during a
  BETWEEN-PERIODS break, instead of silently reverting to the pregame number.
  **Testable outcome:** with period=2 and a blank clock, a +12 home margin and a
  -12 home margin produce DIFFERENT probabilities (today both return the
  pregame anchor exactly).
- Files:
  - `syndicate/features/wnba/cards.py` — `_wnba_elapsed_minutes` and the
    `source`/`markets` fallback that keys off its None.
- Hypothesis: n/a — measured, not inferred. `_wnba_elapsed_minutes(2, "")`
  returns None because the clock fails to parse; `_wnba_live_margin_win_prob`
  then short-circuits to `pregame_p_home_win`, and `source` falls back to
  `pregame` so `markets` is emptied for the whole break. Confirmed by driving
  the real shipped functions: margin +12 and -12 both return 0.4500 against a
  0.45 anchor.
- Falsification test: if a blank clock also occurs at a period's START, then
  "blank clock = period complete" overstates elapsed by a full period and this
  fix is wrong in that state. NARROW fix chosen for exactly this reason —
  confirm against a real captured halftime payload before generalising.
- Verification: reachability FIRST (a halftime case that FAILS on purpose
  pre-fix), then a real between-periods payload from a live game.
- Blocked by: none.

### nfl-props-odds-allowlist — OPEN, **UNOWNED** (session e5e93171 checkpointed and archived 2026-08-21) — NARROWED TO ONE UNDEPLOYED FIX — **THE CAPTURE FIX IS VERIFIED IN PRODUCTION.** `oddsapi_player_props_2026_wk1.csv` went **5 bytes -> 12,142** at 2026-08-21T14:08:06Z with a FRACTIONAL mtime (runtime write, not a boot copy): **84 rows, 84 distinct players, real DraftKings Anytime TD prices**, captured unattended by refresh-worker. First real NFL player-prop capture this platform has ever made. The model was also PRICED for the first time: **-7.35% over 64,007 bets** — it does not beat the market (fading it loses 16.93%, so the picks are correctly signed, they just do not clear the vig). Price shopping **+2.95 ROI pts** (controlled, identical bets); game context **+1.18 pts** (paired, held-out). **REMAINING: one landed-but-undeployed fix, deliberately left to ride along on the next main deploy — see OWED.** — opened 2026-08-20 — session e5e93171-243f-485e-8ade-9116f0130519
- Goal: a real ROI number for NFL player props. **MET** — 64,007 graded bets, `reports/nfl_props_roi.json`.
- Claims held: **NONE.** refresh-worker released 2026-08-21 deliberately rather than
  held through polling — the service was busy on nearly every check for two hours and
  other lanes needed it. Holding a lock while waiting on an unpredictable condition is
  the retired-coordinator anti-pattern.
- **OWED — ONE ITEM, and it needs NO dedicated deploy:**
  `a41f88f8` on main fixes `#389` hit a second time: `fetch_nfl_schedule.py` wrote via
  the PROBING `default_nfl_source_root()`, which returns the root holding
  `upcoming_recs_*.csv` — shipped by the repo mirror, absent from the mounted disk — so
  every write landed in `/opt/render/project/src/data/nfl_source`, the EPHEMERAL
  CHECKOUT, and `publish_hot_artifact` was a silent no-op (`relative_to_data_root()`
  returns None outside the data root, hence no publisher verdict of any kind). The step
  reported `status=ok return_code=0` in 1s every cycle and delivered nothing.
  Writer now uses `nfl_artifact_output_root()` (no probing); reader
  (`game_context.schedule_paths`) puts that same root first. 2 regression tests.
  **WHOEVER DEPLOYS MAIN TO refresh-worker NEXT PICKS THIS UP FOR FREE.** Then verify:
  `nfl_source/schedule_2026.csv` on web must gain a **FRACTIONAL** mtime (whole-second =
  another boot copy, not a publish) AND its lined-game count must go **67 -> ~112**.
  Both together; a fresh mtime alone could be a rewrite of stale bytes. Measured
  2026-08-21: web 67 lined vs nflverse 112, 61 rows differing on spread/total.
  NOT URGENT — it only feeds the game-context multiplier (+1.18 pts on a -7.35% model),
  and NFL Week 1 is 2026-09-10.
- Also landed this session: run-summary artifacts are now allowlisted
  (`reports/migration_runs/*/odds_refresh_*/`), which is what made the above
  diagnosable at all after three independent routes returned nothing.
- Blocked by: none.

### wnba-live-props-data — **OPEN, UNOWNED** `[session 1f76348c 2026-08-21T17:4xZ]` — **PROPS CHAIN BUILT+DEPLOYED (UNPROVEN); `#499` TOTALS PRICING DEPLOYED (UNPROVEN).** Live on BOTH workers at `8d5d6edf` (refresh-worker 16:43:05Z, live-odds-worker 16:48:04Z) — totals scale `3.2` + `ANALYTIC_LIVE_STD_ERR_BY_MARKET {("wnba","totals"): 0.150}` + the fix for it shipping INERT. **TWO READINGS OWED, BOTH BLOCKED ON A LIVE SLATE, BOTH ARMED:** scheduled task `verify-wnba-totals-pricing-499` fires 19:15 CDT 2026-08-21 carrying both. (a) `#499` PASSES only if totals rows refuse as `prob_interval_swamps_edge` (per-row) NOT `analytic_estimator_never_backtested_for_this_market` (category-wide); at sigma=0.150 the bar is ~30pp so **priceable volume is a BUG signal, not success**. (b) `#498` props PASSES only on `WNBA_LIVE_BOX_CAPTURED` with players (live-odds-worker) AND `live_projections.rows_live_projected` > 0. Pre-tip both read 0 — **a zero is indistinguishable from an inert feature**; verifier `scripts/verify_wnba_totals_pricing.py` exits 3 rather than 0 for that reason. DO NOT report either as working. Narrative: `log/2026-08-21.md`. Claims: NONE held. — opened 2026-08-20 — session 1f76348c-062d-4075-a54b-a8b0eadabb2b
- Goal: live WNBA props. **Phase 1 (THIS LANE): persist the live per-player stat
  lines so a worker can read them.** The data was never missing --
  `/wnba/api/live_player_boxscore` serves minutes/pts/reb/ast/threes and has all
  along; it is fetched in the REQUEST PATH on web while the prop join runs in the
  board build on a WORKER, so there is no artifact to read.
  **Testable outcome:** `scripts/capture_wnba_live_player_box.py --date <d>`
  writes an allowlisted artifact on a live slate. VERIFIED against production
  2026-08-21 03:37Z: `games=2 players_with_stats=39` (19 + 20).
- Files:
  - `scripts/capture_wnba_live_player_box.py` — the capture (new).
  - **BLOCKED, NOT CLAIMED:** the `HOT_ARTIFACT_PATTERNS` entry for
    `wnba_source/data/live/live_player_box_*.json` lives in a file held by the
    OPEN lane `nfl-props-odds-allowlist` (actively editing that same list). Not
    edited across lanes. **Until it lands the capture writes an artifact the
    board build cannot see** — written, not yet reachable, which is exactly the
    half of `#488` that reads as working. Owed with it: the
    `is_hot_artifact_relative_path` test.
- Hypothesis: n/a — measured. See `log/2026-08-20.md` and the `state.md`
  correction stamped on the "nothing for props" sentence.
- Falsification test: if the artifact is written but the board build cannot read
  it, the allowlist entry is wrong or nothing publishes it — the two halves
  `#488` records as separately broken. `is_hot_artifact_relative_path` is
  asserted in the tests for exactly that.
- Verification: the capture REFUSES to store an empty/hollow payload (tested),
  because a persisted empty is served in preference to real data thereafter —
  `capture_wnba_pbp.py`'s recorded failure mode.
- **PHASE 2 DONE (pure function, not wired):**
  `syndicate/features/shared/wnba_live_prop_projection.py`. Mirrors `#475`'s
  anchored shape deliberately rather than inventing a third live convention:
  `projected = current + remaining * ((1-w)*pregame_rate + w*live_rate)`,
  `w = played/pregame_minutes`. Collapses to the pregame number at tip-off and
  to the actual stat at the buzzer (both tested — an estimator that misses its
  own endpoints is wrong in the middle too). Remaining minutes CAPPED by the
  game clock. **REFUSES without a pregame anchor** rather than extrapolating a
  live rate — that input is exactly `#475`'s 240-point total. Worked example on
  a real production line (Angel Reese 6 pts / 9 min, 12-pt anchor): projects
  **16.08**, against a naive pace of 20.0 that is never produced.
  **Publishes NO probability and prices NO edge** — this estimator has no
  measured interval, so an edge off it would route around both
  `prob_interval_swamps_edge` and
  `analytic_estimator_never_backtested_for_this_market`. 14 tests + 8 subtests.
- **PHASE 3 ANCHOR FOUND `[2026-08-21, measured]` — the blocker was an unknown,
  not an absence.** `wnba_source/data/processed/cards_sim_detail_<date>.json`
  (exportable, 2.1MB) carries per player under `games[].sim.players`:
  `min_mean` (**expected minutes — phase 2's denominator**), `{pts,reb,ast,
  threes,pra}_mean` + `_sd` + `_q{p10,p50,p90}`, and `prop_ladders[stat]` with
  `simCount: 100`, a full `distribution` histogram and a `ladder` of
  `{total, hitProb}`. Worked example: Paige Bueckers `min_mean 38.37,
  pts_mean 23.39, pts_sd 7.33`. `props_predictions_*.csv` is 403 from WEB but
  that is a route restriction — the lens builder runs on a WORKER and reads
  these directly.
- **THE ONE DECISION PHASE 3 STILL NEEDS, and it must not be made silently.**
  `build_live_prop_index` keys on `liveModelProbOver`, a PROBABILITY. The ladder
  above is the PREGAME distribution: it answers `P(final >= line)` from tip-off.
  A LIVE prop needs `P(final >= line | current, minutes played)` — i.e. the
  distribution of the REMAINDER over the minutes left, which is not the
  full-game distribution and cannot be read off this ladder. Scaling it
  (mean by `m/min_mean`, sd by `sqrt(m/min_mean)`) is the standard assumption
  and is **UNMEASURED HERE** — making it silently is the same move as pricing
  the un-backtested totals estimator. Options: (a) publish phase 2's PROJECTION
  on the lens in a non-probability field and leave the join gate shut, or
  (b) grade the scaling assumption, then price under `prob_std_err(p, simCount)`
  — `simCount: 100` means the SAME interval machinery MLB's 120-sim game lines
  already use would apply.
- **NOT unblocked by this find: TOTALS.** The sim publishes no game-level total
  distribution — `quarters` is `[]` and `players_summary` is bare counts. Totals
  still needs the OddsAPI historical backfill and a grade.
- **PHASE 3(a) DONE `[2026-08-21, user decision: option (a)]` — projections
  published, NO probability.** `syndicate/features/shared/wnba_live_prop_rows.py`
  joins the live capture to the sim anchor by NAME and emits one row per
  (player, stat) carrying `liveProjectedStat`, `current`, `minutes_played/
  remaining`, `pregame_mean/minutes`, plus `priceable: False` and
  `not_priced_reason: live_prop_projection_has_no_measured_interval` spelled out
  per row. **It carries no `liveModelProbOver`, so `build_live_prop_index`
  cannot pick it up and the `sport != "mlb"` gate stays shut — by design, not by
  omission**, and a test asserts no probability-shaped key ever appears.
  Unmatched players are COUNTED AND NAMED (`players_unmatched`), because a name
  join is the machinery whose 91% miss this project already paid an
  investigation for. **A real defect the tests caught:** apostrophes were being
  substituted with a space, so `A'ja Wilson` normalised to `a ja wilson` and
  would have matched nothing — an apostrophe is intra-word, a hyphen separates
  words, and they cannot share a rule. 33 tests + 20 subtests.
  **Verified against real production data:** the empty-capture refusal fired on
  the rolled slate (`games=3 players_with_stats=0` -> REFUSING to write).
- **THE SCALING IS GRADED `[2026-08-21]` — and the assumption turned out to be
  unnecessary.** `scripts/grade_wnba_live_prop_projection.py` replays ESPN pbp,
  reconstructs each player's running points and minutes, drives the SHIPPED
  projection at every scoring play, and scores it against the official final.
  **The replay is self-checked and reconciles 100%** (6+ games, 118+ players,
  points AND minutes exact) — a residual from an unreconciled replay measures
  the bug, so the grader refuses to score one. Rather than grade the assumed
  sd-scaling (`sqrt(m/min_mean)`), it MEASURES the projection's own residual,
  which needs no assumption and is the quantity a consumer wants.
  **POOLED n=796 over 5 slates:**

      minutes_left      n     mean      sd   p90/sd
           30-99       21    +0.18    6.03     1.71
           20-30      129    +0.42    5.38     1.59
           10-20      220    -0.54    5.30     1.61
            5-10      136    -1.23    3.88     1.56
             0-5      290    -1.69    2.70     1.90
             ALL      796    -0.90    4.39

  The interval SHRINKS MONOTONICALLY as the game runs down (6.03 -> 2.70), so a
  single sd would price both ends wrongly. `p90/sd` sits at 1.56-1.71 against
  1.64 for a normal, so the residual is APPROXIMATELY NORMAL in the bulk —
  `P(final >= line) = 1 - Phi((line - projected)/sd_bucket)` is defensible with
  the MEASURED sd. Two caveats for whoever prices it: the `0-5` bucket has
  heavier tails (1.90) and a real late UNDER-projection bias (-1.69).
- **PHASE 3(b) DONE — `liveModelProbOver` is emitted, from the MEASURED
  residual.** `wnba_live_prop_probability.py` turns the projection into
  `P(final >= line) = 1 - Phi((line - projected) / sigma(minutes_remaining))`
  using the graded table above. Three choices, each recorded at the point of
  use: (i) **tail-matched sigma**, `max(sd, p90/1.6449)` — measured sd, widened
  ONLY where the observed tail is fatter than normal, which is the `0-5` bucket
  alone (2.70 -> 3.12); (ii) **NO bias correction** though one was measured, as
  the per-bucket mean flips sign (+0.42 .. -1.69) and fitting it at n=796 is
  fitting noise — a wrong correction shifts every probability one way, worse
  than a slightly wide interval; (iii) **refuses outside the measured range** —
  unknown minutes remaining gets None with a reason, never a default sigma and
  never 0.0. A row prices ONLY when a line is supplied for its
  `(player, market)`. 48 tests + 31 subtests across phases 1-3(b).
  **This does NOT open the join's gate** — `attach_live_projections_for_sport`
  still returns early on `sport != "mlb"`; that is phase 4.
- **PHASE 4 DONE — the gate is OPEN for wnba, and opening it did NOT create a
  silent zero.** `_LIVE_PROP_SPORTS = {mlb, wnba}` in
  `attach_live_projections_for_sport`. `to_snapshot_live_props` translates this
  module's internal rows into the contract `build_live_prop_index` actually
  reads (`playerName` / `prop` / `line` / `liveProjection` /
  `liveModelProbOver`). **Market keys verified against production**
  (`player_points` 45 rows, `player_assists` 21, `player_rebounds` 14,
  `player_threes` 8) rather than guessed — `_snapshot_market` reads `prop` first
  and the board speaks OddsAPI, which is `#412` exactly
  (`miss_no_market_alias = 1385 of 1385`). Markets the board carries but this
  cannot project (`player_double_double`, `player_points_rebounds_assists`,
  `player_triple_double`) are DROPPED, never aliased to something close.
  **A snapshot whose games carry no `liveProps` is now reported BY NAME**
  ("producer not wired") instead of returning 0 rows as though the join had run
  — replacing a named refusal with a silent zero is the permissive-default shape
  this repo has a standing rule about. 202 tests + 45 subtests green across
  props, the game-line join, live-edge policy/enforcement, book-grid and layer-1.
- **WIRED `[2026-08-21]`.** The lens loop captures the live player box before
  the WNBA build (after the headroom gate, so a skipping tick spends no HTTP
  call) and `wnba/live_lens.py::_attach_live_props` CONSUMES that artifact and
  stamps `liveProps` + `livePropsCoverage` per game. The builder never fetches.
  Lines come from the card's `shared_prop_rows` — a FOURTH vocabulary for the
  same four stats (`pts/reb/ast/threes`), verified against 2026-08-19 and
  2026-08-16 rather than assumed. **COVERAGE IS KNOWINGLY THIN:** those are the
  card's FEATURED props (8-9 per slate) not the board's ~120; the fuller source
  is `oddsapi_player_props_<date>.csv`, readable on the worker, and is the
  obvious next widening. Combination markets (`ra`/`pa`/`pr`) are unmapped —
  they cannot come from a single stat mean.
- **A PRECEDENCE BUG THE WIRING TEST CAUGHT:** `sim_game = (a or b) if
  isinstance(pack, dict) else {}` — a conditional expression binds looser than
  `or`, so every game WITHOUT an `evidence_pack` silently got `{}` including
  those with a perfectly good `sim`. Surfaced as `players_matched 0 != 1`, not
  by reading the line.
- **STILL NEVER RUN END TO END.** Every hop is now wired and unit-tested, but
  nothing has executed against a live slate: no deploy, and no WNBA game live
  since the wiring landed. The prop join reports "producer not wired" by name
  until it does. NEXT: deploy, then read `livePropsCoverage` and the join's
  `rows_live_projected` on a live game.
  `prob_std_err`/`PRICEABLE_SIGMA` refusal then applies ON TOP, exactly as for
  MLB — so opening it does not mean every row prices. Previously listed as (3b),
  now done:
  `(player, market, line)` on WNBA's lens rows; (4) open the `sport != "mlb"`
  gate in `attach_live_projections_for_sport`. **Phase 2 needs a MEASURED
  interval before any edge is priced** — same discipline as totals; an
  unbacktested live prop projection may be PUBLISHED but not PRICED.
- **HANDOFF `[2026-08-21]`.** Deployed and reachable; claims released; nothing
  uncommitted. BOTH owed readings need a LIVE WNBA SLATE and neither is blocked
  on code:
  1. `WNBA_LIVE_BOX_CAPTURED games=N players=M` on live-odds-worker, then
     `livePropsCoverage` on the lens and `rows_live_projected` on the board. If
     the capture line appears and the other two stay empty, the fault is in the
     join and its counters name it.
  2. This lane's sibling `wnba-halftime-elapsed` needs a between-periods payload
     (blank clock) to confirm the live lane survives the break.
  Widen the sigma table before the `0-5` bucket carries real money: n=796 over 5
  slates against `#481`'s 73,878, and the grader takes `--date` per slate.

### portfolio-ledger-service-split — OPEN — opened 2026-08-22 — session 74a0966a-a9fe-57cd-8320-f46f235aeed1
- Goal: a bet logged on WEB can be settled by the autorun on REFRESH-WORKER, so
  `/portfolio` stops reading every position as pending.
- Files: `syndicate/features/prediction_ledger.py`,
  `syndicate/features/shared/ledger_bridge.py`,
  RELEASED `[2026-08-24 to exchange-markets-api-integration]`: `scripts/run_refresh_worker.py`
  Reworded 2026-08-28 so the parser can SEE the release this lane already
  recorded in prose; a marker governs what FOLLOWS it on ITS OWN LINE, and the
  old wording put both the strikethrough and the word after the path. Session
  `74a0966a` archived 2026-08-22, `lane-guard` was blocking a narrow,
  additive, try/except-wrapped diagnostic hook on the strength of a dead
  session's claim; rest of this lane's file list untouched),
  `scripts/backfill_portfolio_settlement.py`,
  `tests/test_prediction_ledger_shared_store.py`,
  `tests/test_evaluation_settlement_autorun_ordering.py`,
  `tests/test_ledger_bridge_identity_join.py`,
  `tests/test_backfill_portfolio_settlement.py`
- **Status: three defects found, all FIXED AND DEPLOYED. The goal is NOT met —
  nothing has settled yet.** Narrative and evidence: `log/2026-08-22.md`.
  Subject facts: `state.md [portfolio-settlement]`.
  - `#502` ledger crosses the service boundary — live both services `2aa1df54`
  - `#504` settlement 13th -> 2nd in the chain — live `4eeffb5c`, VERIFIED 1.3ms
  - `#505` join on a stable identity — live `a1e89ff3`, refresh-worker only
- **Unverified and load-bearing:** `#505`'s `entity` field mapping was never
  measured against real evaluation records (worker-local, not in
  `HOT_ARTIFACT_PATTERNS`).
- Backfill tool BUILT and NOT RUN against production:
  `scripts/backfill_portfolio_settlement.py`, preview-by-default. Ran in preview
  in-session; it proved the tool works and nothing about production (no local
  portfolio ledger; the one local evaluation chunk holds a single
  `record_type: prediction` row, not a wager).
- Verification still owed: the next `[ledger_bridge]` line, 2026-08-23 after
  06:00 CT. `matched_by_identity > 0` = the join works; `by_identity` large with
  `matched_by_identity: 0` = the entity mapping is wrong. **That same line also
  gates the backfill** — do not run it with `--commit` before that reading.
- Session `74a0966a` ARCHIVED 2026-08-22. All four deploy claims free at exit.
- **NOTE for whoever owns `refresh-worker-oom-recurrence`:** this lane edited
  `scripts/run_refresh_worker.py`, which your lane nominally holds. Your block is
  no longer in `lanes.md` so `lane-guard` saw no claim. Flagged because the
  change moves an expensive job earlier in the tick chain.
- Blocked by: none.

### render-web-request-path — **OPEN, UNOWNED, CLAIMS RELEASED** `[session 726ef4ff checkpointed and archived 2026-08-22 ~19:4xZ]` — **SHIPPED AND MEASURED; ONE ITEM OWED**
- Goal: web stops being SIGTERM'd during live MLB slates. **Changes 1 and 2 MET.**
- **Claims: NONE held.** Released deliberately at archive time so no future session
  is blocked on `home.py` / `mlb/cards.py` by a dead owner — the orphan failure the
  2026-08-18 sweep had to clean up across 8 lanes.
- **VERIFIED** (web `8149e51d` 19:09:35Z, still live under peer `3ada3512`):
  `apply_live_scores` **3318-8400ms -> 0-93ms** on `games=15`, 14 samples across two
  instances and two deploys. Zero `Handling signal: term` since, against 3 in 4 min
  before. Cold boot exonerated at 2.7s boot-to-listening.
- **OWED, THE ONLY OPEN ITEM:** the card-cache idle bound is **NOT** verified.
  Baseline to beat: 369 MB -> 2,026,717,200 B over ~7.5h, ceiling 2,147,483,600 B.
  Post-deploy numbers are directionally better at comparable ages and that is not
  proof. **Blocked in practice** — peers redeploy web every 20-30 min so no instance
  lives long enough. Instrument: memory-over-uptime + the rate of
  `CONTEXT_CACHE_EVICTED ... web=True` falling.
- **DO NOT allowlist `raw/statsapi/feed_live`** — it freezes live scores (`#413`) and
  buys no speed. Full reasoning in `state.md [web-request-path-latency]`.
- Narrative + evidence: `log/2026-08-22.md` (session `726ef4ff`). Deploy record and
  the stated preflight deviation: `deploys.md` 2026-08-22 19:03Z.
- Next bottleneck, now visible: `build_cards_page_context` 1803-2402ms on a miss.

### portfolio-decision-and-execution — OPEN — opened 2026-08-22 — session 9324a3e5-364e-5fb4-9b4a-b0568019e37f
- Goal: a staged, gated path from the Layer 2 shortlist to a COMMITTED
  portfolio (a closed list of N bets at M dollars, not a ranked board with
  suggestions attached) and then to automated placement — with each stage's
  acceptance stated as a READING, and real money gated on a CLV result rather
  than on the previous stage having shipped.
- Plan: `.syndicate/plan_2026-08-22_portfolio_execution.md` (stages A-D +
  precondition). **STAGE A IS NOW BUILT IN CODE, DARK, AND NOT DEPLOYED.**
- **BANKROLL = $1,000** `[user decision 2026-08-22]`, and user-editable:
  `portfolio_settings.py`, a form on `/portfolio`, `GET`/`POST
  /api/portfolio/settings`. Precedence stored > env > default; **every read is
  fail-safe toward the default**, because a bankroll resolving to 0 on an
  evicted key would size every bet at $0 and read as a quiet slate. The settings
  path carries **no date token** — a dated one takes the store's 10-day TTL and
  the bankroll would silently expire (pinned by a test).
- **TWO INERT-FEATURE DEFECTS, both caught by
  `scripts/portfolio_commit_input_checklist.py` on its FIRST run and by nothing
  else — no test would have failed:**
  1. **`_attach_board_stakes` does not reach the Layer 2 shortlist.** It runs on
     Layer 1's `global_pool`; `build_layer2_shortlist` builds a separate set of
     rows carrying **no sizing fields at all**. The obvious implementation
     (`compute_bet_size(row)`) returns `model_probability 0.5`,
     `implied_probability 0.5`, `edge 0`, **`$0` for every position** — no
     exception, no log line — so the portfolio would have been empty and
     indistinguishable from a thin slate. Stage A DERIVES its inputs instead
     (inverting `expected_value_pct` for the market probability, then adding
     `model_edge_pct`) and refuses by name, never on a default.
  2. **`confidence` is structurally inert in `compute_board_stake`.** Measured:
     `kelly_fraction 0.0241 -> stake 0.00151`, `cap_fraction 0.0446`. The raw
     kelly fraction is what gets shrunk; `confidence` feeds only the cap, which
     sits ~30x above the stake and never binds. Trust weight 0.82 -> 0.32 moved
     the cap 0.0446 -> 0.0296 and the stake **not at all**. **This is a
     `bankroll_manager` property, so it is equally true of `_attach_board_stakes`
     on the Layer 1 pool: `confidence` does not move the served stake.** That
     file is read-only for this lane — recorded, NOT fixed.
- **STORAGE RESOLVED `[measured 2026-08-22T19:0xZ, Render API]` — the ledger's
  own figure was two weeks stale and reversed the decision.** The keyvalue
  `red-d88bvljbc2fs73epfhhg` is at **36.6%** (98.2MB / 268.4MB), 24h range
  83.5–118.1MB, **~170MB headroom** — not the 96% / 34,529-evicted that
  `refresh_state_store.py:139-205` records from 2026-07-31. `#324` reclaimed it.
  Also newly recorded: `persistenceMode: journal_snapshot` (**not a pure
  cache** — it journals AND snapshots), `maxmemoryPolicy: allkeys_lru` which is
  **NOT in `render.yaml`** (so changeable without a `blueprint_sync`, and
  resettable BY one), and **no Postgres exists in the account**. **Therefore
  Stage B does not need Postgres and the plan no longer carries a
  three-service sync.** Recommended and NOT taken (production change, user's
  call): `allkeys_lru` → `volatile_lru`, which makes no-TTL keys — the
  bankroll, the Stage B ledger, `#502`'s `prediction_ledger.json` —
  structurally un-evictable. STILL UNVERIFIED: `evicted_keys`/`keyspace_misses`;
  the metrics API exposes memory, not Redis INFO. Full working: `todo.md #508`.
- **SIM ROLE MEASURED, and the premise "the board is EV only" needed
  correcting: it is true of RANKING and false of SIZING.** On a representative
  row the sim owns **57.6%** of the stake (0.003132 vs 0.001328 with
  `model_edge_pct` zeroed), and it is what **picks the side** — at
  `_SCORE_SIM_WEIGHT = 0.0` `blended_score` reduces to `ev_pct`, which is
  identical for every side of a market, so the shortlist cannot discriminate and
  Stage A's `zero_kelly_stake` refusal does it instead. **Deliberately did NOT
  raise the weight** (`opportunity_signals.py` is unclaimed, so this lane
  could have): the constant's own comment is right that no value works, because
  the missing input is `settled > 0`, not a coefficient. Shipped instead the
  thing that comment says *"nobody has been able to supply"* — per-bet CLV
  decomposition by component (`stake_attribution`: `stake_fraction_ev_only`,
  signed `stake_fraction_sim_delta`, `sim_share_of_stake`, `side_picked_by`,
  plus plan totals). The delta is NOT clamped at zero, because a small negative
  sim edge can legitimately shrink a position and clamping would credit the sim
  only where it helps. Full working: `todo.md #509`.
- **CORRECTION `[user-flagged 2026-08-22]`: "the board is running at 0% sim" is
  RIGHT, and 57.6% was NOT about the board** — it is Stage A's sizing on a
  SYNTHETIC row in undeployed code, and describes nothing running. **Do not
  quote it as production.** The board's 0% is structurally guaranteed:
  `sim_component = _SCORE_SIM_WEIGHT * value_sim` is `0.0` where a sim view
  EXISTS and `None` where it does not, so it can never be non-zero and says
  nothing about whether the sim produced anything. **It did** — production
  refresh-worker 2026-08-22T19:20:09Z (`rows=323 considered=17205`): mlb
  2,279/2,656 projected (86%), wnba 374/391 (96%), nfl 1,010/1,309 (77%),
  soccer 10,686/20,016 with `with_prob=9,896`. **The sim is attaching
  projections to most of the board and the ranker multiplies all of it by
  zero** — deliberately unused, not missing or starved. UNMEASURABLE THIS
  SESSION: the sim's stake share on REAL rows; the agent proxy 403s
  `syndicate-an21.onrender.com`, so no served artifact was readable. Stage A now
  emits `sim_coverage` so the first production commit answers it as a number.
- **SCORING RE-EVALUATED `[user decision 2026-08-22]` — `_SCORE_SIM_WEIGHT`
  0.0 → 0.125 WITH A HARD CAP `_SCORE_SIM_CAP_PCT = 1.5`. THE FIX IS THE CAP,
  NOT THE COEFFICIENT.** The file's prior argument — *"there is NO value of this
  constant that produces a credible board"* — is correct **for a bare weight**,
  which scales with the edge so a large enough disagreement always wins
  eventually (0.25 fails like 0.5, later). But this module already solved that
  once, for the movement term, and said so in its own comment: *"a cap is the
  STRUCTURAL fix for it rather than a smaller number that fails the same way
  later."* The sim term never got that treatment. **Measured by
  `scripts/score_sim_weight_impact.py`, which REPLAYS the 2026-08-08
  distribution that caused the zeroing** (286/300 negative-EV, median edge
  10.36/10.80/12.49/11.99):

      configuration                negative-EV rows promoted   side-picking
      0.5 uncapped (2026-08-08)              286/286              yes
      0.0 (the state replaced)                 0/286              NO
      0.125 capped at 1.5                      0/286              yes

  The pathological row worked: `ev -5, edge +12` → at 0.5 `-5 + 6.00 = +1.00`
  (ranks, the failure); at 0.125-capped `-5 + 1.50 = -3.50` (does not rank).
  **THE POINT OF THE CHANGE:** at 0.0 the board provably **could not pick a
  side** — EV against a proportional de-vig is `1/overround - 1`, identical for
  every side — so it ordered by hold and broke ties arbitrarily. Any non-zero
  contribution makes the sim the entire tiebreak. Both constants are
  env-overridable (`SYNDICATE_SCORE_SIM_WEIGHT`, `SYNDICATE_SCORE_SIM_CAP_PCT`;
  cap 0.0 restores the old behaviour exactly), so this is reversible in seconds
  without a deploy. **STILL A SCREEN, NOT A VALIDATION** — it proves the weight
  cannot repeat the 2026-08-08 arithmetic failure, NOT that the sim is right;
  that still needs `settled > 0` + Stage A's per-bet component decomposition.
- **DEPLOY BLOCKER CLEARED `[user directed 2026-08-22]`.** The stale disclosure
  was flagged as cross-lane and NOT edited; the user then directed the change
  directly, so `intelligence.html` and `layer2_board.py` are claimed **NARROWLY**
  from `layer2-sim-view-and-live-projection` — the same narrow-claim pattern
  that lane itself used on `soccer_projections.py`/`team_aliases.py` on
  2026-08-22. **Taken: the scoring disclosure, the `sim disagrees` tooltip, and
  `_row_value_pct`/`_row_admitted_by_blend` only.** Nothing about the sim view,
  live projection, joins or board rendering was touched.
  **TWO stale user-facing claims found, not one.** The known disclosure, plus
  `intelligence.html:2674` — the `sim disagrees` chip's tooltip read *"It
  carries no weight in the score"*, which the weight change also falsified.
  Found by rendering the page and grepping the SERVED body, not by reading the
  file; the second one was not on any list. Both now describe the cap.
- **SCORE NOW GATES ADMISSION, NOT JUST ORDERING `[user decision 2026-08-22]`.**
  `_row_value_pct` read `ev_pct` FIRST and fell back to `score.value_pct` only
  when EV was absent — which on a scored row it never is. So the sim could
  REORDER the board (`_score_of` ranks on `score.score`) but could never put a
  row ON it: admission ran on price alone, upstream of anything the sim had to
  say. It now prefers the blended `value_pct` (ev + capped sim + capped
  movement, all in EV points, so it is unit-comparable with the hold-derived
  floor) and falls back to `ev_pct` when there is no score block.
  **Bounded by the same cap:** the sim can carry a row across the floor by at
  most 1.5 EV points, so it rescues a marginal price and never a materially bad
  one — which is the only reason handing admission to the blend is defensible,
  since an uncapped term here would let an unvalidated model admit arbitrarily
  bad prices (the 2026-08-08 failure with a wider blast radius than ranking).
  **New counter `rows_admitted_by_blend`**, shipped at the builder AND the
  endpoint in the same commit — `#373`/`#381`/`#391`/`#397` each record a
  counter that existed at the builder and was invisible at that hop, three of
  them costing an investigation. **Zero means the change is inert.**
- **STAGE B BUILT — execution ledger, paper mode, dark behind
  `SYNDICATE_EXECUTION_ENABLED`.** Paper and live are the SAME code with one
  boolean between them (a test asserts identical field sets, differing only in
  `mode`). Idempotency is the load-bearing property: write-ahead (the record is
  on disk as `submitted` at the moment `submit` runs — pinned), a deterministic
  key that is an IDENTITY and **excludes the price** so a re-priced slate is the
  same bets, and refusal-not-overwrite so `submit` is never reached twice. Two
  independent switches for real money, both checked immediately before each
  submit; **any unrecognised mode resolves to `paper`**, the direction that
  spends nothing — the explicit lesson of the same day's backend incident. Live
  is blocked while any order is unreconciled. Storage per `#508`: keyvalue, **no
  date token**, bounded (lean fields, 5k cap with loud trimming, 2MB warning),
  and an unreadable ledger RAISES rather than reading as empty. **Measured end
  to end locally:** 3 rows → 2 positions ($5.19, 40.3% sim-attributed) → 2 paper
  fills → **replay placed=0, duplicates=2**. 41 tests. Full working:
  `todo.md #512`.
- **Local evidence (NOT production):** checklist PASSES 4/4 fields POPULATED and
  CONSUMED plus 4/4 named refusals; 50 new tests pass; 334 related tests pass;
  `/portfolio` renders 200 and a form POST persists a new bankroll (1000 ->
  2500, `source` flips `default` -> `stored`); 60 lane tests and 344 related
  tests pass. **No production slate has been committed — do not report Stage A
  as working.**
- **Stage C's precondition built, `#522`.** Nothing joined a committed position
  to the opening price recorded for its market — Stage A and Stage B carried no
  reference to `clv_opening_ledger` at all, while the openings were being
  recorded all along (3,105 for 08-22, `unkeyable=0`). Built on day 1 rather
  than at the end of the window, because that gap is invisible while it
  accumulates and `#505` is the same shape with a bill. Two paths — a key
  stamped from the same row in the same run, and a derivation for orders already
  placed — and the comparison between them IS the measurement; the derivation
  calls `_opening_key` rather than reimplementing it, so only the
  `book`→`quote.bookmaker` remap is hand-written. Plus live marks
  (`position_marks.py`): every order re-priced against the board, same book only,
  always in probability points via `clv_pct_from_prices`. Plus three page
  defects from the user's screenshot — orphan orders showed no player/line/
  matchup, nothing showed live tracking, and the status line read WEB's env for
  flags gating a WORKER job ("COMMIT JOB off" above 14 filled orders). 33 tests.
  **NOT DEPLOYED — refresh-worker was mid-sim 23:0x–23:1xZ.** The owed reading is
  `CLV_POSITION_JOIN ... derivation_disagrees=` on refresh-worker: non-zero means
  every pre-stamp order is unjoinable and Stage C cannot use tonight's data.
- **Stage B read surface shipped (`/portfolio/paper`).** The plan and the
  ledger both crossed the service boundary already (`_keyvalue_backed` True for
  `execution_ledger.json` and `portfolio_plan_<date>.json`), but nothing
  rendered them, so the only way to see a committed position was to read JSON.
  `/portfolio/paper` + `/api/portfolio/paper` join the ledger onto the plan by
  `position_key` and poll every 45s. **Kept off `/portfolio` deliberately** —
  that page is the user's own bets and `portfolio_summary._is_user_placed_bet`
  exists precisely because auto-tracked model rows once flooded it with 1000+
  "tracked plays" nobody had bet; simulated positions beside real ones would
  rebuild that confusion with better formatting. Four absence states stay
  DISTINCT (job off / no artifact / empty plan / orders never placed) and a
  ledger that cannot be read says so rather than rendering an empty table —
  "no bets" and "cannot see the bets" look identical and only one is safe.
  Orders whose position left the plan are surfaced as orphans, never dropped.
  12 tests. **Local only — no production render taken; production HTTP is
  unreachable from a Claude session (`state.md:2811`).**
- Files:
  `.syndicate/plan_2026-08-22_portfolio_execution.md`,
  `syndicate/features/shared/portfolio_settings.py`,
  `syndicate/features/shared/portfolio_commit.py`,
  RELEASED `[2026-08-28, session d617eefd]`: `syndicate/features/shared/execution_ledger.py`
  RELEASED `[2026-08-28, session d617eefd]`: `tests/test_execution_ledger.py`
  RELEASED, no longer claimed here: ~~`pipeline/portfolio_commit.py`~~ — a
  full claim is now held by `venue-join-refusal-visibility`
  `[2026-08-28, session d617eefd]`, which is fixing this line's own
  `KALSHI_BOARD_JOIN refusals=None` bug (it reads a key the join does not
  return). The path is struck from this Files list so the machine-readable
  claim agrees with the prose: the lane invariant checker does not read a
  strikethrough, and reported this as CONTESTED for that reason alone. Earlier note,
  still true: **INSTRUMENTATION-ONLY CLAIM TRANSFERRED
  to `venue-refresh-decoupling` `[2026-08-28, session 3e5a9659]`** — a timing
  span around the Polymarket join only, NO behaviour change and nothing near
  `_venue_price_resolver`, which this lane's block names as its own open work.
  Taken because this lane opened 2026-08-22 and its session
  (`9324a3e5`) does not appear in `list_sessions` at all. Take it back by
  striking this note.
  `scripts/portfolio_commit_input_checklist.py`,
  RELEASED `[2026-08-28, session 29794bbe]`: `syndicate/blueprints/intelligence.py`
  RELEASED `[2026-08-28, session 29794bbe]`: `syndicate/templates/portfolio.html`
  `syndicate/features/shared/opportunity_signals.py`,
  `scripts/score_sim_weight_impact.py`,
  `tests/test_layer2_blend_admission.py`,
  `tests/test_portfolio_settings.py`,
  `tests/test_opportunity_signals.py`,
  `syndicate/templates/portfolio_paper.html`,
  `syndicate/static/shared/paper_portfolio_pulse.js`,
  `tests/test_portfolio_paper_page.py`,
  `syndicate/features/shared/clv_position_join.py`,
  `syndicate/features/shared/position_marks.py`,
  `tests/test_clv_position_join.py`,
  `tests/test_position_marks.py`
- **NARROW CARVE-OUT released 2026-08-24 to `exchange-markets-api-integration`
  (session 71a74bb7)**, at the user's explicit direction after this lane's own
  owning session was found live and mid-task (`session_01Sia2rPD72eFTriy28azzs2`,
  "Reading the pregame sweep interval per sport") and the lane-guard hook
  offered no narrower mechanism than a whole-file release: `pipeline/
  execute_portfolio.py` -- `_venue_submitter`, adding one `elif name ==
  "polymarket":` branch (wiring `polymarket_us_orders.polymarket_us_submitter`)
  plus a new `_polymarket_resolve_market` helper -- and `tests/
  test_execute_portfolio.py`, new tests only, appended after the existing
  Kalshi price-resolution block, none of the existing tests edited. The rest
  of both files — everything this lane already built — is NOT touched. That
  session was messaged with the exact scope of this edit before any code
  change landed. Reclaim by re-adding both paths to the Files: list above
  whenever this lane wants them back; nothing here removes this lane's
  ownership going forward, only this one narrow slice tonight.
- **SECOND NARROW CARVE-OUT taken 2026-08-25 by `exchange-markets-api-integration`
  (session 71a74bb7) on `polymarket_board_join.py` / `venue_quote_adapters.py`**
  -- both files this lane has been actively committing to today (`3e8856e81`,
  `f32ec00ff`, `18569e814`, `053d336e8`) but had not added to its own Files:
  list above. User asked for a Polymarket coverage deep dive; found
  `SPORTS_MARKET_TYPE_DRAWABLE_OUTCOME` (soccer's 3-way moneyline shape)
  entirely unmapped in `MARKET_TYPE_TO_BOARD`/`_polymarket_sides`, and
  soccer's league match keyed on a literal `sport.lower()` string compare
  that can never equal Polymarket's per-competition slug token (`eflc`
  observed live). Full finding in this lane's own block below. Attempted
  direct message to `session_01Sia2rPD72eFTriy28azzs2` first -- not
  reachable as a live peer from this session's tools, so recorded here per
  this same fallback pattern. **Taken, scoped to exactly two changes**: (a)
  map DRAWABLE_OUTCOME -> `"h2h"` in both files' type maps, (b) soccer
  league resolution via competition tokens instead of literal string match.
  Nothing else in either file touched. Reclaim by re-adding both paths to
  this lane's own Files: list whenever wanted back.
  **SHIPPED, NOT DEPLOYED.** Committed `1868ff7a3`, pushed to
  `claude/exchange-market-apis-jr2lqy` (this branch is not `main`; no
  deploy implied). 43 new/updated tests; **254 tests green** across every
  directly affected suite (`test_polymarket_board_join.py`,
  `test_venue_quote_adapters.py` [new], `test_venue_quote_fanin.py`,
  `test_polymarket_us_markets.py`, `test_polymarket_side_vocabulary.py`,
  `test_polymarket_slate_freshness.py`, `test_kalshi_polymarket_arb.py`,
  `test_execute_portfolio.py`). A broader keyword-filtered run across the
  WHOLE `tests/` directory (`-k "polymarket or venue_quote or team_alias
  or soccer"`) hit a 300s timeout and was SIGTERM'd with no output at
  all -- same collection-time-slowness pattern this session already hit
  once today on a full unfiltered run, not a reported failure. Proceeding
  on the targeted 254, same as that earlier call. **OWED:** production
  verification once this lands on `main` and deploys -- the reading is
  `market_type_not_a_game_line` refusals dropping from ~50% of the
  catalogue, plus a nonzero `soccer` quote count where `venue_quote_adapters`
  currently logs `no_polymarket_row_for_league_soccer` on every cycle.
  **`pipeline/portfolio_commit.py` stayed on this lane's list, untouched** --
  its `_venue_price_resolver` (Kalshi-only price/ticker resolver, built from
  the WHOLE board-join across every market type this lane resolves, not a
  single-market lookup) is materially bigger scope than what was asked, and
  is the one piece still missing before a Polymarket order can reach the
  wired submitter above end to end: nothing populates `OrderRequest.
  venue_ticker` for `venue=polymarket` today, so the new submitter branch is
  real but currently unreachable in production. Named rather than built here,
  same discipline as the rest of this lane's honesty about unbuilt pieces.
  **CORRECTED same evening, per that lane's own acknowledgment
  (`.syndicate/deploys.md`, 2026-08-24 22:20Z):** `_polymarket_resolve_market`
  first called `polymarket_us_markets.fetch_game_markets()` LIVE, on the
  reasoning that no single-market fetch exists on this venue. That made it a
  SECOND independent live caller of the same venue -- `venue_quote_adapters.py`
  states outright that this is a documented incident class (`#139/#144`,
  `#148`) and already reads the persisted artifact instead. Rewritten to read
  `polymarket_us_markets.GAME_SLATE_ARTIFACT`
  (`reports/intelligence/polymarket_us_games.json`, 900s cadence, written by
  that lane's `persist_game_slate`) rather than the venue. Also fixed a real
  bug this forced into the open: the artifact's persisted rows carry NO `id`
  field (`_SLATE_STORAGE_FIELDS` has `slug`, not `id`) -- the original design
  keyed `venue_ticker` on `id` and would have refused every real lookup. Now
  keyed on `slug` directly, which is also what `order_body` needs, so no
  separate id->slug translation exists to drift out of sync. 3 new/renamed
  tests replace the live-fetch ones, including one that fails loudly if this
  function ever calls the venue directly again. 188 tests green across the
  four affected suites.
- Read-only, deliberately NOT claimed: bankroll_manager (Stage A calls
  `compute_board_stake` / `apply_exposure_budgets` and edits neither) and
  intelligence_state (reads `read_layer2_shortlist`).
- Collision check run against every OPEN lane before opening, and re-run with
  the guard's own Files-block parse before claiming the two EXISTING files
  above — `blueprints/intelligence.py` and `templates/portfolio.html` are held
  by no OPEN lane (`layer2_board.py:2634`'s comment naming intelligence.py as
  "held by another lane" refers to one since released). **Two lanes hold files
  this work touches conceptually and I took none of them:**
  `portfolio-ledger-service-split` holds `prediction_ledger.py`;
  `layer2-sim-view-and-live-projection` holds `layer2_board.py`,
  `pipeline/layer2_shortlist.py`, `blueprints/ops.py`, `intelligence.html`.
- Hypothesis (diagnostic half, stated before testing): the DECISION layer is
  substantially built and merely unassembled, while the EXECUTION layer does
  not exist at all and is blocked by something other than code.
- Falsification test: if any sportsbook credential, order call or account
  integration existed anywhere in the tree, the "execution layer does not
  exist" half would be wrong. Grepped for `draftkings|fanduel|pinnacle|
  prophetx|novig|sporttrade|betfair|kalshi|polymarket` across all `*.py` and
  for every outbound `POST`/`urlopen`: **every book name is an OddsAPI feed
  identifier only; every outbound write goes to Render artifact publishing.**
  Hypothesis holds on both halves — `compute_board_stake` and
  `apply_exposure_budgets` are already WIRED (`intelligence_state.py:4250`,
  `:4857`), and nothing places anything.
- **FINDING, checked not assumed — there is nowhere durable to put a money
  ledger.** `render.yaml` declares NO Postgres and no database: three services,
  three separate 50GB disks, one shared 256MB `keyvalue` on the starter plan
  which `refresh_state_store.py:139-205` documents at **96% memory, 34,529
  LRU-evicted keys, 44% keyspace miss** (2026-07-31; 38,865 evicted by
  2026-08-10). Two consequences: (1) `_default_keyvalue_ttl_seconds` gives any
  DATE-TOKENED path a **10-day TTL**, so an `execution_ledger_<date>.json`
  would silently expire — the ledger path must carry no date token; (2)
  `allkeys-lru` evicts keys that carry no TTL too, so **`prediction_ledger.json`
  is LRU-evictable** on a 96%-full instance. (2) is
  `portfolio-ledger-service-split`'s file — **surfaced, not edited.**
  UNVERIFIED: no Redis reading taken today; the percentages are the store's own
  dated comments. Take one before Stage B picks its storage.
- **Verification OWED, and it is a one-read production check.** Stage A is
  gated by `SYNDICATE_PORTFOLIO_COMMIT_ENABLED` (absent = off) and the deploy is
  a plain `.py` push — free, no `render.yaml`, no `blueprint_sync`. The reading
  is `off != on` on ONE date via `/api/portfolio/plan?date=<d>`: `plan_present:
  false, reason: commit_job_disabled` with the flag unset, and a plan whose
  positions sum exactly to the declared exposure with the flag set. Asserted
  locally in both directions already; **a local pass is not the reading.**
- Blocked by: none for stages A-C. **Stage D is blocked on
  `portfolio-ledger-service-split`'s outstanding verify** —
  `settled_count > 0` on `/api/portfolio/summary`. Every stake on the board is
  currently 1/16th Kelly by construction (`_DEFAULT_KELLY_MULTIPLIER` 0.25 ×
  `_MIN_SAMPLE_CREDIBILITY` 0.25) because settled sample is zero everywhere,
  and `_SCORE_SIM_WEIGHT` is 0.0 — so no edge on this board has been scored
  against an outcome yet. Real money before that reading is `learnings.md`
  2026-08-20's "validating against a PROXY" at its most expensive.

- **HANDED TO THIS LANE 2026-08-25 ~23:0xZ by `polymarket-oddsapi-coverage-audit`
  (session 0fd6da62): `find_first_game_offset` IS DROPPING ~8,400 GAME MARKETS
  RIGHT NOW, and `monotonic` cannot see it.** Not edited by that lane --
  `polymarket_us_markets.py` is yours in practice (you authored `508dbc02` and
  `f08930f32`), and this is a premise change rather than a constant.
  **Full item: `todo.md` `#559`. Working: `deploys.md` 2026-08-25T22:54:25Z.**
  Probed directly, one signed read per rung:

      OFFSET_BOUNDARY_PROBE boundary=20964 monotonic=True
        games_below_boundary={'12578': 5, '16771': 5, '18867': 5}
        12,578  GAMES 5/5 SPREAD  asc-nfl-ne-cle-2026-08-27-pos-1pt5
        20,754  futures (LPGA)    tec-lpga-fmcham-2026-08-27-r3l-hyecho
        20,964  BOUNDARY          tec-f1-pigp-2026-09-06-cons-alpine

  The ordering is NOT `[futures][games][empty]`: a golf/F1 futures band sits
  ABOVE a large game block and the search converges into it. `monotonic=True`
  only checks offsets the search itself probed, so it passes while wrong.
  `truncated=False` is true and misleading -- it paged to the end from the wrong
  start. **`_slate_within_budget` is EXONERATED** (`dropped_for_size=0` every
  cycle, 5.99MB headroom) -- it was the first hypothesis and it never fired.
  **NFL wk1 is 2026-08-27 and its full-game spreads are in the invisible band**;
  the symptom is `market_unresolved_for_position`, the same one `f08930f32` was
  written for. Reproduce free with `SYNDICATE_POLYMARKET_OFFSET_PROBE_ON_BOOT=1`
  (PR #74, currently `0`); it derives its rungs from the live boundary.
  Attempted to reach session `01Sia2rPD72eFTriy28azzs2` directly first --
  `ListAgents` returns no reachable peer (cloud session, separate container) and
  the CCR server exposes no session-to-session send -- so this is recorded here
  and in `todo.md`, per this file's established fallback.

### exchange-markets-api-integration — OPEN, GOAL COMPLETE, lane idle — opened 2026-08-24 — session 71a74bb7-67ff-5c39-af7a-c11c2d94cce8
- Goal (DONE): read-only market/odds-pulling client modules for six
  prediction/event-market venues (coinbase, prophetx, novig, polymarket,
  robinhood, crypto.com "OG"). Full research findings, per-venue status, and
  the Novig/ProphetX order-automation scoping work: `todo.md #544` (canonical)
  and `lanes_history.md` (this lane's full narrative, moved 2026-08-25).
- Files still claimed: `syndicate/features/shared/{coinbase,prophetx,novig,
  polymarket,robinhood,cryptocom}_client.py`, matching `scripts/probe_*.py` and
  `tests/test_*_client.py`, `.syndicate/scope_2026-08-24_exchange_markets_api_integration.md`,
  `scripts/probe_exchange_markets.py`.
  RELEASED `[2026-08-29, USER OVERRIDE, to ncaaf-no-orders]`: `scripts/run_refresh_worker.py`
  This lane's claim on it was always **NARROW** and self-described as "one
  small, additive, opt-in-only boot-probe hook"; the lane is idle with
  "nothing outstanding". `ncaaf-no-orders` needs a DIFFERENT region of the same
  file (`_season_projection_should_launch`), `lane-guard` BLOCKED it, the
  conflict was surfaced to the user rather than worked around, and the user
  granted the override. Marker on its own line so the parser SEES the release,
  per the note in `portfolio-ledger-service-split` — which released this same
  path to this same lane on 2026-08-24 for the same reason.
- **Status: nothing outstanding for this lane.** `#544`'s stated NEXT phase
  (order automation for whichever of polymarket/novig/prophetx clears
  legal/ToS review) is externally resolved: Polymarket order automation
  shipped via a sibling session; Novig buy-side automation is OFF by explicit
  user decision (2026-08-24); ProphetX is blocked on a partner credential with
  no self-serve path. Checked against `todo.md` on 2026-08-25 — unchanged,
  still the same answer.
- **2026-08-25 follow-up work, same conversation, not this lane's original
  scope:** real-money execution-cap change (bankroll $1000 unchanged, Kalshi
  $50/day, Polymarket $100/day, $10 max order, 15 combined orders/day) — PR #62
  merged, `live-odds-worker` + `web` redeployed, `live-odds-worker` env vars
  fixed to match (was drifted to a flat $40/day for both venues), **verified
  live in production 2026-08-25T19:35Z**. PR #63 (deploys.md record) merged.
  Both feature branches (`claude/exchange-market-apis-jr2lqy`,
  `claude/record-deploys-2026-08-25`) deleted post-merge — deletion itself had
  to be done by the user; this session's git/API credentials are blocked from
  ref-deletion (confirmed via both `git push --delete` and a direct GitHub API
  `DELETE`, both 403). One confirming comment posted on PR #61 (a different
  session's work) as one of two named owners of `run_refresh_worker.py`; the
  other named owner's session (`portfolio-ledger-service-split`, `74a0966a`)
  was archived before that PR opened and could not respond. User merged PR #61
  directly. Full narrative, evidence, and what's believed-not-verified:
  `.syndicate/log/2026-08-25.md`; deploy measurements: `.syndicate/deploys.md`.
- Blocked by: none. All deploy claims released (`deploy_claim.py status`: all
  four services free).

### kalshi-line-aware-rungs — OPEN — **CLAIMS RELEASED 2026-08-26 03:3xZ, session archived** — BLOCKED ON TWO MEASUREMENTS, do not resume the original goal first — opened 2026-08-25 — session 281da8c3-1df9-5c77-9e34-ee6f15f37b45 (GONE)

- **CLAIMS RELEASED. The files below are FREE to take.** The lane stays OPEN
  because real work remains, but no live session holds it — do not treat the
  `Files:` list as a lock. Whoever picks this up should re-claim what they need.
  Nothing here is uncommitted: tree clean at `d2d44dbaf`, all shipped code live
  under `34717822`.

- **Files:** `tests/test_kalshi_odds_cadence.py`,
  `tests/test_kalshi_precap_cut_by_date.py` (NEW),
  `syndicate/features/shared/kalshi_board.py`, `tests/test_kalshi_board.py`,
  `syndicate/features/shared/kalshi_catalogue.py`,
  `tests/test_kalshi_side_vocabulary.py`, `tests/test_kalshi_futures_eviction.py`.
  **`venue_quote_adapters.py` and `venue_quote_fanin.py` RE-CLAIMED by lane
  `venue-quote-line-join` 2026-08-27** (and `kalshi_odds_refresh.py` likewise on
  2026-08-27, for the per-sport trim floor), exactly as the released-claims note
  above instructs. Removed from this list rather than left contested, because
  `check_lane_invariants.py` reads it as a live claim and reported them as
  two-holder violations.
- **SHIPPED AND VERIFIED (evidence in `log/2026-08-26.md`, rows in `deploys.md`):**
  side vocabulary; futures eviction; `board_by_game_date` on the ticker's game
  date with `BY_CLOSE_DATE` alongside; ticker zone settled Eastern;
  `PRECAP_CUT_BY_DATE`. All live under `34717822`.
- **FOUR HYPOTHESES KILLED, none by argument:** (1) "the working set holds
  nothing for the board's date" — refuted, 1958 markets on it; (2) NCAAF has no
  game on the board's date — true but NOT binding, the join's board side has no
  NCAAF rows at all **[NOW STALE, 2026-08-27: NCAAF reaches the board side.
  The Layer 2 projection-window fix `5e6ef685` admitted it to the candidate set,
  and `VENUE_REPRICE` read `sports=['ncaaf', 'soccer', 'wnba']` at 02:56:06Z with
  `ncaaf` unmatched at only 62. A successor re-deriving this lane's numbers must
  re-measure rather than inherit them]**; (3) `market_is_for_another_date` is a defect — it is a
  description; (4) eviction re-prioritisation recovers ~1,600 markets — measured
  **133**.
- **BLOCKED ON, in order. Do NOT write an eviction change before both:**
  1. `PRECAP_CUT_BY_DATE` taken **during a live slate**. The `03:11Z` reading is
     post-slate and systematically understates it (`KXMLBHRR` cut 747 at 01:49Z,
     132 at 03:11Z). Code is already live; this needs only a reading.
  2. The **outer `MAX_STORED_MARKETS` trim dated the same way**. `cut_total=3940`
     vs `TICK trimmed=8744` — ~4,800 markets are cut by a second date-blind bound
     that nothing dates.
- **THEN, and only if those numbers support it:** line-aware rungs, the lane's
  original goal. Currently unjustified.
- **Largest addressable bucket is now `no_matching_board_row=1838`**, not the
  date bucket. Any successor should start there.

### kalshi-spread-join-sign — **OPEN (reopened 2026-08-26)** — session syndicate-43 (ENDED) — UNOWNED — six things verified; WNBA settlement is BUILT, LANDED and NOT DEPLOYED
- Note: this lane was CLOSED earlier on 2026-08-26 and its block correctly moved
  to `lanes_history.md`. Work continued after that close, so this is a fresh
  block for what is still OWED — the history entry stays as the record.
- Files: `syndicate/features/shared/{kalshi_board_join,kalshi_orders,bet_status_wnba,bet_status_soccer,polymarket_us_orders,board_enrichment}.py`,
  `scripts/build_wnba_boxscores.py`,
  `syndicate/blueprints/wnba.py` and their tests. **ALL CLAIMS RELEASED.**
- Claim reconciliation `[2026-08-27, USER DECISION]`: the intelligence-state
  pipeline module was REMOVED from the `- Files:` line above by lane
  `board-cycle-overview-throughput`. This lane already said ALL CLAIMS
  RELEASED and its session (syndicate-43) has ENDED, but the invariant checker
  parses that line literally and cannot read prose, so the path still
  registered as a live claim and reported CONTESTED. Striking it makes the
  machine-readable claim agree with what this lane already states. None of the
  five OWED items below involve that module.
- VERIFIED (evidence `log/2026-08-26.md`, measurements `deploys.md`): Kalshi
  shard 3 funded (3 MLB fills, `exchange_index=3`) · spreads join sign (15 of 30
  inverted -> 0) · spreads PLACE correctly (`AZ2` home -1.5 -> YES, filled
  3 @ 0.33, venue title matches the row) · WNBA id barrier
  (`game_not_in_live_box` 9 -> absent, graded 0 -> 3) · soccer per-league read
  (`no_soccer_live_state_for_date` -> `match_not_in_soccer_live_state`) · ESPN
  host split (`{"ok":true,"games":3}` after the swap; 403 minutes before).
- **OWED, in priority order:**
  1. **DEPLOY refresh-worker, THEN read `SETTLED date=2026-08-25`.** All code is
     on `origin/main`; the worker was NOT deployed (preflight HOLD, jobs
     climbing 1 -> 10). `not_decided_yet: 6` is UNCHANGED and still reflects the
     ESPN 403. PASSES only if it falls below 6 and Citron (1 reb vs over 3.5) /
     Amoore (3 ast vs over 3.5) grade **LOST**. **DO NOT REPORT WNBA SETTLEMENT
     AS FIXED BEFORE THAT READING** — and treat its all-time `win 100%` as
     wins-only by construction until a loss can settle.
  2. **Re-do the 2026-05-25..08-26 backfill through the KEYVALUE store.** The 84
     files published via `/api/ops/artifacts/publish` sit on WEB'S FILESYSTEM
     while the consumer reads keyvalue on refresh-worker — in production and
     invisible to settlement. `build_wnba_boxscores.py --via-web --start --end`
     run ON a worker lands in the right place.
  3. **Soccer: still 0 settled all-time.** The read is fixed; needs an order
     whose match finished with finals captured after 2026-08-26T16:11Z.
  4. **Polymarket side resolution UNRESOLVED.** `over`->YES/`under`->NO is a
     fixed constant while the price comes from the name-matched index, and the
     `outcomes` array orientation VARIES per market. A cross-check guard was
     built and REVERTED — it silently enthroned the positional reading, the
     disputed question, and contradicted three deliberate tests. Needs venue
     ground truth (Polymarket US credentials, on Render; the env read was
     blocked by the permission classifier). `FILL_ABOVE_LIMIT` ships as
     detection only.
  5. **33 pre-existing test failures** in the soccer/board selection, confirmed
     NOT caused by this lane (identical counts with and without the change).
     `test_team_aliases.py` is 9 of them and the soccer join leans on it.
- Blocked by: none

### wnba-chip-live-token — OPEN, **UNOWNED** (session 3dcd0fb2-a129-4c6a-95f2-29b11ea0d272 checkpointed and ARCHIVED 2026-08-27) — opened 2026-08-27 — **CLOCK FIXED AND VERIFIED IN PRODUCTION (web `e3dceb68`): `LIVE` -> `Q3 20.5`, control and after on the same game against ESPN. TWO THINGS OWED — refresh-worker is not deployed, and the projection guard is UNIT-TESTED ONLY. `todo.md #586`.** **CHECKPOINT 2026-08-27T01:2xZ: refresh-worker reached `070f452a` and DOES carry the fix; the WNBA half is owed on a MISSING SUBJECT, not a missing deploy — `WNBA live=0` when the artifact landed. Next window TOR @ SEA `02:00Z`. Session archived; lane UNOWNED.**
- Goal: a live WNBA game chip carries its QUARTER AND CLOCK (`Q3 5:23`) instead
  of a bare `LIVE`, and never renders a SmartSim projection as an observed score.
- Files: `tests/test_home_wnba_live_state.py`
- **`syndicate/blueprints/home.py` IS NOT LISTED ABOVE ON PURPOSE `[2026-08-28,
  session 3e5a9659]`.** Its claim moved to `soccer-overview-cost` for
  INSTRUMENTATION ONLY — per-league timing inside the soccer games loop, no
  behaviour change, nothing near the WNBA chip/live-token work this lane owns.
  Taken because this lane is marked UNOWNED (session 3dcd0fb2 checkpointed and
  ARCHIVED 2026-08-27). To reclaim, put the path back on the `- Files:` line.
  **THE PATH IS REMOVED RATHER THAN STRUCK THROUGH** because
  `check_lane_invariants.py` parses paths POSITIONALLY and a `~~struck~~` path
  is still a live claim — that is a standing rule in `learnings.md` and I broke
  it here first, producing a false contest between two OPEN lanes.
  — RELEASED (see the note below) — `game_chip_scoreboard.py` was ADDED here
  after the first test run, because refusing to SET a fractional score in
  `home.py` was not enough: `_side_score` falls through to
  `live_state.<side>_pts` and picks the projection back up.
  — **RELEASED: `syndicate/features/shared/game_chip_scoreboard.py` IS NO
  LONGER LISTED ABOVE, ON PURPOSE `[2026-08-28, session 28195565, user
  authorised]`.** Its claim moved to `mlb-final-zero-placeholder` for the
  0-0 placeholder branch
  inside `build_game_chip` ONLY — the code that runs AFTER `_side_score`
  returns. **`_side_score` and its `live_state.<side>_pts` fallthrough — this
  lane's actual subject — are UNTOUCHED, as is everything WNBA.** Taken because
  this lane is UNOWNED (session 3dcd0fb2 ARCHIVED 2026-08-27) and an MLB
  scoring defect traced to that branch: a 0-0 schedule placeholder on a game
  whose status had advanced to FINAL was passed through as an observed result.
  **THE PATH IS REMOVED RATHER THAN STRUCK THROUGH**, for the same reason the
  `home.py` note above gives — a `~~struck~~` path is still a live claim to
  both `lane-guard.py` and `check_lane_invariants.py`, which read positionally.
  (Confirmed here: the guard's disclaimer vocabulary is a fixed list —
  `not claimed`, `released`, `held by`, `claimed by`, … — and "TRANSFERRED" is
  not in it, so a prose transfer note alone releases nothing.)
  **CONSEQUENCE, stated plainly: the guard now protects this file for NEITHER
  lane.** There is no way to express a per-branch claim to it. To reclaim, put
  the path back on the `- Files:` line.
- Hypothesis — **CONFIRMED FROM PRODUCTION BEFORE WRITING ANY CODE**, via
  `/api/ops/wnba/status-trace?date=2026-08-26`. `local_live_state_payload` (what
  `build_live_state_payload` returns, i.e. `live_row`) carries everything needed:

      {"away_pts": 65.0, "home_pts": 38.0, "in_progress": true,
       "period": 3, "clock": "5:23", "status": "5:23 - 3rd"}

  `_apply_wnba_live_scores` builds `live_state` from FIVE keys — `away_pts`,
  `home_pts`, `in_progress`, `final`, `status` — and **drops `period` and
  `clock` on the floor**. `_live_status_token`'s generic branch reads exactly
  `live_state.period` / `live_state.clock`, finds nothing, returns None, and the
  chip falls back to the bare `LIVE` string. Nothing is missing upstream.
- Second defect, same function, same class: **`#160`'s guard is insufficient.**
  `cards.py`'s live-state row falls back to the SmartSim PROJECTED point total
  when no real ESPN boxscore row has matched. The guard gates on
  `in_progress or final` — i.e. on the GAME's state, not on whether the number
  is an OBSERVATION. A live game with no matched boxscore therefore passes the
  gate carrying a projection. That is the user's reported `GSV 85.43 / CON 68.94`
  rendered where a score goes. A real basketball score is a whole number.
- Falsification test: if `local_live_state_payload` rows carried no `period`, the
  data would be missing upstream and this fix would be inert. Checked on
  production: `period: 3`, `clock: "5:23"`, both present on the live game.
- Verification: on a live WNBA slate, `/api/board/game-chips?sports=wnba` returns
  `status_token` matching `^Q\d+ \d+:\d\d$` rather than `LIVE`, and no chip
  carries a non-integral score. Plus a unit test built on the production row
  above that FAILS pre-change.
- Blocked by: none. `wnba/cards.py` is claimed by `wnba-halftime-elapsed` and is
  NOT touched — the whole fix is in `home.py`, which this lane claims and which
  `mlb-chip-live-state` released on closing.

- **VERIFIED** `00:34:02Z` on `inline_artifact_stale`, the path `e3dceb68` is
  deployed to:

      CONTROL  00:29:37Z  GSV @ CON  token='LIVE'     76-48  ESPN P3 1:13  76-48
      AFTER    00:34:02Z  GSV @ CON  token='Q3 20.5'  80-52  ESPN P3       80-52

- **OWED 1 — refresh-worker is on `f8d8b05f` and does NOT carry this.** It builds
  the published chip artifact, so while a fresh one is served the WNBA chip is
  still bare: observed `00:32:49Z`, `src=worker_artifact`, `tok='LIVE'`. Claim
  held by `ncaaf-opener-regions-props`; they offered to release and it was
  DECLINED, because the inline path already proved the fix and their NCAAF
  capture was time-bound. Discharge by reading a WNBA chip on
  `src=worker_artifact` once that service carries `07a7124e` or later.
- **OWED 2 — the projection guard is UNIT-TESTED ONLY and must not be recorded as
  production-verified.** GSV @ CON had a matched ESPN boxscore all evening, so the
  fractional `85.43` path never fired. It needs a game that has tipped off before
  its boxscore row matches.
- **MY OWN VERIFIER RETURNED A FALSE NEGATIVE ON THE PASSING RUN.** The assertion
  assumed a `M:SS` clock; ESPN's `displayClock` under a minute is `20.5`, so a
  CORRECT token printed `STILL BARE`. The raw value settled it. Second instance
  the same night of a watcher summary disagreeing with what it was built to
  check — the other ran the opposite way at `00:08:34Z`.

### nfl-soccer-props-board — **CLOSED 2026-08-27** — session 3515d143 — **GOAL MET AND VERIFIED ON THE SERVED SURFACE.** NFL cards 0 -> **112 `shared_prop_rows` across 14/16 games** (web `e3c168f3`). Both captures multi-book on post-fix files: NFL wk1 **294 rows/1 book -> 556/4 books**, soccer ligue_1 **2,720 rows/4 books, 647 of 1,529 selections multi-quoted**. Narrative + evidence: `log/2026-08-27.md`. STILL OPEN ELSEWHERE, not this lane: `/nfl/api/props` serves rows=0 while the CARDS read the same file fine (downstream of the read path, not `#441`); and nobody has measured whether the ROI number MOVES now that a best price exists to pick.
- Goal: NFL cards serve non-zero `shared_prop_rows`, and BOTH sports' prop CSVs
  carry every book instead of one. Two defects, ported from what
  `ncaaf-opener-regions-props` measured, but only after checking each one
  against production rather than assuming the NCAAF shape transfers.
- Files: `syndicate/features/nfl/cards.py`, `syndicate/features/nfl/props.py`,
  `syndicate/features/nfl/sources.py`,
  `scripts/fetch_nfl_oddsapi_props_local.py`,
  `scripts/fetch_soccer_oddsapi_props_local.py`,
  `tests/test_nfl_props_board.py` (new),
  `tests/test_props_multi_book_capture.py` (new),
  `tests/test_nfl_props.py`, `tests/test_backtest_nfl_props.py`,
  `tests/test_nfl_market_board.py` (all three patched a function the code has
  stopped calling, or pinned behaviour this lane deliberately changed).
- Deliberately NOT claimed (stated outside `Files:` so the invariant checker
  does not read an exclusion as a claim): the shared artifact publisher, held by
  OPEN lane `nfl-fantasy-projections` — no allowlist edit is needed, because the
  NFL props path is already ALLOWED and soccer's per-league props path tested
  ALLOWED against `is_hot_artifact_relative_path` rather than against the
  pattern text. Also not claimed: any NCAAF path (OPEN lane, another live
  session), and the NFL roster/depth-chart builders (claimed) — that artifact is
  READ, never rebuilt.
- Hypothesis: NFL's `shared_prop_rows: 0` is the CARD ATTACH alone, not capture
  and not delivery. `cards.py:381` leaves `prop_recommendations` unset because
  prop rows carry no player→team side; that reason was true when written and is
  now stale, because a real per-player team source is already on web's disk.
- Falsification test: if the NFL wk1 props artifact on web were absent, empty,
  or whole-second-mtime (a boot copy), the zero would be delivery and the attach
  would be inert. MEASURED 2026-08-27 and the hypothesis SURVIVED:
  `nfl_source/oddsapi_player_props_2026_wk1.csv` = **42,753 B**, mtime
  `2026-08-26T23:06:02.931697Z` — FRACTIONAL, a runtime write. 294 rows,
  259 distinct players, 16 distinct events. Also falsifiable and NOT falsified:
  `team` is empty in **0/294** rows, so the split genuinely cannot come from the
  feed; `roster_2026_snapshot.csv` (654,176 B) and `roster_2026.csv` (926,867 B)
  ARE both present on web, so it can come from there.
- Second defect, measured not inferred: the live NFL capture is
  `{draftkings: 294}` — ONE book of N, via `_choose_bookmaker`. Soccer sweeps
  every book in `_ordered_bookmakers` but `parse_event_to_rows` folds to one
  `book_key` per (player, line), so its CSV is one-book too. Price shopping is
  already measured at **+2.95 ROI pts on NFL props** and cannot run off either
  file. NCAAF's same fix gave 5.5x the rows for identical credits.
- Verification: (a) `sum(len(g["shared_prop_rows"]) for g in
  GET /nfl/api/cards?week=1)` goes **0 → >0** on the SERVED board, with a
  spot-checked player attributed to the team the roster says, not the team the
  event string implies. (b) both CSVs carry >1 distinct `book` for at least one
  (player, line) after a real capture, with the row count and credit delta
  recorded. A local-fixture pass does not discharge either.
- Blocked by: none.


### venue-quote-line-join — OPEN, **UNOWNED** (session 3515d143 archived 2026-08-27 ~21:45Z; ALL CLAIMS RELEASED, worktree clean, nothing uncommitted) — **SIX DEFECTS FIXED AND VERIFIED IN PRODUCTION; ONE CHANGE RECORDED AS UNPROVEN; TWO NAMED AND UNFIXED.** Verified: soccer unmatched **15,348 -> 4,006**, grid stamped **13.1% -> 66%**, prop keys now name their player (was a cross-sport WRONG-PLAYER match), kalshi quotes carry a price at all (`yes_bid` was never persisted) and both legs of a threshold market, NFL nicknames resolve (`clubs_unresolved` 64 -> 0), per-sport trim floor, and the venue poll on its own thread (kalshi ~1,250s -> ~120s, polymarket 428-828s -> ~120s). **UNPROVEN: the demand-weighted trim.** Allocation IS the binding constraint (`matched` tracks mlb slots: 794/27, 1620/208, 1741/218, 1706/221) but today's recovery came from MLB's slate approaching first pitch, NOT from the change -- the trim behind `matched=208` logged `demand=None`. **Its test is tomorrow MORNING CT, sustained; the morning was noisy (146/210/99 against a 5-27 baseline) so one good reading is not evidence.** I recorded 'supply not allocation' and had to RETRACT it -- see `deploys.md` 21:0xZ correction. **UNFIXED: a TOTALS key names no GAME** (672 polymarket soccer quotes -> SIX distinct keys, same class as the player-blind props); and the `842`-row builds match 0 on the COMPLETE set, never confirmed as a benign future-date board. Full narrative: `log/2026-08-27.md`.
- Goal: reduce `VENUE_REPRICE_KEYS unmatched_by_sport` for nfl/soccer/ncaaf by
  fixing key-shape mismatches that are PROVEN, and instrumenting the rest.
  Explicitly NOT "make the number go down" -- a wrong match on this path prices
  a real bet against the wrong contract.
- **CLAIMS RELEASED 2026-08-27 at session archive.** Every file this lane held
  is FREE to take — the work in all of them is landed and deployed, so holding
  them would only contest files with live lanes, which is what
  `kalshi-line-aware-rungs` released to me this morning for the same reason.
  Paths deliberately NOT written here: `check_lane_invariants.py` parses any
  backticked path inside a `- Files:` block as a live CLAIM. Former set is in
  the git history of this block and in `log/2026-08-27.md`.
  Whoever resumes this lane should re-claim what they actually need.
- **RELEASED 2026-08-27 at checkpoint: the live-odds worker entrypoint.** My work
  in it (the venue poll thread) is LANDED and DEPLOYED, so holding the claim only
  contested it with OPEN lane `open-bet-live-status`, which is live and holds the
  refresh-worker deploy claim. Path deliberately not written on this line —
  `check_lane_invariants.py` reads any backticked path inside a `- Files:` block
  as a live claim, which is the convention `wnba-live-odds-capture-gap` used when
  it released the same file to me.
  The live-odds worker was formerly referenced by `wnba-live-odds-capture-gap`,
  which RELEASED its claim and deliberately stopped writing the path so the
  invariant checker would stop reporting it contested. Taken here per that
  lane's own instruction.
- **SECOND CAUSE FIXED 2026-08-27, found by the diagnostic this lane shipped.**
  Polymarket sends BARE NFL NICKNAMES; `canonical_team` resolved tri-codes and
  full names but not nicknames, so 2,048 nfl quotes carried
  `clubs_unresolved:64:['49ers','Bears','Bengals','Bills','Broncos','Browns']`.
  `venue_quote_adapters._polymarket_sides` predicted this in a comment -- "the
  day it sends nicknames instead, this counter is the difference between a
  visible alias-map gap and a feed that quietly halves". Nicknames are now
  DERIVED from the alias map's own values (not a second hand-maintained list --
  that is the drift this module exists to prevent) and ambiguous ones are
  dropped: nfl +32/0 dropped, mlb +27/1 dropped ("Sox"), nba +26, wnba +0.
- Hypothesis: OddsAPI's spreads/totals quotes are published WITHOUT a line, so
  they can never meet a board key that correctly carries one.
- Falsification test: if the shard's key carried `line=`, the adapter was right
  and the mismatch is elsewhere. NOT FALSIFIED -- the module's own measured
  comment records the key shape and it has no `line=`, while the value carries
  `last_line`; production `sources_offered` shows `soccer|totals|over`, a total
  with no number, which is not a bet.
- SAFETY: the fix cannot create a wrong-line match. These keys match NOTHING
  today; afterwards they match only a board row at the SAME number. Pinned by a
  test asserting a 3.5 quote still fails a 2.5 row, and by a parametrised h2h
  guard (h2h/h2h_h1/h2h_h2) so the family that already matches cannot regress.
- Verification OWED, on production after a deploy: `unmatched_by_sport` for
  soccer falls from its 11,365 plateau, `selected_by_source` gains `oddsapi` on
  spreads/totals, and `lined_market_without_line:<n>` names whatever residual
  remains. A drop with no oddsapi selections would mean rows vanished rather
  than matched, and would NOT count.
- Deliberately NOT done: aliasing Kalshi's `totals_q1`/`totals_h1` onto
  full-game board rows. If those are real period markets that match prices a
  full-game bet against a first-quarter contract. Kalshi also registers ONE
  series each for nfl/ncaaf (`KXNFLTOTAL`/`KXNCAAFTOTAL`) vs 14 mlb / 7 wnba --
  a registry boundary, not a key defect.
- **THIRD AND LARGEST CAUSE, 2026-08-27: soccer's unmatched rows are ALL player
  props, and the join key did not name the player.** `_candidate_keys` built
  `<sport>|<market>|<side>|<line>` for every row -- complete for a game line,
  and wrong for a prop: every player's anytime-scorer row collapsed to ONE
  string. Rows sharing a key are indistinguishable to `apply_venue_quotes`, so
  the first won and the quote it won described a DIFFERENT HUMAN. That is a
  latent cross-sport defect (wnba `player_threes|over|2.5` had the same shape),
  not a soccer one. `kalshi_board_join` has always keyed props as
  `market|normalize_person(subject)|line`; the fan-in now uses that same
  resolver. Fixed on BOTH sides plus the kalshi adapter, so its prop quotes move
  with the board rather than silently ceasing to match.
- **AND THE CAPTURE HAD NO READER.** `oddsapi` is in `SOURCES` but its adapter
  reads the `odds_history` shard -- game lines only, 44 soccer quotes at 26,886s
  old. The SAME vendor's player props are captured every pregame sweep to
  `soccer_source/<league>/props/<date>.csv` (2,720 rows / 4 books on the real
  2026-08-27 ligue_1 file, 647 of 1,529 selections multi-quoted) and nothing in
  the fan-in opened them. New source `oddsapi_props`, default-on, soccer-only
  with other sports refused BY NAME. Vocabularies already agreed: the CSV's
  `market_key` IS the board's market token.
- Verification OWED on production: soccer `unmatched_by_sport` off its 15,082
  plateau AND `selected_by_source` gaining `oddsapi_props`. A drop without that
  source appearing means rows vanished rather than matched. Also expect kalshi's
  prop selections to CHANGE -- some of what it won before was the wrong player,
  so a fall there is a correction, not a regression, and `prop_without_player`
  names what it could not key.
- **VENUE ROBUSTNESS `[2026-08-27, user ask: kalshi/polymarket on a 30-60s
  cadence with line-move tracking]`. TRIM FLOOR DONE; CADENCE IS NOT AN ENV
  CHANGE AND I SAID TWICE THAT IT WAS.**
  - Line-move tracking ALREADY EXISTS: `venue_daily_odds.record_daily_odds`
    keeps ~10 days, per sport, with movement. The 6,000-market artifact is the
    JOIN'S WORKING SET, not the record.
  - **Corrected twice, both times before setting a variable that would have
    done nothing.** `SYNDICATE_POLYMARKET_REFRESH_INTERVAL_SECONDS` governs
    `_polymarket_catalogue_at_boot()` -- boot only, `force=True`. Kalshi's
    refresh is called once per BOARD BUILD (~3min claimed, ~748s measured), so
    its 120s interval can never fire faster than its caller asks. And the live
    worker's loop is ADAPTIVE: `_live_refresh_loop_interval_for_meta` returns
    the IDLE interval (~900s) whenever no game is live, and BOTH venue ticks
    ride it -- so even `SYNDICATE_POLYMARKET_US_SLATE_INTERVAL_SECONDS=60` is
    inert while idle.
  - **What 30-60s actually needs:** a venue poll independent of the live-refresh
    loop's adaptive interval. The idle interval exists to avoid expensive
    per-sport work when nothing is live; exchange prices are free and move
    continuously, so they do not belong behind that gate. NOT BUILT -- it is a
    new loop and a design decision, not a tweak.
  - **DONE: per-sport floor in the kalshi trim.** Freshest-first was the right
    ORDER and the wrong BUDGET -- MLB's 14 series can fill all 6,000 slots and
    evict soccer entirely, which is the intermittency measured today (173
    quotes -> 0). `_trim_to_storage_bounds` extracted from a 200-line function
    so it could be tested at all; the first test written against it had to
    `skip`, which is the green-and-proves-nothing failure this lane keeps
    naming. 7 tests, 4 fail without the floor.
  - HARD CONSTRAINT, recorded so nobody designs past it: the keyvalue store
    REFUSES at 8MB and `layer2_shortlist` already holds 5.7MB. A 13.3MB write
    was once rejected outright and the artifact stopped being written at all.
    Polling faster is free; KEEPING MORE is not.
- **`[2026-08-27, USER DECISION]` KALSHI AND POLYMARKET ARE THE FOUNDATION OF
  LAYER 1 AND LAYER 2, NOT A SIDE INPUT.** Verbatim intent: they should be
  artifacts continuously updated to track odds/line movement for pregame, live
  AND props, and the boards should be built on them. OddsAPI stays because it
  is where effective EV data comes from -- but it COSTS MONEY PER CALL and the
  two exchanges do not, so cadence spent on the exchanges is close to free and
  cadence spent on OddsAPI is rationed. That inverts the assumption the venue
  path was built under, where OddsAPI was the spine and the venues were an
  optional reprice.
  - Set to a 120s cadence on that basis (not 60s): 60s was measured at ~95s
    polymarket / ~122s kalshi actual, and the polymarket slate write is 5.15MB,
    so 60s cost ~194MB/hour of keyvalue IO against ~21MB/hour before. 120s
    keeps roughly a 5-7x freshness gain at half that IO, on a worker already
    measured at 95.1% of its 2GB.
  - NOT YET DONE, and it is the real work this decision implies: Layer 1/2 read
    OddsAPI as the spine and treat venue quotes as a reprice applied afterwards
    (`_reprice_grid_from_venues`). Making the exchanges the FOUNDATION is an
    ordering change in the board build, not a cadence change, and it is not
    something to slip in behind a diagnostics fix.
- Blocked by: none. Nothing armed; `SYNDICATE_EXECUTION_*` untouched.



### ncaaf-pace-block — OPEN — NCAAF calibration re-fitted and PROMOTED (15.00% -> 7.24%, impossible drives 159 -> 0); NFL deliberately NOT re-fitted (best as shipped); production read of the profile still owed — opened 2026-08-27 — session de363735
- Goal: the NCAAF `pace` block carries a REAL per-team seconds-per-play, so the
  engine stops running every game on the hardcoded 24.0 (`pace_index +0.400`).
- Files: `scripts/build_ncaaf_pace_snapshot.py`,
  `syndicate/features/ncaaf/feature_payload.py`,
  `syndicate/features/ncaaf/sources.py`,
  `tests/test_ncaaf_pace_payload.py`
- Hypothesis: the totals over-dispersion (`1.94x`, measured on the live slate)
  is driven in part by pace. MEASURED, not assumed: with no pace block the
  engine runs 151.6 s/drive while the league-average team is 179.5 — ~18% too
  fast, so more drives fit in a game and totals inflate. `drive_success_
  probability` is unchanged across the whole pace range (0.3270), so the effect
  is cleanly isolated.
- Falsification test: if a re-fit with the pace block ON does not reduce TOTAL
  error against the market, pace is not the driver and the block stays off. The
  correlation study already showed these payload features carry NO information
  the market misses on margin (residual |r| <= 0.021, n=690) — pace is being
  tried because it targets a surface the model is KNOWN to get wrong, not
  because an edge is expected.
- Verification: (a) reachability, off != on, already demonstrated across the
  real range 21.0..33.4 s/play; (b) per-team coverage reported as a RATE over
  FBS teams, not a count; (c) a re-fit reporting TOTAL error, not just margin.
  DONE separately and verified on production: projections 0/51 -> 51/51, strip
  435px -> 181px uniform with crests, live lens state-aware. NOT verifiable in
  production: `_EngineRowProjection` (cards route takes a WEEK only; 2026 has no
  engine rows) and the live lens under real in-game data (no game until Sat).
- Blocked by: none. Ships DEFAULT-OFF behind the existing payload flag — the
  profile was calibrated with pace_index pinned at +0.4, so turning this on is
  a mechanism added to a calibrated engine and owes a re-fit before any deploy.

### board-cycle-overview-throughput — **CLOSED 2026-08-27** — overview fix VERIFIED IN PRODUCTION; throttle half FAILED ITS BAR and bought nothing
- OUTCOME: `sports=0` -> `sports=7` on every memory-refused build, confirmed on
  refresh-worker `b8163ef0` (live 17:02:59Z) by four paired readings at
  18:01/18:17/18:47/18:58Z — guard fires on MLB, the other seven build, MLB
  absent from the list. Pre-fix the identical guard line gave `sports=0`
  eighteen times running. Control holds: the four non-firing iterations read
  `sports=8` with MLB present, so the gate in front of MLB is not relaxed.
- **HALF THE GOAL WAS NOT MET.** The next-day throttle (300 -> 1800s) works as a
  MECHANISM — future-date builds went ~7 min -> ~30 min apart — but today's
  SHARE of iterations is unchanged at 50% (5 today / 4 on 08-28 / 1 on 08-29
  over 127 min, vs a 9/9 baseline). The `>=4:1` bar was unreachable: the board
  window is THREE dates, not two, and the overview fix slowed each build 150s ->
  534s, so there are far fewer builds to redistribute. **The two changes
  interact and I did not predict it.** The throttle bought nothing measurable.
- NET: today's board went from rebuilt every ~7 min with `sports=0` (never
  actually built) to every ~25 min with `sports=7`/`sports=8`. Slower and real,
  instead of fast and empty. Entirely attributable to the overview change.
- Shipped `6421bf7f`, which RODE ALONG on another lane's `b8163ef0` — not a
  deploy of mine; my claim was released at 16:47Z, before it.
- Measurements: `deploys.md 2026-08-27 19:1xZ`. Narrative: `log/2026-08-27.md`.
- FOLLOW-UP left open, no lane: if today's absolute cadence matters more than
  correctness-per-build, the lever is the 534s overview itself (MLB's
  `build_cards_page_context` hydrated on the worker), NOT the throttle.
- Claims: NONE held. Deploy claims: released.

### polymarket-catalogue-pagination — **CLOSED 2026-08-27** — paginator fixed and verified against the LIVE API; the dead boot call is handed off, not dropped
- OUTCOME: `fetch_markets` no longer presents a server-capped first page as the
  whole catalogue. Gamma caps page size at 100 and ignores a larger `limit`
  (measured live: asked 100/200/500 -> 100 rows each); the loop broke on
  `len(page_rows) < limit` with a default limit of 200, so it always stopped
  after page one and reported `truncated=False`. Production had
  `POLYMARKET_CATALOGUE count=100 truncated=False` on all ten boots in 17h.
- VERIFIED AGAINST THE LIVE API, not only mocks: 100 markets / 1 page /
  `truncated=False` before; **600 markets / 6 pages / 0 duplicate ids /
  `truncated=True`** after (`max_pages=6`). 3 of 4 new tests fail against the
  prior loop, confirmed by reverting it. Shipped `6d520b03`.
- THE TRAP, recorded because a naive fix is WORSE than the bug: advancing
  `offset` by `limit` (200) against a 100-row cap steps 0/200/400 and never
  reads rows 100-199 of each stride. The stride must be what came BACK. A test
  asserts the exact offsets requested.
- ALSO FOUND: Gamma has a hard offset ceiling — 1000 and 2000 return 100 rows,
  3000+ returns HTTP 200 carrying `{"type":"validation error","error":"offset
  too large, use /markets/keyset for deeper pagination"}`. Now raises a named
  `gamma_refused`; deeper paging is a different ENDPOINT, not a bigger
  `max_pages`. Documented there.
- IMPACT WAS LATENT, NOT LIVE, and is stated that way deliberately: the only
  production caller is a boot diagnostic on a SUPERSEDED path (global gamma
  exchange; the funded venue is `api.polymarket.us` via `polymarket_us_markets`,
  which `portfolio_commit` already uses at ~17,299 markets). Nothing was
  mispriced. This was a shared client lying about completeness to future callers.
- HANDED OFF, NOT DROPPED: retiring the dead `_polymarket_catalogue_at_boot()`
  hook needs `scripts/run_live_odds_refresh_worker.py`, claimed by OPEN lane
  `open-bet-live-status` (session syndicate-27), re-measured 2026-08-27 as LIVE
  not stale. Messaged them with the evidence AND a warning that this fix changes
  that hook's log shape — `count=100` becomes hundreds/thousands and it now costs
  ~20 requests per boot instead of 1, which strengthens the case for removal. A
  bigger number there does NOT mean the hook became useful; it is still the wrong
  exchange and still cannot feed an order.
- **RETRACTED — I reported 5 pre-existing failures in
  `tests/test_polymarket_board_join.py`. THERE ARE NONE. `53 passed` in the
  primary tree.** They were an artifact of a data-less session worktree: those
  tests resolve soccer clubs through an alias map BUILT FROM `data/` artifacts,
  which `session_worktree.py` excludes. Already a standing rule
  (`learnings.md` 2026-08-21, `978963b5`) that I failed to apply.
  THE METHOD ERROR IS THE LESSON: I "verified" by stashing my diff and
  re-running. Stashing does not restore `data/`, so BOTH ARMS were missing the
  same thing. That proved the failures were not caused by my diff; it could not
  prove they were REAL, and I reported the weaker result as the stronger one.
  I also wrongly attributed them to `b8163ef0` on topic adjacency alone — every
  commit here is `github-actions[bot]`, so authorship distinguishes nothing and
  I had no basis. Attribution removed, not reassigned. Caught by
  `venue-quote-line-join` (syndicate-82), confirmed by me.
- Claims: NONE held. Deploy claims: none taken — this needs no deploy of its own.

### rail-league-label - **CLOSED 2026-08-27T20:1xZ.** `#590`: the rail head label is the chip's league now, not whichever row arrived first. Verified on the SERVED bytes (web `0e964af8`). No claims. Body moved VERBATIM to `lanes_history.md` 2026-08-27; evidence in `deploys.md` + `log/2026-08-27.md`.
### board-card-league-label - **CLOSED 2026-08-27T20:4xZ.** `#591`: the board-card subtitle joins the chip too, and `data-syndicate-sport` stopped carrying a league onto the bet-slip/ledger path. Verified on the SERVED bytes (web `fb9261b8`). No claims. Body moved VERBATIM to `lanes_history.md` 2026-08-27; evidence in `deploys.md` + `log/2026-08-27.md`.
### refresh-worker-deploy-2026-08-27 — **CLOSED 2026-08-27** — deployed, verified PARTIAL, claim released
- OUTCOME: `fb9261b8` live on refresh-worker 20:42:05Z. `no_match|wnba|h2h` 7 -> 0 and `matched` 52 -> 60 on an identical `board_rows=1344`. The alias class-fix is CONFIRMED in production.
- **MY ~22-ROW ESTIMATE WAS OPTIMISTIC; actual recovery ~8.** `totals` also requires the LINE to match, so an alias fix is necessary but not sufficient there — `no_match|wnba|totals` moved only 15 -> 14. Inferred cause, not measured.
- Preflight HELD on first run (2 odds jobs in flight, a deploy kills them), CLEAR 24s later. Deployed against the CLEAR for the exact SHA.
- Measurement: `deploys.md 2026-08-27 20:42:05Z`. Claims: released.

### boot-sync-healthcheck-kill — OPEN — opened 2026-08-27 — session 64625b4d
- Goal: a web boot must not cost the container a long blocking file walk, so
  sync I/O cannot starve `/healthz` inside Render's 5s budget.
- Files: `scripts/bootstrap_data_root.py`, `syndicate/app.py`
- Status: **both fixes LIVE.** `188a89fa` (compare depth follows root policy)
  rode in on `d281995b`; `48833112` (boot sync decides from a name set) deployed
  by this lane 21:54:46Z. Boot sync **72.20s -> 0.65s**, reproduced at 0.59s on
  an unrelated lane's next deploy. `present=33316` + `unchanged=76` = 33,392 =
  `git ls-files` over the roots, so nothing was skipped.
- **Open ONLY on the rate.** 2 deploys since the fix, 0 `server_failed`. Against
  a ~1-in-5 base rate that is not yet evidence. Close when >=5 deploys have
  accumulated with no kill — they will arrive from other lanes' work; do not
  manufacture deploys for this.
- Verification: NOT a per-boot `/healthz` trace — that does not discriminate,
  since two PRE-fix boots that survived were equally clean (5.13s, 5.59s). Count
  `server_failed` per deploy over >=5 deploys.
- Not this lane: `GET /` at 8.1s (`home.py`, claimed elsewhere) is the other
  documented route to the same 5s budget.
- Narrative + dead ends: `.syndicate/log/2026-08-27.md`; measurements:
  `deploys.md`; full working block: `lanes_history.md`.
- Blocked by: none.

### portfolio-top-date-filter — CLOSED — opened 2026-08-27 — closed 2026-08-28 — session 39eeef04
- Goal: a date filter at the top of `/portfolio`. `[user 2026-08-27]` Widened by
  the user during the session to: default to today, retire the old selector,
  make the tiles match the date, and fix what that exposed underneath.
- Files: `blueprints/intelligence.py`, `templates/portfolio.html`,
  `features/shared/{venue_order_states,kalshi_orders,polymarket_us_orders,
  venue_settlement,paper_settlement,execution_guard}.py`,
  `docs/ai_context/venue_order_reconciliation.md`, + tests.
- **SHIPPED AND VERIFIED IN PRODUCTION.** web `6a72040b`, live-odds-worker
  `8edf77e5`. Narrative and every reading: `log/2026-08-28.md`; deploy rows and
  measurements: `deploys.md`.
- **CLAIMS: none held.** web and live-odds-worker released.
- **OPEN, and owned by nobody yet:**
  1. **$8.21 of unresolved Polymarket exposure** — two orders on `http_503`
     `{"code":14}`, no `venue_order_id`, so no read available to us can confirm
     or deny them. `probe_unknown_polymarket_positions` now watches those
     markets and will speak if either resolves. **Only the venue UI settles it.**
  2. **Why 7 of 32 resolutions carry `realized=0.0000` is unexplained.** The
     refusal is safe; the cause is not known. `POLYMARKET_RESOLUTIONS` is the
     instrument for it.
  3. Kalshi pagination is **inert at `n=78`** and has never run a real
     multi-page book.
- Blocked by: none.

### venue-refresh-decoupling — **CLOSED 2026-08-28** — both goals shipped and VERIFIED in production; the board build's cost is now 84% named
- OUTCOME (1) INSTRUMENTATION: `_log_stage_timing` was `logger.info`, which never reaches Render — verified in production BEFORE changing it (a logs search for `duration_ms` returned only `[INTEL_TRACE]`; this function's own payload appeared zero times). Now prints as well as logs, plus six new spans. Attribution went **40% -> 71% -> 84%**.
- OUTCOME (2) VENUE DECOUPLING: `pipeline/venue_odds_loop.py`, OFF by default behind `SYNDICATE_VENUE_ODDS_LOOP_ENABLED`. Verified 01:37-01:39Z — both venues refreshed inside 100s of boot on their own clock, where Kalshi's 120s interval had been unreachable against a 680-874s board period and Polymarket had no loop at all.
- FOLLOW-UP SHIPPED: a refresh COSTS 80-143s, so a 120s interval had the loop fetching near-continuously — my sizing error, caught by reading the `elapsed_s` I had just added. Interval 120 -> 300s; measured gaps `median 144s (n=15) -> 302s`.
- **THE READING** (`wall_s=678.8 cpu_s=664.1 off_cpu_pct=2.2`): `build_intelligence_overview` 331.09s (49%) + `candidate_collection_with_fallback` 168.40s (25%) = **73% of the build**. `layer2_shortlist_build` 51.00s. Everything else under 13s: `kalshi_odds_refresh` 12.84, `portfolio_commit` 5.38, `pull_hot_artifacts` 1.15, `kalshi_board_join` 0.91, `POLYMARKET_BOARD_JOIN` 0.25.
- **THREE OF MY OWN HYPOTHESES RETIRED BY IT**: HTTP pulls (1.15s, I had read a 37s log GAP as a cost), the Polymarket join (0.25s, wrong by 3 orders of magnitude), and venue-loop contention (the 865.2s build predates the loop). Detail in `learnings.md` 2026-08-28 and `log/2026-08-27.md`.
- **NEXT LEVER IS OPTIMISATION, NOT INSTRUMENTATION.** MLB's `build_cards_page_context` hydrating on the worker is the 331s, named as "the real work... untouched" by a code comment since 2026-08-07. **Do not buy more spans** — the residual 107.7s (16%) is spread across gaps individually too small to chase. No lane holds this.
- CLAIMS: all released. `pipeline/portfolio_commit.py` and `polymarket_board_join.py` were taken for INSTRUMENTATION ONLY (`be7cbdeb`, both holders verified not running) and are annotated in their donor blocks — either lane reclaims by striking the note. Deploy claims: none held.
- Goal: (1) the ~56% of board-build compute that is currently UNMEASURED becomes visible in Render logs, and (2) Kalshi/Polymarket price refresh runs on its OWN cadence instead of being gated by the board build's 11-15 min period.
- Files: `pipeline/intelligence_state.py`, `pipeline/kalshi_odds_refresh.py`, `pipeline/polymarket_odds_refresh.py`, NEW `pipeline/venue_odds_loop.py`, and their tests.
- **ACQUIRED FOR INSTRUMENTATION ONLY `[2026-08-28, USER INSTRUCTION: "i need this lane to take the polymarket work"]`:** `pipeline/portfolio_commit.py` (from `portfolio-decision-and-execution`) and `syndicate/features/shared/polymarket_board_join.py` (from `open-bet-live-status`). WHY: `polymarket` appears NOWHERE in `intelligence_state.py` — Kalshi's refresh and join are spanned at board-build level, but Polymarket's equivalent runs inside `run_portfolio_commit`, so a `portfolio_commit` span is a black box over a join that indexes ~8,973 markets against ~1,335 rows and is a credible largest-single-item in the unattributed ~305s. BOTH holders verified NOT RUNNING before taking (`list_sessions`: every session `isRunning: false`; `9324a3e5` absent entirely, lane opened 2026-08-22). SCOPE IS A TIMING SPAN AND NOTHING ELSE — no behaviour change, no touching `_venue_price_resolver` or side-resolution. Annotated in place in both donor blocks so either can reclaim by striking the note.
- MEASURED BASELINE 2026-08-27 21:19-22:17Z, refresh-worker: cycle 680-874s, compute 614-782s, `build_intelligence_overview` 259-290s (~44% of compute). The remaining ~350s is invisible because `_log_stage_timing` is `logger.info`, which per CLAUDE.md never reaches Render's collector.
- Hypothesis (1): every `_log_stage_timing` call is silently lost, so `candidate_building`, `board_publication`, `response_building` and `request_total` have never been read in production. Converting to `print(..., flush=True)` makes them appear with no other change.
- Hypothesis (2): `run_kalshi_odds_refresh()` has exactly ONE production caller — inside `_compute_board_publication_response` — so its `DEFAULT_REFRESH_INTERVAL_SECONDS = 120` is unreachable; the board loop sets the venue cadence. Polymarket has NO loop at all since `_polymarket_catalogue_at_boot` was retired (`fcdc5c57`).
- Falsification (1): wrong if the stage lines still do not appear after the change, or if they account for a trivial share of the ~350s. Falsification (2): wrong if a decoupled loop does not raise observed Kalshi refresh frequency above one-per-board-build.
- Verification: (1) `[intelligence_state] STAGE_TIMING stage=<name> duration_ms=<n>` appears in refresh-worker logs for stages that emit NOTHING today, and the named stages sum to a materially larger share of compute than the 44% currently visible. (2) `[venue_odds_loop] REFRESH venue=kalshi` fires on its own interval, at a rate NOT equal to the board-build rate, and a board build reads CACHED markets rather than triggering a fetch.
- CONSTRAINT, checked before design: both worker entrypoints are CLAIMED — `scripts/run_refresh_worker.py` by `exchange-markets-api-integration`, `scripts/run_live_odds_refresh_worker.py` by `open-bet-live-status`. So the loop is hosted from `start_intelligence_state_background_loop` in the UNCLAIMED `intelligence_state.py`, not from a worker script. No cross-lane edits.
- RISK, stated up front: this worker has 110 OOM kills on record and `worker_periodic_work_never_free` is a standing rule. A new thread must be small, must not hold markets in memory beyond the refresh, and must be OFF by default behind a flag until measured.
- Blocked by: none

### venue-candidate-key-token-guard — OPEN — opened 2026-08-27 — session 764eca35-178c-4c29-afbd-ec621894aaf1

- Goal: `_candidate_keys` stops emitting city/nickname token keys built from a
  board team the club map could NOT resolve, and the two stale assertions in
  `test_polymarket_side_vocabulary.py` are brought onto the shipped key shape.
  One testable outcome: `py -3 -m pytest tests/test_polymarket_side_vocabulary.py
  tests/test_kalshi_side_vocabulary.py tests/test_venue_quote_fanin.py -q` is
  green, with a NEW test that fails before the code change.
- Files: `syndicate/features/shared/venue_quote_fanin.py`,
  `tests/test_polymarket_side_vocabulary.py`
- CLAIM PROVENANCE: both paths were released. `kalshi-line-aware-rungs` removed
  `venue_quote_fanin.py` from its `Files:` list on 2026-08-27 noting it was
  re-claimed by `venue-quote-line-join`; that lane is OPEN, UNOWNED, session
  `3515d143` archived 2026-08-27 ~21:45Z with **ALL CLAIMS RELEASED** and the
  paths deliberately unwritten. The only other mention of
  `test_polymarket_side_vocabulary.py` (line ~1414) is prose listing suites that
  were RUN, not a `- Files:` claim. No live holder.
- Hypothesis: the failures are NOT one bug. Commit `0acabd09` ("Kalshi offered
  every game line under a side the board never asks for") added a THIRD key
  shape — the city/nickname token — and shipped tests for it
  (`test_kalshi_side_vocabulary.py`) without updating the exact-equality
  assertions in the older `test_polymarket_side_vocabulary.py`. So:
  (a) `test_the_board_row_derives_the_SAME_key_from_its_own_teams` is a STALE
  TEST — `mlb|h2h|arizona` / `mlb|h2h|diamondbacks` are the intended new shape
  and both clubs resolved; (b) `test_an_unresolvable_club_adds_NO_second_key` is
  a REAL DEFECT — `team_quote_token` falls back to a normalised RAW string when
  `canonical_team` returns None (correct at the VENUE, where Kalshi says
  "Texas"), so an unresolvable BOARD team yields `mlb|h2h|club`, `mlb|h2h|not`,
  `mlb|h2h|real` from "Not A Real Club". That contradicts the invariant written
  three lines above it in the same function — *"No club, no second key -- never a
  bare team string as a fallback."*
- Falsification: (a) is wrong if `0acabd09` predates the assertions, or if the
  token keys can be shown to be unintended. (b) is wrong if the token block's own
  docstring bound ("the candidate set here is exactly two clubs and both are
  known to be playing each other") is satisfiable without `canonical_team`
  resolving — it is not.
- **RESULT — both halves of the hypothesis CONFIRMED, and a THIRD, LARGER defect
  found that neither test named.** History settles (a): the assertions were
  written `3e8856e8` 2026-08-25T01:00:27Z, the token block landed `0acabd09` the
  same evening at 21:44:32Z, and `3e8856e8` is an ancestor of it. That commit
  shipped `test_kalshi_side_vocabulary.py` for the new shape and reported "655
  tests green" over a filtered set that did not include the file it broke.
- **MY OWN FALSIFICATION CLAUSE WAS PARTLY WRONG and is corrected here.** I wrote
  that an unresolved OPPONENT is also unsafe because it cannot subtract its
  shared tokens. Once the real bound is the sport's whole vocabulary, that is
  false: a token unique across the sport cannot name the opponent whether the
  opponent resolved or not. Requiring the opponent to resolve would have
  narrowed the join for nothing. Only MY side must resolve.
- **THE THIRD DEFECT: the opponent subtraction is the wrong SCOPE, not merely a
  weak one.** `apply_venue_quotes` resolves each candidate against
  `quotes_for_sport` — the sport's WHOLE pool — while the subtraction bounds
  only the row's own game. Measured over the alias maps 2026-08-27, ambiguous
  tokens the board was offering: **soccer 21** (`city` names 14 clubs, `real` 4,
  `manchester` 2, `madrid` 2), **mlb 7** (`chicago`, `sox`, `new`, `york`, `los`,
  `angeles`, `san`), **nfl 5** (`new` names 4), **nba 3**, wnba 0. A Manchester
  City row offered `soccer|h2h|city` and could win a Bristol City quote from a
  different fixture — a wrong-team match at a confident price, indistinguishable
  downstream from a right one. And `_alias_map` is `{}` for **nhl, ncaaf,
  ncaab**, so every one of their rows took the raw-string path unguarded: "Ohio
  State Buckeyes" offered `ncaaf|h2h|state`. NCAAF reached the board side
  2026-08-27, per this file's own `kalshi-line-aware-rungs` note.
- **FIX, three files.** `team_aliases.unambiguous_club_tokens(sport)` [NEW,
  `lru_cache`d, derived from `_alias_map().values()` exactly as
  `_nickname_alias_map` is derived — no second hand-maintained list].
  `venue_quote_adapters.team_name_tokens` now resolves through `canonical_team`
  (NOT `team_quote_token`, whose raw fallback is correct at the venue and wrong
  on the board side) and keeps only tokens that name exactly one club. Its one
  caller `_candidate_keys` keeps the opponent subtraction as a subsumed second
  check; its comment block, which asserted the wrong bound, is corrected in
  place.
- **MEASURED, before -> after.** `Not A Real Club` 5 keys -> 1. `Ohio State
  Buckeyes` 5 -> 1. `Manchester City` 4 -> 2. `Texas Rangers` UNCHANGED at 4,
  including `mlb|h2h|texas` — the case `0acabd09` was built for.
- **REACHABILITY SHOWN, not assumed.** The three new refusal tests were run
  against the pre-fix `team_name_tokens` (monkeypatched back in) and all three
  produce the old keys, so they discriminate. The fourth new test
  (`..._is_not_a_blanket_refusal`) passes in BOTH states BY DESIGN and is
  paired with them: a filter that dropped everything would satisfy all three
  refusals and silently take the Kalshi city match with it.
- **GREEN: 1026 passed, 27 subtests** across every `venue|kalshi|polymarket|
  team_alias` suite (43 files, 95s), plus `tests.test_kalshi_side_vocabulary`
  under **unittest** — the runner CI actually uses — because that suite owns the
  token shape and its end-to-end "Texas wins" -> board row test is the one that
  would catch an over-narrow guard.
- Verification: a reachability test in the pytest sense — the new
  unresolved-club test must FAIL on the pre-fix function and PASS after, and
  `test_kalshi_side_vocabulary.py` (the suite that OWNS the token shape) must
  stay green, proving the guard narrowed the unresolved case and nothing else.
  Per `learnings.md` 2026-08-27 (fixture that cannot violate its property): the
  fixture must contain a row whose club genuinely does not resolve AND a row
  whose OPPONENT does not resolve — the absence has to be present.
- **PUSHED 2026-08-27, `635f869d..1c37c220` on `main`. NOT DEPLOYED** — no
  `render.yaml` in any of the three commits, so no `blueprint_sync`, so nothing
  reached production. `autoDeploy = no` holds for the `.py`.
- **THE PUSH CARRIED TWO COMMITS THAT ARE NOT THIS LANE'S**, and that is stated
  rather than left to be discovered: local `main` was ahead 3 / behind 1 when I
  came to push. Ahead were mine (`1c37c220`) plus `029a8eb2`
  (venue order-reconciliation standard — `kalshi_orders.py`,
  `polymarket_us_orders.py`, `venue_order_states.py`) and `20362bfb` (portfolio
  date filter — `intelligence.py`, `portfolio.html`), both already committed by
  other sessions before this one opened and both unpushed. Behind was
  `635f869d` (`venue-refresh-decoupling`: `intelligence_state.py`,
  `venue_odds_loop.py`) — **no file overlap with anything above**, rebase clean.
  Re-ran after the rebase rather than trusting the pre-rebase green: **132
  passed, 2 subtests** over my surface plus both incoming suites
  (`test_venue_odds_loop.py`, `test_venue_order_states.py`).
- **WHAT IS OWED AND IS NOT DISCHARGED: the production volume reading.** This
  narrows real matching. `venue-quote-line-join` measured soccer unmatched
  15,348 -> 4,006 and grid stamped 13.1% -> 66% on the code this changes, and
  soccer is the sport carrying 21 of the ambiguous tokens. The dropped keys were
  WRONG matches, not lost ones — but that is an argument, not a measurement, and
  nothing here has read live data. Whoever deploys this must read
  `VENUE_REPRICE_KEYS` `unmatched_by_sport` and `stamped` for soccer/mlb/nfl
  before and after, and must NOT treat a fall in `stamped` as a regression
  without checking `unmatched_by_sport_sample` for what stopped matching.
- **NEAR-MISS, CAUGHT BY MESSAGE, 2026-08-27 21:0xZ CT.** `venue-refresh-decoupling`
  acquired the refresh-worker claim at `target=a818f771` five minutes after my
  push — the tip of `main`, which CONTAINS `1c37c220`. Their claim reason named
  an env pickup (`SYNDICATE_KALSHI_REFRESH_INTERVAL_SECONDS=300`) and a clean
  post-boot baseline; nothing in it suggested they knew a venue key-derivation
  narrowing had landed in that SHA. refresh-worker is the service that RUNS
  `apply_venue_quotes`. I messaged them before the deploy fired; **they re-pinned
  to `635f869d`** — the SHA already live, zero code delta, env vars injected at
  deploy time regardless — so **nothing of mine shipped under their claim.**
- **THEIR ARGUMENT WAS BETTER THAN MINE AND CORRECTS IT.** I told them my change
  could not touch their CADENCE reading. True, and too narrow. Their other
  reading is COMPUTE ATTRIBUTION — whether the venue loop moved board compute
  614-782s -> 1061s — and `_candidate_keys` narrowing changes how much work
  `apply_venue_quotes` does INSIDE the interval they are timing. Less work in the
  venue join is exactly a number that would move for a reason that is not theirs.
  It is not orthogonal to their diagnostic; it lands in the middle of it. Recorded
  because I offered a clean bill I was not entitled to offer: "cannot touch your
  verification criterion" is not the same claim as "cannot touch your
  measurement", and I conflated them.
- **A CONFOUND NOW EXISTS FOR MY OWN BEFORE/AFTER, AND I RE-DERIVED IT RATHER
  THAN TAKING IT ON REPORT.** They set `SYNDICATE_KALSHI_REFRESH_INTERVAL_SECONDS`
  120 -> 300 on refresh-worker. Read directly off `/v1/services/<id>/env-vars`
  (2 pages, paginated per CLAUDE.md): `SYNDICATE_KALSHI_REFRESH_INTERVAL_SECONDS
  = '300'`, and alongside it `SYNDICATE_VENUE_ODDS_LOOP_ENABLED = '1'`. INERT
  until their deploy lands, per `render_env_needs_deploy` — a restart does not
  re-inject. After it does, Kalshi refreshes roughly half as often (they measured
  a single refresh at 80-143s against the old 120s interval, i.e. near-continuous
  fetching). **So any `VENUE_REPRICE_KEYS` freshness or quote-age reading taken
  after their deploy is confounded for a reason that is theirs, and any `stamped`
  / `unmatched_by_sport` reading is confounded for a reason that is mine.** The
  two must not be read off the same deploy.
- **A SECOND READING IS OWED AND IS NOT THE SAME AS THE FIRST.** The soccer
  volume question (`stamped` / `unmatched_by_sport` falling) is a MISSED-match
  question. The nhl/ncaaf/ncaab half is a WRONG-match question — `_alias_map` is
  empty there, so `ncaaf|h2h|state` was being offered against a sport-wide quote
  pool — and a wrong match surfaces as a plausible number nowhere, not as a bad
  one. It cannot be read off the same counter and deserves its own deploy.
- SCOPE NOTE, not taken: `venue-quote-line-join` records two UNFIXED items on
  these files (a totals key that names no game; the 842-row zero-match builds).
  Out of scope here.
- Blocked by: none

### nfl-settlement-resolver — **CLOSED 2026-08-28** — VERIFIED IN PRODUCTION: `no_resolver_for_nfl` 16 -> ABSENT, `BET_STATUS resolved` 98 -> 114 (+16, exactly the count that disappeared), `SETTLED 08-27 graded` 2 -> 9. Deployed `5a5efa8d` to refresh-worker 03:41:29Z, live 03:47:11Z; reading 03:59:18Z. Evidence in `deploys.md`. — opened 2026-08-27 — session 764eca35-178c-4c29-afbd-ec621894aaf1

- Goal: NFL bets can be GRADED. One testable outcome: `no_resolver_for_nfl`
  goes to **zero** in `[paper_settlement] SETTLED` / `[bet_status] BET_STATUS`
  and at least one NFL order reaches a won/lost verdict in production.
- MEASURED BEFORE STARTING, 2026-08-28T02:37-02:50Z refresh-worker:
  `SETTLED date=2026-08-28 orders=21 graded=0 ungraded={... 'no_resolver_for_nfl': 6 ...}`
  (**6 of 21 = 29% of today's slate**), `SETTLED date=2026-08-27` 8 of 158,
  `BET_STATUS orders=158` 16. NFL is the ONLY sport producing orders with no
  resolver. This is `#547` repeating: soccer sat at `no_resolver_for_soccer`
  with 0 settled ALL-TIME while being ~97% of the board by row count.
- **THE GAP IS TWO STAGES, NOT ONE — this is the finding that shapes the work.**
  (1) `paper_settlement._default_resolver` has builders for mlb/wnba/soccer
  only. (2) **There is nothing for an NFL resolver to READ.**
  `poll_soccer_live_state.py` is the ONLY live-state poller in `scripts/`.
  `syndicate/features/nfl/live_game_state.py` fetches ESPN over HTTP at call
  time (`_fetch_scoreboard` -> `json.loads(response.read())`), is keyed by
  `(season, week, seasontype)` rather than by DATE — and settlement resolvers
  take `selected_date` — and its only callers are in `preseason_cards.py`,
  always `SEASONTYPE_PRESEASON`. Regular season is not wired at all.
  **Writing only the resolver ships a READER WITH NO PRODUCER** — the inverse
  of `#547` — and it would go out inert with passing tests.
- Files: NEW `scripts/poll_nfl_live_state.py`, NEW
  `syndicate/features/shared/bet_status_nfl.py`, NEW
  `tests/test_bet_status_nfl.py`, and `syndicate/features/shared/manifest.py`
  (`HOT_ARTIFACT_PATTERNS` allowlist entry).
- **NARROW CARVE-OUT, one line**, on `syndicate/features/shared/paper_settlement.py`
  — held by lane `open-bet-live-status` (session `syndicate-27`, recorded in
  that lane's own block as NOT RUNNING). Exactly one `"nfl": lambda: _build(...)`
  entry added to `_default_resolver`'s `builders` dict; nothing else in the file
  touched. Same narrow-carve-out pattern, and same justification, that
  `venue-refresh-decoupling` used on this lane's `polymarket_board_join.py`
  claim on 2026-08-28. Reclaim by re-asserting the path.
- Hypothesis: NFL orders carry `home_team`/`away_team` (as soccer's do), so the
  join is on the TEAM PAIR through `team_aliases`, never on `event_id` — the
  order's id namespace is OddsAPI's and ESPN's is not the same, which is the
  trap `bet_status_soccer` documents and `bet_status_wnba` says cost MLB a day.
  The NFL alias map carries all 32 clubs (measured this session).
- Falsification: wrong if NFL `OrderRequest` rows do NOT carry the team fields,
  in which case the join needs a different key and the refusal must be BY NAME
  rather than a fallback to an id that cannot match.
- Verification: REACHABILITY BEFORE CORRECTNESS per the engine standard —
  `off != on`. The resolver must be shown to change the counter, not merely to
  exist: `no_resolver_for_nfl` non-zero before, zero after, on the SAME slate,
  plus one NFL order reaching won/lost. A test that only proves the module
  imports would pass in both states.
- RISK / TO CHECK, not asserted: my notes carry "NFL week self-pins to 1" from
  the August E2E assessment. Grepping the obvious places found no hardcode, so
  it is NOT claimed as current — but `data/nfl_source/current_week.json` and the
  week derivation must be checked, because a `(season, week)` join would inherit
  it. **Date-keying the artifact sidesteps it entirely**, which is an
  independent reason to prefer the poller over a live `nfl_game_state_index`
  call.
- **BUILT 2026-08-28, BOTH STAGES. NOT DEPLOYED.**
  `scripts/poll_nfl_live_state.py` fetches ESPN by `?dates=YYYYMMDD` (never
  season/week, so the week question is never asked) and persists through
  `refresh_state_store.write_json_file`; `bet_status_nfl.py` reads with the
  matching `read_json_file`, so producer and reader cannot land in different
  places across the web/worker disk split.
- **REACHABILITY PROVEN, `off != on`.** With the one-line `paper_settlement`
  wiring REMOVED: **1 failed, 16 passed** — and the one failure is
  `test_paper_settlement_DISPATCHES_nfl_to_a_real_resolver`, asserting exactly
  `no_resolver_for_nfl`. Restored: **17 passed**. The other 16 pass in BOTH
  states, which is the correct signature — only the reachability test can see a
  dispatch miss.
- **END TO END ON REAL ESPN DATA**, not a fixture. Polled 2026-08-27 live: 4
  games, 3 final. The actual production order `tsc-nfl-pit-buf-2026-08-27 over
  34.5` now grades — PIT 27 @ BUF 28, `current_value=55.0, is_final=True`.
  Moneyline SF@LV returns `margin 6.0, line 0.0` (two-way PUSH semantics, the
  `draw_possible=False` decision); the tri-code join returns the same; the
  in-progress LAR@LAC game returns `started=True, is_final=False` and does not
  settle.
- **FALSIFICATION DID NOT FIRE.** `execute_portfolio.py:133` populates
  `home_team=position.get("home_team")` sport-agnostically and both fields are
  first-class in `execution_ledger`'s durable record. Where a position lacks
  them the resolver refuses as `no_home_away_teams_on_order` — VISIBLE in the
  counter rather than silently joined on an id that cannot match.
- **A SECOND, BIGGER FIX FELL OUT OF A STALE TEST.**
  `test_a_sport_with_no_resolver_is_named_not_silent` used NFL as its example of
  an unwired sport and broke. Its own docstring said it had used SOCCER until
  `#547`. Both times the stand-in was a REAL sport, and both times that is what
  let a live gap read as a correctly-reported one in a green suite. Repointing
  it at NCAAF would have re-armed the trap a third time — NCAAF is on the board
  TODAY. So it now names a sport the platform does not trade, and a NEW test,
  `test_the_traded_sports_WITHOUT_a_resolver_are_pinned_so_a_new_gap_cannot_pass_quietly`,
  pins the set `{nba, nhl, ncaaf, ncaab}`. Adding a sport to the board without a
  resolver now FAILS instead of quietly demonstrating the bug.
- **GREEN: 297 passed** across the settlement/bet-status/game-line/artifact
  surface. TWO FAILURES IN `test_artifact_publisher.py::MissingRequiredArtifactRepairTests`
  ARE **PRE-EXISTING AND NOT MINE** — verified by removing my
  `HOT_ARTIFACT_PATTERNS` entry and re-running: they fail identically without
  it. Their counts read 5 != 7 and 10 != 12, i.e. LOWER than expected, and
  adding a pattern cannot reduce a count.
- **OWED, and it is the whole point of the lane:** the production reading.
  `no_resolver_for_nfl` must go to ZERO and at least one NFL order must reach a
  won/lost verdict. Nothing here is deploy-verified.
- **CLOSED 2026-08-28.** Goal met and measured. Two things are handed ON rather
  than closed with it, because neither is this lane's goal and neither should
  vanish into a closed block:
  1. **`game_not_in_nfl_live_state: 1`** on `SETTLED date=2026-08-26`. The
     resolver RUNS for that date and fails at the JOIN, not at dispatch — one
     NFL order whose game is not in the capture for its ledger date. Likely
     date-bucket skew: an NFL kickoff at 00:00Z belongs to the previous day
     locally, and the capture is fetched per ledger date. One order, named in
     the counter by design.
  2. **`{nba, nhl, ncaaf, ncaab}` still have NO settlement resolver.** Pinned by
     the new `test_the_traded_sports_WITHOUT_a_resolver_are_pinned...` test, so
     it can no longer pass quietly — but pinned is not fixed. NCAAF is on the
     board TODAY (measured this session: kalshi offered 524 ncaaf quotes,
     `wanted_overlap` 32, 52 selected), so its bets are being taken and cannot
     be graded. That is the same `#547` shape a third time, already visible.
- Blocked by: none

### mlb-overview-isolation — **CLOSED 2026-08-28** — MLB builds again, verified ON THE DISCRIMINATING READING, without lowering the floor
- OUTCOME: MLB's hydration runs in a child under `RLIMIT_AS`. `BOARD_OVERVIEW_READY sports=8 mlb:g=15,r=3` at 14:09:31Z — first MLB on the board after hours of `sports=7` with no `mlb:` entry.
- **VERIFIED ON THE READING THAT DISCRIMINATES**, not just the happy one: at 14:17:06Z `unreclaimable=1327.8MB` -> guard headroom **2768.2MB, BELOW the 3000MB floor** — the same band where eighteen consecutive builds read `sports=0` this morning — and isolated MLB SUCCEEDED. The 14:03 build ran 80s after a restart and would likely have passed the floor anyway; it proved the mechanism, not the fix. Guard refusals since deploy: 0.
- THE FLOOR IS UNTOUCHED. `learnings.md 2026-08-15` names "MLB game hydration in pid 39" as the kill and the +3.5GB excursion is still unexplained. This did not argue with that — it made the excursion survivable, because a margin cannot cover a +3.5GB spike in a 4096MB container at ANY admissible headroom.
- **TWO BELIEFS RETIRED.** (1) "MLB is the expensive sport" is FALSE today — it cost **4.43s** and a 1.19MB row; the 3000MB floor was sized on a 2026-08-07 "+2.9GB" that no longer describes it. The real cost is **soccer, 163.2s, 82% of hydrated overview time**. (2) A FIXED cap would have been wrong on the first run: the derived cap read `cap_mb=3221` against headroom 2935MB, where a constant from my own hour-old measurement would have been half that. That is exactly how the floor became unreachable.
- **OWED, and it is the safety property:** the child has never HIT its cap in production. `MEMORY_CAP_HIT` has never fired, so "the OS kills the child, not the worker" rests on a synthetic POSIX test that is SKIPPED on the Windows box this was written on. The fall-through-to-the-guard failure path is unexercised in production. Do not report the OOM risk as closed.
- NEXT LEVER, no lane: **soccer's 163.2s**, now the largest single item in the overview. `SYNDICATE_OVERVIEW_ISOLATION_SPORTS` already accepts it if isolation is the right shape, but its cost is CPU, not memory, so isolation would not make it faster.
- Claims: all released. Flags `SYNDICATE_OVERVIEW_ISOLATION_ENABLED=1` on refresh-worker only.
- Goal: MLB's hydrated overview builds again, WITHOUT lowering the 3000MB expensive floor — by running it in a SUBPROCESS whose memory is capped, so an excursion kills the child and the worker survives. `[USER DECISION 2026-08-28: "do 2 now", choosing this over lowering the floor]`
- Files: `syndicate/features/intelligence.py`, NEW `syndicate/features/shared/overview_subprocess.py`, NEW `scripts/build_sport_overview_child.py`, and their tests.
- MEASURED BASELINE 2026-08-28 13:23-13:42Z, refresh-worker: `OVERVIEW_STOPPED_FOR_MEMORY next_sport=mlb floor=expensive floor_mb=3000` with `headroom_mb` 2167.5 / 2362.8 / 2220.2 against `min_required_mb 3000.0`, basis `unreclaimable` ~1.73-1.93GB. Gap ~640-830MB, far too wide for a `malloc_trim` (measured releases 16-110MB). `BOARD_OVERVIEW_READY sports=7` with NO `mlb:` entry — the board has carried zero MLB games for hours.
- WHY NOT LOWER THE FLOOR: `_OVERVIEW_MIN_SAFE_HEADROOM_BYTES`'s own comment refuses it ("that variance is unexplained, so the gate in front of MLB keeps its full 3000MB margin"), and `learnings.md 2026-08-15` EXONERATES the eight-sport pass while the next entry names "MLB game hydration in pid 39" as the kill. The +3.5GB excursion is real and unexplained. This lane does not argue with that — it makes the excursion SURVIVABLE instead of pre-empting it with a margin that cannot cover it anyway (a +3.5GB spike kills a 4096MB container at ANY admissible floor).
- Hypothesis: `_build_sport_overview` is a clean seam returning one JSON-able dict, so MLB's hydration can run out-of-process under `RLIMIT_AS`. A child that exceeds the cap dies alone; the parent reads a degraded row and continues.
- Falsification: wrong if the sport row does not survive a JSON round-trip, or if the cap cannot be set low enough to protect the parent while still admitting the measured +968MB/+1543MB streamed-path cost.
- KEY DESIGN CONSTRAINT: the cap is DERIVED FROM MEASURED HEADROOM AT CALL TIME (`headroom - reserve`), not a fixed constant. A fixed cap plus a drifting parent baseline is how the 3000MB floor became unreachable in the first place; a derived cap cannot repeat that.
- Verification: `OVERVIEW_SPORT_BEGIN sport=mlb` followed by `OVERVIEW_SPORT_END sport=mlb` and `BOARD_OVERVIEW_READY ... sports=8` WITH an `mlb:g=N` entry, on a build where headroom is BELOW 3000MB — i.e. MLB builds in exactly the condition that refuses it today. Plus: a forced-excursion test showing the child dies and the parent survives.
- RISK: OFF BY DEFAULT behind a flag. This worker has 110 OOM kills and `#241` restart-looped it; a subprocess per board build is periodic work and is not free.
- Blocked by: none

### ncaaf-settlement-resolver — OPEN — opened 2026-08-28 — session 764eca35-178c-4c29-afbd-ec621894aaf1

- Goal: NCAAF bets can be GRADED, and are graded against the RIGHT GAME. One
  testable outcome: `no_resolver_for_ncaaf` reaches production as zero (it does
  not appear today only because NCAAF orders have not hit the ledger yet — see
  below), and an NCAAF order reaches a won/lost verdict.
- Files: NEW `syndicate/features/shared/ncaaf_team_registry.py`, NEW
  `scripts/poll_ncaaf_live_state.py`, NEW
  `syndicate/features/shared/bet_status_ncaaf.py`, NEW
  `tests/test_bet_status_ncaaf.py`, plus the same ONE-LINE carve-out on a file
  held by `open-bet-live-status`: `syndicate/features/shared/paper_settlement.py`
  Reordered 2026-08-28 so the parser reads this as the deference it always was:
  the carve-out has landed and this lane was never a second owner. Plus the
  pinned-set assertion in
  `tests/test_paper_settlement.py` that `nfl-settlement-resolver` added.
- **NCAAF IS NOT NFL, AND THE DIFFERENCE IS THE WHOLE LANE.**
  `team_aliases._alias_map("ncaaf")` is `{}`, so `teams_match` falls through to
  HEURISTICS — `len(token) >= 3 and any(word.startswith(token))`. Across ~130
  FBS teams that means **"Michigan" matches "Michigan State"**, "Ohio" matches
  "Ohio State", and both Miamis match each other. An NFL-shaped resolver would
  therefore grade bets against the WRONG GAME, which is strictly worse than not
  grading them: a wrong verdict is written confidently and nothing downstream
  can tell.
- **THE AUTHORITATIVE VOCABULARY EXISTS AND IS ALREADY ALLOWLISTED.**
  `ncaaf_team_registry.csv`, **684 teams**, columns `team_id`,
  `canonical_team_name`, `abbreviation`, pipe-separated `aliases`,
  `display_name`, `school_name`, `mascot_name`; matched by
  `*_source/source_artifacts/data/processed/team_registry/*.csv` in
  `HOT_ARTIFACT_PATTERNS`.
- **BUT THE EXISTING INDEX CANNOT BE REUSED.** `ncaaf/cards.py::_team_registry_index`
  builds it with `setdefault`, so the FIRST row wins every collision. Measured
  2026-08-28 over that same key construction: **2,342 distinct keys, 128
  AMBIGUOUS** (owned by more than one `team_id`), worst `tigers` -> **25
  teams**. `_resolve_team("Wildcats")` returns Abilene Christian. Same hazard
  class as the venue `_candidate_keys` ambiguity fixed earlier today, and
  disqualifying on a settlement path.
- Hypothesis: dropping ambiguous keys costs nothing on real data, because ESPN
  sends specific forms (`displayName` "TCU Horned Frogs", `location`,
  `abbreviation`) rather than bare mascots.
- **FALSIFICATION ALREADY RUN, AND IT DID NOT FIRE.** Against the live ESPN
  college-football scoreboard for 2026-08-29 (Week 1 opener weekend, 8 games,
  16 teams): **16/16 resolved unambiguously** against the ambiguity-dropped key
  set. If a real slate had resolved poorly the join would need a different key
  and this lane would be about that instead.
- Verification: REACHABILITY BEFORE CORRECTNESS, `off != on`, exactly as
  `nfl-settlement-resolver` proved it — the dispatch test must FAIL with the
  one-line wiring removed. Plus a test that an AMBIGUOUS name ("Tigers") is
  REFUSED rather than resolved to one of 25.
- NOTE ON THE PRODUCTION READING: unlike NFL, `no_resolver_for_ncaaf` is NOT in
  today's counters — NCAAF orders have not reached the ledger yet, though NCAAF
  IS on the board (measured this session: kalshi offered 524 ncaaf quotes,
  `wanted_overlap` 32, 52 selected). So the production reading here is a
  FUTURE-DATED obligation, and a zero counter today is NOT evidence. Say so
  rather than banking it.
- **BUILT 2026-08-28. NOT DEPLOYED.** `ncaaf_team_registry.py` (unambiguous
  index over the 684-team CSV, ambiguous keys DROPPED),
  `poll_ncaaf_live_state.py` (ESPN `college-football` by `?dates=`, derived from
  the NFL poller so the payload parsing cannot drift), `bet_status_ncaaf.py`
  (registry-backed join, NOT `teams_match`).
- **REACHABILITY PROVEN, `off != on`, and BETTER than NFL's.** With the one-line
  wiring removed: **2 failed, 62 passed** — the dispatch test AND
  `test_the_traded_sports_WITHOUT_a_resolver_are_pinned...`, which correctly
  detected `ncaaf` reappearing in the missing set. That tripwire was added by
  `nfl-settlement-resolver` an hour earlier and has now caught a real change.
- **MEASURED ON THE REAL REGISTRY AND THE REAL FEED:** index holds **2,214
  unambiguous keys** of 2,342 (**128 ambiguous dropped**, matching the
  pre-build measurement exactly); on the live 2026-08-29 ESPN slate
  **16/16 team names resolve, 0 unresolved**. `Tigers` and `Wildcats` refuse;
  `Michigan` and `Michigan State` resolve to DIFFERENT ids.
- **HONEST LIMIT ON THE END-TO-END:** the join is verified against real ESPN
  names, the GRADING is not — **no NCAAF game has finished yet this season**
  (08-22 and 08-23 return 0 games; 08-29 returns 8 with 0 finals). So grading is
  unit-tested against synthetic scores only, unlike NFL where a real 27-28 final
  was available. Do not describe this as end-to-end verified.
- **GREEN: 324 passed** across the settlement/bet-status/game-line surface. ONE
  PRE-EXISTING FAILURE, `test_ncaaf_team_registry_reachability.py::
  test_albany_is_a_stated_judgement_not_an_inferred_one` — verified by stashing
  ALL my tracked edits and re-running: it fails identically. It targets
  `ncaaf/oddsapi_lines.py::resolve_team`, a module this lane does not touch.
- Blocked by: none

### portfolio-venue-and-side-integrity — CLOSED 2026-08-29 — both readings discharged; `#603` handed to `venue-join-refusal-visibility` — opened 2026-08-28 — session 12b2be57-d671-480b-b11e-399612c9e84c (ENDED)
- Goal: five `/portfolio` asks `[user 2026-08-28]`, plus what fell out of
  verifying them — WNBA game lines, `#600` (a lost-write race on the money
  ledger), operator actions for two red banners, and then a SEGMENT defect that
  turned out to span both venues.
- **ELEVEN SHIPPED AND DEPLOYED.** Narrative, evidence, dead ends:
  `log/2026-08-28.md` (three blocks). Measurements: `deploys.md`. Items:
  `todo.md` `#595` `#596` `#599` `#600` `#601` `#602` `#603` `#604`.
- Files: `syndicate/blueprints/intelligence.py`, `syndicate/blueprints/ops.py`,
  `syndicate/templates/portfolio.html`,
  `syndicate/features/shared/portfolio_periods.py`,
  `syndicate/features/shared/paper_settlement.py`,
  `syndicate/features/shared/polymarket_us_orders.py`,
  `syndicate/features/shared/polymarket_us_markets.py`,
  `syndicate/features/shared/bet_status_wnba.py`,
  `syndicate/features/shared/execution_ledger.py`,
  `syndicate/features/shared/kalshi_board_join.py`,
  `syndicate/features/shared/kalshi_catalogue.py`,
  `syndicate/features/shared/polymarket_board_join.py`,
  `pipeline/intelligence_state.py`, `pipeline/execute_portfolio.py`, + tests.
- Live: refresh-worker `420dddaa` (BOOTED 21:55:15Z), carrying this lane's
  `#601`/`#602`/`#604` plus 12 commits of `local_5163d9b3`'s soccer work.
  **Deployed manually BY THE USER, twice** — `deploy-guard` refuses on a
  preflight HOLD, and when the user chose to override, the harness classifier
  refused the command independently. Surfaced, not routed around.
- **READING 1 — MEASURED WITH A DENOMINATOR `[2026-08-29 04:53Z]`, and the
  answer is "outcome yes, mechanism no".** 20 polls / 68 min across BOTH
  writers: **59 settlement lines, 49 execute lines, ZERO `LEDGER_MERGE`, ZERO
  `MERGE_READ_FAILED`.** That is a real null, not the bare `concurrent=0` that
  was previously quoted as a pass — the machinery that could collide was
  demonstrably running.
  **WHAT IS AND IS NOT EXERCISED, because this is the dead-constant trap again:**
  `_merge_onto_current` runs on EVERY persist — the log at
  `execution_ledger.py:645` is conditional, the merge is not. So the merge
  function is reachable and running and finding nothing to merge. **Its
  CONFLICT branch has never executed**: "row we did not touch -> keep theirs",
  "deletion racing an update -> keep theirs" are untested in production.
  Code live on all three writers (`f66c7441` an ancestor of every live SHA,
  checked — not assumed).
  **CORRECTION `[2026-08-29, forced-collision test `1d6f324f`]` — THE NULL MEANS
  LESS THAN I REPORTED.** `counts["concurrent"]` increments ONLY when a row
  ALREADY IN OUR BASELINE has a different fingerprint now
  (`execution_ledger.py:443`). An intruder that only APPENDS rows never trips
  it, so an addition-only race is merged correctly and **logged nowhere**.
  So "zero `LEDGER_MERGE` in 68 min" does NOT mean "no concurrent writes" — it
  means "no other writer MODIFIED a row we had loaded". **A placement cycle
  appending orders while settlement holds a snapshot is exactly that invisible
  case**, which is very likely what was happening all along. Found by the test,
  not by production; pinned by
  `test_an_ADDITION_ONLY_race_is_MERGED_but_never_LOGGED`.
  **MECHANISM NOW VERIFIED IN TEST**, which is what closes the gap waiting could
  not: 8 forced-collision tests race real threads through the real
  `_load()`->`_persist()` path, two asserting `concurrent >= 1` so a
  non-overlapping run cannot pass silently. `off != on` — with the merge
  neutered to the pre-fix blind write, **all 8 FAIL**.
  So: symptom-level PASS (ledger monotonic, `1,295,990 -> 1,298,163` vs a
  `-8,031` step) + mechanism-level UNPROVEN. Closing this needs a FORCED
  collision in a test, not more waiting — 68 minutes of real traffic did not
  produce one, which is itself the finding.
- **READING 2 DISCHARGED `[2026-08-29 ~03:46Z]` — the path is CLOSED.** The
  slate placed: 2 orders after boot `21:55:15Z`, both `seg=full` on full-game
  tickets. **All 9 segment orders in the ledger predate every fix** (newest
  `07:40:51Z`; earliest deploy `20:58Z`), so the bad set is bounded and closed.
  What makes this more than an absence: `board_row_is_a_segment_bet: 39` in the
  SAME window — segment rows were PRESENT and were STOPPED, with a named reason,
  and none became an order.
  **LIMIT, STATED:** it does not prove those 39 would have become orders (most
  refused rows never do — only top-edge ones place), so this is "the path is
  closed", NOT "$X was saved on this slate". Only 2 orders ran on the fixed
  code and neither was a segment candidate, so the order count alone proves
  little; it is the PAIRING of 39-refused with 0-segment-orders that verifies.
- Verified in production: WNBA `GSCONN` graded `under lost`/`over won`
  `settled_value 153.0`; ledger monotonic (`1,295,990 -> 1,298,163` vs a
  `-8,031` step); both banners carry working operator actions; ONE `BOOTED`
  after the overridden deploy (no restart loop).
- **`#603` HANDED OVER, NOT FIXED — cross-lane.**
  `venue_quote_adapters.quote_key` is `sport|market|side|line`: no game, no
  segment. Measured 6 of 14 game-line keys → >1 event, 2 → >1 segment on 74
  real orders. Belongs to `venue-join-refusal-visibility`, which has 10 failing
  tests in those files. NOT edited.
- **CONTESTED: `syndicate/blueprints/ops.py` — TWO LIVE OPEN HOLDERS**
  `[flagged 2026-08-28 ~15:0x CDT, session 29794bbe]`. Also held by
  `venue-join-refusal-visibility` (session `d617eefd`). Left deliberately;
  neither claim is stale. This lane's only edit there (`last_blind_write` on
  `ledger-summary`) is deployed and did not collide.
### soccer-overview-cost — OPEN, **STILL UNSOLVED. The per-fixture read defect was REAL, FIXED, DEPLOYED, and is only ~6% of soccer.** — opened 2026-08-28 — session 3e5a9659
- **`[2026-08-29 05:2xZ]` DEPLOYED `3e2cbd0b` AND MEASURED. PREDICATE REFUTED.**
  soccer hydrated bracket **206s -> 204s mean** (pre 210.1/202.7; post 177.7/231.0/124.4).
  Inside the spread. Full numbers and caveats in `deploys.md`.
- **THE MEMO WORKS. `assemble_s` per fixture, same leagues, overnight both sides:**
  epl `0.23 -> 0.16` · ligue_1 `0.31 -> 0.16` · primeira_liga `0.34 -> 0.19` ·
  belgian `0.20 -> 0.02`. The 60-loads-per-week count was structural and correct.
- **WHY IT DID NOT MATTER, AND THIS RETIRES THE LANE'S OWN HEADLINE NUMBER.**
  `assemble_s 19.49 of 20.78s` -- the figure this lane handed forward as "the target
  is narrowed to ONE loop" -- was taken at **20:24Z, a European LIVE window**.
  Overnight, ONE full eight-league pass totals `assemble_s` ~= **28.8s against a
  ~206s soccer bracket = 14%**, not 95%. **DO NOT REUSE THE 19.49/20.78 RATIO.**
  ```
  04:25Z, one pass, PRE-deploy, assemble_s by league
    mls 11.7(15fx) · mls 3.16(17) · epl 2.31(10) · ligue_1 3.39(11)
    eredivisie 0.97(9) · primeira_liga 3.42(10) · championship 1.44(23) · belgian 2.43(12)
    TOTAL ~= 28.8s
  ```
- **SO THE COST IS STILL UNLOCATED — and the search space is now DIFFERENT, not smaller.**
  `week_games` assembly is ~14% overnight. `payload_s` is ~7%. That leaves **~80% of
  soccer's 206s inside `sport_branch` but OUTSIDE `week_games`**, which is where nobody
  has looked, because this lane spent a day narrowing onto `week_games` using a
  live-window ratio. `pregame_props()` was measured at 0.17s and `games()` at ~2.8s,
  both also possibly regime-scoped.
- **EIGHT PREDICTIONS, EIGHT REFUTATIONS.** The method note stands and is now sharper:
  a profiler over a real build, AND the profile must be taken in the regime the
  answer is for. Both the TTL retraction and this one are the same error --
  a quantity measured in one regime used as though it were constant.
- MEASUREMENT HYGIENE, recorded against myself: I set a >25 min settled bar and
  every sample was 2-19 min post-boot, across TWO boots (04:45:04Z, and 05:18:48Z
  from lane `venue-join-refusal-visibility`'s 05:15:37Z deploy taken while this
  claim was held). The verdict is robust -- 204 vs 206 is not a near miss -- but
  the caveat is real and the next reading should meet the bar.
- Deploy claim on refresh-worker: RELEASED 05:2xZ (`free`).
- **`[2026-08-29]` FOUND IT. THE COST IS `_match_to_game` RE-READING THE SAME FILES ONCE PER FIXTURE.**
  Method: not an eighth log span. Counted loader calls through a real `week_games`
  with the simulated branch forced, which is STRUCTURAL and therefore immune to
  the thin local mirror that has confounded three readings in this lane.
  ```
  9 fixtures, belgian_pro_league week 2 -- calls per week_games()
    288  (32.0 per fixture)  team_by_name          (cheap: 0.003s/108 calls)
     18  ( 2.0 per fixture)  live_state_payload    <- SAME (league,date) file
      9  ( 1.0 per fixture)  picks_rows            <- SAME file
      9  ( 1.0 per fixture)  game_markets_rows     <- SAME file
      9  ( 1.0 per fixture)  _prop_picks_by_player <- identical args every call
  ```
  A FLOOR, not a ceiling: `props.py` imports `picks_rows` into its own namespace,
  so `_prop_picks_by_player`'s own per-date reads went uncounted.
  On refresh-worker `live_state_payload` resolves through `read_json_file` -> the
  keyvalue store, so each is a ROUND TRIP, and a miss pays the disk fallback too.
- **THIS IS THE `assemble_s` BLOCK (19.49 of 20.78s), NOT the `payload_s` 7% I
  retracted.** The retracted proposal memoized `recommendations_payload` (the
  per-DATE loop). These four loaders are inside the per-FIXTURE loop. Same word
  "memo", different loop, ~13x the target.
- **IT ALSO EXPLAINS THE VARIANCE**, which no previous hypothesis did. Same league
  and same 10 fixtures read 3.24s and 13.99s. 20 keyvalue round trips whose payload
  size and hit/miss tracks live-match churn is consistent with a 4x spread on
  identical inputs; "one slow league" never was.
- **FIX: a CALL-SCOPED read memo** (`soccer_read_scope()`, `sources.py`), NOT an
  `@lru_cache` -- those four loaders each carry an explicit "Not cached (2026-07-24
  fix)" and that fix is correct. Outside a scope, behaviour is unchanged. Inside
  one assembly pass, one read per `(league, date)`. Across passes nothing is
  retained, so the freeze bug (MLS matches pinned at `status_state="pre"` 0-0 for
  days) cannot recur. Within a pass, re-reading a file 24 times cannot make cards
  FRESHER -- it can only make one board internally inconsistent -- so this is
  strictly more correct than what it replaces.
  MEASURED, 12 fixtures x 2 dates: **60 file loads -> 4, 15.0x.** Scales as 5N -> ~4.
- Tests: `tests/test_soccer_read_scope.py`, 11 passing. Includes the `off != on`
  CONTROL (`test_week_games_without_the_scope_reads_per_fixture` neutralises the
  scope and asserts the count explodes), the across-scope regression test for
  2026-07-24, thread isolation, and exception-path release.
- **PRE-EXISTING FAILURES, NOT MINE AND NOT REAL:** 15 soccer tests fail in the
  WORKTREE identically with and without this diff, and all 38 of the same tests
  PASS in the primary tree. Data-less-worktree artifact. Recording it because the
  same shape produced a false "5 tests are failing" report earlier in this lane --
  a stash control proves "not my diff", never "not a real failure"; the primary
  tree is what settles the second question.
- **HANDOFF STATE, read this first.** The target is narrowed to ONE loop and the method is the problem, not the target. `week_games`'s per-fixture assembly (`for fixture in fixtures`) is the cost: `assemble_s` 19.49 of a 20.78s call, `payload_s` under 7%, `dates` and league both ruled out. Same league + same 10 fixtures read 3.24s and 13.99s, so the VARIANCE is as interesting as the magnitude.
- ~~ONE REAL WIN, VERIFIED~~ **SEE RETRACTION BELOW.** cards-context TTL 600 -> 1200s (`SYNDICATE_SOCCER_CARDS_CONTEXT_TTL_SECONDS`, env only), left in place deliberately.
- **RETRACTED — THE 15x WAS A QUIET-vs-LIVE COMPARISON, NOT A BEFORE/AFTER.** I recorded `games()` 42.34s -> 2.76s as a verified TTL win. Re-measured 2026-08-28 19:10-19:24Z on a SETTLED worker (10-26 min uptime), the same call reads: `0.10, 0.13, 0.26, 0.37` **and** `51.60, 15.51, 10.87, 6.60`. Builds 8-10 min apart still rebuild COLD, well inside the 1200s TTL, so "the first call of each build now hits cache" is FALSE.
  LIKELY CAUSE, and the cache is behaving correctly: the key carries `_live_vintage`, which "changes the moment any match's status or clock moves". 19:00-19:30Z is European evening kickoff, so during live matches the fingerprint churns and every lookup misses REGARDLESS of the TTL. My 17:27Z reading was almost certainly a quiet period; I compared across an uncontrolled variable and attributed the difference to my change — the same error as reading two board-compute points as a trend earlier the same day.
  **THE TTL RAISE IS STILL CORRECT AND SHOULD NOT BE REVERTED** — it costs nothing and helps outside live windows. It is simply NOT a fix for soccer's cost, and soccer is expensive precisely WHEN IT MATTERS, during live matches, because the invalidation is doing its job.
  STILL A HYPOTHESIS: I did not confirm matches were live. Testable by comparing these numbers against a quiet overnight window.
- **THE COST IS STILL UNLOCATED.** soccer 163.2 -> 247.6 -> 381.6s in one day, ncaaf 34.1 -> 69.5s, GAME COUNTS FLAT — it scales with accumulation, not fixtures. The shard `soccer_source/artifacts/soccer/odds_history/<date>.json` went **3,935,768 -> 48,169,883 bytes (12x)**.
- MEASURED AND RULED OUT: `is_active_today` 0.0s · `bars` 0.0s · `games()` ~2.8s · `pregame_props()` 0.17s · `market_board` NOT ON THE PATH. `sport_branch` is **98%** of every sport's overview cost.
- **MEASURED SINCE `[2026-08-28 20:24Z / 21:12Z]`. THE COST IS PER-FIXTURE ASSEMBLY INSIDE `week_games`, AND IT IS NOT DATES, PAYLOADS, OR THE LEAGUE.**
  `_build_cards_page_context_uncached` splits as `week_games` **95-99.9%**, `board_contract` 0.00-1.28s, `setup` 0.00s.
  Inside `week_games`:
  ```
  league          total  dates  payload_s  assemble_s  fixtures
  la_liga          3.24    5       0.01       3.23        10
  primeira_liga    6.86    4       0.22       6.64        10
  la_liga         20.78    7       1.29      19.49        14
  la_liga         13.99    5       0.48      13.51        10
  ```
  `payload_s` is **under 7%**; `payloads_present == dates` every time, so there is no missing-artifact retry. The cost is the `for fixture in fixtures` assembly AFTER the payloads are loaded.
- **RETRACTED — MY REQUEST-SCOPED MEMO RECOMMENDATION.** I proposed memoizing `recommendations_payload` per build and sized it as the fix. **It would save at most ~1.3s of a 20.78s call.** The plumbing analysis behind it was correct and irrelevant: `games()` is an 8-implementation interface, `build_cards_page_context`/`week_games` need 3 signature changes, and memoizing `recommendations_payload` itself is FORBIDDEN (`@lru_cache` removed 2026-07-24 — matches froze at `status_state="pre"` 0-0 for days). All true, all aimed at 7% of the problem.
- **AND THE LEAGUE THEORY IS DEAD TOO.** `la_liga` week 3, SAME 10 fixtures, read **3.24s and 13.99s** — 4x apart on identical inputs. My `belgian_pro_league` 23.73s-for-12-games "19x" was one sample of a highly variable quantity, over-read exactly as I over-read the TTL 42.34->2.76s comparison. **The VARIANCE is now as interesting as the magnitude.**
- **SEVEN PREDICTIONS, SEVEN REFUTATIONS** on this subsystem in one session: ~39 leagues · fan-out · one slow league · props · TTL-dominance · the `market_board` multiplier (unreachable code path) · the payload memo. **DO NOT ADD AN EIGHTH LOG SPAN.** A profiler over ONE real build names the call directly; seven spans have cost a day and moved the target from "somewhere in soccer" to "the per-fixture assembly loop", which is real progress but at a poor rate.
- **FIVE PREDICTIONS, FIVE REFUTATIONS:** ~39 leagues (it is 10) · fan-out (one cold league dominates) · `championship` is slow (it is whichever is cold) · props is the missing 92% (0.17s) · the `market_board` 60s-TTL x 10 leagues x 48MB multiplier (**counter emitted ZERO — that function is not on the overview path**). See `learnings.md 2026-08-28` on instrumenting an unreachable function.
- **RECOMMENDATION TO THE NEXT SESSION: change method, do not add a sixth log span.** A profiler over ONE real build names the call directly; five incremental spans have cost a day and located 3s of 382s. My model of this subsystem is demonstrably poor and that is itself the evidence.
- Claims: `syndicate/blueprints/home.py` (transferred from UNOWNED `wnba-chip-live-token`, instrumentation only — path REMOVED from its Files: line, not struck through) and `syndicate/features/soccer/market_board.py`. Deploy claims: none held.
- Goal: name where soccer's 163.2s goes, per league, before optimising anything.
- Files: `syndicate/blueprints/home.py` (instrumentation only), `syndicate/features/soccer/sources.py`, `syndicate/features/soccer/cards.py`, `syndicate/features/soccer/props.py`, `tests/test_soccer_read_scope.py`, and its tests.
- MEASURED: soccer 163.2s = **82% of hydrated overview time**, from `OVERVIEW_SPORT_BEGIN`/`END` brackets 2026-08-28 03:39-03:42Z (ncaaf 34.1s, nfl 2.0s, everything else <0.2s). MLB is NOT the cost — it is 4.43s isolated.
- Hypothesis: `SoccerSport.games()` runs a NESTED loop — `for league in _active_leagues(today)` x `for week_offset in week_offsets` — calling `build_cards_page_context(league, week, season)` per pair. Soccer carries ~39 units/leagues where every other sport makes ONE call for a date or week, so the cost is the fan-out, not any single call.
- Falsification: wrong if the per-league total is a small fraction of the 163.2s, i.e. the cost is outside this loop.
- WHY INSTRUMENT FIRST, not tune: three hypotheses of mine died to measurement earlier this session (HTTP pulls 1.15s, Polymarket join 0.25s, venue-loop contention). Soccer's internals are currently unmeasured and anything else would be optimising an inferred shape.
- NOTE, already true and NOT the target: `SYNDICATE_HYDRATED_OVERVIEW_MIN_REBUILD_SEC` is already raised to 900 (default 300) and DOES fire (`OVERVIEW_REBUILD_RATE_LIMITED sport=soccer age_sec=577`), so soccer already skips some builds. Raising it further is a cadence lever, not a cost fix, and trades freshness across all eight sports.
- Verification: `[home] SOCCER_GAMES_TIMING` in production naming leagues, call count and elapsed, with the per-league total accounting for a material share of the 163.2s.
- Blocked by: none

### mlb-final-zero-placeholder — OPEN — opened 2026-08-28 — session 28195565
- Goal: a 0-0 "FINAL" in a sport that cannot end level is treated as the
  schedule placeholder it is, with a NAMED reason, instead of being passed
  through as an observed result.
- Files: NONE — **all claims RELEASED 2026-08-28 at checkpoint.** The code
  work is landed on `origin/main` (`eca7e81b`, verified ancestor) and the one
  remaining criterion is READ-ONLY production verification, so holding
  `game_chip_scoreboard.py` would block other lanes for nothing. Paths are
  named in the commit if this lane needs another code change.
  **NOTE for whoever takes `game_chip_scoreboard.py` next:** the guard now
  protects it for NEITHER this lane nor `wnba-chip-live-token` — see the
  release note in that lane's block. Put the path back on a `- Files:` line to
  re-arm it.
- **STATUS 2026-08-28 — SHIPPED TO `origin/main`, NOT DEPLOYED, NOT VERIFIED
  IN PRODUCTION.**
  - `eca7e81b` — the fix + 6 tests. 33 chip / 76 chip+scorer / 90 board-grid
    tests pass; reachability proven `off != on` (the reason string is
    producible only by the new branch; mlb/soccer/nfl/kabaddi differ).
  - `45b46d34` — the lane release from `wnba-chip-live-token`.
  - `cadfbe31` — `--date` on `snapshot_live_gameline_score.py` (separate
    concern, same session).
  - **Web is live on `56e77588`. Nothing is deployed from today's work**, so
    the 08-27 board still reports 644 phantom level finals.
- Hypothesis: CONFIRMED FROM PRODUCTION BEFORE ANY CODE. `/api/board/book-grid?sport=mlb&date=2026-08-27`
  returns `games_with_outcome=4` against `finals_seen=1462, finals_level=644
  (44%)` and `no_final_outcome_for_game=1304`. The 300-row sample carries five
  distinct states: four real score-pairs (COL@WSH 7-1, BAL@STL 7-5, HOU@NYY
  1-5, AZ@SF 6-1) and 114 rows at `final 0-0` (MIL@NYM, LAD@ATL, KC@TOR). Same
  instant, 08-26 reads `finals_seen=3115, finals_level=0`, 15 games. `is_final`
  (status text) and the score (`_side_score`'s seven candidates) are unrelated
  fields, so status can advance to FINAL while the score is still the
  placeholder.
- Falsification test: wrong if the 0-0 finals carry a real 0-0 scoreline
  somewhere upstream, or if the level rate is comparable on a healthy date.
  Neither holds — MLB cannot end 0-0, and 08-26 measured 0%.
- **THIS RECOVERS NO GAMES, and must not be reported as if it does.** The
  scores are absent from the payload and `build_finals_index` already skipped
  these rows for MLB. It fixes the MISREPORTING: 644 placeholders counted as
  observed finals, which aimed the diagnostics at the scorer rather than at the
  missing upstream data. The 11 lost games stay lost on this path.
- Applies `learnings.md 2026-08-28` ("grading an AMBIGUOUS zero as a definite
  outcome"): refuse with a NAMED reason rather than suppressing silently.
- Verification: (a) MLB `final 0-0` suppressed AND carries its reason;
  (b) soccer `final 0-0` PRESERVED — nulling it would re-break the draw fix
  `a293bf14`; (c) MLB `live 0-0` preserved; (d) unknown sport preserved
  (allowlist, never a negation); (e) existing pregame/live tests still pass.
  **(a)-(e) ALL PASS IN TESTS. (f) IS OWED AND IS THE ONLY ONE THAT COUNTS:**
  on a deployed build, `/api/board/book-grid?sport=mlb&date=<a date with
  placeholder finals>` must show `finals_level` FALL (644 -> ~0 for 08-27)
  while `games_with_outcome` does NOT drop on a healthy date (08-26 must stay
  15). A unit-test pass is not that reading — the whole defect was a
  placeholder that every test-level check found plausible.
- **DO NOT re-derive:** this recovers NO games. 08-27 stays capped at 4 of ~15
  because the scores are absent from the payload, not misclassified. If a
  future run sees `games_with_outcome` still 4 after deploy, that is EXPECTED
  and is not a failure of this fix.
- Blocked by: a deploy. Not urgent — the defect is misreporting, not data loss.
- **RIDES ALONG — DO NOT FIRE A SEPARATE refresh-worker DEPLOY FOR THIS
  `[2026-08-28 15:1xZ]`.** All three commits (`74f026a9`, `cadfbe31`,
  `eca7e81b`) sit BEFORE `c748a239` and `481c4b30` on main, so ANY
  refresh-worker deploy of those — or of tip — carries them by construction.
  `portfolio-venue-and-side-integrity` owes exactly that deploy: `c748a239` is
  its real-money fix ("Polymarket has been buying the wrong team") and its
  files (`paper_settlement.py`, `polymarket_us_orders.py`,
  `intelligence_state.py`) are worker-side. It deployed **web** to `90ed748b`
  and not refresh-worker. A second deploy would buy nothing and cost a worker
  reboot plus an in-flight board build.
- **VERIFICATION OWED ON WHOEVER'S DEPLOY LANDS — please take this reading:**
  `/api/board/book-grid?sport=mlb&date=2026-08-27` should show `finals_level`
  fall from **644** toward ~0 and `live_gameline_accuracy` stop being `null`,
  **WHILE 08-26 STAYS AT `games_with_outcome: 15`**. The second half is the one
  that matters — it is what catches the fix over-suppressing. `games_with_outcome`
  for 08-27 staying at **4** is EXPECTED and is not a failure.
- **web is NOT in the path and needs nothing** — it already runs all three
  (live `90ed748b`). Measured 2026-08-28 15:09:55Z: web served a FRESHLY
  generated 08-27 payload while carrying `eca7e81b`, and `finals_level` was
  still 644 with `live_gameline_accuracy` still null. Presence is not
  reachability — the scores are baked into the artifact by the board build on
  refresh-worker, which is the only choke point.

### venue-join-refusal-visibility — OPEN — opened 2026-08-28 — session d617eefd-1628-4795-9e11-7b6aaa3f2ff3
- **`[2026-08-29 15:3xZ]` SECOND REPLY FROM `soccer-overview-cost` — your session was
  again unreachable by cross-session message, so it is here.**
  **CLAIM RELEASED, refresh-worker is `free`. Take it.**
  **YOUR BOOT ASSUMPTION IS WRONG AGAIN, IN THE SAME DIRECTION.** `3f0e4f1d` is NOT
  in my deployed `1fbc7a62` (`git merge-base --is-ancestor` -> false;
  `git log 1fbc7a62..3f0e4f1d` is exactly your one commit). It landed AFTER my
  15:22:02Z deploy. **You need your own deploy.** Twice now: main moves under both
  of us, so check ancestry at DEPLOY time, not at message time.
- **YOUR JOIN FIX VERIFIED INDEPENDENTLY BY `soccer-overview-cost`, AND IT IS
  BIGGER THAN YOU CLAIMED.** Re-derived rather than taken, because it changes MY
  baseline. `POLYMARKET_BOARD_JOIN`, 2026-08-29 04:00Z -> 15:30Z:
  ```
  elapsed_s 279 250 271 251 276 250 245 238 261 258 266 257 268 304 290 312 282 291 349.77 | 201.41 175.9
  matched    39  39  39  39  46  96  96  96  91  91  90  87  87  86  85  85  83  89     85 |    133   135
  ```
  Not just ~175s off the wall clock: **`matched` went 85 -> 135 across the same
  boundary.** You removed a scan AND the join got strictly better. Put BOTH
  numbers in your lane -- the elapsed alone undersells it.
- **CREDIT, STATED SO NEITHER OF US MIS-ATTRIBUTES:** my board-cost baseline
  (builds 900-2000s, `state.md [board-window-staleness]`) predates this. **~100-175s
  of any board-build improvement measured after 15:1xZ is YOURS, not soccer work.**
- **HEADS-UP, IT LANDS ON YOUR CHANNEL:** `SYNDICATE_SPORT_OVERVIEW_PROFILE=soccer`
  is set on refresh-worker. It runs cProfile over soccer's `sport_branch` and emits
  ~60 `[home] SPORT_BRANCH_PROFILE` lines per hydrated build, ~1.3-2x overhead on
  soccer's branch only. Mine, not a regression. Being turned back off as soon as two
  settled samples land. `be3f2afc` made `...=off` an explicit disable, because
  Render's env API rejects an empty value (HTTP 400) and `off` previously worked
  only by the coincidence that no sport is named `off`.
- **`[2026-08-29 ~04:50Z]` REPLY FROM LANE `soccer-overview-cost` — you asked me by
  cross-session message and your session was no longer reachable when I answered,
  so it is here instead.**
  **A REFRESH-WORKER DEPLOY ALREADY WENT OUT: `dep-da964qqjnfac73cqb0ag`,
  `3e2cbd0b`, 04:39:08Z.** Preflight was CLEAR at 04:38:33Z (3 processes, all
  infra), so **no MLB sim was killed** — that cost is paid, do not pay it twice.
  Which of your three it carries, checked BY CONTENT, not by commit message:
  - corners re-keyed onto `cor-all` (`0e61720d`) — **IN**.
  - `_has_segment` screening `fh`/`sh` — **IN**. Verified by reading the deployed
    blob (`git show 3e2cbd0b:syndicate/features/shared/polymarket_board_join.py`),
    which carries the `fh`/`sh` docstring and the 62+62 census note. **The live
    full-game-BTTS mispricing is fixed on this boot.**
  - `8c53d701` board-dates-by-SLATE / 2,038 unreachable markets — **OUT**, it
    landed after the deploy. `git log 3e2cbd0b..8c53d701` is exactly that one
    commit. It is the ONLY one still needing a deploy.
  **COUNTER TRAP, the reason this note matters more than the ETA:**
  `soccer_prop_shapes=` IS in `3e2cbd0b` (`pipeline/portfolio_commit.py:246`) and
  is readable off this boot. **`forward_date_widened=` IS NOT** — it exists only in
  `8c53d701` (`portfolio_commit.py:249`, `polymarket_board_join.py:856/1188`). On
  this boot that field is never emitted, and **a missing field is not a zero**:
  reading nothing there means "not deployed", NOT "the widening found nothing".
  Claim `refresh-worker` is held by `soccer-overview-cost` for a settled-worker
  measurement (~06:00-06:30Z). Break it with `--force` if item 3 is worth more
  than my timing number — it probably is, and I would rather you did.
- Goal: make the exchange-execution joins SAY why they refuse, and fix the
  refusals that are ours. Four items `[user 2026-08-28]`.
- Files: `pipeline/portfolio_commit.py`, `syndicate/blueprints/ops.py`,
  `syndicate/features/shared/polymarket_board_join.py`,
  `syndicate/features/shared/team_aliases.py`,
  `scripts/audit_polymarket_coverage.py`,
  `tests/test_polymarket_spread_audit_hook.py`,
  `tests/test_polymarket_spread_sign_rung.py`,
  `tests/test_polymarket_board_join.py`, `tests/test_team_aliases.py`,
  RELEASED `[2026-08-28, session d617eefd]`: `syndicate/features/shared/execution_ledger.py`
  RELEASED `[2026-08-28, session d617eefd]`: `tests/test_execution_ledger.py`
  — claimed to fix `#600`, then DROPPED UNAPPLIED. Lane
  `portfolio-venue-and-side-integrity` shipped `f66c7441` while I was
  implementing, and theirs is better: a three-way merge against a per-order
  fingerprint captured at `_load()`, so it detects what the caller changed
  WITHOUT a `touched` argument. That covers the four external callers in
  files I could not edit, and handles deletion, which my design left
  unguarded. My commit was reset, not merged. Do not resurrect it.
- Claim provenance: RECLAIMED from three lanes whose sessions were verified
  gone in-session via `list_sessions(include_archived=true)` —
  `open-bet-live-status` (`local_f08f0df5`, archived),
  `portfolio-decision-and-execution` / `9324a3e5` (absent from the roster),
  `kalshi-spread-join-sign` (states ALL CLAIMS RELEASED). Struck in each donor
  block. Any of them reclaims by striking the note.
- Deliberately NOT claimed: the Polymarket SIDE-resolution path and the
  portfolio page — live under `portfolio-venue-and-side-integrity`.
- STATUS: **3 of 4 items VERIFIED IN PRODUCTION. 1 measurement PENDING A DEPLOY.**
  - item 1 Kalshi `reasons=` — **VERIFIED** 16:13:11Z
  - item 2 spread sign audit — **VERIFIED as NON-IDENTIFYING** 16:06:53Z. Closed
    as "not answerable by this instrument", NOT as fixed. Behaviour unchanged:
    spreads were refused before and are refused now.
  - item 3 soccer bucketing — **fix VERIFIED, outcome UNCHANGED.** 13
    competitions proven incl. `mls`; ops reader 738 -> 1,809. But
    `no_match|soccer|h2h` is 93 of 93 board rows. The hypothesis was half
    wrong: those rows were already `no_match`, not `no_candidates`.
  - item 4 ops reader/join agreement — **VERIFIED** (web `8b8a6579`)
- **MEASURED 2026-08-28T17:40:42Z — the orientation thread has its number and
  the hypothesis is DOWNGRADED, not confirmed.** `soccer|h2h` flipped **10 of
  106 tried** (9.4%), `soccer|totals` 2 of 27. I had called orientation "the
  actual blocker" on ONE fixture; it explains a tenth. The other ~96 soccer
  h2h refusals have a cause still unidentified. **Do not ship a flip** — a
  per-sport slug-order difference would show near 100%, not 9.4%, and a blanket
  flip breaks the ~90% pairing correctly today.
- **THE CONTROL IS THIN AND `mlb` IS UNTESTED, which is exactly what `tried=`
  was added to expose.** `mlb` appears in no `tried` key: 35 unmatched
  game-line rows, flip attempted on ZERO (spreads/totals only attempt at the
  board's own line). Its absence from the rescue counter means nothing. Only
  h2h control is `nfl|h2h` 0 of 3; 13 non-soccer attempts total. The second
  reader's critique landed one run before it would have misled us.
- Next: check whether the BOARD has these fixtures inverted rather than the
  venue (`Man City @ Crystal Palace` 2026-08-28 against any fixture list) —
  cheaper than reasoning about slug grammar. See `#598`.
- **REMAINING OPEN THREAD:**
  `POLYMARKET_ORIENTATION` (`432c5915`) counts, per `<league>|<market>`, rows
  that would pair with the slug's sides swapped. MLB/NFL are the control. It
  has **never run in production** — refresh-worker's live SHA `6078536b` does
  not contain it (checked by `git merge-base --is-ancestor`, not timestamps).
  Needs one refresh-worker deploy of `432c5915` or later, then the first board
  publish (~21 min from boot).
- Verification: `POLYMARKET_ORIENTATION would_match_if_flipped={...}` non-empty.
  Soccer high with mlb/nfl near zero => the slug order differs by sport.
  Soccer high WITH mlb/nfl high => the orientation reading is WRONG and the
  cause is elsewhere. **DO NOT APPLY A FLIP on one fixture** — same shape as
  the `pos`/`neg` trap, which fired twice today.
- Deploy claims: ALL RELEASED. Deployed this lane: web + live-odds-worker +
  refresh-worker, each recorded in `deploys.md` with its reading. The
  refresh-worker claim was FORCED once on explicit user instruction (holder was
  ACTIVE, not gone) — recorded there.
- TODO ids: `#597` (Kalshi soccer title grammar) and **`#598`** (the
  orientation measurement). `#598` was filed by this lane as `#596` and
  RENUMBERED by `portfolio-venue-and-side-integrity` (`d99d1672`) because we
  both declared `#596` and theirs landed first — verified here, not taken on
  their word: `git merge-base --is-ancestor 90ed748b d44e643d` is true. Their
  renumber is correct and touched `todo.md` only.
  **Checkpoint commit `d44e643d`'s message still says "Filed #596"** — it is
  pushed and immutable, so a reader following it lands on THEIR item. The id
  to use is `#598`.
- **EXPOSURE CHECK against `#600` (execution-ledger cross-service race), done
  rather than assumed.** A peer found that `execution_ledger._persist` is a
  blind whole-document `write_json_file` with no lock or merge, and that
  refresh-worker and live-odds-worker both read-modify-write it, so the last
  writer wins with whatever it loaded. **Verified here independently** from
  both services' own `KEYVALUE_WRITE_LARGE` lines: refresh-worker wrote
  1,276,296 B at 17:40:48Z, live-odds-worker wrote 1,272,699 B at 17:52:47Z —
  **3,597 bytes SMALLER, twelve minutes later.** The ledger moved backwards.
  `_persist` confirmed by reading it: `write_json_file(_ledger_path(), state)`.
  **THIS LANE'S FINDINGS ARE NOT EXPOSED.** Every verification recorded for
  items 1-4 and the orientation number comes from LOG LINES
  (`KALSHI_BOARD_JOIN`, `POLYMARKET_UNMATCHED`, `POLYMARKET_ORIENTATION`,
  `SPREAD_SIGN_AUDIT`, `ORDER_PATH`) or from board/slate ARTIFACTS
  (`/api/board/layer2-shortlist`, `/api/ops/polymarket/slate`) — none from
  the execution ledger. Checked, not asserted.
  **WHAT IS EXPOSED:** the order/stake counts quoted from
  `/api/ops/execution/ledger-summary` early in this session (`live:polymarket`
  21 orders / $65.88 and similar). Those were descriptive colour, never
  load-bearing, and should be re-read rather than cited.
  This lane writes the ledger via `execute_portfolio` -> `place_order`, so it
  is on the OTHER side of the same race. Not fixing it: concurrency on the
  money path, and `execution_ledger.py` is claimed by
  `portfolio-ledger-service-split`.
- **CONTESTED: `syndicate/blueprints/ops.py` — TWO LIVE OPEN HOLDERS, NOT
  RESOLVED** `[flagged 2026-08-28 ~15:0x CDT, session 29794bbe]`. Held by BOTH
  `portfolio-venue-and-side-integrity` (session `12b2be57`) and
  `venue-join-refusal-visibility` (session `d617eefd`). Four other contested
  files were cleared in the same pass; this one was DELIBERATELY LEFT, because
  both sessions are live and neither claim is stale: transcript last entries
  **19:44:52Z** and **19:40:17Z**, i.e. minutes before this note. Neither lane
  body says what it does to this file, so the ledger cannot decide it either.
  **Whichever of the two finishes first: release it here in the single-line
  form** — ``RELEASED `[date, session]`: `syndicate/blueprints/ops.py` `` — a
  marker only governs its OWN line, so a path on a continuation line still
  reads as a live claim (that mis-shape is what produced three of the four
  contests cleared today). Until then `lane-guard` will block the second
  editor, which is the system working, not a defect.
- Blocked by: none. Next refresh-worker deploy by ANY lane carries the counter.


### cryptocom-finding-correction — **CLOSED 2026-08-28** — VERIFIED AND LANDED on `origin/main` as `ceb3c830`. `FINDING` no longer asserts the falsified "no public REST/WebSocket market-data API has shipped" (a JSON sports endpoint exists and was read live), `rejected_source` -> `corrected_source` (the endpoint is Crypto.com's OWN documented sample, not a third party's invention — right decision, false reason), and `probe()`'s false-positive gate is replaced: `unblocked` defaults False and flips only on a non-crypto `inst_type` in the SANCTIONED Exchange catalogue. 16 tests pass including an off!=on pair proving the gate flips both ways; the old assertions were confirmed to FAIL first. Live run: `unblocked=False reason=exchange_rest_lists_no_event_contracts`, EXCHANGE_REST 957 instruments / non_crypto=0, APP_PROXY http_403. Evidence: `.syndicate/findings_2026-08-28_cryptocom_venue_evaluation.md`. Nothing deployed; no deploy claim taken. — opened 2026-08-28 — session 29794bbe-33cb-45fc-a046-136e18ef3e06
- Goal: `cryptocom_client.py`'s `FINDING` and `probe()` state what was MEASURED
  on 2026-08-28, not what was inferred from a sandbox that could not reach the
  venue. Single testable outcome: `probe()` returns an explicit `unblocked`
  flag computed ONLY from a sanctioned, server-side-readable surface, and
  `FINDING` no longer asserts "no public REST/WebSocket market-data API has
  shipped" — an undocumented JSON sports endpoint exists and was read.
- Files: `syndicate/features/shared/cryptocom_client.py`,
  `scripts/probe_cryptocom.py`, `tests/test_cryptocom_client.py`.
- **CROSS-LANE EDIT, EXPLICIT USER OVERRIDE `[2026-08-28, user: "fix the
  cryptocom_client.py finding with what you found"]`.** These three files are
  claimed by `exchange-markets-api-integration` (`lanes.md` above; OPEN, goal
  complete, lane idle, session `71a74bb7` GONE). Protocol is to stop and
  surface the conflict, which is what this line does; the user's instruction is
  the override and is logged here rather than acted on silently. No file
  outside the three above is touched, and the other lane's other five venue
  clients are untouched.
- Hypothesis: n/a — this is a record correction, not a diagnosis. What is being
  corrected was itself a diagnosis made without egress.
- Falsification test: the claim being removed ("no public market-data API")
  would be re-established if the endpoint
  `web.crypto.com/api/proxy/public/knock-out/predictions/public/api/v1/events`
  did NOT return sports rows. It returned 200 with 200 MLB rows
  (`event_kind_asset_type: "sports"`) on 2026-08-28. Kept as the falsifier
  because it is the one reading the correction rests on.
- Verification: `python -m pytest tests/test_cryptocom_client.py` passes with
  tests that assert the NEW facts (a test asserting the old
  `status == "no_public_api_yet"` string must fail before it is updated —
  off != on), plus `python scripts/probe_cryptocom.py` printing
  `unblocked=False` with a NAMED reason from a live run.
- Blocked by: none. Nothing here is deployed or committed without a further
  instruction; no deploy claim taken.

### finals-silent-score-drop — CLOSED 2026-08-29 — opened 2026-08-29 — session 4ca1d41c-7532-44dc-87ff-cec47f1f07d0
- **OUTCOME: the cap is attributable from the served payload. `date=2026-08-28`
  now reports `finals_skipped_no_numeric_score_games: 11` where it previously
  reported nothing at all.** All four verification criteria discharged, (a) on a
  LIVE DEPLOYED build. No game recovered and no scored number moved, as
  specified.
- Goal: the largest cause of lost `games_with_outcome` STOPS being the one path
  in the scorer that increments no counter. A final dropped for having no
  numeric score is COUNTED and NAMED, so the cap is attributable from the
  served payload alone.
- Files:
  - `syndicate/features/shared/live_gameline_score.py`
  - `tests/test_live_gameline_score.py`
- **THIS DOES NOT RE-OPEN THE SCORER EXONERATION** (`lanes.md` 2026-08-27, "do
  not go looking for a scorer bug"). The scorer is RIGHT to refuse a final with
  no score; refusing SILENTLY is the defect. Observability, not correctness. No
  scoring maths changes and no game is recovered.
- Hypothesis: CONFIRMED FROM PRODUCTION BEFORE ANY CODE `[2026-08-29 ~14:4xZ]`.
  `/api/board/book-grid?sport=mlb&date=2026-08-28` (artifact regenerated
  14:31:06Z, stable across 3 fetches) reports `games_with_outcome=1`,
  `records_considered=6466`, `no_final_outcome_for_game=6137`. A `limit=2000`
  sample resolves the cause exactly: **15 distinct `event_id` on the grid — 12
  `final`, 3 `pregame` — and of the 12 finals only ONE carries numeric scores**
  (Reds 10 @ Cubs 8). The other 11 are `state: final, home_score: None,
  away_score: None`, nulled upstream by `game_chip_scoreboard.py:465`
  (`level_final_impossible_for_sport`). `build_finals_index` then hits
  `float(None) -> TypeError -> continue`, and **that `continue` sits BEFORE
  `diag["finals_seen"] += 1`**, so 11 of 15 games leave NO trace in any
  counter. The index ends with one key; `games_with_outcome=1` follows.
- The counters that DO exist point away from the cause: `finals_seen=196`,
  `finals_level=0`, `finals_skipped_level=0`,
  `finals_skipped_level_sport_unknown=0`. Reading those alone, the finals index
  looks healthy and the blame lands on the ledger/join. It is neither.
  (`learnings.md` "Instrument blindness": a healthy reading is evidence only
  once you know what makes it read unhealthy.)
- **NEW AND NOT PREVIOUSLY RECORDED — a `--date` backfill DECAYS.** The same
  date, scored off two different artifact builds ~9 minutes apart:
  `14:22:04Z -> 4 games`, `14:31:06Z -> 1 game`. Each rebuild of a PAST date
  re-reads the CURRENT scoreboard, which retains fewer of yesterday's scores as
  the feed rolls forward. So `snapshot_live_gameline_score.py --date` is not
  time-neutral: the later it runs the fewer games survive, and an on-time
  capture is worth strictly more than any recovery. This is the mechanism
  behind the scheduled task's "a recovered night can be incomplete" note, and
  it is WHY — the note recorded the symptom only.
- Falsification test: wrong if the 11 scoreless finals carry a real score
  anywhere in the served payload (they do not — `game` holds exactly
  `away_score, home_score, matchup, start_time_utc, state, status_token`, and
  both score fields are `None` on all 11), or if adding the counter changes any
  Brier or any `games_with_outcome` (it must not — a pure diagnostic).
- Verification:
  (a) a new `finals_skipped_no_numeric_score` counter reads **11** for
      `date=2026-08-28` on a rebuilt artifact, and `finals_seen` + that counter
      account for every `final` row on the grid;
  (b) `off != on` reachability — a test asserting the counter is ABSENT must
      fail before the change (the counter is producible only by the new branch);
  (c) `games_with_outcome`, every Brier and every `n` are BYTE-IDENTICAL before
      and after on the same fixture — this recovers no games and must not move
      a single number;
  (d) `python -m pytest tests/test_live_gameline_score.py` passes.
- **STATUS 2026-08-29 — LANDED ON `origin/main` AS `aa8f13bc`. NOT DEPLOYED.
  No deploy claim taken; none needed to push.**
  Verified BY CONTENT, not by ancestry (`learnings.md`: a live SHA need not be
  an ancestor of main): `git show origin/main:syndicate/features/shared/
  live_gameline_score.py` carries `finals_skipped_no_numeric_score` (5
  occurrences) and the reachability test is present in the landed test file.
  Push was CODE-ONLY — two `.py` files, **no `render.yaml`**, so it fired no
  `blueprint_sync` and applied nothing to production.
  Rebased from `session/finals-silent-score-drop` (`82fa5e1b` pre-rebase);
  `3a016554..aa8f13bc`. Ledger/lane and todo-id checks clean at land time.
  **The counter is INERT until a refresh-worker deploy plus a past-date
  artifact rebuild** — the board build is the only choke point that bakes
  `finals_index` into the artifact, and web already proved presence != reachability
  for the sibling fix on 2026-08-28 15:09:55Z. Ride along; do not fire a deploy.
  Worktree `C:	mp\syndicate-sessionsinals-silent-score-drop`, branch
  `session/finals-silent-score-drop` off `origin/main` `9618cc75`.
  Two counters, because `finals_seen`/`finals_level` count ROWS and the
  question anyone asks is about GAMES:
  `finals_skipped_no_numeric_score` (rows) and
  `finals_skipped_no_numeric_score_games` (games, reported NET of the index so
  a game skipped on one row and indexed from another is not called lost).
  - (b) **REACHABILITY PROVEN, `off != on`.** The 3 counter tests fail against
    the pre-change source with `KeyError: 'finals_skipped_no_numeric_score'`.
  - (c) **NO NUMBER MOVES.** The invariance test passes against BOTH the old
    and new source — that is the proof, not a claim. 74 tests green across
    `test_live_gameline_score.py`, `test_live_gameline_accuracy.py`,
    `test_game_chip_scoreboard.py`.
  - (d) `python -m pytest tests/test_live_gameline_score.py` — **19 passed**.
  - (a) **DISCHARGED IN PREDICTION, over REAL production payloads** (new code
    run locally against `/api/board/book-grid?sport=mlb&limit=2000`, not a
    fixture). Sample-bounded where noted; the server scores the full grid:

    | date | rows sampled | NEW rows skipped | **NEW games lost** | `finals_seen` | `finals_level` | games indexed |
    |---|---|---|---|---|---|---|
    | 08-28 | 2000 of 3122 | 1429 | **11** | 129 | 0 | 1 |
    | 08-27 | 1462 of 1462 (COMPLETE) | 644 | **3** | 818 | 0 | 4 |
    | 08-26 | 2000 of 3115 | 0 | **0** | 2000 | 0 | 15 |

  - **08-28 reads exactly 11 games lost, matching the hand count of scoreless
    finals (12 finals, 1 scored). The cap is now attributable from the payload.**
  - **08-27's 644 skipped ROWS is EXACTLY the `finals_level: 644` that
    `mlb-final-zero-placeholder` measured before its fix.** The placeholders did
    not vanish, they moved from one counter to the other — an independent
    cross-check that this counter catches precisely the population that fix
    stopped mis-labelling, and that the two changes compose rather than overlap.
  - **08-26 (the healthy date) reads 0 lost / 15 indexed**, so the counter does
    not fire on a good day and this is not a constant offset.
- **(a) DISCHARGED ON A DEPLOYED BUILD `[2026-08-29 ~16:3xZ]` — RODE ALONG, NO
  DEPLOY FIRED BY THIS LANE.** `refresh-worker` went live on `6625b5e6`, which
  is NEWER than `aa8f13bc`; verified BY CONTENT (`git show 6625b5e6:…/
  live_gameline_score.py` carries the counter, 5 occurrences) rather than by
  ancestry, and `pending_deploys.py` no longer lists `aa8f13bc` for that service.
  Served payload, `/api/board/book-grid?sport=mlb&date=2026-08-28`, artifact
  regenerated 16:31:06Z, re-read after two unrelated web deploys settled:

      finals_seen                            196
      finals_skipped_no_numeric_score       2258   (rows)
      finals_skipped_no_numeric_score_games   11   (GAMES -- the number that matters)
      games_with_outcome                       1

  **11 is exactly the figure predicted from the local run over the production
  payload before the deploy**, and exactly the hand count of scoreless finals
  (15 games, 12 final, 1 scored). `finals_seen + skipped = 2454` final rows of
  3122 total, consistent with the 2,432 implied by a 2,000-row sample; the
  accounting is exact BY CONSTRUCTION (every `final` row takes exactly one of
  the two branches) and is unit-tested, so the sample extrapolation is a
  cross-check, not the proof.
- **08-27 and 08-26 correctly report the counters as ABSENT** — their artifacts
  date from 04:45:59Z and 08-28T03:48Z, both BEFORE the deploy. That is not a
  failure: it confirms the counter appears only on artifacts rebuilt under the
  new code, which is itself evidence the 08-28 reading is genuine rather than
  coincidental. It also means this lane did NOT discharge
  `mlb-final-zero-placeholder`'s owed 08-26 over-suppression reading, which
  still needs 08-26 REBUILT.
- Blocked by: nothing. CLOSED.
- **Superseded note — the old blocker line, kept for the record:** the reading
  below was written as needing a deploy this lane must not fire. It rode along
  on another session's, exactly as intended.
- Blocked by: none for the code. Reading (a) needs a refresh-worker deploy plus
  a past-date artifact rebuild; it must RIDE ALONG on another lane's deploy
  rather than firing one — a diagnostic counter does not justify a worker
  reboot or an in-flight board build.

### READINGS TAKEN FOR ANOTHER LANE — `mlb-final-zero-placeholder` `[2026-08-29 ~15:2xZ]`
That lane's block asks, verbatim, "VERIFICATION OWED ON WHOEVER'S DEPLOY LANDS
— please take this reading". I was in the payload already, so here it is.
Single fetch per date, same instant, `/api/board/book-grid?sport=mlb&date=…`:

| date | artifact generated | `finals_seen` | `finals_level` | `games_with_outcome` |
|---|---|---|---|---|
| 08-26 | 2026-08-28T03:48:26Z | 3115 | 0 | 15 |
| 08-27 | 2026-08-29T04:45:59Z | 818 | **0** (was 644) | 4 |
| 08-28 | 2026-08-29T15:26:46Z | 196 | 0 | 1 |

- **08-27 half: DISCHARGED, PASS.** `finals_level` fell **644 -> 0** on an
  artifact regenerated at 04:45:59Z, i.e. AFTER the 04:39:08Z refresh-worker
  deploy (`dep-da964qqjnfac73cqb0ag`, `3e2cbd0b`) that carried `eca7e81b`.
  `games_with_outcome` stayed **4**, which that lane predicted in advance and
  labelled EXPECTED. The fix is live and behaves as specified.
- **08-26 half: NOT DISCHARGED — DO NOT BANK IT.** It reads 15, but its
  artifact was generated **2026-08-28T03:48:26Z**, which PREDATES the deploy,
  so it was never rebuilt under the fix. 15 is a pre-fix number and is
  therefore no evidence about over-suppression. The over-suppression check is
  still owed and needs 08-26 REBUILT. (`learnings.md` "Test the fix's
  predicate, not its deploy state" / "presence is not reachability".)
- **`live_gameline_accuracy` is ABSENT, NOT `null` — that criterion is
  UNMEASURABLE ON THIS ENDPOINT.** `book_grid_artifact.py:398` writes the key
  into the artifact, but `syndicate/blueprints/intelligence.py` contains ZERO
  references to it, so the route never passes it through and the key is not in
  the served payload at all. A `.get()` returning `None` here means "key
  absent", which is exactly the reading that lane recorded as "still null" on
  2026-08-28. That was never a signal about the recorder. Whoever closes that
  lane must read the field where it actually lives (the artifact on
  refresh-worker) or serve it first.

### ncaaf-no-orders — OPEN — opened 2026-08-29 — session 7b278ebe-b1fa-4ea4-9648-834fb63961b7
- Goal: name the FIRST stage in the NCAAF chain that is zero, with a production
  number at that stage and at the stage before it. NCAAF is emphatically on the
  board (`BOARD_OVERVIEW_READY` 2026-08-29 `ncaaf:g=51`; `INTEL_TRACE`
  `by_sport ncaaf: 213` of 606 scored candidates) and yet **0 NCAAF rows exist
  in the execution ledger across 2026-08-24..08-29 — 1,207 rows, every one
  mlb/wnba/nfl/soccer.** Measured via `/api/portfolio/paper?date=`, whose
  `bet_status.rows` carry `sport`.
- Files: `scripts/generate_smartsim2_ncaaf_projections.py`,
  `syndicate/features/ncaaf/cfbd.py`,
  `syndicate/features/ncaaf/cfbd_backoff.py`,
  `tests/test_cfbd_backoff.py`,
  `scripts/run_refresh_worker.py`,
  `tests/test_season_projection_staleness.py`
  (the last two added 2026-08-29 by USER OVERRIDE — `exchange-markets-api-integration`
  released the worker entrypoint; see its Files line.)
- Reads but does NOT claim (the parser turns any path inside a `- Files:` block
  into a CLAIM, so this is deliberately kept out of it): the portfolio commit
  module is held by `venue-join-refusal-visibility`. READ-ONLY to this
  lane; if a fix needs either, surface the conflict first.
- Hypothesis: **the NCAAF season-projection artifact has not rebuilt since
  2026-08-26 because every rebuild dies on CFBD `HTTP 429`, so NCAAF rows carry
  no model probability and are refused `no_model_edge_pct` before sizing.**
  Supporting, not yet decisive: `SEASON_PROJECTION_LAUNCHING sport=ncaaf` fires
  every few minutes with `reason=artifact_stale` and a MONOTONICALLY GROWING
  `age_seconds` (228,608 -> 238,496 over 2h45m on 08-29), each launch ending in
  `urllib.error.HTTPError: HTTP Error 429: Too Many Requests` at
  `generate_smartsim2_ncaaf_projections.py:66 (_cfbd_get)` via
  `load_ppa_ratings:179` <- `load_ppa_ratings_asof:271` — the prior-season
  fallback. Today's plan refuses `no_model_edge_pct: 843` of `rows_in: 1291`,
  and `sim_coverage.rows_without_sim_edge` is **exactly 843**, so that refusal
  IS the no-sim-edge population.
- **THIS IS A RE-OCCURRENCE, NOT A DISCOVERY.** `learnings.md` 2026-08-27
  ("FORBIDDEN: inferring that a scheduled job SUCCEEDS from an age that sits at
  one interval") records four NCAAF projection runs 21:21:37-21:23:31Z dying on
  the same `HTTP 429` in the same function. That entry fixed the INSTRUMENT
  (age is stamped by the launcher, not by success) and left the 429 itself
  unaddressed. Two days later the artifact is 2.76 days stale.
- Falsification test: the hypothesis is WRONG if NCAAF rows are absent from
  `rows_in` altogether (filtered upstream of sizing — a venue/board-join
  problem, not a model problem), or if NCAAF rows are present WITH a
  `model_edge_pct` and refused for some other reason. Either result moves this
  lane to a different stage and the 429 becomes a real but separate defect.
  Decisive read: per-sport breakdown of the plan's candidate rows, not the
  by-market counts the endpoint currently serves.
- Verification: a named stage with a production count on both sides of it.
  Diagnostic only — no fix, no deploy, until the stage is named.
- **RESULT 2026-08-29 — STAGE NAMED, AND MY HYPOTHESIS IS FALSIFIED. NOTHING IS
  BROKEN: NCAAF IS WITHHELD FROM SIZING ON PURPOSE.**
  Decisive read, production, `/api/board/layer2-shortlist?date=2026-08-29&limit=2000`
  (the default `limit=200` shows only 2 NCAAF rows and would have misled; the
  plan sizes over the full `cards_present=1291`, which matches the plan's
  `rows_in`):

      ncaaf candidate rows            90   (h2h 3, spreads 3, totals 84)
      ...carrying `model_edge_pct`     0   <- the zero stage
      mlb  307/400   soccer 121/400   wnba 20/400   (for contrast)

  All 90 are therefore refused `no_model_edge_pct` at
  `shared/portfolio_commit.py:210` before Kelly, so 0 sized -> 0 orders -> 0
  ledger rows. That matches the 6-day ledger census exactly.
  The 90 split: **40 carry no `projection` at all; 50 carry one whose
  `edge_vs_market_pct` is NULL**, each with an explicit
  `edge_unavailable_reason` — 44 totals *"totals are 1.67x over-dispersed
  against the market and were never scored against the close"*, 6 margin
  *"margin model loses to the closing line by 3.563 points of MAE over 2233
  games (t=17.2)"*.
  Source: `syndicate/features/football/pick_gate.py` `_SERVING_REGISTRY` —
  `("ncaaf","spread")`, `("ncaaf","moneyline")` and `("ncaaf","total")` are all
  `servable=False`, measured 2026-08-19, 2023 SP+ -> 2024 games, clean
  out-of-sample (`graded_leak_status {'clean': 2236}`). Its docstring is
  explicit that DEFAULT IS DENY and that generation/display continue so the
  measurement that lifts the gate can still be taken.
- **EXONERATED: the CFBD 429 loop is NOT the cause.** The suppression reasons
  are STATIC verdicts about measured model skill (n=2233, t=17.2) and about
  totals never having been scored at all — a fresh artifact would carry the
  same two strings. So `no_model_edge_pct` would still be 90/90 with the
  projections rebuilt. I recorded the 429 as the hypothesis before testing it
  and it does not survive; saying so here rather than letting the strong
  supporting numbers stand in for a cause. `learnings.md` 2026-08-29 already
  FORBIDS naming a cause from a mechanism visible without showing it is the
  operative one — this is that rule firing on me.
- **STILL REAL, AND SEPARATE — logged so it does not get closed with this lane:**
  the NCAAF season-projection artifact has not rebuilt since **2026-08-26T16:16
  CDT** (every served `projection.generated_at` is that date) because every
  relaunch dies on `urllib.error.HTTPError: HTTP Error 429` at
  `generate_smartsim2_ncaaf_projections.py:66 (_cfbd_get)` via
  `load_ppa_ratings:179` <- `load_ppa_ratings_asof:271`. `artifact_stale` then
  refires within minutes, so the worker retries ~30x in 2h45m and the CFBD
  quota is spent on a call that cannot succeed. `age_seconds` grew 228,608 ->
  238,496 over that window. **This is a RE-OCCURRENCE**: `learnings.md`
  2026-08-27 records the same 429 in the same function; that entry fixed the
  age-as-liveness INSTRUMENT and left the 429 itself alone. Consequence today
  is bounded (projections are 3 days old and gated out of sizing anyway), but
  it will bite whenever the gate lifts. Not fixed here — no lane holds
  `scripts/run_refresh_worker.py` for the backoff, and the user asked for a
  diagnosis.
- **FIX COMMITTED 2026-08-29 — `ba8bf640` on `session/ncaaf-no-orders`, in this
  session's own worktree (`C:	mp\syndicate-sessions
caaf-no-orders`). NOT
  pushed, NOT deployed, no deploy claim taken.**
  New `syndicate/features/ncaaf/cfbd_backoff.py`: the policy as a pure,
  network-free function plus a transport-agnostic executor. Retries 429/5xx
  ONLY, 5 attempts, exponential-with-full-jitter from 2s, `Retry-After`
  honoured but capped, hard **180s total-sleep ceiling** — the worker does not
  `wait()` on this subprocess, so an over-patient backoff would hold
  `_season_projection_process_still_running` and become an outage in the
  launcher. Non-429 4xx and connection errors are deliberately NOT retried, and
  an exception the classifier does not recognise re-raises at once rather than
  being swallowed into the loop and reported as a rate limit. The final failure
  re-raises the ORIGINAL exception so the traceback still names the real status
  — a wrapper would have hidden the very `HTTP Error 429 ... in _cfbd_get` line
  that made this diagnosable.
  **Wired into BOTH entry points, not only the one in the traceback:**
  `_cfbd_get` (urllib) and `CfbdClient._get_json` (requests, reached by ten
  snapshot builders). They share one API key and therefore one quota.
- **VERIFICATION — `off != on` PROVEN, not asserted.** 15 tests pass. With the
  `call_with_retry` wrapper removed from both call sites the run is
  **2 failed, 13 passed** — exactly the two reachability tests, which drive the
  real `_cfbd_get`/`_get_json` rather than the policy. No regression:
  `-k "ncaaf or cfbd"` is **55F/539P before, 55F/554P after**; the 55 are
  `data/`-absent in the session worktree (worktrees exclude the mirror by
  default) and fail identically without my changes. **This is bench evidence
  only — nothing is deployed, so nothing here is a production reading.**
- **HALF THE DEFECT IS STILL OPEN, AND IT IS THE HALF THAT MAKES THE LOOP HOT.**
  `run_refresh_worker.py::_season_projection_should_launch` consults the
  last-LAUNCH backstop **only when the artifact is MISSING**; the STALE branch
  returns `artifact_stale` unconditionally, so a run that fails leaves the
  artifact exactly as stale as it found it and the next tick relaunches. That
  is `#389`'s own bug surviving in its sibling branch — same shape, same file,
  and `#389`'s docstring already argues the case. **`lane-guard` BLOCKED the
  edit: `scripts/run_refresh_worker.py` is claimed by OPEN lane
  `exchange-markets-api-integration`.** That lane is idle/GOAL COMPLETE and its
  claim on this file is described in its own `Files` line as **NARROW** — "one
  small, additive, opt-in-only boot-probe hook" — a different region entirely.
  Not edited across lanes. Needs the holder's release or a user override.
  Without it, the backoff reduces each doomed run's damage but not the ~30
  relaunches per 2h45m.
- Blocked by: none


### ncaaf-live-lens-state — OPEN — opened 2026-08-29 — session 6dc988f8-c05d-4b4b-a7b3-0f1f30bb2ee3
- Goal: the NCAAF live lens reports a game that is ACTUALLY IN PROGRESS as live.
  Measured 2026-08-29T16:0xZ, with UNC @ TCU at `state=in` / 1st Quarter on
  ESPN, production `/ncaaf/api/live-lens` served
  `Games 51 | Live 0 | Final 0 | Pregame 51`.
- Files: NEW `syndicate/features/ncaaf/live_game_state.py`,
  `syndicate/features/ncaaf/cards.py`, `syndicate/features/ncaaf/live_lens.py`,
  NEW `tests/test_ncaaf_live_game_state.py`, `tests/test_ncaaf_live_lens_local.py`
- Reads but does NOT claim (held by OPEN lane `ncaaf-settlement-resolver`):
  `scripts/poll_ncaaf_live_state.py`, `syndicate/features/shared/ncaaf_team_registry.py`,
  `syndicate/features/shared/bet_status_ncaaf.py`. READ-ONLY to this lane — if the
  fix needs a change inside any of them, surface the conflict first.
- Hypothesis: **this is not a timing artifact and not a lens defect.**
  `_shared_game_state` (`publication_adapter.py:32`) derives `live`/`final`/
  `period`/`clock` from `game["live_state"]`, and `ncaaf/cards.py` contains
  **zero occurrences of `live_state`** — so the field is absent on every NCAAF
  game and the lens's state branch is unreachable by construction. The state
  PATH shipped 2026-08-27 (`ncaaf-board-surfaces`) and was explicitly recorded
  there as "its DATA cannot be [tested] until a game is in progress". A game is
  now in progress and the data is not there.
- Supporting production read, same instant as the ESPN read: on the served
  UNC @ TCU card, `shared_game_state` = `{live: false, final: false,
  period: null, clock: "", startTime: null, status: "Week 1"}`. `status` is the
  constant `"Week 1"`, not a state — so the eyebrow shows `kickoff_label` for
  all 51 cards and will keep doing so after games go final.
- Falsification test: the hypothesis is WRONG if `live_state` reaches the card
  from somewhere other than `cards.py` (a publisher or artifact hop I have not
  read), or if the served payload starts reporting live without a code change
  — either would mean the feed exists and something narrower drops it.
- Verification: production `/ncaaf/api/live-lens` reports `Live >= 1` while
  ESPN reports a game `state=in` in the SAME script run, plus `Final` becoming
  non-zero after a game ends. A unit test is NOT sufficient here — that is
  exactly what passed while this shipped inert.
- **RESULT 2026-08-29 — HYPOTHESIS CONFIRMED, FIXED, VERIFIED ON PRODUCTION.**
  Same-instant read at 16:30:28Z (web `061d5b2b`):

      ESPN        events=8  in=1  post=0   UNC VS TCU "4:00 - 1st Quarter"
      PRODUCTION  games=51  Live=1  Final=0  Pregame=50
                  card "NC @ TCU"  eyebrow 'Q1 - 4:00'      -> MATCH

  Before, 16:05Z, same game already in progress: `Live 0 | Pregame 51`.
  The falsification test did NOT fire: nothing else fed `live_state`, and the
  payload did not change until the code did.

  Three deploys, each verified before the next:
  1. `061d5b2b` live 16:29:36Z — the join. `Live 0 -> 1`.
  2. `efc41b52` live ~16:34Z — real score on the lens.
     Read back: `NC @ TCU [Q1 - 4:00] Score: NC 3 - 10 TCU`.
  3. `4822f8e4` — `startTime` 8/51 -> 51/51 from the card's own kickoff.

  **NOT FIXED, and named rather than left implicit:** NCAAF is still absent
  from `_LIVE_LENS_SPORTS` in `shared/live_lens_loop.py`, so the cross-sport
  live-lens snapshot still carries no NCAAF — a different subsystem. And
  `Final` has never been observed in production; no game had finished at the
  time of the reading, so that path is unit-tested only. That is the SAME
  class of claim `ncaaf-board-surfaces` made about the live path, which is
  what this lane just had to fix.

  Side finding, fixed: `lane-guard` matches path SUFFIX, so the UNOWNED lane
  `soccer-board-mlb-parity`'s bare `cards.py` — in prose that SAID the claim
  was removed — was claiming every sport's cards builder. It blocked this
  work mid-game. `check_lane_invariants` passed throughout.
- Blocked by: none


## Archived lanes (full bodies in `lanes_closed.md`)

> Moved 2026-08-15 to bring this file back under the digest budget.
> Nothing was deleted. Each line points at a full body — including the
> file/line maps and the ORPHANED lanes' resume notes.

- `mlb-prop-oos-calibration` — mlb-prop-oos-calibration — CLOSED-VERIFIED 2026-08-15 — D4 CLOSED: the split ran on production, `batter_hits` is the one verdict that did NOT survive  → `lanes_closed.md`.
- `probability-clamp-removal` — probability-clamp-removal — CLOSED-VERIFIED 2026-08-15 — WNBA site fixed, scored 5/5, shipped as `de0c367f`; the other TWO sites are held by other OPE → `lanes_closed.md`.
- `probability-differential-test` — probability-differential-test — CLOSED-VERIFIED 2026-08-15 — harness + table + owners shipped as `d448a100`; ONE live misprice CONFIRMED in production → `lanes_closed.md`.
- `soccer-backtest-leakage` — soccer-backtest-leakage — CLOSED-VERIFIED 2026-08-14 — **ARCHIVED to `lanes_closed.md`**. Audit §7 #6. HEAD `2dcca4fe`; `50fd7fe2` ALONE IS UNSAFE TO  → `lanes_closed.md`.
- `ask-headline-from-board` — ask-headline-from-board — CLOSED-VERIFIED 2026-08-15 — web `c774fe1a` live 03:29:56Z; B01 delta 0.000 and refusal 4/8 matching its control, both measu → `lanes_closed.md`.
- `recommendation-lane-correctness` — recommendation-lane-correctness — CLOSED-VERIFIED 2026-08-14 — 4 shipped+measured; A3a (`28291eb6`) HELD BACK BY CHOICE, not by doubt — opened 2026-08 → `lanes_closed.md`.
- `soccer-odds-coverage` — soccer-odds-coverage — ORPHANED-CLAIMS-RELEASED 2026-08-15 — claims on `refresh_odds_sources.py` released; the per-league cadence is NOT fixed — opene → `lanes_closed.md`.  **ORPHANED — resume notes + file claims in the archive.**
- `soccer-projection-gap` — soccer-projection-gap — ORPHANED-CLAIMS-RELEASED 2026-08-15 — it claimed NO files; the 30% projection coverage is unchanged — opened 2026-08-14 — sess → `lanes_closed.md`.  **ORPHANED — resume notes + file claims in the archive.**
- `wnba-skill-backtest` — wnba-skill-backtest — CLOSED-VERIFIED 2026-08-14 — opened 2026-08-14 — session: nfl-day-of-game → `lanes_closed.md`.
- `wnba-skill-backtest` — wnba-skill-backtest — CLOSED-VERIFIED — superseded header, kept for the file/line map → `lanes_closed.md`.
- `odds-capture-stall` — odds-capture-stall — CLOSED 2026-08-14 — NOT A DEFECT: the 2h gap IS the configured pregame cadence → `lanes_closed.md`.
- `board-ui-freshness-slip-books` — board-ui-freshness-slip-books — CLOSED 2026-08-14 — all three shipped and verified → `lanes_closed.md`.
- `build-time-estimate` — build-time-estimate — CLOSED 2026-08-14 — board build timed at ~2-4 min on current code; estimator can no longer collapse to ~0 — opened 2026-08-14 —  → `lanes_closed.md`.
- `layer2-board-freshness` — layer2-board-freshness — CLOSED-VERIFIED 2026-08-14 (memory follow-on lives on branch `memory/overview-sum-to-max`, undeployed) — 3h clean window, all → `lanes_closed.md`.
- `projection-skill-declaration` — projection-skill-declaration — CLOSED-VERIFIED 2026-08-14 — opened 2026-08-14 — session: nfl-day-of-game → `lanes_closed.md`.
- `projection-skill-declaration` — projection-skill-declaration — CLOSED-VERIFIED — superseded header, kept for the file/line map → `lanes_closed.md`.
- `projection-degeneracy-detector` — projection-degeneracy-detector — CLOSED-VERIFIED 2026-08-14 — opened 2026-08-14 — session: nfl-day-of-game → `lanes_closed.md`.
- `projection-degeneracy-detector` — projection-degeneracy-detector — CLOSED-VERIFIED — superseded header, kept for the file/line map → `lanes_closed.md`.
- `anon-allocation-site` — anon-allocation-site — ORPHANED-REASSIGNED 2026-08-15 — file claims released to `memory-watchdog-435`; the lane's OWN FINDINGS ARE NOT CLOSED — opened → `lanes_closed.md`.  **ORPHANED — resume notes + file claims in the archive.**
- `nfl-degenerate-writer` — nfl-degenerate-writer — CLOSED-VERIFIED 2026-08-13 — opened 2026-08-13 — session: nfl-day-of-game → `lanes_closed.md`.
- `nfl-degenerate-writer` — nfl-degenerate-writer — CLOSED-VERIFIED — superseded header, kept for the file/line map → `lanes_closed.md`.
- `refresh-worker-anon-leak` — refresh-worker-anon-leak — ORPHANED-REASSIGNED 2026-08-15 — file claims released to `memory-watchdog-435`; the leak itself IS STILL UNEXPLAINED — open → `lanes_closed.md`.  **ORPHANED — resume notes + file claims in the archive.**
- `nfl-day-of-game` — nfl-day-of-game — CLOSED-VERIFIED 2026-08-13 — opened 2026-08-13 — session: nfl-day-of-game → `lanes_closed.md`.
- `nfl-day-of-game` — nfl-day-of-game — CLOSED-VERIFIED — superseded header, kept for the file/line map → `lanes_closed.md`.
- `quote-join-enrich-cost` — quote-join-enrich-cost — CLOSED 2026-08-14 — all three verification criteria MET → `lanes_closed.md`.
- `checkpoint-witness` — checkpoint-witness — CLOSED 2026-08-13 — opened 2026-08-13 — session: hooks-test → `lanes_closed.md`.
- `checkpoint-guard-scope` — checkpoint-guard-scope — CLOSED-VOID 2026-08-13 — opened 2026-08-13 — session: hooks-test → `lanes_closed.md`.
- `memory-guard-reclaimable` — memory-guard-reclaimable — CLOSED 2026-08-13 — fix VERIFIED, and it uncovered a leak → `lanes_closed.md`.
- `mlb-props-regen` — mlb-props-regen — ORPHANED-CLAIMS-RELEASED 2026-08-15 — `live_refresh_loop.py` released; the props-regen fixes are NOT confirmed shipped — opened 2026 → `lanes_closed.md`.  **ORPHANED — resume notes + file claims in the archive.**
- `hooks-enforcement-test` — hooks-enforcement-test — CLOSED 2026-08-13 — opened 2026-08-13 — session: hooks-test → `lanes_closed.md`.
- `intelligence-state-red-baseline` — intelligence-state-red-baseline — CLOSED 2026-08-13 — opened 2026-08-13 — session: intel-state-baseline → `lanes_closed.md`.
- `board-transport` — board-transport — CLOSED 2026-08-13 (work measured 08-10/11) → `lanes_closed.md`.
- `sim-execution-observability` — sim-execution-observability — CLOSED-PENDING-MEASUREMENT 2026-08-13 → `lanes_closed.md`.
- `soccer-sim-grouping` — soccer-sim-grouping — CLOSED 2026-08-10 — shipped and verified, one thread handed on → `lanes_closed.md`.
- `layer1-live-tier` — layer1-live-tier — CLOSED-PENDING-MEASUREMENT 2026-08-13 → `lanes_closed.md`.
- `internal-hostname-cutover` — internal-hostname-cutover — CLOSED 2026-08-13 — verified in production → `lanes_closed.md`.
- `internal-hostname-cutover` — internal-hostname-cutover — CLOSED — opened 2026-08-13 — session: <name> → `lanes_closed.md`.
- `ask-refusal-gate` — ask-refusal-gate — CLOSED-VERIFIED 2026-08-14 — refusal 3/8 -> 6/8 in production, zero regressions — opened 2026-08-14 — session: ask-audit → `lanes_closed.md`.
- `ask-board-candidates` — ask-board-candidates — ORPHANED-CLAIMS-RELEASED 2026-08-15 — `ask_the_syndicate_data.py` released; M1 SHIPPED but a REVERT OF IT IS STAGED IN GIT — op → `lanes_closed.md`.  **ORPHANED — resume notes + file claims in the archive.**
- `board-ui-visible-defects` — board-ui-visible-defects — CLOSED-VERIFIED 2026-08-14 — deployed as web `aadcde77`, every criterion measured in production — opened 2026-08-14 — sessi → `lanes_closed.md`.
- `memory-cutover-ship` — memory-cutover-ship — CLOSED-VERIFIED 2026-08-15 — `#387` shipped in TWO halves (`cfee9c6e` + `705eeefc`), sports=8 restored, peak 34.3% of ceiling —  → `lanes_closed.md`.
- `board-contract-absent-not-neutral` — board-contract-absent-not-neutral — ORPHANED-CLAIMS-RELEASED 2026-08-15 — 6 claims released incl. `game_board_contract.py`; partial work IS committed  → `lanes_closed.md`.  **ORPHANED — resume notes + file claims in the archive.**
- `mlb-oom-outlier-2003z` — mlb-oom-outlier-2003z — CLOSED 2026-08-15 — QUESTION WAS MALFORMED: no outlier, 16 kills that day; H1 falsified — opened 2026-08-15 — session: memory- → `lanes_closed.md`.
- `mlb-hydration-oom-435` — mlb-hydration-oom-435 — CLOSED 2026-08-15 — `build_cards_page_context` is 2 of 6 kills, NOT the common factor — opened 2026-08-15 — session: memory-cu → `lanes_closed.md`.
- `memory-watchdog-435` — memory-watchdog-435 — CLOSED-VERIFIED 2026-08-15 — watchdog + 3 censuses live; ROOT CAUSE FOUND: append-only quote shard, 92.4% superseded, 6.3x read  → `lanes_closed.md`.
- `odds-props-fabricated-probability` — odds-props-fabricated-probability — ORPHANED-CLAIMS-RELEASED 2026-08-15 — the two prop-refresh scripts released; work committed, artifact effect UNMEA → `lanes_closed.md`.  **ORPHANED — resume notes + file claims in the archive.**
- `soccer-card-end-to-end` — soccer-card-end-to-end — CLOSED-VERIFIED 2026-08-15 — deployed as web `7e334509`, every criterion measured in production — opened 2026-08-15 — session → `lanes_closed.md`.
- `model-audit-devig-and-hygiene` — model-audit-devig-and-hygiene — CLOSED-VERIFIED 2026-08-15 — #5 falsified then collapsed for real + D5 done (`2ac3c6bc`, committed, NOT deployed, cons → `lanes_closed.md`.

## MERGED FROM origin/main - coordinator merge cycle

## MERGED FROM origin/main - coordinator merge cycle

## MERGED FROM origin/main - coordinator merge cycle

## MERGED FROM origin/main - coordinator merge cycle

## MERGED FROM origin/main — 2026-08-17, by the coordinator

Block-level union. These blocks existed on `origin/main` and nowhere
on the swept side. Appended verbatim, nothing edited, nothing reordered.

## MERGED FROM origin/main — 2026-08-17, by the coordinator

Block-level union. These blocks existed on `origin/main` and nowhere
on the swept side. Appended verbatim, nothing edited, nothing reordered.

## 2026-08-17 - THE LEDGER IS A RECORD, NOT EVIDENCE (the inverse of the same day's other lesson)

I relayed *"two uncommitted soccer fixes at risk of being lost"* to the
coordinator as an action item. **It came from a lane entry, not from a
measurement.** `git status` was empty and fix #1 was already on main.

**This is the exact inverse of the three errors recorded above it today.** There
I called healthy things BROKEN from a null lookup. Here I called a committed
thing AT RISK from a written claim I never checked. **Same root cause: treating
a statement as a reading.**

`.syndicate/**` records what was true WHEN WRITTEN. This lane was last touched
two days before I quoted it. **Before acting on or forwarding a ledger claim
about the state of the working tree - uncommitted work, missing files, a broken
service - re-measure it.** The cost here was small (a wrong action item, since
retracted). The cost of the reverse - deleting or "rescuing" files on a stale
claim - would not have been.

## MERGED FROM origin/main - reconciliation pass

Blocks whose content was absent from the merged result. Appended verbatim, nothing edited.

## MERGED FROM origin/main - reconciliation pass

Blocks whose content was absent from the merged result. Appended verbatim, nothing edited.



## MERGED FROM origin/main - reconciliation pass

Blocks whose content was absent from the merged result. Appended verbatim, nothing edited.

#### LANE RELEASE — session `bd97b64e` / `7c041356`, 2026-08-18 ~01:4xZ. **ALL HOLDS RELEASED. No file in this repo is claimed by this session any more.**

Released, with status:
- **`wnba-fixture-identity` — CLOSED.** Identity module + 40 tests shipped and on
  `main`. `game_cards` coverage fix proven on the real artifact (1 row → 3).
- **`wnba-phase2-migration` — CLOSED, code shipped, NOT ENABLED.** Autorun
  (`e65a5531`) + tests (`c7494c6c`). Its env keys are live on live-odds-worker
  and **inert until the code deploys**; it then goes hot on the FIRST tick,
  because the flag is already on and `last_epoch=0`.
- **`modelled-fair-edge` — CLOSED.** `edge_vs_modelled_fair_pct` shipped; 228 of
  258 both-terms MLB rows priced on the real payload. **NOT deployed.**
- **`soccer-projection-collapse` — CLOSED, root cause fixed, NOT deployed.**
  `#379`'s widening was inert; its only caller never passed `window_dates`.
- **`wnba-live-tier` — HOLD RELEASED.** I edited exactly ONE file under it,
  `board_enrichment.py`, one call site, on explicit user instruction ("no one has
  it"). **Everything else in that lane is untouched and its other claims stand.**
- **`export-force-refresh-escape` — CLOSED EARLIER BY OVERRIDE** (unattended
  holder, user-authorized). **Its effect measurement is still OWED and was NOT
  discharged by that close.**

**Session markers `.current-lane.7c041356-…` and `.current-lane.bd97b64e-…`
DELETED.** The other markers in that directory belong to other sessions —
including the coordinator's `9ed7fd89` — and were **not touched**.

**WHAT THE NEXT SESSION SHOULD NOT REDO:** everything above is on `main` with
tests. The remaining work is DEPLOY-GATED, not code-gated. Two requests sit with
the coordinator: **Phase 2 WNBA** and the **soccer projection window** (largest
measured effect, and it unblocks ~1,131 of the 1,416 rows the `book_margin_model`
decision was about).



## MERGED FROM origin/main - reconciliation pass

Blocks whose content was absent from the merged result. Appended verbatim, nothing edited.

## Archived lanes (full bodies in `lanes_closed.md`)
- `live-edge-basis` — live-edge-basis — CLOSED-VERIFIED 2026-08-17 — **SHIPPED AND MEASURED. `edge_basis` observed on served rows (refresh-worker `b20072cd`, build 17:44:30 → `lanes_closed.md`.
- `nfl-pbp-root-resolution` — nfl-pbp-root-resolution — **CLOSED 2026-08-16 — resolution mechanism PROVEN CORRECT and the hypothesis FALSIFIED in the same reading. `#441` root caus → `lanes_closed.md`.
- `render-events-reader` — render-events-reader — CLOSED-VERIFIED 2026-08-16 — **`scripts/render_events.py` + `tests/test_render_events.py` SHIPPED TO THE TREE (no deploy — this → `lanes_closed.md`.
- `ui-probe-settle-plateau` — ui-probe-settle-plateau — CLOSED 2026-08-16 — the settle now needs 2400ms of stillness, and a verdict resting on absence says so — opened 2026-08-16 — → `lanes_closed.md`.
- `ui-probe-desktop-height-model` — ui-probe-desktop-height-model — CLOSED 2026-08-16 — desktop is UNFITTABLE, not mis-tuned; measured the floor instead of tuning the threshold — opened  → `lanes_closed.md`.
- `ui-probe-tie-floor-tracking` — ui-probe-tie-floor-tracking — CLOSED 2026-08-16 — floor collected on every row; 5 of 6 stable, mlb mobile fires the rule at 2.06x — opened 2026-08-16  → `lanes_closed.md`.
- `ui-probe-tie-statistic` — ui-probe-tie-statistic — CLOSED 2026-08-16 — implemented as decided; the statistic did NOT help and the instability is the SLATE — opened 2026-08-16 — → `lanes_closed.md`.
- `ui-probe-tracked-statistic-revert` — ui-probe-tracked-statistic-revert — CLOSED 2026-08-16 — reverted to worstGroupPx; exposed and fixed two false alarms that were failing a healthy board → `lanes_closed.md`.
- `branch-overlap-baseline-instrumentation` — branch-overlap-baseline-instrumentation — CLOSED 2026-08-16 — the baseline was sampling hours where the failure does not happen — session: `branch-ove → `lanes_closed.md`.
- `ui-probe-baseline-nfl-ncaaf` — ui-probe-baseline-nfl-ncaaf — CLOSED 2026-08-16 — armed for nfl/ncaaf only; mlb stays watch-only — opened 2026-08-16 — session: ui-probe-rerun-compare → `lanes_closed.md`.
- `mlb-mobile-live-residual` — mlb-mobile-live-residual — CLOSED 2026-08-16 — HYPOTHESIS FALSIFIED; it is a false alarm, the Live fit is convex and `fitRatio` cannot see curvature — → `lanes_closed.md`.
- `branch-overlap-manual-run-marker` — branch-overlap-manual-run-marker — CLOSED — opened 2026-08-16 — session: `branch-overlap-baseline-watch` — verified in production 2026-08-16T19:52:23+ → `lanes_closed.md`.
- `ui-probe-peer-deviation-gate` — ui-probe-peer-deviation-gate — CLOSED 2026-08-16 — one model-free height rule; production green, coverage gap printed — opened 2026-08-16 — session: u → `lanes_closed.md`.
- `layer1-board-coverage` — layer1-board-coverage — UPDATE 2026-08-16 17:5xZ — **DEPLOYED AND FALSIFICATION TEST PASSED. Supersedes this lane's "UNDEPLOYED" line above.** → `lanes_closed.md`.
- `ui-probe-curvature-detection` — ui-probe-curvature-detection — CLOSED 2026-08-16 — `curved` forces `reliable:false`; Preview (the falsification case) is not flagged — opened 2026-08- → `lanes_closed.md`.
- `ui-probe-proportional-budget` — ui-probe-proportional-budget — CLOSED 2026-08-16 — shipped; falsification test FIRED (proportional does not tighten the spread) but it fixes the width → `lanes_closed.md`.
- `layer1-board-coverage` — layer1-board-coverage — **CLOSE REFUSED 2026-08-16 18:0xZ.** Verification is not met, and a NEW production defect was found in this lane's own scope w → `lanes_closed.md`.
- `soccer-live-game-state` — soccer-live-game-state — CLOSED-VERIFIED 2026-08-16 18:56Z — a kicked-off match is no longer `pregame`, and no finished match carries an edge → `lanes_closed.md`.
- `ui-probe-tab-click-race` — ui-probe-tab-click-race — CLOSED 2026-08-16 — cause UNPROVEN and not reproduced; the blindness that made it undiagnosable is fixed — opened 2026-08-16 → `lanes_closed.md`.
- `layer1-board-coverage` — layer1-board-coverage — SCOPE ADDED 2026-08-16 20:0xZ — the HR threshold ladder → `lanes_closed.md`.
- `ui-probe-peer-min-group` — ui-probe-peer-min-group — CLOSED 2026-08-16 — verdicts need n>=3; thin groups reported, never dropped — opened 2026-08-16 — session: ui-probe-rerun-co → `lanes_closed.md`.
- `sim-scheduling` — sim-scheduling — **DEPLOYED AND MEASURED 2026-08-16 21:2xZ.** `#441` verified live; `#445` shipped but unverifiable today; layer2 (both halves) shippe → `lanes_closed.md`.
- `game-shape-capture` — game-shape-capture — UPDATE 2026-08-16 ~23:0xZ (checkpoint) — **PRIMITIVE COMMITTED `af3017e6`; EMIT STILL BLOCKED; HANDOFF SENT** → `lanes_closed.md`.
- `ncaaf-schedule-fallback` — ncaaf-schedule-fallback — **CLOSED-VERIFIED 2026-08-16 — `#445` fixed in `483bb9dd`, on `origin/main`. NOT DEPLOYED (NCAAF opens 08-29)** — opened 202 → `lanes_closed.md`.
- `nfl-pbp-fetcher` — nfl-pbp-fetcher — **CLOSED-VERIFIED 2026-08-16 18:31:15Z — pbp_2025.csv written on the mounted disk (97,951,481 bytes, 46,452 REG plays) and the guard → `lanes_closed.md`.
- `closing-stamp-is-detection-time` — closing-stamp-is-detection-time — CLOSED-VERIFIED — **OUTPUT MEASURED 2026-08-15 22:06 CDT / 2026-08-16 03:06Z. 21/21 new-code stamps precede first pi → `lanes_closed.md`.
- `spread-line-sign-convention` — spread-line-sign-convention — CLOSED-VERIFIED 2026-08-16 — **ARTIFACT OUTPUT NOW MEASURED: 12 of 12 MLB spreads rows correct on the served shortlist ( → `lanes_closed.md`.
- `commit-guard-reads-wrong-index` — commit-guard-reads-wrong-index — CLOSED 2026-08-16 — the guard read the MAIN worktree's index while the commit used another one — session: `live-gamel → `lanes_closed.md`.
- `ask-answer-substance` — ask-answer-substance — **CLOSED-VERIFIED 2026-08-16 — 8 deploys, all measured, live web `9f617f34`. The inline quick ask names a bet a human can place → `lanes_closed.md`.

> Moved 2026-08-15 to bring this file back under the digest budget.
> Nothing was deleted. Each line points at a full body — including the
> file/line maps and the ORPHANED lanes' resume notes.

- `mlb-prop-oos-calibration` — mlb-prop-oos-calibration — CLOSED-VERIFIED 2026-08-15 — D4 CLOSED: the split ran on production, `batter_hits` is the one verdict that did NOT survive  → `lanes_closed.md`.
- `probability-clamp-removal` — probability-clamp-removal — CLOSED-VERIFIED 2026-08-15 — WNBA site fixed, scored 5/5, shipped as `de0c367f`; the other TWO sites are held by other OPE → `lanes_closed.md`.
- `probability-differential-test` — probability-differential-test — CLOSED-VERIFIED 2026-08-15 — harness + table + owners shipped as `d448a100`; ONE live misprice CONFIRMED in production → `lanes_closed.md`.
- `soccer-backtest-leakage` — soccer-backtest-leakage — CLOSED-VERIFIED 2026-08-14 — **ARCHIVED to `lanes_closed.md`**. Audit §7 #6. HEAD `2dcca4fe`; `50fd7fe2` ALONE IS UNSAFE TO  → `lanes_closed.md`.
- `ask-headline-from-board` — ask-headline-from-board — CLOSED-VERIFIED 2026-08-15 — web `c774fe1a` live 03:29:56Z; B01 delta 0.000 and refusal 4/8 matching its control, both measu → `lanes_closed.md`.
- `recommendation-lane-correctness` — recommendation-lane-correctness — CLOSED-VERIFIED 2026-08-14 — 4 shipped+measured; A3a (`28291eb6`) HELD BACK BY CHOICE, not by doubt — opened 2026-08 → `lanes_closed.md`.
- `soccer-odds-coverage` — soccer-odds-coverage — ORPHANED-CLAIMS-RELEASED 2026-08-15 — claims on `refresh_odds_sources.py` released; the per-league cadence is NOT fixed — opene → `lanes_closed.md`.  **ORPHANED — resume notes + file claims in the archive.**
- `soccer-projection-gap` — soccer-projection-gap — ORPHANED-CLAIMS-RELEASED 2026-08-15 — it claimed NO files; the 30% projection coverage is unchanged — opened 2026-08-14 — sess → `lanes_closed.md`.  **ORPHANED — resume notes + file claims in the archive.**
- `wnba-skill-backtest` — wnba-skill-backtest — CLOSED-VERIFIED 2026-08-14 — opened 2026-08-14 — session: nfl-day-of-game → `lanes_closed.md`.
- `wnba-skill-backtest` — wnba-skill-backtest — CLOSED-VERIFIED — superseded header, kept for the file/line map → `lanes_closed.md`.
- `odds-capture-stall` — odds-capture-stall — CLOSED 2026-08-14 — NOT A DEFECT: the 2h gap IS the configured pregame cadence → `lanes_closed.md`.
- `board-ui-freshness-slip-books` — board-ui-freshness-slip-books — CLOSED 2026-08-14 — all three shipped and verified → `lanes_closed.md`.
- `build-time-estimate` — build-time-estimate — CLOSED 2026-08-14 — board build timed at ~2-4 min on current code; estimator can no longer collapse to ~0 — opened 2026-08-14 —  → `lanes_closed.md`.
- `layer2-board-freshness` — layer2-board-freshness — CLOSED-VERIFIED 2026-08-14 (memory follow-on lives on branch `memory/overview-sum-to-max`, undeployed) — 3h clean window, all → `lanes_closed.md`.
- `projection-skill-declaration` — projection-skill-declaration — CLOSED-VERIFIED 2026-08-14 — opened 2026-08-14 — session: nfl-day-of-game → `lanes_closed.md`.
- `projection-skill-declaration` — projection-skill-declaration — CLOSED-VERIFIED — superseded header, kept for the file/line map → `lanes_closed.md`.
- `projection-degeneracy-detector` — projection-degeneracy-detector — CLOSED-VERIFIED 2026-08-14 — opened 2026-08-14 — session: nfl-day-of-game → `lanes_closed.md`.
- `projection-degeneracy-detector` — projection-degeneracy-detector — CLOSED-VERIFIED — superseded header, kept for the file/line map → `lanes_closed.md`.
- `anon-allocation-site` — anon-allocation-site — ORPHANED-REASSIGNED 2026-08-15 — file claims released to `memory-watchdog-435`; the lane's OWN FINDINGS ARE NOT CLOSED — opened → `lanes_closed.md`.  **ORPHANED — resume notes + file claims in the archive.**
- `nfl-degenerate-writer` — nfl-degenerate-writer — CLOSED-VERIFIED 2026-08-13 — opened 2026-08-13 — session: nfl-day-of-game → `lanes_closed.md`.
- `nfl-degenerate-writer` — nfl-degenerate-writer — CLOSED-VERIFIED — superseded header, kept for the file/line map → `lanes_closed.md`.
- `refresh-worker-anon-leak` — refresh-worker-anon-leak — ORPHANED-REASSIGNED 2026-08-15 — file claims released to `memory-watchdog-435`; the leak itself IS STILL UNEXPLAINED — open → `lanes_closed.md`.  **ORPHANED — resume notes + file claims in the archive.**
- `nfl-day-of-game` — nfl-day-of-game — CLOSED-VERIFIED 2026-08-13 — opened 2026-08-13 — session: nfl-day-of-game → `lanes_closed.md`.
- `nfl-day-of-game` — nfl-day-of-game — CLOSED-VERIFIED — superseded header, kept for the file/line map → `lanes_closed.md`.
- `quote-join-enrich-cost` — quote-join-enrich-cost — CLOSED 2026-08-14 — all three verification criteria MET → `lanes_closed.md`.
- `checkpoint-witness` — checkpoint-witness — CLOSED 2026-08-13 — opened 2026-08-13 — session: hooks-test → `lanes_closed.md`.
- `checkpoint-guard-scope` — checkpoint-guard-scope — CLOSED-VOID 2026-08-13 — opened 2026-08-13 — session: hooks-test → `lanes_closed.md`.
- `memory-guard-reclaimable` — memory-guard-reclaimable — CLOSED 2026-08-13 — fix VERIFIED, and it uncovered a leak → `lanes_closed.md`.
- `mlb-props-regen` — mlb-props-regen — ORPHANED-CLAIMS-RELEASED 2026-08-15 — `live_refresh_loop.py` released; the props-regen fixes are NOT confirmed shipped — opened 2026 → `lanes_closed.md`.  **ORPHANED — resume notes + file claims in the archive.**
- `hooks-enforcement-test` — hooks-enforcement-test — CLOSED 2026-08-13 — opened 2026-08-13 — session: hooks-test → `lanes_closed.md`.
- `intelligence-state-red-baseline` — intelligence-state-red-baseline — CLOSED 2026-08-13 — opened 2026-08-13 — session: intel-state-baseline → `lanes_closed.md`.
- `board-transport` — board-transport — CLOSED 2026-08-13 (work measured 08-10/11) → `lanes_closed.md`.
- `sim-execution-observability` — sim-execution-observability — CLOSED-PENDING-MEASUREMENT 2026-08-13 → `lanes_closed.md`.
- `soccer-sim-grouping` — soccer-sim-grouping — CLOSED 2026-08-10 — shipped and verified, one thread handed on → `lanes_closed.md`.
- `layer1-live-tier` — layer1-live-tier — CLOSED-PENDING-MEASUREMENT 2026-08-13 → `lanes_closed.md`.
- `internal-hostname-cutover` — internal-hostname-cutover — CLOSED 2026-08-13 — verified in production → `lanes_closed.md`.
- `internal-hostname-cutover` — internal-hostname-cutover — CLOSED — opened 2026-08-13 — session: <name> → `lanes_closed.md`.
- `ask-refusal-gate` — ask-refusal-gate — CLOSED-VERIFIED 2026-08-14 — refusal 3/8 -> 6/8 in production, zero regressions — opened 2026-08-14 — session: ask-audit → `lanes_closed.md`.
- `ask-board-candidates` — ask-board-candidates — ORPHANED-CLAIMS-RELEASED 2026-08-15 — `ask_the_syndicate_data.py` released; M1 SHIPPED but a REVERT OF IT IS STAGED IN GIT — op → `lanes_closed.md`.  **ORPHANED — resume notes + file claims in the archive.**
- `board-ui-visible-defects` — board-ui-visible-defects — CLOSED-VERIFIED 2026-08-14 — deployed as web `aadcde77`, every criterion measured in production — opened 2026-08-14 — sessi → `lanes_closed.md`.
- `memory-cutover-ship` — memory-cutover-ship — CLOSED-VERIFIED 2026-08-15 — `#387` shipped in TWO halves (`cfee9c6e` + `705eeefc`), sports=8 restored, peak 34.3% of ceiling —  → `lanes_closed.md`.
- `board-contract-absent-not-neutral` — board-contract-absent-not-neutral — ORPHANED-CLAIMS-RELEASED 2026-08-15 — 6 claims released incl. `game_board_contract.py`; partial work IS committed  → `lanes_closed.md`.  **ORPHANED — resume notes + file claims in the archive.**
- `mlb-oom-outlier-2003z` — mlb-oom-outlier-2003z — CLOSED 2026-08-15 — QUESTION WAS MALFORMED: no outlier, 16 kills that day; H1 falsified — opened 2026-08-15 — session: memory- → `lanes_closed.md`.
- `mlb-hydration-oom-435` — mlb-hydration-oom-435 — CLOSED 2026-08-15 — `build_cards_page_context` is 2 of 6 kills, NOT the common factor — opened 2026-08-15 — session: memory-cu → `lanes_closed.md`.
- `memory-watchdog-435` — memory-watchdog-435 — CLOSED-VERIFIED 2026-08-15 — watchdog + 3 censuses live; ROOT CAUSE FOUND: append-only quote shard, 92.4% superseded, 6.3x read  → `lanes_closed.md`.
- `odds-props-fabricated-probability` — odds-props-fabricated-probability — ORPHANED-CLAIMS-RELEASED 2026-08-15 — the two prop-refresh scripts released; work committed, artifact effect UNMEA → `lanes_closed.md`.  **ORPHANED — resume notes + file claims in the archive.**
- `soccer-card-end-to-end` — soccer-card-end-to-end — CLOSED-VERIFIED 2026-08-15 — deployed as web `7e334509`, every criterion measured in production — opened 2026-08-15 — session → `lanes_closed.md`.
- `model-audit-devig-and-hygiene` — model-audit-devig-and-hygiene — CLOSED-VERIFIED 2026-08-15 — #5 falsified then collapsed for real + D5 done (`2ac3c6bc`, committed, NOT deployed, cons → `lanes_closed.md`.
- `nfl-fantasy-projections` — CLOSED-VERIFIED 2026-08-21 — `/nfl/fantasy` live: ESPN-scoring 2026 season+weekly projections, VOR board, and a news layer that captures, accumulates and renders (web `003a5866`)  → `lanes_closed.md`.
