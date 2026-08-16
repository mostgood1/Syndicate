# Syndicate — Work Lanes

> Lanes are exclusive by file path. Two lanes may not claim the same file.
> Max concurrent OPEN lanes: 3 (see `state.md`).
> Managed by `/lane`. Do not hand-edit while a session is running.

## OPEN

### export-force-refresh-escape — OPEN — **BUILT, TESTED (20, verified non-vacuous) AND ON `origin/main` (`734c163e`); ON NO SERVICE — rides along with the next worker deploy, see `deploys.md` PENDING** — opened 2026-08-16 — session: win-prob-null-readable
- Goal: `--force-refresh` actually regenerates the three props SNAPSHOT exports
  instead of re-serving a stale per-date file. Testable: with `force_refresh=True`
  the builder is CALLED even when the snapshot exists; with `False` it is not.
- **Why: found while explaining a `rows=0` win_prob reading.** All three exporters
  short-circuit on a prior `<name>_<date>.json`, but only two take a
  `force_refresh` escape. `_export_cards_props_snapshot` (WNBA `:5082`) has NONE —
  and it is the builder that produced the `rows=32/null=3` reading, so its
  staleness is the least visible. NBA is worse: the whole trio lacks the escape
  AND `_materialize_artifact_bundle` has no `force_refresh` parameter to pass.
  The WNBA sibling comment already names this shape "the same reuse-forever bug".
- **DELIBERATELY NOT THE WHOLE CLASS.** ~30 `if existing:` short-circuits exist
  across the two producers (live snapshots, recon artifacts, game cards, season
  cards). `live_refresh_loop.py` passes `--force-refresh` on EVERY lineup/injury
  trigger, so adding escapes everywhere would turn each trigger into a full
  artifact rebuild on a 2GB worker — the same over-reach `#347`/the 2026-07-19
  `smart_sim_overwrite` fix already had to undo once. Scope is the props snapshot
  trio only; the rest is recorded, not touched.
- Files (exclusive to this lane; `_claims()` CLEAR and every OPEN lane's `Files:`
  block read — zero `oddsapi_props` mentions anywhere in `lanes.md`):
  - `scripts/refresh_wnba_oddsapi_props.py`
  - `scripts/refresh_nba_oddsapi_props.py`
  - `tests/test_export_snapshot_force_refresh.py` (new)
- Falsification test: if the builder still is not called under
  `force_refresh=True`, the gate is not the one at `:5082` — re-read the caller
  chain before changing anything else.
- Verification: new tests assert called/not-called in both files, plus targeted
  producer suites green. **NBA cannot be verified in production — out of season,
  its producer writes no artifact.** Default `False` keeps every path inert until
  someone actually forces a refresh.
- Blocked by: none. No deploy from this lane tonight unless asked.

### layer2-board-quality — OPEN — opened 2026-08-16 — session: layer2-board-quality
- Goal: the curated board scores, labels and moves correctly, and never contradicts the sim. **Testable outcome:** on the served `/api/board/layer2-shortlist` payload, (a) `sim_component` is non-zero wherever `model_edge_pct` is non-zero, (b) every `quote.bookmaker` is in the shared book shortlist, (c) no row carries a negative `model_edge_pct` without an explicit label, (d) negative-value rows are not promoted by low reliability.
- Files:
  - `syndicate/features/shared/layer2_board.py`
  - `syndicate/features/shared/opportunity_signals.py`
  - `pipeline/layer2_shortlist.py`
  - `syndicate/templates/intelligence.html`
  - `syndicate/static/shared/bet_slip.js`
  - `syndicate/static/shared/board_cards.css`
  - `syndicate/blueprints/intelligence.py`
- **CLAIM ON `layer2_board.py` TAKEN FROM `spread-line-sign-convention` 2026-08-16, RESOLVED BY CONTENT RATHER THAN BY NEGOTIATION** (the `clamp-fix-to-workers` precedent):
  - That lane's outstanding item was "artifact output still unverified". **It is now verified: `_side_line_from_cells` is PRESENT in the deployed tree** — `git show 97491161:syndicate/features/shared/layer2_board.py` returns 3 occurrences, identical to `main`. The fix is live on refresh-worker.
  - **Ancestry was the WRONG test and gave the WRONG answer.** `edbbee9d` is NOT an ancestor of live `97491161` (`git merge-base --is-ancestor` → NO), because refresh-worker runs branch `deploy/nfl-pbp-root`, not `main`. Testing by content reverses that conclusion.
  - The holding session (`Orphaned lanes cleanup` = `lane-cleanup`) is ARCHIVED and not running — `list_sessions include_archived:true`, last activity 2026-08-16T01:14:03Z.
- **THE CLAIM WAS NEVER ENFORCED ANYWAY, AND THE HOLDING LANE MIS-READ ITS OWN CHECK.** `lane-guard.py`'s `_claims()` cannot see `spread-line-sign-convention`'s Files block: `FILES_RE` matches its header line (on the colon inside `23:0xZ`), yielding no paths, and the two continuation lines carrying the actual paths start with a backtick, not `-`, so they are never parsed. Measured: a `_claims()` run over `lanes.md` returns **zero** claims on `layer2_board.py`. That lane recorded "Collision check RUN … CLEAR both times, so no other lane was blocked by the gap" — the guard read CLEAR because **its own claim was unparseable**, not because the file was free. My Files block above puts each path on its own `-` bullet so it actually parses.
- Hypothesis: n/a for the audit half (measurement, not diagnosis). Per-goal hypotheses are recorded against G1–G8 below as they are tested.
- Falsification test: per goal. The standing one for the whole lane — if the served payload already satisfies (a)–(d) above, the brief's premise is wrong and the lane closes without a code change.
- Verification: the SERVED payload from `/api/board/layer2-shortlist`, written to `deploys.md`. Not a unit test — the user has twice reported a board defect that automated checks missed.
- Blocked by: none. Read-only on `layer1_board.py`, `templates/shared/layer1_board.html`, `blueprints/layer1_page.py` (Layer 1 session), sim-engine internals, and `pipeline/intelligence_state.py`.

### branch-overlap-baseline-instrumentation — CLOSED 2026-08-16 — the baseline was sampling hours where the failure does not happen — session: `branch-overlap-baseline-watch` (scheduled-task run)
- Goal: take one Phase 1 (`#440`) before-baseline sample; it turned into fixing
  the instrument, because the sample was honest and the schedule was not.
- Files: `.syndicate/scheduled_task_branch_overlap.md`,
  `.syndicate/scheduled_task_oom_band.md`, and three task files under
  `~/.claude/scheduled-tasks/` (outside VCS — prompts now embedded in the
  oom_band mirror so all three are recreatable).
- **NO LANE WAS OPEN WHILE THE WORK HAPPENED.** Opened at checkpoint, closed
  immediately. Config + mirrors only, no app code, nothing contended — but the
  protocol says claim first and I did not.
- Measured: 42 `oomKilled` in 8 days, **41 of 42 in 15:00–23:59 local**; cron
  moved `15 */4 * * *` → `45 19,22,1 * * *` (three 5h windows tiling
  14:45–01:45). Sampling drops 6/day → 3/day with the kill band fully covered.
- Corrected: the oom-band tasks' SHA-equality pin → containment check. See
  `learnings.md` 2026-08-16.
- Added: `preband-refresh-worker-sha-check`, one-time 21:45Z, returns
  BAND CLEAN / BAND COMPROMISED. **It notifies nobody** — created from a
  scheduled-task run session, which cannot subscribe another task.
