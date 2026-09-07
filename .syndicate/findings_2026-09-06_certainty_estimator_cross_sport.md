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

**Covered:** `home_win_prob` reaches `price_moneyline` via
`soccer_live_gameline_source`, so the PRICED number is now smoothed.

**NOT covered — still raw `k/n` on the lens artifact, read by display and other
consumers:** `draw_probability`, `away_win_probability`,
`over_2_5_probability`, `both_teams_scored_probability` (all at
`live_lens.py:289-296`). These never pass through the join, so nothing smooths
them and nothing gates them on an interval.

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
  **REACHABILITY UNKNOWN.** Its importers are lift-analysis, season-validation
  and a `sim_engine` package, none obviously on the board path, and the NFL board
  uses smartsim2 instead. One check settles whether it is live.

- **The test suite writes into git-tracked `data/**`.** Running the sweep
  truncated
  `data/mlb_source/source_artifacts/data/live_lens/live_lens_2026_06_02.jsonl`
  from 20 lines to 1 and appended a fresh row stamped with the run time. Harmless
  content here (all 20 were identical `games: []` degraded records), and
  `discard-guard` caught the restore correctly. But a suite that mutates tracked
  artifacts will eventually be blamed for a mirror diff nobody authored.
