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
| **25** | Phase 0 fail-closed refresh guard + atomic writes | **Phase 0 shipped** — see Done. Remaining: the look-ahead's own interval marker (#24) has not been audited for the same fail-open pattern, and several non-artifact writers still use the unsafe `path.with_suffix(".tmp")` shape (`fetch_soccer_*`, `fetch_soccer_history_local`, the `backtest_*` scripts). |
| **15** | Tier odds refresh cadence by volatility | Biggest quota lever. **Target is 5M.** The plan currently reads 15M (`remaining` 13,920,988 + `used` 1,079,012 = 15,000,000, measured 2026-07-25T18:17Z) — but that 15M is *remediation for a real prior overage*, not headroom, and the goal is to cut burn enough to **downgrade back to 5M and stay there**. Tier: game lines 60s, props 5–10min, alternates/innings 15–30min. Use `/api/ops/oddsapi/quota` to verify the reduction actually lands under 5M rather than assuming it. |

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
| **48** | MLB fingerprint churn. Sim triggered every ~10 min all day 2026-07-24, matching `_mlb_sim_check_interval_seconds`' 600s default. `_mlb_sim_input_fingerprint_by_game` hashes `oddsapi_game_lines_<date>.json` alongside lineups, so any odds refresh can flip a game's hash. **Now corroborated**: 2026-07-25 monitoring caught scoped resims of **6 and 9 games** roughly 20 min apart — scoping works (see #23), but 6–9 of 15 games changing that often is far more than real lineup news, so the odds component is very likely driving it. Each resim is compute *and* the refresh that feeds it is credits, so this ties into the 5M target. Consider excluding odds from the sim-input fingerprint, or hashing only lineup/probable fields. **Not** addressed by the batching revert. |
| **42** | `source_cards_api_payload`'s cache can never hit — keyed on the file it rewrites. **Third instance of this pattern** (`build_mlb_market_board` fixed in `34c9427d`; avoided deliberately in `build_soccer_market_board`). Worth a rule, not three one-off fixes. |
| **37** | `logger.info` never reaches Render's log collector — use `print(..., flush=True)`. This is why the `NameError` in #8 hid for hours, and why #43's stale-date replay stayed invisible for a day. |
| **40** | Reconcile `render.yaml` drift. **Raised in priority**: a blueprint re-apply would flip the MLB sim trigger back **on** and drop the new soccer vars. Current deliberate overrides: `SYNDICATE_ENABLE_MLB_DAILY_SIM_TRIGGER=true`, `SYNDICATE_MLB_SIM_MAX_GAMES_PER_RUN=0`, `SYNDICATE_LOOK_AHEAD_ENABLED=false`, `SYNDICATE_MLB_EVENING_NEXT_DAY_SIM_ENABLED=false`, `SYNDICATE_INTELLIGENCE_CANONICAL_BOARD_STATE=false`, `SYNDICATE_ENABLE_SOCCER_RESIM_TRIGGER`, `SYNDICATE_SOCCER_RESIM_TICK_OWNER`. |
| **39** | Make canonical board-state dual-write safe, then re-enable (disabled; doubled boot memory). |
| **38** | Prune diagnostic `print` scaffolding from `intelligence_state`. |
| **47** | Add soccer to the Layer 2 intelligence sport list — it is absent from candidate generation entirely (`mlb, nba, wnba, nfl, ncaaf, ncaab, nhl`), so MLS contributes nothing to the curated board even with #43 fixed. |
| **49** | Triage 22 pre-existing failures in `tests/test_ops.py`. Verified by stashing all local changes and re-running: 22 failed / 73 passed at baseline. Prior notes recorded "2 plus a flaky third" — real drift is an order of magnitude worse. |
| **50** | `/api/ops/artifacts/export` 502s on broad patterns — it walks every `HOT_ARTIFACT_PATTERNS` glob and accumulates file contents into one in-memory dict before responding. An ops read should not be able to destabilise the 2GB web service. |
| **51** | `hasSampleData` is inverted on the MLB cards payload — `mlb/cards.py:2373-2374` sets it and `hasArtifactData` to the same expression (`not using_sample_data`), so the two can never disagree and the name means the opposite of what it says. |
| **57** | 🔴 **The intelligence board build alone no longer fits in a 2GB worker during a live slate.** The real problem behind the 2026-07-25 outage; #55 fixed a genuine collision but was never the root cause. With MLB games live, the pipeline measured **~700MB idle spiking past 1479MB**, and refresh-worker OOM-looped every 15–30s **with the sim confirmed deferring and never launching** (`"mlbDailySim": {"launched": false, "reason": "intelligence_pipeline_busy"}`). Currently mitigated by `SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP=false` on refresh-worker — the board now only recomputes on web's request path, so it is slower and adds to #56's pressure. **Option analysis:** moving it to live-odds-worker is **NOT viable** — its median is a misleading 515MB, but its WNBA refresh leg is documented spiking to **1.3–1.5GB** in the same 2048MB container ([live_refresh_loop.py:1958](syndicate/features/shared/live_refresh_loop.py:1958)), and today's low readings are an All-Star day with one WNBA game. That leaves: reduce the pipeline's footprint, or give a worker more memory. Measure a candidate host's **peak**, never its median. |
| **55** | ✅ *Fixed 2026-07-25* — **MLB sim and the intelligence board build collide on worker boot.** Live incident 2026-07-25. Once the evening slate is inside its tip-off window the sim fires ~5s after *every* boot, concurrently with the intelligence board build the same worker runs; together they exceed 2GB, so the instance OOMs, restarts, and repeats about once a minute. The launch-time memory gate does not catch it because it measures at ~250MB, before either pipeline grows — the same flaw already documented for the join-mismatch build. **Currently mitigated by `SYNDICATE_ENABLE_MLB_DAILY_SIM_TRIGGER=false` on refresh-worker (and in render.yaml), so MLB sims are OFF.** Fix: make the sim defer while the intelligence pipeline is mid-computation — the inverse of the existing `_mlb_daily_sim_process_still_running` guard, which already protects the odds refresh from the sim but not the sim from the pipeline. Re-enable only after that lands. |
| **56** | 🔴 **Web dies from health-check starvation, not memory.** Same incident, *different* failure: `"HTTP health check failed (timed out after 5 seconds)"`, `oomKilled: false`. `WEB_CONCURRENCY=2` × `GUNICORN_THREADS=1` gives the whole service **two concurrent requests**, and because `SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP=false` on web, intelligence persistence runs on the **request path** ([intelligence_state.py:2678](pipeline/intelligence_state.py:2678)) — so slow requests are routine, not exceptional. Two of them starve `/healthz` and Render kills the instance. render.yaml now sets `GUNICORN_THREADS=4`, **but that is not live** — Render only reads render.yaml on a blueprint sync. Threads not workers: each worker is a whole process on 2GB, and this is I/O-bound waiting. Real fix is to stop persisting on the request path. |
| **53** | **Prop ladder odds for all sports** (split out of #16). No `*_alternate` player market is fetched in any sport, so `_finalize_prop_market`'s `alternates` array is always empty and MLB's ladder surfaces have no book prices to compare the sim against. See #16 for the cost model and why this should ride #15's cadence tiering rather than get its own scheduler. |
| **54** | **The OddsAPI quota store lost its observations — mitigated, root cause not proven.** Read 20 observations at 19:17 on 2026-07-25, then `observation_count: 0` with `latest: null` after the 19:38 deploy. Two hypotheses were **disproven**: `_state_namespace()` is env-derived and stable across deploys, and detached fetcher subprocesses *do* reach the shared keyvalue store (the 20 observations were written by worker-side fetchers and read from the web service, which only works through the shared backend). Remaining explanation is eviction: the key held up to 500 full observation dicts, making this telemetry the largest entry in a Redis instance that also holds sim pointers, refresh manifests and board state. Fixed by making the payload O(1) — baseline + latest + counters, no history — which both removes it as an eviction target and cuts recovery from 500 observations to 2. **If observations vanish again, the eviction theory is wrong and the next suspect is the shared store's own lifecycle.** |
| **24** | Look-ahead interval violations (~28min instead of 60). |
| **12** | Phase 4: smaller per-sport artifacts. |
| **29** | Cross-type duplicate candidates. |
| **30** | WNBA schedule-bootstrap cost. |

## OddsAPI budget (after #14/#15)

> **Measured burn — DO NOT act on a short window.** Two readings, same day:
>
> | Window | Burned | /hour | Projected 30d |
> |---|---|---|---|
> | 235s (2 obs) | 525 | 8,042 | **5.79M** |
> | 855s (7 obs) | 525 | 2,210 | **1.59M** |
>
> Same 525 credits — the later calls were free `/events` requests, so the short
> window extrapolated one burst across a month and overstated by ~3.6×. Neither
> number is trustworthy yet, and the swing itself is the lesson: **let the window
> run for at least a full day before sizing anything against it.**
>
> Both readings are also unrepresentative: WNBA-only observations on an All-Star
> day (one game), MLB's slate winding down, NFL/NCAAF/NCAAB out of season, and
> only 3 of ~8 fetchers instrumented. Wire the rest (#14 remainder) and re-read
> on a busy slate before deciding whether the 5M downgrade is safe.
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
**19** cap soccer props (~2,400/sweep) · **20** verify refresh runs can't stack
(partly addressed by #25's fail-closed marker) · **21** keep 10×-billed historical
endpoints out of prod · **22** stop retrying 4xx in vendor clients

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
- **17** MLB core game lines moved to the slate endpoint. `h2h/spreads/totals` now
  cost **3 credits for the whole slate** instead of 3 per game (45 at 15 games).
  Inning-segment markets are "additional markets" the slate endpoint does not
  serve, so they stay per-event. Core and segment payloads are merged per
  bookmaker *before* `_best_bookmaker_game_lines` scores them — scoring
  separately would pick one book for core and another for segments and mix two
  books' prices into one game. Falls back to the old per-event core request if
  the slate call fails, but a fatal `OUT_OF_USAGE_CREDITS`/bad-key response
  raises instead: silently falling back to the 15×-more-expensive path on
  running out of credits is the worst possible response. First tests this
  fetcher has ever had.
- **18** NCAAF regions default `us,us2,eu,uk` → `us`. OddsAPI bills per region, so
  four regions was a flat 4× and NCAAF was the only sport not on US-only (every
  other lane runs `SYNDICATE_LIVE_ODDS_REFRESH_REGIONS=us`). Real trade: NCAAF
  keeps every bookmaker the API returns with no US filter, so the eu/uk books
  drop out of each game's provider list — the same set every other sport already
  lives without. `ODDS_API_REGIONS` still overrides, so reverting is an env
  change, not a deploy.
- **25 (Phase 0)** Fail-closed refresh guard + atomic artifact writes.
  - *Atomic writes*: `syndicate/features/shared/atomic_artifact_write.py`, wired
    into 11 call sites across 7 producers (NBA/WNBA props, basketball props, NFL
    props, soccer picks/rosters). `df.to_csv(path)` truncates then streams, so a
    reader arriving mid-write silently gets fewer rows — one of the
    candidate-swing symptoms. Temp files carry pid+uuid and sit in the
    destination directory: the `path.with_suffix(".tmp")` shape used elsewhere
    gives two concurrent writers the *same* temp path, and a temp on another
    filesystem makes `os.replace` non-atomic.
  - *Fail-closed launch marker*: `_record_odds_refresh_launch` moved to before
    `launch_refresh_run` instead of after it. It spawns a detached subprocess
    and then does more work, so a raise after the spawn left a sweep running
    with no marker — and the next tick started a second one (#20). Recording
    first makes a failed launch cost one skipped interval instead of a duplicate
    sweep; a missed refresh self-corrects, a duplicate burns credits and can
    stack two heavy pipelines in a 2GB container.
  - 16 tests.
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
  "not burning". **All 9 OddsAPI call sites are now instrumented**: MLB,
  basketball (NBA+WNBA attributed separately), soccer odds + props, NFL props +
  team odds, NHL, NCAAF, NCAAB. NCAAF/NCAAB reach the API through `urlopen` with
  the apiKey embedded in the URL, so those record only the path — the endpoint is
  persisted to the shared store and must never carry a key.

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
