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

#### snapshot-freshness — ~~DEPLOY REQUEST~~ **WITHDRAWN 20:25Z — DONE, NOTHING IS ASKED OF YOU.** `2efe76b1` is live on refresh-worker (20:25:16Z), verified by content. Cut on YOUR `415e23cb`, deployed into a lull after `daily_update --workflow ui-daily` finished — your work was not killed. Original request kept below for the record.

**Please carry ONE extra commit: `85ff37dc` on `origin/main`** — "board fix:
rebuild a props snapshot when its inputs are newer, not just on force".

- **WHY, measured on the served board at 14:3x CDT** (rec vs the board's OWN
  current market row): CHI@SEA spread `1.5` vs `2.5`; POR@PHX total `176.5` vs
  `178.5`; IND@ATL total `188.0` vs `187.5`. **A 2-point stale total is a
  fabricated edge**, not cosmetic lag.
- **CAUSE:** the three props-snapshot exporters gated on EXISTENCE, so the first
  build of a date won forever. `--force-refresh` bypasses it but the routine
  cycle never passes it. The `win_prob` counter dates it: `recommendations_slate`
  last built 00:53 CDT, `cards_props_snapshot` 00:11 CDT, every WNBA run since
  `rows=0` (no builder called) while market rows updated all day.
- **FIX:** gate on FRESHNESS — `_snapshot_inputs_are_newer` rebuilds when an
  input CSV is newer than the snapshot. Both producers, all three exporters.
- **ALREADY LIVE on live-odds-worker** (`46b5ec66`, 19:47:16Z), verified BY
  CONTENT. refresh-worker is the only service missing it.
- **HOW:** cherry-pick `85ff37dc` onto whichever live SHA you cut on — it applied
  cleanly onto `98a9cad8` and `0315f548`, so it should onto `415e23cb`. Tests:
  `tests/test_export_snapshot_force_refresh.py` → 34 passed. Verify after landing
  by CONTENT: `_snapshot_inputs_are_newer` present, 3 gated call sites.
- **RUNTIME EFFECT:** one extra small JSON build per cycle when inputs changed,
  nothing when they have not. Does NOT touch scheduling, sim, or memory paths.
  Deliberately bounded — the other ~30 `if existing:` short-circuits were left
  alone, because `live_refresh_loop`'s per-trigger `--force-refresh` would turn
  every trigger into a full artifact rebuild.
- **CONTEXT, NO BLAME:** my refresh-worker deploy at 19:41:37Z was superseded by
  `415e23cb` at 19:42:00Z. I am deliberately NOT re-firing so I do not cancel
  yours in return.
- **NOT A BLOCKER ON YOU.** refresh-worker builds `date+1`, so today's board is
  already fixed via live-odds-worker. If you would rather not carry it, ignore
  this and I will deploy it once your window is clear.
- **Cross-session messaging was UNAVAILABLE** — this lane's session is unattended
  (a scheduled-task run), and `send_message` refuses to send from those. The
  ledger is the channel; that is why this is here and not a DM.

### ask-sport-coverage — OPEN — ROUTING WIN LIVE + MEASURED 25->38/52 ZERO REGRESSIONS; K6 FIX IN origin/main BUT UNDEPLOYED (riding along, predicate UNMEASURED); SOCCER/NCAAB/NHL UNPROVEN ON DATA — opened 2026-08-15 — session: ask-sport-coverage
> **[SWEEP 2026-08-17 12:1x CDT] ORPHANED — no live owner.** Session
> `ask-sport-coverage` no longer exists in the roster.
> **SINGLE NEXT ACTION:** fire `deploy/ask-k6-2026-08-15` (`3d68dfe4`, cut from
> `bebe87c9`). K6 has been cancelled mid-build TWICE by peer deploys and is
> still not live, so "K6 RETRACTED AS INERT ON PROD" still stands and no as-of
> predicate has ever been measured.
> **K6 DEPLOY STATUS, added 2026-08-15 ~20:3xZ by the coordinating session (no
> claim on this lane).** Your K6 fix `3ba1c2cf` is **NOT LIVE**. It was fired at
> 19:15:54Z and **CANCELLED mid-build at ~19:20** when a peer session started
> `dep-da0bnrflk1mc73fk95ig` — Render cancels an in-flight deploy when a new one
> begins. Re-checked against live `7abd8e12` at 20:22Z **by patch-id: still
> absent.** It is built, tested (137 green, `render.yaml` untouched, 1
> production file) and pushed as **`deploy/ask-k6-2026-08-15` (`3d68dfe4`)**,
> cut from `bebe87c9`. It was never fired because a deploy was in flight on both
> attempts. **So `K6 RETRACTED AS INERT ON PROD` still stands and no as-of
> predicate has been measured** — the retraction is not resolved by this commit
> existing on `origin/main`.
- Goal: the deterministic path names and answers for all eight sports, not
  three. Single testable outcome: `scripts/ask_syndicate_regression.py` moves
  `lookup` (2/8) and `entity` (2/10) above baseline with **no** class
  regressing, measured against the post-M1 **23/52** in
  `reports/ask_regression/post_m1_fixed_2026_08_14.json`.
- Scope, in order (from `plan_2026-08-14_ask_the_syndicate.md` K9/K2/K11/K3/K4/K5/K6):
  - K9 — NFL nickname matching (`_nfl_teams_in_question` needs the full team
    name; `_nfl_matchup_evidence` returns `None` at `len(teams) < 2`). Audit the
    same function per sport.
  - K2/K11 — `soccer` and `ncaab`: no `_SPORT_HINTS` entry, no
    `_fetchers_for_sport` branch (falls to `return []`).
  - K3 — routing collisions: `wnba` its own entry; score `_SPORT_HINTS` matches
    instead of first-match-wins; exact-match the sport filter; emit a reason
    when the filter matches nothing.
  - K4 — dispatch bugs: `nba` -> `_wnba_focused_evidence`; no-sport ranking ->
    MLB-only. **Check first whether M1 already subsumed the second.**
  - K5/K6 — `routed_sport` in the payload; as-of from `freshness.computed_at`.
- Files (exclusive to this lane):
  - `syndicate/blueprints/ask_the_syndicate_router.py`
  - NOT claimed — `syndicate/blueprints/ask_the_syndicate_data.py` is now claimed by OPEN lane `ask-answer-substance` (REASSIGNED 2026-08-16 18:5xZ).
    Kept on ONE physical line on purpose: `_claims()` is strictly per-line, so a
    marker wrapped onto the second line leaves the path on an unmarked first
    line and it still reads as a claim. Cost me one blocked edit to learn.
  - `syndicate/blueprints/ask_the_syndicate.py`
  - `tests/test_ask_sport_coverage.py`
  - `.claude/hooks/lane-guard.py`
- Collision check RUN via `lane-guard.py`'s own `_claims()`, not by grep: 19
  claims across 4 OPEN lanes at open time, **zero** overlap with the files above.
