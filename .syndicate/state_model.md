# state — model

Split out of `state.md` by `scripts/split_state.py`. Bodies are verbatim.
The INDEX of every subject, across every part, is in `state.md`; the
one-subject-one-section rule is global and spans these files.
Same rules as state.md: when a fact changes, EDIT THE LINE.

## [ledger-and-primary-tree] — MEASURED 2026-09-02, this machine

**The primary shared tree is at `origin/main` (`a44dd4bf`), 0 behind / 0 ahead**
— first parity in 139 commits. Verified by `merge-base --is-ancestor`, not by
reading the log.

- **`LEDGER OVER BUDGET` in the session digest can be a STALE CHECKOUT.**
  `session-start.sh` stats `.syndicate/*` in whatever tree you started in. On
  2026-09-02 it reported `lanes.md 246KB>234KB, learnings.md 286KB>273KB` while
  `origin/main` held 148KB and 270KB, both under cap. **Read
  `git show origin/main:<path> | wc -c` before acting on that warning.**
- **learnings.md cap RAISED 280,000 -> 400,000** in `.claude/hooks/session-start.sh`.
  The old "+15% headroom" was consumed in under a day (240,442 -> 278,051,
  ~3KB/hour). Sizing rule now: the compacted floor plus the UNCOMPACTABLE
  WORKING SET, because `compact_learnings.py` compacts strictly BEFORE its
  cutoff, so one to two days of rules are never compactable.
- **Current, at `origin/main`:** state 89%, lanes 62%, learnings 72% of cap.
- **The trim tools' printed `cap 120000` is a REPORTING DEFAULT** (`--cap`), not
  the enforced budget. They will say `*** STILL OVER ***` on a file that is
  comfortably under the real cap. Do not act on that line.
- **Merging a stale branch RESURRECTS archived lane blocks** — 19 of them here,
  auto-merged with no conflict. Re-run `trim_lane_blocks.py --apply` after any
  such merge and check for lanes with two blocks. Rule in `learnings.md`.
- **THE `cap 120000` TRAP FIRED AGAIN, on the session that wrote the line above
  `[2026-09-02]`.** A session quoted `lanes.md` as "173% of cap" and then "1.26x
  over", and used that to justify two trim passes. The enforced budget is
  `session-start.sh:270` — **`lanes.md:240000`, `state.md:750000`,
  `learnings.md:400000`**. At its worst that day the file was **183,062 B = 76%
  of its real cap**, and no digest ever emitted `LEDGER OVER BUDGET`. The trim
  was still worth running — 14 blocks were genuinely duplicated across
  `lanes.md` and `lanes_history.md` — but the STATED reason was wrong twice.
  **Read the threshold from the ENFORCER (`session-start.sh`), never from the
  reporter.**

## [ledger-precommit-guard] LEDGER COMMITS ARE GUARDED AT TWO LEVELS — VERIFIED 2026-09-02

**A stale-tree ledger commit is now refused by git itself**, not only by the
PreToolUse hook. `376bfa94` — a kalshi CODE commit carrying a ~90-commit-stale
`lanes.md` — reverted a trim pass eight minutes after it landed. Both existing
predicates passed, correctly: the commit ADDED blocks, and **a deletion is
invisible to any predicate that looks only at what is present.**

- **The predicate:** a block VERBATIM in upstream `lanes_history.md` and absent
  from upstream `lanes.md` is being un-archived — which only happens when the
  committing tree is behind. `resurrected_blocks()` in
  `.claude/hooks/ledger_invariants.py`; BOTH guards import it, never restate it.
- **What it deliberately does NOT use**, both measured against the live ledger
  first and both would have blocked honest work: **SAME SLUG** (36 slugs live in
  both files — history holds SUPERSEDED blocks of lanes still alive, 18 of them
  OPEN) and **SAME HEADER** (24 match where only 14 bodies do).
- **`core.hooksPath = .githooks`**, set on this clone — one setting, all 48
  worktrees. `.githooks/pre-commit` + `.githooks/ledger_precommit.py`;
  `scripts/install_git_hooks.py --apply` installs it and REFUSES if `.git/hooks`
  holds real hooks, which `core.hooksPath` would silently disable.
- **It reads `git show :<path>`**, which resolves against `GIT_INDEX_FILE` — the
  TEMPORARY index of a `git commit -- <pathspec>`, the exact shape that clobbered.
