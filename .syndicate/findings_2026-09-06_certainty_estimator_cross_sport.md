# The certainty defect, and every sport's exposure to it

`[2026-09-06, lane ncaaf-live-resim-wire]`

**The defect.** `live_gameline_join.prob_std_err` computed Agresti-Coull
`(k+2)/(n+4)` for the INTERVAL — deliberately, with a docstring saying Wald is
0.0 at the boundary and that "it is a LIVE case: the re-sim quantises to k/n" —
and then discarded the smoothed value. The raw Wald `k/n` was published as the
POINT estimate. **The correction reached the width and never the centre.**

**Fixed 2026-09-06** for both `k/n` paths in that module (`price_moneyline`
sim_count rows, `price_distribution_market`). The `analytic_calibration` branch
is deliberately excluded — it is not a count.

---

## What each sport actually does. MEASURED unless marked.

| sport | estimator | n | can it reach exactly 0/1 | reached by the fix |
|---|---|---|---|---|
| **MLB** | `k/n` live re-sim | 120 | **YES — and did** | yes |
| **NCAAF** | `k/n` live re-sim | 120 | **YES — and did** | yes |
| **soccer** | `k/n` live re-sim | 300–400 | **YES, most exposed of all** | priced path only |
| **NFL** | `k/n` smartsim2 | 300 | not today; **YES after the units fix** | yes |
| **NHL** | `k/n` hockeysim | 20,000 | in principle; ~never in practice | **NO — own artifact path** |
| **NBA / WNBA** | logistic on `margin_mean` | n/a | **NO — structurally immune** | n/a (different defects) |

### MLB — measured, and it cost money
Production live-gameline ledger, 6 days to 2026-09-06, 2,810 h2h records
carrying a model probability. Export was `truncated: True`, so these are FLOORS:

    exactly 0.0 or 1.0   83 (2.95%)     priced   59     distinct games   25
    23 hit, **2 LOST**
      2026-08-29  ARI 2 @ SF  7   p=0.0, home won   max |edge_pp| 46.2
      2026-08-29  BOS 2 @ NYY 9   p=0.0, home won   max |edge_pp| 55.9

An exact 0.0 that loses has no recovery: Brier takes its 1.0 ceiling, log loss
is infinite. 23-of-25 being right is not a defence.

### NCAAF — measured on live production state, today
WSU @ WASH, 2026-09-06, collected end-to-end (111 samples, `b6jbd58h8`):
`P = 1.0` published for the final **ten minutes** of a real game, and the series
quantises visibly at 1/120 (`0.991667` = 119/120). Final WSU 10 – WASH 24, so
this certainty HIT. The two MLB rows that lost looked exactly like it at the
time — which is the whole point.

### soccer — STRUCTURALLY THE MOST EXPOSED, and only half covered
`soccer/features/live_lens.py:289` → `home_win_probability = round(home_wins/n, 4)`,
`simulations: int = 300` (400 on the 2026-08-21 artifacts, per
`soccer_live_gameline_source.py:28`). Raw Wald `k/n`.

Why it is worse here than anywhere else: **soccer has draws and low scoring**, so
a three-goal lead at 88' genuinely returns 300/300. Baseball and football need a
full comeback to be ruled out; soccer does not.

`[REVISED after tracing every consumer. The first draft called the uncovered
fields a lens/display concern. Too soft: one of them is used to PRICE. The
covered half is also wider than the draft said.]`

**COVERED, more than first stated.** Three of soccer's four pricing paths run
through the module the fix landed in:

  * `home_win_prob` -> `price_moneyline` (sim_count) — smoothed.
  * totals and spreads at ANY line -> `price_distribution_market`, off
    `total_runs_dist` / `margin_dist`, which
    `soccer_live_gameline_source._histograms_from_scorelines` derives from the
    resumed sim's own scoreline distribution — smoothed.
  * the ONE analytic over-2.5 line -> `price_analytic_line_market`, which needs
    a measured calibration error. Soccer is in NEITHER
    `ANALYTIC_LIVE_STD_ERR_BY_SPORT` nor `..._BY_MARKET`, so it refuses with
    `REASON_ANALYTIC_UNCALIBRATED` and publishes nothing. Correctly excluded
    from smoothing — there is no output to smooth.

`[CORRECTED 2026-09-07 by lane `soccer-threeway-precision-gate`, which did the
work and measured it. FOUR corrections to what follows, three of which make my
account WRONG rather than merely incomplete. Verified here before accepting.]`

