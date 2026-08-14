# Syndicate — Work Lanes

> Lanes are exclusive by file path. Two lanes may not claim the same file.
> Max concurrent OPEN lanes: 3 (see `state.md`).
> Managed by `/lane`. Do not hand-edit while a session is running.

## OPEN

### recommendation-lane-correctness — OPEN — opened 2026-08-14 — session: model-audit
- Goal: no published shortlist row derives its edge from a fabricated
  probability or from a vigged price. Testable outcome, all on the served
  `/api/board/layer2-shortlist`: (a) zero rows whose fair probability came from
  the `0.5` terminal or from `confidence`, (b) every recommendation-lane edge
  labelled `edge_priced_against: "no_vig_fair"`, (c) zero published rows
  carrying a negative `model_edge_pct` (or the field hidden on them).
- Source: Lane A of `.syndicate/plan_2026-08-14_models.md`, derived from
  `.syndicate/audit_2026-08-14_models.md` §4 and ranked fixes 3 and 4.
- **Both defects CONFIRMED in the local tree this session, by reading the file
  rather than trusting the audit prose** (`0a18d901` + local edits):
  - `recommendation_engine.py:685` — `_fair_probability` ends `return 0.5`, and
    line 678 consumes `confidence` as if it were P(outcome).
  - `recommendation_engine.py:294` — `_repriced_probabilities` sets
    `implied_probability = _parse_american_odds(current_odds)`, the raw vigged
    price, and `filter_candidates:1204-1205` passes it straight into
    `calculate_edge`, overriding whatever the candidate carried.
  - Not in the audit, found the same pass: `_repriced_probabilities:311` and
    `_tracking_snapshot:354` ALSO fall back to `confidence` as a model
    probability. A1 must fix three sites, not one.
- Hypothesis (recorded before testing, per protocol — this is A0): the fabricated
  edge is largest exactly where there is no model, because a 0.5 default against
  a plus-money side manufactures a large edge and against a favourite
  manufactures almost none. If so the model-free published rows should skew
  plus-money relative to the 57 rows carrying `model_edge_pct`.
- Falsification test: if the model-free rows' price distribution is the same as
  or shorter than the model-backed rows', the 0.5 default is not selecting for
  longshots, the shortlist is optimistic but not inverted, and A1-A2 stay
  correct-but-not-urgent. Record the result either way.
- **A0 RESULT — the observable is CONFIRMED and the mechanism is NOT the one I
  hypothesised. Both halves matter.** `[measured 2026-08-14 18:26Z, served
  `/api/board/layer2-shortlist?sport=all&limit=500`, artifact written
  18:26:23Z, 250 rows]`

      price (American)      n    plus-money   median    p75      p90      max
      with model_edge_pct   76   48 (63.2%)    +113    +182     +240     +326
      without              174  143 (82.2%)    +875   +2200    +4000  +10000

  Per sport: soccer 100 rows, **100% plus-money, median +2200**; wnba 12 rows,
  100% plus-money, median +455; mlb-without +112.5; nfl-without −105.
  So the model-free half of the board really does sit at far longer prices —
  the shape the hypothesis predicted.
- **But the 0.5 terminal did NOT produce it, and crediting it would have been
  the wrong cause.** Every published row carries `quote.fair_method`, and it is
  `consensus` (150) or `book_margin_model` (100) — never the recommendation
  lane. `_fair_probability` does not price this surface at all. Its 0.5
  terminal is real (confirmed by reading the file) and reaches the
  intelligence/portfolio lane, NOT the shortlist. A1-A2 remain correct; they
  are not the fix for what A0 found.
- **What A0 actually found — a degeneracy, proven arithmetically, 100/100 rows.**
  All 100 soccer rows are priced by `book_margin_model`, every one with
  `books_quoting: 1`. That model is `fair = implied x (1 - hold)`
  (`book_margin_model.py:194`), so on a one-sided row
  **`ev_pct` is identically `-assumed_hold_pct`** — a restatement of the book's
  own margin, carrying no information about the bet.
  - Reproduced exactly: predicting `ev_pct` from
    `round(implied x (1-h), 4) / implied - 1` matches the served value on
    **100 of 100 rows, 0 mismatches, max abs error 0.0100pt** — which is the
    rounding step itself.
  - **3 distinct holds underlie 19 distinct `ev_pct` values.** The apparent
    spread is 4-dp quantisation of `fair` at longshot probabilities
    (`fair` 0.0092 on a +10000 price), not signal. Same shape as `#429`'s
    constant, one layer up.
  - The value floor **cannot ever reject these rows**: soccer's floor is
    `-8.1425 = -1.25 x 6.514`, and 6.514 is the same modelled hold that defines
    their EV. `markets_measured: 0`, `method: modelled_hold`.
  - **All 100 carry a negative `score`.** 40% of the published "opportunity"
    board is one-book longshot props (`player_shots` 43, `player_shots_on_target`
    29, `player_to_receive_red_card` 18, `player_assists` 10) ranked on a
    constant, with `rows_with_projection: 12 of 8512` and
    `rows_with_model_edge: 0` for the sport.
  - Board-wide: `ev_pct` median is **+1.13 on model-backed rows and −6.54 on
    model-free rows**; 174 of 250 published rows have negative EV.
- Severity verdict: the lane is urgent, but the urgent item is this degeneracy
  (A3's territory), not A1/A2. A1/A2 keep their own justification — known sign,
  different surface — and are done first only because they are small and
  independent.
- Verification: re-fetch the served shortlist after deploy and check the three
  outcomes above; unit tests pinning each fix, mutation-checked (restoring the
  old line must turn exactly that test red).
- **CHECKPOINT 2026-08-14 — A0 DONE, A1 DONE, A2 DONE, A3/A4 NOT STARTED.
  NOTHING DEPLOYED, and the exclusion's blast radius is UNMEASURED.**
  - A1/A2 landed in `recommendation_engine.py` (+186/-28, **uncommitted**):
    `_model_probability_only` (model-only P(outcome), else None),
    `_market_fair_probability` (nested quote ONLY), `calculate_edge` and
    `_repriced_probabilities` priced against no-vig fair and labelled
    `edge_priced_against`, the same substitution removed from
    `_tracking_snapshot`'s opening-EV path, and `filter_candidates` now
    rejecting `no_model_probability` by name.
  - `tests/test_recommendation_probability_sources.py` (**new, uncommitted**),
    15 cases, **mutation-pinned**: restoring `confidence` -> 2 red, restoring
    `score/100 + 0.5` -> 5 red, restoring vigged pricing -> 3 red. 66 green
    across the lane's set.
  - **Do NOT deploy before reading the new `FILTER_CANDIDATES` print line.**
    How many production candidates carry a real `model_probability` is unknown,
    so how many rows `no_model_probability` removes is unknown. `logger.info`
    does not reach Render's collector, which is why the line was added.
  - **Expect NO shortlist change from A1/A2.** The shortlist is priced by
    `layer2_board` (`quote.fair_method` = `consensus` / `book_margin_model`),
    not by this module. The lane's stated exit criteria (a)-(c) are written
    against the shortlist and therefore CANNOT be met by A1/A2 — they belong to
    A3/A4. Criteria need restating before this lane closes.
  - Pre-existing failure, proven not mine by re-running it against the pristine
    file from HEAD: `test_intelligence_state.py::...falls_back_on_empty_pool`
    asserts `force_refresh=True` on a call `#387` removed. That file belongs to
    `layer2-board-freshness` — NOT edited. Full run 238 passed / 1 failed.
  - Next action: A3, informed by A0 — the 100 one-book longshot rows ranked on
    `-hold`, plus the 33 rows published with a negative `model_edge_pct`.
- **A3 DONE 2026-08-14, two defects, both measured first. STILL NOT DEPLOYED.**
  - **The score inversion.** `blended_score` returned `value * reliability`,
    which discounts positive value and **promotes negative value**. Measured on
    the served shortlist 18:59:34Z: 156 of 256 rows carried negative value and
    `corr(reliability, score) = -0.8312` across them, against a **+0.8560
    control** on the 98 positive rows. Fixed as `min(value, value*reliability)`
    in `opportunity_signals.py` (+ a `reliability_applied` flag).
    **Simulated before claiming impact: 100 scores unchanged, 156 changed,
    top-50 churn ZERO** — negatives never outranked positives. The real effect
    is on which rows a capped board SELECTS out of the pool, and that is
    **not observable from the shortlist API**.
  - **The uninformative-EV rule.** `_row_ev_is_hold_restatement` +
    `rows_uninformative_ev` in `layer2_board.py`, applied before the per-sport
    bucket so `kind_floor`/`per_sport` cannot re-seat what it rejects.
  - Tests: `tests/test_layer2_uninformative_ev.py` (7, new file) and 5 added to
    `tests/test_opportunity_signals.py`. **Mutation-pinned** both ways.
  - **13 failures in `test_layer2_board.py` / `test_layer2_projection_carry.py`
    are PRE-EXISTING** — proven against pristine files from HEAD, same 13. The
    fixtures build a two-sided row with `cells: {}`, `_fair_by_side` returns
    `({}, None)`, and the fixture yields ZERO candidates. They went stale when
    `#384` made `cells` load-bearing and **currently cannot detect anything**.
    Flagged, not fixed — its own piece of work.
  - **DEPLOY BLOCKER, and it belongs to another lane.** The exclusion drops
    **100 of 256 served rows, all soccer**. Soccer carries
    `rows_with_projection: 12 of 8,512` (0.1%), so it would fall to roughly
    0–12 published rows until projections land — which is exactly what the OPEN
    `soccer-projection-gap` lane owns. Do not ship without that owner agreeing,
    or ship it behind the projection fix rather than before it.
  - **Counter not on the wire yet.** `rows_uninformative_ev` must be added to
    `/api/board/layer2-shortlist`'s explicit key list in
    `syndicate/blueprints/intelligence.py`, held by
    `board-ui-freshness-slip-books`. `#397` says a counter absent from that
    endpoint is invisible no matter how well it works. Needs that lane.
  - Marker note: `.current-lane` was taken by `layer2-board-freshness` at
    14:03:53 mid-edit; borrowed ~15s for one edit and restored immediately.
- **SEQUENCING RESOLVED 2026-08-14 — I WAS WRONG, AND THE DEPENDENCY IS
  ILLUSORY.** I recorded above that A3 must ship behind `soccer-projection-gap`.
  It must not; sequencing it that way blocks A3 indefinitely.
  - For all 100 rows A3 removes, **two independent DELIBERATE design rules each
    guarantee `model_edge_pct` can never be non-null**: (1) `player_shots` and
    `player_shots_on_target` map to a **mean**, and `soccer_projections` refuses
    to derive a probability from a mean on purpose; (2) the rows are one-sided,
    so `_no_vig_over_probability` returns None — the same condition that made
    `book_margin_model` price them. `player_to_receive_red_card` and
    `player_assists` are not in the market map at all. Raising projection
    COVERAGE cannot change any of this.
  - **Measured, with a control** `[19:1xZ, /api/board/book-grid]`:
    soccer `player_shots` **44 rows, 100% one-sided, mean books_quoting 1.00**;
    `player_shots_on_target` **29 rows, 100% one-sided**. MLB props on the same
    call: **1,470 two-sided vs 330 one-sided**. The pipeline can build two-sided
    prop rows; this is soccer's feed, not a broken join.
  - **The rule SELF-HEALS, which is why it is safe alone.** It keys on
    `fair_method == "book_margin_model"`. If soccer ever gets two-sided quotes
    the fair becomes `consensus`, the rule stops firing and the rows return with
    a real EV — no code change, no coordination.
  - **So A3 is unblocked and needs only a PRODUCT decision:** is soccer serving
    ~0 shortlist rows correct, given the alternative is 100 rows ranked on a
    constant that can never acquire a model? Pending the user.
  - Remaining wiring: `rows_uninformative_ev` onto
    `/api/board/layer2-shortlist`. `board-ui-freshness-slip-books` **CLOSED**
    2026-08-14, so `syndicate/blueprints/intelligence.py` is now unclaimed and
    this lane can take it.
- Files (exclusive to this lane):
  - `syndicate/features/shared/recommendation_engine.py`
  - `syndicate/features/shared/layer2_board.py` — A3/A4 only.
  - `tests/test_recommendation_engine.py`, `tests/test_layer2_board.py`,
    `tests/test_recommendation_probability_sources.py` (new this session),
    `tests/test_layer2_uninformative_ev.py` (new this session).
  - `syndicate/features/shared/opportunity_signals.py` — A3's `blended_score`
    monotonicity fix. Added to the claim when A3 started; no OPEN lane claims it
    (checked 2026-08-14 by scanning every lane's claim block).
  - `syndicate/blueprints/intelligence.py` — **CLAIMED 2026-08-14 19:2xZ**, the
    `rows_uninformative_ev` key on `/api/board/layer2-shortlist` ONLY. Freed by
    `board-ui-freshness-slip-books` closing; verified by scanning every claim
    block — the only other mentions are in CLOSED lanes.
  - Collision check 2026-08-14: parsed every OPEN lane's claim block. Claimed
    elsewhere are `scripts/refresh_odds_sources.py` (soccer-odds-coverage),
    `pipeline/intelligence_state.py` (layer2-board-freshness),
    `syndicate/templates/shared/layer1_board.html` +
    `syndicate/features/shared/layer1_board.py` + `syndicate/blueprints/intelligence.py`
    (board-ui-freshness-slip-books), `syndicate/features/shared/live_refresh_loop.py`
    (mlb-props-regen). No overlap with this lane's set.
  - NOT claimed, deliberately: `syndicate/blueprints/intelligence.py` is held by
    `board-ui-freshness-slip-books`. If A4 needs a new counter on the wire,
    surface it to that lane rather than editing across the boundary — `#397`
    says a counter absent from that endpoint is invisible no matter how well it
    works, so this is a real constraint on A4, not a formality.
- Blocked by: none. Independent of Lane B (CLV) by design.

### soccer-odds-coverage — OPEN — opened 2026-08-14 — session: board-ui
- **STATUS 2026-08-14 19:3xZ — NO LONGER BLOCKED ON OBSERVABILITY. Now
  waiting on one scheduled event.**
  - `ccd10349` live on live-odds-worker **14:24:09 CDT**, post-deploy clean,
    zero tracebacks. The worker now reads the artifact its own detached child
    wrote and prints the per-step outcome to its OWN stdout, which is the only
    thing Render's collector captures.
  - **It emits nothing until the next launch, by design** — the on-disk status
    file predates the change and has no `artifactsDir`. Do not read the
    current silence as the fix failing.
  - **NEXT READABLE OUTCOME ~17:28 CDT.** Autorun fires ~17:13 (4h after
    18:13:14Z), reported one tick later. Read live-odds-worker's Render logs
    for `SOCCER_PREGAME_RUN_`.
- **What the log will decide, stated in advance so the reading is not
  post-hoc:**
  - `SOCCER_PREGAME_STEP name=soccer_<league>_odds ok=False rc=<n>` -> the odds
    step RUNS and FAILS. Take `rc` and the step's own stderr next.
  - odds steps absent from the summary entirely -> the run never reaches them;
    look at what precedes them and at the run's own exit.
  - `SOCCER_PREGAME_RUN_NO_ARTIFACT` -> the child dies before writing anything;
    the cause is in launch/startup, not in any step.
- The `#433` step reorder remains shipped and remains NOT a fix for this.
- **STATUS 2026-08-14 19:0xZ — producer identified, failure mode still
  unnamed. The reorder shipped by this lane does NOT fix it.**
  - `phase=pregame` builds 10 odds steps; `phase=live` builds **0**. So
    refresh-worker's soccer autorun (`phase="live"`) never fetches soccer
    odds. **The sole producer is `_launch_autorun_soccer_pregame_refresh` on
    live-odds-worker, 4h cadence.** Single point of failure.
  - A pregame autorun launched **18:13:14Z**, 31 min after `9a3a5bc6` (the
    reorder) went live — odds at steps #11-20, not #21-30. 43 min later: zero
    `game` rows for any league. **Position was never the variable.**
  - `PROCESS_TREE_MEMORY child_count: 0` at 18:21:34Z — subprocess likely gone
    ~8 min after launch. One periodic sample; loose bound, not proof.
  - **BLOCKED ON OBSERVABILITY, not on ideas.** The run's stdout/stderr go to
    a file on the worker's disk; web cannot read it (`exists=False` from
    `/api/ops/odds-refresh/logs` is the disk split, NOT missing logs). No
    error has been seen anywhere in four days.
- **NEXT ACTION, and it is deliberately small:** make
  `_launch_autorun_soccer_pregame_refresh` emit its per-step result summary to
  the worker's OWN stdout, which Render's log API does capture. That converts
  a four-day silent failure into a visible one. It is worker-path code in
  `scripts/run_live_odds_refresh_worker.py` — **claimed by OPEN lanes
  `refresh-worker-anon-leak` / `anon-allocation-site`, so it needs a lane
  reassignment or their owner.** Do not diagnose further without it; three
  hypotheses have already died for want of one log line.
- **ROOT CAUSE FOUND 2026-08-14 18:4xZ, and the lane's whole framing was wrong.
  It is not three leagues. Soccer GAME-odds capture is frozen for ALL of them.**
  Split the shard by `kind` and it is unambiguous:

      league               kind    rows   newest captured_at
      eredivisie           prop     467   2026-08-14T17:21:44   <- TODAY
      eredivisie           game      77   2026-08-10T20:54:06   <- 3.8 days
      primeira_liga        game     141   2026-08-10T20:54:08
      belgian_pro_league   game     111   2026-08-10T20:54:11
      championship         game      93   2026-08-11T00:54:47

  **Every league's `game` rows stop at 08-10/08-11 — eredivisie included.**
  Eredivisie only LOOKED healthy because it also carries 467 prop rows from a
  DIFFERENT producer (`fetch_soccer_oddsapi_props_local.py`) that ran today.
  The other three have no prop rows, so nothing masked them.
- **Corroborated independently by file mtime.** All four
  `<league>/api/odds/game_odds_current.csv` — the game-odds step's own output —
  bound to **48-96h old** via the export route's `since` filter. That matches
  the `game` row timestamps exactly. The probe was validated first against a
  control (the shard itself, known to have gained rows at 12:21 CDT, reads
  "within 2h, not within 1h") rather than trusted unvalidated.
- **This retires the league-specific hypothesis AND the step-position one.**
  There is nothing special about positions 8/9/10; there is something special
  about eredivisie having a second producer. `soccer_{league}_odds` has not
  written for ANY league in ~4 days.
- **It also explains two earlier observations I could not place:** the odds CSVs
  containing today's fixtures with real prices (written 08-10, when today was
  upcoming — the exact caveat I flagged and then nearly dismissed), and
  eredivisie's 99 board rows with only 5 projected (most of those rows are
  props, which is also why its board median read 62 min).
- **STILL UNKNOWN: why the game-odds step stops.** Now a single question about
  one step across all ten leagues, not ten questions — far more tractable.
  Next: get `soccer_<league>_odds` step stdout/stderr from a run, and check
  whether the step is even being SELECTED (its `phases=("pregame",)` means a
  `phase="live"` run builds no odds step at all — and refresh-worker's soccer
  unit autorun runs `phase="live"`).
- Goal: every active soccer league's odds refresh on their own cadence, not
  just the leagues near the front of `_SOCCER_LEAGUE_SLUGS`. Testable outcome:
  the newest `captured_at` per league in
  `soccer_source/tracking/book_quotes/<date>.jsonl` is within one sweep
  interval for ALL leagues with fixtures, not 3 of 6.
- **MEASURED AT THE SHARD, 2026-08-14 (production, via
  `/api/ops/artifacts/export`), shard `2026-08-14.jsonl`, 833 rows:**

      league               rows   newest captured_at
      eredivisie            488   2026-08-14T13:16:41Z   <- current
      primeira_liga         141   2026-08-10T20:54:08Z   <- 3.8 days
      belgian_pro_league    111   2026-08-10T20:54:11Z   <- 3.8 days
      championship           93   2026-08-11T00:54:47Z   <- 3.6 days

  Three of today's FOUR fixtures are in the dark leagues, kicking off 13:45,
  14:00 and 14:15 CDT.
- **The ordering is the signal.** Dark leagues are positions **8, 9, 10** in
  `_SOCCER_LEAGUE_SLUGS`; every fresh league (la_liga 2, mls 6, eredivisie 7)
  is earlier. `refresh_odds_sources.py:1220` builds ONE STEP PER LEAGUE in slug
  order, so a run that ends early always loses the same tail. primeira_liga and
  belgian stopped **3 seconds apart**; championship exactly 4h later — matching
  the autorun interval, i.e. successive runs each dying near the same point.
- **Two candidate causes FALSIFIED before hypothesising:**
  - Season gate: `active_leagues_for_date('2026-08-14')` returns **all 10**
    leagues active. It is not excluding them.
  - Per-league rotation starvation (`#356`): that is refresh-worker's SIM
    autorun (`run_refresh_worker.py:1140`, one league per tick). The ODDS half
    is `_launch_autorun_soccer_pregame_refresh`
    (`run_live_odds_refresh_worker.py:90`), which passes **no**
    `soccer_leagues` and so launches every league in ONE job. Not rotation.
  - Also ruled out: the leagues are not skipped wholesale — the live-state path
    writes their files (16:46:54Z, "0 live games"). It is specific to the odds
    fetch steps.
- **RETRACTED 2026-08-14 18:2xZ — the "ROOT CAUSE PROVEN" claim below is
  FALSIFIED. Read this before the block it retracts.**
  - **The falsifier: a SINGLE-LEAGUE scoped run for `belgian_pro_league`
    (job `0ca3c16b`, launched 12:59:45 CDT, confirmed claimed and running)
    captured NOTHING.** That job is ~6 steps. **A 6-step job cannot die at
    step 27.** Step truncation therefore cannot explain these three leagues.
  - Two further facts that cut the same way: the odds CSVs
    (`<league>/api/odds/game_odds_current.csv`) contain TODAY's fixtures with
    real prices for all four leagues — belgian 35 rows for 2026-08-14
    including Cercle Brugge v Sint Truiden at +125 — and the shard append
    (`_append_soccer_book_quotes`, which swallows exceptions and prints
    `append FAILED`) logged no failure on either worker.
    **CAVEAT, stated because it is exactly the trap I fell into this morning:
    a CSV written on 08-10 would ALSO contain today's fixtures, since they
    were upcoming then. I could not obtain the file mtime, so this is
    suggestive, NOT proof that the captures are fresh.**
  - **What I got wrong, and how.** The step-position correlation was real and
    striking — #27 fresh, #28/#29/#30 dark, no exceptions — and I promoted it
    to "proven" on the strength of the pattern alone, without running the
    four-minute single-league test that would have killed it. Correlation
    with a plausible mechanism is not a cause. This is the second time in one
    session I have taken a clean-looking pattern for a proof; the first was
    calling a 2h cadence an outage.
  - **The reorder that shipped from this claim is NOT harmful and is NOT
    withdrawn** — cheap captures should not queue behind ten sims regardless,
    it is tested, and it is pinned to one file — but it did not fix this bug
    and must not be recorded as having done so.
  - **The surviving discriminator, which is now the whole question:
    eredivisie captures and the other three never do — through the all-league
    autorun, a manifest job, AND a single-league scoped run.** Same script,
    same key, same region, same shard writer. That is league-specific, not
    position-specific. Next step is `/api/ops/oddsapi/sports` (`#433`,
    shipped) to see whether the vendor still lists those three keys at all.

- ~~**ROOT CAUSE PROVEN 2026-08-14 17:00Z via `/api/ops/odds-refresh/plan`
  (dry_run, cost nothing). The run is 50 steps GROUPED BY KIND, not by
  league:**~~ (retained for the ordering evidence, which is accurate; the
  causal claim is retracted above)

      steps  1-10   every league's schedule
      steps 11-20   every league's `artifacts`  <- TEN SOCCER SIMS
      steps 21-30   every league's odds
      steps 31-40   every league's props
      steps 41-50   every league's picks

  The odds steps land at #21-30 — **behind all ten sims.** And the boundary is
  exact:

      soccer_eredivisie_odds        step #27   CURRENT
      soccer_primeira_liga_odds     step #28   dark
      soccer_championship_odds      step #29   dark
      soccer_belgian_pro_league_odds step #30  dark

  **The run dies between step 27 and step 28.** That is not a hypothesis about
  ordering; it is the ordering, read off the planner, matching the observed
  fresh/dark split with no exceptions.
- **CORRECTION, and it changes the OTHER lane.** I wrote in
  `soccer-projection-gap` that it is "NOT downstream of the odds-coverage bug",
  reasoning that eredivisie's odds are current while 94 of its 99 markets carry
  no projection. The observation was right; **the inference was wrong.** Both
  are the SAME truncation at different step positions: eredivisie's ODDS step
  is #27 and ran; its PROPS step is #37 and its PICKS step is #47, and
  **steps 31-50 never execute for ANY league.** So no league gets props or
  picks, which is why soccer projection coverage is 30% and props are the worst
  of it. One cause, three symptoms — I had split it into two lanes on a
  distinction that does not exist.
- The earlier `web_process` / worker-recycle hypothesis is NOT needed to
  explain this and is not evidence-backed. What still needs naming is WHY the
  run stops at ~27 steps (time budget, memory, step timeout) — but the fix does
  not depend on that answer.
- **Fix direction, cheap and order-only:** run every league's ODDS before any
  league's `artifacts` sim. Odds fetches are seconds and 1.46 credits/call;
  the sims are minutes and are what consumes the budget. Reordering costs no
  additional OddsAPI spend and makes odds coverage independent of whether the
  sims finish. Prioritising leagues with fixtures TODAY is the second
  refinement, not the first.
- Falsification test: if a run is shown completing all 50 steps while the tail
  leagues still do not update, truncation is not the cause and the fault is
  inside the per-league fetch instead.
