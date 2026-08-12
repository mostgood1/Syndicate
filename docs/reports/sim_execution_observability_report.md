# Sim execution by sport — what runs, when, how long, and what triggers it

Measured 2026-08-12 against **production** (Render logs API, Render events API,
`/api/ops/live-refresh/state` on the web service). Nothing here is read from the
local `data/**` mirror.

---

## 0. The headline

**Only MLB has a sim run ledger, and half its entries are wrong.**

> **Update, same day.** All three defects below were fixed. `#388` (half the
> entries wrong) and `#389` (NFL busy loop) are **deployed and confirmed in
> production**; `#390` — a ledger for the other six sports — is **built and
> pushed but not deployed**, so the table below still describes production
> until it lands. See §9.

| question | MLB | NFL / NCAAF | soccer | NBA / WNBA / NHL | NCAAB |
|---|---|---|---|---|---|
| launches recorded? | yes (`MLB_DAILY_SIM_TRIGGERED`) | no | no | no | n/a (no sim step) |
| completion recorded? | **51% never finalize** | no | no | no | n/a |
| duration recorded? | start/end only, on the worker disk | no | no | no | n/a |
| readable from web? | yes, ~2-day retention | no | no | no | n/a |

Everything below for non-MLB sports was reconstructed by *sampling the worker's
process table* out of `ALL_PROCESS_MEMORY` log lines — an instrument that exists
for memory diagnostics and happens to print child `cmdline`s. That is the only
route to a non-MLB sim duration that exists today.

---

## 1. There is no cron. Everything is a polling loop.

`render.yaml` defines no `type: cron` service. Three interval loops decide
everything:

| loop | service | interval |
|---|---|---|
| `run_refresh_worker.main` | refresh-worker | `SYNDICATE_REFRESH_WORKER_POLL_SECONDS`, default **30s** |
| `live_refresh_loop` | live-odds-worker | 60s live / 900s idle, adaptive |
| `live_lens_loop` | refresh-worker | `SYNDICATE_LIVE_LENS_INTERVAL_SECONDS`, default **60s** |

Which service owns a given sport's sim is an **env flag**, not a code path
(`SYNDICATE_MLB_SIM_TICK_OWNER`, `WEEKLY_SPORTS_REFRESH_TICK_OWNER`, …). The MLB
sim decision function is called from both loops; ownership is decided at runtime.

---

## 2. MLB — measured

### Cadence
189 launches over 167.2h = **27.1 launches/day**. Median gap between launches
**19 min** (p10 7 min, p90 50 min).

Launches per UTC day: 17, 40, 33, 30, 23, 9, 20, 17 (08-05 → 08-12).

There is a hard daily quiet period of **10–17h**, consistently ending with a
`tip_off_window` launch:

    08-10 05:58 -> 08-10 22:39   16.7h
    08-11 05:33 -> 08-11 22:16   16.7h
    08-12 05:20 -> 08-12 17:14   11.9h

So MLB sims run roughly **16:00Z–06:00Z** (11:00–01:00 Central) — the slate
window — and nothing runs outside it.

### What triggers a launch (n=189, 7 days)

| reason | count | share |
|---|---|---|
| `fingerprint_change` | 101 | 53.4% |
| `tip_off_window` | 67 | 35.4% |
| `first_appearance` | 12 | 6.3% |
| `evening_next_day_sim` | 9 | 4.8% |

- **`first_appearance`** — the first sim of a slate. Fires when
  `daily_summary_<date>.json` does not exist.
- **`evening_next_day_sim`** — pre-warms *tomorrow's* slate after 18:00 Central.
- **`tip_off_window`** — game starts within `SYNDICATE_EVENT_SIM_FORCE_WINDOW_MINUTES`
  (**30**), once per game, marker in `mlb_tip_off_simmed.json`. Bypasses the interval gate.
