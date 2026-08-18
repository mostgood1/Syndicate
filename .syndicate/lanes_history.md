# lanes_history.md — superseded lane checkpoints



## SUPERSEDED CHECKPOINTS FROM `lanes.md` — 2026-08-18 (coordinator)

Older checkpoint blocks from lanes that are still OPEN. Moved verbatim;
nothing summarised, nothing edited. Each lane kept its most recent 2 blocks
in `lanes.md` -- current state plus one prior for context -- and its history
lives here. lanes.md is read at the start of every session; this file is not.

  - refresh-worker-oom-recurrence: 1 of 3 blocks, 368 lines
  - soccer-layer2-dates: 11 of 13 blocks, 896 lines
  - soccer-model-dispersion: 5 of 7 blocks, 232 lines
  - wnba-live-tier: 5 of 7 blocks, 820 lines

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

### wnba-live-tier — CLAIM OVERRIDE LOGGED 2026-08-16 23:2xZ — `syndicate/features/wnba/cards.py`
- `clamp-fix-to-workers` (OPEN) claims that file. I am taking ONE function in it.
  Reasoning, so this can be judged rather than trusted:
  1. **That lane's code work is DONE by its own status:** "refresh-worker SHIPPED
     `57a437d5` (0 clamp sites by content)... THE ONLY OPEN WORK IS VERIFICATION."
  2. **Zero functional overlap.** Their fix was the ±4900 clamp sites; mine is
     `_public_scoreboard_live_state_payload` (`cards.py:3679`), the ESPN
     scoreboard fetch. Different function, untouched by the clamp work. Their
     verification (`watch_clamp_trigger.py --once`) does not read it.
  3. **Their session is UNATTENDED** (`local_70bfde12…`, a scheduled-task run) —
     `send_message` was attempted and REFUSED by the transport, so there is no
     owner to coordinate with. It is a verification watcher, not active editing.
  4. Explicit user instruction to fix the WNBA live_state dropout.
  One function plus a module-level dict; trivially revertable.

#### `render-events-reader` — RE-COMMITTED 2026-08-16 18:3xZ after a stale-copy revert took the CODE
Restoring this block for the THIRD time, and this instance is worse than the two
before it: the revert hit a **source file**, not just the ledger.

**What happened, verified by ancestry not by memory.** `d72a3f66` and `73668b69`
are **orphaned** — `git merge-base --is-ancestor <sha> HEAD` says NO for both,
while `f4627832` says YES. Current HEAD `fedd17ee` therefore carries
`scripts/render_events.py`, `#442` AND `#444` — but **not** the
`_deploy_trigger` fix that `#444` was found by (`grep -c build_started` on
`HEAD:scripts/render_events.py` = **0**; disk = present). Test count in HEAD is
**12** functions; on disk **14** (17 cases, all passing).

**Why that combination is the dangerous one.** A session committed
`docs/ai_context/todo.md` from a copy that included my `#444`, alongside a copy
of `render_events.py` that predated my fix. So the ledger DESCRIBES a fix that
the tree no longer contains, and every cheap check passes: the file exists, the
todo entry exists, the tool runs. Only a content grep on the deployed-tree file
distinguishes it. Same family as `presence-is-not-reachability` and
`test-the-fixs-predicate-not-its-deploy-state`.

**Re-committed from the working tree, which never lost it.** The fix and its two
regression tests are the only code this lane owns; nothing deployed.

#### game-shape-capture — NFL/NCAAF ADDED, **AND THE NFL EMIT ACTUALLY LANDED** `[2026-08-17 ~00:0xZ]`

First sport whose producer was NOT held by another lane. Claim re-checked
immediately before the edit (the rule this lane learned the hard way at 23:0xZ),
`live_game_state` unclaimed in `lanes.md`.

**A THIRD DISTINCT SITUATION — the plan's field list was wrong again (3 for 3).**
It promised down/distance/field position/timeouts/`pace_secs_play` from a grep.
Measured:
- NFL's `_state_from_event` captures `period`, `clock`, `away_pts`, `home_pts`
  **and nothing else** — no down, distance, field position or possession.
- **BUT `_fetch_scoreboard` returns the WHOLE ESPN event JSON**, whose
  competitions carry a `situation` block that **nothing in `nfl/`, `ncaaf/` or
  `football/` reads** — the only `down` references in the tree are the sim
  engine's internal `play_state` and the historical loaders, neither on the live
  path. **Discarded, not absent** — the MLB pattern, and free to fix.
- **`pace_features.py` IS NOT LIVE.** It reads `game["pace_features"]`, a
  season-level secs/play feature for the pregame drive priors. Joining it to a
  live record as in-game tempo is a silent category error.
- **NCAAF HAS NO LIVE-STATE PRODUCER AT ALL** (no `live_game_state` analog).

**TWO SPORT RULES THAT WOULD HAVE BEEN SILENTLY WRONG:**
1. **NCAAF overtime is UNTIMED** — alternating possessions from the 25, no
   clock. Reusing NFL's timed-OT branch would invent a 15-minute period that
   does not exist and report a confident elapsed time. NCAAF OT returns
   `elapsed_minutes: None` and the record stays valid. Mutation F2 fires on it.
2. **NFL regular-season OT is 10 minutes, not 15.** Mutation F3 fires.

**MARGIN BANDS ARE IN SCORES, NOT POINTS** (<=8 / <=16 / <=24 / 25+). An
8-point football game is ONE possession; the basketball scale calls it
`moderate` and baseball's calls it a blowout. Three sports, three units — a
test asserts the same 8-point gap buckets differently in football vs basketball.

**THE EMIT (`nfl/live_game_state.py`):**
- `_state_from_event` now keeps `situation`, **on live games only** — a
  `situation` on a finished game is a feed artefact and would render "3rd and 7"
  hours after the whistle, the same class of defect as the 0-0 placeholder score
  that file already guards against. Mutation E1 fires on it.
- `attach_nfl_live_game_state` attaches `live_state["game_shape"]` behind a
  function-local import and a bare except, so a failure costs the shape block
  and nothing else. The cards board is the product.
- Tests call the REAL `attach_nfl_live_game_state`, not a stub — that file's own
  docstring warns that asserting a field is SET only proves presence.

**66 tests green** (46 shape + 20 NFL, up from 15). **10 of 10 mutations caught**
— 7 on the primitive (football quarters inheriting basketball's 10, NCAAF OT
treated as timed, NFL OT at 15, point bands reused, absent situation reading as
"not in the red zone", out-of-range situation values stored, `margin_in_scores`
flooring instead of ceiling) and **3 on the emit** (stale situation on a finished
game, shape built without the situation so the capture does nothing, shape never
attached).

**UNVERIFIED, and this is the part not to misread.** NFL is the first sport with
a live emit PATH; no production slate has run through it. **n is still 0.**
NCAAF has the contract and **no producer**, season opens 08-29, so nothing there
is verifiable today — a ready rules entry is not coverage. No deploy requested.

#### game-shape-capture — SOCCER ADDED, EMIT LANDED; ALL FIVE SPORTS NOW HAVE A CONTRACT `[2026-08-17 ~00:3xZ]`

**Soccer has the RICHEST live state of any sport here and is the ONLY one
carrying real in-game EVENTS.** Measured on a populated record
(`data/soccer_source/mls/api/live_state/live_state_2026-07-22.json`, CF Montréal
v Toronto FC): shots, shots on target, corners and red cards per side, plus
`half` / `clock_remaining` / scores. **Only 3 of 14 live_state files on disk are
populated at all** — the rest are `count: 0`.

- **Only sport where a true EVENT RATE is derivable.** `shots_per_minute` is a
  real tempo statistic, not the scoring-rate proxy basketball and football had
  to settle for. `shot_dominance` says who is actually on top — 0-0 with shots
  9-5 is not a balanced match, and the scoreline cannot say so.
- **`clock_remaining` IS REMAINING-IN-THAT-HALF, NOT IN THE MATCH**
  (`_current_half_and_clock_remaining`, `_HALF_SECONDS = 2700`). half 2 /
  1800s is the **60th minute**. Reading it as remaining-in-match inverts the
  entire progress axis; mutation S1 fires on exactly that.
- **THE REFUSAL THAT MATTERS MOST, AND IT IS UNIQUE TO SOCCER: the same
  `live_state` embeds the MODEL'S OWN `projection` and `goal_windows` blocks.**
  They are excluded from the shape. Game shape is what a model's error is scored
  AGAINST; folding the model's prediction into it makes the analysis circular —
  "is the model wrong when the model says X" cannot separate a bad model from a
  bad state. No other sport's live_state carries its projection inline, so
  nothing else in the module guards this. Mutation S2 fires on the leak.
- **KNOWN BLIND SPOT, FLAGGED NOT PAPERED OVER:** the producer clamps
  `clock_remaining` at 0 and never returns a half above 2, so second-half
  stoppage is invisible — 90' and 95' both read `match_minute == 90.0`.
  `clock_saturated` marks that case so it can be excluded. Fixing it needs the
  ingestion contract to carry the raw match clock.
- **Zero-shot dominance is `None`, not 0.5** — "nobody has shot yet" and "both
  sides equally" are different states, and collapsing them files every goalless
  opening into the balanced cell.
- **Possession and xG are NOT captured and are NOT invented.** Shots on target
  is not a substitute for either.

**Margin bands are in GOALS** (level / 1 / 2 / 3+) — a fourth distinct scale.
Buckets cap at **13** (3 phases x 4 bands): `first_half`, `second_half`,
`closing` (final 15 min). `red_card_diff` is deliberately NOT in the bucket
despite being one of the strongest state variables in the sport — it would
double the space, and it stays on the record as the obvious first re-cut.

**EMIT LANDED.** `soccer/ingestion/espn_live_state.py` was UNCLAIMED (checked
immediately before the edit). `build_live_state` now binds its dict and attaches
`state["game_shape"]` **before** any projection is merged in by the caller —
the ordering is pinned by a test.

**90 tests green** across `test_game_shape` (57), `test_nfl_live_game_state`
(20), `test_soccer_espn_live_state` (10), `test_poll_soccer_live_state` (3).
**8 of 8 soccer mutations caught** — 6 on the primitive (remaining-in-match
clock, model-output leak, 0.5 dominance default, unflagged saturation, widened
closing window, `half > 2` accepted) and 2 on the emit (shape never attached,
shape built from a synthetic dict rather than the real state).

**STATUS ACROSS THE LANE:** MLB and WNBA primitives on main with emits BLOCKED
by `Layer 1 board coverage audit (fork 2)`; **NFL and soccer emits LANDED**;
NCAAF has a contract and **no producer at all**. **n = 0 everywhere — not one
production slate has run through any of it.**

#### game-shape-capture — CHECKPOINT 2026-08-16 ~19:0x CDT — **ALL WORK ON `origin/main`; LANE STAYS OPEN ON VERIFICATION**

`origin/main` `8a01fa3d`; ref `lane/game-shape-capture` -> same. Five commits,
all verified reachable: `597f4a80` `862aac3a` `2dd384b0` `5cb588f2` `8a01fa3d`.
**90 tests, 31 of 31 mutations caught.** `#454` filed.

**WHY THIS LANE IS NOT CLOSED, stated so nobody closes it on the commit count:**
its verification is *one live slate with a non-zero bucket distribution read
across two builds*, and **that has not run. n = 0 for every sport.** Two emits
exist (NFL, soccer); neither is deployed and neither has seen a production game.

**NEXT ACTIONS, in order:**
1. Read `game_shape` off a live NFL preseason or soccer fixture — the only step
   that turns any of this from prepared into measured.
2. MLB + WNBA emits: two handoffs to `Layer 1 board coverage audit (fork 2)`
   are **unanswered**. If declined, wait for the lanes to close; do not edit
   across them.
3. NCAAF needs a live-state PRODUCER built (no `live_game_state` analog exists).
   Season opens **08-29** — this is the only dated item in the lane.
4. Owed consolidation: `wnba/cards.py:891` should delegate to
   `basketball_elapsed_minutes`; blocked on that file's holder.
