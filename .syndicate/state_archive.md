# State — archived sections

Moved out of `state.md`, which is read at the start of every session and has
to stay inside the digest budget. Nothing deleted; `state.md` keeps a pointer
for each. These are CLOSED or superseded-by-a-dedicated-file, not live state.

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