- **`fingerprint_change`** — the dominant re-sim trigger. Per-game hash over
  `{lineups, odds slice, probable-pitcher overrides, injuries, posted_lineups}`.
  Rate-limited by `SYNDICATE_MLB_SIM_CHECK_INTERVAL_SECONDS` = **600s**.

Three further re-sim triggers exist in code but did not fire in this window:
`join_mismatch_needs_resim`, `board_missing_games`, `props_now_available`.

Note `first_appearance` (12) + `evening_next_day_sim` (9) = 21 "first sims" over
7 slates. A slate has one first sim. The excess is re-first-simming after the
prior attempt died — see §3.

### Duration (n=20 completed runs)

    min 9.2m | p25 13.8m | p50 14.8m | p75 16.9m | max 31.9m

**Duration is inverse to scope**, which is the opposite of the intent:

| games scoped via `--only-game-pks` | n | p50 |
|---|---|---|
| 1 | 4 | **19.5m** |
| 2–5 | 7 | 14.7m |
| 6–10 | 4 | 14.1m |
| 11–15 | 3 | **11.7m** |
| whole slate | 2 | 19.6m |

Re-simming one game costs at least as much as re-simming fifteen. The run is
dominated by fixed cost — the `ui-daily` workflow's 3 profiles, the vendor odds
mirror hydration, the player-game-log bootstrap, and `publish_changed_hot_artifacts`
— not by per-game simulation. **Scoping a re-sim currently buys nothing.**

For context, `scripts/run_mlb_daily_sim_job.py:169-176` documents 45–55 min
whole-slate and a 49-min scoped run. Measured today: p50 14.8m, max 31.9m. The
kill ceiling `SYNDICATE_MLB_SIM_TIMEOUT_SECONDS` is **5400s** — ~6x the p75.

---

## 3. Half of all MLB sims are killed by deploys, and nothing records it

**21 of 41 runs (51%) with a status record are stuck at `state: "running"`** —
including one from 40.7h earlier. Every run that *did* finish exited 0. **There
is not a single recorded failure**, because the failure mode cannot be recorded.

Correlating against the Render events API for refresh-worker:

| | orphaned | completed |
|---|---|---|
| a deploy/restart happened during the run | **9 / 9** | **0 / 4** |

Perfect separation. **25 deploys hit refresh-worker in 17.8h on 08-12 alone.**

### Why nothing records it

`_persist_finished_mlb_sim_run` (`live_refresh_loop.py:2159`) is the only writer
that finalizes a run record, and it reads the module-global `_MLB_SIM_RUN_META`.
A container restart kills the sim subprocess **and** clears that global, so the
finalize can never run. The `*_status.json` stays `"running"` forever.

The concurrency guard is *not* the bug — it correctly clears the active pointer
when `started_dt < _PROCESS_STARTED_AT` (`live_refresh_loop.py:2124-2131`), so a
restart doesn't wedge future sims. It just never writes the death certificate.

**Consequence for the trigger question:** a deploy is an unlogged re-sim
trigger. The sim dies, the artifact never lands, the next tick sees
`first_appearance` or `fingerprint_change` and relaunches. A meaningful share of
the 27 launches/day is re-work caused by deploy churn, not by new information.

### Two writers clobber the same file

`scripts/run_mlb_daily_sim_job.py:394` writes a **camelCase** payload
(`ok`, `returnCode`, `timedOut`, `startedAt`, `finishedAt`, `publishedArtifacts`,
`sims`, `workers`).
`live_refresh_loop.py:2189` writes a **snake_case** payload to the same path
(`state`, `exit_code`, `started_at`, `finished_at`, `pid`, `reason`).

Last writer wins, and the launcher usually writes last: **40 of 41 records carry
the launcher schema**. The wrapper's own outcome fields — including
`publishedArtifacts` and `timedOut` — are destroyed in 98% of runs.

Also, within a single record `started_at` is UTC (`...Z`) and `finished_at` is
Central (`...-05:00`). Durations are correct if parsed tz-aware, and wrong for
anyone eyeballing the two strings.