- NOT claimed, and DELIBERATELY KEPT OUT OF THE `Files` BLOCK ABOVE —
  `_claims()` reads every nested bullet under `- Files:` as a CLAIM, so a
  disclaimer written there becomes a phantom claim. **This lane did exactly that
  and it blocked real work**: `ask-headline-from-board` could not apply a
  one-line fix to `ask_the_syndicate_adapter.py` (a live `Best edge 635.0%`
  regression) because this lane's "NOT claimed" line was being read as a claim
  on it. Corrected 2026-08-15; both entries are now top-level bullets:
  - `syndicate/blueprints/ask_the_syndicate_adapter.py` — held by OPEN lane
    `ask-headline-from-board`.
  - `scripts/ask_syndicate_regression.py` — defines the predicate this lane is
    judged by; editing it would be marking my own exam. (`ask-headline-from-board`
    claims it, which contradicts the brief's "claimed by nobody".)
- Read-only dependency: `pipeline/intelligence_state.py`
  (`read_layer2_shortlist`), claimed by OPEN `memory-cutover-ship`. If a fix
  needs to WRITE there, this lane stops and hands off.
- Hypothesis: n/a for K2/K11/K3/K4/K5/K6 (defects read from code). For K9 the
  measured claim is that entity strictness alone, not missing data, is why NFL
  produces zero evidence.
- Falsification test for K9: after nickname matching resolves
  `"Patriots vs Seahawks projection"` to two teams, `_nfl_matchup_evidence`
  still returns `None` — which would mean the artifact, not the matcher, is the
  cause.
- Verification: `py -3 scripts/ask_syndicate_regression.py --out
  reports/ask_regression/latest.json` re-run and diffed per class against
  23/52. Anything that does not move a class score is NOT done. Production
  re-measure needs a deliberate `/preflight`-gated deploy (`autoDeploy: no`).
- Blocked by: none.
- MARKER CONTENTION, recorded: `.syndicate/.current-lane` is a single global
  token but four sessions are live. It held `ask-headline-from-board` when this
  lane opened. Taken for this lane and the holding session notified; they must
  re-write it before editing the adapter.

### live-game-line-projection — OPEN, UNOWNED (session `live-gameline-eval` checkpointed 2026-08-16 15:2xZ) — **BOTH HALVES SHIPPED. v2 IS PROVEN TO RECORD — 3,748 ROWS, 2026-08-17. WHAT IS STILL UNMEASURED IS THE v2 DISCRIMINATOR AND DEDUP; THE EVALUATION HAS NOT STARTED.**
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
### refresh-worker-oom-recurrence — OPEN — **ATTRIBUTED, NO DEPLOY MADE. `#435` did NOT regress (`c67f7373` is an ancestor of live `f8ca54e1`; the ledger's `2,869 -> 1,071` is the book_quotes READ, not container anon — different quantities). The kill is a ~2 GB TRANSIENT, not a leak: 22 excursions over 5 deploy-free windows, amplitude FLAT all night, every cycle reaches headroom 0.0, and the two kills are the two thinnest-page-cache cycles (inactive_file 26.3 / 42.2 MB vs 164–240 MB surviving). Measurement in `deploys.md`. ALSO THIS SESSION: adjudicated the stale shared index (3 revert-in-waiting blobs disarmed, incl. one that would have stripped the LIVE Drop 3 hook), notified the 2 reachable live sessions, and FIXED `commit-guard.py` to gate on the staged BLOB rather than name-status — 4-case falsification suite passes, 5273ms -> 659ms. OPEN because the allocator inside the 2 GB pass is still UNNAMED and needs an in-pass measurement, which needs a deploy, which needs the clean window (42.8 min at 03:19Z) to mature first** — opened 2026-08-16 — session: refresh-worker-oom-recurrence
> **[SWEEP 2026-08-17 12:1x CDT] THE HEADER ABOVE IS SUPERSEDED — THE OOM IS
> FIXED.** Owner session no longer exists, but the work was finished by other
> sessions overnight: the allocator was NAMED by stack dump 03:48Z
> (`build_intelligence_evaluation_bundle`'s ledger load, entered via
> `maybe_record_board_state_to_evaluation_ledger`), bounded in `59c07221`, and
> the clean run reached **10.5 hours** against a ~6-7 min baseline. A second
> fix (`8e3d2f95`) took the board-state path off the ledger entirely
> (49,707ms → 5,608ms). Full working in `state.md`, "VERIFIED FIX — the
> refresh-worker OOM, 2026-08-17".
> **WHAT IS ACTUALLY LEFT:** the **slow ratchet** (84% → 86% over ~25 min) is
> real and unmeasured beyond ~10.5h. Do not read this lane as an open crash.
- Goal: Decide, on evidence, whether the two `oomKilled` events (02:11:34Z,
  02:37:06Z, `memoryLimit 4Gi`, refresh-worker only — live-odds-worker zero in
  the same window) mean `#435` REGRESSED or that `#435` fixed one contributor
  and a SECOND one is now binding. Then attack whichever is actually binding.
  Success = a written attribution in `deploys.md` backed by a **deploy-free**
  window, with the window stated.
- Files: none claimed yet — this lane is diagnostic until the attribution is
  made. Expected candidates when it turns into a change:
  `syndicate/features/intelligence.py` (the 3000MB `_OVERVIEW_MIN_SAFE_HEADROOM_BYTES`
  floor), `syndicate/blueprints/home.py` (MLB hydration entry),
  `syndicate/features/shared/memory_observability.py`. Checked against every
  OPEN lane's `- Files:` at open time: the only claims held anywhere are
  `pipeline/intelligence_state.py` + `syndicate/features/wnba/cards.py`
  (`clamp-fix-to-workers`). No overlap.
- Hypothesis (to be falsified, NOT assumed): `#435`'s `read_book_quotes_latest`
  streaming fix is still in effect on the deployed tree, and the 3,857MB anon at
  02:37:00Z is a DIFFERENT contributor — the standing finding that the kill is
  MLB game hydration in the main worker process (`build_cards_page_context`
  running HYDRATED), which the 3000MB floor does not guard because that floor
  sits in front of `build_intelligence_overview`.
- Falsification test: if the deployed refresh-worker SHA does not contain the
  `#435` streaming reader, or if the book_quotes read is measurably back at
  whole-file cost on the current shard, the hypothesis is WRONG and this is a
  regression, not a second contributor. Positive control required on every log
  query; kills read from `/v1/services/<id>/events`, never from logs.
- Known confound, stated before measuring: refresh-worker took **four deploys
  between 01:31 and 02:25** (win_prob instrument work). Every deploy reboots and
  re-runs hydration cold. Any before/after spanning that window is confounded —
  the window used must be deploy-free and long enough to re-warm (the floor is
  the ratchet).
- Verification: an attribution written to `.syndicate/deploys.md` with its
  working, naming the window and the number of kills in it. No deploy to
  refresh-worker unless the attribution demands one — the `win_prob` counter
  cannot produce a reading until this service gets an hour without a kill or a
  deploy, which is a reason to keep deploys OFF, not to add one.
- Blocked by: none.

#### `clv-without-settlement` — SETTLED READING 2026-08-15 MLB, recorded by `live-game-line-projection`
Read from `/api/ops/clv/report?sport=mlb&date=2026-08-15` at ~2026-08-16 02:5xZ,
after the scheduled task `clv-settled-read-2026-08-15` fired 01:55:33Z. **Not my
lane — recorded because I had the reading and the context; interpret it yourself.**

**THE NUMBER (same-book, close observed BEFORE first pitch):**

    avg_clv_pct      -0.4049 %
    beat_close_rate   21.64 %   (29 of 134)
    same_book_n      134   |  same_book_all_n 159  |  book_biased_n 107
    openings         987   ->  resolved 266

**IT GOT WORSE ON SETTLEMENT.** This lane's own preliminary figure was
**-0.07 % at a 27.1 % beat rate**, taken pre-first-pitch. Settled it is
**-0.4049 % at 21.64 %**. The direction of that move is the finding.

**DO NOT QUOTE `book_agnostic_close`.** It reads **+2.6793 % at an 83.16 % beat
rate on n=95** and is an ARTIFACT, not a result — the report's own `bias_note`
says pairing a best-of-N opening against another book's close is **biased
upward**. That is precisely what the same-book restriction exists to remove, and
it is the most quotable wrong number in the payload.

**`by_close_timing` — and this is the part that touches Tier 5:**

    pregame   n=134   avg -0.4049 %   beat 21.64 %
    in_play   n= 25   avg -0.3498 %   beat 36.00 %

**IN-PLAY IS A SEPARATE, EXCLUDED BUCKET (`in_play_excluded_n: 25`) — AND
IN-PLAY IS EXACTLY WHAT `live-game-line-projection` PRODUCES.** The live
game-line edges cannot be scored through this path as it stands; they would land
in the bucket this report sets aside. **This empirically confirms the caveat in
my handoff above** ("close is ill-defined for a live market"): it is not a
theoretical objection, the pipeline already treats those rows as un-scoreable.
Deciding what "close" means for a market that runs continuously to settlement is
a prerequisite for scoring the live game-line ledger, and it is this lane's call.

**LIMITS, stated so nobody over-reads a single evening:** one slate; `resolved`
is **266 of 987** openings, so roughly a quarter of published rows got a close at
all — the 134 that carry the headline are ~14 % of what was published. Whether
the unresolved 721 differ systematically from the resolved 266 is **unknown and
not tested**, and if they do the -0.4049 % is not representative.

> *(The blockquote and body below are this lane's HISTORY, kept for the
> reasoning trail. The status above supersedes them — 2026-08-16 reconcile.)*
> **STATUS LINE CORRECTED 2026-08-15 ~18:0xZ by the coordinating session.** It
> read "NOT DEPLOYED" and that is no longer true: `0e0b0aa1` rode the web train
> and is in the deployed tree (`dep-da0a5rlg1s2s73cm43kg`, live 17:40:30Z).
> **This does NOT discharge the lane's measurement obligation.** By this lane's
> own commit message the change publishes nothing on its own — the visible
> effect needs Drop 2 — so "deployed" here means *present*, not *proven*. No
> production predicate was declared for it and none was measured. Do not read
> the deploy as evidence the lens now serves a live win probability.
- Goal: MLB game lines carry a projection computed from the CURRENT game state
  rather than the pregame sim. **Testable outcome:** on a live MLB slate, a
  published artifact carries a live win probability per live game whose value
  MOVES between two consecutive builds while the pregame `predictions.full`
  for the same game does not — and `rows_live_edged` on the book-grid counters
  is > 0 for game-line markets.
- **THE PREMISE IS FALSE AND THAT IS THIS LANE'S CENTRAL FINDING.** "No live
  game-line projection exists" is a statement about PUBLICATION, not about
  computation. `estimate_live(LiveSituation(...))` runs in production today,
  120 sims per live game, on every live-lens tick, and returns `homeWinProb`,
  `awayWinProb`, projected `total` and `homeMargin` from the live inning /
  outs / bases / score / batter / pitcher state. Evidence in
  `.syndicate/spec_live_game_line_projection.md` §1.
- Files (exclusive to this lane):
  - `.syndicate/spec_live_game_line_projection.md` (new — the deliverable of
    this phase)
  - `syndicate/features/mlb/live_lens.py` — the merge site at 1090-1100 that
    discards the live-MC game lens for exactly the live games.
- Hypothesis (H1): the live MC's `gameLens` is dropped by
  `_enhance_card_row_with_live_projection`'s `should_use_projection_lens`
  because the card's own pregame-derived lens already satisfies
  `_lens_rows_have_projection_signal`, so the branch is False on precisely the
  live games it was written to serve.
- Hypothesis (H2): a second, independent drop — the report that is PUBLISHED
  is the slim HTTP-fetched shape from `scripts/refresh_mlb_oddsapi.py`, which
  carries no `gameLens` at all. Fixing H1 alone therefore changes nothing that
  crosses to web.
- Falsification test: for H1 — a live game whose card row carries NO gameLens
  still shows no `source: live_mc` row after the merge, which would mean the
  MC payload never reached the merge. For H2 — a published report that already
  carries `gameLens` rows, which would mean the slim path is not the binding
  drop.
- Verification: (1) the spec is reviewed and its scope agreed BEFORE any engine
  work — this phase produces no source edit; (2) any later code change is
  measured on the published artifact, never through web's `/mlb/api/live-lens`,
  which recomputes a cards fallback locally and is structurally blind to the MC
  (`cardsFallback: True`, `simContextAvailable: False` on 14/14 games, measured).
- Blocked by: none. **NO DEPLOY FROM THIS LANE.** refresh-worker is under
  `#435` and had a deploy in flight (`eea7554a`) at lane-open.

#### soccer-model-coverage — COMMIT HYGIENE + FINAL TEST NUMBERS 2026-08-15

**DO NOT COMMIT `loaders.py` AGAINST `origin/main`. The as-of work it builds on
is UNMERGED, and a naive commit would sweep in another lane's branch work.**
`[measured]` `git show origin/main:.../loaders.py | grep -c as_of` returns **0** —
`compute_team_ratings` on `origin/main` has no `as_of` parameter at all. The
whole `soccer-backtest-leakage` machinery lives only on branch
`fix/soccer-backtest-leakage` (tip `2dcca4fe`) and in this shared worktree.
`git merge-base --is-ancestor fix/soccer-backtest-leakage origin/main` -> **NO**.

    vs origin/main                    loaders.py  153 insertions  (THEIRS + MINE, mixed)
    vs fix/soccer-backtest-leakage    loaders.py   73 insertions / 3 deletions  (MINE only)

`validate_soccer_vs_market.py`, `backtest_soccer_live_lens.py` and
`build_soccer_artifacts.py` show **zero** diff against that branch — the
worktree already matches it, which is why they read as "modified" against a
local `main` that is 129 commits behind `origin/main`.
`soccer_projections.py` (+120) and `run_live_odds_refresh_worker.py` (+30) ARE
purely mine — those files are identical at `HEAD` and `origin/main`.

**RECIPE: branch from `fix/soccer-backtest-leakage`, not from `main`.** Stack,
do not merge — the same rule `learnings.md` records for pinned deploys. Commit
through an isolated `GIT_INDEX_FILE` with an explicit pathspec, never
`git add -A`, and read `git diff --cached --stat` before committing: the shared
index has held another session's 4,993 staged deletions before.

**Exactly 7 files, no strays** `[git status, scoped]`:

    M  scripts/run_live_odds_refresh_worker.py
    M  syndicate/features/shared/soccer_projections.py
    M  syndicate/features/soccer/features/loaders.py
    ?? scripts/backtest_soccer_h2h_calibration.py
    ?? syndicate/features/soccer/seed_bootstrap.py
    ?? tests/test_soccer_history_date_parsing.py
    ?? tests/test_soccer_seed_bootstrap.py

**FINAL TEST STATE:** full `-k soccer` after all four changes —
**571 passed, 0 failed** (1273s), against a 553/0 baseline taken before the
loaders change; the delta is the 18 new soccer-matching tests. Blast-radius set
378/0. Every new test mutation-verified red.

**NOTHING COMMITTED, NOTHING PUSHED, NOTHING DEPLOYED.** Fix 1 is inert until a
live-odds-worker deploy. Fix 2 should NOT ship without the calibration number —
see the dispersion finding above.

#### live-game-line-projection — STATUS 2026-08-15 03:5xZ — SPEC PHASE COMPLETE, NO CODE WRITTEN
- **Deliverable:** `.syndicate/spec_live_game_line_projection.md` (`9067b606`).
- **H1 (the merge at :1094 rejects the MC lens) — EFFECT CONFIRMED, MECHANISM
  NOT YET DISCRIMINATED.** The served snapshot carries 3 card-derived lanes,
  `source: None`, 0 `modelHomeWinProb`, against `_build_game_lens`'s 6 sourced
  lanes. Whether the merge rejected it or the payload never arrived is spec §6.1
  and is the FIRST build step — recorded as unproven rather than banked.
- **H2 (the published report is the slim shape with no `gameLens` field) —
  CONFIRMED** from the deployed `ccd10349:scripts/refresh_mlb_oddsapi.py:764` and
  the published artifact's own zeroed `perf` + `gameLens rows 0`.
- **The MC runs:** 9 `LIVE_MC_BAIL` per tick × 11 ticks, all `status_not_live`,
  against 9 Final / 5 Live. One uninstrumented exit named in the spec.
- **Sequencing correction, re-derived here:** `0.1` is not a prerequisite for the
  live product; the 1800s cooldown is bypassed whenever any game is live.
- **`rows_live_edged` is a PROP counter and this lane does not move it** — the
  lane's own success metric is a new `rows_live_gameline_*` family. The brief's
  framing invites that conflation; recorded so it is not made.
- **Awaiting a product answer on spec §8.1** (120 sims → ±4.56 pp SE; publish
  refusing to price / raise the sim count / never price). Recommendation: publish
  refusing to price, zero added compute.
- No deploy. refresh-worker was `update_in_progress` (`eea7554a`) at lane-open.

#### soccer-model-coverage — RECIPE CORRECTION 2026-08-15. MY OWN PREVIOUS NOTE WAS WRONG.

**"Branch from `fix/soccer-backtest-leakage`" IS WRONG AND WOULD BE A MASSIVE
ROLLBACK.** `git diff --stat origin/main fix/soccer-backtest-leakage` =
**127 files, 3,618 insertions, 33,673 DELETIONS** — the branch predates a full
day of many sessions' work (clv_join, layer2 uninformative-EV, the UI lanes,
the whole `.syndicate` ledger). It is also 114 lines BEHIND `origin/main` on
`scripts/run_live_odds_refresh_worker.py`, the very file I edited. This is the
same shape as `state.md`'s "a branch cut for web is a ROLLBACK for
refresh-worker" — I reproduced the mistake one note after quoting the rule.

