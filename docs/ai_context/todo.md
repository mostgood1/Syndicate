# Syndicate TODO — canonical cross-session list

**This is the single source of truth for outstanding work.** Every session should
read this before starting and update it before finishing. Do not keep a parallel
list in session-local task tools without reconciling it back here.

Last reconciled: 2026-07-27 (see "Reconciliation 2026-07-27").

> **Next free ID: 93.** IDs are never reused. Closed items move to
> [`todo_closed.md`](todo_closed.md) — check there before assuming a number is
> free, and run the shipped-work check in Operational notes before reconciling.

Conventions:
- IDs are stable and never reused. New work appends at the next free number.
- "Validated" means confirmed against production or a test run, with the evidence
  named. An item that merely *looks* fixed is not validated.
- Prefer measurement over inference. Several items below exist because a
  plausible inference was trusted where a measurement was available.
- **A closed item lives in Done and nowhere else.** Nine items were listed as both
  open and closed before 2026-07-26; the open copies were stale but read as live
  work. When you close something, delete the open row — don't leave it.

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
- **New: #90** (filed, open) — NBA's `available_dates()` still scans **every**
  preferred artifact root (via `nba.sources._artifact_roots()`), but
  `processed_path()`/`live_snapshot_path()` (post-`757952e1`) only ever build a
  path in the *primary* root. If NBA is ever configured with more than one
  preferred root (e.g. `SYNDICATE_DATA_ROOT` set alongside the local mirror),
  `available_dates()` can advertise a date whose artifact only exists in a
  secondary root, and `processed_path()` for that date will 404 against the
  primary root instead. Invisible today because production only has one NBA
  root; worth a look before adding a second one.

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
| **83** | 🟢 **Steam detector — SHIPPED 2026-07-27 (`event-feeds` commit), actuator deliberately minimal until #62.** The market is the best-aggregated news feed this system can access (survey conclusion, same date: general news/social watchers rejected — latency loses to the market and false triggers cost sim time + board deferral). Detection at the point deltas were already computed ([odds_refresh_tracking.py](syndicate/features/shared/odds_refresh_tracking.py) `_steam_signal`): a ≥0.5 line move or ≥15¢ price move across ≤45 min between observations; ramp/closing lower the price bar to 10¢ (late money is the most informed). Rides the lifecycle event as a `steam` field AND a bounded per-date record (`reports/steam/steam_events_<date>.json`, last 200) + `STEAM_DETECTED` print. Env: `SYNDICATE_STEAM_{LINE_MOVE,ODDS_MOVE,WINDOW_SECONDS,LATE_ODDS_MOVE}`. **Open:** wire as a consumer-facing surface (board "why is this moving", Ask the Syndicate), and as a re-price trigger **once #62 exists** — do NOT wire it to force re-sims. |
| **84** | 🟡 **MLB park weather — fetch SHIPPED, sim join OPEN.** `scripts/fetch_mlb_weather.py`: NWS (free, keyless) hourly wind/temp/direction for every park with a game today (home teams from the game-lines snapshot; 31-entry coords table incl. roof flags — verified live: 74°F / 6 mph S at Yankee Stadium on first run). Written to `data/weather/weather_<date>.json`, allowlisted for web pull, launched detached from the tick at most hourly (`SYNDICATE_MLB_WEATHER_INTERVAL_SECONDS`, 0 disables). **Open half:** join wind/temp into the sim (totals/HR) via the park-factors join point, and surface on cards. ⚠️ Tampa Bay coords assume Tropicana; verify 2026 venue. Roofed parks are fetched with `roof: true` so consumers discount wind rather than the park going missing. |
| **85** | 🟡 **Remaining structured event feeds** (from the 2026-07-27 survey; general news watchers rejected). (a) **Soccer confirmed XI at ~T-60** — the biggest soccer line-mover, lands inside #82's ramp window; no free structured source identified yet, needs a source decision before any code. (b) **Official injury-report schedule audit** — basketball injury fetch already exists (`_fetch_injuries` → `fetch-injuries` CLI per sport package, fingerprint-diffed for change detection), so the open question is narrower than it looked: whether those fetches align with the leagues' fixed publication times, not whether the mechanism exists. (c) **Probable-pitcher change detection** — verify `probable_pitcher_overrides.json` is fed by detection rather than manually. |
| **86** | 🟡 **LLM analyst layer — judgment, not detection.** Two scoped uses on top of #83's steam record and the existing triggers: **materiality classification** of detected changes (star scratch ≠ ninth bullpen arm; today both force the same sweep) and **movement annotation** ("why did this move") attached to steam events for the Ask the Syndicate briefing family, which is the natural home. Explicitly NOT a raw-news-firehose reader — cost, latency, and hallucinated urgency feeding a pipeline where false triggers block the board. Blocked on nothing, but do after #83's surface exists so the annotations have somewhere to land. |
| **82** | 🟡 **Pregame odds capture: opening line, movement curve, CLV close — per-sport rules agreed 2026-07-27, Phase 1 SHIPPED.** The design (user-signed): each data product has its own sampling need — *opening* = first sweep after posting; *movement* = sparse drift samples + event triggers (lineup/injury force-refresh already exists and bypasses all cadence); *CLV close* = a **per-game T-minus sweep**, which slate-wide cadence structurally misses (worst for WNBA one-game days). **Rules:** MLB/WNBA pregame drift every **2h, full sweeps** (midday PROP samples ride along — user requires them); **soccer 8h (2–3/day)** pre-matchday, daily shape on matchday; live cadence untouched. **Phase 1 (shipped `pregame-cadence` commit):** per-sport interval filter in the tick — a sport whose OWN games aren't live sweeps at most once per its interval (before this, WNBA re-swept every 60s for the whole of an MLB slate); event-triggered sports bypass; every uncertainty fails open; `SYNDICATE_PREGAME_SWEEP_INTERVAL_SECONDS[_<SPORT>]`, 0 disables. **Phases 2+3 SHIPPED 2026-07-27 (same session):** `capture_phase` tag (`drift/ramp/closing/live`, boundaries 80/12 min bracketing the T-windows; `event_type="open"` marks the opener) on every lifecycle observation; T-window scheduler fires full sweeps at T-75/T-10 per game for **non-live sports only** (a live sport's 60s slate-wide cadence already covers its pregame events — the windows matter exactly when they're cheap: first game of the day and WNBA one-game slates); commence times from MLB's game-lines snapshot and WNBA's vendor schedule, everything failing open to "nothing due"; `market_tier=lines_props` on pure drift sweeps drops MLB's 24 segment/alternate markets (~63% of per-event cost) with **existing segment lanes carried forward so the cards' F1/F3/F5/F7 tabs never blank between full sweeps**; T-windows, live, event triggers, and uncertainty all run full. ⚠️ Known limitation: MLB T-windows only fire from the service that owns MLB's tick (owner rules intact); MLS matchday ramp rides its games going live. *Original Phase 3 plan:* per-game **T-75m** post-lineup sweep and **T-10m closing sweep** driven by each sport's start times, plus a `phase` tag (`opening/drift/lineup_trigger/ramp/closing/live`) on lifecycle observations so opening/closing lines are lookups, not timestamp inference. **Phase 2 (after):** market tiering — lines-only drift via #17's slate endpoint (~6 credits) with props every 4h, full markets only at T-windows. |
| **25** | Phase 0 fail-closed refresh guard + atomic writes | **Phase 0 shipped** — see Done. Remaining: the look-ahead's own interval marker (#24) has not been audited for the same fail-open pattern, and several non-artifact writers still use the unsafe collision-prone temp shape. **Enumerated 2026-07-26 — it is six files, not the three previously listed, and the `backtest_*` scripts are NOT among them** (that entry was wrong): [fetch_soccer_history_local.py:44](scripts/fetch_soccer_history_local.py:44), [fetch_soccer_oddsapi_odds_local.py:82](scripts/fetch_soccer_oddsapi_odds_local.py:82), [fetch_soccer_oddsapi_props_local.py:105](scripts/fetch_soccer_oddsapi_props_local.py:105), [fetch_nfl_oddsapi_props_local.py:74](scripts/fetch_nfl_oddsapi_props_local.py:74), [fetch_mlb_oddsapi_local.py:72](scripts/fetch_mlb_oddsapi_local.py:72), [refresh_ncaaf_oddsapi.py:529](scripts/refresh_ncaaf_oddsapi.py:529). All use `path.with_suffix(path.suffix + ".tmp")`, so two concurrent writers of the same file collide on one temp path. `atomic_artifact_write.py` already exists; this is mechanical. |
| **15** | 🔴 **DO NOT DOWNGRADE — conclusion INVERTED by the first full-day measurement, 2026-07-27T01:55Z.** The item's own instruction ("let the window run a full day") was finally satisfiable: baseline 2026-07-26T01:52Z → latest 2026-07-27T01:55Z, **86,572 s**. Result: **371,563 credits burned in 24 h → 15,451/hr → projected 11.12 M/30d — 2.2× OVER the 5 M target**, and 74% of even the current 15 M plan. Two independent counters agree exactly (provider `used` delta 1,188,309→1,559,872 vs local window sum). **Composition: MLB is 96.3%** (357,975 of 371,563; soccer 18 credits, WNBA 332 — both noise). ⚠️ **Why the earlier 1.42 M/mo read was wrong:** it was the period-to-date *average* — ~25 days during which the pipeline was repeatedly degraded (OOM loops, empty boards, workers down). Today was arguably the first fully-healthy day, and **a healthy system burns ~8× the degraded average**. The "estimate is 36× too high" claim compared against that suppressed average; against today the original ~585/sweep estimate is only ~2.3× high. ⚠️ Still one day — do not size the *exact* monthly number off it — but the asymmetric conclusion is safe: even occasional 371 k days keep the total far above 5 M, **and football season only adds**. **Next steps, in order:** (1) attribute MLB's 358 k/day by market family — the recorders already pass `endpoint=url` ([oddsapi_quota.py:100](syndicate/features/shared/oddsapi_quota.py:100)), the store just doesn't aggregate it; a `by_market_family` bucket beside `by_sport` is a small never-raises change and tomorrow's slate produces attributed data; (2) USER DECISION on #16's cuts (a)+(b) — now measurement-backed, ~210 of ~585/sweep ≈ 36%, which alone still leaves ~7 M/mo; (3) USER DECISION: this item's "do not tier the cadence" was premised on the problem not existing — the problem now measurably exists, so cadence tiering (full-game every sweep, segments/alternates every Nth) is back on the table, but that reversal is yours to make, not a session's. Caveat: `by_sport` in the store never resets, but the 02:36Z 7-26 reading (MLB 393 calls/179 credits) pins essentially all MLB burn inside this window. |

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
