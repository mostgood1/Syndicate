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

### THE UNVERIFIED LINE IS NOW DISCHARGED, AND IT REVERSES THE CONCLUSION

**Measured 2026-08-22T19:0xZ via the Render API, 24h at 1h resolution on
`red-d88bvljbc2fs73epfhhg`:**

| | ledger's dated figure | measured today |
|---|---|---|
| memory | 96% | **36.6%** — 98.2 MB of 268.4 MB |
| 24h range | — | 83.5–118.1 MB, i.e. **31–44%** |
| headroom | ~10 MB | **~170 MB** |
| evicted keys | 34,529 (07-31), 38,865 (08-10) | not reachable via the metrics API; **at 37% of maxmemory nothing is being evicted** |

`#324`'s `migration_runs/` exclusion did what it was built to do — it reclaimed
the 211 MB backlog and the store has stayed in the low-40s ever since. **The 96%
figure describes a state that has not held for two weeks**, and it was about to
drive a Postgres decision with a three-service `blueprint_sync` blast radius.

Also read off the live instance and NOT previously recorded anywhere:

- `persistenceMode: journal_snapshot`. **This store is not a pure cache** — it
  journals and snapshots to disk. That is a materially different durability
  story from the one "it's a Redis cache" implies.
- `maxmemoryPolicy: allkeys_lru`, Redis 8.1.4, plan `starter`.
- **`maxmemoryPolicy` is NOT declared in `render.yaml`.** So changing it is a
  dashboard/API edit, NOT a `blueprint_sync` — and it cuts the other way too: a
  future sync could reset it, since the blueprint does not pin it.
- **No Postgres instance exists in the account at all** (`list_postgres_instances`
  → none), confirming the blueprint read.

### THE DECISION, revised on that measurement

**Postgres is not needed for Stage B.** Option (iii) was only compelling
against a store at 96% with no headroom; against 170 MB of headroom with journal
persistence it is a `blueprint_sync` bought for very little.

**Recommended, in order of leverage:**

1. **`allkeys_lru` → `volatile_lru` on `syndicate-refresh-state`.** One setting,
   no deploy, no sync, no code change. It makes the eviction policy match the
   TTL discipline the code already has: date-scoped keys carry TTLs and stay
   evictable; keys with no TTL — the bankroll, the execution ledger,
   `prediction_ledger.json` — become **structurally un-evictable** rather than
   merely un-evicted at current usage. Render supports the value. **This is a
   production change and is the user's call, not mine.**
   *Caveat to state with it:* because the blueprint does not declare the policy,
   a future `render.yaml` sync may reset it to the default. Pinning it in
   `render.yaml` is itself a sync, so the two should be done together and
   deliberately, or the policy re-checked after any sync.
2. **No date token on anything that must not expire.** Already implemented and
   pinned by a test for the settings path; Stage B's ledger inherits the rule.
3. **Verify the write landed.** `update_settings` now reads back what it wrote
   and reports `write_not_durable` rather than returning "saved" — a write that
   raises is easy, a write that returns cleanly and does not land is the one
   that costs you.
4. **Belt-and-braces disk mirror for the Stage B ledger**, via the artifact
   publisher and a `HOT_ARTIFACT_PATTERNS` entry, so a lost key is recoverable
   rather than fatal. Worth it for the money record; not worth it for settings.

**Still UNVERIFIED:** the actual `evicted_keys` / `keyspace_misses` counters.
The metrics API exposes memory, not Redis INFO, so "nothing is being evicted" is
an inference from 37% occupancy against maxmemory rather than a direct read. It
is a sound inference and it is not a measurement.

**Superseded by the measurement above** — kept because the reasoning is still
the right shape, only its inputs were wrong. The three candidates were (i) a
non-date-scoped keyvalue path, (ii) the artifact publisher plus a
`HOT_ARTIFACT_PATTERNS` entry, (iii) a real Postgres. On the 96% figure only
(iii) looked durable. On the measured 36.6% with journal persistence, **(i) plus
(ii) as a recovery mirror is sufficient**, and (iii)'s `blueprint_sync` blast
radius is avoided entirely.

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

## THE SIM'S ROLE — measured, and the premise needs correcting

**"Right now it's EV only" is true of RANKING and false of SIZING**, and the
difference decides what work is worth doing.

