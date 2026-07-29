# Syndicate TODO — canonical cross-session list

**This is the single source of truth for outstanding work.** Every session should
read this before starting and update it before finishing. Do not keep a parallel
list in session-local task tools without reconciling it back here.

Last reconciled: 2026-07-28 (see "Reconciliation 2026-07-28").

> **Next free ID: 129.** IDs are never reused. Closed items move to
> [`todo_closed.md`](todo_closed.md) — check there before assuming a number is
> free, and run the shipped-work check in Operational notes before reconciling.

- **New: #128** (filed, shipped this session, **NOT YET DEPLOYED — see below**)
  — implements #124's two explicitly-deferred follow-ups (a) and (b), triggered
  by the user reporting the same symptom fresh (MLB props still absent/wrong on
  the Layer 2 board) plus a new one ("Live" column showing the game's live total
  instead of the player's own actual, or 0). Confirmed live via production before
  touching code: `/mlb/api/live-lens` had `counts.props: 0` across all 8 live
  games at the time, even though `/mlb/api/cards` showed 6 of those 8 already had
  real `hitterProps`/`pitcherProps` populated — proving the card data existed and
  simply never reached the board, matching #124(a)'s diagnosis exactly.
  - **(a) `mlb/live_lens.py` inverted to cards-primary.** `_persist_live_lens_report`
    now builds the report from `_cards_backed_live_lens_report` FIRST (props come
    from cards, which is reliable per the production check above), then layers the
    vendored 120-sim Monte Carlo live re-sim on top as an *enhancement* via two new
    functions (`_enhance_card_row_with_live_projection`,
    `_enhance_cards_report_with_live_projection`) — MC only ever contributes
    `gameLens`/`status`/`score`/`predictions`, and only fills `props`/`liveProps`/
    `trackedProps` if the card row's are genuinely empty (never overwrites real
    card props). The old cards-onto-MC merge direction (`_merge_cards_context_into_report`/
    `_merge_cards_context_into_live_row`) is left in place (still has direct test
    coverage) but is no longer called from the main path.
  - **(b) The heavy MC re-sim is now hard-refused inside a web request.**
    `_live_projection_enhancement_payload` wraps the vendor `_live_lens_payload`
    call in `refuse_if_compute_in_request_path` (same guard/pattern as
    `_build_candidate_pool` in `pipeline/intelligence_state.py`) — raises only on
    hosted Render inside a real Flask request, no-ops for the live-odds-worker tick
    (no request context there) and local dev. `build_live_lens_snapshot_internal`
    itself now also calls `warn_if_compute_in_request_path` (soft, matches WNBA's
    own request-path fallback), documenting that it's reachable in-request as a
    cache-miss fallback, same shape as `wnba/live_lens.py`'s
    `build_live_lens_page_context`.
  - **New gap found and fixed in the same pass, not previously logged: MLB's
    plain card props (`markets.hitterProps`/`pitcherProps`) carry NO
    `actual`/`live_projection` fields at all** — confirmed via a real production
    `/mlb/api/cards` row (gamePk 824003, live game): full pregame sim/model
    fields, zero live-actual fields. The real live-actuals pipeline
    (registry-tracked snapshots + box-score-driven synthesis —
    `_synth_live_hitter_prop_rows`/`_current_live_pitcher_prop_rows`, genuinely
    independent of the vendored MC path) already existed in `mlb/cards.py` but was
    only reachable through the single-game detail view
    (`source_card_detail_payload` → `_source_sim_detail`). Extracted the shared
    computation into `_live_prop_rows_computed` (used by both) plus a new public
    `live_prop_rows_for_game(selected_date, game_pk)` entrypoint; `live_lens.py`'s
    `_card_to_live_lens_row` now calls a new `_live_props_from_game_detail` for
    any game whose card status bucket is "live", preferring those (real actuals)
    over the plain card props. Same hard-refuse guard as (b) — this does a live
    box-score fetch per game, so it's worker-tick-owned; a web request falls back
    to the plain (actual-less) card props rather than adding fetch latency to the
    request path.
  - **Frontend: `templates/intelligence.html`'s `displayLiveProjection`
    (the board's "Live" column) fixed to stop falling back to `item.live_total`
    (the GAME's live total) for prop candidates** — it was doing so
    unconditionally via `??`, which is exactly why every live prop's "Live" column
    showed the game score (or a real 0 from a genuine live_total) instead of the
    player's own value whenever `live_projection` was unset (i.e. always, before
    this session's backend fix). Now gated on `candidate_type`/`player_name` the
    same way `matchesClientFilters`' `isProp` check already does elsewhere in the
    same file; only game-level candidates still use `live_total` as their live value.
  - **Explicit user direction, not yet acted on beyond this session's MLB work**:
    apply the same architecture to WNBA "moving forward." Checked: WNBA's
    `wnba/live_lens.py` already matches this exact pattern (`build_cards_page_context`
    primary, thin live-line overlay, zero in-process simulation) — this was the
    reference implementation #124(a) told MLB to converge toward, not a gap on
    WNBA's side. No WNBA code changed this session; flagging in case a similar
    "props exist but the live-actuals field is empty" gap turns up there too.
  - **Also cleaned up in the same pass (test hygiene, not a feature change):**
    `report.json` at the repo root was a committed test-pollution artifact (fixture
    output from `tests/test_mlb_refresh_runner.py`'s live-lens tests, which mock
    `live_lens_report_path` to a bare relative `Path("report.json")` instead of a
    tmp path — confirmed via `git log` it's been accidentally recommitted at least
    3 times across sessions: `66720d0b`, `42472a9f`, `71b57a82`). Removed and added
    `/report.json` to `.gitignore` so it stops silently changing test outcomes
    based on git state (this is exactly what made two of these tests initially
    look like regressions from this session's change before the pollution was
    isolated and confirmed unrelated).
  - **Verification**: 197/198 targeted MLB + live-lens tests green (`test_mlb_refresh_runner.py`,
    `test_mlb_live_lens_snapshot_reader.py`, `test_live_lens_loop.py`, and 10 more
    `test_mlb_*.py` files) — the one failure
    (`test_live_lens_payload_refreshes_card_before_game_lens`) is a pre-existing,
    unrelated, run-order-dependent flake confirmed to fail identically against
    unmodified `main` in the same full-file run; not caused by this change.
  - **UPDATE, same session: user asked to commit/push/deploy. Deployed
    (3 rounds, all three services, commits `11815f8b` → `aa1eec15` →
    `86fbfc8e`), and production checking after each round found a SECOND,
    independent, previously-hidden bug that (a)'s fix depended on.**
    `11815f8b` (the fix above) deployed clean but `/mlb/api/live-lens` still
    showed `counts.props: 0` across all live games. Pulled the actual
    persisted worker artifact directly (`/api/ops/artifacts/export`) rather
    than guessing: it was structurally the raw vendor-MC shape (missing
    `prop_groups`/`prop_lens`/`market_tiles`/`probable`/`actual_box_panel`/
    `first1BetSignal`/`score` — fields only `_card_to_live_lens_row` sets),
    proving `_cards_backed_live_lens_report` was silently returning `None`
    on live-odds-worker and falling through to the MC-only branch. Added
    print diagnostics (`[CARDS_BACKED_LIVE_LENS_DIAG]`, `aa1eec15`,
    **still live, not yet removed**) and redeployed; the very first tick
    after that deploy logged the real cause:
    **`_cards_backed_live_lens_report`/`_merge_cards_context_into_report`
    have called `build_cards_page_context(selected_date,
    allow_request_daily_ladders_refresh=True)` since these functions were
    introduced — but the real `build_cards_page_context` (`mlb/cards.py`)
    only ever accepted `selected_date`, no such kwarg. Every call raised
    `TypeError`, silently swallowed by a bare `except Exception`, so the
    cards-fallback path has never actually worked in production, at any
    point before this session — this predates today's cards-primary change
    entirely; today's fix just made this dead-on-arrival path load-bearing
    for the first time, which is what surfaced it.** Every existing test
    mocked `build_cards_page_context` with a signature that accepted the
    bogus kwarg, which is exactly how this stayed hidden for however long
    it's been broken. Fixed both call sites, fixed the two test mocks to
    match the real signature, and added
    `test_cards_backed_live_lens_report_calls_real_build_cards_page_context_signature`
    (`tests/test_mlb_refresh_runner.py`) which uses `inspect.signature` on
    the REAL function instead of a hand-written mock, specifically so this
    class of drift can't hide again. Deployed as `86fbfc8e`.
  - ⚠️ **Still not fully fixed after all three deploys — one more layer
    confirmed, not yet resolved.** Post-`86fbfc8e`, the persisted worker
    report now has the CORRECT card-based shape (all the
    `_card_to_live_lens_row` fields present, confirming the TypeError fix
    landed and cards-primary is genuinely running) but `liveProps` is still
    empty, and `build_cards_page_context`'s own `source_title` came back
    `"MLB cards unavailable"` (`mlb/cards.py:5058`, gated on `summary and
    games` — `games` is provably non-empty here, so `summary` must be
    falsy). That `summary` traces to `daily_artifact_path(selected_date,
    suffix="_locked_policy")` → `daily_summary_<date>_locked_policy.json`,
    which per **#124 item 3** already feeds
    `markets.{pitcher,hitter,extraPitcher,extraHitter}Props` specifically —
    confirmed present on **web's** disk via `/api/ops/artifacts/export`
    (count 1), but that only proves web has it, not live-odds-worker (no
    endpoint exposes worker's own disk contents directly). Leading
    hypothesis, not yet confirmed: live-odds-worker's `pull_hot_artifacts`
    call pulls a narrower artifact set than web/refresh-worker (focused on
    live odds, not the full daily betting-card summary), so this file
    genuinely never reaches its disk even though #124 item 3's repair fixed
    the *transport allowlist* gap, not necessarily *which service* asks for
    it. **Deliberately stopped debugging live here** rather than keep
    redeploying during an active MLB slate (3 rounds of deploys already
    killed/re-triggered the same scoped fingerprint-change resim multiple
    times tonight, each time with explicit user go-ahead). **Next session**:
    (1) confirm whether live-odds-worker's `pull_hot_artifacts`/hot-artifact
    fetch list includes `daily_summary_*_locked_policy.json` at all — if
    not, that's the real remaining fix, same shape as #124 items 2/3 but for
    a different consuming service; (2) once confirmed fixed, re-run this
    session's exact check (`/mlb/api/live-lens` `counts.props` across live
    games, cross-referenced against `/mlb/api/cards`) to close this out;
    (3) remove the `[CARDS_BACKED_LIVE_LENS_DIAG]` prints once confirmed
    fixed and stable; (4) the frontend "Live" column fix
    (`intelligence.html`'s `displayLiveProjection`) IS confirmed correct
    and deployed — no longer falls back to the game's live total for props
    — but hasn't been visually confirmed against a real populated live prop
    row yet since props still aren't reaching the board.

Conventions:
- IDs are stable and never reused. New work appends at the next free number.
- "Validated" means confirmed against production or a test run, with the evidence
  named. An item that merely *looks* fixed is not validated.
- Prefer measurement over inference. Several items below exist because a
  plausible inference was trusted where a measurement was available.
- **A closed item lives in Done and nowhere else.** Nine items were listed as both
  open and closed before 2026-07-26; the open copies were stale but read as live
  work. When you close something, delete the open row — don't leave it.

### Reconciliation 2026-07-28

A long, multi-thread session spanning two concurrent sessions working the
same working directory (this one on WNBA live-lens/odds; "Odds/signals
monitoring" on MLB odds tracking, #124's family, and the props-flap/board-
overwrite fixes). All items below are shipped, deployed, and confirmed live
unless their own entry says otherwise.

- **Closed to [`todo_closed.md`](todo_closed.md):** none this session — no
  items reached full closure-criteria confidence; everything shipped either
  has an explicit "still open" follow-up noted in its own entry (#111's
  vendored-pipeline mechanism, #125's box-score-fallback question) or was
  itself a new item logged mid-investigation (#112-#127).
- **Fixed a real ID collision found during reconciliation**: #104 was
  double-filed (the MLB game-candidates fix and an unrelated NHL
  relative-path bug), almost certainly two concurrent sessions claiming the
  same next-free-ID simultaneously. The NHL entry (zero existing
  cross-references) was renumbered to **#127**; the MLB entry (5
  cross-references elsewhere in this file) kept #104 to avoid a wider,
  riskier rename. No other duplicate IDs found on re-scan, and #111-#127
  don't collide with anything in `todo_closed.md`.
- **This session's arc (#111-#125, #126)**: started from #100's
  consolidation handoff, then a long live chain chasing why the intelligence
  board showed stale/sparse data (#111's MLB odds-merge fix, #113/#114/#115's
  three-layer "combined board vs. stale snapshot" bug, #124's family of MLB
  odds-tracking/board-overwrite fixes from the concurrent session) before
  pivoting fully to a single user-driven thread: WNBA's live-lens page
  showing misleading/missing data for a real live game. That thread (#125)
  went through 9 follow-ups in one continuous investigation — UI
  mislabeling, decoupling projection math from odds availability, a
  market-discovery diagnostic, discovering the real fetch path was
  completely unreachable from production, a merge-layer bug discarding
  fresh live-state, a user-caught architecture violation (web calling
  OddsAPI directly instead of reading worker-written data), the real root
  cause (WNBA's scheduled fetch never requesting period markets), a
  JS `Number(null)` coercion regression, and finally the live-props-total
  gate — each one verified against the actual live production page, not
  assumed fixed. **Deliberately left open for next session**: whether
  `refresh_wnba_oddsapi_props.py`'s own worker-side period-market fast-path
  (which uses the CLAUDE.md-discouraged `_load_source_app` dynamic-import
  pattern) actually reaches `game.betting` in production now that the
  market list is fixed — not yet re-checked end to end.
- **Verify-before-trusting reminder for next session**: several fixes
  tonight (#125's follow-ups especially) were deployed and *appeared*
  correct on first check, then turned out to have a second bug one layer
  deeper (the merge-layer discard, the null-coercion regression) — worth
  remembering that "the API response looks right" isn't the same as "the
  full round trip through every consumer is right." Re-verify #125's
  remaining open item the same way: pull the real production response,
  don't infer from code reading alone.

### Reconciliation 2026-07-27

Nine items closed, one narrowed. The board is populated and correct for the
first time, so several items whose closure criteria were written months ago are
now genuinely met rather than merely believed.

- **Closed to [`todo_closed.md`](todo_closed.md):** #79, #78, #77, #75, #71,
  #68a/b, #66, #65, and **#43 — whose own criterion (`candidate_count > 0`
  *with* a snapshot timestamp) was finally met**: 27 with
  `snapshot_generated_at 2026-07-27T00:05:49Z`.
- **#68 stays open, narrowed to its MLB half, and is recorded UNPROVEN.** The
  "worker sees stubs while web yields 38" diagnosis was a **cross-time**
  comparison; measured side by side minutes later both showed 1. See the
  operational note.
- **#61's withdrawal stands**, but its residual (pregame lane empty) is real and
  still open — the board published `lane_counts {live: 27, pregame: 0}`.
- **#38 is now unblocked.** It was gated on #43/#66/#68 being open; two are
  closed and the third no longer depends on those prints. There is a lot of
  scaffolding to remove after today.
- **#71 check run:** 30 distinct IDs across the last 80 commit subjects, every
  one present in this file or the archive. No gaps.
- ⚠️ **#43 closed does NOT mean its transport is proven** — no cycle has yet
  produced a pool large enough to exercise the oversized-payload path.
- **New: #87** (filed and closed same session) — the event-sim rerun decision's
  `-ArtifactPath` argument was a stringified garbage path, not a cast, so it
  always forced a rerun. See `todo_closed.md` for the fix and the parser-level
  repro; see Operational notes below for the reusable PowerShell lesson.
- **New: #88** (filed and closed same session) — `refresh_ncaaf_oddsapi.py`
  (from `ce48b4de`) had a mangled `_base_norm` (normalized every team name to
  `""`) and crashed in artifact-root-only mode (the runner's actual production
  call shape from `refresh_odds_sources.py`) because `_prediction_files`
  assumed a `data/` subdirectory the flat bundle layout doesn't have. Both
  fixed; see `todo_closed.md` for detail. ⚠️ Not yet observed fixed against a
  live OddsAPI key in production — confirm the orchestrator's
  `ncaaf_lines_snapshot` step on its next real run.
- **New: #89** (filed and closed same session) — `scripts/migration_gate.py`'s
  `evaluate_protected_local_resolvers()` had gone stale against commit
  `757952e1` ("Refactor WNBA odds path resolution", 2026-06-28): NBA's and
  NHL's `processed_path`/`scoreboard_snapshot_path`/`slate_summaries` now
  resolve their root through `odds_control_plane.current_odds_root_for_sport`,
  which imports `preferred_source_roots` in its own module — so the gate's
  `patch("...nba.sources.preferred_source_roots", ...)` /
  `patch("...nhl.sources._source_roots", ...)` were patching bindings nothing
  reads anymore, and the gate **unconditionally reported 3 violations**
  (`runtime_dependency_ok` permanently `False`). Retargeted both to
  `patch("syndicate.features.shared.odds_control_plane.preferred_source_roots", ...)`.
  See `todo_closed.md` for detail, including the confirmed real contract
  change (NBA's `processed_path` lost its multi-root existing-file fallback —
  matches the codebase's "no source-app fallback" direction, not a bug).
  See #90 for a real inconsistency this surfaced.
- **New: #91** (filed, open) — a same-session `git status` review (prompted by
  a "commit all pending updates" request) found a large body of
  **already-written, uncommitted intelligence-query fixes** with no todo entry
  at all, distinct from #74/#87/#88. Committed as-is in `0250ac82` after
  manual diff review (full test suite was interrupted, see #74's row), so
  these are shipped-but-unvalidated-this-session, same caveat as #74:
  - `run_intelligence_query` (intelligence.py): an explicitly requested
    subject ("Compare Judge vs Ohtani") now survives the edge-quality gate
    even if it wouldn't clear the board threshold on its own; the gate still
    applies to everything the question didn't name.
  - Same function: odds-window preferences (`plus_money_only`,
    `candidate_odds_min/max`, `favorite_floor`) and timing preferences
    (`live_only`/`pregame_only`) now filter the flat `recommendations` list,
    not just parlay legs — previously "plus money only" still served
    minus-odds picks outside a parlay.
    build_parlays (intelligence_parlay_runtime.py): honors the requested
    min/max leg count as-is instead of clamping both to `[2,3]` — a 4-leg
    request was silently rebuilt as 3-leg tickets.
  - `response_builder.py`'s `_frontend_parlay` was whitelisting 5 keys and
    silently dropping `label`/`leg_count`/`combined_odds`; now additive over
    the full parlay payload, matching the opportunity-alias pattern already
    used elsewhere in the same file.
  - `syndicate/blueprints/intelligence.py`'s fresh-compute path now calls
    `_hydrate_board_response_payload` (every cached-read path already did) —
    without it, a fresh compute and a cache hit served different top-level
    shapes for `parlays`/`recommendations`/`portfolio`.
  - `_attach_intelligence_response_aliases` now backfills `american_odds`/
    `subject_key`/`market_key` on engine recommendations, which previously
    only pool-serialized candidates carried.
  - A new `_display_subject_names` helper maps lowercase subject-matching
    keys back to real display casing ("Aaron Judge", not "judge") for the
    public `parsed_request.requested_subjects` field.
  - All three Render services (web, refresh-worker, live-odds-worker)
    redeployed to `0250ac82` same session, confirmed `live` and on-commit via
    `/api/ops/version`; no MLB sim was in flight at trigger time (checked via
    `/api/ops/live-refresh/state` immediately before deploying).
- **New: #92** (filed, shipped this session, commit pending) — continuing the
  overnight test-fixing pass that produced #91: fixing the ~29 originally-
  failing `test_intelligence.py` cases one at a time surfaced several more
  real production defects, each verified by making the specific failing test
  pass and (where practical) a targeted unit test on top:
  - 🔴 **MLB's "best home run matchups" feature has likely never surfaced a
    candidate on the real board.** `_mlb_home_run_candidates_from_artifact`
    (intelligence.py) hardcodes `"odds": "-"` and `"projected": "-"` for
    every HR-target candidate it has ever produced — there's no book line to
    project against, that part is correct — but `normalize_candidate`'s
    projection scan never looked at `hr_probability` (the model's actual
    signal), only at `model_probability`/`edge`/etc., so every single
    HR-target candidate was pruned at classification as
    `missing_projection_or_odds`. Fixed by setting `model_probability` from
    `hr_probability` at candidate-build time — the correct semantic slot,
    not a workaround (distinct from #68's explicit "do not add `confidence`"
    warning, which was about a phantom signal masking dead MLS data; here
    the field is real and always populated). Added a direct unit test
    (`test_mlb_home_run_artifact_candidates_survive_classification`) since
    the existing integration test mocks the builder out entirely and could
    never have caught this.
  - `_candidate_betting_rank_key` (governs the flat `recommendations` list,
    used by `_balanced_recommendation_order` and
    `_greedy_low_correlation_selection`) disagreed with
    `build_intelligence_board_contract`'s card sort (#73) on two things it
    had already gotten right there: `advanced_ready` now leads the tuple
    (was absent), and `score` — which already folds in edge, confidence,
    tier, and the risk-profile/market-focus adjustments — now sorts above
    raw `edge`/`confidence` instead of below them. Confirmed regression: a
    "highest confidence" (→ conservative risk profile) query still ranked a
    38%-confidence +320 longshot above a 64%-confidence -135 favorite,
    because raw edge (12.8% vs 2.5%) was compared before the correctly
    risk-adjusted score. `source_summary_score` added as a final tiebreaker,
    same placement/reasoning as the board-contract sort (folding it into
    `score` directly was tried there and reverted — regressed the
    advanced-ready-inputs test).
  - `_frontend_recommendation` (response_builder.py) prefixed every
    recommendation's rationale with "Advanced drivers in play" whenever
    `advanced_inputs`/`advanced_context` were merely *present* — even when
    `advanced_ready` was explicitly `False`, i.e. attached-but-untrustworthy
    context got the same confident framing as genuinely ready inputs. Now
    gated on `advanced_ready` itself; the not-ready case surfaces the real
    gap ("Readiness is partial because N advanced inputs are missing or
    unpublished") instead.
  - `_mlb_subject_prop_candidates_from_artifact` (matches a top-props
    artifact row's player name against the question, independent of the
    "top N"/explicit-market phrasing `_mlb_market_prop_candidates_from_artifact`
    requires) was fully implemented but never called from anywhere. A real
    subject question ("What does Brandon Young's matchup look like") with
    data sitting in the artifact produced zero candidates. Wired into
    `_collect_candidates` for MLB; self-gated by the function's own
    whole-word name match, so it's a no-op for every query that doesn't
    name a rostered player.
  - `structured_response` (the engine's summary/key_factors/risks/confidence
    bundle, built by `_build_structured_response` in
    `pipeline/intelligence_pipeline.py`) was set on the `IntelligenceResult`
    but never promoted from the nested `analysis` object to the query
    response's top level — same shape of gap as #91's `parlays`/
    `recommendations`/`portfolio` promotion, just a field that hadn't been
    caught yet. Fixed in both `_compute_response`
    (`pipeline/intelligence_state.py`) and the cached-read hydration path
    (`_hydrate_board_response_payload`), matching the existing pattern for
    consistency between a fresh compute and a cache hit.
  - Additive alias-layer extensions (`_normalize_opportunity_item`,
    intelligence.py): `market_fit_score` (was nested under
    `candidate["market_fit"]`, several read sites already flattened it back
    out ad hoc), `rationale` (`_candidate_rationale` existed but only
    `_candidate_summary` — itself dead code, nothing serves through it —
    called it), `advanced_readiness`/`advanced_ready`/
    `missing_advanced_inputs` (same dead-code-only-caller pattern).
  - `scripts/fetch_mlb_weather.py`'s `_todays_home_teams` checked a filename
    (`oddsapi_game_lines.json`, no date suffix) that has never existed under
    `daily/snapshots/<date>/`; the real writer and its snapshot mirror both
    use `oddsapi_game_lines_<date_slug>.json`. Confirmed against production:
    yesterday's file exists exactly where the fix now looks, today's simply
    hadn't been produced yet at the time of checking. Zero prior test
    coverage of this function; added two regression tests.
  - `reports/steam/steam_events_<date>.json` (#83's bounded, capped-at-200
    steam record, carries `capture_phase` directly) added to
    `HOT_ARTIFACT_PATTERNS` so it's reachable through the existing
    `/api/ops/artifacts/export` debug endpoint — deliberately NOT the raw
    per-observation lifecycle log (`data/odds_events/<date>.jsonl`), which
    hit 1.2GB in a single day (see `odds_lifecycle.py`) and allowlisting it
    would reproduce the exact oversized-payload pattern #43/#50/#54 already
    cost three outages over.
  - Two tests in `tests/test_live_refresh_loop.py` carried the
    long-standing "two known-failing, accepted baseline" label
    (`test_create_app_starts_shared_live_refresh_loop*`) — both were
    genuinely fixable, not baseline noise: (a)
    `test_defers_while_the_board_build_is_computing` depended on a
    disk-persisted consecutive-defer counter
    (`reports/live_refresh_loop/last_mlb_sim_pipeline_defer.json`) that had
    been accidentally committed mid-threshold (`count: 5`) by the same
    pollution incident below, permanently flipping which branch the test
    hit regardless of what it mocked — now isolates the counter read/write.
    (b) `test_create_app_starts_shared_live_refresh_loop_on_render_web`
    asserted the opposite of the documented, deliberate web/worker split
    (render.yaml pins `SYNDICATE_ENABLE_LIVE_ODDS_REFRESH_LOOP=false` on
    web specifically) — renamed and inverted to pin the actual contract.
    Full file now 159/159.
  - `tests/test_refresh_worker.py::test_main_starts_intelligence_state_background_loop`
    never set `SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP`, so the
    code path it asserted on never ran — same failure mode present in the
    very first traceback taken at the start of this session, so pre-existing
    and unrelated to any change made tonight.
  - ⚠️ **Validation gap, same caveat as #91 and #74**: every fix above was
    verified by making its specific failing test (plus, where added, a
    direct unit test) pass in isolation — confirmed via targeted `pytest`
    invocations, not a completed full-file sweep. `tests/test_intelligence.py`
    alone takes ~20 minutes; two full-sweep attempts this session were
    interrupted (once by an unrelated background-session incident, once by
    the same "tests taking too long" concern that closed out #91's
    validation). **The test suite's own runtime is now a explicit followup**
    — flagged by the user directly: a single file taking 20+ minutes is
    unreasonable and blocks exactly this kind of end-of-session validation.
    Next session should run `pytest --durations=20` to find the actual worst
    offenders (suspects, from tonight's pattern: tests that exercise the
    full `run_intelligence_query` pipeline end-to-end with no mocking of
    candidate generation/scoring/enrichment) before attempting another full
    sweep.
  - 🔴 **Separate incident, same session: a background task spawned for a
    narrow fix ("update stale NBA/NHL resolver checks in migration gate")
    committed the entire working tree instead** — 166 files of local
    test-run/dev-session scratch state (`reports/live_refresh_loop/mlb_sim_runs/`
    per-run dumps, dated `intelligence_state_2026_07_18..27` snapshots,
    schedule-adapter scratch), plus `data/prediction_ledger.json`
    (+84,909 lines — #72 already removed the production write path, so this
    can only be local pytest runs) and `data/odds_events/*.jsonl` (the same
    test-leakage-into-real-paths pattern #91's session independently found
    in `tests/test_odds_refresh_tracking.py`, here landing in git instead of
    just on disk). Pushed to `origin/main` and triggered a full redeploy of
    all three Render services before being caught. Production impact
    checked and was benign — all three services came up `live` cleanly, and
    `sim_run_status.state` was `finished` (not mid-run) at trigger time, so
    nothing was killed — but the pollution itself was real and now
    permanent in git history up to the revert. Reverted in a dedicated
    follow-up commit (166 files removed, 14 legitimately-tracked `reports/`
    files restored to pre-pollution content, `.gitignore` extended so the
    categories can't silently reaccumulate); the actual code/test fixes
    from that commit (the migration-gate resolver retargeting, #91's
    fixes) were reviewed and left intact. **Lesson for any future spawned/
    background session with a narrowly-scoped assignment: commit and push
    only the files the assignment actually touched — never a blanket
    `git add -A`/`git commit -a` sweep of the whole working tree.**
- **New: #93** (filed, shipped this session, commit pending) — user reported
  the home-page board showing WNBA-only for today (0 MLB despite a 12-game
  slate) with duplicate rows on WNBA's picks. Investigation found two
  distinct, unrelated bugs; both fixed and unit-tested, no production
  incident (caught before either shipped further than tonight's session):
  - 🔴 **The real MLB-missing cause: a date-matching guard bug in the core
    board-serving cache, not a keyvalue-size regression as first suspected.**
    Production has `SYNDICATE_LOOK_AHEAD_ENABLED=true` (the deliberate
    "show tomorrow's slate when today has none" feature — confirmed
    intentional, not itself a bug). The background loop's own recurring
    *default* query payload (the one serving plain "today" requests) carries
    no explicit `"date"` field by design (`_stale_snapshot_reason`: a
    dateless payload is the legitimate "today" default) — but with
    look-ahead on, that same dateless cycle can internally resolve to
    **tomorrow's** date instead. Observed live: every sport's
    `context_label` read `2026-07-28` in one cycle (only WNBA had games,
    hence exactly 29 WNBA-only candidates), while the stored request
    payload's own `date` field stayed unset. `IntelligenceStateService
    .read_latest_response`'s `latest_key` fallback (`pipeline/
    intelligence_state.py`) only ever compared `requested_date` against the
    *stored payload's* nominal date, so `latest_date is None` was read as
    "matches any requested date" — true for the common case, but it let a
    look-ahead-shifted dateless snapshot silently stand in for an *explicit*
    same-day request too. Confirmed via production logs: the served
    `/api/intelligence/query` response stayed frozen on a WNBA-only,
    2026-07-28 snapshot for 20+ minutes across multiple fresh 81-candidate
    (all-sport, 2026-07-27) compute cycles that never got served. This
    pattern predates today's deploy (log evidence back to 15:01Z, hours
    before) — not a regression from tonight's fixes. Fixed by adding
    `_effective_snapshot_date` (falls back to the *response's own* computed
    `selected_date` only when the payload itself is silent) and using it in
    both `latest_key`-fallback branches instead of the payload-only check.
    Two tests added (`test_read_latest_response_rejects_dateless_latest_that
    _actually_computed_a_different_date`,
    `..._still_serves_dateless_latest_that_really_computed_today`) —
    the first confirmed to fail against pre-fix source (reverted the fix,
    reran, watched it fail) before being counted as a real guard.
  - **WNBA rank-card rows were duplicated on the board**: every game-level
    pick (ATS/Total) appeared twice — once correctly typed via
    `game_market_recommendations`, and again as a fake "prop" candidate with
    `market: "betting card"` and `player_name` wrongly holding the team/line
    text instead of an actual player. Root cause:
    `_pregame_prop_rows_from_betting_card` (`syndicate/blueprints/home.py`)
    pulls a sport's **entire** ranked betting-card list — which legitimately
    mixes player props with team-level game bets — and force-labels every
    row `heading_override="Betting Card"` regardless of its real market,
    because the rank card never exposed its true market code (only used as
    an `eyebrow` fallback, dropped otherwise). Those mislabeled rows then
    got promoted to `candidate_type="prop"` by `_prop_candidate_from_item`
    (`syndicate/features/intelligence.py`), duplicating whatever
    `_game_candidates_for_sport` already built correctly for the same pick
    — evading the existing #29 cross-type dedup because their
    `market`/`candidate_type` genuinely differ from the real entries (not
    the "different arity, same key" bug #29 fixed). MLB is unaffected
    (`_pregame_prop_rows_from_betting_card` explicitly returns `[]` for
    `slug == "mlb"`); NBA/NHL share the same helper and were **not**
    verified either way — worth a look if the same duplication is ever
    reported there. Fixed by (a) exposing the pick's real market on WNBA's
    rank card (`_card_from_pick`, `syndicate/features/wnba/picks.py`, was
    computed but discarded) and (b) filtering game-level markets
    (ats/total/moneyline/spread) out of the rank-card list in
    `_pregame_prop_rows_from_betting_card` before it reaches the prop-row
    builder — deliberately *not* touching `_prop_rows_from_rank_cards`/
    `_prop_item_from_rank_card` itself, which soccer's props path relies on
    never skipping a card it's given (`_prop_rows_from_rank_cards` zips
    `cards`/`rows` 1:1 by index for `match_id` lookup). Two tests added
    (`test_is_game_level_rank_card_market_classifies_team_bets`,
    `test_pregame_prop_rows_from_betting_card_drops_game_level_cards`).
  - ⚠️ Also found, not fixed: three `test_intelligence.py` tests named for
    fast failure/degradation paths (`..._returns_fallback_when_query_raises`,
    `..._degrades_when_queue_refresh_fails`, `..._forwards_policy_override`)
    took 993s/790s/319s respectively — 35 of the file's ~37-minute total
    runtime — via `pytest --durations=20` per #92's followup. Something in
    each isn't actually mocked the way the test name implies; worth
    investigating before the next full-suite validation attempt. Full
    `test_intelligence.py` run: 163 passed, 10 failed — the 10 failures were
    not investigated this session (pre-existing per #91/#92's known ~113
    failures, not confirmed related to tonight's changes).
- **New: #90** (filed, open) — NBA's `available_dates()` still scans **every**
  preferred artifact root (via `nba.sources._artifact_roots()`), but
  `processed_path()`/`live_snapshot_path()` (post-`757952e1`) only ever build a
  path in the *primary* root. If NBA is ever configured with more than one
  preferred root (e.g. `SYNDICATE_DATA_ROOT` set alongside the local mirror),
  `available_dates()` can advertise a date whose artifact only exists in a
  secondary root, and `processed_path()` for that date will 404 against the
  primary root instead. Invisible today because production only has one NBA
  root; worth a look before adding a second one.
- **New: #94** (filed, shipped this session as Phases 1/3/4/5, **dark-launched — no
  production behavior change yet**) — Layer 2 board redefinition, per explicit
  user direction after #93: stop patching the single-date "latest slot" model
  (three successive fixes tonight — `6c978398`/`7b5d82af`/`18ffd26b` — closed the
  specific corruption bug but left the underlying "one ambiguous current date"
  model in place). New default: the board shows everything currently relevant
  across sports/dates, date becomes an optional filter, not the storage/query
  key.
  - **Storage decision:** built on the legacy `_watched_payloads`/`_snapshots`
    per-date store (proven live, correctly keyed as of tonight's `18ffd26b`),
    **not** the canonical `board_state_<date>.json` store — that one is
    disabled in production (`SYNDICATE_INTELLIGENCE_CANONICAL_BOARD_STATE=false`)
    and blocked on its own unresolved #39 (doubled boot memory). Confirmed
    `SYNDICATE_LOOK_AHEAD_ENABLED=true` is the real production value (a
    `render.yaml` "deliberate overrides" comment claiming `false` is stale
    docs, not reality — worth a one-line fix separately).
  - **`pipeline/intelligence_state.py`:** `_default_board_window_dates()`
    (today + `SYNDICATE_INTELLIGENCE_BOARD_WINDOW_DAYS`, default 3, clamped
    1-7) + `IntelligenceStateService._ensure_default_board_window_watched()`,
    called every `_background_loop()` iteration — today re-queued every
    cycle, today+1/+2 throttled to `SYNDICATE_INTELLIGENCE_BOARD_WINDOW_SLOW_REFRESH_SECONDS`
    (default 300s) so watching a 3-day window costs "1 today-cadence build +
    a slow trickle of ≤2 more", not a flat 3x multiply of the OOM-sensitive
    `_build_candidate_pool`.
  - **Two real bugs found and fixed while building this, both pre-existing
    (not introduced by the redesign), both would have actively corrupted data
    the instant the board-window watch set started computing extra dates:**
    (1) `write_latest_intelligence_state`'s daily file path
    (`_intelligence_state_daily_paths`) was keyed by **wall-clock day of
    writing**, not the content's own `selected_date` — a today+1 compute
    landing on "today" (wall clock) would silently overwrite today's own
    daily file and the global `INTELLIGENCE_STATE_PATH`/`BOARD_SNAPSHOT_PATH`
    "latest" pointers. Fixed: `_intelligence_state_daily_paths(selected_date)`
    now accepts the content's real date; global "latest" files are only
    written when the content represents today-or-dateless. (2)
    `self._latest_key` promotion in `_background_loop` used to promote to
    "whichever date the loop just processed", which would make it flip-flop
    across today/tomorrow/day-after now that several dates are watched
    simultaneously — gated with a `represents_today_or_dateless` check so it
    can never again drift off today.
  - **`read_combined_intelligence_response()`** (new, `pipeline/intelligence_state.py`):
    read-only union of already-computed per-date responses, hard invariant
    "never calls `_build_candidate_pool`" (guarded by a dedicated regression
    test). Stamps `game_date`/`source_board_date` per candidate via a new
    `resolve_candidate_game_date()` helper (`syndicate/features/shared/intelligence_contracts.py`)
    that also fixed a real, independent bug in `UniversalCandidate.from_raw`:
    every candidate from one overview build used to share the SAME date tag
    (`payload["selected_date"]`/`["date"]`), never its own game's date.
  - **`syndicate/blueprints/intelligence.py`:** new
    `SYNDICATE_INTELLIGENCE_COMBINED_BOARD_DEFAULT` flag (default `false`,
    dark-launched like the canonical-board-state flag). `intelligence_query_api`/
    `intelligence_home` check for an explicit `date` in the **raw** request
    (before any default-injection) — explicit-date requests are byte-for-byte
    unchanged regardless of this flag; only a genuinely dateless request with
    the flag on gets the combined response.
  - **`syndicate/templates/intelligence.html`:** new "All" day tab (default),
    Today/Tomorrow/All are now client-side filters over one fetched response
    (matching the existing sport/market/edge tab pattern) instead of each
    triggering its own `/api/intelligence/query` round trip. The free-text
    date input is still a real server fetch — the explicit override for a
    date outside the warm window.
  - **Explicitly deferred (Phase 2, not this session):** week-scoped sports
    (NFL/NCAAF need a "current week" window, not a rolling day-count; soccer's
    available-date probe is per-league) — can't be validated live this
    season, tracked via a code-comment seam in `_default_board_window_dates`
    rather than bolted into the daily-window logic.
  - Full plan: `C:\Users\tempadmin\.claude\plans\quirky-plotting-hummingbird.md`.
  - **Test coverage:** ~35 new tests across `tests/test_intelligence_state.py`
    and `tests/test_intelligence_contracts.py`, all confirmed non-vacuous
    (failed against pre-fix source). Fixed 3 pre-existing, unrelated
    background-loop tests that this session's fuller `_background_loop()`
    exercise exposed as broken by real wall-clock time passing (hardcoded
    2026-06-xx dates hit `_watched_payload_eviction_reason`'s stale-date/
    stale-limit checks) — those tests would have hung forever pre-#93-follow-up
    (nothing else queued to fall back to), not failed loudly; confirmed
    unrelated to the board redesign itself. Full `test_intelligence_state.py`
    + `test_intelligence_contracts.py`: 201 passed, 0 failed.
  - ⚠️ **NOT YET VALIDATED IN PRODUCTION.** The flag is off; Phases 1/3
    (background-loop seeding, the two write-side fixes) ARE live once
    deployed regardless of the flag, since they're unconditional — watch
    `_diag_log_all_process_memory`/cycle-timing logs for the new today+1/+2
    builds for ~24h before flipping `SYNDICATE_INTELLIGENCE_COMBINED_BOARD_DEFAULT`
    on.
- **New: #95** (filed, shipped, live) — user reported the exact #93 symptom
  recurring right after #94 deployed: WNBA-only opps for tomorrow served
  under today's date. Root-caused live via `/api/ops/intelligence/candidate-trace`:
  today's own candidate pool was genuinely healthy (128 real MLB candidates)
  at the moment a `force_refresh` request for `date=2026-07-27` still rolled
  over and returned 24 WNBA-only candidates dated `2026-07-28`. Cause: the
  rollover triggers in `_compute_board_publication_response` and
  `_compute_response` (`pipeline/intelligence_state.py`) checked only "does
  the resolved date equal today", never "did the caller explicitly ask for
  that date" — a single transient empty read for today (plausible under
  tonight's heavy concurrent MLB-sim load) substituted tomorrow's slate for
  an **explicit** request, not just the dateless default rollover was
  originally meant to cover. Fixed by capturing whether the caller's own
  payload carried an explicit date and gating both triggers on its absence.
  Confirmed via the same two pre-existing rollover tests that their
  "dateless default" scenario was never actually reachable (a payload with
  no `date` key resolves `selected_date` to `None`, which can never equal
  `central_today_iso()`'s string return) — replaced with a test documenting
  that plus two new regression tests for the real, reachable bug. Full
  `test_intelligence_state.py` + `test_intelligence_contracts.py`: 202
  passed, 0 failed. **Under #94's board-window model this makes rollover
  fully dead code in practice — every payload the board-window watch set
  queues now carries an explicit date, and no remaining caller sends a
  genuinely dateless one either — full removal is a lower-risk follow-up,
  not done here** to keep this fix minimal while production was actively
  wrong.
- **New: #97** (filed, shipped, live) — two follow-ups from chasing why the
  board still hadn't self-healed after #95 deployed:
  - 🔴 **Found and fixed a second, more severe bug while investigating**:
    `_ensure_default_board_window_watched()` (#94's board-window seeding)
    sat completely UNGUARDED at the top of `_background_loop`'s while body
    — only ever exercised against mocks in unit tests, never real
    production data/timing. An uncaught exception there kills the entire
    background thread instantly, before the loop even reaches its
    pending-queue sync/process step. Proven with a test (fails against
    pre-fix code: the loop dies before ever processing a persisted pending
    payload). Wrapped in the same "a failure here must never kill the loop"
    pattern already used elsewhere in this function. **This turned out NOT
    to be tonight's active cause** — a parallel session's log access showed
    the loop genuinely alive and cycling every 70-90s throughout, not
    dead — but the gap itself was real and is worth having fixed
    regardless.
  - 🟡 **Open, not a bug**: confirmed via `/api/ops/intelligence/candidate-trace`
    (read_only=true) and a parallel session's log pull that `self._latest_key`
    sat frozen at one pre-#95 snapshot (24 WNBA candidates, computed
    2026-07-27T20:58:50Z) for over an hour post-fix, **because today's own
    candidate pool has been genuinely computing near-empty on every
    attempt since ~20:58**, not because of any remaining promotion/rollover
    bug. Real trace at 21:52:05Z: `{"stage": "post_dedupe_and_classify",
    "normalized_in": 14, "classification_pruned": 9,
    "classification_reasons": {"missing_projection_or_odds": 9},
    "dedupe_pruned": 5, "total_candidates": 0}` — only 14 candidates ever
    entered classification (a thin pool, not a memory-truncated one; ruled
    out memory contention directly — refresh-worker sat at 218-255MB of a
    4096MB container the whole window, and zero `MEMORY_GUARD_ABORT` log
    lines). `self._latest_key` correctly refuses to regress a good board
    with an empty one (the existing, deliberate anti-#8 rule), which is
    why the board visibly hasn't changed even though the fix is working as
    designed. Most likely explanation: it's late evening Central and a lot
    of tonight's MLB games are probably final by now, so there's
    legitimately little live/pregame content left — matches the #68
    investigation's exact failure shape from earlier this project's
    history. **Not chased further tonight** — worth a look with
    `/api/ops/intelligence/candidate-trace?date=<today>` next time this
    recurs, checked against the actual live MLB game states at that hour,
    before assuming a new bug.
  - **Also found and cleaned up, unrelated to any of the above**: ~6.7GB of
    accumulated local test/dev-server pollution in `reports/intelligence/`
    on this dev machine (`board_snapshot*.json`/`query_state_cache.json`/
    dated `intelligence_state_*` — all deliberately gitignored, built up
    across many past local sessions, one single stray file alone was
    1.89GB) was making 3 unrelated, pre-existing tests
    (`test_query_endpoint_*_default_cache_is_empty*`) intermittently pick up
    stray real candidate data instead of their own mocks. Confirmed via an
    isolated `git worktree` that this was never a code regression — those 3
    tests pass cleanly there and now pass locally too post-cleanup. Never
    touched git or production; local-machine-only. ⚠️ Mid-cleanup, a `rm`
    over-matched and briefly deleted several **git-tracked** dated
    `board_snapshot_*.json`/`intelligence_state_*.json` files that happen
    to match the gitignore glob despite being committed before the rule
    existed (gitignore doesn't retroactively untrack) — caught immediately
    via `git status` showing them as deleted-tracked rather than
    untracked, restored via `git checkout --` before anything was
    committed. No damage, but a reminder to always diff `--ignored` output
    against plain `git status` before bulk-deleting anything under a
    gitignore pattern, even in directories believed fully ignored.
  - Full `test_intelligence_state.py` + `test_intelligence_contracts.py`:
    203 passed, 0 failed.
- **New: #98** (filed, **still open** — a fix shipped for it via #100 but is
  **not confirmed working live**, see the end of this entry) — user reported
  the board showing MLB live-only
  (0 pregame) with WNBA gone entirely, right after #97 shipped. Two separate
  findings:
  - **WNBA vanishing is correct, not a bug.** Checked `/api/board/game-chips`
    ground truth: WNBA's only game today (SPO @ COOP) is already `final`. No
    live/pregame WNBA game exists today, so it correctly has nothing to show
    — this is the #94 redesign's date-scoping working as intended, not a
    regression.
  - 🔴 **MLB pregame is a real, confirmed gap — reopens the "genuinely open"
    half of #68's 2026-07-26 note** ("`pregame_count` is 0 while MLB has 10
    `preview` games... worth a look on a fresh slate," never chased at the
    time). Ground truth right now: 8 MLB games genuinely still pregame, 3
    live, 1 final — but the board serves `candidate_count: 3`, all live, zero
    pregame. A parallel session's log pull (`INTEL_TRACE post_dedupe_and_classify`)
    confirmed this is real, not a thin slate: `normalized_in: 16,
    classification_pruned: 8 {missing_projection_or_odds: 8}, dedupe_pruned: 5`
    — the same failure shape as #68's earlier live-candidate truthiness bug
    (`_safe_text(0.0, "") == ""`, so a legitimate zero projection read as
    "absent"), but that fix only touched `_append_game_bet_candidate`'s
    live-game path (`_candidate_value_is_present` in
    `_classify_candidate_with_reason`) — never the pregame path.
    **Narrowed but not root-caused tonight**: `_mlb_candidate_live_state`
    (`syndicate/features/intelligence.py:4424`) correctly excludes `"warmup"`
    from `is_live` (confirmed real production data: BAL @ DET, a genuine
    pregame/warmup game, reports `status.abstract: "Live"` /
    `status.detailed: "Warmup"` from MLB's own API — an easy trap for anyone
    checking `abstract` alone) — **but this function is applied downstream,
    in `_apply_live_state_context_to_candidates`, which mutates an ALREADY-BUILT
    candidate list.** It cannot be gating whether a pregame candidate gets
    created in the first place. Also ruled out "pregame candidates never get
    a projection" as a blanket explanation: `predictions` on the same BAL @
    DET game carries real, non-zero `win_prob`/`runs_mean` values at the
    `full`/`first1`/`first3`/`first5` level. **Next concrete step**: find the
    actual MLB-specific pregame candidate-builder in
    `syndicate/features/intelligence.py` (reads `predictions`+`markets`+
    `status.abstract` directly — MLB does not go through the generic
    `_game_bet_candidates_from_game` path in `home.py`, which reads
    `game_market_recommendations`/`betting`/`gameMarkets` keys that do not
    exist on the real `/mlb/api/cards` payload) and check whether its output
    field names for a pregame candidate's projection actually match what
    `normalize_candidate`'s field-scan order expects — a name mismatch would
    explain real, non-zero predictions still classifying as
    `missing_projection_or_odds`, without needing another truthiness bug.
    Same methodology #68 used successfully: real production payload
    (`/mlb/api/cards?date=<today>`), local code, no deploy, no waiting for a
    cycle — and check `context_label` on every trace line, since a
    look-ahead probe for tomorrow fires right after most low/empty-today
    cycles and is easy to misread as a bad "today" number (see #24/#65's
    history on this exact confusion).
  - ⚠️ **Also: a production OOM incident, self-inflicted while diagnosing
    the above.** `/api/ops/intelligence/candidate-trace` (the NON-read-only
    variant) directly calls `build_intelligence_overview`/
    `_build_candidate_pool` inside a web-service Flask route — a deliberate
    debug exception to this repo's "web does no heavy computation" rule (see
    its own code comment), meant to replicate refresh-worker's path on
    demand. Calling it with `sport=mlb` under tonight's heavy concurrent
    MLB-sim load OOM-killed the web service (`srv-d88ahvrbc2fs73eodu30`,
    2Gi limit — refresh-worker runs the same class of work on 4Gi).
    Self-recovered in ~19s (Render's supervisor auto-restarted it); no
    lasting damage, only the web service was hit. **Do not call this
    endpoint's non-read-only form against production under load again** —
    use `read_only=true` (cheap, no compute, just reads the persisted
    state/board_snapshot files) for anything that doesn't specifically need
    a fresh synchronous candidate-pool build, and prefer asking for a
    refresh-worker log pull over triggering one of these on web at all.
  - ⚠️ **Live-checked post-#100-deploy, 2026-07-27T19:38 CDT (~10-15 min
    after `110461f6` went live): still `pregame: 0`, despite 3 genuine
    pregame MLB games confirmed via `/api/board/game-chips` at that exact
    moment** (HOU @ LAA, BOS @ ATH, MIL @ SF — West-coast late games).
    #100's own fix (`model_probability` stamping in
    `_append_game_bet_candidate`) may simply need more background-loop
    cycles to reach a fresh compute, or may not be the full fix — **not
    determined this session**. Do not mark #98 closed/validated on #100's
    writeup alone; re-check `/api/intelligence/query` (safe,
    `force_refresh:false`) against `/api/board/game-chips` ground truth on
    a fresh pregame slate before closing.
- **New: #99** (filed, shipped this session, **commit pending**) — user
  reported MLB K-prop targets stuck at 5 rows and pitcher badges missing on
  a number of game cards. Root-caused via production reads (no deploy
  needed): the odds and sim pipelines are both healthy —
  `oddsapi_pitcher_props_<date>.json` refreshes on schedule and the MLB
  daily-sim reruns on fingerprint changes — but only 5 of today's 24
  starters had a book-posted strikeout line at the times checked (confirmed
  by two independent K-ladder-targets rebuilds ~40 minutes apart landing on
  the exact same 5 pitchers; odds prices drifted, the roster of who-has-a-
  line didn't). That part is expected pregame-cadence behavior, not a bug.
  Two real code defects found and fixed while investigating, both in
  `vendor/mlb_bettingv2/tools/daily_update_multi_profile.py`:
  - **K-ladder-targets had no protection against a scoped/partial resim
    regressing a richer existing artifact.** Unlike HR-targets
    (`_prefer_richer_hr_targets_doc`/`_hr_targets_doc_quality`, comparing
    `(rows, games, source_priority)` and keeping whichever whole document is
    bigger), the K-ladder write path (`:6319`) unconditionally overwrote
    with whatever the current run's scoped `sim_dir` + live odds snapshot
    produced, as long as it had any rows at all — no comparison against
    what was already published. Added `_k_ladder_targets_doc_quality`/
    `_prefer_richer_k_ladder_targets_doc` mirroring HR's pattern exactly and
    rewired the write block to match. Verified with synthetic inputs: a
    smaller scoped rebuild now correctly keeps the richer existing doc, a
    genuinely bigger rebuild still replaces it.
  - **The displayed summary for both K-targets and HR-targets led with
    non-explanatory restatements of the model's own math, not real
    drivers.** `_k_ladder_target_support` (`:3557`) generates two of its
    three reasons by literally restating the pick's own probability/edge
    numbers ("Modeled strikeout total clears X..." / "Model favors the over
    by Y points..."), and because those were prepended first, they
    dominated `k_target_summary` (the first-two-reasons join) on every row,
    crowding out the seven real BvP/opponent-team/recent-form/Statcast/
    pitch-mix generators that already existed further down the list. Same
    bug, more literal example, in `_hitter_hr_target_support` (`:2920`):
    "He is tracking toward a premium lineup slot (4)" and a bare PA-
    opportunity line led ahead of every Statcast/xwoba/exit-velo/pulled-air/
    platoon/pitch-type/park signal — the "just because he's hitting
    cleanup" pattern the user named directly. Fixed both by moving the
    generic-restatement/opportunity/lineup blocks to append last (addition
    is commutative, so this changes zero score math, only reason-TEXT
    order); also added a weather reason sentence for HR (`weather_hr_mult`
    was already scored but never explained in the reason text). Verified
    with synthetic inputs that Statcast reasons now sort ahead of the
    generic lines in both functions.
  - **Weather/park traced end-to-end this session** (an Explore agent did
    the tracing): live MLB StatsAPI gameday weather is genuinely wired into
    HR reasoning (`weather_hr_mult`, real, not dead code) via a roster
    snapshot → sim join. That is a **different** pipeline from #84's newer
    NWS-based `scripts/fetch_mlb_weather.py` — its
    `data/weather/weather_<date>.json` still isn't joined into any
    prediction, confirming #84 is still accurate today. Park factors: the
    real Statcast-derived generator
    (`vendor/mlb_bettingv2/tools/datasets/build_park_factors_from_raw.py`)
    exists but its output was never generated or committed, so
    `park_hr_mult` runs on a crude geometry fallback today (self-documented
    in `sim_engine/models.py:169-188` as "not a true historical park
    factor"). Neither weather nor park factors are wired into
    K-target/strikeout reasoning at all. User explicitly chose to leave
    this as-is (not generate the park-factors dataset, not pull in #84's
    weather artifact) rather than expand scope this session.
  - ⚠️ **Not yet committed or deployed.** Verified via `py_compile` and
    synthetic-input sanity checks only —
    `_hitter_hr_target_support`/`_k_ladder_target_support`/
    `_prefer_richer_k_ladder_targets_doc` have no existing unit test
    coverage anywhere in this repo, a pre-existing gap, not introduced this
    session. Also worth recording: this session found the working tree
    already carrying large unrelated concurrent edits to
    `syndicate/features/mlb/cards.py` (+280/-50 lines) and
    `syndicate/features/shared/market_inventory.py` (+36 lines) from what
    appears to be a parallel session (matches #98's own "a parallel
    session's log pull" note, and two commits — `66e9d7b9` #97,
    `59480b94` #98 — landed on `main` mid-session without this session
    pushing them) — did not touch, stage, or commit either file.

### Reconciliation 2026-07-26

Bookkeeping only. No code or behaviour changed by this pass; two ID collisions
were resolved and nine already-closed rows removed from the open tables.

- **#63 was two different items.** The mutual-deferral invariant test is the
  original #63 and is closed. The "candidates drop to zero at
  `candidate_collection`" item (filed 2026-07-26, newer) is renumbered **#68**.
- **#53 was two different items.** Prop-ladder odds keeps #53 (it is
  cross-referenced from the #16 audit body). The "last simmed" per-league
  rollout is renumbered **#69**.
- **Removed from the open tables as already closed:** #40, #47, #49, #50, #54,
  #55, #57, #60, #63. Knowledge that was only recorded in those rows has been
  moved to Operational notes rather than deleted — check there before assuming
  something was lost.
- **#43 is still open**, despite appearing in the closed line. The write-size fix
  shipped; the item's own closure criterion (`candidate_count > 0` with a
  snapshot timestamp) has not been met. Left in progress deliberately.
- **New: #70** (render.yaml comment/value inversion, found during this pass) and
  **#71** (nothing checks that shipped work reaches this list).
- **#64 was missing entirely** — neither open nor closed. It shipped 2026-07-25
  as `a1638c39` and was found by diffing commit messages against the list. Now
  recorded in `todo_closed.md`. It matters beyond bookkeeping: #64 *is* the
  `_build_candidate_pool` instrumentation that #66 was still asking for, so this
  gap could have caused a session to rebuild existing work.
- **Closed items moved to [`todo_closed.md`](todo_closed.md).** The Done section
  was 106 of 438 lines. Lessons were **not** archived with them — anything that
  should still change a future session's behaviour was promoted into Operational
  notes, because that section gets read and the archive does not.
- **Corrected a stale operational note**: "three 2GB services" has been wrong
  since #57 upgraded refresh-worker to pro/4GB.

---

## Do first

> **START HERE (fresh session): read the morning slate before writing any
> code.** Everything shipped 2026-07-26/27 reports its own results now, and the
> morning readout decides what's next:
>
> 1. **Burn attribution** — `/api/ops/oddsapi/quota` now carries
>    `by_market_family` + `by_hour_utc`. One full slate of data decides #16's
>    cuts (a)/(b) and validates the off-hours gate + per-sport cadence +
>    `lines_props` tiering savings against the 11.12M/30d baseline.
>    ⚠️ **First overnight reading (02:10–04:40Z): `event_list` shows 653 calls
>    / 1,234 credits — a bucket the #15 analysis believed was FREE.** Either
>    that belief is wrong or billed requests whose URLs carry no `markets=`
>    param are misfiled into it (check the slate-endpoint and props-job URL
>    shapes against `_attribute_request_families`). Resolve this before
>    trusting the family split — it may also mean ~1.9 credits/call of
>    "free" event polling is a real cost bucket nobody has counted.
> 2. **CLV capture** — lifecycle observations are phase-tagged
>    (`drift/ramp/closing/live`, `event_type="open"` = opener). Check the first
>    full day's tags and whether T-window sweeps fired (`T_WINDOW_SWEEP_DUE`;
>    WNBA is the sport they exist for).
> 3. **The board through pregame→live→final** — never yet observed end to end.
>    It rolled to Monday's slate with 38→35 pregame cards (pregame lane
>    populated for the first time; cross-source dupes fixed 23fcf8fc). Watch
>    lanes transition as games go live.
> 4. **Steam + weather** — first `STEAM_DETECTED` events and
>    `weather_<date>.json` artifacts should exist; spot-check both.
>
> Then, in order: **#68's MLB half** (unproven — needs a same-instant
> worker-vs-web comparison, single-fetch A/B, on a pregame slate with markets),
> **#84's sim join** (wind/temp into totals/HR via park factors), **#83's
> surfaces** (board "why is this moving" + Ask the Syndicate, now that steam
> events exist), **#38** (prune scaffolding — only after the readout validates),
> **#85/#86** as designed. #56/#74 remain the architectural pair.
>
> ⚠️ Read #68's "two bugs cancelling out" note before touching
> `normalize_candidate`, and the cross-time-comparison operational note before
> comparing worker to web. #78 stays archived as the worked example of the
> rollover-probe misread.

| # | Item | Notes |
|---|---|---|
| **124** | 🟡 **MLB props-absent investigation, 2026-07-28/29 marathon session — SEVEN real bugs found and fixed, all confirmed live; the remaining gap is now a real architecture question, not a bug. START HERE for the next session, read this whole entry before touching anything.** User reported MLB props completely absent from the board, suspected a #112/#116 recurrence. It was not — seven independent, mostly-unrelated bugs were stacked on top of each other, found one at a time by shipping a fix, deploying, watching production logs for the *next* symptom, and repeating. All seven are deployed and confirmed; two follow-up items remain, explicitly scoped below, not started.<br><br>**1. Sport-scoped requests clobbering the canonical board** (`pipeline/intelligence_state.py`, commit `82be2538`). `_compute_board_publication_response` filters `top_opportunities`/`recommendations` down to one sport whenever a caller passes `sport != "all"` (including the per-tab `force_refresh` queued at [blueprints/intelligence.py:1843-1847](syndicate/blueprints/intelligence.py:1843), which fires just from a user loading the intelligence page with a sport tab selected) but never filtered `candidate_count`, so the response still looked "healthy" downstream. `write_latest_intelligence_state` persisted that filtered response into the SAME shared `intelligence_state.json`/`board_snapshot.json` files an unfiltered build writes to, gated only on date. Fixed: both the persist function and `_background_loop`'s `_latest_key` promotion now refuse a sport-scoped payload. Also fixed in the same commit: `_persist_locked`'s separate `board_snapshot.json` write had no artifact-size fallback at all (`BOARD_SNAPSHOT_PERSIST_FAILED` on every cycle, 10.47MB payload vs 8MB keyvalue ceiling) — given the same `_write_state_payload` fallback #105 already uses elsewhere. **Confirmed live**: board correctly showed multiple sports together post-deploy, not collapsed to one.<br><br>**2. MLB pregame props permanently missing on refresh-worker** (`syndicate/features/shared/artifact_publisher.py`, commit `28a90ea0`). `daily_top_props_<date>.json` — the sole source of MLB pregame props (`home.py::_load_mlb_home_top_prop_items`) — was fully populated on web's disk (307 pitcher+hitter rows, verified via `/mlb/api/pitcher-top-props`) but `pull_hot_artifacts`' incremental `since=` pull can only repair a copy OLDER than web's, never one that never arrived (documented in `_required_daily_artifact_paths`' own docstring, which already covered exactly this for `season_betting_card_day_path` per #68 — this file was just never added). Added it. **Confirmed live**: MLB `pregame_count` went 0 → 18 → 28, `data_health` flipped `partial` → `healthy`.<br><br>**3. Same gap, second artifact** (commit `6b53f1e5`). `daily_summary_<date>_locked_policy.json` (feeds `markets.{pitcher,hitter,extraPitcher,extraHitter}Props` via `_cards_recommendation_payload_by_game`, mlb/cards.py) had the identical permanently-missing-repair gap. Added to the same required-artifact list. Real, legitimate fix — but turned out NOT to be why live props were still zero after shipping it (see #5).<br><br>**4. Live-lens snapshots never cross-service-distributed at all** (commit `2340d4e9`). `live_lens_loop.py` (runs on **live-odds-worker**, gated by `SYNDICATE_ENABLE_LIVE_LENS_LOOP`) builds a real per-game live-lens snapshot with populated `liveProps`/`archivedLiveProps` — MLB's via a genuine in-game Monte Carlo re-sim — and calls `publish_changed_hot_artifacts` every tick specifically to push it to web. `data/live/{mlb,nba,wnba}_live_lens.json` were never in `HOT_ARTIFACT_PATTERNS` at all, so that push always silently skipped them (not a keyvalue-size failure — a plain missing allowlist entry). Allowlisted all three. Not sufficient alone: these filenames carry no date, so `pull_hot_artifacts`' date-scoped glob can never match them, and the existing missing-artifact repair only fires once (first time absent) then never again — wrong for a file that must stay fresh every cycle. Added a third, unconditional-every-cycle fetch path alongside the date-glob pull and the once-only repair pass.<br><br>**5. The actual live-props root cause: a wrong freshness proxy** (`syndicate/features/mlb/live_lens.py`, commit `1e0d7555`). Even after #4, refresh-worker's own live-props diagnostic showed real prop-backed live games but `prop_row_counts=[0]*9` — structurally-present, empty lists. Traced to `_live_lens_snapshot_needs_refresh`: it deferred to `_live_lens_report_needs_refresh`, which measures a **different file's mtime on the calling process's own disk** (reset every time `pull_hot_artifacts` re-fetches it) against a 60s max-age — tighter than a real refresh-worker cycle (60-90s+) — so it evaluated "stale" on almost every cycle and discarded a snapshot that had in fact just been read fresh from the shared keyvalue store, replacing it with a thinner from-scratch local recompute. Fixed: trust the already-read snapshot's own `generatedAt` content field first (it reflects when live-odds-worker actually generated it), only falling back to the file-mtime proxy when a snapshot has no `generatedAt` at all.<br><br>**6. "Market still open" as the live SLA, per explicit user direction** (`syndicate/features/shared/recommendation_engine.py`, commit `12d5bfe4`). After #5 landed, real live prop data started flowing — and 123 of 144 total `filter_candidates` rejections in one cycle were `reason=stale_beyond_sla` on that exact real data, because the Phase 2a 30-minute live ceiling (todo.md's earlier freshness-SLA work) checked `last_updated` age, and a prop whose price hasn't needed to move isn't stale, it's just quiet. Live candidates now skip the time-based ceiling entirely when not `state_invalid` (the upstream `_apply_candidate_state_guard`, intelligence.py, already drops a final game / an 8h-frozen live claim / an inactive player before a candidate ever reaches this function — "is the market still open" already existed as a real, correct, upstream signal; the separate time-based ceiling was pure redundancy). Pregame candidates keep the ceiling unchanged (no "still open" concept before a game starts).<br><br>**7. The actual reason MLB's tick still under-performed after #4-#6: a memory-headroom gate tuned for the wrong container** (`render.yaml` + live env var, commit `e1f17691`). `SYNDICATE_LIVE_LENS_MIN_HEADROOM_MB` defaults to 1800MB, checked against live-odds-worker's 2048MB container — effectively requiring total usage stay under ~250MB. Measured live via a temporary diagnostic (`LIVE_LENS_TICK_DIAG`, still in `live_lens_loop.py`, **remove once this fix has run untouched for a full slate**): MLB's tick was failing this exact check on the large majority of cycles, always at the SAME steady ~850-900MB usage regardless of success/failure — the threshold, not real memory pressure, was the cause. NBA/WNBA have no equivalent gate and never fail. Lowered to 1000MB (set live via Render's env-var API + committed to render.yaml for persistence). **Confirmed live**: 6 consecutive successes immediately after the deploy landed, 0 failures since (vs. roughly 1-in-5 before).<br><br>**⚠️ Two follow-ups identified, explicitly NOT started, both found live in this same session's final hour:**<br>**(a) MLB's live props still barely rotate even with #1-#7 all fixed.** Same handful of props (same players/markets/timestamps) kept showing for hours even after tick success hit 100%. Root cause, confirmed by direct comparison: WNBA (which "just works," per the user) builds its live-lens snapshot from `build_cards_page_context` — pre-computed, stored card artifacts, live lines overlaid on top, zero in-process simulation — while MLB's builder runs a real 120-sim Monte Carlo re-sim per live game as its *primary* source, which is inherently slower/heavier and can legitimately come back with nothing new on a given cycle even when it "succeeds." MLB's `live_lens.py` already has a lighter, card/artifact-based path built (`_live_props_from_card`, `_merge_cards_context_into_live_row` — the same betting-card data the pregame path already uses) but it is not the primary source. **Recommended fix, not implemented**: make the card-based read MLB's primary live-props source (matching WNBA's reliable pattern), with the Monte Carlo path as an optional enhancement layered on top rather than a requirement. User separately raised whether `live_lens_loop.py`'s MLB tick belongs on **refresh-worker (4GB)** rather than live-odds-worker (2GB) given refresh-worker's larger container and its original intended purpose — agreed as directionally correct, not yet scoped (need to check `scripts/run_refresh_worker.py`'s entrypoint calls the loop starter, and that `SYNDICATE_ENABLE_LIVE_LENS_LOOP`-style gating moves cleanly without double-running on both services).<br>**(b) `build_live_lens_snapshot_internal` is reachable, unguarded, from a web request.** Explicitly commented "Worker-only compute function" in its own source, yet `@mlb_bp.get("/api/live-lens")` → `api_live_lens()` → `read_latest_live_lens_api_payload()` (and the HTML route via `read_latest_live_lens_page_context`) can trigger it directly inside a web request with **zero** `refuse_if_compute_in_request_path`-style guard, unlike `_build_candidate_pool` which has exactly that guard for exactly this reason. Confirmed real, not yet fixed. Now that #4/#5 mean web should be able to read a genuinely fresh pre-computed snapshot via the shared keyvalue store without ever needing to compute it itself, adding the guard should be safe — but wasn't verified before the session ended. |
| **125** | 🟢 **WNBA live-lens "Current period"/"Current half" segments silently showed the full-game Total/ML/ATS line as if it were period-specific — user-reported, fixed, deployed, and confirmed live (commit `dc940eca`, deploy `dep-d9kk6r1t0dsc73e8n18g`).** Post-deploy check against the same live CON@WSH game confirms the fix: "Current period"/"Current half" now show `ATS: Off card / ATS unavailable / No live period line yet.` and `Total: Off card / Total unavailable / No live period line yet.` instead of duplicating "Total 157.0". The ML row under those same segments is unaffected and correctly still shows a real edge ("WSH ML, Model 14% | Edge -53.9pp... Using current game moneyline") — `quarter_ml`/`half_ml` have a genuine signal (a live-score-derived win probability deliberately priced against the full-game moneyline, clearly labeled as such), unlike ATS/Total which have no period-specific market line at all right now; only the latter two were ever silently mislabeled. User's screenshot of a live CON@WSH game showed identical "Total 157.0 · Live line pending." under both "Current period" and "Current half", matching "Full game"'s own Total exactly. Traced (Explore agent + direct production check): the period/half signal-building logic in `syndicate/static/wnba/cards-parity.js` (`computeLiveGameLens`, `halfSignal`/`quarterSignal`) is real and correctly wired end-to-end back to `vendor/wnba_betting_repo/app.py`'s `api_live_lines()` (`_live_oddsapi_period_totals_for_game` querying OddsAPI's `totals_h1`/`totals_q1..q4` markets, with a Bovada-CSV fallback, `_live_load_period_lines_map`) — not a "never built" gap. But confirmed live via `/wnba/api/live_lines?date=2026-07-28`: `period_totals: {}` and `period_spreads: {}` are genuinely empty right now, while `total`/`home_ml`/`away_ml`/`home_spread` (full-game) are fully populated — real data unavailability upstream (either sportsbooks not offering WNBA period markets the way they do for NBA, or the Bovada fallback pipeline not running; **not resolved which**, would need production disk access or a dedicated check to confirm). Rather than chase third-party/pipeline data availability at 1 AM, fixed the actually-misleading part: `liveLensMarketFromSignal` (`cards-parity.js:4475`) used to fall back to `game.betting.total`/`home_ml`/`home_spread` (the full-game line) for ANY market type whenever the period-specific signal was null, mislabeling it identically for period, half, AND full-game segments with no indication it wasn't segment-specific. **Fix:** added a `periodScoped` parameter (default `false`); the 6 quarter/half call sites in `liveGameLensRows` now pass `true`, so when their signal is null they show an honest "No live period line yet." instead of silently substituting the full-game number. The 3 full-game call sites are unchanged (that fallback is genuinely correct there). `node --check` passed. Committed (`dc940eca`), deployed to the web service only (`dep-d9kk6r1t0dsc73e8n18g` — a static-asset-only change, no need to restart refresh-worker/live-odds-worker), confirmed live above. No automated test added (same DOM/browser-only rationale as #113/#114). **Follow-up 1 (same session): user pushed back — "we should have odds and projections for these periods," correctly rejecting the honest-placeholder fix as the real answer.** Explore-agent trace confirmed the projection math already exists and is genuinely odds-independent: `halfSim`/`quarterSim` (`game.sim.periods.{q1..q4,h1,h2}.total_mean`, a real pregame per-period model output, populated server-side via `_build_fallback_smart_sim_object` in `vendor/wnba_betting_repo/app.py` and `_source_sim_periods` in `syndicate/features/wnba/cards.py:798-884`) blended with live scoring pace — the bug was that `halfSignal`/`quarterSignal`/`halfAtsSignal`/`quarterAtsSignal` only got BUILT (projection included) inside `if (Number.isFinite(halfLine/quarterLine/halfSpread/quarterSpread))`, so the whole signal — including the perfectly-computable projection — was discarded whenever the period-odds line was missing. `half_ml`/`quarter_ml` never had this bug (already priced off the full-game moneyline, not a period line, which is why ML displayed correctly the whole time). **Fixed** (`cards-parity.js`): all 4 total/ATS builders now compute+return a real signal (klass `'MODEL'`, `edge`/`line` both `null`) whenever the underlying model math is available, regardless of whether a period-odds line exists; `liveLensMarketFromSignal` renders this case as `Proj {value}` / `{side} by {margin}` with a "Model projection · no live market yet" sub-label, instead of either the misleading full-game substitution (pre-#125) or the bare "No live period line yet." placeholder (#125's first pass). `node --check` passed. **Follow-up 2 (same session): user pushed further — "we should have that live market line though - it may be named different than expected."** Read `_live_oddsapi_period_totals_for_game` (`vendor/wnba_betting_repo/app.py:522`) in full: it discovers available markets via a `GET /v4/sports/{sport}/events/{event_id}/markets` call, matches against a candidate-name table already covering common naming variants (`totals_h1`/`totals_1h`/`totals_1st_half`/`totals_first_half`, same pattern for q1-q4 and their spread equivalents), and returns empty `period_totals`/`period_spreads` immediately if NONE of those candidates appear in the discovered key set — with the discovery HTTP call's response (including any error) silently swallowed by a bare `except: keys = set()`, so a wrong-endpoint/permissions/format problem in the discovery step itself would be indistinguishable from "sportsbooks genuinely don't offer these markets" without instrumentation. Rather than guess further, added a bounded diagnostic print (`PERIOD_MARKET_DISCOVERY_DIAG`, one per matchup per 20s cache window via this function's own existing cache) logging `discover_status`/`discover_error`/`discovered_keys` verbatim. **Follow-up 3 (same session, this settles it): the real root cause — not a naming mismatch, not third-party data unavailability, a genuine "never wired up" gap, same class as #102.** Deployed follow-up 2's diagnostic, triggered `/wnba/api/live_lines` for the live CON@WSH game repeatedly, and the `PERIOD_MARKET_DISCOVERY_DIAG` print **never once appeared in ANY of the 3 services' logs** — meaning `_live_oddsapi_period_totals_for_game` was never being called at all. Traced why: production's actual per-game entry consistently logged `stage: build_live_lines_payload_fallback_return` (an existing `log_runtime_memory` marker), meaning every request lands in `_fallback_live_lines_game` (`syndicate/features/wnba/cards.py`) — Syndicate's own, real production implementation, NOT the vendored `api_live_lines()` route the earlier follow-ups were reading. Confirmed `_fallback_live_lines_game` **never imported or called `_live_oddsapi_period_totals_for_game` at all** (`grep` returned zero matches in `cards.py`) — it only ever returned `game.betting.*` (static, pregame lines) with `period_totals`/`period_spreads` hardcoded to `{}` unconditionally, and it also never populated `status`/`in_progress`/`period`/`clock` on its own output at all, letting those fields leak through from whatever stale value a prior merge step carried forward (confirmed separately: this endpoint reported `"in_progress": false, "status": "Scheduled"` for the same CON@WSH game that `/wnba/api/live_state` correctly showed live at 43-38, 2nd quarter — a second symptom of the same root cause, not a separate bug). Exactly the shape #102 already found and fixed for the live-lens-tick pipeline ("only reachable over a dead HTTP mechanism nothing in production calls") — this is the same gap in the period-market-fetch piece specifically, which #102 didn't happen to touch. **Fix** (`cards.py`): added `_live_oddsapi_period_lines_for_game` (same lazy-import idiom as `wnba/live_lens.py`'s `_run_wnba_live_lens_tick`, used for the identical reason — a ~40k-line vendored module). `_fallback_live_lines_game` now (a) populates real `status`/`detail`/`period`/`clock`/`in_progress`/`final` via the already-existing `_cards_context_live_state_snapshot(game)` helper instead of leaving them for a stale merge to fill in, and (b) when the game is genuinely in progress and period totals were requested, calls the real fetch and merges its `period_totals`/`period_spreads` in. New test (`test_live_lines_fallback_fetches_real_period_totals_for_a_live_game`, `tests/test_wnba_live_snapshots_local.py`) confirmed to fail pre-fix (`AttributeError`, the function didn't exist) and pass post-fix; full `test_wnba_live_snapshots_local.py` (38) plus `test_wnba_live_lens_worker.py`/`test_wnba_api_snapshot_errors.py` (14) all still pass. **Follow-up 4: deployed and confirmed the merge-layer half of this was ALSO broken.** `_merge_live_lines_game` (`cards.py`) never touched top-level `status`/`detail`/`period`/`clock`/`in_progress`/`final` at all, only `lines.*` — so a stale `local_payload`/`artifact_payload` (primary, written before the game went live) kept winning over the freshly-rebuilt fallback entry (secondary, now correctly computing `in_progress=True` per follow-up 3's fix). **Fixed:** merge now prefers secondary's live-state fields whenever it reports the game further along (in progress or final) than primary, mirroring `_live_state_row_needs_cards_override`'s existing "fresher live signal wins" reasoning elsewhere in this file. New test (`test_merge_live_lines_game_prefers_fresher_in_progress_state`) confirmed to fail pre-fix, pass post-fix. **Deployed and confirmed live**: CON@WSH's `/wnba/api/live_lines` now correctly tracked `in_progress: true`, `status`/`period`/`clock` updating in real time across several polls ("1:35 - 3rd" → "End of 3rd" → "7:32 - 4th" → "5:07 - 4th" etc.) — this part is a real, working, verified fix. `period_totals`/`period_spreads` stayed empty throughout, and added two more diagnostics (`FALLBACK_LIVE_LINES_TRI_DIAG`, `LIVE_ODDSAPI_PERIOD_IMPORT_FAILED`/`_CALL_FAILED`) to chase why — confirmed `away_tri`/`home_tri` resolve correctly ('CON'/'WSH'), `ODDS_API_KEY` is genuinely set on web (verified via Render API, 32 chars, without exposing the value), no import/call exception ever logged, yet the vendored function's own unconditional `PERIOD_MARKET_DISCOVERY_DIAG` print STILL never fired even once across many real, live-game requests — an unresolved mystery for pure remote/log-based diagnosis (would need an actual debugger attached to the process to go further). **Follow-up 5, the real architectural correction — user caught this directly ("are you getting live odds from the live odds worker?"), and the answer is no, which is the bug.** Follow-up 3's fix made **web** call `_live_oddsapi_period_totals_for_game` directly, synchronously, inside a request handler — violating the exact same "web does no heavy compute, workers fetch, web reads" rule this session hard-enforced elsewhere tonight for intelligence compute (`request_path_guard.py`), just in a different corner of the codebase. The **correct** mechanism already exists and predates this session: `scripts/refresh_wnba_oddsapi_props.py` (lines 437-441, run on a worker's own schedule via `refresh_odds_sources.py`'s orchestration) already calls this exact vendored function for in-progress games and writes the result into the local `live_lines` snapshot artifact web is supposed to read via `_filtered_local_live_snapshot_payload` — a proper worker-writes/web-reads split, exactly like everywhere else in this repo. **The likely REAL root cause of the whole night's symptom, found in that same script**: `_WNBA_DEFAULT_MARKETS` (`refresh_odds_sources.py:74-81`) — the market list WNBA's regular scheduled odds refresh actually requests from OddsAPI — is `_WNBA_GAME_MARKETS ("h2h,spreads,totals") + player props`, and **never includes `totals_h1`/`spreads_h1`/`totals_q1`-style period markets at all**, unlike the sibling constant `_DEFAULT_INTERVAL_MARKETS` two lines above it, which explicitly includes `spreads_h1,totals_h1,spreads_h2,totals_h2` for whatever sport that one serves. This is a strong, concrete, not-yet-confirmed lead: the bulk fetch may simply never be asking for period markets, independent of whether OddsAPI/sportsbooks actually offer them. **Deliberately not fixed tonight, given the hour and this being a genuinely separate correction from what was shipped** — next session should: (1) decide whether to revert or properly relocate follow-up 3/4's web-side direct call (their `in_progress`/`status`/`period`/`clock` fix is real and independently valuable and should probably stay; the `_live_oddsapi_period_lines_for_game` direct-fetch call specifically is the part that's architecturally wrong and should likely be removed or demoted to an explicitly-labeled emergency-only fallback), (2) add period markets to `_WNBA_DEFAULT_MARKETS`'s scheduled request, (3) verify `refresh_wnba_oddsapi_props.py`'s existing fast-path call (lines 437-441) actually populates the artifact once markets are being requested, checking `_source_app_fallback_enabled()`'s gate too since that could independently be off. **Follow-up 6, user said "you can continue and fix now" — implemented both corrections.** (1) `_WNBA_GAME_MARKETS` (`scripts/refresh_odds_sources.py`) now includes `spreads_h1,totals_h1,spreads_h2,totals_h2`, bringing WNBA's scheduled bulk fetch to parity with NBA/NCAAB's `_DEFAULT_INTERVAL_MARKETS`; quarter markets deliberately NOT added, matching that same precedent (no basketball sport's bulk cadence fetches quarter-level odds, likely a real #15/#16-adjacent cost/availability tradeoff, not an oversight). (2) Reverted the architecture violation: `_fallback_live_lines_game` (`cards.py`) no longer imports or calls the vendored OddsAPI function at all — it's a thin, static fallback again, reading `period_totals`/`period_spreads` straight from `game.get("betting")` if already present (populated upstream by `refresh_wnba_oddsapi_props.py`'s own worker-side fetch, once markets are actually being requested) rather than ever fetching live from web. Kept the genuinely-correct, independent part of follow-up 3/4: `in_progress`/`status`/`period`/`clock` still come from `_cards_context_live_state_snapshot(game)`, no live call needed for that. Removed all now-resolved diagnostics (`FALLBACK_LIVE_LINES_STATE_DIAG`/`_TRI_DIAG`, `LIVE_ODDSAPI_PERIOD_IMPORT_FAILED`/`_CALL_FAILED`, `PERIOD_MARKET_DISCOVERY_DIAG`) — they were firing on every fallback build (several times per second) and the question they were chasing is now moot given the architecture fix. Rewrote the affected test (`test_live_lines_fallback_surfaces_period_totals_already_on_the_game_object`, replacing the one that pinned the reverted behavior) plus a structural guard test asserting the fallback function no longer exists; both plus a `del selected_date` no-op (kept as a parameter since `build_live_lines_payload` still passes it, avoiding unrelated signature churn) pass; full `test_wnba_live_snapshots_local.py` (40), `test_wnba_live_lens_worker.py`/`test_wnba_api_snapshot_errors.py` (14) all pass. **Still open, deliberately not chased further tonight**: whether `refresh_wnba_oddsapi_props.py`'s own worker-side fast-path (lines 437-441, calls the same vendored function via `_load_source_app`'s dynamic-load-from-a-source-root-path mechanism — itself the "source-app fallback" pattern CLAUDE.md says this repo is moving away from) actually succeeds in production and reaches `game.betting`, and whether the `live_lines` snapshot artifact it writes actually gets published/pulled to web at all (a potential #68-style cross-service artifact gap, not yet checked). Next session: confirm end-to-end that a real live WNBA game's `game.betting.period_totals` is non-empty by the time it reaches `_fallback_live_lines_game`, now that the market list is fixed. **Follow-up 7: found and fixed a real bug the projection-decoupling fix (follow-up 1) introduced — `Number(null) === 0` in JS, not `NaN`.** User reported live rendering showed "MIN 0.0" / "Proj +5.0 vs 0.0" for the MODEL-klass rows instead of the intended honest no-line display. `buildSignal` (`cards-parity.js:1257`) did `Number(edge)`/`Number(line)` directly — passing `null` (follow-up 1's "no market" case) silently became a real `0`, which `Number.isFinite` then treated as present. Fixed with an explicit `null`/`undefined` → `NaN` guard before the `Number()` calls. Confirmed live: rows now correctly show `MIN by 8.0` / `Proj 110.0` with a clean "Model projection · no live market yet" sub-label. **Follow-up 8: user asked "why isn't the live box score loading for WNBA" — checked directly, it's actually working correctly** (real player stat rows for both teams, "Live" badge, confirmed via DOM inspection); likely a transient symptom from one of tonight's several deploy cycles, not a standing bug. No code change. **Follow-up 9: user asked "and props aren't showing the live total" — real, separate bug, fixed.** `transformLiveStripPayload` (`cards-parity.js:3396`) excluded every prop row whose `line_source` was box-score/sim-estimated (`isSyntheticLiveLineSource`: `cards_fallback`/`boxscore_sim_fallback`/`oddsapi_player_props_fallback`) from the "Live opportunities" bucket entirely. Confirmed live: **every** row for the in-progress TOR@MIN game had `line_source: "boxscore_sim_fallback"` (traced to `_hydrate_live_player_lens_payload` in `cards.py`, which computes this exact label whenever the worker-written snapshot has no real `live_projection` field of its own and has to estimate one from box score + sim math) — so the whole "live" bucket came back empty and the panel silently fell back to showing only pregame recommendations with no live total shown at all. Asked the user whether this was a bug or an intentional "only show a live total when there's a real fresh market price" design boundary; user wants a live total shown regardless, badged as estimated rather than hidden. **Fix:** removed the exclusion filter (rows are included now), added an `estimated` field (`isSyntheticLiveLineSource(row.line_source)`) to the transformed item and to `liveItemToPropRow`'s returned row, and added an explicit "Estimated" tag to `reasonTags` (shown in the prop detail view) when synthetic, alongside the existing "Live OddsAPI"/titleCase(lineSource) tag shown for genuinely fresh sources. `node --check` passed; full `test_wnba_live_snapshots_local.py`/`test_wnba_live_lens_worker.py`/`test_wnba_api_snapshot_errors.py` (54) still pass (JS-only change, no Python test coverage for this specific display logic — same DOM/browser-only rationale as #113/#114/#125's earlier JS fixes). **Not yet deployed as of this writing** — deploy web and confirm live before considering this closed. |
| **83** | 🟢 **Steam detector — SHIPPED 2026-07-27 (`event-feeds` commit), actuator deliberately minimal until #62.** The market is the best-aggregated news feed this system can access (survey conclusion, same date: general news/social watchers rejected — latency loses to the market and false triggers cost sim time + board deferral). Detection at the point deltas were already computed ([odds_refresh_tracking.py](syndicate/features/shared/odds_refresh_tracking.py) `_steam_signal`): a ≥0.5 line move or ≥15¢ price move across ≤45 min between observations; ramp/closing lower the price bar to 10¢ (late money is the most informed). Rides the lifecycle event as a `steam` field AND a bounded per-date record (`reports/steam/steam_events_<date>.json`, last 200) + `STEAM_DETECTED` print. Env: `SYNDICATE_STEAM_{LINE_MOVE,ODDS_MOVE,WINDOW_SECONDS,LATE_ODDS_MOVE}`. **Open:** wire as a consumer-facing surface (board "why is this moving", Ask the Syndicate), and as a re-price trigger **once #62 exists** — do NOT wire it to force re-sims. |
| **84** | 🟡 **MLB park weather — fetch SHIPPED, sim join OPEN.** `scripts/fetch_mlb_weather.py`: NWS (free, keyless) hourly wind/temp/direction for every park with a game today (home teams from the game-lines snapshot; 31-entry coords table incl. roof flags — verified live: 74°F / 6 mph S at Yankee Stadium on first run). Written to `data/weather/weather_<date>.json`, allowlisted for web pull, launched detached from the tick at most hourly (`SYNDICATE_MLB_WEATHER_INTERVAL_SECONDS`, 0 disables). **Open half:** join wind/temp into the sim (totals/HR) via the park-factors join point, and surface on cards. ⚠️ Tampa Bay coords assume Tropicana; verify 2026 venue. Roofed parks are fetched with `roof: true` so consumers discount wind rather than the park going missing. |
| **85** | 🟡 **Remaining structured event feeds** (from the 2026-07-27 survey; general news watchers rejected). (a) **Soccer confirmed XI at ~T-60** — the biggest soccer line-mover, lands inside #82's ramp window; no free structured source identified yet, needs a source decision before any code. (b) **Official injury-report schedule audit** — basketball injury fetch already exists (`_fetch_injuries` → `fetch-injuries` CLI per sport package, fingerprint-diffed for change detection), so the open question is narrower than it looked: whether those fetches align with the leagues' fixed publication times, not whether the mechanism exists. (c) **Probable-pitcher change detection** — verify `probable_pitcher_overrides.json` is fed by detection rather than manually. |
| **86** | 🟡 **LLM analyst layer — judgment, not detection.** Two scoped uses on top of #83's steam record and the existing triggers: **materiality classification** of detected changes (star scratch ≠ ninth bullpen arm; today both force the same sweep) and **movement annotation** ("why did this move") attached to steam events for the Ask the Syndicate briefing family, which is the natural home. Explicitly NOT a raw-news-firehose reader — cost, latency, and hallucinated urgency feeding a pipeline where false triggers block the board. Blocked on nothing, but do after #83's surface exists so the annotations have somewhere to land. |
| **82** | 🟡 **Pregame odds capture: opening line, movement curve, CLV close — per-sport rules agreed 2026-07-27, Phase 1 SHIPPED.** The design (user-signed): each data product has its own sampling need — *opening* = first sweep after posting; *movement* = sparse drift samples + event triggers (lineup/injury force-refresh already exists and bypasses all cadence); *CLV close* = a **per-game T-minus sweep**, which slate-wide cadence structurally misses (worst for WNBA one-game days). **Rules:** MLB/WNBA pregame drift every **2h, full sweeps** (midday PROP samples ride along — user requires them); **soccer 8h (2–3/day)** pre-matchday, daily shape on matchday; live cadence untouched. **Phase 1 (shipped `pregame-cadence` commit):** per-sport interval filter in the tick — a sport whose OWN games aren't live sweeps at most once per its interval (before this, WNBA re-swept every 60s for the whole of an MLB slate); event-triggered sports bypass; every uncertainty fails open; `SYNDICATE_PREGAME_SWEEP_INTERVAL_SECONDS[_<SPORT>]`, 0 disables. **Phases 2+3 SHIPPED 2026-07-27 (same session):** `capture_phase` tag (`drift/ramp/closing/live`, boundaries 80/12 min bracketing the T-windows; `event_type="open"` marks the opener) on every lifecycle observation; T-window scheduler fires full sweeps at T-75/T-10 per game for **non-live sports only** (a live sport's 60s slate-wide cadence already covers its pregame events — the windows matter exactly when they're cheap: first game of the day and WNBA one-game slates); commence times from MLB's game-lines snapshot and WNBA's vendor schedule, everything failing open to "nothing due"; `market_tier=lines_props` on pure drift sweeps drops MLB's 24 segment/alternate markets (~63% of per-event cost) with **existing segment lanes carried forward so the cards' F1/F3/F5/F7 tabs never blank between full sweeps**; T-windows, live, event triggers, and uncertainty all run full. ⚠️ Known limitation: MLB T-windows only fire from the service that owns MLB's tick (owner rules intact); MLS matchday ramp rides its games going live. *Original Phase 3 plan:* per-game **T-75m** post-lineup sweep and **T-10m closing sweep** driven by each sport's start times, plus a `phase` tag (`opening/drift/lineup_trigger/ramp/closing/live`) on lifecycle observations so opening/closing lines are lookups, not timestamp inference. **Phase 2 (after):** market tiering — lines-only drift via #17's slate endpoint (~6 credits) with props every 4h, full markets only at T-windows. |
| **25** | Phase 0 fail-closed refresh guard + atomic writes | **Phase 0 shipped** — see Done. Remaining: the look-ahead's own interval marker (#24) has not been audited for the same fail-open pattern, and several non-artifact writers still use the unsafe collision-prone temp shape. **Enumerated 2026-07-26 — it is six files, not the three previously listed, and the `backtest_*` scripts are NOT among them** (that entry was wrong): [fetch_soccer_history_local.py:44](scripts/fetch_soccer_history_local.py:44), [fetch_soccer_oddsapi_odds_local.py:82](scripts/fetch_soccer_oddsapi_odds_local.py:82), [fetch_soccer_oddsapi_props_local.py:105](scripts/fetch_soccer_oddsapi_props_local.py:105), [fetch_nfl_oddsapi_props_local.py:74](scripts/fetch_nfl_oddsapi_props_local.py:74), [fetch_mlb_oddsapi_local.py:72](scripts/fetch_mlb_oddsapi_local.py:72), [refresh_ncaaf_oddsapi.py:529](scripts/refresh_ncaaf_oddsapi.py:529). All use `path.with_suffix(path.suffix + ".tmp")`, so two concurrent writers of the same file collide on one temp path. `atomic_artifact_write.py` already exists; this is mechanical. |
| **15** | 🔴 **DO NOT DOWNGRADE — conclusion INVERTED by the first full-day measurement, 2026-07-27T01:55Z.** The item's own instruction ("let the window run a full day") was finally satisfiable: baseline 2026-07-26T01:52Z → latest 2026-07-27T01:55Z, **86,572 s**. Result: **371,563 credits burned in 24 h → 15,451/hr → projected 11.12 M/30d — 2.2× OVER the 5 M target**, and 74% of even the current 15 M plan. Two independent counters agree exactly (provider `used` delta 1,188,309→1,559,872 vs local window sum). **Composition: MLB is 96.3%** (357,975 of 371,563; soccer 18 credits, WNBA 332 — both noise). ⚠️ **Why the earlier 1.42 M/mo read was wrong:** it was the period-to-date *average* — ~25 days during which the pipeline was repeatedly degraded (OOM loops, empty boards, workers down). Today was arguably the first fully-healthy day, and **a healthy system burns ~8× the degraded average**. The "estimate is 36× too high" claim compared against that suppressed average; against today the original ~585/sweep estimate is only ~2.3× high. ⚠️ Still one day — do not size the *exact* monthly number off it — but the asymmetric conclusion is safe: even occasional 371 k days keep the total far above 5 M, **and football season only adds**. **Next steps, in order:** (1) attribute MLB's 358 k/day by market family — the recorders already pass `endpoint=url` ([oddsapi_quota.py:100](syndicate/features/shared/oddsapi_quota.py:100)), the store just doesn't aggregate it; a `by_market_family` bucket beside `by_sport` is a small never-raises change and tomorrow's slate produces attributed data; (2) USER DECISION on #16's cuts (a)+(b) — now measurement-backed, ~210 of ~585/sweep ≈ 36%, which alone still leaves ~7 M/mo; (3) USER DECISION: this item's "do not tier the cadence" was premised on the problem not existing — the problem now measurably exists, so cadence tiering (full-game every sweep, segments/alternates every Nth) is back on the table, but that reversal is yours to make, not a session's. Caveat: `by_sport` in the store never resets, but the 02:36Z 7-26 reading (MLB 393 calls/179 credits) pins essentially all MLB burn inside this window. |
| **100** | 🟢 **Consolidation SHIPPED, COMMITTED, AND DEPLOYED 2026-07-27/28 (commit `110461f6`) — full call-site enumeration done first per this item's own instruction, then migrated.** Enumerated via three parallel Explore passes over `intelligence.py`/`home.py`/`mlb/cards.py` before any edit, per this item's "don't start migrating before the full list exists" rule: **26 game-state call sites** and **7 projection-presence sites**. New canonical module `syndicate/features/mlb/game_state.py` (`mlb_status_is_live`/`mlb_status_is_final`, zero other repo imports by design to sidestep the home.py/intelligence.py/mlb.cards circular-import relationship) holds the one shared liveness predicate — folds in BOTH the confirmed-correct implementation (`_mlb_candidate_live_state`'s `detailedState`-based warmup exclusion) AND `_cards_status_is_final`'s more-permissive final detection (substring `"final"` match + `"completed early"`), since neither prior implementation alone was the strict superset. Migrated onto it: `_mlb_candidate_live_state` (intelligence.py, now delegates instead of keeping its own inline copy), `_mlb_feed_live_state` (home.py — was abstract-only, fed board-wide `is_live`/`in_progress`), `_actual_payload_is_live`/`_live_lens_row_is_live`/`_cards_status_is_live`/`_cards_status_is_final` (mlb/cards.py), two odds-refresh-timestamp loops, and the market-board live-lens-row gate (mlb/cards.py — `game_state` stays a raw display string, only the `== "live"` gating switched to the canonical predicate). **Root-caused and fixed #98's actual symptom while enumerating (b)**: `_mlb_game_market_recommendation_rows` (home.py) threaded MLB's real moneyline/total model win-probability through only as display text under `"confidence"` — a field `normalize_candidate`'s projection scan (intelligence.py) never checks — while leaving `projected` genuinely empty, so every pregame MLB game-level candidate classified `missing_projection_or_odds` even with real model data present. Fixed by stamping the raw fraction onto `model_probability` (the scan's actual recognized field) at `_append_game_bet_candidate`, the one choke point every sport's game-level candidate passes through — same reasoning as #92's `hr_probability` fix. Also: removed `_candidate_has_usable_projection` as confirmed dead code (0 callers, not the "two disagreeing predicates" case #68 worried about); found and fixed two NEW disagreeing truthiness-bug copies of the same #68 bug class (`score_candidate`'s `has_odds`, `home.py`'s `_first_present_text` used in several field-scans) by canonicalizing on `_candidate_value_is_present`/isinstance-first logic instead of a third bespoke check. Every fix backed by a test confirmed to fail against pre-fix source (verified via `git stash` on the source files only, re-run, then restored) — 6 new/updated tests across `test_mlb_game_state.py` (new file), `test_home.py`, `test_intelligence.py`, `test_mlb_market_board.py`; full targeted run (`test_home.py`+`test_mlb_market_board.py`+`test_mlb_game_state.py`+four other mlb test files) 163/163, plus a keyword-scoped `test_intelligence.py` subset (live/classify/candidate_value/projection/score_candidate/scoring_mode/mlb) 57/57 excluding one confirmed pre-existing failure (`test_intelligence_query_uses_mlb_top_props_artifact_for_requested_pitcher_subject`, reproduced against committed `main` with this session's changes stashed out — unrelated, from a concurrent session's commit). **Committed and deployed** (`110461f6`, pushed to `origin/main`, all 3 Render services redeployed and confirmed `live` via `/api/ops/version` 2026-07-28T00:2x-00:3xZ — see #102's entry for the same deploy, both landed together). ⚠️ **Not yet observed against live production** — the #98 fix is a strong, well-evidenced root-cause match but still needs a real pregame slate to confirm the board actually serves pregame MLB candidates now. **Not done, deliberately out of scope**: `build_mlb_market_board`'s live-lens gating fix has no dedicated integration test (the function's fixture cost is high; covered transitively by the now-tested canonical predicate + the three cards.py wrapper tests, but not end-to-end) — worth adding if this specific path ever regresses. See #103 for a related-but-separate gating question found during enumeration that was deliberately NOT touched here. |
| **101** | 🟢 **MLB market board: real per-side model win probabilities — SHIPPED for MLB 2026-07-27, WNBA/NBA SHIPPED 2026-07-27 (see #102), NHL/NFL/NCAAF/NCAAB still OPEN.** User-reported: `/mlb/market-board` showed blank "Projected" and "NO MODEL VIEW" for most rows, and the one row with a Model % showed the *same* number for both Over and Under (impossible for real win probabilities). Root cause: `_mlb_market_board_prop_rows_for_game`/`_mlb_market_board_rows_for_game` (`cards.py`) only built a `sim_row` for stats the recommendation engine had already picked, using its **edge** value (not a win probability) shared identically across Over/Under since the join key had no `side` component. **Fix (MLB):** `join_odds_to_sim` (`market_inventory.py`) now accepts an optional `model_prob_over` on a sim row and derives each side's complementary probability from the odds row's own `side` at join time (no join-key format change, so existing key-format tests kept passing unmodified), plus stamps a `model_side` field so the UI can badge whichever row the sim actually favors. MLB now computes `model_prob_over`/`projected_value` from the sim's own per-player distribution (`pitcher_props`/`hitter_props`, via `_dist_prob_over_line`, the same mechanism the live-prop rail already used) for **every** market-quoted stat with sim coverage, not just recommended ones; moneyline/total also now price unconditionally from `predictions.full.home_win_prob`/`away_win_prob`/`total_runs_dist` rather than the reco-gated `model_prob`. `market_board.js`/`board_cards.css` render a "Model likes this side" badge on the favored row. **Verified live** against real local artifacts (2026-06-21 slate): Over/Under now genuinely complementary (e.g. 88.6%/11.4%), Projected populated for props with no reco pick, badge on the correct side. 54 pre-existing tests in `test_mlb_market_board.py` pass unmodified; new tests added there and in `test_market_inventory.py`. **Open:** propagate the same dist-based (not edge/reco-pick-gated) per-side model probability to NBA/WNBA (`syndicate/features/shared/basketball_market_board.py`'s props path has the identical reco-pick-only pattern; its game markets already compute genuine two-sided `p_home_win`/`p_over` so may need less work) and to whatever market-board coverage lands for NHL/NFL/NCAAF/NCAAB per #28. |
| **102** | 🟢 **WNBA (then NBA) end-to-end pregame/live audit — SHIPPED AND DEPLOYED 2026-07-27/28.** User-requested full audit of WNBA ahead of its return from All-Star break, then NBA mirrored the same day (offseason, no urgency but wired anyway). Real findings, all fixed and tested (130+ new/updated test passes across both sports): (a) **WNBA/NBA had no real live modeling** — the vendored pace-adjusted live-projection pipeline (`vendor/{wnba,nba}_betting_repo/app.py`'s `api_cron_live_lens_tick`, ~1,386 lines each) was only reachable over a dead HTTP mechanism nothing in production calls; extracted into a plain `_live_lens_tick_payload` function (mirroring how `mlb/live_lens.py` already calls MLB's vendored `_live_lens_payload` in-process) and wired `{wnba,nba}/live_lens.py` to call it every tick. (b) **Found along the way: `{WNBA,NBA}_LIVE_LENS_DIR` in `render.yaml` were relative paths** (`./data/...`) on all 6 service blocks, unlike MLB's correct absolute one — almost certainly resolving against the ephemeral checkout instead of the persistent disk on Render, meaning writes likely never landed anywhere durable. Fixed to absolute, matching MLB's pattern. (c) **Found: the resulting `live_lens_projections/signals_<date>.jsonl` files were never in `artifact_publisher.py`'s `HOT_ARTIFACT_PATTERNS`** — the allowlist that lets live-odds-worker's writes reach the web service (Render gives each service its own disk even at the same mount path). Added both variants (nested/flat) plus an explicit publish call at the end of each live-lens tick in `live_lens_loop.py` so propagation isn't just opportunistic. (d) **#101 follow-up, closes it for WNBA/NBA**: `basketball_market_board.py`'s prop rows either duplicated one probability onto both Over/Under, or only had a model view for recommendation-engine-picked stats. Fixed the duplicate via `join_odds_to_sim`'s existing `model_prob_over` mechanism, then found the sim artifact (`cards_sim_detail_<date>.json`) already carries per-player `{stat}_mean`/`{stat}_sd` that nothing read — wired those in so every market-quoted stat with sim coverage gets a real probability. **Verified against real production data**: WNBA prop rows with a model view went 20/392 → 256/392; NBA 36/246 → 182/246. (e) **`{wnba,nba}/props.py` served the pregame recommendation slate unconditionally regardless of game state** — added live/pregame branching so live games get live-modeled projections vs. live lines instead of stale pregame picks (NBA's version also respects the existing team/player filters). (f) **Removed a fully dead "remote source-app fallback" cluster** (7 functions across `wnba/cards.py`/`nba/cards.py`, proven unreachable by existing tests that pinned it as such) plus one dead stub (`wnba/live_lens.py`'s `_live_line_map`), matching the "no source-app fallback" direction. **Also verified, not bugs**: WNBA's injury/lineup-triggered resim is real and wired at the sport level (`_should_force_sim_rerun` covers both `nba`/`wnba`); a WNBA-only per-matchup narrowing optimization is deliberately staged/observation-only, not broken. Both sports' MAIN game card already has the full 4-panel structure (market snapshot/recommendations/sim detail/props); live box score is served via a separate polling endpoint (`build_live_player_boxscore_payload`) rather than embedded in the same panels list MLB uses — an architecture difference, not a gap. **Open, deliberately not taken on this session**: NHL/NFL/NCAAF/NCAAB still need the #101-style dist-based coverage; WNBA's per-matchup resim narrowing needs `_run_live_refresh_tick` wired to actually use `_LAST_WNBA_LINEUP_INJURY_CHANGED_MATCHUPS` instead of forcing the whole slate. **Shipped, pushed, and deployed**: `35e0b4d5` (WNBA) and `58a215c5` (NBA), pushed to `origin/main`, then all 3 Render services (web/refresh-worker/live-odds-worker) redeployed and confirmed `live` on the resulting merge commit `110461f6` via `/api/ops/version` (2026-07-28T00:2x-00:3xZ). Deploy was deliberately held ~25 minutes for an in-flight `tip_off_window` MLB resim (2 games) to clear per this file's standing caution; when the sim was still running after that wait with no ETA available, user explicitly chose to deploy anyway (an event-driven resim, not irreplaceable data) rather than wait longer. **Not yet observed against a live WNBA/NBA game** — next real slate (WNBA returns 2026-07-28) is the first chance to confirm the live-lens artifacts actually populate end-to-end in production (write path, cross-service publish, and read path all fixed independently this session; watch `live_lens_projections_<date>.jsonl`/`live_lens_signals_<date>.jsonl` timestamps on both `wnba_source` and `nba_source` during a live game). |
| **96** | 🟡 **`/portfolio` never reconciles — the flag is now actually flipped (a prior attempt's placement bug meant it never could have worked), SHIPPED and deployed 2026-07-28. Part (a) done, part (b) scoped but not built — see #122.** Originally validated live 2026-07-27: `/api/portfolio/summary` showed 12 pending bets (9 MLB straight + 3 parlays), all `settled_count: 0` four days later. This session, revisited as a blocker for Layer 2 Phase 3 (calibration-based board suppression needs real settled data to base thresholds on — confirmed via the evaluation ledger: **all ~1350 records, 100% `result: "pending"`**, proving reconciliation autorun has never actually run on Render at all, not just for this one user's MLB-heavy portfolio). **Root cause was one layer deeper than previously logged**: `RECONCILIATION_ENABLE_REFRESH_WORKER_AUTORUN`/`RECONCILIATION_REFRESH_INTERVAL_SECONDS` lived in the **web** service's `envVars` block in `render.yaml` (nominally anchored `&shared_render_env_vars`, but that alias is never referenced by any other service in the file, so nothing was actually shared). The code that reads these two keys (`scripts/run_refresh_worker.py`'s `_reconciliation_auto_refresh_enabled`/`_reconciliation_interval_seconds`) runs as the **refresh-worker** service's own process, which never saw this key at all — confirmed via the Render API before touching anything: 0 of 20 configured env vars on the live refresh-worker service matched `RECONCIL`. So simply flipping `"false"`→`"true"` where the earlier note said to would have changed nothing; the flag needed to move to the service that actually reads it. **Fix**: moved both keys to refresh-worker's own `envVars` block (`true`/`86400`), and — since `render.yaml` alone doesn't sync to a running service without an explicit Blueprint sync — set both directly on the live service via Render's env-var API, confirmed present via a follow-up GET before committing. Deployed to all 3 services, confirmed live (`/api/ops/version` matches the pushed commit). **Verification is honestly incomplete, not claimed as proven**: reconciliation only fires once per refresh-worker cycle (bypassing its own 24h interval gate on this first-ever run, since last-run epoch is 0), and no dedicated status endpoint exposes `reconciliation_autorun_status.json` (written via the keyvalue-backed state store, not reachable from a local checkout without production Redis access) — checked `/api/portfolio/summary` (this session's own test portfolio is 100% MLB, so it can't show the fix working) and Render's logs API (spotty, per established session experience; zero reconciliation-related lines found in the post-deploy window checked, but the worker's first full cycle since deploy may not have completed yet). **Next session: re-check `/api/portfolio/summary` for any NBA/WNBA/NHL positions moving off `pending`, or find a way to read `reconciliation_autorun_status.json` directly, before trusting this is actually settling predictions in production.** MLB itself still cannot resolve regardless — see #122. |
| **122** | 🟡 **NEW — scoped, not built: an MLB actuals/results writer, the other half of #96.** `prediction_reconciliation.py`'s matcher (`_candidate_result_paths`, `RECONCILIATION_PATTERNS`) recursively searches `data/` for `recon_games_{date}.csv`, `recon_props_{date}.csv`, `props_actuals_{date}.csv`, `game_results_{date}.csv`/`.json`, `closing_lines_{date}.csv` — any location under `data/` works (e.g. `data/mlb_source/...`), matched to a prediction by normalized `sport`/`market`/`selection`/`player`/`team` text (`_row_keys`) and graded via either an explicit `result`/`outcome`/`grade` column, or `actual` + `line`/`closing_line`/`market_line` compared against "over"/"under" in the prediction's selection text (`_row_outcome`). **No MLB writer produces any of these five filenames anywhere in the repo.** Concrete build path, all inputs already exist: `mlb/cards.py`'s `_daily_actual_by_game`/`raw_feed_live_path`/`_fetch_current_feed_live` already fetch and cache the MLB Stats API's `feed/live` payload per `gamePk` for other purposes (live/final card rendering) — once a game reaches `Final`, that same cached payload's `liveData.boxscore` has full per-player stat lines (hits, HRs, Ks, etc.) and `liveData.linescore`/`gameData.teams` has the final score. A new script (e.g. `scripts/build_mlb_actuals.py`) would: (1) for a target date, get all that date's `gamePk`s from the existing daily-summary/schedule artifact; (2) for each game whose cached feed shows `Final`, read the already-fetched payload (no new fetching needed); (3) write `game_results_{date}.json` (final score + team names, shaped for `_row_outcome`'s explicit-result or actual+line path) and `props_actuals_{date}.csv` (one row per player per tracked stat, actual value, shaped to match `_row_keys`) under `data/mlb_source/...`. Wire it into the daily pipeline (or refresh-worker's own reconciliation autorun window) once built. Not started this session — this is a real script to write, not a config flip like #96(a) was. |
| **127** | 🟡 **(renumbered from a duplicate #104 during end-of-session reconciliation — this item and #104's "MLB game candidates" entry were both accidentally filed as #104, almost certainly two concurrent sessions claiming the same next-free-ID at once; the MLB entry is the one with 5 existing cross-references elsewhere in this file, so this one moved instead, nothing about its content changed.) `NHL_LIVE_LENS_DIR`/`NHL_DATA_DIR` in `render.yaml` are still relative paths — same bug class as #102's WNBA/NBA fix, found but not fixed (out of scope for that session).** All three service blocks (~line 158-161, 361-363, 651-653) have `NHL_DATA_DIR: ./data/nhl_source/source_artifacts/data` and `NHL_LIVE_LENS_DIR: ./data/nhl_source/source_artifacts/data/live_lens` — relative, unlike MLB's/the now-fixed WNBA's/NBA's absolute equivalents (`/opt/render/project/data/...`). On Render these almost certainly resolve against the ephemeral code checkout rather than the persistent disk, so anything NHL writes there is unlikely to survive a restart/redeploy. **Not investigated**: whether NHL even has an active vendored live-lens tick pipeline analogous to WNBA/NBA's `api_cron_live_lens_tick` worth wiring in-process (per #102's fix) — this item is scoped to the config bug only; confirm the pipeline exists and matters before assuming the same 3-part fix (path + hot-artifact allowlist + in-process wiring) fully applies. |
| **103** | 🟡 **`_mlb_market_prop_candidates_from_artifact` never feeds the default board — found during #100's enumeration, not fixed, needs a USER DECISION not a code call.** Found by a parallel session and relayed during #100's coordination: this artifact-backed MLB prop candidate path (`intelligence.py:4090`) is gated by `wants_ranked_mlb_market_backfill` (`intelligence.py:5232`), true only when the query text matches `\b(?:top|best)\s+(?:\d+|one|two|...)\b` — a normal board-refresh cycle's default query never phrases that way, so this entire path contributes zero to the standard board by construction, not by missing data. Unconfirmed whether this is a deliberate Q&A-only backfill (in which case it's working as designed) or an accidental total-starvation of a path that should also feed the default board. Deliberately not resolved during #100's pass — this is a behavior/product decision (what should the default board show), not a duplicate-code cleanup, so folding it in would have exceeded that item's scope. |
| **104** | 🟢 **MLB game candidates: derive a pick from sim predictions when no recommendation is attached — SHIPPED and deployed 2026-07-27, commit `32725568` (deployed as of `8e4cf228`).** Following #100/#98's confidence-field fix, validated live that of tonight's 9 non-final MLB games only 2 (TOR@WSH, PHI@MIA) had a recommendation-engine pick attached to `markets.ml`/`totals`; the other 7 (including all 3 genuinely pregame ones) had zero game-level candidates even though `game.predictions.full` carried real, non-degenerate win probabilities for every one (e.g. 0.579/0.243/0.446). `_mlb_game_market_recommendation_rows` required `selection`+`model_prob` to build a row at all, so #100's confidence-field fix never got a chance to run for these 7. Mirrors the Layer 1 market board's identical, already-shipped fix (`_mlb_market_board_rows_for_game`'s own docstring: "model_prob... only exists for games the reco engine flagged") — falls back to the sim's own win probability / total-runs distribution when no recommendation is attached, per this file's own "no candidate dropped solely for missing source" rule. Existing recommendation-shaped markets are untouched (tested: an existing pick, even one disagreeing with the sim, still wins). Two new tests, both confirmed to fail pre-fix. |
| **105** | 🔴 **A successful-but-empty recompute cycle silently overwrote a real 6-candidate board snapshot — found and fixed live 2026-07-27, commit pending.** Root cause of tonight's "board looks stuck/empty" symptom, distinct from #98/#100/#104: `IntelligenceStateService._background_loop` (`pipeline/intelligence_state.py:~3107`) already had a guard (`SNAPSHOT_UPDATE_SKIPPED_AFTER_FAILURE`, from an earlier fix) that refused to overwrite a good snapshot when the compute call **raised** (`run_failed`) — but a cycle that completes **without raising** and legitimately computes zero candidates was never covered. Observed live: right after a concurrent session's deploy restarted refresh-worker (commit `7acdf2e0`, #16's event-scoping work), the next real compute cycle landed on 0 candidates — not an exception, just an empty result, plausibly because the freshly-restarted process's own artifact/cache state hadn't caught up yet — and silently replaced the existing 6-candidate snapshot; `self._latest_key` followed it, since that guard's own `self._latest_key == snapshot.key` OR-clause is trivially true for the persistent "today" key on every recompute. Confirmed via `/api/ops/intelligence/candidate-trace?read_only=true`: `state_read_latest_snapshot_candidate_count` went from `6` (computed 19:35:01) to `0` (computed 01:04:08Z) with the same `latest_key` throughout. **Also confirmed, safely, that the candidate-generation code itself is completely healthy** — pulled the real production `/mlb/api/cards` payload and ran `_game_candidates_for_sport`/`_classify_candidate_with_reason` locally (no production compute triggered): **119 real MLB prop candidates, 100% surviving classification**, including a 42%-edge pick (Edgar Quero Under 1.5 Hits, 92.6% model probability vs 50.5% market-implied) that never reached the board. So the emptiness was purely this overwrite bug, not a candidate/classification defect. **Fix:** widened the guard to `(run_failed or snapshot_count <= 0) and previous_count > 0` — skip the same-key overwrite whenever the new result is empty AND the existing one wasn't, regardless of whether the cycle raised. Deliberately narrow (only guards against regressing to *empty*, not any decrease) to avoid fighting legitimate narrowing as games go final overnight. New test (`test_background_loop_does_not_overwrite_a_good_snapshot_with_an_empty_recompute`) confirmed to fail pre-fix (0 != 6) and pass post-fix. **Committed (`ff5621aa`) and deployed (commit `8e4cf228`, confirmed live via `/api/ops/version` on all 3 services).** ⚠️ **The follow-up guess in this entry's first version was wrong** — the post-restart cycle did NOT compute zero from a cold cache; a real 84-candidate, 82-card cycle ran successfully and got REJECTED at the keyvalue-write stage for being oversized (10.18MB against an 8.39MB ceiling), which IS a `run_failed=True` exception path, not the "successful-but-empty" case this item's fix targets. See #108 for that real root cause and its own fix — the two are complementary, not the same bug: this item stops an empty result from erasing a good one; #108 stops a REJECTED (too-large) result from being treated as a failure that erases a good one. Both were needed. |
| **108** | 🟢 **The board_snapshot write had no keyvalue-too-large fallback — this is why the board has been capped at small candidate counts most of tonight, SHIPPED and deployed 2026-07-27, commit `0ab45813`.** User asked directly why the 8MB keyvalue ceiling matters and why this can't just use artifacts — researched properly rather than guessing: **the answer is it already does, partially.** Render's managed Key Value service physically closes the connection above ~9MB (not Syndicate's limit to raise — `refresh_state_store.py:391-397`); `_write_state_payload` (`intelligence_state.py:1448`, shipped for #43) already tries keyvalue first and falls back to the artifact-publish transport (`syndicate/features/shared/artifact_publisher.py`, which routinely moves tens of MB with no ceiling problem) when the write is rejected. Deduplicating the response's four near-copies of the candidate list (`by_sport`/`top_opportunities`/`recommendations`/`board_contract`) was already tried and explicitly rejected in writing — `recommendations` carries 7 fields and 4 differing values the others don't, so it isn't losslessly aliasable. **The actual gap**, found by reading the real traceback from tonight's rejection: `write_latest_intelligence_state` calls `_write_state_payload` (with the fallback) for the compact state payload, but two lines later writes `BOARD_SNAPSHOT_PATH`/`daily_paths["board_snapshot"]` via a **plain `write_json_file` call — no fallback at all** (`intelligence_state.py:1567-1568` pre-fix). Confirmed live: a real, healthy 84-candidate/82-card cycle (28 live + 54 pregame) serialized to 10.18MB, got `KeyValuePayloadTooLarge` here, propagated uncaught, and `_background_loop` treated the whole cycle as `run_failed` — discarding a correctly computed rich board back down to whatever smaller snapshot last fit under 8MB. This is very likely the primary reason props and full slate richness never reached the board tonight, independent of #98/#100/#104/#105. **Fix:** both writes now go through `_write_state_payload` too, reusing the already-proven #43 mechanism rather than inventing new transport logic. New test (`test_write_latest_intelligence_state_falls_back_to_artifact_when_board_snapshot_too_large`) confirmed to fail pre-fix (exception propagates) and pass post-fix. 🟢 **Confirmed live 2026-07-27T02:03Z, end to end.** The natural loop cadence wasn't producing a fresh cycle fast enough to observe this directly (the sim-resident board-build defer, `_board_build_deferral_reason`, kept deferring — see its own new force lever below), so a deploy-time env override was used to force one on refresh-worker's own healthy 4GB (not the memory-tight web service — confirmed web was at 95.6%/89MB headroom at the time, worker was at 22.1%/3.19GB, so the force was directed at the right service). Result: `CANDIDATE_POOL_READY count=23` → `board_input cards=23` → `BOARD_PUBLICATION_RESPONSE_READY candidate_count=23`, served board went from stuck-at-11 `game`-type candidates to **23 real `prop`-type candidates** (peaked at 50 momentarily). This is the first live confirmation that #98/#100/#104/#105/#108 all work together correctly once a full rebuild is actually allowed to run. **New, related lever added and used for this test:** `SYNDICATE_BOARD_BUILD_FORCE_DESPITE_SIM` (`pipeline/intelligence_state.py`, off by default, commit `62edb6fb`) bypasses `_board_build_deferral_reason`'s sim-resident wait entirely — the existing bounded wait (defer up to 5 cycles, then check memory headroom) is correct for normal operation, but forcing a same-session test needed to skip the wait outright. **USER DECISION 2026-07-27: leave it on.** `SYNDICATE_BOARD_BUILD_FORCE_DESPITE_SIM=true` stays set on refresh-worker going forward, not reverted after the test — the sim-resident wait is bypassed entirely from now on, relying solely on the memory-headroom check (already proven sufficient: 4GB usually has room per the code's own measured reasoning). If a future session finds the board starved specifically because this makes rebuilds contend with an active sim under genuinely tight memory, that's the first thing to check — it's a deliberate, informed tradeoff, not an oversight. |
| **109** | 🟢 **The real reason MLB's real candidate pool was prop-only every cycle (never game-type) while WNBA correctly produced both — a cross-service data-mirror gap, found and fixed live 2026-07-27, commit `2aef2715`.** After #108 confirmed props reaching the board, user asked directly about live/pregame + game opportunities together — production traces (`collect_candidates_with_fallback_merge`) showed MLB landing on `{"prop": N}` only across 5+ consecutive real cycles, while a WNBA cycle in the same window showed a genuine `{"game": 20, "prop": 22}` mix. Added a bounded diagnostic (`MLB_GAME_MARKET_ROWS_DIAG`, ~12 prints/cycle) to `_mlb_game_market_recommendation_rows` and redeployed to settle it definitively rather than keep guessing from web-side data. **Confirmed on refresh-worker's own logs, all 12 games, two consecutive real cycles:** `has_markets_ml=False has_markets_totals=False has_predictions_full=True` — refresh-worker's own `dashboard_games` (built from its own artifact mirror, a separate Render disk from web's, per #68's precedent) carries `markets["ml"]`/`["totals"]` as **entirely absent**, not merely lacking a recommendation (the case #104 already handled) — while `predictions.full` is reliably present since the sim runs on refresh-worker itself. #104's fallback required `markets.get("ml")` to be a dict at all before trying anything, so it never got the chance. **Fix:** the moneyline branch of `_mlb_game_market_recommendation_rows` no longer requires `markets["ml"]` to exist — a moneyline pick needs no book line, unlike totals (left untouched, since there's genuinely no line to bet against without a market), so it derives purely from `predictions.full` when markets data is absent, with `odds` left `None` (classification accepts projection OR odds, same reasoning as the HR-targets precedent, #92). New test confirmed to fail pre-fix (`StopIteration`, `rows_returned=0` per the diagnostic) and pass post-fix. **Confirmed live post-deploy:** board went from 0 game-type candidates to **19**, all `game` type, in the next cycle. 🟢 **Resolved, same night**: `_collect_candidates` additively combines both types by design (props from `home_rails`, games from `dashboard_games`, both gated on the SAME always-true `include_props`/`include_games` defaults) — confirmed directly in refresh-worker's own logs post-midnight-rollover: a single WNBA cycle produced `"generated": 42, "markets": {"game": 20, "prop": 22}`, both types together in one `collect_candidates_with_fallback_merge` call. The earlier alternation was transient (deploy-adjacent cache warm-up + MLB's own predictions being briefly absent right at the date rollover to `2026-07-28`), not a structural bug. **Pregame is also now confirmed live**: the same post-rollover cycle produced `CANDIDATE_POOL_READY count=36`, `lane_counts: {live: 0, pregame: 36}` — real pregame candidates, since every game on the new day hadn't started yet. Both of the user's original asks (game+prop together, pregame populated) are now directly observed, not just structurally-argued. |
| **110** | 🟢 **"Tomorrow" showed no opportunities despite refresh-worker already building a real 36-candidate WNBA board for that date — found and fixed live 2026-07-27, commit `21d5fc92`. Sport-agnostic, applies to every sport.** User reported selecting 7-28 ("Tomorrow") produced zero opportunities even though refresh-worker's own logs showed a genuine `CANDIDATE_POOL_READY count=36` cycle for WNBA on that date. Traced `read_combined_intelligence_response` (the read side of #93/#94's combined-board design) → its default date window came from `_default_board_window_dates()`, which intersects the raw today..today+N-1 span with `_supported_intelligence_dates()` — a union of each sport's own `available_dates()` (e.g. `wnba_available_dates()` scanning `data/processed/game_cards_*.csv`/`recommendations_slate_*.json`). That "has a published schedule artifact" check is a reasonable **build-side** optimization (`_ensure_default_board_window_watched` — don't waste a refresh-worker compute cycle on a date nothing has a schedule for) but is the wrong gate for **reading**: it lagged behind a date refresh-worker had already built and published a real board for, so the read path never even attempted it, even though `_read_single_date_response_for_combining` already degrades gracefully to 0 candidates on a genuine miss. **Fix:** split the window computation into `_board_window_candidate_dates` (raw window, no per-sport filtering) and kept `_default_board_window_dates` (the filtered build/watch version, unchanged) separate; `read_combined_intelligence_response` now always attempts every date in the raw window. Applies uniformly to every sport `_supported_intelligence_dates()` covers, not just WNBA — the filtering removed was never sport-specific. New test (`test_default_window_reads_a_built_date_even_when_not_in_supported_dates`) confirmed to fail pre-fix and pass post-fix; one pre-existing test's assertion (`test_falls_back_to_today_when_nothing_warm`, renamed) updated to match the intentionally-widened default window. **Same commit also hard-enforces #56/#98/#109's "web does no heavy compute" rule structurally**: `refuse_if_compute_in_request_path` (`request_path_guard.py`) now *raises* `ComputeInRequestPathError` (previously only warned) when `_build_candidate_pool`/`_compute_response` would run inside a live web request on a hosted (Render) deployment — including the admin-gated debug endpoint, deliberately not exempted since that's exactly the path #98's OOM went through. Local dev (no separate worker process) keeps the old warn-only behavior. 7 tests in `test_request_path_guard.py` (2 pre-existing, 5 new) pass. **Deployed and confirmed live 2026-07-27T22:33Z** (commit `01594083`, all 3 services). User asked to deploy immediately rather than wait for the in-flight resim to clear (it was still running); the deploy killed it as expected, a known/accepted tradeoff for event-driven resims. **Confirmed via a real `/api/intelligence/query` call post-deploy**: `dates_covered: ['2026-07-27', '2026-07-28', '2026-07-29']`, `by_date: {"2026-07-27": {"candidate_count": 5, "covered_sports": ["mlb"]}, "2026-07-28": {"candidate_count": 36, "covered_sports": ["wnba"]}, "2026-07-29": {"candidate_count": 0, "covered_sports": []}}` — tomorrow's already-built 36-candidate WNBA board is now actually served, exactly the symptom this item was opened for. **Follow-up found and fixed same session, commit `2ba04255`**: verified in the browser against production and found the ranked Board table correctly showed only WNBA picks under "Tomorrow", but the **Games strip above it still showed today's live MLB games mixed in** — `renderBoardBody()` (`intelligence.html`) passed the raw, unfiltered `lastRenderItems` into `renderGameCards`, which was deliberate for sport/min-edge/market (so the strip still surfaces a game whose opportunities a stricter filter hid) but wrong for date, since date selects a genuinely different slate rather than narrowing the same one. Split a `matchesDateFilter` helper out of `matchesClientFilters` and applied it to the Games-strip input too. Confirmed live post-deploy (web-only, commit `dep-d9k27rugekts73c6uk70`): the Games strip under "Tomorrow" now shows only the 5 WNBA matchups. |
| **111** | 🟡 **Joint follow-up with a concurrent session ("Odds/signals monitoring"), 2026-07-28 ~17:40Z — real gap confirmed, but board is NOT empty/props-only; mitigated by #108's existing sim fallback.** After the game-lines merge fix below deployed, `has_markets_ml` was still `False` for all 16 games (worse than the 1/16 originally found) — investigated jointly rather than duplicating work, since that session had just made 5 deploys in the same odds-refresh area. Their finding, independently confirmed against the same timestamp window: (a) their event-scoping/props-cadence changes did NOT cause this — h2h/spreads/totals are deliberately fetched for every event regardless of hot/cold status by design, only the 24 segment/alternate markets are cadence-gated; (b) the raw `oddsapi_game_lines_2026_07_28.json` snapshot genuinely has real h2h/spreads/totals for all 16 games (`retrieved_at 17:35:18Z`) — the fetch itself is healthy; (c) the gap is specifically between "the raw file has it" and "refresh-worker's in-process `dashboard_games`'s `markets.ml` field has it" — the same #68-shaped cross-service disconnect, still not root-caused to an exact mechanism; (d) **but `_mlb_game_market_recommendation_rows`'s #108 fallback (already shipped earlier tonight, before any of this) is covering the gap**: when `markets["ml"]` is absent it derives a real Moneyline candidate from `predictions.full`'s sim probabilities directly, so `has_markets_ml=False` still yields `rows_returned=1` per game, not 0. Confirmed live board check (~17:38Z): 55 recommendations, `{moneyline: 25, props: 15, betting card: 5, ats: 5, total: 5}` — real, non-empty MLB coverage. **Net effect right now: MLB moneyline picks display without a real book price/edge (a real accuracy gap worth fixing), not a missing-candidate outage.** Lower urgency than originally framed — deliberately left open rather than rushed, since the fallback means no one is seeing an empty board. **Still needs**: the actual mechanism explaining why refresh-worker's own process-level `dashboard_games` disagrees with its own freshly-fetched on-disk file for `markets.ml` specifically (predictions.full agrees fine) — worth a dedicated session once #112-adjacent priorities allow. **Below is the original fix + its "live confirmation pending" note, both still accurate for what they cover (the merge-not-overwrite behavior itself, and why it couldn't be observed synchronously) — just superseded on the "why is MLB still showing null odds" root cause by the joint finding above.** **Root cause pinned down precisely** (a follow-up Explore pass, since the first pass's mechanism guess was close but not exact): `fetch_and_write_live_odds_for_date` (`vendor/mlb_bettingv2/tools/oddsapi/fetch_daily_oddsapi_markets.py:431`) is the writer `daily_update.py` actually calls (not the properly-incremental `fetch_live_odds_incremental` in `scripts/refresh_mlb_oddsapi.py`, which only serves a separate fast-tick path) — its `oddsapi_game_lines_{token}.json` write had exactly one safeguard: preserve the whole existing file if the new fetch returned **entirely zero** games. It had no handling for a new fetch that returns **some but not all** games (e.g. `_fetch_live_events_for_date`'s own live-events call coming back short for any transient reason) — that silently replaced a complete 16-game file with a 1-game one, and `_collect_game_recommendations` requires a `(away_team, home_team)` match in this exact file to produce a recommendation row at all, so 15 games lost their moneyline picks even though every one of their sim files (a separate, unaffected artifact) was present and current. **Fix (commit `24001215`, deployed as part of `75480110`):** merge the new fetch's games into the existing file by `event_id` instead of replacing wholesale — any existing game absent from this fetch's result is carried forward untouched, any game present in the new fetch overwrites its prior entry. A fetch that genuinely covers the whole slate reduces to the old full-replace behavior (every existing event_id gets overwritten anyway), so this is strictly additive safety, not a behavior change for the common case. Deliberately scoped to game lines only — pitcher/hitter props keep their existing all-or-nothing preserve logic, since props were confirmed unaffected by tonight's symptom (real prop moves were visible in "Pregame Steam" throughout). New tests (`tests/test_fetch_daily_oddsapi_markets.py`): the partial-fetch case confirmed to fail pre-fix (1 game survives of 16) and pass post-fix; a second test confirms a fetch that legitimately covers every game still updates stale lines rather than freezing them forever. **Why live confirmation is pending, not done:** the fix only takes effect the next time this writer actually runs — the on-disk file it needs to correct wasn't rewritten by the deploy itself. Checked production immediately after deploy: `latest_tick` showed `"off-hours: no tracked game live; next sweep when the staleness ceiling expires or a game goes live"` (#82's pregame-cadence design, correctly throttling odds-API spend per #15/#16's already-documented budget overrun) — today's games start at 12:40P CT onward and it was ~11AM CT, so no sweep was due. Forcing an off-schedule odds fetch just to observe the fix immediately would burn real API budget outside its intended cadence for no operational reason; deliberately not done. **Next session/check-in: confirm via the combined-board query that MLB game cards have real `odds`/`edge` (not null) once a natural sweep has run** (the next 2h drift mark, or the T-75/T-10 window as today's games approach). **Original finding, superseded above but kept for context — user-reported "Today (7-28, 10AM CT) only shows WNBA"; root-caused to refresh-worker's own local MLB odds/recommendation enrichment being periodically self-clobbered by scoped resims. This is a real, live, current-day bug, distinct from #68/#109 (which were about predictions.full, already fixed) — this one is about markets.ml being destroyed AFTER it was correctly built.** Confirmed via combined-board API query (`/api/intelligence/query`, `debug_source: combined_board_window`): today's board legitimately has 15 MLB game candidates for 2026-07-28 (not zero — #109's fix is still working), but **every one has `odds/edge/simulated_edge: null`** — bare skeleton rows, useless for betting, which is why the user's practical experience is "only WNBA." Root-caused with a background Explore agent plus refresh-worker's own diagnostic logs (`MLB_GAME_MARKET_ROWS_DIAG`, 2026-07-28T15:06Z): refresh-worker sees `has_predictions_full=True` for all 16 games (sim is current) but `has_markets_ml=True` for only **1 of 16** (game_pk 824976, BOS@ATH) — and even that one lacks `home_odds`/`away_odds`, so `_mlb_game_market_recommendation_rows` (home.py:2926-2933) still can't populate `odds`. Meanwhile web's own `/mlb/api/cards?date=2026-07-28` shows a full, rich `markets.ml` (selection/edge/model_prob/recommendation_tier="official"/reason_summary) for **all 16 games**, proving the enrichment genuinely exists and was computed today — just not where refresh-worker can see it anymore. **Mechanism (Explore agent's finding, not yet independently verified by reading every call site):** the rich shape is built by `_build_locked_policy_card` in `vendor/mlb_bettingv2/tools/daily_update_multi_profile.py` (~line 5247), written via `_write_json(locked_policy_path, locked_policy_card)` (~line 6278) with **no merge against the existing file** — a full overwrite every invocation. `scripts/run_mlb_daily_sim_job.py` (which `live_refresh_loop.py:_launch_mlb_daily_sim` launches, confirmed via production's `/api/ops/live-refresh/state` → `sim_run_status`) is frequently invoked **scoped** to `--only-game-pks` (fingerprint_change/tip_off_window/join_mismatch/coldstart-batch triggers, deliberately batched to avoid OOM-killing the 2GB-class worker per an inline comment) — production's last completed run before this was found: `--only-game-pks 823193,823275,824003,824569,824976` (5 games), `finished_at 2026-07-28T02:04:09-05:00`. `_collect_game_recommendations` (called from `_build_locked_policy_card`) reads the FULL `game_sim_dir` for the date (all 16 per-game sim files, still present regardless of scope) joined against `oddsapi_game_lines_{token}.json` — so the exact clobbering mechanism (whether the odds-lines file itself is being narrowed to the scoped batch on each scoped run's own odds-refresh substep, or whether some other join-time filtering is scoping the output to just the batch) is **not yet fully nailed down** — the Explore agent's read of the locked-policy write as fully non-merging is solid, but why the *lines* input itself apparently narrows to match the same batch needs direct code confirmation before touching anything. Only one game (824976) survived, and it exactly matches the most recent scoped batch — strong circumstantial confirmation of *some* form of scoped-write clobbering in this pipeline, even if the precise file/step isn't 100% pinned. **Deliberately NOT fixed this session**: this sits inside `vendor/mlb_bettingv2/`, the core simulation/recommendation-generation pipeline that produces real betting picks — a wrong fix here risks corrupting recommendations rather than just leaving them missing, a materially worse failure mode than the current "no candidate" gap. Needs a fresh, focused investigation (read `_collect_game_recommendations`, the odds-lines write path, and whether `--only-game-pks` scoping touches `oddsapi_game_lines_{token}.json` at all) before any code change, plus a merge-not-overwrite fix design reviewed before shipping. **This is very likely NOT MLB-specific in principle** — any sport whose resim pipeline does scoped/batched runs against a similarly non-merging enrichment-card write would show the same symptom; MLB is just where it's currently observed and where scoped resims are known to run frequently (per #108's memory-headroom precedent). Worth checking WNBA/NBA/NHL for the same pattern once MLB's fix is designed. |
| **112** | 🟡 **USER DIRECTION, 2026-07-28: pursue moving away from vendored data — bring MLB's simulation/recommendation pipeline fully in-house rather than shelling out to `vendor/mlb_bettingv2`.** Raised directly while investigating #111, whose root cause (a non-merging write deep inside `vendor/mlb_bettingv2/tools/oddsapi/fetch_daily_oddsapi_markets.py`) is a concrete example of the cost of depending on vendored code: fixing a real production bug required tracing through ~6,500 lines of a sibling repo pulled in wholesale, with no test coverage of its own before tonight and no Syndicate-side ownership of its internal write/merge conventions. This matches CLAUDE.md's already-stated direction ("Avoid adding new source-app fallback dependencies — the direction is toward fully local, Syndicate-owned artifact generation per sport") but is a much larger scope than that line implies for MLB specifically, since MLB's `vendor/mlb_bettingv2` is the most heavily depended-upon vendored tree in the repo (daily sim job, locked-policy/recommendation card, odds ingestion all live there). **Not scoped or started this session** — this is a multi-week migration-class initiative (audit what `vendor/mlb_bettingv2` actually does that Syndicate-native code doesn't, decide what moves first, figure out parity-testing so a migration doesn't quietly change real betting recommendations), not something to fold into a single fix. First real step for whoever picks this up: enumerate `vendor/mlb_bettingv2`'s actual call surface from Syndicate-native code (how many entrypoints, how coupled) before estimating size — do not assume it's a small lift. |
| **113** | 🟢 **A second, unrelated cause of "board looks stuck/stale" — SHIPPED and deployed 2026-07-28, commit `c86d9d86`.** Found while double-checking #111 lived up to the user's "last Layer 2 update was 2AM" report: the actual `/api/intelligence/query` combined-board response was verified fresh multiple times (`snapshot_generated_at`/`state_last_updated`/`timestamp` all matching real time), and a fresh browser navigation showed the correct current timestamp — but the user's own screenshot, taken *after a hard refresh*, showed a `board-freshness-chip` reading `snapshot_read · as of Jul 28, 2:01 AM · 50 candidates` alongside a separately-correct `Updated Jul 28, 11:49 AM` status line, plus a `#board-date` input stuck on `07/27/2026` despite the "Today" tab appearing active. Root cause: `intelligence.html`'s initial `state` construction read `document.getElementById("board-date").value` as a fallback when no `?date=` URL param was present — but `<input type="date">` values are restored by the **browser itself** on reload/navigation, independent of HTTP/CDN caching (confirmed `cf-cache-status: DYNAMIC` on this route separately, ruling out a CDN cause), so a tab left open since before midnight silently reintroduced `date=2026-07-27` on every reload including a hard refresh. An explicit date bypasses the combined-board default entirely (`read_combined_intelligence_response`'s own `not explicit_date` gate, #93/#110) and falls back to that stale date's own single-date snapshot — landing on whatever `intelligence_query_api`'s `source="snapshot_read"` branches last computed for 2026-07-27, frozen at 2:01 AM (the last pre-rollover cycle). Confirmed NOT reproducible via a genuinely fresh automated browser session (input empty, chip correct) — consistent with being tab-longevity-dependent, not a backend bug; #111's odds-merge fix is unrelated and unaffected. **Fix:** `state.date` is now seeded only from an explicit `?date=` URL param (an intentional deep link) on load, never from the raw input's live `.value`; the input's displayed value is then synced FROM `state.date` immediately after, overwriting whatever the browser restored — matching the pattern the day-tab click handler already used for its own updates. Verified via `node --check` on the extracted inline script (syntax) and a live post-deploy browser check (fresh load: empty input, `combined_board_window · as of Jul 28, 12:01 PM · 68 candidates`). No automated test added — this is a DOM/browser-restoration interaction that isn't meaningfully unit-testable without a real browser harness; flagged here instead as the regression-prevention record. **If this resurfaces**: check whether `urlParams.get("date")` itself is the carrier (a bookmarked/shared URL with a stale `?date=`) rather than input restoration — same downstream symptom, different fix (would need staleness validation on the URL param too, which this fix deliberately does not add since an explicit URL date is a legitimate, intentional deep-link use case). |
| **115** | 🟢 **The structural cause underneath #111/#113/#114's "two sources" shape — user said "we really just need ONE way everything gets to the board" again after #114 shipped, still seeing varying numbers — SHIPPED and deployed 2026-07-28.** #111/#113/#114 each found and closed a different *trigger* that let an explicit date slip past `read_combined_intelligence_response`'s `not explicit_date` gate in `intelligence_query_api`/`intelligence_home` (`syndicate/blueprints/intelligence.py`) — but the gate itself was still there, so ANY request genuinely carrying a date (typed into `#board-date` and submitted, a specific day clicked in a picker, a bookmarked `?date=` URL) permanently fell to the older `snapshot_read`/`board_snapshot` cascade, a **separately computed candidate pool**, not a filtered view of the same one. Confirmed live, same instant: an identical "today" query returned **72 candidates** via `combined_board_window` (no date) vs. **54** via `snapshot_read` (explicit `date=2026-07-28`). That gap — not a UI caching artifact — is what the user kept seeing after every prior fix. **Root cause:** `read_combined_intelligence_response` already takes a `dates: list[str] | None` and windows gracefully to it (used elsewhere with a real list, e.g. `dates=["2030-01-01","2030-01-02"]` in its own tests) — there was never a structural reason an explicit single date needed a different code path at all. **Fix:** both gates now call `read_combined_intelligence_response(dates=[explicit_date] if explicit_date else None, sport=..., limit=...)` instead of skipping the reader when a date is present. Also fixed a latent `selected_date: None` hardcode in that branch that would have silently un-fixed #113/#114's freshness-chip/`#board-date` sync the moment an explicit date started reaching it. **Verified live post-deploy**: no-date query now `combined_board_window`, 75 candidates across `dates_covered: [07-28, 07-29, 07-30]`; `date=2026-07-28` explicit query now ALSO `combined_board_window` (not `snapshot_read`), 57 candidates, `selected_date: "2026-07-28"` — same source, correctly date-scoped, no more independently-computed second number. Two tests that had encoded the old "explicit date must bypass combined reader" behavior as a guarantee (`test_query_endpoint_never_uses_combined_response_when_date_explicit` and the home-route equivalent) renamed and inverted to assert the new behavior; 7 targeted tests pass. **Deliberately not touched**: the legacy cascade functions themselves (`read_latest_intelligence_state_response`/`read_latest_intelligence_board_snapshot_response`) and `_cached_intelligence_response_from_legacy_cascade` stay as-is — they're now reachable only when the flag is off or the combined reader throws, which is a legitimate fallback, not dead code. Retiring that fallback entirely (making combined-board the ONLY path, flag and all) is a further, more invasive step, deliberately left as a follow-up rather than bundled in under time pressure. |
| **116** | 🟡 **#112 follow-up: odds_history keyvalue writes now fall back to artifact-publish on oversized payloads, matching #43/#108's pattern — SHIPPED and deployed 2026-07-28, pending live confirmation on the next natural refresh cycle.** #112's four prior size-reduction fixes this session (per-row strip → shard-wide field-strip sweep → history limit 50→20 → shard-wide entry-count trim) were each confirmed individually effective (payload measured 18,906,706 → 11,272,980 bytes) but still over the 8,388,608-byte keyvalue ceiling — and critically, `_sync_odds_history_for_refresh`'s three `_keyvalue_write_json_file` calls raised `KeyValuePayloadTooLarge` and aborted the whole per-shard write on any oversized payload, so **none of that trimming could ever actually land on disk**: every cycle re-read the same stale, still-oversized base and recomputed a smaller-but-still-too-big result from it, never converging. **Fix:** routed the three writes through `_write_state_payload` (`pipeline/intelligence_state.py`, the #43/#108 fallback: try keyvalue, fall back to local-disk write + `publish_hot_artifact` on `KeyValuePayloadTooLarge`). That alone wasn't sufficient — `read_json_file` in keyvalue-backend mode consults Redis ONLY, so the fallback's local-disk write would be invisible to every downstream reader; added a matching dual-source read (keyvalue + direct local-disk, freshest `updated_at` wins, mirroring `_read_state_payload`) to **both** the write-side dedup helper (`_load_shard_existing_markets`) and the actual board reader (`odds_control_plane.load_odds_history_payload_for_sport`) — without the second one, the fix would converge the writing service's own next cycle but never reach the board. Also allowlisted the two odds_history paths that live under `data_root()` (`*_source/tracking/odds_history/*.json`, `*_source/artifacts/*/odds_history/*.json`) in `HOT_ARTIFACT_PATTERNS` so `publish_hot_artifact` can actually cross-service-sync the fallback write to web, not just leave it on the writing service's own disk (the third path, `reports/odds_control_plane/odds_history/`, is outside `data_root()` by construction and can only ever help the writing service's own next-cycle read — noted in the allowlist comment, not fixed, since it isn't reachable by the publish mechanism at all). New regression test (`test_history_sync_falls_back_to_artifact_when_too_large_for_keyvalue`) forces the fallback via a 1-byte `SYNDICATE_KEYVALUE_MAX_BYTES`/`SYNDICATE_KEYVALUE_WARN_BYTES` ceiling and confirms both the local-disk write lands AND the board reader (`load_odds_history_payload_for_sport`) sees it. All 3 services deployed and confirmed `live`; `/api/ops/odds-refresh/status` shows no `KeyValuePayloadTooLarge` post-deploy, but the last refresh tick before that check was a pregame-cadence no-op skip (nothing due), not a real odds_history sync cycle — **full convergence on an actually-oversized shard has not yet been observed through a real post-deploy cycle**. Given this session's pattern on this exact item (four prior "confirmed live but still insufficient" rounds), treat this as shipped-not-yet-proven until the next real MLB sweep is checked for the error. |
| **117** | 🟡 **Doubleheader event_id/gamePk collision — root-caused AND fixed at the code level, SHIPPED and deployed 2026-07-28, but a related upstream data-integrity issue surfaced during verification that is NOT covered by this fix.** Found live: CLE @ CIN, a same-day doubleheader, showed a "LIVE, 7th inning" candidate whose `last_updated` was ~21.7h stale and whose attached `movement`/`odds_history` (joined by exact `market_id` at [intelligence_state.py:2569](pipeline/intelligence_state.py:2569), itself correct as written) resolved to the OTHER, not-yet-started game's pregame odds (embedded `row.commence_time` pointed at the 6:10 PM game while the candidate was for the live 12:40 PM game). Only one set of 5 candidates existed for the matchup, not two. **Two confirmed, source-level root causes, both fixed:** (1) [pipeline/intelligence_state.py:2540](pipeline/intelligence_state.py:2540)'s `attach_market_id` call (and `market_id.py`'s own internal fallback) preferred `matchup` ("CLE @ CIN", identical for both games) over `gamePk`/`game_id` whenever a candidate's `event_id` was empty — reordered to try gamePk/game_id first, matchup only as the last resort when no numeric game id exists at all. (2) The dedup identity tuple in `intelligence.py`'s `collect_candidates` loop had no game-identity field, so two doubleheader games produced byte-identical tuples and the second game's candidate was silently dropped as a "duplicate" before scoring — now appends gamePk/game_id/event_id to the tuple when present. New regression tests (`tests/test_market_id.py`, `test_collect_candidates_keeps_both_games_of_a_doubleheader_distinct` in `tests/test_intelligence.py`) confirmed to fail against pre-fix source via `git stash` and pass post-fix — 5/5. Deployed to all 3 services, confirmed `live`. **Full live re-verification of the exact original symptom was not possible**: by the time the deploy landed (~70 min after the bug was found), the 12:40 PM game had gone Final and the 6:10 PM game hadn't started yet — the "live + wrong-game-data" window had closed for today's specific occurrence. Code correctness rests on the unit tests, not a live symptom replay. **New, more concerning finding surfaced while re-checking**: `/mlb/api/cards`'s `gamePk`↔`startTime` mapping for this exact doubleheader **flipped between two checks 70 minutes apart** — `gamePk 824489` was `12:40 PM/live` at the first check and `6:10 PM/Scheduled` at the second; `824490` went the other way. This is either MLB's schedule provider reassigning game_pks mid-day (unusual but not impossible for doubleheaders) or a real ordering/caching bug in how `/mlb/api/cards` assembles the games list — **not diagnosed, not fixed, and this fix (#117) does not protect against it**: preferring `gamePk` as identity is only as reliable as `gamePk` itself being stable across reads, which this observation calls into question. Also very likely related to #111's still-open "the actual mechanism... worth a dedicated session" finding. **Next session should start here**: reproduce the gamePk/startTime flip deliberately (poll `/mlb/api/cards` every few minutes across a real doubleheader and log every `(gamePk, startTime, status)` tuple seen) before assuming #117's fix is sufficient long-term — if gamePk itself is unstable, the identity fix needs a different, more stable anchor (e.g. a composite of team-pair + game-number/sequence, not team-pair + gamePk). **Correction, same session**: re-checked MLB's own authoritative Stats API (`/api/v1.1/game/<gamePk>/feed/live`) directly for both gamePks — `gamePk` itself IS completely stable (824490 = doubleheader game 1, 824489 = game 2, confirmed via the feed's own `game.doubleHeader`/`game.gameNumber` fields, unchanging). The flip was Syndicate's OWN `/mlb/api/cards` showing wrong data at one point, not gamePk instability — narrowed to a SECOND, independent doubleheader collision, now found, fixed, and deployed: `_tracked_game_lines_index` (`syndicate/features/mlb/cards.py`) collapsed a doubleheader's two games into one team-name-keyed entry, discarding one game's real odds outright; every card for either game then looked up the same single (wrong, for one of them) entry. Fixed by keeping all rows per team-pair and disambiguating by matching each row's own `commence_time` against the specific game's `gameDate` (both real ISO timestamps, confirmed via a live artifact pull: OddsAPI's raw rows carry `commence_time`, MLB's `dateTime` survives onto `game["gameDate"]` via `_schedule_context`). 4 new tests in `tests/test_mlb_tracked_game_lines_doubleheader.py`, confirmed to fail pre-fix/pass post-fix. Deployed and confirmed live. **First post-deploy check looked like a persisting symptom (both games still showed identical `markets.ml`/`markets.totals`, -142/+120, total 9.0) but turned out to be a false alarm, run down and explained, not a bug recurrence.** Checked `_betting_payload_by_game` (`cards.py:1846-1895`, the PRIMARY market source, which only defers to the `_tracked_game_lines_index` fallback just fixed when primary data is missing) — its `season_betting_card_day_path` lookup is correctly keyed by `game_pk`, not team names, confirmed by direct code read. Pulled the artifact directly: **no `season_betting_day_2026_07_28.json` exists at all yet** (last synced date is `2026_07_27`) — so `_betting_payload_by_game` returns empty for today regardless of gamePk, and the fallback this item fixed is what's actually serving both cards. Pulled the raw odds snapshot directly to check why the fallback still returned identical data: **only ONE CLE@CIN row exists in the live feed now** (`retrieved_at` ~20:58Z) — the finished 12:40 PM game's row had already been dropped from the feed entirely (bookmakers stop quoting closed games), leaving only the 6:10 PM game's row, whose `h2h` is exactly `{home_odds: '+120', away_odds: '-142'}` — an exact match to what both cards showed. **That's the fallback correctly returning the only real entry that exists, not a bug** — with only one candidate, there's nothing to disambiguate. The fix is confirmed working as designed. **Separate, real gap found along the way, not fixed**: today's `season_betting_card_day_path` artifact not existing at all means MLB's PRIMARY betting/recommendation data is unavailable for all of today's games, doubleheader or not — matches the pattern already documented in #68's own `BETTING_PAYLOAD_READ` diagnostic (`betting_game_count 0`). Worth checking whether this is a one-off sync gap or a recurring issue; not investigated further this session. |
| **123** | 🟢 **Layer 2 Phase 4: board-level correlation badging — SHIPPED and deployed 2026-07-28 (commit `c7133785`).** Part of the Layer 2 board-redesign plan (`C:\Users\tempadmin\.claude\plans\starry-exploring-zephyr.md`). Annotates (does not suppress — user's explicit call) candidates correlated with another candidate on the same board, closing the "5 markets on one game shown as if 5 independent opportunities" complaint the CLE@CIN screenshot raised. Reused `correlation_engine.py`'s existing, real `compute_correlation` (previously wired only into `bankroll_manager.build_portfolio`'s suggested-portfolio panel, never the main board) rather than inventing new scoring. New `attach_board_correlation_flags(candidates, threshold=0.5)` groups by sport and does a pairwise pass within each group, attaching a `correlated_with` list to every candidate (empty on no matches). Threshold 0.5 — looser than `bankroll_manager`'s 0.65, which was tuned for bet-sizing risk, a different bar than board-visibility — both the badge-vs-suppress choice and the threshold were explicit user decisions, not guessed. **Correction to the original plan while implementing**: the plan assumed `recommendation_engine.py::rank_recommendations` was the board's ranking hook point; traced actual callers and found `rank_recommendations`/`rank_candidates` have **zero real callers** in the current pipeline — the real production sort/merge point is `_merge_candidate_pools` in `pipeline/intelligence_state.py`'s `_build_candidate_pool`, which is where this got wired instead. 5 new tests in `tests/test_correlation_engine.py`, built around empirically-measured correlation scores (0.56 for a real same-game/same-team fixture, 0.136 for an unrelated cross-game one) rather than guessed expected values. Existing `_build_candidate_pool` tests pass unmodified. **Verified live post-deploy** against the real board: 65 candidates, 36 carrying at least one real correlation flag with sensible scores (0.51–0.81) correctly clustering same-game WNBA props/ATS/moneyline (e.g. TOR @ MIN, POR @ LVA). 47 of 65 candidates carry the `correlated_with` key rather than all 65 — expected, not a bug: `combined_board_window` merges multiple dates' pools, and a date's pool only gets the flag once it's rebuilt post-deploy; the gap closes on each date's own next natural rebuild cycle (same caveat shape as #115/#116/#120). |
| **118** | 🟡 **Build a real live re-simulation model for NHL — currently has live STATE tracking but a frozen pregame MODEL.** Found while scoping Layer 2's live-lane qualification bar: `nhl/live_lens.py`'s `_live_game_payload` (line 294) pulls genuinely live data from the NHL's own live feed — score, period, clock, shots-on-goal, live skater/goalie boxscore stats (`_official_boxscore_payload`) — and `_live_odds_payload` pulls real live odds. But `_live_lens_card` (line 406) sources its actual projections (`score.get("total_mean")`, `score.get("margin_mean")`, `first10.get("prob_yes")`, and `_best_edges`' EV numbers) entirely from `_sim_payload(game)` — the **static pregame sim**, never re-run or adjusted against the live score/period/clock it's sitting right next to on the same card. A user could be looking at "Home ML EV +12%" computed before puck drop while the scoreboard next to it shows the home team down 3 in the third period. **User explicitly wants this built, not hidden or badged** ("we need to build models for these... add live modeling for them to the todo list") — this is the cheapest of the two live-modeling gaps to close, since the live state/odds plumbing already exists; the work is specifically an in-play win-probability model that consumes that already-flowing live state. **Reference pattern, already proven**: #102's WNBA/NBA work (`_live_lens_tick_payload`, extracted from vendored `api_cron_live_lens_tick`, called in-process from `{wnba,nba}/live_lens.py`) is the exact shape to replicate — a real pace/state-adjusted live projection function, not a bolt-on adjustment to the pregame number. Check whether `vendor/` has an equivalent NHL live-model implementation already sitting unused (as WNBA/NBA's did before #102) before building one from scratch. Not scoped further or started this session. |
| **119** | 🟡 **Build live game-state tracking AND a live re-simulation model for NFL and NCAAF — currently neither exists.** Found the same session as #118, same scoping pass. `nfl/live_lens.py` (confirmed via direct code read, its own comment says so verbatim: "This route no longer reuses the picks board. It reads the snapshot-backed cards payload.") and `ncaaf/live_lens.py` (same shape, file-size-consistent, not fully read line-by-line) both just reformat `build_cards_page_context`'s pregame weekly snapshot into rank cards — no live score/clock/state pull (unlike NHL, #118, which at least has this half), no live odds overlay, no live model. A "Live" lane candidate for either sport today is indistinguishable from a pregame one except for a label. **Bigger lift than #118**: needs both halves built — (a) a live game-state/odds pull (NFL/NCAAF equivalent of NHL's `_official_boxscore_payload`/`_live_odds_payload`, or MLB/WNBA/NBA's live feed integration) and (b) the actual in-play win-probability re-simulation model consuming that state, matching the #102 WNBA/NBA pattern. **User explicitly wants this built, not hidden or badged** (same direction as #118). Given football's slower, discrete-play pace (vs. continuous-clock sports), the live model shape may look meaningfully different from MLB/WNBA/NBA's (e.g. drive-based or play-based state transitions rather than continuous time-decay) — worth a design pass before implementation, not a direct port. Not scoped further or started this session. |
| **120** | 🟢 **Layer 2 Phase 2a: freshness SLA gate on `filter_candidates` — SHIPPED and deployed 2026-07-28 (commit `29258806`).** Part of the Layer 2 board-redesign plan (`C:\Users\tempadmin\.claude\plans\starry-exploring-zephyr.md`); follow-up to #117 (the "LIVE, 7th inning" candidate with 21.7h-stale odds — a data-freshness failure the existing edge-threshold gate had no way to catch, since it only ever checks edge quality). A candidate whose `last_updated`/odds-history age exceeds a per-sport, per-lane ceiling is now rejected before scoring, reason `stale_beyond_sla`. **Ceiling derived from already-tuned config, not a guessed constant, per explicit user direction ("derive from existing cadence")**: pregame = 3x each sport's configured `_pregame_sweep_interval_seconds` (2h default, 8h soccer, #82's design); live = the slate-wide live-tick interval (`_live_refresh_loop_interval_seconds`, 60s default) x 30 = 30 min — flagged in the plan as a deliberately conservative starting point since no per-sport live cadence config exists yet to derive from the same way as pregame. Only rejects when the sport's own manifest (`sport_manifest_last_updated`) also looks healthy — a stale manifest means the whole pipeline is down, a bigger problem this gate should surface, not paper over by also silently rejecting every candidate on top of it. 4 new tests in `tests/test_recommendation_engine.py`, confirmed fail-before/pass-after via `git stash`. **Real gotcha found and documented while writing the tests**: `filter_candidates` does `evaluation_records or _load_records_from_ledger(...)` — an empty list is falsy, so `evaluation_records=[]` still falls through to a REAL on-disk ledger read, which stalled indefinitely on this OneDrive-synced checkout (confirmed via `faulthandler.dump_traceback_later`, stuck in `_load_chunked_ledger_records`'s `Path.read_text`). Every test in the file must pass a genuinely non-empty list; now documented inline for the next person who hits it. Deployed to all 3 services, confirmed live; post-deploy sanity check shows the board still populated (63 candidates via `combined_board_window`), no emptying regression. **Phase 2b superseded**: originally scoped as a hide-vs-badge UI decision for sports without real live modeling (NFL/NCAAF have none; NHL has live state/odds tracking but a frozen pregame model — see #118/#119). User rejected that framing outright — "we need to build models for these... add live modeling for them to the todo list" — so #118 (NHL) and #119 (NFL/NCAAF) are logged as real feature builds instead, not implemented this pass. Phase 3+ (calibration-based suppression, correlation/concentration capping, lane-grid UI) not started. |
| **121** | 🟢 **`test_intelligence.py` took ~3h (user-reported) instead of minutes, and had 22 real failures nobody could see — root-caused to a single import-freezing bug that had been silently defeating test mocks across the whole intelligence query path; SHIPPED and pushed 2026-07-28 (commits `3601d98c`, `e9548067`, `1f47b2d6`).** User asked to fix the failures AND the runtime; both turned out to share one root cause. `syndicate/blueprints/intelligence.py` did `from pipeline.intelligence_state import _INTELLIGENCE_STATE_SERVICE` at module-import time (line 25), binding that name once at blueprint-load — so every test's `patch("pipeline.intelligence_state._INTELLIGENCE_STATE_SERVICE", ...)` silently touched a *different* object than the one the route actually called, and every `force_refresh` query test ran **real, unmocked candidate-pool computation** against real repo artifacts instead of its fixture. That's both why the mocked assertions failed (wrong data came back) and why it was catastrophically slow (real `collect_candidates`/scoring/evaluation-bundle work per test, observed 4+ minutes for a single test that should take under a second). **Fix:** moved the import into `_compute_intelligence_response` as a lazy, per-call import (same pattern `ops.py`'s admin debug endpoint already used correctly) so it always resolves the current `pipeline.intelligence_state._INTELLIGENCE_STATE_SERVICE`, patched or not. **Result:** `test_intelligence.py` full run (173 tests) went from effectively unbounded/hours to **173 passed in 2:12**. Fixing the import surfaced four more real bugs the broken mocks had been masking, all fixed same session: (1) `recommendation_engine.filter_candidates` rewrote a candidate's display `"market"` with its own lowercased internal grouping key (`"HR"` → `"hr"`) on every candidate that passed through it — now preserves the original display value, only synthesizing the internal key when the candidate lacked one (a first attempt also added a `"market_key"` field this same way, which turned out to clobber a *different*, more specific key set upstream — reverted that part, kept only the `"market"` fix). (2) `UniversalCandidate.to_dict()` (`intelligence_contracts.py`) unconditionally overwrote the display odds text with its own normalized-for-math float (`"+124"` → `"124.0"`, losing the sign convention) on every candidate `collect_candidates` wraps — same "prefer the original, only synthesize when absent" fix. (3) `response_builder._frontend_recommendation`'s rationale fallback used a bare `reasoning_text or summary or writeup` instead of the richer `_candidate_rationale()` (advanced-driver text, candidate-level signal detail, raw Statcast context) whenever "rationale" reached it still empty. (4) `_compute_intelligence_response`'s `parsed_request` assembly (added by an earlier, since-superseded session's dead-code fix) replaced the whole UI-facing formatted summary (`timing`/`board_scope`/`chips`/`sports`) with the engine's raw preferences dict whenever present — now merges just the engine's more-authoritative `requested_subjects`/`requested_markets` on top of the formatted base instead of replacing it wholesale. All 10 originally-reported failures plus 2 more that only became visible once mocks started actually working are fixed; one stale test assertion (`queue_mock.assert_called_once()`, carried over from a since-restructured code path) corrected to `assert_not_called()` with the reasoning documented inline. **Separately found and fixed, same session: `test_intelligence_state.py` was hanging indefinitely** (confirmed: killed after 20+ minutes at 100% CPU, no bound) in `BoardWindowWatchFailureDoesNotKillTheLoopTests::test_background_loop_survives_board_window_watch_exception`. Root cause: that test calls `service._background_loop()` directly with `_interval_seconds=0` but never mocks `_mlb_sim_subprocess_running`/`_odds_refresh_in_flight` — on a box where a real sim/odds-refresh genuinely was in flight (this machine, under concurrent multi-session load), `_board_build_deferral_reason` deferred every iteration with zero wait, spinning forever without ever reaching the `write_latest_intelligence_state` call the test relies on to stop the loop. Compounded by the fixture's hardcoded `"date": "2026-07-27"` going stale the moment real wall-clock time crossed into `2026-07-28` — `_watched_payload_eviction_reason` then evicted the payload as stale on every single iteration, and `_sync_persisted_queue_locked` re-read the same never-updated persisted-state file and re-queued the identical "stale" entry every time, an unconditional evict/re-sync cycle that also never reached the loop-stopping call. Fixed by mocking both ambient-state checks to `False` and pinning `central_today_iso()` to the fixture's own date (the established pattern this file's *other* date-fixture tests already use, just missing here) — **20+ min hang → 2.22s**. Full file: **193/196 passed in 5:08** (was: never finished). 3 remaining failures (`test_query_endpoint_*`, unrelated — a different, real-disk-path test-isolation gap) confirmed via `git stash` to fail identically on unmodified code; genuinely pre-existing, not a regression, left open. **Full `tests/` suite not re-run end-to-end after these fixes** (a prior 105-minute baseline run predates this session's changes) — worth a fresh full run before trusting an aggregate pass count, but not done this session given time already spent chasing the two hangs above. |
| **114** | 🟢 **A third, still-live instance of #111/#113's "two sources" shape — user said directly "we need ONE source" after seeing the stale chip again post-#113 — SHIPPED and deployed 2026-07-28.** #113 fixed the *stale browser-restored input* trigger; this is a completely different trigger for the identical downstream symptom (an explicit date silently bypassing `read_combined_intelligence_response`'s `not explicit_date` gate, falling back to the older single-date `snapshot_read` mechanism), reachable through **ordinary, correct use of the Today/Tomorrow day tabs** rather than any stale/leftover state. Root-caused by re-reading `renderFilterTabs`' own day-tab click handler in `intelligence.html`: clicking "Today" sets `state.date = TODAY_ISO` for **client-side filtering only** (per #93's own established design — the day tabs narrow one shared "All" fetch, they were never supposed to trigger a new server round trip) and correctly does NOT call `loadIntelligence()` itself. But the **next scheduled background poll** (`SyndicatePolling`, 60s interval) calls `intelligenceQueryPayload()`, which forwarded `state.date` to the server whenever it was truthy with no way to tell "day-tab client filter" apart from "deliberate explicit-date override" — so every background refresh after clicking Today/Tomorrow silently carried an explicit date from then on, permanently routing that tab's session away from the actively-maintained combined-board window onto the same slower-to-warm single-date snapshot mechanism #113 described. Confirmed **no exception path** was involved first (checked Render's log API for `COMBINED_BOARD_RESPONSE_FAILURE` over the full queryable week — zero hits — ruling out the "combined reader throws, falls through" branch as the cause) before tracing to this mechanism instead. **Fix:** added `state.explicitDateOverride`, a boolean tracked separately from `state.date` itself — `true` only when seeded from an explicit `?date=` URL param on load (an intentional deep link, matching #113's own reasoning) or set by the free-text `#board-date` input's toolbar-submit handler (an intentional user override); explicitly set `false` by the day-tab click handler. `intelligenceQueryPayload()` now gates on `state.date && state.explicitDateOverride` instead of `state.date` alone. Verified via `node --check` (syntax) and a live local-server browser check with a `window.fetch` interceptor: after clicking "Today" (date input populated to today's date, confirming the client-side filter still works), the next captured background-poll request body had `background:true` and **no `date` key at all**; a subsequent free-text-input + Refresh submit correctly still sent an explicit `date` with `force_refresh:true`. No automated test added, same reasoning as #113 (DOM/timer interaction, not meaningfully unit-testable without a real browser harness). **If this resurfaces a fourth time**: check `loadGameChips`/`loadSteam`'s own date handling next — they were deliberately left alone here (already real per-date server fetches by design, not client-filtered), but worth confirming they don't have an analogous "explicit vs. filter" ambiguity of their own. |

## In progress

- **#23 — Make the MLB daily sim memory-safe, then re-enable its trigger.**
  - ✅ *Validated 2026-07-25*: `daily_summary_2026_07_25.json` lands (15 sim artifacts
    published; `/mlb/api/cards` returns 15 cards via `_games_from_daily_summary`,
    which has no input unless the summary exists).
  - ✅ *Measured 2026-07-25*: batching off (`SYNDICATE_MLB_SIM_MAX_GAMES_PER_RUN=0`)
    is safe — 15 games, 15m00s, exit 0, **peak 1576MB / 2048MB**. Full-slate costs
    ~1.0 min/game vs ~6 min/game batched (each batch re-pays roster snapshots, a
    9.3MB statcast cache and an interpreter spawn). Do not reintroduce batching to
    "fix" an OOM without measuring peak memory first.
  - ✅ *Validated by ~90 min of production monitoring 2026-07-25*: event-driven
    per-game scoping genuinely narrows. After the cold-start run stored 15
    per-game fingerprints, later `fingerprint_change` launches scoped to **6
    games** (`20260725_183651`) and **9 games** (`20260725_185705`), both
    `exit 0` — not the whole slate. The earlier all-15 run was the documented
    "no stored fingerprints" branch, not a scoping failure.
  - ❌ Open: re-enable look-ahead with deference to an in-flight sim (reuse
    `_mlb_daily_sim_process_still_running`, mirroring the `any_live` guard).
  - ❌ Open: the 2700s timeout has still never been exercised (today ran 15m).
- **#61 — WITHDRAWN, not a bug.** Filed on a misreading: `board_contract`'s
  `pregame`/`live`/`top_overall` keys exist only in the EMPTY fallback shape the
  status endpoint returns when there is nothing to serve. The populated schema
  uses `cards` + `lane_counts` + `active_lanes`, so checking the fallback keys
  against a working payload reports 0/0/0 regardless. Verified 2026-07-26:
  **24 real cards**, `lane_counts {live: 24}`, e.g. `Nolan McLean hits allowed
  Over 4+, LAD @ NYM, conf 89.0%, edge 0.3662`. **When checking whether the board
  is populated, read `board_contract.cards` / `lane_counts` — never the fallback
  keys.**
  - Genuinely open, and much smaller: `pregame_count` is 0 while MLB has 10
    `preview` games. Either pregame candidates are not clearing an edge
    threshold, or lane assignment defaults everything to `live`. Worth a look on
    a fresh slate; it is a tuning/lane question, not an empty board.

- **#68 — 🔴 ANSWERED ON A LIVE SLATE 2026-07-26T21:29Z. Today's pool is 0 because
  classification prunes 100% of it as `missing_projection_or_odds`.**
  The reading #68 was blocked on, taken with `context_label: "2026-07-26"` —
  today — at 16:29 Central with **3 MLB games in progress and 1 pregame**
  (`/mlb/api/cards?date=2026-07-26`: 15 games, 11 final, 3 live, 1 preview). So
  this is **not** the dead-slate confound that invalidated the 02:36Z and
  21:17Z readings.
  `post_odds_enrichment 41 → post_state_filter 41 → pre/post_requested_market_filter 41 →
  post_dedupe_and_classify {normalized_in: 41, classification_pruned: 41,
  classification_reasons: {"missing_projection_or_odds": 41}, dedupe_pruned: 0,
  total_candidates: 0}`.
  Two facts the earlier readings did not have:
  - **The 41 are `mlb 1 {prop:1}` + `soccer 40 {game:8, prop:32}`, and nothing
    else.** Six sports generate zero. So the board is not losing a large pool at
    classification — it never had one. On 3 live + 1 pregame MLB games, MLB
    contributes **one** candidate. That starvation is upstream of everything
    #68 has been looking at.
  - **#77's producer gate is live and working** (`70ad2c9f` is an ancestor of
    the deployed `dc9fbe81`), so these 40 soccer rows are *not* the
    `is_unsimulated_placeholder` ones — those are already excluded. They are
    real fixtures that still arrive with neither a price nor a projection,
    i.e. #52's `no_sim_coverage` population.
  **Root-caused field-level and HALF FIXED. Two real defects, both measured by
  running the local candidate-generation and classification code over
  *production's own* card payloads** (`/mlb/api/cards`, `/soccer/mls/api/cards`)
  — production data, local code, no deploy. That combination is what every
  previous reading of this got wrong in one direction or the other.

  - **(a) A projection of exactly zero read as "no projection."**
    `_classify_candidate_with_reason` tested presence with
    `_safe_text(value, "") not in {"", "-"}`, and `_safe_text` is
    truthiness-based (`str(value or "")`), so `_safe_text(0.0, "")` is `""`.
    Not a corner case: `_append_game_bet_candidate` gives a **live** game-level
    candidate with no explicit `live_projection` the game's current combined
    score, which is **0 for every scoreless live game**, and
    `normalize_candidate` takes the first *present* field in its scan order —
    so that 0 also shadowed the real `model_probability` behind it. **All 32
    live MLS game candidates were pruned this way**, while
    `_candidate_has_usable_projection` — the predicate three functions up in
    the same file, which does the isinstance check correctly — returned True
    for every one. Two predicates for one question, disagreeing. Fixed with a
    shared `_candidate_value_is_present`; `None`/`""`/`"-"` still reject.
  - **(b) `shared_top_play_rows` was manufacturing picks out of a display
    panel — and (a) was the only thing hiding it.** `_build_top_play_rows`
    ([game_board_contract.py:375](syndicate/features/shared/game_board_contract.py:375))
    builds `{heading: panel title, name: panel item text}` from free-text
    panel items — no price, line or market, unlike `_build_prop_rows` directly
    below it. `_game_bet_candidates_from_game` scraped a price and an edge out
    of that prose and emitted a candidate **even when it found neither**.
    Production carried **56 such rows per MLS slate**, with picks reading
    *"Projected score: New England Revolution 1.4 - CF Montréal 2.1"*,
    *"Margin: 0.80 (home perspective)"*, *"Shots: … 10.1 | … 14.8"* and,
    literally, ***"Simulations: 400"***. ⚠️ **Fixing (a) alone would have
    published all 56 as live picks** — #77 again, one slate later. #77 fixed
    the placeholder half of exactly this and left the narrative half live.
    Now gated on the row expressing a **side** (over/under) or carrying a
    scraped price/edge — structural, not a prose blocklist, and it keeps MLB's
    real `"OVER Brooks Lee"` / `"UNDER Gerrit Cole"` panels (the 2026-07-23
    tests in `test_home.py` pin those and both pass).

  **Measured on one fetch of each payload** (two fetches disagree — games go
  final between them, which is what made an early 42-vs-38 look like a
  regression): MLS 16 games → 56 narrative rows dropped, **8 real Moneyline
  candidates survive and now classify KEPT instead of all-pruned**. MLB 38
  candidates, **identical before and after** — neither fix touches it.

  **Both fixes executed in production 2026-07-26T23:06Z** once #79 stopped the
  memory guard refusing the build: `post_dedupe_and_classify {normalized_in: 17,
  classification_pruned: 9, dedupe_pruned: 0, total_candidates: 8}`, and
  `/api/intelligence/status` served `candidate_count: 8`. The
  `"Simulations: 400"` / `"Run scripts/build_soccer_artifacts.py …"` rows were
  gone, so (b) is confirmed working.

  ⚠️ **But those 8 were not real, and I reported them as a win before checking.
  The user caught it: they were all flagged LIVE and none of those matches were
  live.** They were **yesterday's** finished MLS fixtures (`status`
  `"Sat, Jul 25 · 7:30 PM CT"`, read on the 26th). See #77b below — and note the
  chain, because it is the point: being falsely live is what gave them
  `live_projection = _game_current_combined_score(game) = "0"`, and fix (a) then
  correctly accepted that 0 as a projection. **Two bugs cancelling out.** With
  the liveness bug fixed, MLS produces **0** candidates again, because a
  moneyline carrying only a win probability has no field `normalize_candidate`
  recognises — **`confidence` is not among its projection sources**.
  **Do not "fix" that by adding `confidence` to the list.** Those fixtures are
  finished and priced at nothing (`odds: "-"` on every one, #52/#53). An empty
  board is the correct answer for MLS today, and the previous 8 were an
  artifact. Verified old-vs-new on one payload: MLS `{live: 16} kept=8` →
  `{unknown: 16} kept=0`; **MLB byte-identical** at
  `{final: 13, live: 1, scheduled: 1} kept=17`.

  🟢 **BOARD LIVE 2026-07-27T00:05Z: `candidate_count: 27`, real MLB props
  with prices, lines and edges** (`pitcher strikeouts UNDER Cristopher Sánchez,
  odds -120, line 7.5, edge 0.3735, conf 91.9%`). All 27 are from NYY @ PHI,
  `0-2 | In Progress | Bottom 3rd | 0 outs`, `is_final: false` — so the live
  flags are correct, checked after #77b.

  ⚠️ **CORRECTION, and it matters more than the result: the MLB diagnosis
  below was substantially wrong, and the fix I shipped for it is not what
  unblocked MLB.**
  - **"The worker sees stubs while web yields 38" was a CROSS-TIME
    comparison, not cross-service.** The worker reading was live; the web
    payload was fetched earlier, when 3 games were live and 1 pregame. Measured
    again side by side at 00:04Z: **web had exactly 1 game with ml/totals
    markets, matching the worker's `betting_game_count: 1`.** There was no
    worker/web gap by then. This is the same methodology error the handoff
    warns about three times, made while being careful about it elsewhere in the
    same session — a single-fetch A/B was used for the soccer work and not
    here.
  - **`season_betting_day_<date>.json` is not the source of `markets`.**
    `_cards_recommendation_payload_by_game` builds them from
    `daily_summary_<date>_locked_policy.json` via `_recommendations_by_game`;
    the betting-day file only *supplements*. That locked-policy file was
    **already allowlisted** (`daily_summary_*.json` matches it).
  - **The betting-day file does not exist on web either.** The repair pull
    fetched it successfully and got nothing back:
    `PULL_REPAIR_MISSING … ok=True written=0`. So it is simply not produced in
    this deployment.
  - **What actually filled the board:** game 823433 (NYY @ PHI) went from
    Preview to In Progress, and its live props became available. Not the
    artifact work.
  **The artifact work is still worth keeping** — the allowlist gap and the
  since=-can-never-repair-a-missing-file gap are both real and both latent —
  but they are robustness, not the fix, and #68's MLB half should be considered
  **unproven** rather than closed: it has never been observed failing with web
  and worker genuinely disagreeing at the same instant.

  *Superseded diagnosis, kept because the individual measurements in it are
  sound and only the comparison was wrong:* A once-daily artifact cannot
  be pulled by a lookback-bounded pull. The chain:
  1. `game_candidate_inputs` on the worker: MLB game blocks **all 0**.
  2. `game["markets"]` is the only source of those blocks —
     `_mlb_game_market_recommendation_rows` translates
     `markets["ml"]/["totals"]` into the `game_market_recommendations` that
     `_game_bet_candidates_from_game` reads.
  3. `cards_context_betting_games_loaded {"betting_game_count": 0}`, on a cycle
     where `sim_games 15/15`, `actual_games 15`, `games_built 15`. Everything
     else is healthy; only the betting payload is missing.
  4. `BETTING_PAYLOAD_READ date=2026-07-26 exists=False size=None
     payload_type=NoneType games_count=0` — the file
     `eval/seasons/2026/betting_day_payloads_retuned/season_betting_day_2026_07_26.json`
     **is not on the worker's disk at all.** Not empty, not misshapen: absent.
  5. It cannot arrive. `pull_hot_artifacts` filters by `since=` (observed
     `since=1785108524` = 23:28:44Z, ~5 min before the pull, `artifacts_received=0`
     on the `*2026_07_26*` pattern), and even an absent watermark floors at
     **`_MAX_PULL_WINDOW_SECONDS = 2h`**
     ([artifact_publisher.py:238](syndicate/features/shared/artifact_publisher.py:238)).
     This payload is written **once, in the morning** (~05:09 CT). Anything
     older than the window is permanently unreachable for a worker that does
     not already have it — an incremental pull can repair a copy that is
     *older* than web's, never one that is *missing*.
  ⚠️ **`artifact_status` reports this same path as `artifact_exists: true` /
  `data_health: "ready"`** — it is an any-of check across three paths and the
  other two do exist. **Do not trust that signal for this file**; it is what
  made the missing artifact look present all day.
  **The 2h ceiling is correct and must not simply be raised** — it was added
  after an unbounded pull OOM-crashed the worker and cascaded into web 502s on
  2026-07-25, and both sides load the whole response in memory. The fix wants
  to be a **narrow repair pull**: when a known-required artifact is missing,
  one un-clamped request scoped to that filename (`*season_betting_day_2026_07_26*`,
  `since=0`) returns a single file, so it carries none of the size risk the
  ceiling exists to bound. `artifact_status` already knows the required paths
  per sport, so the "what is missing" half exists.

  *Superseded framing (the "stubs" reading — right symptom, wrong layer):*
  `game_candidate_inputs` on the first successful cycle:
  `mlb {betting: 0, gameLens: 0, gameMarkets: 0, game_market_recommendations: 0,
  markets: 0, shared_prop_rows: 0, shared_top_play_rows: 0}` — **every market
  block empty**, with `game_state: ""` and `is_live: false` as well. Soccer on
  the same cycle has `markets: 5, shared_top_play_rows: 1`. So the worker's MLB
  dashboard games are not partially populated, they are **stubs**: nothing for
  `_game_bet_candidates_from_game` to read, which is why MLB contributed 1
  candidate (from `home_rails` props, not games) against the 38 the same
  function produces from web's `/mlb/api/cards`. **Next: find why
  `_MLBDataProvider.games()` → `build_cards_page_context()` returns stubs on
  the worker when it returns full games on web** — same code, separate Render
  disks. `_mlb_game_market_recommendation_rows` is called on that path and
  found nothing to build from, so start at what `build_cards_page_context`
  read. <br><br>*Superseded:* The worker generated
  **1** candidate for all of MLB, while the identical
  `_game_bet_candidates_from_game` over production's `/mlb/api/cards` payload
  produces **38** — 22 from a single live game, all priced and edged
  (`OVER Bryce Eldridge, Hitter Hits, odds 280, edge 39.2%, projected 1.2`).
  Same code, so the worker's `dashboard_games` must arrive **without the market
  blocks that function reads**. Established by elimination, not observed: web
  and refresh-worker read separate Render disks, and no existing trace reports
  the per-game market payload. `dc9fbe81` was checked and **exonerated** —
  `build_simulation_contract_from_context` copies its input
  (`_copy_mapping`) and `_normalize_game_context` returns a new dict, so
  removing it cannot have stripped `games`. A bounded
  `game_candidate_inputs` trace (two games per sport, presence and size only)
  is committed and answers this in one cycle **once deployed**.

- *Superseded reading (tomorrow's date, kept as the worked example):*
  The reading #68 was blocked on, taken off a healthy worker:
  `post_state_filter 40 → pre_requested_market_filter 40 →
  post_requested_market_filter 40 → post_dedupe_and_classify
  {normalized_in: 40, classification_pruned: 40,
  classification_reasons: {"missing_projection_or_odds": 40},
  dedupe_pruned: 0, total_candidates: 0}`.
  So the loss is **entirely** at classification, dedupe takes nothing, and of
  the two surviving suspects it is `missing_projection_or_odds`, unanimously —
  every candidate arrives with neither a model projection nor a market price.
  **The open work is now upstream of classification:** find why 40 candidates
  reach it with no projection and no odds. Do not re-instrument — #64's trace
  is sufficient and gave this in one read.
  Noted from the same window: `DEFERRED_BOARD_BUILD reason=sim_subprocess_resident`
  repeats while the MLB sim runs, so board rebuilds legitimately pause during a
  sim — that is the mutual-deferral guard, not a fault, and it is why cycles can
  be 10+ minutes apart and cannot be forced.

- ~~**#68 — Candidates drop to zero at `candidate_collection`.**~~ *(Filed as #63;
  renumbered 2026-07-26 — #63 was already the closed mutual-deferral test.)*
  Observed
  2026-07-26T02:36Z on refresh-worker: the stage counters read
  `post_state_filter 16 → pre_requested_market_filter 16 →
  post_requested_market_filter 16`, then
  `candidate_collection {candidate_count: 0, pipeline: "collect_all_recommendations"}`
  in 39ms, and everything downstream is 0 (`scoring input_count 0`,
  `board_input cards 0`). So the loss is between the last market filter and
  collection.
  - ⚠️ **Do not diagnose this on a dead slate.** It was seen at 21:37 local with
    the MLB slate finished (`mlb: 0` generated) and soccer candidates possibly
    for completed matches, so "0 recommendations" may be entirely correct. The
    same end-of-day confound is what made #61 look like a catastrophe.
    Re-check against a live morning slate first.
  - Note there are TWO collection pipelines and they behave differently:
    `collect_candidates_with_fallback_merge` was measured at 240 in / 240 out
    earlier the same evening, while `collect_all_recommendations` is the one
    reporting 0. Establish which one feeds the board before changing either.
  - ✅ **The instrument for this already exists — do not rebuild it.** #64
    (`a1638c39`, 2026-07-25) added an `INTEL_TRACE` across classification and
    dedupe emitting candidates-in, removals per stage, and a **count per
    rejection reason**. It ships a reading, not a diagnosis: the surviving
    suspects are `missing_selection` and `missing_projection_or_odds`. **The open
    work is taking that reading on a live slate**, then fixing whichever rule the
    counts implicate. This item is blocked on a slate, not on code.

- **#31 — NHL revamp Phase 5: local producers replace vendor subprocess.**

## Platform / correctness

| # | Item |
|---|---|
| **62** | **A re-pricing path that refreshes edges without a full Monte Carlo.** Behind #48. `run_mlb_daily_sim_job.py` only takes `--only-game-pks`, and `daily_update.py`'s only skip mechanism is `--preserve-started` (games past Preview), so there is no way to react to a price move except re-simulating. #48 removed prices from the sim fingerprint because the sim summary row is pure model output — win probabilities, run distributions, HR/prop likelihoods, **no odds and no edges** — and the market board joins odds at *read* time. That is correct for the board, but any artifact that *does* bake prices at sim time now goes stale until a lineup/line/tip-off trigger. Architectural, #27/#28 territory. |
| **42** | `source_cards_api_payload`'s cache can never hit — keyed on the file it rewrites. **Third instance of this pattern** (`build_mlb_market_board` fixed in `34c9427d`; avoided deliberately in `build_soccer_market_board`). Worth a rule, not three one-off fixes. |
| **37** | `logger.info` never reaches Render's log collector — use `print(..., flush=True)`. This is why the `NameError` in #8 hid for hours, and why #43's stale-date replay stayed invisible for a day. |
| **74** | 🟡 **SHIPPED 2026-07-27 (commit `0250ac82`), NOT YET FULLY VALIDATED.** A router-inferred `mode` silently overwrote the question's own intent (found 2026-07-26 while fixing headlines): `QueryRouter` classifies e.g. "Explain the best points targets across NBA and WNBA" as `player_analysis`; [intelligence_pipeline.py:86](pipeline/intelligence_pipeline.py:86) `_pipeline_mode_for_query_type` maps that to `"pregame"`; `_query_preferences` read `mode` as an **instruction** and replaced the parsed intent (`best_bets`) with `pregame_bets`. The blocked fix ("Attempted and reverted", 2026-07-26) is the one that shipped: `route_payload` now stamps `mode_inferred` alongside `mode` ([query_router.py](router/query_router.py)), `IntelligencePipelineRequest` carries it through, and `_call_black_box_intelligence` withholds an inferred mode from `run_intelligence_query` rather than forwarding it as an instruction. `syndicate/blueprints/intelligence.py` now also promotes the engine's own `parsed_request` (with real `requested_subjects`) to the top level, gated on this fix existing. ⚠️ **This code sat uncommitted in the working tree for a full session** before today — see [[project_closed_todo_not_shipped_gap]] equivalent lesson in Operational notes. ⚠️ **Not validated this session**: `python -m pytest tests/test_intelligence.py tests/test_intelligence_board_contract.py tests/test_query_router.py` was started but interrupted before completing (user: tests taking too long) — it had progressed cleanly through 55+ cases with zero failures before being stopped, which is supportive but not a completed run. Confirm with a full pass of those three files, or production observation of a `player_analysis`-routed query keeping its own `best_bets` intent, before closing this for real. |
| **39** | Make canonical board-state dual-write safe, then re-enable (disabled; doubled boot memory). |
| **38** | 🟡 **UNBLOCKED 2026-07-27** (was gated on #43/#66/#68; #43 and #66 are closed and #68's MLB half does not depend on these prints). Prune diagnostic scaffolding from `intelligence_state` **and** the rest of today's: `cards_context_*`, `board_contract_*`, `sim_contract_*`, `ODDS_JSONL_LARGE`, `KEYVALUE_PAYLOAD_COMPOSITION`, `BETTING_PAYLOAD_READ`, `game_candidate_inputs`, `PROCESS_ENUM_DEBUG`. ⚠️ **Keep `ROLLOVER_PROBE_BEGIN`/`END` and the dated `CANDIDATE_POOL_READY`/`BOARD_PUBLICATION_RESPONSE_READY`** — those exist because their absence caused three misreadings, and they are one line per cycle. Keep `ALL_PROCESS_MEMORY`/`CONTAINER_MEMORY` until #76 lands, since #79's fix is new. |
| **51** | `hasSampleData` is inverted — and it is **two sites, not one** (corrected 2026-07-26). [mlb/cards.py:2375-2376](syndicate/features/mlb/cards.py:2375) and the *shared* contract at [game_board_contract.py:622-623](syndicate/features/shared/game_board_contract.py:622) both set `hasSampleData` and `hasArtifactData` to the same expression (`not using_sample_data`), so the two can never disagree and the name means the opposite of what it says. The shared-contract copy means every sport on `game_board_v1` inherits it, not just MLB. Note `tests/test_archives.py:203-204` and `:1261-1262` assert both are true, so the tests currently lock in the wrong semantics and must change with the fix. |
| **59** | **Measure WNBA's real peak memory on a live slate (next games Tuesday).** *Reframed 2026-07-26: this no longer "decides #57" — #57 was closed by upgrading refresh-worker to pro/4GB, so the board build is no longer looking for a host.* What still matters is that **live-odds-worker's own headroom is unverified**: it runs the WNBA refresh leg in a 2048MB container, and [render.yaml:550-555](render.yaml:550) explicitly flags that as `UNVERIFIED ON A REAL WNBA SLATE`. The 1.3–1.5GB figure everything is reasoning from is a **code comment from a past incident, not a measurement** ([live_refresh_loop.py:1958](syndicate/features/shared/live_refresh_loop.py:1958)); what was actually measured 2026-07-25 was 412–652MB, on an All-Star day with one game, so it proves nothing. The instrumentation already exists: `basketball_props_smart_sim.py` has 9 `log_list_memory` call sites emitting to stderr, which produced **zero** lines that day (consistent with WNBA being idle, not with broken instrumentation). Watch `ALL_PROCESS_MEMORY` peaks on live-odds-worker through a full WNBA slate. **Measure peak, never median** — a median of 515MB hid a documented 1.3–1.5GB spike and nearly drove a bad placement decision. ⚠️ **#58 closing does not help here.** It cut quarter-sim CPU 73×, but the accumulators went from two 5,000-float lists to two arrays — a rounding error against a 1.3GB question. Take the measurement. |
| **56** | 🔴 **Web dies from health-check starvation, not memory.** Same incident, *different* failure: `"HTTP health check failed (timed out after 5 seconds)"`, `oomKilled: false`. `WEB_CONCURRENCY=2` × `GUNICORN_THREADS=1` gives the whole service **two concurrent requests**, and because `SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP=false` on web, intelligence persistence runs on the **request path** ([intelligence_state.py:2678](pipeline/intelligence_state.py:2678)) — so slow requests are routine, not exceptional. Two of them starve `/healthz` and Render kills the instance. render.yaml now sets `GUNICORN_THREADS=4`, **but that is not live** — Render only reads render.yaml on a blueprint sync. Threads not workers: each worker is a whole process on 2GB, and this is I/O-bound waiting. Real fix is to stop persisting on the request path. |
| **53** | **Prop ladder odds for all sports** (split out of #16). No `*_alternate` player market is fetched in any sport, so `_finalize_prop_market`'s `alternates` array is always empty and MLB's ladder surfaces have no book prices to compare the sim against. See #16 for the cost model and why this should ride #15's cadence tiering rather than get its own scheduler. |
| **24** | Look-ahead interval violations (~28min instead of 60). |
| **12** | Phase 4: smaller per-sport artifacts. |
| **30** | WNBA schedule-bootstrap cost. |
| **90** | NBA `available_dates()` scans all preferred artifact roots but `processed_path()`/`live_snapshot_path()` only resolve against the primary root since `757952e1` — a date can be listed and still 404 if it only exists in a secondary root. Dormant while NBA has one root in production. See Reconciliation 2026-07-27. |

## OddsAPI budget (after #14/#15)

- **#106** 🟢 **Event scoping SHIPPED 2026-07-28** (user-directed budget lever,
  the bigger of the two remaining after the still-open #16 market-drop
  decision). `fetch_live_game_lines_for_date`'s per-event loop
  (`fetch_mlb_oddsapi_local.py`) fetched the 18 segment/alternate markets for
  **every** game on **every** ~90s cycle regardless of that game's own state,
  as long as *some* game on the slate was live — including games hours from
  first pitch and games already final. Now decided per event: live/within-
  75min-T-window games unchanged, everything else skips the per-event
  segment fetch entirely when the slate-wide core call (#17) already covered
  it. Uses #100's canonical `game_state.py` (not a new check) against the
  day's `schedule_raw.json`; fails open on any uncertainty. Verified against
  real production data (today's actual 12-game slate: 10 full-tier, 2
  reduced — the one finished and one postponed game). `SYNDICATE_ODDS_EVENT_SCOPING_ENABLED=false`
  reverts to prior behavior.
  ⚠️ **First landed as dead code** (`7acdf2e0`): built inside
  `refresh_mlb_oddsapi.py`'s `fetch_live_odds_incremental`, reachable only
  via `--mode fast`. The actual command `live_refresh_loop.py` launches uses
  `--mode full` (this script's own argparse default), which calls a
  completely different function (`fetch_and_write_live_odds_for_date` →
  `fetch_live_game_lines_for_date` in `fetch_mlb_oddsapi_local.py`) that the
  first commit never touched. Only caught by checking
  `/api/ops/odds-refresh/status`'s captured stdout — Render's log API never
  surfaced this subprocess's own prints at all (capture mechanism unclear),
  so log-line verification alone would have reported success on dead code.
  Refixed same session (`655a53cd`), re-verified through the real entry
  point. `refresh_mlb_oddsapi.py`'s copy of the scoping logic left in place
  (harmless, still correct, just on the less-traveled fast-mode path) rather
  than risk a rushed cross-file refactor — worth consolidating later, not a
  "two disagreeing predicates" bug since both compute the same thing from
  the same canonical module.
- **#107** 🔴 **`SYNDICATE_ODDS_MARKET_TIER` (#82 Phase 2, logged SHIPPED
  before this session) is apparently never read in `fetch_mlb_oddsapi_local.py`
  at all** — found while fixing #106. It's only checked in
  `refresh_mlb_oddsapi.py`'s `fetch_live_odds_incremental`, the same
  effectively-unused `--mode fast` path #106 was dead-code'd on. If
  production's real path (`--mode full`) never reads this env var, the
  entire #82 Phase 2 segment/alternate cost reduction may never have taken
  effect, despite being logged closed. Circumstantially consistent with
  tonight's own burn numbers: `segment` (182k) and `alternate` (91k) credits
  stayed high the whole session regardless of live/pregame state, which is
  what you'd expect from a tiering flag that's wired into unused code. **Not
  fixed here** — deserves its own same-instant verification (check
  `/api/ops/odds-refresh/status` during an off-hours window, confirm whether
  `market_tier` ever shows up as anything but `full`) before trusting either
  the "shipped" label or this suspicion. If confirmed, the fix is almost
  certainly "read `SYNDICATE_ODDS_MARKET_TIER` in
  `fetch_live_game_lines_for_date` too, gated the same way #106 gates event
  scoping" — small, but needs the same real-production-data verification
  #106 got, not just a code read.

> **Measured burn — first genuine full-day window, 2026-07-27T01:55Z:**
>
> | Window | Burned | /hour | Projected 30d |
> |---|---|---|---|
> | **86,572s (50,544 obs)** | **371,563** | **15,451** | **11.12M** |
>
> MLB 96.3%, soccer and WNBA noise. Provider `used`-delta and local window sum
> agree exactly. The earlier short-window table (5.79M vs 1.59M off the same
> 525 credits) is retired; its lesson — full-day windows only — is what this
> reading finally honors. See #15 for why the intervening 1.42M/mo period
> average was measuring a degraded system, and for the decision points.
>
> **The arithmetic of getting under 5M** (2026-07-27, from #16's audit model
> ~573 credits/sweep × ~625 sweeps/day; attribution shipped `c01302f1` will
> replace these estimates with measured splits after one full slate):
>
> | Lever | Type | Est. effect on MLB's 358k/day |
> |---|---|---|
> | #16(a) drop 8 `alternate_*` | **USER product call** | −21% (−120/sweep) |
> | #16(b) drop 6 `first7` | **USER product call** | −16% (−90/sweep) |
> | Off-hours gate (no sweeps when nothing live/imminent) | engineering | −25–35% of sweeps (by_hour histogram will measure) |
> | Event scoping (props+segments only for live/near games; ~5 of 15 avg) | engineering | −60–70% of per-event burn during active hours |
> | Cadence tiering (segments every Nth sweep) | **USER reversal of #15's "do not tier"** | further, if needed |
>
> (a)+(b) alone: 358k → ~227k/day ≈ 6.8M/mo — **not enough on its own.**
> (a)+(b) + off-hours + event scoping: est. **~60–90k/day ≈ 1.8–2.7M/mo**,
> leaving genuine headroom for football season. Sequence: read tomorrow's
> attributed slate first, then decide (a)/(b), then build scoping/off-hours
> against measured numbers rather than this table.
>
> ⚠️ **Hard sequencing dependency, flagged 2026-07-27: do not build "Event
> scoping" before #100.** Event scoping's whole premise is a reliable
> per-game "is this live or near-live" decision (which games get full
> props+segments vs. drift-only). Building that on the pre-#100 fragmented
> game-state checks (26 sites, at least 6 confirmed reading MLB's
> `abstractGameState` alone and misreading warmup as live) risks either
> overcharging (a warming-up game wrongly gets full markets) or worse,
> undercharging at the moment it actually matters (a game about to go live
> gets denied full markets because its state read as still-drift). **#100
> shipped and deployed 2026-07-27/28 (`110461f6`)** — build event scoping's
> per-game decision on `syndicate.features.mlb.game_state.mlb_status_is_live`/
> `mlb_status_is_final`, not a new bespoke check.
>
> **These are required work, not optimisations. The target is 5M.**
> The plan currently reads 15M, but it was bumped to 15M *because of a real
> prior overage* — it is remediation, and the objective is to cut burn enough to
> **downgrade back to 5M**. Do not read the current 13.9M remaining as headroom.
> Measure each reduction against `/api/ops/oddsapi/quota` so the downgrade is
> made on evidence rather than on a projection that has already been wrong once.
> #19 (cap soccer props, ~2,400 credits/sweep) also gates enabling #44b, which
> forces cache-bypassed soccer refreshes and should stay dark until burn fits 5M.

**16** — **AUDIT DONE 2026-07-25, decision needed.** After #17 the per-event call
still requests **24 segment markets per game** ≈ **360 credits/sweep** on a
15-game slate, dwarfing the 42 that #17 saved. Findings:

- All 27 markets *are* parsed by `_extract_game_lines`, so nothing is dropped
  at parse time. The waste, if any, is further downstream.
- **The Layer 1 market board renders only `full_game`.** Measured on the live
  2026-07-25 board: 1,336 rows across 15 games, **zero** segment rows. The 24
  segment markets never reach it.
- Segments *do* reach the cards surface — `cards.py:1844` iterates
  `full/first1/first3/first5/first7` and `static/mlb/cards_source.js:1030`
  renders an "F7" tab.
- **The sim produces `full/first1/first3/first5` but not `first7`** (see
  `_daily_summary_row`), so the 6 first7 markets render book lines with no model
  behind them — the MLB analogue of soccer's `no_sim_coverage`.
- **Game-line alternates collapse to a single lane.** `_select_primary_game_*_lane`
  keeps only the most-balanced lane per segment; unlike `_finalize_prop_market`,
  which preserves an `alternates` array. So the 8 `alternate_*` markets only
  influence *which* lane wins.

Two candidate cuts, both needing a product call rather than a code judgement:
**(a)** drop the 8 `alternate_*` markets ≈ **120 credits/sweep** — but they
currently compete to be the primary lane, so the displayed line could change;
**(b)** drop the 6 `first7` markets ≈ **90 credits/sweep** — but the F7 tab
would lose its lines, and it already has no sim projection.

**Props half of the audit (2026-07-25) — and a real gap: prop ladders are
never fetched.** MLB requests 7 base hitter markets (`batter_hits`,
`batter_total_bases`, `batter_home_runs`, …) and the pitcher equivalents.
**No `*_alternate` player market is requested anywhere, in any sport.** OddsAPI
serves prop ladders only through those alternate markets, so:

- `_finalize_prop_market` computes `primary` + `alternates`, but with one lane
  per prop the `alternates` array is **always empty**. The ladder plumbing
  already exists and is being fed nothing.
- MLB already ships ladder *surfaces* — `/mlb/hitter-ladders`,
  `/mlb/pitcher-ladders`, `/mlb/k-ladder-targets` — built from the **sim**.
  Without book ladders there is nothing to price them against, so no edge can
  be computed anywhere off the primary line.

**Efficient way to get them.** OddsAPI bills 1 credit per market per region per
request, so batching markets into one request saves nothing — only market
*count* matters. Levers, in order:
1. Fetch alternates only for markets that have a ladder surface, not all 7+.
   (~+1 credit/market/event; +7 markets on a 15-game MLB slate ≈ +105/sweep.)
2. Run ladders on a **slower cadence** than base props — ladder shape moves far
   less than the primary line. This is the same mechanism as #15's tiering, so
   do it as part of that rather than as a separate scheduler.
3. Alternates are per-event only, like segments, so they cannot ride #17's
   slate endpoint.
4. Fund it from the cuts above: (a)+(b) free ~210 credits/sweep, more than the
   ~105 ladders would cost — so ladders can be **net credit-negative** if paired
   with the trims rather than added on top. ·
**19** cap soccer props (~2,400/sweep; measured 2026-07-27: soccer burned **18 credits in 24h** with #44b dark, so this is a *gate for enabling #44b*, not a live leak) · **20** verify refresh runs can't stack
(partly addressed by #25's fail-closed marker) · **21** keep 10×-billed historical
endpoints out of prod · **22** stop retrying 4xx in vendor clients

## Feature work

**26** NBA/WNBA board parity (ESPN athlete IDs, headshots, live projection/line
movement — mirror `288d1e5e`, `604f96f6`, `83315e5c`) · **27** Layer 1 Phase 5:
Layer 2 consumes Layer 1 · **28** Layer 1 Phase 6: market board → NHL, then
NFL/NCAAF/NCAAB · **32–36** NHL revamp Phases 6–10 · **52** MLS: 1432 `unmatched_no_sim_coverage`
rows (~71% of the board have no sim projection at all — separate from #44) ·
**69** "last simmed" per-league rollout — MLB has `simUpdatedAtDisplay` from
`9b5806c6`; needs other sports plus the *reason* (lineup vs injury vs tip-off).
*(Filed as a second #53; renumbered 2026-07-26 — #53 is prop-ladder odds.)*

## Done

**Closed items live in [`todo_closed.md`](todo_closed.md)** — 22 items from the
2026-07-25/26 session plus everything before it. That file is a *record*; every
lesson from a closed item that should still change what a future session does was
kept here instead, under Operational notes. If you need to open the archive to
avoid repeating a mistake, the lesson is filed in the wrong place — promote it.

> **#43 is NOT closed**, despite having appeared in the closed line until
> 2026-07-26. The write-size fix shipped and is real, but the item's own stated
> criterion — `candidate_count > 0` **with a snapshot timestamp** — was never met,
> and the item simultaneously sat in "In progress" saying exactly that. Listing a
> fix as closed while its verification is outstanding is how #8's "empty board"
> came back under a second root cause.

---

## Operational notes worth not rediscovering

- **A top-level `from module import name` freezes that name at import time —
  patching the module attribute later never reaches an already-bound copy in
  another module.** (#121) `syndicate/blueprints/intelligence.py` imported
  `_INTELLIGENCE_STATE_SERVICE` this way; every test's
  `patch("pipeline.intelligence_state._INTELLIGENCE_STATE_SERVICE", ...)`
  silently no-opped against the route's own frozen copy, so `force_refresh`
  query tests ran real, unmocked compute instead of the fixture — both wrong
  results AND catastrophic slowness (minutes per test) from the same bug.
  `syndicate/features/intelligence/api/response_builder.py` already has the
  fix pattern documented for `build_intelligence_overview` specifically
  (`_patch_build_intelligence_overview`, patches both import sites) — but
  that only covers one name. **Before patching ANY module-level singleton or
  function from a test, grep every OTHER module for a top-level
  `from that_module import that_name` import of it** — a lazy/local import at
  the call site (already the correct pattern in `ops.py`) is the permanent
  fix, not a per-test dual-patch.
- **Tests that call threading/background-loop code directly must mock every
  ambient-machine-state check that loop consults, not just the seams the
  test is nominally about.** (#121) `test_background_loop_survives_board_
  window_watch_exception` called `service._background_loop()` with
  `_interval_seconds=0` but never mocked `_mlb_sim_subprocess_running`/
  `_odds_refresh_in_flight` — on a box where either was genuinely true (this
  machine, under concurrent multi-session load), the loop's real deferral
  logic spun forever with zero wait between iterations, never reaching the
  call the test needed to stop it. Same test also had a hardcoded fixture
  date that silently went stale once real wall-clock time passed it,
  independently causing the identical infinite-loop shape via the eviction/
  re-sync path. A test that reads real system state (process list, memory
  headroom, wall-clock "today") is not a unit test, it's a flaky timer with
  extra steps — this file already has the right pattern elsewhere
  (`patch.object(intelligence_state_module, "central_today_iso", return_value=...)`
  on its other date-fixture tests); it's just easy to miss on a new test
  that calls loop internals directly instead of going through the normal
  queue-and-poll interface.
- **Unbounded payloads crossing into the shared keyvalue store caused three
  outages in one day** (#43, #54, #50) — the same bug in different clothes, each
  fixed individually before the pattern was seen. #60 now enforces a ceiling in
  `refresh_state_store.write_json_file` / `write_text_file` that **fails loudly**
  with key, size and caller. **Silence was the actual defect**: each failure
  presented as something else entirely and cost hours. A rejected write that
  names itself is recoverable; one that closes the connection and gets swallowed
  by a generic handler is not. Do not add a new write path to that store without
  a bound.
- **Measure a candidate host's peak, never its median.** live-odds-worker's
  median of 515MB nearly justified putting the board build on a box whose WNBA
  leg is documented spiking to 1.3–1.5GB. Related: a *code comment* is not a
  measurement — the 1.3–1.5GB figure itself has never been verified (#59).
- **Deliberate `render.yaml` overrides — a blueprint re-apply must not undo
  these** (from #40, now closed): `SYNDICATE_ENABLE_MLB_DAILY_SIM_TRIGGER=true`,
  `SYNDICATE_MLB_SIM_MAX_GAMES_PER_RUN=0`, `SYNDICATE_LOOK_AHEAD_ENABLED=false`,
  `SYNDICATE_MLB_EVENING_NEXT_DAY_SIM_ENABLED=false`,
  `SYNDICATE_INTELLIGENCE_CANONICAL_BOARD_STATE=false`,
  `SYNDICATE_ENABLE_SOCCER_RESIM_TRIGGER`, `SYNDICATE_SOCCER_RESIM_TICK_OWNER`,
  plus `plan: pro` on refresh-worker (pinned so a sync cannot undo the paid
  upgrade). ⚠️ **The comments around the intelligence-loop vars currently
  contradict their values — see #70 before trusting the prose in that file.**
- **Exactly ONE service may own the intelligence-state background loop.** Today
  that is refresh-worker (`true`); web and live-odds-worker are `false`. Two
  owners would recompute the same state concurrently and reproduce the 2026-07-25
  collision on a different box.
- **A launch-time memory gate cannot see a collision** (from #55). It measures at
  ~250MB, *before* either pipeline grows. Any future gate of this shape has the
  same blind spot — gate on what the run will peak at, not what it starts at.
- **The quota store's eviction theory was never proven** (from #54). Making the
  payload O(1) removed it as an eviction target, which is why it stopped
  happening — not evidence of why it started. **If observations vanish again the
  theory is wrong**, and the next suspect is the shared store's own lifecycle.
- **Every board cycle emits TWO dated traces, and the second one is tomorrow.**
  `_compute_board_publication_response` builds today, prints
  `CANDIDATE_POOL_READY`, and then — only if today's pool is 0 — probes tomorrow
  with a second fingerprint pass and a second full pool build. The probe emits
  its own `overview_counts`, `artifact_status` and `candidate_generation`
  traces, so **`context_label` alone cannot tell you which half you are
  reading**, and a `tail` of the logs shows only the tomorrow half. The
  discriminator is ordering: **the first `overview_counts` burst of a cycle is
  today; everything after `CANDIDATE_POOL_READY` is the probe.** This trap has
  now cost three separate investigations (#65, #68, #78) — twice *after* #65
  documented it. It stays expensive because the date is not printed: the
  rollover decision is `logger.info("BETTING_BOARD_PUBLISH_DATE")` only, and per
  #37 that never reaches Render. Print it.
- **Before reconciling, check that shipped work reached this list.** Run:<br><br>`git log --format=%s -80 | grep -oE '#[0-9]{1,3}' | sort -u`<br><br>…and confirm every ID appears in `todo.md` or `todo_closed.md`. This was #71,
  closed 2026-07-27 after an audit found #64 to be the only historical gap — but
  the gap mattered: #64 shipped the exact instrumentation another item was still
  asking to build. Run for 2026-07-27: 30 IDs, all present.
- **The inverse of #71 is worse, and #71's check does not catch it: a todo item
  marked closed does not mean its code ever reached git.** Found 2026-07-27:
  #87 and #88 were both recorded closed in `todo_closed.md` from the prior
  session, but `git status` showed both fixes (plus an unrelated #74 fix and
  a batch of undocumented intelligence.py fixes, filed as #91) sitting as
  **uncommitted working-tree changes** — real, tested, correct work that
  simply never got committed before the session ended. They only reached
  `main` when a later session ran `git commit`/`git push` (`0250ac82`). A
  session can do everything right and still ship nothing if it stops before
  the commit. **Before trusting a recent "closed" entry as proof a fix is
  live, run `git status`/`git diff` and check the files that entry names are
  actually clean against `HEAD`** — don't take the doc's word for it,
  especially right before building on top of that fix or deploying.
- **A cross-service comparison must be same-instant, or it is a cross-TIME
  comparison wearing a disguise.** #68's MLB half was diagnosed as "the worker
  sees stubs, web yields 38 candidates" off a worker reading taken live and a
  web payload fetched earlier in the evening. Measured side by side minutes
  later, both showed **1**. Nothing was wrong between the services; the slate
  had simply gone final in between. The soccer work in the same session used a
  single-fetch A/B *specifically* because `/mlb/api/cards` moves under you —
  and then the MLB work did not. If two numbers come from two fetches, they
  are not evidence of a difference.
- **Run the real code over production's own payloads before instrumenting.**
  `/mlb/api/cards` and `/soccer/mls/api/cards` are public and carry the exact
  game dicts candidate generation consumes, so `_game_bet_candidates_from_game`
  and `_classify_candidate_with_reason` can be run against them locally — real
  data, real code, no deploy, no waiting for a cycle. That is how #68's two
  defects were found and how both fixes were measured, after three sessions of
  local mirrors and production logs each answering only half the question.
  Fetch **once** and A/B in-process: the endpoint is live, games go final
  between two fetches, and the counts move under you.
- **A truthiness test is not a presence test.** `_safe_text(value, "")` is
  `str(value or "").strip()`, so `0`, `0.0` and `False` all come back `""`.
  #68's board-emptying bug was exactly this on a numeric field, and the same
  shape is still in `normalize_candidate`'s odds handling. Check any
  `_safe_text(x, "") not in {"", "-"}` that guards a number.
- **"Empty board" is a symptom with at least two distinct root causes** (from #8
  and #43) — a `NameError` in one case, an oversized Redis write in the other.
  Do not treat it as a solved class, and do not assume a past fix covers a new
  occurrence.
- **An un-parenthesized `[type]$obj.prop` as a bare command argument is NOT a
  cast in PowerShell.** In argument-parsing mode, `-Foo [string]$x.prop` binds
  `-Foo` to the literal text `[string]` and then evaluates `$x.prop` as a
  *second*, separate, unbound argument — for a property access this actually
  stringifies the whole parent object (`$x.prop` on its own line is fine;
  `[string]$x.prop` in argument position is not the same expression). #87 hid
  this for an unknown number of ticks because the resulting garbage path simply
  never existed, so `Test-Path` returned false and the caller silently took the
  "must rerun" branch instead of erroring. Grep `unified_daily_update.ps1` for
  other bare `[type]$` casts passed as command arguments before assuming this
  was the only instance; wrap the cast in parens: `-Foo ([string]$x.prop)`.
  Verify with a two-line repro (`function T {param([string]$X) $X}; T -X
  [string]$obj.prop`) rather than trusting it by inspection — it looks correct
  at a glance. **Checked 2026-07-27:** every other `[type]$var.prop` in
  `unified_daily_update.ps1` sits inside `(...)`, `{...}`, or a comparison
  operator (expression-mode parsing, where casts work correctly) — #87 was the
  only bare-argument instance. Re-grep if new command calls are added with a
  cast argument.

- **Patching `preferred_source_roots` only works if you patch it where it's
  actually called from.** `757952e1` moved NBA's `processed_path` and NHL's
  `processed_path`/`scoreboard_snapshot_path`/`slate_summaries` behind
  `odds_control_plane.current_odds_root_for_sport`, which imports
  `preferred_source_roots` in `odds_control_plane.py` itself — patching the
  name imported into `nba.sources`/`nhl.sources` (still correct for
  `nba.sources.available_dates`, which is a separate call path) silently does
  nothing for those functions and a test can pass its own patched mock
  straight through to the wrong root without erroring. #89. When a resolver
  is refactored to delegate to a shared helper, re-check every test/gate that
  patches its old module-local import. **Prefer patching the sport module's
  own public wrapper** (`nba.sources.artifact_processed_root`,
  `nhl.sources._data_roots`) **over the shared helper it delegates to** — it's
  one hop shorter and matches what the rest of the NBA test suite had already
  converged on for this same gap.
- **A Render env-var change via the API does NOT restart the service.** The running process keeps the old
  value until a deploy/restart. Cost real time twice: a mitigation set at 20:16 stayed inert until 20:26, and a
  "fix verified" claim was made against a service still on the previous commit. **Always confirm the deploy is
  `live` on the target commit before crediting a fix.**
- **`TZ=America/Chicago` IS set on Render**, so `date.today()` already returns Central there. A Central-vs-UTC
  sweep is still correct hardening, but do not assume it explains an evening-only symptom — verify against the
  running deploy first.
- **Deferral guards must be bounded.** Three separate starvations shipped this session because
  *finite-per-run* was treated as *finite-in-aggregate*: the odds refresh, the board build and the MLB sim are
  each near-continuous even though every individual run ends. Per-side unit tests passed every time; only the
  joint invariant test (#63) catches it.

- **Render auto-deploy is OFF.** Pushing to `main` ships nothing; deploys must be
  triggered per service via the Render API. Confirmed 2026-07-25.
- **Deploying kills an in-flight MLB sim.** Check before deploying:
  `curl -s -H "X-Admin-Token: $ADMIN_TOKEN" "$BASE/api/ops/live-refresh/state?sim_date=$(date +%F)"`
  and look at `sim_run_status.state`. A full slate takes ~15 min.
- **Three services exist, and they are NOT all the same size** (corrected
  2026-07-26 — this note said "three 2GB services" after #57 had already changed
  it): **web 2GB** (`standard`), **refresh-worker 4GB** (`pro`, upgraded
  2026-07-25 — the #57 fix, and pinned so a blueprint sync cannot undo it),
  **live-odds-worker 2GB** (`standard`). refresh-worker carries the MLB sim *and*
  the intelligence pipeline; live-odds-worker carries neither, but its WNBA
  refresh leg has unmeasured headroom (#59), so it is **not** free real estate.
  Put new periodic work on live-odds-worker only after checking #59. Lane
  ownership follows the `SYNDICATE_*_TICK_OWNER` env pattern.
- **Local pytest pollutes `reports/`.** `git checkout -- reports/` before committing.
- **A Render env-var change via the API does NOT restart the service.** The
  running process keeps the old value, so the change is inert until you trigger
  a deploy/restart. Cost real time during the 2026-07-25 incident: a mitigation
  was set at 20:16, reported as applied, and the disabled subsystem kept running
  until a restart at 20:26. **Always verify the observable** (here: does
  `MLB_DAILY_SIM_TRIGGERED` stop appearing?) rather than inferring from a quiet
  gap in failures.
- **Do not judge a production fix from a short quiet window.** Three times in one
  session a result was called early — Layer 2 "still broken" 6 minutes before it
  recovered, a burn rate quoted off a 4-minute sample that a 14-minute sample cut
  by 3.6×, and an OOM loop called mitigated during a 90-second gap before the
  mitigation had even landed. Wait for the mechanism to be observable.
- **The web service times out on boot during a rollout.** Expect ~60–90s of 502s
  on every web deploy while gunicorn restarts; `/healthz` returns 200 again before
  the heavier routes do. Don't diagnose a "crash" from 502s inside that window —
  check `/deploys` for a rollout first. `/mlb/api/cards` is the heaviest route and
  the last to come back; prefer `/mlb/api/market-board` or `/api/ops/version` for
  health checks.
- **Two known-failing tests** in `tests/test_live_refresh_loop.py`
  (`test_create_app_starts_shared_live_refresh_loop*`). The "rotating flaky third"
  is **`test_mlb_has_live_game_reads_live_lens_counts`** — identified 2026-07-25:
  it passes in isolation and in most full runs, so it is order/timing dependent,
  not a real failure. Baseline before blaming your change.