- **FAILS OPEN in every direction.** No python, no checker, a crash, an
  unreadable index — all exit 0. Only an explicit exit 1 blocks.
- **IT INSTALLED INERT.** Worktrees sit at many commits, so the checker meets OLD
  `ledger_invariants.py` whose `violations()` takes `(rel, text)`; the 3-arg call
  raised `TypeError` and the blanket `except` swallowed it. Now degrades to the
  2-arg call — measured in the primary tree, **0 violations before, 2 after.**
- **COVERAGE IS PARTIAL and fills in as trees update.** A worktree without
  `.githooks/` runs no hook at all; one with an old `ledger_invariants.py` gets
  only the two original predicates. `--no-verify` and
  `SYNDICATE_ALLOW_LEDGER_COMMIT=1` bypass by design — this is a guardrail, not
  an enforcement boundary.
- **Prior art:** `[ledger-and-primary-tree]` already recorded that merging a
  stale branch resurrects archived blocks (19 of them). Its remedy was MANUAL;
  this makes refusal automatic.

## [replay-diff-gate] A PRODUCTION DAY NOW REPRODUCES OFFLINE, 0 MISMATCHES — and two board blocks provably CANNOT `[verified 2026-09-02, lane m625-replay-diff-gate, commits d8caea14 + 9dad0881, NO DEPLOY]`

`py -3 scripts/replay_diff_gate.py --date 2026-09-01` -> **PASS**, mirror
manifest `8d5c42ba8cb18c34`, against production's own `book_grid_2026-09-01.json`:
**280,840 leaves exact, 58,335 clock-derived fields within 0.1s of one shared
3.6s offset, 0 mismatches**, 0 outbound attempts. Runs the REAL
`run_refresh_worker:_run_book_grid_artifact_tick`. Re-verified from a CLEAN
CHECKOUT of `origin/main` after pushing. Full evidence:
`.syndicate/findings_2026-09-02_m625_replay_diff_gate.md`.

- **THE GATE HAS BEEN OBSERVED TO FAIL.** `--perturb` drops ONE line from the
  163 MB tick tape; it fails on exactly 8 fields.
- **NO_FIXTURE IS NOT A PASS.** `migration_gate.py --replay-date <D>` prints
  `Replay-diff: UNKNOWN`; its `ok` uses `is not False`. `--require-replay` makes
  the unknown case fail.
- **RUNNING A WORKER TICK LOCALLY CAN WRITE TO PRODUCTION.** The tick calls
  `publish_hot_artifact` (`run_refresh_worker.py:4753`), an HTTP POST onto web's
  disk. Anyone replaying a worker entrypoint with a live `ADMIN_TOKEN` pushes a
  locally-built artifact into production. The gate strips credentials AND denies
  every socket; the credential strip is what actually fired
  (`SKIP_NOT_CONFIGURED url_set=False token_set=False`).
- **PICK THE REPLAY DAY BY ITS PRODUCER COMMIT.** refresh-worker took **465
  successful deploys in 21 days**; of nine consecutive MLB dates only
  **2026-09-01** was built by `e4a471c0`. Replaying 2026-08-29 emitted
  `by_quote_age`/`fresh_quotes_only`, fields production's artifact does not have
  — the diff was measuring code drift, not correctness.
- **THE CLOCK IS AN INPUT.** Frozen to production's own `generated_at`, which
  then matches to the microsecond and is left CHECKED as the assertion the
  freeze took. One constant 3.6s residual, production stamping after the pivot.
- **TWO BOARD BLOCKS ARE NOT VERIFIABLE OFFLINE BY ANY TOOL, and this is an
  artifact-design gap, not a harness limit.** `data_root()/live/mlb_live_lens.json`
  is **NON-DATED and mutable** — no historical value exists — and web's disk
  holds **zero** files matching `live/*` (two reads 45 min apart) though the
  pattern IS allowlisted (`artifact_publisher.py:885`). It is the single cause
  of every remaining difference: **167 of 167** rows whose `projection` differs
  read `game.state = live` where production reads `pregame`, matching
  production's own `transitions: {"live->pregame": 229}`. Likewise
  `game_state.chips` needs D+1's slate while D's grid is built DURING D+1
  (`D+1 settled first` FALSE on **9 of 9** dates). **Until the live-lens
  snapshot is DATED or archived per tick, the board's live-state correction —
  229 rows on that day — cannot be checked after the fact.**
