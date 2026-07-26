# Syndicate TODO — canonical cross-session list

**This is the single source of truth for outstanding work.** Every session should
read this before starting and update it before finishing. Do not keep a parallel
list in session-local task tools without reconciling it back here.

Last reconciled: 2026-07-26 (bookkeeping pass — see "Reconciliation 2026-07-26").

> **Next free ID: 75.** IDs are never reused. Closed items move to
> [`todo_closed.md`](todo_closed.md) — check there before assuming a number is
> free, and see #71 for the check that catches shipped work missing from both.

Conventions:
- IDs are stable and never reused. New work appends at the next free number.
- "Validated" means confirmed against production or a test run, with the evidence
  named. An item that merely *looks* fixed is not validated.
- Prefer measurement over inference. Several items below exist because a
  plausible inference was trusted where a measurement was available.
- **A closed item lives in Done and nowhere else.** Nine items were listed as both
  open and closed before 2026-07-26; the open copies were stale but read as live
  work. When you close something, delete the open row — don't leave it.

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

| # | Item | Notes |
|---|---|---|
| **25** | Phase 0 fail-closed refresh guard + atomic writes | **Phase 0 shipped** — see Done. Remaining: the look-ahead's own interval marker (#24) has not been audited for the same fail-open pattern, and several non-artifact writers still use the unsafe collision-prone temp shape. **Enumerated 2026-07-26 — it is six files, not the three previously listed, and the `backtest_*` scripts are NOT among them** (that entry was wrong): [fetch_soccer_history_local.py:44](scripts/fetch_soccer_history_local.py:44), [fetch_soccer_oddsapi_odds_local.py:82](scripts/fetch_soccer_oddsapi_odds_local.py:82), [fetch_soccer_oddsapi_props_local.py:105](scripts/fetch_soccer_oddsapi_props_local.py:105), [fetch_nfl_oddsapi_props_local.py:74](scripts/fetch_nfl_oddsapi_props_local.py:74), [fetch_mlb_oddsapi_local.py:72](scripts/fetch_mlb_oddsapi_local.py:72), [refresh_ncaaf_oddsapi.py:529](scripts/refresh_ncaaf_oddsapi.py:529). All use `path.with_suffix(path.suffix + ".tmp")`, so two concurrent writers of the same file collide on one temp path. `atomic_artifact_write.py` already exists; this is mechanical. |
| **15** | **Confirm burn stays under 5M across a full in-season day, then DOWNGRADE the plan** — do *not* tier the cadence. Rewritten 2026-07-26 after measuring instead of estimating. Real billing data: `used` 1,188,488 of a 15M plan = **7.9% period-to-date**, tracking to **~1.42M/month** against the 5M target — already under by ~3.5x. The live rate was 245.7 credits/hr (30d ≈ 177k). The `~585 credits/sweep x 60s ticks ≈ 6.3M/mo` figure that drove this whole workstream was an **estimate and is ~36x too high**; most calls bill *zero* (MLB measured at **393 calls for 179 credits** — event-list calls are free, only market requests bill). Cadence tiering would make props stale for 5–30 min to solve a problem the data says does not exist. **Caveats before acting:** the reading was 02:36 UTC — the quietest hour, MLB ending, one WNBA All-Star game, no football — so an in-season NFL/NCAAF Saturday is the real test; and #54's O(1) quota store keeps only baseline+latest, so there is no full-day curve (the OddsAPI `used` counter is the trustworthy number, not the local store). Some of this headroom is #17/#18, landed 2026-07-25. Keep #19 and #21 from the original scope — they cut waste without costing freshness. |

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
- **#43 — Layer 2 curated board empty. ROOT-CAUSED 2026-07-25, AWAITING VERIFICATION.**
  - The board was **never broken**. It computed **222 candidates every cycle** and
    lost them at the final write: the state payload reached 8.9MB compact
    (16.9MB / 393k lines on disk) and Redis answers a `SET` that size with
    `Connection closed by server`. The retry is correct — it clears the cached
    client and reconnects — which is precisely why this hid for hours: a fresh
    connection cannot fix an oversized *value*, so it failed twice, the exception
    was caught and logged, and the loop carried on looking healthy.
  - ✅ Fixed in `b9925b30`: `response.analysis` was byte-identical to top-level
    `analysis` (now aliased on write, restored on read), and
    `evaluation_record.recommendations` is 1.98MB with no reader anywhere in
    `syndicate/` or `pipeline/`. **8.90MB → 4.37MB**, verified lossless against
    the real production payload.
  - ❌ **NOT closed.** Closure requires `candidate_count > 0` **with a snapshot
    timestamp** on `/api/intelligence/status`. Do NOT close on "the loop is
    iterating" or "builds completed" — both were green for hours while the board
    was empty. That is the whole lesson of this item.
  - ⚠️ 4.37MB is **untested, not known-good**. All that is established is that
    8.9MB fails. If it still fails, the next reductions are
    `response.evaluation_record` (2.21MB) and `candidate_pool` (0.84MB), or move
    the bulk through the artifact publish/pull path. **#60 is closed**, so an
    oversized write now fails loudly with key/size/caller instead of surfacing
    as a generic `ConnectionError` — if 4.37MB is still too big you will see it
    named in the logs rather than having to infer it.
  - Three earlier explanations were each real bugs that did **not** fix this: the
    stale-dated payload replay (`495b71db`), the wrong host (#57), and a
    self-inflicted starving deferral guard (`296402e6`). Each changed a real
    thing and the symptom never moved.
  - ~~Still genuinely open underneath: **#47**~~ — **closed 2026-07-25.** Soccer
    was added to the worker's sport list (it was configured in `app.py` all
    along; the worker reads the *fallback* list). This is no longer a cap on
    what the board can show. The live cap is **#52** (1432 MLS rows with no sim
    coverage), not #47.
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