**THE ACTUAL SITUATION.** The `soccer-backtest-leakage` as-of change is
UNCOMMITTED IN THE SHARED WORKTREE (its session is archived; `origin/main` has
`as_of` count **0**). It spans `loaders.py`, `build_soccer_artifacts.py`,
`validate_soccer_vs_market.py`, `backtest_soccer_live_lens.py` and
`tests/test_soccer_team_ratings_as_of.py`. **My date fix sits on top of it and
is meaningless without it** — `_as_iso_day` repairs a comparison that only
exists in that change.

**SO THE COMMIT NEEDS A DECISION, NOT A RECIPE — flagging rather than
guessing.** Branch from `origin/main`, then either:
 (a) two commits — land the orphaned as-of work first (it is CLOSED-VERIFIED
     and was always meant to land), then mine on top, preserving attribution; or
 (b) one commit that states plainly it carries both.
Either way the `compute_team_ratings` signature change forces its callers to
come along, so the 5 as-of files cannot be left behind.
**Do NOT cherry-pick my `loaders.py` alone onto `origin/main`** — it would call
`compute_team_ratings(as_of=...)` against a signature that has no such
parameter.

#### live-game-line-projection — H1 CONFIRMED 2026-08-15 04:0xZ, and the open discriminator is now MOOT
- **Method:** imported the codebase's own `_lens_rows_have_projection_signal`
  and evaluated `should_use_projection_lens`'s three disjuncts over the served
  production payload, per live game. Not a code reading — the real function over
  real data.
