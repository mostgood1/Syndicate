# Handoff — refresh-worker OOM (RESOLVED 2026-07-26 19:06 UTC)

> **SUPERSEDED IN PART — 2026-08-16.** This document's headline
> ("RESOLVED", "LOCATED: the OOM is inside `apply_game_board_contract`") is
> **falsified for the excursions occurring since 2026-08-15**. Measured
> 2026-08-17 in production: a full `apply_game_board_contract` triplet
> (`sport=nfl games=16`) ran mid-excursion for **anon 2935 -> 2937 MB (+2 MB)**.
> The board contract builder is cheap and is not the allocator.
>
> The 2026-07-26 fix in this document may still be correct for the excursion it
> addressed; what is wrong is reading this file as a current diagnosis. The
> refresh-worker was still `oomKilled` at 02:27:07, 02:51:09, 02:57:53 and
> 03:10:46 on 2026-08-17.
>
> Current state: `.syndicate/state.md` (refresh-worker OOM sections) and
> `docs/ai_context/worker_thread_and_entrypoint_map.md`.

## Resolution

**Root cause: `_load_jsonl_rows` read the entire odds-events file into memory
before applying its row cap.** Production's `data/odds_events/2026-07-26.jsonl`
was **1,238,217,572 bytes (1.24 GB)**. `path.read_text()` allocated that as one
string, `.splitlines()` built a list of every line, every line was parsed, and
*only then* was the result sliced to the last 2000 rows. The cap bounded what
the caller received; it never bounded what the read cost.

Fixed in `5181ed3d` by streaming the file into a `deque(maxlen=N)`. Measured on
a 135 MB file: **734.6 MB peak → 2.9 MB peak, identical output, 251× less.**

Confirmed live:

| | |
|---|---|
| last OOM | 19:05:36, during the deploy, on the old code |
| since `server_available` 19:06:37 | **no OOM, no restart** |
| 1.24 GB file read post-fix | 19:09:09 — read it and survived |
| MLB 15 games | completed |
| soccer 17 games | completed |
| memory | plateaus ~2.65–2.70 GB / 4096 (65–67%), oscillating, not ratcheting |
| **`STATE_PERSIST_BEGIN candidate_count=7`** | 19:09:45 — **board rebuilt on a worker for the first time since 00:02 UTC** |

Why it began at 00:02 UTC mid-slate, and why local never reproduced it: on a
live slate the odds refresh appends to today's file continuously, so the mtime
the `_JSONL_ROWS_CACHE` keys on changes constantly, every lookup misses, and the
full re-read repeats — once per game, per board build. Local `odds_events` files
are 17–97 KB.

The comment above that cache asserted the opposite — *"a miss just means one
full re-read of a file already capped to `_MAX_JSONL_ROWS_PER_FILE`"* — and
believing it is most of why this stayed open for a day. Corrected in place.

### Still open after this

- **The odds-events file grows unbounded** — 1.24 GB in a single day. Reading it
  is now cheap, but nothing prunes or rotates it. See **#76**.
- **~2.7 GB plateau** leaves only 1.4 GB headroom on a 4 GiB container. Not
  failing, but not comfortable. The climb happens during MLB games 0–11.
- **#66 / #68** can now be re-validated — `candidate_count=7`, not zero.
- The `cards_context_*` / `board_contract_*` / `sim_contract_*` / `ADV_CTX_SIZE`
  / `ODDS_SHARD_SIZE` instrumentation is still deployed. Keep it until the
  plateau above is understood, then prune with #38.

---

## The investigation (kept — the wrong turns are the useful part)

Read this before touching `build_intelligence_overview`, `_build_sport_overview`,
or `build_cards_page_context`.

---

## Status

refresh-worker (`srv-d91dpertqb8s73co8ls0`) is OOM-killed at its **4 GiB** limit
and restarts continuously. Observed since **00:02 UTC on 2026-07-26**; 51 kills
in one sampled window. Cadence was ~5 min, and is faster (~40 s) immediately
after a deploy because the loop retries at once instead of waiting for its
interval.

