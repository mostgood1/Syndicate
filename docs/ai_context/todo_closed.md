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
| **57** | Board build stays on refresh-worker, upgraded to pro/4GB |
| **60** | Keyvalue payload ceiling — oversized writes fail loudly |
| **63** | Mutual-deferral starvation invariant test |
| **64** | Candidate pool's last stage made visible — `a1638c39` |
| **67** | Soccer game state derived from the clock, not a frozen `status_state` |
| — | Central-date sweep, 14 call sites + ratchet test (`tests/test_slate_date_timezone_discipline.py`) |

### Detail worth keeping

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