- **ONE `names_only=1` CALL INVENTORIES THE WHOLE HOT SET: 33,221 files /
  13.97 GB in 13.0s**, 2.8 MB of JSON, no file opened (`ops.py:2239-2260`). And
  a narrow `pattern=` costs EXACTLY the same as none — the handler globs all 168
  patterns first and filters after (`ops.py:2240-2248`). Take one inventory and
  filter locally; ten per-family queries are ten full walks.
- Mirror root: `SYNDICATE_MIRROR_ROOT`, refused inside the git tree or under
  OneDrive. `mirror_manifest.py` claims only transfer integrity plus a local
  sha256 — `names_only` returns no hash and no endpoint does, so it is NOT a
  claim that production's bytes equal ours.

## [lane-ledger-conflict-guard] THE LANE CHECKER USED TO PASS A FILE WITH CONFLICT MARKERS IN IT `[fixed 2026-08-30, `10f45a0c`; scope MEASURED 2026-08-31T02:5xZ]`

MEASURED: `.syndicate/lanes.md` sat `UU` in the shared tree from an unfinished
stash pop — markers at 3724/3778/3966 — and `scripts/check_lane_invariants.py`
printed **INVARIANTS HOLD**. It parsed BOTH sides as real lanes, so one lane
existed twice and read as two legitimate blocks rather than as corruption.

**Why that was worse than no check:** this is the script a session runs BEFORE
committing the ledger, so its green is the reassurance that precedes writing the
damage in. Three OPEN lanes (`venue-first-market-universe`,
`exchange-join-refusals`, `ncaaf-market-basis-picks`) existed ONLY on the stashed
side — zero copies in HEAD, zero in `origin/main`. Resolving the other way would
have dropped them to zero copies anywhere.

**Now:** any line starting `<<<<<<< ` or `>>>>>>> ` is refused BEFORE parsing,
with exit code **3** and every marker line named. A conflicted file is not a
ledger with violations, it is two files, so every downstream count is
meaningless — "cannot be checked" is a distinct answer from "failed".
`=======` is deliberately NOT a trigger: a markdown setext H1 underline is a run
of `=` on its own line. Verified both ways — the live 54-lane ledger still exits
0; a conflict spliced at line 3725 exits 3.

**THE OUTCOME WAS FINE AND THE TRIGGER IS STILL UNKNOWN.** The conflict was
resolved correctly by someone (strict union: `+153/-0` vs `origin/main`, all
four lanes once). But `stash@{0} "autostash"` was created 2026-08-29T16:24Z and
nothing explains what made it or what popped it — `rebase.autoStash` and
`merge.autoStash` are both UNSET repo-wide. It can recur.

**Do not trust `.syndicate/lanes.md.CONFLICTED.bak`** — measured 0 markers, 54
headings, all four lanes once. It is the RESOLVED file misnamed; the
pre-resolution state was never captured.


**WHAT IT CATCHES AND WHAT IT MISSES — MEASURED 2026-08-31T02:5xZ, on a real
failure.** A merge that produced NO conflict markers duplicated four lane blocks
in `lanes.md` and shipped as `48cc0770`. Run against that exact file,
`check_lane_invariants.py` **exits 1**: `VIOLATED: 1 contested file(s)`,
`pipeline/intelligence_state.py held by: layer2-cap-raise,
polymarket-yes-leg-binding`. **The checker was not blind — it was not run.** The
duplicate re-parented a claim set (`_claims` binds `- Files:` paths to the
nearest preceding header), and re-parenting surfaces as a contested file, which
is exactly what the existing check tests.

**The residual gap is the harmless half.** A bare duplicate `### <slug>` header
carrying no body claims nothing, so nothing is contested: injecting one gives
**exit 0, `INVARIANTS HOLD`**, with the lane simply counted twice. So the tool's
guarantee is "no claim has two holders", NOT "each slug appears once" — read its
green that way. A duplicate header is worth removing on sight, but only the
claim-bearing kind is load-bearing, and that kind IS caught.

## [settlement-resolver-coverage] SETTLEMENT: NFL CAN BE GRADED, NCAAF IS WIRED-BUT-UNVERIFIED, and three sports still cannot settle a bet `[verified 2026-08-28T03:59:18Z, lanes nfl-settlement-resolver / ncaaf-settlement-resolver]`

