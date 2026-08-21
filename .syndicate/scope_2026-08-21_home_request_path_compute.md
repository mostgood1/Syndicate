# SCOPE — home's request-path compute (the 22:2xZ outage's real cause)

Written 2026-08-21 22:3xZ, immediately after the web outage, by the session
that triggered it. **Diagnosis done, code deliberately NOT written — see §5.**

## 1. The defect, located

`syndicate/blueprints/home.py:5379` calls
`_mlb_game_market_recommendation_rows(game)` **inside a loop over every game on
the slate**. That function is ~130 lines (`:3570`-`:3698`) and emits one
`MLB_GAME_MARKET_ROWS_DIAG` line per call — 15 of them per home request on
tonight's slate, visible in the production logs during the incident.

There is **no cache**. Every home request recomputes all 15.

## 2. Why it took the site down

Render's health check times out at **5 seconds**. Cold, home takes 20-25s. So:

    instance starts cold -> home exceeds 5s -> server_failed (unhealthy)
    -> cycle -> cold again

Observed flapping at 22:15:21 / 22:17:11 / 22:18:41 / 22:25:42 / 22:27:03,
each `server_available` followed by another `server_failed`, `evicted: false`
throughout (NOT an OOM). It broke only when the artifact-publish flood that was
starving web drained on its own.

**This violates the repo's most load-bearing rule** (`CLAUDE.md`): "The web
service does no heavy computation. It only reads precomputed artifacts."

## 3. THE TRAP THAT MAKES THE OBVIOUS FIX WRONG

`@lru_cache` is the reflex here and this repo has already paid for it.
`features/soccer/sources.py` documents the reason in prose:

> "Not cached (2026-07-24 fix ...): this file gets regenerated repeatedly as
> odds/scores update, and **gunicorn workers never auto-recycle**, so an
> `@lru_cache` here (as this used to have) would permanently freeze the
> first-ever read."

So a naive memoisation converts a latency bug into a **staleness** bug that
survives until the next deploy — strictly worse, because it is silent. Any
cache here needs a vintage key (artifact `generated_at`), not just `game_pk`.

## 4. What the fix probably is, in blast-radius order

1. **Measure first.** Time `_mlb_game_market_recommendation_rows` for one game.
   The 130 lines may not be the cost — it may be something it CALLS. Fixing the
   wrong layer is the failure mode this scope exists to prevent.
2. **Cache keyed on artifact vintage**, not on game identity alone, so a
   refreshed artifact invalidates it. Per-request memoisation (compute once per
   request rather than once per game) is the smallest safe step if the same
   inputs are re-read per game.
3. **Move it to the artifact layer** — the architecturally correct answer, and
   what the rule in `CLAUDE.md` actually asks for. Largest change.

## 5. WHY THIS IS A SCOPE AND NOT A COMMIT

The session that found this had ~no context budget left, had just triggered an
outage on this same service, and had within the preceding hour:

- shipped a change asserting **"no regression"** on unit tests that MOCK the IO
  they were supposed to be measuring — structurally blind to a latency cost;
- **misattributed the outage twice**, the second time needing a rollback to
  disprove, while the contradicting evidence (home failing, and home cannot
  reach the changed code) sat in the same output it was reading.

Editing the hottest route on a service that is **still degraded** (home 12s,
intermittent timeouts), from that position, is how one incident becomes two.
The diagnosis is the deliverable; the next session should start at §4.1 with a
measurement, not at a code edit.
