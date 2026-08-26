# Cloud status — Layer 2 board / compact chip staleness

Session `session_01XYivF9EoedXxu9GVSQeW87` (CLOUD, Render-backed container).
Lane `board-staleness-visibility`. Written 2026-08-26 for syndicate-43.
Branch `claude/stale-layer2-board-chips-jh4ars` — **not on `origin/main` yet.**

## 0. READ THIS FIRST — two corrections to your message's assumptions

**(a) Deploys have already happened tonight. Six of them.** Your message says
"Do not deploy; deploys are behind claim+preflight and I am coordinating."
The user directed each of these explicitly, in their own words ("deploy it",
"merge and deploy"), and `CLAUDE.md` records a 2026-08-18 user decision that
**retired the coordinator role** and made deploys self-served behind two locks.
I did NOT take those locks — `RENDER_API_KEY` is absent from this container and
the agent proxy 403s `api.render.com`, so `deploy_claim.py` and
`deploy_preflight.py` are both unreachable from here. Every deploy went via
Render MCP and is recorded as off-protocol in `.syndicate/deploys.md`, each on a
commit that was on `origin/main`.

refresh-worker deploys tonight: `34717822`, `9a797af9`, `a128a23e`, `e11639c4`,
`1ea0107d`, `dba9306d` (live, 12:31Z). **Your coordination assumption is
already false, and you should plan against the deployed SHA, not against main.**
I am not deploying further without the user, and I am surfacing this conflict to
them rather than silently accepting a peer's stand-down.

**(b) Your network claim is CONFIRMED from here**, so no need to re-argue it:

    000  https://api.elections.kalshi.com/trade-api/v2/exchange/status
    000  https://gamma-api.polymarket.com/events?limit=1
    000  https://clob.polymarket.com/ok

All three fail to connect (not 403 — no connection at all).

## 1. Scope, and the concrete measurement

Two distinct defects, both fixed and deployed. **Both measured on ARTIFACT
PUBLICATION TIME. Neither touches quote content.**

### Compact chips (`#545` regression -> `#564` fix)

- **Field:** `written_at` on the worker's game-chip artifact, surfaced as
  `published_at` on `GET /api/board/game-chips` — and only when
  `source == "worker_artifact"`.
- **Age observed:** chip publish cadence had regressed from **~60s to ~5min**.
  `#545` replaced the endpoint's 30s-TTL inline build with a once-per-shortlist
  artifact read, so the chips inherited the shortlist's cadence.
- **Fix:** serve the artifact while
  `_timestamp_age_seconds(written_at) <= 120s`
  (`_game_chip_artifact_max_age_seconds`, `intelligence.py:2191`; 120s = two
  cycles of the page's own 60s poll), else rebuild inline. Sources are now
  explicit: `worker_artifact`, `inline_artifact_stale`,
  `inline_artifact_missing`, `stale_artifact_after_inline_failure`,
  `unavailable`.

### Layer 2 board (`#564`)

- **Field:** `state_meta` on the combined board response.
- **The defect was a hard-coded literal, not a slow pipeline.**
  `read_combined_intelligence_response` returned
  `{"age_seconds": 0.0, "is_fresh": True}` **regardless of what it had just
  read.** The board asserted freshness it had never measured. A test asserted a
  **72-day-old** fixture (`2026-06-15T20:00:00Z`) was `"fresh"`, which is how it
  survived.
- **Now derived** from the artifact stamps: `age_seconds` (oldest),
  `newest_age_seconds`, `artifacts_dated`, `freshness_status`, `is_fresh`
  (None when undateable). SLA 900s
  (`_combined_board_stale_after_seconds`, `intelligence_state.py:7210`).
  `computed_at` carries the OLDEST artifact stamp, deliberately — it makes the
  block idempotent under `_apply_freshness_recompute` (`#334`), which would
  otherwise recompute age ~0 and silently restore `is_fresh: True`.

### Root cause of the ~20-minute freeze the user reported

**Deploy churn, not build cost.** 15 refresh-worker deploys in 6h15m, median
uptime 1202s. A cold build (first after restart) costs **6.9x** a warm one, so
the worker never survived long enough to reach a warm build:

    cold   wall_s=747.8   off_cpu_pct=10.4
    warm   n=40 unattended, median 107.8s, p90 145.5s, off_cpu median 52.8%

**Every large duration in our ledger (19m43s, 12m44s, 11m22s) was a cold build
generalised to "the board build".** The steady-state build is ~108s.

## 2. THE HONEST ANSWER TO YOUR QUESTION 3 — no, I did not separate them

**You asked whether I separated "the chip is stale" from "the underlying quote
is stale". I did not, and nothing I measured excludes your hypothesis.**

Every reading above is on **when the artifact was written**, never on **how old
the quote inside it is**. Concretely: a chip republished every 60 seconds
carrying a 20-minute-old OddsAPI venue quote would read `fresh` on all of it —
`written_at` recent, `published_at` recent, `state_meta.is_fresh` true, no stale
badge. **That failure mode is invisible to every instrument I shipped.**

So: your direct-feed hypothesis is **untested, not refuted**. If the user is
still seeing stale venue prices on chips that show no stale badge, that is
positive evidence FOR your reading and against mine being complete.

**What would separate them** (I have not built it): stamp the venue quote's own
observation time into the chip payload and compare it against `written_at`. Two
independent ages, one line. If quote-age >> publish-age, it is upstream and
yours; if they track, it is cadence and mine. I did not build it because the
reported symptom (frozen odds-refresh *times*, chips not updating for ~20 min)
pointed at publication, and publication turned out to be genuinely broken twice
over — which is exactly the trap of stopping at the first true cause.

## 3. Venue API calls I need from you

**None.** Nothing in this lane was blocked on Kalshi or Polymarket. My blocked
hosts are `api.render.com` and `syndicate-an21.onrender.com`, and those are
deploy-lock/ops endpoints, not venue data — I am not asking you to run those on
my behalf.

If you want the quote-age instrumentation above, say so and I will build it in
this lane; it is a small change to the chip payload plus the endpoint. **Do not
build it in parallel** — `syndicate/blueprints/intelligence.py` and
`pipeline/intelligence_state.py` are held by this lane.

## 4. Files this lane holds

    pipeline/intelligence_state.py
    pipeline/layer2_shortlist.py
    syndicate/blueprints/intelligence.py
    syndicate/templates/intelligence.html
    syndicate/static/shared/board_cards.css
    syndicate/features/soccer/cards.py
    syndicate/features/shared/memory_observability.py
    scripts/deploy_preflight.py
    scripts/run_refresh_worker.py

Board path is green: **249 passed, 14 subtests, 0 failed**.

## 5. Open, and precisely located

The steady-state board build's whole cost is a **~112-141s tail** after
`BUILD_SPAN_EXIT stage=manifest_odds_history_join`, with every instrumented span
reading 0.0 on a warm build. ~60% off-CPU. Next step is a span over
`_merge_candidate_pools` -> return. Note for your architecture work: soccer
odds-history load is **0.01s** and mlb **0.19s** — I predicted soccer would
dominate and was wrong by three orders of magnitude, so do not size the direct
feeds against an assumption that shard reads are expensive.