`paper_settlement._default_resolver` had builders for mlb/wnba/soccer only. NFL
orders returned `no_resolver_for_nfl` forever — measured 2026-08-28T02:50Z,
**6 of 21 orders on that slate (29%)**.

**VERIFIED, NFL** (refresh-worker `5a5efa8d`, read 03:59:18Z): `no_resolver_for_nfl`
**16 -> ABSENT**, `BET_STATUS resolved` **98 -> 114** (+16, exactly the count that
disappeared), `SETTLED 08-27 graded` **2 -> 9**. Two stages were needed, not one:
`nfl/live_game_state.py` fetches ESPN at call time and is keyed by
`(season, week, seasontype)`, so `scripts/poll_nfl_live_state.py` is the producer,
date-keyed and persisted through `refresh_state_store` (settlement runs on
refresh-worker; Render cannot share a disk between services).

**NOT VERIFIED, NCAAF** (refresh-worker `234c9e81` live 15:07:01Z): the counter
`no_resolver_for_ncaaf` was NEVER non-zero, because NCAAF orders have not reached
the ledger — so its absence is not evidence. Only no-harm is measured. Its join is
registry-backed, NOT `teams_match`: `_alias_map("ncaaf")` is `{}` and the fallback
heuristic matches "Michigan" to "Michigan State". `ncaaf_team_registry` holds 684
teams, 2,342 keys, and REFUSES the **128 ambiguous** ones (`tigers` names 25
teams); on the live 2026-08-29 ESPN slate 16/16 names resolved. Scheduled task
`verify-ncaaf-settlement-593` (daily 08:25 CT) reports PENDING rather than passing
on a quiet log.

**STILL CANNOT SETTLE A BET: `nba`, `nhl`, `ncaab`.** Pinned by
`tests/test_paper_settlement.py::test_the_traded_sports_WITHOUT_a_resolver_are_pinned...`,
so adding a sport to the board without a resolver now FAILS instead of quietly
demonstrating the bug. Pinned is not fixed.

## [execution-ledger-cross-service-race] THE MONEY LEDGER IS READ-MODIFY-WRITTEN BY TWO SERVICES WITH NO LOCK, and settlement writes are being silently lost `[verified 2026-08-28T17:4xZ, lane portfolio-venue-and-side-integrity]`

`execution_ledger._persist` does a blind whole-document `write_json_file` — no
lock, no compare-and-swap, no merge. **refresh-worker** (settlement, grading)
and **live-odds-worker** (order placement, venue reconciliation) both `_load()`
the entire ledger, mutate their own copy, and write it back. Last writer wins,
with whatever it happened to load.

**MEASURED, from the two services' own `KEYVALUE_WRITE_LARGE` sizes:**

    refresh-worker  17:40:43  1,271,141   commit path
    refresh-worker  17:40:46  1,275,216
    refresh-worker  17:40:47  1,276,178   <- paper_settlement.py:542, 08-26 graded=8
    refresh-worker  17:40:48  1,276,296   <- paper_settlement.py:542, 08-23 graded=1
    live-odds-worker 17:41:00 1,268,265   <- 12s later, 8,031 bytes SMALLER
    live-odds-worker 17:41:02 1,268,265
    ... held at 1,268,265 for TWELVE MINUTES, then grows from its own orders

**The ledger went BACKWARDS by 8,031 bytes.** live-odds-worker's snapshot is
smaller than refresh-worker's write at 17:40:43, so it was holding a copy loaded
before that entire burst and wrote it back over the top. The 9 grades and every
`grade_check` memo from that settlement pass were discarded.

**HOW IT WAS FOUND, and the symptom is the thing to recognise again.** Two WNBA
totals reported `graded=8` for 2026-08-26 in the log while the served payload
showed **zero** live rows changing outcome across that pass. I spent three wrong
theories on "what filters these rows before the resolver" before running the
deployed predicate chain against the real records: `outcome` falsy,
`status='filled'`, `mode='live'`, age 42.8h/45.2h against a 24h grace — **they
pass every filter and reach the resolver.** Nothing filters them. They were
graded and the write was clobbered.

