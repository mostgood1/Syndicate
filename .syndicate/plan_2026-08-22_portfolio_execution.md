# Plan — from Layer 2 shortlist to a committed portfolio, and then to placed bets

> Lane `portfolio-decision-and-execution`, opened 2026-08-22.
> Written from a read of the code, not of the plan docs. Every claim below
> carries a file:line or a dated measurement; anything I could not verify is
> marked UNVERIFIED rather than smoothed over.

## What this is

A staged path with four stages (A-D) and a hard precondition. Each stage ships
and is measured on its own; **no stage's acceptance reading is the previous
stage's deploy.** Stage D is the only one that touches real money and it is
gated on Stage C's reading, not on Stage C's existence.

## What this is NOT

- Not a proposal to automate placement at DraftKings / FanDuel / BetMGM /
  Caesars / Fanatics. None of them has a betting API; the only route is driving
  their client, it breaches their terms, and the realistic outcome for an
  account detected as bot-driven and +EV is limiting, closure and a frozen
  balance. Ruled out on account-risk grounds at the top so no later stage
  quietly reintroduces it.
- Not a change to how candidates are RANKED. `_SCORE_SIM_WEIGHT` stays 0.0
  until settlement says otherwise (below). Sizing and selection are downstream
  of ranking and can be built without touching it.

---

## THE PRECONDITION — S6, and why it is not negotiable

Three separate readings say the same thing: **nothing on this board has been
scored against outcomes yet.**

| reading | where | value |
|---|---|---|
| sim contribution to the ranking | `opportunity_signals.py:390` | `_SCORE_SIM_WEIGHT = 0.0` |
| `sim_component` non-zero on served rows | measured 2026-08-16T16:20:21Z | **0 of 65** rows carrying `model_edge_pct` |
| settled records written in production | `todo.md #504`, measured 2026-08-22 | **zero** — the write path is unexercised |
| `settled_count` on `/api/portfolio/summary` | `todo.md #502` | `0`, `avg_clv: null` |

And the sizing already knows it. `compute_board_stake`
(`bankroll_manager.py:192`) shrinks every stake by
`_sample_credibility(settled_sample_size)`, which returns
`_MIN_SAMPLE_CREDIBILITY = 0.25` whenever the sample is zero — which is every
market today. Combined with `_DEFAULT_KELLY_MULTIPLIER = 0.25`, **every stake
currently on the board is 1/16th Kelly by construction**, and it is 1/16th
because the system correctly does not believe itself yet.

`_SAMPLE_SIZE_FOR_FULL_CREDIBILITY = 50`. That is the number that has to become
real per market before any of this sizing means anything.

**The governing rule** (`learnings.md`, 2026-08-20, "ONE ERROR IN FIVE
GUISES"): *before building anything, ask what the number is measured AGAINST.
If it is not the quantity the model is judged on — realised outcomes, in bets,
at the unit you would actually wager — it is a screen, never a substitute.*
An automated placer built on an unsettled board is that error at its most
expensive: it converts a screen into money at machine speed, and the loop that
would tell you it is wrong is the loop that is not closed.

**Precondition, stated as a reading, not as a task:**
`/api/portfolio/summary` returns `settled_count > 0`. That is
`portfolio-ledger-service-split`'s outstanding verify (deployed `2aa1df54`
2026-08-22T17:00Z, reconciliation is daily-gated and had not run under the new
code as of the lane's last note). **Stages A-C do not wait on it. Stage D
does.**

---

## A FINDING THAT CHANGES THE STORAGE DESIGN — there is nowhere durable to put a money ledger

Checked, not assumed:

- `render.yaml` declares **no Postgres and no database of any kind.** Three
  services (`syndicate` web, `refresh-worker`, `live-odds-worker`), three
  SEPARATE 50GB disks, one `keyvalue` instance `syndicate-refresh-state`.
- Separate disks are exactly what `#502` root-caused: the bet slip writes on
  web, reconciliation reads on refresh-worker, `SYNDICATE_DATA_ROOT` is the
  same string on both and resolves to two different files.
- So the only cross-service store is the keyvalue instance — and
  `refresh_state_store.py:139-205` documents it as **one shared 256MB Redis on
  the starter plan, measured at 96% memory with 34,529 LRU-evicted keys and a
  44% keyspace miss rate**, running `allkeys-lru`. A later sweep (2026-08-10)
  found 38,865 keys already evicted.
- `_default_keyvalue_ttl_seconds` (`refresh_state_store.py:218`) gives any path
  containing a date token a **10-day TTL**.

**Two consequences, and the second is the serious one.**

1. An execution ledger keyed by date (`execution_ledger_2026-08-22.json`) would
   be handed a 10-day TTL automatically. A record of money placed must not
   expire. So the ledger path must carry **no date token** — or must not go
   through this store at all.
2. `allkeys-lru` evicts ANY key under pressure, including keys with no TTL.
   `prediction_ledger.json` has no date token, so it takes no TTL — but on a
   96%-full instance running allkeys-lru it is still **evictable**. That is not
   my lane's file (`portfolio-ledger-service-split` holds
   `prediction_ledger.py`) and I have not edited it. **Surfaced, not fixed** —
   see OPEN QUESTIONS.

