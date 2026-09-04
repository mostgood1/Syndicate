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

## ALL THREE ADDRESSED, same day `[user decision 2026-09-04]`

- **(a) and (b) — `08d3fae5`.** The open question here ("which key arms it") was
  SETTLED first: `/api/ops/version` on the live web dyno reports its own runtime
  env, carrying `RENDER_SERVICE_NAME`, `RENDER_INSTANCE_ID`,
  `RENDER_EXTERNAL_URL` and `RENDER_GIT_COMMIT` — **none of which are among the
  76 user-defined vars**, so Render injects them and no dashboard edit can
  delete them. The guard now arms on those as well, and a **second defect found
  while reading** was fixed with it: the original chained the LOOKUPS, so
  `RENDER=false` short-circuited the fallback and disarmed the hard gate even
  with `SYNDICATE_REQUIRE_HOSTED_STORAGE=true`. The refusal message now names
  the operation and the arming signal.
- **(c) — this commit.** Refusals and warnings are counted per operation, with
  first/last refusal timestamps, behind `GET /api/ops/request-path-guard`
  (admin-gated). The payload **states its own scope**: the counters are
  per-process and web runs `WEB_CONCURRENCY=2`, so a read covers one worker of
  two and says so, with its pid. Pushing them to the keyvalue store would make
  them service-wide at the cost of a network write on the request path — the
  exact thing the guard exists to keep off it — so the counter is the always-on
  signal and the log line remains the ledger.

  One claim did NOT survive measurement and is recorded because it is the kind
  that usually slips through: the counter's lock is **not** there to stop lost
  increments. An unlocked counter lost **zero** of 80,000 increments across four
  threads over five trials on CPython 3.11. The lock buys snapshot CONSISTENCY —
  the total and the per-operation map are copied together, so they reconcile.

## (a) IS NOW SETTLED, AND IT WENT THE OTHER WAY — `[deployed 2026-09-04 18:20:29Z, ee20c522]`

`/api/ops/request-path-guard` on the live web dyno reports
**`hosted_signal = 'RENDER'`**. So `RENDER` **is** injected into the runtime —
absent from all 76 user-defined env vars, which is exactly why the env-vars API
could not see it and why this document refused to guess. The guard was armed by
`RENDER`, **not** by `SYNDICATE_REQUIRE_HOSTED_STORAGE`, and deleting that
storage key would **not** have disarmed it.

**So the (a) danger above was real as a possibility and was not the real
situation.** Recorded plainly rather than quietly dropped: a warning that turns
out not to apply has to be walked back as clearly as one that does. The
hardening in `08d3fae5` still earns its place — it fixed the `RENDER=false`
short-circuit, which was a live defect, and made arming multi-source so the
question cannot reopen.

## AND THE COUNTER FOUND SOMETHING IN FOUR MINUTES

First read after the deploy, one worker, ~4 minutes since boot: **`refused=0`,
`warned=25`** — every one a warn-only site doing NETWORK I/O on the request path.

    mlb_cards_fetch_current_feed_live          16
    ncaaf_espn_game_state_fetch                 4
    wnba_has_games_for_date_espn_fetch          4
    wnba_public_scoreboard_live_state_fetch     1

`refused=0` means **this document's answer is unchanged** — web still is not
computing intelligence in a request. But `mlb_cards_fetch_current_feed_live`
corroborates the `live-lens-date-gate` lane's note that a feed_live miss on the
request path is an HTTPS call, and was the measured cause of `/healthz` timing
out and gunicorn being SIGTERM'd. **One worker of two, one boot, ~4 minutes —
that is not a rate.** Handed to `mlb-feed-live-terminal-refresh` and
`render-web-request-path`, not chased here.

## THE COUNTER IS A WEB-ONLY INSTRUMENT — do not read it as platform-wide

`GET /api/ops/request-path-guard` exists **only on web**, and its numbers can
only ever describe web. Both the guard and the counter are structurally inert on
refresh-worker and live-odds-worker:

    def warn_if_compute_in_request_path(operation):
        if not has_request_context():
            return          # <-- always taken on a worker

Both workers are plain scripts with no Flask app, so `has_request_context()` is
always False there. `refused=0` from that endpoint means "web refused nothing",
never "the platform refused nothing" — and the workers could not refuse anything
even if they wanted to, because the branch is unreachable. `blueprints/ops.py`
serves no routes on a worker either.

**Deliberately NOT deployed to the workers `[user decision 2026-09-04]`.** The
premise for doing so was that they needed these fixes; they do not. Established
before the decision, not after: refresh-worker was ALREADY on `58ecba3a`
(deployed 18:15:15Z by another session, carrying both `08d3fae5` and the
counter), and on live-odds-worker the code would be inert. Every hard gate
agreed independently — refresh-worker had a live MLB sim running
(`run_mlb_daily_sim_job.py` plus multiprocessing children), preflight returned
**TOO_SOON** (19 min into a 25-min minimum; `#563`), and its claim was taken 18
seconds earlier by `mlb-feed-live-terminal-refresh`; live-odds-worker returned
**CLAIMED** with an odds refresh job in flight. Nothing was forced.

Bringing the workers current is still a live option, but it is a DIFFERENT
decision: they are 31-36 commits behind and that payload is 11-14 runtime files
of other lanes' in-flight work (the MLB sim engine, prop/soccer projections,
portfolio commit, the accuracy ledger), not mine.

## What is STILL not done

**All three are now LIVE on web** as of `ee20c522`, 2026-09-04T18:20:29Z
(`deploys.md`). refresh-worker and live-odds-worker still run older SHAs, so the
guard there is the old code — harmless, since it can only fire inside a request
context and neither serves one. The refusal line has CHANGED SHAPE on web:
anything grepping the exact string `REFUSED: compute in request path on hosted
web` now needs the `(operation=..., hosted_signal=...)` suffix allowed for.

Still open from §5, and not answered by any of this: **the eight-day silence
means either the cache stopped missing or the caller stopped calling, and which
one is NOT established.** The new counter will distinguish them the next time it
happens; it cannot answer it retroactively.

Adjacent lanes, untouched: `render-web-request-path` (UNOWNED, claims released,
"SHIPPED AND MEASURED; ONE ITEM OWED"), `web-oom-thread-gating` (OPEN, owned).
The 2026-08-21 scope note `scope_2026-08-21_home_request_path_compute.md`
describes a DIFFERENT request-path defect — `home.py`'s per-game
`_mlb_game_market_recommendation_rows` loop — which this check did not revisit.