- **branch-overlap-baseline-instrumentation** — archived 2026-08-17. CLOSED 2026-08-16 — the baseline was sampling hours where the failure does not happen — session: `branch-overlap-baseline-watch` (scheduled-task run)
- **branch-overlap-manual-run-marker** — archived 2026-08-17. CLOSED — opened 2026-08-16 — session: `branch-overlap-baseline-watch` — verified in production 2026-08-16T19:52:23+00:00
- **clamp-fix-to-workers** — archived 2026-08-17. CLOSED-VERIFIED 2026-08-17 00:0xZ — the ±4900 clamp is gone from all three live services, and 7,002 served fair_price values carry none**
- **closing-stamp-is-detection-time** — archived 2026-08-17. CLOSED-VERIFIED — **OUTPUT MEASURED 2026-08-15 22:06 CDT / 2026-08-16 03:06Z. 21/21 new-code stamps precede first pitch; 33/36 pre-fix stamps post-dat
- **commit-guard-reads-wrong-index** — archived 2026-08-17. CLOSED 2026-08-16 — the guard read the MAIN worktree's index while the commit used another one — session: `live-gameline-eval`
- **mlb-mobile-live-residual** — archived 2026-08-17. CLOSED 2026-08-16 — HYPOTHESIS FALSIFIED; it is a false alarm, the Live fit is convex and `fitRatio` cannot see curvature — opened 2026-08-16 — sessio
- **ncaaf-schedule-fallback** — archived 2026-08-17. **CLOSED-VERIFIED 2026-08-16 — `#445` fixed in `483bb9dd`, on `origin/main`. NOT DEPLOYED (NCAAF opens 08-29)** — opened 2026-08-16 (retroactively, se
- **nfl-pbp-fetcher** — archived 2026-08-17. **CLOSED-VERIFIED 2026-08-16 18:31:15Z — pbp_2025.csv written on the mounted disk (97,951,481 bytes, 46,452 REG plays) and the guard stopped refusing.
- **nfl-pbp-root-resolution** — archived 2026-08-17. **CLOSED 2026-08-16 — resolution mechanism PROVEN CORRECT and the hypothesis FALSIFIED in the same reading. `#441` root cause settled as an ingestion 
- **render-events-reader** — archived 2026-08-17. CLOSED-VERIFIED 2026-08-16 — **`scripts/render_events.py` + `tests/test_render_events.py` SHIPPED TO THE TREE (no deploy — this is local tooling). Fal
- **soccer-live-game-state** — archived 2026-08-17. CLOSED-VERIFIED 2026-08-16 18:56Z — a kicked-off match is no longer `pregame`, and no finished match carries an edge
- **spread-line-sign-convention** — archived 2026-08-17. CLOSED-VERIFIED 2026-08-16 — **ARTIFACT OUTPUT NOW MEASURED: 12 of 12 MLB spreads rows correct on the served shortlist (9 away + 3 home, the previousl
- **ui-probe-baseline-nfl-ncaaf** — archived 2026-08-17. CLOSED 2026-08-16 — armed for nfl/ncaaf only; mlb stays watch-only — opened 2026-08-16 — session: ui-probe-rerun-compare
- **ui-probe-curvature-detection** — archived 2026-08-17. CLOSED 2026-08-16 — `curved` forces `reliable:false`; Preview (the falsification case) is not flagged — opened 2026-08-16 — session: ui-probe-rerun-co
- **ui-probe-desktop-height-model** — archived 2026-08-17. CLOSED 2026-08-16 — desktop is UNFITTABLE, not mis-tuned; measured the floor instead of tuning the threshold — opened 2026-08-16 — session: ui-probe-r
- **ui-probe-peer-deviation-gate** — archived 2026-08-17. CLOSED 2026-08-16 — one model-free height rule; production green, coverage gap printed — opened 2026-08-16 — session: ui-probe-rerun-compare
- **ui-probe-peer-min-group** — archived 2026-08-17. CLOSED 2026-08-16 — verdicts need n>=3; thin groups reported, never dropped — opened 2026-08-16 — session: ui-probe-rerun-compare
- **ui-probe-proportional-budget** — archived 2026-08-17. CLOSED 2026-08-16 — shipped; falsification test FIRED (proportional does not tighten the spread) but it fixes the width bias — opened 2026-08-16 — ses
- **ui-probe-settle-plateau** — archived 2026-08-17. CLOSED 2026-08-16 — the settle now needs 2400ms of stillness, and a verdict resting on absence says so — opened 2026-08-16 — session: ui-probe-rerun-c
- **ui-probe-tab-click-race** — archived 2026-08-17. CLOSED 2026-08-16 — cause UNPROVEN and not reproduced; the blindness that made it undiagnosable is fixed — opened 2026-08-16 — session: ui-probe-rerun
- **ui-probe-tie-floor-tracking** — archived 2026-08-17. CLOSED 2026-08-16 — floor collected on every row; 5 of 6 stable, mlb mobile fires the rule at 2.06x — opened 2026-08-16 — session: ui-probe-rerun-comp
- **ui-probe-tie-statistic** — archived 2026-08-17. CLOSED 2026-08-16 — implemented as decided; the statistic did NOT help and the instability is the SLATE — opened 2026-08-16 — session: ui-probe-rerun-
- **ui-probe-tracked-statistic-revert** — archived 2026-08-17. CLOSED 2026-08-16 — reverted to worstGroupPx; exposed and fixed two false alarms that were failing a healthy board — opened+closed 2026-08-16 — sessio

#### game-shape-capture — SCOPE ADDED 2026-08-16 ~19:5x CDT — WNBA pbp possessions (`#454` first step)

Files added to this lane: `scripts/wnba_pbp_possessions.py` (new),
`tests/test_wnba_pbp_possessions.py` (new). Both unclaimed; `scripts/` carries
no lane claim.

**THE ANSWER TO "TAKE WNBA PBP FOR MODELLING" IS: THE DATA IS REAL AND THE
SAMPLE IS NOT.** Possessions genuinely exist — `pbp_possessions.poss_est`,
computed as `FGA + TOV + 0.44*FTA - OREB`
(`vendor/wnba_betting_repo/app.py:3572`) — and the values are sound. But on the
tracked mirror:

| stage | count |
|---|---|
| files scanned | 53 |
| game records | 120 |
| with possession data | **17** |
| placeholder ids excluded (`0000000001`…) | 8 |
| **partial / mid-game excluded** | 5 |
| **USABLE GAMES** | **4** |
| dates with possessions | 2 (`''` and `2026-06-27`) |

The four survivors read 73.02 / 74.96 / 78.02 / 85.30 possessions per team —
plausible WNBA figures, which is the sanity check that the underlying
`poss_est` is sound. **No aggregate is emitted: `--min-games` defaults to 10 and
the tool refuses at n=4, naming the shortfall.** Fitting anything on this would
be `#377` committed by the tool written to prevent it. **The mirror is lossy —
production coverage is UNKNOWN and unreadable from here (no `ADMIN_TOKEN`, and
`/api/ops/artifacts/export` reads WEB's disk).**

**TWO DEFECTS IN MY OWN FIRST VERSION, both found by running it rather than by
review:**
1. **Partial snapshots counted as games.** A `pace_per_team` of **2.5**
   (CHI@DAL, one quarter) and **27.18** (CON@TOR, halftime) sat next to real
   ~75-possession games. These are LIVE snapshots; most are mid-game. Fixed by
   `quarters_complete()` (all four `q_totals` non-null).
2. **Repeated snapshots of the same game counted twice.** SEA@TOR and CON@TOR
   each appeared twice with byte-identical totals. Fixed by a dedupe keyed on
   `(game_id, teams)` keeping the highest total.
The docstring had CLAIMED a `partial` flag the code never implemented — a
comment that overstated the code, caught by reading the output.

**A VACUOUS TEST, CAUGHT BY MUTATION AND FIXED.** `test_team_possessions_ignores
_the_zero_valued_home_and_away_keys` passed with the key filter REMOVED, because
the `poss_est <= 0` filter already drops those keys on real data. It pinned the
zero filter, not the key filter, so the key filter could have been deleted
silently. Added
`test_the_key_filter_is_load_bearing_independently_of_the_zero_filter`, which
puts NON-zero values under `home`/`away` — the double-counting case. Mutation P1
now fires.

**15 tests, 6 of 6 mutations caught** (home/away key filter, completeness needing
all four quarters, placeholder ids accepted, aggregate emitted below the floor,
a refusal smuggling a mean out with it, duplicates not collapsed).

**`game_shape.py` COMMENT AMENDED, not the flag.** `possession_pace_available:
False` is correct for the card payload that function reads; the comment now says
so precisely and points at the `live_pbp_stats` family where possessions DO
live, with the coverage caveat and the tricode-vs-home/away trap attached.


### wnba-live-tier — OPEN — **GAME LINES SHIPPED AND VERIFIED (218/321 rows live_aware). PROPS NOT WIRED — the source emits nothing. Tick-over-tick movement UNPROVEN.** — opened 2026-08-16 — session: layer1-board-coverage
> **[SWEEP 2026-08-17 12:1x CDT] OWNER LIVE VIA FORK.** The lane's last claim
> file belongs to an ARCHIVED fork, but `layer1-board-coverage` fork 6 is
> running, so this lane is recoverable in-session rather than orphaned.
> **SINGLE NEXT ACTION:** fix the identity key — `/api/board/game-chips` keeps
> only the game with a SYNTHESIZED key (`POR@PHX`) and drops both games with
> numeric ESPN gamePks, which is why 207 of 300 grid rows had no game block to
> join against. Two further defects behind it: the surviving chip is stale
> (`state=pregame` while the lens has it live), and the WNBA grid never reports
> `final`. Props still not wired.
- Goal: WNBA live games carry a live tier on the Layer 1 board, GAME LINES and
  PROPS. Baseline was **0 of 521 rows** across 2 live games.
- Files: `syndicate/features/shared/board_enrichment.py`,
  `tests/test_wnba_live_tier.py`,
  `tests/test_wnba_scoreboard_carry_forward.py`.
  - **NOT claimed by this lane any more:** `syndicate/features/wnba/cards.py` is
    now held by `game-shape-capture` under a claim override taken 2026-08-16
    ~20:1x CDT **on explicit user instruction**, for ONE function only
    (`build_live_pbp_stats_payload`, `:6390`), to fix `#455`. Logged rather than
    silent, so it can be judged:
    1. **The user directed it** — "take the override and fix it - i dont think
       its actually being worked on by any other lane." That is the authority
       here; the reasoning below is corroboration, not the basis.
    2. **Coordination was attempted three times and never reached a reader.**
       fork 2 (`local_c83b3d44`) archived before replying to two handoffs; a
       third was sent to fork 4 (`local_0cec671d`, running) and is unanswered.
    3. **Zero functional overlap with this lane's own work**, which is the live
       TIER on the Layer 1 board (`attach_live_gamelines_for_sport`,
       `LIVE_LENS_SOURCES_BY_SPORT`). `build_live_pbp_stats_payload` is the pbp
       stats endpoint and is untouched by it.
    4. **It plausibly FIXES this lane's own blocker** — its status reads "PROPS
       NOT WIRED — the source emits nothing", and `#455` is a stuck all-null
       skeleton, which is exactly what a prop consumer reads as nothing.
    **If this lane wants the file back, this note is the record.**
- **DONE — game lines.** `attach_live_gamelines_for_sport` was gated
  `if sport != "mlb"` on a docstring claim that WNBA "has no live tier at all",
  which had gone stale: the live-lens loop already ran for wnba on a 60s tick,
  writing the exact path the join reads. Shipped `fdc72dd0` (refresh-worker) via
  a per-sport `LIVE_LENS_SOURCES_BY_SPORT` (wnba stamps `live_projection`, not
  `live_mc`) plus a top-level team-name fallback (wnba has no `matchup`
  wrapper). **Verified twice on production live slates: 149 rows, then 218 of
  321.** No `simsRun` is published by wnba, so the edge is withheld by
  `REASON_UNUSABLE_SIMS` — an n was NOT invented to open the gate.
- **DONE — the live_state dropout.** `_public_scoreboard_live_state_payload` was
  `except Exception: return None`, publishing a 6s ESPN timeout as "no games in
  progress". Age-bounded MARKED carry-forward shipped `16a898ef`
  (live-odds-worker). **Its trigger has NOT fired in production yet** — unit
  verified only.
- **NOT DONE — props.** Across the entire wnba snapshot, `actual` /
  `live_projection` / `live_total` / `live_total_line` appear 24 times each and
  are **NULL in all 24**. Wiring the prop join would be inert. Producer gap in
  `wnba/live_lens.py` and its box-score source.
- **NOT DONE — tick-over-tick movement.** The stated verification wanted a diff
  proving the numbers MOVE. The second tick had no live rows to compare, so it
  is **unproven, not passed**. Needs another live WNBA slate.
- Verification: game-line half MET (two independent live slates). Props half and
  movement UNMET. Lane stays OPEN for those.
- Blocked by: none.

#### game-shape-capture — WNBA pbp CAPTURE BUILT; THE SOURCE IS SERVING A FROZEN SKELETON (`#455`) `[2026-08-16 ~19:3x CDT]`

**The user corrected me and the correction found a production defect.** I had
reported "no WNBA pbp corpus exists on Render" and, when asked "did you check
render disk", had to answer no — I inferred unreachability from
`HOT_ARTIFACT_PATTERNS` without checking whether the data was there.

**Two of my own claims were wrong:**
1. "Production has been accumulating all season" — **false**. The endpoint
   returns 0 games for 2026-06-27 and 2026-07-15; it serves live only.
2. "The allowlist is the root cause" — **not the binding constraint**. Adding
   the pattern would export an empty set. I had proposed a fix that would have
   cost a web deploy and changed nothing.

**What the checkout files actually are:** cached API responses. The
`payload`/`ttl`/`ok`/`generated_at` wrapper is an HTTP cache envelope, not a
data record — which explains all three anomalies at once (17 records on 2 dates,
test fixtures `0000000001` mixed in, mid-game partials beside completed games).

**THEN THE USER SAID: 2 of today's 3 games are FINAL and one is LIVE.** The
endpoint returned all-null for all three. Reproduced and filed as **`#455`**:
`build_live_pbp_stats_payload` (`wnba/cards.py:6390`) never computes pbp — it
replays a stored snapshot and otherwise emits a hardcoded all-null skeleton,
**and a skeleton has a non-empty `games` list, so once persisted it is served in
preference to real data all day** (`:6401`). `generated_at` read
**16:14:21 CDT, frozen ~3 hours** on a `ttl=1` re-fetch.

**BUILT:** `scripts/capture_wnba_pbp.py` + `tests/test_capture_wnba_pbp.py`.
Its defining rule is a REFUSAL: it never stores a skeleton, counts them
separately, and **exits 2** when every record is one, so "captured nothing"
cannot read as "nothing happened". Storing what the endpoint returns would have
industrialised the defect — a corpus of confident nulls with a fake denominator.
`--probe` reports without writing.

**12 tests, 5 of 5 mutations caught** (skeleton counted as signal, zero-valued
home/away counted as signal, storing with no signal, probe mode writing,
possessions-only detection dropping early live ticks).

**Deliberately NOT done:** no second implementation of the `poss_est` formula.
Inventing one is how two numbers that should agree start disagreeing.

#### PHASE 1C — **VERIFIED IN PRODUCTION 2026-08-17 00:11:36Z.** Lane goal met.
- The lane's pre-registered outcome, met exactly: `FIXTURE_CADENCE sport=soccer
  league=mls due:imminent_handoff_to_t_window:1107s` against `championship` /
  `la_liga` / `primeira_liga` all `skip:mid:18-19h_out`, plus `scope=league
  due=mls of=4` and a live process carrying `--soccer-leagues mls`.
- Shipped as part of a three-service CONVERGENCE (live-odds-worker `c348da53`,
  web `763a2f66`, refresh-worker `7c2b1a17`), each a real merge on its own live
  SHA. 303 tests passed pre-deploy; 0 tracebacks post-deploy.
- **Falsification test did NOT fire:** per-league resolution did reach distinct
  tiers, so league granularity WAS the missing term.
- **Still open in this lane's neighbourhood, NOT done:** soccer live sims. A live
  MLS match serves 321 rows / 5 projections / 0 live_aware. `#440`'s Phase 3 has
  no soccer item at all. That is a plan defect, recorded in `state.md`.
- **Found while deploying, unrelated to this lane:** `#449` refresh-worker OOM
  loop (23 kills / 8 hours). `#447` red layer2 wiring tests. `#448` unattended
  scheduled tasks wedging deploy claims.

#### game-shape-capture — `#456` NBA DATE-SCOPE FIX BUILT; `#455` WNBA BLOCKED BY A CLAIM `[2026-08-16 ~19:5x CDT]`

**NBA does NOT share `#455`.** Checked component by component rather than assumed: NBA **never persists** (zero write calls in `nba/live_lens.py`), so WNBA's sticky-skeleton mechanism cannot occur. Both sports DO emit the identical all-null `ok: True` skeleton, so the instrument-blindness half is shared.

**NBA has its own defect, confirmed in production**: one undated snapshot path served for every requested date (`2025-12-25` -> payload date `2026-06-13`). Filed as **`#456`**, fix built and tested, **NOT DEPLOYED**. The refusal fires on the real endpoint path — `nba.py:_allow_stored_date_fallback()` returns `False`, verified BEFORE writing the fix rather than after.

**A PRE-EXISTING FAILURE, NOT MINE:** `test_nba_refresh_runner.py::test_main_materializes_core_artifacts_into_bundle_root` fails identically with my change reverted to `origin/main`'s version. Attributed by measurement, not assumed.

**`#455` (WNBA) CANNOT BE FIXED BY THIS LANE.** `syndicate/features/wnba/cards.py` is claimed by **`wnba-live-tier` (OPEN)** — re-checked immediately before the edit; no edit was made. Handed to that session. **Worth their attention: their own lane status reads "PROPS NOT WIRED — the source emits nothing." That may BE `#455`** — the skeleton is exactly what a prop consumer would see as "the source emits nothing."

#### refresh-worker-oom-recurrence — CALLER-SIDE TRACE `[2026-08-17 ~00:3xZ]` — **the allocator's SPAN is now named, and BOTH designed brakes on it are measurably inert**
- **Verdict reproduced twice** (`deploys.md`): `last_stage=board_contract_end` on
  the 00:19:48Z kill (`94447830`, anon 1209->3998MB/~25s) and the 00:32:32Z kill
  (`7c2b1a17`, anon 1354->3751MB/~16s). Different commits; the second had no
  concurrent deploy in its window. `apply_game_board_contract` is exonerated.
- **The span, from the loop structure** (`intelligence.py:2793-2835`): between
  `OVERVIEW_SPORT_BEGIN` (a bare `print`, so it CANNOT set `last_stage` — which
  is why the climb looked unmarked) and the `overview_sport_end` stage marker,
  there are exactly two calls: **`_build_sport_overview`** (`home.py:6733`) and
  **`_emit(sport_row)`**. For non-MLB sports the board contract is the LAST
  statement of the cards builder (`nfl/cards.py:505` is
  `return apply_game_board_contract(...)`), so `board_contract_end` is the last
  marker before the stack unwinds — the allocator is ABOVE it, in that span.
- **MEASURED IN PRODUCTION, window 00:24:01Z (7c2b1a17 live) -> 00:35:50Z,
  containing the 00:32:32Z kill:**

      OVERVIEW_SPORT_BEGIN            30   incl. a FULL 8-sport pass at 00:33:38-40
                                           with force_refresh=True skip_game_hydration=False
      OVERVIEW_SPORT_END              30
      OVERVIEW_REBUILD_RATE_LIMITED    0   <-- #251's throttle on hydrated rebuilds
      OVERVIEW_STOPPED_FOR_MEMORY      0   <-- #250's memory circuit breaker

  **The expensive path runs all 8 sports hydrated under `force_refresh=True`,
  and neither guard built to bound it engages — across a window containing an
  OOM kill that reached headroom 0.0.**
- **This REPRODUCES `#336` on current code.** That entry recorded
  `OVERVIEW_REBUILD_RATE_LIMITED` firing ZERO times over 29 minutes and 11 passes
  and left the reason unresolved. It is still zero. The defect is open, not
  historical.
- **The retention mechanism `home.py:6766-6782` describes is the standing
  hypothesis, NOT yet confirmed by me:** `_HOME_OVERVIEW_TTL_SEC` is 10s against
  a ~90s board loop, so the cache "structurally cannot hit" while still RETAINING
  the previous hydrated row — the process holds the old context and builds a new
  one on top. That comment's own 2026-08-07 numbers are `+2.9GB in 73s`. Tonight's
  shape is +2.4GB in 16s and +2.8GB in 25s: same magnitude, much faster.
- **NOT CLAIMED, and the next person must not read it as claimed:** I have not
  shown WHICH of the two calls allocates, and I have not established why either
  guard is silent. Two candidate reasons for the memory guard, untested:
  (a) it is checked BETWEEN sports, so an excursion INSIDE one sport is invisible
  to it by construction — `#250`'s own comment says this; (b)
  `_overview_headroom_exhausted` (`intelligence.py:2635-2661`) returns **False**
  when the snapshot is `None` or lacks `sufficient`, i.e. **unknown maps onto the
  permissive branch and emits no reason** — the failure shape
  `feedback_unknown_must_not_default_permissive` describes.
- **NEXT, in order:** (1) determine why `OVERVIEW_STOPPED_FOR_MEMORY` is silent —
  (a) vs (b) above is decidable by reading one snapshot at a check point;
  (2) instrument the `_build_sport_overview` / `_emit` boundary the way
  `board_contract_end` instrumented the builder's return, since that split is now
  the whole remaining question; (3) only then touch the floors.

#### refresh-worker-oom-recurrence — WHY THE MEMORY GUARD IS SILENT: SETTLED BY MEASUREMENT `[2026-08-17 ~00:4xZ]`
- **Answer: (a). The guard is checked BETWEEN sports; the excursion happens
  INSIDE one. It is passing a check it should pass.** Not a bug in the guard,
  not a stale constant, and NOT the permissive-default hypothesis I had ranked
  first — that one is FALSIFIED below.
- **Measured at a real check point**, the hydrated 8-sport pass at 00:33:38-41
  (`force_refresh=True skip_game_hydration=False`):

      00:33:41  unreclaimable  754.4MB  ->  effective_headroom = 4096 - 754.4 = 3341.6MB
      00:33:43  unreclaimable  769.9MB  ->  effective_headroom = 4096 - 769.9 = 3326.1MB

  Against the STREAMED floor (1500MB) that passes with >2× margin, and it passes
  the EXPENSIVE floor (3000MB) too. `sufficient = effective_headroom >= floor`
  (`memory_observability.py:342`) is simply TRUE. There is nothing for
  `OVERVIEW_STOPPED_FOR_MEMORY` to report.
- **FALSIFIED — my own ranked-first hypothesis (b).** I proposed that
  `_overview_headroom_exhausted` was mapping unknown onto its permissive branch
  (`snapshot is None or snapshot.get("sufficient", True)`), the
  `feedback_unknown_must_not_default_permissive` shape. It is not:
  `memory_headroom_snapshot` returns None only when the cgroup reads fail, and
  they are demonstrably working — the same payloads carry real
  `unreclaimable_mb`. `OVERVIEW_MEMORY_CHECK_FAILED` also fired **0** times, so
  the guard is not throwing either. The code is capable of that failure; tonight
  it is not exhibiting it. Recorded so nobody re-opens it on the strength of the
  code read alone.
- **ALSO FALSIFIED — "the relaxed 1500MB floor is undersized."** I expected the
  arithmetic to show a floor smaller than the excursion. At 3341MB headroom the
  floor was never the binding constraint at check time. **Raising the floors
  would not have prevented either kill tonight** — a change I had listed as a
  next step and would have shipped on a wrong model.
- **The real mechanism, and it is already written down for a DIFFERENT breaker.**
  `intelligence.py:2530-2542` says of the caller's circuit breaker: "a process
  that crosses the container limit ninety seconds into sport 7 of 8 is never
  asked whether it should continue." **The per-sport breaker added to fix that
  has the identical defect one level down** — it samples between sports, and the
  +2.4GB/16s and +2.8GB/25s excursions occur *within* a single sport's
  `_build_sport_overview`. Survival is therefore decided by the baseline
  unreclaimable at the moment the excursion starts (754MB at 00:33 -> would
  survive; 1601MB earlier tonight -> 2494MB headroom vs a +2.8GB excursion ->
  dies), which is a race no between-sport check can arbitrate.
- **The gap stated plainly: an OBSERVER exists, an ACTOR does not.** The
  `MEMORY_WATCHDOG` thread already samples on a clock and saw every one of these
  excursions in real time, at 2s resolution, climbing 100-260 MB/s. It reports
  and does nothing. Every guard that can ACT is on a stage boundary, and the
  allocation does not cross one. `memory_observability.py:758-761` predicted
  exactly this: "multi-GB allocations INSIDE one stage... Adding more boundary
  markers cannot fix that; only sampling on a clock can."
- **NEXT — do NOT touch the floors.** The question is no longer "what threshold"
  but "who can abort mid-stage". Options, unranked and uncosted: give the
  watchdog thread an abort/flag the hydration loop polls; or make
  `_build_sport_overview` itself checkpoint mid-build. Both are real changes to a
  4GB worker on a `learnings.md` "worker periodic work is never free" footing,
  and neither should ship on tonight's evidence without a written design.

#### refresh-worker-oom-recurrence — WATCHDOG ABORT DESIGN WRITTEN `[2026-08-17 ~00:5xZ]`
- `.syndicate/design_2026-08-17_watchdog_abort.md`. **DESIGN ONLY — nothing
  built, nothing deployed.**
- Shape: the watchdog thread raises a flag (one integer comparison on a number it
  already has), the hydration loop polls it at existing stage markers, an
  `OverviewAbort` degrades the pass. No thread-killing, no async exception
  injection — this process writes artifacts continuously and corrupting a
  mid-write is a worse outcome than the OOM.
- **BLOCKED ON TWO MEASUREMENTS, deliberately. Do not build first.**
  - **M1 — marker density during an excursion.** Decides whether polling at
    existing call sites is sufficient (cheap) or the poll must go inside the
    hydration call tree (invasive, and it invalidates the cost argument).
    Evidence is currently MIXED: excursion 1 had a full `nfl` triplet mid-climb;
    excursion 2 read `board_contract_end` for 16s, which cannot distinguish "no
    markers" from "same marker re-firing". Building on excursion 1 alone would
    ship a guard silent in exactly the excursions that have no markers.
  - **M2 — distribution of effective headroom at excursion START, n>=5.** The
    abort floor must sit above the worst starting headroom that still died and
    below routine operating headroom (~3300MB measured). **The floor value is
    left UNSET in the design on purpose** — the existing 1500/3000 constants
    answer a different question ("can the NEXT sport start", not "must the
    CURRENT sport stop"), and picking a number by intuition is how those became
    stale.
- Hard constraints written into the design: never fire on
  `skip_game_hydration=True` (that path feeds `_source_state_fingerprint`, and
  `intelligence.py:2790` calls a truncated sport list "a worse failure than the
  one being prevented"); never write a partial overview to the cache; inert where
  cgroups are unreadable (unknown -> do NOT abort, the opposite polarity to the
  usual rule and justified in place); gate on headroom, NOT on `climb_mb_per_s`.
- Verification plan includes the only criterion that counts: **a window with an
  excursion, an abort logged, and NO `oomKilled` event.**
- **Stated in the design and repeated here: this is CONTAINMENT, not a fix.** It
  turns a process kill into a degraded board. The +2.4-2.8GB allocation is
  untouched and still unattributed.

#### refresh-worker-oom-recurrence — M1 + M2 RUN. **M1 kills the cheap design; M2 OVERTURNS my "floors are irrelevant" claim** `[2026-08-17 ~00:5xZ]`
- **M1 — stage-marker density during an excursion: ZERO.** Four consecutive
  sub-windows over the 00:31:46-00:32:02 climb, each returning **under** the
  100-row cap, so coverage is COMPLETE and the zero is admissible (not the
  `learnings.md:2917` truncation trap):

      00:31:46-50  rows= 2 COMPLETE  stage_markers=0  watchdog=2
      00:31:50-54  rows= 3 COMPLETE  stage_markers=0  watchdog=2
      00:31:54-58  rows=10 COMPLETE  stage_markers=0  watchdog=2
      00:31:58-02  rows=26 COMPLETE  stage_markers=0  watchdog=2

  **The design's option (b) — poll the abort flag at existing stage markers — is
  DEAD.** There is nothing to poll for 16 seconds. Excursion 1's mid-climb `nfl`
  triplet was the exception, not the rule, and building on it would have shipped
  a guard that never fires in the excursions that matter. The M1 gate was the
  correct call. The watchdog's own 2s clock is the ONLY thing sampling in there.
- **M2 — effective headroom at excursion START, n=7 distinct excursions:**

      23:15:38  EFF 2231.0MB   +2078MB      00:08:26  EFF 2502.0MB   +2274MB
      23:30:06  EFF 2684.6MB   +2519MB      00:18:32  EFF 2952.7MB   +2860MB
      23:42:45  EFF 2636.0MB   +2331MB      00:31:46  EFF 2737.3MB   +2397MB
      23:54:45  EFF 2648.4MB   +2567MB

  Range **2231-2953MB**, every one fatal. Excursion magnitude **+2078 to
  +2860MB**. Routine operating headroom measured at a non-excursion check point:
  **~3330MB**.
- **THEREFORE THE VIABLE FLOOR BAND IS 2953-3330MB — and the EXISTING EXPENSIVE
  FLOOR (3000MB) SITS INSIDE IT.** At the check immediately preceding each fatal
  sport, headroom was 2231-2953MB: **below 3000 in all 7 cases, above 1500 in all
  7 cases.** The guard is silent because the seven non-MLB sports are routed to
  the relaxed 1500MB floor. Routing them to the expensive floor would have fired
  before every excursion tonight.
- **CORRECTION — I GOT THIS WRONG EARLIER AND IT WOULD HAVE MISDIRECTED THE
  WORK.** I wrote "raising the floors would not have prevented either kill" and
  "the floor is measurably the wrong lever". That rested on ONE check-point
  sample (3341.6MB at 00:33:41) which was **not** a check preceding an
  excursion — it was a quiet moment with unreclaimable at 754MB. n=1, and the
  wrong 1. With n=7 taken at the points that actually matter, the floor is not
  merely relevant, it is the **cheapest sufficient lever**, and the constant
  already in the code is very nearly the right value.
- **This also closes the loop on the instrument-blindness finding.** The seven
  sports were routed to the relaxed floor because they measured "+1.7MB for five
  sports" — taken with `_log_cards_context_memory`, which exists ONLY for MLB.
  A sport with no instrument read cheap, got the cheap floor, and is now
  demonstrably capable of a +2.8GB excursion.
- **REVISED RECOMMENDATION, replacing the watchdog abort as the first move:**
  the one-line routing change in `_overview_headroom_floor_bytes`
  (`intelligence.py:2627`) — stop treating the seven as cheap — is smaller,
  needs no new mechanism, is testable offline, and is supported by n=7. The
  watchdog abort (`design_2026-08-17_watchdog_abort.md`) remains the right
  CONTAINMENT for excursions that start below any floor, but it is no longer the
  first thing to build, and M1 has made its cheap variant unbuildable.
- **NOT CLAIMED:** that the routing change is free. It will refuse hydration more
  often and the board will be thinner; `intelligence.py:2601` already records
  that a 3000MB floor "refuses the SEVEN CHEAP SPORTS" and read `sports=1` where
  every prior build read `sports=8`. That is the real trade and it needs a
  decision, not a patch.

### wnba-live-tier — CHECKPOINT 2026-08-17 01:1xZ — status unchanged, recorded for the next session
- Game lines DONE and verified twice (149 then **218 of 321** rows live_aware).
- Live_state carry-forward SHIPPED (`16a898ef`) and **its trigger has never
  fired** — 0 log matches since 23:38Z. Unit-verified only.
- Props NOT wired and wiring them would be INERT: all 24 live prop fields are
  NULL at the source. Producer gap in `wnba/live_lens.py`.
- Tick-over-tick movement UNPROVEN — second tick had no live rows.
- **Next action:** re-read on the next live WNBA slate (~21:00Z) for both the
  movement diff and the carry-forward trigger.

#### game-shape-capture — MLB RUN EXPECTANCY BUILT FROM `feed_live` (`#454` first step) `[2026-08-16 ~21:0x CDT]`

`scripts/mlb_run_expectancy.py` + `tests/test_mlb_run_expectancy.py`. Both new, `scripts/` unclaimed.

**THE TABLE EXISTS.** 723 files -> 714 games -> **47 distinct dates** (2026-05-28 .. 2026-07-14) -> 12,423 half-innings (62 incomplete excluded) -> **53,049 plate appearances**. All 24 base-out cells populated; 23 clear an n>=100 floor (`1-3|0` is thin at n=90 and is reported, not compared).

**THE JOIN IS TRUSTWORTHY ON THE CHECKS THAT DO NOT DEPEND ON A REFERENCE:**
- **0 score cross-check mismatches** across 12,361 complete half-innings — runs counted from `movement.end == "score"` agree with the `result` score delta everywhere.
- **Monotonic in outs in all 8 base states.**
- 21 of 23 comparable cells sit within 3 SE of a single global scale factor.

**A REAL BUG, CAUGHT BY A TEST RATHER THAN BY REVIEW.** A runner advancing twice on one play gets two entries, and `start` advances between them while `originBase` does not. My first version deduplicated to the LAST entry and read its `start` — which vacates a base the runner never occupied when the play began and leaves a **phantom runner** on the original base for the rest of the half-inning, inflating exactly the occupied-base cells. Fixing it moved real counts: **`--3|0` n 107 -> 229, `1-3|0` 217 -> 90.** Not cosmetic.

**A MODELLING ERROR OF MINE, worth keeping.** The first comparison fitted an **additive** offset and reported a post-offset scatter of 0.53 runs, which reads as a broken join. The residuals gave it away — strongly negative on low-RE cells, positive on high-RE ones: the signature of a scale factor, not a shift. Under the correct multiplicative fit the same data lands 21/23 inside 3 SE. **A residual that correlates with the fitted value means the model is wrong, not the data.**

**RESULT: k = 1.1459 (+14.6% run environment vs the published era).** Two cells disagree by >3 SE (`-2-|0` +3.4, `--3|0` +3.6) — both among the rarest states.

**ATTRIBUTION OF THOSE TWO IS OPEN, AND THE VERDICT SAYS SO.** The reference table is **RECALLED FROM MEMORY, NOT SOURCED**. A per-cell disagreement is at least as likely to be an error in my reference as in the data, and the outliers are precisely the cells where a recalled number is least reliable and the sample thinnest. **Source the reference before calling either one a data defect.**

**16 tests.** What this unblocks: `game_shape.py`'s leverage-index refusal needs a win-expectancy table; this is its run-expectancy half. The other half needs score differential and inning and is not built.

#### game-shape-capture — MLB WIN EXPECTANCY BUILT BY COMPOSITION (`#454` second half) `[2026-08-16 ~21:2x CDT]`

`scripts/mlb_win_expectancy.py` + `tests/test_mlb_win_expectancy.py`.

**THE EMPIRICAL TABLE IS IMPOSSIBLE FROM THIS SAMPLE, AND THAT IS MEASURED.** Counting win rates per (inning, half, base-out, score band) over the 47 dates gives **4,039 occupied cells, median 4 observations per cell, 68.7% below 10, and ZERO cells at 1,000+**. Publishing that would be `#377` committed by the script written to enable measurement.

**SO IT COMPOSES.** The estimable quantity is P(k runs in the rest of the half-inning) per base-out state — **~2,200 observations per state instead of 4**. WE is assembled from those by convolution rather than counted:
`P(win) = P(home remaining > away remaining) + P(tie) x P(home wins in extras)`.

**SANITY CHECKS LAND ON PUBLISHED VALUES:**

| state | this table | published |
|---|---|---|
| tied, bottom 9, bases empty | **0.641** | ~0.63-0.65 |
| home up 3, top 9, 2 out | **0.993** | ~0.99 |
| home down 3, bottom 9, 2 out | **0.009** | ~0.01 |
| home down 1, bottom 9, runner on 3rd, 1 out | **0.446** | ~0.45-0.50 |

**A THRESHOLD I SET TOO LOOSE, AND FIXED.** The extra-innings constant was estimated from **43 games** (18 home wins = 0.419, SE 0.076) on a floor of 30. That is within ~1.3 SE of the truth but it moved every tied state by several points — bottom-9-tied read 0.583 instead of 0.641. Floor raised to 200; it now defaults to 0.500 and REPORTS the measured value with its SE rather than using it.

**THE HOME-FIELD GAP IS PRINTED, NOT FUDGED.** Start-of-game reads exactly **0.500** where published tables show ~0.540. That difference IS the home-field advantage this model omits — assumption 2 gives both sides one league-average run distribution, so the only asymmetry left is batting last. The script says so in its output and a test pins 0.500, so any undeclared asymmetry creeping in will fail.

**14 tests, 5 of 5 mutations caught** (extra-innings constant ignored, a tie counted as a home win, thin states estimated instead of omitted, the inning term dropped, convolution dropping the carry). Reuses `mlb_run_expectancy`'s replay rather than writing a second base-state reconstruction — the one over there is the one whose phantom-runner bug was already found and fixed.

**`game_shape.py`'s leverage refusal now has BOTH halves.** Leverage is the swing in WE across outcomes from a state; RE and WE are the inputs. **Wiring it in is a separate change and is NOT done** — and the honest caveat travels with it: this WE is a league-average composition under i.i.d. innings, not an empirical win probability.

#### refresh-worker-oom-recurrence — CHECKPOINT `[2026-08-16 20:3x CDT]` session `refresh-worker-oom-trace` — **TWO INSTRUMENTS SHIPPED AND DEPLOYED; THE ALLOCATOR IS STILL UNNAMED; THE READING THAT WOULD NAME IT HAD NOT ARRIVED**
- **Status: OPEN, and I am handing it over mid-measurement.** The peak-SMAPS
  deploy (`4ec66498`, live 01:23:37Z) exists precisely to answer the open
  question and **had not fired at checkpoint time** — it triggers at anon
  ≥2600MB and the post-deploy worker was at 328MB.
- **Shipped and deployed:** `board_contract_end` (all 8 sports, live since
  `7c2b1a17`) and peak SMAPS (`4ec66498`). Both instrumentation only — **no fix,
  no memory reduced, kills continuing at ~12–18 min through 01:07:16Z.**
- **Verified this session** (full evidence in `state.md` + `log/2026-08-16.md`):
  board contract exonerated (+2MB on a 16-game board); M1 zero markers in a 16s
  excursion; M2 headroom 2231–2953MB at excursion start n=7, magnitude
  +2078–2860MB; the memory guard is silent because it PASSES (3341.6MB at a real
  check point); ~87% of anon invisible to the object census with 1293MB in >64MB
  mmap regions, largest 515MB.
- **RETRACTED this session — do not rebuild on these:**
  (1) "allocator is downstream of `apply_game_board_contract`" — `last_stage` is
  process-global with no thread-locals, so it cannot localize anything;
  `state.md:462` already said so and I missed it.
  (2) the artifact-pull path — refuted by a control arm (same rate in excursion
  and non-excursion windows).
  (3) "raising the floors would not have prevented either kill" — wrong, n=1 and
  the wrong 1.
- **`design_2026-08-17_watchdog_abort.md` is BLOCKED.** Its premise (abort the
  hydration loop) is retracted, and M1 killed its cheap implementation.
- **`candidate_2026-08-17_overview_floor_routing.md` is a live option, NOT
  recommended blind.** Routing the seven sports to the 3000MB floor would have
  refused before all 7 excursions — but 3000 sits INSIDE the routine operating
  band (2913–3186MB), so it is a knife-edge that buys survival with erratic
  board coverage. `intelligence.py:2601` already recorded `sports=1` where every
  prior build read `sports=8`. **Product decision, not an engineering one.**
- **NEXT ACTION, single:** read the first `SMAPS_ANON reason=watchdog_PEAK_anon_*`
  line and diff `largest_regions_mb` against the baseline
  (`515.0, 181.1, 166.2[heap], 104.3, 102.0, 90.0, 83.7, 79.0` at anon
  1610–1700MB). **Whichever region grew is the allocator.** If a kill arrives
  with NO peak line, that is the other real result: 2600MB is too high or the
  excursion outruns the 2s sampler — lower `SYNDICATE_MEMORY_WATCHDOG_PEAK_SMAPS_MB`
  (env change + deploy; a restart does not re-inject env).
- **Files:** `syndicate/features/shared/memory_observability.py`,
  `syndicate/features/shared/game_board_contract.py` (both committed and
  deployed; released by this session). Ledger `lanes.md` append is UNCOMMITTED
  by choice — see the log entry.

#### game-shape-capture — LEVERAGE WIRED INTO `game_shape` (`#454` complete) `[2026-08-16 ~21:4x CDT]`

**The refusal is lifted because the premise changed, not because the bar moved.** `game_shape.py` refused a leverage index on the grounds that a real one needs a fitted win-expectancy table this repo did not have. `#454` built both halves from `feed_live`; the docstring now records that history rather than deleting it.

**NEW:** `scripts/mlb_leverage_index.py` (transition matrix + LI + generator), `syndicate/features/shared/mlb_leverage_table.py` (GENERATED, 5,382 cells, 205 KB of literals).

`LI = E|dWE| from the state / E|dWE| averaged over all plate appearances`. The transition matrix is the new estimable piece — the same replay already observes `(state -> runs, state_after)` for every PA: **~53,000 transitions over 24 states, ~2,200 each**, the same order as the run distributions and nowhere near the 4-per-cell that killed the empirical WE table.

**AGREES WITH PUBLISHED LI:**

| situation | this table | published |
|---|---|---|
| start of game | **0.93** | ~0.9-1.0 |
| bottom 9, tied, bases empty | **2.36** | ~2.2-2.5 |
| bottom 9, tied, bases loaded, 2 out | **10.61** | ~10-11 (near the max) |
| bottom 9, up 6 | **0.00** | dead |

**A NORMALISATION ERROR OF MINE, FOUND BY A SANITY CHECK.** The first version weighted by STATE frequency only, treating every (inning, half, margin) combination as equally likely — so 6-run blowouts counted as heavily as tied middle innings. That deflates the mean swing and inflates everything: **start-of-game read 1.14 when an average plate appearance is 1.00 by definition.** Fixed by weighting on the observed frequency of the FULL cell, which the scan now counts. 1.14 -> 0.93.

**PURITY PRESERVED.** The table is a generated module of literals, imported function-locally, so `game_shape` still does no I/O and loads nothing fitted at import. Records carry `leverage_index` AND `leverage_source`, the latter present even when the value is `None`, so provenance is never inferred from the presence of a number.

**A THIRD VACUOUS TEST OF MINE, CAUGHT BY MUTATION.** `test_leverage_never_defaults_to_one_on_a_miss` passed with the lookup changed to `.get(key, 1.0)` — every input in it was rejected by a guard clause BEFORE the dict was touched, so it tested validation, not the default. The separating case is a state that passes every check and is genuinely absent: **`1-3` with 0 outs, the one base-out combination below the n>=100 floor (n=90)**. A defaulted 1.0 there would populate exactly the cell the corpus could not support, with the most innocuous-looking value available. Split into two tests; L1 now fires.

**65 tests, 5 of 5 mutations caught** (default-to-1.0 on a miss, extras reusing the 9th, `leverage_source` dropped, margin not clipped, margin sign inverted).

**WHAT IS STILL NOT TRUE, and it travels on the record:** these are LEAGUE-AVERAGE values under i.i.d. innings, one shared run distribution, no team or park term, extras as a constant, and a start-of-game WE of 0.500 against a published ~0.540 — that gap IS the omitted home-field advantage. Wrong for a specific matchup. **Also unchanged: no production slate has run through `game_shape` for any sport. n = 0 remains n = 0.**

### wnba-live-tier — GAP DIAGNOSED 2026-08-17 02:3xZ — **the WNBA grid NEVER reports `final`. Its games are stuck on `live` hours after they end.**
- **The scorer is exonerated.** It correctly took the
  `no_final_games_on_this_grid` branch because that grid genuinely has none.
- **Measured, wnba `book_grid` artifact 02:37:22Z, 300 rows served:**
  ```
  game.state = live            93
  game.state = NO_GAME_BLOCK  207     <- 69% of rows never joined a game at all
  game.state = final            0     <- at 02:37Z, hours after the slate ended
  ```
  CHI @ SEA was observed **Final 82-80 at ~23:19Z** on the WNBA lens. Three
  hours later the board's grid still calls its rows `live`.
- **This is the MIRROR IMAGE of the soccer defect fixed earlier tonight.**
  Soccer was stuck on `pregame` and never became live; WNBA becomes live and
  never becomes final. Both are `game.state` never reaching a terminal value,
  and both make a whole class of row un-scoreable — soccer by serving edges on
  finished games, WNBA by hiding the outcomes from the scorer.
- **It also costs more than scoring.** `live_edge_policy` keys on `game.state`:
  a finished WNBA game still reading `live` is treated as LIVE, so its rows keep
  a live tier they should have lost. That is the same family as the soccer harm,
  just pointed the other way.
- **NOT yet diagnosed to a line, and I am not guessing.** Two candidates,
  neither checked: (a) the chip/game-state join (`build_game_chips` ->
  `attach_game_state`) reads a source that never flips WNBA to final, while the
  LENS clearly knows (it reported `status: "Final"`, `in_progress: False`);
  (b) the 180s scoreboard carry-forward I shipped tonight (`16a898ef`) holding a
  stale payload — **unlikely, its bound is 180 seconds and this is hours**, but
  it is new code near this surface and must be ruled out rather than assumed
  innocent.
- **The 207 unjoined rows are a SECOND finding**, not part of the same one: 69%
  of WNBA grid rows carry no `game` block at all, so they have no state to be
  wrong about. That is a join-coverage gap and needs its own measurement.
- **First action for whoever picks this up:** read the wnba chips directly
  (`build_game_chips(date, ["wnba"])`) and compare each chip's `state` against
  the lens's `live_state.final` for the same game. If the chips say `live` while
  the lens says `Final`, it is (a) and the carry-forward is exonerated by
  measurement rather than by argument.

### wnba-live-tier — CHIP COMPARISON RUN 2026-08-17 02:4xZ — **the chips are CORRECT. Two candidates eliminated, one named.**
- **RAN the comparison the previous note asked for.** `build_game_chips(
  '2026-08-16', ['wnba'])`:
  ```
  CHI @ SEA   state=final  token='FINAL'  82-80
  IND @ ATL   state=final  token='FINAL'  95-91
  POR @ PHX   state=final  token='FINAL'  88-85
  ```
  `_game_flags` returns `(is_live=False, is_final=True)` for all three.
  **The chip/state-mapping code is EXONERATED — it flips WNBA to final
  correctly.**
- Worth keeping: IND @ ATL had `live_state.final=False, in_progress=True` and
  STILL resolved final, because `_game_flags` found "final" in the `status`
  dict's text and `is_final` forces `is_live=False`. The fallback did its job.
- **THE 180s SCOREBOARD CARRY-FORWARD (`16a898ef`) IS EXONERATED BY
  MEASUREMENT, not by argument.** Its bound is 180 seconds against a
  three-hour discrepancy, and on failure it returns the stored payload without
  re-storing it, so it cannot ratchet. It was named as a suspect because it is
  new code on this surface; it is now cleared.
- **THE 30s CHIP CACHE IS EXONERATED.** `_CACHE_TTL_SECONDS = 30.0` — three
  orders of magnitude too short to hold a three-hour staleness.
- **WHAT THAT LEAVES, and it is a candidate, NOT a conclusion.** The chips are
  right and the served grid is wrong, so the stale `live` is introduced
  *between* them. The leading suspect is
  **`attach_live_game_state_from_lens`** (`book_grid_artifact.py:221`), which
  runs AFTER `attach_game_state` (`:215`) and can overwrite a correct `final`
  with a stale `live` from the published lens snapshot. **Not verified** — I ran
  out of budget before measuring it.
- **NOTE THE ENVIRONMENT DIFFERENCE before trusting the local run.** Locally
  `build_live_state_payload` took `build_live_state_payload_fallback_return` (a
  stored snapshot); on the worker `_render_web_dyno()` is False and it takes the
  live ESPN path. So the local run proves the MAPPING is correct, not that
  production's inputs are the same.
- **Next action, one measurement:** on a served wnba `book_grid` row whose game
  is finished, compare `game.state` against the chip for the same game and
  against `live/wnba_live_lens.json`'s `live_state.final`. If the chip says
  final and the row says live, `attach_live_game_state_from_lens` is the writer
  and the lens is the stale input.

#### refresh-worker-oom-recurrence — CHECKPOINT 2 `[2026-08-16 21:4x CDT / 02:43Z]` session `refresh-worker-oom-trace` — **THREE INSTRUMENTS DEPLOYED, TWO EXCURSIONS CAPTURED, THE ALLOCATOR IS STILL UNNAMED**
- **Status: OPEN. Handing over mid-measurement again.** `PAYLOAD_LOAD`
  (`7d8f960d`, live 02:39:10Z) is the instrument that would settle it and **had
  not fired at checkpoint**. Watcher `bidt2sb0u` was running.
- **The single most important thing for whoever reads this: DO NOT treat "one
  giant growing VMA" as the signature.** Excursion 1 (01:46) was one region
  1096.5→1586.4MB with #2/#3/#4 frozen. Excursion 2 (02:27) was TWO comparable
  regions (~750/~650MB) trading places, moving both up and down. Same bug, two
  shapes — most likely because VMA identity is a kernel-coalescing artifact, in
  which case region topology can locate bytes but can never name an allocator.
- **Verified and durable** (details in `state.md` + `log/2026-08-16.md`): the
  per-file ledger ceiling is applied BEFORE the read and is NOT the bug — the
  unbounded quantities are the accepted SUM (830,832,574 bytes) and caller
  MATERIALISATION; `recommendation_engine`'s duplicate-load defects are already
  fixed; the settlement autorun is OFF (105 env keys, 2 pages) and is statically
  the only production path to `evaluation_settlement._read_chunk_records`.
- **DEAD ENDS, so nobody repeats them:** (1) instrumenting
  `evaluation_settlement._read_chunk_records` — BLOCKED by
  `grading-blocker-settled-zero`, and pointless anyway with the autorun off;
  (2) `LEDGER_LOAD` on `recommendation_engine._load_records_from_ledger` — that
  wrapper reads a FLAT path that does not exist, `records=0`; reverted and moved
  to `_iter_record_payloads`.
- **NEXT ACTION, single:** read the first `PAYLOAD_LOAD` line **with
  `records >= 1000`** and check `anon_delta_mb`. ≥1000MB supports the
  materialisation hypothesis; a small delta on a LARGE load refutes it. **A small
  delta on a small load is a NULL result, not a refutation** — that error was
  made once tonight by an automated verdict and is now guarded in both the code
  and the watcher.
- **Files (all committed, on `origin/main`, released by this session):**
  `memory_observability.py`, `intelligence_evaluation.py`,
  `game_board_contract.py`, `recommendation_engine.py` (net zero),
  `tests/test_watchdog_peak_smaps.py`, `tests/test_ledger_load_trace.py`,
  `tests/test_board_contract_stage_markers.py`. `lanes.md` append UNCOMMITTED by
  choice.

### soccer-layer2-dates — OPEN — opened 2026-08-17 — session: soccer-sport-owner
- Goal: the Layer 2 compact-game rail shows ONLY today's soccer games, each with a
  state its kickoff time can support. **Testable outcome:** on production
  `/intelligence` with the DEFAULT day tab ("All"), the Games rail contains zero
  soccer cards whose Central date != today, and `/api/board/game-chips?sports=soccer`
  returns zero chips with `state` in {final, live} and `start_time_utc` in the future.
- Files:
  - `syndicate/templates/intelligence.html` — TAKEN 2026-08-17 ~20:0xZ from
    `layer2-board-quality`, whose entry now records the release. Scope: the
    day-tab default only (`state.date` init :244, `syncUrlState` :336, day-tab
    handler :383-395, `#board-date` sync :293, toolbar submit :2444). Nothing
    touching scoring, `sim_component`, movement/steam gating or `#446`. A scoped
    release was requested from the live coordinator at ~19:4xZ BEFORE any edit;
    all three owning sessions of that lane are archived and not running.
  - `syndicate/features/soccer/**` — TAKEN. `soccer-model-coverage`'s claims were
    RELEASED at session archive per the 2026-08-17 coordinator sweep (recorded in
    `wnba-phase2-migration`'s own entry); its own body says "To resume: /lane open
    soccer-model-coverage and re-take the files". I am the soccer-owning session.
    **Its uncommitted fixes are NOT mine** — `git status` shows M on
    `ingestion/espn_live_state.py` and `sim_engine/soccersim/calibration_profile.py`;
    I will not commit those.
  - `syndicate/blueprints/home.py` — `_SoccerDataProvider` only (:5944-6047).
    `refresh-worker-oom-recurrence` lists this file as an *expected candidate* and
    says explicitly "none claimed yet ... diagnostic". Read as unclaimed.
- Hypothesis (H1) — **CONFIRMED, MEASURED, root cause found:** the rail's chip date
  filter is inert on the default view. `intelligence.html:1514` reads
  `const railDate = String(state.date || "").slice(0,10) || null;` and the filter is
  `if (railDate && chipDate && chipDate !== railDate) continue;`. The DEFAULT day tab
  is "All", which sets `state.date = ""` (`:244`, deliberate since `#93`), so
  `railDate` is null and the filter never runs. The filter is correct; its guard
  makes it a no-op on the view every user loads.
- Falsification test (H1): if the filter were live on the default view, selecting the
  "Today" tab would not change the soccer card count. **RUN 2026-08-17 19:4xZ in the
  live production page:** default "All" tab = **51 soccer cards across 8 distinct
  non-today dates (Sat Aug 15 → Fri Aug 28)**, including a two-days-PAST game rendered
  PREGAME. Clicking "Today" = **3 soccer cards, 0 non-today dates.** Not falsified.
- Hypothesis (H2) — **CONFIRMED, and it is UPSTREAM DATA, not logic:** the chip
  `eredivisie EXC @ NEC` reads `state: final`, `FINAL`, 0-0, kickoff
  `2026-08-22T18:00:00Z` — five days in the future. Traced end to end: production
  `/soccer/eredivisie/api/cards` serves that game with `live_state: {final: True}`
  while all 7 sibling fixtures read `{final: False}`. `cards.py::_live_state_block`
  maps `status_state == "post"` -> final, so **production's eredivisie schedule
  artifact carries `status_state: "post"` on a future fixture** (event `401875655`
  family; the git mirror, generated 2026-07-20, still reads `"pre"` for the same
  event `401875636`). 1 of 89 chips. **There is no guard anywhere that a fixture
  cannot be final before it has kicked off.**
- Falsification test (H2): if this were a rendering bug rather than bad source data,
  the sibling eredivisie fixtures on the same date/week would show the same wrong
  state. They do not — 7 of 8 read `final: False`. Not falsified.
- Verification: re-run BOTH measurements above against production web after deploy —
  (a) default-tab soccer cards with a non-today Central date: 51 -> 0; (b) chips with
  an impossible state: 1 -> 0. Numbers written to `.syndicate/deploys.md`.
- Blocked by: `intelligence.html` release from `layer2-board-quality` (requested, not
  blocking the H2 work or the soccer pipeline/live-lens strands).

### soccer-layer2-dates — CHECKPOINT 2026-08-17 ~20:5xZ — two fixes committed and UNDEPLOYED, third strand localised not fixed

**Commits, both on local `main`, NEITHER PUSHED. Coordinator notified twice.**

- `cd46b403` — Layer 2 rail dates + soccer impossible status. Deploy request filed
  at `.syndicate/deploy/requests/2026-08-17T202000Z-soccer-layer2-dates.md`.
- `6aaa11af` — soccer projection window, LOADER SIDE ONLY. **Inert until its caller
  is wired**, by construction: `window_dates` is keyword-only and defaults to
  `[selected_date]`. Do not read this commit as a shipped fix.

**#1 rail dates — ROOT CAUSED AND FIXED.** `intelligence.html:244` defaulted
`state.date` to `""`, and BOTH date filters are guarded on it being truthy
(`matchesClientFilters`' `if (!state.date) return true`; the rail's `railDate`).
So the default view was the only view with no date filter. Measured on production
19:4xZ: default "All" = **51 soccer cards over 8 non-today dates (Aug 15 → Aug 28)**,
one a two-days-past match rendered PREGAME; clicking "Today" = **3 cards, 0 non-today
dates**. Fix = default the day tab to Today (**user decision, asked and answered**).
Day filter moved to `?day=` so a defaulted date is never persisted as an explicit
`?date=` override — that would have been `#113` from the other end.

**#2 impossible status — ROOT CAUSED AND FIXED.** `eredivisie EXC @ NEC` served
`state: final`, 0-0, kicking off `2026-08-22T18:00Z`. NOT the renderer: 7 sibling
fixtures same league/week read `final: false`, so one `status_state: "post"` is
corrupt in the schedule artifact. `_effective_status_state` refuses a
started/finished claim its kickoff contradicts. **Downgrade-only** — cannot promote,
so it cannot reintroduce the stuck-at-pregame failure. 12 tests.

**#3 projection window — ROOT CAUSED, HALF FIXED, BLOCKED ON A LANE.**
`#379` widened the QUOTE read to the slate window and left the projection read at
one date. Production 19:5xZ: `grid_rows 8,759`, `rows_with_projection 4`,
`matches_in_source 3`, `unmatched_match_rows 8,755`, `rows_with_model_edge 0`,
soccer absent from `per_sport`, 0 rows served of 5,527 opportunities. This is what
keeps soccer off the board — the A3 filter spares a hold-restatement row ONLY if it
has a projection.
- **Confirmed the fix has something to find** before writing it: production serves
  real simulated projections on exactly the invisible dates — eredivisie 7 of 8
  games Aug 22-28, epl Aug 21, la_liga 8 games Aug 15-21, all with win probabilities.
- **BLOCKED:** the caller is `board_enrichment.py:678`, claimed by OPEN
  `wnba-live-tier` (session `layer1-board-coverage`, which IS live). Scoped release
  requested ~20:4xZ for the soccer branch only. **Not taken. Do not take it without
  a reply** — unlike `layer2-board-quality`, that lane has a running owner.
- Hazard handled loader-side: the sim and board feeds use different event-id schemes
  so the join is really name-keyed; over 7 days one team pair can mean two fixtures.
  Colliding keys are removed and recorded (`ambiguous_team_keys`) rather than guessed.

**#4 live lens — REPRODUCED AND LOCALISED, NOT DIAGNOSED. Next session starts here.**
- `/soccer/la_liga/api/live-lens` at 19:0xZ: **"Live matches: 0", "Source: No data",
  `card_sections: []`** while `ELC @ Deportivo` was genuinely in play (chip LIVE,
  kicked off 19:00Z). Same for championship and primeira_liga, each with a live match.
- The page reads ONLY `soccer_source/<league>/api/live_state/live_state_<date>.json`
  (`live_lens.py:128`). So the poller is not producing them for these leagues.
- **Two hypotheses NOT yet tested — do not report either as cause:**
  H1 the soccer memory gate (`SYNDICATE_SOCCER_LIVE_LENS_MEMORY_GATE_ENABLED`,
  **default True**) is skipping soccer ticks for headroom — plausible given this
  repo's worker-OOM history; H2 the loop is not running soccer at all.
- **EXONERATED, so nobody re-runs it:** the disk split is NOT the cause.
  `soccer_source/*/api/live_state/live_state_*.json` IS allowlisted in
  `artifact_publisher.py`, so the artifact has a path across.
- **STALE LEDGER NOTE CORRECTED:** `state.md` says the soccer poller was "never run"
  / "unwired". It IS wired — `live_lens_loop.py:57` imports
  `poll_active_leagues_for_tick`, `_LIVE_LENS_SPORTS` includes soccer, and
  `SYNDICATE_ENABLE_LIVE_LENS_LOOP: "true"` is in `render.yaml:1041`. Blueprint is
  not live env; **enumerate the live env-vars before concluding anything.**
- Also seen, unexplained, low severity: the live-lens payload's `date` field is the
  integer **1** (the resolved WEEK), not a date.

**Not mine, flagged not fixed:** `tests/test_layer2_soccer_window.py` 2 failures are
PRE-EXISTING (stash-verified: 4 passed / 2 failed with and without my change); its
`monkeypatch.setattr(quotes, "read_book_quotes", ...)` no longer bites.

**Deliberately untouched:** `syndicate/features/soccer/ingestion/espn_live_state.py`
and `sim_engine/soccersim/calibration_profile.py` — uncommitted orphaned
`soccer-model-coverage` work sitting in the shared tree. Note `espn_live_state.py` is
on the #4 path, so whoever takes #4 must reconcile that uncommitted diff FIRST.

**No ledger file committed** — `lanes.md` carries other sessions' concurrent edits.

### soccer-layer2-dates — H1 FALSIFIED 2026-08-17 20:3xZ — the soccer memory gate is NOT the cause, and `ok: true` was never evidence

**H1 (the soccer live-lens memory gate is skipping ticks) is DEAD. Do not re-run it.**

Live env-vars read on all three services (`/v1/services/<id>/env-vars`, paginated):

| key | web | refresh-worker | live-odds-worker |
|---|---|---|---|
| `SYNDICATE_ENABLE_LIVE_LENS_LOOP` | ABSENT | **true** | **true** |
| `SYNDICATE_LIVE_LENS_INTERVAL_SECONDS` | ABSENT | ABSENT | 60 |
| `SYNDICATE_SOCCER_LIVE_LENS_MEMORY_GATE_ENABLED` | ABSENT | ABSENT | ABSENT |
| `SYNDICATE_SOCCER_LIVE_LENS_MIN_HEADROOM_MB` | ABSENT | ABSENT | ABSENT |
| `SYNDICATE_LIVE_LENS_MIN_HEADROOM_MB` (MLB's) | ABSENT | ABSENT | 300 |

Absent means the gate IS enabled (`_env_bool(..., default=True)`) at a 300MB floor, so
the gate was live and the hypothesis was reasonable. It is still wrong:
`/api/ops/live-lens/status` at **20:29:46Z** shows soccer `ok: true`, NOT in
`skippedSports` (`["nba","nfl"]`), `activeSports: ["mlb","wnba","soccer"]`, no
`reason: low_headroom`. **The tick runs, every 60s, and succeeds.**

**`ok: true` PROVES NOTHING HERE, and that is the finding.**
`validate_live_lens_snapshot` returns True for `{"date": ..., "games": []}` — an
EMPTY games list validates. So a tick that processed zero matches is indistinguishable
from one that processed three. Corroborating: soccer's tick ran **20:29:45 -> 20:29:46,
one second**, against MLB's 20:29:37 -> 20:29:44 (seven). Soccer's builder is supposed
to run up to 4 Monte Carlo passes PER LIVE MATCH. One second is the shape of zero work.

**Ground truth at that moment: 3 soccer matches WERE live** and scoring — `ELC @
Deportivo` 0-1, `SLB @ CAS` 5-0 (was 1-0 an hour earlier), `WXM @ CAR` 1-0. So the
poller ran, reported success, and produced nothing the page can read.

**TWO ARTIFACTS, NOT ONE — this is the thing to hold on to.**
- `data/live/soccer_live_lens.json` — bookkeeping/validation ONLY, written by the loop.
  `live_lens.py:21` says so explicitly.
- `soccer_source/<league>/api/live_state/live_state_<date>.json` — the REAL per-league
  artifact, written by `poll_league()`, and the ONLY thing the live-lens page reads.

**REMAINING HYPOTHESES, both untested — do not report either as cause:**
- H3: `active_leagues_for_date(iso_date)` / `poll_league` find no in-progress matches on
  the WORKER. Note the link worth chasing: the poller keys off the schedule artifact's
  `status_state`, which is the SAME field already proven corrupt today (`EXC @ NEC`
  final five days early). Web's copy says "in" for these 3; the worker's copy may not.
- H4: the per-league files are written to the worker disk and never cross.
  `soccer_source/*/api/live_state/live_state_*.json` IS allowlisted in
  `artifact_publisher.py` (so the earlier disk-split exoneration stands for the PATH),
  but that the allowlist covers it is not proof the publish ran.

**THE DISCRIMINATING TEST, already identified so nobody re-derives it:**
`poll_active_leagues_for_tick` returns `leagues_checked`, `leagues_with_games`, `errors`
and the flattened `games` list, and all of it goes into
`data/live/soccer_live_lens.json`. `leagues_with_games == []` proves H3;
non-empty proves H4. **That file is NOT in the publisher allowlist** (only
`live/mlb_live_lens.json`, `live/nba_live_lens.json`, `live/wnba_live_lens.json` are),
so it is unreadable from web — same class as the recorded "worker counters unreadable
from web" rule. Read it via the Render logs API on **live-odds-worker** (which is the
one carrying `MLB_ENABLE_LIVE_LENS_LOOP=true` and so is the likely tick owner), or
allowlist the file.

**GAP FOUND ON THE WAY, worth fixing whoever takes this:** MLB and WNBA both
`print("[LIVE_LENS_TICK_DIAG] ... reason=low_headroom ...")` when their gate trips.
**Soccer's gate returns silently** (`live_lens_loop.py:524-530`). WNBA's own comment in
that same block says "a gate that fires silently cannot be told from a builder that
never ran" — soccer is the instance that comment describes and does not cover. It cost
this session a hypothesis it could have ruled out from a log line.

### soccer-layer2-dates — LIVE LENS ROOT CAUSED 2026-08-17 20:3xZ — H3 CONFIRMED, H4 DEAD. The only leagues that fail are the ones with live matches.

**Worker logs, live-odds-worker, `text=live games`, 19:47-20:32Z.** The poller writes
its real per-league artifact every ~70s, path confirmed:

    20:16:07  wrote /opt/render/project/data/soccer_source/epl/api/live_state/live_state_2026-08-17.json (0 live games)
    ... and bundesliga, serie_a, ligue_1, mls, eredivisie, belgian_pro_league

**SEVEN leagues per tick, every tick. `active_leagues_for_date('2026-08-17')` returns
TEN.** The three that never appear are `la_liga`, `primeira_liga`, `championship` —
**exactly and only the three with live matches** (`ELC @ Deportivo`, `SLB @ CAS`,
`WXM @ CAR`, all in play and scoring at that moment). Zero-overlap anti-correlation,
not a coincidence.

- **H4 (files never cross the disk split) is DEAD.** They are written, to the right
  path, continuously. The read side is not the problem.
- **H3 is CONFIRMED, with a sharper cause than hypothesised.** It is NOT stale
  `status_state` on the worker. `poll_active_leagues_for_tick` (`:175-181`) catches
  each league's exception into an `errors` dict and `continue`s **with no print**, so
  a throwing league is indistinguishable from one that was never active.

**WHY ONLY THE LIVE LEAGUES FAIL — the mechanism, from `poll_league` (`:66-100`).**
Everything expensive sits behind `if live_events:` — `_load_team_ratings`,
`_fill_promoted`, `_load_player_rows`, then the per-event Monte Carlo. A league with
no live match skips that block entirely and writes `(0 live games)` successfully.
**Only a league WITH a live match executes the code that can throw.** So the failure
is invisible on a quiet slate and total on a busy one, which is the worst possible
shape and is why this survived.

**NOT the per-event handler.** That one prints (`skip {event_id}: {error}`, `:88`) and
the logs carry **0 such lines** in the window. The throw is above it — in
`_load_team_ratings`, `_fill_promoted`, `_load_player_rows`, or the post-loop write.

**LEAD, not a finding:** `state.md` already records `SOCCER_PLAYER_ROWS_MISSING` on
**eredivisie, primeira_liga, championship**. Two of those three are in our failing set.
`_load_player_rows` is a live candidate. Eredivisie not failing is consistent — it had
no live match today, so it never reached that line.

**THE EXCEPTION ITSELF IS STILL UNPROVEN.** It is captured in the returned `errors`
dict, which goes only into `data/live/soccer_live_lens.json` — **not in the publisher
allowlist**, so unreadable from web. Do not guess it; make it observable first.

**FIX ORDER for whoever takes this:**
1. **Make the swallow print** — one line at `poll_soccer_live_state.py:180`, mirroring
   `:88`'s existing `skip` print. Without it every later step is guesswork. This is the
   same instrument gap as soccer's silent memory gate recorded above; that is now TWO
   silent handlers on one path in one session.
2. Read the real exception, then fix it.
3. Consider allowlisting `live/soccer_live_lens.json` so `leagues_with_games` /
   `errors` are reachable without the logs API at all.

**Note for `#1`/`#2` of this lane:** the corrupt `status_state` guard I shipped is
unrelated to this — I floated schedule staleness as the link and it is NOT the cause.
Recorded so the guard is not credited with fixing the live lens.

### soccer-layer2-dates — LIVE LENS: EXCEPTION IDENTIFIED 2026-08-17 20:4xZ, NO DEPLOY NEEDED. One-line signature drift.

**The swallowed exception is:**

    TypeError: _load_team_ratings() missing 1 required positional argument: 'as_of'

Reproduced locally, not inferred. `scripts/build_soccer_artifacts.py:54` is
`_load_team_ratings(league, source_root, as_of)` — three required args — and
`scripts/poll_soccer_live_state.py:75` calls it with **two**:

    ratings = _load_team_ratings(league, source_root)

**Caller census (`_load_team_ratings(`):**

| call site | args | state |
|---|---|---|
| `build_soccer_artifacts.py:238` | `(league, source_root, iso_date)` | UPDATED |
| `poll_soccer_live_state.py:75` | `(league, source_root)` | **BROKEN** |
| `validate_soccer_vs_market.py:189` | `(league, fixture_date)` | ok (local 2-arg fn) |
| `validate_soccer_vs_market.py:316` | `(league)` | **ALSO BROKEN** |
| `validate_soccer_vs_market.py:449` | `(league)` | **ALSO BROKEN** |

**Provenance:** `as_of` was made required by the audit §7 #6 / `soccer-backtest-leakage`
as-of work — the same orphaned `soccer-model-coverage` material this lane inherited.
It updated the one caller inside its own module and missed the other three.

**WHY IT SURVIVED, and this is the reusable part.** Three independent covers:
1. **Position in `poll_league`.** The call sits behind `if live_events:`, so it only
   executes for a league with a match IN PLAY. Quiet slate = no error, ever.
2. **The silent handler.** `poll_active_leagues_for_tick:179-181` catches it into an
   `errors` dict with no print, and that dict reaches only
   `data/live/soccer_live_lens.json`, which is not in the publisher allowlist.
3. **The test pinned the fixed caller and only that one.**
   `tests/test_soccer_team_ratings_as_of.py:117` asserts the literal source text
   `"_load_team_ratings(league, source_root, iso_date)"` appears in
   `build_soccer_artifacts`. It is a call-site assertion over ONE module, so it goes
   green while three other call sites are broken. **A signature change needs a caller
   census, not a spot-check of the caller you just edited.**

**THE FIX — one line, `poll_soccer_live_state.py:75`:**

    ratings = _load_team_ratings(league, source_root, iso_date)

`iso_date` is already this function's parameter, and it is the correct value: the
docstring at `build_soccer_artifacts.py:55` says `as_of` is "the date being built for",
and live polling builds for the in-progress fixture's own date. Semantically identical
to `:238`'s `iso_date`.

**Predicted effect, so it is falsifiable:** la_liga / primeira_liga / championship stop
being swallowed; their `live_state_<date>.json` carries `count > 0` while matches are in
play; `/soccer/<league>/api/live-lens` moves off "Live matches: 0 / Source: No data".
Leagues with nothing in play still legitimately write `(0 live games)` — that is NOT a
failure and must not be read as one.

**Diagnostic print is the USER's edit, in flight** — I reverted mine to avoid two
versions. Still worth landing: it is what makes cover #2 stop hiding the NEXT fault,
and it is independent of this fix.

**H4 stays DEAD, H3 CONFIRMED and now explained.** The corrupt `status_state` lead
(`EXC @ NEC`) is EXONERATED for the live lens — wrong hypothesis, recorded so the
status guard is not credited with this.

### soccer-layer2-dates — LIVE LENS FIXED AND VERIFIED PRE-DEPLOY 2026-08-17 20:5xZ — `6bdc50de`

`poll_soccer_live_state.py:75` now passes `iso_date` as `as_of`. Verified by running
the REAL poll path against the live ESPN feed for all three previously-failing
leagues — la_liga, primeira_liga, championship each wrote **`(1 live games)`** where
production wrote nothing. la_liga's payload: Elche 1-1 Deportivo, 2nd half, 7/11
shots, 2/7 corners, 12 live player props. Written to a scratchpad `out_root`, not the
repo data tree.

**Deploy request filed:** `.syndicate/deploy/requests/2026-08-17T205500Z-soccer-live-lens-as-of.md`.
**WORKER-side, not web** — independent of `cd46b403` / `6aaa11af`. Marked LOW urgency
on purpose: a deploy went out just before it was filed and this does not justify
stacking another.

**OPEN QUESTION FOR THE DEPLOYER, do not assume:** `SYNDICATE_ENABLE_LIVE_LENS_LOOP`
is `true` on **BOTH** `refresh-worker` and `live-odds-worker`. The observed soccer
tick logs came from live-odds-worker. If both actually run the loop, both need this or
the fix is half-applied.

**VERIFICATION HAS A PRECONDITION:** it needs a soccer match in play. A league with
nothing live still writes `(0 live games)` and that is CORRECT — the pass condition is
that the three MISSING leagues appear (7 -> 10 `wrote` lines per tick), not that every
count is non-zero. On an empty slate this is unverifiable and must be recorded as
such, not as passing.

**STILL OPEN, deliberately not taken:**
- `validate_soccer_vs_market.py:316` and `:449` — same as-of miss, one arg to a
  two-arg local `_load_team_ratings`. `soccer-model-coverage`'s files.
- `tests/test_soccer_team_ratings_as_of.py:117` asserts the literal call-site TEXT in
  ONE module. This is why CI was green throughout. A caller-census assertion is the
  real fix and would have caught all four sites.
- The silent per-league handler at `:179-181`. **User is adding that print** — I
  reverted mine to avoid two versions; the file is clean in the worktree for them.

**LANE STATUS: all four strands root-caused. Three fixed and committed, none
deployed.** `cd46b403` (rail dates + status guard, web) · `6aaa11af` (projection
window, loader only — INERT until its caller is wired, blocked on `wnba-live-tier`
releasing `board_enrichment.py:678`) · `6bdc50de` (live lens, worker).

#### convergence-phase7-crps — CHECKPOINT 3 (FINAL) 2026-08-17 — **the instrument is built and it has answered the product question: no MLB market beats its price yet, and the reasons are now specific**

- **Phase 7 is DONE and was used**, not just built. It found: the F5 leash, the
  MLB outs uninformative centre (r=0.05), the sim-count knee (~300), NFL margin's
  proven skill (+3.20%, CI excludes zero), NCAAF's total leak, and the missing
  substitution model.
- **THE HEADLINE: MLB hitter props lose to the market in 3 of 3 clean families**
  (0.0015–0.010 Brier). That was the falsification test and it came back
  negative — the programme is "close a measured gap", not "scale an edge".
- **THE BEST NEWS: the opportunity haircut closes that gap in 3/3 families
  out-of-sample and flips `runs` past the market.** One fitted scalar. The
  expensive fix (real substitution) is now justified by measurement.
- **Root cause is a MISSING MECHANIC:** the sim never substitutes position
  players. Managers differ 1.68x, so `manager_tendencies.json` (absent, loader
  returns `{}`) is justified — **P1 and P2 are one piece of work.**
- **I was wrong about game lines and corrected it:** totals run LOW (−0.481), not
  high, so the opportunity bug is PROP-PATH ONLY. Game totals and home-field
  (−0.32 runs) are separate, unexplained defects.
- **Plan:** `.syndicate/plan_2026-08-17_mlb_best_engine.md`.
- **Still open / owed:** the NFL seed curve never completed; production's
  accumulate-vs-retain regime is unconfirmed; `hits_runs_rbis` extractor is
  broken; MLB totals' +2.02% needs a CI; two deploy requests are queued and
  DE-PRIORITISED by me; `outs-props-coverage-check` fires 2026-08-19.
- **NEXT ACTION:** slot-conditioned + score-state haircut (both curves measured
  and in `deploys.md`), then re-run `mlb_opportunity_haircut.py`. The scoreboard
  is the market, and it is now a single command.

### soccer-layer2-dates — CHECKPOINT 2026-08-17 22:0xZ — 4 STRANDS ROOT-CAUSED, 4 COMMITTED + PUSHED, 1 DEPLOYED AND MEASURED, 1 AWAITING WEB, 1 INERT ON ANOTHER LANE — session: soccer-layer2-dates

- Goal: soccer's Layer 2 surfaces tell the truth about WHEN a match is and WHETHER
  it is live, and soccer reaches the board with real projections.
  **Testable outcome:** (a) the Games rail shows only today's Central date;
  (b) no chip reports `live` for a match ESPN calls `post`; (c)
  `pct_projected` for soccer on `/api/board/layer2-shortlist` is materially
  above 0.0.

**STATUS BY STRAND**

| strand | commit | state |
|---|---|---|
| live-lens `TypeError` | `6bdc50de` | **DEPLOYED + MEASURED** (7 -> 10 leagues/tick, 21:38:37Z) |
| rail dates + stale-live guard | `cd46b403` | pushed, **WEB NOT DEPLOYED** (asked twice) |
| projection window | `6aaa11af` | pushed, **INERT** — blocked on `board_enrichment.py:678` |
| caller-census test | `18c5ecb9` | pushed |

**(a) and (b) are NOT met in production** — web is still `60cdf8eb` from 02:52:02Z.
Verified 21:55:10Z by three independent means (deploy API row; **1 of 79**
`cd46b403` template lines on the served page; criterion 1 still failing).
**(c) is NOT met** and cannot be until the wiring below lands.

**THE ONE BLOCKER THAT A DEPLOY CANNOT CLEAR.** `board_enrichment.py:678` still
reads `load_soccer_projections(roots, selected_date)`. It needs the 7-day window.
The file is claimed by OPEN lane `wnba-live-tier` (session `layer1-board-coverage`
= "Layer 1 Board Session", `local_bd97b64e-1126-4970-9cba-dba61ad12a22`, running).
**Messaged 22:0xZ with three options: they take the one-liner, they release the
file, or they say it conflicts and we sequence. No reply yet.** The new kwarg is
keyword-only with a default, so taking it cannot break their in-flight work.

**DO NOT REPEAT THESE — settled this session.**
- The soccer memory gate is EXONERATED (absent env = ENABLED, but it never fired).
- The disk split / publisher is EXONERATED for live-lens; files are written to the
  correct path every ~70s.
- Stale `status_state` on the worker is NOT the live-lens cause. The status bug and
  the live-lens bug are unrelated — do not credit `cd46b403` with fixing the lens.
- `.claude/worktrees/*` had no broken call sites; that was a sweep artefact. Both
  pruned.

**FOR WHOEVER PICKS THIS UP — the two traps that cost time here.**
1. **Test deployment by CONTENT, not ancestry.** `7470939b` does NOT contain
   `6bdc50de` as an ancestor yet ships the fix (deploy branch). Ancestry said
   ABSENT; `git show <sha>:<path>` said PRESENT.
2. **Do not grep a shared symbol to confirm a deploy.** `railDate` is present on
   the STALE web build (it is the older, insufficient filter), so grepping it
   reports success. Derive markers from the actual diff.

**NEXT ACTION, in order:** (1) chase `wnba-live-tier` for `board_enrichment.py:678`
— it is the only thing blocking (c) and the only blocker that is a person, not a
deploy window; (2) get `cd46b403` onto web and run the three criteria (I can run
them in ~1 min); (3) re-verify the live lens end-to-end on a slate with a match
actually in play — today's was `post` across all three leagues.


#### convergence-phase7-crps — CHECKPOINT 4 (FINAL) 2026-08-17 — **P2 shipped to the tree, measured against the market, and DELIBERATELY NOT DEPLOYED**

- **The engine now has a position-player substitution model.** It never did.
  Behind `GameConfig.position_substitutions`, **default False**, 9 tests, and the
  leash suite still green.
- **Opportunity: 34.3% of the gap closed** (starter AB 3.985 → 3.817 vs an actual
  3.495), measured on the real engine, not a rescaling.
- **Accuracy vs the market, 2,415 rows:** hits +0.00209, RBI +0.00573, runs
  +0.00146, **total_bases −0.00154 WORSE**. **The market wins all four.**
  P2 improved the engine and produced **no edge**.
- **NOT DEPLOYED, on purpose.** A 3-of-4 record is not a defensible basis for
  shipping when the failure is in a market we publish. Likely cause is a
  simplification I shipped knowingly: bench selection is **next-available**, not
  platoon/position aware, and total bases is power-weighted.
- **`scripts/reproject_mlb_props_with_subs.py` is the durable win** — a
  one-command market scoreboard for ANY MLB engine change, from archived rosters,
  both arms the sim's own PMF over identical seeds. This did not exist today.
- **Three of my own claims retracted this stretch**: the tendencies artifact was
  inert three ways; the root cause was the missing CONSUMER not the missing file
  (`pinch_hit_aggressiveness` is read by nothing); the anchored sim-count table
  was wrong for NFL/NCAAF. Also: the re-projection smoke run overstated by ~3x.
- **NEXT ACTION:** platoon/position-aware bench selection, then re-run
  `reproject_mlb_props_with_subs.py`. Deploy only with the total-bases row
  non-negative.
- **Still open:** `hits_runs_rbis` extractor broken; MLB totals' +2.02% has no CI;
  two deploy requests queued and de-prioritised by me; `outs-props-coverage-check`
  fires 2026-08-19.

#### soccer-layer2-dates — CLAIM OVERRIDE — taking `artifact_publisher.py` from the ORPHANED lane `clv-without-settlement`
- **Not an override.** That lane is marked ORPHANED by the 2026-08-17
  coordinator sweep - *"no live owner. Session `lane-cleanup` no longer exists
  in the roster"* - and `lane-guard` cannot see sweep releases.
- **Its own SINGLE NEXT ACTION is the same kind of change**: allowlist
  `*_source/data/live_gameline_ledger/*.jsonl` in `HOT_ARTIFACT_PATTERNS`.
  **I did NOT add that pattern** - it is their scope, and every entry on this
  list is a real egress cost (`#394`). Flagged, not taken.
- Files taken: `syndicate/features/shared/artifact_publisher.py` (one added
  pattern, soccer recommendations only).

#### clv-without-settlement — INBOUND ONE-LINE REQUEST from `convergence-phase7-crps` `[2026-08-17]`

**Not a claim, not an edit. A request, because you own the file.**

`syndicate/features/shared/artifact_publisher.py` needs ONE pattern added to
`HOT_ARTIFACT_PATTERNS`:

    "*_source/source_artifacts/data/pitch_splits/pitch_splits_*.json",

**Why:** `#440` measured that the sim's pitch-type multipliers
(`pitch_type_whiff_mult`, `vs_pitch_type`) are empty on **449/449 production
pitchers**, so `.get(pitch_type, 1.0)` makes a slider and a fastball
interchangeable. The data existed only in a `DiskCache` under `vendor/*/data/`,
which is **gitignored AND inside Render's ephemeral checkout** — the `#389`
shape, unable to ship. It is now published as a disk-backed artifact
(`data/mlb_source/source_artifacts/data/pitch_splits/pitch_splits_2026.json`,
73 pitchers) resolved through `SYNDICATE_DATA_ROOT`, and the loader reads it
first (5 tests, including the empty-cache worker case).

**Without this line the artifact will not mirror or export.** Everything else is
committed (`87f34554`).

**I did NOT take the file.** I had already taken one file under a logged override
earlier today and did not reach across a second time. Apply it when convenient —
nothing of mine is deployed and there is no deadline.

#### convergence-phase7-crps — CHECKPOINT 5 (FINAL) 2026-08-17 — **research delivered; pitch-splits wired but UNPROVEN and UNSHIPPABLE without two things I did not do**

- **Research:** `.syndicate/research_2026-08-17_mlb_sim_gaps.md`. Headline —
  pitch-type effectiveness is **built, sampled, and 0% populated** (449/449
  pitchers) while `arsenal` is 100%, so a slider and a fastball are
  interchangeable. Also: **no defence model, no catcher framing, no batted-ball
  types** anywhere; **BVP fetched daily and never referenced by the sim**.
- **Wired (not deployed):** disk-backed artifact via `SYNDICATE_DATA_ROOT` +
  artifact-first loader, 73 pitchers, **5 tests incl. the empty-cache WORKER
  case**. Commit `87f34554`.
- **TWO THINGS BLOCK PRODUCTION AND NEITHER IS MINE TO FINISH:**
  1. one `HOT_ARTIFACT_PATTERNS` line — `artifact_publisher.py` is owned by
     `clv-without-settlement`; **request filed in that lane, file NOT taken**;
  2. **no populator on the worker** — the x64 tool is manual and out-of-pipeline.
- **Effect is INCONCLUSIVE, not negative:** flat at **12.7% pitcher-slot
  coverage** (starters only). 236 bullpen arms were mid-fetch at checkpoint;
  **the re-run at near-full coverage is the owed measurement.**
- **UNVERIFIED:** production population of these fields —
  `/api/ops/artifacts/stream` **403s on `roster_objs/`**.
- **NEXT ACTION:** when the bullpen fetch finishes, rebuild the artifact
  (`build_mlb_pitch_splits_artifact.py --season 2026`) and re-run
  `measure_pitch_splits_effect.py --games 45 --sims 120`. If it is still flat at
  high coverage, **retire the research prediction that pitch-type matchup is the
  most likely market beat** before anyone builds a scheduled populator.

### soccer-layer2-dates — 2026-08-17 23:4xZ — **GOALS (a) AND (b) MET AND VERIFIED IN PRODUCTION. (c) STILL BLOCKED.** — session: soccer-layer2-dates

- Goal: soccer's Layer 2 surfaces tell the truth about WHEN a match is and WHETHER
  it is live, and soccer reaches the board with real projections.

| goal | testable outcome | state |
|---|---|---|
| (a) rail shows only today's Central date | rendered rail | **MET** — 15 cards, all today (was ~60+ across Aug 15–28) |
| (b) no chip reports `live` for a `post` match | chip feed | **MET** — 0 stale-live (was 1) |
| (c) soccer `pct_projected` materially above 0.0 | `/api/board/layer2-shortlist` | **NOT MET — 0.0** |

**(a) and (b) closed by web `e5107913`, live 22:12:38Z, measured 23:47:46Z.**
Full evidence in `deploys.md`. Soccer's 3 rail cards are today's three fixtures,
all correctly `FINAL`. No regression: mlb 11 (9 live), wnba 1; nfl 0 but nfl was
already 0 pre-deploy.

**STRAND STATUS — 4 root-caused, 4 pushed, 3 closed with measurements:**

| strand | commit | state |
|---|---|---|
| rail dates + stale-live guard | `cd46b403` | **DEPLOYED + VERIFIED** |
| live-lens `TypeError` | `6bdc50de` | **DEPLOYED + MEASURED** (7 -> 10 leagues/tick) |
| caller-census test | `18c5ecb9` | pushed |
| projection window | `6aaa11af` | deployed but **INERT** |

**THE ONE REMAINING BLOCKER — unchanged, and it is not a deploy window.**
`board_enrichment.py:678` still reads `load_soccer_projections(roots, selected_date)`
and needs the 7-day window. Until then soccer serves `rows_with_projection 4 /
8,759`, `pct_projected 0.0`, against `quote_rows 16,044`.

**THE CLAIM ON THAT FILE IS HELD BY A DEAD SESSION.** `.current-lane` markers are
the authoritative session->lane map and give
`5d731752-6d65-4308-a143-5b70d1d01fb7 -> wnba-live-tier`. That session is
**archived, not running, last active 2026-08-16T22:15:38Z** (~25h). **I earlier
chased `local_bd97b64e` ("Layer 1 Board Session") on a title+snippet inference —
that was WRONG, it does not hold this lane.** Correction logged so nobody repeats it.

**Coordinator asked, no reply.** `coordinator.id` = `9ed7fd89-…` is **CORRECT, not
stale** — `coordinator.md:162-191` documents that one session carries two ids and
this file holds the hook-payload one the roster cannot see; it is the same session
as roster `local_1d6f136e-…` "Deploy and Document Coordinator". **Do not "fix" that
file** — `deploy-guard.py:35` treats an unresolvable coordinator as the OFF switch,
so rewriting it to the roster id would silently disable the deploy guard globally.
I nearly concluded it was stale; a scheduled-task session reached the same wrong
conclusion earlier today.

**NEXT ACTION — a decision, not a task.** Either the coordinator releases
`board_enrichment.py`, or this lane takes it under a logged CLAIM OVERRIDE on the
precedent `wnba-live-tier` itself set 2026-08-16 23:2xZ against
`clamp-fix-to-workers` (owner unreachable + zero functional overlap + one function
+ trivially revertable — all four hold here, and the owner is archived rather than
merely unattended). **Awaiting explicit user or coordinator go-ahead; not taken.**

**REMAINING UNVERIFIED, deliberately:** the live lens end-to-end. Post-deploy all 10
leagues wrote `(0 live games)`, which is CORRECT — ESPN reported today's three
matches `post`. Needs a slate with a match actually in play. **Not banked.**

### soccer-layer2-dates — 2026-08-18 00:4xZ — LAYER 2 WIRING SUITE REPAIRED (6 failures -> 0), ONE OF THEM A PRODUCTION BUG — session: soccer-layer2-dates

Picked up while verifying the soccer test repair; `lanes.md:206` already recorded
this file as "found and PARTLY fixed on the way, handed on", so it was known-broken
and unowned rather than actively held.

**`9e052dfe` — `test_layer2_soccer_window.py` patched a function production stopped
calling.** `#435` renamed the read to `read_book_quotes_latest`; the test patched
`read_book_quotes`, which still exists, so the patch bound to nothing. Measured: 0
interceptions on the old name, 7 on the new. Two tests failed; a third PASSED
VACUOUSLY (`assert quote_rows == 0` is trivially true when the read is never
intercepted). `raising=False` was the silencer and is gone. Added
`test_the_patched_name_is_the_one_production_calls`.

**`ec8c3beb` — 5 calendar failures + 1 REAL PRODUCTION BUG.**
- Calendar: `_quote()` pinned `snapshot_ts` at 2026-08-08T19:55Z; `book_age_seconds`
  derives from it against the wall clock (9.2 days) against
  `opportunity_gate.PREGAME_MARKET_MAX_AGE_SECONDS` = 86,400. Every row died as
  `pregame_market_stale` BEFORE any shortlist filter, which is why
  `opportunities_considered` was 0 with all seven exclusion counters at 0. **Fourth
  time this file broke on the calendar** — `_no_quality_floor` pins four env floors,
  but the gate's ceiling is a constant in a DIFFERENT module with no env override.
  Fixed at source: `snapshot_ts` is now relative to now, so no age ceiling present
  or future can age these rows out.
- **Production:** `#379`'s per-date `except: continue` swallowed shard read errors,
  absorbing the exception that used to reach the whole-sport handler
  (`layer2_shortlist.py:387`). A sport whose shard raised on EVERY window date
  reported `quote_rows: 0, grid_rows: 0` and no error — identical to a sport with no
  slate. Now emits `error` + per-date `read_errors` on BOTH branches, including the
  success branch (a window losing 3 of 7 dates still serves a partial board, which
  is the more dangerous case and had no test). Verified by construction: 2 of 7
  soccer dates raising still yields `quote_rows: 6`, `rows: 2`, with `error` naming
  both failed dates. Resilience unchanged —
  `test_one_unreadable_date_does_not_lose_the_others` still passes.

**Verified:** 21 passed across both suites; 113 passed across seven Layer 2 suites.

**Learnings entry appended** — four defects this session shared one shape: the error
path rendered as the system's own "nothing here". The discriminator was a RATIO in
every case (7/10 leagues, 0/7 interceptions, 0 rows/7 dates asked) and nobody was
printing the denominator.

**STILL NOT FIXED, one line, named for whoever wants it:** soccer's live-lens memory
gate at `live_lens_loop.py:524-530` returns silently where MLB and WNBA both print
`[LIVE_LENS_TICK_DIAG]`. It is defect #2 of the four and the only one still open.

### soccer-layer2-dates — 2026-08-18 01:0xZ — SILENT GATE FIXED (`481de91d`). 3 of the 4 silent-handler defects now closed. — session: soccer-layer2-dates

Defect #2 of the four in today's learnings entry. `live_lens_loop.py:523-553`:
soccer's headroom gate returned bare where MLB and WNBA both print
`[LIVE_LENS_TICK_DIAG] ... reason=low_headroom`. All three now print.

**Verified both directions, not from the diff:**

    gate trips  -> line emitted, meta {'ok': False, 'skipped': True, 'reason': 'low_headroom'}
    gate passes -> 0 lines,      meta {'ok': True,  'skipped': None,  'reason': None}

The negative case is deliberate — a diagnostic that fires when nothing is wrong is
the next session's false lead. 48 tests pass across four live-lens loop suites; meta
is unchanged, control flow untouched.

**WORTH KNOWING FOR THE NEXT DIAGNOSIS:** this gate is ENABLED in production.
`SYNDICATE_SOCCER_LIVE_LENS_MEMORY_GATE_ENABLED` is ABSENT on all three services and
absent means ON (`_env_bool(default=True)`) at a 300MB floor. It was NOT tripping on
2026-08-17 — that is measured and stays exonerated — but it is armed, and until this
commit deploys a trip is still invisible.

**STILL OPEN — the last silent handler, and the one that actually hid the outage:**
`scripts/poll_soccer_live_state.py:210` catches each league's exception into an
`errors` dict with no log line; that dict reaches only
`data/live/soccer_live_lens.json`, which is NOT in the publisher allowlist. **The
user said 2026-08-17 they were adding this print; it is not in the tree** (checked
at 01:0xZ, line 210 is still a bare `errors[league] = ...` + `continue`). I reverted
my version at the time to avoid two competing edits. Not re-taken without a word —
flagging that it did not land.

**UNDEPLOYED:** `481de91d` is worker-side and needs a live-odds-worker (and possibly
refresh-worker — `SYNDICATE_ENABLE_LIVE_LENS_LOOP` is true on BOTH) deploy to have
any effect. Not urgent: it changes no behaviour, only what a trip looks like.

#### convergence-phase7-crps — CHECKPOINT 5 (FINAL) 2026-08-18 — **26 unfed inputs -> 5, a mandatory engine standard, and still no edge**

- **The durable win is the STANDARD, not the wiring.**
  `docs/ai_context/model_engine_standard.md` (mandatory via `CLAUDE.md`) +
  `scripts/sim_input_checklist.py` (gates at exit 1) mean the next engine cannot
  ship 26 silently-unfed fields.
- **26 -> 5 consumed-but-unfed**, via pitch splits, batter+pitcher batted-ball,
  and a BVP cache fix. The 5 remaining have known causes; 2 have **no producer at
  all** and need a definition before they can be fed.
- **Effect vs market: mean +0.0014, market still wins all four.** Plumbing, not
  an edge. **Nothing deployed and nothing should be** until the refit closes a
  gap.
- **Refit found `k_rate` is not the lever for strikeouts** — a 1.32x correction
  moved simulated K by 0.0005. Those corrections must not ship.
- **Five of my own claims corrected by measurement this stretch**, four of them
  on BVP alone, each from grepping the wrong file. The provenance table exists so
  the next person does not repeat it.
- **Owed:** production population is UNVERIFIED (403 on `roster_objs/`); route is
  `--publish` on the worker. `k_rate` lever unknown. Two fields undefined.
- **NEXT ACTION:** decide whether `statcast_quality_mult` has a meaning worth
  defining, or excuse it in `EXPECTED_SPARSE` so the gate can pass honestly.

### soccer-layer2-dates — CHECKPOINT 2026-08-18 01:1xZ — **ALL THREE GOALS MET AND VERIFIED IN PRODUCTION. Two observability commits UNPUSHED. One end-to-end proof still owed.** — session: soccer-layer2-dates

| goal | outcome | state |
|---|---|---|
| (a) rail shows only today's Central date | rendered rail 15 cards, all today (was ~60 across 08-15..08-28) | **MET** |
| (b) no chip reports `live` for a `post` match | 0 stale-live (was 1) | **MET** |
| (c) soccer `pct_projected` materially above 0.0 | **0.0 -> 53.8**, 4 -> 4,738/8,808 rows, 3 -> 99 matches, 4 -> 9 leagues | **MET** |

**(c) WAS SHIPPED BY ANOTHER SESSION** (`b4d82364`, web `678e2f25` 00:29:52Z), not by
this lane. My byte-identical `1d36d2c1` was dropped from local main via `reset
--soft` + path-scoped unstage (plain `--mixed`/`--hard` would have destroyed three
lanes' work).

**READ THIS BEFORE CITING 53.8%:** at the same instant `active_sports` was
`["mlb","nfl","wnba"]` and **soccer selected rows = 0**. That is GRID coverage, not
board presence, and soccer's absence from the board remains INTENDED (decision 7).
The join is fixed; the board decision is untouched.

**COMMITS**

| commit | scope | state |
|---|---|---|
| `cd46b403` | rail dates + stale-live guard | on origin/main, **DEPLOYED + VERIFIED** |
| `6bdc50de` | live-lens `as_of` TypeError | on origin/main, **DEPLOYED + MEASURED** (7 -> 10 leagues/tick) |
| `6aaa11af` `18c5ecb9` `9e052dfe` `ec8c3beb` | loader window, caller census, test repair, shard-error reporting | on origin/main |
| `481de91d` | soccer headroom gate prints its skip | **UNPUSHED, UNDEPLOYED** |
| `461774cb` | poller prints each league's failure + traceback | **UNPUSHED, UNDEPLOYED** |

Both unpushed commits are observability-only — no behaviour change, so they can ride
along with any worker deploy rather than justifying a window. **`main` is 4 ahead /
238 behind `origin/main`, and 2 of the 4 ahead are OTHER sessions' commits.**

**THE ONE THING STILL OWED: the live lens is UNVERIFIED END-TO-END.** `6bdc50de`'s
primary criterion is measured, but every league wrote `(0 live games)` because ESPN
reported all three of 08-17's matches `post`. **A league with nothing in play writing
`(0 live games)` is CORRECT and must not be read as the fix failing.** Needs a slate
with a match actually in play. Not banked.

**NEXT ACTION:** on the next slate with a soccer match in play, confirm at least one
of la_liga / primeira_liga / championship writes `count > 0` and
`/soccer/<league>/api/live-lens` leaves `Live matches: 0 / Source: No data`. Push
`481de91d` + `461774cb` whenever a worker deploy is going out anyway.

**DEAD ENDS — do not repeat.** Filing a deploy request for (c) — already live, caught
only by re-reading the baseline. Taking a claim override on `board_enrichment.py:678`
— the change was already written. Chasing `local_bd97b64e` for `wnba-live-tier` — the
owner is `5d731752`, archived since 08-16T22:15Z. Treating `coordinator.id` as stale
— it is correct, and rewriting it disables the deploy guard globally.

#### convergence-phase7-crps — CHECKPOINT 6 (FINAL) 2026-08-18 — **inputs 26 -> 0 fed, gap to market closed 32%, still no edge, K deficit characterised not fixed**

- **Checklist PASSES.** Every consumed field is fed, via arsenal + quality +
  batted-ball + BVP. The arsenal leaderboards replaced a 309-call pipeline with
  two calls and cover both sides of the matchup.
- **Fully fed vs market: 4 of 4 better, 32% of the gap closed, `runs` regression
  fixed.** Mean improvement +0.00478. **The market still wins all four. No edge.**
- **K deficit diagnosed and DELIBERATELY NOT FIXED** — two opposing errors of
  almost equal size; fixing the mix alone trades a 27% shortfall for a 26%
  surplus. Values reverted, diagnosis in the code.
- **Refit:** only `hr_rate`/`inplay_hit_rate` corrections are shippable.
  `k_rate`/`bb_rate` are fitted against quantities they cannot move.
- **Four more of my claims corrected by measurement** this stretch, including two
  "unfixable" fields that the provider's leaderboards fill outright.
- **NEXT ACTION:** joint calibration of the pitch mix AND the strike->K
  conversion, scored on `measure_all_inputs_effect.py` rather than the league mix.
  That is the largest remaining modelling defect and the only one big enough to
  matter against a 0.0073 market gap.

#### convergence-phase7-crps — CHECKPOINT 7 (FINAL) 2026-08-18 — **the 0-0 cell fixed exactly, and the market did not care**

Commits `c6da673f`, `306a84a9`, `d8bf0b04`. **One engine change in the tree. No
deploy. Lane stays OPEN.**

**The chain, in the order it actually happened**

1. **Joint calibration FAILED and the failure was informative.** Grid over mix +
   two-strike terms: best K/PA **0.2559 vs target 0.226**, pitches/PA 3.55 vs
   3.90. `two_strike_foul_boost` saturates — it drags FOUL to 21.7% before K
   closes. **Target unreachable within these parameters.** Nothing shipped.
2. **Arithmetic, not search, located the residual.** Sim in-play PA share 0.639
   vs MLB 0.679 **while the per-pitch in-play rate is CORRECT (16.7% vs 17%)**.
   Right per-pitch rate + wrong PA share ⇒ the error is in **count progression**.
3. **Measured it instead of fitting it** (user's call: "worth thinking about is
   PBP data"). `scripts/measure_count_progression.py`, **895,320 real statcast
   pitches**, real-vs-sim outcome matrix by count.
4. **The 0-0 cell is the defect.** Real CALLED **29.6%** / IN_PLAY **11.3%**;
   sim **13.7%** / **25.9%**. *The sim swings at the first pitch; real hitters
   take it.* Same shape at both ends — 0-2 real pitchers WASTE (45.5% ball vs
   29.9%), 3-2 real hitters PROTECT (29.2% foul vs 18.7%).
5. **`first_pitch_swing_damp = 0.42`, `first_pitch_called_boost = 1.60`**,
   applied at 0-0 only, before normalisation. **NOT the same shape as
   `three_ball_take_bias`**, which only adds to `p_ball`.

**RESULT — fixes the cell exactly, no overshoot**

    0-0 called   13.7% -> 29.6%   (real 29.6%)
    0-0 take     46.9% -> 71.0%   (real 68.0%)
    0-0 in-play  25.9% -> 15.0%   (real 11.3%)
    K/PA        0.1609 -> 0.1852  (real 0.226)
    pitches/PA    2.96 -> 3.25    (real 3.90)

**AND THE MARKET IS UNMOVED** — same 2,415 rows: hits −0.00399, rbis +0.00370,
runs −0.00153, tb +0.00129. **2 better / 2 worse, mean −0.00013.** Gap
0.00732 -> 0.00719.

**KEPT — and this is a JUDGEMENT CALL against the lane's own standing rule.**
The rule is that the market is the arbiter. I kept a market-neutral change
because a correct count structure is a **precondition** for calibrating anything
above it (step 1 failed precisely because it fitted on a broken one), and neutral
is not harmful. **Anyone who disagrees sets both to `1.0` — exact no-op, nothing
else to change.** 9 tests pass.

**STILL WRONG:** `base_in_play` 0.23 vs ~0.17; the 0-2 waste cell; the 3-2
protect cell. **K/PA 18% low, pitches/PA 17% short. The first pitch was the
largest single cell, not the whole defect.**

**Unchanged obligations:** production population still UNVERIFIED (403 on
`roster_objs/`; route is `sim_input_checklist.py --publish` on the worker). Two
deploy requests remain queued and de-prioritised by me — monotone seal
`bafb4fb2`, ownership gate `20025cc4`.

#### convergence-phase7-crps — HYPOTHESIS RECORDED BEFORE TESTING 2026-08-18 — **pitch mix is unconditional; the user's per-player/per-count/per-hand model is the missing conditioning**

**THE GAP, verified in code (not grepped for absence):** both pitch-selection
sites draw from ONE distribution —

    simulate.py:1066  pitch_type = _weighted_choice(rng, pitcher.arsenal, PitchType.FF)
    simulate.py:2803  pitch_type = _sample_weight_cdf(rng, pitch_types, pitch_cdf, ...)

`PitcherProfile.arsenal` (models.py:318) is `Dict[PitchType, float]` — **a single
season-long usage vector. Not conditioned on count. Not conditioned on batter
handedness.** The batter side IS now fed (`vs_pitch_type`, `vs_pitch_type_hr`
from the arsenal artifact) — so the engine already knows a hitter's BA by pitch
type, and applies it against **the wrong mix**.

**HYPOTHESIS (recorded before measuring):** the two count cells left broken after
`d8bf0b04` are MIX effects, not outcome-probability effects.
- **0-2 waste cell** (real 45.5% ball vs sim 29.9%): real pitchers throw
  **breaking balls out of the zone** at 0-2. The sim throws its season mix.
- **3-2 protect cell** (real 29.2% foul vs sim 18.7%): real pitchers go
  **fastball in the zone** at 3-2 and hitters protect.
If true, `base_in_play` 0.23-vs-0.17 is partly the same artefact — a season mix
applied uniformly over counts.

**WHY THIS MAY SUCCEED WHERE `d8bf0b04` WAS MARKET-NEUTRAL** (and this is the
part to hold myself to): the first-pitch term is a **league-wide constant** — it
moves every hitter and pitcher identically, which is exactly the kind of
correction a market has already priced. **Count/hand-conditional mix is
PLAYER-SPECIFIC**: it changes WHICH `vs_pitch_type` multiplier applies to WHICH
matchup. A slider-heavy reliever vs a slider-weak hitter with two strikes is a
matchup the season mix cannot express. **That is a differential edge or it is
nothing.**

**FALSIFIABLE:** if conditional mix moves the market no more than the league
constant did, the player-specific argument is wrong and I will say so.

**MEASURABLE — same corpus, no new source.** `vendor/mlb_bettingv2/data/raw/
statcast/pitches/*/*.csv.gz`, 62 files, ~895k pitches, all six required columns
present and verified: `pitch_type balls strikes stand p_throws pitcher batter`.

#### convergence-phase7-crps — MEASURED 2026-08-18 — **hypothesis CONFIRMED: conditional mix is 55-86% PER-PITCHER, not a league constant**

`scripts/measure_pitch_mix_conditioning.py`, **1,472,453 pitches, 1,297
pitchers.** Two measurements, the second one decisive.

**1. The league pattern is real and large.**

    count      n        FB     BR     OS     TVD vs season
    ALL    1,472,453   55.2%  30.6%  14.1%     ---
    3-0       15,596   94.5%   4.1%   1.4%    0.4165
    3-1       31,960   77.7%  15.8%   6.5%    0.2245
    0-2       99,361   42.5%  39.1%  18.4%    0.1370
    1-2      143,361   43.4%  37.7%  18.9%    0.1189

    LHP vs LHB  57.5% FB / 38.8% BR / **3.8% OS**   TVD 0.2106

3-0 is 94.5% fastball against a 55.2% season mix. **The engine throws the season
mix in a 3-0 count.** Lefty-on-lefty, the changeup essentially vanishes (14.1% ->
3.8%) and the engine still throws it.

**2. THE DECISIVE ONE — a single global count rule does NOT recover it.** For
each pitcher/count cell, his true conditional mix vs (a) his own season vector
[what the engine has] and (b) his season vector tilted by the LEAGUE count shift
[the best a global rule can do]:

    count   cells   (a) own season   (b) + league tilt   explained by league
    0-2      495       0.2047            0.1284               37.3%
    1-2      565       0.1717            0.1133               34.0%
    2-0      305       0.2144            0.1465               31.7%
    3-2      432       0.1422            0.1226               13.8%
    0-0      708       0.1043            0.0771               26.1%

**A global count rule removes only 14-45% (median ~30%) of the deviation.
55-86% is irreducibly PER-PITCHER.** At 0-2 the residual is still TVD 0.128 —
**12.8 points of probability mass** that no league-wide correction can reach.

**THIS IS THE DISTINCTION THAT MATTERS vs `d8bf0b04`.** The first-pitch take term
was a league constant and came back market-neutral — consistent with "already
priced". Conditional mix is **majority per-pitcher**, so it changes WHICH
`vs_pitch_type` multiplier lands on WHICH matchup. That is differential
information; the earlier null does not predict this one.

**Sample-size constraint, stated before building:** 1.47M pitches / 1,297
pitchers ~ 1,135 each. A full count x hand cross is 24 cells ~ **47 pitches per
cell — too thin to use raw.** The build must be **empirical-Bayes shrinkage
toward (own season mix x league cell tilt)**, weighted by cell sample. Using raw
per-pitcher cells would fit noise and is FORBIDDEN here. Count buckets should be
cut by measured TVD similarity, not by intuition.

**Still unfalsified, not yet proven:** that this moves the MARKET. Same standard
as everything else in this lane — the scoreboard decides, not the TVD.

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

### soccer-model-dispersion — CHECKPOINT 2026-08-18 03:5xZ — hypothesis SHARPENED, not yet tested: the model is unfed, not merely under-dispersed — session: soccer-sport-owner

**The falsification test in this lane's charter ran and came back NO.** Sim count
cannot close the gap: deterministic seeding makes ±2.9pp a binomial SE, worth ~6% of
the +0.0139 gap. Recorded as a real outcome, not retried with a bigger knob.

**What replaced it.** `scripts/soccer_sim_input_checklist.py` (new, `6ecc8f70`,
pushed) found **20 of 20 engine read sites unfed** — worse than the MLB audit that
produced the standard. That is a mechanism for under-dispersion: a model given four
rating floats and neutral defaults for everything else has nothing to be confident
with, so it regresses to the middle (0.1575 vs market 0.1811).

**Shipped (`1834dd50`, UNPUSHED):** xG + PPDA wired, per-side lookup added to the
engine, 4 reachability tests, checklist aligned to the engine. **20 -> 17 alarms.**
Proven to reach published artifacts by a real A/B build (0.40 -> 0.48 home win).

**NEXT — and the order matters:**
1. **Push `1834dd50`.** Nothing is deployed. Worker/web unaffected until it is.
2. **Before sourcing any new data, check each of the 17 for a MISROUTED PRODUCER.**
   xG turned out to be computed, correct, and filed where the engine could not read
   it. Assume nothing about the other 16 until checked the same way.
3. Only then acquire: shots, big chances, clean sheets, possession share,
   set-piece xG, corners, availability, form.
4. **Re-run the backtest LAST**, once inputs are fed — it is **~22 hours** for the
   1,112-match control at 300 sims and the same match set is the only valid control.

**DO NOT REPEAT:** "no leak-free soccer backtest exists" — that was mine and it is
wrong; one exists (`5a94b134`) and says the model loses 0.5875 vs 0.5737.

### soccer-model-dispersion — CHECKPOINT 2026-08-18 05:0xZ — inputs 20 -> 11 alarms, ALL PUSHED; the charter goal is still UNTESTED — session: soccer-sport-owner

**Shipped and on `origin/main` (`47e583ba`):** `6ecc8f70` (the gate), `1834dd50`
(xG + PPDA + per-side engine lookup + 4 reachability tests), `00475bce` (history
converter + gate now reads real history). **0 ahead / 261 behind; nothing of mine is
uncommitted.**

| | |
|---|---|
| checklist alarms | 20 -> **11** |
| fields closed with NO new data | **9 of 9** |
| reachability | proven per-side, both commits |
| published artifacts | proven for xG only (`0.40 -> 0.48`), NOT re-run after `00475bce` |
| model skill | **UNMEASURED** |
| deployed | **nothing** |

**THE CHARTER GOAL IS UNTESTED.** "Model Brier <= market on one non-belgian league,
over the SAME 1,112 matches" has not been attempted. The inputs changed; whether that
closes the +0.0139 gap is exactly the open question. **Do not infer skill from the
alarm count.**

**NEXT, in order:**
1. **Re-run the A/B artifact build** to prove the nine converter fields reach
   published output. `/tmp/ab.py` pattern: two `build_artifacts` runs, same
   fixture/date/seed/sims, ratings stripped vs full. ~2 min for a 1-fixture slate.
2. **Then the backtest** — `backtest_soccer_h2h_calibration.py --all --limit 120
   --simulations 300`, **~22 hours**, same match set as the 08-15 baseline in
   `reports/soccer_backtest/h2h_calibration_2026-08-15_limit120_n1112.json`.
   A gap that improves on a DIFFERENT match set proves nothing.
3. Only then consider sourcing the four genuinely-missing fields.

**DO NOT RE-RUN:** sim count as the lever (falsified, ~6% of the gap, deterministic
seed). "No leak-free backtest exists" (wrong, `5a94b134` has one).

### soccer-model-dispersion — CHECKPOINT 2026-08-18 05:3xZ — inputs done and pushed; a self-inflicted double-count found and fixed; the charter goal is STILL UNTESTED — session: soccer-sport-owner

**All four commits on `origin/main` (`f5650ef2`). 0 ahead / 262 behind; nothing of
mine uncommitted, unstaged or unpushed.**

| commit | what |
|---|---|
| `6ecc8f70` | the gating checklist (now reads real history, cannot drift) |
| `1834dd50` | xG + PPDA, per-side engine lookup, 4 reachability tests |
| `00475bce` | history converter forwards 9 discarded columns |
| `2d47a607` | **fixes a double-count I introduced in `00475bce`** + mutation-verified invariant test |

    alarms: 20 -> 17 -> 11 -> 13     (13 is the BETTER number; see below)

**I SHIPPED A DEFECT AND THE CHECKPOINT CALLED IT VERIFIED.** `goals_for` duplicated
`xg_for` on the goals-as-xG path, weighting goals 0.36 instead of 0.22. It passed the
checklist, 4 reachability tests, `off != on`, 31 unit tests AND an end-to-end artifact
diff — every one correctly, because the field really was consumed, populated and
reachable. Caught by `total_mean 3.39` looking implausible for eredivisie. Full
writeup in `learnings.md` 2026-08-18.

**11 -> 13 IS PROGRESS.** `goals_per_match` / `goals_against_per_match` are honest
alarms again rather than silently satisfied by a duplicate.

**NEXT, in order — and (1) is now mandatory, not optional:**
1. **RE-FIT, or at least re-read, `_attack_strength`'s weights.** Its constants were
   fitted when every term but the ratings was absent. Seven terms now feed it. CLAUDE.md
   measured a NEGATIVE interaction from two mechanisms in 4 of 4 MLB markets; soccer
   has seven and no re-fit. **The backtest may get WORSE, and that would be the
   weights, not the inputs.**
2. **Then the backtest** — `--all --limit 120 --simulations 300`, **~22 hours**, same
   1,112-match control as `reports/soccer_backtest/h2h_calibration_2026-08-15_limit120_n1112.json`.
3. Only then source the four genuinely-missing fields — each carrying the same
   re-fit hazard.

**DO NOT RE-RUN:** sim count as the lever (falsified, ~6%). "No leak-free backtest
exists" (wrong, `5a94b134`).

### soccer-model-dispersion — FINDING 2026-08-18 05:4xZ — **xG IS 82% OF THE ATTACK INDEX, THROUGH TWO ROUTES. The weights are wrong before the backtest runs.** — session: soccer-sport-owner

**Measured on eredivisie: 22 rated teams, 918 matches.** This predates tonight's
work and is a structural double-count one level above the one `2d47a607` fixed.

    attack_index = (metrics_index + fallback_attack) / 2

      metrics_index   = 0.5 + xg_term(0.22) + shots(0.016) + form(0.06) + ...
      fallback_attack = 0.5 + attack_rating

`attack_rating` IS xG: `(xg_for/league_mean - 1) * scale`.
**`corr(attack_rating, xg_for) = +0.984`.** So xG enters BOTH halves of the average.

| | spread across 22 teams |
|---|---|
| combined `attack_index` | 0.6728 |
| **xG-derived portion** | **0.5546 = 82%** |
| shots (nominally independent) | 0.1813 |
| form | 0.1071 |

**SHOTS IS NOT INDEPENDENT EITHER: `corr(xg_for, shots) = +0.895`.** Its 0.016 weight
adds correlated evidence, not new information.

**WHY THIS PREDICTS THE BACKTEST GETS WORSE, NOT BETTER.** The measured defect is
UNDER-DISPERSION — model stdev 0.1575 vs market 0.1811, too timid. Feeding correlated
signals raises CONFIDENCE without adding INFORMATION: the spread moves the right way
for the wrong reason, and calibration degrades. **If the backtest comes back worse,
read the weights first, not the inputs.** This is CLAUDE.md's measured negative
interaction (2 mechanisms, 4 of 4 MLB markets) with seven terms and no re-fit.

**THE DECISION THIS FORCES — a modelling call, deliberately NOT guessed:**
either (a) drop the xg term from `_attack_strength` because `attack_rating` already
carries it, or (b) stop averaging with `fallback_attack` when metrics are present.
Both are plausible; picking wrong makes it worse. **Do not run the 22-hour backtest
before this is decided** — it would measure the blend, not the inputs.

**SCOPE LIMIT, stated because it is one league:** eredivisie only. The correlations
are strong enough that other leagues are unlikely to differ, but **UNCHECKED**.

**Clamp binds on 1 of 22 teams** — not saturating, so this is a weighting problem
rather than a range problem.