Consequence: **the intelligence board has not rebuilt on a worker all day.**
Re-read #66 and #68 with that in mind — their evidence was gathered while this
was happening, so "candidates drop to zero" may be partly or wholly this.

Not caused by the code deployed that morning: the OOMs predate `ef63996cd`
(04:55 UTC) by nearly five hours.

---

## The verified chain

```
build_intelligence_overview(force_refresh=True, skip_game_hydration=False)
  └─ _build_sport_overview("mlb", …)          syndicate/blueprints/home.py:5101
      └─ _load_home_games("mlb", …)           syndicate/blueprints/home.py:4934
          └─ _MLBDataProvider.games()         syndicate/blueprints/home.py:4156
              └─ build_cards_page_context()   syndicate/features/mlb/cards.py:4683
```

`build_cards_page_context` is the heaviest render path in the app — it backs
`/mlb/api/cards`, already documented as "the heaviest route and the last to come
back" after a deploy. The worker builds that whole page context and keeps only
`payload["games"]`.

**~3.7 GB goes into this one call.** Memory reaches `post_pull_hot_artifacts` at
346 MB, then the process dies ~55 s later at 4096 MB.

### Three things make it fatal rather than merely wasteful

1. **`build_cards_page_context` deep-copies its entire cached payload on every
   call** — [cards.py:4700](../../syndicate/features/mlb/cards.py). So the cache
   holds one copy and the caller gets a second:
   ```python
   cached_context = _cards_context_cache_get(page_cache_key)
   if cached_context is not None:
       return deepcopy(cached_context)
   ```
2. **`force_refresh=True` defeats the overview cache** —
   [home.py:5131](../../syndicate/blueprints/home.py) is
   `if cached and not force_refresh`, so there is no TTL cushion. Every cycle
   pays full cost.