- **#68 — Candidates drop to zero at `candidate_collection`.** *(Filed as #63;
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
| **66** | 🟡 **Board shows no opportunities — but MUCH narrower than it looked, and partly correct behaviour.** Measured 2026-07-26T04:41Z for date 2026-07-25: **MLB 15 games, 80 rows, 80 matched with BOTH price and projection — and all 15 games `final`.** So an empty *actionable* MLB board late at night is **right, not a bug**, and several hours were spent treating correct behaviour as a defect. MLS: 30 games, 2023 rows, but only **163 matched** (1432 `no_sim_coverage`, 428 `needs_resim` — see #52/#44b). `_build_candidate_pool` returning 0 is still unexplained *for a live slate*, and that is the only open part. **Retest on a live slate (weekday afternoon/evening), not after midnight**, now that soccer reports `live` correctly (#67). ~~If it is still 0, instrument `_build_candidate_pool` — the last uninstrumented link.~~ **Corrected 2026-07-26: that instrumentation already shipped** as #64 (`a1638c39`) — classification and dedupe now emit an `INTEL_TRACE` with a count per rejection reason. So the next step is not to build an instrument, it is to **read one**: get a live slate and look at which reason dominates (`missing_selection` vs `missing_projection_or_odds`). See #68. |
| **65** | ⚠️ **MISDIAGNOSED — corrected 2026-07-26.** Filed as "a future-dated payload is being queued and built". **There is no such payload.** `_compute_board_publication_response` rolls itself over: when today's pool is 0 it calls `_next_supported_intelligence_date` and *probes* tomorrow, committing only if tomorrow scores higher. So `context_label: 2026-07-26` in the traces is **expected rollover-probe behaviour, not a bug** — and it appears after ~19:00 CDT because UTC has already rolled over, so tomorrow's date legitimately exists in the per-sport artifact date lists. Two guards were shipped against the queue path (`08014007`, `34e2df35`) and **neither ever fired** (`future_evicted=0` throughout), because the queue was never involved. They are harmless and correct in principle for genuinely stale payloads, but they are not a fix for anything observed. The rollover is a *consequence* of #66, not a cause. **Lesson: `2026-07-26` traces at 21:00 CT are normal — do not chase them.** |
| **42** | `source_cards_api_payload`'s cache can never hit — keyed on the file it rewrites. **Third instance of this pattern** (`build_mlb_market_board` fixed in `34c9427d`; avoided deliberately in `build_soccer_market_board`). Worth a rule, not three one-off fixes. |
| **37** | `logger.info` never reaches Render's log collector — use `print(..., flush=True)`. This is why the `NameError` in #8 hid for hours, and why #43's stale-date replay stayed invisible for a day. |
| **74** | 🟡 **A router-inferred `mode` silently overwrites the question's own intent.** Found 2026-07-26 while fixing headlines. `QueryRouter` classifies e.g. "Explain the best points targets across NBA and WNBA" as `player_analysis`; [intelligence_pipeline.py:86](pipeline/intelligence_pipeline.py:86) `_pipeline_mode_for_query_type` maps that to `"pregame"`; `_query_preferences` reads `mode` as an **instruction** and replaces the parsed intent (`best_bets`) with `pregame_bets`. So a lane the caller never asked for drives downstream behaviour. Two known consequences: the headline (worked around in `17a40505` by letting a named market outrank a generic lane — the workaround is fine but the cause is here), and **`parsed_request.intent` reports the routed intent rather than the parsed one**, which is a public field. **Attempted and reverted**: adding `mode_inferred` to `IntelligencePipelineRequest` and withholding an inferred mode from `run_intelligence_query` is the right shape, but `route_intelligence_request` → `QueryRouter.route_request` **stamps `mode` into the payload before `_normalize_request` sees it**, so by then inferred and caller-supplied are indistinguishable. The fix has to thread an explicit/inferred flag through the router. ⚠️ Blocks promoting the pipeline's `parsed_request` to the top level, which is what several `test_intelligence.py` subject failures need (`requested_subjects` is resolved against the real candidate pool inside `run_intelligence_query` and cannot be reproduced by re-parsing the question). Promoting it before this lands trades ~2 fixed tests for ~3 broken ones — measured. |
| **72** | 🟡 **`record_prediction` writes a growing multi-megabyte file on the production request path.** Found 2026-07-26 while root-causing a 3-hour test suite. [intelligence.py:7706](syndicate/features/intelligence.py:7706) calls it on **every** intelligence query; `prediction_ledger._default_ledger_path()` resolves through `data_root()`, and each call **rewrites the entire file**. Measured locally: ~14.5KB appended per call and the file had reached **2.5MB**, so every write re-serialises an ever-larger document — cost grows with age, and nothing ever resets it. This is #56 territory (slow requests are routine on a 2-thread web service). Its only reader, `pipeline/performance_aggregator.py`, treats it as a fallback and currently reports `used_prediction_ledger_fallback: false` / `prediction_ledger_count: 0` — i.e. **written on every request, read by nobody**. User believes the ledger is obsolete and should not exist. Decide: delete the write path, or bound and justify it. The test-side leak is closed (suite-wide fixture in `tests/conftest.py`); production is untouched. |
| **71** | 🟢 **Nothing checks that shipped work reaches this list.** #64 (`a1638c39`, the candidate-pool trace) shipped 2026-07-25 and appeared in **neither** the open nor the closed sections — it was found only by diffing commit messages against the list. Audited 2026-07-26 across 200 commits: **#64 is the only instance**, so this is rare, not systemic, and does not need a cleanup project. It needs a 10-second check at session end. Run it before reconciling: <br><br>`git log --format=%s -80 \| grep -oE '#[0-9]{1,2}\b' \| sort -u` <br><br>…and confirm every ID appears in `todo.md` or `todo_closed.md`. Worth promoting to a script if it ever catches a second one. **Why it matters beyond bookkeeping:** #64 shipped the exact instrumentation #66 still describes as "the last uninstrumented link", so a session could have rebuilt work that already existed. |
| **70** | 🟡 **`render.yaml`'s comments state the opposite of their own values for the intelligence loop.** Found 2026-07-26 while reconciling. Service blocks: web 18–214, refresh-worker 215–454, live-odds-worker 455+. [render.yaml:324](render.yaml:324) sets `SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP=true` on **refresh-worker** under a comment reading *"DISABLED 2026-07-25 … left disabled here so a blueprint re-apply cannot silently restart it"*; [render.yaml:556](render.yaml:556) sets it `=false` on **live-odds-worker** under a comment reading *"Enabled 2026-07-25 (#57): the board build moved here … refresh-worker's copy is 'false' for that reason."* The **values are correct** — they match #57's actual resolution, the pro/4GB upgrade at [render.yaml:218](render.yaml:218) that made refresh-worker viable again — and both **comments are stale** from the superseded intermediate mitigation. Dangerous because render.yaml is the blueprint-sync source and these comments are the only rationale a future session sees: read literally, they instruct you to invert a working config. #40 reconciled the values; nobody reconciled the prose. |
| **39** | Make canonical board-state dual-write safe, then re-enable (disabled; doubled boot memory). |
| **38** | Prune diagnostic `print` scaffolding from `intelligence_state`. **Do not do this while #43/#66/#68 are open** — those prints are the only instrumentation on the path being diagnosed. |
| **51** | `hasSampleData` is inverted — and it is **two sites, not one** (corrected 2026-07-26). [mlb/cards.py:2375-2376](syndicate/features/mlb/cards.py:2375) and the *shared* contract at [game_board_contract.py:622-623](syndicate/features/shared/game_board_contract.py:622) both set `hasSampleData` and `hasArtifactData` to the same expression (`not using_sample_data`), so the two can never disagree and the name means the opposite of what it says. The shared-contract copy means every sport on `game_board_v1` inherits it, not just MLB. Note `tests/test_archives.py:203-204` and `:1261-1262` assert both are true, so the tests currently lock in the wrong semantics and must change with the fix. |
| **59** | **Measure WNBA's real peak memory on a live slate (next games Tuesday).** *Reframed 2026-07-26: this no longer "decides #57" — #57 was closed by upgrading refresh-worker to pro/4GB, so the board build is no longer looking for a host.* What still matters is that **live-odds-worker's own headroom is unverified**: it runs the WNBA refresh leg in a 2048MB container, and [render.yaml:550-555](render.yaml:550) explicitly flags that as `UNVERIFIED ON A REAL WNBA SLATE`. The 1.3–1.5GB figure everything is reasoning from is a **code comment from a past incident, not a measurement** ([live_refresh_loop.py:1958](syndicate/features/shared/live_refresh_loop.py:1958)); what was actually measured 2026-07-25 was 412–652MB, on an All-Star day with one game, so it proves nothing. The instrumentation already exists: `basketball_props_smart_sim.py` has 9 `log_list_memory` call sites emitting to stderr, which produced **zero** lines that day (consistent with WNBA being idle, not with broken instrumentation). Watch `ALL_PROCESS_MEMORY` peaks on live-odds-worker through a full WNBA slate. **Measure peak, never median** — a median of 515MB hid a documented 1.3–1.5GB spike and nearly drove a bad placement decision. ⚠️ **#58 closing does not help here.** It cut quarter-sim CPU 73×, but the accumulators went from two 5,000-float lists to two arrays — a rounding error against a 1.3GB question. Take the measurement. |
| **56** | 🔴 **Web dies from health-check starvation, not memory.** Same incident, *different* failure: `"HTTP health check failed (timed out after 5 seconds)"`, `oomKilled: false`. `WEB_CONCURRENCY=2` × `GUNICORN_THREADS=1` gives the whole service **two concurrent requests**, and because `SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP=false` on web, intelligence persistence runs on the **request path** ([intelligence_state.py:2678](pipeline/intelligence_state.py:2678)) — so slow requests are routine, not exceptional. Two of them starve `/healthz` and Render kills the instance. render.yaml now sets `GUNICORN_THREADS=4`, **but that is not live** — Render only reads render.yaml on a blueprint sync. Threads not workers: each worker is a whole process on 2GB, and this is I/O-bound waiting. Real fix is to stop persisting on the request path. |
| **53** | **Prop ladder odds for all sports** (split out of #16). No `*_alternate` player market is fetched in any sport, so `_finalize_prop_market`'s `alternates` array is always empty and MLB's ladder surfaces have no book prices to compare the sim against. See #16 for the cost model and why this should ride #15's cadence tiering rather than get its own scheduler. |
| **24** | Look-ahead interval violations (~28min instead of 60). |
| **12** | Phase 4: smaller per-sport artifacts. |
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
- **"Empty board" is a symptom with at least two distinct root causes** (from #8
  and #43) — a `NameError` in one case, an oversized Redis write in the other.
  Do not treat it as a solved class, and do not assume a past fix covers a new
  occurrence.

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
