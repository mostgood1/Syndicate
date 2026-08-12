# Post-egress-fix cleanup: reliability and capacity on the Syndicate workers

Measured 2026-08-12, ~21:30 UTC (16:30 America/Chicago). All production numbers
come from the Render API (`/services/*/env-vars`, `/metrics/*`, `/services/*/events`,
`/services/*/deploys`, `/logs`) and from `GET /api/ops/artifacts/export?names_only=1`
against the live web service. Code citations are `file:line` against `f6c0525f`.

Where I could not measure something directly I say so and mark the reasoning as
**INFERENCE**.

---

## Summary

1. **Nothing is still egressing on the publish path.** Both workers are live on
   `http://syndicate-an21:10000` and production logs show `PUBLISH_OK ... url=http://syndicate-an21:10000/...`.
   **But `render.yaml:400` and `:740` still say `https://syndicate-an21.onrender.com`,
   and `blueprint_sync` fired 11 times in the last 14 days — the next `render.yaml`
   push silently reverts the fix on both workers.** This is the one urgent item.
2. **Disk-full date (live-odds-worker): 2026-10-05** on a 14-day linear fit
   (11.14 → 19.24 GB, 593 MB/day). On the accelerating last-7-day rate
   (780 MB/day) it is **~2026-09-20**. Nothing in the repo deletes an artifact;
   the oldest file on the web disk dates to the day the disk was created.
3. **Top memory suspect is not on live-odds-worker and is not the #394 checksum
   map** (that map is ~1.4 MB). The service actually dying is **refresh-worker**:
   125 OOM kills at 4 GiB in 14 days, and CPU at 100% of its 2-core limit in
   **72.4%** of 5-minute buckets. live-odds-worker peaks at 0.74 cores and never
   exceeds 80%.
4. **Ship first: (PR-1)** point `render.yaml`'s two `SYNDICATE_WEB_PUBLISH_URL`
   values at the internal host; **(PR-2)** add a retention policy for
   `book_quotes` / `odds_history`, which are 2.6 GB of the web disk on their own
   and the entire disk-growth curve.
5. **The #395 ceiling is not firing and has already been raised 10× by hand.**
   0 `PUBLISH_BUDGET_EXCEEDED` in 2–3 days; `SYNDICATE_PUBLISH_HOURLY_BYTE_BUDGET
   = 20 GiB` is set live on both workers, absent from `render.yaml`, and took
   effect only at the 21:19Z deploy today. Against ~101 MB/hr of real traffic
   that is ~200× headroom, so it is effectively already inert — see Task 2 for
   the failure mode, which is worse than "drop".

**PR-1 is committed as `9abd4eb0` and deliberately not pushed** — pushing
`render.yaml` deploys, and `check_deploy_safety.py` is red (odds refresh in
flight, live games). Post-edit enumeration shows the sync would now be an env
no-op on all three services.

---

## Task 1 — Is the fix complete?

### Live env state (read 2026-08-12 21:0x UTC)

| service | `SYNDICATE_WEB_PUBLISH_URL` (live) |
|---|---|
| `syndicate` (web) | *(not set — web does not publish to itself)* |
| `refresh-worker` | `http://syndicate-an21:10000` ✅ |
| `live-odds-worker` | `http://syndicate-an21:10000` ✅ |

**Both workers are fixed, not just live-odds-worker.** Confirmed end-to-end in
production logs rather than by env inspection alone:

```
2026-08-12T21:12:13  [artifact_publisher] PUBLISH_OK path=nfl_source/data/book_grid/book_grid_2026-08-11.json url=http://syndicate-an21:10000/api/ops/artifacts/publish   (refresh-worker)
2026-08-12T21:13:27  [artifact_publisher] PUBLISH_OK path=soccer_source/epl/api/live_state/live_state_2026-08-12.json url=http://syndicate-an21:10000/api/ops/artifacts/publish   (live-odds-worker)
```

### The gap: `render.yaml` still carries the public URL

- [render.yaml:399-400](render.yaml:399) — refresh-worker → `https://syndicate-an21.onrender.com`
- [render.yaml:739-740](render.yaml:739) — live-odds-worker → `https://syndicate-an21.onrender.com`

Per `CLAUDE.md`'s `#284` rule, a `render.yaml` push triggers `blueprint_sync`,
which **rewrites the whole env block** on the affected services. Measured over the
same 14 days:

| service | deploys | of which `blueprint_sync` |
|---|---|---|
| live-odds-worker | 166 | 4 |
| refresh-worker | 349 | 6 |
| web | 349 | 1 |

11 blueprint syncs in a fortnight is not a theoretical trigger. **The live fix is
one `render.yaml` commit away from being undone**, and because the sync writes the
whole block it would happen with no diff naming the URL.

### Other self-referential URL construction

| location | what it is | risk |
|---|---|---|
| [render.yaml:400](render.yaml:400), [:740](render.yaml:740) | worker publish base | **live regression risk — fix this** |
| [scripts/audit_layer1_completeness.py:33](scripts/audit_layer1_completeness.py:33), [scripts/audit_slate_coverage.py:40](scripts/audit_slate_coverage.py:40), [scripts/check_deploy_safety.py:34](scripts/check_deploy_safety.py:34), [scripts/regrade_mlb_game_markets.py:130](scripts/regrade_mlb_game_markets.py:130) | dev/ops tooling defaults | none — run from laptops, not on Render |
| [.github/workflows/daily-update.yml:214](.github/workflows/daily-update.yml:214) | GHA backup puller | correct as-is — GHA is genuinely outside the Render network |
| [tests/test_artifact_publisher.py](tests/test_artifact_publisher.py) (~20 occurrences) | fixtures | none |
| [vendor/mlb_bettingv2/tools/daily_update.py:1381](vendor/mlb_bettingv2/tools/daily_update.py:1381) and 2 siblings | `f"https://{service_name}.onrender.com"` | vestigial vendored code; not on either worker's entrypoint path |