### The sim's own lifecycle log never reaches Render

`run_mlb_daily_sim_job.py` prints `MLB_DAILY_SIM_START`, `MLB_DAILY_SIM_END` and
`MLB_DAILY_SIM_TIMEOUT` with `flush=True`. Across **7 days of Render logs for
both workers: 189 `TRIGGERED` lines, 0 `START`, 0 `END`, 0 `TIMEOUT`.** The
launcher redirects the child's stdout to a file on the worker disk, so the only
sim event visible in logs is the launch. You can see every sim start and no sim
finish.

---

## 4. NFL — running ~90 sims/day against a 24-hour TTL

Observed on refresh-worker over 43.2h:

| process | episodes | per 24h | p50 duration |
|---|---|---|---|
| `generate_smartsim2_nfl_projections.py --season 2026 --week 1` | 83 | 46 | 173s |
| `generate_smartsim2_nfl_preseason_projections.py --season 2026 --week 2` | 72 | 40 | 183s |

Median gap between episode starts: **5 minutes**. These are sequential, not
overlapping — merging overlapping PID segments left all 83/72 distinct.

`SEASON_PROJECTION_REFRESH_INTERVAL_SECONDS` defaults to **86400**. Expected: 1
run/day/sport. Actual: ~46. **The TTL is not holding.**

Cause (`scripts/run_refresh_worker.py:2455-2458`):

```python
age_seconds = _file_age_seconds(artifact_path)
if age_seconds is not None and age_seconds < float(_season_projection_refresh_interval_seconds()):
    continue
```

`_file_age_seconds` returns `None` when `path.stat()` raises — i.e. **when the
artifact is missing** (`:261-266`). The guard maps that unknown onto its
permissive branch, so a projection artifact that never appears at
`data/nfl_source/smartsim2_projections_2026_wk1.csv` makes the sport
*permanently* stale and relaunches it every tick, forever, throttled only by
`_season_projection_process_still_running`.

I have not read the worker disk, so I cannot say *why* the file is absent — but
the observed 5-minute relaunch cadence is itself proof the predicate never
evaluates to "fresh". Either the file is missing or it is always >24h old; both
mean the guard is inert.

Separately: the season script is pinned to `--week 1` in mid-August.

Cost: ~90 launches/day × ~3 min ≈ **4.5 process-hours/day** on the 4GB worker
that also runs MLB sims, and each one is a fresh Python process competing for
the memory headroom the MLB sim gate checks (floor 900MB).

---

## 5. Soccer, WNBA, and the rest

Observed on refresh-worker, same 43.2h window:

| sport | process | episodes | per 24h | p50 | max |
|---|---|---|---|---|---|
| soccer | `build_soccer_artifacts.py` | 15 | 8 | 24s | 374s |
| wnba | `refresh_wnba_oddsapi_props.py` (SmartSim) | 2 | 1 | 131s | 261s |
| nba, nhl, ncaaf, ncaab | — | **0** | — | — | — |

Caveats that matter:

- Soccer and WNBA sims run **inside** the odds refresh, not as their own job.
  There is no launch line, no run stamp, no status record — the episode above is
  a child process caught in a memory sample.
- The zero for NBA/NHL/NCAAB is consistent with off-season, but **this window is
  43.2h in August**; it is not evidence those pipelines work. NCAAF has a
  SmartSim2 script and was never observed running while NFL ran constantly.
- `SYNDICATE_ENABLE_SOCCER_RESIM_TRIGGER` defaults **off** and is not set in
  `render.yaml`, so soccer's join-mismatch re-sim path is dark in production.
- Soccer's own re-sim doesn't spawn a sim — it adds `soccer` to
  `force_refresh_sports` so the odds refresh re-runs the artifact build.

### Method and its limits

`ALL_PROCESS_MEMORY` sampling is bursty (median gap 5s but not uniform), so a
short sim between samples is invisible and a duration is a *lower bound*. To
calibrate it: for MLB, where a ground-truth launch count exists (38 in the same
window), the sampling method found 46 wrapper episodes — within ~20%. Treat the
non-MLB counts as ±20% and the durations as floors.

