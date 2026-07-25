# Syndicate TODO — canonical cross-session list

**This is the single source of truth for outstanding work.** Every session should
read this before starting and update it before finishing. Do not keep a parallel
list in session-local task tools without reconciling it back here.

Last reconciled: 2026-07-25.

Conventions:
- IDs are stable and never reused. New work appends at the next free number.
- "Validated" means confirmed against production or a test run, with the evidence
  named. An item that merely *looks* fixed is not validated.
- Prefer measurement over inference. Several items below exist because a
  plausible inference was trusted where a measurement was available.

---

## Do first

| # | Item | Notes |
|---|---|---|
| **25** | Phase 0 fail-closed refresh guard + atomic writes | Fixes candidate swings, look-ahead interval violations (#24) and duplicate sweeps (#20) at once. Same bug family as #43. |
| **15** | Tier odds refresh cadence by volatility | Biggest quota lever: MLB alone ≈ 585 credits/sweep × 60s ticks ≈ **6.3M/month against a 5M budget**. Game lines 60s, props 5–10min, alternates/innings 15–30min. **Blocked by #14** — do not tune on estimates. |

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
  - ❌ Open: re-enable look-ahead with deference to an in-flight sim (reuse
    `_mlb_daily_sim_process_still_running`, mirroring the `any_live` guard).
  - ❌ Open: the 2700s timeout has still never been exercised (today ran 15m).
- **#43 — Layer 2 curated board empty. Root cause FIXED; board still thin.**
  - ✅ *Validated in production 2026-07-25*: stale-dated payload replay fixed in
    `495b71db`. `context_label` moved from `2026-07-24` to the correct
    `2026-07-25`, `candidate_count` went 0 → 1, and `snapshot_generated_at` went
    `null` → `2026-07-25T18:06:51Z`. Recovery took ~6 minutes after the worker
    restart — do not judge this fix before the loop completes a full cycle.
  - ❌ Open (**separate issue, not the replay bug**): 1 candidate off a 15-game MLB
    slate, and `board_contract.pregame` / `.live` / `.top_overall` are all still 0.
    The pipeline now runs on the right date but produces almost nothing. Work
    backward from candidate generation; see also #47 (soccer absent entirely).
- **#31 — NHL revamp Phase 5: local producers replace vendor subprocess.**

## Platform / correctness

| # | Item |
|---|---|
| **48** | MLB fingerprint churn: sim triggered every ~10 min all day 2026-07-24, matching `_mlb_sim_check_interval_seconds`' 600s default. `_mlb_sim_input_fingerprint_by_game` hashes `oddsapi_game_lines_<date>.json` alongside lineups, so any odds refresh can flip every game's hash. Plausible unfixed driver of the OOM saga; **not** addressed by the batching revert. 2026-07-25 was stable 80+ min — confirm before acting. |
| **42** | `source_cards_api_payload`'s cache can never hit — keyed on the file it rewrites. **Third instance of this pattern** (`build_mlb_market_board` fixed in `34c9427d`; avoided deliberately in `build_soccer_market_board`). Worth a rule, not three one-off fixes. |
| **37** | `logger.info` never reaches Render's log collector — use `print(..., flush=True)`. This is why the `NameError` in #8 hid for hours, and why #43's stale-date replay stayed invisible for a day. |
| **40** | Reconcile `render.yaml` drift. **Raised in priority**: a blueprint re-apply would flip the MLB sim trigger back **on** and drop the new soccer vars. Current deliberate overrides: `SYNDICATE_ENABLE_MLB_DAILY_SIM_TRIGGER=true`, `SYNDICATE_MLB_SIM_MAX_GAMES_PER_RUN=0`, `SYNDICATE_LOOK_AHEAD_ENABLED=false`, `SYNDICATE_MLB_EVENING_NEXT_DAY_SIM_ENABLED=false`, `SYNDICATE_INTELLIGENCE_CANONICAL_BOARD_STATE=false`, `SYNDICATE_ENABLE_SOCCER_RESIM_TRIGGER`, `SYNDICATE_SOCCER_RESIM_TICK_OWNER`. |
| **39** | Make canonical board-state dual-write safe, then re-enable (disabled; doubled boot memory). |
| **38** | Prune diagnostic `print` scaffolding from `intelligence_state`. |
| **47** | Add soccer to the Layer 2 intelligence sport list — it is absent from candidate generation entirely (`mlb, nba, wnba, nfl, ncaaf, ncaab, nhl`), so MLS contributes nothing to the curated board even with #43 fixed. |
| **49** | Triage 22 pre-existing failures in `tests/test_ops.py`. Verified by stashing all local changes and re-running: 22 failed / 73 passed at baseline. Prior notes recorded "2 plus a flaky third" — real drift is an order of magnitude worse. |
| **50** | `/api/ops/artifacts/export` 502s on broad patterns — it walks every `HOT_ARTIFACT_PATTERNS` glob and accumulates file contents into one in-memory dict before responding. An ops read should not be able to destabilise the 2GB web service. |
| **51** | `hasSampleData` is inverted on the MLB cards payload — `mlb/cards.py:2373-2374` sets it and `hasArtifactData` to the same expression (`not using_sample_data`), so the two can never disagree and the name means the opposite of what it says. |
| **24** | Look-ahead interval violations (~28min instead of 60). |
| **12** | Phase 4: smaller per-sport artifacts. |
| **29** | Cross-type duplicate candidates. |
| **30** | WNBA schedule-bootstrap cost. |

## OddsAPI budget (after #14/#15)

**16** audit which of the 27 MLB game markets the board renders · **17** MLB core
game lines → slate endpoint (3 credits vs 45) · **18** NCAAF 4 regions → 1 (pure 4×
multiplier) · **19** cap soccer props (~2,400/sweep) · **20** verify refresh runs
can't stack · **21** keep 10×-billed historical endpoints out of prod · **22** stop
retrying 4xx in vendor clients

## Feature work

**26** NBA/WNBA board parity (ESPN athlete IDs, headshots, live projection/line
movement — mirror `288d1e5e`, `604f96f6`, `83315e5c`) · **27** Layer 1 Phase 5:
Layer 2 consumes Layer 1 · **28** Layer 1 Phase 6: market board → NHL, then
NFL/NCAAF/NCAAB · **32–36** NHL revamp Phases 6–10 · **45** WNBA All-Star game
missing from the market board (`/wnba/api/source/cards` shows 1 game,
`/wnba/api/market-board` shows 0; sims may be infeasible for All-Star rosters but
it should still appear and pull lines) · **52** MLS: 1432 `unmatched_no_sim_coverage`
rows (~71% of the board have no sim projection at all — separate from #44) ·
**53** "last simmed" per-league rollout — MLB has `simUpdatedAtDisplay` from
`9b5806c6`; needs other sports plus the *reason* (lineup vs injury vs tip-off).

## Done

- **1** sim fast-path runtime ceiling · **2** memoize `build_reliability_profile` ·
  **3** deploy+restart for stuck 7-25 sim · **4** last-known-good board while stale ·
  **5** mini card live scoreboard · **6** last odds refresh + sim run on cards ·
  **7** Layer 2 blotter fixes · **9–11** odds-history Phases 1–3 · **13**
  per-candidate live-state cache defeat
- **8** Empty production board (the `NameError`). ⚠️ *The fix was correct, but the
  same symptom recurred 2026-07-25 via an unrelated cause (#43). "Empty board" is a
  symptom with at least two distinct root causes — do not treat it as a solved class.*
- **44a** Soccer market board uncached + no resim detection — `12742e6c`. Adds
  `soccer_needs_resim_event_ids` plus a TTL+artifact-signature cache keyed on
  artifacts the build reads and never writes.
- **44b** Soccer had **no event-driven resim path at all** — `b9f70d3a`. Ships
  **dark**. ⚠️ **Do not enable before #14**: it forces an odds refresh with cache
  bypass, and soccer props are ~2,400 credits/sweep (#19) against a budget already
  projected to overrun. Enable via `SYNDICATE_ENABLE_SOCCER_RESIM_TRIGGER=true` on
  live-odds-worker plus `SYNDICATE_SOCCER_RESIM_TICK_OWNER=false` on refresh-worker.
- **46** `sim_run_status` was unresolvable without grepping worker logs for a run
  stamp — `f6a013e3`. Now falls back to `_active.json` → `_last_attempt.json` and
  always reports `sim_run_resolution`.
- **41** Regression coverage for scoped resims truncating the MLB daily summary
  (`dcda6243` shipped the fix untested). `tests/test_mlb_scoped_resim_summary.py`,
  8 tests in two layers: a behavioural consumer contract on
  `_games_from_daily_summary` (the board is built from `summary["outputs"]` and
  nothing else, so a truncated summary *is* a truncated board), plus a structural
  guard on the vendored producer — necessary because the fix lives inside a
  ~2000-line `main()` whose helpers are nested locals that cannot be imported.
  **The guards were validated against `dcda6243^`: all five fail on the pre-fix
  source and pass on the fixed one**, so they are not vacuous. If `daily_update.py`
  is re-vendored and the guards fail, check the merge is still present before
  loosening the assertions.
- **14** OddsAPI quota instrumentation. `syndicate/features/shared/oddsapi_quota.py`
  records `x-requests-remaining` / `-used` / `-last` from MLB, basketball
  (NBA+WNBA, attributed separately) and soccer fetchers; read it at
  **`GET /api/ops/oddsapi/quota`**. Records observations rather than accumulating,
  because `used`/`remaining` are absolute server-side counters — so burn survives
  the lost writes you get from three services racing on a non-atomic store.
  Recorded *before* `raise_for_status`, since a failed call may still be billed and
  dropping it would bias measured burn downward. Reports `None` rather than `0`
  when there is only one observation: "not measured" must not look like
  "not burning". **Still to wire**: NFL props/team odds, NHL, NCAAF, NCAAB.

---

## Operational notes worth not rediscovering

- **Render auto-deploy is OFF.** Pushing to `main` ships nothing; deploys must be
  triggered per service via the Render API. Confirmed 2026-07-25.
- **Deploying kills an in-flight MLB sim.** Check before deploying:
  `curl -s -H "X-Admin-Token: $ADMIN_TOKEN" "$BASE/api/ops/live-refresh/state?sim_date=$(date +%F)"`
  and look at `sim_run_status.state`. A full slate takes ~15 min.
- **Three 2GB services exist** — web, refresh-worker, live-odds-worker. refresh-worker
  carries the MLB sim *and* the intelligence pipeline; live-odds-worker carries
  neither. Put new periodic work on live-odds-worker. Lane ownership follows the
  `SYNDICATE_*_TICK_OWNER` env pattern.
- **Local pytest pollutes `reports/`.** `git checkout -- reports/` before committing.
- **Two known-failing tests** in `tests/test_live_refresh_loop.py`
  (`test_create_app_starts_shared_live_refresh_loop*`) plus a rotating flaky third.
  Baseline before blaming your change.