1. **THE HOME LEG WAS ALREADY COVERED for certainty; I overstated the exposure.**
   `attach_soccer_projections` calls `probability_refusal.refuse_published_certainty`
   at `soccer_projections.py:1276`, one line after pricing. It blanks a
   `model_prob_over` of exactly 0.0/1.0 and clears the derived edge -- and it
   reads `model_prob_over` and NOTHING ELSE. So **only draw and away were
   exposed**, and the home leg's real defect was the missing INTERVAL, not the
   certainty. The vector below lists `home` alongside them, which reads as
   three exposed legs. It was two.
2. **The blocker was much smaller than I recorded.** `n` never had to be plumbed
   from `live_lens.py`: `soccer/adapters.py:119` already writes
   `"simulations": distribution.simulations` onto every pregame match output, so
   `match.get("simulations")` was in hand at the pricing point all along. One
   assignment, not a cross-module plumb. My "cross-module change to the live
   board" framing was the reason I deferred it, and it was wrong.
3. **n is 400, not the 300 in the signature.** Measured, not read: all 114
   `win_probability` values served by `/soccer/*/api/cards` are exact multiples
   of 1/400 and no smaller n fits. Infer n from quantisation; the default in the
   signature is not what production runs.
4. **`_MODEL_EDGE_MAX_POINTS = 15.0` was hiding the worst cases, which is why
   this survived so long.** A `0/400` leg against a 0.16 fair reads -16.0pp and
   is dropped by the CAP -- never by a certainty rule. So the extreme end looked
   handled while everything between the bar and the cap published freely. A
   guard that silently absorbs the most alarming cases is worse than none: it
   removes the evidence that would have prompted a fix.

**MEASURED COST OF THE FIX**, far larger than the NCAAF 2-of-10 I predicted. On
`/api/board/layer2-shortlist?sport=soccer`: 59 moneyline rows, 28 carrying a
model edge, **17 of 28 (61%) newly withheld**. `[SPLIT RETRACTED 2026-09-07 by
the lane that measured it: the "8 home / 9 away / 0 draw" breakdown CONFLATES TWO
MECHANISMS and must not be cited. `_model_edge_for` opens with
`if edge is None: return _modelled_fair_edge_for(...)`, an early return written
for a ONE-SIDED QUOTE. The new gate writes `edge_vs_market_pct = None` for a
DIFFERENT state -- priced and withheld as imprecise -- and the two are
indistinguishable at that line, so withholding the HOME leg silently drops the
DRAW and AWAY legs before their own bars are ever consulted (3 of 10 legs on a
09-07 sample). Not a safety hole -- `_modelled_fair_edge_for` is side-matched and
returns None rather than an ungated number -- but the per-side counts measure the
early return as much as the gate. The 17/28 TOTAL stands; the split does not.
This is the same shape as `ANALYTIC_UNCALIBRATED` and as "unknown must not
default permissive": ONE FIELD CARRYING TWO STATES, with the consumer branching
as if it carried one.]` The 2σ
bar at n=400 is 4.00pp at p=0.20 and 4.98pp at p=0.50, and soccer disagreements
are usually smaller than that. **The estimator shift was negligible (mean
+0.03pp): the GATE does all the work.** Do not attribute the drop to
Agresti-Coull. Shipped on those numbers by user decision.

LANDED: `6a20281c` (home leg) and `8b6a1f4d` (draw/away), both on `origin/main`,
both routing through `price_moneyline` rather than reimplementing the gate.

**NOT COVERED, AND IT IS A PRICING PATH, NOT A DISPLAY ONE.** `layer2_board`
(`_model_edge_for`, ~1513, and its sibling at ~1589) builds a three-way vector

    {"home": model_prob_over, "draw": draw_probability, "away": away_probability}

and prices the row's side against the market fair probability **directly**.
`draw_probability` and `away_probability` are raw `k/n` from
`soccer/features/live_lens.py:289-296` at n=300-400. This path never calls
`price_moneyline`, so on the soccer three-way market there is:

    no Agresti-Coull centre    no prob_std_err    NO PRECISION GATE AT ALL

A draw leg of `0/300` is ordinary late in a match — likelier than a certainty in
baseball or football, because the draw becomes a genuinely narrow outcome the
moment a second goal separates the sides. **So this is the one place left in the
platform where a raw certainty can still be PRICED, and it is also the market
where certainty is easiest to reach.**