3. **The 2026-07-24 fix deliberately did not cover this path.**
   `skip_game_hydration=True` exists *because* these loaders were measured
   "large enough to exceed the container's 2GB memory limit within one call"
   (see `_build_sport_overview`'s own comment). It was applied to the
   fingerprint path only. Candidate collection must pass `False` because
   `_collect_candidates` reads `dashboard_games`/`home_rails` off the result —
   so the known-fatal call stayed live on exactly the path that needs it.

---

## How this was established (don't redo it)

There are **two** passes over the sports and they behave completely differently.
Confusing them cost hours:

| Pass | Args | Result |
|---|---|---|
| Fingerprint | `skip_game_hydration=True` | all 8 sports in ~2 s, 191 MB → 318 MB |
| Candidate collection | `force_refresh=True, skip_game_hydration=False` | begins MLB, **never finishes it** |

The eight `overview_counts` traces visible every cycle come from the **cheap**
pass. They look like a healthy full sweep. They are — of the wrong pass.

Instrumentation shipped in `ef9b5017` turned this from a silent OOM into a named
one: `build_intelligence_overview` is now an explicit loop emitting
`OVERVIEW_SPORT_BEGIN` / `OVERVIEW_SPORT_END` plus a container-memory sample per
sport. Production showed three hydrated-MLB starts and **zero log lines after any
of them**. Keep that instrumentation; it is how you will confirm a fix.

Note it uses `print(..., flush=True)`, not `logger.info` — see #37. Logging via
`logger.info` is a large part of why this was invisible for 17 hours.

---

## Falsified: it is not soccer

Soccer was the leading hypothesis and it is wrong, though reasonably so:
soccer joined the worker's sport list on 2026-07-25 (#47) and the OOMs began the
next midnight.

- **MLB is first in the sport list.** On the fatal pass the process dies inside
  MLB, so soccer never executes.
- Soccer *is* the most expensive sport on the **cheap** pass — alone it adds
  ~125 MB (193 → 318 MB) where the other seven add ~2 MB combined. Real, worth
  knowing, not the cause of this OOM.

---

## LOCATED 2026-07-26 17:04 UTC: the OOM is inside `apply_game_board_contract`

This is the finding. Everything below it is the evidence trail that led here.

The stage samples from `73ac270e` caught it twice in production. Both runs:

```
cards_context_begin              802.4 MB          197.3 MB
cards_context_summary_loaded     802.6  (+0.2)     200.0  (+2.7)
cards_context_betting_games      804.1  (+1.5)     203.2  (+3.2)
cards_context_sim_games_loaded   810.6  (+6.5)     212.9  (+9.7)
cards_context_actual_games       819.4  (+8.8)     221.5  (+8.6)   15 games, is_today
cards_context_games_built        819.7  (+0.2)     222.0  (+0.5)
cards_context_result_assembled   823.7  (+4.0)     243.5  (+21.5)
cards_context_board_contract_applied   ← NEVER PRINTS. Process is gone.
```

Render events confirm the cause both times:
`server_failed {"evicted": false, "oomKilled": {"memoryLimit": "4Gi"}}` at
17:04:36 and 17:05:06 — 17 s and 42 s after `result_assembled`, matching the
original "dies ~55 s later" observation.

The only statement between those two samples is
[cards.py:4936](../../syndicate/features/mlb/cards.py):

```python
if not _render_web_dyno():
    result = apply_game_board_contract(result, sport="mlb", module="cards")
```

**Note the branch.** `apply_game_board_contract` runs only when *not* a web
dyno, and inside it
[game_board_contract.py:582-590](../../syndicate/features/shared/game_board_contract.py)
gates `simulation_contract` on `not _render_web_dyno()` as well. The web service
takes `_attach_cards_board_contract` instead. **That is why `/mlb/api/cards`
serves a healthy 2.3 MB from web while the worker dies building the same
board** — they are not running the same code. Any future measurement taken from
the web API is measuring the wrong branch.

Two candidates remain inside that call: `_normalize_games` and
`build_simulation_contract_from_context`. `dde838ab` adds three
`board_contract_*` samples to split them. `simulation_contract` is the suspect —
it is the worker-gated one, and it was 99.8% of the payload's deep size in local
profiling while being entirely absent from the production web response.

### Narrowed further by elimination: it needs the odds history

Production artifacts for today were pulled with the ops export endpoint
(`GET /api/ops/artifacts/export?pattern=*mlb_source*<date>*`, admin token
required) into a scratch root, and `build_cards_page_context` was run against
them **on the worker branch** (`SYNDICATE_WEB_DYNO=false`), 15 games:

| | |
|---|---|
| whole-call allocation peak | **79 MB** |
| payload deep size | 4.92 MB |
| `simulation_contract` | 4.92 MB (`games` 3.80, `context` 2.43 — shares structure) |
| per-game mean inside the contract | 0.253 MB |
| **`market_features` per game** | **0.003 MB** |

79 MB with *real production inputs* is still ~47× short. The tell is
`market_features` at 3 KB: it is empty because the one input the export
endpoint cannot supply is missing. `HOT_ARTIFACT_PATTERNS` covers only
`*_source/...` paths, so **`data/odds_events/*.jsonl` and
`reports/odds_control_plane/odds_history/` are not exportable** — and those are
exactly what `build_market_features` reads.

### FIX SHIPPED `5d2dd951`: one odds-history cache shared across the board's games

`_normalize_game_context` called `build_market_features` with `cache=None`,
while `build_simulation_engine_context_from_candidate` — three functions below
it in the same file — already threaded one. That asymmetry was the bug.

Each call loads the odds-history shard for the game's date **plus a lookback
shard** (`SYNDICATE_ODDS_HISTORY_SHARD_LOOKBACK`, default 1 → 2 files per game),
and unlike the odds_events path **these files have no row cap**. Measured
against production artifacts with 8 MB shards:

| | reads | payload |
|---|---|---|
| before | **30** full JSON parses | 4.923 MB |
| after | **2** | 4.923 MB |

Byte-identical output, 15× fewer parses of the same two files.

**Why this was so hard to see, and the methodology lesson:** `tracemalloc` peak
does not move at all (80.7 → 81.2 MB), because each parse is freed before the
next one starts. The comment on `_JSONL_ROWS_CACHE` in the same file already
documents exactly this: *"CPython's allocator doesn't reliably return that churn
to the OS, so RSS ratchets upward across a single pass even though each
individual call's retained memory is bounded."* Production measures cgroup
`memory.current`, which is RSS-like. **Every local measurement in this incident
used `tracemalloc`, which is structurally blind to the failure mode** — that,
not thin local data, is the larger part of why local kept reporting ~80 MB
against production's 3.7 GB. Measure RSS when chasing this.

**Not yet proven to fix the OOM.** It provably removes the duplicate work;
whether that work was the whole 3.7 GB is what the deployed `board_contract_*`
and `sim_contract_*` samples will say. Keep them until a clean run is observed.

### Falsified along the way: caching the recent-market-history index

`build_recent_market_history_index` runs once per game, copies every event under
up to nine aliases and sorts each bucket — it looked like the same bug. Caching
it measured **flat** and cost ~7 MB retained, because `_MAX_JSONL_ROWS_PER_FILE`
already caps that path at 2000 rows/day (~14k events for the 7-day lookback).
Reverted; the reasoning is left in a comment at `_recent_history_rows` so it is
not retried.

### The earlier suspicion (superseded by the above)

`build_simulation_contract_from_context` normalizes each game in a loop
([simulation_adapter.py:382](../../syndicate/features/shared/simulation_adapter.py)),
and `_normalize_game_context` calls `build_market_features` with **no
`payload_cache`** — unlike its sibling
`build_simulation_engine_context_from_candidate`, which threads one. So per
game:

`build_market_features` → `build_market_history_view` → `_recent_history_rows`
→ `load_recent_odds_events(days_back=7)` → `build_recent_market_history_index`

`load_recent_odds_events`'s raw rows *are* cached (`_JSONL_ROWS_CACHE`, mtime
keyed). **`build_recent_market_history_index` is not.** It runs per game, and
per event it does `payload = dict(event)` and appends that copy under **every
alias** — up to nine — then sorts every bucket
([odds_lifecycle.py:253-267](../../syndicate/features/shared/odds_lifecycle.py)).
Fifteen games means fifteen full indexes over seven days of odds events.