- Pushed: `8150ff5b`, `b37b870c`, `80581700`, `38bb30b2`. Ledger writes from this
  checkpoint are UNCOMMITTED (shared files carry other sessions' in-flight edits).
- Blocked by: none. Nothing here is load-bearing for another lane; the
  `refresh-worker-oom-recurrence` owner keeps the diagnosis.

### closing-stamp-is-detection-time — CLOSED-VERIFIED — **OUTPUT MEASURED 2026-08-15 22:06 CDT / 2026-08-16 03:06Z. 21/21 new-code stamps precede first pitch; 33/36 pre-fix stamps post-date it. Same payload, both populations — a control group, not a before/after across time.** — opened 2026-08-15 — closed 2026-08-15 — session: lane-cleanup → clv-settled-read-2026-08-15
- **VERIFICATION 2026-08-15 22:06 CDT / 2026-08-16 03:06Z (scheduled read).**
  - **`closing_detected_at` is present on 21 markets. The new code path ran.**
    Source: the RAW shard `mlb_source/artifacts/mlb/odds_history/2026-08-15.json`
    via `/api/ops/artifacts/stream` (46,317,328 B, `last-modified` 02:51:45Z).
  - **DO NOT RE-RUN THIS CHECK ON `/api/ops/odds-history/inspect`. IT CANNOT SEE
    THE FIELD.** That handler (`syndicate/blueprints/ops.py:2141`) builds each
    market summary from a **fixed 10-key literal** — `stored_market_id`,
    `last_line`, `last_odds`, `history_points`, `history_first`, `history_last`,
    `is_live`, `closing_line`, `closing_price`, `closing_captured_at`. There is
    no `closing_detected_at` key in it. The union of keys over all 3,574 returned
    markets confirms it: the field is absent from the response **regardless of
    what is on disk**. A `0` from `inspect` is instrument blindness. The earlier
    `00:3xZ` "zero of 51" reading was almost certainly taken this way (the
    handover names `inspect` as the step-1 endpoint), which — if so — means it
    was never evidence either way, independently of the no-opportunity argument
    already recorded. Not asserted as fact: I did not observe that run.
  - **THE ASSERTION, on the 21 new-code stamps:** `closing_captured_at <=
    commence_time` on **21 of 21**, none post-dating. Lead time min 1.1 min,
    median 75.3 min, max 103.9 min.
  - **THE CONTROL, in the same payload:** of the 36 stamped markets WITHOUT
    `closing_detected_at` (pre-fix), **33 post-date `commence_time`** and 3 do
    not. So the handed-down baseline "EVERY stamped close had
    `close_age_seconds < 0`" is very nearly right but **not literally true at the
    shard level — it is 33/36, not 36/36.** Stated because a claim of
    universality invites a future reader to treat a single passing pre-fix stamp
    as a fix.
  - **ATTRIBUTED AT THE CLV-ROW LEVEL** (join `event_id|market|matched_bookmaker`,
    confirmed by `close_captured_at` identity — note the row's `bookmaker` is the
    OPENING book, `matched_bookmaker` is the close's book; joining on the wrong
    one produced `NEW=0, unjoined=48` on the first pass and would have read as a
    failed fix):
    - rows off **NEW-code stamps: 30 — all 30 `pregame`, 0 `in_play`**
    - rows off **OLD stamps: 31 — 26 `in_play` (84%), 5 `pregame`**
    - 6 unjoined.
  - **COUNTERFACTUAL:** headline without the 30 re-entered rows would read
    **n=96, −0.3998**; with them it reads **n=126, −0.3165**. The 30 new rows
    average **−0.0499**, i.e. genuine pregame closes are materially better than
    the rows the old code left in.
  - **STILL FORWARD-ONLY.** The stamp is idempotent on `closing_line`, so the 36
    pre-fix markets are permanently wrong and 2026-08-15 is a mixed date forever.
    Generality beyond MLB is UNMEASURED — nfl/wnba resolved 0 rows today, so no
    other sport exercised this path.
- **DISCRIMINATOR RUN 2026-08-15 22:0xZ on the `-186 -> +168` row. RESULT: NEITHER
  ORIGINAL BRANCH. The price is not stale and the clock is not the main problem —
  IT IS THE WRONG SIDE'S PRICE.**
  - Event `dbbb481a…` = **New York Yankees @ Toronto Blue Jays**, first pitch
    19:08Z. FanDuel h2h `history_first` 06:02:51Z carries
    `line={away_odds: -186, home_odds: +156}` — our opening of `-186` is the
    AWAY side, correctly recorded.
  - The stamped close is `closing_price = 168.0`. In that market's own history
    the scalar `odds`/`line` field tracks **`entity`**, and `entity` is
    **`Toronto Blue Jays` — the HOME team**. `+168` is a HOME price (betrivers
    independently shows home `+165` at the same 20:34 tick).
  - **So the joiner differenced an AWAY opening against a HOME close.** That is
    the entire `-27.72`. It is not CLV, not a stale price, and not a late clock.
  - **Measured across every stamped market, not just this one: `entity ==
    home_team` on 18 of 18.** So `closing_price` is ALWAYS the home price.
- **THE DEFECT, in code:** `resolve_close` path 1 takes
  `market_state.get("closing_price")` as a **side-blind scalar**. Path 2
  (`last_pregame_quote`) reads the `line` dict and picks `away_odds`/`home_odds`
  by side — which is exactly why the 100%/100% split fell where it did. The file's
  own docstring already knew: *"Game keys carry NO side — `entity` names one team
  … the history point's `line` dict carries BOTH."* Path 2 acts on that; path 1
  does not.
  - Consequence: **home-side openings get a CORRECT close; away-side openings get
    a garbage one.** Whether a given row is wrong depends only on its side, which
    is why the contaminated bucket had no consistent sign.
  - `totals` markets carry `home_odds/away_odds = None` entirely (6 of the 18),
    so over/under has no side resolution on this path at all.
- **MY SHIPPED FIX WAS RIGHT BY ACCIDENT, AND IT OVER-EXCLUDES. Stated plainly.**
  Web `4316c907` drops `close_age_seconds < 0` rows from the CLV headline. Those
  are exactly the `observed_transition` rows, so it removed the side-mismatched
  ones — **but for a reason that is not the real one**, and it also drops the
  HOME-side rows on that path, whose closes were fine. The exclusion stays (it is
  net-correct and named), but its stated rationale in `deploys.md` is now known to
  be secondary.
- **The timestamp claim is NOT refuted, just demoted:** `closing_captured_at`
  20:34:26Z against a 19:08Z first pitch is still 86 minutes late, and
  `odds_refresh_tracking.py:1602` still writes `now`. Fix the side first; the
  clock is a smaller, separable error.
- **SIDE FIX SHIPPED under `clv-without-settlement` (it owns `clv_join.py`):**
  web `c8810f45` live 21:58:19Z, main `ae0bc968`. 20 away-side openings now
  refuse the home stamp; `observed_transition` 48 -> 22; `in_play_excluded_n`
  48 -> 19; `same_book_n` 131 -> 151; headline `-0.3077` -> `-0.2714`,
  recompute-verified. **THIS LANE'S REMAINING SCOPE IS THE CLOCK ONLY** —
  `odds_refresh_tracking.py:1602` still writes `closing_captured_at = now`
  (detection time), which is why a 19:08Z first pitch carries a 20:34Z stamp.
  That file is still claimed here and untouched.
- **THE `-29.90` ROW IS EXPLAINED, 2026-08-15 22:2xZ. IT IS NOT A MARKET MOVE.
  THE ODDS-HISTORY FEED SWAPPED ITS `home_line`/`away_line` LABELS DURING THE
  DAY, so the same two prices appear under opposite labels.** Event
  `69928d29…` = Seattle Mariners @ **Houston Astros**, FanDuel spreads:

      history_first 06:02:51Z   away_line -1.5 away_odds +168 | home_line  1.5 home_odds -205
      history_last  21:26:47Z   away_line  1.5 away_odds -205 | home_line -1.5 home_odds +168

  **Identical prices (-205 / +168). The line labels are transposed.** The market
  did not move at all — `-205` and `+168` are the two sides of ONE run line.
- **Why the guard could not catch it.** `_price_for_side` checks the line by
  NUMERIC EQUALITY (`abs(point_line - opening_line) > 1e-6`). With the labels
  flipped, opening `home -1.5` matches the close's `home_line -1.5` — which by
  then is the OTHER bet. The guard is doing exactly what it was written to do
  and is defeated by an unstable label, not by a missing one. **Equality of a
  label is not identity of a bet when the label's convention is not stable.**
- **The openings look self-consistent; the history does not.** Three opening
  records for that event's spreads: `home +1.5 @ +178` (05:07, kalshi),
  `home -1.5 @ -183` (07:06, onexbet), `home +1.5 @ +186` (20:40, betopenly) —
  +1.5 is plus money at both ends of the day. The 06:02 history point calls
  `home +1.5` **-205**, contradicting them.
- **SCOPE, measured rather than assumed — and it is NOT the headline killer it
  looks like:**

      same_book subset        n     mean      median   |clv|>10
      spreads (line-bearing)  42   +0.515    +0.000       2
      h2h / totals           128   -0.521    -0.246       0

  The two extreme rows are a **mirror pair from this one event** (`+30.428` on
  `home +1.5`, `-29.900` on `home -1.5`), because BOTH openings were recorded
  and each got the other's close. **They nearly cancel**, which is why the
  spreads mean reads a benign `+0.515` on a median of exactly `0.000`.
  So: **severe per row, self-cancelling in aggregate.** It corrupts any
  per-recommendation CLV, any variance or CI, and any "worst bets" list — while
  leaving the headline roughly intact. h2h and totals are clean (0 of 128).
- **NOT FIXED, and deliberately not fixed from here.** The defect is upstream of
  `clv_join.py` (an unstable label in the odds-history feed), the mirror-pair
  cancellation means it is not urgent for the headline, and a numeric-equality
  guard cannot be patched into correctness without deciding which source owns
  the sign convention. **That decision is the next lane**, and it should start
  from: does the board's published `line` sign agree with the feed's, per sport?
- **OPEN THREAD, NOT MINE TO CLOSE:** one row survives at `clv_pct -29.90`
  (`open -205`, `close 168.0`, side **home**, source **last_pregame_quote**) —
  side-aware path, not a side mismatch. Real move or a third defect, unknown.
- **REVISED FIX, for whoever takes this:** make path 1 side-aware — resolve
  `closing_price` through the same `line`-dict logic path 2 uses, and REFUSE
  (named, counted) when the side cannot be determined rather than returning the
  entity's price. Then re-run this discriminator and re-derive
  `in_play_excluded_n`.

- Goal: `closing_captured_at` means the time the CLOSING PRICE WAS OBSERVED, or
  it is renamed to say what it is. Testable outcome: for every market carrying
  a closing stamp, `closing_captured_at <= commence_time`, OR the field is split
  into an observation time and a detection time and every reader is updated.
- **WHY THIS IS ITS OWN LANE AND NOT AN EDIT INSIDE `clv-without-settlement`:**
  the fix is in the PRODUCER (`odds_refresh_tracking.py`), the CLV joiner is only
  a consumer, and `clv_join.py` is claimed by that lane. Changing a stamp that
  persists in shard files is also a data-shape change, not a display change.
- **WHAT IS ALREADY MEASURED (2026-08-15, do not re-derive):**
  - `/api/ops/clv/report` mlb 2026-08-15: **48 of 179 same-book rows** carry
    `close_age_seconds < 0`, i.e. a closing stamp AFTER first pitch.
  - Clean 100%/100% split by source: every contaminated row is
    `close_source=observed_transition`; every clean row is `last_pregame_quote`.
  - One event: opened `-186`, closing price recorded `+168`, stamped
    `20:34:26Z` against a `19:08Z` first pitch — 86 minutes late.
- **I GOT THE MECHANISM WRONG ONCE ALREADY. The correction is the starting
  point of this lane, not a footnote.** I told the user the recorded price "is
  already live". **Reading `odds_refresh_tracking.py:1600-1602` says the
  opposite**: the stamp is guarded on `was_confirmed_pregame` and deliberately
  records `previous_line`/`previous_odds` — "the value observed the tick BEFORE
  this one -- not current_line/current_odds, which is already the in-play
  number." So the PRICE is intended to be the last pregame price. Only
  `closing_captured_at = now` is the detection tick.
- Hypothesis: **`closing_captured_at` is the DETECTION time, not the observation
  time of the price it accompanies.** The price comes from tick N-1 and the
  timestamp from tick N, so on a ~2h sweep cadence the stamp can post-date the
  price by a full interval and land after commence. If true, `close_age_seconds`
  systematically overstates lateness and says nothing about whether the PRICE
  was pregame.
- Falsification test: if the recorded `closing_price` for the late-stamped rows
  is genuinely an IN-PLAY price (not a stale pregame one), then the stamp is
  honest and the defect is in the `was_confirmed_pregame` gate instead — a
  different fix in a different place. **Discriminator:** compare each late row's
  `closing_price` against that market's own history points before commence. If
  it matches a pregame point, the price is fine and only the clock is wrong. The
  `-186 -> +168` swing is the case to run first; it is large enough that "stale
  pregame price" and "in-play price" make visibly different predictions.
- **THIS LANE CAN INVALIDATE PART OF MY OWN SHIPPED FIX, stated up front so
  nobody has to discover it.** Web `4316c907` excludes `close_age_seconds < 0`
  from the CLV headline. If the hypothesis holds, some of those 48 rows carry
  legitimate pregame prices and are being excluded on a bad clock — the headline
  would be right to distrust the timestamp but wrong to drop the row. The
  exclusion stays until this is resolved (a wrong-but-named exclusion beats a
  silent contamination), but it is **provisional**.
- Verification: (1) the discriminator above run on at least 10 late rows, with
  the split reported; (2) whichever fix follows lands with a test pinning
  `closing_captured_at <= commence_time`; (3) `/api/ops/clv/report` re-read and
  `in_play_excluded_n` re-interpreted against the finding.
- Files (exclusive to this lane):
  - `syndicate/features/shared/odds_refresh_tracking.py` — the single write site
    (`:1602`). Collision check RUN via `lane-guard.py`'s own `_claims()`: CLEAR.
  - `tests/test_odds_closing_stamp.py` (new). CLEAR.
  - **NOT claimed:** `syndicate/features/shared/clv_join.py` (held by
    `clv-without-settlement`) and `syndicate/blueprints/ops.py` (consumer only).
    If the fix needs either, coordinate rather than edit across the lane.
- Blocked by: none. **No deploy from this lane without `/preflight`** — a change
  to a stamp that persists in shard files needs its backfill story decided
  before it ships, not after.

### spread-line-sign-convention — CLOSED-VERIFIED 2026-08-16 — **ARTIFACT OUTPUT NOW MEASURED: 12 of 12 MLB spreads rows correct on the served shortlist (9 away + 3 home, the previously broken case).** File claim released to `layer2-board-quality`; holding session `lane-cleanup` archived 01:14Z — opened 2026-08-15 — session: lane-cleanup → verified by layer2-board-quality
- **VERIFICATION (2026-08-16 ~16:3xZ, by `layer2-board-quality`).** The one open
  item — "artifact output still unverified" — is now closed against the SERVED
  payload (`/api/board/layer2-shortlist`, `written_at` 2026-08-16T16:20:21Z)
  cross-checked cell-by-cell against `/api/board/book-grid?sport=mlb`:

      away rows agree      9/9      (already correct pre-fix)
      home rows agree      3/3      (the case this lane fixed)
      total               12/12

  `_side_line_from_cells` confirmed present in the DEPLOYED tree —
  `git show 97491161:syndicate/features/shared/layer2_board.py` returns 3
  occurrences, identical to `main`.
- **THIS LANE'S OWN DEPLOY CLAIM WAS UNPROVABLE BY ANCESTRY, AND ANCESTRY SAYS
  THE OPPOSITE OF THE TRUTH.** `git merge-base --is-ancestor edbbee9d 97491161`
  returns **NO**. refresh-worker runs branch `deploy/nfl-pbp-root`, not `main`,
  so the fix rode in by content while failing every ancestry test.
  `project_web_runs_a_deploy_branch_not_main` generalises to the WORKERS.
- **A FALSE 3-of-3 DEFECT CAME OUT OF THIS DATA FIRST; recorded so nobody
  re-derives it.** The grid carries MIRRORED rows for one (event, market,
  segment): `row.line=+1.5 / home_cells=-1.5` beside `row.line=-1.5 /
  home_cells=+1.5`. Joining the shortlist to the grid ON `line` picks the wrong
  twin and produces a uniform-looking "home side still inverted, 3/3". The
  discriminating field is the **price vector** — the disputed row's
  `{leovegas_se:123, prophetx:140, unibet_nl:125, unibet_se:125}` matches
  `row.line=1.0` (home cells -1.0) exactly, so its `-1.0` is CORRECT.
  **The lane's original 525-cell result is NOT affected** — it compared cells
  WITHIN a row, never across mirrored rows.
- **THIS LANE'S "NO TEMPLATE CONSUMES THE SHORTLIST" IS NOW STALE AND WAS THE
  BASIS FOR ITS SEVERITY CALL.** Measured 2026-08-16: `layer2_is_primary=True`,
  `legacy_candidate_count=0`, and **108 of 108** board cards carry
  `source=layer2_shortlist`. The `grep` over `templates/`/`static/` still returns
  zero because the wiring is SERVER-SIDE. The blast radius was never limited to
  the Ask headline; the shortlist is the board.
- **CLAIM WAS NEVER ENFORCED.** `lane-guard.py`'s `_claims()` yields **zero**
  claims on `layer2_board.py` from this lane: `FILES_RE` matched the Files header
  on the colon inside `23:0xZ` (harvesting no paths), and the continuation lines
  holding the real paths start with a backtick rather than `-`. This lane's note
  "Collision check RUN … CLEAR both times, so no other lane was blocked by the
  gap" read CLEAR **because its own claim was invisible**, not because the file
  was free.
- **TEMPLATE QUESTION ANSWERED 2026-08-15 23:2xZ. THE CONVENTION IS
  `row["line"] == THE AWAY HANDICAP`, AND ONLY THE HOME SIDE IS BROKEN.**
  - From the 525-cell result: `cell.home.line == -row.line` and (per-book
    internal consistency) `cell.home.line == -cell.away.line`. Therefore
    **`cell.away.line == row.line`, exactly.**
  - So: **away-side rows are CORRECT** — their price and `row["line"]` describe
    the same bet. **Home-side rows are INVERTED** — `layer2_board.py:852` pairs
    `cell["home"]["price"]` with `row["line"]`, which is the away handicap.
  - That is why the no-arb violation showed up only when comparing a home `-1.5`
    opening against a home `+1.5` one: both were home rows.
- **NO TEMPLATE CONSUMES THE SHORTLIST — but chat does, because I wired it there
  tonight.** `grep` over `templates/` and `static/` for `layer2-shortlist`:
  **zero hits**; the board still renders `ranked_all`. The one consumer on a
  user-facing path is `ask_the_syndicate_adapter.py:599`
  (`_board_top_opportunities`), shipped this session as web `c774fe1a`, whose
  `_board_row_selection` renders `f"{side} {line}"`.
  - **Verified live**: the chat headline served
    `'away -1.5 (San Diego Padres @ Cleveland Guardians)'` — an AWAY row, which
    is the correct case. **A HOME spreads row in that list would display the
    away handicap beside the home price.**
  - **So the user-facing blast radius is: home-side spread selections appearing
    in the Ask headline.** Narrow, real, and created by my own change tonight —
    before `c774fe1a` the shortlist had no user-facing consumer at all.
- **SEVERITY, stated so it is not over- or under-called:** not a board-wide
  mislabel (the board does not read these rows), not zero either. It also
  corrupts every home-side spread row in the CLV join, which is where it was
  found.
- Files (claimed 2026-08-15 23:0xZ — **claimed LATE, after the edit, which is a
  protocol lapse of mine; recorded rather than quietly backfilled**):
  `syndicate/features/shared/layer2_board.py`,
  `tests/test_layer2_book_prices_line.py`. Collision check RUN via
  `lane-guard.py`'s own `_claims()` at edit time AND again now: CLEAR both times,
  so no other lane was blocked by the gap.
- **FIX IMPLEMENTED, TESTED, ON MAIN AS `edbbee9d` — DEPLOY HELD.**
  `_side_line_from_cells` reads the handicap from the same cell as the price;
  no-op for away/h2h/props; returns None (caller keeps the row value) when books
  disagree on the sign. 8 new tests, 71 green across board + CLV suites.
  **Not deployed: it needs REFRESH-WORKER, and an MLB sim (pid 79) plus a board
  build were in flight.** Forward-only — today's openings keep the bad lines.
  Ship when the slate is quiet, then re-run the 525-cell invariant.
- **FIX unchanged and now fully justified:** at `layer2_board.py:852` take the
  line from the same cell as the price. Away is already right, so the change
  must not touch it — negate only for the home side, or carry
  `cell[side]["line"]` per book.
- **SAME-BOOK TEST RUN 2026-08-15 23:1xZ on `/api/board/book-grid` (mlb, 33
  spreads rows, 525 book-cells). THIS IS THE DECISIVE MEASUREMENT and it is
  UNIFORM, not statistical:**

      1. each book's OWN home/away lines sum to zero    525/525  consistent
      2. cell's home line vs the ROW's `line`             0/525  agree
                                                        525/525  OPPOSITE SIGN
      3. no-arb per book (implied home + implied away)  median 1.0483, none < 1.0

- **`book_prices` IS NOT MIXING BOOKS. Every book agrees with every other book
  and with itself.** The 2026-08-07 `_complementary` condition (*"books inside a
  single grid row disagree on the SIGN"*) is real but is **NOT** what is
  happening on this data. My previous entry blamed book-vs-book mixing; that is
  now refuted — 100% agreement between books.
- **THE ACTUAL DEFECT, and it is deterministic:** the ROW's `line` is the
  NEGATION of the cell's `home.line`, in every single case. So
  `layer2_board.py:852` building `book_prices = {book: cell["home"]["price"]}`
  and publishing it beside `row["line"]` pairs **the home team's price with the
  opposite handicap**. Every home-side spread opening is therefore recorded as
  `side=home, line=L, price=<home price at -L>`.
- **THIS PARTIALLY REINSTATES THE FINDING I WITHDREW, with a corrected
  mechanism.** The 16-of-17 no-arbitrage violations were REAL; my second reading
  ("confounded by book mixing") was wrong. It is not mixing — it is a uniform
  row-vs-cell convention mismatch. **Third revision of this attribution; this
  one is measured on 525 cells with 100% agreement rather than inferred from a
  neighbouring module's comment.** The sequence, so nobody re-treads it:
  feed transposes labels (WRONG) -> books disagree so `book_prices` mixes
  (WRONG) -> row.line is uniformly the negation of the cell's home line (this,
  measured).
- **STILL NOT ESTABLISHED — the user-facing question, now sharper.** `row["line"]`
  being the away handicap may be the board's INTENDED convention, in which case
  the cards are fine and only the home-side flattening at `:852` is wrong. The
  test is narrow: **does any template render `row.line` beside a HOME selection?**
  Read the card template before assigning any user-facing severity.
- **FIX, now well-specified:** at `layer2_board.py:852`, take the line from the
  same cell as the price (`cell[side]["line"]`) rather than inheriting
  `row["line"]` — either by carrying it per book or by negating for the home
  side. Do NOT "fix" the sign at the CLV end; the pairing is wrong where it is
  built, and every other consumer of `book_prices` inherits it.
- **TRACED 2026-08-15 23:0xZ. THE LINE IS SET AT `layer2_board.py:852-858`, AND
  THE DEFECT IS A DROPPED FIELD, NOT AN INVERTED SIGN.**

      "book_prices": {
          str(book): cell[side]["price"]        # <- price kept
          for book, cell in (row.get("cells") or {}).items()
          ...                                    # <- cell[side]["line"] DROPPED
      }

  Full chain: fetcher (`fetch_mlb_oddsapi_local.py`, EXONERATED — derives
  `home_line = -away_line` per lane) -> book grid (`book_grid.py:304`, passes
  `row.get("line")` through) -> `layer2_board` flattens each cell to a bare
  price -> `record_openings` stores that flat map -> `clv_join`'s same-book
  override reads `book_prices[book]` and pairs it with the ROW's line.
- **THIS REPO ALREADY KNEW, IN A NEIGHBOURING MODULE, AND SAID SO.**
  `board_cross_book.py` tags each quote with *"the CELL's own line, which is not
  always the row's line … this is the pairing guard"*, and `_complementary`
  documents the measured reason (production 2026-08-07, `spreads_alt`, first5):

      betmgm     away -1.5 (+210)   home +1.5 (-295)
      betrivers  away +1.5 (-240)   home -1.5 (+180)

  **Books inside ONE grid row disagree on the SIGN of the line.** That module
  refuses such pairings ("*spreads are signed per side*", postmortem §2.6, after
  a false +250.88% arbitrage). `layer2_board`'s `book_prices` drops the very
  field that guard depends on — and the comment above it says so deliberately:
  *"Flat {book: price}, not the whole cell."* The choice was made for artifact
  size; its cost is that sign information is unrecoverable downstream.
- **SO MY PREVIOUS CONCLUSION IS WRONG AND I AM WITHDRAWING IT.** I reported "the
  BOARD's home-spread `line` sign is inverted, 16 of 17 — possible user-facing
  mislabel". **That test was confounded by exactly this mixing:** it compared
  `book_prices` across books for one row-level line, and those books were not
  all quoting the same side. The 16/17 measures **sign disagreement BETWEEN
  BOOKS**, which is a known and expected market fact — not a board defect.
  **There is no evidence of a user-facing mislabel. Do not act on that claim.**
- **What IS established:** `book_prices` silently mixes books quoting opposite
  sides of a spread, so ANY consumer reading it for a spread selection can get
  the opposite bet's price. `clv_join`'s same-book override is one such consumer;
  that is the `-29.90`/`+30.428` mirror pair.
- **What is NOT established, and needs a same-book test to settle:** whether the
  ROW's own `line`+`price` (anchor book) are correct. My attempt was confounded —
  the two openings had DIFFERENT anchor books (onexbet, betopenly), and since
  books disagree on sign, an anchor-vs-anchor comparison proves nothing. The
  clean test is one book quoting both lines of one event.
- **REVISED FIX (do not ship before the same-book test):** carry the cell's line
  alongside its price — `{book: {"price": …, "line": …}}` — or refuse a same-book
  join whose book line is unknown. The size objection in that comment is real and
  should be answered with a line-only companion field, not by dropping the guard.
- **DISCRIMINATOR RUN 2026-08-15 22:4xZ. It trusts NEITHER label**, which is what
  makes it decisive: for one team, `-1.5` (win by 2+) is strictly harder than
  `+1.5`, so `implied(-1.5) < implied(+1.5)` is a no-arbitrage fact regardless of
  whose naming is right.

      source                          respects invariant   violates
      BOARD (published openings)            1 of 17          16
      FEED  (odds-history lanes)            2 of 2            0

  Board pairs span **15 distinct events** and many books; junk quotes
  (`novig -100000`) excluded. The single exception is `nordicbet -1.5=117 /
  +1.5=111` — implied 0.461 vs 0.474, a 1.3-point gap on a near-pick'em, i.e.
  inside the vig and not evidence of correctness.
- **The feed, on the same event, is internally right both times:** home `+1.5`
  at `-205` (implied 0.672, the easier bet, minus money) and home `-1.5` at
  `+168` (implied 0.373, the harder bet, plus money).
- **SO: `fetch_mlb_oddsapi_local.py` IS EXONERATED. The bug is downstream, where
  a published home-spread selection gets its `line`.** The hypothesis in this
  lane's header is CONFIRMED and the falsification branch (lane-collapse only)
  is REFUTED — lane collapse is real but cannot explain a systematic sign
  violation across 15 events.
- **MY EARLIER ATTRIBUTION IS NOW DOUBLY CORRECTED, and this is the final
  version.** First I wrote that the FEED "transposed its labels" (in
  `learnings.md`). Then I corrected that to "each point is internally
  consistent; the market state holds one lane at a time". **Measured, it is
  neither: the feed is correct and the BOARD is inverted.** The learnings entry
  from earlier tonight describes the right FAILURE MODE (a label whose
  convention is not stable across sources) but names the wrong culprit.
- **THIS IS BIGGER THAN CLV AND MUST NOT SHIP AS A CLV FIX.** These openings are
  recorded FROM published board rows, so if the board serves `side=home,
  line=-1.5` while the price is the `+1.5` price, **users are being shown the
  wrong side of the run line.** That is a correctness problem on the product
  surface; CLV merely made it visible.
- **UNVERIFIED, and it decides the severity — DO THIS BEFORE ANY FIX:** I have
  NOT checked what the rendered card/API actually displays. Two possibilities and
  they need different fixes: (a) the board's `line` field is genuinely inverted at
  the point of publication -> user-facing defect; (b) the board's `line` means
  something other than the home team's handicap (e.g. it carries the away line,
  or the market line) and only the CLV join misreads it -> internal-only. **The
  price data cannot tell these apart; only reading the publisher and the template
  can.**
- Next step, concrete: find where a spreads selection's `line` is set on the
  published row (start from `pipeline/layer2_shortlist.py` and the per-sport
  `cards.py`), and read what the card template renders beside it. Then decide (a)
  vs (b). **Still no deploy** — and generality beyond MLB is still unmeasured.

- Goal: for a spread, ONE source owns the sign of `line` and every consumer
  agrees with it. Testable outcome: for every same-book spreads row in
  `/api/ops/clv/report`, the opening's `(side, line, price)` and the close's
  `(side, line, price)` describe the SAME bet — checked by an assertion that does
  not itself rely on the label (see below) — and a test pins the convention per
  source.
- **WHY: a `-29.90` CLV on a market that never moved.** Event `69928d29…`
  (Seattle @ Houston), FanDuel spreads. The opening recorded `home -1.5 @ -205`;
  the close resolved `home -1.5 @ +168`. `-205` and `+168` are the two sides of
  ONE run line, so the "30-point move" is a bet differenced against its opposite.
- **REFINEMENT FROM READING THE FETCHER — my first framing was too strong and is
  corrected here before anyone acts on it.** I wrote in `learnings.md` that the
  feed "transposed its labels". **Each history point is internally consistent:**
  `fetch_mlb_oddsapi_local.py:505-525` derives `home_line = -away_line` and keys
  each lane by the home line, so `{away -1.5 / home +1.5}` and
  `{away +1.5 / home -1.5}` are both correct — they are **two different lanes of
  the same spreads market**.
  - **The real mechanism is that the odds-history market key carries NO line**
    (`event_id|home_team|away_team|market|bookmaker`), which `clv_join.py`'s own
    docstring already states. So every spread lane collapses into ONE market
    state and the last writer wins. At 06:02Z that state held the home `+1.5`
    lane; at 21:26Z it held home `-1.5`.
  - **What is still genuinely unresolved, and is this lane's question:** the
    opening says `home -1.5` costs `-205`; the 06:02 history says `home +1.5`
    costs `-205`. Same price, opposite line. **One of the two is using the
    opposite sign convention for a home spread, and I do not yet know which.**
- Hypothesis: the board's published `line` for `side=home` carries the OPPOSITE
  sign to the feed's `home_line`. If so every home spread opening is joined to
  the wrong lane, and away rows are joined correctly by accident.
- Falsification test: if the board and feed signs agree, then the mismatch is
  purely lane-collapse (the state simply held a different lane than the opening),
  the sign is exonerated, and the fix is to key history by line rather than to
  change any sign.
  - **Discriminator that does NOT trust either label:** for one event, take the
    published `book_prices` for the home `-1.5` selection and the feed's two
    lanes at the same instant. The lane whose `home_odds` EQUALS the published
    price identifies which line the board meant. Prices are the invariant here;
    labels are the thing under test.
- **SCOPE ALREADY MEASURED, so nobody re-derives it:** mlb 2026-08-15 same-book —
  spreads n=42, mean `+0.515`, median **exactly 0.000**, only 2 rows |clv|>10 and
  those two are a **mirror pair from this one event** (`+30.428` / `-29.900`),
  because both openings were recorded and each got the other's close. h2h/totals
  n=128, **zero** |clv|>10. **Severe per row, near-cancelling in aggregate** —
  so this corrupts per-recommendation CLV, variance, CIs and any "worst bets"
  list, while leaving the headline roughly intact. **It is NOT a headline
  emergency and must not be deployed like one.**
- Files (exclusive to this lane):
  - `scripts/fetch_mlb_oddsapi_local.py` — where `home_line`/`away_line` and the
    lane key are derived. Collision check RUN via `lane-guard.py`'s own
    `_claims()`: CLEAR.
  - `tests/test_spread_line_sign_convention.py` (new). CLEAR.
  - **NOT claimed, held by other OPEN lanes — coordinate, do not edit across:**
    `syndicate/features/shared/odds_refresh_tracking.py`
    (`closing-stamp-is-detection-time`) and
    `syndicate/features/shared/clv_join.py` (`clv-without-settlement`). Both are
    this session's lanes, so the marker can simply be moved if the fix lands
    there — but the claim must be updated first, not bypassed.
- Verification: (1) the discriminator run on >= 5 events across >= 2 books, with
  the winning convention named per source; (2) a test pinning it; (3) the
  spreads |clv|>10 count re-derived and the mirror pair gone.
- **Generality is UNMEASURED and must be established before any fix ships:** all
  of the above is ONE event, ONE date, MLB, FanDuel. NFL/NCAAF spreads and other
  books are untested, and MLB run lines are the asymmetric case that makes the
  error visible — symmetric `-110/-110` spreads would hide it entirely.
- Blocked by: none. **No deploy without `/preflight`**, and not before generality
  is measured — a sign flip applied to a source that was already correct would
  invert every spread join instead of fixing it.