Two defects stacked, not one: the estimator (fixed everywhere else) and the
missing gate (never present here). The gate is the larger.

**WHY IT WAS NOT FIXED IN THIS PASS.** The sim count is not available at the
pricing point. `soccer_projections._probability_projection` returns
`{model_prob_over, side, basis, source}` and `soccer_projections.py` contains no
`simulations` / `sims_run` anywhere, so `n` must be plumbed from the soccer
artifact through the projection dict into `layer2_board` before EITHER defect can
be addressed. That is a cross-module change to the live board; it wants its own
lane and its own measurement, not a rushed edit during a slate with three games
in play and a deploy pending.

Still raw and genuinely display-only, for completeness:
`over_2_5_probability`, `both_teams_scored_probability`.

### NFL — not exposed TODAY, and that is exactly why order matters
Measured by `nfl-rating-units`: across-game `margin_mean` stdev **2.16**, 0 of 14
games at 0.0/1.0, 93.8% of games inside p ∈ [0.35, 0.65]. NFL cannot reach the
boundary because its ratings are per-play EPA and the model barely differentiates
teams at all.

The units fix takes that stdev to **11.44**. A model that differentiates will
eventually return 300/300. **Shipping the scale before the estimator would have
INTRODUCED this defect to the one sport that did not have it.** That is the
ordering, and it is why the estimator landed first.

### NHL — same estimator family, 167× the samples, AND OUT OF REACH OF THE FIX
`nhl/sim_engine/hockeysim/game_market_sim.py:159,259` →
`p_home_ml = (wins_h + 0.5*draws) / n`, `_DEFAULT_GAME_SIMS = 20000`.

Two things, and the second is the one that matters:

1. At n=20,000 an exact 0/1 needs 20,000 identical outcomes. Git-mirror scan:
   **55 h2h rows, 0 exactly 0/1.** State the denominator honestly — 55 rows on a
   mirror that is lossy by design is a **weak null, not a clearance.**
2. **NHL is REFUSED by name, and its edges come from somewhere else entirely.**

   `[CORRECTED after first writing. The first version of this section said NHL
   "does not go through live_gameline_join at all" and inferred that from its
   absence in two tables. Wrong mechanism, and the wrong reader would have gone
   looking in the wrong module. The conclusion — the fix does not reach NHL —
   survives; the reason does not.]`

   `run_refresh_worker.py:5647` builds a book grid for **all eight sports**, and
   `book_grid_artifact.py:318` calls `attach_live_gamelines_for_sport` for each.
   So NHL IS called. It then fails closed at
   `board_enrichment.py:1621` — `_LIVE_GAMELINE_SPORTS = {"mlb", "wnba",
   "soccer", "ncaaf"}` — returning
   `{"supported": False, "reason": "no live re-sim wired for nhl"}` **before**
   `price_moneyline` is ever reached. Fails closed and says so, which is the
   behaviour you want. **NHL therefore publishes ZERO live gameline edges.**
   The same is true of NBA, NFL and NCAAB.

   NHL's actual recommendations come from `hockeysim/artifacts.py:190-217`,
   a separate path emitting `{market, side, price, ev, prob, conf}` rows.
   **That path has no interval and no precision gate** — grep for
   `std_err|sigma|interval|priceable|precision` across `hockeysim/` returns only
   engine-internal usage noise. So "NHL prices with no interval requirement" is
   TRUE, but of the hockeysim recommendation path, not of the join.

   And on that path, `conf` is defined as `max(0.0, prob - 0.5)` — **distance
   from a coin flip, which is not a confidence measure at all.** A `k/n` at
   n=20,000 has a genuinely tight interval; the defect is that nothing computes
   or requires it, and a field named `conf` implies otherwise.

---

## NBA / WNBA — immune to THIS, and carrying their own. `[user: note for later]`

`nba/cards.py:1520` and `wnba/cards.py:957` are the same function:
`_margin_win_prob(margin_mean, scale=3.4)` = `1/(1+exp(-margin/scale))`.
Continuous, so it never reaches 0 or 1. **Genuinely immune, confirmed in code.**

It was not adopted for the `k/n` sports for three reasons, recorded in
`agresti_coull_point`'s docstring: it reads only `margin_mean` and discards the
distribution (a downgrade precisely where a LIVE re-sim earns its keep); `3.4` is
a fitted BASKETBALL scale and a logistic tail is THIN, so in the tails it could
come out MORE confident; and the immunity was not free — no sim count meant no
interval, so those sports were refused `REASON_UNUSABLE_SIMS` outright until
`#481` gave WNBA a measured calibration error.