- Files (exclusive to this lane):
  - `scripts/refresh_odds_sources.py` — league step construction/ordering.
  - `tests/test_soccer_odds_coverage.py` (new).
  - **Ownership checked by PROBE, not by reading:** the two
    `refresh_odds_sources.py` claims in this file belong to CLOSED lanes
    (`sim-execution-observability`, `soccer-sim-grouping`), and the mention
    inside OPEN `refresh-worker-anon-leak` is PROSE, not a Files-block claim.
    `lane-guard.py` fed this exact path on stdin returns **exit 0**. No lane
    needed reassigning; the user authorised taking it and it was not held.
- MITIGATION FIRED FIRST, before diagnosis was complete: all-soccer pregame
  refresh job `a93384d014574861981a05328a62ebe9` at 11:52:22 CDT, because three
  games kick off within two hours and a correct fix does not arrive in time to
  matter for them. League scoping was NOT available — `soccer_leagues` is not
  plumbed through `/api/ops/odds-refresh/run`.
- Blocked by: none.

### soccer-projection-gap — OPEN — opened 2026-08-14 — session: board-ui
- **INCIDENTAL BUT DIRECTLY ON POINT, observed 2026-08-14 19:25Z** in
  live-odds-worker's logs while verifying an unrelated deploy:

      [build_soccer_artifacts] SOCCER_PLAYER_ROWS_MISSING league=eredivisie
        players_dir=/opt/render/project/data/soccer_source/eredivisie/players
      [build_soccer_artifacts] SOCCER_PLAYER_ROWS_MISSING league=primeira_liga
      [build_soccer_artifacts] SOCCER_PLAYER_ROWS_MISSING league=championship

  **The sim is reporting it has no player rows to simulate.** That is a
  first-class candidate for why soccer PROP markets carry no projections —
  which is where this lane measured the gap to be widest (eredivisie: 99
  market rows, 5 projected). The producer is saying, in its own log, that its
  input is missing.
  - **NOT yet a finding.** Observed once, on three leagues, while looking at
    something else. Nobody has checked whether `players/` is empty, stale, or
    simply relocated, nor whether game-line projections come from a different
    path that is unaffected. Do that before building on it.
  - Cheap first step: read `soccer_source/<league>/players/` on the worker's
    disk and compare against a league that DOES project.
- **CROSS-LANE NOTE from `recommendation-lane-correctness` (session model-audit),
  2026-08-14 19:1xZ. Not an edit to this lane's plan — one measurement its goal
  depends on. TWO PRODUCTION ENDPOINTS DISAGREE ABOUT THIS LANE'S HEADLINE
  NUMBER BY 250x, same sport, same date, 45 seconds apart:**

      /api/board/layer1?sport=soccer  rows 8,456  rows_with_projection 2,504 = 29.6%  [19:11:10Z]
      /api/board/layer2-shortlist     rows 8,512  rows_with_projection    12 =  0.1%  [19:10:25Z]

  This lane's "8,299 rows, 2,503 projected = 30.2%" is the **layer1** figure and
  its testable outcome is written against it. The **layer2** ingest — the join
  that actually puts `model_edge_pct` on the shortlist — reports
  `rows_with_projection: 12`, `rows_with_true_probability: 6`,
  `rows_with_model_edge: 0`, `matches_in_source: 4`,
  `unmatched_match_rows: 8,393`. These are two different joins and at most one
  describes the board a user sees. **Suggest not closing on a coverage number
  until it is settled which path is being measured.** Not investigated here —
  this lane's file set, not that one's.
