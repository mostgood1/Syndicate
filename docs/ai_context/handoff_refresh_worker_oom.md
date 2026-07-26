# Handoff — refresh-worker OOM (open incident)

Written 2026-07-26. **The incident is still live at the time of writing.**
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

**Update 2026-07-26 ~16:30 UTC — the env var is now set to `false` on
refresh-worker, but it is NOT in effect.** A Render *restart*
(`POST /v1/services/{id}/restart`) does not re-inject env vars: the worker came
back up still printing `INTELLIGENCE_LOOP_ENABLED` and is still OOM-restarting
(`BOOTED` at 16:18:42, 16:19:38, 16:21:00, 16:23:04, 16:26:26). Applying it
needs a **deploy** (`POST /v1/services/{id}/deploys`), which is the outstanding
step. Worth remembering generally: on this account, env changes do not create a
deploy on their own and a restart will not pick them up.

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