**SO THE DIAGNOSTIC SIGNATURE IS: a `SETTLED ... graded=N` line with N>0 and no
corresponding outcome change on the served payload.** Not a resolver problem.
Check the ledger write sizes across both services before touching a resolver.

**SCOPE — this is not about WNBA and not about settlement.** Any write to this
ledger from either service can be lost: a grade, a `grade_check`, a
reconciliation, a fill. It is the record of real money. `#600`.

**FIXED AND DEPLOYED — `f66c7441`, three-way merge in `_persist`. All three
services on `a36e3c1a` 2026-08-28 ~18:57Z; web on `89678782` 19:09Z.**

**DEPLOY-VERIFIED, PARTIAL.** The ledger stops going backwards: 18:55-18:57 runs
`1,295,990 -> 1,298,163` monotonic ACROSS the service boundary, against the
`-8,031` step that started this. `last_blind_write` is readable on
`/api/ops/execution/ledger-summary` and reads `None` — a meaningful null, since
`_persist` only writes that field and never clears it.

**NOT YET PROVEN: `LEDGER_MERGE` has not fired.** `concurrent=0` since 18:58Z is
an absence in a short window, not a pass — a collision needs a settlement pass
overlapping a placement cycle. What settles it: one `concurrent>0`, or a
`SETTLED ... graded=N` whose outcomes actually appear on the served payload.

**The mechanism, unchanged:** `_load()`
captures a fingerprint per order; a row the writer did not touch is left to
whoever did. A per-order upsert would NOT have fixed it — the stale writer held
every graded order, so overlaying "its" rows discards the grades exactly as
before. Guarantee stated narrowly: different orders no longer clobber; the same
order in one window is still last-writer-wins at field level, blast radius one
row. `off != on` 7 of 10.

**SEVERITY IS HIGHER THAN A LOST GRADE.** `reconcile_live_orders` writes
`reconciled_at` through the same path and the unreconciled gate is a GLOBAL
LATCH (`learnings.md` 2026-08-25: one resting order blocked live placement on
EVERY venue for 32 minutes). A lost `reconciled_at` can re-arm that block.

**CLAIM ATTRIBUTION CORRECTED:** this section first said
`portfolio-ledger-service-split` owns `execution_ledger.py`. It does not —
`check_lane_invariants.claims()` returns NOBODY for that file. Read the claim
map with the tool, not the prose.

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

## [nhl-sim-engine] NHL SIM (hockeysim) — `nhl_sim_input_checklist.py` PASSES, exit 0 `[measured 2026-08-20, lane nhl-model-owner]`

- **Started this session at 16 alarms, now 0.** Full pipeline trace + gating
  checklist: `docs/ai_context/hockeysim_engine_reference.md`
  (§1–§2zzz, §8/§8b), `docs/ai_context/nhl_model_inventory.md`, `todo.md`
  `#463`/`#470`.
- **Special teams, per-team AND league-calibrated**: PP/PK goal conversion
  (`pk_goal_cal_mult=0.4645`, `pp_goal_cal_mult=1.0` deliberately neutral —
  measured statistically indistinguishable from baseline), PP/PK shot volume
  (`pp_shot_cal_mult=0.9108`/`pk_shot_cal_mult=0.3369`, real per-team indices
  layered on top, verified not to disturb the calibration), block rate
  (`block_rate_ev/pk/pp_def` scaled 1.0631x from vendor defaults, real
  per-team `block_rate_index` layered on top, same verification).
- **Real xG model** (`historical_truth/shot_xg_model.py`, logistic on
  distance/angle/shot-type/strength/rebound/empty-net, 112,888 Fenwick
  shots): holdout AUC=0.7450, Brier=0.0667, league xGF/60 within 1.8% of the
  truth-calibrated goals/60 baseline.
- **`TeamRates.blocks_per_60`/`penalties_per_60` REMOVED, not fixed** —
  confirmed dead (populated, `engine.py` never read either field, proven via
  a byte-identical-output test) and no legitimate mechanism existed to wire
  them into without double-counting: blocks are already fully governed by
  the calibrated per-shot `block_rate_*` mechanism above, and penalty rate
  already drives PP/PK segment generation via `special_teams`'s
  `committed_per_game` (`engine.py:718-719`, confirmed by reading the code).
  Deleted from `HockeyTeamFeatures`/`TeamRates` and every call site, traced
  end to end across 15 files (§2l). `shots_per_60`/`faceoff_win_pct` remain
  reachable and unaffected.