---

## 6. Answering the five questions

**When do sims run, by sport?**
MLB: 16:00Z–06:00Z daily, 27 launches/day, nothing outside the slate window.
NFL: continuously, every ~5 min, both season and preseason, 24/7.
Soccer: ~8 episodes/day inside odds-refresh runs.
WNBA: ~1/day inside odds-refresh runs.
NBA/NHL/NCAAB: not observed in a 43h August window.

**How long do they take?**
MLB p50 14.8 min (9.2–31.9). NFL ~3 min. Soccer 24s p50, 374s max. WNBA ~2–4 min.
Only MLB's is recorded anywhere; the rest are reconstructed and are lower bounds.

**How often?**
MLB every ~19 min during the slate. NFL every ~5 min always. Soccer ~every 18 min
when it runs at all. These are launch rates, not success rates — see below.

**When is a game simmed for the first time?**
MLB: `first_appearance` on the first tick where `daily_summary_<date>.json` is
absent, plus an evening pre-warm for tomorrow after 18:00 Central. 21 such
launches for 7 slates — the first sim is being redone.
Other sports: whenever the first odds refresh of the day executes the sport's
generation step. There is no first-sim event for any non-MLB sport.

**What triggers a re-sim?**
Recorded: `fingerprint_change` (53%), `tip_off_window` (35%).
**Unrecorded and material: deploys.** 9/9 orphaned runs had a deploy during the
run; 0/4 completed runs did. 25 deploys hit refresh-worker in 17.8h.
For NFL: a missing-artifact TTL guard that reads "unknown" as "stale".

---

## 7. What would close the gap

Ordered by how much each buys relative to cost. **Not implemented — proposal only.**

1. **Finalize orphaned runs from durable state, not a process global.** Have the
   decision tick reconcile any `state: "running"` record whose
   `started_at < _PROCESS_STARTED_AT` to `state: "killed_by_restart"`. That
   information is already present and already used to clear the active pointer.
   Turns a 51% blind spot into a counted failure mode.
2. **One writer for the run record.** Pick a schema, give the wrapper's outcome
   fields their own key, and stop the clobber. Add `duration_seconds` explicitly
   rather than making every reader diff two differently-zoned timestamps.
3. **Make the NFL guard fail closed.** `age_seconds is None` means "we don't
   know", not "it's stale" — a missing artifact should emit a reason and back
   off, not relaunch every 5 minutes. Same shape as the guard defects already on
   the TODO list.
4. **A per-sport sim ledger.** MLB's `TRIGGERED` line and run-status file are the
   right shape; nothing else has one. A launch/finish record per sport — sport,
   trigger reason, scope, start, end, exit — is the only thing that makes this
   report reproducible without the Render logs API.
5. **Stop scoping MLB re-sims until the fixed cost drops.** `--only-game-pks 1`
   is measurably slower than the full slate. Either the scoping should skip the
   fixed stages or it should be dropped as a false economy.

---

## 8. Which telemetry signals actually tell you a sim is running

This section exists because **two widely-used signals were being read backwards**,
and the pre-deploy "is a sim running?" check is load-bearing given §3.

### `PROCESS_TREE_MEMORY.child_count` — BROKEN. Reads 0 with a sim running.

**An earlier revision of this report called this signal valid. That was wrong,
and the error is instructive enough to leave in.**

The reasoning was: sims are `subprocess.Popen` children of the worker main, so a
child counter must see them. The `ppid` relationship is real —
`ALL_PROCESS_MEMORY`, refresh-worker 2026-08-12 18:35:10Z:

    pid=38   ppid=1    rss=1944.4  python scripts/run_refresh_worker.py     <- worker main
    pid=692  ppid=38   rss=  39.4  scripts/run_mlb_daily_sim_job.py         <- MLB sim wrapper
    pid=693  ppid=692  rss=  99.5  tools/daily_update.py --workflow ui-daily<- MLB sim engine
    pid=696  ppid=693  rss= 102.5  vendor/mlb_bettingv2/...
    pid=687  ppid=38   rss=  26.5  generate_smartsim2_...                   <- NFL sim
    pid=694  ppid=38   rss=  26.1  generate_smartsim2_...                   <- NFL sim