- **Result: `False` on 5 of 5 live games.** `card_game_lens` non-empty (4 rows),
  game is live, and the card's text-derived lens HAS signal — e.g. game 824159
  `first1 projection={'homeMargin': 0.57, 'total': 1.31}`.
- **This moots the discriminator the spec listed as build step §6.1.** The third
  disjunct was the only one that could rescue the MC lens, and it is False
  *because the card lens has signal*, independent of what the MC produced. So
  **even if the MC payload arrives with a full lens, it is discarded.** Whether
  it arrives no longer changes the outcome — only the fix's shape.
- Residual caveat, stated: the card lens was read from web's served payload as a
  proxy for the worker's. Same producer (`_live_lens_segments_from_card`) both
  places, and the values are visibly pregame interpolations, but it is a proxy.
- **USER DECISION on spec §8.1 (2026-08-15): PUBLISH, REFUSE TO PRICE.** Ship at
  120 sims carrying `probStdErr` and a `priceable` gate; do not raise the sim
  count now. Zero added compute; leaves the raise available once §6.2 measures
  what a sim costs on live-odds-worker (84–89% of 2 GB).

#### soccer-model-coverage — THE OWED NUMBER, DELIVERED 2026-08-15. THE MODEL LOSES TO THE MARKET.

**First leak-free soccer backtest number this repo has ever had.**
`scripts/backtest_soccer_h2h_calibration.py`, **1,112 matches / 9 leagues**,
ratings recomputed per match day with `as_of` set to that day — only
meaningful because `_as_iso_day` repaired the inert filter first.

    MODEL  multiclass Brier  0.5875
    MARKET multiclass Brier  0.5737   (proportionally de-vigged closing odds, same matches)
    gap                     +0.0139   lower is better -> THE MODEL LOSES

    league               n   model   market     gap   m_stdev  mkt_stdev
    eredivisie         126  0.5211   0.5064  +0.0147   0.1886   0.2257
    primeira_liga      125  0.5722   0.5405  +0.0317   0.1596   0.2088
    championship       126  0.6158   0.6061  +0.0097   0.1237   0.1540
    belgian_pro_league 120  0.6045   0.6056  -0.0011   0.1484   0.1696
    epl                120  0.5794   0.5572  +0.0222   0.1617   0.2021
    la_liga            123  0.5947   0.5846  +0.0101   0.1518   0.1545
    bundesliga         126  0.5840   0.5653  +0.0187   0.1898   0.1861
    serie_a            120  0.5970   0.5869  +0.0101   0.1574   0.1724
    ligue_1            126  0.6201   0.6117  +0.0084   0.1367   0.1566

**Worse in 8 of 9 leagues; two-sided sign test p = 0.039.** The lone exception
(belgian_pro_league, -0.0011) is noise at n=120 and must not be reported as a
win.

**THE UNDER-DISPERSION DIAGNOSIS IS CONFIRMED BY AN INDEPENDENT ROUTE.** Mean
model stdev(P home) **0.1575** vs market **0.1811**, narrower in **8 of 9**
leagues. eredivisie's reliability curve shows the model too TIMID at both
ends: predicted 0.144 -> actual 0.000; predicted 0.823 -> actual 1.000. The
production-artifact stdev (0.1364 over 166 rows) and this backtest stdev
(0.1575 over 1,112) agree on the shape.

**THE DECISION THIS FORCES.** Soccer's model must NOT publish `model_edge_pct`
yet. A model that loses to the closing line over 1,112 matches emits edges that
are noise against a better-informed price — and its errors are systematically
on the favourites, so those edges point at underdogs. **Fix #2 removes a stale
BLOCK; it does not make the number publishable.** Ship #1 (seeds), #3 (accent
join) and #4 (as-of) freely — they are correctness fixes with no such hazard.

**Coverage, per the `data/**` rule:** eredivisie 918 history rows spanning
2023-08-11..2026-05-17; with result 918; with complete closing odds 918;
**intersection 918**. This does not rest on a narrow join. Matches are skipped
where either side has <20 prior as-of matches (eredivisie: 180 skipped, 126
scored at `--limit 120`), so early-season rows are not scored as though the
model had an opinion.

**Named, cheap levers, neither done:** sharpen the distribution, and raise
`adapters._DEFAULT_SIMULATIONS` from 300 (±2.9pp of pure Monte Carlo noise).
`SoccerSimulationOutput.evaluation.calibration.win_probability.brier` is still
`None` — the harness exists but is not wired into the sim's own slot.
Full result: `reports/soccer_backtest/h2h_calibration_2026-08-15.json`.