This fits every symptom: worker-only (web skips `simulation_contract`),
data-dependent and invisible locally (the local mirror has two `odds_events`
files), grows through the day as events accumulate, and started at 00:02 UTC
when a new day's file began filling.

**It is still a hypothesis.** `72cbf81b` samples memory per game inside that
loop: monotonic climb confirms it, flat says the cost is in `_normalize_games`
instead and the suspect is wrong. Do not fix before reading that.

### The loaders are exonerated

The whole chain from entry to `result_assembled` cost **21 MB** on one run and
**46 MB** on the other. `_daily_actual_by_game` — the loader local profiling
blamed for 78% of the cost — contributed **8.8 MB and 8.6 MB**.

So the local stage table below is *wrong about production*, and instructively
so: it was taken against 2026-06-14, a completed slate whose feed/live payloads
carry full play-by-play. Production was mid-afternoon with games in progress and
much smaller feeds. **Local reproduced the wrong shape of the same function.**
That is the fourth wrong guess this incident has produced, and the first one
caught before anything was built on it.

---

## Measured 2026-07-26: the payload is ~2 MB. The deepcopy is not the cause.

The measurement below was the open question. It has been taken, against
production, and it falsifies the deepcopy hypothesis.

`GET https://syndicate-an21.onrender.com/mlb/api/cards` (15 games, today):

