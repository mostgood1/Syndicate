# Syndicate TODO — closed items archive

Record of shipped work, split out of `docs/ai_context/todo.md` on 2026-07-26 to
keep the working list readable. **`todo.md` remains canonical for anything
outstanding** — start there, not here.

This file is a *record*. Any lesson from a closed item that should still change
what a future session does was deliberately **left in `todo.md`**, under
"Operational notes worth not rediscovering", so that it is read regardless of
whether anyone opens this file. If you find yourself needing to read this
archive to avoid repeating a mistake, that lesson was filed in the wrong place —
promote it back to `todo.md`.

**IDs are stable and never reused.** An ID appearing here is closed forever; new
work takes the next free number (see the counter at the top of `todo.md`).

---

## Closed 2026-08-05 — WNBA CI test-order pollution + empty-slate message mismatch (`task_b4637457`)

| # | What shipped |
|---|---|
| `task_b4637457` | `python -m unittest tests.test_archives` (what CI actually runs) was reporting 6 failures. Two distinct root causes, both fixed in one commit: (1) plain `unittest`'s alphabetical-by-method-name test order (not file order) plus a wall-clock-TTL cache in `wnba/cards.py` keyed only on `(date, event_ids, allow_stored_date_fallback)` let one test's mocked payload leak into a same-key later-running test — `tests/conftest.py` already resets this cache class for pytest, but its autouse fixtures never load under plain `unittest`; fixed with real `setUp`/`tearDown` on `DateArchiveHelperTests` (`tests/test_archives.py`), which run under both runners. (2) `has_games_for_date("1900-01-01")` fell through to a live ESPN call that fails offline and returns `None` rather than `False`, so the wrong empty-state message was chosen; fixed with a founding-year (1997) guard in `wnba/sources.py`. |

Commit: `53cf342a` (2 files). Verified: `unittest tests.test_archives` 383/383 (was 6 failures); `pytest tests/test_archives.py` unaffected (381 passed/2 skipped); 145 tests across the other 6 files touching `has_games_for_date` still pass. Deployed to all three Render services (web, refresh-worker, live-odds-worker) after confirming no in-flight MLB sim — `has_games_for_date` runs in the live request path, so this one needed the deploy, unlike a test-only fix. Full writeup in `todo.md`'s git history (was the top "RESOLVED 2026-08-05 (`task_b4637457`)" entry before this archival pass).

## Closed 2026-07-30 — Games-strip/soccer-league session (#162, #164, #165, #166)

| # | What shipped |
|---|---|
| **162** | Soccer candidates show the real league ("MLS", "La Liga") instead of the generic "Soccer" sport label — `home.py`'s `_append_game_bet_candidate` and `intelligence.py`'s `_steam_candidates_for_sport` both prefer `game.get("league_display")` (stamped by `soccer/cards.py`'s game-dict constructors) over the static per-sport config name. |
| **164** | WNBA pregame props were silently dropped for TODAY's slate (real picks existed in `recommendations_slate_<date>.json` but zero reached the board) — root cause: `_prop_item_from_rank_card` (home.py) never set a `game_id`/`gamePk`/`event_id`, so `_build_sport_overview`'s hydration-intersection filter excluded every one of them. New `_backfill_prop_row_game_id` matches each row's team abbreviations against `home_games`, wired into `_WNBADataProvider.pregame_props`. |
| **165** | Duplicate Games-strip mini-cards for the same live game — went through 3 live-broken versions (matchup-only merge hid a real different-date game; exact date-key broke the original same-day merge; date-clustering still missed a candidate whose date field was itself wrong, not missing) before landing on clustering by **live-chip identity** first, date-compatibility only for chip-less groups. See the Operational note in `todo.md` — this one is worth reading, not just the summary here. |
| **166** | Soccer steam candidates' `game_date` was the board's scan date, not the individual match's real kickoff date (e.g. 7 real Saturday MLS matches all showed "Fri Jul 31"). First fix (season-schedule fuzzy team-name cross-reference) shipped with two real bugs of its own (wrong field-access pattern reading a different structure's shape; no disambiguation for team pairs meeting twice in a season) before being replaced entirely — the raw OddsAPI odds row already carries its own `commence_time` column directly, no cross-referencing needed at all. See the Operational note in `todo.md`. |