**UNVERIFIED:** I have not measured current Redis memory or eviction counts;
the 96% / 34,529 / 38,865 figures are the store's own dated comments from
2026-07-31 and 2026-08-10, not a reading taken today. A reading should be taken
before Stage B chooses its storage.

**What this means for the plan:** Stage B's storage is an open decision with
three candidates, none free — (i) a non-date-scoped keyvalue path, cheapest and
weakest, still LRU-evictable; (ii) the artifact publisher's HTTP path
(`artifact_publisher.py`) plus a `HOT_ARTIFACT_PATTERNS` allowlist entry, which
is how every other cross-service artifact travels; (iii) a real Postgres, which
is a `render.yaml` change and therefore a `blueprint_sync` that rewrites the
whole env block on all three services and 502s every route for ~2 minutes
(CLAUDE.md `#284`, measured 2026-08-08). **(iii) is the only one that is
actually durable, and it is the one with a production blast radius.** Decide
before building, not during.

---

## STAGE A — `portfolio_commit`: turn a ranked board into a committed slate

**What is missing today.** The board computes per-candidate sizing
(`_attach_board_stakes`, `intelligence_state.py:4216`) and a per-game exposure
cap (`apply_exposure_budgets`, `intelligence_state.py:4857` →
`bankroll_manager.py:249`, `_DEFAULT_GAME_EXPOSURE_CAP = 0.05`,
`_CORRELATED_LEG_DECAY = 0.5`). What it does not compute is a **decision**:
there is no bankroll figure, no slate-level exposure ceiling, no cut line, and
no closed list. The board says "here are 108 rows, each with a suggested
fraction." A portfolio says "these 9, at these dollars, totalling this."

### TWO CORRECTIONS TO THIS PLAN, both found while building Stage A

**1. `_attach_board_stakes` does NOT reach the Layer 2 shortlist.** This
document originally said Stage A "consumes `stake`, `stake_fraction` … already
on each row". That is true of Layer 1's `global_pool` and **false of the Layer 2
shortlist**, which `build_layer2_shortlist` builds separately from the market
grid as a different set of row objects. Verified by reading every
`candidate["…"]` assignment in `layer2_board.py`: a shortlist row carries
`side`, `line`, `quote`, `game`, `projection`, `movement`, `ev_pct`,
`model_edge_pct`, `score`, `board_lane` — and no sizing fields at all.

Left unhandled that is not a small bug. `compute_bet_size` answers a row it
cannot read with `model_probability 0.5`, `implied_probability 0.5`, `edge 0`,
**`stake $0` for every position** — no exception, no log line — so the portfolio
would have been empty and would have looked exactly like a quiet slate. Stage A
therefore derives its sizing inputs explicitly (inverting `expected_value_pct`
to recover the market probability, then adding `model_edge_pct`), refuses by
name when an input is absent, and is gated by
`scripts/portfolio_commit_input_checklist.py`.

**2. `confidence` is structurally inert in `compute_board_stake`, so the price
reliability discount had to be applied separately.** The first implementation
passed the row's `price_reliability` in as the sizer's `confidence`. The
checklist caught it as unconsumed on its first run. Measured 2026-08-22:

    kelly_fraction 0.0241 -> stake 0.00151   (x0.25 Kelly, x0.25 credibility)
    cap_fraction   0.0446                    (0.02 + 0.03 x confidence)

`compute_board_stake` shrinks the RAW `kelly_fraction` and applies
`cap_fraction` only as a ceiling — and that ceiling sits ~30x above the stake,
so it never binds. Moving the trust weight 0.82 → 0.32 moved the cap
0.0446 → 0.0296 and moved the stake **not at all**.

**This is a property of `bankroll_manager`, not of the adapter**, so it is
equally true of `_attach_board_stakes` on the Layer 1 pool: whatever
`confidence` a board candidate carries, it does not move the served stake.
`bankroll_manager.py` is read-only for this lane — recorded, not fixed. Stage A
applies the discount as its own named multiplier and records both the factor and
the pre-discount fraction on every position.

**The general lesson, and why both are recorded here rather than only in the
code:** the checklist found in one run what a passing test suite would not have.
Two features, each plausibly wired, each inert — and the second was introduced
by me while fixing the first.

