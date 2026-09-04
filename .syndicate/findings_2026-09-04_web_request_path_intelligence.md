# Does web still compute intelligence on the request path?

`[2026-09-04, session c4287631, lane web-request-path-intelligence-recheck]`
Follow-on to `findings_2026-09-04_web_sigkill_137_cohort.md`, which found the 38
SIGKILLs sat under commits titled "compute intelligence … on empty cache".

**Answer: NO — it is structurally refused. But the attempt is still wired, and
it was still firing 348 times in seven hours as recently as 2026-08-27.**

The distinction matters. "web does not compute intelligence in a request" is
true because a guard *stops* it, not because nothing tries.

---

## What is measured

### 1. The path still exists and web is still the process that would take it

`pipeline/intelligence_state.py:4789` says so in its own words:

> `_compute_board_publication_response` has TWO callers — the background loop
> AND `run_intelligence_query`, which does execute in a live request on web when
> the loop flag is off.

### 2. The loop flag IS off on web — read from the LIVE env, not from that comment

`SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP`, all three services,
`/v1/services/<id>/env-vars`, fully paged:

| service | value | env keys |
|---|---|---|
| web | **`false`** | 76 |
| live-odds-worker | `false` | 129 |
| refresh-worker | **`true`** | 153 |

That is the correct split — one owner recomputes — and it is also precisely what
puts web in the position of having no loop to fall back on when its cache misses.

### 3. A hard guard refuses the compute, at three entry points

`syndicate/features/shared/request_path_guard.py`. Fires at exactly three sites,
all in `pipeline/intelligence_state.py`: `layer2_fast_refresh` (`:4802`),
`_build_candidate_pool` (`:5631`), `_compute_response` (`:7848`). Predicate is
`has_request_context() and _is_render_hosted()`; refresh-worker has no Flask app
so it can never fire there.

**The guard sits AFTER the cache check at every site.** A cache hit is served
normally; only a genuine miss reaching the heavy build is refused. That is
exactly `CLAUDE.md`'s prescribed behaviour — a degraded state rather than an
on-request backfill.

### 4. It demonstrably fires in production

    2026-08-27T15:15:23Z .. 2026-08-27T22:19:34Z
    ERROR:...request_path_guard:REFUSED: compute in request path on hosted web
    348 matches, 5 pages, fully paged

So requests really do reach the compute entry points on web, and really are
turned away. ~50/hour across that window.

### 5. It has been silent for eight days

Zero matches 2026-08-28T00:00Z .. 2026-09-04T17:00Z. **Positive-controlled**, in
the way this repo requires a null to be: the same reader and the same filter
returned 348 matches on 08-27, and `healthz` in a five-minute slice INSIDE the
empty period returned 70 matches (1,162 across the storm window). The reader
works there; the refusals genuinely stopped. Last one
**2026-08-27T22:19:34.973Z**.

### 6. The refusal is swallowed, not surfaced to the user as a 500

`ComputeInRequestPathError` appears **nowhere** in web's logs — including
during the storm, where the control proves the reader was working. It is caught
by name nowhere in application code either; `syndicate/blueprints/intelligence.py`
carries 61 broad `except Exception` blocks, and the `layer2_fast_refresh` site
documents its own catch explicitly ("Caught, not propagated"). So each of the
348 became a degraded response, silently.

---

## Three things worth someone's attention

**(a) The guard is proven armed — but WHICH key arms it is not established, and
one candidate is fragile.** `_is_render_hosted()` reads `RENDER` **or**
`SYNDICATE_REQUIRE_HOSTED_STORAGE`. On web, `RENDER` is **absent from all 76
user-defined env vars** while `SYNDICATE_REQUIRE_HOSTED_STORAGE='true'`. Render
is understood to inject `RENDER=true` into the runtime — **not verified here**,
and the env-vars API cannot show an injected value — so I cannot say which key
is doing the work. Arming itself is not in doubt: the guard fired 348 times, and
that branch is unreachable unless `_is_render_hosted()` returned true.

Why it still matters: **if `SYNDICATE_REQUIRE_HOSTED_STORAGE` is the one arming
it, then removing or renaming that key silently downgrades the HARD guard to
warn-only** and restores exactly the request-path compute that caused `#98`. Its
name is about *storage*, so it is a plausible thing for someone to tidy. This is
the `unknown must not default permissive` shape: absent env lands on the
permissive branch, and nothing says so. Cheap to settle — log which key matched,
or assert at boot.

**(b) The refusal log line cannot tell you WHICH entry point was refused.** The
guard passes `operation` through `extra={...}`, which the default formatter
drops. All 348 lines are byte-identical text. `_compute_response` (the query
API) and `_build_candidate_pool` (including the ops debug endpoint that caused
`#98`) are indistinguishable in production. Put the operation in the message.

**(c) 348 silently degraded responses in seven hours had no alarm on it.** The
guard is doing its job — this is not a memory risk any more. But a cache miss
on web is now a user-visible degradation with an ERROR log nobody counts, and
the eight-day silence since means either the cache stopped missing or the caller
stopped calling. **Which of those it is, is NOT established here.**

---

## What was NOT done

No code changed. No deploy. The remedies above are named, not applied — (a) in
particular touches a load-bearing guard and deserves its own lane and its own
falsification test (`off != on`, per the model-engine standard).

Adjacent lanes, untouched: `render-web-request-path` (UNOWNED, claims released,
"SHIPPED AND MEASURED; ONE ITEM OWED"), `web-oom-thread-gating` (OPEN, owned).
The 2026-08-21 scope note `scope_2026-08-21_home_request_path_compute.md`
describes a DIFFERENT request-path defect — `home.py`'s per-game
`_mlb_game_market_recommendation_rows` loop — which this check did not revisit.