Commits: `8ea2d8b1` (#162) · `409677df`+`fa7d0426`+`cd5b6714`+`940024f2` (#164/#165 + 3 follow-ups) · `2f926f40`+`99293914`+`969e8a44` (#166 + 2 follow-ups). All verified live in production (not just tests) before this session ended, including a full re-check of the rendered board after each fix. Landed alongside two other concurrently-active sessions in the same shared checkout (`#161` Layer 1 closing-line, `#163` Ask The Syndicate player history) — coordinated via send_message rather than colliding on files.

## Closed 2026-07-30/31 — Ask The Syndicate MLB player history + advanced analytics (#163)

User asked for Ask The Syndicate's MLB answers to show real player history and advanced matchup analytics alongside the existing sim-only tables (motivating example: "Eury Perez outs" returning only SmartSim tables, no real data). Shipped across four commits in one continuous session, each one surfacing the next real gap live in production rather than in a vacuum:

| # | What shipped |
|---|---|
| **163a** | New MLB recent-form index (`syndicate/features/mlb/player_game_log.py`) — MLB had no per-player game-log artifact at all (unlike NBA/WNBA/NHL). Scans mirrored `feed_live` files into `mlb_pitcher_game_log.csv`/`mlb_batter_game_log.csv`, incremental by `(game_pk, player_id)`; `run_mlb_daily_sim_job.py` keeps it current automatically. New `_mlb_player_history_evidence` evidence fetcher adds "Last N starts/games", "History vs {opponent}", an actual-stat bar chart, and an "Advanced Statcast profile" table (the underlying Statcast feature file existed but was stale/unused — regenerated for the full 2026 season). Along the way: fixed `_mlb_bvp_evidence`'s pitcher branch silently returning nothing for a young pitcher with sparse career BvP (now an explanatory note + park/weather), and a real pre-existing bug in `_name_matches`/`_person_matches` — no diacritic folding, so "Perez" never matched a *stored* "Pérez" (MLB Stats API returns some names accented, others not) — this was the actual reason the original "Eury Perez outs" screenshot showed nothing at all. |
| **163b** | Real production bug, found via the user's own live test immediately after 163a deployed: "Eury Perez outs" still returned zero visuals. Root cause — Render gives web and refresh-worker separate, non-shared disks; the new CSV/Statcast-feature paths were never added to `artifact_publisher.HOT_ARTIFACT_PATTERNS`, so they built correctly forever on refresh-worker and never once reached web (the same gap class as three prior incidents documented in that file's own comments — see the new Operational note in `todo.md`). Fixed the allowlist, and reordered `run_mlb_daily_sim_job.py` so the game-log bootstrap runs *before* the publish sweep (which only picks up files with mtime newer than the job's start epoch). |
| **163c** | The weekly Statcast refresh from 163a was wired into `scripts/unified_daily_update.ps1`, which turned out to never run in production at all (not referenced by `render.yaml` or any GHA workflow — confirmed live the feature file stayed stuck on a stale generation date through two full deploys). Properly wired into `live_refresh_loop.py` (the actual persistent refresh-worker loop) as a new staleness-gated gate mirroring the existing MLB daily-sim gate's pattern (deferred while a sim is active or memory headroom is low, launched as a detached subprocess, PID-verified status file). Enabled via `SYNDICATE_ENABLE_MLB_STATCAST_REFRESH_TRIGGER` on refresh-worker only. |
| **163d** | Live user feedback on the shipped feature, addressed same session: chart values were hover-tooltip-only (`renderVisualChart` now shows a visible label above each bar); "Eury Perez outs" charted strikeouts regardless of which stat was asked (new `_mlb_pitcher_chart_stat` picks among outs/K/BB/ER/pitches from the actual question wording); added an "Opposing lineup Statcast approach" table (today's lineup's own xwOBA/Barrel%/HardHit%/K-mult, sorted by biggest matchup threat) — previously only the pitcher's own profile was shown, not the batters he's actually facing. |

**Also found, not fixed** (see `todo.md` #167): `source_roots.py`'s `repo_root_from` has an off-by-one for callers 2 subdirectories deep instead of 3 (masked in production by an always-set env var, real trap for local dev without it).

Commits: `fdb6861a` (163a) · `1ea9b4cf` (163b) · `f77d872c` (163c) · `272b496d` (163d). All four deployed to web + refresh-worker and verified against real production queries (not just tests) before this session ended — including watching a real forced resim complete on refresh-worker's actual disk to confirm the artifact-publish fix worked end-to-end, and a live browser check of the rendered chart values. 293/299 relevant tests passing (6 pre-existing, confirmed-unrelated flaky failures). Landed alongside two other concurrently-active sessions in the same shared checkout (Games-strip/soccer-league #162/#164-166, and a separate #161-part-2/production-outage session) — coordinated via send_message, and one of those sessions' own urgent production hotfix (`c44c02cc`/`ac03e46d`, an unrelated broken import) landed cleanly underneath 163c/163d with no collision.

## Closed in the 2026-07-25/26 session

| # | What shipped |
|---|---|
| **14** | OddsAPI quota instrumentation — all 9 call sites |
| **16** | MLB market audit (findings live on in #53) |
| **17** | Core game lines → slate endpoint, 45 → 3 credits |
| **18** | NCAAF regions `us,us2,eu,uk` → `us` |
| **25 (Phase 0)** | Fail-closed refresh guard + atomic artifact writes |
| **40** | `render.yaml` drift reconciled, `plan: pro` pinned |
| **41** | Scoped-resim regression test |
| **44a** | Soccer market board cache + resim detection — `12742e6c` |
| **44b** | Soccer event-driven resim path — `b9f70d3a`, ships **dark** |
| **46** | `sim_run_status` self-resolution — `f6a013e3` |
| **47** | Soccer added to the worker's sport list |
| **48** | Odds prices removed from the sim fingerprint |
| **49** | `test_ops` triage |
| **50** | Artifact-export ceiling |
| **54** | Quota store made O(1) |
| **55** | Sim ↔ board-build alternation, **both** directions |
| **29** | Cross-type duplicate candidates — every pick rendered twice |
| **73** | Ranking signals computed but never applied to the order |
| **58** | Basketball quarter sim vectorised — 215ms → 2.9ms/game (73×) |
| **57** | Board build stays on refresh-worker, upgraded to pro/4GB |
| **60** | Keyvalue payload ceiling — oversized writes fail loudly |
| **63** | Mutual-deferral starvation invariant test |
| **64** | Candidate pool's last stage made visible — `a1638c39` |
| **67** | Soccer game state derived from the clock, not a frozen `status_state` |
| — | Central-date sweep, 14 call sites + ratchet test (`tests/test_slate_date_timezone_discipline.py`) |

### Detail worth keeping

- **73 — ranking signals computed but never applied.** A "highest confidence"
  query and a "highest upside" query returned **byte-identical** orderings. The
  risk profile parsed correctly and reached `preferences`; nothing consulted it.
  Four separate signals, all fully implemented and all inert:
  - `_risk_profile_score_adjustment` and `_market_specific_score_adjustment`
    were **dead code** — defined, never called from anywhere. So `score` was
    `edge x confidence - tier_penalty` and nothing else. Both are no-ops by
    construction outside their trigger (`balanced` profile / no requested
    markets), so wiring them only moves rankings for queries that actually
    expressed a preference.
  - `advanced_ready` appeared nowhere in the board sort, and in the scorer only
    as a ≤0.05 nudge to confidence — far too small to act as the gate its name
    implies. A candidate with missing model inputs could outrank a ready one on
    raw edge.
  - `source_summary_score` (the qualitative read of a basketball prop's
    recent-form writeup) was computed, surfaced in the analysis table and chart
    series, and never ranked on.
  - **`score` itself was absent from the board sort**, which ordered on raw
    `simulated_edge` — a single component outvoting the composite that contains
    it. Fixing the scorer alone changed nothing a user could see; ordering is
    decided in *two* places (`score_candidate` and
    `build_intelligence_board_contract`) and both had to change.
  - ⚠️ **Where a signal goes matters as much as whether it is used.** Folding
    `source_summary_score` into `score` at its native ±3.0 weight regressed
    `test_intelligence_query_prioritizes_ready_advanced_inputs` — a qualitative
    text signal overrode a data-readiness one. Picking a smaller weight would
    have been fitting a magic number to the tests, so it went last in the sort
    as a pure tiebreaker instead, where it only speaks when the quantitative
    signals are genuinely equal.
  - `tests/test_intelligence_ranking_signals.py`, 16 tests, **8 fail against the
    pre-fix source**. Deliberately split: the adjustment-maths tests pass both
    before and after (that function was always correct), so a separate class
    pins that `score_candidate` actually *calls* it — without which the whole
    fix could be reverted and everything else would still pass.
  - Subset went 9 failed / 11 passed → 7 failed / 13 passed, no regressions.

- **29 — cross-type duplicate candidates.** Every pick reached the board twice:
  once as the full candidate (~100 keys, `recommendation_id`, confidence as a
  `"38%"` string) and once as a reduced blotter/ranked row (~35 keys, no
  `recommendation_id`, no `line`, confidence as `38.0`).
  `_recommendation_sources` concatenates several response keys, so both landed
  in one list. **Two independent defects, and fixing either alone changed
  nothing** — which is why this survived so long:
  - The dedup key joined id/name/market parts with `if part`, dropping empty
    components instead of holding position, so the two shapes produced keys of
    different *arity* (`"<recid>|over 0.5|hitter home runs"` vs
    `"over 0.5|hitter home runs"`) and could never collide.
  - `_recommendation_sources` had two early returns handing back the raw list,
    skipping the dedup entirely whenever an upstream key was already populated
    — the common case.
  - **The generalisable rule: a field only ONE representation carries is
    unusable as a hard key component.** True of `recommendation_id`, and
    equally true of `line` — an intermediate fix that put `line` in the tuple
    failed identically (`'0.5'` vs `''`). `line` is now a wildcard: missing on
    either side still matches, two different lines still stay distinct.
  - The same broken key existed in **two copies** (`intelligence_board.py` and
    `pipeline/intelligence_state.py`); both now call one shared
    `dedupe_recommendation_items`, so they cannot drift apart again.
  - `tests/test_intelligence_board_dedupe.py`, 14 tests. Validated against both
    the original key and the intermediate line-in-tuple attempt: both return 2
    where the fix returns 1, so the guards are not vacuous.

- **58 — basketball quarter sim vectorised.** `_simulate_quarters_local` looped
  over samples in Python and, *inside* that, over the four quarters, rebuilding a
  2×2 covariance and running `np.linalg.cholesky` every iteration — ~20,000
  decompositions per game of a matrix that depends only on the quarter. Hoisted
  the covariance and its factor to once per quarter (4×) and replaced the scalar
  `size=(2,)` draws with one `size=(n_draws, 2)` batch per quarter, using
  `Z @ chol.T` for the batched form of `chol @ z`.
  **Measured 215.0 ms → 2.9 ms per game (73×)** at 5,000 samples / 4 quarters.
  - Hoisting the `try`/`except` from per-sample to per-quarter is equivalent
    *because the covariance is sample-invariant*: cholesky either succeeds for
    every sample of a quarter or fails for every one. That is the load-bearing
    argument for the refactor; if a future change makes the covariance vary
    within a quarter, this stops being safe.
  - **Draw order changed**, so a given global RNG state no longer yields the same
    numbers. Nothing depended on it: the function takes no `cfg` and no `rng`,
    never seeds, and the only test that referenced it patched it out entirely.
    Distributions verified equivalent against the pre-fix loop.
  - The fallback path still draws *independent* normals with **no clamping at
    zero**, unlike the correlated path which clamps. That asymmetry predates #58
    and was deliberately left alone — it is a real inconsistency if anyone ever
    hits it, but changing it would have been a behaviour change smuggled into a
    performance fix.
  - `tests/test_basketball_props_quarter_sim.py`, 9 tests. The four structural
    guards were **validated against the pre-fix source: all four fail there and
    pass on the fix**, so they are not vacuous. A distribution-only test would
    have passed against the slow version, which is why the guards count
    decompositions and draw shapes rather than checking moments.
  - ⚠️ **CPU only.** The accumulators went from two 5,000-float Python lists to
    two float64 arrays. Do not read this as progress on #59's memory question.

- **64 — Make the candidate pool's last stage visible** (`a1638c39`).
  *Recorded retroactively 2026-07-26: this shipped on 2026-07-25 and was never
  filed in either list — the only such gap in 200 commits. See #71.*
  Classification and dedupe were the last stage before the pool and the only one
  with no `INTEL_TRACE`; they reported through `_log_json_event` at
  `logging.INFO`, which never reaches Render's collector (#37). So the pipeline
  could discard every candidate and report `candidate_count=0` with no visible
  reason. Adds candidates-in, how many classification and dedupe each removed,
  and a **count per rejection reason**. Deliberately does **not** guess which
  rule fires — the remaining suspects are `missing_selection` and
  `missing_projection_or_odds`, and which one is a production fact to be read,
  not inferred. **The instrument shipped; the reading has not been taken.** That
  reading is the open work in #68.

- **17 — slate endpoint.** Core and segment payloads merge per bookmaker *before*
  `_best_bookmaker_game_lines` scores them; scoring separately would pick one
  book for core and another for segments and mix two books' prices into one
  game. Falls back to per-event on failure, but a fatal `OUT_OF_USAGE_CREDITS` /
  bad-key response **raises** instead — silently falling back to the
  15×-more-expensive path on running out of credits is the worst possible
  response. First tests this fetcher has ever had.

- **18 — NCAAF regions.** Real trade: NCAAF keeps every bookmaker the API returns
  with no US filter, so eu/uk books drop out of each game's provider list — the
  same set every other sport already lives without. `ODDS_API_REGIONS` still
  overrides, so reverting is an env change, not a deploy.

- **25 (Phase 0)** — *Atomic writes*: `atomic_artifact_write.py`, wired into 11
  call sites across 7 producers. `df.to_csv(path)` truncates then streams, so a
  reader arriving mid-write silently gets fewer rows — one of the candidate-swing
  symptoms. Temp files carry pid+uuid and sit in the destination directory.
  *Fail-closed launch marker*: `_record_odds_refresh_launch` moved to **before**
  `launch_refresh_run`; a raise after the spawn used to leave a sweep running
  with no marker and the next tick started a second one (#20). A missed refresh
  self-corrects; a duplicate burns credits and stacks two heavy pipelines. 16
  tests.

- **41 — scoped-resim regression coverage** (`dcda6243` shipped the fix untested).
  `tests/test_mlb_scoped_resim_summary.py`, 8 tests in two layers: a behavioural
  consumer contract on `_games_from_daily_summary`, plus a structural guard on
  the vendored producer — necessary because the fix lives inside a ~2000-line
  `main()` whose helpers are nested locals that cannot be imported. **Validated
  against `dcda6243^`: all five fail on the pre-fix source**, so they are not
  vacuous. If `daily_update.py` is re-vendored and the guards fail, check the
  merge is still present before loosening assertions.

- **14 — quota instrumentation.** Records observations rather than accumulating,
  because `used`/`remaining` are absolute server-side counters — so burn survives
  the lost writes from three services racing on a non-atomic store. Recorded
  *before* `raise_for_status`, since a failed call may still be billed. Reports
  `None` rather than `0` on a single observation: "not measured" must not look
  like "not burning". NCAAF/NCAAB reach the API through `urlopen` with the apiKey
  in the URL, so those record **only the path** — the endpoint is persisted to
  the shared store and must never carry a key.

- **44b — soccer resim, shipped dark.** Enable via
  `SYNDICATE_ENABLE_SOCCER_RESIM_TRIGGER=true` on live-odds-worker plus
  `SYNDICATE_SOCCER_RESIM_TICK_OWNER=false` on refresh-worker. ⚠️ It forces an
  odds refresh with cache bypass and soccer props are ~2,400 credits/sweep
  (#19) — keep dark until burn fits the 5M target.

## Closed 2026-07-26 / 07-27 — the empty-board session

The board went from serving 7 shell-command placeholders to **27 real MLB props
with prices, lines and edges** (`/api/intelligence/status` 2026-07-27T00:05:49Z,
`candidate_count: 27`, all from the one live game, correctly flagged live).
Five defects, in order of how load-bearing they were.

- **79 — the board build's memory guard counted reclaimable page cache.**
  `MEMORY_GUARD_ABORT` every cycle: `current 3228.3 / max 4096`,
  `headroom 867.7` against a 900 floor. But `anon` was **662.5 MB** and
  `inactive_file` **2476.3 MB** with `shmem 0.0` — real headroom was 3393.7 MB.
  Fixed to `max - (current - inactive_file - slab_reclaimable)` (`7b204998`),
  conservative on purpose (`active_file` and `shmem` still count as used) and
  falling back to the old calculation when `memory.stat` is unreadable.
  ⚠️ **This retired the "2.7 GB plateau" as page cache from the 1.24 GB
  odds-events file, not a leak** — which is why `tracemalloc` was blind to it.
  **#76 still leaves that file unbounded.** The gate is shared with
  `live_refresh_loop`'s odds-refresh gate and the MLB live-lens `estimate_live`
  gate, so both gained headroom too.
- **68a — a projection of exactly zero read as missing.** The presence test was
  `_safe_text(value, "") not in {"", "-"}` and `_safe_text` is truthiness-based.
  A live game-level candidate with no explicit `live_projection` gets the game's
  combined score, which is **0 for every scoreless live game**, and that 0 also
  shadowed the real `model_probability` behind it. Fixed with
  `_candidate_value_is_present`.
- **68b — `shared_top_play_rows` published a display panel as picks.** 56 rows
  per MLS slate reading "Projected score: …", "Margin: 0.80 (home perspective)"
  and literally **"Simulations: 400"**. Gated on the row expressing a side
  (over/under) or carrying a scraped price/edge. ⚠️ Only 68a's bug was keeping
  these off the board — fixing 68a alone would have published all 56.
- **77 — placeholders and false liveness.** (a) `_unsimulated_game` empty states
  reached the board as LIVE picks whose `pick` was a shell command; gated at the
  producer on an explicit marker (`70ad2c9f`). (b) **Reported by the user:**
  yesterday's finished MLS fixtures flagged live. The payload contradicted
  itself — `shared_is_live: true` beside
  `shared_game_state {"live": false, …}` — and soccer's `status` is a display
  string so neither the `status` dict nor `live_state` was populated. Structured
  state now wins (`1b333736`), scoped so `shared_is_live` still decides when
  nothing contradicts it.
- **78 — WITHDRAWN, not a date-selection defect.** Every cycle builds TODAY and
  *then* probes tomorrow; the probe emits its own dated traces, so a tail of the
  logs shows only the tomorrow half. Misread into three investigations
  (#65, #68, #78). `ROLLOVER_PROBE_BEGIN`/`END` and dated
  `CANDIDATE_POOL_READY` now make the two halves unambiguous.
- **65 — MISDIAGNOSED, kept as the worked example.** The rollover probe is
  expected behaviour, not a queued future-dated payload; the two guards shipped
  against the queue path never fired because the queue was never involved.
- **66 — board shows no opportunities.** Superseded: the live-slate reading it
  asked for was taken (100% pruned at classification) and the causes are 68a/68b
  above.
- **75 — refresh-worker OOM at 4 GiB.** `_load_jsonl_rows` slurped a 1.24 GB
  odds file before applying its row cap; streamed into a `deque(maxlen=N)`
  (`5181ed3d`), 734.6 MB → 2.9 MB peak.
- **43 — Layer 2 curated board empty.** ✅ **Closure criterion finally met:**
  `candidate_count: 27` **with** `snapshot_generated_at 2026-07-27T00:05:49Z`.
  The transport work (`e323d61f`, `31ff3438`, `81475c19`) is deployed on web and
  worker. ⚠️ **Still unexercised at size** — no cycle since has produced a pool
  large enough to divert to the artifact transport, so the oversized-payload
  path remains deployed-but-unproven. If a big slate ever fails to publish,
  start there rather than assuming it works.
- **71 — nothing checks that shipped work reaches this list.** Audited across
  200 commits: #64 was the only instance, so it is rare rather than systemic.
  The check now lives in Operational notes and was run for this reconciliation
  (30 IDs across 80 commits, all present).

- **80 — admin-token rotation.** Removed from the list at the user's request
  2026-07-27. ID retired, not reused.

- **72 — the per-query prediction-ledger write, deleted 2026-07-27**
  (`569c4e9f`). `record_prediction` ran for every recommendation of every
  intelligence query and rewrote the whole multi-MB
  `data/prediction_ledger.json` on the request path, while its only automated
  reader reported `prediction_ledger_count: 0`. Removed on the user's decision
  that the ledger is obsolete. **Kept:** the `/api/portfolio/bets` write (user
  bets, genuinely read by `/portfolio`) and portfolio_summary's stake-presence
  check (old ledgers still carry stakeless auto-rows). Also deleted the test
  fixture that existed solely to patch this write out — it was 1.46s of a 2.6s
  test. Verified post-deploy: board rebuilt fresh (`01:49:46Z`, 27 candidates).

- **76 —**🟢 **RESOLVED 2026-07-27T01:11Z — verified by file size, not by log line.** `odds_events/<date>.jsonl` grew unbounded (1.24 GB → 1.71 GB in one day); nothing read past the last 2000 rows (`_load_jsonl_rows` deque cap, sole production reader), so it was pure dead weight filling the page cache #79 measured. **Fix, three commits:** append-path compaction to the last 20k raw lines (`0508f8bd`) with a **growth-based** trigger — an absolute ceiling compacted on *every* append once retained > ceiling, 300 compactions/80k rows measured locally, caught before ship; a stale-file scan for closed days (`ec256961`); and the scan triggered from the **read** path too (`3d2110e3`) — production showed refresh-worker holds the 2.66 GB backlog but never appends (odds refresh appends on live-odds-worker), so an append-only hook would never have run on the box that needed it. **Verified in production:** `2026-07-26.jsonl` **1,712,508,566 → 39,296,335 bytes**; `07-24` (315.7 MB) and `07-25` (512.5 MB) stopped printing `ODDS_JSONL_LARGE` entirely (threshold 8 MB), so both trimmed; the `COMPACTED` prints themselves never surfaced (subprocess stdout / spotty logs API) — **the sizes are the evidence**. Residual by design: `07-21/22/23` (46.7/56.9/16.5 MB) sit **below the 64 MB trigger** and are left alone; ~120 MB total, ages out within a week. Footprint ~2.66 GB → ~175 MB. ⚠️ Read-then-replace race documented in the code: fine for tail-read telemetry, needs a lock if a second writer or system-of-record use ever appears. `SYNDICATE_ODDS_EVENTS_COMPACT_BYTES=0` disables.

- **45 — WNBA All-Star game missing from the market board.** Overtaken by
  events 2026-07-26: the game has been played. Closed without a fix at the
  user's direction; if the same gap matters for a future special-event game,
  file it fresh against that game.

- **70 — render.yaml comments contradicted their values.** Closed 2026-07-27 on
  inspection: the comments were **already corrected** in `5b89aef3` (2026-07-26,
  the same reconciliation commit that filed the item) — both intelligence-loop
  blocks now tell the accurate post-#57 story and match their values. The open
  row outlived its own fix by a day; nobody re-checked the file before carrying
  the item forward. Verified directly against render.yaml lines ~318–330 and
  ~550–562 before closing.

- **81 — execution guard released in a `finally`** (`b9da4979`, 2026-07-27).
  Filed and fixed the same night: the release was a plain statement after the
  persist, so 01:04Z's thread death kept the guard held and the MLB sim
  deferred forever against a dead pipeline. The whole acquisition-to-wait
  stretch now runs under a finally; a thread-level test injects a failure into
  exactly the stretch that killed the production thread and asserts the guard
  unlocks even though the thread dies. Verified live: first post-deploy cycle
  built and persisted clean.
- **#29 follow-on — cross-source market synonyms** (`23fcf8fc`, 2026-07-27).
  User-reported: "Tyler Phillips outs is listed twice from two sources." The
  "Pitcher top props" rail (`outs recorded` / `Over 15+`) and the props
  artifacts (`pitcher outs` / `OVER Tyler Phillips`) spell the same bet
  differently, and #29's raw-string core could never collide them. Dedupe key
  now canonicalizes market (role prefix stripped + synonyms) and collapses
  selection to its side token — only when a player subject exists, so game
  markets are untouched. Verified against the live board pre-deploy (38→35,
  exactly the three reported twins) and post-deploy (`board_cards: 35`).
  ⚠️ Lesson: **an automated "no duplicates" check that shares the dedupe's key
  is blind to exactly what the dedupe misses** — a user looking at the actual
  board caught what instrumentation could not. Residual: the candidate POOL
  still carries both shapes (`candidate_count: 38` vs 35 cards); folding the
  canonical key into the pool merge is a small cleanup.

- **87 — event-sim rerun decision always forced a rerun** (2026-07-27). The call
  site at [unified_daily_update.ps1:4619](../../scripts/unified_daily_update.ps1)
  passed `-ArtifactPath [string]$eventPlan.artifactPath` — in PowerShell argument
  mode an un-parenthesized `[type]` before a value is not a cast, it is literal
  text, so the argument was actually `"[string]" + $eventPlan.ToString() +
  ".artifactPath"`, a path that can never exist. `Test-Path` inside
  `Get-EventSimExecutionDecision` (line 2040) therefore always returned false and
  forced `$true`, permanently defeating the fingerprint-equality skip four lines
  below it (line 2052) — the event sim reran every tick regardless of whether its
  inputs had changed. User caught this by reasoning through the parser, not from
  observed behavior. Fixed by parenthesizing: `-ArtifactPath
  ([string]$eventPlan.artifactPath)`. Repro'd the parse bug directly
  (`Test-Arg -ArtifactPath [string]$eventPlan.artifactPath` prints the literal
  `[string]@{...}.artifactPath` text) before and after the fix. Added
  `UnifiedDailyUpdateEventSimDecisionBehaviorTests` to
  `tests/test_unified_daily_update_event_sim_freshness_window.py`, which actually
  invokes the extracted PowerShell function via `powershell.exe -ExecutionPolicy
  Bypass` rather than only pinning source text. ⚠️ **Verified by reverting the
  fix that only the string-pin test catches this exact regression** — the
  behavioral tests construct their own arguments and exercise the function
  correctly regardless of what the buggy call site does, so they pass either way.
  A call-site argument-parsing bug like this one needs a source-text assertion,
  not (only) a functional test of the callee.

- **88 — two production bugs in `refresh_ncaaf_oddsapi.py` from `ce48b4de`
  ("Allow local NCAAF artifact refresh", 2026-05-22)** (2026-07-27). Both were
  in code that had apparently never run end to end since that commit.
  - **(a) `_base_norm` was mangled.** Its body was a copy-pasted fragment of
    `_copy_tree_if_exists` (referencing undefined `source`/`destination`) that
    fell through to `return ""` for every team name; the real normalization
    tail had been left as dead code *after* `_resolve_data_root`'s
    `raise FileNotFoundError`. Every team name normalized to the empty string,
    so `_norm_team`/`_best_schedule_norm` could never match an odds row to a
    schedule row on a real refresh. Fixed by restoring `_base_norm`'s body and
    deleting the dead fragment; also dropped a redundant literal-filename
    `.exists()` check in `_resolve_data_root` that duplicated the glob check
    beneath it and could never match a real (timestamped) filename anyway.
  - **(b) artifact-root-only mode crashed.** `_prediction_files` always looked
    under `<root>/data`, but `scripts/refresh_odds_sources.py`'s NCAAF step
    (the actual production caller) invokes the runner with `--artifact-root`
    only, and that bundle stores
    `college_football_schedule_*_predicted_totals_enhanced*.csv` at the bundle
    **top level**, not under a `data/` subdirectory — so every orchestrator run
    raised `FileNotFoundError` before reaching the OddsAPI call. Verified
    against the real bundle
    (`data/ncaaf_source/source_artifacts/college_football_schedule_2025_predicted_totals_enhanced_*.csv`
    sits at top level, confirmed with `ls`). Fixed `_prediction_files` to try
    `<root>/data` then fall back to `<root>` directly, so both the
    `--source-root` (nested) and `--artifact-root`-only (flat) layouts resolve.
    Reproduced the exact orchestrator invocation
    (`--artifact-root data/ncaaf_source/source_artifacts --week 7`) before and
    after: before, `FileNotFoundError`; after, it reaches the live OddsAPI
    request (fails only on an invalid dummy key, as expected).
  - The existing test (`test_main_uses_artifact_root_as_data_root_when_source_root_omitted`)
    was silently papering over (b) by creating the CSV in **both** locations;
    simplified to only the flat layout now that the runner handles it. Added
    two direct regression tests for `_prediction_files`/`_prediction_context`
    (flat and nested layouts) and one for `_base_norm`/`_norm_team`. All 192
    NCAAF-tagged tests pass (`python -m pytest tests/ -k ncaaf`).
  - ⚠️ **Not yet observed fixed against a live OddsAPI key in production** —
    verification here was local (real bundle files, dummy key, and unit
    tests). Confirm the orchestrator's `ncaaf_lines_snapshot` step actually
    writes updated lines on its next real run before considering NCAAF fully
    healthy again.
  - Both #87 and #88 were marked closed here while their fixes still sat
    uncommitted. Neither reached `main` until a later session (2026-07-27)
    ran `git commit`/`git push` on request, landing in commit `0250ac82`
    alongside #74's fix and the undocumented #91 batch. See the Operational
    note in `todo.md` about the inverse of #71: a closed doc entry does not
    mean the code shipped to git.

- **89 — `migration_gate.py`'s `evaluate_protected_local_resolvers()` was
  stale against `757952e1`** ("Refactor WNBA odds path resolution",
  2026-06-28) (2026-07-27). That commit routed NBA's `processed_path` and
  NHL's `processed_path`/`scoreboard_snapshot_path`/`slate_summaries` through
  the new `odds_control_plane.current_odds_root_for_sport`, which imports
  `preferred_source_roots` in `odds_control_plane.py` itself — not the
  binding in `nba.sources` or `nhl.sources` that the gate was patching. So the
  gate's mocks silently stopped taking effect and it **unconditionally
  reported 3 violations** (`runtime_dependency_ok` permanently `False`,
  failing `tests/test_migration_gate.py::MigrationGateRuntimeDependencyTests::test_evaluate_protected_local_resolvers_passes_current_contracts`).
  - **NHL fix was mechanical.** `_data_roots()` always resolved to a single
    root even before the refactor (`_source_roots()[0] / "data"`), so the
    gate's expected values (local mirror, never the sibling bundle) were
    already right — only the patch target moved, to
    `syndicate.features.nhl.sources._data_roots` directly (matching the
    already-public wrapper the module exposes, rather than reaching into
    `odds_control_plane`'s internals).
  - **NBA is a real contract change, confirmed against the diff, not just a
    stale mock.** `757952e1` deleted the `_first_existing_path` fallback scan
    from `processed_path`/`live_snapshot_path`; NBA no longer picks whichever
    preferred root actually has the file — it always resolves to the primary
    root now, matching NFL/NCAAF's existing "stays on local mirror, no
    sibling-app fallback" pattern and the codebase's stated direction away
    from source-app fallback dependencies. Updated the gate's expectation to
    match (`local_root`, not the external bundle) and patched
    `nba.sources.artifact_processed_root` directly, alongside the existing
    `nba.sources.preferred_source_roots` patch (the latter still governs
    `available_dates()`, which is unaffected by this refactor). This mirrors
    the patch convention other pending test fixes in the same working tree
    (`tests/test_nba_live_snapshots_local.py`, `tests/test_nba_refresh_runner.py`)
    had already converged on for the same `757952e1` gap — same root cause,
    caught independently in two places.
  - Verified: `python -m pytest tests/test_migration_gate.py -q` → 16 passed;
    `evaluate_protected_local_resolvers()` also returns `[]` against the real
    (unpatched) environment.
  - ⚠️ **Surfaced a real, separate latent inconsistency, filed open as #90**:
    NBA's `available_dates()` was left scanning all preferred artifact roots
    while `processed_path()` now only resolves the primary one — dormant
    today because production has one NBA root, but a foot-gun the moment a
    second one exists.

---

## Closed earlier

- **1** sim fast-path runtime ceiling · **2** memoize `build_reliability_profile` ·
  **3** deploy+restart for stuck 7-25 sim · **4** last-known-good board while stale ·
  **5** mini card live scoreboard · **6** last odds refresh + sim run on cards ·
  **7** Layer 2 blotter fixes · **9–11** odds-history Phases 1–3 · **13**
  per-candidate live-state cache defeat
- **8** Empty production board (the `NameError`). ⚠️ *The fix was correct, but the
  same symptom recurred 2026-07-25 via an unrelated cause (#43). "Empty board" is
  a symptom with at least two distinct root causes — do not treat it as a solved
  class.* (This warning is also carried in `todo.md`'s Operational notes, because
  it is still live.)