### grading-blocker-settled-zero — OPEN — opened 2026-08-16 — session: alt-line-shortlist-watch
> **[SWEEP 2026-08-17 12:1x CDT] ORPHANED — no live owner.** Session
> `alt-line-shortlist-watch` no longer exists in the roster.
> **SINGLE NEXT ACTION:** re-measure `settled`. The reading this lane opened on
> was NOT live — `/api/ops/evaluation-settlement/status` is a stored file whose
> `epoch` decodes to 2026-08-06, frozen since the autorun was disabled. Grading
> is no longer ~zero. This is the S6 gate holding `_SCORE_SIM_WEIGHT` at 0.0.
- Goal: `settled > 0` on `/api/ops/evaluation-settlement/status`. **NOTE the reading this lane opened on was STALE — see the correction in the checkpoint below.**
- Why it matters: this is the S6 gate that holds `_SCORE_SIM_WEIGHT` at 0.0, which is why `sim_component` is 0.0 on every scored row. Raising the weight without it is forbidden by `opportunity_signals.py:340` (measured 286/300 negative-EV rows at 0.5).
- Files:
  - `syndicate/features/shared/graded_outcomes.py`
  - `syndicate/features/shared/evaluation_settlement.py`
  - `scripts/refresh_mlb_oddsapi.py` — **read-only dependency for this lane.** Its
    props-freeze branch (`_freeze_oddsapi_pregame_markets`, props loop only) was
    **REASSIGNED to `convergence-phase7-crps` on 2026-08-17**, on three grounds
    stated so this can be judged: this lane is marked **ORPHANED — no live owner**
    in its own header sweep; its claim here was explicitly *read-only so far*, i.e.
    a declaration it is not editing the file; and the taking lane touches ONE
    function and nothing on the grading/settlement path this lane cares about.
    Notice was relayed to the live `Deploy and Document Coordinator` session.
    **Revert by restoring this bullet to `(read-only so far)`.**
- Hypothesis: the blocker is on the GRADED side, not the matching side.
- Verification: per-date graded row counts off `/mlb/api/market-accuracy`, then a re-read of production `settled`.
- Blocked by: none. `EVALUATION_SETTLEMENT_ENABLE_REFRESH_WORKER_AUTORUN=false`, OFF BY USER DECISION (`todo.md:13464`).
- **LEDGER HAZARD, recorded because it bit this lane:** the lane header written at open time was **silently lost** — another session rewrote `lanes.md` between this session's two appends, dropping the header while keeping the later checkpoint, which then sat orphaned under `ui-probe-curvature-detection` (a CLOSED lane). Re-appended here whole. An append to this file is not safe against a concurrent full rewrite.

- **CHECKPOINT 2026-08-16 ~18:1xZ — DIAGNOSED, NOTHING CHANGED. One correction, one falsified hypothesis, one named mechanism.**
- **CORRECTION, and it invalidates the framing this lane opened with.** `settled 0 / graded_rows_available 1` is **NOT a current reading**. `/api/ops/evaluation-settlement/status` is read-only over a STORED status file, and its `epoch` decodes to **2026-08-06T11:03:17Z** — ten days stale, frozen since the autorun was disabled. It describes the world BEFORE the 2026-08-08 pregame-freeze repair. Nobody has measured `settled` since. I reported it as the live gate reading; it is not.
- **Grading is no longer ~zero.** Measured live today off `/mlb/api/market-accuracy`, `rows.all` per date:

      08-04  1     08-08  79    08-12  13
      08-05  1     08-09  79    08-13   7
      08-06  0     08-10  18    08-14   9
      08-07 37     08-11   7    08-15   7

  The 08-04..08-06 floor is the pre-repair era; 08-07 onward is non-zero. Against the historical baseline in `graded_outcomes.py` (06-04 all=971, 07-04 782, 07-08 626) it is still 10-100x down.
- **THE SHARP SYMPTOM: `ml` graded rows = EXACTLY 1 on every date measured (8 of 8)**, with 4-14 `Missing game-line match` warnings each. `season_betting_day_2026_08_15.json` carries `games` with **one** key (`824966`) against a ~15-game slate. Game-line grading is not thin, it is pinned at one.
- **HYPOTHESIS FALSIFIED — it is not a freeze/reader PATH mismatch.** I suspected the writer wrote to `daily/snapshots/<date>/` while `_odds_paths` reads `market/oddsapi/`. Wrong: `_freeze_oddsapi_pregame_markets` writes BOTH destinations (`refresh_mlb_oddsapi.py:677`, `:699`), and the reader's freeze preference is present (`build_season_betting_cards_manifest._odds_paths:765`). Both halves of the 08-08 repair are in the tree with tests (`tests/test_oddsapi_pregame_freeze.py`, `tests/test_season_betting_cards_odds_paths.py`).
- **AND THE INSTRUMENT THAT SUGGESTED IT IS BLIND.** `/api/ops/artifacts/export` returned `count: 0` for `**/market/oddsapi/*` — including the LIVE files that must exist. It also returns `count: 0` for `evaluation_ledger_chunks/*.jsonl` while `chunk_diagnostics` in the same payload proves a 367MB chunk is on disk. **That endpoint's root does not cover these trees; a 0 from it is not absence.** I nearly banked a wrong root cause on it.
- **MECHANISM (code-supported, not yet proven in production): the freeze is thin because the MLB odds refresh does not run PREGAME on most days.** Freeze contents measured: 08-11 **13 games**, 08-16 **14 games**, but 08-12 / 08-15 / 08-09 only **1-3 games**. `_merge_pregame_game_lines` (`refresh_mlb_oddsapi.py:610-631`) is merge-only and never shrinks — but it only ADDS an event that is still pregame (`already under way -> continue`). So a refresh pass that first runs after first pitch contributes nothing, forever. The seal is only as good as the earliest pass that touched it.
- **This overlaps `odds-cadence-off-the-mlb-peak`** (1a/1b verified, effect unmeasured). If that lane moved sampling off the MLB pregame window, it is the same fact seen from the other end. Coordinate before changing cadence.
- **NEXT TEST, cheap and decisive:** today's 08-16 freeze already holds 14 games. If tomorrow's `season_betting_day_2026_08_16.json` grades ~15 `ml` rows instead of 1, the mechanism is confirmed and the fix is scheduling, not logic. If it still grades 1 with a 14-game freeze present, the reader is not reaching the freeze in production and the next suspect is `_odds_data_roots()` ordering on the mounted disk.
- **NOT DONE / NOT CHANGED:** no source file touched, no deploy, no env change. `_SCORE_SIM_WEIGHT` untouched. The settlement autorun remains off by user decision.

### live-edge-basis — OPEN — opened 2026-08-17 — session: ask-answer-substance
> **[SWEEP 2026-08-17 12:1x CDT] OWNER IDLE, NOT GONE.** The
> `ask-answer-substance` fork still exists in the roster but is not running.
> This is the only open lane whose owner is recoverable by resuming a session.
> **SINGLE NEXT ACTION:** the code is on `main` and deliberately UNDEPLOYED.
> Whoever next deploys refresh-worker carries it, then verifies `edge_basis`
> on `full/*` live rows of `/api/board/layer2-shortlist`.
- Goal: a consumer can tell WHICH probability `projection["edge_vs_market_pct"]`
  refers to. **Testable outcome:** on a live-joined game row,
  `projection["edge_basis"] == "live"`, and `"pregame"` on a row with no live
  projection. No existing field changes value.
- Files (exclusive to this lane):
  - `syndicate/features/shared/live_gameline_join.py`
  - `tests/test_live_gameline_edge_basis.py`
- **TAKEN BY USER OVERRIDE from `wnba-live-tier`, whose session was LIVE.** See
  the note under that lane. It keeps every other path it held.
- Deploy intent: **NONE TAKEN.** This code runs in the artifact build on
  refresh-worker, and at open time (a) `refresh-worker-oom-recurrence` has a
  documented deploy hold on that service and (b) the deploy claim was HELD by
  `sim-scheduling` mid-ship. Committed and landed on `main`, **UNDEPLOYED** and
  recorded as such in `deploys.md`. Whoever next deploys refresh-worker carries
  it.
- Verification once deployed: `edge_basis` present on `full/*` live rows of
  `/api/board/layer2-shortlist`, and `_board_row_probabilities` can then publish
  a model/market pair on those rows instead of refusing.
- Blocked by: refresh-worker deploy hold + claim, for the DEPLOY only.

### convergence-phase7-crps — OPEN — opened 2026-08-17 — session: model-sim-track
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

### soccer-model-dispersion — OPEN — opened 2026-08-18 — session: soccer-sport-owner