But **validating the concept is not validating the instrument.** Testing what the
field actually reads while pid 692 was provably alive, same service, overlapping
windows:

    PROCESS_TREE_MEMORY  18:30-19:10Z   child_count == 0  on  55 / 55 lines
    ALL_PROCESS_MEMORY   18:35-18:44Z   sim visible      on  99 / 99 lines

`child_count` comes from `psutil.Process().children(recursive=True)`
(`memory_observability.py:412`) — children of *whatever process emits the line*,
which is not the worker main. It read 0 through an entire 40-minute window
containing a running MLB sim, two running NFL sims, and a 4-deep process tree.

**`child_count: 0` is not evidence that no sim is running.** Anyone using it as a
pre-deploy check is reading an instrument that cannot show the thing being
checked for. The exact mechanism (why the emitter's `children()` is empty when
`ppid=38` says otherwise) is **not established** — the measurement above stands
on its own and is what should drive the decision.

### `ALL_PROCESS_MEMORY` — VALID. Use this one.

Container-wide enumeration via `psutil.process_iter`, so it does not depend on
the emitter's position in the tree. It showed the sim on **99 of 99** lines in
the window where `child_count` showed 0 on 55 of 55, and it carries full
`cmdline`s, so it identifies *which* sim. Every non-MLB measurement in this
report rests on it.

### `CONTAINER_MEMORY.game_count` — NOT a sim signal. Do not use it.

### `CONTAINER_MEMORY.game_count` — NOT a sim signal. Do not use it.

Emitted only by `apply_game_board_contract` via `_log_board_contract_memory`
(`game_board_contract.py:594,596`) as `game_count=len(games)` — the size of a
**board-contract build**. 100 live `board_contract_begin` lines from
refresh-worker:

    18:58:27  soccer   9      18:58:28  soccer  31
    18:58:27  soccer   5      18:58:28  soccer   1
    18:58:27  soccer   1      18:58:28  soccer   9
    18:58:27  soccer  11      18:58:28  soccer  11

It swings 1 → 9 → 11 → 31 → 1 **inside a single second**, cycling across sports
and soccer leagues. A descending run of values (e.g. 15 → 9 → 3 → 1) is four
successive board builds for different sports, not a sim draining a slate. The
field that disambiguates it — `sport` — is in the same JSON payload.

### Durable vs. in-memory state — what a reboot destroys

This is the split that explains §3, and it matters to anyone reasoning about
whether a "first sim" observation is real or an artifact of a restart.

| state | storage | survives reboot? |
|---|---|---|
| `first_appearance` predicate | `daily_summary_<date>.json` on disk | **yes** |
| `fingerprint_change` predicate | `last_mlb_sim_check.json` via `refresh_state_store` | **yes** |
| `tip_off_window` markers | `mlb_tip_off_simmed.json` | **yes** |
| active-run pointer | `mlb_sim_runs/_active.json` | yes (and correctly self-clears) |
| **run completion** (`_MLB_SIM_RUN_META`, `_MLB_SIM_PROCESS`) | **module globals** | **no** |

**Every trigger predicate is durable; only the death certificate is not.** So
deploy churn does not corrupt the trigger statistics in §2 — it *generates* the
orphan records in §3.

### Other measurement notes

- `logger.info` never reaches Render's log collector; only `print(..., flush=True)`
  does. Any instrumentation added must use `print`.