- **Player usage weights built** (`shot_weight`/`goal_weight`/`block_weight`,
  828 players from 47,231 skater-game boxscore records) — these were ALREADY
  reachable pre-fix via `engine.py`'s position/TOI heuristic; real per-player
  data now layers on top, proven at the mechanism level with 3 dedicated
  tests, not just population.
- **`elo_blend_weight` stays at 0.0, deliberately** — a naive win/loss Elo
  does not beat a constant-home-rate baseline (Brier 0.2506 vs 0.2495).
- **Play-by-play ingestion is new substrate** (`NhlWebIngestClient.play_by_play()`,
  1,312 games cached) — was previously unused for NHL entirely (`#454`,
  closed as a data-availability gap this session).
- **`#470`: NHL's first market-comparison backtest** (`scripts/grade_nhl_predictions_vs_market.py`,
  Brier score, `devig()`, mirrors MLB's `convergence-phase7-crps` methodology).
  Confirmed non-circular by reading `adapters.py`/the `/nhl/api/cards` route
  directly — `build_game_prediction` never touches `market_anchoring.py`.
  **Pulls real PRODUCTION data** (`--source production`/`both`, public
  `/nhl/api/cards/dates` + `/nhl/api/cards`, no admin token) as well as the
  thin local mirror. Two real bugs found and fixed while building this, both
  by checking cached responses rather than assuming: (1) several
  `predictions_<date>.csv` files are byte-identical stale duplicates of an
  earlier date — deduped on `(date, home_abbr, away_abbr)`; (2)
  `lookahead_applied` does NOT mean live/circular adjustment despite the
  name — it means "requested date had no games, served the next date that
  does," fixed by keying rows on the RESOLVED date. **Measured, n=14-15
  moneyline/total across 12 dates (2026-03-01..2026-06-11)**: moneyline
  market wins (0.2905 vs 0.2769), total model beats market this run (0.2102
  vs 0.2378) — stated plainly as NOT a powered verdict either way, n is
  still far below what MLB's own much larger sample needed to find its own
  noise floor. Puck-line odds are not exposed by the production route at
  all; `--source both` covers it from local files (n=3).
- **Faceoff track FULLY CLOSED (§2m through §2zzz)**, not just the
  EV/OZ/DZ zone slice: `_faceoff_multipliers` was gated
  `faceoff_ev_only=True` but fed `TeamRates.faceoff_win_pct`, an
  ALL-SITUATIONS blend — closed in stages, each verified not to shift the
  league-wide average shot count (992-pairing round-robin every time, all
  well under 1%): (1) EV/OZ/DZ/NZ per-team zone indices + discrete-event
  decay curves (`zoneCode` confirmed empirically relative to the WINNER,
  not a fixed rink frame; OZ/DZ confirmed genuinely independent, r=0.69
  not ±1.0); (2) a strength-state (PP/PK) mechanism — the first faceoff
  effect outside even strength — where a naive combination of two curves
  inflated league shots +4.478%, found by the SAME round-robin check and
  fixed with an exact per-segment normalization down to +0.203%; (3) a
  per-team PP/PK-role-specific win index refining that mechanism; (4) a
  joint role×zone investigation that correctly DECLINED a full curve
  build — 4 of 6 population cells too data-thin (as few as 197 league-wide
  draws); (5) a player-level lineup-aware layer (real per-player
  `faceoffWinningPctg`-derived rates, TOI-weighted per tonight's confirmed
  roster) for both EV-only and strength-state segments; (6)
  `faceoff_alpha`/`faceoff_diff_clip` calibrated against 1,312 real games
  (95% CI `[-0.005, 0.439]` comfortably contains the vendor's `0.35` —
  decision: left unchanged, backed by measurement not left uncalibrated by
  default) plus a leave-one-out refit confirming that judgment; (7)
  `faceoff_mult_clip_low`/`high` closed with an algebraic proof (max
  possible swing `0.042` is strictly inside the clip's `0.10` headroom for
  ANY input, confirmed by an exhaustive `[0,1]×[0,1]` sweep), after an
  earlier "closes to zero" claim was found to have overstated itself and
  was corrected on the record rather than left standing; (8) the "one
  faceoff assumed per real segment" approximation MEASURED (106,272 real
  segment-windows: mean 0.684 real faceoffs vs the assumed constant 1.0,
  48.64% of segments have ZERO real faceoffs) then ADDRESSED via a
  multi-event-per-segment redesign (`faceoff_multi_event_segment_model`,
  default ON, draws real N∈{0..6} per segment) — built for EV segments
  first (honest non-confirming result: std moved FURTHER from real,
  96.71%→96.03%), then extended to strength-state (PP/PK) segments,
  which REVERSED that finding: combined round-robin std moved to 99.88%
  of real, essentially closing the gap the original measurement found.
  650 hockeysim/nhl tests pass (up from 254 at session start; two
  pre-existing tests in this exact mechanism family broke twice each on
  mean-based reachability comparisons and were durably fixed via
  per-seed-vector comparison, the technique every other test in the
  family already used). `todo.md`'s own addendum for items (7)/(8) is
  NOT YET WRITTEN as of that checkpoint. **THE BLOCKER IS GONE
  `[2026-08-20 ~20:0xZ]`: lane `mlb-overview-hydration-cost` released its
  `todo.md` claim and is now CLOSED, so nothing holds that file for this
  addendum. Whatever Monitor was watching for it to clear can stop.**
  reports) is written and pushed.