### clv-without-settlement — OPEN — **GOAL RE-SCOPED 2026-08-15 23:5xZ: `clv_pct` PER RECOMMENDATION ALREADY EXISTS; THE GAP IS EXPOSURE, AND THE PREDICTION LEDGER IS THE WRONG SUBSTRATE** — opened 2026-08-14 — session: lane-cleanup
- **SETTLED CLV READING 2026-08-15 22:06 CDT / 2026-08-16 03:06Z (scheduled read,
  taken after the last two first pitches at 01:38Z and 01:40Z).**
  - **mlb headline: `avg_clv_pct = −0.3165` over `same_book_n = 126`,
    `beat_close_rate = 0.2143` (27/126).** `openings 999`, `resolved 254`,
    `same_book_all_n 151`, `in_play_excluded_n 25`,
    `unknown_timing_excluded_n 0`, `stamped_close_skipped
    {stamped_close_is_home_side: 59}`, `by_close_source {last_pregame_quote 187,
    observed_transition 67}`, `unresolved_reasons {no_market_in_history 368,
    no_pregame_observation 246, close_precedes_open 113, line_mismatch 18}`.
  - `by_close_timing`: pregame n=126 −0.3165 · in_play n=25 −0.3498.
  - `by_book_scope`: same_book n=151 −0.322 · book_agnostic_close n=92 **+2.8054**
    · different_book_close n=10 **+0.7011**. **The two positives are the known
    upward bias (best-of-N opening vs one book's close). NOT CLV. Never quote.**
  - **INSTRUMENT CHECK PASSED.** Recomputed the headline from `&rows=1`: mean
    `clv_pct` over rows with `close_book_scope == same_book` AND `close_timing ==
    pregame` = **−0.316519 → −0.3165 over n=126**, exact match on both the value
    and the n. `beat_close` recomputed 27/126 = 0.2143, also exact. The report is
    reporting what it says it reports.
  - **`same_book_n` DID NOT RISE — and the prediction was not testable as
    written.** It reads 126 against the last preliminary reading's 151. But the
    prior readings (−0.0711 n=144, −0.668 n=167, −0.3077 n=131, −0.2714 n=151)
    are mid-slate headline `n` only; I do not hold their payloads, and `n` moves
    with how many games have started, how many stamps landed, and the 59
    `stamped_close_is_home_side` skips. **A raw `n` comparison across hours is
    confounded and I am not treating 126 < 151 as a regression OR as a
    refutation.** The mechanism the prediction was about IS confirmed, on the
    within-payload counterfactual: **30 rows that the old code would have
    excluded as `in_play` are in the headline** (n=96 → n=126, −0.3998 →
    −0.3165). See `closing-stamp-is-detection-time` for the attribution.
  - **nfl and wnba UNCHANGED: `resolved = 0`.** `openings` 419 / 111,
    `unresolved_reasons` **100% `no_market_in_history`** for both (419/419,
    111/111). **This is NOT the blind-reader pattern** — the openings ledger is
    readable (`/api/ops/artifacts/export?pattern=reports/intelligence/clv_openings/*.jsonl&names_only=1`
    → `2026-08-15.jsonl` 1,126,475 B, mtime 02:20:33Z). Openings are recorded and
    visible; the join fails because odds-history holds no matching market for
    them. That is a separate, unowned gap.
  - **CONTAMINATION, stated not glossed:** both fixes are FORWARD-ONLY and shipped
    ~23:17Z, so this date is permanently mixed. **36 of 57 stamped markets carry
    the pre-fix clock** (33 of them post-dating first pitch), and 96 of the 126
    headline rows are pre-fix. **−0.3165 is a mixed-cohort number.** The first
    clean reading is 2026-08-16.
- **MEASURED BEFORE BUILDING, and it stopped the build:**
  - `/api/portfolio/summary`: **3 prediction records**, all sport `multi`,
    `settled: 0`, `avg_clv: null`. That is the whole ledger.
  - Same instant, published recommendations: **11,864 opportunities considered**,
    ~600 openings recorded for the date.
  - So `PredictionResult.clv_pct` — the field that exists and is never populated
    — sits on a table with **3 rows**. Filling it would make
    `/api/portfolio/summary.avg_clv` a real number computed over 3
    records: **a metric with no denominator, which is worse than null** because
    null is honestly empty and a number invites use.
- **`clv_pct` PER RECOMMENDATION IS ALREADY PRODUCED.** `compute_clv_for_date`
  emits one row per published opening, each carrying `clv_pct`, `beat_close`,
  `close_source`, `close_timing`, `model_edge_pct` and `ev_pct`, keyed by
  `event_id|market|player|segment|side|line|bookmaker`. **An opening IS a
  published recommendation** — that key is the recommendation's identity.
  Reachable now: `/api/ops/clv/report?date=...&sport=...&rows=1` (179 same-book
  rows today).
- **THE REAL GAP, stated precisely:** the per-recommendation CLV exists only on
  an ops diagnostic endpoint. Nothing a user or the board reads carries it. The
  work is EXPOSURE, not computation — and that is a different, smaller job than
  the lane's original wording implies.
- **THREE SUBSTRATES, materially different work — needs a decision, not a
  default:**
  1. **Attach at artifact build** (`layer2_shortlist`) — every published row
     carries its own `clv_pct`. Truest home; costs a WORKER deploy and only
     applies to rows built after it ships.
  2. **Join at serve time** on web — `/api/board/layer2-shortlist` merges the
     joiner's rows by key. Web-only deploy, works on today's data immediately,
     but recomputes per request (the joiner is a pure read, so it is legal).
  3. **Backfill the prediction ledger** — REJECTED on the evidence above until
     something actually writes recommendations into it at volume.
- **NOT STARTED. No files claimed for this.** Recorded so the next session does
  not rebuild what exists or build onto the 3-row table.

 — OPEN — **PUBLISH FIXED AND MEASURED (web `bebe87c9`, live 19:36:45Z): `same_book_n` 0 → 144, FIRST UNBIASED CLV = -0.07% AT A 27.1% BEAT RATE (PRELIMINARY, TAKEN PRE-FIRST-PITCH). THE LANE'S BREADTH HYPOTHESIS IS REFUTED** — opened 2026-08-14 — session: lane-cleanup
- **RESULT 2026-08-15 19:38Z — the publish fix landed and it changed the answer.**
  `PUBLISH_FAILED`×8/16h (`HTTP 403 FORBIDDEN`, last 19:32:50Z) → `PUBLISH_OK`×2
  at 19:37:00Z and 19:38:10Z, 15s after the deploy; zero failures since. Web now
  holds the artifact. MLB: `openings 0→520`, `resolved 0→293`,
  `same_book_n 0→144`. Also landed on main as `baec34a8` — it had existed ONLY
  on deploy branches (web and main both carried blob `aff59302`).
- **THE PRE-REGISTERED RULE IS REFUTED. Do not re-derive it.** "If `same_book_n`
  is still 0, the blocker is odds-history breadth" — `same_book_n` moved 0→144
  with **no change to odds history**; only the reader moved. Breadth is real but
  it constrains `resolved`, not `same_book_n`:
  `no_market_in_history: 172`, `close_precedes_open: 42`, `line_mismatch: 13`.
- **FIRST UNBIASED NUMBER, and the selection effect is now measured:**

      scope                    n     avg_clv   beat_close
      same_book (UNBIASED)   144     -0.0711      27.1%
      book_agnostic_close    143     +2.7261      82.5%
      different_book_close     6     +1.3907      66.7%

  The biased scopes say the board crushes the close; the honest one says it is
  flat-to-negative and beats the close **27%** of the time. Supersedes the
  retracted `-5.215`.
- **THE LANE'S GOAL WAS ALREADY MET — `clv_pct` PER RECOMMENDATION EXISTS AND
  SHIPS. Do not build it.** Checked 2026-08-15 21:1xZ before writing any code:
  `/api/ops/clv/report?date=...&sport=mlb&rows=1` returns **355 rows, 355 of
  them carrying `clv_pct`**, plus `beat_close`, `close_book_scope`,
  `model_edge_pct` (291/355) and `ev_pct` — no grading, no outcome, no
  `settle_result`, exactly as the goal specifies. `clv_join.py` has done this
  since it was written; it was invisible only because of the 403 publish bug
  fixed earlier today. **The build was already done and the lane did not know.**
  - **The prediction ledger is NOT the recommendation stream and must not be
    used as one** — `/api/portfolio/summary` reports **3 predictions, 0
    settled, `avg_clv: null`** for a single pseudo-sport `multi`, against 636
    MLB openings recorded today. `record_result()` is also the wrong door: it
    computes `clv_pct` only via the settlement path this lane is defined to
    avoid.
- **WHAT WAS ACTUALLY MISSING IS THE SEGMENTATION THE AUDIT WANTED IT FOR.
  Computed below on the 172 unbiased same-book rows — biased scopes excluded.**
- **§4, THE THRESHOLD QUESTION: model edge DOES buy CLV, and the honest
  threshold is far higher than 2%.**

      model_edge bucket    n     avg_clv    beat_close
      edge < 0            69     -0.419        26.1%
      0-2%                25     -1.772        24.0%
      2-5%                17     -1.245        29.4%
      5-10%               25     -0.112        32.0%
      10%+                12     +1.396        41.7%

  Monotone in BOTH columns from `0-2%` up, and **only the 10%+ bucket is
  positive**. On this evidence a 2% threshold publishes rows that lose CLV.
  **Unexplained and left unexplained:** `edge < 0` (-0.419) beats `0-2%`
  (-1.772). Do not build a story on it; n is small.
- **THE HEADLINE LOSS IS ONE BOOK-MARKET CELL, NOT A BROAD PROBLEM.** Two
  findings looked separate ("h2h is bad", "fanduel is bad"); cross-tabbing
  showed they are one:

      cell                        n      avg_clv    beat
      ALL same_book             172      -0.672     27.9%
      FanDuel h2h ONLY           54      -2.648     20.4%
      EVERYTHING ELSE           118      +0.232     31.4%

  FanDuel h2h is **31.4% of rows and 124% of the total loss** — remove it and
  the board's CLV is **positive**. It is not h2h generally (DraftKings h2h
  `+0.488`, n=24) and not FanDuel generally (FanDuel totals `+0.122`, spreads
  `+0.132`).
- **ANSWERED 2026-08-15 21:5xZ — AND MY OWN "FanDuel h2h" HEADLINE IS RETRACTED.
  IT IS NOT A FANDUEL PROBLEM AND NOT AN h2h PROBLEM.**
  - **The cause: rows whose "close" was sampled AFTER FIRST PITCH.**
    `close_age_seconds = (commence - stamp)` (`clv_join.py:216,254`), so a
    NEGATIVE value means the close observation is POST-COMMENCE — an in-play
    price, not a close. **37 of 172 same-book rows (21.5%) are post-commence,
    and they carry 60% of the entire loss.**
  - **The worst four rows are one event.** `dbbb481a…` h2h away: open `-186`,
    "close" `+168`, stamped 20:34:26Z against a 19:08Z first pitch — 86 minutes
    into the game. That is a team going behind early, priced live. It is not
    CLV. Four published openings (kalshi, polymarket, betopenly, betfair_ex_eu)
    all matched that same FanDuel pair, so one bad close entered the mean four
    times at ~-27 points each.
  - **CLEANED, THE FANDUEL CELL IS UNREMARKABLE AND DRAFTKINGS IS WORSE:**

        cell                              n     avg_clv    beat
        ALL same_book (as I reported)   172     -0.672    27.9%
        EXCLUDING post-commence closes  135     -0.346    25.2%
          FanDuel h2h, cleaned           47     -0.616    23.4%
          DraftKings h2h, cleaned        21     -1.378    14.3%

    **"Strip FanDuel h2h and CLV is positive" does not survive cleaning. Do not
    act on it.** The board's honest same-book CLV on this date is about
    **-0.35**, not -0.67, and it is not concentrated in one book-market cell.
  - **How I got it wrong, recorded because the shape repeats:** I read a
    negative `close_age_seconds` as "close precedes open" WITHOUT reading the
    field's definition, then built an attribution on it. The guard for
    close-precedes-open (`:430`) was never the issue — it correctly did not
    fire, because `close > open` on all 37 rows. **Two different defects can
    both produce a negative number in a field you did not define.**
  - **H4 (favourite asymmetry) and H2 (stale openings) are REFUTED by data:**
    FanDuel vs DraftKings h2h open-price medians 102 vs 115.5, favourite share
    41% vs 29%, `close_age` medians 8025s vs 8265s — comparable on every axis.
    **H3 stays refuted at the code level.** What remains of H1 is small and is
    NOT FanDuel-specific.
  - **`n=172` IS NOT 172 INDEPENDENT OBSERVATIONS.** The same book's open/close
    pair is reused for every published opening on that event/market/side, so one
    pair can enter the mean many times. Any confidence interval over these rows
    is overstated until that fan-out is collapsed.
- Files (claimed 2026-08-15 22:0xZ, collision check CLEAR via `lane-guard.py`'s
  own `_claims()`): `syndicate/features/shared/clv_join.py`,
  `tests/test_clv_close_timing.py` (new).
- **DEFECT FIXED AND VERIFIED — web `4316c907` live 21:41:18Z, main `a68e1ce0`.**
  Headline now counts same-book AND pregame closes only. Verified by recomputing
  the mean from the rows at the same instant: `-0.3077` both ways, n=131,
  `in_play_excluded_n=48`, 374/374 rows carry `close_timing`.
  - **The in-play bucket flipped sign between readings** — strongly negative at
    21:1xZ, **`+0.7937` (n=48, beat 54.2%) at 21:4xZ**. The old code would now
    publish `-0.0124`. **The contamination is noise, not a fixed bias**, and it
    could have manufactured a "CLV is improving" story out of game-state drift.
  - Clean series moved 0.04 pts across 2.5h (`-0.346` -> `-0.3077`); dirty series
    moved 0.66 pts (`-0.672` -> `-0.0124`).
  - `clv_join.py` was **entirely absent from main** until `a68e1ce0` (600
    insertions), the same "lives only on a deploy branch" pattern as the
    allowlist entry.
- **OLD, kept for the record:**
- **THE DEFECT TO FIX (its own change, not done here):** `compute_clv_for_date`
  labels post-commence closes but still counts them in the headline
  `avg_clv_pct`. The docstring already anticipates this — *"a caller that wants
  only gold data can filter on them"* — but the headline IS that caller and does
  not filter. Either exclude `close_age_seconds < 0` from the headline or report
  it as a separate scope beside `same_book`, the way book scopes already are.
- **HYPOTHESES FOR THE FanDuel-h2h CELL, WRITTEN BEFORE TESTING (2026-08-15 21:3xZ):**
  - **H3 — join artifact (best-of-N open vs FanDuel close). REFUTED AT THE CODE
    LEVEL BEFORE ANY DATA WAS PULLED.** `clv_join.py:380` sets
    `open_price_override = book_prices.get(book)` whenever it matches a
    same-book close, and `:435` prefers that override over
    `opening.get("price")`. So within `same_book`, open and close are the SAME
    book's prices. The best-of-N price only survives as `open_price_best_book`,
    which is not what `clv_pct` is computed from. **This candidate is dead;
    do not re-raise it without new evidence.**
  - **H1 — real movement.** FanDuel h2h genuinely drifts against the sides we
    publish. Falsified if open/close timing and price levels look like
    DraftKings h2h, which is `+0.488` over the same events.
  - **H2 — stale openings.** Our recorded FanDuel opening is old relative to its
    close, so we are comparing a price nobody could still get. Falsified if
    `open_captured_at` / `close_age_seconds` for the FD cell match the rest.
  - **H4 — favourite/underdog asymmetry (NEW, and the arithmetic favours it).**
    `clv_pct` is in probability POINTS, and `_implied_from_american` is convex:
    the same relative move is worth more points at -250 (71.4%) than at +150
    (40%). If the FD h2h rows sit systematically on heavy favourites, the cell
    can read negative from the METRIC's scale rather than from worse prices.
    Falsified if the FD and DK h2h price distributions are comparable.
  - **H5 — side selection.** We publish one side (the value side); if that side
    is systematically the one that drifts out at FanDuel, the cell is real but
    is a statement about our selection, not about FanDuel.
  - **Sign convention, stated so nobody re-derives it backwards:** `clv_pct =
    (closing_implied - original_implied) * 100`. **Negative means the close is
    LONGER than the price we took** -- we took a short price and it drifted out.
- **CAUSE OF THE FanDuel-h2h CELL IS NOT ESTABLISHED.** Candidates not
  discriminated: FanDuel moneyline closes genuinely moving against us; our
  openings at FanDuel being stale relative to its close; or a `matched_bookmaker`
  artifact in the join. **Do not act on this until one is measured** — its own
  lane.
- **ALL OF THE ABOVE IS PRELIMINARY, same caveat as the headline:** rows fetched
  ~21:1xZ with roughly 10 of 14 MLB games unstarted, so most "closes" are latest
  observations. One date, one sport. Several buckets are n < 25. Re-run after
  the settled read before anything is promoted to a threshold change.
- **SECOND READING 2026-08-15 20:4xZ (4 of 14 MLB games started) — THE NUMBER IS
  MOVING, AND DOWNWARD.** Same endpoint, same date, ~1h later:

      reading           games started   same_book_n   avg_clv   beat_close
      19:38Z (first)         0 of 14         144      -0.0711      27.1%
      20:4xZ (second)        4 of 14         167      -0.668       29.3%

  - The biased scope barely moved (`book_agnostic_close` +2.7261 -> +2.8425,
    n=143 -> 164, beat 82.5% -> 83.5%), so the gap between the honest and the
    flattering number **widened** from ~2.80 to ~3.51 points.
  - `different_book_close` FLIPPED SIGN, +1.3907 -> **-0.5665** (n=6 -> 9). At
    n<10 that is noise; do not read it as a trend.
  - `unresolved_reasons` grew as expected: `close_precedes_open` 42 -> 64,
    `line_mismatch` 13 -> 19, plus a new `no_pregame_observation: 4`.
    `no_market_in_history` held at 172.
  - **STILL NOT THE SETTLED NUMBER.** Last first pitch is **2026-08-16T01:40Z
    (20:40 CDT)** — 10 of 14 games had not started at this reading.
  - **DIRECTION OF TRAVEL MATTERS FOR ANYONE WAITING ON THIS:** both readings
    are negative and the second is 9x more negative. Nothing here supports "the
    board beats the close"; the evidence so far points the other way.
- **A re-read is ARMED** (background monitor, fires after 01:45Z) to capture the
  settled figure. If this session is gone when it fires, run by hand:
  `/api/ops/clv/report?date=2026-08-15&sport=mlb` and record `same_book_n`,
  `avg_clv_pct`, `beat_close_rate` plus the `by_book_scope` table.
- **Minor data oddity, logged not chased:** `by_book_scope` carries a bucket
  keyed `None` with `n=0`. Harmless today; it means some row's scope label is
  null rather than a scope name. Worth a look only if `n` ever becomes nonzero.
- **`-0.0711` IS PRELIMINARY — timing, not arithmetic.** Taken 14:38 CDT, before
  first pitch for most of the slate, so most "closes" are latest observations.
  **Re-read after the last MLB game starts.** One date, one sport, 144 pairs.
- **STILL OPEN, and this is what the lane is now for:** (1) re-read post-slate
  and record the settled number; (2) NFL 246 openings / WNBA 80 both `resolved:
  0` — odds history has no markets for them; (3) NBA/NHL/NCAAF/NCAAB/soccer
  record **0 openings at all** — nobody has asked why; (4) `clv_pct` per
  recommendation, the lane's original goal, is NOT built.
- **Handed back:** lane left OPEN and unclaimed at the end of this session; the
  per-session marker was released. `artifact_publisher.py` is free.

- **THE PUBLISH FAILURE IS DIAGNOSED. Every link measured 2026-08-15 19:0xZ,
  no link inferred.**
  1. **Recorder healthy.** refresh-worker: `[clv_opening_ledger] OPENINGS
     date=2026-08-15 ... already=490`. **490 real openings exist.**
  2. **Sender tries.** refresh-worker (live `c67f7373`) HAS
     `reports/intelligence/clv_openings/*.jsonl` in `HOT_ARTIFACT_PATTERNS`, so
     it calls `publish_hot_artifact` — but only `if written:`, which is why the
     attempts are sparse rather than per-tick.
  3. **Receiver refuses: `HTTP Error 403: FORBIDDEN`**, 8 times in 16h.
     `_write_published_artifact` returns 403 on exactly one condition —
     `if not is_hot_artifact_relative_path(relative_path)` (`ops.py:1100-1101`).
  4. **Web's copy does not have the pattern.** Live web `0bf866c3` →
     0 occurrences of `clv_openings`.
  5. **Not a transport, token or size problem, and this was checked rather than
     assumed:** soccer `live_state` artifacts logged `PUBLISH_OK` to the SAME
     url with the SAME token at 19:11:25Z, seconds after a clv `PUBLISH_FAILED`.
     Zero `SKIP_NOT_CONFIGURED` lines. The file is ~286KB against a 4MiB stream
     threshold, so it takes the proven JSON-envelope path.
- **CORRECTION TO MY OWN FIRST READING, made before acting on it.** I said the
  entry was "on origin/main" and that web had merely fallen behind. **It is NOT
  on main.** Blob for `artifact_publisher.py` is `aff59302` on BOTH web
  `0bf866c3` and `origin/main`; the worker carries `ee94fe6b`. I had grepped the
  WORKING FILE and reported it as main. The entry exists only on the worker's
  deploy branch and in the working tree — it has never been committed to main,
  so it is one `git checkout` away from being lost.