`_SCORE_SIM_WEIGHT = 0.0` means the simulation contributes nothing to which rows
reach the shortlist or in what order. But Stage A's stake is driven by
`model_edge_pct` — the sim's disagreement with the market — and **measured
2026-08-22 on a representative row** (`ev_pct 4.5`, `model_edge_pct 3.2`, -110,
reliability 0.82):

    stake with the sim's edge      0.003132   ($3.13 of $1,000)
    stake with the sim's edge = 0  0.001328   ($1.33) -- pure de-vig price edge
    the sim's share of the stake   57.6%

So **the simulation is already the majority owner of the money in a committed
position**, while contributing exactly nothing to the ranking.

**It is also what picks the side, because the ranking provably cannot.**
`opportunity_signals.py:352-390` states this outright: at weight 0.0
`blended_score` reduces to `ev_pct`, and EV against a proportional de-vig is
`1/overround - 1` — **identical for every side of a market**. The shortlist
therefore orders markets by hold and breaks ties arbitrarily (its opening
production state: Famalicao/Estoril at `ev 8.6383` on draw -750, home +4500 and
away +6000 alike). What actually chooses a side is Stage A's refusals: the wrong
side sizes to zero Kelly and is dropped as `zero_kelly_stake`.

### CORRECTION — "the board is running at 0% sim" is RIGHT, and my 57.6% was not about the board

**Flagged by the user 2026-08-22. The 57.6% above is a property of Stage A's
sizing, on a SYNTHETIC row, in code that is NOT DEPLOYED.** It describes nothing
that is running. The board is at 0% sim and that is correct.

It is also **structurally guaranteed, not a data outage**, which is the part
worth being precise about. `blended_score` emits
`sim_component = _SCORE_SIM_WEIGHT * value_sim` (`opportunity_signals.py:607`).
With the weight at 0.0 that is `0.0` for every row that HAS a sim view and
`None` for every row that does not:

    value_sim  12.0  -> sim_component  0.0
    value_sim  -5.0  -> sim_component -0.0
    value_sim  None  -> sim_component  None

It can never be non-zero. So "0% sim" is true, permanent under this constant,
and **says nothing about whether the sim produced anything.**

**It did.** Production `refresh-worker` logs, build 2026-08-22T19:20:09Z,
`LAYER2_SHORTLIST date=2026-08-22 rows=323 considered=17205 sports=[mlb, nfl,
soccer, wnba]`:

    PREGAME_PROJECTION_JOIN  mlb      considered  2,656   projected  2,279  (86%)
    PREGAME_PROJECTION_JOIN  wnba     considered    391   projected    374  (96%)
    PREGAME_PROJECTION_JOIN  nfl      considered  1,309   projected  1,010  (77%)
    PREGAME_PROJECTION_JOIN  soccer   considered 20,016   projected 10,686
                                                          with_prob  9,896  (49%)

So the simulation is attaching projections to most of the board. **The ranker
multiplies all of it by zero.** The sim is not missing, not broken, and not
starved — it is deliberately unused, which is a different problem with a
different fix.

The closest thing to a served-row measurement remains the ledger's
2026-08-16 reading: **65 of 108 rows carried `model_edge_pct`, and
`sim_component` was non-zero on 0 of them.** Those two numbers together are the
whole story.

**UNMEASURED, and I could not measure it this session:** the sim's share of a
stake on REAL rows. That needs the served shortlist, and the agent proxy 403s
`syndicate-an21.onrender.com` (as `state.md` records), so no production artifact
was readable. The 57.6% is a synthetic row and must not be quoted as production.
**Stage A now reports `sim_coverage` on every run** — `rows_with_sim_edge`,
`rows_without_sim_edge`, `share_with_sim_edge` — so the first production commit
answers it as a number instead of an inference, alongside the per-position
attribution.

### SUPERSEDED 2026-08-22 by a user decision — the weight WAS raised, with a cap

**The section below argued against raising `_SCORE_SIM_WEIGHT`. The user asked
for it directly and that is their call.** What shipped is not the thing this
section argued against, though, and the distinction is the whole point:

- **A bare weight was never the answer, and the argument below is right about
  that.** It scales with the edge, so a large enough disagreement always wins
  eventually — 0.25 fails exactly like 0.5, just later.
- **What shipped is a weight PLUS A HARD CAP** (`_SCORE_SIM_WEIGHT = 0.125`,
  `_SCORE_SIM_CAP_PCT = 1.5`) — the same structural treatment the movement term
  in the same file already had, and which its own comment recommends for
  precisely this failure: *"a cap is the STRUCTURAL fix for it rather than a
  smaller number that fails the same way later."*
