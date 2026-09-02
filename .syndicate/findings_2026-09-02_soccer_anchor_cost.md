# Soccer market-anchoring: the cost/accuracy tradeoff, measured

Lane `soccer-anchor-cost`, session `b2b5b45b`, 2026-09-02. **Nothing was armed.**
`SYNDICATE_SOCCER_MARKET_ANCHOR_WEIGHT` is still absent on every service (read
live this session), which resolves to `0.0` — off.

---

## The headline

**The blocker as posed does not exist at the size posed, and the reason is a
denominator error.** The 84-fixture / 57-min and 200-fixture / 136-min figures
count **priced EVENTS in the odds file**, which is a forward book running out to
13 days. The anchor never sees that list. `build_artifacts` calls
`_fetch_fixtures(league, iso_date)` for **one date**, and `attach_market_odds`
attaches only to those fixtures, so `anchor_ratings_to_market` iterates a
single-date fixture list.

Path (b) — "anchor only what matters" — is therefore **already how the code
works**, and paths (b) and (c) are largely already built. What remains is a real
but much smaller cost, and two problems that are not about cost at all.

---

## What production actually runs

Read live off the Render API this session (allowlisted keys only):

| key | refresh-worker | web | live-odds-worker |
|---|---|---|---|
| `SYNDICATE_SOCCER_SIM_HORIZON_DAYS` | **7** | absent | absent |
| `SYNDICATE_SOCCER_WEEKLY_REFRESH_INTERVAL_SECONDS` | **14400** (4h) | absent | absent |
| `SYNDICATE_SOCCER_MARKET_ANCHOR_WEIGHT` | **absent → 0.0 (OFF)** | absent | absent |

The horizon is **7**, not the code default of `1` — so the unit list is every
in-season league × every fixture date within 7 days. Units are launched **one at
a time as detached subprocesses** (`ops_refresh.py:1407`,
`DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP`), spaced
`interval // unit_count` seconds apart, each refreshing on its own 4h clock.

**So the work is already off the tick, already per-fixture-scoped, and already
memory-isolated** (observed unit cost ~105MB, 41-66s). Path (c)'s "job plumbing"
exists.

---

## The real cost, measured on production rather than inferred

The anchor wiring **is live on refresh-worker** (`e4a471c0`, finished
2026-09-02T19:26:44Z), so production is already emitting the unit telemetry. All
of the following is read off it, not modelled.

### The unit cadence, from `SOCCER_UNIT_*` log lines

```
SOCCER_UNIT_LAUNCHED league=epl unit_date=2026-09-06 scope_kind=league_date unit=1/43 due=13 ...
SOCCER_UNIT_CONFIRMED unit=epl|2026-09-06 wrote_at=1788379211 launched_at=1788379096
```

**43 units**, `due` 9-13 at any tick, launched one at a time ~300-360 s apart
(`14400 // 43` = 335 s). Actual runtimes, from `wrote_at − launched_at`:

| unit | fixtures | runtime |
|---|---|---|
| mls\|2026-09-06 | 0 | 4 s |
| la_liga\|2026-09-06 | 4 | 109 s |
| bundesliga\|2026-09-06 | 2 | 110 s |
| epl\|2026-09-06 | 2 | 115 s |
| ligue_1\|2026-09-06 | 3 | 158 s |
| serie_a\|2026-09-06 | 4 | 185 s |

Least squares over those six: **unit runtime = 27 s overhead + 35 s per
fixture.** The build's own per-fixture cost is therefore the *same order* as the
anchor's 40.9 s — **anchoring roughly doubles a soccer unit**, it does not add
an order of magnitude to it.

### How many fixtures actually pay

Production recommendation artifacts across the live horizon (d+0…d+7):
**42 units carrying fixtures, 136 fixtures total** — matching the log's 43.

But the anchor only solves for fixtures that get `market_odds` **attached**.
Running `attach_market_odds` exactly as `_apply_market_anchor` does, over every
production unit against the production odds CSVs:

    TOTAL over the live horizon: fixtures=136  ATTACHED=66  skipped=70

