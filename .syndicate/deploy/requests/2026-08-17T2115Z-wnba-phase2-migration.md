# DEPLOY REQUEST — Phase 2 WNBA autorun: enable the flag + deploy

**service:** live-odds-worker (`srv-d91dpertqb8s73co8lt0`) only
**sha:** `e65a5531` (autorun) + `c7494c6c` (its tests) — both on `main`
**lane:** wnba-phase2-migration
**urgency:** normal. Nothing is degraded by waiting; the code is inert until the flag is set.

## reason

Nothing on any cadence calls `refresh_wnba_oddsapi_props.main()`. Measured 2026-08-17: `MAIN_ENTRY` **0 hits over 8h on both workers**, `GAME_CARDS_CENSUS` **0 over ~2 days**, with the emitter confirmed present in both deployed SHAs. Phase 1 moved NFL/NCAAF/NCAAB to refresh-worker's weekly autorun; **WNBA was never re-homed.** The GHA cron cannot cover it — it reads `RUN_FULL_PIPELINE` from `github.event.inputs`, which is empty on the `schedule` trigger, so full regeneration is manual-dispatch only.

Consequence: the WNBA `game_cards` coverage fix (82/113 fixtures = 72.6%, shipped and verified by content) **cannot be measured at all** until something calls the builder.

## what to do — TWO STEPS, and please STAGE THEM

**Step 1 — deploy the code with the flag still OFF.** It is inert: `_launch_autorun_wnba_pregame_refresh` returns immediately unless `SYNDICATE_ENABLE_WNBA_PREGAME_REFRESH_AUTORUN` is truthy. Confirm the service is healthy and its memory baseline is unchanged.

**Step 2 — only then set the flag**, ideally in a window you can watch:
```
PUT /v1/services/srv-d91dpertqb8s73co8lt0/env-vars/SYNDICATE_ENABLE_WNBA_PREGAME_REFRESH_AUTORUN
{"value":"1"}
```
**Use the single-key endpoint, NOT `render.yaml`.** A `blueprint_sync` rewrites the whole env block on live services and 502'd every route for ~2 minutes on 2026-08-08. The trade-off is deliberate: this leaves `render.yaml` drifted from live env, and that reconciliation is yours to schedule.

**Env restart caveat:** a restart does not re-inject env vars — set the key, then deploy.

## the risk, stated plainly

**This starts a new periodic job on a 2GB service with documented OOM history.** `render.yaml` records sim workers cut to 1 and the WNBA sim count cut 500 → 250 → 100 all fighting for that memory; `#241` caused a production restart loop. The WNBA refresh leg measures ~1.3–1.5GB RSS.

**`phase="pregame"` is what makes this safe** — it covers schedule/odds/props/picks and **excludes the sim leg**, exactly as soccer's autorun does. It is pinned by test with that reasoning attached. A full-phase autorun here would OOM the service.

Interval defaults to 14400s (4h), matching soccer. Overridable via `SYNDICATE_WNBA_PREGAME_REFRESH_INTERVAL_SECONDS`.

## verify — in this order, and the first is a precondition of the second

1. **`MAIN_ENTRY` appears on live-odds-worker.** Currently a hard zero over 8h, so one line is proof the entrypoint finally runs. **Allow up to one full interval (4h).**
2. **Then `GAME_CARDS_CENSUS` with `scheduled=N covered=N`.** The census cannot appear until step 1 does — do not read its absence as failure before `MAIN_ENTRY` shows.
3. **Watch `ALL_PROCESS_MEMORY` / `MEMORY_WATCHDOG` across the first launch.** This is the reading that says whether pregame-scoping held.

**Do not bank the coverage fix on the census alone** — `fixture_id` present with `covered < scheduled` means the id shipped and the coverage fix did not.

## rollback

Set the flag to `0` — the autorun goes inert immediately, no deploy needed. That is the fastest kill switch and it is why the flag exists. To also remove the code, redeploy the service's prior live SHA.

## note on provenance

I attempted step 2 myself and the permission classifier denied the Render API write. I did not route around it. Recording that so the request is not read as something I could have finished and chose not to.