- **THE FIX IS A DEPLOY, NOT A CODE CHANGE.** Diff between web's blob and the
  worker's is a single pure addition: the comment plus
  `"reports/intelligence/clv_openings/*.jsonl"`. The working tree is
  byte-identical to the worker's deployed blob (`ee94fe6b`), so shipping it to
  web makes sender and receiver agree.
- Files (exclusive to this lane): `syndicate/features/shared/artifact_publisher.py`.
  Collision check RUN via `lane-guard.py`'s own `_claims()`: CLEAR.
  **NOT claimed:** `syndicate/blueprints/ops.py` (held by `quote-feed-age-alarm`)
  — no edit needed there, the receiver logic is already correct.
- Falsification test: if web still 403s after the allowlist ships, the 403 is
  NOT coming from the allowlist branch and `ops.py:1100` is the wrong line —
  re-read the receiver before changing anything else.
- Verification: (1) a `PUBLISH_OK` line for a `clv_openings` path in
  refresh-worker's log; (2) `/api/ops/artifacts/export?pattern=...clv_openings/*.jsonl`
  returns `count >= 1, bytes > 0`; (3) `/api/ops/clv/report?date=2026-08-15&sport=mlb`
  returns `openings > 0`. **All three, or it is not fixed.**
- **DOES NOT CLOSE THE LANE.** This unblocks the measurement; it does not
  produce `clv_pct`. Breadth remains untested.

- **STATUS 2026-08-14 19:50 CDT.** Recorder LIVE (`2b14fbeb`) + `book_prices`
  LIVE (`96e3a9b7`). Joiner is **library-only, no call site, NOT deployed**
  (`deploy/clv-joiner-guards-r2`, `2f596260`). 42 tests green.
- **THE `-5.215` SAME-BOOK AVERAGE IS RETRACTED. Do not resurrect it.** It came
  from 25 rows and looked right — it even had the OPPOSITE SIGN to the biased
  scopes, which is what a genuine bias correction looks like. Two independent
  defects, now refused by name:
  - `line_mismatch` / `line_unverifiable` — history keys carry no line, the
    point's `line` block does; `home -5.0` was being differenced against a
    `home -1.5` close.
  - `close_precedes_open` — **25 of 25** closes were captured BEFORE their
    openings. **This is a PRODUCTION condition**, not a backfill artifact: it
    fires whenever a market is first published after the last pregame
    observation of it.
- **Current honest output on real data:** `same_book_n=0`, `avg_clv_pct=None`,
  `unresolved={close_precedes_open: 38, no_market_in_history: 14,
  no_pregame_observation: 23, line_mismatch: 1}`.
- **BLOCKED ON THE WORKER OOM LOOP `[2026-08-14 20:38 CDT]`.** The worker has
  been OOM-killed **18 times** today, ~1 per 11-15 min per instance across 7
  instances. Tomorrow's measurement needs the worker to stay up long enough to
  record a full day of openings, so **this lane is downstream of the memory
  lanes.** `#435` (`c9378c91`) is live and owns the diagnosis. **Worker deploys
  are HELD.**
- **TODAY'S OPENINGS ARE STRANDED ON THE WORKER.** `/api/ops/clv/report` reads
  `openings=0` for all sports while the worker has ~150+ recorded, because the
  publish fires only on `written > 0` and every 08-14 market was first-seen
  before the publish shipped. Not a bug in the recorder; a gap in when it
  pushes. One-shot-per-boot publish is the fix, and it needs a worker deploy.
- **THE MEASUREMENT IS NOW EXECUTABLE (shipped 2026-08-14 ~20:05 CDT).** It was
  not before: the joiner had no call site and the openings were unreadable off
  the worker. `GET /api/ops/clv/report?sport=<s>[&date=<d>][&rows=1]` is live on
  web (`d9a39ce8`); the worker publishes the openings (`d70f70d8`).
- **NEXT ACTION — the first clean measurement is 2026-08-15 (Central).**
  Production's 08-14 openings only began at 18:32 CDT, so tonight's file is
  late-loaded and its closes mostly predate its openings. Tomorrow, run
  `compute_clv_for_date('2026-08-15', sport)` per sport and read
  `same_book_n` + `avg_clv_pct`. **If `same_book_n` is still 0, the blocker is
  odds-history breadth** (median 2 books per event-market vs the board's best
  of ~13), not the joiner.
- **Known gaps, measured, each its own lane if pursued:** NFL and WNBA resolve
  0 — their odds-history artifact for 08-14 has no markets at all. MLB
  `_alt`/`_lay`/`3_way` families are absent from history entirely.
- **JOINER BUILT 22:5xZ** — `syndicate/features/shared/clv_join.py`, branch
  `deploy/clv-joiner` (`57e32a04`, off `2b14fbeb`). **Library only, no call
  site, NOT deployed** — it ships no production behaviour.
- **THE FIRST CLV NUMBERS THIS SYSTEM HAS EVER PRODUCED, on 150 real openings:**

      scope                  n    avg_clv   beat_close
      different_book_close  32     +6.206    29/32 (91%)
      book_agnostic_close   27     +2.716    18/27 (67%)
      same_book              0         --       --

  **`avg_clv_pct` is None and that is the correct answer.** A +6.2-pt average
  at a 91% beat rate is a SELECTION EFFECT, not skill: the board publishes the
  BEST price across books by construction, so pairing that opening with another
  book's close compares a best-of-N draw to a single draw. The headline counts
  same-book rows only; biased scopes are reported beside it, never blended.
- **What the join can and cannot reach** `[measured, mlb 78 openings]`:
  - props **28/28 matched (100%)**
  - `no_market_in_history` 18 — `h2h_lay`, `totals_alt`, `h2h_3_way`,
    `spreads_alt` are absent from odds history entirely (capture-side gap)
  - 32 game rows matched only via a DIFFERENT book
  - **NFL 0/60 and WNBA 0/12** — their odds-history artifact for 2026-08-14 has
    no markets at all. Capture-side, not a join defect. **Own lane.**
- **THE CHEAP FIX FOR SAME-BOOK CLV, and the next action:** have the opening
  ledger record a MAINSTREAM-book price alongside the best-book one. Odds
  history tracks fanduel/betmgm/draftkings; the board picks polymarket /
  prophetx / betfair_ex. One extra field on each opening makes an unbiased
  same-book comparison possible from tomorrow. Without it the headline stays
  None no matter how good the joiner gets.
- **Recorder is LIVE and verified** — refresh-worker `2b14fbeb`,
  `OPENINGS rows_in=150 written=150 ... truncated=False` at 22:32:02Z.
  Idempotence on the production disk (`written=0 already=150`) is STILL
  unconfirmed; builds are ~21 min apart.
- **UPDATE 22:3xZ — option (a) chosen by the user and SHIPPED.** refresh-worker
  `2b14fbeb`, live 22:20Z. `[clv_opening_ledger] OPENINGS ... rows_in=150
  written=150 already=0 duplicate=0 unkeyable=0 truncated=False` at 22:32:02Z.
  Openings are now being recorded; they were being lost on every build before.
- **OWED, in order:** (1) read a SECOND `OPENINGS` line to confirm idempotence
  in production (`written=0 already=150`) — builds are ~21 min apart; (2) build
  the joiner. (3) optional: put `clv_openings` on
  `/api/board/layer2-shortlist`, which currently omits it (log-only).
- **THE JOINER'S KNOWN PROBLEM, inherited deliberately:** odds history is keyed
  `event_id|home_team|away_team|market|bookmaker` with **no side and no line**;
  the side lives as `entity` INSIDE the history points. The opening ledger keys
  on `event_id|market|player|segment|side|line|bookmaker`. Mapping `side` ->
  `entity` is the unsolved half and must be measured against real data, not
  assumed — the settlement join already failed exactly here (4,560
  `no_key_match` of 8,276).
- **The close is the easy half and is already available:** stamped
  `closing_line` on only ~1.7% of markets, but `history_points > 0` on 100%, so
  derive it from the last pregame observation and LABEL which one was used
  (`observed_transition` vs `last_pregame_quote`) plus `close_age_seconds`.
- Goal: audit §7 ranked fix **#1** — produce `clv_pct` per recommendation with
  no dependency on grading, outcomes or `settle_result`. The audit calls this
  the one measurement that unblocks §4's threshold, §6's cadence decision, and
  every "where should modelling effort go" question.
- **READ-ONLY SO FAR. No files claimed, no code changed.**

**FINDING 1 — the CLOSE side is in far better shape than the audit implies,
but not where it says.** `[measured 08-14 21:3xZ via /api/ops/odds-history/inspect]`

      sport/date        markets   closing_line STAMPED   history_points > 0
      mlb  2026-08-13       1074          18  ( 1.7%)        1074 (100%)
      wnba 2026-08-13        119          11  ( 9.2%)         119 (100%)
      mlb  2026-08-14       3361           0  ( 0.0%)   (no transitions yet)

  The stamp fires only when the pregame->live transition is OBSERVED
  (`odds_refresh_tracking.py:1599` requires `was_confirmed_pregame` and a prior
  `is_live is False`). Only 81 of 1074 MLB markets were ever seen live at all.
  **Building the join on the STAMPED close yields ~18 rows.** But every market
  has history (median 20 points), so a close is DERIVABLE for ~100% by taking
  the last pregame observation before `commence_time`.
- **Design consequence:** the two are NOT the same measurement and must never be
  mixed silently — the `book_margin_model` lesson. A CLV row must carry
  `close_source` = `observed_transition` (gold, ~2%) vs `last_pregame_quote`
  (derived, ~100%) plus `close_age_seconds` = commence_time - captured_at, so a
  close taken 2h early (the pregame sweep cadence) is visible as such.

**FINDING 2 — THE BLOCKER. The OPENING side is effectively unavailable, and the
audit's premise that this is reachable "without touching the 367 MB chunk path"
does not hold.** `[measured 08-14]`
  - `data/prediction_ledger.json` holds **3 records** (it is the portfolio's
    positions — the `pending_count: 3` on `/api/portfolio/summary`), NOT the
    8,276 recommendations.
  - The 8,276 recommendation records WITH their opening `quote` are written to
    `evaluation_ledger_chunks/<date>.jsonl` — the 367 MB path.
  - `board_state_ledger_recorded_fingerprints` is only per-date HASHES; it
    records THAT a board state went into those chunks, not the openings.
  - **The chunks are not merely expensive, they are being SKIPPED at read time.**
    Observed in refresh-worker logs 21:24:54Z:
    `[intelligence_evaluation] SKIP_OVERSIZED_LEDGER_CHUNK path=2026-08-05.jsonl
    bytes=367229260 ceiling=256000000`. And 19 of 21 dates do not exist at all.
  - So openings are unreadable for every date, including the two that exist.

**THE DECISION THIS NEEDS (not mine to take alone — it is a build):**
  - **(a) Record a compact opening snapshot going forward.** One small JSONL per
    date, first-sighting-only per `market_id`: sport, market, side, price,
    bookmaker, books_quoting, fair_prob, model_prob, captured_at. Bounded by
    distinct market_ids/day (~3.4k for MLB), so kilobytes, not 367 MB. The
    joiner then needs no chunk access at all. **Cost: first real CLV number is
    ~24h away, not today.** This is what "unrecorded is unrecoverable" implies.
  - **(b) Recover openings from the 08-05/08-06 chunks.** Rejected unless
    overridden: they exceed the read ceiling and are already skipped, so this
    means raising a guard that exists for OOM reasons on a 4 GB worker, to
    recover 2 dates.
- **Recommendation: (a).** It is the audit's own "smallest change that starts
  capturing CLV" once Finding 2 is accounted for, and it does not touch the
  memory-sensitive path the two OPEN memory lanes are working.
- **NEXT ACTION:** get a decision on (a) vs (b). If (a), claim
  `pipeline/intelligence_state.py` (writer) — **currently held by
  `layer2-board-freshness`, so that lane must be consulted first.**
- Files: none claimed yet, deliberately.

### quote-join-enrich-cost — FOLLOW-UP 2026-08-14 04:37Z — the fix HOLDS, the workload OUTGREW it

- **UNION-NARROWING ANALYSIS 2026-08-14 05:0xZ — TRACED, NOT SHIPPED. Read the
  equivalence warning before writing any of it.**
  - **Where the ~12k rows/call come from.** The union is
    `by_event | by_player | team_groups`
    (`odds_book_quotes.py` ~1292-1307). For a GAME row, `wanted_teams` pulls in
    **every quote row for that game** — every market x every book x every
    selection. That branch dominates; `by_event` and `by_player` are narrow.
  - **OPTION A — market prefilter.** The caller already passes `market`. A
    `by_market` index intersected with the union would cut it by roughly the
    markets-per-game factor (potentially 10x+).
    **NOT equivalence-preserving.** Today the order is identity FIRST, then
    market narrowing with `candidates = narrowed or candidates`. That trailing
    `or` means a market-vocabulary mismatch **falls back to every row of the
    game**. Prefiltering by market removes that fallback: rows that today
    return a same-game quote would return `None`.
    Arguably MORE correct — but it is a silent-failure join, and the decision
    to drop the fallback must be made deliberately, not as a side effect of an
    optimisation.
  - **OPTION B — skip `team_groups` when `by_event` or `by_player` already hit.**
    Team matching is the FALLBACK identity signal; when `event_id` matched, its
    rows are the same game anyway. Same objection: it changes which rows reach
    `identified`, so it is not equivalence-preserving either.
  - **WHY NEITHER WAS SHIPPED TONIGHT.** The original `#414` index was safe
    because it was PROVABLY equivalent — 30+ query shapes asserted identical
    against a full-scan reference, exercising `by_event`, `by_player`,
    `by_teams_fallthrough` AND `no_identity`. Both options above deliberately
    change the identified set, so a differential test cannot pass; they need a
    test that PINS the new semantics, plus an explicit answer to "is losing the
    market fallback intended?".
  - This function's own docstring is the reason for the caution: *"a missing
    quote is visibly missing, a wrong one silently misprices the card and, once
    `#213` records it at bet time, poisons CLV."*
  - **RECOMMENDED ORDER for whoever takes it:** (1) decide the fallback
    question — it is a product call, not a performance one; (2) write the test
    that pins the chosen semantics; (3) then implement. Doing 3 first is how a
    silent mispricing ships.

- **The `#414` index is still doing its job.** 833,619 rows walked against a
  13,215,068-row shard = **6.3% scanned**, ~16x reduction, consistent with the
  21.5x measured at 00:18Z. It has not degraded.
- **But per-game cost is climbing again: 7-8s -> 14.70s.** Fresh MLB readings:
  ```
  04:37:09  total 14.70s  walked  833,619  shard 13,215,068  calls 69
  04:29:34  total  9.12s  walked  760,417  shard 12,832,072  calls 44
  04:15:55  total  4.76s  walked   16,642  shard     49,172  calls  2
  ```
- **TWO separable drivers, and neither is the index failing:**
  1. **Call count 20 -> 69 per game.** More candidates enriched — good for board
     richness, linear in cost.
  2. **Cost per call 0.2755 -> 0.7346s (2.7x).** The shard grew again:
     **~191k rows/call now**, against ~216k earlier and ~83k yesterday
     afternoon. 6.3% of a bigger shard is still more rows.
- `join` is **14.69 of 14.70s**; `post`, `score` and `unattributed_s` are all
  0.00. The segment split is clean and the join is the entire cost — same shape
  as before the fix, at a lower level.
- The two small games at 04:15 (3.95s / 4.76s on a 49,172-row shard) confirm
  cost tracks shard size closely, which is what a join-dominated profile
  predicts.
- **NEXT LEVER, unchanged from what this lane already named: the residual ~12k
  rows walked PER CALL.** Indexing removed the full-shard scan; what remains is
  a linear pass over the candidate union, and at 69 calls a game that is ~833k
  row visits per game. Narrowing the union, or making the per-row test cheaper,
  is the remaining work.
- **Do not read this as a regression of the fix.** Without the index those same
  games would walk 13.2M rows instead of 833k. The lane's verification stands;
  this records that the win is real and eroding under growth.

### quote-join-enrich-cost — PRODUCTION RESULT IN 2026-08-14 00:18Z — the index works, 21.5x measured

- **Both profilers fired at 00:11:15 and 00:18:46Z**, after
  `SYNDICATE_SLOW_ROW_TOTAL_SECONDS=1` / `SYNDICATE_SLOW_ENRICH_TOTAL_SECONDS=1`
  were set on refresh-worker (both were absent, defaulting to 5s — at which the
  instruments could never fire if the fix worked).
  ```
  SLOW_SEGMENT_PROFILE  total_s=7.17 tail_s=7.17 enrich_block=7.17
                        rows_walked=502,157  shard_rows=10,806,750  calls=50
  SLOW_ENRICH_PROFILE   total_s=7.17 join_s=7.16 post_s=0.00 score_s=0.00
                        accounted_s=7.17 unattributed_s=0.00
                        candidates=26 join_calls=26 join_s_per_call=0.2755
  ```
- **READ THESE COUNTERS AS CUMULATIVE, NOT PER-CALL.** `_bump` accumulates
  across the window, so `shard_rows` is 50 calls x ~216k, not a 10.8M-row
  shard. Per call: **216,135 rows before -> 10,043 walked now = 21.5x
  reduction, measured in production.**
- **Board-build cost 21-54s -> 7-8s.** The `#414` cause is fixed.
- **Not the 130x measured locally, and the same line says why: the shard GREW.**
  ~83k rows/call this afternoon -> ~216k now (2.6x). The index is working
  against a target that got bigger. Quote the 21.5x, not the 130x.
- `unattributed_s=0.00` — the segment accounting is complete, so the split is
  trustworthy.
- **`join_s` is still 7.16 of 7.17s.** The join remains essentially the entire
  cost; it is just 3-7x less of it. **The next lever is the residual ~10k
  rows/call, not the scan that is already gone.** Do not re-optimise the scan.
- Verification for this lane is now MET in production. What remains open is
  only whether 7-8s is acceptable, which is a different question.

### ask-sport-coverage — OPEN — ROUTING WIN LIVE + MEASURED 25->38/52 ZERO REGRESSIONS; K6 FIX IN origin/main BUT UNDEPLOYED (riding along, predicate UNMEASURED); SOCCER/NCAAB/NHL UNPROVEN ON DATA — opened 2026-08-15 — session: ask-sport-coverage
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
  - `syndicate/blueprints/ask_the_syndicate_data.py`
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