| | fixtures | anchor cost / 4h interval |
|---|---|---|
| built | 136 | — |
| **priced and attached today** | **66** | **45.0 min** |
| build's own cost today (43 × 27 s + 136 × 35 s) | | 98.7 min |

**45 minutes of extra compute per 4-hour interval on one core, not two hours.**
The brief's 57 / 136 min came from counting priced EVENTS in a forward book that
runs to d+13; the builder is single-date and only half its fixtures are priced.

### Where it does bind: the launch slot

| | units over the 335 s slot |
|---|---|
| today, no anchor | **3 of 42** (mls\|09-05 and mls\|09-09 at 517 s, championship\|09-05 at 412 s) |
| with the anchor | **6 of 42** |

Overrunning is not a failure — the launcher refuses to stack
(`_soccer_autorun_skipped("active_job", …)`), so an over-long unit delays the
next rather than overlapping it. The consequence is cadence: the full 43-unit
pass stretches past 4 h and units refresh more slowly than the interval claims.
**And 3 units already overrun today**, so this is a pre-existing condition the
anchor worsens, not one it creates.

**Memory is not the constraint.** `ALL_PROCESS_MEMORY` on refresh-worker,
2026-09-02T20:26:34Z: `container_memory_unreclaimable_mb = 1710.2` of 4096
(41.8%). The solver allocates one match simulation at a time and discards
everything but the final score, so it adds CPU, not resident set. The `#241`
restart loop and today's OOM are about memory; this is not that shape of work.

## Two problems that are not about cost

### 1. The anchor is silently inert on 40% of team slots

`anchor_ratings_to_market` resolves a fixture to its rating with a plain
`anchored.get(home_team, {"attack_rating": 0.0, "defense_rating": 0.0})` — **no
`match_team_name`**, unlike `_fill_promoted` immediately above it in the same
build and unlike `_rating_for`, which is what the sim uses.

Fixture names come from ESPN; rating keys come from Understat / football-data.
Replicating `build_artifacts`' exact order (`_fill_promoted` **then**
`_apply_market_anchor`) against the real production fixture list for
**2026-09-05, 9 leagues, 90 team slots**:

| league | team slots | anchor reaches | silently inert |
|---|---|---|---|
| epl | 14 | 10 | 4 |
| la_liga | 6 | 5 | 1 |
| serie_a | 6 | 4 | 2 |
| bundesliga | 12 | 8 | 4 |
| ligue_1 | 6 | 4 | 2 |
| eredivisie | 8 | 4 | 4 |
| primeira_liga | 8 | 5 | 3 |
| championship | 22 | 13 | 9 |
| belgian_pro_league | 8 | 1 | **7** |
| **total** | **90** | **54 (60%)** | **36 (40%)** |

`_fill_promoted` covers the no-match teams (it adds an ESPN key with the
promoted prior). The 36 are the **fuzzy-match** teams — `AFC Bournemouth` vs
`Bournemouth`, `Internazionale` vs `Inter`, `1. FC Union Berlin` vs
`Union Berlin`. For those the anchor writes a **new spurious key** built on a
`0.0/0.0` default rating.

It is **inert, not corrupting** — and that is provable rather than lucky.
`match_team_name` returns on the first exact canonical match in candidate order,
`anchored` is built as a copy of `ratings` so the real key always precedes the
spurious one, and the sim therefore resolves back to the real rating. Verified
end to end:

```
BEFORE  ratings["Bournemouth"] attack= 0.0751
AFTER   new keys created: ['AFC Bournemouth', 'Brighton & Hove Albion']
        out["AFC Bournemouth"] attack= 0.0862  defense= 0.0
        sim resolves _rating_for("AFC Bournemouth") -> attack= 0.0751 defense= 0.0158
        >>> unchanged
```

**And the instrumentation reports it as success.** `teams_changed` counts entries
that differ from the input dict, which the spurious keys do:

```
[soccer_anchor] ANCHORED league=epl weight=0.4 teams_changed=2 of 25
teams the SIM reads whose rating actually changed: 0
```

This is the repo's own "presence ≠ reachability" failure, in the one counter
built to catch it. **It must be fixed before any weight above 0.0 is set**, or
the first production reading will be unattributable.

### 1a. The anchor's entire instrumentation is written to `/dev/null`

`ops_refresh.py:1402-1403` launches every refresh unit detached with
`stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL`. `build_soccer_artifacts.py`
runs as that child, so **nothing it prints reaches Render's log collector** —
including every `[soccer_anchor]` line.

Discriminating control, one read of the Render logs API over the same window in
which seven soccer units demonstrably ran and wrote artifacts:

| token | printed by | matches |
|---|---|---|
| `player projections` | **child** `build_soccer_artifacts.py` | **0** |
| `soccer_anchor` | **child** `build_soccer_artifacts.py` | **0** |
| `SOCCER_PLAYER_ROWS_MISSING` | **child** `build_soccer_artifacts.py` | **0** |
| `SOCCER_UNIT_LAUNCHED` | parent `run_refresh_worker.py` | 5 |

`player projections` prints on every successful unit, and the units succeeded
(`SOCCER_UNIT_CONFIRMED` × 7 in that window) — so this is not "the anchor did not
run", it is "no child output is collected at all". The search itself works; the
parent's lines come back.

**So `ODDS_ATTACHED`, `ANCHOR_SKIPPED` and `ANCHORED teams_changed=… elapsed_s=…`
are unreadable in production as built.** Lane `soccer-anchor-wiring`'s stated
verification — *"anchored/skipped counts published per league-date"* — is not
satisfiable through logs. Combined with §1, the anchor can be 40% inert and the
one counter designed to reveal that is both wrong *and* invisible.

The fix is not a log line: it has to be a **published artifact field** (the
recommendations JSON already carries `promoted_prior_teams` and `simulations` —
an `anchor` block belongs beside them), which the export endpoint can then read.

### 1b. The SAME missing name normalisation, one hop earlier, costs 41% of fixtures

`attach_market_odds` joins a fixture to a priced event by `match_id`
(an **ESPN** event id) against the odds file's `event_id` (an **OddsAPI** id) —
two different id spaces that never collide — then falls back to an **exact
string compare** on both team names. So the join lives or dies on the same name
convention the rating lookup does.

Of the **70 skipped fixtures**, testing each against every priced event with the
codebase's own `match_team_name`:

| | fixtures |
|---|---|
| skipped but reachable by a fuzzy name match | **56** |
| genuinely not priced by any book | **14** |

```
belgian_pro_league: 'Sint-Truidense v Union St.-Gilloise'  ==  'Sint Truiden v Union Saint-Gilloise'
belgian_pro_league: 'Royal Charleroi SC v Union St.-Gilloise'  ==  'Charleroi v Union Saint-Gilloise'
belgian_pro_league: 'KAA Gent v OH Leuven'                  ==  'Gent v Leuven'
```

(Method caveat: each candidate was tested pairwise against the fixture, requiring
BOTH team names to clear the threshold. That makes a false pair unlikely but it
is not the same as a best-match-over-all-candidates join, which is what a real
fix must implement.)

**This inverts the cost question.** Fixing both name joins takes the anchor's
reach from **66 → 122 of 136 fixtures**, and its cost from **45.0 → 83.2 min per
4-hour interval** — the correct anchor is nearly **twice as expensive as the
broken one**. Any cost target set against today's 45 min is a target for a
mechanism that is half switched off.

### 2. The validated evidence is thinner than the brief states, and is on the
### one market the audit says never to stake

From the source the brief cites
(`recovered_2026-07-20_soccersim_phase1_build_report.md:259-279`):