| | |
|---|---|
| wire bytes | 1.07 MB |
| parsed deep size | **2.33 MB** |
| `games` | 1.152 MB — **49.4%** |
| `cards` | same 1.152 MB — it aliases the same list, not a second copy |
| everything else | ~0.04 MB |

So the answer to "games versus everything else" is ~50/50 — and it does not
matter, because the whole payload is 2.3 MB. A cold call makes three of them
(`_cards_context_cache_put(deepcopy(...))`, `_today_cache_put(result)`,
`return deepcopy(result)`, [cards.py:4910-4913](../../syndicate/features/mlb/cards.py))
for **~7 MB**. The process dies at 4096 MB. The copies are ~0.2% of the budget.

**The three "traps" in the section below are therefore traps around a 7 MB
problem. Do not spend a session on them.** The `deepcopy` is still wasteful and
`_MLBDataProvider.games()`'s mutation-after-copy is still a real hazard, but
neither is this incident.

### Where the memory actually goes: construction, not the payload

Local profiling of `build_cards_page_context` (2026-06-14, 15 games — a date
whose mirror has the full artifact set including `feed_live` and sims):

| stage | live size | |
|---|---|---|
| `actual_games` — `_daily_actual_by_game`, full StatsAPI feed/live per game | **38.2 MB** | **78%** |
| `sim_games` — `_daily_sim_by_game` | 6.7 MB | |
| `summary` — daily_summary json | 3.7 MB | |
| everything else | ~0.4 MB | |
| sum held live | 49.1 MB | |
| **whole-call allocation peak** | **91.5 MB** | |
| returned payload | 2.0 MB | |

`_daily_actual_by_game` ([cards.py:1985](../../syndicate/features/mlb/cards.py))
is the dominant loader and the least justified: it holds 15 complete feed/live
payloads (~3.2 MB each) live for the whole call so that consumers can read
status, linescore, probable pitchers and boxscore slices off them. Worse, when
`selected_date == today_iso` — always true on the worker — it *fetches a fresh
feed/live over the network per game* (`_fetch_current_feed_live`,
[cards.py:1991-1996](../../syndicate/features/mlb/cards.py)). That is a network
call on a path the architecture says should be an artifact read.

**Local is not the source of truth and this gap is not yet closed:** 91.5 MB
locally versus 3.7 GB in production is ~40×. Local cannot reproduce the blowup,
so the loader table above identifies the *shape* of the cost, not its magnitude.
Do not act on the 40× by guessing — three guesses have already been wrong. The
next step is stage-level `CONTAINER_MEMORY` samples *inside*
`build_cards_page_context` on the worker, in the same style as the
`OVERVIEW_SPORT_BEGIN`/`END` instrumentation from `ef9b5017`, so the 40× is
attributed rather than theorised.

---

## Constraints on the fix — each obvious approach has a trap

**Superseded by the measurement above — kept because the mutation hazard in the
first bullet is real regardless.**

- **Removing the `deepcopy`** breaks callers: `_MLBDataProvider.games()` mutates
  the returned games three lines later
  (`game["game_market_recommendations"] = rows`,
  [home.py:4161-4165](../../syndicate/blueprints/home.py)). Without the copy
  those writes land in the shared cache.
- **Copying only `games`** needs `page_cache_key`, which is computed locally
  inside `build_cards_page_context`. Requires refactoring that function.
- **Artifact-backed `games()`** is the right destination — `_games_from_daily_summary`
  ([cards.py:4630](../../syndicate/features/mlb/cards.py)) already builds games
  from `summary["outputs"]` — but it needs `betting_games` / `sim_games` /
  `actual_games` / `first1_signals_by_game`, all currently assembled inside the
  page-context function.