### soccer-model-coverage — OPEN — BACKTEST DELIVERED (MODEL LOSES TO MARKET, 1,112 matches, gap +0.0139); 4 FIXES BUILT + TESTED, NONE COMMITTED; #2 DELIBERATELY HELD; CALIBRATION HARNESS NEVER RUN ON REAL DATA — opened 2026-08-15 — session: soccer-model
> **DEPLOY STATUS UPDATE 2026-08-15 22:3xZ (coordinating session, no claim).**
> The **soccer as-of pair IS NOW LIVE** on live-odds-worker (`25774aaf`,
> 22:09:15Z) — `allow_undated` present in 5 places in
> `soccer/features/loaders.py`, verified by content in the deployed tree, with
> `191a001b` an ancestor so nothing was dropped. Both halves shipped together,
> so `50fd7fe2`'s MLS-emptying regression cannot recur. This supersedes the
> earlier note here saying it was built but undeployed.
> **Unchanged:** fixes #1 (seed bootstrap) and #3 (accent join) are still NOT
> committed by this lane, and **#2 (3-way de-vig) remains deliberately HELD** by
> user decision — the model measures worse than the market (Brier 0.5875 vs
> 0.5737, worse in 8 of 9 leagues) and its errors sit on favourites.
> **CROSS-LANE, added 2026-08-15 ~21:5xZ by the coordinating session (no claim).**
> The soccer **as-of pair** (`0b0d44d9` + `f05a21c4`, audit §7 #6) is on
> `origin/main` and is built into `deploy/low-props-soccer-asof-2026-08-15`
> (`25774aaf`) together with the prop `0.5` fix — but **it is NOT deployed**.
> live-odds-worker has been `HOLD` for 26+ minutes (odds refresh + rolling
> soccer builds) so no lull was found. **Take both commits or neither**:
> `50fd7fe2`, the first half, once emptied MLS ratings in production on its own.
> Route one (warm the mirror, then deploy) is armed for that service and is the
> proven technique — see `state.md`.
> **CLAIMS RELEASED 2026-08-15 AT SESSION ARCHIVE — the lane is NOT done.**
> Owning session `soccer-model` is being archived deliberately, so its file
> claims are released rather than left as an orphaned lock. This is the same
> failure mode this lane inherited from `soccer-projection-gap`; releasing on
> the way out is the fix.
> **THE WORK IS UNFINISHED AND LIVES UNCOMMITTED IN THE SHARED WORKTREE** — 9
> files, listed in `log/2026-08-15.md`. Anyone taking these files must read the
> RECONCILIATION and RECIPE CORRECTION blocks below first: `loaders.py` depends
> on the orphaned `soccer-backtest-leakage` as-of work, which `origin/main` does
> not have. **Do not `git checkout` or revert these paths casually** — that
> discards a day of tested work that no branch holds.
> **To resume: `/lane open soccer-model-coverage` and re-take the files.**
> Everything below is measured unless labelled otherwise, but re-verify before
> relying on it.
- Goal: soccer carries a REAL model on the published board. **Testable outcome:**
  `/api/board/layer2-shortlist` reports soccer rows with `model_edge_pct`
  non-null at a rate > 0 (today: `rows_with_model_edge: 0`,
  `unmatched_match_rows: 8,393` against `matches_in_source: 4`), AND a
  leak-free soccer backtest number exists for at least one league.
- **FIRST QUESTION, BEFORE ANY BUILD — the headline number is disputed 250x.**
  Two production endpoints, same sport, same date, 45s apart `[measured
  2026-08-14 19:1xZ by session model-audit]`:
  - `/api/board/layer1?sport=soccer` — rows 8,456, `rows_with_projection` 2,504 = **29.6%**
  - `/api/board/layer2-shortlist` — rows 8,512, `rows_with_projection` **12** = **0.1%**,
    `rows_with_model_edge` 0, `matches_in_source` 4, `unmatched_match_rows` 8,393
  These are two different joins and **at most one describes the board a user
  sees.** Settle which before building. If the defect is the layer2 join rather
  than projection coverage, raising coverage fixes nothing and this lane's
  shape changes.
- Hypothesis (H1): the layer2 ingest's match-key join is broken/starved
  (`matches_in_source: 4` is not a coverage number, it is an empty source), and
  projection COVERAGE at 29.6% is a separate, less urgent fact.
- Hypothesis (H2): `SOCCER_PLAYER_ROWS_MISSING league=eredivisie|primeira_liga|
  championship` `[live-odds-worker logs 19:25Z, observed once, LEAD not finding]`
  means the sim's own input is absent, so the projections that would feed either
  join are not being produced for those leagues.
- Falsification test: for H1 — if `matches_in_source` rises with no change to
  projection coverage and `rows_with_model_edge` stays 0, the join is not the
  binding constraint. For H2 — if a league that DOES project has an equally
  empty `players/` dir, the log line is not diagnostic.
- Verification: production `layer2-shortlist` counters re-read after the change,
  plus a leak-free backtest number computed with per-match as-of ratings and its
  per-family date coverage + intersection printed alongside.
- Blocked by: none. **Coordinate with UI Lane G (soccer card end-to-end) — the
  UI plan's G4 says to run these together.**
- **SCOPE FENCES, measured, do not rediscover:**
  - `player_shots` / `player_shots_on_target` map to a **mean**;
    `soccer_projections` refuses by design to derive a probability from a mean,
    and the rows are 100% one-sided so `_no_vig_over_probability` returns None.
    `player_to_receive_red_card` / `player_assists` are not in the market map.
    **These markets can never carry an edge.** Scope around, not into.
  - **MLS cannot be backtested from its current source at all** —
    `fetch_asa_mls_team_history` returns undated season aggregates; a season
    average already contains the season. Needs a per-match source that does not
    exist here.
  - **Soccer `game` odds are frozen platform-wide** (stop at 2026-08-10T20:54:06,
    all leagues); only `prop` rows are fresh, from a different producer.
  - `data/soccer_source/*/validation/*_backtest_*.csv` are **NOT CITABLE**
    (leakage, retired). Soccer backtest accuracy is **unmeasured** until this
    lane produces a leak-free number.
  - The models lane's uninformative-EV filter keys on
    `fair_method == "book_margin_model"` and **self-heals** — do not try to
    defeat it.
- Files (exclusive to this lane):
  - `syndicate/features/soccer/`
  - `scripts/build_soccer_artifacts.py`
  - `scripts/validate_soccer_vs_market.py`
  - `scripts/backtest_soccer_live_lens.py`
  - `tests/test_soccer_feature_loaders.py`
  - `tests/test_soccer_projections.py`
  - `tests/test_soccer_adapter.py`
  - `tests/test_build_soccer_artifacts.py`
  - `syndicate/features/shared/soccer_projections.py`
  - `scripts/run_live_odds_refresh_worker.py`
  - `tests/test_soccer_three_way_devig.py`
  - `tests/test_soccer_seed_bootstrap.py`

- CLAIM WIDENED 2026-08-15 02:5xZ: `soccer_projections.py` lives under
  `features/shared/`, not `features/soccer/`, and the player-props root cause is
  in the live-odds-worker ENTRYPOINT. Checked against every OPEN lane's parsed
  claims before taking them: neither is claimed. `run_refresh_worker.py` is
  deliberately NOT claimed — the `#435` session is live on that service.

- NOT this lane's files (held by live sessions, read-only here):**
  `syndicate/features/shared/recommendation_engine.py`,
  `syndicate/features/shared/layer2_board.py`,
  `syndicate/features/shared/layer1_board.py`,
  `syndicate/features/shared/opportunity_signals.py`,
  `pipeline/intelligence_state.py`, soccer card templates and `board_cards` CSS.

### commit-guard-reads-wrong-index — CLOSED 2026-08-16 — the guard read the MAIN worktree's index while the commit used another one — session: `live-gameline-eval`
- Goal: `commit-guard.py` evaluates the index the COMMIT will use. **DONE.**
- Files: `.claude/hooks/commit-guard.py`, `tests/test_commit_guard_worktree_index.py`.
  Neither claimed by any OPEN lane at the time of the edit.
- **The bug.** Both predicates ran with `cwd=CLAUDE_PROJECT_DIR`. The commit runs
  wherever the shell is — and this repo's own documented recipe for a contended
  tree is `git worktree add` and commit from there. A linked worktree has its own
  index and its own HEAD.
- **Two opposite failures, and the SECOND is the one that mattered:**
  - *False positive*, observed **3× in one session**: a session committing from
    `/c/tmp/lgl-ck` was blocked over reverts staged in the MAIN index while its
    own index held exactly its four intended appends.
  - *False negative*, **never observed and strictly worse**: a stale index in the
    worktree being committed from was never examined, so the guard would pass it
    in silence. That is the entire hazard it was written to catch.
- **`-C` is now checked instead of skipped.** The old code waved
  `git -C <dir> commit` through because it "has its own index". **Having your own
  index is not having a fresh one** — that conflation is what this guard exists
  to catch, so it cannot be the reason to skip. `--git-dir` / `--work-tree` stay
  skipped and are now named as a KNOWN GAP: index and tree decouple there, so
  predicate 1's "is it still on disk" has no single correct base.
- **Verification — falsified, not just asserted.** 13 tests on REAL git repos in
  `tmp_path` (a mocked git reproduces nothing; the bug was which directory git
  ran in). Against the pre-fix hook: **7 fail, 6 pass**, and the load-bearing
  `test_a_stale_index_in_the_LINKED_worktree_is_caught` fails as `assert 0 == 2`
  — the false negative, reproduced. Against the fix: **13 pass.**
- **Honest limit on the end-to-end check.** The real hook binary was run on the
  real payload shape and returned 0, but the shared index happened to be CLEAN at
  that moment, so **that reading is not a positive control** — it cannot
  distinguish the fix from the bug. The positive control is the pytest pair on
  real repos. Deliberately staging a revert in the live shared index to produce
  one would have created the exact landmine the guard exists to prevent.
- Blocked by: none.

### live-game-line-projection — OPEN, UNOWNED (session `live-gameline-eval` checkpointed 2026-08-16 15:2xZ) — **BOTH HALVES SHIPPED AND v2 STILL UNEXERCISED. THE PLUMBING IS DONE TWICE OVER; THE EVALUATION HAS NOT STARTED.**

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
### live-game-line-projection — RE-TAKEN 2026-08-16 03:0xZ (session `live-gameline-eval`)
- Goal: make the ledger capable of producing a sample at all, and make its
  counters readable without streaming a 10 MB artifact. Success = one live slate
  where `live_gameline_ledger.written > 0` and the counters are reachable from
  an API.
- Files: `syndicate/features/shared/live_gameline_ledger.py`,
  `syndicate/features/shared/live_gameline_join.py`,
  `syndicate/blueprints/intelligence.py`, `tests/test_live_gameline_ledger.py`.
  Checked against every OPEN lane's `- Files:` at re-take: no lane claims any of
  them. `refresh-worker-oom-recurrence` names `syndicate/features/intelligence.py`
  as an expected candidate — a DIFFERENT file from `syndicate/blueprints/intelligence.py`.
- Deploy intent: **PREPARE ONLY.** The recorder runs on refresh-worker, and
  `refresh-worker-oom-recurrence` has an explicit hold on deploys to that service
  until its attribution is written. Request file, not a deploy.
- Verification: written to `deploys.md` with the window stated.
- Blocked by: refresh-worker deploy hold (`refresh-worker-oom-recurrence`) for
  the recorder half only. The web half is unblocked.
- **Took `.syndicate/.current-lane` from `refresh-worker-oom-recurrence`** — one
  single-valued marker, N sessions, the known root cause. That lane claims no
  files, so the cost is bounded.

**MEASURED 2026-08-16 03:00–03:1xZ on a LIVE slate (2 games live, 13 final).**
Source: the `book_grid_2026-08-15.json` artifact streamed from web
(`/api/ops/artifacts/stream`, 9,953,474 bytes, `generated_at 03:00:00.538Z`) and
`/mlb/api/live-lens` at 03:00Z. Both read at the same instant, both post-date
`f8ca54e1`.

    live_gamelines       considered 8  projected 2  priceable 0  edged 0
                         withheld 8 = {segment_is_not_full_game: 6,
                                       prob_interval_swamps_edge: 2}
                         index_size 10
    live_gameline_ledger candidates 0  written 0  enabled true

1. **`index_size` IS EXPLAINED. It is not a live-game count and nothing is
   wrong.** It counts snapshot games carrying a `live_mc` lens. Census at 03:0xZ:
   **10 of 15 games carry one — 8 FINAL and 2 LIVE.** A Final keeps its last
   `live_mc` lens, so the number is monotone through a slate: 3 → 8 → 10 is just
   how many games had gone live-or-through-live by each read. **The join loop
   filters on `game.state == live` on the GRID side, so the Final entries are
   never used** — the counter is misleading, not the join. Retire the "unexplained"
   framing; the defect, if any, is that this is the one counter in the block with
   no denominator, which is exactly what invited the wrong reading.
2. **THE RECORDER CANNOT PRODUCE A SAMPLE, AND THIS IS THE REAL BLOCKER.**
   `build_records` skips any row that is not `priceable`; `priceable` requires the
   edge to clear a 2σ bar at 120 sims. Tonight that is **0 of 8**, so
   `candidates: 0` — the ledger was never asked to write anything. **The
   scheduled `live-gameline-ledger-check` will very likely read `written: 0`
   again tomorrow, and that will mean neither "broken" nor "working."**
3. **The filter's stated justification is wrong by three orders of magnitude.**
   The docstring refuses non-priceable rows because "recording thousands of
   refusals per build would bury the handful CLV can score." The measured
   population is **8 rows per build, 2 of them projected.** There are no
   thousands. Recording every PROJECTED row costs ~2 records/build against a
   20,000-record file cap, and it is the difference between a sample and none.
4. **`liveStateAsOf` and `liveStateCarriedForward` are `None` on all 10 lensed
   games, including the 2 live ones.** Consistent with "Drop 2's carry-forward has
   never fired" AND with "the stamp is only applied on the carry-forward path."
   **Not disambiguated — do not record either as established.**

**BOTH HALVES ARE NOW DEPLOYED — 2026-08-16 04:2xZ. `DEPLOYED NOWHERE` below is
SUPERSEDED; the rest of that block still reads true.**
- web `ebd5f677` live 03:38:07Z — the counters are served. Measured null -> object
  across two artifacts.
- refresh-worker `5c419007` live 04:24:33Z — ledger v2. **Deployed and NOT YET
  EXERCISED:** the slate ended between the last pre-deploy build and the first
  post-deploy one, so `considered` went 4 -> 0 and v2 has had no live row to act
  on. Both parented on their service's LIVE SHA, never on main.
- The `refresh-worker-oom-recurrence` hold cleared on its own evidence
  (`9ed17262`: a ~2 GB transient, not a leak) rather than being overridden. I
  asked that session first; it archived between the question and the answer.

**CORRECTION TO THIS LANE'S OWN FINDING #2 ABOVE — read it before quoting the
arc.** "The recorder has never recorded a row" is **FALSE**. The 04:22:51Z
pre-deploy build read `priceable 1, candidates 1, skipped_unchanged 1`, and
`skipped_unchanged` cannot be non-zero unless a matching record already sits on
disk — an empty file always writes, because `_moved(None, rec)` is True. **v1
wrote at least one row tonight**, between 02:4xZ and 04:22Z. The 03:00Z reading
was real and I generalised it to a night. v2's premise survives (1 priceable of 4
considered is a self-selected sample), but "it structurally could not write" was
an overclaim.

**NEXT ACTION is now purely measurement, and the plumbing question is closed.**
`live-gameline-ledger-check`, 20:30 Central 08-16, on a full slate:
`written > 0` on one build, then **`skipped_unchanged > 0` on a later one** —
the second is the real test, and note it has ALREADY been observed once under
v1, so the discriminator for v2 is `written` rising on rows that are NOT
priceable. Read across two builds, never once.

**CHECKPOINT 2026-08-16 03:4xZ.** Shipped to `origin/main`, DEPLOYED NOWHERE:
`c87f6634` (ledger v2 + the book-grid pass-through + 2 test files),
`bbc70d16` (the two deploy requests), `4e82d4b7` (the learnings rule).
97 tests pass, and the pass-through was falsified first — commenting out the two
served keys fails all 6 new tests.

**THE ONE THING THAT DECIDES WHETHER TOMORROW IS A TEST:** the v2 recorder must
be on refresh-worker before the scheduled `live-gameline-ledger-check` fires at
**08-16 20:30 Central**. Against v1 it reads `written: 0` again and means nothing.
That deploy is HELD by `refresh-worker-oom-recurrence`, deliberately — the hold is
correct and the deadline is real, and only the user can trade them off.

**NEXT ACTION for whoever picks this up:** not code. Get the refresh-worker
deploy decided. Everything after it is measurement:
`live_gameline_ledger.written > 0` on one build, then `skipped_unchanged > 0` on
a later one — **the second is the real test**, because the append proving it
writes is not the dedup proving it writes only on movement. Read it across two
builds, never once.
**Lane stays OPEN** — the projection ships, but nothing yet says the edges are good.

**SHIPPED AND LIVE (content-verified per service, not by ancestry):**
- live-odds-worker `c4116ab6` — the live MC stamps `simsRun`.
- refresh-worker `f8ca54e1` — the game-line join, the segment filter, the
  Agresti-Coull boundary, and the CLV recorder.
- web carries D1+D2; it needs neither the vendor stamp nor the join.

**THE ARC, in measured numbers:**

    baseline   index 3   projected 12  edged 0   (sim_count_unusable 12)
    +simsRun   index 8   projected 32  edged 25  <- FIRST EVER, and WRONG
    +segment   index 10  projected  5  edged 4   <- first credible ones
    tail       index 10  projected  2  edged 0   (slate over; ledger written 0)

**THE 25 WERE FAKE AND I RETRACTED THEM MYSELF**, caught while packaging them
for handoff: Wald `sqrt(p(1-p)/n)` is **0.0 at p in {0,1}**, so the 2-sigma bar
was ZERO and everything cleared it; and the full-game projection was priced
against every SEGMENT (SD @ CLE `first1` gave **+42.43 pp**). Both fixed.

**WHAT IS NOT ESTABLISHED — do not let the arc imply otherwise:**
- **No CLV, no settlement, no backtest.** Surviving means an edge exceeds the
  ESTIMATOR'S OWN NOISE at 120 sims. It says nothing about the model.
- **The recorder has never recorded a row** — it went live on a finished slate.
  `written: 0` with `enabled: true` proves wiring, not behaviour.
- **`index_size` 3 -> 8 -> 10 across the night is unexplained.**
- **Drop 2's carry-forward has never been observed firing.**
- The tally is MLB-only; soccer/wnba report `liveMcSources: null`.

**HANDOFFS, all verified present in HEAD:**
- `clv-without-settlement` — the rows are TRANSIENT (edged 25→4→1 on one slate);
  the recorder is the prerequisite, and `clv_join.py` was deliberately untouched.
  Carries two corrections: **Pinnacle is 15/30 in production** (the sharp SET is
  30/30), and "close" is ill-defined for a live market.
- `memory-watchdog-435` — a **2,092 MB** in-process excursion, pid 39, 34 s,
  children proven flat. ~3x `#327`'s largest.
- `soccer-model-coverage` — `SOCCER_PREGAME_AUTORUN_FAILED` lock contention.

**COSTS I IMPOSED, recorded rather than netted out:** three soccer runs killed,
one wrong rollback of a working fix, and two deploys fired over another
session's claim. **No claims held; refresh-worker and live-odds-worker are free.**

**NEXT SESSION STARTS HERE:** tomorrow's live slate is the first real test —
does the ledger grow only on movement, and do the surviving edges beat a sharp
close. **That is evaluation, not plumbing.** The plumbing is done.

### refresh-worker-oom-recurrence — OPEN — **ATTRIBUTED, NO DEPLOY MADE. `#435` did NOT regress (`c67f7373` is an ancestor of live `f8ca54e1`; the ledger's `2,869 -> 1,071` is the book_quotes READ, not container anon — different quantities). The kill is a ~2 GB TRANSIENT, not a leak: 22 excursions over 5 deploy-free windows, amplitude FLAT all night, every cycle reaches headroom 0.0, and the two kills are the two thinnest-page-cache cycles (inactive_file 26.3 / 42.2 MB vs 164–240 MB surviving). Measurement in `deploys.md`. ALSO THIS SESSION: adjudicated the stale shared index (3 revert-in-waiting blobs disarmed, incl. one that would have stripped the LIVE Drop 3 hook), notified the 2 reachable live sessions, and FIXED `commit-guard.py` to gate on the staged BLOB rather than name-status — 4-case falsification suite passes, 5273ms -> 659ms. OPEN because the allocator inside the 2 GB pass is still UNNAMED and needs an in-pass measurement, which needs a deploy, which needs the clean window (42.8 min at 03:19Z) to mature first** — opened 2026-08-16 — session: refresh-worker-oom-recurrence
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

### clamp-fix-to-workers — OPEN — **CHECKPOINTED 2026-08-16 01:4xZ. refresh-worker SHIPPED `57a437d5` (live 00:23:04Z, 0 clamp sites by content). live-odds-worker DEFERRED by user decision — `079cc42b` ready, re-cut before shipping. THE ONLY OPEN WORK IS VERIFICATION: 2 post-deploy reads (00:24Z, 01:30Z) both `no_trigger`, which proves nothing** — opened 2026-08-15 — session: clamp-fix-verification-watch
- Goal: the ±4900 clamp stops being published. **Testable outcome:**
  `py -3 scripts/watch_clamp_trigger.py --once` returns `POST_FIX_OK` on a slate
  that carries an out-of-clamp probability.
- **WHY THIS LANE EXISTS — the web deploy was falsified.** `e831263e` shipped the
  fix to web on 2026-08-15 and production kept mispricing. Measured 23:10:13Z
  (nfl `h2h_3_way` 0.014698 → +4900, correct +6704) and 23:15:46Z (mlb `spreads`
  0.009911/0.990089 → ±4900, correct ±9990) — two triggers, two unrelated slates,
  both `PRE_FIX_MISPRICE` against a fix-carrying web SHA.
  `reports/clamp_watch/trigger_20260815T2310*.json`, `..._231546*.json`.
- **The runbook's "WEB SERVICE ONLY" was wrong, and the reason is instructive.**
  It inferred serve-time stamping from "0 of 108 shortlist-artifact rows carry
  `fair_price`" — true, and about the WRONG ARTIFACT. The shortlist has no
  `fair_price` at all; the intelligence-state card does. Web's block is a
  **backfill** (`if ... card.get("fair_price") is None`), so an upstream-clamped
  value passes through untouched and the web fix is structurally inert.
- Files: `pipeline/intelligence_state.py`, `syndicate/features/wnba/cards.py`.
  - **`syndicate/features/shared/layer2_board.py` DELIBERATELY NOT TOUCHED** — it
    is claimed by OPEN `spread-line-sign-convention`, and that lane's worker
    deploy already carried the layer2_board fix to both workers. Collision found,
    then dissolved by re-measuring rather than by negotiating. 3 sites → 2.
  - Collision check on the two: `clv-without-settlement` claims no files;
    `ask-sport-coverage` lists `intelligence_state.py` read-only;
    `soccer-model-coverage` lists both as "NOT this lane's files". CLEAR.
- Hypothesis: n/a — the producer is established by content, not guessed.
- Falsification test: if refresh-worker deploys with 0 clamp sites and a
  subsequent trigger still reads `PRE_FIX_MISPRICE`, the producer is NOT the
  intelligence-state loop and this attribution is wrong.
- Verification: `watch_clamp_trigger.py --once` → `POST_FIX_OK`, plus 0 clamp
  sites by content at the new live refresh-worker SHA.