| weight | mean MAE vs held-out consensus | fixtures improved |
|---|---|---|
| 0.0 (baseline) | 0.0574 | — |
| 0.4 | 0.0345 (−40%) | 8/10 |
| 0.7 | 0.0282 (−51%) | 8/10 |

**n = 10 fixtures, one EPL opening-weekend slate, h2h only.** The report's own
words: *"a small sample (one slate, 10 fixtures) so the weight sweep is a
sensitivity check, not a tuned production default"*, and its outstanding-items
list still carries *"multi-week market-anchoring validation"*. The brief's
caution is right and is if anything understated: **every number ever measured
for this mechanism is an h2h market-agreement number**, and h2h is the market
the audit says not to stake.

What the staked surface actually looks like, one read of
`/api/board/layer2-shortlist?limit=2000` this session:

- soccer rows on the board: **99**, resolving to **58 distinct fixtures**
- `kind`: **`game` × 99. Zero prop rows.**
- markets: **h2h 73, totals 23, alternate_totals_corners 3**
- upstream, `per_sport.soccer` selects 1,434 rows of which **394 are props** —
  none reach the board

So the derivative markets the anchor is supposed to improve are **26 of 99 board
rows, and none of them are player props**.

Path (b) sizing, for completeness: scoping the anchor to fixtures that reach the
board is **117 → 58, a 50% cut**, not the order of magnitude hoped for — and it
is **circular**, because anchoring changes the projections that decide which
rows clear the board's filters.

---

## The §4.4 obligation, named concretely

`model_engine_standard.md` §4.4 is not a generic warning here. The specific rate
absorbing the anchor's absence is **`shot_calibration`'s shrinkage divisor**,
currently **1.3930** (re-fit 2026-09-01, lane `soccer-shot-shrinkage`). Its own
docstring says it was fitted by joining **archived `expected_shots` predictions**
to ESPN shot events — archived predictions produced with the anchor **off**.

Anchoring moves team attack ratings, which moves the **level** of
`expected_shots`. The divisor would keep applying the unanchored-era correction.
That is the measured-negative-interaction mechanism, and it is directly
measurable as the level ratio in M4 below.

---

## BOTH NAME JOINS FIXED, AND THE REACH REMEASURED

`[user instruction 2026-09-02: "fix both name joins and remeasure anchors reach"]`

Both joins now resolve through `match_team_name`, the matcher the rest of the
chain already uses. Reach measured on the identical basis before and after — same
production artifacts, same production odds CSVs, same
`_fill_promoted`-then-`_apply_market_anchor` order, same live 7-day horizon.

| join | measure | before | after |
|---|---|---|---|
| fixture → priced event (`attach_market_odds`) | fixtures attached | **66 / 136 (49%)** | **122 / 136 (90%)** |
| fixture → ratings key (`anchor_ratings_to_market`) | team slots resolved | **138 / 214 (64%)** | **214 / 214 (100%)** |

The 14 fixtures still skipped are all `no_name_match` — the same 14 independently
identified as genuinely unpriced by any book. **Nothing was forced.**

### Two things the stage counters exposed that I had not measured

- **`event_id` joined 0 of 136 fixtures.** Every attach came from `exact_pair`
  (66) or the new `fuzzy` stage (56). The id join is not merely unreliable
  across the ESPN/OddsAPI boundary — **it has never once succeeded**, and the
  whole feed has been running on the exact-name fallback.
- The recovery is not evenly spread. `belgian_pro_league` went 1 → 10 of 11
  fixtures and 1 → 8 of 8 team slots; `mls` went 14 → 28 of 28. Leagues whose
  clubs carry sponsor/city prefixes were the ones effectively switched off.

### Refusals are counted, not guessed

A wrong join feeds a wrong market price into a ratings anchor, which is worse
than no join. `_fuzzy_event_for` calls `match_team_name` **once against the full
candidate list per side** (best-of-all-candidates, not first-over-threshold),
requires both sides to resolve, and requires the resolved pair to identify
**exactly one** event. `ambiguous_name_match` and `name_match_pair_disagreed`
are refusals with their own counters. `attach_market_odds` now returns
`by_stage` and `skipped_reasons` so a regression in any single stage is
attributable instead of showing up as one total drifting down.