**Build:** `syndicate/features/shared/portfolio_commit.py`, worker-side, plus
`pipeline/portfolio_commit.py` as its runner.

- Input: `read_layer2_shortlist(selected_date)` (`pipeline/intelligence_state.py`),
  which is a pure `read_json_file` — no compute, per the note at
  `ask_the_syndicate_data.py:3448`.
- **Derives** its four sizing inputs per row (see correction 1) rather than
  reading them off it. **Reads `bankroll_manager.py`; does not edit it.**
- Adds what does not exist: a bankroll (**$1,000**, user decision 2026-08-22,
  editable on `/portfolio`), a slate-level total-exposure ceiling, a minimum-EV
  cut line, a max-positions count, and a minimum placeable stake.
- Output: `portfolio_plan_{date}.json` — a closed list, each entry carrying
  `position_key`, side, line, book, price at decision time, `stake_dollars`,
  and the full sizing breadcrumb (`kelly_multiplier`, `sample_credibility`,
  `settled_sample_size`, `price_reliability_factor`, `slate_scale_factor`) so
  the number is inspectable rather than trusted.
- **Request-path refusal is mandatory**: `refuse_if_compute_in_request_path`,
  same as `_build_candidate_pool`. Two reasons, and `layer2_board.py`'s header
  states the stronger one — *a board computed per request cannot be settled*.
  A portfolio computed per request cannot be settled either, and a portfolio
  that cannot be settled cannot be graded, which makes Stage C impossible.

**Acceptance:** `portfolio_plan_{date}.json` exists for a real slate, its
entries sum to exactly the declared exposure, and every entry traces to a
shortlist row by `candidate_id`. Reachability first (`off != on`): the plan
file must be ABSENT with the job disabled and PRESENT with it enabled, on the
same date. A test that cannot fail cannot pass (`learnings.md`, 2026-08-16) —
so the test asserts the denominator: N shortlist rows in, K committed, K < N,
and a named reason for every dropped row.

**Cost: low. No new data, no new model, no deploy risk beyond a worker job.**

---

## STAGE B — the execution ledger, running on paper

**The point of paper mode is not caution theatre.** It is that the paper path
and the live path must be the SAME code with one boolean between them, so that
going live is a flag flip and not a rewrite. A paper harness that differs
structurally from the live one proves nothing about the live one.

**Build:** `syndicate/features/shared/execution_ledger.py`.

- Every commit from Stage A produces an **order record**: `candidate_id`,
  venue, market, side, line, requested price, requested stake, submitted-at,
  status, fill price, fill stake, and an **idempotency key**.
- `mode = paper | live`, default `paper`, honoured at the single point where an
  order is submitted. In paper mode the "fill" is the price that was available
  at decision time; nothing leaves the process.
- Storage per the finding above — decided, then allowlisted in
  `HOT_ARTIFACT_PATTERNS` if it travels by the publisher. **A local cache
  cannot reach Render** (CLAUDE.md, model engine standard).