- **Blocked by: the refresh-worker deploy claim**, held by `red-intelligence-tests`
  (target `037eb356`, since 23:35:01Z), which still carries both sites.
  `send_message` is unavailable from this scheduled-task session, so the claim
  was NOT taken and no coordination message could be sent. Waiting for release.

- **RESULT 2026-08-16 00:23:04Z — refresh-worker shipped `57a437d5`.** 0
  occurrences of `max(0.02, min(0.98` across all three files at the live SHA.
  Cut on live `2c14d9ae`, not main. Gated on `safety_rc == 0 AND zero [JOB]
  processes`, re-verified in the same shell command as the POST.
- **VERIFICATION DID NOT HAPPEN AND IS NOT CLAIMED.** 00:24:04Z read: `rows=12`,
  p=[0.338468, 0.603175], `out_of_clamp=0` → `no_trigger`. The slate collapsed
  from 97 rows as games finished. Same reading a quiet slate gives with the bug
  fully present. The 2-hourly `clamp-fix-verification-watch` task carries this.
- **`live-odds-worker` DEFERRED, not forgotten.** It carries the clamp but does
  not run the intelligence-state loop, so it is not the producer of the measured
  misprice. It is also effectively never idle — 57 samples over 35 min, zero
  job-free moments, running a per-league soccer artifact sweep. `079cc42b` is
  cut, tested and pushed; re-cut on the live SHA before shipping.
- **CORRECTION LOGGED: I twice called live-odds-worker "already fixed" off a
  PENDING claim target.** `49797f4b` was clean and never landed as-is; `c422f79a`
  then `c4116ab6` landed instead, both still clamping. **A claim's target is an
  intention, not a deployment.** Verify by content at the live SHA, every time.
- **TWO SAFETY-TOOL DEFECTS, both in `learnings.md` 2026-08-16:**
  `check_deploy_safety.py` reports CLEAR while jobs run on the service (measured
  on BOTH workers), and has no `--service` flag so it also blocks on the wrong
  service's work. And a wait loop of mine read a stderr HTTP 502 as CLEAR by
  testing for the absence of a failure string.
- **2026-08-16 03:1xZ — THE INSTRUMENT WAS BLIND IN THE WINDOW IT WATCHES, and
  every `no_trigger` since it was built is weaker evidence than it looked.**
  `watch_clamp_trigger.py` gated the confirming read on
  `/api/board/layer2-shortlist`, then judged `/api/intelligence/query`. Two
  different populations. Measured same-instant at 03:14:08Z: **shortlist 0 rows,
  served payload 18 priced rows** — 8,345 opportunities considered and all 8,345
  filtered out (horizon 2,488 + stale_kickoff 2,666 + quote_age 1,256 +
  excluded_market 689 + uninformative 1,246, summing exactly).
  The shortlist drops `stale_kickoff_seconds = 7200` and
  `max_quote_age_seconds = 50400` — **exactly the in-play late-game population
  both real triggers came from** (20:45Z, and 23:10/23:15Z at p=0.009911/0.990089).
  So the gate could read 0 while a misprice was live on a row it had filtered out.
  Found because the user disbelieved a `rows=0` reading, not by the instrument.
- **FIXED, not just recorded.** The trigger now derives from the served payload
  itself — the same surface the verdict judges. The shortlist is still read, as
  recorded context that can no longer suppress a check; both counts print.
  Self-test 11/11. Live at 03:24:19Z: `served_rows=30 (shortlist=12)`, so the
  old gate would still have judged on under half the population.
  - A defect found while writing it: emitting UNPRICED probabilities (needed, or
    `POST_FIX_OK_COLUMN_ABSENT` is unreachable and the fix working becomes
    invisible) double-counted every quoted row — once priced at the parent, once
    unpriced at the `quote` node. Harmless while only pairs were emitted; a
    phantom unpriced twin on every correctly-priced row the moment they were not.
    Caught by the new self-test, not in review.
- **STILL NO VERDICT ON THE FIX.** 03:24:19Z read the corrected population:
  30 rows, p=[0.057749, 0.871508], nothing outside [0.02, 0.98] → `no_trigger`.
  Genuinely quiet, now measured on the right surface. `#439` item 1 stays OPEN.
- **THE SHORTLIST/SERVED MISMATCH IS NOT A DEFECT — AND THAT IS WORSE FOR THE
  OLD GATE THAN "NARROWER" WAS.** Measured 03:3xZ, same instant. They are two
  different pipelines, not two views of one:
  - **Different date window.** shortlist `date: 2026-08-15`, `horizon_days: 1`
    (single date, `central_today_iso()`); served `dates_covered:
    ['2026-08-15','2026-08-16','2026-08-17']`. Late at night the shortlist's
    one-day horizon empties by construction while tomorrow's board is live —
    which is exactly the 0-vs-18 reading, and it will recur every night.
  - **Different pool.** served `source: combined_board_window` (the legacy
    `ranked_all` pool). The shortlist is `layer2_shortlist_artifact`.
  - **Different gates.** horizon / quote_age / stale_kickoff / excluded_market /
    uninformative are applied at BUILD time on refresh-worker for the shortlist
    only; `combined_board_window` does not carry them.
  This is known in-progress L2-A migration, stated in the route's own docstring
  (`intelligence.py:2698`): the board still renders `ranked_all`, the canonical
  board state the shortlist lands in "is never written (both migration flags
  default False and are off)", and pointing the board at L2-A rows "is the goal".
  **So the old gate was not a narrow view of the product — it was an artifact
  nothing user-facing serves.** The clamp misprices were always measured on the
  served path (`layer2_board.py:1345`: 1346 `fair_price` values, 24 on ±4900),
  which is the population the instrument now reads. Consistent, and the reason
  the gate had to go rather than be widened.
  - Sports move within minutes: 03:24Z served WNBA only; 03:3xZ served
    mlb 168 + wnba 216 priced occurrences. Do not treat one read's sport mix
    as the slate's shape.

#### smaps-anon-breakdown — CLOSED 2026-08-15 23:5xZ
**HYPOTHESIS CONFIRMED.** pid 39 anon is **91% mmap** (1,007.2 of 1,106.9MB)
against only **95.9MB of brk `[heap]`**. Falsification was "if `[heap]` dominates,
`mallinfo2`'s `arena` is the follow-up rather than `hblkhd`" — it does not.

**AND THE LANE'S PREMISE WAS RETRACTED BY ITS OWN INSTRUMENT.** The "673MB
outside pymalloc" this lane was opened to chase was cgroup `anon` (1,607MB,
CONTAINER) minus pymalloc arenas (934MB, pid 39 ONLY). Different scopes. The
smaps reader's reconciliation check refused its first production read
(`reconciles: false`, 27.0%) and that refusal was the finding. Per-process the
residue is **~173MB**; ~410MB was always just the 8-10 child processes.

**CONSEQUENCE: `mallinfo2` IS NOT THE NEXT STEP.** I recommended it two hours
ago. The question it was for has largely dissolved, and with pymalloc holding
~934MB of arenas the mmap total is very nearly pymalloc itself — a duller answer
than a mystery, and the right one.