### Outbound calls each worker makes

Render bills **egress** (bytes leaving the network). For an outbound `GET` to a
third-party API the request is a few hundred bytes and the *response* is ingress,
so the data-fetch calls below are near-free even though they are external. The
1.62 TB came from `POST` bodies, which is why the publish path was the whole bill.

| destination | caller | classification |
|---|---|---|
| `http://syndicate-an21:10000` | [artifact_publisher.py:566](syndicate/features/shared/artifact_publisher.py:566) publish/export/stream | **internal — unbilled** ✅ |
| `redis://red-d88bvljbc2fs73epfhhg:6379` | `refresh_state_store` keyvalue backend | **internal — unbilled** ✅ |
| `api.the-odds-api.com` | `scripts/fetch_*_oddsapi_local.py`, `backfill_mlb_historical_odds.py` | external, **ingress-dominant** (billed egress ≈ request headers) |
| `statsapi.mlb.com` | `emit_settlement_inputs.py`, `fetch_mlb_weather.py` | external, ingress-dominant |
| `site.api.espn.com` / `site.web.api.espn.com` | live status, NBA/WNBA cards, basketball props | external, ingress-dominant |
| `api-web.nhle.com`, `api.nhle.com`, `assets.nhle.com` | NHL ingestion | external, ingress-dominant |
| `api.collegefootballdata.com` | NCAAF snapshots | external, ingress-dominant |
| `cdn.nba.com`, `data.nba.com`, `www.nba.com` | vendored NBA repo | external, ingress-dominant |
| `raw.githubusercontent.com`, `github.com` | nflverse / FTN / schedule ingestion | external, ingress-dominant |
| `www.bovada.lv` | vendored NHL/NBA odds | external, ingress-dominant |

**Nothing large is still leaving the Render network.** The only remaining
outbound *bulk* transfer is GHA's `/api/ops/artifacts/export` pull in
`daily-update.yml`, which is correct by design (git backup) and runs once daily.

---

## Task 2 — The #395 hourly ceiling

### What it actually does when hit

Not "block, queue, drop, or crash" — it is a **drop, and on the sweep path a
self-amplifying stall**.

1. [artifact_publisher.py:533](syndicate/features/shared/artifact_publisher.py:533)
   `_publish_budget_blocks()` returns `True` before the upload.
2. `publish_hot_artifact()` returns `False` ([:859](syndicate/features/shared/artifact_publisher.py:859)
   for JSON, [:725](syndicate/features/shared/artifact_publisher.py:725) for streamed).
3. In `sweep_changed_hot_artifacts` the file lands in `failed`
   ([:1022](syndicate/features/shared/artifact_publisher.py:1022)), so
   `all_succeeded` is `False`.
4. In [live_refresh_loop.py:4572-4585](syndicate/features/shared/live_refresh_loop.py:4572)
   the publish watermark is **not advanced**.

So a sustained block means the next sweep re-sweeps a *wider* mtime window,
finds more candidates, and blocks again — each cycle strictly heavier than the
last. That is the same self-amplifying shape the pull side already has a hard
clamp for (`_MAX_PULL_WINDOW_SECONDS`, [:604](syndicate/features/shared/artifact_publisher.py:604));
the publish side has no equivalent.

Worse, `publish_hot_artifact`'s **direct** callers have no retry at all — a
budget block there is a **silent permanent drop**:

- [scripts/refresh_mlb_oddsapi.py:262,264](scripts/refresh_mlb_oddsapi.py:262)
- [scripts/emit_settlement_inputs.py:321](scripts/emit_settlement_inputs.py:321)
- [scripts/fetch_mlb_oddsapi_local.py:759](scripts/fetch_mlb_oddsapi_local.py:759)
- [scripts/run_refresh_worker.py:3022](scripts/run_refresh_worker.py:3022)
- [pipeline/intelligence_state.py:2878](pipeline/intelligence_state.py:2878)

On live odds that is a correctness risk, exactly as the brief says.

### Is it firing today?

**No.** Over the last 2–3 days:

| service | `PUBLISH_BUDGET_EXCEEDED` |
|---|---|
| live-odds-worker | 0 (2-day window) |
| refresh-worker | 0 (3-day window) |

Observed utilisation, from the breaker's own telemetry:

```
2026-08-12T20:37:56  PUBLISH_BUDGET uploads=175 used_mb=101.0 ceiling_mb=2048.0    (live-odds-worker)
2026-08-12T20:43:23  PUBLISH_BUDGET uploads=75  used_mb=62.6  ceiling_mb=2048.0    (refresh-worker)
```

~101 MB in the rolling hour. #394's dedupe is doing the work
(`PUBLISH_SKIPPED_UNCHANGED` is abundant in the logs).

### It has already been raised 10× in production — and the raise only just took effect

Found while enumerating env for PR-1, **not** visible from the code or from
`render.yaml`:

```
SYNDICATE_PUBLISH_HOURLY_BYTE_BUDGET = 21474836480   (20 GiB)
```

is set live on **both workers** and is absent from `render.yaml` — undocumented
config drift, same class as the memory-trace flag in Task 4.