### What they owe, ranked. FITTED vs NOT is the whole distinction.

**FITTED, leave alone:**
- WNBA live win — `#481`, `_WNBA_LIVE_MARGIN_SCALE = 2.1`, refit on 212 games /
  73,878 samples, game-level train/test, test Brier 0.1922 → 0.1661.
- WNBA live totals — `#499`, 249 games / 23,712 samples, 0.1744 → 0.1477.

**NOT FITTED — every one a hard-coded constant applied uniformly to every game:**
- `scale=6.5` — pregame full-game win (`nba/cards.py:2077`, `wnba/cards.py:2011`)
- `scale=7.5` — spread (`wnba/cards.py:1071` calls it "a CONSTANT" in its own comment)
- `scale=10.5` — pregame totals (`nba:2086`, `wnba:2076`)
- `scale=3.4` — the default, used for per-period `p_home_win`
  (`nba:1566,1589,1621`, `wnba:1474,1497,1529,2162`).
  `refresh_wnba_oddsapi_props.py:3068` already flags it: "applies scale=3.4
  uniformly to every game".

**NBA specifically has no `#481`-equivalent at all.** WNBA's live transform was
graded against outcomes and refit; NBA's was not.

`[SETTLED — this was left open in the first draft and is now answered, so nobody
repeats the grep.]` NBA reaches `attach_live_gamelines_for_sport` (the worker
builds a book grid for all eight sports, `run_refresh_worker.py:5647`) and fails
closed there on `_LIVE_GAMELINE_SPORTS`, which holds only
`{mlb, wnba, soccer, ncaaf}`. **NBA publishes zero live gameline edges**, refused
by name with `"no live re-sim wired for nba"` — never reaching `price_moneyline`,
so its absence from `ANALYTIC_LIVE_STD_ERR_BY_SPORT` never comes into play. The
unfitted scale constants below are therefore a PREGAME-path problem for NBA,
not a live-pricing one.

### The honest framing of the NBA/WNBA work
This is a **mechanism** change, not an estimator fix, so per
`model_engine_standard.md` it needs a re-fit and a held-out backtest, not a
constant swap. `#481` and `#499` are the template: replay cached play-by-play
through the real function, split by GAME, score on Brier against outcomes.

---

## Also found, not chased

- **`football/adapters.py:152`** —
  `home_win_probability = max(0.05, min(0.95, 0.5 + margin/28.0))`. A **clamped
  linear ramp**, not a probability model: every margin ≥ +14 is 0.95 and every
  margin ≤ −14 is 0.05. Clamping means it cannot hit 0/1, so it is not this
  defect — but a linear map is cruder than either the logistic or `k/n`.
  `[SETTLED — the draft left this open; it is now answered, so nobody re-runs
  the grep.]` **NOT on the board path, so not a live pricing defect.** The only
  instantiation outside `features/football/` is
  `scripts/football_sim_input_checklist.py:349`. Every board and projection
  import reaches `football.sim_engine.smartsim2.*` DIRECTLY (`ncaaf/cards.py:28`,
  `ncaaf/live_resim.py:98-102`, `ncaaf/game_projections.py:252`,
  `ncaaf/sources.py:275`, the `smartsim2_projection` shims) and never touches
  `FootballSimulationAdapter`. Importing a smartsim2 submodule does execute
  `football/sim_engine/__init__.py`, which imports the adapter — so it is
  reachable BY IMPORT and never CALLED. Presence is not reachability, in the
  direction that favours us for once.

  Worth one line anyway: the ramp lives in the tooling that VALIDATES the real
  engine, so the input checklist carries a notion of win probability the engine
  does not share. Not money, but a checklist that disagrees with its subject is
  a poor oracle.

- **The test suite writes into git-tracked `data/**`.** Running the sweep
  truncated
  `data/mlb_source/source_artifacts/data/live_lens/live_lens_2026_06_02.jsonl`
  from 20 lines to 1 and appended a fresh row stamped with the run time. Harmless
  content here (all 20 were identical `games: []` degraded records), and
  `discard-guard` caught the restore correctly. But a suite that mutates tracked
  artifacts will eventually be blamed for a mirror diff nobody authored.