- **Measured against the distribution that caused the zeroing**
  (`scripts/score_sim_weight_impact.py`): 0.5 uncapped promotes **286/286**
  negative-EV rows; 0.125-capped promotes **0/286** and still separates sides.
  `ev -5, edge +12` goes `+1.00` at 0.5 and `-3.50` capped.
- Reversible without a deploy: `SYNDICATE_SCORE_SIM_CAP_PCT=0.0` restores the
  old behaviour exactly.

**Everything below still holds about what this does NOT establish.** It is a
screen against an arithmetic failure, not evidence the sim is right. Full
working: `todo.md #508`.

### The original argument, kept because it is still the reason the cap is needed

That constant's own comment already argues this, and it is right:

> *"There is NO value of this constant that produces a credible recommendation
> board, because the missing input is `settled > 0`, not a coefficient. 0.5
> grants authority we have not earned; 0.0 grants none and leaves a board that
> cannot discriminate. Both are bad; only one is bad honestly."*

It was zeroed because at 0.5 the sim term DOMINATED — `ev_pct ~ -5` against
`model_edge ~ +12` across four independent market families, 286 of 300 rows — so
the board was selecting *rows where an unvalidated model most disagrees with the
market*, which is the worst possible rule if the model is miscalibrated.
`opportunity_signals.py` is unclaimed by any open lane, so this lane COULD raise
it. It should not: nothing has changed about the evidence.

### What the comment asks for, and what Stage A now supplies

The unlock condition is stated exactly once and has never been met:

> *"TO RAISE IT AGAIN you need S6: `settled > 0` and **CLV decomposed BY
> COMPONENT**, so the EV term and the sim term can be compared on outcomes
> rather than on taste. That is what this constant's own comment below already
> demanded, and **what nobody has been able to supply**."*

Decomposing CLV by component requires knowing, per bet, **which component put
the money there** — and nothing recorded that, so the condition could never be
met however long settlement ran. `stake_attribution` in `portfolio_commit.py`
now records it on every committed position:

    stake_fraction            full, as committed
    stake_fraction_ev_only    the identical row re-sized with model_edge_pct = 0
    stake_fraction_sim_delta  the difference (SIGNED)
    sim_share_of_stake        delta / full
    side_picked_by            "simulation" when the EV-only counterfactual
                              would not have been a bet at all

The counterfactual is exact rather than estimated — re-size the same row with
the sim's edge zeroed and what remains is the pure de-vig price edge. Plan-level
totals carry `staked_dollars_sim_attributed`, `sim_share_of_staked`, and
`positions_where_sim_picked_the_side`.

**The delta is deliberately NOT clamped at zero.** A small negative sim edge
still clears Kelly on a good enough price, so the sim can legitimately SHRINK a
position without vetoing it. Clamping would credit the sim only where it helps,
which is how a component gets credited for an edge it does not have.

Worked example, three rows, $1,000 bankroll:

    e3  ev 6.0  sim 0.5   $2.06   ev-only $1.77  sim $0.29   14.0%  side: price
    e1  ev 4.5  sim 3.2   $3.13   ev-only $1.33  sim $1.80   57.6%  side: price
    e2  ev -1.0 sim 6.0   $3.08   ev-only $0.00  sim $3.08  100.0%  side: SIM
    ----------------------------------------------------------------------
    staked $8.27 | sim-attributed $5.17 (62.5%) | sim picked the side on 1 of 3

`e2` is the case that matters: a position that exists **only** because the model
said so. When settlement lands, those are the bets whose CLV answers whether the
sim has an edge — and until then they are exactly the bets to be most careful
about.

### So the order of work is unchanged, and now unblocked

1. `#502`/`#504` land settlement → `settled > 0`.
2. Stage C joins CLV against `attribution`, per component, per market.
3. **Then** `_SCORE_SIM_WEIGHT` moves on a number instead of on taste — or
   stays at 0.0 on a number, which is an equally good outcome and a far better
   one than today's "nobody could ever check".

**One thing that follows immediately, independent of settlement:** the comment
insists that at weight 0.0 the board "must NOT be presented as *our model found
these*". That is correct for the SHORTLIST. It is not correct for the PORTFOLIO
— a committed position is sim-sized and sim-sided, and `sim_share_of_stake` says
by how much, per bet. The `/portfolio` surface may say so; the Layer 2 board
still may not.

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