- Render logs API works and its `text=` filter is fuzzy, not a substring match —
  it returns near-misses, so filter client-side. `limit` > 100 returns HTTP 400.
  Owner `tea-d2bb5n95pdvs73cje4fg`; refresh-worker `srv-d91dpertqb8s73co8ls0`,
  live-odds-worker `srv-d91dpertqb8s73co8lt0`, web `srv-d88ahvrbc2fs73eodu30`.
- `/api/ops/refresh/status` does **not** exist (404). Use
  `/api/ops/odds-refresh/status` and `/api/ops/live-refresh/state`.
- The ops admin token goes in `X-Admin-Token` or `?admin_token=` — **not**
  `?token=`, which 401s (`ops.py:198-205`).
- `/api/ops/live-refresh/state` resolves historical runs via
  `?sim_run=<stamp>&sim_date=<date>`, but the state store retains only ~2 days:
  41 of 189 launches over 7 days still had a record.
- `memory_current` is page cache. Use `memory_anon_mb`.
- Counters flushed on refresh-worker cannot appear on web's `/api/ops` — separate
  disks.

### The `#23` board-build-on-main-loop path, in this report's terms

`live_refresh_loop.py:1866-1894` runs a full `build_mlb_market_board` on the
worker's main loop to derive `join_mismatch_needs_resim`. It is documented
in-code (it "OOM-killed the 2GB container in ~14 seconds") and tracked as `#23`
with a memory gate as an acknowledged *partial* mitigation.

New data point from this report: **`join_mismatch_needs_resim` did not fire once
in 189 launches over 7 days.** The full board-build cost is paid on the check
path every tick for a trigger that produced zero launches in a week.

---

### The general rule these keep instantiating

**An instrument that cannot record the failure mode is indistinguishable from an
absence of failures.** Three separate instances in this report alone:

- Every completed MLB sim reads `exit_code: 0` and there are **zero recorded
  failures** — because the only writer that could record one is cleared by the
  event that causes the failure (§3).
- `child_count: 0` looked like "no sim running" for a whole afternoon of
  pre-deploy checks. It reads 0 with three sims running.
- The NFL TTL guard treats "artifact missing" as "not fresh, launch" and emits no
  reason, so a permanently-broken artifact path looks identical to a normal
  refresh cadence (§4).

The operational form: **a healthy reading is evidence only once you know what
makes it read unhealthy.** Before trusting `child_count: 0`, confirm a running
sim makes it non-zero. Before trusting a run ledger with no failures, confirm a
killed run can be written into it. Neither was true here.

This is the same shape as three defects already on the TODO list from other
sessions today — a counter the endpoint never served, a floor that shipped inert,
and a test that asserted "nothing is excluded" and so could never fail.

---

## 9. Change log

Every finding above is measurement only. **No production code has been changed
and nothing has been deployed by this work.**