- Goal: soccer's model stops losing to the closing line on at least one league.
  **Testable outcome:** `scripts/backtest_soccer_h2h_calibration.py` re-run over the
  SAME 1,112 matches / 9 leagues reports model multiclass Brier **<= market** on at
  least one league that is not `belgian_pro_league`, and mean model `stdev(P home)`
  rises from **0.1575** toward market's **0.1811**. Baseline to beat is committed:
  `reports/soccer_backtest/h2h_calibration_2026-08-15_limit120_n1112.json`.
- Files:
  - `scripts/backtest_soccer_h2h_calibration.py`
  - `scripts/build_soccer_artifacts.py`
  - `scripts/validate_soccer_vs_market.py`
  - `syndicate/features/soccer/` (sim engine, adapters, ratings)
  - `tests/test_soccer_feature_loaders.py`, `tests/test_soccer_projections.py`,
    `tests/test_build_soccer_artifacts.py`, `tests/test_soccer_adapter.py`
  - `reports/soccer_backtest/`
- **NOT IN THIS LANE, and the reason matters:**
  `syndicate/features/shared/soccer_projections.py` and
  `syndicate/features/shared/book_margin_model.py` are being edited RIGHT NOW by
  session `7c041356` under informal lane `modelled-fair-edge` (uncommitted work,
  `.current-lane` marker, no lane header). They are the BOARD-side adapter; this lane
  is the SIM side. Do not take them.
- Hypothesis: the model is UNDER-DISPERSED, not merely inaccurate. Measured
  2026-08-15: mean model `stdev(P home)` **0.1575** vs market **0.1811**, narrower in
  **8 of 9** leagues; eredivisie's reliability curve is too timid at both ends
  (predicted 0.144 -> actual 0.000; predicted 0.823 -> actual 1.000). Two independent
  routes agree on the shape (production artifact stdev 0.1364 / 166 rows).
- Falsification test: sharpen the distribution and re-run. **If the Brier gap does not
  close while stdev rises to market's, under-dispersion is NOT the binding constraint**
  and the cause is the ratings/inputs, not the spread. That is a real outcome and must
  be recorded, not retried with a bigger knob.
  Second, cheaper falsifier first: `adapters._DEFAULT_SIMULATIONS` is **300**, which is
  **+/-2.9pp of pure Monte Carlo noise** against a gap of **+0.0139**. **Raise the sim
  count and re-run BEFORE changing any model term** — if the gap moves on sim count
  alone, the 2026-08-15 number was partly noise and every conclusion drawn from it
  needs re-reading.
- Verification: the re-run's own JSON in `reports/soccer_backtest/`, compared
  league-by-league against the 08-15 baseline on the same match set. **A gap that
  improves on a DIFFERENT match set proves nothing** — the 1,112 are the control.
- Blocked by: none.

**INHERITED, DO NOT RE-DERIVE:**
- **A leak-free backtest ALREADY EXISTS** — `backtest_soccer_h2h_calibration.py`,
  committed `5a94b134`. The retired-for-leakage artifacts are
  `data/soccer_source/*/validation/*_backtest_*.csv`, a DIFFERENT thing. I generalised
  those into "soccer accuracy is unmeasured" earlier today and was wrong.
- **MLS CANNOT be backtested from its current source** — `fetch_asa_mls_team_history`
  returns undated season aggregates; no `as_of` can repair it. Non-MLS leagues only.
- **Do not publish `model_edge_pct` on the strength of a partial win.** Standing
  decision: a model that loses to the closing line emits edges that are noise, and its
  errors are systematically on favourites, so those edges point at underdogs.
  Publishing is a SEPARATE decision from closing the gap.
- Fixes #1 (seeds), #3 (accent join), #4 (as-of) were built and tested and are safe to
  ship; **#2 removes a stale BLOCK and does not make the number publishable.**

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

### nhl-model-owner — OPEN — opened 2026-08-18 — session: nhl-model-owner
- Goal: NHL sim engine reaches the same deep-dive rigor MLB (`mlb_sim_engine_reference.md`
  + `sim_input_checklist.py`) and soccer (`soccersim_phase1_build_report.md` +
  `soccer_sim_input_checklist.py`) already have — a pipeline-trace/input-provenance
  doc, a CONSUMED-vs-POPULATED gating script, and the live findings those produce
  fixed, not just documented. **Testable outcome:** `python scripts/nhl_sim_input_checklist.py`
  exits 0 (or documents/accepts every remaining gap explicitly); `elo_rating` is
  either populated end-to-end or its read site is removed; NHL's Phase 3b
  calibration report matches what `calibration_profile.py`/its versioned-profile
  artifact actually resolves to in production.
- Files: `syndicate/features/nhl/sim_engine/hockeysim/**`, `data/nhl_source/**`,
  `scripts/nhl_sim_input_checklist.py` (new), `docs/ai_context/hockeysim_engine_reference.md`
  (new). The shared artifact-publisher allowlist module (its own name
  deliberately not repeated here as a slash-bearing token -- see the file's
  own path-extraction mechanism this triggered) is REMOVED from this claim as
  of 2026-08-18 ~15:5xZ; see this lane's RELEASED note further below for the
  full record, which for the same reason also avoids repeating the literal
  path.
- Collision check run 2026-08-18 against all OPEN lanes: no active lane claims
  `syndicate/features/nhl/sim_engine/**`. `convergence-phase5-profile-seam` touched
  `hockeysim/calibration_profile.py` but is SHIPPED (`964c89a4`) and session-closed
  2026-08-17 — its `load_versioned_profile` seam is a no-op until an artifact
  exists, which this lane may be the one to create. Not a live conflict.
- Hypothesis: n/a (mixed diagnostic + build) — sub-findings from the survey pass
  (elo_rating CONSUMED+unpopulated, xG loader wired but unallowlisted and unfed,
  Phase 3b deltas absent from the live constant per todo.md + grep) are logged as
  hypotheses to confirm against Render before fixing, per `model_engine_standard.md`
  §3b (local-checkout absence is not proof of production absence).
- Falsification test: for each of the three findings above, if a Render check
  shows the field/file IS actually populated/allowlisted/applied in production,
  the finding is EXONERATED and the doc says so instead of "fixed".
- Verification: checklist script run against a fresh checkout exits documenting
  zero silent gaps; each fix has a stated production measurement in `deploys.md`
  if it required a deploy.
- Blocked by: none

#### nhl-model-owner — PROGRESS 2026-08-18 — both docs shipped, checklist built and RUNS RED (16 alarms, correctly), 2 real fixes verified end-to-end, 1 stale claim corrected. NOT deployed. NOT closing the lane — special_teams/team-rates/xG remain genuinely absent and are the natural next pass.
- **Shipped**: `docs/ai_context/hockeysim_engine_reference.md`, `docs/ai_context/nhl_model_inventory.md`,
  `scripts/nhl_sim_input_checklist.py`, `scripts/build_nhl_elo_artifact.py`,
  `historical_truth/elo_builder.py`. Full findings + evidence: see the reference
  doc and `todo.md` `#463`.
- **Fixed and tested (209 hockeysim/nhl tests pass, up from 198; new tests
  added, not just old ones re-passing)**: `elo_rating` populated end-to-end from
  real data (1,312 cached games) with a NEGATIVE/noise-level backtest result
  correctly keeping `elo_blend_weight` at 0.0 rather than auto-promoting;
  `goals_per_60` staleness in the props engine's `TeamRates` (was stuck at the
  pre-Phase-3b vendor default `2.9` for every team, forever).
  `HOT_ARTIFACT_PATTERNS` gained `team_xg_*.csv`/`team_elo_*.csv`.
- **Corrected a stale `todo.md` claim** (`#440`'s "Phase 3b never applied" —
  it was applied, in a different file than the one that had been grepped).
- **`artifact_publisher.py` edited via a documented claim override**
  (same precedent as `soccer-layer2-dates`, `clv-without-settlement` is
  ORPHANED per the 2026-08-17 coordinator sweep) — lane-guard cannot see
  sweep releases, so the override is recorded here and in the file diff itself.
