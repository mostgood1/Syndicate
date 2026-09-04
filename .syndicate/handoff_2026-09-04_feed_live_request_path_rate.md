# HANDOFF → `mlb-feed-live-terminal-refresh` — `_fetch_current_feed_live` is firing 8.7×/min on the request path, with ZERO live games

`[2026-09-04, from session c4287631, lane feed-live-warn-rate]`
**Measured, not inferred. Nothing here is a fix, and I edited none of your
files** — `syndicate/features/mlb/cards.py` is your claim and stayed yours.

---

## FINAL BASELINE — the full 20-minute window, and it corrects me TWICE

**This supersedes both earlier numbers in this file. Read this section and skip
the two below it, which are kept only so the corrections are auditable.**

    41 samples, 2026-09-04T18:42:53Z .. 19:02:53Z, 20.0 min, no restart
    pid 97:  192 -> 208  (+16,  1 event)
    pid 98:  176 -> 288  (+112, 4 events)
    TOTAL:   +128 calls over 20.0 min, in 5 increase events

**128 statsapi calls in 20 minutes, with ZERO live games.** At n=5 events this
finally clears the quotability floor, so: **6.4 calls/min**, or more usefully
**8 full-slate passes in 20 min = one pass every 2.5 minutes**.

### Correction 1 — "every increment is exactly 32" was a SAMPLING ARTIFACT

I told you the increments were always 32 and concluded "the loop traverses the
16-game slate TWICE per event". **Wrong.** With the full window the increments
are **`[16, 32]`**. The base unit is **16 = one pass over the 16-game slate**;
a 32 is simply two passes landing inside one 30-second sampling interval.

Nothing about the mechanism changes — it is still one synchronous statsapi call
per game per pass — but the "twice per event" inference was mine and it was an
alias, not a property of the code. 128 calls / 16 per pass = **8 passes**.

### Correction 2 — the per-minute rate, restated honestly

I first wrote **8.7/min** off 7.4 minutes and two events; at 11.9 minutes the
same run gave **5.4/min**; the full 20 minutes gives **6.4/min** on five events.
The first two were not quotable and the third is, barely. The stable statement
is the pass count: **one full-slate pass every ~2.5 min**.

`scripts/sample_request_path_guard.py` now enforces this floor rather than
relying on me to remember it — it refuses to print a rate below 5 increase
events and prints the count instead.

---

## The two earlier, superseded numbers — kept so the correction is auditable

## CORRECTION, same day, before you act on it — the per-minute figure was over-precise

I first wrote **8.7/min** off a 7.4-minute window. Extending the same run to
11.9 minutes moved it to **5.4/min**, and the reason is that the entire figure
rests on **TWO burst events**. A per-minute rate from n=2 is not a rate; it is
one number pretending to be a distribution, and my own standing rule ("a rate,
not a count — state the denominator") is what I broke.

**Quote this instead, which does not move:**

    64 statsapi calls in 11.9 minutes, as 2 bursts of exactly 32
    => roughly one 32-call burst every ~6 minutes, n=2 events

The burst SIZE (32, always) is solid — it is a structural fact about the loop.
The burst FREQUENCY is not yet characterised, and an evening slate will almost
certainly change it. Everything below stands except the headline number.

## The number (as first measured — see the correction above)

`GET /api/ops/request-path-guard`, sampled every 30s, deltas computed **within a
pid** (the counter is per-process and web runs `WEB_CONCURRENCY=2`, so
differencing across workers would be fiction):

| pid | samples | span | `mlb_cards_fetch_current_feed_live` | rate |
|---|---|---|---|---|
| 98 | 9 | 7.1 min | 176 → 240 (+64) | **9.0/min** |
| 97 | 10 | 7.4 min | 192 → 192 (+0) | 0.0/min |
| **both** | 19 | 7.4 min | **+64** | **8.7/min** |

Window 2026-09-04T18:42:53Z .. 18:51:46Z. No restart in it (no count decreased).

**One warn is one synchronous `https://statsapi.mlb.com/.../feed/live` call with
an 8-second timeout, executed inside a live web request** — against Render's
5-second health-check budget.

## The mechanism, and why it is NOT what you'd guess

`cards.py:2345` and `:2349`, inside `for game_pk in game_pks:` —

```python
payload = load_json_or_gz_file(feed_path)
if selected_date == today_iso and isinstance(payload, dict) and not _actual_payload_is_live(payload):
    live_payload = _fetch_current_feed_live(int(game_pk))     # artifact present but not LIVE
if not isinstance(payload, dict) and selected_date == today_iso:
    payload = _fetch_current_feed_live(int(game_pk))           # artifact missing
```

`_actual_payload_is_live` (`:3434`) is false for **`Preview` and for `Final`**,
not just for a missing artifact. So the re-fetch branch is true for every game
that has not started **and** every game that has ended — most of the slate, most
of the day.

**I pre-registered the hypothesis that this tracks live games, and it is
FALSIFIED.** Today's slate is **16 games, all `Preview`, zero live**, and the
rate is 8.7/min anyway. The driver is artifact liveness, not game state.

## The increment is the strongest evidence

**Every single non-zero increment observed was exactly 32**, never 16, never
anything else — and the slate is 16 games. So the unit of work is not "a fetch",
it is **16 sequential statsapi calls per pass**, two passes per event. Worst case
that is 16 × 8s of timeout inside one request.

## Two observations I have NOT turned into conclusions

- **All of it landed on ONE worker.** pid 98 took every burst; pid 97 took none
  in 7.4 minutes. Combined with fixed 32-call bursts arriving on a roughly
  60-second beat, that looks more like an automated poller on a keep-alive
  connection than like user page loads — note `SYNDICATE_INTELLIGENCE_REFRESH_INTERVAL_SECONDS=60`
  and `MLB_LIVE_LENS_LOOP_INTERVAL_SECONDS=30` in web's env. **I have not
  identified the caller**, and it matters: a poller is fixed differently from a
  page.
- **I have not measured latency impact.** That these calls happen is measured;
  that they are slowing anything is not. `scope_2026-08-21_home_request_path_compute.md`
  records `/healthz` starvation from request-path work as a real prior incident,
  which is why it is worth your time — but that is prior art, not this
  measurement.

## The trap, from your own repo's prior art

`@lru_cache` is the reflex and this repo has already paid for it.
`features/soccer/sources.py` documents why: the file is regenerated as odds and
scores update, and **gunicorn workers never auto-recycle**, so a naive memo
freezes the first-ever read until the next deploy — trading a latency bug for a
silent staleness bug. Any cache here needs a **vintage key** (artifact
`generated_at`), not `game_pk` alone. `scope_2026-08-21_home_request_path_compute.md`
§3 has the full reasoning.

## How to watch it yourself

    GET /api/ops/request-path-guard      (admin token; shipped in `58ecba3a`, live on web since 18:20:29Z)

Read `covers` and `pid` before quoting any number — it is **one worker of two**,
and the endpoint exists on **web only** (the guard is inert on both workers,
`has_request_context()` is always false in a plain script). `by_operation`
carries the per-operation split.

**Owned by you, not me.** My lane (`feed-live-warn-rate`) claims no code and is
closing with this handoff.