**Idempotency is the load-bearing safety property, not a nicety.** The placer
must never run inside `refresh-worker`: that service has a documented OOM-kill
history (110 kills on 2026-08-07) and restarts mid-job. A restart between
"order submitted" and "order recorded" double-places. So: claim-before-work
(`#256`'s pattern — a death mid-pass advances the epoch instead of hot-looping),
an idempotency key derived from `(candidate_id, venue, date, sequence)`, and a
write-ahead record BEFORE the submit call, never after.

**And the identity discipline is a repo rule already.** `learnings.md`: *a
wrongly resolved join prices a projection against a different human being,
which is worse at any stake than no bet* — written about the 2.4% short-name
collision that produced a fake `anytime_td +125% ROI`. An order keyed on a
label rather than an identity is the same failure with money attached. The key
is an identity or the stage does not ship.

**Acceptance:** replay a real slate end to end in paper mode; the ledger's
committed dollars equal the plan's, every order carries a distinct idempotency
key, and a deliberately re-run job produces **zero** additional orders. That
last one is the test that matters and it must be written to fail on the
pre-fix code.

---

## STAGE C — the acceptance gate: CLV, not ROI

**ROI over a slate is noise at any sample this system will have this season.
CLV is the only thing that answers "is the edge real" quickly enough to gate
on.** The machinery exists: `clv_opening_ledger.py`, `clv_join.py`, and
`POST /api/portfolio/bets` already stamps the opening price across every book
quoting it (`intelligence.py:2062-2081`) precisely because *unrecorded here is
unrecoverable*.

- Run Stage B in paper for a real, dated window. State the window and the
  number of dates it actually rests on — CLAUDE.md's coverage rule applies
  ("report the number of dates the result actually rests on"), and the git
  `data/**` mirror is not evidence about production.
- Per-market, not pooled. `_SAMPLE_SIZE_FOR_FULL_CREDIBILITY = 50` is per
  market for a reason, and pooling would repeat the "rows ≠ bets" error that
  overstated significance 3.4× (`learnings.md` 2026-08-20).
- Include a positive control, per the same entry. Without one, a null means
  nothing.

**Gate:** a market passes when its paper orders beat the closing line over a
sample stated with its own CI. Markets that do not pass do not get placed —
not "get placed smaller."

**This is also the stage that unblocks `_SCORE_SIM_WEIGHT`.** Not before.

---

## STAGE D — real money, one venue, hard caps

Only markets that cleared Stage C. Only after the S6 precondition reads
`settled_count > 0`.

**Venue.** The only US-legal venues with real order APIs are exchanges and
prediction markets: **Kalshi** (CFTC-regulated, documented REST + WebSocket
trading API, all 50 states), **Sporttrade** (exchange, limited states),
**ProphetX** and **Novig** (peer-to-peer). Non-US: Betfair, Smarkets,
Matchbook. Pinnacle's API exists but through partner/agent arrangements.

**Kalshi first**, on three grounds: a real documented API, no terms problem, and
no account-limiting risk — an exchange does not limit you for winning.

**The honest catch, stated so it is not discovered later.** Those venues are
mostly moneyline / spread / total on major games. `layer2_board.py`'s own
header says props are where the sim differentiates and where **95.5% of the
OddsAPI spend** goes. **So the markets that can be legally automated are
largely not the markets this board is best at.** That is a real limit on the
ceiling of this whole plan and it should inform whether Stage D is worth
building at all — a question worth answering with Stage C's per-market numbers
rather than in advance.

**Non-negotiables for Stage D:**

- Its own service. Never inside `refresh-worker`.
- Per-order, per-day and per-slate dollar caps, all absolute, all read from env.
- A kill switch env var that is checked immediately before every submit, not at
  startup.
- Reachability test before correctness tests (`off != on`), per the model
  engine standard.
- A daily reconciliation of ledger orders against the venue's own position
  list. **The ledger is a record, not evidence** (`lanes.md`, 2026-08-17) — the
  venue is the source of truth about what was actually placed, and any
  divergence halts the placer.

---

## Deliberately NOT in scope

- Retail-book automation, on the grounds at the top.
- Any change to `layer2_board.py`, `pipeline/layer2_shortlist.py`,
  `syndicate/blueprints/ops.py` or `syndicate/templates/intelligence.html` —
  held by `layer2-sim-view-and-live-projection`.
- Any change to `syndicate/features/prediction_ledger.py` — held by
  `portfolio-ledger-service-split`.
- Raising `_SCORE_SIM_WEIGHT`. Gated on Stage C.
- Parlays. `bankroll_manager`'s correlation handling exists
  (`_CORRELATED_LEG_DECAY = 0.5`) but a correlated multi-leg product is a
  different sizing problem and mixing it in would make Stage C unreadable.

## Open questions — need a decision, not an assumption

1. ~~**Bankroll.**~~ **ANSWERED 2026-08-22: $1,000**, user decision, and
   user-editable — `DEFAULT_BANKROLL_UNITS` in `portfolio_settings.py`, a form
   on `/portfolio`, and `GET`/`POST /api/portfolio/settings`. Precedence is
   stored > env > default, and **every read is fail-safe toward the default**:
   the store is a 256MB `allkeys-lru` instance that evicts, and a bankroll
   resolving to 0 would size every bet at $0 and look exactly like a quiet
   slate. `sources` reports per field which layer won, so "you set this" and
   "the store lost your edit" stay distinguishable.
2. **Storage for the execution ledger** — the three candidates above. (iii)
   Postgres is the only durable one and costs a `blueprint_sync` against all
   three services.
3. **Is Stage D worth building**, given that the automatable venues are
   thinnest exactly where the board claims its edge? Answerable from Stage C's
   per-market output; do not answer it now.
4. **`prediction_ledger.json` is LRU-evictable** on a 96%-full allkeys-lru
   instance. Not my lane's file. Belongs to
   `portfolio-ledger-service-split`, flagged here rather than edited.

## Order of work

    S6 precondition (another lane's verify)  ─────────────┐
    Stage A  portfolio_commit ──► Stage B  paper ledger ──► Stage C  CLV gate ──► Stage D  live
                                                                                    ▲
                                                                                    └── gated on both

Stages A, B and C do not wait on the precondition. Stage D waits on both it and
Stage C.