- **Genuinely still open (non-faceoff)**: player-level usage-weight
  producer's small-sample floor (< 5 games falls back to heuristic, by
  design); the vendor's original block-rate EV:PK:PP-def ratio
  (0.45:0.55:0.35) was never itself validated, only scaled; xG model's
  rebound/tip-in coefficient sign is an open question; `#470`'s
  market-backtest sample (n=14-15) is nowhere near powered — re-run as the
  season resumes and dates accumulate.

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

## [sim-scheduling-blocker] 2026-08-17 02:1xZ — VERIFIED (sim-scheduling): the primary goal has ONE blocker — **ARCHIVED 2026-08-19 to `state_archive_2026-08-19.md`, verbatim.**

## [sim-edge-analysis-2026-09-01] FULL-PLATFORM SIM-ENGINE EDGE ANALYSIS — strategy synthesis + new from-code facts `[2026-09-01, session syndicate-8d, read-only]`

Full report: artifact "Where the Edge Lives"
(https://claude.ai/code/artifact/342e3562-d25c-43e4-a617-28e2039001ee); condensed
version + all file:line cites: `.syndicate/findings_2026-09-01_sim_engine_edge_analysis.md`.
Synthesis of the three accuracy assessments + six code surveys. Headline: the
market wins every properly-measured game main line (only unpowered exception:
NHL totals n=14-15); `sim − market` staking is the sim's error term; the plan is
(1) fitted market+sim blend per market, (2) volume to props/derivatives/
correlations/live, (3) venue-hold routing, (4) loop closure, (5) abstention+
sizing. NEW from-code facts this session `[from-code, agent surveys]`:

- **MLB per-sim JOINT outcomes are generated and DISCARDED at aggregation**
  (`daily_update.py:4380-4505` keeps marginal histograms only; H+R+RBI is the
  lone within-sim sum). Persisting per-sim vectors/moments = SGP/ladder/
  derivative pricing asset. A TRUE live MC exists (`live_mc.py`, 120 sims, full
  state incl. count/runner-ids/pitch-counts).
- **Basketball sim is market-anchored UPSTREAM**: quarter means blend to market
  at `margin_w=0.95` / `total_w=0.7` (`sim/quarters.py:66-67`) — downstream
  "edges" vs the same market are noise by construction (mechanically explains
  `#615`). Production `n_sims=100` (`render.yaml:1017`) ⇒ ±5pp MC error.
- **NBA still carries the WNBA bugs**: `p_win = implied + ev`
  (`refresh_nba_oddsapi_props.py:1159,1251,1315`) + arithmetic American-price
  averaging (`:2148-2152`); no clamps, no totals withhold. Port before season.
- **The WNBA live T0-3 hole located**: the JSONL tick writer re-derives `klass`
  in absolute points, bypassing the API layer's "never BET on
  line_source=model" gate (`app.py:46302-46316` vs `:40612-40616`).
- `is_home` hardcoded 0.0 at basketball props inference
  (`basketball_props_features.py:371`); opponent features never fed.
- **`manager_tendencies.json` CANNOT exist on Render** (untracked +
  repo-relative path) — resolves the convergence-phase7-crps open question; all
  30 teams share one ManagerProfile. MLB umpire input likewise unfeedable in
  prod (Windows-only prefetch; mechanism live at ±8%). MLB NWS weather is
  captured on schedule and NOT joined to the sim (open half of `#84`).
- NHL/NCAAB: no settlement resolver, no live poller (bets cannot settle); NHL
  fetcher never requests p1/p2/p3 segment odds. T-window closing sweeps exist
  for MLB+WNBA ONLY — every other sport's "close" is cadence luck.
- Soccer `fit_soccer_probability_calibration.py` output has NO consumer; drift
  detector has no scheduled caller; the only closed auto-calibration loop
  platform-wide is basketball's 7-day mean-bias.
- **OddsAPI: 4,959,329 of 5,000,000 remaining (99.2% unused)** per
  `odds_regions.py:63-66` — the [sharp-reference-price] 92.8%-burn line above
  is overwritten as stale. Historical endpoints: 10 credits/market-region.

## [accuracy-autorun-rearm-state] `#626`(h) IS ARMED, RAN, AND PASSED. The budget, not memory, is now the constraint. `[2026-09-04, lane accuracy-autorun-rearm CLOSED / accuracy-ledger-budget-raise OPEN]`

**Do not re-derive any of this. Superseded the 09-03 "one env key away" text.**

    ACCURACY_SUMMARY_ENABLE_REFRESH_WORKER_AUTORUN = true   (armed 2026-09-04, deploy 7f44f5eb live 14:20:32Z)
    AUTORUN_DONE sports=8 elapsed_s=669.389 error=none      14:34:27Z -- FIRST production run ever
    peak memory_anon_mb 1481.6 of a 4096 ceiling            BELOW the ~1877 baseline cycle peak
    09-02 OOM peak was 3868                                 this run peaked 2386 MiB under it
    oomKilled: LAST FAIL 2026-09-02T15:32:56Z, none since, zero restarts

**THE OOM RISK IS DISCHARGED.** `_project_evaluation_record` took 4.014 resident
bytes per file byte to 0.053; the 09-02 kill cannot recur from this path.

**WHAT REPLACED IT — the cap now costs coverage, which is what the 90MB budget
did before it:** `bytes=1999970055 budget=2000000000` (99.9985% of cap),
`skipped_budget=24`, `truncated=1`, `dates=8` of ~32 chunks. Raised 2GB -> 4GB
(`b55fa165`), **LIVE on `2332b47b` since 15:00:12Z**, verified by CONTENT.
Staged rather than jumping to the ~8.2GB that would admit all 32 chunks: measured
marginal cost is AT MOST 350.6 MiB per 2GB accepted, ~3x worse than the ratio
predicts, so 8.2GB projects to ~2566 MiB and lands too close to the ceiling if it
coincides with the 1877 baseline peak.

**UNEXERCISED.** The autorun is once per Central day and 09-04's ran under the OLD
2GB budget. First 4GB read is >= 07:00 CT 2026-09-05, pre-registered in the lane:
`skipped_budget` 0 = headroom to spare, ~12 = the BYTE budget is the wrong
instrument and the next step is a CHUNK-COUNT bound, between = report the number.

**A LEDGER RECORD IS ONE PER BOARD RECOMMENDATION PER `source_fingerprint` CHANGE**
(`maybe_record_board_state_to_evaluation_ledger`, `pipeline/intelligence_state.py:3023`),
~2.9 per row per day over ~2,027 rows — **NOT one per order.** `record_recommendation`
is the primary writer (`intelligence_evaluation.py:2542`); `record_portfolio_event`
(`:2553`) writes nothing only because that caller passes no `portfolio_events` key.
**A payload accident, not a structural guarantee** — a caller that supplies one makes
a per-order growth term real.

**HOW TO GET A DEPLOY WINDOW ON THIS SERVICE, after four attempts failed on "wait
for a quiet worker":** preflight CLEAR stays VALID 15 MINUTES once written, so it
only has to be CAUGHT once and need not coincide with the deploy. Windows last
under 25 seconds; **poll at ~12s**. CLEAR arrived on the 4th poll. Also expect the
25-minute deploy-spacing lockout (`#563`) — the worker is often idle DURING the
lockout and busy by the time it lifts, which is exactly why waiting kept losing.