The two log lines above say `ceiling_mb=2048.0`, i.e. the code default, because
the processes emitting them had booted before the key was set. Both workers
redeployed at **2026-08-12T21:19Z**, and the processes that came up after it
report:

```
2026-08-12T21:20:54  PUBLISH_BUDGET uploads=25 used_mb=9.7  ceiling_mb=20480.0   (live-odds-worker)
```

So the effective ceiling went from 2 GB/hr to **20 GB/hr about twenty minutes
ago**. This is worth stating plainly for two reasons:

- Against ~101 MB/hr of real traffic that is **~200× headroom**. The #395 brake
  is already administratively inert; the correctness risk in the section above
  is now close to theoretical, which lowers this task's priority relative to
  Task 3.
- It is a live demonstration of the "env needs a deploy" rule: the key was set
  at some point, and the running workers kept enforcing the old value until an
  unrelated deploy re-injected the environment. Anyone who had checked
  `env-vars` and concluded "the ceiling is 20 GiB" would have been wrong for as
  long as that gap lasted. **Check the running process's own log line, not the
  env var.**

### Proposal

**Re-scope, don't remove.** Removing it discards the only byte-level measurement
of publish volume that exists — and per the code comment at
[:495](syndicate/features/shared/artifact_publisher.py:495), that measurement was
the missing term during the incident. Concretely:

1. **Make the ceiling destination-aware.** Add `_publish_url_is_internal()` —
   true when the host has no dot in it or resolves to an RFC1918 address. When
   internal, `_publish_budget_record()` still runs (keep the metric) but
   `_publish_budget_blocks()` returns `False` unconditionally. The brake then
   only ever applies to a genuinely external publish base, which is the exact
   configuration that caused the incident.
2. **Keep a much higher internal-only sanity ceiling** (say 32 GB/hr) purely to
   catch an infinite loop, since even free traffic costs CPU on both sides.
3. **Alert instead of throttle.** Emit a distinct `PUBLISH_BUDGET_WARN` line at
   50%/75%/90% of ceiling. Today the only signal is the refusal itself, which is
   the point at which it is already too late.
4. **If it stays as-is**, the watermark interaction in step 4 above must be
   fixed regardless: a budget refusal should be recorded as `skipped`, not
   `failed`, so it cannot widen the next sweep window.

*One PR. Does not touch #394.*

---

## Task 3 — Disk growth and retention

### Measured growth (Render metrics, 14 days, 6h buckets)

| disk | start | now | rate | % of 50 GB | linear full-date |
|---|---|---|---|---|---|
| live-odds-worker | 11.14 GB | **19.24 GB** | 593 MB/day | 38.5% | **2026-10-05** |
| refresh-worker | 8.36 GB | 14.41 GB | 442 MB/day | 28.8% | 2026-11-03 |
| web | 8.91 GB | 12.60 GB | 270 MB/day | 25.2% | 2027-01-01 |

The brief's "~700 MB/day, four weeks" is close but slightly pessimistic on the
date and slightly optimistic on the shape: growth is **accelerating**, not linear.
First half of the window ran ~390 MB/day; last 7 days ran ~780 MB/day. On the
recent rate live-odds-worker fills around **2026-09-20**. **INFERENCE:** the
acceleration tracks the MLB season's slate size plus the two duplicated
`odds_history` trees below; I have not isolated which dominates.

### Inventory (web disk, hot-allowlisted set, `names_only=1`)