~~Take this measurement first~~ — taken, see above. Composition was 49% `games`
of a 2.3 MB payload; the question turned out not to discriminate between fixes
because every candidate was addressing megabytes. Three earlier guesses at
composition were also wrong (a cProfile figure inflated ~15×, a
`SYNDICATE_DATA_ROOT` change that made things worse, a `parsed_request`
promotion that cost a net test) — that pattern is why the remaining 40× gap
gets instrumented rather than reasoned about.

---

## Mitigation available, not taken

`SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP=false` on refresh-worker,
**plus a restart** — an env change alone stays inert until the service restarts.
This is the documented #57 response. Reversible. Cost: the board then recomputes
only on web's request path, which is slower and adds to #56's health-check
pressure.

It was offered and the decision was to go straight at the root cause instead.
The loop was still running when this was written.

**Applied 2026-07-26 16:42 UTC. It helps a lot. It does NOT stop the OOM.**
Deploy `dep-d9j3g7b7uimc73ceb8o0` (commit `73ac270e`) brought the worker up
printing `INTELLIGENCE_LOOP_DISABLED`, and the OOM cadence went from one every
1–3 minutes to **none for 22 minutes** — then two, at 17:04:36 and 17:05:06.

**So the intelligence-state loop is not the only caller of this path.** With the
loop provably disabled, something else on refresh-worker still reaches
`build_cards_page_context` for today's date and still dies in it. Finding that
caller is open work; the `cards_context_begin` samples are the hook, since they
fire on every entry regardless of caller.

Between the OOMs the worker does real work — `tools/daily_update` ran to
completion (the first one to survive since the incident began), `MLB_SIM_TICK`
fires every 30 s, and memory sits at 650–720 MB (16–18% of 4096).

Getting there took two attempts, and the failed one is the reusable lesson:
**a Render *restart* does not re-inject env vars.** Setting the var and calling
`POST /v1/services/{id}/restart` returned 200 and did restart the process, which
came back still printing `INTELLIGENCE_LOOP_ENABLED` and still OOM-looping
(`BOOTED` 16:18:42, 16:19:38, 16:21:00, 16:23:04, 16:26:26). An env change also
does not create a deploy on its own here. Only `POST /v1/services/{id}/deploys`
applies one. Use the **single-key** endpoint
(`PUT /v1/services/{id}/env-vars/{KEY}`) to change one var — the full-list PUT
replaces every var and would drop the deliberate overrides in `todo.md`.

**What this costs, and what it does not fix.** The board now recomputes only on
web's request path, which is slower and adds to #56's health-check pressure. The
root cause is untouched: re-enabling this loop without fixing
`build_cards_page_context` will reproduce the OOM exactly.

---

## Useful operational notes

- Render auto-deploy is **OFF**. Pushing to `main` ships nothing; trigger per
  service via the API.
- **Do not run a blueprint sync** to deploy — it re-applies `render.yaml` and can
  undo the deliberate env overrides listed in `todo.md`'s Operational notes.
- Service IDs: web `srv-d88ahvrbc2fs73eodu30`, refresh-worker
  `srv-d91dpertqb8s73co8ls0`, live-odds-worker `srv-d91dpertqb8s73co8lt0`.
  Render owner `tea-d2bb5n95pdvs73cje4fg`. `RENDER_API_KEY` is in `.env`.
- Deploys normally kill an in-flight MLB sim — moot while the worker dies every
  few minutes.
- The Render logs API silently returns nothing for some `startTime`/`endTime`
  windows. Fetching recent logs unfiltered and sorting client-side worked.

---

## Related open items

- **#74** — router-inferred mode overwrites parsed intent. Unrelated to the OOM.
- **#72** — `record_prediction` writes a growing multi-MB file on the request
  path. Same architectural smell (memory/IO where an artifact belongs), and the
  user believes that ledger is obsolete.
- **#66 / #68** — re-validate once the worker is healthy; their evidence is
  contaminated by this outage.
- **#42** — `source_cards_api_payload`'s cache can never hit. Same file, same
  neighbourhood, likely related.