**SHIPPED:** `b0ab37a1` (reader) live 22:41:04Z, minimal — live sha + 1 commit,
not converged main, which would have moved production 330 commits for an
instrument.
**NOT SHIPPED:** `c7747a29` (reconcile against the process, not the container).
Three sessions held the deploy claim in 70 min and the live sha moved twice under
a rebase, so it is filed as a request rather than raced for —
`.syndicate/deploy/requests/2026-08-15T2350Z-smaps-reconciliation.md`.
Until it lands the reader reports `reconciles: false` on every read. Cosmetic;
the breakdown itself is correct.
- [(superseded lane detail](lanes_closed.md) — (superseded lane detail — the original body this lane was opened with)
- [quote-join-enrich-cost (detail below, kept for the file/line map)](lanes_closed.md) — quote-join-enrich-cost (detail below, kept for the file/line map) — session: memory-guard
- [memory-guard-reclaimable (detail below, kept for the file/line map)](lanes_closed.md) — memory-guard-reclaimable (detail below, kept for the file/line map) — session: memory-guard
- [render-yaml-web-block-hygiene](lanes_closed.md) — render-yaml-web-block-hygiene — DONE 2026-08-13 — **NO LANE WAS EVER OPENED**
- [(superseded lane detail, kept for the file/line map)](lanes_closed.md) — (superseded lane detail, kept for the file/line map)
- [hooks-enforcement-wiring](lanes_closed.md) — hooks-enforcement-wiring — DONE 2026-08-13 — **NO LANE WAS EVER OPENED**
- [red-intelligence-tests](lanes_closed.md) — red-intelligence-tests — CLOSED-VERIFIED 2026-08-15 — all three reds fixed, 218/0, shipped `1322d0a8`/`d348e040`/`4ae71c4a`, pushed `89c3d94
- [mlb-live-pitcher-projection](lanes_closed.md) — mlb-live-pitcher-projection — CLOSED-VERIFIED 2026-08-16 — (a)/(b)/(c) all measured on 423 rows, 0 violations; live coverage 11.6% -> 50.3%;
- [board-publish-stall](lanes_closed.md) — board-publish-stall — CLOSED-FALSIFIED 2026-08-16 — no stall, no publish failure; the REAL result is that my deployed fix is INERT and resta
- [line-decimal-renderer](lanes_closed.md) — line-decimal-renderer — CLOSED-VERIFIED 2026-08-16 — shipped `f3b9b293`; 5 live rows change, 77 untouched; WEB DEPLOY OWED — opened 2026-08-

#### smaps-anon-breakdown — DEPLOY LANDED 2026-08-16 00:57:32Z (`ada731f5`)
The reconciliation fix is live and the guard is meaningful again. First reading
01:07:38Z:

    reconciles               true      (was false, 27.0% off)
    reconciles_within_pct    0.0
    total_anon_mb          1,672.4     smaps, per-process
    process_rss_anon_mb    1,672.6     RssAnon, per-process
    other_processes_anon_mb    0.4     children, now a LABELLED figure
    cgroup_anon (container) 1,673.0

Two independent kernel accountings of one process agreeing to 0.0%.

**BREAKDOWN NOW TRUSTWORTHY — the lane hypothesis holds on a clean reading:**
`anon_mmap` **1,540.3MB (92%)** against `heap` 128.3MB, `file_backed` 3.6,
`stack` 0.1; mmap split >64MB 741.3 | 8-64MB 639.1 | 1-8MB 159.3 over 426 regions.

**NOTE `other_processes_anon_mb` = 0.4 HERE, not the ~504MB seen at 22:49.** The
children were simply not running at this instant. That is exactly why the old
container-vs-process comparison was unusable: the gap is not a constant to
subtract, it moves with whatever the worker has spawned.

COST: five rebases across five live SHAs (`6f512ffa` -> `129395cc` -> `32186e28`
-> `2c14d9ae` -> `57a437d5`) and four claim holders. On a worker with five
sessions deploying, a two-file change should ride along, not chase.

#### live-game-line-projection — 2026-08-16 ~01:1xZ — THE PREMISE IS TRUE: 25 LIVE GAME-LINE EDGES PUBLISHED
- **Tier 5's goal is met in production.** `index_size 8 / considered 32 /
  projected 32 / edged 25 / prob_interval_swamps_edge 7`, on an artifact
  provably generated after the deploy. Baseline `index 3 / projected 12 /
  sim_count_unusable 12 / edged 0`.
- **Live:** live-odds-worker `c4116ab6` (simsRun stamp), refresh-worker
  `1f36d718` (the join). Web needs neither.
- **THE THREE DROPS, all shipped and measured:** D1 merge condition
  (`0e0b0aa1`), D2 carry-forward (`4bd7dbb3`), D3 join+wiring (`758a89fa`) plus
  the `simsRun` stamp (`49797f4b`) that made the precision gate reachable.
- **NOT ESTABLISHED — the 25 edges are UNVALIDATED.** Clearing 2 sigma at 120
  sims means the edge beats the ESTIMATOR'S noise, not that the model is right.
  No CLV, no settlement, no backtest. **Next work is evaluation, not more
  plumbing** — game lines carry 100% Pinnacle coverage, the strongest position
  on the platform.
- **OPEN:** why `index_size` was 3 earlier and 8 now is unexplained; Drop 2's
  carry-forward has still never been observed firing; the tally is MLB-only.
- **I no longer hold the live-odds-worker claim** — `clamp-fix-to-workers` took
  it ~00:34 and my last two fires went over it. Not force-released; theirs.

- **CHECKPOINT 2026-08-16 01:4xZ — state of the lane for whoever picks it up.**
  - All deploy claims RELEASED. Nothing held by this session.
  - Committed: `86ee112f` (falsification), `0f70969b` (lane), `25e34c63`
    (deploy record + 2 learnings), `1b76c232` (defer + `#439`), `1bd520c2`
    (state.md + the claim-target learning).
  - **NEXT ACTION: run `py -3 scripts/watch_clamp_trigger.py --once` when
    games are IN PLAY.** Both real triggers (23:10Z, 23:15Z) came from live
    in-play markets; the two `no_trigger` reads were a pregame board with
    extremes 0.0687/0.8904. A one-off task fires 2026-08-15 21:31 CDT and the
    recurring `clamp-fix-verification-watch` runs every 2h.
  - **`POST_FIX_OK` closes `#439` item 1.** `PRE_FIX_MISPRICE` now that
    refresh-worker is clean would falsify the intelligence-state attribution —
    that is this lane's stated falsification test, and it is still live.
  - Session log: `.syndicate/log/2026-08-15.md`, final section.

### odds-cadence-off-the-mlb-peak — OPEN — **1a/1b VERIFIED IN PRODUCTION 2026-08-16 05:51:48Z (`dd53d47c`, live-odds-worker): gate runs, soccer exclusion HOLDS at interval_s=28800 baseline. EFFECT still unmeasured; lane goal DEFERRED to 1c (blocked).** — opened 2026-08-16 — session: sim-engine-track
**Scoped only. No code, no deploy. Handing this over rather than starting it at
02:00 local on a fixed crash.**

- **Goal:** stop the soccer/odds refresh branch running concurrently with MLB's
  memory peak. Target: remove ~202.6MB from the worst combined moment, against a
  margin measured at **124MB** (worst combined 3,972.0MB = 97.0% of 4,096MB).
- **THE OWNER'S DOMAIN POINT IS THE PREMISE, and it is confirmed by the data:**
  soccer and the US sports run on opposite schedules, so soccer has no fixture
  reason to be refreshing during MLB's evening peak. Measured 18:11Z-01:5xZ,
  samples with BOTH branches live, against pid 39's peak that hour:

        hr   soccer   mlb   BOTH   pid39 peak
        18      113   383    101       3,230
        19      355   689    317       2,369
        20      241   501    223       3,300
        21      206   215    101       3,328
        22       91   353     82       3,302
        00      206    84     33       3,628

  **Soccer runs in EVERY hour MLB peaks.** The collision is cadence, not fixtures.
- **The concurrency is real** (unlike the `daily_update` chain, which is nested —
  see the correction above). The odds branch hangs off its own child of pid 39:
  `run_refresh_odds_job` -> `refresh_odds_sources` -> `build_soccer_artifacts`
  = 20.4 + 95.5 + 86.7 = **202.6MB** alongside the MLB chain.

**DO NOT START FROM SCRATCH — TWO PIECES ALREADY EXIST:**
1. **`9ec20a06` is written, tested and HELD** — "odds: the pregame relaunch
   cooldown is per-sport, not one clock for all eight"
   (`live_refresh_loop.py` +115, `tests/test_pregame_cooldown_per_sport.py`
   +132). NOT on `origin/main`. It was held because it changes odds cadence and
   would confound `soccer-odds-coverage`'s per-league measurement — that is the
   SAME mechanism this lane needs, so check whether it already does the job
   before writing anything.
2. The `soccer-odds-coverage` lane owns per-league cadence. **Coordinate; do not
   take its files.**

- **Hypothesis:** a per-sport cadence that ties soccer's refresh to its own
  fixture window removes most of the 202.6MB overlap without reducing soccer's
  data quality, because the refreshes during MLB's peak are polling leagues with
  no imminent kickoff.
- **Falsification test:** if soccer's refreshes during 18-22Z are in fact serving
  imminent kickoffs (check `commence_time` on what those runs write), then the
  overlap is REQUIRED and the lever is memory, not scheduling.
- **Verification:** re-run the hour table above; `BOTH` should fall in MLB's peak
  hours, and worst-combined should drop from 3,972MB. Must be a WORST-COMBINED
  measurement across all processes — a per-process figure is what made the margin
  look like 578MB when it was 124MB.
- **Cost note:** OddsAPI spend. Changing cadence changes call volume against a 5M
  cap; `9ec20a06` was held partly for that call.

#### PHASE 1 OPENED 2026-08-15 — scope, files, and what is deliberately NOT in it
- **Goal (single testable outcome):** a sport's pregame sweep interval becomes a
  function of time-to-next-fixture instead of a constant, so leagues with no
  imminent kickoff stop sweeping during MLB's evening peak.
- **Files (exclusive to this lane):** `syndicate/features/shared/live_refresh_loop.py`,
  `tests/test_pregame_cadence_fixture_aware.py` (new). Collision check RUN
  2026-08-15 against all OPEN lanes: both CLEAR.
- **DELIBERATELY OUT OF SCOPE — a collision I am not going to work around.**
  Plan step 1c (per-league soccer scoping) needs `scripts/build_soccer_artifacts.py`
  and `scripts/run_live_odds_refresh_worker.py`, and **both are claimed by OPEN lane
  `soccer-model-coverage`.** Phase 1 ships 1a (commence-time providers) and 1b
  (tiered interval) only. 1c requires coordinating with that lane first.
- **Hypothesis:** most soccer refreshes during 18-22Z serve fixtures days away, so
  a time-to-kickoff gate removes the overlap at no freshness cost.
- **ALREADY FALSIFICATION-TESTED, TWICE, AND IT SURVIVED BOTH:**
  1. This lane's own cmdline test: 43 of 71 invocations (61%) during 18-22Z were
     for kickoffs 2+ days out; 19Z was 100% future-dated.
  2. `#440` Phase 0/H1, independent source (fixtures, not processes):
     **9 European leagues, n=200, 0.0% of kickoffs in the 18:00-01:00 CT band, and
     zero at ANY hour after 14:00 CT.** MLS is the exception at 94.6%, n=111.
- **The rule that falls out, and it is fixture-relative ON PURPOSE:** H1 also
  CORRECTED the believed band table (European soccer is 05:00-14:00 CT, not
  01:00-09:00, and US fixtures start at 11:00, so an 11:00-14:00 contested band
  exists). A clock-based "no soccer in the evening" rule would have been built on
  wrong hours and would break MLS. Gate on time-to-next-kickoff, never on the clock.
- **Verification, and the baseline is NOT the one in this lane's scope block:**
  re-run the hour table from `reports/branch_overlap/baseline.jsonl`, which the
  scheduled task `branch-overlap-baseline-watch` is now accruing. **The 2026-08-16
  figure in this lane (3,972 MB / 97.0% / 124 MB margin) IS ALREADY STALE — the
  first watcher sample read 4096.0 MB = 100.0% of cap in three separate hours.**
  Judge Phase 1 against the accrued distribution, not against that number.
- **Cost gate before shipping:** cadence changes OddsAPI call volume against a 5M
  cap. The tiering should REDUCE calls; measure, do not assume.
- **Do not shelve `9ec20a06`** (per-sport pregame cooldown). It is a freshness fix
  and pushes overlap up; independent clocks PLUS fixture-awareness serves both.
- Blocked by: none. 1c blocked on `soccer-model-coverage`.

#### odds-cadence-off-the-mlb-peak — CHECKED 2026-08-16 02:0xZ: `9ec20a06` does NOT do it
Answering the scope's own question so nobody re-reads that branch.

**It pushes the OPPOSITE way for memory.** Its purpose is FRESHNESS:
`_pregame_relaunch_blocked` read one marker keyed by date, so any sport's launch
started the 1800s cooldown for all eight; MLB rode every 2nd-4th launch and its
quote capture ran every **121.6 min**, which is why the board served prices up to
two hours old and carried candidates that were no longer bettable.

The fix decouples that — each sport cools against its OWN last launch. Checked
the diff explicitly: **no concurrency limit, no memory gate, no serialisation.**
Its direct effect is MORE independent launches, i.e. soccer MORE likely to run
during MLB's peak, not less. The author mitigated exactly one tick of that risk
(a sport with no entry inherits the legacy epoch "so the first tick after this
deploys does not stampede every sport at once") — after that first tick all eight
are free.

**SO THE TWO GOALS ARE IN GENUINE TENSION, and that is the finding:**
- FRESHNESS wants independent clocks -> more overlap.
- MEMORY wants fewer concurrent branches at MLB's peak -> less overlap.

**Do NOT shelve `9ec20a06` for this lane.** Two-hour-stale MLB prices are a
product defect that directly produces unbettable candidates; that outranks 202MB
on a worker that is no longer crashing.

**THE RESOLUTION IS THE OWNER'S DOMAIN POINT:** independent clocks PLUS
fixture-awareness serves both. Soccer keeps its own cadence, but that cadence
follows soccer's kickoffs — which are opposite the US evening. MLB gets its 30-min
freshness; soccer stops polling leagues with no imminent kickoff during MLB's peak.

**NEXT MEASUREMENT IS THE FALSIFICATION TEST ALREADY IN THIS LANE:** read
`commence_time` on what the 18-22Z soccer runs write. Imminent kickoffs -> the
overlap is required and the lever is memory, not scheduling.

#### odds-cadence-off-the-mlb-peak — FALSIFICATION TEST RUN 2026-08-16 02:1xZ: IT DOES NOT FIRE
The test was: "if the 18-22Z soccer refreshes are serving IMMINENT kickoffs, the
overlap is REQUIRED and the lever is memory, not scheduling." They are not.

111 distinct soccer invocations parsed from `ALL_PROCESS_MEMORY` cmdlines
(`--soccer-leagues` + `--soccer-date`), 18:00Z onward. Kickoff DATE being fetched,
by hour:

    18Z   08-15 x4, 08-16 x4, 08-17 x2, 08-21 x6
    19Z   08-19 x2, 08-22 x10          <- 100% FUTURE, 4-7 days out
    20Z   08-15 x2, 08-16 x2, 08-17 x2, 08-20 x2, 08-22 x8
    21Z   08-15 x6, 08-16 x6, 08-17 x3
    22Z   08-15 x2, 08-16 x2, 08-17 x2, 08-21 x6

**43 of 71 invocations during 18-22Z (61%) are for kickoffs 2+ DAYS AWAY.** And
19Z — the hour with the MOST overlap (317 both-branch samples) — was ENTIRELY
future-dated. Nothing it fetched kicked off for four days.

**SO THE OWNER'S DOMAIN POINT IS CONFIRMED AND QUANTIFIED.** Those refreshes can
be deferred out of MLB's peak at no freshness cost, because their fixtures are
days away.

**ONE EXCEPTION THAT MUST NOT BE BROKEN: MLS.** It is the single most-refreshed
league (20 of 111) and its kickoffs genuinely ARE in the US evening. The European
leagues — la_liga 17, championship 16, primeira_liga 14, belgian_pro_league 12,
eredivisie 12, epl 8, ligue_1 8, serie_a 4 (91 of 111) — kick off in the European
day. A blanket "no soccer during the MLB peak" rule would break MLS; the rule has
to be fixture-relative, not league-blind or clock-blind.

**IMPLEMENTATION SHAPE THIS IMPLIES:** gate a league's pregame refresh on
time-to-kickoff rather than on a global clock. Leagues whose next fixture is >N
hours out get a slow cadence; MLS in its own evening stays fast. That serves
`9ec20a06`'s freshness goal AND this lane's memory goal, which is why the two are
only in tension while the cadence is fixture-blind.

#### HANDOFF to `clv-without-settlement` — live game-line edges, and the reason there is nothing to score yet
From `live-game-line-projection`, 2026-08-16 ~02:1xZ. **Read the structural
point before the data — it is the actual deliverable.**

**THE ROWS ARE TRANSIENT AND NOTHING PERSISTS THEM.** `live_gamelines` is
recomputed from scratch on every board build, for whatever games are live at
that instant. Measured tonight, same slate, three builds:

    01:11Z  edged 25   (pre-fix, inflated by segment + boundary defects)
    01:57Z  edged  4   (post-fix)
    02:06Z  edged  1   (slate winding down)

**A CLV number needs (edge at time T) paired with (price at settlement), and the
first half is never written down.** By the time a game settles, the row that
carried its edge has been overwritten several times. **This is the same gap this
lane already solved for recommendations with the opening-snapshot recorder
(`2b14fbeb`, 584 bytes/record) — game-line edges need the equivalent, and it
does not exist.** That recorder is the prerequisite; scoring is downstream of it.

**THE ONE ROW LIVE AT HANDOFF** (artifact `2026-08-16T02:06:59Z`) — offered as a
shape to design against, **not** as a sample to draw a conclusion from, n=1:

    game_pk 824966  TEX @ ATH  state=live  segment=full  market=h2h
    model_home_win_prob 0.6   market_fair_prob 0.4069   edge_pp +19.31
    prob_std_err 0.04405 (Agresti-Coull, n=120)   sims_run 120
    event_id 1145a9db8d138b13599e168a340ad3c7   home Athletics / away Texas Rangers
    sharp books: pinnacle, betfair_ex_eu, matchbook, novig, prophetx   pinnacle=True

**WHAT THESE ROWS DO AND DO NOT WARRANT.** Surviving means: a full-game market,
and an edge exceeding 2 Agresti-Coull standard errors of a 120-sim estimate.
**It means the edge beats the ESTIMATOR'S OWN NOISE. It says nothing about
whether the model is right.** No settlement, no backtest, no CLV.

**TWO CORRECTIONS TO CARRY, both from my own retractions tonight:**
- **`state.md`'s "100% of MLB game lines carry a sharp quote" is confirmed for
  the sharp SET (30/30 in production) but PINNACLE SPECIFICALLY IS 15/30.** A
  "CLV against the Pinnacle close" covers about half the population. Confirmed
  against production, not the mirror.
- **"Closing price" is ill-defined for a LIVE market** — it runs continuously to
  settlement. Decide explicitly whether the close is the last observed price
  before settlement, and note `closing-stamp-is-detection-time` records
  `closing_price` as **always the home price (18/18)**, which would mis-pair
  every away-side row.

**I deliberately did NOT build a parallel CLV path.** `clv_join.py` is yours and
the recorder decision is yours. Producing my own number would have duplicated
the machinery and inherited the side defect.

#### HANDOFF to `memory-watchdog-435` — a 2,092 MB in-process excursion, attribution already done
From `live-game-line-projection`, 2026-08-16 ~02:3xZ. **First refresh-worker OOM
of the day** (user's report: none until this one).

**THE KILL.** `server_failed reason={'evicted': False, 'oomKilled':
{'memoryLimit': '4Gi'}}` at **02:11:34Z** — events API, not logs.

**THE ALLOCATOR IS pid 39, THE MAIN WORKER. Every child is a bystander.**
`ALL_PROCESS_MEMORY`, two samples 34 s apart:

    02:10:49  container 2458.8 MB (60%)   pid 39 rss 1191.1 MB
    02:11:23  container 4094.6 MB (100%)  pid 39 rss 3283.4 MB
    02:11:34  oomKilled

    pid 39 (run_refresh_worker.py)   1191 -> 3283 MB   = +2,092 MB in 34 s
    pid 353 (daily_update.py)        207.7 -> 207.7    FLAT
    pid 394                           95.1 -> 143.7    +48
    pid 383                           79.1 ->  79.4    FLAT
    multiprocessing pool workers     ~54 MB each       FLAT

**THIS KILLS THE OBVIOUS HYPOTHESIS.** The running job was
`daily_update.py --sims 1000 --workers 2`, so "the sim's worker pool multiplies
memory" is the natural guess. **It is wrong** — every pool worker sits at ~54 MB
and the parent is flat to the decimal. It is ONE in-process allocation on the
main thread.

**`post_mlb_sim_tick` IS A BYSTANDER, as `state.md` already says.** Both
`CONTAINER_MEMORY` samples carry that stage and the whole excursion happens
between them. The label names the victim, not the allocator.

**WHY THIS ONE IS WORTH THE WATCHDOG.** `#327`'s open problem is "something
allocates 493-878 MB in-process and nothing knows what". **This is 2,092 MB,
roughly 3x the largest previously recorded** — which is why it crossed 4 GiB
instead of being absorbed. If the ~2 s timer sampler is deployed it should have
caught the interior of this window; if it is not, this is the strongest case yet
for shipping it.

**CONFOUND, STATED.** refresh-worker took **five deploys in the preceding hour**
(01:13, 01:24, 01:31, 01:56 mine, and 02:19 mine AFTER the kill), and `state.md`
records that every deploy resets the memory baseline. **"No OOM all day" partly
describes a worker that had not been restarted repeatedly until tonight — do not
treat it as a controlled baseline.**

**MY OWN CHANGES, assessed rather than assumed:**
- **The CLV ledger (`f8ca54e1`) is EXONERATED for this kill — it deployed
  02:19:10, EIGHT MINUTES AFTER it.** It was not running.
- The segment/boundary fix (`d1e3f908`, live 01:56:44) WAS running. It makes
  `attach_live_gamelines` do strictly LESS work (an early `continue`) and adds
  scalar arithmetic; the join has been live since 23:01 without OOMs. **On the
  stack, but not memory-shaped. Not cleared — just not indicated.**
- **FORWARD RISK THAT IS MINE:** the ledger's `read_last_by_key` parses the whole
  JSONL into a dict **on every board build**. Empty today, grows with the slate,
  and it now runs on this worker. **If a second OOM appears, suspect it first —
  `MLB_LIVE_GAMELINE_LEDGER_ENABLED=0` disables it with no deploy.**


- `win-prob-null-readable` — CLOSED-VERIFIED 2026-08-16 *(full entry in `lanes_closed.md`)*
- `slate-size-headroom` — CLOSED 2026-08-16 *(full entry in `lanes_closed.md`)*
- `worker-child-processes` — CLOSED 2026-08-16 *(full entry in `lanes_closed.md`)*

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

#### live-game-line-projection — ARCHIVE ADDENDUM 2026-08-16 ~03:0xZ (supersedes the "next session" line in the archive above)
Recorded after the archive block, and it **changes the next step**.

The settled MLB CLV read for 2026-08-15 (`ceecf863`) shows
**`in_play_excluded_n: 25` — in-play is a SEPARATE, EXCLUDED bucket**, and
in-play is exactly the population this lane produces. **So the live game-line
edges cannot be scored through the existing CLV path at all**, however many rows
the ledger accumulates.

**The blocker is therefore a DECISION, not more data:** what does "close" mean
for a market that runs continuously to settlement? That is
`clv-without-settlement`'s call, and it gates everything this lane ships.

**Revised order for whoever picks this up:**
1. **Settle the in-play close definition** with `clv-without-settlement`. Until
   then the ledger accrues rows nobody can score.
2. Then read the **8/16 20:30 CDT** scheduled check — dedup working, rows
   accumulating. That proves the RECORDER, which is still worth knowing.
3. Only then ask whether the edges are any good.

**Unchanged:** no claims held; live-odds-worker `c4116ab6`, refresh-worker
`f8ca54e1`, both content-verified. The plumbing is done.

#### CALL-VOLUME CHECK RUN 2026-08-15 — budget clear, and it found a defect in 1a/1b
The gate this lane required before enabling anything. It cleared the cost question
and then failed the thing it was checking, which is the point of running it.

- **BUDGET IS NOT A CONSTRAINT.** `/api/ops/oddsapi/quota`: `projected_30d_credits`
  **3,134,318** against the 5M cap = **62.7%**, 4,353 credits/hr. By sport since
  2026-07-28: mlb 1,627,718 (**93.0%**), soccer 71,912 (**4.1%**), nfl 37,639,
  wnba 13,475. **Soccer cadence is not a cost lever.** (Headers claim ~13.3M
  remaining; `CLAUDE.md` records that as untrue — 5M used here.)
- **THE DEFECT — 1a/1b IS WRONG FOR SOCCER, THE ONE SPORT THIS LANE IS ABOUT.**
  Tiers modelled against the real 2026 fixture lists, 336 hours:

        mlb            12.00 -> 5.45 sweeps/day   -55%
        wnba           12.00 -> 5.83              -51%
        nfl_preseason  12.00 -> 3.56              -70%
        soccer          3.00 -> 5.08              +69%   WRONG DIRECTION

  `_next_fixture_epoch` resolves ONE clock per sport, but soccer's "sport" is ten
  leagues on ten calendars, so the gap is the MINIMUM across all of them and is
  almost never large: **the 24h tier is reached in 0.0% of hours.** The gate would
  have made soccer sweep MORE often — increasing the exact overlap this lane
  exists to remove. Per-league: 24h tier in **49.3%** of league-hours, volume flat
  (3.03/day) but redistributed OFF the peak.
- **I shipped 1a/1b naming soccer as the motivating case. The measurement says
  soccer is the one sport it hurts.** Recorded rather than quietly patched.
- **FIX (`8640f872`):** `_FIXTURE_CADENCE_EXCLUDED_SPORTS = {"soccer"}`, numbers in
  the code, 3 tests pinning it — including a control that fails if the gate is
  disabled outright rather than only for soccer, and a note that the MLS test must
  be REWRITTEN when 1c lands, not deleted. 52 tests green.
- **CONSEQUENCE FOR THIS LANE'S GOAL: 1c is a PREREQUISITE, not an optimisation.**
  Phase 1's headline benefit — soccer off the MLB peak — is DEFERRED until 1c,
  which is blocked on `soccer-model-coverage`. What ships today is a -51% to -70%
  cut in the pregame sweep ceiling for the single-league sports, which is real but
  is NOT what this lane set out to get. State it that way in any status.
- **WHAT THE MODEL IS NOT:** `sweeps/day` is a ceiling on the PREGAME cadence, not
  measured call volume — launches are further gated by the 1800s relaunch cooldown
  and the off-hours gates, and the 60s live tick is not governed by this cadence at
  all. **The credit delta stays UNMEASURED** until the flag is enabled on one
  service and the quota re-read.
- Gates remaining before enabling: the baseline distribution from
  `branch-overlap-baseline-watch` (accruing; one sample is not a distribution).

#### 1a/1b VERIFIED 2026-08-16 05:51:48Z — the gate runs and the exclusion holds
- Three consecutive lines carry the whole decision chain on live-odds-worker:
  `FIXTURE_CADENCE sport=soccer interval=baseline reason=excluded_pending_per_league_scoping`
  -> `PREGAME_CADENCE_DETAIL soccer:marker_age_s=4480/interval_s=28800`
  -> `PREGAME_CADENCE_SKIPPED sports=soccer`.
- **`interval_s=28800` is the load-bearing field**: soccer's 8h BASELINE, not a
  fixture tier. Had the exclusion failed, soccer would have swept MORE often
  (+69%, measured) — the opposite of this lane's goal.
- Predicted the first observable tick at ~05:51:37Z from a 900s idle interval
  against an 1800s cooldown; actual 05:51:48Z. **11 seconds.**
- **THREE WRONG TURNS FIRST, all invisible from `status=live`:** flag on the wrong
  service (refresh-worker never imports `_run_live_refresh_tick`); post-deploy
  silence that was log-ingestion lag, not a boot failure; and
  `_pregame_relaunch_blocked` sitting UPSTREAM of the cadence filter.
- **STILL UNMEASURED: the EFFECT.** One gate decision is not a cadence outcome.
  Needs the `branch-overlap-baseline-watch` distribution. And soccer is excluded
  by design, so **this lane's headline goal stays DEFERRED to 1c**, blocked on
  `soccer-model-coverage`.
- Full measurement in `deploys.md`; unrelated defect found while measuring
  Phase 2's premise is filed as `#441` (NFL week-1 projection unwritten 2.36 days,
  relaunching ~107x/day).
### nfl-pbp-root-resolution — OPEN — **HYPOTHESIS FALSIFIED IN PRODUCTION. The fix shipped (`97491161`, live 15:45:50Z) and `#441` is NOT fixed: the pbp is absent from EVERY root. The change is correct and stays; it was not the cause.** — opened 2026-08-16 — session: sim-engine-track
- Goal: `#441`. The NFL SmartSim2 projection writes again, because the pbp READ
  path resolves to the mounted disk instead of the ephemeral repo checkout.
- Files (exclusive to this lane): `syndicate/features/nfl/sources.py`,
  `scripts/generate_smartsim2_nfl_projections.py`,
  `tests/test_smartsim2_nfl_pbp_root.py` (new). Collision check RUN against all
  OPEN lanes: CLEAR on all three.
- **DIAGNOSIS COMPLETE BEFORE ANY EDIT — measured in production, not inferred:**
  - `DATA_ROOT : /opt/render/project/src/data/nfl_source` (the CHECKOUT)
  - `looked for : .../src/data/nfl_source/tracking/nflverse/pbp/pbp_2026.csv`
  - `.gitignore:96` excludes `data/nfl_source/tracking/`, so the pbp exists ONLY
    on the mounted disk. Zero plays loaded -> `assert_ratings_data_available`
    refuses -> artifact never written -> `age_seconds` climbs forever ->
    ~107 relaunches/day.
- **THE GUARD IS NOT THE BUG. It is working exactly as designed** — it refuses to
  write a degenerate artifact where every team rates `neutral_no_data` and all
  games get the same league-average projection (production served exactly that on
  2026-08-13: `margin 0.96 / total 44.38 / home_win 0.5267` on all 16 preseason
  games across four dates). Do NOT relax it.
- **ROOT CAUSE, and `#389` already found it for the OTHER path:**
  `_first_existing_root` picks a root by probing for `upcoming_recs_*.csv` — a
  DIFFERENT artifact family. The checkout ships those (5 tracked files); the pbp
  subtree is gitignored. So an unrelated artifact's presence decides where the
  pbp is read from. `#389` fixed the WRITE path by adding
  `nfl_artifact_output_root()` and left the READ path on the same selector.
- Hypothesis: adding a pbp-specific resolver that probes candidates for the pbp
  FILE (not for `upcoming_recs_*.csv`) makes the generator find it on the mounted
  disk and write the artifact.
- Falsification test: if the pbp is ALSO absent from the mounted disk, root
  selection is a red herring and the real gap is ingestion. The production
  message says otherwise ("that is the bug, not a missing download") but that is
  the code's assertion, not a directory listing — treat as unconfirmed until the
  artifact actually writes.
- Verification: `SEASON_PROJECTION_LAUNCHING` stops recurring every ~40s, and
  `smartsim2_projections_2026_wk1.csv` appears with a fresh mtime and
  NON-IDENTICAL rows per game (identical rows would mean the guard was bypassed
  rather than satisfied).
#### FALSIFIED 2026-08-16 15:53:28Z — the lane's own falsification test fired
- This lane wrote the test before shipping: *"if the pbp is ALSO absent from the
  mounted disk, root selection is a red herring."* It is, and it was.
- `DegenerateProjectionRun` raised again 8 minutes after go-live, with the same
  `looked for` path as before the fix.
- **THE LOG WAS AMBIGUOUS BY CONSTRUCTION** — the resolver's not-found fallback is
  `default_nfl_source_root()`, i.e. the same checkout path the old code printed.
  "Not deployed" and "ran and found nothing" are indistinguishable in the log.
  Settled by CONTENT: `97491161` carries `nfl_pbp_path` (1) and the generator's
  delegation (1), and refresh-worker is live on it.
- **v3 root cause:** the pbp is gone from every root; ten scripts reference it,
  all reads, zero writes; no nflverse fetcher exists for play-by-play. It was
  present 2026-08-13 (`verify_nfl_autorun_obligations.py:25`, real ratings on
  16/16 games), which matches the 2.79-day staleness.
- **Lane goal NOT met.** The change is kept — it removes a real latent
  misresolution and is inert when the file is absent — but it must not be
  recorded as fixing `#441`.
- Handover: find what REMOVED the file and how it is meant to arrive. That is not
  a code fix and not this lane's scope; `#441` carries the next step.

### live-game-line-projection — OPEN — RE-TAKEN 2026-08-16 03:0xZ (session `live-gameline-eval`) — TIER 5'S PREMISE IS TRUE IN PRODUCTION; THE EDGES ARE UNEVALUATED
### refresh-worker-oom-recurrence — OPEN — **MECHANISM SETTLED, ALLOCATOR STILL UNNAMED. `#435` did NOT regress (scope error: book_quotes READ vs container anon). The failure is a ~2GB TRANSIENT in the PARENT process (pid 39, children <54MB), decided by evictable page cache (inactive_file 26.3/42.2 at kills vs 164-240 surviving), climbing 51s with NO stage marker. THREE fixes shipped and exercised in live `d72d670c` — odds-shard duplicate `51ae7218`, ledger streaming `21f8a165`, 3-ledger-loads-to-1 `aa190d58` — and NONE has been shown to move the transient. deepcopy EXONERATED by measurement (0.54MB peak). Daytime windows are worthless as evidence; the live-slate band 22:00Z-05:00Z is scheduled via `scripts/oom_band_report.py` + two one-time tasks. OPEN pending that result** — opened 2026-08-16 — session: refresh-worker-oom-recurrence
### render-events-reader — CLOSED-VERIFIED 2026-08-16 — **`scripts/render_events.py` + `tests/test_render_events.py` SHIPPED TO THE TREE (no deploy — this is local tooling). Falsification test PASSED: 29/29 known `oomKilled` reproduced for 2026-08-14 CT, and the unpaged control returns 20/29 — i.e. a single-page reader undercounts by 31% while looking like an answer.** — opened 2026-08-16 — session: branch-overlap-baseline-watch
- Goal: `scripts/render_events.py` exists and answers "was this service killed,
  and why" from `/v1/services/<id>/events`, so the 2026-08-15 FORBIDDEN rule
  ("never conclude no-OOM from a LOG search") has a tool behind it. That rule
  names `render_logs.py` as unable to answer the question and leaves nothing in
  its place; every session that has needed a kill census since has hand-rolled
  one. Success = the script reports the window it ACTUALLY covered, pages the
  cursor to exhaustion, and distinguishes `oomKilled` / `evicted` / `unhealthy` /
  `earlyExit` rather than lumping them as "failed".
- Files: `scripts/render_events.py` (NEW). Checked against every OPEN lane's
  `- Files:` at open time: the only claims held anywhere are
  (`clamp-fix-to-workers`) and the four `live_gameline` paths
  (`live-game-line-projection`). No lane claims anything under `scripts/`.
  `refresh-worker-oom-recurrence` is the adjacent lane — it OWNS diagnosing
  refresh-worker memory and this lane must not touch that. Read-only tooling
  only; no service code, no config, no deploy.
- Hypothesis: n/a (tooling, not diagnostic).
- Falsification test: the tool is worthless if it can silently under-cover, which
  is exactly how `render_logs.py`'s predecessor lied (`#434`: 99 samples spanning
  1.2s of a 51s window). So: run it against a window whose contents are already
  known independently — the 29 `oomKilled` on refresh-worker 2026-08-14 CT — and
  require it to return all 29. If a single-page run and a paged run disagree on
  the count, the pager is wrong and the tool must not ship.
- Verification: (a) the 2026-08-14 census reproduces 29/29 `oomKilled`;
  (b) `--json` output round-trips through `json.loads`; (c) `py -3 -m pytest
  tests/test_render_events.py` passes. Recorded here, not in `deploys.md` —
  nothing deploys.
- **Outcome, all three verification criteria run:**
  (a) `--failures-only --since 2026-08-14T05:00:00Z --end 2026-08-15T05:00:00Z`
      returns **29 `oomKilled`**, matching the independently-derived census.
      With `max_pages=1` the same window returns **20** — the pager is the
      difference between a measurement and a plausible undercount.
  (b) `--json` round-trips through `json.loads` (checked on live-odds-worker:
      5 `earlyExit`, 0 OOM since 2026-08-15).
  (c) `py -3 -m pytest tests/test_render_events.py -q` → **15 passed**.
- **Positive control works:** the branch-overlap window 10:09:51Z..15:09:30Z
  today returns zero events AND names the newest event overall
  (`2026-08-16T06:01:34Z deploy_ended`), so "quiet" and "reader broken" print
  differently and exit differently (0 vs 2). This is the whole reason the tool
  exists — the 2026-08-15 FORBIDDEN rule said a negative result about process
  death must come from the events API, and named `render_logs.py` as unable to
  provide one, leaving no tool in its place.
- **Reading it produced, recorded because it is load-bearing for
  `refresh-worker-oom-recurrence` (that lane's, not this one's, to interpret):**
  refresh-worker `server_failed` since 2026-08-09 is **42 events, all 42
  `oomKilled`, none evicted** — 08-08:5, 08-13:4, **08-14:29**, 08-15:4,
  08-16:0-so-far (CT). Kills cluster 15:00–00:00 CT. Separately,
  live-odds-worker's 19 failures over the same week are **zero OOM, all
  `earlyExit`**, still recurring ~1–3/day through 08-16 05:54 CT — a different
  failure mode that a "19 failures" summary would have buried. Not diagnosed
  here; filed as an observation only.
- Files touched: `scripts/render_events.py` (new), `tests/test_render_events.py`
  (new, not in the opening claim — added when the verification step needed it).
  No service code, no config, no deploy.

### ui-probe-settle-plateau — CLOSED 2026-08-16 — the settle now needs 2400ms of stillness, and a verdict resting on absence says so — opened 2026-08-16 — session: ui-probe-rerun-compare
- Goal: `_settle()` can no longer return `settled: true` on a render that never
  started. A verdict that rests on absence of change is labelled as such in the
  JSON and in the printed row, so no reader can mistake it for a proven settle.
- Files: `scripts/ui_layout_probe.py`, `tests/test_ui_layout_probe.py`
- Hypothesis: the 800ms artifact in `reports/ui_layout/rerun_2026-08-16.json`
  (mlb desktop, `contentUnits min==max==33`, `renderSettled: true`) is the two-
  equal-poll rule firing inside a pre-enrichment plateau, not a finished render.
- Falsification test: if the growth curve on mlb desktop shows the fingerprint
  genuinely constant from `load` through enrichment, the plateau theory is wrong
  and the uniform 33 is a real slate.
- **CONFIRMED, not falsified.** Replaying the old rule over a plateau-then-growth
  tape returns `settledMs: 800, settled: true, finalFingerprint: 100` while the
  render goes on to 400 — it stops inside the plateau and reports the
  pre-enrichment DOM as final. On the live re-run with the new rule, mlb desktop
  settled at **6800ms with `sawChange: true`** and desktop/mobile agree at
  **41–53 pairs/card**; under the old rule the same two widths read 33–33 and
  33–49. The contradiction is gone because the reading is no longer premature.
- Verification: `tests/test_ui_layout_probe.py` 35 passed (27 pre-existing + 8
  new); the plateau test asserts `settledMs > 800`, which the old rule fails by
  construction. Live production run 2026-08-16 ~11:0x CDT, all 8 rows OK, no
  false alarm, footer names exactly the six server-side rows.
- What is NOT claimed: the quiet window is a longer window, not a proof. A
  render that stays still for 2400ms and only then starts would still fool it.
  What changed is that such a reading is now *labelled* (`sawChange: false`) and
  fails as soon as a second reading contradicts it.
- Blocked by: none
- Governed by `learnings.md` 2026-08-16 "a wait loop must gate on an AFFIRMATIVE
  success token, never on the absence of a failure string" — `_settle` was that
  rule recurring in a render poll. Absence of DOM change cannot distinguish
  "render finished" from "render has not started".

### ui-probe-desktop-height-model — CLOSED 2026-08-16 — desktop is UNFITTABLE, not mis-tuned; measured the floor instead of tuning the threshold — opened 2026-08-16 — session: ui-probe-rerun-compare
- Goal: desktop reports a height figure that is a real layout signal — either a
  model that fits because it matches how the desktop grid actually sets height,
  or a stated finding that no per-card model can fit and why.
- Files: `scripts/ui_layout_probe.py`, `tests/test_ui_layout_probe.py`
- Hypothesis (written BEFORE testing): (a) grid row-stretching, or (b) pairs
  wrapping into columns so height goes as `ceil(u/cols)`.
- **BOTH HYPOTHESES FALSIFIED.** (a) dead: every card sits at `left=4`, one per
  row — there is no row to equalise against. (b) dead as stated: the pair grid is
  10 visible columns at 1440 and 2 at 390, not 2, and `visRows` fits WORSE than
  `u` (ratio 1.69 vs 1.16).
- **What is true instead:** the grid is a wrapping flow and text WIDTH decides
  where it wraps, so height is not a function of pair count at all. Cards with
  identical `u` differ by **116px** (u=45, n=7) and **97px** (u=49, n=5) on
  desktop; by 81px and 40px on mobile. Agreeing on BOTH `uVis` and `visRows`
  still leaves **74px**. That is a floor no model in these variables can beat.
- **Why no threshold rescues it:** `reliable` needs `residual <= 0.25*explained`,
  so a 116px floor requires 464px of explained range; desktop's content spans
  197px. Tuning the bar would manufacture a fit.
- **Bonus correction:** mobile's residual (81px) EQUALS its floor (81px) — the
  passing model sits on the noise floor and reports text wrap, not layout
  deviation. It passes only because its slope is ~62px/pair vs desktop's ~16,
  buying 743px of range to hide identical noise behind. This revises the
  "residual band ~80–105px" recorded earlier in `log/2026-08-16.md`.
- Verification: 42 tests pass (35 prior + 7 new); the new ones drive the REAL
  shipped `fitGroup` JS in a headless browser over captured production points and
  independently reproduce `floorPx == 116` and mobile `residual == floor == 81`.
- **Verification LIMIT, not claimed as done:** not observed on a live run. The
  11:5x CDT slate collapsed to a uniform 33 pairs at both widths with games Live,
  so nothing fits anywhere (`statesUnfitted: [Live, Preview]`). Verified by
  replay through the shipped code path only.
- Follow-up left open by decision, not oversight: making desktop actually fit
  needs a variable capturing rendered text extent (summed visible section
  heights, or per-section wrapped row counts). Both edge toward circular, so it
  was flagged for a call rather than chosen unilaterally.
- Blocked by: none

### ui-probe-tie-floor-tracking — CLOSED 2026-08-16 — floor collected on every row; 5 of 6 stable, mlb mobile fires the rule at 2.06x — opened 2026-08-16 — session: ui-probe-rerun-compare
- Goal: `identicalContentSpread` emitted on EVERY run at both widths, printed,
  compared across runs, and unable to fail a run while its stability is unknown.
- Files: `scripts/ui_layout_probe.py`, `tests/test_ui_layout_probe.py`
- Decision rule, written BEFORE the readings: moves more than ~2x across runs
  with no card-surface deploy → slate-driven, cannot be baselined → option C.
- **RESULT — 3 consecutive production runs:** nfl desktop 14/14/14, nfl mobile
  50/50/50, ncaaf desktop 45/45/45, ncaaf mobile 53/53/53, mlb desktop
  125/125/125 (116 on the earlier 11:0x geometry, so 1.08x across a slate
  change). **mlb mobile 109/109/53 = 2.06x — the rule FIRES for that row only.**
  It fails informatively: `n` at the worst tie group moved 7 → 8, so tie-group
  membership churns as data enriches and which group is "worst" moves with it.
- **The row the desktop question was actually about (mlb desktop) is stable** at
  125px across three readings while its own `contentUnits` moved 33-57 → 41-57.
  That looks like a property of the CSS, not of the slate.
- Verification: 51 tests pass (42 prior + 9 new), including one proving the floor
  is emitted when `heightModel is None` and `statesUnfitted == ["Preview"]` —
  run through the real shipped JS, not a stub. Three production runs recorded.
- Kept as WATCH, NOT promoted to STABLE_METRICS: one row fails the bar, and the
  metric is one day old.
- **Deliberately not done:** a statistic that would probably pull mlb mobile under
  the bar exists (largest tie group, or a median across groups). Choosing it
  *after* seeing which looks stable is manufacturing the result — the same error
  as tuning the fit threshold, which is what started this whole thread. Left for
  a decision.
- Bug found and fixed en route, predating this lane: `compare()` guarded
  `httpStatus >= 400` but not an `error` row, so `soccer mobile`'s 30s
  `page.goto` timeout was reported as `CODE-DRIVEN DRIFT` on four metrics at
  once. Errored rows are now SKIPPED and named; they still fail the run.
- Blocked by: none

### ui-probe-tie-statistic — CLOSED 2026-08-16 — implemented as decided; the statistic did NOT help and the instability is the SLATE — opened 2026-08-16 — session: ui-probe-rerun-compare
- Goal: track the spread within the LARGEST tie group (user decision), applied at
  every row; the fit-impossibility floor keeps using the MAX across groups.
- Files: `scripts/ui_layout_probe.py`, `tests/test_ui_layout_probe.py`
- Hypothesis (written BEFORE the runs): switching statistic will NOT rescue mlb
  mobile.
- **CONFIRMED — and it is worse, not merely no better.** 3 production runs:
  mlb mobile tracked 67/132/164 = **2.45x** (fires) against worst-group
  99/132/164 = 1.66x; mlb desktop tracked 64/80/64 = 1.25x against worst-group
  83/80/83 = 1.04x. **On both MLB rows the new statistic is LESS stable than the
  one it replaced.** My stated expectation ("would probably pull mlb mobile under
  the bar") was wrong. Mechanism differed from the guess too: the largest group's
  SIZE churns, n = 7/14/7 between runs.
- **The real finding: the axis was wrong.** nfl and ncaaf read 1.00x across three
  runs, both widths, under BOTH statistics — their slates are static (units 3-3,
  16-16). MLB carries a live game and enriches continuously (units 41-57 / 33-57
  / 41-57, Live 1 + Preview 14 every run). The identical-content spread is
  exactly reproducible on a static slate and not reproducible on a churning one;
  no choice of statistic survives content moving underneath it.
- Verification: 57 tests pass (51 prior + 6 new) incl. largest-group tracked
  while `floorPx` takes the worst, and equal-n groups breaking toward the larger
  spread so the tie-break cannot hide a difference. 3 production runs recorded.
- Both statistics are emitted and printed when they differ, so nothing is lost
  whichever is diffed; only `_cmp_value` selects. Reverting is one line.
- **Recommendation NOT taken unilaterally:** revert the tracked statistic to
  `worstGroupPx` (more stable on both MLB rows, and identical to the quantity the
  impossibility floor already uses), then baseline nfl/ncaaf and treat
  MLB-during-a-live-slate as not baselineable in any statistic.
- Provenance caveat: this statistic was chosen AFTER seeing which looked stable,
  so its behaviour is not independent evidence. It did not come true.
- Blocked by: none

### ui-probe-tracked-statistic-revert — CLOSED 2026-08-16 — reverted to worstGroupPx; exposed and fixed two false alarms that were failing a healthy board — opened+closed 2026-08-16 — session: ui-probe-rerun-compare
- Goal: tracked statistic back to the worst tie group, printed number == diffed
  number == the quantity the impossibility floor uses.
- Files: `scripts/ui_layout_probe.py`, `tests/test_ui_layout_probe.py`
- Cross-era safety: `_cmp_value` reads `worstGroupPx` BEFORE `spreadPx`, because
  reports from the largest-group window carry `spreadPx` meaning the other
  quantity. Verified live: post-revert run vs a largest-group-era report reads
  `identicalContentSpread unchanged`.
- **False alarm 1 fixed:** mlb mobile printed "AT ITS NOISE FLOOR (164px) ... not
  layout deviation" and failed the run on that same number (164px > 150px
  budget). A residual at its floor is unmeetable by any model; now reported, not
  failed.
- **False alarm 2 fixed:** mlb desktop then failed with "LAYOUT SPREAD OVER
  BUDGET (313px) with content not driving height" while identical-content cards
  differed by 70px. The branch inferred "content-independent" from a flat linear
  slope; on desktop that is false, because the grid WRAPS and a flat slope means
  the line cannot see content, not that content is absent. The budget now applies
  to the content-controlled figure where tied cards exist, falls back to raw
  spread where none do, and says which it used.
- Verification: 65 tests pass (58 + 7 new); production run after both fixes exits
  0 / OK where the same board failed two rows before.
- Blocked by: none

### layer1-board-coverage — OPEN — **AUDIT DELIVERED AND MEASURED; ONE FIX SHIPPED TO `main`, UNDEPLOYED. All four goals answered except the cross-sport LIVE A/B, which needs two sports live at once and is DEFERRED, not concluded.** — opened 2026-08-16 — checkpointed 2026-08-16 16:4xZ — session: layer1-board-coverage
- Goal: for every in-season sport, a per-sport/per-market-family RATE of
  `projected / total` (alt and period families broken out), every unprojected
  prop classified as EITHER stale-fingerprint OR sim-does-not-emit-this-stat,
  and the `Edge` column's missing term named AT ITS PRODUCER.
- Files (claimed): `syndicate/features/shared/layer1_board.py`,
  `syndicate/templates/shared/layer1_board.html`,
  `syndicate/blueprints/layer1_page.py`,
  `syndicate/blueprints/intelligence.py` (the `/api/board/layer1` handler only).
  Edited in the end: `syndicate/features/shared/prop_projections.py` +
  `tests/test_prop_projections_edge_attribution.py` — checked against every OPEN
  lane's `- Files:` at edit time and claimed by none. Read-only throughout on
  `layer2_board.py`, `intelligence.html`, `bet_slip.js`, `board_cards.css`,
  `soccer_projections.py`, `pipeline/intelligence_state.py`, sim internals.
- **THIS ENTRY WAS WRITTEN TWICE.** The first append was silently overwritten in
  the worktree by a parallel session's read-modify-write of `lanes.md`, and my
  own commit then staged THEIR 44 lines under my message without either of us
  noticing. See the learnings entry of the same date. Re-appended, not rewritten.
- **RESULT** (full audit `.syndicate/audit_2026-08-16_layer1_board.md`;
  measurement + falsification test in `deploys.md`, 2026-08-16 16:19–16:40Z):
  - **Both briefed premises were wrong, and re-checking them first was the whole
    value of the first ten minutes.** Layer 1 is NOT dark (**5 of 5** consecutive
    builds non-zero). Alt lines are NOT unprojected on MLB (`totals_alt` 86/86,
    `spreads_alt` 76/77) — they are unprojected on **WNBA** (419/419 dark). The
    `Edge` column is not blank everywhere: MLB serves **1,462** edges, and most
    rows lacking one already state why on the row.
  - The prior baseline in `docs/ai_context/betting_contract_lifecycle.md` §3a
    (MLB 19.7% projected / **0** edges / game state 1,220 of 3,604) is **EXPIRED**
    — today 68.3% / 1,462 / 2,843 of 2,843. Quoting it would book another lane's
    fix as this lane's regression.
  - **G1** rates measured per sport × family. mlb 1,941/2,843 (68.3%), soccer
    1,704/6,453 (26.4%), wnba 305/872 (35.0%). The MLB gap is **LINE-shaped, not
    market-shaped**: `batter_home_runs` 0.5 → 82.8%, 1.5 → **0.4%**, 2.5 → **0%**.
  - **G2** every unprojected prop classified. mlb 504 no-such-rung / 337
    player-dark (63 players) / 42 residual; soccer 1,293 / 3,128 (836) / 268;
    wnba 39 / 41 / 0. Mapping named: the sim publishes a `<stat>_<N>plus` ladder
    and `hr_2plus`, `hr_3plus`, `hits_runs_rbis_1plus` are the missing rungs.
  - **G3** MLB live lens MEASURED working for props (27 of 201 `live_projected`
    moved, 3 `actual_so_far` advanced over 4 min, right direction) and NOT
    working for game lines (0 live projections on every `game|*` family).
  - **G4** missing term named at the producer: `prop_projections.py` set
    `edge_vs_market_pct = None` and no reason — key **ABSENT** on 284/284 —
    while its soccer sibling has always attributed the same refusal. Fixed in
    `e543e8dd`; replay over real served payloads gives **287/287 attributed, 0
    silent**. The refusal itself is correct (`#238`) and unchanged.
- **NOT DONE, owned elsewhere, routed by `send_message`:** missing sim rungs, the
  63 dark MLB players, WNBA needs a distribution → sim-engine session. The 1,416
  rows carrying BOTH EV terms → Layer 2 session and a **user decision**,
  deliberately not taken here because `modelled_fair` is a book-margin ESTIMATE,
  not a de-vig. The WNBA `wnba_game_cards` +31.7pp finding could NOT be delivered
  (that session is unattended) — it lives in audit §4b and `e543e8dd`'s message.
- Falsification test for the undeployed fix: re-sweep and count rows with a
  projection, no edge of either contract, and no reason. **Expected 0.** Do NOT
  verify by "the reason string appears" — it already appears on 287 rows in
  replay; the residual is the discriminator.
- Verification: met for G1/G2/G4 and for G3-props. **Unmet:** cross-sport live
  A/B (no second live sport in the window). Lane stays OPEN for that.
- Blocked by: none.

### ui-probe-baseline-nfl-ncaaf — CLOSED 2026-08-16 — armed for nfl/ncaaf only; mlb stays watch-only — opened 2026-08-16 — session: ui-probe-rerun-compare
- Goal: `identicalContentSpread` fails on drift for nfl/ncaaf, stays watch-only
  for mlb/soccer, with a new baseline carrying the field.
- Files: `scripts/ui_layout_probe.py`, `tests/test_ui_layout_probe.py`,
  `reports/ui_layout/baseline_2026-08-16.json` (NEW)
- Falsification test: if nfl/ncaaf tie spreads differed between two runs now with
  no deploy, they are not baselineable. **They did not** — 14/50/45/53 held
  across every run today, and the armed comparison reports all four as
  `unchanged (baselined)`.
- Four outcomes kept distinct: drift FAILS; a baseline predating the field is
  NOT COMPARED and does not fail; a VANISHED current value FAILS (absence is
  never a pass); a state change is NOT COMPARABLE rather than drift — which is
  what stops kickoff reading as a layout regression.
- Verification: 72 tests pass (65 + 7 new); live run splits exactly as intended,
  nfl/ncaaf baselined-unchanged while mlb moved 68 -> 69 on the watch line
  without failing.
- **First baseline run was DISCARDED, not shipped**: it failed on `ncaaf desktop
  tab click identity`. Second run clean; the baseline carries `ok: true`. The
  tab-click intermittent is real and unexplained — recorded, not chased.
- **Open and unrelated:** mlb mobile Live state now fails legitimately — residual
  151px against a 40px floor, `atNoiseFloor` False, worst card +79px at 45 pairs,
  1px over budget. The exemption correctly declines. Needs its own look.
- Blocked by: none