- **File count: 6,968**
- **Total size: 5.83 GB** (of web's 12.60 GB total — the rest is non-allowlisted bulk)
- **Oldest file: 2026-05-28 02:31** (`wnba_source/data/processed/recon_props_2026-05-25.csv`)

The web disk was created **2026-05-27**. The oldest file is one day younger than
the disk. **Nothing has ever been deleted.**

Age distribution:

| age | files | bytes |
|---|---|---|
| <1d | 373 | 708 MB |
| 1–7d | 816 | 1,953 MB |
| 7–30d | 3,658 | 2,266 MB |
| 30–90d | 2,121 | 904 MB |
| >90d | 0 | 0 MB |

Top directories:

| bytes | files | directory |
|---|---|---|
| 1,303 MB | 14 | `mlb_source/tracking/book_quotes` |
| 859 MB | 73 | `mlb_source/source_artifacts/data/daily/ladders` |
| 655 MB | 16 | `mlb_source/artifacts/mlb/odds_history` |
| 655 MB | 16 | `mlb_source/tracking/odds_history` |
| 336 MB | 25 | `mlb_source/data/daily/ladders` |
| 272 MB | 387 | `mlb_source/source_artifacts/data/daily` |
| 268 MB | 17 | `reports/intelligence` |

I could not inventory the **workers'** disks directly — neither worker runs an
HTTP server, and `/api/ops/*` reads only the web service's own disk. Worker disk
*totals* above are from Render metrics. **INFERENCE:** the worker composition is
similar-or-worse, since the workers are the *producers* of `book_quotes` and
`odds_history` and additionally hold the non-allowlisted bulk that never crosses
to web.

Two findings worth separating out:

- **`odds_history` is stored twice, byte-identical.** `mlb_source/artifacts/mlb/odds_history/2026-08-07.json`
  and `mlb_source/tracking/odds_history/2026-08-07.json` are both 56.09 MB with
  the same mtime, for all 16 dates. That is **655 MB of pure duplication** on
  each of three disks, and both copies are in `HOT_ARTIFACT_PATTERNS`
  ([artifact_publisher.py](syndicate/features/shared/artifact_publisher.py) —
  `*_source/tracking/odds_history/*.json` and `*_source/artifacts/*/odds_history/*.json`).
- **`book_quotes` is the growth curve.** One file per day, 87–314 MB each,
  14 files retained, 1.3 GB total. At ~200 MB/day average this single family is
  roughly a third of live-odds-worker's daily growth.

### Does the publish loop glob the disk? — Yes

[artifact_publisher.py:1005-1006](syndicate/features/shared/artifact_publisher.py:1005):

```python
for pattern in HOT_ARTIFACT_PATTERNS:
    for candidate in root.glob(pattern):
```

**97 glob patterns**, none containing `**`, evaluated against the disk on
**every tick** — 60s when any game is live. It is not a work list of live events.
Every matched file is `stat()`ed ([:1008](syndicate/features/shared/artifact_publisher.py:1008))
and date/size-checked ([:977](syndicate/features/shared/artifact_publisher.py:977))
before the mtime filter rejects it. On the web disk that is 6,968 files per pass;
on 2026-05-28 it would have been near zero. **Work grows with disk size exactly as
the brief predicted.**

The same 97-pattern glob also runs on the *receiving* side in
[ops.py:1230-1231](syndicate/blueprints/ops.py:1230) and
[:1272-1275](syndicate/blueprints/ops.py:1272).

Corroborating measurement already in the repo: `docs/ai_context/todo.md:9310`
records `publish_changed_hot_artifacts` at **48–74s per cycle** for 73–103
artifacts. Against a 60s live tick that is an entire tick spent sweeping.

**Caveat on attributing CPU to this:** it is real work that scales with the disk,
but on live-odds-worker it is *not* currently saturating anything — see Task 4.
The service where CPU is pegged is refresh-worker.

### Proposed retention policy

Nothing anywhere deletes an artifact. A grep for `unlink|rmtree|os.remove|prune|purge`
across `syndicate/` returns only a bootstrap lock-file removal
([app.py:111](syndicate/app.py:111), [:125](syndicate/app.py:125)) and unrelated
in-memory cache pruners.

Proposed, as its own PR — a `scripts/prune_artifacts.py` invoked once per day
from each worker's loop, **age-based with a per-family override**, defaulting to
dry-run and gated behind `SYNDICATE_ARTIFACT_RETENTION_ENABLED`:

| family | default retention | rationale |
|---|---|---|
| `*_source/tracking/book_quotes/*.jsonl` | **7 days** | pivoted into `book_grid_*.json` the same day; the pivot output is what web reads |
| `*_source/tracking/odds_history/*.json` | **14 days** | CLV needs a window, not a season |
| `*_source/artifacts/*/odds_history/*.json` | **delete outright** | byte-identical duplicate of the above |
| `*/daily/ladders/daily_ladders_*.json` | **30 days** | serving artifact; older dates are archive |
| `reports/intelligence/intelligence_state_*.json` | **14 days** | dated snapshots; `intelligence_state.json` is the live one |
| `settlement_inputs/*` | **settled + 30 days** ✅ *decided* | evidence — age alone is the wrong axis |
| everything else allowlisted | **90 days** | matches the observed distribution (0 files >90d today, so this is a no-op safety net) |

At those numbers the current web hot set drops from 5.83 GB to roughly
**2.1 GB**, and — more importantly — the sweep's per-tick candidate count drops
from 6,968 toward ~1,200, which bounds the CPU trend at its cause.

### Compression does not retire retention — measured

`#396`'s author suggested `#399` supersedes it. It does not, and the arithmetic
matters because "the disk is solved" is the wrong thing to believe. Applying
38.7x to the *whole* growth rate overstates it — `book_quotes` is only part of
the total.

Observed MB/day of new data, last 7 days, web hot set, under `#398`'s tiers:

| tier | MB/day |
|---|---|
| source (`book_quotes` 196.4 + `odds_history` 105.0) | 324.6 |
| derived | 30.6 |
| unmatched | 11.9 |
| eval | 9.6 |
| settlement | 3.5 |

Against whole-disk growth of 593 MB/day (14d) / 780 MB/day (last 7d):

| | 14d rate | 7d rate |
|---|---|---|
| today | 593 → **53 days** | 780 → **40 days** |
| after `#399` (`book_quotes` only — what was built) | 402 → **78 days** | 589 → **54 days** |
| if `odds_history` compressed too (**not built**) | 299 → **105 days** | 486 → **65 days** |

Compression buys ~25 days on the pessimistic rate and the disk still fills. It
is the largest single lever and it is not sufficient. The split is clean:
**compress what cannot be recreated, expire what can.**

**Settlement question — decided 2026-08-12: keep `settlement_inputs` for 30 days
after settlement, not 30 days after write.** The pruner must therefore join each
`settlement_inputs/finals_*.json` / `closing_lines_*.csv` against grading state
and treat **ungraded as "do not delete", never as "old enough"** — an unresolved
join must not fall through to the permissive branch. A file whose settlement
status cannot be determined is retained and counted in a `RETENTION_UNKNOWN`
log line, so a broken join shows up as growth plus a loud counter rather than as
silent evidence loss.

---

## Task 4 — Memory and the restart loop

### The restart loop is mostly not a loop

`server_failed` events, 14 days, broken down by reason:

| service | oomKilled | earlyExit (clean self-exit) | nonZeroExit | unhealthy | total |
|---|---|---|---|---|---|
| live-odds-worker | **33** | **25** | 11 | 0 | 69 |
| refresh-worker | **125** | 0 | 0 | 0 | 125 |
| web | 37 | 0 | 0 | 5 | 42 |

The 25 `earlyExit` events on live-odds-worker are **intentional**.
[run_live_odds_refresh_worker.py:246-265](scripts/run_live_odds_refresh_worker.py:246)
self-exits every 6 h ± 10% (`SYNDICATE_LIVE_ODDS_WORKER_MAX_UPTIME_SECONDS=21600`,
confirmed live) to reset accumulated page cache. Render restarts the process and
records it as a failure. **A quarter of live-odds-worker's "chronic instance
failures" are a designed feature being reported as a fault** — worth knowing
before anyone tunes against that number.

Total-instances drops to zero, 1h buckets: live-odds-worker 9, refresh-worker 7,
web 10 over 14 days.

### Where the memory pressure actually is

Fine-resolution (5-min buckets, last 2 days):

| service | CPU max | CPU p95 | buckets >80% of limit | Mem max | Mem p99 | limit |
|---|---|---|---|---|---|---|
| live-odds-worker | 0.74 | 0.62 | **0 / 553 (0.0%)** | 1,610 MB | 1,502 MB | 1 CPU / 2 GiB |
| refresh-worker | 2.00 | **2.00** | **357 / 493 (72.4%)** | 3,295 MB | 3,174 MB | 2 CPU / 4 GiB |

**This reassigns the brief's premise.** "CPU pegged near 100% during busy
windows" is refresh-worker, comprehensively — it is at its 2-core ceiling in
nearly three-quarters of all 5-minute buckets, and it took 125 OOM kills at 4 GiB
to live-odds-worker's 33 at 2 GiB. live-odds-worker never crossed 80% of one core.
Any capacity work aimed at live-odds-worker's CPU would be aimed at the wrong box.

### The prime suspects, assessed

**The #394 checksum map — not the problem.** `_LAST_PUBLISHED_CHECKSUM`
([:475](syndicate/features/shared/artifact_publisher.py:475)) is only ever read
at [:717](syndicate/features/shared/artifact_publisher.py:717)/[:843](syndicate/features/shared/artifact_publisher.py:843)
and written at [:746](syndicate/features/shared/artifact_publisher.py:746)/[:875](syndicate/features/shared/artifact_publisher.py:875).
**It never evicts.** But sized against reality: 6,968 paths × (~80 B path + 64 B
hex digest + dict overhead) ≈ **1.4 MB**. It is not a memory problem and I would
not spend a PR on it.

Its *comment* is wrong in a way worth correcting, though — it claims the map is
"bounded by the artifact set, which is bounded by the allowlist, so it does not
grow without limit". The allowlist is 97 globs with date wildcards, so the path
set grows with the disk, and the disk has no retention. The bound is Task 3's
retention policy, not the allowlist. **Fix the comment when Task 3 lands** so the
next reader doesn't re-derive this.

`_PUBLISH_BYTES` ([:510](syndicate/features/shared/artifact_publisher.py:510)) is
correctly self-pruning at [:528](syndicate/features/shared/artifact_publisher.py:528)
and holds ~200 tuples. Not a concern.

**The real find on live-odds-worker: production instrumentation left enabled.**
`SYNDICATE_LIVE_ODDS_REFRESH_MEMORY_TRACE = 1` is set **live** on live-odds-worker
and is **absent from `render.yaml`** — undocumented config drift. It enables
[`_largest_gc_object_summary()`](scripts/run_live_odds_refresh_worker.py:178),
which walks `gc.get_objects()` and calls `sys.getsizeof` on **every tracked object
on the heap**, and it runs ~4× per tick (`loop_tick_begin`, `tick_start`,
`tick_end`, `loop_sleep`).

Measured locally: 11 ms on a 31,630-object heap; `gc.get_objects()` alone builds a
list of strong references to every object (0.3 MB for that list at 31k objects).
**INFERENCE, and I want to be careful here:** cost is linear in object count, so a
worker holding a parsed 11 MB artifact mid-tick will be far above 31k objects and
proportionally slower — but I do not have the worker's live object count, and the
CPU metrics above show live-odds-worker is *not* saturated, so I cannot claim this
is causing the OOMs. What I can say plainly: it is a debug-only heap walk running
in production ~5,760 times a day on the service with a 2 GiB ceiling, it
transiently pins every object in the heap, and it buys nothing operationally. It
should be off.

### Bootstrap on start

`SYNDICATE_BOOTSTRAP_ON_START=1` is set live on all three services.
`_bootstrap_render_data()` ([app.py:65](syndicate/app.py:65)) is called **only from
`create_app()`** ([app.py:146](syndicate/app.py:146)), and neither worker
entrypoint reaches `create_app` — `run_live_odds_refresh_worker.py` and
`run_refresh_worker.py` import from `syndicate.features.shared.*` and the vendored
flask_frontend, never `syndicate.app`. **So the flag is inert on both workers**
and there is no boot-time full sweep from this path.

The genuine boot cost is elsewhere and already bounded: `pull_hot_artifacts` has a
hard 2-hour clamp ([:604](syndicate/features/shared/artifact_publisher.py:604))
precisely because "every deploy boots a worker with no watermark, so every deploy
pulled the entire artifact set". The publish side has **no equivalent clamp** —
`_hot_artifact_publish_since_epoch` ([live_refresh_loop.py:3990](syndicate/features/shared/live_refresh_loop.py:3990))
should be checked for the same treatment. That is the asymmetry worth a PR.

### Proposal

1. **Unset `SYNDICATE_LIVE_ODDS_REFRESH_MEMORY_TRACE` on live-odds-worker** (single-key
   env endpoint + deploy; it is not in `render.yaml` so no blueprint push needed).
   Cheapest change in this document.
2. **Clamp the publish watermark window** the way the pull side already is.
3. **Remove `SYNDICATE_BOOTSTRAP_ON_START` from the two workers**, or wire it up —
   right now it reads as protection that does nothing.
4. Bounded structures: not warranted for `_LAST_PUBLISHED_CHECKSUM` on the numbers.
   If you want one anyway, an `OrderedDict` capped at 20,000 entries with
   `move_to_end` on hit is ~4 lines and costs nothing — but Task 3's retention is
   the real bound.

---

## Task 5 — The 11.6 MB artifact

It is **`mlb_source/source_artifacts/data/daily/ladders/daily_ladders_<date>.json`**.
Today's is 11.17 MB; yesterday's 11.76 MB. (Files >12 MB are refused by
`_PUBLISH_MAX_BYTES` at [:956](syndicate/features/shared/artifact_publisher.py:956),
so this family sits right against the ceiling — `SWEEP_SKIPPED {'too_large': N}`
appears continuously in production logs.)

Built from the live production copy of `daily_ladders_2026_08_12.json`.

### Serialized bytes by key, sorted descending

```
stored file            11,711,232 B   11.17 MB
re-serialized compact   6,673,066 B    6.36 MB   -> 43.0% of the file is pretty-print whitespace
gzip(stored)              670,187 B    0.64 MB
gzip(compact)             540,127 B    0.52 MB   -> 21.7x smaller than what is stored today

level 1
  groups                   6.36 MB   100.0%
  generatedAt              ~0 MB
  date                     ~0 MB

level 2
  groups.hitter            5.74 MB    90.2%
  groups.pitcher           0.62 MB     9.8%

level 3 (groups.hitter, 10 prop types, largest first)
  hits_runs_rbis           0.73 MB      rows n=390 (0.59) | hitterOptions n=390 (0.13)
  total_bases              0.68 MB      rows n=390 (0.55) | hitterOptions n=390 (0.13)
  rbi                      0.61 MB      rows n=390 (0.47) | hitterOptions n=390 (0.13)
  hits                     0.58 MB      rows n=390 (0.44) | hitterOptions n=390 (0.13)
  runs                     0.56 MB      rows n=390 (0.43) | hitterOptions n=390 (0.13)
  doubles                  0.54 MB      ...
  home_runs                0.53 MB
  stolen_bases             0.51 MB
  triples                  0.51 MB
  hitter_strikeouts        0.49 MB

rows content (all 3,900 hitter rows, 2.82 MB)
  ladder                   1.15 MB    40.8%
  sourceFile               0.43 MB    15.2%
  headshotUrl              0.39 MB    14.0%
  teamLogoUrl              0.17 MB     6.1%
  opponentLogoUrl          0.17 MB     6.1%
  hitterName               0.06 MB     2.0%
  playerName               0.06 MB     2.0%
```

### Does the dominant key grow monotonically?

**No.** This is a per-date snapshot with no accumulated tick history — `ladder` is
a fixed-length probability table (`total` 0..8 with `exactCount`/`exactProb`/
`hitCount`/`hitProb`). Size scales with **slate width** (15 games × 26 hitters ×
10 props), not with time-of-day. The file is rewritten, not appended.

What it *is* is **denormalized repetition**, three distinct kinds:

1. **Identical option blocks duplicated per prop group — 1.27 MB, 20% of the
   compact payload.** `hitterOptions` is 133.5 KB and appears in all 10 hitter
   groups with **exactly one distinct variant**. Same for `teamOptions` (10×),
   `gameOptions` (10× hitter, 7× pitcher), `pitcherOptions` (7×).
2. **Derivable URLs stored per row — 0.73 MB, 26% of `rows`.** `headshotUrl`,
   `teamLogoUrl`, `opponentLogoUrl` are template strings built from
   `batterId` / `teamId` / `opponentTeamId`, all three of which are already in
   the same row. `teamLogoUrl` has **30 distinct values across 390 rows**.
3. **Exact duplicate fields.** `hitterId` == `batterId` (390/390 identical),
   `playerName` == `hitterName` (389/390). And `sourceFile` — a filesystem path —
   is 15.2% of `rows` at **15 distinct values across 390 rows**.

### Is gzip applied on publish?

**No.** Neither transport compresses. The streamed path sets
`Content-Type: application/octet-stream` with no `Content-Encoding`
([:733-739](syndicate/features/shared/artifact_publisher.py:733)); the JSON path
sets `Content-Type: application/json` and posts `json.dumps(...).encode()`
([:861-869](syndicate/features/shared/artifact_publisher.py:861)). A grep for
`gzip|zlib|Content-Encoding` across `artifact_publisher.py` and `ops.py` returns
nothing.

### Proposal (ordered by benefit/risk)

| change | saving | risk |
|---|---|---|
| **Write compact JSON** (`separators=(',',':')`, drop `indent`) at the producer | 11.17 → 6.36 MB (**−43%**) | very low; nothing parses these by eye |
| **Gzip the publish body** (`Content-Encoding: gzip` + decompress in [ops.py:1096](syndicate/blueprints/ops.py:1096)) | 6.36 → 0.52 MB on the wire (**−92%**) | low, but needs the receiver deployed first — reuse the `_PUBLISH_STREAM_UNSUPPORTED_STATUSES` fallback pattern already at [:666](syndicate/features/shared/artifact_publisher.py:666) |
| **Hoist the option blocks** to one `groups.hitter.options` / `groups.pitcher.options` | −1.27 MB (−20%) | medium — frontend contract change |
| **Drop derivable URL fields**, rebuild client-side from IDs | −0.73 MB (−11%) | medium — frontend contract change |
| **Drop `sourceFile`, `hitterId`, `playerName`** (duplicates/debug) | −0.51 MB (−8%) | low, once confirmed unread |

The first two are pure transport/serialization and require no contract change;
together they take the artifact from 11.17 MB on disk and on the wire to 6.36 MB
on disk and **0.52 MB on the wire**. I would do those two as one PR and treat the
schema changes as separate work behind a frontend check.

**Note:** compact JSON also moves this family from ~11.7 MB to ~6.4 MB, i.e. from
"right against the 12 MB `_PUBLISH_MAX_BYTES` ceiling" to comfortably under it —
which incidentally fixes the `too_large` skips currently appearing in the logs.

---

## Task 6 — Does the disk need to exist?

**Assessment: load-bearing on the workers, arguably vestigial on web — but
removing it is a large project, not a cleanup.**

### What forces it today

1. **`SYNDICATE_REQUIRE_HOSTED_STORAGE=true` on all three services.**
   `data_root()` ([refresh_state_store.py:419-425](syndicate/features/shared/refresh_state_store.py:419))
   and `reports_root()` ([:341-349](syndicate/features/shared/refresh_state_store.py:341))
   **raise** unless a filesystem path is configured. Every artifact read and write
   in the codebase goes through these. There is no object-storage backend behind
   this interface — it returns a `pathlib.Path`.
2. **The publish/pull architecture is filesystem-to-filesystem over HTTP.**
   `sweep_changed_hot_artifacts` globs a local tree; `/api/ops/artifacts/publish`
   writes to a local tree; `pull_hot_artifacts` writes to a local tree. Removing
   the disk means replacing all three, not repointing them.
3. **The workers hold bulk data that is deliberately *excluded* from the
   allowlist and never crosses to web** — `book_quotes` (up to 314 MB/day),
   `odds_history` (~50 MB/day), `eval/batches`, statcast features. This is real
   working data: refresh-worker pivots the 207 MB `book_quotes` shard into
   `book_grid_*.json` precisely because web cannot (one read is ~1.3 GB resident
   on a 2 GB container, per the comment at
   [artifact_publisher.py:50-54](syndicate/features/shared/artifact_publisher.py:50)).
   **The workers' disks are not staging. They are the working set.**

### Where the disk is closest to vestigial

**Web's disk is the weakest case.** Everything on it arrives over HTTP from a
worker, and it exists only because Render will not share a disk between services.
If web read from same-region object storage instead, it would gain rolling deploys
and horizontal scaling. But:

- The `_bootstrap_render_data` path ([app.py:65](syndicate/app.py:65)) writes
  committed repo data to web's disk at boot as the cold-start net.
- Web's disk is also the **read side** of `pull_hot_artifacts` — refresh-worker
  pulls *from* web. So web's disk is load-bearing for a worker, not just for web.

### Blockers, concretely

| blocker | severity |
|---|---|
| No storage abstraction — `data_root()` returns a `Path`, used pervasively | **high** — this is the whole project |
| Bulk families (`book_quotes`, `odds_history`) are worker-local by design and sized in hundreds of MB/day | **high** for workers, none for web |
| `pull_hot_artifacts` makes web's disk an input to refresh-worker | medium |
| `_bootstrap_render_data` cold-start net assumes a writable local tree | medium |
| Render offers no first-party same-region object store; S3 in the same region would be external egress unless routed carefully | medium — **INFERENCE**, I have not priced this |
| 97 glob patterns assume a filesystem; object-store listing has different cost/semantics | medium |

### Recommendation

Do not pursue disk removal as part of this cleanup. The single-instance and
stop-then-start constraint is real, but the **9 zero-instance hours in 14 days on
live-odds-worker are mostly not deploy-related** — 25 of its 69 failures are its
own 6h self-recycle and 33 are OOM kills. Fixing retention (Task 3) and the OOMs
(Task 4) addresses the availability symptom far more cheaply than re-platforming
storage. Revisit if you want genuine horizontal scaling on web, and scope it as
its own project starting with a storage interface behind `data_root()`.

---

## Task 7 — Build minutes

**CI is already on GitHub Actions** — [.github/workflows/ci.yml:13](.github/workflows/ci.yml:13)
runs `ubuntu-latest`, and [daily-update.yml:40](.github/workflows/daily-update.yml:40)
runs `windows-latest`. Neither touches Render. **So moving CI to GitHub Actions
cannot recover any Render pipeline minutes — there is nothing there to move.**

The 1,549 minutes are **deploy builds**. Measured over 14 days:

| service | deploys | wall-clock | avg | triggers |
|---|---|---|---|---|
| live-odds-worker | 166 | 581 min | 3.5 min | `api` 158, `blueprint_sync` 4, `manual` 1, other 3 |
| refresh-worker | 349 | 1,171 min | 3.4 min | `api` 336, `blueprint_sync` 6, `manual` 4, other 3 |
| web | 349 | 1,327 min | 3.8 min | `api` 345, `blueprint_sync` 1, `manual` 2, other 1 |
| **total** | **864** | **3,079 min** | | `api` **839 / 864 (97%)** |

3,079 minutes of deploy wall-clock in 14 days ≈ 6,600/month. Billed *build*
minutes are the build phase only, a fraction of that — 1,549 against a
1,000 included allowance is entirely consistent with this deploy volume.

**Cause: 864 API-triggered deploys in a fortnight — 62 per day across three
services.** `autoDeploy: false` everywhere, so these are all scripted deploys from
this repo's own tooling and from parallel sessions. Every one runs
`pip install -r requirements.txt` from scratch
([render.yaml:677](render.yaml:677) and the two siblings).

### What would actually reduce them

1. **Deploy fewer times.** This is the whole answer. 62 deploys/day is the
   number to attack; nothing about *where* CI runs affects it.
2. **Batch multi-service deploys.** refresh-worker and web are at 349 each —
   near-identical counts suggest they are being deployed in lockstep. If a change
   only affects one service, deploy one.
3. **Cache the pip layer.** `pip install -r requirements.txt` with no wheel cache
   is most of a 3.5-minute build. Render supports build caching; a `pip
   --cache-dir` under a persisted path, or moving to `uv`, would plausibly halve
   it. **INFERENCE** — I have not profiled a build's phases and cannot say what
   share is pip versus image assembly.
4. **Raise the allowance** if 60 deploys/day is genuinely the working style — at
   that rate the overage is structural, not wasteful.

---

## What shipped, and an ID correction

| commit | item | state |
|---|---|---|
| `9abd4eb0` | PR-1, `render.yaml` publish URL | pushed |
| `4970f319` | PR-1 follow-up, publish byte budget in `render.yaml` | pushed |
| `65cf7a80` | **`#399`** — `book_quotes` compressed at rest, 38.7x | pushed |
| `e81b5425` | `#398` — retention coverage + settlement tier | pushed |

**`65cf7a80` was committed as `#397` and is renumbered to `#399`.** `#397` was
taken concurrently by `c5c382b6` (per-game cap readability), which is earlier in
history. `#398` was **not** available as the renumber target either — it is
`e81b5425`, above. The commit message on `65cf7a80` cannot be amended now that
it is on `origin/main`; no code or comment references the number, so this table
is the mapping of record.

**Why the duplicate detector could not catch it.** Both `#397`s were
commit-only with no `todo.md` entry, and the file-level dupe check reads
`todo.md`. `git log --grep` and `grep todo.md` disagree by design, and the ID
lived in the one not checked. But re-checking harder does not fix this: the
`#398` claim above was *correct when the other session ran it* and stale by the
time it arrived, because `e81b5425` landed in between. With four sessions on one
branch, ID selection needs a check at push time or a per-session prefix, not a
more diligent check at commit time.

## What I would ship first, in order

1. **PR-1 — `render.yaml`: point both workers' `SYNDICATE_WEB_PUBLISH_URL` at
   `http://syndicate-an21:10000`.** ✅ **Committed `9abd4eb0`, NOT pushed.**
   See "PR-1 status" below.
2. **PR-2 — artifact retention.** Biggest single lever: bounds the disk (Task 3),
   bounds the sweep's per-tick work, and bounds `_LAST_PUBLISHED_CHECKSUM` as a
   side effect. Ships dry-run first. Unblocked — settlement grace period decided
   (settled + 30 days).

---

## PR-1 status and the pre-push enumeration

Committed as `9abd4eb0`. **Deliberately not pushed**, because pushing
`render.yaml` triggers `blueprint_sync`, which deploys, and
`scripts/check_deploy_safety.py` was red at commit time:

```
NOT CLEAR -- in flight:
  * Odds refresh RUNNING (pid=197, lane=live-odds-worker, stamp=20260812_212252)
  - WARNING: Live games in progress
```

Push when that exits 0.

### The `#284` enumeration, before and after

Whole env block diffed against each service's live `/v1/services/<id>/env-vars`
(paginated at `limit=100`):

| service | [A] value changes *before* | [A] *after* | [B] added | [C] live-only |
|---|---|---|---|---|
| web | 0 | 0 | 0 | 10 |
| refresh-worker | **1** (the URL) | **0** | 0 | 16 |
| live-odds-worker | **1** (the URL) | **0** | 0 | 13 |

`[B] = 0` everywhere, so there is no absent-vs-default trap in this change — the
`EVALUATION_SETTLEMENT_REFRESH_INTERVAL_SECONDS` failure mode recorded in
`CLAUDE.md` does not apply here. **A sync from the corrected file is an env
no-op on all three services.** The only remaining cost of pushing is the deploy
itself: killed in-flight work and ~2 minutes of web 502s.

### Measured: `blueprint_sync` upserts, it does not delete

`CLAUDE.md` says a sync "writes the WHOLE env block, not your diff", which reads
as though live-only keys might be dropped. On the evidence they are not:

- 10 / 16 / 13 live-only keys are present on web / refresh-worker /
  live-odds-worker **today**, after 1 / 7 / 14 blueprint syncs in the last 14 days.
- The 2026-08-08 sync already recorded in `CLAUDE.md` moved refresh-worker
  **92 → 93** keys. A wholesale replace would have cut it to the ~83 the
  blueprint defines. An increase is only consistent with upsert.

So the accurate rule is: **a sync forces every key *named in the file* to the
file's value, and leaves keys absent from the file alone.** That is a narrower
and more useful blast radius than "everything", and it is what makes the
before/after table above sufficient. Worth folding back into `CLAUDE.md`.

**This does not make config pushes safe** — it makes them *enumerable*. The
hazard PR-1 fixes was precisely a key named in the file with a stale value.

Then, in rough benefit order: unset `SYNDICATE_LIVE_ODDS_REFRESH_MEMORY_TRACE`
(one env key, no code); compact-JSON + gzip on the ladders artifact; re-scope the
#395 ceiling to external destinations only; clamp the publish watermark window.

**Not recommended:** removing the disk (Task 6), or moving CI to GitHub Actions
(Task 7 — it is already there).
