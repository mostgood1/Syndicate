# FINDINGS — the execution caps I read all day were ENV VARS THAT ARE NOT IN FORCE

`[2026-09-09, lane segments-joint-v1 — my error, and an agent's independently, on the same predicate]`

## The correction

Every execution cap quoted in this session's venue-routing work was read from
`live-odds-worker`'s environment. **A STORED SETTINGS STORE OVERRIDES THE
ENVIRONMENT ENTIRELY**, and it has held different, larger values since
**2026-09-04T13:21:37-05:00**.

| setting | env var (quoted all day) | **ACTUALLY IN FORCE** | source |
|---|---|---|---|
| `max_order_dollars` | 10 | **35.01** | stored |
| `max_day_dollars_kalshi` | 50 | **150.01** | stored |
| `max_day_dollars_polymarket` | 100 | **150.01** | stored |
| `max_day_dollars_all_venues` | 40 | **251.01** | stored |
| `max_day_orders_kalshi` | (empty) | **15** | stored |
| `bankroll_units` | 40 | **1000** | stored |

Read from `/api/portfolio/limits` and `/api/portfolio/settings`, whose `sources`
map reports **`"stored"` for every field**, with `store_error: null`.

## Why the check I ran could not have found it

I *did* check for a stored override before touching anything, and got a clean
negative:

    /api/ops/artifacts/export?pattern=reports/intelligence/execution_limits.json
    -> NO STORED LIMITS FILE -- env vars govern

**That check was structurally incapable of finding the store.** The settings live
in the **keyvalue backend** via `refresh_state_store.read_json_file`, not as a
published artifact. `learnings.md` already records this exact blindness —
*"[[project_keyvalue_artifact_split_blinds_guards]]: `read_json_file` sees only
keyvalue; a guard reading it is blind to exactly the big payloads that matter"* —
and `execution_limits_settings.py`'s own module docstring says so at `:19-25`:
the web form writes to a store **"the worker never consulted"** unless read
through that hop.

So the artifact export returning nothing was not evidence of absence. **It was
the wrong instrument, and its clean negative read exactly like a real one.**

## What was actually wrong downstream

- **The venue-routing prize was understated ~3x.** I told the user "5 orders/day
  of $10 = ~$2/day, the caps bound the prize". The real ceiling is **15 orders at
  up to $35.01, i.e. $150.01/day**. At the measured +4.1 ROI points that is ~$6/day,
  and the honest conclusion flips: **there is no product decision pending on
  caps, and the correct next step is to SCORE the entry-cost edge rather than
  raise limits.**
- **A subagent made the identical error independently** (`ad693c3bcf7d4aad5`),
  reporting "measured on the live-armed executor: `MAX_ORDER_DOLLARS=10`,
  `MAX_DAY_DOLLARS_KALSHI=50`". Two of us reading the same wrong source is not
  corroboration — **it is one error counted twice**, and it is why the figure
  survived a whole afternoon.
- **Three env vars were set today and are ALL INERT**: `SYNDICATE_BANKROLL_UNITS=1000`,
  `SYNDICATE_EXECUTION_MAX_ORDER_DOLLARS=25`, `SYNDICATE_EXECUTION_MAX_DAY_DOLLARS_KALSHI=200`.
  Stored wins over env on every one. **Nothing about execution behaviour changed
  today.** The user was asked to authorise a change that could not have taken
  effect.

## The lucky part, and it is luck rather than design

The env values set were *lower* than or equal to the stored ones in every case
that matters (25 < 35.01; 200 > 150.01 but stored wins anyway), and bankroll's
env value happened to equal the stored one. **Had the env values been higher AND
env governed, this session would have raised live spending limits on a wrong
premise.** The stored store is what prevented that, not any check of mine.

## The rule

**A cap, limit or flag has a RESOLVED value and a SET value, and they are
different objects.** Never quote a spending limit from `env-vars`; read the
endpoint that reports what the guard resolves, and read its `sources` map —
`execution_guard._stored_live_limit` consults the store BEFORE the env on every
call, freshly, by design.

Generalised: **when a value has more than one possible source, an instrument that
can only see one source cannot produce a negative result about the value.** It
can only report about its own source. This is the same shape as today's other
three instrument failures — a default `limit=300` read as a slate, `player` read
for `player_name`, and a log line that could not fire on a `stdout=DEVNULL`
child. Four in one session, all of the form *the reading was about the
instrument, not the system*.

## Owed

- The venue entry-cost scope (`findings_2026-09-09_venue_routing_scope.md`) and
  the deploy entries quoting "$50/day" and "5 orders" are wrong by this
  correction. They are superseded by this file rather than rewritten.
- The three inert env vars should be either removed or aligned to the stored
  values, so a future reader does not resolve the same contradiction again. **Do
  not simply delete them** — `_float_env` treats absent as "use default", and the
  defaults differ from both the env and the stored values.