- **Also relevant to scope:** for `player_shots` / `player_shots_on_target`,
  `soccer_projections` maps the source to a **mean** and refuses by design to
  derive a probability from it ("a mean presented as a probability is a
  fabricated edge"), and the rows are 100% one-sided so
  `_no_vig_over_probability` returns None. So those markets can never carry
  `edge_vs_market_pct` however well the sim runs — raising projection COVERAGE
  will not give them a model edge. `player_to_receive_red_card` and
  `player_assists` are not in the market map at all.
- **PREMISE CORRECTED 2026-08-14 18:4xZ — read this first.** This lane was
  opened on the reasoning that the projection gap is independent of the odds
  gap, because eredivisie's odds were current while 94 of its 99 markets had
  no projection. **Eredivisie's odds were NOT current.** Its `game` rows stop
  at 2026-08-10T20:54:06 like everyone else's; only its `prop` rows are fresh,
  from a different producer. The observation that founded this lane was an
  artifact of that mask.
- **What that does and does not change.** It removes the PROOF of
  independence — the two gaps may share a cause after all. It does NOT make
  them the same lane: 30% projection coverage, 37/75 `unknown` game states and
  56 game-chips on a 4-fixture day are still measured, still unexplained, and
  still not obviously downstream of a stale odds capture. Keep the lane, drop
  the claim.
- **Do not measure this lane until `soccer-odds-coverage` is fixed.** With
  game odds four days stale, any projection-coverage number is confounded.
- Goal: soccer markets on the board carry the sim's projections. Testable
  outcome: `rows_with_projection / rows` for soccer rises from **30%** toward
  the coverage MLB achieves (1,622 of 2,537 = 64% the same day), and no league
  with a fixture serves 0 projections.
- **MEASURED 2026-08-14 on the served board, and this is NOT downstream of the
  odds-coverage bug — which is why it is a separate lane:**

      league               market rows   with projection
      eredivisie                    99                 5   <- odds are CURRENT
      belgian_pro_league             4                 4
      championship                   3                 3
      primeira_liga                  4                 0   <- zero

  Board-wide soccer: **8,299 rows, 2,503 projected = 30.2%**.
- **The decisive observation:** eredivisie is the ONE league whose odds are
  current, and **94 of its 99 markets have no projection**. The odds arrived
  and the projections did not meet them.
- **~~So this cannot be explained by the capture gap, and fixing capture will
  not fix this.~~ THAT INFERENCE WAS WRONG — corrected same session, 17:00Z.**
  The planner shows the pregame run is 50 steps grouped BY KIND: schedules
  1-10, sims 11-20, odds 21-30, **props 31-40, picks 41-50** — and the run dies
  between step 27 and 28. So eredivisie's odds step (#27) ran while its props
  (#37) and picks (#47) did not, and **steps 31-50 never execute for ANY
  league.** The projection gap and the odds-coverage gap are ONE truncation
  observed at two step positions. I split them into two lanes on a distinction
  that does not exist; the shared fix is in `soccer-odds-coverage`.
- What this lane still owns, because reordering will NOT answer it: whether the
  sim actually produces per-market projections once its steps get to run, the
  37-of-75 `unknown` game states, and the game-chips date scoping. Those are
  not explained by step truncation and must be measured after the reorder
  lands, not before — otherwise a fixed run will be credited with fixing them.
- Second, possibly-related defect from the same payload: `by_state` reports
  **37 of 75 soccer games as `unknown`** — the game-state join failed on half
  the board. An unknown state is not cosmetic; `#298`/`#300` make it FAIL the
  staleness floor, so it can suppress rows downstream.
- Third, on the app-wide surface: `/api/board/game-chips` returns **56 soccer
  chips for date=2026-08-14** when only **4** fixtures are today — epl,
  bundesliga, serie_a and ligue_1 all appear and none play today. Every chip
  also carries `status`, `away_abbr`, `home_abbr` = null. The Layer 2 home
  cards are simultaneously over-inclusive on date and unhydrated.
- Hypothesis: not yet formed, deliberately. Three distinct symptoms (projection
  join, game-state join, chip date-scoping) could be one cause or three, and
  guessing here is exactly how the 08-14 cadence mistake happened. First action
  is to establish whether the soccer sim WROTE projections for today's fixtures
  at all, which separates "not produced" from "produced, not joined".
- Falsification test for that first step: if projection artifacts for
  eredivisie 2026-08-14 contain per-market projections the board is not
  showing, the sim is fine and this is purely a join defect. If they are absent
  or thin, the sim never produced them and the join is exonerated.
- Files: none claimed yet — read-only until the sim-vs-join question is
  settled. Naming files now would claim the wrong ones.
- Blocked by: none. Related to `soccer-odds-coverage` but independent of it,
  proven by the eredivisie row above.

### wnba-skill-backtest — CLOSED-VERIFIED 2026-08-14 — opened 2026-08-14 — session: nfl-day-of-game

**OUTCOME — the lane's stated testable outcome was "a correlation and an MAE
against a constant baseline over a stated sample, OR an evidenced statement that
the data does not support one". It produced the SECOND of those for WNBA, and
the FIRST for a model it did not originally scope.**

- **WNBA game lines: NOT MEASURABLE YET, and nothing is broken.** `pred_margin`
  appears only from 2026-08-02 — 47 files have no column, 0 have it
  unpopulated, 14 have it and every one is 100% populated. 9 of 361 completed
  games carry a projection. Needs TIME, not work: n=30 ~2026-08-26. Re-run
  `scripts/backtest_wnba_projection.py` then; it needs no changes.
- **MLB hitter props: MEASURED (`aac18260`).** 2,487 player-games, exact
  `batter_id` join, DNPs excluded. Biased, not blind — every counting market
  carries signal AND loses to a constant baseline; de-biasing flips 5 of 7.
  Two stacked causes: opportunity +18.4%, per-PA rate +12.2%, opportunity
  explaining 55%. Written into `mlb_prop_calibration.MEASURED_SKILL` and
  attached by the producer, so `projection_skill` stands aside for measured
  markets and still stamps `unmeasured` for the rest.
- **`#428` rescoped: FOUR models, not six.** `live_projection_join` is a join
  and `game_board_contract` is a passthrough; neither is backtestable.
- **NOT DEPLOYED.** `aac18260` is committed and pushed only.
- Three self-inflicted defects caught and fixed inside this lane, all recorded
  in `learnings.md`: a guard gating on the wrong denominator, a verdict
  stronger than its threshold, and a test whose name did not match its
  assertion.
- **Two coverage zeros RETRACTED as evidence**, not findings: `wnba_projections`
  (probe read the wrong CSV shape — values are nested in `plays`) and
  `soccer_projections` (guessed path, no positive control).
- Files released: `scripts/backtest_wnba_projection.py`,
  `scripts/backtest_mlb_props.py`,
  `syndicate/features/shared/mlb_prop_calibration.py`,
  `syndicate/features/shared/prop_projections.py`.

### wnba-skill-backtest — CLOSED-VERIFIED — superseded header, kept for the file/line map
- Goal: `#428`, first of six. Measure whether the WNBA game model predicts
  anything, and write the answer into a `MEASURED_SKILL`-shaped constant the
  producer attaches itself. Testable outcome: a correlation and an MAE for
  `pred_margin` and `pred_total` against real finals, **each reported against a
  constant baseline**, over a stated sample size — or an evidenced statement
  that the data does not support one.
- **WHY WNBA FIRST:** production holds **81 dates** (2026-05-17..08-15), the
  deepest of any sport, and its contract ships MEANS WITHOUT A DISTRIBUTION, so
  correlation is the only honest measure available and there is no probability
  to be tempted into deriving.
- **THE "BLOCKED ON DATA" PREMISE WAS WRONG AND IS ALREADY CORRECTED IN `#428`.**
  It came from a LOCAL read ("4 game-card files"); production has 81 dates. The
  local `game_cards_*.csv` are 7-column stubs with no projections at all, while
  production's carry 19 columns including `pred_margin` / `pred_total`. Do not
  scope anything here from the checkout.
- Data, both confirmed by fetching before any code was written:
  - PROJECTIONS — production `wnba_source/data/processed/game_cards_<date>.csv`
    via `/api/ops/artifacts/stream?path=`, admin token. Carries `pred_margin`,
    `pred_total`, plus the market's `home_spread` / `total` for a baseline.
  - OUTCOMES — **not in that file.** Sourced from ESPN's public WNBA scoreboard,
    the same feed `#429`-era NFL work already uses. Join on date + tri-codes.
- Files (exclusive to this lane):
  - `scripts/backtest_wnba_projection.py` (new)
  - later, if a number is produced: a `MEASURED_SKILL` constant + the one-line
    producer attach in `syndicate/features/shared/wnba_projections.py`
- **HAZARDS, written before running anything:**
  - **Report MAE against a CONSTANT BASELINE, not bare correlation.** NFL's
    totals model sits at r=0.269 and beats the historical mean by only 0.22
    MAE; a bare r would have read as skill. The baseline is the finding.
  - **A sample size is part of the number.** `#377`/`#429` both produced
    authoritative-looking values with no n behind them. If the join yields few
    games, say so and do NOT emit a constant.
  - **Publish the INTERSECTION, not the union** — CLAUDE.md's standing trap.
    Dates with a projection but no final, or vice versa, are excluded and
    COUNTED.
  - Margin sign convention must be pinned against a real game before any
    correlation is believed; an inverted sign turns skill into anti-skill and
    looks plausible either way.
- Falsification: if the model has no skill, that is a RESULT and gets written
  down. `#367` did exactly that for NFL (corr −0.047) and it is why NFL's
  margin projection is suppressed today.
- Blocked by: none.

### odds-capture-stall — CLOSED 2026-08-14 — NOT A DEFECT: the 2h gap IS the configured pregame cadence
- **Outcome: EXONERATED. There was no stall.** The gap is
  `_PREGAME_SWEEP_INTERVAL_FALLBACK = 2 * 3600` in
  `live_refresh_loop.py:3955`, a deliberate `#15 Phase 1` decision dated
  2026-07-27 in its own comment: *daily sports drift-sample every 2h pregame,
  soccer every 8h.* My hypothesis (a gate skipping the fetch through failure)
  named the right MECHANISM and the wrong CHARACTER. The alternative I wrote
  into this lane before testing — "is 2h just a long sample of the ordinary
  cadence" — is the one that won.
- **The reconciliation, every number:**
  - `PREGAME_CADENCE_DETAIL` prints the gate's own arithmetic:
    `mlb:marker_age_s=1820/interval_s=7200`. MLB is skipped until its marker
    passes 7200s.
  - 13:09:01Z — skip list `nfl,soccer,wnba`; **MLB absent, so MLB swept.**
    Quote observed 13:09:14Z. The 13-second offset is the sweep itself.
  - 13:39 / 13:54 / 14:09 / 14:25 / 14:40Z — MLB in the skip list, marker_age
    climbing 1820 -> 4564, all under 7200.
  - 15:10:38Z — skip list `nfl,wnba`; **MLB absent again, so MLB swept.**
    Freshest observation moves to 15:10Z.
  - 13:09 -> 15:10 is **7,289s against an interval of 7,200** — the gap is the
    constant plus one tick's rounding. Nothing failed.
  - Per-sport intervals confirmed live in the same log line: mlb/nfl/wnba
    7200s, soccer 28800s. That reconciles the cross-sport spread measured at
    10:37 (mlb 23.5m, wnba 54.0m, nfl 53.1m, soccer 12.9m) — every one of those
    is a position inside its own sweep interval, not a health signal.
- **Near-game cover DOES exist and I nearly missed it.** `_t_window_due_sports`
  arms a per-game **T-75** ramp sweep and a **T-10** closing sweep, for mlb and
  wnba only (`_T_WINDOW_COMMENCE_PROVIDERS`). So an individual game gets two
  fresh looks close to its own start regardless of the 2h drift cadence. The
  exposure is the MIDDAY window between sweeps, not the moments before a game.
  Zero `T_WINDOW_SWEEP_DUE` in my 13:00-15:30Z sample is CORRECT and carries no
  information: first pitch was 18:20Z, so T-75 could not arm until 17:05Z. An
  absence outside the window is not an absence.
- **Not memory, not a crash, and both were checked before being ruled out:**
  795MB/2048MB with 1252MB headroom; zero `MEMORY_GUARD` hits; the two
  `server_failed earlyExit=true evicted=false` events are the worker's own
  `max_uptime_seconds` recycle (`run_live_odds_refresh_worker.py:411` prints
  `RECYCLING ... to reset accumulated page cache`), ~6h apart, by design.
- **What this leaves OPEN, and it is a product decision, not a bug:** is a 2h
  pregame drift sample the right cadence for a board that is priced off? The
  levers are named and are env-only, no code change:
  `SYNDICATE_PREGAME_SWEEP_INTERVAL_SECONDS_<SPORT>` per sport, or
  `SYNDICATE_PREGAME_SWEEP_INTERVAL_SECONDS` globally
  (`live_refresh_loop.py:3958`). Tightening them spends OddsAPI budget against
  the 5M call cap. **NOT CHANGED — handed to the user with the tradeoff stated.**
- Verification: the falsification test ran and killed the hypothesis. Recorded
  as an exoneration rather than quietly dropped.
- Files: none touched. Read-only diagnosis throughout, so the claimed-file
  conflict with `mlb-props-regen` / the memory lanes never had to be resolved.

### (superseded lane detail — the OPEN body this lane was opened with)
- Goal: name why MLB odds went **2h01m without a single new quote observation**
  on 2026-08-14 while the refresh loop ticked ~8 times through it. Testable
  outcome: the gap is attributed to a named gate/failure with a log line or a
  counter proving it, and either fixed or filed with the fix specified.
- **MEASURED BEFORE HYPOTHESISING, all times CDT:**
  - Freshest MLB quote observation was **08:09:14** and was still 08:09:14 when
    re-read **78 minutes later** — the identical instant, so this is a stall,
    not a slow cadence. Read twice off `/api/board/layer1` (10:00 and 10:18).
  - The board artifact rebuilt normally through the whole gap (10:09 build
    against 08:09 odds). **Board freshness and odds freshness are independent**
    — the grid keeps re-pivoting a frozen shard, which is exactly why nothing
    downstream noticed.
  - **The loop was NOT dead.** `loop_tick_begin` on live-odds-worker at 08:08,
    08:24, 08:39, 08:54, 09:09 ... and `loop_sleep` carrying
    `interval_seconds: 900`, i.e. the adaptive pregame cadence, working as
    designed. Ticks ran; quotes did not appear.
  - **Not memory.** 795MB of 2048, 1252MB headroom, zero `MEMORY_GUARD` hits in
    the window. The two `server_failed earlyExit=true evicted=false` events
    (06:16Z, 12:22Z, ~6h apart) are the worker's OWN `max_uptime_seconds`
    recycle, not crashes — `run_live_odds_refresh_worker.py:411` prints
    `RECYCLING ... to reset accumulated page cache`. Do not chase these.
  - **It recovered on its own** between 10:18 and 10:36 (freshest observation
    moved to 10:10). So the target is an intermittent gate, not a dead service.
  - Cross-sport at 10:37: mlb 23.5m, wnba 54.0m, nfl 53.1m, soccer 12.9m. Tens
    of minutes is NORMAL here. The 2h hole is the tail of an existing
    distribution, not a unique event — so "is 2h just a long sample of the
    ordinary cadence" is a live alternative to the gate story and must be
    tested, not assumed away.
- Hypothesis: the tick runs but the per-sport fetch is skipped by a gate that
  is time- or state-dependent (a T-window/cost gate, an "already captured"
  short-circuit, or an OddsAPI error swallowed into a no-op), so the tick
  reports success while writing nothing to the `book_quotes` shard.
- Falsification test: if a tick inside a stall is shown to CALL the OddsAPI and
  receive quotes, then the fetch is not being skipped and the loss is
  downstream in the shard write or the last-seen tracking — a different fix in
  a different file, and this hypothesis is dead.
- Secondary falsifier: if the per-tick quote-write count is nonzero throughout
  the 08:09-10:10 window, then nothing stalled and `seen_age` is simply not
  measuring what the board is now reporting — which would make the freshness
  field I just shipped WRONG and is the first thing to rule out.
- Files: none claimed yet — this is read-only diagnosis until the gate is
  named. Any fix will land in `syndicate/features/shared/live_refresh_loop.py`
  or `scripts/run_live_odds_refresh_worker.py`, **both of which are claimed by
  OPEN lane `mlb-props-regen`** (`live_refresh_loop.py`) and
  `refresh-worker-anon-leak` / `anon-allocation-site`
  (`run_live_odds_refresh_worker.py`). Diagnosis can proceed; a fix cannot be
  written here without reassigning that file. Flagged now rather than at the
  point of edit.
- Blocked by: none for diagnosis. Blocked on lane reassignment for any fix.

### board-ui-freshness-slip-books — CLOSED 2026-08-14 — all three shipped and verified
- **Outcome: DONE.** Deploy `b98f5ed7` (web, live 15:33:06Z), then the ops
  half as `f9aa2399`/`8ff4e513`.
  1. Odds age is served AND rendered — non-null on `view=all` and `pregame`,
     null with 0 games on `live`. The API test caught a real bug pre-deploy:
     the timestamps were derived BEFORE `partition_board_by_state`, which
     recomputes the block, so every filtered tab would have silently lost the
     odds age while `all` looked correct.
  2. Rail: `board_cards.css` linked (the slip's styles never loaded on this
     page), collapse returns 250px to the board (920 -> 1170 measured), Ask
     button on every row with context resolved off the `<tr>`.
  3. Books default to the operator's 11 of 36, All-books one click away,
     hidden count stated. 20 header columns instead of 46.
- One prediction MISSED and recorded as such: I said the odds age would read
  >120 min; it read 23.0 because the capture recovered between readings. The
  number I committed to was a property of the outage, not of the change.
- 95 tests green. Verification written into `deploys.md`.
- Goal: three UI defects on `/<sport>/market-board`, each with a testable
  outcome:
  1. **The board reports build age and hides odds age, and the two differ by
     two hours.** MEASURED 2026-08-14 15:00Z against production
     (`/api/board/layer1?sport=mlb&date=2026-08-14&window=slate`): artifact
     `generated_at` 14:58:49Z — **1.6 min old** — while the freshest `updated_at`
     across all 14 games' rows is **13:09:05Z (8:09am CDT), 1h51m old**, and
     the minimum `seen_age_seconds` (6576.8s) independently agrees. The header
     says "built 2m old" and a reader takes that as the odds. Outcome: the meta
     strip carries an odds-observation age derived from the rows, warn-styled
     past a threshold, and the two ages are never conflatable.
  2. Bet slip is unstyled and un-collapsible on this page, so the rail eats
     board width permanently. ROOT CAUSE FOUND: `bet_slip.js` renders
     `.bet-slip__*` markup whose styles live ONLY in
     `static/shared/board_cards.css`, which `intelligence.html` loads and
     `shared/layer1_board.html` does not. Outcome: slip renders identically to
     the main board's, collapses, and each row carries the same
     `data-ask-action="ask-pick"` Syndicate button the main board has.
  3. 36 books render as 36 columns on MLB. Outcome: a user-chosen default
     subset with a one-click "all books" toggle, persisted.
- Files (exclusive to this lane):
  - `syndicate/templates/shared/layer1_board.html` — the board page itself.
  - `syndicate/features/shared/layer1_board.py` — board-level odds-freshness
    derivation (`#1`).
  - `syndicate/blueprints/intelligence.py` — `/api/board/layer1` provenance
    fields only.
  - `tests/test_layer1_board.py` — new cases.
  - Collision check: CLEAR. Parsed every OPEN lane's claim block 2026-08-14;
    the four other OPEN lanes claim `pipeline/intelligence_state.py`,
    `syndicate/features/shared/{projection_skill,board_enrichment,memory_observability,live_refresh_loop,refresh_state_store}.py`,
    `scripts/run_refresh_worker.py` and their tests. No overlap.
  - NOT claimed, deliberately: `syndicate/static/shared/bet_slip.js` and
    `board_cards.css` are shared by five boards; this lane LINKS the stylesheet
    rather than editing either.
- Hypothesis (diagnostic half, `#1`): the board's odds are stale on a cadence
  the artifact rebuild hides — the grid rebuilds every ~10 min off a quote
  shard that is refreshed far less often, so build age is not odds age.
- Falsification test: if a fresh read shows `updated_at` tracking
  `generated_at` within minutes, the two ages are the same quantity, the
  measurement above was a one-off capture gap, and item 1 is cosmetic.
- Verification: re-fetch `/api/board/layer1` after deploy and confirm the
  served payload carries the odds-observation timestamp; drive the page with
  the `run-syndicate` skill and confirm the slip renders styled + collapses and
  the default column count drops from 36 to the chosen set.
- Blocked by: item 3 needs the user's book selection before it can be built.
- **`.syndicate/.current-lane` TAKEN FROM `layer2-board-freshness`, and that is
  a real cost, not a formality.** I first tried to leave it alone, reasoning
  that the guard only blocks files another lane claims — WRONG, and it blocked
  my own first edit. `lane-guard.py` skips a claim only when
  `slug == current`, so the marker is not "who else is running", it is "whose
  claims are waived". It is single-valued, so two concurrent lanes cannot both
  be protected: while it names this lane, `layer2-freshness` is blocked from
  editing `pipeline/intelligence_state.py` — its OWN claimed file. Restored to
  `layer2-board-freshness` at this lane's checkpoint. If that session hits a
  BLOCKED message in the meantime, this is why.

### build-time-estimate — CLOSED 2026-08-14 — board build timed at ~2-4 min on current code; estimator can no longer collapse to ~0 — opened 2026-08-14 — session: layer2-freshness
- **VERIFICATION RAN, both criteria, result stated.**
  1. Unit test in which an all-short-circuit window must not yield ~0:
     `tests/test_deploy_safety_build_estimate.py` 9 passed, and
     **mutation-pinned** — restoring `return max(values)` turns exactly that one
     test red (`0.0 not greater than or equal to 60.0`), the other 8 stay green.
  2. `check_deploy_safety.py` against live data still reports
     `a build takes ~2.3min` — unchanged, because the fix only alters the
     all-short-circuit case. `tests/test_deploy_preflight.py` 9 passed.
- Commit `0ddecded` (local). Operator-side script only; **no service code, no
  deploy, nothing to measure in production.**
- Outcome: a current board build is **~2-4 min** (n=39, p90 146.19s, max
  209.66s), not ~23. The 23-min figure predates `#414` and is left in place with
  the measurement beside it rather than retired on one 4h window.
- Two corrections to `#427` itself, both now in the ticket: its item 1 was
  already satisfied (`_expected_build_seconds` always used `max`), and the
  23-minute figure is not "unsourced" — the docstring traces it to a real
  22.9-min build.
- Left open in the ticket, deliberately: `candidate_collection_with_fallback` is
  a wrapper and the 138-210s sits somewhere inside it. That decomposition is the
  only place new instrumentation would earn its cost.
- Goal (`#427`): the deploy gate's build-duration estimate cannot collapse to
  ~0 when its sample happens to contain only empty-pool short-circuits, and the
  ticket's three disagreeing figures are reconciled against the CURRENT code.
  Testable outcome: `_expected_build_seconds` returns a value derived only from
  calls that did real work, and returns a conservative fallback (never None-as-
  zero, never ~0) when the window contains none.
- **MEASURED FIRST, refresh-worker 4h to 2026-08-14 18:0xZ, live `294f9ca9`:**

      COLLECT_SPAN_EXIT collect_candidates   n=39  p50=0.00  p90=146.19  max=209.66
        of those >= 1s:                      n=9   p50=138.30            max=209.66
      fraction >= 60s: 23.1%      fraction >= 600s: 0.0%
      BUILD_SPAN_EXIT candidate_collection_with_fallback n=38 p50=0.00 p90=260.28 max=434.26

  **So ~77% of calls are the empty-pool short-circuit and the real ones cluster
  at 138-210s.** A current board build is ~2-4 min, NOT ~23 min. The 23-minute
  figure predates `#414` (21.5x on the quote join) and describes a board that no
  longer exists.
- **NEAR-MISS, recorded because it nearly became a filed defect.** From the
  distribution I computed "max of the LAST 12 = 0.1s" and was about to report
  the gate as broken. Running the gate instead returned **`a build takes
  ~2.3min`**. Cause: `_render_logs(..., limit=12)` gets rows **oldest-first
  regardless of direction** — a quirk already in `learnings.md` — so the 12 it
  samples are not the 12 I ranked. **The defect is LATENT, not live.** Do not
  write it up as a live failure.
- Files (claimed by this lane):
  - `scripts/check_deploy_safety.py` — `_expected_build_seconds` only.
  - `tests/test_deploy_safety_build_estimate.py` (new).
  - `docs/ai_context/todo.md` — `#427` findings.
  - Collision check: `lane-guard` stdin probe returns exit 0 for all three; the
    only lanes naming these files are CLOSED (`board-transport`) or mention them
    in prose rather than claiming them.
- Hypothesis: the estimator's MAX defence was chosen against a mixed sample
  (where a median would sag) and is undefended against a sample that is
  ENTIRELY short-circuits, in which case max is also ~0.
- Falsification test: if fewer than ~10% of `COLLECT_SPAN_EXIT` values are
  sub-second, the short-circuit population is too small to threaten the sample
  and this lane is solving a non-problem. **Measured 77% — it is real.**
- Verification: a unit test in which an all-short-circuit window yields the
  conservative fallback rather than ~0, red against the current implementation;
  plus `check_deploy_safety.py` still reporting a sane figure on live data.
- Blocked by: none. No deploy — this is an operator-side script.

### layer2-board-freshness — CLOSED-VERIFIED 2026-08-14 — 3h clean window, all five criteria met — opened 2026-08-14 — session: layer2-freshness
- **CLOSED ON THE FULL 3h READ (16:16:56-19:24Z, 187.3 min, commit `294f9ca9`
  unchanged, verified by SHA).** 37 refreshes = 11.9/hour against 1.7/hour;
  23 of them via the new fast path; longest gap 11.8 min against 104.7;
  96 `MEMORY_GUARD_ABORT` so the guard is still actively refusing;
  `LAYER2_GUARD_SKIP` 0 across all 96, so the 600MB floor is correctly sized;
  zero failures, zero OOM. Full detail and the one residual confound in
  `deploys.md`.
- Second work item (`pool["overview"]` retention) shipped as `100c9cb5`,
  **committed, NOT deployed** — it rides the next refresh-worker deploy.
- **CLEAN-WINDOW RESULT 16:16:56-18:00:49Z (103.9 min, no intervening deploy):
  22 refreshes = 12.7/hour against a 1.7/hour baseline; 8 of them via the new
  fast path on cycles the Layer 1 guard refused; longest gap 11.8 min against
  104.7; `LAYER2_GUARD_SKIP` = 0 so the 600MB floor held; zero failures, zero
  OOM.** Full detail and the two stated caveats (abort rate also fell; span is
  104 min not 180) are in `deploys.md`.
- **SECOND WORK ITEM ADDED 2026-08-14, same file, same session: `pool["overview"]`
  retention.** Kept in this lane rather than opening a rival one, because a
  second lane claiming `pipeline/intelligence_state.py` would fight this one for
  the single `.current-lane` marker.
  - `_build_candidate_pool` embeds **every sport's fully hydrated overview** into
    the returned pool (`"overview": [dict(item) for item in overview ...]`),
    which is then cached up to `_max_snapshots`=12 deep AND JSON round-tripped on
    every build and every cache hit.
  - Its ONLY consumer is `_live_pipeline_summary`, which reads it for per-sport
    COUNTS (live games, live prop items, distinct game ids) and one timestamp.
  - **DONE, commit `100c9cb5`, NOT DEPLOYED.** `pool["overview"]` is replaced by
    `pool["overview_summary"]` — five derived values per sport from a new
    `_overview_live_summary`. The legacy key is still READ as a fallback because
    `run_intelligence_query` persists the whole pool inside its response.
    `tests/test_overview_summary_retention.py` 7 passed; the load-bearing one is
    EQUIVALENCE (`json.dumps(sort_keys=True)` over the real consumer), not the
    byte saving.
  - **The saving is NOT quantified and must not be quoted as MB.** What is
    established is the SHAPE: 12 cached pools x 8 hydrated sport rows, plus a
    JSON round-trip of all of it per build and per cache hit. Sizing it needs a
    real slate.
  - **Next in this thread: the SUM -> MAX streaming change itself**, now
    unblocked. `_collect_candidates` and `_odds_history_payloads_by_sport` both
    already iterate per-sport; the `skip_game_hydration=True` fingerprint pass
    must NOT be streamed (its output is a fingerprint — truncating it keys the
    caller's cache off a partial sport list).
  - So this is the last whole-list holder of the hydrated overview, and dropping
    it is the prerequisite for the handoff's architectural fix (peak SUM -> MAX):
    a streamed per-sport overview cannot exist while something downstream keeps
    the whole list alive.
- **Lane stays OPEN only for the span shortfall.** The criterion was a 3h clean
  window and this is 1.73h. Closing on it would be retro-fitting the criterion
  to favourable data.
- **STATUS 2026-08-14 17:4xZ.** Deployed and its path is PROVEN to execute:
  `LAYER2_FAST_REFRESH` x6, 24 refreshes / 126 min, longest gap 19.6 min against
  a 104.7-min baseline, with 28 `MEMORY_GUARD_ABORT` in the same window (the
  guard refusing is the condition this change exists for). `LAYER2_GUARD_SKIP`
  = 0, so the 600MB floor held. Lane stays OPEN because two other deploys
  landed inside the window and the AGGREGATE is therefore not cleanly
  attributable — the liveness is, the magnitude is not.
- **NEXT ACTION:** take one clean 3h window with no intervening deploy and
  re-run the same counts. Only then close.
- **STATUS 2026-08-14: the change is written, tested and mutation-pinned. It is
  NOT deployed and its production effect is UNMEASURED.** Working tree only:
  `pipeline/intelligence_state.py` (+216), `tests/test_layer2_fast_refresh.py`
  (new, 7 tests). Do not record this lane as delivering anything until the
  verification query below has been re-run against a deployed commit.
  - What shipped into the tree: `_abort_if_memory_critical(stage, floor_bytes)`
    extracted from the existing guard (which is now a wrapper, unchanged in
    behaviour); `_LAYER2_MIN_SAFE_HEADROOM_BYTES = 600MB`;
    `_refresh_layer2_shortlist_only()`; the split refusal at the
    `pre_source_state_fingerprint` branch. The `MEMORY_GUARD_ABORT` line gained
    `floor_mb=` so two live floors are tellable apart.
  - Gates on the fast path, in order: env flag
    `SYNDICATE_LAYER2_FAST_REFRESH_ENABLED` (default ON — absent means ON, say
    so before touching `render.yaml`), `refuse_if_compute_in_request_path`
    (web runs `run_intelligence_query` in a request and is a 2GB container),
    `SYNDICATE_LAYER2_FAST_REFRESH_SECONDS` rate limit (default 300s, shared
    with the full build's shortlist write), then its own 600MB floor.
  - **Mutation-pinned, which is the part worth trusting.** Repointing the fast
    path at the 1900MB floor turns 2 of 7 tests red with
    `MEMORY_GUARD_ABORT stage=layer2_fast_refresh floor_mb=1900` in the
    captured stdout — the branch executed and the floor is the discriminator.
  - Also green: `test_malloc_trim_release.py` 7 (trim ordering is pinned there
    and the guard was refactored), `test_candidate_pool_manifest_gate.py` 9,
    and `state.md`'s 4-test cheap smoke from `test_intelligence_state.py`.
  - NOT included, deliberately (one change per deploy): `pool["overview"]`
    embeds every sport's hydrated overview into the cached candidate pool
    (`_max_snapshots`=12) and is read only by `_live_pipeline_summary`, for
    counts and one timestamp. Real retention, worth its own change — but pools
    cache only when `candidate_count > 0`, so it is not the plateau.
  - Deploy exposure when it goes: refresh-worker `.py` only, no `render.yaml`.
    Needs `/preflight`, an in-flight-sim check, and the live SHA re-read inside
    the deploying step.
- Goal: the Layer 2 shortlist (the board web actually serves) refreshes on a
  cadence set by ITS OWN cost, not by whether refresh-worker has enough
  headroom to hydrate eight sports' overviews. Testable outcome: over a 3h
  production window, `LAYER2_SHORTLIST` build count rises from 5 and the
  longest no-rebuild gap falls well below the measured 104.7 min, with no new
  OOM kill and no change to the Layer 1 pool's own guards.
- **MEASURED FIRST (refresh-worker, 11:39-14:39Z 2026-08-14, live commit
  `2e4e2544` re-read in the same run):**
  - **146 `MEMORY_GUARD_ABORT stage=pre_source_state_fingerprint` vs 5
    completed builds = 96.7% of board cycles refused before any work at all.**
    That guard is `_MIN_SAFE_MEMORY_HEADROOM_BYTES` (1900MB), and its own
    comment says it is sized for `build_intelligence_overview`'s ~1.9GB
    transient. `anon` p50 pre-reboot was ~2200-2800MB against the 2196MB it
    needs (4096-1900), so it refuses roughly whenever it looks.
  - Longest gap with NO Layer 2 rebuild: **104.7 min** (12:44:20 -> 14:29:00Z).
    That is the stale board: candidates whose games started during it.
  - The refusal is total. Line 5266 returns `{"ok": false, "error":
    "memory_guard_abort"}` for the WHOLE publication, so the shortlist — which
    does not read the overview — dies with it.
  - **Layer 2 does not consume what the guard is protecting.** On 3 of the 5
    completed builds the Layer 1 pool returned `count=0` while
    `LAYER2_SHORTLIST` returned **256 rows from 13,665 opportunities** on the
    same cycle. `build_layer2_shortlist(selected_date, manifests.keys())` needs
    only the date and `_available_sport_manifests` — not `overview`, not
    `candidates`, not `_collect_candidates`.
  - **The Layer 2 stage's own cost, measured across 4 builds:** 14-27s and
    +27 to +181MB container. Against a 1900MB floor.
  - Legacy `candidate_collection_with_fallback` cost 498.7s of the 3h window.
- **NOT THE FORBIDDEN CHANGE.** This does NOT lower
  `_OVERVIEW_MIN_SAFE_HEADROOM_BYTES` (3000MB) or
  `_MIN_SAFE_MEMORY_HEADROOM_BYTES` (1900MB). Both stay exactly as they are and
  keep gating exactly the stages they were measured against. This adds a
  SEPARATE, SMALLER floor in front of a SEPARATE, CHEAPER stage — which is what
  that constant's own comment asks for: "the floor must be the cost of the
  stage being guarded, not a round number." See
  `docs/ai_context/handoff_overview_hydration.md`, do-not #1.
- Files (claimed by this lane):
  - `pipeline/intelligence_state.py` — the Layer 2 fast path and the split
    refusal at the `pre_source_state_fingerprint` guard.
  - `tests/test_intelligence_state.py` — new cases.
  - No OPEN lane claims either (checked 2026-08-14 against the live
    `lane-guard.py` via stdin probe, exit 0, and against the nearest-preceding-
    header map in this file).
- Hypothesis: board staleness is NOT build slowness. It is refusal rate. The
  builds that run are fine (27s tail); 96.7% of them never start.
- Falsification test: if `LAYER2_SHORTLIST` count does not rise after the
  change, the refusals were not what was blocking it and this lane is wrong.
  A second falsifier: if the Layer 2 fast path's own floor is crossed as often
  as the 1900MB one, then the shortlist is not as cheap as the four samples
  say and the measurement was too narrow.
- Verification: the same 3h production query re-run post-deploy — build count,
  longest gap, abort count by stage, and an OOM check in the Render EVENTS api
  (not the logs; `#423` records that kills are invisible in logs).
- **Policy note, stated rather than hidden: this is the 5th OPEN lane against a
  documented cap of 3.** The cap is policy with no enforcement (`state.md`).
  Flagging rather than silently exceeding.
- Blocked by: none.

### projection-skill-declaration — CLOSED-VERIFIED 2026-08-14 — opened 2026-08-14 — session: nfl-day-of-game

**OUTCOME — the lane's stated testable outcome, met on production.** Every
projection row on every sport carries a `model_skill` block; NFL keeps its
richer measured note untouched; the other producers report
`status: "unmeasured"` explicitly.

Shipped `2d6f7a2f`. **DEPLOYED AND VERIFIED on both services** — web
`03:09:33Z`, refresh-worker `14:22:32Z`.

    nfl      20 rows   {'measured': 20}      <- normalize path
    mlb    1631 rows   {'unmeasured': 1631}  <- the point of #425 gap 1
    wnba    209 rows   {'unmeasured': 209}
    soccer   12 rows   {'unmeasured': 12}

**NFL alone would not have proven it** — it is the one producer with real skill
numbers, so it only exercises the normalize branch. 1,852 rows across three
sports now declare that nobody has measured the model behind them.

- Counts surface in the `projections` coverage block
  (`rows_with_measured_skill` 101 / `rows_with_unmeasured_skill` 947 on NFL's
  book-grid), **not** in `counts` — an earlier claim in this lane said `counts`
  and was wrong.
- **`#425` was closed on BOTH gaps and the six MEASUREMENTS were carved out as
  `#428`** rather than left to age inside a closed ticket. `#428` is blocked on
  data, not effort: soccer results 0 files, MLB `feed_live` 1 date, WNBA
  game-cards 4 files.
- **CLOSED LATE, and that is the lesson.** The work shipped and was verified
  hours before this header was updated, during which `lane-guard` returned
  **exit 2** for `projection_skill.py` and `board_enrichment.py` — locking two
  files against every other session for no reason. A lane whose work is done is
  not a harmless stale note; it is an active lock. Close it when the
  measurement lands, not at checkpoint.
- Files released: `syndicate/features/shared/projection_skill.py`,
  `syndicate/features/shared/board_enrichment.py`,
  `tests/test_projection_skill.py`.

### projection-skill-declaration — CLOSED-VERIFIED — superseded header, kept for the file/line map
- Goal: `#425` gap 1. Every projection on the board declares whether its model
  has ever been evaluated, so a consumer can tell a validated number from an
  unvalidated one. Testable outcome: 100% of projection rows carry a
  `model_skill` block on every sport; NFL keeps its richer measured note
  untouched; the other six report `status: "unmeasured"` explicitly.
- **SCOPE, AND WHAT THIS DELIBERATELY DOES NOT DO.** It does NOT measure the six
  models. That needs six bespoke backtests and the data is not there:
  measured on this checkout today — soccer results **0 files**, MLB
  `feed_live` **1 date**, WNBA processed game-cards **4 files**. CLAUDE.md's
  standing warning is exactly this case: a backtest built on those "will look
  like it ran on months of data and actually be running on whatever the
  narrowest family happens to cover". Producing `correlation: 0.31` from n=4
  would be `#377`'s own failure — an authoritative-looking number that means
  nothing — committed by the ticket written to prevent it.
- So this closes the SYSTEMIC half: silent absence becomes **declared**
  absence. `unmeasured` is a first-class value, not a missing key. The six
  actual measurements get their own ticket with the data gate named.
- Files (exclusive to this lane):
  - `syndicate/features/shared/projection_skill.py` (new)
  - `syndicate/features/shared/board_enrichment.py` — one call in the existing
    `attach_projections` wrapper
  - `tests/test_projection_skill.py` (new)
- Design:
  - Same choke point as the degeneracy detector: the `attach_projections`
    wrapper. One place, seven sports, 13 return sites, zero call sites.
  - **Never overwrite a producer's own note.** NFL's `skill_note` is
    profile-aware (preseason only) and carries real backtest numbers; the
    wrapper fills in only where `model_skill` is ABSENT, and normalises the
    existing one by adding `status: "measured"` so both shapes agree.
  - **Keep the unmeasured note SMALL.** It lands on every projection row on
    every sport, and `#374` records `extraHitterProps` being 68% of the MLB
    live-lens payload. Prose belongs in the module docstring, not in 2,000
    rows. Status + verdict + nulls only.
- Falsification tests: NFL's measured note must survive byte-identical apart
  from the added `status`; a row with no projection must not gain one; the
  block must not grow the payload by more than a few keys.
- Blocked by: none. The six measurements are NOT blocked by this — they are
  blocked by production data access.

### projection-degeneracy-detector — CLOSED-VERIFIED 2026-08-14 — opened 2026-08-14 — session: nfl-day-of-game

**OUTCOME — the lane's stated testable outcome, met.** A synthetic constant
slate is flagged with sport, market and value; a varying slate is not; and the
check runs on all seven producers without touching any of them.

Shipped `2e4e2544`. **DEPLOYED AND VERIFIED ON BOTH SERVICES** — web
`03:09:33Z`, refresh-worker `14:22:32Z` on 2026-08-14. (This line previously
read "NOT DEPLOYED", which was true when the lane closed and stale within
hours; see the `deploys.md` row for the measurement and for why the worker
half was held overnight through an OOM incident.)

    real failure shape (16 games x 3 markets, the 2026-08-13 constants)
      -> 2 groups flagged, games=16 correctly counted despite 32 alt-line rows
    22 tests, falsification cases outnumbering positive ones

- Design held exactly as recorded at open: wrapper over
  `_attach_projections_by_sport`, 13 return sites and 4 call sites untouched,
  games counted not rows, `projected_raw` preferred, threshold >= 4 games.
- `.current-lane` was claimed BRIEFLY and RESTORED to `anon-allocation-site`.
  The pre-open check that said the marker was unnecessary was correct WHEN
  TAKEN and became false the moment this lane claimed the file — a guard's
  input changes when you change the guard's configuration. Re-run such checks
  after opening a lane, not before.
- **`#425` IS ONLY HALF CLOSED, and the lane says so rather than the ticket
  quietly aging:** gap 2 (degeneracy detection) is done; gap 1 (skill
  annotation on six builders) is untouched and needs six measured backtests,
  which is modelling work and not plumbing. `#425` stays OPEN for it.
- Pre-existing, NOT caused here, NOT fixed here:
  `tests/test_layer2_projection_carry.py` has **4 failures**, verified
  identical with this change stashed. Unowned.
- Files released: `syndicate/features/shared/board_enrichment.py`,
  `tests/test_projection_degeneracy.py`.

### projection-degeneracy-detector — CLOSED-VERIFIED — superseded header, kept for the file/line map
- Goal: `#425`. A projection that has collapsed to ONE value across a slate is
  detected and reported for **every** sport, not just the one where a human
  happened to notice. Testable outcome: a synthetic constant slate is flagged
  with sport, market and value; a varying slate is not; and the check runs on
  all seven producers without touching any of them.
- Files (exclusive to this lane):
  - `syndicate/features/shared/board_enrichment.py` — the wrapper + detector.
  - `tests/test_projection_degeneracy.py` (new).
- **`.current-lane` deliberately NOT claimed.** It is one file shared by every
  session and `anon-allocation-site` holds it right now; taking it would break
  that session's own-lane exemption. Verified against the real hook that both
  my files return exit 0 without it, so claiming it would buy nothing and cost
  someone else. Re-check if a file added here IS claimed by an open lane.
- **SCOPE: `#425` has TWO gaps and this lane fixes ONE.** Stated so the ticket
  is not closed on half the work:
  1. **No degeneracy check** — IN SCOPE. A model with real historical skill can
     still emit a constant TODAY because its input went missing, and a
     backtested skill note cannot catch that. It is what actually happened on
     2026-08-13, and nothing reported it.
  2. **No skill annotation on six builders** — OUT OF SCOPE. Needs a measured
     backtest per model (`#367` did NFL's: corr −0.047 over 146 games). Six
     backtests is not a plumbing change, and inventing skill numbers to fill
     the field would be worse than the gap. Stays open on `#425`.
- Design, recorded before implementing:
  - `attach_projections` has **13 return sites across 7 sports**. Adding the
    check at each is the exact mistake `#334` records. Instead the per-sport
    body becomes `_attach_projections_by_sport` and `attach_projections`
    becomes a thin wrapper running the detector over the GRID afterwards — one
    place, all sports, all 13 paths, **zero call sites touched** (4 callers:
    `intelligence.py:2208`, `book_grid_artifact.py:221`,
    `layer2_shortlist.py:176`, and one internal).
  - Group by `(kind, market, segment)`; count distinct **GAMES**, not rows —
    alt lines put many rows on one game and a row-based count would inflate
    into false positives. Unit key is `event_id`, falling back to
    `(home_team, away_team)`, plus `player_name` for props.
  - Compare `projected_raw` where present, else `projected`. Raw is the model
    output before calibration; calibration mapping distinct inputs onto one
    output is a different bug.
- Threshold and its justification: flag only when distinct values == 1 across
  **>= 4 distinct games**. Two- or three-game slates can tie by coincidence;
  four independent games agreeing to full float precision cannot happen to a
  working model. Deliberately conservative — a false positive BLANKS a real
  projection.
- Falsification tests, which matter more than the positive ones: a varying
  slate must NOT flag; a 3-game constant slate must NOT flag (below threshold);
  a slate with many alt-line ROWS but few GAMES must NOT flag; a sport with no
  projections must NOT flag.
- Blocked by: none.

### anon-allocation-site — OPEN — opened 2026-08-14 — session: memory-guard
- **NAMED 2026-08-14 04:1xZ — `json.loads` (`decoder.py:353`), 491.3MB across
  7,172,382 LIVE OBJECTS. AND THE WORKER IS OOM-KILLING.**
  - Production OOM kills confirmed in the Render EVENTS api (not the logs):
    `server_failed / oomKilled / memoryLimit 4G` at **03:20:11, 03:39:57,
    03:46:47, 04:04:27** — same instance `-wc6hd`, `evicted: false`. Four in
    one hour.
  - The single supervisor reading that caught it, `anon` 2490.9MB:
    ```
    491.3MB  n=7,172,382  decoder.py:353            <- json.JSONDecoder
     32.2MB  n=  214,094  importlib._bootstrap:241
     13.1MB  n=   82,408  copy.py:231               <- deepcopy
      8.1MB  n=   37,374  intelligence.py:2342
      1.5MB  n=   56,366  odds_book_quotes.py:1215
    ```
    `json.loads` output is 15x the next contributor. `copy.py` (82k objects)
    is the second theme.
  - **WHAT THIS DOES NOT ESTABLISH, and it matters:** tracemalloc names where
    memory is ALLOCATED, not what HOLDS it — and retention is the bug. Traced
    covers **23.7%** of `anon` (589.8 of 2490.9MB), so ~1900MB remains outside
    its view at `nframe=1`. 491MB is the largest VISIBLE allocator, not proven
    the largest.
  - **5 of 6 readings were CHILD processes** (`anon` ~70MB, top site pure
    import machinery). Only 03:07:40 caught pid 39. **The emitter does not log
    a pid**, which is the same defect that wasted time on
    `LIVE_ODDS_WORKER_MEMORY` earlier tonight — reproduced by me. Add the pid.
  - **NEXT: raise `nframe` 1 -> 3.** At one frame the site is `decoder.py:353`,
    which is Python's own json module and tells us nothing about WHICH read
    retains. Three frames gives the caller — the difference between "JSON
    parsing" and "this artifact read". That is the fix-enabling measurement.
  - Consistent with everything else: `#423` already showed the growth is NOT
    arena fragmentation (arenas plateau ~393MB while `anon` climbs), i.e. live
    retention. 7.17M live objects from parsed artifacts is exactly that shape.
  - **Timing caveat I cannot clear:** the first OOM (03:20:11) is 38 min after
    my tracemalloc deploy (02:41:39). `nframe=1` keeps a traceback per live
    allocation and the lane recorded that hazard before shipping. The events
    window only reaches 30 events so earlier kills are not visible. The leak
    itself was confirmed at 00:04 — hours before the deploy — so the growth is
    not mine, but I cannot prove the instrument is not accelerating it.
    Rollback to `75b8aae6` removes it if the kills need stopping first.
- Goal: name the allocation site holding refresh-worker's **~1700MB of
  non-arena anonymous memory**, with evidence. Testable outcome: a named
  call site (file + function) accounting for >50% of the growth across one
  evening window, or a measured demonstration that the growth is invisible to
  allocation tracing — which is itself a result.
- **Successor to `refresh-worker-anon-leak`, not a parallel lane.** That lane
  eliminated the allocator branch (see its 02:18Z entry: coverage 11-24%,
  `system_current` plateaus at ~393MB while `anon` climbs). Its remaining
  question is exactly this lane's goal. **Do not run both** — the parent stays
  open only as the diagnostic record and its eliminations; new work happens
  here.
- Files (claimed by this lane):
  - `syndicate/features/shared/memory_observability.py` — tracing helpers,
    alongside the existing `malloc_trim` / `mallopt` / `malloc_info` bindings.
  - `scripts/run_refresh_worker.py` — wiring, on the existing stage emitter.
  - `tests/test_memory_observability.py`, `tests/test_refresh_worker.py`.
  - No OPEN lane claims any of these (checked 2026-08-14 02:2xZ).
- Hypothesis: the ~1700MB is live NumPy/Monte Carlo buffers retained by
  references, not freed memory. It is outside glibc's arenas because large
  array allocations take their own path.
- **FALSIFICATION TEST, AND IT MUST RUN FIRST.** `tracemalloc` only sees
  allocations made through **Python's** allocator (`PyMem_*`/`PyObject_*`).
  If NumPy's large buffers bypass that, tracemalloc will report a total far
  below the ~1700MB and the tool is blind here exactly as the gc census was
  (measured: 143KB reported of 546MB resident). **Before instrumenting the
  worker, prove the tool can see the memory**: compare
  `tracemalloc.get_traced_memory()[0]` against cgroup `anon` in one reading.
  Traced << anon means STOP — a different instrument is needed, and this lane
  must not spend a deploy learning that in production.
- **HAZARD — the tool can cause the failure it is measuring.** `tracemalloc`
  stores a traceback per live allocation; on a process that reaches its 4GB
  ceiling hourly that overhead is not free. Mitigations, in order: `nframe=1`,
  enable for a bounded window rather than permanently, and default OFF behind
  an env flag. `#241` is on record as a worker whose periodic work caused a
  production restart loop.
- **HAZARD — every arena reading with `arena_coverage_pct` below 50% is
  `arena_not_representative` BY DESIGN.** Do not read those as a new finding;
  that guard was added 2026-08-14 01:48Z precisely because the unguarded
  verdict misreported four times.
- Verification: a named site with a byte figure, reproduced across two
  windows; or the falsification above, recorded as "tracemalloc cannot see
  it" with the traced-vs-anon numbers that show it.
- Deploy exposure: refresh-worker `.py` only. No `render.yaml`. Its own
  `/preflight`; re-read the live SHA in the same step that deploys (it moved
  five times on 08-13 and a stale one nearly shipped a rollback).
- **FALSIFICATION TEST RUN 2026-08-14 02:3xZ — PASSED. The lane proceeds.**
  Local, deploy-free (`C:	mp	raced_vs_real.py`), Python 3.11.9 / numpy
  1.26.4, `tracemalloc.start(1)`:
  ```
  allocation              RSS       traced    seen
  numpy float64 random  +400.1MB   +400.0MB   100.0%
  python bytes          +400.1MB   +400.0MB   100.0%
  numpy float64 zeros     +0.0MB   +400.0MB   n/a
  pandas DataFrame        +0.1MB   +400.0MB   n/a
  python list of ints   +818.7MB   +230.2MB    28.1%
  ```
  - **NumPy buffers ARE fully traced.** That was the open question and the
    reason to check first. `tracemalloc` will NOT be blind the way the gc
    census was (143KB reported of 546MB resident) or the arena reading was
    (11-24% coverage). Two instruments failed this lane; this one fails
    differently or not at all.
- **HOW TO READ traced-vs-anon IN PRODUCTION. Both directions have benign
  explanations and neither is automatically a defect:**
  - **traced > RSS is EXPECTED and benign.** `np.zeros` and a zero-filled
    DataFrame allocate lazily — the OS returns copy-on-write zero pages and RSS
    does not move until something writes, while `tracemalloc` correctly reports
    the full requested size. Both showed +400MB traced against ~0 RSS. A gap in
    this direction means untouched pages, not an instrument fault.
    `random_sample` is the honest comparison because it writes every byte, and
    it came out at exactly 100%.
  - **traced < anon has TWO causes and they MUST be distinguished, not
    assumed.** (a) object-boxing under `nframe=1` — the list-of-ints row grew
    RSS 818.7MB while traced showed 230.2MB, because six million boxed ints are
    spread across allocations one frame does not fully attribute; or (b)
    genuine blindness. Check (a) first by re-reading with a larger `nframe` on
    a bounded window before concluding (b). Concluding blindness from a shortfall
    that is really object overhead would retire a working instrument.
- Blocked by: nothing. The falsification test needs no deploy.


### nfl-degenerate-writer — CLOSED-VERIFIED 2026-08-13 — opened 2026-08-13 — session: nfl-day-of-game

**OUTCOME — the lane's own testable outcome, met exactly as written.**
It said: *"with the pbp absent, the generator exits non-zero having written
NOTHING, and the previously-good artifact is byte-identical afterwards."*

    no pbp   -> exit 1, artifact sha DAAF137A85EE9984 UNCHANGED,
                message names the gitignored-directory cause
    control  -> same command, real pbp: exit 0, artifact rewritten,
                rating_source = prior_season_fallback

Run against the REAL program, not the guard functions. 105 tests pass.

- Shipped `c7cff28c`, refresh-worker, live `2026-08-14T01:35:38Z`.
  **No sim killed** — `state=finished` read before the POST.
- Post-deploy: `DegenerateProjectionRun` 0, `Traceback` 0, against a 20-row
  positive control. Worker healthy (rss 1607MB, headroom 1483MB).
- **The guard is INERT in production and that was measured BEFORE shipping**:
  the worker can see `pbp_2025.csv` (21:02:06Z `artifact_path=` on the mounted
  disk; artifact carries a real rating on 16/16 games). It is a trap for a
  failure mode not currently occurring. If it ever fires, root resolution moved.
- Design decision held: refuse only when EVERY projection is degenerate.
  Falsification cases both pass — a partial run and an empty schedule are
  allowed through.
- **Two existing tests had to change, and that is the finding.** Both ran
  `main()` with no play-by-play and asserted only that an artifact existed, so
  **the degenerate-write behaviour was pinned by passing tests.** Fixtures now
  supply synthetic prior-season plays; no assertion weakened, still hermetic.
- **CARRY-FORWARD, unowned:** `c7cff28c` and `111a5000` are BOTH inert until
  the next season-projection autorun, **~2026-08-14 16:00 CDT (21:00Z)**. One run
  verifies both. Expected: no `DegenerateProjectionRun`, and `MIA@WSH` /
  `LAR@KC` `rating_source` flips off `neutral_no_data`.
- Files released: `scripts/generate_smartsim2_nfl_projections.py`,
  `scripts/generate_smartsim2_nfl_preseason_projections.py`, their tests.

### nfl-degenerate-writer — CLOSED-VERIFIED — superseded header, kept for the file/line map
- Goal: a SmartSim2 NFL run with no play-by-play data cannot write a
  league-constant projection artifact over a healthy one. Testable outcome:
  with the pbp absent, the generator exits non-zero having written NOTHING,
  and the previously-good artifact is byte-identical afterwards.
- Why this exists: `98950c6d` made the READER immune to the degenerate file
  (drops both-sides-neutral rows, reads every root, newest wins). It does not
  stop the file being WRITTEN, and writing it OVERWRITES the healthy copy —
  which is how the board came to serve `margin 0.96 / total 44.38 /
  home_win 0.5267` on all 16 games across 4 dates.
- Root cause, already measured: `data/nfl_source/tracking/` is **gitignored**,
  so the nflverse pbp is on the mounted disk and absent from the repo
  checkout. A run whose `DATA_ROOT` resolves to the checkout loads ZERO plays,
  `team_rating` returns `(0.0, 0.0, "neutral_no_data")` for every club, and
  300 seeds are burned producing byte-identical rows.
- Files (exclusive to this lane):
  - `scripts/generate_smartsim2_nfl_projections.py` — the shared guards live
    here because the preseason script imports from it (`team_rating`,
    `load_pbp_plays`), so one implementation covers both generators.
  - `scripts/generate_smartsim2_nfl_preseason_projections.py` — wire the guard.
  - `tests/test_nfl_degenerate_writer_guard.py` (new).
- NOT touched: `syndicate/features/shared/nfl_game_projections.py`. The
  reader-side fix is already deployed and verified; re-opening it would put two
  changes on one observable.
- Design decision, recorded before implementing: refuse only when **EVERY**
  projection in the run is degenerate. A partial (e.g. two clubs whose
  abbreviations do not resolve) still yields a file carrying real information
  for the other games, and the deployed reader already drops the bad rows.
  Refusing on a partial would blank a mostly-good board — a worse failure than
  the one being fixed.
- Two guards, deliberately at different stages:
  1. PRECONDITION — zero plays loaded for both seasons is a hard data outage.
     Fail before simulating, so the failure names the missing path instead of
     surfacing as odd numbers 300 seeds later.
  2. PRE-WRITE — every projection degenerate means do not write AT ALL, so the
     last good artifact survives. Never truncate a healthy file with a bad one.
- Falsification test: the guard must NOT fire on a run where at least one club
  has real ratings, and must NOT fire on an empty schedule (no games is a
  different condition from no data, and conflating them would make an
  out-of-season run look like an outage).
- Blocked by: none.

### refresh-worker-anon-leak — OPEN — opened 2026-08-13 — session: memory-guard
- Goal: name what allocates ~300MB/hour of ANONYMOUS memory on refresh-worker,
  with evidence, so the board stops needing a restart every ~4 hours.
  Testable outcome: `anon` growth over a full evening window attributed to a
  named subsystem, or the growth shown to be bounded and the 1900MB floor
  re-derived against it.
- **This lane exists because fixing `#417` made it visible.** The old guard
  credited only `inactive_file`, so it refused for a bookkeeping reason and
  MASKED the real growth. Measured today on refresh-worker:
  ```
  #417's own window (pre-fix): anon FLAT, 1659 -> 1677.9, +18.9MB over 5.4h
  today, post-fix:             anon 1163 -> 2603MB in 4.5h  (~300MB/hour)
  ```
  Same service, same guard, opposite verdict about `anon`. That contrast is
  the whole finding.
- Files: none claimed yet. **Diagnostic only until the allocator is named** —
  `#327`'s lesson is that picking the next plausible candidate is how five
  eliminations got burned. No code lane until there is a measurement.
- Hypothesis (recorded before testing, per protocol): the growth is in a
  long-lived worker process rather than the transient sim/publish children,
  because a restart clears it completely and the children already exit.
- Falsification test: if per-process RSS shows the growth in short-lived
  children that come and go, the parent is exonerated and the leak is a
  retention/accumulation issue in whatever survives them.
- **Measurement RUNNING from a clean baseline.** Sampler `/c/tmp/leak_sampler.py`
  -> `/c/tmp/leak_series.jsonl`, every 3 min for ~2h, capturing `anon` /
  `unreclaimable` / `current` alongside `ALL_PROCESS_MEMORY` per-process RSS.
  Started 23:0xZ against the 22:59:14Z restart (anon 980.6MB).
  **Starting it was urgent: the restarts at 14:56, 18:05 and 22:59 each cleared
  the leak AND destroyed the evidence window.** This is the first clean one
  that has been recorded rather than spent.
- Related: `#327 RESIDUAL` (493-878MB unattributed allocator, five causes
  eliminated, leading lead never measured in bytes). Probably the same animal;
  do not assume so — `#327`'s eliminations were against a different symptom.
- Expected recurrence: on the measured trajectory the board should re-freeze
  ~4-5h after the 22:59 restart. **That prediction is itself a test** — if it
  does not recur, the growth is not linear and the model is wrong.
- **EXONERATED 2026-08-13 23:1x — `_BOOK_QUOTES_RSS_PER_FILE_BYTE = 6.3` is
  CORRECT. The cache budget is not blind.** Hypothesis was that the 500MB
  budget projects `file_bytes * 6.3` without ever measuring residency, so an
  understated coefficient would let the cache hold far more than it believes.
  Measured against real production shards via the real `read_book_quotes`,
  RSS before/after with the cache cleared between:
  ```
  shard        file_MB     rows   real_RSS_MB   REAL x   projected_MB   real/proj
  2026-07-29      15.1   39,370          95.6     6.33           95.2       1.00
  2026-07-22      14.3   37,139          87.3     6.11           90.0       0.97
  2026-08-01      13.7   35,591          82.5     6.04           86.0       0.96
  2026-08-09     207.4  478,782        1221.8     5.89         1306.4       0.94
  ```
  True multiplier 5.89-6.33 against a declared 6.3, slightly CONSERVATIVE at
  scale. Stop re-investigating this. The adjacent traps are handled too:
  `book_quotes_read_affordable` deliberately uses LOGICAL (uncompressed) bytes,
  with the 38.7x compression ratio measured on that same shard.
- **BUT the measurement pointed somewhere better, and the code says it out
  loud.** `odds_book_quotes.py:578-582`: *"freeing an entry does NOT return
  memory to the OS. It lets the next read REUSE those arenas instead of growing
  new ones, so the retained set plateaus at roughly one shard rather than two.
  The win is the plateau, not a reclaim."* And `_evict_book_quotes_over_budget`
  is `while len(_BOOK_QUOTES_CACHE) > 1` — the last entry is never evicted, by
  design. So one 207MB shard means ~1.2GB resident, held, and **2.4x the entire
  500MB budget in a single entry.**
- **HYPOTHESIS 2 (current, not yet confirmed): glibc arena retention across a
  multi-date sweep, in a process that never trims.**
  - refresh-worker does a multi-date sweep, so it loads shard after shard.
  - Each freed shard leaves arenas held, by the design above.
  - `malloc_trim` machinery EXISTS (`memory_observability.py`, ~250 lines,
    with the fragmentation reasoning written out) and `pipeline/
    intelligence_state.py:3201` uses it on the board-build path.
  - **`scripts/run_refresh_worker.py` — pid 39, the process that accumulates —
    never trims.** That asymmetry is the lead.
  - Fits every observation: gradual growth, growth localised to the supervisor,
    restart as the only cure.
- **DISCRIMINATOR, and do not skip it.** The running sampler distinguishes the
  two mechanisms: **stepwise** jumps at shard loads = retention/fragmentation;
  a **smooth ramp** = something else accumulating per-cycle. `#327` burned five
  eliminations by picking the next plausible candidate — do not add a
  `malloc_trim` call before the series says which shape it is.
- Instrument note: a case-SENSITIVE `grep malloc_trim` returned nothing outside
  `memory_observability.py` and read as "nothing calls it". The real emitter is
  `MALLOC_TRIM_FAILED`, uppercase. Search case-insensitively before concluding
  a mechanism is unused.
- pid 39 identified: `python scripts/run_refresh_worker.py`, ppid 1 — the
  supervisor. Children are all transient and small (140 / 120 / 95 / 87 / 47MB
  at 23:08). **Falsification test for hypothesis 1 REJECTED: the growth is not
  in short-lived children.**
- CONFOUND, self-inflicted and recorded: `_BOOK_QUOTES_INDEX_CACHE` (mine,
  `#414`) shipped at 22:59 and lives in pid 39. Tonight's window is the first
  containing it. The HISTORICAL leak is clean — 1163 -> 2603MB was measured
  18:05-22:48 on `03073270`, which predates the index — but current-rate
  numbers must separate the two before attributing anything.
- **MEASUREMENT DESIGN CORRECTED 23:19Z — v2's slope was an artifact and is
  RETRACTED. Do not quote +2418 MB/hour.**
  - v2 sampled the newest reading every 3 min. That series oscillates rather
    than ramps:
    ```
    anon   1332.7 -> 1599.1 -> 1517.4 -> 1356.2 -> 1819.1
    pid39  1073.9 -> 1147.7 -> 1214.4 -> 2005.6 -> 1488.5   (+791 then -517)
    ```
    An endpoint slope over that reads **+2418 MB/hour** against a historical
    ~300 — 8x, and purely a function of which spikes the samples landed on.
  - **Why: a single log query window already contains a huge spread.** Measured
    directly: **73 CONTAINER_MEMORY readings in 1.7 minutes, anon min 1670.0 /
    p50 1749.4 / max 1924.8 — a 254.8MB range.** v2 recorded ONE value out of
    that band per sample. The transient allocation of sims, board builds and
    shard loads completely buries a ~300MB/hour trend.
  - **The right metric was already in `.syndicate` memory: THE FLOOR IS THE
    RATCHET.** A leak raises the trough between cycles; peaks say nothing.
    v3 (`C:	mp\leak_sampler3.py` -> `C:	mp\leak_floor.jsonl`) records
    min/p50/max across every reading in each window, every 5 min. **Read the
    running minimum of the per-window mins**, not the point series.
  - Current floor for reference: **anon min 1670.0MB at 23:19Z** (restart
    baseline was 980.6MB at 22:59Z).
  - Caveat on v3, stated so it is not over-read: 100 log lines span only ~1.7
    min on this service, so each window's min is a *spot* floor, not a
    whole-cycle trough. The running minimum across many windows is what
    approximates the true floor — a single window's min can still sit above it.
- **CHECKPOINT 2026-08-13 23:3xZ — measurement running, NOT yet conclusive.**
  - Floor sampler v3 live (`C:	mp\leak_sampler3.py` -> `C:	mp\leak_floor.jsonl`),
    5-min windows, min/p50/max per window. **Read the RUNNING MINIMUM of the
    per-window mins**, never a point sample — v2's point series produced a
    retracted +2418 MB/hour.
  - Reference points: restart baseline `anon` **980.6MB @ 22:59Z**; floor
    **1670.0MB @ 23:19Z**; guard floor is 1900MB.
  - **The two obvious fixes are already done and already measured.** Do not
    propose adding a flush: `malloc_trim` returned 1109.6MB/24 calls/46min and
    only halved the ratchet, and `configure_malloc_arenas(2)` runs at
    `run_refresh_worker.py:3156`. At guard time trim returns 0.0–2.9MB, so the
    residual is **live objects or fragmentation**, not free-but-unreturned.
  - **NEXT ACTION for whoever picks this up:** read the floor series. Climbing
    toward 1900 with the arena cap already live implicates **live retention**
    (candidate 1) over fragmentation (candidate 2), because the cap was the
    probe for (2). A heap census cannot settle it — `gc.get_objects()` never
    enumerates `str`/`bytes`/`ndarray`, which is most of this workload — so the
    next instrument must differ in KIND: `tracemalloc` on allocation sites, or
    arena-level accounting.
  - **Standing prediction as a test:** board re-freezes ~03:00–04:00Z. If it
    does not, the growth is not linear and the model is wrong.
  - Eliminated tonight, do not redo: cache coefficient (measured 5.89–6.33 vs
    6.3); one-huge-shard (today's MLB shard is 0.1MB); "the worker never
    flushes" (it caps arenas).
- **CORRECTION 2026-08-13 23:33Z — THE PREDICTION IS FALSIFIED AND THE LEAK
  CLAIM IS NOT ESTABLISHED. Read this before acting on anything above.**
  - **Predicted re-freeze at ~4-5h. Aborts resumed at 34 minutes** (restart
    22:59:14Z, `MEMORY_GUARD_ABORT` newest 23:33:29Z). The linear-growth model
    is wrong.
  - **But the REGIME is different, and that matters more than the timing.**
    20:39-22:59 was 300 consecutive aborts with ZERO builds. Now it is
    **intermittent**: 8 `LAYER2_SHORTLIST` builds and 4 aborts since the
    restart. The board works, just not every cycle.
  - **The floor series says why.** `anon` swings ~1650 <-> 3200MB within
    minutes:
    ```
    window    floor      p50      max
    23:19    1670.0   1715.3   1877.9
    23:24    1652.2   2176.0   3203.7
    23:29    1762.8   2518.4   3167.7
    ```
    The guard needs `anon < 2196` to pass (1900 available of 4096). Whether a
    cycle builds therefore depends on **where in that swing the guard samples**.
  - **SO THE ~300MB/hour LEAK IS RETRACTED AS A MEASUREMENT.** `anon 1163 ->
    2603 over 4.5h` came from **two point samples** — the exact method retracted
    hours earlier for the v2 sampler. Against a quantity that oscillates 1550MB
    within minutes, two points cannot distinguish a ratchet from two different
    phases of the same swing. **Do not cite the 300MB/hour figure.**
  - What the floor actually shows so far: 980.6 (restart) -> ~1650 within 20
    min (warm-up) -> **1670 / 1652 / 1763 over the next 10 min — roughly
    FLAT.** No ratchet visible yet.
  - **Caveat on the caveat, stated so it is not over-read the other way:**
    three windows over 10 minutes cannot distinguish a flat floor from a slowly
    rising one either. This retracts the leak as *established*, it does not
    establish its absence. Hours of floor series settle it; the sampler runs.
  - **REFRAME, and it is `#417`'s lesson one level up.** If this is a swing
    rather than a ratchet, the defect is not an allocator to find — it is that
    **a point-sampled guard against a 1550MB-swinging quantity gives an
    unstable verdict.** `#417` fixed *which* quantity is read; it did not make
    *one reading* of that quantity sufficient. A trough-or-median guard, or
    hysteresis, would be the shape of the fix.
  - `SLOW_SEGMENT_PROFILE` / `SLOW_ENRICH_PROFILE`: **0 post-restart.**
    Consistent with the `#414` index working AND with no slow game having run.
    Proves nothing yet — see the silence caveat above.
- **THE EXISTING HEAP CENSUS CANNOT SOLVE THIS, and that is now MEASURED
  rather than argued. Do not reach for it.**
  - `LIVE_ODDS_WORKER_MEMORY` (with `largest_gc_object`) looked like the better
    instrument. It is not, for two independent reasons:
  - **(a) It is not on the process that matters.** `run_refresh_worker.py` —
    pid 39, the supervisor — emits **no heap census at all**. The emitter lives
    in `run_live_odds_refresh_worker.py` and `refresh_odds_sources.py`; the
    latter DOES run on refresh-worker, but as a ~95MB CHILD (observed as pid
    244), not the accumulating parent.
  - **(b) It is structurally blind to this workload.** The implementation is
    `gc.get_objects()` + `sys.getsizeof()`
    (`scripts/refresh_odds_sources.py:222`). `gc.get_objects()` never
    enumerates `str`/`bytes`/`ndarray` (untracked on 3.11 — the fact
    `memory_observability.py` already records), and `sys.getsizeof` is
    SHALLOW, so on a DataFrame it returns the wrapper and not the backing
    arrays.
  - **The live proof, 2026-08-13 23:44Z on live-odds-worker:** it reported
    `largest_gc_object = {type: DataFrame, size_bytes: 143262}` — **143KB — on
    a process at 546MB RSS.** The census found **0.03%** of the memory and
    called it the largest object. `#285` had already concluded the census
    cannot separate the two hypotheses; that is exactly WHY it added
    `malloc_trim` as the discriminator.
  - **Consequence for this lane:** the remaining candidates are (1) live
    `str`/`bytes`/`ndarray` retention and (2) fragmentation, and **no
    gc-based census can distinguish them.** A real instrument must differ in
    KIND — `tracemalloc` snapshots at allocation sites, or arena-level
    accounting.
  - **Do NOT build that yet.** The leak is currently RETRACTED as
    unestablished (see the 23:33Z correction above), and building a
    `tracemalloc` harness for what may be an oscillation rather than a ratchet
    would repeat tonight's mistake at higher cost. It is also a code change to
    a shared worker, so it wants its own lane and `/preflight`. **Read the
    floor series first.**
- **RESOLVED 2026-08-14 00:06Z — THE LEAK IS REAL. This supersedes the 23:33Z
  retraction, which was over-cautious. Third and final revision of this claim.**
  - The floor series spoke once it had ~45 minutes:
    ```
    window     FLOOR      p50      max
    23:19     1670.0   1715.3   1877.9
    23:24     1652.2   2176.0   3203.7
    23:29     1762.8   2518.4   3167.7
    23:34     2329.4   2410.5   2417.0
    23:44     2025.0   2025.0   2367.5
    23:54     2491.7   2492.7   2493.7
    00:04     2588.9   2613.3   2651.2
    ```
  - **The decisive fact is not the slope, it is that the LATEST TROUGH (2588.9)
    is above the FIRST WINDOW'S PEAK (1877.9).** A trough that clears an earlier
    peak is a ratchet and cannot be an oscillation. That is the comparison
    point-sampling could never make, and it is the one to reach for next time.
  - Floor rose **1670 -> 2589MB in 45 min (~+1200 MB/hour)** — roughly 4x the
    retracted 300MB/hour figure, which remains withdrawn as a *number* even
    though the *phenomenon* is confirmed.
  - **The oscillation collapsed as the floor rose**: spread was 1650<->3200
    early, now 2589<->2651 (~60MB). Less headroom to swing in. This is WHY the
    floor is readable now and was not at 23:33 — the instrument did not change,
    the system did.
  - **Board state matches exactly.** Guard needs `anon < 2196`; floor is 2589,
    so it is over threshold at every sample. `MEMORY_GUARD_ABORT` 25 post-
    restart, newest 00:06:31Z (seconds ago); `LAYER2_SHORTLIST` 12, last
    23:56:47Z. It built while the floor was under the line and stopped when the
    floor crossed it. **Board is freezing again at T+1.13h.**
  - Prediction accounting, kept honest: predicted 4-5h, aborts first appeared at
    34 min (which looked like falsification), sustained freeze at ~1.13h. **The
    linear model was wrong in both directions** — early aborts were the peaks
    crossing, the real onset was the floor crossing. Two different mechanisms
    with the same log line.
  - **`#417`'s guard is behaving CORRECTLY throughout.** It is refusing because
    `anon` genuinely exceeds the floor. Do not touch the guard; the defect is
    upstream of it.
- **NEXT ACTION unchanged in kind but now justified:** the leak is real, so a
  `tracemalloc`-class instrument is warranted where it was not two hours ago.
  The gc census still cannot help (measured: 143KB reported of 546MB resident).
  Scope it as its own lane with `/preflight` — it is a code change to a shared
  worker.
- Operational note: the board will need another restart to serve fresh data,
  and each restart destroys the evidence window. **Capture the floor series
  before restarting** — that is now a repeatable procedure, not a one-off.
- **INSTRUMENT PLAN (filed 2026-08-14 in THIS lane, deliberately not a new
  one).** A separate attribution lane would strand every elimination recorded
  above and push us to 5 OPEN against a cap of 3. Escalate cheapest-first:
  - **STEP 1 — `glibc malloc_info()`, near-zero cost.** Dumps per-arena
    totals: bytes in use vs bytes free-but-held. **This alone separates the two
    surviving candidates** — large free-within-arena means FRAGMENTATION; arenas
    mostly live means RETENTION. It is a `ctypes` call into libc, no dependency,
    no per-allocation bookkeeping. `memory_observability.py` already binds
    `mallopt`/`malloc_trim` the same way, so the pattern exists.
  - **STEP 2 — `/proc/self/smaps_rollup`**, also free: `Rss`/`Pss`/`Anonymous`
    for the process, to cross-check pid 39's share against the cgroup `anon`
    the guard reads. Answers "is this even pid 39's memory" without a census.
  - **STEP 3 — `tracemalloc`, ONLY if steps 1-2 say RETENTION.** It attributes
    live bytes to allocation sites, which is what we would then need.
  - **HAZARD, and it is why tracemalloc is step 3 and not step 1: it is NOT
    free on this container.** It stores a traceback per allocation; on a worker
    that already reaches its ceiling every ~1.1h, the instrument can push it
    over and change the thing it measures. `learnings.md` already records that
    worker periodic work is never free (`#241` caused a prod restart loop).
    If it is used: `nframe=1`, enabled for a bounded window, never permanently,
    and never during a slate the board depends on.
  - **Do not reach for the gc census at any step** — measured blind: 143KB
    reported of 546MB resident.
- **Prospective file claim when a step ships** (none held yet; diagnostic
  work needs no claim): `syndicate/features/shared/memory_observability.py`
  (where the libc bindings live) and `scripts/run_refresh_worker.py` (pid 39,
  the only process worth instrumenting). **Neither is claimed by any OPEN lane
  as of 2026-08-14 00:3xZ** — verified, not assumed.
- **Deploy exposure when it ships:** refresh-worker `.py` only, no
  `render.yaml`. But it is a code change to a shared worker under active
  memory pressure, so it takes its own `/preflight` and its own measurement
  window. Do not bundle it into an incident restart.
- **ANSWERED IN PART 2026-08-14 02:18Z — IT IS NOT ARENA FRAGMENTATION.**
  Ten guarded readings at `anon` ~2031MB, refresh-worker `75b8aae6`:
  ```
  01:57  sys=228.9  free%=64.3  cov%=14.1
  02:01  sys=382.6  free%=79.1  cov%=23.6
  02:08  sys=393.4  free%=54.0  cov%=11.0
  02:13  sys=393.4  free%=80.2  cov%=17.8
  02:15  sys=392.8  free%=80.2  cov%=18.3
  ```
  - **Arena coverage 11.0-24.4%.** glibc holds at most a quarter of the
    process's anonymous memory.
  - **`system_current` PLATEAUS at ~393MB** — three consecutive readings
    identical — **while `anon` keeps climbing.** The arena is bounded; the
    growth is entirely outside it. That is the discriminator, and it is
    stronger than the coverage percentage alone.
  - `mmapped` 0.7MB, `arenas` 2 (the `mallopt` cap confirmed applied). So it
    is not glibc's mmap path and not arena proliferation either.
  - **This explains `malloc_trim` returning 0.0-2.9MB at guard time** — not
    "too fragmented to return whole pages", simply nothing there to return.
  - **CLOSES the fragmentation branch.** Do not spend more time on allocator
    tuning, arena counts, or trim cadence.
- **NEXT STEP, now justified where it was not:** `tracemalloc` (or an
  allocation-site sampler) pointed at **array/buffer allocation**, not the
  gc-tracked heap — the census is measured blind here (143KB reported of 546MB
  resident). Leading candidate for the ~1700MB is NumPy/Monte Carlo buffers on
  their own path; **unmeasured, and naming it is the lane's remaining work.**
  Its own lane and `/preflight`: it is a code change to a shared worker, and
  `tracemalloc` stores a traceback per allocation on a process that reaches its
  ceiling hourly.
- **UNEXPLAINED, do not lose:** a board build ran **>8 min at `anon`
  1378-1934MB with ZERO aborts** and never landed (started 01:36:45, typical
  3.7min), with the guard passing and 260MB of headroom. Every other stall
  tonight was memory pressure; this one was not. The restart erased it. Catch
  the next occurrence before theorising.
- Blocked by: nothing. Measurement-bound, not idea-bound.

### nfl-day-of-game — CLOSED-VERIFIED 2026-08-13 — opened 2026-08-13 — session: nfl-day-of-game

**OUTCOME. All five stages exercised against the live 6-game preseason slate.
Four verified working, one shipped-but-not-yet-observable. Three deploys, all
measured. Closed on evidence, not on completion of the work list.**

    sims                  model SOUND; the "identical projections" was file
                          selection, not the model. 2 clubs mis-rated -- fixed,
                          effect NOT yet observable (see carry-forward).
    odds refresh          HEALTHY, was never broken. Do not re-investigate.
    sim proj -> odds      FIXED + VERIFIED. distinct projected_raw 1 -> 6;
                          board and cards agree 6/6 to three decimals.
    live lens             FIXED + VERIFIED via game state.
    game card updates     FIXED + VERIFIED. shared_is_live 0 -> 4,
                          startTime 0/16 -> 16/16.

- Shipped (ORIGIN SHAs — local `9bb2501a`/`3c3dfdfe`/`f1c6c540` will not
  resolve for anyone else): `e29b807f` web 18:54, `98950c6d` refresh-worker
  19:10, `111a5000` refresh-worker 19:13. Measurements in `deploys.md`.
- Priors from the opening entry, resolved: prior 1 (no sim join) **partly
  right** — the join existed but read the wrong file. Prior 2 (`#377`
  degenerate model) **REFUTED** — the model is fine. Prior 3 (`#389` artifact
  root) **not the cause here**, though the same root-resolution family is.
- **CARRY-FORWARD, unowned. Do not close these silently:**
  1. `111a5000`'s `LAR`/`WSH` alias fix is live but changes nothing until the
     next season-projection autorun, **due ~2026-08-14 16:00 CDT (21:00Z)**. Expect
     `MIA@WSH` / `LAR@KC` `rating_source` to flip off `neutral_no_data`.
  2. **The degenerate file is still WRITABLE.** `data/nfl_source/tracking/` is
     gitignored, so a generator run rooted at the repo checkout still produces
     league-constant projections. The reader is now immune; the writer is not.
     No ticket filed.
  3. MLB sim ledger never records completion (34/34 `running`), so no deploy
     gate can ask "did the MLB sim finish".
- Files released: all of `syndicate/features/nfl/**`, `blueprints/nfl.py`,
  `shared/nfl_game_projections.py`, `shared/game_chip_scoreboard.py`,
  `scripts/generate_smartsim2_nfl_projections.py`.

### nfl-day-of-game — CLOSED-VERIFIED — superseded header, kept for the file/line map
- Goal: the NFL day-of-game engine is proven, stage by stage, against
  tonight's 6-game preseason slate (2026-08-13). Testable outcome: for each
  of the five stages — sim run, odds refresh, sim-projection→odds mapping,
  live lens, game-card update — a PRODUCTION measurement that is either
  "works, here is the non-zero reading" or "broken here, this is the first
  stage that is zero". No stage may be closed on a local-checkout reading.
- **Opens as lane 4 against a stated cap of 3.** Recorded, not hidden;
  `state.md` notes the cap is policy with no enforcement and that four ran
  unchallenged on 08-13. Flagged to the user at open time.
- Files (LITERAL PATHS — see the note below; a glob here is not enforcement):
  - `syndicate/features/nfl/live_game_state.py`
  - `syndicate/features/nfl/preseason_cards.py`
  - `syndicate/features/shared/game_chip_scoreboard.py`
  - `tests/conftest.py`
  - `tests/test_nfl_live_game_state.py`
  - `tests/test_nfl_preseason_market_board_live_odds.py`
  - `tests/test_game_chip_scoreboard.py`
  - `tests/test_nfl_preseason_cards.py`
- **THIS BLOCK ORIGINALLY READ `syndicate/features/nfl/**`, AND THAT GUARDED
  NOTHING.** `lane-guard.py` compares literal paths, so a glob claims no file
  at all: every file above was edited with the lane reporting protection it
  was not providing. Found during `/preflight`, by running the ledger's own
  `awk '/^### /{h=$0} /<path>/{print h}'` check and getting NO header back for
  three of the four source files. No collision resulted — none of them is
  claimed by another OPEN lane — but the claim was false while it mattered.
  **Never write a glob in a Files block.** Sibling of the 08-13 entry on
  `lanes.md` being executable configuration rather than documentation: this is
  the same class, arriving through syntax rather than through deletion.
- NOT touched, deliberately — claimed by other OPEN lanes:
  `syndicate/features/shared/live_refresh_loop.py` (mlb-props-regen),
  `pipeline/intelligence_state.py` and
  `syndicate/features/shared/memory_observability.py`
  (memory-guard-reclaimable). If the NFL defect lands in one of these, STOP
  and surface the collision instead of editing across the lane boundary.
- Hypothesis (recorded before testing): the day-of-game path is **not** end
  to end for NFL, and the break is upstream of the board. Three specific
  priors from the ledger, each to be confirmed or exonerated by measurement:
  1. `attach_projections` wires mlb/wnba/soccer only, and `board_enrichment`
     recorded that production holds no NFL predictions/edges of any kind
     (`#329` notes) — so the sim→odds mapping stage may have no join at all.
  2. `#377`: NFL `margin_mean` is a CONSTANT 0.96 and `total_mean` a constant
     38.76 across every game. If a sim runs tonight and the projections are
     still one value per market family, the sim executed and produced nothing
     game-specific — a pass on "did it run" and a fail on "is it a
     projection".
  3. `#389` follow-up: NFL projections were written to the ephemeral checkout
     (`/opt/render/project/src/data/...`) while the guard read
     `/opt/render/project/data/...`; the `nfl_artifact_output_root()` fix is
     recorded as AWAITING FIRST RUN. Tonight is the first live slate to test
     whether a completed sim's artifact is now visible to the reader.
- Falsification test: for prior 1 — a non-empty projection join on an NFL
  card tonight exonerates it. For prior 2 — two or more distinct `projected`
  values across tonight's 6 games exonerates it; one value confirms it. For
  prior 3 — `SEASON_PROJECTION_ARTIFACT_MISSING` absent after a launch, with
  the artifact readable at the guard's root, exonerates it.
- Hazards carried from `learnings.md` into this lane:
  - **A null agrees with everything.** Every zero recorded here needs a
    positive control — a case that makes the same instrument read non-zero —
    before it is written down as a finding. NFL is week-scoped, so an empty
    board is the EXPECTED reading for a wrong week and must never be reported
    as a broken stage.
  - **Preseason and regular season are separate week domains** and separate
    routes (`/nfl/preseason/*` vs `/nfl/*`). Tonight is preseason; reading
    the regular-season route would produce a legitimate empty and look like a
    defect.
  - Local `data/nfl_source/**` is a lossy mirror. Production first, always.
- Verification: a stage-by-stage table written into this lane and into
  `state.md`, each row carrying its measurement and its timestamp, with the
  first zero stage named explicitly if there is one.
- Blocked by: none.

#### MEASURED, 2026-08-13 slate (6 games, kickoffs 18:00–20:00 CDT)

| stage | verdict | measurement |
|---|---|---|
| sim run | RAN, output degenerate | 2 runs (20:59:41Z season, 21:00:11Z preseason); 16 distinct per-game `generated_at` 21:00:18→21:02:06 |
| odds refresh | **WORKS** | 8,537 shard rows, 11 books; DET@CIN 12→132 rows through kickoff, quotes <1.5 min fresh across 12 polls |
| sim→odds mapping | join works, input degenerate | 39/68 rows carry a projection; suppression honest |
| live lens | FAILS | `ll_live_rows = 0` on all 12 polls |
| game cards | FAILS | `cards live=0 final=0` on all 12 polls |
| board game state | **FAILS — root cause** | `by_state {pregame:6, live:0, final:0}` on all 12 polls, 35 min, with 3 games live |

**ROOT CAUSE — one join, not five surfaces.** `_NFLDataProvider.games()`
(`home.py:5704`) hands `build_game_chips` the week-scoped projection cards,
which carry no game state at all: `status` is the plain string
"Preseason Week 1", no `live_state`, no score, no clock, no kickoff time. So
`game_chip_scoreboard._game_flags` returns `(False, False)` for every NFL game
and `build_game_chip` stamps `pregame` by construction. Live lens, cards,
`by_state` and the Layer 1 game-state join all inherit that one value.

**FIXED** — `syndicate/features/nfl/live_game_state.py` stamps `live_state`
onto the cards. Chosen because both `publication_adapter._shared_game_state`
and `game_chip_scoreboard._game_flags` ALREADY read `live_state`; no NFL
builder ever set one. `#334`'s lesson: the fix goes inside the shared shape,
zero call sites touched. Live integration against the real slate:
`matched 16/16, live 2`, `by_state {live:2, pregame:14}`, real scores
(GB@PIT 3-0), real tokens (`Q1 3:42`), and a real kickoff time on all 16 —
the cards had none before.

#### CORRECTIONS MADE IN THIS LANE

- **RETRACTED: "odds refresh stops at kickoff."** It does not. I read a
  13-minute pregame→live transition lag (loop flipped `phase=live` at
  23:13:24Z, 13 min after the 23:00Z kickoff) and reported a stoppage. The
  odds path is the healthiest stage of the five. Exactly the "a null agrees
  with everything" trap this lane's own hazard list named.
- **RETRACTED: "the week label is wrong."** `PRESEASON_WEEK_LABELS` maps
  internal week 2 → "Preseason Week 1" **deliberately** — internal week 1 is
  Hall of Fame Weekend, so tonight IS public Preseason Week 1. Caught by
  reading the code before shipping a "fix". Residual real nit, not fixed:
  `requested_date` formats the RAW index as `f"Preseason Week {selected_week}"`,
  so it says "Week 2" beside `date`'s "Week 1". Cosmetic, left alone.
- **`#377` CONFIRMED and EXTENDED, and the join EXONERATED.** Not just
  `margin_mean`: `home_win_rate` 0.5267, `margin_mean` 0.96, `total_mean`
  44.38 are each ONE value across 16 games and 4 dates (08-13/14/15/16). The
  16 distinct per-game `generated_at` stamps prove the sim ran per game and
  produced identical output — so this is the MODEL, not the lookup.
  `model_prob_over` varies (0.4393–0.5237) only because the LINES vary, which
  makes a degenerate model read as a working one on the board. Lead, not
  conclusion: the artifact carries
  `rating_source=...[neutral_no_data/neutral_no_data]` and `seeds_used=2`.
  **Unowned, needs its own lane.**
- **UNRESOLVED:** cards and Layer 1 disagree about the same 16 games (cards
  show per-game totals, e.g. DET@CIN 46.275; Layer 1 shows the constant
  44.38). Different root resolvers — `default_nfl_source_root()` vs
  `preferred_source_roots()`. Could not settle it: `smartsim2*` is not in
  `HOT_ARTIFACT_PATTERNS`, so ops export/stream both 403 and the production
  CSV is unreadable from here. Flagged, not guessed.

#### FOUND IN PASSING — cross-sport, unclaimed file

`game_chip_scoreboard._score_value(0)` returned **None**: it routed through
`_text`, which is `str(value or "")`, so an integer 0 became `""`. Every
scoreless team lost its score on the chip, in **every sport**. Found because
GB @ PIT rendered `away 3, home None` instead of 3-0. Fixed in `_score_value`
only — not in `_text`, whose other callers are labels and names where the
falsy-collapse is harmless. Pinned by 6 tests in `test_game_chip_scoreboard.py`,
including that the pregame 0-0 placeholder suppression still works.

#### TEST HYGIENE DEFECT I INTRODUCED, THEN FIXED

The game-state stamp made `build_preseason_cards_page_context` perform a live
ESPN call — measured: exactly 1 fetch, ~1.5s, per build. That made the suite
network-dependent, and `test_nfl_preseason_cards` began failing because it
builds 2026 preseason week 1 (Hall of Fame weekend) and ESPN correctly returns
`final` where the board used to hardcode `pregame` — a true reading of the
world and a flaky test. Blocked at the `_fetch_scoreboard` seam by an autouse
conftest fixture, so the index's own caching/keying still runs under test and
only the socket is removed. Positive control written and run: no sockets
opened, `_fetch_scoreboard` returns None under pytest.

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

### quote-join-enrich-cost — CLOSED 2026-08-14 — all three verification criteria MET
- Criteria as written, checked one by one: (1) evening slate MLB `tail_s` < 10s
  -> **7.17s**; (2) cause named in the lane BEFORE the change shipped -> the
  join scan, `19.86s per million rows walked`, R²=0.918; (3) before/after from
  the SAME instrument on comparable slates -> `SLOW_SEGMENT_PROFILE` 21-54s at
  18:07-18:11Z vs 7-8s at 00:11-00:18Z.
- Result: **21.5x fewer rows walked per call (216,135 -> 10,043), board-build
  21-54s -> 7-8s.** `join_s` is still ~100% of the cost, so the remaining lever
  is the residual ~10k rows/call — a NEW question, not this lane's.
- Only measurable because `SYNDICATE_SLOW_ROW_TOTAL_SECONDS`/
  `SYNDICATE_SLOW_ENRICH_TOTAL_SECONDS` were set to 1; at the 5s default a
  working index is indistinguishable from a broken instrument.

### quote-join-enrich-cost (detail below, kept for the file/line map) — session: memory-guard
- Goal: the MLB board-build's ~33s per slow game is attributed to a named
  cause inside `enrich_block` and then cut. Testable outcome: on a comparable
  evening slate, `SLOW_SEGMENT_PROFILE tail_s` for MLB drops below 10s with
  `rows_walked` down by at least an order of magnitude.
- **THE MEASUREMENT LANDED. This lane starts from data, not a hypothesis.**
  `sim-execution-observability` handed this on CLOSED-PENDING-MEASUREMENT,
  waiting for one evening build. It fired 2026-08-13 18:10Z on refresh-worker
  (`03073270`), twice:
  ```
  18:10:24 [home] SLOW_SEGMENT_PROFILE sport=mlb total_s=33.32 rows=2
     rows_s=0.00 tail_s=33.32 enrich_block=33.32 mlb_props_block=0.00
     row[0]=0.00 join:by_player=15,by_teams_fallthrough=5,calls=20,
     rows_walked=1718960
  18:10:58 [home] SLOW_SEGMENT_PROFILE sport=mlb total_s=34.28 rows=2
     rows_s=0.00 tail_s=34.28 enrich_block=34.27 record_rows_block=0.00
     join:by_player=17,by_teams_fallthrough=2,calls=19,rows_walked=1
  ```
  Reading it against that lane's own decision rule:
  - `tail_s` (33.32) **>>** `rows_s` (0.00) -> the cost is **post-loop**, and
    `enrich_block=33.32` names it. The row loop is **EXONERATED** — 0.00s in
    both samples.
  - This confirms the retraction already in `learnings.md`: `SLOW_ROW_PROFILE`'s
    "one pathological iteration takes 100-400s" was a span artifact. There is
    no pathological row.
  - `rows_walked=1718960` over `calls=20` — ~86k rows walked per call. The
    second sample walked **1** row for a near-identical total time, which is
    the single most interesting number here (see falsification test).
- Files (exclusive to this lane):
  - `syndicate/features/shared/odds_book_quotes.py` — the join and its
    counters. `_bump("rows_walked", len(rows))` at L1254; `_QUOTE_JOIN_STATS`
    is per-call, not per-row (documented L1250).
  - `syndicate/features/shared/quote_enrichment.py` — `enrich_candidate_rows`
    at L366, the entry point the enrich block calls.
  - `syndicate/blueprints/home.py` — `enrich_block` mark at L2872, profiler
    emit at L2926. Segment/profiler code only.
- NOT claimed, deliberately: `syndicate/features/intelligence.py`. It is the
  caller (L6362) and holds the `blueprints.home` imports, but this lane does
  not need to edit it, and `memory-guard-reclaimable` has a (never-exercised)
  L2563-constant-only claim on it. If a fix needs that file, resolve the claim
  first rather than editing across lanes.
- Collision check: CLEAR. Neither OPEN lane (`memory-guard-reclaimable`,
  `mlb-props-regen`) claims any of the three files above. The CLOSED
  `sim-execution-observability` lane claimed two of them; this lane is the
  continuation it handed on.
- Hypothesis: the ~33s is a linear scan in the quote join, taken on the
  `by_teams_fallthrough` path when the cheap `event_id` key misses.
- **Falsification test, and it must be run FIRST.** The two samples disagree
  with the hypothesis as stated: sample 1 walked **1,718,960** rows in 33.32s;
  sample 2 walked **1** row in 34.28s. **Near-identical time, six orders of
  magnitude apart in rows walked.** If `rows_walked` does not drive the time,
  the join scan is NOT the cause and the cost is elsewhere in
  `enrich_candidate_rows` — an I/O wait, a per-call artifact load, or a
  network call. Do not optimise the scan until this is resolved.
- **HAZARD — the two instruments agree EXACTLY and that is not corroboration.**
  `SLOW_SEGMENT_PROFILE total_s=33.32` and `SLOW_GAME_CANDIDATE elapsed_s=33.32`
  match to the hundredth in both samples. `learnings.md` ("An instrument's SPAN
  is not its NAME") records that this exact agreement was previously read as two
  independent measurements confirming each other when they were **the same
  quantity measured twice**. Prove they are not reading the same clock interval
  before citing either as independent evidence.
- **HAZARD — `QUOTE_JOIN_STATS` returns 0 hits as a standalone token.** The
  join counters are emitted *inside* the `SLOW_SEGMENT_PROFILE` line
  (`join:...`), so a search for the bare token is not evidence of anything.
  Do not read that zero as a missing instrument.
- Architectural finding, recorded not actioned: `syndicate/features/
  intelligence.py` imports **four** symbols from `syndicate/blueprints/home.py`
  (`_build_sport_overview` L47, `_build_prop_dashboard_row` L48,
  `_game_bet_candidates_from_game` L49, `_mlb_actual_payload_for_game` L6641).
  The worker's board build therefore executes a Flask **presentation
  blueprint**, which inverts the layering CLAUDE.md specifies. Concrete
  consequence already observed: the `[home]` prefix makes worker cost look like
  a web-route problem. Out of scope here; worth its own ticket.
- Verification: a comparable evening slate shows MLB `tail_s` < 10s, with the
  cause named in the lane before any change ships, and a before/after pair
  taken from the SAME instrument on comparable slates.
- Deploy exposure: refresh-worker `.py` only when it comes. No `render.yaml`.
  NOTE: refresh-worker currently carries an OPEN `#417` measurement due
  2026-08-14 13:00 — **do not deploy this lane's changes before that read
  lands**, or the two changes become unattributable.
- Blocked by: none for diagnosis. Deploy blocked until the `#417` read.
- **STATUS 2026-08-13 17:0x CDT — FIX WRITTEN, PUSHED (`9d730aec`), NOT
  DEPLOYED. `/preflight` FAILED; held until after the `#417` read.**
  - The join now indexes `event_id` / `player_name` / `(home,away)` to a
    candidate union instead of scanning the shard. **Measured at production
    shard size (82,500 rows): 85.43 -> 0.66 ms/call, 130x, identical result.**
    Per game: 1.71s -> 0.01s at 20 calls, 5.30s -> 0.04s at 62.
  - **Teams could be indexed safely and that was the load-bearing question.**
    `_row_teams_match` delegates to the alias maps, so a token index would
    silently drop matches ("chc" vs "chicago cubs" is the gap that left 0 of
    108 candidates priced on 2026-08-06). It reads ONLY `home_team`/
    `away_team`, so rows sharing a pair cannot disagree — grouping by pair
    runs the fuzzy matcher once per PAIR (~15) instead of once per ROW (~83k).
  - Equivalence PROVEN, not assumed, because this join's wrong answers are
    silent: 30+ query shapes asserted identical to the full scan, where the
    reference is the real old path (union forced to every row). The grid is
    also asserted to exercise `by_event`, `by_player`,
    `by_teams_fallthrough` AND `no_identity` — a differential test proves
    equality, not coverage — plus index-narrows and no-stale-index tests.
    105 passed / 30 subtests across every quote suite.
  - **The fix will silence its own instrument.** `SLOW_SEGMENT_PROFILE` is
    gated at 5s, so success means it stops emitting — and that zero is
    indistinguishable from a broken instrument or an empty slate. Read it only
    against a positive control (`LAYER2_SHORTLIST` still recurring) and the
    pre-fix baseline of 8 lines in ~4 minutes. Same emitter trap as `basis`,
    caught before the deploy this time rather than after.
  - Local absolute numbers run ~19x faster per call than production's ~1.6s;
    the RATIO is the transferable claim and is likely conservative, since the
    indexed path does not scale with shard size while the scan does.
  - Still unexplained and worth watching: the 18:07:20 sample at **10.53 s/M**
    against ~18-21 for the other seven, at the largest volume. That suggests
    an amortised per-call cost the index will not touch.

- **STATUS 2026-08-13 16:4x CDT — HYPOTHESIS CONFIRMED, NOT FALSIFIED. THE
  FALSIFICATION TEST ABOVE RESTED ON MY OWN TRUNCATION ARTIFACT. Read this
  before acting on anything earlier in this lane.**
  - **RETRACTED: "sample 2 walked 1 row in 34.28s".** That was never in the
    data. The log line is **216 characters** and the printout that produced it
    cut at **210**, turning `rows_walked=1633012` into `rows_walked=1`. The
    "six orders of magnitude apart for identical time" paradox — the entire
    stated reason to distrust the join-scan hypothesis — was an artifact of my
    own display code, not a property of the system.
  - **Eight samples, pulled untruncated 2026-08-13 16:4x from the already-
    deployed profiler.** No new deploy was needed to get them.
    ```
    time      total_s   rows_walked  calls  rows/call  s/call  s per 1M rows
    18:07:20    54.17     5,143,272     62     82,956   0.874         10.53
    18:07:59    38.39     2,073,900     25     82,956   1.536         18.51
    18:08:20    21.22     1,161,384     14     82,956   1.516         18.27
    18:08:44    24.11     1,327,296     16     82,956   1.507         18.16
    18:09:19    34.59     1,704,000     20     85,200   1.730         20.30
    18:09:50    31.72     1,718,960     20     85,948   1.586         18.45
    18:10:24    33.32     1,718,960     20     85,948   1.666         19.38
    18:10:58    34.28     1,633,012     19     85,948   1.804         20.99
    ```
  - **`rows_walked` per call is essentially CONSTANT: 82,956 – 85,948.** Every
    call walks the same ~83k rows. Linear fit of `total_s` on `rows_walked`,
    excluding the 5.1M sample: **19.86 s per million rows, intercept −1.07s,
    R² = 0.918.** Near-zero intercept and near-perfect proportionality — the
    time IS the scan. Hypothesis CONFIRMED.
  - **And it is sharper than the lane predicted.** The lane expected the cost
    on the `by_teams_fallthrough` path when the cheap `event_id` key misses.
    It is not: `by_player` resolves 15–17 of ~20 calls and those calls STILL
    walk ~83k rows. **The scan is unconditional** — a successful join costs the
    same as a failed one. Fixing the fallthrough would have changed nothing.
  - Cost model: ~83k rows/call × ~20s per million ≈ **1.6s per call**, and a
    game makes 14–62 calls, which reproduces the observed 21–54s.
  - One sample resists the model: 18:07:20 is **10.53** s/M against ~18–21 for
    the other seven, and it is the largest (5.1M rows, 62 calls). Cheaper per
    row at higher volume suggests an amortised per-call cost (shard load, cache
    warm). Recorded rather than explained away — it is the one point that would
    move the fix's expected payoff.
  - **Fix direction:** index the quote log by join key instead of scanning it
    per candidate. Not a micro-optimisation of the scan.
  - The `SLOW_ENRICH_PROFILE` deploy is still worth doing — it separates
    `join_s` from `post_s`/`score_s` definitively and gives `join_s_per_call`
    directly — but it is now CONFIRMATION of a known answer, not the discovery
    step. Do not let its absence block the fix.
- **STATUS 2026-08-13 16:2x CDT — INSTRUMENT WRITTEN, PUSHED, NOT DEPLOYED.**
  - `7ce27100` on `origin/main`: `SLOW_ENRICH_PROFILE` splits
    `enrich_candidate_rows` into `setup_s`/`join_s`/`post_s`/`score_s` plus
    `accounted_s`/`unattributed_s`. **Observability only, no behaviour change.**
    Gated at 5s (`SYNDICATE_SLOW_ENRICH_TOTAL_SECONDS`), one line per slow game.
  - Verified rather than assumed, four ways: **liveness** (forced slow join →
    emits, `join_s=0.51` of `total_s=0.54`); **accounting**
    (`accounted_s == total_s`, `unattributed_s=0.00` — no blind spot);
    **silence** below threshold; **degraded path** (a raising join still returns
    every row). Plus a **mutation check** — deleting the `join_s` accumulation
    turns exactly the two attribution tests red and leaves the other 19 green,
    so they are not toothless (`#288`'s failure mode).
  - Two deliberate safety properties: timing locals live OUTSIDE the `try`
    (its `except Exception` swallows and returns unenriched candidates, so
    anything raising in there degrades the board silently), and the emit is in
    a `finally` (three exits; a profiler covering only the happy one would
    under-report exactly the slow calls worth seeing).
  - **DEPLOY FOLDED INTO THE 2026-08-14 13:00 WINDOW** as Part 3 of the
    `417-24h-read` scheduled task, gated on the `#417` read returning a
    CONCLUSIVE verdict. If that read is INCONCLUSIVE the deploy is skipped —
    another reboot would reset the re-warm clock and the read would never land.
  - **Scope of that deploy depends on what happens overnight.** If
    `deploy-419-refresh-worker` fires (00:00–05:00) the worker lands on
    `d6188ca7` and `7ce27100` then adds **exactly one production file**
    (`quote_enrichment.py`). If it does NOT fire, `7ce27100` also carries
    `live_refresh_loop.py` (+107, `#419`) which belongs to `mlb-props-regen` —
    two substantive changes, and not this lane's to bundle. The task is told
    to check and ask rather than decide.
  - **First useful reading is the following EVENING, not at deploy time.** The
    line only fires on a slow game and MLB's slow builds cluster 20:49–00:45Z.
    Silence before then is expected and is not evidence — the same mistake the
    predecessor lane made when it read "neither instrument has emitted" as a
    finding.

### checkpoint-witness — CLOSED 2026-08-13 — opened 2026-08-13 — session: hooks-test
- **OUTCOME: shipped to the working tree, all three verification items met,
  5/5 cases against the LIVE file `settings.json` dispatches to.** Uncommitted.
  - 1 PASS — session checkpointed after its work: exit 0, silent.
  - 2 WARN — work postdates the session's own checkpoint: exit 1, names the
    file, `witness: this session's checkpoint`.
  - 3 WARN — **falsification met.** No signal of its own, fresh shared marker
    (another session checkpointing): still exit 1. Under the old code this was
    a silent pass. This is the defect that mattered.
  - 4 PASS — step 7 via Bash `touch` is picked up as this session's signal.
  - 5 PASS — ledger-only session: nothing at risk, silent.
- Design changed once under test, before running: the first cut kept the
  marker's mtime as a FALLBACK for sessions with no signal. That reinstated
  the false pass for the single most important case — a session that has
  NEVER checkpointed — so the mtime read was removed entirely. Step 7 is
  honoured as an *act* seen in the transcript, not as a timestamp on disk.
- A second session was editing this file concurrently and had independently
  added a session-scoped log witness. Their half was kept; the two remaining
  holes were both in the false-PASS direction (unscoped marker mtime; log
  witness whose flag was session-scoped but whose *timestamp* was
  `max(mtime)` over any file in `.syndicate/log/`). `Edit` reported the file
  had changed on disk mid-lane, which is the only reason this was caught —
  re-read, then continued on top of their structure rather than replacing it.
- `checkpoint.md` step 7 rewritten to match: it had described mtime
  comparison, which is no longer what happens.
- Goal: `checkpoint-guard.py` decides on a witness derived from **this
  session**, so (a) forgetting step 7 no longer produces a false warning and
  (b) another session's checkpoint can no longer produce a false PASS.
- Files (exclusive to this lane): `.claude/hooks/checkpoint-guard.py`,
  `.claude/commands/checkpoint.md`. Neither is claimed by any other lane
  (checked 2026-08-13 against every `###` header).
- Predecessor: `checkpoint-guard-scope`, CLOSED-VOID — it rewrote a file that
  had been deleted. This lane re-read the live artifact and confirmed it is
  unchanged since `5cdf45b6` before editing.
- The defect being fixed is **not** the one that lane chased. `5cdf45b6`
  already scoped the denominator to the session's edited files. What remains is
  the WITNESS: `.syndicate/.last-checkpoint` is repo-global, untracked, and
  written by a manual step.
  - False PASS: session A checkpoints at 15:10, touching the shared marker.
    Session B edited code at 15:05 and stops without checkpointing. B's newest
    work predates the marker, so B passes silently. With 3 concurrent sessions
    this is the common case, not the corner case. **This is the dangerous
    direction — it is the failure the guard exists to prevent.**
  - False WARN: a session that writes the ledger but forgets step 7.
- Fix: witness = the newest of this session's own signals, read from its own
  transcript — the `/checkpoint` invocation timestamp and any `.syndicate/**`
  write by a file tool. The global marker is used **only** when the session has
  no signal of its own, so it can no longer be set by a different session.
  `.syndicate/**` stops counting as work (it is the persistence, not the thing
  at risk), which also removes the false warning from ledger appends.
- Verified before coding: both signals are present in this session's transcript
  — `/checkpoint` at `19:45:50Z` as `<command-name>/checkpoint</command-name>`,
  and tool-written ledger edits at `19:53/19:58Z`. Bash-written appends (`cat
  >>`) do NOT appear, which is why the command timestamp is needed as well.
- Falsification test: construct a payload where the only witness is another
  session's marker. The guard must WARN. If it passes, the contamination is
  not fixed.
- Verification (all three): (1) PASS when the session checkpointed after its
  work; (2) WARN when only a foreign marker is newer; (3) WARN when real work
  postdates the session's own checkpoint — run against the LIVE file that
  `settings.json` dispatches to, with a synthetic payload on stdin.
- Deploy exposure: none. Harness-only.
- Blocked by: none.

### checkpoint-guard-scope — CLOSED-VOID 2026-08-13 — opened 2026-08-13 — session: hooks-test
- **OUTCOME: no work product. The premise was already false when the lane was
  opened, and the lane edited a file that had been deleted.** Both defects it
  set out to fix were fixed in `5cdf45b6` — which was HEAD at this session's
  start. That commit deleted `checkpoint-guard.sh`, added
  `checkpoint-guard.py`, and repointed `settings.json`. See RESULT below.
- Goal: `checkpoint-guard.sh` fires on **this session's unpersisted work** and
  is silent otherwise — i.e. its pass branch becomes reachable and its
  denominator becomes the session, not the worktree.
- Files (exclusive to this lane):
  - `.claude/hooks/checkpoint-guard.sh` — scope + parsing + witness.
  - `.claude/commands/checkpoint.md` — step 7 wording only.
- CORRECTION to the closed `hooks-enforcement-test` lane: step 7 (`touch
  .syndicate/.last-checkpoint`) was reported missing from `checkpoint.md`.
  **It is present and has been since `f6fec4f1`.** The marker was absent
  because that commit landed 08-13; the 27 observed Stop deliveries predate
  it. The defect is not a missing instruction — it is that the pass branch
  depends on a model executing an optional-looking last step.
- Hypothesis: two independent causes of the all-fire distribution.
  (1) `DIRTY` counts the whole worktree (66 files at the last checkpoint,
  4 of them the session's), so the condition is ~always true in a repo whose
  pipeline output is permanently dirty. (2) the pass branch needs BOTH
  `$TODAY_LOG` and `$MARKER`, and the marker had never been written.
- Falsification test: with the marker fresh and only generated output dirty,
  the guard must exit 0. If it still exits 1, scope is not the cause.
- Verification (both required):
  1. PASS branch witnessed — exit 0 at least once. Never observed to date.
  2. FIRE branch still works — touch a source file after the marker and
     confirm exit 1 naming that file, so the fix is not inertness.
- Note on method: running this hook in a terminal is legitimate here. The
  08-13 FORBIDDEN entry is about assuming stdout ARRIVES; delivery for this
  hook is already measured (27 deliveries), so what is unverified is the
  predicate, and the predicate is testable locally.
- Deploy exposure: none. Harness-only, no service code, no `render.yaml`.
- Blocked by: none.
- **RESULT 2026-08-13 — the lane rewrote `checkpoint-guard.sh`, which does not
  exist.** It was read at ~12:49, deleted upstream, and recreated at 14:55 by
  a `Write`. It sat untracked, invoked by nothing; `settings.json` has pointed
  at `checkpoint-guard.py` since `5cdf45b6`. Four tests were run and all four
  "passed" — against the orphan. The live hook was never executed.
  - Also mis-corrected `checkpoint.md` step 7 to describe the orphan's
    semantics (`data/**` `reports/**` `vendor/**` exclusions, log co-witness).
    None of that is true of the `.py`. Reverted.
  - Cleanup: orphan deleted, `checkpoint.md` restored with
    `git checkout --`. `git status -- .claude` is empty against HEAD. Nothing
    from this lane survives in the harness.
  - The `.py`'s scoping is **better** than what this lane built: its
    denominator is the files the session actually edited, parsed from its own
    `transcript_path`, not a path-prefix heuristic over the worktree.
- **RESIDUAL — one real gap in the live `.py`, NOT acted on.** Its only pass
  witness is `.last-checkpoint` (L152). A session that writes the ledger but
  forgets step 7 has its own `.syndicate/` writes counted as unpersisted work
  and is warned anyway. Adding today's log as a second witness would close it.
  Left to the owning session — that file is another lane's freshly shipped
  work and this lane has just demonstrated why it should not edit it blind. — opened 2026-08-13 — session: memory-guard
- **CHECKPOINT 2026-08-13 13:3x CDT. Code done and shipped; the lane stays
  OPEN because its verification is not complete.**
  - Shipped: `03073270` live on refresh-worker since 13:05 CDT (deploy
    `dep-d9v0b8bncjis73an78hg`). Verification items 1 and 2 (unit +
    liveness-in-test) MET: 13/13 memory_observability, falsification tests
    written before the fix and run red first.
  - Verification item 3 (production) **NOT met.** T+23min shows
    `LAYER2_SHORTLIST` x3 vs 0 in the preceding 4h12m and 0 aborts vs ~300 in
    5.4h — but the container is 23 minutes from boot, and the PRE-FIX code
    also rebuilt after a restart and re-froze ~3h later. Not discriminating
    yet.
  - **SINGLE NEXT ACTION for whoever picks this up: take the 24h read at
    2026-08-14 ~13:00 CDT.** Count `MEMORY_GUARD_ABORT` and
    `LAYER2_SHORTLIST` on `srv-d91dpertqb8s73co8ls0` since
    `2026-08-13T18:05:38Z`, and record `anon` drift. Aborts ~0 with the board
    still building = fix holds. Aborts resumed = it did not.
    Write the result into the OPEN `deploys.md` row. OWNER STILL UNASSIGNED.
  - Known gap, do not mistake for a result: `basis` cannot confirm the code
    path ran — it is emitted only on the abort branch. See `learnings.md`.
  - Push blocked, not by this lane: local `main` is 20 ahead / 6 behind and
    `.claude/hooks/session-start.sh` holds another session's uncommitted work.
    `03073270` is already on `origin/main`, so nothing here depends on it.
- **CHECKPOINT 2026-08-13 ~15:0x CDT — final for this session.**
  - Push blocker **CLEARED**: `session-start.sh` was committed by its own
    session (`0634e7bb`/`0f182961`). Local `main` now **22 ahead / 6 behind**,
    so a push needs a merge first and still carries other lanes' commits.
    Nothing in this lane depends on it — `03073270` is already on origin.
  - Filed **`#422`** (`b15fe051`): web is 47 commits behind, only 14 of them
    production, and `layer1-live-tier`'s "SHIPPED AND VERIFIED" may cover only
    the worker half. Filed as an INFERENCE with the confirming check named.
  - A blanket web deploy **FAILED `/preflight`** — 14 commits across five
    lanes, two files claimed by open lanes, no named reader. The board slice
    alone is the deploy worth making, and it belongs to `layer1-live-tier`.
  - Three entries appended to `learnings.md`, all from this lane's own
    instruments misleading it: a discriminator that only emits on failure; a
    watcher whose label was not entailed by its exit condition; and
    "pushed to origin" != "applied to production".
  - **STILL THE SINGLE NEXT ACTION: the 24h read, 2026-08-14 ~13:00 CDT.**
    Owner still unassigned. Everything else in this lane is done.


### memory-guard-reclaimable — CLOSED 2026-08-13 — fix VERIFIED, and it uncovered a leak
- **OUTCOME: all three verification items MET at T+4.71h.** Unit and liveness
  passed in test; production item 3 resolved 22:48Z. The live abort line
  carries `'basis': 'unreclaimable'` — proving the new path executes — with
  `active_file: 891.7` / `inactive_file: 229.8` credited as reclaimable. The
  guard is reading the right quantity. It refuses now only because `anon` is
  genuinely 2522.7MB.
- **The 24h read is cancelled**, not skipped: waiting would have measured a
  rebooted container, and the verdict was already unambiguous.
- **The fix STAYS. Do not revert it** and do not read the 22:39-22:59 freeze as
  its failure — see `#423`. The 1900MB floor is now the open question, and only
  after the leak is understood; resizing against a leaking baseline just moves
  the freeze later.
- Handed on: the leak itself, as `#423` / lane `refresh-worker-anon-leak`.

### memory-guard-reclaimable (detail below, kept for the file/line map) — session: memory-guard
- Goal: `memory_headroom_snapshot` decides on unreclaimable memory
  (`anon + shmem + slab_unreclaimable`), so that total memory in use FALLING
  can never tighten the guard. Unblocks `#417` and `#387` in one change.
- Files (exclusive to this lane):
  - `syndicate/features/shared/memory_observability.py` — the fix. Two sites
    share the same wrong formula:
    - `memory_headroom_snapshot()` L238–242 — `reclaimable_bytes =
      inactive_file + slab_reclaimable`. This is the guard.
    - `log_container_memory()` L599–609 — recomputes the SAME expression to
      derive `memory_unreclaimable_mb`. Diagnostic only, but it is the line
      humans read, so it must move with the guard or the log will contradict
      the decision.
  - `tests/test_memory_observability.py` — see hazard below.
  - `pipeline/intelligence_state.py` — L3189 constant only
    (`_MIN_SAFE_MEMORY_HEADROOM_BYTES = 1900MB`). No call-site change.
  - `syndicate/features/intelligence.py` — L2563 constant only
    (`_OVERVIEW_MIN_SAFE_HEADROOM_BYTES = 3000MB` vs a stage measured at
    ~1479MB). No call-site change.
- Not touched, deliberately: the five calling modules
  (`live_refresh_loop.py` ×2 wrappers, `live_lens_loop.py` ×2 wrappers, and
  both `intelligence_state.py` call sites) all funnel through the one shared
  function. Per the `#334` lesson, the fix goes INSIDE it and touches zero
  call sites — that is what makes it unmissable.
  `scripts/check_worker_memory_gate.py` L338 records that it never inherited
  this formula and works on an RSS basis; adjacent, not the same defect,
  and out of scope.
- Hypothesis: the guard's verdict moves on kernel LRU bookkeeping, not on
  memory pressure. `#417`'s 300 consecutive aborts were caused by ~243MB
  being promoted `inactive_file` → `active_file`, which the formula counts
  as unavailable, while `anon` drifted +18.9MB across all 300 samples.
- Falsification test: replay the `#417` sample series — effective headroom
  fell 1877 → 1643MB while total memory in use fell 3120 → 2705MB. Under the
  new metric the guard must NOT tighten across that series. If it still
  tightens, the LRU-promotion hypothesis is wrong and something else moved it.
- Verification (all three required):
  1. Unit: the replayed `#417` series does not tighten.
  2. Liveness — the guard must still be able to REFUSE. Construct a case with
     genuinely high unreclaimable memory and assert `sufficient` is False.
     Without this, "zero aborts in production" is indistinguishable from a
     permanently-inert guard, and inert is how `#75` (the 4GiB OOM) happened.
  3. Production, after deploy: `MEMORY_GUARD_ABORT
     stage=pre_source_state_fingerprint` over a full day drops to ~0 with
     `anon` flat, and `#387`'s overview build stops aborting at
     `sports_done=0 sports_total=8`.
- HAZARD — an existing test asserts the bug is intentional.
  `test_active_file_and_shmem_are_not_treated_as_reclaimable`
  (`tests/test_memory_observability.py:173`) and the code comment at
  `memory_observability.py:234–237` both call the current formula
  "deliberately the conservative reading". That premise was overturned by
  `#417`: excluding `active_file` is not conservative, it is unstable — it
  makes the verdict swing on a quantity the kernel moves for free. This test
  must be rewritten with a comment recording WHY the premise changed, never
  deleted or quietly made green.
- HAZARD — the direction of failure. Relaxing this guard is what the
  `memory_observability.py:166–168` comment warns walks back into `#75`, the
  4GiB OOM. Note `shmem` was 0.0 in the `#79` measurement, so it has never
  actually been exercised as a pinned-cache term; do not assume it is zero on
  refresh-worker today.
- Deploy: refresh-worker `.py` only. No `render.yaml`, so no `blueprint_sync`
  exposure. Standing sim-check gate applies before any deploy is triggered.
- Blocked by: none.
- **STATUS 2026-08-13 — falsification test written and RUN. Hypothesis
  SURVIVED; the lane is cleared to proceed to the fix.**
  `tests/test_memory_observability.py`, 11 passed / 2 failed, the two failures
  being the new falsification tests, failing for exactly the predicted reason:
  - `test_417_page_cache_promotion_must_not_move_the_guard` — moving 243MB
    between LRU buckets, with `current`, `anon` and total file cache all held
    constant, swings the guard **1895.3 -> 1652.3 (243.0MB)**. The observable
    moves the full size of the reclassification with nothing real changing.
  - `test_417_series_never_tightens_while_memory_in_use_falls` — the recorded
    4-sample series is refused at sample 1 (`09:29:27 refused a build that
    fits`), i.e. all 300 aborted cycles had room under the unreclaimable
    reading.
  - Fixture provenance: `slab_reclaimable` is absent from the recorded table
    and was back-solved per row (34.2 / 35.3 / 34.8 / 39.3MB). All four rows
    then reproduce the recorded `headroom` to **±0.00MB**, so the fixture is
    derived from the real formula rather than fitted to the conclusion. If a
    future edit breaks that reproduction, the fixture is wrong, not the code.
  - `test_unreadable_anon_must_not_produce_a_rosy_headroom` **passes today and
    is still required.** It is inert against the current formula, which never
    reads `anon`; it becomes load-bearing the moment the fix does. Do not read
    its green as evidence of anything about the fix — it is a regression guard
    placed ahead of the change, and its own predicate is not yet exercised.
  - Not committed. The file is RED on a shared tree by design.
- **STATUS 2026-08-13 — FIX WRITTEN. Both falsification tests now pass;
  `tests/test_memory_observability.py` 13/13 green. Not committed, not
  deployed, production effect UNVERIFIED.**
  - The guard now decides on `max_bytes - unreclaimable`, where unreclaimable
    is `max(anon + shmem + slab_unreclaimable, current - reclaimable_file)`
    and `reclaimable_file` now includes `active_file`.
  - **The max() is the part worth reviewing.** The formula `learnings.md`
    prescribed (`anon + shmem + slab_unreclaimable`) is a LOWER bound on
    unreclaimable memory — it credits everything `memory.stat` fails to
    attribute as available, which is the permissive-on-unknown shape. Taking
    the larger of it and the residual basis (`current - reclaimable_file`,
    which is what `#318`'s log line already used) makes unaccounted memory
    count against the guard. On the `#417` samples the two bases differ by
    ~5.1-5.6MB, so this does not change the verdict there — it changes what
    happens if `#327`'s unattributed allocator ever shows up in this reading.
  - Both helpers are shared by the guard and by `log_container_memory`, which
    had an independent second copy of the reclaimable expression. Fixing only
    the guard would have left the abort line contradicting the decision it is
    read to explain. Grepped after the change: no third copy exists.
  - Degrade path unchanged in the safe direction: `anon` absent -> return None
    -> fall back to the previous arithmetic, never to a rosier number.
  - `#417`'s second defect fixed in the same pass:
    `headroom_including_file_cache_mb` -> `headroom_excluding_file_cache_mb`.
    The name stated the opposite of its value and produced a 792MB apparent
    deficit against a real one of 278MB during the incident. Renamed rather
    than aliased; nothing outside this module's tests reads it.
  - Two pre-existing tests changed deliberately, neither made green by
    weakening it:
    - `test_reclaimable_page_cache_does_not_count_against_headroom` (`#79`)
      moved +34.3MB, exactly its fixture's `active_file`. Conclusion it
      protects is intact (868 vs 3428, was 868 vs 3393).
    - `test_active_file_and_shmem_are_not_treated_as_reclaimable` split into
      `test_shmem_is_not_treated_as_reclaimable` (still true, different
      reason) plus the new `#417` invariance test that owns the overturned
      active_file half.
  - Consumer blast radius, partially checked: 7/7
    `test_intelligence_overview_memory_guard.py`, and 25 memory/headroom/guard
    tests across `test_intelligence_state.py`, `test_deploy_preflight.py`,
    `test_live_lens_loop.py`. **Full 6-file consumer sweep still running at
    time of writing — not yet a result.**
  - REMAINING before this can close: the production half of Verification
    (items 2 and 3 above) is untouched. Nothing here proves the deployed
    behaviour changes; per `learnings.md` a deployed fix can be inert.
- **STATUS 2026-08-13 12:2x CDT — PUSHED to `origin/main` as `03073270`,
  decoupled from config. NOT DEPLOYED. Production effect still UNVERIFIED.**
  - `/preflight` returned **FAIL** on the original candidate (`03073270` on
    local `main`) for a reason that had nothing to do with the fix: local
    `main` carried **four unpushed `render.yaml` commits** underneath it
    (web env block 64 -> 52 keys). Render deploys from GitHub, so shipping
    the fix required a push, and that push would have fired `blueprint_sync`
    — rewriting the whole env block on all three live services. A code fix
    would have carried an undecided production config change as a passenger.
  - Resolved by cherry-picking onto `origin/main` in a throwaway worktree
    (the shared tree has other sessions' uncommitted work). Verified before
    pushing: 3 files, **zero `render.yaml` delta**, web-block key count
    64 == 64, and `render.yaml` absent from the commit entirely. 20/20 tests
    green on that base (13 memory_observability + 7 overview guard).
  - **The `render.yaml` web-block audit is now unshipped and unowned.** It
    still sits on local `main` only. It needs its own `/preflight` and its
    own `deploys.md` row — it is a production config change, not a passenger.
    One item for whoever takes it: `MLB_ENABLE_LIVE_LENS_LOOP: "false"` is
    among the 12 keys being removed from web. If the code default is True,
    removing it turns the loop ON for web rather than off — the `absent != off`
    hazard. NOT verified by this lane.
  - **`main` has diverged and this commit now exists twice.** `03073270`
    (local) and `03073270` (origin) are the same change. Local `main` is 6
    ahead / 1 behind origin. Do not `git pull` and assume a clean merge —
    reconcile deliberately, and drop the local duplicate rather than
    re-landing it.
  - Deploy still gated: `scripts/check_deploy_safety.py` returned NOT CLEAR
    twice, 12:14 and 12:2x CDT — MLB sims running back-to-back (pid 4514
    `tip_off_window`, then pid 4718 `fingerprint_change`) plus a live odds
    refresh, with live games in progress. Deploying kills them.
  - **Falsifiable discriminator for the post-deploy read, stated before the
    deploy:** the new `basis` field. `basis=unreclaimable` proves the new
    path executed; `basis=reclaimable_cache` means it degraded to the old
    arithmetic and any "zero aborts" reading is inert-guard-shaped and means
    nothing. Read that BEFORE reading the abort count.
- **STATUS 2026-08-13 ~12:5x CDT — local `main` reconciled with `origin/main`
  (`a3f9ed97`). Push HELD by decision. Still not deployed.**
  - Merge, not rebase. `git cherry` showed two local commits patch-equivalent
    to origin (`03073270`≡`03073270`, `b48aa0d3`≡`b48aa0d3`); a rebase would
    have dropped them cleanly but rewritten **seven commits belonging to other
    sessions** working this shared checkout, and the ledger cites SHAs by
    hand. Verified after: 0 behind / 11 ahead, `origin/main` is an ancestor,
    all six other-session SHAs unchanged, and the merge commit is **empty
    against its first parent** — content was already identical, only ancestry
    changed.
  - One conflict (`.syndicate/lanes.md`), both regions ours-only with an
    **empty theirs side**. Resolved keep-ours; verified content-complete
    (468 lines both sides, differing only CRLF vs LF).
  - NEAR-MISS worth recording: the first merge attempt was aborted because
    another session had **8 files staged in the shared index** (the
    `.syndicate` enforcement hooks). A merge commit takes the WHOLE index, so
    completing it would have swallowed their in-flight work. Proved the merge
    safe in a throwaway worktree instead, and ran it only once their index
    cleared. `learnings.md` already has the never-chain-add-and-commit rule;
    this is the same hazard arriving through `git merge` instead.
- **RETRACTION — the `render.yaml` hazard I raised is NOT a hazard.** This
  lane earlier flagged `MLB_ENABLE_LIVE_LENS_LOOP: "false"` as a possible
  `absent != off` trap in the web-block audit. Checked against the code:
  **no Python reads that key anywhere** — it exists only in `render.yaml`, so
  removing it from web is inert. Also cleared:
  `WEEKLY_SPORTS_ENABLE_REFRESH_WORKER_AUTORUN` defaults **False** when absent
  (`scripts/run_refresh_worker.py:338`), `REFRESH_PREDICT_PROPS_SMART_SIM_PBP`
  defaults **True** matching its removed value, and
  `SYNDICATE_LIVE_ODDS_GAME_LINE_REGIONS` is read only by a worker script as
  EXTRAS (absent = no extras, `scripts/fetch_mlb_oddsapi_local.py:1593`).
  The audit's "already declared on both workers, unchanged there" claim holds.
  Recording the retraction loudly because a false caveat about someone else's
  work silently devalues their correct readings too.
- **What still blocks the push is the MECHANISM, not the diff.** A
  `blueprint_sync` writes the WHOLE env block on all three services — not the
  diff — including live drift nobody has read, and last time it 502'd every
  route for ~2 minutes. That restart kills an in-flight MLB sim exactly as a
  deploy does. Decision taken: **hold the push until
  `check_deploy_safety.py` reports CLEAR, then push and deploy in the same
  quiet window** so the config sync and the code deploy cost one interruption
  instead of two. Watcher `b07yqo98b` is armed, polling every 90s.
- Discrepancy noted, does not affect the verdict: the `#417` narrative in
  `.syndicate/log/2026-08-13.md` and `todo.md` says `current_mb` fell
  "3120 -> 2705", but the 4-row table it sits beside records 2988.6 -> 2705.3.
  The 3120 figure is not in the table; it is presumably an intermediate peak.
  Both readings agree in DIRECTION (usage fell, guard tightened), so the
  falsification test holds either way — but the table is the authoritative
  per-sample record and is what the fixture uses.

### mlb-props-regen — OPEN — opened 2026-08-13 — session: mlb-props-regen
- **CROSS-LANE EDIT TAKEN 2026-08-14, WITH AN EXPLICIT USER OVERRIDE, LOGGED
  HERE BECAUSE THE PROTOCOL REQUIRES IT.** Session `layer2-freshness` edited
  `syndicate/features/shared/live_refresh_loop.py` — this lane's claimed file —
  to make the pregame relaunch cooldown PER-SPORT. `lane-guard` refused it
  (exit 2) and the user authorised the override after being shown the block and
  the two live measurement windows it risks.
  - **Scope is narrow and named**: `_last_pregame_launch_path`,
    `_read_last_pregame_launch`, `_record_pregame_launch`,
    `_pregame_relaunch_blocked`, and the one call site that filters
    `sports_to_launch`. Nothing else in this file was touched. If this lane has
    uncommitted work elsewhere in it, there is no overlap.
  - **Why it could not wait**: the global cooldown is the measured cause of
    MLB's ~121.6-minute odds capture cadence (see `state.md`), which is why the
    board carries candidates that are no longer bettable.
  - **WRITTEN, TESTED, PUSHED TO A BRANCH — NOT ON `main`, NOT DEPLOYED.**
    Commit `ea8fad58` locally, pushed as `origin/odds/pregame-cooldown-per-sport`.
    **Deliberately not on `main`**: `autoDeploy` is off, but other sessions
    deploy refresh-worker several times a day and would have shipped this
    mid-measurement. `origin/main` moved to `e9990ccb` ("#433 soccer: capture
    odds before simulating") while this was being written, which is exactly the
    scenario the branch avoids.
  - What changed, five symbols only: `_record_pregame_launch` (stamps per-sport,
    keeps the legacy `epoch` for rollback), `_pregame_relaunch_blocked` (blocks
    only when EVERY candidate sport is cooling), and the two call sites, which
    now resolve the candidate sport list the same way the existing cadence
    filter does. `_apply_pregame_sport_cadence` was already per-sport and
    correct and is untouched — the defect was that the global gate ran BEFORE it
    and skipped the whole tick.
  - Tests: `tests/test_pregame_cooldown_per_sport.py` 12 passed, mutation-pinned
    (forcing the sport list empty turns exactly the 2 decoupling tests red and
    leaves the 10 safety tests green). `tests/test_live_refresh_loop.py`
    **226 passed / 13 subtests — identical to this lane's own baseline**, so the
    owning lane's suite is intact.
  - **Expected effect when it ships, and the cost:** MLB capture cadence
    ~121.6 min -> ~30 min (its own cooldown). Launch VOLUME rises roughly with
    the number of active sports, so OddsAPI spend rises against the 5M cap.
    Measure calls, not just cadence, in the first window.
  - **NOT DEPLOYED, deliberately.** Held until `530fc5d8`'s verification window
    and the `soccer-odds-coverage` per-league measurement both close, so neither
    is confounded. That was the user's explicit choice.
- Goal: MLB top-props/ladders rebuild automatically once prop odds land,
  instead of serving an empty artifact written before the odds existed.
  Testable outcome: a slate whose top-props artifact was written pre-odds
  gets a `props_now_available` launch within one cooldown of the odds
  landing, with no human trigger.
- Files (exclusive to this lane):
  - `syndicate/features/shared/live_refresh_loop.py` — all three fixes:
    - `_mlb_oddsapi_props_snapshot_has_entries()` L1554 — the blind read.
    - `_mlb_props_now_available_needs_regen()` L1562 — marker write moves out.
    - the fingerprint block L1938–1957 — marker write moves in (launch path).
    - `_sim_pipeline_deferral_reason()` L1673 /
      `_max_consecutive_pipeline_defers()` L1650 — starvation, SEPARATE
      COMMIT (see scope note).
  - `tests/test_live_refresh_loop.py` — see hazard.
- NOT touched, deliberately: `syndicate/features/shared/refresh_state_store.py`.
  Making `read_json_file` fall back to disk globally would fix this and change
  the semantics of every other caller in the repo at the same time. Out of
  scope; the narrow fix goes in the odds-presence helper.
- Hypothesis (recorded before testing — since CONFIRMED, see evidence):
  the `props_now_available` guard has **never been able to fire in
  production**. Its odds check reads through `read_json_file`
  (`refresh_state_store`, imported at L25), which for any path not containing
  `migration_runs/` goes to Redis with **no filesystem fallback** and returns
  `(None, True)` — "confirmed absent, read succeeded" — on a missing key. The
  snapshots it looks for are written by
  `vendor/mlb_bettingv2/tools/oddsapi/fetch_daily_oddsapi_markets.py:_write_json`
  (L87) as plain `tmp.write_text()` + `replace()`. **Writer is filesystem,
  reader is Redis.** So `has_pitcher_odds`/`has_hitter_odds` are always False
  and the guard returns "odds genuinely aren't posted yet" — silently, with no
  log line — every time.
- Evidence:
  - `SYNDICATE_REFRESH_STATE_BACKEND=keyvalue` confirmed live on
    refresh-worker via the Render env-vars API, so `_keyvalue_backed()` is
    True for these paths. This is the load-bearing precondition.
    `[measured 08-13]`
  - top-props written 00:24:21 CDT with `candidateCount: 0`; prop odds landed
    10:08 CDT (18 pitcher / 171 hitter markets); artifact still empty at
    11:43. `[measured 08-13]`
  - 5 of 100 sim ticks in 15:05–16:20Z reached the decision function at all
    (83 gated `intelligence_pipeline_busy`); all 5 returned `no_change` with
    `candidateCount = 0` and odds present. `[measured 08-13]`
  - The odds ARE on refresh-worker's own disk: the 11:56:56 rebuild ran with
    `--refresh-current-oddsapi off` and still produced 12 cards, so
    `daily_update.py` (plain filesystem IO) read them fine. Same box, same
    instant, same file — only the reader differs. `[measured 08-13]`
  - The 2026-08-13 recovery was NOT the safety net: an unrelated 3-game
    lineup resim (`--only-game-pks 823829,824238,824561`) happened to be in
    flight and its top-props stage rewrites the whole artifact. The
    `force-mlb-resim` trigger bounced off it with `previous_run_still_active`,
    so the fix is not attributable to it either. `[measured 08-13]`
- Falsification test: if the guard's odds check reads the snapshots from disk
  and it STILL returns False on a replayed 08-13 state, the writer/reader
  split is not the cause and the cooldown marker is the remaining candidate.
- Verification (all three required):
  1. Unit: a test that exercises the REAL `read_json_file` against a
     keyvalue-backed path with the file present on disk and the key absent.
     Must fail before the fix and pass after.
  2. Liveness — the guard must still be able to return False. Construct a
     case with genuinely no odds on disk and assert False, so "it fires now"
     is distinguishable from "it fires always". Per `learnings.md` 2026-08-13
     ("confirm an instrument can emit non-zero before believing its zero"),
     inverted here: confirm it can still emit False.
  3. Production, after deploy: on a slate whose top-props was written before
     odds landed, a `MLB_SIM_TICK` carrying
     `mlbDailySim.reason = props_now_available` appears within one cooldown
     of the odds file's `retrieved_at`. This reason string has **never once
     appeared in the logs** — absence is the current baseline, so a single
     occurrence is a clean positive.
- HAZARD — the entire existing test suite for this guard is blind to the bug.
  `test_mlb_props_now_available_needs_regen_true_when_odds_landed_after_empty_write`
  (`tests/test_live_refresh_loop.py:1492`) and its four siblings all
  `patch.object(live_refresh_loop, "read_json_file", side_effect=_fake_read)`
  — they replace the very function whose backend routing is the defect. They
  pass today and would pass against the broken code forever. New tests must
  NOT patch `read_json_file`. Do not delete the existing ones; they still
  cover the decision logic.
- HAZARD — three prior incidents (08-01, 08-02, 08-04) are named in this
  guard's own docstring and were "fixed" each time. Every one of those fixes
  refined code sitting downstream of a read that always returns None. Treat
  any further logic-only fix here as suspect until the read is proven.
- SCOPE NOTE — fix 3 (pipeline-defer starvation) is a SEPARATE COMMIT and
  should be a separate deploy. 83% tick suppression is real and measured, but
  the guard only needs to fire once per slate, and 5 opportunities in 75
  minutes is sufficient for that. Shipping a tuning change alongside the
  root-cause fix would make neither attributable — `learnings.md` 2026-08-12
  ("do not batch changes during a diagnosis").
- Interaction, not conflict: the breakthrough path in
  `_sim_pipeline_deferral_reason` gates on
  `_mlb_sim_memory_headroom_snapshot().sufficient`, whose meaning is being
  changed by the `memory-guard-reclaimable` lane. That lane owns
  `memory_observability.py`; this lane does not touch it. Expect the
  breakthrough rate to move when their fix lands, and do not read that as a
  result of this lane's work.
- Blocked by: none.
- **STATUS 2026-08-13 — HYPOTHESIS CONFIRMED, BOTH FIXES WRITTEN AND
  COMMITTED. NOT DEPLOYED. Production effect UNVERIFIED.**
  - `d6188ca7` (`#419`) — the root cause. `8a0d49d8` (`#420`) — the tick-vs-time
    bound, split out deliberately. `a0c5e7af` — tickets filed.
  - Falsification test RAN and the hypothesis survived: with the disk read
    stubbed out (pre-`#419` behaviour) the new regression test goes RED with
    the exact production symptom
    (`MLB_PROPS_REGEN_SKIPPED reason=no_odds_on_disk`), while the liveness test
    stays GREEN. So the test is a discriminator, not an always-fail.
  - `tests/test_live_refresh_loop.py` 226 passed / 13 subtests, exit 0. Seven
    adjacent suites that import this module: 148 passed, exit 0.
  - `#420` found a second, latent bug on the way: `streak_start or now_epoch`
    treats a legitimate epoch `0.0` as absent and restarts the clock every
    tick. Caught by the new elapsed-bound test — a shape unit tests see and
    production, with large epochs, never would. Reader now returns `None` for
    absent and the caller selects with `is None`.
  - **What is NOT established:** that any of this changes production. The
    verification criterion is unchanged and still outstanding — one
    `MLB_SIM_TICK` carrying `mlbDailySim.reason = props_now_available`. That
    string has never appeared in the logs, so absence is the baseline.
  - **Deploy not attempted on purpose.** An MLB slate went live ~12:06 CDT and
    a deploy kills an in-flight sim. Deploy decision belongs to the next
    window, and `/preflight` applies. `.py` only on refresh-worker — no
    `render.yaml`, so no `blueprint_sync` exposure.
  - Handed on, not fixed here: today's season betting-card artifact is missing
    (`verdict: artifact_missing`); scoped resims carry
    `--write-season-frontend-artifacts off` and never rebuild it.
- **STATUS 2026-08-13 12:50 CDT — `#419` IS PUSHED AND ARMED. DEPLOY PENDING
  THE SLATE. Anyone can finish this from cold; everything needed is below.**
  - `origin/main` is now **`d6188ca7`** — a cherry-pick of `d6188ca7` onto
    `f6fec4f1`, containing **`#419` and nothing else**. Verified before push:
    `render.yaml` byte-identical to origin/main (so **no `blueprint_sync`
    exposure**), `memory_observability.py` byte-identical, `#420` excluded.
    **CORRECTION 13:07 CDT — I read that second check wrong.** I inferred
    "identical to origin/main" ⇒ "`#417` is NOT in it". Identical means my
    commit did not CHANGE the file, not that the fix is absent. `03073270`
    (`#417/#387`) was already an ancestor of `f6fec4f1`, so **`d6188ca7`
    CONTAINS `#417`**. Consequence is benign and actually better than what I
    claimed: refresh-worker went live on `03073270` at some point after my
    preflight, so live→target is now measured as exactly two commits —
    `f6fec4f1` (`.claude/` hooks/settings, inert on the server; Render runs
    `scripts/run_refresh_worker.py`) and `#419`. **The only runtime delta is
    `#419`**, and deploying does not revert the memory-guard lane's work.
    Two files, +264/−7. Suite on that exact tree: 223 passed, exit 0.
  - **Why the cherry-pick.** `/preflight` FAILED on plain `main`. Two blockers,
    both other people's work: (1) `d6188ca7` has `03073270` (`#417/#387`) as an
    ANCESTOR, so no commit on main carries `#419` without it — two substantive
    changes, and `#417` moves `sufficient`, the exact gate `#420` reads;
    (2) local main was 12 ahead of origin including **three unpushed
    `render.yaml` commits** (`d16950b9`, `1e09fa9b`, `7c60d0f8`), which per
    `#284` apply to production on push. User chose the cherry-pick.
  - **STILL LOCAL AND UNPUSHED, for their owners:** `#417`/`#387`
    (`03073270`), `#420` (`8a0d49d8`), the three `render.yaml` commits, and
    this lane's own doc commits. Expect duplicate-commit divergence on the next
    push — it has already happened once here (`a3f9ed97`).
  - **Deploy target is refresh-worker ONLY.** Confirmed by env, not assumed:
    `SYNDICATE_ENABLE_MLB_DAILY_SIM_TRIGGER` is `true` there and `false` on
    live-odds-worker, which matches where `MLB_SIM_TICK` actually appears.
    (`SYNDICATE_MLB_REFRESH_TICK_OWNER=true` on live-odds governs a different
    path — odds-refresh sport launch — do not be misled by it.)
  - Gate at 17:45Z: `HOLD, 7 job(s) in flight`, including a live
    `run_mlb_daily_sim_job.py`. Last first pitch 21:10 CDT, so expect CLEAR
    ~00:15–00:30 CDT. A persistent Monitor is polling
    `scripts/deploy_preflight.py --service refresh-worker
    --target-commit d6188ca7 --json` every 10 min. **That monitor dies with the
    session — re-run the gate by hand if picking this up cold.**
  - Deploy only on `verdict: CLEAR`. Do NOT cancel a deploy once it passes
    `build_ended`: per that script's own header, cancelling mid-update CAUSES a
    restart rather than avoiding one.
  - **Verification (the whole point).** One `MLB_SIM_TICK` carrying
    `mlbDailySim.reason = props_now_available` on refresh-worker within one
    3600s cooldown of prop odds landing (measured median 02:02 CDT, `#421`).
    **That string has never appeared in the logs**, so absence is the
    established baseline and a single occurrence is a clean positive. Also
    expect `MLB_PROPS_REGEN_DUE`; `MLB_PROPS_REGEN_SKIPPED reason=no_odds_on_disk`
    appearing *after* odds are on disk would mean the fix did not take.
  - Rollback: redeploy `448e1816` on refresh-worker, or revert `d6188ca7`.
  - **A DURABLE scheduled task now owns this deploy**, so it no longer depends
    on a session staying alive: `deploy-419-refresh-worker`, at
    `C:\Users\tempadmin\.claude\scheduled-tasks\deploy-419-refresh-worker\SKILL.md`,
    firing every 20 min between 00:00–04:59 local. It is self-limiting: exits
    silently on `HOLD`, exits and deletes itself once `d6188ca7` is live,
    deploys at most once, never pushes, never touches `render.yaml`, and
    notifies only on a real outcome. **If you deploy this by hand, delete that
    task** or it will keep firing tomorrow night.
  - Known gap in that mechanism: scheduled tasks only run while the desktop app
    is open; if it is closed at the fire time the run happens at next launch.
    So "durable" means "survives the session", not "survives the app being
    shut all night".
  - **Second known gap, and it needed a fix: first-run tool approvals.** The
    task has never run, so its Bash/curl/notification permissions are not yet
    stored. If it pauses on a prompt at 00:03 with nobody watching, nothing
    deploys and no ping arrives. The obvious remedy — click "Run now" to
    pre-approve — was itself unsafe as originally written, because the task
    relied on its **cron window** to mean "after the slate" and a manual run
    bypasses the schedule. At 13:07 the job gate read `CLEAR` mid-slate, so
    Run now would have deployed into live games. Fixed by making the slate
    condition an explicit **Step 0** inside the prompt (`date +%H` must be
    00–04, checked before anything else), so a manual run now stops
    harmlessly. Same lesson as the `learnings.md` entry it came from —
    encode the stated condition, do not let the schedule imply it.

### hooks-enforcement-test — CLOSED 2026-08-13 — opened 2026-08-13 — session: hooks-test
- OUTCOME: `lane-guard` (PreToolUse) **enforces**, measured at the destination
  in 4 probes. `session-start` **delivers within budget** (1,243 B arrived,
  no truncation). `checkpoint-guard` (Stop) **fires but cannot pass and does
  not block** — 27/27 deliveries across 5 sessions at `exitCode 1`, and the
  harness labels that "non-blocking". Two defects filed below.

#### RESULTS — measured 2026-08-13, this session

| probe | attempt | result |
|---|---|---|
| A | `Edit` own-lane file, marker set | ALLOWED — correct |
| B | `Edit` foreign-claimed file | **BLOCKED**, exit 2, edit did not land |
| C | `Edit` own-lane file, marker EMPTY | **BLOCKED** — marker is load-bearing |
| D | `Write` foreign-claimed file | **BLOCKED** — matcher covers Write, not just Edit |
| E | `Bash` heredoc to foreign-claimed file | **WROTE THROUGH** — by design; the matcher is file-tools only |

- SessionStart, measured from the ARRIVING `attachment` record in this
  session's transcript (`2e6476cd`, line 3): `hookName=SessionStart:startup`,
  `exitCode=0`, `durationMs=1528`, **stdout 1,243 B**, no "Output too large"
  marker. The v3 rewrite holds against the ~2KB cap that made v1 ~5%
  functional. This is the destination-side check the 08-13 FORBIDDEN entry
  demands, not a terminal run.
- Probe C is the one worth remembering: with `.syndicate/.current-lane` empty
  the guard blocks the session's **own** files, and the message reads
  `Current lane: 'none'` — correct behaviour, confusing symptom. A session
  that opens a lane by hand-editing `lanes.md`, or one resumed after
  `/clear`, will hit this and look like a cross-lane collision.
- **Probe C is not hypothetical — it has already happened.** The marker did
  **not exist at all** before this session created it, so `none` was the repo's
  baseline. Session `ab30bcc8` line 186 carries a real block:
  `BLOCKED: tests/test_intelligence_state.py is claimed by OPEN lane
  'intelligence-state-red-baseline'. Current lane: 'none'.` — a session
  refused access to the file of the lane it was working (`#288`, the lane
  behind the `224 passed` baseline in `state.md`). `[measured 08-13]`
- **Closing a lane restores the failure state.** `/lane close` step 4 empties
  the marker, and an empty marker is the same lockout as a missing one. This
  session left it empty per the doc. Safe only because `/lane open` writes it
  — any session that edits a claimed file before opening a lane is locked out.
- METHOD NOTE — counting these from transcripts inflates badly. A first pass
  matching `BLOCKED:` across all transcripts returned **11**; the hook's own
  source and the counting scripts contain the string. Filtering to records
  with a real `tool_result` / `is_error` payload gives **4** (3 probes here,
  1 prior). Sibling of the substring-containment caveat already in
  `learnings.md`.

#### DEFECT 1 — `checkpoint-guard` can never take its pass branch
- `.syndicate/.last-checkpoint` **does not exist and never has**, so
  `[ -f "$MARKER" ]` at `checkpoint-guard.sh:17` is always false and the
  short-circuit is unreachable. Every Stop with a dirty tree warns.
- Measured across every transcript in this project: **27 Stop-hook deliveries,
  5 sessions, `exitCode 1` on all 27. Zero exit 0.** Meanwhile
  `.syndicate/log/2026-08-13.md` is 32,956 B — checkpoints ARE being written.
  The guard has been reporting "no checkpoint" at sessions that checkpointed.
- Second half of the defect: `DIRTY` counts the whole worktree — **65 files at
  baseline**, mostly pipeline output and other sessions' work. Even once the
  marker exists, a background artifact write after the checkpoint pushes
  `NEWEST` past `MARK` and the warning returns. The predicate is ~always true,
  so the alarm carries no information. Same shape as the `learnings.md`
  instrument-blindness entries.
- Fix: `/checkpoint` step 7 must actually `touch` the marker (it is in the
  command doc and was not happening), and the guard should compare against
  files the SESSION touched rather than the whole dirty tree.

#### DEFECT 2 — the Stop guard is advisory, not a gate
- Delivered stderr is prefixed **"Failed with non-blocking status code"**. Exit
  1 on Stop informs; it does not hold the session. The PreToolUse guard's
  exit 2 genuinely blocked (probe B). `CLAUDE.md` presents `/checkpoint` as an
  obligation — "if the session ends without a checkpoint, the work is
  considered lost" — and the enforcement behind it is a log line.
- Fix if a gate is wanted: exit 2. Decide deliberately; a blocking Stop hook
  that always fires (Defect 1) would wedge every session.

#### DEFECT 3 — nothing enforces the concurrent-lane cap
- `state.md` sets max concurrent OPEN lanes to **3** `[policy]`. This test
  opened lanes 3 and 4 and no check anywhere complained. `/lane open` step 3
  checks file collisions only; the cap is never counted.

- Probe fixtures (`reports/hooks_probe/`) and the temporary
  `hooks-probe-foreign` lane were deleted after the run. Nothing shipped;
  no code changed.

#### ORIGINAL LANE ENTRY (kept for the claim/hypothesis record)
- Goal: prove the three wired hooks ENFORCE at the destination, not just emit
  at the source. Named test, deliberately disposable — this lane exists to be
  the subject of its own experiment.
- Files (exclusive to this lane):
  - `.claude/hooks/lane-guard.py` — subject; not guarded by itself (the guard
    exempts `.claude/**` and `.syndicate/**`).
  - `.claude/hooks/checkpoint-guard.sh` — subject.
  - `.claude/hooks/session-start.sh` — subject.
  - `reports/hooks_probe/mine.txt` — probe file, THIS lane owns it. Expected
    ALLOW.
  - probe file owned by the temporary foreign lane below. Expected BLOCK.
- Hypothesis: `lane-guard.py` blocks a cross-lane edit through the harness
  (exit 2 on a `PreToolUse` match), and permits an edit whose claiming lane
  matches `.syndicate/.current-lane`.
- Falsification test: if the foreign-claimed Edit SUCCEEDS, the guard is inert
  in production regardless of what running it in a terminal shows. If the
  own-lane Edit is BLOCKED, the `.current-lane` marker is not being read and
  the guard is unusable (it would block every session's own work).
- Verification: both probes attempted as real `Edit` tool calls in this
  session, plus the SessionStart digest measured from the ARRIVING
  `attachment` record in this session's transcript — not from a terminal run.
  Per `learnings.md` 2026-08-13 (hook stdout cap): a terminal has no cap, so
  it can only ever confirm the emitter.
- Blocked by: none. No file overlap with `memory-guard-reclaimable` or
  `mlb-props-regen`.

## CLOSED THIS SESSION

### intelligence-state-red-baseline — CLOSED 2026-08-13 — opened 2026-08-13 — session: intel-state-baseline
- OUTCOME: `tests/test_intelligence_state.py` goes `4 failed / 220 passed` ->
  **`224 passed, 0 failed`**, all four repaired in the TEST with zero source
  changes, two of them proven load-bearing by source mutation. Verification
  items 1-3 all ran; results are in the STATUS block at the end of this lane.
- Goal: `tests/test_intelligence_state.py` is GREEN on a clean checkout, so a
  session working `#417`/`#338` in `pipeline/intelligence_state.py` can tell its
  own regression from standing noise. Testable outcome: 224 passed / 0 failed
  (baseline measured 2026-08-13: **4 failed, 220 passed, 10 subtests, 891s**).
- Files (exclusive to this lane):
  - `tests/test_intelligence_state.py` — **test-only lane.** All four failures
    are defects in the TEST, not in `pipeline/intelligence_state.py`; see the
    per-test findings below. If any of them turns out to need a source change,
    this lane STOPS and coordinates first.
- NOT touched, deliberately: `pipeline/intelligence_state.py`,
  `syndicate/blueprints/intelligence.py`,
  `syndicate/features/shared/refresh_state_store.py`. Each of the four failures
  is a case of production code being *right* and the test having rotted around
  it. Changing any of them to make a test green would be the exact inversion
  this lane exists to prevent.
- **Collision check against `memory-guard-reclaimable`: CLEAR.** That lane
  claims `pipeline/intelligence_state.py` (L3189 constant only) and
  `tests/test_memory_observability.py`. This lane claims neither. It does NOT
  claim `tests/test_intelligence_state.py` — its own STATUS note records
  running 25 memory/headroom tests from this file as a read-only consumer
  sweep, which is a read, not a claim. Flagged anyway: if that lane's
  `memory_headroom_snapshot` change lands while this lane is open, the
  memory-guard tests in THIS file may move. That is their change, not this
  lane's, and this lane must not "fix" it.
- Hypothesis (recorded before fixing — all four now CONFIRMED by traceback):
  each failure is an independent rot, with no common cause and nothing
  implicating the module under test.
  1. `test_read_latest_response_syncs_shared_backend_state` — **stale fake.**
     Its inline `FakeClient.set` is `lambda self, key, value`, but
     `refresh_state_store.write_json_file` has called `client.set(..., ex=ttl)`
     since `50a093b9` (2026-07-31, keyvalue TTL). `TypeError: unexpected
     keyword argument 'ex'`. The real fake in
     `tests/test_refresh_state_store.py:26` already takes `ex`; this one was
     missed. Production code is correct.
  2. `test_background_loop_survives_board_window_watch_exception` — **premise
     overturned.** Asserts `_latest_key == queued_key` for a payload carrying
     `sport: "mlb"`. `intelligence_state.py:5178-5183` now deliberately
     refuses to promote a sport-scoped payload to `_latest_key`
     (`LATEST_KEY_PROMOTION_SKIPPED_SPORT_SCOPED`, emitted in the failing run)
     because `_latest_key` drives the fallback-free `BOARD_SNAPSHOT_PATH`
     write and a one-sport board must never become "the board". The new
     behaviour already has its own test at line 1739
     (`test_background_loop_never_promotes_a_sport_scoped_payload_to_latest_key`).
     This test simply predates it.
  3. `test_query_endpoint_default_unchanged_when_combined_flag_disabled` —
     **date rot.** Fixture `selected_date` is hardcoded `2026-07-27` and the
     request is the dateless default question, which
     `_normalize_default_query_payload` stamps with today. 17 days apart, so
     `_response_needs_refresh` rejects it on date mismatch and
     `_stale_within_threshold(max_age_days=2)` refuses it as a stale fallback
     — leaving `_empty_default_intelligence_response()`. That cascade is
     deliberate and commented. The test passed the week it was written and
     could not pass after 2026-07-29.
  4. `test_build_candidate_pool_does_not_embed_full_odds_history_payload` —
     **not hermetic; the exact `#288` defect, second instance.** It patches
     `syndicate.features.intelligence.collect_all_recommendations`, which
     `pipeline/intelligence_state.py` never references — so the patch is a
     no-op and the candidates come from real git-tracked mirror data under
     `data/mlb_source/.../2026-06-10/`. That date is now two months past, so
     every one of the 32 scored candidates trips `_candidate_is_final` and is
     dropped (`candidate_scoring input_count=32 output_count=0
     final_filtered=32`), `candidate_pools` skips MLB via `if not
     sport_candidates: continue`, and `pool["candidate_pools"]["mlb"]`
     KeyErrors. The comment at line 3374 records that its sibling
     `test_build_candidate_pool_skips_sports_without_manifests` was REMOVED
     under `#288` for this identical defect; this one survived that pass.
- Falsification test: if a failure is a real defect in
  `pipeline/intelligence_state.py`, then the production path it exercises is
  wrong and the fix belongs in source. Discriminator applied to each: does the
  current source behaviour have (a) an explicit comment stating the intent,
  and (b) a separate test pinning it? For 2 and 3 both hold. For 1 the
  changed call is in a different module with its own correct fake. For 4 the
  patched symbol is provably not referenced by the module under test —
  `grep collect_all_recommendations pipeline/intelligence_state.py` is empty.
  Nothing survived as a source defect.
- HAZARD — test 4 must not be made green by relaxing it. Its live assertions
  are `assertNotIn("odds_history", mlb_pool)` / `assertIn(
  "odds_history_shard_key", mlb_pool)` — the pointer-not-payload contract that
  was the dominant memory driver before `#288`. The `mocked_loader.call_count
  == 2` assertion **already passes against a completely empty pool**, so it
  proves nothing on its own. The rewrite must be verified by MUTATION:
  re-embed `odds_history` in the pool dict and confirm the test goes red.
  Making it pass without that check would leave a second toothless test where
  `#288` removed the first.
- HAZARD — the `#288` comment at line 3374 says "DO NOT restore it by updating
  the expected constant". The same rule binds here: test 4 is repaired by
  removing its dependence on `data/`, not by re-tuning a fixture date until
  the mirror happens to agree.
- Verification (all three required):
  1. Each of the four fails before its own fix and passes after — run
     individually, not only as part of the file.
  2. Mutation checks against SOURCE, both required: re-embed `odds_history`
     on the per-sport pool entry and the rewritten test 4 (the pool test) must
     go red; remove the sport-scoped promotion skip and the rewritten test on
     `_latest_key` must go red.
  3. Full file green: `python -m pytest tests/test_intelligence_state.py`
     back to 0 failed, with the passing count going 220 -> 224 and no test
     deleted or skipped.
- Deploy: none. Test-only change, no production behaviour touched, no
  `render.yaml`. Nothing to gate.
- Blocked by: none.
- **STATUS 2026-08-13 — ALL THREE VERIFICATION ITEMS MET. Lane complete.**
  - (1) The four run individually: `4 passed in 35.34s`, against
    `4 failed in 44.25s` on the same four before the change.
  - (2) MUTATION CHECKS PASSED, run in a throwaway detached worktree at HEAD
    (`C:/tmp/isrb-mut`) so `pipeline/intelligence_state.py` was never edited in
    the shared tree — that file is claimed by `memory-guard-reclaimable`.
    Two source mutations applied at once (they hit different tests):
    - re-embedded `"odds_history": {...}` beside `odds_history_shard_key` in
      the per-sport pool dict -> `test_build_candidate_pool_does_not_embed_
      full_odds_history_payload` FAILED with `AssertionError: 'odds_history'
      unexpectedly found in {...}`. Right test, right reason.
    - replaced `if effective_sport != "all":` with `if False:` ->
      `test_background_loop_survives_board_window_watch_exception` FAILED with
      `'e7557377...' is not None`. Right test, right reason.
    - The mutation output ALSO settles the toothlessness worry directly: the
      failing dict printed `'candidate_count': 1` with a fully-populated
      `candidates` list, so the repaired test is inspecting a real pool, not
      an empty one.
  - (3) Full file: **`224 passed, 10 subtests passed in 901.58s`, 0 failed** —
    against the recorded baseline `4 failed, 220 passed, 10 subtests passed in
    891.33s`. 220 -> 224, nothing deleted, nothing skipped, no `@skip` or
    `xfail` added.
  - Diff is `tests/test_intelligence_state.py` ONLY. Zero source files touched.
    Net assertion change: +4 added (`candidate_count == 1`, `"mlb" in
    candidate_pools`, `mlb_pool["candidate_count"] == 1`, and the inverted
    `_latest_key`), 1 inverted, 0 removed.
  - NOTE on the full-file number's provenance: this run is against
    `d4bb29b5`, not the `b48aa0d3` the brief cited — `memory-guard-reclaimable`
    landed `03073270` (`memory_observability.py`, the `#417` unreclaimable-memory
    guard) in between. That is the interaction this lane flagged when it
    opened, and it turned out benign: the memory/headroom tests in this file
    are green on the new formula. `pipeline/intelligence_state.py` and
    `tests/test_intelligence_state.py` are byte-identical across
    `007f75b6..841228d9`, so the four diagnoses are unaffected by the move.
  - Housekeeping left behind: `C:/tmp/isrb-mut` is out of `git worktree list`
    and empty, but the directory itself would not delete (a lingering handle).
    Harmless; delete it if it is still there next session.


### render-yaml-web-block-hygiene — DONE 2026-08-13 — **NO LANE WAS EVER OPENED**
- Recorded after the fact. The originating task carried an explicit "do not open
  or close any lane" instruction and the work grew past it; five commits landed
  outside lane discipline. Flagged rather than tidied away.
- No collision occurred: the only OPEN lane (`memory-guard-reclaimable`) scopes
  itself to "refresh-worker `.py` only. No `render.yaml`." That was a read, not
  a claim — a second session editing `render.yaml` would not have been detected.
- Files touched: `render.yaml` (web `envVars` only), plus the ops-kit install
  (`.claude/**`, `.syndicate/**`, `CLAUDE.md`).
- Done: web block 62 → 52 entries; nine worker-only keys removed; three
  duplicate declarations (one per service) deduped. Every removed key remains
  declared on both workers.
- Verified: `audit_blueprint_drift.py` exit 0 / zero reverts after each commit;
  `tests/test_render_yaml_envs.py` + `tests/test_refresh_worker.py` pass;
  no duplicate keys on any service.
- **Unverified: nothing was deployed.** Reachability is static analysis only —
  no process has been observed booting without these keys.
- **Open obligation:** three commits unpushed (`d16950b9`, `1e09fa9b`,
  `7c60d0f8`), `origin/main` at `bf06710c`. Two `render.yaml` commits are
  already on origin with no `blueprint_sync` seen in a ~23-minute window —
  that is a window, not an all-clear.

### board-transport — CLOSED 2026-08-13 (work measured 08-10/11)
- Goal: the board computes correctly every cycle and cannot cross the transport.
- Files (exclusive to this lane while open):
  - `pipeline/intelligence_state.py`
  - `syndicate/features/shared/refresh_state_store.py`
  - `syndicate/features/shared/memory_observability.py`
  - `syndicate/blueprints/ops.py` (trace blocks only)
  - `scripts/deploy_preflight.py`, `tests/test_state_freshness.py`,
    `tests/test_candidate_trace_reads.py`, `tests/test_deploy_preflight.py`
- CLOSED: `#317` transport, `#322` state cache, `#324` keyvalue residency,
  `#327` memory instrument, `#334` freshness reporting, `#337` write-path count.
- **OPEN and handed back:** `#338` (serve reads `query_state_cache` at 150 while
  `board_snapshot` stores 220 — cause not localised), `#332` (NFL autorun guard,
  filed not fixed).
- **Blocked on another lane:** `#336`/`#338` are downstream of `#285`'s memory
  ratchet. The overview guard needs **~725MB** it does not have
  (3000MB floor vs 2275.5MB measured headroom), so it aborts at
  `sports_done=0 sports_total=8` and the candidate pool is empty by construction.
- All commits are ancestors of `478edd78`. No uncommitted work from this lane.

### sim-execution-observability — CLOSED-PENDING-MEASUREMENT 2026-08-13
- Goal: measure sim execution per sport (when/how long/how often/what triggers
  a re-sim), then fix what the measurement exposed.
- Files (exclusive to this lane):
  - `syndicate/features/shared/live_refresh_loop.py`
  - `syndicate/features/shared/sim_run_ledger.py`
  - `syndicate/features/shared/odds_book_quotes.py`
  - `syndicate/features/nfl/sources.py`
  - `scripts/run_refresh_worker.py`
  - `scripts/refresh_odds_sources.py`
  - `syndicate/blueprints/ops.py`
  - `syndicate/blueprints/home.py` (segment profiler only)
  - `syndicate/features/intelligence.py` (SLOW_GAME_CANDIDATE only)
- SHIPPED AND VERIFIED: `#388` (orphan cause recorded, observed twice in prod),
  `#389` + artifact-root fix (guard and writer share one resolver),
  `#390` (sim run ledger + `/api/ops/sims/ledger`), `#393` closed as
  root-caused-no-code-change.
- **OPEN AND UNMEASURED: where the board-build cost lives.** `448e1816` is live
  (`15:27:25Z`) carrying `SLOW_SEGMENT_PROFILE` (named segments, rows vs tail)
  and `_QUOTE_JOIN_STATS` (identity resolution by reason + `rows_walked`).
  Neither has emitted: the line is gated per-GAME at 5s and daytime games are
  ~0.4s each.
- Verification still required: one EVENING build (historically 20:49-00:45Z),
  then read one line:
  - `tail_s` >> `rows_s` -> cost is post-loop; `enrich_block` names it
  - `rows_s` >> `tail_s` -> the row loop is implicated after all
  - `by_teams_fallthrough` ~= `calls` with large `rows_walked` -> the cheap
    `event_id` key never matches, as predicted
- Blocked by: nothing. Needs an evening slate only.
- CAUTION: the previous instrument in this lane produced a confident wrong
  answer (see `learnings.md`). Read the segment NAMES, not the totals.

### soccer-sim-grouping — CLOSED 2026-08-10 — shipped and verified, one thread handed on
- Goal: `#282` break the soccer sim into per-league groups. Grew into `#311`,
  `#312`, `#327` as each surfaced from the one before.
- Files (exclusive to this lane):
  - `scripts/refresh_odds_sources.py`
  - `scripts/run_refresh_worker.py`
  - `scripts/audit_blueprint_drift.py` (new)
  - `syndicate/features/shared/ops_refresh.py`
  - `syndicate/features/shared/live_lens_loop.py`
  - `syndicate/features/shared/memory_observability.py`
  - `tests/test_live_lens_loop_publish_instrumentation.py` (new)
- **SHIPPED AND VERIFIED:** `#282` (8 launches, full rotation), `#311` (cap
  fired 16:06:31Z, first time ever, on the autorun path that was broken),
  `#327` instrument work (ring + high-water + in-sweep sampler all confirmed).
- **SHIPPED, MECHANISM UNTESTED:** `#312` — `f1bba90c` on `main`, live on
  nothing (its only deploy was cancelled). `render.yaml` change parked on
  branch **`hold/312-sync-false`**, deliberately off `main`.
- **OPEN, HANDED ON:** `#327 RESIDUAL` — the allocator is unattributed after
  five eliminations. Next action is one small change: record **bytes** on the
  pull and sweep paths beside the existing counts.
- No production change from this lane; all deploys were the oversight lane's.


### layer1-live-tier — CLOSED-PENDING-MEASUREMENT 2026-08-13
- Goal: Layer 1 board carries live projection, sim projection and actual-so-far
  on live rows, with correct live game state; retire `book_grid`.
- Files (exclusive to this lane):
  - `syndicate/features/shared/live_projection_join.py`
  - `syndicate/features/shared/board_enrichment.py`
  - `syndicate/features/shared/book_grid.py`
  - `syndicate/templates/shared/layer1_board.html`
  - `syndicate/templates/book_grid.html` (deleted)
  - `vendor/mlb_bettingv2/sim_engine/live_mc.py`
  - `vendor/mlb_bettingv2/tools/web/flask_frontend.py`
- SHIPPED AND VERIFIED: `#412` (prop join 0 -> 41), `#413` (live state,
  210 rows corrected), `#415` (Betting Board), `#411` (superseded lines).
- **OPEN AND UNVERIFIED: `#416`.** Writer emits live probabilities
  (`priced: 71`/`74`); `rows_live_edged` is still 0 on every build. The
  measurement is not yet READABLE — `e054e19f` splits the counter by game
  state so the `live` bucket can be read without final-game zeros diluting it.
- Verification still required: one build against a slate with live games, then
  read `snapshot_by_game_state["live"]`.
  - `{rows>0, with_live_prob>0}` -> working, edge should follow
  - `{rows>0, with_live_prob=0, with_live_projection>0}` -> writer half failing
  - `{rows: 0}` -> still no live slate, no verdict
- Blocked by: nothing. Needs a live slate only.

### internal-hostname-cutover — CLOSED 2026-08-13 — verified in production
- Verification met: every `PUBLISH_OK` line on refresh-worker at `14:54:11Z`
  carries `url=http://syndicate-an21:10000/api/ops/artifact...`, publishes
  succeeding (`published_hot_artifacts count=14 failed=0`), and
  `PUBLISH_BUDGET uploads=915 used_mb=302.4 ceiling_mb=20480.0`.
- Durability: `render.yaml` carries the internal hostname for both workers, so
  a `blueprint_sync` reinforces the fix instead of reverting it — the one thing
  that could silently have undone it.
- Report committed at `eaf7965d`; tickets now point at it (`3447f983`).

### (superseded lane detail, kept for the file/line map)

### internal-hostname-cutover — CLOSED — opened 2026-08-13 — session: <name>
- Goal: `SYNDICATE_WEB_PUBLISH_URL` points at the internal private-network
  hostname; worker→web traffic no longer leaves the Render network.
- Files:
  - `render.yaml` — env definition. Two blocks, one per worker:
    L418 (`refresh-worker`), L778 (`live-odds-worker`). Both already read
    `http://syndicate-an21:10000` (internal) in the repo. Hostname is
    `syndicate-an21`, NOT `syndicate`.
  - `syndicate/features/shared/artifact_publisher.py` — the only runtime
    reader. Five sites: `_publish_url()` L567, `_export_url()` L1077,
    the pull configuration gate L1230–1231, `_stream_url()` L1614, and
    the single-artifact stream gate L1664.
  - `tests/test_artifact_publisher.py` — asserts full URLs built from the
    var (e.g. L342, L470–480, L522); fixture value is a public
    `https://syndicate.onrender.com`, so a cutover touches it.
  - **No hardcoded fallback exists for this var.** Every read goes through
    `_env("SYNDICATE_WEB_PUBLISH_URL")` and returns `""` / skips when
    unset — absent means "publishing off", not "publish to the public URL".
    `[from-code 08-13]`
- Hypothesis: n/a (root cause confirmed from code)
- Falsification test: n/a
- Verification: service-initiated egress on `live-odds-worker` drops to
  near zero within one full sweep cycle; artifacts still publish
  successfully (non-zero publish count, no 5xx in worker logs).
- Blocked by: none

## CLOSED

_(none yet — seeded ledger)_

### hooks-enforcement-wiring — DONE 2026-08-13 — **NO LANE WAS EVER OPENED**

Recorded retroactively for traceability, matching the `render-yaml-web-block-hygiene`
precedent. Harness-only work (`.claude/**`, `.gitignore`, `.gitattributes`);
collisions were checked against the OPEN lanes and were nil, but that was a
read, not a claim. Third session today to work `.claude/**` without a lane —
if that keeps happening, the protocol should say harness work is exempt rather
than have every session quietly decide it is.

- Outcome: three hooks wired and measured end-to-end. `session-start` v3
  delivers 1,243 B inside the ~2KB cap (v1 delivered ~5%); `lane-guard.py`
  rewritten to parse the real lanes.md shape and confirmed blocking through
  the harness; `checkpoint-guard.py` replaces the `.sh` and can now pass.
- Commits: `f6fec4f1`, `0634e7bb`, `5cdf45b6`. Pushed: `f6fec4f1` only.
- Full detail: `.syndicate/log/2026-08-13.md`, session entry at the tail.

### ask-refusal-gate — OPEN — opened 2026-08-14 — session: ask-audit
- Goal: `market_summary` stops being the answer to questions that are not about
  betting. **Testable outcome:** `"What is the capital of France?"`,
  `"What is the weather at the stadium right now?"` and `"What is my account
  balance and betting history?"` stop returning five betting opportunities, and
  `scripts/ask_syndicate_regression.py`'s `refusal` class moves off 3/8 with
  **no regression in any other class** (currently: advice 4/5, entity 2/10,
  explain 4/6, history 1/5, lookup 2/8, ranking 4/10; overall 20/52).
- Why this first: measured on production 2026-08-14, `market_summary` is the
  resolved intent on **40 of 52** regression questions. It is the router's
  deliberate default for anything unmatched (`ask_the_syndicate_router.py:44-50`),
  and that default was CORRECT for vague *betting* questions -- it fixed a real
  dead end on 2026-08-03. It was never scoped to exclude questions that are not
  about betting at all.
- Files (exclusive to this lane):
  - `syndicate/blueprints/ask_the_syndicate_router.py` -- the default branch.
  - `syndicate/blueprints/ask_the_syndicate.py` -- early return for the new
    intent. **Added after opening**, once the dispatch was traced: the adapter
    selects a schema on `decision.intent` and an unknown intent falls to
    `_bet_analysis_schema`, i.e. the dead end this lane exists to avoid.
    Short-circuiting in the route keeps the change out of the adapter (see
    below) and skips the snapshot read for a question being declined.
  - `tests/test_ask_router_board_summary_default.py` -- new cases.
  - Collision check: CLEAR. Grepped every OPEN lane's claim block 2026-08-14;
    zero mentions of any `ask_the_syndicate*` file. The other OPEN lanes claim
    `pipeline/intelligence_state.py`, `syndicate/blueprints/intelligence.py`,
    `syndicate/features/shared/*`, `scripts/run_refresh_worker.py`.
  - NOT claimed, deliberately: `ask_the_syndicate_adapter.py`. A parallel
    session shipped `_board_summary_sentence` / `_is_general_board_question`
    there (`addec418`, `5c7e4d67`) building for exactly this no-LLM world. This
    lane routes; it does not touch their prose layer.
- Hypothesis (diagnostic half): the default is unconditional, so ANY question
  with no rule match returns a board summary regardless of subject.
- Falsification test: if some upstream guard already declines non-betting
  questions and the five measured board dumps came from something else, the
  router is exonerated and this lane is void. **Checked before opening: no such
  guard exists** -- `route()` returns `market_summary` at score 0 with no
  subject test, and production returned five opportunities for "What is the
  capital of France?".
- Verification: (1) new unit cases pass; (2) the four pre-existing test classes
  in `test_ask_router_board_summary_default.py` still pass -- especially
  `test_unmatched_question_defaults_to_summary_not_single_bet_analysis`, which
  pins the 2026-08-03 fix this must not undo; (3) re-run the regression harness
  against production after deploy and record the class-by-class delta here.
- Blocked by: none.

**RESULT 2026-08-14 -- code complete, locally verified, PRODUCTION MEASUREMENT
STILL OWED (not deployed).**

- **(1) and (2) DONE.** `136 passed, 23 subtests` across
  `test_ask_router_board_summary_default.py`, `test_ask_market_summary_ranking.py`
  and `test_ask_the_syndicate.py`. Blast radius is 4 files (grep
  `ask_the_syndicate_router`), all covered: the two blueprints and the two test
  files. The adapter imports only `RouteDecision`, and `out_of_scope` never
  reaches it -- the route short-circuits first.
- **(3) OWED.** Not deployed. `.py` pushes do not ship (`autoDeploy: no`).
- **Deterministic delta across all 52 regression questions**, router-level so it
  isolates this change from slate movement: `market_summary` **40 -> 37**,
  `out_of_scope` **0 -> 3**, `bet_analysis` 11 -> 11, `matchup_analysis` 1 -> 1.
  **3 cases changed, all 3 correct (F04 weather, F06 capital of France, F08
  personal records), ZERO regressions.** Refusal class 3/8 -> **6/8** expected.
- **MY "5 of 8" ESTIMATE WAS WRONG** and it was load-bearing for prioritisation.
  5 refusal cases were failing, not 8, and a lexical gate fixes 3 of those 5.
  F03 (dead player / nonexistent matchup) needs entity validation; F05
  (impossible tense) needs temporal validation. Both carry real domain
  vocabulary, so no word list catches them -- corrected in the plan.
- **Two regressions were caught by testing the ANSWER direction, not the decline
  direction, and would have shipped otherwise.** "How is Jokic looking tonight?"
  and "Best TB targets today?" were both declined by the first version -- a bare
  player name carries no domain noun, and `_fetchers_for_sport`'s own comment
  already records that exact Jokic phrasing as one the keyword sets miss. Fixed
  by treating day-scoping (`tonight`/`today`/...) as domain vocabulary, since a
  question scoped to a slate day IS about the slate. **A refusal gate must be
  tested on what it must NOT refuse; the decline list alone would have passed.**
- Also caught: `matches` as a domain token let "qwertyuiop nothing matches this
  at all" through. Dropped; `match` kept.