### Reachability, not just presence

`anchor_ratings_to_market` gained an `audit` **out-parameter** (not a changed
return type — `build_soccer_artifacts.py` is held by another lane and needs no
edit). It reports `teams_resolved` / `teams_unresolved`, which is the number
`teams_changed` at the call site structurally cannot give: an unreachable write
still changes the dict. The end-to-end reproduction that previously read

    teams_changed=2 of 25   |   teams the SIM reads whose rating changed: 0

now reads **`teams_changed=2 of 23` with 2 reaching the sim** — no spurious key,
and the change lands on the entry `loaders._rating_for` resolves.

### Safety of landing this at the current weight

- `_apply_market_anchor` returns **before** calling `anchor_ratings_to_market`
  when `weight <= 0`, so join 2 cannot run in production today.
- The only consumer of a fixture's `market_odds` key anywhere in the repo is the
  anchor itself (grepped across `syndicate/` and `scripts/`), so join 1's extra
  attachments move counters and nothing else while the weight is 0.0.
- `tests/test_soccer_anchor_name_joins.py`: **11 tests, 8 of which fail against
  the pre-fix code**; the 3 that pass both ways are deliberate no-regression
  guards (`off != on` at weight 0, input not mutated, unresolvable team still
  handled). Existing `test_soccer_market_odds.py` + `test_soccer_anchor_wiring.py`:
  22 passed, unchanged.

### And it makes the anchor MORE expensive, which is the honest headline

| | attached fixtures | anchor / 4h | + build | share of the 240 min interval |
|---|---|---|---|---|
| before (half switched off) | 66 | 45.0 min | 143.2 min | 60% |
| **after (working)** | **122** | **83.2 min** | **181.4 min** | **76%** |

Units overrunning their 335 s launch slot: **3 today → 5 with the anchor**, of 42.

**So "make it affordable" and "make it correct" pull in opposite directions, and
correctness came first.** Any cost target set against the old 45 min was a target
for a mechanism that was 49%/64% switched off.

## Path (a): what the solver's cost actually buys

### The bisection's output is quantized to 32 values, and always was

`solve_market_rating_shift` runs `max_iterations=5` bisection steps on
`[-shift_bound, +shift_bound] = [-0.30, +0.30]` and returns the final midpoint.
That is one of exactly **2^5 = 32 lattice points, spaced 0.01875** — an error
floor of **±0.00937 on the shift no matter how many simulations are bought.**
The lattice depends only on `shift_bound` and `max_iterations`; `simulations`
cannot move it.

**This is visible in the validation run that produced the −40%/−51%.**
`data/soccer_source/epl/validation/anchor_2026-07-19.csv` survives, and dividing
its `market_shift_applied` by the weight 0.4 recovers the raw shift:

| match | applied | shift | lattice k | distance from lattice |
|---|---|---|---|---|
| Arsenal v Coventry City | 0.0262 | 0.06550 | 19 | 0.000125 |
| Hull City v Manchester United | −0.0188 | −0.04700 | 13 | 0.000125 |
| Everton v Crystal Palace | 0.0338 | 0.08450 | 20 | 0.000125 |
| Ipswich Town v Sunderland | 0.0037 | 0.00925 | 16 | 0.000125 |
| Nottingham Forest v Leeds | 0.0262 | 0.06550 | 19 | 0.000125 |
| Brentford v Tottenham | −0.0487 | −0.12175 | 9 | 0.000125 |
| Brighton v Aston Villa | 0.0037 | 0.00925 | 16 | 0.000125 |
| Man City v Bournemouth | 0.0563 | 0.14075 | 23 | 0.000125 |
| Newcastle v Liverpool | −0.0487 | −0.12175 | 9 | 0.000125 |
| Fulham v Chelsea | 0.0112 | 0.02800 | 17 | 0.000125 |