| when | what | status |
|---|---|---|
| 2026-08-12 | Mapped sim trigger/scheduling code across all 8 sports (read-only) | done |
| 2026-08-12 | Measured 7 days of MLB sim launches from Render logs API (n=189) | done |
| 2026-08-12 | Measured MLB durations/completion from `/api/ops/live-refresh/state` (n=41) | done |
| 2026-08-12 | Correlated orphaned runs against Render events API (9/9 vs 0/4) | done |
| 2026-08-12 | Reconstructed non-MLB sim lifetimes from `ALL_PROCESS_MEMORY` sampling | done |
| 2026-08-12 | Identified NFL TTL guard defect at `run_refresh_worker.py:2455` | done |
| 2026-08-12 | Established `game_count` is a board-build size, not a sim signal (§8) | done |
| 2026-08-12 | **Retracted** an earlier claim in this report that `child_count` was valid; measured it reading 0 with three sims running (§8) | done |
| 2026-08-12 | Filed on `docs/ai_context/todo.md` as `#388` (deploy-killed sims / broken run ledger), `#389` (NFL TTL guard), `#390` (no sim ledger for 6 of 7 sports) | done |
| 2026-08-12 | Renumbered those three from `#387`–`#389` after a concurrent session pushed its own `#387` into the same gap | done |
| 2026-08-12 | **`#388` implemented** — orphan reconcile, merge-not-clobber, `duration_seconds`, launcher-emitted `MLB_DAILY_SIM_END`. 8 new tests, 5 red without the change; `test_live_refresh_loop.py` 219 passed | **in working tree, NOT deployed** |
| 2026-08-12 | **`#389` implemented** — one shared staleness decision for both NFL autoruns; missing artifact falls back to last-launch age instead of reading as stale. 12 tests; the wiring test fails against `HEAD` with `Popen ... Called 1 times` | **pushed, NOT deployed** |
| 2026-08-12 | `#388`+`#389` deployed to refresh-worker (`239b5eba`, live 20:32:22Z) | **live** |
| 2026-08-12 | `#389` **confirmed in production** — 2 launches in 62 min vs ~12, suppression named in the log; surfaced that the NFL artifacts are never written at all | **confirmed** |
| 2026-08-12 | `#388` **regression**: live-odds-worker stamped 3 of 3 live sims `died_untracked` — shared pointer vs local `_process_exists`. Gate `f6c0525f` deployed to live-odds-worker (live 21:44:13Z) | **confirmed 21:54Z** — first post-gate launch clean, null verified against a live instrument |
| 2026-08-12 | **`#390` built** (`2411d748`) — `sim_run_ledger` wired at `_run_command` (soccer/nba/wnba/nhl), the season-projection autorun (nfl/ncaaf) and the MLB launcher; read via `/api/ops/sims/ledger?date=`. 11 tests, incl. wiring against the real step runner | **pushed, NOT deployed** |

### `#388` as implemented

Four changes in `syndicate/features/shared/live_refresh_loop.py`, plus
`tests/test_mlb_sim_run_reconcile.py`:

1. **Orphan reconcile.** All five branches of `_shared_mlb_sim_still_running`
   that decide a run is over now record *why* before clearing the pointer:
   `killed_by_restart`, `killed_runtime_ceiling`, `killed_stalled`,
   `died_untracked`. No new state — the active pointer already carried the run
   identity and already outlived the restart that clears the module globals.
2. **Merge, not replace,** in `_persist_finished_mlb_sim_run`, so the wrapper's
   `publishedArtifacts`/`timedOut`/`ok`/`sims`/`workers` survive.
3. **`duration_seconds` as a field**, so nobody diffs a UTC `started_at` against
   a Central `finished_at` by eye.
4. **`MLB_DAILY_SIM_END` emitted by the launcher**, which is not redirected —
   closing the pair that was 189 starts to 0 finishes. Emitted *before* the
   state-store write deliberately: the write is the half that fails silently.

**Two things the implementation had to get right that the report's §3 didn't
anticipate:**

- The "already finalized?" check **must tolerate both schemas**. A
  wrapper-written record has *no `state` key at all*, so a `state != "running"`
  test reads a completed run as unfinalized and stamps it killed. That is the
  most dangerous false positive available here, and it exists only because of
  the two-writer split in §3.
- For an orphan, `duration_seconds` is an **upper bound**, not a duration: the
  run died when the container did and we only notice on the next tick, so the
  gap includes the restart. The test asserts a bound rather than an equality so
  the field's meaning is recorded rather than implied.

Verified by reverting the file to `HEAD` and re-running: **5 of 8 tests fail
without the change.** The 3 that pass either way are the false-positive guards,
which old code passes by doing nothing — worth knowing, since "the test passes"
would otherwise have been misread as coverage.

### Coordination

Checked with the `Syndicate engineering oversight` session before and during this
work. Clear for this report: `scripts/daily_update*`,
`syndicate/features/simulation_engine.py`, refresh-worker scheduling. Held by
that session today: `pipeline/intelligence_state.py`,
`syndicate/features/intelligence.py`.

An MLB sim was in flight for part of this work (started 18:34:44Z, 4 games,
`fingerprint_change`). Nothing here triggered, cancelled, or deployed anything.