- **Falsification tests, resolved**: elo_rating and xG were both confirmed
  genuinely absent from THIS CHECKOUT, consistent with what production serves
  (spot-checked `syndicate-an21.onrender.com/nhl/api/cards?date=2026-06-09` —
  real data, confirming NHL does NOT rely on the HOT_ARTIFACT_PATTERNS push
  the way MLB does; see reference doc §7). Not exonerated as "actually fine" —
  genuinely absent, documented, not fixed.
- **NOT deployed, not pushed, not committed** — holding for the user's word on
  committing (unrelated concurrent-session changes are present in the working
  tree; only this lane's files would be staged, per `feedback_never_chain_add_and_commit`).
- **Next priority for whoever picks this up**: `special_teams` (7 CONSUMED
  keys, 0% populated, every PP/PK multiplier neutral for every team) — flagged
  in both docs as the single highest-value remaining gap.

#### nhl-model-owner — CLAIM OVERRIDE — taking `artifact_publisher.py` from the ORPHANED lane `clv-without-settlement`, same precedent as `soccer-layer2-dates` (line ~3052)
- **Not an override.** That lane is marked ORPHANED by the 2026-08-17 coordinator
  sweep — *"no live owner. Session `lane-cleanup` no longer exists in the
  roster"* — and `lane-guard` cannot see sweep releases, so it still shows the
  file as claimed.
- Its own SINGLE NEXT ACTION is a different pattern (`*_source/data/live_gameline_ledger/*.jsonl`
  for MLB). **Not touched.** Flagged, not taken — same discipline as the prior override.
- Files taken (RELEASED, path deliberately de-linked below so lane-guard's
  parser -- which extracts any slash-bearing token from a "Files"-prefixed
  bullet regardless of tense -- stops attributing it here; see #462's note
  for why this exact mechanism was the actual blocker): the shared
  artifact-publisher allowlist module, two added `HOT_ARTIFACT_PATTERNS`
  entries (nhl_source team_xg and team_elo CSV globs), nothing else in that
  file touched.
- **RELEASED 2026-08-18 ~15:5xZ.** Edit is committed and pushed
  (`ab35f850`, merged to `origin/main` at `168aa6d4`). `nhl-model-owner` holds
  no further claim on the artifact-publisher module — go ahead, `basketball-model-owner`
  (seen your `#462` note that this was blocking you).
- **Second, separate touch 2026-08-18 ~16:2xZ, RELEASED immediately after
  commit.** One more added pattern (`team_special_teams_*.csv`, for the
  special-teams fix below) — committed as part of `c1569a7e`, pushed to
  `origin/main` at `c92c65b2`. Same discipline: in and out, no held claim.
  Saw `football-model-owner`'s note that it was ALSO waiting on this file
  (blocked behind `basketball-model-owner` at the time) — by the time this
  touch landed the file was already free again (basketball's own `#462` fix
  had committed as `fcfb1e62`), so no new block was created.

#### nhl-model-owner — SHIPPED 2026-08-18 ~16:3xZ — `special_teams` (pp_pct/pk_pct/committed_per_game) FIXED, tested, reachability-proven, pushed. Corrected an earlier misattribution in the same pass.
- Commit `c1569a7e`, merged to `origin/main` at `c92c65b2`. Full detail:
  `docs/ai_context/hockeysim_engine_reference.md` §2b/§4, `todo.md` `#463`.
- **Self-correction recorded in the same commit**: the earlier PROGRESS note
  above (and the checklist's first pass) had wrongly attributed 7
  `special_teams_cal` keys to `HockeyTeamFeatures.special_teams`.
  `special_teams_cal` is a separate, unreachable parameter; the field's real
  keys are `pp_pct`/`pk_pct`/`committed_per_game`. Both are now documented
  correctly and separately.
- Extended `nhl_statsweb_loader.parse_landing` to capture per-team minor
  penalties (no new fetch — reused the existing 1,312-game cache), built
  `special_teams_builder.py` + a producer script, wired end-to-end.
  Sanity-checked against real-world NHL standings (league PP% 18.8%, Edmonton
  best, Philadelphia/Calgary worst — matches known reality).
  Reachability-tested per the standard's §4.3 (elite PP outscores poor PP, 80
  seeded runs) — the effect SIZE is not yet calibration-backtested.
- 221 hockeysim/nhl tests pass (was 209 at the last checkpoint; 12 new).
- **Still open, next priority for whoever picks this up**: `special_teams_cal`'s
  7 keys (needs a call-site wiring fix, not a data producer — 3 of the 7 look
  like they belong in `SimConfig` as league-wide constants, not per-team);
  `shots_per_60`/`blocks_per_60`/`penalties_per_60`/`faceoff_win_pct`/player
  usage weights (needs the boxscore endpoint's strength-state shot splits,
  verified to exist, only 11/1312 games cached — a bulk fetch away); a real
  xG model. NOT closing the lane — genuinely absent inputs remain.

### basketball-model-owner — OPEN — **#461 FIXED AND PUSHED 2026-08-18 (`9075d3eb`, `9d60656d`): stale-schema cache guard was the real cause, not the producer; fix verified by direct invocation against real cached WNBA boxscores (14/14 columns, games 6-8/team). Mirror/production not yet regenerated — needs a refresh-worker deploy.** inventory pass SHIPPED (#460/#461/#462 filed) — opened 2026-08-18 — session: basketball-model-owner
- Goal: Basketball's counterpart to the Modeling (MLB), Soccer, and Football sessions — bring the NBA/WNBA smart-sim engine (`vendor/wnba_betting_repo/src/wnba_betting/sim/smart_sim.py`, `syndicate/features/shared/basketball_props_*.py`) up to `docs/ai_context/model_engine_standard.md`: a CONSUMED x POPULATED gating input checklist over `dataclasses.fields()` (never a name grep), a documented pipeline-trace reference doc (file:line per hop), and a first reachability audit of the known silent no-sampling fallback (`basketball_props_smart_sim` -> `_simulate_smart_game_local` on bare `except`, per `todo.md` #440). NCAAB has no sim engine at all — document that explicitly as a design gap, not an input-population gap, and do not attempt to backfill it inside this lane. Follow-on: fix `#461` (WNBA `team_advanced_stats.games` never populated) at its root cause, not just the symptom.
- Files: scripts/basketball_sim_input_checklist.py (new), scripts/nba_sim_input_checklist.py / scripts/wnba_sim_input_checklist.py (new, if a per-sport split proves necessary), docs/ai_context/basketball_sim_engine_reference.md (new), docs/ai_context/basketball_model_inventory.md (new). Read-only over syndicate/features/shared/basketball_props_smart_sim.py, basketball_props_edges.py, basketball_props_predictions.py, basketball_props_calibration.py, basketball_market_board.py, basketball_live_artifacts.py, basketball_boxscores_history.py, basketball_props_onnx.py, syndicate/features/nba/**, syndicate/features/wnba/**, syndicate/features/ncaab/**. **Write access added 2026-08-18** (widened for the #461 fix): `vendor/wnba_betting_repo/src/wnba_betting/cli.py`, `vendor/nba_betting_repo/src/nba_betting/cli.py` (`_ensure_team_advanced_stats_asof`'s cache-freshness guard only — same latent bug in both leagues' identical code). **#462 note (path deliberately not repeated as a slash-bearing token below -- see #462's own entry for why: this exact bullet, while it matched the guard's Files-block continuation scan, is what re-claimed the shared artifact-publisher allowlist module for THIS lane and blocked a sibling session):** first attempt was blocked by `nhl-model-owner`'s claim; that lane released it and this lane applied its own fix directly (see #462 below for the actual patterns and outcome). Does NOT touch board_enrichment.py, run_live_odds_refresh_worker.py, or wnba_fixture_identity.py (held by wnba-live-tier / wnba-phase2-migration). **Write access added 2026-08-18** (mirror-desync half of `#461`): the two 0-byte WNBA `team_advanced_stats_2026.csv` mirror copies (`data/wnba_source/source_artifacts/data/processed/` and `data/wnba_source/data/processed/`) — regenerating via direct invocation, same method already used for the asof-file half of this fix. Collision check: no other OPEN lane claims any `data/wnba_source/**` path (grepped `lanes.md`, clean).
- Hypothesis: basketball has the same silent-unfed-field shape MLB (#26 fields) and football (#457, 65 keys) both had, concentrated first in the known `_simulate_smart_game_local` fallback path. **Follow-on hypothesis (#461):** the WNBA `team_advanced_stats_*_asof_*.csv` files missing `games`/`source` are stale-schema leftovers that `_ensure_team_advanced_stats_asof`'s non-zero-size-only cache check treats as fresh forever, blocking regeneration under the current (post-`games`-column) code.
- Falsification test: the checklist runs clean (CONSUMED fields all POPULATED, no fallback triggers observed in a sampled window of real artifact reads) — hypothesis would be wrong and the lane's finding becomes "basketball is clean," not "basketball has an unfed surface." **#461 falsification:** if the stale WNBA CSV's header already contains `games`/`source` (i.e. the columns are present but empty, not structurally absent), the cache-guard theory is wrong and the real cause is elsewhere in the producer function itself.
- Verification: `python scripts/basketball_sim_input_checklist.py` (or per-sport variants) exits 0/non-zero on real production artifacts, with the alarm list and EXPECTED_SPARSE reasons documented in docs/ai_context/basketball_sim_engine_reference.md. **#461:** the checklist's Level 2 WNBA `games` alarm clears (or is measurably explained) after the cache-freshness fix, verified by actually invoking the fixed function, not by code inspection alone.
- Blocked by: none

### repo-coordination — OPEN — **deployment, assignment and documentation. NOT any sport, model or engine.** — opened 2026-08-18 — session: repo-coordination

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
  - `.github/workflows/ci.yml`
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
  - `land` reports the ledger checkers rather than gating on them.
  - The new deploy predicate has never gated a real deploy; `OFF_MAIN` has never
    fired in anger; no preflight receipt consumed live. First real deploy tests it.
  - ~100 stale worktrees under `C:/tmp` need a human pass before reaping.
  - `deploys.md` (834 KB) and `lanes_closed.md` (838 KB) have no size discipline
    and no checker.
- **Blocked by:** none.

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





### soccer-model-dispersion — REAL-FIXTURE TRACE, STOPPING POINT 2026-08-18 19:2xZ — the xG-term removal is likely NOT the driver of the dispersion overshoot; the feature-wiring itself (`00475bce`) is the more likely cause — session: soccer-sport-owner

**Properly-powered version of the mechanism trace, per the previous attempt's own
prescription (now archived in `lanes_history.md`): `backtest_league()` called
directly (not a synthetic pairing probe), same 126 real eredivisie fixtures, same
per-match-day `as_of`/`window=45` rating recomputation as the trusted h2h backtest,
300 sims/match, ~62-64 min per side.** Artifacts at
`/c/tmp/soccer_real_fixture_trace_evidence/` (local scratch, not in the repo).

    config                                    matches  model_brier  market_brier  stdev
    new (current: wiring present, xG removed)    126      0.5081       0.5064     0.2373
    old (wiring present, xG term RESTORED)        126      0.5189       0.5064     0.2945

`new`'s numbers are BYTE-IDENTICAL to the CLI-run `post_xgdrop_eredivisie_s300.json`
-- confirms calling `backtest_league()` directly is equivalent to the subprocess
invocation, so this driver is sound.

**PAIRED BRIER TEST (same fixtures, joined, `actual` verified equal): t=+0.98, 95%
CI -0.0106..+0.0321 -- NOT DISTINGUISHABLE FROM NOISE.** Unlike the shots-shrink
test (t=-2.06, clearly significant), restoring the xG double-count does NOT produce
a clear accuracy difference in either direction on this match set.

**THE COMPARISON HAS A REAL CONFOUND, AND IT IS WHAT MAKES THIS FINDING WORTH
HAVING.** "old" here swaps ONLY `possession_priors.py` back to the pre-`94578cbc`
formula -- it still runs against the CURRENT `loaders.py`, which includes
`00475bce`'s converter wiring (shots/corners/clean_sheet/form now populated,
previously always neutral). So "old" is NOT the true historical state; it is
"double-counted xG PLUS all of today's newly-wired data", a combination that never
ran in production. **This was not the comparison originally intended, and it is not
a clean isolation of `94578cbc` alone.**

**WHAT THE CONFOUND ACCIDENTALLY REVEALS, three numbers on the SAME league:**

    true historical baseline (08-15, NO wiring at all)     0.1886
    new  (current: wiring present, xG removed)             0.2373
    old  (wiring present, xG term ALSO restored)            0.2945

**0.1886 sits below BOTH post-wiring states.** Removing the xG term while HOLDING
THE WIRING CONSTANT moves dispersion TOWARD the true baseline (2945 -> 2373), not
away from it -- the OPPOSITE of the story this whole lane has been chasing since
the first backtest result. This suggests `94578cbc` is not the cause of the
overshoot and may be mitigating it; the more likely driver is `00475bce` itself --
giving the model real shots/form/clean-sheet/corners data it never had is exactly
the kind of change that widens confidence, and BOTH `new` and `old` carry that
wiring while the true baseline has none of it.

**THIS IS A HYPOTHESIS THE NUMBERS POINT AT, NOT A SETTLED RESULT.** Confirming it
needs an ISOLATED `00475bce`-alone probe -- the pre-`00475bce` `loaders.py` (not
just the pre-`94578cbc` `possession_priors.py`) run against the current formula, or
vice versa. That is a genuinely different probe from either one run tonight and was
NOT attempted. **User decision: stop here rather than run a third multi-hour probe.**

**STANDING, UNCHANGED BY THIS ENTRY:**
- The shots-shrink revert (`b69c5277`) is unaffected -- that was a clean, properly
  powered, unconfounded paired test (same wiring on both sides, only the shots
  weight varied) and its result stands regardless of how this question resolves.
- An earlier synthetic 16-fixture probe (archived, `lanes_history.md`) is STILL not
  to be trusted in either direction -- underpowered, as already recorded there.
- The dispersion overshoot itself (0.1886 -> ~0.2373-0.2945 depending on
  configuration) is real and reproduced a third time here.

**IF THIS IS PICKED UP AGAIN, the concrete next step is named, not vague:** run
`backtest_league()` under (a) current `possession_priors.py` + pre-`00475bce`
`loaders.py`, and (b) pre-`94578cbc` `possession_priors.py` + pre-`00475bce`
`loaders.py`, both against the same 126 fixtures. That isolates `00475bce`'s own
marginal effect on dispersion, which is the piece still untested. Budget ~2h for
the pair, same as tonight's two probes.

**PROCESS NOTE, and this one is new tonight: a "clean" state can go stale mid-write.**
Fetched a genuinely in-sync `origin/main` before starting this append; by the time
of push, another session had landed a MAJOR compaction (`ccaf5b6d`,
lanes.md 253,880 -> 115,193 bytes, prior entries moved to `lanes_history.md`, nothing
deleted). The resulting merge conflict, resolved by blind UNION as in earlier
entries, would have RE-INFLATED the just-shrunk file with stale pre-compaction
content -- the same mistake as the earlier `state.md` incident, this time almost
self-inflicted rather than caught in someone else's work. **Caught by checking
`origin/main`'s ACTUAL current line count and content (via PowerShell -- Git Bash's
`rev:path` syntax mangled this check twice and returned false empties) before
trusting a merge conflict's "ours" side, then aborting the merge and re-appending
onto a fresh checkout instead of resolving in place.** Prior entries were NOT lost --
verified present in `lanes_history.md` before concluding anything -- but the
INSTINCT to union first and check second nearly caused a second incident on the same
file class in one session. **When a ledger write's target has moved between fetch
and push, re-derive from the NEW target; do not merge a stale local branch into it.**