Every one lands on the lattice (the 0.000125 is the CSV's 4-dp rounding), using
**7 distinct values out of 32**. Three pairs of fixtures got *byte-identical*
shifts. **So the validated gain was produced by a solver with 0.01875 resolution
and a 7-value output space** — whatever bought that gain, it was not precision
below the lattice, because none was available.

### A methodological correction, recorded because it nearly became a finding

The first control run reported **sd = 0.0000 across 12 "different" seeds** and
would have been written up as "the default solver is deterministic". It is not.
`solve_market_rating_shift(seed=S)` draws seeds `S … S+simulations−1`, so seeds
spaced by 1 share 99 of 100 draws — that was **one draw sampled twelve times**.
Disjoint seeds require spacing ≥ `simulations`; the run below uses 5000.

### Measured: shift error vs solver cost

8 real fixtures (EPL / la_liga / serie_a / bundesliga), real history ratings,
real de-vigged production targets. Reference truth = `p(shift)` on a 13-point
grid at 600 seed-disjoint simulations per point, fitted as a logistic in `shift`
by binomial MLE and inverted. Each estimator run at **6 disjoint seeds**
(spacing 5000). 155,280 match simulations, 63 min on 10 cores.

| setting | sims/solve | mean \|bias\| | **mean seed sd** | **mean RMSE** | worst RMSE |
|---|---|---|---|---|---|
| `100x7` | 700 | 0.0241 | 0.0406 | 0.0491 | 0.1060 |
| **`100x5` ← DEFAULT** | **500** | **0.0238** | **0.0414** | **0.0497** | 0.1054 |
| `100x3` | 300 | 0.0275 | 0.0527 | 0.0606 | 0.1103 |
| `50x5` | 250 | 0.0301 | 0.0609 | 0.0705 | 0.1009 |
| `25x5` | 125 | 0.0330 | 0.0755 | 0.0871 | 0.1284 |
| `12x5` | 60 | 0.0442 | 0.0944 | 0.1110 | 0.1469 |

**Three readings, and the first kills the premise of path (a) as posed.**

1. **The default's own seed-to-seed sd is 0.0414 — 2.2× the 0.01875 lattice
   spacing.** The solver is noise-dominated, not resolution-dominated. The
   "precision" the 500 simulations buy is already swamped.
2. **`100x7` buys nothing.** 40% more compute for RMSE 0.0491 vs 0.0497 — inside
   the noise. Iterations past 5 are pure waste; that knob should never be raised.
3. **But cutting `simulations` is NOT free.** Halving to `50x5` costs +42% RMSE
   (0.0497 → 0.0705); `25x5` costs +75%. It degrades as ~1/√n, exactly as a
   Monte-Carlo estimator should. **Path (a) buys cost at a real accuracy price.**

### The lever that is actually free: skip the bisection

`p_base` — the fixture's unanchored simulated home-win probability — is
**already published in every recommendations artifact** at `simulations: 400`
(`win_probability.home`), better precision than the solver's own 100. With a
single pooled logistic slope, the shift is one division:

    shift = (logit(market_target) - logit(p_base)) / b_pooled

Slope stability across the 8 fixtures: mean **3.696**, sd 0.346, **cv 0.094**.

| estimator | extra simulations | mean \|error\| vs reference |
|---|---|---|
| `100x5` bisection (DEFAULT) | 500 / fixture | 0.0497 |
| **pooled-slope surrogate** | **0** | **0.0221** |

**More than twice as accurate as the 500-simulation default, at zero additional
simulations** — because `p_base` is measured on 400 draws and the slope averages
the whole curve, where the bisection spends its budget on five noisy binary
comparisons and throws away every magnitude it saw.

### THE SURROGATE NUMBER IS IN-SAMPLE AND MUST NOT BE SHIPPED ON IT

`b_pooled` was fitted on the same 8 fixtures it is scored against. This repo's
standing rule is explicit — *DO NOT ship any blend or calibration validated only
in-sample (2 failures on record)* — so **0.0221 is a reason to run the held-out
test, not a result.** Two further caveats, both stated because they cut against
the finding:

- The surrogate's worst case (Inter Milan v Napoli, error −0.0878) is also the
  fixture with the outlier slope (2.851 vs 3.696), the largest fit residual
  (0.0690) and the largest fitted-vs-monotone reference gap (0.0495 vs −0.0180).
  Its reference is the least trustworthy of the eight, so that error is partly a
  statement about my reference rather than about the surrogate.
- **Reference uncertainty is not negligible relative to what is being graded:**
  the fitted-vs-monotone inverse gap averages 0.0267 (max 0.0674) against
  estimator RMSEs of 0.05-0.11. The *ranking* is robust — every arm is graded
  against the same reference — but the absolute numbers carry that band.



## Path (a) on the market that matters: PROPS. It is falsified.

Measured on the production path — `build_soccer_simulation_input` →
`adapter.simulate_props` at the production `simulations=400`, 6 real EPL
fixtures, 315 player rows, weight 0.4, arms differing ONLY in the ratings handed
in. Two quantities, and the ratio between them is the answer:

    D_anchor = |prop(anchored @ full solver) - prop(UNANCHORED)|   <- the whole effect
    D_cheap  = |prop(anchored @ cheap solver) - prop(anchored @ full)|  <- what the cut costs

### First: what the anchor actually does to props

| field | mean \|Δ\| | level | relative | level ratio |
|---|---|---|---|---|
| `anytime_scorer_probability_if_playing` | 0.00348 | 0.0686 | **5.1%** | 0.9941 |
| `expected_shots_if_playing` | 0.01810 | 0.6317 | **2.9%** | 1.0036 |
| `expected_shots_on_target_if_playing` | 0.00919 | 0.2162 | **4.3%** | 0.9960 |
| `h2h` home probability | **0.03583** | — | — | — |

The anchor moves the **h2h line by 3.58 pp** and the props by **2.9–5.1%
relative**. It does move the derivatives coherently — the mechanism claim is
real — but its effect is concentrated in the main line, which is exactly the
market the audit says never to stake.

### Then: the cut destroys more than the mechanism creates

| arm | `expected_shots` D_cheap | D_anchor | **ratio** | sign flips vs full |
|---|---|---|---|---|
| `100x3` | 0.00568 | 0.01810 | 0.31 | 0 of 6 |
| `50x5` | 0.03268 | 0.01810 | **1.81** | 1 of 6 |
| `25x5` | 0.02523 | 0.01810 | **1.39** | 2 of 6 |
| `12x5` | 0.03734 | 0.01810 | **2.06** | 2 of 6 |

**A ratio above 1 means the choice of solver budget changes the published prop
projection MORE than anchoring itself does.** Halving `simulations` does not
degrade the anchor gracefully; it replaces the signal with solver noise. And the
solved shift does not merely lose precision, it **reverses**: at `25x5` and
`12x5`, two of six fixtures get the opposite-signed rating delta from the
full-cost solve.

    full   [-0.011, -0.041, +0.011, +0.026, -0.019, +0.034]
    25x5   [-0.064, -0.011, -0.064, +0.064, -0.019, -0.004]

**Path (a) is dead.** Not "a trade with a price" — at half the budget the cost
lever is louder than the thing it is economising on.

`100x3` looks good here (ratio 0.31, no sign flips) and **must not be read as a
recommendation**: cutting to 3 iterations coarsens the lattice to 8 points at
0.075 spacing, and on these 6 fixtures that coarse grid happened to land near
the full-cost answers. M2 grades the same setting as WORSE on shift RMSE
(0.0606 vs 0.0497). Two measurements disagreeing on n=6 is a reason to trust
neither, not to pick the flattering one.

### The §4.4 interaction, quantified rather than asserted

`shot_calibration`'s divisor (1.3930, re-fit 2026-09-01) was fitted on archived
`expected_shots` produced with the anchor OFF, so arming the anchor makes that
fit stale by whatever the anchor shifts the LEVEL. Measured: **level ratio
1.0036 — a 0.36% shift.** Against the divisor's own documented drift across
training windows (1.244–1.438, roughly ±8%), the anchor's level effect is
**an order of magnitude below the noise the divisor already carries.**

So the §4.4 re-fit is still owed on principle, but it is **not the blocker it
would be if the shift were large** — and that is a measurement, not an
assumption. It should be re-fit after arming, not before, and the honest
statement is that this particular interaction is small.

### A cost cross-check that transfers

The arms' wall-clock is contended (6 processes, 12 cores) and should not be
quoted. What does transfer is structural: the solver spends **500 simulations
per fixture against the props sim's 400** — a ratio of 1.25, independently
corroborated by the production-measured 40.9 s anchor vs 35 s build per fixture
(1.17). Two different routes to "the anchor roughly doubles a soccer unit".

---

## Recommendation

**Do not arm. Do not pursue any of the three paths as posed. The cost problem
was mis-sized and is not the binding constraint; correctness and evidence are.**

### On the three candidate paths

| path | verdict |
|---|---|
| **(a) cut solver simulations** | **FALSIFIED.** At half budget the solver's own noise moves props 1.4–2.1× more than anchoring does, and flips the shift's sign on 2 of 6 fixtures. The one safe trim is capping `max_iterations` at 5 — `100x7` costs 40% more for RMSE 0.0491 vs 0.0497. |
| **(b) anchor only what matters** | **ALREADY IMPLEMENTED.** The builder is single-date; the anchor never saw the forward book. Further scoping to board-reaching fixtures buys 117→58 (50%) and is **circular** — anchoring changes which rows clear the board's filters. |
| **(c) move it off the cycle** | **ALREADY BUILT.** 43 detached subprocess units, one at a time, ~335 s apart, memory-isolated. Nothing to do. |

### What the real cost is

**83.2 min per 4-hour interval** on one core once the joins work (was 45.0 min
while half switched off), against a build already costing 98.2 min — **181.4 of
240 min, 76%**. Memory is not touched. The binding constraint is the per-unit
launch slot: 3 of 42 units already overrun it today, 5 would with the anchor.

### The order that actually unblocks this

1. ~~**Fix both name joins.**~~ **DONE, `1182c3a3`** — reach 66→122 fixtures,
   138→214 team slots. Not deployed, not armed.
2. **Publish the anchor audit into the recommendations artifact.** Today every
   `[soccer_anchor]` line goes to `/dev/null` (§1a), so no production reading of
   this mechanism is possible at all. This gates everything below it.
3. **Validate the pooled-slope surrogate held-out** (fit `b` on one set of
   leagues, score on another). If it holds, the cost question disappears —
   83 min → ~0, using a `p_base` the artifact already publishes. Its in-sample
   0.0221 vs the default's 0.0497 is a reason to run the test, not a result.
4. **Multi-week anchored-vs-base validation on PROPS against OUTCOMES** — not
   h2h against the market. The existing evidence is n=10, one slate, h2h, and
   its own author called it a sensitivity check.
5. Re-fit the shot-shrinkage divisor **after** arming (§4.4; measured
   interaction 0.36%, small).
6. Only then consider a weight > 0.

### The strategic caveat that outranks all of the above

The anchor's measured effect is **3.58 pp on h2h and 2.9–5.1% on props**, and
the staked soccer surface today is **99 board rows / 58 fixtures, 74% h2h, and
ZERO player props**. So the mechanism's largest effect lands on the market the
audit says not to stake, and its smallest effect lands on markets that do not
currently reach the board at all.

**Arming this changes almost nothing about what soccer stakes.** The lever that
would is the one `soccer-board-coverage` already named: give soccer a model view
worth ranking on. Market-anchoring is a candidate input to that work, not a
shortcut around it.

